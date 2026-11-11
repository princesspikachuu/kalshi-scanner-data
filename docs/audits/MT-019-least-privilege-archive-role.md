# MT-019: least-privilege archive role — recovery-only

The verified 4,190-record R2 financial/control backup is complete. This change
prepares **non-financial diagnostic cleanup** but **does not activate it**.
All trading/collection workers remain held.

## Why the old archive role was insufficient

The first automatic archival design required `DELETE` on all of
`public.research_job`. Although Python only selected nonfinancial diagnostics,
a compromised maintenance credential would have had broader database deletion
authority. Do not use the previous table-wide DELETE role design.

The new, independently audited `infra/archive-maintenance-role.sql` installs
one **NOLOGIN** principal and one `SECURITY DEFINER` function:

- `pocket_archive_maintenance`: NOT owner, not admin, no membership, NOLOGIN
  until activated as a separate operator step; can SELECT existing
  `research_job` records only. It has **no direct INSERT, UPDATE, DELETE,
  TRUNCATE, schema CREATE or table ownership**. The runtime guard
  also refuses role memberships, inherited-role capability, replication and
  RLS-bypass attributes, even if direct table grants appear harmless.
- `public.mt_reclaim_shadow_diagnostics(uuid,text,jsonb,jsonb)`: EXECUTE privilege
  only on the maintenance role (removed from PUBLIC). It accepts the
  already-R2-verified manifest and all original source row values, atomically
  INSERTS the manifest itself, then rechecks the ordered UUID list, immutable
  timestamps and column values, source namespace, success state, 24-hour age,
  and the allowlisted nonfinancial diagnostic kind. The manifest creation and
  precise DELETE occur **atomically**, or neither happens.
- Compressed event-batches are allowed only under the dedicated diagnostic
  `demo/shadow/event-batch/` prefix and their required format. Actual
  embedded diagnostic event IDs are validated by the Python R2 archive
  verifier *before* the database function is invoked.
- A fabricated manifest cannot authorize deletion of financial rows,
  settlements, wallets, orders, checkpoints, research datasets or other
  namespaces. The function cannot independently contact Cloudflare R2;
  **the application must verify a real R2 write + complete readback first**.
- Newly archived rows now include the `lease_token`, `available_at` and
  `max_attempts` fields so all current `research_job` columns survive
  offloading. Older already-verified R2 archives are still readable.

## Operator activation sequence (NOT performed by code merge)

1. Confirm `pocket_staging` is available, storage headroom and WAL are safe,
   the verified financial/control backup is present, **all paper writers are
   stopped**, and `MT_STORAGE_RECOVERY_HOLD=true`.
2. Using a private Render Shell **owner** session only (never ordinary worker
   env), apply `infra/archive-maintenance-role.sql`. The file is not a
   migration and never runs automatically. It creates the new role as
   **NOLOGIN** first. If the role already exists, do not overwrite or change
   its credentials blindly: inspect and reconcile manually.
3. Generate a strong independent secret locally in that Shell and activate
   `pocket_archive_maintenance` with a PostgreSQL SCRAM password. Never
   paste the owner URL, new password or role URL into this chat, GitHub,
   logs or commits.
4. Add its dedicated `RECOVERY_DATABASE_URL` privately to only the paused
   processing worker. Do **not** replace its normal `DATABASE_URL` or grant
   DELETE/UPDATE to the application login.
5. Operator verifies database role privileges: `SELECT=true`,
   `INSERT=false`, `DELETE=false`, `UPDATE=false`, `TRUNCATE=false`,
   `schema CREATE=false`, EXECUTE constrained SQL function=true, no owner/admin flags,
   no role memberships, NOINHERIT, NOREPLICATION, NOBYPASSRLS.
6. **Only after those checks**, explicitly set
   `MT_ARCHIVE_RECOVERY_LOOP=true` and
   `MT_ARCHIVE_WRITERS_STOPPED=true`, with recovery hold and disabled
   collection still true. The loop uses bounded 24h+ batches, verifies R2
   objects and durable manifest, then calls the SQL fence. It stops on any
   mismatch or error. During maintenance, check logical and physical
   PostgreSQL usage separately and monitor WAL and row/vacuum growth.
7. After backlog recovery, disable both loop flags, verify worker is back
   in held idle mode, and only then evaluate a live-safe retention schedule.

## Important limits

- Deploying this branch alone **cannot** create the role or delete data.
- This is **recovery-only** archival, not automatic maintenance while trading.
- A database owner credential previously pasted into chat needs rotation
  before returning to normal operations; do not reuse it as the maintenance
  credential.
- Cleaning rows releases PostgreSQL reusable space, not necessarily OS disk
  blocks immediately. No automatic VACUUM FULL or destructive table rewrite.
- The backup is a verified control snapshot, not complete PITR protection.
