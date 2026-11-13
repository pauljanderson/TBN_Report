#!/usr/bin/env python3
"""Score zone-placebo runs against each system's real survivor-free run.

    python tools/honest_bt/placebo_score.py --stamp 20261112 [--systems WPBR,BRT,YH,MTS,VZ]

Reads drive/honest_bt/<stamp>/pit/<SYS> (real zones) and placebo_*/<SYS>, zplacebo_*/<SYS> (fake zones:
WPBR_PLACEBO in wpbr_zones.py; TBN_ZONE_PLACEBO in rocket_tbn.py / rocket_vz.py), applies the same PIT membership, eval window and
costs as score.py, and asks: does the real zone beat a fake one, month by month?
Writes placebo_scorecard.csv next to the runs.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from score import EVAL_START, REPO, load_closed, stats, trials_for  # noqa: E402


def _load(run_dir: Path, members: set, rt_cost: float, sys_code: str = "WPBR") -> pd.DataFrame | None:
    hits = [h for h in sorted(run_dir.glob(f"{sys_code}_Closed_*.csv")) if h.stem.split("_Closed_")[1].isdigit()]
    if not hits:
        return None
    df = load_closed(hits[-1])
    df = df[df.opened >= EVAL_START].copy()
    mon = df.opened.dt.to_period("M").astype(str)
    df = df[[(s, m) in members for s, m in zip(df.symbol, mon)]]
    df["net"] = df["gross"] - rt_cost
    return df


def _diff_t(real: pd.DataFrame, fake: pd.DataFrame) -> tuple[float, float, int]:
    """Month-clustered paired test of real-minus-placebo monthly mean net per trade."""
    a = real.groupby(real.opened.dt.to_period("M"))["net"].mean()
    b = fake.groupby(fake.opened.dt.to_period("M"))["net"].mean()
    d = (a - b).dropna()
    if len(d) < 6 or d.std(ddof=1) == 0:
        return float("nan"), float("nan"), len(d)
    return float(d.mean()), float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), len(d)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stamp", required=True)
    ap.add_argument("--cost-bps", type=float, default=10.0)
    ap.add_argument("--systems", default="WPBR,BRT,YH,MTS,VZ")
    a = ap.parse_args(argv)
    root = REPO / "drive" / "honest_bt" / a.stamp
    mem = pd.read_csv(root / "membership_pit.csv")
    members = set(zip(mem.symbol, mem.month.astype(str)))
    rt = 2 * a.cost_bps / 100.0
    rows = []
    for s in [x.strip().upper() for x in a.systems.split(",") if x.strip()]:
        trials = trials_for(s)
        real = _load(root / "pit" / s, members, rt, s)
        if real is None:
            print(f"no real PIT {s} run", file=sys.stderr)
            continue
        rows.append({"system": s, "run": "real_zones", **stats(real, trials), "diff_vs_real": None, "t_diff": None})
        for d in sorted(list(root.glob("placebo_*")) + list(root.glob("zplacebo_*"))):
            if not d.name.startswith(("placebo_random", "placebo_shift", "zplacebo_")):
                continue
            fake = _load(d / s, members, rt, s)
            if fake is None:
                continue
            dm, dt, _ = _diff_t(real, fake)
            rows.append({"system": s, "run": d.name.split("placebo_", 1)[1], **stats(fake, trials),
                         "diff_vs_real": round(-dm, 2), "t_diff": round(dt, 2)})
    out = pd.DataFrame(rows)
    out.to_csv(root / "placebo_scorecard.csv", index=False)
    cols = ["system", "run", "n", "avg_gross", "avg_net", "win", "pf", "t_month", "years_pos", "h1", "h2",
            "diff_vs_real", "t_diff", "verdict"]
    print(out[cols].to_string(index=False))
    print("\ndiff_vs_real = placebo minus real avg net per trade (monthly-paired); t_diff = its t-stat (real better if > 0)")
    print(f"wrote {root / 'placebo_scorecard.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
