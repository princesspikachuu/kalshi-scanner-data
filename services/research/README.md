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
