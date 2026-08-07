#!/usr/bin/env python3
"""Summarize Qull prior_run A/B arms → comparison.html + comparison.md."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path


def _read_summary_metrics(arm_dir: Path) -> dict[str, str]:
    out = {
        "arm": arm_dir.name,
        "stamp": "",
        "trades": "0",
        "wins": "0",
        "pct_wins": "",
        "total_pnl": "",
        "symbols": "0",
    }
    stamp_p = arm_dir / "stamp.txt"
    if stamp_p.exists():
        out["stamp"] = stamp_p.read_text(encoding="utf-8").strip()
    # Prefer Report rollup
    reports = list(arm_dir.glob("QULL_Report_*.csv"))
    if reports:
        with reports[0].open(encoding="utf-8", newline="") as f:
            for row in csv.reader(f):
                if len(row) < 2:
                    continue
                k, v = row[0], row[1]
                if k == "trades":
                    out["trades"] = v
                elif k == "wins":
                    out["wins"] = v
                elif k == "pct_wins":
                    out["pct_wins"] = v
                elif k == "total_pnl_dollars":
                    out["total_pnl"] = v
    summaries = list(arm_dir.glob("QULL_Summary_*.csv"))
    if summaries:
        with summaries[0].open(encoding="utf-8", newline="") as f:
            n = max(0, sum(1 for _ in f) - 1)
        out["symbols"] = str(n)
    meta = arm_dir / "arm_meta.txt"
    if meta.exists():
        out["meta"] = meta.read_text(encoding="utf-8").strip().replace("\n", "; ")
    else:
        out["meta"] = ""
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--ab-root",
        default="drive/paul_experiments/tbn_new_systems/qull_ep_htf/ab_prior_run",
    )
    args = ap.parse_args()
    root = Path(args.ab_root)
    root.mkdir(parents=True, exist_ok=True)
    arms = sorted([p for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")])
    rows = [_read_summary_metrics(a) for a in arms]

    md_path = root / "comparison.md"
    html_path = root / "comparison.html"

    lines = [
        "# Qull HTF A/B — prior_run_pct",
        "",
        "| Arm | Stamp | Trades | Wins | Win% | Total PnL $ | Symbols | Meta |",
        "|-----|-------|--------|------|------|-------------|---------|------|",
    ]
    for r in rows:
        lines.append(
            f"| {r['arm']} | {r['stamp']} | {r['trades']} | {r['wins']} | {r['pct_wins']} | "
            f"{r['total_pnl']} | {r['symbols']} | {r.get('meta', '')} |"
        )
    lines.append("")
    lines.append("Click headers in comparison.html to sort.")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    th = (
        '<th class="sortable-th" data-sort="{t}" tabindex="0" role="columnheader" '
        'aria-sort="none">{lab}<span class="sort-ind"></span></th>'
    )
    headers = [
        ("text", "Arm"),
        ("text", "Stamp"),
        ("num", "Trades"),
        ("num", "Wins"),
        ("num", "Win%"),
        ("num", "Total PnL $"),
        ("num", "Symbols"),
        ("text", "Meta"),
    ]
    body = []
    for r in rows:
        body.append(
            "<tr>"
            f"<td>{r['arm']}</td><td>{r['stamp']}</td><td>{r['trades']}</td>"
            f"<td>{r['wins']}</td><td>{r['pct_wins']}</td><td>{r['total_pnl']}</td>"
            f"<td>{r['symbols']}</td><td>{r.get('meta', '')}</td>"
            "</tr>"
        )
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Qull prior_run A/B</title>
<style>
body{{font-family:Segoe UI,Helvetica,sans-serif;margin:24px;background:#f7f6f2;color:#1c1b19}}
table.sortable{{border-collapse:collapse;width:100%;background:#fff}}
th,td{{border:1px solid #d4d0c4;padding:8px;text-align:left}}
th.sortable-th{{background:#f0eee6;cursor:pointer;user-select:none}}
th.sortable-th .sort-ind{{margin-left:.35em;opacity:.45}}
th.sortable-th.sort-asc .sort-ind::after{{content:"▲";opacity:1}}
th.sortable-th.sort-desc .sort-ind::after{{content:"▼";opacity:1}}
.hint{{color:#5a574f;font-size:.9rem}}
</style></head><body>
<h1>Qull HTF A/B — prior_run_pct</h1>
<p class="hint">Click column headers to sort.</p>
<table class="sortable"><thead><tr>
{''.join(th.format(t=t, lab=lab) for t, lab in headers)}
</tr></thead><tbody>
{''.join(body)}
</tbody></table>
<script>
(function(){{
  function parse(v,t){{v=(v||'').trim();if(t==='num'){{var n=parseFloat(v.replace(/[^0-9.\\-]+/g,''));return isNaN(n)?0:n;}}return v.toLowerCase();}}
  document.querySelectorAll('table.sortable').forEach(function(table){{
    table.querySelectorAll('th.sortable-th').forEach(function(th,idx){{
      th.addEventListener('click',function(){{
        var t=th.getAttribute('data-sort')||'text';
        var asc=!th.classList.contains('sort-asc');
        table.querySelectorAll('th.sortable-th').forEach(function(h){{h.classList.remove('sort-asc','sort-desc');h.setAttribute('aria-sort','none');}});
        th.classList.add(asc?'sort-asc':'sort-desc');th.setAttribute('aria-sort',asc?'ascending':'descending');
        var tb=table.tBodies[0];var rows=[].slice.call(tb.rows);
        rows.sort(function(a,b){{var av=parse(a.cells[idx].textContent,t),bv=parse(b.cells[idx].textContent,t);if(av<bv)return asc?-1:1;if(av>bv)return asc?1:-1;return 0;}});
        rows.forEach(function(r){{tb.appendChild(r);}});
      }});
    }});
  }});
}})();
</script>
</body></html>
"""
    html_path.write_text(html, encoding="utf-8")
    print(f"[QULL-AB] Wrote {html_path} and {md_path} ({len(rows)} arms)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
