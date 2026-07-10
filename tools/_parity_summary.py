#!/usr/bin/env python3
"""One-off parity summary helper (internal)."""
from __future__ import annotations

import io
import contextlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import pandas as pd
from compare_breakout_retest import _compare_symbol, DEFAULT_SYMBOLS
from compare_sheet_trades import compare_symbol, _closed_path, load_sheet, classify, next_td, _trading_days
from sheet_trade_ledgers import SHEET_LEDGER


def brt_summary(run_id: str) -> None:
    print("BRT SUMMARY", run_id)
    print("SYMBOL sheet eng MR rt_exact rt_wrong zone_bound_mism zone_key_match")
    for sym in DEFAULT_SYMBOLS:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _compare_symbol(sym, run_id, show_mismatches=0)
        text = buf.getvalue()

        def grab(prefix: str) -> str:
            for line in text.splitlines():
                if prefix in line:
                    return line.split(":")[-1].strip()
            return "?"

        se = [l for l in text.splitlines() if "sheet rows" in l][0]
        sheet_n = se.split("sheet rows (active):")[1].split("engine")[0].strip()
        eng_n = se.split("engine rows:")[1].strip()
        zm = grab("Matched:")
        zm_parts = zm.split()
        zmatch = zm_parts[0] if zm_parts else "?"
        print(
            f"{sym:6} {sheet_n:>4} {eng_n:>4} {grab('Breakouts matched on Main Row'):>4} "
            f"{grab('Retest exact'):>9} {grab('Retest date wrong'):>9} "
            f"{grab('Zone bound mismatches on MR'):>6} {zmatch:>6}"
        )


def trade_gaps(run_id: str) -> None:
    print("\nTRADE GAPS", run_id)
    eng_all = pd.read_csv(_closed_path(run_id))
    for sym in DEFAULT_SYMBOLS:
        eng = eng_all[eng_all["SYMBOL"] == sym].copy()
        eng["open_d"] = pd.to_datetime(eng["DATE_OPENED"].astype(str), format="%Y%m%d")
        eng["close_d"] = pd.to_datetime(eng["DATE_CLOSED"].astype(str), format="%Y%m%d")
        eng["cad"] = pd.to_datetime(eng["CLOSE_ABOVE_DATE"], errors="coerce")
        eng["purch_key"] = eng["open_d"].dt.strftime("%Y-%m-%d")
        eng["cad_key"] = eng["cad"].dt.strftime("%Y-%m-%d")
        iso = _trading_days(sym)
        sheet = load_sheet(SHEET_LEDGER[sym])
        sheet["purch_d"] = sheet["trigger_d"].map(lambda d: next_td(iso, d))
        matched = set()
        gaps = []
        for _, s in sheet.iterrows():
            er = eng[eng["purch_key"] == s["purch_d"]]
            e = er.iloc[0] if len(er) else None
            if e is not None:
                matched.add(s["purch_d"])
            tag, detail = classify(s.to_dict(), e)
            if tag != "exact":
                gaps.append((tag, s, e, detail))
        eng_only = eng[~eng["purch_key"].isin(matched)]
        if gaps or len(eng_only):
            print(f"\n{sym}:")
            for tag, s, e, detail in gaps:
                msg = f"  {tag:10s} trig={s['trigger_d']} purch={s['purch_d']} ${s['entry_px']:.2f}"
                if e is not None:
                    msg += f" | eng purch={e.open_d.date()} ${float(e.ENTRY_PRICE):.2f} CAD={e.cad_key} {detail}"
                else:
                    msg += f" | no engine | {detail}"
                print(msg)
            for _, e in eng_only.iterrows():
                print(
                    f"  engine_only purch={e.open_d.date()} ${float(e.ENTRY_PRICE):.2f} "
                    f"-> {e.close_d.date()} {e.EXIT_TYPE} CAD={e.cad_key}"
                )


if __name__ == "__main__":
    rid = sys.argv[1] if len(sys.argv) > 1 else "260621111231"
    brt_summary(rid)
    trade_gaps(rid)
