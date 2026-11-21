"""Read-only, bounded paper Favorites position/settlement health summary.

This does not verify an exchange result, infer a payout or mutate a wallet.\nThe recorded marker may originate from a verified WS event or approved REST recovery.
"""
from decimal import Decimal


def position_settlement_health(engine, now):
    """Distinguish active inventory from expired lots pending payout evidence.

    All quantities are open contract quantities, not dollar amounts or
    recoverable cash. Unknown market metadata stays explicitly unknown.
    """
    groups = {
        "still_open": {"lots": 0, "contracts": Decimal(0), "markets": set()},
        "expired_settlement_recorded": {"lots": 0, "contracts": Decimal(0), "markets": set()},
        "expired_no_recorded_settlement": {"lots": 0, "contracts": Decimal(0), "markets": set()},
        "expired_already_paid": {"lots": 0, "contracts": Decimal(0), "markets": set()},
        "unknown_market": {"lots": 0, "contracts": Decimal(0), "markets": set()},
    }
    for lot in engine.wallet.lots:
        market = engine.markets.get(lot.ticker)
        if not market or market.get("close") is None:
            label = "unknown_market"
        elif market.get("paid"):
            label = "expired_already_paid" if market["close"] <= now else "still_open"
        elif market["close"] > now:
            label = "still_open"
        elif lot.ticker in engine.settled:
            label = "expired_settlement_recorded"
        else:
            label = "expired_no_recorded_settlement"
        group = groups[label]
        group["lots"] += 1
        group["contracts"] += lot.quantity
        group["markets"].add(lot.ticker)
    return {
        label: {
            "lots": group["lots"],
            "contracts": str(group["contracts"]),
            "markets": len(group["markets"]),
        }
        for label, group in groups.items()
    }
