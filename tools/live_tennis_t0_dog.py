"""Live system E: tennis moneyline T0 dog Yes in (0.10, 0.50).

P2 freeze. Unique cheaper player at trusted T0. Buy 1 contract IOC/FOK on
the cheapest venue Yes. Poly FOK; size < qty skip. REST recheck. Hold to
settlement. No 50-cross, no favorite dip, no both-Yes.

Skip if Tennis crossover (B) already has this match (absorbed / T0 sent).
If B skipped all-in C>1.05, E may still send the dog. Skip-if-B-open lives
here so a Patel 50-cross edit of live_strategy_b.py is not required.

Does not start a second live_strategy_b.py. Does not sell. Does not wire GTC.
Research-candidate live. Not gold. Not DailyRun. Off until Paul runs CLI.
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
from prediction_paths import RAW_DIR as RAW  # noqa: E402

SID = "tennis_t0_dog"
T0_C_OVER = "t0_allin_c_over_105"
B_WATCH = RAW / "strategy_b_watch.json"
B_HAS_STAGES = {
    "waiting_t0",
    "t0_filled_waiting_50_cross",
    "waiting_cross",
    "waiting_fav_dip",
    "fav_gtc_resting",
    "one_leg_miss",
    "absorbed",
}


def _norm_game(title: str) -> str:
    return " ".join(str(title or "").lower().split())


def _same_match(left: str, right: str) -> bool:
    return live_t0_yes.same_game(left, right)


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _t0_sent(row: dict) -> bool:
    t0 = row.get("t0_yes") if isinstance(row.get("t0_yes"), dict) else {}
    for slot in t0.values():
        if not isinstance(slot, dict):
            continue
        qty = live_lock_orders._dec(slot.get("fill_qty") or slot.get("confirm_qty") or slot.get("qty"))
        if qty is not None and qty >= 1:
            return True
    last = row.get("last_order") if isinstance(row.get("last_order"), dict) else {}
    qty = live_lock_orders._dec(last.get("fill_qty") or last.get("confirm_qty"))
    return bool(qty is not None and qty >= 1)


def _c_over_skip(row: dict) -> bool:
    skip = str(row.get("skip_reason") or "")
    note = str(row.get("note") or "")
    return skip == T0_C_OVER or T0_C_OVER in note


def b_holds_match(title: str, *, sport: str = "tennis", b_status: dict | None = None, path: Path | None = None) -> bool:
    """True when B already has this tennis match (absorbed / T0 sent / waiting).

    Reads B's watch file only. Does not import live_strategy_b. If B skipped
    all-in C>1.05, return False so E may still send the dog.
    """
    if str(sport or "").strip().lower() not in {"", "tennis"}:
        return False
    want = _norm_game(title)
    if not want:
        return False
    data = b_status if isinstance(b_status, dict) else _load_json(path or B_WATCH)
    for row in data.get("matches") or []:
        if not isinstance(row, dict):
            continue
        game = str(row.get("game") or "")
        key = str(row.get("key") or "")
        if not (_same_match(game, title) or _norm_game(key) == want or _norm_game(game) == want):
            continue
        if _c_over_skip(row):
            return False
        stage = str(row.get("stage") or "")
        if stage in B_HAS_STAGES or _t0_sent(row):
            return True
    return False


def plan_send(
    *,
    side_asks: dict,
    quotes: list[dict] | None = None,
    title: str = "",
    sport: str = "tennis",
    b_status: dict | None = None,
    e_status: dict | None = None,
    open_n: int = 0,
    max_open: int = 2,
) -> dict:
    """Pure E decision. Does not POST. Tests and consider_game share this."""
    dog = systems.pick_dog_primary(side_asks)
    if not dog:
        return {"action": "skip", "reason": "no unique dog / 50-50 / junk", "dog": None}
    if b_holds_match(title, sport=sport, b_status=b_status):
        return {"action": "skip", "reason": "B already on match", "dog": dog}
    why = live_t0_yes.e_already_filled_dog(e_status, title, dog)
    if why:
        return {"action": "skip", "reason": why, "dog": dog}
    if int(open_n) >= int(max_open):
        return {"action": "skip", "reason": "max_open", "dog": dog}
    rows = list(quotes or [])
    if not rows:
        for name, px in (side_asks or {}).items():
            rows.append({"venue": "kalshi", "side": name, "yes": px, "ask": px, "team": name})
    best = systems.best_venue_yes(rows, dog, for_send=True)
    if best is None:
        return {"action": "skip", "reason": "no venue Yes", "dog": dog}
    ask = systems._dec(best.get("yes") if best.get("yes") is not None else best.get("ask"))
    if ask is None or not systems.in_dog_band(ask):
        return {"action": "skip", "reason": f"ask {ask} not in (0.10, 0.50)", "dog": dog}
    venue = str(best.get("venue") or "").lower()
    if venue == "polymarket":
        spec = dict(best.get("spec") or {})
        spec.setdefault("venue", "polymarket")
        if best.get("yes_size") is not None:
            spec.setdefault("quote_size", best.get("yes_size"))
            spec.setdefault("yes_size", best.get("yes_size"))
        skip = live_lock_orders.poly_size_lt_qty_skip(spec, rest=False)
        if skip:
            return {"action": "skip", "reason": skip, "dog": dog, "venue": venue, "ask": ask}
    n = systems.contracts_for_stake(ask, size=1, stake_usd=Decimal("1"))
    if n < 1:
        return {"action": "skip", "reason": f"ask {ask} over stake", "dog": dog}
    return {
        "action": "send",
        "reason": "t0 dog",
        "dog": dog,
        "venue": venue,
        "ask": ask,
        "best": best,
        "qty": n,
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
