"""Load per-symbol zone/trade data from a spreadsheet-exported CSV."""
from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path

ZONE_TYPES = {"zone", "z"}
ENTRY_TYPES = {"entry", "in", "buy"}
EXIT_TYPES = {"exit", "out", "sell"}

REQUIRED_COLUMNS = ("record_type", "pivot_date", "zone_low", "zone_high", "breakout_date", "trade_date")

_DATE_FORMATS = (
    "%Y%m%d",
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%m-%d-%Y",
    "%m-%d-%y",
    "%Y/%m/%d",
    "%d/%m/%Y",
)


def _norm_header(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def parse_date(value: object, *, field: str, row_num: int) -> int:
    """Return YYYYMMDD int; empty -> 0."""
    if value is None:
        return 0
    if isinstance(value, float):
        if value != value:  # NaN
            return 0
        if value == int(value) and 19000101 <= int(value) <= 21001231:
            return int(value)
        value = str(int(value)) if value == int(value) else str(value)
    text = str(value).strip()
    if not text or text.lower() in {"0", "na", "n/a", "none", "-"}:
        return 0
    if text.isdigit() and len(text) == 8:
        return int(text)
    for fmt in _DATE_FORMATS:
        try:
            return int(datetime.strptime(text, fmt).strftime("%Y%m%d"))
        except ValueError:
            continue
    raise ValueError(f"row {row_num}: cannot parse {field} date {text!r} (use YYYYMMDD or M/D/YYYY)")


def parse_float(value: object, *, field: str, row_num: int) -> float:
    if value is None:
        raise ValueError(f"row {row_num}: missing {field}")
    text = str(value).strip().replace(",", "")
    if not text:
        raise ValueError(f"row {row_num}: missing {field}")
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"row {row_num}: invalid {field} {text!r}") from exc


def load_symbol_csv(
    path: Path,
    *,
    symbol: str | None = None,
) -> tuple[str, list[tuple[int, float, float, int]], list[int], list[int], str]:
    """
    Read one symbol CSV.

    Columns (header row required):
      record_type, pivot_date, zone_low, zone_high, breakout_date, trade_date

    record_type values:
      zone  — one row per zone cloud (+ optional BO date)
      entry — white IN marker (trade_date)
      exit  — red OUT marker (trade_date)

    Symbol: pass --symbol on CLI, or use filename stem (e.g. NFLX.csv).
    """
    path = Path(path)
    sym = (symbol or path.stem).strip().upper()
    if not sym:
        raise ValueError("symbol is required (use --symbol or name the file SYMBOL.csv)")

    zones: list[tuple[int, float, float, int]] = []
    entries: list[int] = []
    exits: list[int] = []
    notes: list[str] = []

    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError(f"{path}: empty file")
        colmap = {_norm_header(h): h for h in reader.fieldnames if h}
        missing = [c for c in REQUIRED_COLUMNS if c not in colmap]
        if missing:
            raise ValueError(
                f"{path}: missing column(s) {missing}. "
                f"Expected: {', '.join(REQUIRED_COLUMNS)}"
            )

        for row_num, row in enumerate(reader, start=2):
            rtype = str(row.get(colmap["record_type"], "")).strip().lower()
            if not rtype or rtype.startswith("#"):
                continue

            if rtype in ZONE_TYPES:
                pivot = parse_date(row.get(colmap["pivot_date"]), field="pivot_date", row_num=row_num)
                lo = parse_float(row.get(colmap["zone_low"]), field="zone_low", row_num=row_num)
                hi = parse_float(row.get(colmap["zone_high"]), field="zone_high", row_num=row_num)
                bo = parse_date(row.get(colmap["breakout_date"]), field="breakout_date", row_num=row_num)
                if pivot <= 0:
                    raise ValueError(f"row {row_num}: zone needs pivot_date")
                if lo >= hi:
                    raise ValueError(f"row {row_num}: zone_low must be less than zone_high")
                zones.append((pivot, lo, hi, bo))
            elif rtype in ENTRY_TYPES:
                d = parse_date(row.get(colmap["trade_date"]), field="trade_date", row_num=row_num)
                if d <= 0:
                    raise ValueError(f"row {row_num}: entry needs trade_date")
                entries.append(d)
            elif rtype in EXIT_TYPES:
                d = parse_date(row.get(colmap["trade_date"]), field="trade_date", row_num=row_num)
                if d <= 0:
                    raise ValueError(f"row {row_num}: exit needs trade_date")
                exits.append(d)
            elif rtype in {"note", "comment", "header"}:
                note = str(row.get(colmap["trade_date"], "") or row.get(colmap["pivot_date"], "")).strip()
                if note:
                    notes.append(note)
            else:
                raise ValueError(
                    f"row {row_num}: unknown record_type {rtype!r} "
                    f"(use zone, entry, or exit)"
                )

    if not zones:
        raise ValueError(f"{path}: no zone rows found")

    extra_header = "; ".join(notes) if notes else ""
    return sym, zones, entries, exits, extra_header
