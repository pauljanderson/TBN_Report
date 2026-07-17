# OHLC Inspection: 10/12 vs 10/13/2020 (NVDA)

## Raw Data (from NVDA.csv)

| Date | Open | High | Low | Close |
|------|------|------|-----|-------|
| 2020-10-12 | 13.99 | **14.3470** | 13.91 | 14.23 |
| 2020-10-13 | 14.30 | **14.3485** | 14.02 | 14.25 |

## Finding

- **10/12 High:** 14.347
- **10/13 High:** 14.3485 (0.0015 higher)

Our pivot logic uses "earliest bar wins" for ties. Here there is no tie: 10/13 has a strictly higher High. In the ±4 bar window around 10/12, the max High is 14.3485 at 10/13, so the pivot is assigned to **10/13 only**. We do not detect 10/12 as a pivot high because its High (14.347) is not the window max.

The manual system counts **both** 10/12 and 10/13 at $14.35. Likely reasons:

1. **Rounding** – They round to $14.35 and treat both as the same level, possibly counting each bar as a separate touch when price stays in zone.
2. **Bar-based touches** – They may count any bar with High in zone as a touch, not only pivot bars.
3. **Different parameters** – e.g. different window or tie-breaking.

## Recommendation

To match the manual touch count, consider:

- Allowing **consecutive bars at the same level** to count as separate touches when the price is in zone; or
- Adjusting **tie-breaking** (e.g. "latest bar wins") so 10/13 gets the pivot; we would still only have one pivot. The difference is likely due to bar-based vs pivot-only touch counting.
