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
