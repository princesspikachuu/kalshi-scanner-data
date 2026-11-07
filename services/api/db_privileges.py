"""Shared read-only runtime-role and migration audit; no auth data is read."""
import hashlib
from pathlib import Path
import psycopg
from psycopg.rows import dict_row

HISTORY = ('research_artifact', 'research_dataset', 'research_summary',
           'research_dataset_artifact', 'research_result', 'research_result_dataset',
           'research_observation', 'research_campaign', 'research_campaign_work',
           'research_campaign_result', 'raw_archive', 'collection_page')


def audit_database(url, profile='research'):
    """Read-only metadata checks. Never reads identities, sessions, or data payloads."""
    if not isinstance(url, str) or not url.startswith(('postgres://', 'postgresql://')):
        raise ValueError('Invalid DATABASE_URL')
    if profile not in ('api','research'):
        raise ValueError('Invalid database profile')
    expected_role = 'pocket_api_runtime' if profile == 'api' else 'pocket_research_runtime'
    with psycopg.connect(url, connect_timeout=5, row_factory=dict_row,
                         options='-c default_transaction_read_only=on -c statement_timeout=5000') as c:
        applied = {r['name']: r['checksum'] for r in c.execute('SELECT name,checksum FROM public.schema_migration')}
        expected = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (Path(__file__).resolve().parents[2] / 'migrations').glob('*.sql')}
        role = c.execute('''SELECT rolsuper,rolcreaterole,rolcreatedb,rolreplication,rolbypassrls,
            current_user=session_user AS direct_login,
            current_user=%s AS expected_role,
            EXISTS(SELECT 1 FROM pg_auth_members WHERE member=pg_roles.oid) AS has_memberships,
            has_schema_privilege(current_user,'public','CREATE') AS schema_create,
            has_database_privilege(current_user,current_database(),'TEMP') AS temporary_tables,
            EXISTS(SELECT 1 FROM pg_database WHERE datname=current_database()
                AND pg_has_role(current_user,datdba,'USAGE')) AS database_owner
            FROM pg_roles WHERE rolname=current_user''', (expected_role,)).fetchone()
        history = c.execute('''SELECT count(*)::integer AS found,
            coalesce(bool_or(pg_has_role(current_user,relowner,'USAGE')),false) AS owns_history,
            coalesce(bool_or(has_table_privilege(current_user,pg_class.oid,'UPDATE,DELETE,TRUNCATE,TRIGGER,REFERENCES')
                OR has_any_column_privilege(current_user,pg_class.oid,'UPDATE,REFERENCES')),false) AS history_mutation
            FROM pg_class JOIN pg_namespace n ON n.oid=relnamespace
            WHERE n.nspname='public' AND relname=ANY(%s) AND relkind='r' ''', (list(HISTORY),)).fetchone()
    safe = (applied == expected and history['found'] == len(HISTORY)
            and role['direct_login'] and role['expected_role']
            and not any(role[k] for k in role if k not in ('direct_login','expected_role'))
            and not history['owns_history'] and not history['history_mutation'])
    return dict(contract='staging-database-audit-v2', profile=profile, migrations_match=applied == expected,
                migration_count=len(applied), role_flags=role, history_flags=history,
                privilege_boundary_ready=safe)

