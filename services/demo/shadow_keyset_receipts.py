"""Pure rolling source-keyset page receipts for long diagnostic histories.

Works on *indexed source keys* (not original UUID ordering). It does no I/O,
does not prove an unvisited source row exists or that a writer was stopped,
and cannot justify archival, all-time learning, or financial reconciliation.
"""
import hashlib
import re

from services.demo.shadow_history_reconcile import HistoryReconciliationError

PREFIXES = {
    'raw': 'demo/shadow/event/',
    'packed': 'demo/shadow/event-batch/',
    'manifests': 'demo/shadow/archive-manifest/',
}
MAX_KEYS_PER_PAGE = 25
ZERO_HASH = '0' * 64
CONTRACT = 'mt019-source-keyset-chain-v1'


def _state(previous, source):
    if source not in PREFIXES:
        raise HistoryReconciliationError('Invalid indexed source')
    if previous is None:
        return dict(source=source, pages_seen=0, source_rows=0,
                    original_events=0, manifest_originals_claimed=0,
                    last_key=None, next_cursor=None, terminal=False,
                    source_key_digest=ZERO_HASH)
    if not isinstance(previous, dict) or previous.get('contract') != CONTRACT:
        raise HistoryReconciliationError('Invalid source receipt contract')
    if previous.get('source') != source:
        raise HistoryReconciliationError('Source changed between pages')
    for name in ('pages_seen','source_rows','original_events','manifest_originals_claimed'):
        if type(previous.get(name)) is not int or previous[name] < 0:
            raise HistoryReconciliationError('Invalid source receipt counts')
    if type(previous.get('terminal')) is not bool:
        raise HistoryReconciliationError('Invalid source termination flag')
    if not isinstance(previous.get('source_key_digest'), str) or not re.fullmatch(
            r'[0-9a-f]{64}',previous['source_key_digest']):
        raise HistoryReconciliationError('Invalid source receipt hash')
    last = previous.get('last_key')
    cursor = previous.get('next_cursor')
    if previous['pages_seen'] == 0 or not isinstance(last,str):
        raise HistoryReconciliationError('Uninitialized prior source receipt')
    if not last.startswith(PREFIXES[source]):
        raise HistoryReconciliationError('Invalid last indexed key')
    if previous['terminal']:
        if cursor is not None:
            raise HistoryReconciliationError('Terminal receipt has continuation')
    elif cursor != last:
        raise HistoryReconciliationError('Broken prior source continuation')
    return {k:previous[k] for k in (
        'source','pages_seen','source_rows','original_events',
        'manifest_originals_claimed','last_key','next_cursor',
        'terminal','source_key_digest')}


def extend_keyset_receipt(previous, source, page):
    """Check one authenticated source-keyset response and extend a tiny receipt.

    This is a *continuation record*, NOT an assertion the pages came from a
    stable DB snapshot. A caller must authenticate and actually fetch pages
    from the existing bounded endpoints. It cannot forge missing source keys.
    """
    state=_state(previous,source)
    if state['terminal']:
        raise HistoryReconciliationError('Page after terminal source page')
    if not isinstance(page,dict) or page.get('source') != source:
        raise HistoryReconciliationError('Invalid page source')
    expected_order='manifest_key' if source=='manifests' else 'idempotency_key_ascending'
    if page.get('order') != expected_order:
        raise HistoryReconciliationError('Invalid indexed page ordering')
    if page.get('request_cursor') != state['next_cursor']:
        raise HistoryReconciliationError('Source cursor discontinuity')
    items=page.get('items')
    if not isinstance(items,list):
        raise HistoryReconciliationError('Invalid page originals')
    if source=='manifests':
        keys=[entry.get('manifest_key') if isinstance(entry,dict) else None
              for entry in items]
        claimed=0
        for entry in items:
            value=entry.get('original_events') if isinstance(entry,dict) else None
            if type(value) is not int or value<=0:
                raise HistoryReconciliationError('Invalid manifest claimed original count')
            claimed+=value
    else:
        keys=page.get('source_keys')
        if not isinstance(keys,list):
            raise HistoryReconciliationError('Missing indexed source row keys')
        claimed=0
        rows=page.get('source_rows')
        originals=page.get('original_events')
        if (type(rows) is not int or rows!=len(keys)
                or type(originals) is not int or originals!=len(items)):
            raise HistoryReconciliationError('Source count mismatch')
        if source=='raw' and len(items)!=len(keys):
            raise HistoryReconciliationError('Raw source row expansion mismatch')
        if source=='packed' and len(items)>0 and not keys:
            raise HistoryReconciliationError('Packed originals have no source row')
    if len(keys)>MAX_KEYS_PER_PAGE:
        raise HistoryReconciliationError('Source page exceeds bounded key count')
    prior=state['last_key']
    prefix=PREFIXES[source]
    if any(not isinstance(key,str) or not key.startswith(prefix) or
           key<=(prior if prior is not None else prefix) for key in keys):
        raise HistoryReconciliationError('Indexed source key out of range')
    if keys!=sorted(keys) or len(keys)!=len(set(keys)):
        raise HistoryReconciliationError('Unsorted or repeated source keys')
    more=page.get('more')
    if type(more) is not bool:
        raise HistoryReconciliationError('Missing source continuation flag')
    requested_next=page.get('next_cursor')
    if more:
        if not keys or requested_next!=keys[-1]:
            raise HistoryReconciliationError('Invalid source continuation key')
    elif requested_next is not None:
        raise HistoryReconciliationError('Terminal source page still has cursor')
    digest=state['source_key_digest']
    for key in keys:
        digest=hashlib.sha256(bytes.fromhex(digest)+key.encode('utf-8')).hexdigest()
    return dict(
        contract=CONTRACT,source=source,
        pages_seen=state['pages_seen']+1,
        source_rows=state['source_rows']+len(keys),
        original_events=state['original_events']+(len(items) if source!='manifests' else 0),
        manifest_originals_claimed=state['manifest_originals_claimed']+claimed,
        last_key=keys[-1] if keys else state['last_key'],
        next_cursor=requested_next,
        terminal=not more,
        source_key_digest=digest,
        supplied_keyset_chain_verified=True,
        stable_database_snapshot_verified=False,
        r2_manifest_catalog_complete=False,
        all_time_coverage_complete=False,
        financial_reconciliation_complete=False,
        safe_to_train=False,
        safe_to_restart_writers=False,
    )
