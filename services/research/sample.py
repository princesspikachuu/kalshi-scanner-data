"""Deterministic, bounded preview membership from a frozen inventory manifest.

This is a *sample selector*, never a replacement for exhaustive collection.
Callers retain the original full candidate batch and label derived previews.
"""
from collections import defaultdict
from datetime import datetime
from hashlib import sha256

from .normalize import Candidate


def select_preview_candidates(candidates, *, limit=100):
    """Spread first picks across series/events, then add distinct strikes.

    The result depends only on immutable candidate fields, not input order or
    Python's process-randomized hash seed. Returned objects are the originals.
    """
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Preview limit must be 1..100 markets per day')
    events = defaultdict(list)
    tickers = set()
    for candidate in candidates:
        if not isinstance(candidate, Candidate) or not candidate.series or not candidate.event_ticker or not candidate.ticker:
            raise ValueError('Expected identified immutable candidates')
        if candidate.ticker in tickers:
            raise ValueError('Duplicate candidate ticker')
        tickers.add(candidate.ticker)
        close = datetime.fromisoformat(candidate.close_time.replace('Z', '+00:00'))
        if close.tzinfo is None:
            raise ValueError('Candidate close time requires a timezone')
        events[(candidate.series, candidate.event_ticker)].append(candidate)
    if not events:
        return ()

    groups = {key: tuple(sorted(group, key=lambda c: c.ticker)) for key, group in events.items()}
    by_series = defaultdict(list)
    for key, group in groups.items():
        first_close = min(datetime.fromisoformat(c.close_time.replace('Z', '+00:00')) for c in group)
        by_series[key[0]].append((first_close, key))
    series = sorted(by_series)
    chosen_events = []
    for index, ticker in enumerate(series):
        ordered = [key for _, key in sorted(by_series[ticker])]
        quota = limit // len(series) + (index < limit % len(series))
        count = min(len(ordered), quota)
        chosen_events.extend(ordered[i * len(ordered) // count] for i in range(count))
    selected_events = set(chosen_events)
    if len(chosen_events) < limit:
        extra = [(first_close, key) for group in by_series.values() for first_close, key in group if key not in selected_events]
        for _, key in sorted(extra)[:limit - len(chosen_events)]:
            chosen_events.append(key)

    offsets = {key: int.from_bytes(sha256((key[0] + ':' + key[1]).encode()).digest()[:4], 'big') % len(groups[key])
               for key in chosen_events}
    selected = [groups[key][offsets[key]] for key in chosen_events]
    depth = 1
    while len(selected) < limit:
        added = False
        for key in chosen_events:
            group = groups[key]
            if depth >= len(group):
                continue
            selected.append(group[(offsets[key] + depth) % len(group)])
            added = True
            if len(selected) == limit:
                break
        if not added:
            break
        depth += 1
    return tuple(selected)
