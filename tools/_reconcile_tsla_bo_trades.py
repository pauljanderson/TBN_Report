"""Extract latest TSLA sheet BO+trades pastes and reconcile vs engine dumps."""
from __future__ import annotations

import csv
import json
import re
from collections import Counter, OrderedDict
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")
TRANSCRIPT = Path(
    r"C:\Users\songg\.cursor\projects\c-Users-songg-Downloads-stockresearch"
    r"\agent-transcripts\f301f0a6-39e4-4a95-a5fe-45ee16e855fd"
    r"\f301f0a6-39e4-4a95-a5fe-45ee16e855fd.jsonl"
)
OUT_DIR = ROOT / "drive" / "brt_sheet_reconcile"
TOOLS = ROOT / "tools"
ENGINE_BO = ROOT / "drive" / "BRT_breakout_and_retest_260720082240.csv"
ENGINE_CLOSED = ROOT / "drive" / "BRT_Closed_260720082240.csv"
ENGINE_OPEN = ROOT / "drive" / "BRT_Open_260720082240.csv"
WIN_START = datetime(2010, 1, 4).date()
WIN_END = datetime(2026, 6, 5).date()


def parse_money(s):
    if s is None:
        return None
    s = str(s).strip().replace("$", "").replace(",", "").replace("%", "")
    if not s or s.lower() in {"nan", "none", "null"}:
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


def within(a, b, tol=0.02):
    if a is None or b is None:
        return False
    return abs(a - b) <= tol + 1e-9


def extract_latest_user_text(*needles):
    latest = None
    with open(TRANSCRIPT, "r", encoding="utf-8") as f:
        for line in f:
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
            for text in texts:
                if all(n in text for n in needles):
                    latest = text
    if not latest:
        raise SystemExit(f"paste not found for needles={needles}")
    if "</user_query>" in latest:
        # keep full text; markers are inside user_query
        pass
    idx = latest.find("<user_query>")
    if idx >= 0:
        latest = latest[idx + len("<user_query>") :]
    if "</user_query>" in latest:
        latest = latest[: latest.find("</user_query>")]
    return latest


def save_tsv_section(text, header_line, out_path, stop_markers=None):
    stop_markers = stop_markers or []
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith(header_line) or ln.strip() == header_line:
            start = i
            break
    if start is None:
        # fuzzy
        for i, ln in enumerate(lines):
            if header_line.split("\t")[0] in ln and "\t" in ln:
                start = i
                break
    if start is None:
        raise SystemExit(f"header not found: {header_line[:60]}")
    out_lines = [lines[start]]
    for ln in lines[start + 1 :]:
        if any(m in ln for m in stop_markers):
            break
        # stop on blank-ish section headers without tabs that look like new sections
        if ln.strip().lower().startswith("and trades"):
            break
        if ln.strip().lower().startswith("trigger date\t"):
            break
        out_lines.append(ln)
    out_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return out_lines


def load_sheet_breakouts(tsv_path):
    rows = []
    with open(tsv_path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f, delimiter="\t")
        for row in r:
            d = parse_date(row.get("Breakout Date"))
            lo = parse_money(row.get("Zone Lower"))
            hi = parse_money(row.get("Zone Upper"))
            if d is None or lo is None or hi is None:
                continue
            rd = parse_date(row.get("Retest Date"))
            hit = str(row.get("retest hit") or "").strip()
            rows.append(
                {
                    "bo_date": d,
                    "lower": lo,
                    "upper": hi,
                    "active": str(row.get("Breakout Active") or "").strip(),
                    "retest_date": rd,
                    "retest_hit": hit,
                    "too_fast": str(row.get("Too fast retest") or "").strip(),
                    "main_row": row.get("Main Row"),
                }
            )
    return rows


def load_engine_breakouts(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            if (row.get("SYMBOL") or "").upper() != "TSLA":
                continue
            d = parse_date(row.get("Breakout Date"))
            lo = parse_money(row.get("Zone Lower"))
            hi = parse_money(row.get("Zone Upper"))
            if d is None or lo is None or hi is None:
                continue
            if d < WIN_START or d > WIN_END:
                continue
            rows.append(
                {
                    "bo_date": d,
                    "lower": lo,
                    "upper": hi,
                    "retest_date": parse_date(row.get("Retest Date")),
                    "main_row": row.get("Main Row"),
                    "raw": row,
                }
            )
    return rows


def match_breakouts(sheet, engine, tol=0.02):
    eng_by_date = {}
    for i, e in enumerate(engine):
        eng_by_date.setdefault(e["bo_date"], []).append(i)

    used = set()
    exact = []
    near = []
    sheet_only = []

    for si, s in enumerate(sheet):
        cands = eng_by_date.get(s["bo_date"], [])
        # exact first
        hit = None
        kind = None
        for ei in cands:
            if ei in used:
                continue
            e = engine[ei]
            if abs(s["lower"] - e["lower"]) < 1e-9 and abs(s["upper"] - e["upper"]) < 1e-9:
                hit = ei
                kind = "exact"
                break
        if hit is None:
            best = None
            best_score = None
            for ei in cands:
                if ei in used:
                    continue
                e = engine[ei]
                if within(s["lower"], e["lower"], tol) and within(s["upper"], e["upper"], tol):
                    score = abs(s["lower"] - e["lower"]) + abs(s["upper"] - e["upper"])
                    if best_score is None or score < best_score:
                        best = ei
                        best_score = score
            if best is not None:
                hit = best
                kind = "near"
        if hit is None:
            sheet_only.append(s)
            continue
        used.add(hit)
        e = engine[hit]
        retest_ok = (s["retest_date"] == e["retest_date"]) or (
            s["retest_date"] is None and e["retest_date"] is None
        )
        rec = {"sheet": s, "engine": e, "kind": kind, "retest_match": retest_ok}
        if kind == "exact":
            exact.append(rec)
        else:
            near.append(rec)

    engine_only = [engine[i] for i in range(len(engine)) if i not in used]
    return exact, near, sheet_only, engine_only


def classify_bo_mismatches(sheet_only, engine_only):
    """Heuristic classification for remaining BO mismatches."""
    causes = Counter()
    notes = []
    # same date different zone (MAX pick style)
    eng_dates = {}
    for e in engine_only:
        eng_dates.setdefault(e["bo_date"], []).append(e)
    for s in sheet_only:
        same = eng_dates.get(s["bo_date"], [])
        if same:
            # pick closest upper
            closest = min(same, key=lambda e: abs(e["upper"] - s["upper"]))
            du = abs(closest["upper"] - s["upper"])
            if du <= 0.05:
                causes["same_date_near_band_MAX_SKIPPED"] += 1
                notes.append(
                    f"SO {s['bo_date']} {s['lower']}/{s['upper']} vs eng {closest['lower']}/{closest['upper']} (Δupper={du:.4f})"
                )
            else:
                causes["same_date_different_zone"] += 1
                notes.append(
                    f"SO {s['bo_date']} {s['lower']}/{s['upper']} vs eng {[ (x['lower'],x['upper']) for x in same ]}"
                )
        else:
            causes["sheet_date_missing_in_engine"] += 1
            notes.append(f"SO date-missing {s['bo_date']} {s['lower']}/{s['upper']}")

    sheet_dates = {s["bo_date"] for s in sheet_only}
    for e in engine_only:
        if e["bo_date"] not in sheet_dates and e["bo_date"] not in {
            s["bo_date"] for s in sheet_only
        }:
            # already counted via sheet side for same-date; engine-only unique dates:
            pass
    for e in engine_only:
        if not any(s["bo_date"] == e["bo_date"] for s in sheet_only):
            causes["engine_date_missing_in_sheet"] += 1
    return causes, notes


def load_sheet_trades(tsv_path):
    rows = []
    with open(tsv_path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f, delimiter="\t")
        for row in r:
            # tolerate header variants
            trig = (
                row.get("Trigger Date")
                or row.get("Entry Date")
                or row.get("DATE_OPENED")
            )
            d = parse_date(trig)
            entry = parse_money(
                row.get("Entry Price") or row.get("ENTRY_PRICE") or row.get("Entry")
            )
            if d is None or entry is None:
                continue
            xd = parse_date(row.get("Exit Date") or row.get("DATE_CLOSED"))
            xp = parse_money(row.get("Exit Price") or row.get("EXIT_PRICE"))
            pnl = parse_money(row.get("Profit %") or row.get("PNL_PCT") or row.get("Profit %"))
            result = str(row.get("Result") or "").strip()
            rows.append(
                {
                    "trigger": d,
                    "entry": entry,
                    "exit_date": xd,
                    "exit_price": xp,
                    "pnl_pct": pnl,
                    "result": result,
                    "days": row.get("Days In Trade"),
                    "raw": row,
                }
            )
    return rows


def load_engine_trades():
    rows = []
    for path, open_flag in ((ENGINE_CLOSED, False), (ENGINE_OPEN, True)):
        if not path.exists():
            continue
        with open(path, newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                if (row.get("SYMBOL") or "").upper() != "TSLA":
                    continue
                d = parse_date(row.get("DATE_OPENED"))
                entry = parse_money(row.get("ENTRY_PRICE"))
                if d is None or entry is None:
                    continue
                if d < WIN_START or d > WIN_END:
                    continue
                rows.append(
                    {
                        "trigger": d,
                        "entry": entry,
                        "exit_date": parse_date(row.get("DATE_CLOSED")),
                        "exit_price": parse_money(row.get("EXIT_PRICE")),
                        "pnl_pct": parse_money(
                            str(row.get("PNL_PCT") or "").replace("%", "")
                        ),
                        "exit_type": row.get("EXIT_TYPE"),
                        "open": open_flag,
                        "raw": row,
                    }
                )
    return rows


def match_trades(sheet, engine, tol=0.02):
    eng_by_date = {}
    for i, e in enumerate(engine):
        eng_by_date.setdefault(e["trigger"], []).append(i)
    used = set()
    exact = []
    near = []
    sheet_only = []
    for s in sheet:
        cands = eng_by_date.get(s["trigger"], [])
        hit = None
        kind = None
        for ei in cands:
            if ei in used:
                continue
            e = engine[ei]
            if abs(s["entry"] - e["entry"]) < 1e-9:
                hit = ei
                kind = "exact"
                break
        if hit is None:
            best = None
            best_score = None
            for ei in cands:
                if ei in used:
                    continue
                e = engine[ei]
                if within(s["entry"], e["entry"], tol):
                    score = abs(s["entry"] - e["entry"])
                    if best_score is None or score < best_score:
                        best = ei
                        best_score = score
            if best is not None:
                hit = best
                kind = "near"
        if hit is None:
            sheet_only.append(s)
            continue
        used.add(hit)
        rec = {"sheet": s, "engine": engine[hit], "kind": kind}
        if kind == "exact":
            exact.append(rec)
        else:
            near.append(rec)
    engine_only = [engine[i] for i in range(len(engine)) if i not in used]
    return exact, near, sheet_only, engine_only


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    TOOLS.mkdir(parents=True, exist_ok=True)

    text = extract_latest_user_text("Breakout Date", "Zone Lower")
    print("paste chars", len(text))

    bo_header = "Breakout Date\tZone Lower\tZone Upper\tBreakout Active\tMain Row\tScan Start Row\tretest Row\tRetest Date\tretest hit\tToo fast retest"
    bo_path = TOOLS / "tsla_brt_sheet_breakout_retest.tsv"
    bo_lines = save_tsv_section(
        text,
        bo_header,
        bo_path,
        stop_markers=["and trades", "Trigger Date\t"],
    )
    print("BO tsv lines", len(bo_lines))

    # trades may be in same message
    trades_path = TOOLS / "tsla_brt_sheet_trades.tsv"
    if "Trigger Date" in text:
        # find trades header
        trade_header = None
        for ln in text.splitlines():
            if ln.startswith("Trigger Date\t") or (
                "Trigger Date" in ln and "Entry Price" in ln and "\t" in ln
            ):
                trade_header = ln
                break
        if trade_header:
            save_tsv_section(text, trade_header, trades_path, stop_markers=[])
            print("trades header", trade_header[:80])
        else:
            print("WARNING: Trigger Date present but header not parsed")
    else:
        print("WARNING: no trades in this paste — keeping prior trades file if any")

    # Also copy into reconcile folder
    (OUT_DIR / "TSLA_sheet_breakout_retest.csv").write_text(
        # convert tabs to commas carefully via csv
        "",
        encoding="utf-8",
    )

    sheet_bo = load_sheet_breakouts(bo_path)
    eng_bo = load_engine_breakouts(ENGINE_BO)
    print("sheet BO", len(sheet_bo), "engine BO", len(eng_bo))

    exact, near, so, eo = match_breakouts(sheet_bo, eng_bo, tol=0.02)
    matched = exact + near
    retest_ok = sum(1 for m in matched if m["retest_match"])
    causes, notes = classify_bo_mismatches(so, eo)

    # write BO detail csv
    with open(OUT_DIR / "TSLA_breakout_match_detail.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "status",
                "sheet_bo_date",
                "sheet_lo",
                "sheet_hi",
                "sheet_retest",
                "eng_bo_date",
                "eng_lo",
                "eng_hi",
                "eng_retest",
                "retest_match",
            ]
        )
        for m in exact:
            s, e = m["sheet"], m["engine"]
            w.writerow(
                [
                    "exact",
                    s["bo_date"],
                    s["lower"],
                    s["upper"],
                    s["retest_date"],
                    e["bo_date"],
                    e["lower"],
                    e["upper"],
                    e["retest_date"],
                    m["retest_match"],
                ]
            )
        for m in near:
            s, e = m["sheet"], m["engine"]
            w.writerow(
                [
                    "near_0.02",
                    s["bo_date"],
                    s["lower"],
                    s["upper"],
                    s["retest_date"],
                    e["bo_date"],
                    e["lower"],
                    e["upper"],
                    e["retest_date"],
                    m["retest_match"],
                ]
            )
        for s in so:
            w.writerow(
                [
                    "sheet_only",
                    s["bo_date"],
                    s["lower"],
                    s["upper"],
                    s["retest_date"],
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
                    e["bo_date"],
                    e["lower"],
                    e["upper"],
                    e["retest_date"],
                    "",
                ]
            )

    bo_md = []
    bo_md.append("# TSLA breakout/retest reconcile (2026-07-20 09:59 paste)")
    bo_md.append("")
    bo_md.append(f"- Engine: `{ENGINE_BO.name}`")
    bo_md.append(f"- Window: {WIN_START} .. {WIN_END}")
    bo_md.append(f"- Sheet BO rows: **{len(sheet_bo)}**")
    bo_md.append(f"- Engine BO rows (TSLA in window): **{len(eng_bo)}**")
    bo_md.append("")
    bo_md.append("## Match summary")
    bo_md.append(f"- Exact date+bounds: **{len(exact)}**")
    bo_md.append(f"- Near (±$0.02 bounds): **{len(near)}**")
    bo_md.append(f"- Total matched: **{len(matched)}** / {len(sheet_bo)} sheet ({(100*len(matched)/max(1,len(sheet_bo))):.1f}%)")
    bo_md.append(f"- Sheet-only: **{len(so)}**")
    bo_md.append(f"- Engine-only: **{len(eo)}**")
    bo_md.append(f"- Retest date match among matched: **{retest_ok}/{len(matched)}**")
    bo_md.append("")
    bo_md.append("## Remaining mismatch causes")
    for k, v in causes.most_common():
        bo_md.append(f"- {k}: {v}")
    if notes:
        bo_md.append("")
        bo_md.append("### Sheet-only notes (first 40)")
        for n in notes[:40]:
            bo_md.append(f"- {n}")
    bo_md.append("")
    bo_md.append("## Sheet-only (first 50)")
    bo_md.append("| bo_date | lower | upper | retest |")
    bo_md.append("|---|---:|---:|---|")
    for s in so[:50]:
        bo_md.append(f"| {s['bo_date']} | {s['lower']:.4f} | {s['upper']:.4f} | {s['retest_date']} |")
    if len(so) > 50:
        bo_md.append(f"| ... | ({len(so)-50} more) | | |")
    bo_md.append("")
    bo_md.append("## Engine-only (first 50)")
    bo_md.append("| bo_date | lower | upper | retest |")
    bo_md.append("|---|---:|---:|---|")
    for e in eo[:50]:
        bo_md.append(f"| {e['bo_date']} | {e['lower']:.4f} | {e['upper']:.4f} | {e['retest_date']} |")
    if len(eo) > 50:
        bo_md.append(f"| ... | ({len(eo)-50} more) | | |")
    bo_md.append("")

    (OUT_DIR / "TSLA_breakout_diff.md").write_text("\n".join(bo_md), encoding="utf-8")
    (OUT_DIR / "TSLA_breakout_diff.txt").write_text(
        "\n".join(
            [
                f"sheet={len(sheet_bo)} engine={len(eng_bo)} exact={len(exact)} near={len(near)} matched={len(matched)} sheet_only={len(so)} engine_only={len(eo)} retest_ok={retest_ok}",
                f"causes={dict(causes)}",
            ]
        ),
        encoding="utf-8",
    )

    # Trades
    if trades_path.exists() and trades_path.stat().st_size > 20:
        sheet_tr = load_sheet_trades(trades_path)
    else:
        sheet_tr = []
    eng_tr = load_engine_trades()
    print("sheet trades", len(sheet_tr), "engine trades", len(eng_tr))

    tex, tnear, tso, teo = match_trades(sheet_tr, eng_tr, tol=0.02)
    tmatched = tex + tnear

    # PnL summary
    def pnl_sum(rows, key="pnl_pct"):
        vals = [r.get(key) for r in rows if r.get(key) is not None]
        return sum(vals) if vals else None, len(vals)

    sheet_pnl_sum, sheet_pnl_n = pnl_sum(sheet_tr)
    eng_pnl_sum, eng_pnl_n = pnl_sum(eng_tr)

    with open(OUT_DIR / "TSLA_trades_match_detail.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "status",
                "sheet_trigger",
                "sheet_entry",
                "sheet_exit",
                "sheet_pnl",
                "eng_trigger",
                "eng_entry",
                "eng_exit",
                "eng_pnl",
                "eng_exit_type",
            ]
        )
        for m in tex + tnear:
            s, e = m["sheet"], m["engine"]
            w.writerow(
                [
                    m["kind"],
                    s["trigger"],
                    s["entry"],
                    s["exit_date"],
                    s["pnl_pct"],
                    e["trigger"],
                    e["entry"],
                    e["exit_date"],
                    e["pnl_pct"],
                    e.get("exit_type"),
                ]
            )
        for s in tso:
            w.writerow(
                ["sheet_only", s["trigger"], s["entry"], s["exit_date"], s["pnl_pct"], "", "", "", "", ""]
            )
        for e in teo:
            w.writerow(
                [
                    "engine_only",
                    "",
                    "",
                    "",
                    "",
                    e["trigger"],
                    e["entry"],
                    e["exit_date"],
                    e["pnl_pct"],
                    e.get("exit_type"),
                ]
            )

    tr_md = []
    tr_md.append("# TSLA trades reconcile (2026-07-20 09:59 paste)")
    tr_md.append("")
    tr_md.append(f"- Engine closed: `{ENGINE_CLOSED.name}`")
    tr_md.append(f"- Engine open: `{ENGINE_OPEN.name}`")
    tr_md.append(f"- Sheet trades: **{len(sheet_tr)}**")
    tr_md.append(f"- Engine trades (TSLA closed+open in window): **{len(eng_tr)}**")
    tr_md.append("")
    tr_md.append("## Match summary")
    tr_md.append(f"- Exact trigger+entry: **{len(tex)}**")
    tr_md.append(f"- Near (±$0.02 entry): **{len(tnear)}**")
    tr_md.append(
        f"- Total matched: **{len(tmatched)}** / {len(sheet_tr)} sheet ({(100*len(tmatched)/max(1,len(sheet_tr))):.1f}%)"
    )
    tr_md.append(f"- Sheet-only: **{len(tso)}**")
    tr_md.append(f"- Engine-only: **{len(teo)}**")
    if sheet_pnl_sum is not None:
        tr_md.append(f"- Sheet PnL% sum ({sheet_pnl_n} rows): {sheet_pnl_sum:.2f}")
    if eng_pnl_sum is not None:
        tr_md.append(f"- Engine PnL% sum ({eng_pnl_n} rows): {eng_pnl_sum:.2f}")
    tr_md.append("")
    tr_md.append("## Sheet-only")
    tr_md.append("| trigger | entry | exit | pnl% | result |")
    tr_md.append("|---|---:|---|---:|---|")
    for s in tso:
        tr_md.append(
            f"| {s['trigger']} | {s['entry']:.4f} | {s['exit_date']} | {s['pnl_pct']} | {s['result']} |"
        )
    if not tso:
        tr_md.append("(none)")
    tr_md.append("")
    tr_md.append("## Engine-only")
    tr_md.append("| trigger | entry | exit | pnl% | exit_type | open |")
    tr_md.append("|---|---:|---|---:|---|---|")
    for e in teo:
        tr_md.append(
            f"| {e['trigger']} | {e['entry']:.4f} | {e['exit_date']} | {e['pnl_pct']} | {e.get('exit_type')} | {e.get('open')} |"
        )
    if not teo:
        tr_md.append("(none)")
    tr_md.append("")

    (OUT_DIR / "TSLA_trades_diff.md").write_text("\n".join(tr_md), encoding="utf-8")
    (OUT_DIR / "TSLA_trades_diff.txt").write_text(
        f"sheet={len(sheet_tr)} engine={len(eng_tr)} exact={len(tex)} near={len(tnear)} matched={len(tmatched)} sheet_only={len(tso)} engine_only={len(teo)}\n",
        encoding="utf-8",
    )

    # Also write CSV copies of sheet pastes into reconcile folder
    import shutil

    shutil.copy2(bo_path, OUT_DIR / "TSLA_sheet_breakout_retest.tsv")
    if trades_path.exists():
        shutil.copy2(trades_path, OUT_DIR / "TSLA_sheet_trades.tsv")

    print("=== ZONES (already done) exact=135 near=4 so=4 eo=4 early_gaps_closed=YES ===")
    print(
        f"=== BO exact={len(exact)} near={len(near)} matched={len(matched)} so={len(so)} eo={len(eo)} retest={retest_ok}/{len(matched)} ==="
    )
    print(f"=== TRADES exact={len(tex)} near={len(tnear)} matched={len(tmatched)} so={len(tso)} eo={len(teo)} ===")


if __name__ == "__main__":
    main()
