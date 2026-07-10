"""Canonical sheet zone ladders (center, lower, upper per line — tab or space separated)."""

from __future__ import annotations

from pathlib import Path

TOOLS = Path(__file__).resolve().parent

DEFAULT_SYMBOLS = [
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "NVDA",
    "META",
    "TSLA",
    "NFLX",
]

# One file per symbol under tools/. Format: CENTER<TAB>LOWER<TAB>UPPER (no header).
SHEET_ZONE_LEDGER: dict[str, Path] = {
    "AAPL": TOOLS / "aapl_sheet_zones.txt",
    "MSFT": TOOLS / "msft_sheet_zones.txt",
    "GOOGL": TOOLS / "googl_sheet_zones.txt",
    "AMZN": TOOLS / "amzn_sheet_zones.txt",
    "NVDA": TOOLS / "nvda_sheet_zones.txt",
    "META": TOOLS / "meta_sheet_zones.txt",
    "TSLA": TOOLS / "tsla_sheet_zones.txt",
    "NFLX": TOOLS / "nflx_sheet_zones.txt",
}
