"""Reconcile NFLX zone_low sheet trades+BOs vs MarkTen stamp 260721155448."""
from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path
from statistics import mean

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")
OUT = ROOT / "drive" / "brt_sheet_reconcile"
sys.path.insert(0, str(OUT))
from bo_parent_check import (  # noqa: E402
    DEFAULT_STOP_PCT,
    annotate_trade_match,
    index_sheet_bos_by_retest,
)

STAMP = "260721155448"
SYM = "NFLX"
ENTRY_TOL = 0.05
EXIT_PX_TOL = 0.05
SHEET_TRADES = OUT / "NFLX_zone_low_sheet_trades.csv"
SHEET_BOS = OUT / "NFLX_zone_low_sheet_breakouts.csv"


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
    return round(float(s), 4)


def within(a, b, tol):
    return a is not None and b is not None and abs(a - b) <= tol + 1e-9


def load_engine(stamp: str):
    eng = []
    for path, is_open in (
        (ROOT / "drive" / f"BRT_Closed_{stamp}.csv", False),
        (ROOT / "drive" / f"BRT_Open_{stamp}.csv", True),
    ):
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if (r.get("SYMBOL") or "").upper() != SYM:
                    continue
                eng.append(
                    {
                        "trigger_ca": parse_date(r.get("CLOSE_ABOVE_DATE")),
                        "open": parse_date(r.get("DATE_OPENED")),
                        "entry": parse_money(r.get("ENTRY_PRICE")),
                        "exit_date": parse_date(r.get("DATE_CLOSED")),
                        "exit_price": parse_money(r.get("EXIT_PRICE")),
                        "pnl_pct": parse_money(str(r.get("PNL_PCT") or "").replace("%", "")),
                        "exit_type": r.get("EXIT_TYPE") or ("OPEN" if is_open else ""),
                        "is_open": is_open,
                        "days_held": r.get("DAYS_HELD"),
                        "stop": parse_money(r.get("STOP_PRICE")),
                        "target": parse_money(r.get("TARGET_PRICE")),
                        "breakout": parse_date(r.get("BREAKOUT_DATE")),
                    }
                )
    return eng


def load_sheet_trades(path: Path):
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            rows.append(
                {
                    "trigger": parse_date(r["Trigger Date"]),
                    "entry": parse_money(r["Entry Price"]),
                    "exit_date": parse_date(r["Exit Date"]),
                    "exit_price": parse_money(r["Exit Price"]),
                    "pnl_pct": parse_money(r["Profit %"]),
                    "days": int(float(str(r["Days In Trade"]).replace(",", "") or 0)),
                    "result": (r.get("Result") or "").strip(),
                    "pnl_dollars": parse_money(r.get("Profit per trade")),
                }
            )
    return rows


def load_sheet_bos(path: Path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]


def load_eng_bos(stamp: str):
    path = ROOT / "drive" / f"BRT_breakout_and_retest_{stamp}.csv"
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("SYMBOL") or "").upper() == SYM:
                out.append(dict(r))
    return out


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


def sheet_stats(rows):
    pnls = [r["pnl_pct"] for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    wr = 100.0 * len(wins) / len(rows) if rows else 0.0
    avg = mean(pnls) if pnls else 0.0
    wl = (mean(wins) / abs(mean(losses))) if wins and losses else None
    days = mean([r["days"] for r in rows]) if rows else 0.0
    total = sum(r["pnl_dollars"] or 0.0 for r in rows)
    return wr, avg, wl, days, total


def eng_stats(rows):
    pnls = [e["pnl_pct"] for e in rows if e["pnl_pct"] is not None]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    wr = 100.0 * len(wins) / len(rows) if rows else 0.0
    avg = mean(pnls) if pnls else 0.0
    wl = (mean(wins) / abs(mean(losses))) if wins and losses else None
    days = mean([float(e["days_held"]) for e in rows if e["days_held"] not in (None, "")]) if rows else 0.0
    total = sum(50000.0 * (e["pnl_pct"] / 100.0) for e in rows if e["pnl_pct"] is not None)
    return wr, avg, wl, days, total


def main():
    sheet = load_sheet_trades(SHEET_TRADES)
    eng = load_engine(STAMP)
    sheet_bos = load_sheet_bos(SHEET_BOS)
    eng_bos = load_eng_bos(STAMP)
    bos_idx = index_sheet_bos_by_retest(sheet_bos)

    used = set()
    matched = []
    sheet_only = []
    for s in sheet:
        hit = None
        kind = None
        best = None
        best_score = None
        for ei, e in enumerate(eng):
            if ei in used:
                continue
            tok, _, _ = trigger_ok(s["trigger"], e)
            if not tok:
                continue
            if abs(s["entry"] - e["entry"]) < 1e-9:
                hit, kind = ei, "exact"
                break
            if within(s["entry"], e["entry"], ENTRY_TOL):
                score = abs(s["entry"] - e["entry"])
                if best_score is None or score < best_score:
                    best, best_score = ei, score
        if hit is None and best is not None:
            hit, kind = best, "near"
        if hit is None:
            sheet_only.append(s)
            continue
        used.add(hit)
        e = eng[hit]
        exit_date_match = s["exit_date"] == e["exit_date"] if s["exit_date"] and e["exit_date"] else None
        exit_px_match = (
            within(s["exit_price"], e["exit_price"], EXIT_PX_TOL)
            if s["exit_price"] is not None and e["exit_price"] is not None
            else None
        )
        ann = annotate_trade_match(
            sheet_trigger=s["trigger"],
            eng_breakout_date=e.get("breakout"),
            eng_stop=e.get("stop"),
            eng_ca=e.get("trigger_ca") or e.get("open"),
            sheet_bos_by_retest=bos_idx,
            eng_bos=eng_bos,
            exit_date_match=exit_date_match,
            exit_px_match=exit_px_match,
            stop_pct=DEFAULT_STOP_PCT,
            check_stop=True,
        )
        matched.append(
            {
                "sheet": s,
                "engine": e,
                "kind": kind,
                "exit_date_match": exit_date_match,
                "exit_price_match": exit_px_match,
                "ann": ann,
            }
        )
    engine_only = [eng[i] for i in range(len(eng)) if i not in used]
    closed_eng = [e for e in eng if not e["is_open"]]

    detail = OUT / "NFLX_zone_low_trades_match_detail.csv"
    with detail.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "exit_status",
                "bo_parent_status",
                "status_flags",
                "match_kind",
                "sheet_trigger",
                "sheet_entry",
                "sheet_exit",
                "sheet_exit_px",
                "sheet_pnl",
                "eng_ca",
                "eng_entry",
                "eng_exit",
                "eng_exit_px",
                "eng_exit_type",
                "eng_stop",
                "sheet_parent_bo_date",
                "sheet_parent_zone_lower",
                "eng_breakout_date",
                "eng_zone_lower",
                "bo_date_match",
                "zone_lower_match",
            ]
        )
        for m in matched:
            s, e, ann = m["sheet"], m["engine"], m["ann"]
            w.writerow(
                [
                    ann["exit_status"],
                    ann["bo_parent_status"],
                    ann["status_flags"],
                    m["kind"],
                    s["trigger"],
                    s["entry"],
                    s["exit_date"],
                    s["exit_price"],
                    s["pnl_pct"],
                    e["trigger_ca"],
                    e["entry"],
                    e["exit_date"],
                    e["exit_price"],
                    e["exit_type"],
                    e["stop"],
                    ann["sheet_parent_bo_date"],
                    ann["sheet_parent_zone_lower"],
                    ann["eng_breakout_date"],
                    ann["eng_zone_lower"],
                    ann["bo_date_match"],
                    ann["zone_lower_match"],
                ]
            )
        for s in sheet_only:
            w.writerow(["SHEET_ONLY", "", "SHEET_ONLY", "", s["trigger"], s["entry"], s["exit_date"], s["exit_price"], s["pnl_pct"]] + [""] * 12)
        for e in engine_only:
            w.writerow(
                ["ENG_ONLY", "", "ENG_ONLY", "", "", "", "", "", "", e["trigger_ca"], e["entry"], e["exit_date"], e["exit_price"], e["exit_type"], e["stop"], "", "", e.get("breakout"), "", "", ""]
            )

    swr, savg, swl, sdays, stotal = sheet_stats(sheet)
    ewr, eavg, ewl, edays, etotal = eng_stats(closed_eng)
    exit_ok = sum(1 for m in matched if m["exit_date_match"])
    exit_px_ok = sum(1 for m in matched if m["exit_price_match"])
    bo_mm = sum(1 for m in matched if "BO_PARENT_MISMATCH" in m["ann"]["status_flags"])
    zone_mm = sum(1 for m in matched if "ZONE_MISMATCH" in m["ann"]["status_flags"])
    exit_fork = sum(1 for m in matched if m["ann"]["exit_status"] == "EXIT_FORK")
    wl_s = f"{swl:.2f}" if swl is not None else "n/a"
    wl_e = f"{ewl:.2f}" if ewl is not None else "n/a"

    lines = [
        "# NFLX zone_low sheet vs engine — reconcile summary",
        "",
        f"- Sheet trades: `NFLX_zone_low_sheet_trades.csv` ({len(sheet)} closed, paste 2026-07-21 16:43)",
        f"- Sheet BOs: `NFLX_zone_low_sheet_breakouts.csv` ({len(sheet_bos)} rows)",
        f"- Engine stamp: **{STAMP}** (`stop_loss_based=zone_low`)",
        "- Match: trigger±1d + entry±$0.05; additive BO parent Retest==Trigger vs eng BREAKOUT_DATE + zone_lower ±$0.02",
        "",
        "## Match table",
        "",
        "| Layer | Sheet | Engine | Matched | Sheet-only | Engine-only | Notes |",
        "|---|---:|---:|---:|---:|---:|---|",
        f"| Trades | {len(sheet)} | {len(closed_eng)} | **{len(matched)}** | {len(sheet_only)} | {len(engine_only)} | Exit {exit_ok}/{len(matched)}; EXIT_FORK {exit_fork}; BO_PARENT_MISMATCH {bo_mm}; ZONE_MISMATCH {zone_mm} |",
        "",
        "## Portfolio stats",
        "",
        "| Source | Total Trades | Win Rate | Avg Profit % | W/L | Avg Days | Total Profit $ |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| Sheet ledger | {len(sheet)} | {swr:.1f}% | {savg:.1f}% | {wl_s} | {sdays:.1f} | ${stotal:,.2f} |",
        f"| Engine {STAMP} ($50k→$10.5k/21%) | {len(closed_eng)} | {ewr:.1f}% | {eavg:.1f}% | {wl_e} | {edays:.1f}* | ${etotal:,.2f} |",
        "",
        "## Pasteable sheet stats",
        "",
        "```",
        f"Total Trades\t{len(sheet)}",
        f"Win Rate\t{swr:.1f}%",
        f"Average Profit %\t{savg:.1f}%",
        f"Win/Loss Ratio\t{wl_s}",
        f"Average Days in Trade\t{sdays:.1f}",
        f"Total Profit\t${stotal:,.2f}",
        "```",
        "",
        "## Matched trades",
        "",
        "| trigger | entry | flags | sheet BO | sheet lo | eng BO | eng lo | sheet exit | eng exit | type |",
        "|---|---:|---|---|---:|---|---:|---|---|---|",
    ]
    for m in matched:
        s, e, ann = m["sheet"], m["engine"], m["ann"]
        slo = f"{ann['sheet_parent_zone_lower']:.2f}" if ann["sheet_parent_zone_lower"] is not None else ""
        elo = f"{ann['eng_zone_lower']:.2f}" if ann["eng_zone_lower"] is not None else ""
        lines.append(
            f"| {s['trigger']} | {s['entry']:.2f} | `{ann['status_flags']}` | {ann['sheet_parent_bo_date']} | {slo} | "
            f"{ann['eng_breakout_date']} | {elo} | {s['exit_date']} | {e['exit_date']} | {e['exit_type']} |"
        )

    lines += ["", "## Issues", ""]
    issues = [
        m
        for m in matched
        if m["ann"]["exit_status"] != "FULL" or m["ann"]["bo_parent_status"] != "OK"
    ]
    if sheet_only or engine_only or issues:
        for m in issues:
            s, e, ann = m["sheet"], m["engine"], m["ann"]
            lines.append(
                f"- **{s['trigger']}** `{ann['status_flags']}`: sheetBO {ann['sheet_parent_bo_date']}/{ann['sheet_parent_zone_lower']} "
                f"vs engBO {ann['eng_breakout_date']}/{ann['eng_zone_lower']}; "
                f"exit sheet {s['exit_date']}@{s['exit_price']} vs eng {e['exit_date']}@{e['exit_price']} {e['exit_type']}"
            )
        for s in sheet_only:
            lines.append(f"- SHEET_ONLY {s['trigger']} @ {s['entry']}")
        for e in engine_only:
            lines.append(f"- ENG_ONLY {e['trigger_ca']} @ {e['entry']} {e['exit_type']}")
    else:
        lines.append("(none)")

    lines += [
        "",
        "## Artifacts",
        "",
        "- `NFLX_zone_low_sheet_trades.csv`",
        "- `NFLX_zone_low_sheet_breakouts.csv`",
        "- `NFLX_zone_low_trades_match_detail.csv`",
        "- `NFLX_zone_low_reconcile_summary.md`",
        "",
    ]
    summary = OUT / "NFLX_zone_low_reconcile_summary.md"
    summary.write_text("\n".join(lines), encoding="utf-8")

    print(f"NFLX zone_low: matched={len(matched)}/{len(sheet)} so={len(sheet_only)} eo={len(engine_only)}")
    print(f"EXIT_FORK={exit_fork} BO_PARENT_MISMATCH={bo_mm} ZONE_MISMATCH={zone_mm}")
    print(f"SHEET: n={len(sheet)} wr={swr:.1f}% avg={savg:.1f}% wlr={wl_s} days={sdays:.1f} $=${stotal:,.2f}")
    for m in issues:
        ann = m["ann"]
        print(ann["status_flags"], m["sheet"]["trigger"], ann["sheet_parent_bo_date"], ann["eng_breakout_date"])
    for s in sheet_only:
        print("SHEET_ONLY", s["trigger"])
    for e in engine_only:
        print("ENG_ONLY", e["trigger_ca"])
    print("wrote", detail)
    print("wrote", summary)


if __name__ == "__main__":
    main()
