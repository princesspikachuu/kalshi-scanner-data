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

**Coverage:** 15 UTC day(s), 4202 distinct markets.

### Average profit/loss (¢ per contract) by time and bid price

| Minutes remaining | 50–59.9¢ | 60–69.9¢ | 70–79.9¢ | 80–89.9¢ | 90–99.9¢ |
|---:|---:|---:|---:|---:|---:|
| 60m | — | — | — | — | — |
| 45m | +10.41¢ (122) | -0.84¢ (144) | +2.86¢ (168) | +6.46¢ (281) | +2.25¢ (2646) |
| 30m | +2.11¢ (98) | +7.02¢ (102) | +2.48¢ (147) | +4.95¢ (242) | +2.06¢ (2520) |
| 20m | +11.79¢ (86) | +2.07¢ (94) | +3.40¢ (134) | +1.41¢ (206) | +1.80¢ (2875) |
| 15m | +3.82¢ (84) | +3.34¢ (89) | +3.04¢ (113) | +3.57¢ (202) | +1.85¢ (2686) |
| 10m | +1.37¢ (67) | +10.69¢ (89) | +0.94¢ (116) | +2.72¢ (161) | +1.92¢ (2607) |
| 5m | +0.55¢ (47) | +7.86¢ (76) | +8.43¢ (108) | +1.62¢ (156) | +1.87¢ (2924) |
| 3m | +0.53¢ (40) | +11.38¢ (80) | +6.47¢ (86) | +6.48¢ (185) | +1.96¢ (2881) |
| 1m | +6.85¢ (39) | +7.09¢ (57) | +14.56¢ (93) | +9.02¢ (199) | +2.32¢ (3381) |

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

**Coverage:** 21 UTC day(s), 6300 distinct markets.

### Average profit/loss (¢ per contract) by time and bid price

| Minutes remaining | 50–59.9¢ | 60–69.9¢ | 70–79.9¢ | 80–89.9¢ | 90–99.9¢ |
|---:|---:|---:|---:|---:|---:|
| 15m | — | — | — | — | — |
| 10m | +0.78¢ (1379) | -0.80¢ (1354) | +1.84¢ (1391) | +0.71¢ (1413) | +1.43¢ (721) |
| 5m | +3.06¢ (670) | +3.53¢ (745) | +0.89¢ (856) | +1.88¢ (1133) | +1.25¢ (2859) |
| 3m | +3.86¢ (472) | +0.46¢ (478) | +1.38¢ (546) | +2.43¢ (823) | +0.37¢ (3958) |
| 1m | -1.81¢ (154) | +2.09¢ (156) | +0.29¢ (200) | +0.19¢ (316) | +0.43¢ (5456) |

For example, +4.2¢ (n=36) means an average gain of 4.2 cents per
hypothetically filled contract among 36 sampled markets in that cell.

[Detailed Crypto (pooled 15-minute) metrics](crypto15m/REPORT.md)

## Sports (game/match winners)

**Coverage:** 35 UTC day(s), 3895 distinct markets.

### Average profit/loss (¢ per contract) by time and bid price

| Minutes remaining | 50–59.9¢ | 60–69.9¢ | 70–79.9¢ | 80–89.9¢ | 90–99.9¢ |
|---:|---:|---:|---:|---:|---:|
| 360m | +1.49¢ (1063) | -0.02¢ (732) | -2.90¢ (477) | -1.55¢ (299) | +0.63¢ (259) |
| 180m | +4.73¢ (1184) | -3.15¢ (887) | +1.09¢ (588) | -2.73¢ (404) | +1.32¢ (366) |
| 120m | -2.38¢ (861) | +2.04¢ (850) | -0.02¢ (667) | -5.34¢ (584) | +0.54¢ (579) |
| 60m | -0.11¢ (615) | +4.42¢ (608) | +1.35¢ (678) | +4.40¢ (646) | +1.94¢ (1064) |
| 30m | +4.07¢ (473) | +10.17¢ (417) | +10.56¢ (504) | +7.90¢ (595) | +2.85¢ (1596) |
| 15m | +14.42¢ (315) | +12.84¢ (249) | +18.31¢ (333) | +12.63¢ (532) | +2.38¢ (2140) |
| 5m | +16.04¢ (124) | +24.70¢ (86) | +19.40¢ (141) | +14.15¢ (335) | +2.10¢ (2765) |

For example, +4.2¢ (n=36) means an average gain of 4.2 cents per
hypothetically filled contract among 36 sampled markets in that cell.

[Detailed Sports (game/match winners) metrics](sports_game/REPORT.md)

## Daily weather

**Coverage:** 0 UTC day(s), 0 distinct markets.

### Average profit/loss (¢ per contract) by time and bid price

| Minutes remaining | 50–59.9¢ | 60–69.9¢ | 70–79.9¢ | 80–89.9¢ | 90–99.9¢ |
|---:|---:|---:|---:|---:|---:|
| 360m | — | — | — | — | — |
| 180m | — | — | — | — | — |
| 120m | — | — | — | — | — |
| 60m | — | — | — | — | — |
| 30m | — | — | — | — | — |
| 15m | — | — | — | — | — |
| 5m | — | — | — | — | — |

No historical observations collected yet for this market type.

## Daily financial indices

**Coverage:** 0 UTC day(s), 0 distinct markets.

### Average profit/loss (¢ per contract) by time and bid price

| Minutes remaining | 50–59.9¢ | 60–69.9¢ | 70–79.9¢ | 80–89.9¢ | 90–99.9¢ |
|---:|---:|---:|---:|---:|---:|
| 360m | — | — | — | — | — |
| 180m | — | — | — | — | — |
| 120m | — | — | — | — | — |
| 60m | — | — | — | — | — |
| 30m | — | — | — | — | — |
| 15m | — | — | — | — | — |
| 5m | — | — | — | — | — |

No historical observations collected yet for this market type.

## Research cautions
- These are simulated maker bids, NOT verified trades or fills.
- Different entry-time rows can reflect the same underlying contract.
- Hourly weather pools Weather Index and single-station contracts; see the weather details for coverage.
- A dash indicates no observations, not a loss.
- The report is preliminary until we collect multiple days and study maker fill likelihood.
