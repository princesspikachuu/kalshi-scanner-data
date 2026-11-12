"""Bounded, same-transaction inspection of PostgreSQL history *index keys*.

Unlike separately requested windows, every keyset page in this scan shares
ONE REPEATABLE READ, READ ONLY snapshot. The selected PostgreSQL namespaces
are not proof of full historical coverage: deleted/reclaimed data can live
only in R2, and a manifest row is not a verified object.
"""
import hashlib
import re

from services.demo.shadow_snapshot_window import (
    KEY_SQL, MANIFEST_KEYS_SQL, SOURCE_PREFIXES, MAX_WINDOW_KEYS,
)
from services.demo.shadow_history_pages import validate_cursor
from services.demo.shadow_archive_reader import validate_page as validate_manifest_page

MAX_PAGES_PER_SOURCE = 8
MAX_TOTAL_KEYS = 512
CONTRACT = 'mt019-one-snapshot-index-keysets-v1'


def _valid_index_key(source, key, after, prefix):
    if (not isinstance(key, str) or not prefix < key < prefix + 'zzzz'
            or key <= after):
        raise ValueError('Invalid scanned PostgreSQL index key')
    if source == 'manifests':
        validate_manifest_page(1, key)
    else:
        validate_cursor(source, key)


def scan_postgres_index_snapshot(pool, *, page_size=16,
                                 max_pages_per_source=MAX_PAGES_PER_SOURCE,
                                 max_total_keys=MAX_TOTAL_KEYS):
    """Return a bounded same-snapshot digest if all indexed sources terminate.

    Requires a caller-supplied pool. Uses no writes, R2 calls, COUNT/OFFSET,
    worker loop or HTTP requests. Raises rather than reporting a partial scan
    as exhausted. Source selection is exactly the existing keyset SQL,
    including its succeeded-kind/format filter for archive manifests.
    """
    if (type(page_size) is not int or not 1 <= page_size <= MAX_WINDOW_KEYS
            or type(max_pages_per_source) is not int
            or not 1 <= max_pages_per_source <= MAX_PAGES_PER_SOURCE
            or type(max_total_keys) is not int
            or not 1 <= max_total_keys <= MAX_TOTAL_KEYS):
        raise ValueError('Invalid bounded PostgreSQL scan limits')

    summaries = {}
    total_keys = 0
    with pool.connection() as connection:
        with connection.transaction():
            connection.execute(
                'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            connection.execute('SET LOCAL statement_timeout=5000')
            snapshot = connection.execute(
                'SELECT txid_current_snapshot()::text AS snapshot'
            ).fetchone()['snapshot']
            if not isinstance(snapshot, str) or not snapshot:
                raise ValueError('Missing PostgreSQL transaction snapshot')

            for source, prefix in SOURCE_PREFIXES.items():
                after = prefix
                pages = count = 0
                hash_state = hashlib.sha256()
                hash_state.update((CONTRACT + '\\x00' + source + '\\x00').encode())
                query = MANIFEST_KEYS_SQL if source == 'manifests' else KEY_SQL
                while True:
                    rows = connection.execute(
                        query, (after, prefix + 'zzzz', prefix + '%',
                                page_size + 1)
                    ).fetchall()
                    if not isinstance(rows, list) or len(rows) > page_size + 1:
                        raise ValueError('Malformed bounded PostgreSQL page')
                    keys = [row.get('idempotency_key') if isinstance(row, dict)
                            else None for row in rows]
                    # Check the lookahead too; never quietly ignore a
                    # malformed boundary row or an inconsistent ordering.
                    for key in keys:
                        _valid_index_key(source, key, after, prefix)
                    if keys != sorted(keys) or len(keys) != len(set(keys)):
                        raise ValueError('Unsorted or repeated PostgreSQL index key')
                    consumed = keys[:page_size]
                    if total_keys + len(consumed) > max_total_keys:
                        raise ValueError('PostgreSQL snapshot key budget exceeded')
                    for key in consumed:
                        encoded = key.encode('utf-8')
                        hash_state.update(len(encoded).to_bytes(4, 'big'))
                        hash_state.update(encoded)
                    total_keys += len(consumed)
                    count += len(consumed)
                    pages += 1
                    if len(keys) <= page_size:
                        break
                    if pages >= max_pages_per_source or not consumed:
                        raise ValueError('PostgreSQL snapshot pagination budget exceeded')
                    after = consumed[-1]

                summaries[source] = dict(indexed_source_rows=count,
                                         keyset_pages=pages,
                                         index_key_digest=hash_state.hexdigest(),
                                         fully_scanned_in_this_snapshot=True)

    return dict(
        contract=CONTRACT,
        isolation='repeatable_read_read_only',
        transaction_snapshot=snapshot,
        source_order=list(SOURCE_PREFIXES),
        source_keysets=summaries,
        total_indexed_source_rows=total_keys,
        indexed_namespaces_fully_scanned_in_this_snapshot=True,
        # This only proves the selected SQL index keysets at one instant.
        # Manifest data, original R2 records, and business settlement still
        # require independent verification and completeness reconciliation.
        source_exhaustion_verified=False,
        archived_originals_verified=False,
        independently_verified_r2_readbacks=False,
        live_archive_manifest_catalog_exhaustive=False,
        all_time_coverage_complete=False,
        authoritative_settlement_verified=False,
        realized_pnl_reconciled=False,
        safe_to_train=False,
        safe_to_restart_writers=False,
        real_orders_enabled=False,
    )
