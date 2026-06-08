# IND early-signal / pre-entry run-up analysis

**Status:** Reference only — no product gates implemented. Revisit when you want to filter entries that chase extended moves.

**Source run:** `260528112419` (534 closed IND trades, `min_atr_pct_at_entry=8.1`, ATR exits).

---

## Question

Can indicator signals fire **before** large pre-entry run-ups, and which fields predict **post-entry** gain hits vs **already extended** names?

---

## Pre-entry run-up (20 trading days before entry)

| Metric | Value |
|--------|-------|
| Median 20-day pre-entry gain | ~**22.7%** |
| Trades already up **>10%** before entry | ~**71%** |
| Trades already up **>15%** before entry | majority of book |

**Takeaway:** Most IND entries are **not** “first day off the lows”; they often follow a substantial advance into the signal.

---

## Correlations (closed trades, run `260528112419`)

| Field | vs pre-20d gain | vs `POST_ENTRY_GAIN_HIT` |
|-------|-----------------|---------------------------|
| `IND_SCORE` | moderate positive | **~+0.31** (best forward signal) |
| `IND_DIFF` | **~+0.20** (chasing) | weaker |
| Pre-20d gain | — | negative for “fresh” entries |

Higher `IND_SCORE` associates with better **forward** outcomes; higher `IND_DIFF` and large pre-run associate with **chasing** extended names.

---

## Hypothetical gate: cap pre-entry gain

| Rule | Trades kept | Gain-hit rate |
|------|-------------|---------------|
| No cap | 100% | ~**37%** |
| Exclude pre-20d gain **>15%** | ~**37%** of trades | ~**49%** gain-hit rate |

A `max_pre_entry_gain_20d` (or similar) gate would cut trade count sharply but improve hit rate on what remains. **Not enabled** in code — document for future `-v` experiments.

---

## Related config (today)

| Item | Notes |
|------|--------|
| `min_ind_score` | Large trade-count impact when default **32.56** active; CLI `0` is falsy-bugged to 32.56 — use **-1** to disable |
| `min_atr_pct_at_entry` | 8.1 in DailyRun; watchlist `SCANNER` now also requires ATR gate |
| `use_sma50` | Only affects targets when `atr_target=0`; irrelevant when `atr_target=2.4` |

---

## Suggested follow-ups (when revisiting)

1. Backtest `-v max_pre_entry_gain_20d=15` (or 20) on a fixed run set.
2. Stratify reports by `IND_SCORE` decile vs `POST_ENTRY_GAIN_HIT`.
3. Fix `min_ind_score` falsy-`0` → `32.56` in `rocket_brt.py` if you need “gate off” from batch files.

---

## Files

- Backtest engine: `stock_analysis/rocket_brt.py`
- Stops/targets doc: `docs/TRAILING_STOPS.md`
- Watchlist semantics: tightened `SCANNER` rows require ATR + green bar + latest `AS_OF_DATE` (see conversation / `ind_watchlist_*` config)
