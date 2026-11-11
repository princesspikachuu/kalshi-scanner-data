"""Read-only logical PostgreSQL growth budget without false disk claims.

pg_database_size is NOT physical filesystem free space and excludes WAL
headroom. Never use this signal to authorize deletion, VACUUM FULL, trading,
disk expansion, or background archival.
"""
from decimal import Decimal, InvalidOperation

GIB = 1024**3
WARN_FRACTION = Decimal('0.70')
CRITICAL_FRACTION = Decimal('0.85')


def budget_snapshot(database_bytes, capacity_gb):
    if isinstance(database_bytes, bool) or type(database_bytes) is not int or database_bytes < 0:
        raise ValueError('Invalid logical PostgreSQL bytes')
    if isinstance(capacity_gb, bool):
        raise ValueError('Invalid configured database capacity')
    try:
        capacity = Decimal(str(capacity_gb))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError('Invalid configured database capacity') from exc
    if not capacity.is_finite() or not Decimal('1') <= capacity <= Decimal('1024'):
        raise ValueError('Invalid configured database capacity')
    cap_bytes = capacity * GIB
    fraction = Decimal(database_bytes) / cap_bytes
    level = ('critical' if fraction >= CRITICAL_FRACTION else
             'warning' if fraction >= WARN_FRACTION else 'below_warning')
    return dict(
        metric='logical_pg_database_size_only',
        database_bytes=database_bytes,
        configured_capacity_gib=str(capacity),
        logical_fraction_of_capacity=str(round(fraction, 6)),
        threshold_level=level,
        warning_threshold_fraction=str(WARN_FRACTION),
        critical_threshold_fraction=str(CRITICAL_FRACTION),
        physical_disk_used_bytes=None,
        filesystem_free_bytes=None,
        wal_headroom_bytes=None,
        physical_headroom_verified=False,
        safe_to_reclaim=False,
        safe_to_restart_writers=False,
    )


def growth_snapshot(earlier, later, capacity_gb):
    """Classify only two already-measured, timestamped logical snapshots."""
    if not all(isinstance(record, dict) for record in (earlier,later)):
        raise ValueError('Missing logical storage measurements')
    try:
        older_bytes, newer_bytes = earlier['database_bytes'], later['database_bytes']
        older_at, newer_at = Decimal(str(earlier['at'])), Decimal(str(later['at']))
    except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError('Invalid measurement provenance') from exc
    if (type(older_bytes) is not int or type(newer_bytes) is not int or
            older_bytes < 0 or newer_bytes < 0 or
            not older_at.is_finite() or not newer_at.is_finite() or newer_at <= older_at):
        raise ValueError('Invalid measurement order')
    delta = newer_bytes-older_bytes
    per_hour = Decimal(delta)*3600/(newer_at-older_at)
    later_budget = budget_snapshot(newer_bytes, capacity_gb)
    cap_bytes = Decimal(later_budget['configured_capacity_gib'])*GIB
    rate_fraction = per_hour/cap_bytes
    return dict(
        older_database_bytes=older_bytes,
        newer_database_bytes=newer_bytes,
        delta_bytes=delta,
        seconds_between=str(newer_at-older_at),
        logical_bytes_per_hour=str(round(per_hour, 2)),
        growth_fraction_of_capacity_per_hour=str(round(rate_fraction, 8)),
        rapid_growth_flag=rate_fraction >= Decimal('.01'),
        physical_headroom_verified=False,
        action='observe_only',
    )
