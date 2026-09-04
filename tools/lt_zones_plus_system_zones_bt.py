#!/usr/bin/env python3
"""AB: does adding house-system zones help LT-direction predictability?

Control: LT zones alone (same daily score / ±50 entry / exit_40 as
lt_zones_direction_bt_20260824).

One-change arms: LT + BRT / VZ / VEC / YH / WPBR (one-at-a-time) + optional all-stack
(all = BRT+VZ+VEC+YH; WPBR is one-change only — not folded into all).
Universe: BRT∪RL via DuckDB. Research only — not advice, not DailyRun.

Example:
  python tools/lt_zones_plus_system_zones_bt.py
  python tools/lt_zones_plus_system_zones_bt.py --limit 40 --workers 4
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import math
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

import duckdb
import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
_TOOLS = Path(__file__).resolve().parent
_SA = _REPO / "stock_analysis"
_PE = _REPO / "drive" / "paul_experiments"
for _p in (_SA, _REPO, _TOOLS, _PE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import lt_zones_daily_to_15m as lt  # noqa: E402
import lt_zones_direction_bt as bt  # noqa: E402
import lt_zones_direction_watch as watch  # noqa: E402
from compare_format import format_money  # noqa: E402
from rocket_brt import (  # noqa: E402
    BRTConfig,
    compute_pivots,
    compute_touch_stream,
    compute_yh_touch_stream,
)
from vec_zones import compute_vec_touch_stream  # noqa: E402
from vol_zone_break_retest import build_zones as vz_build_zones  # noqa: E402

try:
    from wpbr_zones import aggregate_weekly, compute_wpbr_touch_stream  # noqa: E402
except ImportError:
    from stock_analysis.wpbr_zones import (  # noqa: E402
        aggregate_weekly,
        compute_wpbr_touch_stream,
    )

STAMP = "lt_zones_plus_system_zones_20260824"
DEFAULT_OUT = _PE / STAMP
DEFAULT_DB = _REPO / "data" / "ohlcv.duckdb"
UNIV_PATHS = [
    _REPO / "drive" / "universes" / "BRT_new_from_paul_20260822.csv",
    _REPO / "drive" / "universes" / "RL_universe.csv",
]

IS_CUT = bt.IS_CUT
NEAR_PCT = bt.NEAR_PCT
ENTRY_THRESH = bt.ENTRY_THRESH
ZONE_REFRESH = bt.ZONE_REFRESH
WARMUP = bt.WARMUP
MIN_BARS = bt.MIN_BARS
SHEET = bt.SHEET
INIT_ACCT = bt.INIT_ACCT
COSTS_BPS = bt.COSTS_BPS
EXIT_ARM = "exit_40"  # freeze exit; AB is zone-mix only
CONTROL_MIX = "lt_only"
MAX_SYS_ZONES = 8
VZ_LOOKBACK = 126
# House WPBR production DNA (run_wpbr.bat / _UNION_WPBR_DNA)
WPBR_BAND_PCT = 0.015
WPBR_PRE_BARS = 3
WPBR_POST_BARS = 3
WPBR_PIVOT_PCT = 0.10
WPBR_PIVOT_MODE = "either"
WPBR_BO_CONF = 0.03
WPBR_MAX_DAYS_AFTER_RETEST = 2

# Zone-mix arms (one-change vs control)
MIX_ARMS = [
    "lt_only",
    "lt_plus_brt",
    "lt_plus_vz",
    "lt_plus_vec",
    "lt_plus_yh",
    "lt_plus_wpbr",
    "lt_plus_all",
]

TYPE_W = {
    **watch.TYPE_W,
    "sys_brt": 0.70,
    "sys_vz": 0.70,
    "sys_vec": 0.75,
    "sys_yh": 0.95,
    "sys_wpbr": 0.75,
}


def _sortable_th(label: str, sort_type: str) -> str:
    return bt._sortable_th(label, sort_type)


def load_universe() -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for p in UNIV_PATHS:
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            s = line.strip().upper()
            if not s or s.startswith("#") or s == "SYMBOL":
                continue
            if "," in s:
                s = s.split(",")[0].strip().upper()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
    return out


def score_bar_daily_ext(
    *,
    price: float,
    d_open: float,
    d_high: float,
    d_low: float,
    d_close: float,
    p_high: float,
    p_low: float,
    p_close: float,
    zones: list,
    near_pct: float = NEAR_PCT,
) -> float:
    """Same as bt.score_bar_daily but TYPE_W includes sys_* zone types."""
    if not np.isfinite(price) or price <= 0 or not zones:
        return float("nan")

    day_range = max(d_high - d_low, 1e-9)
    day_loc = (d_close - d_low) / day_range
    day_ret = (d_close - p_close) / max(p_close, 1e-9)

    yl = next((z for z in zones if z.zone_type == "yearly_low"), None)
    yh = next((z for z in zones if z.zone_type == "yearly_high"), None)
    poc = next((z for z in zones if z.zone_type == "poc"), None)

    yl_mid = float(yl.mid) if yl else float("nan")
    yh_mid = float(yh.mid) if yh else float("nan")
    poc_mid = float(poc.mid) if poc else float("nan")

    if np.isfinite(yl_mid) and np.isfinite(yh_mid) and yh_mid > yl_mid:
        yr_pos = float(np.clip((price - yl_mid) / (yh_mid - yl_mid), 0.0, 1.0))
        dist_yl = (price - yl_mid) / price
        dist_yh = (yh_mid - price) / price
    else:
        yr_pos = 0.5
        dist_yl = dist_yh = float("nan")

    up = 0.0
    down = 0.0

    # Patch TYPE_W for nearest-side ranking
    old_w = watch.TYPE_W
    watch.TYPE_W = TYPE_W
    try:
        sup, d_sup = watch._nearest_side(price, zones, side="support", near_pct=near_pct)
        if sup is not None and d_sup <= near_pct and price >= float(sup.lo) * 0.999:
            w = TYPE_W.get(sup.zone_type, 0.4)
            prox = 1.0 - (d_sup / max(near_pct, 1e-9))
            pts = 42.0 * w * max(prox, 0.15)
            if getattr(sup, "confluence", None):
                pts *= 1.15
            up += pts

        res, d_res = watch._nearest_side(price, zones, side="resistance", near_pct=near_pct)
        if res is not None and d_res <= near_pct and price <= float(res.hi) * 1.001:
            w = TYPE_W.get(res.zone_type, 0.4)
            prox = 1.0 - (d_res / max(near_pct, 1e-9))
            pts = 42.0 * w * max(prox, 0.15)
            if getattr(res, "confluence", None):
                pts *= 1.15
            failing = day_loc < 0.45 or price < float(res.mid)
            if failing:
                pts *= 1.1
            down += pts
    finally:
        watch.TYPE_W = old_w

    if poc is not None and np.isfinite(poc_mid):
        above_poc = price >= poc_mid
        prior_above = p_close >= poc_mid
        if above_poc and not prior_above:
            up += 14.0
        elif (not above_poc) and prior_above:
            down += 14.0
        elif above_poc:
            up += 6.0
        else:
            down += 6.0

    hvns = [z for z in zones if z.zone_type == "hvn"]
    if hvns:
        below = [z for z in hvns if z.mid <= price]
        above = [z for z in hvns if z.mid >= price]
        if below:
            zb = min(below, key=lambda z: watch._dist_to_zone(price, z))
            db = watch._dist_to_zone(price, zb)
            if db <= near_pct:
                up += 8.0 * (1.0 - db / near_pct)
        if above:
            za = min(above, key=lambda z: watch._dist_to_zone(price, z))
            da = watch._dist_to_zone(price, za)
            if da <= near_pct:
                down += 8.0 * (1.0 - da / near_pct)

    if np.isfinite(dist_yl) and np.isfinite(dist_yh):
        up += (1.0 - yr_pos) * 12.0
        down += yr_pos * 12.0
        if dist_yl <= near_pct:
            up += 18.0 * (1.0 - dist_yl / near_pct)
        if dist_yh <= near_pct:
            down += 18.0 * (1.0 - dist_yh / near_pct)

    if day_loc >= 0.70:
        up += 7.0
    elif day_loc <= 0.30:
        down += 7.0

    if price > p_high:
        up += 10.0
    elif price < p_low:
        down += 10.0

    if d_open > p_high:
        up += 4.0
    elif d_open < p_low:
        down += 4.0

    up += max(0.0, day_ret) * 180.0
    down += max(0.0, -day_ret) * 180.0
    return float(up - down)


def precompute_brt_events(df: pd.DataFrame) -> list[dict[str, Any]]:
    """House BRT matured pivot bands; visible from maturity bar (as-of filter).

    Sheet-lag maturity marks bar ``i`` when the strong touch lived on ``i - lag``;
    zone bounds are read from that touch bar (zc/zl/zh are often NaN on ``i`` itself).
    Pivot displacement confirm uses house ``pivot_d`` (documented).
    """
    cfg = BRTConfig()
    ph, pl, php, plp = compute_pivots(
        df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m
    )
    l3 = compute_touch_stream(
        df,
        ph,
        pl,
        php,
        plp,
        cfg.band_pct,
        cfg.lookback_long,
        cfg.touch_threshold,
        cfg.lookback_short,
        strong_pivots_enabled=cfg.strong_pivots_enabled,
        strong_pre_pivot_bars=cfg.strong_pre_pivot_bars,
        strong_pre_pivot_pct=cfg.strong_pre_pivot_pct,
        strong_post_pivot_bars=cfg.strong_post_pivot_bars,
        strong_post_pivot_pct=cfg.strong_post_pivot_pct,
        strong_pivot_mode=getattr(cfg, "strong_pivot_mode", "pre"),
        zone_price_round_decimals=cfg.zone_price_round_decimals,
        realtime_filter_enabled=False,
    )
    lag = int(getattr(cfg, "sheet_maturity_lag_bars", 0) or 0)
    if lag <= 0:
        lag = int(getattr(cfg, "strong_post_pivot_bars", 7) or 7)
    matured = l3["matured_now"].to_numpy(bool)
    zl = l3["zone_low"].to_numpy(float)
    zh = l3["zone_high"].to_numpy(float)
    zc = l3["zone_center"].to_numpy(float)
    events: list[dict[str, Any]] = []
    for i in np.flatnonzero(matured):
        src = int(i) - lag
        lo = hi = mid = float("nan")
        for j in range(src, max(-1, src - 30), -1):
            if j < 0:
                break
            if np.isfinite(zc[j]) and float(zc[j]) > 0 and np.isfinite(zl[j]) and np.isfinite(zh[j]):
                lo, hi, mid = float(zl[j]), float(zh[j]), float(zc[j])
                break
        if not (np.isfinite(lo) and np.isfinite(hi) and mid > 0):
            continue
        events.append(
            {
                "asof": int(i),
                "lo": lo,
                "hi": hi,
                "mid": mid,
                "zone_type": "sys_brt",
                "source": f"brt_matured_bar_{int(i)}",
                "strength": 70.0,
                "touches": 2,
            }
        )
    return events


def precompute_yh_events(df: pd.DataFrame) -> list[dict[str, Any]]:
    cfg = BRTConfig()
    l3 = compute_yh_touch_stream(
        df,
        cfg.band_pct,
        cfg.lookback_long,
        cfg.touch_threshold,
        cfg.lookback_short,
        zone_price_round_decimals=cfg.zone_price_round_decimals,
        yh_lookback=int(getattr(cfg, "yh_lookback", 252) or 252),
        yh_move_away_pct=float(getattr(cfg, "yh_move_away_pct", 0.03) or 0.03),
    )
    events: list[dict[str, Any]] = []
    for ev in l3.get("yh_zone_events") or []:
        lo = float(ev["zone_lower"])
        hi = float(ev["zone_upper"])
        mid = float(ev["zone_center"])
        events.append(
            {
                "asof": int(ev["activation_bar"]),
                "lo": lo,
                "hi": hi,
                "mid": mid,
                "zone_type": "sys_yh",
                "source": f"yh_act_{int(ev['activation_bar'])}",
                "strength": 90.0,
                "touches": 1,
            }
        )
    return events


def precompute_vec_events(df: pd.DataFrame) -> list[dict[str, Any]]:
    cfg = BRTConfig()
    l3 = compute_vec_touch_stream(
        df,
        cfg.band_pct,
        cfg.lookback_long,
        cfg.touch_threshold,
        cfg.lookback_short,
        zone_price_round_decimals=cfg.zone_price_round_decimals,
        vec_vp_lookback=int(getattr(cfg, "vec_vp_lookback", 60) or 60),
        vec_vp_bin_pct=float(getattr(cfg, "vec_vp_bin_pct", 0.005) or 0.005),
        vec_prior_bars=int(getattr(cfg, "vec_prior_bars", 5) or 5),
        vec_prior_side=str(getattr(cfg, "vec_prior_side", "high") or "high"),
        vec_confluence_pct=float(getattr(cfg, "vec_confluence_pct", 0.0075) or 0.0075),
        vec_move_away_pct=float(getattr(cfg, "vec_move_away_pct", 0.02) or 0.02),
        vec_min_bars_between=int(getattr(cfg, "vec_min_bars_between", 20) or 20),
    )
    events: list[dict[str, Any]] = []
    for ev in l3.get("vec_zone_events") or l3.get("yh_zone_events") or []:
        lo = float(ev["zone_lower"])
        hi = float(ev["zone_upper"])
        mid = float(ev["zone_center"])
        events.append(
            {
                "asof": int(ev["activation_bar"]),
                "lo": lo,
                "hi": hi,
                "mid": mid,
                "zone_type": "sys_vec",
                "source": f"vec_act_{int(ev['activation_bar'])}",
                "strength": 75.0,
                "touches": 1,
            }
        )
    return events


def precompute_vz_events(df: pd.DataFrame) -> list[dict[str, Any]]:
    if len(df) <= VZ_LOOKBACK:
        return []
    zones = vz_build_zones(df, VZ_LOOKBACK)
    events: list[dict[str, Any]] = []
    for z in zones:
        if z.kind != "HL":
            continue
        events.append(
            {
                "asof": int(z.created_on_idx),
                "lo": float(z.lo),
                "hi": float(z.hi),
                "mid": 0.5 * (float(z.lo) + float(z.hi)),
                "zone_type": "sys_vz",
                "source": f"vz_hl_{z.zone_id}",
                "strength": 70.0,
                "touches": 1,
            }
        )
    return events


def precompute_wpbr_events(df: pd.DataFrame) -> list[dict[str, Any]]:
    """House WPBR weekly pivot bands; as-of after post-pivot confirm (no lookahead).

    ``compute_wpbr_touch_stream`` tags ``activation_bar`` at pivot-week Monday, but a
    strong weekly pivot needs ``strong_post_pivot_bars`` weeks of future highs/lows
    before it is knowable. Visible from the last daily bar of week ``wi + post_bars``.

    DuckDB loader keeps a ``Date`` column + RangeIndex; WPBR needs DatetimeIndex.
    """
    if "Date" in df.columns:
        wdf = df.set_index("Date").sort_index()
    else:
        wdf = df
    if not isinstance(wdf.index, pd.DatetimeIndex):
        wdf = wdf.copy()
        wdf.index = pd.to_datetime(wdf.index)
    l3 = compute_wpbr_touch_stream(
        wdf,
        band_pct=WPBR_BAND_PCT,
        strong_pre_pivot_bars=WPBR_PRE_BARS,
        strong_pre_pivot_pct=WPBR_PIVOT_PCT,
        strong_post_pivot_bars=WPBR_POST_BARS,
        strong_post_pivot_pct=WPBR_PIVOT_PCT,
        strong_pivot_mode=WPBR_PIVOT_MODE,
        breakout_confirmation=WPBR_BO_CONF,
        max_days_after_retest=WPBR_MAX_DAYS_AFTER_RETEST,
        retest_mode="stop_looking",
        zone_price_round_decimals=2,
        merge_overlapping_zones=False,
    )
    weekly = aggregate_weekly(wdf)
    if weekly.empty:
        return []
    w_ends = {pd.Timestamp(t).normalize(): i for i, t in enumerate(weekly.index)}
    dates_norm = pd.DatetimeIndex(wdf.index).normalize().to_numpy()
    n = len(wdf)
    events: list[dict[str, Any]] = []
    for ev in l3.get("wpbr_zone_events") or []:
        pwe = pd.Timestamp(ev["pivot_week_end"]).normalize()
        wi = w_ends.get(pwe)
        if wi is None:
            continue
        conf_wi = int(wi) + WPBR_POST_BARS
        if conf_wi >= len(weekly):
            continue
        conf_end = pd.Timestamp(weekly.index[conf_wi]).normalize().to_numpy()
        asof = int(np.searchsorted(dates_norm, conf_end, side="right")) - 1
        if asof < 0:
            continue
        asof = min(n - 1, asof)
        lo = float(ev["zone_lower"])
        hi = float(ev["zone_upper"])
        mid = float(ev["zone_center"])
        if not (np.isfinite(lo) and np.isfinite(hi) and mid > 0):
            continue
        strength = float(ev.get("wpbr_zone_strength") or 0.0)
        events.append(
            {
                "asof": asof,
                "lo": lo,
                "hi": hi,
                "mid": mid,
                "zone_type": "sys_wpbr",
                "source": f"wpbr_{ev.get('wpbr_zone_id', asof)}",
                "strength": 50.0 + 50.0 * max(0.0, min(1.0, strength)),
                "touches": 1,
            }
        )
    return events


def events_asof(
    events: list[dict[str, Any]],
    *,
    asof_i: int,
    symbol: str,
    price: float,
    max_zones: int = MAX_SYS_ZONES,
    tol_pct: float = 0.005,
) -> list[lt.Zone]:
    ready = [e for e in events if int(e["asof"]) <= asof_i]
    if not ready or not np.isfinite(price) or price <= 0:
        return []
    # Prefer most recently activated zone per mid-cluster, then nearest to price.
    ready = sorted(ready, key=lambda e: -int(e["asof"]))
    deduped: list[dict[str, Any]] = []
    for e in ready:
        mid = float(e["mid"])
        if mid <= 0:
            continue
        if any(abs(float(p["mid"]) - mid) / mid <= tol_pct for p in deduped):
            continue
        deduped.append(e)
    deduped.sort(key=lambda e: abs(float(e["mid"]) - price) / price)
    out: list[lt.Zone] = []
    for e in deduped[:max_zones]:
        out.append(
            lt.Zone(
                symbol,
                str(e["zone_type"]),
                float(e["lo"]),
                float(e["hi"]),
                int(e.get("touches", 1)),
                str(e.get("source", e["zone_type"])),
                mid=float(e["mid"]),
                strength=float(e.get("strength", 50.0)),
            )
        )
    return out


def mix_extras(mix: str) -> set[str]:
    if mix == "lt_only":
        return set()
    if mix == "lt_plus_all":
        # Frozen prior all-stack (no WPBR) so prior arm stays comparable.
        return {"brt", "vz", "vec", "yh"}
    if mix.startswith("lt_plus_"):
        return {mix.split("lt_plus_", 1)[1]}
    raise ValueError(mix)


def build_mix_scores(
    df: pd.DataFrame,
    symbol: str,
    sys_events: dict[str, list[dict[str, Any]]],
) -> dict[str, np.ndarray]:
    n = len(df)
    scores = {m: np.full(n, np.nan, dtype=float) for m in MIX_ARMS}
    if n < WARMUP + 2:
        return scores

    opens = df["Open"].to_numpy(float)
    highs = df["High"].to_numpy(float)
    lows = df["Low"].to_numpy(float)
    closes = df["Close"].to_numpy(float)

    lt_zones: list = []
    last_z = -10**9
    for i in range(WARMUP, n):
        if (i - last_z) >= ZONE_REFRESH or not lt_zones:
            lt_zones = lt.compute_lt_zones(
                df.iloc[: i + 1],
                symbol,
                include_lvn=False,
                max_swing=6,
            )
            last_z = i
        px = float(closes[i])
        extras = {
            "brt": events_asof(sys_events["brt"], asof_i=i, symbol=symbol, price=px),
            "vz": events_asof(sys_events["vz"], asof_i=i, symbol=symbol, price=px),
            "vec": events_asof(sys_events["vec"], asof_i=i, symbol=symbol, price=px),
            "yh": events_asof(sys_events["yh"], asof_i=i, symbol=symbol, price=px),
            "wpbr": events_asof(sys_events["wpbr"], asof_i=i, symbol=symbol, price=px),
        }
        for mix in MIX_ARMS:
            zones = list(lt_zones)
            for key in mix_extras(mix):
                zones.extend(extras[key])
            if not zones:
                continue
            scores[mix][i] = score_bar_daily_ext(
                price=px,
                d_open=opens[i],
                d_high=highs[i],
                d_low=lows[i],
                d_close=closes[i],
                p_high=highs[i - 1],
                p_low=lows[i - 1],
                p_close=closes[i - 1],
                zones=zones,
                near_pct=NEAR_PCT,
            )
    return scores


def process_symbol_chunk(
    args: tuple[str, list[str]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    db_path, symbols = args
    con = duckdb.connect(db_path, read_only=True)
    all_trades: list[dict[str, Any]] = []
    meta = {
        "ok": 0,
        "skip_short": 0,
        "skip_empty": 0,
        "errors": 0,
        "scored_bars": 0,
        "sys_counts": Counter(),
    }
    try:
        for sym in symbols:
            try:
                df = bt.load_symbol_df(con, sym)
                if df.empty:
                    meta["skip_empty"] += 1
                    continue
                if len(df) < MIN_BARS:
                    meta["skip_short"] += 1
                    continue
                sys_events = {
                    "brt": precompute_brt_events(df),
                    "vz": precompute_vz_events(df),
                    "vec": precompute_vec_events(df),
                    "yh": precompute_yh_events(df),
                    "wpbr": precompute_wpbr_events(df),
                }
                for k, evs in sys_events.items():
                    meta["sys_counts"][k] += len(evs)
                mix_scores = build_mix_scores(df, sym, sys_events)
                meta["scored_bars"] += int(np.isfinite(mix_scores[CONTROL_MIX]).sum())
                for mix, scores in mix_scores.items():
                    trades = bt.simulate_arm(
                        df, scores, sym, EXIT_ARM, entry_thresh=ENTRY_THRESH
                    )
                    for t in trades:
                        t["arm"] = mix  # repurpose arm field as zone-mix
                        t["exit_arm"] = EXIT_ARM
                    all_trades.extend(trades)
                meta["ok"] += 1
            except Exception as e:
                meta["errors"] += 1
                # Surface root cause — silent swallow previously published all-zero stamps
                print(f"  [lt+sys] ERROR {sym}: {type(e).__name__}: {e}", flush=True)
    finally:
        con.close()
    # Counter not picklable cleanly across some paths — convert
    meta["sys_counts"] = dict(meta["sys_counts"])
    return all_trades, meta


def judge_arm_vs_control(
    arm_is: dict[str, Any],
    ctrl_is: dict[str, Any],
    arm_oos: dict[str, Any],
    ctrl_oos: dict[str, Any],
) -> tuple[str, str]:
    """IS-primary help/hurt; OOS report-only softener."""
    if arm_is["n"] < 30:
        return "HOLD", "thin IS N"

    d_avg = arm_is["avg_pnl"] - ctrl_is["avg_pnl"]
    d_pf = arm_is["pf"] - ctrl_is["pf"]
    d_wr = arm_is["wr"] - ctrl_is["wr"]
    n_ratio = arm_is["n"] / max(ctrl_is["n"], 1)

    # Quality over count: need avg and PF lift (or clear WR+avg) without N collapse
    helped = (d_avg >= 0.02 and d_pf >= 0.02) or (d_avg >= 0.03 and d_wr >= 0.5)
    hurt = (d_avg <= -0.02 and d_pf <= -0.02) or (d_avg <= -0.03 and d_wr <= -0.5)
    if n_ratio < 0.5 and helped:
        return "HOLD", "IS quality up but N collapsed (>50%)"

    oos_soft = (
        arm_oos["n"] >= 15
        and (arm_oos["avg_pnl"] - ctrl_oos["avg_pnl"]) < -0.02
        and (arm_oos["pf"] - ctrl_oos["pf"]) < -0.02
    )

    if helped and oos_soft:
        return "HOLD", "IS helped but OOS softened vs control (report-only)"
    if helped:
        # Still not KEEP — single study / direction score already DISMISS context
        return "LEAN HELP", "IS quality improved vs LT-only"
    if hurt:
        return "HURT", "IS quality worse vs LT-only"
    return "FLAT", "no material IS quality change"


def overall_verdict(judgments: dict[str, tuple[str, str]], by_mix: dict) -> tuple[str, str]:
    helps = [a for a, (j, _) in judgments.items() if a != CONTROL_MIX and j.startswith("LEAN HELP")]
    hurts = [a for a, (j, _) in judgments.items() if a != CONTROL_MIX and j == "HURT"]
    holds = [a for a, (j, _) in judgments.items() if a != CONTROL_MIX and j == "HOLD"]
    ctrl = by_mix[CONTROL_MIX]
    isi = ctrl["IS"]
    base_weak = not (isi["avg_pnl"] > 0 and isi["pf"] > 1.0 and isi["wr"] >= 50.0)

    if helps and not hurts:
        return "HOLD", (
            f"System zones show IS lean-help on {', '.join(f'`{h}`' for h in helps)}; "
            "still research-only (base score was DISMISS; no KEEP / no DailyRun)."
        )
    if helps and hurts:
        return "HOLD", (
            f"Mixed: lean-help {', '.join(f'`{h}`' for h in helps)}, "
            f"hurt {', '.join(f'`{h}`' for h in hurts)}. "
            "Do not stack blindly; OOS report-only."
        )
    if base_weak and (hurts or not helps):
        return "DISMISS", (
            "Adding house-system zones does not rescue LT-direction predictability "
            f"(hurt={len(hurts)}, hold/flat={len(holds)}; control remains weak)."
        )
    return "DISMISS", "No KEEP-quality lift from system-zone mix vs LT-only."


def write_compare_html(
    path: Path,
    by_mix: dict[str, dict[str, dict]],
    judgments: dict[str, tuple[str, str]],
    meta: dict,
    verdict: str,
    verdict_note: str,
) -> None:
    headers = [
        ("Mix arm", "text"),
        ("Judge (IS)", "text"),
        ("Slice", "text"),
        ("N", "num"),
        ("WR%", "num"),
        ("Avg PnL%", "num"),
        ("ΔAvg vs ctrl", "num"),
        ("PF", "num"),
        ("ΔPF vs ctrl", "num"),
        ("Sheet PnL $", "num"),
        ("Avg days", "num"),
        ("WO max Avg%", "num"),
        ("Ann ROR%", "num"),
        ("Max DD%", "num"),
        ("Long N", "num"),
        ("Short N", "num"),
        ("Note", "text"),
    ]
    ths = "".join(_sortable_th(h, t) for h, t in headers)
    rows = []
    ctrl = by_mix[CONTROL_MIX]
    for mix in MIX_ARMS:
        jtag, jnote = judgments.get(mix, ("—", ""))
        for sl in ("IS", "OOS", "ALL"):
            s = by_mix[mix][sl]
            c = ctrl[sl]
            d_avg = s["avg_pnl"] - c["avg_pnl"] if mix != CONTROL_MIX else 0.0
            d_pf = s["pf"] - c["pf"] if mix != CONTROL_MIX else 0.0
            mark = " control" if mix == CONTROL_MIX and sl == "IS" else ""
            cells = [
                mix,
                jtag if sl == "IS" else "—",
                sl,
                bt._fmt(s["n"], "int"),
                bt._fmt(s["wr"], "pct"),
                bt._fmt(s["avg_pnl"]),
                f"{d_avg:+.3f}" if mix != CONTROL_MIX else "—",
                bt._fmt(s["pf"]),
                f"{d_pf:+.3f}" if mix != CONTROL_MIX else "—",
                bt._fmt(s["sheet"], "money"),
                bt._fmt(s["avg_days"]),
                bt._fmt(s["wo_max"]),
                bt._fmt(s["ann_ror"], "pct") if math.isfinite(s["ann_ror"]) else "—",
                bt._fmt(s["max_dd"], "pct") if math.isfinite(s["max_dd"]) else "—",
                bt._fmt(s["long_n"], "int"),
                bt._fmt(s["short_n"], "int"),
                jnote if sl == "IS" else "",
            ]
            tds = "".join(f"<td>{html_mod.escape(str(c))}</td>" for c in cells)
            rows.append(f'<tr class="{sl.lower()}{mark}">{tds}</tr>')

    help_rows = []
    for mix in MIX_ARMS:
        if mix == CONTROL_MIX:
            continue
        jtag, jnote = judgments[mix]
        isi, oos = by_mix[mix]["IS"], by_mix[mix]["OOS"]
        cis, cos = ctrl["IS"], ctrl["OOS"]
        help_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(mix)}</td>"
            f"<td>{html_mod.escape(jtag)}</td>"
            f"<td>{isi['avg_pnl'] - cis['avg_pnl']:+.3f}</td>"
            f"<td>{isi['pf'] - cis['pf']:+.3f}</td>"
            f"<td>{isi['wr'] - cis['wr']:+.2f}</td>"
            f"<td>{oos['avg_pnl'] - cos['avg_pnl']:+.3f}</td>"
            f"<td>{oos['pf'] - cos['pf']:+.3f}</td>"
            f"<td>{html_mod.escape(jnote)}</td>"
            "</tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>{STAMP} — LT + system zones AB</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 24px; background:#f7f6f2; color:#1a1a1a; }}
h1 {{ font-size: 1.35rem; }}
.meta {{ color:#444; max-width: 980px; }}
table.sortable {{ border-collapse: collapse; background:#fff; margin: 16px 0 28px; font-size: 0.9rem; }}
th, td {{ border: 1px solid #d8d5cc; padding: 6px 8px; text-align: left; }}
th {{ background:#efece4; }}
tr.is {{ background:#fafaf7; }}
tr.oos {{ background:#f3f7fb; }}
tr.control {{ outline: 2px solid #3d6b9a; }}
.verdict {{ padding: 12px 14px; background:#fff; border-left: 4px solid #3d6b9a; margin: 12px 0 20px; }}
{bt.SORTABLE_TH_CSS}
</style></head><body>
<h1>LT zones + system zones — predictability AB</h1>
<p class="meta">Stamp <code>{html_mod.escape(STAMP)}</code> · as-of {html_mod.escape(meta.get('asof',''))} ·
universe BRT∪RL ({meta.get('n_ok')}/{meta.get('n_universe')} scored) ·
exit freeze <code>{EXIT_ARM}</code> · entry |net|≥{ENTRY_THRESH:g} ·
Click column headers to sort.</p>
<div class="verdict"><strong>Verdict: {html_mod.escape(verdict)}</strong> — {html_mod.escape(verdict_note)}</div>
<p class="meta">Research only. Not financial advice. Not DailyRun. OOS is report-only.</p>

<h2>Help / hurt vs LT-only (IS primary)</h2>
<table class="sortable">
<thead><tr>
{_sortable_th("Mix", "text")}
{_sortable_th("Judge", "text")}
{_sortable_th("IS ΔAvg%", "num")}
{_sortable_th("IS ΔPF", "num")}
{_sortable_th("IS ΔWR", "num")}
{_sortable_th("OOS ΔAvg%", "num")}
{_sortable_th("OOS ΔPF", "num")}
{_sortable_th("Note", "text")}
</tr></thead>
<tbody>
{''.join(help_rows)}
</tbody></table>

<h2>Full book by mix × slice</h2>
<table class="sortable">
<thead><tr>{ths}</tr></thead>
<tbody>
{''.join(rows)}
</tbody></table>

<h2>System zone definitions (as-of, no lookahead)</h2>
<ul>
<li><b>BRT</b>: house pivot touch-stream matured bands (±band_pct); visible from sheet-lag maturity bar (bounds from touch bar; house pivot confirm uses <code>pivot_d</code>).</li>
<li><b>VZ</b>: vol-zone HL bands from rolling max-vol winners (lookback {VZ_LOOKBACK}); as-of <code>created_on_idx</code>.</li>
<li><b>VEC</b>: VP POC ∩ prior-period extreme confluence activations (house <code>compute_vec_touch_stream</code>).</li>
<li><b>YH</b>: activated year-high zones (house <code>compute_yh_touch_stream</code>).</li>
<li><b>WPBR</b> (Pivot Break and Retest): weekly strong-pivot bands (±{WPBR_BAND_PCT*100:.1f}%, pre/post {WPBR_PRE_BARS}/{WPBR_POST_BARS} × {WPBR_PIVOT_PCT*100:.0f}% either-mode); as-of last daily bar of week <code>pivot + {WPBR_POST_BARS}</code> (no lookahead vs stream's pivot-Monday tag).</li>
<li>Each mix keeps up to {MAX_SYS_ZONES} nearest system zones to price; LT zones always included except control extras=none.</li>
<li><code>lt_plus_all</code> remains BRT+VZ+VEC+YH (WPBR is one-change only).</li>
</ul>
{bt.SORT_JS}
</body></html>
"""
    path.write_text(html, encoding="utf-8")


def write_baseline_md(
    path: Path,
    by_mix: dict,
    judgments: dict[str, tuple[str, str]],
    meta: dict,
    verdict: str,
    verdict_note: str,
) -> None:
    ctrl = by_mix[CONTROL_MIX]
    lines = [
        f"# BASELINE — LT + system zones predictability AB",
        "",
        f"**Stamp:** `{STAMP}`",
        f"**As-of:** {meta.get('asof')}",
        f"**Verdict:** **{verdict}** — {verdict_note}",
        "**Status:** research only — **not** financial advice, **not** gold, **not** DailyRun.",
        "",
        "## Hypothesis",
        "",
        "Does adding each house system's zones (BRT / VZ / VEC / YH / WPBR) into the LT-direction",
        "score mix improve forward predictability vs LT zones alone?",
        "",
        "## Freeze",
        "",
        "| Knob | Value |",
        "|------|-------|",
        f"| Control mix | `{CONTROL_MIX}` |",
        f"| Entry | next open after \\|net\\| ≥ {ENTRY_THRESH:g} |",
        f"| Exit | **frozen** `{EXIT_ARM}` (not selected from this AB) |",
        "| Score | daily-only LT direction score (+ sys zone proximity when armed) |",
        f"| Zone refresh | every {ZONE_REFRESH} trading days |",
        f"| Near % | {NEAR_PCT * 100:.1f}% |",
        f"| Max system zones / type | {MAX_SYS_ZONES} nearest to price |",
        f"| Sizing | sheet ${SHEET:,.0f}; Initial_Account ${INIT_ACCT:,.0f} |",
        f"| Costs | {COSTS_BPS} bps |",
        f"| WPBR DNA | band={WPBR_BAND_PCT}; pre/post={WPBR_PRE_BARS}/{WPBR_POST_BARS}×{WPBR_PIVOT_PCT}; mode={WPBR_PIVOT_MODE}; as-of=pivot+{WPBR_POST_BARS}w |",
        "",
        "### Mix arms (one-change)",
        "",
        "| Arm | Zones |",
        "|-----|-------|",
        "| `lt_only` | LT yearly + swing S/R + VP (poc/hvn) |",
        "| `lt_plus_brt` | LT + matured BRT pivot bands |",
        "| `lt_plus_vz` | LT + VZ HL max-vol bands |",
        "| `lt_plus_vec` | LT + VEC confluence activations |",
        "| `lt_plus_yh` | LT + YH activated year-high bands |",
        "| `lt_plus_wpbr` | LT + WPBR weekly pivot bands (Pivot Break and Retest) |",
        "| `lt_plus_all` | LT + BRT + VZ + VEC + YH (WPBR not stacked) |",
        "",
        "## Universe / data",
        "",
        "| Item | Value |",
        "|------|-------|",
        "| Source | `data/ohlcv.duckdb` `prices` |",
        "| Universe | BRT_new_from_paul_20260822 ∪ RL_universe |",
        f"| Symbols scored | {meta.get('n_ok')} / {meta.get('n_universe')} |",
        f"| Skipped short/empty/err | {meta.get('skip_short')} / {meta.get('skip_empty')} / {meta.get('errors')} |",
        f"| Date range | {meta.get('date_min')} → {meta.get('date_max')} |",
        f"| IS / OOS | entry_date < {IS_CUT.isoformat()} vs ≥ |",
        f"| Sys zone event counts (sum) | {meta.get('sys_counts')} |",
        "",
        "## Control snapshot (`lt_only` / `exit_40`)",
        "",
        "| Slice | N | WR% | Avg% | PF | Sheet |",
        "|-------|---|-----|------|----|-------|",
    ]
    for sl in ("IS", "OOS", "ALL"):
        s = ctrl[sl]
        lines.append(
            f"| {sl} | {s['n']} | {s['wr']:.1f} | {s['avg_pnl']:.3f} | {s['pf']:.2f} | {format_money(s['sheet'])} |"
        )
    lines.extend(
        [
            "",
            "## Help / hurt table (IS primary; OOS report-only)",
            "",
            "| Mix | Judge | IS ΔAvg | IS ΔPF | IS ΔWR | OOS ΔAvg | OOS ΔPF | Note |",
            "|-----|-------|---------|--------|--------|----------|---------|------|",
        ]
    )
    for mix in MIX_ARMS:
        if mix == CONTROL_MIX:
            continue
        j, note = judgments[mix]
        isi, oos = by_mix[mix]["IS"], by_mix[mix]["OOS"]
        cis, cos = ctrl["IS"], ctrl["OOS"]
        lines.append(
            f"| `{mix}` | **{j}** | {isi['avg_pnl']-cis['avg_pnl']:+.3f} | "
            f"{isi['pf']-cis['pf']:+.3f} | {isi['wr']-cis['wr']:+.2f} | "
            f"{oos['avg_pnl']-cos['avg_pnl']:+.3f} | {oos['pf']-cos['pf']:+.3f} | {note} |"
        )
    lines.extend(
        [
            "",
            "## Anti-overfit",
            "",
            "- OOS report-only — do not retune mix on OOS.",
            "- Exit frozen at prior control `exit_40` (selection bias avoided on exits).",
            "- Quality over N; base LT-direction score already DISMISS on full DuckDB.",
            "- Research candidate ≠ gold ≠ DailyRun.",
            "",
            "## Disclaimer",
            "",
            "Educational / research only. Not trade instructions.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_summary_md(
    path: Path,
    by_mix: dict,
    judgments: dict[str, tuple[str, str]],
    meta: dict,
    verdict: str,
    verdict_note: str,
) -> None:
    ctrl = by_mix[CONTROL_MIX]
    lines = [
        f"# SUMMARY — `{STAMP}`",
        "",
        f"**Verdict:** **{verdict}** — {verdict_note}",
        "",
        "Research only. Not advice. Not DailyRun.",
        "",
        f"- Universe: BRT∪RL · scored **{meta.get('n_ok')}** / {meta.get('n_universe')}",
        f"- Data: `{meta.get('date_min')}` → `{meta.get('date_max')}`",
        f"- Exit freeze: `{EXIT_ARM}` · entry |net|≥{ENTRY_THRESH:g}",
        "",
        "## Help / hurt",
        "",
        "| Mix | Judge | IS N | IS Avg% | IS PF | OOS Avg% | OOS PF |",
        "|-----|-------|------|---------|-------|----------|--------|",
    ]
    for mix in MIX_ARMS:
        j = judgments.get(mix, ("—", ""))[0]
        isi, oos = by_mix[mix]["IS"], by_mix[mix]["OOS"]
        mark = " *" if mix == CONTROL_MIX else ""
        lines.append(
            f"| `{mix}`{mark} | {j} | {isi['n']} | {isi['avg_pnl']:.3f} | {isi['pf']:.2f} | "
            f"{oos['avg_pnl']:.3f} | {oos['pf']:.2f} |"
        )
    lines.extend(
        [
            "",
            f"Control IS: WR {ctrl['IS']['wr']:.1f}% Avg {ctrl['IS']['avg_pnl']:.3f}% PF {ctrl['IS']['pf']:.2f}",
            "",
            "## Files",
            "",
            "- `compare.html`",
            "- `BASELINE.md`",
            "- `LTPS_Closed_*.csv` / `LTPS_Metrics_*.csv`",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=max(1, min(6, (os_cpu := __import__("os").cpu_count() or 4))))
    ap.add_argument("--symbols", type=str, default="", help="Comma override")
    args = ap.parse_args(argv)

    out: Path = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    asof = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if args.symbols.strip():
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = load_universe()
    if args.limit and args.limit > 0:
        symbols = symbols[: args.limit]

    # Intersect with DuckDB
    con = duckdb.connect(str(args.db), read_only=True)
    db_syms = {
        r[0]
        for r in con.execute("SELECT DISTINCT symbol FROM prices").fetchall()
    }
    con.close()
    symbols = [s for s in symbols if s in db_syms]
    print(f"[lt+sys] stamp={STAMP} symbols={len(symbols)} workers={args.workers}", flush=True)

    t0 = time.time()
    chunks = bt.chunked(symbols, args.workers)
    all_trades: list[dict[str, Any]] = []
    meta_acc = {
        "ok": 0,
        "skip_short": 0,
        "skip_empty": 0,
        "errors": 0,
        "scored_bars": 0,
        "sys_counts": Counter(),
    }
    work = [(str(args.db), ch) for ch in chunks]
    if args.workers <= 1 or len(chunks) <= 1:
        for w in work:
            trades, m = process_symbol_chunk(w)
            all_trades.extend(trades)
            for k in ("ok", "skip_short", "skip_empty", "errors", "scored_bars"):
                meta_acc[k] += m[k]
            meta_acc["sys_counts"].update(m.get("sys_counts") or {})
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(process_symbol_chunk, w): i for i, w in enumerate(work)}
            for fut in as_completed(futs):
                trades, m = fut.result()
                all_trades.extend(trades)
                for k in ("ok", "skip_short", "skip_empty", "errors", "scored_bars"):
                    meta_acc[k] += m[k]
                meta_acc["sys_counts"].update(m.get("sys_counts") or {})
                print(f"  chunk done ok+={m['ok']} errors+={m['errors']}", flush=True)

    # Date range
    date_min = date_max = ""
    if all_trades:
        opens = [pd.Timestamp(t["opened"]) for t in all_trades]
        date_min = min(opens).date().isoformat()
        date_max = max(pd.Timestamp(t["closed"]) for t in all_trades).date().isoformat()

    meta = {
        "asof": asof,
        "n_universe": len(symbols),
        "n_ok": meta_acc["ok"],
        "skip_short": meta_acc["skip_short"],
        "skip_empty": meta_acc["skip_empty"],
        "errors": meta_acc["errors"],
        "scored_bars": meta_acc["scored_bars"],
        "sys_counts": dict(meta_acc["sys_counts"]),
        "date_min": date_min,
        "date_max": date_max,
        "elapsed_sec": round(time.time() - t0, 1),
    }

    by_mix: dict[str, dict[str, dict]] = {}
    for mix in MIX_ARMS:
        sub = [t for t in all_trades if t["arm"] == mix]
        by_mix[mix] = {
            "ALL": bt.book_stats(sub),
            "IS": bt.book_stats([t for t in sub if t["slice"] == "IS"]),
            "OOS": bt.book_stats([t for t in sub if t["slice"] == "OOS"]),
        }

    judgments: dict[str, tuple[str, str]] = {CONTROL_MIX: ("CONTROL", "LT zones alone")}
    for mix in MIX_ARMS:
        if mix == CONTROL_MIX:
            continue
        judgments[mix] = judge_arm_vs_control(
            by_mix[mix]["IS"],
            by_mix[CONTROL_MIX]["IS"],
            by_mix[mix]["OOS"],
            by_mix[CONTROL_MIX]["OOS"],
        )

    verdict, verdict_note = overall_verdict(judgments, by_mix)

    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    closed_path = out / f"LTPS_Closed_{day}.csv"
    metrics_path = out / f"LTPS_Metrics_{day}.csv"
    bt.write_closed_csv(closed_path, all_trades)

    # metrics csv
    mrows = []
    for mix in MIX_ARMS:
        jtag, jnote = judgments[mix]
        for sl in ("ALL", "IS", "OOS"):
            s = by_mix[mix][sl]
            cis = by_mix[CONTROL_MIX][sl]
            mrows.append(
                {
                    "MIX": mix,
                    "JUDGE": jtag if sl == "IS" else "",
                    "SLICE": sl,
                    "N": s["n"],
                    "WR": round(s["wr"], 2),
                    "AVG_PNL_PCT": round(s["avg_pnl"], 4),
                    "D_AVG_VS_CTRL": None if mix == CONTROL_MIX else round(s["avg_pnl"] - cis["avg_pnl"], 4),
                    "PF": round(s["pf"], 3),
                    "D_PF_VS_CTRL": None if mix == CONTROL_MIX else round(s["pf"] - cis["pf"], 3),
                    "SHEET_PNL": round(s["sheet"], 2),
                    "AVG_DAYS": round(s["avg_days"], 2),
                    "AVG_PNL_PCT_WO_MAX": round(s["wo_max"], 4),
                    "ANN_ROR": None if not math.isfinite(s["ann_ror"]) else round(s["ann_ror"], 2),
                    "MAX_DD": None if not math.isfinite(s["max_dd"]) else round(s["max_dd"], 2),
                    "LONG_N": s["long_n"],
                    "SHORT_N": s["short_n"],
                    "NOTE": jnote if sl == "IS" else "",
                    "EXITS": json.dumps(s["exits"]),
                }
            )
    pd.DataFrame(mrows).to_csv(metrics_path, index=False)

    write_compare_html(out / "compare.html", by_mix, judgments, meta, verdict, verdict_note)
    write_baseline_md(out / "BASELINE.md", by_mix, judgments, meta, verdict, verdict_note)
    write_summary_md(out / "SUMMARY.md", by_mix, judgments, meta, verdict, verdict_note)
    (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(
        f"[lt+sys] done in {meta['elapsed_sec']}s · verdict={verdict} · "
        f"trades={len(all_trades)} · out={out}",
        flush=True,
    )
    for mix in MIX_ARMS:
        j = judgments[mix][0]
        isi = by_mix[mix]["IS"]
        print(
            f"  {mix:14s} {j:10s} IS n={isi['n']:6d} avg={isi['avg_pnl']:+.3f} pf={isi['pf']:.2f}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
