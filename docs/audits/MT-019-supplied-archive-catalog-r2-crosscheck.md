# MT-019 — Cross-check supplied archive catalog against original R2 readbacks

This offline, read-only validator closes an evidence gap **within a bounded
supplied catalog**, without claiming that the catalog is the entire history.

It requires a terminal, cursor-contiguous set of owner manifest listing pages
plus all original-event readback pages for **each listed manifest**. It calls
the existing source-keyset continuation verifier and per-manifest reclaimed
page-chain verifier, then checks:

- Each catalog row's durable manifest UUID, indexed key UUID, raw/packed kind,
  manifest digest, source-row count, and original-event count.
- Both currently generated matching row/key UUIDs and **legacy independently
  generated manifest-key UUIDs**. Never drop historic data for this reason.
- Every indexed manifest has an R2 readback, and there are no unlisted
  manifest readbacks or duplicated manifest row IDs.
- Every readback source/kind/digest/total matches its indexed manifest and has
  completed offset pagination.
- Every original event is structurally valid, has a canonical UUID and
  legitimate original key, and appears **only once across all supplied
  manifests** (including duplicated keys under different original UUIDs).

The output reports a SHA-256 continuity digest over original identities,
manifest counts, original counts, and any gaps detected through exceptions.

**Boundaries:** max 8 catalog pages, 32 manifests, 128 total R2 pages,
and 4,000 original events per invocation. Large catalogs are deliberately
handled as separately reported segments, not silently treated as globally
exhausted. No database, R2, HTTP or worker I/O occurs in this module.

A page's `verified=True` assertion must come from an authenticated R2
readback that has independently checked its object checksum, decompression,
and manifest. A pure function cannot independently validate a claimed reader
result, and a terminal cursor page is not a stable PostgreSQL snapshot.
Therefore the function **always** reports
`live_postgres_snapshot_consistent=false`,
`independent_r2_reverification_performed=false`,
`global_r2_catalog_exhaustion_verified=false`,
`source_exhaustion_verified=false`,
`all_time_coverage_complete=false`, `safe_to_train=false`,
and `safe_to_restart_writers=false`.

It does not certify settlement, realized P/L, complete hot raw/packed history,
or cross-source duplicate absence. This is not authorization to restore,
delete, archive, enable collection, or restart trading.
