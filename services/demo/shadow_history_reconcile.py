"""Pure, bounded reconciliation of independently verified shadow history pages.

This is intentionally NOT a production all-time history endpoint. Callers must
first independently verify R2 manifests and exhaust each source; this module
cannot manufacture a completeness guarantee or perform I/O.
"""
import json
import re
from decimal import Decimal, InvalidOperation
from uuid import UUID

MAX_INPUT_EVENTS = 256
SOURCES = frozenset(('hot_raw', 'hot_packed', 'r2_pointer',
                     'r2_reclaimed_raw', 'r2_reclaimed_packed'))
COLD_SOURCES = frozenset(('r2_pointer', 'r2_reclaimed_raw',
                          'r2_reclaimed_packed'))


class HistoryReconciliationError(ValueError):
    """Conflicting or unverified original evidence must never be counted."""


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise HistoryReconciliationError('Unserializable original event') from exc


def _validated_event(item, source):
    if not isinstance(item, dict):
        raise HistoryReconciliationError('Invalid original event')
    raw_id = item.get('id')
    try:
        ident = str(UUID(str(raw_id)))
    except (TypeError, AttributeError, ValueError) as exc:
        raise HistoryReconciliationError('Invalid original event ID') from exc
    if ident != raw_id:
        raise HistoryReconciliationError('Noncanonical original event ID')
    key = item.get('key')
    if (not isinstance(key, str) or not key.startswith('demo/shadow/event/')
            or len(key) > 180 or len(key) <= len('demo/shadow/event/')):
        raise HistoryReconciliationError('Invalid original event key')
    params, progress = item.get('parameters'), item.get('progress')
    if not isinstance(params, dict) or not isinstance(progress, dict):
        raise HistoryReconciliationError('Original parameters/progress required')
    if source.endswith('packed'):
        batch_key = item.get('packed_batch_key')
        # An R2 batch decoder need not include the source batch key, but a
        # supplied one must be in the correct namespace.
        if batch_key is not None and (
                not isinstance(batch_key, str)
                or not batch_key.startswith('demo/shadow/event-batch/')):
            raise HistoryReconciliationError('Invalid packed batch provenance')
    time_value = item.get('event_time', progress.get('time'))
    if time_value != progress.get('time'):
        raise HistoryReconciliationError('Event timestamp disagrees with progress')
    # Engine Audit.log serializes the original timestamp as a decimal
    # string. Parse only for time ordering; never rewrite the source progress.
    if time_value is None:
        event_time = None
    else:
        if isinstance(time_value, bool) or not isinstance(time_value, (int,float,str)):
            raise HistoryReconciliationError('Invalid event timestamp')
        if isinstance(time_value,str) and (
                len(time_value)>40 or
                re.fullmatch(r'[0-9]+(?:[.][0-9]+)?',time_value) is None):
            raise HistoryReconciliationError('Invalid event timestamp')
        try:
            parsed=Decimal(str(time_value))
        except (InvalidOperation,ValueError) as exc:
            raise HistoryReconciliationError('Invalid event timestamp') from exc
        if not parsed.is_finite() or not Decimal(0)<=parsed<Decimal('1e15'):
            raise HistoryReconciliationError('Invalid event timestamp')
        event_time=float(parsed)
    return dict(id=ident, key=key, parameters=params, progress=progress,
                event_time=event_time)


def reconcile_verified_pages(pages):
    """Deduplicate originals by UUID, rejecting any conflicting copies.

    Each page has source, items and verified. Cold/R2 pages must explicitly
    carry verified=True, which must be set only *after* independent gzip/SHA
    and manifest verification. A hot page cannot assert full coverage.
    This function always reports all_time_coverage_complete=False.
    """
    if not isinstance(pages, (tuple, list)) or len(pages) > 16:
        raise HistoryReconciliationError('Unbounded source pages')
    unique, keys = {}, {}
    count = 0
    for page in pages:
        if not isinstance(page, dict) or page.get('source') not in SOURCES:
            raise HistoryReconciliationError('Unknown history source')
        source = page['source']
        if source in COLD_SOURCES and page.get('verified') is not True:
            raise HistoryReconciliationError('Cold evidence not verified')
        items = page.get('items')
        if not isinstance(items, list):
            raise HistoryReconciliationError('Invalid page items')
        count += len(items)
        if count > MAX_INPUT_EVENTS:
            raise HistoryReconciliationError('History page budget exceeded')
        for raw in items:
            event = _validated_event(raw, source)
            identity = event['id']
            fingerprint = _canonical((event['key'], event['parameters'],
                                      event['progress']))
            earlier = unique.get(identity)
            if earlier is not None:
                if earlier['fingerprint'] != fingerprint:
                    raise HistoryReconciliationError('Conflicting original event ID')
                earlier['sources'].add(source)
                continue
            if event['key'] in keys and keys[event['key']] != identity:
                raise HistoryReconciliationError('Original event key reused')
            keys[event['key']] = identity
            unique[identity] = dict(event=event, fingerprint=fingerprint,
                                    sources={source})
    # Missing timestamps sort last. UUID is only a deterministic tie-breaker;
    # events with no original time must not be interpreted as sequential.
    result = sorted(unique.values(), key=lambda x: (
        x['event']['event_time'] is None,
        x['event']['event_time'] if x['event']['event_time'] is not None else 0,
        x['event']['id']))
    return dict(items=[dict(**entry['event'],
                            sources=sorted(entry['sources'])) for entry in result],
                input_events=count, unique_events=len(result),
                duplicate_copies=count-len(result),
                all_time_coverage_complete=False,
                source_exhaustion_verified=False,
                real_orders_enabled=False)
