"""Live system C: college football T0 favorite Yes in (0.50, 0.90).

Baseline arm t0_fav_lt_90 restricted to college football moneyline.
Best venue Yes ask for the T0 favorite. Hold to settlement. One shot at T0.

Does not start a second live_strategy_b.py. Does not sell. Does not wire GTC.
Research-candidate live. Not gold. Not DailyRun.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_t0_yes  # noqa: E402

SID = "cfb_favorite"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--tick"]:
        snap = live_t0_yes.tick(SID)
        print({"open": snap.get("currently_open"), "updated_at": snap.get("updated_at")})
        return 0
    if argv[:1] == ["--status"]:
        import json

        print(json.dumps(live_t0_yes.load_status(SID), indent=2, default=str))
        return 0
    live_t0_yes.loop(SID)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
