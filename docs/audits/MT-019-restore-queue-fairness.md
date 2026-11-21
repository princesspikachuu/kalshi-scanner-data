# MT-019 — Prevent restore queue starvation

The v1 and v2 diagnostic restore worker previously iterated
`DemoStore.rows('restore/',5)`. That method sorts all matching rows
by randomly assigned UUID row ID and applies the limit **before**
`restore_requests_v2` filters out requests with `done=true`.
A backlog of completed restore requests could therefore hide an older
pending request indefinitely.

The new `PENDING_RESTORE_SQL` uses the indexed idempotency-key range
`demo/restore/`, filters out completed requests in **PostgreSQL**,
orders by idempotency key and limits to five pending requests before
fetching R2 receipts. No unbounded history or R2 scan occurs.

A disposable PostgreSQL regression seeds twelve completed restore requests
plus one pending restore, verifies the pending request is processed and
the complete original v1 archive progress is restored, and confirms the
completed requests are not changed.

This is a pure code/test safety improvement. It does not activate
restoration, authorize new legacy archival, delete source rows, alter R2,
or change production environments. Automatic archive and the owner
shadow restore queue remain default OFF. If a pending request is itself
invalid, it remains queued with the existing alert/fail-closed behavior;
this PR fixes the completed-requests starvation mechanism, not all
possible failed-request retries.

Do not re-enable demo maintenance, trading or archival until the broader
MT-019 recovery gates and owner dashboard history acceptance pass.
