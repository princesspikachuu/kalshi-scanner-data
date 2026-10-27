"""Explicit staging diagnostics. Importing performs no I/O; never starts collection."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

import psycopg
from psycopg.rows import dict_row

from .archive import prepare
from .r2 import R2Objects
from .runtime import WorkerSettings, ConfigurationError

PROBE_PAYLOAD = {'contract': 'pocket-staging-r2-probe-v1', 'purpose': 'non-market acceptance'}
PROBE_PROVIDER = 'staging_acceptance'
MAX_PROBE_BYTES = 1024
HISTORY = ('research_artifact', 'research_dataset', 'research_summary',
           'research_dataset_artifact', 'research_result', 'research_result_dataset',
           'research_observation', 'research_campaign', 'research_campaign_work',
           'research_campaign_result', 'raw_archive', 'collection_page')


def probe_r2(objects):
    """Two conditional PUTs and two bounded GETs of ONE fixed non-market marker.

    Keeps the tiny immutable object. No DELETE, overwrite, bucket creation,
    database connection or Kalshi request. SDK retries remain bounded by R2Objects.
    """
    archive = prepare(PROBE_PROVIDER, PROBE_PAYLOAD)
    if len(archive.body) > MAX_PROBE_BYTES:
        raise ValueError('Acceptance marker exceeds its fixed limit')
    created = objects.put_if_absent(archive.key, archive.body, 'application/gzip')
    if type(created) is not bool:
        raise ValueError('Invalid object creation result')
    if objects.get(archive.key, MAX_PROBE_BYTES) != archive.body:
        raise ValueError('Acceptance readback mismatch')
    if objects.put_if_absent(archive.key, archive.body, 'application/gzip') is not False:
        raise ValueError('Conditional reuse was not enforced')
    if objects.get(archive.key, MAX_PROBE_BYTES) != archive.body:
        raise ValueError('Acceptance reuse mismatch')
    return dict(contract='staging-r2-acceptance-v1', verified=True, created=created,
                object_key=archive.key, compressed_bytes=len(archive.body), sha256=archive.sha256)


def audit_database(url):
    """Read-only metadata checks. Never reads identities, sessions, or data payloads."""
    if not isinstance(url, str) or not url.startswith(('postgres://', 'postgresql://')):
        raise ConfigurationError('Invalid DATABASE_URL')
    with psycopg.connect(url, connect_timeout=5, row_factory=dict_row,
                         options='-c default_transaction_read_only=on -c statement_timeout=5000') as c:
        applied = {r['name']: r['checksum'] for r in c.execute('SELECT name,checksum FROM public.schema_migration')}
        expected = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (Path(__file__).resolve().parents[2] / 'migrations').glob('*.sql')}
        role = c.execute('''SELECT rolsuper,rolcreaterole,rolcreatedb,rolreplication,rolbypassrls,
            current_user=session_user AS direct_login,
            EXISTS(SELECT 1 FROM pg_auth_members WHERE member=pg_roles.oid) AS has_memberships,
            has_schema_privilege(current_user,'public','CREATE') AS schema_create,
            has_database_privilege(current_user,current_database(),'TEMP') AS temporary_tables,
            EXISTS(SELECT 1 FROM pg_database WHERE datname=current_database()
                AND pg_has_role(current_user,datdba,'USAGE')) AS database_owner
            FROM pg_roles WHERE rolname=current_user''').fetchone()
        history = c.execute('''SELECT count(*)::integer AS found,
            coalesce(bool_or(pg_has_role(current_user,relowner,'USAGE')),false) AS owns_history,
            coalesce(bool_or(has_table_privilege(current_user,pg_class.oid,'UPDATE,DELETE,TRUNCATE,TRIGGER,REFERENCES')
                OR has_any_column_privilege(current_user,pg_class.oid,'UPDATE,REFERENCES')),false) AS history_mutation
            FROM pg_class JOIN pg_namespace n ON n.oid=relnamespace
            WHERE n.nspname='public' AND relname=ANY(%s) AND relkind='r' ''', (list(HISTORY),)).fetchone()
    safe = (applied == expected and history['found'] == len(HISTORY)
            and role['direct_login'] and not any(role[k] for k in role if k != 'direct_login')
            and not history['owns_history'] and not history['history_mutation'])
    return dict(contract='staging-database-audit-v1', migrations_match=applied == expected,
                migration_count=len(applied), role_flags=role, history_flags=history,
                privilege_boundary_ready=safe)


def run_check(settings, action):
    if settings.enabled:
        raise ConfigurationError('Disable collection before acceptance checks')
    if action == 'database-v1':
        return audit_database(settings.database_url)
    if action != 'r2-v1':
        raise ConfigurationError('Invalid staging acceptance action')
    objects = R2Objects.connect(account_id=settings.account_id, bucket=settings.bucket,
                                access_key_id=settings.access_key_id, secret_access_key=settings.secret_access_key)
    try:
        return probe_r2(objects)
    finally:
        objects.client.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['database', 'r2'])
    parser.add_argument('--write-r2-probe', action='store_true',
                        help='Explicitly allow the fixed tiny retained R2 marker')
    args = parser.parse_args(argv)
    if args.action == 'r2' and not args.write_r2_probe:
        parser.error('R2 acceptance requires --write-r2-probe')
    try:
        if os.environ.get('COLLECTION_ENABLED', 'false') != 'false':
            raise ConfigurationError('Disable collection before acceptance checks')
        if args.action == 'database':
            result = audit_database(os.environ.get('DATABASE_URL', ''))
            code = 0 if result['privilege_boundary_ready'] else 3
        else:
            settings = WorkerSettings.from_env()
            result = run_check(settings, 'r2-v1')
            code = 0
        print(json.dumps(result, sort_keys=True))
        return code
    except Exception:
        # Provider and PG exceptions can contain credentials. Never echo diagnostics.
        print('Staging acceptance failed; inspect private configuration and service availability', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
