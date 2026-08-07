"""One-off WPBR Mag9 reconcile-gate diagnosis. Real artifacts only."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools"))
from reconcile_gate import _load_closed_csv  # noqa: E402

drive = ROOT / "drive"
base = _load_closed_csv(drive / "WPBR_Closed_260722174041.csv")
lat = _load_closed_csv(drive / "WPBR_LatestRun_Closed.csv")

MAG9 = ["AAPL", "AMZN", "AU", "META", "MSFT", "NVDA", "NFLX", "GOOGL", "TSLA"]
FAIL = {
    "AAPL": ("2016-09-13", "2017-02-07"),
    "META": ("2016-08-02", "2017-04-28"),
    "MSFT": ("2016-11-16", "2017-06-05"),
    "GOOGL": ("2017-02-08", "2017-10-13"),
    "TSLA": ("2017-05-08", "2017-06-14"),
}


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


print("=== STAMPS / LatestRun identity ===")
lat_path = drive / "WPBR_LatestRun_Closed.csv"
print(f"LatestRun: {lat_path} size={lat_path.stat().st_size} mtime={lat_path.stat().st_mtime}")
lat_md5 = md5(lat_path)
print(f"LatestRun md5={lat_md5}")
stamps = sorted(drive.glob("WPBR_Closed_*.csv"))
matched = []
for p in stamps:
    h = md5(p)
    if h == lat_md5:
        matched.append(p.name)
    print(f"  {p.name} size={p.stat().st_size} md5_match={h == lat_md5}")
print("LatestRun matches:", matched or "(no stamped twin)")

print("\n=== BASELINE vs LATEST symbol counts ===")
for sym in sorted({r["SYMBOL"] for r in base} | {r["SYMBOL"] for r in lat}):
    bn = sum(1 for r in base if r["SYMBOL"] == sym)
    ln = sum(1 for r in lat if r["SYMBOL"] == sym)
    flag = "MAG9" if sym in MAG9 else "AMD-out"
    print(f"  {sym:5s} base={bn:3d} latest={ln:3d}  [{flag}]")


def overlaps(a0, a1, b0, b1):
    return a0 <= b1 and b0 <= a1


print("\n=== FAIL tickers: missing + overlapping replacements ===")
for sym, (mo, mc) in FAIL.items():
    br = next(r for r in base if r["SYMBOL"] == sym and r["DATE_OPENED"] == mo and r["DATE_CLOSED"] == mc)
    bkeys = {(r["DATE_OPENED"], r["DATE_CLOSED"]) for r in base if r["SYMBOL"] == sym}
    lkeys = {(r["DATE_OPENED"], r["DATE_CLOSED"]) for r in lat if r["SYMBOL"] == sym}
    new = sorted(lkeys - bkeys)
    print(f"\n{sym} DIFF=missing_baseline (not price-changed)")
    print(
        f"  miss {mo}->{mc} entry={br['ENTRY_PRICE']} exit={br['EXIT_PRICE']} "
        f"pnl={br['PNL_PCT']} {br['EXIT_TYPE']}"
    )
    print(f"  counts base={len(bkeys)} latest={len(lkeys)} shared={len(bkeys & lkeys)} "
          f"miss={len(bkeys - lkeys)} new_only={len(new)}")
    hits = []
    for no, nc in new:
        if overlaps(mo, mc, no, nc):
            lr = next(
                r
                for r in lat
                if r["SYMBOL"] == sym and r["DATE_OPENED"] == no and r["DATE_CLOSED"] == nc
            )
            hits.append(lr)
            print(
                f"  REPLACEMENT overlap {no}->{nc} entry={lr['ENTRY_PRICE']} "
                f"exit={lr['EXIT_PRICE']} pnl={lr['PNL_PCT']} {lr['EXIT_TYPE']} "
                f"(opens {'BEFORE' if no < mo else 'ON/AFTER'} baseline open)"
            )
    if not hits:
        print("  (no overlapping new_only trade)")

print("\n=== Counterfactual: filter latest DATE_OPENED >= 2016-01-01 ===")
lat2016 = [r for r in lat if (r["DATE_OPENED"] or "") >= "2016-01-01"]
for sym in MAG9:
    bkeys = {(r["DATE_OPENED"], r["DATE_CLOSED"]) for r in base if r["SYMBOL"] == sym}
    lkeys = {(r["DATE_OPENED"], r["DATE_CLOSED"]) for r in lat2016 if r["SYMBOL"] == sym}
    miss = sorted(bkeys - lkeys)
    new = sorted(lkeys - bkeys)
    status = "OK" if not miss else "FAIL"
    print(f"  {sym:5s} {status} miss={len(miss)} new={len(new)} "
          f"miss_keys={miss[:3]}")

print("\n=== Pre-2016 new_only on FAIL tickers (start_date drift signal) ===")
for sym in FAIL:
    bkeys = {(r["DATE_OPENED"], r["DATE_CLOSED"]) for r in base if r["SYMBOL"] == sym}
    lrows = [r for r in lat if r["SYMBOL"] == sym]
    pre = [
        r
        for r in lrows
        if (r["DATE_OPENED"], r["DATE_CLOSED"]) not in bkeys
        and (r["DATE_OPENED"] or "") < "2016-01-01"
    ]
    print(f"  {sym}: pre-2016 new_only={len(pre)}")
    for r in pre[:8]:
        print(f"    {r['DATE_OPENED']}->{r['DATE_CLOSED']}")
