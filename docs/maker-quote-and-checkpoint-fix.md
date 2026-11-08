# Stationary Maker quotes and checkpoint compression

## Diagnosis

On November 8, 2026, Maker had active qualified candidates (including 39 observed trades in the preceding hour) but very few fills. The shared worker also had recurring input backlogs above 8,000 and a roughly 6.2-MB decoded checkpoint. Busy samples spent approximately 11–13 seconds simulating and 13–16 seconds committing batches per 30 seconds.

The entry-price helper inherited a scalper condition: improve the bid only after recent live flow or upward movement. A newly warmed, stationary Maker market could therefore join a large existing bid queue. The stale-order check compared the public bid with our order price, so a one-tick improved quote could also appear stale in the competitive variant despite an unchanged public book.

## Quoting correction

Adaptive Maker buys now improve by one valid contract tick whenever there is at least two ticks of spread. They remain post-only, subject to the same fees, expected-net-profit checks, liquidity, exposure, adverse-selection and resource gates. The other scalping modes retain their existing activity-dependent price rule. Maker repricing compares the old order with the desired passive entry quote; an unchanged desired quote retains queue priority.

Health logs include at most eight active quotes per portfolio, with limit, public bid/ask, remaining quantity, queue ahead, age, remaining lifetime and bounded live-tape executions at prices that could reach the hypothetical quote. These are diagnostics only, not fill authorization. Existing queue uncertainty, actual trade prints, arrival timestamps, partial fills and fees continue determining fills.

## Lossless checkpoint compression reuse

Each financial checkpoint is still complete and committed atomically with all audit events. Large research, calibration and summary subtrees are packed and compared by their actual bytes. Byte-identical subtrees reuse their prior gzip member; any nested mutation changes the bytes and is recompressed. No revision counter, pointer identity or external data reference can silently supply stale research.

The existing envelope, MessagePack schema, decoded bytes, SHA-256 checksum and bounded decompression rules are unchanged. Concatenated standard gzip members decode through the current reader, so neither a new database format nor an API reader deployment is required. Cash, orders, positions and other financial state are freshly encoded every checkpoint. The cache is limited to 16 MiB and 512 entries; eviction affects speed only. There are no extra database rows, market-data requests or paid resources.

The reproducible synthetic benchmark (`scripts/benchmark_checkpoint_segments.py`) used 60 research blocks and changed one block plus cash each iteration. On a 3.95-MB decoded fixture, twelve iterations measured median encoding CPU of 38.16 ms for the whole checkpoint and 23.30 ms with cached members, approximately 39% lower. Base64 storage increased from 880,576 to 910,388 characters, approximately 3.4%. This is an encoding benchmark, not a claim of an identical production-worker improvement; live snapshot time, cache hits, stored size and backlog remain observable.

Tests verify exact decoded-byte/hash equality with the original encoder, Decimal money, arbitrary nested mutations, cache bounds/eviction, corruption/capacity rejection, JSON fallback, current database-reader recovery, stationary YES/NO quote improvement, no self-repricing, unchanged scalper prices and trade-driven partial-fill diagnostics. No historical trading data or portfolio capital is reset.
