"""Drive vs local paths for the prediction-market stamp.

HTML reports stay under drive/ so Google Drive sync and ntfy keep working.
Raw jsonl, locks, balances, snapshots, huge logs, and stamp pycache live
under local/ (this PC only; not synced to Drive).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAMP_NAME = "prediction_market_arb_exhaustive_20261017"
DRIVE_STAMP = ROOT / "drive" / "paul_experiments" / STAMP_NAME
LOCAL_STAMP = ROOT / "local" / "paul_experiments" / STAMP_NAME
RAW_DIR = LOCAL_STAMP / "raw"
PYCACHE_DIR = LOCAL_STAMP / "__pycache__"
ORDERS_STOP = RAW_DIR / "orders_stopped.json"
ONE_LEG_WATCH = RAW_DIR / "one_leg_watch.json"

# Aliases used by writers: STAMP is HTML/output; RAW is bulky local data.
STAMP = DRIVE_STAMP
RAW = RAW_DIR


def ensure_dirs() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PYCACHE_DIR.mkdir(parents=True, exist_ok=True)
    DRIVE_STAMP.mkdir(parents=True, exist_ok=True)
