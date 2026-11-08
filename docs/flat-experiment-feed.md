# Flat experiment feed coalescing

Only the two new Momentum and Liquidity Dislocation portfolios reuse their primary scalper's already validated incoming book/trade frames while entirely flat. Subscription sequences and clock advance are retained. Before an entry evaluation, the latest causal public depth is copied into independent books. Hypothetical depth consumption stays local. Public prints are already deduplicated in the shared causal tape.

An order or position disables coalescing immediately, so all arrivals, queue updates, partial fills and protective exits use every event. A missing or invalid authoritative source fails closed and requires a verified replacement; stale depth is never patched with a delta after skipped frames. Existing Mean Reversion, Fixed, Grid, High Probability and other strategy execution paths remain unchanged. There are no extra subscriptions, REST requests, capital or fee changes.

Tests cover detached depth, no look-ahead at delayed IOC arrival, partial liquidity and fees, active-order processing, sequence gaps/recovery, local depth overlays, and unchanged existing experiments. paper_monitoring_capacity includes cumulative coalesced_inputs for operational cost comparison.
