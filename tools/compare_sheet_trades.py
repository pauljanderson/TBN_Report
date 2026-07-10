#!/usr/bin/env python3
"""Compare engine vs sheet trade logs (trigger D -> purchase D+1 join)."""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from sheet_trade_ledgers import DEFAULT_SYMBOLS, SHEET_LEDGER

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "newdata" / "data"


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


def load_sheet(raw: str) -> pd.DataFrame:
    rows = []
    for line in raw.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        rows.append(
            {
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
    if d not in iso:
        return ""
    i = iso.index(d)
    return iso[i + 1] if i + 1 < len(iso) else ""


def classify(row: dict, eng_row: pd.Series | None) -> tuple[str, str]:
    if eng_row is None:
        return "sheet_only", "no engine purchase on trigger+1"
    ep = abs(float(eng_row.ENTRY_PRICE) - row["entry_px"])
    xp = abs(float(eng_row.EXIT_PRICE) - row["exit_px"])
    ed = abs((pd.Timestamp(eng_row.close_d) - pd.Timestamp(row["exit_d"])).days)
    dd = abs(int(eng_row.DAYS_HELD) - int(row["days"]))
    pp = abs(float(str(eng_row.PNL_PCT).replace("%", "")) - row["pnl_pct"])
    cad = str(eng_row.CLOSE_ABOVE_DATE)[:10] if pd.notna(eng_row.CLOSE_ABOVE_DATE) else ""
    cad_ok = cad == row["trigger_d"]
    if ep < 0.03 and xp < 0.08 and ed <= 2 and dd <= 3 and pp < 2.0 and cad_ok:
        return "exact", ""
    if ep < 0.05 and ed <= 5 and cad_ok:
        return "partial", f"entry_d={ep:.2f} exit_d={ed}d exit_px={xp:.2f} pnl_d={pp:.1f} days_d={dd} cad={cad}"
    if ep < 0.05 and ed <= 5:
        return "partial", f"entry_d={ep:.2f} exit_d={ed}d exit_px={xp:.2f} pnl_d={pp:.1f} days_d={dd} cad={cad} (CAD!=trigger)"
    return "mismatch", f"entry_d={ep:.2f} exit_d={ed}d exit_px={xp:.2f} pnl_d={pp:.1f} days_d={dd} cad={cad}"


def _closed_path(run_id: str) -> Path:
    for sub in ("drive", "Drive"):
        p = ROOT / sub / f"YH_Closed_{run_id}.csv"
        if p.exists():
            return p
    raise FileNotFoundError(f"YH_Closed_{run_id}.csv not found")


def _trading_days(symbol: str) -> list[str]:
    csv_path = DATA_DIR / f"{symbol}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"Price data not found: {csv_path}")
    meta = pd.read_csv(csv_path, parse_dates=["Date"])
    return [d.strftime("%Y-%m-%d") for d in meta.sort_values("Date")["Date"]]


def compare_symbol(
    symbol: str,
    eng_all: pd.DataFrame,
    *,
    verbose: bool = True,
) -> dict:
    if symbol not in SHEET_LEDGER:
        raise KeyError(f"No sheet ledger for {symbol}")

    eng = eng_all[eng_all["SYMBOL"] == symbol].copy()
    eng["open_d"] = pd.to_datetime(eng["DATE_OPENED"].astype(str), format="%Y%m%d")
    eng["close_d"] = pd.to_datetime(eng["DATE_CLOSED"].astype(str), format="%Y%m%d")
    eng["cad"] = pd.to_datetime(eng["CLOSE_ABOVE_DATE"], errors="coerce")
    eng["purch_key"] = eng["open_d"].dt.strftime("%Y-%m-%d")
    eng["cad_key"] = eng["cad"].dt.strftime("%Y-%m-%d")
    eng = eng.sort_values("open_d")

    iso = _trading_days(symbol)
    sheet = load_sheet(SHEET_LEDGER[symbol])
    sheet["purch_d"] = sheet["trigger_d"].map(lambda d: next_td(iso, d))

    if verbose:
        print(f"\n{'=' * 60}")
        print(f"{symbol}: Engine {len(eng)} trades  |  Sheet {len(sheet)} trades")
        print(f"{'=' * 60}")

    matched_eng: set[str] = set()
    exact = partial = sheet_only = 0
    mismatches: list[str] = []

    for _, s in sheet.iterrows():
        er = eng[eng["purch_key"] == s["purch_d"]]
        e = er.iloc[0] if len(er) else None
        if e is not None:
            matched_eng.add(s["purch_d"])
        tag, detail = classify(s.to_dict(), e)
        if tag == "exact":
            exact += 1
        elif tag == "partial":
            partial += 1
        else:
            sheet_only += 1
        if tag != "exact" and verbose:
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
    if verbose:
        print(
            f"Summary: exact={exact} partial={partial} sheet_only={sheet_only} eng_only={len(eng_only)}"
        )
        print(f"Match rate: {exact}/{len(sheet)} exact, {exact + partial}/{len(sheet)} with partial tolerance")
        if mismatches:
            print("\nNon-exact sheet rows:")
            for m in mismatches:
                print(" ", m)
        if len(eng_only):
            print(f"\nEngine-only ({len(eng_only)} trades):")
            for _, e in eng_only.iterrows():
                print(
                    f"  purch {e.open_d.date()} ${float(e.ENTRY_PRICE):.2f} -> {e.close_d.date()} "
                    f"${float(e.EXIT_PRICE):.2f} {e.EXIT_TYPE} {e.PNL_PCT}  CAD={e.cad_key}"
                )

    return {
        "symbol": symbol,
        "sheet_n": len(sheet),
        "eng_n": len(eng),
        "exact": exact,
        "partial": partial,
        "sheet_only": sheet_only,
        "eng_only": len(eng_only),
    }


def main() -> None:
    args = sys.argv[1:]
    run_id = args[0] if args else "260621103925"
    symbols = [a.upper() for a in args[1:]] if len(args) > 1 else DEFAULT_SYMBOLS

    print(f"Run: {run_id}")
    eng_all = pd.read_csv(_closed_path(run_id))

    results = []
    for sym in symbols:
        results.append(compare_symbol(sym, eng_all, verbose=len(symbols) == 1))

    if len(symbols) > 1:
        print(f"\n{'=' * 60}")
        print("OVERALL SUMMARY")
        print(f"{'=' * 60}")
        print(f"{'Symbol':<8} {'Sheet':>5} {'Eng':>5} {'Exact':>5} {'Part':>5} {'S-only':>6} {'E-only':>6}")
        print("-" * 48)
        tot = {"sheet": 0, "eng": 0, "exact": 0, "partial": 0, "sheet_only": 0, "eng_only": 0}
        for r in results:
            print(
                f"{r['symbol']:<8} {r['sheet_n']:>5} {r['eng_n']:>5} {r['exact']:>5} "
                f"{r['partial']:>5} {r['sheet_only']:>6} {r['eng_only']:>6}"
            )
            tot["sheet"] += r["sheet_n"]
            tot["eng"] += r["eng_n"]
            tot["exact"] += r["exact"]
            tot["partial"] += r["partial"]
            tot["sheet_only"] += r["sheet_only"]
            tot["eng_only"] += r["eng_only"]
        print("-" * 48)
        print(
            f"{'TOTAL':<8} {tot['sheet']:>5} {tot['eng']:>5} {tot['exact']:>5} "
            f"{tot['partial']:>5} {tot['sheet_only']:>6} {tot['eng_only']:>6}"
        )
        print(
            f"\nMatch rate: {tot['exact']}/{tot['sheet']} exact, "
            f"{tot['exact'] + tot['partial']}/{tot['sheet']} with partial tolerance"
        )


if __name__ == "__main__":
    main()
