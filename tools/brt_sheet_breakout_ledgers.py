"""Canonical **BRT tab** BH:BQ breakout/retest ledgers."""

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

BRT_SHEET_BREAKOUT_LEDGER: dict[str, Path] = {
    "AAPL": TOOLS / "aapl_brt_sheet_breakout_retest.tsv",
    "AMZN": TOOLS / "amzn_brt_sheet_breakout_retest.tsv",
    "GOOGL": TOOLS / "googl_brt_sheet_breakout_retest.tsv",
    "META": TOOLS / "meta_brt_sheet_breakout_retest.tsv",
    "MSFT": TOOLS / "msft_brt_sheet_breakout_retest.tsv",
    "NFLX": TOOLS / "nflx_brt_sheet_breakout_retest.tsv",
    "NVDA": TOOLS / "nvda_brt_sheet_breakout_retest.tsv",
    "TSLA": TOOLS / "tsla_brt_sheet_breakout_retest.tsv",
}
