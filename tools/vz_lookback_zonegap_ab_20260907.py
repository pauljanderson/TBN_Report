#!/usr/bin/env python3
"""Volume Zone (VZ) lookback + zone-isolation A/B — 20260907.

Family 1: isolated live lookback arms (63/84/168/252) vs house 126.
Family 2: Closed overlay gap filters (single-TF and 126∪252 nearest).

IS judges. OOS/FULL report-only. Research only. Does not touch house pin.
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import json
import math
import os
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))
sys.path.insert(0, str(REPO / "stock_analysis"))

from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    format_money,
    overlay_ann_ror_max_dd,
)
from vol_zone_break_retest import atr14, build_zones, load_ohlcv  # noqa: E402
from _gen_too_high_diff import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    sortable_th,
)
from rocket_post_analysis import (  # noqa: E402
    apply_paul_scores_to_summary_rows,
    assess_symbol_fit,
)

STAMP = "vz_lookback_zonegap_ab_20260907"
OUT_DIR = REPO / "drive" / "paul_experiments" / STAMP
DATA_DIR = REPO / "data" / "newdata" / "data"
UNIV_PATH = REPO / "drive" / "universes" / "VZ_universe.csv"
HOUSE_PIN_PATH = REPO / "drive" / "VZ_house_last_run_ts.txt"
HOUSE_STAMP = "260907093231"
IS_CUT = date(2024, 1, 1)
SHEET = 45_000.0
INIT = DEFAULT_INITIAL_ACCOUNT
HOUSE_LOOKBACK = 126
CLOSE_DAYS = 5

ORIGINAL_REQUEST = (
    "it occurs to me that VZ was a system I came up with, out of the blue, and as we "
    "look at how well each TBN system works with the full universe, this is the best "
    "by many metrics. could we make it better? instead of 6 months highest volume would "
    "another timeframe work better? 4 months? 3 months? 8 months?12? might it make "
    "sense to have multiple different timeframe zones drawn and measured and act only "
    "when there is a certain distance between the one we are acting on and the next "
    "nearest one? give me some thoughts, and run some AB tests please, using IS and "
    "then see if OOS/full hold up"
)

LOOKBACK_ARMS = [
    {"arm": "CONTROL", "lookback": 126, "cal": "~6m (house)", "live": False},
    {"arm": "LB_63", "lookback": 63, "cal": "~3m", "live": True},
    {"arm": "LB_84", "lookback": 84, "cal": "~4m", "live": True},
    {"arm": "LB_168", "lookback": 168, "cal": "~8m", "live": True},
    {"arm": "LB_252", "lookback": 252, "cal": "~12m", "live": True},
]

GAP_ARMS = [
    {"arm": "CONTROL", "thr": 0.0, "source": "none", "label": "no gap filter (house)"},
    {"arm": "GAP_05", "thr": 0.5, "source": "tf126", "label": "single-TF ≥ 0.5 ATR"},
    {"arm": "GAP_10", "thr": 1.0, "source": "tf126", "label": "single-TF ≥ 1.0 ATR"},
    {"arm": "MULTIGAP_05", "thr": 0.5, "source": "union", "label": "multi-TF ≥ 0.5 ATR"},
    {"arm": "MULTIGAP_10", "thr": 1.0, "source": "union", "label": "multi-TF ≥ 1.0 ATR"},
]


def _f(v: Any, default: float = float("nan")) -> float:
    if v is None or v == "":
        return default
    s = str(v).strip().replace("%", "").replace(",", "").replace("$", "")
    if not s or s.upper() in {"N/A", "NONE", "NAN"}:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _parse_d(s: Any) -> Optional[date]:
    t = str(s or "").strip()
    if not t:
        return None
    compact = t.replace("-", "").replace("/", "")[:8]
    for cand, fmt in ((t[:10], "%Y-%m-%d"), (compact, "%Y%m%d"), (t[:10], "%m/%d/%Y")):
        try:
            return datetime.strptime(cand, fmt).date()
        except ValueError:
            continue
    return None


def _exit_type_norm(raw: str) -> str:
    s = str(raw or "").strip().upper().replace(" ", "_")
    if s in {"STOP", "STOP_LOSS"}:
        return "STOP_LOSS"
    if s in {"TARGET", "TIME", "GAP_UP", "GAP_DOWN"}:
        return s
    if "STOP" in s:
        return "STOP_LOSS"
    if "TARGET" in s:
        return "TARGET"
    if "TIME" in s:
        return "TIME"
    return s or "OTHER"


def read_pin(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip().splitlines()[0].strip()


def load_closed(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _parse_d(raw.get("DATE_OPENED") or raw.get("DATE OPENED"))
            closed = _parse_d(raw.get("DATE_CLOSED") or raw.get("DATE CLOSED"))
            if opened is None or closed is None:
                continue
            sym = str(raw.get("SYMBOL", "")).strip().upper()
            entry = _f(raw.get("ENTRY_PRICE") or raw.get("ENTRY PRICE"))
            if not sym or not math.isfinite(entry) or entry <= 0:
                continue
            pnl = _f(raw.get("PNL_PCT") or raw.get("PNL %"), 0.0)
            pnl_d = _f(raw.get("PNL_DOLLARS") or raw.get("PNL $"), pnl / 100.0 * SHEET)
            days = _f(raw.get("DAYS_HELD") or raw.get("DAYS HELD"), 0.0)
            r_mult = _f(raw.get("R_MULT"), float("nan"))
            if not math.isfinite(r_mult):
                r_mult = 1.5 if pnl > 0 else (-1.0 if pnl < 0 else 0.0)
            rows.append(
                {
                    "sym": sym,
                    "opened": opened,
                    "closed": closed,
                    "entry": entry,
                    "exit_px": _f(raw.get("EXIT_PRICE") or raw.get("EXIT PRICE")),
                    "pnl": pnl,
                    "pnl_d": pnl_d,
                    "days": days if math.isfinite(days) else 0.0,
                    "r": r_mult,
                    "exit": _exit_type_norm(raw.get("EXIT_TYPE") or raw.get("EXIT TYPE") or ""),
                    "zone_id": str(raw.get("ZONE_ID") or "").strip(),
                    "zone_lo": _f(raw.get("ZONE_LO")),
                    "atr": _f(raw.get("ATR_14_AT_ENTRY")),
                    "signal": _parse_d(raw.get("SIGNAL_DATE")),
                    "raw": raw,
                }
            )
    return rows


def find_closed_in_dir(d: Path) -> Optional[Path]:
    ts_file = d / "VZ_last_run_ts.txt"
    if ts_file.exists():
        stamp = read_pin(ts_file)
        p = d / f"VZ_Closed_{stamp}.csv"
        if p.exists():
            return p
    latest = d / "VZ_LatestRun_Closed.csv"
    if latest.exists():
        return latest
    hits = sorted(d.glob("VZ_Closed_*.csv"))
    return hits[-1] if hits else None


def find_report_in_dir(d: Path) -> Optional[Path]:
    ts_file = d / "VZ_last_run_ts.txt"
    if ts_file.exists():
        stamp = read_pin(ts_file)
        for name in (f"VZ_Report_{stamp}.csv", f"VZ_Audit_Report_{stamp}.csv"):
            p = d / name
            if p.exists():
                return p
    hits = sorted(d.glob("VZ_Report_*.csv"))
    return hits[-1] if hits else None


def find_audit_in_dir(d: Path) -> Optional[Path]:
    ts_file = d / "VZ_last_run_ts.txt"
    if ts_file.exists():
        stamp = read_pin(ts_file)
        p = d / f"VZ_Audit_Report_{stamp}.csv"
        if p.exists():
            return p
    hits = sorted(d.glob("VZ_Audit_Report_*.csv"))
    return hits[-1] if hits else None


def find_summary_in_dir(d: Path) -> Optional[Path]:
    ts_file = d / "VZ_last_run_ts.txt"
    if ts_file.exists():
        stamp = read_pin(ts_file)
        p = d / f"VZ_Summary_{stamp}.csv"
        if p.exists():
            return p
    hits = sorted(d.glob("VZ_Summary_*.csv"))
    return hits[-1] if hits else None


def find_equity_in_dir(d: Path) -> Optional[Path]:
    ts_file = d / "VZ_last_run_ts.txt"
    if ts_file.exists():
        stamp = read_pin(ts_file)
        for name in (f"VZ_EquityCurve_{stamp}.csv", f"VZ_EquityCurve_Regular_{stamp}.csv"):
            p = d / name
            if p.exists():
                return p
    latest = d / "VZ_LatestRun_EquityCurve.csv"
    return latest if latest.exists() else None


def read_report_row(path: Optional[Path]) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return rows[0] if rows else {}


def audit_lookback(path: Optional[Path]) -> Optional[float]:
    row = read_report_row(path)
    if not row:
        return None
    return _f(row.get("vz_lookback_days"))


def split_is_oos(trades: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return [t for t in trades if t["opened"] < IS_CUT], [t for t in trades if t["opened"] >= IS_CUT]


def _pctile(xs: list[float], q: float) -> float:
    if not xs:
        return float("nan")
    ys = sorted(xs)
    if len(ys) == 1:
        return ys[0]
    pos = q * (len(ys) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return ys[lo]
    return ys[lo] * (1.0 - (pos - lo)) + ys[hi] * (pos - lo)


def _losing_streak(pnls: list[float]) -> int:
    best = cur = 0
    for p in pnls:
        if p < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def symbol_fit_pack(trades: list[dict[str, Any]]) -> dict[str, Any]:
    empty = {
        "n_syms": 0,
        "sum_paul": 0.0,
        "mean_paul": float("nan"),
        "sum_fit": 0.0,
        "mean_fit": float("nan"),
        "sum_fit_r": 0.0,
        "mean_fit_r": float("nan"),
        "mean_pf": float("nan"),
        "mean_wo": float("nan"),
        "mean_outlier": float("nan"),
        "mean_tpy": float("nan"),
        "mean_max_win": float("nan"),
    }
    if not trades:
        return empty
    by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        by_sym[t["sym"]].append(t)
    rows: list[dict[str, Any]] = []
    fieldnames = [
        "SYMBOL",
        "PCT_WINS",
        "TOTAL_PNL",
        "SHEET_PNL",
        "AVG_PNL_PCT",
        "AVG_PNL_PCT_WO_MAX",
        "AVG_TRADES_PER_YEAR",
        "OUTLIER_PCT_OF_WINS",
        "AVG_DAYS_HELD",
        "FIT_SCORE",
        "FIT_SCORE_ROBUST",
        "PROFIT_FACTOR",
        "MAX_WIN_PCT",
    ]
    for sym, ts in by_sym.items():
        pnls = [float(t["pnl"]) for t in ts]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        n = len(ts)
        wr = 100.0 * len(wins) / n
        avg = sum(pnls) / n
        sheet = sum(float(t["pnl_d"]) for t in ts)
        days = [float(t["days"]) for t in ts if math.isfinite(t["days"])]
        avg_days = sum(days) / len(days) if days else 0.0
        opened = [t["opened"] for t in ts]
        closed = [t["closed"] for t in ts]
        span = max((max(closed) - min(opened)).days, 30)
        tpy = n / (span / 365.25)
        closed_rows = [{"PNL_PCT": p, "PNL_DOLLARS": t["pnl_d"]} for t, p in zip(ts, pnls)]
        fr = assess_symbol_fit(
            trades=n,
            wins=len(wins),
            losses=len(losses),
            pct_wins=wr,
            avg_pnl_pct=avg,
            sheet_pnl=sheet,
            avg_tpy=tpy,
            closed_rows=closed_rows,
        )
        gp = sum(wins)
        gl = abs(sum(losses))
        pf = (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0)
        rows.append(
            {
                "SYMBOL": sym,
                "PCT_WINS": wr,
                "TOTAL_PNL": sheet,
                "SHEET_PNL": sheet,
                "AVG_PNL_PCT": avg,
                "AVG_PNL_PCT_WO_MAX": fr.avg_pnl_pct_wo_max,
                "AVG_TRADES_PER_YEAR": tpy,
                "OUTLIER_PCT_OF_WINS": fr.outlier_pct_of_wins,
                "AVG_DAYS_HELD": avg_days,
                "FIT_SCORE": fr.score,
                "FIT_SCORE_ROBUST": fr.score_robust,
                "PROFIT_FACTOR": pf,
                "MAX_WIN_PCT": fr.max_win_pct,
            }
        )
    apply_paul_scores_to_summary_rows(rows, fieldnames)
    pauls = [_f(r.get("PAUL_SCORE"), 0.0) for r in rows]
    fits = [_f(r.get("FIT_SCORE"), 0.0) for r in rows]
    fitr = [_f(r.get("FIT_SCORE_ROBUST"), 0.0) for r in rows]
    pfs = [_f(r.get("PROFIT_FACTOR")) for r in rows]
    wos = [_f(r.get("AVG_PNL_PCT_WO_MAX")) for r in rows]
    outs = [_f(r.get("OUTLIER_PCT_OF_WINS")) for r in rows]
    tpys = [_f(r.get("AVG_TRADES_PER_YEAR")) for r in rows]
    mxs = [_f(r.get("MAX_WIN_PCT")) for r in rows]
    n_s = len(rows)
    return {
        "n_syms": n_s,
        "sum_paul": sum(pauls),
        "mean_paul": sum(pauls) / n_s if n_s else float("nan"),
        "sum_fit": sum(fits),
        "mean_fit": sum(fits) / n_s if n_s else float("nan"),
        "sum_fit_r": sum(fitr),
        "mean_fit_r": sum(fitr) / n_s if n_s else float("nan"),
        "mean_pf": float(np.nanmean(pfs)) if pfs else float("nan"),
        "mean_wo": float(np.nanmean(wos)) if wos else float("nan"),
        "mean_outlier": float(np.nanmean(outs)) if outs else float("nan"),
        "mean_tpy": float(np.nanmean(tpys)) if tpys else float("nan"),
        "mean_max_win": float(np.nanmean(mxs)) if mxs else float("nan"),
    }


def load_summary_pack(path: Optional[Path]) -> dict[str, Any]:
    empty = symbol_fit_pack([])
    if path is None or not path.exists():
        return empty
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    if not rows:
        return empty
    pauls = [_f(r.get("PAUL_SCORE"), 0.0) for r in rows]
    fits = [_f(r.get("FIT_SCORE"), 0.0) for r in rows]
    fitr = [_f(r.get("FIT_SCORE_ROBUST"), 0.0) for r in rows]
    pfs = [_f(r.get("PROFIT_FACTOR") or r.get("Profit_Factor")) for r in rows]
    wos = [_f(r.get("AVG_PNL_PCT_WO_MAX")) for r in rows]
    outs = [_f(r.get("OUTLIER_PCT_OF_WINS")) for r in rows]
    tpys = [_f(r.get("AVG_TRADES_PER_YEAR")) for r in rows]
    mxs = [_f(r.get("MAX_WIN_PCT")) for r in rows]
    n_s = len(rows)
    return {
        "n_syms": n_s,
        "sum_paul": sum(pauls),
        "mean_paul": sum(pauls) / n_s if n_s else float("nan"),
        "sum_fit": sum(fits),
        "mean_fit": sum(fits) / n_s if n_s else float("nan"),
        "sum_fit_r": sum(fitr),
        "mean_fit_r": sum(fitr) / n_s if n_s else float("nan"),
        "mean_pf": float(np.nanmean(pfs)) if pfs else float("nan"),
        "mean_wo": float(np.nanmean(wos)) if wos else float("nan"),
        "mean_outlier": float(np.nanmean(outs)) if outs else float("nan"),
        "mean_tpy": float(np.nanmean(tpys)) if tpys else float("nan"),
        "mean_max_win": float(np.nanmean(mxs)) if mxs else float("nan"),
    }


def book_stats(
    trades: list[dict[str, Any]],
    *,
    equity_curve_path: Optional[Path] = None,
    start_date=None,
    end_date_exclusive=None,
    host_report: Optional[dict[str, Any]] = None,
    summary_pack: Optional[dict[str, Any]] = None,
    use_host_full: bool = False,
) -> dict[str, Any]:
    n = len(trades)
    empty = {
        "n": 0,
        "wins": 0,
        "losses": 0,
        "wr": 0.0,
        "avg_pnl": 0.0,
        "avg_r": 0.0,
        "med_pnl": 0.0,
        "avg_wo_max": 0.0,
        "pf": 0.0,
        "expectancy_d": 0.0,
        "expectancy_pct": 0.0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "wl_count": 0.0,
        "wl_dollar": 0.0,
        "avg_days": 0.0,
        "med_days": 0.0,
        "p90_days": 0.0,
        "capital_days": 0.0,
        "profit_per_cd": float("nan"),
        "ann_ror": float("nan"),
        "max_dd": float("nan"),
        "calmar": float("nan"),
        "sharpe": float("nan"),
        "sharpe_source": "",
        "losing_streak": 0,
        "pct_max_sym": float("nan"),
        "pct_max_trade": float("nan"),
        "exits": {},
        "syms": 0,
        "host_ann_ror": float("nan"),
        "host_max_dd": float("nan"),
        "host_calmar": float("nan"),
        "host_sharpe": float("nan"),
        "agg_pnl": float("nan"),
        "agg_dd": float("nan"),
        "fit": symbol_fit_pack([]),
        "note": "no trades",
    }
    if n == 0:
        return empty
    pnls = [float(t["pnl"]) for t in trades]
    pnls_d = [float(t["pnl_d"]) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    win_d = [d for d in pnls_d if d > 0]
    loss_d = [d for d in pnls_d if d < 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    mx = max(pnls)
    wo = (sum(pnls) - mx) / (n - 1) if n >= 2 else pnls[0]
    days = [float(t["days"]) for t in trades if math.isfinite(t["days"])]
    cap = overlay_ann_ror_max_dd(
        trades,
        cash=SHEET,
        initial_account=INIT,
        equity_curve_path=equity_curve_path,
        start_date=start_date,
        end_date_exclusive=end_date_exclusive,
    )
    by_sym_d: dict[str, float] = defaultdict(float)
    for t in trades:
        by_sym_d[t["sym"]] += float(t["pnl_d"])
    tot_d = sum(pnls_d)
    max_sym = max(by_sym_d.values()) if by_sym_d and tot_d else 0.0
    max_tr = max(pnls_d) if pnls_d and tot_d else 0.0
    exits = Counter(str(t.get("exit") or "") for t in trades)
    fit = summary_pack if summary_pack is not None else symbol_fit_pack(trades)
    host = host_report or {}
    out = {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "wr": 100.0 * len(wins) / n,
        "avg_pnl": sum(pnls) / n,
        "avg_r": sum(float(t["r"]) for t in trades) / n,
        "med_pnl": float(np.median(pnls)),
        "avg_wo_max": wo,
        "pf": (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0),
        "expectancy_d": tot_d / n,
        "expectancy_pct": sum(pnls) / n,
        "avg_win": (sum(wins) / len(wins)) if wins else 0.0,
        "avg_loss": (sum(losses) / len(losses)) if losses else 0.0,
        "wl_count": (len(wins) / len(losses)) if losses else float(len(wins)),
        "wl_dollar": (sum(win_d) / abs(sum(loss_d))) if loss_d else (99.0 if win_d else 0.0),
        "avg_days": (sum(days) / len(days)) if days else 0.0,
        "med_days": float(np.median(days)) if days else 0.0,
        "p90_days": _pctile(days, 0.9) if days else 0.0,
        "capital_days": float(cap.get("capital_days") or 0.0),
        "profit_per_cd": (
            tot_d / float(cap["capital_days"])
            if float(cap.get("capital_days") or 0.0) > 0
            else float("nan")
        ),
        "ann_ror": float(cap.get("ann_ror", float("nan"))),
        "max_dd": float(cap.get("max_dd", float("nan"))),
        "calmar": float(cap.get("calmar", float("nan"))),
        "sharpe": float(cap.get("sharpe", float("nan"))),
        "sharpe_source": str(cap.get("sharpe_source") or ""),
        "losing_streak": _losing_streak(pnls),
        "pct_max_sym": (100.0 * max_sym / tot_d) if tot_d else float("nan"),
        "pct_max_trade": (100.0 * max_tr / tot_d) if tot_d else float("nan"),
        "exits": dict(exits),
        "syms": len({t["sym"] for t in trades}),
        "host_ann_ror": _f(host.get("Ann_ROR")),
        "host_max_dd": _f(host.get("Max_DD")),
        "host_calmar": _f(host.get("Calmar")),
        "host_sharpe": _f(host.get("Sharpe")),
        "agg_pnl": _f(host.get("Aggressive_Total_PNL")),
        "agg_dd": _f(host.get("Aggressive_Max_DD")),
        "fit": fit,
        "note": str(cap.get("note") or ""),
    }
    if use_host_full and math.isfinite(out["host_ann_ror"]):
        out["ann_ror_display"] = out["host_ann_ror"]
        out["max_dd_display"] = out["host_max_dd"]
        out["calmar_display"] = out["host_calmar"]
        out["sharpe_display"] = out["host_sharpe"]
        out["capital_note"] = "FULL host Report Ann ROR / Max DD"
    else:
        out["ann_ror_display"] = out["ann_ror"]
        out["max_dd_display"] = out["max_dd"]
        out["calmar_display"] = out["calmar"]
        out["sharpe_display"] = out["sharpe"]
        out["capital_note"] = "Closed overlay (sheet $45k / $500k)"
    return out


def score_pack(
    trades: list[dict[str, Any]],
    *,
    equity: Optional[Path] = None,
    host: Optional[dict[str, Any]] = None,
    summary: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    is_rows, oos_rows = split_is_oos(trades)
    return {
        "is": book_stats(
            is_rows,
            equity_curve_path=equity,
            end_date_exclusive=IS_CUT,
            summary_pack=None,
        ),
        "oos": book_stats(
            oos_rows,
            equity_curve_path=equity,
            start_date=IS_CUT,
            summary_pack=None,
        ),
        "full": book_stats(
            trades,
            equity_curve_path=equity,
            host_report=host,
            summary_pack=summary,
            use_host_full=bool(host),
        ),
    }


def verdict_is(arm: str, m: dict[str, Any], ctrl: dict[str, Any]) -> tuple[str, str]:
    if arm == "CONTROL":
        return "CONTROL", "House freeze reference (lookback 126 / no gap filter)"
    n, c_n = m["n"], ctrl["n"]
    if n < max(20, int(0.15 * c_n)):
        return "DISMISS", f"Sample collapsed ({n} vs ctrl {c_n})"
    d_wr = m["wr"] - ctrl["wr"]
    d_r = m["avg_r"] - ctrl["avg_r"]
    d_pnl = m["avg_pnl"] - ctrl["avg_pnl"]
    d_pf = m["pf"] - ctrl["pf"]
    d_ror = (
        m["ann_ror"] - ctrl["ann_ror"]
        if math.isfinite(m["ann_ror"]) and math.isfinite(ctrl["ann_ror"])
        else 0.0
    )
    d_dd = (
        m["max_dd"] - ctrl["max_dd"]
        if math.isfinite(m["max_dd"]) and math.isfinite(ctrl["max_dd"])
        else 0.0
    )
    d_fitr = (
        float(m["fit"]["mean_fit_r"]) - float(ctrl["fit"]["mean_fit_r"])
        if math.isfinite(m["fit"]["mean_fit_r"]) and math.isfinite(ctrl["fit"]["mean_fit_r"])
        else 0.0
    )
    better_wr = d_wr >= 1.5
    better_r = d_r >= 0.03
    better_pnl = d_pnl >= 0.15
    better_pf = d_pf >= 0.05
    better_ror = d_ror >= 15.0
    better_dd = d_dd <= -0.5
    worse_wr = d_wr <= -2.0
    worse_r = d_r <= -0.03
    worse_pnl = d_pnl <= -0.15
    worse_pf = d_pf <= -0.08
    worse_ror = d_ror <= -15.0
    worse_dd = d_dd >= 1.5
    quality_up = sum(
        [better_wr, better_r, better_pnl, better_pf, better_ror, better_dd, d_fitr >= 0.25]
    )
    quality_down = sum([worse_wr, worse_r, worse_pnl, worse_pf, worse_ror, worse_dd])
    n_ok = n >= 0.70 * c_n
    headline_flat = abs(d_wr) < 2.0 and abs(d_pnl) < 0.15
    if quality_down >= 2 and quality_up <= 1:
        if headline_flat:
            return "HOLD", "Near-flat IS WR / Avg PnL%; other metrics mixed — default HOLD"
        return "DISMISS", "Quality regresses on multiple IS metrics"
    if worse_wr and worse_pnl:
        return "DISMISS", "IS WR and Avg PnL% both worse"
    if quality_up >= 3 and n_ok and quality_down == 0:
        return "KEEP", "IS quality improves on several metrics without collapsing N"
    if quality_up >= 2 and n_ok and quality_down == 0:
        return "LEAN KEEP", "IS quality lift; N holds"
    if quality_up >= 2 and (not n_ok) and n >= 0.40 * c_n and quality_down == 0:
        return "HOLD", "Quality up but N thinned — not KEEP"
    if quality_down >= 1 and quality_up == 0:
        return "DISMISS", "IS quality worse / no offsetting lift"
    return "HOLD", "Mixed / flat vs freeze — no clear edge"


def oos_softens(arm: dict[str, Any], ctrl: dict[str, Any]) -> bool:
    if arm["n"] < 20 or ctrl["n"] < 20:
        return False
    d_wr = arm["wr"] - ctrl["wr"]
    d_pnl = arm["avg_pnl"] - ctrl["avg_pnl"]
    d_ror = (
        arm["ann_ror"] - ctrl["ann_ror"]
        if math.isfinite(arm["ann_ror"]) and math.isfinite(ctrl["ann_ror"])
        else 0.0
    )
    return (d_wr <= -3.0 and d_pnl <= -0.2) or (d_ror <= -15.0 and d_pnl < 0.5)


def fmt_num(x: Any, nd: int = 2) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(v):
        return "—"
    return f"{v:.{nd}f}"


def fmt_delta(x: Any, nd: int = 2) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(v):
        return "—"
    return f"{v:+.{nd}f}"


def run_isolated_lookback(lookback: int, out_dir: Path, workers: int) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = find_closed_in_dir(out_dir)
    if existing is not None:
        audit = find_audit_in_dir(out_dir) or find_report_in_dir(out_dir)
        lb = audit_lookback(audit)
        if lb is not None and abs(lb - lookback) < 0.1:
            print(f"[lookback] reuse {existing} lookback={lb}", flush=True)
            return existing
        print(f"[lookback] existing Closed lookback={lb} != {lookback}; rerunning", flush=True)
    env = os.environ.copy()
    env.pop("VZ_SYMBOLS", None)
    env.pop("VZ_UNIVERSE_CSV", None)
    env["VZ_LOOKBACK"] = str(lookback)
    env["VZ_WORKERS"] = str(workers)
    rel_out = out_dir.relative_to(REPO).as_posix().replace("/", "\\")
    cmd = (
        f"run_vz.bat drive\\universes\\VZ_universe.csv "
        f"-o {rel_out} -v vz_lookback_days={lookback}"
    )
    pin_before = read_pin(HOUSE_PIN_PATH)
    print(f"[lookback] {cmd}", flush=True)
    subprocess.run(cmd, shell=True, check=True, cwd=str(REPO), env=env)
    pin_after = read_pin(HOUSE_PIN_PATH)
    if pin_after != pin_before:
        raise RuntimeError(
            f"House pin changed {pin_before} -> {pin_after}; aborting (must stay {HOUSE_STAMP})"
        )
    closed = find_closed_in_dir(out_dir)
    if closed is None:
        raise FileNotFoundError(f"no Closed in {out_dir}")
    audit = find_audit_in_dir(out_dir) or find_report_in_dir(out_dir)
    lb = audit_lookback(audit)
    print(f"[lookback] wrote {closed} audit_lookback={lb}", flush=True)
    if lb is not None and abs(lb - lookback) > 0.1:
        raise RuntimeError(f"lookback mismatch: wanted {lookback} got {lb} in {audit}")
    return closed


def _ohlc_path(sym: str) -> Optional[Path]:
    for name in (f"{sym}.csv", f"{sym}.CSV"):
        p = DATA_DIR / name
        if p.is_file():
            return p
    return None


def _zone_date(zone_id: str) -> Optional[date]:
    s = str(zone_id or "").strip()
    if "_" not in s:
        return None
    return _parse_d(s.split("_", 1)[1].strip()[:10])


def edge_gap_atr(lo: float, hi: float, olo: float, ohi: float, atr: float) -> float:
    if not (math.isfinite(lo) and math.isfinite(hi) and math.isfinite(olo) and math.isfinite(ohi)):
        return float("nan")
    if not math.isfinite(atr) or atr <= 0:
        return float("nan")
    if lo <= ohi and olo <= hi:
        return 0.0
    return min(abs(lo - ohi), abs(hi - olo)) / atr


def _hl_zones(df: pd.DataFrame, lookback: int) -> list[Any]:
    if len(df) <= lookback:
        return []
    return [z for z in build_zones(df, lookback) if getattr(z, "kind", "") == "HL"]


def _merge_union(z126: list[Any], z252: list[Any]) -> list[Any]:
    by_id: dict[str, Any] = {}
    for z in list(z126) + list(z252):
        zid = str(getattr(z, "zone_id", "") or "")
        if not zid:
            continue
        prev = by_id.get(zid)
        if prev is None or int(z.created_on_idx) < int(prev.created_on_idx):
            by_id[zid] = z
    return list(by_id.values())


def nearest_gap(
    zones: list[Any],
    *,
    self_id: str,
    self_lo: float,
    self_hi: float,
    signal_idx: int,
    atr: float,
) -> tuple[float, int, str]:
    """Return (min_gap_atr, n_neighbors, nearest_id). inf if no neighbors."""
    best = float("inf")
    nearest = ""
    n_nb = 0
    for z in zones:
        if int(z.created_on_idx) > int(signal_idx):
            continue
        zid = str(z.zone_id)
        if zid == self_id:
            continue
        n_nb += 1
        g = edge_gap_atr(self_lo, self_hi, float(z.lo), float(z.hi), atr)
        if math.isfinite(g) and g < best:
            best = g
            nearest = zid
    return best, n_nb, nearest


def attach_gaps(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Attach single-TF and multi-TF nearest gaps onto house trades."""
    by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        by_sym[t["sym"]].append(t)
    notes = {
        "symbols": 0,
        "missing_ohlc": 0,
        "unmatched_zone": 0,
        "no_atr": 0,
        "no_signal": 0,
        "ok": 0,
    }
    cache_df: dict[str, pd.DataFrame] = {}
    cache_z: dict[tuple[str, int], list[Any]] = {}
    for sym, ts in by_sym.items():
        path = _ohlc_path(sym)
        if path is None:
            notes["missing_ohlc"] += 1
            for t in ts:
                t["gap126"] = float("inf")
                t["gap_union"] = float("inf")
                t["gap_note"] = "missing_ohlc"
            continue
        df = load_ohlcv(path)
        cache_df[sym] = df
        notes["symbols"] += 1
        dates = [pd.Timestamp(x).date() for x in df["Date"]]
        date_to_idx = {d: i for i, d in enumerate(dates)}
        atr = atr14(df)
        highs = df["High"].to_numpy(dtype=np.float64)
        lows = df["Low"].to_numpy(dtype=np.float64)
        z126 = _hl_zones(df, 126)
        z252 = _hl_zones(df, 252)
        cache_z[(sym, 126)] = z126
        cache_z[(sym, 252)] = z252
        z_union = _merge_union(z126, z252)
        z126_by_id = {str(z.zone_id): z for z in z126}

        for t in ts:
            sig = t.get("signal") or t["opened"]
            sig_idx = date_to_idx.get(sig)
            if sig_idx is None:
                # nearest bar within 3 calendar days
                best = None
                for d, i in date_to_idx.items():
                    delta = abs((d - sig).days)
                    if delta <= 3 and (best is None or delta < best[0]):
                        best = (delta, i)
                sig_idx = best[1] if best else None
            if sig_idx is None:
                notes["no_signal"] += 1
                t["gap126"] = float("inf")
                t["gap_union"] = float("inf")
                t["gap_note"] = "no_signal_idx"
                continue
            atr_i = float(atr[sig_idx]) if sig_idx < len(atr) else float("nan")
            if not math.isfinite(atr_i) or atr_i <= 0:
                atr_i = float(t["atr"]) if math.isfinite(t.get("atr", float("nan"))) else float("nan")
            if not math.isfinite(atr_i) or atr_i <= 0:
                notes["no_atr"] += 1
                t["gap126"] = float("inf")
                t["gap_union"] = float("inf")
                t["gap_note"] = "no_atr"
                continue
            zid = t.get("zone_id") or ""
            zself = z126_by_id.get(zid)
            if zself is not None:
                lo, hi = float(zself.lo), float(zself.hi)
            else:
                notes["unmatched_zone"] += 1
                zd = _zone_date(zid)
                zidx = date_to_idx.get(zd) if zd else None
                if zidx is not None:
                    lo, hi = float(lows[zidx]), float(highs[zidx])
                elif math.isfinite(t.get("zone_lo", float("nan"))):
                    lo = float(t["zone_lo"])
                    hi = lo
                else:
                    t["gap126"] = float("inf")
                    t["gap_union"] = float("inf")
                    t["gap_note"] = "unmatched_no_band"
                    continue
            g126, n126, n126_id = nearest_gap(
                z126, self_id=zid, self_lo=lo, self_hi=hi, signal_idx=sig_idx, atr=atr_i
            )
            gun, nun, nun_id = nearest_gap(
                z_union, self_id=zid, self_lo=lo, self_hi=hi, signal_idx=sig_idx, atr=atr_i
            )
            t["gap126"] = g126
            t["gap_union"] = gun
            t["n_nb126"] = n126
            t["n_nb_union"] = nun
            t["nearest126"] = n126_id
            t["nearest_union"] = nun_id
            t["gap_note"] = "ok"
            notes["ok"] += 1
    return notes


def filter_gap(trades: list[dict[str, Any]], *, source: str, thr: float) -> list[dict[str, Any]]:
    if source == "none" or thr <= 0:
        return list(trades)
    key = "gap126" if source == "tf126" else "gap_union"
    kept = []
    for t in trades:
        g = t.get(key, float("inf"))
        if not math.isfinite(g):
            # unmatched / missing: keep (do not bias-drop)
            kept.append(t)
            continue
        if g >= thr:
            kept.append(t)
    return kept


def trade_key(t: dict[str, Any]) -> tuple[str, str, float]:
    return (t["sym"], t["opened"].isoformat() if t["opened"] else "", round(float(t["entry"]), 2))


def write_trade_diff(
    out_path: Path,
    *,
    title: str,
    ctrl_trades: list[dict[str, Any]],
    cand_trades: list[dict[str, Any]],
    arm: str,
) -> None:
    c_map = {trade_key(t): t for t in ctrl_trades}
    k_map = {trade_key(t): t for t in cand_trades}
    exact = []
    used_c, used_k = set(), set()
    for k, ts in c_map.items():
        if k in k_map:
            exact.append((ts, k_map[k]))
            used_c.add(id(ts))
            used_k.add(id(k_map[k]))
    c_left = [t for t in ctrl_trades if id(t) not in used_c]
    k_avail = [t for t in cand_trades if id(t) not in used_k]
    close_matches = []
    for ts in list(c_left):
        best_i = None
        best_score = None
        for i, tl in enumerate(k_avail):
            if ts["sym"] != tl["sym"]:
                continue
            dopen = abs((ts["opened"] - tl["opened"]).days)
            if dopen > CLOSE_DAYS:
                continue
            same_close = ts["closed"] == tl["closed"]
            exit_close = (
                math.isfinite(ts.get("exit_px", float("nan")))
                and math.isfinite(tl.get("exit_px", float("nan")))
                and abs(ts["exit_px"] - tl["exit_px"]) / max(abs(tl["exit_px"]), 1e-9) <= 0.02
            )
            if not (same_close or exit_close):
                continue
            score = (dopen, abs(ts["entry"] - tl["entry"]))
            if best_score is None or score < best_score:
                best_i, best_score = i, score
        if best_i is not None:
            tl = k_avail.pop(best_i)
            close_matches.append((ts, tl))
            used_c.add(id(ts))
            used_k.add(id(tl))
    only_c = [t for t in ctrl_trades if id(t) not in used_c]
    only_k = [t for t in cand_trades if id(t) not in used_k]

    def row_html(tag: str, t: dict[str, Any], other: Optional[dict[str, Any]] = None) -> str:
        opened = t["opened"].isoformat() if t.get("opened") else ""
        closed = t["closed"].isoformat() if t.get("closed") else ""
        extra = ""
        if other is not None:
            extra = (
                f"<td>{html_mod.escape(str(other.get('exit') or ''))}</td>"
                f"<td>{fmt_num(other.get('pnl'))}</td>"
                f"<td>{other['closed'].isoformat() if other.get('closed') else ''}</td>"
            )
        return (
            f"<tr><td>{html_mod.escape(tag)}</td>"
            f"<td>{html_mod.escape(t['sym'])}</td>"
            f"<td>{opened}</td><td>{fmt_num(t.get('entry'))}</td>"
            f"<td>{html_mod.escape(str(t.get('exit') or ''))}</td>"
            f"<td>{fmt_num(t.get('pnl'))}</td><td>{fmt_num(t.get('days'), 1)}</td>"
            f"<td>{closed}</td>{extra}</tr>"
        )

    th_simple = "".join(
        sortable_th(a, b)
        for a, b in [
            ("Bucket", "text"),
            ("Symbol", "text"),
            ("Opened", "date"),
            ("Entry", "num"),
            ("Exit", "text"),
            ("PnL%", "num"),
            ("Days", "num"),
            ("Closed", "date"),
        ]
    )
    th_close = "".join(
        sortable_th(a, b)
        for a, b in [
            ("Bucket", "text"),
            ("Symbol", "text"),
            ("Opened", "date"),
            ("Entry", "num"),
            ("Exit ctrl", "text"),
            ("PnL% ctrl", "num"),
            ("Days", "num"),
            ("Closed ctrl", "date"),
            ("Exit cand", "text"),
            ("PnL% cand", "num"),
            ("Closed cand", "date"),
        ]
    )
    body_old = "".join(row_html("ONLY_IN_CONTROL (old)", t) for t in sorted(only_c, key=lambda x: (x["sym"], x["opened"])))
    body_new = "".join(row_html("ONLY_IN_CANDIDATE (new)", t) for t in sorted(only_k, key=lambda x: (x["sym"], x["opened"])))
    body_ex = "".join(row_html("EXACT", a) for a, _ in exact)
    body_cl = "".join(row_html("CLOSE_ENOUGH", a, b) for a, b in close_matches)

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>{html_mod.escape(title)}</title>
<style>
body {{ font-family: Segoe UI, Georgia, serif; margin: 24px; color: #1a1a18; background: #fafaf8; }}
.muted {{ color: #5c5c56; }}
table.sortable {{ border-collapse: collapse; width: 100%; background: #fff; margin: 12px 0 28px; font-size: 13px; }}
table.sortable th, table.sortable td {{ border: 1px solid #d8d8d0; padding: 6px 8px; }}
table.sortable th {{ background: #f0f0ea; }}
{SORTABLE_TH_CSS}
</style></head><body>
<h1>{html_mod.escape(title)}</h1>
<div class="callout" style="background:#eef2ff;border:1px solid #c7d2fe;padding:12px 14px;margin:1rem 0;">
  <p><strong>What you asked</strong></p>
  <blockquote>{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
  <p><strong>In plain English</strong></p>
  <p>This page lists trades the house book took that the candidate dropped (old),
  trades the candidate added (new), exact matches, and close-enough matches
  (same symbol, entry within 5 calendar days, same/close exit). Volume Zone (VZ)
  research only — not gold.</p>
</div>
<p class="muted">Arm {html_mod.escape(arm)} vs house {HOUSE_STAMP}. Click column headers to sort.</p>
<p>Exact {len(exact)} · Close-enough {len(close_matches)} · Old {len(only_c)} · New {len(only_k)}</p>
<h2>Old — only in control</h2>
<table class="sortable"><thead><tr>{th_simple}</tr></thead><tbody>{body_old or "<tr><td colspan='8'>none</td></tr>"}</tbody></table>
<h2>New — only in candidate</h2>
<table class="sortable"><thead><tr>{th_simple}</tr></thead><tbody>{body_new or "<tr><td colspan='8'>none</td></tr>"}</tbody></table>
<h2>Close-enough</h2>
<table class="sortable"><thead><tr>{th_close}</tr></thead><tbody>{body_cl or "<tr><td colspan='11'>none</td></tr>"}</tbody></table>
<h2>Exact</h2>
<table class="sortable"><thead><tr>{th_simple}</tr></thead><tbody>{body_ex or "<tr><td colspan='8'>none</td></tr>"}</tbody></table>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    out_path.write_text(html, encoding="utf-8")
    print(f"[diff] {out_path} old={len(only_c)} new={len(only_k)} exact={len(exact)} close={len(close_matches)}")


def _exit_mix_s(exits: dict[str, int], n: int) -> str:
    if n <= 0:
        return ""
    return ", ".join(f"{k}={v}({100.0 * v / n:.0f}%)" for k, v in sorted(exits.items()))


def write_family_html(
    out_path: Path,
    *,
    title: str,
    family: str,
    packs: list[dict[str, Any]],
    extra_note: str,
) -> None:
    ctrl = next(p for p in packs if p["arm"] == "CONTROL")

    def row_class(v: str) -> str:
        if v in ("KEEP", "LEAN KEEP"):
            return "keep"
        if v == "DISMISS":
            return "dismiss"
        if v == "HOLD":
            return "hold"
        return ""

    def pack_row(p: dict[str, Any], key: str) -> str:
        m = p[key]
        c = ctrl[key]
        d_n = m["n"] - c["n"]
        d_wr = m["wr"] - c["wr"]
        d_r = m["avg_r"] - c["avg_r"]
        d_pnl = m["avg_pnl"] - c["avg_pnl"]
        d_ror = (
            m["ann_ror"] - c["ann_ror"]
            if math.isfinite(m["ann_ror"]) and math.isfinite(c["ann_ror"])
            else float("nan")
        )
        d_dd = (
            m["max_dd"] - c["max_dd"]
            if math.isfinite(m["max_dd"]) and math.isfinite(c["max_dd"])
            else float("nan")
        )
        fit = m["fit"]
        cfit = c["fit"]
        return (
            "<tr class='{cls}'>"
            "<td>{arm}</td><td>{knob}</td>"
            "<td>{n}</td><td>{wr}</td><td>{avg}</td><td>{avgr}</td><td>{wo}</td>"
            "<td>{ror}</td><td>{dd}</td><td>{cal}</td><td>{sh}</td><td>{pf}</td>"
            "<td>{exp}</td><td>{aw}</td><td>{al}</td><td>{wlc}</td><td>{wld}</td>"
            "<td>{adays}</td><td>{mdays}</td><td>{p90}</td><td>{cdays}</td><td>{ppcd}</td>"
            "<td>{streak}</td><td>{pms}</td><td>{pmt}</td>"
            "<td>{mfitr}</td><td>{mpaul}</td><td>{mwo}</td><td>{mout}</td><td>{mtpy}</td>"
            "<td>{dn}</td><td>{dwr}</td><td>{dr}</td><td>{dpnl}</td><td>{dror}</td>"
            "<td>{ddd}</td><td>{dpf}</td>"
            "<td>{verdict}</td><td>{why}</td><td>{oos}</td><td>{mix}</td>"
            "</tr>"
        ).format(
            cls=row_class(p["verdict"]),
            arm=html_mod.escape(p["arm"]),
            knob=html_mod.escape(p["knob"]),
            n=m["n"],
            wr=fmt_num(m["wr"], 1),
            avg=fmt_num(m["avg_pnl"]),
            avgr=fmt_num(m["avg_r"]),
            wo=fmt_num(m["avg_wo_max"]),
            ror=fmt_num(m["ann_ror"]),
            dd=fmt_num(m["max_dd"]),
            cal=fmt_num(m["calmar"]),
            sh=fmt_num(m["sharpe"]),
            pf=fmt_num(m["pf"]),
            exp=format_money(m.get("expectancy_d")),
            aw=fmt_num(m["avg_win"]),
            al=fmt_num(m["avg_loss"]),
            wlc=fmt_num(m["wl_count"]),
            wld=fmt_num(m["wl_dollar"]),
            adays=fmt_num(m["avg_days"], 1),
            mdays=fmt_num(m["med_days"], 1),
            p90=fmt_num(m["p90_days"], 1),
            cdays=fmt_num(m["capital_days"], 0),
            ppcd=format_money(m.get("profit_per_cd")),
            streak=m["losing_streak"],
            pms=fmt_num(m["pct_max_sym"], 1),
            pmt=fmt_num(m["pct_max_trade"], 1),
            mfitr=fmt_num(fit["mean_fit_r"]),
            mpaul=fmt_num(fit["mean_paul"]),
            mwo=fmt_num(fit["mean_wo"]),
            mout=fmt_num(fit["mean_outlier"], 1),
            mtpy=fmt_num(fit["mean_tpy"]),
            dn=f"{d_n:+d}",
            dwr=fmt_delta(d_wr, 1),
            dr=fmt_delta(d_r),
            dpnl=fmt_delta(d_pnl),
            dror=fmt_delta(d_ror, 1),
            ddd=fmt_delta(d_dd),
            dpf=fmt_delta(m["pf"] - c["pf"]),
            verdict=html_mod.escape(p["verdict"]),
            why=html_mod.escape(p["why"]),
            oos=html_mod.escape(p.get("oos_note", "")),
            mix=html_mod.escape(_exit_mix_s(m["exits"], m["n"])),
        )

    th = "".join(
        sortable_th(a, b)
        for a, b in [
            ("Arm", "text"),
            ("Knob", "text"),
            ("N", "num"),
            ("Win %", "num"),
            ("Avg PnL %", "num"),
            ("AvgR", "num"),
            ("Book AVG_PNL_PCT_WO_MAX", "num"),
            ("Ann ROR %", "num"),
            ("Max DD %", "num"),
            ("Calmar", "num"),
            ("Sharpe", "num"),
            ("Profit factor", "num"),
            ("Expectancy $", "num"),
            ("Avg win %", "num"),
            ("Avg loss %", "num"),
            ("Win/Loss ratio (count)", "num"),
            ("Win/Loss ratio $", "num"),
            ("Avg days held", "num"),
            ("Median days held", "num"),
            ("P90 days held", "num"),
            ("Capital days", "num"),
            ("Profit per capital day", "num"),
            ("Losing streak", "num"),
            ("Pct PnL max symbol", "num"),
            ("Pct PnL max trade", "num"),
            ("Mean FIT Robust", "num"),
            ("Mean Paul Score", "num"),
            ("Mean AVG_PNL_PCT_WO_MAX", "num"),
            ("Mean OUTLIER_PCT_OF_WINS", "num"),
            ("Mean AVG_TRADES_PER_YEAR", "num"),
            ("ΔN", "num"),
            ("ΔWR pp", "num"),
            ("ΔAvgR", "num"),
            ("ΔPnL%", "num"),
            ("ΔAnnROR pp", "num"),
            ("ΔMaxDD pp", "num"),
            ("ΔPF", "num"),
            ("Verdict", "text"),
            ("Why (IS)", "text"),
            ("OOS hold-up", "text"),
            ("Exit mix", "text"),
        ]
    )
    body_is = "\n".join(pack_row(p, "is") for p in packs)
    body_oos = "\n".join(pack_row(p, "oos") for p in packs)
    body_full = "\n".join(pack_row(p, "full") for p in packs)

    recs = [f"{p['arm']}: {p['verdict']} — {p['why']}" for p in packs if p["arm"] != "CONTROL"]
    rec_html = "".join(f"<li>{html_mod.escape(x)}</li>" for x in recs)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html_mod.escape(title)}</title>
<style>
  body {{ margin:0; padding:28px; font-family:"Segoe UI",Georgia,serif; background:#fafaf8; color:#1a1a18; }}
  .wrap {{ max-width:1800px; margin:0 auto; }}
  h1 {{ font-size:1.4rem; }}
  h2 {{ font-size:1.12rem; margin-top:1.8rem; }}
  .muted {{ color:#5c5c56; }}
  .callout {{ background:#eef2ff; border:1px solid #c7d2fe; padding:14px 16px; margin:1rem 0; }}
  .rec {{ background:#fffbeb; border:1px solid #fde68a; padding:14px 16px; margin:1rem 0; }}
  table.sortable {{ border-collapse:collapse; width:100%; font-size:12px; margin-bottom:1.4rem; }}
  table.sortable th, table.sortable td {{ border:1px solid #d8d8d0; padding:5px 7px; vertical-align:top; }}
  table.sortable th {{ background:#f0f0ea; }}
  tr.keep {{ background:#ecfdf5; }}
  tr.dismiss {{ background:#fef2f2; }}
  tr.hold {{ background:#fffbeb; }}
  blockquote {{ margin:0.4rem 0 0.8rem; color:#334155; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<div class="wrap">
  <h1>{html_mod.escape(title)}</h1>
  <p class="muted">Stamp {STAMP} · House pin {HOUSE_STAMP} · Research only · not gold · not DailyRun</p>
  <div class="callout">
    <p><strong>What you asked</strong></p>
    <blockquote>{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
    <p><strong>In plain English</strong></p>
    <p>Volume Zone (VZ) buys the first bounce after price breaks a high-volume shelf.
    Family 1 asks whether a different memory window (3 / 4 / 8 / 12 months of sessions
    instead of about 6) makes cleaner “highest volume day” shelves. Family 2 asks
    whether we should skip crowded stacked shelves and only act when there is empty
    space — measured in Average True Range (ATR) — to the next nearest shelf,
    including extra 12-month shelves drawn only as neighbors. We judge on older
    history (entries before 2024). Newer history and the full book are shown only
    to see if the story holds up. One family, one knob — we do not combine a
    lookback winner with a gap winner from this page.</p>
  </div>
  <div class="rec">
    <p><strong>IS verdicts</strong> (OOS/FULL report-only; OOS softens → HOLD)</p>
    <ul>{rec_html}</ul>
    <p class="muted">{html_mod.escape(extra_note)}</p>
  </div>
  <p class="muted">Click column headers to sort. Total PnL $ / Sheet PnL $ omitted.
  IS/OOS Ann ROR, Max DD, Calmar, Sharpe are Closed-overlay (sheet $45k / $500k).
  FULL lookback arms also carry host Report capital numbers in the note column when present.
  Choosing after this table is in-sample selection (lookbacks were Paul-requested, not a search grid).</p>

  <h2>IS — judge (entry &lt; 2024-01-01)</h2>
  <table class="sortable"><thead><tr>{th}</tr></thead><tbody>{body_is}</tbody></table>

  <h2>OOS — report-only (entry ≥ 2024-01-01)</h2>
  <table class="sortable"><thead><tr>{th}</tr></thead><tbody>{body_oos}</tbody></table>

  <h2>FULL — report-only</h2>
  <table class="sortable"><thead><tr>{th}</tr></thead><tbody>{body_full}</tbody></table>

  <h2>Freeze</h2>
  <p>Universe Paul78.142 (142) · lookback 126 house · rw=63 · HL-only · first_retest ·
  mt≥1 · eps=0.005 · next_open · EXIT_atr4_s025_r15_ts20 · exit_bars=20 · stop_atr=0.25 ·
  target_r=1.5 · min_atr=4 · HVN=false · long · cooldown 10d · aggressive $500k.
  Family shown: {html_mod.escape(family)}.</p>
</div>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    out_path.write_text(html, encoding="utf-8")
    print(f"[html] {out_path}")


def write_index(out_path: Path, lookback_packs: list[dict[str, Any]], gap_packs: list[dict[str, Any]]) -> None:
    def lis(packs: list[dict[str, Any]]) -> str:
        bits = []
        for p in packs:
            bits.append(
                f"<li><strong>{html_mod.escape(p['arm'])}</strong> — {html_mod.escape(p['verdict'])} "
                f"({html_mod.escape(p['why'])})</li>"
            )
        return "".join(bits)

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>VZ lookback + zone-isolation AB 20260907</title>
<style>
body {{ font-family: Segoe UI, Georgia, serif; margin: 28px; background: #fafaf8; color: #1a1a18; }}
.callout {{ background:#eef2ff; border:1px solid #c7d2fe; padding:14px 16px; margin:1rem 0; }}
.muted {{ color:#5c5c56; }}
a {{ color:#1d4ed8; }}
blockquote {{ margin:0.4rem 0 0.8rem; color:#334155; }}
</style></head><body>
<h1>Volume Zone (VZ) lookback + zone-isolation A/B — 20260907</h1>
<p class="muted">House pin {HOUSE_STAMP} unchanged · research only · not gold · not DailyRun</p>
<div class="callout">
  <p><strong>What you asked</strong></p>
  <blockquote>{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
  <p><strong>In plain English</strong></p>
  <p>Two separate tests. First: would a different “highest volume day” memory
  (3 / 4 / 8 / 12 months of sessions vs about 6) make cleaner Volume Zone (VZ)
  shelves? Second: should we skip crowded stacked shelves and only take the
  trade when there is empty space — in Average True Range (ATR) — to the next
  nearest shelf, including extra 12-month shelves drawn only as neighbors?
  We judge on entries before 2024. Newer history is shown only to see if the
  story holds up. We do not combine a lookback pick with a gap pick from this stamp.</p>
</div>
<p><a href="compare_lookback.html">Family 1 — lookback compare</a> ·
<a href="compare_zonegap.html">Family 2 — zone isolation compare</a></p>
<h2>IS verdicts — lookback</h2>
<ul>{lis(lookback_packs)}</ul>
<h2>IS verdicts — zone isolation</h2>
<ul>{lis(gap_packs)}</ul>
<p class="muted">Trade-diff HTML is written only for KEEP / LEAN KEEP arms.</p>
</body></html>
"""
    out_path.write_text(html, encoding="utf-8")


def dump_json(path: Path, obj: Any) -> None:
    def _conv(x: Any) -> Any:
        if isinstance(x, date):
            return x.isoformat()
        if isinstance(x, dict):
            return {str(k): _conv(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [_conv(v) for v in x]
        if isinstance(x, float) and not math.isfinite(x):
            return None
        return x

    path.write_text(json.dumps(_conv(obj), indent=2), encoding="utf-8")


def load_lookback_packs() -> list[dict[str, Any]]:
    house_closed = REPO / "drive" / f"VZ_Closed_{HOUSE_STAMP}.csv"
    house_report = REPO / "drive" / f"VZ_Report_{HOUSE_STAMP}.csv"
    house_sum = REPO / "drive" / f"VZ_Summary_{HOUSE_STAMP}.csv"
    house_eq = REPO / "drive" / f"VZ_EquityCurve_{HOUSE_STAMP}.csv"
    ctrl_trades = load_closed(house_closed)
    packs = []
    for spec in LOOKBACK_ARMS:
        if spec["arm"] == "CONTROL":
            trades = ctrl_trades
            host = read_report_row(house_report)
            summary = load_summary_pack(house_sum)
            equity = house_eq if house_eq.exists() else None
            lookback_ok = 126
            stamp = HOUSE_STAMP
        else:
            d = OUT_DIR / f"lb_{spec['lookback']}"
            closed_p = find_closed_in_dir(d)
            if closed_p is None:
                raise FileNotFoundError(f"missing Closed for {spec['arm']} in {d}")
            trades = load_closed(closed_p)
            host = read_report_row(find_report_in_dir(d))
            summary = load_summary_pack(find_summary_in_dir(d))
            equity = find_equity_in_dir(d)
            lookback_ok = audit_lookback(find_audit_in_dir(d) or find_report_in_dir(d))
            stamp = read_pin(d / "VZ_last_run_ts.txt") if (d / "VZ_last_run_ts.txt").exists() else closed_p.stem
        scores = score_pack(trades, equity=equity, host=host, summary=summary)
        packs.append(
            {
                "arm": spec["arm"],
                "knob": f"lookback_days={spec['lookback']} ({spec['cal']})",
                "lookback": spec["lookback"],
                "trades": trades,
                "stamp": stamp,
                "audit_lookback": lookback_ok,
                **scores,
            }
        )
    ctrl = next(p for p in packs if p["arm"] == "CONTROL")
    for p in packs:
        v, why = verdict_is(p["arm"], p["is"], ctrl["is"])
        note = "report-only"
        if p["arm"] != "CONTROL" and oos_softens(p["oos"], ctrl["oos"]):
            if v in ("KEEP", "LEAN KEEP"):
                why = why + "; OOS softens → HOLD (do not retune)"
                v = "HOLD"
            note = "OOS softens vs control (report-only; HOLD if IS was KEEP)"
        elif p["arm"] != "CONTROL":
            note = "OOS does not clearly soften vs control (still report-only)"
        p["verdict"] = v
        p["why"] = why
        p["oos_note"] = note
    return packs


def load_gap_packs(house_trades: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    notes = attach_gaps(house_trades)
    house_eq = REPO / "drive" / f"VZ_EquityCurve_{HOUSE_STAMP}.csv"
    house_eq_p = house_eq if house_eq.exists() else None
    packs = []
    for spec in GAP_ARMS:
        kept = filter_gap(house_trades, source=spec["source"], thr=spec["thr"])
        # Control can use the host daily curve; filtered arms must use Closed overlay Sharpe.
        scores = score_pack(kept, equity=house_eq_p if spec["source"] == "none" else None)
        packs.append(
            {
                "arm": spec["arm"],
                "knob": spec["label"],
                "source": spec["source"],
                "thr": spec["thr"],
                "trades": kept,
                **scores,
            }
        )
    ctrl = next(p for p in packs if p["arm"] == "CONTROL")
    for p in packs:
        v, why = verdict_is(p["arm"], p["is"], ctrl["is"])
        note = "report-only"
        if p["arm"] != "CONTROL" and oos_softens(p["oos"], ctrl["oos"]):
            if v in ("KEEP", "LEAN KEEP"):
                why = why + "; OOS softens → HOLD (do not retune)"
                v = "HOLD"
            note = "OOS softens vs control (report-only; HOLD if IS was KEEP)"
        elif p["arm"] != "CONTROL":
            note = "OOS does not clearly soften vs control (still report-only)"
        p["verdict"] = v
        p["why"] = why
        p["oos_note"] = note
    return packs, notes


def write_gap_attach_csv(path: Path, trades: list[dict[str, Any]]) -> None:
    cols = [
        "SYMBOL",
        "DATE_OPENED",
        "SIGNAL_DATE",
        "ZONE_ID",
        "PNL_PCT",
        "gap126",
        "gap_union",
        "n_nb126",
        "n_nb_union",
        "nearest126",
        "nearest_union",
        "gap_note",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for t in trades:
            w.writerow(
                {
                    "SYMBOL": t["sym"],
                    "DATE_OPENED": t["opened"].isoformat(),
                    "SIGNAL_DATE": t["signal"].isoformat() if t.get("signal") else "",
                    "ZONE_ID": t.get("zone_id", ""),
                    "PNL_PCT": f"{t['pnl']:.4f}",
                    "gap126": t.get("gap126", ""),
                    "gap_union": t.get("gap_union", ""),
                    "n_nb126": t.get("n_nb126", ""),
                    "n_nb_union": t.get("n_nb_union", ""),
                    "nearest126": t.get("nearest126", ""),
                    "nearest_union": t.get("nearest_union", ""),
                    "gap_note": t.get("gap_note", ""),
                }
            )


def slim(p: dict[str, Any]) -> dict[str, Any]:
    keys = ("arm", "knob", "verdict", "why", "oos_note", "lookback", "audit_lookback", "stamp", "thr", "source")
    out = {k: p.get(k) for k in keys if k in p}
    for sl in ("is", "oos", "full"):
        m = p[sl]
        out[sl] = {
            "n": m["n"],
            "wr": m["wr"],
            "avg_pnl": m["avg_pnl"],
            "avg_r": m["avg_r"],
            "pf": m["pf"],
            "ann_ror": m["ann_ror"],
            "max_dd": m["max_dd"],
            "calmar": m["calmar"],
            "sharpe": m["sharpe"],
            "mean_fit_r": m["fit"]["mean_fit_r"],
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookbacks", action="store_true", help="Run isolated lookback live A/Bs")
    ap.add_argument("--overlay", action="store_true", help="Attach gaps + score Family 2")
    ap.add_argument("--report", action="store_true", help="Write HTML from existing artifacts")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--skip-existing", action="store_true", default=True)
    args = ap.parse_args()
    do_all = not (args.lookbacks or args.overlay or args.report)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    pin = read_pin(HOUSE_PIN_PATH)
    if pin != HOUSE_STAMP:
        print(
            f"[pin] DailyRun/other pin is {pin}; control book stays {HOUSE_STAMP}. "
            "This job will not write drive/VZ_house_last_run_ts.txt.",
            flush=True,
        )

    if args.lookbacks or do_all:
        for spec in LOOKBACK_ARMS:
            if not spec["live"]:
                continue
            run_isolated_lookback(int(spec["lookback"]), OUT_DIR / f"lb_{spec['lookback']}", args.workers)
        pin2 = read_pin(HOUSE_PIN_PATH)
        if pin2 != pin:
            raise RuntimeError(f"House pin mutated {pin} -> {pin2}")

    house_trades = load_closed(REPO / "drive" / f"VZ_Closed_{HOUSE_STAMP}.csv")
    gap_notes: dict[str, Any] = {}
    gap_packs: list[dict[str, Any]] = []
    if args.overlay or do_all or args.report:
        gap_packs, gap_notes = load_gap_packs(house_trades)
        write_gap_attach_csv(OUT_DIR / "house_trade_gaps.csv", house_trades)
        dump_json(OUT_DIR / "gap_attach_notes.json", gap_notes)

    lookback_packs: list[dict[str, Any]] = []
    if args.report or do_all:
        lookback_packs = load_lookback_packs()
        write_family_html(
            OUT_DIR / "compare_lookback.html",
            title="Volume Zone (VZ) lookback window A/B — 20260907",
            family="lookback (ENTRY; live isolated)",
            packs=lookback_packs,
            extra_note=(
                "Paul-requested 3/4/8/12m windows vs house 126. "
                "Choosing after this table is in-sample selection."
            ),
        )
        write_family_html(
            OUT_DIR / "compare_zonegap.html",
            title="Volume Zone (VZ) zone-isolation / multi-TF gap A/B — 20260907",
            family="zone isolation (ENTRY filter; overlay)",
            packs=gap_packs,
            extra_note=(
                f"Overlay on house Closed {HOUSE_STAMP}. Gap attach: {gap_notes}. "
                "Isolation, not confluence. Not HVN."
            ),
        )
        write_index(OUT_DIR / "index.html", lookback_packs, gap_packs)
        dump_json(OUT_DIR / "lookback_scores.json", [slim(p) for p in lookback_packs])
        dump_json(OUT_DIR / "gap_scores.json", [slim(p) for p in gap_packs])

        ctrl_lb = next(p for p in lookback_packs if p["arm"] == "CONTROL")
        for p in lookback_packs:
            if p["verdict"] in ("KEEP", "LEAN KEEP"):
                write_trade_diff(
                    OUT_DIR / f"trade_diff_{p['arm']}.html",
                    title=f"VZ trade diff — house vs {p['arm']}",
                    ctrl_trades=ctrl_lb["trades"],
                    cand_trades=p["trades"],
                    arm=p["arm"],
                )
        ctrl_gap = next(p for p in gap_packs if p["arm"] == "CONTROL")
        for p in gap_packs:
            if p["verdict"] in ("KEEP", "LEAN KEEP"):
                write_trade_diff(
                    OUT_DIR / f"trade_diff_{p['arm']}.html",
                    title=f"VZ trade diff — house vs {p['arm']}",
                    ctrl_trades=ctrl_gap["trades"],
                    cand_trades=p["trades"],
                    arm=p["arm"],
                )
        pin_final = read_pin(HOUSE_PIN_PATH)
        print(
            f"[pin] start={pin} end={pin_final}; control Closed={HOUSE_STAMP} (this job never writes the pin)",
            flush=True,
        )

    print("[done] lookback+zonegap stamp ready", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
