#!/usr/bin/env python3
"""WRL first-pass one-knob A/Bs — 2026-09-22.

Weekly Range / Swing (WRL) research stamp. Control = house freeze
(scale 50/50, stop at swing low, min-zone off, cooldown off).

Three one-knob arms from post-run ImproveHints ``260906140457`` + standard
first-pass (exit identity / one entry gate / one hold-exit knob).
Not a kitchen sink. Research only — does not change ``run_wrl.bat``.

IS = entry_date < 2024-01-01. OOS report-only. Do not retune on OOS.
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
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "stock_analysis"))
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
    sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))
    from _gen_too_high_diff import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # type: ignore

STAMP_DIR = REPO / "drive" / "paul_experiments" / "wrl_firstpass_ab_20260922"
DATA_DIR = REPO / "data" / "newdata" / "data"
PAUL20 = REPO / "drive" / "universes" / "PaulTwenty_universe.csv"
IS_CUT = date(2024, 1, 1)
SHEET_CASH = 47_500.0
INIT = 500_000.0

ORIGINAL_REQUEST = (
    "what is our next step to get WRL to be a real tradeable system? "
    "have we analysed post_run_analysis and wired and run AB tests? if not. let's do it!"
)

CONTROL = "00_control"
ARMS: list[tuple[str, dict[str, Any], str, str]] = [
    (
        CONTROL,
        {"wrl_target_mode": "scale"},
        "House freeze at first-pass time: scale 50/50, stop at swing low, min-zone off, cooldown off",
        "CONTROL",
    ),
    (
        "EXIT_swing",
        {"wrl_target_mode": "swing"},
        "EXIT identity: full size out at swing high (vs scale 50/50)",
        "EXIT",
    ),
    (
        "ENTRY_minzone01",
        {"wrl_min_zone_pct": 0.01},
        "ENTRY gate: demand zone must be ≥ 1% wide (range_low / swing_low − 1)",
        "ENTRY",
    ),
    (
        "EXIT_cd5",
        {"symbol_reentry_cooldown_days": 5},
        "HOLD/EXIT: 5-day symbol cooldown after a close (post-TARGET quick-stop hint)",
        "EXIT",
    ),
]


def _load_paul20() -> list[str]:
    if not PAUL20.is_file():
        return []
    out: list[str] = []
    for line in PAUL20.read_text(encoding="utf-8").splitlines():
        t = line.strip().upper()
        if t and not t.startswith("#"):
            out.append(t)
    return out


def _load_symbol(sym: str, data_dir: Path) -> Optional[pd.DataFrame]:
    path = data_dir / f"{sym}.csv"
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
    tasks = [(sym, frames[sym], _wrl_cfg_dict(cfg)) for sym in symbols if sym in frames]
    t0 = time.time()
    results = _run_wrl_symbol_tasks(tasks, workers)
    closed, opens, watch, scanner = [], [], [], []
    for res in results:
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
        f"stamp={ts}\narm={arm}\noverrides={overrides}\nsymbols={','.join(symbols)}\n"
        f"n_closed={len(closed)}\nelapsed_s={time.time() - t0:.1f}\n",
        encoding="utf-8",
    )
    print(
        f"[WRL-1P] {arm}: {len(closed)} closed / {len(opens)} open  "
        f"({time.time() - t0:.1f}s) -> {arm_dir}",
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
            out.append(
                {
                    "symbol": str(row.get("SYMBOL") or "").upper(),
                    "opened": opened,
                    "closed": closed,
                    "pnl": _f(row.get("PNL_PCT")),
                    "pnl_d": _f(row.get("PNL_DOLLARS")),
                    "days": _f(row.get("DAYS_HELD")),
                    "exit": str(row.get("EXIT_TYPE") or "").strip().upper(),
                    "win": _f(row.get("PNL_PCT")) > 0,
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
    # all equal
    return sum(pcts[:-1]) / (len(pcts) - 1)


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
    exp_pct = avg
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
        "exp_pct": exp_pct,
        "exp_d": (sum(float(r["pnl_d"]) for r in rows) / n) if n else 0.0,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "wl_count": wl_count,
        "wl_d": (sum_w / sum_l) if sum_l > 0 else 0.0,
        "pf": pf,
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
        "n_sym": 0,
    }
    if not p:
        return empty
    pauls, fits, robs, wos, outs, tpys, maxw = [], [], [], [], [], [], []
    with p.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        for row in csv.DictReader(f):
            pauls.append(_f(row.get("PAUL_SCORE")))
            fits.append(_f(row.get("FIT_SCORE")))
            robs.append(_f(row.get("FIT_SCORE_ROBUST")))
            wos.append(_f(row.get("AVG_PNL_PCT_WO_MAX")))
            outs.append(_f(row.get("OUTLIER_PCT_OF_WINS")))
            tpys.append(_f(row.get("AVG_TRADES_PER_YEAR")))
            maxw.append(_f(row.get("MAX_WIN_PCT")))
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
        return f"{int(round(float(v)))}"
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
        return "DISMISS", "IS Avg PnL% and profit factor both worse than control."
    if avg_up and (pf_up or wr_up) and n_ok and not dd_worse:
        if oos_soft:
            return (
                "HOLD",
                "IS quality improved, but OOS softened vs control / vs IS — report-only; do not adopt or retune on OOS.",
            )
        return (
            "LEAN KEEP",
            "IS quality improved (Avg PnL% plus WR or PF) without collapsing N or blowing up Max DD. Research candidate only — not gold / not DailyRun.",
        )
    if dd_worse and (avg_up or pf_up):
        return "HOLD", "Some IS quality lift but Max DD is worse by >5pp — do not adopt on quality-up-with-worse-DD."
    if not n_ok and (avg_up or pf_up):
        return "HOLD", "Quality numbers moved, but trade count collapsed (>40% drop) — judge quality, not a thin book."
    return "HOLD", "IS quality is mixed or flat vs control. Keep the house freeze."


def _metric_rows(
    books: dict[str, dict[str, Any]],
    sums: dict[str, dict[str, Any]],
    audits: dict[str, dict[str, Any]],
) -> list[tuple[str, str, dict[str, Any]]]:
    """(label, kind, {arm: value})."""
    ctrl = books[CONTROL]

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
        ("Losing streak", "int", {a: g(a, "Losing_Streak", "audit") for a in books}),
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
    ]
    # drop excluded labels (Total/Sheet PnL $)
    wanted = set(canonical_book_order_html())
    rows = [r for r in rows if r[0] in wanted or r[0] not in ("Total PnL $", "Sheet PnL $")]
    rows = filter_html_compare_metric_rows(rows, label_index=0)
    _ = ctrl
    return rows


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
                dkind = "money_d" if kind == "money" else kind
                tds.append(f"<td class='num'>{_fmt(d, dkind)}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    note_bits = [f"{html.escape(a)}: {html.escape(n)}" for a, n in notes.items() if n]
    note_html = (
        f"<p class='muted'>{' · '.join(note_bits)}</p>" if note_bits else ""
    )
    return f"""
<h3>{html.escape(title)}</h3>
<p class="muted">Click column headers to sort. Total PnL $ / Sheet PnL $ omitted from HTML (canonical rule).</p>
<div class="table-wrap"><table class="sortable">
<caption>{html.escape(title)} — absolute values and deltas vs {CONTROL}</caption>
<thead><tr>{''.join(ths)}</tr></thead>
<tbody>
{''.join(body)}
</tbody></table></div>
{note_html}
"""


def _exit_table(books: dict[str, dict[str, Any]]) -> str:
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
<h3>Exit mix (FULL book)</h3>
<p class="muted">Click column headers to sort. Counts and % of Closed EXIT_TYPE.</p>
<div class="table-wrap"><table class="sortable">
<thead><tr>{''.join(ths)}</tr></thead>
<tbody>{''.join(body)}</tbody>
</table></div>
"""


def _write_md(
    path: Path,
    symbols: list[str],
    verdicts: dict[str, tuple[str, str]],
    freeze: str,
) -> None:
    lines = [
        "# WRL first-pass A/B — 2026-09-22",
        "",
        "## What you asked",
        "",
        f"> {ORIGINAL_REQUEST}",
        "",
        "## In plain English",
        "",
        "Weekly Range / Swing (WRL) watches a daily close in last week's lower pocket, "
        "then buys the next session if price trades back up through that week's low. "
        "We checked whether post-run analysis and proper one-knob A/B tests already existed. "
        "Cheap ImproveHints existed on the 2026-09-06 full-universe book; deep charts/assessments "
        "did not. A Mag10 kitchen-sink A/B existed without IS/OOS and judged Total PnL. "
        "This stamp runs the three first-pass knobs the hints actually point at, with IS/OOS, "
        "on Paul Twenty.",
        "",
        "## Freeze (everything else locked)",
        "",
        freeze,
        "",
        f"Universe: Paul Twenty ({', '.join(symbols)}).",
        "IS = `entry_date < 2024-01-01`. OOS report-only. Do not retune on OOS.",
        "",
        "## Arms (one knob each)",
        "",
    ]
    for arm, ov, note, kind in ARMS:
        lines.append(f"- `{arm}` [{kind}]: {note} `{ov or '{}'}`")
    lines.extend(["", "## Verdicts (IS quality; OOS report-only)", ""])
    for arm, (lab, why) in verdicts.items():
        lines.append(f"- **{arm} — {lab}:** {why}")
    lines.extend(
        [
            "",
            "## Promotion",
            "",
            "Research candidate only. Not gold. Not DailyRun. No `run_wrl.bat` change.",
            "",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_reports(
    symbols: list[str],
    frames: dict[str, pd.DataFrame],
) -> list[Path]:
    n_univ = len(frames)
    full_books: dict[str, dict[str, Any]] = {}
    is_books: dict[str, dict[str, Any]] = {}
    oos_books: dict[str, dict[str, Any]] = {}
    sums: dict[str, dict[str, Any]] = {}
    audits: dict[str, dict[str, Any]] = {}
    notes: dict[str, str] = {}

    for arm, *_rest in ARMS:
        d = STAMP_DIR / arm
        rows = _closed_rows(d)
        cash = SHEET_CASH
        aud = _audit_row(d)
        audits[arm] = aud
        c_aud = parse_number(aud.get("brt_cash") or aud.get("sheet_brt_cash"))
        if c_aud and c_aud > 0:
            cash = float(c_aud)
        eq = _latest(d, "WRL_EquityCurve_*.csv")
        # skip Aggressive/Regular sidecars for host sharpe
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

    verdicts: dict[str, tuple[str, str]] = {}
    for arm, *_r in ARMS:
        if arm == CONTROL:
            continue
        verdicts[arm] = _quality_verdict(
            is_books[CONTROL],
            is_books[arm],
            oos_ctrl=oos_books[CONTROL],
            oos_cand=oos_books[arm],
        )

    # Overall: if any LEAN KEEP and none DISMISS with worse book → HOLD on adopt
    labs = {arm: v[0] for arm, v in verdicts.items()}
    if any(v == "DISMISS" for v in labs.values()) and not any(v == "LEAN KEEP" for v in labs.values()):
        overall = "DISMISS"
        overall_why = "No arm improved IS quality; keep the house freeze."
    elif any(v == "LEAN KEEP" for v in labs.values()):
        keepers = [a for a, v in labs.items() if v == "LEAN KEEP"]
        overall = "HOLD"
        overall_why = (
            f"IS lean-keep on {', '.join(keepers)} is research-only. "
            "Do not adopt into run_wrl.bat or DailyRun from this IS horse-race. "
            "Next: re-score the chosen freeze on a wider/tradable universe + walk-forward before gold."
        )
    else:
        overall = "HOLD"
        overall_why = (
            "HOLD — do not adopt any arm into run_wrl.bat. "
            "EXIT_swing lifts IS Avg PnL% / PF but win rate drops ~6pp (same pattern as the old Mag10 "
            "Total-PnL 'winner'). ENTRY_minzone01 is a modest IS quality lift (WR +2.8pp, Avg +0.10) "
            "and does not reverse vs control in OOS — still not KEEP. "
            "EXIT_cd5 is a null test: rocket_wrl never assigns cooldown_until, so the 5-day cooldown "
            "knob does not fire. The live gap to tradeable is universe + capacity, not another kitchen-sink sweep."
        )

    freeze = (
        "`wrl_mode=true`, `wrl_target_mode=scale`, `wrl_scale_frac=0.50`, "
        "`stop_pct=1.0` (multiplier on swing low), `wrl_min_zone_pct=0`, "
        "`wrl_time_stop_bars=0`, `symbol_reentry_cooldown_days=0`, "
        "host `$500k × 2.0 × 0.6` like `run_wrl.bat`."
    )
    _write_md(STAMP_DIR / "BASELINE.md", symbols, verdicts, freeze)
    (STAMP_DIR / "HYPOTHESIS.md").write_text(
        "\n".join(
            [
                "# Hypothesis test — WRL first-pass 20260922",
                "",
                f"| Field | Fill |",
                f"|---|---|",
                f"| System / prefix | WRL — Weekly Range / Swing |",
                f"| Baseline stamp | house `run_wrl.bat` / `WRL_BASELINE` (scale 50/50) |",
                f"| Universe | Paul Twenty |",
                f"| Evidence | ImproveHints `260906140457`: small_target_wins, band_tighten_weak_fill, post_target_quick_stop |",
                f"| Hypotheses | EXIT swing target; ENTRY 1% min zone; EXIT 5-day cooldown |",
                f"| Frozen settings | {freeze} |",
                f"| Alternatives | control + 1 value each (3 arms) |",
                f"| Decision | see compare.html — IS quality; OOS report-only |",
                f"| PO sign-off | no |",
                f"| Reconcile freeze | no — research only |",
                "",
            ]
        ),
        encoding="utf-8",
    )

    v_html = []
    for arm, (lab, why) in verdicts.items():
        cls = "ok" if "KEEP" in lab else ("bad" if lab == "DISMISS" else "warn")
        v_html.append(
            f"<div class='callout {cls}'><strong>{html.escape(arm)} — {html.escape(lab)}.</strong> "
            f"{html.escape(why)}</div>"
        )
    ocls = "warn" if overall == "HOLD" else ("bad" if overall == "DISMISS" else "ok")

    html_page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>WRL first-pass A/B — 2026-09-22</title>
<style>
  :root {{ --bg:#f7f6f2; --ink:#1c1b19; --muted:#5a574f; --line:#d4d0c4;
    --card:#fff; --accent:#2a4a5c; --ok:#2d6a4f; --ok-bg:#e8f2ec;
    --warn:#8a5a12; --warn-bg:#f7efe0; --bad:#9b2226; --bad-bg:#fdecea; --fill:#f0eee6; }}
  body {{ margin:0; font-family:"Segoe UI","Helvetica Neue",Georgia,serif; font-size:15px;
    line-height:1.55; color:var(--ink); background:var(--bg); }}
  .wrap {{ max-width:1180px; margin:0 auto; padding:32px 20px 64px; }}
  h1 {{ font-size:1.55rem; margin:0 0 8px; }}
  h2 {{ font-size:1.12rem; margin:26px 0 10px; padding-bottom:5px; border-bottom:1px solid var(--line); }}
  h3 {{ font-size:1.0rem; margin:18px 0 8px; }}
  .lede, .muted {{ color:var(--muted); }}
  .badge {{ display:inline-block; font-size:0.75rem; font-weight:700; padding:2px 8px; background:var(--bad-bg); color:var(--bad); }}
  .callout {{ background:#e8eef2; border-left:4px solid var(--accent); padding:12px 14px; margin:12px 0; }}
  .callout.ok {{ background:var(--ok-bg); border-left-color:var(--ok); }}
  .callout.warn {{ background:var(--warn-bg); border-left-color:var(--warn); }}
  .callout.bad {{ background:var(--bad-bg); border-left-color:var(--bad); }}
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
  <p class="muted">WRL philosophy: <code>docs/systems/wrl.html</code> · research stamp 2026-09-22</p>
  <h1>WRL — Weekly Range / Swing · first-pass A/B</h1>
  <div class="badge">Research candidate — not gold — not DailyRun</div>
  <p class="lede">Paul Twenty · one knob at a time · IS quality · OOS report-only.</p>

  <div class="callout">
    <strong>What you asked</strong>
    <p>{html.escape(ORIGINAL_REQUEST)}</p>
  </div>
  <div class="callout">
    <strong>In plain English</strong>
    <p>Weekly Range / Swing (WRL) is a weekly demand-zone idea: wait for a daily close in the pocket
    under last week’s range, then buy the next session if price trades back up through that week’s low
    (a buy-stop, not a chase). “Post-run analysis” is the house after-action report that lists
    patterns (too many tiny wins, stops that bounce back, etc.). An A/B test changes
    <em>one</em> setting and compares trade quality — win rate, average gain, drawdown — not raw dollar
    totals.</p>
    <p>Cheap ImproveHints already existed on the 6 Sep 2026 full-universe book. Deep charts/assessments
    did not. A Mag10 nine-arm compare existed but judged Total PnL, had no in-sample / out-of-sample
    split, and is not a house-process stamp. This page runs the three first-pass knobs those hints
    actually recommend.</p>
  </div>

  <h2>Status audit (evidence)</h2>
  <div class="table-wrap"><table class="sortable">
  <caption>Click column headers to sort</caption>
  <thead><tr>
    {sortable_th("Question","text")}{sortable_th("Answer","text")}{sortable_th("Evidence","text")}
  </tr></thead>
  <tbody>
    <tr><td>Engine / scanner / Closed</td><td>Yes</td>
      <td><code>stock_analysis/rocket_wrl.py</code> + <code>wrl_zones.py</code> · <code>run_wrl.bat</code> · latest Closed <code>drive/WRL_Closed_260906140457.csv</code> (2026-09-06; 114,791 trades)</td></tr>
    <tr><td>Cheap post_run (ImproveHints)</td><td>Yes — 2026-09-06</td>
      <td><code>drive/WRL_ImproveHints_260906140457.html</code></td></tr>
    <tr><td>Deep post_run (assessments)</td><td>Yes — 2026-09-22 on latest stamp (--no-charts)</td>
      <td><code>drive/WRL_SymbolAssessments_260906140457.html</code> (prior deep was 2026-08-12 Mag10-sized)</td></tr>
    <tr><td>A/B harness wired</td><td>Yes (kitchen sink)</td>
      <td><code>tools/run_wrl_ab.py</code> · 9 Mag10 arms · judged Total PnL · no IS/OOS</td></tr>
    <tr><td>House-process A/B run</td><td>This stamp</td>
      <td>Paul Twenty · 3 one-knob arms · IS/OOS · canonical metrics</td></tr>
    <tr><td>DailyRun</td><td>Not wired</td>
      <td><code>dailyrun_system_status.py</code> <code>wired=False</code></td></tr>
    <tr><td>getTarget / philosophy</td><td>Yes</td>
      <td><code>getTarget.py</code> <code>compute_wrl_system</code> · <code>docs/systems/wrl.html</code></td></tr>
  </tbody></table></div>

  <h2>Freeze</h2>
  <p>{html.escape(freeze)} Universe: <code>{html.escape(','.join(symbols))}</code> ({n_univ} with OHLC).</p>

  <h2>Arms</h2>
  <div class="table-wrap"><table class="sortable">
  <thead><tr>
    {sortable_th("Arm","text")}{sortable_th("Kind","text")}{sortable_th("One knob","text")}{sortable_th("Why (hint)","text")}
  </tr></thead>
  <tbody>
    <tr><td><code>00_control</code></td><td>CONTROL</td><td><code>wrl_target_mode=scale</code></td><td>Pinned old house (scale 50/50) — not the 2026-09-22 swing default</td></tr>
    <tr><td><code>EXIT_swing</code></td><td>EXIT</td><td><code>wrl_target_mode=swing</code></td>
      <td>ImproveHints <code>small_target_wins</code> + target-expand</td></tr>
    <tr><td><code>ENTRY_minzone01</code></td><td>ENTRY</td><td><code>wrl_min_zone_pct=0.01</code></td>
      <td>ImproveHints <code>band_tighten_weak_fill</code></td></tr>
    <tr><td><code>EXIT_cd5</code></td><td>EXIT</td><td><code>symbol_reentry_cooldown_days=5</code></td>
      <td>ImproveHints <code>post_target_quick_stop</code> — <strong>null test</strong>: engine never sets <code>cooldown_until</code></td></tr>
  </tbody></table></div>

  <h2>Verdict</h2>
  <div class="callout {ocls}"><strong>Overall: {html.escape(overall)}.</strong> {html.escape(overall_why)}</div>
  {''.join(v_html)}
  <div class="callout warn"><strong>EXIT_cd5 is a null test.</strong> <code>rocket_wrl.backtest_symbol</code> reads <code>cooldown_until</code> but never assigns it, so a 5-day cooldown does not change the book. Do not treat this arm as evidence against the post-TARGET quick-stop hint.</div>
  <p class="muted">Judged on IS win rate, Avg PnL%, profit factor, expectancy, Max DD — not trade count, not Total PnL. OOS is report-only.</p>

  <h2>FULL book</h2>
  {_table_compare("FULL (all entries)", full_books, sums, audits, notes)}

  <h2>In-sample (entry &lt; 2024-01-01) — decide here</h2>
  {_table_compare("IS", is_books, {a: {} for a in is_books}, {a: {} for a in is_books}, {})}

  <h2>Out-of-sample (entry ≥ 2024-01-01) — report only</h2>
  {_table_compare("OOS", oos_books, {a: {} for a in oos_books}, {a: {} for a in oos_books}, {})}

  {_exit_table(full_books)}

  <h2>What is still missing vs a real tradeable system</h2>
  <ol>
    <li><strong>Tradable universe + capacity.</strong> The 6 Sep 2026 full-universe Closed book has 114,791 trades, win rate 41.3%, average gain +0.56% (below the FIT expectancy gate of 2.5%), and 535 names on at once. That is a firehose, not a sleeve you can size. Next concrete step: freeze a Paul-class / ADV / name-cap list (not ALL) and re-score this freeze on that list.</li>
    <li><strong>Gold bar.</strong> Wider or walk-forward confirmation on the chosen freeze. This in-sample horse-race is not gold. Do not retune on out-of-sample if it softens.</li>
    <li><strong>DailyRun.</strong> Explicit wire in <code>DailyRun.bat</code> plus registry <code>wired=True</code>, Closed parity/reconcile, and a getTarget live check. The philosophy page already exists. Do not wire from this stamp alone.</li>
    <li><strong>Live-style size vs SPY.</strong> Honest dollar risk / name cap on the frozen universe. WRL is named on live-style lists but is not in the official $500k mix.</li>
  </ol>
  <p><strong>Honest next step:</strong> pick one tradable universe (Paul Twenty already used here, or an ADV cut of the full book — not 500 concurrent names), re-run control vs any lean-keep under that freeze, then walk-forward. If quality still holds, product-owner sign-off plus reconcile freeze. Only then consider DailyRun behind <code>SKIP_WRL</code>.</p>

  <h2>Prior Mag10 kitchen sink (do not redo)</h2>
  <p class="muted"><code>docs/systems/wrl_ab.html</code> — Mag10, 9 arms, winner picked by Total PnL
  (<code>02_target_swing</code>). Win rate fell 43.9% → 36.3%. No IS/OOS. Not a promotion stamp.
  Local <code>drive/paul_experiments/wrl/ab_levers/</code> is missing.</p>

  <p class="muted">Generated {html.escape(datetime.now().strftime("%Y-%m-%d %H:%M"))} ·
  <code>tools/wrl_firstpass_ab_20260922.py</code> · research ≠ gold ≠ DailyRun</p>
</div>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    compare = STAMP_DIR / "compare.html"
    compare.write_text(html_page, encoding="utf-8")
    (STAMP_DIR / "OVERALL.txt").write_text(f"{overall}\n{overall_why}\n", encoding="utf-8")
    print(f"[WRL-1P] wrote {compare}", flush=True)
    print(f"[WRL-1P] overall {overall}: {overall_why}", flush=True)
    return [compare, STAMP_DIR / "BASELINE.md"]


def main() -> int:
    ap = argparse.ArgumentParser(description="WRL first-pass one-knob A/B 20260922")
    ap.add_argument("--workers", type=int, default=max(1, min(8, os.cpu_count() or 4)))
    ap.add_argument("--summarize-only", action="store_true")
    ap.add_argument("--symbols", default="", help="Override comma list (default Paul Twenty)")
    args = ap.parse_args()
    STAMP_DIR.mkdir(parents=True, exist_ok=True)
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = _load_paul20()
        if not symbols:
            symbols = ["AAPL", "AMD", "AMZN", "AU", "GOOGL", "META", "MSFT", "NFLX", "NVDA", "TSLA"]
            print("[WRL-1P] PaulTwenty missing — falling back to Mag10", flush=True)
    frames: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        df = _load_symbol(sym, DATA_DIR)
        if df is None:
            print(f"[WRL-1P] skip {sym}: no OHLC", flush=True)
            continue
        frames[sym] = df
    if not frames:
        print("[WRL-1P] no symbol data", flush=True)
        return 1
    kept = [s for s in symbols if s in frames]
    print(f"[WRL-1P] {len(frames)} symbols, {args.workers} workers -> {STAMP_DIR}", flush=True)
    if not args.summarize_only:
        for arm, overrides, _n, _k in ARMS:
            _run_arm(arm, overrides, kept, frames, int(args.workers))
    write_reports(kept, frames)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
