#!/usr/bin/env python3
"""Execution-evidence model for ONE hypothetical resting maker contract.

Public trade history cannot prove our hypothetical order entered the queue or
filled. "trade_through" is a strong *counterfactual* signal, not a real fill.
The historical price ladder and quotes are minute snapshots, not a live book.
"""
from decimal import Decimal, InvalidOperation
from datetime import datetime

OFFSETS_CENTS = (-3, -2, -1, 0, 1, 2, 3)
ORDER_LIFETIME_SECONDS = 60
ORDER_LATENCY_SECONDS = 2
MAX_QUOTE_AGE_SECONDS = 60
FEE_STRESS_CENTS = 1.0  # one hypothetical contract, NOT actual market fees
ATTEMPT_COLUMNS = [
    "date", "asset", "series", "ticker", "event_ticker", "side",
    "minutes_before_close", "best_bid_cents", "best_ask_cents",
    "baseline_band", "bid_offset_cents", "proposed_bid_cents",
    "quote_age_seconds", "entry_ts", "expires_ts", "evidence",
    "opposite_taker_trades", "through_contracts", "at_price_contracts",
    "won", "net_cents_per_attempt_proxy",
]

def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None

def cents(value):
    """Only accept prices aligned with one-cent ticks."""
    try:
        number = Decimal(str(value)) * 100
        if not number.is_finite() or number != number.to_integral_value():
            return None
        return int(number)
    except (InvalidOperation, ValueError, TypeError):
        return None

def candle_price(candle, side, quote):
    entry = candle.get(side + "_" + quote) or {}
    return entry.get("close_dollars", entry.get("close"))

def best_quote(candle):
    """One deterministic side per market/entry time; post-only asks required."""
    yes_bid = cents(candle_price(candle, "yes", "bid"))
    yes_ask = cents(candle_price(candle, "yes", "ask"))
    no_bid = cents(candle_price(candle, "no", "bid"))
    no_ask = cents(candle_price(candle, "no", "ask"))
    if no_bid is None and yes_ask is not None:
        no_bid = 100 - yes_ask
    if no_ask is None and yes_bid is not None:
        no_ask = 100 - yes_bid
    candidates = []
    for side, bid, ask in (("yes", yes_bid, yes_ask),
                           ("no", no_bid, no_ask)):
        if bid is not None and ask is not None and 50 <= bid < 100 and bid < ask:
            candidates.append((bid, side, ask))
    if not candidates:
        return None
    # Higher priced side wins; YES breaks ties. No outcome-based selection.
    bid, side, ask = sorted(candidates, key=lambda v: (-v[0], v[1] != "yes"))[0]
    return side, bid, ask

def trade_evidence(trades, side, proposed_bid_cents, entry_ts, expires_ts):
    """Require opposite-side taker, non-block trade, and a subsequent trade.

    No book depth or queue replay available. We deliberately give at-price
    matches ZERO presumed fills; only strict trade-through receives P/L proxy.
    """
    strong = at_price = opposite_count = 0
    for trade in trades:
        if trade.get("is_block_trade") is True:
            continue
        taker = trade.get("taker_outcome_side")
        if taker not in ("yes", "no") or taker == side:
            continue
        ts = timestamp(trade.get("created_time"))
        if ts is None or not entry_ts + ORDER_LATENCY_SECONDS <= ts <= expires_ts:
            continue
        opposite_count += 1
        leg = "yes_price_dollars" if side == "yes" else "no_price_dollars"
        trade_price = cents(trade.get(leg))
        if trade_price is None:
            continue
        try:
            count = Decimal(str(trade.get("count_fp") or "0"))
        except InvalidOperation:
            continue
        if not count.is_finite() or count <= 0:
            continue
        if trade_price < proposed_bid_cents:
            strong += count
        elif trade_price == proposed_bid_cents:
            at_price += count
    evidence = "trade_through" if strong >= 1 else (
        "at_price_only" if at_price > 0 else "no_trade_evidence")
    return evidence, opposite_count, float(strong), float(at_price)

def simulate(market, asset, date, minute, candle, trades, target_ts, close_ts):
    end_period = candle.get("end_period_ts")
    if end_period is None:
        return []
    age = target_ts - int(end_period)
    if not 0 <= age <= MAX_QUOTE_AGE_SECONDS:
        return []
    quote = best_quote(candle)
    if quote is None:
        return []
    side, best_bid, best_ask = quote
    expires = min(target_ts + ORDER_LIFETIME_SECONDS, close_ts - 1)
    if expires <= target_ts + ORDER_LATENCY_SECONDS:
        return []
    result = int(market.get("result") == side)
    band = f"{(best_bid // 10) * 10:02d}-{(best_bid // 10 + 1) * 10:02d}"
    output = []
    for offset in OFFSETS_CENTS:
        bid = best_bid + offset
        if bid < 50 or bid >= 100 or bid >= best_ask:
            continue
        evidence, number, through, at = trade_evidence(
            trades, side, bid, target_ts, expires)
        # One candidate contract per attempt. Conservative stress fee of 1c
        # charged only when "through" supports the counterfactual fill proxy.
        net = round((100 * result - bid - FEE_STRESS_CENTS), 4) if evidence == "trade_through" else 0.0
        output.append([
            date, asset, market["series_ticker"], market["ticker"],
            market.get("event_ticker") or market["ticker"], side, minute,
            best_bid, best_ask, band, offset, bid, age, target_ts, expires,
            evidence, number, round(through, 3), round(at, 3), result, net,
        ])
    return output
