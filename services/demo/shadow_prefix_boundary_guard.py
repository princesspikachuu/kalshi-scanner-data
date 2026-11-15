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
BOUNDED_ABOVE_UPPER_SQL = """SELECT 1 AS present FROM research_job
    WHERE idempotency_key>=%s AND idempotency_key<%s
      AND idempotency_key LIKE %s LIMIT 1"""
KEY_COLLATION_SQL = """SELECT
    CASE WHEN co.collprovider='d' THEN db.datcollate ELSE co.collcollate END AS locale,
    CASE WHEN co.collprovider='d' THEN db.datlocprovider ELSE co.collprovider END AS provider
    FROM pg_attribute AS a JOIN pg_collation AS co ON co.oid=a.attcollation
    JOIN pg_database AS db ON db.datname=current_database()
    WHERE a.attrelid='public.research_job'::regclass
      AND a.attname='idempotency_key' AND NOT a.attisdropped"""


def _bounded_collation(connection):
    # A slash-to-'0' byte successor is NOT safe in en_US: punctuation has
    # secondary weight. Restrict this optimization to known libc/builtin
    # collations, then increment the last ASCII LETTER of these fixed prefixes.
    # ICU and arbitrary language contractions require a separately proved plan.
    row = connection.execute(KEY_COLLATION_SQL).fetchone()
    byte_locales = {'C', 'POSIX', 'C.UTF-8', 'C.UTF8', 'C.utf8'}
    english_locales = {'en_US.UTF8', 'en_US.UTF-8', 'en_US.utf8'}
    if (not row or not (
            (row['provider'] in ('b', 'c') and row['locale'] in byte_locales)
            or (row['provider'] == 'c' and row['locale'] in english_locales))):
        raise ValueError('Unverified collation for bounded namespace boundary probe')


def assert_no_hidden_prefix_keys(connection, prefixes, *, bounded=False):
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
    if bounded:
        _bounded_collation(connection)
    for prefix in prefixes:
        if connection.execute(EXACT_PREFIX_SQL, (prefix,)).fetchone() is not None:
            raise ValueError('Bare index prefix row would be hidden')
        if bounded:
            # All allowlisted prefixes end in an ASCII letter followed by '/'.
            # This enclosing word range excludes later unrelated namespaces
            # while retaining every suffix, including >= 'zzzz' and Unicode.
            upper = prefix[:-2] + chr(ord(prefix[-2]) + 1)
            query = BOUNDED_ABOVE_UPPER_SQL
            args = (prefix + 'zzzz', upper, prefix + '%')
        else:
            query, args = ABOVE_UPPER_SQL, (prefix + 'zzzz', prefix + '%')
        if connection.execute(query, args).fetchone() is not None:
            raise ValueError('Out-of-range index key would be hidden')
    return True
