#!/usr/bin/env python3
"""15-session time stop on the frozen 2010 pairs book, plus one option-chain day.

Research only. Not gold. Not DailyRun. Does not change the 2010 pair menu.
"""
from __future__ import annotations

import html
import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
from compare_format import ann_ror_from_closed, format_money  # noqa: E402

OUT = ROOT / "drive" / "paul_experiments" / "thorp_timestop_and_chain_scan_20261001"
PAIRS_CSV = (
    ROOT
    / "drive"
    / "paul_experiments"
    / "same_direction_pairs_gap_bt_2010_20260930"
    / "trades.csv"
)
PAIR_MENU = (
    ROOT
    / "drive"
    / "paul_experiments"
    / "same_direction_pairs_gap_bt_2010_20260930"
    / "pairs_correlation.csv"
)
CHAIN = ROOT / "data" / "options" / "yfinance_chain" / "2026-09-30" / "chain.parquet"
DB = ROOT / "data" / "ohlcv.duckdb"

IS_CUT = pd.Timestamp("2024-01-01")
SCAN_DAY = pd.Timestamp("2026-09-30")
STAKE = 10_000.0
EXIT_Z = 0.5
MAX_SESSIONS = 15
# Frozen before any leftover is ranked. Not chosen from rich/cheap names.
LIQ_VOLUME_MIN = 10
LIQ_OI_MIN = 100

ORIGINAL_REQUEST = (
    "CAN WE RUN ANOTHER TEST NOW THAT WE HAVE MORE STOCK AND OPTIONS PRICES? "
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "thorp_options_data_feasibility_20260930/feasibility.html"
)


def _load_bt():
    path = ROOT / "tools" / "same_direction_pairs_gap_bt_2010_20260930.py"
    spec = importlib.util.spec_from_file_location("pairs_2010", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


def _num(value: float, digits: int = 2) -> str:
    if value is None or not np.isfinite(value):
        return "—"
    return f"{value:,.{digits}f}"


def _px(value: float) -> str:
    if value is None or not np.isfinite(value):
        return "—"
    return f"{value:,.2f}"


def _iso(value) -> str:
    if value is None or pd.isna(value):
        return ""
    return pd.Timestamp(value).date().isoformat()


def _pf_text(pf: float, wins: int, n: int) -> str:
    if n and wins == n and not np.isfinite(pf):
        return "no losing trades"
    if pf is None or not np.isfinite(pf):
        return "—"
    return f"{pf:.2f}"


def load_prices(symbols: list[str], bt) -> tuple[pd.DataFrame, dict[str, pd.Series], int]:
    con = __import__("duckdb").connect(str(DB), read_only=True)
    try:
        con.register("want", pd.DataFrame({"symbol": symbols}))
        raw = con.execute(
            """
            SELECT p.symbol, p.date, p.open, p.close
            FROM prices p
            INNER JOIN want w ON p.symbol = w.symbol
            WHERE p.close IS NOT NULL AND p.close > 0
              AND p.date >= DATE '2010-01-01'
            """
        ).fetchdf()
    finally:
        con.close()
    raw["date"] = pd.to_datetime(raw["date"])
    raw["symbol"] = raw["symbol"].astype(str).str.upper()
    raw = raw.drop_duplicates(["symbol", "date"], keep="first")
    closes: dict[str, pd.Series] = {}
    opens: dict[str, pd.Series] = {}
    hits = 0
    for symbol, group in raw.groupby("symbol", sort=False):
        adj, open_adj, n_hits = bt.adjust_symbol(group)
        closes[str(symbol)] = adj
        opens[str(symbol)] = open_adj
        hits += n_hits
    close_wide = pd.DataFrame(closes).sort_index()
    close_wide = close_wide.loc[close_wide.index >= bt.WINDOW_START]
    print(f"prices {len(raw)} rows, {close_wide.shape[1]} symbols, split fixes {hits}", flush=True)
    return close_wide, opens, hits


def prepare_signals(panels: list[dict], bt) -> tuple[dict, dict, list]:
    all_dates = sorted(set().union(*[set(p["dates"]) for p in panels])) if panels else []
    all_dates = [pd.Timestamp(d) for d in all_dates if pd.Timestamp(d) >= bt.WINDOW_START]
    best_on: dict[pd.Timestamp, tuple] = {}
    gap_count: dict[pd.Timestamp, int] = {}
    for n, panel in enumerate(panels, start=1):
        z = panel["z"]
        pct = panel["pct"]
        for i, d in enumerate(panel["dates"]):
            d = pd.Timestamp(d)
            if d < bt.WINDOW_START:
                continue
            zi = float(z[i])
            pi = float(pct[i])
            if not (np.isfinite(zi) and np.isfinite(pi)):
                continue
            if abs(zi) < bt.ENTRY_Z:
                continue
            gap_count[d] = gap_count.get(d, 0) + 1
            ap = abs(pi)
            cur = best_on.get(d)
            if cur is None or ap > cur[0]:
                best_on[d] = (ap, panel, i, zi, pi)
        if n % 400 == 0:
            print(f"signals scanned {n} panels", flush=True)
    print(f"signal days {len(best_on)}", flush=True)
    return best_on, gap_count, all_dates


def replay(panels: list[dict], best_on: dict, gap_count: dict, all_dates: list, bt, clock: int | None) -> tuple[list[dict], pd.DataFrame, dict]:
    position: dict | None = None
    pending_entry: dict | None = None
    pending_exit: dict | None = None
    trades: list[dict] = []
    gap_days = 0
    skipped_busy = 0
    equity_rows: list[dict] = []
    realized = 0.0
    last_unreal = 0.0

    def mark(pos: dict, date: pd.Timestamp) -> float | None:
        panel = pos["panel"]
        i = bt._at(panel, date)
        if i is None:
            return None
        long_px, short_px = bt._side_prices(panel, i, "close", pos["long"], pos["short"], pos["left"])
        return bt._leg_pnl(pos["shares_long"], pos["entry_long"], long_px, "long") + bt._leg_pnl(
            pos["shares_short"], pos["entry_short"], short_px, "short"
        )

    def finish(pos: dict, date: pd.Timestamp, which: str, reason: str, z_exit: float, signal_date) -> None:
        nonlocal position, pending_exit, realized
        panel = pos["panel"]
        i = bt._at(panel, date)
        long_px, short_px = bt._side_prices(panel, i, which, pos["long"], pos["short"], pos["left"])
        long_pnl = bt._leg_pnl(pos["shares_long"], pos["entry_long"], long_px, "long")
        short_pnl = bt._leg_pnl(pos["shares_short"], pos["entry_short"], short_px, "short")
        realized += long_pnl + short_pnl
        trades.append(
            {
                **{k: v for k, v in pos.items() if k != "panel"},
                "exit_date": date,
                "exit_i": i,
                "exit_which": which,
                "exit_signal_date": signal_date,
                "exit_long": long_px,
                "exit_short": short_px,
                "long_pnl": long_pnl,
                "short_pnl": short_pnl,
                "net": long_pnl + short_pnl,
                "z_exit": z_exit,
                "status": "closed",
                "reason": reason,
            }
        )
        position = None
        pending_exit = None

    for date in all_dates:
        if pending_exit is not None and position is not None and date >= pending_exit["fill_on"]:
            z_exit = bt._frozen_z(
                position["panel"],
                pending_exit["signal_date"],
                position["alpha"],
                position["beta"],
                position["center"],
                position["scale"],
            )
            finish(position, date, "open", "Back near the entry line", z_exit, pending_exit["signal_date"])

        if pending_entry is not None and position is None and date >= pending_entry["fill_on"]:
            panel = pending_entry["panel"]
            i = bt._at(panel, date)
            if i is not None:
                long_px, short_px = bt._side_prices(
                    panel, i, "open", pending_entry["long"], pending_entry["short"], pending_entry["left"]
                )
                shares_long = int(STAKE // long_px) if long_px > 0 else 0
                shares_short = int(STAKE // short_px) if short_px > 0 else 0
                if shares_long > 0 and shares_short > 0:
                    position = {
                        **pending_entry,
                        "entry_date": date,
                        "entry_i": i,
                        "entry_long": long_px,
                        "entry_short": short_px,
                        "shares_long": shares_long,
                        "shares_short": shares_short,
                        "worst": None,
                        "closest_abs_z": None,
                    }
            pending_entry = None

        if position is not None:
            panel = position["panel"]
            i = bt._at(panel, date)
            if i is not None and date >= position["entry_date"]:
                mtm = mark(position, date)
                if mtm is not None:
                    position["worst"] = mtm if position["worst"] is None else min(position["worst"], mtm)
                if date > position["entry_date"]:
                    z_now = bt._frozen_z(
                        panel, date, position["alpha"], position["beta"], position["center"], position["scale"]
                    )
                    if np.isfinite(z_now):
                        position["closest_abs_z"] = (
                            abs(z_now)
                            if position["closest_abs_z"] is None
                            else min(position["closest_abs_z"], abs(z_now))
                        )
                    sessions_after = i - position["entry_i"]
                    clock_due = clock is not None and sessions_after >= clock
                    future_cover = pending_exit is not None and pending_exit["fill_on"] > date
                    if clock_due and (pending_exit is None or future_cover):
                        finish(
                            position,
                            date,
                            "close",
                            "15-session time stop",
                            z_now,
                            date,
                        )
                    elif pending_exit is None and np.isfinite(z_now) and abs(z_now) <= EXIT_Z:
                        fill_on = bt._next_session(panel, date)
                        if fill_on is not None:
                            pending_exit = {"signal_date": date, "fill_on": fill_on, "z": z_now}

        if position is None and pending_entry is None and pending_exit is None:
            found = best_on.get(date)
            if found is not None:
                _ap, panel, i, zi, pi = found
                gap_days += 1
                if pi >= 0:
                    short_sym, long_sym = panel["left"], panel["right"]
                else:
                    short_sym, long_sym = panel["right"], panel["left"]
                fill_on = bt._next_session(panel, date)
                if fill_on is not None:
                    pending_entry = {
                        "panel": panel,
                        "left": panel["left"],
                        "right": panel["right"],
                        "label": panel["label"],
                        "long": long_sym,
                        "short": short_sym,
                        "signal_date": date,
                        "z_entry": zi,
                        "pct_entry": pi,
                        "abs_pct": abs(pi),
                        "alpha": float(panel["alpha"][i]),
                        "beta": float(panel["beta"][i]),
                        "center": float(panel["center"][i]),
                        "scale": float(panel["scale"][i]),
                        "fill_on": fill_on,
                    }
        elif position is not None and date in gap_count:
            skipped_busy += 1

        unreal = 0.0
        if position is not None:
            marked = mark(position, date)
            if marked is None:
                marked = last_unreal
            else:
                last_unreal = marked
            unreal = marked
        else:
            last_unreal = 0.0
        equity_rows.append({"date": date, "equity": STAKE + realized + unreal, "in_trade": position is not None})

    if position is not None and all_dates:
        panel = position["panel"]
        last = max(d for d in panel["dates"] if pd.Timestamp(d) <= all_dates[-1])
        i = bt._at(panel, pd.Timestamp(last))
        long_px, short_px = bt._side_prices(panel, i, "close", position["long"], position["short"], position["left"])
        long_pnl = bt._leg_pnl(position["shares_long"], position["entry_long"], long_px, "long")
        short_pnl = bt._leg_pnl(position["shares_short"], position["entry_short"], short_px, "short")
        z_exit = bt._frozen_z(
            panel, pd.Timestamp(last), position["alpha"], position["beta"], position["center"], position["scale"]
        )
        reason = "Still open at the last price"
        if pending_exit is not None:
            reason = "Lined up on the last signal day; the next open is not in the file yet"
        trades.append(
            {
                **{k: v for k, v in position.items() if k != "panel"},
                "exit_date": pd.NaT,
                "mark_date": pd.Timestamp(last),
                "exit_i": i,
                "exit_which": "close",
                "exit_signal_date": pending_exit["signal_date"] if pending_exit else pd.NaT,
                "exit_long": long_px,
                "exit_short": short_px,
                "long_pnl": long_pnl,
                "short_pnl": short_pnl,
                "net": long_pnl + short_pnl,
                "z_exit": z_exit,
                "status": "open",
                "reason": reason,
            }
        )

    equity = pd.DataFrame(equity_rows)
    meta = {
        "gap_days_taken": gap_days,
        "days_busy_with_a_gap": skipped_busy,
        "days": len(all_dates),
    }
    return trades, equity, meta


def sessions_after(trade: dict) -> int | None:
    exit_i = trade.get("exit_i")
    entry_i = trade.get("entry_i")
    if exit_i is None or entry_i is None:
        return None
    return int(exit_i) - int(entry_i)


def trades_frame(trades: list[dict]) -> pd.DataFrame:
    rows = []
    for i, t in enumerate(trades, start=1):
        exit_for_days = t["exit_date"] if t["status"] == "closed" else t.get("mark_date")
        entry = pd.Timestamp(t["entry_date"])
        rows.append(
            {
                "n": i,
                "status": t["status"],
                "sample": "IS" if entry < IS_CUT else "OOS",
                "left": t["left"],
                "right": t["right"],
                "signal_date": _iso(t["signal_date"]),
                "entry_date": _iso(t["entry_date"]),
                "exit_date": _iso(t["exit_date"]) if t["status"] == "closed" else "",
                "mark_date": _iso(t.get("mark_date")) if t["status"] != "closed" else "",
                "long": t["long"],
                "short": t["short"],
                "shares_long": t["shares_long"],
                "shares_short": t["shares_short"],
                "entry_long": t["entry_long"],
                "entry_short": t["entry_short"],
                "exit_long": t["exit_long"],
                "exit_short": t["exit_short"],
                "z_entry": t["z_entry"],
                "z_exit": t["z_exit"],
                "closest_abs_z": t.get("closest_abs_z"),
                "sessions_after_entry": sessions_after(t),
                "days_held": None if pd.isna(exit_for_days) else int((pd.Timestamp(exit_for_days) - entry).days),
                "long_pnl": t["long_pnl"],
                "short_pnl": t["short_pnl"],
                "net": t["net"],
                "net_pct": t["net"] / STAKE * 100.0,
                "worst": t.get("worst"),
                "reason": t["reason"],
                "exit_which": t.get("exit_which") or "",
            }
        )
    return pd.DataFrame(rows)


def assert_control(frame: pd.DataFrame) -> None:
    published = pd.read_csv(PAIRS_CSV)
    if len(frame) != len(published):
        raise SystemExit(f"Control trade count {len(frame)} != published {len(published)}")
    for i, pub in published.iterrows():
        got = frame.iloc[i]
        for col in ("left", "right", "long", "short", "signal_date", "entry_date", "status"):
            if str(got[col]) != str(pub[col]):
                raise SystemExit(f"Control {col} row {i}: {got[col]} != {pub[col]}")
        if str(pub["status"]) == "closed" and str(got["exit_date"]) != str(pub["exit_date"]):
            raise SystemExit(f"Control exit_date row {i}: {got['exit_date']} != {pub['exit_date']}")
        if abs(float(got["entry_long"]) - float(pub["entry_long"])) > 0.02:
            raise SystemExit(f"Control entry_long row {i}: {got['entry_long']} != {pub['entry_long']}")
        if abs(float(got["entry_short"]) - float(pub["entry_short"])) > 0.02:
            raise SystemExit(f"Control entry_short row {i}: {got['entry_short']} != {pub['entry_short']}")
        # The closed trade is history. The open mark uses the latest warehouse close,
        # which can move a few cents after the published CSV was written.
        tol = 0.05 if str(pub["status"]) == "closed" else 5.0
        if abs(float(got["net_pct"]) - float(pub["net_pct"])) > tol:
            raise SystemExit(f"Control net_pct row {i}: {got['net_pct']} != {pub['net_pct']}")
    print("control matches the published 2010 book", flush=True)


def _blank_metrics() -> dict:
    return {
        "n": 0,
        "wins": 0,
        "losses": 0,
        "win_pct": float("nan"),
        "avg_pct": float("nan"),
        "median_pct": float("nan"),
        "avg_win": float("nan"),
        "avg_loss": float("nan"),
        "pf": float("nan"),
        "wo_max": float("nan"),
        "outlier": float("nan"),
        "expectancy_pct": float("nan"),
        "avg_days": float("nan"),
        "median_days": float("nan"),
        "capital_days": 0,
        "profit_per_capital_day": float("nan"),
        "ann_ror": float("nan"),
        "tpy": float("nan"),
        "total": 0.0,
        "time_n": 0,
        "line_n": 0,
        "time_pct": float("nan"),
        "line_pct": float("nan"),
    }


def closed_metrics(frame: pd.DataFrame, years: float) -> dict:
    stats = _blank_metrics()
    if frame is None or frame.empty:
        return stats
    closed = frame[frame["status"] == "closed"].copy()
    if closed.empty:
        return stats
    pcts = closed["net_pct"].to_numpy(dtype=float)
    nets = closed["net"].to_numpy(dtype=float)
    days = closed["days_held"].to_numpy(dtype=float)
    wins = nets[nets > 0]
    losses = nets[nets <= 0]
    win_pcts = pcts[pcts > 0]
    gross_win = float(wins.sum()) if len(wins) else 0.0
    gross_loss = float(-losses.sum()) if len(losses) else 0.0
    if gross_loss > 0:
        pf = gross_win / gross_loss
    elif gross_win > 0:
        pf = float("inf")
    else:
        pf = float("nan")
    if (pcts > 0).any():
        wo = np.delete(pcts, int(np.argmax(pcts)))
        wo_max = float(np.mean(wo)) if len(wo) else float("nan")
        outlier = float(win_pcts.max() / win_pcts.sum() * 100.0) if len(win_pcts) and win_pcts.sum() > 0 else float("nan")
    else:
        wo_max = float(np.mean(pcts)) if len(pcts) else float("nan")
        outlier = float("nan")
    capital_days = int(np.nansum(days))
    total = float(nets.sum())
    avg_days = float(np.nanmean(days)) if len(days) else float("nan")
    ann = ann_ror_from_closed(
        total_pnl=total,
        n_trades=int(len(closed)),
        avg_days_held=avg_days,
        brt_cash=STAKE,
    )
    reasons = closed["reason"].astype(str)
    time_n = int(reasons.str.contains("time stop").sum())
    line_n = int(reasons.str.contains("entry line").sum())
    n = int(len(closed))
    stats.update(
        {
            "n": n,
            "wins": int((nets > 0).sum()),
            "losses": int((nets <= 0).sum()),
            "win_pct": 100.0 * float((nets > 0).mean()),
            "avg_pct": float(np.mean(pcts)),
            "median_pct": float(np.median(pcts)),
            "avg_win": float(np.mean(wins) / STAKE * 100.0) if len(wins) else float("nan"),
            "avg_loss": float(np.mean(losses) / STAKE * 100.0) if len(losses) else float("nan"),
            "pf": float(pf) if np.isfinite(pf) else pf,
            "wo_max": wo_max,
            "outlier": outlier,
            "expectancy_pct": float(np.mean(pcts)),
            "avg_days": avg_days,
            "median_days": float(np.nanmedian(days)),
            "capital_days": capital_days,
            "profit_per_capital_day": (total / capital_days) if capital_days else float("nan"),
            "ann_ror": float(ann) if ann is not None else float("nan"),
            "tpy": float(n / years) if years and years > 0 else float("nan"),
            "total": total,
            "time_n": time_n,
            "line_n": line_n,
            "time_pct": 100.0 * time_n / n if n else float("nan"),
            "line_pct": 100.0 * line_n / n if n else float("nan"),
        }
    )
    return stats


def path_stats(equity: pd.DataFrame) -> dict:
    empty = {
        "max_dd": float("nan"),
        "ann": float("nan"),
        "sharpe": float("nan"),
        "calmar": float("nan"),
        "end": float("nan"),
        "end_pct": float("nan"),
    }
    if equity is None or equity.empty:
        return empty
    eq = equity["equity"].to_numpy(dtype=float)
    if len(eq) < 2 or not np.isfinite(eq).all():
        return empty
    peak = np.maximum.accumulate(eq)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = np.where(peak > 0, eq / peak - 1.0, np.nan)
    max_dd = float(np.nanmin(dd) * 100.0) if np.isfinite(dd).any() else float("nan")
    start_d = pd.Timestamp(equity["date"].iloc[0])
    end_d = pd.Timestamp(equity["date"].iloc[-1])
    years = max((end_d - start_d).days / 365.0, 1 / 365)
    if eq[0] > 0 and eq[-1] > 0:
        ann = float((eq[-1] / eq[0]) ** (1.0 / years) - 1.0) * 100.0
    else:
        ann = float("nan")
    rets = pd.Series(eq).pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    if len(rets) > 5 and float(rets.std(ddof=1)) > 0:
        sharpe = float(rets.mean() / rets.std(ddof=1) * math.sqrt(252))
    else:
        sharpe = float("nan")
    calmar = ann / abs(max_dd) if np.isfinite(ann) and np.isfinite(max_dd) and abs(max_dd) > 1e-9 else float("nan")
    return {
        "max_dd": max_dd,
        "ann": ann,
        "sharpe": sharpe,
        "calmar": float(calmar) if np.isfinite(calmar) else float("nan"),
        "end": float(eq[-1]),
        "end_pct": float(eq[-1] / STAKE * 100.0 - 100.0),
        "years": years,
    }


def slice_years(equity: pd.DataFrame) -> tuple[float, float, float]:
    if equity.empty:
        return 1.0, 1.0, 1.0
    first = pd.Timestamp(equity["date"].iloc[0])
    last = pd.Timestamp(equity["date"].iloc[-1])
    full = max((last - first).days / 365.0, 1 / 365)
    is_years = max((min(last, IS_CUT) - first).days / 365.0, 1 / 365)
    oos_years = max((last - IS_CUT).days / 365.0, 1 / 365)
    return full, is_years, oos_years


def mark_open_before_cut(trade: dict, panel: dict, bt, asof: pd.Timestamp) -> dict | None:
    entry = pd.Timestamp(trade["entry_date"])
    dates = panel["dates"]
    chosen = None
    for i, d in enumerate(dates):
        ts = pd.Timestamp(d)
        if entry <= ts < asof:
            chosen = i
    if chosen is None:
        return None
    long_px, short_px = bt._side_prices(
        panel, chosen, "close", trade["long"], trade["short"], trade["left"]
    )
    long_pnl = bt._leg_pnl(trade["shares_long"], trade["entry_long"], long_px, "long")
    short_pnl = bt._leg_pnl(trade["shares_short"], trade["entry_short"], short_px, "short")
    net = long_pnl + short_pnl
    return {
        "date": _iso(dates[chosen]),
        "long_px": long_px,
        "short_px": short_px,
        "net": net,
        "net_pct": net / STAKE * 100.0,
        "sessions_after_entry": chosen - int(trade["entry_i"]),
    }


def marked_is_pcts(frame: pd.DataFrame, trades: list[dict], panels: dict, bt) -> list[float]:
    """Closed in-sample trades keep their real exit. A ticket still open at the cut is marked then."""
    pcts = []
    by_key = {(t["left"], t["right"], _iso(t["entry_date"])): t for t in trades}
    for rec in frame.itertuples(index=False):
        if rec.sample != "IS":
            continue
        if rec.status == "closed":
            pcts.append(float(rec.net_pct))
            continue
        trade = by_key[(rec.left, rec.right, rec.entry_date)]
        panel = panels[(rec.left, rec.right)]
        marked = mark_open_before_cut(trade, panel, bt, IS_CUT)
        if marked is None:
            continue
        pcts.append(float(marked["net_pct"]))
    return pcts


def judge(marked_control: float, marked_arm: float, wr_c: float, wr_a: float, n_c: int, n_a: int) -> tuple[str, str]:
    if n_a < n_c:
        return "DISMISS", "In-sample trade count fell, so the clock did not earn a keep."
    if not (np.isfinite(marked_control) and np.isfinite(marked_arm)):
        return "HOLD", "The in-sample marked average is not a number, so this stays a hold."
    gap = marked_arm - marked_control
    wr_drop = (wr_c - wr_a) if np.isfinite(wr_c) and np.isfinite(wr_a) else float("nan")
    if gap > 1.0 and (not np.isfinite(wr_drop) or wr_drop <= 10.0):
        return (
            "KEEP",
            "The in-sample marked average is higher and the win rate did not fall by more than 10 points. "
            "That mark includes a control entry that was still open at the last session before 2024. "
            "The finished-trade average by itself looks worse for the clock because it leaves that open hold out. "
            "Out-of-sample was not used.",
        )
    if abs(gap) <= 1.0 or (gap > 1.0 and np.isfinite(wr_drop) and wr_drop > 10.0):
        return (
            "HOLD",
            "The in-sample marked average is flat, or it is higher only with a win-rate drop of more than 10 points. That is not a keep. Out-of-sample was not used.",
        )
    return (
        "DISMISS",
        "The in-sample marked average is worse. Out-of-sample was not used, and the knobs stay frozen.",
    )


def scan_options(menu: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    chain = pd.read_parquet(CHAIN)
    chain["symbol"] = chain["symbol"].astype(str).str.upper()
    chain["expiry_dt"] = pd.to_datetime(chain["expiry"])
    fetched = pd.to_datetime(chain["fetched_at"], utc=True)
    con = __import__("duckdb").connect(str(DB), read_only=True)
    try:
        px = con.execute(
            "SELECT symbol, close FROM prices WHERE date = DATE '2026-09-30'"
        ).fetchdf()
    finally:
        con.close()
    px["symbol"] = px["symbol"].astype(str).str.upper()
    under = chain.groupby("symbol", as_index=False)["underlying_last"].first()
    match = under.merge(px, on="symbol", how="left")
    match["abs_pct"] = (match["underlying_last"] - match["close"]).abs() / match["close"] * 100.0
    nearest = chain.groupby("symbol")["expiry_dt"].transform("min")
    near = chain.loc[chain["expiry_dt"].eq(nearest)].copy()
    two = (near["bid"] > 0) & (near["ask"] > 0)
    liquid = (near["volume"] >= LIQ_VOLUME_MIN) | (near["openInterest"] >= LIQ_OI_MIN)
    book = near.loc[two & liquid].copy()
    book = book.merge(px.rename(columns={"close": "stock"}), on="symbol", how="inner")
    book = book[book["stock"] > 0].copy()
    book["dist"] = (book["strike"] - book["stock"]).abs()
    book["mid_ba"] = (book["bid"] + book["ask"]) / 2.0
    book = book.sort_values(
        ["symbol", "type", "dist", "openInterest", "volume", "strike"],
        ascending=[True, True, True, False, False, True],
    )
    pick = book.groupby(["symbol", "type"], as_index=False, sort=False).head(1).copy()
    call = pick["type"].eq("C")
    pick["intrinsic"] = np.where(
        call,
        np.maximum(pick["stock"] - pick["strike"], 0.0),
        np.maximum(pick["strike"] - pick["stock"], 0.0),
    )
    pick["leftover"] = pick["mid_ba"] - pick["intrinsic"]
    pick["leftover_pct"] = pick["leftover"] / pick["stock"] * 100.0
    pick["spread_pct"] = (pick["ask"] - pick["bid"]) / pick["mid_ba"] * 100.0
    pick["moneyness_pct"] = (pick["strike"] - pick["stock"]) / pick["stock"] * 100.0
    pick["days_to_expiry"] = (pick["expiry_dt"] - SCAN_DAY).dt.days
    pick = pick.sort_values(["leftover", "symbol", "type"], ascending=[False, True, True])
    out = pd.DataFrame(
        {
            "symbol": pick["symbol"].to_numpy(),
            "type": pick["type"].to_numpy(),
            "expiry": pick["expiry_dt"].dt.date.astype(str).to_numpy(),
            "days_to_expiry": pick["days_to_expiry"].to_numpy(),
            "strike": pick["strike"].to_numpy(),
            "stock_close": pick["stock"].to_numpy(),
            "moneyness_pct": pick["moneyness_pct"].to_numpy(),
            "bid": pick["bid"].to_numpy(),
            "ask": pick["ask"].to_numpy(),
            "mid": pick["mid_ba"].to_numpy(),
            "intrinsic": pick["intrinsic"].to_numpy(),
            "leftover": pick["leftover"].to_numpy(),
            "leftover_pct_of_stock": pick["leftover_pct"].to_numpy(),
            "spread_pct_of_mid": pick["spread_pct"].to_numpy(),
            "volume": pick["volume"].to_numpy(),
            "open_interest": pick["openInterest"].to_numpy(),
            "underlying_last": pick["underlying_last"].to_numpy(),
            "contract": pick["contractSymbol"].to_numpy(),
        }
    )
    qualified = set(out["symbol"])
    chain_syms = set(chain["symbol"])
    menu_syms = set(menu["left"]).union(set(menu["right"]))
    both_chain = int(((menu["left"].isin(chain_syms)) & (menu["right"].isin(chain_syms))).sum())
    both_qual = int(((menu["left"].isin(qualified)) & (menu["right"].isin(qualified))).sum())
    focus = {}
    for sym in ("PNFP", "ZION", "HL", "NEM"):
        rows = out[out["symbol"] == sym]
        focus[sym] = {
            "in_chain": sym in chain_syms,
            "qualified": sym in qualified,
            "rows": rows.to_dict(orient="records"),
        }
    pair_focus = {}
    for a, b in (("PNFP", "ZION"), ("HL", "NEM")):
        pair_focus[f"{a}/{b}"] = {
            "both_in_chain": a in chain_syms and b in chain_syms,
            "both_qualified": a in qualified and b in qualified,
        }
    meta = {
        "rows": int(len(chain)),
        "symbols_in_file": int(chain["symbol"].nunique()),
        "fetched_min": str(fetched.min()),
        "fetched_max": str(fetched.max()),
        "close_match_n": int(match["close"].notna().sum()),
        "close_match_max_pct": float(match["abs_pct"].max()) if match["abs_pct"].notna().any() else float("nan"),
        "nearest_symbols": int(near["symbol"].nunique()),
        "nearest_two_sided_symbols": int(near.loc[two, "symbol"].nunique()),
        "qualified_names": int(out["symbol"].nunique()),
        "qualified_contracts": int(len(out)),
        "both_sides": int(out.groupby("symbol")["type"].nunique().eq(2).sum()) if len(out) else 0,
        "expiry_counts": {str(k.date()): int(v) for k, v in near.groupby("symbol")["expiry_dt"].min().value_counts().sort_index().items()},
        "menu_symbols": int(len(menu_syms)),
        "menu_symbols_in_chain": int(len(menu_syms & chain_syms)),
        "menu_pairs": int(len(menu)),
        "menu_pairs_both_in_chain": both_chain,
        "menu_pairs_both_qualified": both_qual,
        "focus": focus,
        "pair_focus": pair_focus,
        "chain_names_without_a_pick": int(chain["symbol"].nunique() - out["symbol"].nunique()),
    }
    return out, meta


def _row_metric(label: str, control: str, arm: str, delta: str, sort_hint: str = "") -> str:
    return "<tr>" + _td(label) + _td(control, True) + _td(arm, True) + _td(delta, True) + "</tr>"


def _delta_pct(arm: float, control: float) -> str:
    if not (np.isfinite(arm) and np.isfinite(control)):
        return "—"
    return f"{arm - control:+.2f} pp"


def _delta_num(arm: float, control: float, digits: int = 2) -> str:
    if not (np.isfinite(arm) and np.isfinite(control)):
        return "—"
    return f"{arm - control:+,.{digits}f}"


def metric_table(title: str, control: dict, arm: dict) -> str:
    rows = [
        ("Closed trades", str(control["n"]), str(arm["n"]), _delta_num(arm["n"], control["n"], 0)),
        ("Wins", str(control["wins"]), str(arm["wins"]), _delta_num(arm["wins"], control["wins"], 0)),
        ("Losses", str(control["losses"]), str(arm["losses"]), _delta_num(arm["losses"], control["losses"], 0)),
        ("Win rate", _pct(control["win_pct"], 1), _pct(arm["win_pct"], 1), _delta_pct(arm["win_pct"], control["win_pct"])),
        ("Average %", _pct(control["avg_pct"]), _pct(arm["avg_pct"]), _delta_pct(arm["avg_pct"], control["avg_pct"])),
        ("Median %", _pct(control["median_pct"]), _pct(arm["median_pct"]), _delta_pct(arm["median_pct"], control["median_pct"])),
        ("Average win %", _pct(control["avg_win"]), _pct(arm["avg_win"]), _delta_pct(arm["avg_win"], control["avg_win"])),
        ("Average loss %", _pct(control["avg_loss"]), _pct(arm["avg_loss"]), _delta_pct(arm["avg_loss"], control["avg_loss"])),
        ("Profit factor", _pf_text(control["pf"], control["wins"], control["n"]), _pf_text(arm["pf"], arm["wins"], arm["n"]), "—"),
        ("Average % leaving out the largest win", _pct(control["wo_max"]), _pct(arm["wo_max"]), _delta_pct(arm["wo_max"], control["wo_max"])),
        ("Outlier share of winning %", _pct(control["outlier"], 1), _pct(arm["outlier"], 1), _delta_pct(arm["outlier"], control["outlier"])),
        ("Expectancy %", _pct(control["expectancy_pct"]), _pct(arm["expectancy_pct"]), _delta_pct(arm["expectancy_pct"], control["expectancy_pct"])),
        ("Trades per year", _num(control["tpy"], 2), _num(arm["tpy"], 2), _delta_num(arm["tpy"], control["tpy"])),
        ("Average calendar days held", _num(control["avg_days"], 1), _num(arm["avg_days"], 1), _delta_num(arm["avg_days"], control["avg_days"], 1)),
        ("Median calendar days held", _num(control["median_days"], 1), _num(arm["median_days"], 1), _delta_num(arm["median_days"], control["median_days"], 1)),
        ("Capital days", f"{control['capital_days']:,}", f"{arm['capital_days']:,}", _delta_num(arm["capital_days"], control["capital_days"], 0)),
        (
            "Profit per capital day",
            format_money(control["profit_per_capital_day"]),
            format_money(arm["profit_per_capital_day"]),
            "—",
        ),
        ("Annualized rate of return", _pct(control["ann_ror"], 1), _pct(arm["ann_ror"], 1), _delta_pct(arm["ann_ror"], control["ann_ror"])),
        (
            "Exit: back near the line",
            f"{control['line_n']} ({_pct(control['line_pct'], 1)})" if control["n"] else "—",
            f"{arm['line_n']} ({_pct(arm['line_pct'], 1)})" if arm["n"] else "—",
            _delta_num(arm["line_n"], control["line_n"], 0),
        ),
        (
            "Exit: 15-session clock",
            f"{control['time_n']} ({_pct(control['time_pct'], 1)})" if control["n"] else "—",
            f"{arm['time_n']} ({_pct(arm['time_pct'], 1)})" if arm["n"] else "—",
            _delta_num(arm["time_n"], control["time_n"], 0),
        ),
    ]
    body = "".join(_row_metric(*row) for row in rows)
    headers = [
        _th("Metric", "text"),
        _th("Control", "num"),
        _th("15-session clock", "num"),
        _th("Clock minus control", "num"),
    ]
    return (
        '<div class="table-wrap"><table class="sortable">'
        f"<caption>{_esc(title)} Click a column header to sort.</caption>"
        f"<thead><tr>{''.join(headers)}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def path_table(control: dict, arm: dict) -> str:
    rows = [
        ("Max drawdown", _pct(control["max_dd"], 1), _pct(arm["max_dd"], 1), _delta_pct(arm["max_dd"], control["max_dd"])),
        (
            "Marked annualized rate of return",
            _pct(control["ann"], 1),
            _pct(arm["ann"], 1),
            _delta_pct(arm["ann"], control["ann"]),
        ),
        ("Calmar", _num(control["calmar"], 2), _num(arm["calmar"], 2), _delta_num(arm["calmar"], control["calmar"])),
        ("Sharpe", _num(control["sharpe"], 2), _num(arm["sharpe"], 2), _delta_num(arm["sharpe"], control["sharpe"])),
        ("Account vs the $10,000 start", _pct(control["end_pct"], 1), _pct(arm["end_pct"], 1), _delta_pct(arm["end_pct"], control["end_pct"])),
    ]
    body = "".join(_row_metric(*row) for row in rows)
    headers = [
        _th("Path metric", "text"),
        _th("Control", "num"),
        _th("15-session clock", "num"),
        _th("Clock minus control", "num"),
    ]
    caption = (
        "Daily marked account, starting at $10,000, adding each closed result and the open mark. "
        "Max drawdown is negative (closer to zero is a smaller hole). "
        "The marked annualized rate of return is the end account versus the start, over the calendar, "
        "not the closed-trade formula in the tables above. Sharpe uses daily changes, a zero interest rate, "
        "and the square root of 252. Click a column header to sort."
    )
    return (
        '<div class="table-wrap"><table class="sortable">'
        f"<caption>{_esc(caption)}</caption>"
        f"<thead><tr>{''.join(headers)}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def trade_table(frame: pd.DataFrame, caption: str) -> str:
    headers = [
        ("#", "num"),
        ("Status", "text"),
        ("Sample", "text"),
        ("Pair", "text"),
        ("Long", "text"),
        ("Short", "text"),
        ("Signal", "date"),
        ("Entry", "date"),
        ("Exit", "date"),
        ("Sessions after entry", "num"),
        ("Calendar days", "num"),
        ("Long in", "num"),
        ("Long out", "num"),
        ("Short in", "num"),
        ("Short out", "num"),
        ("Entry z", "num"),
        ("Exit z", "num"),
        ("Result %", "num"),
        ("Why it left", "text"),
    ]
    body = []
    for rec in frame.itertuples(index=False):
        cells = [
            _td(str(rec.n), True),
            _td(rec.status),
            _td(rec.sample),
            _td(f"{rec.left} / {rec.right}"),
            _td(str(rec.long)),
            _td(str(rec.short)),
            _td(str(rec.signal_date)),
            _td(str(rec.entry_date)),
            _td(str(rec.exit_date) if rec.exit_date else "open"),
            _td("—" if pd.isna(rec.sessions_after_entry) else str(int(rec.sessions_after_entry)), True),
            _td("—" if pd.isna(rec.days_held) else str(int(rec.days_held)), True),
            _td(_px(rec.entry_long), True),
            _td(_px(rec.exit_long), True),
            _td(_px(rec.entry_short), True),
            _td(_px(rec.exit_short), True),
            _td(_num(rec.z_entry, 2), True),
            _td(_num(rec.z_exit, 2), True),
            _td(_pct(rec.net_pct), True),
            _td(str(rec.reason)),
        ]
        body.append("<tr>" + "".join(cells) + "</tr>")
    head = "".join(_th(a, b) for a, b in headers)
    return (
        '<div class="table-wrap"><table class="sortable">'
        f"<caption>{_esc(caption)} Click a column header to sort.</caption>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def option_table(frame: pd.DataFrame, caption: str) -> str:
    headers = [
        ("Symbol", "text"),
        ("Type", "text"),
        ("Expiry", "date"),
        ("Days left", "num"),
        ("Strike", "num"),
        ("Stock close", "num"),
        ("Strike vs stock", "num"),
        ("Bid", "num"),
        ("Ask", "num"),
        ("Mid", "num"),
        ("Intrinsic", "num"),
        ("Leftover $", "num"),
        ("Leftover % of stock", "num"),
        ("Spread % of mid", "num"),
        ("Volume", "num"),
        ("Open interest", "num"),
    ]
    body = []
    for rec in frame.itertuples(index=False):
        side = "Call" if rec.type == "C" else "Put"
        cells = [
            _td(str(rec.symbol)),
            _td(side),
            _td(str(rec.expiry)),
            _td(str(int(rec.days_to_expiry)), True),
            _td(_px(rec.strike), True),
            _td(_px(rec.stock_close), True),
            _td(_pct(rec.moneyness_pct, 1), True),
            _td(_px(rec.bid), True),
            _td(_px(rec.ask), True),
            _td(_px(rec.mid), True),
            _td(_px(rec.intrinsic), True),
            _td(_px(rec.leftover), True),
            _td(_pct(rec.leftover_pct_of_stock), True),
            _td(_pct(rec.spread_pct_of_mid, 1), True),
            _td(f"{int(rec.volume):,}", True),
            _td(f"{int(rec.open_interest):,}", True),
        ]
        body.append("<tr>" + "".join(cells) + "</tr>")
    head = "".join(_th(a, b) for a, b in headers)
    return (
        '<div class="table-wrap"><table class="sortable">'
        f"<caption>{_esc(caption)} Click a column header to sort.</caption>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def focus_html(meta: dict) -> str:
    rows = []
    for sym in ("PNFP", "ZION", "HL", "NEM"):
        info = meta["focus"][sym]
        if not info["rows"]:
            rows.append(
                "<tr>"
                + _td(sym)
                + _td("Yes" if info["in_chain"] else "No")
                + _td("No qualifying contract")
                + _td("—", True)
                + _td("—", True)
                + _td("—", True)
                + _td("—", True)
                + "</tr>"
            )
            continue
        for rec in info["rows"]:
            side = "Call" if rec["type"] == "C" else "Put"
            rows.append(
                "<tr>"
                + _td(sym)
                + _td("Yes")
                + _td(f"{side} {rec['expiry']} strike {_px(rec['strike'])}")
                + _td(_px(rec["stock_close"]), True)
                + _td(_px(rec["mid"]), True)
                + _td(_px(rec["leftover"]), True)
                + _td(_pct(rec["leftover_pct_of_stock"]), True)
                + "</tr>"
            )
    headers = [
        _th("Name", "text"),
        _th("Chain that day", "text"),
        _th("Contract that qualified", "text"),
        _th("Stock close", "num"),
        _th("Mid", "num"),
        _th("Leftover $", "num"),
        _th("Leftover % of stock", "num"),
    ]
    return (
        '<div class="table-wrap"><table class="sortable">'
        "<caption>The two published pairs, on 30 September 2026. "
        "A qualifying contract uses the same nearest-expiry rule as the scan. "
        "Click a column header to sort.</caption>"
        f"<thead><tr>{''.join(headers)}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def extremes(scan: pd.DataFrame, n: int = 5) -> tuple[pd.DataFrame, pd.DataFrame]:
    ordered = scan.sort_values(["leftover", "symbol"], ascending=[False, True])
    rich = ordered.head(n)
    cheap = ordered.tail(n).sort_values(["leftover", "symbol"], ascending=[True, True])
    return rich, cheap


def ticket_sentence(frame: pd.DataFrame, left: str, right: str) -> str:
    hit = frame[(frame["left"] == left) & (frame["right"] == right)]
    if hit.empty:
        return (
            f"The full clock replay never filled {left} / {right}. "
            "The book was already in another pair on the days that name was the widest gap."
        )
    bits = []
    for rec in hit.itertuples(index=False):
        if rec.status == "closed":
            bits.append(
                f"It did fill {rec.short} short / {rec.long} long on {rec.entry_date} "
                f"and left on {rec.exit_date} at the {rec.exit_which}, "
                f"short {_px(rec.exit_short)} and long {_px(rec.exit_long)}, "
                f"{_pct(rec.net_pct)} ({rec.reason})."
            )
        else:
            bits.append(
                f"It filled {rec.short} short / {rec.long} long on {rec.entry_date} and was still open."
            )
    return " ".join(bits)


def published_walk(trade: dict, panel: dict, bt) -> dict:
    entry_i = int(trade["entry_i"])
    n = len(panel["dates"])
    cover = None
    for k in range(1, MAX_SESSIONS):
        i = entry_i + k
        if i >= n:
            break
        z_now = bt._frozen_z(panel, pd.Timestamp(panel["dates"][i]), trade["alpha"], trade["beta"], trade["center"], trade["scale"])
        if np.isfinite(z_now) and abs(z_now) <= EXIT_Z and i + 1 < n:
            cover = {"i": i + 1, "which": "open", "reason": "Back near the entry line", "z": z_now, "signal_i": i}
            break
    clock_i = entry_i + MAX_SESSIONS
    if cover is not None:
        chosen = cover
    elif clock_i < n:
        z_now = bt._frozen_z(
            panel, pd.Timestamp(panel["dates"][clock_i]), trade["alpha"], trade["beta"], trade["center"], trade["scale"]
        )
        chosen = {"i": clock_i, "which": "close", "reason": "15-session time stop", "z": z_now, "signal_i": clock_i}
    else:
        return {"status": "not enough sessions"}
    i = chosen["i"]
    long_px, short_px = bt._side_prices(panel, i, chosen["which"], trade["long"], trade["short"], trade["left"])
    long_pnl = bt._leg_pnl(trade["shares_long"], trade["entry_long"], long_px, "long")
    short_pnl = bt._leg_pnl(trade["shares_short"], trade["entry_short"], short_px, "short")
    net = long_pnl + short_pnl
    return {
        "status": "closed",
        "left": trade["left"],
        "right": trade["right"],
        "long": trade["long"],
        "short": trade["short"],
        "entry_date": _iso(trade["entry_date"]),
        "exit_date": _iso(panel["dates"][i]),
        "exit_which": chosen["which"],
        "reason": chosen["reason"],
        "sessions_after_entry": i - entry_i,
        "exit_long": long_px,
        "exit_short": short_px,
        "entry_long": trade["entry_long"],
        "entry_short": trade["entry_short"],
        "shares_long": trade["shares_long"],
        "shares_short": trade["shares_short"],
        "z_exit": chosen["z"],
        "net": net,
        "net_pct": net / STAKE * 100.0,
        "days_held": int((pd.Timestamp(panel["dates"][i]) - pd.Timestamp(trade["entry_date"])).days),
    }


def render(
    control: pd.DataFrame,
    arm: pd.DataFrame,
    metrics: dict,
    paths: dict,
    walks: list[dict],
    is_mark: dict,
    scan: pd.DataFrame,
    opt: dict,
    verdict: str,
    verdict_why: str,
    meta_bt: dict,
) -> str:
    rich, cheap = extremes(scan, 5)
    js = """
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-" || s === "open") return type === "text" || type === "date" ? "" : 0;
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
      if (typeof av === "string" || typeof bv === "string") {
        return dir * String(av).localeCompare(String(bv));
      }
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
    expiry_bits = ", ".join(f"{k} ({v} names)" for k, v in opt["expiry_counts"].items())
    walk_bits = []
    for w in walks:
        walk_bits.append(
            f"{w['short']} short / {w['long']} long, entered {w['entry_date']} at short {_px(w['entry_short'])} "
            f"and long {_px(w['entry_long'])}, leaves on {w['exit_date']} at the {w['exit_which']} "
            f"(short {_px(w['exit_short'])}, long {_px(w['exit_long'])}), "
            f"{_pct(w['net_pct'])} after {w['sessions_after_entry']} sessions and {w['days_held']} calendar days. "
            f"{w['reason']}."
        )
    pnfp_mark = is_mark.get("PNFP/ZION")
    pnfp_line = "The control had no PNFP / ZION mark to show."
    if pnfp_mark:
        pnfp_line = (
            f"Marked at the last session before 2024, {pnfp_mark['date']}: "
            f"short {_px(pnfp_mark['short_px'])}, long {_px(pnfp_mark['long_px'])}, "
            f"{_pct(pnfp_mark['net_pct'])}. "
            f"That mark is the in-sample hole. The 30 September 2026 mark on this replay, "
            f"{_pct(is_mark['PNFP/ZION_2026']['net_pct'])}, uses the warehouse close now. "
            f"The published trades file marked the same hold at about -394.9% from the close saved with that stamp. "
            f"A few cents of later price cleanup explains the gap. That 2026 mark is not part of the verdict."
        )
    highlight = pd.concat([rich, cheap], ignore_index=True)
    c_is = metrics["control"]["IS"]
    a_is = metrics["arm"]["IS"]
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Thorp time stop and one-day chains — 2026-10-01</title>
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
  .wrap {{ max-width: 1100px; margin: 0 auto; padding: 36px 22px 72px; }}
  header.doc-head {{ border-bottom: 2px solid var(--ink); padding-bottom: 14px; margin-bottom: 22px; }}
  .eyebrow {{
    font-size: 0.72rem; letter-spacing: 0.14em; text-transform: uppercase;
    color: var(--accent); font-weight: 650; margin: 0 0 6px;
  }}
  h1 {{ font-size: 1.65rem; margin: 0 0 8px; letter-spacing: -0.02em; line-height: 1.25; }}
  h2 {{ font-size: 1.2rem; margin: 32px 0 10px; padding-bottom: 5px; border-bottom: 1px solid var(--line); }}
  h3 {{ font-size: 1.02rem; margin: 18px 0 6px; }}
  p, li {{ margin: 0 0 10px; }}
  blockquote.ask {{
    margin: 8px 0 0; white-space: pre-wrap;
    font-family: Georgia, "Times New Roman", serif; font-size: 0.95rem;
  }}
  .callout {{ background: var(--accent-soft); border-left: 4px solid var(--accent); padding: 12px 14px; margin: 14px 0 18px; }}
  .callout.warn {{ background: var(--warn-bg); border-left-color: var(--warn); }}
  .callout.bad {{ background: var(--bad-bg); border-left-color: var(--bad); }}
  .callout.ok {{ background: var(--ok-bg); border-left-color: var(--ok); }}
  .table-wrap {{ overflow-x: auto; margin: 8px 0 16px; }}
  table.sortable {{ border-collapse: collapse; width: 100%; font-size: 14px; background: var(--card); }}
  th, td {{ border: 1px solid var(--line); padding: 8px 9px; text-align: left; vertical-align: top; }}
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
    <h1>A 15-session clock on the pairs book, and one day of option leftovers</h1>
    <p>Two results. The stock clock uses the prices from 2010 through 30 September 2026. The option page is 30 September 2026 only.</p>
  </header>

  <div class="callout">
    <strong>What you asked</strong>
    <blockquote class="ask">{_esc(ORIGINAL_REQUEST)}</blockquote>
  </div>

  <div class="callout">
    <strong>In plain English</strong>
    <p>We re-ran the short pairs idea with a 15-day clock, because a pair that never comes back together was the failure. We also priced every option chain we saved on 30 September against its stock, to see which options look expensive or cheap the way the old warrant books did.</p>
    <p>The stock test can use about 16 years of daily prices. A pair is two stocks that finish up together and down together. The menu is the one already published: full-window correlation at least 0.60, and each half at least 0.55. That cutoff was not rebuilt. A gap is a close at least 2 standard deviations off a 252-session ordinary least squares (OLS) line, which is a straight line through the prior year of log prices, leaving out the signal day. The book shorts the expensive side and buys the cheap side, about $10,000 of whole shares each, at the next open, and it holds one pair at a time. The control sells when a later close is back within 0.5 standard deviations of the line that was frozen on entry, and that sale fills at the next open. The new arm uses that same sale, or it sells at the close of the 15th trading session after entry, whichever comes first.</p>
    <p>The option test can use one wide day, 30 September 2026, plus the ten earlier days that only cover about 21 names. There is no option history before 17 September 2026. A warrant-style hedge back to 2010 is still impossible. The option numbers are a one-day illustration, not a profit and loss. The stock warehouse did not grow. The growth is the 30 September option universe.</p>
  </div>

  <div class="callout {('ok' if verdict == 'KEEP' else 'bad' if verdict == 'DISMISS' else 'warn')}">
    <strong>Verdict on the time stop: {verdict}</strong>
    <p>{_esc(verdict_why)}</p>
    <p>In-sample closed average: control {_pct(c_is['avg_pct'])} on {c_is['n']} trade, clock {_pct(a_is['avg_pct'])} on {a_is['n']} trades, win rate {_pct(a_is['win_pct'], 1)}. The verdict uses the in-sample marked book, which keeps those closed trades and also marks a position that was still open at the last session before 2024. Control marked average {_pct(is_mark['control_avg'])} on {is_mark['control_n']} entries. Clock marked average {_pct(is_mark['arm_avg'])} on {is_mark['arm_n']} entries. Out-of-sample is printed below and was not used to pick this label.</p>
  </div>

  <h2>What was frozen</h2>
  <ul>
    <li>Pair menu: the saved file from the 2010 book, {meta_bt['pairs']:,} pairs. Correlation was not rerun.</li>
    <li>Prices: <code>data/ohlcv.duckdb</code>, split-adjusted the same way as that book. Last session 2026-09-30.</li>
    <li>Entry, one pair, and the $10,000 legs stay put. The 0.5-standard-deviation cover still fills at the next open.</li>
    <li>The only new knob is the clock: the close of the 15th shared session after the entry session. The reading notes said that clock would fill at the next open. This test fills it at that close, which is the instruction for this page.</li>
    <li>In-sample means the entry is before 2024-01-01. Out-of-sample means the entry is on or after that day. Report only.</li>
    <li>Annualized rate of return in the closed-trade tables is the book formula: one plus total result divided by ($10,000 times the number of trades), raised to 365 divided by average days held, minus one. The path table uses a different marked-account version and says so.</li>
    <li>Costs left out: dividends, borrow, commission. Same as the 2010 book.</li>
  </ul>

  <h2>1. Stock test</h2>
  <p>{_esc(ticket_sentence(arm, 'PNFP', 'ZION'))}</p>
  <p>The published ticket, walked on its own with the same shares, is what the clock does to the hold the control is still in. {' '.join(walk_bits)}</p>
  <p>{_esc(pnfp_line)}</p>
  <p>Closed trades ignore a position that never got an exit. The control’s second ticket is that open hold, so it is not inside the control’s closed average. The marked average puts it back, using the last close before 2024, so the verdict does not borrow the 2024–2026 prices.</p>

  <h3>Full book, closed trades</h3>
  {metric_table("Every finished trade. Entry can be before or after 2024.", metrics["control"]["full"], metrics["arm"]["full"])}
  <h3>In-sample, entry before 2024-01-01</h3>
  {metric_table("In-sample quality. This is the sample the verdict uses, together with the open mark described above.", metrics["control"]["IS"], metrics["arm"]["IS"])}
  <h3>Out-of-sample, entry on or after 2024-01-01</h3>
  <p>Report only. These rows did not choose the verdict and the knobs were not changed after seeing them.</p>
  {metric_table("Out-of-sample, report only.", metrics["control"]["OOS"], metrics["arm"]["OOS"])}
  <h3>Marked account path</h3>
  {path_table(paths["control"], paths["arm"])}

  <h3>Control trades</h3>
  {trade_table(control, "The published book, replayed. Same two tickets.")}
  <h3>15-session clock trades</h3>
  {trade_table(arm, "Same entries until a clock exit frees the book. Later tickets are new because the book is no longer stuck.")}

  <h2>2. Option scan, 30 September 2026 only</h2>
  <p>This is a one-day illustration, not a profit and loss. Rich means a high leftover: the option mid sits further above intrinsic value. Cheap means a low leftover, including a mid below intrinsic. Intrinsic for a call is the greater of the stock close minus the strike, and zero. For a put it is the greater of the strike minus the stock close, and zero. The stock is the warehouse close.</p>
  <p>The chain file has {opt['rows']:,} rows and {opt['symbols_in_file']:,} symbols. Quotes in the file were saved from { _esc(opt['fetched_min']) } through { _esc(opt['fetched_max']) }, which is after the 4pm Eastern cash close, not a midday snapshot. The chain’s own stock print matches the warehouse close on every name (largest gap {opt['close_match_max_pct']:.3f}% of the close). Intrinsic still uses the warehouse close.</p>
  <p>Rule, frozen before the ranking: nearest expiry only; bid and ask both above zero; volume at least {LIQ_VOLUME_MIN} or open interest at least {LIQ_OI_MIN}; then the call, and separately the put, whose strike is closest to the stock. A tie goes to higher open interest, then higher volume, then the lower strike. Mid is the average of bid and ask. Names that cleared that rule: <strong>{opt['qualified_names']:,}</strong> of {opt['symbols_in_file']:,} in the file ({opt['chain_names_without_a_pick']:,} had a chain but no contract that cleared it). Contracts in the table: {opt['qualified_contracts']:,}. Names with both a call and a put: {opt['both_sides']:,}.</p>
  <p>Nearest expiry by name: { _esc(expiry_bits) }. Nine names are on an expiry of the same day, so their leftover is an expiring contract, not a long-dated warrant. The saved window is still at most six expiries. Nothing here is a warrant history.</p>
  <p>Of the {opt['menu_pairs']:,} frozen pairs, {opt['menu_pairs_both_in_chain']:,} have both legs in the chain file and {opt['menu_pairs_both_qualified']:,} have both legs clearing the quote rule. {opt['menu_symbols_in_chain']:,} of {opt['menu_symbols']:,} pair-leg symbols appear in the chain. PNFP / ZION both in the chain: {"yes" if opt["pair_focus"]["PNFP/ZION"]["both_in_chain"] else "no"}. Both cleared the quote rule: {"yes" if opt["pair_focus"]["PNFP/ZION"]["both_qualified"] else "no"}. HL / NEM both in the chain: {"yes" if opt["pair_focus"]["HL/NEM"]["both_in_chain"] else "no"}. Both cleared the quote rule: {"yes" if opt["pair_focus"]["HL/NEM"]["both_qualified"] else "no"}.</p>
  {focus_html(opt)}
  <h3>Five richest and five cheapest</h3>
  {option_table(highlight, "Ten contracts from the same scan: the five highest leftovers, then the five lowest. One-day illustration, not a profit and loss.")}
  <h3>Every name that qualified</h3>
  {option_table(scan, "Full one-day scan, richest leftover first. Not a profit and loss. A wide spread means the mid is a noisy quote.")}

  <h2>What this data still cannot do</h2>
  <p>It cannot price a warrant-style hedge from 2010 to now. The stock test has the years. The option file has one wide session and ten narrow ones, nearest expiries only, no dividend series, and no separate model price. Yahoo’s implied volatility is computed from the same quote, so feeding it back into a formula would reprint the market.</p>

  <footer>
    Research only · 1 October 2026 · thorp_timestop_and_chain_scan_20261001 · not gold · not DailyRun.
    Pair menu reused from same_direction_pairs_gap_bt_2010_20260930. Option file yfinance_chain/2026-09-30.
  </footer>
</div>
{js}
</body>
</html>
"""
    return page


def baseline_md(
    metrics: dict,
    paths: dict,
    walks: list[dict],
    is_mark: dict,
    opt: dict,
    verdict: str,
    verdict_why: str,
    meta_bt: dict,
) -> str:
    c_is = metrics["control"]["IS"]
    a_is = metrics["arm"]["IS"]
    c_full = metrics["control"]["full"]
    a_full = metrics["arm"]["full"]
    c_oos = metrics["control"]["OOS"]
    a_oos = metrics["arm"]["OOS"]
    walk_lines = []
    for w in walks:
        walk_lines.append(
            f"- Published ticket {w['left']}/{w['right']}: short {w['short']} / long {w['long']}, "
            f"entry {w['entry_date']}, exit {w['exit_date']} at the {w['exit_which']}, "
            f"short {_px(w['exit_short'])}, long {_px(w['exit_long'])}, {_pct(w['net_pct'])}, {w['reason']}."
        )
    return "\n".join(
        [
            "# Thorp time stop and one-day option chains",
            "",
            "Research only. Not gold. Not DailyRun. One exit knob on the frozen 2010 pairs book, plus a one-day option illustration. No third strategy. OOS is report-only. Nothing was retuned on it.",
            "",
            "## Original request",
            "",
            f"> {ORIGINAL_REQUEST}",
            "",
            "## In plain English",
            "",
            "We re-ran the short pairs idea with a 15-day clock, because a pair that never comes back together was the failure. We also priced every option chain we saved on 30 September against its stock, to see which options look expensive or cheap the way the old warrant books did.",
            "",
            "The stock test uses about 16 years. The option test uses one wide day plus ten narrow days of about 21 names. A warrant-style hedge back to 2010 is still impossible. The stock warehouse did not grow. The growth is the 30 September option universe.",
            "",
            "## Freeze",
            "",
            f"- Pair menu reused from `pairs_correlation.csv` in the 2010 stamp: {meta_bt['pairs']} pairs. Correlation floor was not rebuilt (full window at least 0.60, each half at least 0.55).",
            "- Entry: close at least 2 standard deviations off a 252-session ordinary least squares (OLS) line that excludes the signal day. Biggest absolute percent wins. Short the high side, long the low side, $10,000 a leg, whole shares, next open. One pair.",
            "- Control exit: a later close within 0.5 standard deviations of the frozen line, filled at the next open. No time stop.",
            "- Clock exit: that same cover, or the close of the 15th shared session after the entry session, whichever comes first. The notes page said the clock would fill at the next open. This stamp fills the clock at the close, because that is the request.",
            "- IS: entry before 2024-01-01. OOS: entry on or after 2024-01-01. Report only.",
            "- Verdict sample: in-sample closed trades, plus any in-sample entry still open at the last session before 2024, marked at that close. The 2026 open mark is context, not the verdict.",
            "- Option rule, frozen before ranking: 2026-09-30 only, nearest expiry, bid and ask both positive, volume at least 10 or open interest at least 100, then the call and the put whose strike is closest to the warehouse close. Tie: higher open interest, then higher volume, then lower strike. Leftover = mid minus intrinsic. Mid is the average of bid and ask.",
            "- Costs left out of the stock book: dividends, borrow, commission.",
            "",
            f"## Verdict: {verdict}",
            "",
            verdict_why,
            "",
            f"In-sample closed: control n={c_is['n']}, win rate {_pct(c_is['win_pct'], 1)}, average {_pct(c_is['avg_pct'])}. Clock n={a_is['n']}, win rate {_pct(a_is['win_pct'], 1)}, average {_pct(a_is['avg_pct'])}.",
            f"In-sample marked book (includes the pre-2024 open mark): control {_pct(is_mark['control_avg'])} on {is_mark['control_n']} entries, clock {_pct(is_mark['arm_avg'])} on {is_mark['arm_n']} entries.",
            f"Full closed: control n={c_full['n']}, average {_pct(c_full['avg_pct'])}. Clock n={a_full['n']}, average {_pct(a_full['avg_pct'])}, win rate {_pct(a_full['win_pct'], 1)}.",
            f"OOS closed, report only: control n={c_oos['n']}, average {_pct(c_oos['avg_pct'])}. Clock n={a_oos['n']}, average {_pct(a_oos['avg_pct'])}, win rate {_pct(a_oos['win_pct'], 1)}.",
            f"Marked-account annualized rate of return, full path: control {_pct(paths['control']['ann'], 1)}, clock {_pct(paths['arm']['ann'], 1)}. Max drawdown: control {_pct(paths['control']['max_dd'], 1)}, clock {_pct(paths['arm']['max_dd'], 1)}.",
            "",
            "## Published tickets under the clock alone",
            "",
            *walk_lines,
            "",
            f"PNFP / ZION control mark on {is_mark.get('PNFP/ZION', {}).get('date', '—')}: {_pct(is_mark.get('PNFP/ZION', {}).get('net_pct', float('nan')))}.",
            f"PNFP / ZION control mark on 2026-09-30 (not used for the verdict): {_pct(is_mark.get('PNFP/ZION_2026', {}).get('net_pct', float('nan')))}.",
            "",
            "## Option scan",
            "",
            f"- File rows {opt['rows']:,}, symbols {opt['symbols_in_file']:,}. Fetched {opt['fetched_min']} to {opt['fetched_max']} (after the cash close). Largest underlying-versus-close gap {opt['close_match_max_pct']:.4f}%.",
            f"- Names that qualified: {opt['qualified_names']:,}. Contracts: {opt['qualified_contracts']:,}. Both sides: {opt['both_sides']:,}.",
            f"- Frozen pairs with both legs in the chain: {opt['menu_pairs_both_in_chain']:,} of {opt['menu_pairs']:,}. Both legs qualified: {opt['menu_pairs_both_qualified']:,}.",
            f"- PNFP/ZION both in chain: {opt['pair_focus']['PNFP/ZION']['both_in_chain']}. Both qualified: {opt['pair_focus']['PNFP/ZION']['both_qualified']}.",
            f"- HL/NEM both in chain: {opt['pair_focus']['HL/NEM']['both_in_chain']}. Both qualified: {opt['pair_focus']['HL/NEM']['both_qualified']}.",
            "- 91 names in symbols_missing.csv had no expiries and are not in the scan.",
            "- One-day illustration, not a profit and loss. Not a multi-year backtest.",
            "",
            "## Not claimed",
            "",
            "Not gold. Not DailyRun. The pair menu was chosen on the full window in the 2010 stamp, so membership stays in-sample. This page does not wire a live system and does not retune on the out-of-sample row.",
            "",
        ]
    )


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
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
    bt = _load_bt()
    menu = pd.read_csv(PAIR_MENU)
    menu["left"] = menu["left"].astype(str)
    menu["right"] = menu["right"].astype(str)
    menu["business"] = menu["business"].fillna("") if "business" in menu.columns else ""
    symbols = sorted(set(menu["left"]).union(set(menu["right"])))
    print(f"menu pairs {len(menu)} symbols {len(symbols)}", flush=True)
    close_wide, opens, _hits = load_prices(symbols, bt)
    panels = bt.build_panels(menu, close_wide, opens)
    panel_map = {(p["left"], p["right"]): p for p in panels}
    print("preparing signals", flush=True)
    best_on, gap_count, all_dates = prepare_signals(panels, bt)
    print("control replay", flush=True)
    control_trades, control_eq, _meta_c = replay(panels, best_on, gap_count, all_dates, bt, clock=None)
    control = trades_frame(control_trades)
    assert_control(control)
    print("clock replay", flush=True)
    arm_trades, arm_eq, meta_arm = replay(panels, best_on, gap_count, all_dates, bt, clock=MAX_SESSIONS)
    arm = trades_frame(arm_trades)
    print(f"clock trades {len(arm)} closed {(arm.status == 'closed').sum()}", flush=True)

    full_y, is_y, oos_y = slice_years(control_eq)
    metrics = {"control": {}, "arm": {}}
    for key, frame, years in (
        ("full", control, full_y),
        ("IS", control[control["sample"] == "IS"], is_y),
        ("OOS", control[control["sample"] == "OOS"], oos_y),
    ):
        metrics["control"][key] = closed_metrics(frame, years)
    for key, frame, years in (
        ("full", arm, full_y),
        ("IS", arm[arm["sample"] == "IS"], is_y),
        ("OOS", arm[arm["sample"] == "OOS"], oos_y),
    ):
        metrics["arm"][key] = closed_metrics(frame, years)

    is_eq_c = control_eq[control_eq["date"] < IS_CUT]
    oos_eq_c = control_eq[control_eq["date"] >= IS_CUT]
    is_eq_a = arm_eq[arm_eq["date"] < IS_CUT]
    oos_eq_a = arm_eq[arm_eq["date"] >= IS_CUT]
    paths = {
        "control": path_stats(control_eq),
        "arm": path_stats(arm_eq),
        "control_is_path": path_stats(is_eq_c),
        "arm_is_path": path_stats(is_eq_a),
        "control_oos_path": path_stats(oos_eq_c),
        "arm_oos_path": path_stats(oos_eq_a),
    }

    walks = []
    for trade in control_trades:
        panel = panel_map[(trade["left"], trade["right"])]
        walks.append(published_walk(trade, panel, bt))

    def _avg(xs: list[float]) -> float:
        return float(np.mean(xs)) if xs else float("nan")

    c_mark_pcts = marked_is_pcts(control, control_trades, panel_map, bt)
    a_mark_pcts = marked_is_pcts(arm, arm_trades, panel_map, bt)
    pnfp = next(t for t in control_trades if t["left"] == "PNFP" and t["right"] == "ZION")
    pnfp_is = mark_open_before_cut(pnfp, panel_map[("PNFP", "ZION")], bt, IS_CUT)
    pnfp_2026 = {
        "date": "2026-09-30",
        "net_pct": float(pnfp["net"] / STAKE * 100.0),
        "long_px": float(pnfp["exit_long"]),
        "short_px": float(pnfp["exit_short"]),
    }
    is_mark = {
        "control_avg": _avg(c_mark_pcts),
        "control_n": len(c_mark_pcts),
        "arm_avg": _avg(a_mark_pcts),
        "arm_n": len(a_mark_pcts),
        "control_win": 100.0 * float(np.mean(np.array(c_mark_pcts) > 0)) if c_mark_pcts else float("nan"),
        "arm_win": 100.0 * float(np.mean(np.array(a_mark_pcts) > 0)) if a_mark_pcts else float("nan"),
        "PNFP/ZION": pnfp_is,
        "PNFP/ZION_2026": pnfp_2026,
    }
    verdict, verdict_why = judge(
        is_mark["control_avg"],
        is_mark["arm_avg"],
        is_mark["control_win"],
        is_mark["arm_win"],
        is_mark["control_n"],
        is_mark["arm_n"],
    )
    print(
        f"VERDICT {verdict} marked IS control {is_mark['control_avg']:.2f} arm {is_mark['arm_avg']:.2f}",
        flush=True,
    )

    print("option scan", flush=True)
    scan, opt = scan_options(menu)
    rich, cheap = extremes(scan, 5)

    OUT.mkdir(parents=True, exist_ok=True)
    control.to_csv(OUT / "trades_control.csv", index=False)
    arm.to_csv(OUT / "trades_timestop.csv", index=False)
    pd.DataFrame(walks).to_csv(OUT / "published_ticket_clock.csv", index=False)
    scan.to_csv(OUT / "options_scan.csv", index=False)
    meta_bt = {"pairs": int(len(menu)), "panels": int(len(panels)), **meta_arm}
    page = render(control, arm, metrics, paths, walks, is_mark, scan, opt, verdict, verdict_why, meta_bt)
    (OUT / "report.html").write_text(page, encoding="utf-8")
    (OUT / "BASELINE.md").write_text(
        baseline_md(metrics, paths, walks, is_mark, opt, verdict, verdict_why, meta_bt),
        encoding="utf-8",
    )
    summary = {
        "verdict": verdict,
        "verdict_why": verdict_why,
        "metrics": metrics,
        "paths": paths,
        "is_mark": is_mark,
        "walks": walks,
        "arm_pnfp": arm[(arm.left == "PNFP") & (arm.right == "ZION")].to_dict(orient="records"),
        "opt_counts": {k: v for k, v in opt.items() if k != "focus"},
        "rich": rich.to_dict(orient="records"),
        "cheap": cheap.to_dict(orient="records"),
        "focus": opt["focus"],
    }
    (OUT / "summary.json").write_text(json.dumps(_jsonable(summary), indent=2), encoding="utf-8")
    print(f"wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
