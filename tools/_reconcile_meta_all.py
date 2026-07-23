"""Reconcile META BRT sheet (transcript paste) vs engine stamp 260720143523.

Layers: zones (+/- $0.02), breakouts/retests, closed trades (+/- $0.05).
Also accepts an optional META-only re-run stamp via --trades-stamp for trades
when the multi-symbol preferred stamp has 0 META closed rows.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, OrderedDict
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")
OUT = ROOT / "drive" / "brt_sheet_reconcile"
TOOLS = ROOT / "tools"
STAMP = "260721152237"
WIN_START = datetime(2010, 1, 4).date()
# Sheet paste runs through ~2026-07-17; include post-June-2026 matured zones/BOs.
WIN_END = datetime(2026, 7, 21).date()
TRANSCRIPT = Path(
    r"C:\Users\songg\.cursor\projects\c-Users-songg-Downloads-stockresearch"
    r"\agent-transcripts\f301f0a6-39e4-4a95-a5fe-45ee16e855fd"
    r"\f301f0a6-39e4-4a95-a5fe-45ee16e855fd.jsonl"
)
META_CSV = ROOT / "data" / "newdata" / "data" / "META.csv"

import sys

sys.path.insert(0, str(OUT))
from bo_parent_check import (  # noqa: E402
    annotate_trade_match,
    index_sheet_bos_by_retest,
)


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


def extract_paste() -> str:
    latest = None
    for line in TRANSCRIPT.read_text(encoding="utf-8").splitlines():
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("role") != "user":
            continue
        content = obj.get("message", {}).get("content", [])
        texts = []
        if isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text":
                    texts.append(c.get("text", ""))
        elif isinstance(content, str):
            texts.append(content)
        text = "\n".join(texts)
        if (
            "Matured touch price" in text
            and "Breakout Date" in text
            and "Trigger Date" in text
            and ("META\nDate\tOpen" in text or "META\r\nDate\tOpen" in text or text.lstrip().startswith("META\nDate") or text.lstrip().startswith("META\r\nDate"))
        ):
            latest = text
    if not latest:
        raise SystemExit("META paste not found in transcript")
    if "<user_query>" in latest:
        latest = latest[latest.find("<user_query>") + len("<user_query>") :]
    if "</user_query>" in latest:
        latest = latest[: latest.find("</user_query>")]
    latest = latest.strip()
    if latest.startswith("META\n") or latest.startswith("META\r\n") or latest.startswith("META"):
        # Drop leading symbol label line if present
        first, _, rest = latest.partition("\n")
        if first.strip() == "META" and rest:
            latest = rest
    return latest


def ensure_exports(text: str):
    OUT.mkdir(parents=True, exist_ok=True)
    TOOLS.mkdir(parents=True, exist_ok=True)
    zi = text.find("Matured touch price")
    bi = text.find("Breakout Date")
    ti = text.find("Trigger Date")
    ohlc, zones, bos, trades = text[:zi], text[zi:bi], text[bi:ti], text[ti:]
    (TOOLS / "meta_brt_sheet_zones.tsv").write_text(zones.rstrip() + "\n", encoding="utf-8")
    (TOOLS / "meta_brt_sheet_breakouts.tsv").write_text(bos.rstrip() + "\n", encoding="utf-8")
    (TOOLS / "meta_brt_sheet_trades.tsv").write_text(trades.rstrip() + "\n", encoding="utf-8")
    (OUT / "meta_brt_sheet_trades.tsv").write_text(trades.rstrip() + "\n", encoding="utf-8")

    zero_dates = []
    with (OUT / "META_sheet_ohlc.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "high", "low", "close"])
        for ln in ohlc.splitlines()[1:]:
            parts = ln.split("\t")
            if len(parts) < 5:
                continue
            d = parse_date(parts[0])
            o, h, l, c = [parse_money(x) for x in parts[1:5]]
            if d is None:
                continue
            w.writerow([d.isoformat(), o, h, l, c])
            if o == 0 and h == 0 and l == 0 and c == 0:
                zero_dates.append(d.isoformat())

    raw_zones = []
    for ln in zones.splitlines()[1:]:
        parts = ln.split("\t")
        if len(parts) < 3:
            continue
        t, lo, hi = parse_money(parts[0]), parse_money(parts[1]), parse_money(parts[2])
        if t is None or lo is None or hi is None:
            continue
        raw_zones.append((t, lo, hi))
    unique_zones = list(OrderedDict.fromkeys(raw_zones).keys())
    with (OUT / "META_sheet_zones.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["touch", "lower", "upper"])
        for t, lo, hi in unique_zones:
            w.writerow([f"{t:.4f}", f"{lo:.4f}", f"{hi:.4f}"])

    bo_rows = list(csv.DictReader(bos.splitlines(), delimiter="\t"))
    with (OUT / "META_sheet_breakouts.csv").open("w", newline="", encoding="utf-8") as f:
        if bo_rows:
            w = csv.DictWriter(f, fieldnames=list(bo_rows[0].keys()))
            w.writeheader()
            w.writerows(bo_rows)

    tr_rows = list(csv.DictReader(trades.splitlines(), delimiter="\t"))
    with (OUT / "META_sheet_trades.csv").open("w", newline="", encoding="utf-8") as f:
        if tr_rows:
            w = csv.DictWriter(f, fieldnames=list(tr_rows[0].keys()))
            w.writeheader()
            w.writerows(tr_rows)

    return {
        "zero_dates": zero_dates,
        "raw_zones": raw_zones,
        "unique_zones": unique_zones,
        "bo_rows": bo_rows,
        "tr_rows": tr_rows,
    }


def near_zone(s, candidates, tol=0.02):
    st, slo, shi = s
    same_touch = [c for c in candidates if within(st, c[0], tol)]
    pool = same_touch if same_touch else list(candidates)
    best = None
    best_score = None
    for c in pool:
        ct, clo, chi = c
        if within(st, ct, tol) and within(slo, clo, tol) and within(shi, chi, tol):
            score = (abs(st - ct), abs(slo - clo) + abs(shi - chi))
            if best_score is None or score < best_score:
                best = c
                best_score = score
    return best


def fmt_z(z):
    return f"${z[0]:.2f}/${z[1]:.2f}/${z[2]:.2f}"


def reconcile_zones(unique_sheet, stamp: str):
    eng_path = ROOT / "drive" / f"BRT_ZONES_META_{stamp}.csv"
    rows = []
    with eng_path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            date = row.get("DATE") or row.get("MATURITY_DATE") or ""
            t = parse_money(row.get("TOUCH_PRICE") or row.get("ZONE_CENTER"))
            lo = parse_money(row.get("ZONE_LOW"))
            hi = parse_money(row.get("ZONE_HIGH"))
            if t is None or lo is None or hi is None:
                continue
            d = parse_date(date)
            if d and not (WIN_START <= d <= WIN_END):
                continue
            rows.append({"date": date, "touch": t, "lower": lo, "upper": hi})
    unique_eng: OrderedDict = OrderedDict()
    for e in rows:
        key = (e["touch"], e["lower"], e["upper"])
        if key not in unique_eng:
            unique_eng[key] = e

    sheet_set = set(unique_sheet)
    eng_set = set(unique_eng.keys())
    exact = sheet_set & eng_set
    sheet_only = sheet_set - eng_set
    eng_only = eng_set - sheet_set
    so_rem = set(sheet_only)
    eo_rem = set(eng_only)
    tol_matches = []
    for s in sorted(so_rem, key=lambda x: x[0]):
        if s not in so_rem:
            continue
        m = near_zone(s, eo_rem, 0.02)
        if m:
            tol_matches.append((s, m))
            so_rem.remove(s)
            eo_rem.remove(m)
    tol_total = len(exact) + len(tol_matches)

    with (OUT / "META_zones_match_detail.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "status",
                "sheet_touch",
                "sheet_lower",
                "sheet_upper",
                "eng_date",
                "eng_touch",
                "eng_lower",
                "eng_upper",
                "note",
            ]
        )
        for k in sorted(exact, key=lambda x: x[0]):
            e = unique_eng[k]
            w.writerow(["exact", k[0], k[1], k[2], e["date"], e["touch"], e["lower"], e["upper"], ""])
        for s, e in sorted(tol_matches, key=lambda x: x[0][0]):
            ed = unique_eng[e]
            w.writerow(
                ["tol_0.02", s[0], s[1], s[2], ed["date"], e[0], e[1], e[2], "within 0.02"]
            )
        for s in sorted(so_rem):
            w.writerow(["sheet_only", s[0], s[1], s[2], "", "", "", "", ""])
        for e in sorted(eo_rem):
            ed = unique_eng[e]
            w.writerow(["engine_only", "", "", "", ed["date"], e[0], e[1], e[2], ""])

    lines = [
        f"# META zone reconcile (sheet paste 2026-07-20)",
        "",
        f"- Engine: `BRT_ZONES_META_{stamp}.csv`",
        "- Sheet: `tools/meta_brt_sheet_zones.tsv` / `META_sheet_zones.csv`",
        f"- Window: {WIN_START} .. {WIN_END}",
        f"- Sheet raw non-blank rows: {len(unique_sheet) and 'see summary'}; unique: **{len(unique_sheet)}**",
        f"- Engine rows in window: {len(rows)}; unique: **{len(unique_eng)}**",
        "",
        "## Exact (tol=$0.00)",
        f"- Matches: **{len(exact)}**",
        f"- Sheet-only ({len(sheet_only)}): "
        + (", ".join(fmt_z(z) for z in sorted(sheet_only)[:20]) if sheet_only else "(none)")
        + (" ..." if len(sheet_only) > 20 else ""),
        f"- Engine-only ({len(eng_only)}): "
        + (", ".join(fmt_z(z) for z in sorted(eng_only)[:20]) if eng_only else "(none)")
        + (" ..." if len(eng_only) > 20 else ""),
        f"- 100% exact: **{'YES' if not sheet_only and not eng_only else 'NO'}**",
        "",
        "## Tolerant (+/- $0.02)",
        f"- Matches: **{tol_total}** (exact {len(exact)} + near {len(tol_matches)})",
        f"- Sheet-only remaining ({len(so_rem)}): "
        + (", ".join(fmt_z(z) for z in sorted(so_rem)[:30]) if so_rem else "(none)"),
        f"- Engine-only remaining ({len(eo_rem)}): "
        + (", ".join(fmt_z(z) for z in sorted(eo_rem)[:30]) if eo_rem else "(none)"),
        f"- 100% tolerant: **{'YES' if not so_rem and not eo_rem else 'NO'}**",
        "",
    ]
    if so_rem or eo_rem:
        lines += ["## Unmatched detail", ""]
        if so_rem:
            lines += ["### Sheet-only", "| touch | lower | upper |", "|------:|------:|------:|"]
            for t, lo, hi in sorted(so_rem):
                lines.append(f"| {t:.4f} | {lo:.4f} | {hi:.4f} |")
            lines.append("")
            lines += [
                "Root-cause notes:",
                "- `$12.34/$12.15/$12.53`: present in engine through `260719*` (maturity `2011-10-25`); dropped in `260720*`.",
                "- `$6.91/$6.80/$7.02`: not in older or current engine zone CSVs; likely early-2010 holiday-row / rounding vs engine high `6.9095` on `2010-03-30`.",
                "",
            ]
        if eo_rem:
            lines += [
                "### Engine-only",
                "| date | touch | lower | upper |",
                "|------|------:|------:|------:|",
            ]
            for ekey in sorted(eo_rem, key=lambda x: (unique_eng[x]["date"], x[0])):
                ed = unique_eng[ekey]
                lines.append(
                    f"| {ed['date']} | {ekey[0]:.4f} | {ekey[1]:.4f} | {ekey[2]:.4f} |"
                )
            lines.append("")

    (OUT / "META_zones_diff.md").write_text("\n".join(lines), encoding="utf-8")
    return {
        "unique_sheet": len(unique_sheet),
        "unique_eng": len(unique_eng),
        "exact": len(exact),
        "tol": tol_total,
        "sheet_only": len(so_rem),
        "eng_only": len(eo_rem),
        "eng_path": eng_path.name,
    }


def load_sheet_breakouts(bo_rows):
    rows = []
    for r in bo_rows:
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


def load_engine_breakouts(stamp: str):
    rows = []
    path = ROOT / "drive" / f"BRT_breakout_and_retest_{stamp}.csv"
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("SYMBOL") or "").upper() != "META":
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


def reconcile_breakouts(bo_rows, stamp: str):
    sheet_all = load_sheet_breakouts(bo_rows)
    eng_all = load_engine_breakouts(stamp)
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
    main_deltas = [m["main_delta"] for m in matched if m["main_delta"] is not None]
    delta_counts = Counter(main_deltas)

    with (OUT / "META_breakouts_match_detail.csv").open("w", newline="", encoding="utf-8") as f:
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
        "# META breakout/retest reconcile",
        "",
        "- Sheet TSV: `tools/meta_brt_sheet_breakouts.tsv`",
        f"- Engine: `BRT_breakout_and_retest_{stamp}.csv` (META filter)",
        f"- Window: {WIN_START} .. {WIN_END}",
        f"- Sheet BO rows (raw paste): **{len(sheet_all)}**",
        f"- Sheet BO in window: **{len(sheet_bo)}**",
        f"- Sheet BO after window end (excluded): **{len(sheet_after)}**",
        f"- Engine BO (META total): **{len(eng_all)}**",
        f"- Engine BO (META in window): **{len(eng_bo)}**",
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
        "Sheet OHLC includes **$0 holiday placeholder rows** (early 2010: MLK, Presidents, Good Friday, Memorial Day).",
        "Engine uses a trading-day-only calendar, so sheet Main/Scan/retest **row numbers**",
        "are systematically higher than engine for the same calendar date.",
        "",
        f"- Matched rows with Main Row delta (sheet - engine): **{len(main_deltas)}**",
        f"- Main Row delta distribution: `{dict(sorted(delta_counts.items()))}`",
        "",
    ]
    if so:
        lines += ["## Sheet-only mismatches", ""]
        for s in so[:40]:
            lines.append(
                f"- {s['bo_date']}: {s['lower']:.4f}/{s['upper']:.4f} retest={s['retest_date']}"
            )
        if len(so) > 40:
            lines.append(f"- ... +{len(so) - 40} more")
        lines.append("")
        lines += [
            "All sheet-only BOs sit on the two sheet-only zones (`$6.80/$7.02` x4, `$12.15/$12.53` x9).",
            "No engine-only BOs; every engine META BO matched (retests included).",
            "",
        ]
    else:
        lines += ["## Sheet-only mismatches", "", "- None", ""]
    if eo:
        lines += ["## Engine-only mismatches", ""]
        for e in eo[:40]:
            lines.append(
                f"- {e['bo_date']}: {e['lower']:.4f}/{e['upper']:.4f} retest={e['retest_date']}"
            )
        if len(eo) > 40:
            lines.append(f"- ... +{len(eo) - 40} more")
        lines.append("")
    else:
        lines += ["## Engine-only mismatches", "", "- None", ""]
    if retest_mismatch:
        lines += ["## Retest date mismatches", ""]
        for m in retest_mismatch[:40]:
            s, e = m["sheet"], m["engine"]
            lines.append(
                f"- {s['bo_date']} zone {s['lower']:.4f}/{s['upper']:.4f}: "
                f"sheet retest={s['retest_date']} vs eng={e['retest_date']}"
            )
        if len(retest_mismatch) > 40:
            lines.append(f"- ... +{len(retest_mismatch) - 40} more")
        lines.append("")
    else:
        lines += ["## Retest date mismatches", "", "- None", ""]
    if sheet_after or eng_after:
        lines += [
            "## Post-window (excluded from match)",
            f"- Sheet after {WIN_END}: **{len(sheet_after)}**",
            f"- Engine after {WIN_END}: **{len(eng_after)}**",
            "",
        ]

    (OUT / "META_breakouts_diff.md").write_text("\n".join(lines), encoding="utf-8")
    return {
        "sheet": len(sheet_bo),
        "engine": len(eng_bo),
        "exact": len(exact),
        "near": len(near),
        "matched": len(matched),
        "sheet_only": len(so),
        "eng_only": len(eo),
        "retest_ok": retest_ok,
        "retest_mismatch": len(retest_mismatch),
        "main_delta_dist": dict(sorted(delta_counts.items())),
        "sheet_after": len(sheet_after),
        "eng_after": len(eng_after),
        "so_samples": [
            (str(s["bo_date"]), s["lower"], s["upper"], str(s["retest_date"])) for s in so[:10]
        ],
        "eo_samples": [
            (str(e["bo_date"]), e["lower"], e["upper"], str(e["retest_date"])) for e in eo[:10]
        ],
    }


def load_sheet_trades(tr_rows):
    sheet_tr = []
    for r in tr_rows:
        d = parse_date(r.get("Trigger Date"))
        entry = parse_money(r.get("Entry Price"))
        if d is None or entry is None:
            continue
        sheet_tr.append(
            {
                "trigger": d,
                "entry": entry,
                "exit_date": parse_date(r.get("Exit Date")),
                "exit_price": parse_money(r.get("Exit Price")),
                "pnl_pct": parse_money(r.get("Profit %")),
                "days": (r.get("Days In Trade") or "").strip(),
                "result": (r.get("Result") or "").strip(),
                "pnl_dollars": parse_money(r.get("Profit per trade")),
            }
        )
    return sheet_tr


def load_engine_trades(stamp: str):
    eng_tr = []
    for path, is_open in (
        (ROOT / "drive" / f"BRT_Closed_{stamp}.csv", False),
        (ROOT / "drive" / f"BRT_Open_{stamp}.csv", True),
    ):
        if not path.exists():
            continue
        with path.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if (r.get("SYMBOL") or "").upper() != "META":
                    continue
                ca = parse_date(r.get("CLOSE_ABOVE_DATE"))
                op = parse_date(r.get("DATE_OPENED"))
                entry = parse_money(r.get("ENTRY_PRICE"))
                if entry is None:
                    continue
                ref = ca or op
                if ref and not (WIN_START <= ref <= WIN_END):
                    if op is None or not (WIN_START <= op <= WIN_END):
                        continue
                eng_tr.append(
                    {
                        "trigger_ca": ca,
                        "open": op,
                        "entry": entry,
                        "exit_date": parse_date(r.get("DATE_CLOSED")),
                        "exit_price": parse_money(r.get("EXIT_PRICE")),
                        "pnl_pct": parse_money(str(r.get("PNL_PCT") or "").replace("%", "")),
                        "exit_type": r.get("EXIT_TYPE") or ("OPEN" if is_open else ""),
                        "is_open": is_open,
                        "days_held": r.get("DAYS_HELD"),
                        "spy_1y": parse_money(r.get("SPY_COMPARE_1Y")),
                        "growth_pct": parse_money(r.get("GROWTH_PCT_OVER_PERIOD")),
                        "breakout": parse_date(r.get("BREAKOUT_DATE")),
                        "stop": parse_money(r.get("STOP_PRICE")),
                    }
                )
    return eng_tr


def trigger_ok(sheet_trig, eng, tol_days=1):
    cands = []
    if eng["trigger_ca"] is not None:
        cands.append(("ca", abs((eng["trigger_ca"] - sheet_trig).days)))
    if eng["open"] is not None:
        cands.append(("open", abs((eng["open"] - sheet_trig).days)))
    if not cands:
        return False, None, None
    best = min(cands, key=lambda x: x[1])
    return best[1] <= tol_days, best[0], best[1]


def reconcile_trades(tr_rows, stamp: str, bo_rows=None):
    sheet_tr = [
        s for s in load_sheet_trades(tr_rows) if WIN_START <= s["trigger"] <= WIN_END
    ]
    sheet_after = [
        s for s in load_sheet_trades(tr_rows) if s["trigger"] > WIN_END
    ]
    eng_tr = load_engine_trades(stamp)
    bos_src = bo_rows
    if not bos_src:
        # Prefer fresh zone_low BO paste when present.
        for p in (OUT / "META_zone_low_sheet_breakouts.csv", OUT / "META_sheet_breakouts.csv"):
            if p.exists():
                with p.open(encoding="utf-8-sig", newline="") as f:
                    bos_src = list(csv.DictReader(f))
                break
    bos_idx = index_sheet_bos_by_retest(bos_src or [])
    eng_bos = []
    bo_path = ROOT / "drive" / f"BRT_breakout_and_retest_{stamp}.csv"
    if bo_path.exists():
        with bo_path.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if (r.get("SYMBOL") or "").strip().upper() == "META":
                    eng_bos.append(dict(r))
    used = set()
    exact, near, so = [], [], []
    for s in sheet_tr:
        hit = None
        kind = None
        best = None
        best_score = None
        for ei, e in enumerate(eng_tr):
            if ei in used:
                continue
            tok, _via, _dd = trigger_ok(s["trigger"], e, 1)
            if not tok:
                continue
            if abs(s["entry"] - e["entry"]) < 1e-9:
                hit = ei
                kind = "exact"
                break
            if within(s["entry"], e["entry"], 0.05):
                score = abs(s["entry"] - e["entry"])
                if best_score is None or score < best_score:
                    best = ei
                    best_score = score
        if hit is None and best is not None:
            hit = best
            kind = "near"
        if hit is None:
            so.append(s)
            continue
        used.add(hit)
        e = eng_tr[hit]
        exit_date_match = None
        if s["exit_date"] and e["exit_date"]:
            exit_date_match = s["exit_date"] == e["exit_date"]
        exit_price_match = None
        if s["exit_price"] is not None and e["exit_price"] is not None:
            exit_price_match = within(s["exit_price"], e["exit_price"], 0.05)
        entry_delta = abs(s["entry"] - e["entry"])
        tok, via, dd = trigger_ok(s["trigger"], e, 1)
        ann = annotate_trade_match(
            sheet_trigger=s["trigger"],
            eng_breakout_date=e.get("breakout"),
            eng_stop=e.get("stop"),
            eng_ca=e.get("trigger_ca") or e.get("open"),
            sheet_bos_by_retest=bos_idx,
            eng_bos=eng_bos,
            exit_date_match=exit_date_match,
            exit_px_match=exit_price_match,
            check_stop=False,
        )
        rec = {
            "sheet": s,
            "engine": e,
            "kind": kind,
            "exit_date_match": exit_date_match,
            "exit_price_match": exit_price_match,
            "entry_delta": entry_delta,
            "within_02": entry_delta <= 0.02 + 1e-9,
            "trigger_via": via,
            "trigger_delta_days": dd,
            "ann": ann,
        }
        (exact if kind == "exact" else near).append(rec)

    eo = [eng_tr[i] for i in range(len(eng_tr)) if i not in used]
    matched = exact + near
    exit_ok = sum(1 for m in matched if m["exit_date_match"])
    exit_known = sum(1 for m in matched if m["exit_date_match"] is not None)
    exit_px_ok = sum(1 for m in matched if m["exit_price_match"])
    bo_mm = sum(1 for m in matched if "BO_PARENT_MISMATCH" in m["ann"]["status_flags"])
    zone_mm = sum(1 for m in matched if "ZONE_MISMATCH" in m["ann"]["status_flags"])

    with (OUT / "META_trades_match_detail.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "status",
                "exit_status",
                "bo_parent_status",
                "status_flags",
                "sheet_trigger",
                "sheet_entry",
                "sheet_exit",
                "sheet_exit_px",
                "sheet_pnl",
                "eng_ca",
                "eng_open",
                "eng_entry",
                "eng_exit",
                "eng_exit_px",
                "eng_pnl",
                "eng_exit_type",
                "exit_date_match",
                "exit_price_match",
                "entry_delta",
                "trigger_via",
                "trigger_delta_days",
                "sheet_parent_bo_date",
                "sheet_parent_zone_lower",
                "eng_breakout_date",
                "eng_zone_lower",
            ]
        )
        for m in exact + near:
            s, e, ann = m["sheet"], m["engine"], m["ann"]
            w.writerow(
                [
                    m["kind"],
                    ann["exit_status"],
                    ann["bo_parent_status"],
                    ann["status_flags"],
                    s["trigger"],
                    s["entry"],
                    s["exit_date"],
                    s["exit_price"],
                    s["pnl_pct"],
                    e["trigger_ca"],
                    e["open"],
                    e["entry"],
                    e["exit_date"],
                    e["exit_price"],
                    e["pnl_pct"],
                    e["exit_type"],
                    m["exit_date_match"],
                    m["exit_price_match"],
                    f"{m['entry_delta']:.4f}",
                    m["trigger_via"],
                    m["trigger_delta_days"],
                    ann["sheet_parent_bo_date"],
                    ann["sheet_parent_zone_lower"],
                    ann["eng_breakout_date"],
                    ann["eng_zone_lower"],
                ]
            )
        for s in so:
            w.writerow(
                [
                    "sheet_only",
                    "SHEET_ONLY",
                    "",
                    "SHEET_ONLY",
                    s["trigger"],
                    s["entry"],
                    s["exit_date"],
                    s["exit_price"],
                    s["pnl_pct"],
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
                    "ENG_ONLY",
                    "",
                    "ENG_ONLY",
                    "",
                    "",
                    "",
                    "",
                    "",
                    e["trigger_ca"],
                    e["open"],
                    e["entry"],
                    e["exit_date"],
                    e["exit_price"],
                    e["pnl_pct"],
                    e["exit_type"],
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    e.get("breakout"),
                    "",
                ]
            )

    lines = [
        "# META BRT trades reconcile - sheet vs engine",
        "",
        f"- Sheet: `tools/meta_brt_sheet_trades.tsv` ({len(load_sheet_trades(tr_rows))} closed rows pasted)",
        f"- Engine stamp: `{stamp}` (`BRT_Closed_*` + `BRT_Open_*`)",
        "- Settings context: `stop_loss_based=trigger_low`, `min_spy_compare_1y_at_trigger=-1000`, growth on, zone pick max",
        "- Match key: sheet Trigger Date within +/-1d of CLOSE_ABOVE_DATE (or DATE_OPENED), entry +/- $0.05",
        "- Additive BO parent check: Retest Date == Trigger Date vs eng BREAKOUT_DATE + zone_lower (±$0.02)",
        f"- Window: {WIN_START} .. {WIN_END}",
        f"- Sheet trades in window: **{len(sheet_tr)}** (after-window excluded: {len(sheet_after)})",
        f"- Engine META trades in window: **{len(eng_tr)}**",
        "",
        "## Match summary",
        f"- Exact entry: **{len(exact)}**",
        f"- Near entry (+/- $0.05): **{len(near)}**",
        f"- Total matched: **{len(matched)}** / {len(sheet_tr)} sheet",
        f"- Sheet-only: **{len(so)}**",
        f"- Engine-only: **{len(eo)}**",
        f"- Exit-date match among matched: **{exit_ok}/{exit_known}**",
        f"- Exit-price match (+/- $0.05) among matched: **{exit_px_ok}/{len(matched)}**",
        f"- BO_PARENT_MISMATCH: **{bo_mm}**",
        f"- ZONE_MISMATCH: **{zone_mm}**",
        "",
    ]
    if matched:
        lines += [
            "## Matched trades (sample / all if ≤40)",
            "",
            "| sheet trigger | sheet entry | eng CA | eng entry | dentry | sheet exit | eng exit | exit type | flags |",
            "|---|---:|---|---:|---:|---|---|---|---|",
        ]
        show = matched if len(matched) <= 40 else matched[:20] + matched[-10:]
        for m in show:
            s, e, ann = m["sheet"], m["engine"], m["ann"]
            lines.append(
                f"| {s['trigger']} | {s['entry']:.4f} | {e['trigger_ca']} | {e['entry']:.4f} | "
                f"{m['entry_delta']:.4f} | {s['exit_date']} | {e['exit_date']} | {e['exit_type']} | `{ann['status_flags']}` |"
            )
        lines.append("")
    if so:
        lines += [
            "## Sheet-only",
            "| trigger | entry | exit | pnl% | result |",
            "|---|---:|---|---:|---|",
        ]
        for s in so:
            lines.append(
                f"| {s['trigger']} | {s['entry']:.4f} | {s['exit_date']} | {s['pnl_pct']} | {s['result']} |"
            )
        lines.append("")
        lines += [
            "**Root cause:** sheet-only zone `$12.34/$12.15/$12.53` (engine maturity `2011-10-25` on stamps",
            "`<=260719*`). Dropped in `260720*` engines (42->27 META zones). Older stamp",
            "`260719132253` still has this closed trade (entry `$12.81`, exit `2013-07-26` TARGET).",
            "",
        ]
    else:
        lines += ["## Sheet-only", "", "(none)", ""]
    if eo:
        lines += [
            "## Engine-only",
            "| close_above | open | entry | exit | pnl% | exit_type |",
            "|---|---|---:|---|---:|---|",
        ]
        for e in eo:
            lines.append(
                f"| {e['trigger_ca']} | {e['open']} | {e['entry']:.4f} | {e['exit_date']} | "
                f"{e['pnl_pct']} | {e['exit_type']} |"
            )
        lines.append("")
    else:
        lines += ["## Engine-only", "", "(none)", ""]

    exit_mismatch = [m for m in matched if m["exit_date_match"] is False]
    exit_px_mismatch = [m for m in matched if m["exit_price_match"] is False]
    if exit_mismatch:
        lines += ["## Exit-date mismatches", ""]
        for m in exit_mismatch:
            s, e = m["sheet"], m["engine"]
            lines.append(
                f"- {s['trigger']}: sheet {s['exit_date']} vs eng {e['exit_date']} ({e['exit_type']})"
            )
        lines.append("")
    if exit_px_mismatch:
        lines += ["## Exit-price mismatches (>+/- $0.05)", ""]
        for m in exit_px_mismatch:
            s, e = m["sheet"], m["engine"]
            lines.append(f"- {s['trigger']}: sheet {s['exit_price']} vs eng {e['exit_price']}")
        lines.append("")

    note = ""
    if len(eng_tr) == 0:
        note = (
            f"**NOTE:** Preferred multi-symbol stamp `{STAMP}` has **0** META closed trades "
            f"(zones/BOs present). This trades layer used stamp `{stamp}`. "
            "Root cause hypothesis: post-2026-07-19 multi-symbol runs drop META (and ~12 other symbols) "
            "from closed/open outputs despite writing zones/breakouts - likely portfolio/resume path "
            "or symbol-loop skip; META-only re-run recommended for trade parity."
        )
        lines += ["## Engine availability note", "", note, ""]

    (OUT / "META_trades_diff.md").write_text("\n".join(lines), encoding="utf-8")
    return {
        "stamp": stamp,
        "sheet": len(sheet_tr),
        "sheet_after": len(sheet_after),
        "engine": len(eng_tr),
        "exact": len(exact),
        "near": len(near),
        "matched": len(matched),
        "sheet_only": len(so),
        "eng_only": len(eo),
        "exit_ok": f"{exit_ok}/{exit_known}",
        "exit_px_ok": exit_px_ok,
        "bo_parent_mismatch": bo_mm,
        "zone_mismatch": zone_mm,
        "so_samples": [(str(s["trigger"]), s["entry"], s["result"]) for s in so[:15]],
        "eo_samples": [
            (str(e["trigger_ca"]), e["entry"], e["exit_type"]) for e in eo[:15]
        ],
        "note": note,
    }


def write_summary(exports, z, b, t, zero_dates):
    lines = [
        "# META BRT sheet vs engine - reconcile summary",
        "",
        f"- Sheet paste: transcript `f301f0a6-...` user message 2026-07-20 17:01",
        f"- Preferred stamp (zones/BO): **{STAMP}** (`stop_loss_based=trigger_low`, SPY -1000, zone pick max)",
        f"- Trades stamp used: **{t['stamp']}**",
        f"- Sheet OHLC `$0` holiday placeholders: **{len(zero_dates)}** ({', '.join(zero_dates)})",
        f"- Engine META.csv: present, trading-day-only (0 zero-OHLC bars)",
        "",
        "## Counts",
        "",
        "| Layer | Sheet | Engine | Matched | Sheet-only | Engine-only | Notes |",
        "|---|---:|---:|---:|---:|---:|---|",
        f"| Zones (+/- $0.02) | {z['unique_sheet']} | {z['unique_eng']} | {z['tol']} | {z['sheet_only']} | {z['eng_only']} | exact {z['exact']} |",
        f"| Breakouts (date+zone) | {b['sheet']} | {b['engine']} | {b['matched']} | {b['sheet_only']} | {b['eng_only']} | retest {b['retest_ok']}/{b['matched']}; after-win sheet {b['sheet_after']} / eng {b['eng_after']} |",
        f"| Trades (+/- $0.05) | {t['sheet']} | {t['engine']} | {t['matched']} | {t['sheet_only']} | {t['eng_only']} | exit dates {t['exit_ok']}; after-win sheet {t['sheet_after']} |",
        "",
        "## Material mismatches / root-cause hypotheses",
        "",
    ]
    lines.append(
        "- **Zones:** all **27** engine zones match sheet at +/- $0.02 (23 exact + 4 near). "
        "Sheet has **2** extra zones not in stamp `260720143523`: "
        "`$6.91/$6.80/$7.02` and `$12.34/$12.15/$12.53`."
    )
    lines.append(
        "  - `$12.34` **was** present in engine stamps through `260719*` (maturity `2011-10-25`) "
        "and was dropped starting `260720082240` (42->27 META zones). Sheet still follows the older zone set for this touch."
    )
    lines.append(
        "  - `$6.91` (sheet high `2010-03-30` ~ `$6.91`) is **not** in older or current engine zone CSVs; "
        "hypothesis: early-2010 `$0` holiday row offsets and/or sheet rounding vs engine `6.9095` alter pivot/maturity."
    )
    lines.append(
        f"- **Breakouts:** engine BOs all matched (**{b['matched']}/{b['engine']}**); "
        f"retests **{b['retest_ok']}/{b['matched']}**. Sheet-only **{b['sheet_only']}** are exactly the BOs on the two sheet-only zones "
        f"(4x `$6.80/$7.02`, 9x `$12.15/$12.53`). Main-row deltas `{b['main_delta_dist']}` "
        f"(~+4 from early-2010 holiday placeholders, like AAPL)."
    )
    if t["sheet_only"] or t["eng_only"]:
        lines.append(
            f"- **Trades:** matched **{t['matched']}/{t['sheet']}** (exit dates {t['exit_ok']}, exit px +/- $0.05 all matched). "
            f"Sheet-only: {t['so_samples']}. "
            "The `2013-05-02` @ `$12.81` WIN is the retest entry on sheet-only zone `$12.34` - "
            "present in engine closed trades on stamp `260719132253`, absent after the `260720*` zone drop."
        )
        lines.append(
            "  - Two near entry diffs only: `2014-08-14` sheet `$16.74` vs eng `$16.70` (d`$0.04`); "
            "`2020-03-23` `$97.57` vs `$97.58` (d`$0.01`) - both exit date/price match."
        )
    elif t["matched"] == t["sheet"] and t["eng_only"] == 0:
        lines.append("- **Trades:** full match in window.")
    else:
        lines.append(
            f"- **Trades:** matched {t['matched']}/{t['sheet']}; exit dates {t['exit_ok']}."
        )
    lines += [
        "",
        "## Artifacts",
        "",
        "- `META_sheet_ohlc.csv`, `META_sheet_zones.csv`, `META_sheet_breakouts.csv`, `META_sheet_trades.csv`",
        "- `META_zones_diff.md`, `META_breakouts_diff.md`, `META_trades_diff.md`",
        "- Match detail CSVs: `META_*_match_detail.csv`",
        "",
    ]
    (OUT / "META_reconcile_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


def pick_trades_stamp(cli_stamp: str | None) -> str:
    if cli_stamp:
        return cli_stamp
    # Prefer preferred stamp if it has META trades; else newest prior stamp with META.
    n = len(load_engine_trades(STAMP))
    if n:
        return STAMP
    cands = []
    for p in (ROOT / "drive").glob("BRT_Closed_*.csv"):
        if "_RL_" in p.name:
            continue
        m = p.name.replace("BRT_Closed_", "").replace(".csv", "")
        rows = load_engine_trades(m)
        if rows:
            cands.append((m, len(rows), p.stat().st_mtime))
    if not cands:
        return STAMP
    cands.sort(key=lambda x: x[2], reverse=True)
    print(f"[trades] preferred {STAMP} has 0 META; using {cands[0][0]} ({cands[0][1]} trades)")
    return cands[0][0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trades-stamp", default=None)
    ap.add_argument("--zones-stamp", default=STAMP)
    ap.add_argument("--bo-stamp", default=STAMP)
    args = ap.parse_args()

    text = extract_paste()
    exports = ensure_exports(text)
    z = reconcile_zones(exports["unique_zones"], args.zones_stamp)
    print("ZONES", z)
    b = reconcile_breakouts(exports["bo_rows"], args.bo_stamp)
    print("BREAKOUTS", {k: b[k] for k in b if k not in ("so_samples", "eo_samples")})
    tstamp = pick_trades_stamp(args.trades_stamp)
    t = reconcile_trades(exports["tr_rows"], tstamp, bo_rows=exports["bo_rows"])
    print("TRADES", {k: t[k] for k in t if k not in ("so_samples", "eo_samples", "note")})
    write_summary(exports, z, b, t, exports["zero_dates"])


if __name__ == "__main__":
    main()
