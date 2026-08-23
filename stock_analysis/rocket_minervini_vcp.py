"""Minervini SEPA / VCP Stage-2 pivot breakout — TBN mode ``mvcp_mode``.

New strategy module (not a BRT/YH/WPBR/RL/RS remap). Host: ``rocket_tbn.py``.
Outputs: ``drive/MVCP_*_<stamp>.csv``.

Theory freeze: ``drive/paul_experiments/tbn_new_systems/minervini_vcp/10_theory.md``.
"""
from __future__ import annotations

import csv
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, fields
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

# ---------------------------------------------------------------------------
# Config (read from BRTConfig / -v; defaults match Theory + 40_engine_plan)
# ---------------------------------------------------------------------------


@dataclass
class MvcpConfig:
    mvcp_mode: bool = True
    # Template
    mvcp_rs_min_percentile: float = 80.0
    mvcp_rs_lookback: int = 252
    mvcp_sma200_rise_bars: int = 21
    mvcp_min_pct_above_52w_low: float = 0.30
    mvcp_max_pct_below_52w_high: float = 0.25
    # VCP geometry
    mvcp_min_contractions: int = 2
    mvcp_max_contractions: int = 6
    mvcp_swing_k: int = 3
    mvcp_depth_shrink: float = 0.65
    mvcp_max_first_depth: float = 0.40
    mvcp_min_final_depth: float = 0.02
    mvcp_min_base_bars: int = 15
    mvcp_max_base_bars: int = 120
    mvcp_vol_dry_ratio: float = 0.85
    mvcp_vol_dry_soft_confirm: bool = True
    mvcp_require_prior_advance: bool = True
    mvcp_prior_advance_pct: float = 0.20
    mvcp_prior_advance_bars: int = 63
    # Entry / risk / exit
    mvcp_vol_breakout_mult: float = 1.5
    mvcp_max_extension_above_pivot: float = 0.05
    stop_pct: float = 0.92
    stop_pct_is_multiplier: bool = True
    mvcp_stop_eps: float = 0.001
    target_pct: float = 1.25
    mvcp_strength_pct: float = 0.25
    mvcp_strength_bars: int = 15
    mvcp_trail_sma: int = 20
    mvcp_trail_arm_pct: float = 0.10
    mvcp_time_stop_bars: int = 10
    mvcp_time_stop_min_gain: float = 0.05
    symbol_reentry_cooldown_days: int = 20
    entry_start_date: str = ""
    entry_end_date: str = ""
    # RS universe: "data_dir" = all CSVs in data dir; "run" = active ticker list only
    mvcp_rs_universe: str = "data_dir"
    brt_cash: float = 19_350.0


def mvcp_config_from_brt(cfg: Any) -> MvcpConfig:
    kw: dict[str, Any] = {}
    for f in fields(MvcpConfig):
        if hasattr(cfg, f.name):
            kw[f.name] = getattr(cfg, f.name)
    return MvcpConfig(**kw)


# ---------------------------------------------------------------------------
# Helpers / dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrendTemplateResult:
    ok: bool
    rs_percentile: float | None
    fail_reasons: tuple[str, ...]


@dataclass(frozen=True)
class VcpPattern:
    contractions: int
    depths: tuple[float, ...]
    pivot: float
    final_low: float
    start_idx: int
    end_idx: int
    vol_dry_ok: bool
    prior_advance_ok: bool


@dataclass
class MvcpClosedRow:
    symbol: str
    side: str
    date_opened: str
    entry_price: float
    stop_price: float
    target_price: float
    date_closed: str
    exit_price: float
    exit_type: str
    days_held: int
    pnl_pct: float
    pnl_dollars: float
    ann_ror_pct: float
    max_price: float
    pivot: float
    contractions: int
    depths: str
    rs_percentile: float
    final_low: float
    trigger_date: str
    trigger_close: float
    vol_ratio_trigger: float
    one_liner: str

    def to_csv_row(self) -> list[str]:
        return [
            self.symbol,
            self.side,
            self.date_opened,
            f"{self.entry_price:.4f}",
            f"{self.stop_price:.4f}",
            f"{self.target_price:.4f}",
            self.date_closed,
            f"{self.exit_price:.4f}",
            self.exit_type,
            str(self.days_held),
            f"{self.pnl_pct:.4f}",
            f"{self.pnl_dollars:.2f}",
            f"{self.ann_ror_pct:.2f}",
            f"{self.max_price:.4f}",
            f"{self.pivot:.4f}",
            str(self.contractions),
            self.depths,
            f"{self.rs_percentile:.2f}",
            f"{self.final_low:.4f}",
            self.trigger_date,
            f"{self.trigger_close:.4f}",
            f"{self.vol_ratio_trigger:.4f}",
            self.one_liner,
        ]


MVCP_CLOSED_HEADER = [
    "SYMBOL",
    "SIDE",
    "DATE_OPENED",
    "ENTRY_PRICE",
    "STOP_PRICE",
    "TARGET_PRICE",
    "DATE_CLOSED",
    "EXIT_PRICE",
    "EXIT_TYPE",
    "DAYS_HELD",
    "PNL_PCT",
    "PNL_DOLLARS",
    "ANN_ROR_PCT",
    "MAX_PRICE",
    "PIVOT",
    "CONTRACTIONS",
    "DEPTHS",
    "RS_PERCENTILE",
    "FINAL_LOW",
    "TRIGGER_DATE",
    "TRIGGER_CLOSE",
    "VOL_RATIO_TRIGGER",
    "ONE_LINER",
]

MVCP_OPEN_HEADER = [
    "SYMBOL",
    "DATE_OPENED",
    "ENTRY_PRICE",
    "CURRENT_PRICE",
    "PNL_PCT",
    "DAYS_OPEN",
    "STOP_LOSS",
    "TARGET",
    "PIVOT",
    "CONTRACTIONS",
    "RS_PERCENTILE",
]

MVCP_WATCHLIST_HEADER = [
    "SYMBOL",
    "ASOF_DATE",
    "PIVOT",
    "CLOSE",
    "DIST_TO_PIVOT_PCT",
    "CONTRACTIONS",
    "RS_PERCENTILE",
    "TEMPLATE_OK",
    "NOTES",
]


def _iso(d: Any) -> str:
    if hasattr(d, "strftime"):
        return d.strftime("%Y%m%d")
    s = str(d)[:10].replace("-", "")
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


def prepare_bars(df: pd.DataFrame) -> dict[str, Any]:
    df = df.sort_index()
    dates = [_iso(d) for d in df.index]
    o = df["Open"].astype(float).to_numpy()
    h = df["High"].astype(float).to_numpy()
    l = df["Low"].astype(float).to_numpy()
    c = df["Close"].astype(float).to_numpy()
    vol = df["Volume"].astype(float).to_numpy() if "Volume" in df.columns else np.zeros(len(df))
    close_s = pd.Series(c)
    sma50 = close_s.rolling(50, min_periods=50).mean().to_numpy()
    sma150 = close_s.rolling(150, min_periods=150).mean().to_numpy()
    sma200 = close_s.rolling(200, min_periods=200).mean().to_numpy()
    trail_n = 20
    sma_trail = close_s.rolling(trail_n, min_periods=trail_n).mean().to_numpy()
    vol_sma50 = pd.Series(vol).rolling(50, min_periods=50).mean().to_numpy()
    vol_sma10 = pd.Series(vol).rolling(10, min_periods=10).mean().to_numpy()
    high_52w = pd.Series(h).rolling(252, min_periods=252).max().to_numpy()
    low_52w = pd.Series(l).rolling(252, min_periods=252).min().to_numpy()
    return {
        "dates": dates,
        "o": o,
        "h": h,
        "l": l,
        "c": c,
        "vol": vol,
        "sma50": sma50,
        "sma150": sma150,
        "sma200": sma200,
        "sma_trail": sma_trail,
        "vol_sma50": vol_sma50,
        "vol_sma10": vol_sma10,
        "high_52w": high_52w,
        "low_52w": low_52w,
        "n": len(dates),
    }


# ---------------------------------------------------------------------------
# Trend Template
# ---------------------------------------------------------------------------


def trend_template_pass(
    bars: dict[str, Any],
    i: int,
    cfg: MvcpConfig,
    rs_percentile: float | None,
) -> TrendTemplateResult:
    fails: list[str] = []
    c = float(bars["c"][i])
    sma50 = bars["sma50"][i]
    sma150 = bars["sma150"][i]
    sma200 = bars["sma200"][i]
    if not (np.isfinite(sma50) and np.isfinite(sma150) and np.isfinite(sma200)):
        return TrendTemplateResult(False, rs_percentile, ("sma_warmup",))

    if not (c > sma150 and c > sma200):
        fails.append("price_vs_sma150_200")
    if not (sma150 > sma200):
        fails.append("sma150_vs_sma200")
    rise = int(cfg.mvcp_sma200_rise_bars)
    if i < rise or not np.isfinite(bars["sma200"][i - rise]):
        fails.append("sma200_rise_warmup")
    elif not (sma200 > bars["sma200"][i - rise]):
        fails.append("sma200_not_rising")
    if not (sma50 > sma150 and sma50 > sma200):
        fails.append("sma50_stack")
    if not (c > sma50):
        fails.append("price_vs_sma50")

    low52 = bars["low_52w"][i]
    high52 = bars["high_52w"][i]
    if not (np.isfinite(low52) and np.isfinite(high52) and low52 > 0 and high52 > 0):
        fails.append("52w_warmup")
    else:
        # Theory: Close >= 1.30 × Low_52w
        if c < (1.0 + float(cfg.mvcp_min_pct_above_52w_low)) * low52:
            fails.append("below_30pct_52w_low")
        # within 25% of 52w high: Close >= high * (1 - max_pct_below)
        floor = float(high52) * (1.0 - float(cfg.mvcp_max_pct_below_52w_high))
        if c < floor:
            fails.append("too_far_from_52w_high")

    if rs_percentile is None or not np.isfinite(rs_percentile):
        fails.append("rs_missing")
    elif float(rs_percentile) < float(cfg.mvcp_rs_min_percentile):
        fails.append("rs_below_min")

    return TrendTemplateResult(ok=not fails, rs_percentile=rs_percentile, fail_reasons=tuple(fails))


# ---------------------------------------------------------------------------
# VCP geometry
# ---------------------------------------------------------------------------


def _fractal_swings(h: np.ndarray, l: np.ndarray, k: int, lo: int, hi: int) -> tuple[list[int], list[int]]:
    """Return swing-high / swing-low indices in [lo, hi] with ±k confirmation (hi exclusive of right pad)."""
    n = len(h)
    sh: list[int] = []
    sl: list[int] = []
    # Need ±k bars confirmed → last confirmable index is n-1-k
    last = min(hi, n - 1 - k)
    first = max(lo, k)
    for i in range(first, last + 1):
        window_h = h[i - k : i + k + 1]
        window_l = l[i - k : i + k + 1]
        if h[i] >= np.max(window_h):
            sh.append(i)
        if l[i] <= np.min(window_l):
            sl.append(i)
    return sh, sl


def detect_vcp(bars: dict[str, Any], cfg: MvcpConfig, asof_i: int) -> VcpPattern | None:
    """Detect a completed VCP whose coil ends at/near ``asof_i`` (pivot shelf through asof)."""
    k = int(cfg.mvcp_swing_k)
    n = int(bars["n"])
    if asof_i < int(cfg.mvcp_min_base_bars) + k + 5:
        return None
    h = bars["h"]
    l = bars["l"]
    vol = bars["vol"]
    max_base = int(cfg.mvcp_max_base_bars)
    min_base = int(cfg.mvcp_min_base_bars)
    win_lo = max(0, asof_i - max_base - 2 * k)
    sh, sl = _fractal_swings(h, l, k, win_lo, asof_i + 1)
    if len(sh) < 2 or len(sl) < 2:
        return None

    # Build contractions: for each swing high, take the lowest swing low strictly after it
    # and before the next swing high (or asof). Keep chronological H→L pairs that shrink.
    candidates: list[tuple[int, int, float]] = []  # (hi_idx, lo_idx, depth)
    for j, hi_i in enumerate(sh):
        next_hi = sh[j + 1] if j + 1 < len(sh) else asof_i + 1
        lows_between = [x for x in sl if hi_i < x < next_hi]
        if not lows_between:
            continue
        lo_i = min(lows_between, key=lambda x: l[x])
        hi_px = float(h[hi_i])
        if hi_px <= 0:
            continue
        depth = (hi_px - float(l[lo_i])) / hi_px
        if depth <= 0:
            continue
        candidates.append((hi_i, lo_i, depth))

    if len(candidates) < int(cfg.mvcp_min_contractions):
        return None

    # Prefer the rightmost contiguous shrinking sequence ending with the last candidate near asof
    best: VcpPattern | None = None
    min_c = int(cfg.mvcp_min_contractions)
    max_c = int(cfg.mvcp_max_contractions)
    shrink = float(cfg.mvcp_depth_shrink)

    for end in range(len(candidates) - 1, min_c - 2, -1):
        for start in range(0, end - min_c + 2):
            seq = candidates[start : end + 1]
            if not (min_c <= len(seq) <= max_c):
                continue
            depths = [d for _, _, d in seq]
            if depths[0] > float(cfg.mvcp_max_first_depth):
                continue
            if depths[-1] < float(cfg.mvcp_min_final_depth):
                continue
            ok_shrink = True
            for a, b in zip(depths, depths[1:]):
                if b > a * shrink + 1e-12:
                    ok_shrink = False
                    break
            if not ok_shrink:
                continue
            first_hi = seq[0][0]
            last_lo = seq[-1][1]
            last_hi = seq[-1][0]
            # Breakout bar must be after the coil completes (final swing low confirmed)
            if asof_i <= last_lo:
                continue
            base_bars = asof_i - first_hi
            if base_bars < min_base or base_bars > max_base:
                continue
            # Pivot = max High over final contraction only (last swing high -> last swing low)
            # Do NOT include asof_i — otherwise Close>pivot is nearly impossible.
            pivot = float(np.max(h[last_hi : last_lo + 1]))
            final_low = float(l[last_lo])

            # Volume dry-up: avg vol final contraction <= ratio * avg vol prior contraction
            vol_dry_ok = True
            if len(seq) >= 2:
                prev_hi, prev_lo, _ = seq[-2]
                fin_hi, fin_lo, _ = seq[-1]
                prev_slice = vol[prev_hi : prev_lo + 1]
                fin_slice = vol[fin_hi : fin_lo + 1]
                if len(prev_slice) and len(fin_slice):
                    prev_avg = float(np.mean(prev_slice))
                    fin_avg = float(np.mean(fin_slice))
                    if prev_avg > 0 and fin_avg > prev_avg * float(cfg.mvcp_vol_dry_ratio):
                        vol_dry_ok = False
            if not vol_dry_ok:
                continue
            if cfg.mvcp_vol_dry_soft_confirm:
                v10 = bars["vol_sma10"][asof_i]
                v50 = bars["vol_sma50"][asof_i]
                if np.isfinite(v10) and np.isfinite(v50) and v50 > 0 and v10 > v50:
                    pass

            # Prior advance into base
            prior_ok = True
            if cfg.mvcp_require_prior_advance:
                pb = int(cfg.mvcp_prior_advance_bars)
                if first_hi < pb:
                    prior_ok = False
                else:
                    base_ref = float(bars["c"][first_hi - pb])
                    if base_ref <= 0:
                        prior_ok = False
                    else:
                        adv = (float(bars["c"][first_hi]) - base_ref) / base_ref
                        prior_ok = adv >= float(cfg.mvcp_prior_advance_pct)
            if not prior_ok:
                continue

            # Optional: require coil still "fresh" — asof within K bars after last_lo + swing confirm
            # Allow up to swing_k + a few bars for breakout attempt after coil
            if asof_i - last_lo > max(10, 3 * k):
                continue

            pat = VcpPattern(
                contractions=len(seq),
                depths=tuple(float(x) for x in depths),
                pivot=pivot,
                final_low=final_low,
                start_idx=first_hi,
                end_idx=last_lo,
                vol_dry_ok=vol_dry_ok,
                prior_advance_ok=prior_ok,
            )
            # Prefer latest-ending / more contractions
            if best is None or pat.end_idx > best.end_idx or (
                pat.end_idx == best.end_idx and pat.contractions > best.contractions
            ):
                best = pat
        if best is not None:
            break
    return best


def mvcp_breakout_signal(
    bars: dict[str, Any],
    i: int,
    pattern: VcpPattern,
    cfg: MvcpConfig,
) -> bool:
    c = float(bars["c"][i])
    pivot = float(pattern.pivot)
    if c <= pivot:
        return False
    chase = float(cfg.mvcp_max_extension_above_pivot)
    if chase > 0 and c > pivot * (1.0 + chase):
        return False
    v50 = bars["vol_sma50"][i]
    if not np.isfinite(v50) or v50 <= 0:
        return False
    if float(bars["vol"][i]) < float(cfg.mvcp_vol_breakout_mult) * float(v50):
        return False
    return True


def compute_stop(entry: float, final_low: float, cfg: MvcpConfig) -> float:
    eps = float(cfg.mvcp_stop_eps)
    structural = float(final_low) * (1.0 - eps)
    if cfg.stop_pct_is_multiplier:
        floor_8 = entry * float(cfg.stop_pct)
    else:
        floor_8 = entry * (1.0 - float(cfg.stop_pct))
    # never risk more than 8%; may risk less if coil tighter
    return max(structural, floor_8)


# ---------------------------------------------------------------------------
# RS percentile precompute
# ---------------------------------------------------------------------------


def _read_close_series(path: Path) -> Optional[pd.Series]:
    try:
        df = pd.read_csv(path, usecols=lambda c: str(c).lower() in ("date", "close", "adj close"))
    except Exception:
        try:
            df = pd.read_csv(path)
        except Exception:
            return None
    cols = {c.lower(): c for c in df.columns}
    date_col = cols.get("date")
    close_col = cols.get("close") or cols.get("adj close")
    if not date_col or not close_col:
        return None
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col]).sort_values(date_col)
    s = pd.Series(df[close_col].astype(float).values, index=df[date_col])
    s = s[~s.index.duplicated(keep="last")]
    return s


def precompute_rs_percentiles(
    data_dir: Path,
    lookback: int = 252,
    symbols_filter: Optional[set[str]] = None,
    max_symbols: int = 0,
) -> dict[str, dict[str, float]]:
    """Return {SYMBOL: {YYYYMMDD: percentile_0_100}} using trailing ``lookback`` return rank.

    Cross-section is rebuilt per calendar date among symbols with a valid return that day.
    """
    paths = sorted(data_dir.glob("*.csv"))
    if symbols_filter is not None:
        paths = [p for p in paths if p.stem.upper() in symbols_filter]
    if max_symbols > 0:
        paths = paths[:max_symbols]

    rets: dict[str, pd.Series] = {}
    for i, p in enumerate(paths):
        sym = p.stem.upper()
        s = _read_close_series(p)
        if s is None or len(s) < lookback + 5:
            continue
        r = s / s.shift(lookback) - 1.0
        r = r.dropna()
        if r.empty:
            continue
        # index as YYYYMMDD
        r.index = pd.Index([_iso(d) for d in r.index])
        rets[sym] = r
        if (i + 1) % 200 == 0:
            print(f"[MVCP] RS precompute loaded {i + 1}/{len(paths)} CSVs...", flush=True)

    if not rets:
        return {}

    # Union of dates
    all_dates = sorted(set().union(*(set(s.index) for s in rets.values())))
    # Build matrix in chunks by date for memory simplicity
    out: dict[str, dict[str, float]] = {sym: {} for sym in rets}
    # Sample every date would be slow; vectorize via DataFrame
    df = pd.DataFrame({sym: ser for sym, ser in rets.items()})
    # rank pct along columns (axis=1) → percentile 0..100
    ranks = df.rank(axis=1, pct=True, method="average") * 100.0
    for sym in ranks.columns:
        col = ranks[sym].dropna()
        out[sym] = {str(idx): float(v) for idx, v in col.items()}
    print(f"[MVCP] RS precompute done: {len(out)} symbols, lookback={lookback}", flush=True)
    return out


def rs_lookup(rs_map: dict[str, dict[str, float]], symbol: str, iso: str) -> float | None:
    m = rs_map.get(symbol.upper())
    if not m:
        return None
    v = m.get(iso)
    if v is not None:
        return float(v)
    # nearest prior date ≤ iso
    keys = [k for k in m if k <= iso]
    if not keys:
        return None
    return float(m[max(keys)])


# ---------------------------------------------------------------------------
# Per-symbol backtest
# ---------------------------------------------------------------------------


def backtest_symbol(
    symbol: str,
    df: pd.DataFrame,
    cfg: MvcpConfig,
    rs_map: dict[str, dict[str, float]],
) -> tuple[list[MvcpClosedRow], list[dict[str, Any]], list[dict[str, Any]]]:
    """Backtest with fill-bar exit skip (enter at open, manage from next bar)."""
    bars = prepare_bars(df)
    n = bars["n"]
    closed: list[MvcpClosedRow] = []
    open_rows: list[dict[str, Any]] = []
    watch: list[dict[str, Any]] = []
    pos: dict[str, Any] | None = None
    cooldown_until = ""
    cash = float(cfg.brt_cash)
    trail_n = int(cfg.mvcp_trail_sma)
    if trail_n != 20:
        bars["sma_trail"] = pd.Series(bars["c"]).rolling(trail_n, min_periods=trail_n).mean().to_numpy()
    min_i = max(220, int(cfg.mvcp_min_base_bars) + int(cfg.mvcp_swing_k) + 5)

    for i in range(min_i, n):
        iso = bars["dates"][i]

        if pos is not None and i > int(pos["entry_i"]):
            entry_i = int(pos["entry_i"])
            entry = float(pos["entry"])
            stop = float(pos["stop"])
            target = float(pos["target"])
            max_px = max(float(pos["max_price"]), float(bars["h"][i]))
            pos["max_price"] = max_px
            days_held = i - entry_i
            o = float(bars["o"][i])
            hi = float(bars["h"][i])
            lo = float(bars["l"][i])
            cl = float(bars["c"][i])
            exit_px = None
            exit_type = ""

            if o <= stop:
                exit_px = o
                exit_type = "GAP_DOWN" if o < stop - 1e-9 else "STOP_LOSS"
            elif lo <= stop:
                exit_px = stop
                exit_type = "STOP_LOSS"

            if exit_px is None:
                strength_line = entry * (1.0 + float(cfg.mvcp_strength_pct))
                target_line = entry * float(cfg.target_pct) if float(cfg.target_pct) > 0 else strength_line
                if hi >= strength_line and days_held <= int(cfg.mvcp_strength_bars):
                    exit_px = strength_line
                    exit_type = "STRENGTH"
                elif hi >= target_line:
                    exit_px = target_line
                    exit_type = "TARGET"

            if exit_px is None and days_held >= int(cfg.mvcp_time_stop_bars):
                max_gain = (max_px / entry) - 1.0 if entry > 0 else 0.0
                if max_gain < float(cfg.mvcp_time_stop_min_gain):
                    exit_px = cl
                    exit_type = "TIME_STOP"

            if exit_px is None:
                arm = entry * (1.0 + float(cfg.mvcp_trail_arm_pct))
                if max_px >= arm:
                    sma_t = bars["sma_trail"][i]
                    if np.isfinite(sma_t) and cl < float(sma_t):
                        exit_px = cl
                        exit_type = "TRAIL_SMA"

            if exit_px is not None:
                pnl_pct = (exit_px / entry - 1.0) * 100.0
                shares = cash / entry if entry > 0 else 0.0
                pnl_d = shares * (exit_px - entry)
                cal = max(1, _calendar_days(pos["entry_iso"], iso))
                ann = ((exit_px / entry) ** (365.0 / cal) - 1.0) * 100.0 if entry > 0 else 0.0
                depths_s = ";".join(f"{d:.3f}" for d in pos["depths"])
                closed.append(
                    MvcpClosedRow(
                        symbol=symbol,
                        side="LONG",
                        date_opened=pos["entry_iso"],
                        entry_price=entry,
                        stop_price=stop,
                        target_price=target,
                        date_closed=iso,
                        exit_price=exit_px,
                        exit_type=exit_type,
                        days_held=days_held,
                        pnl_pct=pnl_pct,
                        pnl_dollars=pnl_d,
                        ann_ror_pct=ann,
                        max_price=max_px,
                        pivot=float(pos["pivot"]),
                        contractions=int(pos["contractions"]),
                        depths=depths_s,
                        rs_percentile=float(pos["rs"]),
                        final_low=float(pos["final_low"]),
                        trigger_date=pos["trigger_iso"],
                        trigger_close=float(pos["trigger_close"]),
                        vol_ratio_trigger=float(pos["vol_ratio"]),
                        one_liner=(
                            f"{symbol} | IN {pos['entry_iso']} @ {entry:.2f} -> OUT {iso} @ {exit_px:.2f} | "
                            f"{exit_type} {pnl_pct:+.1f}% | {days_held}d | pivot {pos['pivot']:.2f} "
                            f"n={pos['contractions']}"
                        ),
                    )
                )
                cooldown_until = iso if int(cfg.symbol_reentry_cooldown_days) > 0 else ""
                pos = None
                continue

        if pos is not None:
            continue
        if cooldown_until and int(cfg.symbol_reentry_cooldown_days) > 0:
            if _calendar_days(cooldown_until, iso) < int(cfg.symbol_reentry_cooldown_days):
                continue
        if i + 1 >= n:
            continue

        rs = rs_lookup(rs_map, symbol, iso)
        tt = trend_template_pass(bars, i, cfg, rs)
        pat = detect_vcp(bars, cfg, i)
        if pat is None:
            continue

        if float(bars["c"][i]) <= pat.pivot:
            dist = (pat.pivot - float(bars["c"][i])) / pat.pivot * 100.0 if pat.pivot else 0.0
            if dist <= 8.0:
                watch.append(
                    {
                        "symbol": symbol,
                        "asof": iso,
                        "pivot": pat.pivot,
                        "close": float(bars["c"][i]),
                        "dist": dist,
                        "contractions": pat.contractions,
                        "rs": rs if rs is not None else float("nan"),
                        "template_ok": tt.ok,
                        "notes": "coil" if tt.ok else ",".join(tt.fail_reasons[:3]),
                    }
                )
            continue

        if not tt.ok:
            continue
        if not mvcp_breakout_signal(bars, i, pat, cfg):
            continue

        fill_i = i + 1
        fill_iso = bars["dates"][fill_i]
        if not _entry_date_allowed(fill_iso, cfg.entry_start_date, cfg.entry_end_date):
            continue
        entry = float(bars["o"][fill_i])
        if entry <= 0:
            continue
        stop = compute_stop(entry, pat.final_low, cfg)
        target = entry * float(cfg.target_pct) if float(cfg.target_pct) > 0 else entry * 1.25
        v50 = float(bars["vol_sma50"][i])
        vol_ratio = float(bars["vol"][i]) / v50 if v50 > 0 else 0.0
        pos = {
            "entry_i": fill_i,
            "entry_iso": fill_iso,
            "entry": entry,
            "stop": stop,
            "target": target,
            "max_price": max(entry, float(bars["h"][fill_i])),
            "pivot": pat.pivot,
            "contractions": pat.contractions,
            "depths": pat.depths,
            "rs": float(rs) if rs is not None else 0.0,
            "final_low": pat.final_low,
            "trigger_iso": iso,
            "trigger_close": float(bars["c"][i]),
            "vol_ratio": vol_ratio,
        }

    if pos is not None:
        i = n - 1
        iso = bars["dates"][i]
        entry = float(pos["entry"])
        cl = float(bars["c"][i])
        open_rows.append(
            {
                "symbol": symbol,
                "date_opened": pos["entry_iso"],
                "entry_price": entry,
                "current_price": cl,
                "pnl_pct": (cl / entry - 1.0) * 100.0,
                "days_open": i - int(pos["entry_i"]),
                "stop": float(pos["stop"]),
                "target": float(pos["target"]),
                "pivot": float(pos["pivot"]),
                "contractions": int(pos["contractions"]),
                "rs": float(pos["rs"]),
            }
        )
    if watch:
        watch = [watch[-1]]
    return closed, open_rows, watch


# ---------------------------------------------------------------------------
# Parallel symbol tasks (ProcessPool; same pattern as rocket_rl)
# ---------------------------------------------------------------------------


@dataclass
class MvcpSymbolResult:
    symbol: str
    closed: list[MvcpClosedRow]
    open_rows: list[dict[str, Any]]
    watch: list[dict[str, Any]]
    skip_reason: str = ""


def _mvcp_cfg_dict(cfg: MvcpConfig) -> dict[str, Any]:
    return {f.name: getattr(cfg, f.name) for f in fields(MvcpConfig)}


def _mvcp_cfg_from_dict(d: dict[str, Any]) -> MvcpConfig:
    return MvcpConfig(**{f.name: d[f.name] for f in fields(MvcpConfig)})


def _process_mvcp_symbol(
    args: tuple[str, pd.DataFrame, dict[str, Any], dict[str, float]],
) -> MvcpSymbolResult:
    """Picklable worker: one symbol backtest. ``rs_sym`` is that symbol's RS map only."""
    sym, df, cfg_d, rs_sym = args
    cfg = _mvcp_cfg_from_dict(cfg_d)
    rs_map = {sym.upper(): rs_sym} if rs_sym else {}
    closed, open_rows, watch = backtest_symbol(sym, df, cfg, rs_map)
    return MvcpSymbolResult(sym, closed, open_rows, watch)


def _run_mvcp_symbol_tasks(
    tasks: list[tuple[str, pd.DataFrame, dict[str, Any], dict[str, float]]],
    workers: int,
) -> list[MvcpSymbolResult]:
    results: list[MvcpSymbolResult] = []
    if workers > 0 and len(tasks) > 1:
        n_w = min(int(workers), len(tasks), 32)
        print(f"[MVCP] Spawning {n_w} worker process(es) for {len(tasks)} symbols", flush=True)
        with ProcessPoolExecutor(max_workers=n_w) as ex:
            futs = {ex.submit(_process_mvcp_symbol, t): t[0] for t in tasks}
            for fut in as_completed(futs):
                sym = futs[fut]
                try:
                    res = fut.result()
                except Exception as e:
                    print(f"[MVCP] skip {sym}: worker failed ({e})", flush=True)
                    results.append(MvcpSymbolResult(sym, [], [], [], skip_reason=f"worker failed ({e})"))
                    continue
                results.append(res)
                print(
                    f"[MVCP] {res.symbol}: {len(res.closed)} closed, {len(res.open_rows)} open",
                    flush=True,
                )
    else:
        for t in tasks:
            res = _process_mvcp_symbol(t)
            results.append(res)
            print(
                f"[MVCP] {res.symbol}: {len(res.closed)} closed, {len(res.open_rows)} open",
                flush=True,
            )
    return results


# ---------------------------------------------------------------------------
# Writers + host entry
# ---------------------------------------------------------------------------


def write_mvcp_outputs(
    output_dir: Path,
    ts: str,
    closed: list[MvcpClosedRow],
    open_rows: list[dict[str, Any]],
    watch_rows: list[dict[str, Any]],
    cfg: MvcpConfig,
    *,
    host_meta: Optional[dict[str, Any]] = None,
    tickers: Optional[dict[str, pd.DataFrame]] = None,
    host_cfg: Any = None,
    no_yfinance: bool = False,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    host_meta = host_meta or {}
    closed_path = output_dir / f"MVCP_Closed_{ts}.csv"
    open_path = output_dir / f"MVCP_Open_{ts}.csv"
    watch_path = output_dir / f"MVCP_Watchlist_{ts}.csv"
    summary_path = output_dir / f"MVCP_Summary_{ts}.csv"
    report_path = output_dir / f"MVCP_Report_{ts}.csv"
    audit_path = output_dir / f"MVCP_Audit_Report_{ts}.csv"

    with closed_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(MVCP_CLOSED_HEADER)
        for r in closed:
            w.writerow(r.to_csv_row())

    with open_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(MVCP_OPEN_HEADER)
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
                    f"{r['pivot']:.4f}",
                    r["contractions"],
                    f"{r['rs']:.2f}",
                ]
            )

    with watch_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(MVCP_WATCHLIST_HEADER)
        for r in watch_rows:
            w.writerow(
                [
                    r["symbol"],
                    r["asof"],
                    f"{r['pivot']:.4f}",
                    f"{r['close']:.4f}",
                    f"{r['dist']:.2f}",
                    r["contractions"],
                    f"{r['rs']:.2f}" if np.isfinite(r["rs"]) else "",
                    "1" if r["template_ok"] else "0",
                    r["notes"],
                ]
            )

    # Per-symbol summary (production sibling columns so FIT / concat / assessments work)
    by_sym: dict[str, list[MvcpClosedRow]] = {}
    for r in closed:
        by_sym.setdefault(r.symbol, []).append(r)
    total_pnl_all = sum(r.pnl_dollars for r in closed) or 0.0
    days_per_year = 365.25

    def _first_data_date(sym: str) -> str:
        if not tickers or sym not in tickers:
            return ""
        df = tickers[sym]
        if df is None or len(df) == 0:
            return ""
        try:
            if isinstance(df.index, pd.DatetimeIndex) and len(df.index):
                d0 = df.index[0]
            elif "Date" in df.columns:
                d0 = pd.to_datetime(df["Date"].iloc[0])
            else:
                return ""
            ts0 = pd.Timestamp(d0)
            return ts0.strftime("%Y-%m-%d")
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
                "PROFIT_FACTOR",
                "PCT_OF_TOTAL_PNL",
                # Same names/order as BRT/YH/RS write_brt_summary (filled by write_analysis_artifacts).
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
            sum_wins = sum(r.pnl_dollars for r in rows if r.pnl_pct > 1e-9)
            sum_losses = abs(sum(r.pnl_dollars for r in rows if r.pnl_pct < -1e-9))
            if sum_losses > 0:
                pf = sum_wins / sum_losses
            else:
                pf = sum_wins if sum_wins > 0 else 0.0
            first = _first_data_date(sym)
            years = 0.0
            if first and rows:
                try:
                    d0 = datetime.strptime(first.replace("-", "")[:8], "%Y%m%d")
                    d1 = datetime.strptime(
                        str(rows[-1].date_closed).replace("-", "")[:8], "%Y%m%d"
                    )
                    years = max((d1 - d0).days / days_per_year, 1e-6)
                except Exception:
                    years = 1.0
            elif first:
                try:
                    d0 = datetime.strptime(first.replace("-", "")[:8], "%Y%m%d")
                    years = max((datetime.now() - d0).days / days_per_year, 1e-6)
                except Exception:
                    years = 1.0
            else:
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
                    f"{pf:.2f}",
                    f"{(100.0 * pnl / total_pnl_all) if total_pnl_all else 0.0:.1f}%",
                    "",  # CURRENT_MARKET_CAP (yfinance via write_analysis_artifacts)
                    "",  # SECTOR
                    "",  # INDUSTRY
                    first,
                    f"{(len(rows) / years):.2f}",
                    f"{max_win:.2f}%",
                    f"{med_pct:+.2f}%",
                    f"{(sum(r.days_held for r in rows) / len(rows)) if rows else 0.0:.1f}",
                ]
            )

    # Report rollup
    n_tr = len(closed)
    wins = sum(1 for r in closed if r.pnl_pct > 0)
    total_pnl = sum(r.pnl_dollars for r in closed)
    avg_pnl = (sum(r.pnl_pct for r in closed) / n_tr) if n_tr else 0.0
    exit_counts: dict[str, int] = {}
    for r in closed:
        exit_counts[r.exit_type] = exit_counts.get(r.exit_type, 0) + 1
    with report_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["metric", "value"])
        w.writerow(["stamp", ts])
        w.writerow(["trades", n_tr])
        w.writerow(["wins", wins])
        w.writerow(["losses", n_tr - wins])
        w.writerow(["pct_wins", f"{(100.0 * wins / n_tr) if n_tr else 0:.2f}"])
        w.writerow(["total_pnl_dollars", f"{total_pnl:.2f}"])
        w.writerow(["avg_pnl_pct", f"{avg_pnl:.2f}"])
        w.writerow(["open_positions", len(open_rows)])
        w.writerow(["Max_Positions", host_meta.get("host_max_positions", "")])
        w.writerow(["brt_cash", host_meta.get("host_brt_cash", getattr(cfg, "brt_cash", ""))])
        w.writerow(["audit_brt_cash_1m", host_meta.get("host_audit_brt_cash", "")])
        w.writerow(["total_pnl_audit_1m_scale", host_meta.get("total_pnl_audit_1m", "")])
        for k, v in sorted(exit_counts.items()):
            w.writerow([f"exit_{k}", v])

    equity_path = output_dir / f"MVCP_EquityCurve_{ts}.csv"
    equity_meta_path = output_dir / f"MVCP_EquityMeta_{ts}.csv"
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
            file_prefix="MVCP",
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
        # Fallback realized-ledger (exit-date cumulative $)
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
        from brt_audit_columns import empty_audit_row, write_wide_audit_csv
    except ImportError:
        from stock_analysis.brt_audit_columns import (  # type: ignore
            empty_audit_row,
            write_wide_audit_csv,
        )

    link = f"https://drive.google.com/drive/search?q={ts}"
    row = empty_audit_row()
    row["Timestamp_Drive"] = f'=hyperlink("{link}","{ts}")'
    row["mvcp_mode"] = "true"
    row["sb_mode"] = "false"
    row["rs_mode"] = "false"
    row["rl_mode"] = "false"
    row["mts_mode"] = "false"
    for fdef in fields(MvcpConfig):
        if fdef.name in row:
            row[fdef.name] = getattr(cfg, fdef.name)
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
        ):
            if hasattr(host_cfg, k) and k in row:
                row[k] = getattr(host_cfg, k)
    losses = n_tr - wins
    row["Total_Trades"] = n_tr
    row["Wins"] = wins
    row["Losses"] = losses
    row["BE"] = 0
    row["Pct_Wins"] = f"{(100.0 * wins / n_tr) if n_tr else 0:.2f}"
    row["Pct_Losses"] = f"{(100.0 * losses / n_tr) if n_tr else 0:.2f}"
    row["Total_PNL"] = host_meta.get("total_pnl_audit_1m", f"{total_pnl:.2f}")
    row["Avg_PNL_Pct"] = f"{avg_pnl:.2f}"
    row["Max_Positions"] = host_meta.get("host_max_positions", "")
    row["brt_cash"] = host_meta.get(
        "host_audit_brt_cash", host_meta.get("host_brt_cash", getattr(cfg, "brt_cash", ""))
    )
    row["Aggressive_Total_PNL"] = aggressive_total or host_meta.get("aggressive_total_pnl", "")
    row["Aggressive_Max_DD"] = aggressive_max_dd or host_meta.get("aggressive_max_dd", "")
    row["Max_DD"] = f"{max_dd_pct:.2f}"
    row["Param_Name"] = ""
    row["Param_Value"] = ""
    write_wide_audit_csv(audit_path, row)

    corr_path = output_dir / f"MVCP_Correlation_{ts}.csv"
    try:
        import sys

        _sa = Path(__file__).resolve().parent
        if str(_sa) not in sys.path:
            sys.path.insert(0, str(_sa))
        from correlate_brt_closed import run_correlation_report

        run_correlation_report(str(closed_path), str(corr_path))
    except Exception as e:
        print(f"[MVCP] Correlation skipped: {e}", flush=True)

    # Cheap ONE_LINER / FIT / ImproveHints (same helper as rocket_tbn write_all_outputs).
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
            prefix="MVCP",
            no_yfinance=bool(no_yfinance),
        )
    except Exception as e:
        print(f"[MVCP] analysis artifacts skipped: {e}", flush=True)

    # LatestRun mirrors (core + Audit + EquityCurve)
    for src, name in (
        (closed_path, "MVCP_LatestRun_Closed.csv"),
        (open_path, "MVCP_LatestRun_Open.csv"),
        (summary_path, "MVCP_LatestRun_Summary.csv"),
        (watch_path, "MVCP_LatestRun_Watchlist.csv"),
        (audit_path, "MVCP_LatestRun_Audit_Report.csv"),
        (equity_path, "MVCP_LatestRun_EquityCurve.csv"),
    ):
        dest = output_dir / name
        dest.write_bytes(src.read_bytes())

    (output_dir / "MVCP_last_run_ts.txt").write_text(ts + "\n", encoding="utf-8")
    # Keep shared last_run_ts for host tooling that still reads the unprefixed name
    (output_dir / "last_run_ts.txt").write_text(ts, encoding="utf-8")
    return {
        "closed": closed_path,
        "open": open_path,
        "watchlist": watch_path,
        "summary": summary_path,
        "report": report_path,
        "audit": audit_path,
        "equity_curve": equity_path,
        "equity_meta": equity_meta_path,
    }


def run_mvcp_from_brt_main(
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
    del drive_link  # reserved
    mcfg = mvcp_config_from_brt(cfg)
    n_workers = max(0, int(workers or 0))
    # Isolation: neutralize other modes on the cfg snapshot used for audit
    print(
        f"[MVCP] Minervini VCP Stage-2 on {len(ticker_list)} symbols "
        f"(rs_min={mcfg.mvcp_rs_min_percentile}, depth_shrink={mcfg.mvcp_depth_shrink}, "
        f"stop={mcfg.stop_pct}, target={mcfg.target_pct}, workers={n_workers})",
        flush=True,
    )
    print(
        "[MVCP] Exit priority: STOP/GAP -> STRENGTH(<=15d +25%) / TARGET -> TIME_STOP -> TRAIL_SMA20",
        flush=True,
    )

    rs_filter: Optional[set[str]] = None
    if str(mcfg.mvcp_rs_universe).strip().lower() == "run":
        rs_filter = {s.upper() for s in ticker_list}
        print("[MVCP] RS universe = run symbols only (weak for tiny -s; prefer data_dir)", flush=True)
    else:
        print(f"[MVCP] RS universe = all CSVs under {data_dir}", flush=True)

    t0 = time.time()
    rs_map = precompute_rs_percentiles(
        Path(data_dir),
        lookback=int(mcfg.mvcp_rs_lookback),
        symbols_filter=rs_filter,
    )
    print(f"[MVCP] RS precompute {time.time() - t0:.1f}s", flush=True)

    all_closed: list[MvcpClosedRow] = []
    all_open: list[dict[str, Any]] = []
    all_watch: list[dict[str, Any]] = []
    loaded: dict[str, pd.DataFrame] = {}
    skipped: list[str] = []
    cfg_d = _mvcp_cfg_dict(mcfg)
    tasks: list[tuple[str, pd.DataFrame, dict[str, Any], dict[str, float]]] = []

    for sym in ticker_list:
        df = tickers.get(sym) if tickers else None
        if df is None or (hasattr(df, "empty") and df.empty):
            if load_symbol_fn is not None:
                try:
                    df = load_symbol_fn(sym, data_dir)
                except Exception as e:
                    print(f"[MVCP] skip {sym}: load failed ({e})", flush=True)
                    skipped.append(sym)
                    continue
        if df is None or len(df) < 250:
            print(f"[MVCP] skip {sym}: insufficient bars ({0 if df is None else len(df)})", flush=True)
            skipped.append(sym)
            continue
        loaded[sym] = df
        rs_sym = dict(rs_map.get(sym.upper(), {}) or {})
        tasks.append((sym, df, cfg_d, rs_sym))

    t_bt = time.time()
    results = _run_mvcp_symbol_tasks(tasks, n_workers)
    for res in results:
        if res.skip_reason:
            skipped.append(res.symbol)
            continue
        all_closed.extend(res.closed)
        all_open.extend(res.open_rows)
        all_watch.extend(res.watch)
    print(f"[MVCP] Symbol backtest {time.time() - t_bt:.1f}s (workers={n_workers})", flush=True)

    all_closed.sort(key=lambda r: (r.date_opened, r.symbol))

    # Host sizing parity with YH/BRT/RS Closed dollar-scale (tbn_host_sizing).
    host_meta: dict[str, Any] = {}
    hcfg = HostSizingConfig(
        brt_cash=float(getattr(cfg, "brt_cash", mcfg.brt_cash) or mcfg.brt_cash),
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
        mcfg.brt_cash = adj
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
            f"[MVCP] Host dollar-scale: PNL_DOLLARS × {scale:.6g}; "
            f"brt_cash -> {adj:,.0f} (deployable/Max_Positions={max_pos}; "
            f"audit_label 1M/mp={audit_cash:,.0f})",
            flush=True,
        )

    paths = write_mvcp_outputs(
        Path(output_dir),
        ts,
        all_closed,
        all_open,
        all_watch,
        mcfg,
        host_meta=host_meta,
        tickers=loaded,
        host_cfg=hcfg,
        no_yfinance=bool(no_yfinance),
    )
    wins = sum(1 for r in all_closed if r.pnl_pct > 0)
    losses = sum(1 for r in all_closed if r.pnl_pct <= 0)
    total_pnl = sum(r.pnl_dollars for r in all_closed)
    print(
        f"[MVCP] Closed: {paths['closed']} ({len(all_closed)} trades, {wins}W/{losses}L, "
        f"PnL=${total_pnl:.2f})",
        flush=True,
    )
    print(f"[MVCP] Open: {paths['open']} ({len(all_open)} positions)", flush=True)
    print(f"[MVCP] Summary: {paths['summary']}", flush=True)
    agg = Path(output_dir) / f"MVCP_EquityCurve_Aggressive_{ts}.csv"
    if agg.exists():
        print(f"[MVCP] Equity Aggressive: {agg}", flush=True)
    if skipped:
        print(f"[MVCP] Skipped symbols: {','.join(skipped)}", flush=True)
    return 0
