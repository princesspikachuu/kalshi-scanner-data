# Undeployed app connection preview

`gateway/index.mjs` is the future staging Cloudflare Worker. It is separate from
`worker/src/index.js`, which serves the live research app. Neither that Worker
nor the existing production Wrangler configuration is changed by this draft.

`web/` is a small Google-only sign-in test page and reusable auth client. It is
not the full React research interface. Its purpose is to verify the browser →
Cloudflare → API → PostgreSQL connection before migrating the research app.

## Connection behavior

- Only the four explicit `/api/auth/*` routes are proxied, with fixed methods.
- The API origin is server configuration, never a caller-supplied destination.
- A server-only proxy secret replaces any incoming header with the same name.
- Only the four Pocket login/session cookies are forwarded to the API.
- Multiple Set-Cookie headers are preserved separately, including Expires dates.
- Cross-origin writes, query credentials, oversized bodies, unsafe cookie
  attributes, redirects and malformed provider responses are rejected.
- Errors are sanitized; backend diagnostics and unrelated response fields do
  not reach the browser. Proxy calls have a bounded timeout.
- The browser uses same-origin cookie credentials. ID tokens and challenge
  state stay in memory, not URLs, localStorage or sessionStorage.
- Google's current client library is loaded from its official URL only after a
  challenge is available. One Tap/automatic sign-in is not enabled.
- The sign-in page renders a single Google button and authenticated account/
  sign-out state. Expired or consumed challenges require a fresh page/challenge.
- The page is protected by CSP and popup-compatible opener policy; session
  authorization remains the API's responsibility, not the page's display state.

## Configuration — prepare, do not deploy yet

`infra/wrangler.staging.json` gives this Worker a separate staging name and
assets directory. Public workers.dev and preview URLs are disabled. It has no
routes and is not referenced by a deployment workflow.

Before any staging deployment is authorized, agree on the staging hostname and
set these server-side values through supported Cloudflare settings/secrets:

| Name | Meaning |
| --- | --- |
| APP_ORIGIN | Exact HTTPS staging browser origin, also configured in the API and Google Web client |
| API_ORIGIN | Exact HTTPS origin of the staging API, with no path/query or credentials |
| API_PROXY_SECRET | Same randomly generated secret stored on the API; never a frontend variable |

The Google web client ID is returned by the API's challenge response. No Google
client secret is needed in the browser. Keep the owner account configured only
on the API. No credentials or live configuration values are checked into source.

## Validation

Run `node --test tests/test_login_bridge.mjs`. The draft PR CI runs this alongside
API and actual PostgreSQL tests. The Node tests exercise proxy boundaries,
cookies, request limits, redirects, timeout handling and client session behavior.

A real browser sign-in still requires the owner's Google OAuth client and an
authorized staging hostname/API. Node tests are not a substitute for a live
Google popup/FedCM and deployed Cloudflare acceptance check. Nothing in this
folder has been deployed or used to create hosted resources.

Official implementation references:

- https://developers.cloudflare.com/workers/runtime-apis/headers/
- https://developers.cloudflare.com/workers/runtime-apis/request/
- https://developers.cloudflare.com/workers/wrangler/configuration/
- https://developers.google.com/identity/gsi/web/reference/js-reference
- https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid

The staging gateway also allowlists the four authenticated read-only research
history routes documented in `services/api/README.md`. Only those GET paths and
bounded unique query parameters are forwarded; arbitrary provider/trading paths
remain unavailable. Saved results require an explicit historical/latest view.
Nested response validation remains in the API. Research responses are bounded,
`no-store` and cannot set auth cookies. No research shell or deployment is included.

`/collection.html` is a separate undeployed collection controller. It includes UTC
inclusive date controls, section progress/pause/resume, saved recheck option and
opt-in hourly last-24-hours settings. Only selection, campaign IDs and an ambiguous
request's retry key are stored locally; session/CSRF credentials remain in their
existing cookies. Progress polling does NOT drive collection; the injected server
runner owns all work. The account smoke page links to the controller. The live
research Worker/table remains unchanged. Backend/worker resource setup is pending.
