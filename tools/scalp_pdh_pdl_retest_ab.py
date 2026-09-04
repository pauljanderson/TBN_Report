#!/usr/bin/env python3
"""Event study: impulse 5m/15m → later PDH/PDL retest on 1m → forward outcomes.

Research only. Not gold. Not DailyRun.

After a directional 5m or 15m impulse candle, measure what happens when price
first revisits prior-day high (PDH) or prior-day low (PDL) on the 1m chart.

Usage:
  python tools/scalp_pdh_pdl_retest_ab.py
  python tools/scalp_pdh_pdl_retest_ab.py --universe paultwenty
  python tools/scalp_pdh_pdl_retest_ab.py --stamp scalp_pdh_pdl_retest_20260904
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import math
import sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock_analysis"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

from intraday_1m import (  # noqa: E402
    DEFAULT_1M_DIR,
    ET,
    read_1m,
    resample_ohlcv,
)
import scalp_open15_reversal_ab as ab  # noqa: E402

DRIVE = ROOT / "drive"
DEFAULT_STAMP = "scalp_pdh_pdl_retest_20260904"
SYSTEM = "scalp"
PAULTWENTY_CSV = DRIVE / "universes" / "PaulTwenty_universe.csv"
CANONICAL_OOS = date(2024, 1, 1)

# --- Freeze (see BASELINE.md) ---
SESSION_OPEN = time(9, 30)
SESSION_CLOSE = time(16, 0)
RETEST_DEADLINE = time(15, 55)
IMPULSE_TFS = ("5m", "15m")
RANGE_FRAC_ATR = 0.25  # impulse (H-L) >= this × prior-close daily ATR
MIN_BODY_FRAC = 0.50  # |C-O| / (H-L) >= this (skip dojis / indecision)
TOUCH_TOL_PCT = 0.05  # touch if bar range overlaps level ± 0.05%
HORIZONS_MIN = (5, 15, 30, 60)  # forward minutes from retest bar
# Primary liquidity-grab framing + secondary return-to-other-level
EVENT_COMBOS = (
    # (impulse_dir, level, label, framing)
    ("up", "PDH", "up_impulse_pdh_retest", "primary"),
    ("down", "PDL", "down_impulse_pdl_retest", "primary"),
    ("up", "PDL", "up_impulse_pdl_retest", "secondary"),
    ("down", "PDH", "down_impulse_pdh_retest", "secondary"),
)

SORT_CSS = ab.SORT_CSS
SORT_JS = ab.SORT_JS


def sortable_th(label: str, sort_type: str) -> str:
    return ab.sortable_th(label, sort_type)


def load_paultwenty() -> list[str]:
    if not PAULTWENTY_CSV.exists():
        return []
    rows = PAULTWENTY_CSV.read_text(encoding="utf-8").strip().splitlines()
    out: list[str] = []
    for line in rows:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.append(s.upper())
    return out


def discover_1m_symbols() -> list[str]:
    return ab.discover_1m_symbols(DEFAULT_1M_DIR)


def prior_day_hl_map(daily: pd.DataFrame) -> dict[date, tuple[float, float]]:
    """Session D → (prior High, prior Low) from daily OHLC. Look-ahead safe."""
    dates = list(daily["Date"])
    highs = list(daily["High"].astype(float))
    lows = list(daily["Low"].astype(float))
    out: dict[date, tuple[float, float]] = {}
    for i in range(1, len(dates)):
        out[dates[i]] = (float(highs[i - 1]), float(lows[i - 1]))
    return out


def _bar_times(df: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(df["ts"], utc=True).dt.tz_convert(ET)


def _tod(ts: Any) -> time:
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize(ET)
    else:
        t = t.tz_convert(ET)
    return t.time().replace(tzinfo=None) if t.tzinfo else t.time()


def is_impulse_bar(
    o: float,
    h: float,
    l: float,
    c: float,
    atr: float,
    want_dir: str,
) -> bool:
    if not all(math.isfinite(x) for x in (o, h, l, c, atr)):
        return False
    if atr <= 0:
        return False
    rng = h - l
    if rng <= 0:
        return False
    if rng < RANGE_FRAC_ATR * atr:
        return False
    body = abs(c - o)
    if body / rng < MIN_BODY_FRAC:
        return False
    if want_dir == "up":
        return c > o
    if want_dir == "down":
        return c < o
    return False


def touches_level(h: float, l: float, level: float, tol_pct: float = TOUCH_TOL_PCT) -> bool:
    if not all(math.isfinite(x) for x in (h, l, level)) or level <= 0:
        return False
    lo = level * (1.0 - tol_pct / 100.0)
    hi = level * (1.0 + tol_pct / 100.0)
    return l <= hi and h >= lo


def find_forward_px(
    day1: pd.DataFrame,
    times: pd.Series,
    start_i: int,
    minutes: int,
) -> tuple[Optional[float], Optional[pd.Timestamp]]:
    """Close of first 1m bar at or after start_ts + minutes."""
    if start_i < 0 or start_i >= len(day1):
        return None, None
    t0 = times.iloc[start_i]
    target = t0 + pd.Timedelta(minutes=minutes)
    for j in range(start_i, len(day1)):
        if times.iloc[j] >= target:
            return float(day1["close"].iloc[j]), times.iloc[j]
    return None, None


def eod_close(day1: pd.DataFrame, times: pd.Series, start_i: int) -> Optional[float]:
    if day1.empty or start_i >= len(day1):
        return None
    # last RTH bar of the session
    return float(day1["close"].iloc[-1])


def path_mfe_mae(
    day1: pd.DataFrame,
    times: pd.Series,
    start_i: int,
    entry: float,
    end_i: int,
    *,
    long_side: bool,
) -> tuple[float, float]:
    """MFE/MAE in % from entry over bars start_i+1 .. end_i inclusive."""
    if not math.isfinite(entry) or entry <= 0 or start_i >= len(day1):
        return float("nan"), float("nan")
    lo_i = start_i + 1
    hi_i = min(end_i, len(day1) - 1)
    if lo_i > hi_i:
        return float("nan"), float("nan")
    highs = day1["high"].iloc[lo_i : hi_i + 1].astype(float).to_numpy()
    lows = day1["low"].iloc[lo_i : hi_i + 1].astype(float).to_numpy()
    if long_side:
        mfe = (float(np.nanmax(highs)) / entry - 1.0) * 100.0
        mae = (float(np.nanmin(lows)) / entry - 1.0) * 100.0
    else:
        mfe = (1.0 - float(np.nanmin(lows)) / entry) * 100.0
        mae = (1.0 - float(np.nanmax(highs)) / entry) * 100.0
    return mfe, mae


def classify_outcome(fwd_ret_pct: Optional[float], *, expect_up_reject: bool) -> str:
    """Label bounce/reject vs break for a horizon return.

    For PDH retest: reject = price falls (negative fwd); break = rises.
    For PDL retest: reject = price rises; break = falls.
    expect_up_reject=True means reject = positive return (bounce off PDL).
    """
    if fwd_ret_pct is None or not math.isfinite(fwd_ret_pct):
        return "na"
    if abs(fwd_ret_pct) < 0.05:
        return "flat"
    up = fwd_ret_pct > 0
    if expect_up_reject:
        return "reject_bounce" if up else "break_through"
    return "reject_bounce" if not up else "break_through"


def scan_symbol(
    sym: str,
    *,
    atr_map: dict[date, float],
    pdhl_map: dict[date, tuple[float, float]],
) -> list[dict[str, Any]]:
    try:
        raw = read_1m(sym, DEFAULT_1M_DIR)
    except Exception:
        return []
    df1 = ab.rth_filter(raw)
    if df1.empty:
        return []
    sessions = ab.session_dates(df1)
    events: list[dict[str, Any]] = []

    # Precompute TF frames once
    tf_frames: dict[str, pd.DataFrame] = {
        "5m": resample_ohlcv(df1, "5min"),
        "15m": resample_ohlcv(df1, "15min"),
    }

    for sess in sessions:
        pdhl = pdhl_map.get(sess)
        atr = atr_map.get(sess)
        if pdhl is None or atr is None or not math.isfinite(atr) or atr <= 0:
            continue
        pdh, pdl = pdhl
        day1 = ab.bars_on_day(df1, sess)
        if len(day1) < 30:
            continue
        t1 = _bar_times(day1)

        for tf in IMPULSE_TFS:
            dtf = tf_frames[tf]
            day_tf = ab.bars_on_day(dtf, sess)
            if day_tf.empty:
                continue
            ttf = _bar_times(day_tf)

            for want_dir, level_name, event_label, framing in EVENT_COMBOS:
                level = pdh if level_name == "PDH" else pdl
                # First qualifying impulse of this direction on this TF/session
                impulse_i = None
                for i in range(len(day_tf)):
                    tod = _tod(ttf.iloc[i])
                    if tod < SESSION_OPEN or tod >= RETEST_DEADLINE:
                        continue
                    # Impulse bar must finish before deadline (left-labeled: end ≈ start+tf)
                    o = float(day_tf["open"].iloc[i])
                    h = float(day_tf["high"].iloc[i])
                    l = float(day_tf["low"].iloc[i])
                    c = float(day_tf["close"].iloc[i])
                    if is_impulse_bar(o, h, l, c, atr, want_dir):
                        impulse_i = i
                        break
                if impulse_i is None:
                    continue

                impulse_end = ttf.iloc[impulse_i] + pd.Timedelta(minutes=5 if tf == "5m" else 15)
                # First 1m bar strictly after impulse completion that touches level
                retest_i = None
                for j in range(len(day1)):
                    if t1.iloc[j] < impulse_end:
                        continue
                    tod = _tod(t1.iloc[j])
                    if tod > RETEST_DEADLINE:
                        break
                    h = float(day1["high"].iloc[j])
                    l = float(day1["low"].iloc[j])
                    if touches_level(h, l, level):
                        retest_i = j
                        break
                if retest_i is None:
                    continue

                entry = float(day1["close"].iloc[retest_i])
                if not math.isfinite(entry) or entry <= 0:
                    continue

                # Require price had moved away from level at impulse close
                # (liquidity-grab / return framing): impulse close on the
                # "away" side for primary combos; still record secondary.
                impulse_c = float(day_tf["close"].iloc[impulse_i])
                away_ok = True
                if framing == "primary":
                    if level_name == "PDH" and want_dir == "up":
                        # After up impulse, prefer retest from above or through
                        # (close of impulse above PDH, or bar traded through PDH)
                        away_ok = impulse_c >= level * (1 - TOUCH_TOL_PCT / 100.0) or float(
                            day_tf["high"].iloc[impulse_i]
                        ) >= level
                    elif level_name == "PDL" and want_dir == "down":
                        away_ok = impulse_c <= level * (1 + TOUCH_TOL_PCT / 100.0) or float(
                            day_tf["low"].iloc[impulse_i]
                        ) <= level
                # Soft gate: keep event even if away_ok False, but flag it
                # (user asked for impulse then return — tag quality)

                # Forward returns (signed % from retest close)
                fwd: dict[str, Any] = {}
                end_idx_60 = retest_i
                for m in HORIZONS_MIN:
                    px, ts_f = find_forward_px(day1, t1, retest_i, m)
                    if px is not None and math.isfinite(px):
                        fwd[f"ret_{m}m"] = (px / entry - 1.0) * 100.0
                        # track index for MAE/MFE window
                        for k in range(retest_i, len(day1)):
                            if t1.iloc[k] >= (t1.iloc[retest_i] + pd.Timedelta(minutes=m)):
                                if m == 60:
                                    end_idx_60 = k
                                break
                    else:
                        fwd[f"ret_{m}m"] = float("nan")

                eod = eod_close(day1, t1, retest_i)
                fwd["ret_eod"] = (
                    (eod / entry - 1.0) * 100.0 if eod is not None and math.isfinite(eod) else float("nan")
                )

                # MAE/MFE over 60m window in "reject" direction
                # PDH retest: reject = short (long_side=False for MFE as downside)
                # PDL retest: reject = long
                expect_up_reject = level_name == "PDL"
                mfe, mae = path_mfe_mae(
                    day1,
                    t1,
                    retest_i,
                    entry,
                    end_idx_60 if end_idx_60 > retest_i else min(retest_i + 60, len(day1) - 1),
                    long_side=expect_up_reject,
                )

                ret15 = fwd.get("ret_15m")
                outcome_15 = classify_outcome(
                    ret15 if isinstance(ret15, float) else None,
                    expect_up_reject=expect_up_reject,
                )
                ret30 = fwd.get("ret_30m")
                outcome_30 = classify_outcome(
                    ret30 if isinstance(ret30, float) else None,
                    expect_up_reject=expect_up_reject,
                )

                events.append(
                    {
                        "symbol": sym,
                        "session": sess.isoformat(),
                        "entry_date": sess.isoformat(),
                        "impulse_tf": tf,
                        "impulse_dir": want_dir,
                        "level": level_name,
                        "event": event_label,
                        "framing": framing,
                        "pdh": round(pdh, 6),
                        "pdl": round(pdl, 6),
                        "level_px": round(level, 6),
                        "atr_prior": round(float(atr), 6),
                        "impulse_ts": str(ttf.iloc[impulse_i]),
                        "impulse_o": round(float(day_tf["open"].iloc[impulse_i]), 6),
                        "impulse_h": round(float(day_tf["high"].iloc[impulse_i]), 6),
                        "impulse_l": round(float(day_tf["low"].iloc[impulse_i]), 6),
                        "impulse_c": round(impulse_c, 6),
                        "impulse_range": round(
                            float(day_tf["high"].iloc[impulse_i]) - float(day_tf["low"].iloc[impulse_i]),
                            6,
                        ),
                        "impulse_range_atr": round(
                            (
                                float(day_tf["high"].iloc[impulse_i])
                                - float(day_tf["low"].iloc[impulse_i])
                            )
                            / atr,
                            4,
                        ),
                        "impulse_body_frac": round(
                            abs(impulse_c - float(day_tf["open"].iloc[impulse_i]))
                            / max(
                                float(day_tf["high"].iloc[impulse_i])
                                - float(day_tf["low"].iloc[impulse_i]),
                                1e-12,
                            ),
                            4,
                        ),
                        "away_flag": 1 if away_ok else 0,
                        "retest_ts": str(t1.iloc[retest_i]),
                        "retest_px": round(entry, 6),
                        "mins_impulse_to_retest": round(
                            (t1.iloc[retest_i] - impulse_end).total_seconds() / 60.0,
                            2,
                        ),
                        **{k: (round(v, 6) if isinstance(v, float) and math.isfinite(v) else "") for k, v in fwd.items()},
                        "mfe_60m_reject_pct": round(mfe, 6) if math.isfinite(mfe) else "",
                        "mae_60m_reject_pct": round(mae, 6) if math.isfinite(mae) else "",
                        "outcome_15m": outcome_15,
                        "outcome_30m": outcome_30,
                    }
                )
    return events


def _finite_list(rows: list[dict[str, Any]], key: str) -> list[float]:
    out: list[float] = []
    for r in rows:
        v = r.get(key)
        if v in ("", None):
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            out.append(f)
    return out


def summarize_slice(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    n = len(rows)
    out: dict[str, Any] = {
        "slice": label,
        "N": n,
        "n_symbols": len({str(r.get("symbol")) for r in rows}),
        "n_sessions": len({str(r.get("session")) for r in rows}),
    }
    for h in ["ret_5m", "ret_15m", "ret_30m", "ret_60m", "ret_eod"]:
        vals = _finite_list(rows, h)
        if not vals:
            out[f"{h}_avg"] = None
            out[f"{h}_med"] = None
            out[f"{h}_wr"] = None  # win = return in reject direction
            continue
        out[f"{h}_avg"] = float(np.mean(vals))
        out[f"{h}_med"] = float(np.median(vals))
        # WR raw: positive return rate (direction-agnostic)
        out[f"{h}_wr_up"] = 100.0 * sum(1 for v in vals if v > 0) / len(vals)

    # Reject-side WR at 15m / 30m (from outcome labels)
    for hk in ("outcome_15m", "outcome_30m"):
        labels = [str(r.get(hk) or "") for r in rows]
        known = [x for x in labels if x in ("reject_bounce", "break_through", "flat")]
        if not known:
            out[f"{hk}_reject_pct"] = None
            out[f"{hk}_break_pct"] = None
            out[f"{hk}_flat_pct"] = None
        else:
            out[f"{hk}_reject_pct"] = 100.0 * sum(1 for x in known if x == "reject_bounce") / len(known)
            out[f"{hk}_break_pct"] = 100.0 * sum(1 for x in known if x == "break_through") / len(known)
            out[f"{hk}_flat_pct"] = 100.0 * sum(1 for x in known if x == "flat") / len(known)

    mfe = _finite_list(rows, "mfe_60m_reject_pct")
    mae = _finite_list(rows, "mae_60m_reject_pct")
    out["mfe_60m_avg"] = float(np.mean(mfe)) if mfe else None
    out["mae_60m_avg"] = float(np.mean(mae)) if mae else None
    lag = _finite_list(rows, "mins_impulse_to_retest")
    out["mins_to_retest_avg"] = float(np.mean(lag)) if lag else None
    out["away_pct"] = (
        100.0 * sum(1 for r in rows if int(r.get("away_flag") or 0) == 1) / n if n else None
    )
    return out


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("note\nno_events\n", encoding="utf-8")
        return
    keys: list[str] = []
    seen: set[str] = set()
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k)
                keys.append(k)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def fmt_num(v: Any, nd: int = 2) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    try:
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return str(v)


def write_baseline(
    path: Path,
    *,
    stamp: str,
    symbols: list[str],
    coverage_note: str,
    n_events: int,
    sess_min: str,
    sess_max: str,
) -> None:
    univ = ", ".join(symbols) if len(symbols) <= 25 else f"n={len(symbols)} symbols"
    text = f"""# BASELINE — Scalp PDH/PDL retest after impulse — `{stamp}`

**System:** `{SYSTEM}` (research only). **Not** DailyRun. **Not** gold.

## User mapping

> Impulse candle in one direction → later reclaim/test of yesterday's high or low on 1m → outcome after test.

Operationalized as: directional **5m or 15m** impulse → first **1m** touch of **PDH or PDL** after impulse completion → forward returns / reject-vs-break labels.

## Freeze

| Knob | Value |
|------|--------|
| Universe | PaulTwenty (`drive/universes/PaulTwenty_universe.csv`): {univ} |
| Session | RTH **09:30–16:00 ET** (`rth_filter`) |
| PDH / PDL | Prior session **High / Low** from daily OHLC (`data/newdata/data/{{SYM}}.csv`); look-ahead safe |
| Daily ATR | Wilder ATR(14) as of **prior close** (same as scalp open15) |
| Impulse TF | **5m** and **15m** separately (resample from 1m, left-labeled) |
| Impulse direction | **Up** = Close > Open; **Down** = Close < Open |
| Impulse size | (High−Low) **≥ {RANGE_FRAC_ATR*100:.0f}%** × prior-close ATR |
| Impulse body | \\|Close−Open\\| / (High−Low) **≥ {MIN_BODY_FRAC:.2f}** (skip dojis) |
| Impulse pick | **First** qualifying impulse of that direction per session × TF × event combo |
| Retest | First **1m** bar **after impulse bar completion** that touches level |
| Touch tolerance | Bar range overlaps level ± **{TOUCH_TOL_PCT:g}%** |
| Retest deadline | ≤ **15:55 ET** same session |
| Entry / mark | Retest bar **close** |
| Forward horizons | **5m, 15m, 30m, 60m**, and **EOD** (last RTH 1m close) |
| Reject definition | **PDH** retest: reject = price **down** after test; **PDL** retest: reject = price **up**. Flat if \\|ret\\| < 0.05% |
| MAE/MFE | Over ~60m path in the reject trade direction |
| Frequency | ≤ 1 event per symbol × session × impulse_tf × event combo |

## Event combos

| Event | Impulse | Level | Framing |
|-------|---------|-------|---------|
| `up_impulse_pdh_retest` | Up | PDH | **Primary** — liquidity / return to prior high after up impulse |
| `down_impulse_pdl_retest` | Down | PDL | **Primary** — return to prior low after down impulse |
| `up_impulse_pdl_retest` | Up | PDL | Secondary — up impulse then revisit PDL |
| `down_impulse_pdh_retest` | Down | PDH | Secondary — down impulse then revisit PDH |

`away_flag=1` when the impulse traded through / closed on the level side consistent with a grab-then-retest for primary combos (descriptive; events kept either way).

## Coverage / honesty

{coverage_note}

- Events this stamp: **N={n_events}**.
- Session span in sample: **{sess_min} → {sess_max}**.
- Research candidate / observational event study only.

## Split

Canonical IS (`entry_date < {CANONICAL_OOS.isoformat()}`) / OOS is **N/A** — Yahoo 1m retention is short and entirely post-2024. Full-sample metrics only; do **not** invent a holdout.
"""
    # Fix stamp name in header if overridden — written by main with actual stamp
    path.write_text(text, encoding="utf-8")


def write_summary(
    path: Path,
    *,
    stamp: str,
    slices: list[dict[str, Any]],
    n_events: int,
    symbols: list[str],
    sess_min: str,
    sess_max: str,
    coverage_note: str,
) -> None:
    # Bottom-line from primary pooled
    primary = next((s for s in slices if s["slice"] == "primary_all"), None)
    all_s = next((s for s in slices if s["slice"] == "all"), None)

    def _verdict(s: Optional[dict[str, Any]]) -> str:
        if not s or not s.get("N"):
            return "No events — cannot judge."
        rj = s.get("outcome_15m_reject_pct")
        br = s.get("outcome_15m_break_pct")
        avg15 = s.get("ret_15m_avg")
        if rj is None or br is None:
            return "Mixed / insufficient outcome labels."
        if rj >= br + 5:
            lean = "lean **reject/bounce** after the test"
        elif br >= rj + 5:
            lean = "lean **break/continuation** through the level"
        else:
            lean = "**mixed** (reject ≈ break within ~5pp)"
        return (
            f"N={s['N']}: {lean} at 15m "
            f"(reject {fmt_num(rj,1)}% vs break {fmt_num(br,1)}%; "
            f"avg ret_15m {fmt_num(avg15,3)}%). "
            "Research-only; short Yahoo window; not KEEP/gold."
        )

    lines = [
        f"# SUMMARY — PDH/PDL retest after impulse — `{stamp}`",
        "",
        f"**Research only.** Universe PaulTwenty ({len(symbols)}). "
        f"Events N={n_events}. Sessions {sess_min} → {sess_max}.",
        "",
        "## Bottom line",
        "",
        f"- **Primary combos (up→PDH, down→PDL):** {_verdict(primary)}",
        f"- **All combos:** {_verdict(all_s)}",
        "",
        "## Coverage",
        "",
        coverage_note,
        "",
        "- Canonical IS/OOS: **N/A** (Yahoo 1m short window, all post-2024).",
        "",
        "## Slice table (key cols)",
        "",
        "| Slice | N | ret_15m avg | ret_15m med | reject% 15m | break% 15m | ret_60m avg | ret_eod avg |",
        "|-------|--:|------------:|------------:|------------:|-----------:|------------:|------------:|",
    ]
    for s in slices:
        lines.append(
            "| {slice} | {N} | {a15} | {m15} | {rj} | {br} | {a60} | {ae} |".format(
                slice=s["slice"],
                N=s["N"],
                a15=fmt_num(s.get("ret_15m_avg"), 3),
                m15=fmt_num(s.get("ret_15m_med"), 3),
                rj=fmt_num(s.get("outcome_15m_reject_pct"), 1),
                br=fmt_num(s.get("outcome_15m_break_pct"), 1),
                a60=fmt_num(s.get("ret_60m_avg"), 3),
                ae=fmt_num(s.get("ret_eod_avg"), 3),
            )
        )
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            "- `compare.html` — sortable tables",
            "- `events.csv` — event-level rows",
            "- `slices.csv` — summary metrics",
            "- `BASELINE.md` — frozen definitions",
            "",
            "**Not** DailyRun. **Not** gold. Do not retune on this short window.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_html(
    path: Path,
    *,
    stamp: str,
    slices: list[dict[str, Any]],
    events: list[dict[str, Any]],
    symbols: list[str],
    coverage_note: str,
    sess_min: str,
    sess_max: str,
) -> None:
    slice_cols = [
        ("slice", "text"),
        ("N", "num"),
        ("n_symbols", "num"),
        ("n_sessions", "num"),
        ("ret_5m_avg", "num"),
        ("ret_15m_avg", "num"),
        ("ret_15m_med", "num"),
        ("ret_15m_wr_up", "num"),
        ("outcome_15m_reject_pct", "num"),
        ("outcome_15m_break_pct", "num"),
        ("outcome_15m_flat_pct", "num"),
        ("ret_30m_avg", "num"),
        ("outcome_30m_reject_pct", "num"),
        ("outcome_30m_break_pct", "num"),
        ("ret_60m_avg", "num"),
        ("ret_eod_avg", "num"),
        ("mfe_60m_avg", "num"),
        ("mae_60m_avg", "num"),
        ("mins_to_retest_avg", "num"),
        ("away_pct", "num"),
    ]
    shead = "".join(sortable_th(c, t) for c, t in slice_cols)
    srows = []
    for s in slices:
        cells = []
        for c, _t in slice_cols:
            v = s.get(c)
            if c == "slice":
                cells.append(f"<td>{html_mod.escape(str(v))}</td>")
            elif c == "N" or c.startswith("n_"):
                cells.append(f"<td>{int(v or 0)}</td>")
            else:
                cells.append(f"<td>{html_mod.escape(fmt_num(v, 3 if 'ret_' in c else 2))}</td>")
        srows.append("<tr>" + "".join(cells) + "</tr>")

    # Event sample table (cap rows for HTML size)
    ev_show = events[:500]
    ev_cols = [
        ("symbol", "text"),
        ("session", "date"),
        ("impulse_tf", "text"),
        ("event", "text"),
        ("framing", "text"),
        ("away_flag", "num"),
        ("impulse_range_atr", "num"),
        ("mins_impulse_to_retest", "num"),
        ("ret_5m", "num"),
        ("ret_15m", "num"),
        ("ret_30m", "num"),
        ("ret_60m", "num"),
        ("ret_eod", "num"),
        ("outcome_15m", "text"),
        ("outcome_30m", "text"),
        ("mfe_60m_reject_pct", "num"),
        ("mae_60m_reject_pct", "num"),
    ]
    ehead = "".join(sortable_th(c, t) for c, t in ev_cols)
    erows = []
    for r in ev_show:
        cells = []
        for c, t in ev_cols:
            v = r.get(c, "")
            if t == "num":
                cells.append(f"<td>{html_mod.escape(fmt_num(v if v != '' else None, 3))}</td>")
            else:
                cells.append(f"<td>{html_mod.escape(str(v))}</td>")
        erows.append("<tr>" + "".join(cells) + "</tr>")

    primary = next((s for s in slices if s["slice"] == "primary_all"), None)
    rj = fmt_num(primary.get("outcome_15m_reject_pct") if primary else None, 1)
    br = fmt_num(primary.get("outcome_15m_break_pct") if primary else None, 1)
    n_p = int(primary["N"]) if primary else 0

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>PDH/PDL retest after impulse — {html_mod.escape(stamp)}</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:24px;color:#0f172a;background:#f8fafc;line-height:1.45}}
h1{{font-size:1.45rem;margin:0 0 8px}}
h2{{font-size:1.15rem;margin:28px 0 10px}}
.meta{{color:#475569;font-size:.95rem;max-width:920px}}
.badge{{display:inline-block;background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:4px;font-size:.85rem;font-weight:600}}
table.sortable{{border-collapse:collapse;width:100%;background:#fff;margin:8px 0 16px;font-size:.9rem}}
table.sortable th,table.sortable td{{border:1px solid #e2e8f0;padding:8px 10px;text-align:left}}
table.sortable th{{background:#f1f5f9}}
.note{{font-size:.9rem;color:#64748b}}
{SORT_CSS}
</style>
</head>
<body>
<p class="badge">Research only · not gold · not DailyRun</p>
<h1>Impulse → PDH/PDL 1m retest — forward outcomes</h1>
<p class="meta">
Stamp <code>{html_mod.escape(stamp)}</code> · PaulTwenty ({len(symbols)}) ·
sessions {html_mod.escape(sess_min)} → {html_mod.escape(sess_max)} ·
events N={len(events)} · primary N={n_p}<br/>
Primary 15m: reject {html_mod.escape(rj)}% vs break {html_mod.escape(br)}%<br/>
{html_mod.escape(coverage_note)}<br/>
Canonical IS/OOS <strong>N/A</strong> (Yahoo 1m short window). Click column headers to sort.
</p>

<h2>Slice summary</h2>
<p class="note">Reject = bounce off level (PDH→down, PDL→up). Break = continuation through.</p>
<table class="sortable">
<thead><tr>{shead}</tr></thead>
<tbody>
{''.join(srows)}
</tbody>
</table>

<h2>Events (first {len(ev_show)} of {len(events)})</h2>
<table class="sortable">
<thead><tr>{ehead}</tr></thead>
<tbody>
{''.join(erows)}
</tbody>
</table>

<p class="note">Full event list: <code>events.csv</code>. Frozen knobs: <code>BASELINE.md</code>.</p>
{SORT_JS}
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def build_slices(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    slices: list[dict[str, Any]] = []
    slices.append(summarize_slice(events, "all"))
    primary = [e for e in events if e.get("framing") == "primary"]
    secondary = [e for e in events if e.get("framing") == "secondary"]
    slices.append(summarize_slice(primary, "primary_all"))
    slices.append(summarize_slice(secondary, "secondary_all"))
    for tf in IMPULSE_TFS:
        slices.append(summarize_slice([e for e in events if e.get("impulse_tf") == tf], f"tf_{tf}"))
        slices.append(
            summarize_slice(
                [e for e in primary if e.get("impulse_tf") == tf],
                f"primary_tf_{tf}",
            )
        )
    for _, _, label, _ in EVENT_COMBOS:
        slices.append(summarize_slice([e for e in events if e.get("event") == label], label))
    for tf in IMPULSE_TFS:
        for _, _, label, _ in EVENT_COMBOS:
            rows = [e for e in events if e.get("event") == label and e.get("impulse_tf") == tf]
            slices.append(summarize_slice(rows, f"{label}__{tf}"))
    # away_flag quality filter on primary
    slices.append(
        summarize_slice([e for e in primary if int(e.get("away_flag") or 0) == 1], "primary_away1")
    )
    return slices


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stamp", default=DEFAULT_STAMP)
    ap.add_argument(
        "--universe",
        default="paultwenty",
        choices=("paultwenty", "all_1m"),
        help="paultwenty (default) or all symbols with 1m parquet",
    )
    ap.add_argument("--symbols", default="", help="Comma override, e.g. NVDA,AAPL")
    ap.add_argument("--limit-syms", type=int, default=0)
    args = ap.parse_args()
    stamp = args.stamp
    out_dir = DRIVE / "paul_experiments" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.symbols.strip():
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    elif args.universe == "paultwenty":
        symbols = load_paultwenty()
    else:
        symbols = discover_1m_symbols()
    if args.limit_syms and args.limit_syms > 0:
        symbols = symbols[: args.limit_syms]

    # Keep only symbols with 1m + daily
    usable: list[str] = []
    for s in symbols:
        p = DEFAULT_1M_DIR / f"{s}.parquet"
        d = ROOT / "data" / "newdata" / "data" / f"{s}.csv"
        if p.exists() and d.exists():
            usable.append(s)
    symbols = usable
    print(f"stamp={stamp} symbols={len(symbols)} -> {out_dir}")

    all_events: list[dict[str, Any]] = []
    miss_daily = 0
    for i, sym in enumerate(symbols, 1):
        daily = ab.load_ohlc(sym)
        if daily is None or daily.empty:
            miss_daily += 1
            continue
        atr_map = ab.prior_close_atr_map(daily)
        pdhl_map = prior_day_hl_map(daily)
        ev = scan_symbol(sym, atr_map=atr_map, pdhl_map=pdhl_map)
        all_events.extend(ev)
        if i % 5 == 0 or i == len(symbols):
            print(f"  [{i}/{len(symbols)}] {sym} +{len(ev)} events (cum {len(all_events)})")

    sessions = sorted({str(e.get("session")) for e in all_events if e.get("session")})
    sess_min = sessions[0] if sessions else "—"
    sess_max = sessions[-1] if sessions else "—"

    # Coverage note
    sym_sess: dict[str, int] = defaultdict(int)
    for e in all_events:
        sym_sess[str(e["symbol"])] += 1
    coverage_note = (
        f"Yahoo 1m under `data/intraday/1m/`; PaulTwenty with both 1m+daily n={len(symbols)}; "
        f"miss_daily={miss_daily}. Observed event sessions {sess_min}→{sess_max} "
        f"(n_session_dates={len(sessions)}). Short retention — observational only."
    )

    slices = build_slices(all_events)
    write_csv(out_dir / "events.csv", all_events)
    write_csv(out_dir / "slices.csv", slices)

    # Patch stamp into baseline text
    write_baseline(
        out_dir / "BASELINE.md",
        stamp=stamp,
        symbols=symbols,
        coverage_note=coverage_note,
        n_events=len(all_events),
        sess_min=sess_min,
        sess_max=sess_max,
    )

    write_summary(
        out_dir / "SUMMARY.md",
        stamp=stamp,
        slices=slices,
        n_events=len(all_events),
        symbols=symbols,
        sess_min=sess_min,
        sess_max=sess_max,
        coverage_note=coverage_note,
    )
    write_html(
        out_dir / "compare.html",
        stamp=stamp,
        slices=slices,
        events=all_events,
        symbols=symbols,
        coverage_note=coverage_note,
        sess_min=sess_min,
        sess_max=sess_max,
    )

    primary = next((s for s in slices if s["slice"] == "primary_all"), None)
    print(
        f"Done. events={len(all_events)} primary_N={primary['N'] if primary else 0} "
        f"reject15={fmt_num(primary.get('outcome_15m_reject_pct') if primary else None,1)}% "
        f"break15={fmt_num(primary.get('outcome_15m_break_pct') if primary else None,1)}%"
    )
    print(f"HTML: {out_dir / 'compare.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
