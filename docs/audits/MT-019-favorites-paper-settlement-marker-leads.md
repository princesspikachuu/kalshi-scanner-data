# MT-019 — Supplied paper settlement marker review leads

This no-I/O diagnostic follows the merged original-fill linkage work in PR
#216. It consumes already independently verified historical raw/packed/R2
original pages, performs UUID deduplication and verifies unique
`FAVORITE_ENTRY_COHORT` ↔ `FILL` matches. Only then does it inspect
`SETTLED` audit markers for the same market ticker.

For each ticker with linked entry records, it reports whether the supplied
pages contain zero settlement markers, multiple/ambiguous markers, or one
marker whose timestamp is not earlier than the latest linked entry. A payout
value is exposed only for the *single later paper marker* case; numeric
values must be finite and in the valid [0,1] contract payout range.
Repeated copies of the **same original UUID** from verified R2 do not
become multiple settlements; two independently keyed settlement records
are ambiguous even if their payout matches.

There is no assertion that a paper `SETTLED` marker is a venue-confirmed
market outcome. The hosted Engine records it after a virtual wallet
settlement, but it does not carry individual lot ownership, partial exits,
entry and exit fee allocation, cash reconciliation or the original venue
settlement certificate. Cross-session ticker reuse is also not proven
impossible by these pages.

**Every response keeps** `authoritative_outcome_samples=0`,
`authoritative_settlement_verified=false`,
`realized_pnl_reconciled=false`, `safe_to_train=false`, and
`all_time_coverage_complete=false`. Missing markers mean only that the
supplied page subset lacks that record, not that a trade lost or never
settled.

This PR changes no trading strategy, evidence cells, HTTP route, SQL,
database contents, R2 object, worker loop, archival scheduling, credentials,
or product/account balance. A later authoritative replay still requires
all-source exhaustion, independently verified venue payouts and fully
deterministic virtual lot/fee/cash accounting before any result is trainable.
