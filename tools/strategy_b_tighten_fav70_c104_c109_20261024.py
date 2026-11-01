"""Strategy B vs T0 fav<70 and C 1.04/1.09. Research compare only.

Does not place, cancel, or amend orders. Does not print secrets.
Does not start live_strategy_b.py. Does not change live C_HI=1.20 or D=0.25.
Does not sell tickets. Does not wire GTC. Not gold. Not DailyRun.
"""
from __future__ import annotations

import html as html_mod
import json
import math
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import report_page_extras
from compare_format import (
    DEFAULT_INITIAL_ACCOUNT,
    format_money,
    format_money_delta,
    overlay_ann_ror_max_dd,
)
from odds_cross_winrate_20261020 import build_index, game_norm, parse_dt, tiny_note
from prediction_paths import RAW_DIR as RAW
from price_memory import to_et
from t0_all_games_stats import (
    first_absorbing,
    load_settlement_rows,
    pair_books,
    pick_trusted_clock,
    assign_t0_prices,
    settle_book,
    start_lookup_from_settlements,
    stream_yes_sides,
)
from write_t0_band_from_stay_above import all_in_c, documented_leg_fee

ET = ZoneInfo("America/New_York")
STAMP = (
    ROOT
    / "drive"
    / "paul_experiments"
    / "prediction_market_arb_exhaustive_20261017"
    / "strategy_b_tighten_fav70_c104_c109_20261024"
)
PAGE = STAMP / "compare.html"
BASELINE = STAMP / "BASELINE.md"
AB_PLAN = STAMP / "AB_PLAN.md"
ARMS_JSON = STAMP / "arms.json"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/strategy_b_tighten_fav70_c104_c109_20261024/"
    "compare.html"
)

YES_LO = 0.10
YES_HI = 0.90
C_HI_LIVE = 1.20
FAV_LT = 0.70
C_104 = 1.04
C_109 = 1.09
CROSS = 0.50
D = 0.25
ABSORB = 0.05
IS_CUT = "2024-01-01"
VENUE_RANK = {"kalshi": 0, "gemini": 1, "polymarket": 2, "novig": 3}
SPORT_HEADINGS = (
    ("all", "All sports"),
    ("tennis", "Tennis"),
    ("college football", "College football"),
    ("pro football", "Pro football"),
    ("pro hockey", "Hockey (pro hockey on tape)"),
    ("soccer", "Soccer"),
    ("pro baseball", "Baseball (pro baseball on tape)"),
)

ASKED = (
    "Run a compare: show profit if we executed Strategy B on all these games, vs tightening: "
    "ONLY bet a T0 pair when the winner at T0 (T0 favorite = higher Yes ask) is <70¢, AND "
    "both Yes at T0 cost 1.04 or less, and separately 1.09 or less. Show compares for all sports, "
    "tennis only, and each individual sport, using the all-game T0 / tick tape (not just fills)."
)
PLAIN = (
    "Strategy B buys Yes on both players (or both sides of a spread/total) at the first trusted "
    "start (T0), then extra on the underdog if they later go through 50¢ from below, then a cheaper "
    "ticket on the original favorite if they dip. Tightening = skip the start if the market favorite "
    "is already 70¢ or more, or the two tickets cost more than $1.04 / $1.09. A Yes is a dollar from "
    "0 to 1 and also an implied chance: 0.65 means 65 percent. Cost C is the two Yes asks added "
    "together (the vig, the house overround). Wire C is asks only; all-in C adds documented taker "
    "fees. Primary ranking is net dollars after fees. Live C_HI stays 1.20. This page does not "
    "change live knobs, does not start a second Strategy B, and does not sell tickets. Research "
    "only. Not gold. Not DailyRun. The October 2026 tape is all out-of-sample versus the 2024-01-01 "
    "holdout (in-sample N=0). Same-day contracts, so annualized rate of return is omitted."
)


@dataclass(frozen=True)
class Gate:
    id: str
    label: str
    role: str
    fav_lt: float | None
    c_max: float
    c_mode: str
    diagnostic: bool = False


ARM_CONTROL = Gate("control", "Control · live B (C_HI 1.20, no fav cap)", "control", None, C_HI_LIVE, "wire")
ARM_FAV70_C104 = Gate("fav70_c104", "Candidate A · fav<70¢ AND C≤1.04", "candidate", FAV_LT, C_104, "wire")
ARM_FAV70_C109 = Gate("fav70_c109", "Candidate B · fav<70¢ AND C≤1.09", "candidate", FAV_LT, C_109, "wire")
ARM_FAV70 = Gate("fav70", "Slice · fav<70¢ only (C_HI still 1.20)", "slice", FAV_LT, C_HI_LIVE, "wire", True)
ARM_C104 = Gate("c104", "Slice · C≤1.04 only (any favorite)", "slice", None, C_104, "wire", True)
ARM_C109 = Gate("c109", "Slice · C≤1.09 only (any favorite)", "slice", None, C_109, "wire", True)
ARM_FAV70_C104_ALLIN = Gate(
    "fav70_c104_allin", "All-in A · fav<70¢ AND all-in C≤1.04", "all_in", FAV_LT, C_104, "all_in"
)
ARM_FAV70_C109_ALLIN = Gate(
    "fav70_c109_allin", "All-in B · fav<70¢ AND all-in C≤1.09", "all_in", FAV_LT, C_109, "all_in"
)
ARM_C104_ALLIN = Gate("c104_allin", "All-in slice · all-in C≤1.04 only", "all_in", None, C_104, "all_in", True)
ARM_C109_ALLIN = Gate("c109_allin", "All-in slice · all-in C≤1.09 only", "all_in", None, C_109, "all_in", True)

PRIMARY_ARMS = (ARM_CONTROL, ARM_FAV70_C104, ARM_FAV70_C109, ARM_FAV70, ARM_C104, ARM_C109)
ALLIN_ARMS = (ARM_CONTROL, ARM_FAV70_C104_ALLIN, ARM_FAV70_C109_ALLIN, ARM_C104_ALLIN, ARM_C109_ALLIN)
ALL_GATES = PRIMARY_ARMS + (ARM_FAV70_C104_ALLIN, ARM_FAV70_C109_ALLIN, ARM_C104_ALLIN, ARM_C109_ALLIN)


def esc(value) -> str:
    return html_mod.escape("" if value is None else str(value))


def iso_now() -> str:
    return datetime.now(ET).isoformat(timespec="seconds")


def _out(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


def documented_taker_fee(venue: str, price) -> Decimal | None:
    return documented_leg_fee(str(venue or "").lower(), price)


def t0_favorite_yes(t0_a, t0_b) -> float | None:
    if t0_a is None or t0_b is None:
        return None
    return max(float(t0_a), float(t0_b))


def in_yes_band(price) -> bool:
    if price is None:
        return False
    px = float(price)
    return YES_LO < px < YES_HI


def t0_send_ok(t0_a, t0_b, gate: Gate, all_in=None) -> tuple[bool, str]:
    """Live T0 send gate plus optional fav<70 and C cap. Exclusive <70¢. C cap inclusive."""
    if t0_a is None or t0_b is None:
        return False, "no_t0"
    if not in_yes_band(t0_a) or not in_yes_band(t0_b):
        return False, "yes_band"
    fav = t0_favorite_yes(t0_a, t0_b)
    if gate.fav_lt is not None and fav is not None and fav >= gate.fav_lt - 1e-12:
        return False, "fav_ge_70"
    if gate.c_mode == "all_in":
        if all_in is None:
            return False, "all_in_unknown"
        cost = float(all_in)
    else:
        cost = float(t0_a) + float(t0_b)
    if cost > float(gate.c_max) + 1e-12:
        return False, "c_hi"
    return True, ""


def first_after(ticks: list[tuple[int, float]], ts: int) -> tuple[int, float] | None:
    for t, px in ticks:
        if t > ts:
            return (t, px)
    return None


def first_cross_from_below(
    ticks: list[tuple[int, float]],
    lo: int,
    hi: int,
    t0_px: float | None,
    bar: float = CROSS,
) -> dict | None:
    """Same Trungelliti rewind as strategy_b_t0_plus_50cross_20261023.first_cross_from_below."""
    need_reset = t0_px is not None and float(t0_px) > bar + 1e-12
    reset_ts = None
    for ts, px in ticks:
        if ts <= lo or ts > hi:
            continue
        if px <= ABSORB + 1e-12 or px >= 0.95 - 1e-12:
            continue
        if need_reset:
            if px <= bar + 1e-12:
                need_reset = False
                reset_ts = ts
            continue
        if px > bar + 1e-12:
            nxt = first_after(ticks, ts)
            return {
                "ts": ts,
                "px": px,
                "next_ts": nxt[0] if nxt else None,
                "next_px": nxt[1] if nxt else None,
                "t0_already_above": bool(t0_px is not None and float(t0_px) > bar + 1e-12),
                "reset_ts": reset_ts,
            }
    return None


def first_yes_at_or_below(
    ticks: list[tuple[int, float]],
    after_ts: int,
    hi: int,
    target: float,
) -> dict | None:
    """Same as dense_inplay_fav_lock_cross_smalld_20261021.first_yes_at_or_below."""
    if target is None or target < -1e-12:
        return None
    for ts, px in ticks:
        if ts <= after_ts or ts > hi:
            continue
        if px <= ABSORB + 1e-12:
            continue
        if px <= target + 1e-12:
            return {"ts": ts, "px": px, "target": target}
    return None


def extras_payout(winner: str, n_a: int, n_b: int) -> float:
    if winner == "a":
        return 1.0 + float(n_a)
    if winner == "b":
        return 1.0 + float(n_b)
    return 0.0


def fav_dog_letters(t0_a, t0_b) -> tuple[str, str]:
    if t0_b is not None and t0_a is not None and float(t0_b) > float(t0_a) + 1e-12:
        return "b", "a"
    return "a", "b"


def ticks_of(book: dict, letter: str) -> list[tuple[int, float]]:
    return list(book.get("yes_a") or [] if letter == "a" else book.get("yes_b") or [])


def play_hi(book: dict) -> int | None:
    t0 = book.get("t0_ts")
    if t0 is None:
        return None
    yes_a = book.get("yes_a") or []
    yes_b = book.get("yes_b") or []
    last = None
    for bag in (yes_a, yes_b):
        if bag:
            last = bag[-1][0] if last is None else max(last, bag[-1][0])
    after_a = [row for row in yes_a if row[0] > t0]
    after_b = [row for row in yes_b if row[0] > t0]
    absorb = first_absorbing(after_a, after_b)
    if absorb is None:
        return last
    if last is None:
        return absorb - 1
    return min(last, absorb - 1)


def simulate_b_on_book(book: dict, gate: Gate) -> dict:
    """One SIZE=1 T0 pair, then T0-dog 50-cross from below, then fav dip at 1−cross−D=0.25."""
    t0_a, t0_b = book.get("t0_a"), book.get("t0_b")
    venue = str(book.get("venue") or "")
    all_in = all_in_c(venue, t0_a, t0_b) if t0_a is not None and t0_b is not None else None
    rec = {
        "arm": gate.id,
        "sent": False,
        "skip": "",
        "n_t0": 0,
        "n_cross": 0,
        "n_dip": 0,
        "c_wire": (float(t0_a) + float(t0_b)) if t0_a is not None and t0_b is not None else None,
        "c_all_in": float(all_in) if all_in is not None else None,
        "fav": None,
        "dog": None,
        "t0_fav": t0_favorite_yes(t0_a, t0_b),
        "cross_px": None,
        "cross_ts": None,
        "dip_px": None,
        "dip_ts": None,
        "mix": "skipped",
        "cost": None,
        "fees": None,
        "payout": None,
        "pnl": None,
        "pnl_fee": None,
        "fee_unknown": False,
        "fav_won": None,
    }
    ok, why = t0_send_ok(t0_a, t0_b, gate, all_in=all_in)
    if not ok:
        rec["skip"] = why
        return rec
    fills = [float(t0_a), float(t0_b)]
    fees_parts = [documented_taker_fee(venue, px) for px in fills]
    if any(part is None for part in fees_parts):
        rec["skip"] = "fee_unknown"
        rec["fee_unknown"] = True
        return rec
    fav, dog = fav_dog_letters(t0_a, t0_b)
    rec["fav"] = fav
    rec["dog"] = dog
    rec["sent"] = True
    rec["n_t0"] = 1
    rec["skip"] = ""
    rec["mix"] = "t0 both only"
    lo = int(book["t0_ts"])
    hi = play_hi(book)
    cost = float(t0_a) + float(t0_b)
    n_a = n_b = 0
    if hi is not None:
        t0_dog = float(t0_b) if dog == "b" else float(t0_a)
        cross = first_cross_from_below(ticks_of(book, dog), lo, int(hi), t0_dog)
        if cross is not None:
            fill_px = float(cross["px"])
            fill_ts = int(cross["ts"])
            if ABSORB + 1e-12 < fill_px < 0.95 - 1e-12:
                extra_fee = documented_taker_fee(venue, fill_px)
                if extra_fee is None:
                    rec["skip"] = "fee_unknown"
                    rec["fee_unknown"] = True
                    rec["sent"] = False
                    rec["n_t0"] = 0
                    return rec
                rec["n_cross"] = 1
                rec["cross_px"] = fill_px
                rec["cross_ts"] = fill_ts
                rec["mix"] = "cross, no fav hedge"
                cost += fill_px
                fills.append(fill_px)
                fees_parts.append(extra_fee)
                if dog == "a":
                    n_a += 1
                else:
                    n_b += 1
                target = 1.0 - fill_px - D
                extra = first_yes_at_or_below(ticks_of(book, fav), fill_ts, int(hi), target)
                if extra is not None:
                    dip_px = float(extra["px"])
                    dip_fee = documented_taker_fee(venue, dip_px)
                    if dip_fee is None:
                        rec["skip"] = "fee_unknown"
                        rec["fee_unknown"] = True
                        rec["sent"] = False
                        rec["n_t0"] = 0
                        rec["n_cross"] = 0
                        return rec
                    rec["n_dip"] = 1
                    rec["dip_px"] = dip_px
                    rec["dip_ts"] = int(extra["ts"])
                    rec["mix"] = "cross + fav lock"
                    cost += dip_px
                    fills.append(dip_px)
                    fees_parts.append(dip_fee)
                    if fav == "a":
                        n_a += 1
                    else:
                        n_b += 1
    rec["cost"] = cost
    rec["fees"] = float(sum(fees_parts))
    winner = book.get("winner")
    settled = bool(book.get("settled") and winner in ("a", "b") and not book.get("void"))
    rec["fav_won"] = (winner == fav) if settled else None
    if settled:
        paid = extras_payout(winner, n_a, n_b)
        rec["payout"] = paid
        rec["pnl"] = paid - cost
        rec["pnl_fee"] = paid - cost - rec["fees"]
    return rec


def mean(xs: list[float]) -> float | None:
    return float(statistics.mean(xs)) if xs else None


def median(xs: list[float]) -> float | None:
    return float(statistics.median(xs)) if xs else None


def dollar_drawdown(pnls: list[float]) -> float | None:
    if not pnls:
        return None
    equity = peak = 0.0
    dd = 0.0
    for x in pnls:
        equity += x
        if equity > peak:
            peak = equity
        dd = min(dd, equity - peak)
    return abs(dd)


def losing_streak(pnls: list[float]) -> int:
    best = cur = 0
    for x in pnls:
        if x < -1e-12:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def book_hours(book: dict) -> float:
    t0 = book.get("t0_ts")
    hi = play_hi(book)
    if t0 is None:
        return 0.0
    end = hi if hi is not None else t0
    return max(0.0, float(end) - float(t0)) / 3600.0


def book_date(book: dict) -> str:
    t0 = book.get("t0_ts")
    if t0 is None:
        return ""
    return datetime.fromtimestamp(int(t0), ET).strftime("%Y-%m-%d")


def closed_rows(books: list[dict], gate: Gate) -> list[dict]:
    rows = []
    for book in books:
        rec = (book.get("arms") or {}).get(gate.id) or {}
        if not rec.get("sent") or rec.get("pnl_fee") is None:
            continue
        if not book.get("settled") or book.get("void"):
            continue
        pnl = float(rec["pnl_fee"])
        cost = float(rec["cost"] or 0.0)
        fees = float(rec["fees"] or 0.0)
        cash = cost + fees
        hours = book_hours(book)
        opened = datetime.fromtimestamp(int(book["t0_ts"]), ET) if book.get("t0_ts") else None
        hi = play_hi(book)
        closed = datetime.fromtimestamp(int(hi), ET) if hi is not None else opened
        rows.append(
            {
                "game": book.get("game") or "",
                "sport": book.get("sport") or "",
                "venue": book.get("venue") or "",
                "kind": book.get("kind") or "",
                "date": book_date(book),
                "pnl_d": pnl,
                "pnl_gross": rec.get("pnl"),
                "fees": fees,
                "cost": cost,
                "cash": cash,
                "pnl": (100.0 * pnl / cash) if cash > 1e-12 else None,
                "days": hours / 24.0,
                "hours": hours,
                "opened": opened,
                "closed": closed,
                "fav_won": rec.get("fav_won"),
                "n_cross": rec.get("n_cross") or 0,
                "n_dip": rec.get("n_dip") or 0,
                "n_t0": rec.get("n_t0") or 0,
                "mix": rec.get("mix") or "",
            }
        )
    rows.sort(key=lambda r: (r.get("date") or "", r.get("game") or ""))
    return rows


def slice_is_oos(rows: list[dict], which: str) -> list[dict]:
    if which == "full":
        return list(rows)
    out = []
    for row in rows:
        day = str(row.get("date") or "")[:10]
        if not day:
            continue
        if which == "is" and day < IS_CUT:
            out.append(row)
        elif which == "oos" and day >= IS_CUT:
            out.append(row)
    return out


def summarize_arm(books: list[dict], gate: Gate) -> dict:
    recs = [(b, (b.get("arms") or {}).get(gate.id) or {}) for b in books]
    sent = [(b, r) for b, r in recs if r.get("sent")]
    scored = closed_rows(books, gate)
    pnls = [r["pnl_d"] for r in scored]
    wins = [x for x in pnls if x > 1e-12]
    losses = [x for x in pnls if x < -1e-12]
    n = len(scored)
    sum_win = sum(wins)
    sum_loss = abs(sum(losses))
    pf = (sum_win / sum_loss) if sum_loss > 1e-12 else (float("inf") if sum_win > 0 else None)
    fees = [float(r["fees"]) for r in scored]
    pcts = [r["pnl"] for r in scored if r.get("pnl") is not None]
    wo = None
    if len(pcts) >= 2:
        dropped = pcts[:]
        dropped.remove(max(dropped))
        wo = mean(dropped)
    elif pcts:
        wo = mean(pcts)
    wr_strat = (100.0 * len(wins) / n) if n else None
    fav_known = [r for r in scored if r.get("fav_won") is not None]
    wr_fav = (100.0 * sum(1 for r in fav_known if r["fav_won"]) / len(fav_known)) if fav_known else None
    hours = [r["hours"] for r in scored]
    days = [r["days"] for r in scored]
    avg_days = mean(days) if days else None
    cash = median([r["cash"] for r in scored if r.get("cash")]) or 1.0
    overlay = {}
    try:
        if scored:
            overlay = overlay_ann_ror_max_dd(
                scored, cash=float(cash), initial_account=DEFAULT_INITIAL_ACCOUNT
            )
    except (OverflowError, ValueError, ZeroDivisionError):
        overlay = {"note": "overlay overflow on same-day holds"}
    ann_note = (
        "omitted: same-day contracts (avg days held ~0); house Ann ROR would not be meaningful"
    )
    is_rows = slice_is_oos(scored, "is")
    oos_rows = slice_is_oos(scored, "oos")
    n_void_sent = sum(
        1 for b, r in sent if b.get("void")
    )
    n_pending_sent = sum(
        1 for b, r in sent if (not b.get("settled")) and (not b.get("void"))
    )
    n_fee_skip = sum(1 for _b, r in recs if r.get("fee_unknown"))
    max_trade = max(pnls) if pnls else None
    min_trade = min(pnls) if pnls else None
    return {
        "gate": gate,
        "arm": gate.label,
        "role": gate.role,
        "diagnostic": gate.diagnostic,
        "n_universe": len(books),
        "n_sent": len(sent),
        "n_t0": sum(int(r.get("n_t0") or 0) for _b, r in sent),
        "n_cross": sum(int(r.get("n_cross") or 0) for r in scored),
        "n_dip": sum(int(r.get("n_dip") or 0) for r in scored),
        "n_scored": n,
        "n_win": len(wins),
        "n_loss": len(losses),
        "n_scratch": n - len(wins) - len(losses),
        "n_void_sent": n_void_sent,
        "n_pending_sent": n_pending_sent,
        "n_fee_skip": n_fee_skip,
        "n_is": len(is_rows),
        "n_oos": len(oos_rows),
        "net_pnl": sum(pnls) if pnls else 0.0,
        "pnl_cents": (100.0 * sum(pnls)) if pnls else 0.0,
        "fees": sum(fees) if fees else 0.0,
        "expectancy": mean(pnls),
        "win_pct": wr_strat,
        "fav_win_pct": wr_fav,
        "pf": pf,
        "avg_win": mean(wins),
        "avg_loss": mean(losses),
        "avg_pnl_pct": mean(pcts),
        "avg_pnl_pct_wo_max": wo,
        "max_dd": dollar_drawdown(pnls),
        "max_dd_pct_500k": overlay.get("max_dd") if overlay else None,
        "calmar": None,
        "sharpe": overlay.get("sharpe") if overlay else None,
        "sharpe_source": overlay.get("sharpe_source") if overlay else "",
        "ann_ror": None,
        "ann_ror_is": None,
        "ann_ror_oos": None,
        "ann_ror_note": ann_note,
        "avg_hours": mean(hours),
        "avg_days": avg_days,
        "capital_days": (n * avg_days) if n and avg_days is not None else 0.0,
        "losing_streak": losing_streak(pnls),
        "max_trade": max_trade,
        "min_trade": min_trade,
        "brt_cash": cash,
        "note": tiny_note(n),
        "rows": scored,
    }


def sport_of(book: dict) -> str:
    return str(book.get("sport") or "unknown").strip().lower()


def filter_sport(books: list[dict], sport: str | None) -> list[dict]:
    if not sport or sport == "all":
        return list(books)
    want = sport.strip().lower()
    aliases = {want}
    if want == "hockey":
        aliases.update({"pro hockey", "hockey"})
    if want == "baseball":
        aliases.update({"pro baseball", "baseball"})
    if want == "pro hockey":
        aliases.add("hockey")
    if want == "pro baseball":
        aliases.add("baseball")
    return [b for b in books if sport_of(b) in aliases]


def match_key(book: dict) -> tuple:
    return (
        sport_of(book),
        book.get("game_n") or game_norm(book.get("game") or ""),
        str(book.get("kind") or "moneyline"),
        str(book.get("number") or ""),
    )


def pick_one_venue(books: list[dict]) -> tuple[list[dict], int]:
    bags: dict[tuple, list[dict]] = defaultdict(list)
    for book in books:
        bags[match_key(book)].append(book)
    out = []
    dropped = 0
    for items in bags.values():
        ranked = sorted(
            items,
            key=lambda b: VENUE_RANK.get(str(b.get("venue") or "").lower(), 9),
        )
        out.append(ranked[0])
        dropped += len(ranked) - 1
    return out, dropped


def max_concurrent(books: list[dict]) -> int:
    events = []
    for book in books:
        t0 = book.get("t0_ts")
        if t0 is None:
            continue
        hi = play_hi(book)
        end = int(hi) if hi is not None else int(t0)
        events.append((int(t0), 1))
        events.append((end + 1, -1))
    events.sort()
    cur = mx = 0
    for _t, delta in events:
        cur += delta
        mx = max(mx, cur)
    return mx


def attach_trusted_t0(book: dict, occ_map: dict) -> None:
    yes_a = book.get("yes_a") or []
    yes_b = book.get("yes_b") or []
    listed_dt = parse_dt(book.get("listed_raw") or "")
    if listed_dt is not None:
        listed_dt = to_et(listed_dt)
    occ_dt = occ_map.get(book.get("game_n") or "")
    clock, src, skip = pick_trusted_clock(occ_dt, listed_dt, yes_a, yes_b)
    book["t0_source"] = src
    book["clock_skip"] = skip
    book["clock"] = clock.isoformat() if clock else ""
    book["t0_a"] = None
    book["t0_b"] = None
    book["t0_ts"] = None
    book["t0_label"] = ""
    book["trusted"] = False
    if clock is None or not book.get("two_sided"):
        return
    clock_ts = int(to_et(clock).timestamp())
    t0_a, t0_b, t0_ts, label = assign_t0_prices(yes_a, yes_b, clock_ts)
    book["t0_a"] = t0_a
    book["t0_b"] = t0_b
    book["t0_ts"] = t0_ts
    book["t0_label"] = f"{label} ({src})"
    if t0_a is None or t0_b is None or t0_ts is None:
        book["clock_skip"] = "no_t0_quotes"
        return
    book["c0"] = float(t0_a) + float(t0_b)
    book["trusted"] = True
    fav, dog = fav_dog_letters(t0_a, t0_b)
    book["fav"] = fav
    book["dog"] = dog
    book["t0_fav"] = t0_favorite_yes(t0_a, t0_b)
    book["t0_dog"] = float(t0_b) if dog == "b" else float(t0_a)
    got = all_in_c(book.get("venue") or "", t0_a, t0_b)
    book["c_all_in"] = float(got) if got is not None else None


def load_universe() -> tuple[list[dict], dict]:
    _out("streaming Yes tape (archive + shards)")
    sides, stream_meta = stream_yes_sides()
    books = pair_books(sides)
    settlements = load_settlement_rows()
    index = build_index(settlements)
    occ_map = start_lookup_from_settlements(settlements)
    _out(f"books {len(books)} settlements {len(settlements)}")
    counts = defaultdict(int)
    for i, book in enumerate(books):
        if (i + 1) % 500 == 0:
            _out(f"  scored {i + 1}/{len(books)}")
        settle_book(book, settlements, index)
        attach_trusted_t0(book, occ_map)
        kind = str(book.get("kind") or "")
        if kind == "total" and not book.get("two_sided"):
            counts["totals_one_sided"] += 1
        if not book.get("two_sided"):
            counts["one_sided"] += 1
        elif int(book.get("n_sides") or 0) != 2:
            counts["not_two_complementary"] += 1
        elif not book.get("trusted"):
            counts["no_trusted_t0"] += 1
            counts[f"skip_{book.get('clock_skip') or 'unknown'}"] += 1
        else:
            counts["trusted_two_sided"] += 1
            if book.get("void"):
                counts["void"] += 1
            elif book.get("settled"):
                counts["settled"] += 1
            else:
                counts["pending"] += 1
            if str(book.get("venue") or "").lower() == "novig":
                counts["novig_trusted"] += 1
            if kind == "total":
                counts["totals_two_sided"] += 1
            elif kind == "spread":
                counts["spreads_two_sided"] += 1
            else:
                counts["moneyline_two_sided"] += 1
    trusted = [
        b for b in books
        if b.get("trusted") and b.get("two_sided") and int(b.get("n_sides") or 0) == 2
    ]
    deduped, n_dropped = pick_one_venue(trusted)
    counts["venue_dropped"] = n_dropped
    counts["trusted_deduped"] = len(deduped)
    counts["novig_only_after_dedup"] = sum(
        1 for b in deduped if str(b.get("venue") or "").lower() == "novig"
    )
    sports = sorted({sport_of(b) for b in deduped})
    meta = {
        **stream_meta,
        "n_books": len(books),
        "n_settlements": len(settlements),
        "counts": dict(counts),
        "sports": sports,
        "built_at": iso_now(),
    }
    _out(
        f"trusted two-sided {counts['trusted_two_sided']} after venue-dedup {len(deduped)} "
        f"settled {sum(1 for b in deduped if b.get('settled'))} void "
        f"{sum(1 for b in deduped if b.get('void'))} pending "
        f"{sum(1 for b in deduped if not b.get('settled') and not b.get('void'))}"
    )
    return deduped, meta


def run_all_arms(books: list[dict]) -> None:
    for book in books:
        book["arms"] = {}
        for gate in ALL_GATES:
            book["arms"][gate.id] = simulate_b_on_book(book, gate)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def td(value, *, money: bool = False, delta: bool = False) -> str:
    if money and delta:
        return f"<td>{esc(format_money_delta(value))}</td>"
    if money:
        return f"<td>{esc(format_money(value))}</td>"
    if value is None or value == "":
        return "<td>—</td>"
    if isinstance(value, float) and not math.isfinite(value):
        return "<td>n/a</td>"
    return f"<td>{esc(value)}</td>"


def fmt_pct(value) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return str(value)


def fmt_num(value, digits: int = 3) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return "n/a"
    return f"{number:.{digits}f}"


def fmt_pf(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, float) and math.isinf(value):
        return "∞"
    return fmt_num(value, 2)


def html_table(headers: list[tuple[str, str]], rows: list[list], money_idx: set[int] | None = None) -> str:
    money_idx = money_idx or set()
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        klass = ""
        cells_src = row
        if row and isinstance(row[0], dict) and row[0].get("_total"):
            klass = ' class="total-row"'
            cells_src = row[0].get("cells") or row[1:]
        cells = []
        for i, cell in enumerate(cells_src):
            if isinstance(cell, tuple) and len(cell) == 2 and cell[0] == "delta$":
                cells.append(td(cell[1], money=True, delta=True))
            elif i in money_idx:
                cells.append(td(cell, money=True))
            else:
                cells.append(td(cell))
        body.append(f"<tr{klass}>{''.join(cells)}</tr>")
    if not body:
        body.append("<tr>" + "".join(td("") for _ in headers) + "</tr>")
    return (
        f"{report_page_extras.SWIPE_NOTE_HTML}<div class=\"table-wrap\">"
        f"<table class=\"sortable\"><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def arm_row(summary: dict, control: dict | None = None) -> list:
    s = summary
    delta_pnl = ""
    if control is not None and s.get("gate") is not control.get("gate"):
        delta_pnl = ("delta$", (s["net_pnl"] or 0) - (control["net_pnl"] or 0))
    return [
        s["arm"],
        s["role"] + (" · diagnostic" if s["diagnostic"] else ""),
        s["n_scored"],
        s["n_sent"],
        s["n_t0"],
        s["n_cross"],
        s["n_dip"],
        s["fees"],
        s["net_pnl"],
        fmt_num(s["pnl_cents"], 1),
        fmt_num(s["expectancy"], 4) if s["expectancy"] is not None else "—",
        fmt_pct(s["win_pct"]),
        fmt_pct(s["fav_win_pct"]),
        fmt_pf(s["pf"]),
        s["max_dd"],
        s["n_win"],
        s["n_loss"],
        fmt_num(s["avg_win"], 4) if s["avg_win"] is not None else "—",
        fmt_num(s["avg_loss"], 4) if s["avg_loss"] is not None else "—",
        fmt_num(s["avg_pnl_pct"], 2) if s["avg_pnl_pct"] is not None else "—",
        fmt_num(s["avg_pnl_pct_wo_max"], 2) if s["avg_pnl_pct_wo_max"] is not None else "—",
        "omitted",
        f"n/a (IS N={s['n_is']})",
        f"omitted (OOS N={s['n_oos']})",
        "n/a (no Ann ROR)",
        fmt_num(s["sharpe"], 2) if s["sharpe"] is not None else "—",
        fmt_num(s["avg_hours"], 2) if s["avg_hours"] is not None else "—",
        fmt_num(s["capital_days"], 3),
        s["losing_streak"],
        format_money(s["max_trade"]) if s["max_trade"] is not None else "—",
        s["note"],
        delta_pnl if delta_pnl else "—",
    ]


PRIMARY_HEADERS = [
    ("Arm", "text"),
    ("Role", "text"),
    ("N scored", "num"),
    ("N matches sent", "num"),
    ("N T0 pairs", "num"),
    ("N 50-cross extras", "num"),
    ("N dip extras", "num"),
    ("Total fees $", "num"),
    ("Net P&L with fees $", "num"),
    ("P&L ¢", "num"),
    ("Expectancy $/match", "num"),
    ("Win% strategy", "num"),
    ("WR T0 favorite", "num"),
    ("Profit factor", "num"),
    ("Max DD $", "num"),
    ("Wins", "num"),
    ("Losses", "num"),
    ("Avg win $", "num"),
    ("Avg loss $", "num"),
    ("Avg PnL %", "num"),
    ("AVG_PNL_PCT_WO_MAX", "num"),
    ("Ann ROR full", "text"),
    ("Ann ROR IS", "text"),
    ("Ann ROR OOS", "text"),
    ("Calmar", "text"),
    ("Sharpe", "num"),
    ("Avg hours held", "num"),
    ("Capital days", "num"),
    ("Losing streak", "num"),
    ("Max single-trade $ (not primary)", "text"),
    ("Sample", "text"),
    ("Δ net P&L vs control", "num"),
]
MONEY_COLS = {7, 8, 14}


def section_table(books: list[dict], gates: tuple[Gate, ...], title: str, note: str = "") -> str:
    summaries = [summarize_arm(books, g) for g in gates]
    control = next((s for s in summaries if s["role"] == "control"), summaries[0])
    rows = [arm_row(s, control) for s in summaries]
    bits = [f"<h3>{esc(title)}</h3>"]
    if note:
        bits.append(f'<p class="note">{note}</p>')
    for s in summaries:
        if s["gate"].id in (ARM_CONTROL.id, ARM_FAV70_C104.id, ARM_FAV70_C109.id):
            bits.append(
                f'<p><strong>{esc(s["arm"])}:</strong> net {esc(format_money(s["net_pnl"]))} '
                f"on {s['n_scored']} scored matches "
                f"(sent {s['n_sent']}; 50-cross {s['n_cross']}; dip {s['n_dip']}; "
                f"expectancy {esc(fmt_num(s['expectancy'], 4) if s['expectancy'] is not None else '—')}; "
                f"strategy WR {esc(fmt_pct(s['win_pct']))}; T0-fav WR {esc(fmt_pct(s['fav_win_pct']))})."
                f"</p>"
            )
    bits.append('<p class="note">Click column headers to sort.</p>')
    bits.append(html_table(PRIMARY_HEADERS, rows, MONEY_COLS))
    return "\n".join(bits)


def pending_rows(books: list[dict], limit: int = 40) -> list[list]:
    pending = [
        b for b in books
        if b.get("trusted") and (not b.get("settled")) and (not b.get("void"))
    ]
    pending.sort(key=lambda b: (book_date(b), b.get("game") or ""), reverse=True)
    out = []
    for b in pending[:limit]:
        out.append(
            [
                b.get("sport") or "",
                b.get("game") or "",
                b.get("kind") or "",
                b.get("number") or "",
                b.get("venue") or "",
                book_date(b),
                fmt_num(b.get("t0_fav"), 2),
                fmt_num(b.get("c0"), 3),
                fmt_num(b.get("c_all_in"), 3) if b.get("c_all_in") is not None else "N (no fee coeff)",
            ]
        )
    return out, len(pending)


def per_match_rows(books: list[dict], limit: int = 800) -> list[list]:
    scored = [b for b in books if b.get("settled") and not b.get("void")]
    scored.sort(key=lambda b: (book_date(b), b.get("game") or ""))
    out = []
    for b in scored[:limit]:
        arms = b.get("arms") or {}
        ctrl = arms.get(ARM_CONTROL.id) or {}
        a = arms.get(ARM_FAV70_C104.id) or {}
        bb = arms.get(ARM_FAV70_C109.id) or {}
        out.append(
            [
                b.get("sport") or "",
                b.get("game") or "",
                b.get("kind") or "",
                b.get("number") or "",
                b.get("venue") or "",
                book_date(b),
                fmt_num(b.get("t0_fav"), 2),
                fmt_num(b.get("c0"), 3),
                fmt_num(b.get("c_all_in"), 3) if b.get("c_all_in") is not None else "—",
                "yes" if (ctrl.get("fav_won")) else ("no" if ctrl.get("fav_won") is False else "—"),
                format_money(ctrl.get("pnl_fee")) if ctrl.get("sent") and ctrl.get("pnl_fee") is not None else "skip",
                format_money(a.get("pnl_fee")) if a.get("sent") and a.get("pnl_fee") is not None else "skip",
                format_money(bb.get("pnl_fee")) if bb.get("sent") and bb.get("pnl_fee") is not None else "skip",
                ctrl.get("mix") or "",
            ]
        )
    return out, len(scored)


def judge(ctrl: dict, cand_a: dict, cand_b: dict) -> tuple[str, str]:
    """Quality over count. Combined arms cut N. Do not retune. HOLD on live."""
    def better(cand: dict) -> str:
        n_c, n_t = cand["n_scored"], ctrl["n_scored"]
        exp_c, exp_t = cand["expectancy"], ctrl["expectancy"]
        pnl_c, pnl_t = cand["net_pnl"], ctrl["net_pnl"]
        if n_c <= 0:
            return "DISMISS"
        collapsed = n_t > 0 and n_c < max(20, 0.35 * n_t)
        if exp_c is None or exp_t is None:
            return "HOLD"
        quality_up = exp_c > exp_t + 1e-6 and (pnl_c >= pnl_t - 1e-9)
        quality_down = exp_c < exp_t - 1e-6 and pnl_c < pnl_t - 1e-9
        if quality_down:
            return "DISMISS"
        if quality_up and not collapsed:
            return "LEAN KEEP"
        if quality_up and collapsed:
            return "HOLD"
        return "HOLD"

    a = better(cand_a)
    b = better(cand_b)
    if a == "LEAN KEEP" or b == "LEAN KEEP":
        live = "HOLD on live change (research candidate ≠ gold ≠ DailyRun; do not wire)."
        return "LEAN KEEP (research only)", live
    if a == "DISMISS" and b == "DISMISS":
        return "DISMISS vs control on quality", "HOLD on live change. Live C_HI still 1.20."
    return "HOLD", "HOLD on live change. Do not retune from this table. Live C_HI still 1.20."


def write_baseline(meta: dict, verdict: str, live: str) -> None:
    counts = meta.get("counts") or {}
    BASELINE.write_text(
        "\n".join(
            [
                "# BASELINE — Strategy B vs fav<70¢ × C 1.04 / 1.09",
                "",
                "Research only. Not gold. Not DailyRun. HOLD on live change.",
                "",
                "## Original request",
                ASKED,
                "",
                "## Freeze (control = live Strategy B as of 2026-10-24 13:18 ET after the under-$1 job)",
                "",
                "- T0: buy 1 Yes on each side when both Yes asks in (0.10, 0.90), **no C_LO floor**, C_HI **1.20 on Yes-ask sum (wire)** for the send gate.",
                "- After confirmed T0, live also stacks extra 1-contract pairs while **all-in C < $1**, cap 10. **Primary book here is 1 pair per match at T0 (SIZE=1)** matching historical B sims. Stacking is a note, not P&L.",
                "- Then first from-below 50-cross on the **T0 dog**, then favorite dip at 1 − cross_fill − D with **D=0.25**.",
                "- Extra-Yes-on-dip is DISMISS / off.",
                "- Favorite/dog from **T0 Yes asks**, not fill_px. 50-cross only T0 dog from below. Rewind false favorite-cross (Trungelliti): if the dog is already >50¢ at T0, wait for a down-print ≤50 then the next print >50.",
                "- Fills at ask (taker) on the tick that qualifies. Tape quotes are size-filtered at ingest (`price_memory`); we do not invent a tick with no ask. If a qualifying tick exists, fill at that ask.",
                "- `MAX_OPEN_B_MATCHES` is **not** applied (live risk cap; code currently 4, Paul mentioned 2). Concurrent opens are a footnote.",
                "- Live knobs not changed: C_HI 1.20, D=0.25, stacking all-in<$1 as already wired.",
                "",
                "## T0 definition",
                "",
                "Same trusted first serve as `tools/t0_all_games_stats.py` and `tools/write_t0_band_from_stay_above.py`: Kalshi/Gemini occurrence when clocked, else listed/feed with seconds=00. Tape-resume and first-competitive-without-a-clock are not T0. Clock-hides-match (already absorbing before the clock) is skipped.",
                "",
                "## Universe / grain",
                "",
                f"- Tape: local `price_memory` archive + dated shards under `{RAW}` (via `iter_tick_lines`).",
                f"- Stream lines={meta.get('n_lines')} Yes ticks={meta.get('n_yes')} sides={meta.get('n_sides')}. Seen {meta.get('seen_min')} .. {meta.get('seen_max')}.",
                f"- Two-sided books before filters in pairer; trusted two-sided {counts.get('trusted_two_sided')}; after one-venue-per-match-market {counts.get('trusted_deduped')} (dropped {counts.get('venue_dropped')} extra venues).",
                "- **Grain for P&L: one series per (sport, game, market_type, line)** — Kalshi+Gemini on the same tennis moneyline is **not** summed as two bankrolls. Venue pick order: Kalshi, Gemini, Polymarket, Novig.",
                "- Moneyline, spread (two complementary Yes at the same line), and two-sided totals are separate books. A college-football moneyline and a spread on the same game are two tickets; do not read the all-sports total as one-bet-per-game.",
                f"- One-sided Yes skipped: {counts.get('one_sided')}. Totals two-sided included: {counts.get('totals_two_sided')}. Totals one-sided skipped: {counts.get('totals_one_sided')}.",
                f"- Settled (deduped): counted in HTML. Voids excluded from P&L (N_void trusted two-sided {counts.get('void')}). Pending listed, not scored.",
                f"- Novig: documented fee coefficient missing → skip from with-fee P&L (`fee_unknown`). Novig-only after dedup: {counts.get('novig_only_after_dedup')}.",
                f"- Sports on tape: {', '.join(meta.get('sports') or [])}.",
                "",
                "## Fee model (primary P&L WITH fees)",
                "",
                "- Kalshi: 0.07 × p × (1 − p), rounded to $0.0001 (half-up). **Not** the live-sender $0-unless-fill-payload convention.",
                "- Gemini: same 0.07 × p × (1 − p), round up to a cent.",
                "- Polymarket: theta 0.0695 × p × (1 − p), banker's cent.",
                "- Novig: skip with labeled N if coefficient missing (this tape).",
                "",
                "## Candidates",
                "",
                "- A: control rules except T0 pair only if T0 favorite Yes **< 0.70** AND wire both-Yes C **≤ 1.04**.",
                "- B: same AND wire C **≤ 1.09**.",
                "- One-knob slices (diagnostic, not selection): fav<70 only; C≤1.04 only; C≤1.09 only.",
                "- All-in sensitivity: same caps on all-in C (asks+fees). Primary table is **wire C** to match live C_HI.",
                "",
                "## IS / OOS",
                "",
                "House cut is entry_date < 2024-01-01 IS, >= 2024-01-01 OOS. This tape is all October 2026. **IS N=0 / n/a**. OOS is the whole book. Same-day contracts: annualized rate of return is omitted (avg days held ~0; do not invent a second formula). House formula remains `compare_format.ann_ror_from_closed`.",
                "",
                "## Selection bias",
                "",
                "Paul proposed the fav<70 and C 1.04 / 1.09 filters **after** seeing stay-above-50 / T0-band tables. Choosing these caps on the same tape is in-sample selection even though the 2024 holdout is empty. KEEP/LEAN KEEP is research-only. **Do not retune from this table. Do not wire live.**",
                "",
                "## Engine",
                "",
                "Reuse: `t0_all_games_stats` stream/T0/settle; `first_cross_from_below` (Trungelliti rewind, same as `strategy_b_t0_plus_50cross_20261023`); fav dip `first_yes_at_or_below` (same as dense B); extras_payout (T0 both-Yes pays $1 plus extras on the winner). Not a second live B. Extra-Yes-on-dip off.",
                "",
                f"## Verdict this stamp",
                "",
                f"- {verdict}",
                f"- {live}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def write_ab_plan() -> None:
    AB_PLAN.write_text(
        "\n".join(
            [
                "# AB_PLAN — Strategy B T0 tighten fav<70 × C caps",
                "",
                "One hypothesis: skipping T0 both-Yes when the T0 favorite Yes is already 70¢+ **or** the wire both-Yes cost is above $1.04 / $1.09 improves **quality** of Strategy B (net P&L with fees, expectancy, win%, PF, Max DD) without collapsing N.",
                "",
                "## Arms",
                "",
                "| Arm | T0 favorite Yes | Wire C (primary) | All-in C (sensitivity) | Rest of B |",
                "|-----|-----------------|------------------|------------------------|-----------|",
                "| Control | any in (0.10, 0.90) | ≤ 1.20 | not used for send | dog 50-cross from below, then fav dip D=0.25 |",
                "| Candidate A | **< 0.70** | **≤ 1.04** | ≤ 1.04 in all-in table | same |",
                "| Candidate B | **< 0.70** | **≤ 1.09** | ≤ 1.09 in all-in table | same |",
                "| Slice fav<70 | **< 0.70** | ≤ 1.20 | — | same |",
                "| Slice C≤1.04 | any | **≤ 1.04** | ≤ 1.04 in all-in table | same |",
                "| Slice C≤1.09 | any | **≤ 1.09** | ≤ 1.09 in all-in table | same |",
                "",
                "Slices are **diagnostic**, not selection. The combined AND is the candidate. Do not pick a winner from a slice and then pretend the AND was pre-registered.",
                "",
                "## Frozen",
                "",
                "D=0.25, C_HI live 1.20 on control, no C_LO, SIZE=1, extra-Yes-on-dip off, no MAX_OPEN filter, trusted T0, taker fill at ask, fees as BASELINE.md.",
                "",
                "## Judge",
                "",
                "Primary: net P&L with fees, then expectancy/trade, win%, PF, Max DD, N. Not max single-trade PnL. Quality over count. Combined arms will cut N — report that. KEEP/LEAN KEEP only if quality improves without collapsing N; flat → HOLD; worse → DISMISS. **Do not retune. Do not wire live.**",
                "",
                "## Selection bias",
                "",
                "Filters proposed after stay-above-50 / band tables on this tape. Label HOLD on live regardless of the research KEEP/DISMISS.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def write_html(books: list[dict], meta: dict) -> None:
    sports_present = sorted({sport_of(b) for b in books})
    ctrl_all = summarize_arm(books, ARM_CONTROL)
    a_all = summarize_arm(books, ARM_FAV70_C104)
    b_all = summarize_arm(books, ARM_FAV70_C109)
    tennis = filter_sport(books, "tennis")
    ctrl_t = summarize_arm(tennis, ARM_CONTROL)
    a_t = summarize_arm(tennis, ARM_FAV70_C104)
    b_t = summarize_arm(tennis, ARM_FAV70_C109)
    verdict, live = judge(ctrl_all, a_all, b_all)
    sent_ctrl = [b for b in books if ((b.get("arms") or {}).get(ARM_CONTROL.id) or {}).get("sent")]
    concurrent = max_concurrent(sent_ctrl)
    n_stack = sum(
        1
        for b in sent_ctrl
        if b.get("c_all_in") is not None and float(b["c_all_in"]) < 1.0 - 1e-12
        and b.get("settled") and not b.get("void")
    )
    pending_table, n_pending = pending_rows(books)
    match_table, n_match = per_match_rows(books)
    counts = meta.get("counts") or {}
    other_sports = [
        s for s in sports_present
        if s not in {k for k, _ in SPORT_HEADINGS if k != "all"}
    ]

    sport_sections = []
    for key, title in SPORT_HEADINGS:
        subset = books if key == "all" else filter_sport(books, key)
        if key != "all" and not subset:
            sport_sections.append(
                f"<h2>{esc(title)}</h2><p class=\"note\">No trusted two-sided books on this tape after venue-dedup.</p>"
            )
            continue
        note = ""
        if key == "all":
            note = (
                "Match-market grain (one venue per sport+game+market+line). "
                "ML + spread + total on the same game are separate tickets."
            )
        elif key == "tennis":
            note = "Tennis is almost all moneyline. One venue per match after dedup."
        sport_sections.append(section_table(subset, PRIMARY_ARMS, title, note))

    for sport in other_sports:
        subset = filter_sport(books, sport)
        if subset:
            sport_sections.append(section_table(subset, PRIMARY_ARMS, sport.title() or sport, "Other sport on tape."))

    allin_note = (
        "Control is still the live <strong>wire</strong> C_HI=1.20 send. Candidates below gate the T0 pair on "
        "<strong>all-in C</strong> (asks + documented taker fees). Novig all-in is unknown → that T0 is not sent "
        "on all-in arms. Primary ranking table above stays wire C."
    )
    n_allin = sum(1 for b in books if b.get("c_all_in") is not None)
    n_no_allin = sum(1 for b in books if b.get("c_all_in") is None)

    void_n = sum(1 for b in books if b.get("void"))
    settled_n = sum(1 for b in books if b.get("settled") and not b.get("void"))
    pending_n = sum(1 for b in books if not b.get("settled") and not b.get("void"))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>Strategy B vs fav&lt;70¢ × C 1.04 / 1.09</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.banner {{ background: #fef3c7; border: 1px solid #d97706; padding: 10px 12px; margin: 0 0 14px; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
h1 {{ margin: 0 0 0.4rem; }}
h2 {{ margin: 1.4rem 0 0.5rem; }}
h3 {{ margin: 1.1rem 0 0.4rem; }}
code {{ font-size: 0.92em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Strategy B vs fav&lt;70¢ and C $1.04 / $1.09</h1>
<p class="banner"><strong>Research only. HOLD on live change.</strong> Not gold. Not DailyRun.
Live C_HI stays 1.20. D stays 0.25. No second <code>live_strategy_b.py</code>. No tickets sold. No GTC.
Updated {esc(iso_now())} ET. Bookmark <code>{esc(FILE_URL)}</code>.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<h2>Headline</h2>
<p><strong>All sports (with fees, SIZE=1, no live open-slot cap):</strong>
control {esc(format_money(ctrl_all['net_pnl']))} on {ctrl_all['n_scored']} scored
(N sent {ctrl_all['n_sent']});
candidate A fav&lt;70 AND C≤1.04 {esc(format_money(a_all['net_pnl']))} on {a_all['n_scored']};
candidate B fav&lt;70 AND C≤1.09 {esc(format_money(b_all['net_pnl']))} on {b_all['n_scored']}.</p>
<p><strong>Tennis:</strong>
control {esc(format_money(ctrl_t['net_pnl']))} N={ctrl_t['n_scored']};
A {esc(format_money(a_t['net_pnl']))} N={a_t['n_scored']};
B {esc(format_money(b_t['net_pnl']))} N={b_t['n_scored']}.</p>
<p><strong>Verdict:</strong> {esc(verdict)}. {esc(live)}
Selection bias: these filters were proposed after stay-above-50 / T0-band tables on this tape.
Quality over count — combined arms cut N (control scored {ctrl_all['n_scored']} → A {a_all['n_scored']} / B {b_all['n_scored']}).
Do not retune from this table. Do not wire live.</p>
<p class="note">Primary ranking is <strong>net P&amp;L with fees</strong>, then expectancy/trade, strategy win%,
profit factor, Max DD $, N. Not max single-trade PnL. T0-favorite win rate is not strategy P&amp;L:
a T0 both-Yes pair always pays $1, so without extras the path is 1 − C − fees no matter who wins.</p>

<h2>Freeze and stacking note</h2>
<ul>
<li>Control = live Strategy B as of 2026-10-24 13:18 ET after the under-$1 job: T0 both Yes in (0.10, 0.90),
no C_LO, wire C_HI 1.20, then T0-dog 50-cross from below, then favorite dip at 1 − cross_fill − 0.25.
Extra-Yes-on-dip off.</li>
<li><strong>Stacking:</strong> live also buys extra 1-contract T0 pairs while all-in with fees is still under $1
(cap 10). This compare’s primary book is <strong>one pair per match at T0</strong> (SIZE=1), matching historical B sims.
Among control-sent settled matches, {n_stack} had all-in C &lt; $1 (stack-eligible on live; <em>not</em> added to P&amp;L here).</li>
<li>MAX_OPEN_B_MATCHES is not a sim filter. If every control-sent match could be open at once, peak overlap on this tape was
<strong>{concurrent}</strong> (footnote, not a cap). Live code currently uses 4; Paul mentioned 2 — neither is applied here.</li>
<li>Fills at the qualifying Yes ask. Tape already drops unsized Polymarket/Novig asks at ingest. We do not invent size.</li>
</ul>

<h2>Universe</h2>
<p>Trusted two-sided after venue-dedup: {len(books)}.
Settled non-void {settled_n}. Void {void_n}. Pending {pending_n}.
Venue copies dropped {counts.get('venue_dropped')}.
Novig-only after dedup {counts.get('novig_only_after_dedup')} (with-fee skip if sent).
Totals two-sided included {counts.get('totals_two_sided')}; one-sided totals skipped {counts.get('totals_one_sided')}.
Sports: {esc(', '.join(sports_present) or 'none')}.
Tape {esc(meta.get('seen_min') or '')} .. {esc(meta.get('seen_max') or '')}
({meta.get('n_lines')} lines, {meta.get('n_yes')} Yes ticks).</p>
<p class="note">Annualized rate of return (Ann ROR) uses house
<code>compare_format.ann_ror_from_closed</code> =
<code>((1 + total_pnl / (brt_cash × n_trades)) ** (365 / avg_days_held) − 1) × 100</code>.
Same-day contracts: avg hold is hours, not days, so Ann ROR is <strong>omitted</strong> on full / IS / OOS
(IS N=0 because every T0 is 2026 ≥ 2024-01-01). Calmar is n/a without Ann ROR.
Max DD $ is the peak-to-trough of cumulative with-fee P&amp;L. Paul Score / FIT / BRT exit mix do not apply.</p>

{''.join(sport_sections)}

<h2>One-knob slices (diagnostic — do not pick a winner from these)</h2>
<p class="note">fav&lt;70-only still uses live C_HI 1.20. C-only slices allow any favorite. Combined AND is Candidate A/B.
Slices exist so the AND is honest.</p>
{section_table(books, PRIMARY_ARMS, "All sports — slices sit in the same table as combined arms", "")}
{section_table(tennis, PRIMARY_ARMS, "Tennis — including slices", "")}

<h2>All-in C sensitivity</h2>
<p class="note">{allin_note} All-in computed on {n_allin} books; unknown on {n_no_allin} (Novig / missing schedule).</p>
{section_table(books, ALLIN_ARMS, "All sports — all-in gates for 1.04 / 1.09", "")}
{section_table(tennis, ALLIN_ARMS, "Tennis — all-in gates", "")}

<h2>Canonical compare notes</h2>
<ul>
<li>Book metrics above: N, wins/losses, win%, net P&amp;L $, expectancy $, avg win/loss $, PF, Ann ROR (omitted, reason stated), Max DD $, Calmar n/a, Sharpe (exit-date equity, rf=0, when dates exist), capital days, avg hours held, losing streak, AVG_PNL_PCT_WO_MAX.</li>
<li>Not applicable (BRT sheet): Paul Score, FIT / robust FIT, exit mix TARGET/STOP, trades/year on equities, sheet PnL. Labeled n/a, not invented.</li>
<li>Do not judge on max single-trade PnL (column kept, not primary).</li>
</ul>

<h2>Pending (not scored)</h2>
<p class="note">{n_pending} pending trusted two-sided after dedup. Showing up to 40, newest T0 first.</p>
{html_table(
    [("Sport","text"),("Game","text"),("Market","text"),("Line","text"),("Venue","text"),
     ("T0 date","date"),("T0 fav Yes","num"),("Wire C","num"),("All-in C","text")],
    pending_table,
    set(),
)}

<h2>Per-match scored paths</h2>
<p class="note">{n_match} settled non-void match-markets. skip = T0 gate did not send. Click headers to sort.</p>
{html_table(
    [("Sport","text"),("Game","text"),("Market","text"),("Line","text"),("Venue","text"),
     ("T0 date","date"),("T0 fav","num"),("Wire C","num"),("All-in C","num"),("T0 fav won","text"),
     ("Control net $","text"),("A fav70∧1.04 $","text"),("B fav70∧1.09 $","text"),("Control mix","text")],
    match_table,
    set(),
)}

<h2>What we could not score</h2>
<ul>
<li>Pending games (listed, not in P&amp;L).</li>
<li>Voids / pushes / both-win conflicts (N_void={void_n}).</li>
<li>One-sided Yes, extra-side (not two complementary) books, no trusted clock, clock-hides-match.</li>
<li>Novig with-fee P&amp;L when fee coefficient is missing.</li>
<li>Live stacking P&amp;L (SIZE=1 primary). Live MAX_OPEN cap (not applied).</li>
<li>Ann ROR / Calmar on same-day contracts. IS slice (N=0).</li>
<li>Ask size as a separate field on jsonl ticks — ingest already required positive size for some venues; we do not invent missing size.</li>
</ul>
<p class="tiny">Generator: <code>tools/strategy_b_tighten_fav70_c104_c109_20261024.py</code>.
Tests: <code>tools/test_strategy_b_tighten_fav70_c104_c109_20261024.py</code>.
T0 shared with <code>tools/t0_all_games_stats.py</code>. B cross/dip shared with
<code>tools/strategy_b_t0_plus_50cross_20261023.py</code> / dense B. Fees:
<code>write_t0_band_from_stay_above.documented_leg_fee</code>.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    STAMP.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(html, encoding="utf-8")
    write_baseline(meta, verdict, live)
    write_ab_plan()
    payload = {
        "built_at": iso_now(),
        "verdict": verdict,
        "live": live,
        "file_url": FILE_URL,
        "all_sports": {
            "control": {k: ctrl_all[k] for k in ("n_scored", "n_sent", "net_pnl", "expectancy", "win_pct", "fav_win_pct", "n_cross", "n_dip", "fees")},
            "a": {k: a_all[k] for k in ("n_scored", "n_sent", "net_pnl", "expectancy", "win_pct", "fav_win_pct", "n_cross", "n_dip", "fees")},
            "b": {k: b_all[k] for k in ("n_scored", "n_sent", "net_pnl", "expectancy", "win_pct", "fav_win_pct", "n_cross", "n_dip", "fees")},
        },
        "tennis": {
            "control": {k: ctrl_t[k] for k in ("n_scored", "n_sent", "net_pnl", "expectancy", "n_cross", "n_dip")},
            "a": {k: a_t[k] for k in ("n_scored", "n_sent", "net_pnl", "expectancy")},
            "b": {k: b_t[k] for k in ("n_scored", "n_sent", "net_pnl", "expectancy")},
        },
        "sports": sports_present,
        "concurrent_control": concurrent,
        "n_stack_eligible": n_stack,
        "all_in_computed": n_allin,
        "all_in_unknown": n_no_allin,
        "meta": {k: meta[k] for k in meta if k != "sports"} | {"sports": sports_present},
        "by_sport": {},
    }
    for sport in sports_present:
        subset = filter_sport(books, sport)
        payload["by_sport"][sport] = {
            "control": summarize_arm(subset, ARM_CONTROL)["net_pnl"],
            "n_control": summarize_arm(subset, ARM_CONTROL)["n_scored"],
            "a": summarize_arm(subset, ARM_FAV70_C104)["net_pnl"],
            "n_a": summarize_arm(subset, ARM_FAV70_C104)["n_scored"],
            "b": summarize_arm(subset, ARM_FAV70_C109)["net_pnl"],
            "n_b": summarize_arm(subset, ARM_FAV70_C109)["n_scored"],
        }
    ARMS_JSON.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    _out(f"wrote {PAGE}")
    _out(f"verdict {verdict}")


def main() -> int:
    STAMP.mkdir(parents=True, exist_ok=True)
    books, meta = load_universe()
    _out("simulating arms")
    run_all_arms(books)
    write_html(books, meta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
