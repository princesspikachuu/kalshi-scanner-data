# Synthetic report memory acceptance

Run explicitly, without provider/DB/archive access:

```
python -m services.research.benchmark --days 30
python -m services.research.benchmark --days 366
```

Local Python 3.12, 96 synthetic BTC markets/day, 15 minute bars/market,
five requested entry slots. These are synthetic measurements, not Render
CPU/database acceptance or a guarantee for denser/multi-series categories.

| Case | Markets | Observations | Seconds | Peak RSS KiB | Observation bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline 30 days | 2880 | 14400 | 1.831 | 77368 | 5823691 |
| Baseline 330 days | 31680 | 158400 | 19.617 | 465264 | 64531471 |
| Optimized 366 days | 35136 | 175680 | 19.272 | 426880 | 71588443 |

366-day SHA256: `3e00fae457b948e2241d63fb3badb6976c1c2ab11a70aceaa1e6459b94fbd365`.
30-day baseline/optimized SHA256 remains
`6daadcd23109f7701502451307f1bdd5b98f288ded888a9829040e9f766941ba`.

Reports retain every input observation, all checkpoint coverage counts, original
hold denominators and the pinned exit checkpoint. Compact mode omits diagnostic
bins discarded by report publication, while preserving empty policy cells.
Canonical fingerprint hashing uses existing serialized JSON without a second
full observation serialization. Category publication avoids reparsing that JSON.
Observation inserts use 1000-row batches in one transaction: a failure in any
batch rolls back the entire immutable result. No query-time model recomputation.

Explicit limits: 250000 requested entries, 1000000 path bars, 96 MiB combined
serialized result/observations, 3661 source datasets, 10000 category intervals.
Crossing a limit fails rather than sampling. Existing 512 MiB worker has limited
headroom; SDK/runtime overhead and live RSS remain to measure. Broader categories
and multiple years may require explicit partitioned reports; this is not solved
by these measurements. No compute/DB upgrade or new resource was provisioned.
