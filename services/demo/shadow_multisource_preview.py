"""No-I/O bounded reconciliation preview of supplied history source pages.

Checks internally continuous raw, packed, manifest catalog and per-manifest
verified R2 page chains before deduplicating the original event UUIDs.
A consistent *supplied* catalog is NOT proof no other manifests exist.
Never send this preview to trading or claim global historical completeness.
"""
from services.demo.shadow_history_reconcile import (
    HistoryReconciliationError, reconcile_verified_pages,
)
from services.demo.shadow_page_chain import verify_history_page_chain
from services.demo.shadow_reclaimed_chain import verify_reclaimed_manifest_chain

MAX_PREVIEW_PAGES=16
MAX_PREVIEW_MANIFESTS=8


def reconcile_supplied_history(raw_pages, packed_pages, manifest_pages, reclaimed_by_id):
    """Return a strictly partial preview; fail rather than silently truncate."""
    for kind,pages in (('raw',raw_pages),('packed',packed_pages),
                       ('manifests',manifest_pages)):
        if not isinstance(pages,(list,tuple)) or not 1<=len(pages)<=MAX_PREVIEW_PAGES:
            raise HistoryReconciliationError('Missing or oversized history chain')
        verify_history_page_chain(pages,kind)
    if not isinstance(reclaimed_by_id,dict) or len(reclaimed_by_id)>MAX_PREVIEW_MANIFESTS:
        raise HistoryReconciliationError('Invalid reclaimed history catalog')
    manifests={}
    for page in manifest_pages:
        for item in page['items']:
            if not isinstance(item,dict):
                raise HistoryReconciliationError('Malformed archive manifest summary')
            ident=item.get('manifest_id')
            key=item.get('manifest_key')
            digest=item.get('manifest_digest')
            kind=item.get('kind')
            total=item.get('original_events')
            if (not isinstance(ident,str) or not isinstance(key,str)
                    or not isinstance(digest,str) or kind not in ('raw','packed')
                    or type(total) is not int or total<1
                    or ident in manifests):
                raise HistoryReconciliationError('Duplicate or incomplete archive manifest')
            manifests[ident]=(key,digest,kind,total)
    if len(manifests)>MAX_PREVIEW_MANIFESTS:
        raise HistoryReconciliationError('Too many archive manifests for bounded preview')
    if set(reclaimed_by_id)!=set(manifests):
        raise HistoryReconciliationError('Archive manifest pages omitted or unexpected')
    pieces=[]
    for kind,pages in (('raw',raw_pages),('packed',packed_pages)):
        for page in pages:
            pieces.append(dict(source='hot_raw' if kind=='raw' else 'hot_packed',
                               items=page['items']))
    verified_manifests=0
    for ident in sorted(manifests):
        pages=reclaimed_by_id[ident]
        expected_key,expected_digest,expected_kind,expected_total=manifests[ident]
        receipt=verify_reclaimed_manifest_chain(pages)
        if (receipt['manifest_id']!=ident or receipt['manifest_key']!=expected_key
                or receipt['manifest_digest']!=expected_digest
                or receipt['original_events_verified']!=expected_total
                or receipt['source']!=('r2_reclaimed_raw' if expected_kind=='raw'
                                       else 'r2_reclaimed_packed')):
            raise HistoryReconciliationError('Manifest catalog and R2 receipts conflict')
        verified_manifests+=1
        for page in pages:
            pieces.append(dict(source=page['source'],verified=True,items=page['items']))
    if len(pieces)>MAX_PREVIEW_PAGES:
        raise HistoryReconciliationError('Preview event pages exceed bounded budget')
    reconciled=reconcile_verified_pages(pieces)
    return dict(contract='mt019-supplied-history-preview-v1',
                items=reconciled['items'],
                unique_original_events=reconciled['unique_events'],
                duplicate_source_copies=reconciled['duplicate_copies'],
                input_original_copies=reconciled['input_events'],
                supplied_archived_manifests=verified_manifests,
                supplied_postgres_raw_pages=len(raw_pages),
                supplied_postgres_packed_pages=len(packed_pages),
                supplied_manifest_catalog_pages=len(manifest_pages),
                supplied_chains_verified=True,
                database_snapshot_verified=False,
                r2_manifest_catalog_complete=False,
                all_time_coverage_complete=False,
                safe_to_train=False,
                safe_to_restart_writers=False,
                real_orders_enabled=False)
