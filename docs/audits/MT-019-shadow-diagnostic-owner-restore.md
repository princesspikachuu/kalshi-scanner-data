# MT-019 — Owner-gated diagnostic archive status and restore requests

This is the owner-facing API companion to issue #196 and PR #197.
It does **not** enable automatic archival, unpause trading, query R2 from the
API, or restore any database rows during the HTTP request.

## Authenticated, read-only inspection

`GET /demo/shadow/archive/{uuid}` requires the existing owner's authenticated
session and trusted private proxy boundary. It is scoped to
`demo/shadow/event/` rows whose `progress.archive` is an R2 receipt.
It returns only the archive format (`legacy-v1` or
`demo-shadow-diagnostic-full-row-v2`), a yes/no archive indicator, and
restore-request status (`not_requested`, `requested`, `completed`).
No source progress, private object key, R2 hash, bucket credentials, or
R2 object payload is emitted. It reads PostgreSQL only and never writes.

## Restoration request, OFF by default

`POST /demo/shadow/restore/{uuid}` requires owner session, CSRF validation,
trusted proxy and an **additional private API opt-in**:

`MT_SHADOW_ARCHIVE_RESTORE_REQUESTS_ENABLED=true`

The default is **false**. It only queues a request for an already-archived
`demo/shadow/event/` row. The old `POST /demo/restore/{uuid}`
continues serving existing `demo/event/` v1 restores unchanged; no cross-
namespace call can expose a bot, checkpoint, order, settlement or other
control record through the new route.

A successful POST means **queued for future Demo maintenance**, not that the
data was restored. While collection/trading workers remain held for MT-019,
the queue stays pending. The maintenance worker must independently read
and verify the original R2 archive before its short PostgreSQL transaction
can restore `progress`, subject to PR #197's pointer identity checks and
full-row metadata checks for v2.

Do **not** enable this flag or the separate
`MT_LEGACY_EVENT_ARCHIVE_V2_ENABLED` automatic archival opt-in until the
owner agrees to a maintenance window, the full restore path is accepted,
and all physical storage/WAL, restricted archive account, credential rotation,
and writer-quiescence gates have been independently satisfied.

These routes are an authenticated owner API and not a newly built dashboard
button. Further dashboard integration and archive-history analytics
acceptance remain open items under issue #196.
