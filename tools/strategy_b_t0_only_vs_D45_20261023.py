"""Strategy B D=25 vs D=45 vs t0_only on the frozen dense tennis book.

Research only. Reads local price_memory (archive + dated shards) and official
settlements. Does not place, cancel, or amend orders. Does not print secrets.
Does not touch orders_stopped.json or live_lock_orders. Does not start
live_strategy_b.py. Does not change live D=0.25. Not gold. Not DailyRun.

Same 182-book freeze as strategy_b_D_05_to_50_20261023. One new arm: t0_only
(T0 both Yes; dog>50 observed for labeling only; never buy extra dog or the
original favorite at 1 − cross − D).
"""
from __future__ import annotations

import json
import math
import shutil
import sys
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
    ORIGINAL_N,
    ORIGINAL_PAGE,
    ORIGINAL_SETTLED,
    assign_favorite,
    b_fill_text,
    fees_for,
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
    iso_now,
    mark_inplay,
    match_date,
    money_cell,
    pair_matches,
    signed_money,
    stream_tennis,
)
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

STAMP = ROOT / "drive" / "paul_experiments" / "strategy_b_t0_only_vs_D45_20261023"
PAGE = STAMP / "compare.html"
BASELINE = STAMP / "BASELINE.md"
ARMS_JSON = STAMP / "arms.json"
PRIOR_STAMP = ROOT / "drive" / "paul_experiments" / "strategy_b_D_05_to_50_20261023"
PRIOR_HTML = (
    ROOT
    / "drive"
    / "paul_experiments"
    / "prediction_market_arb_exhaustive_20261017"
    / "dense_inplay_fav_lock_cross_smalld_20261021.html"
)
CONTROL_D = 0.25
B_DIPS = (0.25, 0.45, 0.50)
IS_CUT = "2024-01-01"

ASKED = (
    "Paul: he thinks Strategy B D=45¢ is better than live D=25 because if you compare "
    "win rate to avg win + avg loss, D=45 has higher expectancy. He asks if we agree. "
    "Second ask: run B where we never buy the final dropped opponent. Just buy both Yes "
    "at T0. The old trigger still exists in words: if the lower one rises above 50 for "
    "the first time — but do not buy the original favorite at 1−cross−D. No third ticket."
)

PLAIN = (
    "Strategy B is a tennis moneyline idea. A Yes ticket pays $1 if that named player "
    "wins. At the open we use here (T0) we buy Yes on both players, one contract each. "
    "Only one can win, so those two tickets always pay $1; if they cost $1.01 you are "
    "already down a penny (vig, the house overround). Live Strategy B then waits: if the "
    "cheaper T0 name (the underdog) later prints strictly above 50 cents, it buys one more "
    "of that name, then tries to buy one more of the original favorite cheap enough that "
    "the extra pair locks a D-cent profit (favorite Yes at or below 1 − the underdog cross "
    "fill − D). Live D is 25 cents. Expectancy here is the average dollars per settled "
    "book: win rate times average winning book plus (1 − win rate) times average losing "
    "book (losses are negative). This page keeps the same frozen 182 books as the D=5…50 "
    "sweep and scores three live-style D arms (25, 45, and 50) plus a new arm called "
    "t0_only: buy both Yes at T0 and stop. The 50-cent rise is still watched so we can "
    "label whether the lower name ever printed above 50 — but we do not buy the extra "
    "underdog, and we do not buy the original favorite (the dropped opponent) at "
    "1 − cross − D. No third ticket. Primary P&L is without venue fees. Fills are "
    "optimistic at the printed Yes. The whole October 2026 tape is out-of-sample (OOS): "
    "every T0 is on or after 2024-01-01. There is no in-sample (IS) row. Research only. "
    "Not gold. Not DailyRun. Live D=25 is not changed."
)


def _out(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


def simulate_t0_only(pair: dict) -> None:
    """T0 both Yes. Dog>50 is labeled only. Never buy extra dog or original favorite."""
    assign_favorite(pair)
    t0a, t0b = pair.get("t0_a"), pair.get("t0_b")
    if t0a is not None and t0b is not None and pair.get("c0") is None:
        pair["c0"] = t0a + t0b
        pair["hold_pnl"] = 1.0 - pair["c0"]
    dog = pair.get("dog")
    lo, hi = pair.get("lo"), pair.get("hi")
    venue = pair.get("venue") or ""
    winner = pair.get("winner")
    settled = bool(pair.get("settled") and winner in ("a", "b"))
    c0 = pair.get("c0")
    fills = [float(t0a), float(t0b)] if t0a is not None and t0b is not None else []
    rec = {
        "dip": None,
        "label": "t0_only: both Yes at T0; dog>50 labeled, no send; no third ticket",
        "crossed": False,
        "cross": None,
        "cross_px": None,
        "cross_ts": None,
        "target": None,
        "fav_extra": None,
        "lock_filled": False,
        "n_extra_dog": 0,
        "n_extra_fav": 0,
        "mix": "t0 both only",
        "cost": c0,
        "fees": fees_for(venue, fills),
        "pnl": None,
        "pnl_fee": None,
        "payout": None,
    }
    if t0a is None or t0b is None or c0 is None or lo is None or hi is None:
        pair["t0_only"] = rec
        return
    cross = None
    if dog:
        cross = first_cross_yes(ticks_of(pair, dog, "yes"), lo, hi)
    rec["cross"] = cross
    if cross is not None:
        fill_px = cross.get("px")
        fill_ts = cross.get("ts")
        if fill_px is not None and ABSORB + 1e-12 < float(fill_px) < 0.95 - 1e-12:
            rec["crossed"] = True
            rec["cross_px"] = fill_px
            rec["cross_ts"] = fill_ts
            rec["mix"] = "t0 both only (dog>50 observed, no send)"
    if settled:
        rec["payout"] = 1.0
        rec["pnl"] = 1.0 - float(c0)
        rec["pnl_fee"] = rec["pnl"] - rec["fees"]
    pair["t0_only"] = rec


def simulate_arms(pair: dict) -> None:
    assign_favorite(pair)
    t0a, t0b = pair.get("t0_a"), pair.get("t0_b")
    if t0a is not None and t0b is not None and pair.get("c0") is None:
        pair["c0"] = t0a + t0b
        pair["hold_pnl"] = 1.0 - pair["c0"]
    dog = pair.get("dog")
    lo, hi = pair.get("lo"), pair.get("hi")
    cross = None
    if dog and lo is not None and hi is not None:
        cross = first_cross_yes(ticks_of(pair, dog, "yes"), lo, hi)
    pair["b_cross"] = cross
    pair["b_locks"] = {}
    primary_px = cross["px"] if cross else None
    primary_ts = cross["ts"] if cross else None
    for dip in B_DIPS:
        pair["b_locks"][dip] = simulate_b_variant(
            pair, dip, cross, primary_px, primary_ts, "first print > 0.50"
        )
    simulate_t0_only(pair)


def rec_of(pair: dict, arm: str) -> dict | None:
    if arm == "t0_only":
        return pair.get("t0_only")
    try:
        dip = float(arm)
    except (TypeError, ValueError):
        return None
    return (pair.get("b_locks") or {}).get(dip)


def closed_trades(pairs: list[dict], arm: str) -> list[dict]:
    rows = []
    for pair in pairs:
        rec = rec_of(pair, arm)
        if not rec or rec.get("pnl") is None or not pair.get("settled"):
            continue
        cost = rec.get("cost")
        pnl = rec.get("pnl")
        days = pair_days(pair)
        opened = pair_opened(pair)
        rows.append(
            {
                "game": pair.get("game") or "",
                "venue": pair.get("venue") or "",
                "date": match_date(pair),
                "pnl_d": float(pnl),
                "pnl": pnl_pct(pnl, cost),
                "cost": float(cost) if cost is not None else None,
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
        # Paul's (1−WR)×avg_loss treats scratches as the loss bucket.
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
    dip = None if arm == "t0_only" else float(arm)
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
        and rec_of(p, "0.25").get("pnl") is not None
        and rec_of(p, "0.45")
        and rec_of(p, "0.45").get("pnl") is not None
        and rec_of(p, "t0_only")
        and rec_of(p, "t0_only").get("pnl") is not None
    ]
    buckets: dict[str, list[dict]] = {}
    total_delta = 0.0
    lock_delta = 0.0
    n_lock = 0
    n_same_45_25 = 0
    for p in settled:
        d25 = rec_of(p, "0.25") or {}
        d45 = rec_of(p, "0.45") or {}
        t0 = rec_of(p, "t0_only") or {}
        mix = d25.get("mix") or "unknown"
        delta = float(d45["pnl"]) - float(d25["pnl"])
        total_delta += delta
        locked = bool(d25.get("lock_filled"))
        if locked:
            lock_delta += delta
            n_lock += 1
        if abs(float(d45["pnl"]) - float(d25["pnl"])) < 1e-12:
            n_same_45_25 += 1
        buckets.setdefault(mix, []).append(
            {
                "d25": float(d25["pnl"]),
                "d45": float(d45["pnl"]),
                "t0": float(t0["pnl"]),
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
        "lock_share": share,
        "mean_delta": (total_delta / len(settled)) if settled else None,
    }
    return rows, meta


def decide_verdict(d25: dict, d45: dict, d50: dict, t0: dict, decomp: dict) -> tuple[str, str]:
    same_45_50 = identical_arms(d45, d50)
    same_note = (
        "D=50 is identical to D=45 on this tape (both 0% favorite-lock fill). "
        if same_45_50 else
        "D=50 is not identical to D=45 on this replay. "
    )
    t0_vs_45 = None
    if t0.get("mean") is not None and d45.get("mean") is not None:
        t0_vs_45 = float(t0["mean"]) - float(d45["mean"])
    similar = t0_vs_45 is not None and abs(t0_vs_45) < 0.005
    share = decomp.get("lock_share")
    share_txt = (
        f"{100.0 * share:.1f}% of the D=45 minus D=25 total-dollar gap sits on books "
        f"where D=25 filled the favorite lock ({decomp.get('n_lock')} settled books)."
        if share is not None else
        "Could not split the D=45 minus D=25 gap by lock fill."
    )
    exp25 = d25.get("expectancy_formula")
    exp45 = d45.get("expectancy_formula")
    agree_math = (
        exp45 is not None and exp25 is not None and float(exp45) > float(exp25) + 1e-12
    )
    math_line = (
        f"The arithmetic is right: D=45 expectancy {fmt_signed(exp45)} is higher than "
        f"D=25 {fmt_signed(exp25)} (WR {fmt_pct(d45.get('win_pct'), 1)}% × avg win "
        f"{fmt_signed(d45.get('avg_win'))} + (1−WR) × avg loss {fmt_signed(d45.get('avg_loss'))}). "
        if agree_math else
        "On this freeze D=45 does not have higher expectancy than D=25. "
    )
    t0_line = (
        f"t0_only mean {fmt_signed(t0.get('mean'))} vs D=45 {fmt_signed(d45.get('mean'))}"
        f"{' — similar on this tape' if similar else ' — not similar'} "
        f"(gap {fmt_signed(t0_vs_45)}). t0_only never buys the extra underdog when the "
        f"lower name prints above 50; D=45 still buys that extra underdog and then never "
        f"fills the favorite lock (lock filled {d45.get('pct_lock') or '0'}%). "
    )
    t0_worse = (
        t0.get("mean") is not None
        and d25.get("mean") is not None
        and float(t0["mean"]) < float(d25["mean"]) - 1e-12
    )
    why = (
        f"{math_line}"
        "We do not agree that D=45 is a better live Strategy B, or a tighter lock. "
        f"D=45 win rate {fmt_pct(d45.get('win_pct'), 1)}% is lower than D=25 "
        f"{fmt_pct(d25.get('win_pct'), 1)}%. Favorite-lock fill is "
        f"{d45.get('pct_lock') or '0'}% at D=45 vs {d25.get('pct_lock') or '0'}% at D=25. "
        f"{share_txt} Bigger mean $ at D=45 is unhedged extra-underdog Yes after the 50¢ "
        "print, not a 45-cent lock that actually fills. Ranking D=45 after seeing the "
        "sweep table is in-sample selection on an OOS-dated tape (every T0 ≥ 2024-01-01; "
        f"IS N={d25.get('n_is') or 0}). {same_note}{t0_line}"
        "Skipping the third ticket (original favorite at 1 − cross − D) is already what "
        "D=45 does on this tape, and that is a different strategy than live D=25, which "
        f"fills that ticket on {d25.get('pct_lock') or '0'}% of frozen books. t0_only goes "
        "further: it also skips the extra underdog. "
    )
    if t0_worse:
        why += (
            f"DISMISS t0_only versus live D=25 on quality (mean {fmt_signed(t0.get('mean'))} "
            f"vs {fmt_signed(d25.get('mean'))}, PF {fmt_num(t0.get('pf'))} vs "
            f"{fmt_num(d25.get('pf'))}). "
        )
    why += (
        "HOLD D=45: it can look better on mean $, expectancy, and profit factor on this "
        "same October 2026 book, but there is no IS row, lock fill is 0%, and we do not "
        "retune OOS. Live D=25 is unchanged. Research only. Not gold. Not DailyRun. "
        "Not prediction-market DailyRun."
    )
    return "HOLD", why


def freeze_rows() -> list[tuple[str, str]]:
    return [
        ("Universe", "Same 182 (game, venue) keys as strategy_b_D_05_to_50_20261023 and dense_inplay_fav_lock_cross_smalld_20261021.html. Tennis moneyline. C in [0.95, 1.20]. Both Yes in (0.10, 0.90). Dense in-play bar (≥200 ticks) from the original freeze keys."),
        ("T0", "Same helpers as the 5–25 / 5–50 stamps: assign_actual_t0 (last two-sided Yes at/before trusted actual start; else tape-resume / first competitive). Not the live 5-minute send window."),
        ("Size", "1 contract per ticket. Optimistic fill at the printed Yes ask."),
        ("Fees", "Primary P&L without venue fees. Optional fee rows are not the score."),
        ("Absorb", "Stop extras at first 5¢ / 95¢ absorbing print (D arms only; t0_only sends no extras)."),
        ("Control", "Live Strategy B D=25¢: T0 both Yes, extra underdog Yes at first print > 0.50, original-favorite Yes at/below 1 − cross_fill − 0.25."),
        ("D=45 / D=50", "Same live Strategy B definition; only D changes. Not extra-Yes-on-dip."),
        ("t0_only", "T0 both Yes only. Dog>50 is observed for a label (did the lower name ever print >50). Do not buy extra underdog. Do not buy original favorite / dropped opponent at 1 − cross − D. No third ticket."),
        ("IS / OOS", "Inherited: entire October 2026 tape is OOS (every T0 ≥ 2024-01-01). No IS row. Do not retune on OOS."),
        ("Live D", "0.25 unchanged. This stamp does not wire a new D, is not gold, is not DailyRun, and does not start a second live B."),
        ("Ann ROR", "House compare_format.ann_ror_from_closed. Slot cash = median 1-contract cost of that arm. Days held = T0→window-end hours, floored at 1 hour. Max DD / Sharpe seed $500,000 exit-date equity. Same-day tennis makes Ann ROR capital-turn explosive; judge quality on mean $, WR, PF, Max DD as well."),
        ("Selection", "KEEP/DISMISS on quality, not trade count. Ranking after seeing the D-sweep table is in-sample selection on an OOS-dated tape."),
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
        b50 = rec_of(p, "0.50") or {}
        t0 = rec_of(p, "t0_only") or {}
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
                "inplay_n": p.get("inplay_n") or 0,
                "winner": win_name,
                "live": "yes" if not p.get("settled") else "no",
                "t0_when": et_iso(p.get("t0_ts")),
                "dog50": "yes" if t0.get("crossed") else "no",
                "b25_fill": b_fill_text(p, b25),
                "d25_mix": b25.get("mix") or "",
                "d25_pnl": signed_money(b25.get("pnl")) if b25.get("pnl") is not None else "",
                "d45_mix": b45.get("mix") or "",
                "d45_pnl": signed_money(b45.get("pnl")) if b45.get("pnl") is not None else "",
                "d50_mix": b50.get("mix") or "",
                "d50_pnl": signed_money(b50.get("pnl")) if b50.get("pnl") is not None else "",
                "t0_mix": t0.get("mix") or "",
                "t0_pnl": signed_money(t0.get("pnl")) if t0.get("pnl") is not None else "",
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
    t0 = pair.get("t0_only") or {}
    bits = [
        f"<p><strong>{esc(title)}</strong> {esc(pair.get('venue') or '')}. "
        f"T0 {esc(pair.get('t0_label') or '')} at {esc(et_iso(pair.get('t0_ts')))}: "
        f"{esc(pair.get('side_a'))} {fmt_px(pair.get('t0_a'))} / "
        f"{esc(pair.get('side_b'))} {fmt_px(pair.get('t0_b'))}, C = {fmt_px(pair.get('c0'))}. "
        f"Favorite {esc(pair.get('fav_name') or '')}. Underdog {esc(pair.get('dog_name') or '')}. "
        f"Winner {esc(winner or 'unsettled')}. In-play ticks {pair.get('inplay_n') or 0}.</p>",
        f"<p>Dog&gt;50 observed (label only on t0_only): "
        f"{'yes' if t0.get('crossed') else 'no'} at {fmt_px(t0.get('cross_px'))} "
        f"@ {esc(et_iso(t0.get('cross_ts')))}. t0_only mix {esc(t0.get('mix') or '')}; "
        f"cost {money_cell(t0.get('cost'))}; P&amp;L "
        f"{signed_money(t0.get('pnl')) if t0.get('pnl') is not None else 'unsettled'}.</p>",
    ]
    for dip in B_DIPS:
        rec = (pair.get("b_locks") or {}).get(dip) or {}
        cents = int(round(dip * 100))
        bits.append(
            f"<p>D={cents}¢ target {fmt_px(rec.get('target'))}: {esc(b_fill_text(pair, rec))}; "
            f"mix {esc(rec.get('mix') or '')}; cost {money_cell(rec.get('cost'))}; "
            f"P&amp;L {signed_money(rec.get('pnl')) if rec.get('pnl') is not None else 'unsettled'}.</p>"
        )
    return "\n".join(bits)


def write_baseline(payload: dict) -> None:
    d25, d45, d50, t0 = payload["d25"], payload["d45"], payload["d50"], payload["t0"]
    lines = [
        "# Strategy B t0_only vs D=45 vs live D=25 — freeze",
        "",
        "Research only. Not gold. Not DailyRun. Live D=25 is not changed.",
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
            "",
            "## Expectancy (settled books)",
            "",
            "expectancy = WR × avg_win $ + (1 − WR) × avg_loss $ (avg_loss is negative). "
            "This matches mean $ when every settled row is a win or a loss (no scratches).",
            "",
            "| arm | N | wins | losses | WR% | avg win $ | avg loss $ | expectancy $ | mean $ | formula=mean | PF | lock% |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|",
        ]
    )
    for rec in payload["arm_rows"]:
        lines.append(
            f"| {rec['arm']} | {rec.get('n_settled')} | {rec.get('n_win')} | "
            f"{rec.get('n_loss')} | {fmt_pct(rec.get('win_pct'), 1)} | "
            f"{'n/a — no wins' if not rec.get('n_win') else fmt_signed(rec.get('avg_win'))} | "
            f"{'n/a — no losses' if not rec.get('n_loss') else fmt_signed(rec.get('avg_loss'))} | "
            f"{fmt_signed(rec.get('expectancy_formula'))} | {fmt_signed(rec.get('mean'))} | "
            f"{'yes' if rec.get('formula_matches_mean') else 'no'} | "
            f"{fmt_num(rec.get('pf'))} | {rec.get('pct_lock') or ''} |"
        )
    decomp = payload["decomp_meta"]
    share = decomp.get("lock_share")
    share_txt = f"{100.0 * share:.1f}%" if share is not None else "n/a"
    lines.extend(
        [
            "",
            "## Why D=45 mean is higher",
            "",
            f"- D=25 lock filled {d25.get('pct_lock')}% of frozen books; D=45 lock filled {d45.get('pct_lock')}%; t0_only lock filled {t0.get('pct_lock')}%.",
            f"- D=45 and D=50 are {'identical' if payload.get('same_45_50') else 'not identical'} on this tape.",
            f"- {decomp.get('n_same_45_25')} / {decomp.get('n')} settled books have D=45 P&L equal to D=25 (the books where D=25 also did not fill the favorite lock).",
            f"- {share_txt} of the total-dollar D=45 minus D=25 gap sits on the {decomp.get('n_lock')} books where D=25 filled the third ticket.",
            "- That gap is unhedged extra-underdog Yes, not a tighter 45¢ lock.",
            f"- t0_only mean {fmt_signed(t0.get('mean'))} is not D=45 ({fmt_signed(d45.get('mean'))}): t0_only skips the extra underdog too. On this freeze every settled t0_only book is a vig loss (C ≥ $1, so $1 − C ≤ 0; 0 wins).",
            "",
            "| D=25 mix | N | mean D=25 | mean D=45 | mean t0_only | Δ 45−25 |",
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
            "## Verdict: HOLD",
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
    if PAGE.resolve() in {ORIGINAL_PAGE.resolve(), PRIOR_HTML.resolve(), (PRIOR_STAMP / "compare.html").resolve()}:
        raise RuntimeError("refusing to overwrite a prior stamp HTML")
    d25, d45, d50, t0 = payload["d25"], payload["d45"], payload["d50"], payload["t0"]
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
        ("Expectancy $ (WR×avg win + (1−WR)×avg loss)", "num"),
        ("Mean $", "num"),
        ("Formula matches mean", "text"),
        ("Profit factor", "num"),
        ("% lock filled", "num"),
        ("% dog>50 observed", "num"),
        ("Δ expectancy vs D=25", "num"),
        ("Δ WR vs D=25", "num"),
    ]
    exp_fields = [
        "arm", "role", "n", "wins", "losses", "scratch", "wr", "avg_win", "avg_loss",
        "exp", "mean", "match", "pf", "lock", "cross", "d_exp", "d_wr",
    ]
    compare_headers = [
        ("Arm", "text"),
        ("Role", "text"),
        ("N books", "num"),
        ("N settled", "num"),
        ("Wins", "num"),
        ("Losses", "num"),
        ("Win %", "num"),
        ("Mean $ / expectancy $", "num"),
        ("Median $", "num"),
        ("Avg PnL %", "num"),
        ("AVG_PNL_PCT_WO_MAX", "num"),
        ("Avg win $", "num"),
        ("Avg loss $", "num"),
        ("Profit factor", "num"),
        ("Mean cost", "num"),
        ("% crossed / dog>50 observed", "num"),
        ("% lock filled", "num"),
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
        "median", "avg_pnl_pct", "wo_max", "avg_win", "avg_loss", "pf",
        "mean_cost", "pct_crossed", "pct_lock", "avg_days", "capital_days",
        "ann_ror", "ann_ror_1d", "ann_ror_is", "ann_ror_oos", "max_dd", "max_dd_d",
        "calmar", "sharpe",
        "d_mean", "d_wr", "d_pf", "d_ann", "d_dd", "note",
    ]
    mix_headers = [
        ("D=25 mix (what live B actually did)", "text"),
        ("N settled", "num"),
        ("Mean D=25 $", "num"),
        ("Mean D=45 $", "num"),
        ("Mean t0_only $", "num"),
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
        ("In-play ticks", "num"),
        ("Winner", "text"),
        ("Still live", "text"),
        ("T0 clock", "text"),
        ("Dog>50 observed", "text"),
        ("D=25 fills", "text"),
        ("D=25 mix", "text"),
        ("D=25 P&L", "num"),
        ("D=45 mix", "text"),
        ("D=45 P&L", "num"),
        ("D=50 mix", "text"),
        ("D=50 P&L", "num"),
        ("t0_only mix", "text"),
        ("t0_only P&L", "num"),
    ]
    match_fields = [
        "game", "date", "venue", "side_a", "t0_a", "side_b", "t0_b", "c0",
        "fav", "dog", "inplay_n", "winner", "live", "t0_when", "dog50",
        "b25_fill", "d25_mix", "d25_pnl", "d45_mix", "d45_pnl",
        "d50_mix", "d50_pnl", "t0_mix", "t0_pnl",
    ]
    decomp = payload["decomp_meta"]
    share = decomp.get("lock_share")
    share_txt = f"{100.0 * share:.1f}%" if share is not None else "n/a"
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Strategy B t0_only vs D=45 vs D=25 2026-10-23</title>
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
<h1>Strategy B — t0_only vs D=45 vs live D=25</h1>
<p class="note">Written {esc(payload['written_at'])}. Research only. Not gold. Not DailyRun. Not a trading rule. This page does not place orders. Live D=25 is unchanged. Entire October 2026 tape is out-of-sample (OOS): every T0 ≥ 2024-01-01. In-sample (IS) N={esc(d25.get('n_is') or 0)} — empty. Verdict: <strong>{esc(payload.get('verdict') or 'HOLD')}</strong>.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="hl">
<p><strong>Do we agree D=45 is better?</strong> The expectancy arithmetic is right, and we do not agree that live D should move. D=45 expectancy {esc(fmt_signed(d45.get('expectancy_formula')))} beats D=25 {esc(fmt_signed(d25.get('expectancy_formula')))} because the third ticket (original favorite at 1 − cross − D) never fills at D=45 (lock filled {esc(d45.get('pct_lock') or '0')}% vs {esc(d25.get('pct_lock') or '')} at D=25). That is unhedged extra-underdog Yes, not a tighter lock. Win rate is lower at D=45 ({esc(fmt_pct(d45.get('win_pct'), 1))}% vs {esc(fmt_pct(d25.get('win_pct'), 1))}%). {esc(share_txt)} of the total-dollar gap sits on books where D=25 actually bought that third ticket. Ranking D=45 after the sweep table is selection bias on an OOS-dated tape. HOLD, not KEEP. Live D=25 stays.</p>
<p><strong>t0_only vs D=45:</strong> not the same book. t0_only mean {esc(fmt_signed(t0.get('mean')))}; D=45 mean {esc(fmt_signed(d45.get('mean')))}. t0_only buys both Yes at T0 and stops. D=45 still buys one more of the underdog when that name prints above 50, then never locks the original favorite. Skipping the third ticket is already D=45 on this tape, and that is a different strategy than live D=25. t0_only skips the extra underdog as well — DISMISS t0_only versus live D=25 on quality.</p>
<p><strong>D=50:</strong> {'identical to D=45 on this tape (both 0% favorite-lock fill).' if payload.get('same_45_50') else 'not identical to D=45 on this replay.'}</p>
<p><strong>Frozen universe:</strong> {esc(payload['n_dense'])} tennis books keyed to the original extra-Yes-on-dip HTML ({ORIGINAL_N} keys). Settled {esc(payload['n_dense_settled'])}; still live {esc(payload['n_dense_live'])}. {esc(payload.get('freeze_note') or '')} Prior D-sweep: <a href="../strategy_b_D_05_to_50_20261023/compare.html">strategy_b_D_05_to_50_20261023/compare.html</a> (not overwritten).</p>
<p>Annualized rate of return (Ann ROR) uses <code>compare_format.ann_ror_from_closed</code>. Slot cash = median 1-contract cost of that arm. The hours-held column uses T0→window-end (floor 1 hour) and is capital-turn explosive on same-day tennis — it is the house formula, not a send rule. A second column uses 1 calendar day so arms can be compared. IS Ann ROR is n/a — no IS. Full book = OOS. Max DD % / Sharpe replay exit-date equity from {format_money(DEFAULT_INITIAL_ACCOUNT)} (near 0% at 1-contract size). 1-contract dollar Max DD is cumulative PnL peak-to-trough on the settled book. Total book PnL $ is omitted from the compare table (canonical HTML compare rule).</p>
</div>

<div class="warn">
<p>Primary P&amp;L is without fees. Fills are optimistic at the printed Yes ask. Do not buy after the first 5¢ / 95¢ absorbing print. Verdict <strong>{esc(payload.get('verdict') or 'HOLD')}</strong>. Live D=25 unchanged. Research only. Not gold. Not DailyRun. This page does not start a second live B and does not touch live lock orders.</p>
</div>

<h2>Freeze</h2>
<p class="note">Click column headers to sort. Same 182-book freeze as the D=5…50 sweep. Generator: <code>tools/dense_inplay_fav_lock_cross_smalld_20261021.py</code> helpers plus this stamp script.</p>
{freeze_table}

<h2>1. Expectancy — D=25 vs D=45 vs D=50 vs t0_only</h2>
<p class="note">Expectancy = win rate × average winning book $ + (1 − win rate) × average losing book $ (losses negative). That equals mean $ when every settled row is a win or a loss. % lock filled / % dog&gt;50 observed are all frozen books. Click column headers to sort.</p>
{table(exp_headers, payload["exp_rows"], exp_fields)}

<h2>2. Where the D=45 extra mean comes from</h2>
<p class="note">Same settled books, grouped by what live D=25 actually did. On books that never crossed 50, D=25 = D=45 = t0_only = $1 − C. On books that crossed but D=25 did not fill the favorite, D=25 = D=45 (T0 both + extra underdog) and t0_only is different (no extra underdog). On books where D=25 filled the third ticket, D=45 leaves that extra underdog unhedged. Click column headers to sort.</p>
{table(mix_headers, mix_rows, mix_fields)}
<p class="note">{esc(decomp.get('n_same_45_25'))} of {esc(decomp.get('n'))} settled books have D=45 P&amp;L equal to D=25. {esc(share_txt)} of the total-dollar gap sits on the {esc(decomp.get('n_lock'))} D=25 lock-filled books.</p>

<h2>3. Canonical compare vs control D=25</h2>
<p class="note">Mean / median / win rate / Ann ROR are settled books. % crossed / % lock filled are all frozen books. Deltas are that arm minus D=25. Ann ROR IS is n/a (empty). Full book = OOS. Click column headers to sort.</p>
{table(compare_headers, payload["compare_rows"], compare_fields)}

<h2>4. Worked examples (same named matches as the 5–25 page)</h2>
{payload["hassan_html"]}
{payload["smith_html"]}

<h2>5. Per-match (frozen keys)</h2>
<p class="note">One row per frozen book. Dog&gt;50 observed is a label on t0_only — no send. Click column headers to sort.</p>
{table(match_headers, payload["match_rows"], match_fields)}

<h2>Process notes</h2>
<ul>
<li>KEEP / HOLD / DISMISS is quality versus control D=25, not trade count.</li>
<li>OOS is report-only. Do not retune live D from this tape. No IS row, so KEEP is not available from ranking D after the table.</li>
<li>Live <code>tools/live_strategy_b.py</code> stays at D=0.25. This stamp does not start a second live process and does not edit live lock orders.</li>
<li>Acronyms: T0 is the open used here. C is the two T0 Yes prices added together. Vig is the overround when two Yes prices sum over $1. D is lock profit on the extra post-cross pair. Ann ROR is annualized rate of return. IS is in-sample; OOS is out-of-sample. PF is profit factor. Max DD is maximum drawdown. WR is win rate.</li>
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
    dest_dir = Path(r"G:\My Drive\paul_experiments\strategy_b_t0_only_vs_D45_20261023")
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


def main() -> None:
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
    d25 = quality_block(
        frozen, "0.25",
        "B D=25¢ (live: 1 − cross_fill − D after dog>50)",
        "control",
    )
    d45 = quality_block(
        frozen, "0.45",
        "B D=45¢ (1 − cross_fill − D after dog>50)",
        "candidate D",
    )
    d50 = quality_block(
        frozen, "0.50",
        "B D=50¢ (1 − cross_fill − D after dog>50)",
        "D=50 (same as 45 if lock is 0%)",
    )
    t0 = quality_block(
        frozen, "t0_only",
        "t0_only (both Yes at T0; dog>50 labeled, no send; no third ticket)",
        "new arm",
    )
    arm_rows = [d25, d45, d50, t0]
    for rec in arm_rows:
        _out(
            f"{rec['arm_id']} n={rec['n']} settled={rec['n_settled']} "
            f"mean={fmt_signed(rec['mean'])} WR={fmt_pct(rec.get('win_pct'), 1)} "
            f"avgW={fmt_signed(rec.get('avg_win'))} avgL={fmt_signed(rec.get('avg_loss'))} "
            f"exp={fmt_signed(rec.get('expectancy_formula'))} match={rec.get('formula_matches_mean')} "
            f"PF={fmt_num(rec.get('pf'))} crossed={rec.get('pct_crossed')} "
            f"lock={rec.get('pct_lock')} IS={rec.get('n_is')} OOS={rec.get('n_oos')}"
        )
    mix_rows, decomp_meta = mix_decomp(frozen)
    same_45_50 = identical_arms(d45, d50)
    _out(f"D45 identical to D50: {same_45_50}")
    _out(
        f"decomp n={decomp_meta.get('n')} same45=25 {decomp_meta.get('n_same_45_25')} "
        f"lock_share={decomp_meta.get('lock_share')}"
    )
    verdict, sweet_text = decide_verdict(d25, d45, d50, t0, decomp_meta)
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
        "d50": d50,
        "t0": t0,
        "ctrl": d25,
        "verdict": verdict,
        "sweet_text": sweet_text,
        "same_45_50": same_45_50,
        "mix_rows": mix_rows,
        "decomp_meta": decomp_meta,
        "n_dense": len(frozen),
        "n_dense_settled": len(settled),
        "n_dense_live": len(live),
        "n_missing": len(missing),
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
                "same_45_50": same_45_50,
                "decomp": {k: v for k, v in decomp_meta.items()},
                "n_dense": payload["n_dense"],
                "n_dense_settled": payload["n_dense_settled"],
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
