#!/usr/bin/env python3
"""Load PBR spreadsheet ground-truth zones and trades from tab-separated paste files."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
SYMBOLS = {"AAPL", "AMZN", "META", "MSFT", "GOOGL", "TSLA", "AMD", "AU", "NVDA", "NFLX"}

PBR_HDR = "Break out upper"
TRADE_HDR = "Entry Date\tEntry Price"


def _parse_price(s: str) -> float | None:
    t = re.sub(r"[^0-9.\-]", "", (s or "").strip())
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _parse_date(s: str) -> str | None:
    s = (s or "").strip()
    if not s or s.upper() in ("#N/A", "N/A", ""):
        return None
    if not re.match(r"^\d{1,2}/\d{1,2}/\d{4}$", s):
        return None
    parts = s.split("/")
    m, d, y = int(parts[0]), int(parts[1]), int(parts[2])
    return f"{y:04d}{m:02d}{d:02d}"


def _parse_int(s: str) -> int | None:
    s = (s or "").strip().replace(",", "")
    if not s or s.upper() in ("#N/A", "N/A"):
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


@dataclass
class PbrZoneRow:
    zone_lower: float
    zone_upper: float
    pivot_date: str  # YYYYMMDD
    breakout_date: str | None
    conf_date: str | None
    next_week_start: str | None
    retest_date: str | None
    rocket_buy_date: str | None
    create_breakout_record: bool = True


@dataclass
class PbrTradeRow:
    entry_date: str  # YYYYMMDD fill date
    entry_price: float
    exit_date: str
    exit_price: float
    result: str


@dataclass
class PbrSymbolGroundTruth:
    zones: list[PbrZoneRow] = field(default_factory=list)
    trades: list[PbrTradeRow] = field(default_factory=list)


def parse_pbr_paste(text: str) -> dict[str, PbrSymbolGroundTruth]:
    out: dict[str, PbrSymbolGroundTruth] = {}
    sym: str | None = None
    mode: str | None = None  # zones | trades

    for raw in text.splitlines():
        line = raw.rstrip("\r")
        stripped = line.strip()
        if not stripped:
            continue
        if stripped in SYMBOLS:
            sym = stripped
            mode = None
            out.setdefault(sym, PbrSymbolGroundTruth())
            continue
        if sym is None:
            continue
        if stripped.startswith(PBR_HDR) or stripped.startswith("Breakout Date\tZone"):
            mode = "zones"
            continue
        if stripped.startswith(TRADE_HDR):
            mode = "trades"
            continue
        parts = line.split("\t")
        if mode == "zones" and len(parts) >= 10:
            zl = _parse_price(parts[6])
            zh = _parse_price(parts[7])
            pivot = _parse_date(parts[9])
            if zl is None or zh is None or pivot is None:
                continue
            create_bo = parts[4].strip() == "1" if len(parts) > 4 else True
            row = PbrZoneRow(
                zone_lower=zl,
                zone_upper=zh,
                pivot_date=pivot,
                breakout_date=_parse_date(parts[5]) if len(parts) > 5 else None,
                conf_date=_parse_date(parts[13]) if len(parts) > 13 else None,
                next_week_start=_parse_date(parts[14]) if len(parts) > 14 else None,
                retest_date=_parse_date(parts[16]) if len(parts) > 16 else None,
                rocket_buy_date=_parse_date(parts[18]) if len(parts) > 18 else None,
                create_breakout_record=create_bo,
            )
            out[sym].zones.append(row)
            continue
        if mode == "trades" and len(parts) >= 8:
            ed = _parse_date(parts[0])
            ep = _parse_price(parts[1])
            xd = _parse_date(parts[2])
            xp = _parse_price(parts[3])
            if ed is None or ep is None or xd is None or xp is None:
                continue
            out[sym].trades.append(
                PbrTradeRow(
                    entry_date=ed,
                    entry_price=ep,
                    exit_date=xd,
                    exit_price=xp,
                    result=parts[6].strip(),
                )
            )
    return out


def load_pbr_ground_truth(path: Path | None = None) -> dict[str, PbrSymbolGroundTruth]:
    path = path or (TOOLS / "pbr_sheet_paste.txt")
    if not path.is_file():
        path = TOOLS / "pbr_meta_msft_paste.txt"
    return parse_pbr_paste(path.read_text(encoding="utf-8-sig"))


PBR_SHEET_GROUND_TRUTH: dict[str, Path] = {
    "AAPL": TOOLS / "pbr_sheet_paste.txt",
    "AMZN": TOOLS / "pbr_sheet_paste.txt",
    "META": TOOLS / "pbr_sheet_paste.txt",
    "MSFT": TOOLS / "pbr_sheet_paste.txt",
}
