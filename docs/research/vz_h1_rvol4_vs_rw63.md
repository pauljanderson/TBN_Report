# H1 origin rvol ≥4 vs rw126 control and adopted rw63

Research only. Same DualPaul78 closed trades as the playbook AB (`RESEARCH_CANDIDATE_V2` rw126, next_open, `zone_atr05_ts40`).

## Verdict

The previously applied variable is **`retest_window=63`**. It drops 487 late first-retests from the rw126 book. That cut keeps most of the book and does **not** deliver the Max DD cut that H1 rvol≥4 shows.

- **BEFORE (rw126 control):** N=5313, avg PnL 2.76%, Ann ROR 64.25%, Max DD 38.45%, Calmar 1.67 (OOS N=827 PnL 5.22% Max DD 5.18%).
- **AFTER (rw63 control):** N=4826, avg PnL 2.85%, Ann ROR 66.92%, Max DD 38.21%, Calmar 1.75 (OOS N=775 PnL 5.42% Max DD 5.23%). Lean vs BEFORE: **DISMISS (no change)**.
- **H1 origin rvol ≥4 on rw126:** N=1655 (31% of BEFORE), avg PnL 3.08%, Ann ROR 69.39%, Max DD 17.66%, Calmar 3.93 (OOS N=200 PnL 5.74% Max DD 5.42%). Lean vs BEFORE: **HOLD (weak)**.
- **Stack (rvol≥4 + rw63):** N=1520 (31% of AFTER), avg PnL 3.16%, Ann ROR 71.28%, Max DD 20.59%, Calmar 3.46 (OOS N=191 PnL 5.69% Max DD 5.71%). Lean vs AFTER: **HOLD (weak)**.

H1 rvol≥4 is the calmer book vs both controls (Max DD 17.66% vs 38.45% before / 38.21% after). rw63 barely moves Max DD — it is a small N trim (487 trades), not a drawdown fix. Stacking rvol≥4 on rw63 does not help DD vs H1 alone (20.59% vs 17.66%); most H1 trades already retest inside 63d. If the reason to like H1 is the DD cut, keep it on rw126 rather than stacking. Still research-only: H1 is a thin sleeve (~31% of rw126 N). Do not retune on OOS.

## Setup

rw63 proxy: `bars_after_break ≤ 64` because house fill is next_open (engine window is on the signal bar; entry is T+1).

| Arm | Knob | Lean | N | WR% | Avg PnL% | Avg R | Book Ann ROR% | Max DD% | Calmar | Avg conc | IS N | IS WR% | IS Avg PnL% | IS Max DD% | OOS N | OOS WR% | OOS Avg PnL% | OOS Max DD% |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BEFORE CONTROL rw126 | retest_window=126 (playbook control) | control | 5313 | 50.7% | 2.76 | 0.34 | 64.25 | 38.45 | 1.67 | 14.53 | 4486 | 49.0% | 2.31 | 39.02 | 827 | 60.0% | 5.22 | 5.18 |
| AFTER CONTROL rw63 | retest_window=63 (adopted freeze) | DISMISS (no change) | 4826 | 50.8% | 2.85 | 0.35 | 66.92 | 38.21 | 1.75 | 13.17 | 4051 | 49.0% | 2.36 | 38.92 | 775 | 60.6% | 5.42 | 5.23 |
| H1 ORIGIN_RVOL>=4 on rw126 | origin_rvol >= 4.0 on rw126 | HOLD (weak) | 1655 | 50.4% | 3.08 | 0.33 | 69.39 | 17.66 | 3.93 | 4.74 | 1455 | 49.5% | 2.71 | 17.67 | 200 | 57.0% | 5.74 | 5.42 |
| H1 rvol>=4 + rw63 | origin_rvol >= 4.0 and rw63 | HOLD (weak) | 1520 | 50.5% | 3.16 | 0.32 | 71.28 | 20.59 | 3.46 | 4.37 | 1329 | 49.4% | 2.79 | 20.65 | 191 | 58.1% | 5.69 | 5.71 |

## Reproduce

```
python tools/vz_playbook_strength_ab.py --replay
python tools/vz_h1_rvol4_vs_rw63.py
```

Not gold. Not DailyRun. Do not retune on OOS.
