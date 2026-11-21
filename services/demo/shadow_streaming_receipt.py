"""No-I/O bounded rolling receipts for original event UUIDs across history.

Inputs must be globally ordered by original UUID. These receipts can detect
cross-chunk duplicates/conflicts without an unbounded identity set, but cannot
prove that an unseen UUID was not omitted by a source. No trading action.
"""
import hashlib
import re
from uuid import UUID

from services.demo.shadow_history_reconcile import (
    HistoryReconciliationError, SOURCES, COLD_SOURCES,
    _validated_event, _canonical,
)

MAX_RECEIPT_CHUNK = 256
ZERO_DIGEST = '0' * 64
SCHEMA = 'mt019-ordered-original-receipt-v1'


def _valid_hex(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _state(previous):
    if previous is None:
        return dict(last_original_id=None, last_fingerprint=None,
                    chain_digest=ZERO_DIGEST, original_events=0,
                    duplicate_source_copies=0, checked_chunks=0)
    if not isinstance(previous, dict) or previous.get('contract') != SCHEMA:
        raise HistoryReconciliationError('Unknown streaming receipt contract')
    counts = ('original_events', 'duplicate_source_copies', 'checked_chunks')
    if any(type(previous.get(k)) is not int or previous[k] < 0 for k in counts):
        raise HistoryReconciliationError('Invalid streaming receipt counts')
    last = previous.get('last_original_id')
    fingerprint = previous.get('last_fingerprint')
    if last is None:
        if previous['original_events'] != 0 or fingerprint is not None:
            raise HistoryReconciliationError('Inconsistent empty streaming receipt')
    else:
        try:
            if str(UUID(last)) != last or not _valid_hex(fingerprint):
                raise ValueError('Invalid receipt identity')
        except (ValueError, TypeError, AttributeError) as exc:
            raise HistoryReconciliationError('Invalid receipt identity') from exc
        if previous['original_events'] == 0:
            raise HistoryReconciliationError('Inconsistent streaming receipt count')
    if not _valid_hex(previous.get('chain_digest')):
        raise HistoryReconciliationError('Invalid streaming receipt digest')
    return {k: previous[k] for k in
            ('last_original_id', 'last_fingerprint', 'chain_digest',
             'original_events', 'duplicate_source_copies', 'checked_chunks')}


def extend_ordered_receipt(previous, entries):
    """Extend receipt over <=256 independently verified source items.

    Each entry is {source, verified, item}. Raw/packed hot pages need no
    verified flag; cold items must carry verified=True after independent
    R2 object readback. The input is k-way merged by original UUID (ascending).
    Duplicate copies must be consecutive; conflicts fail closed.
    """
    state = _state(previous)
    if not isinstance(entries, (list, tuple)) or not 1 <= len(entries) <= MAX_RECEIPT_CHUNK:
        raise HistoryReconciliationError('Invalid streaming receipt chunk')
    last = state['last_original_id']
    fingerprint = state['last_fingerprint']
    digest = state['chain_digest']
    unique = state['original_events']
    duplicates = state['duplicate_source_copies']
    for entry in entries:
        if not isinstance(entry, dict) or entry.get('source') not in SOURCES:
            raise HistoryReconciliationError('Invalid receipt source')
        source = entry['source']
        if source in COLD_SOURCES and entry.get('verified') is not True:
            raise HistoryReconciliationError('Unverified cold receipt item')
        item = _validated_event(entry.get('item'), source)
        identifier = item['id']
        original_payload = _canonical([item['key'], item['parameters'], item['progress']])
        current_fingerprint = hashlib.sha256(original_payload.encode('utf-8')).hexdigest()
        if last is not None and identifier < last:
            raise HistoryReconciliationError('Original UUIDs not globally ordered')
        if identifier == last:
            if fingerprint != current_fingerprint:
                raise HistoryReconciliationError('Conflicting original event across chunks')
            duplicates += 1
            continue
        digest = hashlib.sha256(
            bytes.fromhex(digest) + identifier.encode('ascii') +
            bytes.fromhex(current_fingerprint)
        ).hexdigest()
        unique += 1
        last, fingerprint = identifier, current_fingerprint
    return dict(
        contract=SCHEMA,
        last_original_id=last,
        last_fingerprint=fingerprint,
        chain_digest=digest,
        original_events=unique,
        duplicate_source_copies=duplicates,
        checked_chunks=state['checked_chunks'] + 1,
        source_exhaustion_verified=False,
        stable_database_snapshot_verified=False,
        r2_manifest_catalog_complete=False,
        all_time_coverage_complete=False,
        authoritative_financial_outcomes=0,
        safe_to_train=False,
        safe_to_restart_writers=False,
        real_orders_enabled=False,
    )
