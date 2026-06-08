# Trailing stops and stop management — requirements reference

This document explains how stops, targets, and “trailing” behavior work across **Rocket Launcher** (live audit / `portfolio_audit.awk`), **BRT** and **IND** backtests (`rocket_brt.py`), and the **gettarget** live calculator (`gettarget.py`). It is written for operators and developers who need to know which knobs apply where and why results differ between systems.

---

## 1. Executive summary

| System | Engine | Trailing style | Typical DailyRun |
|--------|--------|----------------|------------------|
| **Rocket Launcher (RL)** | `portfolio_audit.awk` | **Profit-gated lock-in** (arm trail after % gain, then fixed stop level) | Step 2 `run_audit.ps1` |
| **Rocket Launcher 100 (RL100)** | Same AWK | Same pattern, separate params | Same (if `RL100_TOGGLE` on) |
| **Dive Bomber (DB)** | Same AWK | **No trailing** — fixed stop above entry | Off by default |
| **BRT whitelist** | `rocket_brt.py` | **Optional gain-based ratchet** (`trailing_stop_increment`); DailyRun **off** | Step 3 — percent stop/target |
| **IND full universe** | `rocket_brt.py` | Same exit engine as BRT; DailyRun uses **ATR** stops/targets + **ATR schedule**, trailing **off** | Step 4 |
| **Live open positions** | `gettarget.py` | Mirrors **BRT** math (`atr_increment`, `atr_progress`, floors) | Step 6 DailyRun |

**Important:** “Trailing” means different things in RL vs BRT/IND. RL trails by **jumping the stop to a fixed % of entry** after a profit milestone. BRT/IND trail by **adding 1% of entry per N% of peak gain** (when `trailing_stop_increment > 0`).

**BRT and IND share one exit implementation.** IND is not a separate stop engine; it is `rocket_brt.py` with indicator entry filters and (often) ATR-based exits.

---

## 2. Rocket Launcher (`portfolio_audit.awk`)

Rocket Launcher simulates the **50-SMA dip-buy** strategy (and optionally **100-SMA**, **Dive Bomber** shorts). Stops and targets are updated **each bar while in a position**.

### 2.1 Initial stop and target (RL, long)

On entry (next session open after signal):

| Field | Default | Meaning |
|-------|---------|---------|
| `RL_STOP_PCT` | `0.934` | Initial stop = **signal-day low × 0.934** (~6.6% below that low, not below entry open). |
| `RL_TARGET_PCT` | `1.20` | Target = **prior session SMA50 × 1.20** (20% above SMA50; target moves with SMA). |
| `RL_TOO_HIGH` | (varies) | Blocks entry if next open is too far above signal-day low. |

`original_stop` and `original_target` are stored on the closed-trade row for audit.

### 2.2 RL trailing stops (profit-gated, two tiers)

Controlled by AWK variables (overridable via `run_audit.ps1` `-RLTrailProfit`, etc.):

| Variable | Default | Role |
|----------|---------|------|
| `RL_TRAIL_PROFIT` | `0` | **Off by default.** If > 0: when **High ≥ entry × (1 + RL_TRAIL_PROFIT)**, arm Trail 1. |
| `RL_TRAIL_STOP` | `0.0` | Once Trail 1 arms: **rl_stop = entry × (1 + RL_TRAIL_STOP)** (e.g. `0` = breakeven, `0.045` = +4.5% above entry). |
| `RL_TRAIL_PROFIT2` | `0` | Second tier: when **High ≥ entry × (1 + RL_TRAIL_PROFIT2)**, arm Trail 2 (overwrites Trail 1). |
| `RL_TRAIL_STOP2` | `0` | Trail 2 stop = **entry × (1 + RL_TRAIL_STOP2)** (e.g. `0.20` = stop 20% above entry). |

**Behavior:**

1. Trailing does **not** ratchet continuously with new highs.
2. It **arms** when price reaches a profit threshold, then **replaces** `rl_stop` with a fixed multiple of entry.
3. Trail 2, if configured, **replaces** Trail 1 when the higher profit threshold is hit.
4. Exit type on stop: `TRAIL_STOP`, `TRAIL_STOP2`, or `STOP_LOSS` (if trail never armed).

**Entry-day stop check:** On the entry session only, stop is tested against **Close**, not Low, to avoid false stop-outs on wide-range entry days.

### 2.3 Other RL exits (not trailing)

| Exit | Trigger | Exit type |
|------|---------|-----------|
| SMA target | High ≥ SMA50-based target | `TARGET` |
| Timed exit | `RL_EXIT_DAYS` / `RL_EXIT_PERCENT` logic | `RL_EXIT_DAYS` |
| Partial exit | `PARTIAL_EXIT_*` | Reduces size; may reset target for remainder |
| Flush / cut losers | `RL_FLUSH_DAYS`, `RL_CUT_THE_LOSERS` | Various |

Stop vs target is evaluated **stop first**, then profit race (SMA target vs timed exit).

### 2.4 Rocket Launcher 100 (`RL100_*`)

Parallel subsystem on **100-SMA** entries. Same trailing pattern with separate defaults:

| Variable | Default |
|----------|---------|
| `RL100_TRAIL_PROFIT` | `0.14` |
| `RL100_TRAIL_STOP` | `0.0` |
| `RL100_TRAIL_PROFIT2` | `0.40` |
| `RL100_TRAIL_STOP2` | `0.20` |

Exit types: `TRAIL_STOP`, `TRAIL_STOP2`, `STOP_LOSS`, `TARGET`, `TIMED_EXIT`, `FLUSH_EXIT`, etc.

### 2.5 Dive Bomber (`DB_*`) — no trailing

Short strategy: fixed `DB_STOP_PCT` (stop **above** entry) and `DB_TARGET_PCT` (target **below** entry). **No trailing stop mechanism.**

### 2.6 RL ↔ BRT mirror

`run_audit.ps1` emits `BRT_Closed_RL_*` via `rl_emit_brt_mirror.py` for regression. That mirror uses RL fill logic, **not** BRT exit rules. Do not expect RL closed trades to match BRT closed trades on stops.

---

## 3. BRT / IND backtest (`rocket_brt.py`)

Single backtest engine. **IND** = same exits + indicator entry gates (`indicator_buy=only`, `min_ind_score`, `sell_ind_diff_below`, etc.).

### 3.1 Initial stop and target

Set at entry (next bar open). Resolution order for **initial** levels:

1. If `atr_target > 0` / `atr_stop > 0`: ATR-based (uses ATR% at entry).
2. Else percent mode:
   - Long target: `entry × target_pct` (or `SMA50 × target_pct` if `use_sma50=true`).
   - Long stop: `entry × stop_pct` (multiplier mode) or `entry × (1 - stop_pct)` (fraction mode).
   - Short: `short_target_pct` / `short_stop_pct` symmetric formulas.

**DailyRun step 3 (BRT whitelist)** — percent mode, no ATR exits:

- `stop_pct=0.903`, `target_pct=1.21` (via defaults / not all repeated on CLI)
- `trailing_stop_increment=0` (default)
- `atr_progress=0`, `atr_days=0`
- `atr_progress_incremental_stop=false`

**DailyRun step 4 (IND)** — ATR exit mode:

- `atr_target=2.4`, `atr_stop=1.1`
- `atr_progress=0.9`, `atr_days=6`
- `trailing_stop_increment=0`
- Optional: `sell_ind_diff_below`, `exit_ind_diff_only` (not in DailyRun.bat today)

### 3.2 Gain-based trailing (`trailing_stop_increment`)

| Config | Default | Meaning |
|--------|---------|---------|
| `trailing_stop_increment` | `0` | `0` = **disabled**. |

When **> 0** (long example):

1. Track **peak High since entry** (`max_high_since_entry`).
2. Each bar, compute  
   `gain_pct = (max_high - entry) / entry × 100`
3. `step_ratio = gain_pct / trailing_stop_increment` (fractional, **not** floored to int).
4. **Working stop** = `initial_stop + step_ratio × 0.01 × entry`  
   (each full “increment” unit of gain adds **1% of entry** above the initial stop).

**Exit label:** `TRAILING_STOP` when the working stop is above the initial stop and price hits it.

**Deprecated alias:** `-v atr_increment=…` maps to `trailing_stop_increment`.

**Contrast with RL:** BRT ratchets continuously with peak price; RL jumps to a fixed stop level after a profit gate.

### 3.3 ATR progress floor (`atr_progress_incremental_stop`)

Separate from gain-based trailing. Requires:

- `atr_progress_incremental_stop=true`
- `atr_days > 0`
- `atr_progress > 0`

**After calendar day `entry_date + atr_days`:**

- Floor = `entry × (1 + atr_progress × atr_pct_at_entry / 100)`
- Active only if floor > current working stop **and** prior bar **Close > floor**
- Working stop is raised to floor; exits use type `atr_incremental_stop`

**DailyRun:** BRT step 3 sets `atr_progress_incremental_stop=false`. IND step 4 does **not** set it (default **false**).

### 3.3b SMA trailing stop (`sma_stop_days`)

Separate from gain-based trailing and the ATR progress floor. Uses a simple moving average of **Close** over **N** sessions.

| Config | Default | Meaning |
|--------|---------|---------|
| `sma_stop_days` | `0` | `0` = **disabled**. Typical values: **20** (default when you enable) or **8**. |

**Long (default IND/BRT side):**

1. Each bar, compute SMA(N) on that bar’s close history.
2. If **Close > SMA(N)**, the SMA level is a candidate stop floor.
3. **Working stop** = **max**(initial stop, gain-based trailing stop, ATR progress floor if active, **SMA(N)**).
4. Stops **never decrease** — only ratchet up.

**Short:** If **Close < SMA(N)**, working stop = **min** of other stops and SMA(N) (tighten only).

**Exit label:** `SMA_STOP` when price hits the working stop and the SMA floor was active on that bar.

**Examples:**

```bash
# Backtest (rocket_brt.py)
-v sma_stop_days=20
-v sma_stop_days=8

# Live (getTarget.py)
--ind-sma-stop-days 20
--brt-sma-stop-days 20
```

Combine with `trailing_stop_increment` and `atr_progress_incremental_stop`; the engine always takes the **tightest** favorable stop (highest for longs).

### 3.4 ATR schedule exit (`atr_progress` + `atr_days`)

Calendar-day deadline (first session **strictly after** `entry_date + atr_days`):

| `atr_progress` | Behavior |
|----------------|----------|
| `≤ 0` | **Timed exit** at that open — exit type `ATR_timed` |
| `> 0` | **Inaction exit** (`ATR_inaction`) at that open **unless** max High from entry through prior bar reached `entry × (1 + atr_progress × atr_pct/100)` |

**IND DailyRun:** `atr_progress=0.9`, `atr_days=6` → must rally 90% of entry ATR% within 6 calendar days or exit at schedule open.

This is an **exit**, not a trailing stop — it closes the trade. The progress floor (§3.3) only **raises** stop when enabled.

### 3.5 IND-only exit: `IND_DIFF` / `exit_ind_diff_only`

| Config | Effect |
|--------|--------|
| `sell_ind_diff_below=N` | Exit next open if trade-aligned `IND_DIFF` on **prior** bar &lt; N |
| `exit_ind_diff_only=true` | **Only** this exit; disables stop, target, trailing, ATR schedule |

### 3.6 Per-bar exit priority (BRT/IND)

While a position is open, the engine checks (simplified):

1. `IND_DIFF_EXIT` (if signaled)
2. If `exit_ind_diff_only` — skip other exits except arming IND_DIFF
3. Gap down / gap up (open through stop or target)
4. Intraday stop / target (low/high vs working stop and target)
5. ATR schedule exit (`ATR_timed` / `ATR_inaction`)

Working stop each bar = max of (long):

- Initial stop
- Gain-based trailing stop (if `trailing_stop_increment > 0`)
- ATR progress floor (if active)
- SMA(N) floor (if `sma_stop_days > 0` and Close > SMA)

### 3.7 Exit type reference (BRT/IND)

| EXIT_TYPE | Source |
|-----------|--------|
| `STOP_LOSS` | Initial percent stop hit |
| `TARGET` | Percent target hit |
| `TRAILING_STOP` | Gain-based trailing stop hit |
| `SMA_STOP` | SMA(N) trailing floor hit |
| `atr_incremental_stop` | ATR progress floor hit |
| `ATR_STOP` / `ATR_TARGET` | When `atr_stop` / `atr_target` used for exits |
| `ATR_timed` / `ATR_inaction` | ATR schedule |
| `IND_DIFF_EXIT` | Indicator diff exit |
| `GAP_DOWN` / `GAP_UP` | Open gaps through stop/target |

---

## 4. Live portfolio tool (`gettarget.py`)

Computes **recommended** stop/target per open position. Each symbol has a **system** (`RL`, `BRT`, or `IND`) in the editable `POSITIONS` table in `getTarget.py`:

```python
"META": ("2026-05-11", 599.97, "RL"),   # date, entry price, system
```

CLI defaults are **per system** (DailyRun step 6):

```text
--brt-atr-target=8 --brt-atr-stop=3 --brt-atr-increment=12 ...
--ind-atr-target=2.4 --ind-atr-stop=1.1 --ind-atr-progress=0.9 --ind-atr-days=6 ...
--rl-target-pct=1.20 --rl-stop-pct=0.934 --rl-use-sma50
--rl-trail-profit=0.14 --rl-trail-stop=0 --rl-trail-profit2=0.40 --rl-trail-stop2=0.20
```

| System | Target | Stop / trailing |
|--------|--------|-----------------|
| **IND** (`--ind-mode auto`, default) | If all `--ind-atr-*` are **0**: `entry×--ind-target-pct` (default 1.21). Else ATR × `--ind-atr-target`. | `entry×--ind-stop-pct` or IND ATR stop |
| **BRT** (`--brt-mode auto`, default) | If all `--brt-atr-*` are **0**: `entry×--brt-target-pct` (default 1.21). Else ATR. | `entry×--brt-stop-pct` or BRT ATR stop |
| **BRT** (`--brt-mode percent`) | Same percent path | Same |
| **RL** | **SMA50(as_of)×rl-target-pct** when `--rl-use-sma50` | Signal-day low×`rl-stop-pct`; trail tiers when high crosses `rl-trail-profit` / `rl-trail-profit2` |

| Output column | Meaning |
|---------------|---------|
| `StopInitial` | `entry × (1 - atr_pct × atr_stop / 100)` |
| `StopTrailing` | `StopInitial + int(gain_pct / atr_increment) × 0.01 × entry` using max High entry→as-of |
| `ATRScheduleProgressPrice` | `entry × (1 + atr_progress × atr_pct / 100)` |
| `ATRProgressStopApplied` | Whether trailing stop was floored up to progress price after deadline |
| `SMAStopApplied` / `SMAStopLevel` | Whether SMA(N) floor raised `StopTrailing`; SMA level used |

**Stop never decreases:** By default, reads previous `getTarget_output.csv` and keeps the higher `StopTrailing` per symbol (warns if computed value would drop).

**Manual entry:** `ACTUAL_ENTRY_PRICE` dict overrides CSV entry price.

**Note:** `gettarget.py` uses **bar index** `entry_i + atr_days` for schedule preview in one code path, while `rocket_brt.py` schedule uses **calendar days**. Treat schedule dates in gettarget as approximate vs backtest when comparing.

---

## 5. Side-by-side comparison

### 5.1 What “trailing” means

| | Rocket Launcher | BRT / IND (`trailing_stop_increment`) |
|---|-----------------|--------------------------------------|
| **Enables when** | High crosses profit % threshold | Any peak gain &gt; 0 (if increment &gt; 0) |
| **Stop formula** | `entry × (1 + RL_TRAIL_STOP)` fixed | `initial_stop + (gain%/N) × 1% × entry` |
| **Updates** | Step change (Trail 1 → Trail 2) | Every bar with new peak high |
| **Default in DailyRun** | Usually off (`RL_TRAIL_PROFIT=0`) | **Off** (`trailing_stop_increment=0`) |

### 5.2 Typical stop/target anchors

| | Rocket Launcher | BRT (step 3) | IND (step 4) |
|---|-----------------|--------------|--------------|
| **Stop** | Signal-day low × 0.934 | Entry × 0.903 | ATR-based (~1.1 × ATR%) |
| **Target** | SMA50 × 1.20 | Entry × 1.21 | ATR-based (~2.4 × ATR%) |
| **Extra** | Trail tiers, timed exit | Zone/pivot entries | IND_DIFF optional, ATR inaction @ 6d |

### 5.3 What DailyRun actually runs today

| Step | Trailing | Stop / target model |
|------|----------|---------------------|
| 2 RL audit | AWK trail params unless passed in `run_audit.ps1` | RL percent + SMA target |
| 3 BRT | **Off** | Percent stop/target |
| 4 IND | **Off** | ATR stop/target + 6-day ATR progress rule |
| 6 gettarget | **On** (`atr_increment=12`) | ATR + progress floor for live book |

---

## 6. Configuration cheat sheet

### Rocket Launcher (`run_audit.ps1` → AWK `-v`)

```powershell
-RLTrailProfit 0.14 -RLTrailStop 0.0 -RLTrailProfit2 0.40 -RLTrailStop2 0.20
```

### BRT backtest

```bash
# Gain-based trailing (unusual for whitelist BRT)
-v trailing_stop_increment=12

# ATR progress stop floor (after N calendar days)
-v atr_progress_incremental_stop=true -v atr_progress=0.9 -v atr_days=6

# SMA trailing stop (20-day default when enabled; try 8)
-v sma_stop_days=20

# Disable all percent trailing/schedule
-v trailing_stop_increment=0 -v atr_days=0
```

### IND backtest

Same flags as BRT, plus:

```bash
-v sell_ind_diff_below=5 -v exit_ind_diff_only=true   # only IND_DIFF exits
```

### Live (gettarget)

```bash
python gettarget.py --atr-stop=3 --atr-target=8 --atr-increment=12 --atr-progress=1.1 --atr-days=14
```

---

## 7. Related files

| File | Role |
|------|------|
| `stock_analysis/portfolio_audit.awk` | Rocket Launcher, RL100, Dive Bomber exits |
| `run_audit.ps1` | Runs audit; passes `RL_TRAIL_*` overrides |
| `stock_analysis/rocket_brt.py` | BRT + IND backtest exits |
| `DailyRun.bat` | Steps 2–4 and 6 orchestration |
| `gettarget.py` | Live stop/target/trailing for open positions |
| `Copy-LatestRunOutputs.ps1` | Copies latest `RL_*`, `BRT_*`, `IND_*` CSVs |

---

## 8. Open questions / known mismatches

1. **RL vs BRT** are different strategies; stop logic is not intended to match.
2. **gettarget** schedule preview may use bar-count `atr_days` in one place vs **calendar days** in `rocket_brt.py` — verify before relying on `ATRScheduleExitDate` for IND backtests.
3. **Gain trailing** uses fractional `gain_pct / increment` in BRT; **gettarget** uses `int(gain_pct / atr_increment)` — tiny differences possible at boundaries.
4. Enabling `RL_TRAIL_PROFIT` in audit changes closed history; default `0` means most RL runs have **no** trailing unless you opt in.

---

*Last aligned to codebase: `DailyRun.bat`, `rocket_brt.py`, `portfolio_audit.awk`, `gettarget.py`.*
