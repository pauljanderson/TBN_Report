# H1 origin rvol ≥4 — broader-universe confirmation

Research only. Frozen rule: `RESEARCH_CANDIDATE_V2` rw126, next_open, `zone_atr05_ts40`, `origin_rvol >= 4.0`. **Do not retune 4.0 on OOS.**

## Verdict: FAIL — gap does not survive outside DualPaul78

PaulTwenty_universe.csv is not in this environment (gitignored); skipped.
Local FullOHLC / DailyRun dump is not in this environment; **SPX500** is the broader-universe proxy.

**DualPaul78:** PASS — DD gap survives — control N=5313 Max DD 38.45% vs H1 N=1655 (31%) Max DD 17.66% (gap 20.79 pp) Calmar 3.93 vs 1.67 OOS N=200 PnL 5.74%.
**SPX500:** HOLD — calmer, gap shrinks — control N=28114 Max DD 39.85% vs H1 N=4897 (17%) Max DD 32.38% (gap 7.47 pp) Calmar 0.95 vs 0.70 OOS N=580 PnL 2.42%.
**SPX_ex_DP78:** FAIL — DD gap gone (clustering) — control N=26533 Max DD 41.70% vs H1 N=4594 (17%) Max DD 36.37% (gap 5.33 pp) Calmar 0.80 vs 0.63 OOS N=543 PnL 2.29%.
**DP78_in_SPX:** FAIL — DD gap gone (clustering) — control N=1581 Max DD 21.81% vs H1 N=303 (19%) Max DD 35.11% (gap -13.30 pp) Calmar 1.76 vs 2.71 OOS N=37 PnL 4.19%.

### What this means

The DualPaul78 ~18% Max DD does **not** travel. On S&P 500, H1 is only ~7pp calmer (39.8% → 32.4%). Take DualPaul78 names out of SPX and the gap is ~5pp (41.7% → 36.4%) — below the 12pp bar. The DualPaul78 names that *are* in SPX actually have **worse** H1 Max DD (21.8% → 35.1%). So the original DD cut lives in the non-SPX DualPaul78 cluster (small/mid, foreign, resource names), not in a general climatic-origin rule.

**Do not promote H1 rvol≥4.** Keep the main sleeve as rw63. Stop papering H1 as a second book.

PASS bar: H1 Max DD at least **12pp** below that universe's rw126 control, WR/Avg R not collapsing, OOS not reversing. DualPaul78's gap was ~21pp (38.5% → 17.7%).

## Setup

Runnable symbols=556 · failed download=3 · closed trades=31846.

| Universe | Arm | Lean | N | WR% | Avg PnL% | Avg R | Book Ann ROR% | Max DD% | Calmar | IS N | IS Max DD% | OOS N | OOS WR% | OOS Avg PnL% | OOS Max DD% |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| DualPaul78 | DualPaul78 CONTROL rw126 | control | 5313 | 50.7% | 2.76 | 0.34 | 64.25 | 38.45 | 1.67 | 4486 | 39.02 | 827 | 60.0% | 5.22 | 5.18 |
| DualPaul78 | DualPaul78 H1 rvol>=4 | PASS — DD gap survives | 1655 | 50.4% | 3.08 | 0.33 | 69.39 | 17.66 | 3.93 | 1455 | 17.67 | 200 | 57.0% | 5.74 | 5.42 |
| SPX500 | SPX500 CONTROL rw126 | control | 28114 | 48.7% | 1.49 | 0.24 | 27.98 | 39.85 | 0.70 | 24451 | 39.78 | 3663 | 47.2% | 1.48 | 16.02 |
| SPX500 | SPX500 H1 rvol>=4 | HOLD — calmer, gap shrinks | 4897 | 50.2% | 1.81 | 0.25 | 30.75 | 32.38 | 0.95 | 4317 | 32.18 | 580 | 52.2% | 2.42 | 10.51 |
| SPX_ex_DP78 | SPX_ex_DP78 CONTROL rw126 | control | 26533 | 48.5% | 1.41 | 0.24 | 26.33 | 41.70 | 0.63 | 23108 | 41.59 | 3425 | 46.2% | 1.24 | 17.06 |
| SPX_ex_DP78 | SPX_ex_DP78 H1 rvol>=4 | FAIL — DD gap gone (clustering) | 4594 | 50.3% | 1.73 | 0.25 | 29.03 | 36.37 | 0.80 | 4051 | 36.12 | 543 | 52.5% | 2.29 | 9.79 |
| DP78_in_SPX | DP78_in_SPX CONTROL rw126 | control | 1581 | 52.5% | 2.81 | 0.36 | 59.02 | 21.81 | 2.71 | 1343 | 22.01 | 238 | 60.9% | 5.01 | 7.56 |
| DP78_in_SPX | DP78_in_SPX H1 rvol>=4 | FAIL — DD gap gone (clustering) | 303 | 49.8% | 3.08 | 0.20 | 61.68 | 35.11 | 1.76 | 266 | 35.11 | 37 | 48.6% | 4.19 | 28.55 |

## Reproduce

```
python tools/vz_h1_rvol4_universe_confirm.py
```

Not gold. Not DailyRun. Do not retune on OOS.
