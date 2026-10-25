# Kalshi Pocket Analytics — Average maker profit/loss by time and price

**Each cell is average hypothetical profit/loss in cents per contract**, then the number of sampled markets in parentheses. All hourly weather markets are pooled; Bitcoin and Ethereum are separate.

Only historical maker bids are used. The results assume orders filled at the displayed bid and **exclude fees**. These are simulations, not actual trading profits. The same contracts can appear at multiple entry times, so do not add counts across rows.

## Hourly weather

**Coverage:** 1 UTC day(s), 100 unique contracts.

| Minutes remaining | 50–59.9¢ | 60–69.9¢ | 70–79.9¢ | 80–89.9¢ | 90–99.9¢ |
|---:|---:|---:|---:|---:|---:|
| 60m | — | — | — | — | — |
| 45m | +46.25¢ (n=4) | +11.00¢ (n=4) | +24.67¢ (n=3) | +2.87¢ (n=8) | +2.63¢ (n=65) |
| 30m | -20.33¢ (n=3) | +34.67¢ (n=3) | +26.00¢ (n=1) | +16.50¢ (n=6) | +2.24¢ (n=71) |
| 20m | -1.00¢ (n=2) | +32.50¢ (n=2) | +25.00¢ (n=2) | +14.50¢ (n=6) | +1.95¢ (n=76) |
| 15m | +50.00¢ (n=1) | -66.00¢ (n=1) | +23.00¢ (n=1) | +16.00¢ (n=3) | +2.19¢ (n=74) |
| 10m | -7.00¢ (n=2) | +31.00¢ (n=1) | +25.00¢ (n=2) | +15.40¢ (n=5) | +1.90¢ (n=71) |
| 5m | -58.00¢ (n=2) | +35.00¢ (n=2) | — | -4.40¢ (n=5) | +1.65¢ (n=91) |
| 3m | -51.00¢ (n=1) | -13.50¢ (n=2) | +29.00¢ (n=1) | -2.80¢ (n=5) | +1.55¢ (n=82) |
| 1m | — | -63.00¢ (n=1) | -40.67¢ (n=3) | +17.75¢ (n=4) | +1.61¢ (n=89) |

[Full Hourly weather figures](weather_hourly/REPORT.md)

## Bitcoin (15-minute)

**Coverage:** 1 UTC day(s), 96 unique contracts.

| Minutes remaining | 50–59.9¢ | 60–69.9¢ | 70–79.9¢ | 80–89.9¢ | 90–99.9¢ |
|---:|---:|---:|---:|---:|---:|
| 15m | — | — | — | — | — |
| 10m | -9.56¢ (n=27) | +12.53¢ (n=17) | -7.30¢ (n=30) | -16.00¢ (n=13) | +7.02¢ (n=9) |
| 5m | -0.08¢ (n=13) | -3.30¢ (n=10) | -26.87¢ (n=15) | +1.05¢ (n=22) | +4.22¢ (n=36) |
| 3m | +16.40¢ (n=10) | -6.67¢ (n=12) | -6.67¢ (n=9) | -8.15¢ (n=13) | +0.32¢ (n=52) |
| 1m | -57.00¢ (n=1) | +36.00¢ (n=2) | -70.00¢ (n=1) | +0.29¢ (n=7) | +1.05¢ (n=85) |

[Full Bitcoin (15-minute) figures](btc15m/REPORT.md)

## Ethereum (15-minute)

**Coverage:** 0 UTC day(s), 0 unique contracts.

| Minutes remaining | 50–59.9¢ | 60–69.9¢ | 70–79.9¢ | 80–89.9¢ | 90–99.9¢ |
|---:|---:|---:|---:|---:|---:|
| 15m | — | — | — | — | — |
| 10m | — | — | — | — | — |
| 5m | — | — | — | — | — |
| 3m | — | — | — | — | — |
| 1m | — | — | — | — | — |

No observations collected yet.

## How to read these tables

`+4.20¢ (n=36)` means 36 sampled contracts would have earned **4.20¢ on average per contract** assuming every bid filled at the historical quote. Negative values represent losses under the same assumption.

The 15-minute crypto opening observation and 60-minute weather observation may be absent if the historical candle API did not return an eligible quote at that boundary.

**The sample currently covers just October 23, 2026 for available assets**. It is not a reliable historical estimate of real-world maker profits.

