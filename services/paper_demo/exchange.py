"""Production GET-only data adapter; virtual portfolio routes never touch HTTP."""
import re,time,json
from datetime import datetime
from cryptography.fernet import Fernet
import httpx
from services.demo.exchange import DemoSigner,ExchangeFailure,PATH,PUBLIC_ACTIVITY_ROOT
from .model import D,decimal,charge
from .ledger import Ledger,rows,get,wire
from .read_budget import PRODUCTION_READS

WS='wss://external-api-ws.kalshi.com/trade-api/ws/v2'

def credentials(store,env):
    row=store.get('paper-credentials')
    if not row or not env.get('DEMO_VAULT_KEY'):return None
    data=json.loads(Fernet(env['DEMO_VAULT_KEY'].encode()).decrypt(row['progress']['encrypted'].encode()))
    return DemoSigner(data['key_id'],data['pem'])

class ProductionData:
    """The only HTTP entry point is GET, with a strict market-data allowlist."""
    def __init__(self,signer=None,client=None):
        self.signer=signer;self.client=client or httpx.Client(timeout=httpx.Timeout(8,connect=5),follow_redirects=False)
        self.reads=0;self.cooldown=0;self.next_read=0;self.before_read=None
    def close(self):self.client.close()
    def call(self,method,path,params=None):
        if method!='GET' or not (path in ('/milestones','/events','/markets','/markets/trades','/series/fee_changes','/events/fee_changes','/exchange/status','/api_keys','/account/limits') or re.fullmatch(r'/(?:markets/[A-Za-z0-9][A-Za-z0-9.-]{0,127}(?:/orderbook)?|series/[A-Za-z0-9-]{1,128}|live_data/milestone/[A-Za-z0-9-]{1,128})',path)):
            raise ExchangeFailure('paper_network_write_forbidden')
        if self.before_read:self.before_read()
        if time.monotonic()<self.cooldown:raise ExchangeFailure('paper_data_rate_limited')
        PRODUCTION_READS.wait()
        self.next_read=time.monotonic()+.05;self.reads+=1
        headers=self.signer.headers('GET',PATH+path) if self.signer else {}
        try:
            with self.client.stream('GET',PUBLIC_ACTIVITY_ROOT+PATH+path,params=params,headers=headers) as response:
                if response.status_code==429:
                    self.cooldown=time.monotonic()+30;PRODUCTION_READS.reject()
                if response.status_code!=200:raise ExchangeFailure('paper_data_unavailable',status=response.status_code)
                payload=bytearray()
                for chunk in response.iter_bytes():
                    payload.extend(chunk)
                    if len(payload)>4*1024*1024:raise ExchangeFailure('paper_data_capacity')
                data=json.loads(payload)
                if not isinstance(data,dict):raise ValueError()
                return data
        except (httpx.HTTPError,ValueError):raise ExchangeFailure('paper_data_unavailable') from None

class Fees:
    def __init__(self,data):self.data=data;self.cache={};self.series={}
    def load(self,ticker,market,now):
        series=market.get('series_ticker') or ticker.split('-')[0];event=market['event_ticker']
        cached=self.series.get(series)
        if not cached or now-cached['at']>30:
            raw=self.data.call('GET','/series/'+series).get('series',{})
            change=self.data.call('GET','/series/fee_changes',dict(series_ticker=series)).get('series_fee_change_arr')
            if not isinstance(change,list) or len(change)>1000:raise ExchangeFailure('paper_fee_schedule_unknown')
            cached=dict(at=now,base=(raw.get('fee_type'),raw.get('fee_multiplier')),changes=change);self.series[series]=cached
        events=[];cursor=None
        for _ in range(5):
            page=self.data.call('GET','/events/fee_changes',dict(event_ticker=event,limit=200,**({'cursor':cursor} if cursor else {})))
            changes=page.get('event_fee_changes')
            if not isinstance(changes,list) or len(changes)>200:raise ExchangeFailure('paper_fee_schedule_unknown')
            events.extend(changes);nxt=page.get('cursor')
            if not nxt:break
            if nxt==cursor:raise ExchangeFailure('paper_fee_schedule_unknown')
            cursor=nxt
        else:raise ExchangeFailure('paper_fee_schedule_unknown')
        try:
            for change in cached['changes']+events:
                if not isinstance(change.get('scheduled_ts'),str):raise ValueError()
                datetime.fromisoformat(change['scheduled_ts'].replace('Z','+00:00')).timestamp()
            state=dict(at=now,base=cached['base'],changes=cached['changes'],events=events)
            self.cache[ticker]=state;self.schedule(ticker,now)
        except (TypeError,ValueError,KeyError):self.cache.pop(ticker,None);raise ExchangeFailure('paper_fee_schedule_unknown') from None
    def schedule(self,ticker,at):
        saved=self.cache.get(ticker)
        if not saved or time.time()-saved['at']>60:raise ExchangeFailure('paper_fee_schedule_stale')
        resolved=saved.get('resolved')
        if resolved and resolved[0]<=at<resolved[1]:return resolved[2],resolved[3]
        def effective(rows):return sorted((r for r in rows if datetime.fromisoformat(r['scheduled_ts'].replace('Z','+00:00')).timestamp()<=at),key=lambda r:datetime.fromisoformat(r['scheduled_ts'].replace('Z','+00:00')).timestamp())
        kind,multiplier=saved['base']
        for r in effective(saved['changes']):kind,multiplier=r['fee_type'],r['fee_multiplier']
        base=(kind,multiplier)
        for r in effective(saved['events']):
            if r.get('fee_type_override') is None and r.get('fee_multiplier_override') is None:kind,multiplier=base
            else:kind=r.get('fee_type_override') or base[0];multiplier=r.get('fee_multiplier_override') if r.get('fee_multiplier_override') is not None else base[1]
        charge('.5',1,kind,multiplier)
        times=[datetime.fromisoformat(r['scheduled_ts'].replace('Z','+00:00')).timestamp() for r in saved['changes']+saved['events']]
        saved['resolved']=(max((t for t in times if t<=at),default=float('-inf')),
                           min((t for t in times if t>at),default=float('inf')),kind,multiplier)
        return kind,multiplier

class PaperExchange:
    paper=True;ws_root=WS
    def __init__(self,store,signer,guard=lambda:None,client=None):
        self.store,self.signer,self.guard=store,signer,guard
        self.data=ProductionData(signer,client);self.ledger=Ledger(store,guard);self.fees=Fees(self.data)
        self.writes=0;self.active_tickers=set();self.books={};self.quotes={};self.markets={};self.before_read=None
    @property
    def reads(self):return self.data.reads
    def close(self):self.data.close()
    def call(self,method,path,*,params=None,body=None):
        params=params or {}
        if method!='GET':raise ExchangeFailure('paper_network_write_forbidden')
        if path.startswith(('/portfolio/','/historical/')):
            self.ledger.expire(time.time())
            if path=='/portfolio/balance':return self.ledger.balance(self.quotes)
            if path=='/portfolio/positions':return dict(market_positions=self.ledger.positions(),cursor='')
            if re.fullmatch(r'/portfolio/orders/paper-[A-Za-z0-9-]{1,128}',path):
                with self.store.pool.connection() as c:o=get(c,'order/'+path.split('/')[-1].removeprefix('paper-'))
                if not o:raise ExchangeFailure('paper_order_not_found',status=404)
                return dict(order=wire(o))
            if path.endswith('/orders'):
                found=[o for o in self.ledger.orders(params.get('status'),params.get('ticker'),params.get('min_ts',0)) if (not params.get('ticker') or o['ticker']==params['ticker']) and (not params.get('status') or o['status']==params['status']) and o['created_at']>=params.get('min_ts',0)]
                if params.get('status')=='resting':self.active_tickers={o['ticker'] for o in found}
                return dict(orders=[wire(o) for o in found],cursor='')
            if path.endswith('/fills'):
                with self.store.pool.connection() as c:found=rows(c,'fill',params.get('ticker'),params.get('min_ts',0))
                return dict(fills=[o for o in found if not params.get('ticker') or o['ticker']==params['ticker']],cursor='')
            raise ExchangeFailure('paper_virtual_route_unsupported')
        if self.before_read:self.before_read()
        page=self.data.call('GET',path,params)
        raw_markets=page.get('markets',[]) if path=='/markets' else [page['market']] if 'market' in page else []
        for raw in raw_markets:
            self.markets[raw['ticker']]=raw;self.ledger.settle(raw)
        return page
    def pages(self,path,key,**params):
        if path.startswith(('/portfolio/','/historical/')):
            yield from self.call('GET',path,params=params)[key];return
        cursor=None
        for _ in range(20):
            page=self.call('GET',path,params=dict(params,limit=200,**({'cursor':cursor} if cursor else {})))
            yield from page[key];following=page.get('cursor')
            if not following:return
            if following==cursor:break
            cursor=following
        raise ExchangeFailure('paper_page_capacity')
    def market_activity_call(self,method,path,*,params=None):return self.call(method,path,params=params)
    def observe_book(self,ticker,book,q,snapshot=False):
        if snapshot:q['paper_epoch_at']=time.time()
        self.books[ticker]=book;self.quotes[ticker]=q
        if snapshot:self.ledger.requeue(ticker,book)
    def invalidate(self):self.books.clear();self.quotes.clear();self.ledger.gap()
    def observe_trade(self,trade,now):
        ticker=trade.get('market_ticker')
        if ticker not in self.books or ticker not in self.active_tickers:return False
        # Refreshes occur outside the feed consumer; never block a price burst
        # on fee metadata. Unknown/stale schedules cannot create a paper fill.
        try:schedule=self.fees.schedule(ticker,now)
        except (ExchangeFailure,ValueError):return False
        return self.ledger.trade(trade,self.quotes.get(ticker),now,schedule)
    def submit(self,intent):
        self.guard();ticker=intent['ticker'];now=time.time();q=self.quotes.get(ticker);book=self.books.get(ticker)
        if not q or not book:raise ExchangeFailure('paper_stale_book')
        if ticker not in self.fees.cache or now-self.fees.cache[ticker]['at']>30:self.fees.load(ticker,self.markets[ticker],now)
        result=self.ledger.submit(intent,self.books.get(ticker,{}),self.quotes.get(ticker,{}),self.fees.schedule(ticker,now),time.time());self.active_tickers.add(ticker);self.writes+=1;return result
    def cancel(self,order_id,ticker):self.guard();self.writes+=1;return self.ledger.cancel(order_id,time.time())
