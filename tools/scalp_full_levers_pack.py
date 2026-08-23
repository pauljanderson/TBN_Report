#!/usr/bin/env python3
"""Scalp full levers data pack — shapes, per-symbol, stop variants, all prior slices.

One coherent book (control entries) plus one-knob stop / time-stop re-exits.
Writes stamp under drive/paul_experiments/<stamp>/ with BASELINE.md + compare.html.

Usage:
  python tools/scalp_full_levers_pack.py --all --stamp scalp_full_levers_20260822
  python tools/scalp_full_levers_pack.py -s SPY,AAPL --stamp scalp_full_levers_smoke
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import math
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "stock_analysis"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import scalp_open15_reversal_ab as ab  # noqa: E402
from compare_format import format_money  # noqa: E402
from intraday_1m import DEFAULT_1M_DIR, ET, read_1m, resample_ohlcv  # noqa: E402

DRIVE = ROOT / "drive"
DEFAULT_STAMP = "scalp_full_levers_20260822"
SYSTEM = "scalp"

# Stop arms (one-knob vs control; target + 11:30 time-stop frozen unless noted)
STOP_ARMS = (
    "control_lod_hod_0p1",
    "setup_bar_0p05",
    "prior_day_hl",
    "prior_week_hl",
)


def classify_open15_shape(
    o: float,
    h: float,
    l: float,
    c: float,
    *,
    prior_h: float = float("nan"),
    prior_l: float = float("nan"),
) -> dict[str, Any]:
    """Documented open15 candle shape labels (descriptive; not a filter).

    Definitions (freeze):
    - body = |C−O|; range = H−L; body_frac = body/range
    - upper_wick = H − max(O,C); lower_wick = min(O,C) − L
    - color: green (C>O), red (C<O), doji_color (C==O) — traded book is red for long /
      green for short by construction
    - doji: body_frac < 0.10
    - marubozu: body_frac >= 0.90
    - hammer_like: lower_wick >= 2×body and upper_wick <= 0.5×body (geometry only)
    - shooting_star_like: upper_wick >= 2×body and lower_wick <= 0.5×body
    - long_upper / long_lower: wick/range >= 0.40 (if not already doji/marubozu/hammer/star)
    - balanced: else
    - engulfing_day: open15 High >= prior-day High AND open15 Low <= prior-day Low
    """
    rng = h - l
    body = abs(c - o)
    if rng <= 0 or not math.isfinite(rng):
        return {
            "open15_color": "flat_range",
            "open15_shape": "invalid_range",
            "open15_body_frac": float("nan"),
            "open15_upper_wick_frac": float("nan"),
            "open15_lower_wick_frac": float("nan"),
            "open15_engulfing_day": 0,
        }
    body_frac = body / rng
    upper = h - max(o, c)
    lower = min(o, c) - l
    upper_frac = upper / rng
    lower_frac = lower / rng
    if c > o:
        color = "green"
    elif c < o:
        color = "red"
    else:
        color = "doji_color"

    engulf = 0
    if (
        math.isfinite(prior_h)
        and math.isfinite(prior_l)
        and h >= prior_h
        and l <= prior_l
    ):
        engulf = 1

    if body_frac < ab.OPEN15_DOJI_BODY_FRAC:
        shape = "doji"
    elif body_frac >= ab.OPEN15_MARUBOZU_BODY_FRAC:
        shape = "marubozu"
    elif body > 0 and lower >= 2.0 * body and upper <= 0.5 * body:
        shape = "hammer_like"
    elif body > 0 and upper >= 2.0 * body and lower <= 0.5 * body:
        shape = "shooting_star_like"
    elif upper_frac >= ab.OPEN15_LONG_WICK_FRAC and upper_frac >= lower_frac:
        shape = "long_upper"
    elif lower_frac >= ab.OPEN15_LONG_WICK_FRAC:
        shape = "long_lower"
    else:
        shape = "balanced"

    if engulf:
        # Keep primary geometry label; flag separately + composite key for slices
        shape_key = f"{shape}|engulfing_day"
    else:
        shape_key = shape

    return {
        "open15_color": color,
        "open15_shape": shape,
        "open15_shape_key": shape_key,
        "open15_body_frac": round(body_frac, 6),
        "open15_upper_wick_frac": round(upper_frac, 6),
        "open15_lower_wick_frac": round(lower_frac, 6),
        "open15_engulfing_day": engulf,
    }


def prior_session_row(daily: pd.DataFrame, d: date) -> Optional[pd.Series]:
    dates = list(daily["Date"])
    if d not in dates:
        # nearest prior available
        prior_dates = [x for x in dates if x < d]
        if not prior_dates:
            return None
        return daily.loc[daily["Date"] == prior_dates[-1]].iloc[0]
    i = dates.index(d)
    if i <= 0:
        return None
    return daily.iloc[i - 1]


def prior_day_hl(daily: pd.DataFrame, d: date) -> tuple[float, float]:
    row = prior_session_row(daily, d)
    if row is None:
        return float("nan"), float("nan")
    return float(row["Low"]), float(row["High"])


def prior_week_hl(daily: pd.DataFrame, d: date) -> tuple[float, float]:
    """Low/High of the previous ISO calendar week (Mon–Sun) from daily bars."""
    iso = d.isocalendar()
    # Monday of current ISO week
    cur_monday = d - timedelta(days=d.weekday())
    prev_monday = cur_monday - timedelta(days=7)
    prev_sunday = cur_monday - timedelta(days=1)
    mask = (daily["Date"] >= prev_monday) & (daily["Date"] <= prev_sunday)
    sub = daily.loc[mask]
    if sub.empty:
        # fallback: last 5 sessions before d
        prior = daily.loc[daily["Date"] < d].tail(5)
        if prior.empty:
            return float("nan"), float("nan")
        return float(prior["Low"].min()), float(prior["High"].max())
    return float(sub["Low"].min()), float(sub["High"].max())


def compute_stop(
    arm: str,
    *,
    side: str,
    entry: float,
    lod: float,
    hod: float,
    setup_l: float,
    setup_h: float,
    prior_lo: float,
    prior_hi: float,
    week_lo: float,
    week_hi: float,
) -> Optional[float]:
    """Return stop price for arm, or None if invalid / missing levels."""
    if arm == "control_lod_hod_0p1":
        if side == "long":
            if not math.isfinite(lod):
                return None
            return lod * (1.0 - ab.STOP_LOD_PCT / 100.0)
        if not math.isfinite(hod):
            return None
        return hod * (1.0 + ab.STOP_LOD_PCT / 100.0)

    if arm == "setup_bar_0p05":
        buf = ab.STOP_SETUP_BUFFER_PCT / 100.0
        if side == "long":
            if not math.isfinite(setup_l):
                return None
            return setup_l * (1.0 - buf)
        if not math.isfinite(setup_h):
            return None
        return setup_h * (1.0 + buf)

    if arm == "prior_day_hl":
        buf = ab.STOP_PRIOR_BUFFER_PCT / 100.0
        if side == "long":
            if not math.isfinite(prior_lo):
                return None
            return prior_lo * (1.0 - buf)
        if not math.isfinite(prior_hi):
            return None
        return prior_hi * (1.0 + buf)

    if arm == "prior_week_hl":
        buf = ab.STOP_PRIOR_BUFFER_PCT / 100.0
        if side == "long":
            if not math.isfinite(week_lo):
                return None
            return week_lo * (1.0 - buf)
        if not math.isfinite(week_hi):
            return None
        return week_hi * (1.0 + buf)

    return None


def stop_valid(side: str, entry: float, stop: float) -> bool:
    if not math.isfinite(stop) or not math.isfinite(entry) or entry <= 0:
        return False
    if side == "long":
        return stop < entry
    return stop > entry


def reexit_with_stop(
    control_trade: dict[str, Any],
    day5: pd.DataFrame,
    *,
    stop: float,
    stop_arm: str,
    time_stop: Optional[time] = ab.TIME_STOP_T,
    eod_flat: time = ab.EOD_FLAT_T,
) -> dict[str, Any]:
    """Same entry/target as control; new stop (+ optional time-stop policy)."""
    entry_ts = str(control_trade["entry_ts"])
    entry_i = None
    for i in range(len(day5)):
        if str(day5.iloc[i]["ts"]) == entry_ts:
            entry_i = i
            break
    if entry_i is None:
        et = pd.Timestamp(entry_ts)
        for i in range(len(day5)):
            if pd.Timestamp(day5.iloc[i]["ts"]) == et:
                entry_i = i
                break
    out = dict(control_trade)
    out["stop_arm"] = stop_arm
    out["stop"] = round(stop, 6)
    if entry_i is None:
        out["exit_type"] = "REEXIT_MISS"
        return out

    side = str(control_trade["side"])
    entry = float(control_trade["entry"])
    target = float(control_trade["target"])
    exit_px, exit_ts, exit_type = ab.resolve_exit(
        day5,
        entry_i,
        side=side,
        entry=entry,
        stop=stop,
        target=target,
        time_stop=time_stop,
        eod_flat=eod_flat,
    )
    if side == "long":
        pnl_pct = (exit_px / entry - 1.0) * 100.0
        risk = entry - stop
        r_mult = (exit_px - entry) / risk if risk > 0 else float("nan")
        shares = int(control_trade.get("shares") or 0)
        pnl_usd = shares * (exit_px - entry)
    else:
        pnl_pct = (entry - exit_px) / entry * 100.0
        risk = stop - entry
        r_mult = (entry - exit_px) / risk if risk > 0 else float("nan")
        shares = int(control_trade.get("shares") or 0)
        pnl_usd = shares * (entry - exit_px)

    out.update(
        {
            "exit_ts": exit_ts,
            "exit": round(exit_px, 6),
            "exit_type": exit_type,
            "pnl_pct": round(pnl_pct, 6),
            "r_mult": round(r_mult, 6) if math.isfinite(r_mult) else "",
            "pnl_usd": round(pnl_usd, 2),
            "win": 1 if pnl_pct > 0 else 0,
            "time_stop_arm": "1130" if time_stop is not None else "none_eod1555",
        }
    )
    return out


def enrich_shape(
    trade: dict[str, Any],
    daily: pd.DataFrame,
    d: date,
) -> dict[str, Any]:
    o = float(trade.get("open15_o") or float("nan"))
    h = float(trade.get("open15_h") or float("nan"))
    l = float(trade.get("open15_l") or float("nan"))
    c = float(trade.get("open15_c") or float("nan"))
    prior = prior_session_row(daily, d)
    ph = float(prior["High"]) if prior is not None else float("nan")
    pl = float(prior["Low"]) if prior is not None else float("nan")
    shape = classify_open15_shape(o, h, l, c, prior_h=ph, prior_l=pl)
    out = dict(trade)
    out.update(shape)
    return out


def per_symbol_full(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_sym: dict[str, list[dict[str, Any]]] = {}
    for t in trades:
        by_sym.setdefault(str(t["symbol"]), []).append(t)
    rows: list[dict[str, Any]] = []
    for sym, ts in by_sym.items():
        pnls = [float(x["pnl_pct"]) for x in ts]
        usds = [float(x["pnl_usd"]) for x in ts]
        advs = [float(x["adv_prior"]) for x in ts if x.get("adv_prior") not in ("", None)]
        n = len(ts)
        wins = sum(1 for p in pnls if p > 0)
        w_usd = [u for u in usds if u > 0]
        l_usd = [u for u in usds if u <= 0]
        gw, gl = sum(w_usd), abs(sum(l_usd))
        pf = (gw / gl) if gl > 0 else (float("inf") if gw > 0 else float("nan"))
        n_eo = sum(1 for x in ts if x.get("entirely_out") == "entirely_out")
        avg = float(np.mean(pnls)) if pnls else float("nan")
        thin = n < 5
        worked = (not thin) and math.isfinite(avg) and avg > 0
        label = "thin_N" if thin else ("worked_well" if worked else "soft_or_neg")
        rows.append(
            {
                "symbol": sym,
                "N": n,
                "Win%": 100.0 * wins / n if n else float("nan"),
                "Avg_PnL_%": avg,
                "Total_PnL_$": sum(usds),
                "Profit_Factor": pf,
                "n_long": sum(1 for x in ts if x.get("side") == "long"),
                "n_short": sum(1 for x in ts if x.get("side") == "short"),
                "entirely_out_rate": 100.0 * n_eo / n if n else float("nan"),
                "median_ADV$": float(np.median(advs)) if advs else float("nan"),
                "label": label,
            }
        )
    rows.sort(key=lambda r: (r["Avg_PnL_%"], r["Total_PnL_$"]), reverse=True)
    return rows


def pick_stop_verdict(control_m: dict[str, Any], cand_m: dict[str, Any], arm: str) -> str:
    """KEEP/HOLD/DISMISS for stop arm vs control. Research only; short window → no KEEP."""
    cn = int(control_m.get("N") or 0)
    kn = int(cand_m.get("N") or 0)
    if kn < 20 or cn < 20:
        return f"HOLD - {arm}: insufficient N (research only)"
    c_avg = control_m.get("Avg_PnL_%")
    k_avg = cand_m.get("Avg_PnL_%")
    c_pf = control_m.get("Profit_Factor")
    k_pf = cand_m.get("Profit_Factor")
    c_dd = control_m.get("Max_DD_%")
    k_dd = cand_m.get("Max_DD_%")
    if not (
        isinstance(c_avg, float)
        and isinstance(k_avg, float)
        and math.isfinite(c_avg)
        and math.isfinite(k_avg)
    ):
        return f"HOLD - {arm}: insufficient metrics"

    # Drop rate vs control (invalid stops filtered)
    drop = (cn - kn) / cn if cn else 0.0
    if drop > 0.25:
        return f"HOLD - {arm}: drops >25% of control entries (invalid/missing levels)"

    dd_ok = True
    if isinstance(k_dd, float) and isinstance(c_dd, float) and math.isfinite(k_dd) and math.isfinite(c_dd):
        dd_ok = abs(k_dd) <= abs(c_dd) * 1.15 + 0.5

    pf_ok = (
        not isinstance(k_pf, float)
        or not isinstance(c_pf, float)
        or not math.isfinite(k_pf)
        or not math.isfinite(c_pf)
        or k_pf >= c_pf - 0.05
    )
    better = (k_avg > c_avg + 0.01) and pf_ok and dd_ok
    worse = k_avg < c_avg - 0.02

    if worse:
        return f"DISMISS - {arm}: Avg PnL% worse than control (research; not DailyRun)"
    if better:
        # Short 1m window → never KEEP / gold
        return (
            f"HOLD - {arm}: modestly better on short 1m window only "
            f"(research candidate; not KEEP / not DailyRun)"
        )
    return f"HOLD - {arm}: flat/mixed vs control (keep control; research only)"


def write_baseline_full(
    path: Path,
    *,
    stamp: str,
    symbols: list[str],
    coverage_note: str,
    n_control: int,
    stop_verdicts: dict[str, str],
) -> None:
    text = f"""# BASELINE — Scalp full levers pack — `{stamp}`

**System:** `{SYSTEM}` (research only). **Not** DailyRun. **Not** gold.

One coherent control book + descriptive slices + one-knob stop / time-stop re-exits.
Prior stamps: `scalp_longshort_20260822`, `scalp_longshort_ext_20260822`.

## Freeze (control entry / exit identity)

| Knob | Value |
|------|--------|
| Universe | All symbols with 1m parquet under `data/intraday/1m/` (n={len(symbols)} this run) |
| Sides | **long+short** |
| Daily ATR | Wilder ATR({ab.DAILY_ATR_N}) prior-close (no look-ahead) |
| ADV$ | Prior-close {ab.ADV_BARS}d mean(Close×Volume); buckets descriptive only |
| Open 15m | Left-labeled 09:30 ET |
| ATR gate | open15 (H−L) **>** {ab.RANGE_FRAC*100:.0f}% × prior-close ATR |
| Long open15 | Loser Close < Open |
| Short open15 | Winner Close > Open |
| Setup TF | 5m; window ≥09:45 and <11:00 ET |
| Long setup | Low < open15 Low; green hammer **or** bullish engulf |
| Short setup | High > open15 High; bearish_hammer (hanging-man **OR** shooting-star) **or** bearish engulf |
| Entry | Next 5m open after setup |
| **Control stop** | Long: **{ab.STOP_LOD_PCT:g}% below LOD** (min 5m low open→setup). Short: **{ab.STOP_LOD_PCT:g}% above HOD**. |
| Target | Long: open15 High. Short: open15 Low. |
| Time stop (control) | **11:30 ET** bar open if still open |
| entirely_out | Long: setup High < open15 Low. Short: setup Low > open15 High. |
| Costs / sheet | {ab.COSTS_BPS} bps · ${ab.SHEET:,.0f}/trade |
| Same-bar pathing | Stop before target |

## Open15 shape definitions (descriptive)

| Label | Definition |
|-------|------------|
| body_frac | \\|C−O\\| / (H−L) |
| upper_wick_frac | (H − max(O,C)) / (H−L) |
| lower_wick_frac | (min(O,C) − L) / (H−L) |
| color | green C>O; red C<O |
| doji | body_frac < {ab.OPEN15_DOJI_BODY_FRAC} |
| marubozu | body_frac ≥ {ab.OPEN15_MARUBOZU_BODY_FRAC} |
| hammer_like | lower ≥ 2×body and upper ≤ 0.5×body |
| shooting_star_like | upper ≥ 2×body and lower ≤ 0.5×body |
| long_upper / long_lower | wick/range ≥ {ab.OPEN15_LONG_WICK_FRAC} (after above) |
| balanced | else |
| engulfing_day | open15 High ≥ prior-day High **and** open15 Low ≤ prior-day Low (flag) |

## Stop variants (one-knob; target + 11:30 frozen)

| Arm | Stop rule |
|-----|-----------|
| control_lod_hod_0p1 | Control (above) |
| setup_bar_0p05 | Long: setup Low × (1 − {ab.STOP_SETUP_BUFFER_PCT}/100). Short: setup High × (1 + {ab.STOP_SETUP_BUFFER_PCT}/100). Buffer **frozen at {ab.STOP_SETUP_BUFFER_PCT:g}%**. |
| prior_day_hl | Long: prior session Low. Short: prior session High. Buffer **{ab.STOP_PRIOR_BUFFER_PCT:g}%** (exact). |
| prior_week_hl | Long/short: prior ISO week Low/High from daily bars. Buffer **{ab.STOP_PRIOR_BUFFER_PCT:g}%**. |

Invalid stops (long stop ≥ entry / short stop ≤ entry) or missing levels → trade **dropped from that arm** (not force-kept).

## Time-stop candidate (same entries)

| Arm | Policy |
|-----|--------|
| control_1130 | 11:30 TIME exit |
| no_timestop_eod1555 | TARGET+STOP only; safety EOD flat {ab.EOD_FLAT_T.strftime('%H:%M')} ET |

## Coverage / honesty

{coverage_note}

- Control trades this stamp: **N={n_control}**.
- Default chronological IS/OOS **not applicable** (short Yahoo 1m window, all post-2024).
- Selection bias: stop/time arms are **in-sample** compares on the same book — label research-only.
- **Not** gold. **Not** DailyRun.

## Stop-arm verdicts (pre-registered quality: Avg PnL%, PF, Max DD; short window → no KEEP)

| Arm | Verdict |
|-----|---------|
{chr(10).join(f"| `{k}` | {v} |" for k, v in stop_verdicts.items())}
"""
    path.write_text(text, encoding="utf-8")


def _slice_shape_side(trades: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for t in trades:
        shape = str(t.get("open15_shape") or "unknown")
        side = str(t.get("side") or "?")
        key = f"{shape}×{side}"
        buckets.setdefault(key, []).append(t)
        if int(t.get("open15_engulfing_day") or 0) == 1:
            buckets.setdefault(f"engulfing_day×{side}", []).append(t)
        color = str(t.get("open15_color") or "?")
        buckets.setdefault(f"color:{color}×{side}", []).append(t)
    return {k: ab.metrics_from_trades(v, include_slices=False) for k, v in sorted(buckets.items())}


def write_full_compare_html(
    path: Path,
    *,
    stamp: str,
    symbols: list[str],
    coverage_note: str,
    control_trades: list[dict[str, Any]],
    control_m: dict[str, Any],
    stop_books: dict[str, list[dict[str, Any]]],
    stop_metrics: dict[str, dict[str, Any]],
    stop_verdicts: dict[str, str],
    timestop_trades: list[dict[str, Any]],
    timestop_m: dict[str, Any],
    timestop_verdict: str,
    skipped_stops: dict[str, int],
) -> None:
    cov = html_mod.escape(coverage_note).replace("\n", "<br/>")

    # --- Stop AB table ---
    ab_cols = [
        ("arm", "text"),
        ("N", "num"),
        ("Win%", "num"),
        ("Avg_PnL_%", "num"),
        ("Profit_Factor", "num"),
        ("Total_PnL_$", "money"),
        ("Max_DD_%", "num"),
        ("ΔAvg_vs_ctrl", "num"),
        ("skipped_invalid", "num"),
        ("verdict", "text"),
    ]
    ab_head = "".join(ab.sortable_th(c, t) for c, t in ab_cols)
    ab_body = []
    c_avg = control_m.get("Avg_PnL_%")
    for arm in STOP_ARMS:
        m = stop_metrics.get(arm) or {}
        k_avg = m.get("Avg_PnL_%")
        d_avg = float("nan")
        if (
            isinstance(c_avg, float)
            and isinstance(k_avg, float)
            and math.isfinite(c_avg)
            and math.isfinite(k_avg)
        ):
            d_avg = k_avg - c_avg
        cells = [
            f"<td>{html_mod.escape(arm)}</td>",
            f"<td>{int(m.get('N') or 0)}</td>",
            f"<td>{ab._fmt_num(m.get('Win%'), 2)}</td>",
            f"<td>{ab._fmt_num(m.get('Avg_PnL_%'), 4)}</td>",
            f"<td>{ab._fmt_num(m.get('Profit_Factor'), 2)}</td>",
            f"<td>{format_money(m.get('Total_PnL_$')) if isinstance(m.get('Total_PnL_$'), (int, float)) else '—'}</td>",
            f"<td>{ab._fmt_num(m.get('Max_DD_%'), 2)}</td>",
            f"<td>{ab._fmt_num(d_avg, 4)}</td>",
            f"<td>{int(skipped_stops.get(arm, 0))}</td>",
            f"<td>{html_mod.escape(stop_verdicts.get(arm, 'HOLD'))}</td>",
        ]
        ab_body.append("<tr>" + "".join(cells) + "</tr>")

    # Time-stop row block
    ts_html = ab._slice_table(
        "D) Time stop on vs off (same entries)",
        f"Control 11:30 vs no-timestop EOD flat. Verdict: {timestop_verdict}",
        "arm",
        {
            "control_1130": control_m,
            "no_timestop_eod1555": timestop_m,
        },
    )

    side_html = ab._slice_table(
        "D) Long vs short (control)",
        "Descriptive.",
        "side",
        control_m.get("by_side") or {},
    )
    eo_html = ab._slice_table(
        "D) entirely_out vs partial (control)",
        "Long: setup High < open15 Low. Short: setup Low > open15 High.",
        "entirely_out",
        control_m.get("by_entirely_out") or {},
    )
    xt_html = ab._slice_table(
        "D) Crosstab entirely_out × side (control)",
        "Four cells.",
        "cell",
        control_m.get("by_crosstab") or {},
    )
    setup_html = ab._slice_table(
        "D) setup_kind incl. bearish_hammer (control)",
        "bearish_hammer = hanging_man OR shooting_star.",
        "setup_kind",
        control_m.get("by_setup") or {},
    )
    sub_html = ab._slice_table(
        "D) setup_subkind (control)",
        "shooting_star vs hanging_man vs engulfing.",
        "setup_subkind",
        control_m.get("by_subkind") or {},
    )
    range_html = ab._slice_table(
        "D) open15 range / ATR buckets (control)",
        "25–40, 40–60, 60–100, >100% of prior-close ATR (gate still >25%).",
        "range_atr_bucket",
        control_m.get("by_range_atr") or {},
    )
    adv_html = ab._slice_table(
        "D) Institutional ADV$ buckets (control)",
        f"Prior-close {ab.ADV_BARS}d ADV$. Not a trade filter.",
        "adv_bucket",
        control_m.get("by_adv_bucket") or {},
    )

    shape_m = {
        k: ab.metrics_from_trades(v, include_slices=False)
        for k, v in sorted(
            {
                str(t.get("open15_shape") or "unknown"): [
                    x
                    for x in control_trades
                    if str(x.get("open15_shape") or "unknown")
                    == str(t.get("open15_shape") or "unknown")
                ]
                for t in control_trades
            }.items()
        )
    }
    # rebuild shape map cleanly
    by_shape: dict[str, list[dict[str, Any]]] = {}
    for t in control_trades:
        by_shape.setdefault(str(t.get("open15_shape") or "unknown"), []).append(t)
    shape_m = {k: ab.metrics_from_trades(v, include_slices=False) for k, v in sorted(by_shape.items())}
    shape_html = ab._slice_table(
        "A) Open15 shape (control)",
        "See BASELINE.md for definitions. Click headers to sort.",
        "open15_shape",
        shape_m,
    )
    shape_side_html = ab._slice_table(
        "A) Open15 shape × side (+ color / engulfing_day flags)",
        "Composite keys. engulfing_day = open15 engulfs prior daily H/L.",
        "shape×side",
        _slice_shape_side(control_trades),
    )

    # Per-symbol full table
    sym_rows = per_symbol_full(control_trades)
    sym_cols = [
        ("symbol", "text"),
        ("N", "num"),
        ("Win%", "num"),
        ("Avg_PnL_%", "num"),
        ("Total_PnL_$", "money"),
        ("Profit_Factor", "num"),
        ("n_long", "num"),
        ("n_short", "num"),
        ("entirely_out_rate", "num"),
        ("median_ADV$", "num"),
        ("label", "text"),
    ]
    shead = "".join(ab.sortable_th(c, t) for c, t in sym_cols)
    sbody = []
    n_sym = len(sym_rows)
    top_cut = max(0, min(15, n_sym))
    bot_cut = max(0, min(15, n_sym))
    for i, r in enumerate(sym_rows):
        cls = ""
        if i < top_cut and r.get("label") == "worked_well":
            cls = ' class="hi-top"'
        elif i < top_cut:
            cls = ' class="hi-top-weak"'
        elif i >= n_sym - bot_cut:
            cls = ' class="hi-bot"'
        cells = []
        for c, _ in sym_cols:
            v = r.get(c, "")
            if c == "Total_PnL_$" and isinstance(v, (int, float)):
                cells.append(f"<td>{format_money(v)}</td>")
            elif c == "median_ADV$" and isinstance(v, float) and math.isfinite(v):
                cells.append(f"<td>{format_money(v)}</td>")
            elif isinstance(v, float):
                cells.append(f"<td>{ab._fmt_num(v, 4 if 'PnL' in c or 'rate' in c else 2)}</td>")
            else:
                cells.append(f"<td>{html_mod.escape(str(v))}</td>")
        sbody.append(f"<tr{cls}>" + "".join(cells) + "</tr>")
    if not sbody:
        sbody.append(f"<tr><td colspan='{len(sym_cols)}'>No trades</td></tr>")

    # Top 15 summary list for header
    top15 = sym_rows[:15]
    top15_li = "".join(
        f"<li><code>{html_mod.escape(r['symbol'])}</code> N={r['N']} "
        f"WR={ab._fmt_num(r['Win%'])}% Avg={ab._fmt_num(r['Avg_PnL_%'], 4)}% "
        f"PnL$={format_money(r['Total_PnL_$'])} [{html_mod.escape(r['label'])}]</li>"
        for r in top15
    )

    # Control book metrics strip
    m = control_m
    metric_bits = (
        f"N={m.get('N')} · WR%={ab._fmt_num(m.get('Win%'))} · "
        f"AvgPnL%={ab._fmt_num(m.get('Avg_PnL_%'), 4)} · "
        f"PF={ab._fmt_num(m.get('Profit_Factor'))} · "
        f"PnL$={format_money(m.get('Total_PnL_$') or 0)} · "
        f"MaxDD%={ab._fmt_num(m.get('Max_DD_%'))}"
    )

    # Trade sample table (capped)
    trade_cols = [
        ("symbol", "text"),
        ("side", "text"),
        ("session", "date"),
        ("open15_shape", "text"),
        ("open15_color", "text"),
        ("setup_kind", "text"),
        ("setup_subkind", "text"),
        ("entirely_out", "text"),
        ("adv_bucket", "text"),
        ("range_atr_bucket", "text"),
        ("entry", "num"),
        ("stop", "num"),
        ("target", "num"),
        ("exit", "num"),
        ("exit_type", "text"),
        ("pnl_pct", "num"),
        ("pnl_usd", "num"),
    ]
    thead = "".join(ab.sortable_th(c, t) for c, t in trade_cols)
    tbody = []
    trade_limit = 2500
    for t in control_trades[:trade_limit]:
        cells = []
        for c, _ in trade_cols:
            v = t.get(c, "")
            if c == "pnl_usd" and isinstance(v, (int, float)):
                cells.append(f"<td>{format_money(v)}</td>")
            elif isinstance(v, float):
                cells.append(f"<td>{ab._fmt_num(v, 4)}</td>")
            else:
                cells.append(f"<td>{html_mod.escape(str(v))}</td>")
        tbody.append("<tr>" + "".join(cells) + "</tr>")
    trade_note = ""
    if len(control_trades) > trade_limit:
        trade_note = (
            f"<p>Showing first {trade_limit} of {len(control_trades)} control trades "
            f"(full book in <code>trades_control.csv</code>).</p>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Scalp full levers — {html_mod.escape(stamp)}</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1.5rem; color: #0f172a; background: #f8fafc; }}
h1,h2 {{ color: #0f172a; }}
.note {{ background: #fff7ed; border-left: 4px solid #f97316; padding: .75rem 1rem; margin: 1rem 0; }}
.verdict {{ font-size: 1.05rem; font-weight: 600; margin: .35rem 0; }}
table {{ border-collapse: collapse; width: 100%; background: #fff; margin: .75rem 0 1.5rem; font-size: .88rem; }}
th, td {{ border: 1px solid #cbd5e1; padding: .35rem .5rem; text-align: left; }}
th {{ background: #e2e8f0; }}
tr.total-row {{ font-weight: 600; background: #f1f5f9; }}
tr.hi-top td {{ background: #dcfce7; }}
tr.hi-top-weak td {{ background: #ecfccb; }}
tr.hi-bot td {{ background: #fee2e2; }}
{ab.SORT_CSS}
code {{ background: #e2e8f0; padding: .1rem .3rem; border-radius: 3px; }}
.toc a {{ margin-right: 1rem; }}
</style>
</head>
<body>
<h1>Scalp full levers data pack</h1>
<p>Stamp <code>{html_mod.escape(stamp)}</code> · {len(symbols)} symbols ·
<strong>research only — not gold / not DailyRun</strong></p>
<p><strong>Control book:</strong> {html_mod.escape(metric_bits)}</p>
<div class="note">
<strong>Coverage.</strong> {cov}<br/>
<strong>All levers / tables live on this page</strong> (plus CSVs in the stamp folder).
Click column headers to sort. Green rows = top performers; red = bottom by Avg PnL%.
<em>worked_well</em> = Avg PnL% &gt; 0 and N≥5; else <em>thin_N</em> or <em>soft_or_neg</em>.
</div>

<nav class="toc">
<a href="#stops">C Stop variants</a>
<a href="#symbols">B Per-symbol</a>
<a href="#shapes">A Open15 shape</a>
<a href="#levers">D All levers</a>
<a href="#trades">Trades</a>
</nav>

<h2>Top 15 symbols by Avg PnL% (control)</h2>
<ol>{top15_li or "<li>None</li>"}</ol>

<h2 id="stops">C) Stop variants vs control</h2>
<p>One-knob stop change; target = open15 extreme; time stop 11:30 frozen.
Invalid/missing levels dropped from candidate arm.</p>
<table class="sortable">
<thead><tr>{ab_head}</tr></thead>
<tbody>{''.join(ab_body)}</tbody>
</table>
{''.join(f'<p class="verdict">{html_mod.escape(v)}</p>' for v in stop_verdicts.values())}

{ts_html}
<p class="verdict">{html_mod.escape(timestop_verdict)}</p>

<h2 id="symbols">B) Per-symbol summary (available 1m window)</h2>
<p>Full sortable table. Highlight: top/bottom by Avg PnL%. Click headers to sort.</p>
<table class="sortable">
<thead><tr>{shead}</tr></thead>
<tbody>{''.join(sbody)}</tbody>
</table>

<div id="shapes">
{shape_html}
{shape_side_html}
</div>

<div id="levers">
{side_html}
{eo_html}
{xt_html}
{setup_html}
{sub_html}
{range_html}
{adv_html}
</div>

<h2 id="trades">Control trades (sample)</h2>
{trade_note}
<table class="sortable">
<thead><tr>{thead}</tr></thead>
<tbody>{''.join(tbody) if tbody else f"<tr><td colspan='{len(trade_cols)}'>No trades</td></tr>"}</tbody>
</table>

<p style="color:#64748b;font-size:.85rem">Generated {datetime.now(tz=ET).isoformat(timespec="seconds")} ·
tool <code>tools/scalp_full_levers_pack.py</code></p>
{ab.SORT_JS}
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def run_full_levers(
    symbols: list[str],
    *,
    stamp: str,
    coverage_note: str,
) -> dict[str, Any]:
    out_dir = DRIVE / "paul_experiments" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    control_trades: list[dict[str, Any]] = []
    stop_books: dict[str, list[dict[str, Any]]] = {a: [] for a in STOP_ARMS}
    skipped_stops: dict[str, int] = {a: 0 for a in STOP_ARMS}
    timestop_trades: list[dict[str, Any]] = []
    diags: list[dict[str, Any]] = []
    sides = {"long", "short"}
    n_sym = len(symbols)

    for i, sym in enumerate(symbols, 1):
        if i == 1 or i % 50 == 0 or i == n_sym:
            print(f"[{i}/{n_sym}] {sym} … ctrl={len(control_trades)}", flush=True)
        daily = ab.load_ohlc(sym)
        if daily is None:
            continue
        atr_map = ab.prior_close_atr_map(daily)
        adv_map = ab.prior_close_adv_map(daily)
        df1 = ab.rth_filter(read_1m(sym, DEFAULT_1M_DIR))
        if df1.empty:
            continue
        df5 = resample_ohlcv(df1, "5min")
        df15 = resample_ohlcv(df1, "15min")
        for d in ab.session_dates(df1):
            atr = atr_map.get(d)
            if atr is None or not math.isfinite(atr) or atr <= 0:
                diags.append({"symbol": sym, "session": str(d), "skip_reason": "no_prior_atr"})
                continue
            adv = float(adv_map.get(d, float("nan")))
            trade, diag = ab.simulate_day(
                sym,
                d,
                df5,
                df15,
                float(atr),
                sides=sides,
                adv_prior=adv,
                time_stop=ab.TIME_STOP_T,
                eod_flat=ab.EOD_FLAT_T,
            )
            diags.append(diag)
            if not trade:
                continue

            trade = enrich_shape(trade, daily, d)
            control_trades.append(trade)
            day5 = ab.bars_on_day(df5, d)

            # Time-stop candidate (same stop)
            timestop_trades.append(
                ab.reexit_trade(trade, day5, time_stop=None, eod_flat=ab.EOD_FLAT_T)
            )

            # Levels for stop variants
            lod = float(trade["lod"]) if trade.get("lod") not in ("", None) else float("nan")
            hod = float(trade["hod"]) if trade.get("hod") not in ("", None) else float("nan")
            setup_l = float(trade.get("setup_l") or float("nan"))
            setup_h = float(trade.get("setup_h") or float("nan"))
            plo, phi = prior_day_hl(daily, d)
            wlo, whi = prior_week_hl(daily, d)
            side = str(trade["side"])
            entry = float(trade["entry"])

            for arm in STOP_ARMS:
                stop = compute_stop(
                    arm,
                    side=side,
                    entry=entry,
                    lod=lod,
                    hod=hod,
                    setup_l=setup_l,
                    setup_h=setup_h,
                    prior_lo=plo,
                    prior_hi=phi,
                    week_lo=wlo,
                    week_hi=whi,
                )
                if stop is None or not stop_valid(side, entry, stop):
                    skipped_stops[arm] = skipped_stops.get(arm, 0) + 1
                    continue
                if arm == "control_lod_hod_0p1":
                    # Already resolved under control stop; keep identity
                    t2 = dict(trade)
                    t2["stop_arm"] = arm
                    stop_books[arm].append(t2)
                else:
                    stop_books[arm].append(
                        reexit_with_stop(
                            trade,
                            day5,
                            stop=float(stop),
                            stop_arm=arm,
                            time_stop=ab.TIME_STOP_T,
                            eod_flat=ab.EOD_FLAT_T,
                        )
                    )

    control_m = ab.metrics_from_trades(control_trades)
    stop_metrics = {a: ab.metrics_from_trades(stop_books[a]) for a in STOP_ARMS}
    timestop_m = ab.metrics_from_trades(timestop_trades)

    stop_verdicts: dict[str, str] = {}
    for arm in STOP_ARMS:
        if arm == "control_lod_hod_0p1":
            stop_verdicts[arm] = ab.pick_verdict(control_m, short_coverage=True)
        else:
            stop_verdicts[arm] = pick_stop_verdict(control_m, stop_metrics[arm], arm)

    # Time-stop AB verdict (reuse ext logic briefly)
    c_avg, k_avg = control_m.get("Avg_PnL_%"), timestop_m.get("Avg_PnL_%")
    if (
        isinstance(c_avg, float)
        and isinstance(k_avg, float)
        and math.isfinite(c_avg)
        and math.isfinite(k_avg)
    ):
        if k_avg < c_avg - 0.02:
            timestop_verdict = "DISMISS - removing 11:30 time stop worsens Avg PnL (research)"
        elif k_avg > c_avg + 0.01:
            timestop_verdict = (
                "HOLD - no-timestop modestly better on short window (research; not KEEP)"
            )
        else:
            timestop_verdict = "HOLD - no-timestop flat/mixed vs 11:30 (keep control; research only)"
    else:
        timestop_verdict = "HOLD - insufficient for time-stop AB"
    stop_verdicts["timestop_ab"] = timestop_verdict

    # --- Write artifacts ---
    def _write_trades(name: str, rows: list[dict[str, Any]]) -> None:
        p = out_dir / name
        if rows:
            keys: list[str] = []
            seen = set()
            for r in rows:
                for k in r:
                    if k not in seen:
                        seen.add(k)
                        keys.append(k)
            with p.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)
        else:
            p.write_text("note\nno_trades\n", encoding="utf-8")

    _write_trades("trades_control.csv", control_trades)
    _write_trades("trades.csv", control_trades)
    _write_trades("trades_no_timestop.csv", timestop_trades)
    for arm in STOP_ARMS:
        _write_trades(f"trades_stop_{arm}.csv", stop_books[arm])

    sym_stats = per_symbol_full(control_trades)
    if sym_stats:
        with (out_dir / "per_symbol.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(sym_stats[0].keys()))
            w.writeheader()
            w.writerows(sym_stats)

    # metrics_ab
    flat_rows = []
    for label, m in [
        ("control_lod_hod_0p1", control_m),
        ("no_timestop_eod1555", timestop_m),
    ] + [(a, stop_metrics[a]) for a in STOP_ARMS if a != "control_lod_hod_0p1"]:
        r = ab._arm_row(label, m)
        fr = {k: v for k, v in r.items() if k != "exit_mix"}
        for ek, ev in (r.get("exit_mix") or {}).items():
            fr[f"exit_{ek}"] = ev
        fr["verdict"] = stop_verdicts.get(label, stop_verdicts.get(label.replace("no_timestop_eod1555", "timestop_ab"), ""))
        flat_rows.append(fr)
    keys = sorted({k for r in flat_rows for k in r})
    with (out_dir / "metrics_ab.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(flat_rows)

    write_baseline_full(
        out_dir / "BASELINE.md",
        stamp=stamp,
        symbols=symbols,
        coverage_note=coverage_note,
        n_control=int(control_m.get("N") or 0),
        stop_verdicts=stop_verdicts,
    )
    ab.STAMP = stamp
    ab.write_ab_plan(out_dir / "AB_PLAN.md")

    html_path = out_dir / "compare.html"
    write_full_compare_html(
        html_path,
        stamp=stamp,
        symbols=symbols,
        coverage_note=coverage_note,
        control_trades=control_trades,
        control_m=control_m,
        stop_books=stop_books,
        stop_metrics=stop_metrics,
        stop_verdicts=stop_verdicts,
        timestop_trades=timestop_trades,
        timestop_m=timestop_m,
        timestop_verdict=timestop_verdict,
        skipped_stops=skipped_stops,
    )

    # SUMMARY
    top15 = sym_stats[:15]
    by_shape: dict[str, list] = {}
    for t in control_trades:
        by_shape.setdefault(str(t.get("open15_shape") or "?"), []).append(t)
    shape_lines = []
    for k, v in sorted(by_shape.items(), key=lambda kv: -len(kv[1])):
        sm = ab.metrics_from_trades(v, include_slices=False)
        shape_lines.append(
            f"- {k}: N={sm.get('N')} WR%={ab._fmt_num(sm.get('Win%'))} "
            f"Avg={ab._fmt_num(sm.get('Avg_PnL_%'), 4)} PF={ab._fmt_num(sm.get('Profit_Factor'))}"
        )

    (out_dir / "SUMMARY.md").write_text(
        f"""# SUMMARY — `{stamp}`

## Control
- N={control_m.get('N')} WR%={ab._fmt_num(control_m.get('Win%'))} Avg={ab._fmt_num(control_m.get('Avg_PnL_%'), 4)} PF={ab._fmt_num(control_m.get('Profit_Factor'))} PnL$={format_money(control_m.get('Total_PnL_$') or 0)}

## Stop-arm verdicts
{chr(10).join(f"- **{k}**: {v}" for k, v in stop_verdicts.items())}

## Top 15 symbols (Avg PnL%)
{chr(10).join(f"- {r['symbol']}: N={r['N']} WR={ab._fmt_num(r['Win%'])}% Avg={ab._fmt_num(r['Avg_PnL_%'], 4)}% PnL$={format_money(r['Total_PnL_$'])} [{r['label']}]" for r in top15)}

## Open15 shape takeaway
{chr(10).join(shape_lines)}

## All data
See `compare.html` (sortable) + CSVs in this stamp folder.
""",
        encoding="utf-8",
    )
    (out_dir / "symbols.txt").write_text("\n".join(symbols) + "\n", encoding="utf-8")

    return {
        "out_dir": out_dir,
        "html": html_path,
        "control_metrics": control_m,
        "stop_metrics": stop_metrics,
        "stop_verdicts": stop_verdicts,
        "timestop_metrics": timestop_m,
        "sym_stats": sym_stats,
        "control_trades": control_trades,
        "n_symbols": len(symbols),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Scalp full levers data pack")
    ap.add_argument("-s", "--symbols", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--stamp", default=DEFAULT_STAMP)
    args = ap.parse_args()

    if args.all:
        symbols = ab.discover_1m_symbols()
    elif args.symbols.strip():
        symbols = [
            p.strip().upper()
            for p in args.symbols.replace(";", ",").split(",")
            if p.strip()
        ]
    else:
        symbols = ["SPY", "AAPL"]

    if not symbols:
        print("No symbols", file=sys.stderr)
        return 2

    coverage_note = (
        "1m store under `data/intraday/1m/`; "
        "global bar span roughly **2026-07-23 … 2026-08-21** (symbol-dependent; "
        "many names only ~Aug 17–21). Yahoo 1m retention — short window. "
        "Incomplete sessions may yield `INCOMPLETE_EOD`."
    )

    result = run_full_levers(symbols, stamp=args.stamp, coverage_note=coverage_note)
    cm = result["control_metrics"]
    print(f"OUT={result['out_dir']}", flush=True)
    print(
        f"CTRL N={cm['N']} WR%={ab._fmt_num(cm['Win%'])} Avg={ab._fmt_num(cm['Avg_PnL_%'], 4)} "
        f"PF={ab._fmt_num(cm['Profit_Factor'])} PnL$={format_money(cm.get('Total_PnL_$') or 0)}",
        flush=True,
    )
    for k, v in result["stop_verdicts"].items():
        print(f"Verdict[{k}]: {v}", flush=True)
    print("Top15:", flush=True)
    for r in result["sym_stats"][:15]:
        print(
            f"  {r['symbol']} N={r['N']} Avg={ab._fmt_num(r['Avg_PnL_%'], 4)} "
            f"[{r['label']}]",
            flush=True,
        )
    print(f"HTML={result['html']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
