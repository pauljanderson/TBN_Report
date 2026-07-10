#!/usr/bin/env python3
"""Aggregate BRT breakout/retest parity stats."""
from __future__ import annotations

import contextlib
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from compare_breakout_retest import _compare_symbol  # noqa: E402


def _g(text: str, pat: str, default: int = 0) -> int:
    m = re.search(pat, text)
    return int(m.group(1)) if m else default


def main() -> int:
    run_id = sys.argv[1] if len(sys.argv) > 1 else "260621201750"
    syms = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "NFLX"]
    print(
        f"{'SYM':6} {'sheet':>5} {'eng':>5} {'zone':>5} {'MR':>4} "
        f"{'rt_ex':>5} {'z_mm':>4} {'s_only':>6} {'e_only':>6}"
    )
    totals = [0] * 8
    for sym in syms:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _compare_symbol(sym, run_id, brt=True, show_mismatches=0)
        t = buf.getvalue()
        row = [
            _g(t, r"sheet rows \(active\): (\d+)"),
            _g(t, r"engine rows: (\d+)"),
            _g(t, r"Matched: (\d+)"),
            _g(t, r"Breakouts matched on Main Row: (\d+)"),
            _g(t, r"Retest exact \(date\+row\):\s+(\d+)"),
            _g(t, r"Zone bound mismatches on MR:\s+(\d+)"),
            _g(t, r"Sheet-only: (\d+)"),
            _g(t, r"Engine-only: (\d+)"),
        ]
        for i, v in enumerate(row):
            totals[i] += v
        print(f"{sym:6} " + " ".join(f"{v:5d}" for v in row))
    print("TOTAL  " + " ".join(f"{v:5d}" for v in totals))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
