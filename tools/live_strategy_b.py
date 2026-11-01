"""Live Strategy B on tennis, D = 0.25 lock profit.

Research only. Not gold. Not DailyRun. One contract. Tennis moneyline Yes only.

At T0 buy both Yes, both-or-nothing: shop every platform that lists the
match (Kalshi, Gemini, Polymarket, Novig) and buy each side on the cheapest
book. Cross-platform pairs are allowed. All-in C ≤ 1.05 HOLD is the sum of
the two chosen after-fee asks. Pick from live poller / price_memory quotes;
REST-confirm only those 1–2 books unpaced; then IOC/FOK. Same cheapest-leg
rule for the 50-cross (T0-dog Yes) and the GTC dip (original-favorite Yes
at fav_target). Recheck both chosen books before either HTTP.
If only one fills, flatten that Yes (buy No on the same venue/instrument).
Do not hold a directional 0.18 dog. If flatten also misses, leftover-watch
ONLY the missed player's Yes. Never opponent No (Goffin). Independent of the
lock-bot latch. Quote checks for leftover / 50c cross / fav dip are
continuous (memory tick wakes the sender; REST confirm is inline, not the
next 3-minute T0-slate walk). Each extra is one IOC, 1 contract, the
first time the rechecked ask is in cap / Taverna>0.50 / Bueno<=1-C-0.25. A
fill stops that stage. A miss or partial marks that extra done — never
another IOC 3s later for the same ticket. Partial fill counts as filled qty.
If the T0 underdog Yes later prints strictly above 0.50 before a 5c/95c
absorb, REST both Yes asks and buy one more of that dog only when both
are true: the T0 favorite's current Yes ask is strictly below the dog Yes
we would pay (opponent has gone under that number), AND all-in C (dog Yes
ask + favorite Yes ask + documented taker fees, same fee model as T0) is
at most 1.05. If favorite Yes >= dog Yes, skip, log cross_fav_not_below_dog,
and do not buy the extra. If all-in C > 1.05 or the fee is unknown, skip,
log cross_allin_c_over_105, no extra, no dip from this illegal cross. Then
buy one more of the original favorite at or below 1 − cross_fill − 0.25,
after a fee recheck that keeps that extra pair a 25-cent lock, only after
a legal cross fill. After that 50-cross fill, REST-recheck the favorite
Yes immediately and rest one 1-contract GTC buy at fav_target (not
cross−25¢) when the ask is still above the target. If the ask is already
at or below the target, take it now with today's IOC/FOK. Do not
double-send. Cancel the GTC on absorb / settle / game over. Poly dip GTC
uses TIME_IN_FORCE_GOOD_TILL_CANCEL, not FOK.

Own state: raw/strategy_b_watch.json. Does not read or write orders_stopped.json.
Does not call resume_orders_after_lock. May send Novig when novig_live.orders_live()
(same 1-contract IOC as Kalshi/Gemini/Polymarket, then GET /v3/portfolio/fills
confirm). Does not shut down the Yes+No lock bot. Rechecks the book immediately
before every send.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_lock_orders  # noqa: E402
import novig_live  # noqa: E402
import polymarket_us_live  # noqa: E402
import price_memory  # noqa: E402
import venue_pace  # noqa: E402
from dense_inplay_yes_dip_20261021 import (  # noqa: E402
    ABSORB as ABSORB_F,
    assign_actual_t0,
    clock_hides_match,
    first_competitive_two_sided,
)
import live_t0_yes  # noqa: E402
from odds_cross_winrate_20261020 import as_float, game_norm, parse_dt  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, PYCACHE_DIR, RAW_DIR as RAW, ROOT as REPO  # noqa: E402
from tennis_decade_at_start_20261020 import is_clocked_start  # noqa: E402

ET = ZoneInfo("America/New_York")
STATE = RAW / "strategy_b_watch.json"
STATE_LOCK = RAW / "strategy_b.lock"
PID_FILE = RAW / "strategy_b.pid"
LOG = RAW / "strategy_b.log"
STOP = RAW / "strategy_b.stop"

STRATEGY_B_ENABLED = True
MAX_OPEN_B_MATCHES = 4
D = Decimal("0.25")
CROSS = Decimal("0.50")
# C_LO=0.95 was a dense-sim universe freeze (tennis_dual_yes_dip_no / 182-book
# D=25), not a lock. It skipped automatic-win T0s (two Yes pay $1). Overnight
# 24 Oct used wire C_HI=1.01 (two Yes asks). Live send now uses all-in C
# (two Yes asks + documented taker fees) <= C_HI 1.05. Do not gate on wire
# 1.01. Stacking uses all-in with fees < $1 after a legal T0. Do not use 1.20.
C_LO = Decimal("0.95")
C_HI = Decimal("1.05")
T0_C_OVER_SKIP = "t0_allin_c_over_105"
CROSS_FAV_NOT_BELOW = "cross_fav_not_below_dog"
CROSS_ALLIN_OVER = "cross_allin_c_over_105"
CROSS_BEFORE_START = "cross_hours_before_trusted_t0"
POLY_T0_THETA = Decimal("0.0695")
_tape_seen: set[str] = set()
T0_STACK_CAP = 10
YES_LO = Decimal("0.10")
YES_HI = Decimal("0.90")
ABSORB = Decimal(str(ABSORB_F))
SIZE = Decimal("1")
ONE = Decimal("1")
TICK_SEC = 1
CROSS_IDLE_SEC = 0.05
T0_ARM_BUDGET_SEC = 1.0
T0_ARM_BUDGET_WHEN_CROSS_SEC = 0.2
T0_LEAD_SEC = int(getattr(live_t0_yes, "T0_LEAD_SEC", 15))
# 30 minutes. Live tennis Yes-ask tape 21–31 Oct 2026: p90 minutes from listed
# T0 until cheapest both-Yes after-fee first drops to <= C_HI 1.05 is ~27 min;
# 28% of hits are after the old 5-minute watch. HOLD C_HI=1.05 and D=0.25.
# E/F/G still use live_t0_yes.T0_GRACE_SEC=300. Poller spawn stays 5 min before.
T0_GRACE_SEC = 1800


def t0_grace_minutes() -> int:
    return max(1, int(T0_GRACE_SEC) // 60)
WATCH_CADENCE = "continuous / memory tick + immediate REST confirm"
EVENT_CACHE_SEC = 20
QUEUE_KEEP = 40
SKIP_KEEP = 30
VENUE_ORDER = ("kalshi", "gemini", "polymarket", "novig")
OPEN_STAGES = {
    "waiting_t0",
    "t0_filled_waiting_50_cross",
    "waiting_cross",
    "waiting_fav_dip",
    "fav_gtc_resting",
    "one_leg_miss",
}
CROSS_STAGES = {"waiting_cross", "t0_filled_waiting_50_cross"}
DIP_STAGES = {"waiting_fav_dip", "fav_gtc_resting"}
VENUE_GTC_TIF = {
    "kalshi": ("time_in_force", "good_till_canceled"),
    "gemini": ("timeInForce", "good-til-cancel"),
    "polymarket": ("tif", "TIME_IN_FORCE_GOOD_TILL_CANCEL"),
    "novig": ("tif", "GTC"),
}
POSTPONED_STAGE = "postponed"
DONE_STAGES = {"done", "absorbed", "abandoned", POSTPONED_STAGE}
# Tokens from live/saved venue payloads or this repo's venue clients.
# Polymarket event.period: SUS (Taverna rain-suspend), POST (live tennis catalog).
# Novig event.status: DELAYED / SUSPENDED (novig_live.QUIET_STATUSES); live ATP/WTA
# tonight was OPEN_PREGAME / OPEN_INGAME / CANCELED / FINAL — CANCELED is not postponed.
# Kalshi market.status=active with empty result is still live, not postponed.
POSTPONED_TOKENS = {
    "sus",
    "post",
    "delayed",
    "postponed",
    "suspended",
}
_STATUS_KEYS = ("status", "state", "marketStatus", "event_status", "ep3Status", "period")
_START_KEYS = (
    "startTime",
    "startDate",
    "gameStartTime",
    "occurrence_datetime",
    "target_datetime",
)
TAPE_RESUME_SOURCES = {
    "tape resume after last >=60min gap",
    "first competitive two-sided Yes",
    "first competitive two-sided Yes (clock hid the match)",
}

_scan = None
_event_cache: dict[str, tuple[float, dict]] = {}
_tick_offset = 0
_tick_path: Path | None = None
_series: dict[tuple, list] = {}
_starts: dict[str, str] = {}


def now_et() -> datetime:
    return datetime.now(ET)


def iso_now() -> str:
    return now_et().isoformat(timespec="milliseconds")


def job_deadline_iso() -> str | None:
    return None


def past_job_deadline(moment: datetime | None = None) -> bool:
    return False


def keep_running() -> bool:
    return not STOP.exists()


def log(msg: str) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    line = f"{iso_now()} {msg}\n"
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(line)


def _dec(value) -> Decimal | None:
    return live_lock_orders._dec(value)


def _money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value.normalize(), "f")


def same_game(left: str, right: str) -> bool:
    a = game_norm(left)
    b = game_norm(right)
    return bool(a and a == b)


def _json_dump(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def empty_status() -> dict:
    return {
        "enabled": bool(STRATEGY_B_ENABLED),
        "d": _money(D),
        "d_meaning": "lock profit 0.25 on the extra post-cross pair, not a 25c dip",
        "max_open_b_matches": int(MAX_OPEN_B_MATCHES),
        "currently_open": 0,
        "pid": None,
        "updated_at": "",
        "cluster_15m": 0,
        "cluster_60m": 0,
        "cluster_note": "",
        "t0_rule": (
            f"Live T0 both-Yes only inside a {t0_grace_minutes()}-minute window of a trusted actual start "
            "(later of Kalshi/Gemini occurrence and a scheduled listed/feed time with "
            "seconds=00; ~15s before through T0_GRACE). A too-early occurrence cannot "
            "beat a still-future listed first-serve. Odd-second Polymarket gameStartTime "
            "stamps are feed updates, not court time. Reject stale listed that hides "
            "in-play (Miyoshi absorb). Do not send if already in-play (occurrence/listed "
            f"more than ~{t0_grace_minutes()} minutes ago, or either Yes absorbing at 5c/95c). Mid-slate start "
            "skips games whose T0 already passed (skip_reason). Never a clockless "
            "first-competitive T0 for live sends. 50-cross only after that trusted T0; "
            "never send a B crossover hours before first serve. Shop cheapest Yes per player across "
            "Kalshi/Gemini/Polymarket/Novig (omit a shop with no ticker); C≤1.05 HOLD on the two chosen after-fee asks. "
            "T0 all-in C must be at most 1.05 (two Yes asks + documented taker fees). "
            "No 0.95 floor — C=0.90 wire still sends if all-in <= 1.05. No wire C_HI=1.01 "
            "gate. All-in C>1.05 is t0_allin_c_over_105: skip, no T0, no 50-cross, no dip, "
            "next game. After both legs confirm qty>=1, if all-in with fees is still under "
            "$1, send another 1-contract T0 pair on the same match until ask size <1, named "
            "balance deny, REST all-in >= $1, or 10 pairs. MAX_OPEN_B_MATCHES is matches, "
            "not contracts."
        ),
        "t0_c_rule": (
            "Send if both Yes in (0.10, 0.90) and all-in C (asks + documented taker fees) "
            "<= 1.05. All-in C>1.05 skip t0_allin_c_over_105 (no T0 / 50-cross / dip). "
            "Fee unknown is only a missing documented taker schedule on a chosen leg "
            "(Novig without coefficient/charge rule) — not venue=multi, and not C>1.05 "
            "without the number. Novig uses c × p × (1−p); WHEN_LIVE is $0 unless "
            "OPEN_INGAME. Unpriced Novig is not the cheapest leg; another shop can still send. "
            "Do not gate on wire C_HI=1.01. Stack another 1-contract T0 pair while all-in "
            "with fees < $1, cap 10 pairs/match. Match slots are not extra contracts."
        ),
        "cross_rule": (
            "50-cross extra: the first trusted memory print of T0-dog Yes > 0.50 wakes "
            "an immediate REST recheck of both Yes asks (inline, not the next T0-slate "
            "walk). Send the T0-dog extra only if the T0 favorite's current Yes ask is "
            "strictly below the dog Yes we would pay AND all-in C (dog Yes + favorite Yes "
            "+ documented taker fees) <= 1.05 (same fee model as T0). If favorite Yes >= "
            "dog Yes (both 81, or favorite still 80 while dog 50-spike 81), skip, log "
            "cross_fav_not_below_dog, do not buy. If all-in C > 1.05 or fee unknown, skip, "
            "log cross_allin_c_over_105, no extra, no dip from this illegal cross. T0 "
            "both-Yes all-in C<=1.05 is unchanged. D=0.25 dip only after a legal cross "
            "fill: immediately rest one GTC favorite Yes at fav_target = 1 − cross_fill "
            "− 0.25 (qty 1) unless the REST ask is already ≤ target, in which case "
            "IOC/FOK as today. extra_pair_net_ok still (after fees ≤ $1−D). Poly dip "
            "GTC is TIME_IN_FORCE_GOOD_TILL_CANCEL, not FOK. One contract. Skip-if "
            "already filled this cross."
        ),
        "last_skip_reason": "",
        "late_t0_skip_reason": "",
        "novig_orders": (
            "may send when Novig orders are live (switch + trading key); "
            "same B rules as Kalshi/Gemini/Polymarket, then GET /v3/portfolio/fills confirm"
        ),
        "watch_cadence": WATCH_CADENCE,
        "lock_bot_latch": "independent; this file is not orders_stopped.json",
        "matches": [],
        "queued": [],
        "skipped": [],
        "research_only": True,
        "gold": False,
        "dailrun": False,
    }


def load_status(path: Path | None = None) -> dict:
    target = path or STATE
    if not target.exists():
        return empty_status()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_status()
    if not isinstance(data, dict):
        return empty_status()
    base = empty_status()
    base.update(data)
    if not isinstance(base.get("matches"), list):
        base["matches"] = []
    if not isinstance(base.get("queued"), list):
        base["queued"] = []
    if not isinstance(base.get("skipped"), list):
        base["skipped"] = []
    return base


def live_b_caps() -> tuple[bool, int]:
    """On/off and max open from systems.json when present. Else module constants."""
    try:
        import prediction_systems

        cfg = prediction_systems.get_system("tennis_crossover")
        return bool(cfg.on), max(1, int(cfg.max_open))
    except Exception:
        return bool(STRATEGY_B_ENABLED), int(MAX_OPEN_B_MATCHES)


def save_status(data: dict) -> None:
    on, max_open = live_b_caps()
    data = dict(data)
    data["updated_at"] = iso_now()
    data["currently_open"] = len(open_matches(data))
    data["enabled"] = bool(on)
    data["max_open_b_matches"] = int(max_open)
    data["display_name"] = "Tennis crossover"
    data["watch_cadence"] = WATCH_CADENCE
    data["novig_orders"] = empty_status()["novig_orders"]
    data["pid"] = os.getpid()
    skipped = [row for row in (data.get("skipped") or []) if isinstance(row, dict)]
    if skipped:
        last = skipped[-1]
        data["last_skip_reason"] = f"{last.get('game') or ''}: {last.get('reason') or ''}".strip(": ")
    with venue_pace.FileLock(STATE_LOCK):
        _json_dump(STATE, data)


def open_matches(data: dict | None = None) -> list[dict]:
    status = data if isinstance(data, dict) else load_status()
    try:
        import open_count_sync

        return open_count_sync.open_rows("tennis_crossover", status)
    except Exception:
        pass
    out = []
    for row in status.get("matches") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("stage") or "") in OPEN_STAGES:
            out.append(row)
    return out


def open_game_names(data: dict | None = None) -> list[str]:
    return [str(row.get("game") or "") for row in open_matches(data) if row.get("game")]


def blocks_lock_bot(sport: str, title: str, data: dict | None = None) -> bool:
    """True when lock-bot must skip NEW pairs on this tennis match."""
    if str(sport or "").strip().lower() != "tennis":
        return False
    want = game_norm(title)
    if not want:
        return False
    for row in open_matches(data):
        if same_game(str(row.get("game") or ""), title):
            return True
        if want and want == game_norm(str(row.get("key") or "")):
            return True
    return False


def extra_pair_net_ok(
    cross_fill: Decimal,
    cross_fee: Decimal | None,
    fav_ask: Decimal,
    fav_spec: dict,
) -> bool:
    """True when the extra post-cross pair stays a 25c lock after fees."""
    fav_fee = live_lock_orders.leg_fee(fav_spec, fav_ask)
    if fav_fee is None:
        return False
    other = cross_fee if cross_fee is not None else Decimal("0")
    net = cross_fill + fav_ask + other + fav_fee
    return net <= (ONE - D)


def fav_target(cross_fill: Decimal) -> Decimal:
    return ONE - cross_fill - D


def in_yes_band(price: Decimal | None) -> bool:
    return price is not None and YES_LO < price < YES_HI


def in_c_band(cost: Decimal | None) -> bool:
    """Live T0 send: all-in C at most C_HI (1.05). No 0.95 floor. No wire 1.01 gate."""
    return cost is not None and cost <= C_HI


def t0_c_over_reason(cost: Decimal | None) -> str:
    if cost is None:
        return f"{T0_C_OVER_SKIP} all-in fee unknown"
    return f"{T0_C_OVER_SKIP} all-in C={_money(cost)}"


def t0_yes_asks_send_ok(
    pa: Decimal | None,
    pb: Decimal | None,
    venue: str | None = None,
    spec_a: dict | None = None,
    spec_b: dict | None = None,
) -> tuple[bool, str]:
    """Live T0 send: both Yes in (0.10, 0.90) and all-in C <= 1.05."""
    if not in_yes_band(pa) or not in_yes_band(pb):
        return False, "T0 Yes outside (0.10, 0.90)"
    spec_a = dict(spec_a or {})
    spec_b = dict(spec_b or {})
    shop = str(venue or "").strip()
    if shop and shop.lower() != "multi":
        spec_a.setdefault("venue", shop)
        spec_b.setdefault("venue", shop)
    v_a = str(spec_a.get("venue") or "").strip().lower()
    v_b = str(spec_b.get("venue") or "").strip().lower()
    if v_a == "multi":
        v_a = ""
        spec_a.pop("venue", None)
    if v_b == "multi":
        v_b = ""
        spec_b.pop("venue", None)
    if not v_a and not v_b:
        return True, "ok"
    all_in = t0_all_in_from_asks(spec_a, pa, spec_b, pb)
    if not in_c_band(all_in):
        return False, t0_c_over_reason(all_in)
    return True, "ok"


def mark_t0_c_over(match: dict, why: str) -> None:
    """Hard skip: no T0, no 50-cross, no dip. Slot is not currently_open."""
    match["stage"] = "abandoned"
    match["note"] = f"{why}; no T0, no 50-cross, no dip"
    match["skip_reason"] = T0_C_OVER_SKIP
    log(f"{match.get('game') or ''} {why}")
    tape_t0(match, "skip", why)


def t0_leg_fee(spec: dict, price: Decimal | None, payload=None) -> Decimal | None:
    """Documented 1-contract taker fee for T0 all-in. Missing schedule → None, not zero.

    Kalshi: 0.07×p×(1−p) to $0.0001 (not the lock-bot Kalshi-as-$0 default).
    Gemini: 0.07×p×(1−p) round up to the next cent.
    Polymarket: 0.0695×p×(1−p) banker's cent when the market coefficient is missing.
    Novig: c × p × (1 − p) when fee_coefficient + fee_charged are on the spec
    (GET fills `fee` overwrites). Else None — do not invent 0.06.
    """
    if price is None:
        return None
    returned = live_lock_orders.fee_returned(payload)
    venue = str((spec or {}).get("venue") or "").strip().lower()
    if venue == "kalshi":
        if returned is not None and returned > 0:
            return returned
        return live_lock_orders.kalshi_fee_amount(price)
    if venue == "gemini":
        return returned if returned is not None else live_lock_orders.gemini_taker_fee(price)
    if venue.startswith("polymarket"):
        if returned is not None:
            return returned
        theta = (spec or {}).get("fee_coefficient")
        if theta in (None, ""):
            theta = POLY_T0_THETA
        return polymarket_us_live.taker_fee(price, theta)
    if venue == "novig":
        if returned is not None:
            return returned
        return novig_live.taker_fee(
            price,
            (spec or {}).get("fee_coefficient"),
            (spec or {}).get("fee_charged"),
            (spec or {}).get("event_status"),
        )
    return None


def t0_all_in_from_asks(
    spec_a: dict,
    pay_a: Decimal | None,
    spec_b: dict,
    pay_b: Decimal | None,
    payload_a=None,
    payload_b=None,
) -> Decimal | None:
    """Both-Yes cash including documented taker fees. Missing fee → unknown, not zero."""
    if pay_a is None or pay_b is None:
        return None
    fee_a = t0_leg_fee(spec_a, pay_a, payload_a)
    fee_b = t0_leg_fee(spec_b, pay_b, payload_b)
    if fee_a is None or fee_b is None:
        return None
    return pay_a + pay_b + fee_a + fee_b


def should_stack_t0(all_in: Decimal | None) -> bool:
    """Stack another 1-contract pair only when all-in both-Yes is strictly under $1."""
    return all_in is not None and all_in < ONE


def _tape_once(parts) -> bool:
    """True the first time we see this snapshot key. Caps the in-memory set."""
    key = "\t".join("" if part is None else str(part) for part in parts)
    if key in _tape_seen:
        return False
    _tape_seen.add(key)
    if len(_tape_seen) > 4000:
        _tape_seen.clear()
        _tape_seen.add(key)
    return True


def tape_t0(match: dict, action: str, why: str, pa: Decimal | None = None, pb: Decimal | None = None) -> None:
    """orders.jsonl event=t0: both Yes asks + all-in C. Skip rows once per game/asks/reason."""
    match = match if isinstance(match, dict) else {}
    t0 = match.get("t0_yes") if isinstance(match.get("t0_yes"), dict) else {}
    a = t0.get("a") if isinstance(t0.get("a"), dict) else {}
    b = t0.get("b") if isinstance(t0.get("b"), dict) else {}
    if pa is None:
        pa = _dec(a.get("yes_ask") or a.get("price") or a.get("pay"))
    if pb is None:
        pb = _dec(b.get("yes_ask") or b.get("price") or b.get("pay"))
    spec_a = _player_spec(match, "a")
    spec_b = _player_spec(match, "b")
    all_in = t0_all_in_from_asks(spec_a, pa, spec_b, pb)
    if action != "send" and not _tape_once(
        ("t0", match.get("game"), action, why, _money(pa), _money(pb))
    ):
        return
    live_lock_orders.record_research_row(
        {
            "event": "t0",
            "action": action,
            "reason": str(why or "")[:400],
            "game": match.get("game") or "",
            "venue": match.get("venue") or spec_a.get("venue") or spec_b.get("venue") or "",
            "player_a": a.get("player") or spec_a.get("player") or "",
            "player_b": b.get("player") or spec_b.get("player") or "",
            "yes_a": _money(pa),
            "yes_b": _money(pb),
            "all_in_c": _money(all_in),
            "system": "tennis_crossover",
        }
    )


def tape_cross(
    match: dict,
    action: str,
    why: str,
    dog: str,
    fav: str,
    dog_ask: Decimal | None,
    fav_ask: Decimal | None,
    all_in: Decimal | None = None,
) -> None:
    """orders.jsonl event=cross: both Yes asks (Patel 80/81 reconstructable)."""
    match = match if isinstance(match, dict) else {}
    live_lock_orders.record_research_row(
        {
            "event": "cross",
            "action": action,
            "reason": str(why or "")[:400],
            "game": match.get("game") or "",
            "venue": match.get("venue") or "",
            "dog": dog,
            "fav": fav,
            "dog_yes": _money(dog_ask),
            "fav_yes": _money(fav_ask),
            "all_in_c": _money(all_in),
            "system": "tennis_crossover",
        }
    )


def t0_leg_confirmed(result: dict | None) -> bool:
    """Venue confirm qty >= 1 is fill truth. Mocked tests may only set filled / fill_qty."""
    result = result or {}
    confirm_qty = _dec(result.get("confirm_qty")) or Decimal("0")
    if result.get("confirm_known"):
        return confirm_qty >= ONE
    fill_qty = _dec(result.get("fill_qty")) or Decimal("0")
    return bool(result.get("filled")) or fill_qty >= ONE


def _t0_yes_cash_for_all_in(row: dict | None, spec: dict, match: dict | None = None) -> Decimal | None:
    """Pay-side Yes cash. Ignore BUY_SHORT inverted fill_px (Trungelliti / Wolff)."""
    row = row or {}
    ask = _t0_yes_quote(row, match)
    fill = _dec(row.get("fill_px"))
    intent = str(row.get("intent") or spec.get("intent") or "")
    inverted = "BUY_SHORT" in intent
    if fill is not None and ask is not None and abs((fill + ask) - ONE) <= Decimal("0.02"):
        inverted = True
    if inverted:
        return ask
    if fill is not None and ask is not None and abs(fill - ask) > Decimal("0.05"):
        return ask
    if fill is not None:
        return fill
    return ask


def t0_fill_all_in(match: dict) -> Decimal | None:
    t0 = match.get("t0_yes") or {}
    total = Decimal("0")
    for which in ("a", "b"):
        row = t0.get(which) or {}
        spec = _player_spec(match, which)
        px = _t0_yes_cash_for_all_in(row, spec, match)
        if px is None:
            return None
        fee = _dec(row.get("fill_fee"))
        if fee is None:
            fee = t0_leg_fee(spec, px)
        if fee is None:
            return None
        total += px + fee
    return total


def _t0_pair_funds_block(spec_a: dict, pay_a: Decimal, spec_b: dict, pay_b: Decimal) -> str:
    for spec, pay in ((spec_a, pay_a), (spec_b, pay_b)):
        live = dict(spec)
        live["outcome"] = "yes"
        live["_strategy_b"] = True
        built = live_lock_orders._spec_at_price(live, pay)
        if built is None:
            return "price not sendable"
        funds = live_lock_orders._funds_block(built)
        if funds:
            return live_lock_orders._balance_deny_from_funds(funds)
    return ""


def is_absorbing(price: Decimal | None) -> bool:
    if price is None:
        return False
    return price <= ABSORB or price >= (Decimal("0.95"))


def _phone_b_note(title: str, message: str) -> None:
    """Detached ntfy. Same helper as the lock bot. Does not wait. Does not place an order."""
    script = ROOT / "tools" / "ntfy_job_done.py"
    route = STAMP / "progress.html"
    try:
        import subprocess
        import win_hidden

        win_hidden.popen(
            [sys.executable, "-u", str(script), "--path", str(route), "-t", title, "-m", message],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            new_group=True,
        )
    except Exception:
        pass


def lock_bot_holds_game(title: str) -> bool:
    """Skip B when the Yes+No lock bot already has a leftover or unmatched one-leg."""
    try:
        rows = live_lock_orders.load_all_watches()
    except Exception:
        rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        game = str(row.get("game") or "")
        if game and same_game(game, title):
            if live_lock_orders.watch_is_active(row) or row.get("filled_venue"):
                return True
    if live_lock_orders.ORDERS_STOP.exists():
        try:
            import prediction_job_control

            latch_on, _text, when = prediction_job_control.orders_latch()
            legs = prediction_job_control.leftover_filled_legs(latch_on, when)
        except Exception:
            legs = []
        for row in legs:
            if same_game(str(row.get("game") or ""), title):
                return True
    return False


def _scan_mod():
    global _scan
    if _scan is not None:
        return _scan
    import live_game_pollers

    _scan = live_game_pollers.load_scan()
    return _scan


def tennis_slate() -> list[dict]:
    import live_game_pollers

    scan = _scan_mod()
    try:
        rows = live_game_pollers.tennis_rows(scan)
    except Exception as exc:
        log(f"tennis slate {type(exc).__name__}")
        return []
    return [row for row in rows if isinstance(row, dict)]


def _parse_start(value) -> datetime | None:
    if isinstance(value, datetime):
        stamp = value
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=ET)
        return stamp.astimezone(ET)
    text = str(value or "").strip()
    if not text or not is_clocked_start(text):
        return None
    got = parse_dt(text)
    if got is None:
        return None
    if got.tzinfo is None:
        got = got.replace(tzinfo=ET)
    return got.astimezone(ET)


def _iter_status_nodes(payload, depth: int = 0):
    """Walk venue payloads for status/start keys only. Does not invent fields."""
    if depth > 5 or not isinstance(payload, dict):
        return
    yield payload
    for key in ("eventState", "gameState", "metadata", "event", "market"):
        inner = payload.get(key)
        if isinstance(inner, dict):
            yield from _iter_status_nodes(inner, depth + 1)
    for key in ("contracts", "markets", "kalshi_events", "gemini_events", "polymarket", "novig_markets"):
        rows = payload.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict):
                yield from _iter_status_nodes(row, depth + 1)


def official_postponed_flag(*payloads) -> str:
    """Non-empty when a real status/period token says delayed, suspended, or postponed."""
    for payload in payloads:
        for node in _iter_status_nodes(payload):
            for key in _STATUS_KEYS:
                raw = node.get(key)
                token = str(raw or "").strip().lower()
                if token in POSTPONED_TOKENS:
                    return f"{key}={raw}"
    return ""


def live_start_from_payloads(*payloads) -> datetime | None:
    best = None
    for payload in payloads:
        for node in _iter_status_nodes(payload):
            for key in _START_KEYS:
                stamp = _parse_start(node.get(key))
                if stamp is None:
                    continue
                if best is None or stamp > best:
                    best = stamp
    return best


def start_moved_next_et_day(original: datetime | None, current: datetime | None) -> bool:
    if original is None or current is None:
        return False
    return current.astimezone(ET).date() > original.astimezone(ET).date()


def closed_without_settlement(*payloads) -> bool:
    """Kalshi/Polymarket closed (or closed=True) with no yes/no result or settled status."""
    saw_closed = False
    saw_settled = False
    for payload in payloads:
        for node in _iter_status_nodes(payload):
            status = str(node.get("status") or node.get("state") or "").strip().lower()
            result = str(node.get("result") or "").strip().lower()
            if result in {"yes", "no"} or status in {"settled", "determined", "finalized"}:
                saw_settled = True
            if status in {"closed", "inactive"}:
                saw_closed = True
            if node.get("closed") is True:
                saw_closed = True
    return saw_closed and not saw_settled


def kg_occurrence_from_payloads(*payloads) -> datetime | None:
    """Kalshi/Gemini occurrence_datetime (or Gemini event startTime) when present."""
    best = None
    for payload in payloads:
        for node in _iter_status_nodes(payload):
            stamp = _parse_start(node.get("occurrence_datetime"))
            if stamp is None and isinstance(node.get("contracts"), list):
                stamp = _parse_start(node.get("startTime"))
            if stamp is None:
                continue
            if best is None or stamp > best:
                best = stamp
    return best


def postponed_reason(*, original_start: datetime | None = None, payloads=()) -> str | None:
    flag = official_postponed_flag(*payloads)
    if flag:
        return flag
    occ = kg_occurrence_from_payloads(*payloads)
    if start_moved_next_et_day(original_start, occ):
        return f"occurrence moved to {occ.astimezone(ET).date().isoformat()} ET"
    live = live_start_from_payloads(*payloads)
    if start_moved_next_et_day(original_start, live):
        return f"start moved to {live.astimezone(ET).date().isoformat()} ET"
    if closed_without_settlement(*payloads):
        return "closed without settlement"
    return None


def original_start_of(match: dict | None, spec: dict | None = None) -> datetime | None:
    spec = spec or {}
    match = match or {}
    for raw in (
        match.get("occurrence"),
        spec.get("occurrence"),
        match.get("listed_start"),
        spec.get("listed_start"),
        spec.get("start"),
        match.get("t0_when"),
    ):
        stamp = _parse_start(raw)
        if stamp is not None:
            return stamp
    return None


def _titles_same_match(left: str, right: str) -> bool:
    if same_game(left, right):
        return True
    a = _split_vs(left)
    b = _split_vs(right)
    if len(a) != 2 or len(b) != 2:
        return False
    ta = {_player_token(a[0]), _player_token(a[1])}
    tb = {_player_token(b[0]), _player_token(b[1])}
    return bool(ta & tb) and ta == tb


def _poly_event_snapshot(title: str) -> dict:
    """Public Polymarket search for period / startTime. Cached. No trading keys."""
    want = str(title or "").strip()
    if not want:
        return {}
    key = "polyevt:" + game_norm(want)
    now = time.time()
    cached = _event_cache.get(key)
    if cached and now - cached[0] < EVENT_CACHE_SEC:
        return cached[1]
    payload: dict = {}
    try:
        names = _split_vs(want)
        query = " ".join(names) if names else want
        data = polymarket_us_live._get(
            polymarket_us_live.GATEWAY
            + "/v1/search?"
            + urllib.parse.urlencode({"query": query, "limit": "10"})
        )
        for event in data.get("events") or []:
            if isinstance(event, dict) and _titles_same_match(str(event.get("title") or ""), want):
                payload = event
                break
    except Exception:
        payload = {}
    _event_cache[key] = (now, payload)
    return payload


def live_postponed_reason(match: dict | None, spec: dict | None, scan=None) -> str | None:
    match = match if isinstance(match, dict) else {}
    spec = spec if isinstance(spec, dict) else {}
    events = {}
    if scan is not None and spec.get("key"):
        try:
            events = _fetch_events(scan, spec)
        except Exception:
            events = {}
    poly = _poly_event_snapshot(str(spec.get("title") or match.get("game") or ""))
    game = spec.get("game") if isinstance(spec.get("game"), dict) else {}
    payloads = (events, poly, spec, game, match)
    return postponed_reason(original_start=original_start_of(match, spec), payloads=payloads)


def mark_postponed(match: dict, reason: str) -> None:
    """Stage postponed. Do not sell. Holdings stay. Extras/cross/dip stop."""
    cancel_resting_fav_gtc(match, "postponed")
    match["stage"] = POSTPONED_STAGE
    match["postponed_reason"] = reason
    match["postponed_at"] = iso_now()
    match["note"] = (
        f"postponed ({reason}). Holdings stay. No extras/cross/dip. Latch untouched."
    )


def _t0_filled_any(match: dict) -> bool:
    t0 = match.get("t0_yes") or {}
    return bool((t0.get("a") or {}).get("filled") or (t0.get("b") or {}).get("filled"))


def release_untrusted_waiting_t0(match: dict, why: str) -> bool:
    """Unfilled waiting_t0 with no trusted clock must not occupy currently_open."""
    if str(match.get("stage") or "") != "waiting_t0":
        return False
    if _t0_filled_any(match) or match.get("stopped"):
        return False
    text = str(why or "")
    if "feed stamp" not in text and "no trusted clock" not in text:
        return False
    match["stage"] = "abandoned"
    match["note"] = f"{text}; slot released (no T0 sent)"
    return True


def cluster_counts(slate: list[dict], moment: datetime | None = None) -> dict:
    """Tennis starts in the next 15 and 60 minutes from listed/occurrence clocks."""
    moment = moment or now_et()
    n15 = n60 = 0
    samples = []
    for row in slate:
        listed = _parse_start(row.get("listed_start") or row.get("start") or "")
        occ = _parse_start(row.get("occurrence") or "")
        _clock, _src = live_t0_yes.choose_trusted_t0_clock(occ, listed)
        start = _clock or occ or listed
        if start is None:
            continue
        delta = (start - moment).total_seconds()
        if 0 <= delta <= 15 * 60:
            n15 += 1
        if 0 <= delta <= 60 * 60:
            n60 += 1
            samples.append((start, str(row.get("title") or row.get("key") or "")))
    samples.sort(key=lambda item: item[0])
    note = (
        f"{n15} tennis start(s) in the next 15 minutes, {n60} in the next 60 minutes. "
        f"max_open_b_matches={MAX_OPEN_B_MATCHES} so B will not fire a 06:00 ATP pile-up."
    )
    return {"cluster_15m": n15, "cluster_60m": n60, "cluster_note": note}


def _pump_ticks() -> None:
    """Append live poller ticks from today's tennis shard. Not a once-a-day CSV."""
    global _tick_offset, _tick_path
    day = now_et().strftime("%Y-%m-%d")
    path = price_memory.shard_jsonl_path(day, "tennis")
    if _tick_path != path:
        _tick_path = path
        _tick_offset = 0
    if not path.exists():
        return
    try:
        with path.open("r", encoding="utf-8") as handle:
            handle.seek(_tick_offset)
            blob = handle.read()
            _tick_offset = handle.tell()
    except OSError:
        return
    for line in blob.splitlines():
        line = line.strip()
        if not line or "moneyline" not in line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        if str(rec.get("sport") or "").lower() != "tennis":
            continue
        if str(rec.get("market_type") or "") != "moneyline":
            continue
        pay = str(rec.get("pay") or "yes").lower()
        if pay not in {"yes", "no"}:
            continue
        price = as_float(rec.get("price"))
        if price is None or price <= 0 or price >= 1:
            continue
        seen = parse_dt(str(rec.get("seen_at") or ""))
        if seen is None:
            continue
        ts = int(price_memory.to_et(seen).timestamp())
        game = rec.get("game") or ""
        side = rec.get("side") or rec.get("side_label") or ""
        venue = str(rec.get("venue") or "").strip()
        if not game or not side or not venue:
            continue
        key = (game_norm(game), venue.lower(), game_norm(side), pay)
        ticks = _series.setdefault(key, [])
        px = round(price, 4)
        if ticks and ticks[-1][0] == ts and ticks[-1][1] == px:
            continue
        if ticks and ticks[-1][1] == px:
            continue
        ticks.append((ts, px))
        start = str(rec.get("game_start") or "")
        if start:
            _starts.setdefault(game_norm(game), start)


def _merge_price_last() -> None:
    try:
        last = price_memory.load_last_sport("tennis")
    except Exception:
        return
    for rec in last.values() if isinstance(last, dict) else []:
        if not isinstance(rec, dict):
            continue
        if str(rec.get("sport") or "").lower() != "tennis":
            continue
        if str(rec.get("market_type") or "") != "moneyline":
            continue
        pay = str(rec.get("pay") or "yes").lower()
        if pay not in {"yes", "no"}:
            continue
        price = as_float(rec.get("price"))
        if price is None or price <= 0 or price >= 1:
            continue
        seen = parse_dt(str(rec.get("seen_at") or ""))
        if seen is None:
            continue
        ts = int(price_memory.to_et(seen).timestamp())
        game = rec.get("game") or ""
        side = rec.get("side") or ""
        venue = str(rec.get("venue") or "").strip()
        if not game or not side or not venue:
            continue
        key = (game_norm(game), venue.lower(), game_norm(side), pay)
        ticks = _series.setdefault(key, [])
        px = round(price, 4)
        if ticks and ticks[-1][0] == ts and ticks[-1][1] == px:
            continue
        if ticks and ticks[-1][1] == px:
            ticks[-1] = (ts, px)
            continue
        ticks.append((ts, px))


def pair_from_ticks(game: str, venue: str, player_a: str, player_b: str) -> dict | None:
    g = game_norm(game)
    v = venue.lower()
    a = game_norm(player_a)
    b = game_norm(player_b)
    yes_a = list(_series.get((g, v, a, "yes")) or [])
    yes_b = list(_series.get((g, v, b, "yes")) or [])
    if not yes_a or not yes_b:
        return None
    return {
        "game": game,
        "venue": venue,
        "side_a": player_a,
        "side_b": player_b,
        "yes_a": yes_a,
        "yes_b": yes_b,
        "no_a": list(_series.get((g, v, a, "no")) or []),
        "no_b": list(_series.get((g, v, b, "no")) or []),
        "start": _starts.get(g) or "",
        "start_dt": _parse_start(_starts.get(g) or ""),
    }


def assign_live_t0(pair: dict, listed_dt: datetime | None, occ_dt: datetime | None) -> None:
    """Match assign_actual_t0 as closely as live poller ticks allow."""
    pair["start"] = listed_dt.isoformat() if listed_dt is not None else (pair.get("start") or "")
    pair["start_dt"] = listed_dt if listed_dt is not None else pair.get("start_dt")
    lookup = {}
    if occ_dt is not None:
        lookup[game_norm(pair.get("game") or "")] = (occ_dt.isoformat(), "occurrence")
    assign_actual_t0(pair, lookup)


def _player_token(name: str) -> str:
    parts = [tok for tok in (name or "").replace(".", " ").split() if tok]
    return parts[-1].lower() if parts else ""


def _player_id(name: str) -> str:
    return _player_token(name) or game_norm(name)


def _sendable_venue(venue: str) -> bool:
    v = str(venue or "").strip().lower()
    if v not in VENUE_ORDER:
        return False
    if v == "novig":
        return bool(novig_live.orders_live())
    return True


def cheapest_memory_yes(game: str, player: str) -> tuple[Decimal | None, str]:
    """Min latest Yes ask for this player across venues. Memory only. No REST."""
    g = game_norm(game)
    want = _player_id(player)
    want_full = game_norm(player)
    best_ask: Decimal | None = None
    best_venue = ""
    for (gg, venue, side, pay), ticks in list(_series.items()):
        if gg != g or pay != "yes" or not ticks:
            continue
        if not _sendable_venue(str(venue or "")):
            continue
        if _player_id(side) != want and game_norm(side) != want_full:
            continue
        try:
            ask = Decimal(str(ticks[-1][1]))
        except Exception:
            continue
        if best_ask is None or ask < best_ask:
            best_ask = ask
            best_venue = str(venue or "").lower()
        elif ask == best_ask:
            cur = str(venue or "").lower()
            if VENUE_ORDER.index(cur) < VENUE_ORDER.index(best_venue or cur):
                best_venue = cur
    return best_ask, best_venue


def memory_venues_for_cheapest(game: str, names: list[str]) -> list[str]:
    """Venues that currently hold the min Yes for the named players."""
    found: list[str] = []
    for name in names:
        _ask, venue = cheapest_memory_yes(game, name)
        if venue and venue not in found:
            found.append(venue)
    return found


def _shop_from_books(books: list[dict]) -> dict:
    shop: dict[str, dict] = {}
    for book in books or []:
        venue = str(book.get("venue") or "").lower()
        for row in book.get("players") or []:
            if not isinstance(row, dict):
                continue
            spec = dict(row)
            spec.setdefault("venue", venue)
            pid = _player_id(spec.get("player") or "")
            if not pid:
                continue
            shop.setdefault(pid, {})[str(spec.get("venue") or venue).lower()] = spec
    return shop


def shop_player_spec(match: dict, player: str, venue: str | None = None) -> dict:
    """Instrument spec for player on venue. T0 spec if same book; else shop catalog."""
    which = _which_player(match, player)
    base = _player_spec(match, which)
    want = str(venue or base.get("venue") or match.get("venue") or "").strip().lower()
    if want in {"", "multi"}:
        want = str(base.get("venue") or match.get("venue") or "").strip().lower()
    shop = match.get("shop") if isinstance(match.get("shop"), dict) else {}
    pid = _player_id(player)
    hit = None
    bag = shop.get(pid) if isinstance(shop.get(pid), dict) else None
    if isinstance(bag, dict):
        hit = bag.get(want)
    if not isinstance(hit, dict):
        for key, venues in shop.items():
            if not isinstance(venues, dict):
                continue
            if _player_id(str(key)) != pid and game_norm(str(key)) != game_norm(player):
                continue
            cand = venues.get(want)
            if isinstance(cand, dict):
                hit = cand
                break
    if isinstance(hit, dict) and (hit.get("instrument") or hit.get("outcome_id")):
        spec = dict(hit)
        spec["player"] = player
        spec.setdefault("venue", want)
        spec.setdefault("outcome", "yes")
        return spec
    if str(base.get("venue") or "").lower() == want:
        return base
    hydrated = _hydrate_shop_spec(match, player, want)
    if hydrated is not None:
        return hydrated
    return base


def _hydrate_shop_spec(match: dict, player: str, venue: str) -> dict | None:
    """One-venue event fetch for a shop miss. Not a 4-platform hunt."""
    venue = str(venue or "").strip().lower()
    if not venue or not _sendable_venue(venue):
        return None
    try:
        scan = _scan_mod()
        spec = {
            "title": match.get("game") or "",
            "key": match.get("key") or "",
            "game": match.get("game_payload") if isinstance(match.get("game_payload"), dict) else {},
        }
        books = moneyline_yes_books(scan, spec, venues=[venue])
    except Exception:
        return None
    shop = _shop_from_books(books)
    match["shop"] = {**(match.get("shop") or {}), **shop}
    pid = _player_id(player)
    bag = shop.get(pid) if isinstance(shop.get(pid), dict) else None
    hit = bag.get(venue) if isinstance(bag, dict) else None
    if isinstance(hit, dict) and (hit.get("instrument") or hit.get("outcome_id")):
        out = dict(hit)
        out["player"] = player
        out.setdefault("venue", venue)
        out.setdefault("outcome", "yes")
        return out
    return None


def _split_vs(title: str) -> list[str]:
    import re

    parts = re.split(r"\s+vs\.?\s+", title or "", maxsplit=1, flags=re.I)
    return [part.strip() for part in parts if part.strip()]


def _yes_spec_from_view(venue: str, view: dict, player: str) -> dict | None:
    pay = _dec(view.get("yes"))
    if pay is None:
        return None
    ident = str(view.get("ident") or "")
    if venue == "kalshi":
        if not ident:
            return None
        return {
            "venue": "kalshi",
            "instrument": ident,
            "outcome": "yes",
            "pay": _money(pay),
            "player": player,
            "intent": "",
        }
    if venue == "gemini":
        if not ident:
            return None
        return {
            "venue": "gemini",
            "instrument": ident,
            "outcome": "yes",
            "pay": _money(pay),
            "player": player,
            "intent": "",
        }
    if venue == "polymarket":
        intent = str(view.get("poly_yes_intent") or "ORDER_INTENT_BUY_LONG")
        if not ident or not intent:
            return None
        return {
            "venue": "polymarket",
            "instrument": ident,
            "outcome": "yes",
            "pay": _money(pay),
            "player": player,
            "intent": intent,
            "fee_coefficient": view.get("fee_coefficient"),
        }
    if venue == "novig":
        yes_id = str(view.get("buy_yes_outcome") or view.get("yes_outcome_id") or "")
        no_id = str(view.get("buy_no_outcome") or view.get("no_outcome_id") or "")
        if not ident or not yes_id:
            return None
        return {
            "venue": "novig",
            "instrument": ident,
            "outcome": "yes",
            "pay": _money(pay),
            "player": player,
            "intent": "",
            "outcome_id": yes_id,
            "yes_outcome_id": yes_id,
            "no_outcome_id": no_id,
            "fee_coefficient": view.get("fee_coefficient"),
            "fee_charged": view.get("fee_charged"),
            "event_status": view.get("event_status"),
        }
    return None


def _fetch_events(scan, spec: dict, venues: list[str] | tuple[str, ...] | None = None) -> dict:
    want = {str(v).strip().lower() for v in (venues or VENUE_ORDER) if str(v).strip()}
    if not want:
        want = set(VENUE_ORDER)
    key = str(spec.get("key") or "")
    cache_key = key + "|" + ",".join(sorted(want))
    now = time.time()
    cached = _event_cache.get(cache_key)
    if cached and now - cached[0] < EVENT_CACHE_SEC:
        return cached[1]
    game = spec.get("game") if isinstance(spec.get("game"), dict) else {}
    k_tickers, g_tickers = scan.tickers_of(game) if game else ([], [])
    kalshi_events = []
    gemini_events = []
    if "kalshi" in want:
        for ticker in k_tickers:
            try:
                kalshi_events.append(scan.fetch_kalshi_event(ticker))
            except Exception:
                continue
    if "gemini" in want:
        for ticker in g_tickers:
            try:
                gemini_events.append(scan.fetch_gemini_event(ticker))
            except Exception:
                continue
    polymarket = []
    novig_markets = []
    try:
        import live_game_pollers
    except Exception:
        live_game_pollers = None
    if "polymarket" in want:
        try:
            if live_game_pollers is None:
                raise RuntimeError("live_game_pollers missing")
            polymarket = live_game_pollers._polymarket_contracts(game, scan, kalshi_events, gemini_events)
        except Exception:
            polymarket = list(game.get("polymarket_markets") or [])
    if "novig" in want:
        try:
            if live_game_pollers is None:
                raise RuntimeError("live_game_pollers missing")
            novig_markets = live_game_pollers._novig_contracts(
                game, scan, kalshi_events, gemini_events, "tennis"
            )
        except Exception:
            novig_markets = list(game.get("novig_markets") or [])
    occ = None
    for ev in kalshi_events:
        if not isinstance(ev, dict):
            continue
        for contract in ev.get("contracts") or []:
            if not isinstance(contract, dict):
                continue
            stamp = _parse_start(contract.get("occurrence_datetime") or "")
            if stamp is not None:
                occ = stamp
                break
        if occ is None:
            occ = _parse_start(ev.get("occurrence_datetime") or ev.get("target_datetime") or "")
        if occ is not None:
            break
    if occ is None:
        for ev in gemini_events:
            if not isinstance(ev, dict):
                continue
            occ = _parse_start(ev.get("startTime") or ev.get("occurrence_datetime") or "")
            if occ is not None:
                break
    payload = {
        "kalshi_events": kalshi_events,
        "gemini_events": gemini_events,
        "polymarket": polymarket or [],
        "novig_markets": novig_markets or [],
        "occurrence": occ,
    }
    _event_cache[cache_key] = (now, payload)
    return payload


def moneyline_yes_books(scan, spec: dict, venues: list[str] | tuple[str, ...] | None = None) -> list[dict]:
    """Per-venue two-player Yes books. Pick cheapest legs across them.

    venues=None reads every sendable shop. Pass 1–2 winners from memory so
    T0 does not REST-hunt the world. Novig is a send venue when orders are live.
    """
    events = _fetch_events(scan, spec, venues=venues)
    game = spec.get("game") if isinstance(spec.get("game"), dict) else {}
    title = str(spec.get("title") or "")
    names = _split_vs(title)
    books = []
    try:
        k_views = [
            v
            for v in scan.load_views(events.get("kalshi_events") or [], "kalshi")
            if str(v.get("kind") or "") == "moneyline"
        ]
    except Exception:
        k_views = []
    try:
        g_views = [
            v
            for v in scan.load_views(events.get("gemini_events") or [], "gemini")
            if str(v.get("kind") or "") == "moneyline"
        ]
    except Exception:
        g_views = []
    poly_views = []
    for contract in events.get("polymarket") or []:
        if not isinstance(contract, dict):
            continue
        parsed = contract if contract.get("long_name") else polymarket_us_live.two_way_moneyline(contract)
        if not parsed:
            continue
        try:
            poly_views.extend(polymarket_us_live.contract_views(parsed if parsed.get("yes_ask") is not None else contract))
        except Exception:
            continue
    n_views = []
    if novig_live.orders_live():
        for contract in events.get("novig_markets") or []:
            if not isinstance(contract, dict):
                continue
            if str(contract.get("kind") or "moneyline") != "moneyline":
                continue
            try:
                n_views.extend(novig_live.contract_views(contract))
            except Exception:
                continue
    grouped = {"kalshi": k_views, "gemini": g_views, "polymarket": poly_views, "novig": n_views}
    for venue in VENUE_ORDER:
        views = [v for v in grouped.get(venue) or [] if isinstance(v, dict) and v.get("yes") is not None]
        players = []
        seen = set()
        for view in views:
            player = str(view.get("label") or view.get("side") or "").strip()
            token = game_norm(player)
            if not player or token in seen:
                continue
            spec_row = _yes_spec_from_view(venue, view, player)
            if spec_row is None:
                continue
            seen.add(token)
            players.append(spec_row)
        if len(players) < 2:
            continue
        if names and len(names) == 2:
            mapped = []
            for name in names:
                hit = next((row for row in players if _player_token(row["player"]) == _player_token(name) or game_norm(name) in game_norm(row["player"])), None)
                if hit:
                    mapped.append(hit)
            if len(mapped) == 2:
                players = mapped
        books.append(
            {
                "venue": venue,
                "title": title,
                "players": players[:2],
                "occurrence": events.get("occurrence"),
                "game": game,
                "key": spec.get("key") or "",
            }
        )
    return books


def rank_cheapest_legs(books: list[dict]) -> dict | None:
    """Min Yes ask per player across venues. Cross-platform pair allowed. No C_HI gate."""
    best: dict[str, dict] = {}
    meta = None
    title_names: list[str] = []
    for book in books or []:
        if not isinstance(book, dict):
            continue
        if meta is None:
            meta = book
            title_names = _split_vs(str(book.get("title") or ""))
        venue = str(book.get("venue") or "")
        if not _sendable_venue(venue):
            continue
        for row in book.get("players") or []:
            if not isinstance(row, dict):
                continue
            pay = _dec(row.get("pay"))
            if pay is None or not in_yes_band(pay) or is_absorbing(pay):
                continue
            spec = dict(row)
            spec.setdefault("venue", venue)
            if not _sendable_venue(str(spec.get("venue") or "")):
                continue
            if t0_leg_fee(spec, pay) is None:
                # Unpriced after-fee (usually Novig without a schedule). Do not
                # let that cheapest wire win the pair and then skip the match.
                continue
            pid = _player_id(spec.get("player") or "")
            if not pid:
                continue
            prev = best.get(pid)
            prev_pay = _dec(prev.get("pay")) if prev else None
            take = prev is None or (prev_pay is not None and pay < prev_pay)
            if not take and prev_pay == pay:
                prev_v = str((prev or {}).get("venue") or "")
                new_v = str(spec.get("venue") or "")
                if prev_v in VENUE_ORDER and new_v in VENUE_ORDER:
                    take = VENUE_ORDER.index(new_v) < VENUE_ORDER.index(prev_v)
            if take:
                best[pid] = spec
    if len(best) < 2:
        return None
    ids: list[str] = []
    if len(title_names) == 2:
        ids = [_player_id(name) for name in title_names]
        if any(i not in best for i in ids):
            ids = []
    if len(ids) != 2:
        first_players = list((meta or {}).get("players") or [])[:2]
        ids = [_player_id(str((row or {}).get("player") or "")) for row in first_players]
        if any(i not in best for i in ids) or len(ids) != 2:
            ids = list(best.keys())[:2]
    if len(ids) != 2 or ids[0] == ids[1]:
        return None
    players = [best[ids[0]], best[ids[1]]]
    v_a = str(players[0].get("venue") or "")
    v_b = str(players[1].get("venue") or "")
    out = dict(meta or {})
    out["players"] = players
    out["venue"] = v_a if v_a == v_b else "multi"
    out["shop_pick"] = "cheapest_leg"
    return out


def pick_cheapest_legs(books: list[dict]) -> dict | None:
    """Min Yes ask per player across venues. Cross-platform pair allowed.

    All-in C ≤ 1.05 HOLD is the sum of the two chosen after-fee asks.
    """
    out = rank_cheapest_legs(books)
    if out is None:
        return None
    players = out.get("players") or []
    if len(players) != 2:
        return None
    pa = _dec(players[0].get("pay"))
    pb = _dec(players[1].get("pay"))
    ok, _why = t0_yes_asks_send_ok(pa, pb, spec_a=players[0], spec_b=players[1])
    if not ok:
        return None
    return out


def pick_t0_book(books: list[dict]) -> dict | None:
    """Cheapest Yes per player across all listed platforms. Same-venue still wins ties."""
    return pick_cheapest_legs(books)


def recheck_yes(spec: dict, *, pace: bool = False) -> tuple[Decimal | None, str]:
    """Recheck the live book ask immediately before a send.

    pace=False is the confirm-before-send path: reserved HTTP seat, never
    skip, does not sit behind catalog / leftover / C-D-E walks.
    Catalog / T0-slate reads keep paced background fetches that may skip.
    """
    built = {
        "venue": spec.get("venue"),
        "instrument": spec.get("instrument"),
        "outcome": "yes",
        "intent": spec.get("intent") or "",
        "outcome_id": spec.get("outcome_id") or "",
        "fee_coefficient": spec.get("fee_coefficient"),
        "fee_charged": spec.get("fee_charged"),
        "event_status": spec.get("event_status"),
    }
    price, note = live_lock_orders.fetch_book_ask(built, pace=pace)
    if built.get("quote_size") not in (None, ""):
        live_lock_orders._attach_quote_size(spec, built.get("quote_size"))
    if price is None:
        return None, note or "book ask missing"
    snapped = live_lock_orders.snap_pay(str(spec.get("venue") or ""), price)
    if snapped is None:
        return None, "ask not sendable"
    return snapped, "book"


def send_yes_ioc(spec: dict, pay: Decimal, step: str, bet_key: str, log_fn=log) -> dict:
    """One Yes contract after a book recheck. Poly FOK; Kalshi/Gemini/Novig IOC."""
    live = dict(spec)
    live["outcome"] = "yes"
    live["_strategy_b"] = True
    live["quote_source"] = "book"
    live["quote_price"] = _money(pay)
    live["quote_seen_at"] = iso_now()
    built = live_lock_orders._spec_at_price(live, pay)
    blank = {
        "filled": False,
        "posted": False,
        "payload": None,
        "status": 0,
        "note": "price not sendable",
        "pay": _money(pay),
        "spec": live,
        "order_id": "",
        "fill_qty": "0",
        "sent_at": "",
    }
    if built is None:
        return blank
    built["_strategy_b"] = True
    built["_bet_key"] = bet_key
    built["_step"] = step
    live_lock_orders._carry_quote_fields(live, built)
    skip = live_lock_orders.poly_size_lt_qty_skip(built)
    if skip:
        log_fn(f"b skip {skip}")
        live_lock_orders.record_research_row(
            {
                "event": "b_skip",
                "action": "skip",
                "reason": skip,
                "game": spec.get("game") or live.get("game") or "",
                "venue": built.get("venue") or "",
                "instrument": built.get("instrument") or "",
                "quote_size": built.get("quote_size") or "",
                "quote_price": built.get("quote_price") or _money(pay),
                "step": step,
                "system": "tennis_crossover",
            }
        )
        blank["note"] = skip
        blank["spec"] = built
        return blank
    funds = live_lock_orders._funds_block(built)
    if funds:
        named = live_lock_orders._balance_deny_from_funds(funds)
        log_fn(f"b skip funds {named}")
        blank["note"] = named
        return blank
    status, payload, note = live_lock_orders._post_same_limit(
        log_fn, bet_key, built, step, live_lock_orders._send, pay, None, None
    )
    filled_qty = live_lock_orders.filled_contracts(payload) if payload is not None else Decimal("0")
    if status not in (200, 201) and not live_lock_orders.venue_confirm_known(payload):
        filled_qty = Decimal("0")
    if live_lock_orders.poly_partial_unexpected(built, filled_qty):
        live_lock_orders.note_poly_fok_partial(built, filled_qty, log_fn)
    if status in (200, 201) and live_lock_orders.order_still_open(payload) and filled_qty < SIZE:
        cancel_status, cancel_note = live_lock_orders._cancel(built, payload)
        log_fn(f"b cancel venue={built.get('venue')} http={cancel_status} {cancel_note}")
        # Keep filled qty. Cancelling the unfilled remainder is not a miss that retries.
    fill_px = live_lock_orders._actual_fill_cash(built, payload) if filled_qty > 0 else None
    fill_fee = live_lock_orders.leg_fee(built, fill_px, payload) if fill_px is not None else None
    confirm = live_lock_orders.venue_confirm_of(payload) or {}
    posted = status != 0
    return {
        "filled": filled_qty >= SIZE,
        "posted": posted,
        "payload": payload,
        "status": status,
        "note": note,
        "pay": built.get("pay") or _money(pay),
        "spec": built,
        "order_id": live_lock_orders._order_id(payload),
        "fill_qty": _money(filled_qty),
        "fill_px": _money(fill_px) if fill_px is not None else "",
        "fill_fee": _money(fill_fee) if fill_fee is not None else "",
        "sent_at": built.get("sent_at") or iso_now() if posted else "",
        "http": status,
        "confirm_known": bool(confirm.get("known")),
        "confirm_qty": str(confirm.get("qty") or "0"),
        "confirm_note": str(confirm.get("note") or ""),
        "confirm_mismatch": bool(confirm.get("mismatch")),
    }


def venue_gtc_tif(venue: str) -> tuple[str, str] | None:
    """Field name and official GTC TIF string, or None if this shop cannot rest."""
    return VENUE_GTC_TIF.get(str(venue or "").strip().lower())


def apply_gtc_body(built: dict) -> tuple[bool, str]:
    """Rewrite an IOC/FOK one-contract body to the venue's resting GTC TIF."""
    venue = str(built.get("venue") or "").strip().lower()
    field = venue_gtc_tif(venue)
    if not field:
        return False, f"gtc_unsupported venue={venue or 'blank'}"
    body = dict(built.get("body") or {})
    key, value = field
    body[key] = value
    if venue == "polymarket":
        body["tif"] = live_lock_orders.POLY_TIF_GTC
        body["synchronousExecution"] = False
        value = live_lock_orders.POLY_TIF_GTC
    if venue == "gemini":
        body.pop("makerOrCancel", None)
        body["makerOrCancel"] = False
    built["body"] = body
    built["_tif"] = "gtc"
    return True, value


def send_yes_gtc(spec: dict, pay: Decimal, step: str, bet_key: str, log_fn=log) -> dict:
    """One Yes GTC rest at `pay`. Does not cancel a still-open remainder.

    Poly TIF is GOOD_TILL_CANCEL, not FOK. Displayed ask size is not a skip:
    this is a resting bid, not a take of the current ask.
    """
    live = dict(spec)
    live["outcome"] = "yes"
    live["_strategy_b"] = True
    live["_tif"] = "gtc"
    live["quote_source"] = "book"
    live["quote_price"] = _money(pay)
    live["quote_seen_at"] = iso_now()
    built = live_lock_orders._spec_at_price(live, pay)
    blank = {
        "filled": False,
        "posted": False,
        "payload": None,
        "status": 0,
        "note": "price not sendable",
        "pay": _money(pay),
        "spec": live,
        "order_id": "",
        "fill_qty": "0",
        "sent_at": "",
        "tif": "gtc",
    }
    if built is None:
        return blank
    ok, tif = apply_gtc_body(built)
    if not ok:
        blank["note"] = tif
        blank["spec"] = built
        return blank
    built["_strategy_b"] = True
    built["_tif"] = "gtc"
    built["_bet_key"] = bet_key
    built["_step"] = step
    live_lock_orders._carry_quote_fields(live, built)
    funds = live_lock_orders._funds_block(built)
    if funds:
        named = live_lock_orders._balance_deny_from_funds(funds)
        log_fn(f"b skip funds {named}")
        blank["note"] = named
        return blank
    status, payload, note = live_lock_orders._post_same_limit(
        log_fn, bet_key, built, step, live_lock_orders._send, pay, None, None
    )
    filled_qty = live_lock_orders.filled_contracts(payload) if payload is not None else Decimal("0")
    if status not in (200, 201) and not live_lock_orders.venue_confirm_known(payload):
        filled_qty = Decimal("0")
    fill_px = live_lock_orders._actual_fill_cash(built, payload) if filled_qty > 0 else None
    fill_fee = live_lock_orders.leg_fee(built, fill_px, payload) if fill_px is not None else None
    confirm = live_lock_orders.venue_confirm_of(payload) or {}
    posted = status != 0
    return {
        "filled": filled_qty >= SIZE,
        "posted": posted,
        "payload": payload,
        "status": status,
        "note": note,
        "pay": built.get("pay") or _money(pay),
        "spec": built,
        "order_id": live_lock_orders._order_id(payload),
        "fill_qty": _money(filled_qty),
        "fill_px": _money(fill_px) if fill_px is not None else "",
        "fill_fee": _money(fill_fee) if fill_fee is not None else "",
        "sent_at": built.get("sent_at") or iso_now() if posted else "",
        "http": status,
        "tif": tif,
        "confirm_known": bool(confirm.get("known")),
        "confirm_qty": str(confirm.get("qty") or "0"),
        "confirm_note": str(confirm.get("note") or ""),
        "confirm_mismatch": bool(confirm.get("mismatch")),
        "resting": bool(
            posted
            and filled_qty < SIZE
            and (live_lock_orders.order_still_open(payload) or live_lock_orders._order_id(payload))
        ),
    }


def tape_fav_dip(match: dict, action: str, why: str, pay: Decimal | None = None, tif: str = "") -> None:
    if action not in {"rest", "fill", "cancel"} and not _tape_once(
        ("fav_dip", match.get("game"), action, why, _money(pay), tif)
    ):
        return
    live_lock_orders.record_research_row(
        {
            "event": "fav_dip",
            "action": action,
            "reason": str(why or "")[:400],
            "game": match.get("game") or "",
            "venue": match.get("venue") or "",
            "fav": match.get("fav_player") or "",
            "fav_target": match.get("fav_target") or "",
            "pay": _money(pay),
            "tif": tif,
            "cross_fill": match.get("cross_fill") or "",
            "system": "tennis_crossover",
        }
    )


def _slim_gtc_spec(spec: dict) -> dict:
    keys = (
        "venue",
        "instrument",
        "outcome",
        "intent",
        "pay",
        "player",
        "fee_coefficient",
        "fee_charged",
        "event_status",
        "outcome_id",
        "quote_price",
        "quote_source",
        "game",
        "_strategy_b",
        "_tif",
        "_bet_key",
        "_step",
    )
    out = {key: spec.get(key) for key in keys if spec.get(key) not in (None, "")}
    out["_strategy_b"] = True
    out["_tif"] = "gtc"
    out["outcome"] = "yes"
    return out


def _remember_fav_gtc(match: dict, spec: dict, result: dict) -> None:
    match["fav_gtc_spec"] = _slim_gtc_spec(result.get("spec") or spec)
    match["fav_gtc_payload"] = result.get("payload")
    match["fav_gtc_order_id"] = str(result.get("order_id") or "")
    match["fav_gtc_pay"] = str(result.get("pay") or "")
    match["fav_gtc_sent_at"] = str(result.get("sent_at") or "")
    match["fav_gtc_tif"] = str(result.get("tif") or "gtc")


def _fav_gtc_resting(match: dict) -> bool:
    if str(match.get("stage") or "") == "fav_gtc_resting":
        return True
    return bool(match.get("fav_gtc_sent")) and not match.get("fav_gtc_filled")


def cancel_resting_fav_gtc(match: dict, why: str) -> None:
    """Cancel a resting favorite-dip GTC. No-op if none / already filled."""
    if match.get("fav_gtc_filled"):
        return
    spec = match.get("fav_gtc_spec")
    payload = match.get("fav_gtc_payload")
    order_id = str(match.get("fav_gtc_order_id") or "")
    if not isinstance(spec, dict) or (not order_id and not payload):
        return
    try:
        status, note = live_lock_orders._cancel(spec, payload if payload is not None else {"id": order_id})
    except Exception as exc:
        status, note = 0, type(exc).__name__
    match["fav_gtc_cancelled"] = True
    match["fav_gtc_cancel_why"] = why
    match["fav_gtc_cancel_http"] = status
    match["fav_gtc_cancel_note"] = str(note or "")
    log(
        f"b fav GTC cancel game={match.get('game')} why={why} "
        f"http={status} {note} oid={order_id}"
    )
    tape_fav_dip(match, "cancel", why, _dec(match.get("fav_gtc_pay")), str(match.get("fav_gtc_tif") or "gtc"))


def _apply_fav_fill(match: dict, result: dict, spec: dict | None = None) -> None:
    """Persist platform-confirmed house cash. Poly BUY_SHORT debit, not Yes-wire."""
    payload = result.get("payload")
    built = result.get("spec") or spec or match.get("fav_gtc_spec") or {}
    qty = _ticket_qty(result)
    fill_px = _dec(result.get("fill_px"))
    if fill_px is None and qty > 0:
        fill_px = live_lock_orders._actual_fill_cash(built, payload)
    fill_fee = _dec(result.get("fill_fee"))
    if fill_fee is None and fill_px is not None:
        fill_fee = live_lock_orders.leg_fee(built, fill_px, payload)
    match["last_order"] = _order_snapshot(result)
    match["fav_fill"] = _money(fill_px) if fill_px is not None else str(result.get("fill_px") or "")
    match["fav_fill_fee"] = _money(fill_fee) if fill_fee is not None else str(result.get("fill_fee") or "")
    match["fav_fill_qty"] = _money(qty)
    match["fav_gtc_filled"] = True
    match["fav_ioc_sent"] = True
    match["stage"] = "done"
    match["note"] = "B complete: T0 both + underdog cross + original-favorite lock"


def poll_fav_gtc_fill(match: dict) -> bool:
    """Confirm a resting GTC with the platform. True when house qty >= 1."""
    spec = match.get("fav_gtc_spec")
    if not isinstance(spec, dict):
        return False
    payload = match.get("fav_gtc_payload")
    try:
        import venue_fill_confirm

        confirm = venue_fill_confirm.confirm_order(
            str(spec.get("venue") or match.get("venue") or ""),
            payload,
            spec,
            tries=1,
            timeout=1.5,
            sleep_sec=0,
        )
        payload = venue_fill_confirm.attach(payload, confirm)
    except Exception as exc:
        log(f"b fav GTC confirm {match.get('game')} {type(exc).__name__}")
        return False
    match["fav_gtc_payload"] = payload
    qty = live_lock_orders.filled_contracts(payload) if payload is not None else Decimal("0")
    extra = _dec(match.get("fav_fill_qty"))
    if extra is not None and extra > qty:
        qty = extra
    if qty < SIZE:
        return False
    fill_px = live_lock_orders._actual_fill_cash(spec, payload)
    fill_fee = live_lock_orders.leg_fee(spec, fill_px, payload) if fill_px is not None else None
    _apply_fav_fill(
        match,
        {
            "payload": payload,
            "spec": spec,
            "fill_qty": _money(qty),
            "fill_px": _money(fill_px) if fill_px is not None else "",
            "fill_fee": _money(fill_fee) if fill_fee is not None else "",
            "order_id": match.get("fav_gtc_order_id") or live_lock_orders._order_id(payload),
            "status": 200,
            "sent_at": match.get("fav_gtc_sent_at") or "",
            "note": "gtc filled",
        },
        spec,
    )
    tape_fav_dip(match, "fill", "gtc filled", fill_px, str(match.get("fav_gtc_tif") or "gtc"))
    return True


def _order_snapshot(result: dict | None) -> dict:
    result = result or {}
    return {
        "id": str(result.get("order_id") or ""),
        "time": str(result.get("sent_at") or ""),
        "http": result.get("status") if result.get("status") is not None else result.get("http"),
        "fill_qty": str(result.get("fill_qty") or "0"),
        "note": str(result.get("note") or ""),
        "pay": str(result.get("pay") or ""),
    }


def _ticket_qty(result: dict | None) -> Decimal:
    """Filled qty on a B extra. Partial > 0 counts; it is never a zero miss."""
    return live_lock_orders.outcome_fill_qty(result)


def _quote_snapshot(players: list[dict]) -> dict:
    out = {}
    for row in players:
        out[str(row.get("player") or "")] = {
            "venue": row.get("venue") or "",
            "instrument": row.get("instrument") or "",
            "ask": row.get("pay") or "",
        }
    return out


def _match_row(spec: dict, book: dict, stage: str) -> dict:
    players = book.get("players") or []
    a = players[0] if players else {}
    b = players[1] if len(players) > 1 else {}
    pa = _dec(a.get("pay"))
    pb = _dec(b.get("pay"))
    fav_is_a = (pb is None) or (pa is not None and pa >= (pb or Decimal("0")))
    return {
        "key": spec.get("key") or book.get("key") or "",
        "game": spec.get("title") or book.get("title") or "",
        "sport": "tennis",
        "venue": book.get("venue") or "",
        "stage": stage,
        "opened_at": iso_now(),
        "t0_label": "",
        "t0_when": "",
        "occurrence": book.get("occurrence").isoformat() if isinstance(book.get("occurrence"), datetime) else str(book.get("occurrence") or ""),
        "listed_start": spec.get("listed_start") or spec.get("start") or "",
        "c": _money(pa + pb) if pa is not None and pb is not None else "",
        "fav_player": str((a if fav_is_a else b).get("player") or ""),
        "dog_player": str((b if fav_is_a else a).get("player") or ""),
        "t0_yes": {
            "a": {
                "player": a.get("player") or "",
                "price": a.get("pay") or "",
                "yes_ask": a.get("pay") or "",
                "filled": False,
                "instrument": a.get("instrument") or "",
                "venue": a.get("venue") or book.get("venue") or "",
                "intent": a.get("intent") or "",
                "fee_coefficient": a.get("fee_coefficient"),
                "fee_charged": a.get("fee_charged"),
                "event_status": a.get("event_status"),
                "outcome_id": a.get("outcome_id") or "",
                "yes_outcome_id": a.get("yes_outcome_id") or a.get("outcome_id") or "",
                "no_outcome_id": a.get("no_outcome_id") or "",
            },
            "b": {
                "player": b.get("player") or "",
                "price": b.get("pay") or "",
                "yes_ask": b.get("pay") or "",
                "filled": False,
                "instrument": b.get("instrument") or "",
                "venue": b.get("venue") or book.get("venue") or "",
                "intent": b.get("intent") or "",
                "fee_coefficient": b.get("fee_coefficient"),
                "fee_charged": b.get("fee_charged"),
                "event_status": b.get("event_status"),
                "outcome_id": b.get("outcome_id") or "",
                "yes_outcome_id": b.get("yes_outcome_id") or b.get("outcome_id") or "",
                "no_outcome_id": b.get("no_outcome_id") or "",
            },
        },
        "cross_fill": "",
        "cross_fee": "",
        "fav_target": "",
        "last_order": {},
        "last_quotes": _quote_snapshot(players),
        "one_leg_miss": "",
        "note": "",
        "shop": book.get("shop") or {},
        "game_payload": book.get("game_payload") if isinstance(book.get("game_payload"), dict) else {},
    }


def _last_px(ticks) -> Decimal | None:
    if not ticks:
        return None
    return Decimal(str(ticks[-1][1]))


def is_scheduled_sports_clock(dt: datetime | None) -> bool:
    """True for 15:10:00 lists. False for Polymarket feed stamps like 23:12:40Z."""
    if not isinstance(dt, datetime):
        return False
    return dt.second == 0 and dt.microsecond == 0


def live_clock_hides_inplay(pair: dict, start_ts: int) -> bool:
    """True when a listed/occurrence clock sits after the match is already live."""
    if clock_hides_match(pair, start_ts):
        return True
    yes_a = pair.get("yes_a") or []
    yes_b = pair.get("yes_b") or []
    comp = first_competitive_two_sided(yes_a, yes_b)
    if comp is None:
        return False
    _a, _b, comp_ts, _lab = comp
    if comp_ts >= start_ts:
        return False

    def moved(ticks) -> bool:
        return len({p for t, p in ticks if t < start_ts}) >= 2

    return moved(yes_a) and moved(yes_b)


def live_trusted_clock(pair: dict, now: datetime | None = None) -> tuple[datetime | None, str]:
    """Later of occurrence and scheduled listed. Never tape-resume or first-competitive.

    A too-early Kalshi occurrence cannot beat a still-future listed first-serve
    (Parks vs Birrell 00:30 occurrence vs 21:30 listed). When listed is more than
    15 minutes away, wait for it. Near listed, absorb/in-play hide still applies
    (Miyoshi). Delayed occurrence after listed still wins. A live/Poly start that
    moved to a later ET day beats an early listed (Liu vs Colby).
    """
    now = now or now_et()
    occ = pair.get("occ_dt")
    if not isinstance(occ, datetime):
        occ = _parse_start(pair.get("occ_start") or pair.get("occurrence") or "")
    listed = pair.get("listed_dt")
    if not isinstance(listed, datetime):
        listed = _parse_start(pair.get("listed_start") or pair.get("start") or "")
    live = pair.get("live_dt")
    if not isinstance(live, datetime):
        live = _parse_start(pair.get("live_start") or "")
    if live is not None and (
        start_moved_next_et_day(listed, live) or start_moved_next_et_day(occ, live)
    ):
        return live, "live start (next day)"
    actual = _parse_start(pair.get("actual_start") or "")
    src = str(pair.get("actual_source") or "")
    label = str(pair.get("t0_label") or "")
    tape = (
        src in TAPE_RESUME_SOURCES
        or src.startswith("tape resume")
        or "first competitive" in label
    )
    listed_like = src in ("", "listed/feed", "listed") or src.startswith("listed")
    occ_ok = occ is not None and not live_clock_hides_inplay(pair, int(occ.timestamp()))
    listed_ok = False
    listed_hours_away = False
    if listed is not None and is_scheduled_sports_clock(listed):
        ahead = (listed - now).total_seconds()
        listed_hours_away = ahead > 15 * 60
        if listed_hours_away:
            listed_ok = not clock_hides_match(pair, int(listed.timestamp()))
        else:
            listed_ok = not live_clock_hides_inplay(pair, int(listed.timestamp()))
    if listed_ok and occ_ok:
        if occ > listed:
            return occ, "occurrence"
        return listed, "listed/feed"
    if listed_ok:
        return listed, "listed/feed"
    if occ_ok and not listed_hours_away:
        return occ, "occurrence"
    if actual is not None and not tape:
        if listed_like and not is_scheduled_sports_clock(actual):
            return None, ""
        if not live_clock_hides_inplay(pair, int(actual.timestamp())):
            return actual, src or "occurrence"
    return None, ""


def extras_cross_clock_ok(match: dict, now: datetime | None = None) -> tuple[bool, str]:
    """50-cross only after trusted T0. Never hours before first serve."""
    now = now or now_et()
    listed = _parse_start(match.get("listed_start") or match.get("start") or "")
    occ = _parse_start(match.get("occurrence") or "")
    live = _parse_start(match.get("live_start") or "")
    if listed is not None or occ is not None:
        try:
            poly = _poly_event_snapshot(str(match.get("game") or ""))
            refreshed = live_start_from_payloads(poly, match)
            if refreshed is not None:
                live = refreshed
                match["live_start"] = refreshed.isoformat()
        except Exception:
            pass
    clock, src = live_t0_yes.choose_trusted_t0_clock(occ, listed, live)
    if clock is None:
        clock = _parse_start(match.get("t0_when") or "")
        src = str(match.get("t0_clock_source") or "t0_when")
    if clock is None:
        if str(match.get("stage") or "") in CROSS_STAGES and _t0_filled_any(match):
            return True, "t0 already filled"
        return False, "no trusted clock; not sending 50-cross"
    if now < clock - timedelta(seconds=T0_LEAD_SEC):
        if (clock - now).total_seconds() > 15 * 60:
            return False, CROSS_BEFORE_START
        return False, "waiting trusted actual start"
    return True, src or "trusted T0"


def extras_cross_ready(match: dict, ask: Decimal | None) -> tuple[bool, str]:
    """T0-dog Yes through 0.50 from below. Never the T0 favorite. No backfill."""
    if ask is None:
        return False, "no live ask"
    if is_absorbing(ask):
        return False, "absorbing"
    if match.get("extra_stuck"):
        return False, "extra attempt stuck; not sending another cross"
    if bool(match.get("cross_need_reset")):
        if ask <= CROSS:
            match["cross_need_reset"] = False
            return False, "reset; waiting next up-cross"
        return False, "waiting next live ask >0.50 (no backfill)"
    if ask <= CROSS:
        return False, "underdog still <=0.50"
    return True, "live ask >0.50"


def cross_fav_below_dog(
    fav_ask: Decimal | None,
    dog_ask: Decimal | None,
) -> tuple[bool, str]:
    """Send the dog extra only if T0 favorite Yes is strictly below the dog Yes we would pay."""
    if dog_ask is None:
        return False, "no live dog ask"
    if fav_ask is None:
        return False, "no live fav ask"
    if fav_ask >= dog_ask:
        return False, CROSS_FAV_NOT_BELOW
    return True, "fav yes strictly below dog yes"


def cross_allin_c_ok(
    dog_spec: dict | None,
    dog_ask: Decimal | None,
    fav_spec: dict | None,
    fav_ask: Decimal | None,
) -> tuple[bool, str]:
    """Same T0 fee model: all-in C = both Yes asks + documented taker fees <= 1.05."""
    all_in = t0_all_in_from_asks(dog_spec or {}, dog_ask, fav_spec or {}, fav_ask)
    if in_c_band(all_in):
        return True, "ok"
    if all_in is None:
        return False, f"{CROSS_ALLIN_OVER} all-in fee unknown"
    return False, f"{CROSS_ALLIN_OVER} all-in C={_money(all_in)}"


def t0_ready(pair: dict, now: datetime | None = None) -> tuple[bool, str]:
    """True only inside the T0_GRACE window of a trusted actual start."""
    now = now or now_et()
    t0_ts = pair.get("t0_ts")
    t0_a = pair.get("t0_a")
    t0_b = pair.get("t0_b")
    if t0_a is None or t0_b is None or t0_ts is None:
        return False, "no T0 yet"
    spec_a = pair.get("spec_a") if isinstance(pair.get("spec_a"), dict) else None
    spec_b = pair.get("spec_b") if isinstance(pair.get("spec_b"), dict) else None
    venue = str(pair.get("venue") or "")
    if venue.lower() == "multi":
        venue = ""
    ok, why = t0_yes_asks_send_ok(
        Decimal(str(t0_a)),
        Decimal(str(t0_b)),
        venue=venue or None,
        spec_a=spec_a,
        spec_b=spec_b,
    )
    if not ok:
        return False, why
    last_a = _last_px(pair.get("yes_a") or []) or Decimal(str(t0_a))
    last_b = _last_px(pair.get("yes_b") or []) or Decimal(str(t0_b))
    if is_absorbing(last_a) or is_absorbing(last_b):
        return False, "already absorbing"
    clock_dt, src = live_trusted_clock(pair, now)
    if clock_dt is None:
        listed = pair.get("listed_dt")
        if not isinstance(listed, datetime):
            listed = _parse_start(pair.get("listed_start") or pair.get("start") or "")
        if listed is not None and not is_scheduled_sports_clock(listed):
            return False, "no trusted clock; listed/feed is a feed stamp not a scheduled start"
        return False, "no trusted clock; not firing clockless T0 live"
    if now < clock_dt - timedelta(seconds=T0_LEAD_SEC):
        return False, "waiting trusted actual start"
    if (now - clock_dt).total_seconds() > T0_GRACE_SEC:
        return False, "missed T0 window"
    return True, pair.get("t0_label") or src


def _bet_key(match: dict, player: str, step: str) -> str:
    return "\t".join(
        [
            "tennis-b",
            str(match.get("key") or ""),
            str(match.get("game") or ""),
            str(match.get("venue") or ""),
            player,
            step,
        ]
    )


def _player_spec(match: dict, which: str) -> dict:
    row = ((match.get("t0_yes") or {}).get(which) or {})
    yes_id = str(row.get("yes_outcome_id") or row.get("outcome_id") or "")
    no_id = str(row.get("no_outcome_id") or "")
    return {
        "venue": row.get("venue") or match.get("venue") or "",
        "instrument": row.get("instrument") or "",
        "outcome": "yes",
        "pay": row.get("yes_ask") or row.get("price") or "",
        "player": row.get("player") or "",
        "intent": row.get("intent") or "",
        "fee_coefficient": row.get("fee_coefficient"),
        "fee_charged": row.get("fee_charged"),
        "event_status": row.get("event_status"),
        "outcome_id": yes_id,
        "yes_outcome_id": yes_id,
        "no_outcome_id": no_id,
        "fill_qty": row.get("fill_qty") or row.get("confirm_qty") or "",
        "confirm_qty": row.get("confirm_qty") or row.get("fill_qty") or "",
        "qty": row.get("fill_qty") or row.get("confirm_qty") or "",
    }


def _which_player(match: dict, player: str) -> str:
    t0 = match.get("t0_yes") or {}
    if game_norm(str((t0.get("a") or {}).get("player") or "")) == game_norm(player):
        return "a"
    return "b"


def send_t0_both(match: dict, step: str = "t0") -> dict:
    """Recheck both Yes books before either HTTP. If either fails, send neither."""
    specs = [("a", _player_spec(match, "a")), ("b", _player_spec(match, "b"))]
    recs = {}
    for which, spec in specs:
        ask, note = recheck_yes(spec)
        recs[which] = (spec, ask, note)
    stacking = step != "t0"

    def _blank(spec, note, ask=None):
        return {
            "filled": False,
            "posted": False,
            "status": 0,
            "note": note,
            "pay": _money(ask) if ask is not None else (spec.get("pay") or ""),
            "fill_qty": "0",
            "order_id": "",
            "sent_at": iso_now(),
        }

    failed = []
    for which, (spec, ask, note) in recs.items():
        if ask is None:
            failed.append((which, note or "book empty"))
        elif not in_yes_band(ask) or is_absorbing(ask):
            failed.append((which, f"recheck ask={_money(ask)} not in band"))
        else:
            if str(spec.get("venue") or "").lower() == "polymarket":
                skip = live_lock_orders.poly_size_lt_qty_skip(spec)
                if skip:
                    failed.append((which, skip))
            elif stacking:
                size = live_lock_orders._takeable_size(spec)
                if size is None or size < ONE:
                    saw = "missing" if size is None else _money(size)
                    failed.append((which, f"ask size <1 (saw {saw})"))
    if not failed and stacking:
        pa, pb = recs["a"][1], recs["b"][1]
        if pa is None or pb is None:
            failed.append(("c", "recheck ask missing"))
        else:
            est = t0_all_in_from_asks(recs["a"][0], pa, recs["b"][0], pb)
            if est is None:
                failed.append(("c", "all-in fee unknown; not stacking"))
            elif est >= ONE:
                failed.append(("c", f"all-in {_money(est)} >= $1"))
            else:
                funds = _t0_pair_funds_block(recs["a"][0], pa, recs["b"][0], pb)
                if funds:
                    failed.append(("c", funds))
    if failed:
        why = "; ".join(f"{which} {note}" for which, note in failed)
        why = f"T0 send gate: {why}; neither leg sent"
        return {which: _blank(recs[which][0], why, recs[which][1]) for which in ("a", "b")}

    results = {}

    def _one(item):
        which, spec, ask = item
        live = dict(spec)
        live["pay"] = _money(ask)
        out = send_yes_ioc(
            live, ask, f"b-{step}", _bet_key(match, str(spec.get("player") or which), step)
        )
        return which, out

    posts = [(which, recs[which][0], recs[which][1]) for which in ("a", "b")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = [pool.submit(_one, item) for item in posts]
        for fut in as_completed(futs):
            which, out = fut.result()
            results[which] = out
    return results


def maybe_stack_t0(match: dict) -> None:
    """After a confirmed T0 both-Yes, buy another 1-contract pair while all-in < $1.

    MAX_OPEN_B_MATCHES is matches, not contracts. Stacking does not take another slot.
    Stops on ask size <1, named balance deny, REST all-in >= $1, one-leg, or T0_STACK_CAP.
    """
    filled_all_in = t0_fill_all_in(match)
    if not should_stack_t0(filled_all_in):
        match["t0_stack_stop"] = (
            f"all-in {_money(filled_all_in)} >= $1"
            if filled_all_in is not None
            else "all-in unknown; not stacking"
        )
        return
    n = int(match.get("t0_stack_n") or 1)
    while n < T0_STACK_CAP:
        results = send_t0_both(match, step=f"t0-s{n + 1}")
        pa = _dec((results.get("a") or {}).get("pay"))
        pb = _dec((results.get("b") or {}).get("pay"))
        posted = any(bool((results.get(which) or {}).get("posted")) for which in ("a", "b"))
        gate = str((results.get("a") or {}).get("note") or (results.get("b") or {}).get("note") or "")
        tape_t0(match, "send" if posted else "skip", "ok" if posted else (gate or "stack not posted"), pa, pb)
        a_ok = t0_leg_confirmed(results.get("a") or {})
        b_ok = t0_leg_confirmed(results.get("b") or {})
        if a_ok and b_ok:
            n += 1
            match["t0_stack_n"] = n
            stacks = match.setdefault("t0_stacks", [])
            stacks.append(
                {
                    "n": n,
                    "a": _order_snapshot(results.get("a")),
                    "b": _order_snapshot(results.get("b")),
                    "when": iso_now(),
                }
            )
            match["last_order"] = _order_snapshot(results.get("b") or results.get("a"))
            extra_all_in = t0_all_in_from_asks(
                _player_spec(match, "a"),
                _dec((results.get("a") or {}).get("fill_px") or (results.get("a") or {}).get("pay")),
                _player_spec(match, "b"),
                _dec((results.get("b") or {}).get("fill_px") or (results.get("b") or {}).get("pay")),
                (results.get("a") or {}).get("payload"),
                (results.get("b") or {}).get("payload"),
            )
            if extra_all_in is None:
                extra_all_in = t0_fill_all_in(match)
            if not should_stack_t0(extra_all_in):
                match["t0_stack_stop"] = (
                    f"all-in {_money(extra_all_in)} >= $1 after stack {n}"
                    if extra_all_in is not None
                    else f"all-in unknown after stack {n}"
                )
                note = str(match.get("note") or "")
                match["note"] = (note + f" Stacked T0 x{n}; stop {match['t0_stack_stop']}.").strip()
                return
            continue
        if a_ok ^ b_ok:
            filled_which = "a" if a_ok else "b"
            fill_player = str((_player_spec(match, filled_which).get("player") or filled_which))
            flat = flatten_t0_leg(match, filled_which)
            why = (
                f"stack {n + 1} one-leg on {fill_player}; "
                f"flattened extra={'yes' if flat.get('filled') else 'miss'}"
            )
            match["t0_stack_stop"] = why
            note = str(match.get("note") or "")
            match["note"] = (note + " " + why + ". Original T0 both-Yes kept.").strip()
            if not flat.get("filled"):
                _phone_b_note(
                    "Strategy B T0 stack flatten miss",
                    f"game={match.get('game')} extra Yes={fill_player}. "
                    "Original T0 kept. Lock-bot latch left as-is.",
                )
            return
        gate = str((results.get("a") or {}).get("note") or (results.get("b") or {}).get("note") or "miss")
        match["t0_stack_stop"] = gate
        note = str(match.get("note") or "")
        match["note"] = (note + f" T0 stack stop: {gate}").strip()
        return
    match["t0_stack_stop"] = f"cap {T0_STACK_CAP} T0 pairs"
    note = str(match.get("note") or "")
    match["note"] = (note + f" Stacked T0 x{n} (cap {T0_STACK_CAP}).").strip()


def flatten_t0_leg(match: dict, which: str) -> dict:
    """Unwind a one-leg T0 Yes by buying No on the same venue/instrument."""
    spec = dict(_player_spec(match, which))
    spec["_strategy_b"] = True
    spec["_bet_key"] = _bet_key(match, str(spec.get("player") or which), "flatten")
    return live_lock_orders.flatten_filled_leg(
        log,
        spec["_bet_key"],
        str(match.get("game") or ""),
        spec,
    )


def flatten_extra_leg(match: dict, player: str) -> dict:
    """Unwind one extra Yes (cross or leftover extra). Not opponent No."""
    which = _which_player(match, player)
    spec = dict(_player_spec(match, which))
    spec["_strategy_b"] = True
    spec["_bet_key"] = _bet_key(match, player, "extra-flatten")
    return live_lock_orders.flatten_filled_leg(
        log,
        spec["_bet_key"],
        str(match.get("game") or ""),
        spec,
    )


def _t0_yes_quote(row: dict | None, match: dict | None = None) -> Decimal | None:
    """Cash to buy this player's Yes at T0. Never fill_px / BUY_SHORT Yes-wire 1-p."""
    row = row or {}
    fill = _dec(row.get("fill_px"))
    yes_ask = _dec(row.get("yes_ask"))
    if yes_ask is not None:
        return yes_ask
    price = _dec(row.get("price"))
    if price is not None and (fill is None or price != fill):
        return price
    player = str(row.get("player") or "")
    if match is not None and player:
        ask = _dec(((match.get("last_quotes") or {}).get(player) or {}).get("ask"))
        if ask is not None and (fill is None or ask != fill):
            return ask
    return None


def _remember_t0_yes_ask(row: dict, got: dict | None = None) -> None:
    """Freeze the book Yes ask. Fill cash stays on fill_px only."""
    got = got or {}
    fill = _dec(got.get("fill_px") or row.get("fill_px"))
    prior = _dec(row.get("yes_ask") or row.get("price"))
    pay = _dec(got.get("pay"))
    ask = None
    if prior is not None and (fill is None or prior != fill):
        ask = prior
    elif pay is not None and (fill is None or pay != fill):
        ask = pay
    elif prior is not None:
        ask = prior
    if ask is not None:
        row["yes_ask"] = _money(ask)
        row["price"] = _money(ask)


def assign_fav_dog_from_yes_asks(match: dict, *, at_t0_fill: bool = False) -> None:
    """Favorite = higher T0 Yes ask. Dog = lower T0 Yes ask. Frozen at T0, not live lead."""
    t0 = match.get("t0_yes") or {}
    pa = _t0_yes_quote(t0.get("a"), match)
    pb = _t0_yes_quote(t0.get("b"), match)
    if pa is None or pb is None:
        return
    match["c"] = _money(pa + pb)
    if pa >= pb:
        fav_which, dog_which = "a", "b"
        dog_px = pb
    else:
        fav_which, dog_which = "b", "a"
        dog_px = pa
    match["fav_player"] = str((t0.get(fav_which) or {}).get("player") or "")
    match["dog_player"] = str((t0.get(dog_which) or {}).get("player") or "")
    if at_t0_fill:
        match["t0_fav_player"] = match["fav_player"]
        match["t0_dog_player"] = match["dog_player"]
        if dog_px > CROSS and not match.get("cross_fill"):
            match["cross_need_reset"] = True


def _cross_was_on_t0_favorite(match: dict) -> bool:
    """True when the extra 50-cross hit the T0 favorite (Dodig 0.61), not the T0 dog."""
    assign_fav_dog_from_yes_asks(match)
    fav = str(match.get("fav_player") or "")
    dog = str(match.get("dog_player") or "")
    who = str(match.get("cross_player") or "")
    if who and fav and game_norm(who) == game_norm(fav):
        return True
    if who and dog and game_norm(who) == game_norm(dog):
        return False
    fill = _dec(match.get("cross_fill"))
    if fill is None:
        return False
    t0 = match.get("t0_yes") or {}
    fav_ask = _t0_yes_quote(t0.get(_which_player(match, fav)), match) if fav else None
    dog_ask = _t0_yes_quote(t0.get(_which_player(match, dog)), match) if dog else None
    if fav_ask is not None and fav_ask > CROSS and abs(fill - fav_ask) <= Decimal("0.02"):
        if dog_ask is None or dog_ask <= CROSS or abs(fill - dog_ask) > Decimal("0.02"):
            return True
    return False


def _dog_50_cross_filled(match: dict) -> bool:
    if _dec(match.get("cross_fill")) is None:
        return False
    if _cross_was_on_t0_favorite(match):
        return False
    dog = str(match.get("dog_player") or "")
    who = str(match.get("cross_player") or "")
    if who and dog and game_norm(who) != game_norm(dog):
        return False
    return True


def _either_side_absorbing_now(match: dict) -> bool:
    game = str(match.get("game") or "")
    venue = str(match.get("venue") or "")
    for who in (str(match.get("fav_player") or ""), str(match.get("dog_player") or "")):
        if not who:
            continue
        px = latest_yes(game, venue, who)
        if px is not None and is_absorbing(px):
            return True
    return False


def repair_false_favorite_cross(match: dict) -> bool:
    """Unwind extras armed on the T0 favorite. Do not sell. Leave a real 5c/95c absorb."""
    assign_fav_dog_from_yes_asks(match)
    stage = str(match.get("stage") or "")
    if stage not in {
        "waiting_fav_dip",
        "fav_gtc_resting",
        "absorbed",
        "waiting_cross",
        "t0_filled_waiting_50_cross",
    }:
        return False
    if not _cross_was_on_t0_favorite(match):
        return False
    if stage == "absorbed" and _either_side_absorbing_now(match):
        return False
    if _fav_gtc_resting(match):
        cancel_resting_fav_gtc(match, "false favorite cross rewind")
    match["stage"] = "waiting_cross"
    match["cross_fill"] = ""
    match["cross_fee"] = ""
    match["fav_target"] = ""
    match["cross_ioc_sent"] = False
    match["fav_ioc_sent"] = False
    match["fav_gtc_sent"] = False
    match["cross_player"] = ""
    t0 = match.get("t0_yes") or {}
    dog = str(match.get("dog_player") or "")
    dog_px = _t0_yes_quote(t0.get(_which_player(match, dog)), match) if dog else None
    if dog_px is not None and dog_px > CROSS:
        match["cross_need_reset"] = True
    match["note"] = (
        "Repaired false 50-cross on T0 favorite. Waiting T0-dog Yes through 0.50 from below. "
        "Did not sell the extra favorite Yes."
    )
    return True


def mark_t0_results(match: dict, results: dict) -> None:
    t0 = match.setdefault("t0_yes", {})
    filled = []
    missed = []
    last = {}
    quotes = {}
    for which in ("a", "b"):
        row = t0.setdefault(which, {})
        got = results.get(which) or {}
        row["filled"] = bool(got.get("filled"))
        _remember_t0_yes_ask(row, got)
        if got.get("fill_px"):
            row["fill_px"] = got.get("fill_px")
        if got.get("fill_fee"):
            row["fill_fee"] = got.get("fill_fee")
        quotes[str(row.get("player") or which)] = {
            "ask": row.get("yes_ask") or row.get("price") or "",
            "venue": row.get("venue") or match.get("venue") or "",
        }
        last = _order_snapshot(got)
        if got.get("filled"):
            filled.append(which)
        else:
            missed.append(which)
    match["last_order"] = last
    match["last_quotes"] = quotes
    assign_fav_dog_from_yes_asks(match, at_t0_fill=True)
    if len(filled) == 2:
        match["stage"] = "waiting_cross"
        if not match.get("t0_stack_n"):
            match["t0_stack_n"] = 1
        if match.get("cross_need_reset"):
            match["note"] = (
                "T0 both Yes filled; original dog already >0.50 at T0. "
                "Waiting for a down-print then next live up-cross. No immediate extra dog."
            )
        else:
            match["note"] = "T0 both Yes filled; waiting for underdog print > 0.50"
        return
    if len(filled) == 1:
        fill_which = filled[0]
        miss_which = missed[0]
        miss_player = str((t0.get(miss_which) or {}).get("player") or "")
        fill_player = str((t0.get(fill_which) or {}).get("player") or "")
        flat = flatten_t0_leg(match, fill_which)
        if flat.get("filled"):
            match["stage"] = "waiting_t0"
            match["one_leg_miss"] = ""
            row = t0.setdefault(fill_which, {})
            row["filled"] = False
            row["flattened"] = True
            match["note"] = (
                f"T0 one-leg flattened {fill_player} Yes. Not holding directional. "
                "Will retry both-Yes in the T0 window."
            )
            _phone_b_note(
                "Strategy B flattened",
                f"Strategy B T0 flatten filled. game={match.get('game')} flattened Yes={fill_player}. "
                "Lock-bot latch left as-is.",
            )
            return
        match["stage"] = "one_leg_miss"
        match["one_leg_miss"] = miss_player
        match["note"] = (
            f"T0 flatten missed on {fill_player}. Leftover-watch missed Yes {miss_player} only. "
            "Do not buy opponent No (Goffin)."
        )
        _phone_b_note(
            "Strategy B one-leg miss",
            f"Strategy B T0 flatten missed. game={match.get('game')} holding Yes={fill_player} "
            f"watching missed Yes={miss_player} only. Lock-bot latch left as-is.",
        )
        return
    match["note"] = "T0 both Yes missed; will retry in the T0 window"
    match["t0_retries"] = int(match.get("t0_retries") or 0) + 1


def latest_yes(game: str, venue: str, player: str) -> Decimal | None:
    key = (game_norm(game), venue.lower(), game_norm(player), "yes")
    ticks = _series.get(key) or []
    if not ticks:
        return None
    return Decimal(str(ticks[-1][1]))


def remember_live_yes(game: str, venue: str, player: str, price) -> None:
    """Test/helper: append a Yes tick so maybe_cross can see a memory cross."""
    px = as_float(price)
    if px is None:
        return
    key = (game_norm(game), str(venue or "").lower(), game_norm(player), "yes")
    ts = int(now_et().timestamp())
    ticks = _series.setdefault(key, [])
    ticks.append((ts, round(px, 4)))


def open_cross_matches(status: dict | None) -> list[dict]:
    rows = []
    for match in (status or {}).get("matches") or []:
        if not isinstance(match, dict) or match.get("stopped"):
            continue
        if match.get("extra_stuck"):
            continue
        if str(match.get("stage") or "") in CROSS_STAGES or str(match.get("stage") or "") in DIP_STAGES:
            rows.append(match)
    return rows


def t0_arm_budget_sec(status: dict | None) -> float:
    """Seconds allowed to REST-hunt new T0s this tick. Shrinks while a 50-cross is armed."""
    if open_cross_matches(status):
        return float(T0_ARM_BUDGET_WHEN_CROSS_SEC)
    return float(T0_ARM_BUDGET_SEC)


def maybe_cross(match: dict) -> None:
    if match.get("stopped") or match.get("extra_stuck"):
        return
    if str(match.get("stage") or "") == POSTPONED_STAGE:
        return
    assign_fav_dog_from_yes_asks(match)
    if str(match.get("stage") or "") not in CROSS_STAGES:
        return
    clock_ok, clock_why = extras_cross_clock_ok(match)
    if not clock_ok:
        match["note"] = clock_why
        return
    dog = str(match.get("t0_dog_player") or match.get("dog_player") or "")
    fav = str(match.get("t0_fav_player") or match.get("fav_player") or "")
    if not dog:
        return
    if fav and game_norm(dog) == game_norm(fav):
        return
    game = str(match.get("game") or "")
    mem, mem_venue = cheapest_memory_yes(game, dog)
    spec = shop_player_spec(match, dog, mem_venue or None)
    if fav and game_norm(str(spec.get("player") or "")) == game_norm(fav):
        match["note"] = "refusing 50-cross on T0 favorite; waiting T0-dog Yes through 0.50 from below"
        return
    if mem is not None:
        match.setdefault("last_quotes", {})[dog] = {
            "ask": _money(mem),
            "recheck": "memory",
            "venue": mem_venue,
        }
        ready, _why = extras_cross_ready(match, mem)
        if not ready:
            return
    ask, note = recheck_yes(spec, pace=False)
    match.setdefault("last_quotes", {})[dog] = {
        "ask": _money(ask) if ask is not None else "",
        "recheck": note,
        "venue": spec.get("venue") or mem_venue,
    }
    if ask is not None and is_absorbing(ask):
        match["stage"] = "absorbed"
        match["note"] = "absorbed before 50c cross; holding T0 both-Yes"
        return
    ready, why = extras_cross_ready(match, ask)
    if not ready:
        return
    fav_mem, fav_mem_venue = cheapest_memory_yes(game, fav) if fav else (None, "")
    fav_spec = shop_player_spec(match, fav, fav_mem_venue or None) if fav else {}
    fav_ask, fav_note = recheck_yes(fav_spec, pace=False) if fav else (None, "no T0 favorite")
    if fav:
        match.setdefault("last_quotes", {})[fav] = {
            "ask": _money(fav_ask) if fav_ask is not None else "",
            "recheck": fav_note,
        }
    ok, gate_why = cross_fav_below_dog(fav_ask, ask)
    all_in = t0_all_in_from_asks(spec, ask, fav_spec, fav_ask)
    if not ok:
        pair_key = f"{_money(ask)}/{_money(fav_ask)}"
        match["note"] = (
            f"{gate_why}; dog yes {_money(ask)} fav yes {_money(fav_ask)}; not sending extra"
        )
        match["cross_fav_skip"] = pair_key
        if str(match.get("cross_fav_logged") or "") != pair_key:
            match["cross_fav_logged"] = pair_key
            log(
                f"{match.get('game') or ''} {CROSS_FAV_NOT_BELOW} "
                f"dog={_money(ask)} fav={_money(fav_ask)}"
            )
            tape_cross(match, "skip", gate_why, dog, fav, ask, fav_ask, all_in)
        return
    ok_c, c_why = cross_allin_c_ok(spec, ask, fav_spec, fav_ask)
    if not ok_c:
        pair_key = f"{_money(ask)}/{_money(fav_ask)}"
        match["note"] = (
            f"{c_why}; dog yes {_money(ask)} fav yes {_money(fav_ask)}; not sending extra"
        )
        match["cross_allin_skip"] = pair_key
        if str(match.get("cross_allin_logged") or "") != pair_key:
            match["cross_allin_logged"] = pair_key
            log(
                f"{match.get('game') or ''} {CROSS_ALLIN_OVER} "
                f"dog={_money(ask)} fav={_money(fav_ask)}"
            )
            tape_cross(match, "skip", c_why, dog, fav, ask, fav_ask, all_in)
        return
    tape_cross(match, "send", "ok", dog, fav, ask, fav_ask, all_in)
    result = send_yes_ioc(spec, ask, "b-cross", _bet_key(match, dog, "cross"))
    match["last_order"] = _order_snapshot(result)
    qty = _ticket_qty(result)
    if qty >= SIZE:
        fill = _dec(result.get("fill_px") or result.get("pay"))
        match["cross_fill"] = _money(fill)
        match["cross_fee"] = result.get("fill_fee") or ""
        match["cross_ioc_sent"] = True
        match["cross_player"] = dog
        if fill is None:
            match["note"] = "cross filled but fill price unknown; not sending fav dip"
            match["stage"] = "waiting_fav_dip"
            return
        match["fav_target"] = _money(fav_target(fill))
        match["stage"] = "waiting_fav_dip"
        match["note"] = f"cross filled at {_money(fill)}; waiting fav Yes at/below {match['fav_target']}"
        return
    match["cross_need_reset"] = True
    match["cross_ioc_sent"] = False
    if qty > 0:
        if str(spec.get("venue") or "").lower() == "polymarket":
            match["extra_stuck"] = True
            match["note"] = (
                f"50c cross Poly partial {_money(qty)}; not flattening as 1. "
                "No leftover-retry. Not a house 1-contract fill."
            )
            return
        flat = flatten_extra_leg(match, dog)
        if flat.get("filled"):
            match["note"] = (
                f"50c cross partial {_money(qty)} at {_money(ask)}; extra flattened. "
                "Waiting next up-cross >0.50. No leftover-retry."
            )
            return
        match["extra_stuck"] = True
        match["note"] = (
            f"50c cross partial {_money(qty)}; flatten missed. No leftover-retry. "
            "Holding T0 + extra dog Yes. Not opponent No."
        )
        return
    match["note"] = (
        f"50c cross IOC miss at {_money(ask)}; extra attempt flattened (nothing filled). "
        "Waiting next live up-cross >0.50. No leftover-retry."
    )


def maybe_fav_dip(match: dict) -> None:
    if match.get("stopped") or match.get("extra_stuck"):
        return
    assign_fav_dog_from_yes_asks(match)
    if str(match.get("stage") or "") not in DIP_STAGES:
        return
    if not _dog_50_cross_filled(match):
        repair_false_favorite_cross(match)
        return
    fav = str(match.get("fav_player") or "")
    dog = str(match.get("dog_player") or "")
    fill = _dec(match.get("cross_fill"))
    if not fav or fill is None:
        return
    target = fav_target(fill)
    match["fav_target"] = _money(target)
    _fav_mem, fav_mem_venue = cheapest_memory_yes(str(match.get("game") or ""), fav)
    spec = shop_player_spec(match, fav, fav_mem_venue or None)
    ask, note = recheck_yes(spec, pace=False)
    match.setdefault("last_quotes", {})[fav] = {
        "ask": _money(ask) if ask is not None else "",
        "recheck": note,
    }
    if ask is not None and is_absorbing(ask):
        cancel_resting_fav_gtc(match, "absorb")
        match["stage"] = "absorbed"
        match["note"] = "absorbed after cross; extra dog Yes held, no fav dip"
        return
    if _fav_gtc_resting(match):
        if poll_fav_gtc_fill(match):
            return
        return
    if match.get("fav_ioc_sent"):
        return
    if ask is None:
        return
    cross_fee = _dec(match.get("cross_fee")) or Decimal("0")
    if ask <= target:
        if not extra_pair_net_ok(fill, cross_fee, ask, spec):
            match["note"] = (
                f"fav ask {_money(ask)} plus fees would exceed 1-0.25 on the extra pair; not sent"
            )
            tape_fav_dip(match, "skip", match["note"], ask, "ioc")
            return
        result = send_yes_ioc(spec, ask, "b-fav", _bet_key(match, fav, "fav"))
        match["last_order"] = _order_snapshot(result)
        qty = _ticket_qty(result)
        if qty >= SIZE:
            _apply_fav_fill(match, result, spec)
            return
        match["fav_ioc_sent"] = True
        match["cross_need_reset"] = True
        match["cross_ioc_sent"] = False
        match["cross_fill"] = ""
        match["fav_target"] = ""
        flat = flatten_extra_leg(match, dog) if dog else {"filled": False}
        if flat.get("filled"):
            match["stage"] = "waiting_cross"
            match["note"] = (
                f"fav dip IOC miss at {_money(ask)}; extra dog Yes flattened. "
                "Holding T0 both-Yes. Waiting next up-cross. No leftover-retry."
            )
            return
        match["extra_stuck"] = True
        match["stage"] = "waiting_cross"
        match["note"] = (
            f"fav dip IOC miss at {_money(ask)}; extra flatten missed. No leftover-retry. "
            "Holding T0 + extra dog Yes. Not opponent No."
        )
        return
    venue = str(spec.get("venue") or match.get("venue") or "").strip().lower()
    tif_field = venue_gtc_tif(venue)
    if tif_field is None:
        why = f"gtc_unsupported venue={venue or 'blank'}; not IOC-looping fav dip"
        match["note"] = why
        match["fav_ioc_sent"] = True
        tape_fav_dip(match, "skip", why, target, "")
        return
    if not extra_pair_net_ok(fill, cross_fee, target, spec):
        why = (
            f"GTC at {_money(target)} plus fees would exceed 1-0.25 on the extra pair; not rested"
        )
        match["note"] = why
        tape_fav_dip(match, "skip", why, target, tif_field[1])
        return
    result = send_yes_gtc(spec, target, "b-fav", _bet_key(match, fav, "fav"))
    match["last_order"] = _order_snapshot(result)
    qty = _ticket_qty(result)
    if qty >= SIZE:
        _apply_fav_fill(match, result, spec)
        tape_fav_dip(match, "fill", "gtc filled immediately", _dec(result.get("fill_px") or result.get("pay")), str(result.get("tif") or "gtc"))
        return
    still_open = bool(result.get("resting")) or live_lock_orders.order_still_open(result.get("payload"))
    if result.get("posted") and result.get("order_id") and still_open:
        _remember_fav_gtc(match, spec, result)
        match["fav_gtc_sent"] = True
        match["fav_ioc_sent"] = True
        match["stage"] = "fav_gtc_resting"
        match["note"] = (
            f"cross filled at {_money(fill)}; fav GTC resting at {match['fav_target']} "
            f"tif={result.get('tif') or tif_field[1]}"
        )
        tape_fav_dip(match, "rest", match["note"], target, str(result.get("tif") or tif_field[1]))
        return
    why = str(result.get("note") or "fav GTC not posted")
    match["note"] = f"fav GTC not rested: {why}"
    if result.get("posted"):
        match["fav_ioc_sent"] = True
    tape_fav_dip(match, "skip", match["note"], target, str(result.get("tif") or tif_field[1]))


def maybe_one_leg_yes(match: dict) -> None:
    """Leftover-watch ONLY the missed player's Yes. Never opponent No."""
    if str(match.get("stage") or "") != "one_leg_miss":
        return
    missed = str(match.get("one_leg_miss") or "")
    if not missed:
        return
    if match.get("leftover_ioc_sent"):
        px = latest_yes(str(match.get("game") or ""), str(match.get("venue") or ""), missed)
        match.setdefault("last_quotes", {})[missed] = {"ask": _money(px) if px is not None else ""}
        return
    spec = _player_spec(match, _which_player(match, missed))
    ask, note = recheck_yes(spec)
    match.setdefault("last_quotes", {})[missed] = {
        "ask": _money(ask) if ask is not None else "",
        "recheck": note,
    }
    if ask is None or not in_yes_band(ask) or is_absorbing(ask):
        if ask is not None and is_absorbing(ask):
            match["stage"] = "abandoned"
            match["note"] = f"missed Yes {missed} absorbed; leftover-watch stopped. Latch untouched."
        return
    result = send_yes_ioc(spec, ask, "b-leftover-yes", _bet_key(match, missed, "leftover-yes"))
    match["last_order"] = _order_snapshot(result)
    if result.get("posted"):
        match["leftover_ioc_sent"] = True
    qty = _ticket_qty(result)
    which = _which_player(match, missed)
    row = (match.get("t0_yes") or {}).setdefault(which, {})
    if qty > 0:
        row["fill_qty"] = _money(qty)
        row["fill_px"] = result.get("fill_px") or result.get("pay") or row.get("fill_px") or ""
        row["fill_fee"] = result.get("fill_fee") or row.get("fill_fee") or ""
    if qty >= SIZE:
        row["filled"] = True
        match["one_leg_miss"] = ""
        match["stage"] = "waiting_cross"
        match["note"] = "leftover Yes filled; T0 both complete. Lock-bot latch left as-is."
        return
    if qty > 0:
        match["note"] = (
            f"leftover Yes {missed} partial fill {_money(qty)}; extra attempt done, not retrying"
        )
        return
    if result.get("posted"):
        match["note"] = f"leftover Yes {missed} IOC miss; extra attempt done, not retrying"


def _stage_label(stage: str, match: dict | None = None) -> str:
    match = match or {}
    names = {
        "waiting_t0": "waiting T0",
        "t0_filled_waiting_50_cross": "T0 filled waiting 50-cross",
        "waiting_cross": "waiting 50-cross (extras)",
        "waiting_fav_dip": f"waiting fav dip at target {match.get('fav_target') or 'X'}",
        "fav_gtc_resting": f"fav GTC resting at {match.get('fav_target') or 'X'}",
        "done": "done",
        "one_leg_miss": "one-leg miss",
        "absorbed": "absorbed",
        "abandoned": "abandoned",
        POSTPONED_STAGE: "postponed",
        "queued": "queued",
    }
    return names.get(stage, stage)


def maybe_absorb(match: dict) -> None:
    assign_fav_dog_from_yes_asks(match)
    game = str(match.get("game") or "")
    venue = str(match.get("venue") or "")
    for who in (str(match.get("fav_player") or ""), str(match.get("dog_player") or "")):
        if not who:
            continue
        px = latest_yes(game, venue, who)
        if px is not None and is_absorbing(px):
            if match.get("stage") in {"t0_filled_waiting_50_cross", "waiting_cross"}:
                match["stage"] = "absorbed"
                match["note"] = "absorbed; holding T0 both-Yes (locked ~vig loss). No extras."
            elif match.get("stage") in DIP_STAGES:
                if not _dog_50_cross_filled(match):
                    repair_false_favorite_cross(match)
                    return
                cancel_resting_fav_gtc(match, "absorb")
                match["stage"] = "absorbed"
                match["note"] = "absorbed after cross; no fav dip"


def _note_b_stage(match: dict | None, prev: str) -> None:
    """Queue the performance page when this match just completed / postponed / left the books."""
    try:
        import orders_performance_refresh
        orders_performance_refresh.maybe_after_b_stage(
            match, prev, str((match or {}).get("stage") or ""),
        )
    except Exception:
        pass


def note_settled_holds(status: dict, snapshot=None) -> int:
    """Mark filled B holds settled when the venue is final. Does not sell.

    Absorbed / waiting_cross / leftover still realize P&L when the match
    settles. Empty Polymarket positions GET while OPEN keeps the hold.
    """
    if not isinstance(status, dict):
        return 0
    try:
        import open_count_sync
        import orders_performance_refresh
    except Exception:
        return 0
    snap = snapshot
    if snap is None:
        try:
            snap = open_count_sync.venue_snapshot()
        except Exception:
            return 0
    n = 0
    hold_stages = set(OPEN_STAGES) | {"absorbed"}
    for match in status.get("matches") or []:
        if not isinstance(match, dict):
            continue
        stage = str(match.get("stage") or "")
        if stage not in hold_stages:
            continue
        if not orders_performance_refresh.b_match_touched(match):
            continue
        try:
            item = open_count_sync.classify_match("tennis_crossover", match, snap)
        except Exception:
            continue
        if not orders_performance_refresh.classified_is_venue_close(item, snapshot=snap):
            continue
        prev = stage
        cancel_resting_fav_gtc(match, "venue settled")
        match["stage"] = "done"
        match["note"] = str(item.get("why") or "venue settled/expired/final/void")
        _note_b_stage(match, prev)
        n += 1
    return n


def process_open(match: dict) -> None:
    if match.get("stopped"):
        return
    if str(match.get("stage") or "") == POSTPONED_STAGE:
        return
    repair_false_favorite_cross(match)
    assign_fav_dog_from_yes_asks(match)
    if str(match.get("stage") or "") not in OPEN_STAGES:
        return
    stage = str(match.get("stage") or "")
    maybe_absorb(match)
    stage = str(match.get("stage") or "")
    if stage == "waiting_t0":
        return
    if stage == "one_leg_miss":
        maybe_one_leg_yes(match)
        return
    if stage in {"t0_filled_waiting_50_cross", "waiting_cross"}:
        maybe_cross(match)
        if str(match.get("stage") or "") in DIP_STAGES:
            maybe_fav_dip(match)
        return
    if stage in DIP_STAGES:
        maybe_fav_dip(match)


def _prepare_book(scan, spec: dict) -> tuple[dict | None, dict | None, str]:
    title = str(spec.get("title") or "")
    # Every sendable shop that has a ticker. Do not REST-only the memory
    # winner — cheapest Yes is per player across Kalshi/Poly/Gemini/Novig.
    books = moneyline_yes_books(scan, spec)
    shop = _shop_from_books(books)
    ranked = rank_cheapest_legs(books)
    if ranked is None:
        return None, None, "no both-Yes book"
    players = ranked.get("players") or []
    if len(players) != 2:
        return None, None, "no both-Yes book"
    pa = _dec(players[0].get("pay"))
    pb = _dec(players[1].get("pay"))
    spec_a = dict(players[0])
    spec_b = dict(players[1])
    ok, why = t0_yes_asks_send_ok(pa, pb, spec_a=spec_a, spec_b=spec_b)
    if not ok:
        return None, None, why
    book = ranked
    book["shop"] = shop
    game_payload = spec.get("game") if isinstance(spec.get("game"), dict) else {}
    book["game_payload"] = game_payload
    players = book["players"]
    spec_a = dict(players[0]) if isinstance(players[0], dict) else {}
    spec_b = dict(players[1]) if len(players) > 1 and isinstance(players[1], dict) else {}
    spec_a.setdefault("venue", players[0].get("venue") if isinstance(players[0], dict) else "")
    if spec_b:
        spec_b.setdefault("venue", players[1].get("venue") if isinstance(players[1], dict) else "")
    listed = _parse_start(spec.get("listed_start") or spec.get("start") or "")
    occ = book.get("occurrence")
    if not isinstance(occ, datetime):
        occ = _parse_start(occ)
    pair = None
    for venue in (
        str(players[0].get("venue") or ""),
        str(players[1].get("venue") or ""),
        str(book.get("venue") or ""),
    ):
        if not venue or venue == "multi":
            continue
        pair = pair_from_ticks(title, venue, players[0]["player"], players[1]["player"])
        if pair is not None:
            break
    if pair is None:
        pair = {
            "game": title,
            "venue": book.get("venue") or "",
            "side_a": players[0]["player"],
            "side_b": players[1]["player"],
            "yes_a": [],
            "yes_b": [],
            "no_a": [],
            "no_b": [],
            "start": spec.get("listed_start") or spec.get("start") or "",
            "start_dt": listed,
        }
        now_ts = int(now_et().timestamp())
        pa = as_float(players[0].get("pay"))
        pb = as_float(players[1].get("pay"))
        if pa is not None:
            pair["yes_a"] = [(now_ts, pa)]
        if pb is not None:
            pair["yes_b"] = [(now_ts, pb)]
    assign_live_t0(pair, listed, occ)
    try:
        poly = _poly_event_snapshot(title)
        live = live_start_from_payloads(poly, game_payload, spec)
        if live is not None:
            pair["live_start"] = live.isoformat()
            pair["live_dt"] = live
    except Exception:
        pass
    pair["spec_a"] = spec_a
    pair["spec_b"] = spec_b
    return book, pair, ""


def fire_t0(match: dict) -> None:
    """Recheck both Yes asks, then IOC both. Occupies the open slot from this send."""
    if str(match.get("stage") or "") == POSTPONED_STAGE:
        return
    t0 = match.get("t0_yes") or {}
    for which in ("a", "b"):
        spec = _player_spec(match, which)
        ask, note = recheck_yes(spec)
        snap = t0.setdefault(which, {})
        snap["recheck"] = note
        if ask is not None:
            snap["price"] = _money(ask)
            snap["yes_ask"] = _money(ask)
    pa = _dec((t0.get("a") or {}).get("price"))
    pb = _dec((t0.get("b") or {}).get("price"))
    match["last_quotes"] = _quote_snapshot(
        [
            {"player": (t0.get("a") or {}).get("player"), "venue": match.get("venue"), "pay": (t0.get("a") or {}).get("price"), "instrument": (t0.get("a") or {}).get("instrument")},
            {"player": (t0.get("b") or {}).get("player"), "venue": match.get("venue"), "pay": (t0.get("b") or {}).get("price"), "instrument": (t0.get("b") or {}).get("instrument")},
        ]
    )
    ok, why = t0_yes_asks_send_ok(
        pa,
        pb,
        venue=match.get("venue"),
        spec_a=_player_spec(match, "a"),
        spec_b=_player_spec(match, "b"),
    )
    if not ok:
        tape_t0(match, "skip", why, pa, pb)
        if T0_C_OVER_SKIP in why:
            mark_t0_c_over(match, why)
            return
        match["note"] = "recheck C/Yes band failed; still waiting T0"
        return
    if is_absorbing(pa) or is_absorbing(pb):
        tape_t0(match, "skip", "absorbed on T0 recheck; not sent", pa, pb)
        match["stage"] = "abandoned"
        match["note"] = "absorbed on T0 recheck; not sent"
        return
    results = send_t0_both(match)
    posted = any(bool((results.get(which) or {}).get("posted")) for which in ("a", "b"))
    note = "ok" if posted else str(
        (results.get("a") or {}).get("note")
        or (results.get("b") or {}).get("note")
        or "T0 not posted"
    )
    tape_t0(match, "send" if posted else "skip", note, pa, pb)
    mark_t0_results(match, results)
    if str(match.get("stage") or "") in CROSS_STAGES or str(match.get("stage") or "") == "waiting_cross":
        maybe_stack_t0(match)
    if match.get("stage") == "waiting_t0" and int(match.get("t0_retries") or 0) >= 3:
        match["stage"] = "abandoned"
        match["note"] = "T0 both Yes missed three times; abandoned. Latch untouched."


def try_t0(scan, spec: dict, status: dict) -> str:
    title = str(spec.get("title") or "")
    if lock_bot_holds_game(title):
        return "lock-bot leftover or unmatched one-leg"
    existing = next(
        (row for row in (status.get("matches") or []) if same_game(str(row.get("game") or ""), title)),
        None,
    )
    if existing is not None:
        postponed = live_postponed_reason(existing, spec, scan)
        if postponed and str(existing.get("stage") or "") not in {"done", "absorbed"}:
            mark_postponed(existing, postponed)
            return POSTPONED_STAGE
        if existing.get("stopped"):
            return "already handled"
        if str(existing.get("stage") or "") not in OPEN_STAGES:
            return "already handled"
        if str(existing.get("stage") or "") == "waiting_t0":
            book, pair, err = _prepare_book(scan, spec)
            if err:
                existing["note"] = err
                if T0_C_OVER_SKIP in err:
                    tape_t0(existing, "skip", err)
                return err
            ready, why = t0_ready(pair or {})
            existing["t0_label"] = (pair or {}).get("t0_label") or why
            clock_dt, clock_src = live_trusted_clock(pair or {})
            existing["t0_when"] = (
                clock_dt.isoformat() if clock_dt is not None else ((pair or {}).get("actual_start") or "")
            )
            existing["t0_clock_source"] = clock_src or (pair or {}).get("actual_source") or ""
            if not ready:
                if T0_C_OVER_SKIP in why:
                    mark_t0_c_over(existing, why)
                    return T0_C_OVER_SKIP
                existing["note"] = why
                release_untrusted_waiting_t0(existing, why)
                return str(existing.get("stage") or why)
            fire_t0(existing)
            if str(existing.get("skip_reason") or "") == T0_C_OVER_SKIP:
                return T0_C_OVER_SKIP
            return str(existing.get("stage") or "waiting_t0")
        return "already open"
    book, pair, err = _prepare_book(scan, spec)
    if err:
        if T0_C_OVER_SKIP in err:
            tape_t0({"game": title, "venue": str((pair or {}).get("venue") or spec.get("venue") or "")}, "skip", err)
        return err
    ready, why = t0_ready(pair or {})
    if T0_C_OVER_SKIP in (why or ""):
        tape_t0(
            {
                "game": title,
                "venue": str((pair or {}).get("venue") or ""),
                "t0_yes": {
                    "a": {
                        "player": (pair or {}).get("side_a") or "a",
                        "yes_ask": (pair or {}).get("t0_a"),
                        "venue": (pair or {}).get("venue"),
                    },
                    "b": {
                        "player": (pair or {}).get("side_b") or "b",
                        "yes_ask": (pair or {}).get("t0_b"),
                        "venue": (pair or {}).get("venue"),
                    },
                },
            },
            "skip",
            why,
            _dec((pair or {}).get("t0_a")),
            _dec((pair or {}).get("t0_b")),
        )
        return why
    clock_dt, _src = live_trusted_clock(pair or {})
    near = (
        clock_dt is not None
        and timedelta(seconds=-60) <= (clock_dt - now_et()) <= timedelta(minutes=15)
    )
    if not ready and not near:
        return why
    postponed = live_postponed_reason({}, spec, scan)
    if postponed:
        return POSTPONED_STAGE
    _on, max_open = live_b_caps()
    if len(open_matches(status)) >= max_open:
        return "queued"
    match = _match_row(spec, book or {}, "waiting_t0")
    match["t0_label"] = (pair or {}).get("t0_label") or why
    clock_dt, clock_src = live_trusted_clock(pair or {})
    match["t0_when"] = (
        clock_dt.isoformat() if clock_dt is not None else ((pair or {}).get("actual_start") or "")
    )
    match["t0_clock_source"] = clock_src or (pair or {}).get("actual_source") or ""
    match["note"] = why if not ready else "T0 window; sending both Yes"
    status.setdefault("matches", []).append(match)
    if ready:
        fire_t0(match)
        if str(match.get("skip_reason") or "") == T0_C_OVER_SKIP:
            return T0_C_OVER_SKIP
    elif release_untrusted_waiting_t0(match, why):
        return str(match.get("stage") or why)
    return str(match.get("stage") or "waiting_t0")


def _slate_spec(slate: list[dict], match: dict) -> dict | None:
    key = str(match.get("key") or "")
    game = str(match.get("game") or "")
    hit = next((row for row in slate if str(row.get("key") or "") == key), None)
    if hit is not None:
        return hit
    return next(
        (row for row in slate if same_game(str(row.get("title") or ""), game)),
        None,
    )


def _process_hot_opens(status: dict) -> int:
    """50-cross / fav-dip / leftover only. No postponed REST. No T0-slate hunt."""
    n = 0
    for match in list(status.get("matches") or []):
        if not isinstance(match, dict) or match.get("stopped"):
            continue
        prev = str(match.get("stage") or "")
        if prev not in CROSS_STAGES and prev not in DIP_STAGES and prev not in {"one_leg_miss"}:
            continue
        try:
            process_open(match)
        except Exception as exc:
            log(f"b open tick {match.get('game')} {type(exc).__name__}")
            match["note"] = f"tick error {type(exc).__name__}"
        n += 1
        _note_b_stage(match, prev)
    return n


def tick_cross_only(status: dict | None = None) -> dict:
    """Pump memory and fire a 50-cross now. Does not walk the T0 slate."""
    status = status if isinstance(status, dict) else load_status()
    on, max_open = live_b_caps()
    status["enabled"] = bool(on)
    status["max_open_b_matches"] = int(max_open)
    status["pid"] = os.getpid()
    if not on:
        return status
    _pump_ticks()
    _merge_price_last()
    before = [(id(row), str(row.get("stage") or ""), row.get("cross_ioc_sent")) for row in (status.get("matches") or [])]
    _process_hot_opens(status)
    after = [(id(row), str(row.get("stage") or ""), row.get("cross_ioc_sent")) for row in (status.get("matches") or [])]
    if before != after:
        save_status(status)
    return status


def _arm_new_matches(scan, slate: list[dict], status: dict, max_open: int) -> None:
    """REST-hunt T0s with a time budget. Re-check 50-cross watches after each probe."""
    if len(open_matches(status)) >= max_open:
        return
    budget = t0_arm_budget_sec(status)
    deadline = time.monotonic() + max(0.0, float(budget))
    ranked = []
    for spec in slate:
        start = _parse_start(spec.get("listed_start") or spec.get("start") or "")
        ranked.append((start or now_et() + timedelta(days=9), spec))
    ranked.sort(key=lambda item: item[0])
    for _start, spec in ranked:
        if time.monotonic() >= deadline:
            break
        title = str(spec.get("title") or "")
        if any(same_game(str(row.get("game") or ""), title) for row in (status.get("matches") or [])):
            continue
        why = try_t0(scan, spec, status)
        _pump_ticks()
        _merge_price_last()
        _process_hot_opens(status)
        if why == "queued":
            q = {
                "game": title,
                "key": spec.get("key") or "",
                "listed_start": spec.get("listed_start") or spec.get("start") or "",
                "reason": "max_open_b_matches=1",
                "when": iso_now(),
            }
            queued = [row for row in (status.get("queued") or []) if not same_game(str(row.get("game") or ""), title)]
            queued.append(q)
            status["queued"] = queued[-QUEUE_KEEP:]
            break
        if why in OPEN_STAGES or why in DONE_STAGES:
            break
        if why not in {
            "no T0 yet",
            "waiting trusted actual start",
            "no both-Yes book",
            "no same-venue both-Yes in C band",
            "already open",
        }:
            skipped = [row for row in (status.get("skipped") or []) if not same_game(str(row.get("game") or ""), title)]
            skipped.append({"game": title, "reason": why, "when": iso_now()})
            status["skipped"] = skipped[-SKIP_KEEP:]
        if time.monotonic() >= deadline:
            break


def tick() -> dict:
    status = load_status()
    on, max_open = live_b_caps()
    status["enabled"] = bool(on)
    status["max_open_b_matches"] = int(max_open)
    status["display_name"] = "Tennis crossover"
    status["watch_cadence"] = WATCH_CADENCE
    status["t0_rule"] = empty_status()["t0_rule"]
    status["t0_c_rule"] = empty_status()["t0_c_rule"]
    status["novig_orders"] = empty_status()["novig_orders"]
    status["pid"] = os.getpid()
    if not on:
        status["note"] = "Tennis crossover is off"
        save_status(status)
        return status
    _pump_ticks()
    _merge_price_last()
    _process_hot_opens(status)
    scan = _scan_mod()
    slate = tennis_slate()
    status.update(cluster_counts(slate))
    for match in list(status.get("matches") or []):
        prev_stage = str(match.get("stage") or "")
        stage = prev_stage
        if stage == POSTPONED_STAGE:
            continue
        spec = None
        if stage in OPEN_STAGES:
            spec = _slate_spec(slate, match)
            postponed = live_postponed_reason(match, spec or {}, scan)
            if postponed:
                mark_postponed(match, postponed)
                _note_b_stage(match, prev_stage)
                continue
        if match.get("stopped"):
            continue
        if stage == "absorbed":
            repair_false_favorite_cross(match)
            stage = str(match.get("stage") or "")
        if stage not in OPEN_STAGES:
            continue
        if str(match.get("stage") or "") == "waiting_t0":
            if spec is None:
                match["stage"] = "abandoned"
                match["note"] = "match left the live tennis slate before T0 send"
                _note_b_stage(match, prev_stage)
                continue
            try_t0(scan, spec, status)
            _note_b_stage(match, prev_stage)
            continue
        if stage in CROSS_STAGES or stage in DIP_STAGES or stage in {"one_leg_miss"}:
            continue
        try:
            process_open(match)
        except Exception as exc:
            log(f"b open tick {match.get('game')} {type(exc).__name__}")
            match["note"] = f"tick error {type(exc).__name__}"
        _note_b_stage(match, prev_stage)
    _arm_new_matches(scan, slate, status, max_open)
    if not open_cross_matches(status):
        try:
            note_settled_holds(status)
        except Exception as exc:
            log(f"b settle note {type(exc).__name__}")
    save_status(status)
    return status


def loop() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    _json_dump(PID_FILE, {"pid": os.getpid(), "started_at": iso_now(), "deadline": job_deadline_iso()})
    log(
        f"strategy b start pid {os.getpid()} D={_money(D)} allin_C_HI={_money(C_HI)} "
        f"skip={T0_C_OVER_SKIP} cross_skip={CROSS_ALLIN_OVER} "
        f"max_open={MAX_OPEN_B_MATCHES} deadline {job_deadline_iso()}"
    )
    status = None
    while keep_running():
        try:
            status = tick()
        except KeyboardInterrupt:
            log("strategy b interrupted; continuing")
        except Exception as exc:
            log(f"strategy b loop {type(exc).__name__}")
        deadline = time.monotonic() + TICK_SEC
        while keep_running() and time.monotonic() < deadline:
            watching = open_cross_matches(status if isinstance(status, dict) else {})
            if not watching:
                left = deadline - time.monotonic()
                if left > 0:
                    time.sleep(min(1.0, left))
                break
            time.sleep(CROSS_IDLE_SEC)
            try:
                status = tick_cross_only(status if isinstance(status, dict) else None)
            except KeyboardInterrupt:
                log("strategy b interrupted; continuing")
            except Exception as exc:
                log(f"strategy b cross tick {type(exc).__name__}")
    log("strategy b exit")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--tick"]:
        snap = tick()
        print(json.dumps({"open": snap.get("currently_open"), "updated_at": snap.get("updated_at")}, default=str))
        return 0
    if argv[:1] == ["--status"]:
        print(json.dumps(load_status(), indent=2, default=str))
        return 0
    loop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
