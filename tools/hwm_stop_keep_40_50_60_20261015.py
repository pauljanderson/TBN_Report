#!/usr/bin/env python3
"""High-water stop overlay: keep 40/50/60% of the gain vs each system's current exit.

Research only. Does not wire DailyRun. Does not retune on out-of-sample.
"""
from __future__ import annotations

import html as html_mod
import json
import math
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import duckdb
import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
_PE = _REPO / "drive" / "paul_experiments"
_DRIVE = _REPO / "Drive"
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

STAMP = "hwm_stop_keep_40_50_60_20261015"
OUT = _PE / STAMP
DB = _REPO / "data" / "ohlcv.duckdb"
IS_CUT = 20240101
KS = (0.40, 0.50, 0.60)
ARMS = ("control", "k40", "k50", "k60")
ARM_LABEL = {
    "control": "Control",
    "k40": "Keep 40%",
    "k50": "Keep 50%",
    "k60": "Keep 60%",
}

# Live sleeves with a closed book. IND is deprecated. MUD is research-only.
SYSTEMS = [
    ("BRT", "Break and ReTest (BRT)", False),
    ("RL", "Rocket Launcher (RL)", False),
    ("YH", "Year High (YH)", False),
    ("MTS", "Magic Touch (MTS)", False),
    ("WPBR", "Weekly Pivot Break and Retest (WPBR)", False),
    ("RS", "Relative Strength vs SPY (RS)", False),
    ("SB", "StockBee (SB)", False),
    ("VZ", "Volume Zone (VZ)", False),
    ("RSI", "Relative Strength Index (RSI)", False),
    ("WRL", "Weekly Range / Swing (WRL)", False),
    ("MUD", "Most Up / Most Down (MUD)", True),
]

ASK = (
    "in addition to the way it is today, can you run a test on every system we have "
    "where we move the stop loss to be 50% of whatever the high water mark is for the "
    "stock after purchase. for example, if a stock's high of the day is up 10% from "
    "entry price, we move the stop loss to 5% gain, etc. i would like to see a table "
    "with all systems control vs. this new stop loss theory. maybe in addition to 50% "
    "of the gain, we try 40% and 60%. do this for IS, and also track OOS and full so "
    "we can confirm."
)

PLAIN = (
    "Each system already has a finished trade list and its own way of getting out. "
    "That current exit is the control, left unchanged. The new idea watches the "
    "highest daily high after the buy (the high-water mark) and lifts the stop so "
    "it keeps only part of that gain. Keep 40% means the stop sits at 40% of the "
    "rise from the buy price to that high; keep 50% and keep 60% do the same with "
    "a larger share of the gain left on the table before the stop. Example: buy at "
    "$100, later daily high $110 (up 10%). Keep 50% puts the stop at $105 (a 5% "
    "gain). The stop for today uses only highs through yesterday. If the open is "
    "already through the stop, the sell is at the open. If the low tags the stop, "
    "the sell is at the stop. If that stop never hits, the original exit still "
    "stands. The new stop is used only when it is tighter than the system's "
    "original stop. This is not a Simple Moving Average (SMA) trail, and it is "
    "not Rocket Launcher's separate partial-exit plan (sell most at +20%, rest at "
    "entry or +40%)."
)


def _th(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{typ}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _norm(name: str) -> str:
    return " ".join(str(name).strip().upper().replace("_", " ").replace("%", " PCT").split())


def _parse_ymd_series(s: pd.Series) -> np.ndarray:
    if pd.api.types.is_numeric_dtype(s):
        num = pd.to_numeric(s, errors="coerce")
        return num.fillna(0).astype(np.int64).to_numpy()
    text = s.astype(str).str.strip()
    compact = text.str.replace("-", "", regex=False).str.replace("/", "", regex=False).str.slice(0, 8)
    num = pd.to_numeric(compact, errors="coerce")
    # m/d/yyyy already stripped slashes may be ambiguous; ISO and YYYYMMDD are the house forms.
    return num.fillna(0).astype(np.int64).to_numpy()


def _to_num(s: pd.Series) -> np.ndarray:
    if pd.api.types.is_numeric_dtype(s):
        return pd.to_numeric(s, errors="coerce").to_numpy(dtype=float)
    t = (
        s.astype(str)
        .str.strip()
        .str.replace("%", "", regex=False)
        .str.replace("$", "", regex=False)
        .str.replace(",", "", regex=False)
        .str.replace("(", "-", regex=False)
        .str.replace(")", "", regex=False)
    )
    return pd.to_numeric(t, errors="coerce").to_numpy(dtype=float)


def _pick(cols: dict[str, str], *names: str) -> Optional[str]:
    for n in names:
        if n in cols:
            return cols[n]
    return None


def _report_capacity(system: str) -> Optional[float]:
    reps = sorted(_DRIVE.glob(f"{system}_Report_*.csv"))
    if not reps:
        return None
    try:
        row = pd.read_csv(reps[-1], nrows=1).iloc[0].to_dict()
    except Exception:
        return None
    for key in ("capacity_brt_cash", "brt_cash", "sheet_brt_cash"):
        v = row.get(key)
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(fv) and fv > 0:
            return fv
    return None


def load_trades(system: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    path = _DRIVE / f"{system}_LatestRun_Closed.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    raw = pd.read_csv(path, low_memory=False)
    lookup = {_norm(c): c for c in raw.columns}
    sym_c = _pick(lookup, "SYMBOL")
    open_c = _pick(lookup, "DATE OPENED")
    close_c = _pick(lookup, "DATE CLOSED")
    entry_c = _pick(lookup, "ENTRY PRICE")
    exit_c = _pick(lookup, "EXIT PRICE")
    xt_c = _pick(lookup, "EXIT TYPE")
    days_c = _pick(lookup, "DAYS HELD")
    pnl_c = _pick(lookup, "PNL PCT", "PNL")
    pnld_c = _pick(lookup, "PNL DOLLARS")
    stop_c = _pick(lookup, "ORIGINAL STOP", "STOP PRICE")
    side_c = _pick(lookup, "SIDE")
    ind_c = _pick(lookup, "INDUSTRY")
    notion_c = _pick(lookup, "ENTRY NOTIONAL")
    if not all([sym_c, open_c, close_c, entry_c, pnl_c]):
        raise SystemExit(f"{system}: missing identity columns among {list(raw.columns)[:12]}")
    df = pd.DataFrame(
        {
            "symbol": raw[sym_c].astype(str).str.upper().str.strip(),
            "opened": _parse_ymd_series(raw[open_c]),
            "closed": _parse_ymd_series(raw[close_c]),
            "entry": _to_num(raw[entry_c]),
            "pnl": _to_num(raw[pnl_c]),
        }
    )
    df["exit_px"] = _to_num(raw[exit_c]) if exit_c else np.nan
    df["days"] = _to_num(raw[days_c]) if days_c else np.nan
    df["pnl_d"] = _to_num(raw[pnld_c]) if pnld_c else np.nan
    df["stop"] = _to_num(raw[stop_c]) if stop_c else np.nan
    df["side"] = raw[side_c].astype(str).str.upper().str.strip() if side_c else "LONG"
    df["industry"] = raw[ind_c].astype(str).str.strip() if ind_c else ""
    df["exit_type"] = raw[xt_c].astype(str).str.strip().str.upper() if xt_c else "UNKNOWN"
    if notion_c:
        df["entry_notional"] = _to_num(raw[notion_c])
    else:
        df["entry_notional"] = np.nan
    # Percent points, not fractions. A book stored as 0.21 would have a tiny median.
    med_abs = float(np.nanmedian(np.abs(df["pnl"].to_numpy())))
    if math.isfinite(med_abs) and 0 < med_abs < 0.5:
        df["pnl"] = df["pnl"] * 100.0
    df = df[(df["symbol"] != "") & (df["symbol"] != "NAN")]
    df = df[(df["opened"] > 19000101) & (df["closed"] >= df["opened"]) & (df["entry"] > 0)]
    df = df[np.isfinite(df["pnl"].to_numpy())].copy()
    meta = {
        "path": str(path),
        "rows_file": int(len(raw)),
        "has_pnl_dollars": bool(pnld_c),
        "stop_col": stop_c or "",
        "n_loaded": int(len(df)),
    }
    return df.reset_index(drop=True), meta


def slot_cash(df: pd.DataFrame, system: str) -> tuple[float, str, np.ndarray]:
    """Per-trade notional and the Ann ROR slot cash (median, capacity only if close)."""
    pnl = df["pnl"].to_numpy(dtype=float)
    doll = df["pnl_d"].to_numpy(dtype=float)
    entry_n = df["entry_notional"].to_numpy(dtype=float) if "entry_notional" in df.columns else np.full(len(df), np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        implied = np.where(
            np.isfinite(doll) & np.isfinite(pnl) & (np.abs(pnl) > 1e-6),
            np.abs(doll) / (np.abs(pnl) / 100.0),
            np.nan,
        )
    # Prefer implied dollars, then the file's entry notional, then slot.
    notion = np.where(np.isfinite(implied) & (implied > 0), implied, np.nan)
    notion = np.where(np.isfinite(notion), notion, np.where(np.isfinite(entry_n) & (entry_n > 0), entry_n, np.nan))
    finite = notion[np.isfinite(notion) & (notion > 0)]
    med = float(np.median(finite)) if len(finite) else float("nan")
    cap = _report_capacity(system)
    if math.isfinite(med) and med > 0:
        if cap is not None and 0.75 <= (med / cap) <= 1.25:
            src = f"Closed median implied notional ${med:,.2f} (Report capacity_brt_cash ${cap:,.2f} is within 25%)"
        elif cap is not None:
            src = (
                f"Closed median implied notional ${med:,.2f} "
                f"(Report capacity_brt_cash ${cap:,.2f} is outside 25%, so the median is the slot)"
            )
        else:
            src = f"Closed median implied notional ${med:,.2f} (no Report capacity_brt_cash)"
        cash = med
        notion = np.where(np.isfinite(notion) & (notion > 0), notion, cash)
        # Rebuild missing dollars off the trade's own notional.
        miss = ~np.isfinite(doll)
        doll = np.where(miss, notion * pnl / 100.0, doll)
        return cash, src, doll
    if cap is not None and cap > 0:
        src = (
            f"No Closed dollar column, so slot cash is Report capacity_brt_cash ${cap:,.2f} "
            f"and each trade's dollars are that slot times its percent return. "
            f"Sheet $47,500 was not used."
        )
        notion = np.full(len(df), cap)
        doll = notion * pnl / 100.0
        return cap, src, doll
    raise SystemExit(f"{system}: cannot size slot cash from Closed dollars or Report capacity")


def load_ohlc(symbols: set[str]) -> dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
    if not symbols:
        return {}
    con = duckdb.connect(str(DB), read_only=True)
    try:
        df = con.execute(
            """
            SELECT UPPER(symbol) AS symbol, date, open, high, low
            FROM prices
            WHERE UPPER(symbol) IN (SELECT * FROM UNNEST(?))
            ORDER BY 1, 2
            """,
            [sorted(symbols)],
        ).fetchdf()
    finally:
        con.close()
    out: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = {}
    if df.empty:
        return out
    df["ymd"] = (
        pd.to_datetime(df["date"]).dt.year * 10000
        + pd.to_datetime(df["date"]).dt.month * 100
        + pd.to_datetime(df["date"]).dt.day
    ).astype(np.int64)
    for sym, g in df.groupby("symbol", sort=False):
        out[str(sym)] = (
            g["ymd"].to_numpy(dtype=np.int64),
            g["open"].to_numpy(dtype=np.float64),
            g["high"].to_numpy(dtype=np.float64),
            g["low"].to_numpy(dtype=np.float64),
        )
    return out


def _ymd_to_date(ymd: int) -> date:
    y = ymd // 10000
    m = (ymd // 100) % 100
    d = ymd % 100
    return date(int(y), int(m), int(d))


def replay_trade(
    bars: Optional[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]],
    opened: int,
    closed: int,
    entry: float,
    stop: float,
) -> dict[float, Optional[tuple[int, float, str]]] | str:
    """Return per-k (exit_ymd, exit_px, tag) or None to keep the book exit.

    A string 'missing' means the daily path cannot cover the hold.
    """
    if closed <= opened:
        return {k: None for k in KS}
    if bars is None:
        return "missing"
    dates, opens, highs, lows = bars
    if dates.size == 0 or int(dates[-1]) < closed:
        return "missing"
    i0 = int(np.searchsorted(dates, opened, side="left"))
    if i0 >= dates.size:
        return "missing"
    hwm = entry
    if int(dates[i0]) == opened:
        hi0 = float(highs[i0])
        if hi0 == hi0 and hi0 > hwm:
            hwm = hi0
        i = i0 + 1
    else:
        i = i0
    seen_after = False
    done: dict[float, Optional[tuple[int, float, str]]] = {k: None for k in KS}
    active = set(KS)
    stop_ok = stop == stop and stop > 0.0
    n = int(dates.size)
    while i < n and int(dates[i]) <= closed and active:
        di = int(dates[i])
        if di > opened:
            seen_after = True
            if hwm > entry:
                gain = hwm - entry
                op = float(opens[i])
                lo = float(lows[i])
                for k in list(active):
                    stop_px = entry + k * gain
                    if stop_ok and not (stop_px > stop):
                        continue
                    if op == op and op <= stop_px:
                        done[k] = (di, op, "HWM_GAP")
                        active.discard(k)
                    elif lo == lo and lo <= stop_px:
                        done[k] = (di, stop_px, "HWM_STOP")
                        active.discard(k)
        hi = float(highs[i])
        if hi == hi and hi > hwm:
            hwm = hi
        i += 1
    if not seen_after:
        return "missing"
    return done


def _calendar_days(opened: int, closed: int, book_days: float) -> float:
    if closed == opened:
        return float(book_days) if book_days == book_days and book_days > 0 else 1.0
    try:
        delta = (_ymd_to_date(closed) - _ymd_to_date(opened)).days
    except ValueError:
        delta = 0
    if delta <= 0:
        if book_days == book_days and book_days > 0:
            return float(book_days)
        return 1.0
    return float(delta)


def build_arm_rows(
    df: pd.DataFrame,
    ohlc: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]],
    dollars: np.ndarray,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    """One list of trades per arm. Control is the book. Overlays replace the exit when the stop hits."""
    stats = Counter()
    rows: dict[str, list[dict[str, Any]]] = {a: [] for a in ARMS}
    symbols = df["symbol"].to_numpy()
    opened = df["opened"].to_numpy(dtype=np.int64)
    closed = df["closed"].to_numpy(dtype=np.int64)
    entry = df["entry"].to_numpy(dtype=float)
    pnl = df["pnl"].to_numpy(dtype=float)
    days = df["days"].to_numpy(dtype=float)
    stop = df["stop"].to_numpy(dtype=float)
    exit_type = df["exit_type"].astype(str).to_numpy()
    industry = df["industry"].astype(str).to_numpy()
    side = df["side"].astype(str).to_numpy()
    n = len(df)
    for i in range(n):
        if i and i % 50000 == 0:
            print(f"    replay {i:,}/{n:,}", flush=True)
        sym = str(symbols[i])
        op_i = int(opened[i])
        cl_i = int(closed[i])
        en = float(entry[i])
        book_pnl = float(pnl[i])
        book_d = float(dollars[i])
        book_days = float(days[i]) if days[i] == days[i] and days[i] > 0 else _calendar_days(op_i, cl_i, float("nan"))
        notion = abs(book_d) / (abs(book_pnl) / 100.0) if abs(book_pnl) > 1e-6 else float("nan")
        if not (notion == notion and notion > 0):
            notion = abs(book_d) if book_pnl == 0 else float("nan")
        side_i = str(side[i])
        if side_i not in {"LONG", "L", "", "NAN"}:
            stats["short_skipped"] += 1
            continue
        bars = ohlc.get(sym)
        replay = replay_trade(bars, op_i, cl_i, en, float(stop[i]))
        if replay == "missing":
            stats["missing_ohlc"] += 1
            continue
        assert isinstance(replay, dict)
        ind = industry[i]
        xt = exit_type[i] or "UNKNOWN"
        base = {
            "symbol": sym,
            "opened": _ymd_to_date(op_i),
            "closed": _ymd_to_date(cl_i),
            "pnl": book_pnl,
            "pnl_d": book_d,
            "days": book_days,
            "exit_type": xt,
            "industry": ind,
        }
        rows["control"].append(base)
        stats["kept"] += 1
        for k, arm in ((0.40, "k40"), (0.50, "k50"), (0.60, "k60")):
            hit = replay.get(k)
            if hit is None:
                rows[arm].append(dict(base))
                continue
            exit_ymd, exit_px, tag = hit
            new_pnl = (exit_px - en) / en * 100.0
            if notion == notion and notion > 0:
                new_d = notion * new_pnl / 100.0
            else:
                new_d = book_d
            new_days = _calendar_days(op_i, exit_ymd, book_days)
            rows[arm].append(
                {
                    "symbol": sym,
                    "opened": _ymd_to_date(op_i),
                    "closed": _ymd_to_date(exit_ymd),
                    "pnl": new_pnl,
                    "pnl_d": new_d,
                    "days": new_days,
                    "exit_type": tag,
                    "industry": ind,
                }
            )
            stats[f"hit_{arm}"] += 1
    return rows, dict(stats)


def _slice(trades: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    if mode == "FULL":
        return trades
    out = []
    for t in trades:
        od = t["opened"]
        ymd = od.year * 10000 + od.month * 100 + od.day
        if mode == "IS" and ymd < IS_CUT:
            out.append(t)
        elif mode == "OOS" and ymd >= IS_CUT:
            out.append(t)
    return out


def book_metrics(trades: list[dict[str, Any]], cash: float) -> dict[str, Any]:
    empty = {
        "n": 0,
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
        "total_pnl_d": 0.0,
        "exit_mix": {},
        "ann_note": "No trades in this slice.",
    }
    if not trades:
        return empty
    pnl = np.array([float(t["pnl"]) for t in trades], dtype=float)
    pnl_d = np.array([float(t["pnl_d"]) for t in trades], dtype=float)
    days = np.array([float(t["days"]) for t in trades], dtype=float)
    n = len(trades)
    wins_m = pnl > 0
    loss_m = pnl < 0
    wins = int(wins_m.sum())
    losses = int(loss_m.sum())
    win_pct = 100.0 * wins / n
    avg_pct = float(np.mean(pnl))
    if n > 1:
        wo = float(np.mean(np.delete(pnl, int(np.argmax(pnl)))))
    else:
        wo = avg_pct
    total = float(pnl_d.sum())
    sum_w = float(pnl_d[pnl_d > 0].sum())
    sum_l = float((-pnl_d[pnl_d < 0]).sum())
    pf = (sum_w / sum_l) if sum_l > 0 else None
    wl_c = (wins / losses) if losses else None
    wl_d = pf
    avg_win = float(pnl[wins_m].mean()) if wins else None
    avg_loss = float(pnl[loss_m].mean()) if losses else None
    days_ok = days[days > 0]
    capital_days = float(days_ok.sum()) if len(days_ok) else 0.0
    avg_days = float(days_ok.mean()) if len(days_ok) else None
    med_days = float(np.median(days_ok)) if len(days_ok) else None
    p90_days = float(np.percentile(days_ok, 90)) if len(days_ok) else None
    ppcd = (total / capital_days) if capital_days > 0 else None
    ann = None
    ann_note = ""
    if cash > 0 and avg_days and avg_days > 0:
        ann = ann_ror_from_closed(total_pnl=total, n_trades=n, avg_days_held=avg_days, brt_cash=cash)
        if ann is None:
            ann_note = "Annualized rate of return could not be computed (base not positive)."
    else:
        ann_note = "Annualized rate of return could not be computed (missing cash or days held)."
    dated = [(t["closed"], float(t["pnl_d"])) for t in trades]
    mdd = max_dd_pct_from_closed_pnl_by_date(dated, initial_account=DEFAULT_INITIAL_ACCOUNT)
    sharpe = sharpe_from_closed_pnl_by_date(dated, initial_account=DEFAULT_INITIAL_ACCOUNT)
    calmar = None
    if ann is not None and mdd is not None and abs(mdd) > 1e-12:
        calmar = float(ann) / abs(float(mdd))
    # Losing streak by exit date then symbol.
    order = sorted(range(n), key=lambda i: (trades[i]["closed"], trades[i]["symbol"]))
    streak = 0
    best_streak = 0
    for i in order:
        if pnl[i] < 0:
            streak += 1
            if streak > best_streak:
                best_streak = streak
        else:
            streak = 0
    # Concentration vs total profit. Blank when the book did not make money.
    def _share(part: float) -> Optional[float]:
        if total > 1e-9:
            return 100.0 * part / total
        return None

    by_sym: dict[str, float] = {}
    by_ind: dict[str, float] = {}
    for i, t in enumerate(trades):
        by_sym[t["symbol"]] = by_sym.get(t["symbol"], 0.0) + float(pnl_d[i])
        ind = t.get("industry") or ""
        if ind and ind.upper() != "NAN":
            by_ind[ind] = by_ind.get(ind, 0.0) + float(pnl_d[i])
    pct_sym = _share(max(by_sym.values())) if by_sym else None
    pct_trade = _share(float(np.max(pnl_d))) if n else None
    pct_ind = _share(max(by_ind.values())) if by_ind else None
    ordered_d = np.sort(pnl_d)
    top10 = float(ordered_d[-10:].sum()) if n else 0.0
    bot10 = float(ordered_d[:10].sum()) if n else 0.0
    pct_top = _share(top10)
    pct_bot = _share(bot10)  # negative share of profit when total > 0
    win_dollars = pnl_d[pnl_d > 0]
    outlier = None
    if win_dollars.size and float(win_dollars.sum()) > 0:
        outlier = 100.0 * float(win_dollars.max()) / float(win_dollars.sum())
    opens = [t["opened"] for t in trades]
    span_days = (max(opens) - min(opens)).days
    tpy = None
    if span_days > 0:
        tpy = n / (span_days / 365.25)
    mix = dict(Counter(t["exit_type"] for t in trades))
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
        "wl_dollars": wl_d,
        "profit_factor": pf,
        "ann_ror": ann,
        "max_dd": mdd,
        "calmar": calmar,
        "sharpe": sharpe,
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
        "total_pnl_d": total,
        "exit_mix": mix,
        "ann_note": ann_note,
    }


METRIC_SPEC = [
    ("Total trades", "n", "num", "int"),
    ("Wins", "wins", "num", "int"),
    ("Losses", "losses", "num", "int"),
    ("Win %", "win_pct", "num", "pct"),
    ("Avg PnL %", "avg_pnl_pct", "num", "pct"),
    ("Book AVG_PNL_PCT_WO_MAX", "avg_pnl_pct_wo_max", "num", "pct"),
    ("Expectancy $", "expectancy_d", "num", "money"),
    ("Expectancy %", "expectancy_pct", "num", "pct"),
    ("Avg win %", "avg_win_pct", "num", "pct"),
    ("Avg loss %", "avg_loss_pct", "num", "pct"),
    ("Win/Loss ratio (count)", "wl_count", "num", "num"),
    ("Win/Loss ratio $", "wl_dollars", "num", "num"),
    ("Profit factor", "profit_factor", "num", "num"),
    ("Ann ROR %", "ann_ror", "num", "pct"),
    ("Max DD %", "max_dd", "num", "pct"),
    ("Calmar", "calmar", "num", "num"),
    ("Sharpe", "sharpe", "num", "num"),
    ("Profit per capital day", "ppcd", "num", "money"),
    ("Capital days", "capital_days", "num", "num"),
    ("Avg days held", "avg_days", "num", "num"),
    ("Median days held", "median_days", "num", "num"),
    ("P90 days held", "p90_days", "num", "num"),
    ("Losing streak", "losing_streak", "num", "int"),
    ("Pct PnL max symbol", "pct_max_symbol", "num", "pct"),
    ("Pct PnL max trade", "pct_max_trade", "num", "pct"),
    ("Pct PnL max industry", "pct_max_industry", "num", "pct"),
    ("Pct PnL top10", "pct_top10", "num", "pct"),
    ("Pct PnL bottom10", "pct_bottom10", "num", "pct"),
    ("Outlier % of win $", "outlier_win_pct", "num", "pct"),
    ("Trades per year", "trades_per_year", "num", "num"),
]


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


def judge(slices: dict[str, dict[str, dict[str, Any]]]) -> dict[str, str]:
    """IS horse race. OOS can only downgrade a keep to HOLD."""
    is_map = slices.get("IS") or {}
    oos_map = slices.get("OOS") or {}
    full_map = slices.get("FULL") or {}
    ctrl = is_map.get("control") or {}
    if not ctrl or not ctrl.get("n"):
        return {
            "verdict": "NO IS",
            "line": "No in-sample trades (entry before 2024-01-01). Full and out-of-sample are report-only. No keep.",
            "is_best": "n/a",
            "full_best": _best_arm(full_map),
        }
    scored = []
    for arm in ("k40", "k50", "k60"):
        m = is_map.get(arm) or {}
        if not m.get("n"):
            continue
        scored.append(arm)
    if not scored:
        return {
            "verdict": "NO OVERLAY",
            "line": "In-sample overlay could not be scored.",
            "is_best": "n/a",
            "full_best": _best_arm(full_map),
        }

    def better_quality(arm: str) -> bool:
        m = is_map[arm]
        c_ann = ctrl.get("ann_ror")
        a_ann = m.get("ann_ror")
        c_avg = ctrl.get("avg_pnl_pct")
        a_avg = m.get("avg_pnl_pct")
        c_wr = ctrl.get("win_pct")
        a_wr = m.get("win_pct")
        c_pf = ctrl.get("profit_factor")
        a_pf = m.get("profit_factor")
        c_dd = ctrl.get("max_dd")
        a_dd = m.get("max_dd")
        if None in (c_ann, a_ann, c_avg, a_avg, c_wr, a_wr):
            return False
        if a_ann <= c_ann or a_avg <= c_avg:
            return False
        if a_wr < c_wr - 1.0:
            return False
        if c_pf is not None and a_pf is not None and a_pf < c_pf - 1e-9:
            return False
        if c_dd is not None and a_dd is not None and a_dd > c_dd + 2.0:
            return False
        return True

    passers = [a for a in scored if better_quality(a)]
    # Horse race among passers, else among all overlays, by IS Ann ROR.
    pool = passers or scored

    def ann_key(arm: str) -> float:
        v = (is_map.get(arm) or {}).get("ann_ror")
        return float(v) if v is not None and math.isfinite(float(v)) else -1e18

    is_best = max(pool, key=ann_key)
    full_best = _best_arm(full_map)
    c_ann = ctrl.get("ann_ror")
    best_ann = (is_map.get(is_best) or {}).get("ann_ror")
    c_avg = ctrl.get("avg_pnl_pct")
    best_avg = (is_map.get(is_best) or {}).get("avg_pnl_pct")
    flat = (
        c_ann is not None
        and best_ann is not None
        and abs(float(best_ann) - float(c_ann)) < 0.25
        and c_avg is not None
        and best_avg is not None
        and abs(float(best_avg) - float(c_avg)) < 0.05
    )
    if flat:
        verdict = "HOLD"
        why = "In-sample annualized rate of return and average return are flat versus control."
    elif not passers:
        verdict = "DISMISS"
        why = (
            "No keep-fraction beat the control on in-sample quality. "
            "A higher annualized rate of return from much shorter holds does not count when average return is not higher."
        )
    elif passers:
        verdict = "LEAN KEEP"
        why = (
            f"In-sample horse race (selection bias) favors {ARM_LABEL[is_best]}: "
            "annualized rate of return and average return both beat control, win rate did not drop by more than 1 point, "
            "profit factor did not fall, and max drawdown did not worsen by more than 2 points."
        )
    else:
        verdict = "HOLD"
    # OOS soften -> HOLD, do not switch the k.
    oos_c = (oos_map.get("control") or {})
    oos_b = (oos_map.get(is_best) or {})
    if verdict == "LEAN KEEP" and oos_c.get("n") and oos_b.get("n"):
        softened = False
        bits = []
        if (
            oos_c.get("ann_ror") is not None
            and oos_b.get("ann_ror") is not None
            and float(oos_b["ann_ror"]) < float(oos_c["ann_ror"])
        ):
            softened = True
            bits.append("out-of-sample annualized rate of return is below control")
        if (
            oos_c.get("avg_pnl_pct") is not None
            and oos_b.get("avg_pnl_pct") is not None
            and float(oos_b["avg_pnl_pct"]) < float(oos_c["avg_pnl_pct"])
        ):
            softened = True
            bits.append("out-of-sample average return is below control")
        if softened:
            verdict = "HOLD"
            why += " Out-of-sample softened (" + "; ".join(bits) + "). HOLD. The keep fraction was not changed to chase out-of-sample."
        else:
            why += " Out-of-sample did not soften versus control on annualized rate of return or average return. Still research only."
    disagree = ""
    if full_best and is_best and full_best != is_best and full_map.get("control", {}).get("n"):
        disagree = (
            f"Full-book annualized rate of return prefers {ARM_LABEL.get(full_best, full_best)}; "
            f"in-sample prefers {ARM_LABEL.get(is_best, is_best)}."
        )
    return {"verdict": verdict, "line": why, "is_best": is_best, "full_best": full_best or "", "disagree": disagree}


def _best_arm(mmap: dict[str, dict[str, Any]]) -> str:
    best = ""
    best_v = -1e18
    for arm in ARMS:
        v = (mmap.get(arm) or {}).get("ann_ror")
        if v is None:
            continue
        fv = float(v)
        if math.isfinite(fv) and fv > best_v:
            best_v = fv
            best = arm
    return best


def _jsonable(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if isinstance(o, (np.floating, np.integer)):
        o = o.item()
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    return o


def render(results: list[dict[str, Any]]) -> str:
    def main_table(mode: str, title: str) -> str:
        heads = [_th("System", "text")]
        for arm in ARMS:
            lab = ARM_LABEL[arm]
            for bit, typ in (("N", "num"), ("Win rate", "num"), ("Avg return", "num"), ("Ann ROR", "num")):
                heads.append(_th(f"{lab} {bit}", typ))
        body = []
        for res in results:
            sl = res["slices"][mode]
            cells = [f"<td>{html_mod.escape(res['label'])}</td>"]
            for arm in ARMS:
                m = sl[arm]
                cells.append(f"<td>{_fmt_cell(m['n'], 'int')}</td>")
                cells.append(f"<td>{_fmt_cell(m['win_pct'], 'pct')}</td>")
                cells.append(f"<td>{_fmt_cell(m['avg_pnl_pct'], 'pct')}</td>")
                cells.append(f"<td>{_fmt_cell(m['ann_ror'], 'pct')}</td>")
            body.append("<tr>" + "".join(cells) + "</tr>")
        return (
            f"<h2>{html_mod.escape(title)}</h2>\n"
            f"{SWIPE_NOTE_HTML}\n<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>"
            + "".join(heads)
            + "</tr></thead><tbody>"
            + "".join(body)
            + "</tbody></table></div>"
        )

    def canon_table(mode: str) -> str:
        heads = [_th("System", "text"), _th("Metric", "text"), _th("Control", "num")]
        for arm in ("k40", "k50", "k60"):
            heads.append(_th(ARM_LABEL[arm], "num"))
            heads.append(_th(f"Δ {ARM_LABEL[arm]}", "num"))
        body = []
        for res in results:
            sl = res["slices"][mode]
            for label, key, _typ, kind in METRIC_SPEC:
                if is_excluded_html_compare_label(label):
                    continue
                cval = sl["control"].get(key)
                cells = [
                    f"<td>{html_mod.escape(res['short'])}</td>",
                    f"<td>{html_mod.escape(label)}</td>",
                    f"<td>{_fmt_cell(cval, kind)}</td>",
                ]
                for arm in ("k40", "k50", "k60"):
                    aval = sl[arm].get(key)
                    cells.append(f"<td>{_fmt_cell(aval, kind)}</td>")
                    dlt = _delta(aval, cval)
                    if kind == "money" and dlt is not None:
                        shown = format_money(dlt)
                        if dlt > 0:
                            shown = "+" + shown
                        cells.append(f"<td>{html_mod.escape(shown)}</td>")
                    else:
                        cells.append(f"<td>{_fmt_cell(dlt, kind if kind != 'int' else 'num')}</td>")
                body.append("<tr>" + "".join(cells) + "</tr>")
        return (
            f"<h2>Canonical compare — {html_mod.escape(mode)}</h2>\n"
            "<p>Absolute values and the change versus that system's control. "
            "Annualized rate of return uses <code>compare_format.ann_ror_from_closed</code>. "
            "Max drawdown and Sharpe use exit-date equity seeded at $500,000 "
            "(no daily equity curve on the overlay). "
            "Profit concentration is blank when total profit is not positive. "
            "Days underwater, open-position counts, aggressive paths, and Paul / FIT scores "
            "are not recomputed: this test does not rebuild a daily portfolio or a Summary file.</p>\n"
            f"{SWIPE_NOTE_HTML}\n<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>"
            + "".join(heads)
            + "</tr></thead><tbody>"
            + "".join(body)
            + "</tbody></table></div>"
        )

    vheads = "".join(
        [
            _th("System", "text"),
            _th("Verdict", "text"),
            _th("IS pick", "text"),
            _th("Full-book Ann ROR pick", "text"),
            _th("Note", "text"),
        ]
    )
    vbody = []
    for res in results:
        j = res["judge"]
        note = j["line"]
        if j.get("disagree"):
            note += " " + j["disagree"]
        vbody.append(
            "<tr>"
            f"<td>{html_mod.escape(res['short'])}</td>"
            f"<td>{html_mod.escape(j['verdict'])}</td>"
            f"<td>{html_mod.escape(ARM_LABEL.get(j['is_best'], j['is_best']))}</td>"
            f"<td>{html_mod.escape(ARM_LABEL.get(j['full_best'], j['full_best']))}</td>"
            f"<td>{html_mod.escape(note)}</td>"
            "</tr>"
        )

    exit_heads = "".join(
        [_th("System", "text"), _th("Arm", "text"), _th("Slice", "text"), _th("Exit", "text"), _th("N", "num"), _th("% of arm", "num")]
    )
    exit_rows = []
    for res in results:
        for mode in ("FULL", "IS", "OOS"):
            for arm in ARMS:
                mix = res["slices"][mode][arm].get("exit_mix") or {}
                n = res["slices"][mode][arm]["n"] or 0
                for xt, cnt in sorted(mix.items(), key=lambda kv: (-kv[1], kv[0])):
                    pct = (100.0 * cnt / n) if n else None
                    exit_rows.append(
                        "<tr>"
                        f"<td>{html_mod.escape(res['short'])}</td>"
                        f"<td>{html_mod.escape(ARM_LABEL[arm])}</td>"
                        f"<td>{mode}</td>"
                        f"<td>{html_mod.escape(str(xt))}</td>"
                        f"<td>{cnt}</td>"
                        f"<td>{_fmt_cell(pct, 'pct')}</td>"
                        "</tr>"
                    )

    cash_rows = []
    for res in results:
        st = res["stats"]
        cash_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(res['label'])}</td>"
            f"<td>{html_mod.escape(format_money(res['cash']))}</td>"
            f"<td>{html_mod.escape(res['cash_src'])}</td>"
            f"<td>{st.get('kept', 0):,}</td>"
            f"<td>{st.get('short_skipped', 0):,}</td>"
            f"<td>{st.get('missing_ohlc', 0):,}</td>"
            f"<td>{st.get('hit_k40', 0):,}</td>"
            f"<td>{st.get('hit_k50', 0):,}</td>"
            f"<td>{st.get('hit_k60', 0):,}</td>"
            f"<td>{'Research' if res['research'] else 'Live book'}</td>"
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
            _th("40% stop hits", "num"),
            _th("50% stop hits", "num"),
            _th("60% stop hits", "num"),
            _th("Book", "text"),
        ]
    )

    names = ", ".join(html_mod.escape(r["label"]) for r in results)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>High-water stop keep 40/50/60</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 24px; color: #0f172a; line-height: 1.45; }}
h1 {{ font-size: 1.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; border-radius: 10px; padding: 12px 14px; margin: 12px 0; }}
.banner {{ background: #fff7ed; border: 1px solid #fdba74; border-radius: 10px; padding: 12px 14px; margin: 12px 0; }}
code {{ font-size: 0.92em; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>High-water stop: keep 40%, 50%, or 60% of the gain</h1>
<p>Research only. Not gold. Not DailyRun. Out-of-sample is report-only. Picking among 40/50/60 on this same history is in-sample selection.</p>
<div class="callout">
<h2>What you asked</h2>
<p>{html_mod.escape(ASK)}</p>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN)}</p>
</div>
<div class="banner">
<p><strong>Control</strong> is each system's current closed book and the exit that book already used. Entries are not rerun and positions are not resized.</p>
<p><strong>High-water mark</strong> is the highest daily high since the entry fill, from the warehouse daily open-high-low-close in <code>data/ohlcv.duckdb</code> (loaded from <code>data/newdata</code>). It is not a 15-minute high. On the entry day the high can set the mark for the next day, and that same day is not stopped out by its own high.</p>
<p><strong>Keep fraction.</strong> Stop = entry + k × (high-water mark − entry), for k of 0.40, 0.50, and 0.60. The stop checked on day T uses the mark through day T−1 only. If the new stop is not above the system's original stop, the original stop stays (the overlay never loosens risk). Before any prior-day high above the entry, the mark equals the entry and the overlay does not move the stop.</p>
<p><strong>Systems on this page:</strong> {names}. Indicators (IND) is deprecated and was skipped. Most Up / Most Down (MUD) is research, not a live DailyRun sleeve. Short trades were left out because this stop is a long rule. A trade with no daily bars covering the hold was left out of every arm.</p>
<p><strong>What showed up.</strong> On a lot of trades the entry day's high is only a little above the buy. That sets the next day's stop just above the buy price. The next open is often already through that stop, so the overlay sells the next morning for a very small gain and never gets to the original target. Win rate can rise while average return falls. That is the rule as written, including using the entry day's high for the next day only.</p>
<p>In-sample means entry before 2024-01-01. Out-of-sample means entry on or after 2024-01-01. Judge keep or dismiss on in-sample quality (win rate, average return, annualized rate of return, profit factor, drawdown), not on trade count. If out-of-sample softens, the call is HOLD. The keep fraction is not retuned to fix out-of-sample.</p>
<p>The first mention of annualized rate of return is this sentence. After that, Ann ROR is the house formula <code>((1 + total profit / (slot cash × N)) ^ (365 / average days held) − 1) × 100</code> via <code>compare_format.ann_ror_from_closed</code>. Slot cash is the Closed median implied notional (profit dollars divided by percent). Report <code>capacity_brt_cash</code> is cited only when it sits within about 25% of that median. A flat $47,500 sheet slot is not used when the closed book is capacity-sized.</p>
</div>
<h2>Verdicts</h2>
<p>Click column headers to sort. The in-sample pick is an in-sample horse race among control and the three keep fractions.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable"><thead><tr>{vheads}</tr></thead><tbody>
{''.join(vbody)}
</tbody></table></div>
{main_table("FULL", "Full book")}
{main_table("IS", "In-sample (entry before 2024-01-01)")}
{main_table("OOS", "Out-of-sample (entry on or after 2024-01-01) — report only")}
{canon_table("FULL")}
{canon_table("IS")}
{canon_table("OOS")}
<h2>Coverage and slot cash</h2>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable"><thead><tr>{cash_heads}</tr></thead><tbody>
{''.join(cash_rows)}
</tbody></table></div>
<h2>Exit mix</h2>
<p>HWM_GAP is a sell at the open because the open was already through the high-water stop. HWM_STOP is a sell at the stop price because the low tagged it. Other labels are the book's original exit type.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable"><thead><tr>{exit_heads}</tr></thead><tbody>
{''.join(exit_rows)}
</tbody></table></div>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""


def write_baseline(results: list[dict[str, Any]]) -> None:
    lines = [
        "# High-water stop keep 40/50/60 — 2026-10-15",
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
        "- Rocket Launcher (RL) control is that closed book, not the named partial exit strategy (80% at +20%, leftover stop at entry, leftover at +40%).",
        "- Overlay arms k = 0.40, 0.50, 0.60. Stop = entry + k × (high-water mark − entry).",
        "- High-water mark = highest daily high since the fill, warehouse daily bars (`data/ohlcv.duckdb`, source `data/newdata`). Not a 15-minute high.",
        "- No lookahead: day T uses the mark through T−1. Entry-day high sets the next day's mark and does not stop out the entry day.",
        "- Open through the stop fills at the open; else a low through the stop fills at the stop; else the original exit stands.",
        "- New stop is used only when it is strictly above the original stop (never loosen). Stop price ≤ 0 counts as no original stop.",
        "- One position per closed trade. No resize. Same entries.",
        "- In-sample: entry_date < 2024-01-01. Out-of-sample: entry_date >= 2024-01-01. Full book reported too.",
        "- Annualized rate of return: `compare_format.ann_ror_from_closed`, days_per_year 365. Slot cash = Closed median implied notional. Report capacity_brt_cash only when within 25% of that median. No flat $47,500 when the book is capacity-sized.",
        "- Max DD and Sharpe: exit-date equity, seed $500,000 (`DEFAULT_INITIAL_ACCOUNT`). Not a daily mark-to-market curve.",
        "- Horse race among control / 40 / 50 / 60 on the same history is in-sample selection. OOS is report-only.",
        "",
        "## Systems",
        "",
        "Live books: Break and ReTest (BRT), Rocket Launcher (RL), Year High (YH), Magic Touch (MTS), Weekly Pivot Break and Retest (WPBR), Relative Strength vs SPY (RS), StockBee (SB), Volume Zone (VZ), Relative Strength Index (RSI), Weekly Range / Swing (WRL).",
        "",
        "Most Up / Most Down (MUD) is included from `MUD_LatestRun_Closed.csv` already on disk and labeled research.",
        "",
        "Indicators (IND) skipped (deprecated). Other non-live prefixes (CS, KELL, MVCP, PBR, QULL, RSIN) were not in the live set and were not run.",
        "",
        "This overlay is not a Simple Moving Average (SMA) target.",
        "",
        "## Slot cash and coverage",
        "",
    ]
    for res in results:
        st = res["stats"]
        j = res["judge"]
        lines.append(
            f"- **{res['label']}** ({'research' if res['research'] else 'live'}): "
            f"slot {format_money(res['cash'])}. {res['cash_src']}. "
            f"Scored {st.get('kept', 0):,}; shorts left out {st.get('short_skipped', 0):,}; "
            f"no OHLC path {st.get('missing_ohlc', 0):,}; "
            f"stop hits 40/50/60 = {st.get('hit_k40', 0):,}/{st.get('hit_k50', 0):,}/{st.get('hit_k60', 0):,}. "
            f"Stop column `{res['stop_col'] or 'none'}`. Verdict **{j['verdict']}**. {j['line']}"
            + (f" {j.get('disagree')}" if j.get("disagree") else "")
        )
    lines += [
        "",
        "## What showed up",
        "",
        "On many trades the entry day's high is only slightly above the fill. That high sets the next day's stop just above entry. The next open is often already through it, so the overlay sells the next morning for a very small gain and does not reach the original target. Win rate can rise while average return falls. A higher annualized rate of return in that case is the short hold in the house formula, not a better average trade.",
        "",
        "## Not computed",
        "",
        "Days underwater, concurrent position counts, aggressive PnL, and Paul / FIT scores need a daily equity curve or a rebuilt Summary. This page does not invent them. Universe is the closed book (entries unchanged).",
        "",
        "## Promotion",
        "",
        "Research candidate at most. Not gold. Not wired to DailyRun.",
        "",
    ]
    (OUT / "BASELINE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    summary_print = []
    for code, label, research in SYSTEMS:
        path = _DRIVE / f"{code}_LatestRun_Closed.csv"
        print(f"=== {code} ===", flush=True)
        if not path.exists():
            print("  SKIP missing closed book", flush=True)
            summary_print.append(f"{code}\tSKIP\tno closed book")
            continue
        df, meta = load_trades(code)
        # Long-only filter is inside the replay so shorts are counted.
        print(f"  loaded {len(df):,} from {meta['rows_file']:,}", flush=True)
        try:
            cash, cash_src, dollars = slot_cash(df, code)
        except SystemExit as e:
            print(f"  SKIP cash: {e}", flush=True)
            summary_print.append(f"{code}\tSKIP\t{e}")
            continue
        syms = set(df["symbol"].unique().tolist())
        print(f"  ohlc symbols {len(syms):,} cash={cash:,.2f}", flush=True)
        ohlc = load_ohlc(syms)
        print(f"  ohlc hit {len(ohlc):,}", flush=True)
        arms, stats = build_arm_rows(df, ohlc, dollars)
        if stats.get("kept", 0) == 0:
            print("  SKIP no usable trades", flush=True)
            summary_print.append(
                f"{code}\tSKIP\tno usable OHLC path kept={stats.get('kept', 0)} missing={stats.get('missing_ohlc', 0)}"
            )
            continue
        slices: dict[str, dict[str, dict[str, Any]]] = {}
        for mode in ("FULL", "IS", "OOS"):
            slices[mode] = {}
            for arm in ARMS:
                slices[mode][arm] = book_metrics(_slice(arms[arm], mode), cash)
        judged = judge(slices)
        res = {
            "code": code,
            "short": code,
            "label": label,
            "research": research,
            "cash": cash,
            "cash_src": cash_src,
            "stop_col": meta.get("stop_col") or "",
            "stats": stats,
            "slices": slices,
            "judge": judged,
        }
        results.append(res)
        full = slices["FULL"]
        bits = [code]
        for arm in ARMS:
            m = full[arm]
            bits.append(
                f"{arm} N={m['n']} WR={m['win_pct']:.2f} AVG={m['avg_pnl_pct']:.3f} ANN={m['ann_ror']}"
            )
        if judged.get("disagree"):
            bits.append("IS_NOTE " + judged["disagree"])
        else:
            bits.append("IS_NOTE agrees_or_empty")
        bits.append(judged["verdict"])
        line = " | ".join(str(b) for b in bits)
        print("  " + line, flush=True)
        summary_print.append(line)
        # Drop heavy exit mix copies are small; trades are not stored.

    html_path = OUT / "compare.html"
    html_path.write_text(render(results), encoding="utf-8")
    write_baseline(results)
    # Compact metrics for the parent summary.
    slim = []
    for res in results:
        slim.append(
            {
                "code": res["code"],
                "cash": res["cash"],
                "cash_src": res["cash_src"],
                "stats": res["stats"],
                "judge": res["judge"],
                "slices": {
                    mode: {
                        arm: {
                            k: res["slices"][mode][arm].get(k)
                            for k in (
                                "n",
                                "win_pct",
                                "avg_pnl_pct",
                                "ann_ror",
                                "profit_factor",
                                "max_dd",
                                "ann_note",
                            )
                        }
                        for arm in ARMS
                    }
                    for mode in ("FULL", "IS", "OOS")
                },
            }
        )
    (OUT / "summary.json").write_text(json.dumps(_jsonable(slim), indent=2), encoding="utf-8")
    (OUT / "PRINT.txt").write_text("\n".join(summary_print) + "\n", encoding="utf-8")
    print("WROTE", html_path, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
