"""Convexity cost recovery and explicit, bounded execution measurements."""
from decimal import Decimal as D, ROUND_FLOOR

ZERO=D(0)


def recovery_order(lot,book,fees,price):
    """Smallest whole-contract IOC that recovers cost at its limit after fees.

    Retain at least one contract. If the observed book cannot cover the whole
    recovery order, wait; arrival-time depth still controls actual execution.
    Partials retry only the unrecovered cash target on a later step.
    """
    if not ZERO<price<1 or lot.recovery_cost<=lot.recovery_proceeds:return ZERO
    maximum=int((lot.quantity-1).to_integral_value(rounding=ROUND_FLOOR))
    if maximum<1:return ZERO
    # Round a fee for each possible whole-contract layer, conservatively allowing
    # fragmented execution rather than understating fees using a single VWAP.
    net=price-fees.charge(D(1),price,False)
    if net<=0:return ZERO
    missing=lot.recovery_cost-lot.recovery_proceeds
    low,high=1,maximum
    if D(high)*net<missing:return ZERO
    while low<high:
        middle=(low+high)//2
        if D(middle)*net>=missing:high=middle
        else:low=middle+1
    quantity=D(low)
    depth=sum((q for p,q in book.depth(lot.side,'sell') if p>=price),ZERO)
    return quantity if depth>=quantity else ZERO


def execution_report(engine,ticker):
    s=engine.wallet.stat(ticker)
    return dict(model='public-L2 FIFO estimate; trade-volume bounded; arrival-book IOC',
        measured=s.execution_measured,scope='Orders submitted since execution measurement upgrade in this cycle',
        latency_ms=engine.latency*1000,orders=s.execution_orders,rejections=s.rejected_orders,
        maker_requested=str(s.maker_requested),maker_filled=str(s.maker_filled),
        maker_fill_rate=str(100*s.maker_filled/s.maker_requested) if s.maker_requested else None,
        taker_requested=str(s.taker_requested),ioc_attempts=s.ioc_attempts,
        partial_iocs=s.partial_iocs,ioc_unfilled=str(s.ioc_unfilled),
        profit_contracts=str(s.profit_contracts),profit_net_proceeds=str(s.profit_proceeds),
        cycle_fees=str(s.fees_paid),cycle_taker_slippage=str(s.taker_slippage),
        data_valid=s.valid,queue_position='estimated',
        partial_profit_price=engine.markets[ticker].get('partial_profit_price','.40'))
