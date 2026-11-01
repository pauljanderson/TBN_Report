#!/usr/bin/env python3
"""ATH pullback 2×-drop ledger + cheap overlay A/B (research only).

Same universe / closing-ATH / daily OHLC as ``top50_ath_drawdown_20260916``.
Does **not** write into ``top50_ath_372_path_20260916`` (sibling first-touch path).

2× the drop = from the **trough** (or from first-touch of D%), price rallies
at least 2 × D% — a measured move / 2R, not merely back to the old ATH (~1×).

Not DailyRun. Not gold. Do not commit from this script.
"""
from __future__ import annotations

import html as html_mod
import json
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

STAMP_ID = "top50_ath_2x_drop_ab_20260916"
STAMP_DIR = REPO / "drive" / "paul_experiments" / STAMP_ID
PRIOR_ID = "top50_ath_drawdown_20260916"
PRIOR_DIR = REPO / "drive" / "paul_experiments" / PRIOR_ID
SIBLING_ID = "top50_ath_372_path_20260916"

DROP_372 = 3.72
SHEET_CASH = 10_000.0
INITIAL_ACCOUNT = 500_000.0
IS_CUT = pd.Timestamp("2024-01-01")

# Eventual-trough buckets (percent). 3.72 is a tight band around the sibling cutoff.
TROUGH_BUCKETS: list[tuple[str, float, float]] = [
    ("2–3%", 2.0, 3.0),
    ("3–4%", 3.0, 4.0),
    ("~3.72% (3.50–3.94)", 3.50, 3.94),
    ("4–5%", 4.0, 5.0),
    ("5–8%", 5.0, 8.0),
    ("8–12%", 8.0, 12.0),
    ("12%+", 12.0, 1e9),
]
# First-touch D% thresholds (pre-declared; 3.72 matches sibling, not a search).
FT_THRESHOLDS = [2.0, 2.5, 3.0, 3.72, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 15.0]
MFE_WINDOWS_CAL = (20, 60, 180, 365)

ORIGINAL_REQUEST = (
    "looking at this report at what avg. pct drop do we regain at least 2x the drop? "
    "and how many days does it take, can we run some AB tests to see if there are "
    "any profitable systems here?"
)
LAYMAN = (
    "Same mega-cap list as the all-time high (ATH) pullback report: names that were "
    "ever in the annual top 50 by approximate market cap on the Standard & Poor's 500 "
    "(S&P 500). After a new closing high, the stock falls D% from that close to the "
    "lowest Low. “Regain at least 2× the drop” means that from that low, price rallies "
    "at least two times D (if it fell 5%, we need +10% off the low). That is a measured "
    "move — more than just crawling back to the old high, which is only about 1× the "
    "drop. We also ask the harder version: from the first day the drop hits a chosen "
    "D% (not waiting for the exact bottom), does price bounce 2× D from that first-touch "
    "line? We bucket pullbacks by size, count how often 2× happens, how many days it "
    "takes, and how many never get there before the chart ends. Then we paper-trade a "
    "few simple rules (buy the first-touch of D%, sell at +2× D or back at the old high, "
    "stop a bit further down) versus do-nothing, buy-and-hold the S&P 500 ETF (SPY), "
    "and the 3.72% first-touch / exit-at-old-high idea. In-sample is entries before 2024; "
    "2024+ is report-only. Research only — not a live rule and not DailyRun."
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


def _fmt_delta(v: Any, digits: int = 2, *, pct: bool = False) -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    sign = "+" if n >= 0 else "−"
    body = f"{abs(n):,.{digits}f}"
    return f"{sign}{body}%" if pct else f"{sign}{body}"


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


def _first_hit(arr: np.ndarray, level: float) -> int | None:
    hits = np.flatnonzero(arr >= level - 1e-12)
    if hits.size == 0:
        return None
    return int(hits[0])


def _mfe_pct(high_win: np.ndarray, base: float) -> float | None:
    if high_win.size == 0 or not np.isfinite(base) or base <= 0:
        return None
    mx = float(np.max(high_win))
    return (mx / base - 1.0) * 100.0


def _cal_end_index(dates: np.ndarray, start_i: int, cal_days: int) -> int:
    t0 = pd.Timestamp(dates[start_i])
    n = len(dates)
    end_i = start_i
    for j in range(start_i, n):
        if int((pd.Timestamp(dates[j]) - t0).days) > cal_days:
            break
        end_i = j
    return end_i


def _trough_2x_for_symbol(symbol: str, frame: pd.DataFrame, events: pd.DataFrame) -> list[dict[str, Any]]:
    dates, close, low, high, date_to_i = _prep_ohlc(frame)
    n = len(close)
    rows: list[dict[str, Any]] = []
    for ev in events.to_dict("records"):
        if str(ev.get("status") or "") == "at_sample_ath":
            continue
        try:
            p0 = float(ev["ath_close"])
            d_pct = float(ev["pct_drop"]) if ev.get("pct_drop") is not None and pd.notna(ev.get("pct_drop")) else None
            p_low = float(ev["trough_low"]) if ev.get("trough_low") is not None and pd.notna(ev.get("trough_low")) else None
        except (TypeError, ValueError):
            continue
        if d_pct is None or p_low is None or not np.isfinite(d_pct) or not np.isfinite(p_low) or p0 <= 0 or p_low <= 0:
            continue
        if d_pct <= 0:
            continue
        ath_key = pd.Timestamp(ev["ath_date"]).date()
        trough_key = pd.Timestamp(ev["trough_date"]).date() if ev.get("trough_date") else None
        ath_i = date_to_i.get(ath_key)
        trough_i = date_to_i.get(trough_key) if trough_key is not None else None
        if ath_i is None or trough_i is None or trough_i >= n:
            continue

        need = p_low * (1.0 + 2.0 * d_pct / 100.0)
        need_close = need
        hit_h = _first_hit(high[trough_i:], need)
        hit_c = _first_hit(close[trough_i:], need_close)
        hit_h_i = trough_i + hit_h if hit_h is not None else None
        hit_c_i = trough_i + hit_c if hit_c is not None else None
        t_tr = pd.Timestamp(dates[trough_i])

        def _days(j: int | None) -> tuple[int | None, int | None]:
            if j is None:
                return None, None
            return int((pd.Timestamp(dates[j]) - t_tr).days), int(j - trough_i)

        cal_h, td_h = _days(hit_h_i)
        cal_c, td_c = _days(hit_c_i)
        last = str(pd.Timestamp(dates[-1]).date())
        mfe_ever = _mfe_pct(high[trough_i:], p_low)
        mfe_close_ever = _mfe_pct(close[trough_i:], p_low)
        win_mfe: dict[str, float | None] = {}
        win_hit: dict[str, int] = {}
        for w in MFE_WINDOWS_CAL:
            end_i = _cal_end_index(dates, trough_i, w)
            win_mfe[f"mfe_high_{w}d"] = _mfe_pct(high[trough_i : end_i + 1], p_low)
            if hit_h_i is not None and int((pd.Timestamp(dates[hit_h_i]) - t_tr).days) <= w:
                win_hit[f"hit_2x_high_{w}d"] = 1
            else:
                win_hit[f"hit_2x_high_{w}d"] = 0

        rows.append(
            {
                "symbol": symbol,
                "ath_seq": ev.get("ath_seq"),
                "ath_date": str(pd.Timestamp(dates[ath_i]).date()),
                "ath_close": p0,
                "trough_date": str(t_tr.date()),
                "trough_low": p_low,
                "pct_drop": d_pct,
                "two_x_target": need,
                "basis": "trough_low",
                "hit_2x_high": int(hit_h_i is not None),
                "hit_2x_close": int(hit_c_i is not None),
                "cal_days_trough_to_2x_high": cal_h,
                "td_days_trough_to_2x_high": td_h,
                "cal_days_trough_to_2x_close": cal_c,
                "td_days_trough_to_2x_close": td_c,
                "never_2x_high": int(hit_h_i is None),
                "mfe_high_ever_pct": mfe_ever,
                "mfe_close_ever_pct": mfe_close_ever,
                "two_d": 2.0 * d_pct,
                "mfe_ge_2d_180": int(
                    (win_mfe.get("mfe_high_180d") is not None)
                    and (win_mfe["mfe_high_180d"] >= 2.0 * d_pct - 1e-9)
                ),
                "mfe_ge_2d_ever": int(mfe_ever is not None and mfe_ever >= 2.0 * d_pct - 1e-9),
                "status_parent": ev.get("status"),
                "last_date": last,
                **win_mfe,
                **win_hit,
            }
        )
    return rows


def _first_touch_2x_for_symbol(
    symbol: str,
    frame: pd.DataFrame,
    events: pd.DataFrame,
    thresholds: list[float],
) -> list[dict[str, Any]]:
    dates, close, low, high, date_to_i = _prep_ohlc(frame)
    n = len(close)
    rows: list[dict[str, Any]] = []
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
        found: dict[float, int] = {}
        for j in range(ath_i + 1, n):
            drop_j = (p0 - float(low[j])) / p0 * 100.0
            for th in thresholds:
                if th in found:
                    continue
                if drop_j + 1e-12 >= th:
                    found[th] = j
            if float(close[j]) > p0:
                break
            if len(found) == len(thresholds):
                break
        for th, trig_i in found.items():
            level = p0 * (1.0 - th / 100.0)
            need = level * (1.0 + 2.0 * th / 100.0)
            t_tr = pd.Timestamp(dates[trig_i])
            hit = _first_hit(high[trig_i:], need)
            hit_c = _first_hit(close[trig_i:], need)
            hit_i = trig_i + hit if hit is not None else None
            hit_c_i = trig_i + hit_c if hit_c is not None else None
            cal_h = int((pd.Timestamp(dates[hit_i]) - t_tr).days) if hit_i is not None else None
            td_h = int(hit_i - trig_i) if hit_i is not None else None
            cal_c = int((pd.Timestamp(dates[hit_c_i]) - t_tr).days) if hit_c_i is not None else None
            mfe_ever = _mfe_pct(high[trig_i:], level)
            win_mfe: dict[str, float | None] = {}
            win_hit: dict[str, int] = {}
            for w in MFE_WINDOWS_CAL:
                end_i = _cal_end_index(dates, trig_i, w)
                win_mfe[f"mfe_high_{w}d"] = _mfe_pct(high[trig_i : end_i + 1], level)
                win_hit[f"hit_2x_high_{w}d"] = int(
                    hit_i is not None and int((pd.Timestamp(dates[hit_i]) - t_tr).days) <= w
                )
            rows.append(
                {
                    "symbol": symbol,
                    "ath_seq": ev.get("ath_seq"),
                    "ath_date": str(pd.Timestamp(dates[ath_i]).date()),
                    "ath_close": p0,
                    "trigger_date": str(t_tr.date()),
                    "trigger_level": level,
                    "trigger_low": float(low[trig_i]),
                    "d_pct": th,
                    "two_x_target": need,
                    "basis": "first_touch_level",
                    "same_bar_through": int(float(low[trig_i]) < level - 1e-12),
                    "hit_2x_high": int(hit_i is not None),
                    "hit_2x_close": int(hit_c_i is not None),
                    "cal_days_touch_to_2x_high": cal_h,
                    "td_days_touch_to_2x_high": td_h,
                    "cal_days_touch_to_2x_close": cal_c,
                    "never_2x_high": int(hit_i is None),
                    "mfe_high_ever_pct": mfe_ever,
                    "two_d": 2.0 * th,
                    "mfe_ge_2d_180": int(
                        (win_mfe.get("mfe_high_180d") is not None)
                        and (win_mfe["mfe_high_180d"] >= 2.0 * th - 1e-9)
                    ),
                    "mfe_ge_2d_ever": int(mfe_ever is not None and mfe_ever >= 2.0 * th - 1e-9),
                    **win_mfe,
                    **win_hit,
                }
            )
    return rows


def _bucket_label(d: float) -> str | None:
    for lab, lo, hi in TROUGH_BUCKETS:
        if lo <= d < hi:
            return lab
    return None


def _agg_trough_bucket(sub: pd.DataFrame, label: str, note: str) -> dict[str, Any]:
    n = int(len(sub))
    hit = sub[sub["hit_2x_high"] == 1]
    never = sub[sub["never_2x_high"] == 1]
    hit180 = sub[sub["hit_2x_high_180d"] == 1] if "hit_2x_high_180d" in sub.columns else hit
    return {
        "bucket": label,
        "basis": "trough (eventual D, High tag)",
        "note": note,
        "n": n,
        "n_names": int(sub["symbol"].nunique()) if n else 0,
        "avg_d": _mean(sub["pct_drop"]) if n else None,
        "median_d": _median(sub["pct_drop"]) if n else None,
        "pct_hit_2x_ever": _rate(int(len(hit)), n),
        "pct_hit_2x_20d": _rate(int(sub["hit_2x_high_20d"].sum()), n) if n else None,
        "pct_hit_2x_60d": _rate(int(sub["hit_2x_high_60d"].sum()), n) if n else None,
        "pct_hit_2x_180d": _rate(int(sub["hit_2x_high_180d"].sum()), n) if n else None,
        "pct_hit_2x_365d": _rate(int(sub["hit_2x_high_365d"].sum()), n) if n else None,
        "pct_never_2x": _rate(int(len(never)), n),
        "avg_days_to_2x": _mean(hit["cal_days_trough_to_2x_high"]) if len(hit) else None,
        "median_days_to_2x": _median(hit["cal_days_trough_to_2x_high"]) if len(hit) else None,
        "p90_days_to_2x": _pctl(hit["cal_days_trough_to_2x_high"], 90) if len(hit) else None,
        "avg_days_to_2x_180": _mean(hit180["cal_days_trough_to_2x_high"]) if len(hit180) else None,
        "median_days_to_2x_180": _median(hit180["cal_days_trough_to_2x_high"]) if len(hit180) else None,
        "median_mfe_180": _median(sub["mfe_high_180d"]) if n else None,
        "mean_mfe_180": _mean(sub["mfe_high_180d"]) if n else None,
        "median_mfe_ever": _median(sub["mfe_high_ever_pct"]) if n else None,
        "mean_mfe_ever": _mean(sub["mfe_high_ever_pct"]) if n else None,
        "two_d_from_avg_d": (2.0 * float(_mean(sub["pct_drop"]))) if n and _mean(sub["pct_drop"]) is not None else None,
        "median_mfe_180_ge_2d": int(
            (_median(sub["mfe_high_180d"]) is not None)
            and (_mean(sub["pct_drop"]) is not None)
            and (_median(sub["mfe_high_180d"]) >= 2.0 * float(_mean(sub["pct_drop"])) - 1e-9)
        )
        if n
        else 0,
        "mean_mfe_180_ge_2d": int(
            (_mean(sub["mfe_high_180d"]) is not None)
            and (_mean(sub["pct_drop"]) is not None)
            and (_mean(sub["mfe_high_180d"]) >= 2.0 * float(_mean(sub["pct_drop"])) - 1e-9)
        )
        if n
        else 0,
        "pct_hit_2x_close_ever": _rate(int(sub["hit_2x_close"].sum()), n) if n else None,
    }


def _agg_ft_bucket(sub: pd.DataFrame, d: float) -> dict[str, Any]:
    n = int(len(sub))
    hit = sub[sub["hit_2x_high"] == 1]
    never = sub[sub["never_2x_high"] == 1]
    hit180 = sub[sub["hit_2x_high_180d"] == 1] if n else sub
    two_d = 2.0 * d
    med180 = _median(sub["mfe_high_180d"]) if n else None
    mean180 = _mean(sub["mfe_high_180d"]) if n else None
    return {
        "bucket": f"first-touch {d:g}%",
        "basis": "first-touch level (High tag of +2D from trigger)",
        "note": f"Trigger = first Low ≥ {d:g}% below ATH close. 2× = High ≥ trigger × (1+{two_d:g}%). Harder than trough-2× when the bar already traded through.",
        "n": n,
        "n_names": int(sub["symbol"].nunique()) if n else 0,
        "avg_d": d,
        "median_d": d,
        "pct_hit_2x_ever": _rate(int(len(hit)), n),
        "pct_hit_2x_20d": _rate(int(sub["hit_2x_high_20d"].sum()), n) if n else None,
        "pct_hit_2x_60d": _rate(int(sub["hit_2x_high_60d"].sum()), n) if n else None,
        "pct_hit_2x_180d": _rate(int(sub["hit_2x_high_180d"].sum()), n) if n else None,
        "pct_hit_2x_365d": _rate(int(sub["hit_2x_high_365d"].sum()), n) if n else None,
        "pct_never_2x": _rate(int(len(never)), n),
        "avg_days_to_2x": _mean(hit["cal_days_touch_to_2x_high"]) if len(hit) else None,
        "median_days_to_2x": _median(hit["cal_days_touch_to_2x_high"]) if len(hit) else None,
        "p90_days_to_2x": _pctl(hit["cal_days_touch_to_2x_high"], 90) if len(hit) else None,
        "avg_days_to_2x_180": _mean(hit180["cal_days_touch_to_2x_high"]) if len(hit180) else None,
        "median_days_to_2x_180": _median(hit180["cal_days_touch_to_2x_high"]) if len(hit180) else None,
        "median_mfe_180": med180,
        "mean_mfe_180": mean180,
        "median_mfe_ever": _median(sub["mfe_high_ever_pct"]) if n else None,
        "mean_mfe_ever": _mean(sub["mfe_high_ever_pct"]) if n else None,
        "two_d_from_avg_d": two_d,
        "median_mfe_180_ge_2d": int(med180 is not None and med180 >= two_d - 1e-9),
        "mean_mfe_180_ge_2d": int(mean180 is not None and mean180 >= two_d - 1e-9),
        "pct_hit_2x_close_ever": _rate(int(sub["hit_2x_close"].sum()), n) if n else None,
        "pct_same_bar_through": _rate(int(sub["same_bar_through"].sum()), n) if n else None,
    }


def _pick_working_d(ft_rows: list[dict[str, Any]]) -> tuple[float, str]:
    """Smallest first-touch D ≥ 3.72 where median 180d MFE ≥ 2D and N≥80.

    Stair-step D<3.72 is reported in the table but not used as the AB D-knob
    (parent pause-2+ median was 3.72). Selection is labeled in BASELINE.
    """
    ranked = [r for r in ft_rows if float(r["avg_d"]) >= DROP_372 - 1e-9 and int(r.get("n") or 0) >= 80]
    ranked.sort(key=lambda r: float(r["avg_d"]))
    for r in ranked:
        if int(r.get("median_mfe_180_ge_2d") or 0) == 1:
            return float(r["avg_d"]), (
                f"smallest first-touch D≥3.72% whose median 180-calendar-day High MFE from the "
                f"trigger ≥ 2D (N={r['n']}, med MFE 180d={r.get('median_mfe_180')})"
            )
    # Fallback: highest 180d hit-rate among D≥3.72
    if ranked:
        best = max(ranked, key=lambda r: (r.get("pct_hit_2x_180d") or -1, -float(r["avg_d"])))
        return float(best["avg_d"]), (
            "no first-touch D≥3.72 had median 180d MFE ≥ 2D; using the ≥3.72 threshold "
            f"with the highest 180d 2× hit-rate ({best['bucket']})"
        )
    return 5.0, "fallback D=5% (material parent slice); no qualifying first-touch row"


def _simulate_trades(
    symbol: str,
    dates: np.ndarray,
    close: np.ndarray,
    low: np.ndarray,
    high: np.ndarray,
    date_to_i: dict,
    events: pd.DataFrame,
    *,
    d_pct: float,
    target: str,
    stop_mult: float,
    arm: str,
) -> list[dict[str, Any]]:
    """One position per symbol. Fill at first-touch D% level.

    target:
      ath_close — first Close > ATH (≈1× back to the high; sibling-style)
      two_d_entry — first High ≥ entry × (1+2D)
    stop = entry × (1 − stop_mult × D/100). Same-bar Low through stop = STOP first.
    """
    n = len(close)
    trades: list[dict[str, Any]] = []
    busy_until = -1
    level_frac = d_pct / 100.0
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
        if ath_i <= busy_until:
            continue
        level = p0 * (1.0 - level_frac)
        trig_i = None
        for j in range(ath_i + 1, n):
            if j <= busy_until:
                continue
            if float(low[j]) <= level + 1e-12:
                trig_i = j
                break
            if float(close[j]) > p0:
                break
        if trig_i is None:
            continue
        stop_px = level * (1.0 - stop_mult * level_frac)
        tgt_px = p0
        if target == "two_d_entry":
            tgt_px = level * (1.0 + 2.0 * level_frac)
        t_tr = pd.Timestamp(dates[trig_i])
        exit_i = None
        exit_px = None
        exit_type = "OPEN"
        trig_low = float(low[trig_i])
        trig_high = float(high[trig_i])
        trig_close = float(close[trig_i])
        if trig_low <= stop_px + 1e-12:
            exit_i, exit_px, exit_type = trig_i, stop_px, "STOP"
        elif target == "two_d_entry" and trig_high >= tgt_px - 1e-12:
            exit_i, exit_px, exit_type = trig_i, tgt_px, "TARGET"
        elif target == "ath_close" and trig_close > p0:
            exit_i, exit_px, exit_type = trig_i, trig_close, "TARGET"
        else:
            for j in range(trig_i + 1, n):
                lj = float(low[j])
                hj = float(high[j])
                cj = float(close[j])
                if lj <= stop_px + 1e-12:
                    exit_i, exit_px, exit_type = j, stop_px, "STOP"
                    break
                if target == "two_d_entry" and hj >= tgt_px - 1e-12:
                    exit_i, exit_px, exit_type = j, tgt_px, "TARGET"
                    break
                if target == "ath_close" and cj > p0:
                    exit_i, exit_px, exit_type = j, cj, "TARGET"
                    break
            if exit_i is None:
                exit_i, exit_px, exit_type = n - 1, float(close[-1]), "OPEN"
        pnl_pct = (float(exit_px) / level - 1.0) * 100.0
        t_ex = pd.Timestamp(dates[exit_i])
        busy_until = exit_i
        trades.append(
            {
                "arm": arm,
                "symbol": symbol,
                "ath_seq": ev.get("ath_seq"),
                "ath_date": str(pd.Timestamp(dates[ath_i]).date()),
                "ath_close": p0,
                "trigger_date": t_tr,
                "exit_date": t_ex,
                "entry": level,
                "exit": float(exit_px),
                "stop": stop_px,
                "target": tgt_px,
                "d_pct": d_pct,
                "stop_mult": stop_mult,
                "target_mode": target,
                "pnl_pct": pnl_pct,
                "pnl_d": SHEET_CASH * pnl_pct / 100.0,
                "cal_days_held": int((t_ex - t_tr).days),
                "td_days_held": int(exit_i - trig_i),
                "exit_type": exit_type,
                "closed": int(exit_type != "OPEN"),
                "is_oos": int(t_tr >= IS_CUT),
            }
        )
    return trades


def _losing_streak(rows: list[dict[str, Any]]) -> int | None:
    if not rows:
        return None
    ordered = sorted(rows, key=lambda t: pd.Timestamp(t["exit_date"]))
    best = cur = 0
    for t in ordered:
        if float(t["pnl_pct"]) <= 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def _concurrent_stats(rows: list[dict[str, Any]]) -> tuple[float | None, float | None, int | None]:
    if not rows:
        return None, None, None
    events: list[tuple[pd.Timestamp, int]] = []
    for t in rows:
        events.append((pd.Timestamp(t["trigger_date"]), 1))
        events.append((pd.Timestamp(t["exit_date"]), -1))
    events.sort(key=lambda x: (x[0], x[1]))
    cur = mx = 0
    # sample daily via unique dates
    by_day: dict[pd.Timestamp, int] = {}
    cur = 0
    for ts, delta in events:
        cur += delta
        mx = max(mx, cur)
        by_day[ts] = cur
    vals = list(by_day.values())
    return _mean(vals), _median(vals), int(mx)


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
        "losing_streak": None,
        "avg_positions": None,
        "median_positions": None,
        "max_positions": None,
        "n_target": 0,
        "n_stop": 0,
        "n_time": 0,
        "n_open": 0,
        "pct_target": None,
        "pct_stop": None,
        "pct_time": None,
        "pct_open": None,
        "paul_score": None,
        "fit_score": None,
        "fit_score_robust": None,
        "overlay_note": "no trades",
        "verdict": "",
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
    avg_pos, med_pos, max_pos = _concurrent_stats(rows)
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
        "losing_streak": _losing_streak(rows),
        "avg_positions": avg_pos,
        "median_positions": med_pos,
        "max_positions": max_pos,
        "n_target": n_target,
        "n_stop": n_stop,
        "n_time": n_time,
        "n_open": n_open,
        "pct_target": _rate(n_target, n),
        "pct_stop": _rate(n_stop, n),
        "pct_time": _rate(n_time, n),
        "pct_open": _rate(n_open, n),
        "paul_score": None,
        "fit_score": None,
        "fit_score_robust": None,
        "overlay_note": ov.get("note") or "",
        "verdict": "",
    }


def _spy_paired(control: list[dict[str, Any]], spy: pd.DataFrame) -> list[dict[str, Any]]:
    if spy.empty or not control:
        return []
    s = spy.dropna(subset=["Close"]).copy()
    s["Date"] = pd.to_datetime(s["Date"])
    s = s.sort_values("Date")
    dates = s["Date"].to_numpy()
    px = s["Close"].to_numpy(dtype=float)
    date_to_i = {pd.Timestamp(d).date(): i for i, d in enumerate(dates)}

    def _px_on(ts: pd.Timestamp) -> float | None:
        key = pd.Timestamp(ts).date()
        i = date_to_i.get(key)
        if i is not None:
            return float(px[i])
        later = [k for k in date_to_i if k >= key]
        if not later:
            return None
        return float(px[date_to_i[min(later)]])

    out: list[dict[str, Any]] = []
    for t in control:
        e = _px_on(t["trigger_date"])
        x = _px_on(t["exit_date"])
        if e is None or x is None or e <= 0:
            continue
        pnl_pct = (x / e - 1.0) * 100.0
        out.append(
            {
                **{k: t[k] for k in ("symbol", "ath_seq", "ath_date") if k in t},
                "arm": "spy_paired_ctrl",
                "trigger_date": t["trigger_date"],
                "exit_date": t["exit_date"],
                "entry": e,
                "exit": x,
                "stop": None,
                "target": None,
                "d_pct": None,
                "stop_mult": None,
                "target_mode": "spy_close_paired",
                "pnl_pct": pnl_pct,
                "pnl_d": SHEET_CASH * pnl_pct / 100.0,
                "cal_days_held": t["cal_days_held"],
                "td_days_held": t.get("td_days_held"),
                "exit_type": "TIME",
                "closed": 1,
                "is_oos": t["is_oos"],
            }
        )
    return out


def _spy_bh(spy: pd.DataFrame) -> list[dict[str, Any]]:
    s = spy.dropna(subset=["Close"]).copy()
    s["Date"] = pd.to_datetime(s["Date"])
    s = s.sort_values("Date")
    if s.empty:
        return []
    e = float(s.iloc[0]["Close"])
    x = float(s.iloc[-1]["Close"])
    t0 = pd.Timestamp(s.iloc[0]["Date"])
    t1 = pd.Timestamp(s.iloc[-1]["Date"])
    pnl = (x / e - 1.0) * 100.0
    return [
        {
            "arm": "spy_bh",
            "symbol": "SPY",
            "ath_seq": 1,
            "ath_date": str(t0.date()),
            "trigger_date": t0,
            "exit_date": t1,
            "entry": e,
            "exit": x,
            "stop": None,
            "target": None,
            "d_pct": None,
            "stop_mult": None,
            "target_mode": "buy_hold",
            "pnl_pct": pnl,
            "pnl_d": SHEET_CASH * pnl / 100.0,
            "cal_days_held": int((t1 - t0).days),
            "td_days_held": int(len(s) - 1),
            "exit_type": "TIME",
            "closed": 1,
            "is_oos": 0,
        }
    ]


def _quality_better(arm: dict[str, Any], ctrl: dict[str, Any]) -> bool:
    a = arm.get("avg_pnl_pct")
    c = ctrl.get("avg_pnl_pct")
    if a is None or c is None or not np.isfinite(a) or not np.isfinite(c):
        return False
    n_a, n_c = int(arm.get("n_trades") or 0), int(ctrl.get("n_trades") or 0)
    if n_a < 30:
        return False
    if n_c > 0 and n_a < max(30, int(0.35 * n_c)) and n_a < 80:
        return False
    pf_a, pf_c = arm.get("profit_factor"), ctrl.get("profit_factor")
    wr_a, wr_c = arm.get("win_pct"), ctrl.get("win_pct")
    pnl_up = a > c + 0.05
    pf_ok = pf_a is None or pf_c is None or (np.isfinite(pf_a) and np.isfinite(pf_c) and pf_a >= pf_c - 0.05)
    wr_ok = wr_a is None or wr_c is None or (wr_a >= wr_c - 3.0)
    return bool(pnl_up and pf_ok and wr_ok)


def _oos_softens(is_arm: dict[str, Any], oos_arm: dict[str, Any]) -> bool:
    ia, oa = is_arm.get("avg_pnl_pct"), oos_arm.get("avg_pnl_pct")
    if ia is None or oa is None or not np.isfinite(ia) or not np.isfinite(oa):
        return True
    if oa < ia - 0.35:
        return True
    iw, ow = is_arm.get("win_pct"), oos_arm.get("win_pct")
    if iw is not None and ow is not None and ow < iw - 8.0:
        return True
    ip, op = is_arm.get("profit_factor"), oos_arm.get("profit_factor")
    if ip is not None and op is not None and np.isfinite(ip) and np.isfinite(op) and op + 0.15 < ip:
        return True
    n_o = int(oos_arm.get("n_trades") or 0)
    if n_o < 20:
        return True
    return False


def _verdict_for(
    arm_id: str,
    books: dict[tuple[str, str], dict[str, Any]],
) -> str:
    if arm_id in ("no_trade", "spy_bh", "spy_paired_ctrl", "ctrl_372_1x_ath"):
        return "CONTROL / CONTEXT"
    is_arm = books.get((arm_id, "IS"))
    oos_arm = books.get((arm_id, "OOS"))
    is_ctrl = books.get(("ctrl_372_1x_ath", "IS"))
    oos_ctrl = books.get(("ctrl_372_1x_ath", "OOS"))
    if not is_arm or not is_ctrl:
        return "HOLD"
    better = _quality_better(is_arm, is_ctrl)
    if not better:
        a, c = is_arm.get("avg_pnl_pct"), is_ctrl.get("avg_pnl_pct")
        if a is not None and c is not None and a + 0.05 < c:
            return "DISMISS"
        return "HOLD"
    if arm_id.endswith("_s05") or arm_id.endswith("_s15"):
        return "HOLD"
    dd_a, dd_c = is_arm.get("max_dd"), is_ctrl.get("max_dd")
    cal_a, cal_c = is_arm.get("calmar"), is_ctrl.get("calmar")
    worse_dd = (
        dd_a is not None
        and dd_c is not None
        and np.isfinite(dd_a)
        and np.isfinite(dd_c)
        and float(dd_a) > float(dd_c) + 1.0
    )
    cal_flat = (
        cal_a is None
        or cal_c is None
        or not np.isfinite(cal_a)
        or not np.isfinite(cal_c)
        or float(cal_a) <= float(cal_c) + 0.05
    )
    if worse_dd and cal_flat:
        return "HOLD"
    if not oos_arm or _oos_softens(is_arm, oos_arm):
        return "HOLD"
    if oos_ctrl and not _quality_better(oos_arm, oos_ctrl):
        return "HOLD"
    return "LEAN KEEP (research only; not gold; not DailyRun)"


def _table(df: pd.DataFrame, cols: list[tuple[str, str, str]], *, row_class_key: str | None = None) -> str:
    if df is None or df.empty:
        return '<p class="small muted">None.</p>'
    head = "".join(_th(lab, typ) for lab, typ, _ in cols)
    body = []
    for _, r in df.iterrows():
        cls = ""
        if row_class_key and str(r.get(row_class_key) or "").startswith("LEAN KEEP"):
            cls = ' class="keep"'
        elif row_class_key and str(r.get(row_class_key) or "") == "DISMISS":
            cls = ' class="dismiss"'
        elif row_class_key and str(r.get(row_class_key) or "") == "HOLD":
            cls = ' class="hold"'
        elif str(r.get("arm") or "") == "ctrl_372_1x_ath":
            cls = ' class="ctrl"'
        elif str(r.get("slice") or "") == "" and str(r.get("bucket") or "").startswith("OVERALL"):
            cls = ' class="total-row"'
        tds = []
        for _lab, typ, key in cols:
            v = r.get(key)
            if typ == "num" and key in ("expectancy_d", "profit_per_capital_day"):
                tds.append(f"<td>{cf.format_money(v)}</td>")
            elif typ == "num" and key.startswith("d_") and "dd" in key:
                tds.append(f"<td>{_fmt_delta(v, 2, pct=True)}</td>")
            elif typ == "num" and key.startswith("d_") and key in (
                "d_win_pct",
                "d_avg_pnl_pct",
                "d_ann_ror",
                "d_avg_pnl_pct_wo_max",
            ):
                tds.append(f"<td>{_fmt_delta(v, 2, pct=True)}</td>")
            elif typ == "num" and key.startswith("d_"):
                tds.append(f"<td>{_fmt_delta(v, 2)}</td>")
            elif typ == "num" and (
                key.startswith("pct_")
                or key.endswith("_pct")
                or key
                in (
                    "win_pct",
                    "ann_ror",
                    "max_dd",
                    "avg_d",
                    "median_d",
                    "avg_pnl_pct",
                    "avg_pnl_pct_wo_max",
                    "expectancy_pct",
                    "avg_win_pct",
                    "avg_loss_pct",
                    "two_d_from_avg_d",
                    "median_mfe_180",
                    "mean_mfe_180",
                    "median_mfe_ever",
                    "mean_mfe_ever",
                )
            ):
                tds.append(f"<td>{_fmt_pct(v)}</td>")
            elif typ == "num" and key in (
                "calmar",
                "sharpe",
                "profit_factor",
                "win_loss_count_ratio",
                "avg_positions",
                "median_positions",
            ):
                tds.append(f"<td>{_fmt_num(v, 2)}</td>")
            elif typ == "num" and key in (
                "n",
                "n_trades",
                "n_wins",
                "n_losses",
                "n_target",
                "n_stop",
                "n_time",
                "n_open",
                "n_names",
                "losing_streak",
                "max_positions",
                "median_mfe_180_ge_2d",
                "mean_mfe_180_ge_2d",
            ):
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


def _write_baseline(
    path: Path,
    *,
    ohlc_start: str,
    ohlc_end: str,
    n_names: int,
    n_aths: int,
    n_trough: int,
    pick_d: float,
    pick_why: str,
    trough_head: dict[str, Any],
    ft_head: dict[str, Any],
    books: pd.DataFrame,
    verdicts: dict[str, str],
) -> None:
    def _row(arm: str, sl: str) -> dict[str, Any]:
        sub = books[(books["arm"] == arm) & (books["slice"] == sl)]
        return sub.iloc[0].to_dict() if len(sub) else {}

    lines = [
        f"# BASELINE — {STAMP_ID}",
        "",
        "**Status:** Research 2×-drop ledger + ≤6 one-knob overlays. **Not gold. Not DailyRun.** No adopt.",
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
        f"- **Parent stamp:** `{PRIOR_ID}` (same ever-top-50 universe, closing sample ATH, trough = lowest Low after the high).",
        f"- **Sibling (do not overwrite):** `{SIBLING_ID}` first-touch 3.72% path study. Same OHLC / names; this stamp is a new folder.",
        "- **Universe:** names ever in the annual approx-mcap top 50 on today's Wikipedia S&P 500 ∩ local DuckDB, years 2011–2026. Survivorship + scaled-now mcaps inherited.",
        "- **ATH:** new **closing** high in the local sample (usually 2010-01-04 or IPO). Not a 52-week high.",
        "- **D (eventual):** `(ATH_close − trough_low) / ATH_close × 100`. Trough = parent lowest Low in (ATH, next ATH] or through last bar if still open.",
        "- **Regain 2× from trough:** first later **High** ≥ `trough_low × (1 + 2D/100)`. Labeled High-tag. Close-tag is also stored (harder). This is a measured move / 2R from the low, **not** a return to the old ATH (~1× D from the low, ignoring the high-to-low vs close-to-low gap).",
        "- **Regain 2× from first-touch:** first later **High** ≥ `trigger_level × (1 + 2D/100)` after the first Low that is D% below the ATH close. Harder / different — you are not assumed to buy the exact bottom.",
        "- **Headline window for “does the typical bounce ≥ 2D”:** 180 calendar days of High MFE from the trough (or from first-touch). “Ever” is also reported; mega-caps that later 5–10× will inflate ever-MFE on old events. 20 / 60 / 365d hit-rates are in the table.",
        f"- **OHLC window:** {ohlc_start} → {ohlc_end}.",
        "- **IS / OOS (overlays only):** IS = `trigger_date < 2024-01-01`; OOS = `trigger_date ≥ 2024-01-01` (report-only; do not retune).",
        "- **AB universe / bars:** same top-50-ever names, daily DuckDB bars. One open position per symbol (skip a new ATH while a trade is open).",
        f"- **Control:** `ctrl_372_1x_ath` — buy first-touch **{DROP_372}%** (Low), target = first Close above the old ATH, stop = extra **1.0 × D** below the trigger. No time-stop. $10,000 sheet notional; Max DD / Sharpe seed $500,000. Costs = 0. Same-bar Low through the stop = STOP first.",
        "- **Candidates (one knob vs freeze):** (1) same 3.72 entry, target **+2D from entry** instead of old ATH; (2) first-touch of the selected “2× works” D, target +2D from entry, stop 1.0D; (3–4) that same D / +2D entry, stop **0.5D** and **1.5D**. Context rows: no-trade, SPY buy-and-hold, SPY paired on control dates.",
        f"- **Selected D for the D/stop knobs:** **{pick_d:g}%** — {pick_why}. Choosing D after the full-sample 2× table is **in-sample selection**; IS/OOS below are re-reported under this freeze. Research only.",
        "- **Not DailyRun. Not gold.** +2D from the *eventual trough* as a live target is look-ahead (you do not know the trough until later) — not an AB arm.",
        "",
        "## Counts",
        "",
        f"- Names: **{n_names}**",
        f"- Parent closing ATH events: **{n_aths}**",
        f"- Trough events with D>0 scored for 2×: **{n_trough}**",
        "",
        "## Headline — 2× from the trough (High tag)",
        "",
        f"- Smallest / featured eventual-drop bucket where median 180d MFE ≥ 2× avg D: see `bucket_trough_2x.csv` / HTML.",
        f"- Across all D>0 troughs: N={trough_head.get('n')}, avg D={trough_head.get('avg_d')}, "
        f"% hit 2× ever={trough_head.get('pct_hit_2x_ever')}, % never={trough_head.get('pct_never_2x')}, "
        f"median / avg days to 2× (hits)={trough_head.get('median_days_to_2x')} / {trough_head.get('avg_days_to_2x')}, "
        f"% hit 2× within 180d={trough_head.get('pct_hit_2x_180d')}.",
        f"- First-touch 3.72% (sibling cutoff): N={ft_head.get('n')}, % hit 2× ever={ft_head.get('pct_hit_2x_ever')}, "
        f"% never={ft_head.get('pct_never_2x')}, median days (hits)={ft_head.get('median_days_to_2x')}, "
        f"median 180d MFE={ft_head.get('median_mfe_180')} vs 2D={ft_head.get('two_d_from_avg_d')}.",
        "",
        "## Overlay vs control (research only)",
        "",
        "Judge quality (win%, Avg PnL%, expectancy, PF, Ann ROR, Max DD, Calmar, Sharpe), not trade count. OOS report-only. HOLD if OOS softens.",
        "",
    ]
    for arm in (
        "no_trade",
        "spy_bh",
        "spy_paired_ctrl",
        "ctrl_372_1x_ath",
        "d372_2x_entry_s1",
        "dsel_2x_entry_s1",
        "dsel_2x_entry_s05",
        "dsel_2x_entry_s15",
    ):
        isr, oosr = _row(arm, "IS"), _row(arm, "OOS")
        lines.append(
            f"- `{arm}` verdict **{verdicts.get(arm, '')}** — "
            f"IS N={isr.get('n_trades')} WR={isr.get('win_pct')} AvgPnL%={isr.get('avg_pnl_pct')} "
            f"PF={isr.get('profit_factor')} AnnROR={isr.get('ann_ror')} MaxDD={isr.get('max_dd')}; "
            f"OOS N={oosr.get('n_trades')} WR={oosr.get('win_pct')} AvgPnL%={oosr.get('avg_pnl_pct')} "
            f"PF={oosr.get('profit_factor')} AnnROR={oosr.get('ann_ror')} MaxDD={oosr.get('max_dd')}."
        )
    lines += [
        "",
        "## Honesty / selection",
        "",
        "- 2× High-tag is optimistic versus a Close-tag (intrabar). Both are in the CSVs.",
        "- 180d MFE is the fair “subsequent rally” window. Ever-MFE on 2010 events is dominated by later mega-cap trends — do not read that as a 2-week edge.",
        "- First-touch limit at exactly D% is optimistic when the trigger bar gaps through (`same_bar_through`).",
        "- Same-bar stop-first is conservative; real gaps can be worse.",
        "- D for the stop/D knobs was chosen after seeing the full-sample 2× first-touch table (selection bias). Frozen after that look; OOS not used to retune.",
        "- Control 3.72% is the parent pause-2+ trading-day median drop (same as the sibling), not a fitted optimum.",
        "- No Paul Score / FIT / robust FIT (closed overlay; no host Summary).",
        "- Survivorship; sample ATH from 2010; dividends ignored; no costs.",
        "- OOS softens → HOLD, do not retune D / stop / target on 2024+.",
        "",
        "## Verdict",
        "",
        "**Research only.** See HTML verdict column. **Not gold. Not DailyRun.** Do not wire DailyRun.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_hypothesis(path: Path, pick_d: float, pick_why: str) -> None:
    path.write_text(
        f"""# HYPOTHESIS — {STAMP_ID}

Research. **None of these is gold / DailyRun.**

| Field | Fill |
|-------|------|
| System / prefix | Top-50 closing-ATH 2×-drop (parent `{PRIOR_ID}`) |
| Evidence | Parent ATH ledger; sibling `{SIBLING_ID}` first-touch 3.72% (do not overwrite) |
| Single knobs | Target (ATH vs +2D from entry); D (3.72 vs selected); stop extra (0.5D / 1.0D / 1.5D) |
| Frozen | Universe + closing ATH + Low first-touch + daily bars + $10k + no time-stop + one position / symbol |
| Selected D | {pick_d:g}% — {pick_why} |
| IS / OOS | trigger_date < 2024-01-01 / ≥ 2024-01-01 (OOS report-only) |
| Control | `ctrl_372_1x_ath` (and no-trade / SPY context) |

Judge quality not count. OOS report-only. HOLD if OOS softens.
""",
        encoding="utf-8",
    )


def _write_html(
    path: Path,
    *,
    trough_buckets: pd.DataFrame,
    ft_buckets: pd.DataFrame,
    books: pd.DataFrame,
    deltas: pd.DataFrame,
    trough_head: dict[str, Any],
    ft372: dict[str, Any],
    pick_d: float,
    pick_why: str,
    smallest_trough: dict[str, Any] | None,
    smallest_ft: dict[str, Any] | None,
    verdicts: dict[str, str],
    ohlc_start: str,
    ohlc_end: str,
    n_names: int,
    n_aths: int,
) -> None:
    cards = [
        (
            "Avg D (all troughs D>0)",
            _fmt_pct(trough_head.get("avg_d")),
            f"Median D {_fmt_pct(trough_head.get('median_d'))} · N={_fmt_int(trough_head.get('n'))}",
        ),
        (
            "% hit 2× from trough (ever / 180d)",
            f"{_fmt_pct(trough_head.get('pct_hit_2x_ever'))} / {_fmt_pct(trough_head.get('pct_hit_2x_180d'))}",
            f"Never 2× {_fmt_pct(trough_head.get('pct_never_2x'))} · High tag",
        ),
        (
            "Days trough → 2× (med / avg)",
            f"{_fmt_num(trough_head.get('median_days_to_2x'), 1)} / {_fmt_num(trough_head.get('avg_days_to_2x'), 1)}",
            "Hits only · calendar days",
        ),
        (
            "First-touch 3.72% → 2× (ever / 180d)",
            f"{_fmt_pct(ft372.get('pct_hit_2x_ever'))} / {_fmt_pct(ft372.get('pct_hit_2x_180d'))}",
            f"Med days {_fmt_num(ft372.get('median_days_to_2x'), 1)} · from the 3.72% line, not the bottom",
        ),
        (
            "Smallest trough bucket median≥2D (180d)",
            (smallest_trough or {}).get("bucket") or "None",
            f"Avg D {_fmt_pct((smallest_trough or {}).get('avg_d'))} · med 180d MFE {_fmt_pct((smallest_trough or {}).get('median_mfe_180'))}",
        ),
        (
            "Smallest first-touch D median≥2D (180d)",
            (smallest_ft or {}).get("bucket") or "None",
            f"Med days {_fmt_num((smallest_ft or {}).get('median_days_to_2x'), 1)} · { _esc(pick_why) }",
        ),
        (
            "AB selected D",
            f"{pick_d:g}%",
            "D/stop knobs. In-sample look at the 2× table; OOS report-only.",
        ),
        (
            "Names / parent ATHs",
            f"{_fmt_int(n_names)} / {_fmt_int(n_aths)}",
            f"OHLC {ohlc_start} → {ohlc_end}",
        ),
    ]
    card_html = "".join(
        f'<div class="card"><h3>{_esc(t)}</h3><div class="metric">{m}</div><div class="small">{_esc(n)}</div></div>'
        for t, m, n in cards
    )

    bucket_cols = [
        ("Bucket", "text", "bucket"),
        ("Basis", "text", "basis"),
        ("N", "num", "n"),
        ("N names", "num", "n_names"),
        ("Avg D", "num", "avg_d"),
        ("Med D", "num", "median_d"),
        ("2D (from avg D)", "num", "two_d_from_avg_d"),
        ("% hit 2× ever", "num", "pct_hit_2x_ever"),
        ("% hit 2× 20d", "num", "pct_hit_2x_20d"),
        ("% hit 2× 60d", "num", "pct_hit_2x_60d"),
        ("% hit 2× 180d", "num", "pct_hit_2x_180d"),
        ("% hit 2× 365d", "num", "pct_hit_2x_365d"),
        ("% never 2× (open)", "num", "pct_never_2x"),
        ("% hit 2× Close ever", "num", "pct_hit_2x_close_ever"),
        ("Avg days to 2×", "num", "avg_days_to_2x"),
        ("Med days to 2×", "num", "median_days_to_2x"),
        ("P90 days to 2×", "num", "p90_days_to_2x"),
        ("Med days (180d hits)", "num", "median_days_to_2x_180"),
        ("Med MFE 180d", "num", "median_mfe_180"),
        ("Mean MFE 180d", "num", "mean_mfe_180"),
        ("Med MFE ever", "num", "median_mfe_ever"),
        ("Mean MFE ever", "num", "mean_mfe_ever"),
        ("Med 180d ≥ 2D?", "num", "median_mfe_180_ge_2d"),
        ("Mean 180d ≥ 2D?", "num", "mean_mfe_180_ge_2d"),
        ("Note", "text", "note"),
    ]
    book_cols = [
        ("Arm", "text", "arm"),
        ("Slice", "text", "slice"),
        ("Verdict", "text", "verdict"),
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
        ("Losing streak", "num", "losing_streak"),
        ("Avg positions", "num", "avg_positions"),
        ("Med positions", "num", "median_positions"),
        ("Max positions", "num", "max_positions"),
        ("N TARGET", "num", "n_target"),
        ("% TARGET", "num", "pct_target"),
        ("N STOP", "num", "n_stop"),
        ("% STOP", "num", "pct_stop"),
        ("N TIME", "num", "n_time"),
        ("% TIME", "num", "pct_time"),
        ("N OPEN", "num", "n_open"),
        ("% OPEN", "num", "pct_open"),
        ("Paul / FIT / robust FIT", "text", "fit_label"),
        ("Note", "text", "note"),
    ]
    delta_cols = [
        ("Arm", "text", "arm"),
        ("Slice", "text", "slice"),
        ("Verdict", "text", "verdict"),
        ("Δ N", "num", "d_n_trades"),
        ("Δ Win %", "num", "d_win_pct"),
        ("Δ Avg PnL %", "num", "d_avg_pnl_pct"),
        ("Δ WO_MAX %", "num", "d_avg_pnl_pct_wo_max"),
        ("Δ PF", "num", "d_profit_factor"),
        ("Δ Ann ROR %", "num", "d_ann_ror"),
        ("Δ Max DD %", "num", "d_max_dd"),
        ("Δ Calmar", "num", "d_calmar"),
        ("Δ Sharpe", "num", "d_sharpe"),
        ("Δ expectancy $", "num", "d_expectancy_d"),
        ("Δ profit / cap day", "num", "d_profit_per_capital_day"),
        ("Δ avg days", "num", "d_avg_days_held"),
    ]

    show_books = books.copy()
    show_books["fit_label"] = "N/A (closed overlay; no host Summary)"
    show_books["verdict"] = show_books["arm"].map(lambda a: verdicts.get(str(a), ""))
    show_deltas = deltas.copy()
    show_deltas["verdict"] = show_deltas["arm"].map(lambda a: verdicts.get(str(a), ""))

    vtxt = "; ".join(f"{k}={v}" for k, v in verdicts.items() if k not in ("no_trade", "spy_bh"))

    def _bkt(df: pd.DataFrame, name: str) -> dict[str, Any]:
        sub = df[df["bucket"] == name]
        return sub.iloc[0].to_dict() if len(sub) else {}

    b23 = _bkt(trough_buckets, "2–3%")
    b812 = _bkt(trough_buckets, "8–12%")
    b12 = _bkt(trough_buckets, "12%+")
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>2× ATH drop + AB — {STAMP_ID}</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 24px; color: #0f172a; background: #f8fafc; }}
h1 {{ font-size: 1.45rem; margin: 0 0 4px; }}
h2 {{ font-size: 1.15rem; margin: 1.6rem 0 .5rem; border-bottom: 1px solid #cbd5e1; padding-bottom: .25rem; }}
.sub, .meta {{ color: #475569; font-size: .92rem; max-width: 76rem; line-height: 1.5; }}
.callout {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .85rem 1rem; margin: .75rem 0; max-width: 76rem; }}
.cards {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0 24px; }}
.card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px 16px; min-width: 200px; flex: 1 1 210px; }}
.card h3 {{ margin: 0 0 8px; font-size: 13px; color: #475569; }}
.metric {{ font-size: 1.2rem; font-weight: 700; line-height: 1.25; }}
.small {{ font-size: 12px; color: #64748b; }}
.muted {{ color: #94a3b8; }}
.table-wrap {{ overflow-x: auto; margin: 8px 0; }}
table.sortable {{ border-collapse: collapse; background: #fff; font-size: 12px; width: 100%; }}
table.sortable th, table.sortable td {{ border: 1px solid #e2e8f0; padding: 6px 8px; text-align: left; vertical-align: top; }}
table.sortable th {{ background: #f1f5f9; }}
tr.total-row td {{ background: #e0f2fe; font-weight: 600; }}
tr.ctrl td {{ background: #f1f5f9; }}
tr.keep td {{ background: #ecfdf5; }}
tr.hold td {{ background: #fffbeb; }}
tr.dismiss td {{ background: #fef2f2; }}
{spx.SORTABLE_TH_CSS}
</style></head><body>
<h1>When does a top-50 ATH pullback regain 2× the drop? — 2026-09-16</h1>
<p class="sub">Research only. Not gold. Not DailyRun. Stamp <code>{STAMP_ID}</code>.
Parent <code>{PRIOR_ID}</code>. Sibling first-touch 3.72% path <code>{SIBLING_ID}</code> was not overwritten.
OHLC {_esc(ohlc_start)} → {_esc(ohlc_end)}. Click column headers to sort.</p>
<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
<p>{_esc(ORIGINAL_REQUEST)}</p>
<h2>In plain English</h2>
<p>{_esc(LAYMAN)}</p>
</div>
<div class="cards">{card_html}</div>
<div class="callout">
<h2 style="margin-top:0">Answer — at what drop does 2× show up, and how many days?</h2>
<p><strong>From the trough (High tag).</strong> The typical bounce already covers 2× D in the <em>smallest</em> bucket we measured: <strong>2–3%</strong> (avg D {_fmt_pct(b23.get('avg_d'))}, median <strong>{_fmt_num(b23.get('median_days_to_2x'), 0)} calendar days</strong> to 2×). Stair-step ATHs (all D&gt;0) look even faster (median {_fmt_num(trough_head.get('median_days_to_2x'), 0)} days) because a 1% dip only needs a 2% bounce. The <em>largest</em> eventual-drop bucket where the median 180-day rally still reaches 2× D is <strong>8–12%</strong> (avg D {_fmt_pct(b812.get('avg_d'))}, median <strong>{_fmt_num(b812.get('median_days_to_2x'), 0)} days</strong>). At <strong>12%+</strong> (avg D {_fmt_pct(b12.get('avg_d'))}) the median 180-day bounce ({_fmt_pct(b12.get('median_mfe_180'))}) no longer reaches 2× ({_fmt_pct(b12.get('two_d_from_avg_d'))}); {_fmt_pct(b12.get('pct_never_2x'))} never tag 2× before the sample ends.</p>
<p><strong>From first-touch of D% (harder).</strong> +2D from the trigger line, not from a later lower low. Median 180-day High MFE ≥ 2D from first-touch <strong>2% through 6%</strong>. At the sibling <strong>3.72%</strong> line: {_fmt_pct(ft372.get('pct_hit_2x_180d'))} hit 2× within 180 days (median {_fmt_num(ft372.get('median_days_to_2x_180'), 1)} days among those hits; {_fmt_num(ft372.get('median_days_to_2x'), 1)} days among all ever-hits); {_fmt_pct(ft372.get('pct_never_2x'))} never. First-touch <strong>8%+</strong> fails the median-180d ≥ 2D test (you need a +16% bounce off an 8% line; the typical 180-day bounce is about 15.5%).</p>
<p><strong>Systems.</strong> No KEEP for live / DailyRun. Overlays are HOLD (tiny Avg PnL%, win-rate cost when targeting 2×, stop-distance shopping, or worse Max DD). See the A/B table.</p>
</div>

<h2>What 2× the drop means</h2>
<ul class="meta">
<li><strong>From the trough</strong> — after a closing all-time high (ATH), D% is high-close → lowest Low. 2× is a rally of 2×D from that low (High first tags <code>trough × (1+2D)</code>). Getting back to the old high is only about 1× D from the low.</li>
<li><strong>From first-touch of D%</strong> — the first bar whose Low is already D% below the ATH close. 2× is +2D from that <em>trigger line</em>, not from a later lower low. Harder if the first-touch bar already washed through, and different because you are not assumed to buy the exact bottom.</li>
<li><strong>Open / never</strong> — the High never reached the 2× tag before the last local bar.</li>
<li><strong>180-day window</strong> — used to judge whether the <em>typical</em> bounce is ≥ 2D without giving 2010 names credit for a decade of later mega-cap trend. Ever / 20 / 60 / 365 are also in the table.</li>
</ul>

<h2>Drop bucket → 2× (trough, then first-touch)</h2>
<p class="small">Event-equal. Trough rows use the parent’s eventual D. First-touch rows use a fixed D threshold (3.72 matches the sibling cutoff). Click headers to sort.</p>
{_table(trough_buckets, bucket_cols)}
<h3>First-touch of D% → bounce ≥ 2× D from the trigger</h3>
{_table(ft_buckets, bucket_cols)}
<p class="small">Selected AB D = <strong>{pick_d:g}%</strong>. {_esc(pick_why)}</p>

<h2>A/B overlays (≤6 one-knob arms)</h2>
<p class="small">Control = buy first-touch 3.72%, exit at the old ATH close (~1×), stop extra 1.0×D.
Candidates change one knob: target (ATH → +2D from entry), D (3.72 → selected), or stop extra (0.5D / 1.0D / 1.5D).
Context: no-trade, SPY buy-and-hold (one hold over the sample), SPY paired on the control’s dates.
$10,000 sheet notional / trade; Ann ROR uses that cash; Max DD / Sharpe seed $500,000 on exit-date equity
(no daily curve — Sharpe is closed-exit-date, not √252). Costs = 0. IS = trigger before 2024-01-01;
OOS = 2024+ report-only. Total / sheet PnL $ omitted. Click headers to sort. Verdicts: { _esc(vtxt) }.</p>
{_table(show_books, book_cols, row_class_key="verdict")}
<h3>Deltas vs <code>ctrl_372_1x_ath</code> (same slice)</h3>
<p class="small">Max DD Δ: negative = smaller drawdown (better). Quality over count. HOLD if OOS softens — do not retune.</p>
{_table(show_deltas, delta_cols, row_class_key="verdict")}

<h2>Definitions</h2>
<ul class="meta">
<li><strong>ATH</strong> — all-time high: new closing high in the local sample. Not a 52-week high.</li>
<li><strong>S&amp;P 500</strong> — Standard &amp; Poor's 500. Today's Wikipedia list projected backward (survivorship), then annual top 50 by approx market cap.</li>
<li><strong>SPY</strong> — the S&amp;P 500 exchange-traded fund used as buy-and-hold / paired context.</li>
<li><strong>2× the drop</strong> — measured move / 2R from the trough or from the first-touch line; not a return to the old high.</li>
<li><strong>IS / OOS</strong> — overlays only. In-sample triggers before 2024-01-01; 2024+ is report-only.</li>
</ul>
<p class="meta">Caveats: survivorship; sample starts 2010; dividends ignored; High-tag is optimistic vs Close; D for stop/D knobs was chosen after the full-sample 2× table (selection labeled). See <a href="BASELINE.md">BASELINE.md</a>.</p>
<script>
{spx.SORTABLE_TABLE_SCRIPT}
</script>
</body></html>
"""
    path.write_text(html, encoding="utf-8")


def _delta_row(arm: dict[str, Any], ctrl: dict[str, Any]) -> dict[str, Any]:
    def d(key: str) -> float | None:
        a, c = arm.get(key), ctrl.get(key)
        if a is None or c is None:
            return None
        try:
            fa, fc = float(a), float(c)
        except (TypeError, ValueError):
            return None
        if not np.isfinite(fa) or not np.isfinite(fc):
            return None
        return fa - fc

    return {
        "arm": arm.get("arm"),
        "slice": arm.get("slice"),
        "d_n_trades": d("n_trades"),
        "d_win_pct": d("win_pct"),
        "d_avg_pnl_pct": d("avg_pnl_pct"),
        "d_avg_pnl_pct_wo_max": d("avg_pnl_pct_wo_max"),
        "d_profit_factor": d("profit_factor"),
        "d_ann_ror": d("ann_ror"),
        "d_max_dd": d("max_dd"),
        "d_calmar": d("calmar"),
        "d_sharpe": d("sharpe"),
        "d_expectancy_d": d("expectancy_d"),
        "d_profit_per_capital_day": d("profit_per_capital_day"),
        "d_avg_days_held": d("avg_days_held"),
    }


def main() -> int:
    t0 = time.time()
    STAMP_DIR.mkdir(parents=True, exist_ok=True)
    if SIBLING_ID in str(STAMP_DIR):
        raise RuntimeError("refusing to write into sibling stamp")
    print("[2x] loading parent events + OHLC...", flush=True)
    prior = _load_prior_events()
    ever = sorted(prior["symbol"].unique())
    raw = ath._load_ohlc(sorted(set(ever) | {"SPY"}))
    raw_by = {s: g for s, g in raw.groupby("symbol", sort=False)}
    spy = raw_by.get("SPY", pd.DataFrame())

    trough_rows: list[dict[str, Any]] = []
    ft_rows: list[dict[str, Any]] = []
    for i, sym in enumerate(ever, 1):
        frame = raw_by.get(sym)
        evs = prior[prior["symbol"] == sym]
        if frame is None or frame.empty or evs.empty:
            print(f"[2x] skip {sym}: no OHLC/events", flush=True)
            continue
        trough_rows.extend(_trough_2x_for_symbol(sym, frame, evs))
        ft_rows.extend(_first_touch_2x_for_symbol(sym, frame, evs, FT_THRESHOLDS))
        if i % 20 == 0 or i == len(ever):
            print(
                f"[2x] scored {i}/{len(ever)} names, {len(trough_rows)} trough-2x, {len(ft_rows)} first-touch",
                flush=True,
            )

    trough_df = pd.DataFrame(trough_rows)
    ft_df = pd.DataFrame(ft_rows)
    if trough_df.empty:
        raise RuntimeError("No trough 2× rows")

    trough_bucket_rows = [
        _agg_trough_bucket(
            trough_df,
            "ALL D>0 (event-equal)",
            "Every parent trough with a positive % drop. Stair-step ATHs dominate.",
        )
    ]
    for lab, lo, hi in TROUGH_BUCKETS:
        if hi >= 1e8:
            sub = trough_df[(trough_df["pct_drop"] >= lo)]
        else:
            sub = trough_df[(trough_df["pct_drop"] >= lo) & (trough_df["pct_drop"] < hi)]
        note = f"Eventual trough D in [{lo:g}, {hi:g}). High-tag 2× from the trough."
        trough_bucket_rows.append(_agg_trough_bucket(sub, lab, note))
    trough_buckets = pd.DataFrame(trough_bucket_rows)

    ft_bucket_rows = []
    for d in FT_THRESHOLDS:
        sub = ft_df[np.isclose(ft_df["d_pct"].to_numpy(dtype=float), d)]
        ft_bucket_rows.append(_agg_ft_bucket(sub, d))
    ft_buckets = pd.DataFrame(ft_bucket_rows)

    trough_head = trough_bucket_rows[0]
    ft372 = next((r for r in ft_bucket_rows if abs(float(r["avg_d"]) - DROP_372) < 1e-9), ft_bucket_rows[0])
    smallest_trough = None
    for r in trough_bucket_rows[1:]:
        if int(r.get("n") or 0) >= 80 and int(r.get("median_mfe_180_ge_2d") or 0) == 1:
            smallest_trough = r
            break
    smallest_ft = None
    for r in sorted(ft_bucket_rows, key=lambda x: float(x["avg_d"])):
        if int(r.get("n") or 0) >= 80 and int(r.get("median_mfe_180_ge_2d") or 0) == 1:
            smallest_ft = r
            break
    pick_d, pick_why = _pick_working_d(ft_bucket_rows)
    if pick_d <= 4.0 + 1e-9:
        # 3.72 already works; 4% is not a meaningful D-knob. Use the parent 5%+ slice.
        pick_d = 5.0
        pick_why = (
            "First-touch 3.72% (and 4%) already have median 180d High MFE >= 2D. "
            "D-knob frozen at 5% (parent material-drop / 5-8 bucket), one change vs 3.72. "
            "Not a silent 4% tweak. " + pick_why
        )

    print(f"[2x] selected D={pick_d:g} — {pick_why}", flush=True)
    print("[2x] simulating overlays...", flush=True)

    arm_specs = [
        (
            "ctrl_372_1x_ath",
            DROP_372,
            "ath_close",
            1.0,
            "CONTROL: first-touch 3.72%; target = Close > old ATH (~1×); stop extra 1.0D.",
        ),
        (
            "d372_2x_entry_s1",
            DROP_372,
            "two_d_entry",
            1.0,
            "Knob=target: same 3.72 first-touch / stop 1.0D; target = +2D from entry (High).",
        ),
        (
            "dsel_2x_entry_s1",
            pick_d,
            "two_d_entry",
            1.0,
            f"Knob=D: first-touch {pick_d:g}%; target +2D from entry; stop extra 1.0D.",
        ),
        (
            "dsel_2x_entry_s05",
            pick_d,
            "two_d_entry",
            0.5,
            f"Knob=stop: first-touch {pick_d:g}% / +2D from entry; stop extra 0.5D.",
        ),
        (
            "dsel_2x_entry_s15",
            pick_d,
            "two_d_entry",
            1.5,
            f"Knob=stop: first-touch {pick_d:g}% / +2D from entry; stop extra 1.5D.",
        ),
    ]
    trades_by_arm: dict[str, list[dict[str, Any]]] = {k: [] for k, *_ in arm_specs}
    notes = {k: n for k, *_rest, n in ((a, d, t, s, n) for a, d, t, s, n in arm_specs)}
    for i, sym in enumerate(ever, 1):
        frame = raw_by.get(sym)
        evs = prior[prior["symbol"] == sym]
        if frame is None or frame.empty or evs.empty:
            continue
        dates, close, low, high, date_to_i = _prep_ohlc(frame)
        for arm, d_pct, target, stop_mult, _note in arm_specs:
            trades_by_arm[arm].extend(
                _simulate_trades(
                    sym,
                    dates,
                    close,
                    low,
                    high,
                    date_to_i,
                    evs,
                    d_pct=d_pct,
                    target=target,
                    stop_mult=stop_mult,
                    arm=arm,
                )
            )
        if i % 25 == 0 or i == len(ever):
            print(f"[2x] overlay {i}/{len(ever)}", flush=True)

    spy_paired = _spy_paired(trades_by_arm["ctrl_372_1x_ath"], spy)
    spy_bh = _spy_bh(spy)
    trades_by_arm["spy_paired_ctrl"] = spy_paired
    trades_by_arm["spy_bh"] = spy_bh
    trades_by_arm["no_trade"] = []
    notes["spy_paired_ctrl"] = "Context: SPY close on the control’s trigger/exit dates (paired hold)."
    notes["spy_bh"] = "Context: buy SPY on the first local bar, hold to the last bar (one trade)."
    notes["no_trade"] = "Control/context: do nothing (cash)."

    book_rows: list[dict[str, Any]] = []
    book_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    arm_order = [
        "no_trade",
        "spy_bh",
        "spy_paired_ctrl",
        "ctrl_372_1x_ath",
        "d372_2x_entry_s1",
        "dsel_2x_entry_s1",
        "dsel_2x_entry_s05",
        "dsel_2x_entry_s15",
    ]
    for arm in arm_order:
        rows = trades_by_arm.get(arm, [])
        if arm == "spy_bh":
            slices = [("FULL", rows)]
        else:
            is_tr = [t for t in rows if pd.Timestamp(t["trigger_date"]) < IS_CUT]
            oos_tr = [t for t in rows if pd.Timestamp(t["trigger_date"]) >= IS_CUT]
            slices = [("FULL", rows), ("IS", is_tr), ("OOS", oos_tr)]
        for sl, chunk in slices:
            rec = _book_metrics(chunk, label=arm, note=notes.get(arm, ""))
            rec["slice"] = sl
            book_rows.append(rec)
            book_lookup[(arm, sl)] = rec

    verdicts = {arm: _verdict_for(arm, book_lookup) for arm in arm_order}
    for rec in book_rows:
        rec["verdict"] = verdicts.get(str(rec["arm"]), "")

    books = pd.DataFrame(book_rows)
    delta_rows = []
    for rec in book_rows:
        arm, sl = rec["arm"], rec["slice"]
        if arm in ("no_trade", "spy_bh", "ctrl_372_1x_ath"):
            continue
        ctrl_sl = sl if sl != "FULL" or ("ctrl_372_1x_ath", "FULL") in book_lookup else "IS"
        ctrl = book_lookup.get(("ctrl_372_1x_ath", sl)) or book_lookup.get(("ctrl_372_1x_ath", ctrl_sl))
        if not ctrl:
            continue
        delta_rows.append(_delta_row(rec, ctrl))
    deltas = pd.DataFrame(delta_rows)

    ohlc_start = str(pd.Timestamp(raw["Date"].min()).date())
    ohlc_end = str(pd.Timestamp(raw["Date"].max()).date())

    trough_df.to_csv(STAMP_DIR / "trough_2x_events.csv", index=False)
    ft_df.to_csv(STAMP_DIR / "first_touch_2x_events.csv", index=False)
    trough_buckets.to_csv(STAMP_DIR / "bucket_trough_2x.csv", index=False)
    ft_buckets.to_csv(STAMP_DIR / "bucket_first_touch_2x.csv", index=False)
    books.to_csv(STAMP_DIR / "books.csv", index=False)
    deltas.to_csv(STAMP_DIR / "books_delta_vs_ctrl.csv", index=False)
    all_tr = []
    for arm in arm_order:
        for t in trades_by_arm.get(arm, []):
            row = dict(t)
            row["trigger_date"] = pd.Timestamp(row["trigger_date"]).strftime("%Y-%m-%d")
            row["exit_date"] = pd.Timestamp(row["exit_date"]).strftime("%Y-%m-%d")
            all_tr.append(row)
    pd.DataFrame(all_tr).to_csv(STAMP_DIR / "trades.csv", index=False)

    _write_baseline(
        STAMP_DIR / "BASELINE.md",
        ohlc_start=ohlc_start,
        ohlc_end=ohlc_end,
        n_names=len(ever),
        n_aths=int(len(prior)),
        n_trough=int(len(trough_df)),
        pick_d=pick_d,
        pick_why=pick_why,
        trough_head=trough_head,
        ft_head=ft372,
        books=books,
        verdicts=verdicts,
    )
    _write_hypothesis(STAMP_DIR / "HYPOTHESIS.md", pick_d, pick_why)
    _write_html(
        STAMP_DIR / "report.html",
        trough_buckets=trough_buckets,
        ft_buckets=ft_buckets,
        books=books,
        deltas=deltas,
        trough_head=trough_head,
        ft372=ft372,
        pick_d=pick_d,
        pick_why=pick_why,
        smallest_trough=smallest_trough,
        smallest_ft=smallest_ft,
        verdicts=verdicts,
        ohlc_start=ohlc_start,
        ohlc_end=ohlc_end,
        n_names=len(ever),
        n_aths=int(len(prior)),
    )
    (STAMP_DIR / "compare.html").write_text(
        (STAMP_DIR / "report.html").read_text(encoding="utf-8"), encoding="utf-8"
    )
    summary = {
        "stamp": STAMP_ID,
        "parent": PRIOR_ID,
        "sibling_not_overwritten": SIBLING_ID,
        "ohlc_start": ohlc_start,
        "ohlc_end": ohlc_end,
        "n_names": len(ever),
        "n_aths": int(len(prior)),
        "n_trough_2x": int(len(trough_df)),
        "selected_d": pick_d,
        "selected_d_why": pick_why,
        "trough_all": trough_head,
        "first_touch_372": ft372,
        "smallest_trough_median_ge_2d_180": smallest_trough,
        "smallest_ft_median_ge_2d_180": smallest_ft,
        "verdicts": verdicts,
        "elapsed_sec": time.time() - t0,
        "not_dailyrun": True,
    }
    (STAMP_DIR / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"selected_d": pick_d, "verdicts": verdicts, "trough_all": {
        k: trough_head.get(k)
        for k in (
            "n",
            "avg_d",
            "pct_hit_2x_ever",
            "pct_hit_2x_180d",
            "pct_never_2x",
            "median_days_to_2x",
            "avg_days_to_2x",
        )
    }}, indent=2, default=str), flush=True)
    print(f"[2x] wrote {STAMP_DIR} in {time.time() - t0:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
