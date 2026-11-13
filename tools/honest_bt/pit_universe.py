"""Point-in-time universe rule for the honest backtest harness.

A symbol is in the universe for calendar month M if, on the last trading bar
BEFORE M starts (so it is knowable when M's trades are decided):
  - it has at least MIN_HISTORY_BARS of history,
  - its 60-bar median close is >= MIN_PRICE,
  - its 60-bar median dollar volume (Close * Volume) is >= MIN_DOLLAR_VOL.

No hand-picked lists, no performance-based selection. Calibrated so breadth is
similar to the current warehouse (its 25th percentile name trades ~$7-18M/day).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

MIN_HISTORY_BARS = 200
MIN_PRICE = 5.0
MIN_DOLLAR_VOL = 10_000_000.0
WINDOW = 60


def _liquidity(df: pd.DataFrame) -> pd.DataFrame:
    px = df["Close"].rolling(WINDOW, min_periods=WINDOW).median()
    dv = (df["Close"] * df["Volume"]).rolling(WINDOW, min_periods=WINDOW).median()
    n = pd.Series(range(1, len(df) + 1), index=df.index)
    ok = (n >= MIN_HISTORY_BARS) & (px >= MIN_PRICE) & (dv >= MIN_DOLLAR_VOL)
    return pd.DataFrame({"ok": ok})


def ever_eligible(df: pd.DataFrame) -> bool:
    """Cheap pre-filter: was the symbol ever in the universe on any bar?"""
    if len(df) < MIN_HISTORY_BARS:
        return False
    return bool(_liquidity(df)["ok"].any())


def monthly_membership(df: pd.DataFrame) -> list[str]:
    """Months ('YYYY-MM') during which this symbol is a universe member."""
    liq = _liquidity(df)
    idx = pd.to_datetime(pd.Index(df.index))
    liq.index = idx
    # Last bar of each month decides membership for the NEXT month.
    month_end = liq.groupby(idx.to_period("M")).tail(1)
    months = []
    for ts, row in month_end.iterrows():
        if bool(row["ok"]):
            months.append(str((pd.Timestamp(ts).to_period("M") + 1)))
    return months


def build_membership(data_dir: str | Path) -> pd.DataFrame:
    """symbol, month rows for every CSV in data_dir (SPY and _files skipped)."""
    rows = []
    for f in sorted(Path(data_dir).glob("*.csv")):
        if f.stem.upper() == "SPY" or f.name.startswith("_"):
            continue
        df = pd.read_csv(f, usecols=["Date", "Close", "Volume"], parse_dates=["Date"]).set_index("Date")
        for m in monthly_membership(df):
            rows.append((f.stem.upper(), m))
    return pd.DataFrame(rows, columns=["symbol", "month"])
