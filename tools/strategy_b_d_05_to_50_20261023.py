"""Strategy B D lock-profit sweep 5¢…50¢ on the frozen dense tennis book.

Research only. Reads local price_memory (archive + dated shards) and official
settlements. Does not place, cancel, or amend orders. Does not print secrets.
Does not touch orders_stopped.json. Does not start live_strategy_b.py.
Does not change live D=0.25. Not gold. Not DailyRun.

Reuses the 2026-10-21 freeze (same 182 game×venue keys, T0 helpers, 1 contract,
primary P&L without fees). One knob: D. Live Strategy B definition:
favorite Yes at/below 1 − cross_fill − D after T0-underdog Yes > 0.50.
"""
from __future__ import annotations

import json
import math
import shutil
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import report_page_extras
from compare_format import (
    DEFAULT_INITIAL_ACCOUNT,
    ann_ror_from_closed,
    format_money,
    format_money_delta,
    overlay_ann_ror_max_dd,
)
from dense_inplay_fav_lock_cross_smalld_20261021 import (
    ORIGINAL_N,
    ORIGINAL_PAGE,
    ORIGINAL_SETTLED,
    assign_favorite,
    b_fill_text,
    first_cross_yes,
    freeze_keys_from_original_html,
    pair_key,
    simulate_b_variant,
    summarize_b,
    ticks_of,
)
from dense_inplay_yes_dip_20261021 import (
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
from tennis_decade_at_start_20261020 import start_lookup_from
from tennis_dual_yes_dip_no_20261021 import (
    et_iso,
    fmt_px,
    fmt_signed,
    last_name,
    mean,
    median,
    named_pairs,
)

ET = ZoneInfo("America/New_York")
STAMP = ROOT / "drive" / "paul_experiments" / "strategy_b_D_05_to_50_20261023"
PAGE = STAMP / "compare.html"
BASELINE = STAMP / "BASELINE.md"
ARMS_JSON = STAMP / "arms.json"
CONTROL_D = 0.25
B_DIPS = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50)
HOUR = 1.0 / 24.0
PRIOR_HTML = (
    ROOT
    / "drive"
    / "paul_experiments"
    / "prediction_market_arb_exhaustive_20261017"
    / "dense_inplay_fav_lock_cross_smalld_20261021.html"
)

ASKED = (
    "Paul: run further testing on Strategy B where we see if the results improve with "
    "30, 35, 40, 45, and 50; compare these to what we had with 5...25."
)

PLAIN = (
    "Strategy B is a tennis moneyline idea. A Yes is a ticket that pays $1 if that named "
    "player wins. At the open we use here (T0) we buy Yes on both players, one contract "
    "each. Only one can win, so those two tickets always pay $1; if they cost $1.01 you "
    "are already down a penny (vig, the house overround). If the original underdog’s Yes "
    "later prints strictly above 50 cents, we buy one more of that name. Then we try to "
    "buy one more of the original favorite cheap enough that the extra pair locks a D-cent "
    "profit: favorite Yes at or below 1 − the underdog cross fill − D. Live D is 25 cents. "
    "This page keeps that definition and only changes D: 5, 10, 15, 20, 25, 30, 35, 40, 45, "
    "and 50 cents on the same frozen book. Extra-Yes-on-dip (buy more of a falling Yes) was "
    "already DISMISS and is not rerun as the score. Bigger D means a cheaper favorite target, "
    "so fewer extra locks fill and more books sit on an unhedged extra underdog Yes. "
    "Primary P&L is without venue fees. Fills are optimistic at the printed Yes. The whole "
    "October 2026 tape is out-of-sample (OOS): every T0 is on or after 2024-01-01. There is "
    "no in-sample (IS) row — that split is inherited from the 5–25 stamp. Research only. "
    "Not gold. Not DailyRun. Live D=25 is not changed."
)


def _out(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


def fmt_pct(value, digits: int = 2) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return "n/a"
    return f"{number:.{digits}f}"


def fmt_ann(value) -> str:
    if value is None or value == "":
        return "n/a"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return "n/a"
    if abs(number) >= 10000:
        return f"{number:.3e}%"
    return f"{number:.2f}%"


def dollar_drawdown(trades: list[dict]) -> float | None:
    if not trades:
        return None
    ordered = sorted(
        trades,
        key=lambda t: (t.get("closed") is None, t.get("closed"), t.get("date") or ""),
    )
    equity = 0.0
    peak = 0.0
    dd = 0.0
    for row in ordered:
        equity += float(row.get("pnl_d") or 0.0)
        if equity > peak:
            peak = equity
        dd = min(dd, equity - peak)
    return abs(dd)


def fmt_num(value, digits: int = 2) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return "n/a"
    return f"{number:.{digits}f}"


def delta_num(cand, ctrl, digits: int = 2) -> str:
    if cand is None or ctrl is None:
        return ""
    try:
        a, b = float(cand), float(ctrl)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(a) or not math.isfinite(b):
        return ""
    return f"{a - b:+.{digits}f}"


def delta_money(cand, ctrl) -> str:
    if cand is None or ctrl is None:
        return ""
    try:
        a, b = float(cand), float(ctrl)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(a) or not math.isfinite(b):
        return ""
    return format_money_delta(a - b)


def pick_named(pairs: list[dict], *needles: str, venue: str = "polymarket") -> dict | None:
    found = named_pairs(pairs, *needles)
    if not found:
        return None
    want = venue.lower()
    for pair in found:
        if str(pair.get("venue") or "").lower() == want:
            return pair
    return found[0]


def simulate_b_dips(pair: dict) -> None:
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


def pair_days(pair: dict) -> float:
    t0 = pair.get("t0_ts")
    hi = pair.get("hi")
    if t0 is None:
        return 1.0
    end = hi if hi is not None else t0
    elapsed = max(0.0, float(end) - float(t0)) / 86400.0
    return max(elapsed, HOUR)


def pair_opened(pair: dict):
    t0 = pair.get("t0_ts")
    if t0 is None:
        return None
    return datetime.fromtimestamp(int(t0), ET)


def pair_closed(pair: dict):
    hi = pair.get("hi")
    if hi is not None:
        return datetime.fromtimestamp(int(hi), ET)
    opened = pair_opened(pair)
    if opened is None:
        return None
    return opened


def pnl_pct(pnl, cost) -> float | None:
    if pnl is None or cost is None:
        return None
    try:
        c = float(cost)
        if c <= 1e-12:
            return None
        return 100.0 * float(pnl) / c
    except (TypeError, ValueError):
        return None


def closed_trades(pairs: list[dict], dip: float) -> list[dict]:
    rows = []
    for pair in pairs:
        rec = (pair.get("b_locks") or {}).get(dip)
        if not rec or rec.get("pnl") is None or not pair.get("settled"):
            continue
        cost = rec.get("cost")
        pnl = rec.get("pnl")
        days = pair_days(pair)
        rows.append(
            {
                "game": pair.get("game") or "",
                "venue": pair.get("venue") or "",
                "date": match_date(pair),
                "pnl_d": float(pnl),
                "pnl": pnl_pct(pnl, cost),
                "cost": float(cost) if cost is not None else None,
                "days": days,
                "opened": pair_opened(pair),
                "closed": pair_closed(pair),
                "crossed": bool(rec.get("crossed")),
                "lock_filled": bool(rec.get("lock_filled")),
                "mix": rec.get("mix") or "",
            }
        )
    return rows


def quality_block(pairs: list[dict], dip: float, summary: dict) -> dict:
    trades = closed_trades(pairs, dip)
    pnls = [t["pnl_d"] for t in trades]
    pcts = [t["pnl"] for t in trades if t.get("pnl") is not None]
    costs = [t["cost"] for t in trades if t.get("cost") is not None]
    days = [t["days"] for t in trades if t.get("days")]
    wins = [x for x in pnls if x > 1e-12]
    losses = [x for x in pnls if x < -1e-12]
    n = len(trades)
    n_win = len(wins)
    n_loss = len(losses)
    sum_win = sum(wins)
    sum_loss = abs(sum(losses))
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
    max_dd_d = dollar_drawdown(trades)
    cents = int(round(dip * 100))
    role = "control" if abs(dip - CONTROL_D) < 1e-12 else (
        "prior 5–25" if dip <= 0.25 + 1e-12 else "new 30–50"
    )
    return {
        "dip": dip,
        "cents": cents,
        "arm": f"B D={cents}¢ (1 − cross_fill − D after dog>50)",
        "role": role,
        "n": summary.get("n"),
        "n_settled": n,
        "n_win": n_win,
        "n_loss": n_loss,
        "win_pct": (100.0 * n_win / n) if n else None,
        "mean": mean(pnls),
        "median": median(pnls),
        "avg_pnl_pct": mean(pcts),
        "avg_pnl_pct_wo_max": wo,
        "expectancy": mean(pnls),
        "avg_win": mean(wins) if wins else None,
        "avg_loss": mean(losses) if losses else None,
        "pf": pf,
        "mean_cost": mean(costs),
        "median_cost": median_cost,
        "brt_cash": cash,
        "pct_crossed": summary.get("pct_crossed"),
        "pct_lock": summary.get("pct_lock"),
        "n_crossed": summary.get("n_crossed"),
        "n_lock": summary.get("n_lock"),
        "avg_days": mean(days) if days else None,
        "capital_days": overlay.get("capital_days"),
        "ann_ror": ann,
        "ann_ror_1d": ann_1d,
        "ann_ror_is": None,
        "ann_ror_oos": ann,
        "max_dd": max_dd,
        "max_dd_d": max_dd_d,
        "calmar": calmar,
        "sharpe": sharpe,
        "sharpe_source": overlay.get("sharpe_source") or "",
        "overlay_note": overlay.get("note") or "",
        "note": summary.get("note") or tiny_note(n),
        "trades": trades,
    }


def band_mean(rows: list[dict], lo: float, hi: float) -> float | None:
    vals = [r["mean"] for r in rows if r.get("mean") is not None and lo - 1e-12 <= r["dip"] <= hi + 1e-12]
    return mean(vals)


def decide_verdict(rows: list[dict]) -> tuple[str, str]:
    ctrl = next((r for r in rows if abs(r["dip"] - CONTROL_D) < 1e-12), None)
    new_rows = [r for r in rows if r["dip"] >= 0.30 - 1e-12]
    prior_rows = [r for r in rows if r["dip"] <= 0.25 + 1e-12]
    if ctrl is None or ctrl.get("mean") is None:
        return (
            "HOLD",
            "No settled control D=25 book to score. HOLD. Research only. Not gold. Not DailyRun.",
        )
    scored_new = [r for r in new_rows if r.get("mean") is not None]
    if not scored_new:
        return (
            "HOLD",
            "No settled 30–50 books. HOLD. Live D=25 unchanged. Research only. Not gold. Not DailyRun.",
        )
    best_new = max(scored_new, key=lambda r: (r["mean"], r.get("pf") or 0.0))
    best_prior = max(
        [r for r in prior_rows if r.get("mean") is not None],
        key=lambda r: (r["mean"], r.get("pf") or 0.0),
    )
    ctrl_mean = ctrl["mean"]
    better_mean = [r for r in scored_new if r["mean"] > ctrl_mean + 1e-12]
    better_pf = [
        r for r in scored_new
        if (r.get("pf") or 0.0) > (ctrl.get("pf") or 0.0) + 1e-12
    ]
    better_wr = [
        r for r in scored_new
        if (r.get("win_pct") or 0.0) > (ctrl.get("win_pct") or 0.0) + 1e-12
    ]
    worse_dd = []
    for r in scored_new:
        if r.get("max_dd") is None or ctrl.get("max_dd") is None:
            continue
        if float(r["max_dd"]) > float(ctrl["max_dd"]) + 1e-12:
            worse_dd.append(r)
    band_prior = band_mean(rows, 0.05, 0.25)
    band_new = band_mean(rows, 0.30, 0.50)
    lock45 = next((r for r in scored_new if r["cents"] == 45), None)
    lock_note = ""
    if lock45 is not None and int(lock45.get("n_lock") or 0) == 0:
        lock_note = (
            "D=45¢ and D=50¢ fill 0% favorite locks on this tape: the target sits at or below "
            "the 5¢ absorb, so the extra underdog Yes is never locked. Mean $ rising there is "
            "unhedged extra-dog Yes, not a tighter Strategy B lock. "
        )
    why = (
        f"Control is live Strategy B D=25¢ mean {fmt_signed(ctrl_mean)}, "
        f"WR {fmt_pct(ctrl.get('win_pct'), 1)}%, PF {fmt_num(ctrl.get('pf'))}, "
        f"Ann ROR (hours held) {fmt_ann(ctrl.get('ann_ror'))}, "
        f"Ann ROR if 1 calendar day {fmt_ann(ctrl.get('ann_ror_1d'))}, "
        f"1-contract dollar Max DD {format_money(ctrl.get('max_dd_d'))}. "
        f"Best 5–25 arm on this replay is D={best_prior['cents']}¢ mean "
        f"{fmt_signed(best_prior['mean'])}. Best 30–50 arm is D={best_new['cents']}¢ mean "
        f"{fmt_signed(best_new['mean'])}. Band mean 5–25 {fmt_signed(band_prior)}; "
        f"band mean 30–50 {fmt_signed(band_new)}. "
        f"{len(better_mean)} of 5 new D arms beat D=25 on mean $; "
        f"{len(better_pf)} on profit factor; {len(better_wr)} on win rate; "
        f"{len(worse_dd)} have worse (higher) $500k Max DD%. "
        f"{lock_note}"
    )
    new_improves = (
        best_new["mean"] > ctrl_mean + 1e-12
        and (best_new.get("pf") or 0.0) >= (ctrl.get("pf") or 0.0) - 1e-9
    )
    if not better_mean and (band_new is None or band_new <= (band_prior or 0.0) + 1e-12):
        tag = "DISMISS"
        why += (
            "DISMISS 30–50 versus control D=25: quality (mean $, and the 30–50 band) does not "
            "improve. Do not retune live D. "
        )
    elif new_improves:
        tag = "HOLD"
        why += (
            "30–50 can look better on this same October 2026 book, but every T0 is OOS and there "
            "is no IS row. Ranking D after seeing this table is in-sample selection on an OOS-dated "
            "tape. HOLD, not KEEP. Do not retune live D=25. "
        )
    else:
        tag = "HOLD"
        why += (
            "HOLD. 30–50 is mixed versus D=25 (mean/PF/WR/DD do not move together). OOS-only tape; "
            "do not retune OOS. Live D=25 unchanged. "
        )
    why += "Research only. Not gold. Not DailyRun. Not prediction-market DailyRun."
    return tag, why


def compare_row(rec: dict, ctrl: dict | None) -> dict:
    is_note = "n/a — no IS (all T0 ≥ 2024-01-01; prior stamp split kept)"
    ann_txt = fmt_ann(rec.get("ann_ror"))
    ann_1d = fmt_ann(rec.get("ann_ror_1d"))
    return {
        "arm": rec["arm"],
        "role": rec["role"],
        "n": rec.get("n"),
        "n_settled": rec.get("n_settled"),
        "wins": rec.get("n_win"),
        "losses": rec.get("n_loss"),
        "win_pct": fmt_pct(rec.get("win_pct"), 1),
        "mean": signed_money(rec.get("mean")),
        "median": signed_money(rec.get("median")),
        "avg_pnl_pct": fmt_pct(rec.get("avg_pnl_pct")),
        "wo_max": fmt_pct(rec.get("avg_pnl_pct_wo_max")),
        "expectancy": signed_money(rec.get("expectancy")),
        "avg_win": signed_money(rec.get("avg_win")),
        "avg_loss": signed_money(rec.get("avg_loss")),
        "pf": fmt_num(rec.get("pf")),
        "mean_cost": money_cell(rec.get("mean_cost")),
        "pct_crossed": rec.get("pct_crossed") or "",
        "pct_lock": rec.get("pct_lock") or "",
        "avg_days": fmt_num(rec.get("avg_days"), 3),
        "capital_days": fmt_num(rec.get("capital_days"), 2),
        "ann_ror": ann_txt,
        "ann_ror_1d": ann_1d,
        "ann_ror_is": is_note,
        "ann_ror_oos": ann_txt,
        "max_dd": fmt_pct(rec.get("max_dd"), 4),
        "max_dd_d": format_money(rec.get("max_dd_d")),
        "calmar": fmt_num(rec.get("calmar")),
        "sharpe": fmt_num(rec.get("sharpe")),
        "d_mean": delta_money(rec.get("mean"), ctrl.get("mean") if ctrl else None),
        "d_wr": delta_num(rec.get("win_pct"), ctrl.get("win_pct") if ctrl else None, 1),
        "d_pf": delta_num(rec.get("pf"), ctrl.get("pf") if ctrl else None),
        "d_ann": delta_num(rec.get("ann_ror_1d"), ctrl.get("ann_ror_1d") if ctrl else None),
        "d_dd": delta_money(rec.get("max_dd_d"), ctrl.get("max_dd_d") if ctrl else None),
        "note": rec.get("note") or "",
    }


def per_match_rows(pairs: list[dict]) -> list[dict]:
    rows = []
    for p in pairs:
        winner = p.get("winner")
        win_name = p.get("side_a") if winner == "a" else p.get("side_b") if winner == "b" else ""
        b_map = p.get("b_locks") or {}
        b25 = b_map.get(0.25) or {}
        row = {
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
            "b25_fill": b_fill_text(p, b25),
        }
        for dip in B_DIPS:
            cents = int(round(dip * 100))
            rec = b_map.get(dip) or {}
            row[f"d{cents}_pnl"] = signed_money(rec.get("pnl")) if rec.get("pnl") is not None else ""
            row[f"d{cents}_mix"] = rec.get("mix") or ""
            row[f"d{cents}_tgt"] = fmt_px(rec.get("target"))
        rows.append(row)
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
    bits = [
        f"<p><strong>{esc(title)}</strong> {esc(pair.get('venue') or '')}. "
        f"T0 {esc(pair.get('t0_label') or '')} at {esc(et_iso(pair.get('t0_ts')))}: "
        f"{esc(pair.get('side_a'))} {fmt_px(pair.get('t0_a'))} / "
        f"{esc(pair.get('side_b'))} {fmt_px(pair.get('t0_b'))}, C = {fmt_px(pair.get('c0'))}. "
        f"Favorite {esc(pair.get('fav_name') or '')}. Underdog {esc(pair.get('dog_name') or '')}. "
        f"Winner {esc(winner or 'unsettled')}. In-play ticks {pair.get('inplay_n') or 0}.</p>"
    ]
    cross = pair.get("b_cross") or {}
    bits.append(
        f"<p>50¢ cross: {fmt_px(cross.get('px'))} @ {esc(et_iso(cross.get('ts')))} "
        f"(next tick {fmt_px(cross.get('next_px'))}).</p>"
    )
    for dip in B_DIPS:
        rec = (pair.get("b_locks") or {}).get(dip) or {}
        cents = int(round(dip * 100))
        bits.append(
            f"<p>D={cents}¢ target {fmt_px(rec.get('target'))}: {esc(b_fill_text(pair, rec))}; "
            f"mix {esc(rec.get('mix') or '')}; cost {money_cell(rec.get('cost'))}; "
            f"P&amp;L {signed_money(rec.get('pnl')) if rec.get('pnl') is not None else 'unsettled'}.</p>"
        )
    return "\n".join(bits)


def freeze_rows() -> list[tuple[str, str]]:
    return [
        ("Arm", "Live Strategy B. D = lock profit on the extra post-cross pair (not a dip from T0 Yes)."),
        ("D definition", "After T0-underdog Yes prints strictly > 0.50, buy 1 more of that name, then original-favorite Yes at/below 1 − cross_fill − D."),
        ("Not rerun as score", "Extra-Yes-on-dip (T0 both, then extra Yes on a falling name) was DISMISS. This page is favorite-dip-after-50-cross."),
        ("Universe", "Same 182 (game, venue) keys as dense_inplay_yes_dip_20261021.html / dense_inplay_fav_lock_cross_smalld_20261021.html. Tennis moneyline. C in [0.95, 1.20]. Both Yes in (0.10, 0.90). Dense in-play bar (≥200 ticks) from the original freeze keys."),
        ("T0", "Same helpers as the 5–25 stamp: assign_actual_t0 (last two-sided Yes at/before trusted actual start; else tape-resume / first competitive). Not the live 5-minute send window — that is ops, not this freeze."),
        ("Size", "1 contract per ticket. Optimistic fill at the printed Yes ask."),
        ("Fees", "Primary P&L without venue fees (same as 5–25). Optional fee rows are not the score."),
        ("Absorb", "Stop extras at first 5¢ / 95¢ absorbing print."),
        ("IS / OOS", "Inherited: entire October 2026 tape is OOS (every T0 ≥ 2024-01-01). No IS row. Do not retune on OOS."),
        ("Live D", "0.25 unchanged. This stamp does not wire a new D, is not gold, is not DailyRun."),
        ("max_open / Novig", "Live MAX_OPEN_B_MATCHES=2 and B never sends Novig are ops. Sim scores every frozen book independently, including whatever venues were in the 182 keys."),
        ("Ann ROR", "House compare_format.ann_ror_from_closed. Slot cash = median 1-contract cost of that arm. Days held = T0→window-end hours, floored at 1 hour. Max DD / Sharpe seed $500,000 exit-date equity. Same-day tennis makes Ann ROR capital-turn explosive; judge quality on mean $, WR, PF, Max DD as well."),
    ]


def write_baseline(payload: dict) -> None:
    ctrl = payload["ctrl"]
    lines = [
        "# Strategy B D = 5¢…50¢ — freeze",
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
        "## D definition (this replay)",
        "",
        "- **Live Strategy B** (favorite at `1 − cross_fill − D` after dog Yes > 0.50).",
        "- **Not** extra-Yes-on-dip (already DISMISS).",
        "- Prior 5–25 generator: `tools/dense_inplay_fav_lock_cross_smalld_20261021.py`.",
        "- Prior HTML: `drive/paul_experiments/prediction_market_arb_exhaustive_20261017/dense_inplay_fav_lock_cross_smalld_20261021.html` (not overwritten).",
        "",
        "## Freeze (one knob: D)",
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
            "",
            "## Control D=25 (this replay)",
            "",
            f"- N settled={ctrl.get('n_settled')} WR={fmt_pct(ctrl.get('win_pct'), 1)}% "
            f"mean={fmt_signed(ctrl.get('mean'))} PF={fmt_num(ctrl.get('pf'))} "
            f"AnnROR_hours={fmt_ann(ctrl.get('ann_ror'))} AnnROR_1d={fmt_ann(ctrl.get('ann_ror_1d'))} "
            f"MaxDD%={fmt_pct(ctrl.get('max_dd'), 4)} MaxDD$={format_money(ctrl.get('max_dd_d'))} "
            f"Calmar={fmt_num(ctrl.get('calmar'))} Sharpe={fmt_num(ctrl.get('sharpe'))} "
            f"avg_days={fmt_num(ctrl.get('avg_days'), 3)} crossed={ctrl.get('pct_crossed')} "
            f"lock={ctrl.get('pct_lock')}",
            "",
            "## Arms vs D=25",
            "",
            "| D¢ | role | N | WR% | mean $ | PF | Ann ROR 1d | Max DD $ | lock% | Δ mean vs 25 |",
            "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for rec in payload["arm_rows"]:
        lines.append(
            f"| {rec['cents']} | {rec['role']} | {rec.get('n_settled')} | "
            f"{fmt_pct(rec.get('win_pct'), 1)} | {fmt_signed(rec.get('mean'))} | "
            f"{fmt_num(rec.get('pf'))} | {fmt_ann(rec.get('ann_ror_1d'))} | "
            f"{format_money(rec.get('max_dd_d'))} | {rec.get('pct_lock') or ''} | "
            f"{delta_money(rec.get('mean'), ctrl.get('mean'))} |"
        )
    lines.extend(
        [
            "",
            f"## Verdict: {payload['verdict']}",
            "",
            payload["sweet_text"],
            "",
            "Selection: KEEP/DISMISS on quality, not trade count. OOS is report-only. "
            "No IS row exists on this tape, so KEEP is not available from this ranking.",
            "",
        ]
    )
    BASELINE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {BASELINE}", flush=True)


def write_html(payload: dict) -> None:
    if PAGE.resolve() == ORIGINAL_PAGE.resolve() or PAGE.resolve() == PRIOR_HTML.resolve():
        raise RuntimeError("refusing to overwrite the prior 5–25 HTML")
    ctrl = payload["ctrl"]
    freeze_table = table(
        [("Knob", "text"), ("Freeze", "text")],
        [{"k": k, "v": v} for k, v in freeze_rows()],
        ["k", "v"],
    )
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
        ("% crossed", "num"),
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
    band_headers = [
        ("Band", "text"),
        ("D¢", "text"),
        ("Best mean arm", "text"),
        ("Best mean $", "num"),
        ("Band mean $", "num"),
        ("Best PF", "num"),
        ("Note", "text"),
    ]
    prior = [r for r in payload["arm_rows"] if r["dip"] <= 0.25 + 1e-12]
    new = [r for r in payload["arm_rows"] if r["dip"] >= 0.30 - 1e-12]
    best_prior = max(prior, key=lambda r: r.get("mean") or -99)
    best_new = max(new, key=lambda r: r.get("mean") or -99)
    band_rows = [
        {
            "band": "5…25 (prior + live control)",
            "d": "5,10,15,20,25",
            "best": best_prior["arm"],
            "best_mean": signed_money(best_prior.get("mean")),
            "band_mean": signed_money(band_mean(prior, 0.05, 0.25)),
            "best_pf": fmt_num(best_prior.get("pf")),
            "note": "Includes live D=25 control. Replay on this tape, not copied from 2026-10-21 HTML.",
        },
        {
            "band": "30…50 (new)",
            "d": "30,35,40,45,50",
            "best": best_new["arm"],
            "best_mean": signed_money(best_new.get("mean")),
            "band_mean": signed_money(band_mean(new, 0.30, 0.50)),
            "best_pf": fmt_num(best_new.get("pf")),
            "note": "Same books, same T0, only D changes.",
        },
    ]
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
        ("D=25 fills", "text"),
    ]
    match_fields = [
        "game", "date", "venue", "side_a", "t0_a", "side_b", "t0_b", "c0",
        "fav", "dog", "inplay_n", "winner", "live", "t0_when", "b25_fill",
    ]
    for dip in B_DIPS:
        cents = int(round(dip * 100))
        match_headers.append((f"D={cents} mix", "text"))
        match_headers.append((f"D={cents} target", "num"))
        match_headers.append((f"D={cents} P&L", "num"))
        match_fields.extend([f"d{cents}_mix", f"d{cents}_tgt", f"d{cents}_pnl"])
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Strategy B D=5¢ to 50¢ 2026-10-23</title>
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
<h1>Strategy B — D lock profit 5¢ to 50¢</h1>
<p class="note">Written {esc(payload['written_at'])}. Research only. Not gold. Not DailyRun. Not a trading rule. This page does not place orders. Live D=25 is unchanged. Entire October 2026 tape is out-of-sample (OOS): every T0 ≥ 2024-01-01. No in-sample (IS) row. Verdict: <strong>{esc(payload.get('verdict') or 'HOLD')}</strong>.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="hl">
<p><strong>Which D definition:</strong> live Strategy B — T0 both Yes, then dog Yes &gt; 0.50, then original favorite at <strong>1 − cross_fill − D</strong>. This is <em>not</em> extra-Yes-on-dip (already DISMISS). Prior 5–25 page: <a href="../prediction_market_arb_exhaustive_20261017/dense_inplay_fav_lock_cross_smalld_20261021.html">dense_inplay_fav_lock_cross_smalld_20261021.html</a> (not overwritten). 5–25 is replayed on this tape so 30–50 sits on the same book.</p>
<p><strong>Frozen universe:</strong> {esc(payload['n_dense'])} tennis books keyed to the original extra-Yes-on-dip HTML ({ORIGINAL_N} keys). Settled {esc(payload['n_dense_settled'])}; still live {esc(payload['n_dense_live'])}. {esc(payload.get('freeze_note') or '')}</p>
<p><strong>Control D=25:</strong> N={esc(ctrl.get('n_settled'))} WR={esc(fmt_pct(ctrl.get('win_pct'), 1))}% mean {esc(fmt_signed(ctrl.get('mean')))} PF={esc(fmt_num(ctrl.get('pf')))} Ann ROR if 1 calendar day={esc(fmt_ann(ctrl.get('ann_ror_1d')))} 1-contract Max DD {esc(format_money(ctrl.get('max_dd_d')))} lock filled {esc(ctrl.get('pct_lock') or '')}.</p>
<p><strong>Verdict:</strong> {esc(payload.get('sweet_text') or '')}</p>
<p>Annualized rate of return (Ann ROR) uses <code>compare_format.ann_ror_from_closed</code>. Slot cash = median 1-contract cost of that arm. The hours-held column uses T0→window-end (floor 1 hour) and is capital-turn explosive on same-day tennis — it is the house formula, not a send rule. A second column uses 1 calendar day so arms can be compared. IS Ann ROR is n/a — no IS. Full book = OOS. Max DD % / Sharpe replay exit-date equity from {format_money(DEFAULT_INITIAL_ACCOUNT)} (near 0% at 1-contract size). 1-contract dollar Max DD is cumulative PnL peak-to-trough on the settled book. Total book PnL $ is omitted from the compare table (canonical HTML compare rule).</p>
</div>

<div class="warn">
<p>Primary P&amp;L is without fees. Fills are optimistic at the printed Yes ask. Do not buy after the first 5¢ / 95¢ absorbing print. Ranking D after seeing this table is selection bias. Verdict <strong>{esc(payload.get('verdict') or 'HOLD')}</strong>. Live D=25 unchanged. Research only. Not gold. Not DailyRun.</p>
</div>

<h2>Freeze</h2>
<p class="note">Click column headers to sort. One knob: D. Everything else copied from the 5–25 stamp.</p>
{report_page_extras.SWIPE_NOTE_HTML}
{freeze_table}

<h2>1. 5…25 vs 30…50 on the same book</h2>
<p class="note">Click column headers to sort.</p>
{table(band_headers, band_rows, ["band", "d", "best", "best_mean", "band_mean", "best_pf", "note"])}

<h2>2. Canonical compare — every D vs control 25</h2>
<p class="note">Mean / median / win rate / Ann ROR are settled books. % crossed / % lock filled are all frozen books. Deltas are that arm minus D=25. Click column headers to sort.</p>
{table(compare_headers, payload["compare_rows"], compare_fields)}

<h2>3. Worked examples (same named matches as the 5–25 page)</h2>
{payload["hassan_html"]}
{payload["smith_html"]}

<h2>4. Per-match Strategy B (frozen keys)</h2>
<p class="note">One row per frozen book. P&amp;L is Strategy B at that D. Click column headers to sort.</p>
{table(match_headers, payload["match_rows"], match_fields)}

<h2>Process notes</h2>
<ul>
<li>KEEP / HOLD / DISMISS is quality versus control D=25, not trade count.</li>
<li>OOS is report-only. If a larger D looks better here, that is still not KEEP: no IS row, selection after seeing the table.</li>
<li>Live <code>tools/live_strategy_b.py</code> stays at D=0.25. This stamp does not start a second live process.</li>
<li>Acronyms: T0 is the open used here. C is the two T0 Yes prices added together. Vig is the overround when two Yes prices sum over $1. D is lock profit on the extra post-cross pair. Ann ROR is annualized rate of return. IS is in-sample; OOS is out-of-sample. IOC is immediate-or-cancel. PF is profit factor. Max DD is maximum drawdown.</li>
</ul>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    STAMP.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    print(f"wrote {PAGE}", flush=True)


def copy_g(path: Path) -> None:
    dest_dir = Path(r"G:\My Drive\paul_experiments\strategy_b_D_05_to_50_20261023")
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
    print(
        f"frozen {len(frozen)}; missing {len(missing)}",
        flush=True,
    )
    for pair in frozen:
        simulate_b_dips(pair)
    settled = [p for p in frozen if p.get("settled")]
    live = [p for p in frozen if not p.get("settled")]
    summaries = [summarize_b(frozen, dip, "b_locks") for dip in B_DIPS]
    arm_rows = [quality_block(frozen, rec["dip"], rec) for rec in summaries]
    ctrl = next(r for r in arm_rows if abs(r["dip"] - CONTROL_D) < 1e-12)
    for rec in arm_rows:
        _out(
            f"B D={rec['cents']}c n={rec['n']} settled={rec['n_settled']} "
            f"mean={fmt_signed(rec['mean'])} WR={fmt_pct(rec.get('win_pct'), 1)} "
            f"PF={fmt_num(rec.get('pf'))} crossed={rec.get('pct_crossed')} "
            f"lock={rec.get('pct_lock')} AnnROR={fmt_num(rec.get('ann_ror'))} "
            f"MaxDD={fmt_pct(rec.get('max_dd'))}"
        )
    verdict, sweet_text = decide_verdict(arm_rows)
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
        "ctrl": ctrl,
        "verdict": verdict,
        "sweet_text": sweet_text,
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
    payload["compare_rows"] = [compare_row(rec, ctrl) for rec in arm_rows]
    STAMP.mkdir(parents=True, exist_ok=True)
    ARMS_JSON.write_text(
        json.dumps(
            {
                "written_at": payload["written_at"],
                "verdict": verdict,
                "sweet_text": sweet_text,
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
