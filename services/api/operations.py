"""Explicit operator-only staging role preparation. Never generates login credentials."""
import hashlib
from pathlib import Path
import psycopg
from .db_privileges import audit_database

ROOT = Path(__file__).resolve().parents[2]


def prepare_runtime_roles(url):
    audit = audit_database(url)
    if not audit['migrations_match'] or not audit['role_flags']['database_owner']:
        raise ValueError('Role preparation requires matching migrations and the database owner')
    source = (ROOT/'infra/runtime-roles.sql').read_text()
    before, separator, body = source.partition('\nBEGIN;\n')
    if not separator or not body.endswith('COMMIT;\n'):
        raise ValueError('Operator role transaction format changed')
    statement = before + '\n' + body.removesuffix('COMMIT;\n')
    expected = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'migrations').glob('*.sql')}
    with psycopg.connect(url,connect_timeout=5,options='-c statement_timeout=5000') as c:
        c.execute('SELECT pg_advisory_xact_lock(723741902)')
        database = c.execute('SELECT current_database()').fetchone()[0]
        if database not in ('pocket_staging','pocket_test'):
            raise ValueError('Role preparation is restricted to dedicated staging or disposable test DB')
        if dict(c.execute('SELECT name,checksum FROM public.schema_migration').fetchall()) != expected:
            raise ValueError('Migrations changed before role preparation')
        # Existing names intentionally fail and roll back; never modify a user's existing role.
        c.execute(statement,prepare=False)
        rows = c.execute("""SELECT NOT rolcanlogin AND NOT rolsuper AND NOT rolcreaterole
            AND NOT rolcreatedb AND NOT rolreplication AND NOT rolbypassrls
            AND NOT EXISTS(SELECT 1 FROM pg_auth_members WHERE member=pg_roles.oid)
            AND NOT EXISTS(SELECT 1 FROM pg_class WHERE relowner=pg_roles.oid)
            FROM pg_roles WHERE rolname IN ('pocket_api_runtime','pocket_research_runtime')""").fetchall()
        if len(rows)!=2 or not all(r[0] for r in rows):
            raise ValueError('Prepared roles failed verification')
    return dict(contract='runtime-role-preparation-v1',prepared=True,login_enabled=False,
                runtime_isolated=False,passwords_created=False)
