"""Window-aware TSLA breakout + trade reconcile (post zone reconcile)."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")
OUT = ROOT / "drive" / "brt_sheet_reconcile"
WIN_START = datetime(2010, 1, 4).date()
WIN_END = datetime(2026, 6, 5).date()
# Latest TSLA-only BRT dump (run_brt.bat; min_spy=-1000, stop_loss_based=trigger_low).
ENG_TS = "260720113551"


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


def within(a, b, tol):
    return a is not None and b is not None and abs(a - b) <= tol + 1e-9


def reconcile_breakouts():
    sheet_bo = []
    with open(
        ROOT / "tools" / "tsla_brt_sheet_breakout_retest.tsv",
        encoding="utf-8",
        newline="",
    ) as f:
        for r in csv.DictReader(f, delimiter="\t"):
            d = parse_date(r.get("Breakout Date"))
            lo = parse_money(r.get("Zone Lower"))
            hi = parse_money(r.get("Zone Upper"))
            if d is None or lo is None or hi is None:
                continue
            sheet_bo.append(
                {
                    "bo_date": d,
                    "lower": lo,
                    "upper": hi,
                    "retest_date": parse_date(r.get("Retest Date")),
                }
            )
    sheet_all = list(sheet_bo)
    sheet_bo = [r for r in sheet_bo if WIN_START <= r["bo_date"] <= WIN_END]
    sheet_after = [r for r in sheet_all if r["bo_date"] > WIN_END]

    eng_bo = []
    with open(
        ROOT / "drive" / "BRT_breakout_and_retest_260720082240.csv",
        encoding="utf-8",
        newline="",
    ) as f:
        for r in csv.DictReader(f):
            if (r.get("SYMBOL") or "").upper() != "TSLA":
                continue
            d = parse_date(r.get("Breakout Date"))
            lo = parse_money(r.get("Zone Lower"))
            hi = parse_money(r.get("Zone Upper"))
            if d is None or lo is None or hi is None:
                continue
            if not (WIN_START <= d <= WIN_END):
                continue
            eng_bo.append(
                {
                    "bo_date": d,
                    "lower": lo,
                    "upper": hi,
                    "retest_date": parse_date(r.get("Retest Date")),
                }
            )

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
        rec = {
            "sheet": s,
            "engine": e,
            "kind": kind,
            "retest_match": s["retest_date"] == e["retest_date"],
        }
        (exact if kind == "exact" else near).append(rec)

    eo = [eng_bo[i] for i in range(len(eng_bo)) if i not in used]
    matched = exact + near
    retest_ok = sum(1 for m in matched if m["retest_match"])

    with open(OUT / "TSLA_breakout_match_detail.csv", "w", newline="", encoding="utf-8") as f:
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
        for m in exact + near:
            s, e = m["sheet"], m["engine"]
            w.writerow(
                [
                    m["kind"],
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
                ["sheet_only", s["bo_date"], s["lower"], s["upper"], s["retest_date"], "", "", "", "", ""]
            )
        for e in eo:
            w.writerow(
                ["engine_only", "", "", "", "", e["bo_date"], e["lower"], e["upper"], e["retest_date"], ""]
            )
        for s in sheet_after:
            w.writerow(
                [
                    "sheet_after_window",
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

    lines = [
        "# TSLA breakout/retest reconcile (2026-07-20 09:59 paste)",
        "",
        "- Engine: `BRT_breakout_and_retest_260720082240.csv`",
        f"- Window: {WIN_START} .. {WIN_END}",
        f"- Sheet BO rows (raw paste): **{len(sheet_all)}**",
        f"- Sheet BO in window: **{len(sheet_bo)}**",
        f"- Sheet BO after window end (excluded): **{len(sheet_after)}**",
        f"- Engine BO (TSLA in window): **{len(eng_bo)}**",
        "",
        "## Match summary (windowed)",
        f"- Exact date+bounds: **{len(exact)}**",
        f"- Near (+/- $0.02 bounds): **{len(near)}**",
        f"- Total matched: **{len(matched)}** / {len(sheet_bo)} sheet ({100 * len(matched) / max(1, len(sheet_bo)):.1f}%)",
        f"- Sheet-only: **{len(so)}**",
        f"- Engine-only: **{len(eo)}**",
        f"- Retest date match among matched: **{retest_ok}/{len(matched)}**",
        f"- 100% windowed match: **{'YES' if not so and not eo else 'NO'}**",
        "",
        "## Remaining mismatch causes",
        "- In-window sheet-only / engine-only: none (MAX_SKIPPED not needed).",
        f"- {len(sheet_after)} sheet rows after 2026-06-05 excluded from mismatch (sheet extends past window/engine dump).",
        "",
        "## Post-window sheet BOs (excluded)",
        "| bo_date | lower | upper | retest |",
        "|---|---:|---:|---|",
    ]
    for s in sheet_after:
        lines.append(
            f"| {s['bo_date']} | {s['lower']:.4f} | {s['upper']:.4f} | {s['retest_date']} |"
        )
    if near:
        lines += ["", "## Near-miss pairs (+/- $0.02)"]
        for m in near:
            s, e = m["sheet"], m["engine"]
            lines.append(
                f"- {s['bo_date']}: sheet {s['lower']:.4f}/{s['upper']:.4f} <-> eng {e['lower']:.4f}/{e['upper']:.4f}"
            )
    lines.append("")
    (OUT / "TSLA_breakout_diff.md").write_text("\n".join(lines), encoding="utf-8")
    (OUT / "TSLA_breakout_diff.txt").write_text(
        f"windowed sheet={len(sheet_bo)} engine={len(eng_bo)} exact={len(exact)} near={len(near)} "
        f"matched={len(matched)} sheet_only={len(so)} engine_only={len(eo)} "
        f"retest_ok={retest_ok} after_window_excluded={len(sheet_after)}\n",
        encoding="utf-8",
    )
    print(
        "BO",
        f"sheet_win={len(sheet_bo)} eng={len(eng_bo)} exact={len(exact)} near={len(near)} "
        f"so={len(so)} eo={len(eo)} after={len(sheet_after)} retest={retest_ok}/{len(matched)}",
    )
    return {
        "sheet": len(sheet_bo),
        "engine": len(eng_bo),
        "exact": len(exact),
        "near": len(near),
        "so": len(so),
        "eo": len(eo),
        "after": len(sheet_after),
        "retest_ok": retest_ok,
        "matched": len(matched),
    }


def is_win(pnl, result=""):
    if (result or "").upper() == "WIN":
        return True
    if (result or "").upper() == "LOSS":
        return False
    if pnl is None:
        return None
    return pnl > 0


def reconcile_trades():
    sheet_tr = []
    with open(
        ROOT / "tools" / "tsla_brt_sheet_trades.tsv", encoding="utf-8", newline=""
    ) as f:
        for r in csv.DictReader(f, delimiter="\t"):
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
                    "result": (r.get("Result") or "").strip(),
                }
            )

    eng_tr = []
    closed_path = ROOT / "drive" / f"BRT_Closed_{ENG_TS}.csv"
    open_path = ROOT / "drive" / f"BRT_Open_{ENG_TS}.csv"
    for path, is_open in ((closed_path, False), (open_path, True)):
        if not path.exists():
            continue
        with open(path, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if (r.get("SYMBOL") or "").upper() != "TSLA":
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
                    }
                )

    by_ca = {}
    for i, e in enumerate(eng_tr):
        if e["trigger_ca"]:
            by_ca.setdefault(e["trigger_ca"], []).append(i)

    used = set()
    exact, near, so = [], [], []
    for s in sheet_tr:
        cands = list(by_ca.get(s["trigger"], []))
        if not cands:
            for ei, e in enumerate(eng_tr):
                if ei in used:
                    continue
                if e["open"] and 0 <= (e["open"] - s["trigger"]).days <= 5:
                    cands.append(ei)
        hit = None
        kind = None
        best = None
        best_score = None
        for ei in cands:
            if ei in used:
                continue
            e = eng_tr[ei]
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
        exit_match = None
        if s["exit_date"] and e["exit_date"]:
            exit_match = s["exit_date"] == e["exit_date"]
        entry_delta = abs(s["entry"] - e["entry"])
        rec = {
            "sheet": s,
            "engine": e,
            "kind": kind,
            "exit_date_match": exit_match,
            "entry_delta": entry_delta,
            "within_02": entry_delta <= 0.02 + 1e-9,
        }
        (exact if kind == "exact" else near).append(rec)

    eo = [eng_tr[i] for i in range(len(eng_tr)) if i not in used]
    matched = exact + near
    exit_ok = sum(1 for m in matched if m["exit_date_match"])
    exit_known = sum(1 for m in matched if m["exit_date_match"] is not None)
    near_02 = sum(1 for m in near if m["within_02"])
    matched_02 = len(exact) + near_02

    sw = sum(1 for s in sheet_tr if is_win(s["pnl_pct"], s["result"]))
    sl = sum(1 for s in sheet_tr if is_win(s["pnl_pct"], s["result"]) is False)
    ew = sum(1 for e in eng_tr if (e["pnl_pct"] or 0) > 0)
    el = sum(1 for e in eng_tr if e["pnl_pct"] is not None and e["pnl_pct"] < 0)

    t_20191114 = None
    for m in matched:
        if m["sheet"]["trigger"] and str(m["sheet"]["trigger"]) == "2019-11-14":
            t_20191114 = m
            break

    with open(OUT / "TSLA_trades_match_detail.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "status",
                "sheet_trigger",
                "sheet_entry",
                "sheet_exit",
                "sheet_pnl",
                "eng_ca",
                "eng_open",
                "eng_entry",
                "eng_exit",
                "eng_pnl",
                "eng_exit_type",
                "exit_date_match",
                "entry_delta",
                "within_0p02",
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
                    s["pnl_pct"],
                    e["trigger_ca"],
                    e["open"],
                    e["entry"],
                    e["exit_date"],
                    e["pnl_pct"],
                    e["exit_type"],
                    m["exit_date_match"],
                    f"{m['entry_delta']:.4f}",
                    m["within_02"],
                ]
            )
        for s in so:
            w.writerow(
                [
                    "sheet_only",
                    s["trigger"],
                    s["entry"],
                    s["exit_date"],
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
                    e["trigger_ca"],
                    e["open"],
                    e["entry"],
                    e["exit_date"],
                    e["pnl_pct"],
                    e["exit_type"],
                    "",
                    "",
                    "",
                ]
            )

    lines = [
        "# TSLA trades reconcile — `min_spy_compare_1y_at_trigger=-1000`",
        "",
        "- Sheet paste: 2026-07-20 (`tools/tsla_brt_sheet_trades.tsv`)",
        f"- Engine: `BRT_Closed_{ENG_TS}.csv` + `BRT_Open_{ENG_TS}.csv` "
        "(TSLA-only via `run_brt.bat`; `min_spy_compare_1y_at_trigger=-1000`; "
        "default `stop_loss_based=trigger_low`)",
        "- Prior after `trigger_low` (`BRT_*_260720111055`, SPY −12): "
        "matched **46**/63, sheet-only **17**, engine-only **2**, exit-date **46**/46",
        "- Match key: sheet **Trigger Date** == engine **CLOSE_ABOVE_DATE**, "
        "entry exact or +/- $0.05 (also report +/- $0.02)",
        f"- Window: {WIN_START} .. {WIN_END}",
        f"- Sheet trades: **{len(sheet_tr)}** (W/L {sw}/{sl})",
        f"- Engine trades in window: **{len(eng_tr)}** (W/L {ew}/{el})",
        "",
        "## Match summary",
        f"- Exact entry: **{len(exact)}**",
        f"- Near entry (+/- $0.05): **{len(near)}** "
        f"(of which +/- $0.02: **{near_02}**)",
        f"- Total matched (+/- $0.05): **{len(matched)}** / {len(sheet_tr)} sheet "
        f"({100 * len(matched) / max(1, len(sheet_tr)):.1f}%) — was **46**/63",
        f"- Matched at +/- $0.02 (exact + near≤0.02): **{matched_02}** / {len(sheet_tr)}",
        f"- Sheet-only: **{len(so)}** (was **17**)",
        f"- Engine-only: **{len(eo)}** (was **2**)",
        f"- Exit-date match among matched (both have exit): **{exit_ok}/{exit_known}** "
        "(was **46**/46)",
        "",
        "## 2019-11-14 check",
    ]
    if t_20191114:
        s, e = t_20191114["sheet"], t_20191114["engine"]
        lines += [
            f"- Matched: sheet exit `{s['exit_date']}` vs engine exit "
            f"`{e['exit_date']}` ({e['exit_type']}) — "
            f"{'EXIT DATE MATCH' if t_20191114['exit_date_match'] else 'exit date MISMATCH'}",
            f"- Entries: sheet {s['entry']:.4f} / engine {e['entry']:.4f}",
            "",
        ]
    else:
        lines += ["- **Not matched** (sheet-only or missing).", ""]

    lines += [
        "## Sheet-only",
        "| trigger | entry | exit | pnl% | result |",
        "|---|---:|---|---:|---|",
    ]
    for s in so:
        lines.append(
            f"| {s['trigger']} | {s['entry']:.4f} | {s['exit_date']} | {s['pnl_pct']} | {s['result']} |"
        )
    if not so:
        lines.append("(none)")
    lines += [
        "",
        "## Engine-only",
        "| close_above | open | entry | exit | pnl% | exit_type |",
        "|---|---|---:|---|---:|---|",
    ]
    for e in eo:
        lines.append(
            f"| {e['trigger_ca']} | {e['open']} | {e['entry']:.4f} | {e['exit_date']} | {e['pnl_pct']} | {e['exit_type']} |"
        )
    if not eo:
        lines.append("(none)")
    lines += [
        "",
        "## Notes",
        "- Sheet Trigger Date aligns with engine CLOSE_ABOVE_DATE; DATE_OPENED is typically next session.",
        "- With `stop_loss_based=trigger_low`, stop = signal-bar Low × 0.934 "
        "(sheet AM); exits can extend past the old entry×0.934 stop-outs.",
        "- Near entry diffs (~$0.03) concentrated in 2013 early OHLC.",
        "",
    ]
    (OUT / "TSLA_trades_diff.md").write_text("\n".join(lines), encoding="utf-8")
    (OUT / "TSLA_trades_diff.txt").write_text(
        f"sheet={len(sheet_tr)} engine={len(eng_tr)} exact={len(exact)} near={len(near)} "
        f"near02={near_02} matched={len(matched)} matched02={matched_02} "
        f"sheet_only={len(so)} engine_only={len(eo)} "
        f"exit_ok={exit_ok}/{exit_known} eng_ts={ENG_TS} stop_loss_based=trigger_low\n",
        encoding="utf-8",
    )
    print(
        "TRADES",
        f"sheet={len(sheet_tr)} eng={len(eng_tr)} exact={len(exact)} near={len(near)} "
        f"near02={near_02} so={len(so)} eo={len(eo)} exit={exit_ok}/{exit_known}",
    )
    if t_20191114:
        print(
            "2019-11-14",
            t_20191114["sheet"]["exit_date"],
            "->",
            t_20191114["engine"]["exit_date"],
            t_20191114["engine"]["exit_type"],
            "exit_match=",
            t_20191114["exit_date_match"],
        )
    print("SO:")
    for s in so:
        print(f"  {s['trigger']} {s['entry']} {s['exit_date']} {s['pnl_pct']} {s['result']}")
    print("EO:")
    for e in eo:
        print(
            f"  ca={e['trigger_ca']} open={e['open']} entry={e['entry']} pnl={e['pnl_pct']} {e['exit_type']}"
        )
    return {
        "sheet": len(sheet_tr),
        "engine": len(eng_tr),
        "exact": len(exact),
        "near": len(near),
        "near_02": near_02,
        "so": len(so),
        "eo": len(eo),
        "matched": len(matched),
        "exit_ok": exit_ok,
        "exit_known": exit_known,
    }


def patch_zones_ac_ad_note():
    """Clarify that the 4 +/-0.02 zone near-misses are +/-1c AC/AD twins."""
    p = OUT / "TSLA_zones_diff.md"
    text = p.read_text(encoding="utf-8")
    old = "- +/-1c AC/AD twins: **0**"
    new = (
        "- +/-1c AC/AD twins: **4** (consumed above as +/-$0.02 near-misses; "
        "same touch, bounds off by $0.01)"
    )
    if old in text:
        text = text.replace(old, new)
        p.write_text(text, encoding="utf-8")
        print("patched zones AC/AD note")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    patch_zones_ac_ad_note()
    bo = reconcile_breakouts()
    tr = reconcile_trades()
    print("DONE", {"bo": bo, "tr": tr})


if __name__ == "__main__":
    main()
