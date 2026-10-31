"""Bounded real-time books. No polling, conflation, or invented empty-side quotes."""
from decimal import Decimal, InvalidOperation
from .exchange import ExchangeFailure

class OrderBooks:
    def __init__(self):self.books={}
    def clear(self):self.books.clear()
    def apply(self,message,received_at):
        raw=message['msg'];ticker=raw['market_ticker'];kind=message['type']
        try:
            clock=int(raw['clock'])
            if kind=='orderbook_snapshot':
                book=dict(yes={},no={},clock=clock)
                for side in ('yes','no'):
                    levels=raw.get(side+'_dollars_fp') or []
                    if len(levels)>2000:raise ValueError()
                    for price,size in levels:
                        p=Decimal(price);n=Decimal(size)
                        if not p.is_finite() or not n.is_finite() or not 0<p<1 or n<0:raise ValueError()
                        if n:book[side][p]=n
                self.books[ticker]=book
            else:
                book=self.books.get(ticker)
                if book is None:raise ValueError()
                if clock<book['clock']:raise ValueError()
                side=raw['side'];p=Decimal(raw['price_dollars']);delta=Decimal(raw['delta_fp'])
                if side not in ('yes','no') or not p.is_finite() or not delta.is_finite() or not 0<p<1:raise ValueError()
                size=book[side].get(p,Decimal(0))+delta
                if size<0:raise ValueError()
                if size:book[side][p]=size
                else:book[side].pop(p,None)
                if len(book[side])>2000:raise ValueError()
                book['clock']=clock
            bid=max(book['yes'],default=None);opposite=max(book['no'],default=None)
            # Snapshot timestamps are connection receipt times; deltas use the
            # exchange event time, not the later network enqueue timestamp.
            event_at=Decimal(str(raw.get('ts_ms') or message.get('sending_ts_ms') or received_at*1000))/1000
            if not event_at.is_finite() or float(event_at)>received_at+5:raise ValueError()
            return ticker,dict(bid=float(bid*100) if bid is not None else 0,
                ask=float((1-opposite)*100) if opposite is not None else 100,
                at=min(received_at,float(event_at)),event_at=float(event_at),source='orderbook',clock=clock,seq=message['seq'],
                received_at=received_at,change=dict(kind=kind,side=raw.get('side'),price=raw.get('price_dollars'),delta=raw.get('delta_fp')),book_ready=bid is not None and opposite is not None,
                best_yes_size=str(book['yes'].get(bid,0)),best_no_size=str(book['no'].get(opposite,0)))
        except (KeyError,ValueError,TypeError,InvalidOperation,OverflowError):
            self.clear();raise ExchangeFailure('stream_book_invalid') from None
