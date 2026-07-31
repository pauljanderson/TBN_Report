"""Separability: cut_the_losers / slope / stack-gap vs NTRA-AU ladders."""
from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

closed = list(csv.DictReader(open("drive/RL_Closed_260730094107.csv", encoding="utf-8-sig")))
by: dict[str, list] = defaultdict(list)
for r in closed:
    by[r["SYMBOL"].strip().upper()].append(r)
for sym in by:
    by[sym].sort(key=lambda r: (r["DATE OPENED"], r["DATE CLOSED"]))


def ymd(s: str) -> str:
    return s.replace("-", "")[:8]


fails = []
ladders = []
for sym, trades in by.items():
    for i, r in enumerate(trades):
        if "TARGET" not in r["EXIT TYPE"].upper() or i + 1 >= len(trades):
            continue
        nxt = trades[i + 1]
        nxt_et = nxt["EXIT TYPE"].upper()
        nxt_days = int(float(nxt["DAYS HELD"] or 0))
        g = (
            datetime.strptime(ymd(nxt["DATE OPENED"]), "%Y%m%d")
            - datetime.strptime(ymd(r["DATE CLOSED"]), "%Y%m%d")
        ).days
        item = (sym, nxt["DATE OPENED"], g, nxt_et, nxt_days)
        if "STOP" in nxt_et and nxt_days <= 10:
            fails.append(item)
        if sym in ("NTRA", "AU") and "TARGET" in nxt_et:
            ladders.append(item)


def load(sym: str):
    p = Path(f"data/newdata/data/{sym}.csv")
    rows = list(csv.reader(p.open(encoding="utf-8-sig", errors="ignore")))
    start = 1 if any(x.lower() in ("date", "close") for x in rows[0]) else 0
    dates, o, h, l, c = [], [], [], [], []
    for row in rows[start:]:
        if len(row) < 5:
            continue
        d = row[0].replace("-", "")[:8]
        if not (d.isdigit() and len(d) == 8):
            continue
        try:
            oo, hh, ll, cc = map(float, row[1:5])
        except Exception:
            continue
        dates.append(d)
        o.append(oo)
        h.append(hh)
        l.append(ll)
        c.append(cc)
    return dates, np.array(o), np.array(h), np.array(l), np.array(c)


def s_n(c, j, n):
    if j < n - 1:
        return None
    return float(c[j - n + 1 : j + 1].mean())


def metrics(sym: str, entry_ymd: str):
    dates, o, h, l, c = load(sym)
    ey = entry_ymd.replace("-", "")[:8]
    try:
        i = dates.index(ey)
    except ValueError:
        return None
    sig = i - 1
    if sig < 80:
        return None
    y_sma = s_n(c, sig - 1, 50)
    if not y_sma:
        return None
    cut = (h[sig - 1] - y_sma) / y_sma
    s_now = s_n(c, sig, 50)
    s_old = s_n(c, sig - 30, 50)
    slope = (s_now / s_old) - 1 if s_now and s_old else None
    g2050 = (s_n(c, sig, 20) / s_n(c, sig, 50) - 1) if s_n(c, sig, 20) and s_n(c, sig, 50) else None
    dip_pos = (l[sig] / y_sma - 1) if y_sma else None
    return {"cut": cut, "slope": slope, "g2050": g2050, "dip_pos": dip_pos}


def collect(items):
    rows = []
    for sym, od, g, et, hd in items:
        m = metrics(sym, od)
        if not m:
            continue
        rows.append({**m, "sym": sym, "od": od, "gap": g})
    return rows


fr = collect(fails)
lr = collect(ladders)


def summarize(rows, label):
    print(f"\n{label} n={len(rows)}")
    for key in ("cut", "slope", "g2050", "dip_pos"):
        vals = sorted(r[key] for r in rows if r[key] is not None)
        print(
            f"  {key}: min={vals[0]:.4f} p25={vals[len(vals)//4]:.4f} "
            f"med={vals[len(vals)//2]:.4f} p75={vals[3*len(vals)//4]:.4f} max={vals[-1]:.4f}"
        )


summarize(fr, "fails")
summarize(lr, "ladders")

print("\n=== cut_the_losers: require cut < thr (current=0.25) ===")
for thr in [0.35, 0.30, 0.25, 0.20, 0.18, 0.15, 0.12, 0.10]:
    kf = sum(1 for r in fr if r["cut"] >= thr)
    kl = sum(1 for r in lr if r["cut"] >= thr)
    print(f"  thr={thr:.2f} blocks_fails={kf}/{len(fr)} blocks_ladders={kl}/{len(lr)}")

print("\n=== slope: require slope >= thr ===")
for thr in [0.0, 0.05, 0.0643, 0.08, 0.10, 0.12, 0.14, 0.15]:
    kf = sum(1 for r in fr if (r["slope"] or 0) < thr)
    kl = sum(1 for r in lr if (r["slope"] or 0) < thr)
    print(f"  thr={thr:.4f} blocks_fails={kf}/{len(fr)} blocks_ladders={kl}/{len(lr)}")

print("\n=== min g20_50 (future lever) ===")
for thr in [0.02, 0.03, 0.04, 0.05, 0.06, 0.065, 0.07]:
    kf = sum(1 for r in fr if (r["g2050"] or 0) < thr)
    kl = sum(1 for r in lr if (r["g2050"] or 0) < thr)
    print(f"  thr={thr:.3f} blocks_fails={kf}/{len(fr)} blocks_ladders={kl}/{len(lr)}")

print("\nladder detail:")
for r in sorted(lr, key=lambda x: (x["sym"], x["od"])):
    print(
        f"  {r['sym']} {r['od']} cut={r['cut']:.4f} slope={r['slope']:.4f} "
        f"g2050={r['g2050']:.4f} dip_pos={r['dip_pos']:.4f}"
    )

print("\nshort-gap fails:")
for r in sorted([x for x in fr if x["gap"] <= 30], key=lambda x: x["gap"]):
    print(
        f"  {r['sym']} {r['od']} gap={r['gap']} cut={r['cut']:.4f} slope={r['slope']:.4f} "
        f"g2050={r['g2050']:.4f} dip_pos={r['dip_pos']:.4f}"
    )
