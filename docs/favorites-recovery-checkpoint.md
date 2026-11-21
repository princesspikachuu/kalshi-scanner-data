# Favorites recovery — 2026-11-20 Pacific

User requests: save after every step; finish observation aggregation; replace research dollar P/L with equal-weight average net return % per observation; recover stagnant positions and resume Favorites only; diagnose hourly finance/weather/sports coverage.

Base: 843b986 on build/google-auth-foundation. Worktree: fix/favorites-recovery-20261120.

Verified live diagnostics at 07:29 UTC: Favorites 75 enabled, cash/available 0.474200, 809.51 open contracts, 241 lots across 33 expired markets with no recorded settlement; no active lots, no orders, 20 fresh active books. Statistics Favorites paused (preserve). Earlier observation-count change merged as #263.

Settlement investigation: ExperimentSuite.settlement_markets excludes ordinary 15m markets. Host REST fallback only checks legacy selected tickers. A held experiment position after legacy rollover/restart can be orphaned from REST confirmation. Implement bounded, fair recovery for held experiment positions using authoritative production market results through the serialized audited consumer; no inferred payout or direct balance rewrite.

Percentage semantics: mean of each resolved event's net P/L / its fee-inclusive closed entry cost, equal event weights. Existing aggregate dollar totals alone cannot reconstruct that mean; never relabel portfolio ROI as average observation ROI. Preserve old history and explicitly expose unavailable/partial coverage where per-event attribution is absent.

Step 2 saved: added settlement_recovery.py and hosted coroutine. Checks up to four least-recently-polled held expired tickers per five-second pass, 30-second per-ticker cooldown, existing shared verified REST budget. Confirms exact ticker, finalized/settled status and yes/no result; dispatches existing serialized experiment_settlement input. Does not mutate wallets directly. Two async regressions pass: orphaned 15m recovery, idempotent cooldown, failure isolation, mismatched/unresolved result rejection and fair bounded progress.

Step 3 saved: fee-inclusive close net tracked per entry chunk; verified resolved events pool cost/net before equal-weight averaging, combining correlated prices inside the same displayed cell. Old partly closed chunks without complete exit attribution are excluded explicitly. Category summary transports compact sum/count; detailed rows retain bounded event attribution. Research tables/matrices display average P/L %, with tracked-return sample count and unavailable legacy coverage. Wallet/dollar accounting is preserved. Equal-weight/merge tests and frontend regressions pass; entry timing suite passes; 13 workspace transport cases pass. Targeted scan/weather/sports suite 35 passed/skipped (2 PostgreSQL cases skipped locally).

Publication attempt was rejected by automatic approval review before Git push (unverified external destination). Subsequently verified through GitHub that princesspikachuu/kalshi-scanner-data is public with connected-account push access, and matches all three existing Render service sources. No publication or hosted recovery yet.
