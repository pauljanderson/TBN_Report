"""Rocket Launcher 50-SMA dip-buy engine — Python port of portfolio_audit.awk (50-trigger path).

Matches AWK bar order: lagged peak/ATR/shock on prior bar, signal on current bar, fill next open.
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

try:
    from rocket_rl_config import RLConfig, rl_config_from_brt_cfg
except ImportError:
    from stock_analysis.rocket_rl_config import RLConfig, rl_config_from_brt_cfg  # type: ignore

# AWK constants (portfolio_audit.awk BEGIN)
SMA_20, SMA_30, SMA_50, SMA_100, SMA_200 = 20, 30, 50, 100, 200
EXPANSION_LOOKBACK = 10
ATR_PERIOD = 14
ATR_EMA_MULT = 13
DAYS_PER_YEAR = 365
MILESTONES = (0.10, 0.20, 0.30, 0.40, 0.50, 0.60)

RL_CLOSED_HEADER = (
    "SYMBOL,DATE OPENED,ENTRY PRICE,SMA20,SMA30,SMA50,SMA100,SMA200,CLOSE TO HIGH,MAX PRICE,"
    "MAX GAIN,MIN PRICE,TOO HIGH?,ORIGINAL STOP,STOP LOSS AT CLOSE,ORIGINAL TARGET,RISK (% to stop),"
    "Reward/risk,DATE CLOSED,DAYS HELD,EXIT PRICE,PNL %,ANNUALIZED ROR,EXIT TYPE,MAE, MAX DRAW DOWN,"
    "TRIGGER TYPE,HIST_HIGH_PCT,HIST_CLOSE_PCT,HIST_LOW_PCT,ENTRY_ATR_STOP,ATR,ATR % OF PRICE,"
    "PREVIOUS EXP TO TARGET,PRIOR RESET,MOST recent EXP,MOST RECENT RESET,SLOPE AT ENTRY,"
    "SPY AT ENTRY,SPY20,SPY30,SPY50,SPY100,SPY200,ACTIVE_SHOCKS,LAST SHOCK MAGNITUDE,"
    "SHOCK REHAB COOLDOWN REMAINING,CLOSE PRIOR,OPEN ON DAY OF CLOSE,DAYS_TO_10,DAYS_TO_20,"
    "DAYS_TO_30,DAYS_TO_40,DAYS_TO_50,DAYS_TO_60,10_TO_CLOSE,20_TO_CLOSE,30_TO_CLOSE,"
    "40_TO_CLOSE,50_TO_CLOSE,60_TO_CLOSE,Trade_CES,PARTIAL_DATE,PARTIAL_AMT,AVG EXIT PRICE,"
    "AVG_VOL,TRIGGER_VOL,PIVOT_HIGH_AT_ENTRY,PIVOT_LOW_AT_ENTRY,STRUCT_HIGH_AT_ENTRY,"
    "STRUCT_LOW_AT_ENTRY,MAJOR_PIVOT_HIGH_AT_ENTRY,MAJOR_PIVOT_LOW_AT_ENTRY,"
    "PIVOT_HIGH_PRICE_AT_ENTRY,PIVOT_LOW_PRICE_AT_ENTRY,LAST_PIVOT_HIGH_PRICE,"
    "LAST_PIVOT_LOW_PRICE,PREV_PIVOT_HIGH_PRICE,PREV_PIVOT_LOW_PRICE"
)

RL_OPEN_HEADER = (
    "SYMBOL,DATE OPENED,ENTRY PRICE,CURRENT PRICE,PNL %,# DAYS OPEN,TRIGGER TYPE,STOP LOSS,TARGET,"
    "DISTANCE COVERED TO TARGET,PREVIOUS EXP TO TARGET,MOST recent EXP,MOST RECENT RESET"
)

RL_SCANNER_HEADER = (
    "SYMBOL,TRIGGER_DATE,TRIGGER_CLOSE,ENTRY_DATE,ENTRY_OPEN_REF,STOP_LOSS,TOO_HIGH_LINE,TARGET,ENTRY_ALLOWED"
)

RL_WATCHLIST_HEADER = (
    "SYMBOL,ASOF_DATE,SETUP_SCORE,WATCH_TIER,MISSING_OR_NOTES,TRIGGER_CLOSE,SMA50_REF"
)

ACCOUNT_SIZE_MULTIPLIER = 10


def days_diff(d1: str, d2: str) -> int:
    """Match portfolio_audit.awk days_diff (mktime local midnight, SECONDS_PER_DAY)."""

    def _epoch(d: str) -> int:
        t = time.struct_time((int(d[:4]), int(d[4:6]), int(d[6:8]), 0, 0, 0, 0, 0, -1))
        return int(time.mktime(t))

    return int((_epoch(d2) - _epoch(d1)) / 86400)


def _prepare_bars(df: pd.DataFrame) -> dict[str, Any]:
    df = df.sort_index()
    dates = [d.strftime("%Y%m%d") if hasattr(d, "strftime") else str(d)[:10].replace("-", "") for d in df.index]
    o = df["Open"].astype(float).to_numpy()
    h = df["High"].astype(float).to_numpy()
    l = df["Low"].astype(float).to_numpy()
    c = df["Close"].astype(float).to_numpy()
    vol = df["Volume"].astype(float).to_numpy() if "Volume" in df.columns else np.zeros(len(df))
    close_s = pd.Series(c)
    smas = {
        20: close_s.rolling(SMA_20, min_periods=SMA_20).mean().to_numpy(),
        30: close_s.rolling(SMA_30, min_periods=SMA_30).mean().to_numpy(),
        50: close_s.rolling(SMA_50, min_periods=SMA_50).mean().to_numpy(),
        100: close_s.rolling(SMA_100, min_periods=SMA_100).mean().to_numpy(),
        200: close_s.rolling(SMA_200, min_periods=SMA_200).mean().to_numpy(),
    }
    return {"dates": dates, "o": o, "h": h, "l": l, "c": c, "vol": vol, "sma": smas, "n": len(dates)}


def _prepare_spy_maps(spy_df: pd.DataFrame) -> dict[str, dict[str, float]]:
    bars = _prepare_bars(spy_df)
    out: dict[str, dict[str, float]] = {"p": {}, "sma": {p: {} for p in (20, 30, 50, 100, 200)}}
    for i, iso in enumerate(bars["dates"]):
        out["p"][iso] = float(bars["c"][i])
        for p in (20, 30, 50, 100, 200):
            v = bars["sma"][p][i]
            if np.isfinite(v) and v > 0:
                out["sma"][p][iso] = float(v)
    return out


@dataclass
class RLClosedRow:
    symbol: str
    entry_iso: str
    entry_price: float
    entry_sma20: float
    entry_sma30: float
    entry_sma50: float
    entry_sma100: float
    entry_sma200: float
    close_to_high: float
    max_price: float
    max_gain: float
    min_price: float
    too_high: float
    original_stop: float
    stop_at_close: float
    original_target: float
    risk_pct: float
    reward_risk: float
    exit_iso: str
    hold_days: int
    exit_price: float
    pnl_pct: float
    ann_ror: float
    exit_type: str
    mae_pct: float
    max_dd: float
    hist_hi: float
    hist_cl: float
    hist_lo: float
    entry_atr_stop: float
    atr_val: float
    exp_hits: int
    prior_reset: str
    last_exp: str
    last_reset: str
    entry_slope: float
    entry_spy_price: float
    entry_spy20: float
    entry_spy30: float
    entry_spy50: float
    entry_spy100: float
    entry_spy200: float
    active_shocks: int
    last_shock_mag: float
    rehab_cooldown: int
    close_prior: float
    open_on_close: float
    m10: int
    m20: int
    m30: int
    m40: int
    m50: int
    m60: int
    m10_to_close: int
    m20_to_close: int
    m30_to_close: int
    m40_to_close: int
    m50_to_close: int
    m60_to_close: int
    trade_ces: float
    partial_date: str
    partial_amt: float
    avg_exit: float
    avg_vol: float
    trigger_vol: float

    def to_csv_row(self) -> str:
        piv = ["0"] * 12
        parts = [
            self.symbol,
            self.entry_iso,
            f"{self.entry_price:.2f}",
            f"{self.entry_sma20:.2f}",
            f"{self.entry_sma30:.2f}",
            f"{self.entry_sma50:.2f}",
            f"{self.entry_sma100:.2f}",
            f"{self.entry_sma200:.2f}",
            f"{self.close_to_high:.2f}",
            f"{self.max_price:.2f}",
            f"{self.max_gain:.2f}",
            f"{self.min_price:.2f}",
            f"{self.too_high:.2f}",
            f"{self.original_stop:.4f}",
            f"{self.stop_at_close:.4f}",
            f"{self.original_target:.4f}",
            f"{self.risk_pct:.4f}",
            f"{self.reward_risk:.2f}",
            self.exit_iso,
            str(self.hold_days),
            f"{self.exit_price:.2f}",
            f"{self.pnl_pct:.2f}%",
            f"{self.ann_ror:.4f}",
            self.exit_type,
            f"{self.mae_pct:.4f}",
            f"{self.max_dd:.6f}",
            "50-trigger",
            f"{self.hist_hi:.4f}",
            f"{self.hist_cl:.4f}",
            f"{self.hist_lo:.4f}",
            f"{self.entry_atr_stop:.4f}",
            f"{self.atr_val:.4f}",
            f"{self.atr_val / self.entry_price:.6f}" if self.entry_price > 0 else "0",
            str(self.exp_hits),
            self.prior_reset,
            self.last_exp,
            self.last_reset,
            f"{self.entry_slope:.4f}",
            f"{self.entry_spy_price:.2f}",
            f"{self.entry_spy20:.2f}",
            f"{self.entry_spy30:.2f}",
            f"{self.entry_spy50:.2f}",
            f"{self.entry_spy100:.2f}",
            f"{self.entry_spy200:.2f}",
            str(self.active_shocks),
            f"{self.last_shock_mag:.4f}",
            str(self.rehab_cooldown),
            f"{self.close_prior:.2f}",
            f"{self.open_on_close:.2f}",
            str(self.m10),
            str(self.m20),
            str(self.m30),
            str(self.m40),
            str(self.m50),
            str(self.m60),
            str(self.m10_to_close),
            str(self.m20_to_close),
            str(self.m30_to_close),
            str(self.m40_to_close),
            str(self.m50_to_close),
            str(self.m60_to_close),
            f"{self.trade_ces:.6f}",
            self.partial_date,
            f"{self.partial_amt:.2f}",
            f"{self.avg_exit:.2f}",
            f"{self.avg_vol:.0f}",
            f"{self.trigger_vol:.0f}",
            *piv,
        ]
        return ",".join(parts)


@dataclass
class RLOpenRow:
    symbol: str
    entry_iso: str
    entry_price: float
    current_price: float
    pnl_pct: float
    days_open: int
    stop: float
    target: float
    dist_covered: float
    exp_hits: int
    last_exp: str
    last_reset: str

    def to_csv_row(self) -> str:
        # AWK open row uses entry_hist_* (never set in 50-trigger path) → 0,, for last three cols
        return (
            f"{self.symbol},{self.entry_iso},{self.entry_price:.2f},{self.current_price:.2f},"
            f"{self.pnl_pct:.2f}%,{self.days_open},50-trigger,{self.stop:.2f},{self.target:.2f},"
            f"{self.dist_covered:.4f},0,,"
        )


@dataclass
class RLScannerRow:
    symbol: str
    trigger_date: str
    trigger_close: float
    entry_date: str
    entry_open_ref: float
    stop_loss: float
    too_high_line: float
    target: float
    entry_allowed: int

    def to_csv_row(self) -> str:
        return (
            f"{self.symbol},{self.trigger_date},{self.trigger_close:.2f},{self.entry_date},"
            f"{self.entry_open_ref:.2f},{self.stop_loss:.2f},{self.too_high_line:.2f},"
            f"{self.target:.2f},{self.entry_allowed}"
        )


@dataclass
class RLWatchRow:
    symbol: str
    asof_date: str
    setup_score: int
    watch_tier: str
    missing_notes: str
    trigger_close: float
    sma50_ref: float

    def to_csv_row(self) -> str:
        miss = self.missing_notes.replace(",", ";")
        return (
            f"{self.symbol},{self.asof_date},{self.setup_score},{self.watch_tier},"
            f"{miss},{self.trigger_close:.2f},{self.sma50_ref:.2f}"
        )


@dataclass
class RLSymbolResult:
    closed: list[RLClosedRow]
    open_row: Optional[RLOpenRow]
    scanner_row: Optional[RLScannerRow]
    watch_row: Optional[RLWatchRow]
    daily_realized: dict[str, float]
    daily_unrealized: dict[str, float]


def _record_watch(
    cfg: RLConfig,
    best: Optional[RLWatchRow],
    candidate: RLWatchRow,
) -> Optional[RLWatchRow]:
    if cfg.watch_disable:
        return best
    if candidate.setup_score < cfg.watch_min_score:
        return best
    if best is None or candidate.setup_score > best.setup_score:
        return candidate
    return best


def _score_near_50_zone(
    *,
    cfg: RLConfig,
    sma50rising: bool,
    inthe50zone: bool,
    uptick: bool,
    closeabove50sma: bool,
    is200sma: bool,
    sma20over50: bool,
    sma50over100: bool,
    sma100over200: bool,
    y_sma: float,
    low: float,
) -> tuple[int, str]:
    wlo = 0
    wmiss = ""
    if is200sma and sma20over50 and sma50over100 and sma100over200:
        wlo += 25
    else:
        wmiss += "STACK "
    if sma50rising:
        wlo += 15
    zt = y_sma * cfg.rl_dip_pct
    zb = y_sma * (1 - (cfg.rl_dip_pct - 1))
    if low <= zt * 1.02 and low >= zb * 0.98:
        wlo += 28
    if inthe50zone:
        wlo += 12
    if uptick:
        wlo += 8
    if closeabove50sma:
        wlo += 8
    return wlo, wmiss.strip()


def _score_pending_filters(
    *,
    is200sma: bool,
    sma20over50: bool,
    sma50over100: bool,
    sma100over200: bool,
    sma50rising: bool,
    inthe50zone: bool,
    uptick: bool,
    closeabove50sma: bool,
    expansion: int,
    acceptance: bool,
    cut_it: int,
    atr_inclusion: bool,
    spy_ok: bool,
    peak_inclusion: bool,
    slope_ok: bool,
    shock_qualified: bool,
    too_low: int,
    vol_ok: bool,
) -> tuple[int, str]:
    wli = 0
    miss = ""
    if is200sma and sma20over50 and sma50over100 and sma100over200:
        wli += 20
    else:
        miss += "STACK "
    if sma50rising:
        wli += 12
    if inthe50zone:
        wli += 13
    if uptick:
        wli += 10
    if closeabove50sma:
        wli += 10
    if expansion:
        wli += 10
    else:
        miss += "EXP "
    if acceptance:
        wli += 5
    else:
        miss += "ACC "
    if cut_it:
        wli += 5
    else:
        miss += "CUT "
    if atr_inclusion:
        wli += 5
    else:
        miss += "ATR "
    if spy_ok:
        wli += 5
    else:
        miss += "SPY "
    if peak_inclusion:
        wli += 3
    else:
        miss += "PEAK "
    if slope_ok:
        wli += 3
    else:
        miss += "SLOPE "
    if shock_qualified:
        wli += 2
    else:
        miss += "SHOCK "
    if not too_low:
        wli += 1
    else:
        miss += "GAP "
    if vol_ok:
        wli += 4
    else:
        miss += "VOL "
    return wli, miss.strip()


def compute_flush_trigger(
    daily_realized: dict[str, float],
    daily_unrealized: dict[str, float],
    rl_cash: float,
    rl_flush_days: int,
) -> dict[str, int]:
    """Portfolio underwater flush map (portfolio_audit.awk END pass 1)."""
    if rl_flush_days <= 0:
        return {}
    all_dates = sorted(set(daily_realized) | set(daily_unrealized))
    initial_account = rl_cash * ACCOUNT_SIZE_MULTIPLIER
    m_realized = 0.0
    flush_hwm = 0.0
    consecutive_underwater = 0
    flush_trigger: dict[str, int] = {}
    for d_iso in all_dates:
        m_realized += daily_realized.get(d_iso, 0.0)
        port_equity = initial_account + m_realized + daily_unrealized.get(d_iso, 0.0)
        if port_equity > flush_hwm:
            flush_hwm = port_equity
            consecutive_underwater = 0
            flush_trigger[d_iso] = 0
        elif flush_hwm > 0 and port_equity < flush_hwm:
            consecutive_underwater += 1
            flush_trigger[d_iso] = 1 if consecutive_underwater >= rl_flush_days else 0
            if flush_trigger[d_iso] == 1:
                consecutive_underwater = 0
                flush_hwm = port_equity
        else:
            consecutive_underwater = 0
            flush_trigger[d_iso] = 0
    return flush_trigger


def _merge_daily_maps(maps: list[dict[str, float]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for m in maps:
        for k, v in m.items():
            out[k] = out.get(k, 0.0) + v
    return out


def run_symbol_rl(
    symbol: str,
    df: pd.DataFrame,
    cfg: RLConfig,
    spy_maps: Optional[dict[str, dict[str, float]]] = None,
    *,
    flush_trigger: Optional[dict[str, int]] = None,
    record_closes: bool = True,
    emit_last_bar_extras: bool = True,
    track_daily_pnl: bool = False,
) -> RLSymbolResult:
    bars = _prepare_bars(df)
    n = bars["n"]
    if n < SMA_50 + cfg.rl_50_sma_lookback + 2:
        return RLSymbolResult([], None, None, None, {}, {})

    dates: list[str] = bars["dates"]
    o, h, l, c, vol = bars["o"], bars["h"], bars["l"], bars["c"], bars["vol"]
    sma20, sma30, sma50, sma100, sma200 = (
        bars["sma"][20],
        bars["sma"][30],
        bars["sma"][50],
        bars["sma"][100],
        bars["sma"][200],
    )

    closed: list[RLClosedRow] = []
    open_row: Optional[RLOpenRow] = None
    scanner_row: Optional[RLScannerRow] = None
    watch_row: Optional[RLWatchRow] = None
    daily_realized: dict[str, float] = {}
    daily_unrealized: dict[str, float] = {}

    # Expansion / peak state
    exp_hits = 0
    ready_to_hit = 1
    last_exp_iso = "0"
    last_reset_iso = "0"
    prior_reset_iso = "0"
    peak_hi = peak_cl = peak_lo = 0.0

    # Shock state (per symbol)
    shock_dates: list[str] = []
    last_shock_mag = 0.0

    atr_rolling = 0.0
    acc_hits = 0
    vol_sum = 0.0

    # Position state
    rl_inv = 0.0
    initial_shares = 0.0
    entry_iso = ""
    entry_price = 0.0
    entry_idx = 0
    rl_stop = 0.0
    original_stop = 0.0
    original_target = 0.0
    rl_target = 0.0
    rl_max_p = 0.0
    rl_min_p = 0.0
    rl_trail_active = 0
    has_hit_time = 0
    time_counter = 0
    has_hit_milestone = 0
    total_exit_proceeds = 0.0
    sym_hwm = 0.0
    max_sym_dd = 0.0
    partial_date = ""
    partial_amt = 0.0
    m_days = [0] * 6

    # Entry snapshot fields
    snap: dict[str, Any] = {}

    iso_lag = dates[0]

    for j in range(1, n + 1):
        idx = j - 1
        y_idx = idx - 1 if j > 1 else -1
        y_iso = dates[y_idx] if y_idx >= 0 else ""
        y_sma = float(sma50[y_idx]) if y_idx >= 0 and np.isfinite(sma50[y_idx]) and sma50[y_idx] > 0 else 0.0

        if y_sma > 0 and j > 1:
            lag = idx - 1
            cur_hi_pct = (h[lag] - y_sma) / y_sma
            cur_cl_pct = (c[lag] - y_sma) / y_sma
            cur_lo_pct = (l[lag] - y_sma) / y_sma
            peak_hi = max(peak_hi, cur_hi_pct)
            peak_cl = max(peak_cl, cur_cl_pct)
            peak_lo = max(peak_lo, cur_lo_pct)
            s50_lag = float(sma50[lag]) if np.isfinite(sma50[lag]) and sma50[lag] > 0 else 0.0
            if s50_lag > 0:
                cur_exp = (h[lag] - s50_lag) / s50_lag
                if cur_exp >= cfg.rl_target_pct - 1 and ready_to_hit == 1:
                    exp_hits += 1
                    prior_reset_iso = last_reset_iso
                    last_exp_iso = iso_lag
                    ready_to_hit = 0
                if l[lag] <= s50_lag * cfg.rl_dip_pct:
                    ready_to_hit = 1
                    last_reset_iso = iso_lag

        # Shock (on lag bar)
        if cfg.rl_shock_threshold == 0:
            shock_qualified = True
            active_shocks = 0
            rehab_cooldown = 0
        elif j > 1:
            lag = idx - 1
            p_today = c[lag]
            p_yest = c[lag - 1] if lag > 0 else p_today
            daily_move = abs((p_today - p_yest) / p_yest) if p_yest > 0 else 0.0
            if daily_move > cfg.rl_shock_threshold:
                shock_dates.append(iso_lag)
                last_shock_mag = daily_move
            active_shocks = 0
            rehab_cooldown = 0
            for sd in reversed(shock_dates):
                diff = days_diff(sd, iso_lag)
                if diff > cfg.rl_shock_rehab_days:
                    break
                active_shocks += 1
                rehab_cooldown = max(rehab_cooldown, cfg.rl_shock_rehab_days - diff)
            shock_qualified = active_shocks <= cfg.rl_shock_max_allowed
        else:
            shock_qualified = True
            active_shocks = 0
            rehab_cooldown = 0

        # ATR on lag bar
        if j > 1:
            lag = idx - 1
            tr = h[lag] - l[lag]
            if atr_rolling == 0:
                atr_rolling = tr
            else:
                atr_rolling = ((atr_rolling * ATR_EMA_MULT) + tr) / ATR_PERIOD

        iso = dates[idx]
        s20 = float(sma20[idx]) if np.isfinite(sma20[idx]) else 0.0
        s30 = float(sma30[idx]) if np.isfinite(sma30[idx]) else 0.0
        s50 = float(sma50[idx]) if np.isfinite(sma50[idx]) else 0.0
        s100 = float(sma100[idx]) if np.isfinite(sma100[idx]) else 0.0
        s200 = float(sma200[idx]) if np.isfinite(sma200[idx]) else 0.0

        if cfg.avg_vol_days > 0:
            vol_sum += vol[idx]
            if j > cfg.avg_vol_days:
                vol_sum -= vol[idx - cfg.avg_vol_days]
            avg_vol = vol_sum / cfg.avg_vol_days if j >= cfg.avg_vol_days else 0.0
        else:
            avg_vol = 0.0

        # Slope + acceptance
        current_slope = 0.0
        if cfg.rl_slope_threshold != 0 and j > cfg.rl_slope_period:
            old_idx = idx - cfg.rl_slope_period
            s50_old = float(sma50[old_idx]) if np.isfinite(sma50[old_idx]) else 0.0
            if s50_old > 0 and s50 > 0:
                current_slope = (s50 / s50_old) - 1.0
        if y_idx >= 0 and np.isfinite(sma50[y_idx]) and sma50[y_idx] > 0 and c[idx] > sma50[y_idx]:
            acc_hits += 1
        if j > cfg.rl_acc_count:
            old_i = idx - cfg.rl_acc_count
            old_prev = old_i - 1
            if old_prev >= 0 and np.isfinite(sma50[old_prev]) and sma50[old_prev] > 0 and c[old_i] > sma50[old_prev]:
                acc_hits -= 1
        acceptance = acc_hits >= cfg.rl_acc_min

        # --- In position: exit management ---
        if rl_inv > 0:
            if track_daily_pnl:
                daily_unrealized[iso] = daily_unrealized.get(iso, 0.0) + (rl_inv * c[idx] - cfg.rl_cash)

            if j > 1 and y_idx >= 0 and np.isfinite(sma50[y_idx]) and sma50[y_idx] > 0:
                rl_target = float(sma50[y_idx]) * cfg.rl_target_pct

            execute_exit = 0
            exit_type = ""
            hit_timed = 0
            rl_sell = 0.0

            if (
                cfg.rl_flush_days > 0
                and flush_trigger is not None
                and flush_trigger.get(iso, 0) == 1
                and iso != entry_iso
            ):
                execute_exit = 1
                exit_type = "FLUSH_EXIT"
                rl_sell = o[idx]

            curr_profit_pct = (h[idx] - entry_price) / entry_price if entry_price > 0 else 0.0
            for mi, mp in enumerate(MILESTONES):
                if curr_profit_pct >= mp and m_days[mi] == 0:
                    m_days[mi] = days_diff(entry_iso, iso) + 1

            if h[idx] > rl_max_p:
                rl_max_p = h[idx]
            if rl_min_p == 0 or l[idx] < rl_min_p:
                rl_min_p = l[idx]

            if has_hit_time == 0 and cfg.rl_exit_percent > 0 and curr_profit_pct >= cfg.rl_exit_percent:
                has_hit_time = 1
                time_counter = 0
            if has_hit_time == 1:
                time_counter += 1

            # Partial exit
            if (
                execute_exit == 0
                and has_hit_milestone == 0
                and cfg.partial_exit_target > 0
                and curr_profit_pct >= cfg.partial_exit_target
            ):
                has_hit_milestone = 1
                partial_date = iso
                shares_to_sell = int(rl_inv * cfg.partial_exit_percent)
                rl_inv -= shares_to_sell
                p_exit = h[idx]
                total_exit_proceeds += shares_to_sell * p_exit
                partial_amt = (shares_to_sell * p_exit) - (shares_to_sell * entry_price)

            if cfg.rl_trail_profit > 0 and rl_trail_active == 0 and h[idx] >= entry_price * (1 + cfg.rl_trail_profit):
                rl_trail_active = 1
                rl_stop = entry_price * (1 + cfg.rl_trail_stop)
            if cfg.rl_trail_profit2 > 0 and h[idx] >= entry_price * (1 + cfg.rl_trail_profit2):
                rl_trail_active = 2
                rl_stop = entry_price * (1 + cfg.rl_trail_stop2)

            if execute_exit == 0:
                timed_exit_px = entry_price * (1 + cfg.rl_exit_percent)
                sma_target_px = rl_target
                stop_price = c[idx] if iso == entry_iso else l[idx]
                if stop_price <= rl_stop:
                    execute_exit = 1
                    rl_sell = rl_stop if rl_stop > o[idx] else o[idx]
                    exit_type = (
                        "TRAIL_STOP2" if rl_trail_active == 2 else ("TRAIL_STOP" if rl_trail_active == 1 else "STOP_LOSS")
                    )
                else:
                    hit_sma = sma_target_px > 0 and h[idx] >= sma_target_px
                    hit_timed = has_hit_time == 1 and time_counter >= cfg.rl_exit_days
                    if hit_sma and hit_timed:
                        execute_exit = 1
                        if sma_target_px < timed_exit_px:
                            rl_sell = sma_target_px if sma_target_px > o[idx] else o[idx]
                            exit_type = "TARGET"
                        else:
                            rl_sell = o[idx]
                            exit_type = "RL_EXIT_DAYS"
                    elif hit_sma:
                        execute_exit = 1
                        exit_type = "TARGET"
                        rl_sell = sma_target_px if sma_target_px > o[idx] else o[idx]
                    elif hit_timed:
                        execute_exit = 1
                        exit_type = "RL_EXIT_DAYS"
                        rl_sell = o[idx]

            if execute_exit == 1:
                if exit_type == "RL_EXIT_DAYS" and hit_timed == 0:
                    if o[idx] > entry_price * (1 + cfg.rl_exit_percent):
                        rl_sell = o[idx]
                    else:
                        rl_sell = entry_price * (1 + cfg.rl_exit_percent)
                elif exit_type == "TARGET":
                    rl_sell = rl_target if rl_target > o[idx] else o[idx]
                elif exit_type == "FLUSH_EXIT":
                    rl_sell = o[idx]
                else:
                    rl_sell = rl_stop

                total_exit_proceeds += rl_inv * rl_sell
                avg_exit = total_exit_proceeds / initial_shares if initial_shares > 0 else rl_sell
                trade_pnl = total_exit_proceeds - (initial_shares * entry_price)
                if track_daily_pnl:
                    daily_realized[iso] = daily_realized.get(iso, 0.0) + trade_pnl
                trade_return = trade_pnl / cfg.rl_cash
                hold_days = days_diff(entry_iso, iso) + 1
                ann_ror = ((1 + trade_return) ** (DAYS_PER_YEAR / hold_days)) - 1 if hold_days > 0 and trade_return > -1 else 0.0
                mae_pct = (entry_price - rl_min_p) / entry_price if entry_price > 0 else 0.0
                current_trade_val = initial_shares * rl_sell
                if current_trade_val > sym_hwm:
                    sym_hwm = current_trade_val
                if sym_hwm > 0 and iso > entry_iso:
                    max_sym_dd = max(max_sym_dd, (sym_hwm - current_trade_val) / sym_hwm)

                entry_idx_snap = snap.get("entry_idx", entry_idx)
                prev_sma50 = float(sma50[entry_idx_snap - 2]) if entry_idx_snap >= 2 else 0.0
                too_high = (entry_price - prev_sma50) / prev_sma50 if prev_sma50 > 0 else 0.0
                max_gain = (rl_max_p - entry_price) / entry_price if entry_price > 0 else 0.0
                risk_pct = (entry_price - original_stop) / entry_price if entry_price > 0 else 0.0
                reward_risk = (
                    (original_target - entry_price) / (entry_price - original_stop)
                    if entry_price > original_stop and entry_price > 0
                    else 0.0
                )
                trade_ces = ((trade_pnl / cfg.rl_cash) * 100) / hold_days if hold_days > 0 else (trade_pnl / cfg.rl_cash) * 100
                m_to = [max(0, hold_days - m) if m > 0 else 0 for m in m_days]

                if record_closes:
                    closed.append(
                        RLClosedRow(
                        symbol=symbol,
                        entry_iso=entry_iso,
                        entry_price=entry_price,
                        entry_sma20=snap.get("sma20", 0.0),
                        entry_sma30=snap.get("sma30", 0.0),
                        entry_sma50=snap.get("sma50", 0.0),
                        entry_sma100=snap.get("sma100", 0.0),
                        entry_sma200=snap.get("sma200", 0.0),
                        close_to_high=snap.get("close_to_high", 0.0),
                        max_price=rl_max_p,
                        max_gain=max_gain,
                        min_price=rl_min_p,
                        too_high=too_high,
                        original_stop=original_stop,
                        stop_at_close=rl_stop,
                        original_target=original_target,
                        risk_pct=risk_pct,
                        reward_risk=reward_risk,
                        exit_iso=iso,
                        hold_days=hold_days,
                        exit_price=rl_sell,
                        pnl_pct=(trade_pnl / cfg.rl_cash) * 100,
                        ann_ror=ann_ror,
                        exit_type=exit_type,
                        mae_pct=mae_pct,
                        max_dd=max_sym_dd,
                        hist_hi=snap.get("peak_hi", 0.0),
                        hist_cl=snap.get("peak_cl", 0.0),
                        hist_lo=snap.get("peak_lo", 0.0),
                        entry_atr_stop=snap.get("atr_stop", 0.0),
                        atr_val=snap.get("atr_val", 0.0),
                        exp_hits=snap.get("exp_hits", 0),
                        prior_reset=snap.get("prior_reset", "0"),
                        last_exp=snap.get("last_exp", "0"),
                        last_reset=snap.get("last_reset", "0"),
                        entry_slope=snap.get("slope", 0.0),
                        entry_spy_price=snap.get("spy_p", 0.0),
                        entry_spy20=snap.get("spy20", 0.0),
                        entry_spy30=snap.get("spy30", 0.0),
                        entry_spy50=snap.get("spy50", 0.0),
                        entry_spy100=snap.get("spy100", 0.0),
                        entry_spy200=snap.get("spy200", 0.0),
                        active_shocks=snap.get("active_shocks", 0),
                        last_shock_mag=snap.get("last_shock_mag", 0.0),
                        rehab_cooldown=snap.get("rehab", 0),
                        close_prior=snap.get("close_prior", 0.0),
                        open_on_close=o[idx],
                        m10=m_days[0],
                        m20=m_days[1],
                        m30=m_days[2],
                        m40=m_days[3],
                        m50=m_days[4],
                        m60=m_days[5],
                        m10_to_close=m_to[0],
                        m20_to_close=m_to[1],
                        m30_to_close=m_to[2],
                        m40_to_close=m_to[3],
                        m50_to_close=m_to[4],
                        m60_to_close=m_to[5],
                        trade_ces=trade_ces,
                        partial_date=partial_date,
                        partial_amt=partial_amt,
                        avg_exit=avg_exit,
                        avg_vol=snap.get("avg_vol", 0.0),
                        trigger_vol=snap.get("trigger_vol", 0.0),
                        )
                    )
                rl_inv = 0.0
                initial_shares = 0.0
                rl_max_p = rl_min_p = 0.0
                rl_trail_active = 0
                has_hit_time = 0
                time_counter = 0
                has_hit_milestone = 0
                total_exit_proceeds = 0.0
                sym_hwm = 0.0
                max_sym_dd = 0.0
                partial_date = ""
                partial_amt = 0.0
                m_days = [0] * 6
                snap = {}

            else:
                current_trade_val = rl_inv * c[idx]
                if current_trade_val > sym_hwm:
                    sym_hwm = current_trade_val
                if sym_hwm > 0 and iso > entry_iso:
                    max_sym_dd = max(max_sym_dd, (sym_hwm - current_trade_val) / sym_hwm)

        elif cfg.sma_qual and j > SMA_50 + cfg.rl_50_sma_lookback:
            lookback_idx = idx - cfg.rl_50_sma_lookback
            sma50rising = (
                lookback_idx >= 0
                and np.isfinite(sma50[idx])
                and np.isfinite(sma50[lookback_idx])
                and sma50[idx] > sma50[lookback_idx]
            )
            dip_hi = y_sma * cfg.rl_dip_pct
            dip_lo = y_sma * (1 - (cfg.rl_dip_pct - 1))
            inthe50zone = l[idx] < dip_hi and l[idx] > dip_lo
            uptick = c[idx] > o[idx]
            closeabove50sma = c[idx] > y_sma
            is200sma = y_idx >= 0 and np.isfinite(sma200[y_idx]) and sma200[y_idx] > 0
            sma20over50 = s20 > s50 > 0
            sma50over100 = s50 > s100 > 0
            sma100over200 = s100 > s200 > 0
            dip_gate = (
                sma50rising
                and inthe50zone
                and uptick
                and closeabove50sma
                and is200sma
                and sma20over50
                and sma50over100
                and sma100over200
            )
            is_last_bar = idx == n - 1

            if emit_last_bar_extras and is_last_bar and rl_inv == 0 and not dip_gate:
                wlo, wmiss = _score_near_50_zone(
                    cfg=cfg,
                    sma50rising=sma50rising,
                    inthe50zone=inthe50zone,
                    uptick=uptick,
                    closeabove50sma=closeabove50sma,
                    is200sma=is200sma,
                    sma20over50=sma20over50,
                    sma50over100=sma50over100,
                    sma100over200=sma100over200,
                    y_sma=y_sma,
                    low=l[idx],
                )
                watch_row = _record_watch(
                    cfg,
                    watch_row,
                    RLWatchRow(
                        symbol=symbol,
                        asof_date=iso,
                        setup_score=wlo,
                        watch_tier="NEAR_50_ZONE",
                        missing_notes=wmiss,
                        trigger_close=c[idx],
                        sma50_ref=y_sma,
                    ),
                )

            if dip_gate:
                expansion = 0
                for k in range(cfg.expansion_lookback_days):
                    p_idx = idx - k
                    if p_idx < 1:
                        continue
                    prev_p = p_idx - 1
                    if np.isfinite(sma50[prev_p]) and sma50[prev_p] > 0 and c[p_idx] >= sma50[prev_p] * cfg.rl_expansion:
                        expansion = 1
                        break

                cur_hi_pct_entry = (h[idx - 1] - y_sma) / y_sma if j > 1 and y_sma > 0 else 0.0
                cut_it = int(cur_hi_pct_entry < cfg.rl_cut_the_losers)

                next_idx = idx + 1
                next_iso = dates[next_idx] if next_idx < n else ""
                signal_open = o[idx]
                next_open = o[next_idx] if next_idx < n else 0.0
                atr_vol = atr_rolling / signal_open if signal_open > 0 else 0.0
                atr_inclusion = (
                    cfg.rl_atr_low_percent <= atr_vol <= cfg.rl_atr_high_percent
                    and atr_rolling < cfg.rl_atr_high_value
                    and signal_open >= cfg.rl_low_price
                )
                peak_inclusion = peak_cl < cfg.peak_threshold_max
                slope_ok = cfg.rl_slope_threshold == 0 or current_slope >= cfg.rl_slope_threshold
                too_low = 0
                if next_idx < n and o[next_idx] > 0 and o[next_idx] < l[idx] * cfg.rl_stop_pct:
                    too_low = 1

                spy_ok = True
                if cfg.spy_inclusion and spy_maps and next_iso:
                    s50m = spy_maps["sma"][50].get(next_iso, 0.0)
                    s100m = spy_maps["sma"][100].get(next_iso, 0.0)
                    s200m = spy_maps["sma"][200].get(next_iso, 0.0)
                    spy_ok = s50m > s100m > s200m > 0

                vol_ok = True
                if cfg.avg_vol_days > 0 and cfg.vol_pct_threshold > 0 and next_iso:
                    entry_day_vol = vol[next_idx] if next_idx < n else 0.0
                    vol_ok = avg_vol > 0 and entry_day_vol >= avg_vol * (1 + cfg.vol_pct_threshold / 100)

                entry_ok = False
                if next_iso and next_open > 0:
                    if cfg.rl_too_high == 0 or next_open <= l[idx] * cfg.rl_too_high * cfg.rl_stop_pct:
                        entry_ok = True

                filters_ok = (
                    expansion
                    and acceptance
                    and cut_it
                    and atr_inclusion
                    and spy_ok
                    and peak_inclusion
                    and slope_ok
                    and shock_qualified
                    and not too_low
                    and vol_ok
                )

                if emit_last_bar_extras and is_last_bar and filters_ok:
                    scan_tgt = float(sma50[y_idx]) * cfg.rl_target_pct if y_idx >= 0 and y_sma > 0 else 0.0
                    stop_lv = l[idx] * cfg.rl_stop_pct
                    th_line = stop_lv * cfg.rl_too_high
                    nxop = next_open if next_open > 0 else 0.0
                    scanner_row = RLScannerRow(
                        symbol=symbol,
                        trigger_date=iso,
                        trigger_close=c[idx],
                        entry_date=next_iso,
                        entry_open_ref=nxop,
                        stop_loss=stop_lv,
                        too_high_line=th_line,
                        target=scan_tgt,
                        entry_allowed=int(entry_ok),
                    )

                if filters_ok and entry_ok:
                    rl_inv = cfg.rl_cash / o[next_idx]
                    initial_shares = rl_inv
                    entry_iso = next_iso
                    entry_price = float(o[next_idx])
                    entry_idx = j + 1
                    rl_stop = l[idx] * cfg.rl_stop_pct
                    original_stop = rl_stop
                    original_target = float(sma50[y_idx]) * cfg.rl_target_pct if y_idx >= 0 else 0.0
                    rl_trail_active = 0
                    has_hit_time = 0
                    time_counter = 0
                    has_hit_milestone = 0
                    total_exit_proceeds = 0.0
                    sym_hwm = 0.0
                    max_sym_dd = 0.0
                    rl_max_p = 0.0
                    rl_min_p = 0.0
                    partial_date = ""
                    partial_amt = 0.0
                    m_days = [0] * 6
                    hi_rng = h[idx] - l[idx]
                    close_to_high = 1 - ((h[idx] - c[idx]) / hi_rng) if hi_rng > 0 else 0.0
                    e20 = float(sma20[next_idx]) if np.isfinite(sma20[next_idx]) else 0.0
                    e30 = float(sma30[next_idx]) if np.isfinite(sma30[next_idx]) else 0.0
                    e50 = float(sma50[next_idx]) if np.isfinite(sma50[next_idx]) else 0.0
                    e100 = float(sma100[next_idx]) if np.isfinite(sma100[next_idx]) else 0.0
                    e200 = float(sma200[next_idx]) if np.isfinite(sma200[next_idx]) else 0.0
                    snap = {
                        "entry_idx": entry_idx,
                        "sma20": e20,
                        "sma30": e30,
                        "sma50": e50,
                        "sma100": e100,
                        "sma200": e200,
                        "close_to_high": close_to_high,
                        "peak_hi": peak_hi,
                        "peak_cl": peak_cl,
                        "peak_lo": peak_lo,
                        "atr_stop": entry_price - atr_rolling * 2,
                        "atr_val": atr_rolling,
                        "exp_hits": exp_hits,
                        "prior_reset": prior_reset_iso,
                        "last_exp": last_exp_iso,
                        "last_reset": last_reset_iso,
                        "slope": current_slope,
                        "avg_vol": avg_vol if cfg.avg_vol_days > 0 else 0.0,
                        "trigger_vol": vol[idx],
                        "close_prior": c[idx],
                        "active_shocks": active_shocks,
                        "last_shock_mag": last_shock_mag,
                        "rehab": rehab_cooldown,
                    }
                    if spy_maps and next_iso:
                        snap["spy_p"] = spy_maps["p"].get(next_iso, 0.0)
                        for sp, sk in ((20, "spy20"), (30, "spy30"), (50, "spy50"), (100, "spy100"), (200, "spy200")):
                            snap[sk] = spy_maps["sma"][sp].get(next_iso, 0.0)

                if emit_last_bar_extras and is_last_bar and rl_inv == 0 and not filters_ok:
                    wli, miss = _score_pending_filters(
                        is200sma=is200sma,
                        sma20over50=sma20over50,
                        sma50over100=sma50over100,
                        sma100over200=sma100over200,
                        sma50rising=sma50rising,
                        inthe50zone=inthe50zone,
                        uptick=uptick,
                        closeabove50sma=closeabove50sma,
                        expansion=expansion,
                        acceptance=acceptance,
                        cut_it=cut_it,
                        atr_inclusion=atr_inclusion,
                        spy_ok=spy_ok,
                        peak_inclusion=peak_inclusion,
                        slope_ok=slope_ok,
                        shock_qualified=shock_qualified,
                        too_low=too_low,
                        vol_ok=vol_ok,
                    )
                    watch_row = _record_watch(
                        cfg,
                        watch_row,
                        RLWatchRow(
                            symbol=symbol,
                            asof_date=iso,
                            setup_score=wli,
                            watch_tier="PENDING_FILTERS",
                            missing_notes=miss,
                            trigger_close=c[idx],
                            sma50_ref=y_sma,
                        ),
                    )

        iso_lag = iso

    if rl_inv > 0:
        last_cl = c[-1]
        open_pnl = (rl_inv * last_cl) - cfg.rl_cash
        dist = (last_cl - entry_price) / (rl_target - entry_price) if rl_target != entry_price else 0.0
        open_row = RLOpenRow(
            symbol=symbol,
            entry_iso=entry_iso,
            entry_price=entry_price,
            current_price=last_cl,
            pnl_pct=(open_pnl / cfg.rl_cash) * 100,
            days_open=n - entry_idx if entry_idx > 0 else 0,
            stop=rl_stop,
            target=rl_target,
            dist_covered=dist,
            exp_hits=snap.get("exp_hits", 0),
            last_exp=snap.get("last_exp", "0"),
            last_reset=snap.get("last_reset", "0"),
        )

    return RLSymbolResult(closed, open_row, scanner_row, watch_row, daily_realized, daily_unrealized)


def _rl_cfg_dict(cfg: RLConfig) -> dict[str, Any]:
    return {f.name: getattr(cfg, f.name) for f in fields(RLConfig)}


def _rl_cfg_from_dict(d: dict[str, Any]) -> RLConfig:
    return RLConfig(**{f.name: d[f.name] for f in fields(RLConfig)})


def _process_rl_symbol(
    args: tuple[
        str,
        pd.DataFrame,
        dict[str, Any],
        Optional[dict],
        Optional[dict[str, int]],
        bool,
        bool,
        bool,
    ],
) -> RLSymbolResult:
    sym, df, cfg_d, spy_maps, flush_trigger, record_closes, emit_last_bar_extras, track_daily_pnl = args
    cfg = _rl_cfg_from_dict(cfg_d)
    return run_symbol_rl(
        sym,
        df,
        cfg,
        spy_maps=spy_maps,
        flush_trigger=flush_trigger,
        record_closes=record_closes,
        emit_last_bar_extras=emit_last_bar_extras,
        track_daily_pnl=track_daily_pnl,
    )


def _run_symbol_tasks(
    tasks: list[tuple],
    workers: int,
) -> list[RLSymbolResult]:
    results: list[RLSymbolResult] = []
    if workers > 0 and len(tasks) > 1:
        with ProcessPoolExecutor(max_workers=min(workers, len(tasks), 32)) as ex:
            futs = [ex.submit(_process_rl_symbol, t) for t in tasks]
            for fut in as_completed(futs):
                results.append(fut.result())
    else:
        for t in tasks:
            results.append(_process_rl_symbol(t))
    return results


def _build_watchlist(
    watch_rows: list[RLWatchRow],
    open_rows: list[RLOpenRow],
    scanner_rows: list[RLScannerRow],
) -> list[RLWatchRow]:
    open_syms = {r.symbol for r in open_rows}
    scan_syms = {r.symbol for r in scanner_rows}
    filtered = [w for w in watch_rows if w.symbol not in open_syms and w.symbol not in scan_syms]
    filtered.sort(key=lambda r: r.symbol)
    return filtered


def run_rl_backtest_batch(
    symbols: list[str],
    tickers: dict[str, pd.DataFrame],
    cfg: RLConfig,
    *,
    spy_df: Optional[pd.DataFrame] = None,
    workers: int = 0,
    load_fn: Any = None,
    data_dir: Optional[Path] = None,
) -> tuple[list[RLClosedRow], list[RLOpenRow], list[RLScannerRow], list[RLWatchRow]]:
    spy_maps = _prepare_spy_maps(spy_df) if spy_df is not None and not spy_df.empty else None
    cfg_d = _rl_cfg_dict(cfg)
    base_tasks: list[tuple[str, pd.DataFrame]] = []
    for sym in symbols:
        df = tickers.get(sym)
        if df is None and load_fn is not None and data_dir is not None:
            df = load_fn(sym, data_dir)
        if df is None or df.empty:
            continue
        base_tasks.append((sym, df))

    flush_trigger: Optional[dict[str, int]] = None
    if cfg.rl_flush_days > 0:
        pass1_tasks = [
            (sym, df, cfg_d, spy_maps, None, False, False, True) for sym, df in base_tasks
        ]
        pass1 = _run_symbol_tasks(pass1_tasks, workers)
        agg_realized = _merge_daily_maps([r.daily_realized for r in pass1])
        agg_unrealized = _merge_daily_maps([r.daily_unrealized for r in pass1])
        flush_trigger = compute_flush_trigger(agg_realized, agg_unrealized, cfg.rl_cash, cfg.rl_flush_days)
        n_flush = sum(1 for v in flush_trigger.values() if v == 1)
        print(f"[RL] Flush pass 1: {len(flush_trigger)} trading days, {n_flush} flush trigger day(s)", flush=True)

    pass_tasks = [
        (
            sym,
            df,
            cfg_d,
            spy_maps,
            flush_trigger,
            True,
            True,
            False,
        )
        for sym, df in base_tasks
    ]
    results = _run_symbol_tasks(pass_tasks, workers)

    all_closed: list[RLClosedRow] = []
    all_open: list[RLOpenRow] = []
    all_scanner: list[RLScannerRow] = []
    all_watch_raw: list[RLWatchRow] = []
    for res in results:
        all_closed.extend(res.closed)
        if res.open_row:
            all_open.append(res.open_row)
        if res.scanner_row:
            all_scanner.append(res.scanner_row)
        if res.watch_row:
            all_watch_raw.append(res.watch_row)

    all_closed.sort(key=lambda r: (r.symbol, r.entry_iso, r.exit_iso))
    all_open.sort(key=lambda r: r.symbol)
    all_scanner.sort(key=lambda r: r.symbol)
    all_watch = _build_watchlist(all_watch_raw, all_open, all_scanner)
    return all_closed, all_open, all_scanner, all_watch


def write_rl_closed(rows: list[RLClosedRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        f.write(RL_CLOSED_HEADER + "\n")
        for row in rows:
            f.write(row.to_csv_row() + "\n")


def write_rl_open(rows: list[RLOpenRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        f.write(RL_OPEN_HEADER + "\n")
        for row in rows:
            f.write(row.to_csv_row() + "\n")


def write_rl_scanner(rows: list[RLScannerRow], path: Path) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        f.write(RL_SCANNER_HEADER + "\n")
        for row in rows:
            f.write(row.to_csv_row() + "\n")


def write_rl_watchlist(rows: list[RLWatchRow], csv_path: Path, txt_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        f.write(RL_WATCHLIST_HEADER + "\n")
        for row in rows:
            f.write(row.to_csv_row() + "\n")
    if rows:
        txt_path.write_text("\n".join(r.symbol for r in rows) + "\n", encoding="utf-8")


def write_rl_outputs(
    output_dir: Path,
    ts: str,
    closed: list[RLClosedRow],
    open_rows: list[RLOpenRow],
    scanner_rows: Optional[list[RLScannerRow]] = None,
    watch_rows: Optional[list[RLWatchRow]] = None,
) -> dict[str, Path]:
    closed_path = output_dir / f"RL_Closed_{ts}.csv"
    open_path = output_dir / f"RL_Open_{ts}.csv"
    write_rl_closed(closed, closed_path)
    write_rl_open(open_rows, open_path)
    paths: dict[str, Path] = {"closed": closed_path, "open": open_path}
    if scanner_rows:
        scanner_path = output_dir / f"RL_Scanner_{ts}.csv"
        write_rl_scanner(scanner_rows, scanner_path)
        paths["scanner"] = scanner_path
    if watch_rows is not None:
        watch_csv = output_dir / f"RL_Watchlist_{ts}.csv"
        watch_txt = output_dir / f"RL_Watchlist_{ts}.txt"
        write_rl_watchlist(watch_rows, watch_csv, watch_txt)
        paths["watchlist"] = watch_csv
        paths["watchlist_txt"] = watch_txt
    (output_dir / "last_run_ts.txt").write_text(ts, encoding="utf-8")
    return paths


def run_rl_from_brt_main(
    *,
    cfg: Any,
    tickers: dict[str, pd.DataFrame],
    ticker_list: list[str],
    output_dir: Path,
    ts: str,
    data_dir: Path,
    load_symbol_fn: Any,
    workers: int,
    spy_df: Optional[pd.DataFrame] = None,
    drive_link: str = "",
) -> int:
    rl_cfg = rl_config_from_brt_cfg(cfg)
    if hasattr(cfg, "rl_cash"):
        rl_cfg = RLConfig(**{**_rl_cfg_dict(rl_cfg), "rl_cash": float(getattr(cfg, "rl_cash", rl_cfg.rl_cash))})

    print(
        f"[RL] Running 50-SMA Rocket Launcher on {len(ticker_list)} symbols "
        f"(rl_cash={rl_cfg.rl_cash:,.0f}, flush_days={rl_cfg.rl_flush_days}, workers={workers})",
        flush=True,
    )
    closed, open_rows, scanner_rows, watch_rows = run_rl_backtest_batch(
        ticker_list,
        tickers,
        rl_cfg,
        spy_df=spy_df,
        workers=workers,
        load_fn=load_symbol_fn,
        data_dir=data_dir,
    )
    paths = write_rl_outputs(output_dir, ts, closed, open_rows, scanner_rows, watch_rows)
    wins = sum(1 for r in closed if r.pnl_pct > 0)
    losses = sum(1 for r in closed if r.pnl_pct < 0)
    print(f"[RL] Closed: {paths['closed']} ({len(closed)} trades, {wins}W/{losses}L)")
    print(f"[RL] Open:   {paths['open']} ({len(open_rows)} positions)")
    if scanner_rows and "scanner" in paths:
        print(f"[RL] Scanner: {paths['scanner']} ({len(scanner_rows)} rows)")
    if watch_rows and "watchlist" in paths:
        print(f"[RL] Watchlist: {paths['watchlist']} ({len(watch_rows)} rows)")

    try:
        from rocket_rl_reports import write_rl_post_reports
    except ImportError:
        from stock_analysis.rocket_rl_reports import write_rl_post_reports  # type: ignore[no-redef]

    write_rl_post_reports(
        cfg=cfg,
        tickers=tickers,
        output_dir=output_dir,
        ts=ts,
        closed_path=paths["closed"],
        open_path=paths.get("open"),
        drive_link=drive_link,
        cash_per_trade=float(rl_cfg.rl_cash),
    )
    return 0
