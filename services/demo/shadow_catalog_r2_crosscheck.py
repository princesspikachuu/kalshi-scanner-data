"""Fail-closed comparison of *supplied* PostgreSQL manifest listings to R2 pages.

Pure, bounded, no I/O. Both R2 manifest verification and source-page
authentication must happen upstream. A terminal supplied keyset chain is
NOT proof of a stable or globally exhaustive PostgreSQL snapshot.
"""
import hashlib
import json
import re
from uuid import UUID

from services.demo.shadow_history_reconcile import (
    HistoryReconciliationError, _validated_event,
)
from services.demo.shadow_keyset_receipts import extend_keyset_receipt
from services.demo.shadow_reclaimed_chain import verify_reclaimed_manifest_chain

MAX_CATALOG_PAGES = 8
MAX_MANIFESTS = 32
MAX_TOTAL_R2_PAGES = 128
MAX_TOTAL_ORIGINALS = 4000
MANIFEST_PREFIX = 'demo/shadow/archive-manifest/'


def _canonical_uuid(value, what):
    if not isinstance(value, str):
        raise HistoryReconciliationError('Invalid '+what)
    try:
        if str(UUID(value)) != value:
            raise ValueError('Noncanonical UUID')
    except (ValueError, TypeError, AttributeError) as exc:
        raise HistoryReconciliationError('Invalid '+what) from exc
    return value


def _manifest_metadata(item):
    if not isinstance(item, dict):
        raise HistoryReconciliationError('Invalid supplied manifest metadata')
    kind = item.get('kind')
    if kind not in ('raw', 'packed'):
        raise HistoryReconciliationError('Invalid supplied manifest kind')
    ident = _canonical_uuid(item.get('manifest_id'), 'manifest row UUID')
    prefix = MANIFEST_PREFIX + ('batch/' if kind == 'packed' else '')
    key = item.get('manifest_key')
    if not isinstance(key, str) or not key.startswith(prefix):
        raise HistoryReconciliationError('Manifest index kind mismatch')
    suffix = _canonical_uuid(key[len(prefix):], 'manifest index UUID')
    mode = ('canonical_row_key' if suffix == ident else 'legacy_independent_key')
    if item.get('manifest_identity_mode', mode) != mode:
        raise HistoryReconciliationError('Manifest identity mode mismatch')
    digest = item.get('manifest_digest')
    if not isinstance(digest, str) or re.fullmatch(r'[0-9a-f]{64}', digest) is None:
        raise HistoryReconciliationError('Invalid supplied manifest digest')
    rows, originals = item.get('archived_rows'), item.get('original_events')
    if (type(rows) is not int or type(originals) is not int
            or not 1 <= rows <= originals <= 10000
            or (kind == 'raw' and rows != originals)):
        raise HistoryReconciliationError('Invalid manifest row/original counts')
    return dict(key=key, id=ident, kind=kind, digest=digest,
                original_events=originals, archived_rows=rows,
                identity_mode=mode)


def audit_supplied_catalog_readbacks(catalog_pages, readback_pages_by_key):
    """Compare one bounded terminal *supplied* manifest list to R2 readbacks.

    The supplied data must come from authenticated, independently verified
    reader calls. This function checks evidence consistency but cannot detect
    rows omitted by a malicious reader or changes between SQL transactions.
    """
    if (not isinstance(catalog_pages, (tuple, list))
            or not 1 <= len(catalog_pages) <= MAX_CATALOG_PAGES
            or not isinstance(readback_pages_by_key, dict)
            or len(readback_pages_by_key) > MAX_MANIFESTS):
        raise HistoryReconciliationError('Archive catalog comparison budget exceeded')
    cursor_receipt = None
    listed = {}
    seen_manifest_ids = set()
    for page in catalog_pages:
        if not isinstance(page, dict) or not isinstance(page.get('items'), list):
            raise HistoryReconciliationError('Invalid supplied catalog page')
        if len(listed) + len(page['items']) > MAX_MANIFESTS:
            raise HistoryReconciliationError('Too many supplied archive manifests')
        cursor_receipt = extend_keyset_receipt(cursor_receipt, 'manifests', page)
        for row in page['items']:
            manifest = _manifest_metadata(row)
            if manifest['key'] in listed or manifest['id'] in seen_manifest_ids:
                raise HistoryReconciliationError('Repeated archive manifest identity')
            listed[manifest['key']] = manifest
            seen_manifest_ids.add(manifest['id'])
    if cursor_receipt['terminal'] is not True:
        raise HistoryReconciliationError('Supplied archive catalog has more pages')
    if set(readback_pages_by_key) != set(listed):
        raise HistoryReconciliationError('Missing or unlisted archive readback')
    seen_original_ids = set()
    seen_original_keys = set()
    total_pages = total_originals = 0
    raw_manifests = packed_manifests = 0
    digest = hashlib.sha256()
    for key in sorted(listed):
        manifest = listed[key]
        pages = readback_pages_by_key[key]
        if not isinstance(pages, (tuple, list)):
            raise HistoryReconciliationError('Invalid R2 readback page group')
        total_pages += len(pages)
        if total_pages > MAX_TOTAL_R2_PAGES:
            raise HistoryReconciliationError('R2 readback page budget exceeded')
        receipt = verify_reclaimed_manifest_chain(pages)
        expected_source = ('r2_reclaimed_raw' if manifest['kind'] == 'raw'
                           else 'r2_reclaimed_packed')
        if (receipt['source'] != expected_source
                or receipt['manifest_id'] != manifest['id']
                or receipt['manifest_key'] != key
                or receipt['manifest_digest'] != manifest['digest']
                or receipt['original_events_verified'] != manifest['original_events']
                or receipt['individual_manifest_exhausted'] is not True):
            raise HistoryReconciliationError('Catalog/readback manifest mismatch')
        total_originals += receipt['original_events_verified']
        if total_originals > MAX_TOTAL_ORIGINALS:
            raise HistoryReconciliationError('Too many supplied archived originals')
        raw_manifests += manifest['kind'] == 'raw'
        packed_manifests += manifest['kind'] == 'packed'
        for page in pages:
            for raw in page['items']:
                original = _validated_event(raw, expected_source)
                ident, original_key = original['id'], original['key']
                if ident in seen_original_ids or original_key in seen_original_keys:
                    raise HistoryReconciliationError('Original repeated across R2 manifests')
                seen_original_ids.add(ident)
                seen_original_keys.add(original_key)
                digest.update(json.dumps(
                    [key, ident, original_key], separators=(',', ':'),
                    ensure_ascii=True).encode('utf-8'))
    if len(seen_original_ids) != total_originals:
        raise HistoryReconciliationError('Missing archived original identities')
    return dict(
        contract='mt019-supplied-catalog-r2-crosscheck-v1',
        supplied_catalog_pages=len(catalog_pages),
        listed_manifests=len(listed),
        raw_manifests=raw_manifests,
        packed_manifests=packed_manifests,
        checked_readback_pages=total_pages,
        claimed_archived_source_rows=sum(x['archived_rows'] for x in listed.values()),
        checked_archived_originals=total_originals,
        unique_archived_original_ids=len(seen_original_ids),
        cross_manifest_identity_digest=digest.hexdigest(),
        supplied_catalog_terminal=True,
        readbacks_match_every_listed_manifest=True,
        # Caller-supplied verified R2 pages must originate in an independently
        # authenticated object SHA/gzip readback; this module performs no I/O.
        live_postgres_snapshot_consistent=False,
        independent_r2_reverification_performed=False,
        global_r2_catalog_exhaustion_verified=False,
        source_exhaustion_verified=False,
        authoritative_settlement_verified=False,
        realized_pnl_reconciled=False,
        all_time_coverage_complete=False,
        safe_to_train=False,
        safe_to_restart_writers=False,
        real_orders_enabled=False,
    )
