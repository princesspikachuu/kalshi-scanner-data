"""Fair, bounded REST confirmation for held paper positions after feed rollover."""
import asyncio
import json
import time
from .weather_window import observation_end


def due_for_confirmation(markets, checks, now, *, limit=4, cooldown=30):
    """Fair, bounded lookup selection; an unfinalized older result never starves others."""
    return sorted(
        (ticker for ticker in markets if now - checks.get(ticker, 0) >= cooldown),
        key=lambda ticker: (checks.get(ticker, 0), markets[ticker]['close'], ticker),
    )[:limit]


async def recover_once(host):
    now = time.time()
    checks = getattr(host, 'position_settlement_checks', None)
    if checks is None:
        checks = host.position_settlement_checks = {}
    held = {}
    for engine, _, _ in host.experiments.portfolios.values():
        for lot in engine.wallet.lots:
            market = engine.markets.get(lot.ticker)
            if lot.quantity > 0 and market and not market.get('paid') and observation_end(market) <= now:
                held[lot.ticker] = market
    # Bounded, in-process diagnostics only: no extra REST calls, database writes,
    # wallet mutations, or changes to the venue's settlement requirements.
    telemetry = getattr(host, 'position_settlement_poll_telemetry', None)
    if not isinstance(telemetry, dict):
        telemetry = host.position_settlement_poll_telemetry = dict(
            next_log_at=0, outcomes={}, per_ticker={})
    # Least-recently checked first: unresolved/failed markets cannot starve others.
    due = due_for_confirmation(held, checks, now)
    for ticker in due:
        checks[ticker] = now
        outcome = 'lookup_error'
        venue_status = 'unavailable'
        try:
            raw = (await asyncio.to_thread(host.verified_data.call, 'GET', '/markets/' + ticker))['market']
            status = raw.get('status')
            venue_status = status if status in ('active', 'open', 'closed', 'determined',
                                                'settled', 'finalized') else 'other'
            if raw.get('ticker') != ticker:
                outcome = 'ticker_mismatch'
            elif status not in ('settled', 'finalized'):
                outcome = 'venue_not_final'
            elif raw.get('result') not in ('yes', 'no'):
                outcome = 'finalized_missing_result'
            else:
                # Existing serialized consumer owns wallet settlement, audit and durability.
                await host.put('experiment_settlement', dict(ticker=ticker,
                    status=raw['status'], result=raw['result']))
                outcome = 'confirmed_queued'
                print(json.dumps(dict(event='paper_position_settlement_confirmed', ticker=ticker,
                    result=raw['result'], real_orders_enabled=False)), flush=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(json.dumps(dict(event='paper_position_settlement_retry', ticker=ticker,
                error=type(exc).__name__, real_orders_enabled=False)), flush=True)
        summary = telemetry['outcomes']
        summary[outcome] = summary.get(outcome, 0) + 1
        row = telemetry['per_ticker'].setdefault(ticker, dict(attempts=0))
        row.update(attempts=row['attempts'] + 1, last_poll_status=outcome,
                   last_venue_status=venue_status, last_polled_at=now)
    for ticker in list(checks):
        if ticker not in held:
            del checks[ticker]
    for ticker in list(telemetry['per_ticker']):
        if ticker not in held:
            del telemetry['per_ticker'][ticker]
    if now >= telemetry['next_log_at']:
        # A few oldest unconfirmed examples distinguish venue settlement delay
        # from missed requests without emitting an unbounded ticker inventory.
        oldest = sorted(held, key=lambda t: (observation_end(held[t]), t))[:3]
        ages = [max(0, now - observation_end(market)) for market in held.values()]
        groups = dict(under_5m=0, five_to_30m=0, thirty_to_120m=0, over_120m=0)
        for age in ages:
            label = ('under_5m' if age < 300 else 'five_to_30m' if age < 1800
                     else 'thirty_to_120m' if age < 7200 else 'over_120m')
            groups[label] += 1
        print(json.dumps(dict(event='paper_position_settlement_poll_health',
            held_markets=len(held), oldest_expired_seconds=int(max(ages, default=0)),
            age_groups=groups, rest_calls=sum(telemetry['outcomes'].values()),
            poll_outcomes=dict(telemetry['outcomes']),
            oldest_unresolved=[dict(ticker=t, expired_seconds=int(max(0, now-observation_end(held[t]))),
                attempts=telemetry['per_ticker'].get(t, {}).get('attempts', 0),
                last_poll_status=telemetry['per_ticker'].get(t, {}).get('last_poll_status', 'not_checked'),
                last_venue_status=telemetry['per_ticker'].get(t, {}).get('last_venue_status', 'not_checked'))
                for t in oldest],
            real_orders_enabled=False)), flush=True)
        telemetry['outcomes'] = {}
        telemetry['next_log_at'] = now + 60


async def recover_positions(host):
    while not host.done.is_set():
        await recover_once(host)
        await asyncio.sleep(5)
