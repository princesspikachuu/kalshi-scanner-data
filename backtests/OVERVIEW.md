# Kalshi Pocket Analytics — average maker P/L by entry time and price

**Main metric:** average simulated profit/loss per contract, in cents.
Each cell pools all hourly weather contracts (regardless of city), or
all Bitcoin or Ethereum contracts within the specified time and purchase-price range.
Each cell shows the average profit/loss followed by the number of markets (n).

**These are not executed trades.** We assume a maker buy fills at the
historical best bid. Fees and fill probability aren't included.
Each entry time reuses some of the same underlying contracts: do not
add sample counts across time rows.

## Hourly weather

**Coverage:** 1 UTC day(s), 100 distinct markets.

### Average profit/loss (¢ per contract) by time and bid price

| Minutes remaining | 50–59.9¢ | 60–69.9¢ | 70–79.9¢ | 80–89.9¢ | 90–99.9¢ |
|---:|---:|---:|---:|---:|---:|
| 60m | — | — | — | — | — |
| 45m | +46.25¢ (4) | +11.00¢ (4) | +24.67¢ (3) | +2.88¢ (8) | +2.63¢ (65) |
| 30m | -20.33¢ (3) | +34.67¢ (3) | +26.00¢ (1) | +16.50¢ (6) | +2.24¢ (71) |
| 20m | -1.00¢ (2) | +32.50¢ (2) | +25.00¢ (2) | +14.50¢ (6) | +1.95¢ (76) |
| 15m | +50.00¢ (1) | -66.00¢ (1) | +23.00¢ (1) | +16.00¢ (3) | +2.19¢ (74) |
| 10m | -7.00¢ (2) | +31.00¢ (1) | +25.00¢ (2) | +15.40¢ (5) | +1.90¢ (71) |
| 5m | -58.00¢ (2) | +35.00¢ (2) | — | -4.40¢ (5) | +1.65¢ (91) |
| 3m | -51.00¢ (1) | -13.50¢ (2) | +29.00¢ (1) | -2.80¢ (5) | +1.55¢ (82) |
| 1m | — | -63.00¢ (1) | -40.67¢ (3) | +17.75¢ (4) | +1.61¢ (89) |

For example, +4.2¢ (n=36) means an average gain of 4.2 cents per
hypothetically filled contract among 36 sampled markets in that cell.

[Detailed Hourly weather metrics](weather_hourly/REPORT.md)

## Bitcoin (15-minute)

**Coverage:** 8 UTC day(s), 760 distinct markets.

### Average profit/loss (¢ per contract) by time and bid price

| Minutes remaining | 50–59.9¢ | 60–69.9¢ | 70–79.9¢ | 80–89.9¢ | 90–99.9¢ |
|---:|---:|---:|---:|---:|---:|
| 15m | — | — | — | — | — |
| 10m | +2.43¢ (199) | -1.52¢ (170) | +2.86¢ (195) | +3.45¢ (138) | +3.49¢ (58) |
| 5m | +11.99¢ (93) | +3.41¢ (87) | -2.74¢ (117) | -1.44¢ (160) | +0.44¢ (303) |
| 3m | +4.13¢ (70) | -10.35¢ (72) | -2.16¢ (80) | -1.01¢ (113) | +0.49¢ (425) |
| 1m | -2.74¢ (19) | -0.18¢ (22) | +3.78¢ (18) | +4.79¢ (47) | -0.46¢ (654) |

For example, +4.2¢ (n=36) means an average gain of 4.2 cents per
hypothetically filled contract among 36 sampled markets in that cell.

[Detailed Bitcoin (15-minute) metrics](btc15m/REPORT.md)

## Ethereum (15-minute)

**Coverage:** 0 UTC day(s), 0 distinct markets.

### Average profit/loss (¢ per contract) by time and bid price

| Minutes remaining | 50–59.9¢ | 60–69.9¢ | 70–79.9¢ | 80–89.9¢ | 90–99.9¢ |
|---:|---:|---:|---:|---:|---:|
| 15m | — | — | — | — | — |
| 10m | — | — | — | — | — |
| 5m | — | — | — | — | — |
| 3m | — | — | — | — | — |
| 1m | — | — | — | — | — |

No historical observations collected yet for this market type.

## Research cautions
- These are simulated maker bids, NOT verified trades or fills.
- Different entry-time rows can reflect the same underlying contract.
- Hourly weather pools Weather Index and single-station contracts; see the weather details for coverage.
- A dash indicates no observations, not a loss.
- The report is preliminary until we collect multiple days and study maker fill likelihood.
