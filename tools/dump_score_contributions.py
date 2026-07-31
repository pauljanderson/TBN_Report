#!/usr/bin/env python3
"""Dump baseline-relative composite score contributions for a ranking.csv.

Same formula as tools/run_rs_one_flag_score_opt.py / run_rs_target_stop_pairs_opt.py:
  higher-better: v/b ; lower-better (maxdd, losing_streak, p90_days): b/v
  contribution_pts = index * weight ; score = sum(contribution_pts)

Usage:
  python tools/dump_score_contributions.py \\
    --ranking drive/paul_experiments/rs_one_flag_score_opt/ranking.csv \\
    --baseline-label baseline

  python tools/dump_score_contributions.py \\
    --ranking drive/paul_experiments/rs_one_flag_score_opt/target_stop_pairs/ranking.csv \\
    --baseline-label pair_t1p25_s0p88
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

W = {
    "ppcd": 15.0,
    "pnl": 15.0,
    "maxdd": 15.0,
    "pf": 15.0,
    "expectancy_pct": 15.0,
    "wlr": 10.0,
    "losing_streak": 10.0,
    "p90_days": 5.0,
}
HIGHER = ("ppcd", "pnl", "pf", "expectancy_pct", "wlr")
LOWER = ("maxdd", "losing_streak", "p90_days")
# ranking.csv column aliases
COL = {
    "ppcd": "ppcd",
    "pnl": "pnl",
    "maxdd": "maxdd",
    "pf": "pf",
    "expectancy_pct": "expectancy_pct",
    "wlr": "wlr",
    "losing_streak": "losing_streak",
    "p90_days": "p90_days",
}


def _f(row: dict, key: str) -> float:
    v = row.get(key, "")
    if v is None or v == "":
        return 0.0
    return float(v)


def ratio_higher(v: float, b: float) -> float:
    if b == 0:
        return 1.0 if v == 0 else (2.0 if v > 0 else 0.0)
    return v / b


def ratio_lower(v: float, b: float) -> float:
    if v == 0:
        return 2.0 if b > 0 else 1.0
    if b == 0:
        return 1.0
    return b / v


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ranking", required=True, type=Path)
    ap.add_argument("--baseline-label", default="baseline")
    ap.add_argument("--labels", default="", help="Comma-separated labels to include (default: all)")
    args = ap.parse_args()

    with args.ranking.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("empty ranking", file=sys.stderr)
        return 1

    by_label = {r["label"]: r for r in rows}
    if args.baseline_label not in by_label:
        print(f"baseline label {args.baseline_label!r} not in ranking", file=sys.stderr)
        return 1
    base = by_label[args.baseline_label]

    want = [s.strip() for s in args.labels.split(",") if s.strip()] or [r["label"] for r in rows]

    hdr = [
        "label",
        "score_reported",
        "score_recon",
        "score_p90_frozen",
        *[f"idx_{k}" for k in W],
        *[f"contrib_{k}" for k in W],
        *[f"delta_{k}" for k in W],
    ]
    print(",".join(hdr))
    for lab in want:
        if lab not in by_label:
            continue
        r = by_label[lab]
        idx: dict[str, float] = {}
        contrib: dict[str, float] = {}
        for k in HIGHER:
            idx[k] = ratio_higher(_f(r, COL[k]), _f(base, COL[k]))
            contrib[k] = idx[k] * W[k]
        for k in LOWER:
            idx[k] = ratio_lower(_f(r, COL[k]), _f(base, COL[k]))
            contrib[k] = idx[k] * W[k]
        recon = sum(contrib.values())
        frozen = recon - contrib["p90_days"] + W["p90_days"]
        reported = r.get("score", "")
        deltas = {k: contrib[k] - W[k] for k in W}
        out = [
            lab,
            str(reported),
            f"{recon:.4f}",
            f"{frozen:.4f}",
            *[f"{idx[k]:.6f}" for k in W],
            *[f"{contrib[k]:.4f}" for k in W],
            *[f"{deltas[k]:.4f}" for k in W],
        ]
        print(",".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
