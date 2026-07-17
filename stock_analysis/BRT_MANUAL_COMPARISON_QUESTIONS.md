# BRT vs Manual Results — Comparison & Questions for Review

**Purpose:** Identify differences between our BRT backtest and the manual/spreadsheet results. Grouped by type with examples and questions for your brother.

---

## 1. MISSING TRADES (Manual has, we don’t)

These are trades in the manual run that we do not take. We often flag them as **short candidates** (6th touch with close ≤ zone).

| Stock | Manual Entry | Manual Exit | Manual P&L | Our Status | Question |
|-------|--------------|-------------|------------|------------|----------|
| **AMZN** | 2/28/2022 $152.73 | 3/7/2022 $140.89 | -$3,681 LOSS | Short candidate 2/28 (close 153.56 ≤ zone 154.45) | Are you taking matured-below-zone as longs? Or different zone/confirmation logic? |
| **AMZN** | 4/19/2022 $157.60 | 4/26/2022 $141.55 | -$4,838 LOSS | Short candidate 4/19 (close 158.12 ≤ zone 158.65) | Same question. |
| **AMZN** | 4/9/2025 $185.44 | 10/31/2025 $250.10 | +$16,563 WIN | Short candidate 4/9 (close 191.10 ≤ zone 192.65) | Same — we flag as short; you take as long. |
| **GOOGL** | 5/4/2022 $120.20 | 5/20/2022 $107.52 | -$5,010 LOSS | Short candidate 5/4 (close 122.26 ≤ zone 122.85) | Same — matured below zone, we skip. |
| **GOOGL** | 8/21/2023 $128.51 | 4/26/2024 $174.37 | +$16,951 WIN | No 8/21 maturity in our run | Different 6th touch date or zone? Our closest is 7/21/2023. |
| **GOOGL** | 7/9/2025 $175.63 | 9/3/2025 $226.56 | +$13,775 WIN | We have 5/8/2025 entry (close date) | Is 7/9 your 6th-touch or close-above date? We have 5/7 6th touch, 5/8 entry. |
| **MSFT** | 10/26/2022 $231.04 | 11/3/2022 $214.88 | -$3,323 LOSS | Short candidate 10/25 (close 250.66 ≤ zone 251.04) | Are 10/25–10/26 same setup? We flag 10/25 as short. |
| **TSLA** | 10/19/2022 $208.28 | 10/20/2022 $203.41 | -$1,111 LOSS | Short candidate 10/18 (close 220.19 ≤ zone 229.82) | Same — we skip; you take. 1-day hold. |

**Total manual P&L on these missing trades:** About -$1,394 (losses and wins net).

---

## 2. EXTRA TRADES (We have, manual doesn’t)

| Stock | Our Entry | Our Exit | Our P&L | Question |
|-------|-----------|----------|---------|----------|
| **AAPL** | 11/30/2022 $141.40 | 12/20/2022 STOP | -$3,402 | We get a 7th-touch maturity 11/29. Do you block new entries while the 10/3 trade is still open? |
| **MSFT** | 11/2/2020 $204.29 | 6/22/2021 TARGET | +$13,775 | Trade before your manual start? Or filtered out? |
| **TSLA** | 6/6/2025 $298.83 | 9/12/2025 TARGET | +$13,775 | We have 6/5 6th touch, 6/6 entry. Manual has no 6/2025 trade. Different zone or 6th touch? |
| **TSLA** | 1/21/2026 $421.66 | 2/5/2026 STOP | -$3,350 | Manual shows 1/21 entry — so this one matches. |

**Net impact of true extras:** AAPL -$3,402; MSFT +$13,775; TSLA one match, one potential extra.

---

## 3. ENTRY DATE SHIFTS (1–15 days)

| Stock | Manual Entry | Our Entry | Difference | Question |
|-------|--------------|-----------|------------|----------|
| **AAPL** | 5/23/2025 | 5/8/2025 | We enter 15 days earlier | Same 6th touch? We have 5/7 6th touch. Do you wait for a later close-above? |
| **NVDA** | 5/15/2023 | 5/15/2023 | Same date | Entry price differs ($28.84 vs $28.51) — see next section. |
| **NVDA** | 5/23/2025 | 5/27/2025 | We enter 4 days later | We have 5/23 6th touch; you enter 5/23. Do you use next-open after 6th touch when close>zone same day? We use 5/27 (next Mon after Fri 5/23). |
| **AAPL** | 3/8, 12/28, 2/1, 9/28 | 3/9, 12/29, 2/2, 9/29 | 1-day shift (next-day convention) | Same-bar vs next-bar interpretation for entry? |
| **AMZN** | 11/21/2025 | 11/24/2025 | 3 days (Fri→Mon) | Weekend: we use next trading day. Same for you? |
| **GOOGL** | 7/9/2025 | 5/8/2025 | Different months | Likely different 6th touch or zone — needs trace. |

---

## 4. ENTRY PRICE DIFFERENCES

| Stock | Entry Date | Manual $ | Ours $ | Diff | Est. $ Impact (on same exit) |
|-------|------------|----------|--------|-----|------------------------------|
| **NVDA** | 5/15/2023 | 28.84 | 28.51 | -0.33 | ~$1,200 more profit for us (lower entry) |
| **AAPL** | 5/13/2022 | 145.55 | 144.59 | -0.96 | ~$50 |
| **AAPL** | 9/9/2022 | 159.59 | 155.47 | -4.12 | ~$250 |
| **AMZN** | 4/23/2021 | 167.40 | 165.96 | -1.44 | ~$75 |
| **AMZN** | 4/13/2023 | 102.07 | 98.95 | -3.12 | ~$400 |
| **META** | 1/15/2021 | 256.90 | 247.90 | -9.00 | ~$1,700 |
| **META** | 12/6/2021 | 321.57 | 308.13 | -13.44 | ~$2,000 |
| **META** | 4/22/2025 | 528.53 | 491.87 | -36.66 | ~$2,600 |
| **NFLX** | 6/17/2019 | 35.56 | 34.27 | -1.29 | ~$50 |

**Likely cause:** Different data (open prices) or “entry bar” definition (e.g., next open after close-above).

---

## 5. EXIT PRICE / EXIT TYPE DIFFERENCES

| Stock | Entry | Manual Exit | Our Exit | Manual P&L | Our P&L | Question |
|-------|-------|-------------|----------|------------|---------|----------|
| **NVDA** | 1/28 | $12.10 STOP | $12.11 STOP | -$3,542 | -$3,257 | Tiny data diff. Same rule. |
| **AAPL** | 10/3 | 12/28 $128.60 (86 days) | 10/13 $134.74 STOP (9 days) | -$5,380 | -$3,371 | We stop out much earlier. Different stop or data? |
| **META** | 12/6 | 2/3 $286.12 | 2/3 $244.65 GAP_DOWN | -$5,236 | -$9,786 | Same date, very different exit price. Data or fill convention? |
| **TSLA** | 7/24 | 8/14 $237.35 STOP | 8/7 $247.51 STOP | -$6,109 | -$4,337 | We exit 1 week earlier. Different stop level? |
| **TSLA** | 12/13 | 1/16 $213.14 GAP_DOWN | 1/12 $220.08 GAP_DOWN | -$5,530 | -$4,163 | We exit 4 days earlier. |
| **AMZN** | 4/13 | 7/3 $131.67 GAP_UP | 6/13 $128.12 GAP_UP | +$13,775 | +$14,003 | Different exit date/price; both GAP_UP. |

---

## 6. SUMMARY BY MONEY IMPACT

**Largest P&L gaps:**

1. **META 12/6 trade:** Manual -$5,236 vs Ours -$4,337 (we lose more; exit price $244 vs $286).
2. **AAPL 10/3 trade:** Manual -$5,380 (held 86 days) vs Ours -$3,371 (stopped in 9 days) — we exit earlier.
3. **AMZN 4/9/2025:** Manual +$16,563, we miss it (short candidate).
4. **GOOGL 8/21/2023:** Manual +$16,951, we have no equivalent trade.
5. **MSFT 11/2/2020:** We have +$13,775; manual may not include this period.

---

## 7. CONSOLIDATED QUESTIONS FOR YOUR BROTHER

1. **Matured-below-zone (short candidates):** Do you ever take these as longs? We skip them and flag as potential shorts.
2. **One trade at a time:** When the 10/3 AAPL trade is open, do you block the 11/30 entry we take?
3. **Entry bar definition:** For “entry = next open after close-above,” do you use the next calendar day or next trading day? (Affects Fri→Mon cases.)
4. **Data source:** Which vendor/feed do you use? We see consistent $0.01–$0.10 differences on OHLC.
5. **Stop reference:** Confirm we use `Low[entry_bar]` for stop, not trigger bar.
6. **NVDA 5/15 vs 5/16:** You use 5/16 open ($28.84); we use 5/15 open ($28.51). Is your close-above on 5/15 and entry on 5/16?
