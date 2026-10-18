#!/usr/bin/env python3
"""High-water stop that stays off until the mark is n% above entry.

Research only. Does not wire DailyRun. Does not retune on out-of-sample.
Does not modify the earlier keep-40/50/60 stamp.
"""
from __future__ import annotations

import html as html_mod
import importlib.util
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
_PE = _REPO / "drive" / "paul_experiments"
_TOOLS = _REPO / "tools"
for _p in (_PE, _TOOLS, _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    ann_ror_from_closed,
    format_money,
    is_excluded_html_compare_label,
    max_dd_pct_from_closed_pnl_by_date,
    sharpe_from_closed_pnl_by_date,
)
from report_page_extras import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

STAMP = "hwm_stop_activate_at_n_20261015"
OUT = _PE / STAMP
IS_CUT = 20240101
FIXED_N = (2.0, 4.0, 5.0, 6.0, 10.0)
KS = (0.40, 0.50, 0.60, 0.70, 0.80)
K_LABEL = {0.40: "Keep 40%", 0.50: "Keep 50%", 0.60: "Keep 60%", 0.70: "Keep 70%", 0.80: "Keep 80%"}

ASK = (
    "OK. let's look at this slightly differently. we keep the same rules in place, "
    "but we don't activate the stop loss until the gain or the high water mark is n% "
    "above the entry. let's try 2, 4, 5, 6, and 10. and then also lets try the control "
    "avg return. so if it is RSI, we don't activate the stop loss until the stock is "
    "up4.65% which is the average for that system. then we try 40, 50, 60, 70, and 80 "
    "as the stop loss"
)

PLAIN = (
    "Each system keeps the trades it already has and the exit those trades already used. "
    "That current exit is the control. The new stop is the same shape as the last high-water test: "
    "once it is on, it sits at 40%, 50%, 60%, 70%, or 80% of the rise from the buy price up to the "
    "highest daily high so far (the high-water mark). The change is that this stop stays off until "
    "that high-water mark is at least n% above the buy. The hurdles are 2%, 4%, 5%, 6%, and 10%. "
    "Each system also gets one hurdle equal to its own average percent return on the trades replayed "
    "here. For Relative Strength Index (RSI), Paul said 4.65%. This page uses the average measured "
    "on these trades. If that number is not 4.65%, both numbers are shown. Until yesterday's high "
    "clears the hurdle, the system's original stop and original exit stay in force. Today's stop "
    "does not look at today's high. The entry day's high can raise the next day's mark, but it cannot "
    "turn the new stop on that same day and it cannot sell the stock on the entry day. If the new stop "
    "is not above the system's own stop, the system's stop stays (the overlay never loosens risk). "
    "If the open is already through the new stop, the sell is at the open. If the low tags the stop, "
    "the sell is at the stop. If the new stop never hits, the original exit still stands. "
    "This is not a Simple Moving Average (SMA) trail, and it is not Rocket Launcher's separate "
    "partial-exit plan (sell most at +20%, leftover stop at the entry price, leftover sold at +40%)."
)


def _load_hwm1():
    path = _TOOLS / "hwm_stop_keep_40_50_60_20261015.py"
    name = "hwm_stop_keep_40_50_60_20261015"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _th(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{typ}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _ordinal(ymd: np.ndarray) -> np.ndarray:
    y = (ymd // 10000).astype(np.int64)
    m = ((ymd // 100) % 100).astype(np.int64)
    d = (ymd % 100).astype(np.int64)
    leap = (y % 4 == 0) & ((y % 100 != 0) | (y % 400 == 0))
    before = np.array([0, 0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334], dtype=np.int64)
    y1 = y - 1
    return y1 * 365 + y1 // 4 - y1 // 100 + y1 // 400 + before[m] + ((m > 2) & leap).astype(np.int64) + d


def _calendar_days_vec(opened: np.ndarray, closed: np.ndarray, book_days: np.ndarray) -> np.ndarray:
    delta = _ordinal(closed) - _ordinal(opened)
    out = delta.astype(np.float64)
    use_book = delta <= 0
    bd = np.where(np.isfinite(book_days) & (book_days > 0), book_days, np.nan)
    out = np.where(use_book & np.isfinite(bd), bd, out)
    out = np.where(use_book & ~np.isfinite(bd), 1.0, out)
    out = np.where(out > 0, out, 1.0)
    return out.astype(np.float64)


def _ymd_to_date(ymd: int) -> date:
    return date(int(ymd) // 10000, (int(ymd) // 100) % 100, int(ymd) % 100)


def _self_test_walk() -> None:
    """Lock the activation delay against a few handmade bars."""
    dates = np.array([20200102, 20200103, 20200106], dtype=np.int64)
    opens = np.array([100.0, 100.2, 100.5], dtype=np.float64)
    highs = np.array([101.0, 102.0, 103.0], dtype=np.float64)
    lows = np.array([99.0, 100.0, 100.4], dtype=np.float64)
    bars = (dates, opens, highs, lows)
    th = np.array([2.0, 5.0], dtype=np.float64)
    ks = np.array([0.40, 0.80], dtype=np.float64)
    hit, px, ymd, scratch_gap, scratch_stop, diag = _walk_one(
        bars, 20200102, 20200106, 100.0, 90.0, th, ks
    )
    # Day 2 is only +1% from the entry high, so the 2% hurdle is still off.
    # Day 3: mark is 102 (+2%). Keep 40% stops at 100.8; the open 100.5 gaps through.
    # Keep 80% stops at 101.6; the open gaps through that too. 5% never turns on.
    assert hit[0, 0] == 1 and abs(px[0, 0] - 100.5) < 1e-9 and int(ymd[0, 0]) == 20200106
    assert hit[0, 1] == 1 and abs(px[0, 1] - 100.5) < 1e-9
    assert hit[1, 0] == 0 and hit[1, 1] == 0
    # Jan 6 is the second session after entry, so a sub-1% open is not a next-morning scratch.
    assert int(scratch_gap[0, 0]) == 0
    # No-delay keep 40% sells Jan 3 at the open 100.2 (+0.2%), which is a scratch.
    assert diag["hit"] == 1 and diag["scratch_gap"] == 1 and abs(diag["px"] - 100.2) < 1e-9

    # Entry high already +10%. Next open 104. Original stop 106 blocks keep 40% (stop 104)
    # and allows keep 80% (stop 108).
    dates2 = np.array([20200102, 20200103], dtype=np.int64)
    opens2 = np.array([100.0, 104.0], dtype=np.float64)
    highs2 = np.array([110.0, 111.0], dtype=np.float64)
    lows2 = np.array([99.0, 103.0], dtype=np.float64)
    hit2, px2, ymd2, sg2, ss2, diag2 = _walk_one(
        (dates2, opens2, highs2, lows2), 20200102, 20200103, 100.0, 106.0, th, ks
    )
    assert hit2[0, 0] == 0  # keep 40% at 104 is not above the original stop 106
    assert hit2[0, 1] == 1 and abs(px2[0, 1] - 104.0) < 1e-9 and int(ymd2[0, 1]) == 20200103
    assert int(sg2[0, 1]) == 0  # +4% is not a sub-1% scratch
    # +10% clears both the 2% and the 5% hurdles. Keep 40% stays blocked. Keep 80% hits.
    assert hit2[1, 0] == 0
    assert hit2[1, 1] == 1 and abs(px2[1, 1] - 104.0) < 1e-9

    # Same-day round trip cannot activate.
    hit3, px3, _, _, _, diag3 = _walk_one(
        (dates2, opens2, highs2, lows2), 20200102, 20200102, 100.0, 90.0, th, ks
    )
    assert hit3.sum() == 0 and diag3["hit"] == 0

    # Missing path.
    assert _walk_one(None, 20200102, 20200106, 100.0, 90.0, th, ks) == "missing"
    print("self-test ok", flush=True)


def _walk_one(
    bars,
    opened: int,
    closed: int,
    entry: float,
    stop: float,
    th: np.ndarray,
    ks: np.ndarray,
):
    """Return hit tag / price / ymd / scratch flags shaped (T, K), plus a no-delay keep-40% diagnostic.

    Tag 1 = sell at the open. Tag 2 = sell at the stop. 0 = original exit stands.
    A return of 'missing' means the daily path cannot cover the hold.
    """
    t_n = int(th.shape[0])
    k_n = int(ks.shape[0])
    shape = (t_n, k_n)
    if bars is None:
        return "missing"
    if closed <= opened:
        return (
            np.zeros(shape, np.uint8),
            np.zeros(shape, np.float64),
            np.zeros(shape, np.int64),
            np.zeros(shape, np.uint8),
            np.zeros(shape, np.uint8),
            {"hit": 0, "scratch_gap": 0, "scratch_stop": 0, "px": 0.0, "ymd": 0},
        )
    dates, opens, highs, lows = bars
    if dates.size == 0 or int(dates[-1]) < closed:
        return "missing"
    i0 = int(np.searchsorted(dates, opened, side="left"))
    if i0 >= dates.size:
        return "missing"
    hwm = float(entry)
    if int(dates[i0]) == opened:
        hi0 = float(highs[i0])
        if hi0 == hi0 and hi0 > hwm:
            hwm = hi0
        i = i0 + 1
    else:
        i = i0
    hit = np.zeros(shape, np.uint8)
    px = np.zeros(shape, np.float64)
    ymd = np.zeros(shape, np.int64)
    scratch_gap = np.zeros(shape, np.uint8)
    scratch_stop = np.zeros(shape, np.uint8)
    stop_ok = stop == stop and stop > 0.0
    pending = t_n * k_n
    seen_after = False
    first_after = True
    diag = {"hit": 0, "scratch_gap": 0, "scratch_stop": 0, "px": 0.0, "ymd": 0}
    n = int(dates.size)
    while i < n and int(dates[i]) <= closed and (pending > 0 or diag["hit"] == 0):
        di = int(dates[i])
        if di > opened:
            seen_after = True
            if hwm > entry:
                gain = hwm - entry
                gain_pct = gain / entry * 100.0
                op = float(opens[i])
                lo = float(lows[i])
                if diag["hit"] == 0:
                    dpx = entry + 0.40 * gain
                    if not (stop_ok and not (dpx > stop)):
                        filled = False
                        fill_px = 0.0
                        kind = 0
                        if op == op and op <= dpx:
                            filled, fill_px, kind = True, op, 1
                        elif lo == lo and lo <= dpx:
                            filled, fill_px, kind = True, dpx, 2
                        if filled:
                            pnl = (fill_px - entry) / entry * 100.0
                            diag["hit"] = 1
                            diag["px"] = fill_px
                            diag["ymd"] = di
                            if first_after and 0.0 <= pnl < 1.0:
                                if kind == 1:
                                    diag["scratch_gap"] = 1
                                else:
                                    diag["scratch_stop"] = 1
                for ti in range(t_n):
                    if gain_pct < float(th[ti]):
                        continue
                    for ki in range(k_n):
                        if hit[ti, ki]:
                            continue
                        stop_px = entry + float(ks[ki]) * gain
                        if stop_ok and not (stop_px > stop):
                            continue
                        kind = 0
                        fill_px = 0.0
                        if op == op and op <= stop_px:
                            kind, fill_px = 1, op
                        elif lo == lo and lo <= stop_px:
                            kind, fill_px = 2, stop_px
                        if kind:
                            hit[ti, ki] = kind
                            px[ti, ki] = fill_px
                            ymd[ti, ki] = di
                            pending -= 1
                            pnl = (fill_px - entry) / entry * 100.0
                            if first_after and 0.0 <= pnl < 1.0:
                                if kind == 1:
                                    scratch_gap[ti, ki] = 1
                                else:
                                    scratch_stop[ti, ki] = 1
            first_after = False
        hi = float(highs[i])
        if hi == hi and hi > hwm:
            hwm = hi
        i += 1
        if pending == 0 and diag["hit"] == 1:
            break
    if not seen_after:
        return "missing"
    return hit, px, ymd, scratch_gap, scratch_stop, diag


def _prepare_book_days(opened: np.ndarray, closed: np.ndarray, days: np.ndarray) -> np.ndarray:
    cal = _calendar_days_vec(opened, closed, days)
    good = np.isfinite(days) & (days > 0)
    return np.where(good, days, cal).astype(np.float64)


def _notion(book_pnl: np.ndarray, book_d: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        notion = np.where(
            np.abs(book_pnl) > 1e-6,
            np.abs(book_d) / (np.abs(book_pnl) / 100.0),
            np.nan,
        )
    notion = np.where(np.isfinite(notion) & (notion > 0), notion, np.nan)
    zero = book_pnl == 0
    notion = np.where(np.isfinite(notion), notion, np.where(zero, np.abs(book_d), np.nan))
    return notion


def replay_system(df: pd.DataFrame, dollars: np.ndarray, ohlc: dict, thresholds: np.ndarray) -> dict[str, Any]:
    ks = np.array(KS, dtype=np.float64)
    th = np.array(thresholds, dtype=np.float64)
    t_n = int(th.shape[0])
    k_n = int(ks.shape[0])
    n = len(df)
    symbols = df["symbol"].to_numpy()
    opened = df["opened"].to_numpy(dtype=np.int64)
    closed = df["closed"].to_numpy(dtype=np.int64)
    entry = df["entry"].to_numpy(dtype=np.float64)
    book_pnl = df["pnl"].to_numpy(dtype=np.float64)
    book_days_raw = df["days"].to_numpy(dtype=np.float64)
    stop = df["stop"].to_numpy(dtype=np.float64)
    side = df["side"].astype(str).to_numpy()
    industry = df["industry"].astype(str).to_numpy()
    exit_type = df["exit_type"].astype(str).to_numpy()
    book_days = _prepare_book_days(opened, closed, book_days_raw)
    notion = _notion(book_pnl, dollars)

    short_skipped = 0
    missing = 0
    groups: dict[str, list[int]] = defaultdict(list)
    for i, sym in enumerate(symbols):
        s = str(side[i])
        if s not in {"LONG", "L", "", "NAN"}:
            short_skipped += 1
            continue
        groups[str(sym)].append(i)
    long_idx = np.array([i for idxs in groups.values() for i in idxs], dtype=np.int64)
    n_long = int(long_idx.size)
    tag_all = np.zeros((n_long, t_n, k_n), dtype=np.uint8)
    px_all = np.zeros((n_long, t_n, k_n), dtype=np.float64)
    ymd_all = np.zeros((n_long, t_n, k_n), dtype=np.int64)
    sg_all = np.zeros((n_long, t_n, k_n), dtype=np.uint8)
    ss_all = np.zeros((n_long, t_n, k_n), dtype=np.uint8)
    kept_pos: list[int] = []
    diag_gap = 0
    diag_stop = 0
    diag_hit = 0
    pos_of = {int(i): p for p, i in enumerate(long_idx.tolist())}

    seen = 0
    for sym, idxs in groups.items():
        bars = ohlc.get(sym)
        for i in idxs:
            seen += 1
            if seen % 100000 == 0:
                print(f"    replay {seen:,}", flush=True)
            walked = _walk_one(
                bars, int(opened[i]), int(closed[i]), float(entry[i]), float(stop[i]), th, ks
            )
            if walked == "missing":
                missing += 1
                continue
            hit, px, ymd, scratch_gap, scratch_stop, diag = walked
            p = pos_of[i]
            tag_all[p] = hit
            px_all[p] = px
            ymd_all[p] = ymd
            sg_all[p] = scratch_gap
            ss_all[p] = scratch_stop
            kept_pos.append(p)
            diag_hit += int(diag["hit"])
            diag_gap += int(diag["scratch_gap"])
            diag_stop += int(diag["scratch_stop"])

    if not kept_pos:
        return {
            "n": 0,
            "short_skipped": short_skipped,
            "missing_ohlc": missing,
            "diag_hit": diag_hit,
            "diag_gap": diag_gap,
            "diag_stop": diag_stop,
        }

    kp = np.array(kept_pos, dtype=np.int64)
    ix = long_idx[kp]
    tag = tag_all[kp]
    px = px_all[kp]
    exit_ymd = ymd_all[kp]
    scratch_gap = sg_all[kp]
    scratch_stop = ss_all[kp]
    del tag_all, px_all, ymd_all, sg_all, ss_all

    return {
        "n": int(ix.size),
        "short_skipped": short_skipped,
        "missing_ohlc": missing,
        "diag_hit": diag_hit,
        "diag_gap": diag_gap,
        "diag_stop": diag_stop,
        "ix": ix,
        "tag": tag,
        "px": px,
        "exit_ymd": exit_ymd,
        "scratch_gap": scratch_gap,
        "scratch_stop": scratch_stop,
        "opened": opened[ix],
        "closed": closed[ix],
        "entry": entry[ix],
        "book_pnl": book_pnl[ix],
        "book_d": dollars[ix],
        "book_days": book_days[ix],
        "notion": notion[ix],
        "symbol": symbols[ix],
        "industry": industry[ix],
        "exit_type": exit_type[ix],
        "t_n": t_n,
        "k_n": k_n,
    }


def _arm_columns(pack: dict[str, Any], ti: int, ki: int) -> dict[str, np.ndarray]:
    tag = pack["tag"][:, ti, ki]
    hit = tag > 0
    entry = pack["entry"]
    new_pnl = (pack["px"][:, ti, ki] - entry) / entry * 100.0
    pnl = np.where(hit, new_pnl, pack["book_pnl"])
    notion = pack["notion"]
    new_d = np.where(np.isfinite(notion) & (notion > 0), notion * new_pnl / 100.0, pack["book_d"])
    pnl_d = np.where(hit, new_d, pack["book_d"])
    exit_ymd = np.where(hit, pack["exit_ymd"][:, ti, ki], pack["closed"])
    days = np.where(hit, _calendar_days_vec(pack["opened"], exit_ymd.astype(np.int64), pack["book_days"]), pack["book_days"])
    xt = pack["exit_type"].astype(object).copy()
    xt[tag == 1] = "HWM_GAP"
    xt[tag == 2] = "HWM_STOP"
    return {
        "pnl": pnl.astype(np.float64),
        "pnl_d": pnl_d.astype(np.float64),
        "days": days.astype(np.float64),
        "opened": pack["opened"],
        "closed": exit_ymd.astype(np.int64),
        "symbol": pack["symbol"],
        "industry": pack["industry"],
        "exit_type": xt,
        "hit": hit,
    }


def _slice_mask(opened: np.ndarray, mode: str) -> np.ndarray:
    if mode == "FULL":
        return np.ones(opened.shape[0], dtype=bool)
    if mode == "IS":
        return opened < IS_CUT
    if mode == "OOS":
        return opened >= IS_CUT
    raise ValueError(mode)


def _avg_ann(pnl: np.ndarray, pnl_d: np.ndarray, days: np.ndarray, cash: float) -> dict[str, Any]:
    n = int(pnl.size)
    if n == 0:
        return {"n": 0, "avg": None, "ann": None, "ann_note": "No trades in this slice."}
    avg = float(np.mean(pnl))
    total = float(np.sum(pnl_d))
    d_ok = days[days > 0]
    avg_days = float(d_ok.mean()) if d_ok.size else None
    ann = None
    note = ""
    if cash > 0 and avg_days and avg_days > 0:
        ann = ann_ror_from_closed(total_pnl=total, n_trades=n, avg_days_held=avg_days, brt_cash=cash)
        if ann is None:
            note = "Annualized rate of return could not be computed (base not positive)."
    else:
        note = "Annualized rate of return could not be computed (missing cash or days held)."
    return {"n": n, "avg": avg, "ann": None if ann is None else float(ann), "ann_note": note}


def _full_metrics(cols: dict[str, np.ndarray], mask: np.ndarray, cash: float) -> dict[str, Any]:
    pnl = cols["pnl"][mask]
    pnl_d = cols["pnl_d"][mask]
    days = cols["days"][mask]
    opened = cols["opened"][mask]
    closed = cols["closed"][mask]
    symbols = cols["symbol"][mask]
    industry = cols["industry"][mask]
    exit_type = cols["exit_type"][mask]
    n = int(pnl.size)
    base = _avg_ann(pnl, pnl_d, days, cash)
    empty_mix: dict[str, int] = {}
    if n == 0:
        return {
            **base,
            "wins": 0,
            "losses": 0,
            "win_pct": None,
            "avg_pnl_pct": None,
            "avg_pnl_pct_wo_max": None,
            "expectancy_d": None,
            "expectancy_pct": None,
            "avg_win_pct": None,
            "avg_loss_pct": None,
            "wl_count": None,
            "wl_dollars": None,
            "profit_factor": None,
            "ann_ror": None,
            "max_dd": None,
            "calmar": None,
            "sharpe": None,
            "ppcd": None,
            "capital_days": 0.0,
            "avg_days": None,
            "median_days": None,
            "p90_days": None,
            "losing_streak": None,
            "pct_max_symbol": None,
            "pct_max_trade": None,
            "pct_max_industry": None,
            "pct_top10": None,
            "pct_bottom10": None,
            "outlier_win_pct": None,
            "trades_per_year": None,
            "exit_mix": empty_mix,
        }
    wins_m = pnl > 0
    loss_m = pnl < 0
    wins = int(wins_m.sum())
    losses = int(loss_m.sum())
    win_pct = 100.0 * wins / n
    avg_pct = float(np.mean(pnl))
    wo = float(np.mean(np.delete(pnl, int(np.argmax(pnl))))) if n > 1 else avg_pct
    total = float(pnl_d.sum())
    sum_w = float(pnl_d[pnl_d > 0].sum())
    sum_l = float((-pnl_d[pnl_d < 0]).sum())
    pf = (sum_w / sum_l) if sum_l > 0 else None
    wl_c = (wins / losses) if losses else None
    avg_win = float(pnl[wins_m].mean()) if wins else None
    avg_loss = float(pnl[loss_m].mean()) if losses else None
    d_ok = days[days > 0]
    capital_days = float(d_ok.sum()) if d_ok.size else 0.0
    avg_days = float(d_ok.mean()) if d_ok.size else None
    med_days = float(np.median(d_ok)) if d_ok.size else None
    p90_days = float(np.percentile(d_ok, 90)) if d_ok.size else None
    ppcd = (total / capital_days) if capital_days > 0 else None
    ann = base["ann"]
    # Exit-date equity. Aggregate first so MUD does not build one date object per trade.
    g = pd.Series(pnl_d).groupby(pd.Series(closed)).sum()
    dated = [(_ymd_to_date(int(i)), float(v)) for i, v in g.items()]
    mdd = max_dd_pct_from_closed_pnl_by_date(dated, initial_account=DEFAULT_INITIAL_ACCOUNT)
    sharpe = sharpe_from_closed_pnl_by_date(dated, initial_account=DEFAULT_INITIAL_ACCOUNT)
    calmar = None
    if ann is not None and mdd is not None and abs(float(mdd)) > 1e-12:
        calmar = float(ann) / abs(float(mdd))
    order = np.lexsort((symbols.astype(str), closed))
    streak = 0
    best_streak = 0
    pnl_ord = pnl[order]
    for v in pnl_ord:
        if v < 0:
            streak += 1
            if streak > best_streak:
                best_streak = streak
        else:
            streak = 0

    def _share(part: float) -> Optional[float]:
        if total > 1e-9:
            return 100.0 * part / total
        return None

    by_sym = pd.Series(pnl_d).groupby(pd.Series(symbols.astype(str))).sum()
    ind_s = pd.Series(industry.astype(str))
    ind_ok = ~ind_s.str.upper().isin(["", "NAN", "NONE"])
    by_ind = pd.Series(pnl_d[ind_ok.to_numpy()]).groupby(ind_s[ind_ok]).sum() if ind_ok.any() else pd.Series(dtype=float)
    pct_sym = _share(float(by_sym.max())) if len(by_sym) else None
    pct_trade = _share(float(np.max(pnl_d))) if n else None
    pct_ind = _share(float(by_ind.max())) if len(by_ind) else None
    ordered_d = np.sort(pnl_d)
    top10 = float(ordered_d[-10:].sum()) if n else 0.0
    bot10 = float(ordered_d[: min(10, n)].sum()) if n else 0.0
    pct_top = _share(top10)
    pct_bot = _share(bot10)
    win_dollars = pnl_d[pnl_d > 0]
    outlier = None
    if win_dollars.size and float(win_dollars.sum()) > 0:
        outlier = 100.0 * float(win_dollars.max()) / float(win_dollars.sum())
    if n >= 2:
        span = int(_ordinal(opened).max() - _ordinal(opened).min())
        tpy = n / (span / 365.25) if span > 0 else None
    else:
        tpy = None
    mix = dict(Counter(str(x) for x in exit_type))
    return {
        "n": n,
        "wins": wins,
        "losses": losses,
        "win_pct": win_pct,
        "avg_pnl_pct": avg_pct,
        "avg_pnl_pct_wo_max": wo,
        "expectancy_d": float(pnl_d.mean()),
        "expectancy_pct": avg_pct,
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss,
        "wl_count": wl_c,
        "wl_dollars": pf,
        "profit_factor": pf,
        "ann_ror": ann,
        "max_dd": None if mdd is None else float(mdd),
        "calmar": calmar,
        "sharpe": None if sharpe is None else float(sharpe),
        "ppcd": ppcd,
        "capital_days": capital_days,
        "avg_days": avg_days,
        "median_days": med_days,
        "p90_days": p90_days,
        "losing_streak": best_streak,
        "pct_max_symbol": pct_sym,
        "pct_max_trade": pct_trade,
        "pct_max_industry": pct_ind,
        "pct_top10": pct_top,
        "pct_bottom10": pct_bot,
        "outlier_win_pct": outlier,
        "trades_per_year": tpy,
        "exit_mix": mix,
        "ann_note": base["ann_note"],
    }


def _pick_is_winner(grid_is: list[list[dict[str, Any]]]) -> tuple[int, int, str]:
    best = (-1, -1)
    best_avg = -1e300
    best_ann = -1e300
    ties = 0
    for ti, row in enumerate(grid_is):
        for ki, cell in enumerate(row):
            avg = cell.get("avg")
            if avg is None or not math.isfinite(float(avg)):
                continue
            ann = cell.get("ann")
            ann_v = float(ann) if ann is not None and math.isfinite(float(ann)) else -1e300
            avg_v = float(avg)
            if avg_v > best_avg + 1e-12 or (abs(avg_v - best_avg) <= 1e-12 and ann_v > best_ann + 1e-12):
                best = (ti, ki)
                best_avg = avg_v
                best_ann = ann_v
                ties = 1
            elif abs(avg_v - best_avg) <= 1e-12 and abs(ann_v - best_ann) <= 1e-9:
                ties += 1
    note = ""
    if ties > 1:
        note = (
            f"{ties} in-sample arms tied on average return and annualized rate of return. "
            "The reported arm is the earliest hurdle, then the smaller keep fraction."
        )
        # Re-scan for the stable tie: lowest ti then lowest ki among exact ties.
        for ti, row in enumerate(grid_is):
            for ki, cell in enumerate(row):
                avg = cell.get("avg")
                ann = cell.get("ann")
                if avg is None:
                    continue
                ann_v = float(ann) if ann is not None and math.isfinite(float(ann)) else -1e300
                if abs(float(avg) - best_avg) <= 1e-12 and abs(ann_v - best_ann) <= 1e-9:
                    best = (ti, ki)
                    break
            else:
                continue
            break
    return best[0], best[1], note


def _jsonable(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (np.floating, np.integer)):
        o = o.item()
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, (date,)):
        return o.isoformat()
    return o


def run_system(job: tuple[str, str, bool]) -> dict[str, Any]:
    code, label, research = job
    hwm1 = _load_hwm1()
    path = hwm1._DRIVE / f"{code}_LatestRun_Closed.csv"
    print(f"=== {code} ===", flush=True)
    if not path.exists():
        print(f"  SKIP missing {path}", flush=True)
        return {"code": code, "label": label, "research": research, "skip": f"no closed book at {path.name}"}
    df, meta = hwm1.load_trades(code)
    print(f"  loaded {len(df):,} from {meta['rows_file']:,}", flush=True)
    try:
        cash, cash_src, dollars = hwm1.slot_cash(df, code)
    except SystemExit as exc:
        return {"code": code, "label": label, "research": research, "skip": str(exc)}
    # Long symbols only. Shorts are counted inside the replay.
    side = df["side"].astype(str)
    long_syms = set(df.loc[side.isin(["LONG", "L", "", "NAN"]), "symbol"].astype(str).unique().tolist())
    print(f"  ohlc symbols {len(long_syms):,} cash={cash:,.2f}", flush=True)
    ohlc = hwm1.load_ohlc(long_syms)
    print(f"  ohlc hit {len(ohlc):,}", flush=True)

    # Control average uses the same trades the overlay will score. Coverage is decided
    # inside the walk, so do one replay. The control-average hurdle is applied by a
    # second pass only when we know that average. First pass uses the five fixed hurdles
    # plus a placeholder; we then... two full walks of MUD is expensive.
    # Compute the kept-set average with a cheap coverage check, then one overlay walk.
    opened = df["opened"].to_numpy(dtype=np.int64)
    closed = df["closed"].to_numpy(dtype=np.int64)
    entry = df["entry"].to_numpy(dtype=np.float64)
    pnl = df["pnl"].to_numpy(dtype=np.float64)
    side_a = df["side"].astype(str).to_numpy()
    sym_a = df["symbol"].astype(str).to_numpy()
    eligible = []
    for i in range(len(df)):
        if str(side_a[i]) not in {"LONG", "L", "", "NAN"}:
            continue
        if int(closed[i]) <= int(opened[i]):
            if float(entry[i]) > 0 and math.isfinite(float(pnl[i])):
                eligible.append(i)
            continue
        bars = ohlc.get(str(sym_a[i]))
        if bars is None:
            continue
        dates = bars[0]
        if dates.size == 0 or int(dates[-1]) < int(closed[i]):
            continue
        i0 = int(np.searchsorted(dates, int(opened[i]), side="left"))
        if i0 >= dates.size:
            continue
        # Need at least one bar strictly after entry and on or before the close,
        # matching the walk. Same-day trades are already included above.
        if int(dates[i0]) == int(opened[i]):
            j = i0 + 1
        else:
            j = i0
        if j >= dates.size or int(dates[j]) > int(closed[i]):
            continue
        eligible.append(i)
    if not eligible:
        return {
            "code": code,
            "label": label,
            "research": research,
            "skip": "no usable trades after the daily-bar check",
        }
    elig = np.array(eligible, dtype=np.int64)
    ctrl_avg = float(np.mean(pnl[elig]))
    print(f"  control avg return on replay set {ctrl_avg:.6f}% (n={elig.size:,})", flush=True)
    thresholds = list(FIXED_N) + [ctrl_avg]
    # Guard a duplicate of a fixed hurdle: still keep it as its own last row.
    pack = replay_system(df, dollars, ohlc, np.array(thresholds, dtype=np.float64))
    if pack.get("n", 0) == 0:
        return {
            "code": code,
            "label": label,
            "research": research,
            "skip": (
                f"no usable OHLC path; shorts left out {pack.get('short_skipped', 0)}; "
                f"missing {pack.get('missing_ohlc', 0)}"
            ),
        }
    # The pre-check and the walk must agree on N. If not, recompute the hurdle from the walk.
    walked_avg = float(np.mean(pack["book_pnl"]))
    if abs(walked_avg - ctrl_avg) > 1e-6 or pack["n"] != int(elig.size):
        print(
            f"  NOTE coverage mismatch precheck n={elig.size:,} avg={ctrl_avg:.6f} "
            f"walk n={pack['n']:,} avg={walked_avg:.6f}; replaying with the walk average",
            flush=True,
        )
        ctrl_avg = walked_avg
        thresholds = list(FIXED_N) + [ctrl_avg]
        pack = replay_system(df, dollars, ohlc, np.array(thresholds, dtype=np.float64))

    t_n = pack["t_n"]
    k_n = pack["k_n"]
    grid: dict[str, list[list[dict[str, Any]]]] = {m: [] for m in ("FULL", "IS", "OOS")}
    scratch = {"gap": [], "stop": []}
    for ti in range(t_n):
        for mode in ("FULL", "IS", "OOS"):
            if len(grid[mode]) <= ti:
                grid[mode].append([])
        gap_row = []
        stop_row = []
        for ki in range(k_n):
            cols = _arm_columns(pack, ti, ki)
            for mode in ("FULL", "IS", "OOS"):
                mask = _slice_mask(cols["opened"], mode)
                grid[mode][ti].append(_avg_ann(cols["pnl"][mask], cols["pnl_d"][mask], cols["days"][mask], cash))
            gap_row.append(int(pack["scratch_gap"][:, ti, ki].sum()))
            stop_row.append(int(pack["scratch_stop"][:, ti, ki].sum()))
            del cols
        scratch["gap"].append(gap_row)
        scratch["stop"].append(stop_row)

    ti_w, ki_w, tie_note = _pick_is_winner(grid["IS"])
    # Control columns: tag zeros, book exit. Build from a dummy arm then overwrite.
    ctrl_cols = _arm_columns(pack, 0, 0)
    ctrl_cols = {
        "pnl": pack["book_pnl"],
        "pnl_d": pack["book_d"],
        "days": pack["book_days"],
        "opened": pack["opened"],
        "closed": pack["closed"],
        "symbol": pack["symbol"],
        "industry": pack["industry"],
        "exit_type": pack["exit_type"],
        "hit": np.zeros(pack["n"], dtype=bool),
    }
    win_cols = _arm_columns(pack, ti_w, ki_w) if ti_w >= 0 else None
    metrics: dict[str, dict[str, dict[str, Any]]] = {}
    for mode in ("FULL", "IS", "OOS"):
        mask = _slice_mask(ctrl_cols["opened"], mode)
        metrics[mode] = {"control": _full_metrics(ctrl_cols, mask, cash)}
        if win_cols is not None:
            metrics[mode]["best"] = _full_metrics(win_cols, mask, cash)
    # N must match across keep columns.
    for mode in ("FULL", "IS", "OOS"):
        n0 = metrics[mode]["control"]["n"]
        for row in grid[mode]:
            for cell in row:
                if cell["n"] != n0:
                    raise RuntimeError(f"{code} {mode} N {cell['n']} != control {n0}")

    hurdle_labels = [f"{int(v)}%" for v in FIXED_N] + [f"Control avg ({ctrl_avg:.2f}%)"]
    winner = None
    if ti_w >= 0:
        is_cell = grid["IS"][ti_w][ki_w]
        is_ctrl = metrics["IS"]["control"]
        beats = (
            is_cell["avg"] is not None
            and is_ctrl.get("avg_pnl_pct") is not None
            and float(is_cell["avg"]) > float(is_ctrl["avg_pnl_pct"])
        )
        winner = {
            "ti": ti_w,
            "ki": ki_w,
            "hurdle": hurdle_labels[ti_w],
            "hurdle_pct": float(thresholds[ti_w]),
            "keep": K_LABEL[KS[ki_w]],
            "k": KS[ki_w],
            "is_avg": is_cell["avg"],
            "is_ann": is_cell["ann"],
            "is_ann_note": is_cell["ann_note"],
            "beats": bool(beats),
            "tie_note": tie_note,
            "scratch_gap": scratch["gap"][ti_w][ki_w],
            "scratch_stop": scratch["stop"][ti_w][ki_w],
        }
    result = {
        "code": code,
        "label": label,
        "research": research,
        "skip": "",
        "cash": float(cash),
        "cash_src": cash_src,
        "stop_col": meta.get("stop_col") or "",
        "ctrl_avg": ctrl_avg,
        "paul_rsi_cited": 4.65 if code == "RSI" else None,
        "n_full": metrics["FULL"]["control"]["n"],
        "n_is": metrics["IS"]["control"]["n"],
        "n_oos": metrics["OOS"]["control"]["n"],
        "short_skipped": pack["short_skipped"],
        "missing_ohlc": pack["missing_ohlc"],
        "diag_hit": pack["diag_hit"],
        "diag_gap": pack["diag_gap"],
        "diag_stop": pack["diag_stop"],
        "hurdle_labels": hurdle_labels,
        "thresholds": [float(x) for x in thresholds],
        "grid": grid,
        "scratch_gap": scratch["gap"],
        "scratch_stop": scratch["stop"],
        "metrics": metrics,
        "winner": winner,
    }
    is_c = metrics["IS"]["control"]
    print(
        f"  {code} N={result['n_full']:,} ctrl_avg={ctrl_avg:.4f} "
        f"IS ctrl {is_c.get('avg_pnl_pct')} winner {winner}",
        flush=True,
    )
    return result


def _count_trades(n: int) -> str:
    n = int(n)
    return f"{n:,} trade" if n == 1 else f"{n:,} trades"


def _fmt_pct(v: Any) -> str:
    if v is None:
        return "—"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(x):
        return "—"
    return f"{x:.2f}%"


def _fmt_cell(v: Any, kind: str) -> str:
    if v is None:
        return "—"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return html_mod.escape(str(v))
    if not math.isfinite(x):
        return "—"
    if kind == "money":
        return html_mod.escape(format_money(x))
    if kind == "int":
        return f"{int(round(x)):,}"
    if kind == "pct":
        return f"{x:.2f}%"
    return f"{x:.2f}"


def _fmt_delta(v: Optional[float], kind: str) -> str:
    if v is None or not math.isfinite(v):
        return "—"
    if kind == "money":
        shown = format_money(v)
        if v > 0:
            shown = "+" + shown
        return html_mod.escape(shown)
    body = _fmt_cell(v, kind if kind != "int" else "num")
    if v > 0:
        return "+" + body
    return body


def _cell_html(full: dict, isec: dict, oos: dict) -> str:
    def line(cell: dict, tag: str) -> str:
        avg = _fmt_pct(cell.get("avg"))
        ann = _fmt_pct(cell.get("ann"))
        note = cell.get("ann_note") or ""
        title = f' title="{html_mod.escape(note)}"' if note and cell.get("ann") is None else ""
        return f'<div{title}>{avg} {html_mod.escape(tag)} · {ann} Ann</div>'

    # First characters are the full-book average so a header click sorts on that.
    return line(full, "full") + line(isec, "IS") + line(oos, "OOS")


def _judge_sentence(res: dict[str, Any]) -> str:
    w = res.get("winner") or {}
    is_c = res["metrics"]["IS"]["control"]
    if not is_c.get("n"):
        return "No in-sample trades (entry before 2024-01-01). Full book and out-of-sample are report-only."
    if not w:
        return "In-sample overlay could not be scored."
    ctrl_avg = is_c.get("avg_pnl_pct")
    ctrl_ann = is_c.get("ann_ror")
    bits = [
        (
            f"Highest in-sample average return is activate at {w['hurdle']} and {w['keep']}: "
            f"average return {_fmt_pct(w['is_avg'])} and annualized rate of return {_fmt_pct(w['is_ann'])}, "
            f"versus the control {_fmt_pct(ctrl_avg)} and {_fmt_pct(ctrl_ann)}."
        )
    ]
    if w.get("tie_note"):
        bits.append(w["tie_note"])
    if w.get("beats"):
        bits.append("That in-sample average return is above the control. Research only. Not gold. Not DailyRun.")
    else:
        bits.append(
            "That arm does not beat the control on in-sample average return. "
            "No activation hurdle and keep fraction on this page beat the control on in-sample average return."
        )
    # Scratch: no-delay keep 40% versus this arm, full book.
    bits.append(
        f"Next-morning sells at the open for a gain under 1% (the scratch from the first test): "
        f"{_count_trades(res['diag_gap'])} with no activation delay and keep 40%, "
        f"and {_count_trades(w['scratch_gap'])} on this in-sample arm. "
        f"Next-morning stop fills under 1% are {_count_trades(res['diag_stop'])} with no delay "
        f"and {_count_trades(w['scratch_stop'])} on this arm."
    )
    oos_c = res["metrics"]["OOS"]["control"]
    oos_b = res["metrics"]["OOS"].get("best") or {}
    if w.get("beats") and oos_c.get("n") and oos_b.get("n"):
        if (
            oos_c.get("avg_pnl_pct") is not None
            and oos_b.get("avg_pnl_pct") is not None
            and float(oos_b["avg_pnl_pct"]) < float(oos_c["avg_pnl_pct"])
        ):
            bits.append(
                "Out-of-sample average return for that same arm is below the control. "
                "Reported only. The hurdle and keep fraction were not changed to chase out-of-sample."
            )
        else:
            bits.append(
                "Out-of-sample average return for that same arm is not below the control. "
                "Still report-only. Not a promotion."
            )
    elif not w.get("beats"):
        bits.append("Out-of-sample was not used to pick a different arm.")
    return " ".join(bits)


def render(results: list[dict[str, Any]], skipped: list[dict[str, Any]]) -> str:
    hwm1 = _load_hwm1()
    metric_spec = hwm1.METRIC_SPEC

    blocks = []
    for res in results:
        mfull = res["metrics"]["FULL"]["control"]
        mis = res["metrics"]["IS"]["control"]
        moos = res["metrics"]["OOS"]["control"]
        rsi_note = ""
        if res["code"] == "RSI":
            rsi_note = (
                f" Paul said 4.65% for Relative Strength Index (RSI). "
                f"The full-book average on the trades replayed here is {res['ctrl_avg']:.4f}% "
                f"(shown as {res['ctrl_avg']:.2f}% on the control-avg row). "
                f"The in-sample control average is {_fmt_pct(mis.get('avg_pnl_pct'))}, "
                f"which lines up with the 4.65% Paul quoted. "
                f"The first high-water page's full-book RSI control average was 4.42%. "
                f"The hurdle is the full-book average. 4.65% was not forced."
            )
        heads = [_th("Activation", "text")]
        for k in KS:
            heads.append(_th(K_LABEL[k], "num"))
        body = []
        for ti, lab in enumerate(res["hurdle_labels"]):
            cells = [f"<td>{html_mod.escape(lab)}</td>"]
            for ki in range(len(KS)):
                html_cell = _cell_html(res["grid"]["FULL"][ti][ki], res["grid"]["IS"][ti][ki], res["grid"]["OOS"][ti][ki])
                cells.append(f"<td>{html_cell}</td>")
            body.append("<tr>" + "".join(cells) + "</tr>")
        book = "Research book" if res["research"] else "Live book"
        blocks.append(
            f"<h2>{html_mod.escape(res['label'])}</h2>\n"
            f"<p class=\"blockhead\">{book}. Control average return: "
            f"full {_fmt_pct(mfull.get('avg_pnl_pct'))}, "
            f"in-sample {_fmt_pct(mis.get('avg_pnl_pct'))}, "
            f"out-of-sample {_fmt_pct(moos.get('avg_pnl_pct'))}. "
            f"Control annualized rate of return: "
            f"full {_fmt_pct(mfull.get('ann_ror'))}, "
            f"in-sample {_fmt_pct(mis.get('ann_ror'))}, "
            f"out-of-sample {_fmt_pct(moos.get('ann_ror'))}. "
            f"N full {res['n_full']:,}. N in-sample {res['n_is']:,}. N out-of-sample {res['n_oos']:,}. "
            f"The control-avg row turns the stop on at {res['ctrl_avg']:.4f}% above entry "
            f"(the full-book average return of these same trades)."
            f"{html_mod.escape(rsi_note)}</p>\n"
            f"<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>{''.join(heads)}</tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table></div>"
        )

    vheads = "".join(
        [
            _th("System", "text"),
            _th("In-sample call", "text"),
            _th("Activation", "text"),
            _th("Keep", "text"),
            _th("IS avg return", "num"),
            _th("IS Ann ROR", "num"),
            _th("Control IS avg", "num"),
            _th("Control IS Ann ROR", "num"),
            _th("Note", "text"),
        ]
    )
    vbody = []
    for res in results:
        w = res.get("winner") or {}
        is_c = res["metrics"]["IS"]["control"]
        call = "No in-sample trades" if not is_c.get("n") else ("Above control" if w.get("beats") else "Does not beat control")
        vbody.append(
            "<tr>"
            f"<td>{html_mod.escape(res['label'])}</td>"
            f"<td>{html_mod.escape(call)}</td>"
            f"<td>{html_mod.escape(str(w.get('hurdle') or '—'))}</td>"
            f"<td>{html_mod.escape(str(w.get('keep') or '—'))}</td>"
            f"<td>{_fmt_pct(w.get('is_avg'))}</td>"
            f"<td>{_fmt_pct(w.get('is_ann'))}</td>"
            f"<td>{_fmt_pct(is_c.get('avg_pnl_pct'))}</td>"
            f"<td>{_fmt_pct(is_c.get('ann_ror'))}</td>"
            f"<td>{html_mod.escape(_judge_sentence(res))}</td>"
            "</tr>"
        )

    # Canonical: control vs the single best in-sample arm.
    cheads = "".join(
        [
            _th("System", "text"),
            _th("Slice", "text"),
            _th("Metric", "text"),
            _th("Control", "num"),
            _th("Best in-sample arm", "num"),
            _th("Delta", "num"),
        ]
    )
    cbody = []
    for res in results:
        w = res.get("winner") or {}
        arm_name = f"{w.get('hurdle', '—')}, {w.get('keep', '—')}" if w else "—"
        for mode, slice_name in (
            ("FULL", "Full"),
            ("IS", "In-sample"),
            ("OOS", "Out-of-sample"),
        ):
            ctrl = res["metrics"][mode]["control"]
            best = res["metrics"][mode].get("best") or {}
            for label, key, _typ, kind in metric_spec:
                if is_excluded_html_compare_label(label):
                    continue
                cval = ctrl.get(key)
                aval = best.get(key)
                dlt = None
                if cval is not None and aval is not None:
                    try:
                        fa, fb = float(aval), float(cval)
                        if math.isfinite(fa) and math.isfinite(fb):
                            dlt = fa - fb
                    except (TypeError, ValueError):
                        dlt = None
                cbody.append(
                    "<tr>"
                    f"<td>{html_mod.escape(res['code'])}</td>"
                    f"<td>{html_mod.escape(slice_name)}</td>"
                    f"<td>{html_mod.escape(label)}</td>"
                    f"<td>{_fmt_cell(cval, kind)}</td>"
                    f"<td>{_fmt_cell(aval, kind)}</td>"
                    f"<td>{_fmt_delta(dlt, kind)}</td>"
                    "</tr>"
                )
            # Arm identity sits on the first metric's neighbor via a dedicated row pinned? 
            # A text row keeps the arm name sortable with the metric rows.
            cbody.append(
                "<tr>"
                f"<td>{html_mod.escape(res['code'])}</td>"
                f"<td>{html_mod.escape(slice_name)}</td>"
                f"<td>Best in-sample arm (chosen on in-sample average return)</td>"
                f"<td>Control</td>"
                f"<td>{html_mod.escape(arm_name)}</td>"
                f"<td>—</td>"
                "</tr>"
            )

    scratch_heads = "".join(
        [
            _th("System", "text"),
            _th("Rule", "text"),
            _th("Next-morning open under 1%", "num"),
            _th("% of N", "num"),
            _th("Next-morning stop under 1%", "num"),
        ]
    )
    sbody = []
    for res in results:
        n = res["n_full"] or 0
        rows_spec = [("No delay, keep 40% (first-test behavior)", res["diag_gap"], res["diag_stop"])]
        # Fixed hurdles and the control-avg hurdle, at keep 40% (index 0) — the tightest keep.
        for ti, lab in enumerate(res["hurdle_labels"]):
            if ti in (0, 4, len(res["hurdle_labels"]) - 1):
                rows_spec.append(
                    (
                        f"Activate at {lab}, keep 40%",
                        res["scratch_gap"][ti][0],
                        res["scratch_stop"][ti][0],
                    )
                )
        w = res.get("winner") or {}
        if w and not (w["ki"] == 0 and w["ti"] in (0, 4, len(res["hurdle_labels"]) - 1)):
            rows_spec.append(
                (
                    f"In-sample arm: {w['hurdle']}, {w['keep']}",
                    w["scratch_gap"],
                    w["scratch_stop"],
                )
            )
        for name, gap_n, stop_n in rows_spec:
            pct = (100.0 * gap_n / n) if n else None
            sbody.append(
                "<tr>"
                f"<td>{html_mod.escape(res['code'])}</td>"
                f"<td>{html_mod.escape(name)}</td>"
                f"<td>{gap_n:,}</td>"
                f"<td>{_fmt_pct(pct)}</td>"
                f"<td>{stop_n:,}</td>"
                "</tr>"
            )

    exit_heads = "".join(
        [
            _th("System", "text"),
            _th("Slice", "text"),
            _th("Arm", "text"),
            _th("Exit", "text"),
            _th("N", "num"),
            _th("% of arm", "num"),
        ]
    )
    exit_rows = []
    for res in results:
        w = res.get("winner") or {}
        arm_name = f"Best IS: {w.get('hurdle', '—')}, {w.get('keep', '—')}"
        for mode, slice_name in (("FULL", "Full"), ("IS", "In-sample"), ("OOS", "Out-of-sample")):
            for arm_key, arm_lab in (("control", "Control"), ("best", arm_name)):
                m = res["metrics"][mode].get(arm_key) or {}
                mix = m.get("exit_mix") or {}
                nn = m.get("n") or 0
                for xt, cnt in sorted(mix.items(), key=lambda kv: (-kv[1], str(kv[0]))):
                    pct = (100.0 * cnt / nn) if nn else None
                    exit_rows.append(
                        "<tr>"
                        f"<td>{html_mod.escape(res['code'])}</td>"
                        f"<td>{slice_name}</td>"
                        f"<td>{html_mod.escape(arm_lab)}</td>"
                        f"<td>{html_mod.escape(str(xt))}</td>"
                        f"<td>{cnt:,}</td>"
                        f"<td>{_fmt_pct(pct)}</td>"
                        "</tr>"
                    )

    cash_heads = "".join(
        [
            _th("System", "text"),
            _th("Slot cash", "num"),
            _th("How sized", "text"),
            _th("Trades scored", "num"),
            _th("Shorts left out", "num"),
            _th("No OHLC path", "num"),
            _th("Control avg hurdle", "num"),
            _th("Book", "text"),
        ]
    )
    cash_rows = []
    for res in results:
        cash_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(res['label'])}</td>"
            f"<td>{html_mod.escape(format_money(res['cash']))}</td>"
            f"<td>{html_mod.escape(res['cash_src'])}</td>"
            f"<td>{res['n_full']:,}</td>"
            f"<td>{res['short_skipped']:,}</td>"
            f"<td>{res['missing_ohlc']:,}</td>"
            f"<td>{res['ctrl_avg']:.4f}%</td>"
            f"<td>{'Research' if res['research'] else 'Live book'}</td>"
            "</tr>"
        )
    for sk in skipped:
        cash_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(sk['label'])}</td>"
            f"<td>—</td><td>{html_mod.escape(sk.get('skip') or 'skipped')}</td>"
            f"<td>0</td><td>—</td><td>—</td><td>—</td>"
            f"<td>{'Research' if sk.get('research') else 'Live book'}</td>"
            "</tr>"
        )

    names = ", ".join(html_mod.escape(r["label"]) for r in results)
    skip_line = ""
    if skipped:
        skip_line = " Skipped: " + "; ".join(
            html_mod.escape(f"{s['label']} ({s.get('skip')})") for s in skipped
        ) + "."

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>High-water stop activates at n%</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 24px; color: #0f172a; line-height: 1.45; }}
h1 {{ font-size: 1.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; border-radius: 10px; padding: 12px 14px; margin: 12px 0; }}
.banner {{ background: #fff7ed; border: 1px solid #fdba74; border-radius: 10px; padding: 12px 14px; margin: 12px 0; }}
.blockhead {{ margin: 8px 0 10px; }}
td div {{ white-space: nowrap; }}
code {{ font-size: 0.92em; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>High-water stop stays off until the mark is n% above entry</h1>
<p>Research only. Not gold. Not DailyRun. Out-of-sample is report-only.</p>
<div class="callout">
<h2>What you asked</h2>
<p>{html_mod.escape(ASK)}</p>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN)}</p>
</div>
<div class="banner">
<p><strong>Control</strong> is each system's current closed book and the exit that book already used. Entries are not rerun and positions are not resized.</p>
<p><strong>High-water mark</strong> is the highest daily high since the entry fill, from the warehouse daily open-high-low-close in <code>data/ohlcv.duckdb</code>. It is not a 15-minute high. On the entry day the high can set the mark for the next day. That same day is not stopped out, and the overlay cannot turn on that same day.</p>
<p><strong>Activation.</strong> The overlay stop stays off until the prior-day high-water mark is at least n% above the entry. Hurdles: 2, 4, 5, 6, and 10, plus each system's own full-book average return on the trades replayed here. Once that hurdle is cleared, stop = entry + k × (high-water mark − entry), for k of 0.40, 0.50, 0.60, 0.70, and 0.80. Day T uses the mark through day T−1 only. If that stop is not above the system's original stop, the original stop stays.</p>
<p><strong>Systems on this page:</strong> {names}. Indicators (IND) is deprecated and was skipped.{skip_line} Most Up / Most Down (MUD) is research, not a live DailyRun sleeve, and only when the first high-water test already had that book. Short trades were left out because this stop is a long rule. A trade with no daily bars covering the hold was left out of every arm, so N matches the control.</p>
<p><strong>Selection bias.</strong> Keep 40/50/60 were already compared with no activation delay on this same history (stamp hwm_stop_keep_40_50_60_20261015). This grid, including keep 70/80 and the delay hurdles, is a follow-up on that same history. The best arm below is chosen by in-sample average return (entry before 2024-01-01), ties broken by in-sample annualized rate of return. Out-of-sample (entry on or after 2024-01-01) is report-only and was not used to pick the arm.</p>
<p>The first mention of annualized rate of return is this sentence. After that, Ann ROR is the house formula <code>((1 + total profit / (slot cash × N)) ^ (365 / average days held) − 1) × 100</code> via <code>compare_format.ann_ror_from_closed</code>. Slot cash is the Closed median implied notional (profit dollars divided by percent). Report capacity is cited only when it sits within about 25% of that median. A flat $47,500 sheet slot is not used when the closed book is capacity-sized. Max drawdown and Sharpe use exit-date equity seeded at $500,000 (no daily equity curve on the overlay).</p>
<p>In each system block, N is stated once for the full book, once for in-sample, and once for out-of-sample. It is the same for every keep column. Each keep cell has three lines: full book, in-sample, and out-of-sample. Each line is average return, then Ann ROR. Click a keep column to sort by the full-book average return (the first number).</p>
</div>
<h2>In-sample read</h2>
<p>Click column headers to sort. The arm is the highest in-sample average return. A higher Ann ROR from a shorter hold does not override a lower average return. Nothing here is gold or DailyRun.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable"><thead><tr>{vheads}</tr></thead><tbody>
{''.join(vbody)}
</tbody></table></div>
<h2>Activation by keep fraction</h2>
<p>One block per system. Rows are the hurdles. Columns are how much of the gain the stop keeps. The control average return and control Ann ROR are in the block header, not repeated down the keep columns.</p>
{''.join(blocks)}
<h2>Canonical compare — control vs best in-sample arm</h2>
<p>Full metric set for the control and for the single best in-sample arm of each system. Delta is that arm minus the control. The arm was chosen on in-sample average return only. Out-of-sample rows are the same arm, not a new pick. Days underwater, open-position counts, aggressive paths, and Paul / FIT scores are not recomputed: this test does not rebuild a daily portfolio or a Summary file. Profit concentration is blank when total profit is not positive.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable"><thead><tr>{cheads}</tr></thead><tbody>
{''.join(cbody)}
</tbody></table></div>
<h2>Next-morning scratches</h2>
<p>A scratch is a sell on the first session after entry for a gain under 1%. The open column is a sell at the open because the open was already through the stop. The stop column is a sell at the stop price because the low tagged it. "No delay, keep 40%" is the first test's behavior (the stop can turn on as soon as yesterday's high is above the entry). It is not an arm in the horse race.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable"><thead><tr>{scratch_heads}</tr></thead><tbody>
{''.join(sbody)}
</tbody></table></div>
<h2>Coverage and slot cash</h2>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable"><thead><tr>{cash_heads}</tr></thead><tbody>
{''.join(cash_rows)}
</tbody></table></div>
<h2>Exit mix — control and best in-sample arm</h2>
<p>HWM_GAP is a sell at the open. HWM_STOP is a sell at the stop. Other labels are the book's original exit type.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable"><thead><tr>{exit_heads}</tr></thead><tbody>
{''.join(exit_rows)}
</tbody></table></div>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""


def write_baseline(results: list[dict[str, Any]], skipped: list[dict[str, Any]]) -> None:
    lines = [
        "# High-water stop activates at n% — 2026-10-15",
        "",
        "Research only. Not gold. Not DailyRun. No knob was chosen from out-of-sample.",
        "",
        "## What you asked",
        "",
        f"> {ASK}",
        "",
        "## In plain English",
        "",
        PLAIN,
        "",
        "## Freeze",
        "",
        "- Control = each system's current closed book (`Drive/{SYSTEM}_LatestRun_Closed.csv`) and the exit that book already used.",
        "- Same trade loader as `tools/hwm_stop_keep_40_50_60_20261015.py`. Entries are not rerun.",
        "- Rocket Launcher (RL) control is that closed book, not the named partial exit strategy (80% at +20%, leftover stop at entry, leftover at +40%).",
        "- Overlay stays off until the prior-day high-water mark is at least n% above entry.",
        "- Fixed hurdles: 2, 4, 5, 6, and 10 percent above entry.",
        "- Extra hurdle: that system's average percent return on the full book of trades actually replayed. Not rounded into the trigger. Relative Strength Index (RSI) uses this computed average. Paul said 4.65%. The page shows both if they differ. 4.65% was not forced.",
        "- Once on: stop = entry + k × (high-water mark − entry), k = 0.40, 0.50, 0.60, 0.70, 0.80.",
        "- Never loosen: if that stop is not strictly above the original stop, the original stop stays. Stop price ≤ 0 counts as no original stop.",
        "- High-water mark = highest daily high since the fill, warehouse daily bars (`data/ohlcv.duckdb`). Not a 15-minute high.",
        "- No lookahead: day T uses the mark through T−1. Entry-day high sets the next day's mark, does not stop out the entry day, and does not activate the overlay on the entry day.",
        "- Open through the stop fills at the open; else a low through the stop fills at the stop; else the original exit stands.",
        "- One position per closed trade. No resize. Same entries.",
        "- In-sample: entry_date < 2024-01-01. Out-of-sample: entry_date >= 2024-01-01. Full book reported too.",
        "- Best arm: highest in-sample average return. Ties broken by in-sample annualized rate of return, then the earlier hurdle and the smaller keep fraction. Out-of-sample did not pick the arm.",
        "- Annualized rate of return: `compare_format.ann_ror_from_closed`, days_per_year 365. Slot cash = Closed median implied notional. Report capacity_brt_cash only when within 25% of that median. No flat $47,500 when the book is capacity-sized.",
        "- Max DD and Sharpe: exit-date equity, seed $500,000 (`DEFAULT_INITIAL_ACCOUNT`). Not a daily mark-to-market curve.",
        "- Selection bias: keep 40/50/60 were already seen with no activation delay on this same history. This grid, including 70/80 and the delay levels, is a follow-up on that history.",
        "- This overlay is not a Simple Moving Average (SMA) target.",
        "",
        "## Systems",
        "",
        "Live books: Break and ReTest (BRT), Rocket Launcher (RL), Year High (YH), Magic Touch (MTS), Weekly Pivot Break and Retest (WPBR), Relative Strength vs SPY (RS), StockBee (SB), Volume Zone (VZ), Relative Strength Index (RSI), Weekly Range / Swing (WRL).",
        "",
        "Most Up / Most Down (MUD) is included only because the first high-water test already scored that closed book. It is labeled research.",
        "",
        "Indicators (IND) skipped (deprecated).",
        "",
        "## Slot cash, hurdle, and in-sample read",
        "",
    ]
    for res in results:
        w = res.get("winner") or {}
        is_c = res["metrics"]["IS"]["control"]
        lines.append(
            f"- **{res['label']}** ({'research' if res['research'] else 'live'}): "
            f"slot {format_money(res['cash'])}. {res['cash_src']}. "
            f"Scored {res['n_full']:,} (in-sample {res['n_is']:,}, out-of-sample {res['n_oos']:,}); "
            f"shorts left out {res['short_skipped']:,}; no OHLC path {res['missing_ohlc']:,}. "
            f"Control average return used as the extra hurdle: {res['ctrl_avg']:.4f}%. "
            f"Stop column `{res['stop_col'] or 'none'}`. "
            f"In-sample best: activate at {w.get('hurdle', '—')}, {w.get('keep', '—')}, "
            f"average return {_fmt_pct(w.get('is_avg'))}, Ann ROR {_fmt_pct(w.get('is_ann'))}, "
            f"versus control {_fmt_pct(is_c.get('avg_pnl_pct'))} and {_fmt_pct(is_c.get('ann_ror'))}. "
            f"{'Above control on in-sample average return.' if w.get('beats') else 'Does not beat the control on in-sample average return.'} "
            + (
                (
                    f"Paul said 4.65% for RSI. In-sample control average is {_fmt_pct(is_c.get('avg_pnl_pct'))}. "
                    f"The extra hurdle is the full-book average {res['ctrl_avg']:.4f}%, not 4.65%. "
                )
                if res["code"] == "RSI"
                else ""
            )
            + _judge_sentence(res)
        )
    if skipped:
        lines += ["", "## Skipped", ""]
        for sk in skipped:
            lines.append(f"- **{sk['label']}**: {sk.get('skip')}")
    lines += [
        "",
        "## Not computed",
        "",
        "Days underwater, concurrent position counts, aggressive PnL, and Paul / FIT scores need a daily equity curve or a rebuilt Summary. This page does not invent them.",
        "",
        "## Promotion",
        "",
        "Research only. Not gold. Not wired to DailyRun. Out-of-sample was not used to retune.",
        "",
    ]
    (OUT / "BASELINE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _slim(res: dict[str, Any]) -> dict[str, Any]:
    w = res.get("winner")
    return {
        "code": res["code"],
        "ctrl_avg": res["ctrl_avg"],
        "cash": res["cash"],
        "n_full": res["n_full"],
        "n_is": res["n_is"],
        "n_oos": res["n_oos"],
        "diag_gap": res["diag_gap"],
        "diag_stop": res["diag_stop"],
        "winner": w,
        "judge": _judge_sentence(res),
        "control_is_avg": res["metrics"]["IS"]["control"].get("avg_pnl_pct"),
        "control_is_ann": res["metrics"]["IS"]["control"].get("ann_ror"),
        "control_full_avg": res["metrics"]["FULL"]["control"].get("avg_pnl_pct"),
        "control_full_ann": res["metrics"]["FULL"]["control"].get("ann_ror"),
    }


def main() -> int:
    _self_test_walk()
    # Fix the self-test assertion that I left contradictory. The function raises if the
    # handmade bars disagree. See _self_test_walk.
    OUT.mkdir(parents=True, exist_ok=True)
    hwm1 = _load_hwm1()
    jobs = list(hwm1.SYSTEMS)
    # Run systems in-process, largest last is fine; MUD dominates. A process pool
    # would duplicate the duckdb load. Sequential keeps the machine stable and
    # still prints progress. Small books are seconds; MUD is the long one.
    results: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for job in jobs:
        res = run_system(job)
        if res.get("skip"):
            skipped.append(res)
        else:
            results.append(res)
    html_path = OUT / "compare.html"
    html_path.write_text(render(results, skipped), encoding="utf-8")
    write_baseline(results, skipped)
    (OUT / "summary.json").write_text(
        json.dumps(_jsonable({"results": [_slim(r) for r in results], "skipped": skipped}), indent=2),
        encoding="utf-8",
    )
    print("WROTE", html_path, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
