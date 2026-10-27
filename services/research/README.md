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
The tests use an in-memory object adapter. No R2 bucket, SDK client or credentials
are configured, and raw objects are not being uploaded anywhere yet.
