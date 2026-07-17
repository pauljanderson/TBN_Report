# Sheet ↔ Python parity (DE / DF / DG)

## What was added

1. **`_compute_sheet_ladder_de_df_dg`** — Builds the 8-rung ladder (CG/CH … DB/DC behavior) from lagged CE/CF and bar overlap, outputting **DE**, **DF**, **DG** (maturity bar index, 0-based) per row.
2. **`--emit-sheet-parity`** — With `-s SYMBOL`, writes `drive/BRT_SheetParity_<SYM>_<ts>.csv` with Python’s DE/DF/DG plus three **blank paste columns** for your sheet.
3. **`--sheet-ladder-active-zone`** — Sets `use_sheet_ladder_active_zone=True`: in `entry_eval_mode=row_local`, the **active zone** for gating uses **DG** from this ladder instead of the “overlapping pending maturities” heuristic.

Config (also via `-v`):

- `sheet_maturity_lag_bars` — spreadsheet **C14** (default `7`)
- `sheet_zone_ladder_rungs` — default `8`
- `use_sheet_ladder_active_zone` — default `False`

## Is it useful to paste full sheet rows for “Python-only” entry dates?

**Yes.** For any date where Python shows a buy and the sheet does not (or the reverse):

1. Run with `--emit-sheet-parity -s TICKER`.
2. In Google Sheets, copy **DE, DF, DG** (and optionally **AK, AQ, BG, BI**) for that **DATE** row.
3. Paste into **SHEET_DE_PASTE**, **SHEET_DF_PASTE**, **SHEET_DG_PASTE** on the same date row in `BRT_SheetParity_*.csv` (or use a VLOOKUP / join in Excel).
4. Sort/filter rows where Python DE ≠ Sheet DE (or DG differs). The **first** date where ladder or gate columns diverge is usually where logic must be fixed.

**Note:** Python uses `zone_low` / `zone_high` from the touch stream for CE/CF. If Excel column **AG/AH** forward-fills differently than Python’s per-bar series, CE/CF (and thus the ladder) can diverge even when DE/DF look close—compare **CE_LAG_*** columns to your sheet CE/CF on those rows.

## How many trades fire on zones that are **not** on the sheet’s 8 rungs?

The spreadsheet only “remembers” **eight** zone bands in CG..DC; older zones drop off. Python’s **pending-maturity** list can still hold more history.

To measure how often a **filled** trade’s zone is **not** represented on any of those eight rungs **at the signal bar** (the bar where `close_above` / bullish gate passed — approach **#1**):

```bash
python rocket_brt.py data/newdata/data -s NVDA -o drive --ladder-mismatch-report
```

Console line:

`8-rung ladder vs trades: X/Y closed trades NOT on any ladder rung at signal bar (close_above_date)`

Output: `drive/BRT_LadderMismatch_<SYM>_<ts>.csv`

- **`ON_ANY_OF_8_RUNGS`**: `YES` / `NO` — whether the trade’s maturity bar (or matching zone bounds) appears in one of the eight slots **at `SIGNAL_BAR`** (same as **`CLOSE_ABOVE_DATE`**).
- **`MATURITY_EQ_DG_ACTIVE`**: whether that trade’s maturity bar equals **DE/DF’s** active **`DG`** on that bar (sheet-style “active” zone).

Use **`NO`** rows to decide: fix Python (if ladder should cap entries), or fix the sheet (if AG/AH / CE lag differs), using the paste columns from the parity CSV on those **dates**.

## References

- Formula snapshots: `unused_columns_scan.py` (lines 83–110).
- Spec: `BRT_LOGIC_SPEC.md` (Sheet zone ladder section).
