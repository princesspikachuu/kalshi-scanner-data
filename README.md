# Kalshi Pocket Analytics — maker-only historical research

The analysis is organized by **contract type × minutes remaining × maker purchase-price range**:

- **Hourly weather:** both hourly Weather Index (multi-station) and hourly single-station temperature contracts, pooled across cities (sample permitting).
- **Bitcoin:** 15-minute contracts.
- **Ethereum:** 15-minute contracts.

## Mobile dashboard app

The **Pocket Analytics** app now lives in [`docs/index.html`](docs/index.html). It is a responsive, installable web app (with an app manifest/icon), and reads the maker-only summary in `backtests/AVERAGES_BY_TIME_AND_PRICE.csv` directly from this public GitHub repository. Its data updates when the historical research workflow commits new results; tap **Refresh** to reload.

To publish an app URL using **GitHub Pages**, the owner of this repository should open **Settings → Pages**, set **Build and deployment → Deploy from a branch**, choose **main** and the **/docs** folder, then save. GitHub will display the published URL once the Pages build succeeds. Expected URL pattern: `https://princesspikachuu.github.io/kalshi-scanner-data/` (only after Pages is enabled).

On a phone, open that URL in a browser and choose **Add to Home screen** / **Install app**, if offered. An installation does not turn historical simulations into verified trading results.

Cloudflare remains a separate deployment: we have not modified or redeployed your existing Worker, because this GitHub connection does not control the Cloudflare account.

## Dynamic app (Cloudflare Worker)

The repository now includes a **dynamic, authenticated app**:

- `worker/src/index.js`: same-origin backend with `GET /api/health`, `GET /api/runs` and authenticated `POST /api/runs`.
- `docs/index.html`: mobile UI with **Run collection in app** and **Check job status**.
- `wrangler.jsonc`: serves the UI and API on the same Cloudflare Worker hostname.
- `.github/workflows/deploy-pocket-app.yml`: **manual-only** Cloudflare deployment, not a scheduled scan.

**One-time setup (must be completed by repository and Cloudflare account owner):**

1. In GitHub repository **Settings → Secrets and variables → Actions**, set `CLOUDFLARE_API_TOKEN` (Cloudflare token scoped to deploy Workers on your account) and `CLOUDFLARE_ACCOUNT_ID`.
2. Create a GitHub fine-grained personal access token scoped only to `princesspikachuu/kalshi-scanner-data` with **Actions: Read and write** and **Metadata: Read**, so it can dispatch and check workflow runs. Save it as GitHub Actions secret `POCKET_GITHUB_ACTIONS_TOKEN`. Don't paste the token in chat or source files.
3. Generate a unique, high-entropy app access key; save it as `POCKET_APP_ADMIN_KEY` in the GitHub Actions secrets. This is the key you'll enter into the phone app to authorize a collection. Do **not** reuse a password or a GitHub token.
4. Open [Deploy Pocket Analytics dynamic Worker](https://github.com/princesspikachuu/kalshi-scanner-data/actions/workflows/deploy-pocket-app.yml) and click **Run workflow** once. The job deploys app assets and installs the two server-side secrets into Cloudflare. You can then use the `*.workers.dev` URL shown by Cloudflare or the deployment log.

**Important:** The existing GitHub Pages app remains read-only; it cannot trigger runs. Open the **Cloudflare Worker URL** to see the working Run button. Configure custom domains inside Cloudflare if desired. The backend does not run automatically, place trades, or continuously poll Kalshi; it only launches the explicitly requested historical GitHub Actions collection.

**Security:** No GitHub token is sent to browsers. The access key is submitted over HTTPS per run, stored only in the active browser session's form field, and checked by the Worker. Keep the Worker URL and access key private; anyone with the key can start a bounded collection job. For additional protection, use Cloudflare Access or another identity-based authentication layer. If the app is public, do not share the admin key.

**Operation:** Set asset, days ago, number of days (up to 7), and markets/day (up to 300, capped at 900 sampled markets for one request). The API validates the input and refuses a second run while one is active. The dashboard's **Check job status** shows recent run state. When completed, **Refresh** loads the latest committed dataset from GitHub. This still relies on the existing GitHub Actions collector; it is not a live-trading bot.

## See the results

**[Open the main time-by-price report](backtests/OVERVIEW.md)** — separate tables for hourly weather, Bitcoin and Ethereum. Each cell is the **average simulated profit/loss in cents per contract**, with sample size in parentheses.

**[Open the full sortable data as CSV](backtests/AVERAGES_BY_TIME_AND_PRICE.csv)** — includes number of contracts, wins, win rate, average maker bid, average profit/loss per contract, hypothetical percentage ROI and sampled days.

The individual market-type reports appear in `backtests/weather_hourly/REPORT.md`, `backtests/btc15m/REPORT.md` and `backtests/eth15m/REPORT.md` as data becomes available.

## On-demand historical collection

Run [Kalshi historical research](https://github.com/princesspikachuu/kalshi-scanner-data/actions/workflows/research-backtest.yml) with asset `weather`, `btc` or `eth`; `days_ago` (1–30); `days_to_collect` (1–7); and per-day `max_markets` (1–300).

- Hourly weather entry times: **60, 45, 30, 20, 15, 10, 5, 3, 1 minutes** remaining.
- Bitcoin/Ethereum entry times: **15, 10, 5, 3, 1 minutes** remaining.
- Jobs run only on manual request; the old live-market scanner schedule is retired.

The workflow runs `scripts/collect_backtest.py`, creates the summary with `scripts/build_report.py`, then commits the resulting research files.

## Important limitations

**None of the reported profits are verified executed trades.** Each observation assumes a passive maker buy was filled at the historical bid, without accounting for order-book queue position, fill probability, market depth, slippage or actual series-specific fees. The grid reports **pre-fee** returns. Correlated weather strikes and repeated market observations across entry times must not be treated as independent bets.

Incomplete or missing contract types indicate inadequate historical coverage, not a measured result. A single day of favorable results is not strong evidence of a durable advantage.
