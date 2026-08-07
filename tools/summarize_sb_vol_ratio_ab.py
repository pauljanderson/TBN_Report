#!/usr/bin/env python3
"""Compare SB Vol≥k×50d-avg A/B arms under ab_vol_ratio/.

Reads latest SB_Audit_Report_*.csv (+ Closed for avg PnL%) per arm folder.
Writes comparison.html + README.md (and prints a table).

Usage:
  python tools/summarize_sb_vol_ratio_ab.py
  python tools/summarize_sb_vol_ratio_ab.py --root drive/paul_experiments/tbn_new_systems/stockbee_momentum_burst/ab_vol_ratio
"""
from __future__ import annotations

import argparse
import csv
import html
import sys
from pathlib import Path
from typing import Any, Optional

CONTROL_ARM = "00_control"
ARM_ORDER = (
    "00_control",
    "01_vol_1_25",
    "02_vol_1_5",
    "03_vol_1_75",
    "04_vol_2_0",
    "05_vol_2_5",
)

SORTABLE_TH_CSS = """
th.sortable-th{cursor:pointer;user-select:none;white-space:nowrap}
th.sortable-th .sort-ind{opacity:.45;margin-left:.25em;font-size:.85em}
th.sortable-th.sort-asc .sort-ind::after{content:"▲";opacity:1}
th.sortable-th.sort-desc .sort-ind::after{content:"▼";opacity:1}
"""

SORTABLE_TABLE_SCRIPT = """
(function(){
  function parseCell(td, type){
    var t=(td.textContent||"").trim().replace(/[$,%]/g,"").replace(/,/g,"");
    if(type==="num"){var n=parseFloat(t); return isNaN(n)?null:n;}
    if(type==="date"||type==="month"){return t;}
    return t.toLowerCase();
  }
  function bind(table){
    var ths=table.querySelectorAll("th.sortable-th");
    ths.forEach(function(th, colIdx){
      th.addEventListener("click", function(){
        var type=th.getAttribute("data-sort")||"text";
        var asc=!th.classList.contains("sort-asc");
        ths.forEach(function(x){x.classList.remove("sort-asc","sort-desc"); x.setAttribute("aria-sort","none");});
        th.classList.add(asc?"sort-asc":"sort-desc");
        th.setAttribute("aria-sort", asc?"ascending":"descending");
        var tbody=table.tBodies[0]; if(!tbody) return;
        var rows=[].slice.call(tbody.querySelectorAll("tr")).filter(function(r){return !r.classList.contains("total-row");});
        rows.sort(function(a,b){
          var av=parseCell(a.children[colIdx], type), bv=parseCell(b.children[colIdx], type);
          if(av==null&&bv==null) return 0;
          if(av==null) return 1; if(bv==null) return -1;
          if(av<bv) return asc?-1:1; if(av>bv) return asc?1:-1; return 0;
        });
        rows.forEach(function(r){tbody.appendChild(r);});
      });
      th.addEventListener("keydown", function(e){
        if(e.key==="Enter"||e.key===" "){e.preventDefault(); th.click();}
      });
    });
  }
  document.querySelectorAll("table.sortable").forEach(bind);
})();
"""


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{html.escape(sort_type)}" '
        f'tabindex="0" role="columnheader" aria-sort="none">'
        f"{html.escape(label)}<span class=\"sort-ind\"></span></th>"
    )


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


def _read_stamp(arm_dir: Path) -> str:
    p = arm_dir / "STAMP.txt"
    if p.exists():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("stamp="):
                return line.split("=", 1)[1].strip()
    aud = _latest(arm_dir, "SB_Audit_Report_*.csv")
    if aud:
        name = aud.stem
        parts = name.split("_")
        if len(parts) >= 4:
            return parts[-1]
    return ""


def _arm_metrics(arm_dir: Path) -> dict[str, Any]:
    aud = _latest(arm_dir, "SB_Audit_Report_*.csv")
    closed = _latest(arm_dir, "SB_Closed_*.csv")
    out: dict[str, Any] = {
        "arm": arm_dir.name,
        "stamp": _read_stamp(arm_dir),
        "trades": 0,
        "wins": 0,
        "wr": 0.0,
        "pnl": 0.0,
        "avg_pnl_pct": 0.0,
        "max_dd": 0.0,
        "agg_pnl": 0.0,
        "agg_dd": 0.0,
        "rej_vol": 0,
        "ok": False,
    }
    if aud and aud.exists():
        with aud.open(newline="", encoding="utf-8-sig", errors="replace") as f:
            row = next(csv.DictReader(f), None)
        if row:
            out["ok"] = True
            out["trades"] = int(_safe_num(row.get("Total_Trades")))
            out["wins"] = int(_safe_num(row.get("Wins")))
            losses = int(_safe_num(row.get("Losses")))
            bes = int(_safe_num(row.get("BEs")))
            tot = out["wins"] + losses + bes
            out["wr"] = (100.0 * out["wins"] / tot) if tot else _safe_num(row.get("Pct_Wins"))
            out["pnl"] = _safe_num(row.get("Total_PNL"))
            out["avg_pnl_pct"] = _safe_num(row.get("Avg_PNL_Pct"))
            out["max_dd"] = _safe_num(row.get("Max_DD"))
            out["agg_pnl"] = _safe_num(row.get("Aggressive_Total_PNL"))
            out["agg_dd"] = _safe_num(row.get("Aggressive_Max_DD"))
            out["rej_vol"] = int(_safe_num(row.get("sb_rejected_vol_vs_avg")))
    if closed and closed.exists() and (out["avg_pnl_pct"] == 0.0 or not aud):
        pnls = []
        with closed.open(newline="", encoding="utf-8-sig", errors="replace") as f:
            for r in csv.DictReader(f):
                pnls.append(_safe_num(r.get("PNL_PCT")))
        if pnls:
            out["avg_pnl_pct"] = sum(pnls) / len(pnls)
            if not out["trades"]:
                out["trades"] = len(pnls)
                out["wins"] = sum(1 for p in pnls if p > 0)
                out["wr"] = 100.0 * out["wins"] / len(pnls)
                out["ok"] = True
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--root",
        default="drive/paul_experiments/tbn_new_systems/stockbee_momentum_burst/ab_vol_ratio",
    )
    args = ap.parse_args()
    root = Path(args.root)
    if not root.is_absolute():
        root = Path.cwd() / root
    root.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for name in ARM_ORDER:
        d = root / name
        if d.is_dir():
            rows.append(_arm_metrics(d))
    for d in sorted(root.iterdir()):
        if d.is_dir() and d.name not in ARM_ORDER and d.name[0:1].isdigit():
            rows.append(_arm_metrics(d))

    ctrl = next((r for r in rows if r["arm"] == CONTROL_ARM), None)

    hdr = (
        f"{'arm':16} {'stamp':14} {'trades':>7} {'WR%':>6} {'PnL$':>12} "
        f"{'avgPnL%':>8} {'MaxDD':>7} {'dPnL$':>12} {'rejVol':>7}"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        d_pnl = (r["pnl"] - ctrl["pnl"]) if ctrl and ctrl["ok"] and r["ok"] else 0.0
        print(
            f"{r['arm']:16} {r['stamp']:14} {r['trades']:7d} {r['wr']:6.1f} {r['pnl']:12.0f} "
            f"{r['avg_pnl_pct']:8.2f} {r['max_dd']:7.2f} {d_pnl:12.0f} {r['rej_vol']:7d}"
        )

    md_lines = [
        "# SB A/B — Vol ≥ k× prior 50d average",
        "",
        "StockBee Momentum Burst (SB) participation gate vs current control.",
        "Host sizing (`run_stockbee_burst.bat` defaults). Production bats unchanged.",
        "",
        "## Gate semantics",
        "",
        "- **`VOL_VS_50`** — Volume_T / mean(Volume of prior `burst_vol_avg_lookback` "
        "sessions) (default lookback **50**; **excludes** signal bar T).",
        "- **Gate** — when `burst_vol_vs_avg_mult > 0`, require "
        "`VOL_VS_50 >= burst_vol_vs_avg_mult`. Missing / undefined MA → reject "
        "(fail closed). `0` = off.",
        "- **Not** the Closed DNA column `VOL_RATIO` (= `V[T]/V[T−1]` day-vs-prior). "
        "Keep `burst_vol_gt_prior=true` unless AB says otherwise.",
        "",
        "## Arms",
        "",
        "| Arm | Extra `-v` |",
        "|---|---|",
        "| `00_control` | (none — mult=0 / off) |",
        "| `01_vol_1_25` | `burst_vol_vs_avg_mult=1.25` |",
        "| `02_vol_1_5` | `burst_vol_vs_avg_mult=1.5` |",
        "| `03_vol_1_75` | `burst_vol_vs_avg_mult=1.75` |",
        "| `04_vol_2_0` | `burst_vol_vs_avg_mult=2.0` |",
        "| `05_vol_2_5` | `burst_vol_vs_avg_mult=2.5` |",
        "",
        "## Results",
        "",
        "Click column headers to sort (HTML). Deltas vs `00_control`.",
        "",
        "| Arm | Stamp | Trades | WR% | Total PnL $ | Avg PnL% | Max DD | "
        "Δ PnL $ | Δ Trades | rej Vol | Agg PnL $ | Agg Max DD |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        d_pnl = (r["pnl"] - ctrl["pnl"]) if ctrl and ctrl["ok"] and r["ok"] else 0.0
        d_tr = (r["trades"] - ctrl["trades"]) if ctrl and ctrl["ok"] and r["ok"] else 0
        md_lines.append(
            f"| `{r['arm']}` | `{r['stamp']}` | {r['trades']} | {r['wr']:.1f} | "
            f"{r['pnl']:.0f} | {r['avg_pnl_pct']:.2f} | {r['max_dd']:.2f} | "
            f"{d_pnl:+.0f} | {d_tr:+d} | {r['rej_vol']} | "
            f"{r['agg_pnl']:.0f} | {r['agg_dd']:.2f} |"
        )

    winner = None
    if ctrl and ctrl["ok"]:
        cands = [r for r in rows if r["ok"] and r["arm"] != CONTROL_ARM]
        if cands:
            winner = max(cands, key=lambda r: r["pnl"])
            beat = winner["pnl"] > ctrl["pnl"]
            md_lines.extend(
                [
                    "",
                    "## Verdict",
                    "",
                    f"- Control PnL: **{ctrl['pnl']:.0f}** ({ctrl['trades']} trades, "
                    f"WR {ctrl['wr']:.1f}%, avg PnL% {ctrl['avg_pnl_pct']:.2f}).",
                    f"- Best gated arm by Total PnL: **`{winner['arm']}`** "
                    f"({winner['pnl']:.0f}, Δ {winner['pnl'] - ctrl['pnl']:+.0f}).",
                    (
                        "- **Beats control** on Total PnL."
                        if beat
                        else "- Does **not** beat control on Total PnL "
                        "(check avg PnL% / DD / trade-count tradeoffs)."
                    ),
                    "",
                    "## Re-run",
                    "",
                    "```bat",
                    "SB_Vol_ab.bat",
                    "SB_Vol_ab.bat HROW,REAL,AKR",
                    "set SB_SYMBOLS=... && SB_Vol_ab.bat",
                    "```",
                    "",
                    "Canonical: `run_sb_ab_vol_ratio.bat`. "
                    "Edit `VOL_RATIO_*` / `RUN_*` at top of that file.",
                ]
            )

    md_path = root / "README.md"
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    body_rows = []
    for r in rows:
        d_pnl = (r["pnl"] - ctrl["pnl"]) if ctrl and ctrl["ok"] and r["ok"] else 0.0
        d_tr = (r["trades"] - ctrl["trades"]) if ctrl and ctrl["ok"] and r["ok"] else 0
        body_rows.append(
            "<tr>"
            f"<td>{html.escape(r['arm'])}</td>"
            f"<td>{html.escape(r['stamp'])}</td>"
            f"<td class='num'>{r['trades']}</td>"
            f"<td class='num'>{r['wr']:.1f}</td>"
            f"<td class='num'>{r['pnl']:.0f}</td>"
            f"<td class='num'>{r['avg_pnl_pct']:.2f}</td>"
            f"<td class='num'>{r['max_dd']:.2f}</td>"
            f"<td class='num'>{d_pnl:+.0f}</td>"
            f"<td class='num'>{d_tr:+d}</td>"
            f"<td class='num'>{r['rej_vol']}</td>"
            f"<td class='num'>{r['agg_pnl']:.0f}</td>"
            f"<td class='num'>{r['agg_dd']:.2f}</td>"
            "</tr>"
        )
    verdict = ""
    if winner and ctrl:
        verdict = (
            f"<p><strong>Winner vs control (Total PnL):</strong> "
            f"<code>{html.escape(winner['arm'])}</code> "
            f"({winner['pnl']:.0f} vs {ctrl['pnl']:.0f}, "
            f"Δ {winner['pnl'] - ctrl['pnl']:+.0f}).</p>"
        )
    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>SB A/B — Vol ≥ k× 50d avg</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:1.5rem;line-height:1.45;color:#1a1a1a}}
h1{{font-size:1.4rem}} h2{{font-size:1.1rem;margin-top:1.5rem}}
table{{border-collapse:collapse;width:100%;margin:1rem 0;font-size:.92rem}}
th,td{{border:1px solid #ccc;padding:.4rem .55rem;text-align:left}}
th{{background:#f3f3f3}}
td.num{{text-align:right;font-variant-numeric:tabular-nums}}
.note{{color:#444;max-width:56rem}}
code{{background:#f5f5f5;padding:.1em .3em;border-radius:3px}}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>SB A/B — Vol ≥ k× prior 50d average</h1>
<p class="note">Gold universe (default), host sizing.
<code>VOL_VS_50 = V[T] / mean(prior 50 sessions)</code>; gate
<code>burst_vol_vs_avg_mult</code> (0=off). Distinct from DNA
<code>VOL_RATIO</code> (day vs prior day). Production bats unchanged.
Click column headers to sort.</p>
{verdict}
<table class="sortable">
<thead><tr>
{sortable_th("Arm", "text")}
{sortable_th("Stamp", "text")}
{sortable_th("Trades", "num")}
{sortable_th("WR%", "num")}
{sortable_th("Total PnL $", "num")}
{sortable_th("Avg PnL%", "num")}
{sortable_th("Max DD", "num")}
{sortable_th("Δ PnL $", "num")}
{sortable_th("Δ Trades", "num")}
{sortable_th("rej Vol", "num")}
{sortable_th("Agg PnL $", "num")}
{sortable_th("Agg Max DD", "num")}
</tr></thead>
<tbody>
{"".join(body_rows)}
</tbody>
</table>
<p class="note">Re-run: <code>SB_Vol_ab.bat</code> (or <code>run_sb_ab_vol_ratio.bat</code>)</p>
<script>
{SORTABLE_TABLE_SCRIPT}
</script>
</body>
</html>
"""
    html_path = root / "comparison.html"
    html_path.write_text(html_doc, encoding="utf-8")
    print(f"\nWrote {md_path}")
    print(f"Wrote {html_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
