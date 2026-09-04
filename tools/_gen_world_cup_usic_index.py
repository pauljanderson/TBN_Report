# -*- coding: utf-8 -*-
"""One-shot generator for world_cup_usic_traders_legit_20260831/index.html"""
import html
import json
from pathlib import Path

root = Path("drive/paul_experiments/world_cup_usic_traders_legit_20260831")
rows = []
for d in sorted(root.iterdir()):
    sj = d / "summary.json"
    if sj.exists():
        rows.append(json.loads(sj.read_text(encoding="utf-8")))


def score_class(n: float) -> str:
    if n >= 7:
        return "score-hi"
    if n >= 4:
        return "score-mid"
    return "score-lo"


def esc(s) -> str:
    return html.escape(str(s) if s is not None else "")


for r in rows:
    r["_avg"] = round(
        (
            r["identity_score_10"]
            + r["transparency_score_10"]
            + r["verifiable_perf_score_10"]
            + r["regulatory_score_10"]
            + r["value_vs_cost_score_10"]
        )
        / 5,
        1,
    )
rows.sort(key=lambda x: -x["_avg"])

tr_parts = []
for r in rows:
    avg = r["_avg"]
    link = f"{r['slug']}/report.html"
    tr_parts.append(
        f"""<tr>
  <td><a href="{esc(link)}">{esc(r['name'])}</a></td>
  <td>{esc(r.get('category', ''))}</td>
  <td class="num {score_class(r['identity_score_10'])}">{r['identity_score_10']}</td>
  <td class="num {score_class(r['transparency_score_10'])}">{r['transparency_score_10']}</td>
  <td class="num {score_class(r['verifiable_perf_score_10'])}">{r['verifiable_perf_score_10']}</td>
  <td class="num {score_class(r['regulatory_score_10'])}">{r['regulatory_score_10']}</td>
  <td class="num {score_class(r['value_vs_cost_score_10'])}">{r['value_vs_cost_score_10']}</td>
  <td class="num {score_class(avg)}">{avg}</td>
  <td>{esc(r.get('verdict_one_liner', ''))}</td>
</tr>"""
    )
body_rows = "\n".join(tr_parts)

out = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>World Cup / USIC Competitors — Legitimacy Compare Index</title>
  <style>
    :root {{
      --bg: #f8fafc; --card: #ffffff; --text: #0f172a; --muted: #64748b;
      --border: #e2e8f0; --accent: #1d4ed8; --green: #15803d; --amber: #b45309; --red: #b91c1c;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
      background: var(--bg); color: var(--text); line-height: 1.55;
      margin: 0; padding: 1.5rem; max-width: 1180px; margin-inline: auto;
    }}
    header {{
      background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 100%);
      color: #fff; padding: 1.75rem 2rem; border-radius: 12px; margin-bottom: 1.5rem;
    }}
    header h1 {{ margin: 0 0 .35rem; font-size: 1.65rem; }}
    header p {{ margin: 0; opacity: .88; font-size: .95rem; }}
    section {{
      background: var(--card); border: 1px solid var(--border);
      border-radius: 10px; padding: 1.25rem 1.5rem; margin-bottom: 1rem;
    }}
    h2 {{ margin: 0 0 .75rem; font-size: 1.15rem; color: #1e293b; }}
    p, li {{ font-size: .95rem; }}
    ul {{ padding-left: 1.25rem; }}
    a {{ color: var(--accent); }}
    .verdict {{
      border-left: 5px solid var(--accent); background: #eff6ff;
      padding: 1rem 1.25rem; border-radius: 0 8px 8px 0; margin: 0 0 1rem;
    }}
    table {{ width: 100%; border-collapse: collapse; font-size: .82rem; margin-top: .5rem; }}
    th, td {{ border: 1px solid var(--border); padding: .45rem .55rem; text-align: left; vertical-align: top; }}
    th {{ background: #f1f5f9; font-weight: 600; }}
    caption {{ caption-side: top; text-align: left; font-size: .82rem; color: var(--muted); margin-bottom: .35rem; }}
    th.sortable-th{{cursor:pointer;user-select:none;white-space:nowrap}}
    th.sortable-th:hover{{background:#e2e8f0}}
    th.sortable-th .sort-ind::after{{content:" \\2195";opacity:.35;font-size:.85em}}
    th.sortable-th.sort-asc .sort-ind::after{{content:" \\2191";opacity:.9}}
    th.sortable-th.sort-desc .sort-ind::after{{content:" \\2193";opacity:.9}}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; }}
    .score-hi {{ color: var(--green); }}
    .score-mid {{ color: var(--amber); }}
    .score-lo {{ color: var(--red); }}
    .footnote {{ font-size: .82rem; color: var(--muted); margin-top: 1.25rem; border-top: 1px solid var(--border); padding-top: .75rem; }}
  </style>
</head>
<body>
  <header>
    <h1>World Cup / USIC Competitors — Legitimacy Compare</h1>
    <p>Robbins World Cup, Global Cup, and U.S. Investing Championship standouts · Generated 2026-08-31 · Not financial advice · Same rubric as Desiano / Chart Fanatics</p>
  </header>

  <section>
    <div class="verdict">
      <strong>Bottom line across 16 names:</strong>
      Championship listings are the strongest verification theater in this set — but Cup/USIC % on aggressive sizing is <em>not</em> retail expectancy, and several recent-leaderboard claims failed primary-source checks.
      <br><br>
      Strongest verified pedigree: Larry Williams, Andrea Unger, Kurt Sakaeda, Mark Minervini, David Ryan, Oliver Kell, Pau Perdices Bellet, David Trullas Vila, Patrick Nill, Fabio Valentini.
      Softest / unresolved: Robert Galus (name not found on boards), Patrick Pomer (press-only pending official table), Toralf Kahlert (listed but HFT/top-Futures claim overstated).
      Highest commercial buyer-beware: Chuck Hughes (sales/refund complaints), Minervini MPA pricing, Serafini/Unger academy opacity / marketing mismatches.
    </div>
    <ul>
      <li><strong>All-time WC legends:</strong> Real titles across the board; Sakaeda/Cook lightest hard-sell; Williams historical NFA/managed-money stain; Hughes contest OK / funnel risky; Serafini 2017 win is ~217% not ~382%.</li>
      <li><strong>Recent WC boards:</strong> Bellet / Trullas / Nill / Valentini cleanest official rows; Pomer provisional; Galus unverified; Kahlert modest Forex placements only.</li>
      <li><strong>USIC:</strong> Minervini, Ryan, Kell all documented champions — books/method strong; paid SaaS/masterclass still non-fiduciary tuition.</li>
    </ul>
  </section>

  <section>
    <h2>Scoreboard (click headers to sort)</h2>
    <table class="sortable">
      <caption>Scores are opinionated /10 from public sources only. Avg = mean of five dimensions. Click column headers to sort.</caption>
      <thead>
        <tr>
          <th class="sortable-th" data-sort="text" tabindex="0" role="columnheader" aria-sort="none">Name<span class="sort-ind"></span></th>
          <th class="sortable-th" data-sort="text" tabindex="0" role="columnheader" aria-sort="none">Category<span class="sort-ind"></span></th>
          <th class="sortable-th" data-sort="num" tabindex="0" role="columnheader" aria-sort="none">Identity<span class="sort-ind"></span></th>
          <th class="sortable-th" data-sort="num" tabindex="0" role="columnheader" aria-sort="none">Transparency<span class="sort-ind"></span></th>
          <th class="sortable-th" data-sort="num" tabindex="0" role="columnheader" aria-sort="none">Verifiable perf<span class="sort-ind"></span></th>
          <th class="sortable-th" data-sort="num" tabindex="0" role="columnheader" aria-sort="none">Regulatory<span class="sort-ind"></span></th>
          <th class="sortable-th" data-sort="num" tabindex="0" role="columnheader" aria-sort="none">Value vs cost<span class="sort-ind"></span></th>
          <th class="sortable-th" data-sort="num" tabindex="0" role="columnheader" aria-sort="none">Avg<span class="sort-ind"></span></th>
          <th class="sortable-th" data-sort="text" tabindex="0" role="columnheader" aria-sort="none">Verdict<span class="sort-ind"></span></th>
        </tr>
      </thead>
      <tbody>
{body_rows}
      </tbody>
    </table>
  </section>

  <p class="footnote">Caveat: Robbins / Global Cup / USIC audited competition results ≠ managed-account returns ≠ student results. Always re-check live official standings. Not investment advice.</p>
  <script>
  (function(){{
    function parse(cell, type){{
      var t = (cell.textContent || '').trim();
      if(type==='num'){{ var n = parseFloat(t.replace(/[^0-9.+-]/g,'')); return isNaN(n) ? null : n; }}
      return t.toLowerCase();
    }}
    document.querySelectorAll('table.sortable').forEach(function(table){{
      var ths = table.querySelectorAll('th.sortable-th');
      ths.forEach(function(th, idx){{
        function activate(){{
          var type = th.getAttribute('data-sort') || 'text';
          var asc = !th.classList.contains('sort-asc');
          ths.forEach(function(h){{ h.classList.remove('sort-asc','sort-desc'); h.setAttribute('aria-sort','none'); }});
          th.classList.add(asc ? 'sort-asc' : 'sort-desc');
          th.setAttribute('aria-sort', asc ? 'ascending' : 'descending');
          var tbody = table.tBodies[0];
          var rows = Array.prototype.slice.call(tbody.rows);
          rows.sort(function(a,b){{
            var av = parse(a.cells[idx], type), bv = parse(b.cells[idx], type);
            if(av===null && bv===null) return 0;
            if(av===null) return 1;
            if(bv===null) return -1;
            if(av<bv) return asc ? -1 : 1;
            if(av>bv) return asc ? 1 : -1;
            return 0;
          }});
          rows.forEach(function(r){{ tbody.appendChild(r); }});
        }}
        th.addEventListener('click', activate);
        th.addEventListener('keydown', function(e){{ if(e.key==='Enter'||e.key===' '){{ e.preventDefault(); activate(); }} }});
      }});
    }});
  }})();
  </script>
</body>
</html>
"""
(root / "index.html").write_text(out, encoding="utf-8")
print(f"Wrote {root / 'index.html'} rows={len(rows)}")
