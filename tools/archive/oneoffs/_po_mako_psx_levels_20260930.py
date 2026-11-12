"""Measure MAKO levels and PSX June 2026 path from daily warehouse. Scratch for stamp."""
from __future__ import annotations

import duckdb
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_daily(sym: str) -> pd.DataFrame:
    p = ROOT / "data" / "newdata" / "data" / f"{sym}.csv"
    df = pd.read_csv(p)
    df.columns = [c.strip().lower() for c in df.columns]
    # common date col names
    for c in ("date", "datetime", "timestamp"):
        if c in df.columns:
            df["date"] = pd.to_datetime(df[c])
            break
    df = df.sort_values("date").reset_index(drop=True)
    for c in ("open", "high", "low", "close", "volume"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def duck_sample():
    c = duckdb.connect(str(ROOT / "data" / "ohlcv.duckdb"), read_only=True)
    tables = c.execute("SHOW TABLES").fetchall()
    print("TABLES", tables)
    return c


def gaps(df: pd.DataFrame, start: str, end: str) -> None:
    sub = df[(df["date"] >= start) & (df["date"] <= end)].copy()
    sub["prev_close"] = df["close"].shift(1).loc[sub.index]
    sub["gap_up"] = sub["low"] - sub["prev_close"]
    sub["gap_dn"] = sub["prev_close"] - sub["high"]
    print("--- bars", start, end, "n", len(sub))
    ups = sub[sub["low"] > sub["prev_close"] * 1.005].copy()
    dns = sub[sub["high"] < sub["prev_close"] * 0.995].copy()
    print("GAP UPS (>0.5%):")
    if len(ups):
        cols = ["date", "prev_close", "open", "high", "low", "close"]
        print(ups[cols].to_string(index=False))
    else:
        print(" none")
    print("GAP DOWNS (>0.5%):")
    if len(dns):
        cols = ["date", "prev_close", "open", "high", "low", "close"]
        print(dns[cols].to_string(index=False))
    else:
        print(" none")


def fill_status(df: pd.DataFrame, gap_i: int) -> None:
    row = df.iloc[gap_i]
    prev = df.iloc[gap_i - 1]
    gap_lo = float(prev["close"])
    gap_hi = float(row["low"])
    if row["low"] < prev["close"]:
        # gap down
        gap_hi = float(prev["close"])
        gap_lo = float(row["high"])
    later = df.iloc[gap_i + 1 :]
    print(
        f"gap bar {row['date'].date()} prev_close={prev['close']:.4f} "
        f"open={row['open']:.4f} low={row['low']:.4f} high={row['high']:.4f} close={row['close']:.4f}"
    )
    # unfilled: prices between prev close and this open/low that later lows never reached
    if row["low"] > prev["close"]:
        print(f"  UP GAP range prev_close {prev['close']:.4f} -> gap open/low {row['low']:.4f}")
        filled = later[later["low"] <= prev["close"] + 1e-6]
        touched_low = later["low"].min() if len(later) else None
        print(f"  later min low={touched_low}")
        if len(filled):
            print(f"  first fill-to-prev-close {filled.iloc[0]['date'].date()} low={filled.iloc[0]['low']}")
        else:
            deepest = later.loc[later["low"].idxmin()] if len(later) else None
            print("  NOT filled to prev close")
            if deepest is not None:
                print(
                    f"  deepest low {deepest['date'].date()} {deepest['low']:.4f} "
                    f"unfilled below that to {prev['close']:.4f}"
                )
                # portion still open: from deepest low down to prev close? 
                # unfilled range is prev_close .. min(later lows that didn't reach, gap low)
                # if min later low is L, unfilled is [prev_close, L) if L > prev_close
                if float(deepest["low"]) > float(prev["close"]):
                    print(
                        f"  OPEN GAP remaining: {float(prev['close']):.4f} to {float(deepest['low']):.4f}"
                    )


def summary(sym: str) -> pd.DataFrame:
    df = load_daily(sym)
    print("\n========", sym, "rows", len(df), "cols", list(df.columns)[:12])
    print("first", df.iloc[0]["date"].date(), "last", df.iloc[-1]["date"].date())
    last = df.iloc[-1]
    print(
        f"LAST {last['date'].date()} O={last['open']:.4f} H={last['high']:.4f} "
        f"L={last['low']:.4f} C={last['close']:.4f}"
    )
    ath_i = df["high"].idxmax()
    ath = df.iloc[ath_i]
    print(f"ATH high {ath['high']:.4f} on {ath['date'].date()} close {ath['close']:.4f}")
    # recent highs
    y = df[df["date"] >= "2025-01-01"]
    print("2025-now max high", y["high"].max(), "on", y.loc[y["high"].idxmax(), "date"].date())
    print("close vs ATH", (last["close"] / ath["high"] - 1) * 100, "%")
    return df


if __name__ == "__main__":
    try:
        duck_sample()
    except Exception as e:
        print("duck err", type(e), e)
    mako = summary("MAKO")
    print("\n== MAKO gaps Aug-Sep 2026 and mid 2025-2026 ==")
    gaps(mako, "2026-07-01", "2026-09-30")
    gaps(mako, "2025-06-01", "2026-09-30")
    # also print Aug 2026 daily bars
    aug = mako[(mako["date"] >= "2026-07-15") & (mako["date"] <= "2026-09-30")]
    print("\nMAKO daily Jul15-Sep30")
    print(aug[["date", "open", "high", "low", "close"]].to_string(index=False))

    psx = summary("PSX")
    print("\n== PSX May-Sep 2026 ==")
    sub = psx[(psx["date"] >= "2026-04-01") & (psx["date"] <= "2026-09-30")]
    print(sub[["date", "open", "high", "low", "close"]].to_string(index=False))
