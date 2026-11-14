# Estimate queued work from committed burst throughput

Live diagnostics showed 54,237 market inputs processed in 26.5 seconds of simulation plus commit work, while the p95 per-input statistic implied roughly three times slower throughput. A small batch pays an entire checkpoint's fixed cost; multiplying that per-input cost by a burst's queue length can unnecessarily pause admission.

Queue-drain estimates now use observed completed batches with at least 32 inputs, including their database commit time. At least 128 such inputs within five seconds are required. The slower input-weighted service cost from five-second and sixty-second windows determines estimated drain time. Without fresh supporting burst evidence, the original p95 estimate remains the fallback. Both histories retain at most 600 samples.

The half-second queue threshold, 2,000-input hard admission cap, p95 lag limit, processing-cost guard, provider cooldown, stale-telemetry guard, subscription caps, and sustained-health requirements for expansion are unchanged. This improves the estimate, not the allowed resource footprint. It does not increase API rate limits or monitoring limits, weaken synchronization, defer financial persistence, or alter execution.

Monitoring exposes the queue-cost basis, measured service milliseconds, and fresh sample input count for live verification. Tests cover fixed checkpoint overhead, inclusive commit timing, slowdown and recovery, stale/insufficient measurements, all independent hard guards, and bounded history.
