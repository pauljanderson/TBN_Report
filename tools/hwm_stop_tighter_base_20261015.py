#!/usr/bin/env python3
"""Tighter (and listed wider) base stops plus Paul's high-water trail.

Research only. Does not wire DailyRun. Does not edit earlier high-water stamps.
Does not retune on out-of-sample.
"""
from __future__ import annotations

import html as html_mod
import importlib.util
import json
import math
import sys
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

from compare_format import format_money, format_money_delta  # noqa: E402
from report_page_extras import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

STAMP = "hwm_stop_tighter_base_20261015"
OUT = _PE / STAMP
IS_CUT = 20240101
FLAT_PP = 0.005

ASK = (
    "so by putting this aggressive trailing stop loss in, we don't let our winners grow as much, "
    "but we do increase the amount of winners we have overall. the most extreme example is WPBR "
    "going from a win rate of 52.12% to 83.86%!\n"
    "so, i'm thinking we might need to reduce our stop losses when the stock doesn't rise.\n"
    "can you rerun these systems through using these new trailing stop losses and the base stop "
    "losses change here:\n"
    "BRT 5.44%, 6.8, 9.07, 10.46, 13.6\n"
    "RL 0.65%, 0.81, 1.08, 1.24, 1.62\n"
    "YH 0.95%, 1.19, 1.59, 1.83, 2.38\n"
    "MTS 2.56%, 3.2, 4.26, 4.92, 6.39\n"
    "WPBR 3.03%, 3.79, 5.06, 5.84, 7.59\n"
    "RS 7.13%, 8.91, 11.88, 13.7, 17.81\n"
    "RSI 2.07%, 2.58, 3.44, 3.97, 5.17"
)

PLAIN = (
    "Each system keeps the buys it already took. The control sells the way that system sells today, "
    "with no high-water trail. A second arm keeps today's starting stop and adds the trailing stop "
    "Paul already picked, so he can see whether a new starting stop helped beyond that trail. "
    "Five more arms replace only the starting stop with the percents he listed, and they keep that "
    "same trail. The trail stays off until a prior day's high is far enough above the buy. "
    "After that, the stop sits at the buy price plus a keep fraction of the rise from the buy to the "
    "highest daily high so far. It never moves down through the starting stop that is in force. "
    "Day T does not use today's high. The entry day cannot turn the trail on and cannot sell on the trail. "
    "Break and ReTest (BRT) turns the trail on at 6% and keeps 70% of the gain. "
    "Rocket Launcher (RL) turns on at 6% and keeps 80%. "
    "Year High (YH) turns on at 2% and keeps 70%. "
    "Magic Touch (MTS) turns on at 4% and keeps 60%. "
    "Weekly Pivot Break and Retest (WPBR) turns on at 2% and keeps 80%. "
    "Relative Strength vs SPY (RS) turns on at 10% and keeps 80%. "
    "Relative Strength Index (RSI) turns on at 6% and keeps 80%. "
    "For Break and ReTest, Year High, Magic Touch, and Weekly Pivot Break and Retest, the starting stop "
    "is that percent under the trigger-day low (trigger low times 1 minus the percent). "
    "Rocket Launcher uses the same idea under the signal-day low. "
    "Relative Strength vs SPY and Relative Strength Index put the stop that percent under the buy. "
    "Relative Strength Index has no price stop today; the new stop is added, and the old Relative "
    "Strength Index exits still fire if that stop and the trail are not hit. "
    "Rocket Launcher's live book still sells 80% at +20% from the buy, moves the leftover stop to the buy, "
    "and sells the leftover at +40%. That partial ladder stays in the control, and it stays in the "
    "current-stop-plus-trail arm, because that arm is the live exit plus the trail Paul already saw. "
    "The five new Rocket Launcher arms do not use that ladder. The live engine's other price target is "
    "the 50-day Simple Moving Average (SMA) envelope, and that target is off, so those five arms have "
    "no separate price target. They exit on the new stop, the trail, or the last daily bar if neither hits. "
    "The other systems still use their live price target (about 21% for Break and ReTest and Year High, "
    "22% for Magic Touch, 20% for Weekly Pivot Break and Retest, 25% for Relative Strength vs SPY) "
    "and Relative Strength vs SPY's 252-bar time stop. The stop is checked before the target."
)

# live_pct is the distance under the anchor today (percent). None = no price stop.
SYSTEMS: list[dict[str, Any]] = [
    {"code": "BRT", "label": "Break and ReTest (BRT)", "act": 6.0, "keep": 0.70,
     "anchor": "trigger", "live_mult": 0.934, "live_pct": 6.6, "round_dp": 2,
     "target_fallback": 1.21, "time_bars": 0, "family": "tbn"},
    {"code": "RL", "label": "Rocket Launcher (RL)", "act": 6.0, "keep": 0.80,
     "anchor": "signal", "live_mult": 0.934, "live_pct": 6.6, "round_dp": -1,
     "target_fallback": None, "time_bars": 0, "family": "rl"},
    {"code": "YH", "label": "Year High (YH)", "act": 2.0, "keep": 0.70,
     "anchor": "trigger", "live_mult": 0.934, "live_pct": 6.6, "round_dp": -1,
     "target_fallback": 1.21, "time_bars": 0, "family": "tbn"},
    {"code": "MTS", "label": "Magic Touch (MTS)", "act": 4.0, "keep": 0.60,
     "anchor": "trigger", "live_mult": 0.934, "live_pct": 6.6, "round_dp": 2,
     "target_fallback": 1.22, "time_bars": 0, "family": "tbn"},
    {"code": "WPBR", "label": "Weekly Pivot Break and Retest (WPBR)", "act": 2.0, "keep": 0.80,
     "anchor": "trigger", "live_mult": 0.92, "live_pct": 8.0, "round_dp": 2,
     "target_fallback": 1.20, "time_bars": 0, "family": "tbn"},
    {"code": "RS", "label": "Relative Strength vs SPY (RS)", "act": 10.0, "keep": 0.80,
     "anchor": "entry", "live_mult": 0.85, "live_pct": 15.0, "round_dp": 2,
     "target_fallback": 1.25, "time_bars": 252, "family": "tbn"},
    {"code": "RSI", "label": "Relative Strength Index (RSI)", "act": 6.0, "keep": 0.80,
     "anchor": "entry", "live_mult": None, "live_pct": None, "round_dp": 2,
     "target_fallback": None, "time_bars": 0, "family": "rsi"},
]

STOPS: dict[str, list[float]] = {
    "BRT": [5.44, 6.8, 9.07, 10.46, 13.6],
    "RL": [0.65, 0.81, 1.08, 1.24, 1.62],
    "YH": [0.95, 1.19, 1.59, 1.83, 2.38],
    "MTS": [2.56, 3.2, 4.26, 4.92, 6.39],
    "WPBR": [3.03, 3.79, 5.06, 5.84, 7.59],
    "RS": [7.13, 8.91, 11.88, 13.7, 17.81],
    "RSI": [2.07, 2.58, 3.44, 3.97, 5.17],
}

METRIC_SPEC = [
    ("Wins", "wins", "int"),
    ("Losses", "losses", "int"),
    ("Win %", "win_pct", "pct"),
    ("Avg PnL %", "avg_pnl_pct", "pct"),
    ("Book AVG_PNL_PCT_WO_MAX", "avg_pnl_pct_wo_max", "pct"),
    ("Expectancy $", "expectancy_d", "money"),
    ("Expectancy %", "expectancy_pct", "pct"),
    ("Avg win %", "avg_win_pct", "pct"),
    ("Avg loss %", "avg_loss_pct", "pct"),
    ("Win/Loss ratio (count)", "wl_count", "num"),
    ("Win/Loss ratio $", "wl_dollars", "num"),
    ("Profit factor", "profit_factor", "num"),
    ("Ann ROR %", "ann_ror", "pct"),
    ("Max DD %", "max_dd", "pct"),
    ("Calmar", "calmar", "num"),
    ("Sharpe", "sharpe", "num"),
    ("Profit per capital day", "ppcd", "money"),
    ("Capital days", "capital_days", "num"),
    ("Avg days held", "avg_days", "num"),
    ("Median days held", "median_days", "num"),
    ("P90 days held", "p90_days", "num"),
    ("Losing streak", "losing_streak", "int"),
    ("Pct PnL max symbol", "pct_max_symbol", "pct"),
    ("Pct PnL max trade", "pct_max_trade", "pct"),
    ("Pct PnL max industry", "pct_max_industry", "pct"),
    ("Pct PnL top10", "pct_top10", "pct"),
    ("Pct PnL bottom10", "pct_bottom10", "pct"),
    ("Outlier % of win $", "outlier_win_pct", "pct"),
    ("Trades per year", "trades_per_year", "num"),
]

NOT_COMPUTED = [
    ("Universe size", "Same closed book. Entries were not rerun. A listed arm drops a trade only when the new stop is not below the buy, so that buy never fills."),
    ("Avg / P90 / max days underwater and % days underwater", "Needs a daily equity curve. This overlay does not build one."),
    ("Avg / median / max positions", "Scored one closed trade at a time."),
    ("Aggressive Total PnL $ / Aggressive Max DD %", "Needs the aggressive sizing path. Not recomputed."),
    ("Paul Score, FIT Score, FIT Score Robust, CES, symbol-mean columns", "Needs a Summary rebuild. Not recomputed."),
    ("Total PnL $ and Sheet PnL $", "Omitted from the HTML compare tables on purpose."),
]


def _load_act():
    path = _TOOLS / "hwm_stop_activate_at_n_20261015.py"
    name = "hwm_stop_activate_at_n_20261015"
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


def _fmt(v: Any, kind: str) -> str:
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


def _delta(a: Any, b: Any) -> Optional[float]:
    if a is None or b is None:
        return None
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(fa) and math.isfinite(fb)):
        return None
    return fa - fb


def _fmt_delta(v: Optional[float], kind: str) -> str:
    if v is None or not math.isfinite(float(v)):
        return "—"
    if kind == "money":
        return html_mod.escape(format_money_delta(v))
    if kind == "int":
        return f"{int(round(v)):+,}"
    if kind == "pct":
        return f"{v:+.2f}%"
    return f"{v:+.2f}"


def _ymd_date(ymd: int) -> date:
    y = int(ymd)
    return date(y // 10000, (y // 100) % 100, y % 100)


def _hold_days(opened: int, closed: int, book_days: float, changed: bool) -> float:
    if not changed:
        if book_days == book_days and book_days > 0:
            return float(book_days)
    try:
        delta = (_ymd_date(closed) - _ymd_date(opened)).days
    except ValueError:
        delta = 0
    if delta <= 0:
        return 1.0
    return float(delta)


def _le(a: float, b: float, dp: int) -> bool:
    if not (a == a and b == b):
        return False
    if dp >= 0:
        return round(float(a), dp) <= round(float(b), dp)
    return float(a) <= float(b)


def _ge(a: float, b: float) -> bool:
    return a == a and b == b and float(a) >= float(b)


def _attach_targets(hwm1, df: pd.DataFrame, system: str) -> pd.DataFrame:
    path = hwm1._DRIVE / f"{system}_LatestRun_Closed.csv"
    raw = pd.read_csv(path, low_memory=False)
    lookup = {hwm1._norm(c): c for c in raw.columns}
    sym_c = hwm1._pick(lookup, "SYMBOL")
    open_c = hwm1._pick(lookup, "DATE OPENED")
    entry_c = hwm1._pick(lookup, "ENTRY PRICE")
    tgt_c = hwm1._pick(lookup, "TARGET PRICE", "ORIGINAL TARGET")
    ret_c = hwm1._pick(lookup, "RETEST LOW")
    sym = raw[sym_c].astype(str).str.upper().str.strip().to_numpy()
    opened = hwm1._parse_ymd_series(raw[open_c])
    entry = hwm1._to_num(raw[entry_c])
    target = hwm1._to_num(raw[tgt_c]) if tgt_c else np.full(len(raw), np.nan)
    retest = hwm1._to_num(raw[ret_c]) if ret_c else np.full(len(raw), np.nan)
    mp: dict[tuple, tuple[float, float]] = {}
    for i in range(len(raw)):
        k = (str(sym[i]), int(opened[i]), round(float(entry[i]), 4) if entry[i] == entry[i] else 0.0)
        if k not in mp:
            mp[k] = (float(target[i]) if target[i] == target[i] else float("nan"),
                     float(retest[i]) if retest[i] == retest[i] else float("nan"))
    t_out = np.full(len(df), np.nan)
    r_out = np.full(len(df), np.nan)
    symbols = df["symbol"].to_numpy()
    opens = df["opened"].to_numpy()
    entries = df["entry"].to_numpy()
    for i in range(len(df)):
        k = (str(symbols[i]), int(opens[i]), round(float(entries[i]), 4))
        hit = mp.get(k)
        if hit:
            t_out[i], r_out[i] = hit
    df = df.copy()
    df["target"] = t_out
    df["retest"] = r_out
    return df


def _load_ohlc(hwm1, symbols: set[str]):
    if not symbols:
        return {}
    con = hwm1.duckdb.connect(str(hwm1.DB), read_only=True)
    try:
        df = con.execute(
            """
            SELECT UPPER(symbol) AS symbol, date, open, high, low, close
            FROM prices
            WHERE UPPER(symbol) IN (SELECT * FROM UNNEST(?))
            ORDER BY 1, 2
            """,
            [sorted(symbols)],
        ).fetchdf()
    finally:
        con.close()
    out = {}
    if df.empty:
        return out
    dt = pd.to_datetime(df["date"])
    df["ymd"] = (dt.dt.year * 10000 + dt.dt.month * 100 + dt.dt.day).astype(np.int64)
    for sym, g in df.groupby("symbol", sort=False):
        out[str(sym)] = (
            g["ymd"].to_numpy(dtype=np.int64),
            g["open"].to_numpy(dtype=np.float64),
            g["high"].to_numpy(dtype=np.float64),
            g["low"].to_numpy(dtype=np.float64),
            g["close"].to_numpy(dtype=np.float64),
        )
    return out


def _snap_anchor(lows: np.ndarray, i0: int, raw: float) -> tuple[float, bool]:
    if not (raw == raw and raw > 0):
        return raw, False
    best_err = 1e9
    best = raw
    snapped = False
    for j in range(i0 - 1, max(-1, i0 - 8), -1):
        lo = float(lows[j])
        if not (lo == lo and lo > 0):
            continue
        err = abs(lo - raw) / raw
        if err < best_err - 1e-15:
            best_err = err
            best = lo
    if best_err <= 0.005:
        return best, True
    return raw, snapped


def _self_test() -> None:
    dates = np.array([20200102, 20200103, 20200106], dtype=np.int64)
    opens = np.array([100.0, 100.0, 100.2], dtype=np.float64)
    highs = np.array([101.0, 103.0, 104.0], dtype=np.float64)
    lows = np.array([99.8, 99.5, 100.0], dtype=np.float64)
    closes = np.array([100.5, 102.0, 103.0], dtype=np.float64)
    bars = (dates, opens, highs, lows, closes)
    # Trail activates on day 3 from the day-2 high of 103. Open 100.2 gaps through keep-50% stop 101.5.
    hit = _walk(
        bars, 20200102, 20200106, 100.0, base=90.0, target=130.0,
        act=2.0, keep=0.50, time_bars=0, round_dp=-1,
        family="tbn", trail=True, book_fallback=False, book_px=0.0, book_xt="TARGET",
    )
    assert hit["tag"] == "HWM_GAP" and abs(hit["px"] - 100.2) < 1e-9 and hit["ymd"] == 20200106, hit
    # Tighter base 99.6 is under the entry-day low (99.8) and above the day-2 low (99.5).
    hit2 = _walk(
        bars, 20200102, 20200106, 100.0, base=99.6, target=130.0,
        act=2.0, keep=0.50, time_bars=0, round_dp=-1,
        family="tbn", trail=True, book_fallback=False, book_px=0.0, book_xt="TARGET",
    )
    assert hit2["tag"] == "STOP_LOSS" and abs(hit2["px"] - 99.6) < 1e-9 and hit2["ymd"] == 20200103, hit2
    # Entry day can sell the base stop. Trail cannot.
    lows_ed = np.array([99.0, 99.5, 100.0], dtype=np.float64)
    hit3 = _walk(
        (dates, opens, highs, lows_ed, closes), 20200102, 20200106, 100.0, base=99.2, target=130.0,
        act=2.0, keep=0.50, time_bars=0, round_dp=-1,
        family="tbn", trail=True, book_fallback=False, book_px=0.0, book_xt="TARGET",
    )
    assert hit3["ymd"] == 20200102 and hit3["tag"] == "STOP_LOSS", hit3
    # RL entry day uses the close, not the low. Close 100.5 is above 99.2, so no entry-day stop.
    hit4 = _walk(
        bars, 20200102, 20200106, 100.0, base=99.2, target=0.0,
        act=6.0, keep=0.80, time_bars=0, round_dp=-1,
        family="rl", trail=True, book_fallback=False, book_px=0.0, book_xt="",
    )
    assert hit4["ymd"] != 20200102
    print("self-test ok", flush=True)


def _walk(
    bars,
    opened: int,
    closed_book: int,
    entry: float,
    *,
    base: float,
    target: float,
    act: float,
    keep: float,
    time_bars: int,
    round_dp: int,
    family: str,
    trail: bool,
    book_fallback: bool,
    book_px: float,
    book_xt: str,
) -> dict[str, Any] | str:
    if bars is None or not (entry == entry and entry > 0):
        return "missing"
    dates, opens, highs, lows, closes = bars
    if dates.size == 0:
        return "missing"
    i0 = int(np.searchsorted(dates, opened, side="left"))
    if i0 >= dates.size or int(dates[i0]) != int(opened):
        return "missing"
    if book_fallback:
        i_book = int(np.searchsorted(dates, closed_book, side="left"))
        if i_book >= dates.size or int(dates[i_book]) != int(closed_book) or int(dates[-1]) < int(closed_book):
            return "missing"
        i_end = i_book
    else:
        if int(dates[-1]) < int(opened):
            return "missing"
        i_end = int(dates.size) - 1
    hwm = float(entry)
    target_on = target == target and target > entry
    base_on = base == base and base > 0
    for i in range(i0, i_end + 1):
        di = int(dates[i])
        op = float(opens[i])
        hi = float(highs[i])
        lo = float(lows[i])
        cl = float(closes[i])
        is_entry = di == int(opened)
        trail_px = None
        if trail and (not is_entry) and hwm > entry:
            gain_pct = (hwm - entry) / entry * 100.0
            if gain_pct + 1e-12 >= act:
                trail_px = entry + keep * (hwm - entry)
        eff = base if base_on else float("nan")
        trail_binds = False
        if trail_px is not None and trail_px == trail_px:
            if not base_on or trail_px > base:
                eff = trail_px
                trail_binds = True
        eff_on = eff == eff and eff > 0
        exited = False
        tag = ""
        px = 0.0
        if family == "rl" and is_entry:
            if eff_on and _le(cl, eff, round_dp):
                exited = True
                if _le(op, eff, round_dp):
                    tag, px = ("HWM_GAP" if trail_binds else "GAP_DOWN"), op
                else:
                    tag, px = ("HWM_STOP" if trail_binds else "STOP_LOSS"), eff
        elif eff_on and _le(op, eff, round_dp):
            exited = True
            tag, px = ("HWM_GAP" if trail_binds else "GAP_DOWN"), op
        elif (not is_entry or family != "rl") and target_on and _ge(op, target):
            exited = True
            tag, px = "GAP_UP", op
        elif family == "rl" and is_entry:
            pass
        elif eff_on and _le(lo, eff, round_dp):
            exited = True
            tag, px = ("HWM_STOP" if trail_binds else "STOP_LOSS"), eff
        elif target_on and _ge(hi, target):
            exited = True
            tag, px = "TARGET", target
        elif time_bars > 0 and (i - i0) >= time_bars:
            exited = True
            tag, px = "TIME", cl
        elif book_fallback and di == int(closed_book):
            exited = True
            tag, px = (book_xt or "BOOK"), (book_px if book_px == book_px and book_px > 0 else cl)
        if exited:
            return {"ymd": di, "px": float(px), "tag": tag, "changed": True}
        if hi == hi and hi > hwm:
            hwm = hi
    if book_fallback:
        return "missing"
    last = i_end
    return {"ymd": int(dates[last]), "px": float(closes[last]), "tag": "DATA_END", "changed": True}


def _trade_dict(
    sym: str,
    industry: str,
    opened: int,
    closed: int,
    pnl: float,
    pnl_d: float,
    days: float,
    exit_type: str,
) -> dict[str, Any]:
    return {
        "symbol": sym,
        "industry": industry,
        "opened": _ymd_date(opened),
        "closed": _ymd_date(closed),
        "pnl": float(pnl),
        "pnl_d": float(pnl_d),
        "days": float(days),
        "exit_type": exit_type or "UNKNOWN",
    }


def _metrics_for(hwm1, rows: list[dict[str, Any]], cash: float) -> dict[str, dict[str, Any]]:
    return {
        "FULL": hwm1.book_metrics(rows, cash),
        "IS": hwm1.book_metrics(hwm1._slice(rows, "IS"), cash),
        "OOS": hwm1.book_metrics(hwm1._slice(rows, "OOS"), cash),
    }


def _notion_of(book_pnl: float, book_d: float, cash: float) -> float:
    if abs(book_pnl) > 1e-6 and book_d == book_d:
        n = abs(book_d) / (abs(book_pnl) / 100.0)
        if n == n and n > 0:
            return float(n)
    if cash == cash and cash > 0:
        return float(cash)
    return float("nan")


def run_system(act, spec: dict[str, Any]) -> dict[str, Any]:
    hwm1 = act._load_hwm1()
    code = spec["code"]
    print(f"=== {code} ===", flush=True)
    df, meta = hwm1.load_trades(code)
    df = _attach_targets(hwm1, df, code)
    cash, cash_src, dollars = hwm1.slot_cash(df, code)
    print(f"  loaded {len(df):,} cash={cash:,.2f}", flush=True)
    side = df["side"].astype(str)
    long_syms = set(df.loc[side.isin(["LONG", "L", "", "NAN"]), "symbol"].astype(str).unique().tolist())
    ohlc = _load_ohlc(hwm1, long_syms)
    # The earlier trail walker unpacks date, open, high, low. Close stays on the five-field bars.
    ohlc_trail = {sym: bars[:4] for sym, bars in ohlc.items()}
    print(f"  ohlc {len(ohlc):,}", flush=True)

    saved_ks = act.KS
    act.KS = (float(spec["keep"]),)
    try:
        pack = act.replay_system(df, dollars, ohlc_trail, np.array([float(spec["act"])], dtype=np.float64))
    finally:
        act.KS = saved_ks
    if pack.get("n", 0) == 0:
        raise SystemExit(f"{code}: no usable trades")
    # The activation walker stores OHLC without close. Rebuild a close-bearing map (already loaded).
    trail_cols = act._arm_columns(pack, 0, 0)
    ix = pack["ix"]
    n = int(ix.size)
    symbols = df["symbol"].to_numpy()
    industry = df["industry"].astype(str).to_numpy()
    opened = df["opened"].to_numpy(dtype=np.int64)
    closed = df["closed"].to_numpy(dtype=np.int64)
    entry = df["entry"].to_numpy(dtype=np.float64)
    stop = df["stop"].to_numpy(dtype=np.float64)
    target = df["target"].to_numpy(dtype=np.float64)
    retest = df["retest"].to_numpy(dtype=np.float64)
    exit_px = df["exit_px"].to_numpy(dtype=np.float64)
    exit_type = df["exit_type"].astype(str).to_numpy()
    book_pnl = df["pnl"].to_numpy(dtype=np.float64)
    book_days = pack["book_days"]

    control_rows: list[dict[str, Any]] = []
    trail_rows: list[dict[str, Any]] = []
    base_rows: dict[float, list[dict[str, Any]]] = {p: [] for p in STOPS[code]}
    unfilled = {p: 0 for p in STOPS[code]}
    snap_ok = 0
    snap_n = 0
    anchor_err = []
    parity_abs = []
    parity_n = 0

    # Trail arm columns are aligned to pack order, which is ix order.
    trail_pnl = trail_cols["pnl"]
    trail_d = trail_cols["pnl_d"]
    trail_days = trail_cols["days"]
    trail_closed = trail_cols["closed"]
    trail_xt = trail_cols["exit_type"]
    book_d = pack["book_d"]

    for p_i in range(n):
        i = int(ix[p_i])
        sym = str(symbols[i])
        ind = str(industry[i])
        if ind.upper() == "NAN":
            ind = ""
        op_i = int(opened[i])
        cl_i = int(closed[i])
        en = float(entry[i])
        bd = float(book_days[p_i])
        bpn = float(book_pnl[i])
        bdl = float(book_d[p_i])
        notion = _notion_of(bpn, bdl, cash)
        control_rows.append(_trade_dict(sym, ind, op_i, cl_i, bpn, bdl, bd, str(exit_type[i])))
        tr_closed = int(trail_closed[p_i])
        tr_xt = str(trail_xt[p_i])
        changed_trail = tr_xt in {"HWM_GAP", "HWM_STOP"}
        trail_rows.append(_trade_dict(
            sym, ind, op_i, tr_closed, float(trail_pnl[p_i]), float(trail_d[p_i]),
            _hold_days(op_i, tr_closed, bd, changed_trail) if changed_trail else float(trail_days[p_i]),
            tr_xt,
        ))

        bars = ohlc.get(sym)
        if bars is None:
            for pct in STOPS[code]:
                unfilled[pct] += 0
            continue
        dates, _o, _h, lows, _c = bars
        i0 = int(np.searchsorted(dates, op_i, side="left"))
        anchor = en
        if spec["anchor"] == "entry":
            anchor = en
        else:
            raw = float("nan")
            if spec["code"] == "WPBR" and retest[i] == retest[i] and retest[i] > 0:
                raw = float(retest[i])
            elif stop[i] == stop[i] and stop[i] > 0 and spec["live_mult"]:
                raw = float(stop[i]) / float(spec["live_mult"])
            if i0 < dates.size and int(dates[i0]) == op_i and raw == raw:
                anchor, did = _snap_anchor(lows, i0, raw)
                snap_n += 1
                snap_ok += int(did)
            elif raw == raw:
                anchor = raw
                snap_n += 1
            if spec["live_mult"] and anchor == anchor and stop[i] == stop[i] and stop[i] > 0:
                anchor_err.append(abs(anchor * float(spec["live_mult"]) - float(stop[i])) / float(stop[i]))

        # Mechanics parity: live book stop + live target, no trail, full path.
        if spec["family"] == "tbn":
            tgt = float(target[i]) if target[i] == target[i] and target[i] > en else (
                en * float(spec["target_fallback"]) if spec["target_fallback"] else 0.0
            )
            par = _walk(
                bars, op_i, cl_i, en, base=float(stop[i]), target=tgt,
                act=float(spec["act"]), keep=float(spec["keep"]),
                time_bars=int(spec["time_bars"]), round_dp=int(spec["round_dp"]),
                family="tbn", trail=False, book_fallback=False, book_px=0.0, book_xt="",
            )
            if isinstance(par, dict):
                parity_n += 1
                pp = (float(par["px"]) - en) / en * 100.0
                parity_abs.append(abs(pp - bpn))

        for pct in STOPS[code]:
            if spec["anchor"] == "entry":
                new_stop = en * (1.0 - pct / 100.0)
            else:
                new_stop = anchor * (1.0 - pct / 100.0) if anchor == anchor else float("nan")
            if not (new_stop == new_stop and new_stop > 0 and new_stop < en):
                unfilled[pct] += 1
                continue
            if spec["family"] == "rsi":
                walked = _walk(
                    bars, op_i, cl_i, en, base=new_stop, target=0.0,
                    act=float(spec["act"]), keep=float(spec["keep"]),
                    time_bars=0, round_dp=int(spec["round_dp"]),
                    family="tbn", trail=True, book_fallback=True,
                    book_px=float(exit_px[i]) if exit_px[i] == exit_px[i] else float("nan"),
                    book_xt=str(exit_type[i]),
                )
            elif spec["family"] == "rl":
                walked = _walk(
                    bars, op_i, cl_i, en, base=new_stop, target=0.0,
                    act=float(spec["act"]), keep=float(spec["keep"]),
                    time_bars=0, round_dp=-1,
                    family="rl", trail=True, book_fallback=False, book_px=0.0, book_xt="",
                )
            else:
                tgt = float(target[i]) if target[i] == target[i] and target[i] > en else (
                    en * float(spec["target_fallback"]) if spec["target_fallback"] else 0.0
                )
                walked = _walk(
                    bars, op_i, cl_i, en, base=new_stop, target=tgt,
                    act=float(spec["act"]), keep=float(spec["keep"]),
                    time_bars=int(spec["time_bars"]), round_dp=int(spec["round_dp"]),
                    family="tbn", trail=True, book_fallback=False, book_px=0.0, book_xt="",
                )
            if walked == "missing" or not isinstance(walked, dict):
                unfilled[pct] += 1
                continue
            new_pnl = (float(walked["px"]) - en) / en * 100.0
            new_d = notion * new_pnl / 100.0 if notion == notion else bdl
            ymd_x = int(walked["ymd"])
            base_rows[pct].append(_trade_dict(
                sym, ind, op_i, ymd_x, new_pnl, new_d,
                _hold_days(op_i, ymd_x, bd, True),
                str(walked["tag"]),
            ))

    arms = []
    arms.append({
        "id": "control",
        "label": "Control — live stop, live exit",
        "pct": None,
        "kind": "control",
        "tighter": False,
        "unfilled": 0,
        "slices": _metrics_for(hwm1, control_rows, cash),
    })
    arms.append({
        "id": "trail",
        "label": f"Live stop + trail (on at {spec['act']:.0f}%, keep {spec['keep']*100:.0f}%)",
        "pct": None,
        "kind": "trail",
        "tighter": False,
        "unfilled": 0,
        "slices": _metrics_for(hwm1, trail_rows, cash),
    })
    for pct in STOPS[code]:
        live = spec["live_pct"]
        tighter = True if live is None else float(pct) < float(live) - 1e-9
        arms.append({
            "id": f"base_{pct}",
            "label": f"{pct:g}% base + trail",
            "pct": float(pct),
            "kind": "base",
            "tighter": tighter,
            "unfilled": int(unfilled[pct]),
            "slices": _metrics_for(hwm1, base_rows[pct], cash),
        })

    def _best(cands: list[dict[str, Any]]) -> dict[str, Any]:
        def key(a: dict[str, Any]):
            avg = a["slices"]["IS"].get("avg_pnl_pct")
            ann = a["slices"]["IS"].get("ann_ror")
            avg_k = float(avg) if avg is not None and math.isfinite(float(avg)) else -1e18
            ann_k = float(ann) if ann is not None and math.isfinite(float(ann)) else -1e18
            return (avg_k, ann_k)
        return max(cands, key=key)

    non_ctrl = [a for a in arms if a["kind"] != "control"]
    fives = [a for a in arms if a["kind"] == "base"]
    best = _best(non_ctrl)
    best5 = _best(fives)
    ctrl_is = arms[0]["slices"]["IS"]
    trail_is = arms[1]["slices"]["IS"]
    ctrl_avg = ctrl_is.get("avg_pnl_pct")
    trail_avg = trail_is.get("avg_pnl_pct")

    def _beats(arm: dict[str, Any]) -> bool:
        avg = arm["slices"]["IS"].get("avg_pnl_pct")
        if ctrl_avg is None or avg is None:
            return False
        return float(avg) - float(ctrl_avg) > FLAT_PP

    tighter_beats = [a for a in fives if a["tighter"] and _beats(a)]
    any_five_beats = [a for a in fives if _beats(a)]
    trail_is_best = best["kind"] == "trail"
    trail_below = (
        ctrl_avg is not None and trail_avg is not None and float(trail_avg) < float(ctrl_avg) - FLAT_PP
    )
    parity = {
        "n": parity_n,
        "median_abs_pnl_pp": float(np.median(parity_abs)) if parity_abs else None,
        "p90_abs_pnl_pp": float(np.percentile(parity_abs, 90)) if parity_abs else None,
        "within_0_25pp": float(np.mean(np.array(parity_abs) < 0.25)) if parity_abs else None,
        "snap_ok": snap_ok,
        "snap_n": snap_n,
        "anchor_median_rel_err": float(np.median(anchor_err)) if anchor_err else None,
    }
    print(
        f"  control IS avg {ctrl_avg} trail IS avg {trail_avg} "
        f"best5 {best5['label']} IS avg {best5['slices']['IS'].get('avg_pnl_pct')} "
        f"parity med {parity['median_abs_pnl_pp']}",
        flush=True,
    )
    return {
        "code": code,
        "label": spec["label"],
        "act": spec["act"],
        "keep": spec["keep"],
        "live_pct": spec["live_pct"],
        "live_mult": spec["live_mult"],
        "anchor": spec["anchor"],
        "family": spec["family"],
        "cash": cash,
        "cash_src": cash_src,
        "stop_col": meta.get("stop_col", ""),
        "n_file": int(meta.get("n_loaded", len(df))),
        "n_scored": n,
        "short_skipped": int(pack.get("short_skipped", 0)),
        "missing_ohlc": int(pack.get("missing_ohlc", 0)),
        "arms": arms,
        "best_id": best["id"],
        "best5_id": best5["id"],
        "tighter_beats": [a["id"] for a in tighter_beats],
        "any_five_beats": [a["id"] for a in any_five_beats],
        "trail_is_best_of_new": trail_is_best,
        "trail_below_control": trail_below,
        "parity": parity,
    }


def _slice_cells(arm: dict[str, Any], sl: str, ctrl: dict[str, Any]) -> str:
    m = arm["slices"][sl]
    c = ctrl["slices"][sl]
    n = m.get("n")
    cn = c.get("n")
    n_txt = f"{int(n):,}" if n is not None else "—"
    if cn is not None and n is not None and int(n) != int(cn):
        n_txt += f" (control {int(cn):,})"
    cells = [
        n_txt,
        _fmt(m.get("win_pct"), "pct"),
        _fmt(m.get("avg_pnl_pct"), "pct"),
        _fmt(m.get("ann_ror"), "pct"),
        _fmt_delta(_delta(m.get("avg_pnl_pct"), c.get("avg_pnl_pct")), "pct"),
        _fmt_delta(_delta(m.get("ann_ror"), c.get("ann_ror")), "pct"),
    ]
    if arm["kind"] == "control":
        cells[4] = "—"
        cells[5] = "—"
    return "".join(f"<td>{x}</td>" for x in cells)


def _main_table(res: dict[str, Any]) -> str:
    ctrl = res["arms"][0]
    head = (
        "<tr>"
        + _th("Arm", "text")
        + _th("Unfilled", "num")
        + _th("N full", "num") + _th("Win % full", "num") + _th("Avg return full", "num") + _th("Ann ROR full", "num")
        + _th("Δ avg full", "num") + _th("Δ Ann ROR full", "num")
        + _th("N IS", "num") + _th("Win % IS", "num") + _th("Avg return IS", "num") + _th("Ann ROR IS", "num")
        + _th("Δ avg IS", "num") + _th("Δ Ann ROR IS", "num")
        + _th("N OOS", "num") + _th("Win % OOS", "num") + _th("Avg return OOS", "num") + _th("Ann ROR OOS", "num")
        + _th("Δ avg OOS", "num") + _th("Δ Ann ROR OOS", "num")
        + "</tr>"
    )
    body = []
    for arm in res["arms"]:
        cls = ' class="best-row"' if arm["id"] == res["best_id"] else ""
        unf = "0" if arm["kind"] != "base" else f"{int(arm['unfilled']):,}"
        body.append(
            f"<tr{cls}><td>{html_mod.escape(arm['label'])}</td><td>{unf}</td>"
            + _slice_cells(arm, "FULL", ctrl)
            + _slice_cells(arm, "IS", ctrl)
            + _slice_cells(arm, "OOS", ctrl)
            + "</tr>"
        )
    return (
        f"<h2>{html_mod.escape(res['label'])}</h2>"
        f"<p>Live starting-stop distance: {html_mod.escape(_live_blurb(res))}. "
        f"Trail stays at {res['act']:.0f}% activation, keep {res['keep']*100:.0f}%. "
        f"Slot cash {html_mod.escape(format_money(res['cash']))}. {html_mod.escape(res['cash_src'])}. "
        f"Scored {res['n_scored']:,} of {res['n_file']:,} closed rows "
        f"(shorts left out {res['short_skipped']:,}; no daily path {res['missing_ohlc']:,}). "
        f"The highlighted row is the best non-control arm on in-sample average return.</p>"
        f"<div class=\"table-wrap\"><table class=\"sortable\"><thead>{head}</thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def _live_blurb(res: dict[str, Any]) -> str:
    if res["live_pct"] is None:
        return "none (Relative Strength Index has no price stop today)"
    if res["anchor"] == "entry":
        return f"{res['live_pct']:g}% under the buy (entry × {res['live_mult']})"
    return f"{res['live_pct']:g}% under the {res['anchor']}-day low (low × {res['live_mult']})"


def _canon_table(res: dict[str, Any], arms: list[dict[str, Any]], sl: str, title: str) -> str:
    ctrl = res["arms"][0]
    head = "<tr>" + _th("Metric", "text")
    for arm in arms:
        head += _th(arm["label"], "num") + _th(f"Δ {arm['label']}", "num")
    head += "</tr>"
    rows = []
    # N first
    rows.append(_metric_row("Trades", "n", "int", arms, ctrl, sl, force_delta_ctrl=True))
    for label, key, kind in METRIC_SPEC:
        rows.append(_metric_row(label, key, kind, arms, ctrl, sl))
    # Exit mix
    types: list[str] = []
    seen = set()
    for arm in arms:
        mix = arm["slices"][sl].get("exit_mix") or {}
        for k in mix:
            if k not in seen:
                seen.add(k)
                types.append(k)
    for xt in types:
        rows.append(_exit_row(xt, arms, ctrl, sl))
    return (
        f"<h3>{html_mod.escape(title)}</h3>"
        f"<div class=\"table-wrap\"><table class=\"sortable\"><thead>{head}</thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _metric_row(label, key, kind, arms, ctrl, sl, force_delta_ctrl: bool = False) -> str:
    tds = [f"<td>{html_mod.escape(label)}</td>"]
    cval = ctrl["slices"][sl].get(key)
    for arm in arms:
        val = arm["slices"][sl].get(key)
        tds.append(f"<td>{_fmt(val, kind)}</td>")
        if arm["kind"] == "control" and not force_delta_ctrl:
            tds.append("<td>—</td>")
        else:
            tds.append(f"<td>{_fmt_delta(_delta(val, cval), kind)}</td>")
    return "<tr>" + "".join(tds) + "</tr>"


def _exit_row(xt: str, arms, ctrl, sl) -> str:
    tds = [f"<td>Exit {html_mod.escape(xt)} count</td>"]
    def _cnt(arm):
        mix = arm["slices"][sl].get("exit_mix") or {}
        return float(mix.get(xt, 0)), float(arm["slices"][sl].get("n") or 0)
    cc, cn = _cnt(ctrl)
    for arm in arms:
        c, n = _cnt(arm)
        pct = (100.0 * c / n) if n else None
        tds.append(f"<td>{int(c):,} ({_fmt(pct, 'pct')})</td>")
        if arm["kind"] == "control":
            tds.append("<td>—</td>")
        else:
            tds.append(f"<td>{_fmt_delta(_delta(c, cc), 'int')}</td>")
    return "<tr>" + "".join(tds) + "</tr>"


def _verdict(res: dict[str, Any]) -> str:
    ctrl = res["arms"][0]["slices"]["IS"]
    trail = res["arms"][1]["slices"]["IS"]
    best5 = next(a for a in res["arms"] if a["id"] == res["best5_id"])
    b5 = best5["slices"]["IS"]
    bits = [
        f"<strong>{html_mod.escape(res['label'])}.</strong> "
        f"In-sample average return is {_fmt(ctrl.get('avg_pnl_pct'), 'pct')} on the control "
        f"(Ann ROR {_fmt(ctrl.get('ann_ror'), 'pct')}, win rate {_fmt(ctrl.get('win_pct'), 'pct')}). "
        f"Live stop plus the trail: average return {_fmt(trail.get('avg_pnl_pct'), 'pct')}, "
        f"Ann ROR {_fmt(trail.get('ann_ror'), 'pct')}, win rate {_fmt(trail.get('win_pct'), 'pct')}."
    ]
    rel = "tighter than today's stop" if best5["tighter"] else "wider than today's stop"
    if res["live_pct"] is None:
        rel = "a new price stop (there is no price stop today)"
    bits.append(
        f" Best of the five listed bases on in-sample average return: {html_mod.escape(best5['label'])} "
        f"({rel}). In-sample average return {_fmt(b5.get('avg_pnl_pct'), 'pct')}, "
        f"Ann ROR {_fmt(b5.get('ann_ror'), 'pct')}, win rate {_fmt(b5.get('win_pct'), 'pct')}."
    )
    b5_avg = b5.get("avg_pnl_pct")
    if ctrl.get("avg_pnl_pct") is not None and b5_avg is not None and float(b5_avg) - float(ctrl["avg_pnl_pct"]) <= FLAT_PP:
        bits.append(" That listed base is still below the control on in-sample average return.")
    if res["tighter_beats"]:
        names = ", ".join(
            html_mod.escape(a["label"]) for a in res["arms"] if a["id"] in res["tighter_beats"]
        )
        bits.append(f" A tighter base plus the trail beats the control on in-sample average return: {names}.")
    else:
        bits.append(" No tighter base plus the trail beats the control on in-sample average return.")
    if res["any_five_beats"] and not res["tighter_beats"]:
        names = ", ".join(html_mod.escape(a["label"]) for a in res["arms"] if a["id"] in res["any_five_beats"])
        bits.append(f" A listed base that is not tighter than today's stop does beat the control: {names}.")
    if res["trail_is_best_of_new"] and res["trail_below_control"]:
        bits.append(
            " The live-stop-plus-trail arm is still the best of these new arms, and it is still below the control "
            "on in-sample average return."
        )
    elif res["trail_is_best_of_new"]:
        bits.append(" The live-stop-plus-trail arm is the best of these new arms on in-sample average return.")
    else:
        bits.append(
            " One of the five new bases beats the live-stop-plus-trail arm on in-sample average return."
        )
    bits.append(" Out-of-sample was not used to pick that read.")
    return "<p>" + " ".join(bits) + "</p>"


def render(results: list[dict[str, Any]]) -> str:
    mains = "".join(_main_table(r) for r in results)
    if not any(r["any_five_beats"] for r in results):
        lead = (
            "<p><strong>Result.</strong> On in-sample average return, none of the five listed bases "
            "plus the trail beats that system's control. No tighter base beats the control either. "
            "Where the live-stop-plus-trail arm is still the best of these arms, it is still below the control.</p>"
        )
    else:
        lead = (
            "<p><strong>Result.</strong> At least one listed base plus the trail beats its control "
            "on in-sample average return. The system notes below name which ones. Out-of-sample was not used.</p>"
        )
    verdicts = lead + "".join(_verdict(r) for r in results)
    canon = []
    for res in results:
        best = next(a for a in res["arms"] if a["id"] == res["best_id"])
        pair = [res["arms"][0], best]
        canon.append(f"<h2>{html_mod.escape(res['label'])} — control vs best in-sample arm</h2>")
        canon.append(
            "<p>Best in-sample arm is chosen by in-sample average return, "
            "tie broken by in-sample annualized rate of return. Out-of-sample did not pick it. "
            f"Best arm: {html_mod.escape(best['label'])}.</p>"
        )
        for sl, title in (
            ("FULL", "Full book"),
            ("IS", "In-sample (entry before 2024-01-01)"),
            ("OOS", "Out-of-sample (entry on or after 2024-01-01) — report only"),
        ):
            canon.append(_canon_table(res, pair, sl, title))
        canon.append(f"<h2>{html_mod.escape(res['label'])} — every arm, canonical set</h2>")
        for sl, title in (
            ("FULL", "Full book, every arm"),
            ("IS", "In-sample, every arm"),
            ("OOS", "Out-of-sample, every arm — report only"),
        ):
            canon.append(_canon_table(res, res["arms"], sl, title))
    parity_rows = []
    for res in results:
        p = res["parity"]
        if res["anchor"] == "entry":
            snap_txt = "entry anchor"
        else:
            snap_txt = f"{p['snap_ok']:,} / {p['snap_n']:,}"
        if res["family"] != "tbn":
            note = "Not compared. Rocket Launcher's live exit is the partial ladder, which this replay does not rebuild. Relative Strength Index falls back to the live exit when the new stop and the trail do not hit."
            if res["family"] == "rsi":
                note = "The new arms fall back to the live Relative Strength Index exit when the price stop and the trail do not hit, so a no-stop replay would match the book by construction."
            parity_rows.append(
                f"<tr><td>{html_mod.escape(res['code'])}</td><td>—</td><td>—</td><td>—</td>"
                f"<td>{html_mod.escape(snap_txt)}</td>"
                f"<td>{_fmt((p['anchor_median_rel_err'] or 0) * 100 if p['anchor_median_rel_err'] is not None else None, 'pct')}</td>"
                f"<td>{html_mod.escape(note)}</td></tr>"
            )
        else:
            parity_rows.append(
                "<tr>"
                f"<td>{html_mod.escape(res['code'])}</td>"
                f"<td>{p['n']:,}</td>"
                f"<td>{_fmt(p['median_abs_pnl_pp'], 'num')}</td>"
                f"<td>{_fmt((p['within_0_25pp'] or 0) * 100, 'pct')}</td>"
                f"<td>{html_mod.escape(snap_txt)}</td>"
                f"<td>{_fmt((p['anchor_median_rel_err'] or 0) * 100 if p['anchor_median_rel_err'] is not None else None, 'pct')}</td>"
                f"<td>Replay of the live stop and the live target, trail off, versus the closed-trade percent.</td>"
                "</tr>"
            )
    parity_table = (
        "<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>"
        + _th("System", "text") + _th("Trades checked", "num")
        + _th("Median abs pnl diff (pp)", "num") + _th("Within 0.25 pp", "num")
        + _th("Anchor snapped to a bar low", "text") + _th("Median anchor vs live stop", "num")
        + _th("Note", "text")
        + "</tr></thead><tbody>"
        + "".join(parity_rows)
        + "</tbody></table></div>"
    )
    missing = "".join(f"<li><strong>{html_mod.escape(n)}</strong> — {html_mod.escape(w)}</li>" for n, w in NOT_COMPUTED)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Tighter base stops plus Paul's high-water trail</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 24px; color: #0f172a; line-height: 1.45; }}
h1 {{ font-size: 1.4rem; }}
h2 {{ font-size: 1.15rem; margin-top: 1.6rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; border-radius: 10px; padding: 12px 14px; margin: 12px 0; }}
.banner {{ background: #fff7ed; border: 1px solid #fdba74; border-radius: 10px; padding: 12px 14px; margin: 12px 0; }}
tr.best-row td {{ background: #ecfdf5; }}
code {{ font-size: 0.92em; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Tighter base stops plus Paul's high-water trail</h1>
<p>Research only. Not gold. Not DailyRun. Out-of-sample is report-only. Nothing here is wired into the live run.</p>
<div class="callout">
<h2>What you asked</h2>
<p>{html_mod.escape(ASK).replace(chr(10), "<br>")}</p>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN)}</p>
</div>
<div class="banner">
<p><strong>Selection bias.</strong> The trail settings were picked after the activation grid in <code>hwm_stop_activate_at_n_20261015</code>, and these stop percents were chosen after that trail page (<code>hwm_stop_paul_picks_20261015</code>) and the win-rate jump it showed. That is in-sample selection on this same history. This page does not retune from out-of-sample, and it does not name a winner from out-of-sample.</p>
<p><strong>Judge.</strong> The read uses in-sample average return versus that system's control. In-sample means entry_date before 2024-01-01. Out-of-sample means entry_date on or after 2024-01-01. A lift smaller than 0.005 percentage points counts as flat.</p>
<p><strong>Rocket Launcher partial exit.</strong> The live book sells 80% at +20% from the buy, moves the leftover stop to the buy, and sells the leftover at +40%. That ladder is in the control. It is also in the live-stop-plus-trail arm, because that arm is the live closed trade plus the trail (the arm already on the pick page). It is not in the five new base-stop arms. Those arms are the listed stop, plus the 6% / keep 80% trail, and no price target. The live 50-day Simple Moving Average (SMA) target is off, and the +20% and +40% levels belong to the ladder, so they are not added back. If neither the stop nor the trail hits, the trade is marked at the last daily close (<code>DATA_END</code>).</p>
<p><strong>How the new stop is placed.</strong> Break and ReTest, Year High, and Magic Touch: percent under the trigger-day low. Today's live stop is that low × 0.934 (6.6% under). Weekly Pivot Break and Retest: percent under the retest-day low. Today's live stop is that low × 0.92 (8% under). A listed 5.44% stop is the anchor × (1 − 0.0544). Rocket Launcher: percent under the signal-day low. Today is signal low × 0.934. Relative Strength vs SPY: percent under the buy. Today is entry × 0.85 (15% under). Relative Strength Index: a new stop under the buy. The anchor is snapped to a daily low in the eight sessions before the buy when that low is within 0.5% of the stop implied by the live multiplier.</p>
<p><strong>Trail.</strong> Off until a prior day's high-water mark is at least the activation percent above the buy. Then stop = buy + keep × (high-water mark − buy). Never loosen below the base stop in force on that arm. Open through the stop sells at the open. A low at or below the stop sells at the stop. A new high raises the next day's stop. The entry day cannot activate the trail and cannot sell on the trail. The base stop can sell on the entry day, matching the live engine (Rocket Launcher checks the entry-day close, not the entry-day low). The price target, when the arm has one, is checked after the stop. If the open is already through the target, the sell is at the open.</p>
<p>The first mention of annualized rate of return is this sentence. After that, Ann ROR is the house formula <code>((1 + total profit / (slot cash × N)) ^ (365 / average days held) − 1) × 100</code> via <code>compare_format.ann_ror_from_closed</code>. Slot cash is the Closed median implied notional. Report capacity is used only when it sits within about 25% of that median. A flat $47,500 sheet slot is not used when the closed book is capacity-sized. The same slot cash is used for every arm of a system. Max drawdown and Sharpe use exit-date equity seeded at $500,000. Calmar is Ann ROR divided by the absolute value of max drawdown when both exist.</p>
{verdicts}
</div>
<p>Click column headers to sort. {SWIPE_NOTE_HTML}</p>
<h2>Main compare</h2>
<p>One block per system. Rows are the control, today's stop plus Paul's trail, then the five listed base stops plus that same trail. N is shown on each slice. If a tighter stop leaves the buy at or below the stop, that trade does not fill and N drops; the Unfilled column counts those. Deltas are versus that system's control. The green row is the best non-control arm on in-sample average return.</p>
{mains}
<h2>Canonical metrics</h2>
<p>Absolute values and deltas versus the control. The first block in each system is the control and the best in-sample arm. The following blocks are every arm. Book leave-max-win-out is Book AVG_PNL_PCT_WO_MAX.</p>
{''.join(canon)}
<h2>Replay check</h2>
<p>For the price-target systems, replaying today's stop and today's target with the trail off should land near the closed-trade percent. A large gap means the new arms are on a different exit path than the live engine. Anchor error is how far anchor × today's multiplier sits from the stored stop.</p>
{parity_table}
<h2>Canonical fields not recomputed</h2>
<ul>{missing}</ul>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""


def _jsonable(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): _jsonable(val) for k, val in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, (np.floating,)):
        x = float(v)
        return None if not math.isfinite(x) else x
    if isinstance(v, (np.integer,)):
        return int(v)
    return v


def write_baseline(results: list[dict[str, Any]]) -> None:
    lines = [
        "# Tighter base stops plus Paul's high-water trail — 2026-10-15",
        "",
        "Research only. Not gold. Not DailyRun. No knob was chosen from out-of-sample. Earlier high-water stamps were read, not edited.",
        "",
        "## What you asked",
        "",
        "> so by putting this aggressive trailing stop loss in, we don't let our winners grow as much, but we do increase the amount of winners we have overall. the most extreme example is WPBR going from a win rate of 52.12% to 83.86%!",
        ">",
        "> so, i'm thinking we might need to reduce our stop losses when the stock doesn't rise.",
        "> can you rerun these systems through using these new trailing stop losses and the base stop losses change here:",
        "> BRT 5.44%, 6.8, 9.07, 10.46, 13.6",
        "> RL 0.65%, 0.81, 1.08, 1.24, 1.62",
        "> YH 0.95%, 1.19, 1.59, 1.83, 2.38",
        "> MTS 2.56%, 3.2, 4.26, 4.92, 6.39",
        "> WPBR 3.03%, 3.79, 5.06, 5.84, 7.59",
        "> RS 7.13%, 8.91, 11.88, 13.7, 17.81",
        "> RSI 2.07%, 2.58, 3.44, 3.97, 5.17",
        "",
        "## In plain English",
        "",
        PLAIN,
        "",
        "## Freeze",
        "",
        "- Control = `Drive/{SYSTEM}_LatestRun_Closed.csv` live exit, no high-water trail.",
        "- Trail settings are Paul's picks and are not changed: Break and ReTest (BRT) 6% / keep 70%; Rocket Launcher (RL) 6% / 80%; Year High (YH) 2% / 70%; Magic Touch (MTS) 4% / 60%; Weekly Pivot Break and Retest (WPBR) 2% / 80%; Relative Strength vs SPY (RS) 10% / 80%; Relative Strength Index (RSI) 6% / 80%.",
        "- Live anchors: BRT, YH, MTS trigger low × 0.934 (6.6%). WPBR retest low × 0.92 (8%). RL signal low × 0.934 (6.6%). RS entry × 0.85 (15%). RSI has no price stop.",
        "- Listed percents are distances. New stop = anchor × (1 − percent). Not the 0.934 multiplier encoding.",
        "- IS = entry_date < 2024-01-01. OOS = entry_date >= 2024-01-01. OOS is report-only.",
        "- Judge: in-sample average return versus the control. Flat band 0.005 percentage points. Best arm tie-break is in-sample annualized rate of return.",
        "- Annualized rate of return: `compare_format.ann_ror_from_closed`, days_per_year 365, on every arm and every slice. Slot cash = Closed median implied notional, same cash for every arm of a system. Report capacity_brt_cash only when within 25% of that median. No flat $47,500 when the book is capacity-sized.",
        "- Selection bias: trail settings and these percents were chosen after earlier tables on this history.",
        "- Rocket Launcher partial ladder (80% at +20%, leftover stop at the buy, leftover at +40%) stays on the control and on the live-stop-plus-trail arm. The five new Rocket Launcher arms do not use it and have no other price target (SMA envelope target is off). Unfinished names are marked at the last close (`DATA_END`).",
        "- Price-target systems keep the closed-trade target (fallback buy × 1.21 BRT/YH, × 1.22 MTS, × 1.20 WPBR, × 1.25 RS) and RS 252-bar time stop at the close. Stop is checked before the target.",
        "- Entry day: trail cannot activate or sell. Base stop can. Rocket Launcher entry day uses the close.",
        "",
        "## Read (in-sample average return only)",
        "",
    ]
    for res in results:
        ctrl = res["arms"][0]["slices"]["IS"]
        trail = res["arms"][1]["slices"]["IS"]
        best5 = next(a for a in res["arms"] if a["id"] == res["best5_id"])
        b5 = best5["slices"]["IS"]
        lines.append(
            f"- **{res['label']}** — control in-sample average return {_fmt(ctrl.get('avg_pnl_pct'), 'pct')}, "
            f"Ann ROR {_fmt(ctrl.get('ann_ror'), 'pct')}. "
            f"Live stop + trail: average return {_fmt(trail.get('avg_pnl_pct'), 'pct')}, "
            f"Ann ROR {_fmt(trail.get('ann_ror'), 'pct')}, win rate {_fmt(trail.get('win_pct'), 'pct')}. "
            f"Best of the five: {best5['label']} — average return {_fmt(b5.get('avg_pnl_pct'), 'pct')}, "
            f"Ann ROR {_fmt(b5.get('ann_ror'), 'pct')}, win rate {_fmt(b5.get('win_pct'), 'pct')}. "
            f"Tighter base beats control: {'yes' if res['tighter_beats'] else 'no'}. "
            f"Trail-only is best of the new arms and still below control: "
            f"{'yes' if res['trail_is_best_of_new'] and res['trail_below_control'] else 'no'}."
        )
    lines += ["", "## Parity", ""]
    for res in results:
        p = res["parity"]
        lines.append(
            f"- {res['code']}: median abs replay-minus-book pnl {p['median_abs_pnl_pp']}; "
            f"within 0.25 pp {p['within_0_25pp']}; snap {p['snap_ok']}/{p['snap_n']}; "
            f"anchor median relative error {p['anchor_median_rel_err']}."
        )
    lines.append("")
    (OUT / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    _self_test()
    act = _load_act()
    # Touch the loader once so duckdb and helpers exist.
    act._load_hwm1()
    results = [run_system(act, spec) for spec in SYSTEMS]
    OUT.mkdir(parents=True, exist_ok=True)
    html = render(results)
    (OUT / "compare.html").write_text(html, encoding="utf-8")
    write_baseline(results)
    (OUT / "summary.json").write_text(json.dumps(_jsonable(results), indent=2), encoding="utf-8")
    print(f"wrote {OUT / 'compare.html'}", flush=True)


if __name__ == "__main__":
    main()
