# Entry Logic: Rocket Launcher vs Dive Bomber

Side-by-side comparison of all conditions required to **open a position**.

---

## Rocket Launcher — 50-day (long)

**When:** `SMA_QUAL == 1`, `j > SMA_PERIOD_50 + RL_50_SMA_LOOKBACK`, and **not** already in an RL position.

### 1. Dip-zone (price vs 50 SMA)

| Condition | Meaning |
|-----------|--------|
| **sma50rising** | SMA50 today > SMA50 from `RL_50_SMA_LOOKBACK` (4) days ago |
| **inthe50zone** | Low is in “dip band”: `y_sma * (1-(RL_DIP_PCT-1)) < raw_lo < y_sma * RL_DIP_PCT` (y_sma = yesterday’s SMA50) |
| **uptick** | Close > open (green day) |
| **closeabove50sma** | Close > yesterday’s SMA50 |
| **is200sma** | SMA200 exists (yesterday) |
| **sma20over50** | SMA20 > SMA50 |
| **sma50over100** | SMA50 > SMA100 |
| **sma100over200** | SMA100 > SMA200 |

→ Bullish stack: 20 > 50 > 100 > 200.

### 2. Expansion (prior strength)

| Condition | Meaning |
|-----------|--------|
| **expansion** | In last `EXPANSION_LOOKBACK_DAYS`, at least one day had close ≥ SMA50(prev) × `RL_EXPANSION` |

### 3. Acceptance (recent closes above 50)

| Condition | Meaning |
|-----------|--------|
| **acceptance** | Rolling count of “close > prior day’s SMA50” over `RL_ACC_COUNT` days ≥ `RL_ACC_MIN` |

### 4. Cut the losers

| Condition | Meaning |
|-----------|--------|
| **cut_it** | Current high % vs yesterday’s SMA50 < `RL_CUT_THE_LOSERS` (e.g. 0.20) |

### 5. ATR / volatility

| Condition | Meaning |
|-----------|--------|
| **atr_inclusion** | ATR% in band (`RL_ATR_LOW_PERCENT` to `RL_ATR_HIGH_PERCENT`), ATR < `RL_ATR_HIGH_VALUE`, price ≥ `RL_LOW_PRICE` |

### 6. Peak (historical expansion cap)

| Condition | Meaning |
|-----------|--------|
| **peak_inclusion** | `peak_cl[sym] < PEAK_THRESHOLD_MAX` |

### 7. Slope

| Condition | Meaning |
|-----------|--------|
| **slope_ok** | If `RL_SLOPE_THRESHOLD != 0`: `current_slope >= RL_SLOPE_THRESHOLD` (SMA50 growth over `RL_SLOPE_PERIOD`); else always OK |

### 8. Shock

| Condition | Meaning |
|-----------|--------|
| **shock_qualified** | If `RL_SHOCK_THRESHOLD == 0`: OK; else count of shocks within `RL_SHOCK_REHAB_DAYS` ≤ `RL_SHOCK_MAX_ALLOWED` |

### 9. Too low (next-day gap)

| Condition | Meaning |
|-----------|--------|
| **!too_low** | Next day’s open is **not** below today’s low × `RL_STOP_PCT` (avoid gap-down) |

### 10. SPY (optional)

| Condition | Meaning |
|-----------|--------|
| **spy_ok** | If `SPY_INCLUSION == 0`: OK; else SPY stack 50 > 100 > 200 on **entry day** |

### 11. Entry-day price cap

| Condition | Meaning |
|-----------|--------|
| **isnottoohigh** | Next day’s open ≤ today’s low × `RL_TOO_HIGH` × `RL_STOP_PCT` |
| **next_day exists, open > 0** | Valid next bar and open price |

**Entry:** Next day’s **open**. Stop = today’s low × `RL_STOP_PCT`, target from SMA50.

---

## Rocket Launcher — 100-day (long)

**When:** `RL_100_TOGGLE == 1`, `j > SMA_PERIOD_100 + 3`, and **not** in an RL 100-day position.

### Conditions (all required)

| Condition | Meaning |
|-----------|--------|
| **sma100_rising** | SMA100 today > SMA100 from 3 days ago |
| **price_action** | Close > open and close > yesterday’s SMA100 |
| **stack_ok** | 20 > 50 > 100 > 200 |
| **exp100** | In lookback, some day had close ≥ SMA100(prev) × `RL_100_EXPANSION` |
| **acc100** | 100-day acceptance: rolling “close > prior SMA100” count ≥ `RL_100_ACC_MIN` over `RL_100_ACC_COUNT` |
| **in_zone100** | Low in 100 dip band: `sma100[y]*(1-(RL_100_DIP_PCT-1)) < raw_lo < sma100[y]*RL_100_DIP_PCT` |
| **next day exists, open > 0** | Valid next bar |
| **RL_TOO_HIGH** | If used: next open ≤ today’s low × `RL_TOO_HIGH` |

**Entry:** Next day’s **open**. Stop = today’s low × `RL_100_STOP_PCT`, target = SMA100 × `RL_100_TARGET_PCT`.

---

## Dive Bomber (short)

**When:** `DB_TOGGLE == 1`, `db_inv == 0`, `j > SMA_PERIOD_200 + DB_RIP_DAYS_MAX`, and SMA50/100/200 all > 0.

### Conditions (all required)

| Condition | Meaning |
|-----------|--------|
| **inverse_stack** | Bearish stack: SMA50 < SMA100 < SMA200 (or, if `DB_INVERSE_STRICT == 0`, only 50 < 100) |
| **falling_50** | SMA50 today < SMA50 from `DB_SLOPE_LOOKBACK` (4) days ago |
| **rip_ok** | Close today > close from `DB_RIP_DAYS_MAX` (5) days ago (rally over that window) |
| **touch_50** | Today’s high ≥ SMA50 × (1 − `DB_RIP_TOUCH_TOL`) (price came within 2.4% of 50 SMA) |
| **db_expansion** | Inverse of RL: at least one day in `EXPANSION_LOOKBACK_DAYS` had close ≤ sma50(prev) × `DB_EXPANSION` (prior weakness) |
| **db_acceptance** | Inverse of RL: rolling count of “close < prior 50” over `DB_ACC_COUNT` days ≥ `DB_ACC_MIN` |
| **next_day_iso_db exists, open > 0** | Valid next bar and open |
| **gap_ok** | If `DB_GAP_UP_MAX > 0`: next open ≤ SMA50(signal day) × `DB_GAP_UP_MAX` |
| **entry_near_50** | Next day’s open is within ±`DB_RIP_TOUCH_TOL` of **signal-day** SMA50: `sma50*(1−tol) ≤ open ≤ sma50*(1+tol)` |

**Entry:** Next day’s **open**. Stop = entry × `DB_STOP_PCT`, target = entry × `DB_TARGET_PCT`.

---

## Comparison summary

| Concept | Rocket Launcher (50) | Rocket Launcher (100) | Dive Bomber |
|--------|------------------------|------------------------|-------------|
| **Trend** | 50 rising, stack 20>50>100>200 | 100 rising, stack 20>50>100>200 | 50 falling, stack 50<100<200 |
| **Price vs MA** | Low in “dip zone” vs 50 SMA | Low in “dip zone” vs 100 SMA | High “touch” 50 SMA; entry open within ±2.4% of 50 |
| **Prior strength** | Expansion (close ≥ SMA50×RL_EXPANSION in lookback) | Expansion vs 100 SMA | Rip + **db_expansion** (close ≤ SMA50×DB_EXPANSION in lookback) |
| **Acceptance** | Rolling closes above 50 ≥ RL_ACC_MIN | Rolling closes above 100 ≥ RL_100_ACC_MIN | **db_acceptance**: rolling closes below 50 ≥ DB_ACC_MIN |
| **Candlestick** | Uptick (close > open), close above 50 | Close > open, close > 100 | — |
| **ATR / price** | ATR band, max ATR value, min price | — | — |
| **Peak / slope** | Peak cap, slope threshold | — | — |
| **Shock** | Shock count within rehab days | — | — |
| **Next-day guard** | !too_low, isnottoohigh (vs RL_TOO_HIGH) | RL_TOO_HIGH check | gap_ok (DB_GAP_UP_MAX), entry_near_50 (±2.4%) |
| **SPY** | Optional: SPY 50>100>200 on entry day | — | — |

**Peak (RL only):** RL uses **peak_inclusion** = (`peak_cl[sym] < PEAK_THRESHOLD_MAX`). `peak_cl[sym]` is the **maximum historical “close % above yesterday’s SMA50”** for the symbol (updated each bar: if today’s close is X% above yesterday’s 50, that’s tracked; the max over time is `peak_cl`). So RL refuses to go long if the stock has already had a close more than 200% (or `PEAK_THRESHOLD_MAX`) above the 50 SMA—it avoids chasing extended names. **Dive Bomber has no equivalent:** there is no “peak trough” or cap on how far price has already dropped below the 50 SMA. Adding an inverse peak for DB (e.g. only short if the stock hasn’t already collapsed beyond some threshold) would be a separate, optional filter.

**Dive Bomber** now has inverse **expansion** and **acceptance**; it still has no ATR, peak, slope, shock, or SPY filters.
