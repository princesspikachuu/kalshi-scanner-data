# MT-019 — Lossless hot-event compaction and storage-budget roadmap

## What this branch changes

The paper engine previously inserted one `research_job` row (with primary-key/unique-index overhead) for **every** shadow event, even when multiple purely diagnostic decisions arrived in one atomic audit commit.

`diagnostic_batches.py` now packs *consecutive* named non-financial diagnostic events in groups of up to 64 into deterministic gzip+base64 JSONB, with a SHA-256 digest of the decoded payload. Original UUIDs, idempotency keys, parameters, detailed progress and timestamps are preserved inside each pack.

Only these named event kinds are eligible:

- `FAVORITE_STAT_DECISION`
- `FAVORITE_ENTRY_DECISION`
- `FAVORITE_REPEAT_OPPORTUNITY`
- `FAVORITE_ENTRY_COHORT`
- `FAVORITE_TRIAL_QUALITY`
- `SCALPER_OBSERVATION_BATCH`

**Never compact into a shared row:** fills, orders, cancellations, settlements, fees, funding, account snapshots, monetary reports, CYCLE_REPORT, safety controls, worker checkpoints or decision types not explicitly allowlisted.

If just one diagnostic event is present, or the bounded compressed payload cannot be represented, preserve its original independent row. No event is sampled or discarded. All rows (packed and raw) continue to commit atomically with the checkpoint.

The authenticated `/demo/shadow/events` endpoint merges the latest 100 raw rows and latest 100 packed rows, checks the checksum and reconstructs original recent events before returning the same 100-item activity view. The original events remain unchanged in the `written_events` audit/telemetry stream.

New counters in `shadow_durability_cost`:
- `diagnostic_batch_rows`
- `diagnostic_events_packed`
- `diagnostic_rows_avoided`

Use these counters, plus Render `research_job` and DB physical-size measurements, to establish actual improvement. **Do not assert projected savings are realized while Render is suspended.**

## Why this is only one part of the answer

Packing recent diagnostics reduces index/row overhead without reducing monitoring or learning. It does not, by itself, migrate older history to Cloudflare R2 or reclaim the existing 10 GB database.

Existing R2 operator recovery is proposed separately in PR #174 and currently covers individual old `demo/shadow/event/` rows, not future `demo/shadow/event-batch/` rows. Before deployment as a permanent storage solution, implement a verified R2 offload and restoration path for both formats plus bounded, explicitly privileged purge/retention. Confirm all recorded original identities still resolve after cold archive.

## Recovery/rollout gates

1. Render 10 GB database is suspended; do not buy more disk or enable automatic capacity growth.
2. PR CI must pass, including financial-event and payload-integrity tests.
3. R2 archival and restoration must support both raw and compressed diagnostic event history before periodic aged-row removal is activated.
4. During controlled database recovery (no new writers), establish full pre/post physical disk measurements, existing backup verification and bounded archive/reclaim tests. Normal VACUUM may only make space reusable internally; it does not necessarily reduce the Render disk allocation.
5. Only restore paper trading after confirming wallet, orders, settlements, history, activity API, and alert health; compare alike periods for actual row growth/CPU/p95 writes.

## Other redundant storage candidates awaiting measurement

- Mutable paper checkpoint rewrites: PR #171 already merged a SHA-verified redundant-write skip; verify live counters once DB resumes.
- Repeated `CYCLE_REPORT` event details plus latest per-market report row: **do not delete either yet**, because the latest report is overwritten and historical event data could be the only prior version.
- `demo/control_backup`: pre-outage backups repeatedly failed with query timeouts / capacity checks; replace heavy repeated full scans with a bounded, verified incremental or chunked R2 backup before considering any cleanup.
- `shadow_balance` and per-bot history retention jobs: logs report missing DELETE privileges; do not grant broad worker deletion rights. Plan a narrow, auditable operator role.
- `research_dataset` and immutable published artifacts: keep them; they may be canonical evidence, and deleting them would silently corrupt learning.
