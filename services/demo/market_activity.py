"""Entry-only availability checks; positions and verification never pause."""
import math,time
from decimal import Decimal
from services.research.reports import SERIES
INACTIVE_RECHECK_SECONDS=15*60

def external_book_ready(book,orders,ticker):
    if not book:return False
    owned={'yes':{},'no':{}}
    for order in orders:
        if order['ticker']!=ticker or order.get('remaining',0)<=0 or order.get('status') in ('closed','rejected'):continue
        side=order['side'];price=Decimal(str(order['price']))/100
        if order['kind']=='exit':side='no' if side=='yes' else 'yes';price=1-price
        owned[side][price]=owned[side].get(price,Decimal(0))+Decimal(str(order['remaining']))
    return all(any(size-owned[side].get(price,Decimal(0))>0 for price,size in book[side].items()) for side in ('yes','no'))

class MarketActivityMixin:
    def restore_market_activity(self):
        row=self.store.get('market_activity')
        if row and row['progress'].get('source')=='public_rest_v3':
            saved=row['progress']
            self.market_seen_active=saved.get('seen_active',{})
            self.market_inactive=saved.get('inactive',{})
            self.market_probe_at={s:v['retry_at'] for s,v in self.market_inactive.items()}
            self.demo_trading_status=saved.get('demo_status')
            self.demo_status_next=saved.get('demo_status_next',0)

    def save_market_activity(self):
        self.store.put('market_activity',dict(source='public_rest_v3',seen_active=self.market_seen_active,inactive=self.market_inactive,
            demo_status=self.demo_trading_status,demo_status_next=self.demo_status_next))

    def demo_trading_allowed(self,quote,now):
        status=self.demo_trading_status
        if not status or now>=self.demo_status_next:return False
        index=quote.get('exchange_index',0)
        return next((s.get('trading_active') is True for s in status.get('exchange_index_statuses',[]) if s.get('exchange_index')==index),status.get('trading_active') is True)

    def check_demo_trading(self,now):
        if now<self.demo_status_next:return
        from .exchange import ExchangeFailure
        try:
            status=self.exchange.call('GET','/exchange/status')
            if not isinstance(status,dict) or not isinstance(status.get('trading_active'),bool):raise ExchangeFailure('invalid_page')
            self.demo_trading_status=status
            self.demo_status_next=now+(30 if status['trading_active'] else INACTIVE_RECHECK_SECONDS)
            self.save_market_activity()
            import json
            print(json.dumps(dict(event='demo_exchange_trading_status',trading_active=status['trading_active'],retry_seconds=self.demo_status_next-now)),flush=True)
        except ExchangeFailure:
            self.demo_trading_status=None;self.demo_status_next=now+30

    def market_entry_ready(self,config,ticker):
        if not config.get('require_active_market'):return True
        q=self.quotes.get(ticker,{})
        return self.demo_trading_allowed(q,time.time()) and q.get('market_activity_ready') is True and q.get('series') not in self.market_inactive

    def refresh_market_activity(self,now):
        # Activity comes only from direct REST evidence. Stream gaps and thin
        # books are execution prerequisites, never evidence of inactivity.
        for ticker,q in self.quotes.items():
            evidence=self.market_api_activity.get(q['series'],{})
            q['market_activity_ready']=ticker in evidence.get('tickers',[]) and now-evidence.get('at',0)<=60
            q['market_inactive_reason']=self.market_inactive.get(q['series'],{}).get('reason')
            if self.demo_trading_status and not self.demo_trading_allowed(q,min(now,self.demo_status_next-.001)):
                q['market_inactive_reason']='Kalshi Demo trading paused or awaiting exchange-status verification.'

    def probe_market_activity(self,now):
        from .runtime import quote
        from .exchange import ExchangeFailure
        wanted={series for b in self.bots if b['desired']=='running' and b['config'].get('require_active_market')
            for square in b['config']['squares'] for series in SERIES[square['asset']]}
        if not wanted:return
        self.check_demo_trading(now)
        if not self.demo_trading_status or not self.demo_trading_status.get('trading_active'):return
        due=[s for s in wanted if self.market_probe_at.get(s,0)<=now and self.market_api_next.get(s,0)<=now]
        if not due:return
        # Active series go first; other probes are bounded to one per turn.
        series=min(due,key=lambda s:(s not in self.market_seen_active,self.market_api_next.get(s,0),s))
        self.market_api_next[series]=now+5
        try:
            page=self.exchange.market_activity_call('GET','/markets',params=dict(series_ticker=series,status='open',limit=200,min_close_ts=int(now),max_close_ts=int(now+900)))
            rows=page.get('markets')
            if not isinstance(rows,list) or len(rows)>200:raise ExchangeFailure('invalid_page')
            current=[]
            for raw in rows:
                parsed=quote(raw,now)
                if not parsed:raise ExchangeFailure('invalid_page')
                ticker,q=parsed
                if q['series']==series and q.get('status')=='active' and q.get('open',now+1)<=now<q['entry_close']:
                    current.append((ticker,q))
            if page.get('cursor'):return # Incomplete evidence never proves absent.
            if len(current)>3:raise ExchangeFailure('discovery_capacity')
            fingerprint={t:[q['bid'],q['ask'],q.get('market_volume')] for t,q in current}
            for ticker,q in current:
                if q.get('market_volume',0):continue
                result=self.exchange.market_activity_call('GET','/markets/'+ticker+'/orderbook',params=dict(depth=1))
                book=result.get('orderbook_fp')
                if not isinstance(book,dict):raise ExchangeFailure('invalid_page')
                levels=[]
                for side in ('yes_dollars','no_dollars'):
                    values=book.get(side)
                    if not isinstance(values,list) or len(values)>100:raise ExchangeFailure('invalid_page')
                    levels.append(sorted(values))
                fingerprint[ticker].extend(levels)
            prior=self.market_api_samples.get(series)
            active=[];basis=[]
            for ticker,q in current:
                volume=q.get('market_volume')
                moved=prior and ticker in prior['prices'] and prior['prices'][ticker]!=fingerprint[ticker]
                if moved or isinstance(volume,(int,float)) and math.isfinite(volume) and volume>0:
                    active.append(ticker);basis.append('price_movement' if moved else 'reported_trades')
            if current and not active:
                # Compare two API observations before calling a quiet book
                # inactive; recent executions independently prove activity.
                if not prior or set(prior['prices'])!=set(fingerprint):
                    self.market_api_samples[series]=dict(at=now,prices=fingerprint)
                    self.market_api_next[series]=now+2;return
                for ticker,q in current:
                    trades=self.exchange.market_activity_call('GET','/markets/trades',params=dict(ticker=ticker,min_ts=int(max(q['open'],now-900)),limit=1))
                    if not isinstance(trades.get('trades'),list):raise ExchangeFailure('invalid_page')
                    if any(t.get('ticker')==ticker for t in trades['trades']):active.append(ticker);basis.append('recent_trade')
                if not active and now-prior['at']<5:
                    self.market_api_next[series]=now+2;return
            self.market_api_samples[series]=dict(at=now,prices=fingerprint)
            self.market_api_activity[series]=dict(at=now,tickers=active)
            if active:
                self.market_seen_active[series]=now
                self.market_inactive.pop(series,None);self.market_probe_at.pop(series,None)
                self.market_api_next[series]=min(now+30,min(q['entry_close'] for t,q in current if t in active))
            else:
                reason='API reports no current running round.' if not current else 'API reports no trades or price movement in the current round.'
                self.market_probe_at[series]=now+INACTIVE_RECHECK_SECONDS
                self.market_inactive[series]=dict(reason=reason,retry_at=now+INACTIVE_RECHECK_SECONDS)
            self.save_market_activity();self.refresh_market_activity(now)
            import json
            print(json.dumps(dict(event='demo_market_activity_api',source='public_rest',series=series,active=bool(active),markets=len(current),evidence=sorted(set(basis)),retry_seconds=30 if active else INACTIVE_RECHECK_SECONDS)),flush=True)
        except ExchangeFailure as error:
            # API failure means verification pending, never confirmed inactive.
            if error.code=='authentication':raise
            self.market_api_next[series]=now+30
            import json
            print(json.dumps(dict(event='demo_market_activity_api_pending',series=series,code=error.code)),flush=True)

    def inactive_bot(self,bot):
        if not bot['config'].get('require_active_market'):return None
        selected={s for square in bot['config']['squares'] for s in SERIES[square['asset']]}
        quotes=[q for q in self.quotes.values() if q['series'] in selected]
        paused=self.demo_trading_status and (all(not self.demo_trading_allowed(q,min(time.time(),self.demo_status_next-.001)) for q in quotes) if quotes else not self.demo_trading_status.get('trading_active'))
        if paused:
            return dict(reason='Kalshi Demo trading paused: the Demo exchange reports trading_active=false.',retry_at=self.demo_status_next,
                action='No new buys are placed. Exchange status is checked again in 15 minutes; existing positions remain monitored.')
        series={s for square in bot['config']['squares'] for s in SERIES[square['asset']]}
        if not series or not all(s in self.market_inactive for s in series):return None
        issues=[self.market_inactive[s] for s in sorted(series)]
        return dict(reason=issues[0]['reason'],retry_at=min(i['retry_at'] for i in issues),
            action='No buys are placed while inactive. Waiting buys are canceled; other bots can use the cash. Activity is rechecked every 15 minutes; existing positions remain monitored.')
