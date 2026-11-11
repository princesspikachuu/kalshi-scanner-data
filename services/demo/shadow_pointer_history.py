"""Bounded, owner-only rehydration of v2 diagnostic pointers for shadow history.

An archived progress pointer is NOT an event. Never return it as if it were
the original decision, or silently discard archived Favorites evidence.
This reader uses separately configured R2 *read-only* credentials, verifies
each gzip/SHA receipt and full-row diagnostic provenance, and never writes.
"""
import re

from services.demo.legacy_event_archive import FORMAT, verified_records
from services.demo.maintenance import read_verified
from services.demo.shadow_archive_reader import ArchiveReaderUnavailable, read_store
from services.demo.shadow_archive_recovery import PREFIX

MAX_COLD_OBJECTS_PER_PAGE = 8
MAX_COLD_ROWS_PER_PAGE = 100
MAX_COMPRESSED = 4 * 1024 * 1024
_KEY = re.compile(r'^demo/events/([0-9a-f]{64})\.json\.gz$')


def _reference(progress):
    if (not isinstance(progress, dict)
            or progress.get('archived') is not True
            or progress.get('archive_format') != FORMAT
            or not isinstance(progress.get('archive'), dict)):
        raise ValueError('Unsupported or incomplete archived diagnostic pointer')
    receipt = progress['archive']
    key = receipt.get('key')
    sha = receipt.get('sha256')
    size = receipt.get('size')
    match = _KEY.fullmatch(key) if isinstance(key, str) else None
    if (not match or not isinstance(sha, str) or sha != match.group(1)
            or type(size) is not int or not 1 <= size <= MAX_COMPRESSED):
        raise ValueError('Invalid diagnostic receipt identity')
    return key, sha, size


def rehydrate_event_rows(rows, *, env=None, store_factory=read_store):
    """Replace only v2 pointer progress in memory; never modify source rows.

    Fail closed when the selected page has any inaccessible/inconsistent cold
    event. The dashboard must not display an incomplete set as full history.
    When all selected events are hot, this performs zero R2/network work.
    """
    if len(rows) > MAX_COLD_ROWS_PER_PAGE:
        raise ValueError('Archive event page too large')
    cold = {}
    for row in rows:
        progress = row.get('progress')
        if isinstance(progress, dict) and ('archive' in progress
                                          or progress.get('archived') is True):
            identity = _reference(progress)
            cold.setdefault(identity, []).append(row)
    if not cold:
        return rows, 0, 0
    if len(cold) > MAX_COLD_OBJECTS_PER_PAGE:
        raise ValueError('Archive page exceeds bounded R2 read budget')
    if env is None:
        import os
        env = os.environ
    if env.get('MT_ARCHIVE_V2_POINTER_READ_ENABLED', 'false') != 'true':
        raise ArchiveReaderUnavailable('V2 diagnostic pointer reader disabled')
    objects = None
    replacements = {}
    try:
        objects = store_factory(env)
        for (key, sha, size), group in cold.items():
            payload = read_verified(objects, dict(key=key, sha256=sha, size=size))
            originals, full = verified_records(payload)
            if not full:
                raise ValueError('Lossless v2 diagnostic archive required')
            by_id = {original['id']: original for original in originals}
            if len(by_id) != len(originals):
                raise ValueError('Duplicate R2 archival identity')
            for row in group:
                ident = row.get('id')
                original = by_id.get(ident)
                if (original is None
                        or original['idempotency_key'] != row.get('idempotency_key')
                        or original['parameters'] != row.get('parameters')
                        or original['created_at'] != row['created_at'].isoformat()):
                    raise ValueError('Archived diagnostic diverged from source row')
                replacements[ident] = original['progress']
        restored = [
            dict(row, progress=replacements[row['id']]) if row.get('id') in replacements
            else row for row in rows
        ]
        return restored, len(replacements), len(cold)
    finally:
        if objects is not None:
            objects.client.close()
