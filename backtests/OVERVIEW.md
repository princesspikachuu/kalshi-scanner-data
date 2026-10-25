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

## Crypto (pooled 15-minute)

**Coverage:** 7 UTC day(s), 2100 distinct markets.

### Average profit/loss (¢ per contract) by time and bid price

| Minutes remaining | 50–59.9¢ | 60–69.9¢ | 70–79.9¢ | 80–89.9¢ | 90–99.9¢ |
|---:|---:|---:|---:|---:|---:|
| 15m | — | — | — | — | — |
| 10m | +4.82¢ (449) | +0.97¢ (473) | +3.45¢ (445) | -2.64¢ (444) | +0.48¢ (275) |
| 5m | +0.55¢ (212) | +1.54¢ (252) | +2.59¢ (295) | +4.90¢ (374) | +1.15¢ (949) |
| 3m | +3.79¢ (162) | -0.71¢ (174) | -2.74¢ (177) | +2.17¢ (269) | -0.10¢ (1308) |
| 1m | -11.41¢ (44) | +8.20¢ (51) | -9.59¢ (69) | +3.39¢ (118) | +0.31¢ (1812) |

For example, +4.2¢ (n=36) means an average gain of 4.2 cents per
hypothetically filled contract among 36 sampled markets in that cell.

[Detailed Crypto (pooled 15-minute) metrics](crypto15m/REPORT.md)

## Sports (game/match winners)

**Coverage:** 7 UTC day(s), 931 distinct markets.

### Average profit/loss (¢ per contract) by time and bid price

| Minutes remaining | 50–59.9¢ | 60–69.9¢ | 70–79.9¢ | 80–89.9¢ | 90–99.9¢ |
|---:|---:|---:|---:|---:|---:|
| 360m | +2.67¢ (248) | -7.81¢ (146) | -13.04¢ (107) | -2.85¢ (55) | +7.63¢ (30) |
| 180m | +2.13¢ (294) | -5.35¢ (207) | +7.12¢ (114) | -4.88¢ (81) | -1.94¢ (49) |
| 120m | -11.41¢ (231) | +4.15¢ (193) | +5.97¢ (155) | -9.66¢ (121) | -1.63¢ (84) |
| 60m | -2.06¢ (166) | -7.04¢ (162) | +7.15¢ (170) | +5.01¢ (157) | +2.49¢ (185) |
| 30m | +1.76¢ (146) | +15.39¢ (114) | +10.18¢ (159) | +3.80¢ (152) | +2.61¢ (295) |
| 15m | +17.69¢ (115) | +13.37¢ (83) | +20.02¢ (92) | +13.17¢ (151) | +3.00¢ (440) |
| 5m | +0.32¢ (37) | +28.57¢ (30) | +24.24¢ (42) | +14.42¢ (100) | +2.56¢ (675) |

For example, +4.2¢ (n=36) means an average gain of 4.2 cents per
hypothetically filled contract among 36 sampled markets in that cell.

[Detailed Sports (game/match winners) metrics](sports_game/REPORT.md)

## Research cautions
- These are simulated maker bids, NOT verified trades or fills.
- Different entry-time rows can reflect the same underlying contract.
- Hourly weather pools Weather Index and single-station contracts; see the weather details for coverage.
- A dash indicates no observations, not a loss.
- The report is preliminary until we collect multiple days and study maker fill likelihood.
