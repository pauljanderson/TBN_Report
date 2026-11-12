"""Diff updated sheet TSLA trades (growth $0=FALSE) vs engine stamp."""
from __future__ import annotations

import csv
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")
OUT = ROOT / "drive" / "brt_sheet_reconcile"
WIN_START = datetime(2010, 1, 4).date()
WIN_END = datetime(2026, 6, 5).date()

# Prefer newest BRT_Closed stamp that has TSLA and sheet-parity knobs.
PREFERRED = "260720113551"

NEW_SHEET_TSV = """Trigger Date	Entry Price	Exit Date	Exit Price	Profit %	Days In Trade	Result	Profit per trade
2/11/2013	$2.5600	2/21/2013	$2.34	-8.79%	10	LOSS	-$4,394.53
7/19/2013	$8.0200	8/6/2013	$9.70	21.00%	18	WIN	$10,500.00
8/15/2013	$9.4700	8/26/2013	$11.46	21.00%	11	WIN	$10,500.00
8/27/2013	$11.2800	11/6/2013	$10.02	-11.15%	71	LOSS	-$5,577.04
12/9/2013	$9.33	1/15/2014	$11.29	21.00%	37	WIN	$10,500.00
4/21/2014	$13.7600	5/8/2014	$12.08	-12.23%	17	LOSS	-$6,116.93
10/30/2014	$16.1700	12/8/2014	$14.64	-9.49%	39	LOSS	-$4,744.03
12/24/2014	$14.7700	1/6/2015	$13.66	-7.55%	13	LOSS	-$3,774.27
1/29/2015	$13.5900	3/27/2015	$12.24	-9.97%	57	LOSS	-$4,983.81
4/17/2015	$13.7900	5/19/2015	$16.69	21.00%	32	WIN	$10,500.00
8/24/2015	$15.3700	2/2/2016	$12.14	-21.00%	162	LOSS	-$10,500.98
3/2/2016	$12.5500	3/17/2016	$15.19	21.00%	15	WIN	$10,500.00
5/2/2016	$15.8200	5/5/2016	$14.62	-7.60%	3	LOSS	-$3,801.83
5/18/2016	$14.2400	6/23/2016	$12.94	-9.16%	36	LOSS	-$4,579.00
7/1/2016	$13.9800	10/17/2016	$12.82	-8.27%	108	LOSS	-$4,135.12
10/21/2016	$13.4000	11/9/2016	$12.29	-8.27%	19	LOSS	-$4,136.42
12/22/2016	$13.8700	1/24/2017	$16.78	21.00%	33	WIN	$10,500.00
4/13/2017	$20.1800	6/8/2017	$24.42	21.00%	56	WIN	$10,500.00
1/10/2018	$22.3500	2/9/2018	$20.55	-8.06%	30	LOSS	-$4,031.32
6/1/2018	$19.62	6/14/2018	$23.74	21.00%	13	WIN	$10,500.00
7/11/2018	$21.43	7/23/2018	$19.61	-8.47%	12	LOSS	-$4,237.05
8/20/2018	$20.71	9/7/2018	$17.34	-16.27%	18	LOSS	-$8,136.17
9/21/2018	$19.90	9/28/2018	$18.02	-9.45%	7	LOSS	-$4,723.62
12/4/2018	$23.73	12/20/2018	$21.80	-8.13%	16	LOSS	-$4,066.58
12/26/2018	$21.32	3/5/2019	$18.32	-14.09%	69	LOSS	-$7,045.64
4/9/2019	$18.45	4/25/2019	$16.78	-9.03%	16	LOSS	-$4,514.96
6/19/2019	$14.87	10/24/2019	$19.89	33.76%	127	WIN	$16,879.62
11/14/2019	$23.38	12/24/2019	$28.29	21.00%	40	WIN	$10,500.00
6/17/2020	$66.87	7/2/2020	$81.43	21.77%	15	WIN	$10,886.80
12/14/2020	$214.43	1/7/2021	$259.46	21.00%	24	WIN	$10,500.00
2/23/2021	$237.28	3/5/2021	$192.71	-18.78%	10	LOSS	-$9,391.39
3/17/2021	$228.10	3/26/2021	$202.68	-11.15%	9	LOSS	-$5,572.56
4/23/2021	$247.00	4/30/2021	$222.53	-9.91%	7	LOSS	-$4,953.44
5/11/2021	$200.83	5/19/2021	$184.18	-8.29%	8	LOSS	-$4,145.30
6/16/2021	$200.63	8/13/2021	$242.76	21.00%	58	WIN	$10,500.00
8/25/2021	$236.10	10/18/2021	$285.68	21.00%	54	WIN	$10,500.00
12/17/2021	$303.57	12/27/2021	$367.32	21.00%	10	WIN	$10,500.00
1/24/2022	$304.73	1/28/2022	$265.09	-13.01%	4	LOSS	-$6,504.47
2/8/2022	$311.67	2/22/2022	$278.04	-10.79%	14	LOSS	-$5,395.13
3/8/2022	$279.83	3/23/2022	$338.59	21.00%	15	WIN	$10,500.00
5/17/2022	$248.17	5/20/2022	$226.92	-8.56%	3	LOSS	-$4,282.29
5/25/2022	$220.47	7/21/2022	$266.77	21.00%	57	WIN	$10,500.00
8/17/2022	$306.00	8/30/2022	$280.23	-8.42%	13	LOSS	-$4,211.11
9/1/2022	$281.07	10/3/2022	$248.58	-11.56%	32	LOSS	-$5,778.97
10/17/2022	$229.50	11/8/2022	$194.02	-15.46%	22	LOSS	-$7,729.85
12/8/2022	$173.84	12/13/2022	$157.90	-9.17%	5	LOSS	-$4,584.09
1/31/2023	$173.8900	2/9/2023	$210.41	$0.21	9	WIN	$10,500.00
2/22/2023	$203.9100	3/9/2023	179.123	-0.1215608847	15	LOSS	-$6,078.04
6/15/2023	$258.9200	8/16/2023	$228.0200	-0.1193418817	62	LOSS	-$5,967.09
8/18/2023	$221.5500	9/11/2023	$268.08	$0.21	24	WIN	$10,500.00
9/13/2023	$271.3200	9/22/2023	250.405	-0.07708462332	9	LOSS	-$3,854.23
10/23/2023	$216.5000	12/27/2023	$261.97	$0.21	65	WIN	$10,500.00
8/21/2024	$223.8200	8/28/2024	204.415	-0.08669806094	7	LOSS	-$4,334.90
9/27/2024	$259.0400	10/10/2024	237.348	-0.08373965411	13	LOSS	-$4,186.98
12/13/2024	$441.0900	1/2/2025	388.273	-0.1197416854	20	LOSS	-$5,987.08
1/17/2025	$432.6400	1/27/2025	392.047	-0.09382743158	10	LOSS	-$4,691.37
2/6/2025	$370.1900	2/11/2025	339.210	-0.08368643129	5	LOSS	-$4,184.32
3/4/2025	$272.9200	3/10/2025	244.559	-0.1039185109	6	LOSS	-$5,195.93
7/1/2025	$312.6300	9/12/2025	$378.28	$0.21	73	WIN	$10,500.00
9/26/2025	$444.3500	11/14/2025	$386.3000	-0.1306402611	49	LOSS	-$6,532.01
12/12/2025	$469.4400	2/4/2026	412.520	-0.1212513207	54	LOSS	-$6,062.57
2/13/2026	$412.3600	3/9/2026	383.762	-0.06935221651	24	LOSS	-$3,467.61
4/7/2026	$363.7900	5/11/2026	$440.19	$0.21	34	WIN	$10,500.00
"""


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


def pick_engine_stamp() -> str:
    """Newest BRT_Closed_* with TSLA rows; fall back to preferred."""
    stamps = []
    for p in (ROOT / "drive").glob("BRT_Closed_*.csv"):
        name = p.name
        if "_RL_" in name:
            continue
        # skip nested experiment dirs already excluded by glob on drive root
        stem = name[len("BRT_Closed_") : -len(".csv")]
        if not stem.isdigit():
            continue
        # has TSLA?
        has = False
        with p.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if (row.get("SYMBOL") or "").upper() == "TSLA":
                    has = True
                    break
        if has:
            stamps.append(stem)
    stamps.sort()
    if not stamps:
        return PREFERRED
    newest = stamps[-1]
    # Prefer newest if >= preferred; else preferred if present
    if PREFERRED in stamps and newest < PREFERRED:
        return PREFERRED
    return newest


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
                        "pnl_pct": parse_money(
                            str(r.get("PNL_PCT") or "").replace("%", "")
                        ),
                        "exit_type": r.get("EXIT_TYPE") or ("OPEN" if is_open else ""),
                        "is_open": is_open,
                        "spy1y": r.get("SPY_COMPARE_1Y"),
                        "growth": r.get("GROWTH_PCT_OVER_PERIOD"),
                        "stop": parse_money(r.get("STOP_PRICE")),
                    }
                )
    return eng_tr


def load_sheet_from_text(text: str):
    sheet_tr = []
    reader = csv.DictReader(text.strip().splitlines(), delimiter="\t")
    for r in reader:
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
    return sheet_tr


def reconcile(sheet_tr, eng_tr):
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
    return {
        "exact": exact,
        "near": near,
        "matched": matched,
        "so": so,
        "eo": eo,
        "exit_ok": exit_ok,
        "exit_known": exit_known,
        "near_02": near_02,
        "matched_02": matched_02,
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    # Save sheet TSV
    sheet_path = ROOT / "tools" / "tsla_brt_sheet_trades.tsv"
    sheet_path.write_text(NEW_SHEET_TSV, encoding="utf-8", newline="\n")
    copy_path = OUT / "tsla_brt_sheet_trades.tsv"
    shutil.copy2(sheet_path, copy_path)

    sheet_tr = load_sheet_from_text(NEW_SHEET_TSV)
    # window filter for sheet: include all if within or note extension
    sheet_in = [s for s in sheet_tr if WIN_START <= s["trigger"] <= WIN_END]
    sheet_after = [s for s in sheet_tr if s["trigger"] > WIN_END]
    # use full sheet list for match (user asked window or full if extends)
    use_sheet = sheet_tr  # sheet ends 2026-04-07 which is in window

    stamp = pick_engine_stamp()
    # If newest is multi-symbol but preferred exists and is TSLA-focused, still use newest if it has TSLA
    eng_tr = load_engine(stamp)
    # Also compute preferred for comparison note
    pref_eng = load_engine(PREFERRED) if stamp != PREFERRED else eng_tr

    r = reconcile(use_sheet, eng_tr)
    exact, near, matched, so, eo = (
        r["exact"],
        r["near"],
        r["matched"],
        r["so"],
        r["eo"],
    )
    exit_ok, exit_known = r["exit_ok"], r["exit_known"]
    near_02, matched_02 = r["near_02"], r["matched_02"]

    sw = sum(1 for s in use_sheet if is_win(s["pnl_pct"], s["result"]))
    sl = sum(1 for s in use_sheet if is_win(s["pnl_pct"], s["result"]) is False)
    ew = sum(1 for e in eng_tr if (e["pnl_pct"] or 0) > 0)
    el = sum(1 for e in eng_tr if e["pnl_pct"] is not None and e["pnl_pct"] < 0)

    # Special checks
    def find_sheet(dstr):
        d = datetime.strptime(dstr, "%Y-%m-%d").date()
        return next((s for s in use_sheet if s["trigger"] == d), None)

    def find_eng(dstr):
        d = datetime.strptime(dstr, "%Y-%m-%d").date()
        return next((e for e in eng_tr if e["trigger_ca"] == d), None)

    def find_matched(dstr):
        d = datetime.strptime(dstr, "%Y-%m-%d").date()
        return next((m for m in matched if m["sheet"]["trigger"] == d), None)

    check_dates = ["2013-02-11", "2013-01-28", "2024-08-21", "2024-09-27", "2024-09-23"]

    # Write match detail
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

    # special status lines
    special_lines = ["## Special checks (growth-formula update)", ""]
    for dstr in check_dates:
        sm = find_matched(dstr)
        ss = find_sheet(dstr)
        ee = find_eng(dstr)
        if sm:
            special_lines.append(
                f"- **{dstr}**: MATCHED (sheet entry {sm['sheet']['entry']:.4f} / eng "
                f"{sm['engine']['entry']:.4f}, Δ={sm['entry_delta']:.4f}; "
                f"exit {'OK' if sm['exit_date_match'] else sm['exit_date_match']})"
            )
        elif ss and not ee:
            special_lines.append(
                f"- **{dstr}**: SHEET-ONLY (entry {ss['entry']:.4f}, exit {ss['exit_date']}, {ss['result']})"
            )
        elif ee and not ss:
            special_lines.append(
                f"- **{dstr}**: ENGINE-ONLY (entry {ee['entry']:.4f}, exit {ee['exit_date']}, {ee['exit_type']})"
            )
        elif not ss and not ee:
            special_lines.append(f"- **{dstr}**: absent from both")
        else:
            special_lines.append(
                f"- **{dstr}**: present both but unmatched? sheet={ss} eng={ee}"
            )
    special_lines.append("")

    lines = [
        "# TSLA trades reconcile — growth formula `$0 prior → FALSE`",
        "",
        "- Sheet paste: 2026-07-20 15:57 (growth update; first trade now **2013-02-11**, was 2013-01-28)",
        f"- Saved: `tools/tsla_brt_sheet_trades.tsv` + `drive/brt_sheet_reconcile/tsla_brt_sheet_trades.tsv`",
        f"- Engine: `BRT_Closed_{stamp}.csv` + `BRT_Open_{stamp}.csv` "
        f"(picked newest with TSLA; preferred was `{PREFERRED}`)",
        "- Settings context: `stop_loss_based=trigger_low`, `min_spy_compare_1y_at_trigger=-1000`, growth_filter on",
        "- Prior (pre growth-sheet fix, same engine `260720113551`): matched **60**/63, sheet-only **3** "
        "(2013-01-28, 2024-08-21, 2024-09-27), engine-only **2** (2024-09-23, 2026-05-19 open)",
        "- Match key: sheet **Trigger Date** == engine **CLOSE_ABOVE_DATE**, entry exact or +/- $0.05 "
        "(also report +/- $0.02)",
        f"- Window: {WIN_START} .. {WIN_END}"
        + (
            f" (sheet after-window excluded: {len(sheet_after)})"
            if sheet_after
            else " (sheet fully inside window)"
        ),
        f"- Sheet trades: **{len(use_sheet)}** (W/L {sw}/{sl}) — was 63; net −1 vs prior paste",
        f"- Engine trades in window: **{len(eng_tr)}** (W/L {ew}/{el})",
        "",
        "## Match summary",
        f"- Exact entry: **{len(exact)}**",
        f"- Near entry (+/- $0.05): **{len(near)}** (of which +/- $0.02: **{near_02}**)",
        f"- Total matched (+/- $0.05): **{len(matched)}** / {len(use_sheet)} sheet "
        f"({100 * len(matched) / max(1, len(use_sheet)):.1f}%) — prior **60**/63",
        f"- Matched at +/- $0.02 (exact + near≤0.02): **{matched_02}** / {len(use_sheet)}",
        f"- Sheet-only: **{len(so)}** (prior **3**)",
        f"- Engine-only: **{len(eo)}** (prior **2**)",
        f"- Exit-date match among matched (both have exit): **{exit_ok}/{exit_known}**",
        "",
    ]
    lines += special_lines
    lines += [
        "## Sheet-only",
        "| trigger | entry | exit | pnl% | result | note |",
        "|---|---:|---|---:|---|---|",
    ]
    notes = {
        datetime(2013, 2, 11).date(): "new first trade after growth $0→FALSE; engine never entered (growth history still short / different CA path)",
        datetime(2024, 8, 21).date(): "growth_filter — Close < Close_756_ago (unchanged)",
        datetime(2024, 9, 27).date(): "open-trade overlap twin — engine entered 2024-09-23",
    }
    for s in so:
        note = notes.get(s["trigger"], "")
        lines.append(
            f"| {s['trigger']} | {s['entry']:.4f} | {s['exit_date']} | {s['pnl_pct']} | {s['result']} | {note} |"
        )
    if not so:
        lines.append("(none)")
    lines += [
        "",
        "## Engine-only",
        "| close_above | open | entry | exit | pnl% | exit_type | note |",
        "|---|---|---:|---|---:|---|---|",
    ]
    eo_notes = {
        datetime(2024, 9, 23).date(): "twin of sheet 2024-09-27",
        datetime(2026, 5, 19).date(): "open trade; sheet window ends before / no sheet row",
    }
    for e in eo:
        note = eo_notes.get(e["trigger_ca"], "")
        lines.append(
            f"| {e['trigger_ca']} | {e['open']} | {e['entry']:.4f} | {e['exit_date']} | "
            f"{e['pnl_pct']} | {e['exit_type']} | {note} |"
        )
    if not eo:
        lines.append("(none)")

    # Near mismatches list
    if near:
        lines += ["", "## Near entry matches (Δ ≤ $0.05)"]
        for m in near:
            s, e = m["sheet"], m["engine"]
            lines.append(
                f"- {s['trigger']}: sheet {s['entry']:.4f} vs eng {e['entry']:.4f} "
                f"(Δ={m['entry_delta']:.4f}; ≤0.02={m['within_02']}; exit_match={m['exit_date_match']})"
            )

    lines += [
        "",
        "## Delta vs prior reconcile",
        "- **2013-01-28** dropped from sheet (growth formula now FALSE when prior=$0) — no longer sheet-only.",
        "- **2013-02-11** added on sheet as new first trade — check Special checks above for match status.",
        "- **2024-08-21** / **2024-09-27** expected to remain sheet-only unless engine path changed.",
        "",
        "## Notes",
        "- Sheet Trigger Date aligns with engine CLOSE_ABOVE_DATE; DATE_OPENED is typically next session.",
        "- With `stop_loss_based=trigger_low`, stop = signal-bar Low × 0.934 (sheet AM).",
        "- Engine stamp was not re-run; comparing against existing Closed/Open only.",
        "",
    ]
    (OUT / "TSLA_trades_diff.md").write_text("\n".join(lines), encoding="utf-8")
    (OUT / "TSLA_trades_diff.txt").write_text(
        f"sheet={len(use_sheet)} engine={len(eng_tr)} exact={len(exact)} near={len(near)} "
        f"near02={near_02} matched={len(matched)} matched02={matched_02} "
        f"sheet_only={len(so)} engine_only={len(eo)} "
        f"exit_ok={exit_ok}/{exit_known} eng_ts={stamp} growth0_false_update=1\n",
        encoding="utf-8",
    )

    summary = {
        "stamp": stamp,
        "sheet": len(use_sheet),
        "engine": len(eng_tr),
        "exact": len(exact),
        "near": len(near),
        "near_02": near_02,
        "matched": len(matched),
        "matched_02": matched_02,
        "so": [(str(s["trigger"]), s["entry"], str(s["exit_date"])) for s in so],
        "eo": [
            (str(e["trigger_ca"]), e["entry"], str(e["exit_date"]), e["exit_type"])
            for e in eo
        ],
        "exit_ok": exit_ok,
        "exit_known": exit_known,
        "pref_n": len(pref_eng),
        "checks": {},
    }
    for dstr in check_dates:
        sm = find_matched(dstr)
        ss = find_sheet(dstr)
        ee = find_eng(dstr)
        if sm:
            summary["checks"][dstr] = "matched"
        elif ss and not ee:
            summary["checks"][dstr] = "sheet_only"
        elif ee and not ss:
            summary["checks"][dstr] = "engine_only"
        else:
            summary["checks"][dstr] = "absent"
    print("SUMMARY", summary)
    return summary


if __name__ == "__main__":
    main()
