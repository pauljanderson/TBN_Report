"""Live system G: soccer Points Total T0 cheapest Yes in [0.20, 0.50).

Sport soccer only (English Premier League (EPL), Major League Soccer (MLS),
UEFA Champions League (UCL), and other soccer leagues already in the catalog —
not NFL, college football, or tennis). Bet type Points Total (over/under) only —
not moneyline, not spread. At T0 buy 1 contract on the cheapest soccer Points
Total Yes with 0.20 <= px < 0.50 (20¢ included, 50¢ skipped; 20–49 inclusive
cents). After-fee cash. Cheapest of Kalshi / Polymarket US / Gemini / Novig
for that game+total line+side — not cheapest across A–F trading systems.
Skip Novig if fee unknown (label). Stake $1, max_open default 2.

Skip if Lock gap (A) already locking that same total (game + line). Do not
leftover-hedge G. B/E/F are tennis — no skip-if-B by match title; skip only
on the same game-key if it collides. D is T0 spreads 51–89, a different bet
type. One contract. REST recheck before send. Poly US FOK; copy E/F T0 send.

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
import prediction_systems as systems  # noqa: E402
from prediction_paths import RAW_DIR as RAW  # noqa: E402

SID = "soccer_t0_total"
B_WATCH = RAW / "strategy_b_watch.json"
E_WATCH = RAW / "tennis_t0_dog_watch.json"
F_WATCH = RAW / "tennis_t0_spread_watch.json"
OPEN_STAGES = {"waiting_t0", "filled", "holding", "open", "absorbed"}


def _norm_game(title: str) -> str:
    return " ".join(str(title or "").lower().split())


def _norm_line(value) -> str:
    text = str(value or "").strip().lower()
    try:
        return f"{float(text):.1f}"
    except (TypeError, ValueError):
        return text


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


def is_soccer_sport(sport: str) -> bool:
    return "soccer" in " ".join(str(sport or "").lower().split())


def already_filled_match(g_status: dict | None, title: str) -> str:
    """Skip reason if G already filled a Points Total Yes on this soccer game."""
    if not isinstance(g_status, dict) or not str(title or "").strip():
        return ""
    for row in g_status.get("matches") or []:
        if not isinstance(row, dict):
            continue
        game = str(row.get("game") or "")
        if not (live_t0_yes.same_game(game, title) or _norm_game(game) == _norm_game(title)):
            continue
        stage = str(row.get("stage") or "")
        if stage in live_t0_yes.E_FILL_STAGES or _row_filled(row):
            if _row_filled(row) or stage in {"filled", "holding", "open", "settled"}:
                return "already filled Points Total Yes on this game"
    return ""


def _lock_parts(bet_key: str) -> dict:
    parts = str(bet_key or "").split("\t")
    while len(parts) < 6:
        parts.append("")
    return {
        "sport": parts[0],
        "game_code": parts[1],
        "date": parts[2],
        "kind": parts[3],
        "side": parts[4],
        "number": parts[5],
    }


def a_holds_same_total(
    title: str,
    number: str = "",
    *,
    lock_keys: list[str] | None = None,
    lock_rows: list[dict] | None = None,
) -> str:
    """True skip reason when Lock gap (A) is already locking this game+total line.

    Same total = same soccer game and same Points Total number (Over or Under).
    A moneyline or spread lock on the same kickoff does not block G.
    """
    if not str(title or "").strip() or not str(number or "").strip():
        return ""
    want_line = _norm_line(number)
    rows = [row for row in (lock_rows or []) if isinstance(row, dict)]
    keys = list(lock_keys) if lock_keys is not None else None
    if keys is None and not rows:
        try:
            keys = list(live_lock_orders.open_lock_keys())
        except Exception:
            keys = []
        try:
            for watch in live_lock_orders.load_all_watches():
                if isinstance(watch, dict):
                    rows.append(watch)
        except Exception:
            pass
    if keys:
        for key in keys:
            parts = _lock_parts(key)
            if str(parts.get("kind") or "").strip().lower() != "total":
                continue
            if _norm_line(parts.get("number")) != want_line:
                continue
            sport = str(parts.get("sport") or "").strip().lower()
            if sport and not is_soccer_sport(sport) and sport not in {"lock", ""}:
                continue
            code = str(parts.get("game_code") or "").strip().lower()
            title_l = _norm_game(title)
            if code and len(code) >= 3 and code in title_l.replace(" ", ""):
                return "A already locking this total"
            rows.append({"bet_key": key, "kind": "total", "number": parts.get("number"), "sport": sport, "game": ""})
    for row in rows:
        key = str(row.get("bet_key") or "")
        parts = _lock_parts(key) if key else {}
        kind = str(row.get("kind") or row.get("market_type") or parts.get("kind") or "").strip().lower()
        if kind != "total":
            continue
        line = row.get("number") if row.get("number") not in (None, "") else parts.get("number")
        if _norm_line(line) != want_line:
            continue
        game = str(row.get("game") or row.get("title") or "")
        sport = str(row.get("sport") or parts.get("sport") or "")
        if game:
            if live_t0_yes.same_game(game, title) or _norm_game(game) == _norm_game(title):
                return "A already locking this total"
            continue
        if sport and not is_soccer_sport(sport) and str(sport).lower() not in {"lock", ""}:
            continue
    return ""


def same_game_key_held(
    key: str,
    title: str = "",
    *,
    b_status: dict | None = None,
    e_status: dict | None = None,
    f_status: dict | None = None,
) -> str:
    """Skip only when B/E/F already hold this exact game-key (collision).

    B/E/F are tennis. Soccer titles do not skip-if-B. Same key is a collision.
    """
    want = str(key or "").strip()
    if not want:
        return ""
    bags = (
        ("B", b_status),
        ("E", e_status),
        ("F", f_status),
    )
    for letter, status in bags:
        if not isinstance(status, dict):
            continue
        for row in status.get("matches") or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("key") or "").strip() != want:
                continue
            stage = str(row.get("stage") or "")
            if stage in OPEN_STAGES or _row_filled(row):
                return f"{letter} already on same game-key"
    return ""


def _load_watch(path: Path) -> dict:
    return _load_json(path)


def plan_send(
    *,
    quotes: list[dict] | None = None,
    title: str = "",
    sport: str = "soccer",
    key: str = "",
    b_status: dict | None = None,
    e_status: dict | None = None,
    f_status: dict | None = None,
    g_status: dict | None = None,
    lock_keys: list[str] | None = None,
    lock_rows: list[dict] | None = None,
    open_n: int = 0,
    max_open: int = 2,
) -> dict:
    """Pure G decision. Does not POST. Tests and consider_game share this."""
    if not is_soccer_sport(sport) and str(sport or "").strip():
        return {"action": "skip", "reason": "not soccer", "best": None}
    rows = [row for row in (quotes or []) if str(row.get("kind") or "").lower() == "total"]
    if not rows:
        return {"action": "skip", "reason": "not Points Total / moneyline or spread", "best": None}
    why = already_filled_match(g_status, title)
    if why:
        return {"action": "skip", "reason": why, "best": None}
    if int(open_n) >= int(max_open):
        return {"action": "skip", "reason": "max_open", "best": None}
    collide = same_game_key_held(
        key,
        title,
        b_status=b_status,
        e_status=e_status,
        f_status=f_status,
    )
    if collide:
        return {"action": "skip", "reason": collide, "best": None}
    in_band = [row for row in rows if systems.in_g_total_band(row.get("yes") if row.get("yes") is not None else row.get("ask"))]
    if not in_band:
        return {"action": "skip", "reason": "no Points Total Yes in [0.20, 0.50)", "best": None}
    fee_ok = [row for row in in_band if systems.total_quote_fee_ok(row)]
    if not fee_ok:
        return {"action": "skip", "reason": "novig fee unknown", "best": None}
    best = systems.pick_cheapest_total_yes(rows)
    if best is None:
        return {"action": "skip", "reason": "no Points Total Yes in [0.20, 0.50)", "best": None}
    ask = systems._dec(best.get("yes") if best.get("yes") is not None else best.get("ask"))
    if ask is None or not systems.in_g_total_band(ask):
        return {"action": "skip", "reason": f"ask {ask} not in [0.20, 0.50)", "best": best}
    number = str(best.get("number") or "")
    a_why = a_holds_same_total(title, number, lock_keys=lock_keys, lock_rows=lock_rows)
    if a_why:
        return {"action": "skip", "reason": a_why, "best": best}
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
        "reason": "t0 cheapest soccer Points Total",
        "dog": side,
        "fav": side,
        "venue": venue,
        "ask": ask,
        "best": best,
        "qty": n,
        "number": number,
        "kind": "total",
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
