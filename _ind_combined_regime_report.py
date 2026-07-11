#!/usr/bin/env python3
"""Filter all-system closed trades to trigger dates when combined IND was in a trade."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DRIVE = ROOT / "drive"
RL_CASH = 47500.0

COMBINED_IND_CLOSED = ROOT / "ind_avg_both" / "IND_Closed_260702092427.csv"
COMBINED_IND_OPEN = ROOT / "ind_avg_both" / "IND_Open_260702092427.csv"


def _norm_date(v) -> str:
    return str(v).strip().replace("-", "")[:8]


def _pct(v) -> float:
    s = str(v).strip().replace("%", "")
    if s == "" or s.lower() == "nan":
        return np.nan
    return float(s)


def load_calendar() -> tuple[list[str], dict[str, str]]:
    spy = pd.read_csv(ROOT / "data" / "newdata" / "data" / "SPY.csv")
    spy["Date"] = pd.to_datetime(spy["Date"]).dt.strftime("%Y%m%d")
    ordered = list(spy["Date"])
    prior = {ordered[i]: ordered[i - 1] for i in range(1, len(ordered))}
    return ordered, prior


def expand_range(opened: str, closed: str, ordered: list[str]) -> set[str]:
    """Trading days from entry through exit inclusive."""
    if not opened or not closed:
        return set()
    try:
        i0 = ordered.index(opened)
        i1 = ordered.index(closed)
    except ValueError:
        return set()
    if i1 < i0:
        i0, i1 = i1, i0
    return set(ordered[i0 : i1 + 1])


def build_combined_ind_in_trade_days(ordered: list[str]) -> set[str]:
    days: set[str] = set()
    if COMBINED_IND_CLOSED.exists():
        df = pd.read_csv(COMBINED_IND_CLOSED, low_memory=False)
        for _, r in df.iterrows():
            days |= expand_range(_norm_date(r["DATE_OPENED"]), _norm_date(r["DATE_CLOSED"]), ordered)
    if COMBINED_IND_OPEN.exists():
        df = pd.read_csv(COMBINED_IND_OPEN, low_memory=False)
        last_day = ordered[-1] if ordered else ""
        for _, r in df.iterrows():
            days |= expand_range(_norm_date(r["DATE_OPENED"]), last_day, ordered)
    return days


def load_brt_like(path: Path, system: str) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, low_memory=False)
    if df.empty:
        return pd.DataFrame()
    out = pd.DataFrame()
    out["symbol"] = df["SYMBOL"]
    out["entry"] = df["DATE_OPENED"].map(_norm_date)
    out["days"] = pd.to_numeric(df["DAYS_HELD"], errors="coerce")
    out["pnl_pct"] = df["PNL_PCT"].map(_pct)
    out["pnl_dollars"] = pd.to_numeric(df["PNL_DOLLARS"], errors="coerce")
    out["system"] = system
    return out


def load_rl(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, low_memory=False)
    if df.empty:
        return pd.DataFrame()
    out = pd.DataFrame()
    out["symbol"] = df["SYMBOL"]
    out["entry"] = df["DATE OPENED"].map(_norm_date)
    out["days"] = pd.to_numeric(df["DAYS HELD"], errors="coerce")
    out["pnl_pct"] = df["PNL %"].map(_pct)
    out["pnl_dollars"] = out["pnl_pct"] / 100.0 * RL_CASH
    out["system"] = "RL"
    return out


def stats(df: pd.DataFrame) -> dict:
    n = len(df)
    if n == 0:
        return {"trades": 0}
    wins = df[df["pnl_pct"] > 0]
    losses = df[df["pnl_pct"] < 0]
    nw, nl = len(wins), len(losses)
    avg_win = wins["pnl_pct"].mean() if nw else 0.0
    avg_loss = losses["pnl_pct"].mean() if nl else 0.0
    payoff = (avg_win / abs(avg_loss)) if (nl and avg_loss != 0) else float("inf")
    return {
        "trades": n,
        "win_rate": nw / n * 100.0,
        "avg_profit_pct": df["pnl_pct"].mean(),
        "wl_ratio_counts": (nw / nl) if nl else float("inf"),
        "payoff": payoff,
        "avg_days": df["days"].mean(),
        "total_profit": df["pnl_dollars"].sum(),
        "wins": nw,
        "losses": nl,
    }


def show(title: str, df: pd.DataFrame) -> None:
    s = stats(df)
    print(f"\n===== {title} =====")
    if s["trades"] == 0:
        print("  (no trades)")
        return
    print(f"  Total trades      : {s['trades']}  ({s['wins']}W / {s['losses']}L)")
    print(f"  Win rate          : {s['win_rate']:.1f}%")
    print(f"  Average profit %   : {s['avg_profit_pct']:+.2f}%")
    print(
        f"  Win/Loss ratio     : {s['payoff']:.2f}  (avg win% / avg loss%)   |  "
        f"counts {s['wl_ratio_counts']:.2f} (W:L)"
    )
    print(f"  Avg days in trade  : {s['avg_days']:.1f}")
    print(f"  Total profit       : ${s['total_profit']:,.0f}")
    print("  by system:")
    for sysname in ["BRT", "IND", "RL", "YH"]:
        sub = df[df["system"] == sysname]
        ss = stats(sub)
        if ss["trades"] == 0:
            continue
        print(
            f"    {sysname:3}: {ss['trades']:4d} trades | win {ss['win_rate']:5.1f}% | "
            f"avgP {ss['avg_profit_pct']:+6.2f}% | ${ss['total_profit']:>12,.0f}"
        )


def main() -> None:
    ordered, prior = load_calendar()
    in_trade_days = build_combined_ind_in_trade_days(ordered)

    n_closed = len(pd.read_csv(COMBINED_IND_CLOSED)) if COMBINED_IND_CLOSED.exists() else 0
    n_open = len(pd.read_csv(COMBINED_IND_OPEN)) if COMBINED_IND_OPEN.exists() else 0
    print(
        f"Combined IND (use_average_ind + average_ind_combine): "
        f"{n_closed} closed + {n_open} open trades"
    )
    print(f"Union in-trade trading days: {len(in_trade_days)}")

    frames = [
        load_brt_like(DRIVE / "BRT_LatestRun_Closed.csv", "BRT"),
        load_brt_like(DRIVE / "IND_LatestRun_Closed.csv", "IND"),
        load_brt_like(DRIVE / "YH_LatestRun_Closed.csv", "YH"),
        load_rl(DRIVE / "RL_LatestRun_Closed.csv"),
    ]
    trades = pd.concat([f for f in frames if not f.empty], ignore_index=True)
    trades = trades.dropna(subset=["pnl_pct"])
    trades["trigger"] = trades["entry"].map(prior)

    filtered = trades[trades["trigger"].isin(in_trade_days)]
    excluded = trades[~trades["trigger"].isin(in_trade_days)]

    print("(Filter: keep trades whose TRIGGER date falls on a combined-IND in-trade day)")
    show("BASELINE — all systems, all trades", trades)
    show("FILTERED — trigger on combined-IND in-trade day", filtered)
    show("EXCLUDED — trigger NOT on combined-IND in-trade day", excluded)

    sb, sf = stats(trades), stats(filtered)
    if sb["trades"] and sf["trades"]:
        print("\nDelta (filtered - baseline):")
        print(f"  trades         : {sf['trades'] - sb['trades']:+d} ({100*sf['trades']/sb['trades']:.1f}% of baseline)")
        print(f"  win rate       : {sf['win_rate'] - sb['win_rate']:+.1f} pp")
        print(f"  avg profit %   : {sf['avg_profit_pct'] - sb['avg_profit_pct']:+.2f} pp")
        print(f"  payoff ratio   : {sf['payoff'] - sb['payoff']:+.2f}")
        print(f"  avg days       : {sf['avg_days'] - sb['avg_days']:+.1f}")
        print(f"  total profit   : ${sf['total_profit'] - sb['total_profit']:+,.0f}")


if __name__ == "__main__":
    main()
