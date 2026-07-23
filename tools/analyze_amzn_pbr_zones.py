"""Backward-compat: run tools/analyze_amzn_wpbr_zones.py instead."""
from __future__ import annotations

import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("analyze_amzn_wpbr_zones.py")), run_name="__main__")
