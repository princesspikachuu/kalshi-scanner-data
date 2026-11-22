# MT-017 — Cloudflare Account Analytics read-only bridge

**Status: prepared; not connected until a user creates the secret and runs the workflow.**  
**Scope:** regular High-Probability Favorites **dashboard/gateway reliability only**; no Cloudflare writes or Render changes.

A direct Cloudflare connector was not available in ChatGPT. Instead, the existing
GitHub connection can read the result of a **manual-only** GitHub Actions job
that calls Cloudflare's official GraphQL **read-only** Analytics API.

## Important privacy notice

The Money Tree GitHub repository is **PUBLIC**. Actions logs may be viewed
by others. The workflow prints **only aggregate counts and CPU percentiles** for
the two named Workers; it never prints access tokens, Cloudflare account IDs,
request paths, IPs, cookies, private invocation events, logs, or raw API responses.
If even aggregate Worker request volumes are sensitive, **do not enable this
workflow here**; use a private repository/observability destination instead.
Only user-controlled manual dispatch is enabled: no scheduled traffic or
deployment is initiated.

## One-time account setup

1. Open https://dash.cloudflare.com/profile/api-tokens and create a custom API
   token called **Money Tree — CPU Analytics Read Only**.
2. Restrict it to the **specific Cloudflare account** hosting Money Tree.
   Select **Account → Account Analytics → Read**, or the equivalent
   Cloudflare account-analytics read-only permission. Do **not** give Workers
   Script Write, DNS Write, R2 Write, Tokens Write or account-admin access.
   Cloudflare's Workers **Metadata Read-Only** role may be used separately for
   *logs/traces* if that feature becomes necessary; it is not required for this
   GraphQL-only query. Verify token scope before creating it.
3. In GitHub open the repository **Settings → Secrets and variables → Actions**
   . Add a **Repository secret** (not an Environment secret) named
   **CLOUDFLARE_OBSERVABILITY_TOKEN** and paste
   the token **there only**. Never paste it into chat, PRs, tickets, scripts,
   workflow inputs, screenshots or terminal output.
4. The workflow also needs **CLOUDFLARE_ACCOUNT_ID**. If the staging deployment
   already uses that GitHub Actions secret, reuse it; otherwise add the account
   ID as a Repository secret too. The account ID itself
   is never printed.
5. Once the workflow exists on **main**, open:
   https://github.com/princesspikachuu/kalshi-scanner-data/actions/workflows/cloudflare-cpu-readonly.yml
   Click **Run workflow** and select **last_24h** for fresh data or
   **nov_09_2026** to examine the historical CPU warning day.
6. Ask **Money Tree — Chat 2.0: Deployment Verification** to analyze the
   resulting GitHub Actions run. We can read the sanitized output using the
   connected GitHub tools, without ever receiving your API token.

## Output / limitations

Each Worker summary includes estimated invocation count, estimated request
errors, requests whose Cloudflare invocation outcome was **exceededCpu**, and
CPU p50, p95 and p99 in **milliseconds**. Counts may be affected by Cloudflare
adaptive sampling. A Worker with no returned rows is reported **no_analytics_rows**,
not "zero CPU problems." Worker resource limits and quotas are distinct from
origin HTTP 403s and from Render trading-worker resource limits. Aggregates
do **not** identify high-CPU routes or raw request traces; deeper investigation
would require additional approved, narrowly scoped observability access.

**Third failed run and independent token probe (Nov 21, 2026 Pacific):** [Actions #44980816586](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44980816586) passed 17 offline tests, but the safe preflight failed at its earliest `viewer { __typename }` GraphQL request with `HTTP 400 (unclassified)`; account and CPU datasets were never checked. This is **not** evidence the token is invalid, and not a Render deployment failure.

To avoid guessing at query schemas or repeatedly asking for token recreation, the next revision uses Cloudflare's documented **`viewer { budget }`** scalar (rather than `__typename` introspection), strips GraphQL query whitespace to one line, and issues a read-only **GET token verification** against the official User or Account API-token verification endpoint only after an analytics failure. It reports only token status (`active`, `disabled`, `expired`, or an error class), never token IDs, expiration dates, private account identifiers, API bodies or raw Cloudflare messages. Cloudflare's published error categories `query contains error` and `Authentication error` are also classified into fixed privacy-safe labels. This doesn't make the unknown root cause known until a real API check succeeds.
**Second failed run / safe diagnostics:** User's rerun [#44980433098](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44980433098) passed all 11 offline tests but Cloudflare continued to return HTTP 400 on all three query variants. Before further credential or query guesses, the bridge now runs a **one-time diagnostic sequence only after the metric query fails**: verify account-ID secret has 32-hex shape (no value exposed), attempt viewer typename, scoped account visibility, and the documented minimal Workers dataset.
The only printed result is `MT017_SAFE_PREFLIGHT` with **fixed stage and error-category labels**. It never prints a token, account ID, Cloudflare message/path, invocation body, IP, or request path. The last fallback now matches the exact variable-nullability convention in Cloudflare's published Workers example (`string` rather than `string!`). A successful diagnostic does not constitute real metrics verification; absence of metrics must not be labeled zero.

**No credential changes required for this test:** The previous runs showed both GitHub secrets were present, but not whether they grant account/dataset access. If safe preflight reports account_id/not_32_hex_characters, the account-ID secret has the wrong format. If viewer fails, investigate API authentication; if account fails, inspect token account scope. Dataset failures are classified without raw errors. Do not share credentials or unredacted responses in this PUBLIC repository.

**HTTP 400 query-schema compatibility:** After the first manual run failed at the Cloudflare GraphQL request (not at deployment), the audit now tries Cloudflare's newer `Time` variable scalar and, for schema HTTP 400 only, a smaller documented read-only query. The final compatibility variant uses the older `string` scalar. On a partial fallback, `exceeded_cpu: null` means the detailed breakdown was unavailable, **not** that zero CPU-limit failures occurred. No raw Cloudflare API response or credentials are printed. Offline test success is not confirmation of actual Cloudflare analytics access.

The workflow has only **workflow_dispatch**, repository **contents:read**,
a fixed Cloudflare **HTTPS POST GraphQL query**, and static Worker names
pocket-analytics-staging and kalshi-pocket-analytics. It cannot deploy code,
change DNS, R2 or Workers settings, enable trading, or read database records.

Docs:
- https://developers.cloudflare.com/analytics/graphql-api/tutorials/querying-workers-metrics/
- https://developers.cloudflare.com/fundamentals/api/how-to/account-owned-token-template/
- https://developers.cloudflare.com/workers/authorization/workers/
