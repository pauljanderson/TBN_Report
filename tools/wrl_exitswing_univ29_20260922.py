#!/usr/bin/env python3
"""WRL EXIT_swing on Paul's 29-name first universe — 2026-09-22.

Weekly Range / Swing (WRL). Research only. Not gold. Not DailyRun.

Adopted parent: ``drive/paul_experiments/wrl_exitswing_is_universe_20260922/``
(freeze: ``wrl_target_mode=swing``, min-zone OFF, scale 50/50 leftover unused,
stop at swing low, cooldown off).

Universe = the 29 names Paul listed after seeing the full-universe IS table.
That pick is in-sample selection. Re-score IS/OOS under the freeze. Do not
retune on OOS. Do not add/drop symbols.
"""
from __future__ import annotations

import argparse
import csv
import html
import math
import os
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "stock_analysis"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

from compare_format import (  # noqa: E402
    canonical_book_order_html,
    filter_html_compare_metric_rows,
    format_money,
    format_money_delta,
    overlay_ann_ror_max_dd,
    parse_number,
)
from rocket_wrl import (  # noqa: E402
    WRL_CLOSED_HEADER,
    WrlConfig,
    _run_wrl_symbol_tasks,
    _wrl_cfg_dict,
    brt_config_from_wrl,
    write_wrl_outputs,
)
from tbn_host_sizing import HostSizingConfig, apply_host_dollar_scale  # noqa: E402

try:
    from _gen_too_high_diff import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th
except ImportError:  # pragma: no cover
    from report_page_extras import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS  # type: ignore

    def sortable_th(label: str, sort_type: str) -> str:  # type: ignore
        return (
            f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
            f'role="columnheader" aria-sort="none">{html.escape(label)}'
            f'<span class="sort-ind"></span></th>'
        )

STAMP_DIR = REPO / "drive" / "paul_experiments" / "wrl_exitswing_univ29_20260922"
PARENT_STAMP = REPO / "drive" / "paul_experiments" / "wrl_exitswing_is_universe_20260922"
DATA_DIR = REPO / "data" / "newdata" / "data"
IS_CUT = date(2024, 1, 1)
SHEET_CASH = 47_500.0
INIT = 500_000.0

# Exact list, Paul's order, uppercase. Do not add/drop.
UNIVERSE_29: tuple[str, ...] = (
    "GEHC",
    "FTRE",
    "UBER",
    "NE",
    "FANG",
    "CARR",
    "IBP",
    "TDG",
    "DELL",
    "HWM",
    "PANW",
    "STZ",
    "LNC",
    "HCA",
    "GDDY",
    "EXLS",
    "CWK",
    "CRM",
    "PVH",
    "SHC",
    "SPG",
    "DRI",
    "FNF",
    "FN",
    "ADBE",
    "CCL",
    "UNH",
    "HGV",
    "MAR",
)
assert len(UNIVERSE_29) == 29
assert len(set(UNIVERSE_29)) == 29
assert all(t == t.upper() and t.isalpha() for t in UNIVERSE_29)

ORIGINAL_REQUEST = (
    "thanks. let's run this universe as our first universe\n"
    "GEHC, FTRE, UBER, NE, FANG, CARR, IBP, TDG, DELL, HWM, PANW, STZ, LNC, "
    "HCA, GDDY, EXLS, CWK, CRM, PVH, SHC, SPG, DRI, FNF, FN, ADBE, CCL, UNH, "
    "HGV, MAR"
)

CONTROL = "00_control"
SWING = "EXIT_swing"
ARMS: list[tuple[str, dict[str, Any], str, str]] = [
    (
        CONTROL,
        {"wrl_target_mode": "scale"},
        "Old control exit: scale 50/50 (half at range high, rest at swing high). Same 29 names.",
        "CONTROL",
    ),
    (
        SWING,
        {"wrl_target_mode": "swing"},
        "Adopted freeze: full size out at swing high. Same 29 names.",
        "EXIT",
    ),
]

PARENT_IS_HEADLINE = "Adopted EXIT_swing IS: N=89,874 · WR=34.3% · Avg PnL%=+0.70 · PF=1.29"
PARENT_OOS_HEADLINE = "Adopted EXIT_swing OOS (report only): N=20,572 · WR=34.7% · Avg PnL%=+0.85 · PF=1.32"


def _host_cfg() -> HostSizingConfig:
    return HostSizingConfig(
        brt_cash=SHEET_CASH,
        initial_capital=INIT,
        aggressive_max_multiple=2.0,
        margin_utilization=0.6,
        max_positions=0,
        aggressive=True,
        aggressive_margin_interest=0.10,
        aggressive_avg_positions=0.0,
        aggressive_sizing_equity_cap=10.0,
        aggressive_sell="false",
        equity_fast_aggressive=True,
    )


def _parse_ymd(val: Any) -> Optional[date]:
    s = str(val or "").strip().replace("-", "")
    if len(s) < 8 or not s[:8].isdigit():
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def _f(x: Any, default: float = 0.0) -> float:
    n = parse_number(x)
    return default if n is None else float(n)


def _load_symbol(sym: str) -> Optional[pd.DataFrame]:
    path = DATA_DIR / f"{sym}.csv"
    if not path.is_file():
        return None
    df = pd.read_csv(path)
    if "Date" not in df.columns:
        return None
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").set_index("Date")
    for c in ("Open", "High", "Low", "Close"):
        if c not in df.columns:
            return None
        df[c] = pd.to_numeric(df[c], errors="coerce")
    if "Volume" in df.columns:
        df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce")
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    return df if len(df) >= 40 else None


def _latest(arm_dir: Path, pattern: str) -> Optional[Path]:
    files = sorted(arm_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _run_arm(
    arm: str,
    overrides: dict[str, Any],
    symbols: list[str],
    frames: dict[str, pd.DataFrame],
    workers: int,
) -> Path:
    arm_dir = STAMP_DIR / arm
    arm_dir.mkdir(parents=True, exist_ok=True)
    cfg = WrlConfig()
    for k, v in overrides.items():
        setattr(cfg, k, v)
    if arm == SWING:
        assert str(cfg.wrl_target_mode).strip().lower() == "swing"
    else:
        assert str(cfg.wrl_target_mode).strip().lower() == "scale"
    assert float(cfg.wrl_min_zone_pct or 0.0) == 0.0
    assert int(cfg.symbol_reentry_cooldown_days or 0) == 0
    assert float(cfg.wrl_scale_frac) == 0.50
    assert float(cfg.stop_pct) == 1.0
    tasks = [(sym, frames[sym], _wrl_cfg_dict(cfg)) for sym in symbols if sym in frames]
    t0 = time.time()
    results = _run_wrl_symbol_tasks(tasks, workers)
    closed, opens, watch, scanner = [], [], [], []
    skipped: list[str] = []
    for res in results:
        if getattr(res, "skip_reason", None):
            skipped.append(res.symbol)
            continue
        closed.extend(res.closed)
        opens.extend(res.open_rows)
        watch.extend(res.watch)
        scanner.extend(res.scanner)
    closed.sort(key=lambda r: (r.date_opened, r.symbol))
    hcfg = _host_cfg()
    host_meta: dict[str, Any] = {}
    if closed:
        adj, scale, max_pos = apply_host_dollar_scale(closed, opens, hcfg)
        cfg.brt_cash = adj
        host_meta = {
            "host_max_positions": max_pos,
            "host_brt_cash": adj,
            "host_pnl_scale": scale,
        }
        print(
            f"[WRL-U29] {arm} host scale ×{scale:.6g}; brt_cash -> {adj:,.0f} (max_pos={max_pos})",
            flush=True,
        )
    ts = time.strftime("%y%m%d%H%M%S")
    write_wrl_outputs(
        arm_dir,
        ts,
        closed,
        opens,
        watch,
        scanner,
        cfg,
        host_meta=host_meta,
        tickers=frames,
        host_cfg=hcfg,
        tbn_cfg=brt_config_from_wrl(cfg, None),
        no_yfinance=True,
    )
    (arm_dir / "STAMP.txt").write_text(
        f"stamp={ts}\narm={arm}\noverrides={overrides}\n"
        f"wrl_min_zone_pct=0\nsymbol_reentry_cooldown_days=0\n"
        f"symbols={','.join(symbols)}\nn_closed={len(closed)}\n"
        f"skipped={','.join(skipped)}\nelapsed_s={time.time() - t0:.1f}\n",
        encoding="utf-8",
    )
    print(
        f"[WRL-U29] {arm}: {len(closed)} closed / {len(opens)} open  "
        f"({time.time() - t0:.1f}s) skipped={skipped} -> {arm_dir}",
        flush=True,
    )
    return arm_dir


def _closed_rows(arm_dir: Path) -> list[dict[str, Any]]:
    p = _latest(arm_dir, "WRL_Closed_*.csv")
    if not p:
        return []
    out: list[dict[str, Any]] = []
    with p.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        for row in csv.DictReader(f):
            opened = _parse_ymd(row.get("DATE_OPENED"))
            closed = _parse_ymd(row.get("DATE_CLOSED"))
            entry = _f(row.get("ENTRY_PRICE"))
            stop = _f(row.get("STOP_PRICE"))
            pnl = _f(row.get("PNL_PCT"))
            risk_pct = ((entry - stop) / entry * 100.0) if entry > 0 and stop < entry else None
            r_mult = (pnl / risk_pct) if risk_pct and risk_pct > 1e-9 else None
            out.append(
                {
                    "symbol": str(row.get("SYMBOL") or "").upper(),
                    "opened": opened,
                    "closed": closed,
                    "pnl": pnl,
                    "pnl_d": _f(row.get("PNL_DOLLARS")),
                    "days": _f(row.get("DAYS_HELD")),
                    "exit": str(row.get("EXIT_TYPE") or "").strip().upper(),
                    "entry": entry,
                    "stop": stop,
                    "r_mult": r_mult,
                    "win": pnl > 0,
                    "raw": row,
                }
            )
    return out


def _slice_rows(rows: list[dict[str, Any]], which: str) -> list[dict[str, Any]]:
    if which == "IS":
        return [r for r in rows if r.get("opened") and r["opened"] < IS_CUT]
    if which == "OOS":
        return [r for r in rows if r.get("opened") and r["opened"] >= IS_CUT]
    return list(rows)


def _pctile(xs: list[float], q: float) -> Optional[float]:
    if not xs:
        return None
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    idx = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[idx]


def _wo_max_mean(pcts: list[float]) -> Optional[float]:
    if not pcts:
        return None
    if len(pcts) == 1:
        return pcts[0]
    drop = max(pcts)
    rest = [x for x in pcts if x != drop]
    if len(rest) < len(pcts):
        return sum(rest) / len(rest)
    return sum(pcts[:-1]) / (len(pcts) - 1)


def _losing_streak(rows: list[dict[str, Any]]) -> int:
    best = 0
    cur = 0
    ordered = sorted(
        rows,
        key=lambda r: (r.get("closed") or date.min, r.get("opened") or date.min, r.get("symbol") or ""),
    )
    for r in ordered:
        if float(r.get("pnl") or 0.0) < 0:
            cur += 1
            if cur > best:
                best = cur
        else:
            cur = 0
    return best


def _book_from_rows(
    rows: list[dict[str, Any]],
    *,
    cash: float,
    n_univ: int,
    equity_curve: Optional[Path] = None,
    start_date: Optional[date] = None,
    end_date_exclusive: Optional[date] = None,
) -> dict[str, Any]:
    n = len(rows)
    pnls = [float(r["pnl"]) for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    wr = (100.0 * len(wins) / n) if n else 0.0
    avg = (sum(pnls) / n) if n else 0.0
    avg_win = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(losses) / len(losses)) if losses else 0.0
    wl_count = (len(wins) / len(losses)) if losses else (float(len(wins)) if wins else 0.0)
    sum_w = sum(float(r["pnl_d"]) for r in rows if r["pnl_d"] > 0)
    sum_l = abs(sum(float(r["pnl_d"]) for r in rows if r["pnl_d"] < 0))
    pf = (sum_w / sum_l) if sum_l > 0 else (sum_w if sum_w > 0 else 0.0)
    days = [float(r["days"]) for r in rows if r.get("days") is not None]
    avg_days = (sum(days) / len(days)) if days else 0.0
    med_days = statistics.median(days) if days else 0.0
    p90_days = _pctile(days, 0.90) or 0.0
    rs = [float(r["r_mult"]) for r in rows if r.get("r_mult") is not None]
    ov = overlay_ann_ror_max_dd(
        rows,
        cash=cash,
        initial_account=INIT,
        equity_curve_path=equity_curve,
        start_date=start_date,
        end_date_exclusive=end_date_exclusive,
        pnl_d_key="pnl_d",
        days_key="days",
        closed_key="closed",
        opened_key="opened",
        pnl_pct_key="pnl",
    )
    exits = Counter(str(r.get("exit") or "UNKNOWN") for r in rows)
    n_ex = sum(exits.values()) or 1
    wo = _wo_max_mean(pnls)
    profit_day = None
    if ov["capital_days"] and ov["capital_days"] > 0:
        profit_day = ov["pnl_d"] / ov["capital_days"]
    return {
        "n_univ": n_univ,
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "wr": wr,
        "avg_pnl_pct": avg,
        "wo_max": wo,
        "exp_pct": avg,
        "exp_d": (sum(float(r["pnl_d"]) for r in rows) / n) if n else 0.0,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "wl_count": wl_count,
        "wl_d": (sum_w / sum_l) if sum_l > 0 else 0.0,
        "pf": pf,
        "avg_r": (sum(rs) / len(rs)) if rs else None,
        "ann_ror": ov["ann_ror"],
        "max_dd": ov["max_dd"],
        "calmar": ov["calmar"],
        "sharpe": ov["sharpe"],
        "sharpe_src": ov["sharpe_source"],
        "profit_day": profit_day,
        "capital_days": ov["capital_days"],
        "avg_days": avg_days,
        "med_days": med_days,
        "p90_days": p90_days,
        "exits": exits,
        "exit_n": n_ex,
        "pnl_d": ov["pnl_d"],
        "losing_streak": _losing_streak(rows),
        "worst": min(pnls) if pnls else None,
        "note": ov.get("note") or "",
    }


def _summary_aggs(arm_dir: Path) -> dict[str, Any]:
    p = _latest(arm_dir, "WRL_Summary_*.csv")
    empty = {
        "mean_paul": None,
        "sum_paul": None,
        "mean_fit": None,
        "sum_fit": None,
        "mean_robust": None,
        "sum_robust": None,
        "mean_wo": None,
        "mean_outlier": None,
        "mean_tpy": None,
        "mean_maxwin": None,
        "mean_pf": None,
        "n_sym": 0,
    }
    if not p:
        return empty
    pauls, fits, robs, wos, outs, tpys, maxw, pfs = [], [], [], [], [], [], [], []
    with p.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        for row in csv.DictReader(f):
            pauls.append(_f(row.get("PAUL_SCORE")))
            fits.append(_f(row.get("FIT_SCORE")))
            robs.append(_f(row.get("FIT_SCORE_ROBUST")))
            wos.append(_f(row.get("AVG_PNL_PCT_WO_MAX")))
            outs.append(_f(row.get("OUTLIER_PCT_OF_WINS")))
            tpys.append(_f(row.get("AVG_TRADES_PER_YEAR")))
            maxw.append(_f(row.get("MAX_WIN_PCT")))
            pfs.append(_f(row.get("PROFIT_FACTOR")))
    if not pauls:
        return empty

    def _mean(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    return {
        "mean_paul": _mean(pauls),
        "sum_paul": sum(pauls),
        "mean_fit": _mean(fits),
        "sum_fit": sum(fits),
        "mean_robust": _mean(robs),
        "sum_robust": sum(robs),
        "mean_wo": _mean(wos),
        "mean_outlier": _mean(outs),
        "mean_tpy": _mean(tpys),
        "mean_maxwin": _mean(maxw),
        "mean_pf": _mean(pfs),
        "n_sym": len(pauls),
    }


def _audit_row(arm_dir: Path) -> dict[str, Any]:
    p = _latest(arm_dir, "WRL_Audit_Report_*.csv") or _latest(arm_dir, "WRL_Report_*.csv")
    if not p:
        return {}
    with p.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        return next(csv.DictReader(f), {}) or {}


def _fmt(v: Any, kind: str = "num") -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "—"
    if kind == "money":
        return format_money(v)
    if kind == "money_d":
        return format_money_delta(v)
    if kind == "pct":
        return f"{float(v):.2f}%"
    if kind in ("calmar", "sharpe"):
        return f"{float(v):.2f}"
    if kind == "int":
        return f"{int(round(float(v))):,}"
    return f"{float(v):.2f}"


def _delta(a: Any, b: Any) -> Optional[float]:
    if a is None or b is None:
        return None
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return None
    if math.isnan(fa) or math.isnan(fb):
        return None
    return fa - fb


def _quality_verdict(
    ctrl: dict[str, Any],
    cand: dict[str, Any],
    *,
    oos_ctrl: dict[str, Any],
    oos_cand: dict[str, Any],
) -> tuple[str, str]:
    """Judge on IS quality. OOS report-only; softening → HOLD."""
    n_ok = cand["n"] >= max(8, int(0.60 * ctrl["n"])) if ctrl["n"] else cand["n"] >= 8
    avg_up = cand["avg_pnl_pct"] > ctrl["avg_pnl_pct"] + 0.05
    pf_up = cand["pf"] > ctrl["pf"] + 0.02
    wr_up = cand["wr"] > ctrl["wr"] + 0.5
    avg_dn = cand["avg_pnl_pct"] < ctrl["avg_pnl_pct"] - 0.05
    pf_dn = cand["pf"] < ctrl["pf"] - 0.02
    dd_worse = False
    if (
        isinstance(cand.get("max_dd"), float)
        and isinstance(ctrl.get("max_dd"), float)
        and math.isfinite(cand["max_dd"])
        and math.isfinite(ctrl["max_dd"])
    ):
        dd_worse = cand["max_dd"] > ctrl["max_dd"] + 5.0

    oos_soft = False
    if oos_ctrl["n"] >= 8 and oos_cand["n"] >= 8:
        if oos_cand["avg_pnl_pct"] + 0.05 < oos_ctrl["avg_pnl_pct"] and oos_cand["pf"] + 0.02 < oos_ctrl["pf"]:
            oos_soft = True
        if avg_up and oos_cand["avg_pnl_pct"] + 0.15 < cand["avg_pnl_pct"]:
            oos_soft = True

    if avg_dn and pf_dn:
        return "DISMISS", "IS Avg PnL% and profit factor both worse than control on this 29-name sleeve."
    if avg_up and (pf_up or wr_up) and n_ok and not dd_worse:
        if oos_soft:
            return (
                "HOLD",
                "IS quality improved vs control-on-same-29, but OOS softened — report-only; do not adopt or retune on OOS.",
            )
        return (
            "LEAN KEEP",
            "IS quality improved (Avg PnL% plus WR or PF) vs control-on-same-29 without collapsing N or blowing up Max DD. Research sleeve only — not gold / not DailyRun.",
        )
    if dd_worse and (avg_up or pf_up):
        return "HOLD", "Some IS quality lift vs control-on-same-29 but Max DD is worse by >5pp."
    if not n_ok and (avg_up or pf_up):
        return "HOLD", "Quality numbers moved, but trade count collapsed (>40% drop)."
    return "HOLD", "IS quality is mixed or flat vs the old control exit on the same 29 names."


def _metric_rows(
    books: dict[str, dict[str, Any]],
    sums: dict[str, dict[str, Any]],
    audits: dict[str, dict[str, Any]],
) -> list[tuple[str, str, dict[str, Any]]]:
    def g(arm: str, key: str, src: str = "book") -> Any:
        if src == "sum":
            return sums.get(arm, {}).get(key)
        if src == "audit":
            return parse_number(audits.get(arm, {}).get(key))
        return books.get(arm, {}).get(key)

    rows: list[tuple[str, str, dict[str, Any]]] = [
        ("Universe size", "int", {a: g(a, "n_univ") for a in books}),
        ("Total trades", "int", {a: g(a, "n") for a in books}),
        ("Wins", "int", {a: g(a, "wins") for a in books}),
        ("Losses", "int", {a: g(a, "losses") for a in books}),
        ("Win %", "pct", {a: g(a, "wr") for a in books}),
        ("Avg PnL %", "num", {a: g(a, "avg_pnl_pct") for a in books}),
        ("Book AVG_PNL_PCT_WO_MAX", "num", {a: g(a, "wo_max") for a in books}),
        ("Expectancy $", "money", {a: g(a, "exp_d") for a in books}),
        ("Expectancy %", "num", {a: g(a, "exp_pct") for a in books}),
        ("Avg win %", "num", {a: g(a, "avg_win") for a in books}),
        ("Avg loss %", "num", {a: g(a, "avg_loss") for a in books}),
        ("Win/Loss ratio (count)", "num", {a: g(a, "wl_count") for a in books}),
        ("Win/Loss ratio $", "num", {a: g(a, "wl_d") for a in books}),
        ("Profit factor", "num", {a: g(a, "pf") for a in books}),
        ("Ann ROR %", "num", {a: g(a, "ann_ror") for a in books}),
        ("Max DD %", "num", {a: g(a, "max_dd") for a in books}),
        ("Calmar", "calmar", {a: g(a, "calmar") for a in books}),
        ("Sharpe", "sharpe", {a: g(a, "sharpe") for a in books}),
        ("Profit per capital day", "money", {a: g(a, "profit_day") for a in books}),
        ("Capital days", "int", {a: g(a, "capital_days") for a in books}),
        ("Avg days held", "num", {a: g(a, "avg_days") for a in books}),
        ("Median days held", "num", {a: g(a, "med_days") for a in books}),
        ("P90 days held", "num", {a: g(a, "p90_days") for a in books}),
        ("Losing streak", "int", {a: g(a, "losing_streak") for a in books}),
        ("Avg positions", "num", {a: parse_number(audits.get(a, {}).get("Avg_Positions")) for a in books}),
        ("Max positions", "int", {a: parse_number(audits.get(a, {}).get("Max_Positions")) for a in books}),
        ("Aggressive Max DD %", "num", {a: parse_number(audits.get(a, {}).get("Aggressive_Max_DD")) for a in books}),
        ("Mean Paul Score", "num", {a: g(a, "mean_paul", "sum") for a in books}),
        ("Σ Paul Score", "num", {a: g(a, "sum_paul", "sum") for a in books}),
        ("Mean FIT Score", "num", {a: g(a, "mean_fit", "sum") for a in books}),
        ("Σ FIT Score", "num", {a: g(a, "sum_fit", "sum") for a in books}),
        ("Mean FIT Score Robust", "num", {a: g(a, "mean_robust", "sum") for a in books}),
        ("Σ FIT Score Robust", "num", {a: g(a, "sum_robust", "sum") for a in books}),
        ("Mean AVG_PNL_PCT_WO_MAX", "num", {a: g(a, "mean_wo", "sum") for a in books}),
        ("Mean OUTLIER_PCT_OF_WINS", "num", {a: g(a, "mean_outlier", "sum") for a in books}),
        ("Mean AVG_TRADES_PER_YEAR", "num", {a: g(a, "mean_tpy", "sum") for a in books}),
        ("Mean MAX_WIN_PCT", "num", {a: g(a, "mean_maxwin", "sum") for a in books}),
        ("Mean PROFIT_FACTOR (symbol)", "num", {a: g(a, "mean_pf", "sum") for a in books}),
    ]
    wanted = set(canonical_book_order_html())
    rows = [r for r in rows if r[0] in wanted or r[0] not in ("Total PnL $", "Sheet PnL $")]
    return filter_html_compare_metric_rows(rows, label_index=0)


def _table_compare(
    title: str,
    books: dict[str, dict[str, Any]],
    sums: dict[str, dict[str, Any]],
    audits: dict[str, dict[str, Any]],
    notes: dict[str, str],
) -> str:
    arms = [a for a, *_ in ARMS if a in books]
    metric_rows = _metric_rows(books, sums, audits)
    ths = [sortable_th("Metric", "text")]
    for a in arms:
        ths.append(sortable_th(a, "num"))
        if a != CONTROL:
            ths.append(sortable_th(f"Δ {a}", "num"))
    body = []
    for label, kind, vals in metric_rows:
        tds = [f"<td>{html.escape(label)}</td>"]
        cv = vals.get(CONTROL)
        for a in arms:
            v = vals.get(a)
            tds.append(f"<td class='num'>{_fmt(v, kind)}</td>")
            if a != CONTROL:
                d = _delta(v, cv)
                dkind = "money_d" if kind == "money" else ("pct" if kind == "pct" else kind)
                if kind == "pct" and d is not None:
                    tds.append(f"<td class='num'>{d:+.2f}pp</td>")
                else:
                    tds.append(f"<td class='num'>{_fmt(d, dkind)}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    note_bits = [f"{html.escape(a)}: {html.escape(n)}" for a, n in notes.items() if n]
    note_html = f"<p class='muted'>{' · '.join(note_bits)}</p>" if note_bits else ""
    return f"""
<h3>{html.escape(title)}</h3>
<p class="muted">Click column headers to sort. Total PnL $ / Sheet PnL $ omitted from HTML (canonical rule).</p>
<div class="table-wrap"><table class="sortable">
<caption>{html.escape(title)} — absolute values and deltas vs {CONTROL} on the same 29 names</caption>
<thead><tr>{''.join(ths)}</tr></thead>
<tbody>
{''.join(body)}
</tbody></table></div>
{note_html}
"""


def _exit_table(books: dict[str, dict[str, Any]], title: str) -> str:
    kinds = sorted({k for b in books.values() for k in b["exits"]})
    arms = [a for a, *_ in ARMS if a in books]
    ths = [sortable_th("Exit", "text")] + [sortable_th(f"{a} N", "num") for a in arms]
    ths += [sortable_th(f"{a} %", "num") for a in arms]
    body = []
    for k in kinds:
        tds = [f"<td>{html.escape(k)}</td>"]
        for a in arms:
            n = books[a]["exits"].get(k, 0)
            tds.append(f"<td class='num'>{n}</td>")
        for a in arms:
            n = books[a]["exits"].get(k, 0)
            pct = 100.0 * n / books[a]["exit_n"] if books[a]["exit_n"] else 0.0
            tds.append(f"<td class='num'>{pct:.1f}%</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    return f"""
<h3>{html.escape(title)}</h3>
<p class="muted">Click column headers to sort. Counts and % of Closed EXIT_TYPE.</p>
<div class="table-wrap"><table class="sortable">
<thead><tr>{''.join(ths)}</tr></thead>
<tbody>{''.join(body)}</tbody>
</table></div>
"""


def _symbol_books(
    rows: list[dict[str, Any]],
) -> dict[str, dict[str, dict[str, Any]]]:
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r.get("symbol"):
            by[r["symbol"]].append(r)
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for sym in UNIVERSE_29:
        recs = by.get(sym, [])
        out[sym] = {
            "IS": _book_from_rows(_slice_rows(recs, "IS"), cash=SHEET_CASH, n_univ=1),
            "OOS": _book_from_rows(_slice_rows(recs, "OOS"), cash=SHEET_CASH, n_univ=1),
            "FULL": _book_from_rows(recs, cash=SHEET_CASH, n_univ=1),
        }
    return out


def _write_universe_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(UNIVERSE_29) + "\n", encoding="utf-8")


def _write_symbol_csv(path: Path, by_arm: dict[str, dict[str, dict[str, dict[str, Any]]]]) -> None:
    fields = [
        "SYMBOL",
        "ARM",
        "N_IS",
        "WR_IS",
        "AVG_PNL_PCT_IS",
        "PF_IS",
        "EXP_PCT_IS",
        "MAX_DD_IS",
        "N_OOS",
        "WR_OOS",
        "AVG_PNL_PCT_OOS",
        "PF_OOS",
        "EXP_PCT_OOS",
        "MAX_DD_OOS",
        "N_FULL",
        "WR_FULL",
        "AVG_PNL_PCT_FULL",
        "PF_FULL",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for arm in (SWING, CONTROL):
            books = by_arm[arm]
            for sym in UNIVERSE_29:
                b = books[sym]
                w.writerow(
                    {
                        "SYMBOL": sym,
                        "ARM": arm,
                        "N_IS": b["IS"]["n"],
                        "WR_IS": f"{b['IS']['wr']:.4f}",
                        "AVG_PNL_PCT_IS": f"{b['IS']['avg_pnl_pct']:.4f}",
                        "PF_IS": f"{b['IS']['pf']:.4f}",
                        "EXP_PCT_IS": f"{b['IS']['exp_pct']:.4f}",
                        "MAX_DD_IS": "" if b["IS"]["max_dd"] is None or (
                            isinstance(b["IS"]["max_dd"], float) and not math.isfinite(b["IS"]["max_dd"])
                        ) else f"{b['IS']['max_dd']:.4f}",
                        "N_OOS": b["OOS"]["n"],
                        "WR_OOS": f"{b['OOS']['wr']:.4f}",
                        "AVG_PNL_PCT_OOS": f"{b['OOS']['avg_pnl_pct']:.4f}",
                        "PF_OOS": f"{b['OOS']['pf']:.4f}",
                        "EXP_PCT_OOS": f"{b['OOS']['exp_pct']:.4f}",
                        "MAX_DD_OOS": "" if b["OOS"]["max_dd"] is None or (
                            isinstance(b["OOS"]["max_dd"], float) and not math.isfinite(b["OOS"]["max_dd"])
                        ) else f"{b['OOS']['max_dd']:.4f}",
                        "N_FULL": b["FULL"]["n"],
                        "WR_FULL": f"{b['FULL']['wr']:.4f}",
                        "AVG_PNL_PCT_FULL": f"{b['FULL']['avg_pnl_pct']:.4f}",
                        "PF_FULL": f"{b['FULL']['pf']:.4f}",
                    }
                )


def _write_overlay_csv(path: Path, by_arm_rows: dict[str, list[dict[str, Any]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["ARM"] + list(WRL_CLOSED_HEADER)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for arm in (SWING, CONTROL):
            for r in by_arm_rows[arm]:
                raw = dict(r.get("raw") or {})
                raw["ARM"] = arm
                w.writerow(raw)


def _parent_headlines() -> tuple[str, str]:
    p = PARENT_STAMP / "HEADLINE.txt"
    if p.is_file():
        lines = [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
        is_h = next((ln for ln in lines if "IS" in ln and "OOS" not in ln), PARENT_IS_HEADLINE)
        oos_h = next((ln for ln in lines if "OOS" in ln), PARENT_OOS_HEADLINE)
        return is_h, oos_h
    return PARENT_IS_HEADLINE, PARENT_OOS_HEADLINE


def _book_headline(label: str, b: dict[str, Any]) -> str:
    dd = b.get("max_dd")
    dd_s = "—" if dd is None or (isinstance(dd, float) and not math.isfinite(dd)) else f"{float(dd):.2f}%"
    return (
        f"{label}: N={b['n']:,} · WR={b['wr']:.1f}% · "
        f"Avg PnL%={b['avg_pnl_pct']:+.2f} · PF={b['pf']:.2f} · Max DD={dd_s}"
    )


def _symbol_table(by_arm: dict[str, dict[str, dict[str, dict[str, Any]]]]) -> str:
    ths = "".join(
        [
            sortable_th("Symbol", "text"),
            sortable_th("N IS swing", "num"),
            sortable_th("WR IS swing", "num"),
            sortable_th("Avg% IS swing", "num"),
            sortable_th("PF IS swing", "num"),
            sortable_th("N OOS swing", "num"),
            sortable_th("WR OOS swing", "num"),
            sortable_th("Avg% OOS swing", "num"),
            sortable_th("PF OOS swing", "num"),
            sortable_th("N IS ctrl", "num"),
            sortable_th("WR IS ctrl", "num"),
            sortable_th("Avg% IS ctrl", "num"),
            sortable_th("PF IS ctrl", "num"),
        ]
    )
    body = []
    for sym in UNIVERSE_29:
        sw = by_arm[SWING][sym]
        ct = by_arm[CONTROL][sym]
        body.append(
            "<tr>"
            f"<td>{html.escape(sym)}</td>"
            f"<td class='num'>{sw['IS']['n']}</td>"
            f"<td class='num'>{sw['IS']['wr']:.1f}</td>"
            f"<td class='num'>{sw['IS']['avg_pnl_pct']:+.2f}</td>"
            f"<td class='num'>{sw['IS']['pf']:.2f}</td>"
            f"<td class='num'>{sw['OOS']['n']}</td>"
            f"<td class='num'>{sw['OOS']['wr']:.1f}</td>"
            f"<td class='num'>{sw['OOS']['avg_pnl_pct']:+.2f}</td>"
            f"<td class='num'>{sw['OOS']['pf']:.2f}</td>"
            f"<td class='num'>{ct['IS']['n']}</td>"
            f"<td class='num'>{ct['IS']['wr']:.1f}</td>"
            f"<td class='num'>{ct['IS']['avg_pnl_pct']:+.2f}</td>"
            f"<td class='num'>{ct['IS']['pf']:.2f}</td>"
            "</tr>"
        )
    return f"""
<div class="table-wrap"><table class="sortable">
<caption>Per-name IS and OOS under the adopted EXIT_swing freeze, plus control IS. Click column headers to sort. Default order is Paul's list, not a rank.</caption>
<thead><tr>{ths}</tr></thead>
<tbody>
{''.join(body)}
</tbody></table></div>
"""


def _write_baseline(
    path: Path,
    *,
    missing: list[str],
    verdict: str,
    why: str,
    is_sw: dict[str, Any],
    oos_sw: dict[str, Any],
    full_sw: dict[str, Any],
    is_ct: dict[str, Any],
    oos_ct: dict[str, Any],
    parent_is: str,
    parent_oos: str,
) -> None:
    freeze = (
        "`wrl_mode=true`, **`wrl_target_mode=swing`** (EXIT_swing — full size out at swing high), "
        "`wrl_scale_frac=0.50` (unused under swing), `stop_pct=1.0` (multiplier on swing low), "
        "`wrl_min_zone_pct=0` (OFF), `wrl_time_stop_bars=0`, `symbol_reentry_cooldown_days=0` "
        "(OFF; do not wire `cooldown_until`), host `$500k × 2.0 × 0.6` like `run_wrl.bat`."
    )
    miss = f" Missing OHLC (listed, not dropped from the freeze file): {', '.join(missing)}." if missing else ""
    lines = [
        "# WRL EXIT_swing first universe (29 names) — 2026-09-22",
        "",
        "## What you asked",
        "",
        f"> {ORIGINAL_REQUEST.replace(chr(10), chr(10) + '> ')}",
        "",
        "## In plain English",
        "",
        "Weekly Range / Swing (WRL) waits for a daily close in last week's lower pocket, "
        "then buys the next session if price trades back up through that week's low. "
        "The adopted exit sells the whole position at the swing high instead of scaling "
        "half off at last week's high. Paul picked these 29 names after looking at the "
        "full-universe in-sample table and asked to run them as the first tradable sleeve. "
        "We froze that list exactly (29 tickers, no adds/drops), re-ran the same engine, "
        "and also ran the old scale-out exit on the same 29 so we can see what the exit "
        "still does. Out-of-sample numbers are report-only — we do not pick knobs from them.",
        "",
        "## Selection bias (label honesty)",
        "",
        "Paul chose these names **after** seeing the full-universe IS symbol table in "
        f"`{PARENT_STAMP.as_posix().replace(str(REPO).replace(chr(92), '/') + '/', '')}`. "
        "That is **in-sample selection**, even though this page also prints OOS. "
        "Do not treat a good IS sleeve as confirmation. Next promotion step is "
        "walk-forward or a **second** universe — not another IS pick from the same table.",
        "",
        "## Delta from prior",
        "",
        f"- **Adopted parent:** `drive/paul_experiments/wrl_exitswing_is_universe_20260922/`.",
        f"- **Prior freeze:** {freeze}",
        "- **This freeze:** same knobs. **Universe change only:** full production WRL → these 29 names.",
        "- **Leftover one-knob:** same 29 names on the old control exit (`wrl_target_mode=scale`) "
        "so the exit compare is not mixed with the name pick.",
        "- **Not kept:** min-zone, cooldown / `cooldown_until`.",
        f"- **Parent full-universe EXIT_swing (context only, different N):** {parent_is}",
        f"- **Parent OOS (context only):** {parent_oos}",
        "",
        "## Freeze (everything else locked)",
        "",
        freeze,
        "",
        "Universe = first universe, 29 names, Paul's order (see `universe29.csv`): "
        + ", ".join(UNIVERSE_29)
        + f". Count = {len(UNIVERSE_29)}. Do not add/drop.{miss}",
        "",
        "IS = `entry_date < 2024-01-01`. OOS = `entry_date >= 2024-01-01`. Report both N and quality. "
        "Do not retune on OOS.",
        "",
        "## Book headlines (29-name sleeve)",
        "",
        f"- {_book_headline('EXIT_swing IS', is_sw)}",
        f"- {_book_headline('EXIT_swing OOS (report only)', oos_sw)}",
        f"- {_book_headline('EXIT_swing FULL', full_sw)}",
        f"- {_book_headline('Control scale IS (same 29)', is_ct)}",
        f"- {_book_headline('Control scale OOS (same 29, report only)', oos_ct)}",
        "",
        "## Verdict",
        "",
        f"**{verdict}** — {why}",
        "",
        "Research candidate / research sleeve only. Not gold. Not DailyRun. No `run_wrl.bat` change.",
        "",
        "## Promotion",
        "",
        "Research ≠ gold ≠ DailyRun. A KEEP/LEAN KEEP here would still be research-only. "
        "Next step: walk-forward or a second universe, not another in-sample name pick.",
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_hypothesis(
    path: Path,
    *,
    verdict: str,
    why: str,
    is_sw: dict[str, Any],
    oos_sw: dict[str, Any],
    is_ct: dict[str, Any],
    oos_ct: dict[str, Any],
) -> None:
    freeze = (
        "parent EXIT_swing + universe=29 names Paul listed; min-zone 0; cooldown 0; "
        "stop_pct=1.0; scale_frac=0.50 unused under swing; leftover control arm is scale 50/50; "
        "host $500k×2.0×0.6"
    )
    text = "\n".join(
        [
            "# Hypothesis test — WRL EXIT_swing univ29 20260922",
            "",
            "| Field | Fill |",
            "|---|---|",
            "| System / prefix | WRL — Weekly Range / Swing |",
            "| Baseline stamp | parent `wrl_exitswing_is_universe_20260922` (EXIT_swing) |",
            "| Universe | First universe — 29 names Paul listed (see `universe29.csv`). In-sample selection after full-univ IS table. |",
            "| Evidence | Parent full-univ EXIT_swing IS N=89,874 WR=34.3% Avg=+0.70 PF=1.29. First-pass Paul Twenty EXIT_swing was HOLD. |",
            "| Hypothesis | The adopted swing-target exit on this 29-name sleeve is the first tradable research universe. Leftover one-knob: same 29 on old scale exit. |",
            "| Single knob (leftover) | `wrl_target_mode` swing vs scale on the frozen 29 |",
            f"| Frozen settings | {freeze} |",
            "| Alternatives | control scale on same 29; parent full-univ headline for context only |",
            f"| Decision | {verdict} — {why} |",
            f"| IS EXIT_swing | N={is_sw['n']}, WR={is_sw['wr']:.1f}%, Avg%={is_sw['avg_pnl_pct']:+.2f}, PF={is_sw['pf']:.2f} |",
            f"| OOS EXIT_swing (report only) | N={oos_sw['n']}, WR={oos_sw['wr']:.1f}%, Avg%={oos_sw['avg_pnl_pct']:+.2f}, PF={oos_sw['pf']:.2f} |",
            f"| IS control (same 29) | N={is_ct['n']}, WR={is_ct['wr']:.1f}%, Avg%={is_ct['avg_pnl_pct']:+.2f}, PF={is_ct['pf']:.2f} |",
            f"| OOS control (same 29, report only) | N={oos_ct['n']}, WR={oos_ct['wr']:.1f}%, Avg%={oos_ct['avg_pnl_pct']:+.2f}, PF={oos_ct['pf']:.2f} |",
            "| PO sign-off | no |",
            "| Reconcile freeze | no — research only |",
            "",
            "OOS is report-only. Do not retune on OOS. Selection bias: names picked after seeing the parent IS table.",
            "",
        ]
    )
    path.write_text(text, encoding="utf-8")


def write_reports(
    symbols: list[str],
    frames: dict[str, pd.DataFrame],
    missing: list[str],
) -> list[Path]:
    n_univ = 29
    full_books: dict[str, dict[str, Any]] = {}
    is_books: dict[str, dict[str, Any]] = {}
    oos_books: dict[str, dict[str, Any]] = {}
    sums: dict[str, dict[str, Any]] = {}
    audits: dict[str, dict[str, Any]] = {}
    notes: dict[str, str] = {}
    rows_by_arm: dict[str, list[dict[str, Any]]] = {}
    sym_by_arm: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}

    for arm, *_rest in ARMS:
        d = STAMP_DIR / arm
        rows = _closed_rows(d)
        rows_by_arm[arm] = rows
        cash = SHEET_CASH
        aud = _audit_row(d)
        audits[arm] = aud
        c_aud = parse_number(aud.get("brt_cash") or aud.get("sheet_brt_cash"))
        if c_aud and c_aud > 0:
            cash = float(c_aud)
        eq = _latest(d, "WRL_EquityCurve_*.csv")
        if eq and ("_Aggressive_" in eq.name or "_Regular_" in eq.name):
            eq = None
            for p in sorted(d.glob("WRL_EquityCurve_*.csv"), key=lambda x: x.stat().st_mtime, reverse=True):
                if "_Aggressive_" not in p.name and "_Regular_" not in p.name:
                    eq = p
                    break
        full_books[arm] = _book_from_rows(rows, cash=cash, n_univ=n_univ, equity_curve=eq)
        is_books[arm] = _book_from_rows(
            _slice_rows(rows, "IS"),
            cash=cash,
            n_univ=n_univ,
            equity_curve=eq,
            end_date_exclusive=IS_CUT,
        )
        oos_books[arm] = _book_from_rows(
            _slice_rows(rows, "OOS"),
            cash=cash,
            n_univ=n_univ,
            equity_curve=eq,
            start_date=IS_CUT,
        )
        sums[arm] = _summary_aggs(d)
        notes[arm] = full_books[arm].get("note") or ""
        sym_by_arm[arm] = _symbol_books(rows)

    verdict, why = _quality_verdict(
        is_books[CONTROL],
        is_books[SWING],
        oos_ctrl=oos_books[CONTROL],
        oos_cand=oos_books[SWING],
    )
    # Sleeve itself is IS-selected. Even LEAN KEEP on the leftover exit stays research-only.
    overall = verdict
    overall_why = why + (
        " Names were picked after the parent full-universe IS table — in-sample selection. "
        "Research sleeve, not DailyRun. Next promotion step is walk-forward or a second universe."
    )

    parent_is, parent_oos = _parent_headlines()
    _write_baseline(
        STAMP_DIR / "BASELINE.md",
        missing=missing,
        verdict=overall,
        why=overall_why,
        is_sw=is_books[SWING],
        oos_sw=oos_books[SWING],
        full_sw=full_books[SWING],
        is_ct=is_books[CONTROL],
        oos_ct=oos_books[CONTROL],
        parent_is=parent_is,
        parent_oos=parent_oos,
    )
    _write_hypothesis(
        STAMP_DIR / "HYPOTHESIS.md",
        verdict=overall,
        why=overall_why,
        is_sw=is_books[SWING],
        oos_sw=oos_books[SWING],
        is_ct=is_books[CONTROL],
        oos_ct=oos_books[CONTROL],
    )
    _write_universe_csv(STAMP_DIR / "universe29.csv")
    _write_symbol_csv(STAMP_DIR / "WRL_Symbol_IS_OOS.csv", sym_by_arm)
    _write_overlay_csv(STAMP_DIR / "WRL_Closed_overlay.csv", rows_by_arm)

    miss_html = (
        f"<p class='muted'>Listed in the freeze but no/short local OHLC: {html.escape(', '.join(missing))} "
        "(not dropped from <code>universe29.csv</code>).</p>"
        if missing
        else ""
    )
    vcls = "ok" if "KEEP" in overall else ("bad" if overall == "DISMISS" else "warn")
    used = [s for s in UNIVERSE_29 if s in frames]

    html_page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>WRL EXIT_swing first universe (29) — 2026-09-22</title>
<style>
  :root {{ --bg:#f7f6f2; --ink:#1c1b19; --muted:#5a574f; --line:#d4d0c4;
    --card:#fff; --accent:#2a4a5c; --ok:#2d6a4f; --ok-bg:#e8f2ec;
    --warn:#8a5a12; --warn-bg:#f7efe0; --bad:#9b2226; --bad-bg:#fdecea; --fill:#f0eee6; }}
  body {{ margin:0; font-family:"Segoe UI","Helvetica Neue",Georgia,serif; font-size:15px;
    line-height:1.55; color:var(--ink); background:var(--bg); }}
  .wrap {{ max-width:1280px; margin:0 auto; padding:32px 20px 64px; }}
  h1 {{ font-size:1.55rem; margin:0 0 8px; }}
  h2 {{ font-size:1.12rem; margin:26px 0 10px; padding-bottom:5px; border-bottom:1px solid var(--line); }}
  h3 {{ font-size:1.0rem; margin:18px 0 8px; }}
  .lede, .muted {{ color:var(--muted); }}
  .badge {{ display:inline-block; font-size:0.75rem; font-weight:700; padding:2px 8px; background:var(--bad-bg); color:var(--bad); }}
  .callout {{ background:#e8eef2; border-left:4px solid var(--accent); padding:12px 14px; margin:12px 0; }}
  .callout.ok {{ background:var(--ok-bg); border-left-color:var(--ok); }}
  .callout.warn {{ background:var(--warn-bg); border-left-color:var(--warn); }}
  .callout.bad {{ background:var(--bad-bg); border-left-color:var(--bad); }}
  .cards {{ display:flex; flex-wrap:wrap; gap:12px; margin:12px 0 8px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 14px; min-width:150px; flex:1 1 150px; }}
  .card .k {{ font-size:0.75rem; color:var(--muted); font-weight:700; }}
  .card .v {{ font-size:1.2rem; font-weight:700; }}
  .table-wrap {{ overflow-x:auto; margin:8px 0 16px; }}
  table.sortable {{ border-collapse:collapse; width:100%; font-size:13px; }}
  th, td {{ border:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top; }}
  thead th {{ background:var(--fill); }}
  td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  caption {{ text-align:left; font-size:0.82rem; color:var(--muted); caption-side:top; margin:0 0 6px; }}
  code {{ background:var(--fill); padding:0.08em 0.3em; }}
  {SORTABLE_TH_CSS}
</style>
</head>
<body>
<div class="wrap">
  <p class="muted">WRL — Weekly Range / Swing · research stamp 2026-09-22 · parent <code>wrl_exitswing_is_universe_20260922</code></p>
  <h1>WRL EXIT_swing · first universe (29 names)</h1>
  <div class="badge">Research candidate — not gold — not DailyRun</div>
  <p class="lede">Adopted freeze: swing-target exit. Min-zone off. Cooldown off. Universe = these 29 names only.</p>

  <div class="callout">
    <strong>What you asked</strong>
    <p>{html.escape(ORIGINAL_REQUEST).replace(chr(10), "<br/>")}</p>
  </div>
  <div class="callout">
    <strong>In plain English</strong>
    <p>Weekly Range / Swing (WRL) is a weekly demand-zone idea: wait for a daily close in the
    pocket under last week’s range, then buy the next session if price trades back up through
    that week’s low. The house default <em>at this stamp</em> scaled out — half at last week’s high, half at the
    higher swing high. <strong>EXIT_swing</strong> skips the half-sale and exits the whole
    position at the swing high. (House engine default flipped to swing on 2026-09-22; this page is the prior research run.)</p>
    <p>You looked at the full-universe in-sample name table and said thanks — run
    <em>this</em> list as the first universe. We counted 29 tickers, froze them exactly
    (uppercase, no adds or drops), and re-ran the same engine on only those names.
    We also re-ran the old scale-out exit on the same 29 so we can see what the exit
    still does on your sleeve. Quality (win rate, average gain, profit factor, expectancy,
    drawdown) decides KEEP vs HOLD — not trade count. Out-of-sample is report-only.</p>
  </div>

  <div class="callout warn">
    <strong>Selection bias.</strong> These names were picked <em>after</em> seeing the
    parent full-universe in-sample symbol table. That is in-sample selection even though
    this page also prints out-of-sample. Do not treat a good IS sleeve as confirmation.
    Do not pick knobs from OOS. Do not gold. Do not wire DailyRun.
  </div>

  <h2>Freeze</h2>
  <p>Parent <code>wrl_exitswing_is_universe_20260922</code> + universe change only:
  <code>wrl_target_mode=swing</code>, min-zone <strong>off</strong>, scale 50/50 leftover unused,
  stop at swing low, cooldown off — do not wire <code>cooldown_until</code>.
  Host <code>$500k × 2.0 × 0.6</code>.</p>
  <p>Universe (29, Paul's order): <code>{html.escape(", ".join(UNIVERSE_29))}</code>.
  OHLC used: {len(used)}.{html.escape(" Missing: " + ", ".join(missing) if missing else "")}</p>
  <p class="muted">IS = entry &lt; 2024-01-01. OOS = entry ≥ 2024-01-01. Leftover one-knob:
  same 29 on old control exit (<code>wrl_target_mode=scale</code>).</p>

  <h2>Verdict</h2>
  <div class="callout {vcls}"><strong>{html.escape(overall)}.</strong> {html.escape(overall_why)}</div>
  <p class="muted">Judged on IS win rate, Avg PnL%, profit factor, expectancy, Max DD vs control-on-same-29 — not trade count, not Total PnL. OOS is report-only.</p>

  <h2>EXIT_swing 29-name headlines</h2>
  <div class="cards">
    <div class="card"><div class="k">IS trades</div><div class="v">{is_books[SWING]['n']:,}</div></div>
    <div class="card"><div class="k">IS win %</div><div class="v">{is_books[SWING]['wr']:.1f}%</div></div>
    <div class="card"><div class="k">IS Avg PnL%</div><div class="v">{is_books[SWING]['avg_pnl_pct']:+.2f}</div></div>
    <div class="card"><div class="k">IS profit factor</div><div class="v">{is_books[SWING]['pf']:.2f}</div></div>
    <div class="card"><div class="k">OOS trades</div><div class="v">{oos_books[SWING]['n']:,}</div></div>
    <div class="card"><div class="k">OOS win %</div><div class="v">{oos_books[SWING]['wr']:.1f}%</div></div>
    <div class="card"><div class="k">OOS Avg PnL%</div><div class="v">{oos_books[SWING]['avg_pnl_pct']:+.2f}</div></div>
    <div class="card"><div class="k">OOS profit factor</div><div class="v">{oos_books[SWING]['pf']:.2f}</div></div>
  </div>
  <p class="muted">{html.escape(_book_headline("EXIT_swing IS", is_books[SWING]))}</p>
  <p class="muted">{html.escape(_book_headline("EXIT_swing OOS (report only)", oos_books[SWING]))}</p>
  <p class="muted">{html.escape(_book_headline("Control scale IS (same 29)", is_books[CONTROL]))}</p>
  <p class="muted">{html.escape(_book_headline("Control scale OOS (same 29, report only)", oos_books[CONTROL]))}</p>

  <h2>Parent full-universe EXIT_swing (context only — different N)</h2>
  <p class="muted">{html.escape(parent_is)}</p>
  <p class="muted">{html.escape(parent_oos)}</p>
  <p class="muted">Not a same-N compare. Shown so the 29-name sleeve can be read against the firehose it was picked from.</p>

  <h2>In-sample (entry &lt; 2024-01-01) — decide here</h2>
  {_table_compare("IS", is_books, {a: {} for a in is_books}, {a: {} for a in is_books}, {})}

  <h2>Out-of-sample (entry ≥ 2024-01-01) — report only</h2>
  {_table_compare("OOS", oos_books, {a: {} for a in oos_books}, {a: {} for a in oos_books}, {})}

  <h2>FULL book</h2>
  {_table_compare("FULL (all entries)", full_books, sums, audits, notes)}

  {_exit_table(full_books, "Exit mix (FULL book)")}
  {_exit_table(is_books, "Exit mix (IS)")}
  {_exit_table(oos_books, "Exit mix (OOS)")}

  <h2>Per-symbol IS + OOS</h2>
  <p>Default order is Paul's list, not a ranking. Click column headers to sort.</p>
  {_symbol_table(sym_by_arm)}
  {miss_html}

  <h2>Promotion</h2>
  <p>Research sleeve only. Not gold. Not DailyRun. No <code>run_wrl.bat</code> change.
  Next step: walk-forward or a <em>second</em> universe — not another in-sample pick from the parent table.</p>

  <p class="muted">Generated {html.escape(datetime.now().strftime("%Y-%m-%d %H:%M"))} ·
  <code>tools/wrl_exitswing_univ29_20260922.py</code> · research ≠ gold ≠ DailyRun</p>
</div>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    compare = STAMP_DIR / "compare.html"
    summary = STAMP_DIR / "summary.html"
    compare.write_text(html_page, encoding="utf-8")
    summary.write_text(html_page, encoding="utf-8")
    (STAMP_DIR / "HEADLINE.txt").write_text(
        _book_headline("EXIT_swing IS (univ29)", is_books[SWING]) + "\n"
        + _book_headline("EXIT_swing OOS (univ29, report only)", oos_books[SWING]) + "\n"
        + _book_headline("Control scale IS (same 29)", is_books[CONTROL]) + "\n"
        + _book_headline("Control scale OOS (same 29, report only)", oos_books[CONTROL]) + "\n"
        + f"VERDICT={overall}\n{overall_why}\n",
        encoding="utf-8",
    )
    (STAMP_DIR / "OVERALL.txt").write_text(f"{overall}\n{overall_why}\n", encoding="utf-8")
    print(f"[WRL-U29] wrote {compare}", flush=True)
    print(f"[WRL-U29] {_book_headline('IS swing', is_books[SWING])}", flush=True)
    print(f"[WRL-U29] {_book_headline('OOS swing', oos_books[SWING])}", flush=True)
    print(f"[WRL-U29] {_book_headline('IS ctrl', is_books[CONTROL])}", flush=True)
    print(f"[WRL-U29] {_book_headline('OOS ctrl', oos_books[CONTROL])}", flush=True)
    print(f"[WRL-U29] verdict {overall}: {overall_why}", flush=True)
    _ = symbols
    return [compare, summary, STAMP_DIR / "BASELINE.md"]


def main() -> int:
    ap = argparse.ArgumentParser(description="WRL EXIT_swing 29-name first universe 20260922")
    ap.add_argument("--workers", type=int, default=max(1, min(8, os.cpu_count() or 4)))
    ap.add_argument("--summarize-only", action="store_true")
    args = ap.parse_args()
    STAMP_DIR.mkdir(parents=True, exist_ok=True)
    _write_universe_csv(STAMP_DIR / "universe29.csv")

    symbols = list(UNIVERSE_29)
    print(f"[WRL-U29] freeze count={len(symbols)} unique={len(set(symbols))}", flush=True)
    print(f"[WRL-U29] {','.join(symbols)}", flush=True)
    frames: dict[str, pd.DataFrame] = {}
    missing: list[str] = []
    for sym in symbols:
        df = _load_symbol(sym)
        if df is None:
            print(f"[WRL-U29] missing OHLC: {sym}", flush=True)
            missing.append(sym)
            continue
        frames[sym] = df
    kept = [s for s in symbols if s in frames]
    print(
        f"[WRL-U29] {len(frames)}/{len(symbols)} with OHLC, {args.workers} workers -> {STAMP_DIR}",
        flush=True,
    )
    print(
        "[WRL-U29] freeze: EXIT_swing wrl_target_mode=swing; control=scale; "
        "min_zone=0; cooldown=0; stop_pct=1.0",
        flush=True,
    )
    if not frames:
        print("[WRL-U29] no symbol data", flush=True)
        return 1
    if not args.summarize_only:
        for arm, overrides, _n, _k in ARMS:
            _run_arm(arm, overrides, kept, frames, int(args.workers))
    write_reports(kept, frames, missing)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
