# MT-019 — Bounded Favorites original FILL↔cohort linkage

This is the next offline evidence-recovery stage after PRs #206 and #209.
A Favorites `FAVORITE_ENTRY_COHORT` audit is emitted during a genuine
paper entry fill, and the paper execution engine also records the original
`FILL` event.

The pure `inspect_supplied_favorite_fill_links` function takes only
**independently verified** original history pages (hot or checksum-verified
R2) and reconciles duplicate original UUIDs before joining. An exact
one-to-one *supplied-record* link requires:

- The original paper order ID, market ticker, side, and buy action.
- Exact decimal quantity, executed price, and entry fee.
- Audit timestamps agreeing within 2 microseconds, accounting for six-digit
  audit formatting; the original cohort itself is independently validated by
  the existing strict cohort forensic parser.
- No second matching original FILL **or** second matching original cohort.
  Ambiguous repeated fills or shared order IDs do not become two wins.

A partial paper fill may share an order ID with later fills, so the ID
alone is not sufficient. Missing source records are counted as
`unmatched_cohorts_in_supplied_pages`, not as trades that never happened.
Two identical plausible originals are reported as ambiguous and are not
linked automatically.

Returned matched record IDs and original price/quantity/fee are **diagnostic
provenance only**. Even successful 1:1 audit linkage is not evidence of
validated market settlement, a reconciled withdrawal/cash ledger,
realized P/L, an independent event outcome sample, source exhaustion or
all-time statistical training readiness. The result always sets:

`authoritative_settlement_verified=false`,
`realized_pnl_reconciled=false`,
`authoritative_outcome_samples=0`,
`all_time_coverage_complete=false`, and `safe_to_train=false`.

There is no SQL, R2, worker, API route, trading mutation, archive deletion,
strategy update or production deployment in this PR. The bounded page
budget stays at 256 original copies. The next stage will need original
partial exits, actual portfolio inventory accounting, venue-confirmed
settlement, fees, stable history-source exhaustion, and independent
consistency checks against the existing evidence cells before any
historical figures become authoritative or trainable.
