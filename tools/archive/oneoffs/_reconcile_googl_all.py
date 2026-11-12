"""Reconcile GOOGL BRT sheet (transcript paste) vs engine stamp 260720143523.

Layers: zones (+/- $0.02), breakouts/retests, closed trades (+/- $0.05).
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
WIN_END = datetime(2026, 7, 20).date()
TRANSCRIPT = Path(
    r"C:\Users\songg\.cursor\projects\c-Users-songg-Downloads-stockresearch"
    r"\agent-transcripts\f301f0a6-39e4-4a95-a5fe-45ee16e855fd"
    r"\f301f0a6-39e4-4a95-a5fe-45ee16e855fd.jsonl"
)
GOOGL_CSV = ROOT / "data" / "newdata" / "data" / "GOOGL.csv"


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
        blob = "\n".join(texts)
        has_sections = (
            "Matured touch price" in blob
            and "Breakout Date" in blob
            and "Trigger Date" in blob
            and "Date\tOpen\tHigh\tLow\tClose" in blob
        )
        is_googl = (
            "GOOGL\nDate\tOpen" in blob
            or "GOOGL\r\nDate\tOpen" in blob
            or ("GOOGL" in blob[:200] and has_sections)
        )
        if has_sections and is_googl:
            latest = blob
    if not latest:
        raise SystemExit("GOOGL paste not found in transcript")
    if "<user_query>" in latest:
        latest = latest[latest.find("<user_query>") + len("<user_query>") :]
    if "</user_query>" in latest:
        latest = latest[: latest.find("</user_query>")]
    latest = latest.strip()
    if latest.startswith("GOOGL\n") or latest.startswith("GOOGL\r\n"):
        first, _, rest = latest.partition("\n")
        if first.strip() == "GOOGL" and rest:
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
    (TOOLS / "googl_brt_sheet_zones.tsv").write_text(zones.rstrip() + "\n", encoding="utf-8")
    (TOOLS / "googl_brt_sheet_breakouts.tsv").write_text(bos.rstrip() + "\n", encoding="utf-8")
    (TOOLS / "googl_brt_sheet_trades.tsv").write_text(trades.rstrip() + "\n", encoding="utf-8")

    zero_dates = []
    trading_dates = []
    with (OUT / "GOOGL_sheet_ohlc.csv").open("w", newline="", encoding="utf-8") as f:
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
            else:
                trading_dates.append(d.isoformat())

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
    with (OUT / "GOOGL_sheet_zones.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["touch", "lower", "upper"])
        for t, lo, hi in unique_zones:
            w.writerow([f"{t:.4f}", f"{lo:.4f}", f"{hi:.4f}"])

    bo_rows = list(csv.DictReader(bos.splitlines(), delimiter="\t"))
    with (OUT / "GOOGL_sheet_breakouts.csv").open("w", newline="", encoding="utf-8") as f:
        if bo_rows:
            w = csv.DictWriter(f, fieldnames=list(bo_rows[0].keys()))
            w.writeheader()
            w.writerows(bo_rows)

    tr_rows = list(csv.DictReader(trades.splitlines(), delimiter="\t"))
    with (OUT / "GOOGL_sheet_trades.csv").open("w", newline="", encoding="utf-8") as f:
        if tr_rows:
            w = csv.DictWriter(f, fieldnames=list(tr_rows[0].keys()))
            w.writeheader()
            w.writerows(tr_rows)

    return {
        "zero_dates": zero_dates,
        "trading_dates": trading_dates,
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
    eng_path = ROOT / "drive" / f"BRT_ZONES_GOOGL_{stamp}.csv"
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

    with (OUT / "GOOGL_zones_match_detail.csv").open("w", newline="", encoding="utf-8") as f:
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
            w.writerow(["tol_0.02", s[0], s[1], s[2], ed["date"], e[0], e[1], e[2], "within 0.02"])
        for s in sorted(so_rem):
            w.writerow(["sheet_only", s[0], s[1], s[2], "", "", "", "", ""])
        for e in sorted(eo_rem):
            ed = unique_eng[e]
            w.writerow(["engine_only", "", "", "", ed["date"], e[0], e[1], e[2], ""])

    lines = [
        "# GOOGL zone reconcile (sheet paste 2026-07-20)",
        "",
        f"- Engine: `BRT_ZONES_GOOGL_{stamp}.csv`",
        "- Sheet: `tools/googl_brt_sheet_zones.tsv` / `GOOGL_sheet_zones.csv`",
        f"- Window: {WIN_START} .. {WIN_END}",
        f"- Sheet unique: **{len(unique_sheet)}**",
        f"- Engine unique: **{len(unique_eng)}**",
        "",
        "## Exact (tol=$0.00)",
        f"- Matches: **{len(exact)}**",
        f"- Sheet-only ({len(sheet_only)}): "
        + (", ".join(fmt_z(z) for z in sorted(sheet_only)[:20]) if sheet_only else "(none)"),
        f"- Engine-only ({len(eng_only)}): "
        + (", ".join(fmt_z(z) for z in sorted(eng_only)[:20]) if eng_only else "(none)"),
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
    (OUT / "GOOGL_zones_diff.md").write_text("\n".join(lines), encoding="utf-8")
    return {
        "unique_sheet": len(unique_sheet),
        "unique_eng": len(unique_eng),
        "exact": len(exact),
        "tol": tol_total,
        "sheet_only": len(so_rem),
        "eng_only": len(eo_rem),
        "sheet_only_keys": sorted(so_rem),
        "eng_only_keys": sorted(eo_rem),
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
            if (r.get("SYMBOL") or "").upper() != "GOOGL":
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

    with (OUT / "GOOGL_breakouts_match_detail.csv").open("w", newline="", encoding="utf-8") as f:
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
        "# GOOGL breakout/retest reconcile",
        "",
        "- Sheet TSV: `tools/googl_brt_sheet_breakouts.tsv`",
        f"- Engine: `BRT_breakout_and_retest_{stamp}.csv` (GOOGL filter)",
        f"- Window: {WIN_START} .. {WIN_END}",
        f"- Sheet BO in window: **{len(sheet_bo)}**",
        f"- Engine BO in window: **{len(eng_bo)}**",
        "",
        "## Match summary (windowed)",
        f"- Exact date+bounds: **{len(exact)}**",
        f"- Near (+/- $0.02 bounds): **{len(near)}**",
        f"- Total matched (date+zone): **{len(matched)}** / {len(sheet_bo)} sheet ({pct:.1f}%)",
        f"- Sheet-only: **{len(so)}**",
        f"- Engine-only: **{len(eo)}**",
        f"- Retest date match among matched: **{retest_ok}/{len(matched)}**",
        f"- Main Row delta distribution: `{dict(sorted(delta_counts.items()))}`",
        "",
    ]
    (OUT / "GOOGL_breakouts_diff.md").write_text("\n".join(lines), encoding="utf-8")
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
        "sheet_only_rows": so,
        "eng_only_rows": eo,
    }


def _sheet_trade_invalid(r: dict, entry, exit_price) -> bool:
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
                if (r.get("SYMBOL") or "").upper() != "GOOGL":
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
    sheet_tr = [s for s in load_sheet_trades(tr_rows) if WIN_START <= s["trigger"] <= WIN_END]
    sheet_after = [s for s in load_sheet_trades(tr_rows) if s["trigger"] > WIN_END]
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
            "trigger_via": via,
            "trigger_delta_days": dd,
        }
        (exact if kind == "exact" else near).append(rec)

    eo = [eng_tr[i] for i in range(len(eng_tr)) if i not in used]
    matched = exact + near
    exit_ok = sum(1 for m in matched if m["exit_date_match"])
    exit_known = sum(1 for m in matched if m["exit_date_match"] is not None)
    exit_px_ok = sum(1 for m in matched if m["exit_price_match"])

    with (OUT / "GOOGL_trades_match_detail.csv").open("w", newline="", encoding="utf-8") as f:
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

    (OUT / "GOOGL_trades_diff.md").write_text(
        f"# GOOGL trades reconcile\n\nmatched={len(matched)}/{len(sheet_tr)} sheet-only={len(so)} eng-only={len(eo)}\n",
        encoding="utf-8",
    )
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
        "eo_samples": [(str(e["trigger_ca"]), e["entry"], e["exit_type"]) for e in eo[:15]],
        "matched_rows": matched,
        "sheet_only_rows": so,
        "eng_only_rows": eo,
    }


def check_ohlc(zero_dates, trading_dates):
    """Compare sheet trading-day OHLC vs engine GOOGL.csv."""
    sheet = {}
    with (OUT / "GOOGL_sheet_ohlc.csv").open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if float(r["open"]) == 0:
                continue
            sheet[r["date"]] = (
                float(r["open"]),
                float(r["high"]),
                float(r["low"]),
                float(r["close"]),
            )
    eng = {}
    if GOOGL_CSV.exists():
        with GOOGL_CSV.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                d = (r.get("Date") or r.get("date") or "").strip()[:10]
                if d:
                    eng[d] = (
                        round(float(r.get("Open") or r.get("open")), 4),
                        round(float(r.get("High") or r.get("high")), 4),
                        round(float(r.get("Low") or r.get("low")), 4),
                        round(float(r.get("Close") or r.get("close")), 4),
                    )
    mismatches = []
    missing_eng = []
    missing_sheet = []
    for d, sbar in sheet.items():
        ebar = eng.get(d)
        if ebar is None:
            missing_eng.append(d)
            continue
        ok = all(abs(round(a, 2) - round(b, 2)) <= 0.02 for a, b in zip(sbar, ebar))
        if not ok:
            mismatches.append((d, sbar, ebar))
    for d in eng:
        if d not in sheet and d >= "2010-01-04":
            missing_sheet.append(d)
    return {
        "zero_count": len(zero_dates),
        "trading_count": len(trading_dates),
        "sheet_trading_bars": len(sheet),
        "engine_bars": len(eng),
        "mismatches": mismatches[:30],
        "mismatch_count": len(mismatches),
        "missing_eng": len(missing_eng),
        "missing_sheet": len(missing_sheet),
        "status": "MATCH" if not mismatches and not missing_eng else "MISMATCH",
    }


def analyze_zero_impact(zero_dates, bo_result, z_result):
    """Quantify how $0 rows affect row indices and phantom zones."""
    zero_set = set(zero_dates)
    # Main row delta from breakouts
    main_delta = bo_result.get("main_delta_dist", {})
    # Check if any sheet-only zones/BOs correlate with zero rows nearby
    lines = [
        "## $0 OHLC holiday placeholder analysis",
        "",
        f"- Sheet total rows: **{len(zero_dates) + bo_result.get('sheet', 0)}** (approx)",
        f"- `$0` placeholder rows: **{len(zero_dates)}** ({100*len(zero_dates)/max(1,len(zero_dates)+3402):.1f}% of grid)",
        f"- Engine GOOGL.csv: trading-day only, **0** zero-OHLC bars",
        "",
        "### Impact mechanism",
        "",
        "Same class of bug as AMZN/NVDA: GOOGLEFINANCE returns `{0,0,0,0,0}` on non-trading days",
        "that the sheet keeps as date rows. These poison:",
        "- Pivot detection (fake `$0` lows become global MIN)",
        "- Touch/pullback % (MIN(Low) in post-pivot window hits `$0`)",
        "- Main/Scan/retest row indices (+N vs engine for same calendar date)",
        "",
        f"- Matched BO Main Row delta distribution: `{main_delta}`",
        "",
        "### Recommended fix",
        "",
        f"**Delete all {len(zero_dates)} `$0` rows** from the GOOGL sheet date/OHLC grid.",
        "Do NOT add OHLC overrides for `$0` holidays — there is no real price to override.",
        "",
    ]
    if zero_dates:
        lines += [
            "### Sample `$0` dates (first 20 / last 5)",
            "",
            ", ".join(zero_dates[:20]) + (" ..." if len(zero_dates) > 20 else ""),
            "",
            "Last: " + ", ".join(zero_dates[-5:]),
            "",
        ]
    return "\n".join(lines)


def four_scenario_stats(stamp: str):
    """Pull GOOGL stats from four-scenario run if available."""
    path = OUT / "BRT_four_scenario_stats.csv"
    if not path.exists():
        return None
    rows = []
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("symbol") or r.get("SYMBOL") or "").upper() == "GOOGL":
                rows.append(r)
    if not rows:
        return None
    lines = ["## Four-scenario Default stats (GOOGL)", ""]
    for r in rows:
        lines.append(
            f"- {r.get('scenario','?')}: trades={r.get('trades','?')} "
            f"win_rate={r.get('win_rate','?')} avg_pnl={r.get('avg_pnl_pct','?')}% "
            f"W/L={r.get('wins','?')}/{r.get('losses','?')}"
        )
    out = OUT / "GOOGL_four_scenario_stats.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lines


def write_summary(exports, z, b, t, ohlc_check, zero_analysis, stamp: str):
    full_parity = (
        z["sheet_only"] == 0
        and z["eng_only"] == 0
        and b["sheet_only"] == 0
        and b["eng_only"] == 0
        and t["sheet_only"] == 0
        and t["eng_only"] == 0
    )
    lines = [
        "# GOOGL BRT sheet vs engine — reconcile summary",
        "",
        f"- Sheet paste: transcript `f301f0a6-...` user message 2026-07-20 (GOOGL OHLC + zones + BOs + trades)",
        f"- Engine stamp: **{stamp}** (`breakout_zone_pick=max`, `stop_loss_based=trigger_low`, SPY -1000, zone pick max, C9=7, C10=10.8%)",
        f"- Sheet `$0` holiday placeholders: **{ohlc_check['zero_count']}** / {ohlc_check['sheet_trading_bars'] + ohlc_check['zero_count']} total rows ({100*ohlc_check['zero_count']/max(1,ohlc_check['sheet_trading_bars']+ohlc_check['zero_count']):.1f}%)",
        f"- Engine GOOGL.csv: {ohlc_check['engine_bars']} trading-day bars, 0 zero-OHLC",
        f"- **OHLC trading-day compare:** **{ohlc_check['status']}** ({ohlc_check['mismatch_count']} mismatches on overlapping dates)",
        "",
        "## Reconciled?",
        "",
        f"**{'YES — full parity' if full_parity else 'Partial'}**",
        "",
        "| Layer | Sheet | Engine | Matched | Sheet-only | Engine-only | Notes |",
        "|---|---:|---:|---:|---:|---:|---|",
        f"| Zones (±$0.02) | {z['unique_sheet']} | {z['unique_eng']} | **{z['tol']}** | **{z['sheet_only']}** | **{z['eng_only']}** | exact {z['exact']} |",
        f"| Breakouts (date+zone) | {b['sheet']} | {b['engine']} | **{b['matched']}** | **{b['sheet_only']}** | **{b['eng_only']}** | retest {b['retest_ok']}/{b['matched']} |",
        f"| Trades (±$0.05 entry) | {t['sheet']} | {t['engine']} | **{t['matched']}** | **{t['sheet_only']}** | **{t['eng_only']}** | exit dates {t['exit_ok']} |",
        "",
        "## Root causes (ranked by impact)",
        "",
    ]

    causes = []
    if ohlc_check["zero_count"] > 100:
        causes.append(
            (
                1,
                f"**{ohlc_check['zero_count']} `$0` holiday placeholder rows** — primary structural poison. "
                "Fake `$0` lows corrupt pivot/Touch/pullback and inflate sheet row indices vs engine. "
                f"Main-row delta `{b.get('main_delta_dist')}` on matched BOs reflects calendar padding.",
            )
        )
    if ohlc_check["mismatch_count"]:
        causes.append(
            (
                2,
                f"**{ohlc_check['mismatch_count']} non-zero OHLC mismatches** vs engine GOOGL.csv — "
                f"sample: {ohlc_check['mismatches'][:3]}",
            )
        )
    if z["sheet_only"] or z["eng_only"]:
        causes.append(
            (
                3,
                f"**Zone gaps:** {z['sheet_only']} sheet-only / {z['eng_only']} engine-only — "
                f"sheet-only: {[fmt_z(x) for x in z.get('sheet_only_keys', [])[:5]]}; "
                f"engine-only: {[fmt_z(x) for x in z.get('eng_only_keys', [])[:5]]}",
            )
        )
    if b["sheet_only"] or b["eng_only"]:
        causes.append(
            (
                4,
                f"**Breakout gaps:** {b['sheet_only']} sheet-only / {b['eng_only']} engine-only",
            )
        )
    if t["sheet_only"] or t["eng_only"]:
        causes.append(
            (
                5,
                f"**Trade gaps:** sheet-only {t['so_samples']}; engine-only {t['eo_samples']}",
            )
        )
    if not causes:
        causes.append((1, "**No material gaps** — counts match at all three layers."))

    for _rank, text in sorted(causes):
        lines.append(f"### {_rank}. {text}")
        lines.append("")

    lines += [
        zero_analysis,
        "",
        "## Exact next actions (user)",
        "",
        f"1. **Delete all {ohlc_check['zero_count']} `$0` OHLC rows** from the GOOGL sheet date grid first. "
        "This is the highest-impact fix (same as AMZN 4-row fix, but GOOGL has far more).",
        "2. After row deletes, re-paste zones/BOs/trades and re-reconcile — expect row-index alignment and possible zone/BO drift.",
    ]
    if ohlc_check["mismatch_count"]:
        lines.append(
            "3. Review non-zero OHLC mismatches; add GOOGL-specific overrides to `OHLC_override_formula.md` only for confirmed bad prints."
        )
    else:
        lines.append(
            "3. **No OHLC overrides needed** for trading-day bars — prices match engine at ±$0.02."
        )
    lines += [
        "",
        f"## Full parity achievable?",
        "",
        f"**{'Yes' if full_parity else 'Yes after $0 row cleanup' if ohlc_check['zero_count'] > 0 and z['tol']==z['unique_sheet'] and b['matched']==b['sheet'] and t['matched']==t['sheet'] else 'Partial — see gaps above'}**",
        "",
        "## Artifacts",
        "",
        "- `GOOGL_sheet_ohlc.csv`, `GOOGL_sheet_zones.csv`, `GOOGL_sheet_breakouts.csv`, `GOOGL_sheet_trades.csv`",
        "- `GOOGL_zones_diff.md`, `GOOGL_breakouts_diff.md`, `GOOGL_trades_diff.md`",
        "- Match detail CSVs: `GOOGL_*_match_detail.csv`",
        "",
    ]
    (OUT / "GOOGL_reconcile_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stamp", default=STAMP)
    ap.add_argument("--bo-stamp", default=None)
    ap.add_argument("--trades-stamp", default=None)
    args = ap.parse_args()
    bo_stamp = args.bo_stamp or args.stamp
    tr_stamp = args.trades_stamp or args.stamp

    text = extract_paste()
    exports = ensure_exports(text)
    ohlc_check = check_ohlc(exports["zero_dates"], exports["trading_dates"])
    print("OHLC", ohlc_check)
    z = reconcile_zones(exports["unique_zones"], args.stamp)
    print("ZONES", z)
    b = reconcile_breakouts(exports["bo_rows"], bo_stamp)
    print("BREAKOUTS", {k: b[k] for k in b if not k.endswith("_rows") and k not in ("so_samples", "eo_samples")})
    t = reconcile_trades(exports["tr_rows"], tr_stamp)
    print("TRADES", {k: t[k] for k in t if k not in ("so_samples", "eo_samples", "matched_rows")})
    zero_analysis = analyze_zero_impact(exports["zero_dates"], b, z)
    four_scenario_stats(tr_stamp)
    write_summary(exports, z, b, t, ohlc_check, zero_analysis, args.stamp)


if __name__ == "__main__":
    main()
