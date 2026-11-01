"""New prediction-system proposals — quick backtest on the Oct 17–24 tape.

Research only. Does not place, cancel, or amend orders. Does not print secrets.
Does not start live_strategy_b.py. Does not sell. Does not wire any live system.
Does not change C_HI, FOK, hard-first, leftover deadline, or GTC. Not gold.
Not DailyRun.

Proposals are distinct from live A (lock), B (tennis both-Yes + 50-cross + dip),
C (CFB moneyline T0 fav in (0.50, 0.90)), D (one spread per game, same band).
"""
from __future__ import annotations

import html as html_mod
import json
import math
import statistics
import sys
from collections import defaultdict
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
import t0_all_games_stats as t0
from t0_fav_lt90_baseline_20261024 import (
    COMPARE_HEADERS,
    VENUE_RANK,
    eligible_books,
    fav_yes_pnl,
    html_table,
    pick_primary,
    quality,
    quality_row,
)
from write_t0_band_from_stay_above import documented_leg_fee

ET = ZoneInfo("America/New_York")
PARENT = (
    ROOT / "drive" / "paul_experiments"
    / "prediction_market_arb_exhaustive_20261017"
)
STAMP = PARENT / "new_systems_backtest_20261024"
PAGE = STAMP / "compare.html"
BASELINE = STAMP / "BASELINE.md"
AB_PLAN = STAMP / "AB_PLAN.md"
ARMS_JSON = STAMP / "arms.json"
SCORE_JSON = STAMP / "scorecard.json"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/new_systems_backtest_20261024/compare.html"
)
IS_CUT = "2024-01-01"
MIN_DAYS_FOR_ANN = 0.05
DOC_FEE_VENUES = {"Kalshi", "Gemini", "Polymarket"}
CROSS = 0.50
ABSORB = 0.05
YES_LO = 0.50
YES_HI = 0.90
SKIP_COIN_LO = 0.70
TINY_N = 8

ASKED = (
    "Deep dive with all data collected. Come up with a few proposals for other "
    "systems that may make money. Put them through a quick backtest. Show results."
)
PLAIN = (
    "Live bots today are four different bets: a two-shop lock that tries to buy "
    "both sides of the same result for less than a dollar (A); tennis that buys "
    "both players at the first trusted start (T0) then later tries a 50-cent "
    "crossover (B); college-football moneyline that buys the starting favorite "
    "between 50 and 90 cents (C); and one spread line per game in that same "
    "band (D). This page does not copy those. It asks whether five other rules "
    "would have made money on this week’s collected prices, size 1 contract, "
    "fees in, settled games only. Soccer moneyline is C’s rule on soccer. "
    "Totals is D’s “one line per game” idea on over/unders (this tape could not "
    "form a two-sided documented-fee book). Tennis T0 dog buys the cheaper player "
    "at the first trusted start with no both-Yes ticket. Tennis dog-only 50-cross "
    "waits until that underdog prints above 50 cents from below. Football skip-coin-flips is C’s band but "
    "only 70–89 cent favorites, on college and NFL moneyline. Missed-leg GTC "
    "asks whether leaving a resting buy on the shop that missed a lock would "
    "have beaten dumping the filled ticket (flatten). None of this is wired. "
    "The rules were chosen after looking at this week’s tape (selection bias)."
)

LIVE_INVENTORY = (
    ("A", "Lock gap", "Hard-first both-sides lock. Leftover watch, no 8AM deadline. Flatten-first. GTC not wired."),
    ("B", "Tennis crossover", "T0 both-Yes all-in C≤1.05, D=0.25 50-cross+dip, Poly FOK. Tennis moneyline."),
    ("C", "CFB favorite", "College football moneyline T0 fav in (0.50, 0.90), best venue, hold to settle."),
    ("D", "T0 spreads", "One spread per game, T0 fav in (0.50, 0.90), any sport with spreads. Totals skipped."),
)


def esc(value) -> str:
    return html_mod.escape("" if value is None else str(value))


def iso_now() -> str:
    return datetime.now(ET).isoformat()


def norm_kind(value) -> str:
    kind = str(value or "moneyline").strip().lower()
    if kind in {"total", "totals", "over_under", "over/under", "ou", "over-under"}:
        return "total"
    if kind in {"spread", "spreads"}:
        return "spread"
    if kind in {"moneyline", "ml", "h2h", ""}:
        return "moneyline"
    return kind


def norm_sport(value) -> str:
    sport = " ".join(str(value or "unknown").lower().split())
    if sport in {"nfl", "pro football", "football"}:
        return "pro football"
    if sport in {"nhl", "pro hockey", "hockey"}:
        return "pro hockey"
    if sport in {"cfb", "ncaaf", "college football"}:
        return "college football"
    if sport.startswith("tennis"):
        return "tennis"
    return sport or "unknown"


def in_open_band(px, lo: float = YES_LO, hi: float = YES_HI) -> bool:
    if px is None:
        return False
    return lo + 1e-12 < float(px) < hi - 1e-12


def in_skip_coin_band(px) -> bool:
    if px is None:
        return False
    return SKIP_COIN_LO - 1e-12 <= float(px) < YES_HI - 1e-12


def fee_for(venue: str, px) -> Decimal | None:
    return documented_leg_fee(str(venue or ""), px)


def yes_trade(*, ask, fee, won: bool, book: dict, arm_id: str, extra: dict | None = None) -> dict | None:
    if ask is None:
        return None
    fee_known = fee is not None
    if not fee_known:
        return None
    pnl = fav_yes_pnl(ask, fee, won=won)
    cost = Decimal(str(ask)) + Decimal(str(fee))
    pnl_pct = (float(pnl) / float(cost) * 100.0) if cost > 0 else None
    t0_ts = book.get("t0_ts")
    end_ts = book.get("end_ts") or t0_ts
    days = 0.0
    opened = closed = None
    if t0_ts is not None:
        opened = datetime.fromtimestamp(int(t0_ts), ET)
        if end_ts is not None:
            closed = datetime.fromtimestamp(int(end_ts), ET)
            days = max(0.0, (int(end_ts) - int(t0_ts)) / 86400.0)
        else:
            closed = opened
    row = {
        "arm": arm_id,
        "sport": norm_sport(book.get("sport")),
        "kind": norm_kind(book.get("kind") or book.get("market_type")),
        "venue": str(book.get("venue") or ""),
        "game": book.get("game") or "",
        "game_n": book.get("game_n") or "",
        "number": book.get("number") or "",
        "t0_fav": book.get("t0_fav"),
        "ask": float(ask),
        "fee": float(fee),
        "fee_known": True,
        "cost": float(cost),
        "won": bool(won),
        "pnl_d": float(pnl),
        "pnl": pnl_pct,
        "days": days,
        "opened": opened,
        "closed": closed,
        "entry_date": opened.date().isoformat() if opened else "",
        "be": float(cost),
        "grain": book.get("_grain") or "match",
        "two_sided": True,
    }
    if extra:
        row.update(extra)
    return row


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
    """Trungelliti rewind: if already >50 at T0, wait for a ≤50 print, then the next >50."""
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


def tagged_books(books: list[dict]) -> list[dict]:
    out = []
    for book in books:
        row = dict(book)
        row["sport"] = norm_sport(row.get("sport"))
        row["kind"] = norm_kind(row.get("kind") or row.get("market_type"))
        out.append(row)
    return out


def filter_books(
    books: list[dict],
    *,
    sports: tuple[str, ...] | None = None,
    kind: str | None = None,
) -> list[dict]:
    out = []
    for book in books:
        if sports and norm_sport(book.get("sport")) not in sports:
            continue
        if kind and norm_kind(book.get("kind") or book.get("market_type")) != kind:
            continue
        out.append(book)
    return out


def pick_one_closest_50(books: list[dict]) -> list[dict]:
    """One line per (sport, game): qualifying unique-fav book whose T0 fav is closest to 50¢."""
    bags: dict[tuple, list[dict]] = defaultdict(list)
    for book in books:
        t0_fav = book.get("t0_fav")
        if t0_fav is None:
            continue
        key = (norm_sport(book.get("sport")), str(book.get("game_n") or book.get("game") or ""))
        bags[key].append(book)
    out = []
    for _key, group in bags.items():
        group = sorted(
            group,
            key=lambda b: (
                abs(float(b.get("t0_fav")) - YES_LO),
                str(b.get("number") or ""),
                VENUE_RANK.get(str(b.get("venue") or ""), 9),
            ),
        )
        chosen = dict(group[0])
        chosen["_n_lines"] = len(group)
        out.append(chosen)
    return out


def directional_trades(books: list[dict], arm_id: str, *, band: str) -> list[dict]:
    out = []
    for book in books:
        t0_fav = book.get("t0_fav")
        if t0_fav is None:
            continue
        px = float(t0_fav)
        if band == "always":
            ok = px > YES_LO + 1e-12
        elif band == "c_band":
            ok = in_open_band(px)
        elif band == "skip_coin":
            ok = in_skip_coin_band(px)
        else:
            ok = False
        if not ok:
            continue
        fee = fee_for(str(book.get("venue") or ""), px)
        trade = yes_trade(
            ask=px,
            fee=fee,
            won=bool(book.get("fav_won")),
            book=book,
            arm_id=arm_id,
        )
        if trade:
            out.append(trade)
    return out


def dog_ticks(book: dict) -> list[tuple[int, float]]:
    dog = book.get("dog")
    if dog == "a":
        return list(book.get("yes_a") or [])
    if dog == "b":
        return list(book.get("yes_b") or [])
    return []


def tennis_dog_t0_trade(book: dict) -> dict | None:
    t0_dog = book.get("t0_dog")
    if t0_dog is None:
        return None
    fee = fee_for(str(book.get("venue") or ""), t0_dog)
    won = book.get("winner") == book.get("dog")
    return yes_trade(
        ask=t0_dog,
        fee=fee,
        won=bool(won),
        book=book,
        arm_id="tennis_t0_dog",
        extra={"fill_src": "t0_dog", "t0_dog": float(t0_dog)},
    )


def tennis_dog_cross_trade(book: dict) -> dict | None:
    t0_ts = book.get("t0_ts")
    end_ts = book.get("end_ts") or t0_ts
    t0_dog = book.get("t0_dog")
    if t0_ts is None or end_ts is None or t0_dog is None:
        return None
    cross = first_cross_from_below(dog_ticks(book), int(t0_ts), int(end_ts), float(t0_dog))
    if cross is None:
        return None
    ask = float(cross["px"])
    fee = fee_for(str(book.get("venue") or ""), ask)
    won = book.get("winner") == book.get("dog")
    trade = yes_trade(
        ask=ask,
        fee=fee,
        won=bool(won),
        book=book,
        arm_id="tennis_dog_50cross",
        extra={
            "fill_src": "dog_50cross",
            "t0_dog": float(t0_dog),
            "cross_ts": cross["ts"],
            "t0_already_above": bool(cross.get("t0_already_above")),
        },
    )
    if trade is None:
        return None
    opened = datetime.fromtimestamp(int(cross["ts"]), ET)
    trade["opened"] = opened
    trade["entry_date"] = opened.date().isoformat()
    if trade.get("closed") and trade["closed"] >= opened:
        trade["days"] = max(0.0, (trade["closed"] - opened).total_seconds() / 86400.0)
    return trade


def gtc_policy_trades(misses: list[dict]) -> tuple[list[dict], list[dict], dict]:
    """Control = actual flatten/leftover. Candidate = GTC lock P&L when the ask came back, else actual."""
    gtc_mod = __import__("_write_lock_missed_leg_gtc_20261024")
    control: list[dict] = []
    candidate: list[dict] = []
    stats = {
        "n_misses": len(misses),
        "n_scored": 0,
        "n_gtc_used": 0,
        "n_fallback_actual": 0,
        "n_unscored": 0,
        "n_hit": 0,
        "n_legal": 0,
    }
    for i, row in enumerate(misses):
        if row.get("game_status") not in {"settled", "void"}:
            stats["n_unscored"] += 1
            continue
        act, act_why = gtc_mod.actual_pnl(row)
        gtc_pnl = row.get("gtc_pnl")
        hit = bool(row.get("gtc_hit"))
        if hit:
            stats["n_hit"] += 1
        if row.get("legal_lock"):
            stats["n_legal"] += 1
        if act is None:
            stats["n_unscored"] += 1
            continue
        start = row.get("start")
        until = row.get("window_until") or start
        opened = start if isinstance(start, datetime) else None
        closed = until if isinstance(until, datetime) else opened
        days = 0.0
        if opened and closed:
            days = max(0.0, (closed - opened).total_seconds() / 86400.0)
        entry_date = opened.date().isoformat() if opened else ""
        act_f = float(act)
        ctrl = {
            "arm": "actual_flatten_leftover",
            "sport": norm_sport(row.get("sport")),
            "kind": "lock_one_leg",
            "venue": str((row.get("fill") or {}).get("venue") or ""),
            "game": row.get("game") or "",
            "game_n": row.get("game") or "",
            "number": "",
            "ask": None,
            "fee": 0.0,
            "fee_known": True,
            "cost": abs(act_f) if abs(act_f) > 1e-12 else 1.0,
            "won": act_f > 1e-12,
            "pnl_d": act_f,
            "pnl": None,
            "days": days,
            "opened": opened,
            "closed": closed,
            "entry_date": entry_date,
            "be": 1.0,
            "grain": "one_leg",
            "why": act_why,
        }
        use_gtc = hit and gtc_pnl is not None
        cand_pnl = float(gtc_pnl) if use_gtc else act_f
        cand = dict(ctrl)
        cand["arm"] = "gtc_then_actual"
        cand["pnl_d"] = cand_pnl
        cand["won"] = cand_pnl > 1e-12
        cand["cost"] = abs(cand_pnl) if abs(cand_pnl) > 1e-12 else 1.0
        cand["why"] = "gtc_lock" if use_gtc else f"fallback {act_why}"
        if ctrl["pnl"] is None and ctrl["cost"]:
            ctrl["pnl"] = (ctrl["pnl_d"] / ctrl["cost"] * 100.0) if ctrl["cost"] else None
        if cand["pnl"] is None and cand["cost"]:
            cand["pnl"] = (cand["pnl_d"] / cand["cost"] * 100.0) if cand["cost"] else None
        control.append(ctrl)
        candidate.append(cand)
        stats["n_scored"] += 1
        if use_gtc:
            stats["n_gtc_used"] += 1
        else:
            stats["n_fallback_actual"] += 1
    return control, candidate, stats


def load_gtc_misses() -> list[dict]:
    gtc_mod = __import__("_write_lock_missed_leg_gtc_20261024")
    flatten = gtc_mod.flatten
    oneleg = gtc_mod.oneleg
    print("scoring lock missed-leg GTC vs flatten (orders tape, not a second sports scan)", flush=True)
    misses, _counts = oneleg.build_events()
    events = oneleg.load_jsonl(gtc_mod.RAW / "orders.jsonl")
    gtc_mod.attach_ask_ticks(misses)
    flatten.attach_game_yes_ticks(misses)
    watch_stats = flatten.load_jsonl(gtc_mod.RAW / "leftover_watch_stats.jsonl")
    settlements = gtc_mod.load_settlements()
    for row in misses:
        row["flat_attempt"] = flatten.flatten_attempt_of(row, events)
        row["watch"] = flatten.leftover_watch_of(row, watch_stats)
        row["hold"] = flatten.hold_to_settle(row, settlements)
        gtc_mod.classify_game(row, settlements)
        gtc_mod.score_gtc(row)
    return misses


def judge(control: dict, cand: dict, *, tiny: int = TINY_N) -> tuple[str, str]:
    n_c = int(cand.get("n") or 0)
    n_k = int(control.get("n") or 0)
    if n_c <= 0:
        return "DISMISS", "N=0 on this tape after settled + documented-fee filters."
    mean_k = control.get("mean")
    mean_c = cand.get("mean")
    wr_k = control.get("win_pct")
    wr_c = cand.get("win_pct")
    pf_k = control.get("pf")
    pf_c = cand.get("pf")
    wo_k = control.get("avg_pnl_pct_wo_max")
    wo_c = cand.get("avg_pnl_pct_wo_max")
    better = worse = 0
    for a, b in ((mean_k, mean_c), (wr_k, wr_c), (pf_k, pf_c), (wo_k, wo_c)):
        if a is None or b is None:
            continue
        if b > a + 1e-12:
            better += 1
        elif b < a - 1e-12:
            worse += 1
    collapsed = n_k >= tiny * 2 and n_c < max(tiny, int(0.4 * n_k))
    mean_up = mean_c is not None and mean_k is not None and float(mean_c) > float(mean_k) + 1e-12
    mean_down = mean_c is not None and mean_k is not None and float(mean_c) < float(mean_k) - 1e-12
    tiny_note = f" Tiny N={n_c}." if n_c < tiny else ""
    bias = " Selection bias: proposed after this week’s tape. Not gold. Not DailyRun. Not a wire."
    if mean_down or worse > better:
        return (
            "DISMISS",
            f"Quality does not beat the control (with-fee mean $ / WR / PF).{tiny_note}{bias}",
        )
    if not mean_up:
        return (
            "HOLD",
            f"Flat vs control on with-fee mean $. Do not KEEP.{tiny_note}{bias}",
        )
    if collapsed:
        return (
            "HOLD",
            f"Mean $ is up but N collapsed {n_k} → {n_c}; judge quality, not a thinner lucky book.{bias}",
        )
    n_loss = int(cand.get("n_loss") or 0)
    if n_c < 10 and n_loss == 0:
        return (
            "HOLD",
            f"Mean $ is up on a perfect N={n_c} week with no losses. That is not quality evidence.{bias}",
        )
    if n_c < tiny or better < 3:
        return (
            "LEAN KEEP (research only)",
            f"With-fee mean $ improves vs control, but sample is small or mixed on WR/PF.{tiny_note}{bias}",
        )
    if n_c >= 20 and better >= 3:
        return (
            "KEEP (research only)",
            f"With-fee quality improves vs control on N≥20 without collapsing N. Still not gold, not DailyRun, not a wire.{tiny_note}{bias}",
        )
    return (
        "LEAN KEEP (research only)",
        f"With-fee quality improves vs control without collapsing N. Still research-only.{tiny_note}{bias}",
    )


def q_for(trades: list[dict], arm_id: str, label: str, grain: str) -> dict:
    got = quality(trades, arm_id=arm_id, label=label, grain=grain)
    avg_days = got.get("avg_days")
    if avg_days is None or float(avg_days) < MIN_DAYS_FOR_ANN or float(avg_days) < 1.0:
        got["ann_ror"] = None
        got["ann_ror_oos"] = None
        got["ann_ror_is"] = None
        got["calmar"] = None
        got["ann_note"] = (
            f"Ann ROR omitted — average days held is "
            f"{avg_days if avg_days is not None else 0:.4f} "
            f"(same-day contracts; house compare_format.ann_ror_from_closed would "
            f"overflow on a near-zero hold). IS N={got.get('n_is') or 0} "
            f"(all T0 ≥ {IS_CUT}; this tape is 2026)."
        )
        if not got.get("is_note"):
            got["is_note"] = f"n/a — no IS (all T0 ≥ {IS_CUT}; this tape is 2026)"
    return got


def proposal_block(
    *,
    pid: str,
    title: str,
    one_liner: str,
    control: dict,
    candidate: dict,
    verdict: str,
    why: str,
    extra_html: str = "",
) -> str:
    rows = [
        quality_row(control, None),
        quality_row(candidate, control),
    ]
    klass = "hold"
    if verdict.startswith("LEAN KEEP") or verdict.startswith("KEEP"):
        klass = "ok"
    elif verdict.startswith("DISMISS"):
        klass = "warn"
    return f"""
<div class="callout {klass}">
<h2>{esc(pid)}. {esc(title)} — {esc(verdict)}</h2>
<p>{esc(one_liner)}</p>
<p>{esc(why)}</p>
</div>
{html_table(COMPARE_HEADERS, rows)}
{extra_html}
"""


def write_baseline(meta: dict, proposals: list[dict], killed: list[dict]) -> None:
    lines = [
        "# New system proposals — freeze",
        "",
        f"Written {iso_now()} ET. Research only. Not gold. Not DailyRun. Not a wire.",
        "",
        "## What you asked",
        "",
        ASKED,
        "",
        "## In plain English",
        "",
        PLAIN,
        "",
        "## Live inventory (do not re-propose)",
        "",
    ]
    for sid, name, rule in LIVE_INVENTORY:
        lines.append(f"- **{sid} {name}:** {rule}")
    lines += [
        "",
        "## Freeze",
        "",
        "- **T0:** first trusted serve (Kalshi/Gemini occurrence, else listed/feed with seconds=00). Same as living `t0_all_games_stats.py`. Not tape-resume. Not first-competitive.",
        "- **Favorite / dog:** higher / lower T0 Yes ask on that venue book. Skip 50-50.",
        "- **Grain:** one primary venue per (sport, game, market, line), rank Kalshi > Gemini > Polymarket > Novig. Totals then keep one line per game (closest T0 fav to 50¢), same as D’s one-spread pick.",
        "- **SIZE=1.** Taker at the Yes ask. Hold to settlement. Settled only. Voids out.",
        "- **Fees (primary P&L WITH fees):** Kalshi 0.07×p×(1−p) to $0.0001; Gemini same formula rounded up to a cent; Polymarket 0.0695×p×(1−p) banker's cent. Novig omitted (no documented coefficient).",
        "- **C band:** exclusive (0.50, 0.90), same as live C/D `in_fav_band`.",
        "- **Skip-coin band:** 0.70 ≤ T0 fav < 0.90.",
        "- **Tennis T0 dog:** buy 1 Yes on the T0 dog at the T0 ask. No both-Yes. No 50-cross. No dip.",
        "- **Tennis dog 50-cross:** first from-below 50¢ print on the T0 dog (Trungelliti rewind). No T0 both-Yes. No favorite dip. No D. One-change vs T0 dog.",
        "- **GTC:** research counterfactual on lock-bot one-legs. Hit = later missed-shop ask ≤ intended REST ask. Candidate uses complementary GTC lock P&L when that hit exists, else the actual flatten/leftover. Does not rest or wire GTC.",
        "- **IS / OOS:** IS = entry_date < 2024-01-01; OOS = entry_date ≥ 2024-01-01. This tape is all 2026 — IS N=0. Same-day: omit Ann ROR (avg days held < 1). House formula `compare_format.ann_ror_from_closed` only.",
        "- **Selection bias:** proposals chosen after seeing this week’s tape. Judge quality over N. Do not retune. Do not wire.",
        "- **Live knobs unchanged:** C_HI 1.05, FOK, hard-first, leftover deadline, no second `live_strategy_b.py`, no sells, no new live system.",
        "",
        "## Tape window",
        "",
    ]
    meta_s = meta or {}
    lines.append(f"- Stream: {esc(meta_s.get('n_lines'))} lines, Yes ticks {esc(meta_s.get('n_yes'))}, sides {esc(meta_s.get('n_sides'))}.")
    lines.append(f"- Seen {esc(meta_s.get('seen_min'))} .. {esc(meta_s.get('seen_max'))}.")
    lines.append("")
    lines.append("## Killed before a KEEP")
    lines.append("")
    for row in killed:
        lines.append(f"- **{row['id']}:** {row['why']}")
    lines.append("")
    lines.append("## Verdicts")
    lines.append("")
    for p in proposals:
        lines.append(
            f"- **{p['id']} {p['title']}:** {p['verdict']} — "
            f"candidate {format_money(p['candidate']['pnl_sum'])} N={p['candidate']['n']} "
            f"vs control {format_money(p['control']['pnl_sum'])} N={p['control']['n']}."
        )
    lines.append("")
    lines.append("See compare.html. Nothing wired.")
    lines.append("")
    STAMP.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text("\n".join(lines), encoding="utf-8")


def write_ab_plan(proposals: list[dict], killed: list[dict]) -> None:
    lines = [
        "# AB_PLAN — new system proposals 24 Oct 2026",
        "",
        "One hypothesis per arm. Frozen knobs in BASELINE.md. Quick backtest on the Oct 17–24 collection. Research only. Not gold. Not DailyRun. Do not wire.",
        "",
        "## Live systems we do not re-propose",
        "",
        "A lock, B tennis crossover (T0 both-Yes + dog 50-cross + fav dip), C CFB ML T0 fav (0.50, 0.90), D one spread per game T0 fav (0.50, 0.90).",
        "",
        "## Arms we scored",
        "",
        "| ID | Proposal | Control | Distinct from |",
        "|----|----------|---------|---------------|",
        "| P1 | Soccer ML T0 fav in (0.50, 0.90), best venue, hold to settle | Always soccer ML T0 fav (>0.50) | C is CFB-only |",
        "| P2 | Tennis T0 dog at T0 ask, no both-Yes, hold to settle | Tennis T0 favorite at T0 ask | B buys both Yes; tennis T0 fav is a known wreck |",
        "| P3 | Tennis dog-only first from-below 50-cross, no T0 both-Yes | Buy T0 tennis dog at T0 ask | One-change vs P2: wait for 50-cross |",
        "| P4 | NFL+CFB moneyline T0 fav ≥0.70 and <0.90 | Same universe, C band (0.50, 0.90) | C did not skip coin-flips; C is CFB-only |",
        "| P5 | Missed-leg GTC at intended ask when it would have hit, else actual flatten/leftover | Actual flatten/leftover P&L | A flattens; GTC is not wired |",
        "",
        "## Dropped by the tape (not a headline arm)",
        "",
    ]
    for row in killed:
        lines.append(f"- **{row['id']}:** {row['why']}")
    lines += [
        "",
        "## Judge",
        "",
        "Primary: with-fee net $, mean $/trade, win%, profit factor, Max DD $, N. Not max single-trade PnL. KEEP / LEAN KEEP only if quality improves without collapsing N; flat → HOLD; worse → DISMISS. Ann ROR omitted on same-day holds. IS N=0 (all 2026). Selection bias labeled. **Do not retune. Do not wire.**",
        "",
        "## Verdicts this stamp",
        "",
    ]
    for p in proposals:
        lines.append(f"- **{p['id']}:** {p['verdict']}")
    lines.append("")
    STAMP.mkdir(parents=True, exist_ok=True)
    AB_PLAN.write_text("\n".join(lines), encoding="utf-8")


def write_html(
    *,
    meta: dict,
    proposals: list[dict],
    killed: list[dict],
    inventory_note: str,
    slices: dict[str, list[list[str]]],
) -> Path:
    sport_rows = slices.get("sports") or []
    headline_headers = [
        ("Proposal", "text"),
        ("Trigger", "text"),
        ("Control N / $", "text"),
        ("Candidate N", "num"),
        ("Candidate net $", "num"),
        ("Mean $", "num"),
        ("Win %", "num"),
        ("PF", "num"),
        ("Max DD $", "num"),
        ("Ann ROR full", "text"),
        ("Ann ROR IS", "text"),
        ("Ann ROR OOS", "text"),
        ("Verdict", "text"),
    ]
    headline = []
    for p in proposals:
        c = p["candidate"]
        k = p["control"]
        headline.append([
            esc(f"{p['id']} {p['title']}"),
            esc(p["trigger"]),
            f"{k['n']} / {format_money(k['pnl_sum'])}",
            str(c.get("n") or 0),
            format_money(c.get("pnl_sum")),
            format_money(c.get("mean")),
            f"{c['win_pct']:.1f}" if c.get("win_pct") is not None else "—",
            f"{c['pf']:.2f}" if c.get("pf") is not None else "—",
            format_money(c.get("max_dd_d")),
            "omitted (same-day)" if c.get("ann_note") else (f"{c['ann_ror']:.1f}" if c.get("ann_ror") is not None else "—"),
            "n/a (IS N=0, all 2026)" if c.get("is_note") else (f"{c['ann_ror_is']:.1f}" if c.get("ann_ror_is") is not None else "—"),
            "omitted (same-day)" if c.get("ann_note") else (f"{c['ann_ror_oos']:.1f}" if c.get("ann_ror_oos") is not None else "—"),
            esc(p["verdict"]),
        ])
    detail = "".join(
        proposal_block(
            pid=p["id"],
            title=p["title"],
            one_liner=p["one_liner"],
            control=p["control"],
            candidate=p["candidate"],
            verdict=p["verdict"],
            why=p["why"],
            extra_html=p.get("extra_html") or "",
        )
        for p in proposals
    )
    killed_html = "".join(f"<p><strong>{esc(row['id'])}.</strong> {esc(row['why'])}</p>" for row in killed)
    inv_rows = [[esc(a), esc(b), esc(c)] for a, b, c in LIVE_INVENTORY]
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
{report_page_extras.CACHE_META}
{report_page_extras.FORCE_RELOAD_SCRIPT}
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>New system proposals — 24 Oct 2026</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.1rem; margin: 1.2rem 0 0.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; }}
.warn {{ background: #fff7ed; border-color: #fdba74; }}
.ok {{ background: #f0fdf4; border-color: #86efac; }}
.hold {{ background: #eef2ff; border-color: #a5b4fc; }}
.note {{ color: #475569; font-size: 14px; }}
.tiny {{ color: #64748b; font-size: 13px; }}
code {{ font-size: 0.9em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>New system proposals — quick backtest</h1>
<p class="note">Written {esc(now)}. America/New_York. Research only. Not gold. Not DailyRun. Did not wire. Did not sell. Did not start a second Strategy B. Did not change C_HI 1.05, FOK, hard-first, leftover deadline, or GTC. SIZE=1. Fees in. Settled only. Click column headers to sort.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="callout hold">
<h2>Selection bias · not a wire</h2>
<p>These rules were picked after looking at this week’s tape (T0 stats, stay-above, B-vs-lock, GTC 15/32). That is in-sample selection even though every trade is after 2024-01-01 (IS N=0). LEAN KEEP here is a research candidate, not gold, not DailyRun. Live A–D stay as they are.</p>
</div>

<h2>Already live — not proposed again</h2>
{html_table([("Sys", "text"), ("Name", "text"), ("Rule", "text")], inv_rows)}
<p class="note">{esc(inventory_note)}</p>

<h2>Headline (candidate vs its control)</h2>
<p class="note">Primary P&amp;L is with documented taker fees. Net $ is the 1-contract book, not a BRT sheet. Annualized rate of return uses <code>compare_format.ann_ror_from_closed</code>; same-day holds omit it. Swipe sideways to see more columns.</p>
{html_table(headline_headers, headline)}

<h2>What the tape could not support</h2>
{killed_html}

<h2>Each proposal (canonical book metrics)</h2>
<p class="note">Control row first, candidate second. Δ columns are candidate minus control. Total PnL $ is shown here because this is a 1-contract prediction-market book (Paul asked for net $); BRT sheet Total/Sheet PnL $ stay omitted on stock compares. Max DD % / Calmar / Sharpe sit on the $500,000 overlay; they are near zero at size 1. Judge mean $, WR, PF, Max DD $.</p>
{detail}

<h2>Tape coverage (settled unique-fav books, match grain, documented fee)</h2>
{html_table([("Sport", "text"), ("Market", "text"), ("N", "num"), ("T0 fav WR %", "num"), ("Always T0 fav net $", "num")], sport_rows)}

<p class="tiny">Generator: <code>tools/new_systems_backtest_20261024.py</code>. Living T0: <code>tools/t0_all_games_stats.py</code>. Fees: <code>write_t0_band_from_stay_above.documented_leg_fee</code>. GTC rows: <code>tools/_write_lock_missed_leg_gtc_20261024.py</code> (this page does not rewrite that HTML). Freeze: <a href="BASELINE.md">BASELINE.md</a> · <a href="AB_PLAN.md">AB_PLAN.md</a>. File URL {esc(FILE_URL)}</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    STAMP.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    return PAGE


def sport_coverage_rows(match_books: list[dict]) -> list[list[str]]:
    bags: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for book in match_books:
        bags[(norm_sport(book.get("sport")), norm_kind(book.get("kind")))].append(book)
    rows = []
    for (sport, kind), group in sorted(bags.items()):
        trades = directional_trades(group, "always", band="always")
        n = len(trades)
        n_win = sum(1 for t in trades if t.get("won"))
        wr = (100.0 * n_win / n) if n else None
        pnl = sum(float(t["pnl_d"]) for t in trades) if trades else 0.0
        rows.append([
            esc(sport),
            esc(kind),
            str(n),
            f"{wr:.1f}" if wr is not None else "—",
            format_money(pnl) if n else "—",
        ])
    return rows


def jsonable(obj):
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items() if k != "trades"}
    if isinstance(obj, list):
        return [jsonable(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


def pack(pid, title, trigger, one_liner, control, candidate, extra_html="") -> dict:
    verdict, why = judge(control, candidate)
    return {
        "id": pid,
        "title": title,
        "trigger": trigger,
        "one_liner": one_liner,
        "control": control,
        "candidate": candidate,
        "verdict": verdict,
        "why": why,
        "extra_html": extra_html,
    }


def run_proposals(match_books: list[dict], venue_books: list[dict]) -> tuple[list[dict], list[dict], dict]:
    killed: list[dict] = []
    tennis_fav = directional_trades(
        filter_books(match_books, sports=("tennis",), kind="moneyline"),
        "tennis_t0_fav",
        band="c_band",
    )
    tennis_q = q_for(tennis_fav, "tennis_t0_fav", "Tennis ML T0 fav in (0.50, 0.90)", "match")
    killed.append({
        "id": "Tennis T0 favorite in C’s band",
        "why": (
            f"Tape already killed all-sports T0 fav <90 (tennis wrecks it). "
            f"Tennis moneyline T0 fav in (0.50, 0.90) is "
            f"{format_money(tennis_q.get('pnl_sum'))} on N={tennis_q.get('n')} "
            f"WR {tennis_q.get('win_pct'):.1f}%." if tennis_q.get("win_pct") is not None else
            f"Tennis moneyline T0 fav in (0.50, 0.90) N={tennis_q.get('n')}. Not a new system."
        ),
    })
    killed.append({
        "id": "All-sports T0 fav <90 / C or D again",
        "why": (
            "All-sports T0 fav <90 was −$3.77 on the companion baseline; C is already CFB ML "
            "in (0.50, 0.90); D is already one spread per game in that band. Stay-above-50 is "
            "not a send trigger (incomplete-path bug is fixed; stay ≠ win rate). Immediate "
            "dual-fill 0/69 is not a new lock rule. Tight B fav<70 AND C≤1.04 is already HOLD. "
            "None of those is re-proposed."
        ),
    })

    hockey_books = filter_books(match_books, sports=("pro hockey",), kind="moneyline")
    hockey_always = directional_trades(hockey_books, "hockey_always", band="always")
    hockey_band = directional_trades(hockey_books, "hockey_c_band", band="c_band")
    hockey_c = q_for(hockey_always, "hockey_always", "Hockey ML always T0 fav", "match")
    hockey_b = q_for(hockey_band, "hockey_c_band", "Hockey ML T0 fav (0.50, 0.90)", "match")
    if (hockey_b.get("n") or 0) < TINY_N:
        killed.append({
            "id": "Hockey moneyline T0 fav in (0.50, 0.90)",
            "why": (
                f"Hockey ML is a real distinct sport from C, but this week’s settled documented-fee "
                f"book is N={hockey_b.get('n')} candidate / N={hockey_c.get('n')} always, "
                f"net {format_money(hockey_b.get('pnl_sum'))}. Too thin to KEEP a system. "
                f"Same C-band idea is scored on soccer (P1) where N is still small but larger."
            ),
        })
    else:
        killed.append({
            "id": "Hockey moneyline folded into soccer",
            "why": "Hockey ML N was large enough; see scorecard. Not dropped.",
        })

    soccer_books = filter_books(match_books, sports=("soccer",), kind="moneyline")
    p1 = pack(
        "P1",
        "Soccer moneyline T0 favorite",
        "Soccer ML T0 fav in (0.50, 0.90), best venue, hold to settle",
        "Same send as live C, on soccer instead of college football. Control is every soccer ML T0 favorite, including 90¢+ tickets.",
        q_for(directional_trades(soccer_books, "soccer_always", band="always"), "soccer_always", "Control · soccer ML always T0 fav", "match"),
        q_for(directional_trades(soccer_books, "soccer_c_band", band="c_band"), "soccer_c_band", "Candidate · soccer ML T0 fav (0.50, 0.90)", "match"),
    )

    total_lines = filter_books(match_books, kind="total")
    totals = pick_one_closest_50(total_lines)
    killed.append({
        "id": "One total per game (D skipped totals)",
        "why": (
            f"Two-sided unique-favorite documented-fee totals on match grain: "
            f"{len(total_lines)} lines / {len(totals)} games. "
            "The dashboard’s 100% T0-fav win rate on totals is not a C-band send book — "
            "most total Yes sides never pair into a two-sided unique favorite with a documented "
            "fee, or sit on Novig. Not implementable on this grain."
        ),
    })

    tennis_ml = filter_books(match_books, sports=("tennis",), kind="moneyline")
    t0_dog_trades = [t for t in (tennis_dog_t0_trade(b) for b in tennis_ml) if t]
    cross_trades = [t for t in (tennis_dog_cross_trade(b) for b in tennis_ml) if t]
    tennis_fav_always = directional_trades(tennis_ml, "tennis_t0_fav", band="always")
    p2 = pack(
        "P2",
        "Tennis T0 dog (no both-Yes)",
        "Buy the T0 tennis underdog at the T0 ask, hold to settle",
        "T0 stats scream this: tennis T0 favorites win about 43% and lose money after fees. Buying the cheaper Yes at T0 is the one-change vs that wreck. Not Strategy B (no both-Yes, no 50-cross, no dip).",
        q_for(tennis_fav_always, "tennis_t0_fav", "Control · tennis T0 favorite at T0 ask", "match"),
        q_for(t0_dog_trades, "tennis_t0_dog", "Candidate · tennis T0 dog at T0 ask", "match"),
    )
    p3 = pack(
        "P3",
        "Tennis dog-only 50-cross",
        "First from-below 50¢ on the T0 dog; no T0 both-Yes; hold to settle",
        "Paul’s old extra-dog idea without Strategy B’s opening both-Yes or the favorite dip. Control is P2’s T0 dog (one-change: wait for the 50-cross instead of taking the T0 ask).",
        q_for(t0_dog_trades, "tennis_t0_dog", "Control · tennis T0 dog at T0 ask", "match"),
        q_for(cross_trades, "tennis_dog_50cross", "Candidate · tennis dog first from-below 50-cross", "match"),
        extra_html=(
            f"<p class='note'>Tennis ML books {len(tennis_ml)}. Cross filled "
            f"{len(cross_trades)} / {len(tennis_ml)} "
            f"({(100.0 * len(cross_trades) / len(tennis_ml)):.1f}% had a from-below 50-cross).</p>"
            if tennis_ml else "<p class='note'>No tennis moneyline books.</p>"
        ),
    )

    fb_books = filter_books(match_books, sports=("college football", "pro football"), kind="moneyline")
    cfb_only = filter_books(match_books, sports=("college football",), kind="moneyline")
    nfl_only = filter_books(match_books, sports=("pro football",), kind="moneyline")
    cfb_ctrl = q_for(directional_trades(cfb_only, "cfb_c_band", band="c_band"), "cfb_c_band", "CFB ML C-band (live C universe)", "match")
    cfb_cand = q_for(directional_trades(cfb_only, "cfb_skip_coin", band="skip_coin"), "cfb_skip_coin", "CFB ML ≥0.70 &lt;0.90", "match")
    nfl_ctrl = q_for(directional_trades(nfl_only, "nfl_c_band", band="c_band"), "nfl_c_band", "NFL ML C-band", "match")
    nfl_cand = q_for(directional_trades(nfl_only, "nfl_skip_coin", band="skip_coin"), "nfl_skip_coin", "NFL ML ≥0.70 &lt;0.90", "match")
    slice_rows = [
        quality_row(cfb_ctrl, None),
        quality_row(cfb_cand, cfb_ctrl),
        quality_row(nfl_ctrl, None),
        quality_row(nfl_cand, nfl_ctrl),
    ]
    p4 = pack(
        "P4",
        "Football moneyline skip coin-flips",
        "NFL+CFB ML T0 fav ≥0.70 and <0.90 (skip 50–69¢)",
        "Live C already buys CFB moneyline in (0.50, 0.90) and does not skip coin-flips. This arm keeps the 90¢ cap, drops 50–69¢ tickets, and adds NFL moneyline. Control is the same NFL+CFB moneyline universe in C’s full (0.50, 0.90) band.",
        q_for(directional_trades(fb_books, "fb_c_band", band="c_band"), "fb_c_band", "Control · NFL+CFB ML T0 fav (0.50, 0.90)", "match"),
        q_for(directional_trades(fb_books, "fb_skip_coin", band="skip_coin"), "fb_skip_coin", "Candidate · NFL+CFB ML T0 fav ≥0.70 &lt;0.90", "match"),
        extra_html="<p class='note'>CFB-only and NFL-only slices (not used to pick the arm).</p>" + html_table(COMPARE_HEADERS, slice_rows),
    )

    gtc_stats = {}
    try:
        misses = load_gtc_misses()
        ctrl_t, cand_t, gtc_stats = gtc_policy_trades(misses)
        p5 = pack(
            "P5",
            "Missed-leg GTC instead of flatten",
            "Rest GTC at the intended missed-leg ask when the ask later ≤ limit; else keep actual flatten/leftover",
            "Research P&L versus what actually happened on lock-bot one-legs. Does not rest GTC. Cancel-on-resolve is still missing.",
            q_for(ctrl_t, "actual_flatten_leftover", "Control · actual flatten / leftover hold-to-settle", "one_leg"),
            q_for(cand_t, "gtc_then_actual", "Candidate · GTC lock P&L on hits, else actual", "one_leg"),
            extra_html=(
                f"<p class='note'>One-legs {gtc_stats.get('n_misses')}. Scored with known actual "
                f"P&amp;L {gtc_stats.get('n_scored')}. GTC used on {gtc_stats.get('n_gtc_used')} "
                f"(ask came back and complementary lock P&amp;L exists). Hits {gtc_stats.get('n_hit')}, "
                f"still ≤0.984 {gtc_stats.get('n_legal')}. Unscored (open/unknown actual) "
                f"{gtc_stats.get('n_unscored')}. Companion hit-rate page is "
                f"<a href='../lock_missed_leg_gtc_20261024.html'>lock_missed_leg_gtc_20261024.html</a> "
                f"(this job does not rewrite it).</p>"
            ),
        )
    except Exception as exc:
        p5 = pack(
            "P5",
            "Missed-leg GTC instead of flatten",
            "Rest GTC at the intended missed-leg ask",
            "Could not score GTC vs flatten on this run.",
            q_for([], "actual_flatten_leftover", "Control · actual flatten / leftover", "one_leg"),
            q_for([], "gtc_then_actual", "Candidate · GTC then actual", "one_leg"),
        )
        killed.append({
            "id": "GTC scorer error",
            "why": f"GTC vs flatten did not finish ({type(exc).__name__}). Not wired. See lock_missed_leg_gtc_20261024.html.",
        })
        gtc_stats = {"error": type(exc).__name__}

    proposals = [p1, p2, p3, p4, p5]
    extra = {
        "hockey_always": hockey_c,
        "hockey_c_band": hockey_b,
        "tennis_t0_fav_c_band": tennis_q,
        "gtc_stats": gtc_stats,
        "cfb_c_band": cfb_ctrl,
        "cfb_skip_coin": cfb_cand,
        "nfl_c_band": nfl_ctrl,
        "nfl_skip_coin": nfl_cand,
        "n_match": len(match_books),
        "n_venue": len(venue_books),
    }
    return proposals, killed, extra


def main() -> int:
    print("loading living T0 books (one sports-tape scan)", flush=True)
    payload = t0.build_payload()
    meta = payload.get("meta") or {}
    books = tagged_books(eligible_books(payload.get("books") or []))
    match_books = tagged_books(pick_primary(books))
    print(
        f"eligible two-sided settled unique-fav {len(books)} venue-games; "
        f"{len(match_books)} primary-venue matches",
        flush=True,
    )
    proposals, killed, extra = run_proposals(match_books, books)
    coverage = sport_coverage_rows(match_books)
    seen = meta.get("seen_min"), meta.get("seen_max")
    inventory_note = (
        f"Tape seen {seen[0]} .. {seen[1]}. Match-grain documented-fee unique-fav N={len(match_books)}."
    )
    write_baseline(meta, proposals, killed)
    write_ab_plan(proposals, killed)
    path = write_html(
        meta=meta,
        proposals=proposals,
        killed=killed,
        inventory_note=inventory_note,
        slices={"sports": coverage},
    )
    STAMP.mkdir(parents=True, exist_ok=True)
    ARMS_JSON.write_text(
        json.dumps({"proposals": jsonable(proposals), "extra": jsonable(extra)}, indent=2, default=str),
        encoding="utf-8",
    )
    SCORE_JSON.write_text(
        json.dumps({"killed": killed, "written_at": iso_now(), "meta": meta}, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"wrote {path}", flush=True)
    for p in proposals:
        c = p["candidate"]
        print(
            f"{p['id']} {p['verdict']} N={c.get('n')} pnl={c.get('pnl_sum')} mean={c.get('mean')}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
