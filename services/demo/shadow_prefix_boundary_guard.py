"""Fail-closed upper/lower index key boundary guard for MT-019 audits.

A bounded query using "idempotency_key < prefix + 'zzzz'" omits malformed or
legacy keys with suffixes equal to or greater than 'zzzz', as well as the
bare prefix. Such hidden keys must not allow a diagnostic to report full
indexed namespace coverage. Execute these probes inside the *same* existing
read-only PostgreSQL snapshot, after the normal bounded keyset walk.

No original event payloads or ID values are returned; there are precisely
two indexed existence probes per explicitly allowlisted namespace.
"""
from services.demo.shadow_history_pages import RAW_PREFIX, PACKED_PREFIX
from services.demo.shadow_archive_reader import PREFIX as MANIFEST_PREFIX

ALLOWED_PREFIXES = frozenset((RAW_PREFIX, PACKED_PREFIX, MANIFEST_PREFIX))

EXACT_PREFIX_SQL = """SELECT 1 AS present FROM research_job
    WHERE idempotency_key=%s LIMIT 1"""
ABOVE_UPPER_SQL = """SELECT 1 AS present FROM research_job
    WHERE idempotency_key>=%s AND idempotency_key LIKE %s LIMIT 1"""


def assert_no_hidden_prefix_keys(connection, prefixes):
    """Raise if a key could be omitted by the bounded namespace predicates.

    Requires a connection already inside the caller's REPEATABLE READ READ ONLY
    transaction; this function never opens a transaction, changes session
    permissions, or connects to the database.
    """
    if (not isinstance(prefixes, (list, tuple))
            or not prefixes or len(prefixes) > len(ALLOWED_PREFIXES)
            or any(prefix not in ALLOWED_PREFIXES for prefix in prefixes)
            or len(set(prefixes)) != len(prefixes)):
        raise ValueError('Invalid bounded index prefix set')
    for prefix in prefixes:
        if connection.execute(EXACT_PREFIX_SQL, (prefix,)).fetchone() is not None:
            raise ValueError('Bare index prefix row would be hidden')
        if connection.execute(
                ABOVE_UPPER_SQL, (prefix + 'zzzz', prefix + '%')
        ).fetchone() is not None:
            raise ValueError('Out-of-range index key would be hidden')
    return True
