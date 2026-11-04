"""Deprecated shim: System C is now College Football total points movers.

Old CLI / process needles that still launch live_cfb_favorite.py keep working.
New code should start live_cfb_total_movers.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from live_cfb_total_movers import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
