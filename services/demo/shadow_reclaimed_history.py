"""Normalize already verified R2 reclaimed-manifest pages for owner history.

No R2 or database access lives here. The only caller that may set verified
is the existing SHA/gzip/full-row manifest reader. An incomplete page never
claims an all-time historical dataset or changes Favorites financial totals.
"""
from uuid import UUID

from services.demo.shadow_history_reconcile import (
    HistoryReconciliationError, reconcile_verified_pages,
)

MAX_RECLAIMED_PAGE_EVENTS = 50
KINDS = {'raw': 'r2_reclaimed_raw', 'packed': 'r2_reclaimed_packed'}


def normalize_reclaimed_manifest_page(result, *, offset):
    if not isinstance(result, dict) or result.get('verified') is not True:
        raise HistoryReconciliationError('R2 manifest verification required')
    if type(offset) is not int or not 0 <= offset <= 10000:
        raise HistoryReconciliationError('Invalid R2 page offset')
    manifest = result.get('manifest')
    if not isinstance(manifest, dict):
        raise HistoryReconciliationError('Missing verified manifest')
    kind = manifest.get('kind')
    if kind not in KINDS:
        raise HistoryReconciliationError('Unknown reclaimed manifest kind')
    identifier = manifest.get('manifest_id')
    key = manifest.get('manifest_key')
    expected_key_prefix = ('demo/shadow/archive-manifest/batch/'
                           if kind == 'packed' else 'demo/shadow/archive-manifest/')
    try:
        if not isinstance(identifier, str) or str(UUID(identifier)) != identifier:
            raise ValueError('Noncanonical manifest UUID')
    except (TypeError, ValueError, AttributeError) as exc:
        raise HistoryReconciliationError('Invalid reclaimed manifest identity') from exc
    if not isinstance(key, str) or key != expected_key_prefix+identifier:
        raise HistoryReconciliationError('Invalid reclaimed manifest identity')
    original_events = manifest.get('original_events')
    if type(original_events) is not int or original_events < 1:
        raise HistoryReconciliationError('Invalid manifest event count')
    total = result.get('total_events')
    if type(total) is not int or total != original_events:
        raise HistoryReconciliationError('Original event count mismatch')
    rows = result.get('items')
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_RECLAIMED_PAGE_EVENTS:
        raise HistoryReconciliationError('Empty or oversized reclaimed page')
    if offset >= total or offset+len(rows) > total:
        raise HistoryReconciliationError('Reclaimed page outside manifest bounds')
    expected_next = offset+len(rows) if offset+len(rows) < total else None
    if result.get('next_offset') != expected_next:
        raise HistoryReconciliationError('Reclaimed event cursor mismatch')
    if result.get('source') != 'cloudflare-r2':
        raise HistoryReconciliationError('Unexpected reclaimed data source')
    events = []
    for row in rows:
        if not isinstance(row, dict):
            raise HistoryReconciliationError('Invalid archived event')
        p = row.get('progress')
        if not isinstance(p, dict):
            raise HistoryReconciliationError('Missing archived progress')
        events.append(dict(
            id=row.get('id'), key=row.get('key'),
            parameters=row.get('parameters'), progress=p,
            event_time=p.get('time'),
            **({'packed_batch_key': row['packed_batch_key']} if 'packed_batch_key' in row else {})
        ))
    page=dict(source=KINDS[kind],verified=True,items=events)
    # Reuse the central original UUID/key/progress verifier, rather than
    # trusting a manifest's count alone or treating a receipt as an event.
    verified = reconcile_verified_pages([page])
    if verified['unique_events'] != len(events):
        raise HistoryReconciliationError('Duplicate events inside one R2 page')
    return dict(contract='demo-v1',source=KINDS[kind],manifest_id=identifier,
                manifest_key=key,offset=offset,total_events=total,
                items=verified['items'],next_offset=expected_next,
                page_events=len(events),verified=True,
                source_exhaustion_verified=False,
                r2_manifest_catalog_complete=False,
                all_time_coverage_complete=False,
                real_orders_enabled=False)
