# VZ OC-overlap volume strength vs PnL / Ann ROR

Research only. Freeze = `RESEARCH_CANDIDATE_V2` (**rw126**) — prior to the last adopted trade-count cut (`retest_window=63`).
House fill `next_open`, exit `zone_atr05_ts40`, DualPaul78 (83 names). Stamp `vz_oc_vol_strength_20260813`.

## Verdict

**No usable correlation.** Overlap-day volume does not rank VZ trades.

- Spearman(`oc_rvol_mean`, PnL%) = **+0.017** (p=0.22, N=5012)
- Spearman vs per-trade Ann ROR = **+0.020** (p=0.16)
- Within-symbol mean Spearman vs PnL% = **+0.023** (83 names)
- Every other volume feature (sum / max / day-count / origin rvol / existing touch strength) is also |r| ≲ 0.03

A Q1→Q4 **mean** PnL lift exists on the full sample (2.33% → 3.30%; book Ann ROR 59% → 88%), but it is not a ranking signal: medians and win rate are not monotone, and **OOS quartiles do not keep Q4 on top**.

Do not add an OC-overlap volume filter on this evidence.

## Setup

A day counts toward strength when **Open or Close sits inside** `[zone.lo, zone.hi]`, after the zone is known and through the signal bar (no look-ahead). Primary metric is mean **relative** volume (day volume / 20-day SMA) so names are comparable. The origin max-vol day is scored separately — it already defined the zone.

| Split | N closed | Win% | Avg PnL% | Avg R | Med PnL% | Avg days | Book Ann ROR% |
|---|---:|---:|---:|---:|---:|---:|---:|
| FULL rw126 | 5313 | 50.7 | 2.76 | 0.34 | 0.43 | 20.0 | 64.25 |
| IS (&lt;2024) | 4486 | 49.0 | 2.31 | 0.28 | −0.60 | 20.3 | 50.63 |
| OOS (2024+) | 827 | 60.0 | 5.22 | 0.67 | 4.94 | 18.5 | 173.77 |

Current adopted freeze uses `retest_window=63` (fewer late retests). This stamp keeps rw126 so the strength test has more trades.

## Spearman vs PnL% (FULL)

| Feature | r | p | N |
|---|---:|---:|---:|
| oc_rvol_mean (primary) | +0.017 | 0.217 | 5012 |
| oc_rvol_sum | +0.004 | 0.794 | 5313 |
| oc_rvol_max | +0.007 | 0.632 | 5012 |
| oc_overlap_n | −0.002 | 0.902 | 5313 |
| log_oc_vol_sum | +0.010 | 0.452 | 5313 |
| origin_rvol | +0.001 | 0.916 | 5307 |
| touch_strength (existing) | +0.011 | 0.416 | 5313 |
| touch_count_all | −0.023 | 0.099 | 5313 |

IS Spearman vs PnL = +0.015 (p=0.34). OOS = +0.035 (p=0.33). Same null.

## Quartiles of `oc_rvol_mean`

### FULL

| Q | N | Win% | Avg PnL% | Med PnL% | Book Ann ROR% |
|---|---:|---:|---:|---:|---:|
| Q1 low | 1253 | 48.1 | 2.33 | −0.89 | 59.16 |
| Q2 | 1253 | 50.8 | 2.67 | 0.74 | 54.54 |
| Q3 | 1253 | 52.8 | 2.78 | 1.11 | 60.17 |
| Q4 high | 1253 | 50.8 | 3.30 | 0.46 | 88.31 |

Q4’s higher **mean** / book Ann ROR is a fat-tail effect (median PnL is worse than Q2/Q3; WR is not highest). High vs low half: 3.04% vs 2.50% avg PnL, 73% vs 57% book Ann ROR — still a thin, non-ranked lift.

### IS

| Q | N | Win% | Avg PnL% | Book Ann ROR% |
|---|---:|---:|---:|---:|
| Q1 | 1057 | 46.4 | 1.90 | 44.3 |
| Q2 | 1056 | 49.6 | 2.38 | 46.6 |
| Q3 | 1056 | 50.8 | 1.98 | 39.3 |
| Q4 | 1057 | 48.4 | 2.88 | 75.0 |

### OOS (does not confirm)

| Q | N | Win% | Avg PnL% | Book Ann ROR% |
|---|---:|---:|---:|---:|
| Q1 | 197 | 57.9 | 4.84 | 214 |
| Q2 | 196 | 57.1 | 4.29 | 115 |
| Q3 | 196 | 63.3 | 6.86 | 246 |
| Q4 | 197 | 62.9 | 5.54 | 173 |

OOS best bucket is Q3, not Q4. Q1 is not the worst on Ann ROR.

## Reproduce

```
python tools/vz_oc_overlap_vol_strength.py
python tools/test_vz_oc_overlap_vol_strength.py   # helpers; needs PYTHONPATH=repo root
```

Full HTML: `docs/research/vz_oc_overlap_vol_strength.html` (also under `drive/paul_experiments/vz_oc_vol_strength_20260813/`).
