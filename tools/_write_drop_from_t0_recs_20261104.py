#!/usr/bin/env python3
"""Write Paul-facing band-dip drop-from-T0 recommendations (2026-11-04).

Research only. Does not place, cancel, or amend orders. Does not print secrets.
Does not retune live A–E. Not gold. Not DailyRun.
"""
from __future__ import annotations

import html as html_mod
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import report_page_extras  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP  # noqa: E402

ET = ZoneInfo("America/New_York")
SRC = ROOT / "docs" / "prediction_market" / "drop_from_t0_band_dips_20261104.json"
OUT_DOCS = ROOT / "docs" / "prediction_market" / "drop_from_t0_recs_20261104.html"
OUT_STAMP = STAMP / "drop_from_t0_recs_20261104.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/drop_from_t0_recs_20261104.html"
)


def esc(v) -> str:
    return html_mod.escape("" if v is None else str(v))


def fmt_cents(x) -> str:
    if x is None:
        return "—"
    return f"{100.0 * float(x):.1f}¢"


def pct(x) -> str:
    if x is None:
        return "—"
    return f"{float(x):.1f}%"


def main() -> None:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    books = data.get("books") or {}
    dense = books.get("A_dense_tennis_live_tape") or {}
    kalshi = books.get("B_kalshi_yes_ask") or {}
    poly = books.get("C_poly_clob_last_trade") or {}
    seed = data.get("comparison_verdict_seed") or {}
    prior = data.get("prior_uniform_20261102") or {}
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M %Z")

    dens_sides = dense.get("band_sides") or {}
    dens_pairs = dense.get("band_pairs") or {}
    dens_cost = dens_pairs.get("opt_cost_when_band_both") or {}
    dens_by = dens_sides.get("by_band") or {}
    dens_low = dens_by.get("20-49_D05") or {}
    dens_high = dens_by.get("50-89_D03") or {}
    dens_uni = dens_pairs.get("uniform_both_hit") or {}

    kal_pairs = kalshi.get("band_pairs") or {}
    kal_tennis = (kalshi.get("band_tennis_ml") or {}).get("pairs") or {}
    kal_t_cost = kal_tennis.get("opt_cost_when_band_both") or {}
    poly_pairs = poly.get("band_pairs") or {}
    poly_cost = poly_pairs.get("opt_cost_when_band_both") or {}

    prior_a = prior.get("A_dense_tennis_live_tape") or {}
    prior_d10_edge = ((prior_a.get("opt_d10") or {}).get("mean_edge_vs_1"))

    # Decile table for dense
    decile_rows = []
    for r in dense.get("band_deciles") or []:
        d_req = r.get("band_required_dip")
        d_lab = "excl." if d_req is None else f"{int(round(100 * float(d_req)))}¢"
        hu = r.get("hit_pct_uniform") or {}
        p = r.get("percentiles") or {}
        decile_rows.append(
            "<tr>"
            f"<td>{esc(r.get('decile'))}</td>"
            f"<td class='num'>{r.get('n')}</td>"
            f"<td class='num'>{fmt_cents(r.get('mean'))}</td>"
            f"<td class='num'>{fmt_cents(r.get('median'))}</td>"
            f"<td class='num'>{fmt_cents(p.get('p75'))}</td>"
            f"<td class='num'>{esc(d_lab)}</td>"
            f"<td class='num'>{pct(r.get('band_hit_pct'))}</td>"
            f"<td class='num'>{pct(hu.get('d05'))}</td>"
            f"<td class='num'>{pct(hu.get('d10'))}</td>"
            "</tr>"
        )

    cmp_rows = []
    for label, bp, prior_key in (
        ("Dense tennis live tape", dens_pairs, "A_dense_tennis_live_tape"),
        ("Kalshi all-sports pairs", kal_pairs, "B_kalshi_yes_ask"),
        ("Kalshi tennis ML pairs", kal_tennis, "B_kalshi_yes_ask"),
        ("Poly CLOB last-trade", poly_pairs, "C_poly_clob_last_trade"),
    ):
        if not bp.get("n"):
            continue
        uni = bp.get("uniform_both_hit") or {}
        cost = bp.get("opt_cost_when_band_both") or {}
        pr = prior.get(prior_key) or {}
        cmp_rows.append(
            "<tr>"
            f"<td>{esc(label)}</td>"
            f"<td class='num'>{bp.get('n')}</td>"
            f"<td class='num'>{pct(bp.get('band_both_hit_pct_of_all'))}</td>"
            f"<td class='num'>{pct((uni.get('d05') or {}).get('hit_pct'))}</td>"
            f"<td class='num'>{pct((uni.get('d10') or {}).get('hit_pct'))}</td>"
            f"<td class='num'>{fmt_cents(cost.get('mean_edge_vs_1'))}</td>"
            f"<td class='num'>{fmt_cents(cost.get('mean_cost'))}</td>"
            f"<td class='num'>{pct(pr.get('both_d10'))}</td>"
            f"<td class='num'>{fmt_cents(((pr.get('opt_d10') or {}).get('mean_edge_vs_1')))}</td>"
            "</tr>"
        )

    # Verdict logic for Paul
    dense_band = dens_pairs.get("band_both_hit_pct_of_all")
    dense_d10 = (dens_uni.get("d10") or {}).get("hit_pct")
    dense_d05 = (dens_uni.get("d05") or {}).get("hit_pct")
    band_edge = dens_cost.get("mean_edge_vs_1")
    freq_vs_10 = (
        "higher" if dense_band is not None and dense_d10 is not None and dense_band > dense_d10
        else "lower/similar"
    )
    edge_vs_10 = (
        "thinner"
        if band_edge is not None and prior_d10_edge is not None and band_edge < prior_d10_edge
        else "similar/wider"
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Drop from T0 — band dips findings &amp; recs (4 Nov 2026)</title>
<style>
body {{ font-family: Georgia, 'Times New Roman', serif; margin: 1.5rem; color: #1a1a1a;
  background: linear-gradient(#f7f4ef, #efe8dc); min-height: 100vh; }}
h1,h2,h3 {{ font-family: 'Segoe UI', system-ui, sans-serif; }}
.muted {{ color: #555; }}
.note {{ max-width: 54rem; line-height: 1.45; }}
.card {{ background: #fff; border: 1px solid #d8d0c2; border-radius: 6px;
  padding: 0.9rem 1.1rem; margin: 0.8rem 0; max-width: 54rem; }}
.rec {{ border-left: 4px solid #2f6f4e; }}
.hold {{ border-left: 4px solid #8a6d3b; }}
.skip {{ border-left: 4px solid #8a3b3b; }}
.warn {{ border-left: 4px solid #8a6d3b; }}
table {{ border-collapse: collapse; width: 100%; background: #fff; font-size: 0.88rem; }}
th, td {{ border: 1px solid #ccc; padding: 0.35rem 0.45rem; text-align: left; }}
th {{ background: #ebe4d8; }}
td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.kpi {{ display: flex; flex-wrap: wrap; gap: 0.75rem; margin: 0.75rem 0 1rem; }}
.kpi div {{ background: #fff; border: 1px solid #d8d0c2; border-radius: 6px;
  padding: 0.65rem 0.9rem; min-width: 8.5rem; }}
.kpi strong {{ display: block; font-size: 1.35rem; font-family: 'Segoe UI', system-ui, sans-serif; }}
.swipe {{ overflow-x: auto; }}
code {{ background: #f0ebe3; padding: 0.05rem 0.3rem; border-radius: 3px; }}
a {{ color: #1f4d7a; }}
</style>
{report_page_extras.SORTABLE_TH_CSS}
</head>
<body>
<h1>Band-specific drop from T0 — findings &amp; what to try</h1>
<p class="muted">Written {esc(now)}. Source rebuild {esc(data.get('written_at_et'))}.
Research only. Not gold. Not DailyRun. Did not retune live A–E.</p>

<div class="note">
<p><strong>Rule under test:</strong> required dip D = <strong>5¢</strong> when that side’s
T0 Yes is in <strong>20–49</strong>; D = <strong>3¢</strong> when T0 Yes is in
<strong>50–89</strong> (exactly 0.50 → 3¢). T0 &lt; 20¢ or ≥ 90¢ excluded from the
band rule. Same books as the 2 Nov uniform-dip report.</p>
</div>

<div class="kpi">
  <div><strong>{pct(dense_band)}</strong>Dense both band-hit</div>
  <div><strong>{pct(dense_d10)}</strong>Dense both ≥10¢ (uniform)</div>
  <div><strong>{fmt_cents(band_edge)}</strong>Band mean optimistic edge</div>
  <div><strong>{fmt_cents(prior_d10_edge)}</strong>Prior ≥10¢ mean edge</div>
  <div><strong>{pct(kal_tennis.get('band_both_hit_pct_of_all'))}</strong>Kalshi tennis band both-hit</div>
</div>

<h2>Verdict in one paragraph</h2>
<div class="note card">
<p>On dense tennis, 5¢@20–49 / 3¢@50–89 is <strong>{esc(freq_vs_10)} frequency</strong>
than the uniform −10¢ System G sketch ({pct(dense_band)} both-hit vs
{pct(dense_d10)} both ≥10¢; also vs {pct(dense_d05)} both ≥5¢), but the optimistic
lock edge is <strong>{esc(edge_vs_10)}</strong>
({fmt_cents(band_edge)} mean edge / mean cost {fmt_cents(dens_cost.get('mean_cost'))}
vs prior −10¢ mean edge {fmt_cents(prior_d10_edge)}). Single-side band hits are
common (20–49 hit {pct(dens_low.get('hit_pct'))}; 50–89 hit
{pct(dens_high.get('hit_pct'))}). Kalshi ask tape is colder: tennis ML band both-hit
only {pct(kal_tennis.get('band_both_hit_pct_of_all'))}, mean edge
{fmt_cents(kal_t_cost.get('mean_edge_vs_1'))} — fees (~2¢) eat most of that.
<strong>Net:</strong> better fill frequency than −10¢ dual-dip, worse edge per fill;
paper as a high-frequency thin-gap sleeve, not a replacement for the −10¢ near-50
lock candidate until a realistic fill+fee replay is green.</p>
</div>

<h2>Recommendations</h2>

<div class="card rec">
<h3>1. TRY (paper): System G′ — band-D dual dip (5¢/3¢)</h3>
<p><strong>Rule sketch:</strong> Tennis moneyline. At T0, require <em>each</em> Yes in
20–89¢ (skip &lt;20 / ≥90). Rest / watch for side A fill ≤ T0A − D(A) and side B
≤ T0B − D(B), with D=5¢ on 20–49 and D=3¢ on 50–89. When both marked filled, hold
Yes+Yes to settlement (or define flatten).</p>
<p><strong>Why:</strong> Dense both-hit {pct(dense_band)} of {dens_pairs.get('n')} pairs
({pct(dens_pairs.get('band_both_hit_pct_of_eligible'))} of both-eligible). Much more
often than −10¢ ({pct(dense_d10)}). Mean optimistic edge
{fmt_cents(band_edge)} before fees.</p>
<p><strong>Gate before live:</strong> Same as 2 Nov — realistic ask+fee fill model,
IS/OOS on larger Kalshi in-play book. Do <strong>not</strong> wire beside B until that
page is green. Expect fees to wipe ~2¢ of the ~{fmt_cents(band_edge)} edge.</p>
<p><strong>A/B vs G:</strong> Keep uniform T=10¢ (25–75 band) as control; G′ is the
band-D variant. Compare realized fill rate, all-in cost, and with-fee EV — not just
max-dip hit rates.</p>
</div>

<div class="card warn">
<h3>2. HOLD / do not prefer G′ over G on edge</h3>
<p>Band dips win on <em>frequency</em>, lose on <em>edge thickness</em>. Prior uniform
−10¢ optimistic mean edge was {fmt_cents(prior_d10_edge)}; band rule is
{fmt_cents(band_edge)}. If the kitchen needs ~10¢+ theoretical lock after fees,
stay with near-50 −10¢ (or −8/−12 A/B) rather than 3–5¢ band D.</p>
</div>

<div class="card rec">
<h3>3. TRY (research): One-side band dump add</h3>
<p>Buy one Yes the first time that side clears its band D (5¢ or 3¢), without waiting
for the other leg. Dense single-side band-hit of eligible =
{pct(dens_sides.get('band_hit_pct_of_eligible'))}. Directional — needs with-fee EV by
band and fav/dog before any stake.</p>
</div>

<div class="card hold">
<h3>4. HOLD live A–E as-is</h3>
<ul>
<li>This page does not retune B’s post-cross fav D=0.25 or C/D/E T0 freezes.</li>
<li>Still skip 90/10 dual-dip locks; band rule already excludes ≥90 and &lt;20.</li>
</ul>
</div>

<div class="card skip">
<h3>5. SKIP</h3>
<ul>
<li><strong>Treating Kalshi ask both-hit like dense tape.</strong> Kalshi tennis band
both-hit {pct(kal_tennis.get('band_both_hit_pct_of_all'))} vs dense
{pct(dense_band)} — different book microstructure.</li>
<li><strong>Assuming 3¢ fav dips clear fees.</strong> Mean band edge on dense is only
{fmt_cents(band_edge)}; on Kalshi tennis {fmt_cents(kal_t_cost.get('mean_edge_vs_1'))}.</li>
</ul>
</div>

<h2>Comparison table (band vs uniform)</h2>
<div class="swipe">
<table class="sortable">
<thead><tr>
<th>Book</th><th class="num">N pairs</th>
<th class="num">Band both-hit%</th>
<th class="num">Uniform ≥5¢%</th><th class="num">Uniform ≥10¢%</th>
<th class="num">Band mean edge</th><th class="num">Band mean cost</th>
<th class="num">Prior ≥10¢%</th><th class="num">Prior ≥10¢ edge</th>
</tr></thead>
<tbody>
{''.join(cmp_rows)}
</tbody>
</table>
</div>

<h2>Dense tennis — max dip by T0 decile + band D</h2>
<p class="muted">Band hit% only for deciles inside 20–89 (excl. = outside rule).
Uniform ≥5¢ / ≥10¢ shown for comparison.</p>
<div class="swipe">
<table class="sortable">
<thead><tr>
<th>T0 decile</th><th class="num">N</th><th class="num">Mean</th><th class="num">Median</th>
<th class="num">p75</th><th class="num">Band D</th><th class="num">Band hit%</th>
<th class="num">≥5¢</th><th class="num">≥10¢</th>
</tr></thead>
<tbody>
{''.join(decile_rows)}
</tbody>
</table>
</div>

<h2>Band composition (dense)</h2>
<ul>
<li>Eligible sides: {dens_sides.get('n_eligible')} / {dens_sides.get('n_sides')}
({pct(dens_sides.get('eligible_pct'))}); excluded {dens_sides.get('excluded_n')}.</li>
<li>20–49 / D=5¢: N={dens_low.get('n')}, hit {pct(dens_low.get('hit_pct'))},
median max dip {fmt_cents(dens_low.get('median_max_dip'))}.</li>
<li>50–89 / D=3¢: N={dens_high.get('n')}, hit {pct(dens_high.get('hit_pct'))},
median max dip {fmt_cents(dens_high.get('median_max_dip'))}.</li>
<li>Poly last-trade both band-hit {pct(poly_pairs.get('band_both_hit_pct_of_all'))},
mean edge {fmt_cents(poly_cost.get('mean_edge_vs_1'))} (small N={poly_pairs.get('n')}).</li>
</ul>

<h2>How this was measured</h2>
<div class="note">
<ul>
<li>Same methodology as
<code>docs/prediction_market/drop_from_t0_by_decile_20261102.html</code>.</li>
<li>Band machine table:
<code>docs/prediction_market/drop_from_t0_band_dips_20261104.html</code></li>
<li>Rebuild:
<code>python -u tools/pm_drop_from_t0_band_dips_20261104.py --report-only</code>
then
<code>python -u tools/_write_drop_from_t0_recs_20261104.py</code></li>
</ul>
<p class="muted">{esc(data.get('limitation'))}</p>
<p class="muted">Seed: {esc(json.dumps(seed))}</p>
</div>

<p class="muted">Local file URL on Paul’s PC: <a href="{esc(FILE_URL)}">{esc(FILE_URL)}</a></p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""

    OUT_DOCS.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOCS.write_text(html, encoding="utf-8")
    try:
        STAMP.mkdir(parents=True, exist_ok=True)
        OUT_STAMP.write_text(html, encoding="utf-8")
        stamp_msg = str(OUT_STAMP)
    except OSError as exc:
        stamp_msg = f"(stamp write failed: {exc})"
    print(f"wrote {OUT_DOCS}")
    print(f"wrote {stamp_msg}")
    print(f"file_url {FILE_URL}")


if __name__ == "__main__":
    main()
