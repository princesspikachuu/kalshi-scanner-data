# Maker trade throughput and queue retention

This extends the existing 2¢ competitive and 3¢ baseline experiments. Their wallets, orders, inventory, research history and P/L remain separate, and they continue consuming the same physical market streams. No parameter is automatically fitted or promoted based on early results.

## Valid quote lifetimes

Default entry quotes now use a 30-minute maximum, adapted to 15–30 minutes from the already-observed trade cadence. Covered profit asks use a 15-minute maximum. An explicit entry limit shorter than these values is respected. Repricing, cancellations, pauses, expiration phases, fee checks and inventory limits remain active. Longer asks also retain immediate adverse-selection cancellation and liquidity-limited liquidation; adverse-selection losses are recorded explicitly.

An idempotent, transactional upgrade changes only old default values (300-second entry / 120-second exit). Values different from those defaults remain intact. Changed profiles receive a revision and archived prior settings; desired running state, contracts, per-market pauses, independent cash and checkpoints are untouched. Existing attempts keep their captured configuration; new attempts use the new quote policy.

## Cached verified admission

Verified candidate metadata is cached for at most 120 seconds, with at most eight cached rows. Healthy admission can retry one cached candidate every five seconds without repeating HTTP requests or consuming the next discovery API slot. Expired observations require verification again. Strategy/category/per-market pauses and the serialized resource/exposure gates remain authoritative. A successful admission clears the cache entry. These records are hypotheses only: the portfolio still needs fresh streaming books and current fee policies before quoting, and the cached discovery trades never enter fill simulation.

## Ranking and comparison

Verified opportunities are ranked using observed last-hour/last-six-hour executions, trade sizes, available contract-price increments, expected maker entry/exit fees and capital commitment. Expected holding time and return per dollar per day are explicitly uncalibrated ranking heuristics. They are excluded from realized/unrealized P/L and cannot authorize a fill. Capped trade responses remain lower-bound samples; no additional executions are invented. Broad discovery volume priors remain separate from verified ranking.

The dashboard scanner records the score basis, recent trade count, estimated net round-trip profit and holding time. Existing timeframe comparisons continue recording actual maker fill rate, wait time, cancellations/repricing, completed round trips, net profit and capital utilization independently for the two variants. Historical observations are retained across the policy revision.

## Backlog processing

The measured worker spent approximately 13 seconds of simulation and 13 seconds committing dirty batches in a 30-second busy sample. Backlogs above 2,000 now use the 1,024-input / 160-ms bounded tier; normal/low-load tiers remain unchanged. Every input retains its order and original timestamp; queue acknowledgments follow atomic durable commits. This trades a longer bounded simulation slice during overload for fewer full-checkpoint writes. Memory buffering remains bounded within the approved single 2-GB worker. No paid resources, API discovery frequency, fees, exposure limits or realistic fill rules change.
