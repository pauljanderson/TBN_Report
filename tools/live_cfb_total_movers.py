"""Live system C: College Football Points Total movers.

Sport college football only. Bet type Points Total (over/under) only — not
moneyline, not spread. At T0 buy 1 contract on a CFB Points Total Yes with
T0 price in 0–19¢ inclusive AND that Yes + opposite Yes ≤ 1.05 (same venue
preferred). After a confirmed fill, rest a GTC sell at paid + 15¢.

Stake $1, max_open default 2. REST recheck before send. Poly US FOK on the
buy. Does not leftover-hedge C. Does not start a second live_strategy_b.py.
Off until Paul runs the CLI. Not gold. Not DailyRun.
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_lock_orders  # noqa: E402
import live_t0_yes  # noqa: E402
import prediction_systems as systems  # noqa: E402

SID = "cfb_total_movers"
KIND = "total"
GTC_OFFSET = systems.GTC_OFFSET_C


def _norm_game(title: str) -> str:
    return " ".join(str(title or "").lower().split())


def _row_filled(row: dict) -> bool:
    last = row.get("last_order") if isinstance(row.get("last_order"), dict) else {}
    qty = live_lock_orders._dec(last.get("fill_qty") or last.get("confirm_qty") or row.get("fill_qty"))
    return bool(qty is not None and qty >= 1)


def is_cfb_sport(sport: str) -> bool:
    return " ".join(str(sport or "").lower().split()) == "college football"


def already_filled_match(status: dict | None, title: str) -> str:
    if not isinstance(status, dict) or not str(title or "").strip():
        return ""
    for row in status.get("matches") or []:
        if not isinstance(row, dict):
            continue
        game = str(row.get("game") or "")
        if not (live_t0_yes.same_game(game, title) or _norm_game(game) == _norm_game(title)):
            continue
        stage = str(row.get("stage") or "")
        if stage in live_t0_yes.E_FILL_STAGES or _row_filled(row) or stage in {
            "exit_gtc_resting",
            "exit_gtc_filled",
        }:
            if _row_filled(row) or stage in {
                "filled",
                "holding",
                "open",
                "settled",
                "exit_gtc_resting",
                "exit_gtc_filled",
            }:
                return "already filled Points Total Yes on this game"
    return ""


def plan_send(
    *,
    quotes: list[dict] | None = None,
    title: str = "",
    sport: str = "college football",
    status: dict | None = None,
    open_n: int = 0,
    max_open: int = 2,
) -> dict:
    """Pure C mover decision. Does not POST."""
    if not is_cfb_sport(sport) and str(sport or "").strip():
        return {"action": "skip", "reason": "not college football", "best": None}
    rows = [row for row in (quotes or []) if str(row.get("kind") or "").lower() == KIND]
    if not rows:
        return {"action": "skip", "reason": "not Points Total / moneyline or spread", "best": None}
    why = already_filled_match(status, title)
    if why:
        return {"action": "skip", "reason": why, "best": None}
    if int(open_n) >= int(max_open):
        return {"action": "skip", "reason": "max_open", "best": None}
    best = systems.pick_mover_yes(rows, kind=KIND, for_send=True)
    if best is None:
        return {
            "action": "skip",
            "reason": "no Points Total Yes in 0-19 with pair <= 1.05",
            "best": None,
        }
    ask = systems._dec(best.get("yes") if best.get("yes") is not None else best.get("ask"))
    if ask is None or not systems.in_mover_band(ask):
        return {"action": "skip", "reason": f"ask {ask} not in 0-19", "best": best}
    opp = systems._dec(best.get("opposite_yes"))
    if opp is None or not systems.mover_pair_ok(ask, opp):
        return {"action": "skip", "reason": "pair > 1.05 or missing opposite", "best": best}
    venue = str(best.get("venue") or "").lower()
    if venue == "polymarket":
        spec = dict(best.get("spec") or {})
        spec.setdefault("venue", "polymarket")
        if best.get("yes_size") is not None:
            spec.setdefault("quote_size", best.get("yes_size"))
            spec.setdefault("yes_size", best.get("yes_size"))
        skip = live_lock_orders.poly_size_lt_qty_skip(spec, rest=False)
        if skip:
            return {"action": "skip", "reason": skip, "best": best, "venue": venue, "ask": ask}
    n = systems.contracts_for_stake(ask, size=1, stake_usd=Decimal("1"))
    if n < 1:
        return {"action": "skip", "reason": f"ask {ask} over stake", "best": best}
    side = str(best.get("side") or best.get("team") or "")
    exit_pay = systems.gtc_exit_pay(ask, GTC_OFFSET)
    return {
        "action": "send",
        "reason": "t0 CFB Points Total mover",
        "dog": side,
        "fav": side,
        "venue": venue,
        "ask": ask,
        "opposite_yes": opp,
        "pair_sum": ask + opp,
        "best": best,
        "qty": n,
        "number": str(best.get("number") or ""),
        "kind": KIND,
        "gtc_offset": GTC_OFFSET,
        "gtc_exit_pay": exit_pay,
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--tick"]:
        snap = live_t0_yes.tick(SID)
        print({"open": snap.get("currently_open"), "updated_at": snap.get("updated_at")})
        return 0
    if argv[:1] == ["--status"]:
        print(json.dumps(live_t0_yes.load_status(SID), indent=2, default=str))
        return 0
    live_t0_yes.loop(SID)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
