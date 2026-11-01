#!/usr/bin/env python3
"""Live DualPaul78 VZ HVN engine A/B — full canonical compare metrics.

Control vs candidate engine Closed (+ Report / Summary / EquityMeta).
Research-only. Not gold. Not DailyRun. Overlay KEEP is not this book.
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import json
import math
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
from compare_format import (  # noqa: E402
    format_money,
    format_money_delta,
    overlay_ann_ror_max_dd,
)

DRIVE = ROOT / "drive"
OUT_DIR = DRIVE / "paul_experiments" / "vz_hvn_engine_ab_20260819"
CTRL_STAMP = "260819140929"
CAND_STAMP = "260819140958"
IS_CUT = date(2024, 1, 1)
SHEET = 45_000.0
INIT = 500_000.0
EXIT_KEYS = ("TARGET", "STOP_LOSS", "GAP_UP", "GAP_DOWN", "TIME")


def _f(v: Any, default: float = float("nan")) -> float:
    if v is None or v == "":
        return default
    s = str(v).strip().replace("%", "").replace(",", "").replace("$", "")
    if not s or s.upper() in {"N/A", "NONE"}:
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


def _row_get(row: dict, *names: str) -> str:
    for n in names:
        if n in row and row[n] not in (None, ""):
            return str(row[n]).strip()
        for k, v in row.items():
            if str(k).strip().upper().replace(" ", "_") == n.upper().replace(" ", "_") and v not in (None, ""):
                return str(v).strip()
    return ""


def load_trades(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _parse_d(_row_get(raw, "DATE_OPENED"))
            if opened is None:
                continue
            pnl = _f(_row_get(raw, "PNL_PCT", "PNL %"), 0.0)
            rows.append(
                {
                    "sym": _row_get(raw, "SYMBOL").upper(),
                    "opened": opened,
                    "closed": _parse_d(_row_get(raw, "DATE_CLOSED")),
                    "pnl": pnl,
                    "r": _f(_row_get(raw, "R_MULT"), 0.0),
                    "days": _f(_row_get(raw, "DAYS_HELD"), 0.0),
                    "pnl_d": _f(_row_get(raw, "PNL_DOLLARS"), 0.0),
                    "exit": _row_get(raw, "EXIT_TYPE"),
                }
            )
    return rows


def _p90(vals: list[float]) -> float:
    if not vals:
        return float("nan")
    s = sorted(vals)
    return float(s[min(len(s) - 1, int(round(0.9 * (len(s) - 1))))])


def book_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(trades)
    empty = {
        "n": 0,
        "wins": 0,
        "losses": 0,
        "be": 0,
        "wr": 0.0,
        "avg_pnl": 0.0,
        "avg_r": 0.0,
        "pf": 0.0,
        "sheet": 0.0,
        "total_pnl_d": 0.0,
        "avg_days": 0.0,
        "med_days": 0.0,
        "p90_days": float("nan"),
        "syms": 0,
        "avg_wo_max": 0.0,
        "ann_ror": float("nan"),
        "max_dd": float("nan"),
        "cap_days": 0.0,
        "ppc": float("nan"),
        "avg_win": float("nan"),
        "avg_loss": float("nan"),
        "wl_n": float("nan"),
        "wl_d": float("nan"),
        "exp_pct": 0.0,
        "exp_d": 0.0,
        "tpy": float("nan"),
        "equity_note": "no trades",
        "exits": {},
    }
    if n == 0:
        return empty
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    be = [p for p in pnls if p == 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    mx = max(pnls)
    wo = (sum(pnls) - mx) / (n - 1) if n >= 2 else pnls[0]
    rs = [t["r"] for t in trades if math.isfinite(t["r"])]
    days = [t["days"] for t in trades if math.isfinite(t["days"]) and t["days"] > 0]
    cap = overlay_ann_ror_max_dd(trades, cash=SHEET, initial_account=INIT)
    cap_days = float(cap["capital_days"] or 0.0)
    sheet = sum(p / 100.0 * SHEET for p in pnls)
    total_d = sum(t["pnl_d"] for t in trades if math.isfinite(t["pnl_d"]))
    opens = [t["opened"] for t in trades if t["opened"]]
    closes = [t["closed"] for t in trades if t["closed"]]
    span = None
    if opens:
        lo = min(opens)
        hi = max(closes) if closes else max(opens)
        span = (hi - lo).days / 365.25
    tpy = (n / span) if span and span > 0 else float("nan")
    win_d = sum(t["pnl_d"] for t in trades if t["pnl"] > 0 and math.isfinite(t["pnl_d"]))
    loss_d = abs(sum(t["pnl_d"] for t in trades if t["pnl"] < 0 and math.isfinite(t["pnl_d"])))
    exits = Counter(str(t.get("exit") or "").strip().upper() or "?" for t in trades)
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "be": len(be),
        "wr": 100.0 * len(wins) / n,
        "avg_pnl": sum(pnls) / n,
        "avg_r": (sum(rs) / len(rs)) if rs else 0.0,
        "pf": (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0),
        "sheet": sheet,
        "total_pnl_d": total_d,
        "avg_days": (sum(days) / len(days)) if days else 0.0,
        "med_days": sorted(days)[len(days) // 2] if days else 0.0,
        "p90_days": _p90(days),
        "syms": len({t["sym"] for t in trades if t["sym"]}),
        "avg_wo_max": wo,
        "ann_ror": cap["ann_ror"],
        "max_dd": cap["max_dd"],
        "cap_days": cap_days,
        "ppc": (total_d / cap_days) if cap_days > 0 else float("nan"),
        "avg_win": (sum(wins) / len(wins)) if wins else float("nan"),
        "avg_loss": (sum(losses) / len(losses)) if losses else float("nan"),
        "wl_n": (len(wins) / len(losses)) if losses else float("nan"),
        "wl_d": (win_d / loss_d) if loss_d > 0 else float("nan"),
        "exp_pct": sum(pnls) / n,
        "exp_d": sheet / n,
        "tpy": tpy,
        "equity_note": cap["note"],
        "exits": dict(exits),
    }


def pack(name: str, trades: list[dict[str, Any]]) -> dict[str, Any]:
    is_t = [t for t in trades if t["opened"] < IS_CUT]
    oos_t = [t for t in trades if t["opened"] >= IS_CUT]
    return {"name": name, "full": book_stats(trades), "is": book_stats(is_t), "oos": book_stats(oos_t)}


def quality_better(cand: dict[str, Any], ctrl: dict[str, Any]) -> bool:
    if cand["n"] <= 0 or ctrl["n"] <= 0:
        return False
    return cand["avg_pnl"] > ctrl["avg_pnl"] and (
        cand["avg_r"] > ctrl["avg_r"] or cand["pf"] > ctrl["pf"] or cand["wr"] > ctrl["wr"]
    )


def oos_softer(cand: dict[str, Any], ctrl: dict[str, Any]) -> bool:
    if cand["n"] < 8 or ctrl["n"] < 8:
        return cand["avg_pnl"] < ctrl["avg_pnl"]
    return cand["avg_pnl"] < ctrl["avg_pnl"] or cand["pf"] < ctrl["pf"]


def arm_verdict(ctrl: dict[str, Any], cand: dict[str, Any]) -> tuple[str, str]:
    lift = cand["is"]["avg_pnl"] - ctrl["is"]["avg_pnl"]
    is_up = quality_better(cand["is"], ctrl["is"]) and lift >= 0.25
    n_frac = (cand["is"]["n"] / ctrl["is"]["n"]) if ctrl["is"]["n"] else 0.0
    n_thin = cand["is"]["n"] < 15 or n_frac < 0.40
    oos_down = oos_softer(cand["oos"], ctrl["oos"])
    ann_c, ann_k = cand["is"]["ann_ror"], ctrl["is"]["ann_ror"]
    dd_c, dd_k = cand["is"]["max_dd"], ctrl["is"]["max_dd"]
    ann_dd_worse = (
        math.isfinite(ann_c)
        and math.isfinite(ann_k)
        and math.isfinite(dd_c)
        and math.isfinite(dd_k)
        and ann_c < ann_k
        and dd_c > dd_k
    )
    if not is_up:
        return "DISMISS", (
            f"IS quality not better / flat (AvgPnL {cand['is']['avg_pnl']:.2f} vs {ctrl['is']['avg_pnl']:.2f}; "
            f"N {cand['is']['n']} vs {ctrl['is']['n']})."
        )
    if n_thin:
        return "HOLD", (
            f"IS quality up but N collapsed ({cand['is']['n']} vs {ctrl['is']['n']}, "
            f"{100 * n_frac:.0f}% retained). Do not KEEP."
        )
    if oos_down:
        return "HOLD", (
            f"IS quality up (AvgPnL {cand['is']['avg_pnl']:.2f} vs {ctrl['is']['avg_pnl']:.2f}) "
            f"but OOS softened — do not retune."
        )
    if ann_dd_worse:
        return "HOLD", (
            "IS Ann ROR fell and Max DD worsened vs control — downgrade KEEP to HOLD."
        )
    if lift >= 0.50 and n_frac >= 0.70:
        return "KEEP", (
            f"IS quality up (AvgPnL {cand['is']['avg_pnl']:.2f} vs {ctrl['is']['avg_pnl']:.2f}, "
            f"N retained {100 * n_frac:.0f}%); OOS did not soften. Research-only — not DailyRun."
        )
    return "LEAN KEEP", (
        f"IS quality up (AvgPnL {cand['is']['avg_pnl']:.2f} vs {ctrl['is']['avg_pnl']:.2f}); "
        f"OOS did not soften. Modest lift and/or N drop — lean only. Research-only."
    )


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


SORT_JS = r"""
<script>
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
    var pinned = rows.filter(function (r) { return r.classList.contains("total-row"); });
    var movable = rows.filter(function (r) { return !r.classList.contains("total-row"); });
    movable.sort(function (a, b) {
      var av = parseSortValue(a.cells[col] ? a.cells[col].innerText : "", type);
      var bv = parseSortValue(b.cells[col] ? b.cells[col].innerText : "", type);
      var cmp = av < bv ? -1 : av > bv ? 1 : 0;
      return dir === "asc" ? cmp : -cmp;
    });
    movable.concat(pinned).forEach(function (r) { tbody.appendChild(r); });
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("th.sortable-th").forEach(function (th, idx) {
      function activate() {
        var type = th.getAttribute("data-sort") || "text";
        var asc = !th.classList.contains("sort-asc");
        table.querySelectorAll("th.sortable-th").forEach(function (x) {
          x.classList.remove("sort-asc", "sort-desc");
        });
        th.classList.add(asc ? "sort-asc" : "sort-desc");
        sortTable(table, idx, type, asc ? "asc" : "desc");
      }
      th.addEventListener("click", activate);
      th.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activate(); }
      });
    });
  });
})();
</script>
"""


def fmt_n(v: Any, nd: int) -> str:
    if v is None:
        return "—"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(x):
        return "—"
    if nd == 0:
        return f"{int(round(x))}"
    return f"{x:.{nd}f}"


def delta_cell(cand: float, ctrl: float, nd: int, *, money: bool = False) -> str:
    if not (math.isfinite(float(cand) if cand is not None else float("nan")) and math.isfinite(float(ctrl) if ctrl is not None else float("nan"))):
        try:
            c = float(cand)
            k = float(ctrl)
            if not (math.isfinite(c) and math.isfinite(k)):
                return "—"
        except (TypeError, ValueError):
            return "—"
    c = float(cand)
    k = float(ctrl)
    d = c - k
    if money:
        return format_money_delta(d)
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:.{nd}f}"


def metrics_table(rows: list[tuple], packed: list[dict[str, Any]], title: str, caption: str) -> str:
    """rows: (label, getter(pack)->val, nd, money). packed[0] is control."""
    head = sortable_th("Metric", "text") + "".join(sortable_th(p["name"], "num") for p in packed)
    head += sortable_th("Δ vs control", "num")
    body = ""
    for label, getter, nd, money in rows:
        body += f"<tr><td>{html_mod.escape(label)}</td>"
        vals = []
        for p in packed:
            v = getter(p)
            vals.append(v)
            cell = format_money(v) if money else fmt_n(v, nd)
            body += f'<td class="num">{cell}</td>'
        body += f'<td class="num">{delta_cell(vals[1], vals[0], nd, money=money)}</td></tr>'
    return (
        f"<h3>{html_mod.escape(title)}</h3>"
        f"<p class='small'>{html_mod.escape(caption)} Click column headers to sort.</p>"
        f"<table class='sortable'><caption>Click column headers to sort.</caption>"
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    )


def closed_spec(split: str) -> list[tuple]:
    g = lambda k: (lambda p, _k=k, _s=split: p[_s][_k])
    rows = [
        ("Closed N (context)", g("n"), 0, False),
        ("Wins", g("wins"), 0, False),
        ("Losses", g("losses"), 0, False),
        ("BE", g("be"), 0, False),
        ("Win %", g("wr"), 1, False),
        ("Total PnL $ (Closed dollars)", g("total_pnl_d"), 2, True),
        ("Sheet PnL $", g("sheet"), 2, True),
        ("Avg PnL %", g("avg_pnl"), 2, False),
        ("Book AVG_PNL_PCT_WO_MAX", g("avg_wo_max"), 2, False),
        ("AvgR", g("avg_r"), 2, False),
        ("Expectancy $ / trade", g("exp_d"), 2, True),
        ("Expectancy %", g("exp_pct"), 2, False),
        ("Avg win %", g("avg_win"), 2, False),
        ("Avg loss %", g("avg_loss"), 2, False),
        ("Win/Loss ratio (count)", g("wl_n"), 2, False),
        ("Win/Loss ratio $", g("wl_d"), 2, False),
        ("Profit factor", g("pf"), 2, False),
        ("Ann ROR % (Closed overlay, $45k / $500k DD)", g("ann_ror"), 1, False),
        ("Max DD % (Closed overlay $500k)", g("max_dd"), 2, False),
        ("Profit / capital day $", g("ppc"), 2, True),
        ("Capital days", g("cap_days"), 0, False),
        ("Avg days held", g("avg_days"), 1, False),
        ("Median days held", g("med_days"), 1, False),
        ("P90 days held", g("p90_days"), 1, False),
        ("Trades / year (span)", g("tpy"), 2, False),
        ("Names", g("syms"), 0, False),
    ]
    for ek in EXIT_KEYS:
        rows.append((f"Exit {ek} N", lambda p, e=ek, s=split: float(p[s]["exits"].get(e, 0)), 0, False))
        rows.append(
            (
                f"Exit {ek} %",
                lambda p, e=ek, s=split: (
                    100.0 * p[s]["exits"].get(e, 0) / p[s]["n"] if p[s]["n"] else float("nan")
                ),
                1,
                False,
            )
        )
    return rows


def load_first_row(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        row = next(r, None)
        return dict(row) if row else {}


def mean_num(rows: list[dict], *keys: str) -> float:
    vals = []
    for r in rows:
        v = _f(_row_get(r, *keys))
        if math.isfinite(v):
            vals.append(v)
    return (sum(vals) / len(vals)) if vals else float("nan")


def sum_num(rows: list[dict], *keys: str) -> float:
    vals = []
    for r in rows:
        v = _f(_row_get(r, *keys))
        if math.isfinite(v):
            vals.append(v)
    return float(sum(vals)) if vals else float("nan")


def report_pack(folder: Path, stamp: str, name: str) -> dict[str, Any]:
    rep = load_first_row(folder / f"VZ_Report_{stamp}.csv")
    meta = load_first_row(folder / f"VZ_EquityMeta_{stamp}.csv")
    summ_path = folder / f"VZ_Summary_Symbols_{stamp}.csv"
    srows: list[dict[str, str]] = []
    if summ_path.is_file():
        with summ_path.open(newline="", encoding="utf-8-sig") as f:
            srows = list(csv.DictReader(f))
    dd_meta = _f(_row_get(meta, "Max_Drawdown_pct"))
    agg_dd = _f(_row_get(meta, "Aggressive_Max_Drawdown_pct"))
    return {
        "name": name,
        "total_pnl": _f(_row_get(rep, "Total_PNL")),
        "sheet": _f(_row_get(rep, "sheet_PnL", "Sheet_PnL")),
        "n": _f(_row_get(rep, "Total_Trades")),
        "wins": _f(_row_get(rep, "Wins")),
        "losses": _f(_row_get(rep, "Losses")),
        "be": _f(_row_get(rep, "BE")),
        "wr": _f(_row_get(rep, "Pct_Wins")),
        "avg_pnl": _f(_row_get(rep, "Avg_PNL_Pct")),
        "pf": _f(_row_get(rep, "Profit_Factor")),
        "ann_ror": _f(_row_get(rep, "Ann_ROR")),
        "max_dd": _f(_row_get(rep, "Max_DD")),
        "exp": _f(_row_get(rep, "Expectancy")),
        "exp_pct": _f(_row_get(rep, "Expectancy_Pct")),
        "avg_win": _f(_row_get(rep, "Avg_Win_Pct")),
        "avg_loss": _f(_row_get(rep, "Avg_Loss_Pct")),
        "wl_n": _f(_row_get(rep, "Win_Loss_Ratio")),
        "wl_d": _f(_row_get(rep, "Win_Loss_Ratio_Dollar")),
        "avg_days": _f(_row_get(rep, "Avg_Days_Held")),
        "med_days": _f(_row_get(rep, "Median_Days_Held")),
        "p90_days": _f(_row_get(rep, "P90_Days")),
        "avg_uw": _f(_row_get(rep, "Avg_Days_Underwater")),
        "p90_uw": _f(_row_get(rep, "P90_Days_Underwater")),
        "cap_days": _f(_row_get(rep, "Capital_Days")),
        "ppc": _f(_row_get(rep, "Profit_Per_Capital_Day")),
        "streak": _f(_row_get(rep, "Losing_Streak")),
        "ces_avg": _f(_row_get(rep, "CES_AVG")),
        "ces_med": _f(_row_get(rep, "CES_Median")),
        "top10": _f(_row_get(rep, "Pct_PNL_Top10")),
        "bot10": _f(_row_get(rep, "Pct_PNL_Bottom10")),
        "max_pos": _f(_row_get(rep, "Max_Positions")),
        "avg_pos": _f(_row_get(rep, "Avg_Positions")),
        "med_pos": _f(_row_get(rep, "Median_Positions")),
        "conc_sym": _f(_row_get(rep, "Pct_PNL_Max_Symbol")),
        "conc_tr": _f(_row_get(rep, "Pct_PNL_Max_Trade")),
        "conc_ind": _f(_row_get(rep, "Pct_PNL_Max_Industry")),
        "agg_pnl": _f(_row_get(rep, "Aggressive_Total_PNL", "Aggressive_Total_PNL")),
        "agg_dd": _f(_row_get(rep, "Aggressive_Max_DD")),
        "eq_dd": dd_meta,
        "eq_uw_days": _f(_row_get(meta, "Max_Days_Underwater")),
        "eq_uw_pct": _f(_row_get(meta, "Pct_Days_Underwater")),
        "eq_agg_dd": agg_dd,
        "eq_agg_pnl": _f(_row_get(meta, "Aggressive_Total_PNL")),
        "sum_paul": sum_num(srows, "PAUL_SCORE"),
        "mean_paul": mean_num(srows, "PAUL_SCORE"),
        "sum_fit": sum_num(srows, "FIT_SCORE"),
        "mean_fit": mean_num(srows, "FIT_SCORE"),
        "sum_robust": sum_num(srows, "FIT_SCORE_ROBUST"),
        "mean_robust": mean_num(srows, "FIT_SCORE_ROBUST"),
        "mean_wo": mean_num(srows, "AVG_PNL_PCT_WO_MAX"),
        "mean_out": mean_num(srows, "OUTLIER_PCT_OF_WINS"),
        "mean_tpy": mean_num(srows, "AVG_TRADES_PER_YEAR"),
        "mean_maxw": mean_num(srows, "MAX_WIN_PCT"),
        "n_sym_sum": float(len(srows)),
    }


def report_spec() -> list[tuple]:
    g = lambda k: (lambda p, _k=k: p[_k])
    return [
        ("Universe names (Summary_Symbols rows)", g("n_sym_sum"), 0, False),
        ("Total trades", g("n"), 0, False),
        ("Wins / Losses / BE", g("wins"), 0, False),
        ("Losses", g("losses"), 0, False),
        ("BE", g("be"), 0, False),
        ("Win %", g("wr"), 1, False),
        ("Total PnL $ (Report)", g("total_pnl"), 2, True),
        ("Sheet PnL $ (Report)", g("sheet"), 2, True),
        ("Avg PnL %", g("avg_pnl"), 2, False),
        ("Expectancy $", g("exp"), 2, True),
        ("Expectancy %", g("exp_pct"), 2, False),
        ("Avg win % / Avg loss %", g("avg_win"), 2, False),
        ("Avg loss %", g("avg_loss"), 2, False),
        ("Win/Loss ratio (count)", g("wl_n"), 2, False),
        ("Win/Loss ratio $", g("wl_d"), 2, False),
        ("Profit factor", g("pf"), 2, False),
        ("Ann ROR % (Report / Audit)", g("ann_ror"), 1, False),
        ("Max DD % (Report host MTM)", g("max_dd"), 2, False),
        ("EquityMeta Max DD %", g("eq_dd"), 2, False),
        ("Profit / capital day $", g("ppc"), 2, True),
        ("Capital days", g("cap_days"), 0, False),
        ("Avg / Median / P90 days held", g("avg_days"), 1, False),
        ("Median days held", g("med_days"), 1, False),
        ("P90 days held", g("p90_days"), 1, False),
        ("Avg / P90 days underwater (Report)", g("avg_uw"), 1, False),
        ("P90 days underwater", g("p90_uw"), 1, False),
        ("EquityMeta max days UW", g("eq_uw_days"), 0, False),
        ("EquityMeta % days UW", g("eq_uw_pct"), 1, False),
        ("Losing streak", g("streak"), 0, False),
        ("Avg / Median / Max positions", g("avg_pos"), 2, False),
        ("Median positions", g("med_pos"), 1, False),
        ("Max positions", g("max_pos"), 0, False),
        ("Aggressive Total PnL $", g("agg_pnl"), 2, True),
        ("Aggressive Max DD %", g("agg_dd"), 2, False),
        ("Pct PnL max symbol / trade / industry", g("conc_sym"), 2, False),
        ("Pct PnL max trade", g("conc_tr"), 2, False),
        ("Pct PnL max industry", g("conc_ind"), 2, False),
        ("Pct PnL top10 / bottom10", g("top10"), 1, False),
        ("Pct PnL bottom10", g("bot10"), 1, False),
        ("CES avg / median", g("ces_avg"), 2, False),
        ("CES median", g("ces_med"), 2, False),
        ("Σ Paul Score", g("sum_paul"), 0, False),
        ("Mean Paul Score", g("mean_paul"), 2, False),
        ("Σ / mean FIT_SCORE", g("sum_fit"), 0, False),
        ("Mean FIT_SCORE", g("mean_fit"), 2, False),
        ("Σ / mean FIT_SCORE_ROBUST", g("sum_robust"), 0, False),
        ("Mean FIT_SCORE_ROBUST", g("mean_robust"), 2, False),
        ("Mean AVG_PNL_PCT_WO_MAX (Summary)", g("mean_wo"), 2, False),
        ("Mean OUTLIER_PCT_OF_WINS", g("mean_out"), 1, False),
        ("Mean AVG_TRADES_PER_YEAR", g("mean_tpy"), 2, False),
        ("Mean MAX_WIN_PCT (context)", g("mean_maxw"), 2, False),
    ]


def find_closed(stamp: str, extra_dirs: list[Path] | None = None) -> Path:
    extra = extra_dirs or []
    cands = [
        *[d / f"VZ_Closed_{stamp}.csv" for d in extra],
        *[d / "live_ctrl" / f"VZ_Closed_{stamp}.csv" for d in extra],
        *[d / "live_cand" / f"VZ_Closed_{stamp}.csv" for d in extra],
        OUT_DIR / "live_ctrl" / f"VZ_Closed_{stamp}.csv",
        OUT_DIR / "live_cand" / f"VZ_Closed_{stamp}.csv",
        OUT_DIR / "cand_out" / f"VZ_Closed_{stamp}.csv",
        DRIVE / f"VZ_Closed_{stamp}.csv",
    ]
    for p in cands:
        if p.is_file():
            return p
    raise SystemExit(f"missing Closed for stamp {stamp}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--control-stamp", default=CTRL_STAMP)
    ap.add_argument("--cand-stamp", default=CAND_STAMP)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument(
        "--title",
        default="VZ HVN engine A/B — DualPaul78 — canonical metrics",
    )
    ap.add_argument(
        "--universe-note",
        default="DualPaul78 (83-name Paul 7–8 winner-cut). That sleeve has survivor bias — it is not a tradable tape.",
    )
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    ctrl_path = find_closed(args.control_stamp, [out_dir])
    cand_path = find_closed(args.cand_stamp, [out_dir])
    ctrl = pack(f"control HVN-off {args.control_stamp}", load_trades(ctrl_path))
    cand = pack(f"HVN-on {args.cand_stamp}", load_trades(cand_path))
    verdict, why = arm_verdict(ctrl, cand)
    packed = [ctrl, cand]
    r_ctrl = report_pack(ctrl_path.parent, args.control_stamp, ctrl["name"])
    r_cand = report_pack(cand_path.parent, args.cand_stamp, cand["name"])
    rpacks = [r_ctrl, r_cand]
    out_dir.mkdir(parents=True, exist_ok=True)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>{html_mod.escape(args.title)}</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 24px; color: #1a1a1a; max-width: 1500px; }}
h1 {{ font-size: 1.35rem; }}
h2 {{ font-size: 1.12rem; margin-top: 28px; }}
.sub, .small {{ color: #555; line-height: 1.45; }}
.card {{ background: #f7f8fa; border: 1px solid #e2e5ea; padding: 12px 14px; border-radius: 6px; margin: 12px 0; }}
.verdict {{ border: 2px solid #b45309; background: #fff7ed; }}
.verdict h2 {{ margin: 0 0 8px; font-size: 1.2rem; }}
table.sortable {{ border-collapse: collapse; width: 100%; font-size: 0.84rem; margin: 8px 0 16px; }}
table.sortable th, table.sortable td {{ border-bottom: 1px solid #e5e7eb; padding: 6px 8px; text-align: left; }}
table.sortable th {{ background: #f0f2f5; }}
table.sortable caption {{ text-align: left; color: #555; padding: 4px 0; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
th.sortable-th {{ cursor: pointer; user-select: none; white-space: nowrap; }}
th.sortable-th:hover {{ background: #e2e8f0; }}
th.sortable-th .sort-ind::after {{ content: " \\2195"; opacity: .35; font-size: .85em; }}
th.sortable-th.sort-asc .sort-ind::after {{ content: " \\2191"; opacity: .9; }}
th.sortable-th.sort-desc .sort-ind::after {{ content: " \\2193"; opacity: .9; }}
code {{ background: #eee; padding: 1px 4px; border-radius: 3px; }}
</style>
</head>
<body>
<h1>{html_mod.escape(args.title)}</h1>
<p class="sub">This is <strong>engine vs engine</strong>
(<code>{html_mod.escape(args.control_stamp)}</code> vs <code>{html_mod.escape(args.cand_stamp)}</code>),
<strong>not</strong> an overlay-filter of house Closed. Universe: {html_mod.escape(args.universe_note)}
Full metric set from <code>CANONICAL_COMPARE_METRICS.md</code> (absolute + Δ).
Judge <strong>quality over N</strong>. Research candidate ≠ gold ≠ DailyRun. Isolated <code>-o</code>;
house DualPaul78 pin stayed <code>260817212836</code>.</p>
<div class="card">
<p>HVN gate is inside <code>generate_signals</code> (after min_touches, before append; VP at <code>signal_idx</code>).
ATR min-4 remains a post-filter. One knob: <code>vz_require_hvn_overlap</code> false vs true.
Default remains <strong>false</strong>. Frozen VP: 60d / 0.5% bins / HVN 50% of POC. Do not retune on OOS.</p>
<p><strong>DualPaul78 survivor bias remains</strong> even when this page is a 764 tradable tape.
A KEEP on DualPaul78 does not become a KEEP here (or vice versa) without labeling that as a second selection.
VZ is <strong>not</strong> a general TBN gold system.</p>
</div>
<div class="card verdict">
<h2>Verdict: {html_mod.escape(verdict)}</h2>
<p>{html_mod.escape(why)}</p>
<p>If OOS softened vs control → HOLD, do not retune HVN frac. Flag stays default <strong>false</strong> unless PO adopts after reconcile freeze.</p>
</div>
<h2>Full book — Report / EquityMeta / Summary_Symbols</h2>
{metrics_table(report_spec(), rpacks, "Report + EquityMeta + Paul/FIT", "Host book (sizing path). Report Max DD is host MTM; Closed overlay DD is below.")}
<h2>IS / OOS / full — Closed overlay (same formula both splits)</h2>
{metrics_table(closed_spec("is"), packed, "IS (entry < 2024-01-01)", "Judge KEEP/HOLD/DISMISS here.")}
{metrics_table(closed_spec("oos"), packed, "OOS (entry >= 2024-01-01, report-only)", "Soften → HOLD.")}
{metrics_table(closed_spec("full"), packed, "Full Closed overlay", "Apples-to-apples with IS/OOS; Ann ROR uses sheet $45,000; Max DD seeds $500,000.")}
<p class="small">Do not judge on max single-trade PnL. Headline FIT vs robust FIT both shown.
Stamps: control <code>live_ctrl/</code> · candidate <code>live_cand/</code>.</p>
{SORT_JS}
</body>
</html>
"""
    html_path = out_dir / "compare.html"
    html_path.write_text(html, encoding="utf-8")
    summary = {
        "control_closed": str(ctrl_path),
        "cand_closed": str(cand_path),
        "verdict": verdict,
        "why": why,
        "control": {k: ctrl[k] for k in ("full", "is", "oos")},
        "candidate": {k: cand[k] for k in ("full", "is", "oos")},
        "report_control": r_ctrl,
        "report_candidate": r_cand,
    }
    (out_dir / "engine_ab_stats.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"verdict={verdict}")
    print(why)
    print(f"html={html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
