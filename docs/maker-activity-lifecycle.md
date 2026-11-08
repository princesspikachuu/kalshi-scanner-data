# Market Maker activity lifecycle

Live observations on November 8, 2026 showed only five baseline and eight competitive order submissions, with one competitive round trip ($0.0166 net). Both portfolios frequently had no monitored market. Discovery had 56 candidates, with real rejections for trade frequency and unstable prices, as well as processing-backlog pauses.

Two lifecycle mismatches compounded those valid gates. Generic flat-market rotation retired Maker probes after two minutes between orders. Maker separately stopped new buys five minutes after discovery if no print had arrived in the preceding two minutes. These clocks fit fast scalps poorly suited to slower market making.

Maker now uses an observation window of six median positive intervals between the already-fetched discovery trades, bounded to 15–60 minutes. The latest actual live print refreshes the window. Discovery trades remain metadata and are never fed to the fill simulator. Old markets without cadence metadata receive the 15-minute minimum. Genuinely idle, flat markets still rotate out. Explicit pauses, scheduled-event windows, adverse selection, exposure limits and fee/liquidity checks remain active. Resting orders still have their configured five-minute lifetime and retain cancellation/repricing logic; this change does not manufacture longer-lived orders or fills.

Normal rotation honors the Maker window; the existing reclaim path can still release a flat Maker probe when another strategy needs capacity. The physical Maker stream cap remains two. Experimental portfolios share those streams. No new polling, API requests, history buffers or paid compute are added. Longer useful observation may keep these two existing slots active more often; the worker admission gate and total capacity remain unchanged.

Discovery now distinguishes enqueue from actual admission. The engine acknowledges successful shared monitoring, or records a capacity rejection and allows a retry after 30 seconds rather than silently losing the candidate for five minutes. Actual admission continues to require current healthy capacity. Dashboard scanner records and logs report that acknowledged status.

Regression tests cover retention and eventual retirement, live-print renewal, restart persistence, cross-strategy reclaim, unchanged capital with no fills, and a capacity race followed by safe admission. Existing maker round-trip, queue, cancellation, fee, exposure, settlement and portfolio-isolation tests remain in the suite.
