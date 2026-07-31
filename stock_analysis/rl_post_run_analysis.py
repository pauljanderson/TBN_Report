#!/usr/bin/env python3
"""RL thin wrapper around ``post_run_analysis.py`` (keeps existing docs/commands).

See ``docs/POST_RUN_ANALYSIS.md``. Equivalent to::

  python stock_analysis/post_run_analysis.py --system RL …

Optional deep missed-move scan::

  python stock_analysis/rl_post_run_analysis.py --stamp … --missed-moves --no-charts
"""from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
_SA = _REPO / "stock_analysis"
if str(_SA) not in sys.path:
    sys.path.insert(0, str(_SA))

try:
    from post_run_analysis import main as _post_main
except ImportError:
    from stock_analysis.post_run_analysis import main as _post_main  # type: ignore


def main(argv=None) -> int:
    return _post_main(argv, default_system="RL")


if __name__ == "__main__":
    raise SystemExit(main())
