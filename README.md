# Kalshi Pocket Analytics — maker-only historical research

See [the working app plan](APP_PLAN.md) for the automation roadmap, proposed stack, and required hold-versus-early-sale analysis.

The analysis is organized by **contract type × minutes remaining × maker purchase-price range**:

- **Hourly weather:** both hourly Weather Index (multi-station) and hourly single-station temperature contracts, pooled across cities (sample permitting).
- **Bitcoin:** 15-minute contracts.
- **Ethereum:** 15-minute contracts.

## Mobile dashboard app

The **Pocket Analytics** app now lives in [`docs/index.html`](docs/index.html). It is a responsive, installable web app (with an app manifest/icon), and reads the maker-only summary in `backtests/AVERAGES_BY_TIME_AND_PRICE.csv` directly from this public GitHub repository. Its data updates when the historical research workflow commits new results; tap **Refresh** to reload.

To publish an app URL using **GitHub Pages**, the owner of this repository should open **Settings → Pages**, set **Build and deployment → Deploy from a branch**, choose **main** and the **/docs** folder, then save. GitHub will display the published URL once the Pages build succeeds. Expected URL pattern: `https://princesspikachuu.github.io/kalshi-scanner-data/` (only after Pages is enabled).

On a phone, open that URL in a browser and choose **Add to Home screen** / **Install app**, if offered. An installation does not turn historical simulations into verified trading results.

Cloudflare remains a separate deployment: we have not modified or redeployed your existing Worker, because this GitHub connection does not control the Cloudflare account.

## Dashboard refresh and data synchronization

Every successful `research-backtest.yml` run now executes `scripts/sync_dashboard.py`, publishing `docs/data.csv`, `docs/dataset-meta.json` and `docs/status-{btc,eth,weather}.json` in the **same commit** as the research output. This prevents the app from relying on a fallback GitHub raw URL for refreshed data. The mobile app shows the accumulated sample's actual trading days, observations, market count and date range.

The initial same-origin files were also published from the existing historical results. Use the **Refresh** button to load the new data. If you are using **GitHub Pages**, GitHub Pages must publish the newest commit first. If you are using the **Cloudflare Worker** app, deploy the latest main branch via `deploy-pocket-app.yml`; Cloudflare serves the bundled `docs/` at deploy time, so a new research commit alone cannot update the already deployed static assets. We can later add automatic safe redeployment or a dynamic data endpoint.

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

**Operation:** Set asset, days ago (up to 3,650), number of days (up to 7), and markets/day (up to 300, capped at 900 sampled markets for one request). The API validates the input and refuses a second run while one is active. The dashboard's **Check job status** shows recent run state. When completed, **Refresh** loads the latest committed dataset from GitHub. This still relies on the existing GitHub Actions collector; it is not a live-trading bot.

## See the results

**[Open the main time-by-price report](backtests/OVERVIEW.md)** — separate tables for hourly weather, Bitcoin and Ethereum. Each cell is the **average simulated profit/loss in cents per contract**, with sample size in parentheses.

**[Open the full sortable data as CSV](backtests/AVERAGES_BY_TIME_AND_PRICE.csv)** — includes number of contracts, wins, win rate, average maker bid, average profit/loss per contract, hypothetical percentage ROI and sampled days.

The individual market-type reports appear in `backtests/weather_hourly/REPORT.md`, `backtests/btc15m/REPORT.md` and `backtests/eth15m/REPORT.md` as data becomes available.

## On-demand historical collection

Run [Kalshi historical research](https://github.com/princesspikachuu/kalshi-scanner-data/actions/workflows/research-backtest.yml) with asset `weather`, `btc` or `eth`; `days_ago` (1–3,650); `days_to_collect` (1–7); and per-day `max_markets` (1–300).

- Hourly weather entry times: **60, 45, 30, 20, 15, 10, 5, 3, 1 minutes** remaining.
- Bitcoin/Ethereum entry times: **15, 10, 5, 3, 1 minutes** remaining.
- Jobs run only on manual request; the old live-market scanner schedule is retired.

The workflow runs `scripts/collect_backtest.py`, creates the summary with `scripts/build_report.py`, then commits the resulting research files.

## Important limitations

**None of the reported profits are verified executed trades.** Each observation assumes a passive maker buy was filled at the historical bid, without accounting for order-book queue position, fill probability, market depth, slippage or actual series-specific fees. The grid reports **pre-fee** returns. Correlated weather strikes and repeated market observations across entry times must not be treated as independent bets.

Incomplete or missing contract types indicate inadequate historical coverage, not a measured result. A single day of favorable results is not strong evidence of a durable advantage.

## Older historical collections

Set **Starting how many days ago?** to 90, 180, 365, or another offset up to 3,650 (10 years). The app previews the actual UTC date range. Each run still samples at most seven days and 300 markets per day. Availability depends on when that market family began and which quotes Kalshi retains; an older date is not a guarantee of coverage.

For archived dates the collector enumerates the complete series archive, reusing a runner-local index across all requested days. An incomplete archive fails without publishing partial results. The first archive lookup can take longer than a recent-date collection.

## Loss prevention by purchase price

The dashboard includes a separate **Loss prevention by purchase price** comparison. Select the entry time and turn **Apply supported loss-prevention thresholds** on or off. Both comparison columns use identical entries and a stated fee-stress scenario: 1¢ entry, plus 2¢ per early sale. The original before-fee heatmap remains unchanged.

Fresh collections now save minute-close YES/NO bid paths in per-day `.paths.json` files using the candles already downloaded, so no extra Kalshi requests are needed. Older entry-only CSVs cannot establish an exit threshold. Collect at least seven distinct dates with usable paths to allow five earlier training days and two later validation days. More history and markets may be needed for individual cost bands.

The study tests only downside sale prices, in 5¢ steps, independently by contract family, purchase-price band, and entry time. Candidates must meet minimum market/event/trigger counts and positive event-clustered improvement bounds in training, then pass later validation. A failed candidate is not replaced by another fitted to validation. Training observations are excluded from the displayed comparison after splitting. Each category's latest view is restricted to its staged run's observations; the cumulative view includes eligible saved price paths.

An exit uses the first subsequent positive bid at or below the threshold, strictly before close. A gap below the threshold sells at the observed bid, not the more favorable threshold. Missing quotes exclude that entry; zero bids mean no available buyer. Trades that later recovered count against exiting. No supported threshold means holding, with the reason shown.

These are exploratory minute-close quote simulations with assumed entry and exit fills. The fee stress is not the actual fee schedule. Depth, order queues, execution latency and slippage are not replayed. This feature does not place orders or guarantee loss prevention.
