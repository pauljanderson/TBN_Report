#!/usr/bin/env python3
"""Select VZ names with IS-only Paul 7–8 (no OOS Paul) and compare books.

Uses ALL freeze Closed stamp 260817214643. Paul peer ranks are computed on
IS trades only (entry_date < 2024-01-01). OOS is report-only.
"""
from __future__ import annotations

import csv
import html as html_mod
import math
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock_analysis"))
from rocket_post_analysis import apply_paul_scores_to_summary_rows  # noqa: E402

DRIVE = ROOT / "drive"
OUT_DIR = DRIVE / "paul_experiments" / "vz_is_paul78_20260818"
UNIVERSE_CSV = DRIVE / "universes" / "VZ_IS_Paul78_universe.csv"
SHEET = 45_000.0
IS_CUT = date(2024, 1, 1)
ALL_STAMP = "260817214643"
DUAL_STAMP = "260817212836"
DUAL_UNIV = DRIVE / "universes" / "VZ_universe.csv"


def _f(v: Any, default: float = 0.0) -> float:
    if v is None or v == "":
        return default
    s = str(v).strip().replace("%", "").replace(",", "").replace("$", "")
    if not s:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _parse_d(s: str) -> Optional[date]:
    s = str(s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


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
            pnl = _f(raw.get("PNL_PCT") or raw.get("PNL %"))
            rows.append(
                {
                    "sym": sym,
                    "opened": opened,
                    "pnl": pnl,
                    "r": _f(raw.get("R_MULT") or raw.get("R_MULTIPLE")),
                    "days": _f(raw.get("DAYS_HELD") or raw.get("DAYS HELD")),
                    "pnl_d": _f(raw.get("PNL_DOLLARS")),
                    "exit": str(raw.get("EXIT_TYPE") or "").strip(),
                }
            )
    return rows


def load_universe_symbols(path: Path) -> list[str]:
    out: list[str] = []
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            s = line.strip().upper()
            if not s or s.startswith("#") or s == "SYMBOL":
                continue
            out.append(s.split(",")[0].strip())
    return out


def book_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {
            "n": 0,
            "wins": 0,
            "wr": 0.0,
            "avg_pnl": 0.0,
            "avg_r": 0.0,
            "pf": 0.0,
            "sheet": 0.0,
            "pnl_d": 0.0,
            "avg_days": 0.0,
            "syms": 0,
        }
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    return {
        "n": n,
        "wins": len(wins),
        "wr": 100.0 * len(wins) / n,
        "avg_pnl": sum(pnls) / n,
        "avg_r": sum(t["r"] for t in trades) / n,
        "pf": (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0),
        "sheet": sum(p / 100.0 * SHEET for p in pnls),
        "pnl_d": sum(t["pnl_d"] for t in trades),
        "avg_days": sum(t["days"] for t in trades) / n,
        "syms": len({t["sym"] for t in trades}),
    }


def split_is_oos(trades: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    is_t = [t for t in trades if t["opened"] < IS_CUT]
    oos_t = [t for t in trades if t["opened"] >= IS_CUT]
    return is_t, oos_t


def is_symbol_summary(is_trades: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(is_trades)
    pnls = [t["pnl"] for t in is_trades]
    wins = [p for p in pnls if p > 0]
    wr = 100.0 * len(wins) / n if n else 0.0
    avg = sum(pnls) / n if n else 0.0
    if n >= 2:
        mx = max(pnls)
        wo = (sum(pnls) - mx) / (n - 1)
    else:
        wo = avg
    sheet = sum(p / 100.0 * SHEET for p in pnls)
    total_pnl_d = sum(t["pnl_d"] for t in is_trades)
    days = [t["days"] for t in is_trades]
    avg_days = sum(days) / n if n else 0.0
    dates = [t["opened"] for t in is_trades]
    span_years = max((max(dates) - min(dates)).days / 365.25, 1.0 / 365.25)
    tpy = n / span_years
    win_sum = sum(wins)
    top = max(wins) if wins else 0.0
    outlier = (100.0 * top / win_sum) if win_sum > 0 else 0.0
    return {
        "TRADES": n,
        "PCT_WINS": wr,
        "TOTAL_PNL": total_pnl_d,
        "SHEET_PNL": sheet,
        "AVG_PNL_PCT": avg,
        "AVG_PNL_PCT_WO_MAX": wo,
        "AVG_TRADES_PER_YEAR": tpy,
        "OUTLIER_PCT_OF_WINS": outlier,
        "AVG_DAYS_HELD": avg_days,
    }


def fmt_n(v: Any, nd: int = 2) -> str:
    if v is None:
        return "—"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(x):
        return "—"
    if nd == 0:
        return f"{x:,.0f}"
    return f"{x:,.{nd}f}"


def fmt_money(v: float) -> str:
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.2f}"


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
  function bind(table, th, col) {
    function onActivate(e) {
      if (e.type === "touchend") e.preventDefault();
      var type = th.getAttribute("data-sort") || "text";
      var cur = th.getAttribute("aria-sort");
      var dir = cur === "ascending" ? "desc" : "asc";
      table.querySelectorAll("th.sortable-th").forEach(function (h) {
        h.classList.remove("sort-asc", "sort-desc");
        h.setAttribute("aria-sort", "none");
      });
      th.classList.add(dir === "asc" ? "sort-asc" : "sort-desc");
      th.setAttribute("aria-sort", dir === "asc" ? "ascending" : "descending");
      sortTable(table, col, type, dir);
    }
    th.addEventListener("click", onActivate);
    th.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onActivate(e); }
    });
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("th.sortable-th").forEach(function (th, col) {
      bind(table, th, col);
    });
  });
})();
</script>
"""


def main() -> int:
    all_trades = load_closed(DRIVE / f"VZ_Closed_{ALL_STAMP}.csv")
    dual_trades = load_closed(DRIVE / f"VZ_Closed_{DUAL_STAMP}.csv")
    dual_syms = set(load_universe_symbols(DUAL_UNIV))

    by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in all_trades:
        by_sym[t["sym"]].append(t)

    is_rows: list[dict[str, Any]] = []
    fields = [
        "SYMBOL",
        "TRADES",
        "PCT_WINS",
        "TOTAL_PNL",
        "SHEET_PNL",
        "AVG_PNL_PCT",
        "AVG_PNL_PCT_WO_MAX",
        "AVG_TRADES_PER_YEAR",
        "OUTLIER_PCT_OF_WINS",
        "AVG_DAYS_HELD",
    ]
    for sym, ts in sorted(by_sym.items()):
        is_t, _ = split_is_oos(ts)
        if not is_t:
            continue
        row = is_symbol_summary(is_t)
        row["SYMBOL"] = sym
        is_rows.append(row)

    apply_paul_scores_to_summary_rows(is_rows, list(fields))
    selected = [r for r in is_rows if int(_f(r.get("PAUL_SCORE"), -1)) >= 7]
    sel_syms = {str(r["SYMBOL"]).upper() for r in selected}
    sel_trades = [t for t in all_trades if t["sym"] in sel_syms]
    dual_slice = [t for t in all_trades if t["sym"] in dual_syms]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    UNIVERSE_CSV.parent.mkdir(parents=True, exist_ok=True)
    with UNIVERSE_CSV.open("w", encoding="utf-8", newline="") as f:
        f.write("# VZ IS-only Paul 7–8 universe — RESEARCH\n")
        f.write("# Paul peer rank on IS trades only (entry < 2024-01-01) from ALL freeze 260817214643\n")
        f.write("# NOT gold / NOT DailyRun. OOS Paul was not used to select names.\n")
        f.write("SYMBOL\n")
        for r in sorted(selected, key=lambda x: (-int(_f(x.get("PAUL_SCORE"))), str(x["SYMBOL"]))):
            f.write(f"{r['SYMBOL']}\n")

    with (OUT_DIR / "is_paul_scores.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=fields + ["PAUL_SCORE"],
            extrasaction="ignore",
        )
        w.writeheader()
        for r in sorted(is_rows, key=lambda x: (-int(_f(x.get("PAUL_SCORE"))), -_f(x.get("SHEET_PNL")))):
            w.writerow(r)

    overlap = sel_syms & dual_syms
    only_is = sel_syms - dual_syms
    only_dual = dual_syms - sel_syms

    books = {
        "ALL (1110 names)": all_trades,
        "DualPaul78 (IS+OOS Paul ≥7)": dual_slice,
        "IS-Paul78 (IS Paul ≥7, no OOS Paul)": sel_trades,
    }
    # Dual live run trades for overlay $ path (same freeze, sleeve capital)
    books["DualPaul78 live run 260817212836"] = dual_trades

    def pack(name: str, trades: list[dict[str, Any]]) -> dict[str, Any]:
        is_t, oos_t = split_is_oos(trades)
        return {
            "name": name,
            "full": book_stats(trades),
            "is": book_stats(is_t),
            "oos": book_stats(oos_t),
        }

    packed = [pack(k, v) for k, v in books.items()]

    # Verdict on trade quality of IS-Paul OOS vs ALL OOS vs Dual OOS
    is_paul = packed[2]
    dual_p = packed[1]
    all_p = packed[0]
    oos_wr_lift = is_paul["oos"]["wr"] - all_p["oos"]["wr"]
    oos_vs_dual = is_paul["oos"]["avg_pnl"] - dual_p["oos"]["avg_pnl"]
    if is_paul["oos"]["n"] < 30:
        verdict = "HOLD"
        why = "OOS N too small to promote."
    elif is_paul["oos"]["wr"] >= all_p["oos"]["wr"] + 3 and is_paul["oos"]["avg_pnl"] >= all_p["oos"]["avg_pnl"] + 0.5:
        if is_paul["oos"]["avg_pnl"] + 0.3 >= dual_p["oos"]["avg_pnl"] and is_paul["oos"]["wr"] + 1.5 >= dual_p["oos"]["wr"]:
            verdict = "KEEP research sleeve"
            why = (
                "IS-only Paul 7–8 still beats ALL on OOS quality. Cleaner than DualPaul78 "
                "(OOS Paul not used to pick names). Not gold / not DailyRun — still an IS winner cut."
            )
        else:
            verdict = "KEEP research sleeve (weaker than DualPaul78 OOS)"
            why = (
                "Beats ALL on OOS so the sleeve is not only OOS-Paul contamination, but DualPaul78 "
                "OOS still looks better — part of Dual’s OOS edge was using OOS Paul."
            )
    elif is_paul["oos"]["wr"] < all_p["oos"]["wr"] or is_paul["oos"]["avg_pnl"] < all_p["oos"]["avg_pnl"]:
        verdict = "DISMISS as a cleaner DualPaul"
        why = "IS-only Paul 7–8 does not beat ALL on OOS — DualPaul78’s OOS strength was largely OOS-Paul selection."
    else:
        verdict = "HOLD"
        why = "OOS lift vs ALL is small; do not retune. Research sleeve only."

    html_path = OUT_DIR / "vz_is_paul78_vs_dual_all.html"

    def metric_rows() -> str:
        specs = [
            ("Names traded", "syms", 0),
            ("Closed N", "n", 0),
            ("Wins", "wins", 0),
            ("Win %", "wr", 1),
            ("Avg PnL %", "avg_pnl", 2),
            ("AvgR", "avg_r", 2),
            ("Profit factor", "pf", 2),
            ("Sheet PnL $", "sheet", -1),
            ("Avg days held", "avg_days", 1),
        ]
        splits = (("full", "Full book"), ("is", "IS (entry < 2024-01-01)"), ("oos", "OOS (entry ≥ 2024-01-01)"))
        chunks = []
        for sk, slabel in splits:
            body = ""
            for label, key, nd in specs:
                body += f"<tr><td>{html_mod.escape(label)}</td>"
                for p in packed:
                    v = p[sk][key]
                    cell = fmt_money(v) if nd < 0 else fmt_n(v, nd)
                    body += f'<td class="num">{cell}</td>'
                body += "</tr>"
            head = sortable_th("Metric", "text") + "".join(
                sortable_th(p["name"], "num") for p in packed
            )
            chunks.append(
                f"<h2>{html_mod.escape(slabel)}</h2>"
                f'<p class="small">Click column headers to sort.</p>'
                f'<table class="sortable"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'
            )
        return "\n".join(chunks)

    name_rows = ""
    score_by = {str(r["SYMBOL"]).upper(): r for r in selected}
    for sym in sorted(sel_syms):
        r = score_by[sym]
        flag = []
        if sym in dual_syms:
            flag.append("also DualPaul78")
        else:
            flag.append("new vs DualPaul78")
        name_rows += (
            "<tr>"
            f"<td>{html_mod.escape(sym)}</td>"
            f'<td class="num">{int(_f(r.get("PAUL_SCORE")))}</td>'
            f'<td class="num">{int(_f(r.get("TRADES")))}</td>'
            f'<td class="num">{fmt_n(r.get("PCT_WINS"), 1)}</td>'
            f'<td class="num">{fmt_n(r.get("AVG_PNL_PCT"), 2)}</td>'
            f"<td>{html_mod.escape(', '.join(flag))}</td>"
            "</tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>VZ IS-only Paul 7–8 vs DualPaul78 vs ALL</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 24px; color: #1a1a1a; max-width: 1400px; }}
h1 {{ font-size: 1.35rem; margin: 0 0 8px; }}
h2 {{ font-size: 1.1rem; margin: 28px 0 8px; }}
.sub, .small {{ color: #555; line-height: 1.45; }}
.badge {{ display: inline-block; padding: 4px 10px; border-radius: 4px; font-weight: 600; }}
.card {{ background: #f7f8fa; border: 1px solid #e2e5ea; padding: 12px 14px; border-radius: 6px; margin: 12px 0; }}
table.sortable {{ border-collapse: collapse; width: 100%; font-size: 0.88rem; margin: 8px 0 16px; }}
table.sortable th, table.sortable td {{ border-bottom: 1px solid #e5e7eb; padding: 6px 8px; text-align: left; }}
table.sortable th {{ background: #f0f2f5; }}
td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
th.sortable-th {{ cursor: pointer; user-select: none; white-space: nowrap; }}
th.sortable-th:hover {{ background: #e4e4dc; }}
.sort-ind {{ display: inline-block; width: 0.9em; margin-left: 4px; color: #94a3b8; font-size: 10px; }}
th.sort-asc .sort-ind::after {{ content: "▲"; color: #334155; }}
th.sort-desc .sort-ind::after {{ content: "▼"; color: #334155; }}
code {{ background: #eee; padding: 1px 4px; border-radius: 3px; }}
</style>
</head>
<body>
<h1>VZ universe: IS-only Paul 7–8 (no OOS Paul)</h1>
<p class="sub">Frozen knobs = ALL stamp <code>{ALL_STAMP}</code> (<code>EXIT_atr4_s025_r15</code>).
Paul 0–8 is recomputed on <strong>IS trades only</strong> (entry &lt; 2024-01-01), peer ranks among every ALL name with IS trades.
Names with IS Paul ≥ 7 are kept. <code>PAUL_SCORE_OOS</code> is not used. Click column headers to sort.</p>
<div class="card">
<strong>Verdict: {html_mod.escape(verdict)}</strong>
<p>{html_mod.escape(why)}</p>
<p>IS-Paul names: <strong>{len(sel_syms)}</strong> &nbsp; DualPaul78: <strong>{len(dual_syms)}</strong> &nbsp;
overlap: <strong>{len(overlap)}</strong> &nbsp; IS-only not in Dual: <strong>{len(only_is)}</strong> &nbsp;
Dual not in IS-Paul: <strong>{len(only_dual)}</strong></p>
<p>OOS WR lift vs ALL: {oos_wr_lift:+.1f}pp &nbsp; OOS Avg PnL vs DualPaul78 slice: {oos_vs_dual:+.2f}pp</p>
</div>
<p>This is still an <strong>IS winner cut</strong> of the VZ book — cleaner than DualPaul78 (which required OOS Paul ≥ 7 too),
but not a trait universe (liquidity/ADR/listing). Trade-level stats below slice the ALL Closed file (same fills as a re-run).
Sleeve Ann ROR / Max DD need <code>run_vz.bat {UNIVERSE_CSV.as_posix()}</code> because aggressive overlay changes when other names are absent.</p>
<p>Universe file: <code>{UNIVERSE_CSV.relative_to(ROOT).as_posix()}</code></p>
{metric_rows()}
<h2>IS-Paul ≥7 names</h2>
<p class="small">Paul score is IS-only peer rank. Click headers to sort.</p>
<table class="sortable"><thead><tr>
{sortable_th("Symbol", "text")}
{sortable_th("IS Paul", "num")}
{sortable_th("IS trades", "num")}
{sortable_th("IS WR %", "num")}
{sortable_th("IS Avg PnL %", "num")}
{sortable_th("vs DualPaul78", "text")}
</tr></thead><tbody>{name_rows}</tbody></table>
{SORT_JS}
</body>
</html>
"""
    html_path.write_text(html, encoding="utf-8")
    print(f"IS names with trades: {len(is_rows)}")
    print(f"IS Paul >=7: {len(sel_syms)}")
    print(f"DualPaul78: {len(dual_syms)} overlap={len(overlap)} only_is={len(only_is)} only_dual={len(only_dual)}")
    print(f"IS-Paul full N={is_paul['full']['n']} WR={is_paul['full']['wr']:.1f} avg={is_paul['full']['avg_pnl']:.2f}")
    print(f"IS-Paul IS  N={is_paul['is']['n']} WR={is_paul['is']['wr']:.1f} avg={is_paul['is']['avg_pnl']:.2f}")
    print(f"IS-Paul OOS N={is_paul['oos']['n']} WR={is_paul['oos']['wr']:.1f} avg={is_paul['oos']['avg_pnl']:.2f}")
    print(f"ALL     OOS N={all_p['oos']['n']} WR={all_p['oos']['wr']:.1f} avg={all_p['oos']['avg_pnl']:.2f}")
    print(f"Dual    OOS N={dual_p['oos']['n']} WR={dual_p['oos']['wr']:.1f} avg={dual_p['oos']['avg_pnl']:.2f}")
    print(f"VERDICT {verdict}")
    print(f"HTML {html_path}")
    print(f"UNIVERSE {UNIVERSE_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
