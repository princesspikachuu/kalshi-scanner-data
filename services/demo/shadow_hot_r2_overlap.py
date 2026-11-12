"""Read-only overlap check for bounded supplied hot and archived shadow originals.

Offline diagnostics only. The source pages and R2 readbacks MUST be obtained
through separately authenticated readers. Terminal keyset cursors do not prove
that the underlying database remained stable while pages were fetched.
"""
from services.demo.shadow_catalog_r2_crosscheck import (
    audit_supplied_catalog_readbacks,
)
from services.demo.shadow_history_reconcile import (
    HistoryReconciliationError, MAX_INPUT_EVENTS, reconcile_verified_pages,
)
from services.demo.shadow_keyset_receipts import extend_keyset_receipt

MAX_COMBINED_PAGES = 16
MAX_HOT_PAGES_PER_SOURCE = 8
RAW_PREFIX = 'demo/shadow/event/'
PACKED_PREFIX = 'demo/shadow/event-batch/'


def _hot_pages(source, pages):
    """Validate a complete *supplied* indexed source chain and its provenance."""
    if (not isinstance(pages, (list, tuple))
            or not 1 <= len(pages) <= MAX_HOT_PAGES_PER_SOURCE):
        raise HistoryReconciliationError('Invalid bounded hot source page chain')
    receipt = None
    normalized = []
    for page in pages:
        receipt = extend_keyset_receipt(receipt, source, page)
        originals = page['items']
        source_keys = page['source_keys']
        if source == 'raw':
            # The raw SQL index row is itself the original event. A supplied
            # page cannot claim key A while substituting original key B.
            if [item.get('key') if isinstance(item, dict) else None
                    for item in originals] != source_keys:
                raise HistoryReconciliationError('Raw indexed key/original mismatch')
            if len(source_keys) > 4:
                raise HistoryReconciliationError('Raw source exceeds SQL page budget')
        else:
            # Each currently supported packed SQL page contains one batch.
            # Every decoded event must link back to that exact batch.
            if len(source_keys) > 1:
                raise HistoryReconciliationError('Packed source exceeds SQL page budget')
            if any(not isinstance(item, dict)
                   or item.get('packed_batch_key') not in source_keys
                   for item in originals):
                raise HistoryReconciliationError('Packed original/batch key mismatch')
            if source_keys and any(not key.startswith(PACKED_PREFIX)
                                   for key in source_keys):
                raise HistoryReconciliationError('Packed source namespace mismatch')
        normalized.append(dict(source='hot_' + source, items=originals))
    if receipt['terminal'] is not True:
        raise HistoryReconciliationError('Supplied hot source has more indexed pages')
    return receipt, normalized


def audit_supplied_hot_r2_overlap(raw_pages, packed_pages, catalog_pages,
                                  readback_pages_by_key):
    """Cross-check a bounded set of hot originals against verified R2 archives.

    A matching original appearing both hot and archived counts as ONE identity;
    mismatched payloads or reused original keys reject the entire audit.
    All coverage, settlement, trading and writer-restart gates remain false.
    """
    # Check independently validated R2 catalog/readback identity and source
    # chain integrity BEFORE deduplicating any copies against hot originals.
    archive = audit_supplied_catalog_readbacks(catalog_pages,
                                                readback_pages_by_key)
    raw_receipt, raw = _hot_pages('raw', raw_pages)
    packed_receipt, packed = _hot_pages('packed', packed_pages)
    cold = [page for key in sorted(readback_pages_by_key)
            for page in readback_pages_by_key[key]]
    pages = raw + packed + cold
    if len(pages) > MAX_COMBINED_PAGES:
        raise HistoryReconciliationError('Combined source page budget exceeded')
    supplied = sum(len(page['items']) for page in pages)
    if supplied > MAX_INPUT_EVENTS:
        raise HistoryReconciliationError('Combined original event budget exceeded')

    joined = reconcile_verified_pages(pages)
    hot_originals = raw_receipt['original_events'] + packed_receipt['original_events']
    if joined['input_events'] != hot_originals + archive['checked_archived_originals']:
        raise HistoryReconciliationError('Original source/readback count mismatch')
    return dict(
        contract='mt019-supplied-hot-r2-overlap-v1',
        raw_source_pages=raw_receipt['pages_seen'],
        packed_source_pages=packed_receipt['pages_seen'],
        raw_source_rows=raw_receipt['source_rows'],
        packed_source_rows=packed_receipt['source_rows'],
        hot_originals_supplied=hot_originals,
        archived_originals_supplied=archive['checked_archived_originals'],
        archived_manifests_supplied=archive['listed_manifests'],
        original_copies_examined=joined['input_events'],
        unique_originals=joined['unique_events'],
        matching_duplicate_copies=joined['duplicate_copies'],
        raw_index_digest=raw_receipt['source_key_digest'],
        packed_index_digest=packed_receipt['source_key_digest'],
        archive_original_identity_digest=archive['cross_manifest_identity_digest'],
        supplied_source_chains_terminal=True,
        supplied_catalog_readbacks_match=True,
        # This routine has no authority to attest live source exhaustion,
        # credential independence, actual settlement, or financial outcomes.
        stable_postgres_snapshot_verified=False,
        independently_authenticated_r2_reads=False,
        all_time_sources_exhausted=False,
        all_time_coverage_complete=False,
        authoritative_settlement_verified=False,
        realized_pnl_reconciled=False,
        safe_to_train=False,
        safe_to_restart_writers=False,
        real_orders_enabled=False,
    )
