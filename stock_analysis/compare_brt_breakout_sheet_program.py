#!/usr/bin/env python3
"""
BRT breakout/retest: sheet export vs program CSV (practical troubleshooting checklist).

1) Normalize: diff against BRT_breakout_and_retest_<ts>.csv (authoritative program).
2) Align: match on (Main Row, zone lower @ N dp, zone upper @ N dp).
3) Filters: --sheet-active-only keeps Breakout Active in {1, true, yes}.
4) Retest audit: --audit-retests --ohlc-csv replays first overlap (scan delta + rounding).

Run from repo root (stockresearch):

  python -m stock_analysis.compare_brt_breakout_sheet_program \\
    --program Drive/BRT_breakout_and_retest_260417171816.csv \\
    --sheet Drive/TSLA_sheet_brt_export.tsv \\
    --symbol TSLA

  python -m stock_analysis.compare_brt_breakout_sheet_program \\
    --program Drive/BRT_breakout_and_retest_260417171816.csv \\
    --sheet Drive/TSLA_sheet_brt_export.tsv --symbol TSLA --sheet-active-only \\
    --audit-retests --ohlc-csv data/newdata/data/TSLA.csv \\
    --audit-dates 3/1/2021,11/5/2024
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any, Optional


def _norm_header(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").strip().lower()).strip("_")


def _parse_mdy(s: str) -> Optional[str]:
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _parse_money(s: str) -> Optional[float]:
    if s is None:
        return None
    t = str(s).strip().replace("$", "").replace(",", "")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _parse_intish(s: Any) -> Optional[int]:
    if s is None or str(s).strip() == "":
        return None
    try:
        return int(float(str(s).strip()))
    except ValueError:
        return None


def _sniff_dialect(sample: str) -> csv.Dialect:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",\t;")
    except csv.Error:
        class D(csv.excel):
            delimiter = ","

        return D()


@dataclass
class BrRow:
    symbol: str
    breakout_iso: str
    breakout_mdy: str
    zl: float
    zu: float
    main_row: int
    scan_row: Optional[int]
    retest_row: Optional[int]
    retest_iso: Optional[str]
    source: str
    raw: dict[str, str]

    def key(self, zd: int) -> tuple[int, float, float]:
        return (self.main_row, round(self.zl, zd), round(self.zu, zd))

    def date_zone_key(self, zd: int) -> tuple[str, float, float]:
        """Breakout date + zone bounds (authoritative when sheet MR drifts vs CSV row index)."""
        return (self.breakout_iso, round(self.zl, zd), round(self.zu, zd))


def _col(colmap: dict[str, str], *names: str) -> Optional[str]:
    for n in names:
        k = _norm_header(n)
        if k in colmap:
            return colmap[k]
    return None


def _load_rows(
    path: Path,
    source: str,
    symbol: str,
    *,
    sheet_active_only: bool = False,
) -> list[BrRow]:
    raw_text = path.read_text(encoding="utf-8-sig")
    sample = raw_text[:4096]
    dialect = _sniff_dialect(sample)
    f = StringIO(raw_text)
    rdr = csv.DictReader(f, dialect=dialect)
    if not rdr.fieldnames:
        return []
    colmap = {_norm_header(h): h for h in rdr.fieldnames}
    c_sym = _col(colmap, "symbol", "sym")
    c_bd = _col(colmap, "breakout date", "breakout_date")
    c_zl = _col(colmap, "zone lower", "zone_lower")
    c_zu = _col(colmap, "zone upper", "zone_upper")
    c_mr = _col(colmap, "main row", "main_row")
    c_sr = _col(colmap, "scan start row", "scan_start_row")
    c_rr = _col(colmap, "retest row", "retest_row")
    c_rd = _col(colmap, "retest date", "retest_date")
    c_act = colmap.get("breakout_active") or colmap.get("breakoutactive")
    if not c_act:
        for h in rdr.fieldnames or []:
            if "breakout" in _norm_header(h) and "active" in _norm_header(h):
                c_act = h
                break

    rows: list[BrRow] = []
    for raw in rdr:
        sym = (raw.get(c_sym) or "").strip().upper() if c_sym else ""
        if symbol:
            if c_sym and sym != symbol.upper():
                continue
            if not c_sym:
                sym = symbol.upper()
        if sheet_active_only and c_act:
            av = str(raw.get(c_act, "")).strip().lower()
            if av not in ("1", "1.0", "true", "yes", "y"):
                continue
        bd = (raw.get(c_bd) or "").strip() if c_bd else ""
        iso = _parse_mdy(bd)
        if not iso:
            continue
        zl = _parse_money(raw.get(c_zl)) if c_zl else None
        zu = _parse_money(raw.get(c_zu)) if c_zu else None
        if zl is None or zu is None:
            continue
        mr = _parse_intish(raw.get(c_mr)) if c_mr else None
        if mr is None:
            continue
        sr = _parse_intish(raw.get(c_sr)) if c_sr else None
        rr = _parse_intish(raw.get(c_rr)) if c_rr else None
        rdiso = _parse_mdy((raw.get(c_rd) or "").strip()) if c_rd else None
        rows.append(
            BrRow(
                symbol=sym,
                breakout_iso=iso,
                breakout_mdy=bd,
                zl=float(zl),
                zu=float(zu),
                main_row=int(mr),
                scan_row=sr,
                retest_row=rr,
                retest_iso=rdiso,
                source=source,
                raw={k: raw.get(k, "") for k in (rdr.fieldnames or [])},
            )
        )
    return rows


def _audit_first_retest(
    ohlc_csv: Path,
    breakout_iso: str,
    zl: float,
    zu: float,
    first_data_row: int,
    scan_delta: int,
    rd: int,
) -> tuple[str, str]:
    import pandas as pd

    df = pd.read_csv(ohlc_csv, parse_dates=["Date"], index_col="Date")
    idx = pd.DatetimeIndex(pd.to_datetime(df.index))
    dates = idx.strftime("%Y-%m-%d").tolist()
    if breakout_iso not in dates:
        return "", f"date {breakout_iso} not in OHLC ({ohlc_csv})"
    b = dates.index(breakout_iso)
    zlr, zur = (round(zl, rd), round(zu, rd)) if rd >= 0 else (zl, zu)
    start = b + max(1, int(scan_delta))
    for k in range(start, len(df)):
        lo = float(df.iloc[k]["Low"])
        hi = float(df.iloc[k]["High"])
        if rd >= 0:
            lo, hi = round(lo, rd), round(hi, rd)
        if lo <= zur and hi >= zlr:
            return dates[k], f"bar_index={k} main_row={k + first_data_row}"
    return "", "no overlap in history"


def main() -> int:
    ap = argparse.ArgumentParser(description="Compare sheet BRT breakout/retest export to program CSV.")
    ap.add_argument("--program", required=True, type=Path, help="BRT_breakout_and_retest_<ts>.csv")
    ap.add_argument("--sheet", required=True, type=Path, help="Sheet export (CSV or TSV with headers)")
    ap.add_argument("--symbol", default="TSLA")
    ap.add_argument("--zone-decimals", type=int, default=2)
    ap.add_argument("--sheet-active-only", action="store_true")
    ap.add_argument("--excel-first-data-row", type=int, default=2)
    ap.add_argument("--scan-delta", type=int, default=3)
    ap.add_argument("--round-decimals", type=int, default=2)
    ap.add_argument("--audit-retests", action="store_true")
    ap.add_argument("--ohlc-csv", type=Path, default=None)
    ap.add_argument("--audit-dates", default="", help="Extra M/D/YYYY dates to audit (comma-separated)")
    args = ap.parse_args()

    if not args.program.is_file():
        print(f"ERROR: program file not found: {args.program}", file=sys.stderr)
        return 2
    if not args.sheet.is_file():
        print(f"ERROR: sheet file not found: {args.sheet}", file=sys.stderr)
        return 2

    prog = _load_rows(args.program, "program", args.symbol, sheet_active_only=False)
    sheet = _load_rows(args.sheet, "sheet", args.symbol, sheet_active_only=bool(args.sheet_active_only))

    zd = max(0, int(args.zone_decimals))
    dup_p = [r.key(zd) for r in prog]
    if len(dup_p) != len(set(dup_p)):
        print("WARN: program has duplicate (Main Row, zone) keys; last row wins in map.", file=sys.stderr)

    pm = {r.key(zd): r for r in prog}
    sm = {r.key(zd): r for r in sheet}

    only_p = sorted(set(pm) - set(sm), key=lambda k: (k[0], k[1], k[2]))
    only_s = sorted(set(sm) - set(pm), key=lambda k: (k[0], k[1], k[2]))
    common = sorted(set(pm) & set(sm), key=lambda k: (k[0], k[1], k[2]))

    sym = args.symbol.upper()
    print(f"=== BRT breakout/retest diff ({sym}) ===")
    print(f"Program rows: {len(prog)}  Sheet rows: {len(sheet)}  (sheet_active_only={args.sheet_active_only})")
    print(f"Match key: (Main Row, round(zone_lo,{zd}), round(zone_hi,{zd}))")
    print(f"Only in program: {len(only_p)}  Only in sheet: {len(only_s)}  Matched keys: {len(common)}")
    print()

    if only_p:
        print("--- Only in PROGRAM ---")
        for k in only_p[:100]:
            r = pm[k]
            print(
                f"  {r.breakout_mdy}  ZL={r.zl:.4f} ZU={r.zu:.4f}  MR={r.main_row}  "
                f"retest={r.retest_iso or ''}  rrow={r.retest_row}"
            )
        if len(only_p) > 100:
            print(f"  ... ({len(only_p) - 100} more)")
        print()

    if only_s:
        print("--- Only in SHEET ---")
        for k in only_s[:100]:
            r = sm[k]
            print(
                f"  {r.breakout_mdy}  ZL={r.zl:.4f} ZU={r.zu:.4f}  MR={r.main_row}  "
                f"retest={r.retest_iso or ''}  rrow={r.retest_row}"
            )
        if len(only_s) > 100:
            print(f"  ... ({len(only_s) - 100} more)")
        print()

    mism_bo: list[tuple[BrRow, BrRow]] = []
    mism_rt: list[tuple[BrRow, BrRow]] = []
    for k in common:
        a, b = pm[k], sm[k]
        if a.breakout_iso != b.breakout_iso:
            mism_bo.append((a, b))
        if (a.retest_iso or "") != (b.retest_iso or "") or (a.retest_row or -1) != (b.retest_row or -1):
            mism_rt.append((a, b))

    if mism_bo:
        print(f"--- Matched zone, BREAKOUT calendar date differs ({len(mism_bo)}) ---")
        for a, b in mism_bo[:50]:
            print(f"  MR={a.main_row} Z={a.zl:.2f}/{a.zu:.2f}  prog_date={a.breakout_iso}  sheet_date={b.breakout_iso}")
        if len(mism_bo) > 50:
            print(f"  ... ({len(mism_bo) - 50} more)")
        print()

    if mism_rt:
        print(f"--- Matched zone, retest differs ({len(mism_rt)}) ---")
        for a, b in mism_rt[:80]:
            print(
                f"  {a.breakout_iso}  Z={a.zl:.2f}/{a.zu:.2f}  MR={a.main_row}  "
                f"prog_ret={a.retest_iso} pr={a.retest_row}  |  sheet_ret={b.retest_iso} sr={b.retest_row}"
            )
        if len(mism_rt) > 80:
            print(f"  ... ({len(mism_rt) - 80} more)")
        print()

    if args.audit_retests:
        if not args.ohlc_csv or not args.ohlc_csv.is_file():
            print("ERROR: --audit-retests requires --ohlc-csv pointing at symbol OHLC", file=sys.stderr)
            return 2
        extra = {_parse_mdy(s.strip()) for s in args.audit_dates.split(",") if s.strip()}
        extra.discard(None)
        print("--- Retest overlap audit (program zone + OHLC) ---")
        seen: set[str] = set()

        def audit_pair(a: BrRow, b: BrRow) -> None:
            k2 = f"{a.breakout_iso}|{a.main_row}|{round(a.zl, 4)}|{round(a.zu, 4)}"
            if k2 in seen:
                return
            seen.add(k2)
            first, note = _audit_first_retest(
                args.ohlc_csv,
                a.breakout_iso,
                a.zl,
                a.zu,
                int(args.excel_first_data_row),
                int(args.scan_delta),
                int(args.round_decimals),
            )
            print(
                f"  breakout={a.breakout_iso}  zone={a.zl:.4f}/{a.zu:.4f}  "
                f"prog_ret={a.retest_iso}  sheet_ret={b.retest_iso}  replay_first={first}  ({note})"
            )

        for a, b in mism_rt:
            audit_pair(a, b)
        for iso in sorted(extra):
            pr = next((x for x in prog if x.breakout_iso == iso), None)
            if not pr:
                continue
            sr = next((x for x in sheet if x.breakout_iso == iso), None)
            sh = sr if sr else pr
            audit_pair(pr, sh)
        print()

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
