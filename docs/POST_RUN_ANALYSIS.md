# Post-run analysis (all systems)

Optional deep charts + HTML for any **TBN**-hosted system that writes `{prefix}_Closed_<ts>.csv` /
`{prefix}_Summary_<ts>.csv`. Cheap sheet enrichments run automatically after each
backtest; charts/deep HTML are **not** part of DailyRun.

**TBN** = Twin Beacon Networks engine (`rocket_tbn.py`). **BRT** in the table below is the Break-and-ReTest *system* prefix — see `docs/TBN_VS_BRT.md`.

## Systems / prefixes

| Prefix | System | Chart style |
|--------|--------|-------------|
| **RL** / DB | Rocket Launcher (dip-buy) | SMA20/50/100/200 + dip band + IN/OUT/stop |
| **BRT** / WPBR / YH / VEC / PBR | Zone systems | Close + SMA50 + zone bands from Closed `ZONE_CENTER` + IN/OUT/stop |
| **IND** / MTS / RS / ADX | Other | Close + SMA50 + IN/OUT/stop |
| **SB** / **MVCP** | StockBee / Minervini VCP (standalone writers) | Close + SMA50 + IN/OUT/stop |

Auto-detect: scan `drive/{PREFIX}_Closed_{stamp}.csv`, or pass `--system` / `--closed`.

## Cheap (every run)

Emitted after Summary write:

| Artifact | Columns / files |
|----------|-----------------|
| Closed | `ONE_LINER` |
| Summary | `FIT`, `FIT_SCORE`, `FIT_SCORE_ROBUST`, `MAX_WIN_PCT`, `AVG_PNL_PCT_WO_MAX`, `MEDIAN_PNL_PCT` (diag only), `OUTLIER_PCT_OF_WINS`, `FIT_ASSESSMENT` (RL also keeps `RL_FIT`); `PAUL_SCORE` (0–8: +1 each if ≥ max(mean,median) for PCT_WINS / TOTAL_PNL / SHEET_PNL / AVG_PNL_PCT / AVG_PNL_PCT_WO_MAX / AVG_TRADES_PER_YEAR; +1 each if ≤ min(mean,median) for OUTLIER_PCT_OF_WINS / AVG_DAYS_HELD) |
| Hints | `{prefix}_ImproveHints_<ts>.csv` + `.md` + `.html` |

`FIT_SCORE` (headline) is unchanged: mean `AVG_PNL_PCT` drives the avg-pnl points bucket.

**Before → after (robust):** median Closed `PNL %` was retired as the robust PnL input (it over-punished ~50% WR books). Current `FIT_SCORE_ROBUST` uses the same point rules but:

1. **Leave-max-win-out** mean trade `PNL %` (drop the single largest winning trade, then re-average) for the avg-pnl points bucket — `AVG_PNL_PCT_WO_MAX`. Sheet PnL is scaled the same way (fixed-notional share of the dropped win).
2. Soft outlier penalty: **−1** if top win &gt;50% of sum of winning PnL% **or** that trade’s fixed-notional share &gt;60% of sum(PnL%); **−2** if &gt;70% of win PnLs or &gt;80% of sheet share.

`MEDIAN_PNL_PCT` remains on Summary for inspection but is **not** used in the robust score. Process write-up (formula + AMZN before/after): `drive/paul_experiments/system_setup_process.html` § FIT / robust (mirrored in `docs/system_setup_process.html`).

When robust is materially weaker (score ≥2 below headline, or tier drop), `FIT_ASSESSMENT` appends `robust Low/Med… (wo-max avg …%, outlier …% of wins)`.

Use **headline** for continuity / sheet paste; use **robust** for promotion gates (“≥50% wins, sheet &gt;10k, ≥0.36 tpy, edge not carried by one outlier”).

### Parameter tweaks + peer-learn (ImproveHints)

Emitted automatically with cheap ImproveHints (no extra flag). Additive sections in the same
`{prefix}_ImproveHints_<ts>.*` artifacts.

**How to use (PO process):** treat rows as **candidate hypotheses / missed-trade evidence**, not as
orders to optimize. If nothing actionable appears and human ToS review finds no concrete miss,
**do not hunt params**. When acting: one knob, ≤2 pre-agreed alternatives, ToS before/after,
judge quality / thesis / DD / reconcile—not max profit. Adopt only with PO sign-off + reconcile
freeze. Template: `docs/HYPOTHESIS_TEST.md` · process steps 5–8 / 12 in
`drive/paul_experiments/system_setup_process.html`.

| Section | What it scores | Direction signals |
|---------|----------------|-------------------|
| **band_pct** | Weak fills (low `MAX_PRICE` MFE then STOP/TIME) → **tighten**; RejectedFills near-band rejects with OHLC follow-through → **loosen** | Counts, % of scored, confidence |
| **target_pct** | TARGET exits that keep running (in-hold MAX past target, or post-exit OHLC) → **expand**; approach 50–95% of entry→target then fail → **contract**; TARGET held ≥100d → **contract** (turnover / Ann_ROR over max single PnL) | Same |
| **stop_pct** | STOP then rebound above entry (OHLC) or MFE≥5% then STOP → **expand**; never-worked losers (MFE&lt;2%) → **hold** / tighten only if fat losses cluster | Same |
| **peer-learn** | Hold-range overlaps vs peer `*_LatestRun_Closed.csv` (or newest stamp) under `drive/` | Adopt only when countable (peer TARGET after our STOP; wider stop won; longer hold won) |
| **slow-winner patterns** | `slow_target_grind` (TARGET ≥100d); `winner_peak_giveback` (win but MFE−PnL ≥10pp); `early_run_long_tail` (+10% by day≤25 then hold ≥80d) → closer target / trail / shorter time-stop **hypotheses** | Evidence counts; one knob |

**Opposing lenses:** expand vs hold/contract (and tighten vs loosen) can both fire on **different trade subsets**. `param_tweak_hints.collect_param_tweak_hints` reconciles those into **one tension card** (direction lean or `mixed`, confidence capped at `medium`) so ImproveHints / ImprovePriority do not ship two high-confidence opposite knob moves — prefer one coherent hypothesis / A/B arm (see `docs/system_setup_process.html` steps 5–6 and `docs/HYPOTHESIS_TEST.md`).

Heuristics are documented on each row (`HEURISTIC` column / MD bullets). Confidence is
`high` / `medium` / `low` / `insufficient` — do not change production knobs on thin samples.
Hints suggest a **direction** for a hypothesis test; they are not a license for combinatorial sweeps.

**YH param-hint A/B:** `run_yh_param_hint_ab.bat <stamp>` (driver `tools/yh_param_hint_ab.py`) runs control vs one alt each for top ImproveHints `stop_pct` / `target_pct` / `band_pct` cards (frozen `run_yh.bat` baselines; ≤1 alternative per knob). Writes `drive/paul_experiments/yh_param_hint_ab/comparison.html`. Deep ImprovePriority HTML (`write_improve_priority_html`) puts **Parameter suggestions** first (with a **Run AB** column for YH), then taken-trade patterns / peer-learn — hypothesis-test framing, not optimal search (`docs/HYPOTHESIS_TEST.md`).

- **Closed-only** always runs (DailyRun-safe).
- **OHLC extras** (post-exit continuation, stop rebound, RejectedFills follow-through) run when
  in-run `tickers` are passed to `write_analysis_artifacts`, or when deep CLI passes `--data-dir`
  (e.g. `--refresh-cheap`).
- Peer scan reads other systems’ Closed books from `drive/`; it does not call
  `tools/sb_system_convergence.py` (same overlap idea, lighter).
- **Future / tooling:** teach post-run analysis to surface near-miss / band-touch more explicitly
  across zone systems (beyond RL `--missed-moves`) so evidence for hypothesis tests is easier to count.

`FIT_SCORE` trades/year component (`AVG_TRADES_PER_YEAR` in `assess_symbol_fit`): higher frequency is rewarded; there is no “busy” penalty for high tpy.

| `AVG_TRADES_PER_YEAR` | Points |
|-----------------------|--------|
| ≥ 1.0 | +2 |
| ≥ 0.36 | +1 |
| 0 &lt; tpy &lt; 0.2 | 0 (note: `rare setups`) |
| otherwise | 0 |

### RL post-TARGET quick stops

ImproveHints / SymbolAssessments may flag **TARGET → quick STOP** re-entries. For RL, prefer **`rl_post_target_reentry_bars` + `rl_post_target_reentry_mode`** (`stop_loss` with `rl_post_target_stop_pct`, or quality gates `min_stack` / `under_sma_limit`, or `none` cooldown) over a calendar **`symbol_reentry_cooldown_days`** (BRT-only / unwired in `rocket_rl`, and it kills NTRA-style ladders). Defaults are **bars=0 / off**. See `docs/TRAILING_STOPS.md` §2.1.

- **RL:** `write_rl_post_reports` → `write_rl_analysis_artifacts`
- **BRT / WPBR / YH / IND / MTS / RS / …:** `write_all_outputs` → `write_analysis_artifacts`
- **SB / MVCP:** `rocket_stockbee_burst.write_outputs` / `rocket_minervini_vcp.write_mvcp_outputs` → `write_analysis_artifacts`

## Deep (manual)

```bat
rem RL (wrapper keeps old commands working)
python stock_analysis\rl_post_run_analysis.py --stamp 260729143509 --charts
python stock_analysis\rl_post_run_analysis.py --symbols CRWD,AU -w 4
python stock_analysis\rl_post_run_analysis.py --stamp 260729183512 --missed-moves --no-charts -s NVDA,AMD,TSLA

rem Any system
python stock_analysis\post_run_analysis.py --system RL --stamp 260729143509 --charts -w 4
python stock_analysis\post_run_analysis.py --system BRT --stamp 260729143513 --charts -w 4
python stock_analysis\post_run_analysis.py --system RS --stamp 260729143513 --charts -w 4
python stock_analysis\post_run_analysis.py --stamp 260729143509
python stock_analysis\post_run_analysis.py --closed drive\BRT_Closed_260729143513.csv --no-charts
```

| Flag | Meaning |
|------|---------|
| `--system` | `RL\|BRT\|WPBR\|YH\|MTS\|RS\|IND\|…` (default: auto) |
| `--stamp` / `-t` | Run id (default: `drive/last_run_ts.txt`) |
| `--workers` / `-w` | Chart ProcessPool size; **default `-1` → min(4, CPUs)**; `0` = sequential |
| `--charts` / `--no-charts` | PNGs on by default for this script |
| `--missed-moves` | **RL/DB only:** heuristic near-miss + blind-spot scan (not DailyRun) |
| `--missed-min-gain` | Min fwd max-gain % to keep a NEAR_MISS (default 8) |
| `--missed-blind-min-gain` | Min fwd max-gain % to keep a BLIND_SPOT (default 12) |
| `--refresh-cheap` | Re-write ONE_LINER / FIT / ImproveHints before HTML |
| `--symbols` / `-s` | Subset of tickers |

Outputs:

```
{prefix}_Charts_<ts>/{prefix}_<SYM>_<ts>.png
{prefix}_SymbolAssessments_<ts>.html
{prefix}_ImprovePriority_<ts>.html
{prefix}_MissedMoves_<ts>.csv          # with --missed-moves (RL/DB)
```

### Missed / almost-taken moves (RL v1)

Optional deep path only (`--missed-moves`). **Not** part of DailyRun.

**What exists today (engine artifacts):**

| Artifact | Scope | Useful for misses? |
|----------|-------|--------------------|
| `RL_Watchlist` | **Last bar only** — `NEAR_50_ZONE` / `PENDING_FILTERS` + miss tags (`EXP ATR SLOPE…`) | Live watch, not history |
| `RL_Scanner` | Last-bar pending fills | Same |
| Closed / Open / underwater / pivots | Taken trades / structure | Context, not reject log |
| Historical reject CSV | **None** — AWK/`rocket_rl` do not log every blocked dip | — |

**v1 approach:** replay dip+stack on OHLC+SMAs with Report params; when primary gate fires but secondary gates fail → **NEAR_MISS** (+ forward return / max gain / TARGET-like); when stack+near-dip then a material rally but primary incomplete → **BLIND_SPOT** (“weren’t looking”). Surfaces in SymbolAssessments §6 and ImprovePriority “Why we miss winners”.

**Limits:** heuristic ≠ perfect MarkTen (no full in-position / flush / IND / SPY-TC / entry-window fidelity unless those Report flags are on and SPY is loaded). Confirm candidates on charts / agent review before changing production gates.

## Modules

| Path | Role |
|------|------|
| `stock_analysis/rocket_post_analysis.py` | Shared one-liners, FIT, hints, charts (+ workers) |
| `stock_analysis/param_tweak_hints.py` | Band/target/stop + peer-learn heuristics (ImproveHints) |
| `stock_analysis/rocket_rl_analysis.py` | Thin re-export (backward compatible) |
| `stock_analysis/post_run_analysis.py` | System-agnostic deep CLI |
| `stock_analysis/rl_post_run_analysis.py` | RL wrapper (`--system RL`) |
| `stock_analysis/rl_missed_moves.py` | RL near-miss / blind-spot heuristic (`--missed-moves`) |
