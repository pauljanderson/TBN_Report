#!/usr/bin/env python3
"""
Emit BRT-style Closed / Open / Audit_Report CSVs from Rocket Launcher (RL_*) outputs.

Rocket Launcher writes ``RL_Closed_<ts>.csv`` and ``RL_Open_<ts>.csv`` (comma-separated,
column names with spaces). This script maps the overlapping fields into ``BRTTrade`` rows
and calls ``write_brt_closed`` / ``write_brt_open`` / ``write_brt_audit_report`` so you get
BRT-shaped artifacts for comparison (separate filenames, e.g. ``BRT_Closed_RL_<ts>.csv``).

Typical use (from repo root, after ``portfolio_audit.awk`` / ``run_audit.ps1``):

  python stock_analysis/rl_emit_brt_mirror.py --output-dir drive --data-dir data/newdata/data

Also writes ``RL_Correlation_<ts>.csv`` / ``RL_ReferenceStats_<ts>.csv`` (field vs PNL % drivers).

If ``--ts`` is omitted, reads ``<output-dir>/last_run_ts.txt`` (written by the AWK audit).

Portfolio **Max_DD** on ``BRT_Audit_Report_RL_*`` is read from the AWK summary row (column 0 contains
the run ``ts``): ``RocketLauncher.csv`` at repo root, then ``temp_run.csv`` at repo root (same row
is written to both on a normal audit), then ``<output-dir>/RocketLauncher.csv``. Values use AWK
``max_port_dd`` (fraction); if no matching row is found, ``compute_metrics`` leaves drawdown as N/A.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Any, Optional

import pandas as pd

try:
    from rocket_brt import (
        BRTConfig,
        BRTTrade,
        _apply_report_dollar_scale_to_trades,
        _enrich_post_entry_gain_hit,
        compute_metrics,
        load_all_tickers,
        write_brt_audit_report,
        write_brt_closed,
        write_brt_open,
    )
except ImportError:
    from stock_analysis.rocket_brt import (  # type: ignore[no-redef]
        BRTConfig,
        BRTTrade,
        _apply_report_dollar_scale_to_trades,
        _enrich_post_entry_gain_hit,
        compute_metrics,
        load_all_tickers,
        write_brt_audit_report,
        write_brt_closed,
        write_brt_open,
    )


def _parse_pct(s: Any) -> float:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return 0.0
    t = str(s).strip().replace("%", "").replace(",", "")
    if t == "":
        return 0.0
    try:
        return float(t)
    except ValueError:
        return 0.0


def _strip_df_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _norm_date(s: Any) -> str:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    t = str(s).strip().replace("-", "")
    if re.fullmatch(r"\d{8}", t):
        return t
    if len(t) >= 8 and t[:8].isdigit():
        return t[:8]
    return t[:8] if len(t) >= 8 else t


def _fnum(row: pd.Series, *keys: str) -> Optional[float]:
    for k in keys:
        if k not in row.index:
            continue
        v = row[k]
        if pd.isna(v):
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _fint(row: pd.Series, key: str, default: int = 0) -> int:
    if key not in row.index:
        return default
    v = row[key]
    if pd.isna(v):
        return default
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _rl_closed_row_to_trade(row: pd.Series) -> BRTTrade:
    """Best-effort map from RL_Closed row to BRTTrade (BRT-only fields default)."""
    sym = str(row.get("SYMBOL", "")).strip().upper()
    d_open = _norm_date(row.get("DATE OPENED"))
    d_close = _norm_date(row.get("DATE CLOSED"))
    entry = float(_fnum(row, "ENTRY PRICE") or 0.0)
    exit_px = float(_fnum(row, "EXIT PRICE") or 0.0)
    stop = float(_fnum(row, "STOP LOSS AT CLOSE", "ORIGINAL STOP") or 0.0)
    target = float(_fnum(row, "ORIGINAL TARGET") or 0.0)
    max_px = float(_fnum(row, "MAX PRICE") or entry or 0.0)
    days_held = _fint(row, "DAYS HELD", 0)
    pnl_pct = _parse_pct(row.get("PNL %"))
    exit_type = str(row.get("EXIT TYPE", "") or "").strip()
    atr_abs = _fnum(row, "ATR")
    atr_pct_rl = _fnum(row, "ATR % OF PRICE")  # RL stores as fraction of price (e.g. 0.034)
    # BRT audit column ATR_PCT_AT_ENTRY is (ATR/entry)*100 in writer; keep atr_14_at_entry from RL ATR column.
    atr_pct_at_entry: Optional[float] = None
    if atr_abs is not None and entry > 0:
        atr_pct_at_entry = (atr_abs / entry) * 100.0
    elif atr_pct_rl is not None:
        atr_pct_at_entry = atr_pct_rl * 100.0
    return BRTTrade(
        symbol=sym,
        date_opened=d_open,
        entry_price=entry,
        stop_price=stop,
        target_price=target,
        date_closed=d_close,
        exit_price=exit_px,
        exit_type=exit_type,
        days_held=days_held,
        pnl_pct=pnl_pct,
        pnl_dollars=0.0,
        max_price=max_px if max_px > 0 else entry,
        atr_14_at_entry=atr_abs,
        atr_pct_at_entry=atr_pct_at_entry,
        entry_pivot_was_strong=(
            int(float(row.get("PIVOT_HIGH_AT_ENTRY", 0) or 0) > 0)
            if "PIVOT_HIGH_AT_ENTRY" in row.index
            else 0
        ),
        entry_major_pivot=(
            int(float(row.get("MAJOR_PIVOT_HIGH_AT_ENTRY", 0) or 0) > 0)
            if "MAJOR_PIVOT_HIGH_AT_ENTRY" in row.index
            else 0
        ),
        struct_high=str(row.get("STRUCT_HIGH_AT_ENTRY", "") or "").strip(),
        struct_low=str(row.get("STRUCT_LOW_AT_ENTRY", "") or "").strip(),
        maturity_date="",
        close_above_date="",
        breakout_date="",
        volume_at_entry=_fnum(row, "AVG_VOL"),
        rel_vol_at_entry=(
            (float(row["TRIGGER_VOL"]) / float(row["AVG_VOL"]))
            if (
                "TRIGGER_VOL" in row.index
                and "AVG_VOL" in row.index
                and not pd.isna(row.get("AVG_VOL"))
                and float(row.get("AVG_VOL") or 0) > 0
            )
            else None
        ),
    )


def _rl_open_row_to_trade(row: pd.Series) -> BRTTrade:
    sym = str(row.get("SYMBOL", "")).strip().upper()
    d_open = _norm_date(row.get("DATE OPENED"))
    entry = float(_fnum(row, "ENTRY PRICE") or 0.0)
    stop = float(_fnum(row, "STOP LOSS") or 0.0)
    target = float(_fnum(row, "TARGET") or 0.0)
    pnl_pct = _parse_pct(row.get("PNL %"))
    return BRTTrade(
        symbol=sym,
        date_opened=d_open,
        entry_price=entry,
        stop_price=stop,
        target_price=target,
        pnl_pct=pnl_pct,
        pnl_dollars=0.0,
        max_price=entry,
    )


def _read_ts(output_dir: Path, ts_arg: str) -> str:
    if ts_arg.strip():
        return ts_arg.strip()
    p = output_dir / "last_run_ts.txt"
    if not p.exists():
        raise FileNotFoundError(f"No --ts and missing {p}")
    return p.read_text(encoding="utf-8", errors="replace").strip()


# portfolio_audit.awk appends ``max_port_dd`` (peak-to-trough fraction) after ``synthetic_ror``.
# RocketLauncher.csv has had multiple column layouts over time; try canonical index first, then fallbacks.
_RL_ROCKET_LAUNCHER_MAX_DD_COL_CANDIDATES = (53, 49, 44)


def _parse_portfolio_dd_fraction(cell: str) -> Optional[float]:
    """Parse max_port_dd cell: AWK uses a fraction in [0,1]. Percent only if the cell contains %."""
    raw = str(cell).strip()
    had_pct = "%" in raw
    t = raw.replace("%", "").replace(",", "")
    if not t:
        return None
    try:
        v = float(t)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return None
    if v < 0:
        return None
    if v <= 1.000001:
        return v
    if had_pct and v <= 100.0:
        return v / 100.0
    return None


def _max_port_dd_from_row(row: list[str]) -> Optional[float]:
    for idx in _RL_ROCKET_LAUNCHER_MAX_DD_COL_CANDIDATES:
        if len(row) <= idx:
            continue
        v = _parse_portfolio_dd_fraction(row[idx])
        if v is not None:
            return v
    return None


def _max_port_dd_scan_ledger_file(path: Path, ts: str) -> Optional[float]:
    """
    Scan one ledger/summary file (RocketLauncher.csv or temp_run.csv): from bottom, return
    max-portfolio-DD fraction from the first row whose column 0 contains ``ts`` when ``ts`` is set;
    if ``ts`` is empty, use the bottom-most parseable wide row.
    """
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return None

    def parse_line(ln: str) -> Optional[list[str]]:
        try:
            return next(csv.reader([ln]))
        except Exception:
            return None

    min_cols = min(_RL_ROCKET_LAUNCHER_MAX_DD_COL_CANDIDATES) + 1
    ts_st = (ts or "").strip()
    fallback: Optional[list[str]] = None
    for ln in reversed(lines):
        row = parse_line(ln)
        if not row or len(row) <= min_cols:
            continue
        if fallback is None:
            fallback = row
        if ts_st and ts_st in (row[0] or ""):
            return _max_port_dd_from_row(row)
    if ts_st:
        return None
    return _max_port_dd_from_row(fallback) if fallback else None


def _max_port_dd_from_rl_run_ledger(repo_root: Path, out_dir: Path, ts: str) -> Optional[float]:
    """
    Portfolio max DD fraction for this run: same row the AWK audit appends (hyperlink col0 has ``ts``).

    Tries, in order: ``repo_root/RocketLauncher.csv``, ``repo_root/temp_run.csv`` (mirror of that row
    after the OUT_FILE fix), then ``out_dir/RocketLauncher.csv``.
    """
    ts_st = (ts or "").strip()
    for path in (
        repo_root / "RocketLauncher.csv",
        repo_root / "temp_run.csv",
        out_dir / "RocketLauncher.csv",
    ):
        v = _max_port_dd_scan_ledger_file(path, ts_st)
        if v is not None:
            return v
    if ts_st:
        tried = ", ".join(str(p) for p in (repo_root / "RocketLauncher.csv", repo_root / "temp_run.csv", out_dir / "RocketLauncher.csv"))
        print(
            f"[rl_emit_brt_mirror] ts={ts_st!r} not found in ledger files ({tried}); "
            "skip RL portfolio Max_DD.",
            file=sys.stderr,
        )
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Emit BRT-shaped CSVs from RL_Closed / RL_Open.")
    ap.add_argument("--output-dir", "-o", type=str, default="drive")
    ap.add_argument("--data-dir", type=str, default="data/newdata/data")
    ap.add_argument(
        "--symbols",
        "-s",
        type=str,
        default="",
        help="Comma-separated tickers: only load these CSVs for post-entry enrichment (default: all tickers in data-dir).",
    )
    ap.add_argument("--ts", type=str, default="", help="Run timestamp yyMMddHHmmss (default: read last_run_ts.txt)")
    ap.add_argument("--brt-cash", type=float, default=47500.0, help="Notional per trade for PNL_DOLLARS scaling")
    args = ap.parse_args()

    repo = Path(__file__).resolve().parent.parent
    out_dir = Path(args.output_dir)
    if not out_dir.is_absolute():
        out_dir = repo / out_dir
    data_dir = Path(args.data_dir)
    if not data_dir.is_absolute():
        data_dir = repo / data_dir

    ts = _read_ts(out_dir, args.ts)
    rl_closed = out_dir / f"RL_Closed_{ts}.csv"
    rl_open = out_dir / f"RL_Open_{ts}.csv"
    if not rl_closed.exists():
        print(f"[rl_emit_brt_mirror] RL closed not found: {rl_closed}", file=sys.stderr)
        return 1

    closed_df = _strip_df_columns(pd.read_csv(rl_closed, low_memory=False))
    closed: list[BRTTrade] = []
    for _, row in closed_df.iterrows():
        try:
            closed.append(_rl_closed_row_to_trade(row))
        except Exception as e:
            print(f"[rl_emit_brt_mirror] skip closed row: {e}", file=sys.stderr)

    open_list: list[BRTTrade] = []
    if rl_open.exists():
        open_df = _strip_df_columns(pd.read_csv(rl_open, low_memory=False))
        for _, row in open_df.iterrows():
            try:
                open_list.append(_rl_open_row_to_trade(row))
            except Exception as e:
                print(f"[rl_emit_brt_mirror] skip open row: {e}", file=sys.stderr)

    cfg = BRTConfig(brt_cash=float(args.brt_cash))
    sym_filt: set[str] | None = None
    if str(args.symbols).strip():
        sym_filt = {x.strip().upper() for x in str(args.symbols).split(",") if x.strip()}
    tickers = (
        load_all_tickers(str(data_dir), symbols_filter=sym_filt) if data_dir.exists() else {}
    )

    for t in closed:
        if t.entry_price > 0 and cfg.brt_cash > 0:
            t.pnl_dollars = (cfg.brt_cash / t.entry_price) * (t.exit_price - t.entry_price)
    for t in open_list:
        if t.entry_price > 0 and cfg.brt_cash > 0:
            cur = t.entry_price * (1.0 + t.pnl_pct / 100.0)
            t.pnl_dollars = (cfg.brt_cash / t.entry_price) * (cur - t.entry_price)

    if closed:
        _apply_report_dollar_scale_to_trades(closed, open_list, cfg)
    if tickers:
        _enrich_post_entry_gain_hit(closed + open_list, tickers, cfg)
        try:
            from rocket_brt import _enrich_trades_entry_indicators
        except ImportError:
            from stock_analysis.rocket_brt import _enrich_trades_entry_indicators
        _enrich_trades_entry_indicators(closed + open_list, tickers, cfg)

    out_closed = out_dir / f"BRT_Closed_RL_{ts}.csv"
    out_open = out_dir / f"BRT_Open_RL_{ts}.csv"
    write_brt_closed(closed, str(out_closed), reference_stats=None, cfg=cfg)
    write_brt_open(open_list, str(out_open), tickers=tickers, brt_cash=cfg.brt_cash, closed=closed, cfg=cfg)

    metrics = dict(compute_metrics(closed, cfg))
    # Portfolio max DD from Rocket Launcher (AWK equity curve); BRT compute_metrics has no OHLC path here.
    _rl_mdd = _max_port_dd_from_rl_run_ledger(repo, out_dir, ts)
    if _rl_mdd is not None and _rl_mdd >= 0:
        metrics["Max_Drawdown"] = f"{_rl_mdd * 100.0:.2f}%"
        total_trades = int(metrics.get("Wins", 0) or 0) + int(metrics.get("Losses", 0) or 0) + int(metrics.get("BEs", 0) or 0)
        if total_trades > 0:
            metrics["DD_Per_Trade"] = f"{(_rl_mdd / total_trades):.4f}"

    audit_rl = out_dir / f"BRT_Audit_Report_RL_{ts}.csv"
    write_brt_audit_report(
        cfg,
        metrics,
        str(out_dir),
        ts,
        drive_link="",
        file_prefix="BRT",
        audit_report_suffix="_RL",
    )

    # RL closed-field correlation vs PNL % / annualized ROR (same column layout as BRT_Correlation_*)
    _script_dir = Path(__file__).resolve().parent
    if str(_script_dir) not in sys.path:
        sys.path.insert(0, str(_script_dir))
    try:
        from correlate_rl_closed import run_rl_correlation_report
    except ImportError:
        from stock_analysis.correlate_rl_closed import run_rl_correlation_report  # type: ignore[no-redef]

    rl_corr = out_dir / f"RL_Correlation_{ts}.csv"
    try:
        run_rl_correlation_report(str(rl_closed), str(rl_corr))
        if rl_corr.exists():
            print(f"[rl_emit_brt_mirror] Wrote {rl_corr.name}")
    except Exception as e:
        print(f"[rl_emit_brt_mirror] RL correlation report skipped: {e}", file=sys.stderr)

    print(
        f"[rl_emit_brt_mirror] Wrote {out_closed.name} ({len(closed)}), "
        f"{out_open.name} ({len(open_list)}), {audit_rl.name}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
