#!/usr/bin/env python3
"""Backfill AWK-style pivot/structure columns on an RL_Closed CSV.

Uses rocket_rl.compute_awk_rl_pivot_context (same math as portfolio_audit.awk)
snapshotted at DATE OPENED. Does not change trade identity / exits.

  python tools/enrich_rl_closed_pivots.py IN.csv -o OUT.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock_analysis"))
from rocket_rl import (  # noqa: E402
    compute_awk_rl_pivot_context,
    snap_awk_rl_pivots_at_entry,
)

DATA_DIR = ROOT / "data" / "newdata" / "data"
PIVOT_COLS = [
    "PIVOT_HIGH_AT_ENTRY",
    "PIVOT_LOW_AT_ENTRY",
    "STRUCT_HIGH_AT_ENTRY",
    "STRUCT_LOW_AT_ENTRY",
    "MAJOR_PIVOT_HIGH_AT_ENTRY",
    "MAJOR_PIVOT_LOW_AT_ENTRY",
    "PIVOT_HIGH_PRICE_AT_ENTRY",
    "PIVOT_LOW_PRICE_AT_ENTRY",
    "LAST_PIVOT_HIGH_PRICE",
    "LAST_PIVOT_LOW_PRICE",
    "PREV_PIVOT_HIGH_PRICE",
    "PREV_PIVOT_LOW_PRICE",
]

_ohlc: dict[str, pd.DataFrame | None] = {}


def _load_ohlc(sym: str) -> pd.DataFrame | None:
    if sym in _ohlc:
        return _ohlc[sym]
    path = DATA_DIR / f"{sym}.csv"
    if not path.is_file():
        _ohlc[sym] = None
        return None
    df = pd.read_csv(path)
    cols = {str(c).lower(): c for c in df.columns}
    date_c = cols.get("date") or list(df.columns)[0]
    df[date_c] = pd.to_datetime(df[date_c])
    df = df.sort_values(date_c).reset_index(drop=True)
    rename = {}
    for want in ("Open", "High", "Low", "Close", "Volume"):
        for c in df.columns:
            if str(c).lower() == want.lower():
                rename[c] = want
    df = df.rename(columns=rename)
    df["ymd"] = df[date_c].dt.strftime("%Y%m%d")
    _ohlc[sym] = df
    return df


def _fmt_price(v) -> str:
    if v is None:
        return ""
    try:
        import math

        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return ""
    except Exception:
        pass
    return f"{float(v):.4f}"


def enrich_row(row: dict[str, str]) -> dict[str, str]:
    out = dict(row)
    sym = (row.get("SYMBOL") or "").strip().upper()
    opened = (row.get("DATE OPENED") or row.get("DATE_OPENED") or "").strip().replace("-", "")
    if len(opened) != 8 or not sym:
        return out
    df = _load_ohlc(sym)
    if df is None or df.empty:
        return out
    hits = df.index[df["ymd"] == opened].tolist()
    if not hits:
        return out
    idx = int(hits[0])
    ctx = compute_awk_rl_pivot_context(df["High"].to_numpy(), df["Low"].to_numpy())
    snap = snap_awk_rl_pivots_at_entry(ctx, idx)
    out["PIVOT_HIGH_AT_ENTRY"] = str(int(snap["pivot_high"]))
    out["PIVOT_LOW_AT_ENTRY"] = str(int(snap["pivot_low"]))
    out["STRUCT_HIGH_AT_ENTRY"] = snap["struct_high"] or ""
    out["STRUCT_LOW_AT_ENTRY"] = snap["struct_low"] or ""
    out["MAJOR_PIVOT_HIGH_AT_ENTRY"] = str(int(snap["major_ph"]))
    out["MAJOR_PIVOT_LOW_AT_ENTRY"] = str(int(snap["major_pl"]))
    out["PIVOT_HIGH_PRICE_AT_ENTRY"] = _fmt_price(snap["pivot_high_pr"])
    out["PIVOT_LOW_PRICE_AT_ENTRY"] = _fmt_price(snap["pivot_low_pr"])
    out["LAST_PIVOT_HIGH_PRICE"] = _fmt_price(snap["last_ph_pr"])
    out["LAST_PIVOT_LOW_PRICE"] = _fmt_price(snap["last_pl_pr"])
    out["PREV_PIVOT_HIGH_PRICE"] = _fmt_price(snap["prev_ph_pr"])
    out["PREV_PIVOT_LOW_PRICE"] = _fmt_price(snap["prev_pl_pr"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("src", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    args = ap.parse_args()
    if not args.src.is_file():
        print(f"ERROR: missing {args.src}", file=sys.stderr)
        return 2
    with args.src.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            print("ERROR: empty header", file=sys.stderr)
            return 2
        fieldnames = list(reader.fieldnames)
        for c in PIVOT_COLS:
            if c not in fieldnames:
                fieldnames.append(c)
        rows = [enrich_row(r) for r in reader]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    # quick fill stats
    filled_last = sum(1 for r in rows if (r.get("LAST_PIVOT_HIGH_PRICE") or "").strip())
    ph = sum(1 for r in rows if r.get("PIVOT_HIGH_AT_ENTRY") == "1")
    pl = sum(1 for r in rows if r.get("PIVOT_LOW_AT_ENTRY") == "1")
    print(
        f"Wrote {args.out} N={len(rows)} "
        f"PIVOT_HIGH=1:{ph} PIVOT_LOW=1:{pl} LAST_PH filled:{filled_last}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
