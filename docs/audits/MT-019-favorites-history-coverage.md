# MT-019 — Favorites historical evidence presence audit (not statistics)

The summarize_supplied_favorites_evidence() pure function inspects only a
bounded set of independently verified source pages after original-UUID
reconciliation. It counts the presence of Favorites entry cohort, trial
quality, entry/experimental decisions and SETTLED audit rows, detecting
apparent ticker links and missing ticker identifiers. It performs zero SQL
queries, R2 operations, trading actions, or background work.

Critically, a market's presence in a SETTLED log does NOT establish its
actual paper portfolio position, fill price/quantity, transaction fees,
complete realized P/L, authoritative settled payout or independent event
outcome. Matching tickers are explicitly only potential review leads.
Missing a settlement from supplied pages does not establish it never
occurred elsewhere.

All results always declare:
- authoritative_outcome_samples=0
- financial_reconciliation_complete=false
- all_time_coverage_complete=false
- source_exhaustion_verified=false
- safe_to_train=false

The existing favorite_statistics.aggregate() builds calibrated
probabilities and dollar results from favorite_timing.METRICS evidence
cells, not from these audit rows. Do not feed the presence audit into
statistics-backed Favorites decision code, overwrite evidence cells or
claim all-time learning recovered. Future work must build deterministic
authoritative replay from fill/cohort/settlement and accounting records,
verify every source/archived manifest's original IDs, reconcile against
persisted cells and prove no double-count before re-enabling training.

This PR introduces only a pure library, bounded tests and documentation.
It does not expose a new HTTP endpoint nor activate R2 reader credentials,
automatic archive, database cleanup, collection or trading.
