#!/usr/bin/env python3
"""Compare house RSI freeze (no dist gate) vs min_dist52=7.18. Writes stamp HTML/BASELINE."""
from __future__ import annotations

import csv
import html as html_mod
import json
import math
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    canonical_book_order_html,
    enrich_calmar_sharpe_on_report_dict,
    format_money,
    format_money_delta,
    overlay_ann_ror_max_dd,
    parse_number,
)

STAMP = "rsi_mindist52_718_20260916"
OUT_DIR = REPO / "drive" / "paul_experiments" / STAMP
IS_CUT = date(2024, 1, 1)
SHEET = 10_000.0
INIT = DEFAULT_INITIAL_ACCOUNT
UNIV_N = 149

ORIGINAL_REQUEST = (
    "let's wire in min distance to 52 week high at 7.18, and run that through. "
    "send me a compare.html with the current defaults."
)
PLAIN_ENGLISH = (
    "Only take a Relative Strength Index (RSI) buy if, at the trigger close, "
    "price is at least 7.18% below the 52-week high. Compare that book to today’s "
    "house freeze (same everything else, no distance gate). Then make 7.18 the "
    "DailyRun default. Distance here means how far the close sits under the high "
    "(0% = sitting on the high; larger = further below)."
)

SORTABLE_TH_CSS = """
th.sortable-th { cursor: pointer; user-select: none; white-space: nowrap; }
th.sortable-th:hover { background: #e2e8f0; }
th.sortable-th .sort-ind::after { content: " \\2195"; opacity: .35; font-size: .85em; }
th.sortable-th.sort-asc .sort-ind::after { content: " \\2191"; opacity: .9; }
th.sortable-th.sort-desc .sort-ind::after { content: " \\2193"; opacity: .9; }
"""
SORTABLE_TABLE_SCRIPT = """
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : 0;
    if (type === "text") return s.toUpperCase();
    var n = s.replace(/[$,%+]/g, "").replace(/,/g, "");
    var v = parseFloat(n);
    return Number.isFinite(v) ? v : 0;
  }
  function sortTable(table, col, type, dir) {
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll("tr"));
    rows.sort(function (a, b) {
      var av = parseSortValue(a.cells[col] && a.cells[col].textContent, type);
      var bv = parseSortValue(b.cells[col] && b.cells[col].textContent, type);
      if (typeof av === "string" || typeof bv === "string") {
        return dir * String(av).localeCompare(String(bv));
      }
      return dir * (av - bv);
    });
    rows.forEach(function (r) { tbody.appendChild(r); });
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("th.sortable-th").forEach(function (th, col) {
      th.addEventListener("click", function () {
        var type = th.dataset.sort || "text";
        var dir = th.dataset.dir === "asc" ? -1 : 1;
        table.querySelectorAll("th.sortable-th").forEach(function (h) {
          h.dataset.dir = ""; h.classList.remove("sort-asc", "sort-desc");
        });
        th.dataset.dir = dir === 1 ? "asc" : "desc";
        th.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
        sortTable(table, col, type, dir);
      });
    });
  });
})();
"""


def sortable_th(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{html_mod.escape(typ)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _parse_date(raw: Any) -> Optional[date]:
    s = str(raw or "").strip()
    if not s:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s[:10] if fmt != "%Y%m%d" else s[:8], fmt).date()
        except ValueError:
            continue
    return None


def _latest_ts(folder: Path) -> str:
    pins = list(folder.glob("RSI_Closed_*.csv"))
    if not pins:
        raise FileNotFoundError(f"no RSI_Closed_*.csv in {folder}")
    pins.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return pins[0].stem.split("_")[-1]


def load_closed(folder: Path, ts: str) -> list[dict[str, Any]]:
    path = folder / f"RSI_Closed_{ts}.csv"
    out = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            opened = _parse_date(raw.get("DATE_OPENED"))
            pnl = parse_number(raw.get("PNL_PCT"))
            if opened is None or pnl is None:
                continue
            days = parse_number(raw.get("DAYS_HELD")) or 0.0
            pnl_d = parse_number(raw.get("PNL_DOLLARS"))
            if pnl_d is None:
                pnl_d = pnl / 100.0 * SHEET
            out.append(
                {
                    "symbol": str(raw.get("SYMBOL") or "").strip(),
                    "opened": opened,
                    "closed": _parse_date(raw.get("DATE_CLOSED")),
                    "pnl": pnl,
                    "pnl_d": pnl_d,
                    "days": days,
                    "exit": str(raw.get("EXIT_TYPE") or "").strip().upper(),
                }
            )
    return out


def slc(rows: list[dict[str, Any]], which: str) -> list[dict[str, Any]]:
    if which == "IS":
        return [r for r in rows if r["opened"] < IS_CUT]
    if which == "OOS":
        return [r for r in rows if r["opened"] >= IS_CUT]
    return list(rows)


def _median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[len(s) // 2]


def _p90(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[int(0.9 * (len(s) - 1))]


def pack(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    empty = {"n": 0, "wins": 0, "losses": 0, "win_pct": None, "avg_pnl_pct": None}
    if not n:
        return empty
    wins = sum(1 for r in rows if r["pnl"] > 0)
    losses = sum(1 for r in rows if r["pnl"] < 0)
    pcts = [r["pnl"] for r in rows]
    avg = sum(pcts) / n
    wo = sorted(pcts)
    avg_wo = (sum(wo[:-1]) / (n - 1)) if n > 1 else avg
    w = [p for p in pcts if p > 0]
    l = [p for p in pcts if p < 0]
    days = [r["days"] for r in rows if r["days"] > 0]
    overlay = [
        {
            "pnl": r["pnl"],
            "pnl_d": r["pnl_d"],
            "days": r["days"],
            "closed": r["closed"],
            "opened": r["opened"],
        }
        for r in rows
    ]
    ov = overlay_ann_ror_max_dd(overlay, cash=SHEET, initial_account=INIT)
    pnls_d = [r["pnl_d"] for r in rows]
    sw = sum(x for x in pnls_d if x > 0)
    sl_ = abs(sum(x for x in pnls_d if x < 0))
    pf = (sw / sl_) if sl_ > 0 else sw
    cap = ov.get("capital_days") or sum(days)
    total = float(ov.get("pnl_d") or sum(pnls_d))
    exits = Counter(r["exit"] or "?" for r in rows)
    wl_count = (wins / losses) if losses else float(wins)
    wl_dollar = (sw / sl_) if sl_ > 0 else sw
    return {
        "n": n,
        "wins": wins,
        "losses": losses,
        "win_pct": 100.0 * wins / n,
        "avg_pnl_pct": avg,
        "avg_wo_max": avg_wo,
        "avg_win_pct": (sum(w) / len(w)) if w else 0.0,
        "avg_loss_pct": (sum(l) / len(l)) if l else 0.0,
        "expectancy_pct": avg,
        "expectancy_d": total / n,
        "pf": pf,
        "wl_count": wl_count,
        "wl_dollar": wl_dollar,
        "ann_ror": ov.get("ann_ror"),
        "max_dd": ov.get("max_dd"),
        "calmar": ov.get("calmar"),
        "sharpe": ov.get("sharpe"),
        "avg_days": (sum(days) / len(days)) if days else 0.0,
        "median_days": _median(days),
        "p90_days": _p90(days),
        "capital_days": cap,
        "profit_per_cap_day": (total / cap) if cap else 0.0,
        "exits": dict(exits),
        "n_syms": len({r["symbol"] for r in rows}),
    }


def load_report(folder: Path, ts: str) -> dict[str, Any]:
    path = folder / f"RSI_Report_{ts}.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        row = next(csv.DictReader(f))
    out = {k: parse_number(v) if parse_number(v) is not None else v for k, v in row.items()}
    enrich_calmar_sharpe_on_report_dict(
        out, equity_curve_path=folder / f"RSI_EquityCurve_{ts}.csv"
    )
    return out


def load_equity_meta(folder: Path, ts: str) -> dict[str, Any]:
    path = folder / f"RSI_EquityMeta_{ts}.csv"
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        row = next(csv.DictReader(f))
    return {k: parse_number(v) if parse_number(v) is not None else v for k, v in row.items()}


def load_summary(folder: Path, ts: str) -> list[dict[str, Any]]:
    path = folder / f"RSI_Summary_{ts}.csv"
    rows = []
    if not path.is_file():
        return rows
    with path.open(encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            rows.append(raw)
    return rows


def _mean(xs: list[float]) -> Optional[float]:
    return (sum(xs) / len(xs)) if xs else None


def summary_pack(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    paul = [parse_number(r.get("PAUL_SCORE")) for r in rows]
    fit = [parse_number(r.get("FIT_SCORE")) for r in rows]
    fitr = [parse_number(r.get("FIT_SCORE_ROBUST")) for r in rows]
    wo = [parse_number(r.get("AVG_PNL_PCT_WO_MAX")) for r in rows]
    outl = [parse_number(r.get("OUTLIER_PCT_OF_WINS")) for r in rows]
    tpy = [parse_number(r.get("AVG_TRADES_PER_YEAR")) for r in rows]
    mx = [parse_number(str(r.get("MAX_WIN_PCT") or "").replace("%", "")) for r in rows]
    pf = [parse_number(r.get("PROFIT_FACTOR")) for r in rows]
    paul = [x for x in paul if x is not None]
    fit = [x for x in fit if x is not None]
    fitr = [x for x in fitr if x is not None]
    wo = [x for x in wo if x is not None]
    outl = [x for x in outl if x is not None]
    tpy = [x for x in tpy if x is not None]
    mx = [x for x in mx if x is not None]
    pf = [x for x in pf if x is not None]
    return {
        "n_syms": len(rows),
        "sum_paul": sum(paul),
        "mean_paul": _mean(paul),
        "sum_fit": sum(fit),
        "mean_fit": _mean(fit),
        "sum_fitr": sum(fitr),
        "mean_fitr": _mean(fitr),
        "mean_wo": _mean(wo),
        "mean_outl": _mean(outl),
        "mean_tpy": _mean(tpy),
        "mean_max_win": _mean(mx),
        "mean_pf": _mean(pf),
    }


def _fmt_pct(v: Any) -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "—"
    return f"{float(v):.2f}%"


def _fmt_num(v: Any, d: int = 2) -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "—"
    return f"{float(v):,.{d}f}"


def _delta_pct(a: Any, b: Any) -> str:
    if a is None or b is None:
        return "—"
    try:
        return f"{float(a) - float(b):+.2f}"
    except (TypeError, ValueError):
        return "—"


def verdict(
    c_full: dict, a_full: dict, c_oos: dict, a_oos: dict, c_is: dict, a_is: dict
) -> tuple[str, str]:
    """Research KEEP/HOLD/DISMISS plus DailyRun preference note."""
    n_c = float(c_full.get("n") or 0)
    n_a = float(a_full.get("n") or 0)
    avg_c = float(c_full.get("avg_pnl_pct") or 0)
    avg_a = float(a_full.get("avg_pnl_pct") or 0)
    wr_c = float(c_full.get("win_pct") or 0)
    wr_a = float(a_full.get("win_pct") or 0)
    oos_c = float(c_oos.get("avg_pnl_pct") or 0) if c_oos.get("n") else None
    oos_a = float(a_oos.get("avg_pnl_pct") or 0) if a_oos.get("n") else None
    n_ratio = (n_a / n_c) if n_c else 0.0
    collapsed = n_ratio < 0.55
    d_avg = avg_a - avg_c
    d_wr = wr_a - wr_c
    oos_soft = oos_c is not None and oos_a is not None and (oos_a - oos_c) <= -0.40
    if collapsed and d_avg < 0.3:
        research = "DISMISS (N collapsed without a quality lift)"
    elif oos_soft:
        research = "HOLD (OOS softened vs house — report-only; do not retune OOS)"
    elif d_avg >= 0.30 and d_wr >= -1.0 and not collapsed:
        research = "LEAN KEEP (quality up, N intact) — still in-sample selection"
    elif d_avg >= 0.15 and not collapsed:
        research = "HOLD / lean keep (small FULL quality lift; in-sample selection)"
    elif d_avg <= -0.40:
        research = "DISMISS (FULL quality worse)"
    else:
        research = "HOLD (flat quality / mixed)"
    wired = (
        "DailyRun wired by preference (Paul ask) even if research is HOLD. "
        "7.18 was picked after seeing correlation / sheet — in-sample selection."
    )
    return research, wired


def arm_row(name: str, knob: str, st: dict, ctrl: dict, sl: str, note: str) -> str:
    d_avg = _delta_pct(st.get("avg_pnl_pct"), ctrl.get("avg_pnl_pct"))
    d_dd = _delta_pct(st.get("max_dd"), ctrl.get("max_dd"))
    cells = [
        name,
        knob,
        f"{st.get('n') or 0:,}",
        str(st.get("n_syms") or ""),
        _fmt_pct(st.get("win_pct")),
        _fmt_pct(st.get("avg_pnl_pct")),
        _fmt_pct(st.get("avg_wo_max")),
        _fmt_pct(st.get("expectancy_pct")),
        format_money(st.get("expectancy_d")),
        _fmt_pct(st.get("avg_win_pct")),
        _fmt_pct(st.get("avg_loss_pct")),
        _fmt_num(st.get("wl_count")),
        _fmt_num(st.get("wl_dollar")),
        _fmt_num(st.get("pf")),
        _fmt_pct(st.get("ann_ror")),
        _fmt_pct(st.get("max_dd")),
        _fmt_num(st.get("calmar")),
        _fmt_num(st.get("sharpe")),
        format_money(st.get("profit_per_cap_day")),
        _fmt_num(st.get("capital_days"), 0),
        _fmt_num(st.get("avg_days"), 1),
        _fmt_num(st.get("median_days"), 1),
        _fmt_num(st.get("p90_days"), 1),
        f"{d_avg}%",
        f"{d_dd}",
        note,
    ]
    return "<tr>" + "".join(f"<td>{html_mod.escape(str(c))}</td>" for c in cells) + "</tr>"


SLICE_HEADERS = [
    ("Arm", "text"),
    ("Knob", "text"),
    ("N", "num"),
    ("Names", "num"),
    ("Win %", "num"),
    ("Avg PnL %", "num"),
    ("AVG_PNL_PCT_WO_MAX", "num"),
    ("Expectancy %", "num"),
    ("Expectancy $", "num"),
    ("Avg win %", "num"),
    ("Avg loss %", "num"),
    ("Win/Loss (count)", "num"),
    ("Win/Loss $", "num"),
    ("PF", "num"),
    ("Ann ROR %", "num"),
    ("Max DD %", "num"),
    ("Calmar", "num"),
    ("Sharpe", "num"),
    ("Profit / cap day", "num"),
    ("Capital days", "num"),
    ("Avg days", "num"),
    ("Median days", "num"),
    ("P90 days", "num"),
    ("Δ Avg PnL % vs ctrl", "num"),
    ("Δ Max DD vs ctrl", "num"),
    ("Note", "text"),
]


def slice_table(ctrl: dict, cand: dict, sl: str, note: str) -> str:
    title = {
        "IS": "IS (entry &lt; 2024-01-01) — 7.18 was shopped here / on the sheet",
        "OOS": "OOS (entry ≥ 2024-01-01) — report-only",
        "FULL": "FULL (all history) — overlay $10k/fill on $500k seed",
    }[sl]
    th = "".join(sortable_th(h, t) for h, t in SLICE_HEADERS)
    return (
        f"<h3>{title}</h3>"
        f'<p class="meta">Click column headers to sort. Sheet $ / Total PnL $ omitted.</p>'
        f'<table class="sortable"><thead><tr>{th}</tr></thead><tbody>'
        f"{arm_row('CONTROL', 'min_dist=off', ctrl, ctrl, sl, '')}"
        f"{arm_row('CANDIDATE', 'min_dist=7.18', cand, ctrl, sl, note)}"
        f"</tbody></table>"
    )


def full_canonical_rows(
    c_rep: dict, a_rep: dict, c_eq: dict, a_eq: dict, c_sum: dict, a_sum: dict, c_wo: Any, a_wo: Any
) -> list[tuple[str, str, str, str]]:
    def g(d: dict, *keys: str) -> Any:
        for k in keys:
            if k in d and d[k] not in (None, "", "N/A"):
                return d[k]
        return None

    pairs = [
        ("Universe size", UNIV_N, UNIV_N, "int"),
        ("Total trades", g(c_rep, "Total_Trades"), g(a_rep, "Total_Trades"), "int"),
        ("Wins", g(c_rep, "Wins"), g(a_rep, "Wins"), "int"),
        ("Losses", g(c_rep, "Losses"), g(a_rep, "Losses"), "int"),
        ("Win %", g(c_rep, "Pct_Wins"), g(a_rep, "Pct_Wins"), "pct"),
        ("Avg PnL %", g(c_rep, "Avg_PNL_Pct"), g(a_rep, "Avg_PNL_Pct"), "pct"),
        ("Book AVG_PNL_PCT_WO_MAX", c_wo, a_wo, "pct"),
        ("Expectancy $", g(c_rep, "Expectancy"), g(a_rep, "Expectancy"), "money"),
        ("Expectancy %", g(c_rep, "Expectancy_Pct"), g(a_rep, "Expectancy_Pct"), "pct"),
        ("Avg win %", g(c_rep, "Avg_Win_Pct"), g(a_rep, "Avg_Win_Pct"), "pct"),
        ("Avg loss %", g(c_rep, "Avg_Loss_Pct"), g(a_rep, "Avg_Loss_Pct"), "pct"),
        ("Win/Loss ratio (count)", g(c_rep, "Win_Loss_Ratio"), g(a_rep, "Win_Loss_Ratio"), "num"),
        ("Win/Loss ratio $", g(c_rep, "Win_Loss_Ratio_Dollar"), g(a_rep, "Win_Loss_Ratio_Dollar"), "num"),
        ("Profit factor", g(c_rep, "Profit_Factor"), g(a_rep, "Profit_Factor"), "num"),
        ("Ann ROR %", g(c_rep, "Ann_ROR"), g(a_rep, "Ann_ROR"), "pct"),
        ("Max DD %", g(c_rep, "Max_DD"), g(a_rep, "Max_DD"), "pct"),
        ("Calmar", g(c_rep, "Calmar"), g(a_rep, "Calmar"), "num"),
        ("Sharpe", g(c_rep, "Sharpe") or g(c_eq, "Sharpe"), g(a_rep, "Sharpe") or g(a_eq, "Sharpe"), "num"),
        ("Profit per capital day", g(c_rep, "Profit_Per_Capital_Day"), g(a_rep, "Profit_Per_Capital_Day"), "money"),
        ("Capital days", g(c_rep, "Capital_Days"), g(a_rep, "Capital_Days"), "int"),
        ("Avg days held", g(c_rep, "Avg_Days_Held"), g(a_rep, "Avg_Days_Held"), "num"),
        ("Median days held", g(c_rep, "Median_Days_Held"), g(a_rep, "Median_Days_Held"), "num"),
        ("P90 days held", g(c_rep, "P90_Days"), g(a_rep, "P90_Days"), "num"),
        ("Avg days underwater", g(c_rep, "Avg_Days_Underwater"), g(a_rep, "Avg_Days_Underwater"), "num"),
        ("P90 days underwater", g(c_rep, "P90_Days_Underwater"), g(a_rep, "P90_Days_Underwater"), "num"),
        ("Max days underwater (equity)", g(c_eq, "Max_Days_Underwater"), g(a_eq, "Max_Days_Underwater"), "int"),
        ("% days underwater (equity)", g(c_eq, "Pct_Days_Underwater"), g(a_eq, "Pct_Days_Underwater"), "pct"),
        ("Losing streak", g(c_rep, "Losing_Streak"), g(a_rep, "Losing_Streak"), "int"),
        ("Avg positions", g(c_rep, "Avg_Positions"), g(a_rep, "Avg_Positions"), "num"),
        ("Median positions", g(c_rep, "Median_Positions"), g(a_rep, "Median_Positions"), "num"),
        ("Max positions", g(c_rep, "Max_Positions"), g(a_rep, "Max_Positions"), "int"),
        ("Aggressive Total PnL $", g(c_rep, "Aggressive_Total_PNL"), g(a_rep, "Aggressive_Total_PNL"), "money"),
        ("Aggressive Max DD %", g(c_rep, "Aggressive_Max_DD"), g(a_rep, "Aggressive_Max_DD"), "pct"),
        ("Pct PnL max symbol", g(c_rep, "Pct_PNL_Max_Symbol"), g(a_rep, "Pct_PNL_Max_Symbol"), "pct"),
        ("Pct PnL max trade", g(c_rep, "Pct_PNL_Max_Trade"), g(a_rep, "Pct_PNL_Max_Trade"), "pct"),
        ("Pct PnL max industry", g(c_rep, "Pct_PNL_Max_Industry"), g(a_rep, "Pct_PNL_Max_Industry"), "pct"),
        ("Pct PnL top10", g(c_rep, "Pct_PNL_Top10"), g(a_rep, "Pct_PNL_Top10"), "pct"),
        ("Pct PnL bottom10", g(c_rep, "Pct_PNL_Bottom10"), g(a_rep, "Pct_PNL_Bottom10"), "pct"),
        ("CES avg", g(c_rep, "CES_AVG"), g(a_rep, "CES_AVG"), "num"),
        ("CES median", g(c_rep, "CES_Median"), g(a_rep, "CES_Median"), "num"),
        ("Σ Paul Score", c_sum.get("sum_paul"), a_sum.get("sum_paul"), "num"),
        ("Mean Paul Score", c_sum.get("mean_paul"), a_sum.get("mean_paul"), "num"),
        ("Σ FIT Score", c_sum.get("sum_fit"), a_sum.get("sum_fit"), "num"),
        ("Mean FIT Score", c_sum.get("mean_fit"), a_sum.get("mean_fit"), "num"),
        ("Σ FIT Score Robust", c_sum.get("sum_fitr"), a_sum.get("sum_fitr"), "num"),
        ("Mean FIT Score Robust", c_sum.get("mean_fitr"), a_sum.get("mean_fitr"), "num"),
        ("Mean AVG_PNL_PCT_WO_MAX", c_sum.get("mean_wo"), a_sum.get("mean_wo"), "pct"),
        ("Mean OUTLIER_PCT_OF_WINS", c_sum.get("mean_outl"), a_sum.get("mean_outl"), "pct"),
        ("Mean AVG_TRADES_PER_YEAR", c_sum.get("mean_tpy"), a_sum.get("mean_tpy"), "num"),
        ("Mean MAX_WIN_PCT", c_sum.get("mean_max_win"), a_sum.get("mean_max_win"), "pct"),
    ]
    order = set(canonical_book_order_html())
    out = []
    for label, cv, av, kind in pairs:
        if label not in order:
            continue
        if kind == "money":
            cs, as_ = format_money(cv), format_money(av)
            try:
                ds = format_money_delta(float(av) - float(cv)) if cv is not None and av is not None else "—"
            except (TypeError, ValueError):
                ds = "—"
        elif kind == "pct":
            cs, as_ = _fmt_pct(cv), _fmt_pct(av)
            ds = _delta_pct(av, cv)
        elif kind == "int":
            cs = "—" if cv is None else f"{int(float(cv)):,}"
            as_ = "—" if av is None else f"{int(float(av)):,}"
            try:
                ds = f"{int(float(av) - float(cv)):+,}" if cv is not None and av is not None else "—"
            except (TypeError, ValueError):
                ds = "—"
        else:
            cs, as_ = _fmt_num(cv), _fmt_num(av)
            ds = _delta_pct(av, cv)
        out.append((label, cs, as_, ds))
    return out


def exit_table(c_ex: Counter, a_ex: Counter, n_c: int, n_a: int) -> str:
    keys = sorted(set(c_ex) | set(a_ex))
    th = "".join(
        sortable_th(h, t)
        for h, t in [
            ("EXIT_TYPE", "text"),
            ("Ctrl N", "num"),
            ("Ctrl %", "num"),
            ("Cand N", "num"),
            ("Cand %", "num"),
            ("Δ N", "num"),
        ]
    )
    rows = []
    for k in keys:
        cn, an = c_ex.get(k, 0), a_ex.get(k, 0)
        cp = 100.0 * cn / n_c if n_c else 0.0
        ap = 100.0 * an / n_a if n_a else 0.0
        rows.append(
            "<tr>"
            + "".join(
                f"<td>{html_mod.escape(str(x))}</td>"
                for x in (k, cn, f"{cp:.1f}%", an, f"{ap:.1f}%", f"{an - cn:+d}")
            )
            + "</tr>"
        )
    return (
        '<table class="sortable"><thead><tr>'
        + th
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def main() -> int:
    ctrl_dir = OUT_DIR / "control"
    cand_dir = OUT_DIR / "candidate"
    ctrl_ts = _latest_ts(ctrl_dir)
    cand_ts = _latest_ts(cand_dir)
    ctrl_all = load_closed(ctrl_dir, ctrl_ts)
    cand_all = load_closed(cand_dir, cand_ts)
    packs = {
        sl: (pack(slc(ctrl_all, sl)), pack(slc(cand_all, sl)))
        for sl in ("IS", "OOS", "FULL")
    }
    c_full, a_full = packs["FULL"]
    c_oos, a_oos = packs["OOS"]
    c_is, a_is = packs["IS"]
    research, wired = verdict(c_full, a_full, c_oos, a_oos, c_is, a_is)
    c_rep = load_report(ctrl_dir, ctrl_ts)
    a_rep = load_report(cand_dir, cand_ts)
    c_eq = load_equity_meta(ctrl_dir, ctrl_ts)
    a_eq = load_equity_meta(cand_dir, cand_ts)
    c_sum = summary_pack(load_summary(ctrl_dir, ctrl_ts))
    a_sum = summary_pack(load_summary(cand_dir, cand_ts))
    canon = full_canonical_rows(
        c_rep, a_rep, c_eq, a_eq, c_sum, a_sum, c_full.get("avg_wo_max"), a_full.get("avg_wo_max")
    )
    c_ex = Counter(c_full.get("exits") or {})
    a_ex = Counter(a_full.get("exits") or {})

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    baseline = f"""# BASELINE — {STAMP}

**Status:** Param A/B (one knob). DailyRun wired by preference. **Not walk-forward gold.** OOS report-only.

## What you asked

> {ORIGINAL_REQUEST}

## In plain English

{PLAIN_ENGLISH}

## Honesty

- One knob: `rsi_min_dist_to_52w_high_pct_at_trigger=7.18` (MIN: keep if DIST_TO_52W_HIGH_PCT_AT_TRIGGER ≥ 7.18).
- Freeze otherwise: ob=70 / os=30 / exit=70 / max_trigger=60 / **min_atr=5** (house, not play atr=0) / ts=20 / next_open / house `rsi_universe.csv` 149.
- Control is a **full-history house-default re-run** (no `entry_end_date`, no extra gates). Not play stamps `260916113811` / `114053` / `114743` / `115501` (those used atr=0 and/or `entry_end_date` and/or stole the house pin).
- IS = entry_date < 2024-01-01; OOS report-only. **7.18 was picked after seeing correlation / sheet — in-sample selection.**
- KEEP only if quality improves without collapsing N; OOS soften → HOLD. DailyRun wiring is Paul’s explicit ask even if research would HOLD.

## Control vs candidate

| Arm | Knob | Isolated stamp | Names |
|-----|------|----------------|-------|
| CONTROL | min_dist=off (0) | `{ctrl_ts}` | 149 |
| CANDIDATE | min_dist=7.18 | `{cand_ts}` | 149 |

### CONTROL
- **IS** N={c_is['n']} WR={c_is['win_pct']:.2f}% Avg%={c_is['avg_pnl_pct']:.2f} MaxDD={c_is['max_dd']:.2f}
- **OOS** N={c_oos['n']} WR={c_oos['win_pct']:.2f}% Avg%={c_oos['avg_pnl_pct']:.2f} MaxDD={c_oos['max_dd']:.2f}
- **FULL** N={c_full['n']} WR={c_full['win_pct']:.2f}% Avg%={c_full['avg_pnl_pct']:.2f} MaxDD={c_full['max_dd']:.2f}

### CANDIDATE min_dist=7.18
- **IS** N={a_is['n']} WR={a_is['win_pct']:.2f}% Avg%={a_is['avg_pnl_pct']:.2f} MaxDD={a_is['max_dd']:.2f}
- **OOS** N={a_oos['n']} WR={a_oos['win_pct']:.2f}% Avg%={a_oos['avg_pnl_pct']:.2f} MaxDD={a_oos['max_dd']:.2f}
- **FULL** N={a_full['n']} WR={a_full['win_pct']:.2f}% Avg%={a_full['avg_pnl_pct']:.2f} MaxDD={a_full['max_dd']:.2f}

- **Research verdict:** {research}
- **DailyRun:** {wired}
- **OOS Δ Avg%:** {float(a_oos['avg_pnl_pct']) - float(c_oos['avg_pnl_pct']):+.2f} (report-only)
"""
    (OUT_DIR / "BASELINE.md").write_text(baseline, encoding="utf-8")

    canon_th = "".join(
        sortable_th(h, t)
        for h, t in [
            ("Metric", "text"),
            ("CONTROL (off)", "num"),
            ("CANDIDATE (7.18)", "num"),
            ("Δ cand−ctrl", "num"),
        ]
    )
    canon_body = "".join(
        "<tr>"
        + "".join(f"<td>{html_mod.escape(str(x))}</td>" for x in row)
        + "</tr>"
        for row in canon
    )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>{STAMP}</title>
<style>
{SORTABLE_TH_CSS}
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1.5rem; color: #0f172a; background: #f8fafc; }}
h1 {{ font-size: 1.4rem; margin: 0 0 .35rem; }}
h2 {{ font-size: 1.12rem; margin: 1.5rem 0 .45rem; border-bottom: 1px solid #cbd5e1; padding-bottom: .25rem; }}
.meta {{ color: #475569; font-size: .92rem; max-width: 78rem; }}
.insight {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .75rem 1rem; margin: .75rem 0; max-width: 78rem; }}
.ask {{ background: #eff6ff; border: 1px solid #bfdbfe; }}
table.sortable {{ border-collapse: collapse; background: #fff; font-size: .82rem; margin: .5rem 0 1rem; }}
table.sortable th, table.sortable td {{ border: 1px solid #e2e8f0; padding: .32rem .5rem; }}
table.sortable th {{ background: #f1f5f9; }}
.badge {{ display: inline-block; padding: .1rem .45rem; border-radius: 4px; font-size: .8rem; background: #e2e8f0; }}
.caveat {{ color: #9a3412; font-size: .9rem; }}
blockquote.meta {{ margin: .4rem 0 0; padding-left: .8rem; border-left: 3px solid #93c5fd; }}
</style></head><body>
<h1>RSI min distance to 52-week high = 7.18 vs house default (off)</h1>
<p class="badge">One-knob ENTRY A/B · DailyRun wired by preference · not walk-forward gold · OOS report-only</p>
<p class="meta">Stamp <code>{STAMP}</code> · 2026-09-16 · click column headers to sort</p>
<div class="insight ask">
<h2 style="margin-top:0;border:0">What you asked</h2>
<blockquote class="meta">{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN_ENGLISH)}</p>
</div>
<div class="insight">
<p><strong>Research verdict:</strong> {html_mod.escape(research)}</p>
<p><strong>DailyRun:</strong> {html_mod.escape(wired)}</p>
<p class="caveat"><strong>Selection honesty:</strong> 7.18 was picked after seeing correlation / the sheet.
That is in-sample selection. OOS is report-only. Control is a fresh full-history house run
(ob70/os30/exit70/max60/<strong>atr5</strong>/ts20/next_open, 149 names) — not the IS play stamps
that used atr=0 or <code>entry_end_date</code>.</p>
<p class="meta">Control stamp <code>{ctrl_ts}</code> · Candidate <code>{cand_ts}</code> ·
<code>-v DIST_TO_52W_HIGH_PCT_AT_TRIGGER=</code> is MIN (≥).</p>
</div>
<h2>IS / OOS / FULL (Closed overlay)</h2>
{slice_table(c_is, a_is, "IS", "in-sample selection")}
{slice_table(c_oos, a_oos, "OOS", "report-only")}
{slice_table(c_full, a_full, "FULL", research)}
<h2>FULL host Report / EquityMeta / Summary (canonical set)</h2>
<p class="meta">Click column headers to sort. Sheet $ / Total PnL $ omitted per compare rule.</p>
<table class="sortable"><thead><tr>{canon_th}</tr></thead><tbody>{canon_body}</tbody></table>
<h2>Exit mix (FULL Closed)</h2>
{exit_table(c_ex, a_ex, int(c_full['n']), int(a_full['n']))}
<script>{SORTABLE_TABLE_SCRIPT}</script>
</body></html>
"""
    (OUT_DIR / "compare.html").write_text(html, encoding="utf-8")
    (OUT_DIR / "summary.json").write_text(
        json.dumps(
            {
                "ctrl_ts": ctrl_ts,
                "cand_ts": cand_ts,
                "research_verdict": research,
                "dailyrun": wired,
                "slices": {
                    k: {"control": v[0], "candidate": v[1]} for k, v in packs.items()
                },
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"[rsi mindist] wrote {OUT_DIR / 'compare.html'}")
    print(
        f"  CONTROL {ctrl_ts} FULL N={c_full['n']} Avg%={c_full['avg_pnl_pct']:.2f} "
        f"OOS Avg%={c_oos['avg_pnl_pct']:.2f}"
    )
    print(
        f"  CAND    {cand_ts} FULL N={a_full['n']} Avg%={a_full['avg_pnl_pct']:.2f} "
        f"OOS Avg%={a_oos['avg_pnl_pct']:.2f}"
    )
    print(f"  research {research}")
    print(f"  dailyrun {wired}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
