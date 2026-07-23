"""
YH max_ind_diff_at_trigger=3 chronological walk-forward / OOS validation.

Design
------
- Fixed production YH settings (same as run_yh.bat / run_yh_low_diff_experiments.py).
- Threshold 3 is FROZEN for all OOS folds (no per-fold tuning).
- Entry windows via entry_start_date / entry_end_date (warmup history retained;
  each fold is a fresh engine BT so positions do not leak across folds).
- Primary OOS: six non-overlapping 2-year calendar folds (enough samples vs yearly).
- Optional train sensitivity: thresholds 0/3/6 on a single pre-2021 train window
  (does not change OOS decision threshold).

Concurrency: up to 3 concurrent jobs x -w 10. Does not modify run_yh.bat.

Outputs under drive/yh_low_diff_exp/oos/:
  status.txt, comparison.csv, comparison.md, folds/<id>/YH_* artifacts
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

REPO = Path(__file__).resolve().parents[1]
OUT_ROOT = REPO / "drive" / "yh_low_diff_exp" / "oos"
STATUS_PATH = OUT_ROOT / "status.txt"
DATA_DIR = REPO / "data" / "newdata" / "data"
SA = REPO / "stock_analysis"
TOOLS = REPO / "tools"
for p in (REPO, SA, TOOLS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# Reuse frozen YH production settings from the in-sample experiment harness
from run_yh_low_diff_experiments import (  # noqa: E402
    YH_COMMON_V,
    _find_latest,
    _resolve_python,
    _safe_num,
    extract_metrics,
    load_yh_symbols,
)

# Chronological 2-year OOS folds (entry years). Pre-2015 left as warmup-only.
OOS_FOLDS: list[tuple[str, str, str]] = [
    ("F1_2015_2016", "2015-01-01", "2016-12-31"),
    ("F2_2017_2018", "2017-01-01", "2018-12-31"),
    ("F3_2019_2020", "2019-01-01", "2020-12-31"),
    ("F4_2021_2022", "2021-01-01", "2022-12-31"),
    ("F5_2023_2024", "2023-01-01", "2024-12-31"),
    ("F6_2025_2026", "2025-01-01", "2026-12-31"),
]

# Single expanding-style train window for threshold sensitivity (frozen OOS still uses 3)
TRAIN_SENS: list[tuple[str, str, str, int | None]] = [
    ("TRAIN_2013_2020_t0", "2013-01-01", "2020-12-31", 0),
    ("TRAIN_2013_2020_t3", "2013-01-01", "2020-12-31", 3),
    ("TRAIN_2013_2020_t6", "2013-01-01", "2020-12-31", 6),
]


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
        "YH Low-DIFF OOS / Walk-Forward Status",
        f"started_at:     {started_at}",
        f"updated_at:     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"elapsed:        {_fmt_dur(elapsed)}",
        f"current:        {current_id}",
        f"trials:         {done}/{total} ({pct:.1f}%)",
        f"eta:            {eta}",
        f"concurrency:    {jobs} concurrent jobs x -w {workers}",
        f"note:           {note}".rstrip(),
        "",
        "Watch: Get-Content -Wait drive\\yh_low_diff_exp\\oos\\status.txt",
    ]
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  [status] {_fmt_dur(elapsed)}  {done}/{total}  {current_id}  {note}")


def build_cmd(
    py: str,
    outdir: Path,
    workers: int,
    symbols: str,
    extra_v: list[str],
) -> list[str]:
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


def run_job(
    py: str,
    job_id: str,
    label: str,
    fold_id: str,
    phase: str,
    start: str,
    end: str,
    max_diff: int | None,
    workers: int,
    symbols: str,
    skip_existing: bool,
) -> dict:
    outdir = OUT_ROOT / "folds" / job_id
    outdir.mkdir(parents=True, exist_ok=True)
    result: dict = {
        "id": job_id,
        "label": label,
        "fold_id": fold_id,
        "phase": phase,
        "entry_start": start,
        "entry_end": end,
        "max_ind_diff_at_trigger": max_diff if max_diff is not None else "",
        "outdir": str(outdir),
    }
    existing = extract_metrics(outdir)
    if skip_existing and existing is not None and existing.get("Total_Trades", 0) > 0:
        result["ok"] = True
        result["exit_code"] = 0
        result["elapsed_s"] = 0.0
        result["metrics"] = existing
        result["skipped"] = True
        return result

    extra = [
        f"entry_start_date={start}",
        f"entry_end_date={end}",
    ]
    if max_diff is not None:
        extra.append(f"max_ind_diff_at_trigger={int(max_diff)}")

    cmd = build_cmd(py, outdir, workers, symbols, extra)
    log_path = outdir / "run.log"
    t0 = time.time()
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        log.write("CMD: " + " ".join(cmd) + "\n\n")
        log.flush()
        proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(REPO))
    elapsed = time.time() - t0
    metrics = extract_metrics(outdir)
    # Verify no entry-date leakage (DATE_OPENED may be next session after signal;
    # allow a short fill lag past inclusive end_date).
    closed = _find_latest(outdir, "YH_Closed_*.csv")
    leak_n = 0
    if closed is not None:
        import pandas as pd

        df = pd.read_csv(closed, low_memory=False)
        d = df["DATE_OPENED"].astype(str).str.replace(r"\D", "", regex=True).str[:8]
        s8 = start.replace("-", "")[:8]
        e8 = end.replace("-", "")[:8]
        e_lag = (pd.Timestamp(e8) + pd.Timedelta(days=10)).strftime("%Y%m%d")
        # Prefer trigger/signal date when present
        trig_col = next(
            (c for c in ("DATE_TRIGGER", "TRIGGER_DATE", "SIGNAL_DATE", "DATE_SIGNAL") if c in df.columns),
            None,
        )
        if trig_col:
            t = df[trig_col].astype(str).str.replace(r"\D", "", regex=True).str[:8]
            leak_n = int(((t < s8) | (t > e8)).sum()) if len(t) else 0
        else:
            leak_n = int(((d < s8) | (d > e_lag)).sum()) if len(d) else 0
        result["entry_min"] = d.min() if len(d) else ""
        result["entry_max"] = d.max() if len(d) else ""
    result["entry_date_leaks"] = leak_n
    result["ok"] = proc.returncode == 0 and metrics is not None and leak_n == 0
    result["exit_code"] = proc.returncode
    result["elapsed_s"] = elapsed
    result["metrics"] = metrics or {}
    result["skipped"] = False
    if not result["ok"]:
        err = f"exit={proc.returncode}"
        if leak_n:
            err += f"; entry_date_leaks={leak_n}"
        err += f"; see {log_path}"
        result["error"] = err
    return result


def _pnl_concentration(outdir: Path) -> float:
    closed = _find_latest(outdir, "YH_Closed_*.csv")
    if closed is None:
        return 0.0
    import pandas as pd

    df = pd.read_csv(closed, low_memory=False)
    if df.empty or "PNL_DOLLARS" not in df.columns:
        return 0.0
    pnl = pd.to_numeric(df["PNL_DOLLARS"], errors="coerce").fillna(0.0)
    by = pnl.groupby(df["SYMBOL"].astype(str).str.upper()).sum()
    tot = float(by.sum())
    if abs(tot) < 1e-9 or by.empty:
        return 0.0
    return float(100.0 * by.abs().max() / abs(tot))


def _row_from_result(r: dict) -> dict:
    m = r.get("metrics") or {}
    trades = int(m.get("Total_Trades", 0) or 0)
    return {
        "id": r["id"],
        "fold_id": r.get("fold_id", ""),
        "phase": r.get("phase", ""),
        "arm": "max_diff" if r.get("max_ind_diff_at_trigger") != "" else "baseline",
        "threshold": r.get("max_ind_diff_at_trigger", ""),
        "entry_start": r.get("entry_start", ""),
        "entry_end": r.get("entry_end", ""),
        "ok": bool(r.get("ok")),
        "exit_code": r.get("exit_code"),
        "elapsed_s": round(float(r.get("elapsed_s", 0) or 0), 1),
        "Total_Trades": trades,
        "Total_PNL": round(float(m.get("Total_PNL", 0) or 0), 2),
        "Profit_Factor": round(float(m.get("Profit_Factor", 0) or 0), 3),
        "Max_DD": round(float(m.get("Max_DD", 0) or 0), 2),
        "PPCD": round(float(m.get("Profit_Per_Capital_Day", 0) or 0), 4),
        "Expectancy": round(float(m.get("Expectancy", 0) or 0), 2),
        "Avg_PNL_Pct": round(float(m.get("Avg_PNL_Pct", 0) or 0), 3),
        "Ann_ROR": round(float(m.get("Ann_ROR", 0) or 0), 2),
        "Pct_Wins": round(float(m.get("Pct_Wins", 0) or 0), 2),
        "Pct_PNL_Max_Symbol": round(
            float(m.get("Pct_PNL_Max_Symbol", 0) or 0)
            or _pnl_concentration(Path(r.get("outdir", ""))),
            2,
        ),
        "entry_min": r.get("entry_min", ""),
        "entry_max": r.get("entry_max", ""),
        "entry_date_leaks": int(r.get("entry_date_leaks", 0) or 0),
        "outdir": r.get("outdir", ""),
        "error": r.get("error", ""),
    }


def _aggregate_oos(oos_rows: list[dict]) -> dict:
    """Pair baseline vs max_diff_3 per fold; compute lift + pooled totals."""
    by_fold: dict[str, dict[str, dict]] = {}
    for r in oos_rows:
        by_fold.setdefault(r["fold_id"], {})[r["arm"]] = r

    fold_cmp = []
    wins = 0
    for fid, arms in sorted(by_fold.items()):
        b = arms.get("baseline")
        g = arms.get("max_diff")
        if not b or not g:
            continue
        beat_ppcd = g["PPCD"] > b["PPCD"]
        beat_pnl = g["Total_PNL"] > b["Total_PNL"]
        beat_pf = g["Profit_Factor"] >= b["Profit_Factor"]
        beat = beat_ppcd and beat_pnl and beat_pf
        if beat:
            wins += 1
        retain = (
            100.0 * g["Total_Trades"] / b["Total_Trades"] if b["Total_Trades"] else 0.0
        )
        fold_cmp.append(
            {
                "fold_id": fid,
                "entry_start": b["entry_start"],
                "entry_end": b["entry_end"],
                "base_trades": b["Total_Trades"],
                "gate_trades": g["Total_Trades"],
                "retain_pct": round(retain, 1),
                "base_PNL": b["Total_PNL"],
                "gate_PNL": g["Total_PNL"],
                "base_PF": b["Profit_Factor"],
                "gate_PF": g["Profit_Factor"],
                "base_DD": b["Max_DD"],
                "gate_DD": g["Max_DD"],
                "base_PPCD": b["PPCD"],
                "gate_PPCD": g["PPCD"],
                "base_Ann_ROR": b["Ann_ROR"],
                "gate_Ann_ROR": g["Ann_ROR"],
                "base_Win%": b["Pct_Wins"],
                "gate_Win%": g["Pct_Wins"],
                "base_Exp": b["Expectancy"],
                "gate_Exp": g["Expectancy"],
                "base_MaxSym%": b["Pct_PNL_Max_Symbol"],
                "gate_MaxSym%": g["Pct_PNL_Max_Symbol"],
                "beat_base": "Y" if beat else "N",
                "delta_PPCD": round(g["PPCD"] - b["PPCD"], 4),
                "delta_PNL": round(g["Total_PNL"] - b["Total_PNL"], 2),
                "delta_PF": round(g["Profit_Factor"] - b["Profit_Factor"], 3),
            }
        )

    def _pool(arm: str) -> dict:
        rows = [r for r in oos_rows if r["arm"] == arm and r["ok"]]
        trades = sum(r["Total_Trades"] for r in rows)
        pnl = sum(r["Total_PNL"] for r in rows)
        # Capital-day weighted PPCD approximation from per-fold report fields:
        # reconstruct capital_days ≈ PNL / PPCD when PPCD != 0
        cap_days = 0.0
        gp = 0.0  # rough PF via expectancy not available; use trade-weighted PF mean
        for r in rows:
            if abs(r["PPCD"]) > 1e-12:
                cap_days += r["Total_PNL"] / r["PPCD"]
            else:
                cap_days += 0.0
        ppcd = (pnl / cap_days) if cap_days > 0 else 0.0
        # Trade-weighted averages
        def tw(key: str) -> float:
            if trades <= 0:
                return 0.0
            return sum(r[key] * r["Total_Trades"] for r in rows) / trades

        # Worst (max) DD across folds — conservative aggregate
        max_dd = max((r["Max_DD"] for r in rows), default=0.0)
        # PF: cannot perfectly pool without trade lists; use trade-weighted mean PF
        pf = tw("Profit_Factor")
        return {
            "folds": len(rows),
            "Total_Trades": trades,
            "Total_PNL": round(pnl, 2),
            "Profit_Factor_tw": round(pf, 3),
            "Max_DD_worst": round(max_dd, 2),
            "PPCD_pooled": round(ppcd, 4),
            "Expectancy_tw": round(tw("Expectancy"), 2),
            "Ann_ROR_tw": round(tw("Ann_ROR"), 2),
            "Pct_Wins_tw": round(tw("Pct_Wins"), 2),
            "Avg_PNL_Pct_tw": round(tw("Avg_PNL_Pct"), 3),
        }

    base_pool = _pool("baseline")
    gate_pool = _pool("max_diff")
    retain = (
        100.0 * gate_pool["Total_Trades"] / base_pool["Total_Trades"]
        if base_pool["Total_Trades"]
        else 0.0
    )
    n_folds = len(fold_cmp)
    early = [f for f in fold_cmp if f["entry_start"] < "2021-01-01"]
    late = [f for f in fold_cmp if f["entry_start"] >= "2021-01-01"]

    def _early_late(subset: list[dict]) -> dict:
        if not subset:
            return {"n": 0, "wins": 0, "base_pnl": 0.0, "gate_pnl": 0.0, "base_ppcd": 0.0, "gate_ppcd": 0.0}
        return {
            "n": len(subset),
            "wins": sum(1 for f in subset if f["beat_base"] == "Y"),
            "base_pnl": round(sum(f["base_PNL"] for f in subset), 2),
            "gate_pnl": round(sum(f["gate_PNL"] for f in subset), 2),
            "base_ppcd": round(sum(f["base_PPCD"] for f in subset) / len(subset), 4),
            "gate_ppcd": round(sum(f["gate_PPCD"] for f in subset) / len(subset), 4),
        }

    return {
        "fold_cmp": fold_cmp,
        "n_folds": n_folds,
        "folds_won": wins,
        "base_pool": base_pool,
        "gate_pool": gate_pool,
        "retain_pct": round(retain, 1),
        "early": _early_late(early),
        "late": _early_late(late),
    }


def write_artifacts(results: list[dict], *, jobs: int, workers: int) -> tuple[Path, Path, str]:
    rows = [_row_from_result(r) for r in results]
    oos_rows = [r for r in rows if r["phase"] == "oos"]
    train_rows = [r for r in rows if r["phase"] == "train_sens"]
    agg = _aggregate_oos(oos_rows) if oos_rows else None

    csv_path = OUT_ROOT / "comparison.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    fold_csv = OUT_ROOT / "fold_comparison.csv"
    if agg and agg["fold_cmp"]:
        with open(fold_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(agg["fold_cmp"][0].keys()))
            w.writeheader()
            w.writerows(agg["fold_cmp"])

    # Verdict rules (OOS decision; threshold frozen at 3)
    verdict = "needs-more-data"
    summary = ""
    if agg and agg["n_folds"] >= 4:
        bp, gp = agg["base_pool"], agg["gate_pool"]
        won = agg["folds_won"]
        n = agg["n_folds"]
        win_frac = won / n if n else 0.0
        pool_beats = (
            gp["PPCD_pooled"] > bp["PPCD_pooled"]
            and gp["Total_PNL"] > bp["Total_PNL"]
            and gp["Profit_Factor_tw"] >= bp["Profit_Factor_tw"]
        )
        early_ok = agg["early"]["n"] == 0 or (
            agg["early"]["gate_pnl"] > agg["early"]["base_pnl"]
            and agg["early"]["gate_ppcd"] > agg["early"]["base_ppcd"]
        )
        late_ok = agg["late"]["n"] == 0 or (
            agg["late"]["gate_pnl"] > agg["late"]["base_pnl"]
            and agg["late"]["gate_ppcd"] > agg["late"]["base_ppcd"]
        )
        thin = gp["Total_Trades"] < 80 or any(
            f["gate_trades"] < 8 for f in agg["fold_cmp"]
        )
        # Concentration: reject if any gate fold MaxSym% > 40
        conc_bad = any(f["gate_MaxSym%"] > 40.0 for f in agg["fold_cmp"])

        if thin and not (pool_beats and win_frac >= 0.67):
            verdict = "needs-more-data"
            summary = (
                f"OOS sample too thin for confident adoption "
                f"(gate trades={gp['Total_Trades']}, folds_won={won}/{n}). "
                "Do not edit run_yh.bat."
            )
        elif pool_beats and win_frac >= 0.67 and early_ok and late_ok and not conc_bad:
            verdict = "adopt"
            summary = (
                f"OOS ADOPT: max_ind_diff_at_trigger=3 beats baseline on pooled "
                f"PPCD+PNL+PF and wins {won}/{n} folds "
                f"(pooled PPCD {gp['PPCD_pooled']:.2f} vs {bp['PPCD_pooled']:.2f}, "
                f"PNL ${gp['Total_PNL']:,.0f} vs ${bp['Total_PNL']:,.0f}, "
                f"PF_tw {gp['Profit_Factor_tw']:.2f} vs {bp['Profit_Factor_tw']:.2f}, "
                f"retain {agg['retain_pct']:.0f}%). "
                "Still review Max_DD_worst before production wire-up."
            )
        elif (not pool_beats) or win_frac < 0.4:
            verdict = "reject"
            summary = (
                f"OOS REJECT: gate does not consistently beat baseline "
                f"(folds_won={won}/{n}, pooled PPCD {gp['PPCD_pooled']:.2f} vs "
                f"{bp['PPCD_pooled']:.2f}, PNL ${gp['Total_PNL']:,.0f} vs "
                f"${bp['Total_PNL']:,.0f}). Leave run_yh.bat unchanged."
            )
        else:
            verdict = "needs-more-data"
            summary = (
                f"OOS MIXED: folds_won={won}/{n}, pool_beats={pool_beats}, "
                f"early_ok={early_ok}, late_ok={late_ok}, conc_bad={conc_bad}. "
                "Do not adopt yet; leave run_yh.bat unchanged."
            )
    elif not agg:
        verdict = "needs-more-data"
        summary = "No OOS results available."
    else:
        verdict = "needs-more-data"
        summary = f"Only {agg['n_folds']} OOS folds completed; need ≥4."

    # Train sensitivity note
    sens_note = ""
    if train_rows:
        by_t = {str(r["threshold"]): r for r in train_rows if r["ok"]}
        if "0" in by_t and "3" in by_t and "6" in by_t:
            t0, t3, t6 = by_t["0"], by_t["3"], by_t["6"]
            sens_note = (
                f"Train 2013–2020 sensitivity (not used to pick OOS threshold): "
                f"t0 PPCD={t0['PPCD']:.2f} n={t0['Total_Trades']}; "
                f"t3 PPCD={t3['PPCD']:.2f} n={t3['Total_Trades']}; "
                f"t6 PPCD={t6['PPCD']:.2f} n={t6['Total_Trades']}. "
            )
            if t3["PPCD"] >= t0["PPCD"] and t3["PPCD"] >= t6["PPCD"] * 0.9:
                sens_note += "Threshold 3 is competitive on train (stable)."
            else:
                sens_note += "Threshold 3 is not clearly best on train — treat OOS cautiously."

    md_path = OUT_ROOT / "comparison.md"
    lines = [
        "# YH Low-DIFF OOS / Walk-Forward Validation",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Question",
        "",
        "Does `max_ind_diff_at_trigger=3` improve YH on **chronological out-of-sample** "
        "folds (fixed settings, no per-fold tuning) enough to adopt in production?",
        "",
        "## Method",
        "",
        "- In-sample context (full history): baseline 445 / $532k / PF 1.58 / DD 12.5% / "
        "PPCD 33 / AnnROR 36.8% vs DIFF≤3: 186 / $884k / PF 2.02 / DD 16.1% / PPCD 126.6 / "
        "AnnROR 61.6%; same-day rank rejected.",
        "- **OOS folds**: six non-overlapping 2-year entry windows (2015–16 … 2025–26).",
        "- Each fold = independent engine BT with `entry_start_date` / `entry_end_date`; "
        "full prior history available for warmup/signals; **no position leak across folds**.",
        "- Arms: **baseline** vs **max_ind_diff_at_trigger=3** (threshold frozen).",
        "- Optional train sensitivity: thresholds 0/3/6 on 2013–2020 only (does not change OOS gate).",
        f"- Concurrency: {jobs} jobs × `-w {workers}`.",
        "- Production `run_yh.bat` **not** modified.",
        "",
        "## Per-fold OOS",
        "",
    ]
    if agg and agg["fold_cmp"]:
        lines.append(
            "| fold | base n | gate n | retain% | base PNL | gate PNL | base PF | gate PF | "
            "base DD | gate DD | base PPCD | gate PPCD | base AnnR | gate AnnR | "
            "base Win% | gate Win% | beat |"
        )
        lines.append(
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"
        )
        for f in agg["fold_cmp"]:
            lines.append(
                f"| {f['fold_id']} | {f['base_trades']} | {f['gate_trades']} | {f['retain_pct']:.0f} | "
                f"{f['base_PNL']:.0f} | {f['gate_PNL']:.0f} | {f['base_PF']:.2f} | {f['gate_PF']:.2f} | "
                f"{f['base_DD']:.1f} | {f['gate_DD']:.1f} | {f['base_PPCD']:.2f} | {f['gate_PPCD']:.2f} | "
                f"{f['base_Ann_ROR']:.1f} | {f['gate_Ann_ROR']:.1f} | "
                f"{f['base_Win%']:.1f} | {f['gate_Win%']:.1f} | {f['beat_base']} |"
            )
        bp, gp = agg["base_pool"], agg["gate_pool"]
        lines.extend(
            [
                "",
                "## Aggregate OOS",
                "",
                f"- Folds won (PPCD+PNL+PF): **{agg['folds_won']}/{agg['n_folds']}**",
                f"- Retained trades: **{agg['retain_pct']:.1f}%** "
                f"({gp['Total_Trades']} / {bp['Total_Trades']})",
                "",
                "| arm | trades | PNL | PF_tw | Max_DD_worst | PPCD_pooled | Exp_tw | AnnROR_tw | Win%_tw | Avg%_tw |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
                f"| baseline | {bp['Total_Trades']} | {bp['Total_PNL']:.0f} | {bp['Profit_Factor_tw']:.3f} | "
                f"{bp['Max_DD_worst']:.1f} | {bp['PPCD_pooled']:.4f} | {bp['Expectancy_tw']:.2f} | "
                f"{bp['Ann_ROR_tw']:.1f} | {bp['Pct_Wins_tw']:.1f} | {bp['Avg_PNL_Pct_tw']:.2f} |",
                f"| max_diff_3 | {gp['Total_Trades']} | {gp['Total_PNL']:.0f} | {gp['Profit_Factor_tw']:.3f} | "
                f"{gp['Max_DD_worst']:.1f} | {gp['PPCD_pooled']:.4f} | {gp['Expectancy_tw']:.2f} | "
                f"{gp['Ann_ROR_tw']:.1f} | {gp['Pct_Wins_tw']:.1f} | {gp['Avg_PNL_Pct_tw']:.2f} |",
                "",
                "### Early vs late",
                "",
                f"- Early (pre-2021 folds): wins {agg['early']['wins']}/{agg['early']['n']}; "
                f"PNL gate {agg['early']['gate_pnl']:.0f} vs base {agg['early']['base_pnl']:.0f}; "
                f"avg PPCD gate {agg['early']['gate_ppcd']:.2f} vs base {agg['early']['base_ppcd']:.2f}",
                f"- Late (2021+ folds): wins {agg['late']['wins']}/{agg['late']['n']}; "
                f"PNL gate {agg['late']['gate_pnl']:.0f} vs base {agg['late']['base_pnl']:.0f}; "
                f"avg PPCD gate {agg['late']['gate_ppcd']:.2f} vs base {agg['late']['base_ppcd']:.2f}",
            ]
        )

    if train_rows:
        lines.extend(
            [
                "",
                "## Train sensitivity (threshold 0/3/6 on 2013–2020; OOS still frozen at 3)",
                "",
                "| id | thr | trades | PNL | PF | DD | PPCD | AnnROR | Win% |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for r in sorted(train_rows, key=lambda x: str(x["threshold"])):
            lines.append(
                f"| {r['id']} | {r['threshold']} | {r['Total_Trades']} | {r['Total_PNL']:.0f} | "
                f"{r['Profit_Factor']:.3f} | {r['Max_DD']:.1f} | {r['PPCD']:.4f} | "
                f"{r['Ann_ROR']:.1f} | {r['Pct_Wins']:.1f} |"
            )
        if sens_note:
            lines.extend(["", sens_note])

    lines.extend(
        [
            "",
            "## Verdict",
            "",
            f"**Verdict: {verdict}**",
            "",
            summary,
            "",
            "## Notes",
            "",
            "- `entry_start_date` / `entry_end_date` added as universal entry window gates "
            "(independent of `sheet_rocket_buy_mode`).",
            "- Open positions at fold end may exit after `entry_end_date`; that is intentional "
            "(attribute full trade PnL to the fold that generated the entry).",
            "- Rerun: `python tools/run_yh_low_diff_oos.py --jobs 3 --workers 10`",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT_ROOT / "verdict.txt").write_text(f"{verdict}\n{summary}\n", encoding="utf-8")
    return csv_path, md_path, verdict


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--jobs", type=int, default=3, help="Concurrent engine BTs (max 3)")
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument(
        "--no-train-sens",
        action="store_true",
        help="Skip train-window threshold 0/3/6 sensitivity runs",
    )
    ap.add_argument(
        "--folds",
        default="",
        help="Comma list of fold ids to run (default: all OOS folds)",
    )
    args = ap.parse_args()
    jobs = max(1, min(3, int(args.jobs)))
    workers = max(1, int(args.workers))

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUT_ROOT / "folds").mkdir(parents=True, exist_ok=True)
    py = _resolve_python()
    symbols = load_yh_symbols()
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    session_start = time.time()

    want_folds = {x.strip() for x in args.folds.split(",") if x.strip()} or {
        f[0] for f in OOS_FOLDS
    }

    specs: list[tuple] = []
    # OOS: baseline + max_diff_3 per fold
    for fold_id, start, end in OOS_FOLDS:
        if fold_id not in want_folds:
            continue
        specs.append(
            (
                f"{fold_id}__baseline",
                f"OOS {fold_id} baseline",
                fold_id,
                "oos",
                start,
                end,
                None,
            )
        )
        specs.append(
            (
                f"{fold_id}__max_diff_3",
                f"OOS {fold_id} max_diff=3",
                fold_id,
                "oos",
                start,
                end,
                3,
            )
        )
    if not args.no_train_sens:
        for job_id, start, end, thr in TRAIN_SENS:
            specs.append(
                (
                    job_id,
                    f"Train sens thr={thr}",
                    "TRAIN_2013_2020",
                    "train_sens",
                    start,
                    end,
                    thr,
                )
            )

    total = len(specs)
    write_status(
        started_at=started_at,
        session_start=session_start,
        current_id="starting",
        done=0,
        total=total,
        note="launching",
        jobs=jobs,
        workers=workers,
    )

    results: list[dict] = []
    done = 0
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = {
            ex.submit(
                run_job,
                py,
                job_id,
                label,
                fold_id,
                phase,
                start,
                end,
                max_diff,
                workers,
                symbols,
                args.skip_existing,
            ): job_id
            for job_id, label, fold_id, phase, start, end, max_diff in specs
        }
        for fut in as_completed(futs):
            job_id = futs[fut]
            try:
                r = fut.result()
            except Exception as e:
                r = {
                    "id": job_id,
                    "label": job_id,
                    "fold_id": "",
                    "phase": "error",
                    "entry_start": "",
                    "entry_end": "",
                    "max_ind_diff_at_trigger": "",
                    "ok": False,
                    "error": str(e),
                    "metrics": {},
                    "elapsed_s": 0.0,
                    "outdir": "",
                }
            results.append(r)
            done += 1
            note = "OK" if r.get("ok") else f"FAIL {r.get('error', '')}"
            write_status(
                started_at=started_at,
                session_start=session_start,
                current_id=job_id,
                done=done,
                total=total,
                note=note,
                jobs=jobs,
                workers=workers,
            )
            m = r.get("metrics") or {}
            print(
                f"  [{done}/{total}] {job_id}: ok={r.get('ok')} trades={m.get('Total_Trades')} "
                f"PNL={m.get('Total_PNL')} PPCD={m.get('Profit_Per_Capital_Day')} "
                f"({_fmt_dur(float(r.get('elapsed_s', 0) or 0))})"
            )

    results.sort(key=lambda r: r.get("id", ""))
    csv_path, md_path, verdict = write_artifacts(results, jobs=jobs, workers=workers)
    write_status(
        started_at=started_at,
        session_start=session_start,
        current_id="done",
        done=total,
        total=total,
        note=f"verdict={verdict}",
        jobs=jobs,
        workers=workers,
    )
    print(f"\nWrote {csv_path}")
    print(f"Wrote {md_path}")
    print(f"Verdict: {verdict}")
    return 0 if all(r.get("ok") for r in results if r.get("phase") == "oos") else 1


if __name__ == "__main__":
    raise SystemExit(main())
