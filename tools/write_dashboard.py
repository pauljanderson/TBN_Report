"""Kitchen scoreboard for the live prediction-market bots (systems A–E).

Drive HTML: dashboard.html in the 17 Oct 2026 stamp. Rebuilds from the same
tape as orders_performance.html. Live scoreboard — do not emit What you asked
/ In plain English here (other paul_experiments research HTML still gets that
block). Does not place, cancel, or sell. Does not print secrets. Does not
start a second Tennis crossover (B). Does not bump stake, wire D NFL,
leftover GTC, or retune C=1.05.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import report_page_extras  # noqa: E402
import write_orders_performance as wop  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW  # noqa: E402

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "dashboard.html"
CACHE = RAW / "dashboard_cache.json"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/dashboard.html"
)
LETTERS = tuple(row[0] for row in wop.SYSTEM_SPECS)
SYS_COLOR = {
    "A": "#4c1d95",
    "B": "#0f766e",
    "C": "#b45309",
    "D": "#1d4ed8",
    "E": "#be123c",
    "F": "#0369a1",
    "G": "#15803d",
}


def esc(value) -> str:
    return wop.esc(value)


def now_et() -> datetime:
    return datetime.now(ET)


def midnight_et(when: datetime | None = None) -> datetime:
    stamp = when or now_et()
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=ET)
    local = stamp.astimezone(ET)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def parse_when(value) -> datetime | None:
    if isinstance(value, datetime):
        stamp = value
    else:
        stamp = wop.parse_dt(value)
    if stamp is None:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=ET)
    return stamp.astimezone(ET)


def in_today(value, *, today: datetime | None = None) -> bool:
    stamp = parse_when(value)
    if stamp is None:
        return False
    start = midnight_et(today)
    return start <= stamp < start + timedelta(days=1)


def in_window(value, *, start: datetime | None = None, end: datetime | None = None) -> bool:
    stamp = parse_when(value)
    if stamp is None:
        return False
    if start is not None and stamp < start:
        return False
    if end is not None and stamp >= end:
        return False
    return True


def ddec(value) -> Decimal | None:
    return wop.ddec(value)


def money4_dollar(value) -> str:
    return wop.money4_dollar(value)


def money_signed(value) -> str:
    if value in (None, ""):
        return "—"
    try:
        number = Decimal(str(value))
    except Exception:
        return str(value)
    sign = "+" if number > 0 else ("−" if number < 0 else "")
    return f"{sign}${abs(number).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}"


def system_letter(cluster: dict) -> str:
    letter = str(cluster.get("system_letter") or wop.system_of(cluster) or "")
    return letter if letter in LETTERS else "?"


def system_label(letter: str) -> str:
    spec = wop.SYSTEM_BY_LETTER.get(letter)
    return f"{letter} {spec[2]}" if spec else letter


def is_sent_leg(leg: dict) -> bool:
    if not isinstance(leg, dict):
        return False
    if leg.get("has_io"):
        return True
    http = str(leg.get("http") or "").strip().lower()
    return http not in {"", "0", "pending", "none"}


def _filled_sent_count(cluster: dict) -> int:
    n = 0
    for other in cluster.get("fill_legs") or cluster.get("legs") or []:
        if wop.qty_is_fill(other.get("qty")) and is_sent_leg(other):
            n += 1
    return n


def ticket_realized(leg: dict, cluster: dict):
    """One venue fill → one P&L. Do not stamp the cluster sum on every leg."""
    if wop.qty_is_fill(leg.get("qty")) and leg.get("ticket_pnl") not in (None, ""):
        return ddec(leg.get("ticket_pnl"))
    if _filled_sent_count(cluster) <= 1:
        return ddec(cluster.get("realized"))
    return None


def outcome_of(leg: dict, cluster: dict) -> str:
    filled = wop.qty_is_fill(leg.get("qty"))
    postponed = bool(cluster.get("postponed"))
    settled = wop.cluster_is_settled(cluster)
    open_now = bool(cluster.get("venue_live") or cluster.get("open_legs"))
    if not filled:
        if wop.is_empty_http_fill(leg.get("http"), leg.get("qty")):
            return "missed send"
        return "sent, not filled"
    if postponed and not cluster.get("venue_paid") and not cluster.get("void"):
        return "postponed"
    if settled:
        if cluster.get("void"):
            return "void"
        status = str(leg.get("ticket_status") or "").lower()
        realized = ticket_realized(leg, cluster)
        if status == "void":
            return "void"
        if status == "flatten" and realized is not None and realized == 0:
            return "settled flatten"
        if status == "lose" or (status != "win" and realized is not None and realized < 0):
            return "settled loss"
        if status == "win" or (status != "lose" and realized is not None and realized > 0):
            return "settled win"
        if realized is not None and realized == 0:
            return "settled flat"
        if realized is None and (
            cluster.get("flatten_filled")
            or (cluster.get("complementary") and cluster.get("venue_paid") and not cluster.get("status_unknown"))
        ):
            return "settled"
        if cluster.get("status_unknown") or realized is None:
            return "settled, P&L unknown"
        return "settled"
    if open_now:
        return "open"
    return "filled"


def trade_row(leg: dict, cluster: dict) -> dict:
    filled = wop.qty_is_fill(leg.get("qty"))
    settled = wop.cluster_is_settled(cluster)
    realized = ticket_realized(leg, cluster)
    leftover_hedge = wop.order_types.is_directional_leftover(leg, cluster)
    letter = "A" if leftover_hedge else system_letter(cluster)
    when = parse_when(leg.get("sent_at")) or wop.cluster_when(cluster) or cluster.get("start")
    fee_txt = wop.fee_cell_text(leg) if filled else (wop.money4(leg.get("fee")) if leg.get("fee") not in (None, "") else "")
    after_txt = wop.after_fee_text(leg) if filled else ""
    if filled and after_txt == "" and ddec(leg.get("cash")) is not None and leg.get("fee") in (None, ""):
        after_txt = "fee unknown"
    pnl_txt = ""
    if filled and cluster.get("void"):
        pnl_txt = "void"
    elif filled and cluster.get("postponed") and not cluster.get("venue_paid"):
        pnl_txt = "postponed"
    elif filled and settled and realized is not None:
        pnl_txt = money_signed(realized)
    elif filled and (cluster.get("venue_live") or cluster.get("open_legs")):
        pnl_txt = f"open {money4_dollar(cluster.get('open_cost'))} at risk"
    outcome = outcome_of(leg, cluster)
    success = "yes — venue fill qty > 0" if filled else "no"
    failure = ""
    if not filled and wop.is_empty_http_fill(leg.get("http"), leg.get("qty")):
        failure = "missed send (HTTP OK, confirm 0)"
    elif filled and settled and realized is not None and realized < 0:
        failure = "lost bet (settled with-fee P&L < 0)"
    return {
        "when": wop.fmt_et(when) if when else "",
        "when_raw": when.isoformat() if isinstance(when, datetime) else "",
        "system": letter,
        "system_name": "A leftover" if leftover_hedge else system_label(letter),
        "game": str(cluster.get("game") or ""),
        "league": str(cluster.get("league") or wop.league_of(cluster) or ""),
        "sport": str(cluster.get("sport") or ""),
        "venue": str(leg.get("venue") or ""),
        "side": wop.kitchen_side_label(leg, cluster),
        "order_type": wop.order_types.TYPE_LEFTOVER if leftover_hedge else wop.order_type_of(leg, cluster),
        "wire": wop.money4(leg.get("cash") or leg.get("limit")) if filled or leg.get("cash") not in (None, "") else wop.money4(leg.get("limit")),
        "fee": fee_txt,
        "after_fee": after_txt,
        "http": str(leg.get("http_line") or leg.get("http") or ""),
        "filled": "yes" if filled else "no",
        "filled_label": success,
        "failure": failure,
        "qty": wop.money4(leg.get("qty")),
        "outcome": outcome,
        "pnl": pnl_txt,
        "posted": bool(is_sent_leg(leg)),
        "open": bool(filled and (cluster.get("venue_live") or cluster.get("open_legs")) and not settled),
        "settled": bool(filled and settled),
        "realized": str(realized) if realized is not None else "",
        "order_id": str(leg.get("order_id") or ""),
        "postponed": "yes" if cluster.get("postponed") else "no",
    }


def _leg_no_oid_key(leg: dict) -> tuple:
    return (
        str(leg.get("venue") or ""),
        str(leg.get("instrument") or ""),
        str(leg.get("sent_at") or ""),
        str(leg.get("step") or ""),
        str(leg.get("side") or ""),
        str(leg.get("limit") or ""),
        str(leg.get("qty") or ""),
        str(leg.get("player") or ""),
    )


def flatten_trades(clusters: list[dict]) -> list[dict]:
    """One venue order id → one row. Prefer the cluster that owns the fill."""
    owned: dict[str, tuple] = {}
    no_oid: list[tuple] = []
    for cluster in clusters or []:
        fill_ids = {
            str(leg.get("order_id") or "").strip()
            for leg in (cluster.get("fill_legs") or [])
            if str(leg.get("order_id") or "").strip()
        }
        walked = cluster.get("legs") or cluster.get("fill_legs") or []
        for leg in walked:
            if not is_sent_leg(leg):
                continue
            oid = str(leg.get("order_id") or "").strip()
            if not oid:
                no_oid.append((leg, cluster))
                continue
            prev = owned.get(oid)
            if prev is None or oid in fill_ids:
                owned[oid] = (leg, cluster)
    rows = [trade_row(leg, cluster) for leg, cluster in owned.values()]
    seen_no_oid: set[tuple] = set()
    for leg, cluster in no_oid:
        key = _leg_no_oid_key(leg)
        if key in seen_no_oid:
            continue
        seen_no_oid.add(key)
        rows.append(trade_row(leg, cluster))
    rows.sort(key=lambda row: str(row.get("when_raw") or ""), reverse=True)
    return rows


def _num(row: dict, key: str) -> Decimal:
    return ddec(row.get(key)) or Decimal("0")


def overlay_games(open_rows: list[dict]) -> dict[str, set[str]]:
    games: dict[str, set[str]] = {letter: set() for letter in LETTERS}
    for row in open_rows or []:
        letter = str(row.get("system") or "")
        if letter not in games:
            continue
        key = wop.game_norm(str(row.get("game") or row.get("instrument") or ""))
        if key:
            games[letter].add(key)
    return games


def apply_overlay_open(stats: dict, open_rows: list[dict], *, filled_rows: list[dict] | None = None) -> dict:
    """Open counts come from job_status Positions overlay, not stale cluster flags."""
    games = overlay_games(open_rows)
    if filled_rows is not None:
        filled_games: dict[str, set[str]] = {letter: set() for letter in LETTERS}
        for row in filled_rows:
            if row.get("filled") != "yes":
                continue
            letter = str(row.get("system") or "")
            if letter not in filled_games:
                continue
            key = wop.game_norm(str(row.get("game") or ""))
            if key:
                filled_games[letter].add(key)
        for letter in LETTERS:
            stats["by"][letter]["open"] = len(games[letter] & filled_games[letter])
    else:
        for letter in LETTERS:
            stats["by"][letter]["open"] = len(games[letter])
    stats["open_by"] = {letter: stats["by"][letter]["open"] for letter in LETTERS}
    stats["n_open_today_fills"] = sum(stats["open_by"].values())
    stats["n_open_overlay"] = sum(len(games[letter]) for letter in LETTERS)
    stats["open_dollars"] = sum((ddec(r.get("exposure")) or Decimal("0") for r in open_rows or []), Decimal("0"))
    return stats


def stats_for(
    rows: list[dict],
    clusters: list[dict],
    open_rows: list[dict],
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict:
    picked = []
    for row in rows:
        if start is None and end is None:
            picked.append(row)
            continue
        stamp = parse_when(row.get("when_raw") or row.get("when"))
        if stamp is None:
            continue
        if start is not None and stamp < start:
            continue
        if end is not None and stamp >= end:
            continue
        picked.append(row)
    filled = [row for row in picked if row.get("filled") == "yes"]
    missed = [row for row in picked if str(row.get("outcome") or "") == "missed send"]
    by = {
        letter: {
            "sent": 0,
            "filled": 0,
            "missed": 0,
            "open": 0,
            "settled": 0,
            "pnl": Decimal("0"),
            "invested": Decimal("0"),
            "roi": None,
        }
        for letter in LETTERS
    }
    seen_pnl: set[tuple] = set()
    for row in picked:
        letter = str(row.get("system") or "")
        if letter not in by:
            continue
        slot = by[letter]
        slot["sent"] += 1
        if row.get("filled") == "yes":
            slot["filled"] += 1
        if row.get("outcome") == "missed send":
            slot["missed"] += 1
        if row.get("open"):
            slot["open"] += 1
        if row.get("settled"):
            slot["settled"] += 1
            key = (letter, row.get("game"), row.get("when_raw"), row.get("realized"))
            if key not in seen_pnl and row.get("realized") not in ("", None):
                seen_pnl.add(key)
                slot["pnl"] += _num(row, "realized")
    # Cluster-level P&L / invested (one per filled cluster, not per leg) for the window.
    pnl_by = {letter: Decimal("0") for letter in LETTERS}
    invested_by = {letter: Decimal("0") for letter in LETTERS}
    for cluster in clusters or []:
        if int(cluster.get("n_fill_legs") or 0) < 1:
            continue
        if not wop.cluster_is_settled(cluster):
            continue
        if cluster.get("status_unknown") or cluster.get("void"):
            continue
        when = wop.cluster_when(cluster)
        if start is not None and (when is None or when < start):
            continue
        if end is not None and (when is None or when >= end):
            continue
        letter = system_letter(cluster)
        if letter in pnl_by:
            pnl_by[letter] += ddec(cluster.get("realized")) or Decimal("0")
            invested_by[letter] += wop.invested_from_clusters([cluster])
    for letter in LETTERS:
        by[letter]["pnl"] = pnl_by[letter]
        by[letter]["invested"] = invested_by[letter]
        by[letter]["roi"] = wop.roi_pct(pnl_by[letter], invested_by[letter])
    open_games = set()
    open_dollars = Decimal("0")
    for row in open_rows or []:
        key = wop.game_norm(str(row.get("game") or row.get("instrument") or ""))
        if key:
            open_games.add(key)
        open_dollars += ddec(row.get("exposure")) or Decimal("0")
    total_pnl = sum(pnl_by.values(), Decimal("0"))
    total_invested = sum(invested_by.values(), Decimal("0"))
    stats = {
        "n_sent": len(picked),
        "n_filled": len(filled),
        "n_missed": len(missed),
        "n_open_today_fills": 0,
        "n_settled": sum(1 for row in filled if row.get("settled")),
        "n_open_overlay": len(open_games),
        "open_dollars": open_dollars,
        "pnl": total_pnl,
        "invested": total_invested,
        "roi": wop.roi_pct(total_pnl, total_invested),
        "by": by,
        "pnl_by": pnl_by,
        "invested_by": invested_by,
        "filled_by": {letter: by[letter]["filled"] for letter in LETTERS},
        "missed_by": {letter: by[letter]["missed"] for letter in LETTERS},
        "open_by": {letter: 0 for letter in LETTERS},
        "settled_by": {letter: by[letter]["settled"] for letter in LETTERS},
    }
    return apply_overlay_open(stats, open_rows)


def equity_points(
    clusters: list[dict],
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[tuple[str, float]]:
    items = []
    for cluster in wop.filled_trade_clusters(clusters or []):
        if not wop.cluster_is_settled(cluster):
            continue
        if cluster.get("status_unknown") or cluster.get("void"):
            continue
        when = wop.cluster_when(cluster)
        if when is None:
            continue
        if start is not None and when < start:
            continue
        if end is not None and when >= end:
            continue
        items.append((when, float(ddec(cluster.get("realized")) or 0)))
    items.sort(key=lambda pair: pair[0])
    points = []
    run = 0.0
    if start is not None:
        points.append((wop.fmt_et(start), 0.0))
    for when, pnl in items:
        run += pnl
        points.append((wop.fmt_et(when), round(run, 4)))
    if not points:
        stamp = start or now_et()
        points.append((wop.fmt_et(stamp), 0.0))
    return points


def live_systems(snap: dict | None = None) -> list[dict]:
    if isinstance(snap, dict) and snap.get("systems"):
        rows = list(snap.get("systems") or [])
        if rows:
            return rows
    try:
        import prediction_systems

        jobs = None
        positions = (snap or {}).get("positions") if isinstance(snap, dict) else None
        venue = None
        if isinstance(snap, dict):
            jobs = None
        return prediction_systems.status_rows(jobs, snapshot=venue, positions=positions)
    except Exception:
        return []


def cash_rows() -> list[list]:
    try:
        import venue_cash_local

        store = venue_cash_local.load_unlocked()
    except Exception:
        return []
    out = []
    venues = store.get("venues") if isinstance(store, dict) and isinstance(store.get("venues"), dict) else {}
    for venue in ("kalshi", "gemini", "polymarket", "novig"):
        cash = None
        try:
            import venue_cash_local

            cash = venue_cash_local.cash_of(store, venue)
        except Exception:
            row = venues.get(venue) if isinstance(venues.get(venue), dict) else {}
            cash = ddec(row.get("cash")) if row else ddec(store.get(venue) if isinstance(store, dict) else None)
        out.append([venue, money4_dollar(cash) if cash is not None else "unknown"])
    return out


def open_from_positions(bundle: dict | None) -> list[dict] | None:
    if not isinstance(bundle, dict) or not isinstance(bundle.get("rows"), list):
        return None
    rows = []
    try:
        import job_status_positions as jsp
    except Exception:
        jsp = None
    for item in bundle.get("rows") or []:
        if not isinstance(item, dict):
            continue
        letter = str(item.get("letter") or "")
        game = str(item.get("game") or item.get("name") or "")
        blob = " ".join(str(item.get(k) or "") for k in ("game", "market", "bets", "stage", "name"))
        postponed = "yes" if "postponed" in blob.lower() else "no"
        sport = str(item.get("sport") or "")
        open_type = str(item.get("open_type") or "") or wop.order_types.open_now_type(letter)
        legs = [leg for leg in (item.get("legs") or []) if isinstance(leg, dict)]
        if not legs:
            legs = [item]
        for leg in legs:
            ticker = str(leg.get("ticker") or item.get("ticker") or "")
            venue = str(leg.get("venue_label") or leg.get("venue") or item.get("venue_label") or item.get("venue") or "")
            pay = str(leg.get("pay") or item.get("pay") or "")
            bet_for = str(leg.get("side_label") or item.get("bets") or wop.UNKNOWN_ASK)
            who_pays = ""
            if jsp is not None:
                try:
                    who_pays = jsp._who_pays_for_leg(leg)
                    bet_for = jsp.bet_text(leg)
                except Exception:
                    pass
            try:
                import kalshi_ticker_decode as ktd

                inst = ticker if ktd.is_sports_ticker(ticker) else ""
                if inst:
                    if not pay:
                        pay = ktd.pay_from_garbled_bet(bet_for)
                    decoded = ktd.decode_with_cached_title(inst, pay=pay, fetch=False)
                    if decoded.kind:
                        game = decoded.game or game
                        sport = sport or decoded.sport
                        bet_for = ktd.kitchen_clear(decoded, pay or "yes")
                        who_pays = who_pays or ktd.pays_if_label(decoded, pay or "yes")
                        ticker = inst
            except Exception:
                pass
            qty = leg.get("qty_text") or leg.get("qty") or item.get("qty_text") or item.get("qty") or ""
            cost = leg.get("cost") if leg.get("cost") is not None else item.get("cost")
            rows.append({
                "game": game,
                "sport": sport,
                "league": wop.league_from_instrument(ticker) if ticker else "",
                "system": letter,
                "open_type": open_type,
                "players": wop.players_game_label(game, sport),
                "bet_for": bet_for,
                "who_pays": who_pays,
                "bet_against": "Positions overlay",
                "venue": venue,
                "instrument": ticker,
                "confirmed": str(qty),
                "position": str(qty),
                "exposure": str(cost or 0),
                "postponed": postponed,
                "leftover": "",
                "source": "job_status Positions overlay",
                "tape": "",
                "held": leg.get("held") or item.get("held") or "",
                "mark": item.get("mark_text") or item.get("mark") or "",
                "pnl": item.get("pnl_text") if item.get("pnl_text") is not None else item.get("pnl"),
            })
    return rows


def a_status_note(systems: list[dict], latch_on: bool = False) -> str:
    row = next((item for item in systems if str(item.get("letter") or "") == "A"), {})
    on = str(row.get("on") or "").lower() == "on"
    if not on or latch_on:
        return (
            "A Lock gap is off. A one-leg lock fill turns A off only "
            "(systems.json lock.on=false) so we do not send a new Yes+No pair "
            "while leftover flatten still runs. Tennis crossover B, college football "
            "favorite C, T0 spreads D, and tennis T0 dog E stay on. Turn A back with "
            "python tools/prediction_job_control.py systems --lock on "
            "(or double-click run_prediction_orders_on.bat). That does not start a second B."
        )
    return (
        "A Lock gap is on right now. If a lock fills one leg and misses the other, "
        "A turns off (systems.json lock.on=false) until you turn it back; leftover "
        "flatten still runs. B–E stay on. Did not start a second B."
    )


def pid_cell(row: dict) -> str:
    pid = str(row.get("pid") or "").strip() or "down"
    extra = str(row.get("extra_pids") or "").strip()
    alive = row.get("alive")
    if pid in {"", "-", "—", "down"} or alive is False:
        return "down"
    if extra:
        return f"{pid} (extra {extra} — should be one)"
    return pid


def systems_table_rows(systems: list[dict]) -> list[list]:
    out = []
    for item in systems:
        letter = str(item.get("letter") or "")
        name = str(item.get("name") or system_label(letter))
        if letter == "D" and "NFL" not in name:
            name = "T0 spreads (on except NFL)"
        cap = ""
        if letter == "A":
            cap = "lock.net_max 0.99"
        out.append([
            letter,
            name,
            item.get("on") or "",
            item.get("stake") or "",
            item.get("max_open") or "",
            item.get("open") or "",
            pid_cell(item),
            cap or "—",
            (item.get("last") or "—")[:160],
        ])
    return out


TRADE_HEADERS = [
    ("When ET", "date"),
    ("System", "text"),
    ("Type", "text"),
    ("Match", "text"),
    ("League", "text"),
    ("Venue", "text"),
    ("Side", "text"),
    ("Wire", "num"),
    ("Fee", "text"),
    ("After-fee", "text"),
    ("HTTP", "text"),
    ("Filled", "text"),
    ("Outcome", "text"),
    ("Failure kind", "text"),
    ("P&L if settled", "text"),
]


def trade_table_rows(rows: list[dict]) -> list[list]:
    out = []
    for row in rows:
        out.append([
            row.get("when"),
            row.get("system_name") or row.get("system"),
            row.get("order_type") or "—",
            row.get("game"),
            row.get("league"),
            row.get("venue"),
            row.get("side"),
            row.get("wire"),
            row.get("fee"),
            row.get("after_fee"),
            row.get("http"),
            row.get("filled_label") or row.get("filled"),
            row.get("outcome"),
            row.get("failure") or "—",
            row.get("pnl") or "—",
        ])
    return out


def open_table_rows(open_rows: list[dict]) -> list[list]:
    out = []
    for row in open_rows or []:
        letter = str(row.get("system") or "")
        postponed = str(row.get("postponed") or "no")
        if postponed not in {"yes", "no"}:
            postponed = "yes" if str(postponed).lower() in {"yes", "true", "postponed"} else "no"
        out.append([
            system_label(letter) if letter in LETTERS else letter,
            row.get("open_type") or wop.order_types.open_now_type(letter),
            row.get("players") or wop.players_game_label(str(row.get("game") or ""), str(row.get("sport") or "")),
            row.get("sport") or "",
            row.get("league") or "",
            row.get("bet_for") or wop.UNKNOWN_ASK,
            row.get("who_pays") or "",
            row.get("venue"),
            row.get("confirmed") or row.get("position") or "",
            money4_dollar(row.get("exposure")),
            postponed,
            row.get("held") or "",
            row.get("source") or "job_status Positions overlay",
        ])
    if not out:
        out.append(["—", "—", "none open on the Positions overlay", "", "", "", "", "", "", "$0", "no", "", ""])
    return out


def _svg_escape(text: str) -> str:
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def svg_signed_bars(pairs: list[tuple[str, Decimal]], *, title: str, unit: str = "$") -> str:
    width, height = 720, 220
    pad_l, pad_r, pad_t, pad_b = 48, 16, 28, 44
    inner_w = width - pad_l - pad_r
    inner_h = height - pad_t - pad_b
    vals = [float(v or 0) for _label, v in pairs] or [0.0]
    lo = min(0.0, min(vals))
    hi = max(0.0, max(vals))
    span = hi - lo or 1.0
    zero_y = pad_t + (hi / span) * inner_h
    n = max(len(pairs), 1)
    gap = 12
    bar_w = max(18, (inner_w - gap * n) / n)
    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="220" role="img" aria-label="{_svg_escape(title)}">',
        f'<text x="{pad_l}" y="18" font-size="13" fill="#334155">{_svg_escape(title)}</text>',
        f'<line x1="{pad_l}" y1="{zero_y:.1f}" x2="{width - pad_r}" y2="{zero_y:.1f}" stroke="#94a3b8" stroke-width="1"/>',
    ]
    for i, (label, raw) in enumerate(pairs):
        val = float(raw or 0)
        x = pad_l + i * (bar_w + gap) + gap / 2
        h = abs(val) / span * inner_h
        y = zero_y - h if val >= 0 else zero_y
        color = SYS_COLOR.get(label[:1], "#334155")
        if val < 0:
            color = "#991b1b"
        elif val > 0:
            color = "#166534"
        letter = label.split()[0] if label else "?"
        color = SYS_COLOR.get(letter, color) if val == 0 else color
        if val == 0:
            color = SYS_COLOR.get(letter, "#94a3b8")
            h = 2
            y = zero_y - 1
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{max(h, 2):.1f}" fill="{color}" rx="3"/>'
        )
        txt = f"{unit}{val:.2f}" if unit == "$" else f"{val:.0f}"
        ty = y - 4 if val >= 0 else y + h + 12
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{ty:.1f}" text-anchor="middle" font-size="11" fill="#0f172a">{_svg_escape(txt)}</text>'
        )
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{height - 14}" text-anchor="middle" font-size="11" fill="#475569">{_svg_escape(label)}</text>'
        )
    parts.append("</svg>")
    return f'<div class="chart">{"".join(parts)}</div>'


def svg_grouped_bars(
    labels: list[str],
    series: list[tuple[str, list[float], str]],
    *,
    title: str,
) -> str:
    width, height = 720, 220
    pad_l, pad_r, pad_t, pad_b = 48, 16, 28, 48
    inner_w = width - pad_l - pad_r
    inner_h = height - pad_t - pad_b
    ymax = max([0.0] + [v for _n, vals, _c in series for v in vals] + [1.0])
    n = max(len(labels), 1)
    group_w = inner_w / n
    bar_w = max(10, (group_w - 16) / max(len(series), 1))
    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="220" role="img" aria-label="{_svg_escape(title)}">',
        f'<text x="{pad_l}" y="18" font-size="13" fill="#334155">{_svg_escape(title)}</text>',
    ]
    for i, label in enumerate(labels):
        gx = pad_l + i * group_w + 8
        for j, (_name, vals, color) in enumerate(series):
            val = float(vals[i]) if i < len(vals) else 0.0
            h = (val / ymax) * inner_h if ymax else 0
            x = gx + j * bar_w
            y = pad_t + inner_h - h
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w - 4:.1f}" height="{max(h, 1):.1f}" fill="{color}" rx="2"/>'
            )
            if val:
                parts.append(
                    f'<text x="{x + (bar_w - 4) / 2:.1f}" y="{y - 3:.1f}" text-anchor="middle" font-size="10" fill="#0f172a">{val:.0f}</text>'
                )
        parts.append(
            f'<text x="{gx + group_w / 2 - 8:.1f}" y="{height - 16}" text-anchor="middle" font-size="11" fill="#475569">{_svg_escape(label)}</text>'
        )
    lx = pad_l
    for name, _vals, color in series:
        parts.append(f'<rect x="{lx}" y="{height - 12}" width="10" height="10" fill="{color}"/>')
        parts.append(f'<text x="{lx + 14}" y="{height - 3}" font-size="11" fill="#475569">{_svg_escape(name)}</text>')
        lx += 90
    parts.append("</svg>")
    return f'<div class="chart">{"".join(parts)}</div>'


def svg_line(points: list[tuple[str, float]], *, title: str, color: str = "#4c1d95") -> str:
    width, height = 720, 220
    pad_l, pad_r, pad_t, pad_b = 52, 16, 28, 36
    inner_w = width - pad_l - pad_r
    inner_h = height - pad_t - pad_b
    ys = [p[1] for p in points] or [0.0]
    lo = min(0.0, min(ys))
    hi = max(0.0, max(ys))
    span = hi - lo or 1.0
    n = max(len(points) - 1, 1)

    def xy(i: int, yv: float) -> tuple[float, float]:
        x = pad_l + (i / n) * inner_w
        y = pad_t + (hi - yv) / span * inner_h
        return x, y

    zero_y = pad_t + (hi - 0.0) / span * inner_h
    coords = [xy(i, yv) for i, (_label, yv) in enumerate(points)]
    d = " ".join(
        ("M" if i == 0 else "L") + f" {x:.1f} {y:.1f}" for i, (x, y) in enumerate(coords)
    )
    last = points[-1][1] if points else 0.0
    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="220" role="img" aria-label="{_svg_escape(title)}">',
        f'<text x="{pad_l}" y="18" font-size="13" fill="#334155">{_svg_escape(title)}</text>',
        f'<line x1="{pad_l}" y1="{zero_y:.1f}" x2="{width - pad_r}" y2="{zero_y:.1f}" stroke="#cbd5e1" stroke-width="1"/>',
        f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2.5"/>',
    ]
    if coords:
        x, y = coords[-1]
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}"/>')
        parts.append(
            f'<text x="{x:.1f}" y="{y - 8:.1f}" text-anchor="end" font-size="12" fill="#0f172a">{last:+.2f}</text>'
        )
        parts.append(
            f'<text x="{pad_l}" y="{height - 8}" font-size="11" fill="#64748b">{_svg_escape(points[0][0])}</text>'
        )
        parts.append(
            f'<text x="{width - pad_r}" y="{height - 8}" text-anchor="end" font-size="11" fill="#64748b">{_svg_escape(points[-1][0])}</text>'
        )
    parts.append("</svg>")
    return f'<div class="chart">{"".join(parts)}</div>'


def kpi_card(label: str, value: str, *, tone: str = "") -> str:
    cls = f" kpi-{tone}" if tone else ""
    return (
        f'<div class="kpi{cls}"><div class="kpi-label">{esc(label)}</div>'
        f'<div class="kpi-value">{esc(value)}</div></div>'
    )


def kpi_strip(stats: dict) -> str:
    pnl = stats.get("pnl") or Decimal("0")
    tone = "up" if pnl > 0 else ("down" if pnl < 0 else "")
    roi = stats.get("roi")
    roi_tone = "up" if (roi is not None and roi > 0) else ("down" if (roi is not None and roi < 0) else "")
    return (
        '<div class="kpis">'
        + kpi_card("With-fee P&L", money_signed(pnl), tone=tone)
        + kpi_card("ROI", wop.fmt_roi(roi), tone=roi_tone)
        + kpi_card("N sent", str(stats.get("n_sent") or 0))
        + kpi_card("N filled (qty > 0)", str(stats.get("n_filled") or 0), tone="up")
        + kpi_card("N missed send", str(stats.get("n_missed") or 0), tone="down")
        + kpi_card("N open now", str(stats.get("n_open_today_fills") or 0))
        + kpi_card("N settled", str(stats.get("n_settled") or 0))
        + "</div>"
    )


def window_charts(stats: dict, equity: list[tuple[str, float]], *, title_prefix: str) -> str:
    pnl_pairs = [(letter, stats["pnl_by"].get(letter, Decimal("0"))) for letter in LETTERS]
    filled_vals = [float(stats["filled_by"].get(letter, 0)) for letter in LETTERS]
    missed_vals = [float(stats["missed_by"].get(letter, 0)) for letter in LETTERS]
    open_vals = [float(stats["open_by"].get(letter, 0)) for letter in LETTERS]
    settled_vals = [float(stats["settled_by"].get(letter, 0)) for letter in LETTERS]
    return (
        svg_signed_bars(pnl_pairs, title=f"{title_prefix} with-fee P&L by system")
        + svg_line(equity, title=f"{title_prefix} cumulative with-fee equity", color="#4c1d95")
        + svg_grouped_bars(
            list(LETTERS),
            [
                ("Filled", filled_vals, "#166534"),
                ("Missed send", missed_vals, "#991b1b"),
            ],
            title=f"{title_prefix} filled vs missed send",
        )
        + svg_grouped_bars(
            list(LETTERS),
            [
                ("Open", open_vals, "#a16207"),
                ("Settled", settled_vals, "#334155"),
            ],
            title=f"{title_prefix} open vs settled (filled tickets)",
        )
    )


def dashboard_script() -> str:
    extra = """
  function setDashWindow(which) {
    document.querySelectorAll("[data-window]").forEach(function (el) {
      el.hidden = el.getAttribute("data-window") !== which;
    });
    document.querySelectorAll("[data-window-btn]").forEach(function (btn) {
      var on = btn.getAttribute("data-window-btn") === which;
      btn.classList.toggle("on", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }
  document.querySelectorAll("[data-window-btn]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      setDashWindow(btn.getAttribute("data-window-btn"));
    });
  });
  setDashWindow("today");
"""
    script = report_page_extras.SORTABLE_TABLE_SCRIPT
    marker = "})();\n</script>"
    if marker in script:
        return script.replace(marker, extra + marker, 1)
    return script[:-9] + extra + "</script>"


def by_system_today_table(stats: dict) -> str:
    headers = [
        ("System", "text"),
        ("N sent", "num"),
        ("N filled", "num"),
        ("N missed send", "num"),
        ("N open", "num"),
        ("N settled", "num"),
        ("With-fee P&L", "num"),
        ("ROI %", "num"),
    ]
    rows = []
    empty = {
        "sent": 0,
        "filled": 0,
        "missed": 0,
        "open": 0,
        "settled": 0,
        "pnl": Decimal("0"),
        "invested": Decimal("0"),
        "roi": None,
    }
    for letter, _sid, name, _code in wop.SYSTEM_SPECS:
        slot = (stats.get("by") or {}).get(letter) or empty
        rows.append([
            f"{letter} {name}",
            slot["sent"],
            slot["filled"],
            slot["missed"],
            slot["open"],
            slot["settled"],
            money_signed(slot["pnl"]),
            wop.fmt_roi(slot.get("roi")),
        ])
    total = [
        "Combined",
        stats["n_sent"],
        stats["n_filled"],
        stats["n_missed"],
        stats["n_open_today_fills"],
        stats["n_settled"],
        money_signed(stats["pnl"]),
        wop.fmt_roi(stats.get("roi")),
    ]
    return wop.table(headers, rows, total)


def fill_types_on_rows(rows: list[dict]) -> None:
    """Stamp Paul's A–E Type on cached dashboard rows. Display only. No P&L."""
    import order_types
    from order_ledger import ORDERS, _load_jsonl

    need = [row for row in rows or [] if isinstance(row, dict) and not row.get("order_type")]
    if not need:
        return
    sends = [row for row in _load_jsonl(ORDERS) if isinstance(row, dict) and row.get("event") == "sent"]
    by_oid: dict[str, dict] = {}
    by_game: dict[str, list] = defaultdict(list)
    for sent in sends:
        oid = str(sent.get("order_id") or "").strip()
        key = str(sent.get("bet_key") or "")
        parts = key.split("\t")
        game = str(sent.get("game") or "") or (parts[2] if len(parts) > 2 else "")
        if oid:
            by_oid[oid] = sent
        if game:
            by_game[game].append(sent)
    for row in need:
        sent = by_oid.get(str(row.get("order_id") or "").strip())
        if not sent:
            continue
        key = str(sent.get("bet_key") or "")
        parts = key.split("\t")
        game = str(sent.get("game") or row.get("game") or "") or (parts[2] if len(parts) > 2 else "")
        letter = str(row.get("system") or "")
        step = str(sent.get("step") or "")
        sent_key = str(sent.get("bet_key") or "")
        if step in {"watch", "recovery"} and (
            letter in {"C", "D", "E", "F", "G"}
            or sent_key.startswith(("tennis-t0-dog", "tennis-t0-spread", "soccer-t0-total", "cfb-favorite", "spread-t0"))
        ):
            row["order_type"] = order_types.TYPE_LEFTOVER
            continue
        row["order_type"] = order_types.from_sent(sent, by_game.get(game) or [sent], "", letter=letter)


def day_nav_html(payload: dict) -> str:
    prev = str(payload.get("prev_href") or "").strip()
    nxt = str(payload.get("next_href") or "").strip()
    day = str(payload.get("day") or "")
    prev_el = (
        f'<a class="day-nav-btn" href="{esc(prev)}">Previous</a>'
        if prev
        else '<span class="day-nav-btn off">Previous</span>'
    )
    next_el = (
        f'<a class="day-nav-btn" href="{esc(nxt)}">Next</a>'
        if nxt
        else '<span class="day-nav-btn off">Next</span>'
    )
    return (
        f'<nav class="day-nav" aria-label="Dashboard day">{prev_el}'
        f'<span class="day-nav-label">{esc(day)} ET</span>{next_el}</nav>'
    )


def write_html(payload: dict) -> str:
    systems = payload.get("systems") or []
    open_rows = payload.get("open_rows") or []
    today_rows = payload.get("today_rows") or []
    all_rows = payload.get("all_rows") or []
    fill_types_on_rows(today_rows)
    fill_types_on_rows(all_rows)
    today = payload.get("today") or {}
    inception = payload.get("inception") or {}
    generated = payload.get("generated_at") or now_et().strftime("%Y-%m-%d %H:%M:%S ET")
    trades_at = payload.get("trades_at") or generated
    live_at = payload.get("live_at") or generated
    latch_on = bool(payload.get("latch_on"))
    day = payload.get("day") or midnight_et().strftime("%Y-%m-%d")
    net_max = payload.get("net_max") or "0.99"
    overlay_n = len({wop.game_norm(str(r.get("game") or r.get("instrument") or "")) for r in open_rows if r.get("game") or r.get("instrument")})
    overlay_n = overlay_n or len(open_rows)
    open_dollars = sum((ddec(r.get("exposure")) or Decimal("0") for r in open_rows), Decimal("0"))
    a_note = a_status_note(systems, latch_on=latch_on)
    sys_on = ", ".join(
        f"{item.get('letter')} {item.get('on')}"
        for item in systems
    ) or "unknown"
    css = """
body { font-family: Segoe UI, system-ui, sans-serif; margin: 16px; color: #0f172a; background: #fff; }
h1, h2 { color: #1e293b; }
.def { background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 16px; margin: 12px 0; }
.note { color: #475569; font-size: 14px; }
.updated { font-size: 1.1rem; margin: 0.25rem 0 1rem; }
code { font-size: 13px; }
.kpis { display: flex; flex-wrap: wrap; gap: 10px; margin: 12px 0; }
.kpi { background: #f8fafc; border: 1px solid #d8dee9; padding: 10px 14px; min-width: 7.5rem; flex: 1 1 7rem; }
.kpi-label { font-size: 12px; color: #64748b; }
.kpi-value { font-size: 1.35rem; font-weight: 650; }
.kpi-up { border-color: #86efac; background: #f0fdf4; }
.kpi-down { border-color: #fecaca; background: #fef2f2; }
.toggles { display: flex; gap: 8px; margin: 8px 0 12px; flex-wrap: wrap; }
.toggles button { font: inherit; padding: 6px 12px; border: 1px solid #cbd5e1; background: #fff; border-radius: 6px; cursor: pointer; }
.toggles button.on { background: #4c1d95; color: #fff; border-color: #4c1d95; }
.chart { width: 100%; max-width: 100%; margin: 8px 0 16px; background: #fff; }
.sys-on { color: #166534; font-weight: 650; }
.sys-off { color: #991b1b; font-weight: 650; }
.links a { margin-right: 12px; }
.day-nav { display: flex; gap: 10px; align-items: center; justify-content: space-between; margin: 8px 0 16px; }
.day-nav-btn {
  display: inline-flex; align-items: center; justify-content: center;
  min-height: 44px; min-width: 44px; padding: 10px 16px;
  border: 1px solid #cbd5e1; border-radius: 8px;
  text-decoration: none; color: #4c1d95; font-weight: 650; background: #fff;
}
.day-nav-btn.off { color: #94a3b8; pointer-events: none; }
.day-nav-label { font-weight: 650; text-align: center; flex: 1 1 auto; }
"""
    on_bits = []
    for item in systems:
        cls = "sys-on" if str(item.get("on") or "") == "on" else "sys-off"
        pid = pid_cell(item)
        on_bits.append(
            f'<span class="{cls}">{esc(item.get("letter"))} {esc(item.get("on"))}</span>'
            f' pid {esc(pid)}'
        )
    sys_line = " · ".join(on_bits) if on_bits else "systems unknown"
    today_charts = window_charts(today, payload.get("equity_today") or [], title_prefix="Today")
    inc_charts = window_charts(inception, payload.get("equity_inception") or [], title_prefix="Inception")
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prediction-market dashboard — scoreboard</title>
<style>
{css}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Prediction-market dashboard</h1>
{day_nav_html(payload)}
<p class="updated"><strong>Updated {esc(generated)}</strong> (Eastern Time). Stamp 17 Oct 2026. Trades rebuilt {esc(trades_at)}. Systems / open from {esc(live_at)}.</p>
<p class="note links">
<a href="job_status.html">job_status.html</a>
<a href="orders.html">orders.html</a>
<a href="orders_performance.html">orders_performance.html</a>
</p>
<p class="note">Kitchen scoreboard for the live bots. Does not place or sell tickets. Click column headers to sort. {report_page_extras.SWIPE_NOTE_HTML.replace('<p class="swipe-note">', '').replace('</p>', '')}</p>

<h2>Systems working or not</h2>
<p class="note">{sys_line}. Stake, max open, and lock.net_max come from systems.json. One python pid each (or down). {esc(a_note)} <strong>D on except NFL</strong> — live T0 spreads skips pro football while gathering data; college football stays on if D is on. Send cap lock.net_max {esc(net_max)}.</p>
{wop.table(
    [
        ("Sys", "text"),
        ("Name", "text"),
        ("On/off", "text"),
        ("Stake $", "num"),
        ("Max open", "num"),
        ("Open now", "num"),
        ("PID", "text"),
        ("lock.net_max", "text"),
        ("Last action", "text"),
    ],
    systems_table_rows(systems),
)}

<h2>Today</h2>
<p class="note">Eastern Time calendar day {esc(day)}. Toggle today (since midnight ET) versus inception (first confirmed fill). Counts: sent = posted IOC; filled = venue confirm qty &gt; 0 (a house fill is still 1 contract; a Polymarket 0.3 leftover is a real ticket); missed send = HTTP OK confirm 0; open = still on the Positions overlay; settled = venue-paid / final / void / flatten. Primary P&amp;L is with fees.</p>
<div class="toggles" role="group" aria-label="Today or inception">
<button type="button" class="on" data-window-btn="today" aria-pressed="true">Today (since midnight ET)</button>
<button type="button" data-window-btn="inception" aria-pressed="false">Inception</button>
</div>
<div data-window="today">
{kpi_strip(today)}
{by_system_today_table(today)}
{today_charts}
</div>
<div data-window="inception" hidden>
{kpi_strip(inception)}
{by_system_today_table(inception)}
{inc_charts}
</div>

<h2>Open now</h2>
<p class="note">Same unique-game overlay as job_status Positions / venue truth. Kalshi qty ≥ 1, Polymarket qty &gt; 0, plus a confirmed fill kept when the Polymarket positions GET is empty and the market is still OPEN. Settled / expired / final / void never count as open. Postponed is labeled postponed. Type is A lock gap / B T0 / B crossover / E dog (same family as the orders Type column). Bet for is the seat we hold; Who $1 pays is which result cashes that seat. Dollar at risk is after-fee cost still held. Overlay games: {esc(overlay_n)}. Dollars at risk: {esc(money4_dollar(open_dollars))}.</p>
{wop.table(
    [
        ("System", "text"),
        ("Type", "text"),
        ("Players / game", "text"),
        ("Sport", "text"),
        ("League", "text"),
        ("Bet for", "text"),
        ("Who $1 pays", "text"),
        ("Venue", "text"),
        ("Qty", "text"),
        ("$ at risk", "num"),
        ("Postponed", "text"),
        ("Held since ET", "date"),
        ("Source", "text"),
    ],
    open_table_rows(open_rows),
)}

<h2>Trades today</h2>
<p class="note">Each filled or missed send on {esc(day)} ET. Successful = venue-confirmed fill qty &gt; 0. Missed send = HTTP OK confirm 0 (ghost 201) — never a won/lost ticket. Lost bet = settled with-fee P&amp;L &lt; 0. Click headers to sort.</p>
{wop.table(TRADE_HEADERS, trade_table_rows(today_rows))}

<h2>Full book (every posted send)</h2>
<p class="note">Same columns for the whole tape. Not a second P&amp;L formula. After-fee is wire plus documented taker fee; missing fee says fee unknown, not 0.</p>
{wop.table(TRADE_HEADERS, trade_table_rows(all_rows))}

<h2>Local venue cash slip</h2>
<p class="note">House cash on this PC (venue_cash_local.json). Confirm from the venue about once an hour. Amounts only — no secrets.</p>
{wop.table([("Venue", "text"), ("Local cash", "num")], payload.get("cash") or cash_rows())}

<div class="def">
<h2>How to read success and failure</h2>
<ul>
<li><strong>Successful buy:</strong> venue-confirmed fill quantity at least 1.</li>
<li><strong>Missed send:</strong> we posted, HTTP said OK, confirm quantity 0. Ghost HTTP 201 without a fill is a miss.</li>
<li><strong>Lost bet:</strong> the ticket filled, the game settled, and with-fee P&amp;L is below zero.</li>
<li>A miss is not a lost bet. A lost bet is not a miss.</li>
<li>One venue fill is one row with one P&amp;L. A ticket is a win or a loss, not both.</li>
</ul>
<p><strong>Leftover-watch:</strong> after a lock send, if one side fills and the other misses, A watches and buys the missing side or flattens so we are not naked. That is lock-bot cleanup, not System E. A comment already said not to leftover-watch a directional dog; the skip list never included E, so tennis T0 dog fills were registered by accident. Those hedge posts are Type leftover / hedge (A leftover) — not E Tennis T0 dog — so 55¢ Djokovic and 51¢ No Musetti are not underdog tickets.</p>
<p>On/off snapshot: {esc(sys_on)}. Did not sell, start a second B, bump stake, wire D NFL, leftover GTC, or retune C=1.05.</p>
</div>
<p class="note">Data: orders.jsonl, order_io.jsonl, systems.json, job_status Positions overlay, fill-history truth, venue_cash_local.json. Rebuilds with orders_performance.html after a confirmed fill or a closed trade (background; does not sit on A hard-then-easy IOC). Job status refreshes systems / open about once a minute. Manual: <code>python tools/write_orders_performance.py</code> then this page. {esc(FILE_URL)}</p>
{dashboard_script()}
</body>
</html>
"""
    return report_page_extras.inject_report_page_extras(page)


def _jsonable(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def build_payload(
    clusters: list[dict],
    open_rows: list[dict],
    *,
    systems: list[dict] | None = None,
    snap: dict | None = None,
    summary: dict | None = None,
    trades_at: str | None = None,
    day: datetime | None = None,
    prev_href: str = "",
    next_href: str = "",
) -> dict:
    now = now_et()
    focus = midnight_et(day or now)
    end = focus + timedelta(days=1) if day is not None else None
    start = focus
    all_rows = flatten_trades(clusters)
    if end is not None:
        clipped = []
        for row in all_rows:
            stamp = parse_when(row.get("when_raw") or row.get("when"))
            if stamp is not None and stamp < end:
                clipped.append(row)
        all_rows = clipped
    today_rows = [row for row in all_rows if in_today(row.get("when_raw") or row.get("when"), today=focus)]
    today = stats_for(all_rows, clusters, open_rows, start=start, end=end or (start + timedelta(days=1)))
    inception = stats_for(all_rows, clusters, open_rows, start=None, end=end)
    live = systems if systems is not None else live_systems(snap)
    latch_on = bool((snap or {}).get("latch_on"))
    net_max = "0.99"
    for item in live:
        name = str(item.get("name") or "")
        if "cap " in name:
            net_max = name.split("cap ", 1)[-1].rstrip(")")
            break
    if net_max == "0.99":
        try:
            import live_lock_orders

            net_max = str(live_lock_orders.send_line())
        except Exception:
            pass
    generated = now.strftime("%Y-%m-%d %H:%M:%S ET")
    return {
        "generated_at": generated,
        "trades_at": trades_at or generated,
        "live_at": generated,
        "day": start.strftime("%Y-%m-%d"),
        "prev_href": prev_href,
        "next_href": next_href,
        "systems": live,
        "open_rows": open_rows,
        "today_rows": today_rows,
        "all_rows": all_rows,
        "today": today,
        "inception": inception,
        "equity_today": equity_points(clusters, start=start, end=end or (start + timedelta(days=1))),
        "equity_inception": equity_points(clusters, start=None, end=end),
        "cash": cash_rows(),
        "latch_on": latch_on,
        "net_max": net_max,
        "summary": summary or {},
    }


def save_cache(payload: dict) -> None:
    try:
        RAW.mkdir(parents=True, exist_ok=True)
        slim = {
            "trades_at": payload.get("trades_at"),
            "today_rows": payload.get("today_rows"),
            "all_rows": payload.get("all_rows"),
            "today": _jsonable(payload.get("today")),
            "inception": _jsonable(payload.get("inception")),
            "equity_today": payload.get("equity_today"),
            "equity_inception": payload.get("equity_inception"),
            "day": payload.get("day"),
            "prev_href": payload.get("prev_href"),
            "next_href": payload.get("next_href"),
            "net_max": payload.get("net_max"),
            "open_rows": payload.get("open_rows"),
            "systems": payload.get("systems"),
        }
        CACHE.write_text(json.dumps(slim, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass


def load_cache() -> dict | None:
    try:
        data = json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _empty_system_slot() -> dict:
    return {
        "sent": 0,
        "filled": 0,
        "missed": 0,
        "open": 0,
        "settled": 0,
        "pnl": Decimal("0"),
        "invested": Decimal("0"),
        "roi": None,
    }


def _revive_stats(raw: dict | None) -> dict:
    data = dict(raw or {})
    for key in ("pnl", "open_dollars", "invested"):
        if key in data:
            data[key] = ddec(data.get(key)) or Decimal("0")
    if "invested" not in data:
        data["invested"] = Decimal("0")
    by = {}
    for letter, slot in (data.get("by") or {}).items():
        item = dict(slot)
        item["pnl"] = ddec(item.get("pnl")) or Decimal("0")
        item["invested"] = ddec(item.get("invested")) or Decimal("0")
        if item.get("roi") in (None, ""):
            item["roi"] = wop.roi_pct(item["pnl"], item["invested"])
        else:
            item["roi"] = ddec(item.get("roi"))
        by[letter] = item
    data["by"] = by or {letter: _empty_system_slot() for letter in LETTERS}
    pnl_by = {}
    for letter, amount in (data.get("pnl_by") or {}).items():
        pnl_by[letter] = ddec(amount) or Decimal("0")
    data["pnl_by"] = pnl_by or {letter: Decimal("0") for letter in LETTERS}
    invested_by = {}
    for letter, amount in (data.get("invested_by") or {}).items():
        invested_by[letter] = ddec(amount) or Decimal("0")
    data["invested_by"] = invested_by or {letter: Decimal("0") for letter in LETTERS}
    if data.get("roi") in (None, ""):
        data["roi"] = wop.roi_pct(data.get("pnl"), data.get("invested"))
    else:
        data["roi"] = ddec(data.get("roi"))
    for key in ("filled_by", "missed_by", "open_by", "settled_by"):
        data[key] = {str(k): int(v or 0) for k, v in (data.get(key) or {}).items()}
    return data


def write_payload(payload: dict, path: Path | None = None) -> Path:
    STAMP.mkdir(parents=True, exist_ok=True)
    target = path or PAGE
    html = write_html(payload)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(html, encoding="utf-8")
    tmp.replace(target)
    if target.resolve() == PAGE.resolve():
        save_cache(payload)
    return target


def dated_dashboard_name(day: datetime) -> str:
    return f"dashboard_{midnight_et(day).strftime('%Y%m%d')}.html"


def write_daily_dashboards(
    clusters: list[dict],
    open_rows: list[dict],
    *,
    summary: dict | None = None,
    snap: dict | None = None,
    days: int = 7,
) -> list[Path]:
    """One venue-true kitchen file per ET calendar day, plus prev/next."""
    today = midnight_et()
    stamps = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    paths = []
    for i, day in enumerate(stamps):
        prev_href = dated_dashboard_name(stamps[i - 1]) if i else ""
        next_href = dated_dashboard_name(stamps[i + 1]) if i + 1 < len(stamps) else "dashboard.html"
        payload = build_payload(
            clusters,
            open_rows if day == today else [],
            snap=snap,
            summary=summary,
            day=day,
            prev_href=prev_href,
            next_href=next_href,
        )
        path = STAMP / dated_dashboard_name(day)
        write_payload(payload, path)
        print(f"wrote {path}", flush=True)
        paths.append(path)
    return paths


def write_from_performance(
    clusters: list[dict],
    open_rows: list[dict],
    *,
    summary: dict | None = None,
    snap: dict | None = None,
) -> Path:
    """Full rewrite from scored clusters. Called after orders_performance.html."""
    yesterday = midnight_et() - timedelta(days=1)
    payload = build_payload(
        clusters,
        open_rows,
        snap=snap,
        summary=summary,
        prev_href=dated_dashboard_name(yesterday),
        next_href="",
    )
    path = write_payload(payload, PAGE)
    print(f"wrote {path}", flush=True)
    write_daily_dashboards(clusters, open_rows, summary=summary, snap=snap)
    return path


def refresh_from_job_status(snap: dict | None) -> Path | None:
    """Cheap live header: systems + open overlay. Does not rescore the tape. Does not ntfy."""
    cache = load_cache()
    if not cache:
        return None
    systems = live_systems(snap)
    open_rows = open_from_positions((snap or {}).get("positions") if isinstance(snap, dict) else None)
    if open_rows is None:
        open_rows = cache.get("open_rows") or []
    now = now_et().strftime("%Y-%m-%d %H:%M:%S ET")
    payload = {
        "generated_at": now,
        "trades_at": cache.get("trades_at") or now,
        "live_at": now,
        "day": cache.get("day") or midnight_et().strftime("%Y-%m-%d"),
        "prev_href": cache.get("prev_href") or dated_dashboard_name(midnight_et() - timedelta(days=1)),
        "next_href": cache.get("next_href") or "",
        "systems": systems or cache.get("systems") or [],
        "open_rows": open_rows,
        "today_rows": cache.get("today_rows") or [],
        "all_rows": cache.get("all_rows") or [],
        "today": apply_overlay_open(_revive_stats(cache.get("today")), open_rows),
        "inception": apply_overlay_open(_revive_stats(cache.get("inception")), open_rows),
        "equity_today": [tuple(p) for p in (cache.get("equity_today") or [])],
        "equity_inception": [tuple(p) for p in (cache.get("equity_inception") or [])],
        "cash": cash_rows(),
        "latch_on": bool((snap or {}).get("latch_on")),
        "net_max": cache.get("net_max") or "0.99",
        "summary": {},
    }
    return write_payload(payload)


def main() -> int:
    """Standalone: prefer a live performance rebuild so the tape is not stale."""
    print("dashboard via orders_performance rebuild", flush=True)
    return wop.main()


if __name__ == "__main__":
    raise SystemExit(main())
