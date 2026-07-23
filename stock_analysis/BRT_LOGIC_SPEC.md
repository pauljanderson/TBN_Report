# Rocket BRT — Explicit Logic Specification v1.1

*(Incorporates product owner feedback: entry timing 2-day window, short candidates, 7/10 rule, configurable band_pct)*

---

## 1. PIVOT DETECTION (Level 1)

**Parameters:** `k=4`, `m=7`, `d=0.06` (6%)

**For each bar j** (where j ∈ [k, n-m-1]):

### Pivot High
1. **Window:** Bars j-k through j+k (2k+1 bars, centered on j)
2. **Local max:** `wmax = max(High[j-k..j+k])`, tie-break: **earliest** bar with that high
3. **First idx hi:** Index of the first (leftmost) bar in the window with High == wmax
4. **Is pivot high:**  
   `hi_j == wmax` AND `j == first_idx_hi` (bar j must be the one with the max)
5. **Confirmation:** Min of **future bars only** (j+1 … j+m), no leakage:  
   `future_lo = min(Low[j+1..j+m])`  
   `future_lo <= hi_j * (1 - d)`  
   i.e. price must drop at least 6% below the pivot high within the next 7 bars
6. **Output:** If both true → `pivot_high[j]=1`, `ph_price[j]=High[j]`

### Pivot Low
1. **Window:** Same j-k to j+k
2. **Local min:** `wmin = min(Low[j-k..j+k])`, tie-break: **earliest** bar with that low
3. **First idx lo:** Index of the first bar in the window with Low == wmin
4. **Is pivot low:**  
   `lo_j == wmin` AND `j == first_idx_lo`
5. **Confirmation:** Max of **future bars only** (j+1 … j+m):  
   `future_hi = max(High[j+1..j+m])`  
   `future_hi >= lo_j * (1 + d)`
6. **Output:** If both true → `pivot_low[j]=1`, `pl_price[j]=Low[j]`

**Note:** Pivot High and Pivot Low are independent; a bar can be both, one, or neither. Index bounds [k, n-m-1] prevent out-of-range errors.

---

## 2. TOUCH STREAM & MATURITY (Level 3)

**Parameters:** `band_pct=0.02` (configurable), `lookback_long=504`, `touch_threshold=2` (STONK_DATA 3.0 sheet: **2** touches to mature)

### Sheet-touch Final Pivot High (`brt_sheet_touch` / `compute_sheet_brt_touch_stream`)

When BRT sheet-touch is enabled, a **Final Pivot High** requires: local high (±`pivot_local_window`) AND post-drop (≥`pivot_future_move_pct` over `post_pivot_bars`) AND not-also-pivot-low. **Column L / no-dup** (suppress a second Final PH because a prior Final PH exists in the local window at ±`dedup_tol_pct`) is **disabled** per PO 2026-07-20 — consecutive same-price Final PHs are allowed (AMZN 2011-10-14 + 2011-10-17 @ $12.34). Pivot-low no-dup and local/post/not-also gates remain. Touch still needs Final PH + pre-strong (Z) + pullback ≥ `strong_post_pivot_pct` over `strong_post_pivot_bars`.

### What counts as a touch
For each bar i:
- If `pivot_high[i]==1` → **touch at bar i**, `touch_price[i] = High[i]`
- Else if `pivot_low[i]==1` → **touch at bar i**, `touch_price[i] = Low[i]`
- Else → **no touch**, `touch_price[i] = null`

**Strong pivot filter (optional, STONK_DATA 3.0):** When `strong_pivots_enabled` is True and `realtime_filter_enabled` is False, a pivot only produces a touch if it passes the strong-pivot rules. Defaults match the BRT sheet: `strong_pre_pivot_bars=7`, `strong_pre_pivot_pct=0.081`, `strong_post_pivot_bars=7`, `strong_post_pivot_pct=0.108`, `strong_pivot_mode="pre"`. (MTS sheet uses different C-cell values — see `run_mts.bat` / `--mts-sheet-parity`.)
- **Pre (lookback, realtime-safe):** Pivot **Low** at \(t\): `(1 - Low[t] / max(High[t-pre_bars : t])) >= strong_pre_pivot_pct`. Pivot **High** at \(t\): `High[t] / min(Low[t-pre_bars : t]) - 1 >= strong_pre_pivot_pct`. Indices are prior bars only (no lookahead).
- **Post (lookahead):** Same follow-through test as legacy: e.g. pivot low requires `max(High[t+1:t+post_bars+1])/Low[t] - 1 >= strong_post_pivot_pct`.
- **`strong_pivot_mode`:** `pre` (default) uses only pre rules; `post` uses only post rules; `both` requires pre **and** post. With `realtime_filter_enabled`, the strong filter is skipped and **all** pivots create touches.

**Only pivots produce touches.** No pivot = no touch. Pivot-only counting avoids double-counting "staying in zone" (if we ever switch to bar-based: enter zone = 1 touch; staying inside = not multiple touches).

### Zone band (per touch)
When bar i has a touch:
- `zone_center[i] = touch_price[i]`
- `zone_low[i] = zone_center[i] * (1 - band_pct)`
- `zone_high[i] = zone_center[i] * (1 + band_pct)`

Each touch defines its **own** band. **Overlapping bands are not merged** in the current implementation. This allows parallel band maturity—e.g. pivot A band 98–102 and pivot B band 99–103 can each mature independently, which may produce near-duplicate levels or two maturity events in adjacent bars. Acceptable for v1. *(Future: merge overlapping bands into persistent zones.)*

### Touch count (long-memory)
For bar i with a touch:
- `start = max(0, i - lookback_long + 1)`
- `count =` number of bars j in [start, i] where:
  - `touch_price[j]` is not null, AND
  - `zone_low[i] <= touch_price[j] <= zone_high[i]`

We count **prior pivots** that fall inside **this** bar's zone band. **We do not track persistent zone objects**—we recalculate maturity from scratch per pivot. This matches the spreadsheet prototype and is valid for v1.

### Maturity event
- `prev_count = touch_count[i-1]` (or 0 if i==0)
- `matured_now[i] = (count >= touch_threshold) AND (prev_count < touch_threshold)` — default **`touch_threshold = 2`** (sheet)

One-time trigger. No repeat on subsequent touches after maturity.

### Long vs short (matured-below)
- **Long trigger:** `matured_now[i]` AND `Close[i] > zone_center[i]` (close above zone)
- **Short candidate:** `matured_now[i]` AND `Close[i] <= zone_center[i]` — flagged for possible shorting; not traded in v1

---

## 3. ENTRY

### Entry timing (maturity touch + bullish candle same day or next day)
- **Close > Open** (bullish candle) must occur on the maturity bar (when `touch_count` reaches `touch_threshold`, default **2**) **or** the bar immediately after (next day only).
- **BE (sheet):** `Close >= Low + (High − Low) × C27` with default **C27 = 1e-7** (Python: `entry_close_min_range_position`; set to **0** to disable this micro-position check).
- **Entry** = next trading day open **after** the bar where `Close > Open`.
- Example: maturity 5/12, bullish candle 5/12 → entry = 5/15 open. Or maturity 5/12, bullish candle 5/13 → entry = 5/16 open.

### Entry price and bar
- **Entry date:** Next trading day after the close-above bar
- **Entry price:** `entry = Open[close_above_bar + 1]`
- **Stop:** `stopPrice = Low[entry_bar] * stop_pct` — **entry bar** low × multiplier (not trigger candle)
- **Target:** `targetPrice = entry * target_pct` — **multiplier form** (standardized)
- **`min_zone_above_pct` (default 0 = off):** when >0, reject entry if a matured zone sits above the trade zone with gap `(nearest_above_low − current_zone_high) / current_zone_high ≤ threshold` (fraction); take the trade if no overhead zone. Nearest above uses matured zone centers in `lookback_long` (non-overlapping bands), same inventory as `zone_above_center`.
- **`require_no_zone_above` (default False):** when True, only take entries with no matured non-overlapping zone above (`PCT_ENTRY_TO_BOTTOM_ZONE_ABOVE` empty / `zone_above_center == 0`). Same inventory as `min_zone_above_pct`, but requires empty overhead rather than a minimum gap.

### Target convention (standardized)
We use **Option B (multiplier form)**:
- `targetPrice = entry * target_pct`
- `target_pct = 1.29` → 29% above entry

**Do not mix with Option A (percent form):** `target = entry * (1 + target_pct)` with `target_pct = 0.29`. Choose one and lock it everywhere.

### BRT_Like_WPBR package (`brt_like_wpbr`, default **False**)

Optional package flag (display name **BRT_Like_WPBR**) that adapts the WPBR two-stage break/confirm/retest concept to **daily** bars on the **existing BRT matured-zone inventory** (Z1 — no weekly bars, no new zone stream). When **False**, the breakout/retest/entry path above is 100% unchanged (classic BRT). When **True**, decisions **B / D / E / F** flip together as one unit, and Stage 1/2 breakout + daily strength metrics turn on:

- **Stage 1 breakout** (bar `b`): `Close[b] > zone_upper` (strict, OPEN-A recommended `>`) **and** `Close[b-1] <= zone_upper`. Zone selection reuses the DI `breakout_zone_pick` / role / YH logic.
- **Stage 2 confirm** (bar `c ≥ b`): first `High[c] > zone_upper × (1 + brt_like_wpbr_confirm_pct)` (default **0.03**). Same-bar allowed. No cap by default (`brt_like_wpbr_confirm_max_bars = 0`, OPEN-C recommended C1). Until Stage 2 fires there is no retest / entry.
- **B — retest scan start:** bar `c + 1` (first session strictly after confirm). `sheet_breakout_scan_start_row_delta` / C19 is **dropped** on this path.
- **D — retest (hold-above):** first `r ≥ c+1` with `Low[r] ≤ upper` **and** `Close[r] > upper` **and** `Close[r-1] ≥ lower`.
- **E — entry window only:** for `di` in `[r, r + brt_like_wpbr_max_days_after_retest]` (default **2**, inclusive), signal when `Close[di] > Open[di]` **and** `Close[di] > upper`; fill = next session open. **Red-to-green and the COUNTIF retest-date gate are disabled on this path** (replaced by the WPBR window). **3-year growth is optional:** when `growth_filter_enabled=true` it still applies (not forced off by BLW); when `false`, WPBR window only.
- **F — too-fast (BQ):** ignored (unimplemented).
- **Strength (audit-only):** daily `brt_*` analogs of the WPBR strength fields + a 0–1 `brt_zone_strength` composite are written to the `BRT_breakout_and_retest_*.csv` (extra columns appear only when this flag is on). Phase 1 does **not** gate entries by strength.

Everything **not** in B/D/E/F stays classic BRT: zone birth/maturity (sheet lag), stops (`stop_pct`), targets (`target_pct`), portfolio/sizing, and all other configured entry filters (`min_spy_compare_*`, `too_high_multiplier`, TKL, consolidation, etc.) still apply as configured. Enable via `-v brt_like_wpbr=true`. Sheet (workbook) parity for this path is a **phase-2 follow-up** (see `drive/brt_sheet_reconcile/BRT_PBR_DAILY_RULES_REQUIREMENTS.md` §7); the engine can run ahead of the sheet.

### WPBR standalone retest scan — `retest_mode` (`wpbr_zones.py`, default **`stop_looking`**)

Applies to the **standalone WPBR system** (`wpbr_zones=true`, weekly pivot zones), not the BLW daily path above. Controls how `find_wpbr_retest_and_signal` terminates the daily forward scan that begins the Monday after the confirmation week (`next_week_start`):

- **`stop_looking` (DEFAULT — matches the sheet `Daily Retest Row`):** first bar with `Low ≤ upper` **and** `Close > upper`, but **only before** the first bar (on/after `next_week_start`) with `Close < zone_lower` (the sheet abandon-"kill" window). If abandon precedes any hold-above bar, the retest is **blank** for that zone. **No** prior-`Close[r-1] ≥ lower` gate — exact sheet parity. Reproduces the pasted META `Daily Retest Row` formula **48/48** (incl. the 7 abandon-kill blanks).
- **`keep_looking` (legacy engine):** unbounded forward scan (no abandon kill) **plus** the prior `Close[r-1] ≥ lower` gate. Gives 41/48 on META (7 engine-only retests where the sheet is blank).

Wire via `-v retest_mode=stop_looking|keep_looking` (BRTConfig `wpbr_retest_mode`; `retest_mode` / `wpbr_retest_mode` aliases). Default is `stop_looking` so `run_wpbr.bat` / DailyRun match the sheet with no extra flag; use `keep_looking` for A/B against the old behavior. **Product decision (2026-07-22): the sheet wins** — engine adopts the sheet's abandon-kill retest as the default; the flag only exists to A/B the legacy scan. The sheet formulas are unchanged.

### Support / Resistance Test (approach-direction labels)
- **Not** touch confirmations; they indicate whether price is testing the zone as support or resistance.
- **Overlap (per bar t):** `overlap[t] = (low[t] <= zone_upper) AND (high[t] >= zone_low)`.
- **Support Test:** price approached from above → `support_test[t] = overlap[t] AND (close[t-1] > zone_upper)`.
- **Maturity alignment:** When Support Test is **enabled** (`support_test_enabled`, default **True**), overlap counts toward Support Test only on bars **strictly after** the zone **maturity bar** (the bar where `touch_count_long` first reaches **`touch_threshold`**). Overlap on the maturity bar itself does not count; the first eligible bar is the next session. Disable the whole Support Test anchor with **`support_test_enabled = False`** or CLI **`--no-support-test`** — Level Acceptance 7/10 can still apply without the ST anchor.
- **Resistance Test:** price approached from below → `resistance_test[t] = overlap[t] AND (close[t-1] < zone_low)`.
- Used to anchor Level Acceptance to the correct zone when multiple zones interact on consecutive days.

### Level Acceptance (7/10 rule) and anchoring
- Before a buy triggers: at least `level_acceptance_required` of the last `level_acceptance_window` bars (ending on trigger day) must close above the **zone lower** of the anchored zone.
- **Anchoring rule (fix for consecutive-zone timing):** When `support_test_enabled`, Level Acceptance is evaluated only when Support Test is TRUE on the current bar or the prior bar (with overlap-only-after-maturity as above). If Support Test is TRUE today → evaluate acceptance vs today’s ZoneLower; else if Support Test was TRUE yesterday → evaluate vs yesterday’s ZoneLower; else Level Acceptance fails (trade blocked). If Support Test is disabled, the ST anchor is skipped (`au_anchor_ok` treated as satisfied for anchoring). This ties the 7/10 gate to the support-tested zone and avoids wrong-zone evaluation.
- Zone lower = zone_center × (1 − band_pct). Trigger = maturity bar (`touch_count_long` reaches `touch_threshold`); close-above can be same day or next day.
- Default: 7/10 (enabled). Use `--level-acceptance 0/10` to disable.

### Tradeable Key Level (AC) — legacy / optional
- **Spreadsheet:** not used in the current sheet; Python keeps the feature **off** by default (`tradeable_key_level_enabled = False`).
- **Objective (when enabled):** Require both historical structural maturity (long window) and recent structural engagement (short window) before a buy signal is allowed.
- **AC = Tradeable Key Level:** TRUE only when:
  - `touch_count_long >= touch_threshold` (same threshold as zone maturity; default **2**)
  - `touch_count_short >= 2` (touches within short lookback, default 105 bars)
- **Buy gate (when enabled):** `OR(AC[current_bar], AC[prior_bar])`.
- **Parameters:** `lookback_short = 105`. Use `--tradeable-key-level-off` if enabling elsewhere.

### Tight Range Qualifier
- Blocks levels that mature in structurally compressed ("dead range") environments.
- **Evaluated** on the maturity-touch row only; **required** for buy (current or prior row per Excel).
- **Formula:** `RangePct = (MAX(High over last N bars) / MIN(Low over last N bars)) − 1`
- **Pass:** `RangePct > threshold` (default 35%)
- **Fail:** `RangePct ≤ threshold` or insufficient lookback → trade blocked.
- **Parameters:** `tight_range_threshold_pct = 0.35` (sheet **C7**), `tight_range_lookback = 105` (sheet **C24**), `tight_range_enabled = True`.
- **Rationale:** NVDA Trade 1 (2021) matured after ~5 months of tight compression (25.98% range); blocked. NVDA 2–5 (larger expansion) passed.
- Use `--tight-range-off` to disable. Use `--tight-range-threshold 0.40` to adjust.

### Stop convention
- **Stop reference bar:** Trigger (maturity-touch) bar — matches manual system.
- **Multiplier:** `stopPrice = Low[trigger_bar] × stop_pct`, e.g. `stop_pct = 0.934` (6.6% below trigger bar low)
- **Fraction below:** `stopPrice = Low[trigger_bar] × (1 - stop_pct)`, e.g. `stop_pct = 0.069` (6.9% below)

---

## 3.5 Sheet zone ladder (DE / DF / DG) — optional parity

The spreadsheet maintains a **stack** of up to eight zone bands (CG/CH through DB/DC). When lagged **CE/CF** (from columns AG/AH, `ROW−C14`) are non-empty, a new zone enters the top rung and older rungs shift down. **DE** is the **lower** bound of the **first** rung (in order) whose band overlaps the current bar (`High ≥ zone_lower` and `Low ≤ zone_upper`). **DF** and **DG** are the matching upper bound and **maturity bar** (availability row) for that rung.

Python (`rocket_brt.py`) can mirror this with `zone_low`/`zone_high` as AG/AH analogs and `sheet_maturity_lag_bars` = **C14**.

- **Export for diffing:** `python rocket_brt.py … -s NVDA --emit-sheet-parity` → `BRT_SheetParity_NVDA_<ts>.csv` includes **SHEET_DE_PASTE**, **SHEET_DF_PASTE**, **SHEET_DG_PASTE** so you can paste Google Sheet values for the same dates and spot the first mismatch.
- **Stricter entries:** `--sheet-ladder-active-zone` with `-v entry_eval_mode=row_local` uses ladder **DG** as the active maturity bar for row-local gating (instead of only “pending zones that overlap price”).

If Excel AG/AH differ from Python’s per-bar zone columns (e.g. forward-fill), CE/CF and the ladder may diverge—compare **CE_LAG_ZONE_*** in the parity CSV to the sheet.

See **`SHEET_PARITY_DIFF.md`** for a short manual workflow.

---

## 4. EXIT LOGIC

**When we have an open position** and process bar i (first bar = entry day):

### Resolution order (first match wins)
1. **Gap down:** `Open[i] <= stopPrice` → exit at `Open[i]`, type `GAP_DOWN`
2. **Gap up through target:** `Open[i] >= targetPrice` → exit at `Open[i]`, type `GAP_UP`
3. **Intraday stop:** `Low[i] <= stopPrice` → exit at `stopPrice`, type `STOP_LOSS`
4. **Intraday target:** `High[i] >= targetPrice` → exit at `targetPrice`, type `TARGET`
5. Else: no exit this bar

**When both stop and target are inside the same bar's range:** Stop wins (checked before target). Conservative and correct.

### Exit date
Date of bar i (the bar where the exit condition was met).

---

## 5. FROZEN CONVENTIONS (DO NOT DRIFT)

**Locked as of v1.1. Do not change for performance tuning.**

| Convention | Value | Rationale |
|------------|-------|-----------|
| **Close-above window** | 1 day | Close>open (bullish candle) must be on maturity-touch day OR the day after only; entry = next open after |
| **Stop reference bar** | Trigger (maturity-touch) bar | `Stop = Low[trigger_bar] × stop_pct` — matches manual |
| **Stop form** | Multiplier | `stop_pct = 0.934` (6.6% below); do not mix with fraction form |
| **Target form** | Multiplier | `target_pct = 1.29` (29% above); multiplier form only |
| **Band width** | `band_pct = 0.02` | Configurable; default 2%; lock when backtesting |
| **Exit priority** | Gap down → Gap up → Stop → Target | Fixed order; stop checked before target |
| **Pivot tie-break** | Earliest bar | When multiple bars share local max/min |

**Parameter drift creates phantom edge.** Freeze before re-backtest; do not tweak after viewing results.
