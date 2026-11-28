"""Evaluate read-only Render telemetry outside the paper-trading worker.

The caller collects telemetry and delivers the returned alerts. This utility
only reads and writes its own JSON state and performs no network operations.
"""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import time


EVENT_OVERLAP = 15 * 60
EVENT_BACKFILL = 60 * 60
REPEAT_SECONDS = 60 * 60


def timestamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def event_start(state, now):
    previous = state.get('event_end')
    return min(now - EVENT_BACKFILL, previous - EVENT_OVERLAP) if previous is not None else now - EVENT_BACKFILL


def latest_run(samples, predicate):
    """Length of the current confirmed run, allowing a missed sampled point."""
    end = start = None
    for at, value in reversed(samples):
        if not predicate(value) or (start is not None and start - at > 180):
            break
        if end is None:
            end = at
        start = at
    return 0 if start is None else end - start


def evaluate(state, snapshot):
    now = snapshot['now']
    alerts = []
    signals = state.setdefault('signals', {})

    def transition(key, tier, **evidence):
        # A missing measurement must not mark a live incident resolved.
        if tier is None:
            return
        previous = signals.get(key, {})
        before = previous.get('tier', 0)
        last_alert = previous.get('last_alert', 0)
        if tier > before or (tier and now - last_alert >= REPEAT_SECONDS) or (before and tier == 0):
            alerts.append(dict(signal=key, tier=tier, **evidence))
            last_alert = now
        signals[key] = dict(tier=tier, last_alert=last_alert)

    events = snapshot.get('events')
    transition('render_events_unavailable', int(events is None))
    if events is not None:
        cutoff = event_start(state, now)
        seen = state.setdefault('event_ids', {})
        failures = []
        for event in sorted(events, key=lambda row: row['timestamp']):
            at = timestamp(event['timestamp'])
            if event['type'] != 'server_failed' or not cutoff <= at <= now or event['id'] in seen:
                continue
            seen[event['id']] = at
            reason = (event.get('details') or {}).get('reason') or {}
            failures.append(dict(id=event['id'], at=event['timestamp'], oom=bool(reason.get('oomKilled'))))
        if failures:
            alerts.append(dict(signal='render_worker_crash', tier=3, count=len(failures), events=failures))
        state['event_end'] = now
        state['event_ids'] = {key: at for key, at in seen.items() if at >= now - EVENT_BACKFILL}

    # The collector supplies worst utilization across worker instances for each
    # timestamp; values are fractions of the measured memory limit.
    memory = sorted((at, ratio) for at, ratio in snapshot.get('memory', []) if now - 3600 <= at <= now)
    memory_missing = not memory or now - memory[-1][0] > 300
    transition('render_memory_telemetry_stale', int(memory_missing))
    if not memory_missing:
        ratio = memory[-1][1]
        peak = max(value for at, value in memory if at >= now - 900)
        sustained = latest_run(memory, lambda value: value >= .75)
        tier = 3 if peak >= .95 else 2 if peak >= .90 or sustained >= 1800 else 1 if sustained >= 600 else 0
        transition('render_memory_pressure', tier, latest=ratio, peak_15m=peak, sustained_seconds=sustained)

    groups = {}
    for row in snapshot.get('logs', []):
        at = timestamp(row['timestamp'])
        if now - 1800 <= at <= now:
            groups.setdefault(row['event'], []).append((at, row))
    for rows in groups.values():
        rows.sort(key=lambda item: item[0])

    def fresh(name, folder=None):
        return [(at, row) for at, row in groups.get(name, [])
                if folder is None or row.get('folder') == folder]

    def current(rows):
        return rows[-1][1] if rows and now - rows[-1][0] <= 300 else None

    pipeline = fresh('shadow_pipeline_cost')
    transition('render_worker_heartbeat_stale', int(current(pipeline) is None))

    capacity = fresh('paper_monitoring_capacity')
    if (last := current(capacity)) is not None:
        duration = latest_run(capacity, lambda row: row.get('admitting') is False)
        transition('favorites_discovery_interrupted', int(duration >= 600),
                   seconds=duration, reason=last.get('reason'))

    trading = fresh('favorites_trading_diagnostics', 'favorites')
    if (last := current(trading)) is not None:
        transition('favorites_books_stale', int(latest_run(trading, lambda row:
            row.get('running_bots', 0) > 0 and row.get('active_markets', 0) > 0
            and row.get('fresh_active_books') == 0) >= 300), active_markets=last.get('active_markets'))

    if (last := current(fresh('paper_position_settlement_poll_health'))) is not None:
        count = last.get('held_by_folder', {}).get('favorites', 0)
        age = max((row.get('expired_seconds', 0) for row in last.get('oldest_favorites', [])), default=0)
        transition('favorites_settlement_backlog', int(count > 0 and age >= 1800), held=count, oldest_seconds=age)

    activity_rows = fresh('favorites_quote_lifecycle')
    activity = current(activity_rows)
    if activity is not None and current(trading) is not None:
        window = activity.get('window_seconds', 0)
        if window and now - activity.get('telemetry_started_at', now) >= window:
            submitted, fills = activity['submitted_orders'], activity['first_filled_events']
            healthy_books = latest_run(trading, lambda row:
                row.get('running_bots', 0) > 0 and row.get('fresh_active_books', 0) > 0) >= 600
            without_attempts = latest_run(activity_rows, lambda row: row['submitted_orders'] == 0)
            without_fills = latest_run(activity_rows, lambda row: row['first_filled_events'] == 0)
            transition('favorites_low_activity', int((healthy_books and without_attempts >= 900) or
                (submitted >= 10 and without_fills >= 900)), submissions=submitted, filled_events=fills,
                window_seconds=window)

    return alerts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--input', type=Path)
    args = parser.parse_args()
    state = json.loads(args.state.read_text(encoding='utf-8')) if args.state.exists() else {}
    if args.input is None:
        print(json.dumps(dict(event_start=event_start(state, time.time()))))
        return
    snapshot = json.loads(args.input.read_text(encoding='utf-8-sig'))
    alerts = evaluate(state, snapshot)
    temp = args.state.with_suffix('.tmp')
    temp.write_text(json.dumps(state), encoding='utf-8')
    os.replace(temp, args.state)
    print(json.dumps(dict(alerts=alerts)))


if __name__ == '__main__':
    main()
