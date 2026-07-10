#!/usr/bin/env python3
"""Compare NVDA engine vs sheet trade log (entry = purchase day)."""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

SHEET_RAW = """
1/2/2019	$3.34	2/15/2019	$4.07	21.86%	44	WIN	$10,381.74
3/8/2019	$3.79	3/21/2019	$4.59	21.00%	13	WIN	$9,975.00
4/3/2019	$4.70	4/26/2019	$4.39	-6.60%	23	LOSS	-$3,135.00
5/6/2019	$4.45	5/9/2019	$4.16	-6.60%	3	LOSS	-$3,135.00
6/6/2019	$3.60	7/23/2019	$4.36	21.00%	47	WIN	$9,975.00
7/26/2019	$4.37	8/1/2019	$4.08	-6.60%	6	LOSS	-$3,135.00
8/21/2019	$4.29	8/28/2019	$4.01	-6.60%	7	LOSS	-$3,135.00
9/13/2019	$4.47	11/25/2019	$5.41	21.00%	73	WIN	$9,975.00
12/24/2019	$5.97	2/14/2020	$7.22	21.00%	52	WIN	$9,975.00
2/24/2020	$6.91	2/25/2020	$6.45	-6.60%	1	LOSS	-$3,135.00
2/28/2020	$6.92	3/6/2020	$6.46	-6.60%	7	LOSS	-$3,135.00
3/23/2020	$5.73	4/7/2020	$6.93	21.00%	15	WIN	$9,975.00
4/8/2020	$6.80	5/15/2020	$8.23	21.00%	37	WIN	$9,975.00
6/29/2020	$9.31	8/5/2020	$11.27	21.00%	37	WIN	$9,975.00
9/24/2020	$12.45	2/11/2021	$15.06	21.00%	140	WIN	$9,975.00
2/23/2021	$14.12	3/3/2021	$13.19	-6.60%	8	LOSS	-$3,135.00
3/17/2021	$13.14	3/25/2021	$12.27	-6.60%	8	LOSS	-$3,135.00
11/23/2021	$31.46	12/6/2021	$29.38	-6.60%	13	LOSS	-$3,135.00
1/24/2022	$22.55	2/24/2022	$21.02	-6.78%	31	LOSS	-$3,222.84
5/2/2022	$19.40	5/6/2022	$18.12	-6.60%	4	LOSS	-$3,135.00
5/19/2022	$17.33	5/20/2022	$16.19	-6.60%	1	LOSS	-$3,135.00
6/14/2022	$16.10	6/30/2022	$15.04	-6.60%	16	LOSS	-$3,135.00
7/5/2022	$15.01	7/29/2022	$18.16	21.00%	24	WIN	$9,975.00
9/30/2022	$12.35	10/10/2022	$11.53	-6.60%	10	LOSS	-$3,135.00
10/13/2022	$12.06	10/14/2022	$11.26	-6.60%	1	LOSS	-$3,135.00
10/17/2022	$12.34	11/10/2022	$14.93	21.00%	24	WIN	$9,975.00
12/12/2022	$18.53	12/15/2022	$17.15	-7.45%	3	LOSS	-$3,537.51
2/13/2023	$21.58	3/17/2023	$26.11	21.00%	32	WIN	$9,975.00
4/5/2023	$26.58	5/25/2023	$38.52	44.92%	50	WIN	$21,337.47
8/18/2023	$44.49	9/21/2023	$41.55	-6.60%	34	LOSS	-$3,135.00
10/4/2023	$44.05	10/20/2023	$41.14	-6.60%	16	LOSS	-$3,135.00
11/16/2023	$49.52	12/1/2023	$46.25	-6.60%	15	LOSS	-$3,135.00
12/12/2023	$47.63	1/19/2024	$57.99	21.75%	38	WIN	$10,331.72
4/25/2024	$83.82	5/23/2024	$102.03	21.73%	28	WIN	$10,319.43
7/12/2024	$130.56	7/17/2024	$121.35	-7.05%	5	LOSS	-$3,350.76
8/21/2024	$130.02	8/29/2024	$121.36	-6.66%	8	LOSS	-$3,163.74
10/16/2024	$139.34	12/17/2024	$129.09	-7.36%	62	LOSS	-$3,494.15
1/30/2025	$123.78	2/3/2025	$114.75	-7.30%	4	LOSS	-$3,465.22
2/28/2025	$123.51	3/3/2025	$115.36	-6.60%	3	LOSS	-$3,135.00
3/7/2025	$109.90	4/3/2025	$102.65	-6.60%	27	LOSS	-$3,135.00
4/11/2025	$114.11	4/16/2025	$104.55	-8.38%	5	LOSS	-$3,979.49
4/29/2025	$104.47	5/13/2025	$126.41	21.00%	14	WIN	$9,975.00
6/12/2025	$142.48	7/17/2025	$172.40	21.00%	35	WIN	$9,975.00
8/20/2025	$174.85	10/29/2025	$211.57	21.00%	70	WIN	$9,975.00
11/7/2025	$195.11	11/14/2025	$182.23	-6.60%	7	LOSS	-$3,135.00
"""


def parse_mdy(s: str) -> str:
    s = s.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    dt = pd.to_datetime(s, errors="coerce")
    return "" if pd.isna(dt) else dt.strftime("%Y-%m-%d")


def parse_money(s: str) -> float:
    return float(re.sub(r"[^0-9.\-]", "", str(s)))


def load_sheet() -> pd.DataFrame:
    rows = []
    for line in SHEET_RAW.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        rows.append(
            {
                # Sheet "Entry Date" = trigger day D; entry price = open on D+1
                "trigger_d": parse_mdy(parts[0]),
                "entry_px": parse_money(parts[1]),
                "exit_d": parse_mdy(parts[2]),
                "exit_px": parse_money(parts[3]),
                "pnl_pct": parse_money(parts[4]),
                "days": int(parts[5]),
                "result": parts[6],
            }
        )
    return pd.DataFrame(rows)


def next_td(iso: list[str], d: str) -> str:
    return iso[iso.index(d) + 1]


def norm_exit(t: str) -> str:
    t = str(t).upper()
    if "GAP" in t and "UP" in t:
        return "GAP_UP"
    if "GAP" in t and "DOWN" in t:
        return "GAP_DOWN"
    if "TARGET" in t:
        return "TARGET"
    if "STOP" in t:
        return "STOP_LOSS"
    return t


def classify(row: dict, eng_row: pd.Series | None, purch: str) -> tuple[str, str]:
    if eng_row is None:
        return "sheet_only", "no engine purchase on trigger+1"
    ep = abs(float(eng_row.ENTRY_PRICE) - row["entry_px"])
    xp = abs(float(eng_row.EXIT_PRICE) - row["exit_px"])
    ed = (pd.Timestamp(eng_row.close_d) - pd.Timestamp(row["exit_d"])).days
    dd = abs(int(eng_row.DAYS_HELD) - int(row["days"]))
    pp = abs(float(str(eng_row.PNL_PCT).replace("%", "")) - row["pnl_pct"])
    cad = str(eng_row.CLOSE_ABOVE_DATE)[:10] if pd.notna(eng_row.CLOSE_ABOVE_DATE) else ""
    cad_ok = cad == row["trigger_d"]
    if ep < 0.03 and xp < 0.08 and abs(ed) <= 2 and dd <= 3 and pp < 2.0 and cad_ok:
        return "exact", ""
    if ep < 0.05 and abs(ed) <= 5 and cad_ok:
        return "partial", f"entry_d={ep:.2f} exit_d={ed}d exit_px={xp:.2f} pnl_d={pp:.1f} days_d={dd} cad={cad}"
    if ep < 0.05 and abs(ed) <= 5:
        return "partial", f"entry_d={ep:.2f} exit_d={ed}d exit_px={xp:.2f} pnl_d={pp:.1f} days_d={dd} cad={cad} (CAD!=trigger)"
    return "mismatch", f"entry_d={ep:.2f} exit_d={ed}d exit_px={xp:.2f} pnl_d={pp:.1f} days_d={dd} cad={cad}"


def _closed_path(run_id: str) -> Path:
    for sub in ("drive", "Drive"):
        p = ROOT / sub / f"YH_Closed_{run_id}.csv"
        if p.exists():
            return p
    return ROOT / "Drive" / f"YH_Closed_{run_id}.csv"


def main() -> None:
    run_id = sys.argv[1] if len(sys.argv) > 1 else ""
    if not run_id:
        runs = []
        for sub in ("drive", "Drive"):
            d = ROOT / sub
            if d.is_dir():
                runs.extend(d.glob("YH_Closed_*.csv"))
        runs = sorted(runs, key=lambda p: p.stat().st_mtime, reverse=True)
        run_id = runs[0].stem.replace("YH_Closed_", "") if runs else ""
    print(f"Run: {run_id}")

    eng = pd.read_csv(_closed_path(run_id))
    eng = eng[eng["SYMBOL"] == "NVDA"].copy()
    eng["open_d"] = pd.to_datetime(eng["DATE_OPENED"].astype(str), format="%Y%m%d")
    eng["close_d"] = pd.to_datetime(eng["DATE_CLOSED"].astype(str), format="%Y%m%d")
    eng["cad"] = pd.to_datetime(eng["CLOSE_ABOVE_DATE"], errors="coerce")
    eng["purch_key"] = eng["open_d"].dt.strftime("%Y-%m-%d")
    eng["cad_key"] = eng["cad"].dt.strftime("%Y-%m-%d")
    eng = eng.sort_values("open_d")

    meta = pd.read_csv(ROOT / "data" / "newdata" / "data" / "NVDA.csv", parse_dates=["Date"])
    iso = [d.strftime("%Y-%m-%d") for d in meta.sort_values("Date")["Date"]]

    sheet = load_sheet()
    sheet["purch_d"] = sheet["trigger_d"].map(lambda d: next_td(iso, d) if d in iso else "")

    print(f"Engine NVDA trades: {len(eng)}  Sheet trades: {len(sheet)}\n")

    matched_eng: set[str] = set()
    exact = partial = sheet_only = 0
    mismatches: list[str] = []

    print("=== SHEET vs ENGINE (trigger D -> purchase D+1 join) ===")
    for _, s in sheet.iterrows():
        er = eng[eng["purch_key"] == s["purch_d"]]
        e = er.iloc[0] if len(er) else None
        if e is not None:
            matched_eng.add(s["purch_d"])
        tag, detail = classify(s.to_dict(), e, s["purch_d"])
        if tag == "exact":
            exact += 1
        elif tag == "partial":
            partial += 1
        else:
            sheet_only += 1
        if tag != "exact":
            line = (
                f"{tag:10s} sheet trig {s['trigger_d']} purch {s['purch_d']} ${s['entry_px']:.2f} "
                f"-> {s['exit_d']} ${s['exit_px']:.2f} {s['pnl_pct']:+.2f}%"
            )
            if e is not None:
                line += (
                    f" | eng {e.open_d.date()} ${float(e.ENTRY_PRICE):.2f} -> {e.close_d.date()} "
                    f"${float(e.EXIT_PRICE):.2f} {e.EXIT_TYPE} {e.PNL_PCT} CAD={e.cad_key}"
                )
            else:
                near = eng.copy()
                near["dd"] = (near["open_d"] - pd.Timestamp(s["purch_d"])).dt.days.abs()
                if len(near):
                    n = near.sort_values("dd").iloc[0]
                    line += f" | nearest eng {n.open_d.date()} (delta {int(n.dd)}d)"
            if detail:
                line += f" | {detail}"
            mismatches.append(line)

    eng_only = eng[~eng["purch_key"].isin(matched_eng)]
    print(f"\nSummary: exact={exact} partial={partial} sheet_only={sheet_only} eng_only={len(eng_only)}")
    print(f"Match rate: {exact}/{len(sheet)} exact, {exact+partial}/{len(sheet)} entry+/-5d exit\n")

    if mismatches:
        print("Non-exact sheet rows:")
        for m in mismatches[:40]:
            print(" ", m)
        if len(mismatches) > 40:
            print(f"  ... +{len(mismatches)-40} more")

    if len(eng_only):
        print("\nEngine-only (no sheet entry on purchase date):")
        for _, e in eng_only.iterrows():
            print(
                f"  purch {e.open_d.date()} ${float(e.ENTRY_PRICE):.2f} -> {e.close_d.date()} "
                f"{e.EXIT_TYPE} {e.PNL_PCT}  CAD={e.cad_key}"
            )


if __name__ == "__main__":
    main()
