#!/usr/bin/env python3
"""Score wpbr_mtf.py runs: PIT membership, entries 2019+, costs, month-clustered t, placebo gap.

    python tools/honest_bt/mtf_score.py --root drive/honest_bt/20261113/mtf --trials 51
Each sub-folder with a trades.csv is a run; runs named <base>__placebo_s<k> are compared with <base>.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from score import EVAL_START, REPO, stats  # noqa: E402
from placebo_score import _diff_t  # noqa: E402


def load(run: Path, members: set, rt: float) -> pd.DataFrame:
    df = pd.read_csv(run / "trades.csv", parse_dates=["opened", "closed"])
    df = df[df.closed.notna()]  # open trades are not scored (same as engine Closed files)
    df = df[df.opened >= EVAL_START].copy()
    mon = df.opened.dt.to_period("M").astype(str)
    df = df[[(s, m) in members for s, m in zip(df.symbol, mon)]].copy()
    df["net"] = df["gross"] - rt
    return df


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True)
    ap.add_argument("--stamp", default="20261112", help="membership source")
    ap.add_argument("--trials", type=int, default=51)
    ap.add_argument("--cost-bps", type=float, default=10.0)
    a = ap.parse_args(argv)
    root = REPO / a.root if not Path(a.root).is_absolute() else Path(a.root)
    mem = pd.read_csv(REPO / "drive" / "honest_bt" / a.stamp / "membership_pit.csv")
    members = set(zip(mem.symbol, mem.month.astype(str)))
    rt = 2 * a.cost_bps / 100.0
    runs = {p.parent.name: p.parent for p in sorted(root.glob("*/trades.csv"))}
    data = {k: load(v, members, rt) for k, v in runs.items()}
    rows, years = [], {}
    for k, df in data.items():
        base, _, plc = k.partition("__")
        r = {"run": k, **stats(df, a.trials)}
        if plc and base in data:
            dm, dt, _ = _diff_t(data[base], df)
            r["diff_vs_real"], r["t_diff"] = round(-dm, 2), round(dt, 2)
        rows.append(r)
        years[k] = df.groupby(df.opened.dt.year)["net"].mean().round(2)
    out = pd.DataFrame(rows)
    out.to_csv(root / f"scorecard_{int(a.cost_bps)}bps.csv", index=False)
    cols = [c for c in ["run", "n", "avg_gross", "avg_net", "win", "pf", "t_month", "t_bar", "years_pos", "h1", "h2",
                        "breakeven_bps", "diff_vs_real", "t_diff", "verdict"] if c in out]
    print(out[cols].to_string(index=False))
    print("\nnet per trade by year:")
    print(pd.DataFrame(years).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
