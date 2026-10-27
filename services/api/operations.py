"""Explicit operator-only staging role preparation. Never generates or returns plaintext login credentials."""
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


RUNTIME_ROLES = ('pocket_api_runtime','pocket_research_runtime')


def validate_runtime_verifiers(verifiers):
    """Accept only libpq SCRAM-SHA-256/4096 verifiers for the two fixed roles."""
    import base64
    import re
    if not isinstance(verifiers,dict) or set(verifiers)!=set(RUNTIME_ROLES):
        raise ValueError('Two fixed runtime verifiers are required')
    for value in verifiers.values():
        if not isinstance(value,str) or len(value)>256:
            raise ValueError('Invalid runtime verifier')
        match=re.fullmatch(r'SCRAM-SHA-256\$4096:([A-Za-z0-9+/=]+)\$([A-Za-z0-9+/=]+):([A-Za-z0-9+/=]+)',value)
        try:
            if not match or [len(base64.b64decode(part,validate=True)) for part in match.groups()]!=[16,32,32]:
                raise ValueError()
        except Exception:raise ValueError('Invalid runtime verifier') from None
    if len(set(verifiers.values()))!=2:raise ValueError('Independent runtime verifiers are required')


def activate_runtime_roles(url,verifiers):
    """One-time atomic activation. Already-active roles fail closed, never rotate."""
    from psycopg import sql
    validate_runtime_verifiers(verifiers)
    audit=audit_database(url)
    if not audit['migrations_match'] or not audit['role_flags']['database_owner']:
        raise ValueError('Runtime activation requires matching migrations and database owner')
    expected={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'migrations').glob('*.sql')}
    with psycopg.connect(url,connect_timeout=5,options='-c statement_timeout=5000') as c:
        c.execute('SELECT pg_advisory_xact_lock(723741902)')
        if c.execute('SELECT current_database()').fetchone()[0] not in ('pocket_staging','pocket_test'):
            raise ValueError('Runtime activation is restricted to staging or disposable test DB')
        if dict(c.execute('SELECT name,checksum FROM public.schema_migration').fetchall())!=expected:
            raise ValueError('Migrations changed before runtime activation')
        rows=c.execute("""SELECT rolname FROM pg_roles WHERE rolname=ANY(%s)
            AND NOT rolcanlogin AND NOT rolsuper AND NOT rolcreaterole AND NOT rolcreatedb
            AND NOT rolreplication AND NOT rolbypassrls AND NOT rolinherit
            AND NOT EXISTS(SELECT 1 FROM pg_auth_members WHERE member=pg_roles.oid)
            AND NOT EXISTS(SELECT 1 FROM pg_class WHERE relowner=pg_roles.oid)""",(list(RUNTIME_ROLES),)).fetchall()
        if {r[0] for r in rows}!=set(RUNTIME_ROLES):
            raise ValueError('Runtime roles must be prepared, unprivileged and not active')
        for role in RUNTIME_ROLES:
            # Only libpq-produced verifiers enter SQL, never the original passwords.
            c.execute(sql.SQL('ALTER ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(role),sql.Literal(verifiers[role])))
    return dict(contract='runtime-role-activation-v1',activated=True,roles=2,
                passwords_returned=False,runtime_isolated=False)
