# Research collection foundation — undeployed

`queue.py` uses PostgreSQL for durable work instead of a browser process or a new
message broker. It has no network client, polling daemon, API route or trade code.
The existing research dashboard/collection workflow does not use it yet.

## Worker contract

1. Create a separate bounded database pool for the research worker. A future
   owner-authenticated API can enqueue a canonical validated collection request
   with a stable idempotency key. The same key with different parameters fails.
2. `claim()` returns a job plus a fresh UUID lease token; concurrent workers use
   row locks with `SKIP LOCKED`. Default lease is 120 seconds (10–600 allowed).
   Heartbeat well before expiry, using the job ID AND that attempt's lease token.
3. Read `pages(job_id)` and reuse completed work. Request provider data outside
   database transactions. Upload to a content-addressed immutable archive object,
   verify its checksum and size, THEN call `checkpoint(...)` with the archive
   receipt and pagination state. The caller must verify upload durability; this
   queue does not prove that an object exists in R2.
4. Archive reference, completed page and page progress commit together. Repeated
   identical page writes are harmless. Conflicting evidence rolls back. A crash
   before DB commit can leave an orphan object but cannot advance the cursor.
   Future object cleanup must retain objects referenced by committed evidence.
5. `fail(...)` accepts a safe code, not exception text. Retryable failures requeue
   with a delay; exhausted attempts become terminal. Expired leases can be
   reclaimed with a new token. Old/cancelled/expired tokens cannot write progress,
   heartbeat or finish. A cancellation preserves previously committed pages.
6. `finish()` only records the worker's successful completion. It does NOT publish
   a dataset, mark any global time range complete or update `ingestion_cursor`.
   A later ingestion/publication layer must validate membership and coverage.

A lease fences database writes, not an in-flight network request. Archive uploads
must therefore be immutable/idempotent. Never attach order submission to this
research queue. Retry delays/provider budgets and bounded HTTP concurrency belong
to the provider adapter; this primitive does not claim faster provider throughput.
A provider pagination cursor is allowed in a checkpoint; credentials are not.

The pool must return dict rows (as `PostgresStore.pool` does). No transaction is
held while fetching or uploading. Progress currently counts completed pages, not
markets or percentage coverage. There is no automatic retry of terminal jobs;
submit a new request/key deliberately if the original job has failed/cancelled.

## Validation

CI provisions disposable PostgreSQL 17 and runs the queue integration tests in
`services/api/tests/test_research_queue.py` along with the existing API tests.
They check concurrent enqueue/claim, stale attempts, crash recovery, cancellation,
retry limits, durable cursors, idempotency and transaction rollback. Locally:

```sh
python -m unittest discover -s services/api/tests -v
```

Postgres cases skip unless `POCKET_TEST_DATABASE_URL` names a disposable database
whose name is exactly `pocket_test`. Never point this test suite at hosted data.

References: PostgreSQL 17 SELECT locking documentation
https://www.postgresql.org/docs/17/sql-select.html and Psycopg transactions
https://www.psycopg.org/psycopg3/docs/basic/transactions.html.

## Immutable archive codec

`archive.py` produces sorted compact UTF-8 JSON and gzip with a fixed timestamp,
then uses the SHA-256 of the compressed bytes in the object key. The same payload
and encoder version deduplicate; if a future compressor version changes bytes,
it creates a new immutable object. Original decimal price strings remain strings.
This is canonicalized parsed JSON, not an exact HTTP-wire capture. Never archive
request authorization headers or tokens as provider payloads.

`ArchiveStore` wraps an `ObjectStore` interface with conditional create, bounded
reads, and read-after-write checksum/length verification. It returns the receipt
accepted by `ResearchQueue.checkpoint` only after successful readback. Existing
corrupt evidence fails rather than being overwritten. The object-store adapter
must propagate upload/read failures and limit reads while streaming. A successful
readback is an integrity check, not a substitute for a cloud retention policy.

Decompression caps output at 32 MiB and compressed objects at 8 MiB. Invalid UTF-8,
truncated/corrupt gzip, duplicate keys, nonfinite numbers, non-string object keys
and excessive nesting are rejected. Split larger provider responses into pages.
The tests use an in-memory object adapter. The R2 SDK adapter below is available but unconfigured. No R2 bucket or credentials
are configured, and raw objects are not being uploaded anywhere yet.


## R2 S3 adapter (unconfigured)

`r2.py` implements the archive object contract with pinned boto3/botocore.
Construct `R2Objects.connect(account_id=..., bucket=..., access_key_id=...,
secret_access_key=...)` only from a future worker's secure runtime configuration,
then pass it to `ArchiveStore`. No import-time client or environment lookup occurs.
Never commit account credentials, put them in browser config or log SDK exceptions.
No worker entrypoint or hosted resource is enabled by this milestone.

Writes validate content-addressed keys and bytes, send Content-MD5 for transport
integrity and `IfNoneMatch='*'` for atomic create-only writes. Only the specific
412 PreconditionFailed response means an existing object; access failures,
conflicts, timeouts and service errors propagate. A lost upload acknowledgement
may have committed: retry the same conditional key, never overwrite or infer
success from absence. ArchiveStore still requires exact readback before receipts.

Reads validate keys and declared lengths, request at most the remaining byte
budget plus one sentinel byte, reject oversized/truncated/corrupt content and
close response streams on every path. SHA-256 in the key is the integrity proof;
ETags are not treated as checksums. SDK checksum defaults are set to when-required
for R2 compatibility; application SHA-256 and upload Content-MD5 remain in use.
No multipart upload, delete, bucket creation, ACL or presigned URL is exposed.

The client fixes the account R2 endpoint, TLS, region auto and path addressing;
connect/read timeouts are 5/10 seconds with at most 3 SDK attempts. These are socket
limits, not a total job deadline or provider-wide rate budget. The future worker
must fit archive I/O and retries inside its lease/heartbeat and job deadline.

Twelve SDK-stub tests cover create/reuse, conditional header serialization,
readback, corruption, bounded streaming and failures. They use fake credentials
and do not prove hosted R2 permissions, retention or real network behavior. Owner
setup and an explicitly authorized staging acceptance test remain pending.

Official references checked October 26, 2026:
- https://developers.cloudflare.com/r2/api/s3/extensions/ (atomic conditional PUT)
- https://developers.cloudflare.com/r2/api/s3/api/ (supported S3 headers)
- https://developers.cloudflare.com/r2/examples/aws/boto3/ (endpoint and region)
- https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_object.html
- https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/get_object.html

## Incremental inventory planning and resumable steps

`inventory.py` defines immutable request scopes and a provider-injected one-page
worker. `scopes_for_days` produces one historical market index per series and
collection generation, shared by all requested days, plus recent per-day queries.
Historical listings do not accept close-date filters. A generation is an explicit
collection identity, NOT a provider snapshot or snapshot-consistency guarantee.
Change it deliberately for refreshes; never silently reuse earlier generations.
The recent query bounds are inclusive provider bounds widened by one second;
downstream selection must enforce the exact half-open UTC close-day interval.

Plan both sources: the historical cutoff is based on settlement time, so routing
by market close date alone can omit delayed settlements. Keep settled `yes/no`
selection, cross-source ticker deduplication and candle/trade provenance in the
future normalization layer. Raw listing pages retain all rows and price strings;
no new observation or return metric is produced in this milestone.

To integrate without starting a daemon:
1. Build scopes for explicit series, UTC days and a generation. Use `scope.key`
   in the idempotency key and `scope.parameters()` as a queue job's parameters.
   Keep one historical scope shared across days. Queue asset is a routing label;
   the scope identity is the actual query identity. Retrying a terminal job needs
   a deliberate new queue idempotency key; never reset its immutable pages.
2. Reconstruct `plan(scopes, [(job, queue.pages(job['id'])), ...])` from stored jobs.
   It returns every requested scope as fetch, resume, complete, empty, unavailable
   or failed, with a job reference. No last-success-date high-water mark hides gaps.
   Complete means a succeeded job with a contiguous terminal listing traversal.
   Empty means zero rows in a successfully traversed listing, not zero trades,
   zero eligible settled markets or unavailable prices. Both are inventory-only.
3. Configure `ReadBudget` once from a deliberate conservative application policy;
   all workers sharing the provider/account must share the same database name.
   No account tier or endpoint cost is inferred. Conflicting configurations fail.
   Pass an explicit endpoint token cost to `InventoryWorker`. This budget does not
   coordinate the old live collector or other applications using that account.
4. Claim a job with `ResearchQueue.claim()`, then call `worker.step(job, deadline=...)`
   using a fixed monotonic deadline. Inject an `ArchiveStore` and a provider with
   `fetch(scope, cursor, timeout_seconds) -> ProviderPage`. That provider must do
   exactly one bounded read, no internal retries, and translate only known safe
   errors to `ProviderFailure`. `scope.request(cursor)` supplies the read-only
   relative listing path/arguments. The optional `KalshiInventory` transport below is available but not started.
5. Repeat steps returning partial; schedule throttled steps after retry_after and
   heartbeat while waiting. There is no blocking sleep or DB transaction around
   remote I/O. Requeued jobs require a fresh claim/token. The shared token bucket
   charges every fetch, includes a shared 429 cooldown and uses PostgreSQL time.
6. Each successful step verifies archive bytes before atomically committing a
   page key, input/output cursor, count, availability and archive reference. On a
   restart the next cursor comes only from committed pages. A terminal checkpoint
   followed by a crash can finish without fetching again. Cycles, missing pages
   and safety limits cannot become complete coverage. A lost lease/cancellation
   fences progress even if an in-flight archive upload finishes.

A page deadline failure after upload can leave an unreferenced immutable object;
it cannot advance a DB cursor. Unexpected I/O/integrity failures propagate and
leave the lease to expire; callers must not save/log raw exception details. Known
provider failures save only allowlisted codes and bounded delayed retries. Failed
jobs retain completed pages and remain visible in the gap plan. The worker has no
loop, schedule, hosted connection, API route, dataset publication or trading code.
A future runner must handle shutdown/heartbeats and avoid letting slow archive
I/O exceed the lease; socket timeouts are not hard end-to-end deadlines.

Tests use a fake provider and object store with the actual PostgreSQL queue/budget
in CI, exercising restart, terminal-checkpoint crashes, stale leases, cancellations,
failed uploads, deadlines, unavailable data, cycles and concurrent token spending.
This does not establish provider retention, real API throughput, point-in-time
snapshot consistency, settled quote coverage or a measurable application speedup.

Official Kalshi docs checked October 26, 2026:
- https://docs.kalshi.com/api-reference/historical/get-historical-markets
- https://docs.kalshi.com/getting_started/historical_data
- https://docs.kalshi.com/getting_started/pagination
- https://docs.kalshi.com/getting_started/rate_limits


## Public Kalshi inventory HTTP adapter (not running)

`kalshi.py` supplies `KalshiInventory`, injectable as the inventory worker provider.
Create it explicitly in a context manager and pass it to `InventoryWorker`; imports
create no client, runner, schedule or requests. No hosted collection has run.
Only the fixed HTTPS Kalshi host and GET `/markets` or `/historical/markets` paths
are exposed. Query scopes, historical index reuse, unfiltered raw inventory and
separate recent/historical evidence remain unchanged. Public market data needs no
account credentials; there are no account, portfolio or order methods.

The adapter owns its HTTPX client and builds requests without merging client
cookies. It disables environment credentials/proxies and redirects, sends no auth,
uses zero transport retries, and makes exactly one request per worker invocation.
Socket timeouts are 0..10 seconds from the worker's remaining deadline. Additional
monotonic checks surround headers, raw transport chunks and parsing. These checks
are cooperative: HTTPX timeouts bound network inactivity, not a hard total runtime
or DNS duration. A future runner still needs lease/heartbeat/shutdown handling.

Responses are capped at 8 MiB while streaming; oversized lengths are rejected
before reading, and truncated lengths fail. The client requests identity encoding
and rejects compressed bodies rather than allowing hidden decompression growth.
Wrong content types, duplicate keys, invalid UTF-8/surrogates, nonfinite numbers,
excess nesting, invalid pagination shapes and malformed market identities/close
times fail the entire page. No rows are silently dropped. Price strings and new
provider fields are retained without conversion. Market result/strategy/price
semantics remain for settled-candidate normalization; listing validity is not
quote coverage. A server that ignores identity encoding or exceeds the fixed page
size budget will fail explicitly; compatibility has not been tested live.

429s produce a safe rate-limit code. 408/500/502/503/504 and transport failures
produce retryable safe codes. Redirects, auth errors, unexpected statuses and
listing 404s are terminal invalid responses, never synthetic empty/unavailable
pages. Error bodies and Location/diagnostic text are not read, returned or saved.
Response streams close on success, errors, oversized reads and deadlines. Do not
enable raw HTTP logging: even public URLs contain opaque pagination cursors.

Retry-After supports integer seconds and HTTP dates; absent/malformed headers use
30 seconds and past/zero values use at least one second. Shared database cooldown
preserves longer server delays independently of the queue's 3600-second retry
limit, so reclaiming a job early still cannot fetch before the shared budget
allows it. `ProviderFailure.cooldown` and `ReadBudget.defer` now support positive
integer cooldowns up to 2**40 seconds (a finite database-safe ceiling); queue retry
limits remain unchanged. Service-unavailable responses also apply this shared
cooldown. Configure all workers to use the same provider/account budget name.
The old live collector and other applications are not governed by this budget.

Fourteen HTTP-stub tests and two additional actual-PostgreSQL pipeline cases cover
fixed routes/cookies, failure mapping, stream limits/cleanup, schema rejection,
long cooldowns and cursor-preserving retry/resume through the real queue. No real
Kalshi requests, credentials, R2 writes, hosted migrations or trading occurred.

Official references checked October 27, 2026:
- https://docs.kalshi.com/api-reference/market/get-markets
- https://docs.kalshi.com/api-reference/historical/get-historical-markets
- https://www.python-httpx.org/advanced/timeouts/
- https://www.python-httpx.org/quickstart/#streaming-responses
- https://www.python-httpx.org/environment_variables/

## Verified settled-candidate normalization

`normalize.py` builds a versioned `CandidateBatch` from explicitly selected queue
jobs and committed archive receipts. Call `normalize_inventory(series, utc_day,
generation, [(job, queue.page_evidence(job_id)), ...], archive_store)`. The new
queue read method joins committed page references to archive metadata; it does
not mutate a job, create coverage or prove the object still exists.

Both recent-day and historical-series inventory are required for each requested
series/generation. Missing, unfinished, failed/cancelled or unavailable inputs
produce a non-ready batch with explicit input states and **no candidate cohort**.
A succeeded job alone is insufficient: its terminal cursor chain must be complete.
A complete listing with no eligible candidates is a ready empty candidate batch,
which remains distinct from missing evidence and from a future empty quote sample.

Multiple successful complete jobs for the same scope require the caller to select
explicit membership; the normalizer never silently picks a refresh or merges
separate run versions. Failed earlier attempts cannot overwrite complete immutable
evidence. Other scopes/generations are not mixed into the requested batch.

For every selected page the normalizer reads through ArchiveStore, re-verifying
SHA-256, compressed length and bounded JSON decoding. It checks the archive's
scope and checkpoint against the committed DB page, including cursor and item
count. An object with a valid hash but the wrong envelope is still rejected.
Missing/corrupt evidence, page gaps, conflicting outcomes, mismatched market
identity/series or safety limits raise before returning any usable batch.

Candidates use the current collector's eligibility rule: result exactly yes/no
and close time in `[00:00 UTC, next 00:00 UTC)`. Offsets and fractional seconds are
handled exactly; current live collector code is untouched. There is no separate
status filter, horizon selection, stratified sampling, quote conversion, fill
simulation, loss prevention, ROI or observation metric in this layer.

Tickers deduplicate across pages and recent/historical sources. Close time, series
and event identity must agree across all scanned appearances, including those
outside the requested day; settled yes/no conflicts block the batch. A pending
appearance may later agree with a settled one, but only settled rows become
outcome evidence. Different price snapshots are retained as distinct references;
the normalizer does not select a listing quote or turn it into a maker fill.

Each candidate carries all its confirming job/scope/page/object/checksum/row-index
references. Original provider fields and decimal price strings stay in immutable
archives, without conversion. To inspect a variant, read `archive_store.read(
reference.receipt())['response']['markets'][reference.row_index]`. The candidate
and its references are frozen records; batches have a deterministic fingerprint
including normalization version, target day/generation, input membership and all
confirming references. Input order does not affect the fingerprint.

Default scan ceilings are 250,000 rows and 10,000 pages (configurable up to
1,000,000 rows / 10,000 pages). Limits count duplicate and out-of-day inventory;
they fail rather than truncate. The normalizer keeps a bounded identity map in
memory and performs no SQL publication or persistence of its derived batch.
Large historical series may require a future indexed normalization implementation.
No speedup, provider snapshot consistency or complete quote coverage is claimed.

Twelve pure normalization tests and two additional actual-PG pipeline tests cover
UTC boundaries, source deduplication, original-price provenance, incomplete source
rejection, conflicts, hash/envelope integrity, deterministic membership and limits.
No live provider/object-store traffic is required. Reviewed existing
`scripts/collect_backtest.py` and current official market schemas on October 27,
2026: https://docs.kalshi.com/api-reference/market/get-markets and
https://docs.kalshi.com/api-reference/historical/get-historical-market.

## Resumable candle/trade evidence (not running)

`evidence.py` plans raw evidence for a ready normalized candidate batch. Call
`build_scopes(batch, archive_store, lookback_seconds=..., resources=...)`. It
archives a JSON-native versioned manifest with the complete candidate membership,
input provenance and fingerprint, then returns an `EvidencePlan`. Retain its
manifest receipt even for a ready empty batch. Planning performs no provider
reads or enqueue operations. Every candidate is planned; safety limits fail
rather than silently sampling. Optional trade resources do not alter membership.

Lookback is 60..86400 seconds before close, divided into windows of at most six
hours. Unix bounds use the ceiling of close time; retain exact candidate close
time when later selecting valid entry quotes or excluding after-close trades.
One-minute candles use bounded time windows; trades use cursor pages of at most
1000 rows. Recent and historical sources are separate scopes, allowing explicit
migration/fallback evidence without inferring routing from close dates or hiding
an unavailable source. Candle and trade cutoffs can differ. All requests are
charged separately to the shared budget. There is no hidden retry/fallback call.

Enqueue each scope's `parameters()` with a stable idempotency key based on its
key. Claim normally and call `EvidenceWorker.step` with a fixed monotonic deadline,
shared read budget and explicit endpoint token cost. The worker reuses the tested
inventory lease/checkpoint engine with an evidence-specific scope loader/parser
and `evidence/` page namespace. Default inventory behavior remains unchanged.
Before fetching, it reads/verifies the manifest and checks exact candidate
membership and settled identity. This binds the normalized output; it does not
re-read every original inventory object on every evidence step. Publication must
independently validate the chosen complete input/evidence membership.

`KalshiEvidence` shares the bounded, fixed-host credential-free HTTP transport.
It exposes only recent/historical public candle and trade GET routes. Listing 404s
remain errors; evidence-route 404s are recorded as explicit unavailable pages with
only HTTP status metadata, never synthetic empty data. Other HTTP errors remain
safe retries/failures. No actual provider requests or hosted object writes have run.

Candle responses must match the requested ticker/window. Both current recent
`close_dollars` and documented historical `close` price fields retain their
original decimal strings. Numeric cents are not guessed or converted to dollars.
Null/absent quote fields remain raw incomplete quote evidence. Trades retain price
and quantity strings, taker direction and block status; identities, windows and
known price/quantity fields are checked without filtering or fabricating fills.
At-price trades and public trades are still not proof our hypothetical maker order
filled; the existing conservative execution model is unchanged.

Restart reuses committed cursors; stale/cancelled attempts cannot checkpoint.
404/unavailable, empty, partial and failed jobs remain distinct. Finishing a
candle window proves only a successful raw response, not complete minute-by-minute
quote coverage. Adjacent windows have inclusive boundary overlap. Later ingestion
must merge candle period keys/trade IDs across windows AND sources, retain every
provenance reference and reject conflicting duplicates before publication.
Trade coverage must never replace the full candle sample denominator.

Manifest references are durable in scope/job parameters but have no separate DB
artifact registry yet. No cleanup exists: future retention/GC must retain these
manifest objects and every transitive inventory/evidence reference, not just rows
in raw_archive. Large membership manifests can exceed archive size limits and
must then be explicitly partitioned, never truncated. A plan ceiling of 100,000
scopes prevents accidental unbounded job creation. No runner, UI, observations,
returns, dataset publication or precomputed summary is added in this milestone.

Nine pure HTTP/planner tests and four additional actual-PG pipeline cases cover
both resources/sources, immutable membership, one-day bounds/windowing, decimal
units, null quotes, unavailable evidence, trade restart, stale leases, shared
cooldowns, corrupted manifests and cancellation. Existing inventory tests also
exercise the shared worker/transport after extraction. Performance and real
provider compatibility remain unmeasured.

Current official schemas checked October 27, 2026:
- https://docs.kalshi.com/api-reference/market/get-market-candlesticks
- https://docs.kalshi.com/api-reference/historical/get-historical-market-candlesticks
- https://docs.kalshi.com/api-reference/market/get-trades
- https://docs.kalshi.com/api-reference/historical/get-historical-trades

## Verified immutable dataset publication and precomputed coverage

`datasets.py` implements a raw-evidence dataset boundary. `prepare_dataset(plan,
attempts, archives, inventory_loader)` re-reads the candidate manifest and every
transitive inventory page, rebuilds normalized membership and compares its exact
fingerprint. `inventory_loader(id)` returns `(queue.get(id), queue.page_evidence(id))`.
It reconstructs the canonical all-candidate evidence plan, then verifies selected
completed jobs, page chains, archive receipts and scope/checkpoint/response identity.
Missing/failed/partial scopes block publication; multiple complete jobs require
explicit membership selection. Generation/refresh versions are never mixed.

Publication policy `raw-evidence-dataset-v1` requires every planned request scope to
reach a committed terminal state. Explicit unavailable/empty scopes are retained
as coverage facts, not treated as quotes or no-fill estimates. This policy permits
a coverage dataset with missing quotes; it is NOT an eligibility gate for a full
ROI backtest. Research metrics must apply their own exact quote/path requirements
and retain the original cohort/missing-coverage denominators. No ROI, return, sell
threshold, acceptance rate or actual fill metric is produced here.

Candle period keys and trade IDs deduplicate across source/window overlaps. Known
current/historical candle OHLC aliases and decimal formatting are compared in
explicit dollar units; original representations remain in archives. Quantity aliases
normalize as counts. Compatible additional fields merge; disagreements on shared
facts block the entire dataset, including null/non-null quote disagreements.
Every confirming job/scope/page/object/row reference is retained. Raw row limits
include duplicates and fail rather than truncate. Prepared payloads are capped at
64 MiB; this is a bounded in-memory implementation, not a measured large-scale one.

`DatasetStore.publish(stream_key, prepared)` verifies prepared payload/summary/
artifact integrity, then atomically inserts the artifact registry, immutable run,
precomputed coverage summary and all transitive artifact references. Bulk registry
and membership writes avoid a SQL round trip per object. A transaction-scoped
per-stream advisory lock plus unique fingerprint makes concurrent retries
idempotent. A refresh appends a new version; retrying an older version returns its
original ID and cannot move latest backwards. No live database or runtime worker
is configured by this class. Migration 0006 is explicit, never applied on startup.

The registry includes the normalized manifest, all input inventory pages (including
empty source pages) and evidence pages. GC remains unimplemented and must also retain
unpublished active jobs' transitive references; published artifact membership alone
is not permission to delete anything else. SQL triggers reject UPDATE/DELETE on
published datasets, summaries, artifacts and membership rows. They are not protection
against a privileged operator disabling triggers or truncating tables; least-privilege
runtime roles and hosted retention policy remain staging setup work.

`history(stream_key, before=..., limit=...)` reads only immutable metadata and
precomputed `evidence-coverage-v1` summaries, using the `(stream_key,id DESC)` index
and keyset pagination. It does not load raw payloads or recalculate data. Counts
separate full candidate membership, candle records/candidate coverage, trade
records/candidate coverage and each terminal source state. No implicit cumulative
view or cross-run aggregation is performed. An authenticated API wrapper and
separate return/loss-risk summary version remain subsequent milestones.

Reviewed current main `26c65c2325d3c5f18e3c8e9ef8142fc938f8bbdf` loss_prevention,
loss_risk and table behavior before implementing this boundary. Current table
retains the full hold cohort and marks original loss rates strictly above 50% as
Trade not recommended. No live model/table files were copied, merged or changed.
The old draft base must not silently replace those later live fixes.

Eight pure ingestion and seven real-PostgreSQL publication tests cover transitive
integrity, complete membership, conflict rejection, reference retention, absent
trade evidence, immutable history, concurrent retries, atomic rollback, artifact
conflicts, stream isolation and keyset history. Read-only schema validation is
separate from provisioning; the unchanged validator downloads only the public
Render schema. A local automatic review blocked that network-check polling during
this milestone; offline code checks continued and CI results are recorded in the
checkpoint. No deployment was attempted.

PostgreSQL references checked October 27, 2026:
- https://www.postgresql.org/docs/17/explicit-locking.html
- https://www.postgresql.org/docs/17/sql-createtrigger.html
