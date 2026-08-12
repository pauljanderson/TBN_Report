#!/usr/bin/env python3
"""Per-trade breakdown for high same-day RS entry clusters (gold-65).

IND_DIFF alignment (same as tools/summarize_rl_rs_sb_ind_gate_ab.py):
  Trade-aligned bull−bear indicator count at the **trigger** bar
  (session before DATE_OPENED). RS Closed already stamps IND_DIFF /
  IND_SCORE when use_indicators=true; we use those rocket fields
  (no re-enrich needed when the column is present).

Prior avg days held:
  Mean DAYS_HELD of the same symbol's prior closed RS trades with
  DATE_OPENED < this entry and DATE_CLOSED <= this entry date.
  N/A when no prior trades.
"""
from __future__ import annotations

import csv
import html
import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")
CLOSED = (
    ROOT
    / "drive/paul_experiments/rs_baseline_260807141317/engine_closed/RS_Closed_260807141317.csv"
)
OUT_HTML = ROOT / "drive/paul_experiments/RS_SameDay_Entry_Cluster_Trades.html"
OUT_JSON = ROOT / "_tmp_rs_sameday_cluster_trades.json"

# High same-day RS entry dates (N>=8 on gold-65), in requested order
TARGET_DATES = [
    "20250122",
    "20260408",
    "20130107",
    "20231012",
    "20250425",
    "20170426",
    "20221018",
    "20240819",
]

SORTABLE_TH_CSS = """
th.sortable-th{cursor:pointer;user-select:none;white-space:nowrap}
th.sortable-th .sort-ind{opacity:.45;margin-left:.25em;font-size:.85em}
th.sortable-th.sort-asc .sort-ind::after{content:"▲";opacity:1}
th.sortable-th.sort-desc .sort-ind::after{content:"▼";opacity:1}
"""

SORTABLE_TABLE_SCRIPT = """
(function(){
  function parseCell(td, type){
    var t=(td.textContent||"").trim();
    if(!t || t==="—" || t==="N/A"){ return type==="text"?"":null; }
    t=t.replace(/[$,%+]/g,"").replace(/,/g,"");
    if(type==="num"){ var n=parseFloat(t); return isNaN(n)?null:n; }
    if(type==="date"||type==="month"){ return t; }
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


def ymd8(s: str) -> str:
    digits = "".join(ch for ch in str(s or "") if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else ""


def fmt_date(s: str) -> str:
    d = ymd8(s)
    if len(d) != 8:
        return str(s)
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


def parse_pct(s) -> float | None:
    if s is None or str(s).strip() == "":
        return None
    try:
        return float(str(s).replace("%", "").replace(",", "").strip())
    except ValueError:
        return None


def parse_num(s) -> float | None:
    if s is None or str(s).strip() == "" or str(s).strip().upper() == "N/A":
        return None
    try:
        return float(str(s).replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


def cls_for(x: float | None) -> str:
    if x is None:
        return ""
    if x > 0:
        return "pos"
    if x < 0:
        return "neg"
    return ""


def prior_avg_days_held(
    all_by_sym: dict[str, list[dict]],
    sym: str,
    entry: str,
) -> float | None:
    """Mean DAYS_HELD of prior closed RS trades for symbol at entry time."""
    priors = []
    for r in all_by_sym.get(sym, []):
        o = ymd8(r.get("DATE_OPENED", ""))
        c = ymd8(r.get("DATE_CLOSED", ""))
        if not o or not c:
            continue
        if o < entry and c <= entry:
            dh = parse_num(r.get("DAYS_HELD"))
            if dh is not None:
                priors.append(dh)
    if not priors:
        return None
    return statistics.mean(priors)


def main() -> None:
    rows = list(csv.DictReader(CLOSED.open(encoding="utf-8")))
    print(f"Loaded {len(rows)} trades from {CLOSED.name}")

    by_open: dict[str, list[dict]] = defaultdict(list)
    by_sym: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        o = ymd8(r.get("DATE_OPENED", ""))
        if o:
            by_open[o].append(r)
        sym = str(r.get("SYMBOL", "")).strip().upper()
        if sym:
            by_sym[sym].append(r)

    # Prefer Closed-stamped IND (same as rl_rs_sb_ind_gate_ab when column present)
    ind_present = sum(1 for r in rows if str(r.get("IND_DIFF", "")).strip() != "")
    print(f"IND_DIFF present on Closed: {ind_present}/{len(rows)}")

    day_blocks = []
    missing_ind_notes: list[str] = []

    for entry in TARGET_DATES:
        trades = by_open.get(entry, [])
        if not trades:
            print(f"WARNING: no trades on {fmt_date(entry)}")
            day_blocks.append(
                {
                    "date": entry,
                    "date_fmt": fmt_date(entry),
                    "n": 0,
                    "trades": [],
                    "summary": {},
                }
            )
            continue

        trade_rows = []
        for r in sorted(trades, key=lambda x: (str(x.get("SYMBOL", "")).upper(),)):
            sym = str(r.get("SYMBOL", "")).strip().upper()
            pnl_pct = parse_pct(r.get("PNL_PCT"))
            pnl_dol = parse_num(r.get("PNL_DOLLARS"))
            days_held = parse_num(r.get("DAYS_HELD"))
            ind_raw = str(r.get("IND_DIFF", "")).strip()
            ind_diff = parse_num(ind_raw) if ind_raw else None
            score_raw = str(r.get("IND_SCORE", "")).strip()
            ind_score = parse_num(score_raw) if score_raw else None
            prior_avg = prior_avg_days_held(by_sym, sym, entry)
            if ind_diff is None:
                missing_ind_notes.append(f"{fmt_date(entry)} {sym}")

            trade_rows.append(
                {
                    "symbol": sym,
                    "entry": fmt_date(r.get("DATE_OPENED", entry)),
                    "exit": fmt_date(r.get("DATE_CLOSED", "")),
                    "days_held": days_held,
                    "pnl_pct": pnl_pct,
                    "pnl_dollars": pnl_dol,
                    "exit_type": str(r.get("EXIT_TYPE", "") or "").strip(),
                    "ind_diff": ind_diff,
                    "ind_score": ind_score,
                    "prior_avg_days": prior_avg,
                    "entry_price": parse_num(r.get("ENTRY_PRICE")),
                    "exit_price": parse_num(r.get("EXIT_PRICE")),
                }
            )

        pnls = [t["pnl_pct"] for t in trade_rows if t["pnl_pct"] is not None]
        wins = sum(1 for p in pnls if p > 0)
        ind_vals = [t["ind_diff"] for t in trade_rows if t["ind_diff"] is not None]
        prior_vals = [
            t["prior_avg_days"] for t in trade_rows if t["prior_avg_days"] is not None
        ]
        summary = {
            "n": len(trade_rows),
            "wins": wins,
            "losses": len(pnls) - wins,
            "wr": (100.0 * wins / len(pnls)) if pnls else 0.0,
            "avg_pnl_pct": statistics.mean(pnls) if pnls else None,
            "avg_ind_diff": statistics.mean(ind_vals) if ind_vals else None,
            "ind_diff_n": len(ind_vals),
            "avg_prior_hold": statistics.mean(prior_vals) if prior_vals else None,
            "prior_hold_n": len(prior_vals),
            "sum_pnl_dollars": sum(
                t["pnl_dollars"] for t in trade_rows if t["pnl_dollars"] is not None
            ),
        }
        day_blocks.append(
            {
                "date": entry,
                "date_fmt": fmt_date(entry),
                "n": len(trade_rows),
                "trades": trade_rows,
                "summary": summary,
            }
        )
        print(
            f"{fmt_date(entry)} N={summary['n']} WR={summary['wr']:.1f}% "
            f"avgPNL%={summary['avg_pnl_pct']:.2f} "
            f"avgIND={summary['avg_ind_diff'] if summary['avg_ind_diff'] is not None else 'N/A'} "
            f"avgPriorHold={summary['avg_prior_hold'] if summary['avg_prior_hold'] is not None else 'N/A'} "
            f"(prior_n={summary['prior_hold_n']})"
        )

    # --- HTML ---
    overview_rows = []
    for b in day_blocks:
        s = b["summary"]
        if not s:
            continue

        def _fmt_n(v, places=2):
            if v is None:
                return "—"
            return f"{v:.{places}f}"

        def _fmt_pct_signed(v, places=2):
            if v is None:
                return "—"
            return f"{v:+.{places}f}%"

        overview_rows.append(
            "<tr>"
            f"<td><a href='#d-{b['date']}'>{html.escape(b['date_fmt'])}</a></td>"
            f"<td class='num'>{s['n']}</td>"
            f"<td class='num'>{s['wr']:.1f}%</td>"
            f"<td class='num {cls_for(s['avg_pnl_pct'])}'>"
            f"{_fmt_pct_signed(s['avg_pnl_pct'])}</td>"
            f"<td class='num'>{_fmt_n(s['avg_ind_diff'], 1)}</td>"
            f"<td class='num'>{_fmt_n(s['avg_prior_hold'], 1)}</td>"
            f"<td class='num'>{s['prior_hold_n']}/{s['n']}</td>"
            f"<td class='num {cls_for(s.get('sum_pnl_dollars'))}'>"
            f"${s.get('sum_pnl_dollars', 0):,.0f}</td>"
            "</tr>"
        )

    sections = []
    for b in day_blocks:
        s = b["summary"]
        body = []
        for t in b["trades"]:
            ind_s = "—" if t["ind_diff"] is None else f"{t['ind_diff']:.0f}"
            score_s = "—" if t["ind_score"] is None else f"{t['ind_score']:.2f}"
            prior_s = (
                "N/A" if t["prior_avg_days"] is None else f"{t['prior_avg_days']:.1f}"
            )
            pnl_s = "—" if t["pnl_pct"] is None else f"{t['pnl_pct']:+.2f}%"
            dol_s = "—" if t["pnl_dollars"] is None else f"${t['pnl_dollars']:,.0f}"
            dh_s = "—" if t["days_held"] is None else f"{t['days_held']:.0f}"
            body.append(
                "<tr>"
                f"<td>{html.escape(t['symbol'])}</td>"
                f"<td>{html.escape(t['entry'])}</td>"
                f"<td>{html.escape(t['exit'])}</td>"
                f"<td class='num'>{dh_s}</td>"
                f"<td class='num {cls_for(t['pnl_pct'])}'>{pnl_s}</td>"
                f"<td class='num {cls_for(t['pnl_dollars'])}'>{dol_s}</td>"
                f"<td>{html.escape(t['exit_type'])}</td>"
                f"<td class='num'>{ind_s}</td>"
                f"<td class='num'>{score_s}</td>"
                f"<td class='num'>{prior_s}</td>"
                "</tr>"
            )

        def _avg(v, places=2, pct=False):
            if v is None:
                return "—"
            return f"{v:+.{places}f}%" if pct else f"{v:.{places}f}"

        prior_sum = (
            "N/A"
            if s.get("avg_prior_hold") is None
            else f"{s['avg_prior_hold']:.1f}"
        )
        summary_row = (
            "<tr class='total-row'>"
            f"<td colspan='3'><strong>Day summary</strong> "
            f"N={s.get('n', 0)} · WR={s.get('wr', 0):.1f}% · "
            f"wins/losses={s.get('wins', 0)}/{s.get('losses', 0)}</td>"
            f"<td class='num'>—</td>"
            f"<td class='num {cls_for(s.get('avg_pnl_pct'))}'>"
            f"<strong>{_avg(s.get('avg_pnl_pct'), pct=True)}</strong></td>"
            f"<td class='num {cls_for(s.get('sum_pnl_dollars'))}'>"
            f"<strong>${s.get('sum_pnl_dollars', 0):,.0f}</strong></td>"
            f"<td>—</td>"
            f"<td class='num'><strong>{_avg(s.get('avg_ind_diff'), 1)}</strong></td>"
            f"<td class='num'>—</td>"
            f"<td class='num'><strong>{prior_sum}</strong></td>"
            "</tr>"
        )

        sections.append(
            f"""
<section id="d-{b['date']}">
  <h2>{html.escape(b['date_fmt'])} · N={b['n']}</h2>
  <p class="sub">Click column headers to sort. Footer row stays pinned.</p>
  <table class="sortable">
    <thead><tr>
      {sortable_th("Symbol", "text")}
      {sortable_th("Entry", "date")}
      {sortable_th("Exit", "date")}
      {sortable_th("Days held", "num")}
      {sortable_th("PNL%", "num")}
      {sortable_th("PNL$", "num")}
      {sortable_th("Exit type", "text")}
      {sortable_th("IND_DIFF", "num")}
      {sortable_th("IND_SCORE", "num")}
      {sortable_th("Prior avg days held", "num")}
    </tr></thead>
    <tbody>
      {"".join(body)}
      {summary_row}
    </tbody>
  </table>
</section>
"""
        )

    missing_html = ""
    if missing_ind_notes:
        missing_html = (
            "<p class='warn'><strong>IND_DIFF missing</strong> for: "
            + ", ".join(html.escape(x) for x in missing_ind_notes)
            + "</p>"
        )
    else:
        missing_html = (
            "<p>All listed trades have Closed-stamped <code>IND_DIFF</code>.</p>"
        )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>RS Same-Day Entry Cluster Trades (gold-65)</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8;
  --pos:#3dd68c; --neg:#f07178; --line:#2a3544; --accent:#5b9fd4; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:Segoe UI, system-ui, sans-serif; background:var(--bg);
  color:var(--text); line-height:1.45; padding:1.5rem 2rem 3rem; }}
h1 {{ font-size:1.45rem; margin:0 0 .4rem; }}
h2 {{ font-size:1.15rem; margin:2rem 0 .5rem; color:var(--accent); }}
.sub, .meta {{ color:var(--muted); font-size:.92rem; }}
.meta {{ margin-bottom:1.2rem; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:8px;
  padding:1rem 1.1rem; margin:1rem 0; }}
table {{ border-collapse:collapse; width:100%; font-size:.9rem; margin:.6rem 0 1rem; }}
th, td {{ border-bottom:1px solid var(--line); padding:.35rem .55rem; text-align:left; }}
th {{ background:#121a24; position:sticky; top:0; z-index:1; }}
td.num, th.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
tr.total-row {{ background:#15202b; font-weight:600; }}
.pos {{ color:var(--pos); }}
.neg {{ color:var(--neg); }}
a {{ color:var(--accent); }}
code {{ background:#121a24; padding:.05rem .3rem; border-radius:3px; font-size:.88em; }}
.warn {{ color:#f0c674; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>RS Same-Day Entry Cluster Trades</h1>
<p class="meta">
  Gold-65 Closed: <code>{html.escape(str(CLOSED.relative_to(ROOT)).replace(chr(92), "/"))}</code><br>
  Stamp <code>260807141317</code> · High same-day entry dates with N≥8<br>
  Generated {datetime.now().strftime("%Y-%m-%d %H:%M")}
</p>

<div class="card">
  <h2 style="margin-top:0">IND_DIFF alignment</h2>
  <p>Same as <code>tools/summarize_rl_rs_sb_ind_gate_ab.py</code> /
  <code>rl_rs_sb_ind_gate_ab</code>: <strong>IND_DIFF</strong> is the trade-aligned
  bull−bear indicator count at the <strong>trigger</strong> bar (session before
  <code>DATE_OPENED</code>). Source: rocket fields already stamped on RS Closed
  (<code>IND_DIFF</code>, <code>IND_SCORE</code>) when <code>use_indicators=true</code>.</p>
  <p><strong>Prior avg days held</strong>: mean <code>DAYS_HELD</code> of that
  symbol’s prior closed RS trades with <code>DATE_OPENED</code> &lt; this entry and
  <code>DATE_CLOSED</code> ≤ entry date; <code>N/A</code> if none.</p>
  {missing_html}
</div>

<h2>Overview (N≥8 days)</h2>
<p class="sub">Click column headers to sort.</p>
<table class="sortable">
  <thead><tr>
    {sortable_th("Date", "date")}
    {sortable_th("N", "num")}
    {sortable_th("WR", "num")}
    {sortable_th("Avg PNL%", "num")}
    {sortable_th("Avg IND_DIFF", "num")}
    {sortable_th("Avg prior-hold", "num")}
    {sortable_th("Prior-hold coverage", "text")}
    {sortable_th("Sum PNL$", "num")}
  </tr></thead>
  <tbody>
    {"".join(overview_rows)}
  </tbody>
</table>

{"".join(sections)}

<script>{SORTABLE_TABLE_SCRIPT}</script>
</body>
</html>
"""

    OUT_HTML.write_text(page, encoding="utf-8")
    print(f"Wrote {OUT_HTML}")

    payload = {
        "source": str(CLOSED.relative_to(ROOT)).replace("\\", "/"),
        "stamp": "260807141317",
        "ind_alignment": (
            "Trigger bar = session before DATE_OPENED; "
            "Closed-stamped IND_DIFF / IND_SCORE (rl_rs_sb_ind_gate_ab column_present mode)"
        ),
        "prior_avg_days_held": (
            "mean DAYS_HELD of same-symbol trades with DATE_OPENED < entry "
            "and DATE_CLOSED <= entry; N/A if none"
        ),
        "ind_diff_present_on_closed": f"{ind_present}/{len(rows)}",
        "missing_ind_diff": missing_ind_notes,
        "days": [
            {
                "date": b["date_fmt"],
                "summary": b["summary"],
                "trades": b["trades"],
            }
            for b in day_blocks
        ],
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {OUT_JSON}")
    if missing_ind_notes:
        print("MISSING IND_DIFF:", ", ".join(missing_ind_notes))
    else:
        print("No missing IND_DIFF on cluster trades.")


if __name__ == "__main__":
    main()
