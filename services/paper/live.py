"""Bounded live paper ledger. Pure simulation: no network or exchange orders.

All prices and cash are integer cents; results exclude fees. A trade-through
proxy is evidence for a simulated fill, never proof of an achievable maker fill.
"""
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_CEILING
from .portfolio import proposed_bid
from .rules import matching_rule

MAX_MARKETS=100
MAX_ORDERS=100
MAX_POSITIONS=200
MAX_SESSION_ORDERS=10000
FRESH_SECONDS=10


def price(value,*,ask=False):
    try:
        v=Decimal(str(value))*100
        if not v.is_finite() or not 0<=v<=100:return None
        return int(v.to_integral_value(rounding=ROUND_CEILING if ask else ROUND_FLOOR))
    except (InvalidOperation,ValueError,TypeError):return None


def initial(cash):
    return dict(version=1,cash=cash,starting_cash=cash,orders=[],positions=[],markets={},
        attempted={},recent=[],seen_trades=[],sequence=0,orders_placed=0,filled_contracts=0,
        realized_pnl=0,feed='waiting for feed',stopping=False,gaps=0,provider_reads=0,
        skipped_stale=0,capacity_limited=False,quotes={},last_message_at=None)


def lifecycle(m,msg):
    """Apply lifecycle hints; settlement still requires an explicit result."""
    kind=msg.get('event_type')
    if kind=='deactivated':m['status']='closed'
    elif kind=='activated':m['status']='active'
    elif kind=='settled':m['status']='settled'
    if kind in ('deactivated','settled','close_date_updated','activated'):
        close=msg.get('close_ts')
        if isinstance(close,(int,float)) and close>0:m['close']=close
        if kind=='settled' and msg.get('result') in ('yes','no'):m['result']=msg['result']


class Ledger:
    def __init__(self,state,strategies,fill_model='conservative'):
        self.s=state;self.strategies=strategies;self.fill_model=fill_model;self.events=[]

    def log(self,kind,now,**data):
        self.s['sequence']+=1
        row=dict(sequence=self.s['sequence'],kind=kind,time=now,**data)
        self.events.append(row);self.s['recent']=(self.s['recent']+[row])[-40:]

    def exposure(self,event=None):
        return sum(o['remaining']*o['bid'] for o in self.s['orders'] if event is None or o['event']==event)+sum(p['cost'] for p in self.s['positions'] if event is None or p['event']==event)

    def equity(self):return self.s['cash']+self.exposure()

    def cancel(self,o,now,reason):
        if not o['remaining']:return
        self.s['cash']+=o['remaining']*o['bid']
        self.log('cancel',now,order_id=o['id'],ticker=o['ticker'],contracts=o['remaining'],reason=reason)
        o['remaining']=0

    def suspend(self,now,reason='feed gap'):
        for o in self.s['orders']:self.cancel(o,now,reason)
        self.s['orders']=[];self.s['quotes']={};self.s['feed']=reason;self.s['gaps']+=1
        self.log('feed_gap',now,reason=reason)

    def stop(self,now):
        self.s['stopping']=True
        for o in self.s['orders']:self.cancel(o,now,'stopped by you')
        self.s['orders']=[]
        self.log('stop',now,reason='No new bids; filled positions remain monitored through settlement')

    def tick(self,now):
        for o in self.s['orders']:
            m=self.s['markets'].get(o['ticker'],{})
            if now>=o['expires'] or m.get('status') not in ('open','active'):self.cancel(o,now,'market period ended')
        self.s['orders']=[o for o in self.s['orders'] if o['remaining']]
        remaining=[]
        for p in self.s['positions']:
            m=self.s['markets'].get(p['ticker'],{});result=m.get('result')
            # A projected close is not a settlement. Credit only confirmed result.
            if result in ('yes','no') and m.get('status') in ('settled','finalized'):
                paid=100*p['quantity'] if result==p['side'] else 0
                self.s['cash']+=paid;self.s['realized_pnl']+=paid-p['cost']
                self.log('settlement',now,order_id=p['id'],ticker=p['ticker'],contracts=p['quantity'],
                    result=result,profit_loss_cents=paid-p['cost'])
            else:remaining.append(p)
        self.s['positions']=remaining
        pinned={o['ticker'] for o in self.s['orders']}|{p['ticker'] for p in remaining}
        for ticker,m in list(self.s['markets'].items()):
            if now>m['close']+60 and ticker not in pinned:
                self.s['markets'].pop(ticker);self.s['quotes'].pop(ticker,None);self.s['attempted'].pop(ticker,None)
        if self.s['orders_placed']>=MAX_SESSION_ORDERS:self.s['stopping']=True;self.s['capacity_limited']=True

    def fill(self,o,quantity,now,evidence):
        if quantity<=0:return
        existing=next((p for p in self.s['positions'] if p['id']==o['id']),None)
        if existing is None:
            if len(self.s['positions'])>=MAX_POSITIONS:
                self.s['capacity_limited']=True;return
            existing=dict(id=o['id'],ticker=o['ticker'],event=o['event'],side=o['side'],quantity=0,
                cost=0,stop=o['stop'],bid=o['bid'],strategy=o['strategy'])
            self.s['positions'].append(existing)
        o['remaining']-=quantity;existing['quantity']+=quantity;existing['cost']+=quantity*o['bid']
        self.s['filled_contracts']+=quantity
        self.log('fill',now,order_id=o['id'],ticker=o['ticker'],side=o['side'],bid_cents=o['bid'],
            contracts=quantity,remaining=o['remaining'],evidence=evidence)

    def trade(self,msg,now):
        ticker=msg.get('market_ticker');trade_id=msg.get('trade_id')
        if not any(o['ticker']==ticker and o['remaining'] for o in self.s['orders']):return
        if not isinstance(trade_id,str) or not 1<=len(trade_id)<=128 or trade_id in self.s['seen_trades']:return
        ts=msg.get('ts_ms',0)/1000 if isinstance(msg.get('ts_ms'),(int,float)) else msg.get('ts')
        if not isinstance(ts,(int,float)) or not now-10<=ts<=now+2:return
        if msg.get('is_block_trade') or msg.get('taker_outcome_side',msg.get('taker_side')) not in ('yes','no'):return
        try:
            count=Decimal(str(msg.get('count_fp','0')))
            if not count.is_finite() or not 0<count<=100000000:return
            available=int(count)
        except (InvalidOperation,ValueError):return
        self.s['seen_trades']=(self.s['seen_trades']+[trade_id])[-512:]
        for o in sorted(self.s['orders'],key=lambda o:(-o['bid'],-o['priority'],o['created'])):
            if not available:break
            if o['ticker']!=ticker or ts<o['created']+2 or ts>=o['expires']:continue
            if msg.get('taker_outcome_side',msg.get('taker_side'))==o['side']:continue
            p=price(msg.get(o['side']+'_price_dollars'),ask=True)
            if p is None or p>o['bid'] or (self.fill_model=='conservative' and p==o['bid']):continue
            qty=min(available,o['remaining']);before=o['remaining']
            self.fill(o,qty,now,'trade-through proxy' if p<o['bid'] else 'at-price volume estimate; queue unknown')
            available-=before-o['remaining']
        self.s['orders']=[o for o in self.s['orders'] if o['remaining']]

    def quote(self,msg,now):
        ticker=msg.get('market_ticker')
        if ticker not in self.s['markets']:return
        ts=msg.get('ts_ms',0)/1000 if isinstance(msg.get('ts_ms'),(int,float)) else msg.get('ts')
        if not isinstance(ts,(int,float)) or not now-FRESH_SECONDS<=ts<=now+2:
            self.s['skipped_stale']+=1;return
        bid=price(msg.get('yes_bid_dollars'));ask=price(msg.get('yes_ask_dollars'),ask=True)
        if bid is None or ask is None or not 0<=bid<ask<=100:return
        if now>=self.s['markets'][ticker]['close'] or self.s['markets'][ticker]['status'] not in ('open','active'):return
        previous=self.s['quotes'].get(ticker)
        if previous and ts<previous['time']:return
        sizes={}
        for side,field in (('yes','yes_bid_size_fp'),('no','yes_ask_size_fp')):
            try:
                v=Decimal(str(msg.get(field,'0')));sizes[side]=int(v) if v.is_finite() and 0<=v<=100000000 else 0
            except (InvalidOperation,ValueError):sizes[side]=0
        quote=dict(time=ts,yes_bid=bid,yes_ask=ask,sizes=sizes)
        self.s['quotes'][ticker]=quote
        # Depth is consumed once per timestamp across all positions. Duplicate
        # quotes cannot repeatedly sell against the same displayed quantity.
        consumed=self.s.setdefault('sale_depth',{}).get(ticker,{})
        if consumed.get('time')!=ts:consumed=dict(time=ts,yes=0,no=0)
        for p in list(self.s['positions']):
            if p['ticker']!=ticker or p['stop'] is None:continue
            sale=bid if p['side']=='yes' else 100-ask
            if sale>p['stop']:continue
            qty=min(p['quantity'],max(0,sizes[p['side']]-consumed[p['side']]))
            if not qty:continue
            cost=p['bid']*qty;self.s['cash']+=sale*qty;self.s['realized_pnl']+=sale*qty-cost
            p['quantity']-=qty;p['cost']-=cost;consumed[p['side']]+=qty
            self.log('loss_prevention_sale',now,order_id=p['id'],ticker=ticker,side=p['side'],contracts=qty,
                sale_cents=sale,profit_loss_cents=sale*qty-cost,evidence='displayed bid and size; simulated sale')
        self.s['positions']=[p for p in self.s['positions'] if p['quantity']]
        if consumed['yes'] or consumed['no']:self.s.setdefault('sale_depth',{})[ticker]=consumed

    def enter(self,now):
        if self.s['stopping'] or self.s['feed']!='connected':return
        opportunities=[]
        for ticker,m in self.s['markets'].items():
            q=self.s['quotes'].get(ticker)
            if not q or now-q['time']>FRESH_SECONDS or not now<m['close']<=now+86400 or m['status'] not in ('open','active'):continue
            side='yes' if q['yes_bid']>=100-q['yes_ask'] else 'no'
            bid=q['yes_bid'] if side=='yes' else 100-q['yes_ask']
            ask=q['yes_ask'] if side=='yes' else 100-q['yes_bid']
            for i,s in enumerate(self.strategies):
                if str(i) in self.s['attempted'].get(ticker,[]):continue
                if m['series'] not in s['series']:continue
                if matching_rule(s,ask,(m['close']-now)/60):
                    opportunities.append((-s['statistical_yield_percent'],m['close'],ticker,i,side,bid,ask))
        for _,_,ticker,i,side,best_bid,ask in sorted(opportunities):
            if len(self.s['orders'])>=MAX_ORDERS or len(self.s['positions'])>=MAX_POSITIONS or self.s['orders_placed']>=MAX_SESSION_ORDERS:
                self.s['capacity_limited']=True;break
            s=self.strategies[i];m=self.s['markets'][ticker];bid=proposed_bid(ask,s,best_bid)
            if not 1<=bid<ask:continue
            bankroll=self.equity();desired=min(s['contracts']*bid,bankroll*s['balance_percent']//100,bankroll//10)
            for o in sorted(self.s['orders'],key=lambda o:o['priority']):
                if o['priority']>=s['statistical_yield_percent']:continue
                if self.s['cash']<desired or (o['event']==m['event'] and bankroll//10-self.exposure(m['event'])<desired):self.cancel(o,now,'higher-yield opportunity')
            self.s['orders']=[o for o in self.s['orders'] if o['remaining']]
            qty=min(s['contracts'],min(self.s['cash'],bankroll//10-self.exposure(m['event']),bankroll*s['balance_percent']//100)//bid)
            if qty<1:continue
            self.s['cash']-=qty*bid;self.s['orders_placed']+=1
            o=dict(id='live-'+str(self.s['orders_placed']),ticker=ticker,event=m['event'],side=side,bid=bid,
                quantity=qty,remaining=qty,created=now,expires=m['close'],priority=s['statistical_yield_percent'],
                stop=s.get('loss_trigger_cents'),strategy=i)
            self.s['orders'].append(o);self.s['attempted'].setdefault(ticker,[]).append(str(i))
            self.log('bid',now,order_id=o['id'],ticker=ticker,event=m['event'],side=side,bid_cents=bid,
                contracts=qty,expires=m['close'],strategy=s['name'])
            if self.fill_model=='all_filled':self.fill(o,qty,now,'optimistic assumption: every bid fills; NOT a realistic fill estimate')
        self.s['orders']=[o for o in self.s['orders'] if o['remaining']]

    def apply(self,messages,now):
        self.tick(now)
        for msg in messages:
            if msg.get('type')=='ticker':self.quote(msg.get('msg',{}),now)
            elif msg.get('type')=='trade':self.trade(msg.get('msg',{}),now)
            elif msg.get('type')=='market_lifecycle_v2':
                body=msg.get('msg',{});m=self.s['markets'].get(body.get('market_ticker'))
                if m:
                    lifecycle(m,body)
                    if m['status'] not in ('open','active'):
                        for o in self.s['orders']:
                            if o['ticker']==m['ticker']:self.cancel(o,now,'market lifecycle changed')
        self.enter(now);self.tick(now)
        # Prune depth bookkeeping with market lifetime.
        self.s['sale_depth']={k:v for k,v in self.s.get('sale_depth',{}).items() if k in self.s['markets']}


def public_state(state):
    view={k:v for k,v in state.items() if k not in ('markets','quotes','attempted','seen_trades','sale_depth','orders','positions')}
    # Internal event keys and ranking fields are not needed by the cards.
    # Project rows explicitly so worst-case provider identifiers still fit the
    # gateway's existing 256 KiB response limit at full position capacity.
    view['orders']=[{k:o[k] for k in ('id','ticker','side','bid','quantity','remaining','expires')} for o in state.get('orders',[])]
    view['positions']=[{k:p[k] for k in ('id','ticker','side','quantity','cost','stop','bid')} for p in state.get('positions',[])]
    return view
