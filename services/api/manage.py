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


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['migrate','prepare-runtime-roles']);args=parser.parse_args()
    try:
        if args.action=='migrate':
            migrate(os.environ['DATABASE_URL']);print('Migrations applied')
        else:
            if os.environ.get('COLLECTION_ENABLED','false')!='false':
                raise ValueError('Disable collection before operator actions')
            from .operations import prepare_runtime_roles
            import json
            print(json.dumps(prepare_runtime_roles(os.environ['DATABASE_URL']),sort_keys=True))
    except Exception:raise SystemExit('Database operation failed; inspect private configuration and database availability') from None
