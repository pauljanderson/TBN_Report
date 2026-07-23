"""
Validate soft hypothesis: RL + OBV_SLOPE10=BULL.

Arms (production RL settings from run_rl.bat; run_rl.bat itself NOT modified):
  baseline              — production RL
  require_obv_bull      — mandatory_ind_states OBV_SLOPE10=BULL
  exclude_obv_bull      — exclude_ind_states OBV_SLOPE10=BULL (diagnostic)
  same_day_prefer_bull  — soft rank: on days with any BULL, keep BULL only

Also writes post-hoc association by OBV_SLOPE10 state and chronological
walk-forward fold metrics (fixed BULL hypothesis; no holdout tuning).

Concurrency: up to 3 jobs x -w 10.

Outputs under drive/rl_obv_slope10_exp/:
  association.md/csv, walkforward.csv, comparison.md/csv, status.txt, <arm>/
"""
from __future__ import annotations

import argparse
import csv
import json
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
OUT_ROOT = REPO / "drive" / "rl_obv_slope10_exp"
STATUS_PATH = OUT_ROOT / "status.txt"
DATA_DIR = REPO / "data" / "newdata" / "data"
SA = REPO / "stock_analysis"
TOOLS = REPO / "tools"
EXP = REPO / "experiments"
for p in (REPO, SA, TOOLS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

RL_CASH = 47500.0
MIN_TRADES_GATE = 25  # hard gate retain is small by design (n≈50 BULL)
MAX_DD = 35.0

REQUIRE_JSON = EXP / "rl_obv_slope10_require_bull.json"
EXCLUDE_JSON = EXP / "rl_obv_slope10_exclude_bull.json"
PER_SYMBOL = SA / "Per_Symbol_Optimized_Settings_Approved_Latest.json"

# Frozen production -v matching run_rl.bat (entry math); capital path uses --aggressive.
RL_COMMON_V = [
    "rl_mode=true",
    "brt_zones=false",
    "yh_zones=false",
    "wpbr_zones=false",
    "indicator_buy=off",
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
    jobs: int = 3,
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
        "RL OBV_SLOPE10 Experiment Status",
        f"started_at:     {started_at}",
        f"updated_at:     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"elapsed:        {_fmt_dur(elapsed)}",
        f"current:        {current_id}",
        f"trials:         {done}/{total} ({pct:.1f}%)",
        f"eta:            {eta}",
        f"concurrency:    {jobs} concurrent jobs x -w {workers}",
        f"note:           {note}".rstrip(),
        "",
        "Watch: Get-Content -Wait drive\\rl_obv_slope10_exp\\status.txt",
    ]
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  [status] {_fmt_dur(elapsed)}  {done}/{total}  {current_id}  {note}")


def load_rl_symbols() -> str:
    env = os.environ.get("RL_SYMBOLS", "").strip()
    if env:
        return env
    bat = (REPO / "run_rl.bat").read_text(encoding="utf-8", errors="replace")
    m = re.search(r'set "RL_SYMBOLS=([^"]+)"', bat)
    if not m:
        raise RuntimeError("Could not parse RL_SYMBOLS from run_rl.bat")
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
    report = _find_latest(outdir, "RL_Report_*.csv")
    if report is None:
        report = _find_latest(outdir, "RL_Audit_Report_*.csv")
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
    if PER_SYMBOL.is_file():
        cmd.extend(["--per-symbol-settings", str(PER_SYMBOL)])
    for v in RL_COMMON_V + extra_v:
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


def _ymd8_series(s: pd.Series) -> pd.Series:
    return s.astype(str).str.replace(r"\D", "", regex=True).str[:8]


def _rl_closed_to_stats_frame(path: Path) -> pd.DataFrame:
    from analyze_ind_diff_at_trigger_pnl import _load_rl

    return _load_rl(path)


def _trade_stats_frame(df: pd.DataFrame) -> dict:
    from analyze_ind_diff_at_trigger_pnl import _trade_stats

    st = _trade_stats(df)
    n = int(st["n"])
    # Year concentration
    years = {}
    if n and "entry" in df.columns:
        ys = (df["entry"].astype(str).str[:4]).value_counts(normalize=True)
        years = {str(k): float(v) for k, v in ys.items()}
        top_year = str(ys.index[0]) if len(ys) else ""
        top_year_share = float(ys.iloc[0]) if len(ys) else 0.0
    else:
        top_year, top_year_share = "", 0.0
    return {
        **st,
        "top_year": top_year,
        "top_year_share": top_year_share,
        "year_shares": years,
    }


def run_association(workers: int = 10) -> dict:
    """Post-hoc OBV_SLOPE10 BULL/BEAR/NEUTRAL at RL trigger on LatestRun (or baseline closed)."""
    from analyze_ind_signal_overlay_pnl import enrich_states

    closed_path = REPO / "drive" / "RL_LatestRun_Closed.csv"
    baseline_closed = _find_latest(OUT_ROOT / "baseline", "RL_Closed_*.csv")
    if baseline_closed is not None:
        closed_path = baseline_closed
    if not closed_path.is_file():
        raise FileNotFoundError(f"No RL closed file for association: {closed_path}")

    trades = _rl_closed_to_stats_frame(closed_path)
    cache_dir = DATA_DIR / ".brt_indicator_cache"
    enriched = enrich_states(trades, cache_dir, workers=workers)
    enriched = enriched[enriched.get("ok", True) == True].copy()  # noqa: E712
    col = "lab_OBV_SLOPE10"
    if col not in enriched.columns:
        raise RuntimeError("OBV_SLOPE10 state column missing after enrich")

    rows = []
    for state in ("BULL", "BEAR", "NEUTRAL", "ALL"):
        sub = enriched if state == "ALL" else enriched[enriched[col] == state]
        st = _trade_stats_frame(sub)
        rows.append(
            {
                "state": state,
                "n": st["n"],
                "avg_pnl_pct": st["avg_pnl_pct"],
                "median_pnl_pct": st["median_pnl_pct"],
                "total_pnl_pct": st["total_pnl_pct"],
                "total_pnl_dollars": st["total_pnl_dollars"],
                "profit_factor": st["profit_factor"],
                "win_rate": st["win_rate"],
                "expectancy_pct": st["expectancy_pct"],
                "avg_days": st["avg_days"],
                "n_symbols": st["n_symbols"],
                "top_symbol": st["top_symbol"],
                "top_symbol_share": st["top_symbol_share"],
                "top_year": st["top_year"],
                "top_year_share": st["top_year_share"],
            }
        )
    assoc = pd.DataFrame(rows)
    assoc_csv = OUT_ROOT / "association.csv"
    assoc.to_csv(assoc_csv, index=False)

    all_avg = float(assoc.loc[assoc["state"] == "ALL", "avg_pnl_pct"].iloc[0])
    lines = [
        "# RL × OBV_SLOPE10 post-hoc association",
        "",
        f"Source closed: `{closed_path}`",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "Trigger bar = session before entry. States from `.brt_indicator_cache`.",
        "",
        "| State | N | Avg% | Med% | Total% | Total$ | PF | Win% | Exp% | TopSym | TopSym% | TopYear | TopYear% |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---|---:|",
    ]
    for _, r in assoc.iterrows():
        pf = r["profit_factor"]
        pf_s = f"{pf:.2f}" if pf is not None and np.isfinite(pf) else "inf"
        lift = ""
        if r["state"] not in ("ALL",) and r["n"]:
            lift = f" ({float(r['avg_pnl_pct']) - all_avg:+.2f}pp)"
        lines.append(
            f"| {r['state']}{lift} | {int(r['n'])} | {float(r['avg_pnl_pct']):.2f} | "
            f"{float(r['median_pnl_pct']):.2f} | {float(r['total_pnl_pct']):.1f} | "
            f"{float(r['total_pnl_dollars']):.0f} | {pf_s} | {100*float(r['win_rate']):.1f} | "
            f"{float(r['expectancy_pct']):.2f} | {r['top_symbol']} | "
            f"{100*float(r['top_symbol_share'] or 0):.1f} | {r['top_year']} | "
            f"{100*float(r['top_year_share'] or 0):.1f} |"
        )
    # Symbol concentration detail for BULL
    bull = enriched[enriched[col] == "BULL"]
    if len(bull):
        lines.extend(["", "## BULL symbol concentration (n>=2)", ""])
        vc = bull["symbol"].value_counts()
        for sym, cnt in vc.items():
            if cnt < 2:
                break
            sub = bull[bull["symbol"] == sym]
            lines.append(
                f"- {sym}: n={int(cnt)}, avg={float(sub['pnl_pct'].mean()):.2f}%, "
                f"total$={float(sub['pnl_dollars'].sum()):.0f}"
            )
    assoc_md = OUT_ROOT / "association.md"
    assoc_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Persist enriched for soft-rank arm
    enriched_path = OUT_ROOT / "rl_trades_obv_enriched.csv"
    enriched.to_csv(enriched_path, index=False)
    return {
        "assoc": assoc,
        "enriched": enriched,
        "closed_path": closed_path,
        "enriched_path": enriched_path,
        "assoc_csv": assoc_csv,
        "assoc_md": assoc_md,
    }


def _trade_stats_from_rl_closed(df: pd.DataFrame) -> dict:
    work = df.copy()
    # Normalize RL native columns
    if "PNL %" in work.columns and "PNL_PCT" not in work.columns:
        work["PNL_PCT"] = work["PNL %"]
    if "DAYS HELD" in work.columns and "DAYS_HELD" not in work.columns:
        work["DAYS_HELD"] = work["DAYS HELD"]
    if "SYMBOL" not in work.columns and "symbol" in work.columns:
        work["SYMBOL"] = work["symbol"]
    if "DATE_OPENED" not in work.columns:
        if "DATE OPENED" in work.columns:
            work["DATE_OPENED"] = work["DATE OPENED"]
        elif "entry" in work.columns:
            work["DATE_OPENED"] = work["entry"]
    pnl_pct = pd.to_numeric(
        work["PNL_PCT"].astype(str).str.replace("%", "", regex=False), errors="coerce"
    )
    if "PNL_DOLLARS" in work.columns:
        pnl_d = pd.to_numeric(work["PNL_DOLLARS"], errors="coerce")
    else:
        pnl_d = pnl_pct / 100.0 * RL_CASH
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
        "Avg_Days_Held": float(days.mean()) if days is not None and days.notna().any() else 0.0,
        "_pnl_d": pnl_d,
        "_days": days if days is not None else pd.Series([0.0] * n),
        "_work": work,
    }


def _capital_metrics_from_rl_closed(closed_df: pd.DataFrame) -> dict:
    st = _trade_stats_from_rl_closed(closed_df)
    work = st.pop("_work")
    pnl_d = st.pop("_pnl_d")
    days = st.pop("_days")
    n = st["Total_Trades"]
    total_pnl = st["Total_PNL"]
    capital_days = int(days.sum()) if n else 0
    avg_days = float(days.mean()) if n else 0.0
    ppcd = (total_pnl / capital_days) if capital_days > 0 else 0.0
    if avg_days > 0 and n > 0:
        ann_ror = ((1.0 + total_pnl / (RL_CASH * n)) ** (365.0 / avg_days) - 1.0) * 100.0
    else:
        ann_ror = 0.0
    st["Capital_Days"] = capital_days
    st["Profit_Per_Capital_Day"] = ppcd
    st["Ann_ROR"] = ann_ror

    # Approximate Max_DD via chronological $ stack (fallback if equity sim fails)
    eq = pnl_d.cumsum() + 500_000.0
    peak = eq.cummax()
    dd = (peak - eq) / peak.replace(0, np.nan)
    st["Max_DD"] = float(dd.max() * 100.0) if len(dd) and dd.notna().any() else 0.0
    st["Aggressive_Max_DD"] = st["Max_DD"]
    st["Aggressive_Total_PNL"] = 0.0

    if "SYMBOL" in work.columns:
        by = pnl_d.groupby(work["SYMBOL"].astype(str).str.upper()).sum()
        tot = float(by.sum()) or 1.0
        st["Pct_PNL_Max_Symbol"] = float(100.0 * by.abs().max() / abs(tot)) if len(by) else 0.0
    else:
        st["Pct_PNL_Max_Symbol"] = 0.0

    try:
        from BRT_DrawdownCalc import compute_equity_metrics
        from rocket_brt import _load_symbol_data
    except ImportError:
        from stock_analysis.BRT_DrawdownCalc import compute_equity_metrics
        from stock_analysis.rocket_brt import _load_symbol_data

    # Build BRT-like trade dicts for equity sim
    trades = []
    for i, row in work.iterrows():
        entry = str(row.get("DATE_OPENED") or row.get("DATE OPENED") or "")
        exit_ = str(row.get("DATE CLOSED") or row.get("DATE_CLOSED") or "")
        entry8 = re.sub(r"\D", "", entry)[:8]
        exit8 = re.sub(r"\D", "", exit_)[:8]
        if len(entry8) < 8:
            continue
        entry_iso = f"{entry8[:4]}-{entry8[4:6]}-{entry8[6:8]}"
        exit_iso = f"{exit8[:4]}-{exit8[4:6]}-{exit8[6:8]}" if len(exit8) >= 8 else entry_iso
        ep = float(pd.to_numeric(row.get("ENTRY PRICE", row.get("entry_price")), errors="coerce") or 0)
        xp = float(pd.to_numeric(row.get("EXIT PRICE", row.get("exit_price")), errors="coerce") or 0)
        trades.append(
            {
                "SYMBOL": str(row.get("SYMBOL", "")).upper(),
                "DATE_OPENED": entry_iso,
                "DATE_CLOSED": exit_iso,
                "ENTRY_PRICE": ep,
                "EXIT_PRICE": xp,
                "PNL_DOLLARS": float(pnl_d.loc[i]) if i in pnl_d.index else float(pnl_d.iloc[0]),
                "DAYS_HELD": float(days.loc[i]) if i in days.index else 0.0,
                "SIDE": "LONG",
            }
        )
    syms = sorted({t["SYMBOL"] for t in trades if t["SYMBOL"]})
    tickers: dict = {}
    for sym in syms:
        try:
            df = _load_symbol_data(sym, DATA_DIR, use_duckdb=True)
        except Exception:
            df = None
        if df is not None and not getattr(df, "empty", True):
            tickers[sym] = df
    if tickers and trades:
        try:
            eqm = compute_equity_metrics(
                trades,
                [],
                tickers,
                cash=RL_CASH,
                initial_capital=500000.0,
                aggressive=True,
                aggressive_margin_interest=0.10,
                aggressive_max_multiple=2.0,
                aggressive_avg_positions=None,
                aggressive_sizing_equity_cap=True,
                margin_utilization=1.0,
                aggressive_sell="false",
            )
            st["Max_DD"] = float(eqm.get("Max_Drawdown", st["Max_DD"]) or st["Max_DD"])
            st["Aggressive_Max_DD"] = float(eqm.get("Aggressive_Max_Drawdown", st["Max_DD"]) or st["Max_DD"])
            st["Aggressive_Total_PNL"] = float(eqm.get("Aggressive_Total_PNL", 0) or 0)
            if eqm.get("Ann_ROR") is not None:
                st["Ann_ROR"] = float(eqm["Ann_ROR"])
        except Exception as e:
            st["equity_error"] = str(e)[:200]
    return st


def _same_day_prefer_bull(closed: pd.DataFrame, enriched: pd.DataFrame) -> pd.DataFrame:
    """Soft rank: if a calendar entry day has any OBV_SLOPE10=BULL, keep only those; else keep all."""
    base = closed.copy()
    base["_row"] = np.arange(len(base))
    # RL native or BRT-like
    sym_col = "SYMBOL" if "SYMBOL" in base.columns else "symbol"
    date_col = "DATE OPENED" if "DATE OPENED" in base.columns else (
        "DATE_OPENED" if "DATE_OPENED" in base.columns else "entry"
    )
    base["SYMBOL_U"] = base[sym_col].astype(str).str.upper().str.strip()
    base["ENTRY8"] = _ymd8_series(base[date_col])
    en = enriched.copy()
    en["symbol"] = en["symbol"].astype(str).str.upper().str.strip()
    en["entry"] = _ymd8_series(en["entry"])
    state_col = "lab_OBV_SLOPE10"
    merge = base.merge(
        en[["symbol", "entry", state_col]],
        left_on=["SYMBOL_U", "ENTRY8"],
        right_on=["symbol", "entry"],
        how="left",
    )
    keep_rows: list[int] = []
    for _day, g in merge.groupby("ENTRY8", sort=False):
        bulls = g[g[state_col] == "BULL"]
        chosen = bulls if len(bulls) else g
        keep_rows.extend(chosen["_row"].tolist())
    return closed.iloc[sorted(set(keep_rows))].copy()


def run_same_day_arm(baseline_outdir: Path, enriched: pd.DataFrame) -> dict:
    arm_id = "same_day_prefer_bull"
    outdir = OUT_ROOT / arm_id
    outdir.mkdir(parents=True, exist_ok=True)
    result: dict = {
        "id": arm_id,
        "label": "Same-day soft prefer OBV_SLOPE10=BULL",
        "outdir": str(outdir),
        "mode": "postfilter",
    }
    t0 = time.time()
    closed_path = _find_latest(baseline_outdir, "RL_Closed_*.csv")
    if closed_path is None:
        # Fall back to LatestRun
        closed_path = REPO / "drive" / "RL_LatestRun_Closed.csv"
    if not closed_path.is_file():
        result["ok"] = False
        result["error"] = "No RL_Closed for same-day arm"
        result["metrics"] = {}
        result["elapsed_s"] = time.time() - t0
        return result

    closed = pd.read_csv(closed_path, low_memory=False)
    filtered = _same_day_prefer_bull(closed, enriched)
    filtered_path = outdir / "RL_Closed_same_day_prefer_bull.csv"
    filtered.to_csv(filtered_path, index=False)
    stats = _capital_metrics_from_rl_closed(filtered)
    report_path = outdir / f"RL_Report_{datetime.now().strftime('%y%m%d%H%M%S')}.csv"
    with open(report_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[k for k in stats.keys() if not k.startswith("_")])
        w.writeheader()
        w.writerow({k: v for k, v in stats.items() if not k.startswith("_")})
    meta = {
        "baseline_closed": str(closed_path),
        "filtered_closed": str(filtered_path),
        "baseline_n": int(len(closed)),
        "filtered_n": int(len(filtered)),
        "retain_pct": 100.0 * len(filtered) / max(1, len(closed)),
    }
    (outdir / "filter_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    result["ok"] = True
    result["exit_code"] = 0
    result["elapsed_s"] = time.time() - t0
    result["metrics"] = stats
    result["filter_meta"] = meta
    return result


def walkforward_metrics(results: list[dict], enriched: pd.DataFrame) -> pd.DataFrame:
    """Chronological OOS folds on closed trades; fixed BULL hypothesis (no tuning)."""
    # Define folds from overall entry span
    entries = enriched["entry"].astype(str).str.replace(r"\D", "", regex=True).str[:8]
    entries = entries[entries.str.len() == 8]
    if entries.empty:
        return pd.DataFrame()
    years = sorted({int(e[:4]) for e in entries})
    folds: list[tuple[str, str, str]] = []
    # Rolling 1-year validation folds (need >=2 years)
    for y in years:
        folds.append((f"year_{y}", f"{y}0101", f"{y}1231"))
    # Early / late chronological halves
    sorted_e = sorted(entries.tolist())
    mid = sorted_e[len(sorted_e) // 2]
    folds.append(("early_half", sorted_e[0], mid))
    folds.append(("late_half", mid, sorted_e[-1]))

    rows = []
    for r in results:
        arm = r["id"]
        if r.get("mode") == "postfilter":
            path = OUT_ROOT / arm / "RL_Closed_same_day_prefer_bull.csv"
            if not path.is_file():
                continue
            closed = pd.read_csv(path, low_memory=False)
            # Attach state via enrich join
            from analyze_ind_diff_at_trigger_pnl import _load_rl

            # Rebuild minimal frame
            if "DATE OPENED" in closed.columns:
                frame = _load_rl(path)
            else:
                continue
            # Use enriched states for require/exclude simulation on postfilter already applied
            en = enriched.copy()
        else:
            path = _find_latest(OUT_ROOT / arm, "RL_Closed_*.csv")
            if path is None:
                continue
            from analyze_ind_diff_at_trigger_pnl import _load_rl

            frame = _load_rl(path)
            en = None

        # Join OBV state from enriched (symbol+entry)
        base = frame.copy()
        base["symbol"] = base["symbol"].astype(str).str.upper()
        base["entry8"] = _ymd8_series(base["entry"])
        en2 = enriched.copy()
        en2["symbol"] = en2["symbol"].astype(str).str.upper()
        en2["entry8"] = _ymd8_series(en2["entry"])
        joined = base.merge(
            en2[["symbol", "entry8", "lab_OBV_SLOPE10"]],
            on=["symbol", "entry8"],
            how="left",
        )

        for fold_name, start, end in folds:
            sub = joined[(joined["entry8"] >= start) & (joined["entry8"] <= end)]
            st = _trade_stats_frame(sub)
            rows.append(
                {
                    "arm": arm,
                    "fold": fold_name,
                    "start": start,
                    "end": end,
                    "n": st["n"],
                    "avg_pnl_pct": st["avg_pnl_pct"],
                    "median_pnl_pct": st["median_pnl_pct"],
                    "total_pnl_dollars": st["total_pnl_dollars"],
                    "profit_factor": st["profit_factor"],
                    "win_rate": st["win_rate"],
                    "expectancy_pct": st["expectancy_pct"],
                    "top_symbol": st["top_symbol"],
                    "top_symbol_share": st["top_symbol_share"],
                }
            )
    wf = pd.DataFrame(rows)
    if not wf.empty:
        wf.to_csv(OUT_ROOT / "walkforward.csv", index=False)
    return wf


def _beats(a: dict | None, b: dict | None) -> bool:
    if not a or not b:
        return False
    return (
        float(a.get("Profit_Per_Capital_Day", 0)) > float(b.get("Profit_Per_Capital_Day", 0))
        and float(a.get("Total_PNL", 0)) > float(b.get("Total_PNL", 0))
        and float(a.get("Profit_Factor", 0)) >= float(b.get("Profit_Factor", 0))
    )


def aggregate(results: list[dict], wf: pd.DataFrame, *, jobs: int, workers: int) -> tuple[Path, Path]:
    by_id = {r["id"]: r for r in results}
    base = by_id.get("baseline")
    rows = []
    for r in results:
        m = r.get("metrics") or {}
        trades = int(m.get("Total_Trades", 0) or 0)
        dd = float(m.get("Max_DD", 0) or 0)
        gate_ok = bool(r.get("ok")) and trades >= MIN_TRADES_GATE and dd <= MAX_DD
        beat = "Y" if base and _beats(m, base.get("metrics") or {}) else "N"
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

    base_row = next((r for r in rows if r["id"] == "baseline"), None)
    req_row = next((r for r in rows if r["id"] == "require_obv_bull"), None)
    excl_row = next((r for r in rows if r["id"] == "exclude_obv_bull"), None)
    soft_row = next((r for r in rows if r["id"] == "same_day_prefer_bull"), None)

    # Fold consistency: require_obv_bull avg% > baseline avg% on late_half and majority of year folds
    fold_note = "n/a"
    if not wf.empty and base_row and req_row:
        late = wf[(wf["fold"] == "late_half")]
        b_late = late[late["arm"] == "baseline"]
        r_late = late[late["arm"] == "require_obv_bull"]
        year_folds = wf[wf["fold"].str.startswith("year_")]
        wins = 0
        total_y = 0
        for fold_name, g in year_folds.groupby("fold"):
            bb = g[g["arm"] == "baseline"]
            rr = g[g["arm"] == "require_obv_bull"]
            if bb.empty or rr.empty or int(rr.iloc[0]["n"] or 0) < 5:
                continue
            total_y += 1
            if float(rr.iloc[0]["avg_pnl_pct"] or 0) > float(bb.iloc[0]["avg_pnl_pct"] or 0):
                wins += 1
        late_ok = False
        if not b_late.empty and not r_late.empty and int(r_late.iloc[0]["n"] or 0) >= 8:
            late_ok = float(r_late.iloc[0]["avg_pnl_pct"] or 0) > float(b_late.iloc[0]["avg_pnl_pct"] or 0)
        fold_note = f"year-folds beat baseline avg% {wins}/{total_y}; late_half={'Y' if late_ok else 'N'}"

    adopt_req = bool(req_row and base_row and req_row["beat_baseline"] == "Y" and req_row["gate_pass"] == "PASS")
    adopt_soft = bool(soft_row and base_row and soft_row["beat_baseline"] == "Y" and soft_row["gate_pass"] == "PASS")
    # Exclude bull should be worse if hypothesis true
    excl_supports = False
    if excl_row and base_row and excl_row["ok"]:
        excl_supports = float(excl_row["Avg_PNL_Pct"]) < float(base_row["Avg_PNL_Pct"])

    if adopt_req and "Y" in fold_note and excl_supports:
        verdict = "NEEDS-MORE-DATA"
        summary = (
            "Require-BULL beats baseline on full-sample PPCD+PNL+PF and late/year folds look supportive, "
            f"but BULL n remains small ({req_row['Total_Trades']} trades). "
            "Do not promote to production; extend OOS sample / more years before adopt."
        )
        next_step = (
            "Keep hypothesis fixed; re-run after next ~50–100 RL closes (or 1 more calendar year) "
            "and require late_half + ≥2 year-folds still beat baseline on avg% and PF."
        )
    elif adopt_req:
        verdict = "NEEDS-MORE-DATA"
        summary = (
            f"Full-sample require-BULL beats baseline, but fold consistency is weak ({fold_note}). "
            "Treat as still-unconfirmed; n is too small for production."
        )
        next_step = (
            "Do not change run_rl.bat. Re-check walk-forward after more closed trades; "
            "if late_half fails again, reject."
        )
    elif adopt_soft and not adopt_req:
        verdict = "NEEDS-MORE-DATA"
        summary = (
            "Soft same-day prefer-BULL shows a partial lift vs hard gate; still insufficient for adopt "
            f"(fold note: {fold_note})."
        )
        next_step = "Keep as watchlist soft rank only; re-validate after more RL sample."
    else:
        # Check if association lift fails to survive capital BT
        verdict = "REJECT"
        summary = (
            "Prior +5.3pp BULL association does not survive implementable RL capital backtests / "
            f"walk-forward consistency ({fold_note})."
        )
        next_step = (
            "Leave RL production unchanged. Do not add OBV_SLOPE10=BULL gate. "
            "If revisiting, require pre-registered OOS with n_BULL>=80."
        )

    # Soften REJECT if sample tiny and directionally positive but not beating
    if req_row and base_row and req_row["ok"] and req_row["Total_Trades"] < 40:
        if float(req_row["Avg_PNL_Pct"]) > float(base_row["Avg_PNL_Pct"]) and verdict == "REJECT":
            verdict = "NEEDS-MORE-DATA"
            summary = (
                "Directionally higher avg% under require-BULL but sample too small / capital metrics "
                f"do not clearly beat baseline. Fold note: {fold_note}."
            )
            next_step = (
                "No production change. Collect more RL closes; re-run this script with --skip-existing "
                "after refreshing baseline."
            )

    lines = [
        "# RL + OBV_SLOPE10=BULL validation",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Question",
        "",
        "Does **OBV_SLOPE10=BULL at RL trigger** improve RL as an implementable hard gate or "
        "same-day soft rank (capital path), beyond the post-hoc +5.3pp screen (n=50)?",
        "",
        "## Method",
        "",
        "- **baseline**: `run_rl.bat` production settings (`rl_mode=true`, per-symbol settings).",
        "- **require_obv_bull**: same + `mandatory_ind_states_path=rl_obv_slope10_require_bull.json`.",
        "- **exclude_obv_bull**: diagnostic + `exclude_ind_states_path=rl_obv_slope10_exclude_bull.json`.",
        "- **same_day_prefer_bull**: among same `DATE OPENED`, if any BULL exists keep only BULL; else keep all.",
        "- Walk-forward: chronological year folds + early/late halves on closed trades (hypothesis fixed).",
        f"- Hard gates: trades ≥ {MIN_TRADES_GATE}, Max_DD ≤ {MAX_DD}%.",
        f"- Concurrency: {jobs} jobs × `-w {workers}`.",
        "- Production `run_rl.bat` **not** modified.",
        "",
        "## Capital backtest results",
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

    lines.extend(
        [
            "",
            "## Walk-forward consistency",
            "",
            f"- {fold_note}",
            f"- Detail: `walkforward.csv`",
            "",
            "## Verdict",
            "",
            f"**{verdict}**",
            "",
            summary,
            "",
            f"**Next step:** {next_step}",
            "",
            "## Artifacts",
            "",
            "- `association.md` / `association.csv`",
            "- `comparison.csv`",
            "- `walkforward.csv`",
            "- per-arm folders under `drive/rl_obv_slope10_exp/`",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT_ROOT / "verdict.txt").write_text(f"{verdict}\n{summary}\nNEXT: {next_step}\n", encoding="utf-8")
    return csv_path, md_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument(
        "--arms",
        default="baseline,require_obv_bull,exclude_obv_bull,same_day_prefer_bull",
        help="Comma list of arms",
    )
    ap.add_argument("--association-only", action="store_true")
    args = ap.parse_args()

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    if not REQUIRE_JSON.is_file() or not EXCLUDE_JSON.is_file():
        print(f"Missing experiment JSON under {EXP}", file=sys.stderr)
        return 2

    py = _resolve_python()
    symbols = load_rl_symbols()
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    session_start = time.time()
    want = {a.strip() for a in args.arms.split(",") if a.strip()}

    write_status(
        started_at=started_at,
        session_start=session_start,
        current_id="association",
        done=0,
        total=1,
        note="post-hoc OBV_SLOPE10 association",
        jobs=args.jobs,
        workers=args.workers,
    )
    assoc_res = run_association(workers=args.workers)
    print(f"[write] {assoc_res['assoc_md']}")
    if args.association_only:
        write_status(
            started_at=started_at,
            session_start=session_start,
            current_id="done",
            done=1,
            total=1,
            note="association-only complete",
            jobs=args.jobs,
            workers=args.workers,
        )
        return 0

    engine_specs = []
    if "baseline" in want:
        engine_specs.append(("baseline", "RL production baseline", []))
    if "require_obv_bull" in want:
        engine_specs.append(
            (
                "require_obv_bull",
                "RL + require OBV_SLOPE10=BULL",
                [f"mandatory_ind_states_path={REQUIRE_JSON}"],
            )
        )
    if "exclude_obv_bull" in want:
        engine_specs.append(
            (
                "exclude_obv_bull",
                "RL + exclude OBV_SLOPE10=BULL",
                [f"exclude_ind_states_path={EXCLUDE_JSON}"],
            )
        )

    results: list[dict] = []
    total_steps = len(engine_specs) + (1 if "same_day_prefer_bull" in want else 0) + 1  # +wf
    done = 0

    write_status(
        started_at=started_at,
        session_start=session_start,
        current_id="engine",
        done=done,
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
                note = "ok" if r.get("ok") else f"FAIL {r.get('error', '')}"
                write_status(
                    started_at=started_at,
                    session_start=session_start,
                    current_id=arm_id,
                    done=done,
                    total=total_steps,
                    note=note,
                    jobs=args.jobs,
                    workers=args.workers,
                )
                print(
                    f"[{arm_id}] ok={r.get('ok')} trades={r.get('metrics', {}).get('Total_Trades')} "
                    f"elapsed={r.get('elapsed_s'):.0f}s"
                )

    if "same_day_prefer_bull" in want:
        write_status(
            started_at=started_at,
            session_start=session_start,
            current_id="same_day_prefer_bull",
            done=done,
            total=total_steps,
            note="soft rank postfilter",
            jobs=args.jobs,
            workers=args.workers,
        )
        base_dir = OUT_ROOT / "baseline"
        sd = run_same_day_arm(base_dir, assoc_res["enriched"])
        results.append(sd)
        done += 1
        write_status(
            started_at=started_at,
            session_start=session_start,
            current_id="same_day_prefer_bull",
            done=done,
            total=total_steps,
            note="ok" if sd.get("ok") else "FAIL",
            jobs=args.jobs,
            workers=args.workers,
        )

    # Stable order
    order = {"baseline": 0, "require_obv_bull": 1, "exclude_obv_bull": 2, "same_day_prefer_bull": 3}
    results.sort(key=lambda r: order.get(r["id"], 99))

    write_status(
        started_at=started_at,
        session_start=session_start,
        current_id="walkforward",
        done=done,
        total=total_steps,
        note="chronological folds",
        jobs=args.jobs,
        workers=args.workers,
    )
    wf = walkforward_metrics(results, assoc_res["enriched"])
    done += 1

    csv_path, md_path = aggregate(results, wf, jobs=args.jobs, workers=args.workers)
    write_status(
        started_at=started_at,
        session_start=session_start,
        current_id="done",
        done=done,
        total=total_steps,
        note=f"wrote {md_path.name}",
        jobs=args.jobs,
        workers=args.workers,
    )
    print(f"[write] {csv_path}")
    print(f"[write] {md_path}")
    print((OUT_ROOT / "verdict.txt").read_text(encoding="utf-8"))
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
