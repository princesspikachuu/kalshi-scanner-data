# Read-only paper cash reconciliation

`services.demo.shadow_cash_reconciliation.reconcile_wallet` is a pure replay
library. It performs no database, archive, exchange, or wallet writes and is not
connected to the runtime startup path. A successful result never authorizes a
restart or financial repair.

Supply an independently established initial funding amount, a saved wallet,
and complete original financial event rows for exactly one portfolio and
session. The caller must establish source completeness, session boundaries,
portfolio membership, and any cold-history coverage before invoking replay.
Resolve archive pointers to verified originals first. Preserve original UUIDs,
keys, timestamps, status, asset, and progress. Reject missing or duplicate rows.

The checker replays buys, sells, fees, opposite-side collateral releases,
refills, and settlements without using the live Wallet implementation. It
checks each recorded cash link, then compares cash, deposits, and aggregate
remaining quantities by market and side with the saved wallet. Supply Decimal
or serialized decimal evidence to avoid losing precision before replay.

PostgreSQL transaction timestamps can be shared by several events. Random
UUIDs cannot establish their order. A bounded search finds a covered-inventory,
cash-consistent ordering within each timestamp group; capacity exhaustion or
an unresolved path raises `CashReconciliationError`. This does not establish
individual lot cost or target attribution.

Independently compare recorded fill fee totals with active plus retired report
totals. Independently verify recorded settlement prices and pending outcomes
against authoritative venue records. This library replays recorded fees and
settlement prices; it does not certify the historical fee schedule or outcomes.

For operational evidence, capture originals and the checkpoint in one read-only
repeatable-read snapshot, release the transaction before remote I/O, and preserve
private originals plus receipts in the existing verified archive destination.
Record the capture digest and source bounds, not private wallet data in source
control. Recheck checkpoint identity before acting on a pending settlement plan.
Process confirmed payouts through an audited settlement path; never fix an
apparent mismatch by resetting cash, deleting history, or editing balances.

Validation: `python -m unittest services.api.tests.test_shadow_cash_reconciliation`.
Fixtures exercise partial exits, fees, collateral netting, transaction ordering,
zero-payout settlements, malformed and duplicate evidence, missing events,
coverage violations, endpoint mismatches, and bounded-search failure.
