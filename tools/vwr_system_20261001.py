#!/usr/bin/env python3
"""Volume Washout Reclaim (VWR) research page.

Freezes the right-side arm from lance_rsv_washout_ab_20261001.
Does not overwrite that folder. Research only. Not gold. Not DailyRun.

  python tools/vwr_system_20261001.py
"""
from __future__ import annotations

import html as html_mod
import importlib.util
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))
sys.path.insert(0, str(REPO / "tools"))

import compare_format as cf  # noqa: E402
from be_stop_replay_ab import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    sortable_th,
)

_spec = importlib.util.spec_from_file_location(
    "lance_rsv_washout",
    REPO / "tools" / "lance_rsv_washout_ab_20261001.py",
)
lance = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(lance)

STAMP = "vwr_system_20261001"
OUT = REPO / "drive" / "paul_experiments" / STAMP
DRIVE = REPO / "drive"
SOURCE = REPO / "drive" / "paul_experiments" / "lance_rsv_washout_ab_20261001"
IS_CUT = pd.Timestamp("2024-01-01")

ORIGINAL_REQUEST = (
    "let's turn this into a system. what's a good name? i like using acronyms. "
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "lance_rsv_washout_ab_20261001/compare.html "
    "I want to see all the trades and a summary/comparison to other systems like VZ, RL, etc. "
    "then run post analysis and AB tests and publish results please"
)

HOUSE = [
    ("VZ", "Volume Zone", "Volume zone, then a retest entry. Live sleeve."),
    ("RL", "Rocket Launcher", "Dip toward a moving average after a run-up. Live sleeve."),
    ("BRT", "Break and ReTest", "Break a level, then buy the retest. Live sleeve."),
    ("MTS", "Magic Touch", "First touch of a level on the Magic Touch tab. Live sleeve."),
    ("YH", "Year High", "Buy a pullback that is still near the yearly high. Live sleeve."),
    ("WPBR", "Pivot Break and Retest", "Weekly pivot break, then a daily retest. Live sleeve."),
    ("RS", "Relative Strength", "Strength versus the S&P 500 fund (SPY), with a trend gate. Live sleeve."),
    ("SB", "StockBee Momentum Burst", "Short burst after a tight coil. Live sleeve."),
    ("RSI", "Relative Strength Index", "Wilder 14-period heat gauge, bought after it cools. Live sleeve. Not the Relative Strength system."),
    ("WRL", "Weekly Range / Swing", "Weekly range and swing sleeve. Live sleeve."),
    ("IND", "Indicator / Trend Condition", "Legacy indicator path. Deprecated. Scored because a published book is on disk."),
]


def _esc(x: Any) -> str:
    return html_mod.escape("" if x is None else str(x))


def _num(v: Any) -> float:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return float("nan")
    return n if np.isfinite(n) else float("nan")


def _f(v: Any, d: int = 2) -> str:
    n = _num(v)
    if not np.isfinite(n):
        return "—"
    return f"{n:,.{d}f}"


def _fp(v: Any, d: int = 2) -> str:
    n = _num(v)
    if not np.isfinite(n):
        return "—"
    return f"{n:.{d}f}%"


def _px(v: Any) -> str:
    n = _num(v)
    if not np.isfinite(n):
        return "—"
    return f"{n:.4f}".rstrip("0").rstrip(".")


def _th_row(pairs: list[tuple[str, str]]) -> str:
    return "".join(sortable_th(label, kind) for label, kind in pairs)


def run_arm(
    raw: pd.DataFrame,
    bars: dict[str, pd.DataFrame],
    *,
    min_drop: float,
    hold_bars: int,
    target_r: float,
) -> list[dict[str, Any]]:
    sig = raw.loc[raw["ret5"] <= -min_drop].copy()
    lance.HOLD_BARS = hold_bars
    lance.TARGET_R = target_r
    lance.MIN_DROP = min_drop
    picks = lance.pick_signals(sig, bars)
    return lance.simulate(picks, bars, "right")


def restore_freeze() -> None:
    lance.HOLD_BARS = 10
    lance.TARGET_R = 1.0
    lance.MIN_DROP = 0.15


def packs(trades: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        "full": lance.summarize(trades),
        "is": lance.summarize(lance._slice(trades, "is")),
        "oos": lance.summarize(lance._slice(trades, "oos")),
    }


def trait_block(trades: list[dict[str, Any]], label: str) -> dict[str, Any]:
    if not trades:
        return {"label": label, "n": 0}
    pnl = np.array([t["pnl"] for t in trades], dtype=float)
    cut = float(np.quantile(pnl, 0.90))
    top = [t for t in trades if t["pnl"] >= cut]
    rest = [t for t in trades if t["pnl"] < cut]
    if len(top) < 5:
        top = sorted(trades, key=lambda t: -t["pnl"])[: max(5, len(trades) // 10)]
        top_ids = {id(t) for t in top}
        rest = [t for t in trades if id(t) not in top_ids]

    def med(rows: list[dict[str, Any]], key: str) -> float:
        if not rows:
            return float("nan")
        return float(np.median([t[key] for t in rows]))

    def share(rows: list[dict[str, Any]], reasons: set[str]) -> float:
        if not rows:
            return float("nan")
        return 100.0 * sum(1 for t in rows if t["exit_reason"] in reasons) / len(rows)

    def risk_pct(t: dict[str, Any]) -> float:
        entry = float(t["entry"])
        if entry <= 0:
            return float("nan")
        return (entry - float(t["stop"])) / entry * 100.0

    def med_risk(rows: list[dict[str, Any]]) -> float:
        vals = [risk_pct(t) for t in rows]
        vals = [v for v in vals if np.isfinite(v)]
        return float(np.median(vals)) if vals else float("nan")

    return {
        "label": label,
        "n": len(trades),
        "cut": cut,
        "top_n": len(top),
        "rest_n": len(rest),
        "top_pnl": med(top, "pnl"),
        "rest_pnl": med(rest, "pnl"),
        "top_ret5": med(top, "ret5"),
        "rest_ret5": med(rest, "ret5"),
        "top_excess": med(top, "excess"),
        "rest_excess": med(rest, "excess"),
        "top_vol": med(top, "vol_ratio"),
        "rest_vol": med(rest, "vol_ratio"),
        "top_risk": med_risk(top),
        "rest_risk": med_risk(rest),
        "top_days": med(top, "days"),
        "rest_days": med(rest, "days"),
        "top_target": share(top, {"TARGET", "GAP_TARGET"}),
        "rest_target": share(rest, {"TARGET", "GAP_TARGET"}),
        "top_stop": share(top, {"STOP", "GAP_STOP"}),
        "rest_stop": share(rest, {"STOP", "GAP_STOP"}),
        "top_time": share(top, {"TIME"}),
        "rest_time": share(rest, {"TIME"}),
        "top_gap_target": share(top, {"GAP_TARGET"}),
        "rest_gap_target": share(rest, {"GAP_TARGET"}),
    }


def winner_prose(full: dict[str, Any], ins: dict[str, Any]) -> tuple[str, bool]:
    """Return prose and whether the tighter-drop arm was inspired by in-sample winners."""
    deeper = (
        np.isfinite(ins.get("top_ret5", np.nan))
        and np.isfinite(ins.get("rest_ret5", np.nan))
        and ins["top_ret5"] <= ins["rest_ret5"] - 0.03
    )
    wider = (
        np.isfinite(full.get("top_risk", np.nan))
        and np.isfinite(full.get("rest_risk", np.nan))
        and full["top_risk"] >= full["rest_risk"] * 1.25
    )
    same_drop = (
        np.isfinite(full.get("top_ret5", np.nan))
        and np.isfinite(full.get("rest_ret5", np.nan))
        and abs(full["top_ret5"] - full["rest_ret5"]) < 0.03
    )
    bits = [
        "The top of the return distribution is the best 10% of closed trades by percent gain. "
        "This is a description of those trades. It is not a new entry rule.",
        (
            f"On the full book the cutoff for that top slice is {_fp(full.get('cut'))} "
            f"({full.get('top_n', 0)} trades). Their median gain is {_fp(full.get('top_pnl'))}. "
            f"The other trades have a median of {_fp(full.get('rest_pnl'))}."
        ),
    ]
    if wider:
        bits.append(
            f"What they share is a wide climax bar. The top slice's median risk "
            f"(entry minus the washout low, divided by entry) is {_fp(full.get('top_risk'))}, "
            f"against {_fp(full.get('rest_risk'))} on the rest of the book. "
            "The frozen exit sells at a gain equal to that risk (1R), so a wide washout that then "
            "reclaims and hits the target prints a large percent even though it did not run for weeks. "
            f"{_fp(full.get('top_target'), 0)} of the top slice exited at the target "
            f"(including gaps through it). The rest of the book hit the target {_fp(full.get('rest_target'), 0)} of the time."
        )
    else:
        bits.append(
            f"The top slice exits at the target {_fp(full.get('top_target'), 0)} of the time "
            f"(the rest of the book: {_fp(full.get('rest_target'), 0)}). "
            f"Median risk is {_fp(full.get('top_risk'))} in the top slice and {_fp(full.get('rest_risk'))} on the rest."
        )
    if same_drop:
        bits.append(
            f"They do not share a deeper five-day drop. Median five-day return is "
            f"{_fp(full.get('top_ret5') * 100)} in the top slice and {_fp(full.get('rest_ret5') * 100)} on the rest. "
            f"Median excess versus QQQ is "
            f"{full.get('top_excess') * 100:.1f} percentage points versus {full.get('rest_excess') * 100:.1f} percentage points. "
            f"Median volume versus the prior 20 sessions is {_f(full.get('top_vol'))} times versus {_f(full.get('rest_vol'))} times."
        )
    else:
        bits.append(
            "They also fell harder than the other trades before the signal. "
            f"Median five-day return is {_fp(full.get('top_ret5') * 100)} in the top slice and "
            f"{_fp(full.get('rest_ret5') * 100)} on the rest. "
            f"Median excess versus QQQ is {full.get('top_excess') * 100:.1f} percentage points versus "
            f"{full.get('rest_excess') * 100:.1f} percentage points. "
            f"Median volume ratio is {_f(full.get('top_vol'))} versus {_f(full.get('rest_vol'))}. "
            "Volume was not hotter in the top slice."
        )
    bits.append(
        f"They are not longer holds. Median calendar days is {_f(full.get('top_days'), 1)} "
        f"in the top slice and {_f(full.get('rest_days'), 1)} on the rest. "
        f"Time exits are {_fp(full.get('top_time'), 0)} of the top slice and {_fp(full.get('rest_time'), 0)} of the rest. "
        f"Stops are {_fp(full.get('top_stop'), 0)} of the top slice."
    )
    bits.append(
        f"The same cut on entries before 2024 (in-sample only, so the later years do not pick the story) "
        f"has median five-day return {_fp(ins.get('top_ret5') * 100)} in the top slice and "
        f"{_fp(ins.get('rest_ret5') * 100)} on the rest, and median risk {_fp(ins.get('top_risk'))} versus "
        f"{_fp(ins.get('rest_risk'))}."
    )
    return " ".join(bits), deeper


def judge(base_is: dict[str, Any], arm_is: dict[str, Any], arm_oos: dict[str, Any]) -> tuple[str, str]:
    if int(arm_is.get("n") or 0) < 30 or int(base_is.get("n") or 0) < 30:
        return "HOLD", "Too few in-sample trades to judge quality."
    n_ratio = arm_is["n"] / base_is["n"]
    d_avg = arm_is["avg_pnl"] - base_is["avg_pnl"]
    d_wr = arm_is["win_pct"] - base_is["win_pct"]
    d_r = arm_is["avg_r"] - base_is["avg_r"]
    base_ror = _num(base_is.get("ann_ror"))
    arm_ror = _num(arm_is.get("ann_ror"))
    d_ror = arm_ror - base_ror if np.isfinite(arm_ror) and np.isfinite(base_ror) else float("nan")
    base_dd = _num(base_is.get("max_dd"))
    arm_dd = _num(arm_is.get("max_dd"))
    d_dd = arm_dd - base_dd if np.isfinite(arm_dd) and np.isfinite(base_dd) else float("nan")
    collapsed = n_ratio < 0.50
    ror_ok = (not np.isfinite(d_ror)) or d_ror > -2.0
    dd_ok = (not np.isfinite(d_dd)) or d_dd < 2.0
    better = d_avg > 0.10 and (d_wr > 2.0 or d_r > 0.05) and ror_ok and dd_ok
    worse = d_avg < -0.10 and (d_r < -0.02 or (np.isfinite(d_ror) and d_ror < -2.0))
    oos_n = int(arm_oos.get("n") or 0)
    oos_soft = False
    if oos_n > 30 and arm_is["avg_pnl"] > 0 and arm_oos["avg_pnl"] < arm_is["avg_pnl"] - 0.25:
        oos_soft = True
    oos_ror = _num(arm_oos.get("ann_ror"))
    if oos_n > 30 and np.isfinite(arm_ror) and arm_ror > 0 and np.isfinite(oos_ror) and oos_ror < arm_ror - 5:
        oos_soft = True
    soft_txt = ""
    if oos_n > 30:
        soft_txt = (
            f" Out-of-sample average is {_fp(arm_oos.get('avg_pnl'))} "
            f"and annualized rate of return is {_fp(arm_oos.get('ann_ror'))} "
            f"on {oos_n} trades (report only)."
        )
    if worse and not better:
        return "DISMISS", (
            f"In-sample average changed by {d_avg:+.2f} percentage points, "
            f"win rate by {d_wr:+.1f} percentage points, average R by {d_r:+.2f}, "
            f"and annualized rate of return by {d_ror:+.1f} percentage points, "
            f"with {arm_is['n'] - base_is['n']:+d} trades. Quality got worse."
            + soft_txt
        )
    if better and collapsed:
        return "HOLD", (
            f"In-sample quality improved (average {d_avg:+.2f} percentage points, "
            f"win rate {d_wr:+.1f} percentage points) but trades fell from {base_is['n']} to {arm_is['n']}. "
            "That is a hold, not a keep."
            + soft_txt
        )
    if better and oos_soft:
        return "HOLD", (
            f"In-sample quality improved (average {d_avg:+.2f} percentage points, "
            f"win rate {d_wr:+.1f} percentage points, annualized rate of return {d_ror:+.1f} percentage points). "
            "Out-of-sample is softer than that arm's own earlier period. Hold. Do not retune."
        )
    if better:
        return "KEEP", (
            f"In-sample quality improved (average {d_avg:+.2f} percentage points, "
            f"win rate {d_wr:+.1f} percentage points, annualized rate of return {d_ror:+.1f} percentage points) "
            f"and trades stayed at {arm_is['n']} versus {base_is['n']}. "
            "Research lean only. The freeze on this page does not change."
            + soft_txt
        )
    return "HOLD", (
        f"In-sample average changed by {d_avg:+.2f} percentage points, "
        f"win rate by {d_wr:+.1f} percentage points, and annualized rate of return by {d_ror:+.1f} percentage points, "
        f"with {arm_is['n'] - base_is['n']:+d} trades. Quality did not clearly improve."
        + soft_txt
    )


def _report_value(row: pd.Series, *names: str) -> float:
    upper = {str(c).upper(): c for c in row.index}
    for name in names:
        col = upper.get(name.upper())
        if col is None:
            continue
        return _num(row[col])
    return float("nan")


def _latest_report(prefix: str) -> Path | None:
    hits = list(DRIVE.glob(f"{prefix}_Report_*.csv"))
    if not hits:
        return None
    return max(hits, key=lambda p: p.stem.split("_")[-1])


def _stamp_from_report(path: Path) -> str:
    return path.stem.split("_")[-1]


def _closed_for(prefix: str, stamp: str) -> Path | None:
    stamped = DRIVE / f"{prefix}_Closed_{stamp}.csv"
    if stamped.is_file():
        return stamped
    latest = DRIVE / f"{prefix}_LatestRun_Closed.csv"
    if prefix == "WPBR" and not latest.is_file():
        latest = DRIVE / "PBR_LatestRun_Closed.csv"
    return latest if latest.is_file() else None


def _closed_span_and_exits(path: Path) -> dict[str, Any]:
    header = pd.read_csv(path, nrows=0)
    cols = {c.upper(): c for c in header.columns}
    opened = cols.get("DATE_OPENED") or cols.get("OPENED")
    exit_c = cols.get("EXIT_TYPE") or cols.get("EXIT_REASON")
    use = [c for c in (opened, exit_c) if c]
    if not use:
        return {}
    df = pd.read_csv(path, usecols=use, dtype=str, low_memory=False)
    out: dict[str, Any] = {"closed_file": path.name, "n_closed_file": int(len(df))}
    if opened:
        dates = pd.to_datetime(df[opened], errors="coerce")
        dates = dates.dropna()
        if len(dates):
            span = max((dates.max() - dates.min()).days / 365.25, 1 / 365.25)
            out["first_entry"] = dates.min().date().isoformat()
            out["last_entry"] = dates.max().date().isoformat()
            out["span_years"] = float(span)
            out["trades_per_year"] = float(len(dates) / span)
    if exit_c:
        counts = Counter(str(x).strip() for x in df[exit_c].fillna("") if str(x).strip())
        out["exits"] = dict(counts)
    return out


def load_house() -> list[dict[str, Any]]:
    rows = []
    for code, expansion, blurb in HOUSE:
        report = _latest_report(code)
        if report is None:
            continue
        frame = pd.read_csv(report, nrows=1)
        if frame.empty:
            continue
        row = frame.iloc[0]
        stamp = _stamp_from_report(report)
        n = _report_value(row, "Total_Trades")
        book = {
            "code": code,
            "expansion": expansion,
            "blurb": blurb,
            "report": report.name,
            "stamp": stamp,
            "n": n,
            "wins": _report_value(row, "Wins"),
            "losses": _report_value(row, "Losses"),
            "win_pct": _report_value(row, "Pct_Wins"),
            "avg_pnl": _report_value(row, "Avg_PNL_Pct"),
            "avg_win": _report_value(row, "Avg_Win_Pct"),
            "avg_loss": _report_value(row, "Avg_Loss_Pct"),
            "pf": _report_value(row, "Profit_Factor"),
            "ann_ror": _report_value(row, "Ann_ROR"),
            "max_dd": _report_value(row, "Max_DD"),
            "calmar": _report_value(row, "Calmar"),
            "sharpe": _report_value(row, "Sharpe"),
            "avg_days": _report_value(row, "Avg_Days_Held"),
            "median_days": _report_value(row, "Median_Days_Held"),
            "p90_days": _report_value(row, "P90_Days"),
            "capital_days": _report_value(row, "Capital_Days"),
            "expect_pct": _report_value(row, "Expectancy_Pct"),
            "trades_per_year": float("nan"),
            "first_entry": "",
            "last_entry": "",
            "span_years": float("nan"),
            "closed_file": "",
            "exits": {},
        }
        closed = _closed_for(code, stamp)
        if closed is not None:
            extra = _closed_span_and_exits(closed)
            if extra.get("trades_per_year") and (not np.isfinite(n) or abs(extra.get("n_closed_file", 0) - n) > max(5, 0.02 * n)):
                book["span_note"] = (
                    f"Closed file {extra.get('closed_file')} has {extra.get('n_closed_file')} rows; "
                    f"the report row has {n:.0f} trades. Trades/year uses the closed file and may not match the report."
                )
            else:
                book["span_note"] = ""
            book.update({k: extra[k] for k in ("trades_per_year", "first_entry", "last_entry", "span_years", "closed_file", "exits") if k in extra})
        rows.append(book)
        print(f"[vwr] house {code} n={n} ann={book['ann_ror']}", flush=True)
    return rows


def exit_mix_table(vwr_full: dict[str, Any], house: list[dict[str, Any]]) -> str:
    keys = ["TARGET", "STOP_LOSS", "STOP", "GAP_UP", "GAP_DOWN", "GAP_TARGET", "GAP_STOP", "TIME"]
    head = _th_row([("System", "text"), ("File", "text")] + [(k, "num") for k in keys])
    body = []

    def cells(n: float, exits: dict[str, Any]) -> str:
        out = []
        for k in keys:
            c = int(exits.get(k, 0) or 0)
            if c == 0:
                out.append("<td>—</td>")
            else:
                pct = 100.0 * c / n if n else float("nan")
                out.append(f"<td>{c} ({_fp(pct, 0)})</td>")
        return "".join(out)

    n = float(vwr_full.get("n") or 0)
    body.append(f"<tr><td>VWR</td><td>this page</td>{cells(n, vwr_full.get('exits') or {})}</tr>")
    for h in house:
        exits = h.get("exits") or {}
        if not exits:
            continue
        nn = float(sum(int(v) for v in exits.values()))
        body.append(f"<tr><td>{_esc(h['code'])}</td><td>{_esc(h.get('closed_file') or '')}</td>{cells(nn, exits)}</tr>")
    return (
        '<table class="sortable"><caption>Exit counts and share of that book. Click column headers to sort. '
        "Blank means that exit name was not in the file. Names differ by system, so a column is not one shared exit.</caption>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"
    )


def metric_table(title: str, books: list[tuple[str, dict[str, Any]]]) -> str:
    head = _th_row(
        [("Slice", "text")]
        + [
            (label, kind)
            for label, kind in (
                ("Trades", "num"),
                ("Win %", "num"),
                ("Avg %", "num"),
                ("Median %", "num"),
                ("Avg without largest win %", "num"),
                ("Profit factor", "num"),
                ("Ann ROR %", "num"),
                ("Max DD %", "num"),
                ("Calmar", "num"),
                ("Sharpe", "num"),
                ("Avg days", "num"),
                ("Median days", "num"),
                ("Trades / year", "num"),
                ("Avg R", "num"),
                ("Expectancy $", "num"),
            )
        ]
    )
    body = []
    for label, s in books:
        body.append(
            "<tr>"
            f"<td>{_esc(label)}</td>"
            f"<td>{_f(s.get('n'), 0)}</td>"
            f"<td>{_fp(s.get('win_pct'))}</td>"
            f"<td>{_fp(s.get('avg_pnl'))}</td>"
            f"<td>{_fp(s.get('median_pnl'))}</td>"
            f"<td>{_fp(s.get('avg_wo'))}</td>"
            f"<td>{_f(s.get('pf'))}</td>"
            f"<td>{_fp(s.get('ann_ror'))}</td>"
            f"<td>{_fp(s.get('max_dd'))}</td>"
            f"<td>{_f(s.get('calmar'))}</td>"
            f"<td>{_f(s.get('sharpe'))}</td>"
            f"<td>{_f(s.get('avg_days'))}</td>"
            f"<td>{_f(s.get('median_days'))}</td>"
            f"<td>{_f(s.get('trades_per_year'))}</td>"
            f"<td>{_f(s.get('avg_r'))}</td>"
            f"<td>{_esc(cf.format_money(s.get('expect_d')))}</td>"
            "</tr>"
        )
    exits = books[0][1].get("exits") or {}
    n = max(int(books[0][1].get("n") or 0), 1)
    mix = ", ".join(
        f"{k} {int(exits.get(k, 0))} ({100.0 * int(exits.get(k, 0)) / n:.0f}%)"
        for k in ("STOP", "GAP_STOP", "TARGET", "GAP_TARGET", "TIME")
    )
    return (
        f"<h3>{_esc(title)}</h3>"
        '<table class="sortable"><caption>Click column headers to sort. '
        "Annualized rate of return (Ann ROR) replays a fixed $10,000 sheet on a $500,000 account, "
        "the same closed-trade formula the washout page used. "
        f"Full-book exit mix: {_esc(mix)}.</caption>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"
    )


def side_table(vwr: dict[str, Any], house: list[dict[str, Any]]) -> str:
    head = _th_row(
        [
            ("System", "text"),
            ("Trades", "num"),
            ("Win %", "num"),
            ("Avg %", "num"),
            ("Profit factor", "num"),
            ("Ann ROR %", "num"),
            ("Max DD %", "num"),
            ("Calmar", "num"),
            ("Sharpe", "num"),
            ("Avg days", "num"),
            ("Trades / year", "num"),
            ("First entry", "date"),
            ("Last entry", "date"),
            ("Source", "text"),
        ]
    )
    rows = [
        (
            "VWR Volume Washout Reclaim",
            vwr,
            "2010-02-09",
            "",
            "this page, right-side freeze",
        )
    ]
    # first/last filled below for VWR by caller via vwr keys if present
    body = []
    vwr_row = {
        "n": vwr.get("n"),
        "win_pct": vwr.get("win_pct"),
        "avg_pnl": vwr.get("avg_pnl"),
        "pf": vwr.get("pf"),
        "ann_ror": vwr.get("ann_ror"),
        "max_dd": vwr.get("max_dd"),
        "calmar": vwr.get("calmar"),
        "sharpe": vwr.get("sharpe"),
        "avg_days": vwr.get("avg_days"),
        "trades_per_year": vwr.get("trades_per_year"),
    }
    body.append(_side_tr("VWR — Volume Washout Reclaim", vwr_row, vwr.get("first_entry", ""), vwr.get("last_entry", ""), "this freeze"))
    for h in house:
        body.append(
            _side_tr(
                f"{h['code']} — {h['expansion']}",
                h,
                h.get("first_entry") or "",
                h.get("last_entry") or "",
                h.get("report") or "",
            )
        )
    _ = rows
    return (
        '<table class="sortable"><caption>Click column headers to sort. '
        "Side-by-side published books. Universe, years, size, and exit are not matched. "
        "House annualized rate of return is the number in that system's report file. "
        "Volume Washout Reclaim uses the $10,000 sheet formula above. "
        "A higher cell is not a reason to call this system gold.</caption>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"
    )


def _side_tr(name: str, s: dict[str, Any], first: str, last: str, source: str) -> str:
    return (
        "<tr>"
        f"<td>{_esc(name)}</td>"
        f"<td>{_f(s.get('n'), 0)}</td>"
        f"<td>{_fp(s.get('win_pct'))}</td>"
        f"<td>{_fp(s.get('avg_pnl'))}</td>"
        f"<td>{_f(s.get('pf'))}</td>"
        f"<td>{_fp(s.get('ann_ror'))}</td>"
        f"<td>{_fp(s.get('max_dd'))}</td>"
        f"<td>{_f(s.get('calmar'))}</td>"
        f"<td>{_f(s.get('sharpe'))}</td>"
        f"<td>{_f(s.get('avg_days'))}</td>"
        f"<td>{_f(s.get('trades_per_year'))}</td>"
        f"<td>{_esc(first or '—')}</td>"
        f"<td>{_esc(last or '—')}</td>"
        f"<td>{_esc(source)}</td>"
        "</tr>"
    )


def trades_table(trades: list[dict[str, Any]]) -> str:
    head = _th_row(
        [
            ("Symbol", "text"),
            ("Signal date", "date"),
            ("Entry date", "date"),
            ("Exit date", "date"),
            ("Entry", "num"),
            ("Exit", "num"),
            ("Stop", "num"),
            ("Target", "num"),
            ("Return %", "num"),
            ("R", "num"),
            ("Days", "num"),
            ("Sessions", "num"),
            ("Exit reason", "text"),
            ("5-day return %", "num"),
            ("Excess vs QQQ pp", "num"),
            ("Volume ratio", "num"),
        ]
    )
    rows = []
    for t in trades:
        rows.append(
            "<tr>"
            f"<td>{_esc(t['symbol'])}</td>"
            f"<td>{_esc(t['signal_date'])}</td>"
            f"<td>{_esc(t['opened'])}</td>"
            f"<td>{_esc(t['closed'])}</td>"
            f"<td>{_px(t['entry'])}</td>"
            f"<td>{_px(t['exit'])}</td>"
            f"<td>{_px(t['stop'])}</td>"
            f"<td>{_px(t['target'])}</td>"
            f"<td>{_fp(t['pnl'])}</td>"
            f"<td>{_f(t['r'])}</td>"
            f"<td>{int(t['days'])}</td>"
            f"<td>{int(t['sessions'])}</td>"
            f"<td>{_esc(t['exit_reason'])}</td>"
            f"<td>{_fp(float(t['ret5']) * 100)}</td>"
            f"<td>{_fp(float(t['excess']) * 100)}</td>"
            f"<td>{_f(t['vol_ratio'])}</td>"
            "</tr>"
        )
    return (
        '<div class="scroll"><table class="sortable"><caption>'
        f"All {len(trades)} closed trades. Click column headers to sort.</caption>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def trait_table(full: dict[str, Any], ins: dict[str, Any]) -> str:
    head = _th_row(
        [
            ("Slice", "text"),
            ("Trades", "num"),
            ("Median return %", "num"),
            ("Median 5-day return %", "num"),
            ("Median excess vs QQQ pp", "num"),
            ("Median volume ratio", "num"),
            ("Median risk % of entry", "num"),
            ("Median days", "num"),
            ("Target %", "num"),
            ("Stop %", "num"),
            ("Time %", "num"),
        ]
    )
    body = []
    for prefix, block in (("Full book top 10%", full), ("Full book rest", full), ("In-sample top 10%", ins), ("In-sample rest", ins)):
        which = "top" if "top" in prefix else "rest"
        n_key = "top_n" if which == "top" else "rest_n"
        body.append(
            "<tr>"
            f"<td>{prefix}</td>"
            f"<td>{block.get(n_key, 0)}</td>"
            f"<td>{_fp(block.get(which + '_pnl'))}</td>"
            f"<td>{_fp(_num(block.get(which + '_ret5')) * 100)}</td>"
            f"<td>{_f(_num(block.get(which + '_excess')) * 100)}</td>"
            f"<td>{_f(block.get(which + '_vol'))}</td>"
            f"<td>{_fp(block.get(which + '_risk'))}</td>"
            f"<td>{_f(block.get(which + '_days'), 1)}</td>"
            f"<td>{_fp(block.get(which + '_target'), 0)}</td>"
            f"<td>{_fp(block.get(which + '_stop'), 0)}</td>"
            f"<td>{_fp(block.get(which + '_time'), 0)}</td>"
            "</tr>"
        )
    return (
        '<table class="sortable"><caption>What the top of the return distribution looks like next to the other trades. '
        "Click column headers to sort. Description only.</caption>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"
    )


def ab_table(base: dict[str, dict[str, Any]], arms: list[dict[str, Any]]) -> str:
    head = _th_row(
        [
            ("Arm", "text"),
            ("Kind", "text"),
            ("Slice", "text"),
            ("Trades", "num"),
            ("Win %", "num"),
            ("Avg %", "num"),
            ("Ann ROR %", "num"),
            ("Max DD %", "num"),
            ("Verdict", "text"),
        ]
    )
    body = []
    for sl, nice in (("full", "Full"), ("is", "IS before 2024"), ("oos", "OOS from 2024")):
        s = base[sl]
        verd = "frozen" if sl == "is" else "context" if sl == "full" else "report only"
        body.append(
            "<tr>"
            "<td>Frozen VWR</td><td>FREEZE</td>"
            f"<td>{nice}</td><td>{_f(s.get('n'), 0)}</td><td>{_fp(s.get('win_pct'))}</td>"
            f"<td>{_fp(s.get('avg_pnl'))}</td><td>{_fp(s.get('ann_ror'))}</td>"
            f"<td>{_fp(s.get('max_dd'))}</td><td>{verd}</td></tr>"
        )
    for arm in arms:
        for sl, nice in (("full", "Full"), ("is", "IS before 2024"), ("oos", "OOS from 2024")):
            s = arm["packs"][sl]
            if sl == "is":
                verd = arm["verdict"]
            elif sl == "oos":
                verd = "report only"
            else:
                verd = "context"
            body.append(
                "<tr>"
                f"<td>{_esc(arm['name'])}</td><td>{_esc(arm['kind'])}</td>"
                f"<td>{nice}</td><td>{_f(s.get('n'), 0)}</td><td>{_fp(s.get('win_pct'))}</td>"
                f"<td>{_fp(s.get('avg_pnl'))}</td><td>{_fp(s.get('ann_ror'))}</td>"
                f"<td>{_fp(s.get('max_dd'))}</td><td>{_esc(verd)}</td></tr>"
            )
    return (
        '<table class="sortable"><caption>One knob at a time versus the frozen system. '
        "Click column headers to sort. Verdict uses in-sample quality only. "
        "Out-of-sample is report-only. If it is softer than that arm's own in-sample result, the verdict is HOLD.</caption>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"
    )


def system_blurb(house: list[dict[str, Any]]) -> str:
    bits = []
    for h in house:
        bits.append(f"{h['code']} is {h['expansion']}. {h['blurb']}")
    return " ".join(bits)


def sit_sentence(vwr: dict[str, Any], house: list[dict[str, Any]]) -> str:
    by = {h["code"]: h for h in house}
    vz = by.get("VZ", {})
    rl = by.get("RL", {})
    return (
        f"On its own $10,000 sheet, Volume Washout Reclaim has {_f(vwr.get('n'), 0)} trades, "
        f"a {_fp(vwr.get('win_pct'))} win rate, an average trade of {_fp(vwr.get('avg_pnl'))}, "
        f"and an annualized rate of return of {_fp(vwr.get('ann_ror'))}. "
        f"The published Volume Zone book shows {_fp(vz.get('ann_ror'))} annualized "
        f"on {_f(vz.get('n'), 0)} trades, and Rocket Launcher shows {_fp(rl.get('ann_ror'))} "
        f"on {_f(rl.get('n'), 0)} trades. Those books do not share a universe, a calendar, or an exit, "
        "so this page does not treat the gap as a win or a loss for Volume Washout Reclaim."
    )


def render(
    trades: list[dict[str, Any]],
    book: dict[str, dict[str, Any]],
    house: list[dict[str, Any]],
    prose: str,
    deeper: bool,
    full_traits: dict[str, Any],
    is_traits: dict[str, Any],
    arms: list[dict[str, Any]],
) -> str:
    vwr = book["full"]
    css = SORTABLE_TH_CSS + """
    body { font: 16px/1.45 Georgia, serif; margin: 2rem auto; max-width: 1180px; color: #1a1a1a; padding: 0 1rem; }
    h1 { font-size: 1.6rem; }
    .callout { background: #f6f3ea; border: 1px solid #e2d8c0; padding: 0.8rem 1rem; margin: 1rem 0; }
    .warn { background: #f8efe8; border: 1px solid #e2cbb8; padding: 0.8rem 1rem; margin: 1rem 0; }
    table { border-collapse: collapse; width: 100%; margin: 0.6rem 0 1.2rem; font-size: 0.88rem; }
    th, td { border-bottom: 1px solid #ddd; padding: 0.35rem 0.45rem; text-align: right; vertical-align: top; }
    th:first-child, td:first-child { text-align: left; }
    caption { text-align: left; font-size: 0.85rem; color: #444; margin-bottom: 0.3rem; caption-side: top; }
    .scroll { overflow-x: auto; }
    nav a { margin-right: 0.8rem; }
    code { font-size: 0.92em; }
    """
    arm_blocks = []
    for arm in arms:
        bias = ""
        if arm.get("selection_bias"):
            bias = (
                "<p><strong>Selection bias.</strong> "
                + _esc(arm["selection_bias"])
                + " Out-of-sample was not used to choose this arm. The freeze stays the right-side rule above.</p>"
            )
        arm_blocks.append(
            f"<h3>{_esc(arm['name'])} <span>({_esc(arm['kind'])})</span></h3>"
            f"<p>{_esc(arm['what'])}</p>"
            f"<p><strong>{_esc(arm['verdict'])}.</strong> {_esc(arm['finding'])}</p>"
            f"{bias}"
        )
    first = min(t["opened"] for t in trades)
    last = max(t["opened"] for t in trades)
    vwr["first_entry"] = first
    vwr["last_entry"] = last
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Volume Washout Reclaim (VWR)</title>
<style>{css}</style></head><body>
<h1>Volume Washout Reclaim (VWR)</h1>
<p>Research only. Not gold. Not a live DailyRun system. Stamp <code>{STAMP}</code>.
Frozen from the right-side arm in <code>lance_rsv_washout_ab_20261001</code>. That folder is unchanged.</p>
<nav>
<a href="#asked">What you asked</a>
<a href="#rule">Frozen rule</a>
<a href="#trades">All trades</a>
<a href="#summary">Summary</a>
<a href="#books">Other systems</a>
<a href="#winners">Big winners</a>
<a href="#ab">A/B tests</a>
</nav>
<div class="callout" id="asked">
<h2>What you asked</h2>
<p>{_esc(ORIGINAL_REQUEST)}</p>
<h2>In plain English</h2>
<p>The idea is a washout that has already turned. Each day the book lists stocks that fell at least 15% in five sessions,
fell at least 8 percentage points harder than the Nasdaq-100 exchange-traded fund (QQQ), and traded at least twice their recent volume,
with at least $20 million of stock changing hands. It keeps the ten most extreme names.
It does not buy the next morning just because the stock fell. It buys the next session only if price trades back through the high of that washout day.
The fill is that high, or the open if the open is already above it. The stop is the low of the washout day.
The target is a gain equal to the risk, called 1R. If neither the stop nor the target has hit after ten sessions, counting the entry day, it sells at the close.
In-sample (IS) means the buy was before 2024. Out-of-sample (OOS) means the buy was in 2024 or later, and those results are a report only.</p>
<p>The other books on this page are already-published systems. Volume Zone (VZ) buys a retest of a heavy-volume price zone.
Rocket Launcher (RL) buys a dip toward a moving average after a stock has already run.
Break and ReTest (BRT) buys a retest after a level breaks. Magic Touch (MTS) buys a first touch of a level.
Year High (YH) buys a pullback that is still near the year's high.
Pivot Break and Retest (WPBR) uses a weekly pivot, then a daily retest.
Relative Strength (RS) buys strength versus the S&amp;P 500 fund (SPY).
StockBee Momentum Burst (SB) buys a short expansion after a tight coil.
Relative Strength Index (RSI) is Wilder's heat gauge, bought after a hot reading cools. It is not the Relative Strength system.
Weekly Range / Swing (WRL) is the weekly swing sleeve.
Indicator / Trend Condition (IND) is an older indicator path and is deprecated.
Annualized rate of return (Ann ROR) turns the average trade and the hold time into a yearly pace.
These books were not rebuilt for this page, and they were not traded on the same list of stocks.</p>
</div>
<div class="warn">
<p><strong>HOLD as a live rule.</strong> The source test already compared this entry with buying the next open.
Before 2024 the reclaim entry raised the win rate and the average R, and it also cut the trade count by more than half.
Average R was still about flat, and from 2024 on the book loses money in percent.
This page names that reclaim rule so it can be inspected. It does not promote it.</p>
</div>
<h2 id="rule">Frozen rule and the name</h2>
<p><strong>Volume Washout Reclaim (VWR).</strong>
The name fits because the rule waits for a high-volume washout, then buys only when price reclaims the high of that washout day.
The letters RSV from the source test (the relative-strength versus QQQ filter, plus volume) stay inside the rule. They are not the system code.
VWR is not Volume Zone, Rocket Launcher, Break and ReTest, Magic Touch, Year High, Pivot Break and Retest,
Relative Strength, StockBee, Indicator, Weekly Range / Swing, Relative Strength Index, or the engine name TBN.</p>
<table class="sortable"><caption>Frozen knobs. Click column headers to sort.</caption>
<thead><tr>{_th_row([("Knob", "text"), ("Value", "text")])}</tr></thead>
<tbody>
<tr><td>Name</td><td>Volume Washout Reclaim (VWR)</td></tr>
<tr><td>Universe</td><td>Daily warehouse prices joined to QQQ. QQQ itself is excluded.</td></tr>
<tr><td>Signal, known at the close</td><td>5-day return at or below −15%; excess versus QQQ at or below −8 percentage points; volume at least 2× the prior 20 sessions; close times volume at least $20,000,000; high above low.</td></tr>
<tr><td>Rank</td><td>10 most negative excess that day. One open window per symbol for 10 sessions after the entry bar.</td></tr>
<tr><td>Entry</td><td>Next session only if the high reaches the washout day's high. Fill at that high, or at the open if the open gaps through.</td></tr>
<tr><td>Stop</td><td>Washout-day low. Same bar: stop is checked before the target. A gap through the stop fills at the open.</td></tr>
<tr><td>Target</td><td>1R above the entry. A gap through the target fills at the open.</td></tr>
<tr><td>Time</td><td>Exit at the close of session 10, counting the entry session.</td></tr>
<tr><td>Size</td><td>$10,000 sheet per trade. Drawdown replay starts at $500,000.</td></tr>
<tr><td>IS / OOS</td><td>Entry before 2024-01-01 / on or after. Out-of-sample is report-only.</td></tr>
</tbody></table>
<h2 id="trades">All trades</h2>
{trades_table(trades)}
<h2 id="summary">Summary of Volume Washout Reclaim</h2>
<p>In-sample (IS) is an entry before 2024-01-01. Out-of-sample (OOS) is an entry on or after that date. OOS did not pick the rule.
Max drawdown (Max DD) is the deepest drop in the $500,000 replay. Sharpe uses exit dates, risk-free rate zero.</p>
{metric_table("Full book, in-sample, and out-of-sample", [("Full", book["full"]), ("IS before 2024", book["is"]), ("OOS from 2024", book["oos"])])}
<h2 id="books">Other published books</h2>
<p>{_esc(sit_sentence(vwr, house))}</p>
<p>{_esc(system_blurb(house))}</p>
{side_table(vwr, house)}
{exit_mix_table(book["full"], house)}
<h2 id="winners">Big winners</h2>
<p>{_esc(prose)}</p>
{trait_table(full_traits, is_traits)}
<h2 id="ab">One-knob tests versus the freeze</h2>
<p>Each arm changes one knob that already exists in the washout generator. The entry test on the source page
(buy the next open, versus wait for the washout high) is not repeated. Arms are not stacked.
ENTRY means the list of buys changes. EXIT means the same buys are closed differently, except the time arm,
which also lengthens how long a symbol stays locked after a signal, because that lock is the same ten-session window in the generator.
A skip-if-already-extended rule is not in the generator, so it is not tested here.</p>
{ab_table(book, arms)}
{''.join(arm_blocks)}
<p class="warn">No arm replaces the freeze. A KEEP on this page would still be an in-sample choice and would need its own stamp.
{"The tighter-washout arm was aimed at the in-sample winners, so treat it as selection bias even if the numbers look neat." if deeper else "The in-sample top slice was not a clearly deeper five-day drop than the rest, so the tighter 25% arm is the page's suggested washout test, not a filter copied from the winners."}</p>
<footer><p>Generator <code>tools/vwr_system_20261001.py</code>. Source page <code>drive/paul_experiments/lance_rsv_washout_ab_20261001/compare.html</code>.</p></footer>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""


def write_trades(path: Path, trades: list[dict[str, Any]]) -> None:
    cols = [
        "symbol", "signal_date", "opened", "closed", "entry", "exit", "stop", "target",
        "pnl", "r", "days", "sessions", "exit_reason", "ret5", "excess", "vol_ratio",
    ]
    pd.DataFrame(trades)[cols].rename(columns={"opened": "entry_date", "closed": "exit_date", "pnl": "return_pct"}).to_csv(path, index=False)


def write_baseline(
    book: dict[str, dict[str, Any]],
    arms: list[dict[str, Any]],
    deeper: bool,
) -> None:
    def line(s: dict[str, Any]) -> str:
        return (
            f"N {int(s.get('n') or 0)}, win rate {_fp(s.get('win_pct'))}, "
            f"avg {_fp(s.get('avg_pnl'))}, median {_fp(s.get('median_pnl'))}, "
            f"profit factor {_f(s.get('pf'))}, max DD {_fp(s.get('max_dd'))}, "
            f"Ann ROR {_fp(s.get('ann_ror'))}, avg days {_f(s.get('avg_days'))}, "
            f"trades/year {_f(s.get('trades_per_year'))}"
        )

    arm_lines = []
    for arm in arms:
        arm_lines.append(
            f"- **{arm['kind']} {arm['name']} — {arm['verdict']}.** {arm['finding']}"
            + (f" Selection bias: {arm['selection_bias']}" if arm.get("selection_bias") else "")
        )
    text = f"""# Volume Washout Reclaim (VWR)

Research only. Not gold. Not DailyRun.

## Name

Volume Washout Reclaim (VWR). The name fits because the rule waits for a high-volume washout, then buys only when price reclaims the high of that washout day. RSV from the source test stays inside the relative-strength and volume filters. It is not the system code.

## What you asked

{ORIGINAL_REQUEST}

## In plain English

Buy the reclaim of a washout day's high, stop at that day's low, take profit at 1R, and sell at the close if neither has happened after ten sessions. Compare the book with already-published systems. Do not treat a higher cell than Volume Zone (VZ) or Rocket Launcher (RL) as a matched win.

## Freeze

The source page `lance_rsv_washout_ab_20261001` tested buy-the-next-open against the reclaim of the washout high. Its verdict was HOLD. This stamp freezes the reclaim arm (the quality winner on that page) as the research system. It does not promote it.

| Knob | Value |
|---|---|
| Universe | Daily warehouse `data/ohlcv.duckdb` `prices`, joined to QQQ. QQQ excluded. |
| Signal | 5-day return ≤ −15%; excess vs QQQ ≤ −8 percentage points; volume ≥ 2× prior 20 sessions; close×volume ≥ $20,000,000; high > low. |
| Rank | 10 most negative excess that day. One window per symbol for 10 sessions after the entry bar. |
| Entry | Next session only if high ≥ washout high. Fill at the high, or at the open if the open gaps through. |
| Stop | Washout low. Stop checked before target on the same bar. Gap through the stop fills at the open. |
| Exit | 1R target, else close of session 10. Gap through the target fills at the open. |
| Size | $10,000 sheet. Drawdown replay starts at $500,000. |
| IS / OOS | Entry before 2024-01-01 / on or after. OOS is report-only. Knobs were not picked from OOS. |

## Book

- Full: {line(book["full"])}
- IS: {line(book["is"])}
- OOS: {line(book["oos"])}

## A/B

One knob at a time. Same warehouse. Freeze unchanged even if an arm says KEEP.

{chr(10).join(arm_lines)}

Tighter washout was inspired by in-sample winners: {"yes" if deeper else "no"}.

## Not this

Not gold. Not DailyRun. Not wired to getTarget or the monthly report.
"""
    (OUT / "BASELINE.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    restore_freeze()
    print("[vwr] scanning signals", flush=True)
    con = __import__("duckdb").connect(str(lance.DB), read_only=True)
    try:
        raw = lance.load_signals(con)
        print(f"[vwr] raw signals {len(raw)}", flush=True)
        symbols = sorted(set(raw["symbol"].astype(str)))
        bars = lance.load_bars(con, symbols)
    finally:
        con.close()
    print("[vwr] frozen right-side", flush=True)
    frozen = run_arm(raw, bars, min_drop=0.15, hold_bars=10, target_r=1.0)
    book = packs(frozen)
    print(
        f"[vwr] frozen n={book['full'].get('n')} wr={book['full'].get('win_pct')} avg={book['full'].get('avg_pnl')}",
        flush=True,
    )
    src = pd.read_csv(SOURCE / "trades_right.csv")
    if len(src) != len(frozen):
        raise SystemExit(f"frozen resim {len(frozen)} != source trades {len(src)}")
    if abs(float(src["pnl"].sum()) - sum(t["pnl"] for t in frozen)) > 0.05:
        raise SystemExit("frozen resim pnl does not match source trades_right.csv")

    print("[vwr] entry tighter drop", flush=True)
    tight = run_arm(raw, bars, min_drop=0.25, hold_bars=10, target_r=1.0)
    print("[vwr] exit 2R", flush=True)
    target2 = run_arm(raw, bars, min_drop=0.15, hold_bars=10, target_r=2.0)
    print("[vwr] exit 20 sessions", flush=True)
    hold20 = run_arm(raw, bars, min_drop=0.15, hold_bars=20, target_r=1.0)
    restore_freeze()

    full_traits = trait_block(frozen, "full")
    is_traits = trait_block(lance._slice(frozen, "is"), "is")
    prose, deeper = winner_prose(full_traits, is_traits)

    arm_defs = [
        {
            "name": "5-day drop at or below −25%",
            "kind": "ENTRY",
            "what": (
                "Same reclaim entry, same 1R target, same ten-session exit. "
                "The only change is the washout screen: the five-day drop must be 25% or more, instead of 15%."
            ),
            "trades": tight,
            "selection_bias": (
                "Before 2024, the top of the return distribution had a deeper five-day drop than the other trades "
                "(see the winner table). This arm tests that tighter screen. "
                "It was not part of the source page's scored test. Looking at winners and then filtering for them is in-sample selection."
            ) if deeper else "",
        },
        {
            "name": "Target at 2R",
            "kind": "EXIT",
            "what": (
                "Same buys as the freeze. The target is twice the risk instead of one times the risk. "
                "The stop and the ten-session clock stay put. "
                "The winner description shows the large percent gains are mostly 1R prints on wide washouts, "
                "so the next exit question is whether asking for 2R improves the in-sample trade. "
                "That question comes from the frozen exit, not from a new symbol filter."
            ),
            "trades": target2,
            "selection_bias": "",
        },
        {
            "name": "Time exit at session 20",
            "kind": "EXIT",
            "what": (
                "Same 15% washout and same 1R target. The clock is 20 sessions instead of 10. "
                "In the generator, a name is also locked for that same window, so this arm can skip signals the freeze would have taken. "
                "About one in five frozen trades ends on the ten-session clock, which is why this is the next time test."
            ),
            "trades": hold20,
            "selection_bias": "",
        },
    ]
    arms = []
    for arm in arm_defs:
        p = packs(arm["trades"])
        verdict, finding = judge(book["is"], p["is"], p["oos"])
        arms.append({**arm, "packs": p, "verdict": verdict, "finding": finding})
        safe_name = arm["name"].replace("\u2212", "-")
        print(f"[vwr] {arm['kind']} {safe_name}: {verdict}", flush=True)

    print("[vwr] reading published books", flush=True)
    house = load_house()
    html = render(frozen, book, house, prose, deeper, full_traits, is_traits, arms)
    (OUT / "report.html").write_text(html, encoding="utf-8")
    write_trades(OUT / "trades.csv", frozen)
    write_baseline(book, arms, deeper)
    print(f"[vwr] wrote {OUT}", flush=True)
    for sl in ("full", "is", "oos"):
        s = book[sl]
        print(
            f"[vwr] {sl} N={s.get('n')} WR={s.get('win_pct'):.2f} avg={s.get('avg_pnl'):.4f} ann={s.get('ann_ror')}",
            flush=True,
        )
    for arm in arms:
        safe = (arm["name"] + " | " + arm["finding"]).replace("\u2212", "-")
        print(f"[vwr] FINDING {arm['verdict']} | {safe}", flush=True)


if __name__ == "__main__":
    main()
