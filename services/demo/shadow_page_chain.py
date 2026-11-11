"""Pure pagination-chain verification for indexed shadow evidence sources.

A validated chain only proves that the *supplied pages* are internally
continuous. It cannot prove a database snapshot, full R2 catalog enumeration,
or all-time financial coverage. No SQL/R2/network operations are performed.
"""
from services.demo.shadow_history_reconcile import HistoryReconciliationError

PREFIXES = {
    'raw': 'demo/shadow/event/',
    'packed': 'demo/shadow/event-batch/',
    'manifests': 'demo/shadow/archive-manifest/',
}
MAX_PAGES = 64


def verify_history_page_chain(pages, source):
    if source not in PREFIXES:
        raise HistoryReconciliationError('Unknown page source')
    if not isinstance(pages, (list, tuple)) or not 1 <= len(pages) <= MAX_PAGES:
        raise HistoryReconciliationError('Invalid or unbounded page chain')
    prefix = PREFIXES[source]
    cursor = None
    seen = set()
    total = 0
    for index, page in enumerate(pages):
        if not isinstance(page, dict):
            raise HistoryReconciliationError('Invalid page')
        if source == 'manifests':
            if page.get('order') != 'manifest_key':
                raise HistoryReconciliationError('Invalid manifest ordering')
        elif page.get('source') != source or page.get('order') != 'idempotency_key_ascending':
            raise HistoryReconciliationError('Invalid history ordering')
        if page.get('request_cursor') != cursor:
            # The collecting caller explicitly records its request cursor;
            # an omitted/incorrect cursor must not claim page continuity.
            raise HistoryReconciliationError('History cursor discontinuity')
        items = page.get('items')
        if not isinstance(items, list):
            raise HistoryReconciliationError('Invalid history items')
        if source == 'manifests':
            keys = [item.get('manifest_key') if isinstance(item, dict) else None
                    for item in items]
            # Indexed manifest keys come from the owner-authenticated
            # manifest listing; these are not R2 object addresses.
        else:
            keys = [item.get('key') if isinstance(item, dict) else None
                    for item in items]
            if source == 'packed':
                # A packed page expands original event IDs, not source row
                # keys. Require explicit source-row keys from indexed response.
                keys = page.get('source_keys')
                if not isinstance(keys, list):
                    raise HistoryReconciliationError('Packed source keys missing')
        if any(not isinstance(key, str) or not key.startswith(prefix)
               or key <= (cursor or prefix) for key in keys):
            raise HistoryReconciliationError('Invalid history key order')
        if keys != sorted(keys) or len(set(keys)) != len(keys):
            raise HistoryReconciliationError('Unsorted or repeated history keys')
        if any(key in seen for key in keys):
            raise HistoryReconciliationError('Repeated history source row')
        seen.update(keys)
        total += len(items)
        more = page.get('more')
        next_cursor = page.get('next_cursor')
        if type(more) is not bool:
            raise HistoryReconciliationError('Missing termination indicator')
        if more:
            if not keys or next_cursor != keys[-1] or index == len(pages)-1:
                raise HistoryReconciliationError('Broken history page continuation')
            cursor = next_cursor
        else:
            if next_cursor is not None or index != len(pages)-1:
                raise HistoryReconciliationError('Premature history termination')
    return dict(source=source, supplied_pages=len(pages),
                supplied_items=total, supplied_keys=len(seen),
                pagination_chain_verified=True,
                database_snapshot_verified=False,
                r2_manifest_catalog_complete=False,
                all_time_coverage_complete=False)
