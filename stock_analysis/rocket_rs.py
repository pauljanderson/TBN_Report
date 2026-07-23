#!/usr/bin/env python3
"""RS (Relative Strength) engine: SPY_COMPARE 1Y/2Y/3Y > 0 AND all IND_TC_* Strong.

Entry = next open after signal close (BRT scan convention).
Exits: target_pct / stop_pct as entry multipliers (default 1.25 / 0.88).
No zones / trailing. One position at a time per symbol.

Outputs (under -o, default drive/):
  RS_Closed_<ts>.csv
  RS_Open_<ts>.csv
  RS_Scanner_<ts>.csv   (signal on last bar → buy next open; empty file if none)
  RS_Summary_<ts>.csv

DailyRun / standalone: run_rs.bat
Experiment harness (kept): tools/run_spy_tc_strong_system.py
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

_SA = Path(__file__).resolve().parent
_REPO = _SA.parent
if str(_SA) not in sys.path:
    sys.path.insert(0, str(_SA))
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from brt_entry_indicators import (  # noqa: E402
    _ensure_gate_arrays,
    _tc_outlook_label,
    build_entry_indicator_precompute,
    resolve_indicator_cache_dir,
)
from rocket_brt import (  # noqa: E402
    _RS_SPY_LAG_3Y,
    _align_stock_spy_close_for_rs,
    _rs_excess_pct_points,
    _rs_pass_all_horizons_vs_spy,
    load_csv,
)

FILE_PREFIX = "RS"
DEFAULT_TARGET_PCT = 1.25
DEFAULT_STOP_PCT = 0.88
INITIAL_CAPITAL = 1_000_000.0
MAX_POSITIONS = 10

# Curated production universe (also set in run_rs.bat as RS_SYMBOLS).
DEFAULT_SYMBOLS = [
    "TRV", "WELL", "CTAS", "CASY", "AFL", "BDX", "CW", "CB", "BSX", "CPRT",
    "AJG", "HWM", "NVDA", "TJX", "FISV", "PRI", "MCD", "ATEYY", "MCK", "POOL",
    "FICO", "V", "QQQ", "ENSG", "DHR", "UNH", "DECK", "RELX", "RBC", "ORLY",
    "MSCI", "ROP", "CAH", "ADBE", "BRO", "MCO", "COST", "NFLX", "BBIO", "POWL",
    "BR", "LOGI", "TMO", "FIX", "AER", "CHTR", "PGR", "LII", "EME", "TDY",
    "ETR", "AXSM", "SYK", "AVGO", "WST",
]


@dataclass
class Trade:
    SYMBOL: str
    SIDE: str
    DATE_SIGNAL: str
    DATE_OPENED: str
    ENTRY_PRICE: float
    STOP_PRICE: float
    TARGET_PRICE: float
    DATE_CLOSED: str
    EXIT_PRICE: float
    EXIT_TYPE: str
    DAYS_HELD: int
    PNL_PCT: float
    PNL_DOLLARS: float
    SPY_COMPARE_1Y: float
    SPY_COMPARE_2Y: float
    SPY_COMPARE_3Y: float
    IND_TC_SHORT_OUTLOOK: str
    IND_TC_INT_OUTLOOK: str
    IND_TC_LONG_OUTLOOK: str


@dataclass
class OpenTrade:
    SYMBOL: str
    SIDE: str
    DATE_SIGNAL: str
    DATE_OPENED: str
    ENTRY_PRICE: float
    STOP_PRICE: float
    TARGET_PRICE: float
    CURRENT_PRICE: float
    DAYS_HELD: int
    PNL_PCT: float
    PNL_DOLLARS: float
    SPY_COMPARE_1Y: float
    SPY_COMPARE_2Y: float
    SPY_COMPARE_3Y: float
    IND_TC_SHORT_OUTLOOK: str
    IND_TC_INT_OUTLOOK: str
    IND_TC_LONG_OUTLOOK: str


def _iso(d: Any) -> str:
    if hasattr(d, "strftime"):
        return d.strftime("%Y-%m-%d")
    return str(d)[:10]


def _exit_long(
    *,
    entry: float,
    stop: float,
    target: float,
    op: float,
    hi: float,
    lo: float,
) -> tuple[Optional[str], Optional[float]]:
    """Same-bar priority: gap stop → gap target → intraday stop → intraday target."""
    if op <= stop:
        return "STOP", float(op)
    if op >= target:
        return "TARGET", float(op)
    if lo <= stop:
        return "STOP", float(stop)
    if hi >= target:
        return "TARGET", float(target)
    return None, None


def _signal_at(
    t: int,
    *,
    tc_ok: np.ndarray,
    st: np.ndarray,
    sp: np.ndarray,
    pre: Any,
) -> Optional[dict[str, Any]]:
    if not bool(tc_ok[t]):
        return None
    if not _rs_pass_all_horizons_vs_spy(st, sp, t):
        return None
    e1, e2, e3 = _rs_excess_pct_points(st, sp, t)
    if e1 is None or e2 is None or e3 is None:
        return None
    if not (e1 > 0 and e2 > 0 and e3 > 0):
        return None
    return {
        "SPY_COMPARE_1Y": float(e1),
        "SPY_COMPARE_2Y": float(e2),
        "SPY_COMPARE_3Y": float(e3),
        "IND_TC_SHORT_OUTLOOK": _tc_outlook_label(int(pre.tc_short_sum[t])),
        "IND_TC_INT_OUTLOOK": _tc_outlook_label(int(pre.tc_int_sum[t])),
        "IND_TC_LONG_OUTLOOK": _tc_outlook_label(int(pre.tc_long_sum[t])),
    }


def backtest_symbol(
    sym: str,
    df: pd.DataFrame,
    spy_df: pd.DataFrame,
    *,
    notional: float,
    data_dir: Path,
    target_pct: float = DEFAULT_TARGET_PCT,
    stop_pct: float = DEFAULT_STOP_PCT,
    liquidate_at_end: bool = False,
    use_indicators: bool = True,
) -> tuple[list[Trade], Optional[OpenTrade], Optional[dict[str, Any]]]:
    """Return (closed, open_or_none, scanner_row_or_none).

    Scanner = signal on last bar with no open position (buy next session open).
    """
    if not use_indicators:
        print(f"[SKIP] {sym}: use_indicators=false (TC required for RS)", flush=True)
        return [], None, None

    aligned = _align_stock_spy_close_for_rs(df, spy_df)
    if aligned is None:
        return [], None, None
    st, sp = aligned
    n = len(df)
    if n < _RS_SPY_LAG_3Y + 2:
        return [], None, None

    pre = build_entry_indicator_precompute(
        df,
        symbol=sym,
        cache_dir=resolve_indicator_cache_dir(None, data_dir=data_dir),
        use_cache=True,
    )
    if pre is None:
        print(f"[WARN] {sym}: indicator precompute unavailable", flush=True)
        return [], None, None
    pre = _ensure_gate_arrays(pre)
    if pre.tc_short_sum is None or pre.tc_int_sum is None or pre.tc_long_sum is None:
        print(f"[WARN] {sym}: TC outlook arrays missing", flush=True)
        return [], None, None
    tc_ok = (
        (pre.tc_short_sum > 0)
        & (pre.tc_int_sum > 0)
        & (pre.tc_long_sum > 0)
    )

    open_arr = df["Open"].to_numpy(dtype=np.float64)
    high_arr = df["High"].to_numpy(dtype=np.float64)
    low_arr = df["Low"].to_numpy(dtype=np.float64)
    close_arr = df["Close"].to_numpy(dtype=np.float64)
    dates = df.index

    trades: list[Trade] = []
    open_trade: Optional[OpenTrade] = None
    search_from = _RS_SPY_LAG_3Y

    while search_from <= n - 2:
        signal_t = -1
        meta: dict[str, Any] = {}
        for t in range(search_from, n - 1):
            hit = _signal_at(t, tc_ok=tc_ok, st=st, sp=sp, pre=pre)
            if hit is None:
                continue
            signal_t = t
            meta = hit
            break
        if signal_t < 0:
            break

        entry_bar = signal_t + 1
        entry = float(open_arr[entry_bar])
        if not np.isfinite(entry) or entry <= 0:
            search_from = signal_t + 1
            continue
        stop = entry * stop_pct
        target = entry * target_pct
        exit_type: Optional[str] = None
        exit_px: Optional[float] = None
        exit_bar = -1
        for i in range(entry_bar + 1, n):
            et, ep = _exit_long(
                entry=entry,
                stop=stop,
                target=target,
                op=float(open_arr[i]),
                hi=float(high_arr[i]),
                lo=float(low_arr[i]),
            )
            if et is not None:
                exit_type, exit_px, exit_bar = et, ep, i
                break

        if exit_type is None:
            if liquidate_at_end:
                exit_bar = n - 1
                exit_type = "EOD"
                exit_px = float(close_arr[exit_bar])
            else:
                cur = float(close_arr[n - 1])
                pnl_pct = (cur / entry - 1.0) * 100.0
                days = max(int((dates[n - 1] - dates[entry_bar]).days), 0)
                open_trade = OpenTrade(
                    SYMBOL=sym,
                    SIDE="LONG",
                    DATE_SIGNAL=_iso(dates[signal_t]),
                    DATE_OPENED=_iso(dates[entry_bar]),
                    ENTRY_PRICE=round(entry, 4),
                    STOP_PRICE=round(stop, 4),
                    TARGET_PRICE=round(target, 4),
                    CURRENT_PRICE=round(cur, 4),
                    DAYS_HELD=days,
                    PNL_PCT=round(pnl_pct, 4),
                    PNL_DOLLARS=round(notional * pnl_pct / 100.0, 2),
                    SPY_COMPARE_1Y=round(float(meta["SPY_COMPARE_1Y"]), 4),
                    SPY_COMPARE_2Y=round(float(meta["SPY_COMPARE_2Y"]), 4),
                    SPY_COMPARE_3Y=round(float(meta["SPY_COMPARE_3Y"]), 4),
                    IND_TC_SHORT_OUTLOOK=str(meta["IND_TC_SHORT_OUTLOOK"]),
                    IND_TC_INT_OUTLOOK=str(meta["IND_TC_INT_OUTLOOK"]),
                    IND_TC_LONG_OUTLOOK=str(meta["IND_TC_LONG_OUTLOOK"]),
                )
                break

        pnl_pct = (float(exit_px) / entry - 1.0) * 100.0
        days = max(int((dates[exit_bar] - dates[entry_bar]).days), 0)
        trades.append(
            Trade(
                SYMBOL=sym,
                SIDE="LONG",
                DATE_SIGNAL=_iso(dates[signal_t]),
                DATE_OPENED=_iso(dates[entry_bar]),
                ENTRY_PRICE=round(entry, 4),
                STOP_PRICE=round(stop, 4),
                TARGET_PRICE=round(target, 4),
                DATE_CLOSED=_iso(dates[exit_bar]),
                EXIT_PRICE=round(float(exit_px), 4),
                EXIT_TYPE=exit_type,
                DAYS_HELD=days,
                PNL_PCT=round(pnl_pct, 4),
                PNL_DOLLARS=round(notional * pnl_pct / 100.0, 2),
                SPY_COMPARE_1Y=round(float(meta["SPY_COMPARE_1Y"]), 4),
                SPY_COMPARE_2Y=round(float(meta["SPY_COMPARE_2Y"]), 4),
                SPY_COMPARE_3Y=round(float(meta["SPY_COMPARE_3Y"]), 4),
                IND_TC_SHORT_OUTLOOK=str(meta["IND_TC_SHORT_OUTLOOK"]),
                IND_TC_INT_OUTLOOK=str(meta["IND_TC_INT_OUTLOOK"]),
                IND_TC_LONG_OUTLOOK=str(meta["IND_TC_LONG_OUTLOOK"]),
            )
        )
        search_from = exit_bar + 1 if exit_bar >= 0 else signal_t + 1

    scanner: Optional[dict[str, Any]] = None
    if open_trade is None and n >= _RS_SPY_LAG_3Y + 1:
        last_t = n - 1
        hit = _signal_at(last_t, tc_ok=tc_ok, st=st, sp=sp, pre=pre)
        if hit is not None:
            close_px = float(close_arr[last_t])
            scanner = {
                "SYMBOL": sym,
                "DATE": _iso(dates[last_t]),
                "CLOSE": round(close_px, 4),
                "STOP_LOSS": round(close_px * stop_pct, 4),
                "TARGET": round(close_px * target_pct, 4),
                "SIGNAL_BAR_LOW": round(float(low_arr[last_t]), 4),
                "SIGNAL_BAR_HIGH": round(float(high_arr[last_t]), 4),
                "PRIOR_DAY_CLOSE": round(float(close_arr[last_t - 1]), 4) if last_t > 0 else "",
                "SPY_COMPARE_1Y": round(float(hit["SPY_COMPARE_1Y"]), 4),
                "SPY_COMPARE_2Y": round(float(hit["SPY_COMPARE_2Y"]), 4),
                "SPY_COMPARE_3Y": round(float(hit["SPY_COMPARE_3Y"]), 4),
                "IND_TC_SHORT_OUTLOOK": hit["IND_TC_SHORT_OUTLOOK"],
                "IND_TC_INT_OUTLOOK": hit["IND_TC_INT_OUTLOOK"],
                "IND_TC_LONG_OUTLOOK": hit["IND_TC_LONG_OUTLOOK"],
                "NOTE": "Buy next open (signal on last close)",
            }

    return trades, open_trade, scanner


def _portfolio_max_dd(trades: list[Trade], *, capital: float, max_pos: int) -> float:
    if not trades:
        return 0.0
    notional = capital / max(max_pos, 1)
    events: list[tuple[pd.Timestamp, str, Trade]] = []
    for t in trades:
        events.append((pd.Timestamp(t.DATE_OPENED), "open", t))
        events.append((pd.Timestamp(t.DATE_CLOSED), "close", t))
    events.sort(key=lambda x: (x[0], 0 if x[1] == "close" else 1))

    equity = capital
    peak = capital
    max_dd = 0.0
    open_slots = 0
    accepted: set[int] = set()

    for _ts, kind, t in events:
        tid = id(t)
        if kind == "open":
            if open_slots >= max_pos:
                continue
            open_slots += 1
            accepted.add(tid)
        else:
            if tid not in accepted:
                continue
            open_slots = max(0, open_slots - 1)
            pnl = notional * (t.PNL_PCT / 100.0)
            equity += pnl
            peak = max(peak, equity)
            dd = (peak - equity) / peak * 100.0 if peak > 0 else 0.0
            max_dd = max(max_dd, dd)
    return float(max_dd)


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _write_summary_csv(path: Path, closed: list[Trade]) -> None:
    from collections import defaultdict

    by_sym: dict[str, list[Trade]] = defaultdict(list)
    for t in closed:
        by_sym[t.SYMBOL].append(t)
    total_pnl = sum(t.PNL_DOLLARS for t in closed)
    rows: list[dict[str, Any]] = []
    for sym in sorted(by_sym.keys()):
        trades = by_sym[sym]
        wins = sum(1 for t in trades if t.PNL_PCT > 0)
        losses = sum(1 for t in trades if t.PNL_PCT < 0)
        bes = sum(1 for t in trades if t.PNL_PCT == 0)
        total = sum(t.PNL_DOLLARS for t in trades)
        avg_pct = sum(t.PNL_PCT for t in trades) / len(trades) if trades else 0.0
        pct_of_total = (total / total_pnl * 100.0) if total_pnl else 0.0
        rows.append(
            {
                "SYMBOL": sym,
                "TRADES": len(trades),
                "WINS": wins,
                "LOSSES": losses,
                "BEs": bes,
                "TOTAL_PNL": f"{total:.2f}",
                "AVG_PNL_PCT": f"{avg_pct:.2f}%",
                "PCT_OF_TOTAL_PNL": f"{pct_of_total:.1f}%",
            }
        )
    _write_csv(
        path,
        rows,
        ["SYMBOL", "TRADES", "WINS", "LOSSES", "BEs", "TOTAL_PNL", "AVG_PNL_PCT", "PCT_OF_TOTAL_PNL"],
    )


def _parse_kv_overrides(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in items:
        if "=" not in raw:
            continue
        k, v = raw.split("=", 1)
        out[k.strip().lower()] = v.strip()
    return out


def _run_one(
    sym: str,
    *,
    data_dir: Path,
    spy_df: pd.DataFrame,
    notional: float,
    target_pct: float,
    stop_pct: float,
    liquidate_at_end: bool,
    use_indicators: bool,
) -> tuple[str, list[Trade], Optional[OpenTrade], Optional[dict[str, Any]], Optional[str]]:
    path = data_dir / f"{sym}.csv"
    if not path.is_file():
        return sym, [], None, None, f"no CSV"
    try:
        df = load_csv(str(path))
        closed, opened, scanner = backtest_symbol(
            sym,
            df,
            spy_df,
            notional=notional,
            data_dir=data_dir,
            target_pct=target_pct,
            stop_pct=stop_pct,
            liquidate_at_end=liquidate_at_end,
            use_indicators=use_indicators,
        )
        return sym, closed, opened, scanner, None
    except Exception as exc:  # noqa: BLE001 — per-symbol isolation for DailyRun
        return sym, [], None, None, str(exc)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "data_dir",
        nargs="?",
        default=str(_REPO / "data" / "newdata" / "data"),
        help="CSV data directory (default: data/newdata/data)",
    )
    ap.add_argument("-o", "--out", "--out-dir", dest="out", default=str(_REPO / "drive"))
    ap.add_argument(
        "-s",
        "--symbols",
        default=",".join(DEFAULT_SYMBOLS),
        help="Comma-separated symbols",
    )
    ap.add_argument("-w", "--workers", type=int, default=8, help="Parallel symbol workers")
    ap.add_argument(
        "-v",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Override: target_pct, stop_pct, use_indicators, max_positions, capital, liquidate_at_end",
    )
    ap.add_argument("--target", "--target-pct", dest="target_pct", type=float, default=None)
    ap.add_argument("--stop", "--stop-pct", dest="stop_pct", type=float, default=None)
    ap.add_argument("--capital", type=float, default=None)
    ap.add_argument("--max-positions", type=int, default=None)
    ap.add_argument(
        "--liquidate-at-end",
        action="store_true",
        help="Force EOD exit on still-open trades (experiment mode)",
    )
    args = ap.parse_args(argv)
    kv = _parse_kv_overrides(list(args.v or []))

    data_dir = Path(args.data_dir)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    symbols = [s.strip().upper() for s in str(args.symbols).split(",") if s.strip()]
    target_pct = float(
        args.target_pct
        if args.target_pct is not None
        else kv.get("target_pct", DEFAULT_TARGET_PCT)
    )
    stop_pct = float(
        args.stop_pct if args.stop_pct is not None else kv.get("stop_pct", DEFAULT_STOP_PCT)
    )
    capital = float(args.capital if args.capital is not None else kv.get("capital", INITIAL_CAPITAL))
    max_pos = int(
        args.max_positions
        if args.max_positions is not None
        else kv.get("max_positions", MAX_POSITIONS)
    )
    use_ind_raw = kv.get("use_indicators", "true").strip().lower()
    use_indicators = use_ind_raw in ("1", "true", "yes", "on")
    liquidate_at_end = bool(args.liquidate_at_end) or kv.get("liquidate_at_end", "").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    notional = capital / max(max_pos, 1)
    workers = max(1, int(args.workers))

    spy_path = data_dir / "SPY.csv"
    if not spy_path.is_file():
        raise SystemExit(f"Missing SPY.csv at {spy_path}")
    spy_df = load_csv(str(spy_path))

    t0 = datetime.now()
    stamp = t0.strftime("%y%m%d%H%M%S")
    all_closed: list[Trade] = []
    all_open: list[OpenTrade] = []
    all_scanner: list[dict[str, Any]] = []
    per_sym: dict[str, int] = {}

    print(
        f"[RS] symbols={len(symbols)} target={target_pct} stop={stop_pct} "
        f"use_indicators={use_indicators} workers={workers}",
        flush=True,
    )

    def _job(sym: str):
        return _run_one(
            sym,
            data_dir=data_dir,
            spy_df=spy_df,
            notional=notional,
            target_pct=target_pct,
            stop_pct=stop_pct,
            liquidate_at_end=liquidate_at_end,
            use_indicators=use_indicators,
        )

    if workers <= 1:
        results = [_job(sym) for sym in symbols]
    else:
        results = []
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_job, sym): sym for sym in symbols}
            for fut in as_completed(futs):
                results.append(fut.result())

    for sym, closed, opened, scanner, err in results:
        if err:
            print(f"[SKIP] {sym}: {err}", flush=True)
            continue
        per_sym[sym] = len(closed)
        all_closed.extend(closed)
        if opened is not None:
            all_open.append(opened)
        if scanner is not None:
            all_scanner.append(scanner)
        print(
            f"  {sym}: closed={len(closed)} open={1 if opened else 0} scanner={1 if scanner else 0}",
            flush=True,
        )

    all_closed.sort(key=lambda t: (t.DATE_OPENED, t.SYMBOL))
    all_open.sort(key=lambda t: (t.DATE_OPENED, t.SYMBOL))
    all_scanner.sort(key=lambda r: (r.get("DATE", ""), r.get("SYMBOL", "")))

    closed_path = outdir / f"{FILE_PREFIX}_Closed_{stamp}.csv"
    open_path = outdir / f"{FILE_PREFIX}_Open_{stamp}.csv"
    scanner_path = outdir / f"{FILE_PREFIX}_Scanner_{stamp}.csv"
    summary_path = outdir / f"{FILE_PREFIX}_Summary_{stamp}.csv"

    closed_fields = [f.name for f in fields(Trade)]
    _write_csv(closed_path, [asdict(t) for t in all_closed], closed_fields)

    open_fields = [f.name for f in fields(OpenTrade)]
    _write_csv(open_path, [asdict(t) for t in all_open], open_fields)

    scanner_fields = [
        "SYMBOL",
        "DATE",
        "CLOSE",
        "STOP_LOSS",
        "TARGET",
        "SIGNAL_BAR_LOW",
        "SIGNAL_BAR_HIGH",
        "PRIOR_DAY_CLOSE",
        "SPY_COMPARE_1Y",
        "SPY_COMPARE_2Y",
        "SPY_COMPARE_3Y",
        "IND_TC_SHORT_OUTLOOK",
        "IND_TC_INT_OUTLOOK",
        "IND_TC_LONG_OUTLOOK",
        "NOTE",
    ]
    _write_csv(scanner_path, all_scanner, scanner_fields)
    _write_summary_csv(summary_path, all_closed)

    metrics = {
        "Total_Trades": len(all_closed),
        "Open_Positions": len(all_open),
        "Scanner_Signals": len(all_scanner),
        "Wins": sum(1 for t in all_closed if t.PNL_DOLLARS > 0),
        "Win_Rate_Pct": round(
            100.0 * sum(1 for t in all_closed if t.PNL_DOLLARS > 0) / len(all_closed), 2
        )
        if all_closed
        else 0.0,
        "Total_PNL": round(sum(t.PNL_DOLLARS for t in all_closed), 2),
        "Max_DD_Pct": round(_portfolio_max_dd(all_closed, capital=capital, max_pos=max_pos), 2),
        "target_pct": target_pct,
        "stop_pct": stop_pct,
        "symbols": symbols,
        "trades_per_symbol": per_sym,
        "elapsed_s": round((datetime.now() - t0).total_seconds(), 1),
        "stamp": stamp,
        "closed_csv": str(closed_path),
        "open_csv": str(open_path),
        "scanner_csv": str(scanner_path),
        "summary_csv": str(summary_path),
    }
    print(json.dumps(metrics, indent=2), flush=True)
    print(f"Wrote {closed_path}", flush=True)
    print(f"Wrote {open_path}", flush=True)
    print(f"Wrote {scanner_path}", flush=True)
    print(f"Wrote {summary_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
