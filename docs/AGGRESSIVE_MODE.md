# Aggressive mode (`--aggressive`) — reference

This document explains how **aggressive** equity simulation works in `rocket_brt.py` and `BRT_DrawdownCalc.py`. It is separate from trade entry/exit logic (stops, targets, indicators). Aggressive mode only changes how **portfolio equity, drawdown, and margin** are modeled after trades are generated.

For stop/target behavior see [TRAILING_STOPS.md](./TRAILING_STOPS.md).

---

## 1. Executive summary

| Topic | Behavior |
|--------|----------|
| **What it does** | Builds a **daily share-level portfolio simulator** on top of closed + open trades. Each new entry is sized as **`current_equity × aggressive_max_multiple / avg_positions`** (default 2× equity spread across avg slots). |
| **What it does not do** | Does not change which trades open/close, fill prices, or per-trade `PNL_DOLLARS` in `*_Closed_*.csv` (those still use `brt_cash`). |
| **Why use it** | Produces **Max_DD**, underwater stats, and equity curves that reflect **compounding equity**, **overlapping positions**, and **margin interest** when gross exposure exceeds net equity. |
| **DailyRun** | Both BRT step 3 and IND step 4 pass `--aggressive` (defaults below). |
| **Primary outputs** | `{BRT\|IND}_EquityCurve_<ts>.csv` (aggressive series used for Max_DD), `{prefix}_EquityCurve_Aggressive_<ts>.csv`, optional `{prefix}_aggressive_trim_log_<ts>.csv`. |

**CLI help line (shorthand):** “equity×2/avg_positions per entry; margin interest on borrowed notional” — expanded in §4.

---

## 2. Two different “capital” numbers

Confusing these two is the most common source of misread audits.

| Field | Default | Used for |
|--------|---------|----------|
| **`brt_cash`** | `47500` in config; **report scaling** sets `brt_cash = 1_000_000 / Max_Positions` on the audit row | **Per-trade PnL** in the backtest: `pnl_dollars = (brt_cash / entry_price) × price_move`. Each slot is one “unit” of capital. |
| **`initial_capital`** | `500000` (`--initial-capital`) | **Portfolio equity curve** and **Max_Drawdown**: starting account equity for aggressive (and passive) simulation. |

They are **independent by design**:

- You can have `brt_cash ≈ 47.5k` per slot (from 1M / ~21 positions) while `initial_capital = 500k` for the DD path.
- **`Total_PNL`** on the audit row is scaled from summed trade dollars (`brt_cash` basis).
- **`Aggressive_Total_PNL`** is `final_equity − initial_capital` from the aggressive simulator (includes margin interest; compounding sizing).

Do not expect `Total_PNL` to equal `Aggressive_Total_PNL` unless you align sizing assumptions on purpose.

---

## 3. Passive vs aggressive equity curves

### 3.1 Without `--aggressive` (passive / “regular”)

`BRT_DrawdownCalc.compute_equity_metrics` walks each business day:

1. For each open trade, mark to market with OHLC **Close** (shares = `brt_cash / entry_price`).
2. Sum unrealized PnL + realized PnL on close dates.
3. `equity = initial_capital + cumulative_realized + floating`.

- No margin, no trims, no position-count cap.
- Position count = number of distinct symbols with an open trade that day.

### 3.2 With `--aggressive`

After the passive path is built (unless fast mode — §7), the engine **replaces** the equity series with `_simulate_aggressive_share_level`:

1. **Dynamic notional per new entry:**  
   `notional = equity_at_signal × aggressive_max_multiple / avg_positions`  
   `shares = notional / entry_price` on each entry open.

   **`equity_at_signal`** = cash + MTM of all open holdings at the **signal date** (prior business day to entry open). Matches backtest convention: size the next entry from yesterday’s closes while still long prior names.

2. **Daily mark-to-market** on holdings (Close from ticker CSVs).

3. **No proportional trim** — overlapping positions may exceed cash; **cash goes negative** (borrowed = `max(0, −cash)`).

4. **Margin interest:**  
   `borrowed = max(0, −cash)` (equivalent to gross − equity when fully invested on margin)  
   Daily charge: `borrowed × (aggressive_margin_interest / 365)`.

5. **End-of-day exits** at close/exit price for trades closing that day.

**Max_Drawdown** and underwater metrics are computed from this **aggressive** equity series, not from passive OHLC sum (when aggressive succeeds).

### 3.3 Comparison series (`Equity_Regular`)

When aggressive runs the **full** path (not `--equity-fast-aggressive`), the passive snapshot is saved as:

- `equity_values_regular` in memory
- `{BRT|IND}_EquityCurve_Regular_<ts>.csv` on disk (if written)

`BRT_DrawdownCalc` can chart **both** lines: aggressive (primary) vs regular OHLC.

---

## 4. Aggressive algorithm (detail)

Implementation: `BRT_DrawdownCalc._simulate_aggressive_share_level`.

### 4.1 Average positions (`avg_pos`)

Used for sizing:

```text
notional_per_entry = equity_at_signal × aggressive_max_multiple / avg_pos
```

| Source | When |
|--------|------|
| `--aggressive-avg-positions N` | If `N > 0`, use `N`. |
| Auto | Mean of **daily distinct symbol counts** on days with at least one open position (from trade open/close dates). |

Reported on audit as **`Aggressive_Avg_Positions`**.

**Example** (`initial_capital = 500_000`, `avg_pos = 2.6266`, `multiple = 2`):

| Step | Calculation |
|------|-------------|
| First entry (SII 2016-03-03) | `500_000 × 2 / 2.6266 ≈ $380_720` |
| After +9.4% close | equity ≈ `$535_788` |
| Next entry (STX 2016-03-18) | `535_788 × 2 / 2.6266 ≈ $407_971` |
| Still long STX; AX signal 2016-03-18, entry 2016-03-21 | Mark STX at **2016-03-18 close**; equity ≈ `$552_028`; AX slot ≈ `$421_074` |
| Overlap | Gross ≈ `$820k+` on ~`$552k` equity → ~`$268k` borrowed at 10% annual |

### 4.2 Leverage multiple (`aggressive_max_multiple`)

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `aggressive_max_multiple` | `2.0` | Target **total gross** when fully deployed at avg count ≈ `2 × equity`. Each slot gets `equity × multiple / avg_pos`. |

There is **no** hard trim to `initial_capital × multiple`. Overlap can push gross higher; margin is handled via negative cash.

### 4.3 Margin interest

After EOD MTM and closes:

```text
borrowed = max(0, −cash)
daily_interest = borrowed × (aggressive_margin_interest / 365)
cash -= daily_interest
```

Default **`aggressive_margin_interest = 0.10`** → 10% annualized on borrowed notional.

### 4.4 End-of-day equity

```text
equity = cash + sum(shares × mark_price)
```

Written to `{prefix}_EquityCurve_<ts>.csv` (column `Equity`) and `{prefix}_EquityCurve_Aggressive_<ts>.csv`. Optional columns: `Positions`, `Equity_Pct_of_Initial` (= `(equity/initial_capital − 1) × 100`).

### 4.5 Legacy trim log

`{prefix}_aggressive_trim_log_<ts>.csv` is **no longer populated** (trim logic removed). File may be absent or empty on new runs.

---

## 5. CLI and config

### 5.1 Flags (`rocket_brt.py`)

| Flag | Default | Purpose |
|------|---------|---------|
| `--aggressive` | off | Enable aggressive equity overlay. |
| `--initial-capital` | `500000` | Account size for equity / DD (`initial_capital` in config). |
| `--aggressive-margin-interest` | `0.10` | Annual rate on borrowed notional (`max(0, −cash)`). |
| `--aggressive-max-multiple` | `2.0` | Sizing leverage: each entry = `equity × multiple / avg_pos`. |
| `--aggressive-avg-positions` | `0` (= auto) | Override average position count for sizing. |
| `--equity-fast-aggressive` | off | Skip passive OHLC pass; aggressive only (faster; no `Equity_Regular` file). |
| `--no-equity-metrics` | off | Skip entire equity / Max_DD block (saves time on huge runs). |

### 5.2 Config fields (`BRTConfig` / `-v`)

Same names in audit CSV columns:

```text
-v aggressive=true
-v initial_capital=500000
-v aggressive_margin_interest=0.10
-v aggressive_max_multiple=2.0
-v aggressive_avg_positions=0
-v equity_fast_aggressive=true
```

### 5.3 DailyRun.bat (current)

Both backtest steps use `--aggressive` with defaults above. They do **not** pass `--equity-fast-aggressive` (so passive comparison is still computed when equity metrics run).

---

## 6. Output files

| File | Contents |
|------|----------|
| `{BRT\|IND}_EquityCurve_<ts>.csv` | **Primary** curve used for Max_DD (aggressive values when `--aggressive`). Columns: `Date`, `Equity`, optional `Positions`, `Equity_Regular` if dual path. |
| `{BRT\|IND}_EquityMeta_<ts>.csv` | One row: `Initial_Account_Size`, `Max_Drawdown_*`, `Aggressive=true/false`. |
| `{BRT\|IND}_EquityCurve_Aggressive_<ts>.csv` | Same aggressive series, dedicated copy for charts / Drive. |
| `{BRT\|IND}_EquityCurve_Regular_<ts>.csv` | Passive OHLC curve (only if not fast aggressive). |
| `{BRT\|IND}_aggressive_trim_log_<ts>.csv` | Days when proportional trim fired (may be empty). |
| `{BRT\|IND}_underwater_<ts>.csv` | Underwater episodes from equity series (via drawdown helper). |

`Copy-LatestRunOutputs.ps1` copies `*_EquityCurve_Aggressive_<ts>.csv` → `*_LatestRun_EquityCurve_Aggressive.csv`.

---

## 7. Audit report columns

On `BRT_Audit_Report_*` / `IND_Audit_Report_*` (summary row, `Param_Name` empty):

| Column | Meaning |
|--------|---------|
| `aggressive` | `True` if `--aggressive` was on. |
| `initial_capital` | Equity starting point (default 500k). |
| `aggressive_margin_interest` | Annual margin rate. |
| `aggressive_max_multiple` | Gross cap multiple. |
| `aggressive_avg_positions` | Override (0 = auto). |
| `Max_DD` | Peak-to-trough on **aggressive** equity (when aggressive). |
| `Aggressive_Total_PNL` | Final aggressive equity − `initial_capital`. |
| `Aggressive_Avg_Positions` | `avg_pos` used in sim. |
| `Aggressive_Days_AtOrBelow_Avg` | Days at ≤ avg position count. |
| `Aggressive_Days_In_Margin` | Days with `borrowed > 0` (negative cash / on margin). |
| `Aggressive_Days_Trimmed_Over_2xAvg` | Legacy counter; always 0 (trim removed). |

**Note:** `Aggressive_Total_PNL` can differ materially from `Total_PNL` (trade-sum on `brt_cash` basis). Compare them only when you understand §2.

---

## 8. Performance options

| Mode | Speed | What you get |
|------|-------|----------------|
| Default aggressive | Slower | Passive OHLC + aggressive replay; `Equity_Regular` + aggressive. |
| `--equity-fast-aggressive` | Much faster on large universes | Aggressive-only calendar; no passive pass; no `Equity_Regular`. |
| `--no-equity-metrics` | Fastest | No equity curves, no Max_DD from simulator (metrics from trades only). |

IND full-universe runs with hundreds of symbols often use aggressive; consider fast aggressive for sweeps.

---

## 9. Using with `BRT_DrawdownCalc`

```text
python stock_analysis/BRT_DrawdownCalc.py drive/IND_Closed_<ts>.csv ...
```

- Reads saved `EquityCurve` / `EquityMeta` when present.
- If `Aggressive=true` in meta, charts label the primary series as aggressive.
- Can recompute passive overlay for comparison when ticker data is supplied.

If Max_DD on a chart disagrees slightly with an old audit, check whether the run used **aggressive** vs passive and whether **`initial_capital`** matches.

---

## 10. Mental model (example)

Defaults: `initial_capital = 500_000`, `avg_pos = 1.15`, `max_multiple = 2`.

- Each **new** trade gets about `500_000 / 1.15 ≈ 434_000` notional (shares × entry).
- If you briefly hold **2** symbols and gross &gt; **$1M**, or count &gt; `floor(1.15×2)=2`, the sim **scales down** all positions and logs a trim.
- On days when gross &gt; **$500k**, you pay **10% annual** interest on `(gross − 500k)` for that day.

This models a book that **targets full deployment per slot** but **cannot exceed 2× account gross** without selling down.

---

## 11. FAQ

**Does aggressive change my Closed trade PnL?**  
No. Closed rows still use `brt_cash` sizing from the backtest.

**Why is `Equity_Pct_of_Initial` negative early in `EquityCurve_Aggressive`?**  
Column is `(equity / initial_capital − 1) × 100`, not “return on deployed slot”. Early drawdowns and cash drag from many entries can show negative % until the book compounds.

**Is aggressive the same as RL trailing stops?**  
No. RL trails are in `portfolio_audit.awk`. Aggressive is portfolio leverage/trim simulation in `BRT_DrawdownCalc`.

**Should live `gettarget.py` use aggressive?**  
No. `gettarget.py` is per-position stop/target only; it does not run this equity simulator.

**Where is the code?**  
- Simulator: `stock_analysis/BRT_DrawdownCalc.py` (`_simulate_aggressive_share_level`, `compute_equity_metrics`)  
- Wiring: `stock_analysis/rocket_brt.py` (`--aggressive`, `_write_aggressive_equity_curve`)  
- Glossary strings: `rocket_brt.py` `_AUDIT_CFG_GLOSSARY` / metrics helpers  

---

## 12. Related docs

- [TRAILING_STOPS.md](./TRAILING_STOPS.md) — exits and live `gettarget.py`  
- `DailyRun.bat` — steps 3 (BRT) and 4 (IND) enable `--aggressive`  
- `Copy-LatestRunOutputs.ps1` — copies latest aggressive equity CSVs  

*Last aligned to codebase: May 2026.*
