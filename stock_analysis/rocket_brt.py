#!/usr/bin/env python3
"""Backward-compatible shim → TBN engine (`rocket_tbn.py`).

Prefer::

    python stock_analysis/rocket_tbn.py ...

This module keeps ``import rocket_brt`` / ``from rocket_brt import ...`` working for
tools and optimizers. The Break-and-ReTest *system* is still **BRT**
(``brt_zones=true``, ``BRT_*`` outputs, ``run_brt.bat``).

See ``docs/TBN_VS_BRT.md``.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

try:
    from rocket_tbn import *  # noqa: F401, F403
    from rocket_tbn import main  # noqa: F401
    import rocket_tbn as _tbn
except ImportError:  # package-style: stock_analysis.rocket_brt
    from stock_analysis.rocket_tbn import *  # type: ignore  # noqa: F401, F403
    from stock_analysis.rocket_tbn import main  # type: ignore  # noqa: F401
    import stock_analysis.rocket_tbn as _tbn  # type: ignore

# Private helpers (tools often `from rocket_brt import _load_symbol_data`, etc.)
for _k, _v in vars(_tbn).items():
    if _k.startswith("_") and not _k.startswith("__"):
        globals()[_k] = _v
del _k, _v, _tbn

if __name__ == "__main__":
    raise SystemExit(main())
