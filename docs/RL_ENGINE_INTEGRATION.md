# Rocket Launcher (RL) → `rocket_brt.py` Integration Plan

Engineering deep-dive and implementation roadmap. **Gold standard:** `Drive/RL_LatestRun_*` from run **`260629143410`** (2026-06-29 14:34:10 ET).

---

## Executive summary

Rocket Launcher is **not** a variant of BRT zone/retest logic. It is a separate **50-SMA dip-buy** strategy (optional 100-SMA and Dive Bomber subsystems) implemented today in **`portfolio_audit.awk`** (~2,500 lines). `rocket_brt.py` handles **BRT / IND / YH** via zone breakout + retest (or IND-only indicator scan).

**Goal:** Port RL into Python inside `rocket_brt.py` with `rl_mode=true`, reach **trade parity** on the 76-stock gold universe, then retire the AWK dependency for production runs.

**Authority:** `portfolio_audit.awk` and its `-v` variable passthrough are the **authoritative math** (dip band, acceptance, target 1.20, trail arming, all gates). The RL spreadsheet is reference only.

---

## Decisions (locked)

| Topic | Decision |
|-------|----------|
| Math source | **AWK** (`portfolio_audit.awk` + `-v` defaults) |
| RL vs BRT | **Separate runs** — `rl_mode=true` for dip-buy; separate invocation for BRT zone/retest |
| No combined mode | No `rl_mode=both`; one engine per backtest pass |
| Parity universe | **76 stocks** — `data/rl_gold_universe.txt` (+ SPY loaded first by runner) |
| Full universe | Run ad hoc when testing changes; not the CI gold gate |
| RL100 / Dive Bomber | **Defer** until 50-trigger matches |
| Trails / flush | **Off by default**; enable only via explicit `-v` (e.g. `rl_trail_profit=0.14`) |

---

## Gold standard (today's LatestRun)

| Artifact | Value |
|----------|-------|
| Run timestamp | `260629143410` |
| Closed trades | **204** (117 TARGET / 87 STOP_LOSS) |
| Universe | **76** symbols in summary (**75** with ≥1 trade; SPY = 0) |
| Open positions | **2** (STLD, TWLO) |
| Watchlist | **28** (as-of 20260629) |
| Scanner | **2** (MTSI, AMKR — ENTRY_ALLOWED=0) |
| Audit Total_PNL (scaled) | **$1,463,818.75** |
| Ann_ROR / Max_DD | **83.17% / 11.77%** |
| Profit factor | **4.94** |

### Verification trades (must match exactly)

```
TSLA  20170301→20170609  entry 16.95  exit 25.12  +48.22%  TARGET   100d
CLS   20260522→20260601  entry 360.60 exit 425.11 +17.89%  TARGET   11d
CCJ   20210616→20210708  entry 19.94  exit 17.90  -10.21%  STOP_LOSS 23d
AMKR  20260223→20260303  entry 47.59  exit 44.27  -6.97%   STOP_LOSS 9d
STLD  open 20260626 @ 245.39  stop 225.22  target 292.52
TWLO  open 20260622 @ 184.48  stop 167.51  target 223.35
```

Regression note: `RegressionReport_260629143410.md` — **RL_Closed identical** vs prior run; Open/Scanner differ only on live price fields.

---

## Current architecture

```
DailyRun.bat [2/8]  →  run_audit.ps1
                         ├─ gawk portfolio_audit.awk  (+ SPY.csv first, symbol CSVs)
                         └─ rl_emit_brt_mirror.py     → BRT_Closed_RL_*, audit row

DailyRun.bat [3–5/8] → rocket_brt.py  (BRT whitelist / IND full / YH zones)
```

| System | Engine | Output prefix | Entry model |
|--------|--------|---------------|-------------|
| **RL** | AWK | `RL_` | 50-SMA dip, next open |
| **BRT** | Python | `BRT_` | Zone BO + retest |
| **IND** | Python | `IND_` | Indicator-only (`indicator_buy=only`) |
| **YH** | Python | `YH_` | Year-high zones |

`rl_emit_brt_mirror.py` converts RL native CSV → BRT column shape for comparison tooling. It does **not** change fill logic.

---

## RL algorithm (50-trigger) — reverse engineered

Source: `portfolio_audit.awk` lines ~1203–1410 (entry), ~894–1200 (exit while in position). Human-readable: `ENTRY_LOGIC_COMPARISON.md`.

### Entry (signal bar → fill next open)

**Precondition:** flat, `SMA_QUAL=1`, bar index > 54.

**Phase A — Dip candle (all required):**

| Gate | AWK variable | Default |
|------|--------------|---------|
| SMA50 rising | `sma50rising` | SMA50[j] > SMA50[j−4] |
| In dip band | `inthe50zone` | `y_sma*(1-(DIP-1)) < low < y_sma*DIP` |
| Green day | `uptick` | close > open |
| Close above SMA50 | `closeabove50sma` | close > yesterday SMA50 |
| Bull stack | | SMA20 > SMA50 > SMA100 > SMA200 |

**Phase B — Post-dip filters (all required):**

| Gate | Default |
|------|---------|
| Expansion | ≥1 day in 10d: close ≥ prior SMA50 × **1.163** |
| Acceptance | Rolling 10d count(close > prior SMA50) ≥ **8** |
| Cut losers | High % above y-SMA50 < **0.25** |
| ATR band | ATR% ∈ [**2.44%**, **8.48%**], ATR < **200**, price ≥ min |
| Peak cap | Max historical close% above SMA50 < **200%** |
| Slope | SMA50 30d growth ≥ **0.0643** (0 = off) |
| Shock | If threshold=0: pass; else shocks in 120d ≤ 1 |
| Not too low | next open ≥ today low × **0.934** |
| SPY | If `SPY_INCLUSION=0`: pass (DailyRun default) |
| Volume | If `VOL_PCT_THRESHOLD>0`: entry vol gate |

**Phase C — Fill:**

- Entry: **next session open**
- Stop: **signal-day low × 0.934** (not entry × stop_pct)
- Target: **prior-day SMA50 × 1.20** (updated daily while open)
- Too high: next open ≤ low × **1.14** × **0.934**
- Size: **RL_CASH / entry_open** shares (default **$47,500** notional)
- One open position per symbol; **no max_positions cap**

### Exit priority (while in position)

1. **FLUSH_EXIT** — portfolio underwater `RL_FLUSH_DAYS` consecutive days (two-pass; default **off**)
2. **Partial exit** — `PARTIAL_EXIT_TARGET` (default **off**)
3. **Trail 1** — high ≥ entry×(1+`RL_TRAIL_PROFIT`) → stop = entry×(1+`RL_TRAIL_STOP`) (defaults **0** = off)
4. **Trail 2** — tier-2 profit/stop (defaults **0** = off)
5. **Stop** — low ≤ stop (entry day uses **close** for stop check)
6. **Target** — high ≥ SMA50-based target → fill max(target, open)
7. **Timed exit** — after profit ≥ **29%**, count **RL_EXIT_DAYS** (default 10000 ≈ off)

Milestone counters (10/20/30/40/50/60%) and MAE/max drawdown per trade are recorded on close.

### Subsystems (later phases)

- **RL100** (`RL100_TOGGLE=1`): parallel 100-SMA dip system → `RL100_Closed_*`
- **Dive Bomber** (`DB_TOGGLE=1`): inverse stack short → `DB_Closed_*`

DailyRun uses **50-trigger only** (`SMA_QUAL=1`, RL100/DB off).

---

## BRT vs RL — why they diverge

| Dimension | RL (AWK) | BRT (Python) |
|-----------|----------|--------------|
| Signal | SMA dip in uptrend | Mature zone touch → DI breakout → retest |
| Stop anchor | Signal **low** × 0.934 | Entry × stop_pct |
| Target | **Moving SMA50** × 1.20 | Entry × target_pct (or ATR for IND) |
| Trails | Profit-gated step stops | Continuous ratchet (usually off) |
| Portfolio | Optional flush; no position cap | max_positions |
| Sizing | Fixed RL_CASH | brt_cash / aggressive equity |

`use_sma50=true` in BRT only changes **target anchor** — it does **not** implement RL entry gates.

---

## Flag model in `rocket_brt.py`

**Separate DailyRun invocations** (same as today):

| Step | Command shape | Prefix |
|------|---------------|--------|
| Rocket Launcher | `-v rl_mode=true` (+ RL params as needed) | `RL_` |
| BRT zone/retest | `-v rl_mode=false -v brt_zones=true ...` | `BRT_` |
| IND | `-v indicator_buy=only ...` | `IND_` |
| YH | `-v yh_zones=true -v brt_zones=false ...` | `YH_` |

When `rl_mode=true`, the engine skips zone/retest/IND paths and runs the 50-SMA dip-buy loop only.

```python
rl_mode: str = "false"       # true | false
rl_cash: float = 47_500.0    # RL_CASH
rl_target_pct: float = 1.20  # not BRT's 1.21
rl_trail_profit: float = 0.0 # off unless passed in
rl_flush_days: int = 0       # off unless passed in
# Full defaults: stock_analysis/rocket_rl_config.py
```

### `_output_file_prefix(cfg)` precedence

```
if rl_mode == true:       → "RL"
elif indicator_buy == only: → "IND"
elif yh_zones-only:        → "YH"
else:                     → "BRT"
```

Target DailyRun RL step (after parity):

```bat
python stock_analysis\rocket_brt.py data\newdata\data -o drive -w 6 --no-regression ^
  -v rl_mode=true ^
  -s "@data/rl_gold_universe.txt"   rem or inline comma list
```

---

## Implementation phases

### Phase 0 — Parity harness ✅ (this PR)

- `tools/run_rl_parity.py` — compare `RL_Closed_*` trade keys vs Python output
- `stock_analysis/rocket_rl_config.py` — RLConfig defaults = AWK BEGIN block
- This document

### Phase 1 — Core 50-trigger bar engine

New module `stock_analysis/rocket_rl.py`:

- Per-symbol OHLCV loop (reuse data loading from `rocket_brt.py`)
- SMA 20/30/50/100/200 (reuse precomputed CSV cols 8–12 when present)
- ATR(14), acceptance rolling window, expansion lookback, peak_cl, shock detector
- Entry gate chain + next-open fill
- Exit stack (stop/target/trails/timed; flush deferred to Phase 2)
- Emit native **79-column** `RL_Closed` / **13-column** `RL_Open` schema

Wire into `rocket_brt.py`:

- `rl_mode=true` → call `run_rl_backtest()` instead of zone pipeline
- Skip pivot/zone/DI work when RL-only (performance)

**Gate:** `run_rl_parity.py` passes on DailyRun symbol list — 204 trades, 117W/87L, 6 anchor trades exact.

### Phase 2 — Scanner, watchlist, flush, audit row

- Last-bar scanner + watchlist scoring (NEAR_50_ZONE / PENDING_FILTERS)
- Two-pass `RL_FLUSH_DAYS` portfolio logic
- `RocketLauncher.csv` / summary row compatibility
- Drop `rl_emit_brt_mirror.py` from critical path (optional keep for regression)

### Phase 3 — RL100 + Dive Bomber (deferred)

Port after 50-trigger gold parity is stable.

### Phase 4 — DailyRun cutover

Replace `run_audit.ps1` in `DailyRun.bat` with `rocket_brt.py -v rl_mode=true` and `-s` from `data/rl_gold_universe.txt`.

Keep AWK fallback until parity stable for 2+ weeks.

---

## Code reuse map

| RL need | Existing Python |
|---------|-----------------|
| OHLCV load / symbol loop | `rocket_brt.py` data paths |
| SMA arrays | `_compute_sma_arr`, precomputed cols via `precompute_csv_smas.py` |
| ATR | BRT ATR helpers |
| Closed/Open CSV writers | Adapt `write_brt_closed` **or** native RL writer matching 79 cols |
| Audit metrics | `compute_metrics` + scaling in `rl_emit_brt_mirror.py` |
| Pivot enrich on close | Already in AWK END + mirror enrich — optional Phase 2 |
| SPY benchmark | SPY.csv load pattern from AWK |

**Must implement fresh:** dip zone gates, acceptance counter, expansion scan, peak_cl tracker, shock rehab, RL exit priority, profit-gated trails, timed exit counter, scanner/watchlist last-bar logic.

---

## Test strategy

1. **Trade-key regression:** `(SYMBOL, DATE_OPENED, DATE_CLOSED, EXIT_TYPE)` set must match exactly.
2. **Field regression:** entry/exit prices, PNL %, DAYS HELD, stops/targets on full closed file.
3. **Aggregate regression:** wins/losses, Total_PNL, Ann_ROR, Max_DD from audit row.
4. **Open book:** symbol count, entry dates, stop/target levels (prices may drift with data updates).
5. **Symbol-scoped dev tests:** TSLA, CLS, CCJ, AMKR during development (`-s SYMBOL -w 0`).

Run:

```powershell
python tools/run_rl_parity.py --gold Drive/RL_LatestRun_Closed.csv
python tools/run_rl_parity.py --run --symbols-file data/rl_gold_universe.txt
```

---

## File index

| Path | Role |
|------|------|
| `stock_analysis/portfolio_audit.awk` | **Authoritative** RL engine + math |
| `data/rl_gold_universe.txt` | 76-stock parity universe |
| `run_audit.ps1` | AWK runner + mirror |
| `stock_analysis/rl_emit_brt_mirror.py` | RL → BRT-shaped CSV |
| `stock_analysis/ENTRY_LOGIC_COMPARISON.md` | Entry gate reference |
| `stock_analysis/rocket_rl_config.py` | Python RL defaults (= AWK BEGIN) |
| `tools/run_rl_parity.py` | Parity tests |
| `Drive/RL_LatestRun_Closed.csv` | Gold standard closed |
| `Drive/BRT_Audit_Report_RL_260629143410.csv` | Gold standard metrics |
