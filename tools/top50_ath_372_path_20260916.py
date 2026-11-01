#!/usr/bin/env python3
"""First-touch 3.72% ATH-drop paths + cheap overlay (research only).

Same universe / closing-ATH rules as ``top50_ath_drawdown_20260916``.
3.72% is the pause-2+ trading-day median % drop from that stamp.

Not DailyRun. Not gold. Do not commit from this script.
"""
from __future__ import annotations

import html as html_mod
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

import compare_format as cf  # noqa: E402
import run_spx_diversification as spx  # noqa: E402
import top50_ath_drawdown_20260916 as ath  # noqa: E402

STAMP_ID = "top50_ath_372_path_20260916"
STAMP_DIR = REPO / "drive" / "paul_experiments" / STAMP_ID
PRIOR_ID = "top50_ath_drawdown_20260916"
PRIOR_DIR = REPO / "drive" / "paul_experiments" / PRIOR_ID
TREND_AB = "spx_trend_ab_20260916"

DROP_PCT = 3.72
THRESH = DROP_PCT / 100.0
STOP_EXTRA = 0.05
TIME_STOP_CAL = 25
SHEET_CASH = 10_000.0
INITIAL_ACCOUNT = 500_000.0
IS_CUT = pd.Timestamp("2024-01-01")

ORIGINAL_REQUEST = (
    "with this system: ... what kind of moves does a stock make once it drops "
    "3.72% or more? how many go lower? by how much? how many bounce back. how long? "
    "can you brainstorm some ideas on ways we can invest in this succesfully?"
)
LAYMAN = (
    "We used the same mega-cap list as the all-time high (ATH) drawdown ledger: names "
    "that were ever in the annual top 50 by approximate market cap on the Standard & "
    "Poor's 500 (S&P 500). After each closing ATH we wait for the first daily bar "
    "whose Low is at least 3.72% below that ATH close — that is the trigger "
    "(3.72% was the typical pullback on pauses of two or more trading days in the "
    "prior stamp, not a fitted 'best' number). From that first touch we ask: did "
    "price go lower still, and by how much extra? Did the close get back to a new "
    "high, and how many days did that take? We also count a halfway bounce (price "
    "recovers half of the 3.72% drop without needing a new high). Then we paper-trade "
    "one simple idea versus doing nothing: buy at the 3.72% line, sell on a new ATH "
    "close, after 25 calendar days, or if price falls another 5%. In-sample is "
    "triggers before 2024; 2024+ is report-only. Research brainstorm only — not a "
    "live rule and not DailyRun."
)


def _esc(x: Any) -> str:
    return html_mod.escape("" if x is None else str(x))


def _mean(vals: Any) -> float | None:
    arr = np.asarray(list(vals), dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return None
    return float(np.mean(arr))


def _median(vals: Any) -> float | None:
    arr = np.asarray(list(vals), dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return None
    return float(np.median(arr))


def _pctl(vals: Any, q: float) -> float | None:
    arr = np.asarray(list(vals), dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return None
    return float(np.percentile(arr, q))


def _fmt_num(v: Any, digits: int = 2) -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "—"
    try:
        return f"{float(v):,.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_int(v: Any) -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "—"
    try:
        return f"{int(v):,}"
    except (TypeError, ValueError):
        return "—"


def _fmt_pct(v: Any, digits: int = 2) -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "—"
    try:
        return f"{float(v):.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def _th(label: str, sort_type: str) -> str:
    return spx._sortable_th(label, sort_type)


def _rate(num: int, den: int) -> float | None:
    if den <= 0:
        return None
    return 100.0 * float(num) / float(den)


def _load_prior_events() -> pd.DataFrame:
    path = PRIOR_DIR / "all_events.csv"
    if not path.is_file():
        raise RuntimeError(f"Missing prior stamp events: {path}")
    df = pd.read_csv(path)
    df["symbol"] = df["symbol"].astype(str).str.upper()
    return df


def _prep_ohlc(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict]:
    df = frame.dropna(subset=["Close"]).copy()
    close = df["Close"].to_numpy(dtype=float)
    ok = np.isfinite(close) & (close > 0)
    df = df.loc[ok]
    dates = pd.to_datetime(df["Date"]).to_numpy()
    close = df["Close"].to_numpy(dtype=float)
    raw_low = df["Low"].to_numpy(dtype=float)
    raw_high = df["High"].to_numpy(dtype=float)
    low_ok = np.isfinite(raw_low) & (raw_low > 0)
    high_ok = np.isfinite(raw_high) & (raw_high > 0)
    low = np.where(low_ok, raw_low, close)
    high = np.where(high_ok, raw_high, close)
    date_to_i = {pd.Timestamp(d).date(): i for i, d in enumerate(dates)}
    return dates, close, low, high, date_to_i


def _paths_for_symbol(symbol: str, frame: pd.DataFrame, events: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    dates, close, low, high, date_to_i = _prep_ohlc(frame)
    n = len(close)
    if n < 2:
        return [], []
    half_level_frac = THRESH * 0.5
    bounce2 = 1.02
    bounce5 = 1.05
    paths: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []

    for ev in events.to_dict("records"):
        if str(ev.get("status") or "") == "at_sample_ath":
            continue
        try:
            p0 = float(ev["ath_close"])
        except (TypeError, ValueError):
            continue
        if not np.isfinite(p0) or p0 <= 0:
            continue
        ath_key = pd.Timestamp(ev["ath_date"]).date()
        ath_i = date_to_i.get(ath_key)
        if ath_i is None or ath_i >= n - 1:
            continue
        level = p0 * (1.0 - THRESH)
        trigger_i = None
        for j in range(ath_i + 1, n):
            if float(low[j]) <= level:
                trigger_i = j
                break
            if float(close[j]) > p0:
                break
        if trigger_i is None:
            continue

        rec_i = None
        for j in range(trigger_i, n):
            if float(close[j]) > p0:
                rec_i = j
                break
        win_end = rec_i if rec_i is not None else n - 1
        win_low = low[trigger_i : win_end + 1]
        trough_rel = int(np.argmin(win_low))
        trough_i = trigger_i + trough_rel
        trough = float(low[trough_i])
        trigger_low = float(low[trigger_i])
        trigger_close = float(close[trigger_i])
        trigger_high = float(high[trigger_i])
        t_ath = pd.Timestamp(dates[ath_i])
        t_tr = pd.Timestamp(dates[trigger_i])
        t_tr_low = pd.Timestamp(dates[trough_i])

        extra_from_level = max(0.0, (level - trough) / p0 * 100.0)
        same_bar_extra = max(0.0, (level - trigger_low) / p0 * 100.0)
        # Low<=3.72% is the trigger, so trough<=level is almost always true.
        # "Went lower" for Paul = continuation after first touch, or a material
        # wash through the 3.72% line on the trigger bar (>=1% of ATH extra).
        same_bar_through = bool(same_bar_extra >= 1.0)
        went_lower = bool(extra_from_level >= 1.0)

        after = low[trigger_i + 1 : win_end + 1]
        if after.size:
            after_trough = float(np.min(after))
            after_i = trigger_i + 1 + int(np.argmin(after))
            went_lower_after_bar = bool(after_trough < trigger_low - 1e-12)
            extra_after_bar_from_trigger_low = (
                (trigger_low - after_trough) / p0 * 100.0 if went_lower_after_bar else 0.0
            )
            extra_after_bar_from_level = max(0.0, (level - after_trough) / p0 * 100.0)
        else:
            after_trough = None
            after_i = None
            went_lower_after_bar = False
            extra_after_bar_from_trigger_low = 0.0
            extra_after_bar_from_level = 0.0

        recovered = rec_i is not None
        t_rec = pd.Timestamp(dates[rec_i]) if recovered else None
        cal_rec = int((t_rec - t_tr).days) if recovered else None
        td_rec = int(rec_i - trigger_i) if recovered else None

        half_px = p0 * (1.0 - half_level_frac)
        bounce2_px = level * bounce2
        bounce5_px = level * bounce5
        half_i = None
        b2_i = None
        b5_i = None
        mfe_close = float(trigger_close)
        mfe_high = float(trigger_high)
        for j in range(trigger_i, win_end + 1):
            cj = float(close[j])
            hj = float(high[j])
            if cj > mfe_close:
                mfe_close = cj
            if hj > mfe_high:
                mfe_high = hj
            if half_i is None and cj >= half_px:
                half_i = j
            if b2_i is None and cj >= bounce2_px:
                b2_i = j
            if b5_i is None and cj >= bounce5_px:
                b5_i = j

        last_close = float(close[-1])
        path = {
            "symbol": symbol,
            "ath_seq": ev.get("ath_seq"),
            "ath_date": str(t_ath.date()),
            "ath_close": p0,
            "trigger_date": str(t_tr.date()),
            "trigger_low": trigger_low,
            "trigger_close": trigger_close,
            "trigger_level": level,
            "trigger_basis": "Low",
            "cal_days_ath_to_trigger": int((t_tr - t_ath).days),
            "td_days_ath_to_trigger": int(trigger_i - ath_i),
            "same_bar_through": int(same_bar_through),
            "same_bar_extra_pct_of_ath": same_bar_extra,
            "went_lower_vs_372": int(went_lower),
            "went_lower_after_trigger_bar": int(went_lower_after_bar),
            "first_touch_was_trough": int(not went_lower_after_bar),
            "post_trigger_trough": trough,
            "post_trigger_trough_date": str(t_tr_low.date()),
            "extra_drop_from_372_pct_of_ath": extra_from_level if went_lower else 0.0,
            "after_bar_trough": after_trough,
            "extra_after_bar_from_trigger_low_pct_of_ath": extra_after_bar_from_trigger_low,
            "extra_after_bar_from_372_pct_of_ath": extra_after_bar_from_level,
            "eventual_pct_drop_ath_to_trough": (p0 - trough) / p0 * 100.0,
            "recovered_new_ath": int(recovered),
            "still_open": int(not recovered),
            "next_ath_date": str(t_rec.date()) if recovered else "",
            "next_ath_close": float(close[rec_i]) if recovered else None,
            "cal_days_trigger_to_ath": cal_rec,
            "td_days_trigger_to_ath": td_rec,
            "bounce_50pct_retrace": int(half_i is not None),
            "cal_days_trigger_to_50pct": int((pd.Timestamp(dates[half_i]) - t_tr).days) if half_i is not None else None,
            "bounce_plus2_from_trigger": int(b2_i is not None),
            "cal_days_trigger_to_plus2": int((pd.Timestamp(dates[b2_i]) - t_tr).days) if b2_i is not None else None,
            "bounce_plus5_from_trigger": int(b5_i is not None),
            "cal_days_trigger_to_plus5": int((pd.Timestamp(dates[b5_i]) - t_tr).days) if b5_i is not None else None,
            "mfe_close_pct_from_trigger": (mfe_close / level - 1.0) * 100.0,
            "mfe_high_pct_from_trigger": (mfe_high / level - 1.0) * 100.0,
            "last_close": last_close,
            "last_date": str(pd.Timestamp(dates[-1]).date()),
            "status": "recovered" if recovered else "open_unrecovered",
            "n_years_top50": ev.get("n_years_top50"),
            "first_top50_year": ev.get("first_top50_year"),
            "last_top50_year": ev.get("last_top50_year"),
            "years_in_top50": ev.get("years_in_top50"),
        }
        paths.append(path)

        stop_px = level * (1.0 - STOP_EXTRA)
        exit_i = None
        exit_px = None
        exit_type = "OPEN"
        # Conservative same-bar: stop if Low tags extra 5%.
        if trigger_low <= stop_px + 1e-12:
            exit_i = trigger_i
            exit_px = stop_px
            exit_type = "STOP"
        elif trigger_close > p0:
            exit_i = trigger_i
            exit_px = trigger_close
            exit_type = "TARGET"
        else:
            for j in range(trigger_i + 1, n):
                lj = float(low[j])
                cj = float(close[j])
                cal = int((pd.Timestamp(dates[j]) - t_tr).days)
                if lj <= stop_px + 1e-12:
                    exit_i = j
                    exit_px = stop_px
                    exit_type = "STOP"
                    break
                if cj > p0:
                    exit_i = j
                    exit_px = cj
                    exit_type = "TARGET"
                    break
                if cal >= TIME_STOP_CAL:
                    exit_i = j
                    exit_px = cj
                    exit_type = "TIME"
                    break
            if exit_i is None:
                exit_i = n - 1
                exit_px = float(close[-1])
                exit_type = "OPEN"
        pnl_pct = (float(exit_px) / level - 1.0) * 100.0
        t_ex = pd.Timestamp(dates[exit_i])
        trades.append(
            {
                "symbol": symbol,
                "ath_seq": ev.get("ath_seq"),
                "ath_date": str(t_ath.date()),
                "trigger_date": t_tr,
                "exit_date": t_ex,
                "entry": level,
                "exit": float(exit_px),
                "stop": stop_px,
                "target_ath": p0,
                "pnl_pct": pnl_pct,
                "pnl_d": SHEET_CASH * pnl_pct / 100.0,
                "cal_days_held": int((t_ex - t_tr).days),
                "td_days_held": int(exit_i - trigger_i),
                "exit_type": exit_type,
                "closed": int(exit_type != "OPEN"),
                "is_oos": int(t_tr >= IS_CUT),
            }
        )
    return paths, trades


def _stock_summary(paths: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for sym, g in paths.groupby("symbol", sort=True):
        n = int(len(g))
        lower = g[g["went_lower_vs_372"] == 1]
        lower_after = g[g["went_lower_after_trigger_bar"] == 1]
        rec = g[g["recovered_new_ath"] == 1]
        open_u = g[g["still_open"] == 1]
        extra = lower["extra_drop_from_372_pct_of_ath"] if len(lower) else pd.Series(dtype=float)
        rows.append(
            {
                "symbol": sym,
                "n_triggers": n,
                "pct_went_lower_vs_372": _rate(int(len(lower)), n),
                "pct_went_lower_after_bar": _rate(int(len(lower_after)), n),
                "pct_first_touch_was_trough": _rate(int(g["first_touch_was_trough"].sum()), n),
                "pct_same_bar_through": _rate(int(g["same_bar_through"].sum()), n),
                "median_same_bar_extra": _median(g["same_bar_extra_pct_of_ath"]),
                "avg_extra_drop_if_lower": _mean(g["extra_drop_from_372_pct_of_ath"]),
                "median_extra_drop_if_lower": _median(g["extra_drop_from_372_pct_of_ath"]),
                "p90_extra_drop_if_lower": _pctl(g["extra_drop_from_372_pct_of_ath"], 90),
                "avg_extra_drop_all": _mean(g["extra_drop_from_372_pct_of_ath"]),
                "median_extra_drop_all": _median(g["extra_drop_from_372_pct_of_ath"]),
                "pct_recovered_new_ath": _rate(int(len(rec)), n),
                "pct_still_open": _rate(int(len(open_u)), n),
                "avg_cal_days_to_ath": _mean(rec["cal_days_trigger_to_ath"]) if len(rec) else None,
                "median_cal_days_to_ath": _median(rec["cal_days_trigger_to_ath"]) if len(rec) else None,
                "pct_bounce_50pct": _rate(int(g["bounce_50pct_retrace"].sum()), n),
                "median_cal_days_to_50pct": _median(g.loc[g["bounce_50pct_retrace"] == 1, "cal_days_trigger_to_50pct"]),
                "pct_bounce_plus2": _rate(int(g["bounce_plus2_from_trigger"].sum()), n),
                "pct_bounce_plus5": _rate(int(g["bounce_plus5_from_trigger"].sum()), n),
                "n_years_top50": int(pd.to_numeric(g["n_years_top50"], errors="coerce").max() or 0),
                "first_top50_year": int(pd.to_numeric(g["first_top50_year"], errors="coerce").min())
                if pd.to_numeric(g["first_top50_year"], errors="coerce").notna().any()
                else None,
                "last_top50_year": int(pd.to_numeric(g["last_top50_year"], errors="coerce").max())
                if pd.to_numeric(g["last_top50_year"], errors="coerce").notna().any()
                else None,
            }
        )
    return pd.DataFrame(rows)


def _overall(paths: pd.DataFrame) -> dict[str, Any]:
    n = int(len(paths))
    lower = paths[paths["went_lower_vs_372"] == 1]
    lower_after = paths[paths["went_lower_after_trigger_bar"] == 1]
    rec = paths[paths["recovered_new_ath"] == 1]
    open_u = paths[paths["still_open"] == 1]
    extra = lower["extra_drop_from_372_pct_of_ath"] if len(lower) else pd.Series(dtype=float)
    extra_after = lower_after["extra_after_bar_from_trigger_low_pct_of_ath"] if len(lower_after) else pd.Series(dtype=float)
    return {
        "n_triggers": n,
        "n_names": int(paths["symbol"].nunique()) if n else 0,
        "n_went_lower_vs_372": int(len(lower)),
        "pct_went_lower_vs_372": _rate(int(len(lower)), n),
        "n_went_lower_after_bar": int(len(lower_after)),
        "pct_went_lower_after_bar": _rate(int(len(lower_after)), n),
        "n_first_touch_was_trough": int(paths["first_touch_was_trough"].sum()) if n else 0,
        "pct_first_touch_was_trough": _rate(int(paths["first_touch_was_trough"].sum()) if n else 0, n),
        "n_same_bar_through": int(paths["same_bar_through"].sum()) if n else 0,
        "pct_same_bar_through": _rate(int(paths["same_bar_through"].sum()) if n else 0, n),
        "median_same_bar_extra": _median(paths["same_bar_extra_pct_of_ath"]) if n else None,
        "avg_same_bar_extra": _mean(paths["same_bar_extra_pct_of_ath"]) if n else None,
        "p90_same_bar_extra": _pctl(paths["same_bar_extra_pct_of_ath"], 90) if n else None,
        "avg_extra_drop_if_lower": _mean(extra),
        "median_extra_drop_if_lower": _median(extra),
        "p90_extra_drop_if_lower": _pctl(extra, 90),
        "avg_extra_drop_all": _mean(paths["extra_drop_from_372_pct_of_ath"]) if n else None,
        "median_extra_drop_all": _median(paths["extra_drop_from_372_pct_of_ath"]) if n else None,
        "p90_extra_drop_all": _pctl(paths["extra_drop_from_372_pct_of_ath"], 90) if n else None,
        "avg_extra_after_bar_if_lower": _mean(extra_after),
        "median_extra_after_bar_if_lower": _median(extra_after),
        "p90_extra_after_bar_if_lower": _pctl(extra_after, 90),
        "n_recovered_new_ath": int(len(rec)),
        "pct_recovered_new_ath": _rate(int(len(rec)), n),
        "n_still_open": int(len(open_u)),
        "pct_still_open": _rate(int(len(open_u)), n),
        "avg_cal_days_to_ath": _mean(rec["cal_days_trigger_to_ath"]) if len(rec) else None,
        "median_cal_days_to_ath": _median(rec["cal_days_trigger_to_ath"]) if len(rec) else None,
        "p90_cal_days_to_ath": _pctl(rec["cal_days_trigger_to_ath"], 90) if len(rec) else None,
        "avg_td_days_to_ath": _mean(rec["td_days_trigger_to_ath"]) if len(rec) else None,
        "median_td_days_to_ath": _median(rec["td_days_trigger_to_ath"]) if len(rec) else None,
        "pct_bounce_50pct": _rate(int(paths["bounce_50pct_retrace"].sum()) if n else 0, n),
        "median_cal_days_to_50pct": _median(paths.loc[paths["bounce_50pct_retrace"] == 1, "cal_days_trigger_to_50pct"])
        if n
        else None,
        "avg_cal_days_to_50pct": _mean(paths.loc[paths["bounce_50pct_retrace"] == 1, "cal_days_trigger_to_50pct"])
        if n
        else None,
        "pct_bounce_plus2": _rate(int(paths["bounce_plus2_from_trigger"].sum()) if n else 0, n),
        "pct_bounce_plus5": _rate(int(paths["bounce_plus5_from_trigger"].sum()) if n else 0, n),
        "median_mfe_close_from_trigger": _median(paths["mfe_close_pct_from_trigger"]) if n else None,
        "median_cal_days_ath_to_trigger": _median(paths["cal_days_ath_to_trigger"]) if n else None,
    }


def _buckets_extra(paths: pd.DataFrame) -> pd.DataFrame:
    extra = paths["extra_drop_from_372_pct_of_ath"].to_numpy(dtype=float)
    bins = [
        ("<1% extra (shallow)", extra < 1),
        ("1–2% extra", (extra >= 1) & (extra < 2)),
        ("2–5% extra", (extra >= 2) & (extra < 5)),
        ("5–10% extra", (extra >= 5) & (extra < 10)),
        ("10%+ extra", extra >= 10),
    ]
    n = len(extra)
    rows = []
    for lab, mask in bins:
        c = int(np.sum(mask))
        rows.append({"bucket": lab, "n": c, "pct_of_triggers": _rate(c, n)})
    return pd.DataFrame(rows)


def _buckets_recover(paths: pd.DataFrame) -> pd.DataFrame:
    n = int(len(paths))
    rec = paths[paths["recovered_new_ath"] == 1]
    days = rec["cal_days_trigger_to_ath"].to_numpy(dtype=float)
    bins = [
        ("0–5d to new ATH", days <= 5),
        ("6–25d to new ATH", (days > 5) & (days <= 25)),
        ("26–60d to new ATH", (days > 25) & (days <= 60)),
        ("61–180d to new ATH", (days > 60) & (days <= 180)),
        ("181+d to new ATH", days > 180),
    ]
    rows = []
    for lab, mask in bins:
        c = int(np.sum(mask))
        rows.append({"bucket": lab, "n": c, "pct_of_triggers": _rate(c, n)})
    c_open = int((paths["still_open"] == 1).sum())
    rows.append({"bucket": "Still open (no new ATH yet)", "n": c_open, "pct_of_triggers": _rate(c_open, n)})
    return pd.DataFrame(rows)


def _book_metrics(trades: list[dict[str, Any]] | pd.DataFrame, *, label: str, note: str) -> dict[str, Any]:
    if isinstance(trades, pd.DataFrame):
        rows = trades.to_dict("records")
    else:
        rows = list(trades)
    n = len(rows)
    empty = {
        "arm": label,
        "note": note,
        "n_trades": 0,
        "n_wins": 0,
        "n_losses": 0,
        "win_pct": None,
        "avg_pnl_pct": None,
        "avg_pnl_pct_wo_max": None,
        "expectancy_pct": None,
        "expectancy_d": None,
        "avg_win_pct": None,
        "avg_loss_pct": None,
        "win_loss_count_ratio": None,
        "profit_factor": None,
        "ann_ror": None,
        "max_dd": None,
        "calmar": None,
        "sharpe": None,
        "sharpe_source": "",
        "profit_per_capital_day": None,
        "capital_days": 0.0,
        "avg_days_held": None,
        "median_days_held": None,
        "p90_days_held": None,
        "n_target": 0,
        "n_stop": 0,
        "n_time": 0,
        "n_open": 0,
        "pct_target": None,
        "pct_stop": None,
        "pct_time": None,
        "pct_open": None,
        "overlay_note": "no trades",
    }
    if n <= 0:
        return empty
    pnls = [float(t["pnl_pct"]) for t in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    days = [float(t["cal_days_held"]) for t in rows]
    dollars = [float(t["pnl_d"]) for t in rows]
    n_w, n_l = len(wins), len(losses)
    wo = None
    if len(pnls) >= 2:
        i_max = int(np.argmax(pnls))
        rest = [p for i, p in enumerate(pnls) if i != i_max]
        wo = float(np.mean(rest)) if rest else None
    elif pnls:
        wo = float(pnls[0])
    sum_w = float(sum(wins)) if wins else 0.0
    sum_l = float(sum(losses)) if losses else 0.0
    pf = (sum_w / abs(sum_l)) if abs(sum_l) > 1e-12 else None
    cap_days = float(sum(max(d, 0.0) for d in days))
    total_d = float(sum(dollars))
    exits = [str(t.get("exit_type") or "") for t in rows]
    n_target = exits.count("TARGET")
    n_stop = exits.count("STOP")
    n_time = exits.count("TIME")
    n_open = exits.count("OPEN")
    dated = []
    for t in rows:
        td = t.get("exit_date")
        if td is None or pd.isna(td):
            continue
        dated.append(
            {
                "pnl_d": t["pnl_d"],
                "pnl_pct": t["pnl_pct"],
                "days": t["cal_days_held"],
                "closed": pd.Timestamp(td),
                "opened": pd.Timestamp(t["trigger_date"]),
            }
        )
    ov = cf.overlay_ann_ror_max_dd(
        dated,
        cash=SHEET_CASH,
        initial_account=INITIAL_ACCOUNT,
        pnl_d_key="pnl_d",
        days_key="days",
        closed_key="closed",
        opened_key="opened",
        pnl_pct_key="pnl_pct",
    )
    return {
        "arm": label,
        "note": note,
        "n_trades": n,
        "n_wins": n_w,
        "n_losses": n_l,
        "win_pct": _rate(n_w, n),
        "avg_pnl_pct": _mean(pnls),
        "avg_pnl_pct_wo_max": wo,
        "expectancy_pct": _mean(pnls),
        "expectancy_d": _mean(dollars),
        "avg_win_pct": _mean(wins),
        "avg_loss_pct": _mean(losses),
        "win_loss_count_ratio": (float(n_w) / float(n_l)) if n_l else None,
        "profit_factor": pf,
        "ann_ror": ov.get("ann_ror"),
        "max_dd": ov.get("max_dd"),
        "calmar": ov.get("calmar"),
        "sharpe": ov.get("sharpe"),
        "sharpe_source": ov.get("sharpe_source") or "",
        "profit_per_capital_day": (total_d / cap_days) if cap_days > 0 else None,
        "capital_days": cap_days,
        "avg_days_held": _mean(days),
        "median_days_held": _median(days),
        "p90_days_held": _pctl(days, 90),
        "n_target": n_target,
        "n_stop": n_stop,
        "n_time": n_time,
        "n_open": n_open,
        "pct_target": _rate(n_target, n),
        "pct_stop": _rate(n_stop, n),
        "pct_time": _rate(n_time, n),
        "pct_open": _rate(n_open, n),
        "overlay_note": ov.get("note") or "",
    }


def _eventual_compare(prior: pd.DataFrame) -> dict[str, Any]:
    sub = prior.copy()
    sub["pct_drop"] = pd.to_numeric(sub["pct_drop"], errors="coerce")
    hit = sub[sub["pct_drop"] >= DROP_PCT]
    rec = hit[hit["status"] == "recovered"]
    extra = hit["pct_drop"] - DROP_PCT
    return {
        "n_eventual_ge_372": int(len(hit)),
        "pct_of_all_aths": _rate(int(len(hit)), int(len(sub))),
        "n_recovered": int(len(rec)),
        "pct_recovered": _rate(int(len(rec)), int(len(hit))),
        "n_open": int((hit["status"] == "open_unrecovered").sum()),
        "median_eventual_drop": _median(hit["pct_drop"]),
        "median_extra_vs_372": _median(extra),
        "avg_extra_vs_372": _mean(extra),
        "median_cal_low_to_high": _median(rec["cal_days_low_to_new_high"]) if len(rec) else None,
        "note": (
            "Eventual-trough slice: every ATH whose lowest Low was eventually ≥3.72% down. "
            "This overstates 'already 3.72%' because recovery days are counted from the trough, "
            "not from the first touch. First-touch rows are the path study."
        ),
    }


def _write_baseline(
    path: Path,
    *,
    ov: dict[str, Any],
    ev: dict[str, Any],
    books: pd.DataFrame,
    ohlc_start: str,
    ohlc_end: str,
    n_names: int,
    n_aths: int,
) -> None:
    is_row = books[books["arm"] == "overlay_IS"].iloc[0].to_dict() if len(books[books["arm"] == "overlay_IS"]) else {}
    oos_row = books[books["arm"] == "overlay_OOS"].iloc[0].to_dict() if len(books[books["arm"] == "overlay_OOS"]) else {}
    full_row = books[books["arm"] == "overlay_FULL"].iloc[0].to_dict() if len(books[books["arm"] == "overlay_FULL"]) else {}
    path.write_text(
        f"""# BASELINE — {STAMP_ID}

**Status:** Research path study + one cheap overlay. **Not gold. Not DailyRun.** No adopt.

## What you asked

> {ORIGINAL_REQUEST}

## In plain English

{LAYMAN}

## Freeze (do not silently mutate)

- **Parent stamp:** `{PRIOR_ID}` (same ever-top-50 universe, closing sample ATH, trough = lowest Low after the high).
- **Universe:** names ever in the annual approx-mcap top 50 on today's Wikipedia S&P 500 ∩ local DuckDB, years 2011–2026. Survivorship + scaled-now mcaps inherited.
- **ATH:** new **closing** high in the local sample (usually 2010-01-04 or IPO). Not a 52-week high.
- **3.72%:** drop from the ATH **close**. Taken from the parent stamp's `pause_2plus_td` median % drop (~3.716%), rounded. **Not retuned.**
- **Trigger (first-touch):** first bar **after** the ATH bar whose daily **Low** satisfies `(ATH_close − Low) / ATH_close ≥ 3.72%`. Labeled `trigger_basis=Low`. Close-based first-touch is not the headline.
- **Went lower vs 3.72%:** eventual pullback trough (min Low from trigger through next ATH or last bar) is below the 3.72% level. Extra % = `(3.72%_level − trough) / ATH_close × 100`.
- **Went lower after trigger bar:** a later bar prints a Low below the trigger bar's Low (continuation after first touch).
- **Bounce to new ATH:** first later **close** that exceeds the ATH close. Days = calendar days from trigger date. If never: **open**.
- **50% retrace:** first close back to halfway from the 3.72% level to the ATH (1.86% off the ATH close). Does not require a new high.
- **+2% / +5% bounce:** first close ≥ 2% / 5% above the 3.72% trigger level (may or may not be a new ATH).
- **OHLC window:** {ohlc_start} → {ohlc_end}.
- **IS / OOS (overlay only):** IS = `trigger_date < 2024-01-01`; OOS = `trigger_date ≥ 2024-01-01` (report-only; do not retune).
- **Overlay (one cheap paper trade, vs no-trade):** buy limit at the 3.72% level on the trigger bar; stop at extra 5% below that level (8.72% below ATH close); target = close > ATH; time-stop = 25 calendar days (parent 5%+ median recover-from-low was 25d). Same-bar Low through the stop = STOP first (conservative). Costs = 0. Sheet notional ${SHEET_CASH:,.0f}/trade; Max DD / Sharpe seed ${INITIAL_ACCOUNT:,.0f}.
- **Not DailyRun. Not gold.** Each invest idea is a **hypothesis**, not KEEP.

## Counts

- Names with at least one 3.72% trigger: **{n_names}**
- Parent closing ATH events scanned: **{n_aths}**
- First-touch 3.72% triggers: **{ov.get("n_triggers")}**
- Eventual-trough ≥3.72% rows (overstates first-touch timing): **{ev.get("n_eventual_ge_372")}**

## Headline (first-touch, event-equal)

- Went lower after the trigger bar: {ov.get("pct_went_lower_after_bar")} (first-touch was the trough {ov.get("pct_first_touch_was_trough")})
- Extra drop from 3.72% line to eventual trough (avg / median / p90): {ov.get("avg_extra_drop_all")} / {ov.get("median_extra_drop_all")} / {ov.get("p90_extra_drop_all")}
- Material extra ≥1% of ATH: {ov.get("pct_went_lower_vs_372")}; same-bar wash ≥1%: {ov.get("pct_same_bar_through")}
- Recovered to new ATH: {ov.get("pct_recovered_new_ath")}; still open {ov.get("pct_still_open")}
- Days trigger → new ATH (recovered only, avg / median): {ov.get("avg_cal_days_to_ath")} / {ov.get("median_cal_days_to_ath")}

## Overlay vs no-trade (research only)

Control = no-trade (cash). Candidate = the frozen overlay. Judge quality, not count. OOS report-only.

- FULL: N={full_row.get("n_trades")} WR={full_row.get("win_pct")} AvgPnL%={full_row.get("avg_pnl_pct")} AnnROR={full_row.get("ann_ror")} MaxDD={full_row.get("max_dd")}
- IS: N={is_row.get("n_trades")} WR={is_row.get("win_pct")} AvgPnL%={is_row.get("avg_pnl_pct")} AnnROR={is_row.get("ann_ror")} MaxDD={is_row.get("max_dd")}
- OOS: N={oos_row.get("n_trades")} WR={oos_row.get("win_pct")} AvgPnL%={oos_row.get("avg_pnl_pct")} AnnROR={oos_row.get("ann_ror")} MaxDD={oos_row.get("max_dd")}

## Honesty / selection

- Choosing 3.72% from the parent pause median is descriptive, not a search. Do not grid other cutoffs on this stamp.
- First-touch Low fill at exactly 3.72% is optimistic when the trigger bar gaps through (see `same_bar_through`).
- Same-bar stop-first is conservative; real fills can be worse on gaps.
- Overlay is one frozen recipe, not a winner after a horse-race. Selection bias if you pick another exit after seeing the table.
- Prior weekly-support overlays on the S&P mega-cap hold book (`{TREND_AB}`) were **HOLD** — do not treat "skip if weekly support broken" as a KEEP.
- OOS softens → HOLD, do not retune 3.72 / 5% / 25d on 2024+.
- Survivorship; sample ATH from 2010; dividends ignored.

## Verdict

**Research only.** Path facts + hypotheses. **Not KEEP. Not DailyRun.**
""",
        encoding="utf-8",
    )


def _write_hypothesis(path: Path) -> None:
    path.write_text(
        f"""# HYPOTHESIS — {STAMP_ID}

Research brainstorm. **None of these is KEEP.** Not DailyRun.

| Field | Fill |
|-------|------|
| System / prefix | Top-50 closing-ATH path (parent `{PRIOR_ID}`) |
| Evidence | Parent pause-2+ td median drop ≈ 3.72%; parent 5%+ median low→new-high = 25 calendar days; `{TREND_AB}` weekly-support overlays HOLD |
| Overlay run here | Buy 3.72% first-touch; stop extra 5%; target new ATH close; time-stop 25d vs no-trade |
| Frozen | Universe + ATH + Low first-touch + 3.72 / 5 / 25 |
| IS / OOS | trigger_date < 2024-01-01 / ≥ 2024-01-01 (OOS report-only) |

## Ideas (each a hypothesis)

1. **H1 — Buy the 3.72% dip, 1R under the post-trigger trough / extra 5%.** Mega-caps often pause a few percent after a high. A hard stop under the extra-5% line (or under the realized post-trigger trough once it prints) is the cheap test already run on this stamp.
2. **H2 — Do not buy first touch; wait for a higher low after 3.72%.** If a large share keep falling after the trigger bar, first-touch is early. A later higher low is a second, untested entry knob.
3. **H3 — Time-stop if not back to the ATH in 25 days.** Parent 5%+ pullbacks had a 25-day median from trough to new high. This overlay already uses 25d from the *trigger* (earlier than the trough). A 25d-from-trough variant is a different knob.
4. **H4 — Scale in.** Third at 3.72%, third at extra ~2%, third at extra ~5%. Cuts gap-through pain; needs its own AB (not run here).
5. **H5 — Skip if weekly support is broken / falling.** Link `{TREND_AB}` (HOLD on the equal-weight mega-cap book). Do not assume it helps this dip-buy.

Judge quality (win%, AvgR / Avg PnL%, expectancy, DD, Calmar, Sharpe) not trade count. OOS report-only.
""",
        encoding="utf-8",
    )


def _table(df: pd.DataFrame, cols: list[tuple[str, str, str]], *, row_class: str | None = None) -> str:
    if df is None or df.empty:
        return '<p class="small muted">None.</p>'
    head = "".join(_th(lab, typ) for lab, typ, _ in cols)
    body = []
    for _, r in df.iterrows():
        cls = f' class="{row_class}"' if row_class else ""
        tds = []
        for _lab, typ, key in cols:
            v = r.get(key)
            if typ == "num" and (
                key.startswith("pct_")
                or key.endswith("_pct")
                or "pct" in key
                or key in ("win_pct", "ann_ror", "max_dd", "calmar", "sharpe", "profit_factor")
            ):
                tds.append(f"<td>{_fmt_pct(v) if 'ratio' not in key and key not in ('calmar', 'sharpe', 'profit_factor', 'win_loss_count_ratio') else _fmt_num(v, 2)}</td>")
            elif typ == "num" and key in ("expectancy_d", "profit_per_capital_day"):
                tds.append(f"<td>{cf.format_money(v)}</td>")
            elif typ == "num" and key in ("n_triggers", "n", "n_trades", "n_wins", "n_losses", "n_target", "n_stop", "n_time", "n_open", "n_years_top50", "n_names"):
                tds.append(f"<td>{_fmt_int(v)}</td>")
            elif typ == "num":
                tds.append(f"<td>{_fmt_num(v, 1 if 'days' in key or key == 'capital_days' else 2)}</td>")
            else:
                tds.append(f"<td>{_esc(v)}</td>")
        body.append(f"<tr{cls}>" + "".join(tds) + "</tr>")
    return (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def _write_html(
    path: Path,
    *,
    ov: dict[str, Any],
    ev: dict[str, Any],
    stocks: pd.DataFrame,
    paths: pd.DataFrame,
    extra_b: pd.DataFrame,
    rec_b: pd.DataFrame,
    books: pd.DataFrame,
    ohlc_start: str,
    ohlc_end: str,
) -> None:
    cards = [
        ("N first-touch triggers", _fmt_int(ov.get("n_triggers")), f"{_fmt_int(ov.get('n_names'))} names · Low pierce of 3.72% off ATH close"),
        ("% went lower after first-touch bar", _fmt_pct(ov.get("pct_went_lower_after_bar")), f"Later Low under the trigger Low · first-touch was the trough {_fmt_pct(ov.get('pct_first_touch_was_trough'))}"),
        ("Extra drop from 3.72% (med / avg / p90)", f"{_fmt_pct(ov.get('median_extra_drop_all'))} / {_fmt_pct(ov.get('avg_extra_drop_all'))} / {_fmt_pct(ov.get('p90_extra_drop_all'))}", "Added %-of-ATH from the 3.72% line to the eventual trough"),
        ("% material extra ≥1% / same-bar wash ≥1%", f"{_fmt_pct(ov.get('pct_went_lower_vs_372'))} / {_fmt_pct(ov.get('pct_same_bar_through'))}", f"Trigger-bar extra median {_fmt_pct(ov.get('median_same_bar_extra'))}"),
        ("% back to new ATH", _fmt_pct(ov.get("pct_recovered_new_ath")), f"Still open {_fmt_pct(ov.get('pct_still_open'))}"),
        ("Days trigger → new ATH (med / avg)", f"{_fmt_num(ov.get('median_cal_days_to_ath'), 1)} / {_fmt_num(ov.get('avg_cal_days_to_ath'), 1)}", "Recovered events only · calendar days"),
        ("% halfway bounce (50% retrace)", _fmt_pct(ov.get("pct_bounce_50pct")), f"Median days {_fmt_num(ov.get('median_cal_days_to_50pct'), 1)}"),
        ("% +2% from trigger / +5%", f"{_fmt_pct(ov.get('pct_bounce_plus2'))} / {_fmt_pct(ov.get('pct_bounce_plus5'))}", "Close ≥2% or ≥5% above the 3.72% level"),
    ]
    card_html = "".join(
        f'<div class="card"><h3>{_esc(t)}</h3><div class="metric">{m}</div><div class="small">{_esc(n)}</div></div>'
        for t, m, n in cards
    )

    book_cols = [
        ("Arm", "text", "arm"),
        ("N trades", "num", "n_trades"),
        ("Wins", "num", "n_wins"),
        ("Losses", "num", "n_losses"),
        ("Win %", "num", "win_pct"),
        ("Avg PnL %", "num", "avg_pnl_pct"),
        ("AVG_PNL_PCT_WO_MAX", "num", "avg_pnl_pct_wo_max"),
        ("Expectancy %", "num", "expectancy_pct"),
        ("Expectancy $", "num", "expectancy_d"),
        ("Avg win %", "num", "avg_win_pct"),
        ("Avg loss %", "num", "avg_loss_pct"),
        ("W/L count", "num", "win_loss_count_ratio"),
        ("Profit factor", "num", "profit_factor"),
        ("Ann ROR %", "num", "ann_ror"),
        ("Max DD %", "num", "max_dd"),
        ("Calmar", "num", "calmar"),
        ("Sharpe", "num", "sharpe"),
        ("Profit / capital day", "num", "profit_per_capital_day"),
        ("Capital days", "num", "capital_days"),
        ("Avg days held", "num", "avg_days_held"),
        ("Med days held", "num", "median_days_held"),
        ("P90 days held", "num", "p90_days_held"),
        ("N TARGET", "num", "n_target"),
        ("% TARGET", "num", "pct_target"),
        ("N STOP", "num", "n_stop"),
        ("% STOP", "num", "pct_stop"),
        ("N TIME", "num", "n_time"),
        ("% TIME", "num", "pct_time"),
        ("N OPEN", "num", "n_open"),
        ("% OPEN", "num", "pct_open"),
        ("Note", "text", "note"),
    ]
    stock_cols = [
        ("Symbol", "text", "symbol"),
        ("N triggers", "num", "n_triggers"),
        ("% extra ≥1% of ATH", "num", "pct_went_lower_vs_372"),
        ("% lower after bar", "num", "pct_went_lower_after_bar"),
        ("% first-touch was trough", "num", "pct_first_touch_was_trough"),
        ("% same-bar wash ≥1%", "num", "pct_same_bar_through"),
        ("Med same-bar extra", "num", "median_same_bar_extra"),
        ("Avg extra from 3.72%", "num", "avg_extra_drop_if_lower"),
        ("Med extra from 3.72%", "num", "median_extra_drop_if_lower"),
        ("P90 extra from 3.72%", "num", "p90_extra_drop_if_lower"),
        ("% new ATH", "num", "pct_recovered_new_ath"),
        ("% still open", "num", "pct_still_open"),
        ("Avg d to ATH", "num", "avg_cal_days_to_ath"),
        ("Med d to ATH", "num", "median_cal_days_to_ath"),
        ("% 50% retrace", "num", "pct_bounce_50pct"),
        ("Med d to 50%", "num", "median_cal_days_to_50pct"),
        ("% +2% from trigger", "num", "pct_bounce_plus2"),
        ("% +5% from trigger", "num", "pct_bounce_plus5"),
        ("Years in top 50", "num", "n_years_top50"),
        ("First top-50 year", "num", "first_top50_year"),
        ("Last top-50 year", "num", "last_top50_year"),
    ]
    extra_cols = [("Extra-drop bucket", "text", "bucket"), ("N", "num", "n"), ("% of triggers", "num", "pct_of_triggers")]
    rec_cols = [("Recovery bucket", "text", "bucket"), ("N", "num", "n"), ("% of triggers", "num", "pct_of_triggers")]

    overall_stock = {
        "symbol": "OVERALL (event-equal)",
        "n_triggers": ov.get("n_triggers"),
        "pct_went_lower_vs_372": ov.get("pct_went_lower_vs_372"),
        "pct_went_lower_after_bar": ov.get("pct_went_lower_after_bar"),
        "pct_first_touch_was_trough": ov.get("pct_first_touch_was_trough"),
        "pct_same_bar_through": ov.get("pct_same_bar_through"),
        "median_same_bar_extra": ov.get("median_same_bar_extra"),
        "avg_extra_drop_if_lower": ov.get("avg_extra_drop_all"),
        "median_extra_drop_if_lower": ov.get("median_extra_drop_all"),
        "p90_extra_drop_if_lower": ov.get("p90_extra_drop_all"),
        "pct_recovered_new_ath": ov.get("pct_recovered_new_ath"),
        "pct_still_open": ov.get("pct_still_open"),
        "avg_cal_days_to_ath": ov.get("avg_cal_days_to_ath"),
        "median_cal_days_to_ath": ov.get("median_cal_days_to_ath"),
        "pct_bounce_50pct": ov.get("pct_bounce_50pct"),
        "median_cal_days_to_50pct": ov.get("median_cal_days_to_50pct"),
        "pct_bounce_plus2": ov.get("pct_bounce_plus2"),
        "pct_bounce_plus5": ov.get("pct_bounce_plus5"),
        "n_years_top50": None,
        "first_top50_year": None,
        "last_top50_year": None,
    }
    stocks_show = pd.concat([pd.DataFrame([overall_stock]), stocks.sort_values("symbol")], ignore_index=True)

    stock_head = "".join(_th(a, b) for a, b, _ in stock_cols)
    stock_body = []
    for i, r in stocks_show.iterrows():
        cls = ' class="total-row"' if r["symbol"] == "OVERALL (event-equal)" else ""
        tds = []
        for _lab, typ, key in stock_cols:
            v = r.get(key)
            if key == "symbol":
                if r["symbol"] == "OVERALL (event-equal)":
                    tds.append("<td><strong>OVERALL (event-equal)</strong></td>")
                else:
                    tds.append(f'<td><a class="sym" href="#triggers" data-filter="{_esc(v)}">{_esc(v)}</a></td>')
            elif typ == "num" and ("pct" in key or "extra" in key):
                tds.append(f"<td>{_fmt_pct(v)}</td>")
            elif typ == "num" and key in ("n_triggers", "n_years_top50", "first_top50_year", "last_top50_year"):
                tds.append(f"<td>{_fmt_int(v)}</td>")
            elif typ == "num":
                tds.append(f"<td>{_fmt_num(v, 1)}</td>")
            else:
                tds.append(f"<td>{_esc(v)}</td>")
        stock_body.append(f"<tr{cls}>" + "".join(tds) + "</tr>")

    ev_head = "".join(
        [
            _th("Symbol", "text"),
            _th("ATH #", "num"),
            _th("ATH date", "date"),
            _th("Trigger date", "date"),
            _th("ATH close", "num"),
            _th("Trigger level", "num"),
            _th("Trigger low", "num"),
            _th("Through same bar", "text"),
            _th("Went lower vs 3.72%", "text"),
            _th("Lower after bar", "text"),
            _th("Extra % vs 3.72%", "num"),
            _th("Extra after bar %", "num"),
            _th("Eventual % drop", "num"),
            _th("New ATH?", "text"),
            _th("New ATH date", "date"),
            _th("Cal d trigger→ATH", "num"),
            _th("50% retrace", "text"),
            _th("Cal d to 50%", "num"),
            _th("+2% from trigger", "text"),
            _th("+5% from trigger", "text"),
            _th("Status", "text"),
        ]
    )
    ev_body = []
    show = paths.sort_values(["symbol", "ath_seq"])
    for _, e in show.iterrows():
        cls = "open" if int(e.get("still_open") or 0) else ""
        ev_body.append(
            f'<tr class="{cls}" data-sym="{_esc(e["symbol"])}" data-open="{int(e.get("still_open") or 0)}" '
            f'data-lower="{int(e.get("went_lower_vs_372") or 0)}">'
            f"<td>{_esc(e['symbol'])}</td>"
            f"<td>{_fmt_int(e['ath_seq'])}</td>"
            f"<td>{_esc(e['ath_date'])}</td>"
            f"<td>{_esc(e['trigger_date'])}</td>"
            f"<td>{_fmt_num(e['ath_close'], 2)}</td>"
            f"<td>{_fmt_num(e['trigger_level'], 2)}</td>"
            f"<td>{_fmt_num(e['trigger_low'], 2)}</td>"
            f"<td>{'Y' if int(e.get('same_bar_through') or 0) else 'N'}</td>"
            f"<td>{'Y' if int(e.get('went_lower_vs_372') or 0) else 'N'}</td>"
            f"<td>{'Y' if int(e.get('went_lower_after_trigger_bar') or 0) else 'N'}</td>"
            f"<td>{_fmt_pct(e['extra_drop_from_372_pct_of_ath'])}</td>"
            f"<td>{_fmt_pct(e['extra_after_bar_from_trigger_low_pct_of_ath'])}</td>"
            f"<td>{_fmt_pct(e['eventual_pct_drop_ath_to_trough'])}</td>"
            f"<td>{'Y' if int(e.get('recovered_new_ath') or 0) else 'N'}</td>"
            f"<td>{_esc(e['next_ath_date'])}</td>"
            f"<td>{_fmt_num(e['cal_days_trigger_to_ath'], 0)}</td>"
            f"<td>{'Y' if int(e.get('bounce_50pct_retrace') or 0) else 'N'}</td>"
            f"<td>{_fmt_num(e['cal_days_trigger_to_50pct'], 0)}</td>"
            f"<td>{'Y' if int(e.get('bounce_plus2_from_trigger') or 0) else 'N'}</td>"
            f"<td>{'Y' if int(e.get('bounce_plus5_from_trigger') or 0) else 'N'}</td>"
            f"<td>{_esc(e['status'])}</td>"
            "</tr>"
        )

    h1 = (
        "Buy the 3.72% first-touch in these mega-caps with a hard stop another 5% under the trigger "
        "(or, once printed, under the post-trigger trough / 1R). The overlay on this page is that recipe "
        "versus doing nothing. Hypothesis only — look at IS quality and whether OOS softened."
    )
    h2 = (
        "Do not buy the first 3.72% print. Wait for a later higher low after the trigger bar, then buy "
        f"that higher low. About {_fmt_pct(ov.get('pct_went_lower_after_bar'))} of triggers made a new low "
        "after the first-touch bar — first-touch can be early. Untested entry knob."
    )
    h3 = (
        "Keep a time-stop if the close is not back to a new ATH in about 25 days (the parent stamp's "
        "median recover-from-low on 5%+ pullbacks). This overlay already time-stops at 25d from the "
        f"trigger; recovered-to-ATH median here is {_fmt_num(ov.get('median_cal_days_to_ath'), 1)} days. "
        "A 25d-from-trough variant is a different test. Hypothesis only."
    )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>3.72% ATH first-touch paths — {STAMP_ID}</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 24px; color: #0f172a; background: #f8fafc; }}
h1 {{ font-size: 1.45rem; margin: 0 0 4px; }}
h2 {{ font-size: 1.15rem; margin: 1.6rem 0 .5rem; border-bottom: 1px solid #cbd5e1; padding-bottom: .25rem; }}
.sub, .meta {{ color: #475569; font-size: .92rem; max-width: 74rem; line-height: 1.5; }}
.callout {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .85rem 1rem; margin: .75rem 0; max-width: 74rem; }}
.idea {{ background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: .85rem 1rem; margin: .6rem 0; max-width: 74rem; }}
.idea h3 {{ margin: 0 0 .35rem; font-size: 1rem; }}
.tag {{ display: inline-block; background: #92400e; color: #fff; font-size: 11px; padding: 1px 6px; border-radius: 999px; margin-right: 6px; }}
.cards {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0 24px; }}
.card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px 16px; min-width: 200px; flex: 1 1 210px; }}
.card h3 {{ margin: 0 0 8px; font-size: 13px; color: #475569; }}
.metric {{ font-size: 1.25rem; font-weight: 700; line-height: 1.25; }}
.small {{ font-size: 12px; color: #64748b; }}
.muted {{ color: #94a3b8; }}
.table-wrap {{ overflow-x: auto; margin: 8px 0; }}
table.sortable {{ border-collapse: collapse; background: #fff; font-size: 12px; width: 100%; }}
table.sortable th, table.sortable td {{ border: 1px solid #e2e8f0; padding: 6px 8px; text-align: left; vertical-align: top; }}
table.sortable th {{ background: #f1f5f9; }}
tr.open td {{ background: #fff7ed; }}
tr.total-row td {{ background: #e0f2fe; font-weight: 600; }}
a.sym {{ color: #1d4ed8; text-decoration: none; font-weight: 600; }}
a.sym:hover {{ text-decoration: underline; }}
input.filter {{ padding: 6px 10px; border: 1px solid #cbd5e1; border-radius: 6px; min-width: 220px; }}
{spx.SORTABLE_TH_CSS}
</style></head><body>
<h1>Once a top-50 name drops 3.72% from a closing ATH — 2026-09-16</h1>
<p class="sub">Research path study. Not gold. Not DailyRun. Stamp <code>{STAMP_ID}</code>.
Parent <code>{PRIOR_ID}</code>. OHLC {_esc(ohlc_start)} → {_esc(ohlc_end)}.
Trigger = first daily <em>Low</em> ≥3.72% below the ATH close. Click column headers to sort.</p>
<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
<p>{_esc(ORIGINAL_REQUEST)}</p>
<h2>In plain English</h2>
<p>{_esc(LAYMAN)}</p>
</div>
<div class="cards">{card_html}</div>

<h2>What “go lower” and “bounce” mean</h2>
<ul class="meta">
<li><strong>Trigger</strong> — first bar after the all-time high (ATH) close whose Low is 3.72% or more below that close. Not a close-based trigger.</li>
<li><strong>Went lower after the trigger bar</strong> — a later session made a new Low under the first-touch bar. This is the headline “how many go lower” after you could have bought the 3.72% line. If no later lower Low, the first-touch bar <em>was</em> the trough.</li>
<li><strong>Extra drop</strong> — how much further the eventual trough sits below the 3.72% line, as a percent of the ATH close (all triggers).</li>
<li><strong>Material extra / same-bar wash</strong> — eventual extra ≥1% of ATH, or the trigger bar itself already ran ≥1% of ATH through the 3.72% line. A limit at 3.72% may not fill cleanly on a wash.</li>
<li><strong>Bounce to new ATH</strong> — a later close beats the old ATH close. Open = has not happened yet in this sample.</li>
<li><strong>50% retrace / +2% / +5%</strong> — bounce toward the high without requiring a new ATH.</li>
</ul>

<h2>How much further after 3.72%</h2>
<p class="small">Extra drop is %-of-ATH below the 3.72% level (not %-of-the-trigger-price). Click headers to sort.</p>
{_table(extra_b, extra_cols)}
<p class="small">All first-touch triggers: median extra {_fmt_pct(ov.get("median_extra_drop_all"))},
average {_fmt_pct(ov.get("avg_extra_drop_all"))}, 90th percentile {_fmt_pct(ov.get("p90_extra_drop_all"))}
below the 3.72% line (eventual trough).
After the trigger bar (true continuation): {_fmt_pct(ov.get("pct_went_lower_after_bar"))} of triggers;
the other {_fmt_pct(ov.get("pct_first_touch_was_trough"))} printed their pullback low on the first-touch bar.
If they continued, median extra from the trigger Low {_fmt_pct(ov.get("median_extra_after_bar_if_lower"))}
(p90 {_fmt_pct(ov.get("p90_extra_after_bar_if_lower"))}).
Same-bar wash ≥1% of ATH through the 3.72% line: {_fmt_pct(ov.get("pct_same_bar_through"))}
(median trigger-bar extra {_fmt_pct(ov.get("median_same_bar_extra"))}).</p>

<h2>Bounce back — how many, how long</h2>
{_table(rec_b, rec_cols)}
<p class="small">Recovered to a new ATH: {_fmt_pct(ov.get("pct_recovered_new_ath"))}
({_fmt_int(ov.get("n_recovered_new_ath"))} of {_fmt_int(ov.get("n_triggers"))}).
Still open: {_fmt_pct(ov.get("pct_still_open"))}.
Median / average / p90 calendar days trigger → new ATH (recovered only):
{_fmt_num(ov.get("median_cal_days_to_ath"), 1)} / {_fmt_num(ov.get("avg_cal_days_to_ath"), 1)} / {_fmt_num(ov.get("p90_cal_days_to_ath"), 1)}.
Halfway bounce (close back to 1.86% off the ATH): {_fmt_pct(ov.get("pct_bounce_50pct"))},
median {_fmt_num(ov.get("median_cal_days_to_50pct"), 1)} days.
Close +2% / +5% above the trigger level: {_fmt_pct(ov.get("pct_bounce_plus2"))} / {_fmt_pct(ov.get("pct_bounce_plus5"))}.</p>

<h2>Eventual-trough slice (overstates “already 3.72%”)</h2>
<p class="meta">Parent rows whose <em>lowest</em> Low was eventually ≥3.72% down: N={_fmt_int(ev.get("n_eventual_ge_372"))}
({_fmt_pct(ev.get("pct_of_all_aths"))} of all closing ATHs). Median eventual drop {_fmt_pct(ev.get("median_eventual_drop"))};
median extra vs 3.72% {_fmt_pct(ev.get("median_extra_vs_372"))}; {_fmt_pct(ev.get("pct_recovered"))} later printed a new ATH;
median days <em>from the trough</em> to that high {_fmt_num(ev.get("median_cal_low_to_high"), 1)} (not from first-touch).
{_esc(ev.get("note"))}</p>

<h2>Invest ideas — hypotheses, not KEEP</h2>
<p class="small">Brainstorm only. Research candidate ≠ gold ≠ DailyRun. Prior weekly-support overlays on the mega-cap hold book
(<code>{TREND_AB}</code>) were <strong>HOLD</strong> — do not treat them as a green light.</p>
<div class="idea">
<h3><span class="tag">HYPOTHESIS</span> H1 — Buy the 3.72% dip, stop extra 5% / 1R</h3>
<p>{_esc(h1)}</p>
</div>
<div class="idea">
<h3><span class="tag">HYPOTHESIS</span> H2 — Wait for a higher low after 3.72%</h3>
<p>{_esc(h2)}</p>
</div>
<div class="idea">
<h3><span class="tag">HYPOTHESIS</span> H3 — Time-stop if not recovered in ~25 days</h3>
<p>{_esc(h3)}</p>
</div>
<div class="idea">
<h3><span class="tag">HYPOTHESIS</span> H4 — Scale in (not run)</h3>
<p>Third at the 3.72% line, third ~2% extra, third ~5% extra. Softens same-bar wash-through
({_fmt_pct(ov.get("pct_same_bar_through"))} of triggers already traded under the line on day one). Needs its own one-knob AB.</p>
</div>
<div class="idea">
<h3><span class="tag">HYPOTHESIS</span> H5 — Skip if weekly support is broken</h3>
<p>Only take the dip when weekly support is still rising and the close is not through the line.
Linked prior stamp <code>{TREND_AB}</code> was HOLD on the equal-weight top-X book (IS mixed / OOS often softened).
Do not adopt here.</p>
</div>

<h2>Cheap overlay vs no-trade (IS / OOS)</h2>
<p class="small">Control = do nothing (no trades). Candidate = buy the 3.72% limit on first Low-touch; stop extra 5%;
target = close above the ATH; time-stop = 25 calendar days. Same-bar Low through the stop exits STOP first.
$10,000 sheet notional / trade; Ann ROR uses that cash; Max DD / Sharpe seed $500,000 on exit-date equity
(no daily curve — Sharpe is closed-exit-date, not √252). Costs = 0. IS = trigger before 2024-01-01;
OOS = 2024+ report-only. Total / sheet PnL $ omitted from this table. Click headers to sort.</p>
{_table(books, book_cols)}
<p class="small">No-trade is zeros. If OOS quality softens versus IS, HOLD — do not retune 3.72 / 5% / 25d on 2024+.
This overlay is one frozen recipe, not a winner after shopping exits.</p>

<h2 id="stocks">Per-stock summary</h2>
<p class="small">Event-equal overall pinned at the top while you sort. Click a ticker to filter the trigger list.
Click column headers to sort.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{stock_head}</tr></thead><tbody>{''.join(stock_body)}</tbody></table></div>

<h2 id="triggers">Every first-touch trigger</h2>
<p class="small">Full list. Combined CSV: <a href="triggers.csv">triggers.csv</a>. Overlay fills: <a href="overlay_trades.csv">overlay_trades.csv</a>.</p>
<p><label class="small">Filter symbol <input class="filter" id="symFilter" type="search" placeholder="e.g. AAPL" /></label>
<button type="button" class="filter" data-slice="all">All</button>
<button type="button" class="filter" data-slice="open">Still open</button>
<button type="button" class="filter" data-slice="lower">Went lower vs 3.72%</button>
<span class="small" id="filterCount"></span></p>
<div class="table-wrap"><table class="sortable" id="eventsTable"><thead><tr>{ev_head}</tr></thead><tbody>{''.join(ev_body)}</tbody></table></div>

<h2>Definitions</h2>
<ul class="meta">
<li><strongATH</strong> — all-time high: new closing high in the local sample (first DuckDB bar, usually 2010-01-04 or the IPO). Not a 52-week high.</li>
<li><strong>S&amp;P 500</strong> — Standard &amp; Poor's 500. Membership is today's Wikipedia list projected backward (survivorship), then annual top 50 by approx market cap.</li>
<li><strong>3.72% trigger</strong> — first daily Low at least 3.72% below the ATH close. 3.72% is the parent pause-2+ trading-day median drop, not a searched optimum.</li>
<li><strong>Days</strong> — calendar days unless labeled td (trading days).</li>
<li><strong>IS / OOS</strong> — overlay only. In-sample triggers before 2024-01-01; 2024+ is report-only.</li>
</ul>
<p class="meta">Caveats: survivorship; scaled-now market caps; sample starts 2010; dividends ignored; limit fill at 3.72% is optimistic on gaps.
See <a href="BASELINE.md">BASELINE.md</a> and <a href="HYPOTHESIS.md">HYPOTHESIS.md</a>.</p>
<script>
{spx.SORTABLE_TABLE_SCRIPT}
(function(){{
  var input = document.getElementById("symFilter");
  var table = document.getElementById("eventsTable");
  var count = document.getElementById("filterCount");
  var slice = "all";
  function apply(sym){{
    var q = (sym || "").trim().toUpperCase();
    if (input && input.value.toUpperCase() !== q) input.value = q;
    var rows = table ? table.tBodies[0].querySelectorAll("tr") : [];
    var shown = 0;
    rows.forEach(function(r){{
      var ok = !q || (r.getAttribute("data-sym") || "") === q;
      if (slice === "open") ok = ok && r.getAttribute("data-open") === "1";
      if (slice === "lower") ok = ok && r.getAttribute("data-lower") === "1";
      r.style.display = ok ? "" : "none";
      if (ok) shown++;
    }});
    if (count) count.textContent = "showing " + shown + " triggers" + (q ? (" for " + q) : "") + (slice !== "all" ? (" [" + slice + "]") : "");
  }}
  if (input) input.addEventListener("input", function(){{ apply(input.value); }});
  document.querySelectorAll("a.sym[data-filter]").forEach(function(a){{
    a.addEventListener("click", function(){{ apply(a.getAttribute("data-filter")); }});
  }});
  document.querySelectorAll("button[data-slice]").forEach(function(b){{
    b.addEventListener("click", function(){{ slice = b.getAttribute("data-slice") || "all"; apply(input ? input.value : ""); }});
  }});
  apply(input ? input.value : "");
}})();
</script>
</body></html>
"""
    path.write_text(html, encoding="utf-8")


def main() -> int:
    t0 = time.time()
    STAMP_DIR.mkdir(parents=True, exist_ok=True)
    print("[372] loading parent events + OHLC...", flush=True)
    prior = _load_prior_events()
    ever = sorted(prior["symbol"].unique())
    raw = ath._load_ohlc(ever)
    raw_by = {s: g for s, g in raw.groupby("symbol", sort=False)}

    paths: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    for i, sym in enumerate(ever, 1):
        frame = raw_by.get(sym)
        evs = prior[prior["symbol"] == sym]
        if frame is None or frame.empty or evs.empty:
            print(f"[372] skip {sym}: no OHLC/events", flush=True)
            continue
        p, t = _paths_for_symbol(sym, frame, evs)
        paths.extend(p)
        trades.extend(t)
        if i % 20 == 0 or i == len(ever):
            print(f"[372] scored {i}/{len(ever)} names, {len(paths)} triggers", flush=True)

    if not paths:
        raise RuntimeError("No 3.72% first-touch triggers found")

    path_df = pd.DataFrame(paths)
    trade_df = pd.DataFrame(trades)
    stocks = _stock_summary(path_df)
    ov = _overall(path_df)
    extra_b = _buckets_extra(path_df)
    rec_b = _buckets_recover(path_df)
    ev = _eventual_compare(prior)

    is_tr = [t for t in trades if pd.Timestamp(t["trigger_date"]) < IS_CUT]
    oos_tr = [t for t in trades if pd.Timestamp(t["trigger_date"]) >= IS_CUT]
    books = pd.DataFrame(
        [
            _book_metrics([], label="no_trade", note="Control: do nothing (cash)."),
            _book_metrics(
                trades,
                label="overlay_FULL",
                note="Buy 3.72% first-touch; stop extra 5%; target new ATH close; time-stop 25d. All years.",
            ),
            _book_metrics(is_tr, label="overlay_IS", note="Same overlay. Triggers before 2024-01-01."),
            _book_metrics(oos_tr, label="overlay_OOS", note="Same overlay. Triggers on/after 2024-01-01 (report-only)."),
        ]
    )

    ohlc_start = str(pd.Timestamp(raw["Date"].min()).date())
    ohlc_end = str(pd.Timestamp(raw["Date"].max()).date())

    path_df.to_csv(STAMP_DIR / "triggers.csv", index=False)
    stocks.to_csv(STAMP_DIR / "stock_summary.csv", index=False)
    extra_b.to_csv(STAMP_DIR / "extra_drop_buckets.csv", index=False)
    rec_b.to_csv(STAMP_DIR / "recovery_buckets.csv", index=False)
    books.to_csv(STAMP_DIR / "overlay_compare.csv", index=False)
    out_tr = trade_df.copy()
    out_tr["trigger_date"] = pd.to_datetime(out_tr["trigger_date"]).dt.strftime("%Y-%m-%d")
    out_tr["exit_date"] = pd.to_datetime(out_tr["exit_date"]).dt.strftime("%Y-%m-%d")
    out_tr.to_csv(STAMP_DIR / "overlay_trades.csv", index=False)
    (STAMP_DIR / "overall.json").write_text(json.dumps(ov, indent=2, default=str), encoding="utf-8")

    _write_baseline(
        STAMP_DIR / "BASELINE.md",
        ov=ov,
        ev=ev,
        books=books,
        ohlc_start=ohlc_start,
        ohlc_end=ohlc_end,
        n_names=int(ov["n_names"]),
        n_aths=int(len(prior)),
    )
    _write_hypothesis(STAMP_DIR / "HYPOTHESIS.md")
    _write_html(
        STAMP_DIR / "report.html",
        ov=ov,
        ev=ev,
        stocks=stocks,
        paths=path_df,
        extra_b=extra_b,
        rec_b=rec_b,
        books=books,
        ohlc_start=ohlc_start,
        ohlc_end=ohlc_end,
    )
    (STAMP_DIR / "compare.html").write_text(
        (STAMP_DIR / "report.html").read_text(encoding="utf-8"), encoding="utf-8"
    )
    summary = {
        "stamp": STAMP_ID,
        "parent": PRIOR_ID,
        "drop_pct": DROP_PCT,
        "trigger_basis": "Low",
        "ohlc_start": ohlc_start,
        "ohlc_end": ohlc_end,
        "overall": ov,
        "eventual_trough_ge_372": ev,
        "overlay": books.to_dict("records"),
        "elapsed_sec": time.time() - t0,
        "not_dailyrun": True,
    }
    (STAMP_DIR / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {
                k: ov[k]
                for k in (
                    "n_triggers",
                    "n_names",
                    "pct_went_lower_vs_372",
                    "pct_went_lower_after_bar",
                    "median_extra_drop_if_lower",
                    "pct_recovered_new_ath",
                    "pct_still_open",
                    "median_cal_days_to_ath",
                    "avg_cal_days_to_ath",
                )
            },
            indent=2,
        ),
        flush=True,
    )
    print(f"[372] wrote {STAMP_DIR} in {time.time() - t0:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
