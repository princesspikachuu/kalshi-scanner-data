"""Read-only inventory of ALL archive-manifest namespace rows in one snapshot.

The existing recognized-manifest history reader intentionally filters rows by
kind, status, and format. This separate bounded audit reports rows that would
be invisible in that filtered index, so such records cannot be assumed absent
or treated as safely reclaimable. No data is moved or quarantined.
"""
import hashlib

from services.demo.shadow_archive_reader import PREFIX, summary
from services.demo.shadow_prefix_boundary_guard import assert_no_hidden_prefix_keys

MAX_PAGE_SIZE = 25
MAX_PAGES = 8
MAX_KEYS = 200
MAX_ANOMALY_EXAMPLES = 12

NAMESPACE_SQL = """SELECT id::text,idempotency_key,parameters,progress,created_at,status
    FROM research_job
    WHERE idempotency_key>%s AND idempotency_key<%s
    AND idempotency_key LIKE %s
    ORDER BY idempotency_key LIMIT %s"""


def _classification(row):
    """Classify without trusting a row's claims of archive legitimacy."""
    if row.get('status') != 'succeeded':
        return 'not_succeeded'
    params = row.get('parameters')
    if not isinstance(params, dict) or params.get('kind') not in (
            'shadow_event_r2_manifest', 'diagnostic_batch_r2_manifest'):
        return 'unrecognized_manifest_kind'
    progress = row.get('progress')
    if not isinstance(progress, dict):
        return 'invalid_manifest_body'
    expected = ('shadow-r2-event-batch-v1'
                if params['kind'] == 'shadow_event_r2_manifest'
                else 'shadow-diagnostic-r2-manifest-v1')
    if progress.get('format') != expected:
        return 'unrecognized_manifest_format'
    try:
        summary(row)  # Existing UUID/key/kind/count/format/digest validation.
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError):
        return 'invalid_manifest_metadata'
    return 'recognized'


def audit_manifest_namespace_snapshot(pool, *, page_size=16, max_pages=MAX_PAGES,
                                      max_keys=MAX_KEYS):
    """Inspect a bounded whole-prefix SQL keyset within ONE read-only snapshot.

    Every row in the index prefix is included, not only recognized archived
    manifests. A truncated/bad query raises rather than claiming termination.
    Returned examples hash keys rather than disclosing raw row bodies.
    """
    if (type(page_size) is not int or not 1 <= page_size <= MAX_PAGE_SIZE
            or type(max_pages) is not int or not 1 <= max_pages <= MAX_PAGES
            or type(max_keys) is not int or not 1 <= max_keys <= MAX_KEYS):
        raise ValueError('Invalid manifest namespace audit limits')

    classifications = {}
    anomalies = []
    seen_keys = 0
    pages_seen = 0
    after = PREFIX
    key_digest = hashlib.sha256()
    class_digest = hashlib.sha256()
    with pool.connection() as connection:
        with connection.transaction():
            connection.execute(
                'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            connection.execute('SET LOCAL statement_timeout=5000')
            snapshot = connection.execute(
                'SELECT txid_current_snapshot()::text AS snapshot'
            ).fetchone()['snapshot']
            if not isinstance(snapshot, str) or not snapshot:
                raise ValueError('Missing PostgreSQL snapshot ID')
            while True:
                rows = connection.execute(
                    NAMESPACE_SQL,
                    (after, PREFIX + 'zzzz', PREFIX + '%', page_size + 1)
                ).fetchall()
                if not isinstance(rows, list) or len(rows) > page_size + 1:
                    raise ValueError('Malformed manifest namespace SQL page')
                keys = []
                for row in rows:
                    if not isinstance(row, dict):
                        raise ValueError('Malformed manifest namespace row')
                    key = row.get('idempotency_key')
                    if (not isinstance(key, str) or not PREFIX < key < PREFIX+'zzzz'
                            or key <= after):
                        raise ValueError('Out-of-range manifest namespace key')
                    keys.append(key)
                if keys != sorted(keys) or len(set(keys)) != len(keys):
                    raise ValueError('Unsorted or duplicate manifest namespace keys')
                taken = rows[:page_size]
                if seen_keys + len(taken) > max_keys:
                    raise ValueError('Manifest namespace key budget exceeded')
                for row in taken:
                    key = row['idempotency_key']
                    encoded = key.encode('utf-8')
                    key_digest.update(len(encoded).to_bytes(4, 'big'))
                    key_digest.update(encoded)
                    classification = _classification(row)
                    classifications[classification] = (
                        classifications.get(classification, 0) + 1)
                    class_digest.update(
                        (classification + ':' + hashlib.sha256(encoded).hexdigest()
                         + '\\n').encode('utf-8'))
                    if classification != 'recognized' and len(anomalies) < MAX_ANOMALY_EXAMPLES:
                        anomalies.append({
                            'index_key_sha256': hashlib.sha256(encoded).hexdigest(),
                            'classification': classification,
                        })
                seen_keys += len(taken)
                pages_seen += 1
                if len(rows) <= page_size:
                    break
                if pages_seen >= max_pages or not taken:
                    raise ValueError('Manifest namespace page budget exceeded')
                after = keys[page_size - 1]
            assert_no_hidden_prefix_keys(connection, [PREFIX])

    recognized = classifications.get('recognized', 0)
    unrecognized = seen_keys - recognized
    return dict(
        contract='mt019-manifest-namespace-inventory-v1',
        isolation='repeatable_read_read_only',
        transaction_snapshot=snapshot,
        full_prefix_keyset_terminal_in_one_snapshot=True,
        bounded_prefix_key_boundaries_verified=True,
        namespace_rows=seen_keys,
        keyset_pages=pages_seen,
        recognized_manifest_rows=recognized,
        unrecognized_or_unsafe_rows=unrecognized,
        unrecognized_classification_counts={
            key: value for key, value in sorted(classifications.items())
            if key != 'recognized'},
        anomaly_examples=anomalies,
        full_prefix_key_digest=key_digest.hexdigest(),
        classified_key_digest=class_digest.hexdigest(),
        recognized_only_query_may_hide_rows=(unrecognized > 0),
        # This cannot certify archived history even if unrecognized == 0.
        r2_manifest_readback_verified=False,
        all_time_history_exhaustion_verified=False,
        physical_free_disk_and_wal_verified=False,
        source_exhaustion_verified=False,
        all_time_coverage_complete=False,
        safe_to_train=False,
        safe_to_restart_writers=False,
        real_orders_enabled=False,
    )
