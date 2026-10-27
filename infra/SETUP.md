# Infrastructure and access — preparation only

## Current connection evidence

| Service | Verified state | Next step |
| --- | --- | --- |
| GitHub | Repository read/write and draft PR access work | Keep application and infrastructure changes on the development draft |
| Render | Connected; owner selected “My Workspace”; workspace-scoped queries work | No services returned; no PostgreSQL instances found. Prepare staging before any creation |
| Cloudflare | Existing GitHub Actions deployment connection works for the research app | Prepare a separate staging app/proxy and scoped R2 access; no direct Cloudflare administration tool is connected |
| Google Cloud | Owner account confirmed; no administration connection or web OAuth client ID established for this app | Owner creates or selects a Google Cloud project and a Web OAuth client |
| PostgreSQL | Code, migrations and CI integration are prepared | No Render database created; use a disposable CI database first |
| R2 | Planned for compressed raw archives | No buckets, access keys or uploads created |

The Render connection can list services, inspect deployments/logs/metrics and run
supported read-only SQL. Database migrations run through application tooling.
The existing deployment connection is not full Cloudflare account access. Google
Drive/Gmail connections are not Google Cloud administration or app login setup.

## Prepared staging stack

`infra/render.staging.yaml` defines a staging project with one Python API web
service and a PostgreSQL database in Oregon. Both use the private database
connection. The database denies public connections. The API pool is capped at
five connections. This is an initial staging choice; confirm production region
using measurements before provisioning production.

Automatic deploys and preview environments are disabled. **Creating or syncing
this Blueprint can still provision resources, incur costs and perform an initial
deploy. Do not create or sync it during this preparation phase.** It is stored
under `infra/`, not linked to Render. No application service has been created.

The initial configuration deliberately omits continuously billed research and
trading workers until their code is ready. Research jobs and the future trading
engine will run separately from the API so slow backfills cannot block live state.
No Redis, Kubernetes or additional database is required by this draft.

## Account-side setup when staging is ready

1. **Google Cloud:** Create or select the owner-controlled Pocket Analytics
   project. Configure Google Auth Platform branding/audience and a Web client
   for Sign in with Google. Register the exact staging HTTPS app origin, without
   a path. Add the owner's account as a test user if the selected audience mode
   requires it. Choose the owner's exact Google account; do not infer it from
   hosting or GitHub identities.
2. **Google login configuration:** Store the public web client ID as
   `GOOGLE_CLIENT_ID`, the exact origin as `APP_ORIGIN`, and the chosen account as
   `OWNER_GOOGLE_EMAIL`. Google ID-token login does not require a browser client
   secret. If Google is not authoritative for that email, bind its verified
   stable Google subject administratively instead of trusting email alone.
3. **Render:** Review the Blueprint's resource names, plans, region, disk size
   and budget. Only when resource creation is authorized, connect this GitHub
   repository using Render's scoped GitHub integration and select the explicit
   Blueprint file/branch. Workspace MCP access does not by itself connect the
   repository for builds. Keep automatic deploys off.
4. **Database:** Use the generated internal connection through `fromDatabase`.
   Keep public access disabled. The prepared pre-deploy command applies the
   transactional migrations. Review migrations before the eventual deploy;
   owner/session and research tables are not applied to any hosted database yet.
5. **Cloudflare staging:** Use a separate staging Worker/app hostname. Store the
   API origin and the shared proxy secret in Worker server configuration. Put
   the same generated secret in the API; never expose it in frontend assets.
   Implement the proxy contract in `services/api/README.md` before browser tests.
6. **R2:** Create private staging and production buckets separately when the
   archive client is ready. Use a bucket-scoped token for object access. Keep
   object references/checksums in PostgreSQL. Do not grant account-wide access
   merely to upload archive files.
7. **Acceptance:** Test owner login, wrong-account rejection, challenge replay,
   session expiry, CSRF failures, logout and direct-backend requests. Verify
   both private database access and secrets redaction before promoting anything.

## Work already prepared versus outstanding

Prepared: API/auth code, pinned dependencies, session and research-storage
migrations, staging Blueprint, schema validation, and PostgreSQL CI checks.

Outstanding: actual Google OAuth configuration and storing the chosen owner account in server configuration,
Cloudflare staging proxy/UI, Render resource creation, hosted migration run,
R2 archival client, SQL research ingestion/queries, job workers and eventual
forward paper trading. No live order placement exists in this draft.

## Current official references

- https://render.com/docs/mcp-server
- https://render.com/docs/blueprint-spec
- https://render.com/docs/compute-plans
- https://render.com/docs/private-network
- https://render.com/docs/configure-environment-variables
- https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid
- https://developers.google.com/identity/gsi/web/guides/verify-google-id-token

## Integration discovery result

The current plugin search returned no Cloudflare plugin and no Google Cloud
administration plugin capable of creating OAuth clients. BigQuery and the
Google productivity connectors do not provide that capability. More integrations
may be available in https://chatgpt.com/plugins; none were installed for an
unrelated capability. Continue through the existing Cloudflare CI connection
and owner-controlled Google Cloud console setup for this milestone.
