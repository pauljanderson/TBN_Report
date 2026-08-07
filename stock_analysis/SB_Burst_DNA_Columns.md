# SB burst DNA columns (Closed / Open / Correlation)

StockBee Momentum Burst (`rocket_stockbee_burst.py`, prefix `SB_`) splices the
following columns onto BRT-schema Closed/Open after `write_brt_closed` /
`write_brt_open`:

| Column | Meaning | On Closed | On Open | Correlation predictor |
|--------|---------|-----------|---------|------------------------|
| `SIGNAL_DATE` | Signal bar date (T) | yes | yes | no (date stamp; `BASE_EXCLUDE`) |
| `PCT_DAY` | Close_T / Close_{T-1} − 1 | yes | yes | yes |
| `DCR` | Day's close range `(C−L)/(H−L)` on signal bar | yes | yes | yes |
| `RANGE_EXP` | Signal range vs prior lookback ranges | yes | yes | yes |
| `VOL_RATIO` | Volume_T / Volume_{T−1} (day vs prior day) | yes | yes | yes |
| `VOL_VS_50` | Volume_T / mean(Volume of prior `burst_vol_avg_lookback` sessions, default 50; excludes T) | yes | yes | yes |
| `SIGNAL_LOW` | Signal-bar Low of Day (LOD); fill stop | yes | yes | yes |
| `RISK_PCT` | `(entry − stop) / entry` at fill | yes | yes | yes |
| `MM_RATIO` | Market Monitor 10d ±4% breadth ratio at T−1 (blank if series not built) | yes | yes | yes |
| `T1_NARROW` | 1 if T−1 range ≤ median (or mode) of prior lookback ranges | yes | yes | yes |
| `T1_DOWN` | 1 if Close_{T−1} < Close_{T−2} | yes | yes | yes |
| `T1_RANGE` | High−Low on T−1 | yes | yes | yes |

Watchlist also carries `SIGNAL_LOW` (plus `MUST_OPEN_ABOVE` / `MUST_OPEN_AT_OR_BELOW`) and the MM / T1 / VOL_VS_50 DNA columns when present.

Gates (default OFF): `burst_mm_gate` + `burst_mm_min_ratio`; `burst_require_t1_narrow_or_down` + `burst_t1_narrow_mode`; `burst_vol_vs_avg_mult` (0=off) + `burst_vol_avg_lookback` (default 50).

Note: existing `VOL_RATIO` is **not** the 50d participation gate — that uses `VOL_VS_50` / `burst_vol_vs_avg_mult`.

Audit counters: `sb_rejected_mm`, `sb_rejected_t1_n`, `sb_rejected_vol_vs_avg`.

Writers: `_BURST_DNA_CLOSED_COLS` / `_burst_dna_*_dict` / `_splice_burst_dna_columns`.
Correlation: `correlate_brt_closed.run_correlation_report` after DNA splice.
