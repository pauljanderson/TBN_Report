# Sheet vs engine — open questions

Logged when sheet behavior is ambiguous or conflicts with documented BRT_LOGIC_SPEC.
User to resolve later.

---

## 2026-06-20 — NVDA parity pass

### Resolved (engine fixes)
- **Stop multiplier:** Sheet uses 6.6% stop = `entry × 0.934`. Engine default was `0.903` (9.7%), widening stop and missing 2021-03-25 NVDA stop (low 12.272 vs stop 12.27 vs engine 11.86). **Fixed:** `stop_pct` default → `0.934`. Run `260620194127` / `260620194321`: NVDA 2021-03-18 → **2021-03-25 STOP_LOSS @ $12.27**, 7 days, -6.60% — **exact sheet match**.

### NVDA parity score (run `260620194127`, YH-only NVDA)
- **28 / 45 exact** (entry, exit date/price, PnL%, days, trigger CAD)
- **0 partial**, **17 sheet_only**, **30 engine_only**
- Tools: `tools/compare_nvda_sheet.py`, `tools/diagnose_nvda_sheet_only.py`, `tools/forensics_nvda_20210325.py`

### TSLA trade parity (runs 260621083209 → 260621085653)
- **AH buy formula** (user): ``AG & AV & COUNTIF(BO,D) & H7<=E7 & H8>E8`` — documented in ``SHEET_ROCKET_BUY_FORMULA``.
- **Root cause #1:** engine lacked **red-to-green** (prior bar Close<=Open). Fixed ``sheet_red_to_green_entry_enabled`` (default True).
- **Root cause #2:** engine expanded retest dates to **D+1**; sheet ``COUNTIF(BO,D)`` is **strict**. Default ``sheet_dw_countif_include_prior_bar_date=False``.
- **Trace 2019-11-14 blocked:** old engine entered 10/25→10/28 (no red-to-green); with fix, no 10/31 entry either; **11/14 now matches**.
- **Trace 2021-12-30:** old engine entered on 12/23 breakout; with fix **CAD=12/30, entry 12/31 @ 357.81** matches sheet.
- **Score:** 34/40 exact (run ``260621085653``), 39 engine vs 40 sheet trades; 6 sheet_only + 5 engine_only remain.
- **BH:BQ** is a FILTER ledger: ``BH=FILTER(D,BG=1)``, ``BI=FILTER(BE,BG=1)``, ``BJ=FILTER(BC,BG=1)``, ``BK=FILTER(BF,BG=1)``.
- **BL** = ``MATCH(BH, D:D, 0)``; **BM** = ``BL + $C$19`` (C19=2); **BN/BO/BP/BQ** as documented in ``sheet_column_reference.BREAKOUT_LEDGER_FORMULAS``.
- **Main Row −8 vs engine:** resolved — **D2 = 2016-01-14** (CSV starts 2016-01-04, index 8) → ``MATCH(2017-02-21)`` = 279 vs engine 287. Not blank header rows.
- **Open:** none for TSLA breakout ledger (402/402). **BC:BG** confirmed — see ``BREAKOUT_PER_ROW_FORMULAS``.
- **BD** (*Selected break upper*) may be ``#REF!``; not referenced by BE/BF/BG or BH:BQ FILTER.

### TSLA breakout/retest DI zone pick (run `260621074438`)
- **Root cause of 44 zone swaps:** engine used ``MIN(BI)`` among crossed zones; sheet uses ``MAX(BI)`` among zones **activated before** the breakout bar (exclude same-day YH activation-only crosses).
- **Fix:** ``_sheet_pick_di_breakout_zone_long`` in ``rocket_brt.py``; verified **402/402** breakout keys + **381/381** retest dates (21 both no retest).
- Old comment ``FILTER + MIN`` was **wrong** for this sheet (likely MSFT/BRT legacy guess).

- **22 / 45 exact**, **23 sheet_only**, **48 engine_only**
- **Wins:** 2019-01-02 (growth slack), 2019-03-08 (BY next-session), 2019-04-03 exact
- **Regression vs 28/45:** BY next-session + growth slack unlock early 2019 but add more engine-only retest entries (extra COVID cluster, adjacent retest days), shifting later matches
- Engine defaults now: `growth_history_slack_bars=2`, `sheet_dw_countif_include_prior_bar_date=true`
- `run_brt.ps1` injects `max_positions=16`, `min_spy_compare_1y_at_trigger=-1000`, `too_high_multiplier=0` when not overridden (required for NVDA YH parity vs stock defaults)

### Sheet_only breakdown (17 rows)
| Cause | Count | Notes |
|-------|-------|-------|
| **Blocked: engine already in NVDA trade** on sheet purchase date | 9 | Engine one-position-per-symbol; sheet log still shows entry. Examples: 2019-09-13 (blocked by 8/29→10/22), 2020-03-23 (blocked by 3/19→3/24), 2023-04-05 (blocked by 3/22→5/25). |
| **No retest row on trigger day** | 5 | e.g. 2019-03-08 sheet trigger but engine retest is 3/25 (BO 3/19). Zone/breakout calendar mismatch. |
| **Retest on trigger, not blocked, still no entry** | 8 | e.g. 2019-01-02 has retest row + not blocked — entry gate failure (active-zone context, sheet ladder gates, or other). Needs per-bar gate trace. |

### Open — one trade per symbol vs sheet cadence
- Engine blocks new entries while any position is open. Nine sheet_only rows are **explicit overlaps** where sheet took a second trade while engine was still long. Confirm whether sheet portfolio allows overlapping NVDA positions or uses a different capital model.

### Open — stop anchor bar
- `BRT_LOGIC_SPEC.md` says `stop = Low[trigger_bar] × stop_pct`. NVDA 2021-03-17: sheet stop $12.27 matches `entry × 0.934`, not `trigger_low × 0.934`. Engine uses **entry fill price**. Confirm sheet stop anchor.

### Open — exit price on stop touch (non-gap)
- Sheet 2021-03-25 exit $12.27 = stop when low tags stop but open is above stop. Engine matches (`exit_at_close_when_stopped=False`).

### Open — engine_only trades (30)
- Engine takes trades the sheet log omits. Categories below (see `tools/analyze_nvda_gaps.py`).

### 2026-06-20 — User follow-up (gate trace + BO/retest + engine-only)

#### 1) “Blocked” sheet_only (9 rows) — NOT sheet overlap
All nine are **engine-only positions** still open on the sheet purchase date. Sheet was flat (prior sheet trade already exited). Root cause: **extra engine entries** the sheet did not take → blocks the legitimate sheet signal without violating one-position rules.

#### 2) Per-bar gate trace (8 non-blocked sheet_only triggers)
| Trigger | Purch | First blocking gate (TRACE) |
|---------|-------|-----------------------------|
| **2019-01-02** | 2019-01-03 | `growth_not_enough_history` (eval_bar=754 < growth_bars=756) on BO 12/28/2018 retest zone |
| **2019-01-03** | — | `close<=open` on eval bar (red day; entry already missed) |
| **2019-03-08** | 2019-03-11 | `Retest Date - eval 20190308 not in BY retest set` — engine retest is **2019-03-07**, sheet **2019-03-08** |
| **2019-03-11** | — | Same BY retest set miss |
| **2024-07-12** | 2024-07-15 | BY retest set miss on 20240712 |
| **2024-07-15** | — | `close<=open` on trigger bar |
| 2019-06-06, 2019-08-21, 2020-04-08, 2022-10-13, 2025-04-11 | — | No pending evaluated on trace bar (no retest row on that calendar day in engine export) |

**Open:** Does sheet apply `growth_filter` (756 bars) on YH tab? Engine blocks 2019-01-02 retest for insufficient history at bar 754.

#### 3) Breakout / retest data
- Engine export `YH_breakout_and_retest_260620194127.csv`: **449** retest rows.
- Pasted `nvda_breakout_ledger_full.tsv` is **column-shifted** in pandas (406/439 rows parse `Retest Date` as `1`). Rebuild via `tools/build_nvda_ledger_from_transcript.py` before automated ledger diff.
- **Concrete mismatch (2019-03-08):** Sheet ledger row BO 2/12/2019 MR784 retest **3/8/2019**; engine export same BO MR784 retest **3/7/2019** (retest row 800 vs sheet 801). Strict `sheet_dw_countif_entry_enabled` requires eval on 3/8 → entry blocked; sheet trigger is 3/8.
- Tools: `tools/compare_nvda_bo_retest.py`, `tools/trace_nvda_sheet_only_gates.py`

#### 4) Engine-only trades — what it means & suggestions
**Meaning:** Engine closed a trade on a purchase date that does not appear in the 45-row sheet log. The sheet is not “in a trade” on that day; the engine took a **different signal** (usually adjacent retest day or extra COVID-era cluster).

**Categories (run `260620194127`, 30 engine-only):**
| Category | Examples | Suggested resolution |
|----------|----------|----------------------|
| **A. Extra entry blocks later sheet trade** | 2019-08-29, 2020-03-19, 2023-03-22 | Fix why engine enters when sheet does not (BY retest day, growth, sheet ladder gates). Removing extras fixes 9 sheet_only without overlap. |
| **B. Retest date ±1 day** | Engine 3/7 vs sheet trigger 3/8 | Align retest overlap detection to sheet calendar (audit YH retest bar index). |
| **C. Stale BO / long memory** | 2022-09-19 from BO 2021-03-26 | Optional `max_days_since_breakout` or sheet-style zone retirement. |
| **D. COVID cluster** | 2020-03-10, 03-16, 03-18, 03-19 | Sheet log may omit rapid re-entries; confirm if sheet suppresses adjacent signals. |
| **E. Sheet log curation** | Many engine-only have valid retest rows | Sheet trade log may be a **subset** of full COUNTIF ledger, not every engine-eligible retest. |

**Suggested next engine experiments (no overlap model change):**
1. Trace one engine-only vs sheet-nearest with `--debug-entry NVDA <CAD>` (e.g. 2019-08-28 blocker trade).
2. Fix retest date parity for MR784-style rows, re-run NVDA.
3. Rebuild clean ledger TSV, run `compare_nvda_bo_retest.py` for full 367-style key match.
4. Confirm with user: YH tab `growth_filter_enabled` / `growth_bars=756` — if off on sheet, set engine to match for YH runs.


