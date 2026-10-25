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

**Coverage:** 8 UTC day(s), 2194 distinct markets.

### Average profit/loss (¢ per contract) by time and bid price

| Minutes remaining | 50–59.9¢ | 60–69.9¢ | 70–79.9¢ | 80–89.9¢ | 90–99.9¢ |
|---:|---:|---:|---:|---:|---:|
| 60m | — | — | — | — | — |
| 45m | +8.00¢ (64) | -5.33¢ (69) | +8.75¢ (88) | +6.38¢ (153) | +2.03¢ (1423) |
| 30m | -5.85¢ (46) | +11.46¢ (54) | +3.57¢ (77) | +5.67¢ (121) | +1.77¢ (1437) |
| 20m | +18.70¢ (44) | +9.69¢ (48) | +2.91¢ (78) | +1.79¢ (112) | +1.50¢ (1639) |
| 15m | +10.85¢ (40) | +2.46¢ (50) | +4.05¢ (61) | +6.49¢ (117) | +1.48¢ (1464) |
| 10m | +4.34¢ (32) | +11.73¢ (51) | +3.34¢ (65) | +4.73¢ (84) | +1.62¢ (1478) |
| 5m | +2.68¢ (19) | +7.80¢ (40) | +16.39¢ (57) | +2.57¢ (87) | +1.50¢ (1724) |
| 3m | -11.42¢ (19) | +12.21¢ (43) | +14.90¢ (40) | +7.17¢ (108) | +1.59¢ (1590) |
| 1m | -11.56¢ (16) | +1.00¢ (26) | +14.33¢ (45) | +12.45¢ (96) | +1.57¢ (1795) |

For example, +4.2¢ (n=36) means an average gain of 4.2 cents per
hypothetically filled contract among 36 sampled markets in that cell.

[Detailed Hourly weather metrics](weather_hourly/REPORT.md)

## Bitcoin (15-minute)

**Coverage:** 19 UTC day(s), 1800 distinct markets.

### Average profit/loss (¢ per contract) by time and bid price

| Minutes remaining | 50–59.9¢ | 60–69.9¢ | 70–79.9¢ | 80–89.9¢ | 90–99.9¢ |
|---:|---:|---:|---:|---:|---:|
| 15m | — | — | — | — | — |
| 10m | +0.44¢ (464) | +1.37¢ (402) | +1.57¢ (447) | +1.05¢ (340) | +2.82¢ (147) |
| 5m | +1.73¢ (217) | -1.58¢ (216) | +0.85¢ (268) | -1.91¢ (353) | +0.09¢ (746) |
| 3m | +1.25¢ (141) | -4.54¢ (170) | -6.83¢ (195) | +0.60¢ (252) | +0.54¢ (1042) |
| 1m | +2.93¢ (45) | -2.77¢ (57) | +11.37¢ (56) | +4.21¢ (109) | +0.12¢ (1533) |

For example, +4.2¢ (n=36) means an average gain of 4.2 cents per
hypothetically filled contract among 36 sampled markets in that cell.

[Detailed Bitcoin (15-minute) metrics](btc15m/REPORT.md)

## Ethereum (15-minute)

**Coverage:** 12 UTC day(s), 1136 distinct markets.

### Average profit/loss (¢ per contract) by time and bid price

| Minutes remaining | 50–59.9¢ | 60–69.9¢ | 70–79.9¢ | 80–89.9¢ | 90–99.9¢ |
|---:|---:|---:|---:|---:|---:|
| 15m | — | — | — | — | — |
| 10m | -0.54¢ (246) | -1.24¢ (250) | +1.65¢ (276) | -1.47¢ (212) | +1.30¢ (151) |
| 5m | +7.06¢ (120) | +4.36¢ (129) | +4.64¢ (159) | +1.92¢ (212) | +0.54¢ (516) |
| 3m | +4.16¢ (86) | +0.83¢ (83) | -1.31¢ (98) | +4.10¢ (155) | +0.78¢ (712) |
| 1m | +15.75¢ (20) | +17.36¢ (28) | +9.00¢ (26) | -6.06¢ (52) | +0.43¢ (1010) |

For example, +4.2¢ (n=36) means an average gain of 4.2 cents per
hypothetically filled contract among 36 sampled markets in that cell.

[Detailed Ethereum (15-minute) metrics](eth15m/REPORT.md)

## Research cautions
- These are simulated maker bids, NOT verified trades or fills.
- Different entry-time rows can reflect the same underlying contract.
- Hourly weather pools Weather Index and single-station contracts; see the weather details for coverage.
- A dash indicates no observations, not a loss.
- The report is preliminary until we collect multiple days and study maker fill likelihood.
