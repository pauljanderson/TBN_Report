"""Strategy B D=25 vs D=45 vs t0_plus_first_50_cross on the frozen dense tennis book.

Research only. Reads local price_memory (archive + dated shards) and official
settlements. Does not place, cancel, or amend orders. Does not print secrets.
Does not touch orders_stopped.json or live_lock_orders. Does not start
live_strategy_b.py. Does not change live D=0.25. Not gold. Not DailyRun.

Same 182-book freeze as strategy_b_D_05_to_50_20261023. New stamp so the
misunderstood t0_only page is not silently mutated.

Primary P&L is WITH live-sender fees. Arm t0_plus_first_50_cross is T0 both
Yes, then one extra original-dog Yes at the first up-cross through 0.50 from
below, then stop. No original-favorite ticket at 1 − cross − D.
"""
from __future__ import annotations

import json
import math
import shutil
import sys
from decimal import ROUND_CEILING, ROUND_HALF_EVEN, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import report_page_extras
from compare_format import (
    DEFAULT_INITIAL_ACCOUNT,
    ann_ror_from_closed,
    format_money,
    overlay_ann_ror_max_dd,
)
from dense_inplay_fav_lock_cross_smalld_20261021 import (
    CROSS,
    ORIGINAL_N,
    ORIGINAL_PAGE,
    ORIGINAL_SETTLED,
    assign_favorite,
    b_fill_text,
    first_cross_yes,
    freeze_keys_from_original_html,
    pair_key,
    simulate_b_variant,
    ticks_of,
)
from dense_inplay_yes_dip_20261021 import (
    ABSORB,
    assign_actual_t0,
    attach_pair_results,
    esc,
    extras_payout,
    iso_now,
    mark_inplay,
    match_date,
    money_cell,
    pair_matches,
    signed_money,
    stream_tennis,
)
from inmatch_vol_hedge_20261021 import first_after
from odds_cross_no_roi_60_70_20261020 import table
from odds_cross_winrate_20261020 import pct, tiny_note
from polymarket_tennis_no_90plus_20261020 import load_catalog, load_settlements
from strategy_b_d_05_to_50_20261023 import (
    compare_row,
    dollar_drawdown,
    fmt_ann,
    fmt_num,
    fmt_pct,
    pair_closed,
    pair_days,
    pair_opened,
    pick_named,
    pnl_pct,
)
from tennis_decade_at_start_20261020 import start_lookup_from
from tennis_dual_yes_dip_no_20261021 import (
    et_iso,
    fmt_px,
    fmt_signed,
    last_name,
    mean,
    median,
)

STAMP = ROOT / "drive" / "paul_experiments" / "strategy_b_t0_plus_50cross_20261023"
PAGE = STAMP / "compare.html"
BASELINE = STAMP / "BASELINE.md"
ARMS_JSON = STAMP / "arms.json"
PRIOR_STAMP = ROOT / "drive" / "paul_experiments" / "strategy_b_D_05_to_50_20261023"
OLD_T0_STAMP = ROOT / "drive" / "paul_experiments" / "strategy_b_t0_only_vs_D45_20261023"
PRIOR_HTML = (
    ROOT
    / "drive"
    / "paul_experiments"
    / "prediction_market_arb_exhaustive_20261017"
    / "dense_inplay_fav_lock_cross_smalld_20261021.html"
)
CONTROL_D = 0.25
B_DIPS = (0.25, 0.45)
IS_CUT = "2024-01-01"
CENT = Decimal("0.01")
ONE = Decimal("1")
POLY_THETA = Decimal("0.0695")
ARM_T0PLUS = "t0_plus_first_50_cross"

ASKED = (
    "Paul corrected two things. Primary P&L must be WITH fees (Polymarket taker, "
    "Kalshi/Gemini/Novig as the live senders charge). He misunderstood t0_only. His "
    "intent is not buy both at T0 and never send again. It is: T0 buy both Yes (same C "
    "band, 1 contract, same T0 clock as live B). Then the first crossover from the "
    "bottom — original dog Yes rises through 0.50 from below for the first time — buy "
    "that crossing dog Yes (1 contract IOC at the cross ask). And that is it. Do not "
    "buy the original favorite / dropped opponent at 1 − cross − D. No third ticket on "
    "the favorite. Name the arm t0_plus_first_50_cross (not t0_only). If the dog is "
    "already >0.50 at T0, wait for a down-print then first up-cross (same as the "
    "Trungelliti bugfix); do not instantly cross. Compare live D=25, D=45, and that "
    "arm on the same 182-book freeze, with-fee P&L. Do we agree D=45 / this arm is "
    "better? KEEP/HOLD/DISMISS on quality. Live still D=25."
)

PLAIN = (
    "A Yes ticket pays $1 if that named tennis player wins. At the open we use here "
    "(T0) we buy Yes on both players, one contract each. Only one can win, so those "
    "two tickets always pay $1; if they cost $1.01 you are already down a penny (vig, "
    "the house overround). Live Strategy B then waits: if the cheaper T0 name (the "
    "underdog, or dog) later prints through 50 cents from below, it buys one more of "
    "that name, then tries to buy one more of the original favorite cheap enough that "
    "the extra pair locks a D-cent profit (favorite Yes at or below 1 − the underdog "
    "cross fill − D). Live D is 25 cents. This page scores three arms on the same "
    "frozen 182 books, and the dollars that matter are after venue fees. "
    "t0_plus_first_50_cross is both Yes at the start, then one more Yes on the dog "
    "the first time it prints over 50 from below, then stop. It is not live B, which "
    "then tries to buy the old favorite cheap. D=45 on the old tape looked like extra "
    "dog plus never filling that favorite — this page checks whether Paul’s arm "
    "matches that once fees are in. If the dog is already over 50 at T0, we wait for "
    "a print at or under 50, then the next print over 50; we do not buy extra at the "
    "open. Expectancy is the average with-fee dollars per settled book (also WR times "
    "average winning book plus (1 − WR) times average losing book). The whole October "
    "2026 tape is out-of-sample (OOS): every T0 is on or after 2024-01-01. There is no "
    "in-sample (IS) row. Research only. Not gold. Not DailyRun. Live D=25 is not changed."
)


def _out(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


def live_sender_fee(venue: str, price: float) -> float:
    """Fee the live senders charge for one $1-payout IOC taker fill.

    Kalshi: $0 unless a fill response returned a fee (replay has no fill payload).
    Gemini: 0.07 × p × (1 − p), rounded up to the next cent.
    Polymarket: theta × p × (1 − p), banker's cent; tape has no feeCoefficient so
    tennis default 0.0695.
    Novig: live B does not send Novig; tape has no fee_coefficient so $0.
    """
    name = (venue or "").strip().lower()
    px = Decimal(str(price))
    if px <= 0 or px >= 1:
        return 0.0
    if name == "kalshi":
        return 0.0
    if name == "gemini":
        raw = Decimal("0.07") * px * (ONE - px)
        if raw < 0:
            raw = Decimal("0")
        return float(raw.quantize(CENT, rounding=ROUND_CEILING))
    if name.startswith("polymarket"):
        exact = POLY_THETA * px * (ONE - px)
        if exact < 0:
            exact = Decimal("0")
        return float(exact.quantize(CENT, rounding=ROUND_HALF_EVEN))
    if name == "novig":
        return 0.0
    return 0.0


def fees_live(venue: str, prices: list[float]) -> float:
    return sum(live_sender_fee(venue, px) for px in prices if px is not None)


def first_cross_from_below(
    ticks: list[tuple[int, float]],
    lo: int,
    hi: int,
    t0_px: float | None,
    bar: float = CROSS,
) -> dict | None:
    """First original-dog Yes up-cross through bar from below.

    If T0 dog is already > bar, wait for a non-absorbing down-print at or below
    bar, then the next live print strictly above bar. Do not treat the T0-already-
    above print as a cross (Trungelliti bugfix). Absorbing 5¢ / 95¢ prints are
    skipped and do not count as the down-print.
    """
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


def collect_fills(pair: dict, rec: dict) -> list[float]:
    fills: list[float] = []
    t0a, t0b = pair.get("t0_a"), pair.get("t0_b")
    if t0a is not None:
        fills.append(float(t0a))
    if t0b is not None:
        fills.append(float(t0b))
    if rec.get("n_extra_dog") and rec.get("cross_px") is not None:
        fills.append(float(rec["cross_px"]))
    extra = rec.get("fav_extra") or {}
    if rec.get("n_extra_fav") and extra.get("px") is not None:
        fills.append(float(extra["px"]))
    return fills


def apply_live_fees(pair: dict, rec: dict) -> None:
    fills = collect_fills(pair, rec)
    venue = pair.get("venue") or ""
    rec["fees"] = fees_live(venue, fills)
    rec["n_fills"] = len(fills)
    if rec.get("pnl") is not None:
        rec["pnl_fee"] = float(rec["pnl"]) - float(rec["fees"])
    else:
        rec["pnl_fee"] = None


def simulate_t0_plus(pair: dict, cross: dict | None) -> dict:
    t0a, t0b = pair.get("t0_a"), pair.get("t0_b")
    c0 = pair.get("c0")
    lo, hi = pair.get("lo"), pair.get("hi")
    dog = pair.get("dog")
    venue = pair.get("venue") or ""
    winner = pair.get("winner")
    settled = bool(pair.get("settled") and winner in ("a", "b"))
    rec = {
        "dip": None,
        "label": (
            "t0_plus_first_50_cross: both Yes at T0, extra original-dog Yes at "
            "first from-below 50 cross, no favorite ticket"
        ),
        "crossed": False,
        "cross": cross,
        "cross_px": None,
        "cross_ts": None,
        "target": None,
        "fav_extra": None,
        "lock_filled": False,
        "n_extra_dog": 0,
        "n_extra_fav": 0,
        "mix": "t0 both only",
        "cost": c0,
        "fees": 0.0,
        "pnl": None,
        "pnl_fee": None,
        "payout": None,
        "t0_already_above": bool(cross and cross.get("t0_already_above")),
    }
    if t0a is None or t0b is None or c0 is None or lo is None or hi is None:
        apply_live_fees(pair, rec)
        return rec
    n_a = n_b = 0
    cost = float(c0)
    fill_px = cross["px"] if cross else None
    fill_ts = cross["ts"] if cross else None
    if cross is not None and fill_px is not None and fill_ts is not None:
        if ABSORB + 1e-12 < float(fill_px) < 0.95 - 1e-12:
            rec["crossed"] = True
            rec["cross_px"] = fill_px
            rec["cross_ts"] = fill_ts
            rec["n_extra_dog"] = 1
            rec["mix"] = "t0 + first 50 cross (no third ticket)"
            cost += float(fill_px)
            if dog == "a":
                n_a += 1
            else:
                n_b += 1
    rec["cost"] = cost
    rec["fees"] = fees_live(
        venue,
        collect_fills(pair, rec) if rec.get("n_extra_dog") else [float(t0a), float(t0b)],
    )
    if settled:
        paid = extras_payout(winner, n_a, n_b)
        rec["payout"] = paid
        rec["pnl"] = paid - cost
        rec["pnl_fee"] = rec["pnl"] - rec["fees"]
    else:
        apply_live_fees(pair, rec)
    return rec


def simulate_arms(pair: dict) -> None:
    assign_favorite(pair)
    t0a, t0b = pair.get("t0_a"), pair.get("t0_b")
    if t0a is not None and t0b is not None and pair.get("c0") is None:
        pair["c0"] = t0a + t0b
        pair["hold_pnl"] = 1.0 - pair["c0"]
    dog = pair.get("dog")
    lo, hi = pair.get("lo"), pair.get("hi")
    t0_dog = pair.get("t0_dog")
    pair["dog_t0_above_50"] = bool(t0_dog is not None and float(t0_dog) > CROSS + 1e-12)
    old_cross = None
    cross = None
    if dog and lo is not None and hi is not None:
        ticks = ticks_of(pair, dog, "yes")
        old_cross = first_cross_yes(ticks, lo, hi)
        cross = first_cross_from_below(ticks, lo, hi, t0_dog)
    pair["old_b_cross"] = old_cross
    pair["b_cross"] = cross
    pair["cross_changed"] = False
    if (old_cross or {}).get("ts") != (cross or {}).get("ts") or (
        old_cross or {}
    ).get("px") != (cross or {}).get("px"):
        pair["cross_changed"] = bool(old_cross or cross)
    pair["b_locks"] = {}
    primary_px = cross["px"] if cross else None
    primary_ts = cross["ts"] if cross else None
    for dip in B_DIPS:
        rec = simulate_b_variant(
            pair, dip, cross, primary_px, primary_ts, "first up-cross through 0.50 from below"
        )
        apply_live_fees(pair, rec)
        pair["b_locks"][dip] = rec
    pair[ARM_T0PLUS] = simulate_t0_plus(pair, cross)


def rec_of(pair: dict, arm: str) -> dict | None:
    if arm == ARM_T0PLUS:
        return pair.get(ARM_T0PLUS)
    try:
        dip = float(arm)
    except (TypeError, ValueError):
        return None
    return (pair.get("b_locks") or {}).get(dip)


def closed_trades(pairs: list[dict], arm: str) -> list[dict]:
    rows = []
    for pair in pairs:
        rec = rec_of(pair, arm)
        if not rec or rec.get("pnl_fee") is None or not pair.get("settled"):
            continue
        cost = rec.get("cost")
        fees = float(rec.get("fees") or 0.0)
        pnl = rec.get("pnl_fee")
        cash = (float(cost) + fees) if cost is not None else None
        days = pair_days(pair)
        opened = pair_opened(pair)
        rows.append(
            {
                "game": pair.get("game") or "",
                "venue": pair.get("venue") or "",
                "date": match_date(pair),
                "pnl_d": float(pnl),
                "pnl_gross": rec.get("pnl"),
                "fees": fees,
                "pnl": pnl_pct(pnl, cash),
                "cost": cash,
                "cost_ticket": float(cost) if cost is not None else None,
                "days": days,
                "opened": opened,
                "closed": pair_closed(pair),
                "crossed": bool(rec.get("crossed")),
                "lock_filled": bool(rec.get("lock_filled")),
                "mix": rec.get("mix") or "",
                "entry_date": match_date(pair),
            }
        )
    return rows


def slice_trades(trades: list[dict], which: str) -> list[dict]:
    if which == "full":
        return list(trades)
    out = []
    for t in trades:
        day = str(t.get("date") or t.get("entry_date") or "")[:10]
        if not day:
            continue
        if which == "is" and day < IS_CUT:
            out.append(t)
        elif which == "oos" and day >= IS_CUT:
            out.append(t)
    return out


def expectancy_parts(pnls: list[float]) -> dict:
    wins = [x for x in pnls if x > 1e-12]
    losses = [x for x in pnls if x < -1e-12]
    n = len(pnls)
    n_win = len(wins)
    n_loss = len(losses)
    n_scratch = n - n_win - n_loss
    wr = (n_win / n) if n else None
    avg_win = mean(wins) if wins else None
    avg_loss = mean(losses) if losses else None
    mean_pnl = mean(pnls) if pnls else None
    formula = None
    if n and wr is not None:
        win_leg = (wr * avg_win) if avg_win is not None else 0.0
        if avg_loss is not None:
            formula = win_leg + (1.0 - wr) * avg_loss
        else:
            formula = win_leg
    exact = None
    if n:
        exact = ((sum(wins) if wins else 0.0) + (sum(losses) if losses else 0.0)) / n
    return {
        "n": n,
        "n_win": n_win,
        "n_loss": n_loss,
        "n_scratch": n_scratch,
        "win_pct": (100.0 * wr) if wr is not None else None,
        "wr": wr,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "mean": mean_pnl,
        "expectancy_formula": formula,
        "expectancy_exact": exact,
        "formula_matches_mean": (
            formula is not None
            and mean_pnl is not None
            and abs(formula - mean_pnl) < 1e-9
        ),
    }


def quality_block(pairs: list[dict], arm: str, label: str, role: str) -> dict:
    recs = [rec_of(p, arm) for p in pairs]
    recs = [r for r in recs if r]
    trades = closed_trades(pairs, arm)
    pnls = [t["pnl_d"] for t in trades]
    gross = [float(t["pnl_gross"]) for t in trades if t.get("pnl_gross") is not None]
    fees = [float(t["fees"]) for t in trades]
    pcts = [t["pnl"] for t in trades if t.get("pnl") is not None]
    costs = [t["cost"] for t in trades if t.get("cost") is not None]
    days = [t["days"] for t in trades if t.get("days")]
    parts = expectancy_parts(pnls)
    sum_win = sum(x for x in pnls if x > 1e-12)
    sum_loss = abs(sum(x for x in pnls if x < -1e-12))
    pf = (sum_win / sum_loss) if sum_loss > 1e-12 else (sum_win if sum_win > 0 else 0.0)
    wo = None
    if len(pcts) >= 2:
        dropped = pcts[:]
        dropped.remove(max(dropped))
        wo = mean(dropped)
    elif pcts:
        wo = mean(pcts)
    median_cost = median(costs) if costs else None
    cash = float(median_cost) if median_cost and median_cost > 0 else 1.0
    overlay = overlay_ann_ror_max_dd(
        trades,
        cash=cash,
        initial_account=DEFAULT_INITIAL_ACCOUNT,
    )
    ann = overlay.get("ann_ror")
    if ann is not None and not math.isfinite(float(ann)):
        ann = None
    n = parts["n"]
    ann_1d = None
    if n > 0 and cash > 0:
        ann_1d = ann_ror_from_closed(
            total_pnl=sum(pnls),
            n_trades=n,
            avg_days_held=1.0,
            brt_cash=cash,
        )
    max_dd = overlay.get("max_dd")
    if max_dd is not None and not math.isfinite(float(max_dd)):
        max_dd = None
    calmar = overlay.get("calmar")
    if calmar is not None and not math.isfinite(float(calmar)):
        calmar = None
    sharpe = overlay.get("sharpe")
    if sharpe is not None and not math.isfinite(float(sharpe)):
        sharpe = None
    is_trades = slice_trades(trades, "is")
    oos_trades = slice_trades(trades, "oos")
    ann_is = None
    if is_trades:
        is_overlay = overlay_ann_ror_max_dd(
            is_trades, cash=cash, initial_account=DEFAULT_INITIAL_ACCOUNT
        )
        ann_is = is_overlay.get("ann_ror")
        if ann_is is not None and not math.isfinite(float(ann_is)):
            ann_is = None
    n_cross = sum(1 for r in recs if r.get("crossed"))
    n_lock = sum(1 for r in recs if r.get("lock_filled"))
    dip = None if arm == ARM_T0PLUS else float(arm)
    cents = None if dip is None else int(round(dip * 100))
    return {
        "arm_id": arm,
        "dip": dip,
        "cents": cents,
        "arm": label,
        "role": role,
        "n": len(recs),
        "n_settled": n,
        "n_win": parts["n_win"],
        "n_loss": parts["n_loss"],
        "n_scratch": parts["n_scratch"],
        "win_pct": parts["win_pct"],
        "mean": parts["mean"],
        "mean_gross": mean(gross) if gross else None,
        "mean_fees": mean(fees) if fees else None,
        "median": median(pnls) if pnls else None,
        "avg_pnl_pct": mean(pcts),
        "avg_pnl_pct_wo_max": wo,
        "expectancy": parts["expectancy_formula"] if parts["expectancy_formula"] is not None else parts["mean"],
        "expectancy_formula": parts["expectancy_formula"],
        "expectancy_exact": parts["expectancy_exact"],
        "formula_matches_mean": parts["formula_matches_mean"],
        "avg_win": parts["avg_win"],
        "avg_loss": parts["avg_loss"],
        "pf": pf,
        "mean_cost": mean(costs),
        "median_cost": median_cost,
        "brt_cash": cash,
        "pct_crossed": pct(n_cross, len(recs)) if recs else "",
        "pct_lock": pct(n_lock, len(recs)) if recs else "",
        "n_crossed": n_cross,
        "n_lock": n_lock,
        "avg_days": mean(days) if days else None,
        "capital_days": overlay.get("capital_days"),
        "ann_ror": ann,
        "ann_ror_1d": ann_1d,
        "ann_ror_is": ann_is,
        "ann_ror_oos": ann,
        "n_is": len(is_trades),
        "n_oos": len(oos_trades),
        "max_dd": max_dd,
        "max_dd_d": dollar_drawdown(trades),
        "calmar": calmar,
        "sharpe": sharpe,
        "sharpe_source": overlay.get("sharpe_source") or "",
        "overlay_note": overlay.get("note") or "",
        "note": tiny_note(n),
        "trades": trades,
    }


def identical_arms(a: dict, b: dict, keys: tuple[str, ...] | None = None) -> bool:
    keys = keys or (
        "n_settled", "n_win", "n_loss", "mean", "pf", "avg_win", "avg_loss",
        "n_lock", "n_crossed",
    )
    for k in keys:
        va, vb = a.get(k), b.get(k)
        if va is None and vb is None:
            continue
        try:
            if abs(float(va) - float(vb)) > 1e-12:
                return False
        except (TypeError, ValueError):
            if va != vb:
                return False
    return True


def mix_decomp(pairs: list[dict]) -> tuple[list[dict], dict]:
    settled = [
        p for p in pairs
        if p.get("settled")
        and rec_of(p, "0.25")
        and rec_of(p, "0.25").get("pnl_fee") is not None
        and rec_of(p, "0.45")
        and rec_of(p, "0.45").get("pnl_fee") is not None
        and rec_of(p, ARM_T0PLUS)
        and rec_of(p, ARM_T0PLUS).get("pnl_fee") is not None
    ]
    buckets: dict[str, list[dict]] = {}
    total_delta = 0.0
    lock_delta = 0.0
    n_lock = 0
    n_same_45_25 = 0
    n_same_45_t0 = 0
    n_same_25_t0 = 0
    for p in settled:
        d25 = rec_of(p, "0.25") or {}
        d45 = rec_of(p, "0.45") or {}
        t0 = rec_of(p, ARM_T0PLUS) or {}
        mix = d25.get("mix") or "unknown"
        p25 = float(d25["pnl_fee"])
        p45 = float(d45["pnl_fee"])
        p0 = float(t0["pnl_fee"])
        delta = p45 - p25
        total_delta += delta
        locked = bool(d25.get("lock_filled"))
        if locked:
            lock_delta += delta
            n_lock += 1
        if abs(p45 - p25) < 1e-12:
            n_same_45_25 += 1
        if abs(p45 - p0) < 1e-12:
            n_same_45_t0 += 1
        if abs(p25 - p0) < 1e-12:
            n_same_25_t0 += 1
        buckets.setdefault(mix, []).append(
            {
                "d25": p25,
                "d45": p45,
                "t0": p0,
                "delta": delta,
                "lock25": locked,
                "lock45": bool(d45.get("lock_filled")),
            }
        )
    rows = []
    order = ["t0 both only", "cross, no fav hedge", "cross + fav lock"]
    seen = set()
    names = [m for m in order if m in buckets] + [m for m in buckets if m not in order]
    for mix in names:
        if mix in seen:
            continue
        seen.add(mix)
        items = buckets[mix]
        rows.append(
            {
                "mix": mix,
                "n": len(items),
                "mean_25": mean([x["d25"] for x in items]),
                "mean_45": mean([x["d45"] for x in items]),
                "mean_t0": mean([x["t0"] for x in items]),
                "d_45_25": mean([x["delta"] for x in items]),
                "n_lock25": sum(1 for x in items if x["lock25"]),
                "n_lock45": sum(1 for x in items if x["lock45"]),
            }
        )
    share = (lock_delta / total_delta) if abs(total_delta) > 1e-12 else None
    meta = {
        "n": len(settled),
        "total_delta": total_delta,
        "lock_delta": lock_delta,
        "n_lock": n_lock,
        "n_same_45_25": n_same_45_25,
        "n_same_45_t0": n_same_45_t0,
        "n_same_25_t0": n_same_25_t0,
        "lock_share": share,
        "mean_delta": (total_delta / len(settled)) if settled else None,
    }
    return rows, meta


def decide_verdict(d25: dict, d45: dict, t0: dict, decomp: dict, same_45_t0: bool) -> tuple[str, str]:
    t0_vs_45 = None
    if t0.get("mean") is not None and d45.get("mean") is not None:
        t0_vs_45 = float(t0["mean"]) - float(d45["mean"])
    share = decomp.get("lock_share")
    share_txt = (
        f"{100.0 * share:.1f}% of the D=45 minus D=25 total-dollar gap sits on books "
        f"where D=25 filled the favorite lock ({decomp.get('n_lock')} settled books)."
        if share is not None else
        "Could not split the D=45 minus D=25 gap by lock fill."
    )
    exp25 = d25.get("expectancy_formula")
    exp45 = d45.get("expectancy_formula")
    exp0 = t0.get("expectancy_formula")
    agree_math = (
        exp45 is not None and exp25 is not None and float(exp45) > float(exp25) + 1e-12
    )
    math_line = (
        f"The with-fee arithmetic is right: D=45 expectancy {fmt_signed(exp45)} is higher "
        f"than D=25 {fmt_signed(exp25)} (WR {fmt_pct(d45.get('win_pct'), 1)}% × avg win "
        f"{fmt_signed(d45.get('avg_win'))} + (1−WR) × avg loss {fmt_signed(d45.get('avg_loss'))}). "
        if agree_math else
        "On this freeze, with-fee D=45 does not have higher expectancy than D=25. "
    )
    match_line = (
        f"t0_plus_first_50_cross with-fee mean {fmt_signed(t0.get('mean'))} matches D=45 "
        f"{fmt_signed(d45.get('mean'))} on this tape (same extra dog, no favorite fill; "
        f"{decomp.get('n_same_45_t0')} / {decomp.get('n')} settled books identical). "
        if same_45_t0 else
        f"t0_plus_first_50_cross with-fee mean {fmt_signed(t0.get('mean'))} vs D=45 "
        f"{fmt_signed(d45.get('mean'))} (gap {fmt_signed(t0_vs_45)}). "
        f"{decomp.get('n_same_45_t0')} / {decomp.get('n')} settled books are identical. "
        "They are not the same book on every row. "
    )
    t0_worse = (
        t0.get("mean") is not None
        and d25.get("mean") is not None
        and float(t0["mean"]) < float(d25["mean"]) - 1e-12
        and (t0.get("pf") or 0.0) < (d25.get("pf") or 0.0) - 1e-12
    )
    t0_better = (
        t0.get("mean") is not None
        and d25.get("mean") is not None
        and float(t0["mean"]) > float(d25["mean"]) + 1e-12
        and (t0.get("pf") or 0.0) >= (d25.get("pf") or 0.0) - 1e-9
    )
    why = (
        f"{math_line}"
        "We do not agree that D=45, or t0_plus_first_50_cross, is a better live Strategy B. "
        f"D=45 win rate {fmt_pct(d45.get('win_pct'), 1)}% vs D=25 "
        f"{fmt_pct(d25.get('win_pct'), 1)}%. Favorite-lock / third-ticket fill is "
        f"{d45.get('pct_lock') or '0'}% at D=45 vs {d25.get('pct_lock') or '0'}% at D=25, "
        f"and {t0.get('pct_lock') or '0'}% on t0_plus_first_50_cross (that arm never sends "
        "the favorite). "
        f"{share_txt} Bigger with-fee mean $ at D=45 / Paul’s arm is unhedged extra-underdog "
        "Yes after the first from-below 50¢ print, not a 45-cent lock that actually fills. "
        "Ranking after seeing this table is in-sample selection on an OOS-dated tape "
        f"(every T0 ≥ 2024-01-01; IS N={d25.get('n_is') or 0}). {match_line}"
        "Live D=25 still tries to buy the original favorite cheap after the extra dog. "
        "Paul’s arm does not. "
    )
    if t0_worse:
        tag = "DISMISS"
        why += (
            f"DISMISS t0_plus_first_50_cross versus live D=25 on quality (with-fee mean "
            f"{fmt_signed(t0.get('mean'))} vs {fmt_signed(d25.get('mean'))}, PF "
            f"{fmt_num(t0.get('pf'))} vs {fmt_num(d25.get('pf'))}). "
        )
    elif t0_better:
        tag = "HOLD"
        why += (
            "HOLD D=45 and t0_plus_first_50_cross versus live D=25: with-fee mean $ and "
            "profit factor can look better on this same October 2026 book, but there is no "
            "IS row, third-ticket fill is 0% on those two arms, and we do not retune OOS. "
        )
    else:
        tag = "HOLD"
        why += (
            "HOLD. Quality does not move together versus D=25 (mean / PF / WR). OOS-only "
            "tape; do not retune OOS. "
        )
    why += (
        f"With-fee expectancy: D=25 {fmt_signed(exp25)}; D=45 {fmt_signed(exp45)}; "
        f"t0_plus_first_50_cross {fmt_signed(exp0)}. Live D=25 is unchanged. Research "
        "only. Not gold. Not DailyRun. Not prediction-market DailyRun."
    )
    return tag, why


def freeze_rows() -> list[tuple[str, str]]:
    return [
        ("Universe", "Same 182 (game, venue) keys as strategy_b_D_05_to_50_20261023 and dense_inplay_fav_lock_cross_smalld_20261021.html. Tennis moneyline. C in [0.95, 1.20]. Both Yes in (0.10, 0.90). Dense in-play bar (≥200 ticks) from the original freeze keys."),
        ("T0", "Same helpers as the 5–25 / 5–50 stamps: assign_actual_t0 (last two-sided Yes at/before trusted actual start; else tape-resume / first competitive). Same C band and 1-contract size as live B. Not the live 5-minute send window."),
        ("Size", "1 contract per ticket. Optimistic IOC fill at the printed Yes ask."),
        ("Fees", "PRIMARY P&L WITH venue fees as live senders charge. Kalshi $0. Gemini 0.07×p×(1−p) round up to the next cent. Polymarket taker theta 0.0695 (tape has no feeCoefficient; banker's cent). Novig $0 on this replay (live B does not send Novig; tape has no fee_coefficient). Without-fee $ is diagnostic only, not the score. Delta from prior stamps that scored without fees."),
        ("Cross", "First original-dog Yes up-cross through 0.50 from below. If T0 dog already >0.50, wait for a non-absorbing down-print ≤0.50, then the next print >0.50 (Trungelliti). Do not instantly cross. Absorbing 5¢/95¢ prints are skipped."),
        ("Absorb", "Stop extras at first 5¢ / 95¢ absorbing print."),
        ("Control", "Live Strategy B D=25¢: T0 both Yes, extra underdog Yes at first from-below 50 cross, original-favorite Yes at/below 1 − cross_fill − 0.25. Primary $ with fees."),
        ("D=45", "Same live Strategy B definition; only D changes. Not extra-Yes-on-dip. Primary $ with fees."),
        ("t0_plus_first_50_cross", "T0 both Yes, then 1 extra original-dog Yes at the first from-below 50 cross (IOC at that ask). Stop. Do not buy the original favorite / dropped opponent at 1 − cross − D. No third ticket. Not t0_only (the misunderstood buy-both-and-stop arm)."),
        ("Prior t0_only", "drive/paul_experiments/strategy_b_t0_only_vs_D45_20261023 is not mutated. That page scored the wrong arm and without-fee P&L."),
        ("IS / OOS", "Inherited: entire October 2026 tape is OOS (every T0 ≥ 2024-01-01). No IS row. Do not retune on OOS."),
        ("Live D", "0.25 unchanged. This stamp does not wire a new D, is not gold, is not DailyRun, and does not start a second live B."),
        ("Ann ROR", "House compare_format.ann_ror_from_closed. Slot cash = median 1-contract cost including fees. Days held = T0→window-end hours, floored at 1 hour. Max DD / Sharpe seed $500,000 exit-date equity. Same-day tennis makes Ann ROR capital-turn explosive; judge quality on with-fee mean $, WR, PF, Max DD as well."),
        ("Selection", "KEEP/DISMISS on quality, not trade count. Ranking after seeing the table is in-sample selection on an OOS-dated tape."),
    ]


def expectancy_table_rows(arms: list[dict], ctrl: dict) -> list[dict]:
    from strategy_b_d_05_to_50_20261023 import delta_money, delta_num

    rows = []
    for rec in arms:
        match = rec.get("formula_matches_mean")
        rows.append(
            {
                "arm": rec["arm"],
                "role": rec["role"],
                "n": rec.get("n_settled"),
                "wins": rec.get("n_win"),
                "losses": rec.get("n_loss"),
                "scratch": rec.get("n_scratch"),
                "wr": fmt_pct(rec.get("win_pct"), 1),
                "avg_win": (
                    "n/a — no wins"
                    if not rec.get("n_win")
                    else signed_money(rec.get("avg_win"))
                ),
                "avg_loss": (
                    "n/a — no losses"
                    if not rec.get("n_loss")
                    else signed_money(rec.get("avg_loss"))
                ),
                "exp": signed_money(rec.get("expectancy_formula")),
                "mean": signed_money(rec.get("mean")),
                "gross": signed_money(rec.get("mean_gross")),
                "fees": signed_money(rec.get("mean_fees")),
                "match": "yes" if match else ("no" if match is False else ""),
                "pf": fmt_num(rec.get("pf")),
                "lock": rec.get("pct_lock") or "",
                "cross": rec.get("pct_crossed") or "",
                "d_exp": delta_money(rec.get("expectancy_formula"), ctrl.get("expectancy_formula")),
                "d_wr": delta_num(rec.get("win_pct"), ctrl.get("win_pct"), 1),
            }
        )
    return rows


def canonical_row(rec: dict, ctrl: dict) -> dict:
    row = compare_row(rec, ctrl)
    if rec.get("n_is"):
        row["ann_ror_is"] = fmt_ann(rec.get("ann_ror_is"))
    else:
        row["ann_ror_is"] = "n/a — no IS (all T0 ≥ 2024-01-01; prior stamp split kept)"
    row["ann_ror_oos"] = fmt_ann(rec.get("ann_ror_oos"))
    row["ann_ror"] = fmt_ann(rec.get("ann_ror"))
    row["mean_gross"] = signed_money(rec.get("mean_gross"))
    row["mean_fees"] = signed_money(rec.get("mean_fees"))
    if not rec.get("n_win"):
        row["avg_win"] = "n/a — no wins"
    if not rec.get("n_loss"):
        row["avg_loss"] = "n/a — no losses"
    return row


def per_match_rows(pairs: list[dict]) -> list[dict]:
    rows = []
    for p in pairs:
        winner = p.get("winner")
        win_name = p.get("side_a") if winner == "a" else p.get("side_b") if winner == "b" else ""
        b25 = rec_of(p, "0.25") or {}
        b45 = rec_of(p, "0.45") or {}
        t0 = rec_of(p, ARM_T0PLUS) or {}
        rows.append(
            {
                "game": p.get("game") or "",
                "date": match_date(p),
                "venue": p.get("venue") or "",
                "side_a": p.get("side_a") or "",
                "t0_a": fmt_px(p.get("t0_a")),
                "side_b": p.get("side_b") or "",
                "t0_b": fmt_px(p.get("t0_b")),
                "c0": fmt_px(p.get("c0")),
                "fav": last_name(p.get("fav_name") or "") or "",
                "dog": last_name(p.get("dog_name") or "") or "",
                "t0_dog": fmt_px(p.get("t0_dog")),
                "inplay_n": p.get("inplay_n") or 0,
                "winner": win_name,
                "live": "yes" if not p.get("settled") else "no",
                "t0_when": et_iso(p.get("t0_ts")),
                "dog50_t0": "yes" if p.get("dog_t0_above_50") else "no",
                "cross_chg": "yes" if p.get("cross_changed") else "no",
                "dog50": "yes" if t0.get("crossed") else "no",
                "b25_fill": b_fill_text(p, b25),
                "d25_mix": b25.get("mix") or "",
                "d25_pnl": signed_money(b25.get("pnl_fee")) if b25.get("pnl_fee") is not None else "",
                "d25_fee": signed_money(b25.get("fees")) if b25.get("fees") is not None else "",
                "d45_mix": b45.get("mix") or "",
                "d45_pnl": signed_money(b45.get("pnl_fee")) if b45.get("pnl_fee") is not None else "",
                "t0_mix": t0.get("mix") or "",
                "t0_pnl": signed_money(t0.get("pnl_fee")) if t0.get("pnl_fee") is not None else "",
                "t0_fee": signed_money(t0.get("fees")) if t0.get("fees") is not None else "",
            }
        )
    rows.sort(key=lambda r: (-(r.get("inplay_n") or 0), r.get("game") or "", r.get("venue") or ""))
    return rows


def example_html(title: str, pair: dict | None, missing: str) -> str:
    if pair is None:
        return f"<p class='note'>{esc(missing)}</p>"
    winner = ""
    if pair.get("winner") == "a":
        winner = pair.get("side_a") or ""
    elif pair.get("winner") == "b":
        winner = pair.get("side_b") or ""
    t0 = pair.get(ARM_T0PLUS) or {}
    bits = [
        f"<p><strong>{esc(title)}</strong> {esc(pair.get('venue') or '')}. "
        f"T0 {esc(pair.get('t0_label') or '')} at {esc(et_iso(pair.get('t0_ts')))}: "
        f"{esc(pair.get('side_a'))} {fmt_px(pair.get('t0_a'))} / "
        f"{esc(pair.get('side_b'))} {fmt_px(pair.get('t0_b'))}, C = {fmt_px(pair.get('c0'))}. "
        f"Favorite {esc(pair.get('fav_name') or '')}. Underdog {esc(pair.get('dog_name') or '')} "
        f"T0 Yes {fmt_px(pair.get('t0_dog'))}"
        f"{' (already &gt;0.50; wait for down-print)' if pair.get('dog_t0_above_50') else ''}. "
        f"Winner {esc(winner or 'unsettled')}. In-play ticks {pair.get('inplay_n') or 0}.</p>",
        f"<p>First from-below 50 cross: "
        f"{'yes' if t0.get('crossed') else 'no'} at {fmt_px(t0.get('cross_px'))} "
        f"@ {esc(et_iso(t0.get('cross_ts')))}. t0_plus mix {esc(t0.get('mix') or '')}; "
        f"ticket cost {money_cell(t0.get('cost'))}; fees {signed_money(t0.get('fees'))}; "
        f"with-fee P&amp;L "
        f"{signed_money(t0.get('pnl_fee')) if t0.get('pnl_fee') is not None else 'unsettled'}.</p>",
    ]
    for dip in B_DIPS:
        rec = (pair.get("b_locks") or {}).get(dip) or {}
        cents = int(round(dip * 100))
        bits.append(
            f"<p>D={cents}¢ target {fmt_px(rec.get('target'))}: {esc(b_fill_text(pair, rec))}; "
            f"mix {esc(rec.get('mix') or '')}; ticket cost {money_cell(rec.get('cost'))}; "
            f"fees {signed_money(rec.get('fees'))}; with-fee P&amp;L "
            f"{signed_money(rec.get('pnl_fee')) if rec.get('pnl_fee') is not None else 'unsettled'}.</p>"
        )
    return "\n".join(bits)


def write_baseline(payload: dict) -> None:
    d25, d45, t0 = payload["d25"], payload["d45"], payload["t0"]
    lines = [
        "# Strategy B t0_plus_first_50_cross vs D=45 vs live D=25 — freeze",
        "",
        "Research only. Not gold. Not DailyRun. Live D=25 is not changed.",
        "",
        "Delta from prior: primary P&L with live-sender fees + corrected arm "
        "`t0_plus_first_50_cross` (not t0_only). New stamp; the misunderstood "
        "`strategy_b_t0_only_vs_D45_20261023` page is not mutated.",
        "",
        "## What you asked",
        "",
        ASKED,
        "",
        "## In plain English",
        "",
        PLAIN,
        "",
        "## Freeze",
        "",
    ]
    for k, v in freeze_rows():
        lines.append(f"- **{k}:** {v}")
    lines.extend(
        [
            "",
            "## Replay N",
            "",
            f"- Frozen books: {payload['n_dense']} (original freeze {ORIGINAL_N}).",
            f"- Settled: {payload['n_dense_settled']} (original write {ORIGINAL_SETTLED}; freeze is on keys, not settled flags).",
            f"- Still live: {payload['n_dense_live']}. Missing freeze keys: {payload['n_missing']}.",
            f"- {payload.get('freeze_note') or ''}",
            f"- IS settled: {d25.get('n_is') or 0} (empty). OOS settled: {d25.get('n_oos')}.",
            f"- T0 dog already >0.50: {payload.get('n_t0_dog_above')} books. From-below cross differs from old first-print>50: {payload.get('n_cross_changed')} books.",
            "",
            "## Expectancy (settled books, WITH fees)",
            "",
            "expectancy = WR × avg_win $ + (1 − WR) × avg_loss $ (avg_loss is negative). "
            "This matches mean with-fee $ when every settled row is a win or a loss (no scratches).",
            "",
            "| arm | N | wins | losses | WR% | avg win $ | avg loss $ | expectancy $ | mean with-fee $ | mean without-fee $ (not the score) | mean fees | formula=mean | PF | lock% | extra-dog% |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|",
        ]
    )
    for rec in payload["arm_rows"]:
        lines.append(
            f"| {rec['arm']} | {rec.get('n_settled')} | {rec.get('n_win')} | "
            f"{rec.get('n_loss')} | {fmt_pct(rec.get('win_pct'), 1)} | "
            f"{'n/a — no wins' if not rec.get('n_win') else fmt_signed(rec.get('avg_win'))} | "
            f"{'n/a — no losses' if not rec.get('n_loss') else fmt_signed(rec.get('avg_loss'))} | "
            f"{fmt_signed(rec.get('expectancy_formula'))} | {fmt_signed(rec.get('mean'))} | "
            f"{fmt_signed(rec.get('mean_gross'))} | {fmt_signed(rec.get('mean_fees'))} | "
            f"{'yes' if rec.get('formula_matches_mean') else 'no'} | "
            f"{fmt_num(rec.get('pf'))} | {rec.get('pct_lock') or ''} | "
            f"{rec.get('pct_crossed') or ''} |"
        )
    decomp = payload["decomp_meta"]
    share = decomp.get("lock_share")
    share_txt = f"{100.0 * share:.1f}%" if share is not None else "n/a"
    lines.extend(
        [
            "",
            "## Does Paul’s arm match D=45 economically?",
            "",
            f"- D=25 lock / third-ticket filled {d25.get('pct_lock')}% of frozen books; D=45 lock filled {d45.get('pct_lock')}%; t0_plus_first_50_cross lock filled {t0.get('pct_lock')}%.",
            f"- Extra-dog (from-below 50) filled {t0.get('pct_crossed')}% on t0_plus; D=25 crossed {d25.get('pct_crossed')}%; D=45 crossed {d45.get('pct_crossed')}%.",
            f"- {decomp.get('n_same_45_t0')} / {decomp.get('n')} settled books have D=45 with-fee P&L equal to t0_plus_first_50_cross.",
            f"- {decomp.get('n_same_45_25')} / {decomp.get('n')} settled books have D=45 equal to D=25.",
            f"- {share_txt} of the total-dollar D=45 minus D=25 gap sits on the {decomp.get('n_lock')} books where D=25 filled the third ticket.",
            "- On this tape D=45 still does not fill the favorite (target sits at/under the 5¢ absorb when the extra dog fill is >0.50). Paul’s arm is extra dog + stop by design. Economically they match when the favorite never fills.",
            "",
            "| D=25 mix | N | mean D=25 with-fee | mean D=45 with-fee | mean t0_plus with-fee | Δ 45−25 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for r in payload.get("mix_rows") or []:
        lines.append(
            f"| {r['mix']} | {r['n']} | {fmt_signed(r['mean_25'])} | "
            f"{fmt_signed(r['mean_45'])} | {fmt_signed(r['mean_t0'])} | "
            f"{fmt_signed(r['d_45_25'])} |"
        )
    lines.extend(
        [
            "",
            f"## Verdict: {payload.get('verdict') or 'HOLD'}",
            "",
            payload["sweet_text"],
            "",
            "Selection: KEEP/DISMISS on quality, not trade count. OOS is report-only. "
            "No IS row exists on this tape, so KEEP is not available from this ranking. "
            "Live D=25 unchanged.",
            "",
        ]
    )
    BASELINE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {BASELINE}", flush=True)


def write_html(payload: dict) -> None:
    blocked = {
        ORIGINAL_PAGE.resolve(),
        PRIOR_HTML.resolve(),
        (PRIOR_STAMP / "compare.html").resolve(),
        (OLD_T0_STAMP / "compare.html").resolve(),
    }
    if PAGE.resolve() in blocked:
        raise RuntimeError("refusing to overwrite a prior stamp HTML")
    d25, d45, t0 = payload["d25"], payload["d45"], payload["t0"]
    freeze_table = table(
        [("Knob", "text"), ("Freeze", "text")],
        [{"k": k, "v": v} for k, v in freeze_rows()],
        ["k", "v"],
    )
    exp_headers = [
        ("Arm", "text"),
        ("Role", "text"),
        ("N settled", "num"),
        ("Wins", "num"),
        ("Losses", "num"),
        ("Scratches", "num"),
        ("Win %", "num"),
        ("Avg win $", "num"),
        ("Avg loss $", "num"),
        ("Expectancy $ with fees (WR×avg win + (1−WR)×avg loss)", "num"),
        ("Mean $ with fees (the score)", "num"),
        ("Mean $ without fees (not the score)", "num"),
        ("Mean fees $", "num"),
        ("Formula matches mean", "text"),
        ("Profit factor", "num"),
        ("% third-ticket / lock filled", "num"),
        ("% extra dog filled (from-below 50)", "num"),
        ("Δ expectancy vs D=25", "num"),
        ("Δ WR vs D=25", "num"),
    ]
    exp_fields = [
        "arm", "role", "n", "wins", "losses", "scratch", "wr", "avg_win", "avg_loss",
        "exp", "mean", "gross", "fees", "match", "pf", "lock", "cross", "d_exp", "d_wr",
    ]
    compare_headers = [
        ("Arm", "text"),
        ("Role", "text"),
        ("N books", "num"),
        ("N settled", "num"),
        ("Wins", "num"),
        ("Losses", "num"),
        ("Win %", "num"),
        ("Mean $ with fees / expectancy $", "num"),
        ("Mean $ without fees (not the score)", "num"),
        ("Mean fees $", "num"),
        ("Median $", "num"),
        ("Avg PnL %", "num"),
        ("AVG_PNL_PCT_WO_MAX", "num"),
        ("Avg win $", "num"),
        ("Avg loss $", "num"),
        ("Profit factor", "num"),
        ("Mean cost incl. fees", "num"),
        ("% extra dog filled", "num"),
        ("% third-ticket / lock filled", "num"),
        ("Avg days held", "num"),
        ("Capital days", "num"),
        ("Ann ROR full (hours held)", "text"),
        ("Ann ROR if 1 calendar day", "text"),
        ("Ann ROR IS", "text"),
        ("Ann ROR OOS (hours held)", "text"),
        ("Max DD % ($500k seed)", "num"),
        ("Max DD $ (1-contract cum)", "num"),
        ("Calmar", "num"),
        ("Sharpe", "num"),
        ("Δ mean $ vs D=25", "num"),
        ("Δ WR vs D=25", "num"),
        ("Δ PF vs D=25", "num"),
        ("Δ Ann ROR 1d vs D=25", "num"),
        ("Δ Max DD $ vs D=25", "num"),
        ("Note", "text"),
    ]
    compare_fields = [
        "arm", "role", "n", "n_settled", "wins", "losses", "win_pct", "mean",
        "mean_gross", "mean_fees",
        "median", "avg_pnl_pct", "wo_max", "avg_win", "avg_loss", "pf",
        "mean_cost", "pct_crossed", "pct_lock", "avg_days", "capital_days",
        "ann_ror", "ann_ror_1d", "ann_ror_is", "ann_ror_oos", "max_dd", "max_dd_d",
        "calmar", "sharpe",
        "d_mean", "d_wr", "d_pf", "d_ann", "d_dd", "note",
    ]
    mix_headers = [
        ("D=25 mix (what live B actually did)", "text"),
        ("N settled", "num"),
        ("Mean D=25 with-fee $", "num"),
        ("Mean D=45 with-fee $", "num"),
        ("Mean t0_plus_first_50_cross with-fee $", "num"),
        ("Δ D=45 − D=25 $", "num"),
        ("N lock filled at D=25", "num"),
        ("N lock filled at D=45", "num"),
    ]
    mix_rows = []
    for r in payload["mix_rows"]:
        mix_rows.append(
            {
                "mix": r["mix"],
                "n": r["n"],
                "m25": signed_money(r["mean_25"]),
                "m45": signed_money(r["mean_45"]),
                "mt0": signed_money(r["mean_t0"]),
                "d": signed_money(r["d_45_25"]),
                "l25": r["n_lock25"],
                "l45": r["n_lock45"],
            }
        )
    mix_fields = ["mix", "n", "m25", "m45", "mt0", "d", "l25", "l45"]
    match_headers = [
        ("Match", "text"),
        ("Date", "date"),
        ("Venue", "text"),
        ("Yes A", "text"),
        ("T0 A", "num"),
        ("Yes B", "text"),
        ("T0 B", "num"),
        ("C", "num"),
        ("Fav", "text"),
        ("Dog", "text"),
        ("T0 dog Yes", "num"),
        ("In-play ticks", "num"),
        ("Winner", "text"),
        ("Still live", "text"),
        ("T0 clock", "text"),
        ("Dog already >50 at T0", "text"),
        ("From-below cross ≠ old first-print>50", "text"),
        ("Extra dog filled", "text"),
        ("D=25 fills", "text"),
        ("D=25 mix", "text"),
        ("D=25 with-fee P&L", "num"),
        ("D=25 fees", "num"),
        ("D=45 mix", "text"),
        ("D=45 with-fee P&L", "num"),
        ("t0_plus mix", "text"),
        ("t0_plus with-fee P&L", "num"),
        ("t0_plus fees", "num"),
    ]
    match_fields = [
        "game", "date", "venue", "side_a", "t0_a", "side_b", "t0_b", "c0",
        "fav", "dog", "t0_dog", "inplay_n", "winner", "live", "t0_when",
        "dog50_t0", "cross_chg", "dog50",
        "b25_fill", "d25_mix", "d25_pnl", "d25_fee", "d45_mix", "d45_pnl",
        "t0_mix", "t0_pnl", "t0_fee",
    ]
    decomp = payload["decomp_meta"]
    share = decomp.get("lock_share")
    share_txt = f"{100.0 * share:.1f}%" if share is not None else "n/a"
    same_txt = (
        "yes — same extra dog, no favorite fill, identical with-fee $ on every settled book"
        if payload.get("same_45_t0")
        else (
            f"not on every row ({decomp.get('n_same_45_t0')} / {decomp.get('n')} settled "
            "books identical)"
        )
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Strategy B t0_plus_first_50_cross vs D=45 vs D=25 2026-10-23</title>
{report_page_extras.CACHE_META}
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 24px; color: #1e293b; line-height: 1.45; max-width: none; }}
h1 {{ font-size: 1.7rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.25rem; margin-top: 1.7rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 12px 0; }}
.note {{ color: #475569; font-size: 0.95rem; }}
.hl {{ background: #fef9c3; padding: 10px 12px; border: 1px solid #eab308; margin: 12px 0; }}
.warn {{ background: #fef2f2; padding: 10px 12px; border: 1px solid #f87171; margin: 12px 0; }}
code {{ font-size: 0.92em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Strategy B — t0_plus_first_50_cross vs D=45 vs live D=25</h1>
<p class="note">Written {esc(payload['written_at'])}. Research only. Not gold. Not DailyRun. Not a trading rule. This page does not place orders. Live D=25 is unchanged. Entire October 2026 tape is out-of-sample (OOS): every T0 ≥ 2024-01-01. In-sample (IS) N={esc(d25.get('n_is') or 0)} — empty. Verdict: <strong>{esc(payload.get('verdict') or 'HOLD')}</strong>. New stamp; the old t0_only page is not mutated.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="hl">
<p><strong>Do we agree D=45 / this arm is better?</strong> With-fee expectancy D=25 {esc(fmt_signed(d25.get('expectancy_formula')))}; D=45 {esc(fmt_signed(d45.get('expectancy_formula')))}; t0_plus_first_50_cross {esc(fmt_signed(t0.get('expectancy_formula')))}. We do not wire live D from this tape. D=45 third-ticket / lock filled {esc(d45.get('pct_lock') or '0')}% vs {esc(d25.get('pct_lock') or '')} at D=25. t0_plus lock filled {esc(t0.get('pct_lock') or '0')}% — that arm never sends the favorite. {esc(share_txt)} of the total-dollar gap sits on books where D=25 actually bought that third ticket. Ranking after the table is selection bias on an OOS-dated tape. Verdict <strong>{esc(payload.get('verdict') or 'HOLD')}</strong>. Live D=25 stays.</p>
<p><strong>t0_plus_first_50_cross vs D=45:</strong> {esc(same_txt)}. Paul’s arm is both Yes at start, then one more Yes on the dog the first time it prints over 50 from below, stop. It is not live B (which then tries to buy the old favorite cheap). On the old without-fee tape D=45 looked like extra dog + never filling the favorite. With fees, D=45 lock fill is {esc(d45.get('pct_lock') or '0')}%.</p>
<p><strong>Not t0_only:</strong> the misunderstood “buy both at T0 and never send again” arm is not scored here. Prior page <code>strategy_b_t0_only_vs_D45_20261023</code> is left as-is.</p>
<p><strong>Frozen universe:</strong> {esc(payload['n_dense'])} tennis books keyed to the original extra-Yes-on-dip HTML ({ORIGINAL_N} keys). Settled {esc(payload['n_dense_settled'])}; still live {esc(payload['n_dense_live'])}. {esc(payload.get('freeze_note') or '')} T0 dog already &gt;0.50 on {esc(payload.get('n_t0_dog_above'))} books; from-below cross differs from old first-print&gt;50 on {esc(payload.get('n_cross_changed'))} books. Prior D-sweep (without-fee): <a href="../strategy_b_D_05_to_50_20261023/compare.html">strategy_b_D_05_to_50_20261023/compare.html</a> (not overwritten).</p>
<p>Annualized rate of return (Ann ROR) uses <code>compare_format.ann_ror_from_closed</code>. Slot cash = median 1-contract cost including fees. The hours-held column uses T0→window-end (floor 1 hour) and is capital-turn explosive on same-day tennis — it is the house formula, not a send rule. A second column uses 1 calendar day so arms can be compared. IS Ann ROR is n/a — no IS (all T0 after 2024-01-01). Full book = OOS. Max DD % / Sharpe replay exit-date equity from {format_money(DEFAULT_INITIAL_ACCOUNT)} (near 0% at 1-contract size). 1-contract dollar Max DD is cumulative with-fee PnL peak-to-trough on the settled book. Total book PnL $ is omitted from the compare table (canonical HTML compare rule).</p>
</div>

<div class="warn">
<p>Primary P&amp;L is <strong>with fees</strong> (Polymarket taker 0.0695, Gemini round-up, Kalshi $0, Novig $0 on this tape). Fills are optimistic at the printed Yes ask. Do not buy after the first 5¢ / 95¢ absorbing print. Dog already &gt;0.50 at T0 waits for a down-print, then the first up-cross. Verdict <strong>{esc(payload.get('verdict') or 'HOLD')}</strong>. Live D=25 unchanged. Research only. Not gold. Not DailyRun. This page does not start a second live B and does not touch live lock orders.</p>
</div>

<h2>Freeze</h2>
<p class="note">Click column headers to sort. Same 182-book freeze as the D=5…50 sweep. Generator helpers: <code>tools/dense_inplay_fav_lock_cross_smalld_20261021.py</code> plus this stamp script. Swipe sideways to see more columns.</p>
{freeze_table}

<h2>1. Expectancy with fees — D=25 vs D=45 vs t0_plus_first_50_cross</h2>
<p class="note">Expectancy = win rate × average winning book $ + (1 − win rate) × average losing book $ (losses negative). That equals mean with-fee $ when every settled row is a win or a loss. % lock / % extra dog are all frozen books. Click column headers to sort.</p>
{table(exp_headers, payload["exp_rows"], exp_fields)}

<h2>2. Where the D=45 extra mean comes from</h2>
<p class="note">Same settled books, grouped by what live D=25 actually did, with-fee $. On books that never crossed 50 from below, D=25 = D=45 = t0_plus = $1 − C − T0 fees. On books that crossed but D=25 did not fill the favorite, D=25 = D=45 = t0_plus (T0 both + extra underdog). On books where D=25 filled the third ticket, D=45 and t0_plus leave that extra underdog unhedged. Click column headers to sort.</p>
{table(mix_headers, mix_rows, mix_fields)}
<p class="note">{esc(decomp.get('n_same_45_25'))} of {esc(decomp.get('n'))} settled books have D=45 P&amp;L equal to D=25. {esc(decomp.get('n_same_45_t0'))} of {esc(decomp.get('n'))} have D=45 equal to t0_plus_first_50_cross. {esc(share_txt)} of the total-dollar gap sits on the {esc(decomp.get('n_lock'))} D=25 lock-filled books.</p>

<h2>3. Canonical compare vs control D=25 (with-fee $)</h2>
<p class="note">Mean / median / win rate / Ann ROR are settled books. % extra dog / % lock filled are all frozen books. Deltas are that arm minus D=25. Ann ROR IS is n/a (empty — all T0 after 2024-01-01). Full book = OOS. Click column headers to sort.</p>
{table(compare_headers, payload["compare_rows"], compare_fields)}

<h2>4. Worked examples (same named matches as the 5–25 page)</h2>
{payload["hassan_html"]}
{payload["smith_html"]}

<h2>5. Per-match (frozen keys)</h2>
<p class="note">One row per frozen book. P&amp;L columns are with fees. Extra dog filled is the from-below 50 send on t0_plus / D arms. Click column headers to sort. Swipe sideways to see more columns.</p>
{table(match_headers, payload["match_rows"], match_fields)}

<h2>Process notes</h2>
<ul>
<li>KEEP / HOLD / DISMISS is quality versus control D=25, not trade count.</li>
<li>OOS is report-only. Do not retune live D from this tape. No IS row, so KEEP is not available from ranking after the table.</li>
<li>Live <code>tools/live_strategy_b.py</code> stays at D=0.25. This stamp does not start a second live process and does not edit live lock orders. No GTC, no sell, no commit, no secrets.</li>
<li>Acronyms: T0 is the open used here. C is the two T0 Yes prices added together. Vig is the overround when two Yes prices sum over $1. D is lock profit on the extra post-cross pair. Ann ROR is annualized rate of return. IS is in-sample; OOS is out-of-sample. IOC is immediate-or-cancel. PF is profit factor. Max DD is maximum drawdown. WR is win rate.</li>
</ul>
<p><strong>Verdict:</strong> {esc(payload.get('sweet_text') or '')}</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    STAMP.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    print(f"wrote {PAGE}", flush=True)


def copy_g(path: Path) -> None:
    dest_dir = Path(r"G:\My Drive\paul_experiments\strategy_b_t0_plus_50cross_20261023")
    if dest_dir.parent.exists() or Path("G:/").exists():
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / path.name
            shutil.copy2(path, dest)
            print(f"copied {dest}", flush=True)
        except OSError as exc:
            print(f"G: copy skipped: {exc}", flush=True)
    else:
        print("G: not present, skip copy", flush=True)


def json_safe(rec: dict) -> dict:
    out = {}
    for k, v in rec.items():
        if k == "trades":
            continue
        if isinstance(v, float) and not math.isfinite(v):
            out[k] = None
        else:
            out[k] = v
    return out


def self_check() -> None:
    lo, hi = 100, 1000
    ticks = [(110, 0.52), (120, 0.48), (130, 0.51), (140, 0.62)]
    got = first_cross_from_below(ticks, lo, hi, 0.55)
    assert got is not None and got["ts"] == 130 and abs(got["px"] - 0.51) < 1e-12, got
    assert got.get("t0_already_above") is True
    instant = first_cross_from_below(ticks, lo, hi, 0.40)
    assert instant is not None and instant["ts"] == 110, instant
    absorb = first_cross_from_below([(110, 0.04), (120, 0.48), (130, 0.51)], lo, hi, 0.55)
    assert absorb is not None and absorb["ts"] == 130, absorb
    none = first_cross_from_below([(110, 0.52), (120, 0.53)], lo, hi, 0.55)
    assert none is None
    fee_k = live_sender_fee("Kalshi", 0.41)
    fee_g = live_sender_fee("Gemini", 0.41)
    fee_p = live_sender_fee("Polymarket", 0.41)
    fee_n = live_sender_fee("Novig", 0.41)
    assert fee_k == 0.0, fee_k
    assert fee_n == 0.0, fee_n
    assert fee_g > 0 and fee_p > 0, (fee_g, fee_p)
    _out(f"self_check ok gemini_fee={fee_g:.2f} poly_fee={fee_p:.2f}")


def main() -> None:
    self_check()
    freeze_keys = freeze_keys_from_original_html()
    freeze_set = set(freeze_keys)
    print(f"freeze keys from original HTML {len(freeze_keys)} unique {len(freeze_set)}", flush=True)
    stream = stream_tennis()
    settlements = load_settlements()
    catalog = load_catalog()
    start_lookup = start_lookup_from(settlements, catalog)
    pairs = pair_matches(stream["series"], start_lookup)
    tennis = [p for p in pairs if (p.get("sport") or "").lower() == "tennis"]
    print(f"two-sided tennis {len(tennis)}", flush=True)
    for pair in tennis:
        assign_actual_t0(pair, start_lookup)
    attach_pair_results(tennis, settlements)
    for pair in tennis:
        mark_inplay(pair)
    by_key: dict[tuple[str, str], dict] = {}
    for pair in tennis:
        by_key[pair_key(pair)] = pair
    frozen = []
    missing = []
    for key in freeze_keys:
        pair = by_key.get(key)
        if pair is None:
            missing.append(key)
            continue
        frozen.append(pair)
    print(f"frozen {len(frozen)}; missing {len(missing)}", flush=True)
    for pair in frozen:
        simulate_arms(pair)
    settled = [p for p in frozen if p.get("settled")]
    live = [p for p in frozen if not p.get("settled")]
    n_t0_dog_above = sum(1 for p in frozen if p.get("dog_t0_above_50"))
    n_cross_changed = sum(1 for p in frozen if p.get("cross_changed"))
    d25 = quality_block(
        frozen, "0.25",
        "B D=25¢ (live: 1 − cross_fill − D after from-below 50; with fees)",
        "control",
    )
    d45 = quality_block(
        frozen, "0.45",
        "B D=45¢ (1 − cross_fill − D after from-below 50; with fees)",
        "candidate D",
    )
    t0 = quality_block(
        frozen, ARM_T0PLUS,
        "t0_plus_first_50_cross (T0 both + extra dog at first from-below 50; no favorite; with fees)",
        "new arm",
    )
    arm_rows = [d25, d45, t0]
    for rec in arm_rows:
        _out(
            f"{rec['arm_id']} n={rec['n']} settled={rec['n_settled']} "
            f"mean_fee={fmt_signed(rec['mean'])} mean_gross={fmt_signed(rec.get('mean_gross'))} "
            f"fees={fmt_signed(rec.get('mean_fees'))} WR={fmt_pct(rec.get('win_pct'), 1)} "
            f"avgW={fmt_signed(rec.get('avg_win'))} avgL={fmt_signed(rec.get('avg_loss'))} "
            f"exp={fmt_signed(rec.get('expectancy_formula'))} match={rec.get('formula_matches_mean')} "
            f"PF={fmt_num(rec.get('pf'))} crossed={rec.get('pct_crossed')} "
            f"lock={rec.get('pct_lock')} IS={rec.get('n_is')} OOS={rec.get('n_oos')}"
        )
    mix_rows, decomp_meta = mix_decomp(frozen)
    same_45_t0 = identical_arms(d45, t0)
    _out(f"D45 identical to t0_plus: {same_45_t0}")
    _out(
        f"decomp n={decomp_meta.get('n')} same45=25 {decomp_meta.get('n_same_45_25')} "
        f"same45=t0 {decomp_meta.get('n_same_45_t0')} lock_share={decomp_meta.get('lock_share')} "
        f"t0_dog>50={n_t0_dog_above} cross_changed={n_cross_changed}"
    )
    verdict, sweet_text = decide_verdict(d25, d45, t0, decomp_meta, same_45_t0)
    _out(f"VERDICT {verdict}")
    freeze_bits = []
    if len(frozen) != ORIGINAL_N:
        freeze_bits.append(
            f"Frozen N is {len(frozen)}, not {ORIGINAL_N} "
            f"({len(missing)} keys missing from current tape)."
        )
    else:
        freeze_bits.append(f"Frozen N holds at {ORIGINAL_N}.")
    if len(settled) != ORIGINAL_SETTLED:
        freeze_bits.append(
            f"Settled N is {len(settled)}, not {ORIGINAL_SETTLED} from the 5–25 write. "
            "Freeze is on (game, venue) keys, not on settled flags; more official winners "
            "can attach later."
        )
    else:
        freeze_bits.append(f"Settled N holds at {ORIGINAL_SETTLED}.")
    hassan = pick_named(frozen, "rodenas", "hassan", venue="polymarket")
    smith = pick_named(frozen, "smith", "purcell", venue="polymarket")
    payload = {
        "written_at": iso_now(),
        "arm_rows": arm_rows,
        "d25": d25,
        "d45": d45,
        "t0": t0,
        "ctrl": d25,
        "verdict": verdict,
        "sweet_text": sweet_text,
        "same_45_t0": same_45_t0,
        "mix_rows": mix_rows,
        "decomp_meta": decomp_meta,
        "n_dense": len(frozen),
        "n_dense_settled": len(settled),
        "n_dense_live": len(live),
        "n_missing": len(missing),
        "n_t0_dog_above": n_t0_dog_above,
        "n_cross_changed": n_cross_changed,
        "freeze_note": " ".join(freeze_bits),
        "hassan_html": example_html(
            "Rodenas vs Hassan",
            hassan,
            "Rodenas vs Hassan Polymarket is not on this frozen book.",
        ),
        "smith_html": example_html(
            "Smith vs Purcell",
            smith,
            "Smith vs Purcell Polymarket is not on this frozen book.",
        ),
        "match_rows": per_match_rows(frozen),
        "stream_lines": stream.get("n_lines"),
        "seen_min": stream.get("seen_min"),
        "seen_max": stream.get("seen_max"),
    }
    payload["exp_rows"] = expectancy_table_rows(arm_rows, d25)
    payload["compare_rows"] = [canonical_row(rec, d25) for rec in arm_rows]
    STAMP.mkdir(parents=True, exist_ok=True)
    ARMS_JSON.write_text(
        json.dumps(
            {
                "written_at": payload["written_at"],
                "verdict": verdict,
                "sweet_text": sweet_text,
                "same_45_t0": same_45_t0,
                "decomp": {k: v for k, v in decomp_meta.items()},
                "n_dense": payload["n_dense"],
                "n_dense_settled": payload["n_dense_settled"],
                "n_t0_dog_above": n_t0_dog_above,
                "n_cross_changed": n_cross_changed,
                "arms": [json_safe(r) for r in arm_rows],
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    write_html(payload)
    write_baseline(payload)
    copy_g(PAGE)
    copy_g(BASELINE)
    print("done", flush=True)


if __name__ == "__main__":
    main()
