#!/usr/bin/env python3
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "drive" / "brt_sheet_reconcile"

summary = """# AU BRT sheet vs engine — reconcile summary

- Sheet paste: transcript `f301f0a6-...` user message 2026-07-20 (AU OHLC + zones + BOs + trades)
- Engine stamp: **260720215017** (AU-only; `breakout_zone_pick=max`, `stop_loss_based=trigger_low`, SPY -1000, `strong_post_pivot_bars=7`, `strong_post_pivot_pct=0.108`, `max_market_cap=0`)
- Final-PH no-dup (column L): **DISABLED** in current `rocket_brt.py` (twins allowed) — used for this run
- Sheet `$0` holiday placeholders: **0** / 4160 rows
- Engine `AU.csv`: 4160 trading-day bars, 0 zero-OHLC
- **OHLC trading-day compare:** **MISMATCH** (26 dates differ at ±$0.02)

## Reconciled?

**Partial** — trades full parity; one zone gap (OHLC) cascades into BO gaps.

| Layer | Sheet | Engine | Matched | Sheet-only | Engine-only | Notes |
|---|---:|---:|---:|---:|---:|---|
| Zones (±$0.02) | 109 | 109 | **108** | **1** | **1** | exact 107; near 1 ($17.86) |
| Breakouts (date+zone) | 668 | 672 | **663** | **5** | **9** | retest 662/663; Main Row Δ `{0:663}` |
| Trades (±$0.05 entry) | 43 | 43 | **43** | **0** | **0** | exit dates **43/43** |

## Root causes (ranked by impact)

### 1. Sheet High **2015-08-24 = $8.93** vs engine **$8.31** (Δ +$0.62)
Drives the only zone miss:
- Sheet-only: `$8.93 / $8.79 / $9.07`
- Engine-only: `$8.88 / $8.74 / $9.02`
Cascades into most BO gaps (sheet BOs on 8.79/9.07 vs engine 8.74/9.02 on overlapping dates).

### 2. Sheet bar **2024-10-15** wrong (sheet O/H/L/C ≈ 26.89/27.34/26.82/27.34 vs eng 27.29/27.69/27.17/27.55)
Causes sheet BO `2024-10-16` vs engine `2024-10-15` on zone 26.54/27.38.

### 3. Sheet **2019-08-19** H/L wrong (sheet 20.73/19.98 vs eng 21.10/19.65)
Matched BO `2019-08-14` has retest **2019-09-10** (sheet) vs **2019-08-19** (engine) — only retest miss among 663.

### 4. Other non-zero OHLC mismatches (23 more dates)
Mostly small Open tweaks; larger Close diffs on 2011-10-27 (−0.47) and 2012-05-23 (−1.34); 2025-05-22 full-bar drift (same date class as TSLA/NVDA). None currently create extra zone/trade misses beyond #1–#3.

### 5. No `$0` holiday poison
Unlike AMZN/GOOGL/NVDA — AU sheet has **0** zero-OHLC rows. Main Row deltas are all **0**.

## Exact next actions (user)

1. **Override AU 2015-08-24 High → 8.31** (must; closes the zone + most BO gaps).
2. **Override AU 2024-10-15** → O/H/L/C `27.29 / 27.69 / 27.17 / 27.55`.
3. **Override AU 2019-08-19** → H/L `21.10 / 19.65`.
4. Optional: override **2025-05-22** full bar to eng `42.83 / 43.29 / 42.17 / 42.88`, plus other mismatch dates if chasing 100% OHLC.
5. Re-paste zones/BOs after overrides; trades already match — expect zones→109/109 and BOs→~parity.
6. **Accept** residual tiny ±$0.02 noise (e.g. $17.86 lower/upper already within tol).

Formula updated in `OHLC_override_formula.md` (AU merged; TSLA/AMD/MSFT/NFLX/NVDA preserved).

## Full parity?

**NO** today (zones 108/109, BOs 663/668). **YES on trades (43/43).** Achievable after High 2015-08-24 (+ the 2024-10-15 / 2019-08-19 fixes).

## Four-scenario cut-paste

See `AU_four_scenario_stats.md`.

## Artifacts

- `AU_sheet_{ohlc,zones,breakouts,trades}.csv`
- `AU_{zones,breakouts,trades}_diff.md` + `*_match_detail.csv`
- `AU_four_scenario_stats.md`
- Engine: `BRT_*_260720215017.csv` (+ scenario stamps 215133 / 215138 / 215142)
"""

(OUT / "AU_reconcile_summary.md").write_text(summary, encoding="utf-8")
print("wrote summary")
