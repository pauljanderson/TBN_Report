#!/usr/bin/env python3
"""S&P X equal-weight book + shop trendline EXIT/HOLD overlays.

Research only. Not gold. Not DailyRun.

Phase 1: as-of weekly/monthly/daily support (confirmed pivots, signal-day close)
on every name ever held in CONTROL X=10 D=21 and/or IS-leaning X=5 D=126.
Phase 2: ≤6 one-knob overlays on the same equal-weight engine.

Usage:
  python tools/run_spx_trend_ab.py
  python tools/run_spx_trend_ab.py --skip-charts
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import math
import sys
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from run_spx_diversification import (  # noqa: E402
    INITIAL_CAPITAL,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    _fetch_sp500_tickers,
    load_price_panels,
    metrics_from_equity,
    refresh_market_caps,
    run_one_backtest,
    spy_buy_and_hold,
)
from trendline_slopes_paultwenty import (  # noqa: E402
    MONTH_FREQ,
    PIVOT_K,
    WEEK_FREQ,
    confirmed_pivots_daily,
    confirmed_pivots_htf,
    last_two_confirmed,
    line_price_at,
    load_ohlc,
    slope_metrics,
)

EXTEND = REPO / "drive" / "paul_experiments" / "spx_x_d_extend_20260916"
STAMP = REPO / "drive" / "paul_experiments" / "spx_trend_ab_20260916"
DB_PATH = REPO / "data" / "ohlcv.duckdb"
IS_CUT = "2024-01-01"
COST_BPS = 10.0
THRU_PCT = 2.0
EXT_PCT = 10.0
CASH_FRAC = 0.60

ORIGINAL_REQUEST = (
    "let's analyze all the charts through the years of all the stocks owned "
    "and apply some trend analysis to them. come up with some winning theories "
    "to test in a series of AB tests against these big stocks"
)

LAYMAN = (
    "We already have a simple book that owns the biggest Standard & Poor's 500 "
    "(S&P 500) names, equal dollars each, and rebalances on a timer. This job "
    "looks at the same names through the years using the shop's trendlines — "
    "a support line drawn from confirmed swing lows on weekly, monthly, and daily "
    "bars, scored as-of each rebalance (no peeking at the future). Then we test "
    "a few one-rule overlays: skip a new name, drop a name, or go to cash when "
    "the weekly support line is falling, broken, or the price is stretched too "
    "far above it. Control is the unmodified book. In-sample (IS) is 2011–2023; "
    "2024+ is out-of-sample (OOS) and report-only. We judge quality "
    "(Compound Annual Growth Rate (CAGR), max drawdown, Sharpe) not trade count. "
    "Research only — not DailyRun."
)

PRIMARY = {"X": 5, "N": 126, "label": "X5_D126"}
CHECK = {"X": 10, "N": 21, "label": "X10_D21"}


def _esc(s: Any) -> str:
    return html_mod.escape("" if s is None else str(s))


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{_esc(sort_type)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{_esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def load_career_tickers() -> tuple[list[str], dict[str, list[dict[str, Any]]]]:
    books = {
        "X10_D21": EXTEND / "ticker_careers_X10_D21.csv",
        "X5_D126": EXTEND / "ticker_careers_X5_D126.csv",
    }
    careers: dict[str, list[dict[str, Any]]] = {}
    names: set[str] = set()
    for key, path in books.items():
        df = pd.read_csv(path)
        rows = df.to_dict(orient="records")
        careers[key] = rows
        for rec in rows:
            t = str(rec.get("ticker") or "").strip().upper()
            if t:
                names.add(t)
    return sorted(names), careers


def load_add_drop() -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for key, name in (
        ("X10_D21", "add_drop_history_X10_D21.csv"),
        ("X5_D126", "add_drop_history_X5_D126.csv"),
    ):
        df = pd.read_csv(EXTEND / name)
        rows = []
        for rec in df.to_dict(orient="records"):
            def _names(raw: Any) -> list[str]:
                s = str(raw or "").strip()
                if not s or s == "—" or s.lower() == "nan":
                    return []
                return [p.strip().upper() for p in s.split(",") if p.strip() and p.strip() != "—"]

            rows.append(
                {
                    "date": str(rec.get("date") or "")[:10],
                    "year": rec.get("year"),
                    "kind": rec.get("kind"),
                    "added": _names(rec.get("added")),
                    "dropped": _names(rec.get("dropped")),
                    "held": _names(rec.get("held")),
                    "members": _names(rec.get("members")),
                }
            )
        out[key] = rows
    return out


class TrendBook:
    """Confirmed-pivot support/resistance scores, no lookahead."""

    def __init__(self, symbols: list[str]) -> None:
        self.pack: dict[str, dict[str, Any]] = {}
        self.missing: list[str] = []
        for sym in symbols:
            df = load_ohlc(sym)
            if df is None or df.empty:
                self.missing.append(sym)
                continue
            dates = [d if isinstance(d, date) else pd.Timestamp(d).date() for d in df["Date"]]
            self.pack[sym] = {
                "dates": dates,
                "close": [float(x) for x in df["Close"]],
                "date_set": set(dates),
                "piv_d": confirmed_pivots_daily(df, PIVOT_K["daily"]),
                "piv_w": confirmed_pivots_htf(df, WEEK_FREQ, PIVOT_K["weekly"]),
                "piv_m": confirmed_pivots_htf(df, MONTH_FREQ, PIVOT_K["monthly"]),
            }

    def _asof_bar(self, rec: dict[str, Any], as_of: date) -> tuple[date, float] | None:
        dates: list[date] = rec["dates"]
        # Signal-day close if that bar exists; else last prior completed bar.
        if as_of in rec["date_set"]:
            i = dates.index(as_of)
            return dates[i], float(rec["close"][i])
        prior = [d for d in dates if d < as_of]
        if not prior:
            return None
        d = prior[-1]
        i = dates.index(d)
        return d, float(rec["close"][i])

    def score_side(self, pivs: list[Any], as_of: date, close: float, kind: str) -> dict[str, Any]:
        empty = {
            "dir": "",
            "dist": float("nan"),
            "line": float("nan"),
            "slope_pct_per_day": float("nan"),
        }
        pair = last_two_confirmed(pivs, kind, as_of)
        if not pair:
            return empty
        a, b = pair
        active_from = max(a.confirmed_on, b.confirmed_on)
        if active_from > as_of:
            return empty
        sm = slope_metrics(a.date, a.price, b.date, b.price)
        line_px = line_price_at(a.date, a.price, b.date, b.price, as_of)
        dist = (
            (close - line_px) / line_px * 100.0
            if math.isfinite(line_px) and line_px != 0
            else float("nan")
        )
        return {
            "dir": sm["direction"],
            "dist": dist,
            "line": line_px,
            "slope_pct_per_day": sm["slope_pct_per_day"],
        }

    def score(self, sym: str, as_of: date) -> dict[str, Any]:
        rec = self.pack.get(sym)
        out: dict[str, Any] = {
            "symbol": sym,
            "as_of": as_of.isoformat(),
            "px_date": "",
            "close": float("nan"),
            "w_sup": "",
            "m_sup": "",
            "d_sup": "",
            "w_dist": float("nan"),
            "m_dist": float("nan"),
            "d_dist": float("nan"),
            "ok": False,
        }
        if not rec:
            return out
        bar = self._asof_bar(rec, as_of)
        if not bar:
            return out
        px_date, close = bar
        w = self.score_side(rec["piv_w"], px_date, close, "L")
        m = self.score_side(rec["piv_m"], px_date, close, "L")
        d = self.score_side(rec["piv_d"], px_date, close, "L")
        out.update(
            {
                "px_date": px_date.isoformat(),
                "close": close,
                "w_sup": w["dir"],
                "m_sup": m["dir"],
                "d_sup": d["dir"],
                "w_dist": w["dist"],
                "m_dist": m["dist"],
                "d_dist": d["dist"],
                "ok": True,
            }
        )
        return out


def _parse_iso(s: str) -> date:
    return date.fromisoformat(str(s)[:10])


def thru(dist: float) -> bool:
    return math.isfinite(dist) and dist < -THRU_PCT


def extended(dist: float) -> bool:
    return math.isfinite(dist) and dist > EXT_PCT


def diagnose(book: TrendBook, add_drop: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    event_rows: list[dict[str, Any]] = []
    month_rows: list[dict[str, Any]] = []
    for book_id, events in add_drop.items():
        held_by_year: dict[int, set[str]] = {}
        for ev in events:
            as_of = _parse_iso(ev["date"])
            for role, names in (
                ("added", ev["added"]),
                ("dropped", ev["dropped"]),
                ("held", ev["held"]),
            ):
                for sym in names:
                    sc = book.score(sym, as_of)
                    row = {
                        "book": book_id,
                        "date": ev["date"],
                        "year": ev.get("year"),
                        "role": role,
                        **sc,
                        "w_thru": thru(sc["w_dist"]),
                        "w_ext": extended(sc["w_dist"]),
                    }
                    event_rows.append(row)
            y = int(as_of.year)
            held_by_year[y] = set(ev["members"] or ev["held"] or [])

        # Month-end snapshots while a name is in that year's book
        all_dates: set[date] = set()
        for rec in book.pack.values():
            all_dates.update(rec["dates"])
        month_ends: dict[tuple[int, int], date] = {}
        for d in sorted(all_dates):
            month_ends[(d.year, d.month)] = d
        for (y, _m), d in sorted(month_ends.items()):
            names = held_by_year.get(y) or set()
            if not names:
                continue
            for sym in sorted(names):
                sc = book.score(sym, d)
                month_rows.append(
                    {
                        "book": book_id,
                        "date": d.isoformat(),
                        "year": y,
                        "role": "month_end_held",
                        **sc,
                        "w_thru": thru(sc["w_dist"]),
                        "w_ext": extended(sc["w_dist"]),
                    }
                )

    def _mix(rows: list[dict[str, Any]], role: str) -> dict[str, Any]:
        sub = [r for r in rows if r["role"] == role]
        n = len(sub)
        dirs = Counter(r["w_sup"] or "NONE" for r in sub)
        return {
            "n": n,
            "w_up": dirs.get("UP", 0),
            "w_down": dirs.get("DOWN", 0),
            "w_flat": dirs.get("FLAT", 0),
            "w_none": dirs.get("NONE", 0),
            "w_thru": sum(1 for r in sub if r["w_thru"]),
            "w_ext": sum(1 for r in sub if r["w_ext"]),
            "m_down": sum(1 for r in sub if r.get("m_sup") == "DOWN"),
            "pct_w_up": (100.0 * dirs.get("UP", 0) / n) if n else 0.0,
            "pct_w_down": (100.0 * dirs.get("DOWN", 0) / n) if n else 0.0,
            "pct_w_thru": (100.0 * sum(1 for r in sub if r["w_thru"]) / n) if n else 0.0,
            "pct_w_ext": (100.0 * sum(1 for r in sub if r["w_ext"]) / n) if n else 0.0,
            "pct_m_down": (100.0 * sum(1 for r in sub if r.get("m_sup") == "DOWN") / n) if n else 0.0,
        }

    mixes = {
        "added": _mix(event_rows, "added"),
        "dropped": _mix(event_rows, "dropped"),
        "held_recon": _mix(event_rows, "held"),
        "month_end_held": _mix(month_rows, "month_end_held"),
    }

    notes: list[str] = []
    add = mixes["added"]
    drop = mixes["dropped"]
    held = mixes["month_end_held"]
    notes.append(
        f"Adds (n={add['n']}): weekly support UP {add['pct_w_up']:.0f}%, "
        f"DOWN {add['pct_w_down']:.0f}%, through the line {add['pct_w_thru']:.0f}%, "
        f"extended >{EXT_PCT:.0f}% {add['pct_w_ext']:.0f}%, monthly DOWN {add['pct_m_down']:.0f}%."
    )
    notes.append(
        f"Drops (n={drop['n']}): weekly support UP {drop['pct_w_up']:.0f}%, "
        f"DOWN {drop['pct_w_down']:.0f}%, through the line {drop['pct_w_thru']:.0f}%, "
        f"extended >{EXT_PCT:.0f}% {drop['pct_w_ext']:.0f}%, monthly DOWN {drop['pct_m_down']:.0f}%."
    )
    notes.append(
        f"Month-end while held (n={held['n']}): weekly UP {held['pct_w_up']:.0f}%, "
        f"DOWN {held['pct_w_down']:.0f}%, through {held['pct_w_thru']:.0f}%, "
        f"extended >{EXT_PCT:.0f}% {held['pct_w_ext']:.0f}%."
    )

    # Concrete edge-shaped notes (not a kitchen sink)
    if add["n"] and add["pct_w_down"] >= 20:
        notes.append(
            "Pattern: a meaningful slice of adds arrived with weekly support already DOWN — "
            "skip-add-if-DOWN is chart-supported, not decorative."
        )
    if drop["n"] and drop["pct_w_down"] >= add["pct_w_down"] + 10:
        notes.append(
            "Pattern: drops were more often weekly-DOWN than adds — a hold/drop overlay "
            "on falling weekly support has a story (may just be the 2022 growth crash)."
        )
    if held["n"] and held["pct_w_ext"] >= 50:
        notes.append(
            "Pattern: these mega-caps sit extended above weekly support most of the time "
            "they are owned. Skip-if-extended will often leave slots empty — test it, "
            "but watch for a 1-name / cash lottery."
        )
    if held["n"] and held["pct_w_thru"] <= 20:
        notes.append(
            "Pattern: while held, closes are through weekly support only ~17% of month-ends. "
            "Drop-if-broken is a sparse overlay, not constant churn."
        )
    if add["n"] and add["pct_m_down"] >= 20:
        notes.append(
            "Pattern: some adds had monthly support DOWN. A monthly skip-add is a "
            "higher-timeframe cousin of the weekly skip — one knob, not stacked with weekly."
        )

    # Highlight specific famous rotations
    highlights = []
    for r in event_rows:
        if r["role"] not in ("added", "dropped"):
            continue
        if r["symbol"] in {"META", "TSLA", "NVDA", "UNH", "XOM", "CVX", "AMZN"}:
            highlights.append(r)

    def _one(book_id: str, dt: str, role: str, sym: str) -> dict[str, Any] | None:
        for r in event_rows:
            if (
                r.get("book") == book_id
                and str(r.get("date"))[:10] == dt
                and r.get("role") == role
                and r.get("symbol") == sym
            ):
                return r
        return None

    examples = [
        ("X5_D126", "2021-01-05", "added", "TSLA",
         "TSLA entered the 5 at weekly UP but +66% above weekly support (stretched add)."),
        ("X5_D126", "2023-01-04", "dropped", "TSLA",
         "TSLA left the 5 with weekly DOWN and −19% through support — the broken-support drop story."),
        ("X5_D126", "2023-01-04", "added", "UNH",
         "UNH replaced TSLA: weekly UP but already ~3% through support."),
        ("X5_D126", "2024-01-03", "added", "NVDA",
         "NVDA entered 2024 weekly UP but −5% through support — skip-add-if-through would have missed the OOS rocket."),
        ("X10_D21", "2023-01-04", "dropped", "META",
         "META left the 10 after 2022: weekly DOWN (falling line) but still far above it, not through."),
        ("X10_D21", "2023-01-04", "dropped", "NVDA",
         "NVDA left the 10 Jan 2023: weekly DOWN, still +82% above the falling line."),
        ("X10_D21", "2022-01-04", "added", "NVDA",
         "NVDA first entered Jan 2022 weekly UP and +36% extended."),
        ("X5_D126", "2018-01-03", "dropped", "XOM",
         "XOM left the 5 in 2018 with weekly UP — a market-cap rotation, not a trend break."),
        ("X5_D126", "2015-01-05", "added", "JNJ",
         "JNJ entered the 5 in 2015 with weekly support already DOWN."),
    ]
    for book_id, dt, role, sym, text in examples:
        if _one(book_id, dt, role, sym):
            notes.append(f"{sym} {dt} ({book_id} {role}): {text}")

    return {
        "event_rows": event_rows,
        "month_rows": month_rows,
        "mixes": mixes,
        "notes": notes,
        "highlights": highlights,
    }


def make_filter(arm: str, trend: TrendBook, syms: list[str], calendar: pd.DatetimeIndex):
    idx = {s: i for i, s in enumerate(syms)}

    def _asof(signal_i: int) -> date:
        return pd.Timestamp(calendar[int(signal_i)]).date()

    def _sc(j: int, as_of: date) -> dict[str, Any]:
        if j < 0 or j >= len(syms):
            return {"ok": False, "w_sup": "", "m_sup": "", "w_dist": float("nan")}
        return trend.score(syms[j], as_of)

    def filt(signal_i: int, proposed: list[int], current: list[int], kind: str) -> list[int]:
        as_of = _asof(signal_i)
        cur = set(int(x) for x in current)
        scores = {int(j): _sc(int(j), as_of) for j in proposed}

        if arm == "control":
            return list(proposed)

        if arm == "no_add_w_down_or_thru2":
            out = []
            for j in proposed:
                j = int(j)
                if j in cur:
                    out.append(j)
                    continue
                sc = scores[j]
                if sc.get("w_sup") == "DOWN" or thru(float(sc.get("w_dist") or float("nan"))):
                    continue
                out.append(j)
            return out

        if arm == "drop_w_break":
            return [
                int(j)
                for j in proposed
                if not thru(float(scores[int(j)].get("w_dist") or float("nan")))
            ]

        if arm == "skip_ext10":
            return [
                int(j)
                for j in proposed
                if not extended(float(scores[int(j)].get("w_dist") or float("nan")))
            ]

        if arm == "stay_w_up":
            return [int(j) for j in proposed if scores[int(j)].get("w_sup") == "UP"]

        if arm == "cash_if_60pct_w_down":
            n = len(proposed)
            if n == 0:
                return []
            n_down = sum(1 for j in proposed if scores[int(j)].get("w_sup") == "DOWN")
            thresh = max(1, int(math.ceil(CASH_FRAC * n)))
            if n_down >= thresh:
                return []
            return [int(j) for j in proposed]

        if arm == "no_add_m_down":
            out = []
            for j in proposed:
                j = int(j)
                if j in cur:
                    out.append(j)
                    continue
                if scores[j].get("m_sup") == "DOWN":
                    continue
                out.append(j)
            return out

        return list(proposed)

    # silence unused
    _ = idx
    return filt


ARMS: list[dict[str, str]] = [
    {
        "id": "control",
        "kind": "CONTROL",
        "one_liner": "Unmodified equal-weight rebalance book (no trend overlay).",
    },
    {
        "id": "no_add_w_down_or_thru2",
        "kind": "ENTRY",
        "one_liner": "Don't add a name if weekly support is DOWN or close is >2% through weekly support; incumbents stay.",
    },
    {
        "id": "drop_w_break",
        "kind": "EXIT",
        "one_liner": "Drop (sell to cash / skip slot) if close is >2% through weekly support.",
    },
    {
        "id": "skip_ext10",
        "kind": "HOLD",
        "one_liner": "Skip the slot if close is >10% above weekly support (no capital in extended names).",
    },
    {
        "id": "stay_w_up",
        "kind": "HOLD",
        "one_liner": "Require weekly support UP to stay in the book; otherwise skip slot.",
    },
    {
        "id": "cash_if_60pct_w_down",
        "kind": "EXIT",
        "one_liner": "Cash the whole book if ≥60% of the roster has weekly support DOWN (≥3 of 5; ≥6 of 10).",
    },
    {
        "id": "no_add_m_down",
        "kind": "ENTRY",
        "one_liner": "Don't add a name if monthly support is DOWN; incumbents stay.",
    },
]


def _held_vals(held_counts: list[tuple[str, int]]) -> list[int]:
    vals = [int(n) for _d, n in held_counts]
    while vals and vals[0] == 0:
        vals.pop(0)
    return vals


def _avg_held(held_counts: list[tuple[str, int]]) -> float:
    vals = _held_vals(held_counts)
    if not vals:
        return float("nan")
    return float(np.mean(vals))


def _min_held(held_counts: list[tuple[str, int]]) -> int:
    vals = _held_vals(held_counts)
    if not vals:
        return 0
    return int(min(vals))


def result_payload(r: Any, arm_id: str, book_label: str) -> dict[str, Any]:
    extras = r.extras or {}
    eq = extras.get("equity") or []
    dates = [d for d, _v in eq]
    equity = [float(v) for _d, v in eq]
    held = extras.get("held_counts") or []
    slices = {
        "IS": metrics_from_equity(dates, equity, end=IS_CUT),
        "OOS": metrics_from_equity(dates, equity, start=IS_CUT),
        "FULL": metrics_from_equity(dates, equity),
    }
    return {
        "arm": arm_id,
        "book": book_label,
        "X": r.X,
        "N": r.N,
        "ok": r.ok,
        "error": r.error,
        "start": r.start,
        "end": r.end,
        "final_equity": r.final_equity,
        "total_return": r.total_return,
        "cagr": r.cagr,
        "max_dd": r.max_dd,
        "sharpe": r.sharpe,
        "ann_vol": r.ann_vol,
        "total_trades": r.total_trades,
        "turnover": r.turnover,
        "n_rebalances": r.n_rebalances,
        "n_reconstitutions": r.n_reconstitutions,
        "avg_held": _avg_held(held),
        "min_held": _min_held(held),
        "slices": slices,
        "equity": eq,
        "ledger": extras.get("ledger") or [],
        "membership": extras.get("membership") or [],
    }


def _fmt(x: Any, nd: int = 2) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(v):
        return "—"
    return f"{v:.{nd}f}"


def _fmt_money(x: Any) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(v):
        return "—"
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.2f}"


def _delta(a: Any, b: Any) -> str:
    try:
        av = float(a)
        bv = float(b)
    except (TypeError, ValueError):
        return "—"
    if not (math.isfinite(av) and math.isfinite(bv)):
        return "—"
    d = av - bv
    return f"{d:+.2f}"


def judge_book(control: dict[str, Any], arm: dict[str, Any]) -> tuple[str, str]:
    if arm["arm"] == "control":
        return "CONTROL", "Unmodified book."
    cis, ais = control["slices"]["IS"], arm["slices"]["IS"]
    coos, aoos = control["slices"]["OOS"], arm["slices"]["OOS"]
    if not (cis.get("ok") and ais.get("ok")):
        return "DISMISS", "IS slice missing."
    avg_h = float(arm.get("avg_held") or 0)
    if math.isfinite(avg_h) and avg_h < 2.0:
        return "DISMISS", f"Lottery: average names held {avg_h:.2f} (<2)."

    cagr_up = ais["cagr"] >= cis["cagr"] + 0.10
    sharpe_up = ais["sharpe"] >= cis["sharpe"] + 0.01
    dd_ok = ais["max_dd"] <= cis["max_dd"] + 2.0
    cagr_down = ais["cagr"] <= cis["cagr"] - 0.50
    sharpe_down = ais["sharpe"] <= cis["sharpe"] - 0.03
    dd_worse = ais["max_dd"] >= cis["max_dd"] + 3.0

    is_quality = cagr_up and sharpe_up and dd_ok
    is_worse = (cagr_down and sharpe_down) or (dd_worse and not (cagr_up and sharpe_up))

    oos_ok = bool(coos.get("ok") and aoos.get("ok"))
    oos_soften = False
    if oos_ok:
        oos_soften = (
            aoos["cagr"] < coos["cagr"] - 1.0
            or aoos["sharpe"] < coos["sharpe"] - 0.05
            or aoos["max_dd"] > coos["max_dd"] + 3.0
        )

    if is_worse:
        return (
            "DISMISS",
            f"IS quality worse (CAGR {_fmt(ais['cagr'])} vs {_fmt(cis['cagr'])}, "
            f"Sharpe {_fmt(ais['sharpe'])} vs {_fmt(cis['sharpe'])}, "
            f"MaxDD {_fmt(ais['max_dd'])} vs {_fmt(cis['max_dd'])}).",
        )
    if is_quality and oos_soften:
        return (
            "HOLD",
            "IS quality beat control, but OOS softened — report-only, do not retune.",
        )
    if is_quality and not oos_soften:
        return (
            "KEEP",
            "IS quality beat control (CAGR + Sharpe, MaxDD not much worse) and OOS did not soften. "
            "Research only — not gold, not DailyRun.",
        )
    return (
        "HOLD",
        "IS mixed / flat vs control on quality. No KEEP.",
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    pd.DataFrame(rows).to_csv(path, index=False)


def _fix_compare_table(book_label: str, rows: list[dict[str, Any]], verdicts: dict[str, tuple[str, str]]) -> str:
    """Canonical-ish IS/OOS/FULL compare. Ann ROR = CAGR on this engine."""
    heads = [
        ("Arm", "text"),
        ("Kind", "text"),
        ("Verdict", "text"),
        ("IS CAGR %", "num"),
        ("IS MaxDD %", "num"),
        ("IS Sharpe", "num"),
        ("IS Calmar", "num"),
        ("Δ IS CAGR", "num"),
        ("Δ IS MaxDD", "num"),
        ("Δ IS Sharpe", "num"),
        ("OOS CAGR %", "num"),
        ("OOS MaxDD %", "num"),
        ("OOS Sharpe", "num"),
        ("OOS Calmar", "num"),
        ("FULL CAGR % / Ann ROR", "num"),
        ("FULL MaxDD %", "num"),
        ("FULL Sharpe", "num"),
        ("FULL Calmar", "num"),
        ("FULL final $", "num"),
        ("Avg held", "num"),
        ("Min held", "num"),
        ("Trades", "num"),
        ("Turnover", "num"),
        ("Rebalances", "num"),
    ]
    control = next(r for r in rows if r["arm"] == "control")
    thead = "".join(sortable_th(l, t) for l, t in heads)
    meta = {a["id"]: a for a in ARMS}
    body = []
    for r in rows:
        v, _why = verdicts[f"{book_label}:{r['arm']}"]
        cis, ais = control["slices"], r["slices"]
        kind = meta.get(r["arm"], {}).get("kind", "")
        cls = {"KEEP": "keep", "HOLD": "hold", "DISMISS": "dismiss", "CONTROL": "ctrl"}.get(v, "")
        cells = [
            _esc(r["arm"]),
            _esc(kind),
            f'<span class="{cls}">{_esc(v)}</span>',
            _fmt(ais["IS"].get("cagr")) if ais["IS"].get("ok") else "—",
            _fmt(ais["IS"].get("max_dd")) if ais["IS"].get("ok") else "—",
            _fmt(ais["IS"].get("sharpe"), 3) if ais["IS"].get("ok") else "—",
            _fmt(ais["IS"].get("calmar"), 3) if ais["IS"].get("ok") and ais["IS"].get("calmar") is not None else "—",
            _delta(ais["IS"].get("cagr"), cis["IS"].get("cagr")) if ais["IS"].get("ok") else "—",
            _delta(ais["IS"].get("max_dd"), cis["IS"].get("max_dd")) if ais["IS"].get("ok") else "—",
            _delta(ais["IS"].get("sharpe"), cis["IS"].get("sharpe")) if ais["IS"].get("ok") else "—",
            _fmt(ais["OOS"].get("cagr")) if ais["OOS"].get("ok") else "—",
            _fmt(ais["OOS"].get("max_dd")) if ais["OOS"].get("ok") else "—",
            _fmt(ais["OOS"].get("sharpe"), 3) if ais["OOS"].get("ok") else "—",
            _fmt(ais["OOS"].get("calmar"), 3) if ais["OOS"].get("ok") and ais["OOS"].get("calmar") is not None else "—",
            _fmt(ais["FULL"].get("cagr")) if ais["FULL"].get("ok") else "—",
            _fmt(ais["FULL"].get("max_dd")) if ais["FULL"].get("ok") else "—",
            _fmt(ais["FULL"].get("sharpe"), 3) if ais["FULL"].get("ok") else "—",
            _fmt(ais["FULL"].get("calmar"), 3) if ais["FULL"].get("ok") and ais["FULL"].get("calmar") is not None else "—",
            _fmt_money(r.get("final_equity")),
            _fmt(r.get("avg_held")),
            str(int(r.get("min_held") or 0)),
            str(int(r.get("total_trades") or 0)),
            _fmt(r.get("turnover")),
            str(int(r.get("n_rebalances") or 0)),
        ]
        body.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    return (
        f'<p class="meta"><strong>{_esc(book_label)}</strong> — click column headers to sort. '
        "Ann ROR on this continuous equal-weight book is CAGR on the same equity path.</p>"
        f'<table class="sortable"><thead><tr>{thead}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def event_table(rows: list[dict[str, Any]], caption: str) -> str:
    heads = [
        ("Book", "text"),
        ("Date", "date"),
        ("Role", "text"),
        ("Symbol", "text"),
        ("W sup", "text"),
        ("W dist %", "num"),
        ("M sup", "text"),
        ("M dist %", "num"),
        ("D sup", "text"),
        ("Through?", "text"),
        ("Extended?", "text"),
    ]
    thead = "".join(sortable_th(l, t) for l, t in heads)
    body = []
    for r in rows:
        wcls = {"UP": "up", "DOWN": "down"}.get(str(r.get("w_sup") or ""), "")
        body.append(
            "<tr>"
            f"<td>{_esc(r.get('book'))}</td>"
            f"<td>{_esc(r.get('date'))}</td>"
            f"<td>{_esc(r.get('role'))}</td>"
            f"<td>{_esc(r.get('symbol'))}</td>"
            f'<td class="{wcls}">{_esc(r.get("w_sup") or "—")}</td>'
            f"<td>{_fmt(r.get('w_dist'))}</td>"
            f"<td>{_esc(r.get('m_sup') or '—')}</td>"
            f"<td>{_fmt(r.get('m_dist'))}</td>"
            f"<td>{_esc(r.get('d_sup') or '—')}</td>"
            f"<td>{'yes' if r.get('w_thru') else 'no'}</td>"
            f"<td>{'yes' if r.get('w_ext') else 'no'}</td>"
            "</tr>"
        )
    return (
        f'<p class="meta">{_esc(caption)} Click column headers to sort.</p>'
        f'<table class="sortable"><thead><tr>{thead}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def load_engine_panels(start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, dict[str, float], list[str]]:
    try:
        wiki = _fetch_sp500_tickers()
    except Exception:
        cached = REPO / "drive" / "spx_diversification" / "sp500_constituents_wikipedia.txt"
        alt = EXTEND / "sp500_constituents_wikipedia.txt"
        path = cached if cached.is_file() else alt
        wiki = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    import duckdb

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        db_syms = {str(r[0]).upper() for r in con.execute("SELECT DISTINCT symbol FROM prices").fetchall()}
    finally:
        con.close()
    universe = [s for s in wiki if s in db_syms]
    mcap = refresh_market_caps(universe, workers=8, force=False)
    if "GOOG" in mcap and "GOOGL" in mcap:
        mcap.pop("GOOG", None)
    opens, closes, spy = load_price_panels(list(mcap.keys()), start=start, end=end)
    keep = [c for c in closes.columns if c == "SPY" or c in mcap]
    return opens[keep], closes[keep], spy, mcap, universe


def maybe_charts(symbols: list[str]) -> dict[str, Any]:
    try:
        from trendlines_ensure_charts import ensure_charts

        return ensure_charts(symbols, STAMP)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "built": [], "failed": list(symbols)}


def write_baseline(
    path: Path,
    *,
    names: list[str],
    notes: list[str],
    verdicts: dict[str, tuple[str, str]],
    primary_rows: list[dict[str, Any]],
    check_rows: list[dict[str, Any]],
    overall: str,
    overall_why: str,
) -> None:
    lines = [
        "# BASELINE — spx_trend_ab_20260916",
        "",
        "**Status:** Research candidate. **Not gold. Not DailyRun.** OOS report-only.",
        "",
        "## What you asked",
        "",
        f"> {ORIGINAL_REQUEST}",
        "",
        "## In plain English",
        "",
        LAYMAN,
        "",
        "## Freeze (do not silently mutate)",
        "",
        "- **Engine:** `tools/run_spx_diversification.py` equal-weight top-X, annual recon, intra-year every D trading days",
        "- **Primary book:** X=5 D=126 (IS-leaning from `spx_x_d_extend_20260916`)",
        "- **Check book:** X=10 D=21 (CONTROL from that stamp)",
        "- **Capital:** $500,000",
        "- **Costs:** 10 bps/side on traded notional",
        "- **Fills:** next open after signal close",
        "- **Trend as-of:** signal-day close (prior completed bar vs next-open fill); confirmed fractal pivots only (`confirmed_on <= as_of`)",
        "- **Pivots:** daily k=5, weekly W-FRI k=3, monthly ME k=2 (shop `trendline_slopes_paultwenty`)",
        "- **Missing line:** not DOWN / not through / not extended (pass-through) except `stay_w_up` which requires an actual UP",
        "- **No substitute names:** skipped slots stay cash; do not promote the next-largest cap",
        "- **Cash overlay threshold:** ≥60% of roster weekly support DOWN (3 of 5; 6 of 10)",
        "- **IS:** equity date < 2024-01-01",
        "- **OOS:** equity date ≥ 2024-01-01 (report-only; do not retune)",
        "- **One knob per arm.** Judge quality (CAGR, MaxDD, Sharpe) over count.",
        "- **Not DailyRun. Not gold.**",
        "",
        "## Names covered (union of CONTROL X=10 D=21 and X=5 D=126 careers)",
        "",
        ", ".join(names),
        "",
        "## Chart / theory notes",
        "",
    ]
    for n in notes:
        lines.append(f"- {n}")
    lines += [
        "",
        "## Arms (one hypothesis each)",
        "",
    ]
    for a in ARMS:
        lines.append(f"- **{a['id']}** ({a['kind']}): {a['one_liner']}")
    lines += [
        "",
        "## Honesty / selection",
        "",
        "- Prior DailyRun fill trendline ABs (buy-low B; skip-broken-weekly) were HOLD/DISMISS. "
        "This is a **different book** (equal-weight mega-cap hold + rebalance). Those verdicts are not assumed.",
        "- Six overlays were proposed from the Phase 1 mix (adds vs drops vs month-end-held), then frozen. "
        "Choosing a winner after seeing the table is in-sample selection — KEEP still requires IS quality "
        "and no OOS soften, and is research-only.",
        "- OOS is report-only. If OOS softens → HOLD, do not retune thresholds (2%, 10%, 60%).",
        "- Survivorship and scaled-now market caps inherited from the S&P X engine.",
        "",
        f"## Overall verdict: **{overall}**",
        "",
        overall_why,
        "",
        "## Primary X=5 D=126",
        "",
    ]
    ctrl = next(r for r in primary_rows if r["arm"] == "control")
    for r in primary_rows:
        v, why = verdicts[f"X5_D126:{r['arm']}"]
        sl = r["slices"]
        lines.append(
            f"- **{r['arm']}** {v}: IS CAGR {_fmt(sl['IS'].get('cagr'))}% MaxDD {_fmt(sl['IS'].get('max_dd'))}% "
            f"Sharpe {_fmt(sl['IS'].get('sharpe'), 3)} · OOS CAGR {_fmt(sl['OOS'].get('cagr'))}% "
            f"MaxDD {_fmt(sl['OOS'].get('max_dd'))}% Sharpe {_fmt(sl['OOS'].get('sharpe'), 3)} · "
            f"FULL CAGR {_fmt(sl['FULL'].get('cagr'))}% · avg held {_fmt(r.get('avg_held'))} · {why}"
        )
    lines += ["", "## Check X=10 D=21", ""]
    for r in check_rows:
        v, why = verdicts[f"X10_D21:{r['arm']}"]
        sl = r["slices"]
        lines.append(
            f"- **{r['arm']}** {v}: IS CAGR {_fmt(sl['IS'].get('cagr'))}% MaxDD {_fmt(sl['IS'].get('max_dd'))}% "
            f"Sharpe {_fmt(sl['IS'].get('sharpe'), 3)} · OOS CAGR {_fmt(sl['OOS'].get('cagr'))}% "
            f"MaxDD {_fmt(sl['OOS'].get('max_dd'))}% Sharpe {_fmt(sl['OOS'].get('sharpe'), 3)} · "
            f"avg held {_fmt(r.get('avg_held'))} · {why}"
        )
    lines += [
        "",
        "## Control reprints (unmodified engine)",
        "",
        f"- Primary control start {ctrl['start']} end {ctrl['end']}",
        "",
        "## Caveats",
        "",
        "- Today's Wikipedia S&P 500 list projected backward (survivorship).",
        "- Market caps are Yahoo-now scaled by Close_t / Close_now.",
        "- Dividends not reinvested. Next-open fills. 10 bps/side.",
        "- Shop 6-month PNGs (if present) are latest-lookback visuals; through-the-years analysis is the as-of score tables.",
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_html(
    path: Path,
    *,
    names: list[str],
    diag: dict[str, Any],
    verdicts: dict[str, tuple[str, str]],
    primary_rows: list[dict[str, Any]],
    check_rows: list[dict[str, Any]],
    overall: str,
    overall_why: str,
    charts_info: dict[str, Any],
) -> None:
    add_rows = [r for r in diag["event_rows"] if r["role"] in ("added", "dropped")]
    add_rows = sorted(add_rows, key=lambda r: (str(r.get("date")), str(r.get("book")), str(r.get("role"))))
    highlights = sorted(diag["highlights"], key=lambda r: (str(r.get("date")), str(r.get("symbol"))))
    theory_lis = "".join(
        f"<li><strong>{_esc(a['id'])}</strong> ({_esc(a['kind'])}): {_esc(a['one_liner'])}</li>"
        for a in ARMS
        if a["id"] != "control"
    )
    note_lis = "".join(f"<li>{_esc(n)}</li>" for n in diag["notes"])
    v_lis = []
    for key, (v, why) in verdicts.items():
        if key.endswith(":control"):
            continue
        v_lis.append(f"<li><code>{_esc(key)}</code> <strong>{_esc(v)}</strong> — {_esc(why)}</li>")
    built = charts_info.get("built") or []
    already = charts_info.get("already_ok") or []
    failed = charts_info.get("failed") or []
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>S&P X trend overlays — spx_trend_ab_20260916</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1.5rem; color: #0f172a; background: #f8fafc; }}
h1 {{ font-size: 1.45rem; margin: 0 0 .35rem; }}
h2 {{ font-size: 1.15rem; margin: 1.6rem 0 .5rem; border-bottom: 1px solid #cbd5e1; padding-bottom: .25rem; }}
.meta, .caveat {{ color: #475569; font-size: .92rem; max-width: 72rem; }}
.callout {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .85rem 1rem; margin: .75rem 0; max-width: 72rem; }}
table.sortable {{ border-collapse: collapse; background: #fff; font-size: .82rem; margin: .5rem 0 1rem; }}
table.sortable th, table.sortable td {{ border: 1px solid #e2e8f0; padding: .32rem .5rem; text-align: left; }}
table.sortable th {{ background: #f1f5f9; }}
.up {{ color: #047857; font-weight: 600; }}
.down {{ color: #b91c1c; font-weight: 600; }}
.keep {{ color: #047857; font-weight: 700; }}
.hold {{ color: #b45309; font-weight: 700; }}
.dismiss {{ color: #b91c1c; font-weight: 700; }}
.ctrl {{ color: #334155; font-weight: 700; }}
{SORTABLE_TH_CSS}
</style></head><body>
<h1>S&P X trend overlays — 2026-09-16</h1>
<p class="meta">Research only. Not gold. Not DailyRun. Stamp <code>spx_trend_ab_20260916</code>.</p>
<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
<p>{_esc(ORIGINAL_REQUEST)}</p>
<h2>In plain English</h2>
<p>{_esc(LAYMAN)}</p>
</div>
<h2>Overall verdict: {_esc(overall)}</h2>
<p class="meta">{_esc(overall_why)}</p>
<h2>Names covered</h2>
<p class="meta">{_esc(", ".join(names))} ({len(names)} unique careers from CONTROL X=10 D=21 and/or X=5 D=126).</p>
<h2>Chart / theory notes</h2>
<ul class="meta">{note_lis}</ul>
<p class="meta">Shop charts (latest 6-month lookback) built={len(built)} already={len(already)} failed={len(failed)}.
Through-the-years work is the as-of score tables, not a gallery of 15-year PNGs.
{(' Chart index: <a href="charts/index.html">charts/index.html</a>.' ) if (STAMP / 'charts' / 'index.html').is_file() else ''}</p>
<h2>Theories tested (one knob each)</h2>
<ul class="meta">{theory_lis}</ul>
<h2>Compare — primary X=5 D=126</h2>
{_fix_compare_table("X5_D126", primary_rows, verdicts)}
<h2>Compare — check X=10 D=21</h2>
{_fix_compare_table("X10_D21", check_rows, verdicts)}
<h2>Per-arm verdicts</h2>
<ul class="meta">{''.join(v_lis)}</ul>
<h2>Adds / drops as-of weekly support</h2>
{event_table(add_rows, "Every annual add and drop, scored as-of the reconstitution signal date.")}
<h2>Headline rotations (energy / META / TSLA / NVDA / UNH / AMZN)</h2>
{event_table(highlights, "Same as-of scores, filtered to the names Paul called out plus the energy pair.")}
<h2>Freeze</h2>
<ul class="meta">
<li>Same equal-weight engine as <code>spx_x_d_extend_20260916</code>. Overlay is the only change.</li>
<li>IS = entry/equity date &lt; 2024-01-01; OOS 2024+ report-only.</li>
<li>Confirmed pivots only; signal-day close vs next-open fill.</li>
<li>Skipped slots stay cash — no next-cap substitute.</li>
<li>KEEP only if IS quality beats control without a 1-name lottery; OOS soften → HOLD.</li>
</ul>
<h2>Caveats</h2>
<ul class="meta caveat">
<li>Survivorship: today's S&amp;P 500 list projected backward.</li>
<li>Market caps are Yahoo-now scaled by price (not true historical free float).</li>
<li>Prior DailyRun trendline fill ABs were HOLD/DISMISS — different book, not assumed here.</li>
<li>Six arms after seeing Phase 1 mixes is still in-sample selection of the menu. Verdicts vs frozen control.</li>
</ul>
<script>{SORTABLE_TABLE_SCRIPT}</script>
</body></html>
"""
    path.write_text(html, encoding="utf-8")


def overall_verdict(verdicts: dict[str, tuple[str, str]], primary_rows: list[dict[str, Any]]) -> tuple[str, str]:
    prim = {k.split(":", 1)[1]: v for k, v in verdicts.items() if k.startswith("X5_D126:") and not k.endswith(":control")}
    keeps = [k for k, (v, _) in prim.items() if v == "KEEP"]
    holds = [k for k, (v, _) in prim.items() if v == "HOLD"]
    if keeps:
        # pick best IS sharpe among KEEP
        best = None
        best_sh = -1e9
        for r in primary_rows:
            if r["arm"] in keeps and r["slices"]["IS"].get("ok"):
                sh = float(r["slices"]["IS"]["sharpe"])
                if sh > best_sh:
                    best_sh = sh
                    best = r
        name = best["arm"] if best else keeps[0]
        return (
            "KEEP",
            f"Primary KEEP: {name} vs unmodified X=5 D=126 on IS quality without a lottery, "
            "and OOS did not soften. Research only — do not wire DailyRun.",
        )
    if holds:
        return (
            "HOLD",
            "No primary KEEP. Best case is HOLD (IS mixed/flat, or IS lift reversed/softened OOS). "
            "Do not retune 2% / 10% / 60% on 2024+.",
        )
    return (
        "DISMISS",
        "All primary overlays lost IS quality or collapsed holdings. Trend overlays did not beat "
        "the unmodified mega-cap book on this freeze.",
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-charts", action="store_true")
    ap.add_argument("--start", default="2010-01-01")
    ap.add_argument("--end", default="2026-12-31")
    args = ap.parse_args()
    t0 = time.time()
    STAMP.mkdir(parents=True, exist_ok=True)

    names, careers = load_career_tickers()
    add_drop = load_add_drop()
    print(f"[spx-tl] names {len(names)}: {', '.join(names)}", flush=True)

    print("[spx-tl] building confirmed-pivot books...", flush=True)
    trend = TrendBook(names)
    if trend.missing:
        print(f"[spx-tl] missing OHLC: {trend.missing}", flush=True)

    print("[spx-tl] Phase 1 diagnosis...", flush=True)
    diag = diagnose(trend, add_drop)
    write_csv(STAMP / "asof_add_drop_scores.csv", diag["event_rows"])
    # month-end is large; keep a compact monthly mix + write full csv
    write_csv(STAMP / "asof_month_end_held_scores.csv", diag["month_rows"])
    (STAMP / "diagnosis_notes.json").write_text(
        json.dumps({"notes": diag["notes"], "mixes": diag["mixes"], "missing_ohlc": trend.missing}, indent=2),
        encoding="utf-8",
    )

    print("[spx-tl] loading engine panels...", flush=True)
    opens, closes, spy, mcap, _universe = load_engine_panels(args.start, args.end)
    calendar = closes.index
    syms = [c for c in closes.columns if c != "SPY" and c in mcap]
    print(f"[spx-tl] panel {len(calendar)} days × {len(syms)} names", flush=True)

    books = [PRIMARY, CHECK]
    all_payloads: dict[str, list[dict[str, Any]]] = {}
    for spec in books:
        label = spec["label"]
        print(f"[spx-tl] book {label} ...", flush=True)
        rows = []
        for arm in ARMS:
            allow_empty = arm["id"] != "control"
            fn = None if arm["id"] == "control" else make_filter(arm["id"], trend, syms, calendar)
            print(f"  arm {arm['id']}", flush=True)
            r = run_one_backtest(
                X=int(spec["X"]),
                N=int(spec["N"]),
                cost_bps=COST_BPS,
                opens=opens,
                closes=closes,
                mcap_now=mcap,
                capital0=INITIAL_CAPITAL,
                collect_extras=True,
                filter_members=fn,
                allow_empty=allow_empty,
            )
            if not r.ok:
                print(f"  FAIL {arm['id']}: {r.error}", flush=True)
            rows.append(result_payload(r, arm["id"], label))
        all_payloads[label] = rows
        eq_dir = STAMP / f"equity_{label}"
        eq_dir.mkdir(exist_ok=True)
        for row in rows:
            pd.DataFrame([{"date": d, "equity": v} for d, v in row["equity"]]).to_csv(
                eq_dir / f"{row['arm']}.csv", index=False
            )

    primary_rows = all_payloads["X5_D126"]
    check_rows = all_payloads["X10_D21"]
    verdicts: dict[str, tuple[str, str]] = {}
    for label, rows in (("X5_D126", primary_rows), ("X10_D21", check_rows)):
        ctrl = next(r for r in rows if r["arm"] == "control")
        for r in rows:
            verdicts[f"{label}:{r['arm']}"] = judge_book(ctrl, r)

    overall, overall_why = overall_verdict(verdicts, primary_rows)

    charts_info: dict[str, Any] = {"skipped": True}
    if not args.skip_charts:
        print("[spx-tl] ensure_charts...", flush=True)
        charts_info = maybe_charts(names)

    write_baseline(
        STAMP / "BASELINE.md",
        names=names,
        notes=diag["notes"],
        verdicts=verdicts,
        primary_rows=primary_rows,
        check_rows=check_rows,
        overall=overall,
        overall_why=overall_why,
    )
    write_html(
        STAMP / "compare.html",
        names=names,
        diag=diag,
        verdicts=verdicts,
        primary_rows=primary_rows,
        check_rows=check_rows,
        overall=overall,
        overall_why=overall_why,
        charts_info=charts_info,
    )

    slim = []
    for label, rows in (("X5_D126", primary_rows), ("X10_D21", check_rows)):
        for r in rows:
            v, why = verdicts[f"{label}:{r['arm']}"]
            slim.append(
                {
                    "book": label,
                    "arm": r["arm"],
                    "verdict": v,
                    "why": why,
                    "avg_held": r.get("avg_held"),
                    "min_held": r.get("min_held"),
                    "is_cagr": r["slices"]["IS"].get("cagr"),
                    "is_maxdd": r["slices"]["IS"].get("max_dd"),
                    "is_sharpe": r["slices"]["IS"].get("sharpe"),
                    "oos_cagr": r["slices"]["OOS"].get("cagr"),
                    "oos_maxdd": r["slices"]["OOS"].get("max_dd"),
                    "oos_sharpe": r["slices"]["OOS"].get("sharpe"),
                    "full_cagr": r["slices"]["FULL"].get("cagr"),
                    "full_maxdd": r["slices"]["FULL"].get("max_dd"),
                    "full_sharpe": r["slices"]["FULL"].get("sharpe"),
                    "full_final": r.get("final_equity"),
                }
            )
    write_csv(STAMP / "compare.csv", slim)
    summary = {
        "stamp": "spx_trend_ab_20260916",
        "overall": overall,
        "overall_why": overall_why,
        "names": names,
        "notes": diag["notes"],
        "verdicts": {k: {"verdict": v, "why": w} for k, (v, w) in verdicts.items()},
        "elapsed_sec": time.time() - t0,
        "charts": {k: charts_info.get(k) for k in ("built", "already_ok", "failed", "error", "skipped")},
    }
    (STAMP / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"[spx-tl] done {overall} in {time.time() - t0:.1f}s -> {STAMP}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
