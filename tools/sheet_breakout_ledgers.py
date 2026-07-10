"""Canonical sheet BH:BQ breakout/retest ledgers (FILTER spill — own row index)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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

# TSV paths under tools/; add ledgers as they are pasted from the sheet.
SHEET_BREAKOUT_LEDGER: dict[str, Path] = {
    "AAPL": TOOLS / "aapl_sheet_breakout_retest.tsv",
    "MSFT": TOOLS / "msft_sheet_breakout_retest.tsv",
    "GOOGL": TOOLS / "googl_sheet_breakout_retest.tsv",
    "AMZN": TOOLS / "amzn_sheet_breakout_retest.tsv",
    "NVDA": TOOLS / "nvda_sheet_breakout_retest.tsv",
    "META": TOOLS / "meta_sheet_breakout_retest.tsv",
    "TSLA": TOOLS / "tsla_sheet_breakout_retest.tsv",
    "NFLX": TOOLS / "nflx_sheet_breakout_retest.tsv",
}
