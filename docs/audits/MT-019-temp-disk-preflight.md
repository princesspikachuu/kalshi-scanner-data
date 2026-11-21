# MT-019 — Paused-worker ephemeral temp disk preflight

The proposed V2 control backup stages around 4,190 control rows as framed
chunks into an **unlinked temporary file** before R2 upload. The live census
measured ~190,253,997 bytes of PostgreSQL JSONB payload, **not** the actual
serialized bytes, and temporary disk availability is not exposed by Render's
normal CPU/memory metric APIs.

This zero-write preflight is intentionally separate from any backup.

## Activation

Only on the disabled processing collector with existing
`MT_STORAGE_RECOVERY_HOLD=true`, `WORKER_ROLE=collector`,
`COLLECTION_ENABLED=false`, acceptance and operator action off:

1. Set `MT_WORKER_DISK_AUDIT_ONCE=true` in that worker's Render environment.
   This triggers a redeploy with collection **still disabled**.
2. Inspect its single `control_backup_temp_disk_preflight` JSON log.
3. Immediately restore `MT_WORKER_DISK_AUDIT_ONCE=false`; ensure the worker
   returns LIVE in its held/disabled configuration.

The audit reads only filesystem metadata through `shutil.disk_usage` and
`os.statvfs` for the same directory `tempfile.TemporaryFile` would use.
There is no PostgreSQL connection, R2 request, file creation, deletion,
restoration or trading initiation.

Results include total/free filesystem bytes, conservative per-user available
bytes, a 256 MiB safety reserve, and maximum admissible staging bytes (capped
at 512 MiB), plus the measured source JSONB payload for comparison.

**A true result for `source_jsonb_fits_stage_budget` is only a prerequisite,
not an approval to run V2.** Python JSON serialization, filesystem overhead,
per-container ephemeral quotas and tmpfs memory limits may differ. Evaluate
Render instance memory and staging throughput, and require the full restored
R2 backup receipt before setting backup health to verified.

Neither this preflight nor archival cleanup should be scheduled automatically.
