#!/usr/bin/env python3
"""Compare sheet BH:BQ breakout/retest ledger vs engine YH_breakout export.

Usage:
  python tools/compare_breakout_retest.py <RUN_ID> [SYMBOL ...]

Examples:
  python tools/compare_breakout_retest.py 260621111231 AAPL
  python tools/compare_breakout_retest.py 260621111231          # all symbols with ledgers
"""
from __future__ import annotations

import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "stock_analysis"))

from compare_brt_breakout_sheet_program import BrRow, _parse_intish, _parse_mdy, _parse_money  # noqa: E402
from sheet_breakout_ledgers import DEFAULT_SYMBOLS, SHEET_BREAKOUT_LEDGER  # noqa: E402
from brt_sheet_breakout_ledgers import (  # noqa: E402
    BRT_SHEET_BREAKOUT_LEDGER,
    DEFAULT_SYMBOLS as BRT_DEFAULT_SYMBOLS,
)

DATA_DIR = ROOT / "data" / "newdata" / "data"
DRIVE_DIRS = [ROOT / "drive", ROOT / "Drive"]


def _normalize_brt_tsv_df(df: pd.DataFrame) -> pd.DataFrame:
    """Repair ledgers where header had leading empty columns but data rows are aligned."""
    cols = [str(c).strip() for c in df.columns]
    if "Breakout Date" in cols and cols[0] not in ("Breakout Date", ""):
        pass  # already aligned
    elif "Unnamed: 0" in df.columns:
        # Date in first unnamed col; Zone Lower in second; real headers shifted right by 2
        rename = {
            "Unnamed: 0": "Breakout Date",
            "Unnamed: 1": "Zone Lower",
            "Breakout Date": "Zone Upper",
            "Zone Lower": "Breakout Active",
            "Zone Upper": "Main Row",
            "Breakout Active": "Scan Start Row",
            "Main Row": "retest Row",
            "Scan Start Row": "Retest Date",
            "retest Row": "retest hit",
            "Retest Date": "Too fast retest",
        }
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _load_sheet_tsv(path: Path, symbol: str, *, active_only: bool = True) -> list[BrRow]:
    df = pd.read_csv(path, sep="\t", dtype=str)
    df.columns = [c.strip() for c in df.columns]
    if "Breakout Date" not in df.columns:
        df = _normalize_brt_tsv_df(df)
    if active_only and "Breakout Active" in df.columns:
        act = df["Breakout Active"].astype(str).str.strip().str.lower()
        df = df[act.isin({"1", "1.0", "true", "yes"})].copy()
    rows: list[BrRow] = []
    for _, raw in df.iterrows():
        bd = str(raw.get("Breakout Date", "") or "").strip()
        iso = _parse_mdy(bd)
        zl = _parse_money(raw.get("Zone Lower"))
        zu = _parse_money(raw.get("Zone Upper"))
        mr = _parse_intish(raw.get("Main Row"))
        if not iso or zl is None or zu is None or mr is None:
            continue
        rows.append(
            BrRow(
                symbol=symbol.upper(),
                breakout_iso=iso,
                breakout_mdy=bd,
                zl=float(zl),
                zu=float(zu),
                main_row=int(mr),
                scan_row=_parse_intish(raw.get("Scan Start Row")),
                retest_row=_parse_intish(raw.get("retest Row")),
                retest_iso=_parse_mdy(str(raw.get("Retest Date", "") or "").strip()),
                source="sheet",
                raw={c: str(raw.get(c, "")) for c in df.columns},
            )
        )
    return rows


def _load_engine_csv(path: Path, symbol: str) -> list[BrRow]:
    df = pd.read_csv(path)
    df = df[df["SYMBOL"].astype(str).str.upper() == symbol.upper()].copy()
    rows: list[BrRow] = []
    for _, raw in df.iterrows():
        bd = str(raw.get("Breakout Date", "") or "").strip()
        iso = _parse_mdy(bd)
        zl = _parse_money(raw.get("Zone Lower"))
        zu = _parse_money(raw.get("Zone Upper"))
        mr = _parse_intish(raw.get("Main Row"))
        if not iso or zl is None or zu is None or mr is None:
            continue
        rows.append(
            BrRow(
                symbol=symbol.upper(),
                breakout_iso=iso,
                breakout_mdy=bd,
                zl=float(zl),
                zu=float(zu),
                main_row=int(mr),
                scan_row=_parse_intish(raw.get("Scan Start Row")),
                retest_row=_parse_intish(raw.get("retest Row")),
                retest_iso=_parse_mdy(str(raw.get("Retest Date", "") or "").strip()),
                source="program",
                raw={c: str(raw.get(c, "")) for c in df.columns},
            )
        )
    return rows


def _engine_path(run_id: str, *, brt: bool = False) -> Path:
    prefix = "BRT" if brt else "YH"
    name = f"{prefix}_breakout_and_retest_{run_id}.csv"
    for d in DRIVE_DIRS:
        p = d / name
        if p.is_file():
            return p
    return DRIVE_DIRS[0] / name


def _replay_retest(
    ohlc: pd.DataFrame,
    bo_iso: str,
    zl: float,
    zu: float,
    scan_delta: int,
    rd: int = 2,
) -> tuple[str, int | None]:
    dates = ohlc["iso"].tolist()
    if bo_iso not in dates:
        return "", None
    b = dates.index(bo_iso)
    zlr, zur = round(zl, rd), round(zu, rd)
    start = b + max(1, scan_delta)
    for k in range(start, len(ohlc)):
        lo = round(float(ohlc.iloc[k]["Low"]), rd)
        hi = round(float(ohlc.iloc[k]["High"]), rd)
        if lo <= zur and hi >= zlr:
            return dates[k], k + 2
    return "", None


def _zone_center(zl: float, zu: float) -> float:
    return (zl + zu) / 2.0


def _compare_symbol(
    symbol: str,
    run_id: str,
    *,
    zone_decimals: int = 2,
    scan_delta: int = 2,
    show_mismatches: int = 40,
    brt: bool = False,
) -> int:
    sym = symbol.upper()
    ledger_map = BRT_SHEET_BREAKOUT_LEDGER if brt else SHEET_BREAKOUT_LEDGER
    ledger_path = ledger_map.get(sym)
    if ledger_path is None or not ledger_path.is_file():
        label = "brt" if brt else "yh"
        print(f"SKIP {sym}: no {label} sheet ledger at tools/")
        return 0

    prog_path = _engine_path(run_id, brt=brt)
    if not prog_path.is_file():
        print(f"ERROR: engine export not found: {prog_path}", file=sys.stderr)
        return 2

    sheet_rows = _load_sheet_tsv(ledger_path, sym, active_only=True)
    prog_rows = _load_engine_csv(prog_path, sym)
    zd = max(0, zone_decimals)

    sm_zone = {r.key(zd): r for r in sheet_rows}
    pm_zone = {r.key(zd): r for r in prog_rows}
    sm_dz = {r.date_zone_key(zd): r for r in sheet_rows}
    pm_dz = {r.date_zone_key(zd): r for r in prog_rows}
    sm_mr = {r.main_row: r for r in sheet_rows}
    pm_mr = {r.main_row: r for r in prog_rows}
    sm_bo = {(r.breakout_iso, r.main_row): r for r in sheet_rows}
    pm_bo = {(r.breakout_iso, r.main_row): r for r in prog_rows}

    ohlc_path = DATA_DIR / f"{sym}.csv"
    ohlc: pd.DataFrame | None = None
    if ohlc_path.is_file():
        ohlc = pd.read_csv(ohlc_path, parse_dates=["Date"]).sort_values("Date")
        ohlc["iso"] = ohlc["Date"].dt.strftime("%Y-%m-%d")

    print("=" * 100)
    print(f"{sym}  sheet={ledger_path.name}  engine={prog_path.name}")
    print(f"  sheet rows (active): {len(sheet_rows)}  engine rows: {len(prog_rows)}")
    print("=" * 100)

    # --- Authoritative: Breakout Date + zone (MR may drift when sheet D row count != CSV) ---
    dz_only_s = sorted(set(sm_dz) - set(pm_dz))
    dz_only_p = sorted(set(pm_dz) - set(sm_dz))
    common_dz = sorted(set(sm_dz) & set(pm_dz))
    dz_rt_date = sum(
        1
        for k in common_dz
        if (sm_dz[k].retest_iso or "") == (pm_dz[k].retest_iso or "")
    )
    dz_rt_exact = sum(
        1
        for k in common_dz
        if (sm_dz[k].retest_iso or "") == (pm_dz[k].retest_iso or "")
        and (sm_dz[k].retest_row or -1) == (pm_dz[k].retest_row or -1)
    )
    mr_delta_on_dz: Counter[int] = Counter()
    for k in common_dz:
        mr_delta_on_dz[int(pm_dz[k].main_row) - int(sm_dz[k].main_row)] += 1

    print()
    print(f"--- BREAKOUT keys (Breakout Date + zone @ {zd}dp) [authoritative] ---")
    print(f"  Matched: {len(common_dz)}  Sheet-only: {len(dz_only_s)}  Engine-only: {len(dz_only_p)}")
    print(f"  Retest date on date+zone matches: {dz_rt_date}/{len(common_dz)}")
    print(f"  Retest exact (date+row) on date+zone: {dz_rt_exact}/{len(common_dz)}")
    print(f"  PARITY date+zone matched: {len(common_dz)}/{len(sheet_rows)}")
    print(f"  PARITY retest date on matched: {dz_rt_date}/{len(common_dz) if common_dz else 1}")
    if mr_delta_on_dz and (len(mr_delta_on_dz) > 1 or next(iter(mr_delta_on_dz)) != 0):
        print(f"  Main Row delta (engine - sheet) on date+zone matches: {dict(sorted(mr_delta_on_dz.items()))}")

    if dz_only_s:
        print()
        print(f"--- Sheet-only date+zone ({len(dz_only_s)}) ---")
        for k in dz_only_s[:show_mismatches]:
            r = sm_dz[k]
            eng_same_day = [r2 for r2 in prog_rows if r2.breakout_iso == r.breakout_iso]
            eng_z = (
                f"eng same-day Z ${eng_same_day[0].zl:.2f}/${eng_same_day[0].zu:.2f}"
                if len(eng_same_day) == 1
                else f"eng same-day rows={len(eng_same_day)}"
            )
            print(f"  {r.breakout_mdy} ${r.zl:.2f}/${r.zu:.2f} RT {r.retest_iso or '-'}  ({eng_z})")
        if len(dz_only_s) > show_mismatches:
            print(f"  ... +{len(dz_only_s) - show_mismatches} more")

    if dz_only_p:
        print()
        print(f"--- Engine-only date+zone ({len(dz_only_p)}) ---")
        for k in dz_only_p[:show_mismatches]:
            r = pm_dz[k]
            sh_same_day = [r2 for r2 in sheet_rows if r2.breakout_iso == r.breakout_iso]
            sh_z = (
                f"sheet same-day Z ${sh_same_day[0].zl:.2f}/${sh_same_day[0].zu:.2f}"
                if len(sh_same_day) == 1
                else f"sheet same-day rows={len(sh_same_day)}"
            )
            print(f"  {r.breakout_mdy} ${r.zl:.2f}/${r.zu:.2f} RT {r.retest_iso or '-'}  ({sh_z})")
        if len(dz_only_p) > show_mismatches:
            print(f"  ... +{len(dz_only_p) - show_mismatches} more")

    # --- Breakouts by (Main Row, zone) ---
    only_s = sorted(set(sm_zone) - set(pm_zone))
    only_p = sorted(set(pm_zone) - set(sm_zone))
    common_zone = sorted(set(sm_zone) & set(pm_zone))

    print()
    print(f"--- BREAKOUT keys (Main Row + zone @ {zd}dp) [row index; may false-mismatch] ---")
    print(f"  Matched: {len(common_zone)}  Sheet-only: {len(only_s)}  Engine-only: {len(only_p)}")

    # Same main row, different zone bounds (tighter/wider band)
    zone_bound_mism: list[tuple[BrRow, BrRow]] = []
    for mr in sorted(set(sm_mr) & set(pm_mr)):
        s, p = sm_mr[mr], pm_mr[mr]
        if s.key(zd) != p.key(zd):
            zone_bound_mism.append((s, p))

    if zone_bound_mism:
        print()
        print(f"--- Same Main Row, different zone bounds ({len(zone_bound_mism)}) ---")
        for s, p in zone_bound_mism[:show_mismatches]:
            d_lo = round(p.zl - s.zl, 4)
            d_hi = round(p.zu - s.zu, 4)
            ctr_s = _zone_center(s.zl, s.zu)
            ctr_p = _zone_center(p.zl, p.zu)
            print(
                f"  BO {s.breakout_mdy} MR{s.main_row}\n"
                f"    sheet Z ${s.zl:.2f}/${s.zu:.2f}  (ctr ~${ctr_s:.2f})\n"
                f"    eng   Z ${p.zl:.2f}/${p.zu:.2f}  (ctr ~${ctr_p:.2f})  "
                f"delta lo={d_lo:+.2f} hi={d_hi:+.2f}"
            )
        if len(zone_bound_mism) > show_mismatches:
            print(f"  ... +{len(zone_bound_mism) - show_mismatches} more")

    if only_s:
        print()
        print(f"--- Sheet-only zone keys ({len(only_s)}) ---")
        for k in only_s[:15]:
            r = sm_zone[k]
            print(f"  {r.breakout_mdy} MR{r.main_row} ${r.zl:.2f}/${r.zu:.2f}")
        if len(only_s) > 15:
            print(f"  ... +{len(only_s) - 15} more")

    if only_p:
        print()
        print(f"--- Engine-only zone keys ({len(only_p)}) ---")
        for k in only_p[:15]:
            r = pm_zone[k]
            print(f"  {r.breakout_mdy} MR{r.main_row} ${r.zl:.2f}/${r.zu:.2f}")
        if len(only_p) > 15:
            print(f"  ... +{len(only_p) - 15} more")

    # --- Retests: match on Main Row (zone drift tolerant) ---
    print()
    print("--- RETESTS (match on Main Row) ---")
    rt_exact = rt_date_only = rt_both_wrong = both_empty = sheet_empty = eng_empty = 0
    rt_mismatches: list[str] = []
    zone_caused: list[str] = []

    for mr in sorted(set(sm_mr) & set(pm_mr)):
        s, p = sm_mr[mr], pm_mr[mr]
        s_rt = s.retest_iso or ""
        e_rt = p.retest_iso or ""
        zone_diff = s.key(zd) != p.key(zd)

        if not s_rt and not e_rt:
            both_empty += 1
            continue
        if not s_rt and e_rt:
            eng_empty += 1
            rt_mismatches.append(
                f"  {s.breakout_mdy} MR{mr}  sheet=no retest  engine={p.retest_iso} rr{p.retest_row}"
            )
            continue
        if s_rt and not e_rt:
            sheet_empty += 1
            rt_mismatches.append(
                f"  {s.breakout_mdy} MR{mr}  sheet={s.retest_iso} rr{s.retest_row}  engine=no retest"
            )
            continue

        row_ok = s.retest_row is not None and p.retest_row is not None and int(s.retest_row) == int(p.retest_row)
        date_ok = s_rt == e_rt
        if date_ok and row_ok:
            rt_exact += 1
        elif date_ok:
            rt_date_only += 1
            rt_mismatches.append(
                f"  {s.breakout_mdy} MR{mr}  date ok {s_rt}  row sheet={s.retest_row} eng={p.retest_row}"
            )
        else:
            rt_both_wrong += 1
            line = (
                f"  {s.breakout_mdy} MR{mr}  "
                f"sheet=${s.zl:.2f}/${s.zu:.2f} RT {s.retest_iso}(rr{s.retest_row})  |  "
                f"eng=${p.zl:.2f}/${p.zu:.2f} RT {e_rt}(rr{p.retest_row})"
            )
            rt_mismatches.append(line)
            if zone_diff and ohlc is not None:
                sim_s, _ = _replay_retest(ohlc, s.breakout_iso, s.zl, s.zu, scan_delta)
                sim_p, _ = _replay_retest(ohlc, p.breakout_iso, p.zl, p.zu, scan_delta)
                if sim_s == s_rt and sim_p == e_rt:
                    zone_caused.append(
                        f"    ^ zone-driven: OHLC replay sheet zone -> {sim_s}, engine zone -> {sim_p}"
                    )

    matched_mr = len(set(sm_mr) & set(pm_mr))
    print(f"  Breakouts matched on Main Row: {matched_mr}")
    print(f"  Retest exact (date+row):       {rt_exact}")
    print(f"  Retest date ok, row off:       {rt_date_only}")
    print(f"  Retest date wrong:             {rt_both_wrong}")
    print(f"  Both no retest:                {both_empty}")
    print(f"  Sheet empty / engine has:      {eng_empty}")
    print(f"  Sheet has / engine empty:      {sheet_empty}")
    print(f"  Zone bound mismatches on MR:   {len(zone_bound_mism)}")

    if rt_mismatches:
        print()
        print(f"Retest mismatches ({len(rt_mismatches)}):")
        for i, line in enumerate(rt_mismatches[:show_mismatches]):
            print(line)
            if i < len(zone_caused):
                print(zone_caused[i])
        if len(rt_mismatches) > show_mismatches:
            print(f"  ... +{len(rt_mismatches) - show_mismatches} more")

    # --- Retests on exact zone-key matches ---
    rt_zone_exact = sum(
        1
        for k in common_zone
        if (sm_zone[k].retest_iso or "") == (pm_zone[k].retest_iso or "")
        and (sm_zone[k].retest_row or -1) == (pm_zone[k].retest_row or -1)
    )
    print()
    print(f"  Retest exact on zone-key matches ({len(common_zone)} rows): {rt_zone_exact}/{len(common_zone)}")

    # Highlight trade-critical retest dates (COUNTIF / BO column)
    trade_dates = {
        "AAPL": ["2019-05-29", "2019-06-14", "2019-05-23"],
    }
    if sym in trade_dates:
        print()
        print("--- Trade-critical retest dates (BO column) ---")
        for d in trade_dates[sym]:
            sh = [r for r in sheet_rows if r.retest_iso == d]
            en = [r for r in prog_rows if r.retest_iso == d]
            print(f"  {d}: sheet hits={len(sh)}  engine hits={len(en)}")
            for r in sh[:2]:
                print(f"    sheet BO {r.breakout_mdy} MR{r.main_row} Z${r.zl:.2f}/${r.zu:.2f}")
            for r in en[:2]:
                print(f"    eng   BO {r.breakout_mdy} MR{r.main_row} Z${r.zl:.2f}/${r.zu:.2f}")

    print()
    return 0


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(
            "Usage: python tools/compare_breakout_retest.py [--brt] <RUN_ID> [SYMBOL ...]",
            file=sys.stderr,
        )
        return 2

    brt = False
    if args[0] == "--brt":
        brt = True
        args = args[1:]
    if not args:
        print("Usage: python tools/compare_breakout_retest.py [--brt] <RUN_ID> [SYMBOL ...]", file=sys.stderr)
        return 2

    run_id = args[0]
    default_syms = BRT_DEFAULT_SYMBOLS if brt else DEFAULT_SYMBOLS
    symbols = [a.upper() for a in args[1:]] if len(args) > 1 else default_syms

    rc = 0
    for sym in symbols:
        r = _compare_symbol(sym, run_id, brt=brt)
        if r != 0:
            rc = r
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
