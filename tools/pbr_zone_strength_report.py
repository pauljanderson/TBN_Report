"""Backward-compat: run tools/wpbr_zone_strength_report.py instead."""
from __future__ import annotations

import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("wpbr_zone_strength_report.py")), run_name="__main__")
