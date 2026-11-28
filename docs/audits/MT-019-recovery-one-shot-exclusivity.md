# MT-019 — Startup exclusivity for held recovery one-shots

All MT-019 diagnostic and backup one-shots default **OFF**. The processing
collector runs with `MT_STORAGE_RECOVERY_HOLD=true`, `WORKER_ROLE=collector`
and `COLLECTION_ENABLED=false` during recovery. Every diagnostic has its
own authorization gate, but the main worker previously tested them in sequence
without rejecting a startup that enabled several at once.

This PR adds one centralized **fail-before-I/O** exclusion check in
`services.research.runtime.run` covering these flags:

- `MT_WAL_PREFLIGHT_ONCE`: aggregate PostgreSQL/WAL census
- `MT_STORAGE_RECOVERY_AUDIT`: read-only database storage inventory
- `MT_ARCHIVE_VERIFY_ONCE`: R2 diagnostic archive readback
- `MT_CONTROL_BACKUP_AUDIT`: read-only control backup census
- `MT_CONTROL_BACKUP_V2_ONCE`: R2 multipart control backup publication
- `MT_WORKER_DISK_AUDIT_ONCE`: worker-local temporary disk read-only audit

Only one may be true at startup. None may overlap
`MT_ARCHIVE_RECOVERY_LOOP=true` or recurring
`MT_CONTROL_BACKUP_V2_ENABLED=true`. The optional
`MT_BACKUP_EXACT_CENSUS=true` is allowed **only as a subordinate option** of
`MT_CONTROL_BACKUP_AUDIT=true`, and never with archive recovery.

If these constraints are violated, the worker refuses startup before invoking
any recovery R2 or PostgreSQL method. Its error message includes only fixed
safe flag-level classification, never connection strings or credentials.

This safeguard does not authorize any diagnostic. Each one's existing
recovery-held, disabled-worker-specific authorization still applies. It does
not activate archival, collection, live trading, additional database roles or
recurring backups. Every activity continues to require explicit operator
approval and reset.

As of November 11, 2026, the independent R2 diagnostic archive verification
returned one verified manifest, all 10 archived records and 7,892 compressed
bytes; `MT_ARCHIVE_VERIFY_ONCE` was immediately reset to false and a held
replacement worker deployment initiated. This check is not a complete PITR
or physical Render free-disk measurement.
