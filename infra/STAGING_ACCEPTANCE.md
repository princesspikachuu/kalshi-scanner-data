# Staging acceptance and runtime database isolation

Verified on October 27, 2026: real R2 conditional-write/readback/reuse acceptance
passed with an 88-byte retained marker; hosted DB audit verified nine matching
migrations and correctly rejected operator credentials as a runtime boundary.
224 tests passed in CI 40553521523. Runtime-role SQL was subsequently applied as NOLOGIN role preparation by
96f59f3 (receipt verified); passwords and runtime credential/migration separation
remain pending. Do not re-run the fresh-role transaction. See the latest checkpoint for
exact deploy IDs and final diagnostic-off verification.


Collection stays disabled throughout. Enabled worker startup now refuses collection
unless the read-only audit verifies a direct non-owner login without elevated
privileges, memberships, schema/temp creation or history-mutation privileges.
An operator DATABASE_URL cannot pass even if COLLECTION_ENABLED is toggled true. Do not change live Cloudflare configuration,
upgrade compute, expose the database, or add a trading credential for these checks.
Owner has confirmed actual Google login, persistence after refresh and logout.
These are owner-reported browser checks; automated wrong-account testing remains
separate. Public-repo checkpoints contain no owner email or credential values.

## Existing private worker diagnostics

The Render connector cannot query this private DB: its external IP allowlist is
empty. Keep it empty. Use the existing research worker's private network instead.
After the tested commit is manually deployed, merge one temporary environment
variable on pocket-research-staging, preserving every existing secret/group:

- `STAGING_ACCEPTANCE=database-v1`: one read-only catalog/migration checksum audit
  per process start; no user/session rows or payloads are read. JSON flags report
  ownership, elevated roles, memberships, schema/temp creation and immutable-history
  DML privileges. Operator credentials must NOT pass this boundary check. A CLI
  audit also exits 3 when isolation is not ready; that is an expected finding.
- `STAGING_ACCEPTANCE=r2-v1`: one bounded R2 marker verification per process start,
  then normal disabled idle. Maximum two conditional PUTs and two bounded GETs,
  each with the SDK's existing maximum three attempts. The deterministic marker
  uses provider staging_acceptance and a non-market payload, below 1 KiB; at most
  one tiny retained object, no delete/overwrite, no database writes or Kalshi calls.
  Repeated starts reuse the same key. A successful JSON receipt is required; a
  live worker alone is NOT proof. Failure is sanitized and idles without app retries.

Both flags require COLLECTION_ENABLED=false. Invalid values or simultaneous
collection enablement are rejected before opening clients. Default is off and
opens no diagnostic connections. Change STAGING_ACCEPTANCE back to off after
recording each result, then verify the final disabled deployment. Service restarts
while a flag is enabled can repeat that bounded diagnostic; never leave it on.
No continuous acceptance schedule or new paid service is needed.

Equivalent private shell commands:

```
python -m services.research.acceptance database
python -m services.research.acceptance r2 --write-r2-probe
```

Do not copy hosted credentials locally to run these. Error output intentionally
omits SDK/PG diagnostics that might include private URLs or credentials.

## Database permissions — non-login role preparation applied

infra/runtime-roles.sql is a separate explicit operator transaction, NOT a numbered
migration, startup hook or deploy command. It creates two fresh NOLOGIN roles:

- pocket_api_runtime: auth/session operations and campaign controls; reads published
  coverage/results. Owner subject and existing session material cannot be updated.
- pocket_research_runtime: queue/budget work and append-only archive/data/result
  publication; no access to owner sessions, login challenges or owner identities.

Neither owns objects or has privileged-role membership, CREATE, TRUNCATE, mutable
history DML, trigger alteration or future-table default grants. PUBLIC schema
creation and database TEMP creation are revoked to prevent shadowing unqualified
names in publication guards. Operator retains ownership for migrations. Existing
role names fail closed rather than silently reusing a potentially privileged role.
The transaction must be reviewed against any other applications sharing the DB
before applying; this staging DB is dedicated but do not assume names are absent.

The SQL alone does NOT isolate running processes. Owner must securely establish
separate LOGIN credentials for these principals, with no membership in operator,
each other or privileged predefined roles; keep passwords in Render only. Use
separate runtime DATABASE_URLs that authenticate DIRECTLY as the corresponding
role, and retain the operator URL only for explicit migrations in a separate job.
Do not leave the operator URL available to runtime or rely on SET ROLE: an operator
session can reset/escalate back. Current Blueprint preDeploy/runtime share DATABASE_URL,
so removing the operator from runtime also requires splitting migration execution
from service startup before changing URLs. No password is generated or committed
by this permission-plan milestone. The grants are now applied to the NOLOGIN
roles, but the running processes still use the operator credential; actual
runtime isolation remains pending.

Real disposable-PG tests exercise auth, campaign controls, queue claims, budget
configuration and dataset/report publication under the proposed grants. They deny
history rewriting, trigger removal, permanent/temp shadow tables and cross-service
session access. Tests use privileged SET LOCAL ROLE only for impersonation and
never claim that this makes an operator credential safe in production.

Official privilege references:
- https://www.postgresql.org/docs/17/sql-grant.html
- https://www.postgresql.org/docs/17/role-membership.html
- https://render.com/docs/private-network

## Preparing the non-login roles without credentials

A default-off operator action can apply the reviewed NOLOGIN role plan from the
existing private research worker. It checks the exact nine migration hashes,
requires the database owner, allows ONLY pocket_staging or disposable pocket_test,
and serializes with migrations. SQL and postconditions share one transaction;
name collisions fail closed and roll back the whole preparation. No passwords,
LOGIN permissions, runtime URL changes, ownership transfers or role memberships
are created. Existing roles are never silently repurposed.

After CI passes, merge these temporary worker values (preserve all other fields):
COLLECTION_ENABLED=false, STAGING_ACCEPTANCE=off,
STAGING_OPERATOR_ACTION=prepare-roles-v1. One attempt per process prints a
runtime-role-preparation-v1 receipt, then idles. Failure is sanitized and does not
retry. Reset STAGING_OPERATOR_ACTION=off and verify the final disabled deployment.
A prepared=true receipt still says runtime_isolated=false and passwords_created=false.
Existing role names on a repeat are deliberately an operator-review failure.
Equivalent private operator command: python -m services.api.manage prepare-runtime-roles.
Never run the operator action with a runtime login or enable collection alongside it.

## API credential-cutover gate

Shared read-only database audit v2 now checks the expected direct role as well as
ownership, dangerous grants, memberships, schema/temp privileges and migration
checksums. The research worker requires pocket_research_runtime. The API can opt
into REQUIRE_API_RUNTIME_DB=true and requires pocket_api_runtime before opening
its pool; connection diagnostics are sanitized. This API flag defaults false until
the owner completes the coordinated cutover, preserving the working staging login.
The worker collection gate remains mandatory. A worker login cannot pass the API
profile and vice versa. Actual service credential isolation is still pending.

For the eventual cutover, first apply/verify migrations through a private operator
session that is separate from the long-lived app processes. Then remove automatic
operator migration commands from BOTH services, configure private direct runtime
DATABASE_URLs and remove any operator URL/password variables from their runtime
environments, enable the API gate, deploy and inspect both direct-role audits.
The existing Blueprint still specifies operator URLs and preDeploy migrations;
it must be reconciled before any future manual sync, which otherwise restores
unsafe settings. Keep Blueprint sync paused. A sync:false field does not prompt
again when updating an existing Blueprint; private values require explicit edits.
Do not hide an operator URL in a second service env variable or just SET ROLE.
Owner-only secure password/connection setup must finish before collection.
