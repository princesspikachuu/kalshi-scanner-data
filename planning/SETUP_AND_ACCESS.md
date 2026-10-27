# Pocket Analytics — setup, connections, and Google-only login

**Draft setup runbook. No resources, subscriptions, OAuth clients, migrations, application deployments, or live trading are being created by this document.** It extends [the build plan](BUILD_PLAN.md). Preparation and connections can be discussed now; provisioning and deployment remain paused.

## 1. Where we are building

Keep the existing GitHub repository, `princesspikachuu/kalshi-scanner-data`, as the source of truth. Continue on a development branch while the current research app remains available.

| Part | Where it lives | Initial resource name / role |
| --- | --- | --- |
| Source, tests, migrations and configuration | Existing GitHub repository | Existing repository; draft development branch |
| New React/TypeScript interface | Cloudflare static assets + Worker | Staging frontend first; final hostname to be assigned |
| Python/FastAPI backend | Render web service | `pocket-api` |
| Continuous trading/paper engine | Render background worker | `pocket-engine`; paper mode initially |
| Historical ingestion/backtests | Render background worker or bounded jobs | `pocket-research` |
| Operational SQL data | Render managed PostgreSQL | `pocket-db`, private connectivity from the services |
| Large raw archives | Cloudflare R2 | Separate private staging/production buckets |
| Google authentication configuration | Google Cloud project / Google Auth Platform | `Pocket Analytics`; separate development/production web clients |

Suggested repository layout: `apps/web/`, `services/api/`, `services/engine/`, `services/research/`, `packages/strategy_core/`, `migrations/`, `infra/`, and `tests/`. This is proposed structure, not a new implementation already present.

The browser uses the Cloudflare app origin. Route `/api/*` through its Worker to Render so login sessions use first-party app cookies. The backend still validates every protected request; directly reaching the Render hostname must not bypass authentication.

## 2. Connection status and what each connection gives us

| Connection | Confirmed status in this session | Useful access / limit |
| --- | --- | --- |
| GitHub | Already connected and used for this repository | Read/write source, draft PRs, inspect Actions jobs/logs; repository settings and secret management are separate capabilities |
| Render | Available integration found; not yet confirmed installed/connected | Services, deployments, logs, metrics and read-only SQL through supported tools |
| Cloudflare | Existing GitHub Actions deployment route works; no direct Cloudflare connector is currently loaded | Continue code/config deployment through the existing scoped CI connection after deployment resumes |
| Google Cloud authentication settings | No Google Cloud administration connection confirmed | One-time console setup by the owner; Google Drive/Gmail connections do not grant Cloud administration |
| App Google login | Planned, not implemented | Identity plus our own account authorization and session management |

Render's MCP documentation currently lists resource-creation and configuration limitations, including background-worker creation. Use a reviewed Blueprint to define the complete stack when provisioning is authorized, rather than promise the connector can create every resource. Its SQL query tool is read-only; migrations run through our migration code/runtime.

## 3. Preparation now — without deployment

### Step 1: Keep GitHub connected

**You:** Keep the existing GitHub connection authorized for this repository. No new broad personal-access token is needed just to edit code in this chat.

**I can prepare:** Code and document changes in branches, draft PRs, tests, API/schema definitions, migration scripts, and a future deployment configuration. Record reproducible setup/test commands and project rules in repository documentation.

**Done when:** I can fetch the intended branch and create a harmless draft change in this repository. This is already demonstrated.

### Step 2: Add and connect Render

**You:**

1. Create or open your account at [Render](https://dashboard.render.com/).
2. Create/select a dedicated workspace named `Pocket Analytics`.
3. In ChatGPT's Plugins directory, find **Render**, install it, and complete its requested account connection. If the current chat does not receive the new tools, reopen this project in a new chat and explicitly use Render.
4. When linking Render to GitHub for a later Blueprint, grant repository access to this repository rather than all unrelated repositories.
5. Tell me which Render workspace to select after the connection is confirmed.

**I will verify:** Workspace identity and available tools with read-only listing calls. No service creation, deployment, environment changes or database queries that expose private records are required for this connection check.

**Done when:** Render tools are available here and a read-only workspace/service listing succeeds. Merely installing the integration is not proof the external account is connected.

Prefer the normal OAuth connection. Do not paste a Render API key into chat. If an API-key-based automation connection becomes necessary, store it through the supported connection/secret mechanism; first review the account/workspace access it grants. Selecting a workspace targets operations but is not a substitute for controlling the underlying credential's permissions.

### Step 3: Retain the existing Cloudflare route; direct access is optional

**You:** Keep the Cloudflare account that hosts the current app available. We already have a working GitHub-to-Cloudflare deployment workflow. Do not replace or reveal its secret values just to plan the new app.

**I can prepare:** Worker/static-app configuration, routing, R2 integration code, and future deployment jobs in GitHub.

For additional direct Cloudflare administration, Cloudflare documents an OAuth-capable MCP endpoint at `https://mcp.cloudflare.com/mcp`. The plugin search in this session returned no installable Cloudflare result. Connecting that endpoint depends on a compatible, permitted MCP connection path in your workspace; do not assume pasting its URL into this chat connects it. We can use the existing CI path while that optional access is unresolved.

If direct access is added later, review permissions for the relevant account, Worker, buckets and any selected DNS zone. Full-account administration is not a prerequisite for normal coding, logs, or releases.

### Step 4: Choose the app owner and hostnames

**You provide:**

- The exact Google account that should be allowed to own/sign into the app.
- Whether that is the only allowed account initially (proposed default: yes).
- Whether to keep the existing app hostname or use a domain you already own later. No new domain purchase is required for planning.

**I record:** The owner-only access policy and separate local, staging and production origins. Final staging/production hostnames are assigned before registering their Google web clients.

Do not enroll the first visitor automatically as owner. The existing public GitHub research files also remain public unless repository visibility is separately changed; login does not make already-public artifacts private.

## 4. Google-only sign-in design

**Decision:** The only login button is **Sign in with Google**. No application password database, password resets, email/password signup, or separate paid authentication provider is planned.

Use Google Identity Services for identity and our backend/PostgreSQL for authorization and sessions. Google login is separate from connecting ChatGPT to Render/GitHub, and separate from authorizing access to Google Drive, Gmail, or other Google APIs. Request only identity information needed for login; do not request those unrelated Google API permissions.

Proposed flow:

1. The app obtains login state/nonce and CSRF protection from the backend.
2. The user clicks Google's sign-in button and chooses a Google account.
3. The frontend securely posts the returned Google ID token to `/api/auth/google` on the same app origin.
4. The backend validates the token using Google's supported library: signature, issuer, expected client audience, expiry and the applicable nonce/CSRF checks for our chosen flow.
5. Match the approved owner identity; reject valid Google identities that are not authorized for this app.
6. Store the stable Google `sub` as the account identifier and create a server-managed app session.
7. Issue a Secure, HttpOnly, appropriately SameSite session cookie. Keep provider tokens out of local storage, URLs, analytics and logs.
8. Every private HTTP endpoint and live-update subscription checks that app session. Sign out revokes our session; it need not log the user out of Google everywhere.

Use a verified owner email only for approved initial enrollment, then bind authorization to Google `sub`. For a Google account using an external non-Gmail/non-Workspace address, verify the intended subject out of band rather than rely on the email address alone. The owner can still use Google-only login; this does not require adding an app password.

Suggested auth tables: `users`, `google_identities` with unique issuer/subject, `sessions` storing hashes of opaque session tokens, and authentication/audit events. Session lifetime and revocation policy are configurable; exact durations are not agreed yet.

## 5. One-time Google Console setup — after hostnames are known

**You do in your Google account, or through a supported authorized administration flow:**

1. Create/select a Google Cloud project for Pocket Analytics.
2. Open **Google Auth Platform** and configure app branding, contact information and audience. Use the correct audience for your actual Google account; an organization-only setting must not accidentally exclude a personal Gmail owner.
3. Create an OAuth client of type **Web application**.
4. Add the actual app origin(s) to **Authorized JavaScript origins**: scheme plus hostname, without a page path. Add the required localhost origins/ports for developer testing if used.
5. The proposed implementation uses the GIS JavaScript callback and our own same-origin token POST. A Google redirect URI is needed only if we select Google's redirect UX; in that case register the exact endpoint, including its path.
6. Use a distinct development/staging client and production client so allowed origins and test configuration are explicit. Configure permitted test accounts where required by Google's audience/testing settings; our backend's owner restriction remains authoritative.
7. Provide the **client ID** for the correct environment. It is public configuration. Do not paste a client secret, Google password, or one-time code into chat. The planned ID-token verification flow does not require exposing a client secret to the frontend.

**I implement and test later:** The branded Google button, token validation, owner binding, session creation, logout, protected API/subscription checks, sign-in state persistence and clear denied-access messages. Branding/domain verification requirements must be checked for the final configuration; do not promise Google approval automatically.

## 6. Provisioning sequence — still paused

When construction/provisioning is authorized:

1. Prepare and review `infra/render.yaml` for the API, paper engine, research service and PostgreSQL; keep auto-deploy behavior explicit.
2. Create staging resources only after reviewing the exact resource sizes and recurring costs. A Render Blueprint can provision resources and trigger deploys; do not click **Deploy Blueprint** during the present planning stage.
3. Put PostgreSQL and connecting Render services in the same region. Use private database connectivity; do not open public SQL access merely to give the assistant visibility.
4. Generate runtime secrets in the hosting platform, bind the database connection internally, and create scoped R2 object credentials for the required buckets.
5. Run versioned SQL migrations through a dedicated migration process with the necessary permissions. Use normal app roles for runtime queries; Render read-only SQL tools are for inspection.
6. Configure the Cloudflare frontend/proxy and the real staging Google client ID. Protect new private data and control routes before connecting account data.
7. Test owner sign-in, denied accounts, logout/session expiry, CSRF, direct-API protection, reconnect behavior and logs without secret leakage.
8. Import/reconcile research data and verify full-sample counts and P/L invariance.
9. Add live recording and paper mode; live-order execution remains a later phase with its own configured controls.

Proposed runtime settings: `APP_ORIGIN`, `GOOGLE_CLIENT_ID`, a controlled owner-enrollment setting, private `DATABASE_URL`, session/CSRF secrets where the selected library needs them, and scoped R2 configuration. Define environment-specific values outside source control. Do not give me raw production SQL credentials or trading keys in chat; supported secret stores/runtime bindings are the right destinations.

## 7. What I can handle versus what stays with you

| Work | I can prepare/perform once the relevant connection and action are authorized | Your account-side step |
| --- | --- | --- |
| App/database code | Schemas, migrations, backend/frontend, tests and reviews | Resolve owner/risk/product choices |
| GitHub workflow | Branches, draft PRs, CI configuration and inspection | Maintain repository connection and any required account settings |
| Render operations | Supported service/log/deploy inspection and operations; configuration via reviewed source | Account connection, billing/terms and resource-spend decisions |
| SQL | Import/migration code and safe inspection via supported tools | Approve hosting/access configuration when provisioning resumes |
| Cloudflare | Code/config/CI path now; direct administration if a suitable connection is added | Account OAuth/permission choices and any domain ownership steps |
| Google sign-in | Full app integration and validation tests | Google account/console ownership, audience/origin configuration and public client ID |
| Secrets | Reference bindings and use supported runtime/connection mechanisms | Enter/authorize secret values through the appropriate secure flow |

The desired connection level is enough to build, inspect, debug and operate this app, rather than unrestricted access to unrelated accounts. No new cloud connection by itself overrides the current no-deployment instruction.

## 8. Ready-to-build checklist

- [x] Existing GitHub repository and working app identified.
- [x] Draft build and setup documents saved outside the deployment branch.
- [ ] Render integration installed and external connection confirmed.
- [ ] Dedicated Render workspace identified.
- [ ] Google owner account selected.
- [ ] Final local/staging/production origins recorded.
- [ ] Google web client(s) configured for the selected environments.
- [ ] Database/auth/API contracts reviewed.
- [ ] Resource sizes, secrets destinations and deployment controls reviewed before provisioning.

## Official references checked for this runbook

- [ChatGPT plugin installation and connection](https://learn.chatgpt.com/docs/plugins?surface=app)
- [Render MCP capabilities and limitations](https://render.com/docs/mcp-server)
- [Render Blueprints](https://render.com/docs/infrastructure-as-code)
- [Render PostgreSQL creation and private connections](https://render.com/docs/postgresql-creating-connecting)
- [Cloudflare official MCP connection](https://developers.cloudflare.com/agents/model-context-protocol/cloudflare/servers-for-cloudflare/)
- [Google Identity Services client setup](https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid)
- [Google server-side ID-token validation](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token)
