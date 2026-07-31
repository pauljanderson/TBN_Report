"""RL missed / almost-taken positive moves (optional deep post-run analysis).

Heuristic scan of OHLC + SMAs — **not** a full MarkTen / AWK portfolio replay.
There is no historical reject CSV from ``rocket_rl`` / AWK (Watchlist + Scanner are
last-bar only). This module approximates:

1. **NEAR_MISS** — dip+stack primary gate fired, secondary filters (or too_high fill)
   blocked entry; records block tags + forward returns / max gain.
2. **BLIND_SPOT** — stack-aligned SMA50-dip vicinity + material forward rally, but
   primary gate incomplete (no uptick / close>SMA50 / rising, etc.) — “weren’t looking”.

Limits (document in HTML / CSV notes):
- Ignores in-position / flush / IND / SPY-TC / entry-window / vol day effects unless
  those gates are on in Report and SPY maps are supplied.
- Not identical to live MarkTen; use charts + agent review for confirmation.
"""
from __future__ import annotations

import csv
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd

try:
    from rocket_rl import ATR_EMA_MULT, ATR_PERIOD, SMA_50, _prepare_bars
    from rocket_rl_config import RLConfig, atr_pct_band_passes, parse_rl_atr_percent_bound, parse_rl_too_high
except ImportError:
    from stock_analysis.rocket_rl import (  # type: ignore
        ATR_EMA_MULT,
        ATR_PERIOD,
        SMA_50,
        _prepare_bars,
    )
    from stock_analysis.rocket_rl_config import (  # type: ignore
        RLConfig,
        atr_pct_band_passes,
        parse_rl_atr_percent_bound,
        parse_rl_too_high,
    )

MISSED_MOVES_CSV_HEADER = (
    "SYMBOL,KIND,TRIGGER_DATE,BLOCK_REASONS,SETUP_NOTES,TRIGGER_CLOSE,SMA50_REF,NEXT_OPEN,"
    "FWD_RET_5D_PCT,FWD_RET_20D_PCT,FWD_MAX_GAIN_20D_PCT,FWD_MAX_GAIN_60D_PCT,"
    "HIT_TARGET_LIKE_60D,DAYS_TO_TARGET_LIKE,ALREADY_TRADED_NEARBY,HEURISTIC_NOTE"
)

_REPORT_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "sma_qual": ("rl_sma_qual", "sma_qual"),
    "rl_cash": ("rl_cash",),
    "rl_dip_pct": ("rl_dip_pct",),
    "rl_50_sma_lookback": ("rl_50_sma_lookback",),
    "rl_stop_pct": ("rl_stop_pct",),
    "rl_target_pct": ("rl_target_pct",),
    "rl_too_high": ("rl_too_high",),
    "rl_expansion": ("rl_expansion",),
    "rl_acc_min": ("rl_acc_min",),
    "rl_acc_count": ("rl_acc_count",),
    "expansion_lookback_days": ("rl_expansion_lookback_days", "expansion_lookback_days"),
    "rl_cut_the_losers": ("rl_cut_the_losers",),
    "rl_atr_low_percent": ("rl_atr_low_percent",),
    "rl_atr_high_percent": ("rl_atr_high_percent",),
    "rl_atr_high_value": ("rl_atr_high_value",),
    "rl_low_price": ("rl_low_price",),
    "peak_threshold_max": ("rl_peak_threshold_max", "peak_threshold_max"),
    "rl_slope_period": ("rl_slope_period",),
    "rl_slope_threshold": ("rl_slope_threshold",),
    "rl_shock_threshold": ("rl_shock_threshold",),
    "rl_shock_rehab_days": ("rl_shock_rehab_days",),
    "rl_shock_max_allowed": ("rl_shock_max_allowed",),
    "spy_inclusion": ("rl_spy_inclusion", "spy_inclusion"),
    "avg_vol_days": ("rl_avg_vol_days", "avg_vol_days"),
    "vol_pct_threshold": ("rl_vol_pct_threshold", "vol_pct_threshold"),
}


def _truthy(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    s = str(val or "").strip().lower()
    return s in ("1", "true", "yes", "y", "on")


def _fnum(val: Any, default: float = 0.0) -> float:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return default
    s = str(val).strip().replace("%", "").replace(",", "")
    if not s or s.upper() in ("N/A", "NAN", "NONE", ""):
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _ymd8(val: Any) -> str:
    s = str(val or "").strip().replace("-", "")
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else ""


def _iso_dash(ymd: str) -> str:
    d = _ymd8(ymd)
    if len(d) >= 8:
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    return str(ymd or "")


def rl_config_from_report(report_path: Optional[Path]) -> RLConfig:
    """Build RLConfig from ``RL_Report_<ts>.csv`` when present; else defaults."""
    if report_path is None or not Path(report_path).is_file():
        return RLConfig()
    with Path(report_path).open(newline="", encoding="utf-8") as f:
        row = next(csv.DictReader(f), {}) or {}
    kwargs: dict[str, Any] = {}
    for fld in fields(RLConfig):
        aliases = _REPORT_FIELD_ALIASES.get(fld.name, (f"rl_{fld.name}", fld.name))
        raw = None
        key_present = False
        for a in aliases:
            if a in row:
                key_present = True
                if str(row[a]).strip() != "":
                    raw = row[a]
                    break
        if raw is None:
            # Explicit empty ATR% / too_high in Report → treat as off (not dataclass default).
            if key_present and fld.name in ("rl_atr_low_percent", "rl_atr_high_percent"):
                kwargs[fld.name] = None
            elif key_present and fld.name == "rl_too_high":
                kwargs[fld.name] = 0.0
            continue
        if fld.name in ("sma_qual", "spy_inclusion", "watch_disable", "indicator_cache"):
            kwargs[fld.name] = _truthy(raw)
        elif fld.name in ("rl_atr_low_percent", "rl_atr_high_percent"):
            kwargs[fld.name] = parse_rl_atr_percent_bound(raw)
        elif fld.name == "rl_too_high":
            kwargs[fld.name] = parse_rl_too_high(raw)
        elif fld.name in (
            "rl_50_sma_lookback",
            "rl_acc_min",
            "rl_acc_count",
            "expansion_lookback_days",
            "rl_slope_period",
            "rl_shock_rehab_days",
            "rl_shock_max_allowed",
            "avg_vol_days",
            "watch_min_score",
            "rl_exit_days",
            "rl_flush_days",
            "spy_int_tc_lag",
        ):
            try:
                kwargs[fld.name] = int(float(str(raw).strip()))
            except (TypeError, ValueError):
                pass
        else:
            try:
                kwargs[fld.name] = float(raw)
            except (TypeError, ValueError):
                if isinstance(fld.default, str):
                    kwargs[fld.name] = str(raw)
    try:
        return RLConfig(**kwargs)
    except TypeError:
        return RLConfig()


@dataclass
class MissedMoveEvent:
    symbol: str
    kind: str  # NEAR_MISS | BLIND_SPOT
    trigger_date: str
    block_reasons: str
    setup_notes: str
    trigger_close: float
    sma50_ref: float
    next_open: float
    fwd_ret_5d_pct: float
    fwd_ret_20d_pct: float
    fwd_max_gain_20d_pct: float
    fwd_max_gain_60d_pct: float
    hit_target_like_60d: int
    days_to_target_like: int
    already_traded_nearby: int
    heuristic_note: str = "heuristic!=MarkTen"

    def as_csv_row(self) -> list[Any]:
        return [
            self.symbol,
            self.kind,
            _iso_dash(self.trigger_date),
            self.block_reasons,
            self.setup_notes,
            f"{self.trigger_close:.4f}",
            f"{self.sma50_ref:.4f}",
            f"{self.next_open:.4f}",
            f"{self.fwd_ret_5d_pct:.2f}",
            f"{self.fwd_ret_20d_pct:.2f}",
            f"{self.fwd_max_gain_20d_pct:.2f}",
            f"{self.fwd_max_gain_60d_pct:.2f}",
            self.hit_target_like_60d,
            self.days_to_target_like if self.days_to_target_like >= 0 else "",
            self.already_traded_nearby,
            self.heuristic_note,
        ]


def _entry_dates_by_symbol(closed_rows: Iterable[dict[str, Any]]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    for r in closed_rows:
        sym = str(r.get("SYMBOL", "") or "").strip().upper()
        ymd = _ymd8(r.get("DATE OPENED") or r.get("DATE_OPENED") or r.get("ENTRY_DATE"))
        if sym and ymd:
            out[sym].add(ymd)
    return out


def _nearby_trade(entry_dates: set[str], trigger_ymd: str, next_ymd: str, window: int = 5) -> bool:
    """True if a Closed entry falls within ±window calendar-ish ymd compare (coarse)."""
    if not entry_dates:
        return False
    # Exact match on fill day or trigger day
    if trigger_ymd in entry_dates or next_ymd in entry_dates:
        return True
    # Coarse: same YYYYMM and day within window via int math on yyyymmdd (good enough)
    try:
        t = int(trigger_ymd)
        n = int(next_ymd) if next_ymd else t
    except ValueError:
        return False
    for e in entry_dates:
        try:
            ei = int(e)
        except ValueError:
            continue
        if abs(ei - t) <= window or abs(ei - n) <= window:
            # yyyymmdd numeric proximity is imperfect across month ends; also check ±3 trading via string prefix
            if e[:6] == trigger_ymd[:6] or e[:6] == (next_ymd[:6] if next_ymd else ""):
                return True
            if abs(ei - t) <= window + 27:  # allow month boundary fuzzy
                day_t = t % 100
                day_e = ei % 100
                if abs(day_e - day_t) <= window and abs((ei // 100) - (t // 100)) <= 1:
                    return True
    return False


def _forward_metrics(
    o: np.ndarray,
    h: np.ndarray,
    c: np.ndarray,
    sma50: np.ndarray,
    idx: int,
    *,
    target_pct: float,
    y_sma: float,
) -> tuple[float, float, float, float, int, int]:
    """Returns fwd_ret_5, fwd_ret_20, max_gain_20, max_gain_60 (%), hit_target, days_to_target."""
    n = len(c)
    next_idx = idx + 1
    if next_idx >= n or o[next_idx] <= 0:
        return 0.0, 0.0, 0.0, 0.0, 0, -1
    entry = float(o[next_idx])
    target_px = float(y_sma) * float(target_pct) if y_sma > 0 else 0.0

    def _ret_at(bars: int) -> float:
        j = min(n - 1, next_idx + bars - 1)
        return (float(c[j]) / entry - 1.0) * 100.0

    def _max_gain(bars: int) -> float:
        end = min(n, next_idx + bars)
        if end <= next_idx:
            return 0.0
        mx = float(np.nanmax(h[next_idx:end]))
        return (mx / entry - 1.0) * 100.0

    hit = 0
    days_to = -1
    if target_px > 0:
        end = min(n, next_idx + 60)
        for j in range(next_idx, end):
            if float(h[j]) >= target_px:
                hit = 1
                days_to = j - next_idx + 1
                break
    return _ret_at(5), _ret_at(20), _max_gain(20), _max_gain(60), hit, days_to


def scan_symbol_missed_moves(
    symbol: str,
    df: pd.DataFrame,
    cfg: RLConfig,
    *,
    entry_dates: Optional[set[str]] = None,
    spy_maps: Optional[dict[str, dict[str, float]]] = None,
    min_fwd_max_gain_pct: float = 8.0,
    min_blind_max_gain_pct: float = 12.0,
    event_cooldown_bars: int = 15,
    max_events_per_symbol: int = 40,
) -> list[MissedMoveEvent]:
    """Heuristic scan for one symbol. Prefer events with material forward upside."""
    bars = _prepare_bars(df)
    n = bars["n"]
    if n < SMA_50 + cfg.rl_50_sma_lookback + 5:
        return []

    dates: list[str] = bars["dates"]
    o, h, l, c, vol = bars["o"], bars["h"], bars["l"], bars["c"], bars["vol"]
    sma20, sma50, sma100, sma200 = (
        bars["sma"][20],
        bars["sma"][50],
        bars["sma"][100],
        bars["sma"][200],
    )
    entries = entry_dates or set()

    exp_hits = 0
    ready_to_hit = 1
    peak_cl = 0.0
    atr_rolling = 0.0
    acc_hits = 0
    vol_sum = 0.0
    iso_lag = dates[0]

    events: list[MissedMoveEvent] = []
    last_event_idx = -10_000

    for j in range(1, n):
        idx = j - 1
        y_idx = idx - 1 if j > 1 else -1
        y_sma = (
            float(sma50[y_idx])
            if y_idx >= 0 and np.isfinite(sma50[y_idx]) and sma50[y_idx] > 0
            else 0.0
        )

        if y_sma > 0 and j > 1:
            lag = idx - 1
            cur_cl_pct = (c[lag] - y_sma) / y_sma
            peak_cl = max(peak_cl, cur_cl_pct)
            s50_lag = float(sma50[lag]) if np.isfinite(sma50[lag]) and sma50[lag] > 0 else 0.0
            if s50_lag > 0:
                cur_exp = (h[lag] - s50_lag) / s50_lag
                if cur_exp >= cfg.rl_target_pct - 1 and ready_to_hit == 1:
                    exp_hits += 1
                    ready_to_hit = 0
                if l[lag] <= s50_lag * cfg.rl_dip_pct:
                    ready_to_hit = 1

        if cfg.rl_shock_threshold == 0:
            shock_qualified = True
        elif j > 1:
            lag = idx - 1
            p_today = c[lag]
            p_yest = c[lag - 1] if lag > 0 else p_today
            # Shock state not fully tracked for rehab; threshold 0 is production default.
            daily_move = abs((p_today - p_yest) / p_yest) if p_yest > 0 else 0.0
            shock_qualified = daily_move <= cfg.rl_shock_threshold or cfg.rl_shock_max_allowed >= 1
        else:
            shock_qualified = True

        if j > 1:
            lag = idx - 1
            tr = h[lag] - l[lag]
            if atr_rolling == 0:
                atr_rolling = tr
            else:
                atr_rolling = ((atr_rolling * ATR_EMA_MULT) + tr) / ATR_PERIOD

        iso = dates[idx]
        s20 = float(sma20[idx]) if np.isfinite(sma20[idx]) else 0.0
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

        if not cfg.sma_qual or j <= SMA_50 + cfg.rl_50_sma_lookback:
            iso_lag = iso
            continue
        if y_sma <= 0:
            iso_lag = iso
            continue

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
        near_zone = l[idx] <= dip_hi * 1.02 and l[idx] >= dip_lo * 0.98
        uptick = c[idx] > o[idx]
        closeabove50sma = c[idx] > y_sma
        is200sma = y_idx >= 0 and np.isfinite(sma200[y_idx]) and sma200[y_idx] > 0
        sma20over50 = s20 > s50 > 0
        sma50over100 = s50 > s100 > 0
        sma100over200 = s100 > s200 > 0
        stack_ok = is200sma and sma20over50 and sma50over100 and sma100over200

        dip_gate = (
            sma50rising
            and inthe50zone
            and uptick
            and closeabove50sma
            and stack_ok
        )

        next_idx = idx + 1
        next_iso = dates[next_idx] if next_idx < n else ""
        next_open = float(o[next_idx]) if next_idx < n else 0.0
        traded_near = 1 if _nearby_trade(entries, iso, next_iso) else 0

        # --- Secondary filters (only meaningful when dip_gate) ---
        if dip_gate and idx - last_event_idx >= event_cooldown_bars and next_open > 0:
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

            signal_open = float(o[idx])
            atr_vol = atr_rolling / signal_open if signal_open > 0 else 0.0
            atr_inclusion = (
                atr_pct_band_passes(atr_vol, cfg.rl_atr_low_percent, cfg.rl_atr_high_percent)
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

            entry_ok = cfg.rl_too_high == 0 or next_open <= l[idx] * cfg.rl_too_high * cfg.rl_stop_pct

            reasons: list[str] = []
            if not expansion:
                reasons.append("EXP")
            if not acceptance:
                reasons.append("ACC")
            if not cut_it:
                reasons.append("CUT")
            if not atr_inclusion:
                reasons.append("ATR")
            if not spy_ok:
                reasons.append("SPY")
            if not peak_inclusion:
                reasons.append("PEAK")
            if not slope_ok:
                reasons.append("SLOPE")
            if not shock_qualified:
                reasons.append("SHOCK")
            if too_low:
                reasons.append("GAP")
            if not vol_ok:
                reasons.append("VOL")
            if not entry_ok:
                reasons.append("TOO_HIGH")

            filters_ok = not reasons
            # Skip pure "would take" bars already in ledger; if filters pass but not traded → note POSITION?
            if filters_ok and traded_near:
                iso_lag = iso
                continue
            if filters_ok and not traded_near:
                reasons = ["NO_LEDGER_FILL"]
                setup_notes = "filters_ok but no Closed fill (position/cooldown/window?)"
            else:
                setup_notes = "dip+stack OK; secondary blocked"

            if reasons:
                r5, r20, mg20, mg60, hit, days_t = _forward_metrics(
                    o, h, c, sma50, idx, target_pct=cfg.rl_target_pct, y_sma=y_sma
                )
                material = mg20 >= min_fwd_max_gain_pct or mg60 >= min_fwd_max_gain_pct or hit == 1
                if material and not traded_near:
                    events.append(
                        MissedMoveEvent(
                            symbol=symbol.upper(),
                            kind="NEAR_MISS",
                            trigger_date=iso,
                            block_reasons=" ".join(reasons),
                            setup_notes=setup_notes,
                            trigger_close=float(c[idx]),
                            sma50_ref=y_sma,
                            next_open=next_open,
                            fwd_ret_5d_pct=r5,
                            fwd_ret_20d_pct=r20,
                            fwd_max_gain_20d_pct=mg20,
                            fwd_max_gain_60d_pct=mg60,
                            hit_target_like_60d=hit,
                            days_to_target_like=days_t,
                            already_traded_nearby=traded_near,
                        )
                    )
                    last_event_idx = idx
                    if len(events) >= max_events_per_symbol:
                        break

        # --- Blind spots: stack + near dip, incomplete primary, big rally after ---
        elif (
            stack_ok
            and near_zone
            and not dip_gate
            and idx - last_event_idx >= event_cooldown_bars
            and next_open > 0
            and not traded_near
        ):
            primary_miss: list[str] = []
            if not sma50rising:
                primary_miss.append("RISING")
            if not inthe50zone:
                primary_miss.append("DIP")
            if not uptick:
                primary_miss.append("UPTICK")
            if not closeabove50sma:
                primary_miss.append("CLOSE")
            r5, r20, mg20, mg60, hit, days_t = _forward_metrics(
                o, h, c, sma50, idx, target_pct=cfg.rl_target_pct, y_sma=y_sma
            )
            material = mg20 >= min_blind_max_gain_pct or mg60 >= min_blind_max_gain_pct or hit == 1
            if material and primary_miss:
                events.append(
                    MissedMoveEvent(
                        symbol=symbol.upper(),
                        kind="BLIND_SPOT",
                        trigger_date=iso,
                        block_reasons=" ".join(primary_miss),
                        setup_notes="stack+near-dip; primary incomplete - weren't looking",
                        trigger_close=float(c[idx]),
                        sma50_ref=y_sma,
                        next_open=next_open,
                        fwd_ret_5d_pct=r5,
                        fwd_ret_20d_pct=r20,
                        fwd_max_gain_20d_pct=mg20,
                        fwd_max_gain_60d_pct=mg60,
                        hit_target_like_60d=hit,
                        days_to_target_like=days_t,
                        already_traded_nearby=traded_near,
                    )
                )
                last_event_idx = idx
                if len(events) >= max_events_per_symbol:
                    break

        iso_lag = iso

    # Prefer highest forward max-gain events
    events.sort(key=lambda e: (-e.fwd_max_gain_60d_pct, -e.fwd_max_gain_20d_pct, e.trigger_date))
    return events[:max_events_per_symbol]


def scan_missed_moves(
    tickers: dict[str, pd.DataFrame],
    cfg: RLConfig,
    closed_rows: list[dict[str, Any]],
    *,
    spy_df: Optional[pd.DataFrame] = None,
    min_fwd_max_gain_pct: float = 8.0,
    min_blind_max_gain_pct: float = 12.0,
) -> list[MissedMoveEvent]:
    spy_maps = None
    if spy_df is not None and not spy_df.empty:
        try:
            from rocket_rl import _prepare_spy_maps
        except ImportError:
            from stock_analysis.rocket_rl import _prepare_spy_maps  # type: ignore
        spy_maps = _prepare_spy_maps(spy_df)

    by_entry = _entry_dates_by_symbol(closed_rows)
    all_events: list[MissedMoveEvent] = []
    for sym, df in tickers.items():
        if df is None or getattr(df, "empty", True):
            continue
        all_events.extend(
            scan_symbol_missed_moves(
                sym,
                df,
                cfg,
                entry_dates=by_entry.get(sym.upper(), set()),
                spy_maps=spy_maps,
                min_fwd_max_gain_pct=min_fwd_max_gain_pct,
                min_blind_max_gain_pct=min_blind_max_gain_pct,
            )
        )
    all_events.sort(key=lambda e: (-e.fwd_max_gain_60d_pct, e.symbol, e.trigger_date))
    return all_events


def write_missed_moves_csv(events: list[MissedMoveEvent], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        f.write(MISSED_MOVES_CSV_HEADER + "\n")
        for e in events:
            f.write(",".join(str(x) for x in e.as_csv_row()) + "\n")
    return path


def aggregate_miss_themes(
    events: list[MissedMoveEvent],
    *,
    min_symbol_count: int = 2,
) -> list[dict[str, Any]]:
    """Portfolio themes: which block tags co-occur with positive forward moves."""
    tag_syms: dict[str, set[str]] = defaultdict(set)
    tag_count: Counter[str] = Counter()
    tag_kind: dict[str, Counter[str]] = defaultdict(Counter)
    tag_avg_mg: dict[str, list[float]] = defaultdict(list)

    for e in events:
        tags = [t for t in str(e.block_reasons).split() if t]
        if not tags:
            continue
        for t in tags:
            tag_syms[t].add(e.symbol)
            tag_count[t] += 1
            tag_kind[t][e.kind] += 1
            tag_avg_mg[t].append(e.fwd_max_gain_60d_pct)

    lever_map = {
        "EXP": ("rl_expansion / expansion_lookback_days", "Relax expansion lookback or threshold if winners cluster here."),
        "ACC": ("rl_acc_min / rl_acc_count", "Lower acceptance bar if ACC blocks strong follow-through."),
        "CUT": ("rl_cut_the_losers", "Raise cut_the_losers ceiling if CUT blocks winners after shallow prior highs."),
        "ATR": ("rl_atr_low/high_percent", "Widen ATR% band if ATR is a common winner-blocker."),
        "SLOPE": ("rl_slope_threshold / rl_slope_period", "Ease slope gate if SLOPE near-misses then run."),
        "TOO_HIGH": ("rl_too_high", "Raise/disable too_high fill gate if gaps-up still work."),
        "PEAK": ("peak_threshold_max", "Raise peak cap if PEAK blocks after long advances."),
        "SPY": ("spy_inclusion", "Review SPY stack filter if SPY blocks good names."),
        "VOL": ("vol_pct_threshold", "Ease volume surge gate if VOL blocks winners."),
        "GAP": ("rl_stop_pct (too_low/gap)", "Gap-down fills - review stop geometry."),
        "UPTICK": ("primary uptick", "Blind spot: red/flat trigger day before rally - optional soft uptick."),
        "CLOSE": ("close > SMA50", "Blind spot: close still <= SMA50 on dip day."),
        "RISING": ("SMA50 rising lookback", "Blind spot: SMA50 not rising yet."),
        "DIP": ("rl_dip_pct", "Blind spot: low outside dip band (near-zone only)."),
        "NO_LEDGER_FILL": ("position / cooldown / window", "Filters OK but no Closed fill - check overlap/cooldown."),
        "SHOCK": ("rl_shock_*", "Shock rehab blocked entry."),
    }

    themes: list[dict[str, Any]] = []
    for tag, n in tag_count.most_common():
        n_sym = len(tag_syms[tag])
        if n_sym < min_symbol_count and n < 3:
            continue
        lever, suggestion = lever_map.get(
            tag,
            (f"gate:{tag}", f"Review {tag} gate - common on missed winners."),
        )
        avg_mg = sum(tag_avg_mg[tag]) / len(tag_avg_mg[tag]) if tag_avg_mg[tag] else 0.0
        kinds = tag_kind[tag]
        themes.append(
            {
                "hypothesis_id": f"miss_winner_{tag.lower()}",
                "tag": tag,
                "symbol_count": n_sym,
                "event_count": n,
                "near_miss": int(kinds.get("NEAR_MISS", 0)),
                "blind_spot": int(kinds.get("BLIND_SPOT", 0)),
                "avg_fwd_max_gain_60d": round(avg_mg, 1),
                "lever": lever,
                "suggestion": suggestion,
                "symbols": sorted(tag_syms[tag])[:20],
                "evidence": (
                    f"{n} events / {n_sym} syms; avg fwd max-gain 60d {avg_mg:.1f}% "
                    f"(NEAR_MISS={kinds.get('NEAR_MISS', 0)}, BLIND_SPOT={kinds.get('BLIND_SPOT', 0)})"
                ),
            }
        )
    themes.sort(key=lambda t: (-t["symbol_count"], -t["event_count"], t["tag"]))
    return themes


def events_by_symbol(events: list[MissedMoveEvent]) -> dict[str, list[MissedMoveEvent]]:
    out: dict[str, list[MissedMoveEvent]] = defaultdict(list)
    for e in events:
        out[e.symbol].append(e)
    return out
