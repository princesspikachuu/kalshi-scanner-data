"""Maker-only conditional exits, using outcome-side bids and durable ceilings."""
from uuid import uuid5,NAMESPACE_URL
from .engine import side_quote,profit_maker_price
from .cycles import retry_ready

def enabled(value):return value.get('cycle_exit_mode')=='late_threshold'

def fresh(quote,now):
    if not quote or quote.get('source')!='orderbook' or not quote.get('book_verified') or quote.get('price_grid_refresh'):return False
    return quote.get('status')=='active' and 0<=now-quote.get('at',0)<=5 and now<quote['close']

def due(order,quote,now):
    if not enabled(order) or not fresh(quote,now):return False
    end=order.get('market_close_at',quote.get('entry_close',quote['close']))
    bid,ask=side_quote(quote,order['side'])
    return (0<end-now<=order.get('late_exit_minutes',5)*60
        and 0<=bid<ask<=100 and bid<order.get('late_exit_threshold_cents',40))

def maker_price(order,quote):
    bid,_=side_quote(quote,order['side'])
    # A full cent above the bid, rounded UP to this market's actual tick grid.
    price=profit_maker_price(quote,order['side'],bid+1)
    ceiling=order.get('late_exit_ceiling_cents')
    return price if price is not None and (ceiling is None or price<=ceiling) else None

def needs_action(order,quote,orders,now):
    if not fresh(quote,now) or order.get('filled',0)-order.get('sold',0)<=.001:return False
    if not order.get('late_exit_triggered') and not due(order,quote,now):return False
    children=[o for o in orders if o.get('parent')==order['client_id'] and o.get('status') not in ('closed','rejected')]
    if any(o.get('status') in ('intent','uncertain','cancel_pending') for o in children):return False
    price=maker_price(order,quote)
    if price is None:return False
    if any(o.get('exit_role')!='late' for o in children):return True
    if any(o.get('remaining',0)>0 and o['price']-price>order.get('late_exit_reprice_cents',5)+1e-8 for o in children):return True
    return order['filled']-order.get('sold',0)-sum(o.get('remaining',0) for o in children)>.001

class LateExitMixin:
    def latch_late_exit(self,order,quote,now):
        if order.get('late_exit_triggered') or not due(order,quote,now):return False
        price=maker_price(order,quote)
        if price is None:return False
        order.update(late_exit_triggered=True,late_exit_triggered_at=now,late_exit_ceiling_cents=price)
        self.save_order(order)
        self.record('late_exit_trigger',order,'Final-window bid below hold threshold; maker exit triggered',
            reference='bid',threshold_cents=order.get('late_exit_threshold_cents',40),bid_cents=side_quote(quote,order['side'])[0])
        return True

    def late_sell(self,order,quote,now):
        if not enabled(order) or not self.recovered or not fresh(quote,now):return False
        if order['ticker'] in self.blocked or order['ticker'] in self.netting_pending:return False
        if order.get('filled',0)-order.get('sold',0)<=.001:return False
        self.latch_late_exit(order,quote,now)
        if not order.get('late_exit_triggered'):return False
        retry=order.get('late_price_retry')
        refreshed=retry and retry.get('reason')=='price_tick' and quote.get('metadata_at',0)>retry.get('rejected_at',now) and now>=retry['after']
        if not refreshed and not retry_ready(retry,quote,now):return False
        # Release all remaining buys before selling, including opposite bids.
        for other in self.orders:
            if other['ticker']==order['ticker'] and other['kind']=='entry' and other.get('remaining',0)>0:
                if other.get('status') not in ('intent','uncertain','cancel_pending'):
                    self.park_cycle_entry(other,'Conditional late exit: cancel waiting buys before selling');return True
                return False
        children=[o for o in self.orders if o.get('parent')==order['client_id'] and o.get('status') not in ('closed','rejected')]
        if any(o.get('status') in ('intent','uncertain','cancel_pending') for o in children):return False
        price=maker_price(order,quote)
        if price is None:return False # A rising bid never raises a saved limit.
        for child in children:
            if child.get('exit_role')!='late' or (child.get('remaining',0)>0 and child['price']-price>order.get('late_exit_reprice_cents',5)+1e-8):
                order['late_exit_ceiling_cents']=min(order['late_exit_ceiling_cents'],price);self.save_order(order)
                self.cancel(child,'Lowering conditional maker sell after price moved more than the reprice gap')
                return True
        amount=round(order['filled']-order.get('sold',0)-sum(o.get('remaining',0) for o in children),2)
        if amount<=.001:return False
        attempt=order.get('late_exit_attempt',0)+1
        order.update(late_exit_attempt=attempt,late_exit_ceiling_cents=min(order['late_exit_ceiling_cents'],price));self.save_order(order)
        self.submit(dict(client_id=str(uuid5(NAMESPACE_URL,f"demo-late/{order['client_id']}/{attempt}")),
            kind='exit',exit_role='late',parent=order['client_id'],bot=order['bot'],revision=order['revision'],
            ticker=order['ticker'],side=order['side'],price=price,quantity=amount,close=quote['close'],
            exchange_index=order.get('exchange_index',-1),exit_reference='bid',pricing_bid_cents=side_quote(quote,order['side'])[0],
            late_triggered_at=order.get('late_exit_triggered_at'),created_at=now,status='intent',remaining=0,filled=0))
        return True
