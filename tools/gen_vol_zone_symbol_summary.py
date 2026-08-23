#!/usr/bin/env python3
"""Build house-style VZ Symbol Summary (Paul score) from full-univ signals.

Research only — not gold / not DailyRun. Re-aggregates ``signals_rw63.csv``
from ``vol_zone_v2_rw63_fulluniv_*`` (no full-universe re-run).

Paul Score uses ``stock_analysis.rocket_post_analysis.apply_paul_scores_to_summary_rows``
exactly (0–8 peer thresholds vs this Summary's **mean** only).

Synthetic sheet dollars: each trade notional = $45,000 (house SHEET_INVESTMENT);
``TOTAL_PNL`` / ``SHEET_PNL`` = sum(pnl_pct/100 * 45000). VZ has no engine cash sizing.
``AVG_DAYS_HELD`` = mean ``bars_held`` (trading-bar proxy; documented in HTML).

Usage:
  python tools/gen_vol_zone_symbol_summary.py
  python tools/gen_vol_zone_symbol_summary.py --stamp-dir drive/paul_experiments/vol_zone_v2_rw63_fulluniv_20260810
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from stock_analysis.rocket_post_analysis import (  # noqa: E402
    apply_paul_scores_to_summary_rows,
    assess_symbol_fit,
)

DEFAULT_STAMP = "vol_zone_v2_rw63_fulluniv_20260810"
DEFAULT_STAMP_DIR = REPO / "drive" / "paul_experiments" / DEFAULT_STAMP
SHEET_NOTIONAL = 45_000.0  # house SHEET_INVESTMENT
OOS_SPLIT = pd.Timestamp("2024-01-01")
DAYS_PER_YEAR = 365.25

# Research-suggested gold-set cutoffs (NOT adopted until user confirms).
# Aligns with docs/system_setup_process.html promotion defaults + Paul peer score.
PROPOSED_MIN_TRADES = 20
PROPOSED_MIN_PAUL = 5
PROPOSED_MIN_WR = 50.0
PROPOSED_MIN_SHEET = 10_000.0
PROPOSED_MIN_TPY = 1.0
PROPOSED_MIN_EXPECTANCY = 2.5
PROPOSED_MIN_WO_MAX = 0.20
PROPOSED_MIN_OOS_N = 5
PROPOSED_MIN_PAUL_OOS = 4

SORTABLE_TH_CSS = """
th.sortable-th{cursor:pointer;user-select:none;white-space:nowrap}
th.sortable-th:hover{background:#e2e8f0}
th.sortable-th .sort-ind::after{content:" \\2195";opacity:.35;font-size:.85em}
th.sortable-th.sort-asc .sort-ind::after{content:" \\2191";opacity:.9}
th.sortable-th.sort-desc .sort-ind::after{content:" \\2193";opacity:.9}
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
  function bind(table) {
    var ths = table.querySelectorAll("thead th.sortable-th");
    ths.forEach(function (th, idx) {
      th.addEventListener("click", function () {
        var type = th.getAttribute("data-sort") || "text";
        var asc = !th.classList.contains("sort-asc");
        ths.forEach(function (x) { x.classList.remove("sort-asc", "sort-desc"); x.setAttribute("aria-sort", "none"); });
        th.classList.add(asc ? "sort-asc" : "sort-desc");
        th.setAttribute("aria-sort", asc ? "ascending" : "descending");
        sortTable(table, idx, type, asc ? 1 : -1);
      });
      th.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); th.click(); }
      });
    });
  }
  document.querySelectorAll("table.sortable").forEach(bind);
})();
</script>
"""


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{html_mod.escape(sort_type)}" '
        f'tabindex="0" role="columnheader" aria-sort="none">'
        f"{html_mod.escape(label)}<span class=\"sort-ind\"></span></th>"
    )


def _f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _years(start: Optional[pd.Timestamp], end: Optional[pd.Timestamp]) -> float:
    if start is None or end is None or pd.isna(start) or pd.isna(end):
        return 0.0
    if end < start:
        return 0.0
    return max((end - start).days / DAYS_PER_YEAR, 1e-9)


def _slice_metrics(g: pd.DataFrame) -> dict[str, float]:
    n = len(g)
    if n == 0:
        return {
            "n": 0,
            "wins": 0,
            "losses": 0,
            "bes": 0,
            "pct_wins": 0.0,
            "avg_pnl": 0.0,
            "avg_r": 0.0,
            "total_pnl": 0.0,
            "avg_bars": 0.0,
            "pf": 0.0,
        }
    pnls = g["pnl_pct"].astype(float)
    wins = int((pnls > 0).sum())
    losses = int((pnls < 0).sum())
    bes = int((pnls == 0).sum())
    win_sum = float(pnls[pnls > 0].sum()) if wins else 0.0
    loss_sum = float(pnls[pnls < 0].sum()) if losses else 0.0
    pf = (win_sum / abs(loss_sum)) if loss_sum < 0 else (999.0 if win_sum > 0 else 0.0)
    return {
        "n": n,
        "wins": wins,
        "losses": losses,
        "bes": bes,
        "pct_wins": 100.0 * wins / n,
        "avg_pnl": float(pnls.mean()),
        "avg_r": float(g["r_mult"].astype(float).mean()),
        "total_pnl": float((pnls / 100.0 * SHEET_NOTIONAL).sum()),
        "avg_bars": float(g["bars_held"].astype(float).mean()),
        "pf": pf,
    }


def build_summary_rows(
    signals: pd.DataFrame,
    per_symbol: pd.DataFrame,
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    """Return (summary rows, fieldnames, paul diagnostics)."""
    meta = {}
    if not per_symbol.empty:
        for _, r in per_symbol.iterrows():
            sym = str(r.get("symbol", "")).strip().upper()
            if sym:
                meta[sym] = r

    by_sym: dict[str, pd.DataFrame] = {
        str(sym).upper(): g.copy() for sym, g in signals.groupby("symbol", sort=False)
    }

    # Include ok symbols with zero trades from per_symbol coverage.
    all_syms = sorted(set(meta.keys()) | set(by_sym.keys()))
    rows: list[dict[str, Any]] = []
    closed_by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for sym in all_syms:
        g = by_sym.get(sym, pd.DataFrame())
        m = meta.get(sym)
        status = str(m.get("status", "ok")) if m is not None else ("ok" if len(g) else "missing")
        note = str(m.get("note", "") or "") if m is not None else ""
        date_start = None
        date_end = None
        if m is not None:
            try:
                date_start = pd.Timestamp(m.get("date_start"))
            except Exception:
                date_start = None
            try:
                date_end = pd.Timestamp(m.get("date_end"))
            except Exception:
                date_end = None
        if len(g) and (date_start is None or pd.isna(date_start)):
            date_start = pd.Timestamp(g["entry_date"].min())
        if len(g) and (date_end is None or pd.isna(date_end)):
            date_end = pd.Timestamp(g["entry_date"].max())

        full = _slice_metrics(g)
        if len(g):
            ed = pd.to_datetime(g["entry_date"])
            is_g = g[ed < OOS_SPLIT]
            oos_g = g[ed >= OOS_SPLIT]
        else:
            is_g = g
            oos_g = g
        is_m = _slice_metrics(is_g)
        oos_m = _slice_metrics(oos_g)

        years = _years(date_start, date_end)
        avg_tpy = (full["n"] / years) if years > 0 and full["n"] else 0.0

        closed_rows: list[dict[str, Any]] = []
        if len(g):
            for _, t in g.iterrows():
                closed_rows.append(
                    {
                        "SYMBOL": sym,
                        "PNL_PCT": float(t["pnl_pct"]),
                        "DATE_CLOSED": str(pd.Timestamp(t["entry_date"]).date()),
                    }
                )
        closed_by_sym[sym] = closed_rows

        fr = assess_symbol_fit(
            trades=full["n"],
            wins=full["wins"],
            losses=full["losses"],
            pct_wins=full["pct_wins"],
            avg_pnl_pct=full["avg_pnl"],
            sheet_pnl=full["total_pnl"],
            avg_tpy=avg_tpy,
            closed_rows=closed_rows,
        )

        row: dict[str, Any] = {
            "SYMBOL": sym,
            "STATUS": status,
            "NOTE": note,
            "TRADES": str(full["n"]),
            "WINS": str(full["wins"]),
            "LOSSES": str(full["losses"]),
            "BEs": str(full["bes"]),
            "PCT_WINS": f"{full['pct_wins']:.1f}%" if full["n"] else "",
            "TOTAL_PNL": f"{full['total_pnl']:.2f}" if full["n"] else "",
            "SHEET_PNL": f"{full['total_pnl']:.2f}" if full["n"] else "",
            "AVG_PNL_PCT": f"{full['avg_pnl']:.2f}" if full["n"] else "",
            "AVG_R": f"{full['avg_r']:.3f}" if full["n"] else "",
            "PROFIT_FACTOR": f"{full['pf']:.2f}" if full["n"] else "",
            "FIRST_DATA_DATE": str(date_start.date()) if date_start is not None and not pd.isna(date_start) else "",
            "LAST_DATA_DATE": str(date_end.date()) if date_end is not None and not pd.isna(date_end) else "",
            "AVG_TRADES_PER_YEAR": f"{avg_tpy:.2f}" if full["n"] and years > 0 else "",
            "AVG_DAYS_HELD": f"{full['avg_bars']:.1f}" if full["n"] else "",
            "IS_TRADES": str(is_m["n"]),
            "IS_PCT_WINS": f"{is_m['pct_wins']:.1f}%" if is_m["n"] else "",
            "IS_AVG_PNL_PCT": f"{is_m['avg_pnl']:.2f}" if is_m["n"] else "",
            "IS_AVG_R": f"{is_m['avg_r']:.3f}" if is_m["n"] else "",
            "IS_SHEET_PNL": f"{is_m['total_pnl']:.2f}" if is_m["n"] else "",
            "OOS_TRADES": str(oos_m["n"]),
            "OOS_PCT_WINS": f"{oos_m['pct_wins']:.1f}%" if oos_m["n"] else "",
            "OOS_AVG_PNL_PCT": f"{oos_m['avg_pnl']:.2f}" if oos_m["n"] else "",
            "OOS_AVG_R": f"{oos_m['avg_r']:.3f}" if oos_m["n"] else "",
            "OOS_SHEET_PNL": f"{oos_m['total_pnl']:.2f}" if oos_m["n"] else "",
            "FIT": fr.fit,
            "FIT_SCORE": str(fr.score),
            "FIT_SCORE_ROBUST": str(fr.score_robust),
            "MAX_WIN_PCT": f"{fr.max_win_pct:.2f}%" if full["n"] else "",
            "AVG_PNL_PCT_WO_MAX": f"{fr.avg_pnl_pct_wo_max:.2f}" if full["n"] else "",
            "MEDIAN_PNL_PCT": f"{fr.median_pnl_pct:.2f}" if full["n"] else "",
            "OUTLIER_PCT_OF_WINS": f"{fr.outlier_pct_of_wins:.1f}" if full["n"] else "",
            "FIT_ASSESSMENT": fr.text,
        }
        rows.append(row)

    fieldnames = [
        "SYMBOL",
        "STATUS",
        "TRADES",
        "WINS",
        "LOSSES",
        "BEs",
        "PCT_WINS",
        "TOTAL_PNL",
        "SHEET_PNL",
        "AVG_PNL_PCT",
        "AVG_R",
        "PROFIT_FACTOR",
        "FIRST_DATA_DATE",
        "LAST_DATA_DATE",
        "AVG_TRADES_PER_YEAR",
        "AVG_DAYS_HELD",
        "IS_TRADES",
        "IS_PCT_WINS",
        "IS_AVG_PNL_PCT",
        "IS_AVG_R",
        "IS_SHEET_PNL",
        "OOS_TRADES",
        "OOS_PCT_WINS",
        "OOS_AVG_PNL_PCT",
        "OOS_AVG_R",
        "OOS_SHEET_PNL",
        "FIT",
        "FIT_SCORE",
        "FIT_SCORE_ROBUST",
        "MAX_WIN_PCT",
        "AVG_PNL_PCT_WO_MAX",
        "MEDIAN_PNL_PCT",
        "OUTLIER_PCT_OF_WINS",
        "FIT_ASSESSMENT",
        "NOTE",
    ]

    # Full-history Paul Score (peer thresholds on this Summary — in-sample selection lens).
    traded = [r for r in rows if int(_f(r.get("TRADES"), 0)) > 0]
    paul_diag = apply_paul_scores_to_summary_rows(traded, fieldnames)
    score_by_sym = {r["SYMBOL"]: r.get("PAUL_SCORE", "") for r in traded}
    for r in rows:
        r["PAUL_SCORE"] = score_by_sym.get(r["SYMBOL"], "")

    # OOS-only Paul Score: peer thresholds among symbols with OOS trades (report-only).
    oos_rows: list[dict[str, Any]] = []
    oos_fields = [
        "SYMBOL",
        "PCT_WINS",
        "TOTAL_PNL",
        "SHEET_PNL",
        "AVG_PNL_PCT",
        "AVG_PNL_PCT_WO_MAX",
        "AVG_TRADES_PER_YEAR",
        "OUTLIER_PCT_OF_WINS",
        "AVG_DAYS_HELD",
    ]
    for r in rows:
        oos_n = int(_f(r.get("OOS_TRADES"), 0))
        if oos_n <= 0:
            continue
        # Rebuild WO_MAX / outlier from OOS trades only for peer components.
        sym = r["SYMBOL"]
        g = by_sym.get(sym, pd.DataFrame())
        if g.empty:
            continue
        ed = pd.to_datetime(g["entry_date"])
        oos_g = g[ed >= OOS_SPLIT]
        om = _slice_metrics(oos_g)
        closed_oos = [
            {"PNL_PCT": float(t["pnl_pct"]), "DATE_CLOSED": str(pd.Timestamp(t["entry_date"]).date())}
            for _, t in oos_g.iterrows()
        ]
        # Years for OOS window: split → last data
        last = r.get("LAST_DATA_DATE") or ""
        try:
            end = pd.Timestamp(last) if last else OOS_SPLIT
        except Exception:
            end = OOS_SPLIT
        oos_years = _years(OOS_SPLIT, end)
        oos_tpy = oos_n / oos_years if oos_years > 0 else 0.0
        fr_oos = assess_symbol_fit(
            trades=om["n"],
            wins=om["wins"],
            losses=om["losses"],
            pct_wins=om["pct_wins"],
            avg_pnl_pct=om["avg_pnl"],
            sheet_pnl=om["total_pnl"],
            avg_tpy=oos_tpy,
            closed_rows=closed_oos,
        )
        oos_rows.append(
            {
                "SYMBOL": sym,
                "PCT_WINS": f"{om['pct_wins']:.1f}%",
                "TOTAL_PNL": f"{om['total_pnl']:.2f}",
                "SHEET_PNL": f"{om['total_pnl']:.2f}",
                "AVG_PNL_PCT": f"{om['avg_pnl']:.2f}",
                "AVG_PNL_PCT_WO_MAX": f"{fr_oos.avg_pnl_pct_wo_max:.2f}",
                "AVG_TRADES_PER_YEAR": f"{oos_tpy:.2f}",
                "OUTLIER_PCT_OF_WINS": f"{fr_oos.outlier_pct_of_wins:.1f}",
                "AVG_DAYS_HELD": f"{om['avg_bars']:.1f}",
            }
        )
    oos_fields_copy = list(oos_fields)
    oos_paul_diag = apply_paul_scores_to_summary_rows(oos_rows, oos_fields_copy)
    oos_score = {r["SYMBOL"]: r.get("PAUL_SCORE", "") for r in oos_rows}
    if "PAUL_SCORE_OOS" not in fieldnames:
        fieldnames.append("PAUL_SCORE_OOS")
    # Keep PAUL_SCORE after FIT block for readability
    if "PAUL_SCORE" in fieldnames:
        fieldnames.remove("PAUL_SCORE")
    # Place PAUL_SCORE near front after SYMBOL for gold-set scanning
    insert_at = fieldnames.index("TRADES") if "TRADES" in fieldnames else 1
    fieldnames.insert(insert_at, "PAUL_SCORE")
    for r in rows:
        r["PAUL_SCORE_OOS"] = oos_score.get(r["SYMBOL"], "")

    return rows, fieldnames, {"full": paul_diag, "oos": oos_paul_diag}


def proposed_gold_pass(row: dict[str, Any]) -> bool:
    trades = int(_f(row.get("TRADES"), 0))
    if trades < PROPOSED_MIN_TRADES:
        return False
    paul = _f(row.get("PAUL_SCORE"), -1)
    if paul < PROPOSED_MIN_PAUL:
        return False
    wr_s = str(row.get("PCT_WINS", "")).replace("%", "")
    if _f(wr_s, 0) < PROPOSED_MIN_WR:
        return False
    if _f(row.get("SHEET_PNL"), 0) <= PROPOSED_MIN_SHEET:
        return False
    if _f(row.get("AVG_TRADES_PER_YEAR"), 0) < PROPOSED_MIN_TPY:
        return False
    if _f(row.get("AVG_PNL_PCT"), 0) < PROPOSED_MIN_EXPECTANCY:
        return False
    if _f(row.get("AVG_PNL_PCT_WO_MAX"), 0) < PROPOSED_MIN_WO_MAX:
        return False
    return True


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Sort by PAUL_SCORE desc, then SHEET_PNL desc for convenience
    def sort_key(r: dict[str, Any]) -> tuple:
        return (
            -_f(r.get("PAUL_SCORE"), -1),
            -_f(r.get("SHEET_PNL"), 0),
            -_f(r.get("AVG_PNL_PCT"), 0),
            r.get("SYMBOL", ""),
        )

    ordered = sorted(rows, key=sort_key)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(ordered)


def _num_cell(v: Any) -> str:
    s = "" if v is None else str(v)
    return html_mod.escape(s)


def write_html(
    path: Path,
    *,
    stamp: str,
    rows: list[dict[str, Any]],
    paul_diag: dict[str, Any],
    csv_name: str,
    proposed_csv_name: str,
) -> None:
    traded = [r for r in rows if int(_f(r.get("TRADES"), 0)) > 0]
    by_paul = sorted(traded, key=lambda r: (_f(r.get("PAUL_SCORE"), -1), _f(r.get("SHEET_PNL"), 0)), reverse=True)
    top = by_paul[:25]
    bottom = list(reversed(by_paul[-25:])) if len(by_paul) >= 25 else list(reversed(by_paul))
    proposed = [r for r in by_paul if proposed_gold_pass(r)]

    thr = (paul_diag.get("full") or {}).get("thresholds") or {}
    thr_rows = ""
    for label, info in thr.items():
        thr_rows += (
            "<tr>"
            f"<td>{html_mod.escape(label)}</td>"
            f"<td>{html_mod.escape(str(info.get('rule', '')))}</td>"
            f"<td>{info.get('mean', 0):.4g}</td>"
            f"<td>{info.get('median', 0):.4g}</td>"
            f"<td>{info.get('threshold', 0):.4g}</td>"
            f"<td>{info.get('n', 0)}</td>"
            "</tr>"
        )

    def sym_table(subset: list[dict[str, Any]], title: str) -> str:
        body = []
        for r in subset:
            body.append(
                "<tr>"
                f"<td>{_num_cell(r.get('SYMBOL'))}</td>"
                f"<td><b>{_num_cell(r.get('PAUL_SCORE'))}</b></td>"
                f"<td>{_num_cell(r.get('PAUL_SCORE_OOS'))}</td>"
                f"<td>{_num_cell(r.get('TRADES'))}</td>"
                f"<td>{_num_cell(r.get('PCT_WINS'))}</td>"
                f"<td>{_num_cell(r.get('AVG_PNL_PCT'))}</td>"
                f"<td>{_num_cell(r.get('AVG_R'))}</td>"
                f"<td>{_num_cell(r.get('SHEET_PNL'))}</td>"
                f"<td>{_num_cell(r.get('AVG_TRADES_PER_YEAR'))}</td>"
                f"<td>{_num_cell(r.get('AVG_DAYS_HELD'))}</td>"
                f"<td>{_num_cell(r.get('PROFIT_FACTOR'))}</td>"
                f"<td>{_num_cell(r.get('FIT'))}</td>"
                f"<td>{_num_cell(r.get('FIT_SCORE_ROBUST'))}</td>"
                f"<td>{_num_cell(r.get('OOS_TRADES'))}</td>"
                f"<td>{_num_cell(r.get('OOS_PCT_WINS'))}</td>"
                f"<td>{_num_cell(r.get('OOS_AVG_R'))}</td>"
                "</tr>"
            )
        return f"""
<h3>{html_mod.escape(title)}</h3>
<p class="small">Click column headers to sort.</p>
<table class="sortable">
<thead><tr>
{sortable_th("SYMBOL", "text")}
{sortable_th("PAUL_SCORE", "num")}
{sortable_th("PAUL_SCORE_OOS", "num")}
{sortable_th("TRADES", "num")}
{sortable_th("PCT_WINS", "num")}
{sortable_th("AVG_PNL_PCT", "num")}
{sortable_th("AVG_R", "num")}
{sortable_th("SHEET_PNL", "num")}
{sortable_th("AVG_TPY", "num")}
{sortable_th("AVG_BARS_HELD", "num")}
{sortable_th("PF", "num")}
{sortable_th("FIT", "text")}
{sortable_th("FIT_ROBUST", "num")}
{sortable_th("OOS_N", "num")}
{sortable_th("OOS_WR%", "num")}
{sortable_th("OOS_AvgR", "num")}
</tr></thead>
<tbody>
{''.join(body)}
</tbody>
</table>
"""

    all_body = []
    for r in by_paul:
        all_body.append(
            "<tr>"
            f"<td>{_num_cell(r.get('SYMBOL'))}</td>"
            f"<td><b>{_num_cell(r.get('PAUL_SCORE'))}</b></td>"
            f"<td>{_num_cell(r.get('PAUL_SCORE_OOS'))}</td>"
            f"<td>{_num_cell(r.get('TRADES'))}</td>"
            f"<td>{_num_cell(r.get('PCT_WINS'))}</td>"
            f"<td>{_num_cell(r.get('AVG_PNL_PCT'))}</td>"
            f"<td>{_num_cell(r.get('AVG_R'))}</td>"
            f"<td>{_num_cell(r.get('SHEET_PNL'))}</td>"
            f"<td>{_num_cell(r.get('TOTAL_PNL'))}</td>"
            f"<td>{_num_cell(r.get('AVG_TRADES_PER_YEAR'))}</td>"
            f"<td>{_num_cell(r.get('AVG_DAYS_HELD'))}</td>"
            f"<td>{_num_cell(r.get('PROFIT_FACTOR'))}</td>"
            f"<td>{_num_cell(r.get('OUTLIER_PCT_OF_WINS'))}</td>"
            f"<td>{_num_cell(r.get('AVG_PNL_PCT_WO_MAX'))}</td>"
            f"<td>{_num_cell(r.get('FIT'))}</td>"
            f"<td>{_num_cell(r.get('FIT_SCORE'))}</td>"
            f"<td>{_num_cell(r.get('FIT_SCORE_ROBUST'))}</td>"
            f"<td>{_num_cell(r.get('IS_TRADES'))}</td>"
            f"<td>{_num_cell(r.get('IS_PCT_WINS'))}</td>"
            f"<td>{_num_cell(r.get('OOS_TRADES'))}</td>"
            f"<td>{_num_cell(r.get('OOS_PCT_WINS'))}</td>"
            f"<td>{_num_cell(r.get('OOS_AVG_PNL_PCT'))}</td>"
            f"<td>{_num_cell(r.get('OOS_AVG_R'))}</td>"
            "</tr>"
        )

    filter_txt = (
        f"TRADES≥{PROPOSED_MIN_TRADES}, PAUL_SCORE≥{PROPOSED_MIN_PAUL}, "
        f"PCT_WINS≥{PROPOSED_MIN_WR:.0f}%, SHEET_PNL&gt;{PROPOSED_MIN_SHEET:,.0f}, "
        f"AVG_TRADES_PER_YEAR≥{PROPOSED_MIN_TPY}, "
        f"AVG_PNL_PCT≥{PROPOSED_MIN_EXPECTANCY}, "
        f"AVG_PNL_PCT_WO_MAX≥{PROPOSED_MIN_WO_MAX}"
    )
    oos_note = (
        f"Optional tighten: PAUL_SCORE_OOS≥{PROPOSED_MIN_PAUL_OOS} and "
        f"OOS_TRADES≥{PROPOSED_MIN_OOS_N} (report-only; do not retune on OOS)."
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>VolZone Symbol Summary — {html_mod.escape(stamp)}</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:24px;max-width:1400px;color:#1a1a1a;line-height:1.45}}
h1,h2,h3{{margin-top:1.4em}}
code{{background:#f4f4f5;padding:2px 6px;border-radius:4px}}
table.sortable{{border-collapse:collapse;width:100%;font-size:12.5px;margin:12px 0}}
table.sortable th,table.sortable td{{border:1px solid #cbd5e1;padding:5px 7px;text-align:left}}
table.sortable thead{{background:#f1f5f9}}
.note{{background:#fff7ed;border-left:4px solid #f97316;padding:10px 14px;margin:16px 0}}
.callout{{background:#eff6ff;border-left:4px solid #3b82f6;padding:10px 14px;margin:16px 0}}
.ok{{background:#f0fdf4;border-left:4px solid #22c55e;padding:10px 14px;margin:16px 0}}
.warn{{background:#fef2f2;border-left:4px solid #ef4444;padding:10px 14px;margin:16px 0}}
.small{{color:#64748b;font-size:12px}}
a{{color:#1d4ed8}}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>VolZone Symbol Summary (Paul score)</h1>
<p class="small">Stamp <code>{html_mod.escape(stamp)}</code> · Source <code>signals_rw63.csv</code> ·
Freeze: HL-only · first_retest · mt≥1 · eps=0.005 · lookback=126 · rw=63 · exit <code>zone_atr05_ts40</code> ·
<b>Research only — not production gold / not DailyRun</b>.</p>

<div class="note">
<strong>Purpose.</strong> House-style per-symbol Summary for gold-set / universe selection
(compare apples-to-apples with BRT/RS/YH <code>*_Summary_*.csv</code> + <code>PAUL_SCORE</code>).
CSV: <a href="{html_mod.escape(csv_name)}">{html_mod.escape(csv_name)}</a> ·
Proposed candidates: <a href="{html_mod.escape(proposed_csv_name)}">{html_mod.escape(proposed_csv_name)}</a>.
Pooled book still in <a href="VolZone_FullUniverse_Summary.html">VolZone_FullUniverse_Summary.html</a>.
</div>

<h2>1. Paul Score formula (house exact)</h2>
<div class="callout">
<strong>One-liner:</strong> Integer <b>0–8</b>: +1 each if ≥ <b>mean</b> across this Summary for
<code>PCT_WINS</code>, <code>TOTAL_PNL</code>, <code>SHEET_PNL</code>, <code>AVG_PNL_PCT</code>,
<code>AVG_PNL_PCT_WO_MAX</code>, <code>AVG_TRADES_PER_YEAR</code>;
+1 each if ≤ <b>mean</b> for <code>OUTLIER_PCT_OF_WINS</code>, <code>AVG_DAYS_HELD</code>
(faster turnover better). Peer median is not used for thresholds; <code>MEDIAN_PNL_PCT</code> is never scored. Blank/non-numeric cells skipped.
Implemented by <code>rocket_post_analysis.apply_paul_scores_to_summary_rows</code>.
</div>
<p class="small"><b>Fit caveat:</b> Full-history <code>PAUL_SCORE</code> is a peer rank on the full sample
(in-sample selection lens). <code>PAUL_SCORE_OOS</code> recomputes the same 0–8 rule on OOS-only metrics
among symbols with 2024+ trades — <b>report-only</b>; do not retune freezes on OOS.</p>

<h3>Peer thresholds used (full-history)</h3>
<table class="sortable">
<thead><tr>
{sortable_th("Component", "text")}
{sortable_th("Rule", "text")}
{sortable_th("Mean", "num")}
{sortable_th("Median", "num")}
{sortable_th("Threshold", "num")}
{sortable_th("N", "num")}
</tr></thead>
<tbody>
{thr_rows}
</tbody>
</table>

<div class="callout">
<strong>VZ dollar proxy.</strong> No engine <code>brt_cash</code> sizing — each trade uses synthetic notional
${SHEET_NOTIONAL:,.0f} so <code>TOTAL_PNL</code> = <code>SHEET_PNL</code> = Σ(pnl_pct/100 × {SHEET_NOTIONAL:,.0f}).
<code>AVG_DAYS_HELD</code> = mean <code>bars_held</code> (trading bars, not calendar days).
</div>

<h2>2. Coverage</h2>
<table class="sortable">
<thead><tr>
{sortable_th("Metric", "text")}
{sortable_th("Count", "num")}
</tr></thead>
<tbody>
<tr><td>Symbols in Summary rows</td><td>{len(rows)}</td></tr>
<tr><td>Symbols with ≥1 trade</td><td>{len(traded)}</td></tr>
<tr><td>Proposed gold-set candidates (research filter)</td><td>{len(proposed)}</td></tr>
</tbody>
</table>

<h2>3. Proposed gold-set filter (research — not adopted)</h2>
<div class="warn">
<strong>Proposed / research only.</strong> Do <b>not</b> treat this list as production gold until you confirm.
Filter mirrors <code>docs/system_setup_process.html</code> promotion defaults plus Paul score:
<code>{html_mod.escape(filter_txt)}</code>.
{html_mod.escape(oos_note)}
</div>
{sym_table(proposed[:80], f"Proposed candidates (showing up to 80 of {len(proposed)}; sorted by PAUL_SCORE)")}

<h2>4. Top / bottom by PAUL_SCORE</h2>
{sym_table(top, "Top 25 by PAUL_SCORE (then SHEET_PNL)")}
{sym_table(bottom, "Bottom 25 by PAUL_SCORE")}

<h2>5. All symbols with trades</h2>
<p class="small">Click column headers to sort. Default order: PAUL_SCORE ↓, SHEET_PNL ↓.</p>
<table class="sortable">
<thead><tr>
{sortable_th("SYMBOL", "text")}
{sortable_th("PAUL_SCORE", "num")}
{sortable_th("PAUL_SCORE_OOS", "num")}
{sortable_th("TRADES", "num")}
{sortable_th("PCT_WINS", "num")}
{sortable_th("AVG_PNL_PCT", "num")}
{sortable_th("AVG_R", "num")}
{sortable_th("SHEET_PNL", "num")}
{sortable_th("TOTAL_PNL", "num")}
{sortable_th("AVG_TPY", "num")}
{sortable_th("AVG_BARS_HELD", "num")}
{sortable_th("PF", "num")}
{sortable_th("OUTLIER%_WINS", "num")}
{sortable_th("AVG_PNL%_WO_MAX", "num")}
{sortable_th("FIT", "text")}
{sortable_th("FIT_SCORE", "num")}
{sortable_th("FIT_ROBUST", "num")}
{sortable_th("IS_N", "num")}
{sortable_th("IS_WR%", "num")}
{sortable_th("OOS_N", "num")}
{sortable_th("OOS_WR%", "num")}
{sortable_th("OOS_AvgPnL%", "num")}
{sortable_th("OOS_AvgR", "num")}
</tr></thead>
<tbody>
{''.join(all_body)}
</tbody>
</table>

{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def update_baseline(stamp_dir: Path, csv_name: str, html_name: str, proposed_name: str) -> None:
    bl = stamp_dir / "BASELINE.md"
    if not bl.is_file():
        return
    text = bl.read_text(encoding="utf-8")
    block = f"""
## Symbol Summary (Paul score) — research gold-set lens

- `{csv_name}` — house-style per-symbol Summary with `PAUL_SCORE` (0–8) + FIT / IS/OOS cols
- `{html_name}` — sortable HTML (Paul score prominent; proposed candidates labeled research-only)
- `{proposed_name}` — symbols passing proposed filter (NOT adopted gold)

**Paul Score (house):** +1 each if ≥ mean for PCT_WINS, TOTAL_PNL, SHEET_PNL, AVG_PNL_PCT, AVG_PNL_PCT_WO_MAX, AVG_TRADES_PER_YEAR; +1 each if ≤ mean for OUTLIER_PCT_OF_WINS, AVG_DAYS_HELD. Peer median is not used for thresholds; `MEDIAN_PNL_PCT` is never scored. Full-history score is an in-sample peer rank; `PAUL_SCORE_OOS` is report-only.

**Proposed filter (research):** TRADES≥{PROPOSED_MIN_TRADES}, PAUL_SCORE≥{PROPOSED_MIN_PAUL}, PCT_WINS≥{PROPOSED_MIN_WR:.0f}%, SHEET_PNL>{PROPOSED_MIN_SHEET:,.0f}, AVG_TRADES_PER_YEAR≥{PROPOSED_MIN_TPY}, AVG_PNL_PCT≥{PROPOSED_MIN_EXPECTANCY}, AVG_PNL_PCT_WO_MAX≥{PROPOSED_MIN_WO_MAX}. Confirm before treating as gold.
"""
    marker = "## Symbol Summary (Paul score)"
    if marker in text:
        # Replace from marker to end of file section or append once
        pre = text.split(marker)[0].rstrip()
        text = pre + "\n" + block
    else:
        # Insert into Outputs list and append section
        if "- `BASELINE.md`" in text:
            text = text.replace(
                "- `BASELINE.md`",
                f"- `BASELINE.md`\n- `{csv_name}` / `{html_name}` / `{proposed_name}` — symbol Summary + Paul score",
            )
        text = text.rstrip() + "\n" + block
    bl.write_text(text + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--stamp-dir",
        type=Path,
        default=DEFAULT_STAMP_DIR,
        help="Full-univ stamp directory with signals_rw63.csv",
    )
    args = ap.parse_args()
    stamp_dir = args.stamp_dir.resolve()
    signals_path = stamp_dir / "signals_rw63.csv"
    per_path = stamp_dir / "per_symbol_rw63.csv"
    if not signals_path.is_file():
        print(f"ERROR: missing {signals_path}", file=sys.stderr)
        return 1

    stamp = stamp_dir.name
    print(f"Loading {signals_path} …")
    signals = pd.read_csv(signals_path)
    per = pd.read_csv(per_path) if per_path.is_file() else pd.DataFrame()
    print(f"  signals={len(signals)} symbols_in_signals={signals['symbol'].nunique()}")

    rows, fieldnames, paul_diag = build_summary_rows(signals, per)
    csv_name = f"VZ_Summary_Symbols_{stamp}.csv"
    html_name = "VolZone_Symbol_Summary.html"
    proposed_name = f"VZ_Proposed_GoldSet_{stamp}.csv"

    csv_path = stamp_dir / csv_name
    html_path = stamp_dir / html_name
    proposed_path = stamp_dir / proposed_name

    write_csv(csv_path, rows, fieldnames)
    proposed_rows = [r for r in rows if proposed_gold_pass(r)]
    write_csv(proposed_path, proposed_rows, fieldnames)
    write_html(
        html_path,
        stamp=stamp,
        rows=rows,
        paul_diag=paul_diag,
        csv_name=csv_name,
        proposed_csv_name=proposed_name,
    )
    update_baseline(stamp_dir, csv_name, html_name, proposed_name)

    traded = [r for r in rows if int(_f(r.get("TRADES"), 0)) > 0]
    top10 = sorted(
        traded,
        key=lambda r: (_f(r.get("PAUL_SCORE"), -1), _f(r.get("SHEET_PNL"), 0)),
        reverse=True,
    )[:10]
    print(f"saved: {csv_path}")
    print(f"saved: {html_path}")
    print(f"saved: {proposed_path} (n={len(proposed_rows)})")
    print("TOP10 PAUL_SCORE:")
    for r in top10:
        print(
            f"  {r['SYMBOL']:6s} PAUL={r.get('PAUL_SCORE')} OOS={r.get('PAUL_SCORE_OOS')} "
            f"N={r.get('TRADES')} WR={r.get('PCT_WINS')} AvgPnL%={r.get('AVG_PNL_PCT')} "
            f"SHEET={r.get('SHEET_PNL')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
