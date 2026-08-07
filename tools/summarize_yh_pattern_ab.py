#!/usr/bin/env python3
"""Summarize YH pattern A/B suites (false_start / post_target / fat_stops).

Writes comparison.csv + comparison.html under the suite root.
Also prints a console table.

Usage:
  python tools/summarize_yh_pattern_ab.py --suite false_start
  python tools/summarize_yh_pattern_ab.py --suite post_target --root drive/paul_experiments/yh_post_target_ab
  python tools/summarize_yh_pattern_ab.py --suite fat_stops
"""
from __future__ import annotations

import argparse
import csv
import html
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
DRIVE = REPO / "drive"

DEFAULT_ROOTS = {
    "false_start": DRIVE / "paul_experiments" / "yh_false_start_ab",
    "post_target": DRIVE / "paul_experiments" / "yh_post_target_ab",
    "fat_stops": DRIVE / "paul_experiments" / "yh_fat_stops_ab",
}

SUITE_TITLES = {
    "false_start": "YH false_start_2022_2023 A/B",
    "post_target": "YH post_target_quick_stop A/B",
    "fat_stops": "YH fat_stops A/B",
}

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
    var ths = table.querySelectorAll("th.sortable-th");
    ths.forEach(function (th, idx) {
      function activate() {
        var type = th.getAttribute("data-sort") || "text";
        var asc = !th.classList.contains("sort-asc");
        ths.forEach(function (x) {
          x.classList.remove("sort-asc", "sort-desc");
          x.setAttribute("aria-sort", "none");
        });
        th.classList.add(asc ? "sort-asc" : "sort-desc");
        th.setAttribute("aria-sort", asc ? "ascending" : "descending");
        sortTable(table, idx, type, asc ? 1 : -1);
      }
      th.addEventListener("click", activate);
      th.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activate(); }
      });
    });
  }
  document.querySelectorAll("table.sortable").forEach(bind);
})();
</script>
"""


def _safe_num(x: Any) -> float:
    if x is None or x == "" or str(x).strip().upper() == "N/A":
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace("%", "").replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def _latest(outdir: Path, pattern: str) -> Optional[Path]:
    files = sorted(outdir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{html.escape(sort_type)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _closed_year(row: dict[str, str]) -> int:
    raw = str(row.get("DATE_CLOSED") or row.get("DATE CLOSED") or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) >= 4 and digits[:4].isdigit():
        return int(digits[:4])
    return 0


def pattern_counts(closed: Path, suite: str) -> dict[str, float]:
    out = {
        "fs15_n": 0,
        "fs15_pnl": 0.0,
        "ptqs_n": 0,
        "fat_n": 0,
        "fat_pnl": 0.0,
    }
    if not closed.is_file():
        return out
    rows: list[dict[str, str]] = []
    with closed.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        rows = list(csv.DictReader(f))
    by_sym: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        sym = str(r.get("SYMBOL") or "").strip().upper()
        if not sym:
            continue
        by_sym.setdefault(sym, []).append(r)
    for sym, trades in by_sym.items():
        trades.sort(
            key=lambda r: (
                str(r.get("DATE_OPENED") or r.get("DATE OPENED") or ""),
                str(r.get("DATE_CLOSED") or r.get("DATE CLOSED") or ""),
            )
        )
        for i, r in enumerate(trades):
            et = str(r.get("EXIT_TYPE") or r.get("EXIT TYPE") or "").upper()
            days = int(_safe_num(r.get("DAYS_HELD", r.get("DAYS HELD", 0))))
            pnl_pct = _safe_num(r.get("PNL_PCT", r.get("PNL %", 0)))
            pnl_usd = _safe_num(r.get("PNL_DOLLARS", r.get("PNL", 0)))
            year = _closed_year(r)
            if "STOP" in et and year in (2022, 2023) and days <= 15 and pnl_pct < 0:
                out["fs15_n"] += 1
                out["fs15_pnl"] += pnl_usd
            if "STOP" in et and pnl_pct <= -12:
                out["fat_n"] += 1
                out["fat_pnl"] += pnl_usd
            if i + 1 < len(trades):
                nxt = trades[i + 1]
                nxt_et = str(nxt.get("EXIT_TYPE") or nxt.get("EXIT TYPE") or "").upper()
                nxt_days = int(_safe_num(nxt.get("DAYS_HELD", nxt.get("DAYS HELD", 0))))
                if "TARGET" in et and "STOP" in nxt_et and nxt_days <= 10:
                    out["ptqs_n"] += 1
    return out


def extract_metrics(arm_dir: Path) -> Optional[dict[str, Any]]:
    report = _latest(arm_dir, "YH_Report_*.csv") or _latest(arm_dir, "YH_Summary_*.csv")
    if not report:
        return None
    with report.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return None
    row = rows[0]
    wins = int(_safe_num(row.get("Wins", row.get("Winners", 0))))
    losses = int(_safe_num(row.get("Losses", row.get("Losers", 0))))
    bes = int(_safe_num(row.get("BEs", row.get("BE", 0))))
    trades = int(_safe_num(row.get("Total_Trades")))
    if trades <= 0:
        trades = wins + losses + bes
    wr = _safe_num(row.get("Pct_Wins"))
    if wr == 0.0 and trades:
        wr = 100.0 * wins / trades
    stamp = ""
    m = re.search(r"_(\d{12})\.csv$", report.name)
    if m:
        stamp = m.group(1)
    closed = _latest(arm_dir, "YH_Closed_*.csv")
    return {
        "stamp": stamp,
        "report": report.name,
        "trades": trades,
        "wr": wr,
        "avg_pnl_pct": _safe_num(row.get("Avg_PNL_Pct")),
        "ann_ror": _safe_num(row.get("Ann_ROR")),
        "pnl": _safe_num(row.get("Total_PNL")),
        "max_dd": _safe_num(row.get("Max_DD")),
        "pf": _safe_num(row.get("Profit_Factor")),
        "closed": closed,
    }


def lean_verdict(suite: str, arm: str, m: dict[str, Any], ctrl: dict[str, Any], pat: dict[str, float], ctrl_pat: dict[str, float]) -> tuple[str, str]:
    if arm.startswith("01_control") or arm == "00_control":
        return "control", "Baseline Mag9 (no TSLA) run_yh.bat levers."
    d_ann = float(m.get("ann_ror", 0)) - float(ctrl.get("ann_ror", 0))
    d_pnl = float(m.get("pnl", 0)) - float(ctrl.get("pnl", 0))
    d_dd = float(m.get("max_dd", 0)) - float(ctrl.get("max_dd", 0))
    if suite == "false_start":
        d_fs = int(pat.get("fs15_n", 0)) - int(ctrl_pat.get("fs15_n", 0))
        if "start_" in arm and d_pnl < -0.05 * abs(float(ctrl.get("pnl", 1)) or 1):
            return (
                "dismiss",
                f"Truncates entry history (Δ trades={int(m.get('trades', 0)) - int(ctrl.get('trades', 0))}); "
                f"FS15 Δ={d_fs} but Absolute Total_PNL collapses (ΔPnL={d_pnl:+.0f}) — not a usable regime filter.",
            )
        if d_fs < 0 and d_ann >= -1.0 and d_pnl >= -0.05 * abs(float(ctrl.get("pnl", 1)) or 1):
            return "hold", f"Cuts FS15 ({d_fs}) with tolerable Ann_ROR/PnL; needs ToS before adopt."
        if d_ann < -1.5 or d_pnl < -0.08 * abs(float(ctrl.get("pnl", 1)) or 1):
            return "dismiss", f"Hurts portfolio (ΔAnn_ROR={d_ann:+.2f}, ΔPnL={d_pnl:+.0f}); FS15 Δ={d_fs}."
        if d_fs >= 0 and (d_ann < 0 or d_pnl < 0):
            return "dismiss", f"Does not reduce false-starts (FS15 Δ={d_fs}) and not better on Ann_ROR/PnL."
        return "hold", f"Mixed: FS15 Δ={d_fs}, ΔAnn_ROR={d_ann:+.2f}, ΔPnL={d_pnl:+.0f}."
    if suite == "post_target":
        d_pt = int(pat.get("ptqs_n", 0)) - int(ctrl_pat.get("ptqs_n", 0))
        if d_pt < 0 and d_ann >= -1.0 and d_dd <= 1.0:
            return "hold", f"Fewer PTQS ({d_pt}) without large Ann_ROR/DD hit; ToS gate before adopt."
        if d_ann < -1.5 or d_pnl < -0.08 * abs(float(ctrl.get("pnl", 1)) or 1):
            return "dismiss", f"Cuts quality or size too hard (ΔAnn_ROR={d_ann:+.2f}, ΔPnL={d_pnl:+.0f}); PTQS Δ={d_pt}."
        if d_pt >= 0:
            return "dismiss", f"Does not cut post-TARGET quick stops (PTQS Δ={d_pt})."
        return "hold", f"PTQS Δ={d_pt}, ΔAnn_ROR={d_ann:+.2f}, ΔPnL={d_pnl:+.0f}."
    # fat_stops
    d_fat = int(pat.get("fat_n", 0)) - int(ctrl_pat.get("fat_n", 0))
    if d_fat < 0 and d_ann >= -1.0 and d_pnl >= -0.05 * abs(float(ctrl.get("pnl", 1)) or 1):
        return "hold", f"Fewer fat stops ({d_fat}) with tolerable Ann_ROR/PnL; conflicts with expand-stop peer lean — ToS."
    if d_ann < -1.5 or d_pnl < -0.08 * abs(float(ctrl.get("pnl", 1)) or 1):
        return "dismiss", f"Tighter/time-stop hurts (ΔAnn_ROR={d_ann:+.2f}, ΔPnL={d_pnl:+.0f}); fat Δ={d_fat}."
    if d_fat >= 0:
        return "dismiss", f"Does not reduce fat stops (Δ={d_fat})."
    return "hold", f"fat Δ={d_fat}, ΔAnn_ROR={d_ann:+.2f}, ΔPnL={d_pnl:+.0f}."


def summarize(suite: str, root: Path) -> Path:
    arms = sorted([p for p in root.iterdir() if p.is_dir()], key=lambda p: p.name)
    rows: list[dict[str, Any]] = []
    for arm_dir in arms:
        m = extract_metrics(arm_dir)
        if not m:
            rows.append({"arm": arm_dir.name, "ok": False})
            continue
        pat = pattern_counts(m["closed"], suite) if m.get("closed") else {}
        rows.append({"arm": arm_dir.name, "ok": True, "metrics": m, "pattern": pat})

    ctrl = next((r for r in rows if r.get("ok") and r["arm"].startswith("01_")), None)
    cm = (ctrl or {}).get("metrics") or {}
    cp = (ctrl or {}).get("pattern") or {}

    # Console
    print(f"\n=== {SUITE_TITLES.get(suite, suite)} ===")
    print(f"root={root}")
    hdr = f"{'arm':24} {'trades':>7} {'WR%':>6} {'Ann_ROR':>8} {'Total_PNL':>12} {'Max_DD':>7} {'FS15':>5} {'PTQS':>5} {'FAT':>5} {'lean':>8}"
    print(hdr)
    print("-" * len(hdr))
    out_rows: list[dict[str, Any]] = []
    for r in rows:
        if not r.get("ok"):
            print(f"{r['arm']:24}  — missing report")
            continue
        m = r["metrics"]
        p = r["pattern"]
        lean, why = lean_verdict(suite, r["arm"], m, cm, p, cp)
        print(
            f"{r['arm']:24} {int(m['trades']):7d} {float(m['wr']):6.1f} "
            f"{float(m['ann_ror']):8.2f} {float(m['pnl']):12.0f} {float(m['max_dd']):7.2f} "
            f"{int(p.get('fs15_n', 0)):5d} {int(p.get('ptqs_n', 0)):5d} {int(p.get('fat_n', 0)):5d} {lean:>8}"
        )
        out_rows.append(
            {
                "arm": r["arm"],
                "stamp": m.get("stamp", ""),
                "trades": int(m["trades"]),
                "wr": float(m["wr"]),
                "avg_pnl_pct": float(m.get("avg_pnl_pct", 0)),
                "ann_ror": float(m["ann_ror"]),
                "pnl": float(m["pnl"]),
                "max_dd": float(m["max_dd"]),
                "fs15_n": int(p.get("fs15_n", 0)),
                "ptqs_n": int(p.get("ptqs_n", 0)),
                "fat_n": int(p.get("fat_n", 0)),
                "d_trades": int(m["trades"]) - int(cm.get("trades", 0) or 0),
                "d_ann_ror": float(m["ann_ror"]) - float(cm.get("ann_ror", 0) or 0),
                "d_pnl": float(m["pnl"]) - float(cm.get("pnl", 0) or 0),
                "d_dd": float(m["max_dd"]) - float(cm.get("max_dd", 0) or 0),
                "lean": lean,
                "why": why,
            }
        )

    root.mkdir(parents=True, exist_ok=True)
    csv_path = root / "comparison.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "arm", "stamp", "trades", "wr", "avg_pnl_pct", "ann_ror", "pnl", "max_dd",
                "fs15_n", "ptqs_n", "fat_n", "d_trades", "d_ann_ror", "d_pnl", "d_dd", "lean", "why",
            ],
        )
        w.writeheader()
        for row in out_rows:
            w.writerow(row)

    # HTML
    ths = "".join(
        [
            _sortable_th("Arm", "text"),
            _sortable_th("Stamp", "text"),
            _sortable_th("Trades", "num"),
            _sortable_th("WR%", "num"),
            _sortable_th("Avg%", "num"),
            _sortable_th("Ann_ROR", "num"),
            _sortable_th("Total_PNL", "num"),
            _sortable_th("Max_DD", "num"),
            _sortable_th("FS15", "num"),
            _sortable_th("PTQS", "num"),
            _sortable_th("FAT", "num"),
            _sortable_th("Δ Ann_ROR", "num"),
            _sortable_th("Δ PnL", "num"),
            _sortable_th("Lean", "text"),
            _sortable_th("Why", "text"),
        ]
    )
    body = []
    for row in out_rows:
        body.append(
            "<tr>"
            f"<td><code>{html.escape(row['arm'])}</code></td>"
            f"<td>{html.escape(str(row['stamp']))}</td>"
            f"<td>{row['trades']}</td>"
            f"<td>{row['wr']:.1f}</td>"
            f"<td>{row['avg_pnl_pct']:.2f}</td>"
            f"<td>{row['ann_ror']:.2f}</td>"
            f"<td>{row['pnl']:.0f}</td>"
            f"<td>{row['max_dd']:.2f}</td>"
            f"<td>{row['fs15_n']}</td>"
            f"<td>{row['ptqs_n']}</td>"
            f"<td>{row['fat_n']}</td>"
            f"<td>{row['d_ann_ror']:+.2f}</td>"
            f"<td>{row['d_pnl']:+.0f}</td>"
            f"<td><strong>{html.escape(row['lean'])}</strong></td>"
            f"<td>{html.escape(row['why'])}</td>"
            "</tr>"
        )
    title = SUITE_TITLES.get(suite, suite)
    html_doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html.escape(title)}</title>
<style>
body {{ margin:0; padding:28px; font-family:"Segoe UI",Georgia,serif; background:#fafaf8; color:#1a1a18; }}
.wrap {{ max-width:1400px; margin:0 auto; }}
h1 {{ font-size:1.5rem; }}
.muted {{ color:#5c5c56; }}
table.sortable {{ border-collapse:collapse; width:100%; font-size:13px; }}
table.sortable th, table.sortable td {{ border:1px solid #d8d8d0; padding:6px 8px; vertical-align:top; }}
table.sortable th {{ background:#f0f0ea; }}
code {{ font-size:12px; }}
{SORTABLE_TH_CSS}
</style></head><body><div class="wrap">
<h1>{html.escape(title)}</h1>
<p class="muted">Mag9 without TSLA. Click column headers to sort. Generated {html.escape(datetime.now().strftime("%Y-%m-%d %H:%M"))}.
FS15 = 2022–23 STOP ≤15d PNL&lt;0; PTQS = TARGET→STOP≤10d; FAT = STOP PNL%≤−12.</p>
<table class="sortable"><thead><tr>{ths}</tr></thead><tbody>
{"".join(body)}
</tbody></table>
</div>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    html_path = root / "comparison.html"
    html_path.write_text(html_doc, encoding="utf-8")
    print(f"Wrote {csv_path}")
    print(f"Wrote {html_path}")
    return html_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", required=True, choices=sorted(DEFAULT_ROOTS.keys()))
    ap.add_argument("--root", default="")
    args = ap.parse_args()
    root = Path(args.root) if args.root.strip() else DEFAULT_ROOTS[args.suite]
    if not root.is_absolute():
        root = REPO / root
    if not root.is_dir():
        raise SystemExit(f"Missing suite root: {root}")
    summarize(args.suite, root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
