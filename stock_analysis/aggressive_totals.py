"""
Recompute aggressive portfolio metrics for an existing backtest run without rerunning rocket_brt.

Uses Closed/Open CSVs + OHLC tickers + audit parameters to replay the aggressive equity ledger
(BRT_DrawdownCalc._simulate_aggressive_share_level) with different sizing / leverage inputs.

Examples:
  python stock_analysis/aggressive_totals.py 260706134400 --engine MTS
  python stock_analysis/aggressive_totals.py 260706134400 --engine MTS --avg-positions 7,8,9,10,15
  python stock_analysis/aggressive_totals.py 260706134400 --engine MTS --risk-grid -o Drive/grid.csv
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from itertools import product
from pathlib import Path
from typing import Any, Optional

import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from BRT_DrawdownCalc import (  # noqa: E402
    _equity_calendar_dates_aggressive_only,
    _mean_daily_unique_symbols_active,
    _normalize_aggressive_sell,
    _resolve_ticker_dir,
    _simulate_aggressive_share_level,
    _underwater_and_max_dd_from_equity_series,
    clean_numeric,
    normalize_ohlc_columns,
)
from DrawdownCalc import _resolve_closed_csv_argument  # noqa: E402

METRIC_COLS = (
    "Aggressive_Total_PNL",
    "Aggressive_Max_DD",
    "Aggressive_Max_DD_pct",
    "Aggressive_Avg_Positions",
    "Aggressive_Days_AtOrBelow_Avg",
    "Aggressive_Days_In_Margin",
    "Aggressive_Days_Trimmed_Over_2xAvg",
)

INPUT_COLS = (
    "aggressive_avg_positions",
    "aggressive_max_multiple",
    "aggressive_sizing_equity_cap",
    "aggressive_sell",
)

OUTPUT_COLS = INPUT_COLS + METRIC_COLS

RISK_GRID = {
    "avg_positions": [16.0, 18.0, 20.0],
    "max_multiple": [1.5, 2.0],
    "equity_cap": [3.0, 5.0, 10.0],
    "aggressive_sell": ["false", "losers"],
}


def _engine_from_closed_path(closed_path: str) -> str:
    name = os.path.basename(closed_path).upper()
    for prefix in ("MTS", "IND", "BRT", "RL", "YH"):
        if name.startswith(f"{prefix}_CLOSED_"):
            return prefix
    return "BRT"


def _load_audit_params(base_dir: str, timestamp: str, file_prefix: str) -> dict[str, Any]:
    """Read aggressive-related params from the audit/report row for this run."""
    defaults = {
        "initial_capital": 500_000.0,
        "aggressive_margin_interest": 0.10,
        "aggressive_max_multiple": 2.0,
        "aggressive_sizing_equity_cap": 10.0,
        "aggressive_sell": "false",
        "margin_utilization": 1.0,
        "aggressive_avg_positions": 0.0,
    }
    audit_metrics = {}
    for name in (
        f"{file_prefix}_Audit_Report_{timestamp}.csv",
        f"{file_prefix}_Report_{timestamp}.csv",
    ):
        path = os.path.join(base_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            df = pd.read_csv(path, index_col=False, nrows=1)
            if df.empty:
                continue
            df.columns = [str(c).strip() for c in df.columns]
            colmap = {c.lower(): c for c in df.columns}
            row = df.iloc[0]

            def _get(key: str, default=None):
                c = colmap.get(key.lower())
                if c is None:
                    return default
                return row[c]

            out = dict(defaults)
            for key in (
                "initial_capital",
                "aggressive_margin_interest",
                "aggressive_max_multiple",
                "aggressive_sizing_equity_cap",
                "margin_utilization",
                "aggressive_avg_positions",
            ):
                v = _get(key)
                if v is not None and str(v).strip() != "":
                    out[key] = float(clean_numeric(v))
            sell = _get("aggressive_sell")
            if sell is not None and str(sell).strip() != "":
                out["aggressive_sell"] = _normalize_aggressive_sell(str(sell).strip())
            for mkey in METRIC_COLS:
                if mkey == "Aggressive_Max_DD_pct":
                    continue
                c = colmap.get(mkey.lower())
                if c is not None:
                    audit_metrics[mkey] = row[c]
            out["_audit_source"] = name
            out["_audit_metrics"] = audit_metrics
            return out
        except Exception:
            continue
    out = dict(defaults)
    out["_audit_source"] = None
    out["_audit_metrics"] = {}
    return out


def _load_trades(closed_path: str, open_path: str) -> tuple[list[dict], list[dict]]:
    required_closed = ["SYMBOL", "DATE_OPENED", "ENTRY_PRICE", "DATE_CLOSED", "EXIT_PRICE"]
    df_closed = pd.read_csv(closed_path, index_col=False)
    df_closed.columns = [c.strip() for c in df_closed.columns]
    missing = [c for c in required_closed if c not in df_closed.columns]
    if missing:
        raise ValueError(f"Closed CSV missing columns: {missing}")

    closed: list[dict] = []
    for _, row in df_closed.iterrows():
        closed.append(
            {
                "SYMBOL": str(row["SYMBOL"]).strip(),
                "DATE_OPENED": row["DATE_OPENED"],
                "DATE_CLOSED": row["DATE_CLOSED"],
                "ENTRY_PRICE": clean_numeric(row["ENTRY_PRICE"]),
                "EXIT_PRICE": clean_numeric(row["EXIT_PRICE"]),
                "PNL_DOLLARS": clean_numeric(row["PNL_DOLLARS"])
                if "PNL_DOLLARS" in df_closed.columns
                else 0.0,
            }
        )

    open_trades: list[dict] = []
    if os.path.isfile(open_path):
        df_open = pd.read_csv(open_path, index_col=False)
        df_open.columns = [c.strip() for c in df_open.columns]
        if all(c in df_open.columns for c in ["SYMBOL", "DATE_OPENED", "ENTRY_PRICE"]):
            for _, row in df_open.iterrows():
                open_trades.append(
                    {
                        "SYMBOL": str(row["SYMBOL"]).strip(),
                        "DATE_OPENED": row["DATE_OPENED"],
                        "ENTRY_PRICE": clean_numeric(row["ENTRY_PRICE"]),
                    }
                )
    return closed, open_trades


def _load_tickers(ticker_dir: str, symbols: set[str]) -> dict[str, pd.DataFrame]:
    tickers: dict[str, pd.DataFrame] = {}
    missing: list[str] = []
    for sym in sorted(symbols):
        path = os.path.join(ticker_dir, f"{sym}.csv")
        if not os.path.isfile(path):
            missing.append(sym)
            continue
        try:
            df_t = pd.read_csv(path)
            df_t = normalize_ohlc_columns(df_t)
            if "Date" not in df_t.columns or "Close" not in df_t.columns:
                missing.append(sym)
                continue
            df_t["Date"] = pd.to_datetime(df_t["Date"])
            tickers[sym] = df_t
        except Exception:
            missing.append(sym)
    if missing:
        preview = ", ".join(missing[:12])
        suffix = f" ... (+{len(missing) - 12} more)" if len(missing) > 12 else ""
        print(f"[WARN] Missing tickers ({len(missing)}/{len(symbols)}): {preview}{suffix}")
    return tickers


def _effective_margin_utilization(*, aggressive: bool, margin_utilization: float) -> float:
    """Match rocket_brt._effective_margin_utilization: aggressive runs use full 1.0 leverage."""
    if aggressive:
        return 1.0
    util = float(margin_utilization or 0.6)
    return max(0.0, min(util, 1.0))


def _parse_float_list(raw: str) -> list[float]:
    out: list[float] = []
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        out.append(float(part))
    return out


def _parse_sell_list(raw: str) -> list[str]:
    out: list[str] = []
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        mode = _normalize_aggressive_sell(part)
        if mode not in ("false", "average", "losers", "winners"):
            raise ValueError(f"Invalid aggressive_sell mode: {part!r}")
        out.append(mode)
    return out


def _resolve_auto_avg_positions(all_dates: list, closed: list, open_trades: list) -> float:
    """Mean daily symbol count on active days (auto aggressive_avg_positions)."""
    return float(_mean_daily_unique_symbols_active(all_dates, closed, open_trades))


def compute_aggressive_totals(
    *,
    closed: list[dict],
    open_trades: list[dict],
    tickers: dict[str, pd.DataFrame],
    initial_capital: float,
    aggressive_avg_positions: float,
    aggressive_margin_interest: float = 0.10,
    aggressive_max_multiple: float = 2.0,
    aggressive_sizing_equity_cap: float = 10.0,
    margin_utilization: float = 1.0,
    aggressive_sell: str = "false",
    all_dates: Optional[list] = None,
    auto_avg_positions: Optional[float] = None,
) -> dict[str, Any]:
    dates = all_dates or _equity_calendar_dates_aggressive_only(closed, open_trades)
    if not dates:
        raise ValueError("No trade dates found in Closed/Open CSVs")

    avg_pos_in = float(aggressive_avg_positions)
    if avg_pos_in > 0:
        avg_pos_used = avg_pos_in
    else:
        avg_pos_used = (
            float(auto_avg_positions)
            if auto_avg_positions is not None
            else _resolve_auto_avg_positions(dates, closed, open_trades)
        )
        if avg_pos_used <= 0:
            raise ValueError("Could not resolve auto aggressive_avg_positions (no active trade days)")

    sell_mode = _normalize_aggressive_sell(aggressive_sell)
    (
        equity_values,
        _pos_values,
        below_or_at_avg_days,
        margin_days,
        trimmed_days,
        _trim_log,
    ) = _simulate_aggressive_share_level(
        dates,
        closed,
        open_trades,
        tickers,
        float(initial_capital),
        float(avg_pos_used),
        float(aggressive_margin_interest),
        float(aggressive_max_multiple),
        float(aggressive_sizing_equity_cap),
        float(margin_utilization),
        sell_mode,
    )

    if not equity_values:
        raise ValueError("Aggressive simulation produced no equity values")

    init = float(initial_capital)
    total_pnl = float(equity_values[-1]) - init
    max_dd_raw, _, _ = _underwater_and_max_dd_from_equity_series(equity_values, init)
    max_dd_pct = round(max_dd_raw * 100.0, 4) if max_dd_raw > 0 else 0.0

    return {
        "aggressive_avg_positions": avg_pos_in,
        "aggressive_max_multiple": float(aggressive_max_multiple),
        "aggressive_sizing_equity_cap": float(aggressive_sizing_equity_cap),
        "aggressive_sell": sell_mode,
        "Aggressive_Total_PNL": round(total_pnl, 2),
        "Aggressive_Max_DD": f"{max_dd_pct:.2f}%" if max_dd_raw > 0 else "N/A",
        "Aggressive_Max_DD_pct": max_dd_pct,
        "Aggressive_Avg_Positions": round(float(avg_pos_used), 4),
        "Aggressive_Days_AtOrBelow_Avg": int(below_or_at_avg_days),
        "Aggressive_Days_In_Margin": int(margin_days),
        "Aggressive_Days_Trimmed_Over_2xAvg": int(trimmed_days),
    }


def run_sweep(
    *,
    run_id: str,
    ticker_dir: Path,
    engine: Optional[str],
    avg_positions_list: list[float],
    max_multiple_list: list[float],
    equity_cap_list: list[float],
    sell_list: list[str],
    initial_capital: Optional[float],
    aggressive_margin_interest: Optional[float],
    margin_utilization: Optional[float],
    verbose: bool = True,
) -> pd.DataFrame:
    closed_path, _ts_mode, eng = _resolve_closed_csv_argument(
        run_id,
        engine_preference=engine,
    )
    if not os.path.isfile(closed_path):
        raise FileNotFoundError(
            f"No Closed CSV for run {run_id!r}. Pass a path or 12-digit timestamp with --engine."
        )
    file_prefix = engine or eng or _engine_from_closed_path(closed_path)
    base_dir = os.path.dirname(os.path.abspath(closed_path))
    ts_match = re.search(r"(\d{12})", os.path.basename(closed_path))
    timestamp = ts_match.group(1) if ts_match else run_id.strip()

    audit = _load_audit_params(base_dir, timestamp, file_prefix)
    init_cap = float(initial_capital if initial_capital is not None else audit["initial_capital"])
    margin_int = float(
        aggressive_margin_interest
        if aggressive_margin_interest is not None
        else audit["aggressive_margin_interest"]
    )
    margin_util_raw = float(
        margin_utilization if margin_utilization is not None else audit["margin_utilization"]
    )
    margin_util = float(
        margin_utilization
        if margin_utilization is not None
        else _effective_margin_utilization(aggressive=True, margin_utilization=margin_util_raw)
    )

    if not avg_positions_list:
        avg_positions_list = [float(audit.get("aggressive_avg_positions", 0.0) or 0.0)]
    if not max_multiple_list:
        max_multiple_list = [float(audit["aggressive_max_multiple"])]
    if not equity_cap_list:
        equity_cap_list = [float(audit["aggressive_sizing_equity_cap"])]
    if not sell_list:
        sell_list = [_normalize_aggressive_sell(str(audit.get("aggressive_sell", "false")))]

    open_path = os.path.join(base_dir, f"{file_prefix}_Open_{timestamp}.csv")
    closed, open_trades = _load_trades(closed_path, open_path)
    symbols = {t["SYMBOL"] for t in closed} | {t["SYMBOL"] for t in open_trades}
    resolved_ticker_dir = _resolve_ticker_dir(str(ticker_dir))
    tickers = _load_tickers(resolved_ticker_dir, symbols)
    all_dates = _equity_calendar_dates_aggressive_only(closed, open_trades)
    auto_avg = _resolve_auto_avg_positions(all_dates, closed, open_trades)

    if verbose:
        if margin_utilization is None and abs(margin_util_raw - margin_util) > 1e-9:
            print(
                f"[OK] margin_utilization audit={margin_util_raw} -> effective={margin_util} "
                "(rocket_brt uses 1.0 when --aggressive)"
            )
        print(f"[OK] Run {timestamp} ({file_prefix})")
        print(f"[OK] Closed: {closed_path} ({len(closed)} trades)")
        print(
            f"[OK] Open:   {open_path} ({len(open_trades)} rows)"
            if open_trades
            else "[OK] Open:   (none)"
        )
        print(f"[OK] Tickers: {len(tickers)}/{len(symbols)} loaded from {resolved_ticker_dir}")
        if audit.get("_audit_source"):
            print(f"[OK] Params from {audit['_audit_source']}")
        print(f"[OK] initial_capital={init_cap:,.0f}  margin_interest={margin_int}")
        print(f"[OK] auto avg_positions (when input=0): {auto_avg:.4f}")
        grid_n = (
            len(avg_positions_list)
            * len(max_multiple_list)
            * len(equity_cap_list)
            * len(sell_list)
        )
        print(f"[OK] Grid size: {grid_n} combinations")

    rows: list[dict] = []
    combos = list(
        product(avg_positions_list, max_multiple_list, equity_cap_list, sell_list)
    )
    for i, (avg, mult, cap, sell) in enumerate(combos, start=1):
        if verbose and (i == 1 or i == len(combos) or i % 10 == 0):
            print(
                f"[{i}/{len(combos)}] avg={avg} max_mult={mult} "
                f"eq_cap={cap} sell={sell}"
            )
        row = compute_aggressive_totals(
            closed=closed,
            open_trades=open_trades,
            tickers=tickers,
            initial_capital=init_cap,
            aggressive_avg_positions=float(avg),
            aggressive_margin_interest=margin_int,
            aggressive_max_multiple=float(mult),
            aggressive_sizing_equity_cap=float(cap),
            margin_utilization=margin_util,
            aggressive_sell=sell,
            all_dates=all_dates,
            auto_avg_positions=auto_avg,
        )
        rows.append(row)

    df = pd.DataFrame(rows, columns=list(OUTPUT_COLS))
    df = df.sort_values(
        ["Aggressive_Max_DD_pct", "Aggressive_Total_PNL"],
        ascending=[True, False],
    ).reset_index(drop=True)

    if verbose:
        audit_metrics = audit.get("_audit_metrics") or {}
        if audit_metrics:
            print("\n[audit row for comparison]")
            for col in METRIC_COLS:
                if col == "Aggressive_Max_DD_pct":
                    continue
                if col in audit_metrics:
                    print(f"  {col}: {audit_metrics[col]}")
    return df


def main() -> int:
    default_tickers = _REPO_ROOT / "data" / "newdata" / "data"

    p = argparse.ArgumentParser(
        description="Recompute aggressive totals for an existing Closed/Open run (no full backtest).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python stock_analysis/aggressive_totals.py 260706134400 --engine MTS\n"
            "  python stock_analysis/aggressive_totals.py 260706134400 --engine MTS --avg-positions 7,8,9\n"
            "  python stock_analysis/aggressive_totals.py 260706134400 --engine MTS --risk-grid\n"
            "  python stock_analysis/aggressive_totals.py 260706134400 --engine MTS \\\n"
            "    --avg-positions 16,18,20 --max-multiple 1.5,2.0 --equity-cap 3,5,10 \\\n"
            "    --aggressive-sell false,losers -o Drive/aggressive_grid.csv\n"
            "  (0 in --avg-positions = auto mean positions from the run's trade calendar)\n"
        ),
    )
    p.add_argument(
        "run",
        help="12-digit timestamp (yyMMddHHmmss) or path to *Closed_<ts>.csv",
    )
    p.add_argument("--engine", choices=("BRT", "IND", "MTS", "RL", "YH"), default=None)
    p.add_argument(
        "--ticker-dir",
        type=Path,
        default=default_tickers,
        help="OHLCV CSV directory (default: data/newdata/data)",
    )
    p.add_argument(
        "--avg-positions",
        default="",
        help="Comma-separated aggressive_avg_positions (default: audit; 0 = auto)",
    )
    p.add_argument(
        "--max-multiple",
        default="",
        help="Comma-separated aggressive_max_multiple values (default: audit)",
    )
    p.add_argument(
        "--equity-cap",
        default="",
        help="Comma-separated aggressive_sizing_equity_cap values (default: audit)",
    )
    p.add_argument(
        "--aggressive-sell",
        default="",
        help="Comma-separated modes: false,average,losers,winners (default: audit)",
    )
    p.add_argument(
        "--risk-grid",
        action="store_true",
        help=(
            "Preset grid: avg=16,18,20  max_mult=1.5,2.0  equity_cap=3,5,10  "
            "sell=false,losers (36 combos). Overrides unset list args."
        ),
    )
    p.add_argument("--initial-capital", type=float, default=None)
    p.add_argument("--margin-interest", type=float, default=None, dest="margin_interest")
    p.add_argument(
        "--margin-utilization",
        type=float,
        default=None,
        help="Override margin utilization (default: 1.0 for aggressive, like rocket_brt)",
    )
    p.add_argument("-o", "--output", type=Path, default=None, help="CSV output path")
    p.add_argument("-q", "--quiet", action="store_true", help="Less progress output")
    args = p.parse_args()

    if args.risk_grid:
        avg_list = (
            _parse_float_list(args.avg_positions)
            if args.avg_positions
            else list(RISK_GRID["avg_positions"])
        )
        mult_list = (
            _parse_float_list(args.max_multiple)
            if args.max_multiple
            else list(RISK_GRID["max_multiple"])
        )
        cap_list = (
            _parse_float_list(args.equity_cap)
            if args.equity_cap
            else list(RISK_GRID["equity_cap"])
        )
        sell_list = (
            _parse_sell_list(args.aggressive_sell)
            if args.aggressive_sell
            else list(RISK_GRID["aggressive_sell"])
        )
    else:
        avg_list = _parse_float_list(args.avg_positions) if args.avg_positions else []
        mult_list = _parse_float_list(args.max_multiple) if args.max_multiple else []
        cap_list = _parse_float_list(args.equity_cap) if args.equity_cap else []
        sell_list = _parse_sell_list(args.aggressive_sell) if args.aggressive_sell else []

    try:
        df = run_sweep(
            run_id=args.run.strip(),
            ticker_dir=args.ticker_dir,
            engine=args.engine,
            avg_positions_list=avg_list,
            max_multiple_list=mult_list,
            equity_cap_list=cap_list,
            sell_list=sell_list,
            initial_capital=args.initial_capital,
            aggressive_margin_interest=args.margin_interest,
            margin_utilization=args.margin_utilization,
            verbose=not args.quiet,
        )
    except Exception as exc:
        print(f"[ERR] {exc}", file=sys.stderr)
        return 1

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 240)
    pd.set_option("display.max_rows", 50)
    print("\n" + df.to_string(index=False))

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(args.output, index=False)
        print(f"\n[OK] Wrote {len(df)} rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
