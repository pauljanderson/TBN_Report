"""Live system D: T0 spread favorite Yes in (0.50, 0.90).

Any sport on the tape with spread markets except NFL / pro football.
NFL is skipped (`d_skip_nfl_gathering`) until we have enough T0 spread data.
College football and other sports stay on. systems.json D stays on — this is
not a global D off. At most one T0 ticket per game (traditional spread /
wins-by-n, closest to 50¢), then the next game, until max_open.
`--d-all-lines` is ignored. Totals and team totals are tracked but are not D
sends and do not fill leftover slots on the same kickoff.

Does not start a second live_strategy_b.py. Does not sell. Does not wire GTC.
Does not sell existing D tickets. Research-candidate live. Not gold. Not DailyRun.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_t0_yes  # noqa: E402

SID = "spread_t0"


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
