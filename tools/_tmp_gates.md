# TSLA sheet-only trades — entry gate analysis (current)

- Engine stamp: **`260720143523`** (`stop_loss_based=trigger_low`, `min_spy_compare_1y_at_trigger=-1000`, `growth_filter` 756 / slack 2)
- Sheet paste after growth `$0 prior → FALSE`: `tsla_brt_sheet_trades.tsv` (**63** trades)
- Match: **60 / 63** (±$0.05 entry on Trigger = CLOSE_ABOVE); exit dates **60/60** among matches
- Breakouts/retests: in-window parity holds — remaining misses are **entry-path** divergences
- Detail writeups:
  - `TSLA_sheet_only_2013-02-11.md`
  - `TSLA_sheet_only_2024-08-21.md`
  - `TSLA_sheet_only_2024-09-27.md`
- Diff: `TSLA_trades_diff.md`

---

## Active engine entry gates (this stamp)

### ON / binding

| Gate | Value | Role |
|------|------:|------|
| `entry_from_retest_only` | true | Buy only after BY/retest pending |
| `sheet_dw_countif_entry_enabled` | true | Eval date in simulated BY set |
| `require_close_gt_open` | true | Bullish signal bar (C>O) |
| `sheet_red_to_green_entry_enabled` | true | Prior red + today green |
| `growth_filter_enabled` | true | Need history + `Close[t] >= Close[t−756]` |
| `growth_bars` / `growth_history_slack_bars` | 756 / 2 | Min eval index **754** |
| `min_spy_compare_1y_at_trigger` | **−1000** | Effectively **off** |
| `allow_secondary_entries` | false | One open trade per symbol |
| `sheet_no_entry_same_bar_after_exit` | true | No same-bar re-entry |
| `stop_loss_based` | `trigger_low` | Exit path |

### OFF / no-op here

`too_high_multiplier=0`, `min_ind_score=-1`, IND buy off, tight-range off, DO/DP off.  
`entry_filter_major_pivot` / `entry_filter_is_20bar_high_at_trigger` are audit-style fields — **not** consulted in the pending entry loop.

---

## Current sheet-only root causes (3)

| # | Trigger | Entry | Exit | PnL | First engine block | Key number / gate | Why sheet still enters |
|--:|---------|------:|------|----:|--------------------|-------------------|------------------------|
| 1 | **2013-02-11** | 2.56 | 2013-02-21 | −8.79% | **`growth_not_enough_history`** | eval idx **659** < min **754** (short **95** bars; no Close[t−756]) | Sheet composite Growth OK (≥2 of 1Y/2Y/3Y); 1Y+2Y pass even when 3Y is $0/FALSE |
| 2 | **2024-08-21** | 223.82 | 2024-08-28 | −8.67% | **`growth_filter_fail`** | Engine Close **223.27** < Close[i−756] **229.66** (**2021-08-18**), **−2.78%** | **756 off-by-1:** sheet `INDEX($H:$H,ROW()-756)` → row **2931** = **2021-08-17** Close **221.90** → PASS; engine uses **2021-08-18** |
| 3 | **2024-09-27** | 259.04 | 2024-10-10 | −8.37% | **`allow_secondary_entries=false`** (open trade) | Engine long from **2024-09-23** @ 254.08 until **2024-10-11** | Sheet skipped 9/23 and took 9/25→9/27 retest instead |

### Engine-only twin (not sheet-only, but paired with #3)

| CLOSE_ABOVE | Entry | Exit | Note |
|-------------|------:|------|------|
| **2024-09-23** | 254.08 | 2024-10-11 GAP_DOWN (−13.36%) | Blocks sheet’s 9/27; growth on 9/23 **+2.72%** (250 ≥ 243.39). Counterfactual: skip 9/23 → engine **would** take 9/27. |

---

## Root-cause counts (current 3)

| Count | Gate |
|------:|------|
| **2** | `growth_filter` (1× not enough history; 1× **756 off-by-1** → close &lt; close−756) |
| **1** | one-trade-at-a-time / open overlap (twin trigger) |

Not causes for these 3: missing BO/retest, red→green, C>O, SPY floor (disabled at −1000), IND, too-high fill.

---

## Historical note (pre−1000 SPY stamp `260720111055`)

Earlier reconcile had **17** sheet-only rows: **16** first-failed `min_spy_compare_1y=-12`, **1** growth history (2013-01-28).  
After `-v min_spy_compare_1y_at_trigger=-1000` and the sheet `$0→FALSE` growth edit, that collapsed to the **3** above (2013-01-28 dropped; 2013-02-11 appeared).

Archived pieces: `TSLA_sheet_only_trades_list.md`, `TSLA_sheet_only_audit_reasons.md`, `TSLA_sheet_only_gates_diag.json`.

---

## Recommended next knobs (if chasing sheet parity)

1. **Growth lookback alignment** — **2024-08-21** is a confirmed **756 off-by-1** (sheet ROW()−756 → 8/17/2021; engine i−756 → 8/18/2021). Fix sheet↔CSV row/bar mapping or lookback index so both hit the same prior close. Separately, **2013-02-11** is still early-history / composite Growth OK vs `growth_not_enough_history`.
2. **9/23 vs 9/27** — decide which retest is canonical; stopping engine 9/23 (or allowing secondary entries) is what unlocks 9/27 parity.

---

## Sources

- `run_brt.bat`, `BRT_Audit_Report_260720143523.csv`
- `BRT_Closed_260720143523.csv`, `BRT_breakout_and_retest_260720143523.csv`
- `stock_analysis/ENTRY_GATES_SHEET_VS_PROGRAM.md`, `rocket_brt.py` growth helpers
