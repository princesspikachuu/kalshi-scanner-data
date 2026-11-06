#!/usr/bin/env python3
"""Production-data shadow trading and deterministic event replay. Never sends exchange orders."""
import argparse
import asyncio
from datetime import datetime
from decimal import Decimal as D
import json
import logging
import os
from pathlib import Path
import re
import signal
import sys
import time

import requests
from websockets.asyncio.client import connect
from .auth import Signer
from services.paper_demo.read_budget import PRODUCTION_READS
from .core import Audit, ConvexityStrategy, Engine, FeePolicy, StrategyFleet

LOG = logging.getLogger('shadow')
BASE = 'https://external-api.kalshi.com/trade-api/v2'
WS = 'wss://external-api-ws.kalshi.com/trade-api/ws/v2'
COINBASE = 'wss://ws-feed.exchange.coinbase.com'


def ts(value):
    return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()


class ProductionData:
    """Only three public GET routes are allowed. No account/order endpoints or mutation verb."""
    def get(self, path: str, params=None):
        if not (path in ('/markets', '/series/KXBTC15M') or
                re.fullmatch(r'/markets/KX[A-Z0-9]+15M-[A-Za-z0-9-]+', path) or
                re.fullmatch(r'/series/KX[A-Z0-9]+15M', path)):
            raise ValueError('Data client route not allowed')
        # No shared requests.Session across threads. Connection setup isn't in the execution path.
        PRODUCTION_READS.wait()
        with requests.Session() as session:
            session.trust_env = False
            response = session.get(BASE+path, params=params, timeout=(2,5), allow_redirects=False)
            if response.status_code==429:PRODUCTION_READS.reject()
            if response.status_code != 200:
                raise RuntimeError(f'Public data HTTP {response.status_code}')
            return response.json()

    async def fetch(self, path, params=None):
        return await asyncio.to_thread(self.get, path, params)


class ForwardRun:
    def __init__(self, args):
        self.args = args
        self.audit = Audit(args.output)
        self.engine = Engine(self.audit, cash=args.cash, latency_ms=args.latency_ms,
                             seed=args.seed, toxic_fill_probability=args.toxic_probability)
        self.profiles = json.loads(Path(__file__).with_name('market_profiles.json').read_text())
        if args.series:
            chosen=set(args.series.split(','))
            self.profiles=[p for p in self.profiles if p['series'] in chosen]
            if chosen != {p['series'] for p in self.profiles}:
                raise ValueError('Unknown series selected')
        self.profiles=[dict(p, contracts=args.contracts) for p in self.profiles]
        self.strategy = StrategyFleet(self.engine, self.profiles)
        self.api = ProductionData()
        self.signer = Signer(os.environ['KALSHI_API_KEY_ID'],
                            Path(os.environ['KALSHI_PRIVATE_KEY_PATH']).read_bytes())
        self.queue = asyncio.Queue(maxsize=20000)
        self.done = asyncio.Event()
        self.selected = {}
        self.raw = open(Path(args.output)/'capture.jsonl', 'x')
        self.config = dict(cash=args.cash, latency_ms=args.latency_ms, seed=args.seed,
                           toxic_probability=args.toxic_probability, contracts=args.contracts, profiles=self.profiles)
        self.raw.write(json.dumps({'source':'config','payload':self.config,'time':0})+'\n')
        (Path(args.output)/'run_config.json').write_text(json.dumps(self.config,indent=2))
        self.refill_offset = 0

    async def put(self, source, payload):
        # Consumer assigns the simulation clock and records exact processing order.
        await self.queue.put((source, payload, time.time()))

    async def fee_policy(self,market,metadata):
        return FeePolicy.from_series(metadata)

    async def settlement_observed(self,ticker):
        return ticker in self.engine.settled

    async def discover(self):
        while not self.done.is_set():
            try:
                for series, ticker in list(self.selected.items()):
                    if await self.settlement_observed(ticker):
                        market = (await self.api.fetch('/markets/'+ticker))['market']
                        if market['status'] in ('finalized','settled') and market.get('result') in ('yes','no'):
                            await self.put('settlement', dict(ticker=ticker,
                                yes_payout='1' if market['result']=='yes' else '0'))
                            while not self.engine.markets[ticker].get('paid'):
                                await asyncio.sleep(.02)
                            self.selected.pop(series, None)
                wanted={p['series']:p for p in self.profiles if p['series'] not in self.selected}
                if wanted:
                    now=time.time()
                    rows, cursor, seen=[], '', set()
                    for _ in range(20):
                        result=await self.api.fetch('/markets',dict(status='open',
                            min_close_ts=int(now),max_close_ts=int(now+900),limit=1000,cursor=cursor))
                        rows.extend(result['markets'])
                        cursor=result.get('cursor','')
                        if not cursor:
                            break
                        if cursor in seen:
                            raise ValueError('Repeated discovery cursor')
                        seen.add(cursor)
                    else:
                        raise ValueError('Market discovery capacity reached')
                    for profile in self.profiles:
                        series=profile['series']
                        if series not in wanted:
                            continue
                        candidates=[m for m in rows if m['ticker'].startswith(series+'-') and
                            m['status']=='active' and ts(m['open_time'])<=now and
                            0<ts(m['close_time'])-now<=900 and m['ticker'] not in self.engine.markets]
                        if not candidates:
                            continue
                        market=min(candidates,key=lambda m:ts(m['close_time']))
                        try:
                            metadata=(await self.api.fetch('/series/'+series))['series']
                            fee=await self.fee_policy(market,metadata)
                        except (ValueError,RuntimeError):
                            LOG.warning('Market %s waiting for verified fee metadata',series)
                            continue
                        normalized=dict(ticker=market['ticker'],close=ts(market['close_time']),
                            open=ts(market['open_time']),event_ticker=market['event_ticker'],
                            bot_id=profile['id'],bot_name=profile['name'],
                            strategy_version=profile['version'],fee_type=metadata['fee_type'],
                            fee_multiplier=str(metadata['fee_multiplier']))
                        self.selected[series]=market['ticker']
                        await self.put('market',dict(market=normalized,
                            taker_multiplier=str(fee.taker_multiplier),maker_multiplier=str(fee.maker_multiplier)))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOG.error('DISCOVERY_OR_SETTLEMENT %s: %s',type(exc).__name__,str(exc))
                await self.put('gap',{'reason':'discovery/fee/settlement metadata failed'})
            await asyncio.sleep(2)

    async def kalshi(self):
        delay = .25
        while not self.done.is_set():
            try:
                async with connect(WS, additional_headers=self.signer.headers('GET','/trade-api/ws/v2'),
                                   ping_interval=10, ping_timeout=5, max_queue=2048,
                                   open_timeout=5, max_size=2**22) as ws:
                    await ws.send(json.dumps(dict(id=1, cmd='subscribe',
                        params=dict(channels=['market_lifecycle_v2']))))
                    subscribed, ident = set(), 2
                    book_sid=trade_sid=None
                    last_snapshot_request = 0.0
                    connected_at = time.monotonic()
                    while not self.done.is_set():
                        # Keep lifecycle subscription across rolls to avoid missing settlement events.
                        desired={t for t in self.selected.values() if t in self.engine.markets}
                        additions=desired-subscribed
                        removals=subscribed-desired
                        if removals and book_sid is not None and trade_sid is not None:
                            for sid in (book_sid,trade_sid):
                                await ws.send(json.dumps(dict(id=ident,cmd='update_subscription',params=dict(
                                    sid=sid,market_tickers=sorted(removals),action='delete_markets'))))
                                ident+=1
                            subscribed-=removals
                        if additions and (not subscribed or (book_sid is not None and trade_sid is not None)):
                            for channel,sid in (('orderbook_delta',book_sid),('trade',trade_sid)):
                                if sid is None:
                                    command=dict(id=ident,cmd='subscribe',params=dict(
                                        channels=[channel],market_tickers=sorted(additions)))
                                else:
                                    command=dict(id=ident,cmd='update_subscription',params=dict(
                                        sid=sid,market_tickers=sorted(additions),action='add_markets'))
                                await ws.send(json.dumps(command))
                                ident+=1
                            subscribed.update(additions)
                        if book_sid is not None and time.time()-last_snapshot_request>1:
                            invalid=[(t,self.engine.books[t]) for t in desired if not self.engine.books[t].valid
                                     and self.engine.books[t].sid == book_sid]
                            if invalid:
                                await ws.send(json.dumps(dict(id=ident,cmd='update_subscription',params=dict(
                                    sid=book_sid,market_tickers=[t for t,b in invalid],action='get_snapshot'))))
                                ident+=1
                                last_snapshot_request=time.time()
                        try:
                            event = json.loads(await asyncio.wait_for(ws.recv(), .5))
                        except TimeoutError:
                            continue
                        if event.get('type')=='subscribed':
                            if event.get('msg',{}).get('channel')=='orderbook_delta':book_sid=event['msg']['sid']
                            if event.get('msg',{}).get('channel')=='trade':trade_sid=event['msg']['sid']
                        if event.get('type') == 'error':
                            code=event.get('msg',{}).get('code')
                            raise ValueError(f'Kalshi subscription rejected: code={code} request={event.get("id")}')
                        await self.put('kalshi', event)
                        if time.monotonic()-connected_at>=30:delay=.25
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                reason=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
                LOG.warning('KALSHI_DISCONNECTED %s', reason)
            finally:
                if not self.done.is_set():
                    await self.put('gap', {'reason':'Kalshi stream disconnected; resnapshot required'})
            await asyncio.sleep(delay)
            delay = min(5, delay*2)

    async def spot(self):
        delay = .25
        while not self.done.is_set():
            try:
                async with connect(COINBASE, ping_interval=10, ping_timeout=5, open_timeout=5) as ws:
                    await ws.send(json.dumps(dict(type='subscribe', product_ids=['BTC-USD'],
                                                 channels=['matches','heartbeat'])))
                    connected_at = time.monotonic()
                    async for raw in ws:
                        event = json.loads(raw)
                        if event.get('type')=='error':
                            raise ValueError('Coinbase subscription error')
                        if time.monotonic()-connected_at>=30:delay=.25
                        if event.get('type')=='match' and event.get('product_id')=='BTC-USD':
                            await self.put('spot', dict(price=event['price'], event_time=ts(event['time'])))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOG.warning('SPOT_DISCONNECTED %s', type(exc).__name__)
            finally:
                if not self.done.is_set():
                    await self.put('gap', {'reason':'spot stream disconnected'})
            await asyncio.sleep(delay)
            delay = min(5, delay*2)

    async def clock(self):
        while not self.done.is_set():
            await self.put('clock', {})
            path = Path(self.args.output)/'refills.jsonl'
            if path.exists():
                with path.open() as f:
                    f.seek(self.refill_offset)
                    while True:
                        before = f.tell()
                        line = f.readline()
                        if not line.endswith('\n'):
                            self.refill_offset = before
                            break
                        self.refill_offset = f.tell()
                        await self.put('refill', json.loads(line))
            await asyncio.sleep(.05)

    def reject_input(self,source,payload,exc):
        # Never turn a malformed book for one market into 28 unrelated errors.
        # No raw payloads, authentication headers, or provider bodies enter logs.
        known={'stale book event','book sequence gap','negative depth',
               'invalid binary book level','crossed complementary book',
               'invalid/stale spot','non-monotonic replay clock',
               'settlement requires prior explicit WS settled event'}
        reason=str(exc) if str(exc) in known else 'malformed '+source+' event'
        ticker=payload.get('msg',{}).get('market_ticker') if source=='kalshi' else payload.get('ticker')
        self.input_rejections=getattr(self,'input_rejections',0)+1
        if not hasattr(self,'rejection_logs'):self.rejection_logs={}
        key=(source,ticker,reason);at=time.monotonic()
        if at-self.rejection_logs.get(key,-1e9)>=5:
            self.rejection_logs[key]=at
            LOG.warning('SIMULATION_INPUT_REJECTED source=%s ticker=%s reason=%s count=%s',
                        source,ticker,reason,self.input_rejections)
        if ticker in self.engine.books:
            self.engine.data_gap(ticker,reason)
        else:
            if source=='spot':self.engine.spot=type(self.engine.spot)()
            for affected in self.engine.books:
                if affected not in self.engine.settled:self.engine.data_gap(affected,reason)

    async def consume(self):
        last_at = 0
        while not self.done.is_set():
            source, payload, received = await self.queue.get()
            # Preserve receipt order; wall-clock regressions are not silently transformed into a new market clock.
            now = max(received, last_at)
            if received < last_at-.01:
                source, payload = 'gap', {'reason':'local clock regressed'}
            last_at = now
            record = dict(source=source, payload=payload, time=now)
            self.raw.write(json.dumps(record)+'\n')
            self.raw.flush()
            try:
                self.engine.handle(source, payload, now)
            except ValueError as exc:
                self.reject_input(source,payload,exc)
            self.queue.task_done()

    async def run(self):
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self.done.set)
        workers = [asyncio.create_task(c) for c in (self.discover(),self.kalshi(),self.spot(),
                                                   self.clock(),self.consume())]
        stopper = asyncio.create_task(self.done.wait())
        try:
            completed, _ = await asyncio.wait([*workers,stopper], return_when=asyncio.FIRST_COMPLETED)
            for task in completed:
                if task is not stopper:
                    task.result()
        finally:
            self.done.set()
            for task in workers+[stopper]:
                task.cancel()
            await asyncio.gather(*workers,stopper,return_exceptions=True)
            for ticker in self.engine.markets:
                self.engine.report(ticker, final=self.engine.markets[ticker].get('paid',False))
            self.raw.close()
            self.audit.close()


def replay(args):
    with open(args.capture) as f:
        config_record = json.loads(next(f))
        if config_record['source'] != 'config':
            raise ValueError('capture must start with configuration')
        config = config_record['payload']
        audit = Audit(args.output)
        engine = Engine(audit, cash=config['cash'], latency_ms=args.latency_ms if args.latency_ms is not None
                        else config['latency_ms'], seed=args.seed if args.seed is not None else config['seed'],
                        toxic_fill_probability=args.toxic_probability if args.toxic_probability is not None
                        else config['toxic_probability'])
        StrategyFleet(engine,config['profiles']) if config.get('profiles') else ConvexityStrategy(engine, config['contracts'])
        (Path(args.output)/'run_config.json').write_text(json.dumps(dict(config,
            latency_ms=engine.latency*1000, toxic_probability=engine.toxic_probability,
            seed=args.seed if args.seed is not None else config['seed'], capture=str(args.capture)),indent=2))
        try:
            for line in f:
                record = json.loads(line)
                try:
                    engine.handle(record['source'],record['payload'],record['time'])
                except ValueError:
                    for ticker in engine.books:
                        if ticker not in engine.settled:
                            engine.data_gap(ticker, 'invalid recorded input')
            # Do not advance beyond recorded data or settle unresolved positions by guessing.
            for ticker in engine.markets:
                engine.report(ticker, final=engine.markets[ticker].get('paid',False))
        finally:
            audit.close()


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode',required=True)
    live = sub.add_parser('live', help='Forward-test with production public market data; virtual orders only')
    live.add_argument('--cash',default='1000')
    live.add_argument('--series',help='Optional comma-separated subset; default is all 28 saved market families')
    live.add_argument('--contracts',type=int,default=100)
    live.add_argument('--latency-ms',type=float,default=150)
    live.add_argument('--seed',type=int,default=7)
    live.add_argument('--toxic-probability',type=float,default=.35)
    live.add_argument('--output',required=True)
    back = sub.add_parser('replay',help='Replay recorded L2 + trades + spot, without any network connection')
    back.add_argument('capture')
    back.add_argument('--output',required=True)
    back.add_argument('--latency-ms',type=float)
    back.add_argument('--seed',type=int)
    back.add_argument('--toxic-probability',type=float)
    refill = sub.add_parser('refill',help='Add virtual funds to a running forward test')
    refill.add_argument('--output',required=True)
    refill.add_argument('--amount',required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    if args.mode=='refill':
        amount = D(args.amount)
        if not amount.is_finite() or amount<=0:
            parser.error('refill must be positive')
        if not (Path(args.output)/'ledger.sqlite3').exists():
            parser.error('choose an existing running forward-test directory')
        fd = os.open(Path(args.output)/'refills.jsonl', os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
        try:
            os.write(fd,(json.dumps({'amount':str(amount)})+'\n').encode())
            os.fsync(fd)
        finally:
            os.close(fd)
        print('Virtual refill queued; no exchange funds moved.')
    elif args.mode=='replay':
        replay(args)
    else:
        if not 1 <= args.contracts <= 10000:
            parser.error('contracts must be 1..10000')
        print('SHADOW ONLY — production data; no real orders, balances, or fund transfers.')
        asyncio.run(ForwardRun(args).run())


if __name__=='__main__':
    main()
