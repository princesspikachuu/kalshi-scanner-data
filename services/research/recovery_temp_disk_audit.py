"""One-shot, no-write temporary-storage preflight for MT-019 backup V2.

Render exposes CPU and RAM via metrics, but not a verified ephemeral temp-disk
quota. This checks the exact Python tempfile directory that the proposed
chunked control backup would use. It does not open the DB, write a file, or
turn on a worker. Filesystem free-space measurements are advisory, not proof
of platform-specific ephemeral storage limits.
"""
import json
import os
import shutil
import tempfile

RESERVE_BYTES=256*1024*1024
MAX_STAGE_BYTES=512*1024*1024
SOURCE_JSONB_BYTES=190253997  # Nov 11 SELECT-only census, not serialized size.


def is_authorized(env, settings):
    if env.get('MT_WORKER_DISK_AUDIT_ONCE','false') != 'true':
        return False
    if not (env.get('MT_STORAGE_RECOVERY_HOLD') == 'true'
            and settings.role == 'collector'
            and settings.enabled is False
            and settings.acceptance == 'off'
            and settings.operator_action == 'off'
            and env.get('COLLECTION_ENABLED') == 'false'
            and env.get('MT_ARCHIVE_RECOVERY_LOOP','false') != 'true'
            and env.get('MT_ARCHIVE_VERIFY_ONCE','false') != 'true'
            and env.get('MT_CONTROL_BACKUP_AUDIT','false') != 'true'
            and env.get('MT_CONTROL_BACKUP_V2_ONCE','false') != 'true'):
        raise ValueError('Temporary-storage preflight requires idle recovery-held collector')
    return True


def inspect(*, tempdir=tempfile.gettempdir, disk_usage=shutil.disk_usage, statvfs=os.statvfs):
    """Check available bytes in the directory used by TemporaryFile.

    statvfs f_bavail is the unprivileged-process allowance, while disk_usage
    free may not include per-user quotas. Use the smaller available value.
    """
    directory=tempdir()
    usage=disk_usage(directory)
    mount=statvfs(directory)
    available_by_fs=int(mount.f_bavail)*int(mount.f_frsize)
    usable=max(0,min(int(usage.free),available_by_fs))
    budget=min(MAX_STAGE_BYTES,max(0,usable-RESERVE_BYTES))
    return dict(event='control_backup_temp_disk_preflight',mode='read_only',
        tmp_directory=directory,
        filesystem_total_bytes=int(usage.total),
        filesystem_free_bytes=int(usage.free),
        unprivileged_available_bytes=available_by_fs,
        conservative_available_bytes=usable,
        reserved_for_worker_bytes=RESERVE_BYTES,
        proposed_spool_cap_bytes=MAX_STAGE_BYTES,
        maximum_stage_budget_bytes=budget,
        shadow_bot_census_jsonb_bytes=187718269,
        total_control_census_jsonb_bytes=SOURCE_JSONB_BYTES,
        source_jsonb_fits_stage_budget=budget>SOURCE_JSONB_BYTES,
        sufficient_for_full_backup='unverified',
        advisory_only=True,
        no_database_access=True,
        no_write=True)


def audit_once(*, inspect_fn=inspect, emit=print):
    report=dict(event='control_backup_temp_disk_preflight',mode='read_only',
                verified=False,advisory_only=True,no_write=True)
    try:
        report.update(inspect_fn())
        report['verified']=True
    except Exception as error:
        # Don't echo paths or provider/credential-bearing exception messages.
        report['error_type']=type(error).__name__
    emit(json.dumps(report,sort_keys=True),flush=True)
    return report
