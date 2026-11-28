"""Read-only held-to-settlement evidence for *regular* Favorites research.

Older Favorites observations can have real early exits. When an authoritative
binary outcome was subsequently recorded, the research counterfactual uses
original entry costs/fees and the settlement payout, never the exit proceeds
or exit fee. It does not rewrite durable records, wallet cash or trading state.
"""
from decimal import Decimal as D, InvalidOperation


def _number(value):
    try:
        n = D(str(value))
        return n if n.is_finite() else None
    except (ValueError, TypeError, ArithmeticError, InvalidOperation):
        return None


def _outcomes(row):
    observed = row.get('outcome_events')
    if not isinstance(observed, dict):
        return {}
    result = {}
    for event, payout in observed.items():
        if type(payout) not in (int, str) or payout not in (0, 1, '0', '1'):
            continue
        identity = str(event)
        if not identity:
            continue
        result[identity] = min(result.get(identity, 1), int(payout))
    return result


def _entry_amounts(row, outcomes):
    """Derive event-specific entry size/cost, preferring exact fill evidence.

    Historic aggregate rows may not retain per-event quantity. Their derived
    return remains useful but is explicitly marked *estimated*. We do not
    assign another event's full aggregate cost to each event.
    """
    total_cost = _number(row.get('cost'))
    total_qty = _number(row.get('contracts'))
    resolved = _number(row.get('resolved'))
    unverified = _number(row.get('unverified'))
    mean_unit = total_cost / total_qty if (
        total_cost is not None and total_cost > 0
        and total_qty is not None and total_qty > 0) else None
    entry_price = _number(row.get('price'))
    original_returns = row.get('return_events')
    original_returns = original_returns if isinstance(original_returns, dict) else {}
    matching = {str(k): v for k, v in original_returns.items() if isinstance(v, dict)}
    wide = row.get('wide_events')
    wide = wide if isinstance(wide, dict) else {}
    wide = {str(k): v for k, v in wide.items() if isinstance(v, list)}
    for event in outcomes:
        source = matching.get(event, {})
        exact_records = wide.get(event, [])
        if exact_records:
            qty = D(0)
            cost = D(0)
            valid = True
            for record in exact_records:
                if not isinstance(record, (list, tuple)) or len(record) < 3:
                    valid = False
                    break
                q, c = _number(record[1]), _number(record[2])
                if q is None or c is None or q <= 0 or c <= 0:
                    valid = False
                    break
                qty += q
                cost += c
            if valid and qty > 0 and cost > 0:
                yield event, qty, cost, False
                continue

        event_cost = _number(source.get('cost'))
        # A present but invalid historical cost is not permission to invent
        # a different entry basis from cohort averages. A genuinely absent
        # attribution may be conservatively reconstructed below.
        if source and (event_cost is None or event_cost <= 0):
            continue
        # A single fully settled event accounts for all recorded purchases
        # only when no unrelated/unverified quantity can be hiding in the row.
        complete = (len(outcomes) == 1 and mean_unit is not None
                    and unverified in (None, 0)
                    and (resolved == total_qty or (resolved is None
                         and (total_qty == 1 or event_cost == total_cost))))
        if complete:
            yield event, total_qty, total_cost, False
            continue

        # Previous exit records still contain the entry *cost* for this event.
        # Infer quantity from the cohort's mean entry cost per contract, which
        # accounts for the original entry fees. The estimate is never exact.
        if event_cost is not None and mean_unit is not None and event_cost <= total_cost:
            yield event, event_cost / mean_unit, event_cost, True
            continue
        if event_cost is not None and (mean_unit is None and entry_price is not None and entry_price > 0):
            yield event, event_cost / entry_price, event_cost, True
            continue

        # Legacy evidence has a confirmed outcome but no exact event sizing:
        # use the original per-contract entry basis, not the exit P/L. Never
        # extrapolate if more known events than purchased contracts or some
        # purchases were unverified.
        if (mean_unit is not None and unverified in (None, 0)
                and total_qty >= D(len(outcomes))):
            yield event, D(1), mean_unit, True


def _settlement_payout(row, outcomes, event):
    """Use authoritative paid-contract totals for a fully resolved one-event row.

    An event identity can combine correlated threshold contracts. The event's
    conservative binary label may be adverse even when this *particular*
    entry side actually paid. Keep the conservative label for win statistics,
    but never substitute it for a known cash payout.
    """
    if len(outcomes) == 1:
        qty = _number(row.get('contracts'))
        resolved = _number(row.get('resolved'))
        winners = _number(row.get('winners'))
        if (qty is not None and qty > 0 and resolved == qty
                and winners in (D(0), resolved)):
            return winners / resolved
    return D(outcomes[event])


def regular_favorites_held_row(row):
    """Return a new research row, with known exits treated as held trades.

    Unconfirmed outcomes never contribute an ROI sample. Exact previously
    computed hold-only returns are preserved, including cases where adverse
    correlated threshold labels differ from the actual cash settlement payout.
    """
    if not isinstance(row, dict):
        return row
    outcomes = _outcomes(row)
    old_returns = row.get('return_events')
    old_returns = old_returns if isinstance(old_returns, dict) else {}
    old_returns = {str(k): v for k, v in old_returns.items() if isinstance(v, dict)}
    policy = row.get('return_policy')
    returns = {}
    for event, quantity, cost, estimated in _entry_amounts(row, outcomes):
        existing = old_returns.get(event)
        if policy != 'all_executions' and isinstance(existing, dict):
            original_cost = _number(existing.get('cost'))
            original_net = _number(existing.get('net'))
            if original_cost is not None and original_cost > 0 and original_net is not None:
                returns[event] = dict(cost=str(original_cost), net=str(original_net),
                    **({'estimated': True} if existing.get('estimated') else {}))
                continue
        payout = _settlement_payout(row, outcomes, event)
        returns[event] = dict(cost=str(cost), net=str(quantity * payout - cost),
                              **({'estimated': True} if estimated else {}))

    # Preserve a known exact hold record even if aggregate row size metadata
    # was subsequently retired. Unlabelled historical results remain eligible
    # only with an independently known outcome and valid entry cost.
    if policy != 'all_executions':
        for event, entry in old_returns.items():
            if event not in outcomes or event in returns:
                continue
            cost = _number(entry.get('cost'))
            net = _number(entry.get('net'))
            if cost is not None and cost > 0 and net is not None:
                returns[event] = dict(cost=str(cost), net=str(net),
                    **({'estimated': True} if entry.get('estimated') else {}))

    old_wide = row.get('wide_events')
    wide = {}
    if isinstance(old_wide, dict):
        for raw_event, records in old_wide.items():
            event = str(raw_event)
            if event not in outcomes or not isinstance(records, list):
                continue
            valid_records = []
            for record in records:
                if not isinstance(record, (list, tuple)) or len(record) < 3:
                    continue
                q, cost = _number(record[1]), _number(record[2])
                if q is None or q <= 0 or cost is None or cost <= 0:
                    continue
                if policy == 'all_executions':
                    # Never carry a real exit's P/L into the wide held view.
                    payout = _settlement_payout(row, outcomes, event)
                    valid_records.append([record[0], str(q), str(cost),
                                          str(q * payout - cost)])
                else:
                    valid_records.append(list(record))
            if valid_records:
                wide[event] = valid_records
    return dict(row, outcome_events=outcomes, return_events=returns,
                wide_events=wide, return_policy='hold_only')


def regular_favorites_held_bots(bots):
    """Derived-only portfolio view used by all three regular Favorites tables."""
    if not isinstance(bots, dict):
        return {}
    result = {}
    for bot_id, metric in bots.items():
        if isinstance(metric, dict) and isinstance(metric.get('entry_timing'), list):
            result[bot_id] = dict(metric, entry_timing=[
                regular_favorites_held_row(row) for row in metric['entry_timing']])
        else:
            result[bot_id] = metric
    return result
