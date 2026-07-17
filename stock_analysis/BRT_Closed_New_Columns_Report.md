# BRT_Closed — New Columns Report

This document describes the **new columns** added to the BRT_Closed output for analysis and filtering. Use it to share with your partner or for your own reference.

---

## 1. Growth (single-period gain at entry)

One column: the **percent gain** from the price `growth_bars` days ago to the price at entry (e.g. 33.10 = 33.1% over 3 years when growth_bars=756). | Column                   | Type   | Description |
|--------------------------|--------|-------------|
| **GROWTH_PCT_OVER_PERIOD** | % or empty | (price_at_entry - price_n_days_ago) / price_n_days_ago × 100. Empty when no price growth_bars days ago (e.g. stock &lt; 3 years old). |

**Growth filter (when enabled):** Buy only if price at entry &gt; price growth_bars days ago; if stock has no data that far back, we don't buy.

---

## 2. Pivot sequence in zone (strong setup)

These describe the **sequence of pivot highs (H) and pivot lows (L)** inside the trigger zone *before* the entry bar. A “strong” setup is when the zone saw 2–3 highs then 1–2 lows (switch from resistance to support) before the buy.

| Column                      | Type | Description |
|----------------------------|------|-------------|
| **PIVOT_RUN_H_BEFORE_ENTRY** | int | Number of consecutive pivot **highs** in the zone immediately before the trailing lows. |
| **PIVOT_RUN_L_BEFORE_ENTRY** | int | Number of trailing pivot **lows** in the zone at the end of the sequence (1 or 2). |
| **PIVOT_SWITCH_H_TO_L**      | 0/1 | 1 = pattern “≥2 highs then 1–2 lows” at the end of the in-zone pivot sequence (strong setup). |

**Use:** Filter for “strong” setups with `PIVOT_SWITCH_H_TO_L = 1`, or slice by run lengths (e.g. 2H then 1L).

---

## 3. Bands above and below (for targets/stops)

- **Zone above** = next key-level zone **above the entry price** (so `ZONE_ABOVE_CENTER` is always &gt; `ENTRY_PRICE` when present). Used as a first target.
- **Zone below** = next key-level zone **below the trigger band** (the zone that generated the entry). Used as a stop/invalidation reference.

| Column                           | Type   | Description |
|----------------------------------|--------|-------------|
| **ZONE_ABOVE_CENTER**            | float  | Center of the next key-level zone **above entry price** (empty if none in lookback). Always greater than ENTRY_PRICE when present. |
| **ZONE_BELOW_CENTER**            | float  | Center of the next key-level zone **below** the trigger band (empty if none in lookback). Only levels clearly below the trigger band are counted. |
| **PCT_ENTRY_TO_BOTTOM_ZONE_ABOVE** | %     | Percent move from entry to the **bottom** of the zone above: `(bottom_above - entry) / entry × 100`. Useful as a first target. Empty if no zone above. |
| **PCT_DROP_TO_TOP_ZONE_BELOW**   | %     | Percent **drop** from entry to the **top** of the zone below: `(entry - top_below) / entry × 100`. Useful as a stop or invalidation level. Empty if no zone below. |

**Use:** Compare realized exits to these levels; filter by “target reach” or “stop distance”; or use the percentages as reference targets/stops in live trading.

---

## Quick reference — new columns only

- **Growth:** GROWTH_PCT_OVER_PERIOD (% gain over growth_bars at entry)  
- **Pivot pattern:** PIVOT_RUN_H_BEFORE_ENTRY, PIVOT_RUN_L_BEFORE_ENTRY, PIVOT_SWITCH_H_TO_L  
- **Trigger-relative bands:** ZONE_ABOVE_CENTER, ZONE_BELOW_CENTER, PCT_ENTRY_TO_BOTTOM_ZONE_ABOVE, PCT_DROP_TO_TOP_ZONE_BELOW  

All of these are computed at **entry** and written once per trade in BRT_Closed.
