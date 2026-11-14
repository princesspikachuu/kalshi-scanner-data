"""Verify complete offset traversal of *one* verified R2 manifest.

This does not imply the PostgreSQL manifest catalog was exhaustively listed,
nor that trading events in other stores have been incorporated.
"""
import re
from uuid import UUID
from services.demo.shadow_history_reconcile import HistoryReconciliationError

MAX_MANIFEST_PAGES = 128


def verify_reclaimed_manifest_chain(pages):
    if not isinstance(pages, (tuple, list)) or not 1 <= len(pages) <= MAX_MANIFEST_PAGES:
        raise HistoryReconciliationError('Invalid reclaimed page chain')
    first = pages[0]
    if not isinstance(first, dict):
        raise HistoryReconciliationError('Invalid reclaimed page')
    ident, key, source, total, digest = (first.get('manifest_id'),
                                  first.get('manifest_key'),
                                  first.get('source'),
                                  first.get('total_events'),
                                  first.get('manifest_digest'))
    if (source not in ('r2_reclaimed_raw','r2_reclaimed_packed')
            or not isinstance(ident, str) or not isinstance(key, str)
            or not key.startswith('demo/shadow/archive-manifest/')
            or type(total) is not int or not 1 <= total <= 10000
            or not isinstance(digest,str) or re.fullmatch(r'[0-9a-f]{64}',digest) is None):
        raise HistoryReconciliationError('Invalid reclaimed manifest metadata')
    prefix=('demo/shadow/archive-manifest/batch/'
            if source=='r2_reclaimed_packed'
            else 'demo/shadow/archive-manifest/')
    try:
        if not key.startswith(prefix) or str(UUID(key[len(prefix):])) != key[len(prefix):]:
            raise ValueError('Invalid index suffix')
        if str(UUID(ident)) != ident:
            raise ValueError('Invalid durable manifest ID')
    except (TypeError,ValueError,AttributeError) as exc:
        raise HistoryReconciliationError('Reclaimed manifest key/ID not canonical') from exc
    seen_ids = set()
    position = 0
    for index, page in enumerate(pages):
        if (not isinstance(page, dict) or page.get('verified') is not True
                or page.get('manifest_id') != ident
                or page.get('manifest_key') != key
                or page.get('manifest_digest') != digest
                or page.get('source') != source
                or page.get('total_events') != total
                or page.get('offset') != position):
            raise HistoryReconciliationError('Reclaimed manifest page discontinuity')
        rows = page.get('items')
        count = page.get('page_events')
        if (not isinstance(rows, list) or type(count) is not int
                or not 1 <= count <= 50 or len(rows) != count):
            raise HistoryReconciliationError('Invalid reclaimed event page')
        for item in rows:
            if not isinstance(item, dict) or not isinstance(item.get('id'), str):
                raise HistoryReconciliationError('Invalid reclaimed original ID')
            if item['id'] in seen_ids:
                raise HistoryReconciliationError('Repeated original ID in manifest chain')
            seen_ids.add(item['id'])
        position += count
        if position > total:
            raise HistoryReconciliationError('Reclaimed manifest count exceeded')
        expected = position if position < total else None
        if page.get('next_offset') != expected:
            raise HistoryReconciliationError('Invalid reclaimed page continuation')
        if index < len(pages)-1 and expected is None:
            raise HistoryReconciliationError('Extra reclaimed page after completion')
        if index == len(pages)-1 and expected is not None:
            raise HistoryReconciliationError('Missing reclaimed manifest pages')
    if position != total or len(seen_ids) != total:
        raise HistoryReconciliationError('Incomplete reclaimed manifest')
    return dict(manifest_id=ident,manifest_key=key,manifest_digest=digest,
                source=source,
                original_events_verified=total,verified_pages=len(pages),
                individual_manifest_exhausted=True,
                source_exhaustion_verified=False,
                r2_manifest_catalog_complete=False,
                all_time_coverage_complete=False)
