#!/usr/bin/env python3
"""Similar Stock Difference exit grid. Research only. Not gold. Not DailyRun.

The grid below is frozen before any profit number from this run is read.
Choosing a best cell after the table is in-sample selection. Do not adopt one.
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import thorp_timestop_and_chain_scan_20261001 as thorp  # noqa: E402
from compare_format import format_money  # noqa: E402

sys.path.insert(0, str(ROOT))
from report_page_extras import RESPONSIVE_TABLE_CSS, SWIPE_NOTE_HTML  # noqa: E402

OUT = ROOT / "drive" / "paul_experiments" / "ssd_exit_grid_20261001"
PAIRS_CSV = thorp.PAIRS_CSV
CLOCK_CSV = (
    ROOT
    / "drive"
    / "paul_experiments"
    / "thorp_timestop_and_chain_scan_20261001"
    / "trades_timestop.csv"
)
IS_CUT = thorp.IS_CUT
STAKE = thorp.STAKE
# Same last session as the frozen 2010 book and the 15-session clock page.
STUDY_END = pd.Timestamp("2026-09-30")

# Frozen before this script looks at profit. Do not add cells after the fact.
# Time sweep holds the band at 0.5. Band sweep holds the clock at 15.
# Time 15 and band 0.5 are the same replay as baseline B, not extra ideas.
GRID = (
    {"arm_id": "A", "family": "Baseline", "name": "A — 0.5 band, no clock", "exit_z": 0.5, "clock": None, "same_as": ""},
    {"arm_id": "B", "family": "Baseline", "name": "B — 0.5 band or 15 sessions", "exit_z": 0.5, "clock": 15, "same_as": ""},
    {"arm_id": "T5", "family": "Time sweep", "name": "5 sessions, band 0.5", "exit_z": 0.5, "clock": 5, "same_as": ""},
    {"arm_id": "T10", "family": "Time sweep", "name": "10 sessions, band 0.5", "exit_z": 0.5, "clock": 10, "same_as": ""},
    {"arm_id": "T15", "family": "Time sweep", "name": "15 sessions, band 0.5", "exit_z": 0.5, "clock": 15, "same_as": "B"},
    {"arm_id": "T20", "family": "Time sweep", "name": "20 sessions, band 0.5", "exit_z": 0.5, "clock": 20, "same_as": ""},
    {"arm_id": "T40", "family": "Time sweep", "name": "40 sessions, band 0.5", "exit_z": 0.5, "clock": 40, "same_as": ""},
    {"arm_id": "Z025", "family": "Band sweep", "name": "0.25 band, clock 15", "exit_z": 0.25, "clock": 15, "same_as": ""},
    {"arm_id": "Z050", "family": "Band sweep", "name": "0.50 band, clock 15", "exit_z": 0.5, "clock": 15, "same_as": "B"},
    {"arm_id": "Z100", "family": "Band sweep", "name": "1.00 band, clock 15", "exit_z": 1.0, "clock": 15, "same_as": ""},
    {"arm_id": "Z150", "family": "Band sweep", "name": "1.50 band, clock 15", "exit_z": 1.5, "clock": 15, "same_as": ""},
)

# Frozen verdict vs baseline B. Uses the in-sample marked book, not out-of-sample.
# Same 1 point / 10 point idea as the published 15-session clock page, plus an
# 80% count floor so a much smaller book cannot keep on a handful of trades.
KEEP_AVG_EDGE = 1.0
KEEP_WR_DROP_MAX = 10.0
KEEP_N_RATIO_MIN = 0.80
FOCUS_PAIRS = (("HL", "NEM"), ("PNFP", "ZION"))

ORIGINAL_REQUEST = (
    "great - thanks. looks like we might have something here. let's split this into 2 different jobs.\n"
    "1. SSD. Similar Stock difference. can we run different numbers to use to exit for both "
    "standard deviation and time exit?"
)


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _th(label: str, sort: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{_esc(label)}<span class="sort-ind"></span></th>'
    )


def _td(text: str, num: bool = False) -> str:
    cls = ' class="num"' if num else ""
    return f"<td{cls}>{_esc(text)}</td>"


def _pct(value: float, digits: int = 2) -> str:
    if value is None or not np.isfinite(value):
        return "—"
    return f"{value:+.{digits}f}%"


def _md_pct(value: float, digits: int = 2) -> str:
    return _pct(value, digits)


def _num(value: float, digits: int = 2) -> str:
    if value is None or not np.isfinite(value):
        return "—"
    return f"{value:,.{digits}f}"


def _clock_label(clock: int | None) -> str:
    if clock is None:
        return "none"
    return str(int(clock))


def replay(panels, best_on, gap_count, all_dates, bt, exit_z: float, clock: int | None):
    """Same engine as the clock page. Band width is the only added knob."""
    thorp.EXIT_Z = float(exit_z)
    trades, equity, meta = thorp.replay(panels, best_on, gap_count, all_dates, bt, clock)
    if clock is not None and int(clock) != 15:
        reason = f"{int(clock)}-session time stop"
        for trade in trades:
            if trade.get("reason") == "15-session time stop":
                trade["reason"] = reason
    return trades, equity, meta


def _assert_book(frame: pd.DataFrame, published_path: Path, name: str) -> None:
    published = pd.read_csv(published_path)
    if len(frame) != len(published):
        raise SystemExit(f"{name} trade count {len(frame)} != published {len(published)}")
    for i, pub in published.iterrows():
        got = frame.iloc[i]
        for col in ("left", "right", "long", "short", "entry_date", "status"):
            if str(got[col]) != str(pub[col]):
                raise SystemExit(f"{name} {col} row {i}: {got[col]} != {pub[col]}")
        if "signal_date" in published.columns and str(got["signal_date"]) != str(pub["signal_date"]):
            raise SystemExit(f"{name} signal_date row {i}: {got['signal_date']} != {pub['signal_date']}")
        pub_exit = "" if pd.isna(pub.get("exit_date")) else str(pub["exit_date"])
        got_exit = "" if not str(got["exit_date"]) or str(got["exit_date"]) == "nan" else str(got["exit_date"])
        if str(pub["status"]) == "closed" and got_exit != pub_exit:
            raise SystemExit(f"{name} exit_date row {i}: {got_exit} != {pub_exit}")
        if "reason" in published.columns and str(got["reason"]) != str(pub["reason"]):
            raise SystemExit(f"{name} reason row {i}: {got['reason']} != {pub['reason']}")
        tol = 0.05 if str(pub["status"]) == "closed" else 5.0
        if abs(float(got["net_pct"]) - float(pub["net_pct"])) > tol:
            raise SystemExit(f"{name} net_pct row {i}: {got['net_pct']} != {pub['net_pct']}")
    print(f"{name} matches the published book", flush=True)


def marked_stats(frame: pd.DataFrame, trades: list[dict], panel_map: dict, bt) -> dict:
    pcts = thorp.marked_is_pcts(frame, trades, panel_map, bt)
    if not pcts:
        return {"n": 0, "avg": float("nan"), "median": float("nan"), "wr": float("nan")}
    arr = np.asarray(pcts, dtype=float)
    return {
        "n": int(len(arr)),
        "avg": float(np.mean(arr)),
        "median": float(np.median(arr)),
        "wr": 100.0 * float(np.mean(arr > 0)),
    }


def judge_vs_b(arm: dict, base: dict, is_baseline_cell: bool) -> tuple[str, str]:
    """In-sample quality versus baseline B. Out-of-sample is not an input."""
    if is_baseline_cell:
        return (
            "baseline",
            "This cell is baseline B. Same 0.5 band and same 15-session clock. It is not a new exit.",
        )
    a = arm["marked"]
    b = base["marked"]
    if not (np.isfinite(a["avg"]) and np.isfinite(b["avg"])):
        return "HOLD", "The in-sample marked average is not a number, so this stays a hold. Out-of-sample was not used."
    gap = float(a["avg"] - b["avg"])
    wr_drop = (b["wr"] - a["wr"]) if np.isfinite(a["wr"]) and np.isfinite(b["wr"]) else float("nan")
    collapsed = b["n"] > 0 and a["n"] < KEEP_N_RATIO_MIN * b["n"]
    if gap < -KEEP_AVG_EDGE:
        return (
            "DISMISS",
            f"In-sample marked average is {gap:+.2f} points versus baseline B, worse than the 1 point bar. "
            "Out-of-sample was not used.",
        )
    if collapsed:
        return (
            "HOLD",
            "In-sample marked count is under 80% of baseline B, so the book shrank. Not a keep. "
            "Out-of-sample was not used.",
        )
    if gap > KEEP_AVG_EDGE and (not np.isfinite(wr_drop) or wr_drop <= KEEP_WR_DROP_MAX):
        return (
            "KEEP",
            "In-sample marked average is more than 1 point above baseline B, the win rate did not fall "
            "by more than 10 points, and the marked count stayed at least 80% of baseline B. "
            "Research only. Not adopted. Out-of-sample was not used.",
        )
    if gap > KEEP_AVG_EDGE and np.isfinite(wr_drop) and wr_drop > KEEP_WR_DROP_MAX:
        return (
            "HOLD",
            "In-sample marked average is higher, but the win rate fell by more than 10 points. Not a keep. "
            "Out-of-sample was not used.",
        )
    return (
        "HOLD",
        "In-sample marked average is within 1 point of baseline B. Not a keep and not a dismiss. "
        "Out-of-sample was not used.",
    )


def _slice_frame(frame: pd.DataFrame, sample: str | None) -> pd.DataFrame:
    if sample is None:
        return frame
    return frame[frame["sample"] == sample]


def open_text(frame: pd.DataFrame, sample: str | None = None) -> str:
    rows = _slice_frame(frame, sample)
    rows = rows[rows["status"] == "open"]
    if rows.empty:
        return "flat"
    bits = []
    for rec in rows.itertuples(index=False):
        bits.append(
            f"{rec.short} short / {rec.long} long ({rec.left}/{rec.right}), entered {rec.entry_date}, "
            f"marked {_pct(rec.net_pct)} at {rec.mark_date} ({rec.reason})"
        )
    return "; ".join(bits)


def _pf(stats: dict) -> str:
    return thorp._pf_text(stats["pf"], stats["wins"], stats["n"])


def _calmar(ann: float, max_dd: float) -> float:
    if not (np.isfinite(ann) and np.isfinite(max_dd)) or abs(max_dd) < 1e-9:
        return float("nan")
    return float(ann / abs(max_dd))


def pack_arm(spec: dict, frame: pd.DataFrame, trades: list[dict], equity: pd.DataFrame, panel_map, bt) -> dict:
    full_y, is_y, oos_y = thorp.slice_years(equity)
    samples = {
        "full": closed_and_path(frame, equity, full_y, None),
        "IS": closed_and_path(frame, equity, is_y, "IS"),
        "OOS": closed_and_path(frame, equity, oos_y, "OOS"),
    }
    return {
        **spec,
        "frame": frame,
        "trades": trades,
        "samples": samples,
        "marked": marked_stats(frame, trades, panel_map, bt),
        "open_full": open_text(frame, None),
        "open_is": open_text(frame, "IS"),
        "open_oos": open_text(frame, "OOS"),
    }


def closed_and_path(frame: pd.DataFrame, equity: pd.DataFrame, years: float, sample: str | None) -> dict:
    view = _slice_frame(frame, sample)
    stats = thorp.closed_metrics(view, years)
    if sample == "IS":
        path = thorp.path_stats(equity[equity["date"] < IS_CUT])
    elif sample == "OOS":
        path = thorp.path_stats(equity[equity["date"] >= IS_CUT])
    else:
        path = thorp.path_stats(equity)
    stats["max_dd"] = path["max_dd"]
    stats["sharpe"] = path["sharpe"]
    stats["path_ann"] = path["ann"]
    stats["calmar"] = _calmar(stats["ann_ror"], path["max_dd"])
    stats["open_n"] = int((view["status"] == "open").sum()) if not view.empty else 0
    return stats


def focus_rows(arm: dict) -> list[dict]:
    frame = arm["frame"]
    out = []
    for left, right in FOCUS_PAIRS:
        pair = f"{left}/{right}"
        hit = frame[
            ((frame["left"] == left) & (frame["right"] == right))
            | ((frame["left"] == right) & (frame["right"] == left))
        ]
        if hit.empty:
            out.append(
                {
                    "arm_id": arm["arm_id"],
                    "pair": pair,
                    "in_path": "no",
                    "status": "",
                    "sample": "",
                    "entry_date": "",
                    "exit_or_mark": "",
                    "sessions": "",
                    "reason": "Not in this path",
                    "net_pct": float("nan"),
                    "long": "",
                    "short": "",
                }
            )
            continue
        for rec in hit.itertuples(index=False):
            when = rec.exit_date if rec.status == "closed" and rec.exit_date else rec.mark_date
            sessions = rec.sessions_after_entry
            out.append(
                {
                    "arm_id": arm["arm_id"],
                    "pair": pair,
                    "in_path": "yes",
                    "status": rec.status,
                    "sample": rec.sample,
                    "entry_date": rec.entry_date,
                    "exit_or_mark": when,
                    "sessions": "" if pd.isna(sessions) else str(int(sessions)),
                    "reason": rec.reason,
                    "net_pct": float(rec.net_pct),
                    "long": rec.long,
                    "short": rec.short,
                }
            )
    return out


def _oos_note(arm: dict, base: dict) -> str:
    a = arm["samples"]["OOS"]["avg_pct"]
    b = base["samples"]["OOS"]["avg_pct"]
    if np.isfinite(a) and np.isfinite(b) and a < b - KEEP_AVG_EDGE:
        return "OOS average is softer than baseline B. Report only. Knobs were not changed."
    return "OOS is report-only."


def summary_rows(arms: list[dict]) -> pd.DataFrame:
    rows = []
    for arm in arms:
        for sample in ("full", "IS", "OOS"):
            st = arm["samples"][sample]
            rows.append(
                {
                    "arm_id": arm["arm_id"],
                    "family": arm["family"],
                    "name": arm["name"],
                    "exit_z": arm["exit_z"],
                    "clock_sessions": "" if arm["clock"] is None else int(arm["clock"]),
                    "same_book_as": arm["same_as"],
                    "sample": sample,
                    "n_closed": st["n"],
                    "wins": st["wins"],
                    "losses": st["losses"],
                    "win_pct": st["win_pct"],
                    "avg_pct": st["avg_pct"],
                    "median_pct": st["median_pct"],
                    "avg_win_pct": st["avg_win"],
                    "avg_loss_pct": st["avg_loss"],
                    "pf": st["pf"],
                    "avg_pct_wo_max": st["wo_max"],
                    "outlier_pct": st["outlier"],
                    "expectancy_pct": st["expectancy_pct"],
                    "trades_per_year": st["tpy"],
                    "avg_days": st["avg_days"],
                    "median_days": st["median_days"],
                    "capital_days": st["capital_days"],
                    "profit_per_capital_day": st["profit_per_capital_day"],
                    "ann_ror": st["ann_ror"],
                    "max_dd_path": st["max_dd"],
                    "sharpe_path": st["sharpe"],
                    "calmar_house_ann_over_path_dd": st["calmar"],
                    "line_exits": st["line_n"],
                    "clock_exits": st["time_n"],
                    "open_n": st["open_n"],
                    "open_book": {"full": arm["open_full"], "IS": arm["open_is"], "OOS": arm["open_oos"]}[sample],
                    "marked_is_n": arm["marked"]["n"],
                    "marked_is_avg": arm["marked"]["avg"],
                    "marked_is_median": arm["marked"]["median"],
                    "marked_is_win_pct": arm["marked"]["wr"],
                    "verdict": arm["verdict"],
                    "verdict_why": arm["verdict_why"],
                    "oos_note": arm["oos_note"],
                }
            )
    return pd.DataFrame(rows)


def _table(headers: list[tuple[str, str]], rows: list[str], caption: str) -> str:
    head = "".join(_th(label, sort) for label, sort in headers)
    body = "".join(rows)
    return (
        '<div class="table-wrap"><table class="sortable">'
        f"<caption>{caption}</caption>"
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def _arm_headline_row(arm: dict, base: dict) -> str:
    full = arm["samples"]["full"]
    ins = arm["samples"]["IS"]
    oos = arm["samples"]["OOS"]
    cells = [
        _td(arm["arm_id"]),
        _td(arm["family"]),
        _td(arm["name"]),
        _td(f"{arm['exit_z']:.2f}", True),
        _td(_clock_label(arm["clock"]), True),
        _td(str(full["n"]), True),
        _td(_pct(full["win_pct"], 1), True),
        _td(_pct(full["avg_pct"]), True),
        _td(_pct(full["median_pct"]), True),
        _td(_pct(full["ann_ror"], 1), True),
        _td(str(ins["n"]), True),
        _td(_pct(ins["win_pct"], 1), True),
        _td(_pct(ins["avg_pct"]), True),
        _td(_pct(ins["median_pct"]), True),
        _td(_pct(ins["ann_ror"], 1), True),
        _td(str(oos["n"]), True),
        _td(_pct(oos["win_pct"], 1), True),
        _td(_pct(oos["avg_pct"]), True),
        _td(_pct(oos["median_pct"]), True),
        _td(_pct(oos["ann_ror"], 1), True),
        _td(arm["open_full"]),
        _td(arm["verdict"]),
    ]
    return "<tr>" + "".join(cells) + "</tr>"


def _quality_row(arm: dict, base: dict) -> str:
    ins = arm["samples"]["IS"]
    b = base["samples"]["IS"]
    m = arm["marked"]
    bm = base["marked"]
    cells = [
        _td(arm["arm_id"]),
        _td(arm["family"]),
        _td(str(ins["n"]), True),
        _td(_pct(ins["win_pct"], 1), True),
        _td(_pct(ins["avg_pct"]), True),
        _td(_pct(ins["avg_pct"] - b["avg_pct"]), True),
        _td(_pct(ins["median_pct"]), True),
        _td(str(m["n"]), True),
        _td(_pct(m["wr"], 1), True),
        _td(_pct(m["avg"]), True),
        _td(_pct(m["avg"] - bm["avg"]), True),
        _td(_pct(m["median"]), True),
        _td(_pct(ins["ann_ror"], 1), True),
        _td(_pct(ins["max_dd"], 1), True),
        _td(_num(ins["sharpe"], 2), True),
        _td(_num(ins["calmar"], 2), True),
        _td(f"{ins['line_n']} / {ins['time_n']}", True),
        _td(arm["open_is"]),
        _td(arm["verdict"]),
    ]
    return "<tr>" + "".join(cells) + "</tr>"


def _canon_row(arm: dict, sample: str, base: dict) -> str:
    st = arm["samples"][sample]
    b = base["samples"][sample]
    cells = [
        _td(arm["arm_id"]),
        _td(sample),
        _td(str(st["n"]), True),
        _td(str(st["wins"]), True),
        _td(str(st["losses"]), True),
        _td(_pct(st["win_pct"], 1), True),
        _td(_pct(st["win_pct"] - b["win_pct"], 1), True),
        _td(_pct(st["avg_pct"]), True),
        _td(_pct(st["avg_pct"] - b["avg_pct"]), True),
        _td(_pct(st["median_pct"]), True),
        _td(_pct(st["avg_win"]), True),
        _td(_pct(st["avg_loss"]), True),
        _td(_pf(st), True),
        _td(_pct(st["wo_max"]), True),
        _td(_pct(st["outlier"], 1), True),
        _td(_pct(st["expectancy_pct"]), True),
        _td(_num(st["tpy"], 2), True),
        _td(_num(st["avg_days"], 1), True),
        _td(_num(st["median_days"], 1), True),
        _td(f"{st['capital_days']:,}", True),
        _td(format_money(st["profit_per_capital_day"]), True),
        _td(_pct(st["ann_ror"], 1), True),
        _td(_pct(st["ann_ror"] - b["ann_ror"], 1), True),
        _td(_pct(st["max_dd"], 1), True),
        _td(_num(st["sharpe"], 2), True),
        _td(_num(st["calmar"], 2), True),
        _td(str(st["line_n"]), True),
        _td(str(st["time_n"]), True),
        _td(arm["verdict"] if sample == "IS" else "report only"),
    ]
    return "<tr>" + "".join(cells) + "</tr>"


def _focus_html(rows: list[dict]) -> str:
    body = []
    for rec in rows:
        body.append(
            "<tr>"
            + _td(rec["arm_id"])
            + _td(rec["pair"])
            + _td(rec["in_path"])
            + _td(rec["status"])
            + _td(rec["sample"])
            + _td(rec["short"] + (" / " + rec["long"] if rec["long"] else ""))
            + _td(rec["entry_date"])
            + _td(rec["exit_or_mark"])
            + _td(rec["sessions"], True)
            + _td(rec["reason"])
            + _td(_pct(rec["net_pct"]), True)
            + "</tr>"
        )
    return _table(
        [
            ("Arm", "text"),
            ("Pair", "text"),
            ("In this path", "text"),
            ("Status", "text"),
            ("Sample", "text"),
            ("Short / long", "text"),
            ("Entry", "date"),
            ("Exit or mark", "date"),
            ("Sessions after entry", "num"),
            ("How it ended", "text"),
            ("Result %", "num"),
        ],
        body,
        "HL/NEM and PNFP/ZION under each rule. Click a column header to sort. "
        "One pair is held at a time, so an earlier exit changes the next trade.",
    )


def render(arms: list[dict], base: dict, focus: list[dict], best: dict) -> str:
    headline = "".join(_arm_headline_row(arm, base) for arm in arms)
    quality = "".join(_quality_row(arm, base) for arm in arms)
    canon_is = "".join(_canon_row(arm, "IS", base) for arm in arms)
    canon_full = "".join(_canon_row(arm, "full", base) for arm in arms)
    canon_oos = "".join(_canon_row(arm, "OOS", base) for arm in arms)
    headlines = _table(
        [
            ("Arm", "text"),
            ("Sweep", "text"),
            ("Rule", "text"),
            ("Band", "num"),
            ("Clock sessions", "num"),
            ("N full", "num"),
            ("WR full", "num"),
            ("Avg full", "num"),
            ("Median full", "num"),
            ("Full Ann ROR", "num"),
            ("N IS", "num"),
            ("WR IS", "num"),
            ("Avg IS", "num"),
            ("Median IS", "num"),
            ("IS Ann ROR", "num"),
            ("N OOS", "num"),
            ("WR OOS", "num"),
            ("Avg OOS", "num"),
            ("Median OOS", "num"),
            ("OOS Ann ROR", "num"),
            ("Open book at the last price", "text"),
            ("Verdict vs B", "text"),
        ],
        [headline],
        "Closed trades. N, win rate, average, and median are closed trades only. "
        "The open book is whatever is still on at the last price, and it is not in those closed averages. "
        "Click a column header to sort.",
    )
    quality_tbl = _table(
        [
            ("Arm", "text"),
            ("Sweep", "text"),
            ("IS closed N", "num"),
            ("IS closed WR", "num"),
            ("IS closed avg", "num"),
            ("IS closed avg minus B", "num"),
            ("IS closed median", "num"),
            ("IS marked N", "num"),
            ("IS marked WR", "num"),
            ("IS marked avg", "num"),
            ("IS marked avg minus B", "num"),
            ("IS marked median", "num"),
            ("IS Ann ROR", "num"),
            ("IS Max DD", "num"),
            ("IS Sharpe", "num"),
            ("IS Calmar", "num"),
            ("IS line / clock exits", "num"),
            ("IS entry still open at the end", "text"),
            ("Verdict vs B", "text"),
        ],
        [quality],
        "Verdict sample. In-sample means the entry is before 2024-01-01. "
        "Marked keeps the closed in-sample result and, if that entry is still open at the last session before 2024, "
        "marks it there. Median is shown and is not the verdict input. Click a column header to sort.",
    )
    canon_headers = [
        ("Arm", "text"),
        ("Sample", "text"),
        ("N", "num"),
        ("Wins", "num"),
        ("Losses", "num"),
        ("Win %", "num"),
        ("Win % minus B", "num"),
        ("Avg %", "num"),
        ("Avg % minus B", "num"),
        ("Median %", "num"),
        ("Avg win %", "num"),
        ("Avg loss %", "num"),
        ("Profit factor", "num"),
        ("Avg % without the largest win", "num"),
        ("Outlier share of winning %", "num"),
        ("Expectancy %", "num"),
        ("Trades per year", "num"),
        ("Avg days held", "num"),
        ("Median days held", "num"),
        ("Capital days", "num"),
        ("Profit per capital day", "num"),
        ("Ann ROR", "num"),
        ("Ann ROR minus B", "num"),
        ("Max DD", "num"),
        ("Sharpe", "num"),
        ("Calmar", "num"),
        ("Line exits", "num"),
        ("Clock exits", "num"),
        ("Label", "text"),
    ]
    js = r"""
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-" || s === "flat") return type === "text" || type === "date" ? "" : 0;
    if (type === "text" || type === "date" || type === "month") return s.toUpperCase();
    var n = s.replace(/[$,%+]/g, "").replace(/,/g, "").replace(/ pp/g, "");
    var v = parseFloat(n);
    return Number.isFinite(v) ? v : 0;
  }
  function sortTable(table, col, type, dir) {
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll("tr"));
    var pinned = rows.filter(function (r) { return r.classList.contains("total-row"); });
    var movable = rows.filter(function (r) { return !r.classList.contains("total-row"); });
    movable.sort(function (a, b) {
      var av = parseSortValue(a.cells[col] && a.cells[col].textContent, type);
      var bv = parseSortValue(b.cells[col] && b.cells[col].textContent, type);
      if (typeof av === "string" || typeof bv === "string") return dir * String(av).localeCompare(String(bv));
      return dir * (av - bv);
    });
    movable.concat(pinned).forEach(function (r) { tbody.appendChild(r); });
  }
  function bindSortHeader(table, th, col) {
    function onActivate(e) {
      if (e.type === "touchend") e.preventDefault();
      var type = th.dataset.sort || "text";
      var dir = th.dataset.dir === "asc" ? -1 : 1;
      table.querySelectorAll("th.sortable-th").forEach(function (h) {
        h.dataset.dir = "";
        h.classList.remove("sort-asc", "sort-desc");
        h.setAttribute("aria-sort", "none");
      });
      th.dataset.dir = dir === 1 ? "asc" : "desc";
      th.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
      th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
      sortTable(table, col, type, dir);
    }
    th.addEventListener("click", onActivate);
    th.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onActivate(e); }
    });
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    var headers = table.tHead ? table.tHead.rows[0].cells : [];
    Array.prototype.forEach.call(headers, function (th, col) {
      if (th.classList.contains("sortable-th")) bindSortHeader(table, th, col);
    });
  });
})();
</script>
"""
    best_names = ", ".join(best["names"])
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Similar Stock Difference exit grid — 2026-10-01</title>
  <style>
  :root {{
    --bg: #f7f6f2; --ink: #1c1b19; --muted: #5a574f; --line: #d4d0c4;
    --card: #ffffff; --accent: #2a4a5c; --accent-soft: #e8eef2;
    --ok: #2d6a4f; --ok-bg: #e8f2ec; --warn: #8a5a12; --warn-bg: #f7efe0;
    --fill: #f0eee6; --bad: #9b2226; --bad-bg: #fdecea;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; font-family: "Segoe UI", "Helvetica Neue", Georgia, serif;
    font-size: 16px; line-height: 1.55; color: var(--ink);
    background:
      radial-gradient(ellipse 80% 50% at 10% -10%, #e4ebe8 0%, transparent 55%),
      radial-gradient(ellipse 60% 40% at 100% 0%, #ebe6dc 0%, transparent 50%),
      var(--bg);
  }}
  .wrap {{ max-width: 1280px; margin: 0 auto; padding: 36px 22px 72px; }}
  header.doc-head {{ border-bottom: 2px solid var(--ink); padding-bottom: 14px; margin-bottom: 22px; }}
  .eyebrow {{
    font-size: 0.72rem; letter-spacing: 0.14em; text-transform: uppercase;
    color: var(--accent); font-weight: 650; margin: 0 0 6px;
  }}
  h1 {{ font-size: 1.65rem; margin: 0 0 8px; letter-spacing: -0.02em; line-height: 1.25; }}
  h2 {{ font-size: 1.2rem; margin: 32px 0 10px; padding-bottom: 5px; border-bottom: 1px solid var(--line); }}
  p, li {{ margin: 0 0 10px; }}
  blockquote.ask {{
    margin: 8px 0 0; white-space: pre-wrap;
    font-family: Georgia, "Times New Roman", serif; font-size: 0.95rem;
  }}
  .callout {{ background: var(--accent-soft); border-left: 4px solid var(--accent); padding: 12px 14px; margin: 14px 0 18px; }}
  .callout.warn {{ background: var(--warn-bg); border-left-color: var(--warn); }}
  .table-wrap {{ overflow-x: auto; margin: 8px 0 16px; }}
  table.sortable {{ border-collapse: collapse; width: 100%; font-size: 13.5px; background: var(--card); }}
  th, td {{ border: 1px solid var(--line); padding: 7px 8px; text-align: left; vertical-align: top; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
  thead th {{ background: var(--fill); }}
  th.sortable-th {{ cursor: pointer; user-select: none; }}
  th.sortable-th:hover {{ background: #e8e4d8; }}
  .sort-ind {{ display: inline-block; width: 0.9em; margin-left: 4px; color: #9a9588; font-size: 10px; }}
  th.sort-asc .sort-ind::after {{ content: "\\25B2"; color: var(--ink); }}
  th.sort-desc .sort-ind::after {{ content: "\\25BC"; color: var(--ink); }}
  caption {{ text-align: left; font-size: 0.86rem; color: var(--muted); margin: 0 0 6px; caption-side: top; }}
  footer {{ margin-top: 28px; font-size: 0.82rem; color: var(--muted); border-top: 1px solid var(--line); padding-top: 12px; }}
  </style>
</head>
<body>
<div class="wrap">
  <header class="doc-head">
    <p class="eyebrow">Research only · not gold · not DailyRun</p>
    <h1>Similar Stock Difference exit grid</h1>
    <p>Job 1 only. Job 2, the option differential, is a separate page and is not here.</p>
  </header>

  <div class="callout">
    <strong>What you asked</strong>
    <blockquote class="ask">{_esc(ORIGINAL_REQUEST)}</blockquote>
    <p>This page is job 1. Job 2 is not in this folder.</p>
  </div>

  <div class="callout">
    <strong>In plain English</strong>
    <p>Similar Stock Difference (SSD) shorts the stock that ran ahead and buys the one that lagged. This test only changes when we get out: either when they are close again on a standard-deviation band, or when a fixed number of days runs out.</p>
    <p>The pair list and the entry rule stay frozen. Two stocks have to move together (full-window correlation at least 0.60, and each half at least 0.55). A gap is a close at least 2 standard deviations off a 252-session ordinary least squares (OLS) line that stops the day before the signal. The book holds one pair, about $10,000 of whole shares on each side, filled at the next open. Baseline A gets out only when a later close is back within 0.5 standard deviations of the line frozen at entry, filled at the next open. Baseline B uses that same band, or the close of the 15th session, whichever comes first. The other rows change only the session count, or only the band width. The grid was written down before these profit numbers were computed.</p>
  </div>

  <div class="callout warn">
    <strong>Pre-declared search, not a production pick</strong>
    <p>Judging the best cell after seeing this table is in-sample selection. The highest in-sample marked average in this grid is { _esc(best_names) }, at {_pct(best["avg"])} on {best["n"]} marked entries. That label uses the in-sample number after the table existed. This page does not adopt that cell, does not add a new band or a new clock, and does not use the out-of-sample row to pick.</p>
    <p>A keep here means the in-sample marked book beat baseline B on a frozen rule: more than 1 percentage point of marked average, win rate not worse by more than 10 points, and marked count at least 80% of baseline B. Research only.</p>
  </div>

  <h2>What was frozen</h2>
  <ul>
    <li>Pair menu: the saved 2010 file, not a new correlation run. Full window at least 0.60, each half at least 0.55.</li>
    <li>Prices stop at the same last session as those two books, 2026-09-30, even if the warehouse has a later print.</li>
    <li>Entry: |z| at least 2 on the prior 252 sessions, biggest absolute percent gap, one pair, next open, short the high side, long the low side, $10,000 a leg, whole shares.</li>
    <li>Band exit fills at the next open. A clock exit fills at the close of that session. If both fire, the open fill already scheduled for today happens first. On the clock day itself, the close is used if no band fill is already due that morning.</li>
    <li>In-sample: entry before 2024-01-01. Out-of-sample: entry on or after 2024-01-01. Out-of-sample is report-only.</li>
    <li>Annualized rate of return is the house formula on closed trades: one plus total result divided by ($10,000 times the number of trades), raised to 365 divided by average calendar days held, minus one. The two legs are $10,000 each. The formula still uses $10,000 because that is the stake this book already uses. Max drawdown and Sharpe come from the marked account path (reference $10,000 plus closed results and the open mark). Calmar is that house annualized rate divided by the absolute path max drawdown. Paul score and FIT are not on this pairs book.</li>
    <li>Costs left out: dividends, borrow, commission. Same as the 2010 book.</li>
  </ul>

  <h2>The grid</h2>
  {headlines}

  <h2>In-sample verdict versus baseline B</h2>
  {quality_tbl}

  <h2>Book metrics, in-sample</h2>
  {_table(canon_headers, [canon_is], "In-sample closed trades, absolute and versus baseline B. Verdicts use the marked book in the table above, not this closed-only average. Click a column header to sort.")}

  <h2>Book metrics, full history</h2>
  {_table(canon_headers, [canon_full], "Full closed book. Click a column header to sort. Dollar profit totals are left off this page; profit per capital day is the per-day figure.")}

  <h2>Out-of-sample, report only</h2>
  <p>These rows were not used to keep, hold, or dismiss an arm. If an out-of-sample average is softer than baseline B, the knobs stay where they were.</p>
  {_table(canon_headers, [canon_oos], "Out-of-sample closed trades, entry on or after 2024-01-01. Report only. Click a column header to sort.")}

  <h2>HL / NEM and PNFP / ZION</h2>
  <p>The book holds one pair. An earlier clock or a wider band frees the next day for a different gap, so these two names can vanish, show up later, or exit on a different rule. That is path dependence. A missing row means the pair never got the book under that rule, not that the signal failed to exist on the calendar.</p>
  {_focus_html(focus)}

  <h2>How each verdict was reached</h2>
  <ul>
    {''.join(f'<li><strong>{_esc(arm["arm_id"])} — {_esc(arm["verdict"])}.</strong> {_esc(arm["verdict_why"])} {_esc(arm["oos_note"])}</li>' for arm in arms)}
  </ul>

  <footer>
    Research only · 1 October 2026 · ssd_exit_grid_20261001 · not gold · not DailyRun.
    The 2010 pairs folder and the time-stop folder were not overwritten.
  </footer>
</div>
{js}
</body>
</html>
"""
    if "report-table-responsive" not in page:
        page = page.replace("</style>", RESPONSIVE_TABLE_CSS + "\n</style>", 1)
    if "Swipe sideways to see more columns." not in page:
        page = page.replace("</h1>", "</h1>\n  " + SWIPE_NOTE_HTML, 1)
    return page


def baseline_md(arms: list[dict], base: dict, best: dict, n_pairs: int) -> str:
    lines = [
        "# Similar Stock Difference exit grid",
        "",
        "Research only. Not gold. Not DailyRun. This page does not adopt a cell.",
        "",
        "## What you asked",
        "",
        "> " + ORIGINAL_REQUEST.replace("\n", "\n> "),
        "",
        "Job 1 only. Job 2, the option differential, is a separate job and is not in this folder.",
        "",
        "## In plain English",
        "",
        "Similar Stock Difference (SSD) shorts the stock that ran ahead and buys the one that lagged. This test only changes when we get out: either when they are close again on a standard-deviation band, or when a fixed number of days runs out.",
        "",
        "The entry is frozen. A gap is a close at least 2 standard deviations off a 252-session ordinary least squares (OLS) line that stops the day before the signal.",
        "",
        "## Freeze",
        "",
        f"- Pair menu reused from `same_direction_pairs_gap_bt_2010_20260930/pairs_correlation.csv` ({n_pairs} pairs). Correlation was not rebuilt. Full window at least 0.60, each half at least 0.55.",
        "- Replay calendar ends 2026-09-30, the last session of the frozen books.",
        "- Entry |z| >= 2, 252-session OLS excluding the signal day, biggest absolute percent, one pair, next open, short high / long low, $10,000 a leg, whole shares.",
        "- Baseline A: exit when a later close is within 0.5 standard deviations of the frozen line, next open. No clock.",
        "- Baseline B: that 0.5 band, or the close of the 15th session, whichever comes first.",
        "- Time sweep, band fixed at 0.5: clocks 5, 10, 15, 20, 40. The 15-session cell is baseline B.",
        "- Band sweep, clock fixed at 15: bands 0.25, 0.5, 1.0, 1.5. The 0.5 cell is baseline B.",
        "- No cell was added after the results.",
        "- IS: entry_date < 2024-01-01. OOS: entry_date >= 2024-01-01. OOS is report-only.",
        "- Verdict vs baseline B on the in-sample marked book (closed IS exits, plus an IS entry still open at the last session before 2024 marked at that close).",
        f"- KEEP if marked average beats B by more than {KEEP_AVG_EDGE:.0f} point, win rate does not fall by more than {KEEP_WR_DROP_MAX:.0f} points, and marked count is at least {KEEP_N_RATIO_MIN:.0%} of B. Else HOLD within 1 point or if count/win-rate fails. DISMISS if marked average is worse by more than 1 point.",
        "- Median is reported and is not the verdict input.",
        "- Annualized rate of return uses `compare_format.ann_ror_from_closed` with brt_cash $10,000, the stake this book already uses. Max DD and Sharpe use the marked account path. Calmar is house Ann ROR / abs(path Max DD). Paul score and FIT are not on this book.",
        "- Calling the highest in-sample marked cell the best is in-sample selection. It is not adopted.",
        "",
        f"Highest in-sample marked average: {', '.join(best['names'])} at {best['avg']:+.2f}% on {best['n']} marked entries. Selection bias. Not adopted.",
        "",
        "## Results",
        "",
        "| Arm | Sweep | IS closed N | IS WR | IS avg | IS median | IS marked N | IS marked avg | OOS avg | Open at end | Verdict |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for arm in arms:
        ins = arm["samples"]["IS"]
        oos = arm["samples"]["OOS"]
        lines.append(
            f"| {arm['arm_id']} | {arm['family']} | {ins['n']} | {_md_pct(ins['win_pct'], 1)} | {_md_pct(ins['avg_pct'])} | "
            f"{_md_pct(ins['median_pct'])} | {arm['marked']['n']} | {_md_pct(arm['marked']['avg'])} | "
            f"{_md_pct(oos['avg_pct'])} | {arm['open_full']} | {arm['verdict']} |"
        )
    lines.extend(["", "## Why", ""])
    for arm in arms:
        lines.append(f"- **{arm['arm_id']} — {arm['verdict']}.** {arm['verdict_why']} {arm['oos_note']}")
    lines.extend(
        [
            "",
            "## Path dependence",
            "",
            "One pair at a time. An earlier exit changes which gap is taken next. HL/NEM and PNFP/ZION are listed in `focus_pairs.csv` and on the HTML page.",
            "",
            "The 2010 pairs folder and `thorp_timestop_and_chain_scan_20261001` were not overwritten.",
            "",
        ]
    )
    return "\n".join(lines)


def _best_cell(arms: list[dict]) -> dict:
    seen = {}
    for arm in arms:
        key = (arm["exit_z"], arm["clock"])
        seen.setdefault(key, []).append(arm)
    winner_key = max(seen, key=lambda k: seen[k][0]["marked"]["avg"])
    group = seen[winner_key]
    return {
        "names": [a["arm_id"] + " " + a["name"] for a in group],
        "avg": group[0]["marked"]["avg"],
        "n": group[0]["marked"]["n"],
        "ids": [a["arm_id"] for a in group],
    }


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, (np.floating, float)):
        if not np.isfinite(value):
            return None
        return float(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    return value


def main() -> None:
    bt = thorp._load_bt()
    menu = pd.read_csv(thorp.PAIR_MENU)
    menu["left"] = menu["left"].astype(str)
    menu["right"] = menu["right"].astype(str)
    menu["business"] = menu["business"].fillna("") if "business" in menu.columns else ""
    symbols = sorted(set(menu["left"]).union(set(menu["right"])))
    print(f"menu pairs {len(menu)} symbols {len(symbols)}", flush=True)
    close_wide, opens, _hits = thorp.load_prices(symbols, bt)
    panels = bt.build_panels(menu, close_wide, opens)
    panel_map = {(p["left"], p["right"]): p for p in panels}
    print("preparing signals", flush=True)
    best_on, gap_count, all_dates = thorp.prepare_signals(panels, bt)
    all_dates = [d for d in all_dates if pd.Timestamp(d) <= STUDY_END]
    best_on = {d: v for d, v in best_on.items() if pd.Timestamp(d) <= STUDY_END}
    print(f"replay calendar through {STUDY_END.date()} ({len(all_dates)} sessions)", flush=True)

    cache: dict[tuple, tuple] = {}
    packed = []
    for spec in GRID:
        key = (float(spec["exit_z"]), None if spec["clock"] is None else int(spec["clock"]))
        if key not in cache:
            print(f"replay z={key[0]} clock={key[1]}", flush=True)
            cache[key] = replay(panels, best_on, gap_count, all_dates, bt, key[0], key[1])
        trades, equity, _meta = cache[key]
        frame = thorp.trades_frame(trades)
        if spec["arm_id"] == "A":
            _assert_book(frame, PAIRS_CSV, "Baseline A")
        if spec["arm_id"] == "B":
            _assert_book(frame, CLOCK_CSV, "Baseline B")
        packed.append(pack_arm(spec, frame, trades, equity, panel_map, bt))

    base = next(arm for arm in packed if arm["arm_id"] == "B")
    for arm in packed:
        verdict, why = judge_vs_b(arm, base, arm["same_as"] == "B" or arm["arm_id"] == "B")
        arm["verdict"] = verdict
        arm["verdict_why"] = why
        arm["oos_note"] = _oos_note(arm, base)
        print(
            f"{arm['arm_id']} {verdict} closedIS {arm['samples']['IS']['n']} "
            f"avg {arm['samples']['IS']['avg_pct']:.2f} marked {arm['marked']['avg']:.2f} "
            f"oos {arm['samples']['OOS']['avg_pct']:.2f}",
            flush=True,
        )

    best = _best_cell(packed)
    focus = [row for arm in packed for row in focus_rows(arm)]
    summary = summary_rows(packed)
    OUT.mkdir(parents=True, exist_ok=True)
    summary.to_csv(OUT / "summary.csv", index=False)
    pd.DataFrame(focus).to_csv(OUT / "focus_pairs.csv", index=False)
    (OUT / "report.html").write_text(render(packed, base, focus, best), encoding="utf-8")
    (OUT / "BASELINE.md").write_text(baseline_md(packed, base, best, len(menu)), encoding="utf-8")
    slim = []
    for arm in packed:
        slim.append(
            {
                "arm_id": arm["arm_id"],
                "verdict": arm["verdict"],
                "verdict_why": arm["verdict_why"],
                "oos_note": arm["oos_note"],
                "marked": arm["marked"],
                "open_full": arm["open_full"],
                "IS": {k: arm["samples"]["IS"][k] for k in ("n", "win_pct", "avg_pct", "median_pct", "ann_ror")},
                "OOS": {k: arm["samples"]["OOS"][k] for k in ("n", "win_pct", "avg_pct", "median_pct")},
                "full": {k: arm["samples"]["full"][k] for k in ("n", "win_pct", "avg_pct", "median_pct")},
            }
        )
    (OUT / "summary.json").write_text(json.dumps(_jsonable({"best": best, "arms": slim}), indent=2), encoding="utf-8")
    print(f"wrote {OUT}", flush=True)
    print(f"BEST {best['ids']} marked {best['avg']:.2f} n {best['n']}", flush=True)


if __name__ == "__main__":
    main()
