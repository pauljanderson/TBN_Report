#!/usr/bin/env python3
"""Live BRT + walk-forward for IS Paul8+FIT6 55-name research sleeve.

1) Assumes live full-history run already exists under OUT (isolated -o).
2) Rolling walk-forward: train 3y / test 1y (frozen run_brt.bat knobs; no retune).
3) Sortable compare HTML: live 55 vs production 42 + WF summary.
4) BASELINE.md + PO_REVIEW.md — research sleeve only; do not invent PO sign-off.

Does not edit BRT_universe.csv / run_brt.bat / DailyRun.
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import math
import os
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock_analysis"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
sys.path.insert(0, str(ROOT / "tools"))

from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    format_money,
    format_money_delta,
    overlay_ann_ror_max_dd,
    parse_number,
)
from walkforward import build_rolling_folds  # noqa: E402

OUT = ROOT / "drive" / "paul_experiments" / "brt_is_paul8_fit6_live_wf_20260820"
UNIV_55 = ROOT / "drive" / "universes" / "BRT_is_paul8_fit6_260820002407.csv"
UNIV_42 = ROOT / "drive" / "universes" / "BRT_universe.csv"
LIVE_STAMP = "260820142629"
PROD42_STAMP = "260820120322"
PROD42_CLOSED = ROOT / "drive" / f"BRT_Closed_{PROD42_STAMP}.csv"
PROD42_REPORT = ROOT / "drive" / f"BRT_Report_{PROD42_STAMP}.csv"
PROD42_SUMMARY = ROOT / "drive" / f"BRT_Summary_{PROD42_STAMP}.csv"
IS_CUT = date(2024, 1, 1)
SHEET = 47_500.0
PRIOR_HOLD = "drive/paul_experiments/brt_is_paul8_fit6_20260820_v2"

SORTABLE_TH_CSS = """
th.sortable-th { cursor: pointer; user-select: none; white-space: nowrap; }
th.sortable-th:hover { background: #e2e8f0; }
th.sortable-th .sort-ind::after { content: " \\2195"; opacity: .35; font-size: .85em; }
th.sortable-th.sort-asc .sort-ind::after { content: " \\2191"; opacity: .9; }
th.sortable-th.sort-desc .sort-ind::after { content: " \\2193"; opacity: .9; }
"""
SORTABLE_TABLE_SCRIPT = """
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : 0;
    if (type === "text") return s.toUpperCase();
    if (type === "date") {
      var iso = s.match(/(\\d{4})-(\\d{2})-(\\d{2})/);
      if (iso) return parseInt(iso[1] + iso[2] + iso[3], 10);
      return 0;
    }
    var n = s.replace(/[$,%+]/g, "").replace(/,/g, "");
    var v = parseFloat(n);
    return Number.isFinite(v) ? v : 0;
  }
  function sortTable(table, col, type, dir) {
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll("tr"));
    var pinned = rows.filter(function (r) { return r.classList.contains("total-row"); });
    var movable = rows.filter(function (r) { return !r.classList.contains("total-row"); });
    movable.sort(function (a, b) {
      var av = parseSortValue(a.cells[col] && a.cells[col].textContent, type);
      var bv = parseSortValue(b.cells[col] && b.cells[col].textContent, type);
      if (typeof av === "string" || typeof bv === "string") {
        return dir * String(av).localeCompare(String(bv));
      }
      return dir * (av - bv);
    });
    movable.concat(pinned).forEach(function (r) { tbody.appendChild(r); });
  }
  function bindSortHeader(table, th, col) {
    function onActivate(e) {
      if (e.type === "touchend") e.preventDefault();
      var type = th.dataset.sort || "text";
      var dir = th.dataset.dir === "asc" ? -1 : 1;
      table.querySelectorAll("th.sortable-th").forEach(function (h) {
        h.dataset.dir = "";
        h.classList.remove("sort-asc", "sort-desc");
        h.setAttribute("aria-sort", "none");
      });
      th.dataset.dir = dir === 1 ? "asc" : "desc";
      th.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
      th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
      sortTable(table, col, type, dir);
    }
    th.addEventListener("click", onActivate);
    th.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onActivate(e); }
    });
    th.addEventListener("touchend", onActivate, { passive: false });
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("th.sortable-th").forEach(function (th, col) {
      bindSortHeader(table, th, col);
    });
  });
})();
</script>
"""


def escape(s: Any) -> str:
    return html_mod.escape("" if s is None else str(s))


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _f(v: Any) -> float:
    n = parse_number(v)
    return float(n) if n is not None else 0.0


def _parse_d(v: Any) -> Optional[date]:
    s = str(v or "").strip()
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) >= 8:
        try:
            return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
        except ValueError:
            return None
    if len(s) >= 10 and s[4] == "-":
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None
    return None


def load_universe(path: Path) -> list[str]:
    out: list[str] = []
    with path.open(encoding="utf-8-sig") as f:
        for ln in f:
            s = ln.strip().upper()
            if not s or s.startswith("#") or s == "SYMBOL":
                continue
            if "," in s and "SYMBOL" in s.upper():
                continue
            out.append(s.split(",")[0].strip())
    return out


def load_report(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        row = next(csv.DictReader(f), None)
    return dict(row) if row else {}


def load_closed(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _parse_d(raw.get("DATE_OPENED") or raw.get("DATE OPENED") or "")
            if opened is None:
                continue
            sym = str(raw.get("SYMBOL") or "").strip().upper()
            if not sym:
                continue
            closed = _parse_d(raw.get("DATE_CLOSED") or raw.get("DATE CLOSED") or "")
            pnl = _f(raw.get("PNL_PCT") or raw.get("PNL %"))
            entry = _f(raw.get("ENTRY_PRICE") or raw.get("ENTRY PRICE"))
            stop = _f(raw.get("STOP_PRICE") or raw.get("STOP PRICE"))
            r_col = _f(raw.get("R_MULT") or raw.get("R_MULTIPLE"))
            risk_pct = ((entry - stop) / entry * 100.0) if entry > 0 and stop > 0 else 0.0
            r_mult = r_col if r_col else (pnl / risk_pct if risk_pct > 1e-9 else 0.0)
            rows.append(
                {
                    "sym": sym,
                    "opened": opened,
                    "closed": closed,
                    "pnl": pnl,
                    "r": r_mult,
                    "days": _f(raw.get("DAYS_HELD") or raw.get("DAYS HELD")),
                    "pnl_d": _f(raw.get("PNL_DOLLARS") or raw.get("PNL $")),
                    "exit": str(raw.get("EXIT_TYPE") or raw.get("EXIT TYPE") or "").strip(),
                }
            )
    return rows


def book_stats(trades: list[dict[str, Any]], *, cash: float) -> dict[str, Any]:
    n = len(trades)
    empty = {
        "n": 0,
        "wins": 0,
        "losses": 0,
        "wr": 0.0,
        "avg_pnl": 0.0,
        "avg_pnl_wo_max": 0.0,
        "avg_r": 0.0,
        "pf": 0.0,
        "sheet": 0.0,
        "pnl_d": 0.0,
        "avg_days": 0.0,
        "ann_ror": float("nan"),
        "max_dd": float("nan"),
        "capital_days": 0.0,
        "exit_counts": {},
    }
    if n == 0:
        return empty
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    if n >= 2:
        mx = max(pnls)
        avg_wo = (sum(pnls) - mx) / (n - 1)
    else:
        avg_wo = sum(pnls) / n
    days = [t["days"] for t in trades]
    ov = overlay_ann_ror_max_dd(trades, cash=cash if cash > 0 else SHEET)
    pnl_d = float(ov.get("pnl_d") or sum(t["pnl_d"] for t in trades))
    cap_d = float(ov.get("capital_days") or sum(days))
    exits = Counter(str(t.get("exit") or "").strip() or "?" for t in trades)
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "wr": 100.0 * len(wins) / n,
        "avg_pnl": sum(pnls) / n,
        "avg_pnl_wo_max": avg_wo,
        "avg_r": sum(t["r"] for t in trades) / n,
        "pf": (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0),
        "sheet": sum(p / 100.0 * SHEET for p in pnls),
        "pnl_d": pnl_d,
        "avg_days": sum(days) / n if days else 0.0,
        "ann_ror": ov["ann_ror"],
        "max_dd": ov["max_dd"],
        "capital_days": cap_d,
        "exit_counts": dict(exits),
        "ann_ror_note": ov.get("note") or "",
    }


def split_is_oos(trades: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    is_t = [t for t in trades if t["opened"] < IS_CUT]
    oos_t = [t for t in trades if t["opened"] >= IS_CUT]
    return is_t, oos_t


def cash_from_report(rep: dict[str, Any]) -> float:
    for k in ("sheet_brt_cash", "brt_cash", "sheet_brt_cash"):
        v = parse_number(rep.get(k))
        if v is not None and v > 0:
            return float(v)
    return SHEET


def summary_agg(path: Path) -> dict[str, Any]:
    out = {
        "n_sym": 0,
        "mean_paul": float("nan"),
        "mean_fit": float("nan"),
        "mean_fit_robust": float("nan"),
        "mean_wo_max": float("nan"),
        "mean_outlier": float("nan"),
        "mean_tpy": float("nan"),
    }
    if not path.is_file():
        return out
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig", newline="")))
    if not rows:
        return out
    n = len(rows)
    def mean(key: str) -> float:
        vals = [_f(r.get(key)) for r in rows]
        return sum(vals) / n if n else float("nan")

    out.update(
        {
            "n_sym": n,
            "mean_paul": mean("PAUL_SCORE"),
            "mean_fit": mean("FIT_SCORE"),
            "mean_fit_robust": mean("FIT_SCORE_ROBUST"),
            "mean_wo_max": mean("AVG_PNL_PCT_WO_MAX"),
            "mean_outlier": mean("OUTLIER_PCT_OF_WINS"),
            "mean_tpy": mean("AVG_TRADES_PER_YEAR"),
        }
    )
    return out


def fmt_num(v: Any, nd: int = 2) -> str:
    n = parse_number(v)
    if n is None or (isinstance(n, float) and (math.isnan(n) or math.isinf(n))):
        return "—"
    return f"{n:.{nd}f}"


def fmt_pct(v: Any, nd: int = 1) -> str:
    n = parse_number(v)
    if n is None or (isinstance(n, float) and math.isnan(n)):
        return "—"
    return f"{n:.{nd}f}%"


def delta(a: Any, b: Any) -> Optional[float]:
    xa, xb = parse_number(a), parse_number(b)
    if xa is None or xb is None:
        return None
    return xa - xb


def resolve_python() -> str:
    env_py = os.environ.get("PY", "").strip()
    if env_py and Path(env_py).is_file():
        return env_py
    return sys.executable


def find_latest(outdir: Path, pattern: str) -> Optional[Path]:
    files = sorted(outdir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def extract_metrics(outdir: Path) -> Optional[dict[str, Any]]:
    report = find_latest(outdir, "BRT_Report_*.csv")
    if report is None:
        return None
    rep = load_report(report)
    closed = find_latest(outdir, "BRT_Closed_*.csv")
    trades = load_closed(closed) if closed else []
    wins = int(_f(rep.get("Wins")))
    total = int(_f(rep.get("Total_Trades")))
    if total <= 0:
        total = len(trades)
    wr = (100.0 * wins / total) if total else _f(rep.get("Pct_Wins"))
    return {
        "report": report.name,
        "closed": closed.name if closed else "",
        "n": total,
        "wr": wr,
        "avg_pnl": _f(rep.get("Avg_PNL_Pct")),
        "pf": _f(rep.get("Profit_Factor")),
        "ann_ror": _f(rep.get("Ann_ROR")),
        "max_dd": _f(rep.get("Max_DD")),
        "total_pnl": _f(rep.get("Total_PNL")),
        "sheet_pnl": _f(rep.get("sheet_PnL")),
        "brt_cash": cash_from_report(rep),
    }


def run_fold(
    fold_name: str,
    entry_start: str,
    entry_end: str,
    *,
    workers: int = 24,
) -> dict[str, Any]:
    outdir = OUT / "wf_folds" / fold_name
    outdir.mkdir(parents=True, exist_ok=True)
    existing = extract_metrics(outdir)
    if existing is not None and existing.get("n", 0) >= 0 and find_latest(outdir, "BRT_Report_*.csv"):
        existing["fold"] = fold_name
        existing["entry_start"] = entry_start
        existing["entry_end"] = entry_end
        existing["skipped"] = True
        existing["ok"] = True
        return existing

    # Use run_brt.bat so knobs stay identical (do not mutate bat).
    cmd = [
        "cmd",
        "/c",
        "run_brt.bat",
        str(UNIV_55),
        "-o",
        str(outdir),
        "-w",
        str(workers),
        "-v",
        f"entry_start_date={entry_start}",
        "-v",
        f"entry_end_date={entry_end}",
    ]
    log_path = outdir / "run.log"
    t0 = time.time()
    with log_path.open("w", encoding="utf-8", errors="replace") as logf:
        logf.write("CMD: " + " ".join(cmd) + "\n\n")
        logf.flush()
        proc = subprocess.run(cmd, stdout=logf, stderr=subprocess.STDOUT, cwd=str(ROOT))
    elapsed = time.time() - t0
    m = extract_metrics(outdir) or {}
    m.update(
        {
            "fold": fold_name,
            "entry_start": entry_start,
            "entry_end": entry_end,
            "ok": proc.returncode == 0 and bool(m),
            "exit_code": proc.returncode,
            "elapsed_s": elapsed,
            "skipped": False,
        }
    )
    return m


def slice_fold_metrics(
    trades: list[dict[str, Any]],
    folds: list,
    *,
    cash: float,
) -> list[dict[str, Any]]:
    """Report-only Closed slices for train+test (supplement to live fold re-runs)."""
    rows = []
    for f in folds:
        train_start = date.fromisoformat(f.train_start)
        train_end = date.fromisoformat(f.train_end)
        val_start = date.fromisoformat(f.val_start)
        val_end = date.fromisoformat(f.val_end)
        train = [t for t in trades if train_start <= t["opened"] <= train_end]
        test = [t for t in trades if val_start <= t["opened"] <= val_end]
        for role, subset in (("train", train), ("test", test)):
            st = book_stats(subset, cash=cash)
            rows.append(
                {
                    "fold": f.name,
                    "role": role,
                    "start": f.train_start if role == "train" else f.val_start,
                    "end": f.train_end if role == "train" else f.val_end,
                    "n": st["n"],
                    "wr": round(st["wr"], 2),
                    "avg_pnl": round(st["avg_pnl"], 3),
                    "pf": round(st["pf"], 3),
                    "ann_ror": round(st["ann_ror"], 2) if st["ann_ror"] == st["ann_ror"] else None,
                    "max_dd": round(st["max_dd"], 2) if st["max_dd"] == st["max_dd"] else None,
                    "sheet_pnl": round(st["sheet"], 2),
                }
            )
    return rows


def build_compare_rows(live_rep: dict, prod_rep: dict, live_sum: dict, prod_sum: dict) -> list[dict]:
    def g(rep: dict, *keys: str, default: Any = None) -> Any:
        for k in keys:
            if k in rep and rep[k] not in (None, ""):
                return rep[k]
        return default

    specs = [
        ("Universe size", "num", 55, 42),
        ("Total trades", "num", g(live_rep, "Total_Trades"), g(prod_rep, "Total_Trades")),
        ("Wins", "num", g(live_rep, "Wins"), g(prod_rep, "Wins")),
        ("Win %", "pct", g(live_rep, "Pct_Wins"), g(prod_rep, "Pct_Wins")),
        ("Total PnL $", "money", g(live_rep, "Total_PNL"), g(prod_rep, "Total_PNL")),
        ("Sheet PnL $", "money", g(live_rep, "sheet_PnL"), g(prod_rep, "sheet_PnL")),
        ("Avg PnL %", "pct", g(live_rep, "Avg_PNL_Pct"), g(prod_rep, "Avg_PNL_Pct")),
        ("Expectancy $", "money", g(live_rep, "Expectancy"), g(prod_rep, "Expectancy")),
        ("Expectancy %", "pct", g(live_rep, "Expectancy_Pct"), g(prod_rep, "Expectancy_Pct")),
        ("Avg win %", "pct", g(live_rep, "Avg_Win_Pct"), g(prod_rep, "Avg_Win_Pct")),
        ("Avg loss %", "pct", g(live_rep, "Avg_Loss_Pct"), g(prod_rep, "Avg_Loss_Pct")),
        ("Win/Loss ratio (count)", "num", g(live_rep, "Win_Loss_Ratio"), g(prod_rep, "Win_Loss_Ratio")),
        ("Win/Loss ratio $", "num", g(live_rep, "Win_Loss_Ratio_Dollar"), g(prod_rep, "Win_Loss_Ratio_Dollar")),
        ("Profit factor", "num", g(live_rep, "Profit_Factor"), g(prod_rep, "Profit_Factor")),
        ("Ann ROR %", "pct", g(live_rep, "Ann_ROR"), g(prod_rep, "Ann_ROR")),
        ("Max DD %", "pct", g(live_rep, "Max_DD"), g(prod_rep, "Max_DD")),
        ("Profit / capital day", "money", g(live_rep, "Profit_Per_Capital_Day"), g(prod_rep, "Profit_Per_Capital_Day")),
        ("Capital days", "num", g(live_rep, "Capital_Days"), g(prod_rep, "Capital_Days")),
        ("Avg days held", "num", g(live_rep, "Avg_Days_Held"), g(prod_rep, "Avg_Days_Held")),
        ("Avg days underwater", "num", g(live_rep, "Avg_Days_Underwater"), g(prod_rep, "Avg_Days_Underwater")),
        ("Avg positions", "num", g(live_rep, "Avg_Positions"), g(prod_rep, "Avg_Positions")),
        ("Aggressive Total PnL", "money", g(live_rep, "Aggressive_Total_PNL"), g(prod_rep, "Aggressive_Total_PNL")),
        ("Aggressive Max DD %", "pct", g(live_rep, "Aggressive_Max_DD"), g(prod_rep, "Aggressive_Max_DD")),
        ("Pct PnL max symbol", "pct", g(live_rep, "Pct_PNL_Max_Symbol"), g(prod_rep, "Pct_PNL_Max_Symbol")),
        ("Pct PnL max trade", "pct", g(live_rep, "Pct_PNL_Max_Trade"), g(prod_rep, "Pct_PNL_Max_Trade")),
        ("Pct PnL max industry", "pct", g(live_rep, "Pct_PNL_Max_Industry"), g(prod_rep, "Pct_PNL_Max_Industry")),
        ("Pct PnL top10", "pct", g(live_rep, "Pct_PNL_Top10"), g(prod_rep, "Pct_PNL_Top10")),
        ("Pct PnL bottom10", "pct", g(live_rep, "Pct_PNL_Bottom10"), g(prod_rep, "Pct_PNL_Bottom10")),
        ("CES avg", "num", g(live_rep, "CES_AVG"), g(prod_rep, "CES_AVG")),
        ("Mean Paul Score", "num", live_sum.get("mean_paul"), prod_sum.get("mean_paul")),
        ("Mean FIT_SCORE", "num", live_sum.get("mean_fit"), prod_sum.get("mean_fit")),
        ("Mean FIT_SCORE_ROBUST", "num", live_sum.get("mean_fit_robust"), prod_sum.get("mean_fit_robust")),
        ("Mean AVG_PNL_PCT_WO_MAX", "num", live_sum.get("mean_wo_max"), prod_sum.get("mean_wo_max")),
        ("Mean OUTLIER_PCT_OF_WINS", "num", live_sum.get("mean_outlier"), prod_sum.get("mean_outlier")),
        ("Mean AVG_TRADES_PER_YEAR", "num", live_sum.get("mean_tpy"), prod_sum.get("mean_tpy")),
        ("brt_cash (engine)", "money", g(live_rep, "brt_cash"), g(prod_rep, "brt_cash")),
        ("sheet_brt_cash", "money", g(live_rep, "sheet_brt_cash"), g(prod_rep, "sheet_brt_cash")),
    ]
    rows = []
    for label, kind, a, b in specs:
        d = delta(a, b)
        rows.append({"metric": label, "kind": kind, "live55": a, "prod42": b, "delta": d})
    return rows


def exit_mix(trades: list[dict[str, Any]]) -> list[tuple[str, int, float]]:
    c = Counter(str(t.get("exit") or "?").strip() or "?" for t in trades)
    n = sum(c.values()) or 1
    return [(k, v, 100.0 * v / n) for k, v in sorted(c.items(), key=lambda x: -x[1])]


def write_html(
    *,
    live_rep: dict,
    prod_rep: dict,
    compare_rows: list[dict],
    live_is: dict,
    live_oos: dict,
    prod_is: dict,
    prod_oos: dict,
    wf_live_rows: list[dict],
    wf_slice_rows: list[dict],
    exit_live: list[tuple],
    exit_prod: list[tuple],
    overlap: dict,
) -> Path:
    def cell(kind: str, v: Any) -> str:
        if kind == "money":
            return escape(format_money(v))
        if kind == "pct":
            return escape(fmt_pct(v, 2))
        return escape(fmt_num(v, 2) if parse_number(v) is not None else ("—" if v in (None, "") else v))

    def dcell(kind: str, v: Any) -> str:
        if v is None:
            return "—"
        if kind == "money":
            return escape(format_money_delta(v))
        sign = "+" if v >= 0 else ""
        if kind == "pct":
            return escape(f"{sign}{v:.2f}pp")
        return escape(f"{sign}{v:.2f}")

    book_trs = []
    for r in compare_rows:
        book_trs.append(
            "<tr>"
            f"<td>{escape(r['metric'])}</td>"
            f"<td>{cell(r['kind'], r['live55'])}</td>"
            f"<td>{cell(r['kind'], r['prod42'])}</td>"
            f"<td>{dcell(r['kind'], r['delta'])}</td>"
            "</tr>"
        )

    def split_trs(label: str, st: dict) -> str:
        return (
            "<tr>"
            f"<td>{escape(label)}</td>"
            f"<td>{st['n']}</td>"
            f"<td>{fmt_pct(st['wr'], 1)}</td>"
            f"<td>{fmt_num(st['avg_pnl'], 2)}</td>"
            f"<td>{fmt_num(st['pf'], 2)}</td>"
            f"<td>{fmt_num(st['ann_ror'], 2)}</td>"
            f"<td>{fmt_num(st['max_dd'], 2)}</td>"
            f"<td>{format_money(st['sheet'])}</td>"
            "</tr>"
        )

    wf_trs = []
    for r in wf_live_rows:
        wf_trs.append(
            "<tr>"
            f"<td>{escape(r.get('fold',''))}</td>"
            f"<td>{escape(r.get('entry_start',''))}</td>"
            f"<td>{escape(r.get('entry_end',''))}</td>"
            f"<td>{r.get('n',0)}</td>"
            f"<td>{fmt_pct(r.get('wr'), 1)}</td>"
            f"<td>{fmt_num(r.get('avg_pnl'), 2)}</td>"
            f"<td>{fmt_num(r.get('pf'), 2)}</td>"
            f"<td>{fmt_num(r.get('ann_ror'), 2)}</td>"
            f"<td>{fmt_num(r.get('max_dd'), 2)}</td>"
            f"<td>{format_money(r.get('sheet_pnl'))}</td>"
            f"<td>{'Y' if r.get('ok') else 'N'}</td>"
            "</tr>"
        )

    slice_trs = []
    for r in wf_slice_rows:
        if r.get("role") != "test":
            continue
        slice_trs.append(
            "<tr>"
            f"<td>{escape(r['fold'])}</td>"
            f"<td>{escape(r['start'])}</td>"
            f"<td>{escape(r['end'])}</td>"
            f"<td>{r['n']}</td>"
            f"<td>{fmt_pct(r['wr'], 1)}</td>"
            f"<td>{fmt_num(r['avg_pnl'], 2)}</td>"
            f"<td>{fmt_num(r['pf'], 2)}</td>"
            f"<td>{fmt_num(r['ann_ror'], 2)}</td>"
            f"<td>{fmt_num(r['max_dd'], 2)}</td>"
            f"<td>{format_money(r['sheet_pnl'])}</td>"
            "</tr>"
        )

    exit_trs = []
    keys = sorted({e[0] for e in exit_live} | {e[0] for e in exit_prod})
    live_m = {k: (n, p) for k, n, p in exit_live}
    prod_m = {k: (n, p) for k, n, p in exit_prod}
    for k in keys:
        ln, lp = live_m.get(k, (0, 0.0))
        pn, pp = prod_m.get(k, (0, 0.0))
        exit_trs.append(
            f"<tr><td>{escape(k)}</td><td>{ln}</td><td>{fmt_pct(lp,1)}</td>"
            f"<td>{pn}</td><td>{fmt_pct(pp,1)}</td></tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>BRT IS Paul8+FIT6 live 55 vs prod 42 + walk-forward</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 24px; color: #0f172a; background: #f8fafc; }}
h1,h2 {{ margin: 0.6em 0 0.35em; }}
.small {{ color: #64748b; font-size: 0.92em; }}
.banner {{ background: #fef3c7; border: 1px solid #f59e0b; padding: 12px 14px; border-radius: 8px; margin: 12px 0 18px; }}
table.sortable {{ border-collapse: collapse; width: 100%; background: #fff; margin: 10px 0 22px; }}
th, td {{ border: 1px solid #e2e8f0; padding: 6px 8px; text-align: left; font-size: 0.92em; }}
th {{ background: #f1f5f9; }}
tr:nth-child(even) td {{ background: #f8fafc; }}
code {{ background: #e2e8f0; padding: 1px 4px; border-radius: 3px; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>BRT research sleeve — live 55 vs production 42 + walk-forward</h1>
<p class="small">Stamp folder: <code>{escape(str(OUT.relative_to(ROOT)))}</code> · Click column headers to sort</p>
<div class="banner">
<strong>HOLD / research sleeve only.</strong> Not gold. Not DailyRun. Does not replace
<code>drive/universes/BRT_universe.csv</code>. Prior OOS hold-up context:
<code>{escape(PRIOR_HOLD)}</code>. PO chart review prepared — <em>no PO sign-off claimed</em>.
</div>

<h2>Identity</h2>
<ul>
<li>Live 55 stamp: <code>BRT_*_{LIVE_STAMP}.*</code> under this folder (isolated <code>-o</code>)</li>
<li>Freeze CSV: <code>{escape(str(UNIV_55.relative_to(ROOT)))}</code> (55 names, honest IS Paul≥8 ∧ FIT≥6 ∧ robust FIT≥6 cut)</li>
<li>Production 42 Closed (reuse): <code>drive/BRT_Closed_{PROD42_STAMP}.csv</code></li>
<li>Knobs: current <code>run_brt.bat</code> (not mutated)</li>
<li>Overlap vs 42: shared={overlap['shared']}, only55={overlap['only55']}, only42={overlap['only42']}</li>
</ul>

<h2>Book compare — live 55 vs production 42</h2>
<p class="small">Canonical metric set. Δ = live55 − prod42. Concurrent books use stamp cash; not apples-to-apples capacity (brt_cash differs).</p>
<table class="sortable">
<thead><tr>
{sortable_th("Metric", "text")}
{sortable_th("Live 55", "num")}
{sortable_th("Prod 42", "num")}
{sortable_th("Δ", "num")}
</tr></thead>
<tbody>
{''.join(book_trs)}
</tbody>
</table>

<h2>IS / OOS overlay (Closed entry split @ 2024-01-01)</h2>
<p class="small">OOS report-only. Sheet $={format_money(SHEET)}; Max DD seed ${DEFAULT_INITIAL_ACCOUNT:,.0f}.</p>
<table class="sortable">
<thead><tr>
{sortable_th("Book", "text")}
{sortable_th("N", "num")}
{sortable_th("WR", "num")}
{sortable_th("Avg PnL%", "num")}
{sortable_th("PF", "num")}
{sortable_th("Ann ROR", "num")}
{sortable_th("Max DD", "num")}
{sortable_th("Sheet PnL", "num")}
</tr></thead>
<tbody>
{split_trs("Live55 IS", live_is)}
{split_trs("Live55 OOS", live_oos)}
{split_trs("Prod42 IS", prod_is)}
{split_trs("Prod42 OOS", prod_oos)}
</tbody>
</table>

<h2>Walk-forward — live fold re-runs (frozen knobs)</h2>
<p class="small">Rolling train 3y → test 1y (<code>stock_analysis/walkforward.py</code>).
Each test window re-run via <code>run_brt.bat</code> with <code>entry_start_date</code>/<code>entry_end_date</code>.
Train folds documented only (no param retune). Metrics from each fold Report.</p>
<table class="sortable">
<thead><tr>
{sortable_th("Fold", "text")}
{sortable_th("Test start", "date")}
{sortable_th("Test end", "date")}
{sortable_th("N", "num")}
{sortable_th("WR", "num")}
{sortable_th("Avg PnL%", "num")}
{sortable_th("PF", "num")}
{sortable_th("Ann ROR", "num")}
{sortable_th("Max DD", "num")}
{sortable_th("Sheet PnL", "num")}
{sortable_th("OK", "text")}
</tr></thead>
<tbody>
{''.join(wf_trs)}
</tbody>
</table>

<h2>Walk-forward — Closed slice (full live path, test windows)</h2>
<p class="small">Same fold dates; trades sliced from full-history live Closed (concurrent path carries across folds). Supplement to fold re-runs.</p>
<table class="sortable">
<thead><tr>
{sortable_th("Fold", "text")}
{sortable_th("Test start", "date")}
{sortable_th("Test end", "date")}
{sortable_th("N", "num")}
{sortable_th("WR", "num")}
{sortable_th("Avg PnL%", "num")}
{sortable_th("PF", "num")}
{sortable_th("Ann ROR", "num")}
{sortable_th("Max DD", "num")}
{sortable_th("Sheet PnL", "num")}
</tr></thead>
<tbody>
{''.join(slice_trs)}
</tbody>
</table>

<h2>Exit mix</h2>
<table class="sortable">
<thead><tr>
{sortable_th("EXIT_TYPE", "text")}
{sortable_th("Live55 N", "num")}
{sortable_th("Live55 %", "num")}
{sortable_th("Prod42 N", "num")}
{sortable_th("Prod42 %", "num")}
</tr></thead>
<tbody>
{''.join(exit_trs)}
</tbody>
</table>

<p class="small">Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} · research artifact</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    path = OUT / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_baseline(
    *,
    live_rep: dict,
    prod_rep: dict,
    live_is: dict,
    live_oos: dict,
    prod_is: dict,
    prod_oos: dict,
    wf_live_rows: list[dict],
    overlap: dict,
    verdict: str,
) -> Path:
    test_rows = [r for r in wf_live_rows if int(r.get("n") or 0) > 0]
    median_wr = sorted(float(r["wr"]) for r in test_rows)[len(test_rows) // 2] if test_rows else float("nan")
    median_avg = sorted(float(r["avg_pnl"]) for r in test_rows)[len(test_rows) // 2] if test_rows else float("nan")
    median_pf = sorted(float(r["pf"]) for r in test_rows)[len(test_rows) // 2] if test_rows else float("nan")
    oos_soft = live_oos["wr"] < live_is["wr"] - 3 or live_oos["avg_pnl"] < live_is["avg_pnl"] * 0.7
    folds_ok = sum(1 for r in wf_live_rows if r.get("ok") and int(r.get("n") or 0) > 0)

    lines = [
        "# BASELINE — BRT IS Paul8+FIT6 live run + walk-forward (20260820)",
        "",
        "**Research sleeve only. Not gold. Not DailyRun. Do not replace `drive/universes/BRT_universe.csv`.**",
        "",
        "## Freeze",
        "",
        f"- Universe CSV: `{UNIV_55.as_posix()}` (55 names)",
        f"- Selection prior: `{PRIOR_HOLD}` (OOS HOLD; IS gate caveats on selection stamp)",
        f"- Live stamp (isolated `-o`): **`{LIVE_STAMP}`** under `{OUT.as_posix()}`",
        f"- Production 42 Closed (reuse, not overwritten): **`{PROD42_STAMP}`** @ `drive/BRT_Closed_{PROD42_STAMP}.csv`",
        "- Knobs: current `run_brt.bat` (unchanged)",
        "- Exit identity: production BRT stop/target/sheet path",
        "",
        "## Overlap vs production 42",
        "",
        f"- Shared: **{overlap['shared']}** ({', '.join(overlap['shared_syms']) or '—'})",
        f"- Only in 55: **{overlap['only55']}**",
        f"- Only in 42: **{overlap['only42']}**",
        "",
        "## Live full-book (Report)",
        "",
        "| Book | N | WR% | Avg PnL% | PF | Ann ROR | Max DD | Sheet PnL | Total PnL |",
        "|------|---|-----|----------|----|---------|--------|-----------|-----------|",
        (
            f"| Live 55 `{LIVE_STAMP}` | {int(_f(live_rep.get('Total_Trades')))} | "
            f"{_f(live_rep.get('Pct_Wins')):.1f} | {_f(live_rep.get('Avg_PNL_Pct')):.2f} | "
            f"{_f(live_rep.get('Profit_Factor')):.2f} | {_f(live_rep.get('Ann_ROR')):.2f} | "
            f"{_f(live_rep.get('Max_DD')):.2f} | {format_money(live_rep.get('sheet_PnL'))} | "
            f"{format_money(live_rep.get('Total_PNL'))} |"
        ),
        (
            f"| Prod 42 `{PROD42_STAMP}` | {int(_f(prod_rep.get('Total_Trades')))} | "
            f"{_f(prod_rep.get('Pct_Wins')):.1f} | {_f(prod_rep.get('Avg_PNL_Pct')):.2f} | "
            f"{_f(prod_rep.get('Profit_Factor')):.2f} | {_f(prod_rep.get('Ann_ROR')):.2f} | "
            f"{_f(prod_rep.get('Max_DD')):.2f} | {format_money(prod_rep.get('sheet_PnL'))} | "
            f"{format_money(prod_rep.get('Total_PNL'))} |"
        ),
        "",
        "Note: `brt_cash` differs (live55 vs prod42 sizing). Prefer quality metrics + sheet PnL; do not judge on max trade.",
        "",
        "## IS / OOS (entry < / ≥ 2024-01-01) on Closed overlay",
        "",
        "| Book | Split | N | WR | Avg PnL% | PF | Ann ROR | Max DD | Sheet PnL |",
        "|------|-------|---|----|----------|----|---------|--------|-----------|",
        f"| Live55 | IS | {live_is['n']} | {live_is['wr']:.1f} | {live_is['avg_pnl']:.2f} | {live_is['pf']:.2f} | {live_is['ann_ror']:.2f} | {live_is['max_dd']:.2f} | {format_money(live_is['sheet'])} |",
        f"| Live55 | OOS | {live_oos['n']} | {live_oos['wr']:.1f} | {live_oos['avg_pnl']:.2f} | {live_oos['pf']:.2f} | {live_oos['ann_ror']:.2f} | {live_oos['max_dd']:.2f} | {format_money(live_oos['sheet'])} |",
        f"| Prod42 | IS | {prod_is['n']} | {prod_is['wr']:.1f} | {prod_is['avg_pnl']:.2f} | {prod_is['pf']:.2f} | {prod_is['ann_ror']:.2f} | {prod_is['max_dd']:.2f} | {format_money(prod_is['sheet'])} |",
        f"| Prod42 | OOS | {prod_oos['n']} | {prod_oos['wr']:.1f} | {prod_oos['avg_pnl']:.2f} | {prod_oos['pf']:.2f} | {prod_oos['ann_ror']:.2f} | {prod_oos['max_dd']:.2f} | {format_money(prod_oos['sheet'])} |",
        "",
        f"OOS softens vs IS on live55: **{'yes' if oos_soft else 'no / mixed'}** — OOS remains report-only; do not retune.",
        "",
        "## Walk-forward",
        "",
        "- Pattern: `build_rolling_folds(train_years=3, test_years=1, step_years=1)`",
        "- Frozen knobs: no train-fold optimization",
        "- Test folds: true re-runs under `wf_folds/<fold>/` with entry windows",
        f"- Folds OK: {folds_ok}/{len(wf_live_rows)}",
        f"- Median test WR / AvgPnL% / PF: {median_wr:.1f} / {median_avg:.2f} / {median_pf:.2f}",
        "- Detail: `walkforward_live.csv`, `walkforward_closed_slice.csv`",
        "",
        "## Selection honesty",
        "",
        "55-name list is an in-sample DualPaul-style Summary cut (prior stamp). Live+WF here is the next evidence step; still not a house pin.",
        "",
        f"## Verdict: **{verdict}**",
        "",
        "House BRT remains the 42-name production whitelist. PO may review charts; **PO sign-off is not recorded here**.",
        "",
        "## Artifacts",
        "",
        f"- Compare HTML: `{OUT / 'compare.html'}`",
        f"- PO note: `{OUT / 'PO_REVIEW.md'}`",
        f"- Live Closed/charts: `{OUT / f'BRT_Closed_{LIVE_STAMP}.csv'}`, zones `BRT_ZONES_*_{LIVE_STAMP}.csv`",
        "",
    ]
    path = OUT / "BASELINE.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_po_review(*, live_is: dict, live_oos: dict, verdict: str) -> Path:
    lines = [
        "# PO review pack — BRT IS Paul8+FIT6 live + WF (research sleeve)",
        "",
        "**Status: ready for PO chart review. PO sign-off: NOT claimed / NOT recorded.**",
        "",
        "## What this is",
        "",
        "- Research sleeve: 55 names from honest IS Paul≥8 ∧ FIT≥6 ∧ robust FIT≥6 cut",
        "- Live concurrent book + walk-forward under frozen `run_brt.bat` knobs",
        "- Isolated output — production LatestRun / 42-name house pin **not** overwritten",
        "",
        "## Stamp IDs",
        "",
        f"| Role | Stamp | Path |",
        f"|------|-------|------|",
        f"| Live 55 (candidate sleeve) | `{LIVE_STAMP}` | `{OUT.as_posix()}/BRT_*_{LIVE_STAMP}.*` |",
        f"| Production 42 (control) | `{PROD42_STAMP}` | `drive/BRT_Closed_{PROD42_STAMP}.csv` (+ Report/Summary/zones in `drive/`) |",
        f"| Prior OOS HOLD context | selection `260820002407` | `{PRIOR_HOLD}` |",
        "",
        "## Where Closed / charts live",
        "",
        f"- Closed: `{OUT / f'BRT_Closed_{LIVE_STAMP}.csv'}`",
        f"- Open / Watchlist / Summary / Report / EquityCurve: same folder + stamp `{LIVE_STAMP}`",
        f"- Per-symbol zones: `{OUT.as_posix()}/BRT_ZONES_<SYM>_{LIVE_STAMP}.csv`",
        f"- Zone entries: `{OUT.as_posix()}/BRT_ZONES_ENTRIES_<SYM>_{LIVE_STAMP}.csv`",
        f"- ImproveHints: `{OUT / f'BRT_ImproveHints_{LIVE_STAMP}.html'}`",
        f"- Compare (sortable): `{OUT / 'compare.html'}`",
        f"- Walk-forward fold runs: `{OUT / 'wf_folds'}/`",
        "",
        "## What to review (suggested)",
        "",
        "1. Setup identity vs house BRT on overlapping names (AMAT, AMD, NFLX, NVDA) — same break/retest language?",
        "2. New names only in the 55 — do charts still look like BRT zones (not a different pattern)?",
        "3. OOS / late WF folds — quality hold-up vs IS (WR / Avg PnL% / PF / DD), not just trade count",
        "4. Concentration / exit mix vs 42 (compare.html exit section)",
        "",
        "## Headline numbers (context only)",
        "",
        f"- Live55 IS: N={live_is['n']} WR={live_is['wr']:.1f}% AvgPnL={live_is['avg_pnl']:.2f}% PF={live_is['pf']:.2f}",
        f"- Live55 OOS: N={live_oos['n']} WR={live_oos['wr']:.1f}% AvgPnL={live_oos['avg_pnl']:.2f}% PF={live_oos['pf']:.2f}",
        f"- Research verdict (pre-PO): **{verdict}**",
        "",
        "## Explicit non-claims",
        "",
        "- No PO passed / signed-off language",
        "- Not gold; not DailyRun-wired",
        "- Do not overwrite `BRT_universe.csv` from this stamp",
        "",
    ]
    path = OUT / "PO_REVIEW.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def decide_verdict(live_is: dict, live_oos: dict, prod_oos: dict, wf_rows: list[dict]) -> str:
    """Quality-first; OOS soften → HOLD. Do not invent LEAN KEEP without clear hold-up."""
    oos_ok_vs_self = (
        live_oos["n"] >= 50
        and live_oos["pf"] >= 1.2
        and live_oos["avg_pnl"] > 0
    )
    oos_vs_42 = (
        live_oos["avg_pnl"] >= prod_oos["avg_pnl"] * 0.85
        and live_oos["wr"] >= prod_oos["wr"] - 5
    )
    tests = [r for r in wf_rows if r.get("n") and int(r.get("n") or 0) > 0]
    if tests:
        pos_pf = sum(1 for r in tests if float(r.get("pf") or 0) >= 1.2) / len(tests)
        pos_pnl = sum(1 for r in tests if float(r.get("avg_pnl") or 0) > 0) / len(tests)
    else:
        pos_pf = pos_pnl = 0.0
    oos_soft = live_oos["wr"] < live_is["wr"] - 5 or live_oos["avg_pnl"] < live_is["avg_pnl"] * 0.65
    # Prior stamp was HOLD; require clear OOS+WF hold-up vs 42 for LEAN — else HOLD.
    if (
        oos_ok_vs_self
        and oos_vs_42
        and not oos_soft
        and pos_pf >= 0.7
        and pos_pnl >= 0.7
        and live_oos["wr"] >= live_is["wr"] - 8
    ):
        return "LEAN KEEP as research sleeve (still not house / not gold) — pending PO chart review"
    if oos_ok_vs_self and pos_pnl >= 0.55:
        return "HOLD as research sleeve (OOS softens vs IS / trails 42 quality; WF mixed; not gold; not DailyRun)"
    return "HOLD as research sleeve (OOS/WF softens or thin — do not promote)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-wf-runs", action="store_true", help="Only stamp from existing live + slice WF")
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--workers", type=int, default=24)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    live_closed_path = OUT / f"BRT_Closed_{LIVE_STAMP}.csv"
    live_report_path = OUT / f"BRT_Report_{LIVE_STAMP}.csv"
    live_summary_path = OUT / f"BRT_Summary_{LIVE_STAMP}.csv"
    if not live_closed_path.is_file() or not live_report_path.is_file():
        print(f"ERROR: missing live stamp under {OUT}", file=sys.stderr)
        return 1
    if not PROD42_CLOSED.is_file():
        print(f"ERROR: missing prod42 Closed {PROD42_CLOSED}", file=sys.stderr)
        return 1

    syms55 = load_universe(UNIV_55)
    syms42 = load_universe(UNIV_42)
    s55, s42 = set(syms55), set(syms42)
    overlap = {
        "shared": len(s55 & s42),
        "only55": len(s55 - s42),
        "only42": len(s42 - s55),
        "shared_syms": sorted(s55 & s42),
    }

    live_trades = load_closed(live_closed_path)
    prod_trades = load_closed(PROD42_CLOSED)
    live_rep = load_report(live_report_path)
    prod_rep = load_report(PROD42_REPORT)
    live_cash = cash_from_report(live_rep)
    prod_cash = cash_from_report(prod_rep)
    live_sum = summary_agg(live_summary_path)
    prod_sum = summary_agg(PROD42_SUMMARY)

    live_is_t, live_oos_t = split_is_oos(live_trades)
    prod_is_t, prod_oos_t = split_is_oos(prod_trades)
    live_is = book_stats(live_is_t, cash=SHEET)
    live_oos = book_stats(live_oos_t, cash=SHEET)
    prod_is = book_stats(prod_is_t, cash=SHEET)
    prod_oos = book_stats(prod_oos_t, cash=SHEET)

    # Folds from live Closed span
    opened = pd.to_datetime([t["opened"].isoformat() for t in live_trades])
    folds = build_rolling_folds(
        opened.min(),
        opened.max(),
        train_years=3,
        test_years=1,
        step_years=1,
    )
    (OUT / "wf_folds").mkdir(parents=True, exist_ok=True)

    wf_live_rows: list[dict[str, Any]] = []
    if not args.skip_wf_runs:
        print(f"[wf] {len(folds)} folds, jobs={args.jobs}", flush=True)
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
            futs = {
                ex.submit(
                    run_fold,
                    f.name,
                    f.val_start,
                    f.val_end,
                    workers=args.workers,
                ): f
                for f in folds
            }
            for fut in as_completed(futs):
                f = futs[fut]
                r = fut.result()
                wf_live_rows.append(r)
                print(
                    f"  [{r.get('fold')}] ok={r.get('ok')} n={r.get('n')} "
                    f"wr={r.get('wr')} avg={r.get('avg_pnl')} pf={r.get('pf')} "
                    f"skipped={r.get('skipped')}",
                    flush=True,
                )
        wf_live_rows.sort(key=lambda r: r.get("entry_start") or r.get("fold") or "")
    else:
        for f in folds:
            outdir = OUT / "wf_folds" / f.name
            m = extract_metrics(outdir)
            if m is None:
                m = {
                    "fold": f.name,
                    "entry_start": f.val_start,
                    "entry_end": f.val_end,
                    "ok": False,
                    "n": 0,
                    "wr": 0.0,
                    "avg_pnl": 0.0,
                    "pf": 0.0,
                    "ann_ror": 0.0,
                    "max_dd": 0.0,
                    "sheet_pnl": 0.0,
                }
            else:
                m["ok"] = True
                m.setdefault("fold", f.name)
                m.setdefault("entry_start", f.val_start)
                m.setdefault("entry_end", f.val_end)
            wf_live_rows.append(m)

    # Closed-slice supplement
    wf_slice_rows = slice_fold_metrics(live_trades, folds, cash=SHEET)

    # Persist CSVs
    wf_csv = OUT / "walkforward_live.csv"
    if wf_live_rows:
        keys = [
            "fold",
            "entry_start",
            "entry_end",
            "n",
            "wr",
            "avg_pnl",
            "pf",
            "ann_ror",
            "max_dd",
            "sheet_pnl",
            "total_pnl",
            "ok",
            "skipped",
            "elapsed_s",
        ]
        with wf_csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            for r in wf_live_rows:
                w.writerow(r)

    slice_csv = OUT / "walkforward_closed_slice.csv"
    with slice_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(wf_slice_rows[0].keys()) if wf_slice_rows else [])
        if wf_slice_rows:
            w.writeheader()
            w.writerows(wf_slice_rows)

    compare_rows = build_compare_rows(live_rep, prod_rep, live_sum, prod_sum)
    exit_live = exit_mix(live_trades)
    exit_prod = exit_mix(prod_trades)
    verdict = decide_verdict(live_is, live_oos, prod_oos, wf_live_rows)

    html_path = write_html(
        live_rep=live_rep,
        prod_rep=prod_rep,
        compare_rows=compare_rows,
        live_is=live_is,
        live_oos=live_oos,
        prod_is=prod_is,
        prod_oos=prod_oos,
        wf_live_rows=wf_live_rows,
        wf_slice_rows=wf_slice_rows,
        exit_live=exit_live,
        exit_prod=exit_prod,
        overlap=overlap,
    )
    base_path = write_baseline(
        live_rep=live_rep,
        prod_rep=prod_rep,
        live_is=live_is,
        live_oos=live_oos,
        prod_is=prod_is,
        prod_oos=prod_oos,
        wf_live_rows=wf_live_rows,
        overlap=overlap,
        verdict=verdict,
    )
    po_path = write_po_review(live_is=live_is, live_oos=live_oos, verdict=verdict)

    print(f"[done] html={html_path}")
    print(f"[done] baseline={base_path}")
    print(f"[done] po={po_path}")
    print(f"[done] verdict={verdict}")
    print(
        f"[done] live55 N={live_rep.get('Total_Trades')} WR={live_rep.get('Pct_Wins')} "
        f"Avg={live_rep.get('Avg_PNL_Pct')} PF={live_rep.get('Profit_Factor')} "
        f"Ann={live_rep.get('Ann_ROR')} DD={live_rep.get('Max_DD')}"
    )
    print(
        f"[done] prod42 N={prod_rep.get('Total_Trades')} WR={prod_rep.get('Pct_Wins')} "
        f"Avg={prod_rep.get('Avg_PNL_Pct')} PF={prod_rep.get('Profit_Factor')} "
        f"Ann={prod_rep.get('Ann_ROR')} DD={prod_rep.get('Max_DD')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
