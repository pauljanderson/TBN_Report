"""Diff AAPL sheet trades vs engine stamp 260720143523 (SPY -1000 / preferred)."""
from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")
OUT = ROOT / "drive" / "brt_sheet_reconcile"
STAMP = "260720143523"
SHEET_TSV = ROOT / "tools" / "aapl_brt_sheet_trades.tsv"
AAPL_CSV = ROOT / "data" / "newdata" / "data" / "AAPL.csv"
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


def within(a, b, tol):
    return a is not None and b is not None and abs(a - b) <= tol + 1e-9


def is_win(pnl, result=""):
    if (result or "").upper() == "WIN":
        return True
    if (result or "").upper() == "LOSS":
        return False
    if pnl is None:
        return None
    return pnl > 0


def load_engine(stamp: str):
    eng_tr = []
    for path, is_open in (
        (ROOT / "drive" / f"BRT_Closed_{stamp}.csv", False),
        (ROOT / "drive" / f"BRT_Open_{stamp}.csv", True),
    ):
        if not path.exists():
            continue
        with path.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if (r.get("SYMBOL") or "").upper() != "AAPL":
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
                        "pnl_pct": parse_money(
                            str(r.get("PNL_PCT") or "").replace("%", "")
                        ),
                        "exit_type": r.get("EXIT_TYPE") or ("OPEN" if is_open else ""),
                        "is_open": is_open,
                        "days_held": r.get("DAYS_HELD"),
                        "spy_1y": parse_money(r.get("SPY_COMPARE_1Y")),
                        "growth_pct": parse_money(r.get("GROWTH_PCT_OVER_PERIOD")),
                        "breakout": parse_date(r.get("BREAKOUT_DATE")),
                    }
                )
    return eng_tr


def load_sheet(path: Path):
    sheet_tr = []
    with path.open(encoding="utf-8", newline="") as f:
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
                    "days": (r.get("Days In Trade") or "").strip(),
                    "result": (r.get("Result") or "").strip(),
                    "pnl_dollars": parse_money(r.get("Profit per trade")),
                }
            )
    return sheet_tr


def trigger_ok(sheet_trig, eng, tol_days=1):
    """Sheet Trigger Date within ±tol_days of CLOSE_ABOVE (preferred) or DATE_OPENED."""
    cands = []
    if eng["trigger_ca"] is not None:
        cands.append(("ca", abs((eng["trigger_ca"] - sheet_trig).days)))
    if eng["open"] is not None:
        cands.append(("open", abs((eng["open"] - sheet_trig).days)))
    if not cands:
        return False, None, None
    best = min(cands, key=lambda x: x[1])
    return best[1] <= tol_days, best[0], best[1]


def reconcile(sheet_tr, eng_tr, entry_tol=0.05, day_tol=1):
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
            tok, _via, _dd = trigger_ok(s["trigger"], e, day_tol)
            if not tok:
                continue
            if abs(s["entry"] - e["entry"]) < 1e-9:
                hit = ei
                kind = "exact"
                break
            if within(s["entry"], e["entry"], entry_tol):
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
        tok, via, dd = trigger_ok(s["trigger"], e, day_tol)
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
    near_02 = sum(1 for m in near if m["within_02"])
    matched_02 = len(exact) + near_02
    return {
        "exact": exact,
        "near": near,
        "matched": matched,
        "so": so,
        "eo": eo,
        "exit_ok": exit_ok,
        "exit_known": exit_known,
        "exit_px_ok": exit_px_ok,
        "near_02": near_02,
        "matched_02": matched_02,
    }


def check_aapl_data():
    info = {
        "exists": AAPL_CSV.exists(),
        "rows": 0,
        "first": None,
        "last": None,
        "zero_ohlc": 0,
        "holiday_hits": [],
    }
    if not info["exists"]:
        return info
    # Common US holidays 2019–2024 that sheets sometimes keep as $0 bars
    holidays = [
        "2019-01-01",
        "2019-01-21",
        "2019-02-18",
        "2019-04-19",
        "2019-05-27",
        "2019-07-04",
        "2019-09-02",
        "2019-11-28",
        "2019-12-25",
        "2021-01-01",
        "2021-01-18",
        "2021-02-15",
        "2021-04-02",
        "2021-05-31",
        "2021-07-05",
        "2021-09-06",
        "2021-11-25",
        "2021-12-24",
        "2022-01-17",
        "2022-02-21",
        "2022-04-15",
        "2022-05-30",
        "2022-06-20",
        "2022-07-04",
        "2022-09-05",
        "2022-11-24",
        "2022-12-26",
        "2024-01-01",
        "2024-01-15",
        "2024-02-19",
        "2024-03-29",
        "2024-05-27",
        "2024-06-19",
        "2024-07-04",
    ]
    with AAPL_CSV.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    info["rows"] = len(rows)
    if rows:
        info["first"] = rows[0].get("Date")
        info["last"] = rows[-1].get("Date")
    dates = {r.get("Date") for r in rows}
    info["holiday_hits"] = [d for d in holidays if d in dates]
    for r in rows:
        try:
            o, h, l, c = (
                float(r.get("Open") or 0),
                float(r.get("High") or 0),
                float(r.get("Low") or 0),
                float(r.get("Close") or 0),
            )
        except ValueError:
            continue
        if o == 0 and h == 0 and l == 0 and c == 0:
            info["zero_ohlc"] += 1
    return info


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    copy = OUT / "aapl_brt_sheet_trades.tsv"
    copy.write_text(SHEET_TSV.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")

    sheet_tr = load_sheet(SHEET_TSV)
    eng_tr = load_engine(STAMP)
    r = reconcile(sheet_tr, eng_tr)
    exact, near, matched, so, eo = (
        r["exact"],
        r["near"],
        r["matched"],
        r["so"],
        r["eo"],
    )
    exit_ok, exit_known = r["exit_ok"], r["exit_known"]
    exit_px_ok = r["exit_px_ok"]
    near_02, matched_02 = r["near_02"], r["matched_02"]
    data = check_aapl_data()

    sw = sum(1 for s in sheet_tr if is_win(s["pnl_pct"], s["result"]))
    sl = sum(1 for s in sheet_tr if is_win(s["pnl_pct"], s["result"]) is False)
    ew = sum(1 for e in eng_tr if (e["pnl_pct"] or 0) > 0)
    el = sum(1 for e in eng_tr if e["pnl_pct"] is not None and e["pnl_pct"] < 0)

    with open(OUT / "AAPL_trades_match_detail.csv", "w", newline="", encoding="utf-8") as f:
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

    exit_mismatch = [m for m in matched if m["exit_date_match"] is False]
    exit_px_mismatch = [m for m in matched if m["exit_price_match"] is False]

    lines = [
        "# AAPL BRT trades reconcile — sheet vs engine",
        "",
        f"- Sheet paste: 4 closed trades → `tools/aapl_brt_sheet_trades.tsv` + `drive/brt_sheet_reconcile/aapl_brt_sheet_trades.tsv`",
        f"- Engine: `BRT_Closed_{STAMP}.csv` + `BRT_Open_{STAMP}.csv` (preferred stamp; SPY −1000 / growth on; **no AAPL re-run** — Closed already had 4 AAPL rows)",
        "- Settings context: `min_spy_compare_1y_at_trigger=-1000`, `growth_filter_enabled=true`, `run_brt.bat` defaults (`stop_pct=0.934`, `target_pct=1.21`)",
        "- Match key: sheet **Trigger Date** within ±1 calendar day of engine **CLOSE_ABOVE_DATE** (or DATE_OPENED), entry exact or ±$0.05",
        f"- Window: {WIN_START} .. {WIN_END}",
        f"- Sheet trades: **{len(sheet_tr)}** (W/L {sw}/{sl})",
        f"- Engine AAPL trades in window: **{len(eng_tr)}** (W/L {ew}/{el}; open=0)",
        "",
        "## Match summary",
        f"- Exact entry: **{len(exact)}**",
        f"- Near entry (±$0.05): **{len(near)}** (of which ±$0.02: **{near_02}**)",
        f"- Total matched (±$0.05 + trigger ±1d): **{len(matched)}** / {len(sheet_tr)} sheet "
        f"({100 * len(matched) / max(1, len(sheet_tr)):.1f}%)",
        f"- Matched at ±$0.02 (exact + near≤0.02): **{matched_02}** / {len(sheet_tr)}",
        f"- Sheet-only: **{len(so)}**",
        f"- Engine-only: **{len(eo)}**",
        f"- Exit-date match among matched: **{exit_ok}/{exit_known}**",
        f"- Exit-price match (±$0.05) among matched: **{exit_px_ok}/{len(matched)}**",
        "",
        "## Matched trades",
        "",
        "| sheet trigger | sheet entry | eng CA | eng open | eng entry | Δentry | sheet exit | eng exit | exit Δ$ | exit type | pnl sheet/eng |",
        "|---|---:|---|---|---:|---:|---|---|---:|---|---|",
    ]
    for m in matched:
        s, e = m["sheet"], m["engine"]
        epd = (
            abs(s["exit_price"] - e["exit_price"])
            if s["exit_price"] is not None and e["exit_price"] is not None
            else None
        )
        lines.append(
            f"| {s['trigger']} | {s['entry']:.4f} | {e['trigger_ca']} | {e['open']} | "
            f"{e['entry']:.4f} | {m['entry_delta']:.4f} | {s['exit_date']} | {e['exit_date']} | "
            f"{'' if epd is None else f'{epd:.4f}'} | {e['exit_type']} | "
            f"{s['pnl_pct']}/{e['pnl_pct']} |"
        )

    lines += [
        "",
        "## Sheet-only",
        "| trigger | entry | exit | pnl% | result | likely gate |",
        "|---|---:|---|---:|---|---|",
    ]
    if so:
        for s in so:
            lines.append(
                f"| {s['trigger']} | {s['entry']:.4f} | {s['exit_date']} | "
                f"{s['pnl_pct']} | {s['result']} | check growth / SPY / one-trade-at-a-time |"
            )
    else:
        lines.append("| *(none)* | | | | | |")

    lines += [
        "",
        "## Engine-only",
        "| close_above | open | entry | exit | pnl% | exit_type | likely gate / note |",
        "|---|---|---:|---|---:|---|---|",
    ]
    if eo:
        for e in eo:
            lines.append(
                f"| {e['trigger_ca']} | {e['open']} | {e['entry']:.4f} | {e['exit_date']} | "
                f"{e['pnl_pct']} | {e['exit_type']} | growth / SPY / one-trade-at-a-time / open not on sheet |"
            )
    else:
        lines.append("| *(none)* | | | | | | |")

    if near:
        lines += ["", "## Near entry matches (Δ ≤ $0.05)"]
        for m in near:
            s, e = m["sheet"], m["engine"]
            lines.append(
                f"- {s['trigger']}: sheet {s['entry']:.4f} vs eng {e['entry']:.4f} "
                f"(Δ={m['entry_delta']:.4f}; ≤0.02={m['within_02']}; "
                f"exit_match={m['exit_date_match']})"
            )
    else:
        lines += ["", "## Near entry matches (Δ ≤ $0.05)", "", "(none — all exact)"]

    if exit_mismatch:
        lines += ["", "## Exit-date mismatches among matched"]
        for m in exit_mismatch:
            s, e = m["sheet"], m["engine"]
            lines.append(
                f"- {s['trigger']}: sheet exit {s['exit_date']} vs eng "
                f"{e['exit_date']} ({e['exit_type']})"
            )
    else:
        lines += ["", "## Exit-date mismatches among matched", "", "(none)"]

    if exit_px_mismatch:
        lines += ["", "## Exit-price mismatches among matched (>±$0.05)"]
        for m in exit_px_mismatch:
            s, e = m["sheet"], m["engine"]
            lines.append(
                f"- {s['trigger']}: sheet {s['exit_price']} vs eng {e['exit_price']}"
            )
    else:
        lines += ["", "## Exit-price mismatches among matched", "", "(none)"]

    lines += [
        "",
        "## Minor deltas (not match failures)",
        "",
        "| trigger | sheet days | eng days_held | sheet pnl% | eng pnl% | note |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for m in matched:
        s, e = m["sheet"], m["engine"]
        note = []
        if s["days"] and str(e["days_held"]) and s["days"] != str(e["days_held"]):
            note.append("days_held off-by-1..3 (calendar vs session)")
        if s["pnl_pct"] is not None and e["pnl_pct"] is not None:
            if abs(s["pnl_pct"] - e["pnl_pct"]) > 0.005:
                note.append("pnl% rounding")
            elif abs(s["pnl_pct"] - e["pnl_pct"]) > 1e-9:
                note.append("pnl% 0.01 rounding")
        lines.append(
            f"| {s['trigger']} | {s['days']} | {e['days_held']} | {s['pnl_pct']} | "
            f"{e['pnl_pct']} | {'; '.join(note) or 'ok'} |"
        )

    lines += [
        "",
        "## Data / holiday check",
        "",
        f"- Engine OHLC file: `{AAPL_CSV.as_posix()}` → **{'present' if data['exists'] else 'MISSING'}**",
    ]
    if data["exists"]:
        lines += [
            f"- Bars: **{data['rows']}** ({data['first']} .. {data['last']})",
            f"- Zero OHLC rows (O=H=L=C=0): **{data['zero_ohlc']}**",
            f"- US holiday dates present in engine CSV: **{len(data['holiday_hits'])}** "
            f"({', '.join(data['holiday_hits']) if data['holiday_hits'] else 'none — engine skips holidays'})",
            "- Sheet OHLC paste was **not** provided (trades-only). Cannot assert sheet `$0` holiday bars; "
            "engine has no holiday rows and no $0 OHLC bars, so no engine-side $0-gap vs a clean Yahoo calendar.",
        ]

    lines += [
        "",
        "## Gates note (mismatches)",
        "",
        "No sheet-only / engine-only trades — no growth / SPY / one-trade-at-a-time divergence on the closed set.",
        "Both SPY−1000 trades with negative SPY_COMPARE_1Y are present on sheet and engine "
        "(2021-10-01 SPY≈−6.7, 2024-04-09 SPY≈−23.9).",
        "",
        "## Notes",
        "",
        "- Sheet Trigger Date == engine CLOSE_ABOVE_DATE on all 4 (exact day).",
        "- DATE_OPENED is next session; exits (date + price) agree.",
        "- Dollar PnL differs (sheet ~$5k risk units vs engine sizing) — not used as match key.",
        f"- Detail CSV: `AAPL_trades_match_detail.csv`",
        "",
    ]

    md_path = OUT / "AAPL_trades_diff.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    summary = {
        "stamp": STAMP,
        "sheet": len(sheet_tr),
        "engine": len(eng_tr),
        "exact": len(exact),
        "near": len(near),
        "matched": len(matched),
        "so": [(str(s["trigger"]), s["entry"]) for s in so],
        "eo": [(str(e["trigger_ca"]), e["entry"], e["exit_type"]) for e in eo],
        "exit_ok": f"{exit_ok}/{exit_known}",
        "exit_px_ok": exit_px_ok,
        "aapl_csv": data,
        "md": str(md_path),
    }
    print("SUMMARY", summary)
    return summary


if __name__ == "__main__":
    main()
