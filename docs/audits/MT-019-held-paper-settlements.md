# Held paper payout recovery

`services.demo.held_paper_settlement` is an explicitly invoked recovery library,
with no worker-startup registration or automatic opt-in. It books confirmed
closed-market payouts while trading remains held. It has no exchange order
client, bot initialization, discovery, or simulation clock loop.

`build_plan` decodes a lossless checkpoint copy and requires exact coverage of
closed markets with remaining inventory. Each public venue record must match
its ticker, have finalized/settled status, carry a binary result, and have been
fetched within five minutes. Market and source-clock boundaries are checked.
The normal `Engine.complete_settlement` method performs Wallet settlement and
produces the normal SETTLED and final CYCLE_REPORT records. The normal event
handler calls this same method after its existing clock processing.

The held path never advances pending actions. It cancels queued/resting orders
only for the recovered closed markets, preserves unrelated orders and pending
actions, and marks affected cycles invalid because downtime must not become
strategy evidence. Deposits and recorded total fees remain unchanged. Strategy
state, pauses, calibration, summaries, RNG state and unknown checkpoint fields
are preserved. No new fills or deposits are created.

Before execution, save the complete before-image, exact plan, original fresh
outcomes and the existing financial reconciliation receipt reference with
`maintenance.put_verified` in the private archive. Preserve a separately
discoverable root/catalog reference. Never put private balances or these
references in GitHub. An archive size/capacity failure must stop before SQL.

`commit_plan` rereads the verified evidence and reconciliation checkpoint,
rebuilds the plan, requires freshness and the exact held backup-only environment,
and refuses a maintenance credential. It accepts only the existing restricted
paper runtime role on the intended staging database. It acquires the ordinary
runtime and trading-mode advisory fences without waiting, locks and compares
the original checkpoint, then commits the new checkpoint, append-only event
rows, final reports and a deterministic operation receipt in one transaction.
A conflicting final report aborts the transaction. Any failure rolls back all
financial changes. A retry recognizes a committed operation and cannot pay it
again. Read back the committed checkpoint and all expected audit/report rows
after execution; preserve the resulting receipt in the verified archive.

This operation does not release API, collection or trading holds, enable a
strategy, validate all-time cold history, or authorize a restart. Reconcile the
new settlement rows against the before-image, then refresh physical growth/WAL
acceptance and stage paper execution separately. Keep the independent archive
worker and recurring backups working throughout.

Validation covers payout arithmetic and entry fee realization, state/pauses
preservation, absence of queued fills, stale/missing/wrong outcomes, corrupted
proofs and tampered plans. Disposable PostgreSQL checks prove atomic audits and
reports, idempotence, runtime-fence exclusion, changed-checkpoint rejection and
rollback after an injected audit insertion failure. The production role check
is replaced only by an assertion that those tests use `pocket_test`.
