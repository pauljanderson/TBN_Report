#!/usr/bin/env python3
"""
Oliver Kell — Price Action Cycle (PAC) / Wedge Pop — standalone research engine.

Prefix: KELL_
Docs: drive/paul_experiments/tbn_new_systems/kell_pac/RESEARCH.md

Standalone by design (does NOT require rocket_tbn edits). Wedge Pop v0 only;
EMA Crossback / Base n' Break are DNA stubs for later.

Entry (signal bar T):
  - Reversal Extension context in lookback: Close <= EMA20 * (1 - rev_ext_pct)
  - EMA tightness: |EMA10 - EMA20| / Close <= tight_pct
  - Close > EMA10 and Close > EMA20; prior close <= max(EMA10, EMA20)
  - Optional: Close > SMA50; volume >= vol_mult * SMA20(vol)
  - Exhaustion ban: skip if Close > EMA20 * (1 + exh_ban_pct) when exh_ban_pct > 0
  - Price >= min_price

Fill: next open. Stop: min Low of prior coil_bars.
Exit: Close < EMA(trail_ema) → exit next open (or same-close research path uses close).
"""
from __future__ import annotations

import argparse
import csv
import math
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
        resolve_max_positions,
    )
except ImportError:
    try:
        from stock_analysis.tbn_host_sizing import (  # type: ignore
            DEFAULT_AGGRESSIVE_MAX_MULTIPLE,
            DEFAULT_INITIAL_CAPITAL,
            DEFAULT_MARGIN_UTILIZATION,
            HostSizingConfig,
            apply_host_dollar_scale,
            resolve_max_positions,
        )
    except ImportError:
        DEFAULT_INITIAL_CAPITAL = 500_000.0
        DEFAULT_AGGRESSIVE_MAX_MULTIPLE = 2.0
        DEFAULT_MARGIN_UTILIZATION = 0.6
        HostSizingConfig = None  # type: ignore
        apply_host_dollar_scale = None  # type: ignore
        resolve_max_positions = None  # type: ignore

try:
    from ohlcv_store import list_csv_symbols as _list_csv_symbols
except ImportError:
    try:
        from stock_analysis.ohlcv_store import list_csv_symbols as _list_csv_symbols  # type: ignore
    except ImportError:
        _list_csv_symbols = None  # type: ignore

FILE_PREFIX = "KELL"
DEFAULT_CASH = 47_500.0


@dataclass
class KellConfig:
    ema_fast: int = 10
    ema_slow: int = 20
    sma_struct: int = 50
    rev_lookback: int = 40
    rev_ext_pct: float = 0.08
    tight_pct: float = 0.025
    coil_bars: int = 8
    vol_mult: float = 0.0  # 0 = off
    require_sma50: bool = True
    min_price: float = 10.0
    trail_ema: int = 20
    exh_ban_pct: float = 0.12
    cash: float = DEFAULT_CASH
    initial_capital: float = DEFAULT_INITIAL_CAPITAL
    aggressive_max_multiple: float = DEFAULT_AGGRESSIVE_MAX_MULTIPLE
    margin_utilization: float = DEFAULT_MARGIN_UTILIZATION
    max_positions: int = 0
    aggressive: bool = False
    host_dollar_scale: bool = True
    entry_start_date: str = ""
    entry_end_date: str = ""
    cooldown_bars: int = 5


@dataclass
class KellClosedRow:
    symbol: str
    side: str
    date_opened: str
    entry_price: float
    stop_price: float
    date_closed: str
    exit_price: float
    exit_type: str
    days_held: int
    pnl_pct: float
    pnl_dollars: float
    setup: str
    phase: str
    ema10: float
    ema20: float
    sma50: float
    ema_gap_pct: float
    ext_below_ema20_pct: float
    ext_above_ema20_pct: float
    vol_ratio: float
    coil_low: float
    coil_bars: int
    trail_ema: int
    prior_phase: str
    trigger_date: str
    trigger_close: float

    def to_csv_row(self) -> list[str]:
        def f(x: float, nd: int = 4) -> str:
            if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
                return ""
            return f"{x:.{nd}f}"

        return [
            self.symbol,
            self.side,
            self.date_opened,
            f(self.entry_price),
            f(self.stop_price),
            self.date_closed,
            f(self.exit_price),
            self.exit_type,
            str(self.days_held),
            f(self.pnl_pct, 6),
            f(self.pnl_dollars, 2),
            self.setup,
            self.phase,
            f(self.ema10),
            f(self.ema20),
            f(self.sma50),
            f(self.ema_gap_pct, 6),
            f(self.ext_below_ema20_pct, 6),
            f(self.ext_above_ema20_pct, 6),
            f(self.vol_ratio, 4),
            f(self.coil_low),
            str(self.coil_bars),
            str(self.trail_ema),
            self.prior_phase,
            self.trigger_date,
            f(self.trigger_close),
        ]


CLOSED_HEADER = [
    "SYMBOL",
    "SIDE",
    "DATE_OPENED",
    "ENTRY_PRICE",
    "STOP_PRICE",
    "DATE_CLOSED",
    "EXIT_PRICE",
    "EXIT_TYPE",
    "DAYS_HELD",
    "PNL_PCT",
    "PNL_DOLLARS",
    "SETUP",
    "PHASE",
    "EMA10",
    "EMA20",
    "SMA50",
    "EMA_GAP_PCT",
    "EXT_BELOW_EMA20_PCT",
    "EXT_ABOVE_EMA20_PCT",
    "VOL_RATIO",
    "COIL_LOW",
    "COIL_BARS",
    "TRAIL_EMA",
    "PRIOR_PHASE",
    "TRIGGER_DATE",
    "TRIGGER_CLOSE",
]


def _as_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "y", "on")


def load_ohlcv_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    if "Date" not in df.columns:
        raise ValueError(f"No Date column in {path}")
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date", ignore_index=True)
    for c in ("Open", "High", "Low", "Close", "Volume"):
        if c not in df.columns:
            lower = {str(x).lower(): x for x in df.columns}
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
        out[c] = pd.to_numeric(out[c], errors="coerce").astype(float)
    return out


def parse_symbols(s: str) -> list[str]:
    if not s or not str(s).strip():
        return []
    return [x.strip().upper() for x in str(s).split(",") if x.strip()]


def list_symbols(data_dir: Path) -> list[str]:
    if _list_csv_symbols is not None:
        return list(_list_csv_symbols(data_dir, include_spy=False))
    out: list[str] = []
    for p in sorted(Path(data_dir).glob("*.csv")):
        sym = p.stem.upper()
        if sym == "SPY":
            continue
        out.append(sym)
    return out


def resolve_run_symbols(symbols_arg: str | None, data_dir: Path) -> list[str]:
    named = parse_symbols(symbols_arg or "")
    return named if named else list_symbols(data_dir)


def _ema(series: np.ndarray, span: int) -> np.ndarray:
    return pd.Series(series).ewm(span=span, adjust=False).mean().to_numpy(dtype=float)


def _sma(series: np.ndarray, window: int) -> np.ndarray:
    return pd.Series(series).rolling(window, min_periods=window).mean().to_numpy(dtype=float)


def _ymd(ts: Any) -> str:
    if hasattr(ts, "strftime"):
        return ts.strftime("%Y-%m-%d")
    return str(ts)[:10]


def _in_entry_window(ymd: str, cfg: KellConfig) -> bool:
    if cfg.entry_start_date and ymd < cfg.entry_start_date[:10]:
        return False
    if cfg.entry_end_date and ymd > cfg.entry_end_date[:10]:
        return False
    return True


def backtest_symbol(sym: str, df: pd.DataFrame, cfg: KellConfig) -> tuple[list[KellClosedRow], list[dict[str, Any]]]:
    if len(df) < max(cfg.rev_lookback, cfg.sma_struct, cfg.trail_ema) + 5:
        return [], []

    o = df["Open"].to_numpy(dtype=float)
    h = df["High"].to_numpy(dtype=float)
    l = df["Low"].to_numpy(dtype=float)
    c = df["Close"].to_numpy(dtype=float)
    v = df["Volume"].to_numpy(dtype=float)
    dates = df.index
    n = len(c)

    ema10 = _ema(c, cfg.ema_fast)
    ema20 = _ema(c, cfg.ema_slow)
    sma50 = _sma(c, cfg.sma_struct)
    vol_sma = _sma(v, 20)
    trail = _ema(c, int(cfg.trail_ema))

    closed: list[KellClosedRow] = []
    watches: list[dict[str, Any]] = []
    i = max(cfg.rev_lookback, cfg.sma_struct, cfg.coil_bars, 25) + 1
    last_exit_i = -10_000

    while i < n - 1:
        if i - last_exit_i < cfg.cooldown_bars:
            i += 1
            continue
        ymd = _ymd(dates[i])
        if not _in_entry_window(ymd, cfg):
            i += 1
            continue
        if not (c[i] > 0 and ema10[i] > 0 and ema20[i] > 0):
            i += 1
            continue
        if c[i] < cfg.min_price:
            i += 1
            continue

        # Reversal Extension context
        lb0 = max(0, i - cfg.rev_lookback)
        ext_depths = []
        for j in range(lb0, i + 1):
            if ema20[j] > 0 and c[j] > 0:
                ext_depths.append(1.0 - (c[j] / ema20[j]))
        max_ext_below = max(ext_depths) if ext_depths else 0.0
        had_rev = max_ext_below >= cfg.rev_ext_pct

        gap = abs(ema10[i] - ema20[i]) / c[i]
        above_both = c[i] > ema10[i] and c[i] > ema20[i]
        prior_not_above = c[i - 1] <= max(ema10[i - 1], ema20[i - 1])
        tight = gap <= cfg.tight_pct
        sma_ok = (not cfg.require_sma50) or (not math.isnan(sma50[i]) and c[i] > sma50[i])
        vol_ratio = (v[i] / vol_sma[i]) if vol_sma[i] and vol_sma[i] > 0 else float("nan")
        vol_ok = cfg.vol_mult <= 0 or (not math.isnan(vol_ratio) and vol_ratio >= cfg.vol_mult)
        ext_above = (c[i] / ema20[i] - 1.0) if ema20[i] > 0 else 0.0
        exh_ok = cfg.exh_ban_pct <= 0 or ext_above <= cfg.exh_ban_pct

        # Watchlist: tightening under/near stack with rev context
        if had_rev and tight and gap <= cfg.tight_pct * 1.25 and c[i] <= max(ema10[i], ema20[i]) * 1.02:
            watches.append(
                {
                    "SYMBOL": sym,
                    "DATE": ymd,
                    "READY": 1 if (had_rev and tight and sma_ok) else 0,
                    "EMA_GAP_PCT": gap,
                    "EXT_BELOW_EMA20_PCT": max_ext_below,
                    "CLOSE": c[i],
                    "EMA10": ema10[i],
                    "EMA20": ema20[i],
                }
            )

        if not (had_rev and tight and above_both and prior_not_above and sma_ok and vol_ok and exh_ok):
            i += 1
            continue

        coil0 = max(0, i - cfg.coil_bars)
        coil_low = float(np.min(l[coil0:i]))
        if not (coil_low > 0 and coil_low < c[i]):
            i += 1
            continue

        fill_i = i + 1
        entry = float(o[fill_i])
        if entry <= 0 or entry < coil_low:
            # gap through stop / invalid
            i = fill_i + 1
            continue

        stop = coil_low
        notional = float(cfg.cash)
        shares = notional / entry if entry > 0 else 0.0
        exit_i = None
        exit_type = "EOD"
        exit_px = float(c[-1])

        for k in range(fill_i, n):
            # stop: gap through → GAP_DOWN @open; else STOP_LOSS @stop
            if l[k] <= stop:
                exit_i = k
                if float(o[k]) <= stop:
                    exit_type = "GAP_DOWN"
                    exit_px = float(o[k])
                else:
                    exit_type = "STOP_LOSS"
                    exit_px = float(stop)
                if exit_px <= 0:
                    exit_px = float(stop)
                break
            # trail on close (signal), fill next open when possible
            if k > fill_i and c[k] < trail[k]:
                if k + 1 < n:
                    exit_i = k + 1
                    exit_type = "TRAIL_EMA"
                    exit_px = float(o[k + 1])
                else:
                    exit_i = k
                    exit_type = "TRAIL_EMA"
                    exit_px = float(c[k])
                break

        if exit_i is None:
            exit_i = n - 1
            exit_type = "EOD"
            exit_px = float(c[exit_i])

        pnl_pct = exit_px / entry - 1.0
        pnl_dollars = shares * (exit_px - entry)
        days_held = max(0, exit_i - fill_i)
        sma50_v = float(sma50[i]) if not math.isnan(sma50[i]) else float("nan")

        closed.append(
            KellClosedRow(
                symbol=sym,
                side="LONG",
                date_opened=_ymd(dates[fill_i]),
                entry_price=entry,
                stop_price=stop,
                date_closed=_ymd(dates[exit_i]),
                exit_price=exit_px,
                exit_type=exit_type,
                days_held=days_held,
                pnl_pct=pnl_pct,
                pnl_dollars=pnl_dollars,
                setup="WEDGE_POP",
                phase="WEDGE_POP",
                ema10=float(ema10[i]),
                ema20=float(ema20[i]),
                sma50=sma50_v,
                ema_gap_pct=float(gap),
                ext_below_ema20_pct=float(max_ext_below),
                ext_above_ema20_pct=float(ext_above),
                vol_ratio=float(vol_ratio) if not math.isnan(vol_ratio) else float("nan"),
                coil_low=float(coil_low),
                coil_bars=int(cfg.coil_bars),
                trail_ema=int(cfg.trail_ema),
                prior_phase="REV_EXT",
                trigger_date=ymd,
                trigger_close=float(c[i]),
            )
        )
        last_exit_i = exit_i
        i = exit_i + 1

    return closed, watches


def run_backtest(
    symbols: list[str],
    data_dir: Path,
    cfg: KellConfig,
) -> tuple[list[KellClosedRow], list[dict[str, Any]], dict[str, Any]]:
    all_closed: list[KellClosedRow] = []
    all_watch: list[dict[str, Any]] = []
    skipped: list[str] = []
    for sym in symbols:
        path = Path(data_dir) / f"{sym}.csv"
        if not path.exists():
            # case-insensitive fallback
            matches = list(Path(data_dir).glob(f"{sym}.csv")) + list(Path(data_dir).glob(f"{sym.lower()}.csv"))
            if not matches:
                skipped.append(f"{sym}: missing csv")
                continue
            path = matches[0]
        try:
            df = load_ohlcv_csv(path)
            closed, watches = backtest_symbol(sym, df, cfg)
            all_closed.extend(closed)
            all_watch.extend(watches[-3:])  # keep recent per symbol
        except Exception as exc:  # noqa: BLE001 — research runner continues
            skipped.append(f"{sym}: {exc}")

    all_closed.sort(key=lambda r: (r.date_opened, r.symbol))
    wins = sum(1 for r in all_closed if r.pnl_pct > 0)
    n = len(all_closed)
    total_pnl = sum(r.pnl_dollars for r in all_closed)
    meta = {
        "n_closed": n,
        "n_open": 0,
        "n_signals": n,
        "win_rate": (100.0 * wins / n) if n else 0.0,
        "total_pnl": total_pnl,
        "symbols_skipped": skipped,
        "n_symbols": len(symbols) - len(skipped),
    }
    return all_closed, all_watch, meta


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def write_outputs(
    output_dir: Path,
    stamp: str,
    cfg: KellConfig,
    closed: list[KellClosedRow],
    watches: list[dict[str, Any]],
    meta: dict[str, Any],
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    closed_path = output_dir / f"{FILE_PREFIX}_Closed_{stamp}.csv"
    _write_csv(closed_path, CLOSED_HEADER, [r.to_csv_row() for r in closed])
    paths["closed"] = closed_path

    open_path = output_dir / f"{FILE_PREFIX}_Open_{stamp}.csv"
    _write_csv(open_path, CLOSED_HEADER, [])
    paths["open"] = open_path

    # Summary per symbol
    by_sym: dict[str, list[KellClosedRow]] = {}
    for r in closed:
        by_sym.setdefault(r.symbol, []).append(r)
    sum_header = [
        "SYMBOL",
        "TRADES",
        "WINS",
        "LOSSES",
        "PCT_WINS",
        "TOTAL_PNL",
        "AVG_PNL_PCT",
        "PROFIT_FACTOR",
        "AVG_DAYS_HELD",
    ]
    sum_rows: list[list[str]] = []
    for sym, rows in sorted(by_sym.items()):
        wins = sum(1 for x in rows if x.pnl_pct > 0)
        losses = len(rows) - wins
        avg_pct = sum(x.pnl_pct for x in rows) / len(rows) if rows else 0.0
        avg_days = sum(x.days_held for x in rows) / len(rows) if rows else 0.0
        tot = sum(x.pnl_dollars for x in rows)
        sum_wins = sum(x.pnl_dollars for x in rows if x.pnl_pct > 0)
        sum_losses = abs(sum(x.pnl_dollars for x in rows if x.pnl_pct < 0))
        pf = (sum_wins / sum_losses) if sum_losses > 0 else (sum_wins if sum_wins > 0 else 0.0)
        sum_rows.append(
            [
                sym,
                str(len(rows)),
                str(wins),
                str(losses),
                f"{(100.0 * wins / len(rows)) if rows else 0.0:.2f}",
                f"{tot:.2f}",
                f"{avg_pct * 100.0:.4f}",
                f"{pf:.2f}",
                f"{avg_days:.2f}",
            ]
        )
    summary_path = output_dir / f"{FILE_PREFIX}_Summary_{stamp}.csv"
    _write_csv(summary_path, sum_header, sum_rows)
    paths["summary"] = summary_path

    wh_header = ["SYMBOL", "DATE", "READY", "EMA_GAP_PCT", "EXT_BELOW_EMA20_PCT", "CLOSE", "EMA10", "EMA20"]
    wh_rows = [
        [
            w.get("SYMBOL", ""),
            w.get("DATE", ""),
            str(w.get("READY", "")),
            f"{float(w.get('EMA_GAP_PCT', 0)):.6f}",
            f"{float(w.get('EXT_BELOW_EMA20_PCT', 0)):.6f}",
            f"{float(w.get('CLOSE', 0)):.4f}",
            f"{float(w.get('EMA10', 0)):.4f}",
            f"{float(w.get('EMA20', 0)):.4f}",
        ]
        for w in watches
    ]
    watch_path = output_dir / f"{FILE_PREFIX}_Watchlist_{stamp}.csv"
    _write_csv(watch_path, wh_header, wh_rows)
    paths["watchlist"] = watch_path

    # Equity curve (exit-date cumulative)
    eq_rows: list[list[str]] = []
    equity = float(cfg.initial_capital)
    eq_rows.append(["DATE", "EQUITY", "PNL_DAY"])
    running = equity
    by_day: dict[str, float] = {}
    for r in closed:
        by_day[r.date_closed] = by_day.get(r.date_closed, 0.0) + r.pnl_dollars
    for d in sorted(by_day):
        running += by_day[d]
        eq_rows.append([d, f"{running:.2f}", f"{by_day[d]:.2f}"])
    equity_path = output_dir / f"{FILE_PREFIX}_EquityCurve_{stamp}.csv"
    with equity_path.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(eq_rows)
    paths["equity"] = equity_path

    peak = equity
    max_dd = 0.0
    run = equity
    for d in sorted(by_day):
        run += by_day[d]
        peak = max(peak, run)
        if peak > 0:
            max_dd = max(max_dd, (peak - run) / peak)
    meta_path = output_dir / f"{FILE_PREFIX}_EquityMeta_{stamp}.csv"
    _write_csv(
        meta_path,
        ["INITIAL_CAPITAL", "FINAL_EQUITY", "TOTAL_PNL", "MAX_DD_PCT", "N_CLOSED", "WIN_RATE_PCT"],
        [
            [
                f"{cfg.initial_capital:.2f}",
                f"{running:.2f}",
                f"{meta.get('total_pnl', 0):.2f}",
                f"{max_dd * 100.0:.4f}",
                str(meta.get("n_closed", 0)),
                f"{meta.get('win_rate', 0):.2f}",
            ]
        ],
    )
    paths["equity_meta"] = meta_path

    report_path = output_dir / f"{FILE_PREFIX}_Report_{stamp}.txt"
    report_path.write_text(
        "\n".join(
            [
                f"Kell PAC research run stamp={stamp}",
                f"closed={meta.get('n_closed')} win_rate={meta.get('win_rate'):.1f}% "
                f"pnl=${meta.get('total_pnl'):.2f}",
                f"trail_ema={cfg.trail_ema} tight_pct={cfg.tight_pct} "
                f"rev_ext_pct={cfg.rev_ext_pct} exh_ban_pct={cfg.exh_ban_pct}",
                f"require_sma50={cfg.require_sma50} min_price={cfg.min_price}",
                f"skipped={len(meta.get('symbols_skipped', []))}",
                "NOTE: research Audit — not full brt_audit_columns host schema.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    paths["report"] = report_path

    audit_path = output_dir / f"{FILE_PREFIX}_Audit_Report_{stamp}.csv"
    audit_fields = {
        "system": "kell_pac",
        "prefix": FILE_PREFIX,
        "stamp": stamp,
        "audit_shape": "research_row",
        "kell_mode": "standalone",
        "n_closed": meta.get("n_closed"),
        "win_rate_pct": round(float(meta.get("win_rate", 0)), 4),
        "total_pnl": round(float(meta.get("total_pnl", 0)), 2),
        "kell_trail_ema": cfg.trail_ema,
        "kell_tight_pct": cfg.tight_pct,
        "kell_rev_ext_pct": cfg.rev_ext_pct,
        "kell_exh_ban_pct": cfg.exh_ban_pct,
        "kell_coil_bars": cfg.coil_bars,
        "kell_require_sma50": cfg.require_sma50,
        "kell_min_price": cfg.min_price,
        "host_dollar_scale": cfg.host_dollar_scale,
        "aggressive": cfg.aggressive,
    }
    with audit_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(list(audit_fields.keys()))
        w.writerow([audit_fields[k] for k in audit_fields])
    paths["audit"] = audit_path

    # LatestRun mirrors
    for label, src in (
        ("Closed", closed_path),
        ("Open", open_path),
        ("Summary", summary_path),
        ("Watchlist", watch_path),
        ("Audit_Report", audit_path),
        ("EquityCurve", equity_path),
    ):
        dst = output_dir / f"{FILE_PREFIX}_LatestRun_{label}.csv"
        dst.write_bytes(src.read_bytes())
        paths[f"latest_{label.lower()}"] = dst

    (output_dir / f"{FILE_PREFIX}_last_run_ts.txt").write_text(stamp + "\n", encoding="utf-8")
    return paths


def cfg_from_args(ns: argparse.Namespace) -> KellConfig:
    return KellConfig(
        rev_lookback=int(ns.kell_rev_lookback),
        rev_ext_pct=float(ns.kell_rev_ext_pct),
        tight_pct=float(ns.kell_tight_pct),
        coil_bars=int(ns.kell_coil_bars),
        vol_mult=float(ns.kell_vol_mult),
        require_sma50=_as_bool(ns.kell_require_sma50),
        min_price=float(ns.kell_min_price),
        trail_ema=int(ns.kell_trail_ema),
        exh_ban_pct=float(ns.kell_exh_ban_pct),
        cash=float(ns.cash),
        initial_capital=float(ns.initial_capital),
        aggressive_max_multiple=float(ns.aggressive_max_multiple),
        margin_utilization=float(ns.margin_utilization),
        max_positions=int(ns.max_positions),
        aggressive=bool(ns.aggressive),
        host_dollar_scale=_as_bool(ns.host_dollar_scale),
        entry_start_date=str(ns.entry_start_date or ""),
        entry_end_date=str(ns.entry_end_date or ""),
    )


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Oliver Kell PAC / Wedge Pop research engine (KELL_*)")
    p.add_argument("data_dir", nargs="?", default="data/newdata/data")
    p.add_argument("-o", "--output-dir", default="drive")
    p.add_argument("-s", "--symbols", default="", help="Comma list; empty = all CSV excl. SPY")
    p.add_argument("--stamp", default="")
    p.add_argument("--cash", type=float, default=DEFAULT_CASH)
    p.add_argument("--kell-rev-lookback", type=int, default=40)
    p.add_argument("--kell-rev-ext-pct", type=float, default=0.08)
    p.add_argument("--kell-tight-pct", type=float, default=0.025)
    p.add_argument("--kell-coil-bars", type=int, default=8)
    p.add_argument("--kell-vol-mult", type=float, default=0.0)
    p.add_argument("--kell-require-sma50", type=_as_bool, default=True)
    p.add_argument("--kell-min-price", type=float, default=10.0)
    p.add_argument("--kell-trail-ema", type=int, default=20)
    p.add_argument("--kell-exh-ban-pct", type=float, default=0.12)
    p.add_argument("--initial-capital", type=float, default=DEFAULT_INITIAL_CAPITAL)
    p.add_argument("--aggressive-max-multiple", type=float, default=DEFAULT_AGGRESSIVE_MAX_MULTIPLE)
    p.add_argument("--margin-utilization", type=float, default=DEFAULT_MARGIN_UTILIZATION)
    p.add_argument("--max-positions", type=int, default=0)
    p.add_argument("--aggressive", action="store_true")
    p.add_argument("--host-dollar-scale", type=_as_bool, default=True)
    p.add_argument("--entry-start-date", default="")
    p.add_argument("--entry-end-date", default="")
    p.add_argument(
        "-w",
        "--workers",
        type=int,
        default=0,
        help="Parallel workers (accepted for run_*.bat parity; 0=sequential)",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    cfg = cfg_from_args(args)
    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    symbols = resolve_run_symbols(args.symbols, data_dir)
    stamp = (args.stamp or "").strip() or datetime.now().strftime("%y%m%d%H%M%S")
    if not symbols:
        print(f"[KELL] ERROR: no symbols under {data_dir}", flush=True)
        return 1

    print(
        f"[KELL] PAC Wedge Pop research: {len(symbols)} symbols -> {output_dir} stamp={stamp} "
        f"tight={cfg.tight_pct} rev={cfg.rev_ext_pct} trail={cfg.trail_ema}",
        flush=True,
    )
    closed, watches, meta = run_backtest(symbols, data_dir, cfg)

    if (
        cfg.host_dollar_scale
        and closed
        and apply_host_dollar_scale is not None
        and HostSizingConfig is not None
    ):
        host_cfg = HostSizingConfig(
            brt_cash=float(cfg.cash),
            initial_capital=float(cfg.initial_capital),
            aggressive_max_multiple=float(cfg.aggressive_max_multiple),
            margin_utilization=float(cfg.margin_utilization),
            max_positions=int(cfg.max_positions),
            aggressive=bool(cfg.aggressive),
        )
        # apply_host_dollar_scale expects objects with pnl_dollars attr — our rows match
        opens: list[Any] = []
        adj, scale, max_pos = apply_host_dollar_scale(closed, opens, host_cfg)
        cfg.cash = adj
        meta["total_pnl"] = sum(r.pnl_dollars for r in closed)
        meta["host_max_positions"] = max_pos
        meta["host_pnl_scale"] = scale
        print(
            f"[KELL] Host dollar-scale × {scale:.6g}; brt_cash -> {adj:,.0f} "
            f"(Max_Positions={max_pos})",
            flush=True,
        )
    elif cfg.host_dollar_scale and apply_host_dollar_scale is None:
        print("[KELL] WARNING: tbn_host_sizing unavailable — skipping dollar-scale", flush=True)

    paths = write_outputs(output_dir, stamp, cfg, closed, watches, meta)
    print(
        f"[KELL] Done. closed={meta['n_closed']} WR={meta['win_rate']:.1f}% "
        f"PnL=${meta['total_pnl']:.2f} skipped={len(meta['symbols_skipped'])}",
        flush=True,
    )
    print(f"[KELL] Closed: {paths['closed']}", flush=True)
    print(f"[KELL] Summary: {paths['summary']}", flush=True)
    print(f"[KELL] Audit: {paths['audit']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
