#!/usr/bin/env python3
"""Score every system the same honest way and write the scorecard.

Variants (columns of the scorecard):
  reported : drive/<SYS>_LatestRun_Closed.csv as production reports it
             (curated universe, survivor data, no costs)
  rule     : same engine + profile, ALL symbols in the canonical warehouse,
             kept only when the symbol was in the point-in-time universe that month
  pit      : same, on survivor-free Alpaca data (data/pit_daily)

All variants: entries from EVAL_START, costs COST_BPS per side, t-stat clustered
by entry month (trades in the same month are not independent), and a
multiple-testing bar sqrt(2 ln N) where N = variants tried for that system.

Usage: python tools/honest_bt/score.py --stamp 20261112 [--cost-bps 10]
Writes drive/honest_bt/<stamp>/scorecard.csv and scorecard.json
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
from pit_universe import build_membership  # noqa: E402

SYSTEMS = ["BRT", "YH", "MTS", "WPBR", "RS", "SB", "VZ", "RSI", "WRL", "RL"]
EVAL_START = "2019-01-01"
SPLIT = "2023-01-01"  # first half 2019-2022 vs second half 2023-now
DATA = {"rule": REPO / "data" / "newdata" / "data", "pit": REPO / "data" / "pit_daily"}
RUN_DIR = {"rule": "canon", "pit": "pit"}  # run_honest.py --variant names


def load_closed(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    df.columns = [c.strip().upper().replace(" ", "_") for c in df.columns]
    pc = "PNL_%" if "PNL_%" in df.columns else "PNL_PCT"
    out = pd.DataFrame({
        "symbol": df["SYMBOL"].astype(str).str.upper().str.strip(),
        "opened": pd.to_datetime(df["DATE_OPENED"].astype(str).str[:8], format="%Y%m%d", errors="coerce"),
        "closed": pd.to_datetime(df["DATE_CLOSED"].astype(str).str[:8], format="%Y%m%d", errors="coerce"),
        "gross": pd.to_numeric(df[pc].astype(str).str.replace("%", "", regex=False), errors="coerce"),
    })
    return out.dropna(subset=["opened", "gross"])


def trials_for(sys_code: str) -> int:
    """How many variants were tried: experiment folders + A/B launchers for this system."""
    pat = re.compile(rf"^{sys_code}[_\-]", re.I)
    n = 0
    exp = REPO / "drive" / "paul_experiments"
    if exp.is_dir():
        n += sum(1 for p in exp.iterdir() if pat.match(p.name))
    n += sum(1 for p in REPO.glob(f"run_{sys_code.lower()}_*ab*.bat"))
    return max(n, 1)


def clustered_t(df: pd.DataFrame) -> float:
    m = df.groupby(df["opened"].dt.to_period("M"))["net"].mean()
    if len(m) < 6 or m.std(ddof=1) == 0:
        return float("nan")
    return float(m.mean() / (m.std(ddof=1) / math.sqrt(len(m))))


def stats(df: pd.DataFrame, trials: int) -> dict:
    if df.empty:
        return {"n": 0}
    net = df["net"]
    wins, losses = net[net > 0].sum(), -net[net < 0].sum()
    years = df.groupby(df["opened"].dt.year)["net"].mean()
    h1, h2 = df[df.opened < SPLIT]["net"], df[df.opened >= SPLIT]["net"]
    t = clustered_t(df)
    bar = math.sqrt(2 * math.log(trials)) if trials > 1 else 1.96
    bar = max(bar, 1.96)
    avg = float(net.mean())
    if avg <= 0:
        verdict = "FAIL"
    elif t >= bar and h1.mean() > 0 and h2.mean() > 0:
        verdict = "PASS"
    else:
        verdict = "WEAK"
    span_years = max((df.opened.max() - df.opened.min()).days / 365.25, 0.5)
    return {
        "n": int(len(df)), "per_year": round(len(df) / span_years, 1),
        "avg_gross": round(float(df["gross"].mean()), 2), "avg_net": round(avg, 2),
        "win": round(float((net > 0).mean()), 3),
        "pf": round(float(wins / losses), 2) if losses > 0 else None,
        "t_month": round(t, 2) if not math.isnan(t) else None, "t_bar": round(bar, 2),
        "years_pos": f"{int((years > 0).sum())}/{len(years)}",
        "h1": round(float(h1.mean()), 2) if len(h1) else None,
        "h2": round(float(h2.mean()), 2) if len(h2) else None,
        "breakeven_bps": round(float(df["gross"].mean()) * 100 / 2, 0),
        "verdict": verdict,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stamp", required=True)
    ap.add_argument("--cost-bps", type=float, default=10.0, help="per side")
    a = ap.parse_args(argv)
    root = REPO / "drive" / "honest_bt" / a.stamp
    rt_cost = 2 * a.cost_bps / 100.0  # percent round trip

    members: dict[str, set] = {}
    for v, d in DATA.items():
        if (root / RUN_DIR[v]).is_dir() and d.is_dir():
            mem = build_membership(d)
            members[v] = set(zip(mem.symbol, mem.month))
            mem.to_csv(root / f"membership_{v}.csv", index=False)

    rows, out = [], {"stamp": a.stamp, "cost_bps_per_side": a.cost_bps, "eval_start": EVAL_START,
                     "split": SPLIT, "systems": {}}
    for s in SYSTEMS:
        trials = trials_for(s)
        rec = {"trials": trials}
        srcs = {"reported": REPO / "drive" / f"{s}_LatestRun_Closed.csv"}
        for v in ("rule", "pit"):
            vd = root / RUN_DIR[v] / s
            hits = sorted(vd.glob("*_Closed_*.csv")) if vd.is_dir() else []
            hits = [h for h in hits if h.stem.split("_Closed_")[1].isdigit()]
            if hits:
                srcs[v] = hits[-1]
        for v, p in srcs.items():
            if not p.exists():
                continue
            df = load_closed(p)
            df = df[df.opened >= EVAL_START].copy()
            if v in members:
                mon = df.opened.dt.to_period("M").astype(str)
                df = df[[(sym, m) in members[v] for sym, m in zip(df.symbol, mon)]]
            df["net"] = df["gross"] - rt_cost
            st = stats(df, trials)
            st["source"] = str(p.relative_to(REPO))
            rec[v] = st
            rows.append({"system": s, "variant": v, "trials": trials, **{k: x for k, x in st.items() if k != "source"}})
        out["systems"][s] = rec
    pd.DataFrame(rows).to_csv(root / "scorecard.csv", index=False)
    (root / "scorecard.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(pd.DataFrame(rows).to_string(index=False))
    print(f"\nwrote {root / 'scorecard.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
