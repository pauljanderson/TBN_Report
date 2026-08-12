#!/usr/bin/env python3
"""
Volume Zone (VZ) - break & retest research sleeve (TBN-hosted).

TBN mode: ``rocket_tbn.py -v vz_mode=true`` (preferred; ``run_vz.bat``).
Standalone: ``python stock_analysis/rocket_vz.py …`` still works and uses the same
Closed / Audit / Report / equity / post_run writers as RS/SB peers.

Engine logic: ``tools/vol_zone_break_retest.py``
  Freeze entry gates: RESEARCH_CANDIDATE_V2_RW63 (HL-only, first_retest, mt≥1, rw63)
  Primary exit: PRIMARY_EXIT = zone_atr05_ts40
  House default fill: entry_on=next_open (signal bar T close -> buy T+1 open).
  Prior research AB freeze used entry_on=close (EOD fill on signal bar - also predictive;
  never buys signal-bar open).

Outputs (prefix ``VZ_``):
  Closed / Open / Watchlist / Summary / Report / Audit_Report (wide TBN schema)
  EquityCurve (+ Aggressive) / EquityMeta / Correlation / Summary_Symbols
  Pipeline_Timings / checkpoint / LatestRun_* / last_run_ts

Status: **research candidate only** - not production gold, not DailyRun-wired.
Docs: drive/paul_experiments/VZ_System_Guide.html
      drive/paul_experiments/tbn_new_systems/volume_zone/HOW_TO_RUN.md
      drive/paul_experiments/VZ_TBN_Integration_And_Predictive_Timing.html

Examples:
  run_vz.bat
  run_vz.bat -w 12 -s NVDA,AAPL
  run_vz.bat drive\\universes\\PaulTwenty_universe.csv
  python stock_analysis/rocket_tbn.py data/newdata/data -o drive -v vz_mode=true -s NVDA,AAPL
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import os
import pickle
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, fields, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
_SA = Path(__file__).resolve().parent
if str(_SA) not in sys.path:
    sys.path.insert(0, str(_SA))

# Research engine (not gold)
from tools.vol_zone_break_retest import (  # noqa: E402
    OOS_SPLIT_DATE,
    PRIMARY_EXIT,
    RESEARCH_CANDIDATE_V2_RW63,
    ExitSpec,
    SysParams,
    atr14,
    assert_predictive_entry,
    build_zones,
    load_ohlcv,
    load_universe_symbols,
    run_symbol_with_params,
    simulate_exit_spec,
    split_is_oos,
    summarize_signal_dicts,
)

from tools.gen_vol_zone_symbol_summary import (  # noqa: E402
    SHEET_NOTIONAL,
    build_summary_rows,
    write_csv as write_summary_csv,
    write_html as write_summary_html,
)

FILE_PREFIX = "VZ"
DEFAULT_INITIAL_CAPITAL = 500_000.0
DEFAULT_DATA_DIR = REPO / "data" / "newdata" / "data"
DEFAULT_OUT_DIR = REPO / "drive"
DEFAULT_UNIVERSE = REPO / "drive" / "universes" / "VZ_universe.csv"
STAMP_ROOT = REPO / "drive" / "paul_experiments"

# Extra Closed DNA spliced after write_brt_closed (peer pattern = SB burst DNA).
_VZ_DNA_CLOSED_COLS = (
    "SIGNAL_DATE",
    "ENTRY_ON",
    "ZONE_ID",
    "ZONE_KIND",
    "ZONE_LO",
    "BREAK_DATE",
    "BARS_AFTER_BREAK",
    "TOUCH_COUNT_ALL",
    "TOUCH_COUNT_HOLDS",
    "PRE_BREAK_TOUCHES",
    "POST_BREAK_TOUCHES",
    "STRENGTH",
    "BREAK_DIST_PCT",
    "BREAK_ATR_MULT",
    "VISIT_N",
    "EXIT_NAME",
    "PARAMS_TAG",
    "R_MULT",
    "ONE_LINER",
)

CLOSED_HEADER = [
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
    "R_MULT",
    "SIGNAL_DATE",
    "ENTRY_ON",
    "ZONE_ID",
    "ZONE_KIND",
    "ZONE_LO",
    "BREAK_DATE",
    "BARS_AFTER_BREAK",
    "TOUCH_COUNT_ALL",
    "TOUCH_COUNT_HOLDS",
    "PRE_BREAK_TOUCHES",
    "POST_BREAK_TOUCHES",
    "STRENGTH",
    "BREAK_DIST_PCT",
    "BREAK_ATR_MULT",
    "VISIT_N",
    "EXIT_NAME",
    "PARAMS_TAG",
    "ONE_LINER",
]

OPEN_HEADER = [
    "SYMBOL",
    "DATE_OPENED",
    "ENTRY_PRICE",
    "CURRENT_PRICE",
    "PNL_PCT",
    "DAYS_OPEN",
    "STOP_LOSS",
    "TARGET",
    "ZONE_ID",
    "NOTES",
]

WATCH_HEADER = [
    "SYMBOL",
    "ASOF_DATE",
    "ZONE_ID",
    "ZONE_KIND",
    "ZONE_LO",
    "ZONE_HI",
    "NOTES",
]


def _as_bool(x: Any) -> bool:
    if isinstance(x, bool):
        return x
    return str(x).strip().lower() in ("1", "true", "yes", "on")


def _ymd(d: Any) -> str:
    if hasattr(d, "strftime"):
        return d.strftime("%Y%m%d")
    s = str(d)[:10].replace("-", "")
    return s


def _iso(d: Any) -> str:
    if hasattr(d, "strftime"):
        return d.strftime("%Y-%m-%d")
    return str(d)[:10]


def parse_symbols(s: str) -> list[str]:
    return [x.strip().upper() for x in (s or "").replace(";", ",").split(",") if x.strip()]


def list_data_dir_symbols(data_dir: Path) -> list[str]:
    if not data_dir.is_dir():
        return []
    return sorted(
        p.stem.upper()
        for p in data_dir.glob("*.csv")
        if p.is_file() and p.stem.upper() != "SPY"
    )


def resolve_symbols(symbols_arg: str, data_dir: Path) -> list[str]:
    raw = (symbols_arg or "").strip()
    if not raw or raw in ("*", "ALL"):
        return list_data_dir_symbols(data_dir)
    parsed = parse_symbols(raw)
    return parsed


@dataclass
class VzConfig:
    lookback_days: int = 126
    retest_window: int = 63
    retest_eps_pct: float = 0.005
    first_retest_only: bool = True
    min_touches_before_entry: int = 1
    # House / TBN default: next open after signal bar (predictive). Prior AB freeze used close.
    entry_on: str = "next_open"
    zone_kinds: tuple[str, ...] = ("HL",)
    exit_name: str = "zone_atr05_ts40"
    exit_bars: int = 40
    target_r: float = 2.0
    stop_atr_buffer: float = 0.5
    sheet_notional: float = SHEET_NOTIONAL
    initial_capital: float = DEFAULT_INITIAL_CAPITAL
    aggressive: bool = True
    write_charts: bool = False
    write_stamp_folder: bool = True
    max_positions: int = 0
    aggressive_max_multiple: float = 2.0
    margin_utilization: float = 0.6
    brt_cash: float = SHEET_NOTIONAL  # Ann_ROR scale (sheet notional by default)


def params_from_cfg(cfg: VzConfig) -> SysParams:
    base = replace(
        RESEARCH_CANDIDATE_V2_RW63,
        lookback_days=int(cfg.lookback_days),
        retest_window=int(cfg.retest_window),
        retest_eps_pct=float(cfg.retest_eps_pct),
        first_retest_only=bool(cfg.first_retest_only),
        min_touches_before_entry=int(cfg.min_touches_before_entry),
        entry_on=str(cfg.entry_on),  # type: ignore[arg-type]
        zone_kinds=tuple(cfg.zone_kinds),  # type: ignore[arg-type]
        exit_bars=int(cfg.exit_bars),
        target_r=float(cfg.target_r),
    )
    return base


def exit_spec_from_cfg(cfg: VzConfig) -> ExitSpec:
    if cfg.exit_name == PRIMARY_EXIT.name:
        return PRIMARY_EXIT
    return ExitSpec(
        name=str(cfg.exit_name),
        label=f"custom {cfg.exit_name}",
        exit_bars=int(cfg.exit_bars),
        target_r=float(cfg.target_r),
        stop_atr_buffer=float(cfg.stop_atr_buffer),
    )


def _exit_price_from_pnl(entry: float, pnl_pct: float) -> float:
    return float(entry) * (1.0 + float(pnl_pct) / 100.0)


def _ann_ror(pnl_pct: float, days_held: int) -> float:
    if days_held <= 0:
        return 0.0
    return float(pnl_pct) * (365.25 / float(days_held))


_STILL_OPEN_REASONS = frozenset({"still_open", "end_of_data"})


def enrich_trade_rows(
    symbol: str,
    df: pd.DataFrame,
    sigs: list,
    params: SysParams,
    atr: np.ndarray,
    exit_spec: ExitSpec,
    sheet_notional: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """House Closed + Open rows + research signal fields.

    ``still_open`` / ``end_of_data`` from simulate_exit go to Open (active as-of last bar),
    not Closed. Only ``time`` with bars_held >= exit_bars is a real time-stop close.
    """
    closed: list[dict[str, Any]] = []
    opens: list[dict[str, Any]] = []
    dates = df["Date"]
    highs = df["High"].to_numpy(dtype=np.float64)
    asof_ymd = _ymd(dates.iloc[-1]) if len(dates) else ""
    asof_iso = _iso(dates.iloc[-1]) if len(dates) else ""
    zone_hi_fallback = 0.0
    for s in sigs:
        sim = simulate_exit_spec(df, s, exit_spec, atr=atr)
        bars = int(sim["bars_held"])
        exit_idx = min(len(df) - 1, int(s.entry_idx) + bars)
        entry = float(s.entry_price)
        pnl_pct = float(sim["pnl_pct"])
        exit_px = _exit_price_from_pnl(entry, pnl_pct)
        stop_px = float(sim["stop"])
        target_px = float(sim["target"])
        # Max high from entry through exit/as-of bar
        max_px = (
            float(np.max(highs[int(s.entry_idx) : exit_idx + 1]))
            if exit_idx >= s.entry_idx
            else entry
        )
        raw_reason = str(sim["exit_reason"] or "").strip().lower()
        exit_reason = raw_reason.upper()
        if exit_reason == "TIME":
            exit_type = "TIME"
        elif exit_reason == "STOP":
            exit_type = "STOP"
        elif exit_reason == "TARGET":
            exit_type = "TARGET"
        else:
            exit_type = exit_reason
        d_open = _ymd(s.entry_date)
        d_signal = _ymd(getattr(s, "signal_date", None) or s.entry_date)
        # Predictive smoke: signal known on signal bar; entry never before signal.
        try:
            assert_predictive_entry(s, str(params.entry_on))  # type: ignore[arg-type]
        except AssertionError as e:
            raise AssertionError(f"{symbol}: {e}") from e
        pnl_dollars = pnl_pct / 100.0 * float(sheet_notional)
        zone_lo = round(float(s.stop), 4)
        # Zone hi not always on signal; approximate from stop/zone if present
        zone_hi = float(getattr(s, "zone_hi", 0) or getattr(s, "zone_high", 0) or 0) or zone_hi_fallback
        signal_dict = {
            "symbol": symbol,
            "zone_id": s.zone_id,
            "kind": s.kind,
            "break_date": str(pd.Timestamp(s.break_date).date()),
            "signal_date": str(pd.Timestamp(getattr(s, "signal_date", s.entry_date)).date()),
            "entry_date": str(pd.Timestamp(s.entry_date).date()),
            "entry_price": round(entry, 4),
            "entry_on": str(params.entry_on),
            "stop": round(stop_px, 4),
            "zone_lo": zone_lo,
            "bars_after_break": int(s.bars_after_break),
            "touch_count_all": int(s.touch_count_all),
            "touch_count_holds": int(s.touch_count_holds),
            "pre_break_touches": int(s.pre_break_touches),
            "post_break_touches": int(s.post_break_touches),
            "strength": round(float(s.strength), 3),
            "break_dist_pct": round(float(s.break_dist_pct), 5),
            "break_atr_mult": round(float(s.break_atr_mult), 3),
            "visit_n": int(s.visit_n),
            "pnl_pct": round(pnl_pct, 4),
            "r_mult": round(float(sim["r_mult"]), 4),
            "win": int(pnl_pct > 0),
            "exit_reason": sim["exit_reason"],
            "bars_held": bars,
            "exit_name": exit_spec.name,
            "params_tag": s.params_tag,
        }
        base = {
            "SYMBOL": symbol,
            "SIDE": "LONG",
            "DATE_OPENED": d_open,
            "ENTRY_PRICE": round(entry, 4),
            "STOP_PRICE": round(stop_px, 4),
            "TARGET_PRICE": round(target_px, 4),
            "DAYS_HELD": bars,
            "PNL_PCT": round(pnl_pct, 4),
            "PNL_DOLLARS": round(pnl_dollars, 2),
            "ANN_ROR_PCT": round(_ann_ror(pnl_pct, bars), 4),
            "MAX_PRICE": round(max_px, 4),
            "R_MULT": round(float(sim["r_mult"]), 4),
            "SIGNAL_DATE": d_signal,
            "ENTRY_ON": str(params.entry_on),
            "ZONE_ID": s.zone_id,
            "ZONE_KIND": s.kind,
            "ZONE_LO": zone_lo,
            "ZONE_HI": round(zone_hi, 4) if zone_hi else "",
            "BREAK_DATE": _ymd(s.break_date),
            "BARS_AFTER_BREAK": int(s.bars_after_break),
            "TOUCH_COUNT_ALL": int(s.touch_count_all),
            "TOUCH_COUNT_HOLDS": int(s.touch_count_holds),
            "PRE_BREAK_TOUCHES": int(s.pre_break_touches),
            "POST_BREAK_TOUCHES": int(s.post_break_touches),
            "STRENGTH": round(float(s.strength), 3),
            "BREAK_DIST_PCT": round(float(s.break_dist_pct), 5),
            "BREAK_ATR_MULT": round(float(s.break_atr_mult), 3),
            "VISIT_N": int(s.visit_n),
            "EXIT_NAME": exit_spec.name,
            "PARAMS_TAG": s.params_tag,
            "ENTRY_BAR_INDEX": int(s.entry_idx),
            "_signal": signal_dict,
        }
        if raw_reason in _STILL_OPEN_REASONS:
            one = (
                f"{symbol} | SIG {_iso(getattr(s, 'signal_date', s.entry_date))} "
                f"IN {_iso(s.entry_date)} @ {entry:.2f} -> OPEN asof {asof_iso} "
                f"@ {exit_px:.2f} | MTM {pnl_pct:+.1f}% | {bars}d/{exit_spec.exit_bars}d | zone {s.zone_id}"
            )
            open_row = {
                **base,
                "ASOF_DATE": asof_ymd,
                "CURRENT_PRICE": round(exit_px, 4),
                "DATE_CLOSED": "",
                "EXIT_PRICE": "",
                "EXIT_TYPE": "",
                "ONE_LINER": one,
            }
            opens.append(open_row)
        else:
            d_close = _ymd(dates.iloc[exit_idx])
            one = (
                f"{symbol} | SIG {_iso(getattr(s, 'signal_date', s.entry_date))} "
                f"IN {_iso(s.entry_date)} @ {entry:.2f} -> OUT {_iso(dates.iloc[exit_idx])} "
                f"@ {exit_px:.2f} | {exit_type} {pnl_pct:+.1f}% | {bars}d | zone {s.zone_id}"
            )
            closed.append(
                {
                    **base,
                    "DATE_CLOSED": d_close,
                    "EXIT_PRICE": round(exit_px, 4),
                    "EXIT_TYPE": exit_type,
                    "ONE_LINER": one,
                }
            )
    return closed, opens


def enrich_closed_rows(
    symbol: str,
    df: pd.DataFrame,
    sigs: list,
    params: SysParams,
    atr: np.ndarray,
    exit_spec: ExitSpec,
    sheet_notional: float,
) -> list[dict[str, Any]]:
    """Backward-compatible: closed rows only (opens discarded). Prefer enrich_trade_rows."""
    closed, _opens = enrich_trade_rows(
        symbol, df, sigs, params, atr, exit_spec, sheet_notional
    )
    return closed


def _resolve_vz_workers(workers_arg: int) -> int:
    """Map CLI ``-w`` to process count. ``0`` = sequential; ``-1`` = min(8, CPUs)."""
    w = int(workers_arg)
    if w < 0:
        return min(8, os.cpu_count() or 4)
    return max(0, w)


def _vz_cfg_dict(cfg: VzConfig) -> dict[str, Any]:
    return {f.name: getattr(cfg, f.name) for f in fields(VzConfig)}


def _vz_cfg_from_dict(d: dict[str, Any]) -> VzConfig:
    known = {f.name for f in fields(VzConfig)}
    return VzConfig(**{k: v for k, v in d.items() if k in known})


def _process_one_symbol(
    sym: str,
    data_dir: Path,
    cfg: VzConfig,
) -> dict[str, Any]:
    """One-symbol VZ backtest (picklable via ``_worker_vz_symbol``)."""
    ts = time.time()
    csv_path = data_dir / f"{sym}.csv"
    if not csv_path.is_file():
        note = f"missing CSV: {csv_path.name}"
        return {
            "symbol": sym,
            "status": "missing",
            "note": note,
            "rows": [],
            "open_rows": [],
            "per_symbol": {"symbol": sym, "status": "missing", "note": note},
            "elapsed": time.time() - ts,
        }
    try:
        params = params_from_cfg(cfg)
        exit_spec = exit_spec_from_cfg(cfg)
        df = load_ohlcv(csv_path)
        atr = atr14(df)
        zones = build_zones(df, params.lookback_days)
        sigs, _, _ = run_symbol_with_params(sym, df, zones, atr, params)
        rows_closed, rows_open = enrich_trade_rows(
            sym, df, sigs, params, atr, exit_spec, cfg.sheet_notional
        )
        # Per-symbol WR/AvgR from closed only (still_open excluded via summarize too)
        sig_dicts = [r["_signal"] for r in rows_closed if "_signal" in r]
        m = summarize_signal_dicts(sig_dicts)
        is_r, oos_r = split_is_oos(sig_dicts)
        m_is = summarize_signal_dicts(is_r)
        m_oos = summarize_signal_dicts(oos_r)
        elapsed = time.time() - ts
        return {
            "symbol": sym,
            "status": "ok",
            "note": "",
            "rows": rows_closed,
            "open_rows": rows_open,
            "per_symbol": {
                "symbol": sym,
                "status": "ok",
                "n_bars": len(df),
                "date_start": str(pd.Timestamp(df["Date"].iloc[0]).date()),
                "date_end": str(pd.Timestamp(df["Date"].iloc[-1]).date()),
                "rw63_n": m["n_signals"],
                "rw63_wr": m["win_rate"],
                "rw63_avg_r": m["avg_r"],
                "rw63_avg_pnl_pct": m["avg_pnl_pct"],
                "rw63_is_n": m_is["n_signals"],
                "rw63_is_wr": m_is["win_rate"],
                "rw63_is_avg_r": m_is["avg_r"],
                "rw63_oos_n": m_oos["n_signals"],
                "rw63_oos_wr": m_oos["win_rate"],
                "rw63_oos_avg_r": m_oos["avg_r"],
            },
            "elapsed": elapsed,
            "n_signals": m["n_signals"],
            "win_rate": m["win_rate"],
            "avg_r": m["avg_r"],
        }
    except Exception as e:  # noqa: BLE001
        note = str(e)
        return {
            "symbol": sym,
            "status": "error",
            "note": note,
            "rows": [],
            "open_rows": [],
            "per_symbol": {"symbol": sym, "status": "error", "note": note},
            "elapsed": time.time() - ts,
        }


def _worker_vz_symbol(args: tuple[str, str, dict[str, Any]]) -> dict[str, Any]:
    """ProcessPool worker: (symbol, data_dir_str, cfg_dict)."""
    sym, data_dir_str, cfg_d = args
    return _process_one_symbol(sym, Path(data_dir_str), _vz_cfg_from_dict(cfg_d))


def _print_symbol_result(res: dict[str, Any]) -> None:
    sym = res["symbol"]
    if res["status"] != "ok":
        print(f"  SKIP {sym}: {res.get('note') or res['status']}", flush=True)
        return
    print(
        f"  {sym}: N={res.get('n_signals', 0)} WR={float(res.get('win_rate', 0))*100:.1f}% "
        f"AvgR={float(res.get('avg_r', 0)):.2f} ({float(res.get('elapsed', 0)):.2f}s)",
        flush=True,
    )


def run_backtest(
    symbols: list[str],
    data_dir: Path,
    cfg: VzConfig,
    *,
    workers: int = 0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict], dict[str, Any]]:
    params = params_from_cfg(cfg)
    exit_spec = exit_spec_from_cfg(cfg)
    closed: list[dict[str, Any]] = []
    opens: list[dict[str, Any]] = []
    signal_rows: list[dict[str, Any]] = []
    per_symbol: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    t0 = time.time()
    per_sym_sec: list[tuple[str, float, int]] = []

    n_workers = _resolve_vz_workers(int(workers))
    cfg_d = _vz_cfg_dict(cfg)
    data_dir_str = str(data_dir)
    results: list[dict[str, Any]] = []

    if n_workers > 0 and len(symbols) > 1:
        n_w = min(n_workers, len(symbols), 32)
        print(
            f"[VZ] Spawning {n_w} worker process(es) for {len(symbols)} symbols",
            flush=True,
        )
        tasks = [(sym, data_dir_str, cfg_d) for sym in symbols]
        with ProcessPoolExecutor(max_workers=n_w) as ex:
            futs = {ex.submit(_worker_vz_symbol, t): t[0] for t in tasks}
            for fut in as_completed(futs):
                sym = futs[fut]
                try:
                    res = fut.result()
                except Exception as e:  # noqa: BLE001
                    res = {
                        "symbol": sym,
                        "status": "error",
                        "note": f"worker failed ({e})",
                        "rows": [],
                        "open_rows": [],
                        "per_symbol": {
                            "symbol": sym,
                            "status": "error",
                            "note": f"worker failed ({e})",
                        },
                        "elapsed": 0.0,
                    }
                _print_symbol_result(res)
                results.append(res)
    else:
        for sym in symbols:
            res = _process_one_symbol(sym, data_dir, cfg)
            _print_symbol_result(res)
            results.append(res)

    # Stable order matching request list when parallel completion scrambled
    by_sym = {r["symbol"]: r for r in results}
    for sym in symbols:
        res = by_sym.get(sym)
        if res is None:
            continue
        rows = list(res.get("rows") or [])
        open_rows = list(res.get("open_rows") or [])
        closed.extend(rows)
        opens.extend(open_rows)
        signal_rows.extend([r["_signal"] for r in rows if "_signal" in r])
        # Keep still_open signals in stamp CSV for audit, but summarize excludes them
        signal_rows.extend([r["_signal"] for r in open_rows if "_signal" in r])
        per_symbol.append(res["per_symbol"])
        per_sym_sec.append((sym, float(res.get("elapsed") or 0.0), len(rows) + len(open_rows)))
        if res["status"] != "ok":
            skipped.append({"symbol": sym, "note": res.get("note") or res["status"]})

    # Drop private _signal before returning rows for CSV
    closed_out = [{k: v for k, v in r.items() if k != "_signal"} for r in closed]
    open_out = [{k: v for k, v in r.items() if k != "_signal"} for r in opens]
    full_m = summarize_signal_dicts(signal_rows)
    is_rows, oos_rows = split_is_oos(signal_rows)
    meta: dict[str, Any] = {
        "n_symbols": len(symbols),
        "n_ok": sum(1 for r in per_symbol if r.get("status") == "ok"),
        "n_skipped": len(skipped),
        "n_closed": len(closed_out),
        "n_open": len(open_out),
        "n_signals": full_m["n_signals"],
        "win_rate": full_m["win_rate"] * 100.0,
        "avg_pnl_pct": full_m["avg_pnl_pct"],
        "avg_r": full_m["avg_r"],
        "total_pnl": sum(float(r["PNL_DOLLARS"]) for r in closed_out),
        "exit_mix": {},
        "elapsed_sec": time.time() - t0,
        "workers": n_workers if n_workers > 0 and len(symbols) > 1 else 0,
        "per_symbol_sec": per_sym_sec,
        "skipped": skipped,
        "params": params,
        "exit_spec": exit_spec,
        "is_m": summarize_signal_dicts(is_rows),
        "oos_m": summarize_signal_dicts(oos_rows),
        "full_m": full_m,
        "signal_rows": signal_rows,
        "per_symbol": per_symbol,
    }
    for r in closed_out:
        et = str(r.get("EXIT_TYPE", ""))
        meta["exit_mix"][et] = meta["exit_mix"].get(et, 0) + 1
    if open_out:
        meta["exit_mix"]["OPEN"] = len(open_out)
    return closed_out, open_out, per_symbol, meta


def write_equity(
    path: Path,
    meta_path: Path,
    closed: list[dict[str, Any]],
    *,
    initial_cash: float,
    aggressive: bool,
) -> None:
    by_date: dict[str, float] = {}
    for r in closed:
        d = str(r.get("DATE_CLOSED", ""))
        if len(d) == 8 and d.isdigit():
            d = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        if not d:
            continue
        by_date[d] = by_date.get(d, 0.0) + float(r.get("PNL_DOLLARS") or 0.0)
    dates = sorted(by_date)
    equity = float(initial_cash)
    peak = equity
    max_dd = 0.0
    rows: list[dict[str, Any]] = []
    for d in dates:
        equity += by_date[d]
        if equity > peak:
            peak = equity
        dd = ((peak - equity) / peak) if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
        rows.append({"Date": d, "Equity": round(equity, 2), "Positions": ""})
    if not rows:
        rows.append({"Date": "", "Equity": initial_cash, "Positions": ""})
    pd.DataFrame(rows).to_csv(path, index=False)
    pd.DataFrame(
        [
            {
                "Initial_Account_Size": initial_cash,
                "Max_Drawdown_fraction": max_dd,
                "Max_Drawdown_pct": f"{max_dd * 100:.2f}%",
                "Aggressive": bool(aggressive),
                "Curve_Kind": "realized_sheet_notional_by_exit_date",
                "Sheet_Notional": SHEET_NOTIONAL,
                "Note": "VZ research sleeve - sheet $45k/trade; not host dollar-scale",
            }
        ]
    ).to_csv(meta_path, index=False)



def vz_closed_to_brt_trade(r: dict[str, Any]) -> Any:
    try:
        from rocket_tbn import BRTTrade
    except ImportError:
        from stock_analysis.rocket_tbn import BRTTrade  # type: ignore

    t = BRTTrade(
        symbol=str(r["SYMBOL"]).upper(),
        date_opened=str(r["DATE_OPENED"]),
        entry_price=float(r["ENTRY_PRICE"]),
        stop_price=float(r["STOP_PRICE"]),
        target_price=float(r["TARGET_PRICE"]),
        date_closed=str(r.get("DATE_CLOSED") or ""),
        exit_price=float(r.get("EXIT_PRICE") or 0.0),
        exit_type=str(r.get("EXIT_TYPE") or ""),
        days_held=int(r.get("DAYS_HELD") or 0),
        pnl_pct=float(r.get("PNL_PCT") or 0.0),
        pnl_dollars=float(r.get("PNL_DOLLARS") or 0.0),
        max_price=float(r.get("MAX_PRICE") or r.get("ENTRY_PRICE") or 0.0),
        zone_low=float(r.get("ZONE_LO") or 0.0),
        touch_count=int(r.get("TOUCH_COUNT_ALL") or 0),
        breakout_date=str(r.get("BREAK_DATE") or ""),
        days_since_breakout=int(r.get("BARS_AFTER_BREAK") or 0)
        if r.get("BARS_AFTER_BREAK") not in (None, "")
        else None,
        entry_bar_index=int(r.get("ENTRY_BAR_INDEX") or -1),
    )
    return t


def brt_config_from_vz(cfg: VzConfig, host_cfg: Any = None) -> Any:
    """BRTConfig for unified Audit/Report (same wide schema as RS/SB)."""
    try:
        from rocket_tbn import BRTConfig
    except ImportError:
        from stock_analysis.rocket_tbn import BRTConfig  # type: ignore

    base_kw = dict(
        vz_mode=True,
        sb_mode=False,
        qull_mode=False,
        mvcp_mode=False,
        brt_zones=False,
        yh_zones=False,
        wpbr_zones=False,
        rl_mode="false",
        relative_strength_enabled=False,
        brt_cash=float(cfg.brt_cash or cfg.sheet_notional),
        initial_capital=float(cfg.initial_capital),
        aggressive=bool(cfg.aggressive),
        aggressive_max_multiple=float(cfg.aggressive_max_multiple),
        margin_utilization=float(cfg.margin_utilization),
        max_positions=int(cfg.max_positions),
        vz_lookback_days=int(cfg.lookback_days),
        vz_retest_window=int(cfg.retest_window),
        vz_retest_eps_pct=float(cfg.retest_eps_pct),
        vz_first_retest_only=bool(cfg.first_retest_only),
        vz_min_touches_before_entry=int(cfg.min_touches_before_entry),
        vz_entry_on=str(cfg.entry_on),
        vz_zone_kinds=",".join(cfg.zone_kinds),
        vz_exit_name=str(cfg.exit_name),
        vz_exit_bars=int(cfg.exit_bars),
        vz_target_r=float(cfg.target_r),
        vz_stop_atr_buffer=float(cfg.stop_atr_buffer),
        vz_sheet_notional=float(cfg.sheet_notional),
    )
    if host_cfg is not None:
        try:
            return replace(host_cfg, **base_kw)
        except TypeError:
            pass
    return BRTConfig(**base_kw)


def vz_config_from_brt(cfg: Any) -> VzConfig:
    kinds = str(getattr(cfg, "vz_zone_kinds", "HL") or "HL")
    zone_kinds = tuple(x.strip() for x in kinds.split(",") if x.strip()) or ("HL",)
    return VzConfig(
        lookback_days=int(getattr(cfg, "vz_lookback_days", 126)),
        retest_window=int(getattr(cfg, "vz_retest_window", 63)),
        retest_eps_pct=float(getattr(cfg, "vz_retest_eps_pct", 0.005)),
        first_retest_only=bool(getattr(cfg, "vz_first_retest_only", True)),
        min_touches_before_entry=int(getattr(cfg, "vz_min_touches_before_entry", 1)),
        entry_on=str(getattr(cfg, "vz_entry_on", "next_open") or "next_open"),
        zone_kinds=zone_kinds,  # type: ignore[arg-type]
        exit_name=str(getattr(cfg, "vz_exit_name", "zone_atr05_ts40")),
        exit_bars=int(getattr(cfg, "vz_exit_bars", 40)),
        target_r=float(getattr(cfg, "vz_target_r", 2.0)),
        stop_atr_buffer=float(getattr(cfg, "vz_stop_atr_buffer", 0.5)),
        sheet_notional=float(getattr(cfg, "vz_sheet_notional", SHEET_NOTIONAL)),
        initial_capital=float(getattr(cfg, "initial_capital", DEFAULT_INITIAL_CAPITAL) or DEFAULT_INITIAL_CAPITAL),
        aggressive=bool(getattr(cfg, "aggressive", True)),
        max_positions=int(getattr(cfg, "max_positions", 0) or 0),
        aggressive_max_multiple=float(getattr(cfg, "aggressive_max_multiple", 2.0) or 2.0),
        margin_utilization=float(getattr(cfg, "margin_utilization", 0.6) or 0.6),
        brt_cash=float(getattr(cfg, "brt_cash", SHEET_NOTIONAL) or SHEET_NOTIONAL),
        write_stamp_folder=True,
    )


def _splice_vz_dna_columns(
    path: Path,
    dna_by_key: dict[tuple[str, str, str], dict[str, str]],
    dna_cols: tuple[str, ...],
) -> None:
    if not path.is_file():
        return
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    if not fieldnames:
        return
    for c in dna_cols:
        if c not in fieldnames:
            fieldnames.append(c)
    for row in rows:
        sym = str(row.get("SYMBOL", "") or "").strip().upper()
        opened = str(row.get("DATE_OPENED", "") or "").strip()
        closed = str(row.get("DATE_CLOSED", "") or "").strip()
        dna = dna_by_key.get((sym, opened, closed)) or {}
        for c in dna_cols:
            row[c] = dna.get(c, row.get(c, ""))
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _vz_dna_from_closed_row(r: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for c in _VZ_DNA_CLOSED_COLS:
        v = r.get(c, "")
        out[c] = "" if v is None else str(v)
    return out


def write_audit(path: Path, stamp: str, cfg: VzConfig, meta: dict[str, Any]) -> None:
    """Legacy KEY/VALUE stub - prefer write_outputs TBN wide Audit. Kept for callers."""
    del path, stamp, cfg, meta


def write_report(path: Path, stamp: str, cfg: VzConfig, meta: dict[str, Any]) -> None:
    """Human-readable companion txt (TBN also writes wide VZ_Report_*.csv)."""
    exit_spec: ExitSpec = meta["exit_spec"]
    params: SysParams = meta["params"]
    lines = [
        f"VZ Volume Zone report {stamp}",
        "STATUS=RESEARCH_CANDIDATE (not gold / not DailyRun)",
        "ENGINE=rocket_tbn vz_mode / rocket_vz (TBN Closed+Audit DNA)",
        f"freeze=RESEARCH_CANDIDATE_V2_RW63 exit={exit_spec.name}",
        f"lookback={params.lookback_days} rw={params.retest_window} eps={params.retest_eps_pct} "
        f"first_retest={params.first_retest_only} mt>={params.min_touches_before_entry} "
        f"zones={','.join(params.zone_kinds)} entry_on={params.entry_on}",
        "PREDICTIVE: signal bar uses Low/High/Close of that bar; fill=next_open (T+1 open) "
        "or close (same-bar close). Never signal-bar open.",
        f"exit: stop=zone.lo-{exit_spec.stop_atr_buffer}*ATR target={exit_spec.target_r}R "
        f"time_stop={exit_spec.exit_bars}d",
        f"symbols={meta.get('n_symbols')} ok={meta.get('n_ok')} skipped={meta.get('n_skipped')}",
        f"closed={meta.get('n_closed')} open={meta.get('n_open', 0)} WR={meta.get('win_rate'):.2f}% "
        f"AvgPnL%={meta.get('avg_pnl_pct'):.3f} AvgR={meta.get('avg_r'):.3f} "
        f"sheet_pnl=${meta.get('total_pnl'):,.2f} (notional ${cfg.sheet_notional:,.0f}/trade)",
        f"exit_mix={meta.get('exit_mix')}",
        f"IS: N={meta['is_m']['n_signals']} WR={meta['is_m']['win_rate']*100:.1f}% "
        f"AvgR={meta['is_m']['avg_r']:.2f}",
        f"OOS: N={meta['oos_m']['n_signals']} WR={meta['oos_m']['win_rate']*100:.1f}% "
        f"AvgR={meta['oos_m']['avg_r']:.2f} (report-only; do not retune)",
        f"elapsed_sec={meta.get('elapsed_sec'):.1f}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_run_html(
    path: Path,
    *,
    stamp: str,
    cfg: VzConfig,
    meta: dict[str, Any],
    universe_label: str,
) -> None:
    exit_spec: ExitSpec = meta["exit_spec"]
    params: SysParams = meta["params"]
    fm, im, om = meta["full_m"], meta["is_m"], meta["oos_m"]

    def row(label: str, m: dict) -> str:
        return (
            f"<tr><td>{html_mod.escape(label)}</td>"
            f"<td>{m['n_signals']}</td>"
            f"<td>{m['win_rate']*100:.1f}%</td>"
            f"<td>{m['avg_pnl_pct']:.2f}</td>"
            f"<td>{m['avg_r']:.3f}</td></tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>VZ Run Summary - {html_mod.escape(stamp)}</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:24px;max-width:960px;color:#1a1a1a;line-height:1.45}}
h1{{font-size:1.4rem;margin:0 0 .4em}}
.meta{{color:#64748b;font-size:13px}}
.bad{{background:#fef2f2;border-left:4px solid #ef4444;padding:10px 14px;margin:12px 0}}
.callout{{background:#eff6ff;border-left:4px solid #3b82f6;padding:10px 14px;margin:12px 0}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin:12px 0}}
th,td{{border:1px solid #cbd5e1;padding:6px 8px;text-align:left}}
thead{{background:#f1f5f9}}
code{{background:#f4f4f5;padding:1px 5px;border-radius:3px;font-size:12px}}
</style></head><body>
<h1>VZ - Volume Zone run summary</h1>
<p class="meta">Stamp <code>{html_mod.escape(stamp)}</code> · Universe <code>{html_mod.escape(universe_label)}</code></p>
<div class="bad"><strong>Research candidate only.</strong> Not production gold. Not DailyRun-wired.
Frozen knobs from <code>RESEARCH_CANDIDATE_V2_RW63</code> + <code>{html_mod.escape(exit_spec.name)}</code>.
OOS is report-only - do not retune.</div>
<div class="callout"><strong>Predictive timing:</strong> signal bar = retest known at close
(uses that bar Low/High/Close). Default fill <code>entry_on={html_mod.escape(str(params.entry_on))}</code>
- never buys the open of the signal morning.</div>
<table>
<thead><tr><th>Knob</th><th>Value</th></tr></thead>
<tbody>
<tr><td>lookback_days</td><td>{params.lookback_days}</td></tr>
<tr><td>retest_window</td><td>{params.retest_window}</td></tr>
<tr><td>retest_eps_pct</td><td>{params.retest_eps_pct}</td></tr>
<tr><td>first_retest_only</td><td>{params.first_retest_only}</td></tr>
<tr><td>min_touches_before_entry</td><td>{params.min_touches_before_entry}</td></tr>
<tr><td>zone_kinds</td><td>{html_mod.escape(','.join(params.zone_kinds))}</td></tr>
<tr><td>entry_on</td><td>{html_mod.escape(str(params.entry_on))}</td></tr>
<tr><td>exit</td><td>stop=zone.lo−{exit_spec.stop_atr_buffer}·ATR · {exit_spec.target_r}R · ts={exit_spec.exit_bars}d</td></tr>
<tr><td>sheet_notional</td><td>${cfg.sheet_notional:,.0f}/trade</td></tr>
<tr><td>TBN path</td><td>vz_mode -> write_brt_closed / write_brt_audit_report / compute_metrics</td></tr>
</tbody></table>
<table>
<thead><tr><th>Split</th><th>N</th><th>WR</th><th>Avg PnL%</th><th>AvgR</th></tr></thead>
<tbody>
{row("FULL", fm)}
{row("IS (&lt;2024)", im)}
{row("OOS (≥2024)", om)}
</tbody></table>
<p class="meta">Sheet PnL (FULL closed): ${meta.get('total_pnl'):,.2f} · open={meta.get('n_open', 0)} ·
exit_mix={html_mod.escape(str(meta.get('exit_mix')))} ·
elapsed {meta.get('elapsed_sec'):.1f}s · artifacts under <code>drive/VZ_*_{html_mod.escape(stamp)}.*</code>
· TIME = bars_held≥{exit_spec.exit_bars} only; as-of truncation → Open (still_open), not Closed TIME.</p>
<p class="meta">See also <a href="../VZ_System_Guide.html">VZ_System_Guide.html</a> ·
<a href="VZ_TBN_Integration_And_Predictive_Timing.html">VZ_TBN_Integration_And_Predictive_Timing.html</a> ·
<a href="tbn_new_systems/volume_zone/HOW_TO_RUN.md">HOW_TO_RUN.md</a></p>
</body></html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def write_baseline_md(path: Path, *, stamp: str, universe_label: str, n_symbols: int, cfg: VzConfig) -> None:
    md = f"""# VZ run stamp - RESEARCH (not gold)

**Stamp:** `{stamp}`  
**Status:** Research sleeve via `run_vz.bat` -> `rocket_tbn -v vz_mode=true` / `rocket_vz.py` - **not** production gold, **not** DailyRun-wired.

## Freeze (default knobs - do not retune on OOS)

| Knob | Value |
|------|-------|
| lookback_days | {cfg.lookback_days} |
| zone_kinds | HL only |
| first_retest_only | {cfg.first_retest_only} |
| min_touches_before_entry | {cfg.min_touches_before_entry} |
| retest_eps_pct | {cfg.retest_eps_pct} |
| retest_window | {cfg.retest_window} |
| entry_on | {cfg.entry_on} (house default next_open; prior AB freeze used close) |
| Primary exit | `{cfg.exit_name}` (stop = zone.lo − {cfg.stop_atr_buffer}·ATR; target {cfg.target_r}R; time stop {cfg.exit_bars}d) |

## Predictive timing

Signal bar T: retest known from T's Low/High/Close (end of day).  
Fill: next open (T+1) by default, or T close. **Forbidden:** buy T open using T's range.

## Universe

- Label: `{universe_label}`
- Symbols requested: {n_symbols}
- Default research univ: `drive/universes/VZ_universe.csv` (DualPaul78 83-name set)

## Chronologic split

IS = entry_date < 2024-01-01; OOS = entry_date >= 2024-01-01. OOS report-only.

## Sheet PnL

Fixed notional **${cfg.sheet_notional:,.0f}** per trade.

## Outputs

House `drive/VZ_*_{stamp}.*` (TBN wide Audit/Closed) plus this stamp folder.
"""
    path.write_text(md, encoding="utf-8")


def _ensure_ohlc_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    """BRT open MTM expects DatetimeIndex; VZ/TBN frames often keep a Date column."""
    if df is None or getattr(df, "empty", True):
        return df
    if isinstance(df.index, pd.DatetimeIndex):
        return df
    if "Date" in getattr(df, "columns", []):
        out = df.copy()
        out.index = pd.to_datetime(out["Date"], errors="coerce")
        return out
    try:
        idx = pd.to_datetime(df.index, errors="coerce")
        if bool(getattr(idx, "notna", lambda: pd.Series(dtype=bool))().any()):
            out = df.copy()
            out.index = idx
            return out
    except Exception:
        pass
    return df


def write_outputs(
    output_dir: Path,
    stamp: str,
    cfg: VzConfig,
    closed: list[dict[str, Any]],
    meta: dict[str, Any],
    *,
    opens: Optional[list[dict[str, Any]]] = None,
    universe_label: str,
    tickers: Optional[dict[str, pd.DataFrame]] = None,
    host_cfg: Any = None,
    drive_link: str = "",
    no_yfinance: bool = False,
    data_dir: Optional[Path] = None,
) -> dict[str, Path]:
    """Write VZ_* via BRT Closed/Open/Audit/Report writers (RS/SB parity)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    opens = list(opens or [])
    paths: dict[str, Path] = {}
    closed_path = output_dir / f"{FILE_PREFIX}_Closed_{stamp}.csv"
    open_path = output_dir / f"{FILE_PREFIX}_Open_{stamp}.csv"
    summary_path = output_dir / f"{FILE_PREFIX}_Summary_{stamp}.csv"
    watch_path = output_dir / f"{FILE_PREFIX}_Watchlist_{stamp}.csv"
    report_txt_path = output_dir / f"{FILE_PREFIX}_Report_{stamp}.txt"
    audit_path = output_dir / f"{FILE_PREFIX}_Audit_Report_{stamp}.csv"
    equity_path = output_dir / f"{FILE_PREFIX}_EquityCurve_{stamp}.csv"
    equity_meta_path = output_dir / f"{FILE_PREFIX}_EquityMeta_{stamp}.csv"
    corr_path = output_dir / f"{FILE_PREFIX}_Correlation_{stamp}.csv"

    try:
        from rocket_tbn import (
            compute_metrics,
            write_brt_closed,
            write_brt_open,
            write_brt_report,
            write_brt_audit_report,
            _enrich_trades_yfinance,
            _enrich_post_entry_gain_hit,
            _enrich_trades_ohlc_features,
            _enrich_trades_entry_indicators,
        )
    except ImportError:
        from stock_analysis.rocket_tbn import (  # type: ignore
            compute_metrics,
            write_brt_closed,
            write_brt_open,
            write_brt_report,
            write_brt_audit_report,
            _enrich_trades_yfinance,
            _enrich_post_entry_gain_hit,
            _enrich_trades_ohlc_features,
            _enrich_trades_entry_indicators,
        )

    report_cfg = brt_config_from_vz(cfg, host_cfg=host_cfg)
    brt_closed = [vz_closed_to_brt_trade(r) for r in closed]
    brt_open = [vz_closed_to_brt_trade(r) for r in opens]
    tickers_mtm = {
        str(k).upper(): _ensure_ohlc_datetime_index(v)
        for k, v in (tickers or {}).items()
        if v is not None
    }

    try:
        _enrich_trades_ohlc_features(
            brt_closed + brt_open,
            tickers_mtm,
            report_cfg,
            data_dir=data_dir,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[VZ] OHLC feature enrich skipped: {e}", flush=True)
    try:
        _enrich_trades_entry_indicators(brt_closed + brt_open, tickers_mtm, report_cfg)
    except Exception as e:  # noqa: BLE001
        print(f"[VZ] entry_indicators enrich skipped: {e}", flush=True)
    if not no_yfinance and (brt_closed or brt_open):
        try:
            _enrich_trades_yfinance(brt_closed, brt_open)
        except Exception as e:  # noqa: BLE001
            print(f"[VZ] yfinance enrich skipped: {e}", flush=True)
    try:
        _enrich_post_entry_gain_hit(brt_closed + brt_open, tickers_mtm, report_cfg)
    except Exception as e:  # noqa: BLE001
        print(f"[VZ] post_entry enrich skipped: {e}", flush=True)

    write_brt_closed(brt_closed, str(closed_path), cfg=report_cfg)
    _splice_vz_dna_columns(
        closed_path,
        {
            (str(r["SYMBOL"]).upper(), str(r["DATE_OPENED"]), str(r["DATE_CLOSED"])): _vz_dna_from_closed_row(r)
            for r in closed
        },
        _VZ_DNA_CLOSED_COLS,
    )
    write_brt_open(
        brt_open,
        str(open_path),
        tickers=tickers_mtm,
        brt_cash=float(cfg.brt_cash or cfg.sheet_notional),
        closed=brt_closed,
        cfg=report_cfg,
    )
    with watch_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(WATCH_HEADER)
        for r in opens:
            w.writerow(
                [
                    str(r.get("SYMBOL", "")).upper(),
                    str(r.get("ASOF_DATE", "") or ""),
                    str(r.get("ZONE_ID", "") or ""),
                    str(r.get("ZONE_KIND", "") or ""),
                    r.get("ZONE_LO", ""),
                    r.get("ZONE_HI", ""),
                    (
                        f"OPEN position as-of last bar; bars_held={r.get('DAYS_HELD', '')}/"
                        f"{cfg.exit_bars}; not a TIME exit"
                    ),
                ]
            )

    # Summary (ALL + by symbol) - keep house shape + peer fields when enriched
    by_sym: dict[str, list[dict[str, Any]]] = {}
    for r in closed:
        by_sym.setdefault(str(r["SYMBOL"]), []).append(r)
    with summary_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "SYMBOL",
                "N_TRADES",
                "WIN_RATE_PCT",
                "TOTAL_PNL",
                "AVG_PNL_PCT",
                "AVG_R",
                "AVG_DAYS_HELD",
            ]
        )
        for sym in sorted(by_sym):
            rows = by_sym[sym]
            wins = sum(1 for r in rows if float(r["PNL_PCT"]) > 0)
            w.writerow(
                [
                    sym,
                    len(rows),
                    f"{100.0 * wins / len(rows):.2f}",
                    f"{sum(float(r['PNL_DOLLARS']) for r in rows):.2f}",
                    f"{float(np.mean([float(r['PNL_PCT']) for r in rows])):.4f}",
                    f"{float(np.mean([float(r['R_MULT']) for r in rows])):.4f}",
                    f"{float(np.mean([float(r['DAYS_HELD']) for r in rows])):.2f}",
                ]
            )
        if closed:
            wins = sum(1 for r in closed if float(r["PNL_PCT"]) > 0)
            w.writerow(
                [
                    "ALL",
                    len(closed),
                    f"{100.0 * wins / len(closed):.2f}",
                    f"{sum(float(r['PNL_DOLLARS']) for r in closed):.2f}",
                    f"{float(np.mean([float(r['PNL_PCT']) for r in closed])):.4f}",
                    f"{float(np.mean([float(r['R_MULT']) for r in closed])):.4f}",
                    f"{float(np.mean([float(r['DAYS_HELD']) for r in closed])):.2f}",
                ]
            )
    paths["summary"] = summary_path
    write_report(report_txt_path, stamp, cfg, meta)
    paths["report_txt"] = report_txt_path

    # Equity: prefer host DrawdownCalc path when tickers available; else realized ledger
    host_equity_written = False
    if tickers and (cfg.aggressive or bool(meta.get("use_host_equity"))):
        try:
            from tbn_host_sizing import HostSizingConfig, compute_and_write_host_equity
        except ImportError:
            from stock_analysis.tbn_host_sizing import (  # type: ignore
                HostSizingConfig,
                compute_and_write_host_equity,
            )

        # Host equity expects objects with symbol/date_opened/… - use Burst-like duck typing via BRTTrade
        class _EqRow:
            __slots__ = (
                "symbol",
                "date_opened",
                "date_closed",
                "entry_price",
                "exit_price",
                "pnl_dollars",
                "days_held",
                "stop_price",
                "target_price",
            )

            def __init__(self, r: dict[str, Any]) -> None:
                self.symbol = str(r["SYMBOL"]).upper()
                self.date_opened = str(r["DATE_OPENED"])
                self.date_closed = str(r["DATE_CLOSED"])
                self.entry_price = float(r["ENTRY_PRICE"])
                self.exit_price = float(r["EXIT_PRICE"])
                self.pnl_dollars = float(r["PNL_DOLLARS"])
                self.days_held = int(r["DAYS_HELD"])
                self.stop_price = float(r["STOP_PRICE"])
                self.target_price = float(r["TARGET_PRICE"])

        sizing_cfg = HostSizingConfig(
            brt_cash=float(cfg.brt_cash or cfg.sheet_notional),
            initial_capital=float(cfg.initial_capital),
            aggressive_max_multiple=float(cfg.aggressive_max_multiple),
            margin_utilization=float(cfg.margin_utilization),
            max_positions=int(cfg.max_positions),
            aggressive=bool(cfg.aggressive),
            aggressive_margin_interest=0.0,
            aggressive_avg_positions=0.0,
            aggressive_sizing_equity_cap=0.0,
        )
        equity = compute_and_write_host_equity(
            output_dir=output_dir,
            ts=stamp,
            file_prefix=FILE_PREFIX,
            closed=[_EqRow(r) for r in closed],
            open_trades=[],
            tickers=tickers,
            cfg=sizing_cfg,
        )
        if equity:
            host_equity_written = True
            md = equity.get("Max_Drawdown", "")
            meta["max_dd_pct"] = md
            if equity.get("_aggressive"):
                meta["aggressive_total_pnl"] = f"{float(equity.get('_equity_total_pnl', 0) or 0):.2f}"
                meta["aggressive_max_dd"] = equity.get("Aggressive_Max_Drawdown", "")
                meta["aggressive_avg_positions"] = equity.get("Aggressive_Avg_Positions", 0)
            agg_path = output_dir / f"{FILE_PREFIX}_EquityCurve_Aggressive_{stamp}.csv"
            if agg_path.exists():
                paths["equity_aggressive"] = agg_path
            if equity_path.exists():
                paths["equity"] = equity_path
            if equity_meta_path.exists():
                paths["equity_meta"] = equity_meta_path

    if not host_equity_written:
        write_equity(
            equity_path,
            equity_meta_path,
            closed,
            initial_cash=cfg.initial_capital,
            aggressive=cfg.aggressive,
        )
        paths["equity"] = equity_path
        paths["equity_meta"] = equity_meta_path
        if cfg.aggressive:
            agg = output_dir / f"{FILE_PREFIX}_EquityCurve_Aggressive_{stamp}.csv"
            shutil.copy2(equity_path, agg)
            paths["equity_aggressive"] = agg

    metrics = compute_metrics(brt_closed, report_cfg)
    if meta.get("max_dd_pct") not in (None, ""):
        metrics["Max_Drawdown"] = meta.get("max_dd_pct")
    if meta.get("aggressive_total_pnl") not in (None, ""):
        metrics["Aggressive_Total_PNL"] = meta.get("aggressive_total_pnl")
    if meta.get("aggressive_max_dd") not in (None, ""):
        metrics["Aggressive_Max_Drawdown"] = meta.get("aggressive_max_dd")
    if meta.get("aggressive_avg_positions") not in (None, ""):
        metrics["Aggressive_Avg_Positions"] = meta.get("aggressive_avg_positions")

    write_brt_report(
        report_cfg,
        metrics,
        str(output_dir),
        stamp,
        drive_link=drive_link,
        file_prefix=FILE_PREFIX,
    )
    write_brt_audit_report(
        report_cfg,
        metrics,
        str(output_dir),
        stamp,
        drive_link=drive_link,
        file_prefix=FILE_PREFIX,
    )
    written_audit = output_dir / f"{FILE_PREFIX}_Audit_Report_{stamp}.csv"
    if written_audit.exists():
        paths["audit"] = written_audit
        if written_audit.resolve() != audit_path.resolve():
            audit_path.write_bytes(written_audit.read_bytes())
    written_report = output_dir / f"{FILE_PREFIX}_Report_{stamp}.csv"
    if written_report.exists():
        paths["report"] = written_report

    # Paul-score Summary Symbols
    signals_df = pd.DataFrame(meta.get("signal_rows") or [])
    per_df = pd.DataFrame(meta.get("per_symbol") or [])
    if not signals_df.empty or not per_df.empty:
        sum_rows, fieldnames, paul_diag = build_summary_rows(signals_df, per_df)
        sym_sum_path = output_dir / f"{FILE_PREFIX}_Summary_Symbols_{stamp}.csv"
        write_summary_csv(sym_sum_path, sum_rows, fieldnames)
        paths["summary_symbols"] = sym_sum_path
        html_sum = output_dir / f"{FILE_PREFIX}_Symbol_Summary_{stamp}.html"
        write_summary_html(
            html_sum,
            stamp=stamp,
            rows=sum_rows,
            paul_diag=paul_diag,
            csv_name=sym_sum_path.name,
            proposed_csv_name=f"{FILE_PREFIX}_Proposed_GoldSet_{stamp}.csv",
        )
        paths["summary_html"] = html_sum

    try:
        try:
            from correlate_brt_closed import run_correlation_report
        except ImportError:
            from stock_analysis.correlate_brt_closed import run_correlation_report  # type: ignore
        run_correlation_report(str(closed_path), str(corr_path))
        paths["correlation"] = corr_path
        pairs = corr_path.with_name(corr_path.name.replace("_Correlation_", "_Correlation_Pairs_", 1))
        if pairs.is_file():
            paths["correlation_pairs"] = pairs
    except Exception as e:  # noqa: BLE001
        print(f"[VZ] WARN correlation skipped: {e}", flush=True)

    try:
        try:
            from rocket_post_analysis import write_analysis_artifacts
        except ImportError:
            from stock_analysis.rocket_post_analysis import write_analysis_artifacts  # type: ignore
        write_analysis_artifacts(
            cfg=report_cfg,
            tickers=tickers or {},
            output_dir=output_dir,
            ts=stamp,
            closed_path=closed_path,
            summary_path=summary_path,
            open_path=open_path,
            prefix=FILE_PREFIX,
            no_yfinance=bool(no_yfinance),
        )
    except Exception as e:  # noqa: BLE001
        print(f"[VZ] analysis artifacts skipped: {e}", flush=True)

    timings_path = output_dir / f"{FILE_PREFIX}_Pipeline_Timings_{stamp}.csv"
    with timings_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["SYMBOL", "ELAPSED_SEC", "N_TRADES"])
        for sym, sec, n in meta.get("per_symbol_sec") or []:
            w.writerow([sym, f"{sec:.4f}", n])
        w.writerow(["ALL", f"{meta.get('elapsed_sec'):.4f}", meta.get("n_closed")])
    paths["timings"] = timings_path

    ckpt = output_dir / f"{FILE_PREFIX}_checkpoint_{stamp}.pkl"
    with ckpt.open("wb") as f:
        pickle.dump(
            {
                "stamp": stamp,
                "cfg": cfg,
                "params": meta.get("params"),
                "exit_spec": meta.get("exit_spec"),
                "signal_rows": meta.get("signal_rows"),
                "per_symbol": meta.get("per_symbol"),
                "closed": closed,
                "opens": opens,
                "full_m": meta.get("full_m"),
                "is_m": meta.get("is_m"),
                "oos_m": meta.get("oos_m"),
                "tbn_integrated": True,
            },
            f,
            protocol=pickle.HIGHEST_PROTOCOL,
        )
    paths["checkpoint"] = ckpt

    run_html = output_dir / f"{FILE_PREFIX}_Run_Summary_{stamp}.html"
    write_run_html(run_html, stamp=stamp, cfg=cfg, meta=meta, universe_label=universe_label)
    paths["run_html"] = run_html

    if cfg.write_stamp_folder:
        stamp_dir = STAMP_ROOT / f"vz_run_{stamp}"
        stamp_dir.mkdir(parents=True, exist_ok=True)
        write_baseline_md(
            stamp_dir / "BASELINE.md",
            stamp=stamp,
            universe_label=universe_label,
            n_symbols=int(meta.get("n_symbols") or 0),
            cfg=cfg,
        )
        if meta.get("signal_rows") is not None:
            pd.DataFrame(meta["signal_rows"]).to_csv(stamp_dir / "signals_rw63.csv", index=False)
        if meta.get("per_symbol") is not None:
            pd.DataFrame(meta["per_symbol"]).to_csv(stamp_dir / "per_symbol_rw63.csv", index=False)
        shutil.copy2(run_html, stamp_dir / "VZ_Run_Summary.html")
        if "summary_html" in paths:
            shutil.copy2(paths["summary_html"], stamp_dir / "VolZone_Symbol_Summary.html")
        if "summary_symbols" in paths:
            shutil.copy2(paths["summary_symbols"], stamp_dir / paths["summary_symbols"].name)
        if "audit" in paths:
            shutil.copy2(paths["audit"], stamp_dir / paths["audit"].name)
        paths["stamp_dir"] = stamp_dir

    for label, src in [
        ("Closed", closed_path),
        ("Open", open_path),
        ("Summary", summary_path),
        ("Watchlist", watch_path),
        ("Audit_Report", paths.get("audit", audit_path)),
        ("EquityCurve", paths.get("equity", equity_path)),
    ]:
        if src is None or not Path(src).exists():
            continue
        dst = output_dir / f"{FILE_PREFIX}_LatestRun_{label}.csv"
        shutil.copy2(src, dst)
        paths[f"latest_{label}"] = dst
    if "summary_symbols" in paths:
        shutil.copy2(
            paths["summary_symbols"],
            output_dir / f"{FILE_PREFIX}_LatestRun_Summary_Symbols.csv",
        )
    if "correlation" in paths:
        shutil.copy2(paths["correlation"], output_dir / f"{FILE_PREFIX}_LatestRun_Correlation.csv")
    shutil.copy2(run_html, output_dir / f"{FILE_PREFIX}_LatestRun_Run_Summary.html")
    (output_dir / f"{FILE_PREFIX}_last_run_ts.txt").write_text(stamp + "\n", encoding="utf-8")
    (output_dir / "last_run_ts.txt").write_text(stamp, encoding="utf-8")
    paths["closed"] = closed_path
    paths["open"] = open_path
    paths["watchlist"] = watch_path
    paths["last_run_ts"] = output_dir / f"{FILE_PREFIX}_last_run_ts.txt"
    return paths


def run_vz_from_brt_main(
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
    """TBN host entry (``vz_mode=true``) - VZ DNA + BRT writers / unified Audit."""
    vcfg = vz_config_from_brt(cfg)
    symbols: list[str] = []
    loaded: dict[str, pd.DataFrame] = {}
    for sym in ticker_list:
        df = tickers.get(sym) if tickers else None
        if df is None or (hasattr(df, "empty") and df.empty):
            if load_symbol_fn is not None:
                try:
                    df = load_symbol_fn(sym, data_dir)
                except Exception as e:  # noqa: BLE001
                    print(f"[VZ] skip {sym}: load failed ({e})", flush=True)
                    continue
        if df is None or len(df) < int(vcfg.lookback_days) + 5:
            print(
                f"[VZ] skip {sym}: insufficient bars ({0 if df is None else len(df)})",
                flush=True,
            )
            continue
        symbols.append(sym)
        loaded[sym] = df

    print(
        f"[VZ] Volume Zone on {len(symbols)} symbols "
        f"(lookback={vcfg.lookback_days} rw={vcfg.retest_window} "
        f"entry_on={vcfg.entry_on} exit={vcfg.exit_name})",
        flush=True,
    )
    print(
        "[VZ] Predictive: signal at retest-bar close; fill next_open (default) or close - "
        "never signal-bar open",
        flush=True,
    )

    closed, opens, _per, meta = run_backtest(
        symbols, data_dir, vcfg, workers=int(workers or 0)
    )
    meta["use_host_equity"] = True
    # Prefer already-loaded frames for equity / enrich (Date column or DatetimeIndex)
    for sym, df in list(loaded.items()):
        if "Date" not in getattr(df, "columns", []):
            try:
                if isinstance(df.index, pd.DatetimeIndex):
                    d2 = df.reset_index()
                    if "Date" not in d2.columns and len(d2.columns):
                        d2 = d2.rename(columns={d2.columns[0]: "Date"})
                    loaded[sym] = d2
            except Exception:
                pass

    paths = write_outputs(
        Path(output_dir),
        ts,
        vcfg,
        closed,
        meta,
        opens=opens,
        universe_label=f"tbn vz_mode ({len(symbols)} sym)",
        tickers=loaded,
        host_cfg=cfg,
        drive_link=drive_link,
        no_yfinance=bool(no_yfinance),
        data_dir=Path(data_dir),
    )
    print(
        f"[VZ] Done closed={meta['n_closed']} open={meta.get('n_open', 0)} "
        f"WR={meta['win_rate']:.1f}% "
        f"sheet_pnl=${meta['total_pnl']:,.2f} -> {paths.get('closed')}",
        flush=True,
    )
    if "audit" in paths:
        print(f"[VZ] Audit {paths['audit']}", flush=True)
    return 0




def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="VZ Volume Zone research sleeve (VZ_* house artifacts)"
    )
    p.add_argument("data_dir", nargs="?", default=str(DEFAULT_DATA_DIR))
    p.add_argument("-o", "--output-dir", default=str(DEFAULT_OUT_DIR))
    p.add_argument("-s", "--symbols", default="", help="Comma list, or * / ALL for full scan")
    p.add_argument("--universe", type=Path, default=None, help="Universe CSV (one ticker/line)")
    p.add_argument("--stamp", default="")
    p.add_argument("--lookback-days", type=int, default=126)
    p.add_argument("--retest-window", type=int, default=63)
    p.add_argument("--retest-eps-pct", type=float, default=0.005)
    p.add_argument("--first-retest-only", type=_as_bool, default=True)
    p.add_argument("--min-touches", type=int, default=1)
    p.add_argument("--entry-on", default="next_open", choices=["close", "next_open"])
    p.add_argument("--exit-name", default="zone_atr05_ts40")
    p.add_argument("--exit-bars", type=int, default=40)
    p.add_argument("--target-r", type=float, default=2.0)
    p.add_argument("--stop-atr-buffer", type=float, default=0.5)
    p.add_argument("--sheet-notional", type=float, default=SHEET_NOTIONAL)
    p.add_argument("--initial-capital", type=float, default=DEFAULT_INITIAL_CAPITAL)
    p.add_argument("--aggressive", action="store_true", default=True)
    p.add_argument("--no-aggressive", action="store_true")
    p.add_argument("--no-stamp-folder", action="store_true")
    p.add_argument(
        "-w",
        "--workers",
        type=int,
        default=0,
        help="Parallel symbol workers (0=sequential, N=ProcessPool, -1=auto min(8,CPUs))",
    )
    p.add_argument(
        "-v",
        "--set",
        action="append",
        default=[],
        help="Override KEY=VALUE (lookback_days, retest_window, …)",
    )
    return p


def _apply_v_overrides(cfg: VzConfig, sets: list[str]) -> VzConfig:
    for item in sets or []:
        if "=" not in item:
            continue
        k, v = item.split("=", 1)
        k = k.strip()
        v = v.strip()
        if not hasattr(cfg, k):
            # aliases
            aliases = {
                "min_touches_before_entry": "min_touches_before_entry",
                "min_touches": "min_touches_before_entry",
            }
            k2 = aliases.get(k, k)
            if not hasattr(cfg, k2):
                print(f"[VZ] WARN unknown -v key: {k}", flush=True)
                continue
            k = k2
        cur = getattr(cfg, k)
        if isinstance(cur, bool):
            setattr(cfg, k, _as_bool(v))
        elif isinstance(cur, int):
            setattr(cfg, k, int(float(v)))
        elif isinstance(cur, float):
            setattr(cfg, k, float(v))
        elif isinstance(cur, tuple):
            setattr(cfg, k, tuple(x.strip() for x in v.split(",") if x.strip()))
        else:
            setattr(cfg, k, v)
    return cfg


def cfg_from_args(ns: argparse.Namespace) -> VzConfig:
    cfg = VzConfig(
        lookback_days=int(ns.lookback_days),
        retest_window=int(ns.retest_window),
        retest_eps_pct=float(ns.retest_eps_pct),
        first_retest_only=_as_bool(ns.first_retest_only),
        min_touches_before_entry=int(ns.min_touches),
        entry_on=str(ns.entry_on),
        exit_name=str(ns.exit_name),
        exit_bars=int(ns.exit_bars),
        target_r=float(ns.target_r),
        stop_atr_buffer=float(ns.stop_atr_buffer),
        sheet_notional=float(ns.sheet_notional),
        initial_capital=float(ns.initial_capital),
        aggressive=not bool(ns.no_aggressive),
        write_stamp_folder=not bool(ns.no_stamp_folder),
    )
    return _apply_v_overrides(cfg, list(ns.set or []))


def main(argv: Optional[list[str]] = None) -> int:
    ns = build_arg_parser().parse_args(argv)
    data_dir = Path(ns.data_dir)
    out_dir = Path(ns.output_dir)
    cfg = cfg_from_args(ns)

    universe_label = ""
    if ns.universe is not None:
        symbols = load_universe_symbols(Path(ns.universe))
        universe_label = str(Path(ns.universe))
    elif (ns.symbols or "").strip():
        symbols = resolve_symbols(ns.symbols, data_dir)
        universe_label = f"-s {ns.symbols}"
    elif DEFAULT_UNIVERSE.is_file():
        symbols = load_universe_symbols(DEFAULT_UNIVERSE)
        universe_label = str(DEFAULT_UNIVERSE)
    else:
        symbols = list_data_dir_symbols(data_dir)
        universe_label = "ALL (no VZ_universe.csv)"

    stamp = (ns.stamp or "").strip() or datetime.now().strftime("%y%m%d%H%M%S")
    n_workers = _resolve_vz_workers(int(getattr(ns, "workers", 0) or 0))
    print(
        f"[VZ] RESEARCH sleeve - {len(symbols)} symbols freeze=rw{cfg.retest_window} "
        f"exit={cfg.exit_name} workers={n_workers} stamp={stamp}",
        flush=True,
    )
    print(f"[VZ] universe={universe_label}", flush=True)

    closed, opens, _per, meta = run_backtest(
        symbols, data_dir, cfg, workers=int(getattr(ns, "workers", 0) or 0)
    )
    paths = write_outputs(
        out_dir, stamp, cfg, closed, meta, opens=opens, universe_label=universe_label
    )
    print(
        f"[VZ] Done closed={meta['n_closed']} open={meta.get('n_open', 0)} "
        f"WR={meta['win_rate']:.1f}% "
        f"sheet_pnl=${meta['total_pnl']:,.2f} -> {paths.get('closed')}",
        flush=True,
    )
    if "run_html" in paths:
        print(f"[VZ] HTML {paths['run_html']}", flush=True)
    if "stamp_dir" in paths:
        print(f"[VZ] stamp {paths['stamp_dir']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
