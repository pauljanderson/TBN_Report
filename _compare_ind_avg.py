#!/usr/bin/env python3
"""Compare IND closed-trade stats between two BRT closed CSVs."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent


def _pct(v) -> float:
    if pd.isna(v):
        return float("nan")
    s = str(v).strip().replace("%", "")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def load_closed(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    if df.empty:
        return df
    out = pd.DataFrame()
    out["symbol"] = df["SYMBOL"]
    out["entry"] = df["DATE_OPENED"]
    out["exit"] = df.get("DATE_CLOSED", "")
    out["days"] = pd.to_numeric(df["DAYS_HELD"], errors="coerce")
    out["pnl_pct"] = df["PNL_PCT"].map(_pct)
    out["pnl_dollars"] = pd.to_numeric(df["PNL_DOLLARS"], errors="coerce")
    if "TRIGGER_DATE" in df.columns:
        out["trigger"] = df["TRIGGER_DATE"]
    return out.dropna(subset=["pnl_pct"])


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
        "wins": nw,
        "losses": nl,
        "win_rate": nw / n * 100.0,
        "avg_profit_pct": df["pnl_pct"].mean(),
        "payoff": payoff,
        "wl_counts": (nw / nl) if nl else float("inf"),
        "avg_days": df["days"].mean(),
        "total_profit": df["pnl_dollars"].sum(),
    }


def fmt_money(x: float) -> str:
    return f"${x:,.0f}"


def show_row(label: str, s: dict) -> None:
    if s["trades"] == 0:
        print(f"{label:22} (no trades)")
        return
    print(
        f"{label:22}  trades={s['trades']:5d}  win={s['win_rate']:5.1f}%  "
        f"avgP={s['avg_profit_pct']:+6.2f}%  payoff={s['payoff']:4.2f}  "
        f"days={s['avg_days']:5.1f}  total={fmt_money(s['total_profit'])}"
    )


def compare(baseline: pd.DataFrame, variant: pd.DataFrame, base_label: str, var_label: str) -> None:
    sb, sv = stats(baseline), stats(variant)
    print(f"\n=== IND comparison: {base_label} vs {var_label} ===\n")
    show_row(base_label, sb)
    show_row(var_label, sv)
    if sb["trades"] and sv["trades"]:
        print("\nDelta (variant - baseline):")
        print(f"  trades         : {sv['trades'] - sb['trades']:+d}")
        print(f"  win rate       : {sv['win_rate'] - sb['win_rate']:+.1f} pp")
        print(f"  avg profit %   : {sv['avg_profit_pct'] - sb['avg_profit_pct']:+.2f} pp")
        print(f"  payoff ratio   : {sv['payoff'] - sb['payoff']:+.2f}")
        print(f"  avg days       : {sv['avg_days'] - sb['avg_days']:+.1f}")
        print(f"  total profit   : {fmt_money(sv['total_profit'] - sb['total_profit'])}")

    # overlap analysis
    if not baseline.empty and not variant.empty:
        bset = set(zip(baseline["symbol"], baseline["entry"].astype(str)))
        vset = set(zip(variant["symbol"], variant["entry"].astype(str)))
        only_b = bset - vset
        only_v = vset - bset
        both = bset & vset
        print(f"\nTrade overlap (symbol + entry date):")
        print(f"  shared entries : {len(both)}")
        print(f"  baseline only  : {len(only_b)}")
        print(f"  variant only   : {len(only_v)}")


def main() -> int:
    base_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "drive" / "IND_LatestRun_Closed.csv"
    var_path = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "ind_avg_cmp" / "IND_Closed_latest.csv"
    if not base_path.exists():
        print(f"Missing baseline: {base_path}", file=sys.stderr)
        return 1
    if not var_path.exists():
        print(f"Missing variant: {var_path}", file=sys.stderr)
        return 1
    compare(load_closed(base_path), load_closed(var_path), base_path.name, var_path.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
