"""Live system F: tennis spread T0 cheapest Yes in [0.20, 0.50).

Sport tennis only (ATP/WTA/ITF/Challenger as E if those markets exist).
Bet type spread only — not moneyline, not Points Total. At T0 buy 1 contract
on the cheapest tennis spread Yes with 0.20 <= px < 0.50 (20¢ included, 50¢
skipped; 20–49 inclusive cents). After-fee cash. Cheapest of available
venues/sides on that match. Stake $1, max_open default 2.

Skip if Tennis crossover (B) already has this match (same as E skip-if-B).
Does not flatten E leftovers. Leftover-watch must not hedge F. One contract.
Sequential hard-first is not required (T0 like E, not lock-gap A). Does not
require pair <= 1.05. REST recheck before send. Poly US FOK; copy E T0 send.

Does not start a second live_strategy_b.py. Does not sell. Does not wire GTC.
Off until Paul runs the CLI. Do not auto-start this process from a research job.
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
import live_tennis_t0_dog  # noqa: E402
import prediction_systems as systems  # noqa: E402
from prediction_paths import RAW_DIR as RAW  # noqa: E402

SID = "tennis_t0_spread"
B_WATCH = RAW / "strategy_b_watch.json"


def _norm_game(title: str) -> str:
    return " ".join(str(title or "").lower().split())


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _row_filled(row: dict) -> bool:
    last = row.get("last_order") if isinstance(row.get("last_order"), dict) else {}
    qty = live_lock_orders._dec(last.get("fill_qty") or last.get("confirm_qty") or row.get("fill_qty"))
    return bool(qty is not None and qty >= 1)


def already_filled_match(f_status: dict | None, title: str) -> str:
    """Skip reason if F already filled a spread Yes on this tennis match."""
    if not isinstance(f_status, dict) or not str(title or "").strip():
        return ""
    for row in f_status.get("matches") or []:
        if not isinstance(row, dict):
            continue
        game = str(row.get("game") or "")
        if not (live_t0_yes.same_game(game, title) or _norm_game(game) == _norm_game(title)):
            continue
        stage = str(row.get("stage") or "")
        if stage in live_t0_yes.E_FILL_STAGES or _row_filled(row):
            if _row_filled(row) or stage in {"filled", "holding", "open", "settled"}:
                return "already filled spread Yes on this match"
    return ""


def b_holds_match(title: str, *, sport: str = "tennis", b_status: dict | None = None, path: Path | None = None) -> bool:
    """Same skip-if-B as E. Reads B's watch file. Does not import live_strategy_b."""
    return live_tennis_t0_dog.b_holds_match(title, sport=sport, b_status=b_status, path=path or B_WATCH)


def plan_send(
    *,
    quotes: list[dict] | None = None,
    title: str = "",
    sport: str = "tennis",
    b_status: dict | None = None,
    f_status: dict | None = None,
    open_n: int = 0,
    max_open: int = 2,
) -> dict:
    """Pure F decision. Does not POST. Tests and consider_game share this."""
    if str(sport or "").strip().lower() not in {"", "tennis"}:
        return {"action": "skip", "reason": "not tennis", "best": None}
    rows = [row for row in (quotes or []) if str(row.get("kind") or "").lower() == "spread"]
    if not rows:
        return {"action": "skip", "reason": "not spread / moneyline or total", "best": None}
    if b_holds_match(title, sport=sport, b_status=b_status):
        return {"action": "skip", "reason": "B already on match", "best": None}
    why = already_filled_match(f_status, title)
    if why:
        return {"action": "skip", "reason": why, "best": None}
    if int(open_n) >= int(max_open):
        return {"action": "skip", "reason": "max_open", "best": None}
    best = systems.pick_cheapest_spread_yes(rows)
    if best is None:
        return {"action": "skip", "reason": "no spread Yes in [0.20, 0.50)", "best": None}
    ask = systems._dec(best.get("yes") if best.get("yes") is not None else best.get("ask"))
    if ask is None or not systems.in_f_spread_band(ask):
        return {"action": "skip", "reason": f"ask {ask} not in [0.20, 0.50)", "best": best}
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
    return {
        "action": "send",
        "reason": "t0 cheapest tennis spread",
        "dog": side,
        "fav": side,
        "venue": venue,
        "ask": ask,
        "best": best,
        "qty": n,
        "number": str(best.get("number") or ""),
        "kind": "spread",
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
