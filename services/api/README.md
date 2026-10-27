# Pocket Analytics API — development draft

This branch prepares the future API and infrastructure. It is not deployed or
linked to a Render Blueprint. The existing research app is unaffected.

## Implemented

- FastAPI health, Google challenge/sign-in, current-user and logout routes.
- Official Google signature verification, cached public keys with a bounded
  transport timeout, audience/issuer/expiry checks and a single-use nonce.
- Explicit owner bootstrap and permanent binding to Google's stable subject.
  Email bootstrap requires a Google-authoritative Gmail or Workspace identity;
  other Google accounts need a preverified configured subject.
- PostgreSQL sessions, revocation, expiry, CSRF hashes, one-use login challenges
  and shared login/challenge rate budgets.
- Secure `__Host-` cookies, same-origin mutation checks, request-size limits and
  a server-only proxy secret. Sensitive input and connection strings are omitted
  from API errors. Credentials are never returned as URL parameters.
- Transactional, checksum-checked migrations with an advisory lock. The API
  does not apply migrations automatically at startup.
- Initial tables for future durable research jobs, archive references and
  completed ingestion cursors. Collection workers and archive uploads remain
  to be implemented; the new API exposes no research or trading actions.

## Local validation

```bash
python -m venv .venv
.venv/bin/pip install -r services/api/requirements-dev.txt
.venv/bin/python -m unittest discover -s services/api/tests -v
.venv/bin/python infra/validate_blueprint.py
```

Without `POCKET_TEST_DATABASE_URL`, PostgreSQL integration tests are explicitly
skipped. The draft PR workflow starts a disposable PostgreSQL 17 container and
runs them there. It creates no hosted API or Render database. Integration tests
refuse to operate unless the database is named `pocket_test`.

The Google SDK tests use a locally generated test signing key and certificate.
They exercise the installed verifier's signature, audience and expiry checks
without a live Google account. Live OAuth and browser login still need staging
configuration and an end-to-end acceptance test.

After an isolated local or staging database is configured, apply migrations
explicitly with `python -m services.api.manage migrate` using `DATABASE_URL`.
Start the API with `uvicorn services.api.app:create_app --factory`. See
[the infrastructure runbook](../../infra/SETUP.md) for configuration and boundaries.

## Browser/proxy contract

The browser remains on the Cloudflare app origin. The undeployed `apps/gateway` Worker proxy forwards
`/api/auth/*` to this API's `/auth/*`, passing cookies, Origin, Content-Type,
`X-CSRF-Token` and Sec-Fetch-Site while replacing `X-Pocket-Proxy` with the
server-stored `API_PROXY_SECRET`. Never send this secret to the browser. Preserve
Set-Cookie headers separately; do not combine them or add a cookie Domain.

1. `GET /auth/challenge` returns public client ID, nonce and CSRF token, and
   sets two Secure/HttpOnly login cookies. Keep the returned nonce/CSRF in memory.
2. Initialize Google Identity Services with that client ID and nonce. Send its
   credential and the challenge nonce/CSRF as JSON to `POST /auth/google`.
3. The API consumes the challenge once, verifies Google, authorizes/provisions
   the explicitly configured owner, revokes the previous session, and sets a
   Secure/HttpOnly session cookie plus a readable Secure CSRF cookie.
4. `GET /auth/me` checks database expiry and revocation on every request.
5. `POST /auth/logout` requires the session, original app Origin and
   `X-CSRF-Token` matching the CSRF cookie and stored session hash.

Future private routes must use the same authenticated-session dependency and
mutation CSRF checks. Proxy origin and secret checks alone are not user login.
The normal flow uses Google identity only; it requests no Gmail or Drive access.

Official identity reference:
https://developers.google.com/identity/gsi/web/guides/verify-google-id-token

The matching sign-in preview and connection tests are documented in `apps/README.md`.

### Undeployed research history contract

Authenticated GET routes (through the staging gateway's `/api` prefix):

- `/research/datasets?stream=btc-raw`: published raw dataset **coverage** versions.
- `/research/results?stream=btc-results`: compact saved report versions/counts.
- `/research/results/123?stream=btc-results&view=historical` (or `latest`): exact
  saved table cells, baseline/exit stress and pinned model/source version.
- `/research/results/123/datasets?stream=btc-results`: exact dataset membership,
  immutable hashes, UTC close dates and `is_latest` flags for that saved result.

All require the existing proxy secret AND current owner session. GET needs no
CSRF token; logout and login protections are unchanged. No research writes are
exposed. Unknown result/wrong stream is 404; an empty published cohort is 200.
`historical` means the complete explicitly selected cumulative cohort, not a
server-generated date filter. `latest` must be selected explicitly; inspect
`latest_membership_known` because an unknown latest cohort is not an empty run.

Pages have `{contract:"research-history-v1",items:[...],next_cursor:null|"..."}`;
pass `next_cursor` as `cursor` until null. Default limit 25, maximum 50. Cursors
are authenticated with a domain-separated use of the existing server-only proxy
key, bound to stream/collection/result and invalid after key rotation. Page size
may change. IDs are decimal **strings** (Postgres bigint exceeds browser integer
precision). Metadata exposes dates/counts/hashes, never raw archives/observations.
Membership pages let clients verify every date/version rather than infer exact
membership from a first/last date range. Do not apply a saved cell's adjustment
to another report, dataset set or baseline.

Streams use `[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}`. Duplicate/unknown query parameters,
malformed/out-of-range IDs, altered/cross-query cursors and unsupported views fail
closed. Response models forbid extra fields/nonfinite metrics and check original
cohort counts, table dimensions, strict >50% labels and original observations.
Unsupported/corrupt saved versions yield a generic 503, never a partial table.
The gateway bounds body reads to 256 KiB and validates response envelopes; the
API validates nested fields. All responses are `no-store`; gateway research
responses cannot set login cookies. These routes remain separate from live UI.

`services/research/history.py` uses indexed stream/id keysets and the membership
primary key. SQL projects only precomputed coverage/counts/cells from immutable
rows; no collector, archive reader, observation scan or policy builder runs in a
GET. Table cells have a 128 KiB SQL projection guard and at most 45 validated
cells. Lists request one extra metadata row to detect another page. Keysets avoid
offset drift, but independent requests are not a database snapshot: concurrently
committing older allocated IDs can appear only on a later fresh traversal. No
representative throughput/latency benchmark or hosted compatibility claim yet.
Unfinished queue jobs, detailed path evidence and arbitrary date recomputation
are intentionally outside this publication-history read contract.
