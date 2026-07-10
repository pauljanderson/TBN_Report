#!/usr/bin/env python3
"""Compare TSLA sheet breakout/retest export vs engine YH_breakout_and_retest CSV."""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _parse_mdy(s) -> str:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    s = str(s).strip()
    if not s:
        return ""
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def _money(x) -> float:
    if pd.isna(x):
        return float("nan")
    t = str(x).strip().replace("$", "").replace(",", "")
    if not t:
        return float("nan")
    return float(t)


def _intish(x):
    if pd.isna(x) or str(x).strip() == "":
        return None
    return int(float(str(x).strip()))


def _load_sheet(path: Path, active_only: bool = True) -> pd.DataFrame:
    df = pd.read_csv(path, sep="\t", dtype=str)
    df.columns = [c.strip() for c in df.columns]
    df["bo_iso"] = df["Breakout Date"].map(_parse_mdy)
    df["rt_iso"] = df["Retest Date"].map(_parse_mdy)
    df["zl"] = df["Zone Lower"].map(_money).round(2)
    df["zu"] = df["Zone Upper"].map(_money).round(2)
    df["main_row"] = df["Main Row"].map(_intish)
    df["scan_row"] = df["Scan Start Row"].map(_intish)
    df["rt_row"] = df["retest Row"].map(_intish)
    if active_only and "Breakout Active" in df.columns:
        act = df["Breakout Active"].astype(str).str.strip().str.lower()
        df = df[act.isin({"1", "true", "yes"})].copy()
    df["key"] = list(zip(df["bo_iso"], df["zl"], df["zu"]))
    return df


def _load_engine(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df[df["SYMBOL"].astype(str).str.upper() == "TSLA"].copy()
    df["bo_iso"] = df["Breakout Date"].map(_parse_mdy)
    df["rt_iso"] = df["Retest Date"].map(_parse_mdy)
    df["zl"] = df["Zone Lower"].map(_money).round(2)
    df["zu"] = df["Zone Upper"].map(_money).round(2)
    df["main_row"] = df["Main Row"].map(_intish)
    df["scan_row"] = df["Scan Start Row"].map(_intish)
    df["rt_row"] = df["retest Row"].map(_intish)
    df["key"] = list(zip(df["bo_iso"], df["zl"], df["zu"]))
    return df


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", type=Path, default=ROOT / "tools" / "tsla_sheet_breakout_retest.tsv")
    ap.add_argument("--program", type=Path, default=ROOT / "drive" / "YH_breakout_and_retest_260621072339.csv")
    ap.add_argument("--include-inactive", action="store_true")
    args = ap.parse_args()

    if not args.sheet.is_file():
        print(f"ERROR: sheet not found: {args.sheet}", file=sys.stderr)
        return 2
    if not args.program.is_file():
        print(f"ERROR: program not found: {args.program}", file=sys.stderr)
        return 2

    sheet = _load_sheet(args.sheet, active_only=not args.include_inactive)
    eng = _load_engine(args.program)

    print(f"=== TSLA breakout/retest parity ===")
    print(f"Sheet rows (active): {len(sheet)}")
    print(f"Engine rows:         {len(eng)}")
    print()

    # --- Breakout phase: match on (date, zone) ---
    sk = set(sheet["key"])
    ek = set(eng["key"])
    both_keys = sk & ek
    sheet_only_keys = sk - ek
    eng_only_keys = ek - sk

    print("--- BREAKOUTS (key = breakout date + zone lo/hi) ---")
    print(f"Matched keys:     {len(both_keys)}")
    print(f"Sheet-only keys:  {len(sheet_only_keys)}")
    print(f"Engine-only keys: {len(eng_only_keys)}")
    print()

    # Main row offset when keys match
    offsets: list[int] = []
    bo_date_mism: list[str] = []
    scan_mism: list[str] = []
    for k in sorted(both_keys):
        sr = sheet[sheet["key"] == k].iloc[0]
        er = eng[eng["key"] == k].iloc[0]
        if sr["bo_iso"] != er["bo_iso"]:
            bo_date_mism.append(k[0])
        if sr["main_row"] is not None and er["main_row"] is not None:
            offsets.append(int(sr["main_row"]) - int(er["main_row"]))
        if sr["scan_row"] is not None and er["scan_row"] is not None and sr["scan_row"] != er["scan_row"]:
            scan_mism.append(f"{k[0]} z={k[1]}/{k[2]} sheet_scan={sr['scan_row']} eng={er['scan_row']}")

    if offsets:
        from collections import Counter
        oc = Counter(offsets)
        print(f"Main Row offset (sheet - engine) when zone+date match:")
        for off, cnt in oc.most_common(5):
            print(f"  {off:+d}  ({cnt} rows)")
        print()

    if sheet_only_keys:
        print(f"Sheet-only breakouts ({len(sheet_only_keys)}):")
        for k in sorted(sheet_only_keys)[:20]:
            r = sheet[sheet["key"] == k].iloc[0]
            print(f"  {r['Breakout Date']}  ${r['zl']:.2f}/{r['zu']:.2f}  MR={r['main_row']}")
        if len(sheet_only_keys) > 20:
            print(f"  ... ({len(sheet_only_keys) - 20} more)")
        print()

    if eng_only_keys:
        print(f"Engine-only breakouts ({len(eng_only_keys)}):")
        for k in sorted(eng_only_keys)[:20]:
            r = eng[eng["key"] == k].iloc[0]
            print(f"  {r['Breakout Date']}  ${r['zl']:.2f}/{r['zu']:.2f}  MR={r['main_row']}")
        if len(eng_only_keys) > 20:
            print(f"  ... ({len(eng_only_keys) - 20} more)")
        print()

    # --- Retest phase (matched breakouts only) ---
    print("--- RETESTS (matched breakouts) ---")
    rt_exact = rt_date_only = rt_row_only = rt_both_wrong = both_empty = sheet_empty_eng_has = rt_eng_empty = 0
    rt_mismatches: list[str] = []

    for k in sorted(both_keys):
        sr = sheet[sheet["key"] == k].iloc[0]
        er = eng[eng["key"] == k].iloc[0]
        s_rt_d = str(sr["rt_iso"] or "")
        e_rt_d = str(er["rt_iso"] or "")
        s_rt_r = sr["rt_row"]
        e_rt_r = er["rt_row"]

        if not s_rt_d and not e_rt_d:
            both_empty += 1
            continue
        if not s_rt_d and e_rt_d:
            sheet_empty_eng_has += 1
            if e_rt_d:
                rt_mismatches.append(f"  {sr['Breakout Date']}  sheet=no retest  engine={er['Retest Date']} row={e_rt_r}")
            continue
        if s_rt_d and not e_rt_d:
            rt_eng_empty += 1
            rt_mismatches.append(f"  {sr['Breakout Date']}  sheet={sr['Retest Date']} row={s_rt_r}  engine=no retest")
            continue

        date_ok = s_rt_d == e_rt_d
        row_ok = s_rt_r is not None and e_rt_r is not None and int(s_rt_r) == int(e_rt_r)
        if not row_ok and s_rt_r is not None and e_rt_r is not None:
            row_ok = int(s_rt_r) - int(e_rt_r) == (offsets[0] if offsets else 0)

        if date_ok and row_ok:
            rt_exact += 1
        elif date_ok:
            rt_date_only += 1
            rt_mismatches.append(
                f"  {sr['Breakout Date']}  retest DATE ok {sr['Retest Date']}  ROW sheet={s_rt_r} eng={int(e_rt_r) if e_rt_r else ''}"
            )
        elif row_ok:
            rt_row_only += 1
            rt_mismatches.append(
                f"  {sr['Breakout Date']}  retest ROW ok  sheet={sr['Retest Date']}({s_rt_r}) eng={er['Retest Date']}({int(e_rt_r)})"
            )
        else:
            rt_both_wrong += 1
            rt_mismatches.append(
                f"  {sr['Breakout Date']}  z=${sr['zl']:.2f}  sheet={sr['Retest Date']}({s_rt_r})  eng={er['Retest Date']}({int(e_rt_r) if e_rt_r else ''})"
            )

    with_retest_sheet = sum(1 for k in both_keys if sheet[sheet["key"] == k].iloc[0]["rt_iso"])
    print(f"Matched breakouts:              {len(both_keys)}")
    print(f"Sheet has retest date:          {with_retest_sheet}")
    print(f"Retest exact (date+row):        {rt_exact}")
    print(f"Retest date ok, row off:        {rt_date_only}")
    print(f"Retest row ok, date off:        {rt_row_only}")
    print(f"Retest both wrong:               {rt_both_wrong}")
    print(f"Both agree no retest:           {both_empty}")
    print(f"Sheet empty, engine has retest: {sheet_empty_eng_has}")
    print(f"Sheet has retest, engine empty: {rt_eng_empty}")
    print()

    if rt_mismatches:
        print(f"Retest mismatches ({len(rt_mismatches)}):")
        for line in rt_mismatches[:40]:
            print(line)
        if len(rt_mismatches) > 40:
            print(f"  ... ({len(rt_mismatches) - 40} more)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
