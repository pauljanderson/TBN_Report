# VZ breakout amount and time-to-retest vs PnL / Ann ROR

Research only. Same rw126 DualPaul78 closed trades as the OC-overlap study (N=5313, prior to the rw63 cut).

## Verdict

**You already measure both. Neither is a usable continuous ranking filter.** Spearman vs PnL is ~0 for time and run-up, and only **+0.025** for break-bar distance.

What the **buckets** add:

- **Time:** 1–63 days after the break all look similar (~2.7–3.1% avg PnL, ~66–70% book Ann ROR). **64–126 days is worse** (1.93% / 41% Ann ROR; OOS 2.57% / 70% vs 5–6% / 165–235% earlier). That group cut is exactly `retest_window=63`. Inside the 63-day window, more timing precision does not help.
- **Amount:** tiny clears (`<0.25%` beyond `zone.hi`) are a weaker group (1.57% / 35% Ann ROR). Clears `≥3%` are better on *means* (3.93% / 106%; OOS 8.0% / 337%). Rank correlation is still |r|≲0.04 — a few fat winners, not a sort key. Optional one-knob AB (drop `<0.25%` or require `≥3%`) only if you want to spend a hypothesis slot; not an adopt from this table.
- **Run-up before retest:** same pattern as amount (Q4 mean > Q1, Spearman 0). Do not add it as a strength score.
- **Joint:** `early + large run-up` is the one cell that pops (FULL 5.07% / 136% Ann ROR; OOS N=114 at 9.5%). That is two knobs at once — observation only, not a filter proposal.

## What was measured

- **Time:** `bars_after_break` — trading bars from upside break close to fill (next-open, so includes T+1).
- **Amount (break bar):** `break_dist_pct` / `break_atr_mult` — how far the break close cleared `zone.hi`.
- **Amount (run-up):** `ext_pct` — max high from the break bar through the signal bar, vs `zone.hi`. Known by signal close; no look-ahead.

## Spearman

| Feature | vs PnL% | vs trade Ann ROR | vs R |
|---|---|---|---|
| bars_after_break (time) | -0.002 (p=0.912, N=5313) | -0.012 (p=0.393, N=5313) | -0.004 (p=0.754, N=5313) |
| break_dist_pct (amount) | +0.025 (p=0.071, N=5313) | +0.034 (p=0.015, N=5313) | +0.038 (p=0.006, N=5313) |
| break_atr_mult | +0.022 (p=0.104, N=5313) | +0.025 (p=0.072, N=5313) | +0.035 (p=0.010, N=5313) |
| ext_pct (run-up) | -0.000 (p=0.993, N=5313) | +0.011 (p=0.402, N=5313) | +0.017 (p=0.211, N=5313) |
| ext_atr | -0.012 (p=0.399, N=5280) | -0.006 (p=0.661, N=5280) | +0.008 (p=0.573, N=5280) |

Within-symbol mean Spearman vs PnL: time -0.003 · run-up +0.011 · break-bar +0.034.

## Time buckets

### FULL

| bucket | N | Win% | Avg PnL% | Med PnL% | Book Ann ROR% |
|---|---:|---:|---:|---:|---:|
| 1-5 | 1806 | 52.4% | 3.08 | 1.27 | 66.25 |
| 6-21 | 1888 | 49.4% | 2.65 | -0.45 | 66.51 |
| 22-63 | 1119 | 50.8% | 2.85 | 0.46 | 69.73 |
| 64-126 | 495 | 49.7% | 1.93 | -0.49 | 40.55 |
| 127+ | 5 | 40.0% | -3.49 | -7.53 | -55.07 |

### OOS

| bucket | N | Win% | Avg PnL% | Med PnL% | Book Ann ROR% |
|---|---:|---:|---:|---:|---:|
| 1-5 | 281 | 56.6% | 5.09 | 4.29 | 164.77 |
| 6-21 | 316 | 65.8% | 6.23 | 5.93 | 235.25 |
| 22-63 | 178 | 57.9% | 4.52 | 4.09 | 134.14 |
| 64-126 | 51 | 51.0% | 2.57 | 0.39 | 70.27 |
| 127+ | 1 | 0.0% | -12.14 | -12.14 | -96.57 |

## Amount buckets (break-bar close vs zone.hi)

### FULL

| bucket | N | Win% | Avg PnL% | Med PnL% | Book Ann ROR% |
|---|---:|---:|---:|---:|---:|
| <0.25% | 677 | 46.2% | 1.57 | -1.58 | 34.98 |
| 0.25-1% | 1473 | 51.5% | 2.34 | 0.75 | 49.96 |
| 1-3% | 1730 | 49.9% | 2.62 | -0.02 | 59.46 |
| >=3% | 1433 | 52.9% | 3.93 | 1.66 | 105.79 |

### OOS

| bucket | N | Win% | Avg PnL% | Med PnL% | Book Ann ROR% |
|---|---:|---:|---:|---:|---:|
| <0.25% | 91 | 50.5% | 2.69 | 0.51 | 74.71 |
| 0.25-1% | 226 | 65.0% | 5.61 | 5.89 | 197.82 |
| 1-3% | 307 | 55.0% | 3.85 | 2.96 | 110.60 |
| >=3% | 203 | 66.0% | 8.01 | 8.49 | 337.06 |

## Run-up quartiles (`ext_pct`)

### FULL

| quartile | N | Win% | Avg PnL% | Med PnL% | Book Ann ROR% |
|---|---:|---:|---:|---:|---:|
| Q1 low | 1329 | 51.0% | 2.01 | 0.56 | 40.21 |
| Q2 | 1328 | 48.9% | 2.04 | -0.58 | 47.70 |
| Q3 | 1328 | 51.2% | 3.03 | 0.73 | 73.30 |
| Q4 high | 1328 | 51.7% | 3.97 | 1.21 | 103.86 |

### OOS

| quartile | N | Win% | Avg PnL% | Med PnL% | Book Ann ROR% |
|---|---:|---:|---:|---:|---:|
| Q1 low | 207 | 58.9% | 3.55 | 3.37 | 102.23 |
| Q2 | 207 | 58.9% | 4.93 | 5.60 | 156.08 |
| Q3 | 206 | 61.2% | 5.37 | 5.40 | 184.46 |
| Q4 high | 207 | 60.9% | 7.05 | 5.32 | 274.99 |

## Joint median split (time × run-up)

| bucket | N | Win% | Avg PnL% | Med PnL% | Book Ann ROR% |
|---|---:|---:|---:|---:|---:|
| early / small | 2011 | 50.5% | 2.13 | 0.26 | 45.11 |
| early / large | 779 | 52.6% | 5.07 | 1.90 | 135.98 |
| late / small | 646 | 48.3% | 1.70 | -0.69 | 38.80 |
| late / large | 1877 | 51.0% | 2.85 | 0.55 | 69.58 |

### OOS 2×2

| bucket | N | Win% | Avg PnL% | Med PnL% | Book Ann ROR% |
|---|---:|---:|---:|---:|---:|
| early / small | 309 | 56.6% | 4.16 | 3.53 | 129.27 |
| early / large | 114 | 64.9% | 9.50 | 11.40 | 547.94 |
| late / small | 105 | 65.7% | 4.48 | 5.48 | 125.04 |
| late / large | 299 | 59.5% | 4.96 | 4.24 | 155.29 |

## Reproduce

```
python tools/vz_breakout_amt_time.py
```
