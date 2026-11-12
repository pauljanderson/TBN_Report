"""Reconcile AAPL BRT sheet breakouts/retests vs engine dump."""
from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")
OUT = ROOT / "drive" / "brt_sheet_reconcile"
SHEET = ROOT / "tools" / "aapl_brt_sheet_breakouts.tsv"
ENG = ROOT / "drive" / "BRT_breakout_and_retest_260720143523.csv"
# Match TSLA window used in other reconciles; sheet ends 8/7/2025 so all in-window.
WIN_START = datetime(2010, 1, 4).date()
WIN_END = datetime(2026, 6, 5).date()


def parse_date(s):
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y%m%d", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_money(s):
    if s is None:
        return None
    s = str(s).strip().replace("$", "").replace(",", "").replace("%", "")
    if not s:
        return None
    try:
        return round(float(s), 4)
    except ValueError:
        return None


def parse_int(s):
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def within(a, b, tol):
    return a is not None and b is not None and abs(a - b) <= tol + 1e-9


def load_sheet():
    rows = []
    with SHEET.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            d = parse_date(r.get("Breakout Date"))
            lo = parse_money(r.get("Zone Lower"))
            hi = parse_money(r.get("Zone Upper"))
            if d is None or lo is None or hi is None:
                continue
            rows.append(
                {
                    "bo_date": d,
                    "lower": lo,
                    "upper": hi,
                    "main_row": parse_int(r.get("Main Row")),
                    "scan_row": parse_int(r.get("Scan Start Row")),
                    "retest_row": parse_int(r.get("retest Row")),
                    "retest_date": parse_date(r.get("Retest Date")),
                    "retest_hit": (r.get("retest hit") or "").strip(),
                    "too_fast": (r.get("Too fast retest") or "").strip(),
                }
            )
    return rows


def load_engine():
    rows = []
    with ENG.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("SYMBOL") or "").upper() != "AAPL":
                continue
            d = parse_date(r.get("Breakout Date"))
            lo = parse_money(r.get("Zone Lower"))
            hi = parse_money(r.get("Zone Upper"))
            if d is None or lo is None or hi is None:
                continue
            rows.append(
                {
                    "bo_date": d,
                    "lower": lo,
                    "upper": hi,
                    "main_row": parse_int(r.get("Main Row")),
                    "scan_row": parse_int(r.get("Scan Start Row")),
                    "retest_row": parse_int(r.get("retest Row")),
                    "retest_date": parse_date(r.get("Retest Date")),
                }
            )
    return rows


def main():
    sheet_all = load_sheet()
    eng_all = load_engine()
    sheet_bo = [r for r in sheet_all if WIN_START <= r["bo_date"] <= WIN_END]
    sheet_after = [r for r in sheet_all if r["bo_date"] > WIN_END]
    eng_bo = [r for r in eng_all if WIN_START <= r["bo_date"] <= WIN_END]
    eng_after = [r for r in eng_all if r["bo_date"] > WIN_END]

    by_date = {}
    for i, e in enumerate(eng_bo):
        by_date.setdefault(e["bo_date"], []).append(i)

    used = set()
    exact, near, so = [], [], []
    for s in sheet_bo:
        hit = None
        kind = None
        for ei in by_date.get(s["bo_date"], []):
            if ei in used:
                continue
            e = eng_bo[ei]
            if abs(s["lower"] - e["lower"]) < 1e-9 and abs(s["upper"] - e["upper"]) < 1e-9:
                hit = ei
                kind = "exact"
                break
        if hit is None:
            best = None
            best_score = None
            for ei in by_date.get(s["bo_date"], []):
                if ei in used:
                    continue
                e = eng_bo[ei]
                if within(s["lower"], e["lower"], 0.02) and within(s["upper"], e["upper"], 0.02):
                    score = abs(s["lower"] - e["lower"]) + abs(s["upper"] - e["upper"])
                    if best_score is None or score < best_score:
                        best = ei
                        best_score = score
            if best is not None:
                hit = best
                kind = "near"
        if hit is None:
            so.append(s)
            continue
        used.add(hit)
        e = eng_bo[hit]
        main_d = (
            None
            if s["main_row"] is None or e["main_row"] is None
            else s["main_row"] - e["main_row"]
        )
        scan_d = (
            None
            if s["scan_row"] is None or e["scan_row"] is None
            else s["scan_row"] - e["scan_row"]
        )
        retest_row_d = None
        if s["retest_row"] is not None and e["retest_row"] is not None:
            retest_row_d = s["retest_row"] - e["retest_row"]
        rec = {
            "sheet": s,
            "engine": e,
            "kind": kind,
            "retest_match": s["retest_date"] == e["retest_date"],
            "main_delta": main_d,
            "scan_delta": scan_d,
            "retest_row_delta": retest_row_d,
        }
        (exact if kind == "exact" else near).append(rec)

    eo = [eng_bo[i] for i in range(len(eng_bo)) if i not in used]
    matched = exact + near
    retest_ok = sum(1 for m in matched if m["retest_match"])
    retest_mismatch = [m for m in matched if not m["retest_match"]]

    # Row-index analysis (holiday $0 rows inflate sheet row numbers)
    main_deltas = [m["main_delta"] for m in matched if m["main_delta"] is not None]
    delta_counts = Counter(main_deltas)
    retest_row_deltas = [
        m["retest_row_delta"] for m in matched if m["retest_row_delta"] is not None
    ]
    retest_row_counts = Counter(retest_row_deltas)

    detail = OUT / "AAPL_breakout_match_detail.csv"
    with detail.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "status",
                "sheet_bo_date",
                "sheet_lo",
                "sheet_hi",
                "sheet_main",
                "sheet_scan",
                "sheet_retest_row",
                "sheet_retest",
                "eng_bo_date",
                "eng_lo",
                "eng_hi",
                "eng_main",
                "eng_scan",
                "eng_retest_row",
                "eng_retest",
                "retest_match",
                "main_delta",
                "scan_delta",
                "retest_row_delta",
            ]
        )
        for m in exact + near:
            s, e = m["sheet"], m["engine"]
            w.writerow(
                [
                    m["kind"],
                    s["bo_date"],
                    s["lower"],
                    s["upper"],
                    s["main_row"],
                    s["scan_row"],
                    s["retest_row"],
                    s["retest_date"],
                    e["bo_date"],
                    e["lower"],
                    e["upper"],
                    e["main_row"],
                    e["scan_row"],
                    e["retest_row"],
                    e["retest_date"],
                    m["retest_match"],
                    m["main_delta"],
                    m["scan_delta"],
                    m["retest_row_delta"],
                ]
            )
        for s in so:
            w.writerow(
                [
                    "sheet_only",
                    s["bo_date"],
                    s["lower"],
                    s["upper"],
                    s["main_row"],
                    s["scan_row"],
                    s["retest_row"],
                    s["retest_date"],
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                ]
            )
        for e in eo:
            w.writerow(
                [
                    "engine_only",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    e["bo_date"],
                    e["lower"],
                    e["upper"],
                    e["main_row"],
                    e["scan_row"],
                    e["retest_row"],
                    e["retest_date"],
                    "",
                    "",
                    "",
                    "",
                ]
            )

    pct = 100.0 * len(matched) / max(1, len(sheet_bo))
    lines = [
        "# AAPL breakout/retest reconcile",
        "",
        f"- Sheet TSV: `tools/aapl_brt_sheet_breakouts.tsv`",
        f"- Engine: `{ENG.name}` (AAPL filter)",
        f"- Window: {WIN_START} .. {WIN_END}",
        f"- Sheet BO rows (raw paste): **{len(sheet_all)}**",
        f"- Sheet BO in window: **{len(sheet_bo)}**",
        f"- Sheet BO after window end (excluded): **{len(sheet_after)}**",
        f"- Engine BO (AAPL total): **{len(eng_all)}**",
        f"- Engine BO (AAPL in window): **{len(eng_bo)}**",
        f"- Engine BO after window end: **{len(eng_after)}**",
        "",
        "## Match summary (windowed)",
        f"- Exact date+bounds: **{len(exact)}**",
        f"- Near (+/- $0.02 bounds): **{len(near)}**",
        f"- Total matched (date+zone): **{len(matched)}** / {len(sheet_bo)} sheet ({pct:.1f}%)",
        f"- Sheet-only: **{len(so)}**",
        f"- Engine-only: **{len(eo)}**",
        f"- Retest date match among matched: **{retest_ok}/{len(matched)}**"
        + (f" ({100.0 * retest_ok / max(1, len(matched)):.1f}%)" if matched else ""),
        f"- 100% windowed date+zone match: **{'YES' if not so and not eo and len(matched) == len(sheet_bo) else 'NO'}**",
        "",
        "## Row-index / holiday calendar note",
        "",
        "Sheet OHLC includes **$0 holiday placeholder rows** (e.g. 1/18/2010, 2/15/2010).",
        "Engine uses a trading-day-only calendar, so sheet Main/Scan/retest **row numbers**",
        "are systematically higher than engine for the same calendar date.",
        "",
        "This does **not** affect breakout/retest **date** or **zone bound** matching;",
        "it only shifts Excel row indices used by sheet formulas.",
        "",
        f"- Matched rows with Main Row delta (sheet − engine): **{len(main_deltas)}**",
        f"- Main Row delta distribution: `{dict(sorted(delta_counts.items()))}`",
        f"- Retest Row delta distribution (when both present): `{dict(sorted(retest_row_counts.items()))}`",
        "",
    ]
    if main_deltas:
        # show a few early/late examples
        samples = matched[:3] + matched[-3:]
        lines += [
            "### Sample Main Row offsets (sheet − engine)",
            "| bo_date | sheet Main | eng Main | delta |",
            "|---|---:|---:|---:|",
        ]
        seen = set()
        for m in samples:
            s, e = m["sheet"], m["engine"]
            key = s["bo_date"]
            if key in seen:
                continue
            seen.add(key)
            lines.append(
                f"| {s['bo_date']} | {s['main_row']} | {e['main_row']} | {m['main_delta']} |"
            )
        lines.append("")

    lines += ["## Sheet-only mismatches", ""]
    if so:
        for s in so:
            lines.append(
                f"- {s['bo_date']}: {s['lower']:.4f}/{s['upper']:.4f} retest={s['retest_date']}"
            )
    else:
        lines.append("- None")
    lines += ["", "## Engine-only mismatches", ""]
    if eo:
        for e in eo:
            lines.append(
                f"- {e['bo_date']}: {e['lower']:.4f}/{e['upper']:.4f} retest={e['retest_date']}"
            )
    else:
        lines.append("- None")
    lines += ["", "## Retest date mismatches", ""]
    if retest_mismatch:
        for m in retest_mismatch:
            s, e = m["sheet"], m["engine"]
            lines.append(
                f"- {s['bo_date']} zone {s['lower']:.4f}/{s['upper']:.4f}: "
                f"sheet retest={s['retest_date']} vs eng={e['retest_date']}"
            )
    else:
        lines.append("- None")
    if near:
        lines += ["", "## Near-miss pairs (+/- $0.02)"]
        for m in near:
            s, e = m["sheet"], m["engine"]
            lines.append(
                f"- {s['bo_date']}: sheet {s['lower']:.4f}/{s['upper']:.4f} "
                f"<-> eng {e['lower']:.4f}/{e['upper']:.4f}"
            )
    if sheet_after:
        lines += [
            "",
            "## Post-window sheet BOs (excluded)",
            "| bo_date | lower | upper | retest |",
            "|---|---:|---:|---|",
        ]
        for s in sheet_after:
            lines.append(
                f"| {s['bo_date']} | {s['lower']:.4f} | {s['upper']:.4f} | {s['retest_date']} |"
            )
    if eng_after:
        lines += [
            "",
            "## Post-window engine BOs (excluded from windowed match)",
            "| bo_date | lower | upper | retest |",
            "|---|---:|---:|---|",
        ]
        for e in eng_after:
            lines.append(
                f"| {e['bo_date']} | {e['lower']:.4f} | {e['upper']:.4f} | {e['retest_date']} |"
            )
    lines.append("")
    out_md = OUT / "AAPL_breakouts_diff.md"
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(
        f"sheet={len(sheet_all)} windowed={len(sheet_bo)} eng={len(eng_bo)} "
        f"exact={len(exact)} near={len(near)} matched={len(matched)} "
        f"sheet_only={len(so)} engine_only={len(eo)} retest_ok={retest_ok} "
        f"main_delta_dist={dict(sorted(delta_counts.items()))}"
    )
    print(f"wrote {out_md}")
    print(f"wrote {detail}")


if __name__ == "__main__":
    main()
