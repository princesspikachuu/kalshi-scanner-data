"""Single fenced Demo worker. Bounded stream, durable intents, verified recovery."""
import json,os,time,signal,threading,hashlib,traceback,math
from collections import OrderedDict
from datetime import datetime,timezone
from decimal import Decimal
from uuid import uuid5,NAMESPACE_URL
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from .store import DemoStore
from .orderbook import OrderBooks
from .exchange import Exchange,ExchangeFailure,credentials,WS
from .stream_buffer import BufferedSocket,close_details
from .engine import candidates,quantity,qualifies,exit_price,wire_order,protective_threshold,order_threshold,entry_protection_matches

LOCK=723741931
TERMINAL=('executed','canceled','cancelled')
def number(value):return float(Decimal(str(value or '0')))
def cents(value):return round(number(value)*100)
def count(raw,key):return number(raw.get(key+'_fp',raw.get(key,0)))
def timestamp(value):
    if isinstance(value,(int,float)):return float(value)
    return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()

def quote(raw,now):
    try:
        ticker=raw['ticker'];bid=cents(raw['yes_bid_dollars']);ask=cents(raw['yes_ask_dollars'])
        series=raw.get('series_ticker') or ticker.split('-')[0]
        close=timestamp(raw['close_time']);entry_close=close;entry_clock='market_close'
        from services.research.reports import SERIES
        if series in SERIES['sports'] and raw.get('can_close_early') is True and raw.get('expected_expiration_time'):
            expected=timestamp(raw['expected_expiration_time'])
            if math.isfinite(expected) and 0<expected<=close:entry_close=expected;entry_clock='expected_expiration'
        return ticker,dict(bid=bid,ask=ask,at=now,close=close,entry_close=entry_close,entry_clock=entry_clock,
            metadata_at=now,open=timestamp(raw['open_time']) if raw.get('open_time') else 0,exchange_index=raw.get('exchange_index',0),series=series,result=raw.get('result'),status=raw.get('status'))
    except (KeyError,ValueError,TypeError):return None

class Worker:
    def __init__(self,store,exchange,stop,guard):
        self.store,self.exchange,self.stop,self.guard=store,exchange,stop,guard
        self.quotes={};self.states={};self.bots=[];self.orders=[];self.blocked=set();self.account={}
        self.last_reconcile=0;self.last_discovery=0;self.last_health=0;self.last_snapshot=0;self.last_diagnostic=0;self.stage="starting"
        self.socket=None;self.subscription=set();self.lifecycle_sid=None;self.lifecycle_requested=False;self.book_sid=None;self.stream_command=3;self.sequence={};self.recovered=False;self.series_index=0;self.discovery_turn=0
        self.funding=None;self.shard_reservations={};self.rejections_repaired=False
        self.cycle_discovery_epoch=-1;self.cycle_discovery_cursor=''
        self.unconfirmed_history_at={}
        self.daily_pnl={};self.daily_pnl_day=-1
        self.last_verified=0;self.sync_pending=None;self.netting_pending=set();self.pending_markets=set();self.lifecycle_sid=None;self.lifecycle_requested=False
        self.ownership_details={};self.historical_markets=set();self.ownership_digest=None;self.next_closed_repair=0
        self.market_ledger={};self.blocked_since={};self.recent_market_changes={};self.syncing_markets=set()
        self.historical_lookup_at={};self.next_historical_lookup=0;self.historical_missing={}
        self.next_empty_repair=0;self.empty_repair_at={}
        self.risk_sources=OrderedDict()
        self.legacy_exit_evidence=None;self.issue=None;self.last_health_state=None;self.context_market=None;self.context_order=None;self.context_bot=None
        self.reset_row=None;self.reset_controller=None;self.book_pong=None;self.last_book_ping=0;self.books=OrderBooks();self.cursor={};self.last_discovered={};self.last_account_write=0;self.trigger_digest={};self.order_cache={};self.bot_revisions={};self.maker_retries={}
        self.stream_outage_since=None;self.stream_disconnect_count=0;self.stream_recovery_count=0
        self.stream_last_recovered_at=0;self.stream_last_disconnected_at=0;self.stream_last_pressure_at=0;self.stream_opened_at=0;self.stream_outage_alerted=False
        self.stream_event_revision=0;self.rest_feed_drains=0;self.rest_feed_messages=0
        self.last_entry_bot=None;self.cycle_locks={}
        if isinstance(self.exchange,Exchange):self.exchange.before_read=self.drain_stream_during_read
    def entry_diagnostics(self,now):
        from .engine import entry_price,side_quote,fair_budget_config
        running_count=max(1,sum(b['desired']=='running' and not b.get('archived') for b in self.bots))
        from services.research.reports import SERIES
        summary={}
        for bot in self.bots:
            config=fair_budget_config(bot['config'],running_count);matched=fresh=available=submitted=blocked=maker=budget=stop_blocked=minimum=incomplete=0
            if config.get('strategy')=='buy_low_sell_high':
                from .cycles import diagnostics
                summary[bot['id']]=diagnostics(bot,self.quotes,self.states,self.orders,now,self.blocked,self.netting_pending,self.account,self.recovered,
                    daily_reason=self.daily_guard(bot,now),funding_waits=getattr(self.funding,'waits',{}),fair_running_count=running_count,cycle_locks=self.cycle_locks)
                if config.get('daily_loss_percent') is not None:summary[bot['id']]['daily_risk']=dict(limit_percent=config['daily_loss_percent'],pnl_cents=self.daily_pnl.get(bot['id']))
                continue
            market_exposure={};bot_exposure=0;exit_waiting=None
            for entry in self.orders:
                if entry['kind']!='entry' or entry['bot']!=bot['id'] or not entry.get('exit_triggered') or entry.get('filled',0)<=entry.get('sold',0):continue
                q=self.quotes.get(entry['ticker']);ceiling=entry.get('exit_ceiling_cents')
                working=any(o.get('parent')==entry['client_id'] and o['status'] not in ('closed','rejected') for o in self.orders)
                if q and now-q['at']<=5 and now<q['close'] and ceiling is not None and not working and side_quote(q,entry['side'])[0]>=ceiling:
                    exit_waiting=f'Protective exit retains its {ceiling}¢ limit, which would now cross the current bid; waiting for a maker-only quote'
                    break
            for order in self.orders:
                if order['kind']!='entry':continue
                amount=(order.get('remaining',0)+max(0,order.get('filled',0)-order.get('sold',0)))*order['price']
                market_exposure[order['ticker']]=market_exposure.get(order['ticker'],0)+amount
                if order['bot']==bot['id']:bot_exposure+=amount
            for ticker,q in self.quotes.items():
                from services.research.reports import SERIES
                if not any(q['series'] in SERIES[s['asset']] for s in config['squares']):continue
                available+=1
                if now-q['at']>5:continue
                fresh+=1
                if not q.get('book_ready',True) or not 0<q['bid']<q['ask']<100:incomplete+=1;continue
                for index,square in enumerate(config['squares']):
                    for side in ('yes','no'):
                        if not qualifies(square,q,side,now,config['qualification']):continue
                        matched+=1
                        if ticker in self.blocked:blocked+=1;continue
                        if self.states.get(bot['id'],{}).get(f'{ticker}/{index}/{side}',{}).get('submitted'):submitted+=1;continue
                        if not entry_protection_matches(config,square,q,side):stop_blocked+=1;continue
                        price=entry_price(config,q,side,square)
                        if price is None:
                            if config.get('minimum_cents') is not None and entry_price(dict(config,minimum_cents=None),q,side,square) is not None:minimum+=1
                            else:maker+=1
                            continue
                        if quantity(config,price,self.account.get('equity_cents',0),self.account.get('cash_cents',0),market_exposure.get(ticker,0),bot_exposure)<1:budget+=1
            if exit_waiting:message=exit_waiting
            elif bot['desired']!='running':message='New entries paused'
            elif not available:message='No open Demo markets found for these categories yet'
            elif not fresh:message=f'{available} Demo markets found; waiting for fresh streaming prices'
            elif incomplete==fresh:message=f'{fresh} fresh Demo markets found, but their order books are incomplete'
            elif not matched:message=f'{fresh} fresh Demo markets checked; none match the selected price/time windows'
            elif blocked==matched:message='Matching markets need ownership reconciliation'
            elif submitted==matched:message='Matching conditions already attempted; waiting for a new qualifying cycle'
            elif stop_blocked==matched:message='Entry skipped: current ASK is already at or below the protective exit trigger'
            elif minimum==matched:message='Matching conditions found; calculated bids are below the minimum bid'
            elif maker==matched:message='Matching conditions found; entry price would cross the ask'
            elif budget==matched:message='Matching conditions found; spending limits cannot fund one contract'
            else:message=f'{matched} matching conditions across {fresh} fresh Demo markets'
            summary[bot['id']]=dict(categories=sorted({s['asset'] for s in config['squares']}),estimated_finish=any(q.get('entry_clock')=='expected_expiration' and any(q['series'] in SERIES[s['asset']] for s in config['squares']) for q in self.quotes.values()),message=message,markets=available,fresh=fresh,incomplete_books=incomplete,matches=matched,attempted=submitted,blocked=blocked,maker_blocked=maker,budget_blocked=budget,exit_blocked=stop_blocked,minimum_blocked=minimum,exit_waiting=bool(exit_waiting))
        return summary
    def drain_stream_during_read(self):
        """Service live prices during slow, sequential REST reconciliation.

        Executes only on the owning worker thread, between GET calls. Do not
        process socket events concurrently with reconciliation or trading,
        and never run this callback while an exchange WRITE is in progress.
        """
        if self.stage not in ('reconciliation','trade') or self.socket is None or self.stop.is_set():return
        before=self.socket.stats()['consumed'] if hasattr(self.socket,'stats') else 0
        try:self.stream(wait=False)
        except ExchangeFailure as error:
            if error.code.startswith('stream') or error.code=='connection':
                self.mark_stream_failure(error.code)
                self.close_stream()
                self.stream_event_revision+=1
                self.recovered=False;self.last_reconcile=0
            else:raise
        finally:
            if self.socket and hasattr(self.socket,'stats'):
                consumed=self.socket.stats()['consumed']-before
                self.rest_feed_drains+=1;self.rest_feed_messages+=max(0,consumed)

    def stream_telemetry(self,now):
        stats=self.socket.stats() if hasattr(self.socket,'stats') else {}
        return dict(connected=self.socket is not None,
            subscribed_markets=len(self.subscription),verified_subscription=self.book_sid is not None,
            fresh_books=sum(q.get('source')=='orderbook' and q.get('book_ready') and 0<=now-q.get('at',0)<=5 for q in self.quotes.values()),
            disconnects=self.stream_disconnect_count,recoveries=self.stream_recovery_count,
            outage_seconds=round(max(0,now-self.stream_outage_since),2) if self.stream_outage_since is not None else 0,
            last_recovered_at=self.stream_last_recovered_at,last_disconnected_at=self.stream_last_disconnected_at,
            serviced_during_rest=self.rest_feed_messages,rest_feed_drains=self.rest_feed_drains,buffer=stats)

    def stream_recovered(self):
        # Price-feed recovery and account ownership verification are independent.
        # New accepted orders can keep ownership reconciliation pending even when
        # the WebSocket has restored live, sequenced, verified price books.
        if self.stream_outage_since is None or self.socket is None or self.book_sid is None:return False
        now=time.time()
        active=any(q.get('status','active')=='active' and q.get('close',0)>now for q in self.quotes.values())
        if active and not any(
            q.get('source')=='orderbook' and q.get('book_ready') and 0<=now-q.get('at',0)<=5 for q in self.quotes.values()):return False
        duration=round(max(0,now-self.stream_outage_since),3)
        self.stream_outage_since=None;self.stream_recovery_count+=1;self.stream_last_recovered_at=now;self.stream_outage_alerted=False
        print(json.dumps(dict(event='demo_stream_recovered',downtime_seconds=duration,
            reconnects=self.stream_disconnect_count,fresh_books=self.stream_telemetry(now)['fresh_books'])),flush=True)
        self.store.clear_alert('stream')
        return True

    def mark_stream_failure(self,reason):
        # Missing/gapped/invalid orderbook data is still an actionable error.
        # Invalidate every previously observed quote before reconnecting.
        now=time.time()
        if self.stream_outage_since is None:self.stream_outage_since=now
        self.stream_disconnect_count+=1;self.stream_last_disconnected_at=now
        print(json.dumps(dict(event='demo_stream_integrity_failure',code=reason,
            outage_seconds=round(now-self.stream_outage_since,2),
            disconnects=self.stream_disconnect_count)),flush=True)

    def recover_feed(self,error):
        now=time.time()
        buffer=self.socket.stats() if hasattr(self.socket,'stats') else {}
        self.recovered=False;self.close_stream()
        self.mark_stream_failure(error.code)
        print(json.dumps(dict(event='demo_stream_disconnected',code=error.code,
            outage_seconds=round(max(0,now-self.stream_outage_since),2),
            reconnects=self.stream_disconnect_count,
            buffer_messages=buffer.get('messages'),buffer_peak=buffer.get('peak_messages'),
            close_code=buffer.get('close_code'))),flush=True)
        if now-self.stream_outage_since>=25 and not self.stream_outage_alerted:
            self.store.alert('stream','Kalshi Demo prices have been unavailable for more than 25 seconds. New entries wait for a verified fresh feed.',True)
            self.stream_outage_alerted=True
        self.health('reconnecting','Market-price stream reconnecting; entries wait for fresh quotes and verified orders')

    def health(self,state,message):
        now=time.time()
        if state=='ready':self.issue=None
        if now-self.last_health>=10 or state!=self.last_health_state:
            self.store.put('health',dict(state=state,message=message,at=now,features=['square_bid_caps_v1','square_loss_prevention_v1','editable_rules_v1','buy_low_sell_high_v1','current_time_loss_v1'],
                watched=len(self.quotes),read_requests=self.exchange.reads,write_requests=self.exchange.writes,
                markets={t:{k:q.get(k) for k in ('close','open','status')} for t,q in self.quotes.items()},
                stream=self.stream_telemetry(now),reconciled_at=self.last_verified or self.last_reconcile,sync_pending=self.sync_pending if state=='syncing' else None,blocked_markets=sorted(self.blocked),historical_markets=sorted(self.historical_markets),syncing_markets=sorted(self.syncing_markets),ownership_details=self.ownership_details,bots=self.entry_diagnostics(now),issue=self.issue))
            self.last_health=now;self.last_health_state=state
        if now-self.last_diagnostic>=60:
            print(json.dumps(dict(event='demo_diagnostic',state=state,stage=self.stage,
                running=sum(b['desired']=='running' for b in self.bots),bots=len(self.bots),
                conditions=sum(len(b['config']['squares']) for b in self.bots if b['desired']=='running'),
                categories=sorted({s['asset'] for b in self.bots if b['desired']=='running' for s in b['config']['squares']}),
                watched=len(self.quotes),fresh=sum(now-q['at']<=5 for q in self.quotes.values()),
                orders=len(self.orders),stream=self.stream_telemetry(now),read_requests=self.exchange.reads,write_requests=self.exchange.writes,
                reconciled=self.recovered,last_verified=self.last_verified,sync_action=self.sync_pending['action'] if self.sync_pending else None,
                funding_waits=getattr(self.funding,'waits',{}),entry_diagnostics=self.entry_diagnostics(now))),flush=True)
            self.last_diagnostic=now
    def trading_health(self):
        self.stream_recovered()
        if self.stream_outage_since is not None:
            duration=max(0,time.time()-self.stream_outage_since)
            if duration>=25 and not self.stream_outage_alerted:
                self.store.alert('stream','Kalshi Demo prices have been unavailable for more than 25 seconds. New entries wait for a verified fresh feed.',True)
                self.stream_outage_alerted=True
            self.health('reconnecting','Waiting for fresh sequenced price snapshots and verified account state');return
        if self.recovered:self.health('ready','Demo account verified')
        elif self.sync_pending and self.last_verified>0 and time.time()-self.last_verified<=45 and self.issue is None:
            self.health('syncing','Order '+self.sync_pending['action']+' · checking updated balances and positions before the next entry')
        else:self.health('reconciling','Verifying exchange order state')
    def load_bots(self):
        self.reset_row=self.store.get('reset')
        self.bots=[]
        for row in self.store.rows('bot/',100):
            key=row['idempotency_key'].split('/')[-1]
            self.bots.append(dict(id=key,config=row['parameters']['config'],revision=row['parameters']['revision'],prior_protection=row['parameters'].get('prior_protection',{}),**row['progress']))
            if key not in self.states or self.bot_revisions.get(key)!=row['parameters']['revision']:
                prior=self.store.get('trigger/'+key)
                self.states[key]=prior['progress'] if prior and prior['parameters'].get('revision')==row['parameters']['revision'] else {}
                self.bot_revisions[key]=row['parameters']['revision']
                self.trigger_digest[key]=json.dumps(self.states[key],sort_keys=True)
                config=row['parameters']['config']
                print(json.dumps(dict(event='demo_entry_policy',categories=sorted({s['asset'] for s in config['squares']}),
                    qualification=config['qualification'],price_reference=config['price_reference'],
                    adjustment_cents=config['adjustment_cents'],maximum_cents=config.get('maximum_cents'),minimum_cents=config.get('minimum_cents'))),flush=True)
        self.orders=self.store.active_orders()
        self.refresh_cycle_locks()
        active={o['client_id'] for o in self.orders}
        self.order_cache={k:v for k,v in self.order_cache.items() if k in active}
        if any(b['config'].get('daily_loss_percent') is not None and b['id'] not in self.daily_pnl for b in self.bots):self.last_reconcile=0
    def daily_guard(self,bot,now):
        limit=bot['config'].get('daily_loss_percent')
        if limit is None:return None
        if self.daily_pnl_day!=int(now//86400) or bot['id'] not in self.daily_pnl:return 'daily_check'
        return 'daily_loss' if self.daily_pnl[bot['id']]<=-self.account.get('equity_cents',0)*limit/100 else None
    def poll_funding(self):
        # Confirmation must keep progressing even when no new bid qualifies.
        if self.funding is None:
            if not self.store.get('funding'):return
            from .funding import ShardFunding
            self.funding=ShardFunding(self.store,self.exchange)
        self.funding.poll()
    def repair_rejected_entries(self):
        if self.rejections_repaired:return
        with self.store.pool.connection() as c:
            rows=c.execute("""SELECT parameters,progress FROM research_job
                WHERE idempotency_key>='demo/order/' AND idempotency_key<'demo/order/zzzz'
                AND (parameters->>'kind'='entry' OR (parameters->>'exit_role'='profit'
                    AND parameters->>'rejection_reason' IN ('post_only','price_tick'))) AND progress->>'status'='rejected'
                AND NOT(parameters ? 'funding_retry_v1') ORDER BY created_at DESC LIMIT 501""").fetchall()
        if len(rows)>500:raise ExchangeFailure('rejected_order_repair_capacity')
        bots={b['id']:b for b in self.bots}
        for row in rows:
            order={**row['parameters'],**row['progress']};bot=bots.get(order['bot'])
            if self.retry_cycle_rejection(order):continue
            if order['kind']=='entry' and bot and order['revision']==bot['revision']:
                key=f"{order['ticker']}/{order['square']}/{order['side']}"
                memory=self.states.get(bot['id'],{}).get(key)
                if memory and memory.get('submitted'):
                    memory.update(submitted=False,attempt=memory.get('attempt',0)+1)
                    self.store.put('trigger/'+bot['id'],self.states[bot['id']],parameters=dict(revision=bot['revision']))
            order['funding_retry_v1']=True;self.save_order(order)
        self.rejections_repaired=True
    def retry_cycle_rejection(self,order):
        from .cycles import STRATEGY,rejection_prices
        if (order.get('entry_strategy')!=STRATEGY and order.get('exit_role')!='profit') or order.get('rejection_reason') not in ('post_only','price_tick'):return False
        now=time.time();quote=self.quotes.get(order['ticker'],{})
        retry=dict(after=now+.5,clock=quote.get('clock'),seq=quote.get('seq'),source=order['client_id'])
        prices=rejection_prices(order)
        if order['kind']=='entry':
            bot=next((b for b in self.bots if b['id']==order['bot'] and b['revision']==order['revision']),None)
            key=f"{order['ticker']}/{order['square']}/{order['side']}"
            memory=self.states.get(order['bot'],{}).get(key)
            if not bot or not memory or memory.get('cycle')!=order['cycle']:return False
            if (memory.get('price_retry') or {}).get('source')!=order['client_id']:
                memory.update(submitted=prices is None,attempt=max(memory.get('attempt',0),order.get('entry_attempt',0)+1),price_retry=retry)
                if prices:memory.update(retry_buy_cents=prices[0],retry_sell_cents=prices[1])
                self.store.put('trigger/'+order['bot'],self.states[order['bot']],parameters=dict(revision=order['revision']))
        else:
            parent=next((o for o in self.orders if o['client_id']==order.get('parent')),None)
            if not parent:return False
            if (parent.get('profit_price_retry') or {}).get('source')!=order['client_id']:
                parent.update(profit_price_retry=retry,profit_retry_exhausted=prices is None)
                if prices:parent['profit_target_cents']=prices[1]
                self.save_order(parent)
        order['funding_retry_v1']=True;self.save_order(order)
        self.record('cycle_price_retry',order,
            ('Buy retry lowered 2¢; future profit sell lowered 2¢' if order['kind']=='entry' else 'Profit sell retry raised 2¢') if prices else 'Price retry reached the market price boundary; no further price retry',
            previous_price_cents=order['price'],retry_price_cents=(prices[0] if order['kind']=='entry' else prices[1]) if prices else None,
            profit_target_cents=prices[1] if prices else None)
        return True
    def refresh_cycle_locks(self):
        tickers=set(self.quotes)|{o['ticker'] for o in self.orders}
        self.cycle_locks=self.store.filled_cycle_sides(tickers)
        for order in self.orders:self.remember_cycle_side(order)
    def remember_cycle_side(self,order):
        if order.get('kind')!='entry' or order.get('entry_strategy')!='buy_low_sell_high' or order.get('filled',0)<=0:return
        ticker=order['ticker'];prior=self.cycle_locks.get(ticker)
        self.cycle_locks[ticker]=order['side'] if prior in (None,order['side']) else 'both'
    def save_order(self,order):
        self.remember_cycle_side(order)
        data={k:v for k,v in order.items() if k not in ('status','filled','remaining','fees','exchange_id','closed_at','realized_cents')}
        state={k:v for k,v in order.items() if k in ('status','filled','remaining','fees','exchange_id','closed_at','realized_cents')}
        packed=json.dumps([data,state],sort_keys=True)
        if self.order_cache.get(order['client_id'])!=packed:
            self.store.put('order/'+order['client_id'],state,parameters=data)
            self.order_cache[order['client_id']]=packed
    def research_stop(self,identifier,band,minutes):
        if identifier not in self.risk_sources:
            with self.store.pool.connection() as c:
                row=c.execute("""SELECT asset,(SELECT jsonb_agg(jsonb_build_array(
                    cell#>'{hold,price_band_cents}',cell#>'{hold,minutes_before_close}',
                    coalesce(cell#>>'{loss_prevention,sell_threshold_cents}',cell#>>'{loss_prevention,threshold_cents}',cell#>>'{conditional_loss,sell_threshold_cents}',cell#>>'{conditional_loss,threshold_cents}')::numeric))
                    FROM jsonb_array_elements(report#>'{historical,cells}') cell) AS stops
                    FROM research_result WHERE id=%s""",(identifier,)).fetchone()
            from services.research.reports import MINUTES
            bands={}
            if row:
                for key,upper,stop in row['stops'] or []:
                    lower=max((m for m in MINUTES[row['asset']] if m<upper),default=0)
                    bands.setdefault(key,[]).append((lower,upper,stop))
            self.risk_sources[identifier]=bands
            if len(self.risk_sources)>500:self.risk_sources.popitem(last=False)
        self.risk_sources.move_to_end(identifier)
        return next((stop for low,high,stop in self.risk_sources[identifier].get(band,[]) if low<minutes<=high),None)
    def record(self,kind,order,message,**detail):
        self.store.event(kind,message,bot=order.get('bot'),ticker=order.get('ticker'),details=dict(order_kind=order.get('kind'),client_id=order.get('client_id'),exchange_id=order.get('exchange_id'),side=order.get('side'),price=order.get('price'),quantity=order.get('quantity'),condition=order.get('condition'),quote=self.quotes.get(order.get('ticker')),**detail))
    def apply_cycle_offsets(self,offsets):
        if not offsets:return
        from psycopg.types.json import Jsonb
        changes=[]
        for order in self.orders:
            amount=offsets.get(order['client_id'],0)
            if amount:changes.append((order,dict(offset_quantity=round(order.get('offset_quantity',0)+amount,2),offset_credit_cents=round(order.get('offset_credit_cents',0)+50*amount,2))))
        with self.store.pool.connection() as c:
            for order,data in changes:
                result=c.execute("""UPDATE research_job SET parameters=parameters||%s
                    WHERE idempotency_key=%s AND coalesce((parameters->>'offset_quantity')::numeric,0)=%s
                    AND progress->>'status' NOT IN ('closed','rejected')""",
                    (Jsonb(data),'demo/order/'+order['client_id'],order.get('offset_quantity',0)))
                if result.rowcount!=1:raise ExchangeFailure('cycle_offset_conflict')
        for order,data in changes:
            order.update(data);self.record('position_offset',order,'Confirmed opposite fills offset inventory; estimated $1 pair credit split between lots',offset_quantity=offsets[order['client_id']])
    def rearm_cycle(self,order,now):
        if order.get('entry_strategy')!='buy_low_sell_high' or order.get('exit_triggered'):return
        if order.get('status')!='closed' or order.get('remaining',0)>0 or order.get('filled',0)<=0 or order.get('sold',0)<order['filled']:return
        bot=next((b for b in self.bots if b['id']==order['bot']),None)
        if not bot or bot['revision']!=order['revision'] or not bot['config'].get('cycle_repeat'):return
        key=f"{order['ticker']}/{order['square']}/{order['side']}"
        memory=self.states.setdefault(bot['id'],{}).get(key)
        if not memory or memory['cycle']!=order['cycle'] or not memory['submitted']:return
        memory.update(cycle=memory['cycle']+1,submitted=False,first_at=now,attempt=0)
        for field in ('retry_buy_cents','retry_sell_cents','price_retry'):memory.pop(field,None)
        self.store.put('trigger/'+bot['id'],self.states[bot['id']],parameters=dict(revision=bot['revision']))
    def restore_filled_cycle_claim(self,order):
        if order['kind']!='entry' or order.get('entry_strategy')!='buy_low_sell_high' or order.get('filled',0)<=0:return
        bot=next((b for b in self.bots if b['id']==order['bot'] and b['revision']==order['revision']),None)
        key=f"{order['ticker']}/{order['square']}/{order['side']}"
        memory=self.states.get(order['bot'],{}).get(key)
        # A parked buy can fill before cancellation reaches the exchange.
        if bot and memory and memory.get('cycle')==order['cycle'] and not memory.get('submitted'):
            memory['submitted']=True
            self.store.put('trigger/'+bot['id'],self.states[bot['id']],parameters=dict(revision=bot['revision']))
    def profit_sell(self,order,quote,now):
        if order.get('entry_strategy')!='buy_low_sell_high' or order.get('exit_triggered') or not self.recovered:return False
        if order['ticker'] in self.blocked or order['ticker'] in self.netting_pending:return False
        from .cycles import retry_ready
        if order.get('profit_retry_exhausted') or not retry_ready(order.get('profit_price_retry'),quote,now):return False
        if any(o['kind']=='entry' and o['ticker']==order['ticker'] and o['side']!=order['side'] and o.get('status') not in ('closed','rejected') and (o.get('remaining',0)>0 or o.get('filled',0)>o.get('sold',0) or o.get('status') in ('intent','uncertain','cancel_pending')) for o in self.orders):return False
        if any(o['kind']=='entry' and o['ticker']==order['ticker'] and o['side']==order['side'] and o['price']>=order['profit_target_cents']
            and o.get('status') not in ('closed','rejected') and (o.get('remaining',0)>0 or o.get('status') in ('intent','uncertain','cancel_pending')) for o in self.orders):return False
        children=[o for o in self.orders if o.get('parent')==order['client_id'] and o['status'] not in ('closed','rejected')]
        if any(o['status'] in ('intent','uncertain') for o in children):return False
        amount=round(order['filled']-order.get('sold',0)-sum(o.get('remaining',0) for o in children),2)
        if amount<=.001:return False
        attempt=order.get('profit_attempt',0)+1;order['profit_attempt']=attempt;self.save_order(order)
        identifier=str(uuid5(NAMESPACE_URL,f"demo-profit/{order['client_id']}/{attempt}"))
        self.submit(dict(client_id=identifier,kind='exit',exit_role='profit',parent=order['client_id'],bot=order['bot'],revision=order['revision'],
            ticker=order['ticker'],side=order['side'],price=order['profit_target_cents'],quantity=amount,close=quote['close'],exchange_index=order.get('exchange_index',-1),
            created_at=now,status='intent',remaining=0,filled=0))
        return True
    def recover_closed_orders(self,by_client,known,blocked,now):
        if now<self.next_closed_repair:return False
        self.next_closed_repair=now+60
        candidates={key:raw for key,raw in by_client.items() if key and key not in known and raw.get('ticker') in blocked}
        if not candidates:return False
        from .ownership import needs_recovery
        keys=['demo/order/'+key for key in list(candidates)[:4000]]
        with self.store.pool.connection() as c:
            rows=c.execute("SELECT parameters,progress FROM research_job WHERE idempotency_key=ANY(%s) AND progress->>'status' IN ('closed','rejected')",(keys,)).fetchall()
        recovered=False
        for row in rows:
            data,state=row['parameters'],row['progress'];raw=candidates.get(data.get('client_id'))
            if not raw or not needs_recovery(data,state,raw):continue
            state=dict(state,exchange_id=raw['order_id'],filled=count(raw,'fill_count'),remaining=count(raw,'remaining_count'),fees=cents(raw.get('maker_fees_dollars',0))+cents(raw.get('taker_fees_dollars',0)))
            state['status']='resting' if raw['status']=='resting' else 'held' if data['kind']=='entry' and state['filled'] else 'closed'
            if state['status']!='closed':state.pop('closed_at',None)
            self.store.put('order/'+data['client_id'],state)
            self.record('fill_recovered',dict(data,**state),'Recovered exchange-confirmed order changes after local closure',previous_filled=row['progress'].get('filled',0),filled=state['filled'])
            print(json.dumps(dict(event='demo_closed_order_recovered',ticker=data['ticker'],kind=data['kind'],previous_filled=row['progress'].get('filled',0),filled=state['filled'])),flush=True)
            recovered=True
        return recovered
    def refresh_historical_market(self,tickers,now):
        if now<self.next_historical_lookup:return
        from urllib.parse import quote as path_quote
        for ticker in sorted(tickers):
            q=self.quotes.get(ticker)
            prior=next((o for o in self.orders if o['ticker']==ticker and o.get('entry_strategy')!='buy_low_sell_high' and o.get('close',now+1)<=now),None)
            if not (q and q['close']<=now or prior) or now<self.historical_lookup_at.get(ticker,0):continue
            self.next_historical_lookup=now+10;self.historical_lookup_at[ticker]=now+300
            try:
                response=self.exchange.call('GET','/markets/'+path_quote(ticker,safe=''));parsed=quote(response.get('market',{}),now)
                if not parsed or parsed[0]!=ticker:return
                _,metadata=parsed
                if q:
                    for field in ('close','entry_close','entry_clock','status','result','exchange_index','series','open','metadata_at'):q[field]=metadata[field]
                else:metadata['at']=0;self.quotes[ticker]=metadata
                self.historical_missing.pop(ticker,None)
            except ExchangeFailure as error:
                if error.status==404:
                    end=q['close'] if q else prior['close']
                    self.historical_missing[ticker]=dict(market_end=end,checked_at=now)
                elif error.code=='authentication':raise
                else:self.historical_lookup_at[ticker]=now+60
            return
    def repair_empty_finalized_intents(self,blocked,expected,actual,remote,recent,now):
        """Clear only proven-empty stale intents; never manufacture a fill or settlement."""
        if now<self.next_empty_repair:return False
        self.next_empty_repair=now+15
        from .ownership import verified_empty_finalized_intents,native_expiry_passed
        for ticker in sorted(blocked):
            if now<self.empty_repair_at.get(ticker,0):continue
            q=self.quotes.get(ticker)
            local=[order for order in self.orders if order['ticker']==ticker]
            finalized=bool(q and q.get('status') in ('closed','settled','finalized','determined'))
            if not (finalized or native_expiry_passed(local,now)) or (
                any(o['status'] not in ('intent','uncertain','cancel_pending','resting') or o.get('filled',0) for o in local)
            ):continue
            if abs(expected.get(ticker,0))>.001 or abs(actual.get(ticker,0))>.001:continue
            self.empty_repair_at[ticker]=now+300
            try:
                # Filtered, fully paginated exchange evidence. Unknown fills
                # prevent cleanup even when the exchange position is flat.
                # Read both tiers: an empty live endpoint alone does not prove
                # an old intent never filled. Any archive failure keeps it held.
                # Live first, archive second also covers records moving to the
                # archive between these reads instead of observing neither tier.
                history=list(self.exchange.pages('/portfolio/orders','orders',ticker=ticker))
                history+=list(self.exchange.pages('/historical/orders','orders',ticker=ticker))
                fills=list(self.exchange.pages('/portfolio/fills','fills',ticker=ticker))
                fills+=list(self.exchange.pages('/historical/fills','fills',ticker=ticker))
                positions=list(self.exchange.pages('/portfolio/positions','market_positions',count_filter='position'))
                current_actual={p['ticker']:number(p.get('position_fp',p.get('position',0))) for p in positions}
            except ExchangeFailure as error:
                if error.code=='authentication':raise
                self.empty_repair_at[ticker]=now+60
                return False
            clients=verified_empty_finalized_intents(
                ticker,local,q,expected.get(ticker,0),current_actual.get(ticker,0),
                remote,history,fills,time.time())
            if not clients:continue
            for order in local:
                if order['client_id'] not in clients:continue
                order.update(status='closed',remaining=0,closed_at=now)
                self.save_order(order)
                self.record('stale_intent_cleared',order,
                    'Expired unfilled intent cleared after live and archived order, fill and position verification',
                    evidence='live_and_archived_history;expired_or_finalized;zero_position')
            self.orders=self.store.active_orders()
            self.last_reconcile=0;self.recovered=False
            print(json.dumps(dict(event='demo_stale_intents_cleared',ticker=ticker,count=len(clients))),flush=True)
            return True
        return False

    def order_history(self,positions,remote,now):
        """Complete history for relevant markets, not the account's lifetime churn.

        Keep pagination fail-closed. An old held entry must not make every
        reconciliation enumerate thousands of unrelated canceled bids.
        """
        starts={}
        known={o.get('client_id') for o in self.orders if o.get('client_id')}
        resting={o.get('client_order_id'):o for o in remote if o.get('client_order_id')}
        for order in self.orders:
            ticker=order['ticker']
            raw=resting.get(order.get('client_id'))
            # A complete resting snapshot already verifies an untouched bid.
            # Missing/filled/ambiguous local orders still require history.
            if (raw and order.get('status')=='resting' and not order.get('filled',0)
                and not count(raw,'fill_count')):continue
            starts[ticker]=min(starts.get(ticker,now),order['created_at'])
        # Include unowned positions/resting orders so closed local records can
        # still be recovered from exchange evidence. Do not time-limit these.
        unbounded={p['ticker'] for p in positions}|{o['ticker'] for o in remote
            if o.get('client_order_id') not in known or count(o,'fill_count')}
        # Old unconfirmed intents with no exchange ID or exposure stay blocked.
        # Poll their histories every 30 seconds instead of delaying every live
        # bid on the same empty lookup. Fresh account positions/resting orders
        # still force immediate verification if any exposure appears.
        quiet=set()
        remote_tickers={o['ticker'] for o in remote}
        for ticker in starts.keys()-unbounded-remote_tickers:
            local=[o for o in self.orders if o['ticker']==ticker]
            if all(o.get('status') in ('intent','uncertain') and not o.get('exchange_id')
                and not o.get('filled',0) and not o.get('remaining',0)
                and o.get('close',now)>0 and o.get('close',now)<=now-60 for o in local):
                quiet.add(ticker)
        history=[]
        checked=0
        for ticker in sorted(set(starts)|unbounded):
            if ticker in quiet and now-self.unconfirmed_history_at.get(ticker,0)<30:continue
            params=dict(ticker=ticker)
            if ticker not in unbounded:params['min_ts']=int(starts[ticker])-60
            history.extend(self.exchange.pages('/portfolio/orders','orders',**params))
            checked+=1
            if ticker in quiet:self.unconfirmed_history_at[ticker]=now
        print(json.dumps(dict(event='demo_history_scope',local_orders=len(self.orders),
            resting_orders=len(remote),history_markets=checked)),flush=True)
        return history
    def lookup_exchange_order(self,order):
        try:
            result=self.exchange.call('GET','/portfolio/orders/'+order['exchange_id'])
            return result.get('order',result)
        except ExchangeFailure as error:
            if error.status!=404 or error.ambiguous:raise
            # A missing individual GET does not prove an outstanding
            # limit was canceled or an open position was settled.
            print(json.dumps(dict(event='demo_order_lookup_missing',
                ticker=order['ticker'],kind=order['kind'],
                status=order.get('status'),http_status=404)),flush=True)
            return None

    def reconcile(self):
        """Complete paginated exchange state; gaps never manufacture fills."""
        now=time.time();start_feed_revision=self.stream_event_revision;self.load_bots()
        balance=self.exchange.call('GET','/portfolio/balance')
        positions=list(self.exchange.pages('/portfolio/positions','market_positions',count_filter='position'))
        # Resting orders include manual orders. Recent records resolve lost responses.
        remote=list(self.exchange.pages('/portfolio/orders','orders',status='resting'))
        self.shard_reservations={}
        from .funding import resting_reservation
        for raw in remote:
            index=raw.get('exchange_index',0)
            # Reserve the limit's worst-case cash cost, including manual orders.
            self.shard_reservations[index]=self.shard_reservations.get(index,0)+resting_reservation(raw)
        recent=self.order_history(positions,remote,now)
        by_client={o.get('client_order_id'):o for o in remote+recent}
        known_ids={o['client_id'] for o in self.orders};blocked={o['ticker'] for o in remote if o.get('client_order_id') not in known_ids}
        for order in self.orders:
            self.context_market=order['ticker'];self.context_order=order.get('exchange_id') or order['client_id'];self.context_bot=order['bot']
            raw=by_client.get(order['client_id'])
            if raw is None and order.get('exchange_id'):
                raw=self.lookup_exchange_order(order)
            if raw is None:
                # A durable intent may have crossed the network before a crash.
                # Absence in paginated history is not permission to submit again.
                order['status']='uncertain';blocked.add(order['ticker']);self.save_order(order);continue
            previous=order.get('filled',0);prior_status=order.get('status')
            order.update(exchange_id=raw['order_id'],filled=count(raw,'fill_count'),remaining=count(raw,'remaining_count'),
                fees=cents(raw.get('maker_fees_dollars',0))+cents(raw.get('taker_fees_dollars',0)))
            order['status']='resting' if raw['status']=='resting' else 'held' if order['kind']=='entry' and order['filled'] else 'closed'
            if order['kind']=='exit' and raw['status'] in TERMINAL:order['status']='closed'
            if order['status']=='resting' and order.get('cancel_404_at') and now-order['cancel_404_at']<30:
                # A still-resting order after a rejected cancel requires a
                # bounded per-market retry cooldown, never a tight 404 loop.
                blocked.add(order['ticker'])
            self.rearm_allocation_cancel(order)
            # Persist the replacement permission before retiring the old row.
            # A restart between writes still sees an active cancellation and
            # therefore cannot duplicate the replacement or lose its rearm.
            self.save_order(order)
            self.restore_filled_cycle_claim(order)
            if order['filled']>previous:self.record('fill',order,'Exchange-confirmed '+order['kind']+' fill',filled=order['filled'])
            if prior_status not in ('closed','held') and order['status']=='closed':self.record('cancel',order,'Exchange order is no longer resting')
        # Reload includes fills committed above and closed exits for per-entry allocation.
        parents=[o['client_id'] for o in self.orders if o['kind']=='entry']
        with self.store.pool.connection() as c:
            exits=c.execute("SELECT parameters,progress FROM research_job WHERE idempotency_key>='demo/order/' AND idempotency_key<'demo/order/zzzz' AND parameters->>'kind'='exit' AND parameters->>'parent'=ANY(%s) AND progress->>'filled' IS NOT NULL LIMIT 5001",(parents,)).fetchall()
            risk_bots=[b['id'] for b in self.bots if b['config'].get('daily_loss_percent') is not None]
            self.daily_pnl={b:0 for b in risk_bots};self.daily_pnl_day=int(now//86400)
            if risk_bots:
                scores=c.execute("""SELECT parameters->>'bot' AS bot,sum((progress->>'realized_cents')::numeric) AS pnl FROM research_job
                    WHERE idempotency_key>='demo/order/' AND idempotency_key<'demo/order/zzzz'
                    AND parameters->>'bot'=ANY(%s) AND parameters->>'kind'='entry' AND progress ? 'realized_cents'
                    AND (progress->>'closed_at')::numeric>=%s GROUP BY 1""",(risk_bots,self.daily_pnl_day*86400)).fetchall()
                self.daily_pnl.update({r['bot']:float(r['pnl']) for r in scores})
        if len(exits)>5000:raise ExchangeFailure('entry_exit_reconciliation_capacity')
        sold={};exit_fees={}
        for row in exits:
            parent=row['parameters'].get('parent')
            sold[parent]=round(sold.get(parent,0)+row['progress'].get('filled',0),2)
            exit_fees[parent]=exit_fees.get(parent,0)+row['progress'].get('fees',0)
        self.orders=self.store.active_orders()
        from .cycles import offset_plan
        actual={p['ticker']:number(p.get('position_fp',p.get('position',0))) for p in positions}
        offsets,self.netting_pending=offset_plan(self.orders,sold,actual,blocked)
        self.apply_cycle_offsets(offsets)
        for order in self.orders:
            if order['kind']=='entry':
                order['sold']=round(sold.get(order['client_id'],0)+order.get('offset_quantity',0),2)
                if order.get('filled',0)>0 and order['sold']>=order['filled'] and order.get('remaining',0)==0:
                    sale_total=sum(r['progress'].get('filled',0)*r['parameters']['price'] for r in exits if r['parameters'].get('parent')==order['client_id'])
                    order['realized_cents']=round(sale_total+order.get('offset_credit_cents',0)-order['filled']*order['price']-order.get('fees',0)-exit_fees.get(order['client_id'],0))
                    order['status']='closed';order['closed_at']=now;self.save_order(order)
                    self.record('realized',order,'Entry fully exited',realized_cents=order['realized_cents'])
                    self.rearm_cycle(order,now)
        expected={}
        for order in self.orders:
            if order['kind']=='entry':
                order['sold']=round(sold.get(order['client_id'],0)+order.get('offset_quantity',0),2)
                posted=[r['parameters']['price'] for r in exits if r['parameters'].get('exit_role')!='profit' and r['parameters'].get('parent')==order['client_id'] and r['progress'].get('status')!='rejected' and r['parameters'].get('created_at',0)>=order.get('exit_rule_started_at',0)]
                if posted:order['exit_ceiling_cents']=min(order.get('exit_ceiling_cents',99),*posted)
                self.save_order(order)
            if order['kind']=='entry' and order['status']!='closed':expected[order['ticker']]=expected.get(order['ticker'],0)+(order.get('filled',0)-order.get('sold',0))*(1 if order['side']=='yes' else -1)
        actual={p['ticker']:number(p.get('position_fp',p.get('position',0))) for p in positions}
        differences={t for t in set(expected)|set(actual) if abs(expected.get(t,0)-actual.get(t,0))>.001}
        if differences:
            # Initial positions were fetched BEFORE paginated order history.
            # Fill/cancel updates across shared bots can make that first snapshot
            # stale. A fresh, complete position read is authoritative; an API
            # failure still fails closed and cannot clear a discrepancy.
            latest=list(self.exchange.pages('/portfolio/positions','market_positions',count_filter='position'))
            positions=latest
            actual={p['ticker']:number(p.get('position_fp',p.get('position',0))) for p in latest}
        mismatches={t for t in set(expected)|set(actual) if abs(expected.get(t,0)-actual.get(t,0))>.001}|blocked
        self.refresh_historical_market(mismatches,now)
        for ticker in set(expected)|set(actual):
            q=self.quotes.get(ticker)
            if q and q.get('status') in ('settled','finalized') and q.get('result') in ('yes','no'):
                for order in self.orders:
                    if order['kind']=='entry' and order['ticker']==ticker and order.get('filled',0)>order.get('sold',0):
                        payout=100 if q.get('result')==order['side'] else 0
                        sale_total=sum(r['progress'].get('filled',0)*r['parameters']['price'] for r in exits if r['parameters'].get('parent')==order['client_id'])
                        order['realized_cents']=round(sale_total+order.get('offset_credit_cents',0)+(order['filled']-order.get('sold',0))*payout-order['filled']*order['price']-order.get('fees',0)-exit_fees.get(order['client_id'],0))
                        order.update(status='closed',closed_at=now);self.save_order(order)
                        self.record('settlement',order,'Exchange-confirmed settlement',realized_cents=order['realized_cents'])
                continue
            if abs(expected.get(ticker,0)-actual.get(ticker,0))>.001:blocked.add(ticker)
        self.blocked=blocked
        self.historical_lookup_at={t:v for t,v in self.historical_lookup_at.items() if t in blocked}
        self.historical_missing={t:v for t,v in self.historical_missing.items() if t in blocked}
        if blocked and self.recover_closed_orders(by_client,known_ids,blocked,now):
            self.last_discovery=0;self.last_reconcile=0;self.recovered=False;return
        if blocked and self.repair_empty_finalized_intents(blocked,expected,actual,remote,recent,now):
            # Publish a fresh verification snapshot, not a speculative reduction
            # in the blocked set while the saved ledger is changing.
            return
        from .ownership import describe,market_ledger,transient_sync
        snapshot_at=time.time()
        self.market_ledger=market_ledger(self.orders,expected,actual,remote,blocked,
            {bot['id']:bot['config'].get('name',bot['id']) for bot in self.bots})
        ended=self.blocked_since.keys()-blocked
        for ticker in ended:
            previous=self.market_ledger.get(ticker,{})
            print(json.dumps(dict(event='demo_market_reconciliation_resolved',ticker=ticker,
                blocked_seconds=round(snapshot_at-self.blocked_since[ticker],3),
                participating_bots=[b['id'] for b in previous.get('bots',[])])),flush=True)
        self.blocked_since={t:self.blocked_since.get(t,snapshot_at) for t in blocked}
        self.recent_market_changes={t:v for t,v in self.recent_market_changes.items() if snapshot_at-v<=120}
        self.ownership_details=describe(blocked,expected,actual,self.quotes,self.orders,remote,now,self.historical_missing,ledger=self.market_ledger)
        self.historical_markets={t for t,d in self.ownership_details.items() if d['informational']}
        actionable=blocked-self.historical_markets
        self.syncing_markets={t for t in actionable if transient_sync(self.market_ledger[t],snapshot_at,
            self.recent_market_changes.get(t,0),self.blocked_since[t],self.last_verified)}
        for ticker,details in self.ownership_details.items():
            details['blocked_seconds']=round(max(0,snapshot_at-self.blocked_since[ticker]),2)
            details['syncing']=ticker in self.syncing_markets
        # Elapsed seconds are display-only. Do not turn every half-second tick
        # into a health write and an ownership log entry.
        stable={t:{k:v for k,v in detail.items() if k!='blocked_seconds'} for t,detail in self.ownership_details.items()}
        digest=json.dumps(stable,sort_keys=True)
        if digest!=self.ownership_digest:
            summarized={t:dict(reason=d['reason'],expected=d['expected_contracts'],actual=d['exchange_contracts'],
                bots=[b['id'] for b in d.get('bots',[])],orders=d.get('order_count',0),
                verification_orders=[dict(kind=o.get('kind'),status=o.get('status'),side=o.get('side'),
                    price=o.get('price'),filled=o.get('filled',0),remaining=o.get('remaining',0),
                    has_exchange_id=bool(o.get('exchange_id')),
                    created_at=o.get('created_at'),close=o.get('close'),
                    cancel_404_at=o.get('cancel_404_at'))
                    for o in self.orders if o['ticker']==t][:3],
                unowned=d.get('unowned_order_count',0),syncing=d.get('syncing',False),
                blocked_seconds=d.get('blocked_seconds',0)) for t,d in self.ownership_details.items()}
            print(json.dumps(dict(event='demo_ownership_check',actionable=len(actionable),
                syncing=len(self.syncing_markets),historical=len(self.historical_markets),markets=summarized)),flush=True)
            self.ownership_digest=digest;self.last_health=0
        urgent=actionable-self.syncing_markets
        if urgent:
            from .ownership import ownership_alert
            self.store.alert('ownership',ownership_alert(self.ownership_details,urgent),True)
        else:self.store.clear_alert('ownership')
        self.account=dict(cash_cents=int(balance['balance']),position_value_cents=int(balance['portfolio_value']),
            equity_cents=int(balance['balance'])+int(balance['portfolio_value']),at=now,
            held_markets=len([p for p in positions if number(p.get('position_fp',p.get('position',0)))]))
        self.store.put('account',self.account)
        if int(now//900)!=int(self.last_snapshot//900):
            self.store.put('equity/'+str(int(now//900)),dict(at=now,value=self.account['equity_cents']));self.last_snapshot=now
        # Fills/order updates received while the REST history was being
        # paginated may postdate individual page snapshots. Do not let a
        # successful but raced reconciliation erase their verification flag.
        changed_during_read=self.stream_event_revision!=start_feed_revision
        self.last_reconcile=0 if changed_during_read else now
        self.last_verified=time.time();self.recovered=not changed_during_read
        if not changed_during_read:self.sync_pending=None;self.issue=None
        self.store.clear_alert('recovery');self.store.clear_alert('exchange')
    def discover(self):
        now=time.time()
        from services.research.reports import SERIES
        series=sorted({s for b in self.bots if b['desired']=='running' for q in b['config']['squares'] for s in SERIES[q['asset']]})
        pinned={o['ticker'] for o in self.orders}
        cycle_series={s for b in self.bots if b['desired']=='running'
            and b['config'].get('strategy')=='buy_low_sell_high'
            for square in b['config']['squares'] for s in SERIES[square['asset']]}
        requests=[];pending=set()
        epoch=int(now//900);cycle_sweep=False
        if self.pending_markets:
            pending=set(self.pending_markets)
            requests=[dict(tickers=','.join(sorted(pending)),limit=200)]
        elif cycle_series and (self.cycle_discovery_epoch!=epoch or self.cycle_discovery_cursor):
            # Find this round across all series in a bounded, paginated read.
            # Per-series fallback continues after this sweep completes.
            cycle_sweep=True
            params=dict(status='open',limit=200,min_close_ts=int(now),max_close_ts=(epoch+1)*900+1)
            if self.cycle_discovery_epoch==epoch and self.cycle_discovery_cursor:
                params['cursor']=self.cycle_discovery_cursor
            requests=[params]
        elif pinned and (self.discovery_turn%5==0 or not series):
            requests=[dict(tickers=','.join(sorted(pinned)[:100]),limit=200)]
        elif series:
            # Sweep multiple different 15-minute series at a time. Previously
            # a single series was queried only every 5 seconds, so 28 bots
            # could miss most of a 15-minute market before the next sweep.
            order=sorted(series,key=lambda s:(s not in cycle_series,s))
            count=min(3,len(order)) if cycle_series else 1
            for i in range(count):
                current=order[(self.series_index+i)%len(order)]
                params=dict(series_ticker=current,status='open',limit=200,min_close_ts=int(now))
                if current not in SERIES['sports']:params['max_close_ts']=int(now+86400)
                if self.cursor.get(current):params['cursor']=self.cursor[current]
                requests.append(params)
        else:self.last_discovery=now;return
        for params in requests:
            page=self.exchange.call('GET','/markets',params=params)
            if not isinstance(page.get('markets'),list) or len(page['markets'])>200:raise ExchangeFailure('discovery_capacity')
            if cycle_sweep:
                self.cycle_discovery_epoch=epoch;self.cycle_discovery_cursor=page.get('cursor') or ''
            if 'series_ticker' in params:self.cursor[params['series_ticker']]=page.get('cursor') or ''
            for raw in page['markets']:
                parsed=quote(raw,now)
                if parsed:
                    ticker,q=parsed
                    # REST discovery does not qualify new trades; wait for the
                    # stream to verify the sequenced market book before buying.
                    if ticker not in pinned and not now<q['entry_close']<=now+86400:continue
                    old=self.quotes.get(ticker)
                    if old:
                        q=dict(old,close=q['close'],entry_close=q['entry_close'],
                            entry_clock=q['entry_clock'],status=q['status'],
                            result=q['result'],exchange_index=q['exchange_index'],
                            series=q['series'],open=q.get('open',0),metadata_at=now)
                    else:q['at']=0
                    self.quotes[ticker]=q;self.last_discovered[ticker]=now
            if 'series_ticker' in params:self.series_index+=1
            if pending:self.pending_markets.difference_update(pending)
        from .watchlist import select_markets
        eligible={t:q for t,q in self.quotes.items() if t in pinned or q['series'] in series}
        self.quotes=select_markets(eligible,pinned,now,cycle_series=cycle_series)
        self.refresh_cycle_locks()
        self.maker_retries={t:r for t,r in self.maker_retries.items() if t in self.quotes}
        self.last_discovered={t:v for t,v in self.last_discovered.items() if t in self.quotes}
        self.last_discovery=now;self.discovery_turn+=1
    def observe_exit_triggers(self,ticker,now,previous=None):
        """Latch the first crossing before another ticker message can replace it."""
        from .engine import side_quote
        q=self.quotes.get(ticker)
        # Latch a verified price crossing even while order ownership is syncing.
        # Submitting a sell is still prohibited by the blocked-market trade gate.
        if not q or now-q['at']>5 or now>=q['close']:return False
        bots={b['id']:b for b in self.bots};triggered=False
        for order in self.orders:
            if order['ticker']!=ticker or order['kind']!='entry' or order.get('exit_triggered') or order.get('status')=='uncertain' or order.get('filled',0)<=order.get('sold',0):continue
            bot=bots.get(order['bot'])
            if not bot:continue
            threshold=order_threshold(bot,order,q,now,self.research_stop)
            bid,ask=side_quote(q,order['side'])
            if threshold is None or not 0<=bid<ask<100 or ask>threshold:continue
            if q.get('source')=='orderbook' and not q.get('book_ready'):continue
            order['exit_triggered']=True;order['exit_reference']='ask';self.save_order(order)
            prior_ask=side_quote(previous,order['side'])[1] if previous and not (previous.get('source')=='orderbook' and not previous.get('book_ready')) else None
            gap=round(q.get('event_at',q['at'])-previous.get('event_at',previous['at']),3) if previous and previous.get('at') else None
            self.record('exit_trigger',order,'Current ASK reached the protective exit trigger',threshold=threshold,reference='ask',minutes_remaining=max(0,(q.get('entry_close',q['close'])-now)/60),protection_clock='market_time_remaining',previous_ask=prior_ask,observation_gap_seconds=gap,verification_pending=ticker in self.blocked)
            print(json.dumps(dict(event='demo_exit_trigger',threshold=threshold,minutes_remaining=max(0,(q.get('entry_close',q['close'])-now)/60),bid=bid,ask=ask,side=order['side'],quote_age=now-q['at'],entry_price=order['price'],previous_ask=prior_ask,observation_gap_seconds=gap,source=q.get('source'),clock=q.get('clock'),seq=q.get('seq'))),flush=True)
            triggered=True
        return triggered

    def stream(self,wait=True):
        desired={t for t,q in self.quotes.items() if q.get('status','active')=='active' and q['close']>time.time()}
        if not desired:return
        if self.socket is None:
            self.close_stream()
            from websockets.sync.client import connect
            from websockets.exceptions import WebSocketException
            try:
                connection=connect(WS,additional_headers=self.exchange.signer.headers('GET','/trade-api/ws/v2'),
                    max_size=262144,max_queue=16,open_timeout=8,close_timeout=2,ping_interval=15,ping_timeout=20,compression=None)
            except (OSError,TimeoutError,WebSocketException):raise ExchangeFailure('stream_connection_lost') from None
            self.socket=BufferedSocket(connection);self.stream_opened_at=time.time()
            self.socket.send(json.dumps(dict(id=1,cmd='subscribe',params=dict(channels=['orderbook_delta'],market_tickers=sorted(desired),update_interval_ms=0,use_yes_price=False))))
            self.socket.send(json.dumps(dict(id=2,cmd='subscribe',params=dict(channels=['fill','user_orders']))))
            self.subscription=desired;self.sequence={};self.recovered=False
        elif desired!=self.subscription and self.book_sid is not None:
            # Add/remove markets on the existing sequence instead of repeatedly
            # disconnecting held positions whenever discovery finds a market.
            for action,markets in [('add_markets',desired-self.subscription),('delete_markets',self.subscription-desired)]:
                if markets:
                    self.stream_command+=1
                    self.socket.send(json.dumps(dict(id=self.stream_command,cmd='update_subscription',params=dict(sids=[self.book_sid],market_tickers=sorted(markets),action=action))))
            self.subscription=desired
            self.books.books={t:b for t,b in self.books.books.items() if t in desired}
        want_lifecycle=any(b['desired']=='running' and b['config'].get('strategy')=='buy_low_sell_high' for b in self.bots)
        if want_lifecycle and not self.lifecycle_requested:
            self.stream_command+=1;self.socket.send(json.dumps(dict(id=self.stream_command,cmd='subscribe',params=dict(channels=['market_lifecycle_v2']))));self.lifecycle_requested=True
        elif not want_lifecycle and self.lifecycle_sid is not None:
            self.stream_command+=1;self.socket.send(json.dumps(dict(id=self.stream_command,cmd='unsubscribe',params=dict(sids=[self.lifecycle_sid]))));self.lifecycle_sid=None;self.lifecycle_requested=False
        # The receiver is independent of REST/database I/O. Drain a larger,
        # time-bounded batch when those calls leave messages queued, without
        # dropping any intermediate protective-exit price crossings.
        started=time.monotonic()
        for index in range(768):
            if index>=32 and time.monotonic()-started>=.35:break
            try:message=json.loads(self.socket.recv(timeout=.5 if wait and index==0 else 0))
            except TimeoutError:
                # A quiet but sequenced book remains current after a confirmed
                # transport round trip and an empty receive queue. No REST polls.
                now=time.time()
                if self.book_pong is not None and self.book_pong.is_set():
                    for ticker in self.books.books:
                        q=self.quotes.get(ticker)
                        if q and q.get('source')=='orderbook':q['at']=now
                    self.book_pong=None
                if self.book_pong is None and now-self.last_book_ping>=2 and hasattr(self.socket,'ping'):
                    self.book_pong=self.socket.ping();self.last_book_ping=now
                break
            if message.get('type')=='error':raise ExchangeFailure('stream_subscription')
            if message.get('type')=='subscribed':
                if message.get('msg',{}).get('channel')=='orderbook_delta':self.book_sid=message['msg']['sid']
                if message.get('msg',{}).get('channel')=='market_lifecycle_v2':self.lifecycle_sid=message['msg']['sid']
                continue
            if 'seq' in message and 'sid' in message:
                sid=message['sid'];seq=message['seq']
                if sid in self.sequence and seq!=self.sequence[sid]+1:raise ExchangeFailure('stream_gap')
                self.sequence[sid]=seq
            raw=message.get('msg',{})
            if message.get('type')=='market_lifecycle_v2' and raw.get('event_type') in ('activated','created'):
                ticker=raw.get('market_ticker','')
                from services.research.reports import SERIES
                wanted={series for b in self.bots if b['desired']=='running' and b['config'].get('strategy')=='buy_low_sell_high' for square in b['config']['squares'] for series in SERIES[square['asset']]}
                if any(ticker.startswith(series+'-') for series in wanted) and len(self.pending_markets)<100:
                    self.pending_markets.add(ticker);self.last_discovery=0
            if message.get('type') in ('fill','user_orders'):
                # Order-update notifications can accompany every accepted bid.
                # Only a fill changes exposure and invalidates a REST history
                # snapshot that is still being paginated.
                if message.get('type')=='fill':self.stream_event_revision+=1
                self.last_reconcile=0
                ticker=raw.get('market_ticker') or raw.get('ticker')
                if ticker:self.recent_market_changes[ticker]=time.time()
            # Verify newly filled exposure before consuming later price changes;
            # otherwise its first stop crossing could arrive while filled=0.
            if message.get('type')=='fill':return
            if message.get('type') in ('orderbook_snapshot','orderbook_delta'):
                ticker=raw.get('market_ticker')
                if ticker not in self.quotes:continue
                self.book_sid=message['sid']
                now=time.time();old=self.quotes[ticker]
                # Late updates from an ended market cannot authorize a trade.
                # Consume their sequence without resetting unrelated live books.
                if old['close']<=now or old.get('status') in ('closed','settled','finalized','determined'):
                    self.books.books.pop(ticker,None);old['at']=0
                    continue
                ticker,observed=self.books.apply(message,getattr(self.socket,'received_at',None) or now)
                self.quotes[ticker]=dict(old,**observed)
                # Yield on the first crossing instead of collapsing a burst of
                # exchange changes into its last (potentially much lower) price.
                if observed['book_ready'] and self.observe_exit_triggers(ticker,now,old):return
        # A connected TCP socket without a usable exchange subscription is
        # not a working feed. Avoid leaving bots indefinitely waiting on it.
        if self.socket is not None and self.book_sid is None and self.stream_opened_at and time.time()-self.stream_opened_at>25:
            raise ExchangeFailure('stream_subscription')
    def close_stream(self):
        if self.socket:
            try:self.socket.close()
            except Exception:pass
        self.socket=None;self.subscription=set();self.lifecycle_sid=None;self.lifecycle_requested=False;self.book_sid=None;self.book_pong=None;self.last_book_ping=0;self.books.clear();self.stream_opened_at=0
        for q in self.quotes.values():q['at']=0
    def cancel(self,order,reason):
        self.context_market=order['ticker'];self.context_order=order.get('exchange_id') or order['client_id'];self.context_bot=order['bot']
        if order.get('status') in ('cancel_pending','uncertain') or not order.get('remaining',0) or not order.get('exchange_id'):return
        if order.get('cancel_404_at') and time.time()-order['cancel_404_at']<30:return
        try:self.exchange.cancel(order['exchange_id'],order['ticker'])
        except ExchangeFailure as error:
            if error.status!=404 or error.ambiguous:raise
            # Kalshi no longer finds this order on the DELETE route; it might
            # have filled, canceled, or moved before the request arrived.
            # A 404 does NOT prove zero resting exposure or authorize a retry.
            order.update(status='cancel_pending',cancel_404_at=time.time(),
                cancel_404_count=order.get('cancel_404_count',0)+1)
            self.save_order(order)
            self.record('cancel_verification_pending',order,
                'Kalshi did not find the order when cancellation was requested; verifying order and position history before any replacement',
                http_status=404,provider_code=error.provider_code)
            self.blocked.add(order['ticker']);self.recovered=False;self.last_reconcile=0
            print(json.dumps(dict(event='demo_cancel_not_found',ticker=order['ticker'],
                kind=order['kind'],http_status=404,account_verification_required=True)),flush=True)
            return
        order['remaining']=0
        order['status']='cancel_pending'
        self.save_order(order);self.record('cancel',order,reason)
        self.sync_pending=dict(action='canceled',bot=order['bot'],market=order['ticker'],at=time.time())
        self.recent_market_changes[order['ticker']]=self.sync_pending['at']
        # Reconcile races/fills before considering any replacement or released cash.
        self.recovered=False;self.last_reconcile=0
    def submit(self,intent):
        self.context_market=intent['ticker'];self.context_order=intent['client_id'];self.context_bot=intent['bot']
        # Durable intent precedes network write. Ambiguous writes are never replayed.
        self.save_order(intent);self.record('order_intent',intent,'Verified '+intent['kind']+' order prepared')
        reconcile_needed=True
        try:
            result=self.exchange.submit(intent)
            intent.update(exchange_id=result['order_id'],status='resting',remaining=number(result['remaining_count']),filled=number(result['fill_count']))
            self.save_order(intent);self.record('order',intent,'Kalshi Demo accepted '+('profit sell' if intent.get('exit_role')=='profit' else 'maker-only '+intent['kind']))
            self.sync_pending=dict(action='accepted',bot=intent['bot'],market=intent['ticker'],at=time.time())
            self.recent_market_changes[intent['ticker']]=self.sync_pending['at']
            opened=self.quotes.get(intent['ticker'],{}).get('open')
            print(json.dumps(dict(event='demo_order_accepted',kind=intent['kind'],bot=intent['bot'],ticker=intent['ticker'],seconds_since_open=round(time.time()-opened,2) if opened else None,asset=(intent.get('condition') or {}).get('asset'),exchange_index=intent.get('exchange_index'),remaining=intent['remaining'],filled=intent['filled'],price=intent['price'],side=intent['side'])),flush=True)
        except ExchangeFailure as error:
            if not error.ambiguous:intent['rejection_reason']=error.reason if error.code=='exchange_rejected' else None
            intent['status']='uncertain' if error.ambiguous else 'rejected';self.save_order(intent)
            self.record('order_uncertain' if error.ambiguous else 'order_rejected',intent,'Exchange confirmation incomplete' if error.ambiguous else 'Exchange rejected order',rejection_code=error.provider_code,rejection_reason=error.reason,http_status=error.status)
            if error.ambiguous:self.blocked.add(intent['ticker'])
            if not error.ambiguous and error.status==404:
                # Definitive rejection of this *new* order, not an uncertain
                # accepted order and not proof that some earlier order vanished.
                # Keep this attempt recorded; do not silently retry its ID or
                # let a stale quote initiate another order on the same market.
                q=self.quotes.get(intent['ticker'])
                if q:q['at']=0
                self.last_discovery=0;reconcile_needed=False
                print(json.dumps(dict(event='demo_submit_not_found',ticker=intent['ticker'],
                    kind=intent['kind'],http_status=404,definitively_rejected=True)),flush=True)
                return
            if not error.ambiguous and self.retry_cycle_rejection(intent):
                reconcile_needed=False
                return
            if not error.ambiguous and error.reason=='post_only':
                q=self.quotes.get(intent['ticker'],{})
                self.maker_retries[intent['ticker']]=dict(clock=q.get('clock'),seq=q.get('seq'),after=time.time()+.5)
                if intent['kind']=='entry':
                    key=f"{intent['ticker']}/{intent['square']}/{intent['side']}"
                    memory=self.states.get(intent['bot'],{}).get(key)
                    if memory:
                        memory.update(submitted=False,attempt=memory.get('attempt',0)+1)
                        self.store.put('trigger/'+intent['bot'],self.states[intent['bot']],parameters=dict(revision=intent['revision']))
                reconcile_needed=False
                return
            raise
        finally:
            if reconcile_needed:self.recovered=False;self.last_reconcile=0
    def upgrade_legacy_exits(self):
        legacy=[o for o in self.orders if o['kind']=='entry' and o.get('exit_triggered') and o.get('exit_reference')!='ask']
        if not legacy:return False
        if self.legacy_exit_evidence is None:
            with self.store.pool.connection() as c:
                rows=c.execute("""SELECT progress->'details' AS details FROM research_job
                    WHERE idempotency_key>='demo/event/' AND idempotency_key<'demo/event/zzzz'
                    AND parameters->>'kind'='exit_trigger' AND progress->'details'->>'client_id'=ANY(%s)
                    ORDER BY created_at DESC LIMIT 5001""",([o['client_id'] for o in legacy],)).fetchall()
            if len(rows)>5000:raise ExchangeFailure('exit_policy_reconciliation_capacity')
            self.legacy_exit_evidence={}
            for row in rows:
                d=row['details'] or {};self.legacy_exit_evidence.setdefault(d.get('client_id'),d)
        from .engine import side_quote
        for order in legacy:
            original=self.legacy_exit_evidence.get(order['client_id']) or {};q=original.get('quote') or {}
            # Reset only a proven old BID-only trigger that never met the new
            # ASK rule. Missing evidence retains its existing protective exit.
            known='bid' in q and 'ask' in q and original.get('threshold') is not None
            original_ask=side_quote(q,order['side'])[1] if known else None
            invalid=known and (not 0<original_ask<100 or original_ask>original['threshold'])
            children=[o for o in self.orders if o.get('parent')==order['client_id']]
            if invalid:
                if any(o['status']=='uncertain' for o in children):self.blocked.add(order['ticker']);continue
                for child in children:
                    if child.get('remaining',0)>0:
                        self.cancel(child,'Replacing an old BID-only exit with the requested ASK policy');return True
                order['exit_triggered']=False;order.pop('exit_ceiling_cents',None);order['exit_rule_started_at']=time.time()
                self.record('exit_policy_updated',order,'Old BID-only trigger cleared; protection now follows current ASK')
            order['exit_reference']='ask';self.save_order(order)
        return False
    def park_cycle_entry(self,order,message):
        if order.get('cancel_404_at') and time.time()-order['cancel_404_at']<30:return
        self.cancel(order,message)
        if order.get('status')=='cancel_pending':return
        if order.get('entry_strategy')!='buy_low_sell_high' or order.get('filled',0):return
        bot=next((b for b in self.bots if b['id']==order['bot'] and b['revision']==order['revision']),None)
        key=f"{order['ticker']}/{order['square']}/{order['side']}"
        memory=self.states.get(order['bot'],{}).get(key)
        if bot and memory and memory.get('cycle')==order['cycle']:
            memory.update(submitted=False,attempt=memory.get('attempt',0)+1)
            self.store.put('trigger/'+order['bot'],self.states[order['bot']],parameters=dict(revision=bot['revision']))
    def rearm_allocation_cancel(self,order):
        if not order.get('allocation_rearm') or order['status']!='closed' or order.get('filled',0) or order.get('remaining',0):return
        bot=next((b for b in self.bots if b['id']==order['bot'] and b['revision']==order['revision']),None)
        key=f"{order['ticker']}/{order['square']}/{order['side']}"
        memory=self.states.get(order['bot'],{}).get(key)
        if bot and memory and memory.get('cycle')==order['cycle'] and memory.get('submitted'):
            memory.update(submitted=False,attempt=memory.get('attempt',0)+1)
            self.store.put('trigger/'+bot['id'],self.states[bot['id']],parameters=dict(revision=bot['revision']))
    def trade(self):
        now=time.time();bots={b['id']:b for b in self.bots}
        for order in self.orders:self.remember_cycle_side(order)
        # Hard safety deadline: handle every outstanding low buy before new
        # entries or profit-sell scheduling. Keep filled lots and their sells.
        from .cycles import buy_cancel_deadline
        for order in self.orders:
            if order.get('entry_strategy')!='buy_low_sell_high' or order.get('kind')!='entry' or order.get('remaining',0)<=0:continue
            if order.get('status') in ('uncertain','intent','cancel_pending','closed','rejected'):continue
            deadline=buy_cancel_deadline(order,self.quotes.get(order['ticker']))
            if deadline is not None and now>=deadline:
                self.cancel(order,'Three-minute cutoff: cancel unfilled low buy while retaining any filled contracts')
                return
        if self.recovered and self.upgrade_legacy_exits():return
        for order in self.orders:
            if order.get('status')=='cancel_pending' or (order.get('cancel_404_at') and now-order['cancel_404_at']<30):continue
            if order['ticker'] in self.netting_pending and order['kind']=='exit' and order.get('remaining',0)>0:
                self.cancel(order,'Canceling sells before reconciling offsetting YES and NO fills');return
        from .cycles import park_reason,entry_block_reason
        market_orders={}
        for order in self.orders:market_orders.setdefault(order['ticker'],[]).append(order)
        for order in self.orders:
            if order.get('status')=='cancel_pending' or (order.get('cancel_404_at') and now-order['cancel_404_at']<30):continue
            reason=park_reason(order,market_orders[order['ticker']],self.cycle_locks.get(order['ticker']))
            if reason:
                self.park_cycle_entry(order,'Canceling a low bid outside the first filled side for this round' if reason=='side_lock' else 'Parking opposite low bid while filled inventory has a profit sell' if reason=='opposite_inventory' else 'Parking a low bid that would cross a bot profit sell')
                return
        exiting={o['ticker'] for o in self.orders if o.get('status') not in ('closed','rejected') and
            (o.get('kind')=='exit' and o.get('exit_role')!='profit' or o.get('kind')=='entry' and o.get('exit_triggered') and o.get('filled',0)>o.get('sold',0))}
        for order in self.orders:
            bot=bots.get(order['bot']);q=self.quotes.get(order['ticker'])
            if order.get('status') in ('uncertain','cancel_pending') or (order.get('cancel_404_at') and now-order['cancel_404_at']<30):continue
            if self.recovered and order.get('revision',(bot or {}).get('revision'))==(bot or {}).get('revision') and order['kind']=='entry' and order.get('remaining',0)>0 and bot and bot['config'].get('maximum_cents') is not None and order.get('entry_pricing')!='cap_v2':
                self.cancel(order,'Replacing the old fixed maximum with a capped calculated bid')
                if order.get('status')=='cancel_pending':return
                order['entry_pricing']='cap_v2';self.save_order(order)
                if not order.get('filled',0):
                    key=f"{order['ticker']}/{order['square']}/{order['side']}"
                    memory=self.states.get(order['bot'],{}).get(key)
                    if memory:
                        memory.update(submitted=False,attempt=memory.get('attempt',0)+1)
                        self.store.put('trigger/'+order['bot'],self.states[order['bot']],parameters=dict(revision=bot['revision']))
                return
            if order['kind']=='entry' and order.get('remaining',0)>0:
                explicitly_invalid=(not bot or bot['desired']!='running' or order['revision']!=bot['revision'] or now>=order['close'])
                fresh=q is not None and now-q['at']<=5
                is_cycle=order.get('entry_strategy')=='buy_low_sell_high'
                if bot and order['revision']==bot['revision'] and q and not is_cycle:
                    square=bot['config']['squares'][order['square']]
                    remaining_minutes=(q.get('entry_close',q['close'])-now)/60
                    explicitly_invalid=explicitly_invalid or not square['min_minutes']<remaining_minutes<=square['max_minutes']
                if bot and order['revision']==bot['revision'] and self.recovered and not is_cycle:
                    square=bot['config']['squares'][order['square']]
                    if square.get('maximum_cents') is not None and order['price']>square['maximum_cents']:
                        self.cancel(order,'Square maximum lowered below this resting entry bid')
                        if order.get('status')=='cancel_pending':return
                        if not order.get('filled',0):
                            key=f"{order['ticker']}/{order['square']}/{order['side']}"
                            memory=self.states.get(order['bot'],{}).get(key)
                            if memory:
                                memory.update(submitted=False,attempt=memory.get('attempt',0)+1)
                                self.store.put('trigger/'+order['bot'],self.states[order['bot']],parameters=dict(revision=bot['revision']))
                        return
                condition_invalid=fresh and bot and order['revision']==bot['revision'] and (not is_cycle and not qualifies(bot['config']['squares'][order['square']],q,order['side'],now,bot['config']['qualification']) or not entry_protection_matches(bot['config'],bot['config']['squares'][order['square']],q,order['side']))
                # A reconnect is not evidence that a resting bid is invalid.
                # Preserve it until fresh data verifies the condition or expiry.
                if explicitly_invalid or condition_invalid:self.cancel(order,'Entry no longer matches verified conditions');return
            if not bot or not q or now-q['at']>5 or now>=q['close'] or order['ticker'] in self.blocked or order['ticker'] in self.netting_pending:continue
            retry=self.maker_retries.get(order['ticker'])
            if retry and (now<retry['after'] or (q.get('clock'),q.get('seq'))==(retry['clock'],retry.get('seq'))):continue
            config=bot['config']
            if order.get('exit_role')=='profit':
                parent=next((o for o in self.orders if o.get('client_id')==order.get('parent')),None)
                if parent and parent.get('exit_triggered') and order.get('remaining',0)>0:
                    self.cancel(order,'Protective exit replaces the fixed profit sell');return
                continue
            if order['kind']=='exit' and order.get('remaining',0)>0:
                parent=next((o for o in self.orders if o.get('client_id')==order.get('parent')),None)
                ceiling=min(order['price'],parent.get('exit_ceiling_cents',99) if parent else 99)
                price=exit_price(q,order['side'],ceiling)
                if price is not None and price<order['price']:
                    if parent:parent['exit_ceiling_cents']=price;self.save_order(parent)
                    self.cancel(order,'Lowering protective maker exit as current ASK falls');return
            if order['kind']!='entry' or order.get('filled',0)<=order.get('sold',0):continue
            threshold=order_threshold(bot,order,q,now,self.research_stop)
            from .engine import side_quote
            bid,ask=side_quote(q,order['side'])
            if not 0<=bid<ask<=100:continue
            if not order.get('exit_triggered') and threshold is not None and 0<ask<100 and ask<=threshold:
                self.observe_exit_triggers(order['ticker'],now)
            if order.get('exit_triggered'):
                exiting.add(order['ticker'])
                for other in self.orders:
                    if other['ticker']==order['ticker'] and other['kind']=='entry' and other.get('remaining',0)>0:self.park_cycle_entry(other,'Protective exit blocks new entries');return
                if any(o['ticker']==order['ticker'] and o['kind']=='entry' and o.get('status') in ('intent','uncertain','cancel_pending') for o in self.orders):continue
                if any(o.get('parent')==order['client_id'] and o['status'] not in ('closed','rejected') for o in self.orders):continue
                price=exit_price(q,order['side'],order.get('exit_ceiling_cents'))
                if price and price>bid:
                    order['exit_ceiling_cents']=price
                    attempt=order.get('exit_attempt',0)+1;order['exit_attempt']=attempt;self.save_order(order)
                    identifier=str(uuid5(NAMESPACE_URL,f"demo-exit/{order['client_id']}/{attempt}"))
                    self.submit(dict(client_id=identifier,kind='exit',parent=order['client_id'],bot=order['bot'],revision=order['revision'],ticker=order['ticker'],side=order['side'],price=price,quantity=order['filled']-order.get('sold',0),close=q['close'],created_at=now,exit_reference='ask',status='intent',remaining=0,filled=0));return
            elif self.profit_sell(order,q,now):return
        if not self.recovered or now-self.last_reconcile>35:return
        retrying={t for t,r in self.maker_retries.items() if now<r['after'] or (self.quotes.get(t,{}).get('clock'),self.quotes.get(t,{}).get('seq'))==(r['clock'],r.get('seq'))}
        from .engine import fair_budget_config,fair_order_candidates,cycle_tranche
        running_count=max(1,sum(b['desired']=='running' and not b.get('archived') for b in self.bots))
        fair_configs={id:fair_budget_config(b['config'],running_count) for id,b in bots.items()}
        options=candidates(self.bots,self.quotes,self.states,now,self.blocked|exiting|retrying)
        # Preserve the established price/time/expected-ROI priority slots for
        # condition bots (notably sports). Rotate only low/high opportunities
        # within their own slots; fairness must not override ranked strategies.
        cycle_bots={id for id,b in bots.items() if b['config'].get('strategy')=='buy_low_sell_high'}
        market_cost={};bot_cost={}
        for order in self.orders:
            if order['kind']=='entry':
                cost=(order.get('remaining',0)+max(0,order.get('filled',0)-order.get('sold',0)))*order['price']
                market_cost[order['ticker']]=market_cost.get(order['ticker'],0)+cost
                bot_cost[order['bot']]=bot_cost.get(order['bot'],0)+cost
        cycle_queue=iter(fair_order_candidates([i for i in options if i['bot'] in cycle_bots],self.last_entry_bot,bot_cost))
        options=[next(cycle_queue) if i['bot'] in cycle_bots else i for i in options]
        equity=self.account['equity_cents']
        needs_coverage=any(i['bot'] in cycle_bots and not self.daily_guard(bots[i['bot']],now)
            and bot_cost.get(i['bot'],0)<cycle_tranche(fair_configs[i['bot']],equity,running_count)/2
            and not entry_block_reason(i,market_orders.get(i['ticker'],[]),i['ticker'] in self.netting_pending,self.cycle_locks.get(i['ticker']))
            for i in options)
        # Rebalancing yields entry slots between cancellations. Otherwise many
        # oversized historical bids could monopolize every trade pass.
        if now-getattr(self,'last_allocation_cancel',0)>=30:
            for order in sorted(self.orders,key=lambda o:o.get('remaining',0)*o.get('price',0),reverse=True):
                if (order.get('entry_strategy')!='buy_low_sell_high' or order.get('kind')!='entry'
                    or order.get('status')!='resting' or order.get('remaining',0)<=0
                    or order['ticker'] in self.blocked or order.get('exit_triggered')
                    or now-order.get('cancel_404_at',0)<30 or order['bot'] not in cycle_bots):continue
                tranche=cycle_tranche(fair_configs[order['bot']],equity,running_count)
                reserved=order['remaining']*order['price']
                allowed=quantity(fair_configs[order['bot']],order['price'],equity,
                    self.account['cash_cents']+reserved,
                    max(0,market_cost.get(order['ticker'],0)-reserved),
                    max(0,bot_cost.get(order['bot'],0)-reserved))
                over_cap=order['remaining']>allowed
                if over_cap or (running_count>1 and needs_coverage and reserved>max(order['price'],tranche*1.25)):
                    order['allocation_rearm']=True;self.save_order(order)
                    self.cancel(order,'Resizing an unfilled bid to current spending limits' if over_cap else 'Redistributing an oversized unfilled bid so more eligible bots can trade')
                    self.last_allocation_cancel=now
                    return
        direction={o['ticker']:o['side'] for o in self.orders if o['kind']=='entry' and (o.get('remaining',0)>0 or o.get('filled',0)>o.get('sold',0))}
        peers={};equity=self.account['equity_cents'];cash=self.account['cash_cents']
        for item in options:
            config=fair_configs[item['bot']]
            if config.get('strategy')=='buy_low_sell_high' and not self.daily_guard(bots[item['bot']],now) and not entry_block_reason(item,market_orders.get(item['ticker'],[]),item['ticker'] in self.netting_pending,self.cycle_locks.get(item['ticker'])):
                if quantity(config,item['price'],equity,cash,market_cost.get(item['ticker'],0),bot_cost.get(item['bot'],0))>0:
                    peers.setdefault(item['ticker'],[]).append(item)
        for item in options:
            self.context_market=item['ticker'];self.context_order=None;self.context_bot=item['bot']
            if len({o['ticker'] for o in self.orders})>=100 and item['ticker'] not in {o['ticker'] for o in self.orders}:continue
            if len(self.orders)>=490:continue
            bot=bots[item['bot']];config=fair_configs[item['bot']];equity=self.account['equity_cents']
            is_cycle=config.get('strategy')=='buy_low_sell_high'
            active_entries=[o for o in self.orders if o['kind']=='entry' and o['ticker']==item['ticker'] and o['status'] not in ('closed','rejected')]
            if item['ticker'] in self.netting_pending:continue
            if is_cycle:
                if entry_block_reason(item,market_orders.get(item['ticker'],[]),item['ticker'] in self.netting_pending,self.cycle_locks.get(item['ticker'])):continue
            else:
                if any(o.get('entry_strategy')=='buy_low_sell_high' for o in active_entries):continue
                if item['ticker'] in direction and direction[item['ticker']]!=item['side']:continue
            market=market_cost.get(item['ticker'],0);exposure=bot_cost.get(item['bot'],0)
            if self.daily_guard(bot,now):continue
            amount=quantity(config,item['price'],equity,self.account['cash_cents'],market,exposure)
            if is_cycle:
                from .cycles import shared_quantity
                amount=shared_quantity(item,peers.get(item['ticker'],[]),config,equity,cash,market,exposure)
                amount=min(amount,max(1,int(cycle_tranche(config,equity,running_count)/item['price'])))
            if amount<1:continue
            if self.funding is None:
                from .funding import ShardFunding
                self.funding=ShardFunding(self.store,self.exchange)
            shard=self.quotes[item['ticker']].get('exchange_index',0)
            from .funding import ShardFunding
            if isinstance(self.funding,ShardFunding):
                local_cash=self.funding.available_cash(shard,self.shard_reservations)
                if local_cash>=item['price']:
                    underserved={p['bot'] for p in options if p['bot'] in cycle_bots
                        and self.quotes[p['ticker']].get('exchange_index',0)==shard
                        and bot_cost.get(p['bot'],0)<=exposure
                        and not entry_block_reason(p,market_orders.get(p['ticker'],[]),p['ticker'] in self.netting_pending,self.cycle_locks.get(p['ticker']))
                        and not self.daily_guard(bots[p['bot']],now)}
                    amount=min(amount,max(1,int(local_cash/max(1,len(underserved))/item['price'])))
            target=amount*item['price'] if is_cycle else max(amount*item['price'],equity*config['bot_percent']/100-exposure)
            if not self.funding.ensure(shard,amount*item['price'],target,self.shard_reservations):continue
            # Funding requests take time: recheck prices and entry qualification
            # on the next stream tick before preparing any order.
            from .cycles import eligible
            still_matches=eligible(config,config['squares'][item['square']],self.quotes[item['ticker']],time.time()) if is_cycle else qualifies(config['squares'][item['square']],self.quotes[item['ticker']],item['side'],time.time(),config['qualification'])
            if time.time()-self.quotes[item['ticker']]['at']>5 or not still_matches:continue
            memory=self.states[item['bot']][item['key']];memory['submitted']=True
            self.store.put('trigger/'+item['bot'],self.states[item['bot']],parameters=dict(revision=bot['revision']))
            identifier=str(uuid5(NAMESPACE_URL,f"demo-entry/{item['bot']}/{bot['revision']}/{item['key']}/{item['cycle']}/{item['first_at']:.6f}/{memory.get('attempt',0)}"))
            extra=dict(entry_strategy='buy_low_sell_high',profit_target_cents=item['profit_target_cents'],entry_attempt=memory.get('attempt',0)) if is_cycle else {}
            extra['market_close_at']=self.quotes[item['ticker']].get('entry_close',self.quotes[item['ticker']]['close'])
            extra['market_trading_close_at']=self.quotes[item['ticker']]['close']
            end=self.quotes[item['ticker']].get('entry_close',self.quotes[item['ticker']]['close'])-(180 if is_cycle else 0)
            if is_cycle:self.last_entry_bot=item['bot']
            self.submit(dict(client_id=identifier,kind='entry',entry_pricing='cap_v2',condition=config['squares'][item['square']],exit_reference='ask',exchange_index=self.quotes[item['ticker']].get('exchange_index',0),bot=item['bot'],revision=bot['revision'],ticker=item['ticker'],side=item['side'],square=item['square'],cycle=item['cycle'],price=item['price'],quantity=amount,close=end,created_at=now,status='intent',remaining=0,filled=0,**extra));return
        for bot in self.bots:
            # Compare state before writing; quiet ticks produce no database writes.
            packed=json.dumps(self.states[bot['id']],sort_keys=True)
            if self.trigger_digest.get(bot['id'])!=packed:
                self.store.put('trigger/'+bot['id'],self.states[bot['id']],parameters=dict(revision=bot['revision']));self.trigger_digest[bot['id']]=packed
    def loop(self):
        from .reset import ResetController,ResetRequest,request_reset,ACTIVE
        self.reset_controller=ResetController(self.store,self.exchange)
        bootstrap=os.environ.get('DEMO_RESET_REQUEST_JSON')
        if bootstrap and not self.store.get('reset'):request_reset(self.store,ResetRequest.model_validate_json(bootstrap))
        next_reconcile=0;next_controls=0;maintenance_at=0;backoff=1;credential_check=0;credential_version=None
        try:
            while not self.stop.is_set():
                now=time.time()
                try:
                    self.context_market=self.context_order=self.context_bot=None
                    self.guard()
                    if now>=credential_check:
                        credential_check=now+30;record=self.store.get('credentials');changed=record['progress'].get('changed_at') if record else None
                        if credential_version is not None and changed!=credential_version:
                            signer=credentials(self.store,os.environ)
                            if signer:self.exchange.signer=signer;self.close_stream();self.recovered=False
                        credential_version=changed
                    self.stage='controls'
                    controls_due=now>=next_controls
                    if controls_due:self.load_bots();self.repair_rejected_entries();next_controls=now+5
                    request=self.store.get('refresh') if now>=next_controls-1 else None
                    if request and request['progress']['requested_at']>self.last_reconcile:self.last_reconcile=0
                    if self.reset_row and self.reset_row['progress'].get('state') in ACTIVE:
                        self.stage='reset'
                        if self.socket:self.close_stream()
                        self.reset_controller.step(self.reset_row)
                        self.recovered=False
                        self.health('resetting',self.reset_row['progress']['message'])
                        if now>=maintenance_at:
                            from .maintenance import maintenance
                            maintenance(self.store,os.environ,self.stop);maintenance_at=now+300
                        self.stop.wait(.5);continue
                    if controls_due:self.stage='reconciliation';self.poll_funding()
                    self.stage="discovery"
                    if self.pending_markets or now-self.last_discovery>=(2 if any(b['desired']=='running' and b['config'].get('strategy')=='buy_low_sell_high' for b in self.bots) else 5):self.discover()
                    self.stage="stream";self.stream()
                    self.stage="reconciliation"
                    if not self.recovered or now-self.last_reconcile>=30:self.reconcile()
                    self.stage='trade';self.trade();self.trading_health()
                    if self.socket and now-self.stream_last_pressure_at>=30:
                        pressure=self.socket.stats()
                        if pressure['messages']>=1024 or pressure['oldest_age_seconds']>=3:
                            print(json.dumps(dict(event='demo_stream_pressure',messages=pressure['messages'],
                                bytes=pressure['bytes'],oldest_age_seconds=pressure['oldest_age_seconds'],
                                peak_messages=pressure['peak_messages'])),flush=True)
                            self.stream_last_pressure_at=now
                    if now>=maintenance_at:
                        from .maintenance import maintenance
                        maintenance(self.store,os.environ,self.stop);maintenance_at=now+300
                    backoff=1
                except ExchangeFailure as error:
                    if self.stage=='stream' and error.code in ('stream_closed','stream_connection_lost'):
                        self.recover_feed(error)
                        self.stop.wait(min(3,backoff));backoff=min(4,backoff*2)
                        continue
                    if self.stage=='stream' and error.code.startswith('stream'):
                        self.mark_stream_failure(error.code)
                    print(json.dumps(dict(event='demo_exchange_failure',stage=self.stage,code=error.code,ambiguous=error.ambiguous,status=error.status,provider_code=error.provider_code,reason=error.reason)),flush=True)
                    self.recovered=False
                    from .diagnostics import exchange_issue
                    self.issue=exchange_issue(error,self.stage,market=self.context_market,order_id=self.context_order,bot=self.context_bot)
                    self.issue['at']=time.time()
                    self.store.alert('exchange',self.issue['summary']+' '+self.issue['action'],True)
                    self.health('attention',self.issue['summary'])
                    if error.code.startswith('stream') or error.code=='connection':self.close_stream()
                    self.stop.wait(backoff);backoff=min(60,backoff*2)
                except Exception as error:
                    print(json.dumps(dict(event='demo_runtime_failure',stage=self.stage,error_type=type(error).__name__,**close_details(error),frames=[dict(function=f.name,line=f.lineno) for f in traceback.extract_tb(error.__traceback__)[-4:]])),flush=True)
                    self.recovered=False;self.close_stream()
                    from .diagnostics import runtime_issue
                    self.issue=runtime_issue(self.stage,market=self.context_market,order_id=self.context_order,bot=self.context_bot)
                    self.issue['at']=time.time()
                    self.store.alert('recovery',self.issue['summary']+' '+self.issue['action'],True)
                    self.health('attention',self.issue['summary'])
                    self.stop.wait(backoff);backoff=min(60,backoff*2)
                self.stop.wait(.5)
        finally:
            self.close_stream();self.health('recovering','Worker restarting; preserve exchange orders for reconciliation')

def run(stop):
    from services.api.db_privileges import audit_database
    url=os.environ['DATABASE_URL']
    if not audit_database(url,'research')['privilege_boundary_ready']:raise RuntimeError('Runtime database is not ready')
    with ConnectionPool(url,min_size=1,max_size=3,kwargs=dict(row_factory=dict_row,connect_timeout=5,options='-c statement_timeout=5000')) as pool:
        store=DemoStore(pool)
        # Session advisory lock is held for the process lifetime; verify the same
        # connection before every write. DB loss aborts before any new order.
        with pool.connection() as lock:
            notice_at=0
            while True:
                acquired=lock.execute('SELECT pg_try_advisory_lock(%s) AS locked',(LOCK,)).fetchone()['locked']
                lock.commit()
                if acquired:break
                if time.time()>=notice_at:
                    latest=store.get('health')
                    bots=store.rows('bot/',100)
                    print(json.dumps(dict(event='demo_lock_wait',health=latest['progress'] if latest else None,
                        running=sum(r['progress'].get('desired')=='running' for r in bots),bots=len(bots))),flush=True)
                    notice_at=time.time()+60
                if stop.wait(5):return
            # The latest reported accidental reset is reversible only if all
            # copied bots are unused. This guard runs under the exclusive
            # worker fence and does not touch any exchange order or position.
            from .reset import undo_recent_incident
            undo_recent_incident(store)
            print(json.dumps(dict(event='demo_worker_ready',environment='demo',max_connections=3,watch_limit=100)),flush=True)
            # Retain legacy results/checkpoints but stop obsolete queued work so
            # collection analysis does not keep yielding to an absent replayer.
            with pool.connection() as c:
                c.execute("""UPDATE research_job SET status='cancelled',finished_at=clock_timestamp(),lease_token=NULL,lease_expires_at=NULL
                    WHERE status IN ('queued','running') AND
                    ((idempotency_key>='paper-replay/' AND idempotency_key<'paper-replay/zzzz')
                    OR (idempotency_key>='paper-live/' AND idempotency_key<'paper-live/zzzz'))""")
            def guard():
                if lock.closed:raise RuntimeError('Trading fence lost')
                result=lock.execute("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid() AND objid=%s) AS owned",(LOCK,)).fetchone()
                lock.commit()
                if not result['owned']:raise RuntimeError('Trading fence lost')
            try:
                next_maintenance=0;connection_notice=False
                while not stop.is_set():
                    signer=credentials(store,os.environ)
                    if signer:break
                    if not connection_notice:
                        print(json.dumps(dict(event='demo_connection_required',trading_active=False)),flush=True);connection_notice=True
                    store.put('health',dict(state='connection_required',message='Connect your Kalshi Demo API key to verify the account',at=time.time(),features=['square_bid_caps_v1','square_loss_prevention_v1','editable_rules_v1','buy_low_sell_high_v1','current_time_loss_v1']))
                    from .maintenance import maintenance
                    if time.time()>=next_maintenance:
                        maintenance(store,os.environ,stop);next_maintenance=time.time()+300
                    stop.wait(30)
                if stop.is_set():return
                exchange=Exchange(signer,guard=guard)
                try:Worker(store,exchange,stop,guard).loop()
                finally:exchange.close()
            finally:
                if not lock.closed:lock.execute('SELECT pg_advisory_unlock(%s)',(LOCK,));lock.commit()
