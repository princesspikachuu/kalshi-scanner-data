"""Freshness-bounded, exact-request weather inventory availability snapshots.

An empty response is evidence only for the exact series, endpoint, UTC date and
cursor that produced it. New snapshot days recheck the provider; neighboring
dates and unknown series never inherit an observed empty interval.
"""
from datetime import datetime, timedelta, timezone

from .reports import SERIES

VERSION = 'verified-weather-calendar-v1'
UTC = timezone.utc


def snapshot(scope, now=None):
    """Return the UTC-day snapshot window for a configured weather series.

    This is a cache lifetime, not a claim that provider history is immutable.
    The receipt and checkpoint remain mandatory before reuse can be considered.
    """
    if not hasattr(scope, 'series') or scope.series not in SERIES['weather'] | SERIES['weather_daily']:
        return None
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError('Calendar clock must be timezone-aware')
    start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return dict(version=VERSION, snapshot_utc=start.isoformat(), expires_utc=(start + timedelta(days=1)).isoformat())
