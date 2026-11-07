"""One consistent virtual-wallet snapshot, independent of strategy evidence quality."""
from decimal import Decimal as D

ZERO=D(0)
FIELDS=('unfilled_bids','unfilled_principal','reserved_fees','unfilled_contracts',
        'active_cost','active_value','active_contracts','pending_cost','pending_value',
        'pending_contracts','pending_max_payout','position_cost')

def empty():
    return dict({k:ZERO for k in FIELDS},active_value_known=True,pending_value_known=True,
                pending_all_confirmed=True)

def finish(row):
    row=dict(row)
    if not row['active_value_known']:row['active_value']=None
    if not row['pending_value_known']:row['pending_value']=None
    known=row['active_value_known'] and row['pending_value_known']
    row['position_value']=row['active_value']+row['pending_value'] if known else None
    row['unrealized_pnl']=row['position_value']-row['position_cost'] if known else None
    row['pending_payout_state']=('none' if not row['pending_contracts'] else
        'confirmed' if row['pending_all_confirmed'] else 'estimated' if row['pending_value_known'] else 'unknown')
    return row

def strings(value):
    if isinstance(value,D):return str(value)
    if isinstance(value,dict):return {k:strings(v) for k,v in value.items()}
    if isinstance(value,list):return [strings(v) for v in value]
    return value

def snapshot(engine,profiles,now):
    by_series={p['series']:p['id'] for p in profiles}
    groups={p['id']:empty() for p in profiles};total=empty();positions=[];orders=[]
    def owner(ticker):return engine.markets.get(ticker,{}).get('bot_id') or by_series.get(ticker.split('-')[0],'unassigned')
    def buckets(ticker):return (total,groups.setdefault(owner(ticker),empty()))
    for order in engine.orders.values():
        if order.status not in ('pending','resting'):continue
        principal=order.remaining*order.price if order.action=='buy' else ZERO
        if order.action=='buy':
            for row in buckets(order.ticker):
                row['unfilled_bids']+=order.reserved;row['unfilled_principal']+=principal
                row['reserved_fees']+=order.reserved-principal;row['unfilled_contracts']+=order.remaining
        orders.append(dict(id=order.id,bot_id=owner(order.ticker),ticker=order.ticker,side=order.side,action=order.action,
            quantity=order.remaining,price=order.price,status=order.status,maker=order.maker,
            reserved=order.reserved,principal=principal))
    for lot in engine.wallet.lots:
        market=engine.markets[lot.ticker];pending=now>=market['close']
        cost=lot.quantity*lot.price+lot.entry_fee;book=engine.books.get(lot.ticker)
        confirmed=market.get('yes_payout_confirmed')
        mark=None;source='unavailable'
        if pending and confirmed in ('0','1'):
            mark=D(confirmed) if lot.side=='yes' else 1-D(confirmed);source='confirmed_outcome'
        elif book and book.valid and (pending or
                now-max(book.at,engine.book_feed_at.get(book.sid,0))<=engine.stale_seconds):
            mark=book.bid(lot.side)
            if mark is not None:source='last_bid' if pending else 'current_bid'
        value=lot.quantity*mark if mark is not None else None
        kind='pending' if pending else 'active'
        for row in buckets(lot.ticker):
            row[kind+'_cost']+=cost;row['position_cost']+=cost
            row[kind+'_contracts']+=lot.quantity
            if value is None:row[kind+'_value_known']=False
            else:row[kind+'_value']+=value
            if pending:
                row['pending_max_payout']+=lot.quantity
                row['pending_all_confirmed'] &= source=='confirmed_outcome'
        positions.append(dict(ticker=lot.ticker,bot_id=owner(lot.ticker),side=lot.side,
            quantity=lot.quantity,price=lot.price,entry_fee=lot.entry_fee,cost=cost,
            value=value,mark_price=mark,valuation_source=source,quote_at=book.at if book else None,
            state=kind,is_armed=lot.is_armed,phase_origin=lot.phase_origin,
            bot_revision=market.get('bot_revision',1)))
    total=finish(total);groups={k:finish(v) for k,v in groups.items()}
    # Open cost includes the remaining entry fees. This identity includes ALL
    # realized money movements, even when a cycle is excluded from research.
    total.update(cash=engine.wallet.cash,deposits=engine.wallet.deposits,
        available_cash=engine.wallet.cash-total['unfilled_bids'],
        realized_pnl=engine.wallet.cash+total['position_cost']-engine.wallet.deposits)
    total['equity']=engine.wallet.cash+total['position_value'] if total['position_value'] is not None else None
    total['total_pnl']=total['equity']-engine.wallet.deposits if total['equity'] is not None else None
    cycles={}
    for ticker,stat in engine.wallet.stats.items():
        market=engine.markets.get(ticker)
        if not market:continue
        cycles[ticker]=dict(ticker=ticker,bot_id=owner(ticker),bot_revision=market.get('bot_revision',1),
            at=now if market.get('paid') else min(now,market['close']),data_valid=stat.valid,
            gross_profit=stat.gross,total_fees_paid=stat.fees_paid,
            net_realized_pnl=stat.gross-stat.realized_fees,
            closed_contracts=stat.closed,winning_contracts=stat.won)
    return strings(dict(schema=1,at=now,portfolio=total,bots=groups,
                        positions=positions,orders=orders,current_cycles=cycles))
