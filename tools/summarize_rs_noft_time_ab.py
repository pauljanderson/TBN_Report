#!/usr/bin/env python3
"""Compare RS NO_FT + TIME A/B arms under rs_noft_time_ab/.

Reads latest RS_Audit_Report_*.csv (fallback RS_Report_*.csv) per arm folder.
House metric names from Audit Summary:
  Total_Trades, Pct_Wins, Avg_PNL_Pct, Ann_ROR, Avg_Days_Held, Total_PNL,
  Max_DD, Losing_Streak, P90_Days, brt_cash, Max_Positions

Writes comparison.html + comparison.csv (and prints a table).
Deltas vs 00_control when present.

Combo picker (after singles):
  python tools/summarize_rs_noft_time_ab.py --write-combo-list path.txt --max-combos 4

Usage:
  python tools/summarize_rs_noft_time_ab.py
  python tools/summarize_rs_noft_time_ab.py --root drive/paul_experiments/rs_noft_time_ab
"""
from __future__ import annotations

import argparse
import csv
import html
import re
import sys
from pathlib import Path
from typing import Any, Optional

CONTROL_ARM = "00_control"

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

METRIC_COLS = (
    ("trades", "Total_Trades", "total trades"),
    ("wr", "Pct_Wins", "win rate %"),
    ("avg_pnl_pct", "Avg_PNL_Pct", "average profit %"),
    ("ann_ror", "Ann_ROR", "Ann_ROR"),
    ("avg_days", "Avg_Days_Held", "avg. days in trade"),
    ("pnl", "Total_PNL", "Total_PNL"),
    ("max_dd", "Max_DD", "Drawdown"),
    ("losing_streak", "Losing_Streak", "losing streak"),
    ("p90_days", "P90_Days", "p90 days"),
    ("brt_cash", "brt_cash", "brt_cash"),
    ("max_positions", "Max_Positions", "Max_Positions"),
)

_RE_NO_FT_ONLY = re.compile(r"(?:^|\D)no_ft_(\d+)$", re.I)
_RE_TIME_ONLY = re.compile(r"(?:^|\D)time_(\d+)$", re.I)
_RE_COMBO = re.compile(r"combo_nft(\d+)_t(\d+)", re.I)
_RE_LEGACY_COMBO = re.compile(r"no_ft(\d+)_time(\d+)", re.I)


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
    for pat in ("RS_Audit_Report_*.csv", "RS_Report_*.csv"):
        aud = _latest(arm_dir, pat)
        if aud:
            return aud.stem.split("_")[-1]
    return ""


def _arm_sort_key(name: str) -> tuple:
    m = re.match(r"^(\d+)_", name)
    prefix = int(m.group(1)) if m else 999
    kind = 3
    if name == CONTROL_ARM or name.endswith("_control"):
        kind = 0
    elif "combo" in name or _RE_LEGACY_COMBO.search(name):
        kind = 2
    elif "no_ft" in name and "time" not in name.replace("no_ft", ""):
        kind = 1
    elif "time_" in name:
        kind = 1
    return (kind, prefix, name)


def _classify_arm(name: str) -> tuple[str, Optional[int], Optional[int]]:
    """Return (kind, no_ft_n, time_n) where kind in control|no_ft|time|combo|other."""
    if name == CONTROL_ARM:
        return ("control", 0, 0)
    m = _RE_COMBO.search(name)
    if m:
        return ("combo", int(m.group(1)), int(m.group(2)))
    m = _RE_LEGACY_COMBO.search(name)
    if m:
        return ("combo", int(m.group(1)), int(m.group(2)))
    m = _RE_NO_FT_ONLY.search(name)
    if m and "time" not in name.split("no_ft", 1)[-1]:
        return ("no_ft", int(m.group(1)), 0)
    # arms like 01_no_ft_3
    m = re.search(r"no_ft_(\d+)$", name, re.I)
    if m:
        return ("no_ft", int(m.group(1)), 0)
    m = _RE_TIME_ONLY.search(name)
    if m:
        return ("time", 0, int(m.group(1)))
    return ("other", None, None)


def _arm_metrics(arm_dir: Path) -> dict[str, Any]:
    aud = _latest(arm_dir, "RS_Audit_Report_*.csv")
    report = _latest(arm_dir, "RS_Report_*.csv")
    src = aud or report
    kind, nft, tm = _classify_arm(arm_dir.name)
    out: dict[str, Any] = {
        "arm": arm_dir.name,
        "stamp": _read_stamp(arm_dir),
        "ok": False,
        "kind": kind,
        "missing_metrics": [],
        "trades": 0,
        "wr": 0.0,
        "avg_pnl_pct": 0.0,
        "ann_ror": 0.0,
        "avg_days": 0.0,
        "pnl": 0.0,
        "max_dd": 0.0,
        "losing_streak": 0,
        "p90_days": 0.0,
        "brt_cash": 0.0,
        "max_positions": 0,
        "no_ft_days": "" if nft is None else str(nft),
        "time_stop_days": "" if tm is None else str(tm),
        "exit_no_ft": 0,
        "exit_time": 0,
    }
    if not src or not src.exists():
        out["missing_metrics"] = [c[1] for c in METRIC_COLS]
        return out

    with src.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        row = next(csv.DictReader(f), None) or {}

    out["ok"] = True
    aud_nft = str(row.get("no_ft_days", "") or "").strip()
    aud_tm = str(row.get("time_stop_days", "") or "").strip()
    if aud_nft != "":
        out["no_ft_days"] = aud_nft
    if aud_tm != "":
        out["time_stop_days"] = aud_tm

    field_getters = {
        "trades": lambda r: int(_safe_num(r.get("Total_Trades"))),
        "wr": lambda r: _safe_num(r.get("Pct_Wins")),
        "avg_pnl_pct": lambda r: _safe_num(r.get("Avg_PNL_Pct")),
        "ann_ror": lambda r: _safe_num(r.get("Ann_ROR")),
        "avg_days": lambda r: _safe_num(r.get("Avg_Days_Held")),
        "pnl": lambda r: _safe_num(r.get("Total_PNL")),
        "max_dd": lambda r: _safe_num(r.get("Max_DD")),
        "losing_streak": lambda r: int(_safe_num(r.get("Losing_Streak"))),
        "p90_days": lambda r: _safe_num(r.get("P90_Days")),
        "brt_cash": lambda r: _safe_num(r.get("brt_cash")),
        "max_positions": lambda r: int(_safe_num(r.get("Max_Positions"))),
    }
    for key, audit_name, _label in METRIC_COLS:
        raw = row.get(audit_name)
        if raw is None or str(raw).strip() == "":
            if key == "wr" and row.get("Wins") is not None:
                wins = int(_safe_num(row.get("Wins")))
                losses = int(_safe_num(row.get("Losses")))
                bes = int(_safe_num(row.get("BE", row.get("BEs", 0))))
                tot = wins + losses + bes
                out["wr"] = (100.0 * wins / tot) if tot else 0.0
                if not out["trades"]:
                    out["trades"] = tot or int(_safe_num(row.get("Total_Trades")))
                continue
            out["missing_metrics"].append(audit_name)
            continue
        out[key] = field_getters[key](row)

    if not out["trades"]:
        wins = int(_safe_num(row.get("Wins")))
        losses = int(_safe_num(row.get("Losses")))
        bes = int(_safe_num(row.get("BE", row.get("BEs", 0))))
        out["trades"] = int(_safe_num(row.get("Total_Trades"))) or (wins + losses + bes)

    closed = _latest(arm_dir, "RS_Closed_*.csv")
    if closed and closed.exists():
        n_no_ft = 0
        n_time = 0
        with closed.open(newline="", encoding="utf-8-sig", errors="replace") as f:
            for r in csv.DictReader(f):
                et = str(r.get("EXIT_TYPE") or r.get("EXIT TYPE") or "").strip().upper()
                if et == "NO_FT":
                    n_no_ft += 1
                elif et == "TIME":
                    n_time += 1
        out["exit_no_ft"] = n_no_ft
        out["exit_time"] = n_time
    return out


def _collect_rows(root: Path) -> list[dict[str, Any]]:
    arm_dirs = [p for p in root.iterdir() if p.is_dir() and (p.name[0:1].isdigit() or p.name.startswith("ref_"))]
    arm_dirs.sort(key=lambda p: _arm_sort_key(p.name))
    return [_arm_metrics(d) for d in arm_dirs]


def _pick_combos(rows: list[dict[str, Any]], max_combos: int) -> list[tuple[int, int]]:
    """Pick up to max_combos (no_ft, time) pairs from best singles vs control."""
    ctrl = next((r for r in rows if r["arm"] == CONTROL_ARM and r["ok"]), None)
    if not ctrl:
        return []

    def _n(r: dict[str, Any], key: str) -> int:
        try:
            return int(float(str(r.get(key) or "0")))
        except ValueError:
            return 0

    no_ft_arms = [r for r in rows if r["ok"] and r.get("kind") == "no_ft"]
    time_arms = [r for r in rows if r["ok"] and r.get("kind") == "time" and _n(r, "time_stop_days") >= 30]
    if not no_ft_arms or not time_arms:
        return []

    # Prefer arms that beat control on Total_PNL; else take top by PnL.
    nft_beat = [r for r in no_ft_arms if r["pnl"] >= ctrl["pnl"]]
    tm_beat = [r for r in time_arms if r["pnl"] >= ctrl["pnl"]]
    nft_pool = sorted(nft_beat or no_ft_arms, key=lambda r: r["pnl"], reverse=True)
    tm_pool = sorted(tm_beat or time_arms, key=lambda r: r["pnl"], reverse=True)

    pairs: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()

    def _add(n: int, t: int) -> None:
        if n <= 0 or t <= 0:
            return
        key = (n, t)
        if key in seen:
            return
        # Skip if combo folder already exists
        seen.add(key)
        pairs.append(key)

    best_n = _n(nft_pool[0], "no_ft_days")
    best_t = _n(tm_pool[0], "time_stop_days")
    # best_n × top 2 times; top 2 no_ft × best_t
    for t_arm in tm_pool[:2]:
        _add(best_n, _n(t_arm, "time_stop_days"))
    for n_arm in nft_pool[:2]:
        _add(_n(n_arm, "no_ft_days"), best_t)
    # If still room and both beaters exist, cross second-bests
    if len(nft_pool) > 1 and len(tm_pool) > 1:
        _add(_n(nft_pool[1], "no_ft_days"), _n(tm_pool[1], "time_stop_days"))

    return pairs[: max(0, max_combos)]


def _write_combo_list(path: Path, pairs: list[tuple[int, int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{n},{t}" for n, t in pairs]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    print(f"Wrote {len(pairs)} combo(s) to {path}")
    for n, t in pairs:
        print(f"  combo no_ft_days={n} time_stop_days={t}")


def _write_reports(root: Path, rows: list[dict[str, Any]]) -> int:
    ctrl = next((r for r in rows if r["arm"] == CONTROL_ARM and r["ok"]), None)

    hdr = (
        f"{'arm':28} {'stamp':12} {'trades':>7} {'WR%':>6} {'avgPnL%':>8} "
        f"{'Ann_ROR':>8} {'avgDays':>7} {'Total_PNL':>12} {'Max_DD':>8} "
        f"{'LoseSt':>6} {'p90':>5} {'brt_cash':>10} {'MaxPos':>6} "
        f"{'NO_FT':>5} {'TIME':>5} {'dPnL':>10}"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        if not r["ok"]:
            print(f"{r['arm']:28} {'MISSING':12}")
            continue
        d_pnl = (r["pnl"] - ctrl["pnl"]) if ctrl else 0.0
        d_s = f"{d_pnl:+,.0f}" if ctrl and r["arm"] != CONTROL_ARM else "—"
        miss = f"  [missing: {', '.join(r['missing_metrics'])}]" if r["missing_metrics"] else ""
        print(
            f"{r['arm']:28} {r['stamp']:12} {r['trades']:7d} {r['wr']:6.1f} "
            f"{r['avg_pnl_pct']:8.2f} {r['ann_ror']:8.2f} {r['avg_days']:7.1f} "
            f"{r['pnl']:12,.0f} {r['max_dd']:8.2f} {r['losing_streak']:6d} "
            f"{r['p90_days']:5.0f} {r['brt_cash']:10,.0f} {r['max_positions']:6d} "
            f"{r['exit_no_ft']:5d} {r['exit_time']:5d} {d_s:>10}{miss}"
        )

    csv_path = root / "comparison.csv"
    csv_fields = [
        "arm",
        "stamp",
        "kind",
        "no_ft_days",
        "time_stop_days",
        "Total_Trades",
        "Pct_Wins",
        "Avg_PNL_Pct",
        "Ann_ROR",
        "Avg_Days_Held",
        "Total_PNL",
        "Max_DD",
        "Losing_Streak",
        "P90_Days",
        "brt_cash",
        "Max_Positions",
        "EXIT_NO_FT",
        "EXIT_TIME",
        "d_Total_PNL",
        "d_Total_Trades",
        "d_Pct_Wins",
        "d_Ann_ROR",
        "d_Max_DD",
        "missing_metrics",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=csv_fields)
        w.writeheader()
        for r in rows:
            d_pnl = (r["pnl"] - ctrl["pnl"]) if ctrl and r["ok"] else ""
            d_tr = (r["trades"] - ctrl["trades"]) if ctrl and r["ok"] else ""
            d_wr = (r["wr"] - ctrl["wr"]) if ctrl and r["ok"] else ""
            d_ror = (r["ann_ror"] - ctrl["ann_ror"]) if ctrl and r["ok"] else ""
            d_dd = (r["max_dd"] - ctrl["max_dd"]) if ctrl and r["ok"] else ""
            if r["arm"] == CONTROL_ARM:
                d_pnl = d_tr = d_wr = d_ror = d_dd = ""
            w.writerow(
                {
                    "arm": r["arm"],
                    "stamp": r["stamp"],
                    "kind": r.get("kind", ""),
                    "no_ft_days": r["no_ft_days"],
                    "time_stop_days": r["time_stop_days"],
                    "Total_Trades": r["trades"] if r["ok"] else "",
                    "Pct_Wins": f"{r['wr']:.4f}" if r["ok"] else "",
                    "Avg_PNL_Pct": f"{r['avg_pnl_pct']:.4f}" if r["ok"] else "",
                    "Ann_ROR": f"{r['ann_ror']:.4f}" if r["ok"] else "",
                    "Avg_Days_Held": f"{r['avg_days']:.4f}" if r["ok"] else "",
                    "Total_PNL": f"{r['pnl']:.4f}" if r["ok"] else "",
                    "Max_DD": f"{r['max_dd']:.4f}" if r["ok"] else "",
                    "Losing_Streak": r["losing_streak"] if r["ok"] else "",
                    "P90_Days": f"{r['p90_days']:.4f}" if r["ok"] else "",
                    "brt_cash": f"{r['brt_cash']:.4f}" if r["ok"] else "",
                    "Max_Positions": r["max_positions"] if r["ok"] else "",
                    "EXIT_NO_FT": r["exit_no_ft"] if r["ok"] else "",
                    "EXIT_TIME": r["exit_time"] if r["ok"] else "",
                    "d_Total_PNL": d_pnl,
                    "d_Total_Trades": d_tr,
                    "d_Pct_Wins": d_wr,
                    "d_Ann_ROR": d_ror,
                    "d_Max_DD": d_dd,
                    "missing_metrics": ";".join(r["missing_metrics"]),
                }
            )

    body_rows = []
    for r in rows:
        if not r["ok"]:
            body_rows.append(
                f"<tr><td>{html.escape(r['arm'])}</td>"
                f"<td colspan='20'><em>MISSING</em></td></tr>"
            )
            continue
        d_pnl = (r["pnl"] - ctrl["pnl"]) if ctrl else 0.0
        d_tr = (r["trades"] - ctrl["trades"]) if ctrl else 0
        d_wr = (r["wr"] - ctrl["wr"]) if ctrl else 0.0
        d_ror = (r["ann_ror"] - ctrl["ann_ror"]) if ctrl else 0.0
        miss_note = (
            f" <span class='miss' title='{html.escape(', '.join(r['missing_metrics']))}'>"
            f"(partial)</span>"
            if r["missing_metrics"]
            else ""
        )
        body_rows.append(
            "<tr>"
            f"<td>{html.escape(r['arm'])}{miss_note}</td>"
            f"<td>{html.escape(r['stamp'])}</td>"
            f"<td class='num'>{html.escape(str(r['no_ft_days']))}</td>"
            f"<td class='num'>{html.escape(str(r['time_stop_days']))}</td>"
            f"<td class='num'>{r['trades']}</td>"
            f"<td class='num'>{r['wr']:.1f}</td>"
            f"<td class='num'>{r['avg_pnl_pct']:.2f}</td>"
            f"<td class='num'>{r['ann_ror']:.2f}</td>"
            f"<td class='num'>{r['avg_days']:.1f}</td>"
            f"<td class='num'>{r['pnl']:,.0f}</td>"
            f"<td class='num'>{r['max_dd']:.2f}</td>"
            f"<td class='num'>{r['losing_streak']}</td>"
            f"<td class='num'>{r['p90_days']:.0f}</td>"
            f"<td class='num'>{r['brt_cash']:,.0f}</td>"
            f"<td class='num'>{r['max_positions']}</td>"
            f"<td class='num'>{r['exit_no_ft']}</td>"
            f"<td class='num'>{r['exit_time']}</td>"
            f"<td class='num'>{d_pnl:+,.0f}</td>"
            f"<td class='num'>{d_tr:+d}</td>"
            f"<td class='num'>{d_wr:+.1f}</td>"
            f"<td class='num'>{d_ror:+.2f}</td>"
            "</tr>"
        )

    verdict_bits: list[str] = []
    if ctrl:
        cands = [r for r in rows if r["ok"] and r["arm"] != CONTROL_ARM]
        best_pnl = max(cands, key=lambda x: x["pnl"]) if cands else None
        if best_pnl:
            beat = best_pnl["pnl"] > ctrl["pnl"]
            verdict_bits.append(
                f"Best Total_PNL arm: <code>{html.escape(best_pnl['arm'])}</code> "
                f"({best_pnl['pnl']:,.0f} vs control {ctrl['pnl']:,.0f}, "
                f"Δ {best_pnl['pnl'] - ctrl['pnl']:+,.0f})"
                + (" — beats control." if beat else " — does not beat control.")
            )
        for kind, label in (("no_ft", "Best NO_FT"), ("time", "Best TIME"), ("combo", "Best combo")):
            pool = [r for r in cands if r.get("kind") == kind]
            if not pool:
                continue
            arm = max(pool, key=lambda x: x["pnl"])
            verdict_bits.append(
                f"{label} (<code>{html.escape(arm['arm'])}</code>): "
                f"PnL Δ {arm['pnl'] - ctrl['pnl']:+,.0f}, "
                f"Ann_ROR Δ {arm['ann_ror'] - ctrl['ann_ror']:+.2f}, "
                f"Max_DD Δ {arm['max_dd'] - ctrl['max_dd']:+.2f}, "
                f"WR {arm['wr']:.1f}% (control {ctrl['wr']:.1f}%), "
                f"trades {arm['trades']}."
            )
        beaters = [r for r in cands if r["pnl"] > ctrl["pnl"]]
        if beaters:
            names = ", ".join(f"<code>{html.escape(r['arm'])}</code>" for r in sorted(beaters, key=lambda x: -x["pnl"]))
            verdict_bits.append(f"Arms beating control on Total_PNL: {names}.")
        else:
            verdict_bits.append("No arm beats control on Total_PNL.")

    verdict_html = (
        "<ul>" + "".join(f"<li>{b}</li>" for b in verdict_bits) + "</ul>"
        if verdict_bits
        else "<p><em>No control arm yet — run the suite.</em></p>"
    )

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>RS A/B — NO_FT + TIME grid (SB-style)</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:1.5rem;line-height:1.45;color:#1a1a1a}}
h1{{font-size:1.4rem}} h2{{font-size:1.1rem;margin-top:1.5rem}}
table{{border-collapse:collapse;width:100%;margin:1rem 0;font-size:.85rem}}
th,td{{border:1px solid #ccc;padding:.35rem .45rem;text-align:left}}
th{{background:#f3f3f3}}
td.num{{text-align:right;font-variant-numeric:tabular-nums}}
.note{{color:#444;max-width:64rem}}
.miss{{color:#a60;font-size:.85em}}
code{{background:#f5f5f5;padding:.1em .3em;border-radius:3px}}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>RS A/B — SB-style NO_FT + TIME (RS-scale grid)</h1>
<p class="note">
Relative Strength (RS) production levers with portable
<code>no_ft_days</code> / <code>time_stop_days</code>
(same semantics as StockBee <code>burst_no_ft_days</code> / <code>burst_time_stop_days</code>:
bars from fill, sell at close; NO_FT = never Close &gt; entry).
Default grids: NO_FT 3/5/7/10; TIME 30/60/90/120/180/252 (not SB's 5).
Metrics from <code>RS_Audit_Report</code>. Click column headers to sort. Deltas vs <code>00_control</code>.
</p>
<h2>Verdict</h2>
{verdict_html}
<table class="sortable">
<thead><tr>
{sortable_th("Arm", "text")}
{sortable_th("Stamp", "text")}
{sortable_th("no_ft_days", "num")}
{sortable_th("time_stop_days", "num")}
{sortable_th("Total trades", "num")}
{sortable_th("Win rate %", "num")}
{sortable_th("Avg profit %", "num")}
{sortable_th("Ann_ROR", "num")}
{sortable_th("Avg days", "num")}
{sortable_th("Total_PNL", "num")}
{sortable_th("Drawdown (Max_DD %)", "num")}
{sortable_th("Losing streak", "num")}
{sortable_th("P90 days", "num")}
{sortable_th("brt_cash", "num")}
{sortable_th("Max_Positions", "num")}
{sortable_th("EXIT_NO_FT", "num")}
{sortable_th("EXIT_TIME", "num")}
{sortable_th("Δ Total_PNL", "num")}
{sortable_th("Δ Trades", "num")}
{sortable_th("Δ WR%", "num")}
{sortable_th("Δ Ann_ROR", "num")}
</tr></thead>
<tbody>
{"".join(body_rows)}
</tbody>
</table>
<p class="note">Re-run: <code>run_rs_noft_time_ab.bat</code> —
env <code>NO_FT_GRID</code>, <code>TIME_GRID</code>, <code>RUN_COMBO_AUTO</code>,
<code>MAX_COMBOS</code>, <code>RS_SYMBOLS</code>, <code>RS_UNIVERSE_CSV</code>,
<code>SKIP_EXISTING</code>, <code>RS_NOFT_TIME_SMOKE</code>.</p>
<script>
{SORTABLE_TABLE_SCRIPT}
</script>
</body>
</html>
"""
    html_path = root / "comparison.html"
    html_path.write_text(html_doc, encoding="utf-8")
    print()
    print(f"Root: {root.resolve()}")
    print(f"Wrote {csv_path}")
    print(f"Wrote {html_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--root",
        type=Path,
        default=Path("drive/paul_experiments/rs_noft_time_ab"),
        help="A/B output root (arm subdirs)",
    )
    ap.add_argument(
        "--write-combo-list",
        type=Path,
        default=None,
        help="Write no_ft,time pairs for promising combos (one per line) and exit",
    )
    ap.add_argument("--max-combos", type=int, default=4, help="Max combo pairs to emit")
    args = ap.parse_args()
    root: Path = args.root
    if not root.is_absolute():
        root = Path.cwd() / root
    if not root.is_dir():
        print(f"No output root yet: {root}", file=sys.stderr)
        return 1

    rows = _collect_rows(root)
    if not rows:
        print(f"No arm folders under {root}", file=sys.stderr)
        return 1

    if args.write_combo_list is not None:
        pairs = _pick_combos(rows, max(0, int(args.max_combos)))
        out = args.write_combo_list
        if not out.is_absolute():
            out = Path.cwd() / out
        # Drop pairs that already have a combo arm folder
        existing = set()
        for r in rows:
            if r.get("kind") == "combo" and r["ok"]:
                try:
                    existing.add((int(float(r["no_ft_days"])), int(float(r["time_stop_days"]))))
                except ValueError:
                    pass
        pairs = [p for p in pairs if p not in existing]
        _write_combo_list(out, pairs)
        return 0

    return _write_reports(root, rows)


if __name__ == "__main__":
    raise SystemExit(main())
