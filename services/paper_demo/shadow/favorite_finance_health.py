"""Bounded, read-only post-admission finance-hourly diagnostics for regular Favorites.

Counts are point-in-time *market/book-stage* indicators, not unique exchange
events, missed fills, or evidence of profitability. No REST calls, order placement,
risk changes, persistence, or historical reconstruction.
"""
from decimal import Decimal as D

from .hourly import hourly_category

TICK = D('.01')
FLOOR = D('.70')
CEILING = D('.95')


def finance_hourly_funnel_snapshot(suite, now):
    """Explain zero weekday finance bids after discovery without touching execution.

    This ONLY inspects the regular Favorites portfolio. Missing or stale scan
    coverage remains explicitly different from a known lack of eligible listings.
    """
    portfolio = getattr(suite, 'portfolios', {}).get('favorites')
    if not portfolio:
        return dict(configured_series=0, enabled_series=0, paper_cash_available=None,
                    by_series={})

    engine, fleet, profiles = portfolio
    selected = {}
    for p in profiles:
        series = p.get('series')
        if (p.get('strategy') != 'favorites' or p.get('asset') != 'hourly' or
                not isinstance(series, str) or hourly_category(series) != 'finance'):
            continue
        bot = fleet.bots.get(series)
        selected[series] = bool(bot and bot.enabled)

    counts = ('admitted_active_markets', 'parked_active_markets', 'fresh_books',
              'fee_verified_admitted_markets', 'two_sided_books',
              'price_candidate_books', 'fee_verified_price_books',
              'fundable_price_books', 'resting_or_pending_buy_orders')
    coverage = getattr(suite, 'hourly_coverage', {})
    rows = {}
    for series, enabled in sorted(selected.items()):
        last = coverage.get(series, {})
        at = last.get('at')
        recent = isinstance(at, (int, float)) and 0 <= now - at <= 120
        rows[series] = dict(enabled=enabled,
            scan_recent=recent,
            scan_reason=(str(last.get('reason', 'unknown'))[:110]
                         if recent else 'no_recent_scan'),
            scan_listed_last=(int(last.get('active_markets', 0)) if recent else None),
            scan_eligible_last=(int(last.get('eligible_markets', 0)) if recent else None),
            **{field: 0 for field in counts})

    cash = engine.available()
    for ticker, market in engine.markets.items():
        series = ticker.split('-', 1)[0]
        row = rows.get(series)
        if row is None or not row['enabled'] or not market.get('hourly_price'):
            continue
        if market.get('paid') or market.get('close', 0) <= now:
            continue
        if market.get('entry_parked'):
            row['parked_active_markets'] += 1
            continue
        row['admitted_active_markets'] += 1
        fee_verified = engine.zero_maker_entry_allowed(ticker)
        if fee_verified:
            row['fee_verified_admitted_markets'] += 1
        book = engine.books.get(ticker)
        if book is None or not engine.book_fresh(ticker):
            continue
        row['fresh_books'] += 1
        yes, no = book.bid('yes'), book.bid('no')
        if yes is None or no is None or yes + no >= 1:
            continue
        row['two_sided_books'] += 1

        # Indicative regular-Favorites preferred side and 1-cent maker price.
        # Existing attempt-side locks are respected. This is NOT an order decision:
        # time window, previously filled buckets and risk still apply.
        bot = fleet.bots[series]
        attempt = bot.attempts.get(ticker, {})
        side = attempt.get('side') if attempt.get('side') in ('yes', 'no') else (
            'yes' if yes >= no else 'no')
        bid = yes if side == 'yes' else no
        opposite = no if side == 'yes' else yes
        candidate = min(bid + TICK, D(1) - opposite - TICK, CEILING)
        if not FLOOR <= candidate <= CEILING:
            continue
        row['price_candidate_books'] += 1
        if not fee_verified:
            continue
        row['fee_verified_price_books'] += 1
        # Certified zero-maker-fee portfolios require at least one contract.
        # This is a snapshot of *shared* available cash, not N simultaneous bids.
        if cash >= candidate:
            row['fundable_price_books'] += 1

    for order in engine.orders.values():
        if order.action != 'buy' or order.status not in ('pending', 'resting'):
            continue
        series = order.ticker.split('-', 1)[0]
        row = rows.get(series)
        if row is not None and row['enabled']:
            row['resting_or_pending_buy_orders'] += 1

    return dict(configured_series=len(rows),
                enabled_series=sum(row['enabled'] for row in rows.values()),
                paper_cash_available=str(cash),
                denominator='point_in_time_market_snapshots_not_independent_events',
                by_series=rows)
