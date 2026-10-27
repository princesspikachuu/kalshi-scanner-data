# Staging launch proposal — not applied

Prepared October 27, 2026. Owner reports creating the **pocket-r2-staging** Render
environment group with R2_ACCOUNT_ID, R2_BUCKET, R2_ACCESS_KEY_ID and
R2_SECRET_ACCESS_KEY. Secret values were not retrieved or copied into this repo.
The public Google Web client ID has been provided in the private setup conversation;
set GOOGLE_CLIENT_ID during resource creation. Owner email stays private in Render.
Render and GitHub tool access work; Render's scoped GitHub build installation still
needs confirmation if the repository does not appear in its creation flow.

## Concrete resources and estimated monthly cost

| Resource | Plan | Proposed monthly cost |
| --- | --- | ---: |
| pocket-api-staging | 0.5 CPU / 512 MB | $7 |
| pocket-research-staging | 1 CPU / 2 GB | $25 |
| pocket-db-staging | 0.5 CPU / 1 GB | $19 compute |
| Database disk | 5 GB, autoscaling off | Budget $1.50 at $0.30/GB |
| **Render planning subtotal** | One instance each, Oregon | **About $52.50/month** |

Verify the final Render review estimate before creation, including any included
storage, workspace subscription, taxes, bandwidth and build-minute overages. This
subtotal is a sizing proposal, NOT a hard spending cap or measured capacity claim.
There is no trading engine in this staging stack. The research worker's 2 GB and
DB's 1 GB leave more headroom for JSON/derived paths than the initial 512 MB worker/
256 MB DB idea. Dense ranges may still hit the explicitly documented report limits.

Cloudflare R2 Standard's account-wide free allowance includes 10 GB-month, 1 million
Class A requests and 10 million Class B requests monthly. Beyond it: $0.015/GB-month,
$4.50/million Class A and $0.36/million Class B; usage rounding applies. Both retries
and archive verification can add metered operations. Cloudflare Worker request/CPU
usage beyond its applicable plan allowance is also separate. No upgrade is proposed
for the staging gateway during this step. Staging and future production are separate
stacks; keeping both would incur their combined costs.

Verified official references (HTML read after the fetch tool could not read Markdown):
- https://render.com/pricing
- https://render.com/docs/compute-plans
- https://render.com/docs/blueprint-spec
- https://render.com/docs/configure-environment-variables
- https://render.com/docs/deploys
- https://render.com/docs/health-checks
- https://render.com/docs/private-network
- https://developers.cloudflare.com/r2/pricing/

## Exact future creation input

**Do not create/sync this Blueprint until the owner authorizes the quoted paid
staging resources and initial staging deployment.** Creating a Blueprint performs
an initial deployment even though automatic deploys are off. The full research app
and existing live Worker remain separate and unchanged.

- Workspace: the owner-confirmed My Workspace.
- Repository: princesspikachuu/kalshi-scanner-data.
- Branch: build/google-auth-foundation (explicitly configured for API and worker).
- Blueprint file: infra/render.staging.yaml, using the newest tested commit.
- Existing environment group: pocket-r2-staging. It must stay in the same workspace
  and be global/unscoped or scoped compatibly with Pocket Analytics/staging. Do not
  redefine it in the Blueprint or replace its credential values.
- Initial API values: APP_ORIGIN is the planned exact HTTPS staging app origin,
  GOOGLE_CLIENT_ID is the public ID provided by the owner, OWNER_GOOGLE_EMAIL is
  the confirmed owner account stored ONLY in private server configuration. Generate
  API_PROXY_SECRET through Render; do not paste it into chat or public source.
- Both processes get the database's generated INTERNAL connection string. Public
  database access stays disabled. Transactional migrations run as pre-deploy commands
  under the existing migration lock. Long-lived least-privilege runtime roles remain
  a hardening step before enabling collection; generated operator access can bypass
  SQL immutability triggers and must not be called a complete privilege boundary.
- Only the research worker receives the R2 group. Start command:
  `python -m services.research.runtime`. COLLECTION_ENABLED remains **false**. Its
  default disabled loop opens no DB/R2/HTTP clients and does not schedule work.
- The worker accepts the four EXACT credential names supplied in setup, plus
  DATABASE_URL and explicit KALSHI_READ_RATE/CAPACITY/ENDPOINT_COST. No ambient AWS
  credentials, arbitrary API host or trading credentials are used. Current proposed
  application budget is one token/second, capacity one, cost one per read. This is
  an app-side cap, not a promise about Kalshi's account tier or absence of 429s.
- Optional `python -m services.research.runtime --check-config` validates format
  without connecting. It must not be represented as verification that keys work.
- SIGTERM/SIGINT stop the loop and close HTTP/S3/PG resources. A bounded current
  step may finish/checkpoint first; forced termination recovers via durable leases.
  Heavy report computation has no hard CPU deadline, so shutdown can require lease
  recovery rather than a guaranteed graceful finish. Worker shutdown allowance: 120s.

## After authorized creation, before collection

1. Inspect actual Render deploy IDs and wait for terminal live state. API readiness
   must pass on the intended commit. A worker has no HTTP health-check URL.
2. Confirm environment KEY NAMES/group linkage without displaying secret values;
   format-check privately and verify safe startup logs. The Render connector currently
   has service environment updates but no group-inspection tool, so owner-created
   group contents/linkability have not been independently verified yet.
3. Harden runtime DB privileges and arrange a separately authorized tiny R2
   create/readback integrity test. Keep the archive bucket private and retain objects
   referenced by immutable datasets; no deletion/retention cleanup is implemented.
4. Configure the separate staging Cloudflare gateway with API_ORIGIN and the shared
   proxy secret, plus APP_ORIGIN. Reconcile the public Google origin registration.
   Its workers.dev/preview URLs are still off; publishing this separate gateway
   requires the next staging deployment action, not a change to the live app.
5. Verify actual owner Google login, wrong-account rejection, CSRF, logout and cookie
   round trip. Automated tests do not verify real FedCM/Google acceptance.
6. Only after the connection/privilege/read-budget checks should COLLECTION_ENABLED
   be enabled explicitly. This alone does not opt any category into hourly refresh;
   auto settings remain off until selected. Run a tiny real collection and verify
   complete dataset/report membership before larger ranges. No trading is involved.

The research-table/history shell and representative performance measurements remain
unfinished; this proposal prepares infrastructure testing rather than claiming the
entire product is production-ready. Do not merge or replace live table files from
this older draft branch.
