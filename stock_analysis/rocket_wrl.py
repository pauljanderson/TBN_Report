"""WRL — Weekly Range / Swing demand-zone breakout (TBN mode ``wrl_mode``).

Outputs: ``drive/WRL_*_<stamp>.csv`` (Closed / Open / Watchlist / Scanner / Summary /
Report / Audit / EquityCurve). Host: ``rocket_tbn.py``.
"""
from __future__ import annotations

import csv
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, fields, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

try:
    from tbn_host_sizing import (
        HostSizingConfig,
        apply_host_dollar_scale,
        audit_display_brt_cash,
        compute_and_write_host_equity,
    )
except ImportError:
    from stock_analysis.tbn_host_sizing import (  # type: ignore
        HostSizingConfig,
        apply_host_dollar_scale,
        audit_display_brt_cash,
        compute_and_write_host_equity,
    )

try:
    from wrl_zones import (
        WeeklyLevels,
        attach_daily_levels,
        breakout_up_from_demand,
        close_in_demand_zone,
        fill_price,
        levels_for_bar,
    )
except ImportError:
    from stock_analysis.wrl_zones import (  # type: ignore
        WeeklyLevels,
        attach_daily_levels,
        breakout_up_from_demand,
        close_in_demand_zone,
        fill_price,
        levels_for_bar,
    )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class WrlConfig:
    wrl_mode: bool = True
    # range = full exit at range high; swing = full exit at swing high;
    # scale = 50% at range high, remainder at swing high (stop to breakeven after T1).
    wrl_target_mode: str = "scale"
    wrl_scale_frac: float = 0.50
    # Stop at swing_low * stop_pct (1.0 = at the swing low).
    stop_pct: float = 1.0
    stop_pct_is_multiplier: bool = True
    wrl_min_zone_pct: float = 0.0  # min (range_low/swing_low - 1); 0 = off
    # Skip fill unless structural reward/risk >= this (0 = off).
    # Reward is range_high-fill (range), swing_high-fill (swing), or the
    # primary target for the current wrl_target_mode (primary).
    wrl_min_rr: float = 0.0
    wrl_min_rr_target: str = "range"  # range | swing | primary
    wrl_time_stop_bars: int = 0  # 0 = off
    symbol_reentry_cooldown_days: int = 0
    entry_start_date: str = ""
    entry_end_date: str = ""
    brt_cash: float = 47_500.0


def wrl_config_from_brt(cfg: Any) -> WrlConfig:
    kw: dict[str, Any] = {}
    for f in fields(WrlConfig):
        if hasattr(cfg, f.name):
            kw[f.name] = getattr(cfg, f.name)
    return WrlConfig(**kw)


def _wrl_cfg_dict(cfg: WrlConfig) -> dict[str, Any]:
    return {f.name: getattr(cfg, f.name) for f in fields(WrlConfig)}


def _wrl_cfg_from_dict(d: dict[str, Any]) -> WrlConfig:
    return WrlConfig(**{f.name: d[f.name] for f in fields(WrlConfig) if f.name in d})


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


@dataclass
class WrlClosedRow:
    symbol: str
    side: str
    date_opened: str
    entry_price: float
    stop_price: float
    target_price: float
    target2_price: float
    date_closed: str
    exit_price: float
    exit_type: str
    days_held: int
    pnl_pct: float
    pnl_dollars: float
    ann_ror_pct: float
    max_price: float
    range_high: float
    range_low: float
    swing_high: float
    swing_low: float
    watch_date: str
    signal_date: str
    range_week_end: str
    one_liner: str
    rr_t1: float = 0.0
    rr_t2: float = 0.0

    def to_csv_row(self) -> list[str]:
        return [
            self.symbol,
            self.side,
            self.date_opened,
            f"{self.entry_price:.4f}",
            f"{self.stop_price:.4f}",
            f"{self.target_price:.4f}",
            f"{self.target2_price:.4f}",
            self.date_closed,
            f"{self.exit_price:.4f}",
            self.exit_type,
            str(self.days_held),
            f"{self.pnl_pct:.4f}",
            f"{self.pnl_dollars:.2f}",
            f"{self.ann_ror_pct:.2f}",
            f"{self.max_price:.4f}",
            f"{self.range_high:.4f}",
            f"{self.range_low:.4f}",
            f"{self.swing_high:.4f}",
            f"{self.swing_low:.4f}",
            f"{self.rr_t1:.4f}",
            f"{self.rr_t2:.4f}",
            self.watch_date,
            self.signal_date,
            self.range_week_end,
            self.one_liner,
        ]


WRL_CLOSED_HEADER = [
    "SYMBOL",
    "SIDE",
    "DATE_OPENED",
    "ENTRY_PRICE",
    "STOP_PRICE",
    "TARGET_PRICE",
    "TARGET2_PRICE",
    "DATE_CLOSED",
    "EXIT_PRICE",
    "EXIT_TYPE",
    "DAYS_HELD",
    "PNL_PCT",
    "PNL_DOLLARS",
    "ANN_ROR_PCT",
    "MAX_PRICE",
    "RANGE_HIGH",
    "RANGE_LOW",
    "SWING_HIGH",
    "SWING_LOW",
    "RR_T1",
    "RR_T2",
    "WATCH_DATE",
    "SIGNAL_DATE",
    "RANGE_WEEK_END",
    "ONE_LINER",
]

WRL_OPEN_HEADER = [
    "SYMBOL",
    "DATE_OPENED",
    "ENTRY_PRICE",
    "CURRENT_PRICE",
    "PNL_PCT",
    "DAYS_OPEN",
    "STOP_LOSS",
    "TARGET",
    "TARGET2",
    "RANGE_HIGH",
    "RANGE_LOW",
    "SWING_HIGH",
    "SWING_LOW",
    "WATCH_DATE",
    "SIGNAL_DATE",
]

WRL_WATCHLIST_HEADER = [
    "SYMBOL",
    "ASOF_DATE",
    "ROW_TYPE",
    "STATUS",
    "CLOSE",
    "RANGE_HIGH",
    "RANGE_LOW",
    "SWING_HIGH",
    "SWING_LOW",
    "ZONE_LOW",
    "ZONE_HIGH",
    "TARGET",
    "TARGET2",
    "STOP_LOSS",
    "TRIGGER_HINT",
]

WRL_SCANNER_HEADER = [
    "SYMBOL",
    "DATE",
    "CLOSE",
    "STOP_LOSS",
    "TARGET",
    "TARGET2",
    "RANGE_HIGH",
    "RANGE_LOW",
    "SWING_HIGH",
    "SWING_LOW",
    "MIN_ENTRY_OPEN",
    "MAX_ENTRY_OPEN",
    "TRIGGER_HINT",
]


def _iso(d: Any) -> str:
    if hasattr(d, "strftime"):
        return d.strftime("%Y%m%d")
    s = str(d)[:10].replace("-", "")
    return s


def _iso_dash(d: Any) -> str:
    s = _iso(d)
    if len(s) >= 8:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def _entry_date_allowed(iso: str, start: str, end: str) -> bool:
    s = (start or "").strip().replace("-", "")[:8]
    e = (end or "").strip().replace("-", "")[:8]
    if s and iso < s:
        return False
    if e and iso > e:
        return False
    return True


def _calendar_days(d1: str, d2: str) -> int:
    def _ep(d: str) -> int:
        t = time.struct_time((int(d[:4]), int(d[4:6]), int(d[6:8]), 0, 0, 0, 0, 0, -1))
        return int(time.mktime(t))

    return int((_ep(d2) - _ep(d1)) / 86400)


def _stop_from_levels(levels: WeeklyLevels, cfg: WrlConfig) -> float:
    sl = float(levels.swing_low)
    if cfg.stop_pct_is_multiplier:
        return sl * float(cfg.stop_pct)
    return sl * (1.0 - float(cfg.stop_pct))


def _zone_wide_enough(levels: WeeklyLevels, cfg: WrlConfig) -> bool:
    min_pct = float(cfg.wrl_min_zone_pct or 0.0)
    if min_pct <= 0:
        return True
    sl = float(levels.swing_low)
    if sl <= 0:
        return False
    return (float(levels.range_low) / sl - 1.0) >= min_pct - 1e-12


def _structural_rr(fill: float, stop: float, target: float) -> float:
    """Reward/risk at fill: (target - fill) / (fill - stop). 0 if risk is not positive."""
    risk = float(fill) - float(stop)
    if risk <= 0:
        return 0.0
    return (float(target) - float(fill)) / risk


def _rr_at_fill(fill: float, stop: float, levels: WeeklyLevels) -> tuple[float, float]:
    """T1 = range high, T2 = swing high. Knowable at fill; used on Closed + correlation."""
    return (
        _structural_rr(fill, stop, float(levels.range_high)),
        _structural_rr(fill, stop, float(levels.swing_high)),
    )


def _min_rr_reward_price(levels: WeeklyLevels, cfg: WrlConfig) -> float:
    tgt = str(getattr(cfg, "wrl_min_rr_target", "range") or "range").strip().lower()
    if tgt == "swing":
        return float(levels.swing_high)
    if tgt == "primary":
        mode = str(getattr(cfg, "wrl_target_mode", "scale") or "scale").strip().lower()
        return _primary_target(levels, mode)
    return float(levels.range_high)


def _min_rr_allows_entry(fill: float, stop: float, levels: WeeklyLevels, cfg: WrlConfig) -> bool:
    """True when wrl_min_rr is off, or structural reward/risk is at least the threshold."""
    min_rr = float(getattr(cfg, "wrl_min_rr", 0.0) or 0.0)
    if min_rr <= 0:
        return True
    rr = _structural_rr(fill, stop, _min_rr_reward_price(levels, cfg))
    return rr + 1e-12 >= min_rr


def _primary_target(levels: WeeklyLevels, mode: str) -> float:
    m = (mode or "scale").strip().lower()
    if m == "swing":
        return float(levels.swing_high)
    return float(levels.range_high)


def wrl_closed_to_brt_trade(r: WrlClosedRow) -> Any:
    """Map a WRL closed trade onto BRTTrade so compute_metrics / Audit match VZ/SB."""
    try:
        from rocket_tbn import BRTTrade
    except ImportError:
        from stock_analysis.rocket_tbn import BRTTrade  # type: ignore

    t = BRTTrade(
        symbol=str(r.symbol).upper(),
        date_opened=str(r.date_opened),
        entry_price=float(r.entry_price),
        stop_price=float(r.stop_price),
        target_price=float(r.target_price),
        date_closed=str(r.date_closed or ""),
        exit_price=float(r.exit_price or 0.0),
        exit_type=str(r.exit_type or ""),
        days_held=int(r.days_held or 0),
        pnl_pct=float(r.pnl_pct or 0.0),
        pnl_dollars=float(r.pnl_dollars or 0.0),
        max_price=float(r.max_price or r.entry_price or 0.0),
        zone_low=float(r.swing_low or 0.0),
        zone_high=float(r.range_low or 0.0),
        zone_center=float(r.range_high or 0.0),
        side=str(r.side or "LONG"),
    )
    t.signal_date = str(r.signal_date or "")
    return t


def brt_config_from_wrl(cfg: WrlConfig, host_cfg: Any = None) -> Any:
    """BRTConfig for unified Audit/Report (same wide schema as VZ/SB)."""
    try:
        from rocket_tbn import BRTConfig
    except ImportError:
        from stock_analysis.rocket_tbn import BRTConfig  # type: ignore

    base_kw: dict[str, Any] = dict(
        wrl_mode=True,
        vz_mode=False,
        sb_mode=False,
        qull_mode=False,
        mvcp_mode=False,
        brt_zones=False,
        yh_zones=False,
        wpbr_zones=False,
        vec_zones=False,
        rl_mode="false",
        relative_strength_enabled=False,
        wrl_target_mode=str(cfg.wrl_target_mode or "scale"),
        wrl_scale_frac=float(cfg.wrl_scale_frac or 0.50),
        wrl_min_zone_pct=float(cfg.wrl_min_zone_pct or 0.0),
        wrl_min_rr=float(getattr(cfg, "wrl_min_rr", 0.0) or 0.0),
        wrl_min_rr_target=str(getattr(cfg, "wrl_min_rr_target", "range") or "range"),
        wrl_time_stop_bars=int(cfg.wrl_time_stop_bars or 0),
        stop_pct=float(cfg.stop_pct),
        stop_pct_is_multiplier=bool(cfg.stop_pct_is_multiplier),
        brt_cash=float(cfg.brt_cash),
        symbol_reentry_cooldown_days=int(cfg.symbol_reentry_cooldown_days or 0),
        entry_start_date=str(cfg.entry_start_date or ""),
        entry_end_date=str(cfg.entry_end_date or ""),
        compute_equity_metrics=True,
    )
    if host_cfg is not None:
        for k in (
            "initial_capital",
            "aggressive",
            "aggressive_max_multiple",
            "margin_utilization",
            "max_positions",
            "aggressive_margin_interest",
            "aggressive_avg_positions",
            "aggressive_sizing_equity_cap",
            "days_per_year",
        ):
            if hasattr(host_cfg, k):
                base_kw[k] = getattr(host_cfg, k)
        if hasattr(host_cfg, "wrl_mode"):
            try:
                return replace(host_cfg, **base_kw)
            except TypeError:
                pass
    return BRTConfig(**base_kw)


# ---------------------------------------------------------------------------
# Per-symbol backtest
# ---------------------------------------------------------------------------


def backtest_symbol(
    symbol: str,
    df: pd.DataFrame,
    cfg: WrlConfig,
) -> tuple[list[WrlClosedRow], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Watch (close in demand zone) → next-day upside break → structural targets."""
    closed: list[WrlClosedRow] = []
    open_rows: list[dict[str, Any]] = []
    watch: list[dict[str, Any]] = []
    scanner: list[dict[str, Any]] = []
    if df is None or len(df) < 10:
        return closed, open_rows, watch, scanner

    weekly, swings, week_idx = attach_daily_levels(df)
    if weekly is None or len(weekly) < 3:
        return closed, open_rows, watch, scanner

    dates = df.index
    o = df["Open"].to_numpy(dtype=np.float64)
    h = df["High"].to_numpy(dtype=np.float64)
    l = df["Low"].to_numpy(dtype=np.float64)
    c = df["Close"].to_numpy(dtype=np.float64)
    n = len(df)
    cash = float(cfg.brt_cash)
    mode = (cfg.wrl_target_mode or "scale").strip().lower()
    scale_frac = min(0.99, max(0.01, float(cfg.wrl_scale_frac or 0.50)))
    use_scale = mode == "scale"
    cooldown_until = ""
    pos: dict[str, Any] | None = None
    watch_i: int | None = None
    watch_levels: WeeklyLevels | None = None

    def _close_trade(
        *,
        exit_i: int,
        exit_px: float,
        exit_type: str,
        avg_exit: float,
        pnl_d: float,
        pnl_pct: float,
    ) -> None:
        nonlocal pos
        assert pos is not None
        iso = _iso(dates[exit_i])
        entry = float(pos["entry"])
        cal = max(1, _calendar_days(pos["entry_iso"], iso))
        ann = ((avg_exit / entry) ** (365.0 / cal) - 1.0) * 100.0 if entry > 0 else 0.0
        lv: WeeklyLevels = pos["levels"]
        closed.append(
            WrlClosedRow(
                symbol=symbol,
                side="LONG",
                date_opened=pos["entry_iso"],
                entry_price=entry,
                stop_price=float(pos["initial_stop"]),
                target_price=float(pos["t1"]),
                target2_price=float(pos["t2"]),
                date_closed=iso,
                exit_price=avg_exit,
                exit_type=exit_type,
                days_held=exit_i - int(pos["entry_i"]),
                pnl_pct=pnl_pct,
                pnl_dollars=pnl_d,
                ann_ror_pct=ann,
                max_price=float(pos["max_price"]),
                range_high=lv.range_high,
                range_low=lv.range_low,
                swing_high=lv.swing_high,
                swing_low=lv.swing_low,
                rr_t1=float(pos.get("rr_t1", 0.0) or 0.0),
                rr_t2=float(pos.get("rr_t2", 0.0) or 0.0),
                watch_date=pos["watch_iso"],
                signal_date=pos["signal_iso"],
                range_week_end=_iso_dash(lv.range_week_end),
                one_liner=(
                    f"{symbol} | IN {pos['entry_iso']} @ {entry:.2f} -> OUT {iso} @ {avg_exit:.2f} | "
                    f"{exit_type} {pnl_pct:+.1f}% | RH {lv.range_high:.2f} SH {lv.swing_high:.2f}"
                ),
            )
        )
        pos = None

    for i in range(n):
        iso = _iso(dates[i])
        lv = levels_for_bar(swings, week_idx, i)

        if pos is not None and i > int(pos["entry_i"]):
            entry = float(pos["entry"])
            stop = float(pos["stop"])
            t1 = float(pos["t1"])
            t2 = float(pos["t2"])
            remaining = float(pos["remaining"])
            t1_done = bool(pos["t1_done"])
            realized_d = float(pos["realized_d"])
            realized_px_w = float(pos["realized_px_w"])
            pos["max_price"] = max(float(pos["max_price"]), float(h[i]))
            op, hi, lo, cl = float(o[i]), float(h[i]), float(l[i]), float(c[i])
            shares = cash / entry if entry > 0 else 0.0
            time_stop = int(cfg.wrl_time_stop_bars or 0)
            days_held = i - int(pos["entry_i"])

            def _take(frac: float, px: float, label: str) -> str | None:
                nonlocal remaining, realized_d, realized_px_w, t1_done
                take = min(remaining, frac)
                if take <= 0:
                    return None
                realized_d += shares * take * (px - entry)
                realized_px_w += take * px
                remaining -= take
                pos["remaining"] = remaining
                pos["realized_d"] = realized_d
                pos["realized_px_w"] = realized_px_w
                if remaining <= 1e-12:
                    sold = 1.0 - remaining
                    avg = (realized_px_w / sold) if sold > 1e-12 else px
                    pnl_pct = (avg / entry - 1.0) * 100.0 if entry > 0 else 0.0
                    _close_trade(
                        exit_i=i,
                        exit_px=px,
                        exit_type=label,
                        avg_exit=avg,
                        pnl_d=realized_d,
                        pnl_pct=pnl_pct,
                    )
                    return "closed"
                return "partial"

            # Intraday order: gap through stop, gap through remaining target, stop, target.
            if op <= stop:
                _take(remaining, op, "GAP_DOWN" if op < stop - 1e-9 else "STOP_LOSS")
                if pos is None:
                    watch_i = None
                    watch_levels = None
                    continue
            else:
                tgt = t2 if (use_scale and t1_done) else (t2 if mode == "swing" else t1)
                if op >= (t2 if (use_scale and t1_done) else tgt):
                    if use_scale and not t1_done and op >= t1:
                        _take(scale_frac, op, "TARGET1")
                        if pos is None:
                            watch_i = None
                            watch_levels = None
                            continue
                        t1_done = True
                        pos["t1_done"] = True
                        pos["stop"] = entry
                        stop = entry
                    if pos is not None and op >= t2:
                        _take(remaining, op, "GAP_UP" if not t1_done else "TARGET2")
                        if pos is None:
                            watch_i = None
                            watch_levels = None
                            continue
                    elif pos is not None and (not use_scale) and op >= tgt:
                        _take(remaining, op, "GAP_UP")
                        if pos is None:
                            watch_i = None
                            watch_levels = None
                            continue

                if pos is not None and lo <= stop:
                    _take(remaining, stop, "STOP_LOSS")
                    if pos is None:
                        watch_i = None
                        watch_levels = None
                        continue

                if pos is not None and use_scale and not t1_done and hi >= t1:
                    _take(scale_frac, t1, "TARGET1")
                    if pos is None:
                        watch_i = None
                        watch_levels = None
                        continue
                    t1_done = True
                    pos["t1_done"] = True
                    pos["stop"] = entry
                    stop = entry

                if pos is not None:
                    final_tgt = t2 if (use_scale or mode == "swing") else t1
                    if hi >= final_tgt:
                        label = "TARGET2" if (use_scale and t1_done) else "TARGET"
                        _take(remaining, final_tgt, label)
                        if pos is None:
                            watch_i = None
                            watch_levels = None
                            continue

            if pos is not None and time_stop > 0 and days_held >= time_stop:
                _take(remaining, cl, "TIME_STOP")
                if pos is None:
                    watch_i = None
                    watch_levels = None
                    continue

        if pos is not None:
            continue
        if cooldown_until and int(cfg.symbol_reentry_cooldown_days) > 0:
            if _calendar_days(cooldown_until, iso) < int(cfg.symbol_reentry_cooldown_days):
                continue

        # Convert yesterday's watch into today's buy.
        if watch_i is not None and watch_levels is not None and watch_i + 1 == i:
            if breakout_up_from_demand(float(o[i]), float(h[i]), watch_levels):
                fill = fill_price(float(o[i]), watch_levels)
                stop = _stop_from_levels(watch_levels, cfg)
                t1 = _primary_target(watch_levels, mode)
                t2 = float(watch_levels.swing_high)
                if mode == "swing":
                    t1 = t2
                fill_iso = iso
                if (
                    fill > 0
                    and stop < fill
                    and t1 > fill
                    and _entry_date_allowed(fill_iso, cfg.entry_start_date, cfg.entry_end_date)
                    and _min_rr_allows_entry(fill, stop, watch_levels, cfg)
                ):
                    rr_t1, rr_t2 = _rr_at_fill(fill, stop, watch_levels)
                    pos = {
                        "entry_i": i,
                        "entry_iso": fill_iso,
                        "entry": fill,
                        "stop": stop,
                        "initial_stop": stop,
                        "t1": t1,
                        "t2": t2,
                        "remaining": 1.0,
                        "t1_done": False if use_scale else True,
                        "realized_d": 0.0,
                        "realized_px_w": 0.0,
                        "max_price": max(fill, float(h[i])),
                        "levels": watch_levels,
                        "watch_iso": _iso(dates[watch_i]),
                        "signal_iso": fill_iso,
                        "rr_t1": rr_t1,
                        "rr_t2": rr_t2,
                    }
                    if not use_scale:
                        # Full-size single target: t1 is the only target.
                        pos["t1_done"] = True
                    watch_i = None
                    watch_levels = None
                    continue
            watch_i = None
            watch_levels = None

        if lv is None or not _zone_wide_enough(lv, cfg):
            continue
        if close_in_demand_zone(float(c[i]), lv):
            watch_i = i
            watch_levels = lv

    if pos is not None:
        i = n - 1
        entry = float(pos["entry"])
        cl = float(c[i])
        lv = pos["levels"]
        open_rows.append(
            {
                "symbol": symbol,
                "date_opened": pos["entry_iso"],
                "entry_price": entry,
                "current_price": cl,
                "pnl_pct": (cl / entry - 1.0) * 100.0 if entry else 0.0,
                "days_open": i - int(pos["entry_i"]),
                "stop": float(pos["stop"]),
                "target": float(pos["t1"]),
                "target2": float(pos["t2"]),
                "range_high": lv.range_high,
                "range_low": lv.range_low,
                "swing_high": lv.swing_high,
                "swing_low": lv.swing_low,
                "watch_date": pos["watch_iso"],
                "signal_date": pos["signal_iso"],
            }
        )

    last = n - 1
    last_lv = levels_for_bar(swings, week_idx, last) if last >= 0 else None
    if last_lv is not None and close_in_demand_zone(float(c[last]), last_lv) and pos is None:
        asof = _iso(dates[last])
        stop = _stop_from_levels(last_lv, cfg)
        t1 = _primary_target(last_lv, mode)
        t2 = float(last_lv.swing_high)
        hint = (
            "Close inside demand zone [swing_low, range_low]. "
            "Next session: buy if price opens (not through swing low) and trades up through range low. "
            f"Targets range high {last_lv.range_high:.2f} then swing high {last_lv.swing_high:.2f}."
        )
        watch.append(
            {
                "symbol": symbol,
                "asof": asof,
                "row_type": "WATCH",
                "status": "CLOSE_IN_DEMAND_ZONE",
                "close": float(c[last]),
                "range_high": last_lv.range_high,
                "range_low": last_lv.range_low,
                "swing_high": last_lv.swing_high,
                "swing_low": last_lv.swing_low,
                "zone_low": last_lv.swing_low,
                "zone_high": last_lv.range_low,
                "target": t1,
                "target2": t2,
                "stop": stop,
                "notes": hint,
            }
        )
        scanner.append(
            {
                "symbol": symbol,
                "date": _iso_dash(dates[last]),
                "close": float(c[last]),
                "stop": stop,
                "target": t1,
                "target2": t2,
                "range_high": last_lv.range_high,
                "range_low": last_lv.range_low,
                "swing_high": last_lv.swing_high,
                "swing_low": last_lv.swing_low,
                "min_entry_open": last_lv.swing_low,
                "max_entry_open": last_lv.range_low,
                "hint": hint,
            }
        )
    return closed, open_rows, watch, scanner


# ---------------------------------------------------------------------------
# Parallel
# ---------------------------------------------------------------------------


@dataclass
class WrlSymbolResult:
    symbol: str
    closed: list[WrlClosedRow]
    open_rows: list[dict[str, Any]]
    watch: list[dict[str, Any]]
    scanner: list[dict[str, Any]]
    skip_reason: str = ""


def _process_wrl_symbol(args: tuple[str, pd.DataFrame, dict[str, Any]]) -> WrlSymbolResult:
    sym, df, cfg_d = args
    cfg = _wrl_cfg_from_dict(cfg_d)
    closed, open_rows, watch, scanner = backtest_symbol(sym, df, cfg)
    return WrlSymbolResult(sym, closed, open_rows, watch, scanner)


def _run_wrl_symbol_tasks(
    tasks: list[tuple[str, pd.DataFrame, dict[str, Any]]],
    workers: int,
) -> list[WrlSymbolResult]:
    results: list[WrlSymbolResult] = []
    if workers > 0 and len(tasks) > 1:
        n_w = min(int(workers), len(tasks), 32)
        print(f"[WRL] Spawning {n_w} worker process(es) for {len(tasks)} symbols", flush=True)
        with ProcessPoolExecutor(max_workers=n_w) as ex:
            futs = {ex.submit(_process_wrl_symbol, t): t[0] for t in tasks}
            for fut in as_completed(futs):
                sym = futs[fut]
                try:
                    res = fut.result()
                except Exception as e:
                    print(f"[WRL] skip {sym}: worker failed ({e})", flush=True)
                    results.append(WrlSymbolResult(sym, [], [], [], [], skip_reason=f"worker failed ({e})"))
                    continue
                results.append(res)
                print(
                    f"[WRL] {res.symbol}: {len(res.closed)} closed, {len(res.open_rows)} open, "
                    f"{len(res.watch)} watch",
                    flush=True,
                )
    else:
        for t in tasks:
            res = _process_wrl_symbol(t)
            results.append(res)
            print(
                f"[WRL] {res.symbol}: {len(res.closed)} closed, {len(res.open_rows)} open, "
                f"{len(res.watch)} watch",
                flush=True,
            )
    return results


# ---------------------------------------------------------------------------
# Writers + host
# ---------------------------------------------------------------------------


def write_wrl_outputs(
    output_dir: Path,
    ts: str,
    closed: list[WrlClosedRow],
    open_rows: list[dict[str, Any]],
    watch_rows: list[dict[str, Any]],
    scanner_rows: list[dict[str, Any]],
    cfg: WrlConfig,
    *,
    host_meta: Optional[dict[str, Any]] = None,
    tickers: Optional[dict[str, pd.DataFrame]] = None,
    host_cfg: Any = None,
    tbn_cfg: Any = None,
    drive_link: str = "",
    no_yfinance: bool = False,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    host_meta = host_meta or {}
    closed_path = output_dir / f"WRL_Closed_{ts}.csv"
    open_path = output_dir / f"WRL_Open_{ts}.csv"
    watch_path = output_dir / f"WRL_Watchlist_{ts}.csv"
    scanner_path = output_dir / f"WRL_Scanner_{ts}.csv"
    summary_path = output_dir / f"WRL_Summary_{ts}.csv"
    report_path = output_dir / f"WRL_Report_{ts}.csv"
    audit_path = output_dir / f"WRL_Audit_Report_{ts}.csv"

    with closed_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(WRL_CLOSED_HEADER)
        for r in closed:
            w.writerow(r.to_csv_row())

    with open_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(WRL_OPEN_HEADER)
        for r in open_rows:
            w.writerow(
                [
                    r["symbol"],
                    r["date_opened"],
                    f"{r['entry_price']:.4f}",
                    f"{r['current_price']:.4f}",
                    f"{r['pnl_pct']:.4f}",
                    r["days_open"],
                    f"{r['stop']:.4f}",
                    f"{r['target']:.4f}",
                    f"{r['target2']:.4f}",
                    f"{r['range_high']:.4f}",
                    f"{r['range_low']:.4f}",
                    f"{r['swing_high']:.4f}",
                    f"{r['swing_low']:.4f}",
                    r["watch_date"],
                    r["signal_date"],
                ]
            )

    with watch_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(WRL_WATCHLIST_HEADER)
        for r in watch_rows:
            w.writerow(
                [
                    r["symbol"],
                    r["asof"],
                    r["row_type"],
                    r["status"],
                    f"{r['close']:.4f}",
                    f"{r['range_high']:.4f}",
                    f"{r['range_low']:.4f}",
                    f"{r['swing_high']:.4f}",
                    f"{r['swing_low']:.4f}",
                    f"{r['zone_low']:.4f}",
                    f"{r['zone_high']:.4f}",
                    f"{r['target']:.4f}",
                    f"{r['target2']:.4f}",
                    f"{r['stop']:.4f}",
                    r["notes"],
                ]
            )

    with scanner_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(WRL_SCANNER_HEADER)
        for r in scanner_rows:
            w.writerow(
                [
                    r["symbol"],
                    r["date"],
                    f"{r['close']:.4f}",
                    f"{r['stop']:.4f}",
                    f"{r['target']:.4f}",
                    f"{r['target2']:.4f}",
                    f"{r['range_high']:.4f}",
                    f"{r['range_low']:.4f}",
                    f"{r['swing_high']:.4f}",
                    f"{r['swing_low']:.4f}",
                    f"{r['min_entry_open']:.4f}",
                    f"{r['max_entry_open']:.4f}",
                    r["hint"],
                ]
            )

    by_sym: dict[str, list[WrlClosedRow]] = {}
    for r in closed:
        by_sym.setdefault(r.symbol, []).append(r)
    total_pnl_all = sum(r.pnl_dollars for r in closed) or 0.0
    days_per_year = 365.25

    def _first_data_date(sym: str) -> str:
        if not tickers or sym not in tickers:
            return ""
        frame = tickers[sym]
        if frame is None or len(frame) == 0:
            return ""
        try:
            if isinstance(frame.index, pd.DatetimeIndex) and len(frame.index):
                d0 = frame.index[0]
            elif "Date" in frame.columns:
                d0 = pd.to_datetime(frame["Date"].iloc[0])
            else:
                return ""
            return pd.Timestamp(d0).strftime("%Y-%m-%d")
        except Exception:
            return ""

    with summary_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "SYMBOL",
                "TRADES",
                "WINS",
                "LOSSES",
                "BEs",
                "PCT_WINS",
                "TOTAL_PNL",
                "SHEET_PNL",
                "AVG_PNL_PCT",
                "PCT_OF_TOTAL_PNL",
                "CURRENT_MARKET_CAP",
                "SECTOR",
                "INDUSTRY",
                "FIRST_DATA_DATE",
                "AVG_TRADES_PER_YEAR",
                "MAX_WIN_PCT",
                "MEDIAN_PNL_PCT",
                "AVG_DAYS_HELD",
            ]
        )
        for sym in sorted(by_sym):
            rows = by_sym[sym]
            wins = sum(1 for r in rows if r.pnl_pct > 1e-9)
            losses = sum(1 for r in rows if r.pnl_pct < -1e-9)
            bes = len(rows) - wins - losses
            pnls = [r.pnl_pct for r in rows]
            pnl = sum(r.pnl_dollars for r in rows)
            avg_pct = (sum(pnls) / len(pnls)) if pnls else 0.0
            med_pct = float(np.median(pnls)) if pnls else 0.0
            max_win = max(pnls) if pnls else 0.0
            first = _first_data_date(sym)
            years = 1.0
            if first and rows:
                try:
                    d0 = datetime.strptime(first.replace("-", "")[:8], "%Y%m%d")
                    d1 = datetime.strptime(str(rows[-1].date_closed).replace("-", "")[:8], "%Y%m%d")
                    years = max((d1 - d0).days / days_per_year, 1e-6)
                except Exception:
                    years = 1.0
            w.writerow(
                [
                    sym,
                    len(rows),
                    wins,
                    losses,
                    bes,
                    f"{(100.0 * wins / len(rows)) if rows else 0.0:.1f}%",
                    f"{pnl:.2f}",
                    f"{pnl:.2f}",
                    f"{avg_pct:.2f}%",
                    f"{(100.0 * pnl / total_pnl_all) if total_pnl_all else 0.0:.1f}%",
                    "",
                    "",
                    "",
                    first,
                    f"{(len(rows) / years):.2f}",
                    f"{max_win:.2f}%",
                    f"{med_pct:+.2f}%",
                    f"{(sum(r.days_held for r in rows) / len(rows)) if rows else 0.0:.1f}",
                ]
            )

    equity_path = output_dir / f"WRL_EquityCurve_{ts}.csv"
    equity_meta_path = output_dir / f"WRL_EquityMeta_{ts}.csv"
    max_dd = 0.0
    max_dd_pct = 0.0
    aggressive_total = ""
    aggressive_max_dd = ""
    host_equity_written = False
    if tickers is not None and host_cfg is not None and (
        bool(getattr(host_cfg, "aggressive", False)) or bool(host_meta.get("use_host_equity"))
    ):
        equity = compute_and_write_host_equity(
            output_dir=output_dir,
            ts=ts,
            file_prefix="WRL",
            closed=closed,
            open_trades=open_rows,
            tickers=tickers,
            cfg=host_cfg,
        )
        if equity:
            host_equity_written = True
            md = equity.get("Max_Drawdown", "")
            try:
                max_dd_pct = float(str(md).replace("%", "").strip())
                max_dd = max_dd_pct / 100.0
            except (TypeError, ValueError):
                pass
            if equity.get("_aggressive"):
                aggressive_total = f"{float(equity.get('_equity_total_pnl', 0) or 0):.2f}"
                aggressive_max_dd = str(equity.get("Aggressive_Max_Drawdown", "") or "")

    if not host_equity_written:
        by_date: dict[str, float] = {}
        for r in closed:
            d = str(r.date_closed or "").strip().replace("-", "")
            if len(d) >= 8 and d[:8].isdigit():
                iso = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            else:
                iso = str(r.date_closed or "").strip()
            if not iso:
                continue
            by_date[iso] = by_date.get(iso, 0.0) + float(r.pnl_dollars)
        init_cash = float(host_meta.get("host_brt_cash") or getattr(cfg, "brt_cash", 0) or 47500.0)
        equity_val = init_cash
        peak = equity_val
        max_dd = 0.0
        eq_rows: list[dict[str, Any]] = []
        for d in sorted(by_date):
            equity_val += by_date[d]
            if equity_val > peak:
                peak = equity_val
            dd = ((peak - equity_val) / peak) if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
            eq_rows.append({"Date": d, "Equity": equity_val, "Positions": ""})
        if not eq_rows:
            eq_rows.append({"Date": "", "Equity": init_cash, "Positions": ""})
        pd.DataFrame(eq_rows).to_csv(equity_path, index=False)
        max_dd_pct = max_dd * 100.0
        pd.DataFrame(
            [
                {
                    "Initial_Account_Size": init_cash,
                    "Max_Drawdown_fraction": max_dd,
                    "Max_Drawdown_pct": f"{max_dd_pct:.2f}%",
                    "Max_Days_Underwater": "",
                    "Pct_Days_Underwater": "",
                    "Aggressive": False,
                    "Curve_Kind": "realized_pnl_by_exit_date",
                }
            ]
        ).to_csv(equity_meta_path, index=False)

    try:
        from rocket_tbn import compute_metrics, write_brt_audit_report, write_brt_report
    except ImportError:
        from stock_analysis.rocket_tbn import (  # type: ignore
            compute_metrics,
            write_brt_audit_report,
            write_brt_report,
        )

    report_cfg = brt_config_from_wrl(cfg, tbn_cfg if tbn_cfg is not None else host_cfg)
    if host_meta.get("host_brt_cash") not in (None, ""):
        try:
            report_cfg = replace(report_cfg, brt_cash=float(host_meta["host_brt_cash"]))
        except (TypeError, ValueError):
            pass
    brt_closed = [wrl_closed_to_brt_trade(r) for r in closed]
    metrics = compute_metrics(brt_closed, report_cfg)
    if host_meta.get("host_max_positions") not in (None, ""):
        try:
            metrics["Max_Positions"] = int(host_meta["host_max_positions"])
        except (TypeError, ValueError):
            pass
    if max_dd_pct:
        metrics["Max_Drawdown"] = max_dd_pct
    if aggressive_total not in (None, ""):
        metrics["Aggressive_Total_PNL"] = aggressive_total
    if aggressive_max_dd not in (None, ""):
        metrics["Aggressive_Max_Drawdown"] = aggressive_max_dd
    elif host_meta.get("aggressive_max_dd") not in (None, ""):
        metrics["Aggressive_Max_Drawdown"] = host_meta.get("aggressive_max_dd")
    if host_meta.get("aggressive_total_pnl") not in (None, "") and not aggressive_total:
        metrics["Aggressive_Total_PNL"] = host_meta.get("aggressive_total_pnl")

    write_brt_report(
        report_cfg,
        metrics,
        str(output_dir),
        ts,
        drive_link=drive_link,
        file_prefix="WRL",
    )
    write_brt_audit_report(
        report_cfg,
        metrics,
        str(output_dir),
        ts,
        drive_link=drive_link,
        file_prefix="WRL",
    )
    written_audit = output_dir / f"WRL_Audit_Report_{ts}.csv"
    if written_audit.exists() and written_audit.resolve() != audit_path.resolve():
        audit_path.write_bytes(written_audit.read_bytes())
    written_report = output_dir / f"WRL_Report_{ts}.csv"
    if written_report.exists():
        report_path = written_report

    corr_path = output_dir / f"WRL_Correlation_{ts}.csv"
    try:
        import sys

        _sa = Path(__file__).resolve().parent
        if str(_sa) not in sys.path:
            sys.path.insert(0, str(_sa))
        from correlate_brt_closed import run_correlation_report

        run_correlation_report(str(closed_path), str(corr_path))
    except Exception as e:
        print(f"[WRL] Correlation skipped: {e}", flush=True)

    try:
        import sys

        _sa = Path(__file__).resolve().parent
        if str(_sa) not in sys.path:
            sys.path.insert(0, str(_sa))
        try:
            from rocket_post_analysis import write_analysis_artifacts
        except ImportError:
            from stock_analysis.rocket_post_analysis import write_analysis_artifacts  # type: ignore
        write_analysis_artifacts(
            cfg=None,
            tickers=tickers or {},
            output_dir=output_dir,
            ts=ts,
            closed_path=closed_path,
            summary_path=summary_path,
            open_path=open_path,
            prefix="WRL",
            no_yfinance=bool(no_yfinance),
        )
    except Exception as e:
        print(f"[WRL] analysis artifacts skipped: {e}", flush=True)

    for src, name in (
        (closed_path, "WRL_LatestRun_Closed.csv"),
        (open_path, "WRL_LatestRun_Open.csv"),
        (summary_path, "WRL_LatestRun_Summary.csv"),
        (watch_path, "WRL_LatestRun_Watchlist.csv"),
        (scanner_path, "WRL_LatestRun_Scanner.csv"),
        (audit_path, "WRL_LatestRun_Audit_Report.csv"),
        (equity_path, "WRL_LatestRun_EquityCurve.csv"),
    ):
        dest = output_dir / name
        if src.is_file():
            dest.write_bytes(src.read_bytes())

    (output_dir / "WRL_last_run_ts.txt").write_text(ts + "\n", encoding="utf-8")
    (output_dir / "last_run_ts.txt").write_text(ts, encoding="utf-8")
    return {
        "closed": closed_path,
        "open": open_path,
        "watchlist": watch_path,
        "scanner": scanner_path,
        "summary": summary_path,
        "report": report_path,
        "audit": audit_path,
        "equity_curve": equity_path,
        "equity_meta": equity_meta_path,
    }


def run_wrl_from_brt_main(
    *,
    cfg: Any,
    tickers: dict[str, pd.DataFrame],
    ticker_list: list[str],
    output_dir: Path,
    ts: str,
    data_dir: Path,
    load_symbol_fn: Any,
    workers: int = 0,
    drive_link: str = "",
    no_yfinance: bool = False,
) -> int:
    wcfg = wrl_config_from_brt(cfg)
    n_workers = max(0, int(workers or 0))
    print(
        f"[WRL] Weekly range/swing demand-zone on {len(ticker_list)} symbols "
        f"(target_mode={wcfg.wrl_target_mode}, stop_pct={wcfg.stop_pct}, workers={n_workers})",
        flush=True,
    )
    print(
        "[WRL] Watch: daily close in [swing_low, range_low]. "
        "Buy next day if High > range_low (no gap down through swing_low). "
        "Targets: range high then swing high.",
        flush=True,
    )

    all_closed: list[WrlClosedRow] = []
    all_open: list[dict[str, Any]] = []
    all_watch: list[dict[str, Any]] = []
    all_scanner: list[dict[str, Any]] = []
    loaded: dict[str, pd.DataFrame] = {}
    skipped: list[str] = []
    cfg_d = _wrl_cfg_dict(wcfg)
    tasks: list[tuple[str, pd.DataFrame, dict[str, Any]]] = []

    for sym in ticker_list:
        df = tickers.get(sym) if tickers else None
        if df is None or (hasattr(df, "empty") and df.empty):
            if load_symbol_fn is not None:
                try:
                    df = load_symbol_fn(sym, data_dir)
                except Exception as e:
                    print(f"[WRL] skip {sym}: load failed ({e})", flush=True)
                    skipped.append(sym)
                    continue
        if df is None or len(df) < 30:
            print(f"[WRL] skip {sym}: insufficient bars ({0 if df is None else len(df)})", flush=True)
            skipped.append(sym)
            continue
        loaded[sym] = df
        tasks.append((sym, df, cfg_d))

    t_bt = time.time()
    results = _run_wrl_symbol_tasks(tasks, n_workers)
    for res in results:
        if res.skip_reason:
            skipped.append(res.symbol)
            continue
        all_closed.extend(res.closed)
        all_open.extend(res.open_rows)
        all_watch.extend(res.watch)
        all_scanner.extend(res.scanner)
    print(f"[WRL] Symbol backtest {time.time() - t_bt:.1f}s (workers={n_workers})", flush=True)

    all_closed.sort(key=lambda r: (r.date_opened, r.symbol))

    host_meta: dict[str, Any] = {}
    hcfg = HostSizingConfig(
        brt_cash=float(getattr(cfg, "brt_cash", wcfg.brt_cash) or wcfg.brt_cash),
        initial_capital=float(getattr(cfg, "initial_capital", 500_000) or 500_000),
        aggressive_max_multiple=float(getattr(cfg, "aggressive_max_multiple", 2.0) or 2.0),
        margin_utilization=float(getattr(cfg, "margin_utilization", 0.6) or 0.6),
        max_positions=int(getattr(cfg, "max_positions", 0) or 0),
        aggressive=bool(getattr(cfg, "aggressive", False)),
        aggressive_margin_interest=float(getattr(cfg, "aggressive_margin_interest", 0.10) or 0.10),
        aggressive_avg_positions=float(getattr(cfg, "aggressive_avg_positions", 0) or 0),
        aggressive_sizing_equity_cap=float(getattr(cfg, "aggressive_sizing_equity_cap", 10.0) or 10.0),
        aggressive_sell=str(getattr(cfg, "aggressive_sell", "false") or "false"),
        equity_fast_aggressive=bool(getattr(cfg, "equity_fast_aggressive", False)),
    )
    if all_closed:
        adj, scale, max_pos = apply_host_dollar_scale(all_closed, all_open, hcfg)
        wcfg.brt_cash = adj
        host_meta = {
            "host_max_positions": max_pos,
            "host_brt_cash": adj,
            "host_pnl_scale": scale,
            "host_audit_brt_cash": audit_display_brt_cash(max_pos),
        }
        audit_cash = float(host_meta["host_audit_brt_cash"])
        closed_pnl = sum(r.pnl_dollars for r in all_closed)
        audit_pnl = closed_pnl * (audit_cash / adj) if adj > 0 else closed_pnl
        host_meta["total_pnl_audit_1m"] = f"{audit_pnl:.2f}"
        print(
            f"[WRL] Host dollar-scale: PNL_DOLLARS × {scale:.6g}; "
            f"brt_cash -> {adj:,.0f} (deployable/Max_Positions={max_pos}; "
            f"audit_label 1M/mp={audit_cash:,.0f})",
            flush=True,
        )

    paths = write_wrl_outputs(
        Path(output_dir),
        ts,
        all_closed,
        all_open,
        all_watch,
        all_scanner,
        wcfg,
        host_meta=host_meta,
        tickers=loaded,
        host_cfg=hcfg,
        tbn_cfg=cfg,
        drive_link=drive_link,
        no_yfinance=bool(no_yfinance),
    )
    wins = sum(1 for r in all_closed if r.pnl_pct > 0)
    losses = sum(1 for r in all_closed if r.pnl_pct <= 0)
    total_pnl = sum(r.pnl_dollars for r in all_closed)
    print(
        f"[WRL] Closed: {paths['closed']} ({len(all_closed)} trades, {wins}W/{losses}L, "
        f"PnL=${total_pnl:.2f})",
        flush=True,
    )
    print(f"[WRL] Open: {paths['open']} ({len(all_open)} positions)", flush=True)
    print(f"[WRL] Watchlist: {paths['watchlist']} ({len(all_watch)} rows)", flush=True)
    print(f"[WRL] Scanner: {paths['scanner']} ({len(all_scanner)} rows)", flush=True)
    if skipped:
        print(f"[WRL] Skipped symbols: {','.join(skipped)}", flush=True)
    return 0
