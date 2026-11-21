# MT-019 — Terminal owner archive restore status

## Problem

After a verified v1/v2 R2-backed diagnostic restoration, the worker replaces
the archived `research_job.progress` pointer with the original event progress
and adds `restored_at`. The original owner-only
`GET /demo/shadow/archive/{uuid}` endpoint required an active
`progress.archive` pointer and thus reported 404 immediately after the
restore succeeded. The dashboard could not distinguish a completed restore
from an unknown archived record.

## Safe API-only correction

The route still queries **only** the `demo/shadow/event/` namespace using
the existing owner-authenticated, trusted-proxy boundary. An archived pointer
continues returning only format, ID, archive boolean and requested/not-
requested status. After the pointer is cleared, `completed` requires all
of the following evidence:

- The same allowed source row still exists.
- The separate durable `demo/restore/{uuid}` request has
  `source='owner_shadow_diagnostic'`, a matching original event ID, and
  `done=true`.
- The original source progress contains `restored_at`.
- The active R2 pointer is **absent**.

If any evidence is absent, the endpoint returns 404 instead of guessing.
It never returns an R2 key, receipt hash, archived payload, original research
parameters or other private progress. The restore request records the
nonsecret format before restoration so a successful v2 restore retains the
correct format label.

The separate `POST /demo/shadow/restore/{uuid}` remains gated by
`MT_SHADOW_ARCHIVE_RESTORE_REQUESTS_ENABLED=true` (default OFF), requires
owner session and CSRF, and queues only. Nothing is restored inline. No
database migration is required. The existing `demo/event/` legacy restore
route and all historical data remain untouched.

Disposable PostgreSQL route tests cover completed status after a pointer is
actually cleared, false "done" while the pointer remains, incorrect source
markers, mismatched event IDs, missing restored timestamps, cross-namespace
controls and absent proxy credentials.

The PR does not authorize enabling automatic archival, trading, collection
or database cleanup. It is an API code-only safety/readability improvement;
the manual API deploy must keep restoration opt-in OFF.
