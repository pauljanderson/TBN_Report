#!/usr/bin/env python3
"""Max entry gap-up (entry open vs trigger close) per symbol for a closed run."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RUN = sys.argv[1] if len(sys.argv) > 1 else "260619145037"
SYMS = ["NFLX", "MSFT", "META", "GOOGL", "AMZN", "AAPL", "NVDA", "TSLA"]


def main() -> None:
    closed = pd.read_csv(ROOT / "Drive" / f"YH_Closed_{RUN}.csv")
    closed = closed[closed["SYMBOL"].isin(SYMS)].copy()
    closed["open_d"] = pd.to_datetime(closed["DATE_OPENED"].astype(str), format="%Y%m%d")
    closed["trigger_d"] = pd.to_datetime(closed["CLOSE_ABOVE_DATE"], errors="coerce")

    rows: list[dict] = []
    for sym in SYMS:
        df = closed[closed["SYMBOL"] == sym]
        ohlc = pd.read_csv(ROOT / "data" / "newdata" / "data" / f"{sym}.csv", parse_dates=["Date"])
        ohlc = ohlc.sort_values("Date")
        ohlc_map = {d.strftime("%Y-%m-%d"): row for d, row in zip(ohlc["Date"], ohlc.itertuples())}

        for r in df.itertuples():
            trig = r.trigger_d
            if pd.isna(trig):
                continue
            ts = trig.strftime("%Y-%m-%d")
            bar = ohlc_map.get(ts)
            if bar is None:
                continue
            trig_close = float(bar.Close)
            entry = float(r.ENTRY_PRICE)
            stop = float(r.STOP_PRICE)
            if trig_close <= 0 or entry <= 0:
                continue
            gap_pct = (entry / trig_close - 1.0) * 100.0
            rows.append(
                {
                    "symbol": sym,
                    "trigger": ts,
                    "entry_date": r.open_d.strftime("%Y-%m-%d"),
                    "trigger_close": trig_close,
                    "entry": entry,
                    "gap_up_pct": gap_pct,
                    "stop": stop,
                    "stop_pct_entry": (1.0 - stop / entry) * 100.0,
                    "stop_dollar_entry": entry - stop,
                }
            )

    allr = pd.DataFrame(rows)
    print(f"Run {RUN}\n")
    print("Per-symbol MAX gap up (entry open vs trigger close):")
    print("-" * 90)
    mx = allr.loc[allr.groupby("symbol")["gap_up_pct"].idxmax()].sort_values("gap_up_pct", ascending=False)
    for _, r in mx.iterrows():
        print(
            f"{r['symbol']:5s}  gap {r['gap_up_pct']:6.2f}%  "
            f"trigger {r['trigger']}  entry {r['entry_date']}  "
            f"entry ${r['entry']:.2f} (trigger close ${r['trigger_close']:.2f})  "
            f"stop ${r['stop']:.2f}  ({r['stop_pct_entry']:.2f}% below entry, ${r['stop_dollar_entry']:.2f})"
        )

    print("\nTop 10 gap-ups across all 8 symbols:")
    print("-" * 90)
    for _, r in allr.sort_values("gap_up_pct", ascending=False).head(10).iterrows():
        print(
            f"{r['symbol']:5s}  gap {r['gap_up_pct']:6.2f}%  "
            f"trigger {r['trigger']}  entry {r['entry_date']}  "
            f"stop ${r['stop']:.2f}  ({r['stop_pct_entry']:.2f}% below entry)"
        )


if __name__ == "__main__":
    main()
