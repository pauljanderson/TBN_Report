"""Compare entry quality features: post_target_quick_stop fails vs NTRA/AU ladder re-entries."""
from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median

PATH = Path(r"drive/RL_Closed_260730094107.csv")


def col(r, *names):
    upper = {k.upper().replace("_", " "): v for k, v in r.items()}
    for n in names:
        key = n.upper().replace("_", " ")
        if key in upper and upper[key] not in (None, ""):
            return upper[key]
    # also try underscore form
    upper2 = {k.upper(): v for k, v in r.items()}
    for n in names:
        if n.upper() in upper2 and upper2[n.upper()] not in (None, ""):
            return upper2[n.upper()]
    return ""


def ymd(s: str) -> str:
    s = str(s).strip().replace("-", "")[:8]
    return s if len(s) == 8 and s.isdigit() else ""


def fnum(x, default=None):
    try:
        return float(str(x).replace("%", "").strip())
    except Exception:
        return default


def gap_days(a, b):
    da = datetime.strptime(ymd(a), "%Y%m%d")
    db = datetime.strptime(ymd(b), "%Y%m%d")
    return (db - da).days


def main() -> None:
    with PATH.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    by = defaultdict(list)
    for r in rows:
        sym = str(col(r, "SYMBOL")).strip().upper()
        if sym:
            by[sym].append(r)
    for sym in by:
        by[sym].sort(key=lambda r: (ymd(col(r, "DATE OPENED")), ymd(col(r, "DATE CLOSED"))))

    def feat(r):
        entry = fnum(col(r, "ENTRY PRICE"))
        s20 = fnum(col(r, "SMA20"))
        s50 = fnum(col(r, "SMA50"))
        s100 = fnum(col(r, "SMA100"))
        s200 = fnum(col(r, "SMA200"))
        slope = fnum(col(r, "SLOPE AT ENTRY", "SLOPE_AT_ENTRY"))
        # stack gaps as fractions
        g20_50 = (s20 / s50 - 1.0) if s20 and s50 else None
        g50_100 = (s50 / s100 - 1.0) if s50 and s100 else None
        g100_200 = (s100 / s200 - 1.0) if s100 and s200 else None
        # dip depth: how far entry below SMA50 (negative = below)
        dip = (entry / s50 - 1.0) if entry and s50 else None
        # hist high pct as cut_the_losers proxy (prior high extension above SMA)
        hist_hi = fnum(col(r, "HIST_HIGH_PCT"))
        cth = fnum(col(r, "CLOSE TO HIGH", "CLOSE_TO_HIGH"))
        return {
            "slope": slope,
            "g20_50": g20_50,
            "g50_100": g50_100,
            "g100_200": g100_200,
            "dip": dip,
            "hist_hi": hist_hi,
            "cth": cth,
            "days": fnum(col(r, "DAYS HELD")),
            "pnl": fnum(col(r, "PNL %", "PNL_PCT")),
        }

    fails = []
    ladders = []  # NTRA/AU TARGET->TARGET next
    for sym, trades in by.items():
        for i, r in enumerate(trades):
            et = str(col(r, "EXIT TYPE")).upper()
            if "TARGET" not in et or i + 1 >= len(trades):
                continue
            nxt = trades[i + 1]
            nxt_et = str(col(nxt, "EXIT TYPE")).upper()
            nxt_days = int(fnum(col(nxt, "DAYS HELD"), 0) or 0)
            g = gap_days(col(r, "DATE CLOSED"), col(nxt, "DATE OPENED"))
            item = {
                "sym": sym,
                "gap": g,
                "prior_out": col(r, "DATE CLOSED"),
                "in": col(nxt, "DATE OPENED"),
                "next_et": nxt_et,
                "next_days": nxt_days,
                **feat(nxt),
            }
            if "STOP" in nxt_et and nxt_days <= 10:
                fails.append(item)
            if sym in ("NTRA", "AU") and "TARGET" in nxt_et:
                ladders.append(item)

    def summarize(xs, label):
        print(f"\n=== {label} n={len(xs)} ===")
        for key in ("gap", "slope", "g20_50", "g50_100", "g100_200", "dip", "hist_hi", "cth"):
            vals = sorted(v[key] for v in xs if v.get(key) is not None)
            if not vals:
                print(f"  {key}: n/a")
                continue
            print(
                f"  {key}: min={vals[0]:.4f} p25={vals[len(vals)//4]:.4f} "
                f"med={vals[len(vals)//2]:.4f} p75={vals[3*len(vals)//4]:.4f} max={vals[-1]:.4f}"
            )

    summarize(fails, "post_target_quick_stop re-entry bars")
    summarize(ladders, "NTRA/AU TARGET->TARGET ladder re-entries")

    print("\n=== NTRA/AU ladder re-entry detail ===")
    for x in sorted(ladders, key=lambda t: (t["sym"], t["in"])):
        print(
            f"  {x['sym']} IN={x['in']} gap={x['gap']}d slope={x['slope']} "
            f"g20_50={None if x['g20_50'] is None else round(x['g20_50'],4)} "
            f"dip={None if x['dip'] is None else round(x['dip'],4)} hist_hi={x['hist_hi']}"
        )

    print("\n=== fail detail (gap<=30, quality) ===")
    for x in sorted([f for f in fails if f["gap"] <= 30], key=lambda t: t["gap"]):
        print(
            f"  {x['sym']} IN={x['in']} gap={x['gap']}d slope={x['slope']} "
            f"g20_50={None if x['g20_50'] is None else round(x['g20_50'],4)} "
            f"dip={None if x['dip'] is None else round(x['dip'],4)} hist_hi={x['hist_hi']}"
        )

    # hypothetical cut_the_losers thresholds: need prior high extension
    # hist_hi may be peak above SMA as fraction?
    print("\n=== hist_hi distribution note (cut proxy) ===")
    for xs, label in ((fails, "fails"), (ladders, "ladders")):
        vals = [v["hist_hi"] for v in xs if v["hist_hi"] is not None]
        if vals:
            print(f"  {label} hist_hi med={median(vals):.4f} min={min(vals):.4f} max={max(vals):.4f}")


if __name__ == "__main__":
    main()
