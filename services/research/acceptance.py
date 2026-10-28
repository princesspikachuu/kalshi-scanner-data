"""Explicit staging diagnostics. Importing performs no I/O; never starts collection."""
import argparse
import json
import os
import sys

import psycopg

from services.api.db_privileges import audit_database, HISTORY
from .archive import prepare
from .r2 import R2Objects
from .runtime import WorkerSettings, ConfigurationError

PROBE_PAYLOAD = {'contract': 'pocket-staging-r2-probe-v1', 'purpose': 'non-market acceptance'}
PROBE_PROVIDER = 'staging_acceptance'
MAX_PROBE_BYTES = 1024


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
