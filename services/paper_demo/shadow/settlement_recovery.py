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
    # Least-recently checked first: unresolved/failed markets cannot starve others.
    due = due_for_confirmation(held, checks, now)
    for ticker in due:
        checks[ticker] = now
        try:
            raw = (await asyncio.to_thread(host.verified_data.call, 'GET', '/markets/' + ticker))['market']
            if (raw.get('ticker') == ticker and raw.get('status') in ('settled', 'finalized')
                    and raw.get('result') in ('yes', 'no')):
                # Existing serialized consumer owns wallet settlement, audit and durability.
                await host.put('experiment_settlement', dict(ticker=ticker,
                    status=raw['status'], result=raw['result']))
                print(json.dumps(dict(event='paper_position_settlement_confirmed', ticker=ticker,
                    result=raw['result'], real_orders_enabled=False)), flush=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(json.dumps(dict(event='paper_position_settlement_retry', ticker=ticker,
                error=type(exc).__name__, real_orders_enabled=False)), flush=True)
    for ticker in list(checks):
        if ticker not in held:
            del checks[ticker]


async def recover_positions(host):
    while not host.done.is_set():
        await recover_once(host)
        await asyncio.sleep(5)
