"""Single read-only Kalshi streaming lane, isolated from historical replay.

Discovery shares ReadBudget with collection. WebSocket buffers, watched markets,
commands, REST cadence, retry delay, ledger state and database pools are bounded.
"""
import json,re,time,random,logging
from datetime import datetime
from services.research.kalshi import KalshiInventory,parse_json
from services.research.inventory import ProviderFailure
from services.research.queue import LeaseLost
from .live import MAX_MARKETS,lifecycle
from .live_store import LiveStore

LOG=logging.getLogger(__name__)
WS_URL='wss://external-api-ws.kalshi.com/trade-api/ws/v2'
WS_PATH='/trade-api/ws/v2'


def metadata(raw):
    ticker=raw.get('ticker');event=raw.get('event_ticker')
    if not isinstance(ticker,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,256}',ticker):return None
    if not isinstance(event,str) or not 1<=len(event)<=256:return None
    try:
        close=datetime.fromisoformat(raw['close_time'].replace('Z','+00:00'))
        if close.tzinfo is None:return None
        close=close.timestamp()
    except (KeyError,ValueError,TypeError):return None
    return dict(ticker=ticker,event=event,series=raw.get('series_ticker') or ticker.split('-')[0],
        close=close,status=raw.get('status','unknown'),result=raw.get('result',''))


class Reconnect(Exception):pass


class LiveFeed:
    def __init__(self,pool,budget,signer,stop,*,clock=time.time,connector=None):
        self.store=LiveStore(pool);self.budget=budget;self.signer=signer;self.stop=stop
        self.clock=clock;self.connector=connector;self.watch_limit=MAX_MARKETS
        self.reads=0;self.reconnects=0;self.last_health=0

    def health(self,status):
        now=self.clock()
        if now-self.last_health>=15:
            self.store.health(now,status);self.last_health=now

    def discover(self,provider,strategies,state,catalog,cursors,step):
        """At most one bounded REST page per call; caller spaces calls by 2s."""
        now=self.clock();series=sorted({series for s in strategies for series in s['series']})
        pending=sorted({p['ticker'] for p in state['positions']}|{o['ticker'] for o in state['orders']})
        # Pending outcomes take one slot every ten calls; reads are batched.
        if pending and (step%10==0 or state['stopping']):
            args=dict(tickers=','.join(pending[:100]),limit=1000)
            current=None
        else:
            current=series[step%len(series)]
            args=dict(series_ticker=current,status='open',min_close_ts=int(now),max_close_ts=int(now+86400),limit=1000)
            if cursors.get(current):args['cursor']=cursors[current]
        wait=self.budget.take(1)
        if wait:return max(2,wait),'sharing read allowance with collection'
        self.reads+=1
        try:
            page=provider._read('/markets',args,5,parse_json).payload
            if not isinstance(page.get('markets'),list) or len(page['markets'])>1000:raise Reconnect()
            cursor=page.get('cursor') or ''
            if not isinstance(cursor,str) or len(cursor)>4096:raise Reconnect()
            if current is not None:cursors[current]=cursor
            for raw in page['markets']:
                m=metadata(raw)
                if m and (m['series'] in series or m['ticker'] in state['markets']):catalog[m['ticker']]=m
            # Catalog is a bounded selection, never an unbounded exchange feed.
            pinned={o['ticker'] for o in state['orders']}|{p['ticker'] for p in state['positions']}
            for ticker in list(catalog):
                if catalog[ticker]['close']<now and ticker not in pinned:catalog.pop(ticker)
            if len(catalog)>1000:
                rank=lambda m:(m['ticker'] not in pinned,m['close'])
                catalog=dict((m['ticker'],m) for m in sorted(catalog.values(),key=rank)[:1000])
            self.budget.successful()
            return 2,None,catalog
        except ProviderFailure as error:
            if error.code=='provider_rate_limit':self.budget.rate_limited(max(1,min(60,error.cooldown or 1)))
            elif error.cooldown:self.budget.defer(max(1,min(60,error.cooldown)))
            return max(2,min(60,error.cooldown or 5)),'market discovery backed off'

    def watched(self,catalog,state,strategies):
        now=self.clock();pinned={o['ticker'] for o in state['orders']}|{p['ticker'] for p in state['positions']}
        markets=dict(state['markets']);markets.update(catalog)
        def rank(m):
            yields=[s['statistical_yield_percent'] for s in strategies if m['series'] in s['series']]
            return (m['ticker'] not in pinned,-max(yields,default=-100000),m['close'],m['ticker'])
        candidates=[m for m in markets.values() if m['ticker'] in pinned or (now<m['close']<=now+86400 and m['status'] in ('open','active'))]
        return sorted(candidates,key=rank)[:max(self.watch_limit,len(pinned))]

    def run_session(self,job,provider):
        strategies=job['parameters']['strategies'];catalog={};cursors={};step=0;next_discovery=0
        state=self.store.checkpoint(job,self.clock(),gap='starting or recovering; waiting for fresh quotes')
        socket=None;subscribed={};acks=set();current=set();sequence={};command=0;last_command=0;backoff=2;healthy_since=None
        def close():
            nonlocal socket,subscribed,acks,current,sequence,healthy_since
            if socket is not None:
                try:socket.close()
                except Exception:pass
            socket=None;subscribed={};acks=set();current=set();sequence={};healthy_since=None
        try:
            while not self.stop.is_set():
                self.health('live paper lane ready')
                now=self.clock();messages=[];watch=self.watched(catalog,state,strategies)
                diagnostics=dict(provider_reads=self.reads,reconnects=self.reconnects,
                    watch_limit=self.watch_limit,watched_markets=len(watch),discovery_note=None,
                    market_candidates=len(catalog))
                if len(catalog)>self.watch_limit:diagnostics['capacity_limited']=True
                if now>=next_discovery:
                    result=self.discover(provider,strategies,state,catalog,cursors,step)
                    delay,note=result[:2]
                    if len(result)==3:catalog=result[2];step+=1
                    next_discovery=self.clock()+delay;diagnostics['discovery_note']=note
                    watch=self.watched(catalog,state,strategies)
                desired={m['ticker'] for m in watch if m['close']>now}
                try:
                    if desired and socket is None:
                        if self.connector is None:
                            from websockets.sync.client import connect
                            connector=connect
                        else:connector=self.connector
                        socket=connector(WS_URL,additional_headers=self.signer.headers('GET',WS_PATH),
                            open_timeout=10,close_timeout=2,ping_interval=10,ping_timeout=10,
                            max_size=262144,max_queue=16,compression=None,proxy=None)
                        command+=1
                        socket.send(json.dumps(dict(id=command,cmd='subscribe',params=dict(channels=['ticker','trade'],
                            market_tickers=sorted(desired),send_initial_snapshot=True))))
                        if self.stop.wait(1):break
                        command+=1
                        socket.send(json.dumps(dict(id=command,cmd='subscribe',params=dict(channels=['market_lifecycle_v2']))))
                        current=desired;last_command=now
                    elif socket is not None and desired!=current and len(subscribed)==3 and now-last_command>=1:
                        # A bounded subscription update, never one command/tick.
                        remove=current-desired;add=desired-current
                        action='delete_markets' if remove else 'add_markets';tickers=sorted(remove or add)
                        for channel,sid in subscribed.items():
                            if channel=='market_lifecycle_v2':continue
                            if self.stop.wait(max(0,1-(self.clock()-last_command))):break
                            command+=1;socket.send(json.dumps(dict(id=command,cmd='update_subscription',
                                params=dict(sids=[sid],market_tickers=tickers,action=action))))
                            last_command=self.clock()
                        current=(current-remove)|add;last_command=self.clock()
                    if socket is not None:
                        deadline=time.monotonic()+.5
                        for index in range(200):
                            try:raw=socket.recv(timeout=1 if index==0 else 0)
                            except TimeoutError:break
                            msg=json.loads(raw)
                            if msg.get('type')=='error':
                                code=msg.get('msg',{}).get('code')
                                if code in (25,26):self.watch_limit=max(10,self.watch_limit//2)
                                raise Reconnect('subscription rejected; retrying with backoff')
                            if msg.get('type')=='subscribed':
                                ack=msg.get('msg',{});channel=ack.get('channel')
                                if channel in ('ticker','trade','market_lifecycle_v2'):
                                    subscribed[channel]=ack['sid'];acks.add(channel)
                            if 'seq' in msg and 'sid' in msg and msg.get('type')!='subscribed':
                                sid=str(msg['sid']);seq=msg['seq'];previous=sequence.get(sid)
                                if type(seq) is not int or (previous is not None and seq!=previous+1):raise Reconnect('stream sequence gap')
                                sequence[sid]=seq
                            if msg.get('type')=='market_lifecycle_v2':
                                body=msg.get('msg',{});ticker=body.get('market_ticker')
                                m=catalog.get(ticker) or state['markets'].get(ticker)
                                if m:
                                    m=dict(m);lifecycle(m,body);catalog[ticker]=m;messages.append(msg)
                            elif msg.get('type') in ('ticker','trade'):messages.append(msg)
                            if time.monotonic()>=deadline:break
                    else:self.stop.wait(1)
                    feed='connected' if len(acks)==3 else ('subscribing' if socket else 'discovering eligible markets')
                    state=self.store.checkpoint(job,self.clock(),messages=messages,metadata=watch,feed=feed,diagnostics=diagnostics)
                    if len(acks)==3:
                        if healthy_since is None:healthy_since=self.clock()
                        if self.clock()-healthy_since>=60:backoff=2
                    if state['stopping'] and not state['positions'] and not state['orders']:break
                except LeaseLost:raise
                except Exception:
                    close();self.reconnects+=1
                    state=self.store.checkpoint(job,self.clock(),gap='feed interrupted; reconnecting',
                        diagnostics=dict(reconnects=self.reconnects,retry_in_seconds=backoff))
                    self.stop.wait(backoff+random.random());backoff=min(60,backoff*2)
        finally:
            close()
            self.store.release(job,self.clock())

    def run(self):
        """Failures back off locally; never bring down the collection process."""
        with KalshiInventory(signer=self.signer) as provider:
            while not self.stop.is_set():
                try:
                    self.health('ready; waiting for a live paper account')
                    job=self.store.claim()
                    if job is None:self.stop.wait(3);continue
                    self.run_session(job,provider)
                except LeaseLost:continue
                except Exception:
                    LOG.warning('live_paper_lane_backing_off')
                    self.stop.wait(5)


def check_feed():
    """One bounded read-only deployment probe; no paper account is created."""
    import os
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool
    from services.research.kalshi_auth import signer_from_env
    from services.research.budget import ReadBudget
    from websockets.sync.client import connect
    signer=signer_from_env(os.environ)
    if signer is None:raise ValueError('Market-data authentication is required')
    with ConnectionPool(os.environ['DATABASE_URL'],min_size=1,max_size=1,
            kwargs=dict(row_factory=dict_row,connect_timeout=5,options='-c statement_timeout=5000')) as pool:
        budget=ReadBudget(pool)
        if budget.take(1):return dict(ok=False,reason='shared read budget busy; retry later')
        with KalshiInventory(signer=signer) as provider:
            page=provider._read('/markets',dict(series_ticker='KXBTC15M',status='open',limit=10),5,parse_json).payload
        rows=[r for r in page.get('markets',[]) if metadata(r)]
        if not rows:return dict(ok=False,reason='no open BTC 15-minute market in probe')
        ticker=sorted(rows,key=lambda r:r['close_time'])[0]['ticker']
        channels=set();fresh=False;deadline=time.monotonic()+20
        with connect(WS_URL,additional_headers=signer.headers('GET',WS_PATH),open_timeout=10,close_timeout=2,
                max_size=262144,max_queue=16,compression=None,proxy=None) as ws:
            ws.send(json.dumps(dict(id=1,cmd='subscribe',params=dict(channels=['ticker','trade'],market_tickers=[ticker],send_initial_snapshot=True))))
            while time.monotonic()<deadline:
                try:msg=json.loads(ws.recv(timeout=2))
                except TimeoutError:continue
                if msg.get('type')=='error':return dict(ok=False,reason='subscription rejected',code=msg.get('msg',{}).get('code'))
                if msg.get('type')=='subscribed':channels.add(msg.get('msg',{}).get('channel'))
                if msg.get('type')=='ticker':
                    body=msg.get('msg',{});ts=body.get('ts_ms',0)/1000 if 'ts_ms' in body else body.get('ts',0)
                    fresh=0<=time.time()-ts<=10
                if channels=={'ticker','trade'} and fresh:break
        return dict(ok=channels=={'ticker','trade'} and fresh,ticker=ticker,channels=sorted(channels),fresh_quote=fresh,
            exchange_orders_sent=0)


if __name__=='__main__':
    try:print(json.dumps(check_feed(),sort_keys=True),flush=True)
    except Exception:print(json.dumps(dict(ok=False,reason='read-only feed probe failed; check private service logs')),flush=True)
