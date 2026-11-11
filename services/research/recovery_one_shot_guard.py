"""MT-019 exclusive recovery operations, validated before any recovery I/O.

The disabled collector exposes several operator-only audit and R2 one-shots.
Accidentally enabling multiple flags would execute their work sequentially at
startup, wasting resources and potentially publishing overlapping backups.
Fail closed before connecting to PostgreSQL or R2. No secrets in errors.
"""

ONE_SHOTS = (
    'MT_WAL_PREFLIGHT_ONCE',
    'MT_STORAGE_RECOVERY_AUDIT',
    'MT_ARCHIVE_VERIFY_ONCE',
    'MT_CONTROL_BACKUP_AUDIT',
    'MT_CONTROL_BACKUP_V2_ONCE',
    'MT_WORKER_DISK_AUDIT_ONCE',
)


def check_recovery_jobs_exclusive(env):
    """Reject simultaneous recovery tasks, preserving ordinary idle startup."""
    active = tuple(name for name in ONE_SHOTS if env.get(name) == 'true')
    if len(active) > 1:
        raise ValueError('Only one MT-019 recovery one-shot may run per startup')
    if active and env.get('MT_ARCHIVE_RECOVERY_LOOP') == 'true':
        raise ValueError('Recovery audit cannot run alongside archival loop')
    if active and env.get('MT_CONTROL_BACKUP_V2_ENABLED') == 'true':
        raise ValueError('Recovery audit cannot run alongside recurring backup')
    if (env.get('MT_BACKUP_EXACT_CENSUS') == 'true'
            and env.get('MT_CONTROL_BACKUP_AUDIT') != 'true'):
        raise ValueError('Exact census requires only the backup audit')
    if (env.get('MT_BACKUP_EXACT_CENSUS') == 'true'
            and env.get('MT_ARCHIVE_RECOVERY_LOOP') == 'true'):
        raise ValueError('Exact census cannot run alongside archival loop')
    return active
