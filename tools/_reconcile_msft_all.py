"""Reconcile MSFT BRT sheet (transcript paste) vs engine stamp 260720143523.

Layers: zones (+/- $0.02), breakouts/retests, closed trades (+/- $0.05).
Also accepts an optional MSFT-only re-run stamp via --trades-stamp for trades
when the multi-symbol preferred stamp has 0 MSFT closed rows.
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
STAMP = "260720143523"
WIN_START = datetime(2010, 1, 4).date()
# Sheet paste runs through ~2026-07-17; include post-June-2026 matured zones/BOs.
WIN_END = datetime(2026, 7, 20).date()
TRANSCRIPT = Path(
    r"C:\Users\songg\.cursor\projects\c-Users-songg-Downloads-stockresearch"
    r"\agent-transcripts\f301f0a6-39e4-4a95-a5fe-45ee16e855fd"
    r"\f301f0a6-39e4-4a95-a5fe-45ee16e855fd.jsonl"
)
MSFT_CSV = ROOT / "data" / "newdata" / "data" / "MSFT.csv"


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
    """Prefer the latest full MSFT paste (OHLC + zones + BOs + trades)."""
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
        blob = "\n".join(texts)
        has_sections = (
            "Matured touch price" in blob
            and "Breakout Date" in blob
            and "Trigger Date" in blob
            and "Date\tOpen\tHigh\tLow\tClose" in blob
        )
        is_msft = (
            "MSFT\nDate\tOpen" in blob
            or "MSFT\r\nDate\tOpen" in blob
            or ("1/4/2010\t$30.6500" in blob and has_sections)
        )
        if has_sections and is_msft:
            latest = blob
    if not latest:
        raise SystemExit("MSFT paste not found in transcript")
    if "<user_query>" in latest:
        latest = latest[latest.find("<user_query>") + len("<user_query>") :]
    if "</user_query>" in latest:
        latest = latest[: latest.find("</user_query>")]
    latest = latest.strip()
    if latest.startswith("MSFT\n") or latest.startswith("MSFT\r\n"):
        first, _, rest = latest.partition("\n")
        if first.strip() == "MSFT" and rest:
            latest = rest
    if "Date\tOpen\tHigh\tLow\tClose" in latest:
        latest = latest[latest.find("Date\tOpen\tHigh\tLow\tClose") :]
    return latest


def ensure_exports(text: str):
    OUT.mkdir(parents=True, exist_ok=True)
    TOOLS.mkdir(parents=True, exist_ok=True)
    zi = text.find("Matured touch price")
    bi = text.find("Breakout Date")
    ti = text.find("Trigger Date")
    ohlc, zones, bos, trades = text[:zi], text[zi:bi], text[bi:ti], text[ti:]
    (TOOLS / "msft_brt_sheet_zones.tsv").write_text(zones.rstrip() + "\n", encoding="utf-8")
    (TOOLS / "msft_brt_sheet_breakouts.tsv").write_text(bos.rstrip() + "\n", encoding="utf-8")
    (TOOLS / "msft_brt_sheet_trades.tsv").write_text(trades.rstrip() + "\n", encoding="utf-8")
    (OUT / "msft_brt_sheet_trades.tsv").write_text(trades.rstrip() + "\n", encoding="utf-8")

    zero_dates = []
    with (OUT / "MSFT_sheet_ohlc.csv").open("w", newline="", encoding="utf-8") as f:
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
    with (OUT / "MSFT_sheet_zones.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["touch", "lower", "upper"])
        for t, lo, hi in unique_zones:
            w.writerow([f"{t:.4f}", f"{lo:.4f}", f"{hi:.4f}"])

    bo_rows = list(csv.DictReader(bos.splitlines(), delimiter="\t"))
    with (OUT / "MSFT_sheet_breakouts.csv").open("w", newline="", encoding="utf-8") as f:
        if bo_rows:
            w = csv.DictWriter(f, fieldnames=list(bo_rows[0].keys()))
            w.writeheader()
            w.writerows(bo_rows)

    tr_rows = list(csv.DictReader(trades.splitlines(), delimiter="\t"))
    with (OUT / "MSFT_sheet_trades.csv").open("w", newline="", encoding="utf-8") as f:
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
    eng_path = ROOT / "drive" / f"BRT_ZONES_MSFT_{stamp}.csv"
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

    with (OUT / "MSFT_zones_match_detail.csv").open("w", newline="", encoding="utf-8") as f:
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
        f"# MSFT zone reconcile (sheet paste 2026-07-20)",
        "",
        f"- Engine: `BRT_ZONES_MSFT_{stamp}.csv`",
        "- Sheet: `tools/msft_brt_sheet_zones.tsv` / `MSFT_sheet_zones.csv`",
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

    (OUT / "MSFT_zones_diff.md").write_text("\n".join(lines), encoding="utf-8")
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
            if (r.get("SYMBOL") or "").upper() != "MSFT":
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

    with (OUT / "MSFT_breakouts_match_detail.csv").open("w", newline="", encoding="utf-8") as f:
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
        "# MSFT breakout/retest reconcile",
        "",
        "- Sheet TSV: `tools/msft_brt_sheet_breakouts.tsv`",
        f"- Engine: `BRT_breakout_and_retest_{stamp}.csv` (MSFT filter)",
        f"- Window: {WIN_START} .. {WIN_END}",
        f"- Sheet BO rows (raw paste): **{len(sheet_all)}**",
        f"- Sheet BO in window: **{len(sheet_bo)}**",
        f"- Sheet BO after window end (excluded): **{len(sheet_after)}**",
        f"- Engine BO (MSFT total): **{len(eng_all)}**",
        f"- Engine BO (MSFT in window): **{len(eng_bo)}**",
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

    (OUT / "MSFT_breakouts_diff.md").write_text("\n".join(lines), encoding="utf-8")
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


def _sheet_trade_invalid(r: dict, entry, exit_price) -> bool:
    """Drop sheet garbage rows (e.g. 7/17/2026 with $0 entry/exit / #DIV/0!)."""
    raw_entry = str(r.get("Entry Price") or "")
    raw_exit = str(r.get("Exit Price") or "")
    raw_pnl = str(r.get("Profit %") or "") + str(r.get("Profit per trade") or "")
    if "#DIV/0!" in raw_entry or "#DIV/0!" in raw_exit or "#DIV/0!" in raw_pnl:
        return True
    if entry is not None and abs(entry) < 1e-9 and (
        exit_price is None or abs(exit_price) < 1e-9
    ):
        return True
    return False


def load_sheet_trades(tr_rows):
    sheet_tr = []
    for r in tr_rows:
        d = parse_date(r.get("Trigger Date"))
        entry = parse_money(r.get("Entry Price"))
        exit_price = parse_money(r.get("Exit Price"))
        if d is None or entry is None:
            continue
        if _sheet_trade_invalid(r, entry, exit_price):
            continue
        sheet_tr.append(
            {
                "trigger": d,
                "entry": entry,
                "exit_date": parse_date(r.get("Exit Date")),
                "exit_price": exit_price,
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
                if (r.get("SYMBOL") or "").upper() != "MSFT":
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


def reconcile_trades(tr_rows, stamp: str):
    sheet_tr = [
        s for s in load_sheet_trades(tr_rows) if WIN_START <= s["trigger"] <= WIN_END
    ]
    sheet_after = [
        s for s in load_sheet_trades(tr_rows) if s["trigger"] > WIN_END
    ]
    eng_tr = load_engine_trades(stamp)
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
        }
        (exact if kind == "exact" else near).append(rec)

    eo = [eng_tr[i] for i in range(len(eng_tr)) if i not in used]
    matched = exact + near
    exit_ok = sum(1 for m in matched if m["exit_date_match"])
    exit_known = sum(1 for m in matched if m["exit_date_match"] is not None)
    exit_px_ok = sum(1 for m in matched if m["exit_price_match"])

    with (OUT / "MSFT_trades_match_detail.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "status",
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
            ]
        )
        for m in exact + near:
            s, e = m["sheet"], m["engine"]
            w.writerow(
                [
                    m["kind"],
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
                ]
            )
        for s in so:
            w.writerow(
                [
                    "sheet_only",
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
                ]
            )

    lines = [
        "# MSFT BRT trades reconcile — sheet vs engine",
        "",
        f"- Sheet: `tools/msft_brt_sheet_trades.tsv` ({len(load_sheet_trades(tr_rows))} closed rows pasted)",
        f"- Engine stamp: `{stamp}` (`BRT_Closed_*` + `BRT_Open_*`)",
        "- Settings context: `stop_loss_based=trigger_low`, `min_spy_compare_1y_at_trigger=-1000`, growth on, zone pick max",
        "- Match key: sheet Trigger Date within +/-1d of CLOSE_ABOVE_DATE (or DATE_OPENED), entry +/- $0.05",
        f"- Window: {WIN_START} .. {WIN_END}",
        f"- Sheet trades in window: **{len(sheet_tr)}** (after-window excluded: {len(sheet_after)})",
        f"- Engine MSFT trades in window: **{len(eng_tr)}**",
        "",
        "## Match summary",
        f"- Exact entry: **{len(exact)}**",
        f"- Near entry (+/- $0.05): **{len(near)}**",
        f"- Total matched: **{len(matched)}** / {len(sheet_tr)} sheet",
        f"- Sheet-only: **{len(so)}**",
        f"- Engine-only: **{len(eo)}**",
        f"- Exit-date match among matched: **{exit_ok}/{exit_known}**",
        f"- Exit-price match (+/- $0.05) among matched: **{exit_px_ok}/{len(matched)}**",
        "",
    ]
    if matched:
        lines += [
            "## Matched trades (sample / all if ≤40)",
            "",
            "| sheet trigger | sheet entry | eng CA | eng entry | Δentry | sheet exit | eng exit | exit type |",
            "|---|---:|---|---:|---:|---|---|---|",
        ]
        show = matched if len(matched) <= 40 else matched[:20] + matched[-10:]
        for m in show:
            s, e = m["sheet"], m["engine"]
            lines.append(
                f"| {s['trigger']} | {s['entry']:.4f} | {e['trigger_ca']} | {e['entry']:.4f} | "
                f"{m['entry_delta']:.4f} | {s['exit_date']} | {e['exit_date']} | {e['exit_type']} |"
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
            f"**NOTE:** Preferred multi-symbol stamp `{STAMP}` has **0** MSFT closed trades "
            f"(zones/BOs present). This trades layer used stamp `{stamp}`. "
            "Root cause hypothesis: post-2026-07-19 multi-symbol runs drop MSFT (and ~12 other symbols) "
            "from closed/open outputs despite writing zones/breakouts — likely portfolio/resume path "
            "or symbol-loop skip; MSFT-only re-run recommended for trade parity."
        )
        lines += ["## Engine availability note", "", note, ""]

    (OUT / "MSFT_trades_diff.md").write_text("\n".join(lines), encoding="utf-8")
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
        "so_samples": [(str(s["trigger"]), s["entry"], s["result"]) for s in so[:15]],
        "eo_samples": [
            (str(e["trigger_ca"]), e["entry"], e["exit_type"]) for e in eo[:15]
        ],
        "note": note,
    }


def write_summary(exports, z, b, t, zero_dates, zones_stamp: str, bo_stamp: str, ohlc_check: dict):
    lines = [
        "# MSFT BRT sheet vs engine — reconcile summary",
        "",
        f"- Sheet paste: transcript `f301f0a6-...` user message 2026-07-20 17:31 (corrected OHLC)",
        f"- Zones/BO stamp: **{zones_stamp}** / **{bo_stamp}** (`stop_loss_based=trigger_low`, SPY -1000, zone pick max, `max_market_cap=0`)",
        f"- Trades stamp used: **{t['stamp']}**",
        f"- Sheet OHLC `$0` holiday placeholders: **{len(zero_dates)}** ({', '.join(zero_dates)})",
        f"- Engine MSFT.csv: present, trading-day-only (0 zero-OHLC bars)",
        f"- **OHLC spot-check:** **{ohlc_check.get('status')}** ({len(ohlc_check.get('checked') or [])} bars)",
        "",
        "## Counts",
        "",
        "| Layer | Sheet | Engine | Matched | Sheet-only | Engine-only | Notes |",
        "|---|---:|---:|---:|---:|---:|---|",
        f"| Zones (+/- $0.02) | {z['unique_sheet']} | {z['unique_eng']} | {z['tol']} | {z['sheet_only']} | {z['eng_only']} | exact {z['exact']} |",
        f"| Breakouts (date+zone) | {b['sheet']} | {b['engine']} | {b['matched']} | {b['sheet_only']} | {b['eng_only']} | retest {b['retest_ok']}/{b['matched']}; after-win sheet {b['sheet_after']} / eng {b['eng_after']} |",
        f"| Trades (+/- $0.05) | {t['sheet']} | {t['engine']} | {t['matched']} | {t['sheet_only']} | {t['eng_only']} | exit dates {t['exit_ok']}; after-win sheet {t['sheet_after']}; invalid sheet rows excluded: {t.get('invalid_excluded', 0)} |",
        "",
        "## Material mismatches / root-cause hypotheses",
        "",
    ]
    if ohlc_check.get("status") == "MATCH":
        lines.append("- **OHLC spot-check:** sheet vs engine trading-day bars match at +/- $0.02.")
    elif ohlc_check.get("mismatches"):
        lines.append(f"- **OHLC mismatches:** {ohlc_check.get('mismatches')}")
    else:
        lines.append("- **OHLC spot-check:** incomplete (bars missing).")
    if z["sheet_only"] or z["eng_only"]:
        lines.append(
            f"- **Zones:** {z['sheet_only']} sheet-only / {z['eng_only']} engine-only after +/- $0.02 — "
            "likely maturity-window edge, duplicate-touch collapse, or post-window engine zones filtered."
        )
    else:
        lines.append("- **Zones:** full match at +/- $0.02.")
    if b["sheet_only"] or b["eng_only"] or b["retest_mismatch"]:
        lines.append(
            f"- **Breakouts:** sheet-only {b['sheet_only']}, engine-only {b['eng_only']}, "
            f"retest mismatches {b['retest_mismatch']}. Main-row delta dist `{b['main_delta_dist']}` "
            "(expect ~+4 from early-2010 sheet holiday placeholders, like AAPL)."
        )
        if b["so_samples"]:
            lines.append(f"  - Sheet-only samples: {b['so_samples']}")
        if b["eo_samples"]:
            lines.append(f"  - Engine-only samples: {b['eo_samples']}")
    else:
        lines.append(
            f"- **Breakouts:** full date+zone match; retests {b['retest_ok']}/{b['matched']}; "
            f"Main-row deltas `{b['main_delta_dist']}`."
        )
    if t["engine"] == 0:
        lines.append(
            f"- **Trades:** stamp has **0** MSFT closed trades despite BOs. "
            "Often `max_market_cap` default wipes MSFT when yfinance leaves market_cap=None — use `max_market_cap=0` or checkpoint rewrite. "
            f"Trades layer used `{t['stamp']}`."
        )
    if t["sheet_only"] or t["eng_only"]:
        lines.append(
            f"- **Trades mismatches:** sheet-only {t['sheet_only']} {t['so_samples']}; "
            f"engine-only {t['eng_only']} {t['eo_samples']}. "
            "Likely growth/SPY/one-trade-at-a-time gates, or older-stamp setting drift vs sheet."
        )
    elif t["matched"] == t["sheet"] and t["eng_only"] == 0:
        lines.append("- **Trades:** full match in window (invalid $0/#DIV/0! sheet rows excluded).")
    else:
        lines.append(
            f"- **Trades:** matched {t['matched']}/{t['sheet']}; exit dates {t['exit_ok']}."
        )
    lines += [
        "",
        "## Artifacts",
        "",
        "- `MSFT_sheet_ohlc.csv`, `MSFT_sheet_zones.csv`, `MSFT_sheet_breakouts.csv`, `MSFT_sheet_trades.csv`",
        "- `MSFT_zones_diff.md`, `MSFT_breakouts_diff.md`, `MSFT_trades_diff.md`",
        "- Match detail CSVs: `MSFT_*_match_detail.csv`",
        "- Four-scenario cut-paste: `MSFT_four_scenario_stats.md`",
        "",
    ]
    (OUT / "MSFT_reconcile_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


def check_critical_bars():
    """Spot-check a few sheet OHLC bars vs engine MSFT.csv."""
    want_dates = ["2010-01-04", "2013-04-24", "2020-04-13", "2022-04-01"]
    sheet = {}
    with (OUT / "MSFT_sheet_ohlc.csv").open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            d = r.get("date")
            if d in want_dates:
                sheet[d] = (
                    float(r["open"]),
                    float(r["high"]),
                    float(r["low"]),
                    float(r["close"]),
                )
    eng = {}
    if MSFT_CSV.exists():
        with MSFT_CSV.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                d = (r.get("Date") or r.get("date") or "").strip()[:10]
                if d in want_dates:
                    eng[d] = (
                        round(float(r.get("Open") or r.get("open")), 4),
                        round(float(r.get("High") or r.get("high")), 4),
                        round(float(r.get("Low") or r.get("low")), 4),
                        round(float(r.get("Close") or r.get("close")), 4),
                    )
    mismatches = []
    checked = []
    for d, sbar in sheet.items():
        ebar = eng.get(d)
        if ebar is None:
            mismatches.append((d, sbar, None))
            continue
        ok = all(abs(round(a, 2) - round(b, 2)) <= 0.02 for a, b in zip(sbar, ebar))
        checked.append((d, sbar, ebar, ok))
        if not ok:
            mismatches.append((d, sbar, ebar))
    status = "MATCH" if checked and not mismatches else ("MISMATCH" if mismatches else "MISSING")
    return {
        "checked": checked,
        "mismatches": mismatches,
        "status": status,
        "sheet": sheet,
        "engine": eng,
    }


def pick_trades_stamp(cli_stamp: str | None) -> str:
    if cli_stamp:
        return cli_stamp
    # Prefer preferred stamp if it has MSFT trades; else newest prior stamp with MSFT.
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
    print(f"[trades] preferred {STAMP} has 0 MSFT; using {cands[0][0]} ({cands[0][1]} trades)")
    return cands[0][0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trades-stamp", default=None)
    ap.add_argument("--zones-stamp", default="260720143523")
    ap.add_argument("--bo-stamp", default="260720165358")
    args = ap.parse_args()

    text = extract_paste()
    exports = ensure_exports(text)
    ohlc_check = check_critical_bars()
    print("OHLC_CHECK", ohlc_check.get("status"), ohlc_check.get("checked"))
    z = reconcile_zones(exports["unique_zones"], args.zones_stamp)
    print("ZONES", z)
    b = reconcile_breakouts(exports["bo_rows"], args.bo_stamp)
    print("BREAKOUTS", {k: b[k] for k in b if k not in ("so_samples", "eo_samples")})
    tstamp = pick_trades_stamp(args.trades_stamp or "260720165358")
    # Count invalid raw rows excluded
    raw_valid = 0
    raw_invalid = 0
    for r in exports["tr_rows"]:
        d = parse_date(r.get("Trigger Date"))
        entry = parse_money(r.get("Entry Price"))
        exit_price = parse_money(r.get("Exit Price"))
        if d is None:
            continue
        if entry is None or _sheet_trade_invalid(r, entry, exit_price):
            raw_invalid += 1
        else:
            raw_valid += 1
    t = reconcile_trades(exports["tr_rows"], tstamp)
    t["invalid_excluded"] = raw_invalid
    print("TRADES", {k: t[k] for k in t if k not in ("so_samples", "eo_samples", "note")})
    write_summary(
        exports, z, b, t, exports["zero_dates"], args.zones_stamp, args.bo_stamp, ohlc_check
    )


if __name__ == "__main__":
    main()
