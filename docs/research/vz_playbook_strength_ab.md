# VZ playbook strength ABs

Research only. Control = `RESEARCH_CANDIDATE_V2` rw126, DualPaul78, next_open, `zone_atr05_ts40`.

## Verdict

### H1 origin climatic rvol

- **H1 ORIGIN_RVOL>=2.5**: DISMISS — FULL N=3631 WR 50.8% avg PnL 2.76% Ann ROR 61.76% (OOS N=561 PnL 5.38%)
- **H1 ORIGIN_RVOL>=4.0**: HOLD (weak) — FULL N=1655 WR 50.4% avg PnL 3.08% Ann ROR 69.39% (OOS N=200 PnL 5.74%)

### H2 naked / drop min_touches

- **H2 MT0 drop prior-touch**: DISMISS — FULL N=6013 WR 49.0% avg PnL 2.45% Ann ROR 56.70% (OOS N=932 PnL 4.69%)
- **H2 NAKED only**: DISMISS — FULL N=2684 WR 47.0% avg PnL 2.05% Ann ROR 46.09% (OOS N=406 PnL 3.90%)

### H3 lighter retest volume

- **H3 RETEST/ORIGIN<=0.5**: DISMISS — FULL N=4079 WR 50.6% avg PnL 2.73% Ann ROR 60.65% (OOS N=595 PnL 5.68%)
- **H3 SIGNAL_RVOL<1**: DISMISS — FULL N=2774 WR 49.7% avg PnL 2.47% Ann ROR 55.42% (OOS N=431 PnL 5.40%)

## Setup

Control origin_rvol median=3.09 p10=1.91 p90=6.78.
Control retest/origin median=0.29 signal_rvol median=0.97.

| Arm | Knob | Lean | N | WR% | Avg PnL% | Avg R | Book Ann ROR% | IS N | IS WR% | IS Avg PnL% | OOS N | OOS WR% | OOS Avg PnL% |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CONTROL mt>=1 | none (rw126 v2) | control | 5313 | 50.7% | 2.76 | 0.34 | 64.25 | 4486 | 49.0% | 2.31 | 827 | 60.0% | 5.22 |
| H1 ORIGIN_RVOL>=2.5 | origin_rvol >= 2.5 | DISMISS | 3631 | 50.8% | 2.76 | 0.33 | 61.76 | 3070 | 49.1% | 2.28 | 561 | 59.7% | 5.38 |
| H1 ORIGIN_RVOL>=4.0 | origin_rvol >= 4.0 | HOLD (weak) | 1655 | 50.4% | 3.08 | 0.33 | 69.39 | 1455 | 49.5% | 2.71 | 200 | 57.0% | 5.74 |
| H2 MT0 drop prior-touch | min_touches 1→0 | DISMISS | 6013 | 49.0% | 2.45 | 0.32 | 56.70 | 5081 | 47.5% | 2.04 | 932 | 57.4% | 4.69 |
| H2 NAKED only | mt=0 and touch_count_all==0 | DISMISS | 2684 | 47.0% | 2.05 | 0.30 | 46.09 | 2278 | 45.5% | 1.72 | 406 | 55.2% | 3.90 |
| H3 RETEST/ORIGIN<=0.5 | signal_vol / origin_vol <= 0.5 | DISMISS | 4079 | 50.6% | 2.73 | 0.33 | 60.65 | 3484 | 48.8% | 2.22 | 595 | 61.5% | 5.68 |
| H3 SIGNAL_RVOL<1 | signal_rvol < 1.0 | DISMISS | 2774 | 49.7% | 2.47 | 0.30 | 55.42 | 2343 | 47.6% | 1.93 | 431 | 61.0% | 5.40 |

## Reproduce

```
python tools/vz_playbook_strength_ab.py
```

Not gold. Not DailyRun. Do not retune on OOS.
