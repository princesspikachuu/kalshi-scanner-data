# MT-019 — Logical database growth budget, not disk-free measurement

The pre-existing `services.research.storage_audit.inspect_storage` already
reads `pg_database_size`, a bounded relation summary and a sampled research
family breakdown. This change adds a **pure, no-extra-SQL classification**
when the existing `DATABASE_CAPACITY_GB` environment value is set.

- Logical bytes / configured cap threshold: warning >=70%, critical >=85%.
- Optional pure two-snapshot growth estimate (flag at >=1% of configured
  capacity/hour) takes *supplied measurements*, not another query or polling
  loop; no recurring task is enabled here.
- The result always marks physical disk usage, free filesystem bytes, WAL
  headroom and physical safety as **unknown/unverified**.
- It never authorizes DELETE, TRUNCATE, VACUUM FULL, disk purchase, restart,
  background archiving or any trading actions.
- Existing sampled job family counts remain explicitly sampled, not exact.
- Malformed capacity and measurement inputs fail closed; audit output states
  unavailability rather than fabricating a percentage.

The currently held collector can deploy this without starting collection or
additional monitoring. This is not a substitute for Render physical disk/WAL
metrics and a private, scoped archival operator role. No change to live env,
database, R2, worker cadence, user funds or historical trading data.
