# MT-019 — Favorites original cohort audit forensics

The existing Favorites collector emits a FAVORITE_ENTRY_COHORT audit record
when an entry fill occurs. It includes audited price, quantity, fee, paper
order ID, plus an encoded original cohort detail dictionary.

The pure `inspect_original_cohort` function checks the original entry
information without SQL, R2 calls or any strategy mutation:

- Requires the original event kind, bounded JSON detail, expected cohort
  fields and a supported entry key namespace.
- Checks audited order ID, quantity and price against recorded cohort details.
- Verifies entry cost equals original quantity × price + original fee using
  exact decimal arithmetic.
- Rejects malformed/nonfinite/negative amounts, impossible remaining balances,
  impossible prices, missing order identity, and repeated original UUIDs within
  a bounded page.
- Preserves original event/order identities and flags whether the original
  entry was recorded as fresh.

**Critical restriction:** an entry fill alone is not evidence of an
authoritative market outcome, completed cash settlement, realized profit,
independent probability sample, or an all-time dataset. Every response marks
`authoritative_settlement_verified=false`,
`realized_pnl_reconciled=false`,
`eligible_for_learning=false`, and
`all_time_coverage_complete=false`. No Favorites strategy/analytics
dashboard input is modified by this module.

Future work must separately join authoritative order close/partial fill,
fee, verified outcome and original event ticker, then compare against current
evidence cells without counting multiple fills on one event as independent
wins. This helper is **only** an offline validation stage.

The audit's original `side`, six-field entry key, integer-cent paid price and six-decimal audit time must also agree with the recorded cohort. A 2-microsecond comparison tolerance only accounts for audit timestamp formatting and does not imply settlement-time reconciliation.
