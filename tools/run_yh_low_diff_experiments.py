"""
YH low-IND_DIFF capital backtest experiment.

Arms:
  baseline          — production run_yh.bat settings
  max_diff_3        — same + max_ind_diff_at_trigger=3 (hard gate at entry)
  same_day_low_diff — post-entry same-day keep lowest IND_DIFF among baseline
                      candidates, then recompute equity/capital metrics

Concurrency: up to 3 jobs x -w 10. Does not modify run_yh.bat.

Outputs under drive/yh_low_diff_exp/:
  status.txt, comparison.csv, comparison.md, <arm>/YH_* artifacts
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
OUT_ROOT = REPO / "drive" / "yh_low_diff_exp"
STATUS_PATH = OUT_ROOT / "status.txt"
DATA_DIR = REPO / "data" / "newdata" / "data"
SA = REPO / "stock_analysis"
TOOLS = REPO / "tools"
for p in (REPO, SA, TOOLS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# Hard gates for YH-scale sample (baseline ~445 trades, MaxDD ~12%)
MIN_TRADES = 100
MAX_DD = 25.0

# Frozen production settings matching run_yh.bat (do not edit run_yh.bat here)
YH_COMMON_V = [
    "yh_zones=true",
    "brt_zones=false",
    "wpbr_zones=false",
    "rl_mode=false",
    "band_pct=0.0099",
    "yh_move_away_pct=0.031",
    "yh_lookback=252",
    "yh_memory_mode=sheet",
    "strong_pre_pivot_bars=7",
    "strong_pre_pivot_pct=0.12",
    "strong_post_pivot_bars=7",
    "strong_post_pivot_pct=0.109",
    "strong_pivot_mode=both",
    "target_pct=1.27",
    "stop_pct=0.923",
    "stop_pct_is_multiplier=true",
    "too_high_multiplier=1.04",
    "min_spy_compare_1y_at_trigger=97.5",
    "max_spy_compare_1y_at_trigger=0",
    "min_atr_pct_at_trigger=0",
    "max_atr_pct_at_trigger=0",
    "growth_filter_enabled=true",
    "growth_bars=756",
    "use_indicators=false",
    "indicator_buy=off",
    f"ind_score_weights_path={REPO / 'stock_analysis' / 'ind_score_weights_260609152353.json'}",
    "min_ind_score=0",
    "indicator_diff=10",
    "symbol_reentry_cooldown_days=20",
]


def _resolve_python() -> str:
    env_py = os.environ.get("PY", "").strip()
    if env_py and Path(env_py).is_file():
        return env_py
    for p in (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Python/Python310/python.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Python/Python311/python.exe",
    ):
        if p.is_file():
            return str(p)
    return sys.executable


def _fmt_dur(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    return f"{m}m {s:02d}s"


def write_status(
    *,
    started_at: str,
    session_start: float,
    current_id: str,
    done: int,
    total: int,
    note: str = "",
    jobs: int = 2,
    workers: int = 10,
) -> None:
    elapsed = time.time() - session_start
    remaining = max(0, total - done)
    if done > 0 and remaining > 0:
        eta = _fmt_dur((elapsed / done) * remaining)
    elif remaining == 0:
        eta = "0s (done)"
    else:
        eta = "estimating..."
    pct = (100.0 * done / total) if total else 100.0
    lines = [
        "YH Low-DIFF Experiment Status",
        f"started_at:     {started_at}",
        f"updated_at:     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"elapsed:        {_fmt_dur(elapsed)}",
        f"current:        {current_id}",
        f"trials:         {done}/{total} ({pct:.1f}%)",
        f"eta:            {eta}",
        f"concurrency:    {jobs} concurrent jobs x -w {workers}",
        f"note:           {note}".rstrip(),
        "",
        "Watch: Get-Content -Wait drive\\yh_low_diff_exp\\status.txt",
    ]
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  [status] {_fmt_dur(elapsed)}  {done}/{total}  {current_id}  {note}")


def load_yh_symbols() -> str:
    env = os.environ.get("YH_SYMBOLS", "").strip()
    if env:
        return env
    bat = (REPO / "run_yh.bat").read_text(encoding="utf-8", errors="replace")
    m = re.search(r'set "YH_SYMBOLS=([^"]+)"', bat)
    if not m:
        raise RuntimeError("Could not parse YH_SYMBOLS from run_yh.bat")
    return m.group(1).strip()


def _safe_num(x) -> float:
    if x is None or x == "" or str(x).strip().upper() == "N/A":
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace("%", "").replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def _find_latest(outdir: Path, pattern: str) -> Path | None:
    files = sorted(outdir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def extract_metrics(outdir: Path) -> dict | None:
    report = _find_latest(outdir, "YH_Report_*.csv")
    if report is None:
        report = _find_latest(outdir, "YH_Audit_Report_*.csv")
    if report is None:
        return None
    with open(report, newline="", encoding="utf-8", errors="replace") as f:
        row = next(csv.DictReader(f), None)
    if not row:
        return None
    wins = int(_safe_num(row.get("Wins", 0)))
    losses = int(_safe_num(row.get("Losses", 0)))
    bes = int(_safe_num(row.get("BE", row.get("BEs", 0))))
    total_trades = int(_safe_num(row.get("Total_Trades", 0)))
    if total_trades <= 0:
        total_trades = wins + losses + bes
    return {
        "report_file": report.name,
        "Total_Trades": total_trades,
        "Total_PNL": _safe_num(row.get("Total_PNL", 0)),
        "Profit_Factor": _safe_num(row.get("Profit_Factor", 0)),
        "Max_DD": _safe_num(row.get("Max_DD", 0)),
        "Profit_Per_Capital_Day": _safe_num(row.get("Profit_Per_Capital_Day", 0)),
        "Expectancy": _safe_num(row.get("Expectancy", 0)),
        "Avg_PNL_Pct": _safe_num(row.get("Avg_PNL_Pct", 0)),
        "Wins": wins,
        "Losses": losses,
        "BE": bes,
        "Capital_Days": int(_safe_num(row.get("Capital_Days", 0))),
        "Ann_ROR": _safe_num(row.get("Ann_ROR", 0)),
        "Pct_PNL_Max_Symbol": _safe_num(row.get("Pct_PNL_Max_Symbol", 0)),
        "Pct_Wins": _safe_num(row.get("Pct_Wins", 0)),
        "Aggressive_Total_PNL": _safe_num(row.get("Aggressive_Total_PNL", 0)),
        "Aggressive_Max_DD": _safe_num(row.get("Aggressive_Max_DD", 0)),
    }


def build_cmd(py: str, outdir: Path, workers: int, symbols: str, extra_v: list[str]) -> list[str]:
    cmd = [
        py,
        str(SA / "rocket_brt.py"),
        str(DATA_DIR),
        "-o",
        str(outdir),
        "-w",
        str(workers),
        "--aggressive",
        "--use-duckdb",
        "--no-regression",
    ]
    for v in YH_COMMON_V + extra_v:
        cmd.extend(["-v", v])
    cmd.extend(["-s", symbols])
    return cmd


def run_engine_arm(
    py: str,
    arm_id: str,
    label: str,
    workers: int,
    symbols: str,
    extra_v: list[str],
    skip_existing: bool,
) -> dict:
    outdir = OUT_ROOT / arm_id
    outdir.mkdir(parents=True, exist_ok=True)
    result: dict = {"id": arm_id, "label": label, "outdir": str(outdir), "mode": "engine"}
    existing = extract_metrics(outdir)
    if skip_existing and existing is not None and existing.get("Total_Trades", 0) > 0:
        result["ok"] = True
        result["exit_code"] = 0
        result["elapsed_s"] = 0.0
        result["metrics"] = existing
        result["skipped"] = True
        return result

    cmd = build_cmd(py, outdir, workers, symbols, extra_v)
    log_path = outdir / "run.log"
    t0 = time.time()
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        log.write("CMD: " + " ".join(cmd) + "\n\n")
        log.flush()
        proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(REPO))
    elapsed = time.time() - t0
    metrics = extract_metrics(outdir)
    result["ok"] = proc.returncode == 0 and metrics is not None
    result["exit_code"] = proc.returncode
    result["elapsed_s"] = elapsed
    result["metrics"] = metrics or {}
    result["skipped"] = False
    if not result["ok"]:
        result["error"] = f"exit={proc.returncode}; see {log_path}"
    return result


def _trade_stats_from_closed(df: pd.DataFrame) -> dict:
    """Mirror YH_Report trade-level fields from a Closed CSV subset."""
    work = df.copy()
    pnl_pct = pd.to_numeric(
        work["PNL_PCT"].astype(str).str.replace("%", "", regex=False), errors="coerce"
    )
    pnl_d = pd.to_numeric(work["PNL_DOLLARS"], errors="coerce")
    days = pd.to_numeric(work.get("DAYS_HELD"), errors="coerce") if "DAYS_HELD" in work.columns else None
    n = int(len(work))
    wins = int((pnl_d > 0).sum()) if n else 0
    losses = int((pnl_d < 0).sum()) if n else 0
    bes = int((pnl_d == 0).sum()) if n else 0
    gp = float(pnl_d[pnl_d > 0].sum()) if n else 0.0
    gl = float((-pnl_d[pnl_d < 0]).sum()) if n else 0.0
    pf = (gp / gl) if gl > 0 else (float("inf") if gp > 0 else 0.0)
    total_pnl = float(pnl_d.sum()) if n else 0.0
    avg_pct = float(pnl_pct.mean()) if n and pnl_pct.notna().any() else 0.0
    win_pcts = pnl_pct[pnl_d > 0]
    loss_pcts = pnl_pct[pnl_d < 0]
    return {
        "Total_Trades": n,
        "Wins": wins,
        "Losses": losses,
        "BE": bes,
        "Pct_Wins": 100.0 * wins / n if n else 0.0,
        "Total_PNL": total_pnl,
        "Profit_Factor": float(pf) if math.isfinite(pf) else 0.0,
        "Avg_PNL_Pct": avg_pct,
        "Expectancy": total_pnl / n if n else 0.0,
        "Avg_Win_Pct": float(win_pcts.mean()) if len(win_pcts) else 0.0,
        "Avg_Loss_Pct": float(loss_pcts.mean()) if len(loss_pcts) else 0.0,
        "Avg_Days_Held": float(days.mean()) if days is not None and days.notna().any() else 0.0,
    }


def _ymd8_series(s: pd.Series) -> pd.Series:
    """Normalize DATE_OPENED-like values to YYYYMMDD strings (handles int YYYYMMDD)."""
    return s.astype(str).str.replace(r"\D", "", regex=True).str[:8]


def _same_day_keep_lowest_diff(closed: pd.DataFrame, enriched: pd.DataFrame) -> pd.DataFrame:
    """Keep the single lowest-IND_DIFF trade per DATE_OPENED (ties: first symbol)."""
    base = closed.copy()
    base["_row"] = np.arange(len(base))
    base["SYMBOL_U"] = base["SYMBOL"].astype(str).str.upper().str.strip()
    base["ENTRY8"] = _ymd8_series(base["DATE_OPENED"])
    en = enriched.copy()
    en["symbol"] = en["symbol"].astype(str).str.upper().str.strip()
    en["entry"] = _ymd8_series(en["entry"])
    merge = base.merge(
        en[["symbol", "entry", "ind_diff"]],
        left_on=["SYMBOL_U", "ENTRY8"],
        right_on=["symbol", "entry"],
        how="left",
    )
    merge = merge.dropna(subset=["ind_diff"])
    # Group by calendar entry day string
    merge = merge.sort_values(["ENTRY8", "ind_diff", "SYMBOL_U", "_row"])
    keep_idx = merge.groupby("ENTRY8", sort=False)["_row"].first()
    return closed.iloc[keep_idx.to_numpy()].copy()


def _capital_metrics_from_closed(closed_df: pd.DataFrame, *, brt_cash: float = 37037.03703703704) -> dict:
    """Match rocket_brt report formulas for Capital_Days / PPCD / Ann_ROR; Max_DD via equity sim."""
    pnl_d = pd.to_numeric(closed_df["PNL_DOLLARS"], errors="coerce").fillna(0.0)
    days = pd.to_numeric(closed_df["DAYS_HELD"], errors="coerce").fillna(0.0)
    n = int(len(closed_df))
    total_pnl = float(pnl_d.sum())
    capital_days = int(days.sum()) if n else 0
    avg_days = float(days.mean()) if n else 0.0
    ppcd = (total_pnl / capital_days) if capital_days > 0 else 0.0
    # Same Ann_ROR formula as rocket_brt._compute_trade_metrics
    if avg_days > 0 and n > 0:
        ann_ror = ((1.0 + total_pnl / (brt_cash * n)) ** (365.0 / avg_days) - 1.0) * 100.0
    else:
        ann_ror = 0.0

    max_dd = 0.0
    agg_dd = 0.0
    agg_pnl = 0.0
    try:
        from BRT_DrawdownCalc import compute_equity_metrics
        from rocket_brt import _load_symbol_data
    except ImportError:
        from stock_analysis.BRT_DrawdownCalc import compute_equity_metrics
        from stock_analysis.rocket_brt import _load_symbol_data

    trades = closed_df.to_dict(orient="records")
    syms = sorted({str(r.get("SYMBOL", "")).strip().upper() for r in trades if r.get("SYMBOL")})
    tickers: dict = {}
    for sym in syms:
        try:
            df = _load_symbol_data(sym, DATA_DIR, use_duckdb=True)
        except Exception:
            df = None
        if df is not None and not getattr(df, "empty", True):
            tickers[sym] = df
    if tickers:
        eq = compute_equity_metrics(
            trades,
            [],
            tickers,
            cash=brt_cash,
            initial_capital=500000.0,
            aggressive=True,
            aggressive_margin_interest=0.10,
            aggressive_max_multiple=2.0,
            aggressive_avg_positions=None,
            aggressive_sizing_equity_cap=10.0,
            margin_utilization=1.0,
            aggressive_sell="false",
        )
        max_dd = _safe_num(eq.get("Max_Drawdown", 0))
        agg_dd = _safe_num(eq.get("Aggressive_Max_Drawdown", 0))
        if "_equity_total_pnl" in eq:
            agg_pnl = float(eq.get("_equity_total_pnl") or 0)
        else:
            agg_pnl = float(eq.get("_final_equity", 500000.0) or 500000.0) - 500000.0
    else:
        # Chronological $ stack fallback
        eq_curve = pnl_d.cumsum() + 500000.0
        peak = eq_curve.cummax()
        dd = (peak - eq_curve) / peak.replace(0, np.nan)
        max_dd = float(dd.max() * 100.0) if len(dd) and dd.notna().any() else 0.0
        agg_dd = max_dd

    return {
        "Max_DD": max_dd,
        "Capital_Days": capital_days,
        "Profit_Per_Capital_Day": ppcd,
        "Ann_ROR": ann_ror,
        "Aggressive_Max_DD": agg_dd,
        "Aggressive_Total_PNL": agg_pnl,
    }


def run_same_day_arm(baseline_outdir: Path, workers: int = 10) -> dict:
    arm_id = "same_day_low_diff"
    outdir = OUT_ROOT / arm_id
    outdir.mkdir(parents=True, exist_ok=True)
    result: dict = {
        "id": arm_id,
        "label": "Same-day keep lowest IND_DIFF (capital recompute)",
        "outdir": str(outdir),
        "mode": "postfilter",
    }
    t0 = time.time()
    closed_path = _find_latest(baseline_outdir, "YH_Closed_*.csv")
    if closed_path is None:
        result["ok"] = False
        result["error"] = f"No YH_Closed_*.csv under {baseline_outdir}"
        result["metrics"] = {}
        result["elapsed_s"] = time.time() - t0
        return result

    from analyze_ind_diff_at_trigger_pnl import _load_brt_like, enrich_with_cache

    closed = pd.read_csv(closed_path, low_memory=False)
    # LONG only (YH production is long)
    if "SIDE" in closed.columns:
        closed = closed[closed["SIDE"].astype(str).str.upper().str.strip() == "LONG"].copy()

    loaded = _load_brt_like(closed_path, "YH")
    cache_dir = DATA_DIR / ".brt_indicator_cache"
    enriched = enrich_with_cache(loaded, cache_dir, workers=workers)
    filtered = _same_day_keep_lowest_diff(closed, enriched)
    filtered_path = outdir / "YH_Closed_same_day_low_diff.csv"
    filtered.to_csv(filtered_path, index=False)

    stats = _trade_stats_from_closed(filtered)
    # Top symbol concentration
    if len(filtered):
        pnl_by_sym = (
            pd.to_numeric(filtered["PNL_DOLLARS"], errors="coerce")
            .groupby(filtered["SYMBOL"].astype(str).str.upper())
            .sum()
        )
        total = float(pnl_by_sym.sum()) or 1.0
        stats["Pct_PNL_Max_Symbol"] = float(100.0 * pnl_by_sym.abs().max() / abs(total)) if len(pnl_by_sym) else 0.0
    else:
        stats["Pct_PNL_Max_Symbol"] = 0.0

    try:
        eq = _capital_metrics_from_closed(filtered)
        stats.update(eq)
    except Exception as e:
        result["equity_error"] = str(e)
        pnl = pd.to_numeric(filtered["PNL_DOLLARS"], errors="coerce").fillna(0.0)
        days = pd.to_numeric(filtered["DAYS_HELD"], errors="coerce").fillna(0.0)
        cd = int(days.sum()) if len(filtered) else 1
        stats["Capital_Days"] = cd
        stats["Profit_Per_Capital_Day"] = stats["Total_PNL"] / cd if cd else 0.0
        eq_curve = pnl.cumsum() + 500000.0
        peak = eq_curve.cummax()
        dd = (peak - eq_curve) / peak.replace(0, np.nan)
        stats["Max_DD"] = float(dd.max() * 100.0) if len(dd) and dd.notna().any() else 0.0
        stats["Ann_ROR"] = 0.0
        stats["Aggressive_Max_DD"] = stats["Max_DD"]
        stats["Aggressive_Total_PNL"] = 0.0
        print(f"  [warn] capital metrics fallback: {e}")

    # Write a minimal report CSV for extract_metrics compatibility
    report_path = outdir / f"YH_Report_{datetime.now().strftime('%y%m%d%H%M%S')}.csv"
    with open(report_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(stats.keys()))
        w.writeheader()
        w.writerow(stats)

    meta = {
        "baseline_closed": str(closed_path),
        "filtered_closed": str(filtered_path),
        "baseline_n": int(len(closed)),
        "filtered_n": int(len(filtered)),
        "retain_pct": 100.0 * len(filtered) / max(1, len(closed)),
    }
    if len(filtered):
        f2 = filtered.copy()
        f2["SYMBOL_U"] = f2["SYMBOL"].astype(str).str.upper().str.strip()
        f2["ENTRY8"] = _ymd8_series(f2["DATE_OPENED"])
        en2 = enriched.copy()
        en2["symbol"] = en2["symbol"].astype(str).str.upper().str.strip()
        en2["entry"] = _ymd8_series(en2["entry"])
        joined = en2.merge(
            f2[["SYMBOL_U", "ENTRY8"]],
            left_on=["symbol", "entry"],
            right_on=["SYMBOL_U", "ENTRY8"],
            how="inner",
        )
        meta["mean_ind_diff_kept"] = float(joined["ind_diff"].mean()) if len(joined) else None
    else:
        meta["mean_ind_diff_kept"] = None
    (outdir / "filter_meta.json").write_text(
        __import__("json").dumps(meta, indent=2), encoding="utf-8"
    )

    result["ok"] = True
    result["exit_code"] = 0
    result["elapsed_s"] = time.time() - t0
    result["metrics"] = stats
    result["filter_meta"] = meta
    return result


def aggregate(results: list[dict], *, jobs: int, workers: int) -> tuple[Path, Path]:
    by_id = {r["id"]: r for r in results}
    base = by_id.get("baseline")
    rows = []
    for r in results:
        m = r.get("metrics") or {}
        trades = int(m.get("Total_Trades", 0) or 0)
        dd = float(m.get("Max_DD", 0) or 0)
        gate_ok = bool(r.get("ok")) and trades >= MIN_TRADES and dd <= MAX_DD
        beat = "N"
        if base and base.get("metrics") and m and int(base["metrics"].get("Total_Trades", 0) or 0) > 0:
            bm = base["metrics"]
            beat = (
                "Y"
                if (
                    trades > 0
                    and float(m.get("Profit_Per_Capital_Day", 0))
                    > float(bm.get("Profit_Per_Capital_Day", 0))
                    and float(m.get("Total_PNL", 0)) > float(bm.get("Total_PNL", 0))
                    and float(m.get("Profit_Factor", 0)) >= float(bm.get("Profit_Factor", 0))
                )
                else "N"
            )
        rows.append(
            {
                "id": r["id"],
                "label": r.get("label", ""),
                "mode": r.get("mode", ""),
                "ok": bool(r.get("ok")),
                "exit_code": r.get("exit_code"),
                "elapsed_s": round(float(r.get("elapsed_s", 0) or 0), 1),
                "Total_Trades": trades,
                "Total_PNL": round(float(m.get("Total_PNL", 0) or 0), 2),
                "Profit_Factor": round(float(m.get("Profit_Factor", 0) or 0), 3),
                "Max_DD": round(dd, 2),
                "PPCD": round(float(m.get("Profit_Per_Capital_Day", 0) or 0), 4),
                "Expectancy": round(float(m.get("Expectancy", 0) or 0), 2),
                "Avg_PNL_Pct": round(float(m.get("Avg_PNL_Pct", 0) or 0), 3),
                "Ann_ROR": round(float(m.get("Ann_ROR", 0) or 0), 2),
                "Pct_Wins": round(float(m.get("Pct_Wins", 0) or 0), 2),
                "Pct_PNL_Max_Symbol": round(float(m.get("Pct_PNL_Max_Symbol", 0) or 0), 2),
                "Aggressive_Total_PNL": round(float(m.get("Aggressive_Total_PNL", 0) or 0), 2),
                "Aggressive_Max_DD": round(float(m.get("Aggressive_Max_DD", 0) or 0), 2),
                "gate_pass": "PASS" if gate_ok else "FAIL",
                "beat_baseline": beat,
                "outdir": r.get("outdir", ""),
                "error": r.get("error", ""),
            }
        )

    csv_path = OUT_ROOT / "comparison.csv"
    md_path = OUT_ROOT / "comparison.md"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    lines = [
        "# YH Low-IND_DIFF Capital Backtest",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Question",
        "",
        "Does a **low IND_DIFF at trigger** overlay improve YH as an *implementable* "
        "entry filter / same-day ranker (full capital path), not just post-hoc screening?",
        "",
        "Prior screening: DIFF≤3 → avg 5.72% vs 3.23%, PF 2.14 vs 1.58, retain ~34%.",
        "",
        "## Method",
        "",
        "- **baseline**: production `run_yh.bat` settings (engine BT).",
        "- **max_diff_3**: same + `-v max_ind_diff_at_trigger=3` (engine hard gate at trigger).",
        "- **same_day_low_diff**: among baseline closed trades sharing `DATE_OPENED`, keep "
        "lowest trigger IND_DIFF only; recompute trade + equity metrics.",
        f"- Hard gates: trades ≥ {MIN_TRADES}, Max_DD ≤ {MAX_DD}%.",
        f"- Concurrency: {jobs} jobs × `-w {workers}`.",
        "- Production `run_yh.bat` **not** modified.",
        "",
        "## Results",
        "",
        "| id | trades | PNL | PF | Max_DD | PPCD | Exp | Avg% | AnnROR | Win% | MaxSym% | gate | vsBase |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['id']} | {r['Total_Trades']} | {r['Total_PNL']:.0f} | {r['Profit_Factor']:.3f} | "
            f"{r['Max_DD']:.1f} | {r['PPCD']:.4f} | {r['Expectancy']:.2f} | {r['Avg_PNL_Pct']:.2f} | "
            f"{r['Ann_ROR']:.1f} | {r['Pct_Wins']:.1f} | {r['Pct_PNL_Max_Symbol']:.1f} | "
            f"{r['gate_pass']} | {r['beat_baseline']} |"
        )

    base_row = next((r for r in rows if r["id"] == "baseline"), None)
    gate_row = next((r for r in rows if r["id"] == "max_diff_3"), None)
    rank_row = next((r for r in rows if r["id"] == "same_day_low_diff"), None)

    lines.extend(["", "## Verdict", ""])

    def _beats(a: dict | None, b: dict | None) -> bool:
        if not a or not b or a["gate_pass"] != "PASS":
            return False
        return (
            a["PPCD"] > b["PPCD"]
            and a["Total_PNL"] > b["Total_PNL"]
            and a["Profit_Factor"] >= b["Profit_Factor"]
        )

    adopt_gate = _beats(gate_row, base_row)
    adopt_rank = _beats(rank_row, base_row)

    if adopt_gate and (not rank_row or gate_row["PPCD"] >= rank_row["PPCD"]):
        verdict = "needs OOS"
        summary = (
            f"**max_diff_3** beats baseline on PPCD+PNL+PF under hard gates "
            f"(PPCD {gate_row['PPCD']:.2f} vs {base_row['PPCD']:.2f}, "
            f"PF {gate_row['Profit_Factor']:.2f} vs {base_row['Profit_Factor']:.2f}, "
            f"trades {gate_row['Total_Trades']} vs {base_row['Total_Trades']}). "
            "Lift matches screening direction, but trade count drops sharply — "
            "**needs walk-forward / OOS** before any production change. "
            "**Do not** edit `run_yh.bat` yet."
        )
    elif adopt_rank:
        verdict = "needs OOS"
        summary = (
            f"**same_day_low_diff** beats baseline on PPCD+PNL+PF "
            f"(PPCD {rank_row['PPCD']:.2f} vs {base_row['PPCD']:.2f}). "
            "Soft rank is weaker than a hard DIFF≤3 gate in screening; "
            "confirm OOS before adopting. **Do not** edit `run_yh.bat` yet."
        )
    elif gate_row and base_row and gate_row["ok"] and gate_row["Avg_PNL_Pct"] > base_row["Avg_PNL_Pct"] + 0.5:
        verdict = "needs OOS"
        summary = (
            "Hard DIFF≤3 improves **per-trade** quality (avg%/PF) but does **not** clearly "
            "beat baseline on full-capital PPCD+PNL together (or fails gates). "
            "Interesting for research; **reject for production** until OOS shows capital-path lift. "
            "**Do not** edit `run_yh.bat`."
        )
    else:
        verdict = "reject"
        summary = (
            "Low-DIFF overlays do **not** improve YH on the capital path vs baseline. "
            "Prior screening lift does not survive implementable gating / same-day ranking. "
            "**Reject** for production; leave `run_yh.bat` unchanged."
        )

    lines.append(f"**Verdict: {verdict}**")
    lines.append("")
    lines.append(summary)
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- `max_ind_diff_at_trigger` is a new optional engine gate (independent of `indicator_buy`).",
            "- Same-day arm is a capital recompute on the baseline trade set (engine cannot "
            "cross-rank parallel symbol workers at entry).",
            "- Screening context: `drive/Low_IND_Diff_Overlay_PnL_By_System.md`, "
            "`drive/Followup_ABC_Integrated_Summary.md`.",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT_ROOT / "verdict.txt").write_text(f"{verdict}\n{summary}\n", encoding="utf-8")
    return csv_path, md_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--jobs", type=int, default=2, help="Concurrent engine BTs (baseline + max_diff_3)")
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument(
        "--arms",
        default="baseline,max_diff_3,same_day_low_diff",
        help="Comma list of arms to run",
    )
    args = ap.parse_args()

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    py = _resolve_python()
    symbols = load_yh_symbols()
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    session_start = time.time()
    want = {a.strip() for a in args.arms.split(",") if a.strip()}

    engine_specs = []
    if "baseline" in want:
        engine_specs.append(("baseline", "YH production baseline", []))
    if "max_diff_3" in want:
        engine_specs.append(
            ("max_diff_3", "YH + max_ind_diff_at_trigger=3", ["max_ind_diff_at_trigger=3"])
        )

    results: list[dict] = []
    total_steps = len(engine_specs) + (1 if "same_day_low_diff" in want else 0)
    done = 0

    write_status(
        started_at=started_at,
        session_start=session_start,
        current_id="starting",
        done=0,
        total=total_steps,
        note="launching engine arms",
        jobs=args.jobs,
        workers=args.workers,
    )

    if engine_specs:
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
            futs = {
                ex.submit(
                    run_engine_arm,
                    py,
                    arm_id,
                    label,
                    args.workers,
                    symbols,
                    extra_v,
                    args.skip_existing,
                ): arm_id
                for arm_id, label, extra_v in engine_specs
            }
            for fut in as_completed(futs):
                arm_id = futs[fut]
                r = fut.result()
                results.append(r)
                done += 1
                write_status(
                    started_at=started_at,
                    session_start=session_start,
                    current_id=arm_id,
                    done=done,
                    total=total_steps,
                    note=("ok" if r.get("ok") else r.get("error", "fail")),
                    jobs=args.jobs,
                    workers=args.workers,
                )

    if "same_day_low_diff" in want:
        write_status(
            started_at=started_at,
            session_start=session_start,
            current_id="same_day_low_diff",
            done=done,
            total=total_steps,
            note="post-filter + equity recompute",
            jobs=args.jobs,
            workers=args.workers,
        )
        base_dir = OUT_ROOT / "baseline"
        # Prefer just-finished baseline; else fall back to drive LatestRun
        if _find_latest(base_dir, "YH_Closed_*.csv") is None:
            # Copy LatestRun closed into baseline folder for enrich
            latest = REPO / "drive" / "YH_LatestRun_Closed.csv"
            if latest.is_file():
                base_dir.mkdir(parents=True, exist_ok=True)
                # Use LatestRun as closed source via symlink-like copy of report too
                import shutil

                dest = base_dir / "YH_Closed_from_LatestRun.csv"
                shutil.copy2(latest, dest)
                # Also copy report metrics if present for baseline row
                for pat in ("YH_Report_*.csv", "YH_LatestRun_Summary.csv"):
                    src = _find_latest(REPO / "drive", pat.replace("*", "*"))
                rep = REPO / "drive" / "YH_Report_260719094937.csv"
                if rep.is_file() and extract_metrics(base_dir) is None:
                    shutil.copy2(rep, base_dir / rep.name)
        # If baseline engine result missing from results, synthesize from report
        if not any(r["id"] == "baseline" for r in results):
            m = extract_metrics(base_dir)
            if m:
                results.append(
                    {
                        "id": "baseline",
                        "label": "YH production baseline",
                        "outdir": str(base_dir),
                        "mode": "engine",
                        "ok": True,
                        "exit_code": 0,
                        "elapsed_s": 0.0,
                        "metrics": m,
                    }
                )
        sd = run_same_day_arm(base_dir, workers=args.workers)
        results.append(sd)
        done += 1
        write_status(
            started_at=started_at,
            session_start=session_start,
            current_id="same_day_low_diff",
            done=done,
            total=total_steps,
            note=("ok" if sd.get("ok") else sd.get("error", "fail")),
            jobs=args.jobs,
            workers=args.workers,
        )

    # Stable order; backfill any arm metrics already on disk (e.g. same_day-only rerun)
    for arm_id in ("baseline", "max_diff_3", "same_day_low_diff"):
        if any(r["id"] == arm_id for r in results):
            continue
        m = extract_metrics(OUT_ROOT / arm_id)
        if m and int(m.get("Total_Trades", 0) or 0) > 0:
            results.append(
                {
                    "id": arm_id,
                    "label": arm_id,
                    "outdir": str(OUT_ROOT / arm_id),
                    "mode": "engine" if arm_id != "same_day_low_diff" else "postfilter",
                    "ok": True,
                    "exit_code": 0,
                    "elapsed_s": 0.0,
                    "metrics": m,
                }
            )
    order = {"baseline": 0, "max_diff_3": 1, "same_day_low_diff": 2}
    results.sort(key=lambda r: order.get(r["id"], 99))
    csv_path, md_path = aggregate(results, jobs=args.jobs, workers=args.workers)
    write_status(
        started_at=started_at,
        session_start=session_start,
        current_id="done",
        done=total_steps,
        total=total_steps,
        note=f"wrote {md_path.name}",
        jobs=args.jobs,
        workers=args.workers,
    )
    print(f"\nWrote {csv_path}")
    print(f"Wrote {md_path}")
    print((OUT_ROOT / "verdict.txt").read_text(encoding="utf-8"))
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
