#!/usr/bin/env python3
"""
Generate ThinkorSwim zone studies for MarkTen symbols from drive exports.

Reads latest drive/<PREFIX>_ZONES_<SYM>_<stamp>.csv plus matching Closed/Open ledgers.
Untraded zones -> Color.GRAY; traded zones -> O-Y-B-C-V cycle.
One study per symbol: <PREFIX>_<SYM>_zones_trades.ts

PREFIX defaults to BRT; use --prefix WPBR for Pivot Break and Retest runs
(WPBR_ZONES_* / WPBR_Closed_* / WPBR_Open_*).

Usage:
  python tos/gen_brt_markten_from_drive.py
  python tos/gen_brt_markten_from_drive.py -o drive/brt_tos_studies/markten
  python tos/gen_brt_markten_from_drive.py --trades-stamp 260721155448 --zones-stamp 260721155448 --name-suffix ZoneLow -o drive/brt_tos_studies/markten_zone_low
  python tos/gen_brt_markten_from_drive.py --prefix WPBR -o drive/wpbr_tos_studies/markten
  python tos/gen_brt_markten_from_drive.py --prefix WPBR --zones-stamp 260722174105 --trades-stamp 260722174105 -o drive/wpbr_tos_studies/markten
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_TOS_DIR = Path(__file__).resolve().parent
_ROOT = _TOS_DIR.parent
if str(_TOS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOS_DIR))

from ts_common import write_ts_files  # noqa: E402

MARKTEN = ["AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA", "AU", "AMD", "NFLX"]
DRIVE = _ROOT / "drive"
DEFAULT_OUT = DRIVE / "brt_tos_studies" / "markten"
DEFAULT_PREFIX = "BRT"

# Prefer post-L-disable engine stamps (2026-07-20+).
_STAMP_RE = re.compile(r"_(\d{12})\.csv$", re.I)


@dataclass
class ZoneRow:
    maturity_yyyymmdd: int
    center: float
    lo: float
    hi: float
    pivot_bar: int | None = None
    bar_index: int | None = None
    # WPBR zones CSV: weekly BO Monday (prefer over Closed BREAKOUT_DATE for ToS BO bubbles)
    breakout_yyyymmdd: int = 0


@dataclass
class TradeHit:
    zone_center: float
    breakout_yyyymmdd: int = 0
    entry_yyyymmdd: int = 0
    exit_yyyymmdd: int = 0
    maturity_yyyymmdd: int = 0


@dataclass
class SymbolResult:
    symbol: str
    zones: int = 0
    traded: int = 0
    untraded: int = 0
    entries: int = 0
    exits: int = 0
    zones_stamp: str = ""
    trades_stamp: str = ""
    filename: str = ""
    path: str = ""
    skipped: str = ""
    error: str = ""


def _parse_stamp(path: Path) -> str | None:
    m = _STAMP_RE.search(path.name)
    return m.group(1) if m else None


def _ymd_int(value: object) -> int:
    if value is None:
        return 0
    text = str(value).strip()
    if not text or text.lower() in {"0", "na", "n/a", "none", "-", ""}:
        return 0
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 8:
        return int(digits[:8])
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return int(datetime.strptime(text[:10], fmt).strftime("%Y%m%d"))
        except ValueError:
            continue
    if text.isdigit() and len(text) == 8:
        return int(text)
    return 0


def _f(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    text = str(value).strip().replace(",", "")
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def _norm_prefix(prefix: str) -> str:
    p = (prefix or DEFAULT_PREFIX).strip().upper()
    if not p:
        return DEFAULT_PREFIX
    return p


def latest_zones_path(
    symbol: str,
    drive: Path = DRIVE,
    stamp: str | None = None,
    *,
    prefix: str = DEFAULT_PREFIX,
) -> Path | None:
    pref = _norm_prefix(prefix)
    if stamp:
        p = drive / f"{pref}_ZONES_{symbol}_{stamp}.csv"
        return p if p.is_file() else None

    paths = list(drive.glob(f"{pref}_ZONES_{symbol}_*.csv"))
    # Exclude ENTRIES companion files
    paths = [p for p in paths if "ENTRIES" not in p.name.upper()]
    if not paths:
        return None

    def key(p: Path) -> tuple:
        s = _parse_stamp(p) or "0"
        return (s, p.stat().st_mtime)

    return max(paths, key=key)


def ledger_path(
    kind: str, stamp: str, drive: Path = DRIVE, *, prefix: str = DEFAULT_PREFIX
) -> Path | None:
    """kind: Closed | Open"""
    pref = _norm_prefix(prefix)
    p = drive / f"{pref}_{kind}_{stamp}.csv"
    return p if p.is_file() else None


def find_trades_stamp_for_symbol(
    symbol: str,
    preferred_stamp: str,
    drive: Path = DRIVE,
    *,
    prefix: str = DEFAULT_PREFIX,
) -> str | None:
    """
    Prefer Closed ledger with preferred_stamp if it contains the symbol;
    else newest Closed that contains the symbol.
    """
    pref = _norm_prefix(prefix)
    preferred = ledger_path("Closed", preferred_stamp, drive, prefix=pref)
    if preferred and _closed_has_symbol(preferred, symbol):
        return preferred_stamp

    closed_files = sorted(
        drive.glob(f"{pref}_Closed_*.csv"),
        key=lambda p: (_parse_stamp(p) or "0", p.stat().st_mtime),
        reverse=True,
    )
    # Skip variant ledgers like WPBR_Closed_SecondChanceOnly_*
    closed_files = [
        p
        for p in closed_files
        if re.fullmatch(rf"{re.escape(pref)}_Closed_\d{{12}}\.csv", p.name, re.I)
    ]
    for path in closed_files:
        if _closed_has_symbol(path, symbol):
            return _parse_stamp(path)
    # Open-only fallback
    open_files = sorted(
        drive.glob(f"{pref}_Open_*.csv"),
        key=lambda p: (_parse_stamp(p) or "0", p.stat().st_mtime),
        reverse=True,
    )
    open_files = [
        p
        for p in open_files
        if re.fullmatch(rf"{re.escape(pref)}_Open_\d{{12}}\.csv", p.name, re.I)
    ]
    for path in open_files:
        if _closed_has_symbol(path, symbol):  # same header check works
            return _parse_stamp(path)
    return None


def _closed_has_symbol(path: Path, symbol: str) -> bool:
    sym = symbol.upper()
    try:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                if str(row.get("SYMBOL", "")).strip().upper() == sym:
                    return True
    except OSError:
        return False
    return False


def load_zones(path: Path) -> list[ZoneRow]:
    rows: list[ZoneRow] = []
    seen: set[tuple[int, float, float, float]] = set()
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            matured = str(raw.get("MATURED_NOW", "1")).strip()
            if matured in {"0", "false", "False"}:
                continue
            # WPBR zone CSVs use DATE / PIVOT_MONDAY (no MATURITY_DATE).
            mat = _ymd_int(
                raw.get("MATURITY_DATE")
                or raw.get("PIVOT_MONDAY")
                or raw.get("DATE")
            )
            center = _f(raw.get("ZONE_CENTER"))
            lo = _f(raw.get("ZONE_LOW"))
            hi = _f(raw.get("ZONE_HIGH"))
            if mat <= 0 or lo <= 0 or hi <= 0 or lo >= hi:
                continue
            key = (mat, round(center, 4), round(lo, 4), round(hi, 4))
            if key in seen:
                continue
            seen.add(key)
            pivot_bar = int(_f(raw.get("PIVOT_BAR"), 0)) or None
            bar_index = int(_f(raw.get("BAR_INDEX"), 0)) or None
            # WPBR: BREAKOUT_MONDAY is the weekly BO; Closed BREAKOUT_DATE is often wrong for bubbles.
            bo = _ymd_int(raw.get("BREAKOUT_MONDAY") or raw.get("BREAKOUT_DATE"))
            rows.append(
                ZoneRow(
                    maturity_yyyymmdd=mat,
                    center=center,
                    lo=lo,
                    hi=hi,
                    pivot_bar=pivot_bar,
                    bar_index=bar_index,
                    breakout_yyyymmdd=bo,
                )
            )
    rows.sort(key=lambda z: (z.maturity_yyyymmdd, z.center))
    return rows


def load_trades(
    symbol: str, stamp: str, drive: Path = DRIVE, *, prefix: str = DEFAULT_PREFIX
) -> list[TradeHit]:
    hits: list[TradeHit] = []
    sym = symbol.upper()
    pref = _norm_prefix(prefix)
    for kind in ("Closed", "Open"):
        path = ledger_path(kind, stamp, drive, prefix=pref)
        if path is None:
            continue
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            for raw in reader:
                if str(raw.get("SYMBOL", "")).strip().upper() != sym:
                    continue
                center = _f(raw.get("ZONE_CENTER"))
                if center <= 0:
                    continue
                hits.append(
                    TradeHit(
                        zone_center=center,
                        breakout_yyyymmdd=_ymd_int(raw.get("BREAKOUT_DATE")),
                        entry_yyyymmdd=_ymd_int(raw.get("DATE_OPENED")),
                        exit_yyyymmdd=_ymd_int(raw.get("DATE_CLOSED")) if kind == "Closed" else 0,
                        maturity_yyyymmdd=_ymd_int(raw.get("MATURITY_DATE")),
                    )
                )
    return hits


def _centers_match(a: float, b: float) -> bool:
    tol = max(0.015, abs(a) * 0.0015)
    return abs(a - b) <= tol


def assign_trades_to_zones(
    zones: list[ZoneRow], trades: list[TradeHit]
) -> list[TradeHit | None]:
    """
    Map each trade to at most one zone (best center match).
    A zone is traded if >=1 trade maps to it (many trades may share one zone).
    Returns primary TradeHit per zone (best BO/entry) or None.
    """
    zone_trades: list[list[TradeHit]] = [[] for _ in zones]

    for t in trades:
        best_zi: int | None = None
        best_key: tuple | None = None
        for zi, z in enumerate(zones):
            if not _centers_match(z.center, t.zone_center):
                continue
            mat_ok = (
                0
                if (t.maturity_yyyymmdd and t.maturity_yyyymmdd == z.maturity_yyyymmdd)
                else 1
            )
            dist = abs(z.center - t.zone_center)
            key = (mat_ok, dist, abs(z.maturity_yyyymmdd - (t.maturity_yyyymmdd or z.maturity_yyyymmdd)))
            if best_key is None or key < best_key:
                best_key = key
                best_zi = zi
        if best_zi is not None:
            zone_trades[best_zi].append(t)

    primary: list[TradeHit | None] = []
    for hits in zone_trades:
        if not hits:
            primary.append(None)
            continue
        hits_sorted = sorted(
            hits,
            key=lambda h: (0 if h.breakout_yyyymmdd else 1, h.entry_yyyymmdd or 10**9),
        )
        primary.append(hits_sorted[0])
    return primary


def cloud_start_yyyymmdd(zone: ZoneRow) -> int:
    """Use maturity date (when zone becomes available) as cloud start."""
    return zone.maturity_yyyymmdd


def generate_symbol(
    symbol: str,
    output_dir: Path,
    drive: Path = DRIVE,
    *,
    prefix: str = DEFAULT_PREFIX,
    zones_stamp: str | None = None,
    trades_stamp: str | None = None,
    name_suffix: str | None = None,
    study_label: str | None = None,
) -> SymbolResult:
    pref = _norm_prefix(prefix)
    result = SymbolResult(symbol=symbol)
    zpath = latest_zones_path(symbol, drive, stamp=zones_stamp, prefix=pref)
    if zpath is None:
        hint = f" for stamp {zones_stamp}" if zones_stamp else ""
        result.skipped = f"no {pref}_ZONES_*.csv found{hint}"
        return result

    z_stamp = _parse_stamp(zpath) or ""
    result.zones_stamp = z_stamp

    if trades_stamp:
        t_stamp = trades_stamp
        if not ledger_path("Closed", t_stamp, drive, prefix=pref) and not ledger_path(
            "Open", t_stamp, drive, prefix=pref
        ):
            result.skipped = f"no {pref} Closed/Open ledger for stamp {t_stamp}"
            return result
    else:
        found = find_trades_stamp_for_symbol(symbol, z_stamp, drive, prefix=pref)
        if found is None:
            result.skipped = f"no {pref} Closed/Open ledger containing {symbol}"
            return result
        t_stamp = found
    result.trades_stamp = t_stamp

    zones = load_zones(zpath)
    if not zones:
        result.skipped = f"no matured zones in {zpath.name}"
        return result

    trades = load_trades(symbol, t_stamp, drive, prefix=pref)
    hits = assign_trades_to_zones(zones, trades)
    zone_tuples: list[tuple[int, float, float, int]] = []
    traded_flags: list[bool] = []
    entries: list[int] = []
    exits: list[int] = []
    seen_entry: set[int] = set()
    seen_exit: set[int] = set()

    for z, hit in zip(zones, hits):
        is_traded = hit is not None
        # Prefer zone BREAKOUT_MONDAY (WPBR); fall back to Closed BREAKOUT_DATE (BRT / missing zone col).
        if is_traded:
            bo = z.breakout_yyyymmdd or (hit.breakout_yyyymmdd if hit else 0)
        else:
            bo = 0
        zone_tuples.append((cloud_start_yyyymmdd(z), z.lo, z.hi, bo))
        traded_flags.append(is_traded)

    # Entry/exit markers from full ledger (deduped by date)
    for t in trades:
        if t.entry_yyyymmdd and t.entry_yyyymmdd not in seen_entry:
            seen_entry.add(t.entry_yyyymmdd)
            entries.append(t.entry_yyyymmdd)
        if t.exit_yyyymmdd and t.exit_yyyymmdd not in seen_exit:
            seen_exit.add(t.exit_yyyymmdd)
            exits.append(t.exit_yyyymmdd)

    entries.sort()
    exits.sort()

    suffix = (name_suffix or "zones_trades").strip("_")
    fname = f"{pref}_{symbol.upper()}_{suffix}.ts"
    label = study_label or (
        f"{pref} {symbol.upper()} {suffix}" if name_suffix else f"{pref} {symbol.upper()}"
    )
    extra = (
        f"Source zones={zpath.name}; trades={pref}_Closed/Open_{t_stamp}; "
        f"traded={sum(traded_flags)} grey={len(traded_flags) - sum(traded_flags)}"
    )
    out = write_ts_files(
        symbol,
        zone_tuples,
        entries,
        exits,
        output_dir=output_dir,
        extra_header=extra,
        traded=traded_flags,
        study_label=label,
        filename=fname,
    )

    result.zones = len(zone_tuples)
    result.traded = sum(traded_flags)
    result.untraded = len(traded_flags) - result.traded
    result.entries = len(entries)
    result.exits = len(exits)
    result.filename = fname
    result.path = str(out)
    return result


def write_readme(
    output_dir: Path,
    results: list[SymbolResult],
    *,
    prefix: str = DEFAULT_PREFIX,
    name_suffix: str | None = None,
    notes: list[str] | None = None,
) -> Path:
    pref = _norm_prefix(prefix)
    suffix = (name_suffix or "zones_trades").strip("_")
    file_pat = f"{pref}_<SYMBOL>_{suffix}.ts"
    study_ex = f"{pref} NVDA {suffix}" if name_suffix else f"{pref} NVDA zones"
    lines = [
        f"# {pref} MarkTen ThinkorSwim studies",
        "",
        f"Generated from engine `{pref}_ZONES_*` (all matured zones) + `{pref}_Closed` / `{pref}_Open` ledgers.",
        "",
    ]
    if notes:
        lines.extend(notes)
        lines.append("")
    lines.extend(
        [
            "## Naming",
            "",
            f"- File: `{file_pat}`",
            f"- Study header: `{pref} <SYMBOL>{' ' + suffix if name_suffix else ''}` "
            "(paste into Studies → Create; name the study to match)",
            "",
            "## Colors",
            "",
            "- **Traded** zones (ZONE_CENTER matches a Closed/Open trade): Orange → Yellow → Blue → Cyan → Violet cycle",
            "- **Untraded** zones: Gray clouds only (no BO bubble)",
            "- Entries: white arrows; Exits: red arrows",
            "",
            "## Index",
            "",
            "| Symbol | Zones | Traded (colored) | Untraded (grey) | Entries | Exits | Zones stamp | Trades stamp | File |",
            "|--------|------:|-----------------:|----------------:|--------:|------:|-------------|--------------|------|",
        ]
    )
    for r in results:
        if r.error or r.skipped:
            note = r.error or r.skipped
            lines.append(
                f"| {r.symbol} | — | — | — | — | — | {r.zones_stamp or '—'} | {r.trades_stamp or '—'} | SKIPPED: {note} |"
            )
        else:
            lines.append(
                f"| {r.symbol} | {r.zones} | {r.traded} | {r.untraded} | {r.entries} | {r.exits} | "
                f"`{r.zones_stamp}` | `{r.trades_stamp}` | `{r.filename}` |"
            )
    lines.extend(
        [
            "",
            "## How to load in ThinkorSwim",
            "",
            "1. Open chart for the symbol",
            "2. Studies → Edit Studies → Create…",
            "3. Paste the `.ts` contents",
            f"4. Name the study e.g. `{study_ex}`",
            "",
        ]
    )
    path = output_dir / "README.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Generate MarkTen TOS zone studies from drive exports (BRT or WPBR)"
    )
    ap.add_argument(
        "--prefix",
        default=DEFAULT_PREFIX,
        help="Output/ledger prefix: BRT (default) or WPBR. "
        "Controls which ZONES/Closed/Open files are read and study filenames.",
    )
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output directory (default: drive/brt_tos_studies/markten "
        "or drive/wpbr_tos_studies/markten when --prefix WPBR)",
    )
    ap.add_argument(
        "-s",
        "--symbol",
        action="append",
        dest="symbols",
        help="Subset of MarkTen symbols (repeatable). Default: all MarkTen.",
    )
    ap.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Parallel symbol workers (default 4)",
    )
    ap.add_argument(
        "--trades-stamp",
        default=None,
        help="Force Closed/Open ledger stamp (e.g. 260721155448 for zone_low).",
    )
    ap.add_argument(
        "--zones-stamp",
        default=None,
        help="Force <PREFIX>_ZONES_<SYM>_<stamp>.csv (default: latest per symbol).",
    )
    ap.add_argument(
        "--name-suffix",
        default=None,
        help="Filename/study suffix after <PREFIX>_<SYM>_ (default: zones_trades). "
        "Example: ZoneLow -> BRT_META_ZoneLow.ts",
    )
    ap.add_argument(
        "--study-label",
        default=None,
        help="Override thinkScript header label (default: <PREFIX> <SYM> [<suffix>]).",
    )
    args = ap.parse_args(argv)

    pref = _norm_prefix(args.prefix)
    symbols = [s.strip().upper() for s in (args.symbols or MARKTEN)]
    for s in symbols:
        if s not in MARKTEN:
            print(f"WARNING: {s} not in MarkTen list {MARKTEN}", file=sys.stderr)

    if args.output is not None:
        out = Path(args.output).resolve()
    elif pref == "WPBR":
        out = (DRIVE / "wpbr_tos_studies" / "markten").resolve()
    else:
        out = DEFAULT_OUT.resolve()
    out.mkdir(parents=True, exist_ok=True)
    print(f"Prefix: {pref}")
    print(f"Output: {out}\n")
    if args.trades_stamp:
        print(f"Trades stamp: {args.trades_stamp}")
    if args.zones_stamp:
        print(f"Zones stamp:  {args.zones_stamp}")
    if args.name_suffix:
        print(f"Name suffix:  {args.name_suffix}")
    print()

    errors = 0

    def _run(sym: str) -> SymbolResult:
        try:
            return generate_symbol(
                sym,
                out,
                DRIVE,
                prefix=pref,
                zones_stamp=args.zones_stamp,
                trades_stamp=args.trades_stamp,
                name_suffix=args.name_suffix,
                study_label=args.study_label,
            )
        except Exception as exc:  # noqa: BLE001
            return SymbolResult(symbol=sym, error=str(exc))

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futs = {pool.submit(_run, sym): sym for sym in symbols}
        by_sym: dict[str, SymbolResult] = {}
        for fut in as_completed(futs):
            r = fut.result()
            by_sym[r.symbol] = r
            if r.error or r.skipped:
                errors += 1
                print(f"SKIP/ERROR {r.symbol}: {r.error or r.skipped}")
            else:
                print(
                    f"OK {r.symbol}: zones={r.zones} traded={r.traded} grey={r.untraded} "
                    f"entries={r.entries} exits={r.exits} -> {r.filename}"
                )

    results = [by_sym[s] for s in symbols if s in by_sym]
    notes: list[str] = ["## Run settings", "", f"- File prefix: `{pref}`"]
    if args.trades_stamp:
        notes.append(f"- Trades stamp: `{args.trades_stamp}`")
    if args.zones_stamp:
        notes.append(f"- Zones stamp: `{args.zones_stamp}`")
    if args.name_suffix:
        notes.append(f"- Name suffix: `{args.name_suffix}`")
    if pref == "WPBR":
        notes.extend(
            [
                "",
                "## WPBR parity (from run_wpbr.bat / Audit)",
                "",
                "- `target_pct=1.22`, `stop_pct=0.91`, `band_pct=0.015`",
                "- `entry_start_date=2016-01-01`, `wpbr_second_chance_after_win=true`",
                "- `wpbr_breakout_confirmation=0.03`, `wpbr_max_days_after_retest=2`",
            ]
        )
    readme = write_readme(
        out, results, prefix=pref, name_suffix=args.name_suffix, notes=notes
    )
    print(f"\nWrote {readme}")
    print("Done.")
    return 1 if errors and all(r.skipped or r.error for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
