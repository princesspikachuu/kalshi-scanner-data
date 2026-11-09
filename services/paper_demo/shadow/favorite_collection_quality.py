"""Bounded reporting of Favorites collection quality; never used for trading decisions.

A fill cohort is not an independent settlement. Outcome identities are deduplicated
per market type across series, side, price and time cells. Rolling rates contain
only outcomes timestamped when the new observation was actually confirmed.
"""
from collections import defaultdict
from decimal import Decimal as D
from .favorite_timing import METRICS
from .favorite_statistics import price_bucket


def collection_quality(bots, now):
    totals=dict(cohort_contracts=D(0), unverified_entry_contracts=D(0),
                settled_cohort_contracts=D(0), outcome_cells=0)
    events_by_type=defaultdict(set)
    rolling_1h=defaultdict(set)
    rolling_24h=defaultdict(set)
    timestamped=defaultdict(set)
    cell_events=defaultdict(set)
    for bot in bots:
        cells=bot.exit_evidence.cells
        for row_key, row in cells.items():
            if not row_key.startswith(METRICS) or not row.get('key'):
                continue
            mt=row.get('market_type') or 'unknown'
            totals['cohort_contracts']+=D(row.get('contracts','0'))
            totals['unverified_entry_contracts']+=D(row.get('unverified','0'))
            totals['settled_cohort_contracts']+=D(row.get('resolved','0'))
            outcome_cell=cells.get(row['key'],{})
            observed=outcome_cell.get('events',{})
            timestamps=outcome_cell.get('event_times',{})
            if observed:totals['outcome_cells']+=1
            group=(mt,price_bucket(row.get('price','0')),row.get('horizon') or 'unknown')
            for event in observed:
                identity=(mt,str(event))
                events_by_type[mt].add(identity)
                cell_events[group].add(identity)
                at=timestamps.get(event)
                if at is None:
                    continue
                try:at=float(at)
                except (TypeError,ValueError):continue
                # No fabricated history, no future timestamps.
                if not 0<=at<=now:continue
                timestamped[mt].add(identity)
                if now-at<=86400:rolling_24h[mt].add(identity)
                if now-at<=3600:rolling_1h[mt].add(identity)
    categories={}
    for mt in sorted(events_by_type):
        all_events=events_by_type[mt]
        categories[mt]=dict(unique_verified_outcomes=len(all_events),
            timestamped_outcomes=len(timestamped[mt]),
            unknown_time_outcomes=len(all_events-timestamped[mt]),
            unique_verified_1h=len(rolling_1h[mt]),
            unique_verified_24h=len(rolling_24h[mt]),
            rolling_window_complete=len(all_events-timestamped[mt])==0)
    return dict(cohort_contracts=str(totals['cohort_contracts']),
        unverified_entry_contracts=str(totals['unverified_entry_contracts']),
        settled_cohort_contracts=str(totals['settled_cohort_contracts']),
        outcome_cells=totals['outcome_cells'],
        unique_verified_outcomes=sum(v['unique_verified_outcomes'] for v in categories.values()),
        unique_verified_1h=sum(v['unique_verified_1h'] for v in categories.values()),
        unique_verified_24h=sum(v['unique_verified_24h'] for v in categories.values()),
        # Legacy outcomes were retained without timestamps; these windows are
        # lower bounds until a full window of timestamped operation is observed.
        rolling_counts_are_lower_bounds=True,
        by_market_type=categories,
        price_time_cells=[dict(market_type=mt,price_bucket=price,horizon=h,unique_verified_outcomes=len(events))
            for (mt,price,h),events in sorted(cell_events.items()) if events])
