# MT-019 — Archive manifest index namespace and identity isolation

The owner-only archive catalog is indexed in PostgreSQL at
`demo/shadow/archive-manifest/`, with raw manifests addressed as
`archive-manifest/<uuid>` and packed manifests as
`archive-manifest/batch/<uuid>`.

Following the confirmed raw-versus-packed namespace collision under
PostgreSQL text collation, the manifest index SELECTs now require an
**explicit bound prefix match** as well as their original bounded keyset
range, status and kind filters. The exact per-ID lookup has the same
namespace restriction. There are no additional queries or R2 calls.

Each returned catalog record must also have:

- A canonical UUID matching the indexed manifest key exactly.
- A raw or packed manifest key namespace matching its durable kind.
- The matching expected manifest format.
- Valid positive archived/source-event counts.

An inconsistent, stale, or neighboring record fails closed instead of being
presented as a verified archive. This check runs before any requested R2
readback and does not change original archive content.

Tests cover both raw and packed legitimate manifests; mismatched identifiers,
opposite namespaces, malformed UUIDs, unexpected formats, and SQL parameters.
This is an owner-only, read-only metadata change. It does not verify the full
R2 catalog, prove financial settlement, enable history restoration, start
trading/collection, or authorize archival deletion.
