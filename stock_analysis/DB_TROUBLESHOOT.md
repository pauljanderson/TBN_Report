# Dive Bomber Troubleshooting: Too Many Trades

## Current Defaults (portfolio_audit.awk)

| Parameter | Current | Header Doc | Notes |
|-----------|---------|------------|-------|
| DB_STOP_PCT | 1.0934 | 1.05 | 9.34% stop (wider than doc) |
| DB_TARGET_PCT | 0.80 | 0.90 | 20% profit target |
| DB_RIP_DAYS_MIN | 3 | 3 | **Never used in logic** |
| DB_RIP_DAYS_MAX | 5 | 5 | Used for rip lookback |
| DB_RIP_TOUCH_TOL | 0.024 | 0.02 | 2.4% tolerance |
| DB_MAX_HOLD_DAYS | 32 | 10 | Long hold window |
| DB_SQUEEZE_EXIT | 0 | 20 | **Off** – no squeeze protection |
| DB_INVERSE_STRICT | 1 | 1 | 50<100<200 required |
| DB_SLOPE_LOOKBACK | 4 | 4 | 4-day falling 50 SMA |
| DB_GAP_UP_MAX | 1.14 | 1.05 | **Very permissive** – allows 14% above 50 SMA |

---

## Entry Logic (all must be true)

1. **db_inv == 0** – not in a short
2. **j > 205** – enough history (200 + 5)
3. **inverse_stack** – 50 < 100 < 200 (bearish)
4. **falling_50** – SMA50 today < SMA50 from 4 days ago
5. **rip_ok** – close today > close from 5 days ago
6. **touch_50** – high today ≥ SMA50 × 0.976 (within 2.4% of 50 SMA)
7. **gap_ok** – next day open ≤ SMA50 × 1.14 (up to 14% above 50 SMA)
8. Next day exists and has valid open

---

## Issues That Likely Cause Too Many Trades

### 1. **DB_RIP_DAYS_MIN is never used**

`rip_ok` only checks: close today > close from 5 days ago. Any 5-day rally qualifies.

- **Intended behavior:** Rally should occur within a 3–5 day window.
- **Current behavior:** Any positive 5-day move counts as a rip.
- **Fix:** Use `DB_RIP_DAYS_MIN` so the rally is constrained to the last 3–5 days (e.g. close > close from 5 days ago AND close > close from 3 days ago, or similar).

### 2. **DB_GAP_UP_MAX = 1.14 is very loose**

- **Intended:** Short when price rallies to the 50 SMA and opens near it.
- **Current:** Allows shorts when next open is up to 14% above the 50 SMA.
- **Fix:** Lower to 1.03–1.05 so entries are closer to the 50 SMA.

### 3. **No cooldown after exit**

After exiting (e.g. MAX_HOLD), the same symbol can re-enter the next day if conditions still hold.

- **Fix:** Add `DB_COOLDOWN_DAYS` – no new short in the same symbol for N days after exit.

### 4. **rip_ok is too weak**

- Only checks: close > close 5 days ago.
- No minimum rally size (e.g. 2–3%).
- **Fix:** Add something like `(raw_cl - rip_cl_old) / rip_cl_old >= DB_RIP_MIN_PCT` (e.g. 0.02 for 2%).

### 5. **DB_SQUEEZE_EXIT = 0**

Squeeze exit is off, so shorts can run through strong rallies until stop or MAX_HOLD.

- **Fix:** Turn on squeeze (e.g. 20-day high) to cut bad shorts earlier.

### 6. **touch_50 is permissive**

`raw_hi >= sma50 * 0.976` – high only needs to be within 2.4% of the 50 SMA.

- **Fix:** Tighten `DB_RIP_TOUCH_TOL` to 0.01 (1%) or require close to be near the 50 SMA, not just the high.

---

## Recommended Changes (in order of impact)

1. **Tighten DB_GAP_UP_MAX** – 1.14 → 1.05 (or 1.03)
2. **Add DB_COOLDOWN_DAYS** – e.g. 5–10 days
3. **Use DB_RIP_DAYS_MIN** – require rally within the 3–5 day window
4. **Add DB_RIP_MIN_PCT** – minimum rally size (e.g. 2%)
5. **Enable DB_SQUEEZE_EXIT** – e.g. 20-day high
6. **Tighten DB_RIP_TOUCH_TOL** – 0.024 → 0.01 or 0.015
