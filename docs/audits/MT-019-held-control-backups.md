# Backup-only supervision while trading stays paused

`MT_CONTROL_BACKUP_HELD_WORKER=true` adds an explicit default-OFF route in
the existing research entry point. It starts no collector, paper executor,
acceptance action, legacy archiver, restore loop, or normal maintenance loop.
It requires the recovery hold, disabled collection, collector role, research
runtime profile, acceptance/operator actions off, and multipart backups enabled.
All archive modes and recovery one-shots must be off on this worker.

The worker uses its existing non-owner research runtime connection, never the
maintenance credential. A distinct session advisory lease serializes rolling
replacements while allowing a separate diagnostic archiver to keep its own
lease. Every minute it checks backup health; only a verified, discoverable
multipart snapshot less than 24 hours old can defer work. Invalid, future or
legacy health cannot suppress a backup. A fresh healthy snapshot is reused
across process restarts, avoiding repeated full readbacks on each deployment.

When due, it invokes the existing spooled multipart backup with the same
read-only consistent source snapshot, resource limits, full R2 readback and
independently discoverable catalog. Only backup health advances after complete
verification. No financial state, source rows, history or strategy settings are
changed. Failure releases clients and parks with a sanitized review-required
event, rather than retrying indefinitely. Explicit deploy/restart revalidates
readiness and reevaluates health; failure parking is not a durable retry latch.

Deploy code with the backup-only opt-in off. First place diagnostic archiving
on the separate existing worker and verify its exclusive lease and clean cycle.
Only then disable the original service's diagnostic-retention flags, keeping
its hold and collection off, and enable both backup-only and multipart-backup
flags. No new service, instance, plan, database object or privilege is required.
Before returning this service to paper execution, disable the backup-only flag;
the ordinary demo maintenance loop can retain multipart backups enabled and
uses the existing policy's backup interval. Preserve intentional strategy pauses.

Tests cover startup dispatch and default-off behavior, invalid roles/holds,
archive/recovery exclusion before I/O, due/fresh/future/invalid health, source
failure with no immediate retry, lease loss, redacted errors, and real
PostgreSQL lease handoff without blocking the separate diagnostic lease.
This backup scope is not a whole-database backup or financial reconciliation.
