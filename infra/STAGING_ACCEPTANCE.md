# Staging acceptance and runtime database isolation

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

## Database permission plan — prepared, not automatically applied

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
by this permission-plan milestone, and the plan has NOT been applied to staging.

Real disposable-PG tests exercise auth, campaign controls, queue claims, budget
configuration and dataset/report publication under the proposed grants. They deny
history rewriting, trigger removal, permanent/temp shadow tables and cross-service
session access. Tests use privileged SET LOCAL ROLE only for impersonation and
never claim that this makes an operator credential safe in production.

Official privilege references:
- https://www.postgresql.org/docs/17/sql-grant.html
- https://www.postgresql.org/docs/17/role-membership.html
- https://render.com/docs/private-network
