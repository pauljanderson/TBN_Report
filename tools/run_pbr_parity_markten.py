"""Backward-compat: run tools/run_wpbr_parity_markten.py instead."""
from __future__ import annotations

import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("run_wpbr_parity_markten.py")), run_name="__main__")
