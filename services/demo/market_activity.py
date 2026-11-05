"""Entry-only availability checks; positions and verification never pause."""
import math
from decimal import Decimal
from services.research.reports import SERIES

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
    def market_entry_ready(self,config,ticker):
        if not config.get('require_active_market'):return True
        q=self.quotes.get(ticker,{})
        return (q.get('market_activity_ready') is True and q.get('series') not in self.market_inactive
            and external_book_ready(self.books.books.get(ticker),self.orders,ticker))

    def refresh_market_activity(self,now):
        if now<self.next_activity_check:return
        self.next_activity_check=now+1
        wanted={series for b in self.bots if b['desired']=='running' and b['config'].get('require_active_market')
            for s in b['config']['squares'] for series in SERIES[s['asset']]}
        for series in wanted:
            if self.market_probe_at.get(series,0)>now:continue
            if series in self.market_inactive and series not in self.market_probe_started:
                self.market_probe_started[series]=now
            rows=[(t,q) for t,q in self.quotes.items() if q['series']==series and q.get('status')=='active'
                and q.get('open',now+1)<=now<q.get('entry_close',q['close'])
                and (not series.endswith('15M') or q.get('entry_close',q['close'])-now<=900)]
            verified=[(t,q) for t,q in rows if q.get('source')=='orderbook' and q.get('book_verified') and 0<=now-q.get('at',0)<=5]
            reason=None
            if not rows:
                if now-self.market_probe_started.get(series,self.started_at)<30:continue
                reason='No current active market is available for this bot.'
            elif not verified:
                continue # A reconnect cannot prove a resting bid is invalid.
            else:
                live=False
                for ticker,q in verified:
                    volume=q.get('market_volume')
                    zero_volume=isinstance(volume,(int,float)) and math.isfinite(volume) and volume==0 and now-q.get('open',now)>=60
                    external=external_book_ready(self.books.books.get(ticker),self.orders,ticker)
                    q['market_activity_ready']=external and not zero_volume
                    q['market_inactive_reason']=None if q['market_activity_ready'] else 'No external two-sided liquidity.' if not external else 'No trades reported after the opening minute.'
                    live=live or q['market_activity_ready']
                if not live:reason='No usable external liquidity or trading activity in the current market.'
            if reason:
                self.market_probe_at[series]=now+60
                self.market_probe_started.pop(series,None)
                self.market_inactive[series]=dict(reason=reason,retry_at=now+60)
            else:
                self.market_probe_at.pop(series,None);self.market_inactive.pop(series,None)
                self.market_probe_started.pop(series,None)
        self.market_inactive={s:v for s,v in self.market_inactive.items() if s in wanted}
        self.market_probe_at={s:v for s,v in self.market_probe_at.items() if s in wanted}

    def inactive_bot(self,bot):
        if not bot['config'].get('require_active_market'):return None
        series={s for square in bot['config']['squares'] for s in SERIES[square['asset']]}
        if not series or not all(s in self.market_inactive for s in series):return None
        issues=[self.market_inactive[s] for s in sorted(series)]
        return dict(reason=issues[0]['reason'],retry_at=min(i['retry_at'] for i in issues),
            action='Waiting buys are canceled; other bots can use the cash. Activity is rechecked every minute; existing positions remain monitored.')
