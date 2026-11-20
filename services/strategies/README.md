# Draft strategy foundation

This isolated milestone stores immutable revisions of draft strategy rules. The
rules use integer cents and contract counts, include entry timing and order
parameters, encode a research-backed downside exit by purchase-price band, and
bound per-trade, category, strategy, global, and daily exposure. Revision writes
use optimistic concurrency; an old revision remains readable after a change.

There are no API routes, market subscriptions, order submission, enable control,
paper engine, or live trading in this milestone. `strategy_draft.state` is
restricted to `draft` by the database. Future paper-mode work must validate
market evidence and execution permissions independently.

`0010_draft_strategy_versions.sql` is **unapplied**. Deploying this branch would
require a coordinated operator migration and runtime-role grant/audit update;
the current staging API and worker use restricted accounts and must not run this
migration automatically. The migration does not change existing research data.

Local validation: `python -m unittest discover -s services/api/tests -q` passed
276 cases, with 91 PostgreSQL cases skipped without a disposable `pocket_test`
database. Four new PostgreSQL tests cover append-only revisions, stale writes,
and direct SQL mutation rejection and must run in CI before integration.
