"""Canonical **BRT tab** zone ladders (center, lower, upper per line).

Separate from YH zone ledgers in ``sheet_zone_ledgers.py``.
"""

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
BRT_SHEET_ZONE_LEDGER: dict[str, Path] = {
    "AAPL": TOOLS / "aapl_brt_sheet_zones.txt",
    "AMZN": TOOLS / "amzn_brt_sheet_zones.txt",
    "GOOGL": TOOLS / "googl_brt_sheet_zones.txt",
    "META": TOOLS / "meta_brt_sheet_zones.txt",
    "MSFT": TOOLS / "msft_brt_sheet_zones.txt",
    "NFLX": TOOLS / "nflx_brt_sheet_zones.txt",
    "NVDA": TOOLS / "nvda_brt_sheet_zones.txt",
    "TSLA": TOOLS / "tsla_brt_sheet_zones.txt",
}
