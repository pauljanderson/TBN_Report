#!/usr/bin/env python3
"""William O'Neil CAN SLIM — price-legs v0 (prefix CS_).

Standalone research engine (not a rocket_tbn mode). Implements N / S / L / M from
OHLCV + optional SPY / Market Monitor. C / A / I soft-fill from yfinance DuckDB
cache when available; gates still default OFF.

Docs: drive/paul_experiments/tbn_new_systems/oneil_canslim/RESEARCH.md
DNA:  .../DNA.md
Run:  run_canslim.bat
"""
from __future__ import annotations

import argparse
import csv
import math
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

try:
    from tbn_host_sizing import (
        DEFAULT_AGGRESSIVE_MAX_MULTIPLE,
        DEFAULT_INITIAL_CAPITAL,
        DEFAULT_MARGIN_UTILIZATION,
        HostSizingConfig,
        apply_host_dollar_scale,
        audit_display_brt_cash,
    )
except ImportError:
    from stock_analysis.tbn_host_sizing import (  # type: ignore
        DEFAULT_AGGRESSIVE_MAX_MULTIPLE,
        DEFAULT_INITIAL_CAPITAL,
        DEFAULT_MARGIN_UTILIZATION,
        HostSizingConfig,
        apply_host_dollar_scale,
        audit_display_brt_cash,
    )

try:
    from ohlcv_store import list_csv_symbols as _list_csv_symbols
except ImportError:
    try:
        from stock_analysis.ohlcv_store import list_csv_symbols as _list_csv_symbols  # type: ignore
    except ImportError:
        _list_csv_symbols = None  # type: ignore

try:
    from fundamentals_yfinance import (
        canslim_dna_from_fundamentals,
        ensure_symbols as _fund_ensure_symbols,
        yfinance_disabled as _fund_yf_disabled,
    )
except ImportError:
    try:
        from stock_analysis.fundamentals_yfinance import (  # type: ignore
            canslim_dna_from_fundamentals,
            ensure_symbols as _fund_ensure_symbols,
            yfinance_disabled as _fund_yf_disabled,
        )
    except ImportError:
        canslim_dna_from_fundamentals = None  # type: ignore
        _fund_ensure_symbols = None  # type: ignore
        _fund_yf_disabled = None  # type: ignore
FILE_PREFIX = "CS"
DAYS_PER_YEAR = 365.25
DEFAULT_CASH = 47_500.0
_WEEK52 = 252


def _as_bool(x: Any) -> bool:
    if isinstance(x, bool):
        return x
    return str(x).strip().lower() in ("1", "true", "yes", "on")


def _iso(d: Any) -> str:
    if hasattr(d, "strftime"):
        return d.strftime("%Y%m%d")
    s = str(d).replace("-", "")[:8]
    return s


def _ymd_dash(d: Any) -> str:
    iso = _iso(d)
    if len(iso) == 8:
        return f"{iso[:4]}-{iso[4:6]}-{iso[6:]}"
    return str(d)[:10]


@dataclass
class CanslimConfig:
    # N — new highs / pivot
    max_pct_below_52w_high: float = 0.25
    pivot_lookback: int = 55
    min_price: float = 5.0
    # S — supply/demand volume
    vol_breakout_mult: float = 1.40
    vol_sma_bars: int = 50
    # L — leadership RS proxy
    rs_min: float = 80.0
    rs_lookback: int = 252
    # M — market
    market_gate: bool = True  # SPY SMA50 > SMA200 lag-1
    mm_gate: bool = False
    mm_min_ratio: float = 2.0
    # C / A / I — soft-fill DNA from yfinance cache; gates default OFF
    require_c: bool = False
    require_a: bool = False
    require_i: bool = False
    c_eps_yoy_min: float = 0.25  # fraction; used only when require_c
    a_eps_cagr_min: float = 0.25
    a_roe_min: float = 0.17
    i_inst_pct_min: float = 0.0  # 0 = any positive institutional % when require_i
    # Risk / exit
    stop_pct: float = 0.92
    target_pct: float = 1.20
    trail_sma: int = 0  # 0 = off; else exit on close < SMA
    time_stop_bars: int = 40
    cooldown_bars: int = 20
    # Sizing
    cash: float = DEFAULT_CASH
    initial_capital: float = DEFAULT_INITIAL_CAPITAL
    aggressive_max_multiple: float = DEFAULT_AGGRESSIVE_MAX_MULTIPLE
    margin_utilization: float = DEFAULT_MARGIN_UTILIZATION
    max_positions: int = 0
    aggressive: bool = False
    host_dollar_scale: bool = True
    entry_start_date: str = ""
    entry_end_date: str = ""
    # Fundamentals soft-fill
    fundamentals_fill: bool = True
    fundamentals_db: str = ""
    force_refresh_fundamentals: bool = False

@dataclass
class ClosedRow:
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
    trigger_date: str
    trigger_close: float
    pivot: float
    pct_below_52w: float
    vol_ratio: float
    rs_percentile: float
    c_status: str
    a_status: str
    n_status: str
    s_status: str
    l_status: str
    i_status: str
    m_status: str
    market_spy_50gt200: str
    mm_ratio: float
    c_eps_yoy: str
    a_eps_cagr: str
    a_roe: str
    s_float: str
    i_sponsor: str
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
            self.trigger_date,
            f"{self.trigger_close:.4f}",
            f"{self.pivot:.4f}",
            f"{self.pct_below_52w:.4f}",
            f"{self.vol_ratio:.4f}",
            f"{self.rs_percentile:.2f}",
            self.c_status,
            self.a_status,
            self.n_status,
            self.s_status,
            self.l_status,
            self.i_status,
            self.m_status,
            self.market_spy_50gt200,
            "" if not math.isfinite(self.mm_ratio) else f"{self.mm_ratio:.4f}",
            self.c_eps_yoy,
            self.a_eps_cagr,
            self.a_roe,
            self.s_float,
            self.i_sponsor,
            self.one_liner,
        ]

CLOSED_HEADER = [
    "SYMBOL", "SIDE", "DATE_OPENED", "ENTRY_PRICE", "STOP_PRICE", "TARGET_PRICE",
    "DATE_CLOSED", "EXIT_PRICE", "EXIT_TYPE", "DAYS_HELD", "PNL_PCT", "PNL_DOLLARS",
    "TRIGGER_DATE", "TRIGGER_CLOSE", "PIVOT", "PCT_BELOW_52W_HIGH", "VOL_RATIO",
    "RS_PERCENTILE", "C_STATUS", "A_STATUS", "N_STATUS", "S_STATUS", "L_STATUS",
    "I_STATUS", "M_STATUS", "MARKET_SPY_50GT200", "MM_RATIO", "C_EPS_YOY",
    "A_EPS_CAGR", "A_ROE", "S_FLOAT", "I_SPONSOR", "ONE_LINER",
]

OPEN_HEADER = [
    "SYMBOL", "DATE_OPENED", "ENTRY_PRICE", "STOP_PRICE", "TARGET_PRICE",
    "TRIGGER_DATE", "PIVOT", "RS_PERCENTILE", "VOL_RATIO", "C_STATUS", "A_STATUS",
    "N_STATUS", "S_STATUS", "L_STATUS", "I_STATUS", "M_STATUS", "ONE_LINER",
]


def load_ohlcv_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    if "Date" not in df.columns:
        raise ValueError(f"No Date column in {path}")
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date", ignore_index=True)
    lower = {str(x).lower(): x for x in df.columns}
    for c in ("Open", "High", "Low", "Close", "Volume"):
        if c not in df.columns:
            src = lower.get(c.lower())
            if src is None and c == "Volume":
                df["Volume"] = 0.0
            elif src is not None:
                df[c] = df[src]
            else:
                raise ValueError(f"Missing {c} in {path}")
    df = df.set_index("Date")
    out = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    for c in out.columns:
        out[c] = out[c].astype(float)
    return out


def parse_symbols(s: str) -> list[str]:
    return [x.strip().upper() for x in (s or "").replace(";", ",").split(",") if x.strip()]


def list_data_dir_symbols(data_dir: Path) -> list[str]:
    if _list_csv_symbols is not None:
        return list(_list_csv_symbols(data_dir, include_spy=False))
    if not data_dir.is_dir():
        return []
    return sorted(
        p.stem.upper()
        for p in data_dir.glob("*.csv")
        if p.is_file() and p.stem.upper() != "SPY"
    )


def resolve_run_symbols(symbols_arg: str | None, data_dir: Path) -> list[str]:
    parsed = parse_symbols(symbols_arg or "")
    if parsed:
        return parsed
    return list_data_dir_symbols(data_dir)


def _ann_ror(pnl_pct: float, days_held: int) -> float:
    if days_held <= 0:
        return 0.0
    r = 1.0 + pnl_pct / 100.0
    if r <= 0:
        return -100.0
    return (r ** (DAYS_PER_YEAR / days_held) - 1.0) * 100.0


def precompute_rs_percentiles(
    data_dir: Path,
    symbols: list[str],
    lookback: int = 252,
) -> dict[str, dict[str, float]]:
    """{SYM: {YYYYMMDD: percentile_0_100}} among run symbols with valid returns."""
    rets: dict[str, pd.Series] = {}
    for sym in symbols:
        path = data_dir / f"{sym}.csv"
        if not path.exists():
            continue
        try:
            df = load_ohlcv_csv(path)
        except Exception:
            continue
        if len(df) < lookback + 5:
            continue
        s = df["Close"]
        r = s / s.shift(lookback) - 1.0
        r = r.dropna()
        if r.empty:
            continue
        r.index = pd.Index([_iso(d) for d in r.index])
        rets[sym] = r
    if not rets:
        return {}
    df = pd.DataFrame({sym: ser for sym, ser in rets.items()})
    ranks = df.rank(axis=1, pct=True, method="average") * 100.0
    out: dict[str, dict[str, float]] = {}
    for sym in ranks.columns:
        col = ranks[sym].dropna()
        out[sym] = {str(idx): float(v) for idx, v in col.items()}
    return out


def rs_lookup(rs_map: dict[str, dict[str, float]], symbol: str, iso: str) -> float | None:
    m = rs_map.get(symbol.upper())
    if not m:
        return None
    if iso in m:
        return float(m[iso])
    keys = [k for k in m if k <= iso]
    if not keys:
        return None
    return float(m[max(keys)])


def load_spy_50gt200(data_dir: Path) -> dict[str, int]:
    """YYYYMMDD -> 1 if SMA50 > SMA200 on that bar."""
    path = data_dir / "SPY.csv"
    if not path.exists():
        return {}
    df = load_ohlcv_csv(path)
    c = df["Close"]
    sma50 = c.rolling(50, min_periods=50).mean()
    sma200 = c.rolling(200, min_periods=200).mean()
    out: dict[str, int] = {}
    for dt, a, b in zip(df.index, sma50, sma200):
        if not (np.isfinite(a) and np.isfinite(b)):
            continue
        out[_iso(dt)] = 1 if float(a) > float(b) else 0
    return out


def _prior_ymd(iso: str, spy_map: dict[str, int]) -> str | None:
    keys = [k for k in spy_map if k < iso]
    return max(keys) if keys else None


def _in_entry_window(iso_dash: str, cfg: CanslimConfig) -> bool:
    d = iso_dash.replace("-", "")[:8]
    if cfg.entry_start_date:
        s = cfg.entry_start_date.replace("-", "")[:8]
        if d < s:
            return False
    if cfg.entry_end_date:
        e = cfg.entry_end_date.replace("-", "")[:8]
        if d > e:
            return False
    return True


def backtest_symbol(
    symbol: str,
    df: pd.DataFrame,
    cfg: CanslimConfig,
    rs_map: dict[str, dict[str, float]],
    spy_50gt200: dict[str, int],
    mm_ratio_by_ymd: Optional[dict[str, float]],
    dna: Optional[dict[str, str]] = None,
    fund: Any = None,
) -> tuple[list[ClosedRow], Optional[dict[str, Any]], Optional[dict[str, Any]], int]:
    o = df["Open"].to_numpy(dtype=float)
    h = df["High"].to_numpy(dtype=float)
    l = df["Low"].to_numpy(dtype=float)
    c = df["Close"].to_numpy(dtype=float)
    v = df["Volume"].to_numpy(dtype=float)
    dates = list(df.index)
    n = len(df)
    lb = max(int(cfg.pivot_lookback), 1)
    vol_lb = max(int(cfg.vol_sma_bars), 1)
    warm = max(_WEEK52, lb, vol_lb, cfg.rs_lookback) + 2
    closed: list[ClosedRow] = []
    open_row: Optional[dict[str, Any]] = None
    watch: Optional[dict[str, Any]] = None
    n_signals = 0
    pos = None  # dict
    cooldown_until = -1
    dna = dna or {
        "c_eps_yoy": "",
        "a_eps_cagr": "",
        "a_roe": "",
        "s_float": "STUB",
        "i_sponsor": "UNKNOWN",
        "c_status": "STUB",
        "a_status": "STUB",
        "i_status": "STUB",
    }
    for i in range(warm, n - 1):  # need i+1 for fill
        if pos is not None:
            # manage from bar i (fill was prior open)
            entry = float(pos["entry"])
            stop = float(pos["stop"])
            target = float(pos["target"])
            exit_px = None
            exit_type = None
            # gap stop / target / trail / time (BRT/PVH: open through stop → GAP_DOWN)
            if l[i] <= stop:
                if o[i] <= stop:
                    exit_px = float(o[i])
                    exit_type = "GAP_DOWN"
                else:
                    exit_px = float(stop)
                    exit_type = "STOP_LOSS"
            elif h[i] >= target:
                exit_px = target
                exit_type = "TARGET"
            elif cfg.trail_sma > 0 and i >= cfg.trail_sma:
                sma = float(np.mean(c[i - cfg.trail_sma + 1 : i + 1]))
                if c[i] < sma:
                    exit_px = float(c[i])
                    exit_type = "TRAIL_SMA"
            if exit_px is None and (i - int(pos["fill_i"])) >= int(cfg.time_stop_bars):
                exit_px = float(c[i])
                exit_type = "TIME"
            if exit_px is not None:
                pnl_pct = (exit_px / entry - 1.0) * 100.0
                days = max(1, (dates[i].date() - dates[int(pos["fill_i"])].date()).days)
                closed.append(
                    ClosedRow(
                        symbol=symbol,
                        side="LONG",
                        date_opened=_ymd_dash(dates[int(pos["fill_i"])]),
                        entry_price=entry,
                        stop_price=stop,
                        target_price=target,
                        date_closed=_ymd_dash(dates[i]),
                        exit_price=float(exit_px),
                        exit_type=str(exit_type),
                        days_held=int(days),
                        pnl_pct=pnl_pct,
                        pnl_dollars=cfg.cash * (exit_px / entry - 1.0),
                        trigger_date=pos["trigger_date"],
                        trigger_close=float(pos["trigger_close"]),
                        pivot=float(pos["pivot"]),
                        pct_below_52w=float(pos["pct_below_52w"]),
                        vol_ratio=float(pos["vol_ratio"]),
                        rs_percentile=float(pos["rs"]),
                        c_status=str(pos.get("c_status", dna["c_status"])),
                        a_status=str(pos.get("a_status", dna["a_status"])),
                        n_status="PASS",
                        s_status="PASS",
                        l_status="PASS",
                        i_status=str(pos.get("i_status", dna["i_status"])),
                        m_status=str(pos["m_status"]),
                        market_spy_50gt200=str(pos["spy_flag"]),
                        mm_ratio=float(pos["mm_ratio"]),
                        c_eps_yoy=str(pos.get("c_eps_yoy", dna["c_eps_yoy"])),
                        a_eps_cagr=str(pos.get("a_eps_cagr", dna["a_eps_cagr"])),
                        a_roe=str(pos.get("a_roe", dna["a_roe"])),
                        s_float=str(pos.get("s_float", dna["s_float"])),
                        i_sponsor=str(pos.get("i_sponsor", dna["i_sponsor"])),
                        one_liner=(
                            f"CS pivot BO rs={pos['rs']:.0f} vol={pos['vol_ratio']:.2f}x "
                            f"-> {exit_type} {pnl_pct:+.1f}%"
                        ),
                    )
                )
                cooldown_until = i + int(cfg.cooldown_bars)
                pos = None
            continue

        if i < cooldown_until:
            continue

        iso = _iso(dates[i])
        iso_dash = _ymd_dash(dates[i])
        if not _in_entry_window(iso_dash, cfg):
            continue
        if c[i] < cfg.min_price or c[i] <= 0:
            continue

        # N: 52w proximity
        w0 = max(0, i - _WEEK52 + 1)
        high_52 = float(np.max(h[w0 : i + 1]))
        if high_52 <= 0:
            continue
        pct_below = (high_52 - c[i]) / high_52
        n_ok = pct_below <= float(cfg.max_pct_below_52w_high)
        # N: pivot break — close > max high of prior lookback (exclude today)
        pivot = float(np.max(h[i - lb : i]))
        pivot_break = c[i] > pivot
        n_pass = n_ok and pivot_break

        # S: volume
        vol_sma = float(np.mean(v[i - vol_lb : i])) if i >= vol_lb else float("nan")
        vol_ratio = (v[i] / vol_sma) if vol_sma and vol_sma > 0 else float("nan")
        s_pass = math.isfinite(vol_ratio) and vol_ratio >= float(cfg.vol_breakout_mult)

        # L: RS
        rs = rs_lookup(rs_map, symbol, iso)
        l_pass = rs is not None and float(rs) >= float(cfg.rs_min)

        # M: SPY lag-1
        m_status = "OFF"
        spy_flag = ""
        if cfg.market_gate:
            prior = _prior_ymd(iso, spy_50gt200)
            if prior is None:
                m_status = "FAIL"
            else:
                spy_flag = str(spy_50gt200.get(prior, 0))
                m_status = "PASS" if spy_50gt200.get(prior, 0) == 1 else "FAIL"
        mm_ratio = float("nan")
        if cfg.mm_gate and mm_ratio_by_ymd is not None:
            prior_mm = _prior_ymd(iso, {k: 1 for k in mm_ratio_by_ymd})
            if prior_mm is None:
                m_status = "FAIL"
            else:
                mm_ratio = float(mm_ratio_by_ymd.get(prior_mm, float("nan")))
                if not (math.isfinite(mm_ratio) and mm_ratio >= float(cfg.mm_min_ratio)):
                    m_status = "FAIL"
                elif m_status != "FAIL":
                    m_status = "PASS"

        m_pass = (m_status in ("PASS", "OFF"))

        # Watch near-miss: N almost, others ok
        if n_ok and (not pivot_break) and s_pass and l_pass and m_pass:
            watch = {
                "symbol": symbol,
                "asof": iso_dash,
                "pivot": pivot,
                "close": float(c[i]),
                "rs": float(rs) if rs is not None else float("nan"),
                "vol_ratio": vol_ratio,
                "note": "near pivot",
            }

        if not (n_pass and s_pass and l_pass and m_pass):
            continue

        # Optional C/A/I hard gates (default OFF). Soft DNA still fills when cache has data.
        if cfg.require_c:
            yoy = getattr(fund, "c_eps_yoy", None) if fund is not None else None
            if yoy is None or float(yoy) < float(cfg.c_eps_yoy_min):
                continue
        if cfg.require_a:
            cagr = getattr(fund, "a_eps_cagr", None) if fund is not None else None
            roe = getattr(fund, "roe", None) if fund is not None else None
            cagr_ok = cagr is not None and float(cagr) >= float(cfg.a_eps_cagr_min)
            roe_ok = roe is not None and float(roe) >= float(cfg.a_roe_min)
            if not (cagr_ok or roe_ok):
                continue
        if cfg.require_i:
            inst = getattr(fund, "inst_pct", None) if fund is not None else None
            if inst is None or float(inst) < float(cfg.i_inst_pct_min):
                continue

        n_signals += 1
        fill_i = i + 1
        entry = float(o[fill_i])
        if entry <= 0:
            continue
        stop = entry * float(cfg.stop_pct)
        target = entry * float(cfg.target_pct)
        pos = {
            "fill_i": fill_i,
            "entry": entry,
            "stop": stop,
            "target": target,
            "trigger_date": iso_dash,
            "trigger_close": float(c[i]),
            "pivot": pivot,
            "pct_below_52w": pct_below,
            "vol_ratio": vol_ratio,
            "rs": float(rs) if rs is not None else float("nan"),
            "m_status": m_status,
            "spy_flag": spy_flag,
            "mm_ratio": mm_ratio,
            "c_status": dna["c_status"],
            "a_status": dna["a_status"],
            "i_status": dna["i_status"],
            "c_eps_yoy": dna["c_eps_yoy"],
            "a_eps_cagr": dna["a_eps_cagr"],
            "a_roe": dna["a_roe"],
            "s_float": dna["s_float"],
            "i_sponsor": dna["i_sponsor"],
        }
        # Position open: management starts on subsequent bars.

    if pos is not None:
        open_row = {
            "symbol": symbol,
            "date_opened": _ymd_dash(dates[int(pos["fill_i"])]),
            "entry_price": float(pos["entry"]),
            "stop_price": float(pos["stop"]),
            "target_price": float(pos["target"]),
            "trigger_date": pos["trigger_date"],
            "pivot": float(pos["pivot"]),
            "rs": float(pos["rs"]),
            "vol_ratio": float(pos["vol_ratio"]),
            "c_status": str(pos.get("c_status", dna["c_status"])),
            "a_status": str(pos.get("a_status", dna["a_status"])),
            "i_status": str(pos.get("i_status", dna["i_status"])),
            "one_liner": f"CS open pivot={pos['pivot']:.2f} rs={pos['rs']:.0f}",
        }

    return closed, open_row, watch, n_signals


def run_backtest(
    symbols: list[str],
    data_dir: Path,
    cfg: CanslimConfig,
    output_dir: Optional[Path] = None,
) -> tuple[list[ClosedRow], list[dict], list[dict], dict[str, Any]]:
    print(f"[CS] Precomputing RS percentiles ({len(symbols)} symbols, lb={cfg.rs_lookback})...", flush=True)
    rs_map = precompute_rs_percentiles(data_dir, symbols, lookback=int(cfg.rs_lookback))
    print(f"[CS] RS map ready: {len(rs_map)} symbols", flush=True)
    spy_map = load_spy_50gt200(data_dir) if cfg.market_gate else {}
    if cfg.market_gate and not spy_map:
        print("[CS] WARNING: SPY.csv missing/short — market_gate will FAIL all bars", flush=True)

    mm_lookup: Optional[dict[str, float]] = None
    if cfg.mm_gate:
        try:
            from rocket_stockbee_mm import build_or_load_mm_series, MMBuildConfig
        except ImportError:
            from stock_analysis.rocket_stockbee_mm import (  # type: ignore
                build_or_load_mm_series,
                MMBuildConfig,
            )
        cache = Path(output_dir or "drive") / "CS_MM_Series_latest.csv"
        _frame, mm_lookup, path = build_or_load_mm_series(
            data_dir, cfg=MMBuildConfig(), cache_path=cache, force_rebuild=False
        )
        print(f"[CS] MM series: {path} days={len(mm_lookup)}", flush=True)

    fund_by_sym: dict[str, Any] = {}
    dna_by_sym: dict[str, dict[str, str]] = {}
    if bool(cfg.fundamentals_fill) and _fund_ensure_symbols is not None and canslim_dna_from_fundamentals is not None:
        skip_net = _fund_yf_disabled() if _fund_yf_disabled is not None else False
        print(
            f"[CS] Fundamentals soft-fill: {len(symbols)} symbols "
            f"(NO_YFINANCE={skip_net} force={cfg.force_refresh_fundamentals})",
            flush=True,
        )
        try:
            fund_by_sym = _fund_ensure_symbols(
                symbols,
                db_path=cfg.fundamentals_db or None,
                force_refresh=bool(cfg.force_refresh_fundamentals),
            )
            for sym, bundle in fund_by_sym.items():
                dna_by_sym[sym] = canslim_dna_from_fundamentals(bundle)
        except Exception as e:
            print(f"[CS] Fundamentals fill skipped: {e}", flush=True)
    elif bool(cfg.fundamentals_fill):
        print("[CS] Fundamentals module missing — C/A/I DNA stays STUB/UNKNOWN", flush=True)

    closed: list[ClosedRow] = []
    opens: list[dict] = []
    watches: list[dict] = []
    skip: list[str] = []
    n_signals = 0
    for sym in symbols:
        path = data_dir / f"{sym}.csv"
        if not path.exists():
            skip.append(f"{sym}: missing")
            continue
        try:
            df = load_ohlcv_csv(path)
        except Exception as e:
            skip.append(f"{sym}: {e}")
            continue
        if len(df) < _WEEK52 + cfg.pivot_lookback + 5:
            skip.append(f"{sym}: short history")
            continue
        rows, op, wa, sigs = backtest_symbol(
            sym,
            df,
            cfg,
            rs_map,
            spy_map,
            mm_lookup,
            dna=dna_by_sym.get(sym),
            fund=fund_by_sym.get(sym),
        )
        closed.extend(rows)
        n_signals += sigs
        if op:
            opens.append(op)
        if wa:
            watches.append(wa)

    closed.sort(key=lambda r: (r.date_opened, r.symbol))
    wins = sum(1 for r in closed if r.pnl_pct > 0)
    meta: dict[str, Any] = {
        "n_closed": len(closed),
        "n_open": len(opens),
        "n_signals": n_signals,
        "n_watch": len(watches),
        "symbols_skipped": skip,
        "total_pnl": sum(r.pnl_dollars for r in closed),
        "win_rate": (100.0 * wins / len(closed)) if closed else 0.0,
        "avg_pnl_pct": (sum(r.pnl_pct for r in closed) / len(closed)) if closed else 0.0,
    }
    return closed, opens, watches, meta


def write_outputs(
    output_dir: Path,
    stamp: str,
    cfg: CanslimConfig,
    closed: list[ClosedRow],
    opens: list[dict],
    watches: list[dict],
    meta: dict[str, Any],
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    closed_p = output_dir / f"{FILE_PREFIX}_Closed_{stamp}.csv"
    with closed_p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CLOSED_HEADER)
        for r in closed:
            w.writerow(r.to_csv_row())
    paths["closed"] = closed_p

    open_p = output_dir / f"{FILE_PREFIX}_Open_{stamp}.csv"
    with open_p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(OPEN_HEADER)
        for r in opens:
            w.writerow([
                r["symbol"], r["date_opened"], f"{r['entry_price']:.4f}",
                f"{r['stop_price']:.4f}", f"{r['target_price']:.4f}",
                r["trigger_date"], f"{r['pivot']:.4f}", f"{r['rs']:.2f}",
                f"{r['vol_ratio']:.4f}",
                r.get("c_status", "STUB"), r.get("a_status", "STUB"),
                "PASS", "PASS", "PASS",
                r.get("i_status", "STUB"), "PASS", r.get("one_liner", ""),
            ])
    paths["open"] = open_p

    # Summary per symbol
    by_sym: dict[str, list[ClosedRow]] = {}
    for r in closed:
        by_sym.setdefault(r.symbol, []).append(r)
    sum_p = output_dir / f"{FILE_PREFIX}_Summary_{stamp}.csv"
    with sum_p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "SYMBOL", "TRADES", "WINS", "LOSSES", "PCT_WINS", "TOTAL_PNL",
            "SHEET_PNL", "AVG_PNL_PCT", "AVG_TRADES_PER_YEAR", "AVG_DAYS_HELD",
        ])
        for sym in sorted(by_sym):
            rows = by_sym[sym]
            wins = sum(1 for r in rows if r.pnl_pct > 0)
            losses = len(rows) - wins
            pnl = sum(r.pnl_dollars for r in rows)
            avg_pct = sum(r.pnl_pct for r in rows) / len(rows)
            avg_days = sum(int(r.days_held or 0) for r in rows) / len(rows) if rows else 0.0
            # crude years from first→last
            d0 = min(r.date_opened for r in rows).replace("-", "")
            d1 = max(r.date_closed for r in rows).replace("-", "")
            try:
                y0 = datetime.strptime(d0, "%Y%m%d")
                y1 = datetime.strptime(d1, "%Y%m%d")
                years = max((y1 - y0).days / DAYS_PER_YEAR, 1.0 / 12.0)
            except Exception:
                years = 1.0
            w.writerow([
                sym, len(rows), wins, losses,
                f"{100.0 * wins / len(rows):.2f}",
                f"{pnl:.2f}", f"{pnl:.2f}", f"{avg_pct:.4f}",
                f"{len(rows) / years:.2f}",
                f"{avg_days:.1f}",
            ])
    paths["summary"] = sum_p

    watch_p = output_dir / f"{FILE_PREFIX}_Watchlist_{stamp}.csv"
    with watch_p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["SYMBOL", "ASOF", "PIVOT", "CLOSE", "RS_PERCENTILE", "VOL_RATIO", "NOTE"])
        for r in watches:
            w.writerow([
                r["symbol"], r["asof"], f"{r['pivot']:.4f}", f"{r['close']:.4f}",
                "" if not math.isfinite(r["rs"]) else f"{r['rs']:.2f}",
                "" if not math.isfinite(r["vol_ratio"]) else f"{r['vol_ratio']:.4f}",
                r.get("note", ""),
            ])
    paths["watchlist"] = watch_p

    report_p = output_dir / f"{FILE_PREFIX}_Report_{stamp}.txt"
    report_p.write_text(
        "\n".join([
            f"CAN SLIM (CS) price-legs report stamp={stamp}",
            f"closed={meta['n_closed']} open={meta['n_open']} signals={meta['n_signals']}",
            f"win_rate={meta['win_rate']:.1f}% avg_pnl_pct={meta['avg_pnl_pct']:.2f}",
            f"total_pnl={meta['total_pnl']:.2f}",
            f"rs_min={cfg.rs_min} pivot_lb={cfg.pivot_lookback} vol_mult={cfg.vol_breakout_mult}",
            f"market_gate={cfg.market_gate} mm_gate={cfg.mm_gate}",
            (
                "C/A/I=soft-fill from yfinance DuckDB cache when present; "
                f"gates require_c/a/i={cfg.require_c}/{cfg.require_a}/{cfg.require_i}"
            ),
            "",
        ]),
        encoding="utf-8",
    )
    paths["report"] = report_p

    # Skinny audit (research — not full BRT wide schema)
    audit_p = output_dir / f"{FILE_PREFIX}_Audit_Report_{stamp}.csv"
    with audit_p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["key", "value"])
        for k, v in [
            ("prefix", FILE_PREFIX),
            ("stamp", stamp),
            ("system", "oneil_canslim"),
            ("cs_mode", "standalone_v0"),
            ("n_closed", meta["n_closed"]),
            ("n_open", meta["n_open"]),
            ("n_signals", meta["n_signals"]),
            ("win_rate", f"{meta['win_rate']:.2f}"),
            ("total_pnl", f"{meta['total_pnl']:.2f}"),
            ("rs_min", cfg.rs_min),
            ("pivot_lookback", cfg.pivot_lookback),
            ("vol_breakout_mult", cfg.vol_breakout_mult),
            ("max_pct_below_52w_high", cfg.max_pct_below_52w_high),
            ("market_gate", cfg.market_gate),
            ("mm_gate", cfg.mm_gate),
            ("stop_pct", cfg.stop_pct),
            ("target_pct", cfg.target_pct),
            ("C_STATUS", "SOFT_WHEN_CACHED"),
            ("A_STATUS", "SOFT_WHEN_CACHED"),
            ("I_STATUS", "SOFT_WHEN_CACHED"),
            ("fundamentals_fill", cfg.fundamentals_fill),
            ("require_c", cfg.require_c),
            ("require_a", cfg.require_a),
            ("require_i", cfg.require_i),
            ("audit_schema", "skinny_kv_not_brt_wide"),
        ]:
            w.writerow([k, v])
    paths["audit"] = audit_p

    # Equity: exit-date cumulative
    eq_p = output_dir / f"{FILE_PREFIX}_EquityCurve_{stamp}.csv"
    meta_eq = output_dir / f"{FILE_PREFIX}_EquityMeta_{stamp}.csv"
    equity = float(cfg.initial_capital)
    rows_eq: list[tuple[str, float]] = []
    for r in sorted(closed, key=lambda x: x.date_closed):
        equity += r.pnl_dollars
        rows_eq.append((r.date_closed, equity))
    with eq_p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["DATE", "EQUITY"])
        for d, e in rows_eq:
            w.writerow([d, f"{e:.2f}"])
    peak = float(cfg.initial_capital)
    max_dd = 0.0
    for _, e in rows_eq:
        peak = max(peak, e)
        if peak > 0:
            max_dd = min(max_dd, (e - peak) / peak)
    with meta_eq.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["key", "value"])
        w.writerow(["initial_capital", cfg.initial_capital])
        w.writerow(["final_equity", equity])
        w.writerow(["max_dd_frac", f"{max_dd:.6f}"])
        w.writerow(["n_closed", len(closed)])
    paths["equity_curve"] = eq_p
    paths["equity_meta"] = meta_eq

    # LatestRun mirrors
    for label, src in [
        ("Closed", closed_p),
        ("Open", open_p),
        ("Summary", sum_p),
        ("Watchlist", watch_p),
        ("Audit_Report", audit_p),
        ("EquityCurve", eq_p),
    ]:
        dst = output_dir / f"{FILE_PREFIX}_LatestRun_{label}.csv"
        shutil.copy2(src, dst)
        paths[f"latest_{label}"] = dst

    (output_dir / f"{FILE_PREFIX}_last_run_ts.txt").write_text(stamp + "\n", encoding="utf-8")
    return paths


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="O'Neil CAN SLIM price-legs (CS_*) — C/A/I soft-fill")
    p.add_argument("data_dir", nargs="?", default="data/newdata/data")
    p.add_argument("-o", "--output-dir", default="drive")
    p.add_argument("-s", "--symbols", default="")
    p.add_argument("--stamp", default="")
    p.add_argument("--cash", type=float, default=DEFAULT_CASH)
    p.add_argument("--rs-min", type=float, default=80.0)
    p.add_argument("--rs-lookback", type=int, default=252)
    p.add_argument("--pivot-lookback", type=int, default=55)
    p.add_argument("--vol-breakout-mult", type=float, default=1.40)
    p.add_argument("--max-pct-below-52w-high", type=float, default=0.25)
    p.add_argument("--stop-pct", type=float, default=0.92)
    p.add_argument("--target-pct", type=float, default=1.20)
    p.add_argument("--trail-sma", type=int, default=0)
    p.add_argument("--time-stop-bars", type=int, default=40)
    p.add_argument("--market-gate", type=_as_bool, default=True)
    p.add_argument("--mm-gate", type=_as_bool, default=False)
    p.add_argument("--mm-min-ratio", type=float, default=2.0)
    p.add_argument("--min-price", type=float, default=5.0)
    p.add_argument("--require-c", type=_as_bool, default=False, help="Gate on C_EPS_YOY when fundamentals present")
    p.add_argument("--require-a", type=_as_bool, default=False, help="Gate on A_EPS_CAGR/ROE when present")
    p.add_argument("--require-i", type=_as_bool, default=False, help="Gate on institutional %% when present")
    p.add_argument("--fundamentals-fill", type=_as_bool, default=True)
    p.add_argument("--fundamentals-db", default="", help="DuckDB path (else FUNDAMENTALS_DB / drive default)")
    p.add_argument("--force-refresh-fundamentals", action="store_true")
    p.add_argument("--initial-capital", type=float, default=DEFAULT_INITIAL_CAPITAL)
    p.add_argument("--aggressive-max-multiple", type=float, default=DEFAULT_AGGRESSIVE_MAX_MULTIPLE)
    p.add_argument("--margin-utilization", type=float, default=DEFAULT_MARGIN_UTILIZATION)
    p.add_argument("--max-positions", type=int, default=0)
    p.add_argument("--aggressive", action="store_true")
    p.add_argument("--host-dollar-scale", type=_as_bool, default=True)
    p.add_argument("--entry-start-date", default="")
    p.add_argument("--entry-end-date", default="")
    return p


def cfg_from_args(ns: argparse.Namespace) -> CanslimConfig:
    return CanslimConfig(
        max_pct_below_52w_high=float(ns.max_pct_below_52w_high),
        pivot_lookback=int(ns.pivot_lookback),
        min_price=float(ns.min_price),
        vol_breakout_mult=float(ns.vol_breakout_mult),
        rs_min=float(ns.rs_min),
        rs_lookback=int(ns.rs_lookback),
        market_gate=_as_bool(ns.market_gate),
        mm_gate=_as_bool(ns.mm_gate),
        mm_min_ratio=float(ns.mm_min_ratio),
        require_c=_as_bool(ns.require_c),
        require_a=_as_bool(ns.require_a),
        require_i=_as_bool(ns.require_i),
        stop_pct=float(ns.stop_pct),
        target_pct=float(ns.target_pct),
        trail_sma=int(ns.trail_sma),
        time_stop_bars=int(ns.time_stop_bars),
        cash=float(ns.cash),
        initial_capital=float(ns.initial_capital),
        aggressive_max_multiple=float(ns.aggressive_max_multiple),
        margin_utilization=float(ns.margin_utilization),
        max_positions=int(ns.max_positions),
        aggressive=bool(ns.aggressive),
        host_dollar_scale=_as_bool(ns.host_dollar_scale),
        entry_start_date=str(ns.entry_start_date or ""),
        entry_end_date=str(ns.entry_end_date or ""),
        fundamentals_fill=_as_bool(ns.fundamentals_fill),
        fundamentals_db=str(ns.fundamentals_db or ""),
        force_refresh_fundamentals=bool(ns.force_refresh_fundamentals),
    )

def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    cfg = cfg_from_args(args)
    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    symbols = resolve_run_symbols(args.symbols, data_dir)
    stamp = (args.stamp or "").strip() or datetime.now().strftime("%y%m%d%H%M%S")
    if not symbols:
        print(f"[CS] ERROR: no symbols under {data_dir}", flush=True)
        return 1
    mode = "whitelist" if parse_symbols(args.symbols) else "full CSV"
    print(
        f"[CS] CAN SLIM price-legs: {len(symbols)} symbols ({mode}) -> {output_dir} stamp={stamp} "
        f"rs>={cfg.rs_min} pivot_lb={cfg.pivot_lookback} vol>={cfg.vol_breakout_mult} "
        f"mkt={cfg.market_gate} mm={cfg.mm_gate} | C/A/I soft-fill "
        f"(gates={cfg.require_c}/{cfg.require_a}/{cfg.require_i})",
        flush=True,
    )
    closed, opens, watches, meta = run_backtest(symbols, data_dir, cfg, output_dir=output_dir)

    if cfg.host_dollar_scale and closed:
        host_cfg = HostSizingConfig(
            brt_cash=float(cfg.cash),
            initial_capital=float(cfg.initial_capital),
            aggressive_max_multiple=float(cfg.aggressive_max_multiple),
            margin_utilization=float(cfg.margin_utilization),
            max_positions=int(cfg.max_positions),
            aggressive=bool(cfg.aggressive),
        )
        try:
            adj, scale, max_pos = apply_host_dollar_scale(closed, opens, host_cfg)
            cfg.cash = float(adj)
            meta["host_max_positions"] = max_pos
            meta["host_pnl_scale"] = scale
            meta["total_pnl"] = sum(r.pnl_dollars for r in closed)
            meta["host_audit_brt_cash"] = audit_display_brt_cash(max_pos)
            print(
                f"[CS] Host dollar-scale x{scale:.6g}; brt_cash->{adj:,.0f} max_pos={max_pos}",
                flush=True,
            )
        except Exception as e:
            print(f"[CS] Host dollar-scale skipped: {e}", flush=True)
        if cfg.aggressive:
            print(
                "[CS] Note: aggressive flag set; EquityCurve is exit-date simple "
                "(full BRT overlay needs tickers map — deferred)",
                flush=True,
            )

    paths = write_outputs(output_dir, stamp, cfg, closed, opens, watches, meta)
    print(
        f"[CS] Done. closed={meta['n_closed']} open={meta['n_open']} signals={meta['n_signals']} "
        f"PnL=${meta['total_pnl']:.2f} WR={meta['win_rate']:.1f}%",
        flush=True,
    )
    for s in meta["symbols_skipped"][:12]:
        print(f"[CS] SKIP {s}", flush=True)
    print(f"[CS] Closed: {paths['closed']}", flush=True)
    print(f"[CS] Summary: {paths['summary']}", flush=True)
    print(f"[CS] Audit: {paths['audit']} (skinny KV - not BRT-wide)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())