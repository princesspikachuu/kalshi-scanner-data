# MT-019 — Bounded partial history reconciliation preview

The pure `reconcile_supplied_history` helper connects existing safety
primitives without making PostgreSQL or Cloudflare R2 requests:

1. Verify provided raw-event, packed-batch, and manifest-catalog cursor chains
   end correctly, with no skipped/repeated supplied pages.
2. Match the supplied manifest catalog exactly against the supplied verified
   R2 manifest chains. Require stable manifest ID, indexed key, opaque digest,
   kind and original-event count.
3. Deduplicate original hot/cold event UUIDs using the shared fail-closed
   reconciliation primitive; reject conflicting copies.
4. Return original progress/parameters and counts for *this bounded preview*.

Hard limits: 16 source/event pages and eight manifests per call; the shared
identity reconciler also caps the total supplied originals at 256. Larger
histories require explicit streaming/chunked receipts without silently
truncating or making claims about unvisited pages.

Importantly, a complete *supplied* manifest catalog is not proof that the
PostgreSQL catalog itself was exhaustively enumerated at a stable snapshot,
that no unseen R2 manifests exist, or that every historical paper trading
event is included. Every result has
`database_snapshot_verified=false`,
`r2_manifest_catalog_complete=false`,
`all_time_coverage_complete=false`, and `safe_to_train=false`.

This is an offline integration/test primitive, not a live endpoint or new
worker. It does not change Favorites evidence cells, compute wins, alter
historical P/L, restart collection/trading, enable archive cleanup or use
credentials. The next source-of-truth step requires a stable cutoff/snapshot,
streaming catalog and per-original evidence acceptance without double-counting.

The shared original-ID reconciler tolerates a previously normalized numeric event_time alongside the unchanged decimal-string original progress.time, but rejects inconsistent numeric times. This permits verified R2 page adaptation to pass through a second reconciliation stage without modifying its source audit payload.
