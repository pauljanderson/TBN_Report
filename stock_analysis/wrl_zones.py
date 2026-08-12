"""WRL — Weekly Range / Swing Low demand-zone breakout.

Levels (as-of a daily bar, using only **completed** weeks):

- **Range high / range low**: high and low of the previous completed week
  (week ending Friday strictly before the as-of date).
- **Swing high**: walking backward from the week before that, the first weekly
  high that is **higher** than the previous week's high.
- **Swing low**: walking backward independently, the first weekly low that is
  **lower** than the previous week's low.

Demand zone = [swing low, range low]. Supply targets = range high, then swing high.

Daily sequence:

1. Close inside the demand zone → **WATCH**.
2. Next session opens (still not gapped down through swing low) and trades
   **up out** of the zone (High > range low) → **BUY**.
3. Fill at Open if already above range low, else at range low (intraday break).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

try:
    from wpbr_zones import aggregate_weekly
except ImportError:
    from stock_analysis.wpbr_zones import aggregate_weekly  # type: ignore


@dataclass(frozen=True)
class WeeklyLevels:
    """Completed-week structure attached to a daily bar."""

    range_high: float
    range_low: float
    swing_high: float
    swing_low: float
    range_week_end: pd.Timestamp
    swing_high_week_end: pd.Timestamp
    swing_low_week_end: pd.Timestamp
    range_week_idx: int
    swing_high_week_idx: int
    swing_low_week_idx: int


def walk_swing_high(wh: np.ndarray, range_week_idx: int) -> tuple[int, float]:
    """First week before ``range_week_idx`` whose high > previous-week high."""
    if range_week_idx < 1 or range_week_idx >= len(wh):
        return -1, float("nan")
    range_high = float(wh[range_week_idx])
    if not (np.isfinite(range_high) and range_high > 0):
        return -1, float("nan")
    for i in range(range_week_idx - 1, -1, -1):
        h = float(wh[i])
        if np.isfinite(h) and h > range_high:
            return i, h
    return -1, float("nan")


def walk_swing_low(wl: np.ndarray, range_week_idx: int) -> tuple[int, float]:
    """First week before ``range_week_idx`` whose low < previous-week low."""
    if range_week_idx < 1 or range_week_idx >= len(wl):
        return -1, float("nan")
    range_low = float(wl[range_week_idx])
    if not (np.isfinite(range_low) and range_low > 0):
        return -1, float("nan")
    for i in range(range_week_idx - 1, -1, -1):
        lo = float(wl[i])
        if np.isfinite(lo) and lo < range_low:
            return i, lo
    return -1, float("nan")


def compute_week_swings(weekly: pd.DataFrame) -> list[Optional[WeeklyLevels]]:
    """Per weekly bar: structure treating **that** bar as the previous (range) week.

    Index ``i`` is valid only when week ``i`` is a completed previous week for
    later daily bars. Swing search starts at ``i-1``.
    """
    if weekly is None or len(weekly) == 0:
        return []
    wh = weekly["High"].to_numpy(dtype=np.float64)
    wl = weekly["Low"].to_numpy(dtype=np.float64)
    ends = pd.DatetimeIndex(weekly.index).normalize()
    n = len(weekly)
    out: list[Optional[WeeklyLevels]] = []
    for i in range(n):
        if i < 1:
            out.append(None)
            continue
        rh, rl = float(wh[i]), float(wl[i])
        if not (np.isfinite(rh) and np.isfinite(rl) and rh > 0 and rl > 0 and rh >= rl):
            out.append(None)
            continue
        sh_i, sh = walk_swing_high(wh, i)
        sl_i, sl = walk_swing_low(wl, i)
        if sh_i < 0 or sl_i < 0:
            out.append(None)
            continue
        if not (sl < rl <= rh < sh):
            out.append(None)
            continue
        out.append(
            WeeklyLevels(
                range_high=rh,
                range_low=rl,
                swing_high=sh,
                swing_low=sl,
                range_week_end=pd.Timestamp(ends[i]),
                swing_high_week_end=pd.Timestamp(ends[sh_i]),
                swing_low_week_end=pd.Timestamp(ends[sl_i]),
                range_week_idx=i,
                swing_high_week_idx=sh_i,
                swing_low_week_idx=sl_i,
            )
        )
    return out


def _prev_completed_week_idx(week_ends: np.ndarray, asof: np.datetime64) -> int:
    """Last Friday week-end strictly before ``asof`` (in-progress week excluded)."""
    idx = int(np.searchsorted(week_ends, asof, side="left")) - 1
    if idx < 0:
        return -1
    return idx


def attach_daily_levels(
    df: pd.DataFrame,
    *,
    weekly: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, list[Optional[WeeklyLevels]], np.ndarray]:
    """Map each daily bar to completed-week range/swing levels.

    Returns ``(weekly, swings_by_week, week_idx_by_daily)`` where
    ``week_idx_by_daily[t]`` is the previous-completed-week index or -1.
    """
    if weekly is None:
        weekly = aggregate_weekly(df)
    swings = compute_week_swings(weekly)
    dates = pd.DatetimeIndex(df.index).normalize()
    week_ends = pd.DatetimeIndex(weekly.index).normalize().to_numpy()
    n = len(df)
    week_idx = np.full(n, -1, dtype=np.int32)
    asof = dates.to_numpy()
    for t in range(n):
        week_idx[t] = _prev_completed_week_idx(week_ends, asof[t])
    return weekly, swings, week_idx


def close_in_demand_zone(close: float, levels: WeeklyLevels) -> bool:
    """True when close is inside [swing_low, range_low] inclusive."""
    return float(levels.swing_low) <= float(close) <= float(levels.range_low)


def breakout_up_from_demand(
    open_: float,
    high: float,
    levels: WeeklyLevels,
) -> bool:
    """Next-day buy: did not gap down through swing low, and traded above range low."""
    if float(open_) < float(levels.swing_low):
        return False
    return float(high) > float(levels.range_low)


def fill_price(open_: float, levels: WeeklyLevels) -> float:
    """Fill at the open if already out of the zone, else at range low."""
    op = float(open_)
    zh = float(levels.range_low)
    return op if op >= zh else zh


def levels_for_bar(
    swings: list[Optional[WeeklyLevels]],
    week_idx: np.ndarray,
    bar: int,
) -> Optional[WeeklyLevels]:
    if bar < 0 or bar >= len(week_idx):
        return None
    wi = int(week_idx[bar])
    if wi < 0 or wi >= len(swings):
        return None
    return swings[wi]
