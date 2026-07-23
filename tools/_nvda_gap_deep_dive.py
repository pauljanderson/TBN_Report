"""One-off NVDA gap deep-dive: OHLC pivots, exit knife, BO clustering."""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")
OUT = ROOT / "drive" / "brt_sheet_reconcile"


def load_ohlc(path: Path, sheet_fmt: bool) -> dict:
    out = {}
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if sheet_fmt:
                d = r["date"]
                out[d] = {k: float(r[k]) for k in ("open", "high", "low", "close")}
            else:
                d = r["Date"][:10]
                out[d] = {
                    "open": round(float(r["Open"]), 4),
                    "high": round(float(r["High"]), 4),
                    "low": round(float(r["Low"]), 4),
                    "close": round(float(r["Close"]), 4),
                }
    return out


def zone_band(touch: float, pct: float = 0.02) -> tuple[float, float, float]:
    lo = round(touch * (1 - pct), 4)
    hi = round(touch * (1 + pct), 4)
    return touch, lo, hi


def sheet_2dec_band(touch_raw: float) -> tuple[float, float, float]:
    """Sheet displays 2-decimal touch; band is touch±2%."""
    touch = round(touch_raw, 2)
    lo = round(touch * 0.98, 2)
    hi = round(touch * 1.02, 2)
    return touch, lo, hi


def main() -> None:
    sheet = load_ohlc(OUT / "NVDA_sheet_ohlc.csv", True)
    eng = load_ohlc(ROOT / "data" / "newdata" / "data" / "NVDA.csv", False)

    print("=" * 80)
    print("1) EARLY ZONE PIVOT EVIDENCE (2010)")
    print("=" * 80)
    # Find local highs in Feb-Mar 2010 on engine precise data
    feb_mar = sorted(d for d in eng if d.startswith("2010-02") or d.startswith("2010-03"))
    for d in feb_mar:
        h = eng[d]["high"]
        sh = sheet.get(d, {}).get("high")
        if h >= 0.44 or (sh and sh >= 0.44):
            eng_band = sheet_2dec_band(h) if False else zone_band(round(h, 2))
            print(
                f"{d}: eng_H={h:.4f} sheet_H={sh} | "
                f"eng 2dec touch={round(h,2)} band {round(round(h,2)*0.98,2)}/{round(round(h,2)*1.02,2)}"
            )

    print("\nPivot maturity 2010-02-26 (engine zone 0.45/0.44/0.46):")
    for d in ["2010-02-19", "2010-02-22", "2010-02-23", "2010-02-24", "2010-02-25", "2010-02-26"]:
        e, s = eng.get(d), sheet.get(d)
        print(f"  {d}: eng={e} sheet={s}")

    print("\nSheet phantom zone 0.42/0.41/0.43 — likely from rounded High 0.42:")
    for d in feb_mar:
        sh = sheet.get(d, {}).get("high")
        if sh and 0.41 <= sh <= 0.43:
            print(f"  {d}: sheet H={sh:.2f}")

    print("\n" + "=" * 80)
    print("2) 2018-02-09 ZONE 6.30 vs 6.23")
    print("=" * 80)
    for d in ["2018-02-05", "2018-02-06", "2018-02-07", "2018-02-08", "2018-02-09", "2018-02-12"]:
        e, s = eng.get(d), sheet.get(d)
        print(f"{d}: eng_H={e['high'] if e else None} sheet_H={s['high'] if s else None}")

    print("\n" + "=" * 80)
    print("3) 2017-12-22 EXIT KNIFE-EDGE")
    print("=" * 80)
    entry = 4.83
    target = round(entry * 1.21, 4)
    print(f"Entry={entry} target=entry*1.21={target}")
    for d in ["2018-01-19", "2018-01-22", "2018-01-23"]:
        e, s = eng.get(d), sheet.get(d)
        if e and s:
            print(
                f"{d}: eng_H={e['high']:.4f} sheet_H={s['high']:.4f} | "
                f"eng hits={e['high'] >= target - 1e-9} sheet hits={s['high'] >= target - 1e-9} | "
                f"delta eng={e['high'] - target:.4f} sheet={s['high'] - target:.4f}"
            )

    print("\n" + "=" * 80)
    print("4) 2025-05-22 DUPLICATE + DOWNSTREAM")
    print("=" * 80)
    for d in ["2025-05-19", "2025-05-20", "2025-05-21", "2025-05-22", "2025-05-23"]:
        e, s = eng.get(d), sheet.get(d)
        print(f"{d}: sheet={s} eng={e}")
    s21, s22 = sheet.get("2025-05-21"), sheet.get("2025-05-22")
    if s21 and s22:
        dup = all(abs(s21[k] - s22[k]) < 0.001 for k in s21)
        print(f"Sheet 5/22 duplicate of 5/21? {dup}")

    # Check if any BO/trade references 2025-05-22
    bo_dates = []
    with (OUT / "NVDA_sheet_breakouts.csv").open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            for col in ("Breakout Date", "Retest Date"):
                v = r.get(col, "")
                if "5/22/2025" in v or "2025-05-22" in v:
                    bo_dates.append((col, r.get("Breakout Date"), r.get("Zone Low"), r.get("Zone High")))
    print(f"BO rows referencing 2025-05-22: {bo_dates or '(none)'}")

    print("\n" + "=" * 80)
    print("5) BO GAP CLUSTERING BY ZONE BAND")
    print("=" * 80)
    sheet_only = []
    eng_only = []
    with (OUT / "NVDA_breakouts_match_detail.csv").open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            st = r.get("status", "")
            if st == "sheet_only":
                sheet_only.append(r)
            elif st == "engine_only":
                eng_only.append(r)

    so_cluster = Counter(f"{r['sheet_lo']}/{r['sheet_hi']}" for r in sheet_only)
    eo_cluster = Counter(f"{r['eng_lo']}/{r['eng_hi']}" for r in eng_only)
    print("Sheet-only by zone band:")
    for b, n in so_cluster.most_common():
        print(f"  {b}: {n}")
    print("Engine-only by zone band:")
    for b, n in eo_cluster.most_common():
        print(f"  {b}: {n}")

    print("\n" + "=" * 80)
    print("6) FULL OHLC MISMATCH SCAN (sheet vs eng, all dates)")
    print("=" * 80)
    mismatches = []
    for d in sorted(set(sheet) & set(eng)):
        s, e = sheet[d], eng[d]
        for field in ("open", "high", "low", "close"):
            if abs(round(s[field], 2) - round(e[field], 2)) > 0.02:
                mismatches.append((d, field, s[field], e[field]))
    print(f"Total field mismatches (>±$0.02 on 2-dec): {len(mismatches)}")
    for m in mismatches[:30]:
        print(f"  {m[0]} {m[1]}: sheet={m[2]} eng={m[3]}")
    if len(mismatches) > 30:
        print(f"  ... and {len(mismatches)-30} more")

    # Write cluster summary for report
    lines = [
        "# NVDA gap cluster analysis (auto-generated)",
        "",
        "## Sheet-only BO by zone",
        "",
    ]
    for b, n in so_cluster.most_common():
        lines.append(f"- `{b}`: **{n}** BOs")
    lines += ["", "## Engine-only BO by zone", ""]
    for b, n in eo_cluster.most_common():
        lines.append(f"- `{b}`: **{n}** BOs")
    lines += ["", "## OHLC mismatches (>±$0.02)", ""]
    for d, field, sv, ev in mismatches:
        lines.append(f"- {d} {field}: sheet={sv} eng={ev}")
    (OUT / "NVDA_gap_cluster_analysis.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {OUT / 'NVDA_gap_cluster_analysis.md'}")


if __name__ == "__main__":
    main()
