#!/usr/bin/env python3
"""Replay the ten same-direction pairs: fade the widest gap, hold to alignment.

Research replay only. The pair menu was chosen on the full Sep 2022–Sep 2026
window, so which names are eligible is in-sample. Each day's gap, the entry,
and the exit use only prices known by that close, and the fill is the next open.
"""
from __future__ import annotations

import html
import importlib.util
import math
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
from compare_format import format_money  # noqa: E402

DB = ROOT / "data" / "ohlcv.duckdb"
OUT_DIR = ROOT / "drive" / "paul_experiments" / "same_direction_pairs_gap_bt_20260929"
OUT_HTML = OUT_DIR / "report.html"

TRADE_START = pd.Timestamp("2022-09-29")
IS_CUT = pd.Timestamp("2024-01-01")
LOOKBACK = 252
ENTRY_Z = 2.0
EXIT_Z = 0.5
STAKE = 10_000.0

PAIRS: list[tuple[str, str, str]] = [
    ("GOOG", "GOOGL", "Alphabet, two share classes"),
    ("FOX", "FOXA", "Fox, two share classes"),
    ("NWS", "NWSA", "News Corp, two share classes"),
    ("CPT", "MAA", "Apartment landlords"),
    ("PHM", "TOL", "Homebuilders"),
    ("AMAT", "LRCX", "Chipmaking equipment"),
    ("DHI", "LEN", "Homebuilders"),
    ("MLM", "VMC", "Crushed stone and aggregates"),
    ("KLAC", "LRCX", "Chipmaking equipment"),
    ("LEN", "PHM", "Homebuilders"),
]

ORIGINAL_REQUEST = (
    "can you run a backtest where we go back in time and identify the biggest gap "
    "each day and short the stock that is high and buy the stock that is low until "
    "the come together or near alignment. show me what stocks were bought/sold and "
    "when the poaitions were closed etc."
)


def _load_pairs_mod():
    path = ROOT / "tools" / "same_direction_pairs_20260929.py"
    spec = importlib.util.spec_from_file_location("same_direction_pairs_20260929", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = _load_pairs_mod()


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def load_bars(symbols: list[str]) -> dict[str, pd.DataFrame]:
    con = duckdb.connect(str(DB), read_only=True)
    try:
        frame = con.execute(
            """
            SELECT symbol, date, open, close
            FROM prices
            WHERE symbol IN (SELECT * FROM UNNEST(?))
              AND close > 0 AND open > 0
            """,
            [symbols],
        ).fetchdf()
    finally:
        con.close()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    out: dict[str, pd.DataFrame] = {}
    for symbol, group in frame.groupby("symbol", sort=False):
        bars = group.drop_duplicates("date").set_index("date").sort_index()
        close_adj, _hits = MOD.split_adjust(bars["close"].astype(float))
        # Same split scale the close adjustment applied, carried onto the open.
        scale = (close_adj / bars["close"].astype(float)).replace([np.inf, -np.inf], np.nan)
        open_adj = bars["open"].astype(float) * scale
        out[str(symbol)] = pd.DataFrame({"open": open_adj, "close": close_adj}).dropna()
    return out


def rolling_link(y: np.ndarray, x: np.ndarray) -> dict[str, np.ndarray]:
    n = len(y)
    z = np.full(n, np.nan)
    pct = np.full(n, np.nan)
    alpha = np.full(n, np.nan)
    beta = np.full(n, np.nan)
    center = np.full(n, np.nan)
    scale = np.full(n, np.nan)
    for i in range(LOOKBACK, n):
        xs = x[i - LOOKBACK : i]
        ys = y[i - LOOKBACK : i]
        if not (np.isfinite(xs).all() and np.isfinite(ys).all()):
            continue
        if not (np.isfinite(y[i]) and np.isfinite(x[i])):
            continue
        a, b, resid = MOD.ols_fit(xs, ys)
        mu = float(np.mean(resid))
        sd = float(np.std(resid, ddof=1))
        if not np.isfinite(sd) or sd <= 1e-12:
            continue
        resid_i = float(y[i] - (a + b * x[i]))
        z[i] = (resid_i - mu) / sd
        pct[i] = 100.0 * (math.exp(resid_i - mu) - 1.0)
        alpha[i] = a
        beta[i] = b
        center[i] = mu
        scale[i] = sd
    return {"z": z, "pct": pct, "alpha": alpha, "beta": beta, "center": center, "scale": scale}


def build_panels(bars: dict[str, pd.DataFrame]) -> dict[tuple[str, str], pd.DataFrame]:
    panels: dict[tuple[str, str], pd.DataFrame] = {}
    for left, right, _label in PAIRS:
        both = bars[left][["open", "close"]].join(
            bars[right][["open", "close"]], how="inner", lsuffix="_l", rsuffix="_r"
        ).dropna()
        both = both[(both["open_l"] > 0) & (both["open_r"] > 0)]
        sig = rolling_link(np.log(both["close_l"].to_numpy()), np.log(both["close_r"].to_numpy()))
        for key, arr in sig.items():
            both[key] = arr
        panels[(left, right)] = both
    return panels


def _frozen_z(panel: pd.DataFrame, date: pd.Timestamp, alpha: float, beta: float, center: float, scale: float) -> float:
    row = panel.loc[date]
    resid = float(math.log(row["close_l"]) - (alpha + beta * math.log(row["close_r"])))
    return (resid - center) / scale


def _leg_pnl(shares: int, entry: float, exit_px: float, side: str) -> float:
    if side == "long":
        return shares * (exit_px - entry)
    return shares * (entry - exit_px)


def run_backtest(panels: dict[tuple[str, str], pd.DataFrame]) -> tuple[list[dict], pd.DataFrame, dict]:
    all_dates = sorted(set().union(*[set(p.index) for p in panels.values()]))
    all_dates = [d for d in all_dates if d >= TRADE_START]
    by_pair_dates = {key: list(panel.index) for key, panel in panels.items()}

    position: dict | None = None
    pending_entry: dict | None = None
    pending_exit: dict | None = None
    trades: list[dict] = []
    gap_days = 0
    skipped_busy = 0
    equity_rows: list[dict] = []
    realized = 0.0
    last_unreal = 0.0

    def next_session(key: tuple[str, str], after: pd.Timestamp) -> pd.Timestamp | None:
        for d in by_pair_dates[key]:
            if d > after:
                return d
        return None

    def mark(pos: dict, date: pd.Timestamp, which: str) -> float:
        panel = panels[pos["key"]]
        if date not in panel.index:
            return None
        row = panel.loc[date]
        px_l = float(row["close_l"] if which == "close" else row["open_l"])
        px_r = float(row["close_r"] if which == "close" else row["open_r"])
        long_px = px_l if pos["long"] == pos["left"] else px_r
        short_px = px_l if pos["short"] == pos["left"] else px_r
        return _leg_pnl(pos["shares_long"], pos["entry_long"], long_px, "long") + _leg_pnl(
            pos["shares_short"], pos["entry_short"], short_px, "short"
        )

    for date in all_dates:
        if pending_exit is not None and position is not None and date >= pending_exit["fill_on"]:
            panel = panels[position["key"]]
            if date in panel.index:
                row = panel.loc[date]
                exit_long = float(row["open_l"] if position["long"] == position["left"] else row["open_r"])
                exit_short = float(row["open_l"] if position["short"] == position["left"] else row["open_r"])
                long_pnl = _leg_pnl(position["shares_long"], position["entry_long"], exit_long, "long")
                short_pnl = _leg_pnl(position["shares_short"], position["entry_short"], exit_short, "short")
                net = long_pnl + short_pnl
                realized += net
                z_exit = _frozen_z(
                    panel, pending_exit["signal_date"],
                    position["alpha"], position["beta"], position["center"], position["scale"],
                )
                trades.append({
                    **position,
                    "exit_date": date,
                    "exit_signal_date": pending_exit["signal_date"],
                    "exit_long": exit_long,
                    "exit_short": exit_short,
                    "long_pnl": long_pnl,
                    "short_pnl": short_pnl,
                    "net": net,
                    "z_exit": z_exit,
                    "closest_abs_z": position.get("closest_abs_z"),
                    "status": "closed",
                    "reason": "Back near the entry line",
                })
                position = None
                pending_exit = None

        if pending_entry is not None and position is None and date >= pending_entry["fill_on"]:
            panel = panels[pending_entry["key"]]
            if date in panel.index:
                row = panel.loc[date]
                entry_long = float(row["open_l"] if pending_entry["long"] == pending_entry["left"] else row["open_r"])
                entry_short = float(row["open_l"] if pending_entry["short"] == pending_entry["left"] else row["open_r"])
                shares_long = int(STAKE // entry_long) if entry_long > 0 else 0
                shares_short = int(STAKE // entry_short) if entry_short > 0 else 0
                if shares_long > 0 and shares_short > 0:
                    position = {
                        **pending_entry,
                        "entry_date": date,
                        "entry_long": entry_long,
                        "entry_short": entry_short,
                        "shares_long": shares_long,
                    "shares_short": shares_short,
                    "worst": None,
                    "closest_abs_z": None,
                }
                pending_entry = None

        if position is not None:
            panel = panels[position["key"]]
            if date in panel.index and date >= position["entry_date"]:
                mtm = mark(position, date, "close")
                if mtm is not None:
                    position["worst"] = mtm if position["worst"] is None else min(position["worst"], mtm)
                if pending_exit is None and date > position["entry_date"]:
                    z_now = _frozen_z(
                        panel, date, position["alpha"], position["beta"], position["center"], position["scale"]
                    )
                    if np.isfinite(z_now):
                        position["closest_abs_z"] = (
                            abs(z_now) if position["closest_abs_z"] is None else min(position["closest_abs_z"], abs(z_now))
                        )
                    if np.isfinite(z_now) and abs(z_now) <= EXIT_Z:
                        fill_on = next_session(position["key"], date)
                        if fill_on is not None:
                            pending_exit = {"signal_date": date, "fill_on": fill_on, "z": z_now}

        if position is None and pending_entry is None and pending_exit is None:
            best = None
            for key, panel in panels.items():
                if date not in panel.index:
                    continue
                row = panel.loc[date]
                z = float(row["z"])
                pct = float(row["pct"])
                if not (np.isfinite(z) and np.isfinite(pct)):
                    continue
                if abs(z) < ENTRY_Z:
                    continue
                if best is None or abs(pct) > best["abs_pct"]:
                    left, right = key
                    if pct >= 0:
                        short_sym, long_sym = left, right
                    else:
                        short_sym, long_sym = right, left
                    best = {
                        "key": key,
                        "left": left,
                        "right": right,
                        "label": next(lb for a, b, lb in PAIRS if (a, b) == key),
                        "long": long_sym,
                        "short": short_sym,
                        "signal_date": date,
                        "z_entry": z,
                        "pct_entry": pct,
                        "abs_pct": abs(pct),
                        "alpha": float(row["alpha"]),
                        "beta": float(row["beta"]),
                        "center": float(row["center"]),
                        "scale": float(row["scale"]),
                    }
            if best is not None:
                gap_days += 1
                fill_on = next_session(best["key"], date)
                if fill_on is not None:
                    best["fill_on"] = fill_on
                    pending_entry = best
        elif position is not None or pending_entry is not None or pending_exit is not None:
            # Count days a fresh gap existed but the book was already committed.
            saw = False
            for panel in panels.values():
                if date not in panel.index:
                    continue
                z = float(panel.at[date, "z"])
                if np.isfinite(z) and abs(z) >= ENTRY_Z:
                    saw = True
                    break
            if saw and position is not None:
                skipped_busy += 1

        unreal = 0.0
        if position is not None:
            marked = mark(position, date, "close")
            if marked is None:
                marked = last_unreal
            else:
                last_unreal = marked
            unreal = marked
        else:
            last_unreal = 0.0
        equity_rows.append({
            "date": date,
            "equity": STAKE + realized + unreal,
            "in_trade": position is not None,
        })

    if position is not None:
        panel = panels[position["key"]]
        last = panel.index[panel.index <= all_dates[-1]][-1]
        row = panel.loc[last]
        exit_long = float(row["close_l"] if position["long"] == position["left"] else row["close_r"])
        exit_short = float(row["close_l"] if position["short"] == position["left"] else row["close_r"])
        long_pnl = _leg_pnl(position["shares_long"], position["entry_long"], exit_long, "long")
        short_pnl = _leg_pnl(position["shares_short"], position["entry_short"], exit_short, "short")
        z_exit = _frozen_z(
            panel, last, position["alpha"], position["beta"], position["center"], position["scale"]
        )
        reason = "Still open at the last price"
        if pending_exit is not None:
            reason = "Lined up on the last signal day; the next open is not in the file yet"
        trades.append({
            **position,
            "exit_date": pd.NaT,
            "mark_date": last,
            "exit_signal_date": pending_exit["signal_date"] if pending_exit else pd.NaT,
            "exit_long": exit_long,
            "exit_short": exit_short,
            "long_pnl": long_pnl,
            "short_pnl": short_pnl,
            "net": long_pnl + short_pnl,
            "z_exit": z_exit,
            "closest_abs_z": position.get("closest_abs_z"),
            "status": "open",
            "reason": reason,
        })

    equity = pd.DataFrame(equity_rows)
    meta = {"gap_days_taken": gap_days, "days_busy_with_a_gap": skipped_busy, "days": len(all_dates)}
    return trades, equity, meta


def _days_held(entry: pd.Timestamp, exit_date: pd.Timestamp) -> int | None:
    if pd.isna(exit_date):
        return None
    return int((pd.Timestamp(exit_date) - pd.Timestamp(entry)).days)


def _metrics(closed: list[dict]) -> dict:
    if not closed:
        return {"n": 0, "wins": 0, "win_pct": float("nan"), "avg_pct": float("nan"),
                "median_pct": float("nan"), "avg_win": float("nan"), "avg_loss": float("nan"),
                "pf": float("nan"), "total": 0.0, "avg_days": float("nan"), "median_days": float("nan")}
    nets = np.array([t["net"] for t in closed], dtype=float)
    pcts = nets / STAKE * 100.0
    days = np.array([_days_held(t["entry_date"], t["exit_date"]) for t in closed], dtype=float)
    wins = nets[nets > 0]
    losses = nets[nets <= 0]
    gross_win = float(wins.sum()) if len(wins) else 0.0
    gross_loss = float(-losses.sum()) if len(losses) else 0.0
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf") if gross_win > 0 else float("nan")
    return {
        "n": int(len(closed)),
        "wins": int((nets > 0).sum()),
        "win_pct": 100.0 * float((nets > 0).mean()),
        "avg_pct": float(np.mean(pcts)),
        "median_pct": float(np.median(pcts)),
        "avg_win": float(np.mean(wins) / STAKE * 100.0) if len(wins) else float("nan"),
        "avg_loss": float(np.mean(losses) / STAKE * 100.0) if len(losses) else float("nan"),
        "pf": float(pf) if np.isfinite(pf) else float("nan"),
        "total": float(nets.sum()),
        "avg_days": float(np.mean(days)),
        "median_days": float(np.median(days)),
    }


def _equity_stats(equity: pd.DataFrame) -> dict:
    if equity.empty:
        return {"max_dd": float("nan"), "ann": float("nan"), "sharpe": float("nan"), "end": STAKE}
    eq = equity["equity"].to_numpy(dtype=float)
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    max_dd = float(dd.min() * 100.0)
    start_d = pd.Timestamp(equity["date"].iloc[0])
    end_d = pd.Timestamp(equity["date"].iloc[-1])
    years = max((end_d - start_d).days / 365.0, 1 / 365)
    ann = float((eq[-1] / STAKE) ** (1.0 / years) - 1.0) * 100.0 if eq[-1] > 0 else float("nan")
    rets = pd.Series(eq).pct_change().dropna()
    if len(rets) > 5 and float(rets.std(ddof=1)) > 0:
        sharpe = float(rets.mean() / rets.std(ddof=1) * math.sqrt(252))
    else:
        sharpe = float("nan")
    return {"max_dd": max_dd, "ann": ann, "sharpe": sharpe, "end": float(eq[-1])}


def _fmt_pct(value: float) -> str:
    if value is None or not np.isfinite(value):
        return "—"
    return f"{value:+.1f}%"


def _fmt_px(value: float) -> str:
    if value is None or not np.isfinite(value):
        return "—"
    return f"{value:,.2f}"


def _fmt_z(value: float) -> str:
    if value is None or not np.isfinite(value):
        return "—"
    return f"{value:+.2f}"


def _th(label: str, sort: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{_esc(label)}<span class="sort-ind"></span></th>'
    )


def _kv_table(rows: list[tuple[str, str]]) -> str:
    body = "".join(f"<tr><td>{_esc(a)}</td><td>{b}</td></tr>" for a, b in rows)
    return (
        '<div class="table-wrap"><table class="sortable"><caption>Click column headers to sort.</caption>'
        "<thead><tr>" + _th("Item", "text") + _th("Value", "text") + f"</tr></thead><tbody>{body}</tbody></table></div>"
    )


def _metric_rows(title: str, stats: dict) -> list[tuple[str, str]]:
    return [
        (f"{title} trades", str(stats["n"])),
        (f"{title} wins", f"{stats['wins']} ({_fmt_pct(stats['win_pct']).replace('+', '')})"),
        (f"{title} average result on the $10,000 stake", _fmt_pct(stats["avg_pct"])),
        (f"{title} median result", _fmt_pct(stats["median_pct"])),
        (f"{title} average winner", _fmt_pct(stats["avg_win"])),
        (f"{title} average loser", _fmt_pct(stats["avg_loss"])),
        (f"{title} profit factor", "no losing trades" if stats["n"] and stats["wins"] == stats["n"] else ("—" if not np.isfinite(stats["pf"]) else f"{stats['pf']:.2f}")),
        (f"{title} net", format_money(stats["total"])),
        (f"{title} average calendar days held", "—" if not np.isfinite(stats["avg_days"]) else f"{stats['avg_days']:.0f}"),
        (f"{title} median calendar days held", "—" if not np.isfinite(stats["median_days"]) else f"{stats['median_days']:.0f}"),
    ]


def write_report(trades: list[dict], equity: pd.DataFrame, meta: dict) -> None:
    closed = [t for t in trades if t["status"] == "closed"]
    still = [t for t in trades if t["status"] == "open"]
    full = _metrics(closed)
    is_stats = _metrics([t for t in closed if pd.Timestamp(t["entry_date"]) < IS_CUT])
    oos_stats = _metrics([t for t in closed if pd.Timestamp(t["entry_date"]) >= IS_CUT])
    eq_stats = _equity_stats(equity)
    last = pd.Timestamp(equity["date"].iloc[-1]).date().isoformat() if not equity.empty else "—"

    headers = [
        ("#", "num"), ("Pair", "text"), ("Signal", "text"), ("Bought on", "text"), ("Closed on", "text"),
        ("Bought", "text"), ("Shares bought", "num"), ("Buy price", "num"), ("Sold long at", "num"),
        ("Shorted", "text"), ("Shares short", "num"), ("Short sale", "num"), ("Covered at", "num"),
        ("Gap at signal (z)", "num"), ("Gap at signal", "num"), ("Gap at exit or last mark (z)", "num"),
        ("Closest it got", "num"),
        ("Days held", "num"), ("Long result", "num"), ("Short result", "num"), ("Net", "num"),
        ("Net on $10k stake", "num"), ("Worst open net", "num"), ("Why it ended", "text"),
    ]
    body = []
    running = 0.0
    for i, t in enumerate(trades, start=1):
        running_show = t["net"] if t["status"] == "closed" else float("nan")
        if t["status"] == "closed":
            running += t["net"]
        exit_label = pd.Timestamp(t["exit_date"]).date().isoformat() if t["status"] == "closed" else "Still open"
        held = _days_held(t["entry_date"], t["exit_date"] if t["status"] == "closed" else t["mark_date"])
        cls = ' class="open-row"' if t["status"] == "open" else ""
        cells = [
            str(i),
            f"{t['left']} / {t['right']}",
            pd.Timestamp(t["signal_date"]).date().isoformat(),
            pd.Timestamp(t["entry_date"]).date().isoformat(),
            exit_label,
            t["long"],
            str(t["shares_long"]),
            _fmt_px(t["entry_long"]),
            _fmt_px(t["exit_long"]),
            t["short"],
            str(t["shares_short"]),
            _fmt_px(t["entry_short"]),
            _fmt_px(t["exit_short"]),
            _fmt_z(t["z_entry"]),
            _fmt_pct(t["pct_entry"]),
            _fmt_z(t["z_exit"]),
            "—" if t.get("closest_abs_z") is None else f"{t['closest_abs_z']:.2f}",
            "—" if held is None else str(held),
            format_money(t["long_pnl"]),
            format_money(t["short_pnl"]),
            format_money(t["net"]),
            _fmt_pct(t["net"] / STAKE * 100.0),
            format_money(t["worst"]),
            t["reason"],
        ]
        _ = running_show
        tds = "".join(
            f'<td class="num">{_esc(c)}</td>' if n not in (1, 5, 9, 23) else f"<td>{_esc(c)}</td>"
            for n, c in enumerate(cells)
        )
        body.append(f"<tr{cls}>{tds}</tr>")

    head = "".join(_th(label, sort) for label, sort in headers)
    table = (
        '<div class="table-wrap"><table class="sortable">'
        "<caption>Click column headers to sort. One row is one round trip. "
        "The open row, if any, is marked to the last close and is not a finished trade. "
        "“Gap at signal” is the first ticker versus the prior-year line, in percent. "
        "Positive means the first ticker was the expensive one.</caption>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )

    summary_rows = _metric_rows("Closed", full) + [
        ("Account at the end, $10,000 stake plus closed and open marks", format_money(eq_stats["end"])),
        ("Worst peak-to-trough drop of that account", _fmt_pct(eq_stats["max_dd"])),
        ("Yearly pace of that account", _fmt_pct(eq_stats["ann"])),
        ("Sharpe of daily account changes (descriptive, rf = 0)", "—" if not np.isfinite(eq_stats["sharpe"]) else f"{eq_stats['sharpe']:.2f}"),
        ("Days scanned", str(meta["days"])),
        ("Days a new gap was taken", str(meta["gap_days_taken"])),
        ("Days a gap was already on the board while a trade was open", str(meta["days_busy_with_a_gap"])),
        ("Still open", str(len(still))),
    ]
    split_rows = _metric_rows("Earlier entries (before 2024)", is_stats) + _metric_rows(
        "Later entries (2024 on)", oos_stats
    )

    open_note = ""
    if still:
        t = still[-1]
        held = _days_held(t["entry_date"], t["mark_date"])
        closest = "—" if t.get("closest_abs_z") is None else f"{t['closest_abs_z']:.2f}"
        open_note = (
            f" Bought {t['long']} and shorted {t['short']} on {pd.Timestamp(t['entry_date']).date().isoformat()}, "
            f"and that position is still open after {held} calendar days. "
            f"Marked to the last price it is {format_money(t['net'])}. "
            f"The closest the frozen gap got was {closest} wiggles, and it has to reach {EXIT_Z:.1f} before the rule closes it. "
            f"While it is open, no new pair is taken."
        )
    if full["n"] == 0 and not still:
        lead = "The rule never found a gap wide enough to trade."
        lead_class = "warn"
    else:
        end_vs = eq_stats["end"] - STAKE
        change = ("+" + format_money(end_vs)) if end_vs >= 0 else format_money(end_vs)
        lead = (
            f"{full['n']} trades finished, for a combined {format_money(full['total'])} "
            f"({_fmt_pct(full['avg_pct'])} average on the $10,000 stake). "
            f"With the open mark included, the account sits at {format_money(eq_stats['end'])} "
            f"({change} versus the starting stake)."
            + open_note
        )
        lead_class = "ok" if end_vs > 0 else "bad"

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Gap fade backtest — {last}</title>
  <style>{MOD.CSS}
  tr.open-row td {{ background: var(--warn-bg); }}
  .wrap {{ max-width: 1280px; }}
  </style>
</head>
<body>
<div class="wrap">
  <header class="doc-head">
    <p class="eyebrow">Research replay · not a live system</p>
    <h1>Buy the cheap side, short the rich side, hold until they line up</h1>
    <p class="lede">Signals from {TRADE_START.date().isoformat()} through {last}. Fills at the next open. Stake about ${STAKE:,.0f} on each leg, whole shares.</p>
  </header>

  <div class="callout">
    <strong>What you asked.</strong>
    <p>{_esc(ORIGINAL_REQUEST)}</p>
    <strong>In plain English.</strong>
    <p>Using the ten pairs that have moved together for years, we walked forward one day at a time. On any day we had no trade open, we looked for the pair that was furthest apart in price, but only if that gap was also statistically wide (at least two normal wiggles). We bought the cheap stock and shorted the expensive one. We kept that bet until the two prices came back near the line we used on entry day (within half a wiggle). Then we closed both sides. We did not flip to a new pair while one was still open.</p>
  </div>

  <div class="callout {lead_class}">
    <strong>Result.</strong>
    <p>{lead}</p>
  </div>

  <div class="callout warn">
    <strong>How to read this.</strong>
    <p>The list of ten pairs was chosen with the full September 2022–September 2026 history in hand, so the menu itself peeks at the years being traded. Once that menu is frozen, each day’s gap uses only the prior {LOOKBACK} sessions, and the order fills the next morning. Entries before 1 Jan 2024 and entries from that date on are both shown. The later block is not a clean holdout of the pair list, and nothing here was retuned after seeing it. Dividends and the cost of borrowing shares for the short are not in the dollars. This is not wired to DailyRun.</p>
  </div>

  <h2>The rule that was frozen</h2>
  <ul>
    <li>Menu: the ten pairs from the same-direction study. No other stocks.</li>
    <li>Each day, fit last year’s line on the prior {LOOKBACK} closes, stopping the day before the signal. A gap counts when the latest close is at least {ENTRY_Z:.0f} wiggles off that line.</li>
    <li>If several pairs qualify, take the one with the largest percent gap. Short the high one, buy the low one, about ${STAKE:,.0f} of whole shares each side.</li>
    <li>The line is then frozen. Exit when a later close is within {EXIT_Z:.1f} wiggles of that same line. Sell the long and cover the short at the next open.</li>
    <li>One pair at a time. No time limit. No stop was added beyond “wait until they line up.”</li>
  </ul>

  <h2>Account summary</h2>
  {_kv_table(summary_rows)}

  <h2>Entries before 2024, and entries from 2024 on</h2>
  <p>Split by the day the shares were bought. The pair menu was not re-picked on the later block.</p>
  {_kv_table(split_rows)}

  <h2>Every position</h2>
  {table}

  <footer>
    Written {pd.Timestamp.now().strftime("%Y-%m-%d")} · stamp same_direction_pairs_gap_bt_20260929 · source tools/same_direction_pairs_gap_bt_20260929.py
  </footer>
</div>
{MOD.SORT_JS}
</body>
</html>
"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(page, encoding="utf-8")
    lines = [
        "# Gap-fade replay",
        "",
        "Research only. Not DailyRun.",
        "",
        "## Original request",
        "",
        f"> {ORIGINAL_REQUEST}",
        "",
        "## In plain English",
        "",
        "Each day the book was flat, buy the cheap stock and short the expensive stock in the widest qualifying pair, and hold until that pair lined back up.",
        "",
        "## Freeze",
        "",
        f"- Pairs: the ten from same_direction_pairs_20260929 (full-window selection; labeled in-sample).",
        f"- Trade window: {TRADE_START.date()} through last price.",
        f"- Entry |z| >= {ENTRY_Z} on a {LOOKBACK}-session line that excludes the signal day. Biggest |percent| wins.",
        f"- Exit |z| <= {EXIT_Z} on the frozen entry line. Fill next open.",
        f"- One position. Stake ${STAKE:.0f} per leg, whole shares. No dividends, borrow, or commission.",
        f"- Closed trades: {full['n']}. Average stake result: {full['avg_pct'] if full['n'] else float('nan'):.2f}%.",
        "",
    ]
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    symbols = sorted({s for pair in PAIRS for s in pair[:2]})
    bars = load_bars(symbols)
    missing = [s for s in symbols if s not in bars]
    if missing:
        raise SystemExit(f"Missing prices for {missing}")
    panels = build_panels(bars)
    trades, equity, meta = run_backtest(panels)
    write_report(trades, equity, meta)
    print(f"trades {len(trades)} wrote {OUT_HTML}")
    for i, t in enumerate(trades, start=1):
        exit_d = t["exit_date"] if t["status"] == "closed" else "OPEN"
        print(
            f"{i:02d} {t['status']:6} signal {pd.Timestamp(t['signal_date']).date()} "
            f"in {pd.Timestamp(t['entry_date']).date()} out {exit_d} "
            f"BUY {t['long']} x{t['shares_long']} @{t['entry_long']:.2f}->{t['exit_long']:.2f} "
            f"SHORT {t['short']} x{t['shares_short']} @{t['entry_short']:.2f}->{t['exit_short']:.2f} "
            f"z {t['z_entry']:+.2f} closest {t.get('closest_abs_z')} pct {t['pct_entry']:+.1f} net {t['net']:.2f} {t['reason']}"
        )


if __name__ == "__main__":
    main()
