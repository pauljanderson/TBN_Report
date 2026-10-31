"""T0-favorite <90¢ one-Yes baseline + stay-above inequality audit.

Research only. Not Strategy B (not both Yes). Does not place, cancel, or
amend orders. Does not print secrets. Does not start live_strategy_b.py.
Does not change live C_HI/D/stacking. Does not sell. Does not wire GTC.
Does not touch strategy_b_tighten_fav70_c104_c109_20261024.
Not gold. Not DailyRun.
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
from write_t0_band_from_stay_above import documented_leg_fee, rows_from_living_books

ET = ZoneInfo("America/New_York")
PARENT = (
    ROOT / "drive" / "paul_experiments"
    / "prediction_market_arb_exhaustive_20261017"
)
STAMP = PARENT / "t0_fav_lt90_baseline_20261024"
PAGE = STAMP / "compare.html"
BASELINE = STAMP / "BASELINE.md"
AUDIT_JSON = STAMP / "audit.json"
ARMS_JSON = STAMP / "arms.json"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/t0_fav_lt90_baseline_20261024/compare.html"
)
IS_CUT = "2024-01-01"
MIN_DAYS_FOR_ANN = 0.05
VENUE_RANK = {"Kalshi": 0, "Gemini": 1, "Polymarket": 2, "Novig": 3}
DOC_FEE_VENUES = {"Kalshi", "Gemini", "Polymarket"}
CAL_BUCKETS = (
    (">90", 0.90, 1.01),
    ("80-89", 0.80, 0.90),
    ("70-79", 0.70, 0.80),
    ("60-69", 0.60, 0.70),
    ("50-59", 0.50, 0.60),
)
ARM_SPECS = (
    ("always_t0_fav", "Any unique T0 favorite (Yes ask > the other side; skip 50-50)"),
    ("t0_fav_lt_90", "T0 favorite Yes < 0.90 (Paul's ask)"),
    ("t0_fav_lt_70", "Diagnostic: T0 favorite Yes < 0.70"),
    ("t0_fav_70_to_89", "Diagnostic: 0.70 ≤ T0 favorite Yes < 0.90"),
)
PRIMARY_ARMS = ("always_t0_fav", "t0_fav_lt_90")

ASKED = (
    "Does our data show that 95.3% of the time the winner at T0 is the winner at "
    "the end? He is reading stay-above-50 vs T0-favorite win rate. Be precise. "
    "If T0 favorites win that often, if we wagered on the T0 winner when it was "
    "<90¢, would we make money? Run a baseline test. Same baseline for soccer "
    "where he saw T0 winner wins 91.3%. He thinks the numbers look wrong: college "
    "football stay-above-50 is 95.3% but T0 favorite win rate is only 89.8%. "
    "Wouldn't win rate be at least as high as stay-above-50? Check for all sports."
)
PLAIN = (
    "Stay-above-50 means the side the market liked at the first trusted start "
    "price (T0) never printed 50 cents or lower while we were watching. Winning "
    "means that side actually won the market. Those are not the same. If we "
    "missed the end of the game, we can falsely say they never went below 50 "
    "and then they lost — a losing Yes must go to $0, so it must print 50 cents "
    "or lower unless our ticks stopped early. 95.3% was college-football "
    "stay-above on the companion band page (mostly spreads), not “the T0 "
    "favorite won the game.” 91.3% on soccer was also stay-above, not the win "
    "rate. This page audits that inequality on the same rows, then runs a "
    "simple baseline that is not Strategy B: at trusted T0, buy 1 Yes on the "
    "T0 favorite only, taker at the Yes ask, with documented fees, hold to "
    "settlement. Buying an 80-cent favorite to win $1 needs them to win more "
    "often than about 80% after fees. 91% soccer favorites can still lose money "
    "if you mostly buy 93-cent tickets. Research only. Not gold. Not DailyRun. "
    "Paul proposed <90 after seeing the dashboard (selection bias). Live "
    "Strategy B is unchanged."
)


def esc(value) -> str:
    return html_mod.escape("" if value is None else str(value))


def iso_now() -> str:
    return datetime.now(ET).isoformat()


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def html_table(headers: list[tuple[str, str]], rows: list[list[str]], *, total: bool = False) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for i, row in enumerate(rows):
        klass = ' class="total-row"' if total and i == len(rows) - 1 else ""
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr{klass}>{cells}</tr>")
    if not body:
        body.append("<tr>" + "".join("<td></td>" for _ in headers) + "</tr>")
    return (
        f"{report_page_extras.SWIPE_NOTE_HTML}<div class=\"table-wrap\">"
        f"<table class=\"sortable\"><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def fav_yes_pnl(ask, fee, *, won: bool) -> Decimal:
    """SIZE=1 taker Yes held to settlement. PnL = 1 - ask - fee on a win, else -ask - fee."""
    a = Decimal(str(ask))
    f = Decimal("0") if fee is None else Decimal(str(fee))
    cost = a + f
    if won:
        return Decimal("1") - cost
    return -cost


def arm_ok(arm_id: str, t0_fav: float) -> bool:
    if arm_id == "always_t0_fav":
        return t0_fav > 0.50 + 1e-12
    if arm_id == "t0_fav_lt_90":
        return 0.50 + 1e-12 < t0_fav < 0.90 - 1e-12
    if arm_id == "t0_fav_lt_70":
        return 0.50 + 1e-12 < t0_fav < 0.70 - 1e-12
    if arm_id == "t0_fav_70_to_89":
        return 0.70 - 1e-12 <= t0_fav < 0.90 - 1e-12
    return False


def cal_bucket(px: float) -> str:
    if px > 0.90:
        return ">90"
    if px >= 0.80:
        return "80-89"
    if px >= 0.70:
        return "70-79"
    if px >= 0.60:
        return "60-69"
    if px > 0.50:
        return "50-59"
    return "under-50"


def mean(xs: list[float]) -> float | None:
    if not xs:
        return None
    return float(sum(xs) / len(xs))


def eligible_books(books: list[dict]) -> list[dict]:
    out = []
    for book in books or []:
        if book.get("skip"):
            continue
        if not book.get("settled") or book.get("void"):
            continue
        if not book.get("two_sided"):
            continue
        if not book.get("fav"):
            continue
        t0_fav = book.get("t0_fav")
        if t0_fav is None:
            continue
        if abs(float(t0_fav) - 0.50) <= 1e-12:
            continue
        if book.get("t0_a") is None or book.get("t0_b") is None:
            continue
        out.append(book)
    return out


def match_key(book: dict) -> tuple:
    return (
        str(book.get("sport") or "").lower(),
        str(book.get("game_n") or ""),
        str(book.get("kind") or book.get("market_type") or "moneyline"),
        str(book.get("number") or ""),
    )


def pick_primary(books: list[dict]) -> list[dict]:
    bags: dict[tuple, list[dict]] = defaultdict(list)
    for book in books:
        bags[match_key(book)].append(book)
    out = []
    for _key, group in bags.items():
        group = sorted(
            group,
            key=lambda b: (VENUE_RANK.get(str(b.get("venue") or ""), 9), str(b.get("venue") or "")),
        )
        chosen = dict(group[0])
        chosen["_grain"] = "match"
        chosen["_n_venues"] = len(group)
        out.append(chosen)
    return out


def book_trade(book: dict, arm_id: str) -> dict | None:
    t0_fav = float(book.get("t0_fav"))
    if not arm_ok(arm_id, t0_fav):
        return None
    venue = str(book.get("venue") or "")
    fee = documented_leg_fee(venue, t0_fav)
    fee_known = fee is not None
    if not fee_known:
        fee = Decimal("0")
    won = bool(book.get("fav_won"))
    pnl = fav_yes_pnl(t0_fav, fee, won=won)
    cost = Decimal(str(t0_fav)) + Decimal(str(fee))
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
    be = float(cost)
    return {
        "arm": arm_id,
        "sport": book.get("sport") or "unknown",
        "kind": book.get("kind") or book.get("market_type") or "moneyline",
        "venue": venue,
        "game": book.get("game") or "",
        "game_n": book.get("game_n") or "",
        "number": book.get("number") or "",
        "t0_fav": t0_fav,
        "bucket": cal_bucket(t0_fav),
        "fee": float(fee),
        "fee_known": fee_known,
        "cost": float(cost),
        "won": won,
        "pnl_d": float(pnl),
        "pnl": pnl_pct,
        "days": days,
        "opened": opened,
        "closed": closed,
        "entry_date": opened.date().isoformat() if opened else "",
        "be": be,
        "grain": book.get("_grain") or "venue-game",
        "two_sided": True,
    }


def trades_for(books: list[dict], arm_id: str, *, documented_fee_only: bool = True) -> list[dict]:
    out = []
    for book in books:
        trade = book_trade(book, arm_id)
        if trade is None:
            continue
        if documented_fee_only and not trade["fee_known"]:
            continue
        out.append(trade)
    return out


def dollar_drawdown(trades: list[dict]) -> float | None:
    if not trades:
        return None
    ordered = sorted(trades, key=lambda t: (t.get("closed") or datetime.min.replace(tzinfo=ET), t.get("game") or ""))
    eq = 0.0
    peak = 0.0
    dd = 0.0
    for t in ordered:
        eq += float(t["pnl_d"])
        if eq > peak:
            peak = eq
        if peak - eq > dd:
            dd = peak - eq
    return dd


def quality(trades: list[dict], *, arm_id: str, label: str, grain: str) -> dict:
    pnls = [float(t["pnl_d"]) for t in trades]
    pcts = [float(t["pnl"]) for t in trades if t.get("pnl") is not None]
    costs = [float(t["cost"]) for t in trades]
    days = [float(t["days"]) for t in trades]
    wins = [p for p in pnls if p > 1e-12]
    losses = [p for p in pnls if p < -1e-12]
    n = len(trades)
    n_win = sum(1 for t in trades if t.get("won"))
    n_loss = n - n_win
    sum_win = sum(wins) if wins else 0.0
    sum_loss = abs(sum(losses)) if losses else 0.0
    pf = (sum_win / sum_loss) if sum_loss > 1e-12 else (sum_win if sum_win > 0 else None)
    wo = None
    if len(pcts) >= 2:
        dropped = pcts[:]
        dropped.remove(max(dropped))
        wo = mean(dropped)
    elif pcts:
        wo = mean(pcts)
    avg_days = mean(days) if days else None
    cash = float(statistics.median(costs)) if costs else 1.0
    omit_ann = (avg_days is None) or (avg_days < 1.0)
    ann_note = ""
    overlay: dict = {}
    if trades and not omit_ann:
        try:
            overlay = overlay_ann_ror_max_dd(
                trades, cash=cash, initial_account=DEFAULT_INITIAL_ACCOUNT,
            )
        except OverflowError:
            omit_ann = True
            overlay = {}
    ann = overlay.get("ann_ror") if overlay else None
    if ann is not None and not math.isfinite(float(ann)):
        ann = None
    if omit_ann:
        ann = None
        ann_note = (
            f"Ann ROR omitted — average days held is {avg_days if avg_days is not None else 0:.4f} "
            "(same-day contracts; house formula would overflow on a near-zero hold)."
        )
    is_trades = [t for t in trades if (t.get("entry_date") or "9999") < IS_CUT]
    oos_trades = [t for t in trades if (t.get("entry_date") or "") >= IS_CUT]
    ann_is = None
    ann_oos = None if omit_ann else ann
    is_note = "n/a — no IS (all T0 ≥ 2024-01-01; this tape is 2026)"
    if is_trades and not omit_ann:
        try:
            is_over = overlay_ann_ror_max_dd(
                is_trades, cash=cash, initial_account=DEFAULT_INITIAL_ACCOUNT,
            )
        except OverflowError:
            is_over = {}
        ann_is = is_over.get("ann_ror")
        if ann_is is not None and not math.isfinite(float(ann_is)):
            ann_is = None
        is_note = ""
    max_dd = overlay.get("max_dd")
    if max_dd is not None and not math.isfinite(float(max_dd)):
        max_dd = None
    calmar = overlay.get("calmar")
    if calmar is not None and (not math.isfinite(float(calmar)) or omit_ann or not max_dd):
        calmar = None
    sharpe = overlay.get("sharpe")
    if sharpe is not None and not math.isfinite(float(sharpe)):
        sharpe = None
    wr = (100.0 * n_win / n) if n else None
    avg_cost = mean(costs)
    expectancy = mean(pnls)
    return {
        "arm_id": arm_id,
        "arm": label,
        "grain": grain,
        "n": n,
        "n_win": n_win,
        "n_loss": n_loss,
        "win_pct": wr,
        "pnl_sum": sum(pnls) if pnls else 0.0,
        "mean": expectancy,
        "median": float(statistics.median(pnls)) if pnls else None,
        "avg_pnl_pct": mean(pcts),
        "avg_pnl_pct_wo_max": wo,
        "avg_win": mean(wins),
        "avg_loss": mean(losses),
        "pf": pf,
        "expectancy": expectancy,
        "mean_cost": avg_cost,
        "median_cost": cash,
        "avg_days": avg_days,
        "capital_days": overlay.get("capital_days") if overlay else 0.0,
        "ann_ror": ann,
        "ann_ror_is": ann_is,
        "ann_ror_oos": ann_oos,
        "n_is": len(is_trades),
        "n_oos": len(oos_trades),
        "max_dd": max_dd,
        "max_dd_d": dollar_drawdown(trades),
        "calmar": calmar,
        "sharpe": sharpe,
        "sharpe_source": (overlay.get("sharpe_source") or "") if overlay else "",
        "overlay_note": (overlay.get("note") or "") if overlay else "",
        "ann_note": ann_note,
        "is_note": is_note,
        "brt_cash": cash,
        "trades": trades,
    }


def fmt_pct(value, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{float(value):.{digits}f}"


def fmt_num(value, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{float(value):.{digits}f}"


def fmt_ann(value) -> str:
    if value is None:
        return "—"
    try:
        if not math.isfinite(float(value)):
            return "—"
    except (TypeError, ValueError):
        return "—"
    return f"{float(value):.1f}"


def delta(a, b) -> float | None:
    if a is None or b is None:
        return None
    return float(a) - float(b)


def slice_trades(trades: list[dict], sport: str | None = None, kind: str | None = None) -> list[dict]:
    out = trades
    if sport and sport != "all sports":
        out = [t for t in out if str(t.get("sport") or "").lower() == sport.lower()]
    if kind and kind != "all":
        out = [t for t in out if str(t.get("kind") or "") == kind]
    return out


def calibration_rows(trades: list[dict]) -> list[list[str]]:
    bags: dict[str, list[dict]] = {label: [] for label, _lo, _hi in CAL_BUCKETS}
    bags["under-50"] = []
    for t in trades:
        bags.setdefault(t.get("bucket") or "under-50", []).append(t)
    rows = []
    order = [label for label, _lo, _hi in CAL_BUCKETS] + ["under-50"]
    all_t = []
    for label in order:
        group = bags.get(label) or []
        all_t.extend(group)
        n = len(group)
        n_win = sum(1 for t in group if t.get("won"))
        wr = (100.0 * n_win / n) if n else None
        costs = [float(t["cost"]) for t in group]
        be = mean(costs)
        edge = (wr - 100.0 * be) if wr is not None and be is not None else None
        pnls = [float(t["pnl_d"]) for t in group]
        rows.append([
            esc(label),
            str(n),
            str(n_win),
            fmt_pct(wr),
            fmt_num(be, 3) if be is not None else "—",
            fmt_pct(100.0 * be if be is not None else None),
            fmt_pct(edge),
            format_money(sum(pnls) if pnls else 0.0) if n else "—",
            format_money(mean(pnls)) if pnls else "—",
            "tiny sample" if 0 < n < 20 else ("small sample" if n < 50 else ("no settled rows" if n == 0 else "")),
        ])
    n = len(all_t)
    n_win = sum(1 for t in all_t if t.get("won"))
    wr = (100.0 * n_win / n) if n else None
    costs = [float(t["cost"]) for t in all_t]
    be = mean(costs)
    edge = (wr - 100.0 * be) if wr is not None and be is not None else None
    pnls = [float(t["pnl_d"]) for t in all_t]
    rows.append([
        "All",
        str(n),
        str(n_win),
        fmt_pct(wr),
        fmt_num(be, 3) if be is not None else "—",
        fmt_pct(100.0 * be if be is not None else None),
        fmt_pct(edge),
        format_money(sum(pnls) if pnls else 0.0) if n else "—",
        format_money(mean(pnls)) if pnls else "—",
        "",
    ])
    return rows


def quality_row(q: dict, control: dict | None) -> list[str]:
    def dlt(key, fmt="num"):
        if control is None:
            return "—"
        got = delta(q.get(key), control.get(key))
        if got is None:
            return "—"
        if fmt == "money":
            return format_money_delta(got)
        if fmt == "pct":
            return f"{got:+.1f}"
        return f"{got:+.2f}"

    ann_full = q["ann_note"] if q.get("ann_note") else fmt_ann(q.get("ann_ror"))
    ann_is = q.get("is_note") or fmt_ann(q.get("ann_ror_is"))
    ann_oos = q["ann_note"] if q.get("ann_note") else fmt_ann(q.get("ann_ror_oos"))
    return [
        esc(q.get("arm") or q.get("arm_id")),
        esc(q.get("grain") or ""),
        str(q.get("n") or 0),
        str(q.get("n_win") or 0),
        fmt_pct(q.get("win_pct")),
        format_money(q.get("pnl_sum")),
        format_money(q.get("mean")),
        fmt_num(q.get("avg_pnl_pct")),
        fmt_num(q.get("avg_pnl_pct_wo_max")),
        format_money(q.get("avg_win")),
        format_money(q.get("avg_loss")),
        fmt_num(q.get("pf")),
        format_money(q.get("expectancy")),
        fmt_num(q.get("avg_days"), 3),
        fmt_num(q.get("capital_days"), 2),
        format_money(q.get("max_dd_d")),
        fmt_pct(q.get("max_dd")),
        fmt_num(q.get("calmar")),
        fmt_num(q.get("sharpe")),
        esc(ann_full),
        esc(ann_is),
        esc(ann_oos),
        str(q.get("n_is") or 0),
        str(q.get("n_oos") or 0),
        dlt("win_pct", "pct"),
        dlt("mean", "money"),
        dlt("avg_pnl_pct"),
        dlt("pf"),
    ]


COMPARE_HEADERS = [
    ("Arm", "text"),
    ("Grain", "text"),
    ("N", "num"),
    ("Wins", "num"),
    ("Win %", "num"),
    ("With-fee PnL $", "num"),
    ("Mean $", "num"),
    ("Avg PnL %", "num"),
    ("AVG_PNL_PCT_WO_MAX", "num"),
    ("Avg win $", "num"),
    ("Avg loss $", "num"),
    ("Profit factor", "num"),
    ("Expectancy $", "num"),
    ("Avg days held", "num"),
    ("Capital days", "num"),
    ("Max DD $", "num"),
    ("Max DD %", "num"),
    ("Calmar", "num"),
    ("Sharpe", "num"),
    ("Ann ROR full", "text"),
    ("Ann ROR IS", "text"),
    ("Ann ROR OOS", "text"),
    ("N IS", "num"),
    ("N OOS", "num"),
    ("Δ Win % vs always", "num"),
    ("Δ Mean $ vs always", "num"),
    ("Δ Avg PnL % vs always", "num"),
    ("Δ PF vs always", "num"),
]


def judge(always: dict, lt90: dict) -> tuple[str, str]:
    """KEEP only if quality improves. New baseline, not a wire."""
    if (lt90.get("n") or 0) <= 0:
        return "HOLD", "t0_fav_lt_90 has N=0 on this slice."
    mean_a = always.get("mean")
    mean_b = lt90.get("mean")
    wr_a = always.get("win_pct")
    wr_b = lt90.get("win_pct")
    pf_a = always.get("pf")
    pf_b = lt90.get("pf")
    wo_a = always.get("avg_pnl_pct_wo_max")
    wo_b = lt90.get("avg_pnl_pct_wo_max")
    better = 0
    worse = 0
    for a, b in ((mean_a, mean_b), (wr_a, wr_b), (pf_a, pf_b), (wo_a, wo_b)):
        if a is None or b is None:
            continue
        if b > a + 1e-12:
            better += 1
        elif b < a - 1e-12:
            worse += 1
    if better > worse and (mean_b or 0) > (mean_a or 0):
        return (
            "LEAN KEEP (research only)",
            "t0_fav_lt_90 improves with-fee mean $ vs always_t0_fav on this slice. "
            "Paul proposed <90 after seeing the dashboard (selection bias). Not gold. Not DailyRun. Not a wire.",
        )
    if worse > better or (mean_b or 0) < (mean_a or 0):
        return (
            "HOLD / DISMISS as a wire",
            "t0_fav_lt_90 does not improve with-fee quality vs always_t0_fav. "
            "Buying cheap-looking favorites can still lose money after fees. Research only.",
        )
    return (
        "HOLD",
        "Quality is flat vs always_t0_fav. Do not KEEP. Do not wire. Selection bias: <90 was proposed after the dashboard.",
    )


def write_baseline_md(payload: dict, recs: dict) -> None:
    full = payload.get("full") or {}
    q3 = int(full.get("q3_n_all") or 0)
    stay = int(full.get("n_same_stay") or 0)
    wins = sum(int(b.get("q3_win") or 0) for b in (full.get("by_sport") or {}).values())
    text = f"""# T0 favorite <90¢ baseline — freeze

Written {iso_now()} ET. Research only. Not gold. Not DailyRun. Not a wire.

## What you asked

{ASKED}

## In plain English

{PLAIN}

## Freeze

- **T0:** first trusted serve (Kalshi/Gemini occurrence, else listed/feed with seconds=00). Same as living `t0_all_games_stats.py`. Not tape-resume. Not first-competitive.
- **Favorite:** higher T0 Yes ask on that venue book. Skip 50-50.
- **Stay-above-50:** post-T0 path exists, favorite never printed ≤50¢, and we did not lose while the last tick was still >50¢. Empty tape = `no_post_t0_path`. Last tick 80¢ + official loss = `path_incomplete` / missing crash, not stay-above.
- **Win:** official venue settlement. Voids excluded.
- **Baseline (not Strategy B):** SIZE=1, buy 1 Yes on the T0 favorite only, taker at the Yes ask, documented fees, hold to settlement.
- **Fees:** Kalshi 0.07×p×(1−p) to $0.0001; Gemini same formula rounded up to a cent; Polymarket 0.0695×p×(1−p) banker's cent. Novig has no documented coefficient → omitted from primary P&L (not treated as zero-fee).
- **Arms:** `always_t0_fav` (control), `t0_fav_lt_90` (Paul's ask), diagnostic `t0_fav_lt_70` and `t0_fav_70_to_89`. Do not pick from the diagnostics.
- **Grain:** headline is **one match** (primary venue Kalshi > Gemini > Polymarket > Novig). Venue-game grain is labeled and is not an independent bankroll.
- **Universe:** settled two-sided trusted-T0 unique-favorite books on the living dashboard tape (moneyline, spread, total).
- **IS / OOS:** IS = entry_date < 2024-01-01; OOS = entry_date ≥ 2024-01-01. This tape is all 2026 — IS N=0. Still print three Ann ROR columns. Same-day: if avg days held < {MIN_DAYS_FOR_ANN}, omit Ann ROR with reason. House formula `compare_format.ann_ror_from_closed` only. Do not invent a second one.
- **Selection bias:** Paul proposed <90 after seeing the dashboard. Judge quality over N. KEEP only if quality improves. New baseline, not a wire.
- **Live knobs unchanged:** C_HI=1.20, D=0.25, no second `live_strategy_b.py`, no GTC, no sells.

## Headline numbers (after the stay-above fix)

- Same-N all-sports stay-above: {stay}/{q3} ({t0.pct(stay, q3)}%).
- Same-N all-sports T0-favorite win rate: {wins}/{q3} ({t0.pct(wins, q3)}%).
- Stay-above-but-lost (should be ~0 after the fix): {full.get("n_stay_lost")}.
- Missing crash (last tick >50¢, official loss): {full.get("n_missing_crash")}.
- Incomplete paths: {full.get("n_incomplete")}. No post-T0 path: {(full.get("skips") or {}).get("no_post_t0_path")}.

Pre-fix band page (same N, vacuous stay on thin tape): college football stay-above 95.3% (121/127) vs win 89.8% (114/127); soccer stay-above 91.3% (21/23) vs win 87.0% (20/23). That inequality is a definition bug, not evidence that stay-above beats winning.

## Verdict

See compare.html. Live B unchanged.
"""
    BASELINE.write_text(text, encoding="utf-8")


def write_html(payload: dict, recs: dict, ineq_rows: list[list[str]], cal_tables: dict) -> Path:
    full = payload.get("full") or {}
    q3 = int(full.get("q3_n_all") or 0)
    stay = int(full.get("n_same_stay") or 0)
    wins = sum(int(b.get("q3_win") or 0) for b in (full.get("by_sport") or {}).values())
    always = recs["match"].get("always_t0_fav") or {}
    lt90 = recs["match"].get("t0_fav_lt_90") or {}
    verdict, why = judge(always, lt90)
    soccer_always = recs["match_soccer"].get("always_t0_fav") or {}
    soccer_lt90 = recs["match_soccer"].get("t0_fav_lt_90") or {}
    cfb_always = recs["match_cfb"].get("always_t0_fav") or {}
    cfb_lt90 = recs["match_cfb"].get("t0_fav_lt_90") or {}
    compare_rows = []
    control = recs["match"].get("always_t0_fav")
    for arm_id, _label in ARM_SPECS:
        q = recs["match"].get(arm_id)
        if q:
            compare_rows.append(quality_row(q, None if arm_id == "always_t0_fav" else control))
    vg_rows = []
    vg_control = recs["venue"].get("always_t0_fav")
    for arm_id, _label in ARM_SPECS:
        q = recs["venue"].get(arm_id)
        if q:
            vg_rows.append(quality_row(q, None if arm_id == "always_t0_fav" else vg_control))

    def slice_table(key: str) -> str:
        rows = []
        control_s = recs[key].get("always_t0_fav")
        for arm_id, _label in ARM_SPECS[:2]:
            q = recs[key].get(arm_id)
            if q:
                rows.append(quality_row(q, None if arm_id == "always_t0_fav" else control_s))
        return html_table(COMPARE_HEADERS, rows)

    sport_blocks = []
    for key, title in (
        ("match_soccer", "Soccer"),
        ("match_cfb", "College football"),
        ("match_tennis", "Tennis"),
        ("match_pro_football", "Pro football"),
        ("match_pro_hockey", "Pro hockey"),
        ("match_pro_baseball", "Pro baseball"),
    ):
        if key not in recs:
            continue
        sport_blocks.append(f"<h3>{esc(title)}</h3>{slice_table(key)}")

    kind_blocks = []
    for key, title in (
        ("match_moneyline", "Moneyline"),
        ("match_spread", "Spread"),
        ("match_total", "Total"),
    ):
        if key not in recs:
            continue
        kind_blocks.append(f"<h3>{esc(title)}</h3>{slice_table(key)}")

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>T0 fav &lt;90¢ baseline + stay-above audit</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.banner {{ background: #fef3c7; border: 1px solid #d97706; padding: 10px 12px; margin: 0 0 14px; }}
.hold {{ background: #fff7ed; border: 1px solid #fdba74; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
h1 {{ margin: 0 0 0.4rem; }}
h2 {{ margin: 1.4rem 0 0.5rem; }}
code {{ font-size: 0.92em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>T0 favorite &lt;90¢ baseline + stay-above audit</h1>
<p class="banner"><strong>Research only.</strong> Not gold. Not DailyRun. Not Strategy B.
Did not change live C_HI=1.20 or D=0.25. Did not sell. Did not wire GTC.
Did not start a second <code>live_strategy_b.py</code>. Bookmark <code>{esc(FILE_URL)}</code>.</p>
<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>
<div class="hold">
<h2>Direct answers</h2>
<p><strong>1. Is 95.3% “the T0 favorite wins the game”?</strong> No. 95.3%
(121/127) on the 2026-10-24 band page was college-football <em>stay-above-50</em>
(mostly spreads), not the win rate. The same table’s T0-favorite win rate was
89.8% (114/127). Soccer 91.3% (21/23) was also stay-above; the win rate there
was 87.0% (20/23). After the completeness fix, all-sports T0-favorite win rate
on the living dashboard (same N as stay-above) is
<strong>{esc(t0.pct(wins, q3))}%</strong> ({esc(wins)}/{esc(q3)}). Stay-above on
that same N is {esc(t0.pct(stay, q3))}% ({esc(stay)}/{esc(q3)}).</p>
<p><strong>2. Would betting the T0 favorite when &lt;90¢ make money?</strong>
Match grain, documented fees, SIZE=1, hold to settlement:
always_t0_fav N={esc(always.get("n"))} with-fee PnL {esc(format_money(always.get("pnl_sum")))}
(mean {esc(format_money(always.get("mean")))}, win {esc(fmt_pct(always.get("win_pct")))}%).
t0_fav_lt_90 N={esc(lt90.get("n"))} with-fee PnL {esc(format_money(lt90.get("pnl_sum")))}
(mean {esc(format_money(lt90.get("mean")))}, win {esc(fmt_pct(lt90.get("win_pct")))}%).
Soccer always N={esc(soccer_always.get("n"))} {esc(format_money(soccer_always.get("pnl_sum")))};
soccer &lt;90¢ N={esc(soccer_lt90.get("n"))} {esc(format_money(soccer_lt90.get("pnl_sum")))}.
College football always N={esc(cfb_always.get("n"))} {esc(format_money(cfb_always.get("pnl_sum")))};
CFB &lt;90¢ N={esc(cfb_lt90.get("n"))} {esc(format_money(cfb_lt90.get("pnl_sum")))}.
<strong>Verdict: {esc(verdict)}.</strong> {esc(why)}</p>
<p><strong>3. Why was stay-above 95.3 vs win 89.8?</strong> Same N, so it was not
“different denominators” on that band table. It was a definition bug: thin/incomplete
paths (no crash ticks; last print still &gt;50¢ while settlement said they lost)
counted as stay-above. On a complete path a loser must print ≤50¢. After the fix,
stay-above-but-lost = {esc(full.get("n_stay_lost"))} and missing-crash =
{esc(full.get("n_missing_crash"))}. Win rate ≥ stay-above on the same rows.
Living dashboard: <a href="../t0_all_games_stats.html">t0_all_games_stats.html</a>.
Band companion: <a href="../t0_band_from_stay_above_20261024.html">t0_band_from_stay_above_20261024.html</a>.</p>
</div>
<p class="note">Click column headers to sort. Grain for the headline P&amp;L is
<strong>one match</strong> (primary venue). Venue-game rows are labeled separately
and must not be summed as an independent bankroll. Primary P&amp;L is with documented
taker fees. Annualized rate of return uses <code>compare_format.ann_ror_from_closed</code>
on the full book, in-sample (entry before 2024-01-01), and out-of-sample
(entry on or after 2024-01-01). This tape is all 2026 so IS N=0. Same-day contracts:
if average days held is ~0, Ann ROR is omitted rather than invented. Total/Sheet
capacity PnL is not a stock-slot here; With-fee PnL $ is SIZE=1 contract dollars.</p>

<h2>Audit — stay-above vs win rate, same N</h2>
<p class="note">Stay-above-50 = the T0 favorite’s price never printed 50¢ or lower
while we were watching a complete path. Winning = they actually won. If we missed
the end of the game, we can falsely say they never went below 50 and then they lost.
After the fix, stay-above should be ≤ win rate on the same rows. Grain is venue-game
on this table (living dashboard). Voids out. One-sided books can be a favorite when
that Yes is above 50¢; the baseline P&amp;L below uses two-sided only.</p>
{html_table(
    [
        ("Sport", "text"),
        ("Market", "text"),
        ("N win-rate", "num"),
        ("N stay path", "num"),
        ("Stay-above % (same N)", "num"),
        ("Stay n / N", "text"),
        ("T0 favorite win %", "num"),
        ("Win n / N", "text"),
        ("Stay-above-but-lost", "num"),
        ("Missing crash", "num"),
        ("No post-T0 path", "num"),
        ("Path incomplete", "num"),
        ("Stay > win (bug)?", "text"),
        ("Sample", "text"),
    ],
    ineq_rows,
)}

<h2>Baseline compare — match grain (primary venue)</h2>
<p class="note">Control = always_t0_fav. Candidate = t0_fav_lt_90. Diagnostics are
not for picking. Documented-fee venues only (Kalshi / Gemini / Polymarket). SIZE=1.</p>
{html_table(COMPARE_HEADERS, compare_rows)}

<h2>Calibration — implied break-even vs realized win rate</h2>
<p class="note">This is the heart of “would we make money.” Buying at cost C (ask + fee)
to win $1 needs a win rate above 100×C percent. An 80¢ ticket with a 1¢ fee breaks
even at about 81%. A 93¢ favorite that wins 91% of the time still loses money.</p>
<h3>always_t0_fav, all sports, match grain</h3>
{html_table(
    [
        ("T0 favorite Yes", "text"), ("N", "num"), ("Wins", "num"), ("Win %", "num"),
        ("Mean cost (ask+fee)", "num"), ("Implied break-even %", "num"),
        ("Win % − BE %", "num"), ("With-fee PnL $", "num"), ("Mean $", "num"), ("Sample", "text"),
    ],
    cal_tables.get("always_all") or [],
    total=True,
)}
<h3>t0_fav_lt_90, all sports, match grain</h3>
{html_table(
    [
        ("T0 favorite Yes", "text"), ("N", "num"), ("Wins", "num"), ("Win %", "num"),
        ("Mean cost (ask+fee)", "num"), ("Implied break-even %", "num"),
        ("Win % − BE %", "num"), ("With-fee PnL $", "num"), ("Mean $", "num"), ("Sample", "text"),
    ],
    cal_tables.get("lt90_all") or [],
    total=True,
)}
<h3>Soccer — always_t0_fav</h3>
{html_table(
    [
        ("T0 favorite Yes", "text"), ("N", "num"), ("Wins", "num"), ("Win %", "num"),
        ("Mean cost (ask+fee)", "num"), ("Implied break-even %", "num"),
        ("Win % − BE %", "num"), ("With-fee PnL $", "num"), ("Mean $", "num"), ("Sample", "text"),
    ],
    cal_tables.get("always_soccer") or [],
    total=True,
)}
<h3>Soccer — t0_fav_lt_90</h3>
{html_table(
    [
        ("T0 favorite Yes", "text"), ("N", "num"), ("Wins", "num"), ("Win %", "num"),
        ("Mean cost (ask+fee)", "num"), ("Implied break-even %", "num"),
        ("Win % − BE %", "num"), ("With-fee PnL $", "num"), ("Mean $", "num"), ("Sample", "text"),
    ],
    cal_tables.get("lt90_soccer") or [],
    total=True,
)}
<h3>College football — always_t0_fav</h3>
{html_table(
    [
        ("T0 favorite Yes", "text"), ("N", "num"), ("Wins", "num"), ("Win %", "num"),
        ("Mean cost (ask+fee)", "num"), ("Implied break-even %", "num"),
        ("Win % − BE %", "num"), ("With-fee PnL $", "num"), ("Mean $", "num"), ("Sample", "text"),
    ],
    cal_tables.get("always_cfb") or [],
    total=True,
)}
<h3>College football — t0_fav_lt_90</h3>
{html_table(
    [
        ("T0 favorite Yes", "text"), ("N", "num"), ("Wins", "num"), ("Win %", "num"),
        ("Mean cost (ask+fee)", "num"), ("Implied break-even %", "num"),
        ("Win % − BE %", "num"), ("With-fee PnL $", "num"), ("Mean $", "num"), ("Sample", "text"),
    ],
    cal_tables.get("lt90_cfb") or [],
    total=True,
)}

<h2>By sport (match grain, always vs &lt;90¢)</h2>
{''.join(sport_blocks)}

<h2>Moneyline vs spread vs total (match grain, always vs &lt;90¢)</h2>
{''.join(kind_blocks)}

<h2>Venue-game grain (do not sum as an independent bankroll)</h2>
<p class="note">Same match on Kalshi and Gemini is two rows here. Headline P&amp;L above
picks one primary venue per match. Do not add this table to the match-grain dollars.</p>
{html_table(COMPARE_HEADERS, vg_rows)}

<p class="tiny">Generator: <code>tools/t0_fav_lt90_baseline_20261024.py</code>.
Living dashboard: <code>tools/t0_all_games_stats.py</code>. Band companion:
<code>tools/write_t0_band_from_stay_above.py</code>. Tests:
<code>tools/test_t0_fav_lt90_baseline_20261024.py</code>.
Written {esc(iso_now())} ET. file:// {esc(FILE_URL)}</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    STAMP.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    return PAGE


def build_recs(match_books: list[dict], venue_books: list[dict]) -> dict:
    recs: dict[str, dict] = {}

    def fill(key: str, books: list[dict], grain: str, sport=None, kind=None):
        recs[key] = {}
        for arm_id, label in ARM_SPECS:
            trades = trades_for(books, arm_id, documented_fee_only=True)
            trades = slice_trades(trades, sport=sport, kind=kind)
            recs[key][arm_id] = quality(trades, arm_id=arm_id, label=label, grain=grain)

    fill("match", match_books, "match")
    fill("venue", venue_books, "venue-game")
    fill("match_soccer", match_books, "match", sport="soccer")
    fill("match_cfb", match_books, "match", sport="college football")
    fill("match_tennis", match_books, "match", sport="tennis")
    fill("match_pro_football", match_books, "match", sport="pro football")
    fill("match_pro_hockey", match_books, "match", sport="pro hockey")
    fill("match_pro_baseball", match_books, "match", sport="pro baseball")
    fill("match_moneyline", match_books, "match", kind="moneyline")
    fill("match_spread", match_books, "match", kind="spread")
    fill("match_total", match_books, "match", kind="total")
    return recs


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


def main() -> int:
    print("scoring living books (one tape scan)", flush=True)
    payload = t0.build_payload()
    print("writing living dashboard", flush=True)
    t0.write_html(payload)
    t0.copy_g(t0.PAGE)
    print("writing band companion from the same books", flush=True)
    t0.rebuild_band_companion(payload)
    books = eligible_books(payload.get("books") or [])
    match_books = pick_primary(books)
    print(
        f"eligible two-sided settled unique-fav {len(books)} venue-games; "
        f"{len(match_books)} primary-venue matches",
        flush=True,
    )
    recs = build_recs(match_books, books)
    ineq = t0.inequality_rows(payload.get("full") or {})
    cal = {
        "always_all": calibration_rows(recs["match"]["always_t0_fav"]["trades"]),
        "lt90_all": calibration_rows(recs["match"]["t0_fav_lt_90"]["trades"]),
        "always_soccer": calibration_rows(recs["match_soccer"]["always_t0_fav"]["trades"]),
        "lt90_soccer": calibration_rows(recs["match_soccer"]["t0_fav_lt_90"]["trades"]),
        "always_cfb": calibration_rows(recs["match_cfb"]["always_t0_fav"]["trades"]),
        "lt90_cfb": calibration_rows(recs["match_cfb"]["t0_fav_lt_90"]["trades"]),
    }
    STAMP.mkdir(parents=True, exist_ok=True)
    write_baseline_md(payload, recs)
    path = write_html(payload, recs, ineq, cal)
    AUDIT_JSON.write_text(
        json.dumps({
            "full": {k: v for k, v in (payload.get("full") or {}).items() if k not in ("stay_buckets",)},
            "n_eligible_venue": len(books),
            "n_eligible_match": len(match_books),
            "written_at": iso_now(),
        }, indent=2, default=str),
        encoding="utf-8",
    )
    ARMS_JSON.write_text(json.dumps(jsonable(recs), indent=2, default=str), encoding="utf-8")
    always = recs["match"]["always_t0_fav"]
    lt90 = recs["match"]["t0_fav_lt_90"]
    print(
        f"HEADLINE always N={always['n']} pnl={always['pnl_sum']:.4f} "
        f"lt90 N={lt90['n']} pnl={lt90['pnl_sum']:.4f} wrote {path}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
