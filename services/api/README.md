# Private API foundation — development draft

This branch adds Google-only authentication primitives and a draft PostgreSQL
owner/session schema. It adds no HTTP endpoints and is not deployed. No OAuth
clients, paid resources or databases have been created.

`auth_policy.py` delegates ID-token signature validation to the official
`google-auth` library, binds audience and nonce, rejects expired/unverified
claims, and authorizes the owner by persisted Google subject rather than email.
It also provides same-origin double-submit CSRF checks and random session
material with server-side hashes. Unit tests mock the Google adapter; they do
not claim live signature verification has been tested.

The schema allows one owner and revocable expiring sessions. It has not been
applied or tested against a running PostgreSQL instance. Do not deploy this as
a complete login service.

Next implementation steps:

1. Integrate FastAPI, the official Google library, a cached public-key transport,
   request body limits and login rate limiting. Lock dependency versions and
   run API tests against those installed dependencies.
2. Add a server-issued login challenge: CSRF + single-use nonce, expiry and
   replay protection. Verify CSRF/origin before calling token verification.
3. Persist owner provisioning using the owner's explicit verified account;
   provision and bind its stable subject administratively. Never allow the
   first arbitrary visitor to become owner. The owner's email remains needed.
4. Apply the migration to isolated staging PostgreSQL; implement transactional
   session creation, lookup, expiry, revocation and logout. A token hash alone
   is not authentication without the database expiry/revocation checks.
5. Set `__Host-pocket_session` with Secure, HttpOnly, SameSite=Lax, Path=/ and no
   Domain. Keep session credentials out of browser localStorage. Require CSRF
   for authenticated mutations. Keep Google credentials out of logs/URLs.
6. Add `/auth/google`, `/auth/me`, `/auth/logout` and protect every private route.
   Keep the browser on the Cloudflare origin using the planned API proxy.
7. Add the Google sign-in button using only the configured public web client ID,
   validate staged/production origins, then test wrong-account, expired-session,
   cross-origin, replay, logout and directly accessed backend requests end to end.

Reference: https://developers.google.com/identity/gsi/web/guides/verify-google-id-token
