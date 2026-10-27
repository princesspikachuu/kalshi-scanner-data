"""Explicit transactional migrations; never automatically run on API startup."""
import hashlib
import os
from pathlib import Path
import psycopg


def migrate(url,directory=None):
    directory=directory or Path(__file__).resolve().parents[2]/'migrations'
    with psycopg.connect(url,connect_timeout=5) as c:
        c.execute('SELECT pg_advisory_xact_lock(723741902)')
        c.execute('CREATE TABLE IF NOT EXISTS schema_migration(name text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())')
        applied=dict(c.execute('SELECT name,checksum FROM schema_migration').fetchall())
        for file in sorted(directory.glob('*.sql')):
            source=file.read_bytes();checksum=hashlib.sha256(source).hexdigest()
            if file.name in applied:
                if applied[file.name]!=checksum:raise RuntimeError('Migration checksum changed: '+file.name)
                continue
            c.execute(source.decode(),prepare=False)
            c.execute('INSERT INTO schema_migration(name,checksum) VALUES(%s,%s)',(file.name,checksum))


def verify_runtime(url,profile):
    from .db_privileges import audit_database
    receipt=audit_database(url,profile)
    if not receipt['privilege_boundary_ready']:
        raise RuntimeError('Runtime database privileges or migrations do not match')
    return receipt


def deployment_check(url,profile=None):
    # Compatibility for the existing hosted preDeploy command during cutover.
    # Once a profile is configured, this path executes read-only checks only.
    if profile is not None:return verify_runtime(url,profile)
    migrate(url)
    return dict(contract='operator-migration-v1',migrations_applied=True)


if __name__=='__main__':
    import argparse
    import json
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['migrate','verify-runtime','prepare-runtime-roles'])
    parser.add_argument('--profile',choices=['api','research'])
    args=parser.parse_args()
    try:
        if args.action=='migrate':
            receipt=deployment_check(os.environ['DATABASE_URL'],os.environ.get('RUNTIME_DB_PROFILE'))
        elif args.action=='verify-runtime':
            receipt=verify_runtime(os.environ['DATABASE_URL'],args.profile or os.environ['RUNTIME_DB_PROFILE'])
        else:
            if os.environ.get('COLLECTION_ENABLED','false')!='false':
                raise ValueError('Disable collection before operator actions')
            from .operations import prepare_runtime_roles
            receipt=prepare_runtime_roles(os.environ['DATABASE_URL'])
        print(json.dumps(receipt,sort_keys=True))
    except Exception:raise SystemExit('Database operation failed; inspect private configuration and database availability') from None
