# TSLA trades reconcile — growth formula `$0 prior → FALSE`

- Sheet paste: 2026-07-20 15:57 (growth update; first trade now **2013-02-11**, was 2013-01-28)
- Saved: `tools/tsla_brt_sheet_trades.tsv` + `drive/brt_sheet_reconcile/tsla_brt_sheet_trades.tsv`
- Engine: `BRT_Closed_260720143523.csv` + `BRT_Open_260720143523.csv` (picked newest with TSLA; preferred was `260720113551`)
- Settings context: `stop_loss_based=trigger_low`, `min_spy_compare_1y_at_trigger=-1000`, growth_filter on
- Prior (pre growth-sheet fix, same engine `260720113551`): matched **60**/63, sheet-only **3** (2013-01-28, 2024-08-21, 2024-09-27), engine-only **2** (2024-09-23, 2026-05-19 open)
- Match key: sheet **Trigger Date** == engine **CLOSE_ABOVE_DATE**, entry exact or +/- $0.05 (also report +/- $0.02)
- Window: 2010-01-04 .. 2026-06-05 (sheet fully inside window)
- Sheet trades: **63** (W/L 22/41) — same count as prior (swapped 2013-01-28 → 2013-02-11)
- Engine trades in window: **62** (W/L 22/40); same vs preferred stamp `260720113551`

## Match summary
- Exact entry: **55**
- Near entry (+/- $0.05): **5** (of which +/- $0.02: **3**)
- Total matched (+/- $0.05): **60** / 63 sheet (95.2%) — prior **60**/63
- Matched at +/- $0.02 (exact + near≤0.02): **58** / 63
- Sheet-only: **3** (prior **3**)
- Engine-only: **2** (prior **2**)
- Exit-date match among matched (both have exit): **60/60**

## Special checks (growth-formula update)

- **2013-02-11**: SHEET-ONLY (entry 2.5600, exit 2013-02-21, LOSS)
- **2013-01-28**: absent from both
- **2024-08-21**: SHEET-ONLY (entry 223.8200, exit 2024-08-28, LOSS)
- **2024-09-27**: SHEET-ONLY (entry 259.0400, exit 2024-10-10, LOSS)
- **2024-09-23**: ENGINE-ONLY (entry 254.0800, exit 2024-10-11, GAP_DOWN)

## Sheet-only
| trigger | entry | exit | pnl% | result | note |
|---|---:|---|---:|---|---|
| 2013-02-11 | 2.5600 | 2013-02-21 | -8.79 | LOSS | new first trade after growth $0→FALSE; engine never entered (growth history still short / different CA path) |
| 2024-08-21 | 223.8200 | 2024-08-28 | -0.0867 | LOSS | growth_filter — Close < Close_756_ago (unchanged) |
| 2024-09-27 | 259.0400 | 2024-10-10 | -0.0837 | LOSS | open-trade overlap twin — engine entered 2024-09-23 |

## Engine-only
| close_above | open | entry | exit | pnl% | exit_type | note |
|---|---|---:|---|---:|---|---|
| 2024-09-23 | 2024-09-24 | 254.0800 | 2024-10-11 | -13.36 | GAP_DOWN | twin of sheet 2024-09-27 |
| 2026-05-19 | 2026-05-20 | 407.6000 | None | -8.7 | OPEN | open trade; sheet window ends before / no sheet row |

## Near entry matches (Δ ≤ $0.05)
- 2013-07-19: sheet 8.0200 vs eng 7.9900 (Δ=0.0300; ≤0.02=False; exit_match=True)
- 2013-08-15: sheet 9.4700 vs eng 9.4400 (Δ=0.0300; ≤0.02=False; exit_match=True)
- 2013-08-27: sheet 11.2800 vs eng 11.2700 (Δ=0.0100; ≤0.02=True; exit_match=True)
- 2013-12-09: sheet 9.3300 vs eng 9.3400 (Δ=0.0100; ≤0.02=True; exit_match=True)
- 2015-01-29: sheet 13.5900 vs eng 13.6000 (Δ=0.0100; ≤0.02=True; exit_match=True)

## Delta vs prior reconcile
- **2013-01-28** dropped from sheet (growth formula now FALSE when prior=$0) — no longer sheet-only.
- **2013-02-11** added on sheet as new first trade — check Special checks above for match status.
- **2024-08-21** / **2024-09-27** expected to remain sheet-only unless engine path changed.

## Notes
- Sheet Trigger Date aligns with engine CLOSE_ABOVE_DATE; DATE_OPENED is typically next session.
- With `stop_loss_based=trigger_low`, stop = signal-bar Low × 0.934 (sheet AM).
- Engine stamp was not re-run; comparing against existing Closed/Open only.
