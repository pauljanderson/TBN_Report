# Portfolio Audit Performance Recommendations

## How to Use Instrumentation

Run the audit with `INSTRUMENT=1` to generate timing data:

```powershell
awk -f portfolio_audit.awk -v INSTRUMENT=1 -v DATA_DIR="path\to\data" ... (other -v args) SPY.csv ticker1.csv ticker2.csv ...
```

Or add `-v INSTRUMENT=1` to your existing `run_audit.ps1` / optimizer invocation.

Output is written to `instrument.txt` in the current directory (or `OUTPUT_DIR` if overridden). It includes:

- **Scout [SYM]**: Time to read each ticker CSV and build `raw_*`, `dates`, etc.
- **Audit [SYM]**: Time for `perform_audit()` per symbol
- **Pass1/Pass2** (when RL_FLUSH_DAYS > 0): Two-pass flush timing
- **SPY load**, **Metrics/sort**, **File output**: END block phase breakdown
- **TOTAL RUNTIME**: End-to-end duration

---

## Likely Hotspots (Based on Code Analysis)

### 1. **perform_audit inner loop (highest impact)**

The main loop iterates `j = 1` to `d_ptr[sym]` (~5000+ bars per symbol × ~1000 symbols = millions of iterations).

**Within the loop:**

| Area | Calls per bar | Notes |
|------|---------------|-------|
| `days_diff()` | 6–12+ | Uses `mktime()` twice per call; expensive |
| Shock loop | O(shock_count) | Iterates all shocks per bar |
| Expansion lookback | 10 | `EXPANSION_LOOKBACK_DAYS` |
| Squeeze high calc | DB_SQUEEZE_EXIT | Loop over N days when enabled |

### 2. **days_diff()**

```awk
function days_diff(d1, d2, t1, t2) {
    t1 = mktime(substr(d1,1,4) " " substr(d1,5,2) " " substr(d1,7,2) " 00 00 00")
    t2 = mktime(substr(d2,1,4) " " substr(d2,5,2) " " substr(d2,7,2) " 00 00 00")
    return int((t2 - t1) / SECONDS_PER_DAY)
}
```

`mktime()` is costly. Called for milestones (6×), hold_days, and in shock loop.

**Recommendation:** Cache `days_diff(rl_entry_iso[sym], iso)` for the current bar; only recompute when `iso` or `rl_entry_iso[sym]` changes. Or precompute a `date_to_epoch[iso]` map in BEGIN/on load and compute `(epoch2 - epoch1) / 86400` without `mktime()`.

### 3. **Shock detector loop**

```awk
for (s_idx = 1; s_idx <= shock_count; s_idx++) {
    diff = days_diff(shock_event_dates[s_idx], iso)
    ...
}
```

Runs every bar. With many shocks, this is O(bars × shocks).

**Recommendation:** Stop iterating once shocks are older than `RL_SHOCK_REHAB_DAYS` and remove them from the list. Or break early when `diff > RL_SHOCK_REHAB_DAYS` for the rest.

### 4. **trim_working_set()**

Calls PowerShell to `EmptyWorkingSet` for all processes. `system()` is slow and is invoked once (two-pass mode) or not at all (normal mode).

**Recommendation:** Keep as-is; it runs only in two-pass mode. If needed, add a flag to skip it for speed testing.

### 5. **Multiple asort() calls**

`asort(all_trade_ces)`, `asort(all_hold_days)`, `asort(pos_array)`, `asorti(all_trading_dates, sorted_dates)`, etc. Each is O(n log n).

**Recommendation:** Low priority; run infrequently in END. Only optimize if instrumentation shows END block is a large share of time.

### 6. **Array access patterns**

`raw_op[sym, iso]`, `sma50[iso]`, etc. are used constantly. AWK’s associative arrays are generally efficient, but repeated lookups add up.

**Recommendation:** Cache frequently used values in local variables for the current bar (e.g. `sma50_iso = sma50[iso]`) instead of multiple `sma50[iso]` lookups.

### 7. **debug_printf / debug_print**

When `DEBUG_SYM` is set, these run on every bar and do `sprintf` + file I/O.

**Recommendation:** Ensure `DEBUG_SYM` is unset in production runs.

### 8. **Two-pass mode (RL_FLUSH_DAYS > 0)**

Runs `perform_audit()` twice for every symbol. Doubles audit cost.

**Recommendation:** No simple fix without changing semantics. Instrumentation will show how much time is in Pass1 vs Pass2.

---

## Suggested Optimization Order

1. **Add date epoch cache** – Replace `days_diff` `mktime` usage with integer day offsets from a precomputed map.
2. **Prune shock list** – Drop or skip shocks beyond rehab window to shorten the shock loop.
3. **Cache current-bar lookups** – Use local variables for `sma50[iso]`, `raw_*[sym, iso]` where used multiple times.
4. **Profile with INSTRUMENT=1** – Confirm that Scout vs Audit and END phases match expectations before deeper changes.

---

## Quick Wins

| Change | Effort | Expected Impact |
|--------|--------|-----------------|
| Unset DEBUG_SYM in production | Trivial | Avoids heavy I/O when debugging |
| Add date epoch cache for days_diff | Medium | High (many calls) |
| Early exit / prune in shock loop | Low | Medium |
| Cache sma50[iso], raw_* in inner loop | Low | Low–Medium |
| Skip trim_working_set when benchmarking | Trivial | Saves a few seconds in two-pass runs |

---

## Next Steps

1. Run with `INSTRUMENT=1` on a representative dataset.
2. Inspect `instrument.txt` for Scout vs Audit vs END timing.
3. If Audit dominates: apply date cache and shock pruning first.
4. If Scout dominates: consider faster CSV parsing or fewer columns.
5. If END dominates: profile sorts and file writes.
