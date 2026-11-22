"""Bounded, read-only post-admission finance-hourly diagnostics for regular Favorites.

Counts are point-in-time *market/book-stage* indicators, not unique exchange
events, missed fills, or evidence of profitability. No REST calls, order placement,
risk changes, persistence, or historical reconstruction.
"""
from decimal import Decimal as D
from math import isfinite

from .hourly import hourly_category
from .schedules import session_wake

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
    coverage = getattr(suite, 'hourly_coverage', {}) or {}
    metadata = getattr(suite, 'hourly_metadata', {}) or {}
    retries = getattr(suite, 'hourly_retry_at', {}) or {}
    discovery_wakes = getattr(suite, 'discovery_wakes', {}) or {}
    rows = {}
    for series, enabled in sorted(selected.items()):
        last = coverage.get(series, {})
        at = last.get('at')
        valid_at = (isinstance(at, (int, float)) and not isinstance(at, bool)
                    and isfinite(at) and 0 <= now - at)
        age = int(now - at) if valid_at else None
        recent = age is not None and age <= 120

        # A missing 120s scan record is not an absent venue listing. The two
        # cash indexes may be intentionally asleep outside their NYSE session.
        # These are local scheduling hints, never authority to trade or skip.
        calendar_wake = session_wake(series, now)
        future = (last.get('next_check_at'), retries.get(series),
                  discovery_wakes.get('hourly:' + series), calendar_wake)
        next_scan = [int(value - now) for value in future
                     if isinstance(value, (int, float)) and not isinstance(value, bool)
                     and now < value < now + 31_536_000]
        if recent:
            scan_state = 'recent'
        elif calendar_wake is not None:
            scan_state = 'scheduled_cash_index'
        elif next_scan:
            scan_state = 'scheduled_retry'
        elif age is None:
            scan_state = 'never_scanned'
        else:
            scan_state = 'stale'

        series_metadata = metadata.get(series, {})
        frequency = (series_metadata.get('frequency')
                     if isinstance(series_metadata, dict) else None)
        rows[series] = dict(enabled=enabled,
            scan_recent=recent,
            scan_reason=(str(last.get('reason', 'unknown'))[:110]
                         if recent else 'no_recent_scan'),
            scan_state=scan_state,
            scan_last_age_seconds=age,
            scan_last_reason=(str(last.get('reason', 'unknown'))[:110] if last else None),
            next_scan_hint_seconds=min(next_scan, default=None),
            verified_series_frequency=str(frequency)[:24] if frequency is not None else None,
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
