#!/usr/bin/env python3
"""Cache the official live-style $250k wallet with $7,500/mo wires OFF.

Used by generate_system_performance_report.py so the published vs-S&P 500
headline is not mixed with 2026 personal transfers. Research overlay only.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "stock_analysis"))

from live_style_sizing import (  # noqa: E402
    ACCOUNT_START,
    ADV_FRAC,
    FREEZE_STAMP,
    MAX_RISK_DOLLAR,
    NAME_CAP_FRAC,
    RISK_FRAC,
    ensure_nowire_vs_spy_cache,
)


def main() -> int:
    pack = ensure_nowire_vs_spy_cache(force=True)
    print(
        f"[nowire] start=${ACCOUNT_START:,.0f} stamp={FREEZE_STAMP} "
        f"lids risk={RISK_FRAC:.0%}/${MAX_RISK_DOLLAR:,.0f} adv={ADV_FRAC:.0%} "
        f"name={NAME_CAP_FRAC:.1%}",
        flush=True,
    )
    print(
        f"[nowire] end=${pack['end']:,.2f} spy=${pack['spy_end']:,.2f} "
        f"beat=${pack['beat']:,.2f} ann={pack['ann_ror']:.4f} "
        f"spy_ann={pack['spy_ann_ror']:.4f} dd={pack['max_dd_pct']:.2f}% "
        f"points={len(pack.get('curve') or [])}",
        flush=True,
    )
    if pack.get("asof"):
        print(f"[nowire] asof={pack['asof']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
