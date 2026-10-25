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

**Coverage:** 15 UTC day(s), 1424 distinct markets.

### Average profit/loss (¢ per contract) by time and bid price

| Minutes remaining | 50–59.9¢ | 60–69.9¢ | 70–79.9¢ | 80–89.9¢ | 90–99.9¢ |
|---:|---:|---:|---:|---:|---:|
| 15m | — | — | — | — | — |
| 10m | +0.56¢ (367) | -1.64¢ (321) | +2.29¢ (362) | +2.43¢ (276) | +3.88¢ (98) |
| 5m | +2.40¢ (172) | -0.93¢ (173) | -1.71¢ (209) | -2.16¢ (289) | +0.20¢ (581) |
| 3m | -1.55¢ (120) | -6.03¢ (128) | -7.78¢ (156) | +1.07¢ (211) | +0.72¢ (809) |
| 1m | +4.22¢ (37) | -3.37¢ (46) | +8.79¢ (47) | +3.98¢ (90) | +0.02¢ (1204) |

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
