# BRT vs Manual Trade Comparison (Fuzzy Match)

**BRT file:** drive/BRT_Closed_260302121838.csv
**Manual list:** (provided trades)
*Fuzzy matching: same symbol + exit_date, entry dates within 2 days*

---

## Summary

| Group | Count |
|-------|-------|
| Matched (fuzzy or exact) | 15 |
| - Exact match (same entry date) | 0 |
| - Fuzzy match (entry date off 1-2 days) | 15 |
| - Matched but with price/other differences | 3 |
| - Matched, no material difference | 12 |
| BRT only (symbols in manual list) | 6 |
| Manual only | 7 |

---

## 1. In BRT only (symbols that appear in manual list)

Trades in BRT with no fuzzy match in manual:

- **AAPL** Entry 20220912 @ 159.59 -> Exit 20220929 @ 142.6 (-10.64%, 17d)
- **AAPL** Entry 20250527 @ 198.3 -> Exit 20250922 @ 255.81 (29.00%, 118d)
- **AMZN** Entry 20220301 @ 152.73 -> Exit 20220307 @ 140.89 (-7.75%, 6d)
- **MSFT** Entry 20230821 @ 317.93 -> Exit 20240130 @ 412.26 (29.67%, 162d)
- **NVDA** Entry 20250527 @ 134.15 -> Exit 20250717 @ 173.05 (29.00%, 51d)
- **TSLA** Entry 20220621 @ 224.6 -> Exit 20220729 @ 289.74 (29.00%, 38d)

---

## 2. In Manual only

Trades in manual with no fuzzy match in BRT:

- **AAPL** Entry 20220909 @ 159.59 -> Exit 20220929 @ 144.54 (-9.43%, 20d)
- **AAPL** Entry 20250523 @ 198.3 -> Exit 20250922 @ 255.81 (29.00%, 122d)
- **MSFT** Entry 20230525 @ 324.02 -> Exit 20240209 @ 417.99 (29.00%, 260d)
- **NVDA** Entry 20250523 @ 134.15 -> Exit 20250717 @ 173.05 (29.00%, 55d)
- **TSLA** Entry 20220224 @ 269.74 -> Exit 20220328 @ 355.03 (31.62%, 32d)
- **TSLA** Entry 20220617 @ 224.6 -> Exit 20220729 @ 289.73 (29.00%, 42d)
- **TSLA** Entry 20230724 @ 272.38 -> Exit 20230814 @ 237.35 (-12.86%, 21d)

---

## 3. Matched but with differences

Matched trades with price/exit/days differences:

- **MSFT** BRT entry 20221209 / manual entry 20221208
  - exit_price: BRT=226.22 manual=227.02
  - entry_date: BRT=20221209 manual=20221208 (next-open convention)
- **TSLA** BRT entry 20251024 / manual entry 20251023
  - exit_price: BRT=386.3 manual=386.58
  - entry_date: BRT=20251024 manual=20251023 (next-open convention)
- **TSLA** BRT entry 20260122 / manual entry 20260121
  - exit_price: BRT=389.89 manual=391.93
  - entry_date: BRT=20260122 manual=20260121 (next-open convention)

---

## 4. Matched, no material difference

*12 trades* (entry date may differ by 1-2 days; prices/exit align)
