"""Reconcile fixed-minute research bid cohorts with actual paper entry orders.

This is intentionally independent from the execution engine's qualified P/L
calculation: the exact-order ledger is independently settled, and the research
reference uses the latest candle *at or before* each fixed checkpoint (<=120s).
The fixed-time baseline is NOT an executable portfolio or the same population.
"""
import json
from .rules import entry_rules
from decimal import Decimal, InvalidOperation


def _cents(raw):
    try:
        value=Decimal(str(raw))*100
        return int(value) if value.is_finite() and value==value.to_integral_value() else None
    except (ValueError, TypeError, InvalidOperation):
        return None


def _bid(bar,side):
    quoted=bar.get(side+'_bid') or {}
    value=_cents(quoted.get('close_dollars',quoted.get('close')))
    if value is None and side=='no':
        yes=bar.get('yes_ask') or {}
        yes_ask=_cents(yes.get('close_dollars',yes.get('close')))
        if yes_ask is not None:value=100-yes_ask
    return value


def _research_side(bar):
    picks=[(price,side) for side in ('yes','no')
        if (price:=_bid(bar,side)) is not None and 50<=price<100]
    return max(picks,key=lambda x:(x[0],x[1]=='yes')) if picks else None


def _compatible(s,m):
    asset=s.get('asset')
    series=m['candidate'].get('series')
    return (asset==m['asset'] or
        (asset=='btc' and series=='KXBTC15M') or
        (asset=='eth' and series=='KXETH15M') or
        (asset=='crypto' and series in {
            'KXBTC15M','KXETH15M','KXSOL15M','KXXRP15M',
            'KXDOGE15M','KXBNB15M','KXHYPE15M','KXZEC15M','KXNEAR15M'}))


def _roi(pnl,stake):
    return round(pnl*100/stake,4) if stake else None


def compare_cohorts(db,markets,strategies,orders,ledger_hold_pnl):
    # The spool is on disk. Index queries for a market at its precise research
    # checkpoint rather than materializing a second in-memory candle timeline.
    db.execute('CREATE INDEX IF NOT EXISTS cohort_quote_lookup ON events(ticker,kind,ts,serial)')
    by_order={(o['ticker'],o['strategy']):o for o in orders}
    sections=[]
    for idx,strategy in enumerate(strategies):
        if len(entry_rules(strategy))>1:
            sections.append(dict(strategy=strategy.get('name','Multi-square strategy'),checkpoint_minutes=None,fixed_bid_band_cents=None,markets_checked=0,fixed_quotes_available=0,reference_band_markets=0,reference_band_wins=0,reference_bid_stake_cents=0,reference_bid_pnl_cents=0,reference_events=0,reference_markets_without_order=0,paired_markets=0,paired_contracts=0,paired_winners=0,paired_fixed_bid_stake_cents=0,paired_fixed_bid_pnl_cents=0,paired_replay_bid_stake_cents=0,paired_replay_bid_pnl_cents=0,different_side=0,missing_or_stale_fixed_quote=0,fixed_band_mismatch=0,unmatched_replay_orders=sum(o['strategy']==idx for o in orders),reference_distinct_events=0,fixed_reference_roi_percent=None,paired_reference_roi_percent=None,paired_replay_roi_percent=None,paired_price_difference_cents=0))
            continue
        summary=dict(strategy=strategy.get('name') or f'Strategy {idx+1}',
            checkpoint_minutes=strategy.get('entry_minute_max'),
            fixed_bid_band_cents=[strategy.get('min_price'),strategy.get('max_price')],
            markets_checked=0,fixed_quotes_available=0,
            reference_band_markets=0,reference_band_wins=0,
            reference_bid_stake_cents=0,reference_bid_pnl_cents=0,
            reference_events=set(),reference_markets_without_order=0,
            paired_markets=0,paired_contracts=0,paired_winners=0,
            paired_fixed_bid_stake_cents=0,paired_fixed_bid_pnl_cents=0,
            paired_replay_bid_stake_cents=0,paired_replay_bid_pnl_cents=0,
            different_side=0,missing_or_stale_fixed_quote=0,
            fixed_band_mismatch=0,unmatched_replay_orders=0)
        for ticker,m in markets.items():
            if not _compatible(strategy,m) or m['close'] is None:continue
            summary['markets_checked']+=1
            target=m['close']-60*strategy['entry_minute_max']
            row=db.execute("""SELECT data FROM events
                WHERE ticker=? AND kind='quote' AND ts<=? AND ts>=?
                ORDER BY ts DESC,serial DESC LIMIT 1""",
                (ticker,target,target-120)).fetchone()
            order=by_order.get((ticker,idx))
            if not row:
                if order:summary['missing_or_stale_fixed_quote']+=1
                continue
            choice=_research_side(json.loads(row[0]))
            if choice is None:
                if order:summary['missing_or_stale_fixed_quote']+=1
                continue
            summary['fixed_quotes_available']+=1
            fixed_bid,reference_side=choice
            if not strategy['min_price']<=fixed_bid<=strategy['max_price']:
                if order:summary['fixed_band_mismatch']+=1
                continue
            won=int(m['candidate']['result']==reference_side)
            summary['reference_band_markets']+=1
            summary['reference_band_wins']+=won
            summary['reference_bid_stake_cents']+=fixed_bid
            summary['reference_bid_pnl_cents']+=100*won-fixed_bid
            summary['reference_events'].add(m['event'])
            if order is None:
                summary['reference_markets_without_order']+=1
                continue
            if order['side']!=reference_side:
                summary['different_side']+=1
                continue
            quantity=order['quantity']
            summary['paired_markets']+=1
            summary['paired_contracts']+=quantity
            summary['paired_winners']+=won*quantity
            summary['paired_fixed_bid_stake_cents']+=fixed_bid*quantity
            summary['paired_fixed_bid_pnl_cents']+=(100*won-fixed_bid)*quantity
            summary['paired_replay_bid_stake_cents']+=order['bid']*quantity
            summary['paired_replay_bid_pnl_cents']+=(100*won-order['bid'])*quantity
        # Replays can place orders that don't appear in the research bid-band
        # cohort. Those are NOT counted as paired comparisons.
        summary['unmatched_replay_orders']=sum(
            o['strategy']==idx for o in orders)-summary['paired_markets']
        summary['reference_distinct_events']=len(summary.pop('reference_events'))
        summary['fixed_reference_roi_percent']=_roi(
            summary['reference_bid_pnl_cents'],summary['reference_bid_stake_cents'])
        summary['paired_reference_roi_percent']=_roi(
            summary['paired_fixed_bid_pnl_cents'],summary['paired_fixed_bid_stake_cents'])
        summary['paired_replay_roi_percent']=_roi(
            summary['paired_replay_bid_pnl_cents'],summary['paired_replay_bid_stake_cents'])
        summary['paired_price_difference_cents']=(
            summary['paired_fixed_bid_pnl_cents']-summary['paired_replay_bid_pnl_cents'])
        if summary['paired_price_difference_cents']!=(
            summary['paired_replay_bid_stake_cents']-summary['paired_fixed_bid_stake_cents']):
            raise ValueError('Paired cohort entry-price reconciliation failed')
        sections.append(summary)
    return dict(
        methodology='Research reference: one contract per eligible market at the latest quote <= fixed checkpoint, max 120s old, selected by higher YES/NO bid, grouped by research BID band. Paired subset: the same ticker and side among actual replay orders. Price differences reflect both timing and posted-bid pricing. No inferred fills.',
        parity_basis='Same actual replay orders, sides, prices, quantities and settlements, independently recomputed from the order ledger.',
        same_orders_ledger_hold_pnl_cents=ledger_hold_pnl,
        strategies=sections)
