#!/usr/bin/env python3
"""Write Paul-facing drop-from-T0 HTML report + system recommendations.

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
SRC = ROOT / "docs" / "prediction_market" / "drop_from_t0_by_decile_20261102.json"
OUT_DOCS = ROOT / "docs" / "prediction_market" / "drop_from_t0_recs_20261102.html"
OUT_STAMP = STAMP / "drop_from_t0_recs_20261102.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/drop_from_t0_recs_20261102.html"
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


def slice_row(book: dict, sport: str, kind: str, decile: str) -> dict | None:
    for r in book.get("slices") or []:
        if r.get("sport") == sport and r.get("kind") == kind and r.get("decile") == decile:
            return r
    return None


def main() -> None:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    books = data.get("books") or {}
    dense = books.get("A_dense_tennis_live_tape") or {}
    kalshi = books.get("B_kalshi_yes_ask") or {}
    poly = books.get("C_poly_clob_last_trade") or {}
    case = data.get("kolar_moeller") or {}
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M %Z")

    dens_ov = dense.get("overall") or {}
    dens_pairs = dense.get("pairs_summary") or {}
    dens_role = dense.get("role_overlay") or {}
    kal_role = kalshi.get("role_overlay") or {}

    tennis_decile_rows = []
    for band in (
        "10-19", "20-29", "30-39", "40-49", "50-59",
        "60-69", "70-79", "80-89", "90-99",
    ):
        r = slice_row(dense, "tennis", "moneyline", band)
        if not r:
            continue
        p = r.get("percentiles") or {}
        h = r.get("hit_pct") or {}
        tennis_decile_rows.append(
            "<tr>"
            f"<td>{esc(band)}</td>"
            f"<td class='num'>{r.get('n')}</td>"
            f"<td class='num'>{fmt_cents(r.get('mean'))}</td>"
            f"<td class='num'>{fmt_cents(r.get('median'))}</td>"
            f"<td class='num'>{fmt_cents(p.get('p25'))}</td>"
            f"<td class='num'>{fmt_cents(p.get('p75'))}</td>"
            f"<td class='num'>{fmt_cents(p.get('p90'))}</td>"
            f"<td class='num'>{pct(h.get('d05'))}</td>"
            f"<td class='num'>{pct(h.get('d10'))}</td>"
            f"<td class='num'>{pct(h.get('d15'))}</td>"
            f"<td class='num'>{pct(h.get('d20'))}</td>"
            f"<td class='num'>{pct(h.get('d25'))}</td>"
            "</tr>"
        )

    both_rows = []
    for key, label in (
        ("d05", "≥5¢"),
        ("d10", "≥10¢"),
        ("d15", "≥15¢"),
        ("d20", "≥20¢"),
        ("d25", "≥25¢"),
    ):
        hit = (dens_pairs.get("both_hit_pct") or {}).get(key)
        cost = (dens_pairs.get("opt_cost_when_both") or {}).get(key) or {}
        both_rows.append(
            "<tr>"
            f"<td>{esc(label)}</td>"
            f"<td class='num'>{pct(hit)}</td>"
            f"<td class='num'>{cost.get('n') or 0}</td>"
            f"<td class='num'>{fmt_cents(cost.get('mean_cost'))}</td>"
            f"<td class='num'>{fmt_cents(cost.get('median_cost'))}</td>"
            f"<td class='num'>{fmt_cents(cost.get('mean_edge_vs_1'))}</td>"
            "</tr>"
        )

    sport_specs = [
        ("tennis", "moneyline", "Tennis ML", dense, "Dense live"),
        ("tennis", "moneyline", "Tennis ML", kalshi, "Kalshi ask"),
        ("tennis", "moneyline", "Tennis ML", poly, "Poly trade"),
        ("pro football", "moneyline", "NFL ML", kalshi, "Kalshi ask"),
        ("pro football", "spread", "NFL spread", kalshi, "Kalshi ask"),
        ("pro football", "total", "NFL total", kalshi, "Kalshi ask"),
        ("college football", "moneyline", "CFB ML", kalshi, "Kalshi ask"),
        ("college football", "spread", "CFB spread", kalshi, "Kalshi ask"),
        ("college football", "total", "CFB total", kalshi, "Kalshi ask"),
        ("baseball", "moneyline", "MLB ML", kalshi, "Kalshi ask"),
    ]
    sport_rows = []
    for sport, kind, label, book, book_name in sport_specs:
        r = slice_row(book, sport, kind, "ALL")
        if not r:
            continue
        h = r.get("hit_pct") or {}
        sport_rows.append(
            "<tr>"
            f"<td>{esc(label)}</td>"
            f"<td>{esc(book_name)}</td>"
            f"<td class='num'>{r.get('n')}</td>"
            f"<td class='num'>{fmt_cents(r.get('mean'))}</td>"
            f"<td class='num'>{fmt_cents(r.get('median'))}</td>"
            f"<td class='num'>{pct(h.get('d10'))}</td>"
            f"<td class='num'>{pct(h.get('d15'))}</td>"
            "</tr>"
        )

    case_lis = []
    for s in case.get("sides") or []:
        case_lis.append(
            f"<li><strong>{esc(s.get('name'))}</strong>: T0 {fmt_cents(s.get('t0_px'))}, "
            f"min after T0 {fmt_cents(s.get('min_px'))}, "
            f"max dip {fmt_cents(s.get('max_dip'))}</li>"
        )

    near = dens_role.get("near_50_deciles_40_59") or {}
    far = dens_role.get("far_deciles_0_19_or_80_99") or {}
    fav = dens_role.get("favorite") or {}
    dog = dens_role.get("dog") or {}
    kal_near = kal_role.get("near_50_deciles_40_59") or {}
    kal_far = kal_role.get("far_deciles_0_19_or_80_99") or {}

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Drop from T0 — findings &amp; system recommendations (2 Nov 2026)</title>
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
<h1>Drop from starting price (T0) — findings &amp; what to try next</h1>
<p class="muted">Written {esc(now)}. Source rebuild {esc(data.get('written_at_et'))}.
Research only. Not gold. Not DailyRun. Did not retune live A–E.</p>

<div class="note">
<p><strong>Question:</strong> If we buy gaps by waiting for each side to cheapen from
its opening price — like Kolar 29%→18% and Moeller 79%→63%, buy at −10pp each —
what can we get away with on average, by percentile, and by starting-price decile?</p>
</div>

<div class="kpi">
  <div><strong>{fmt_cents(dens_ov.get('median'))}</strong>Tennis median max dip</div>
  <div><strong>{fmt_cents(dens_ov.get('mean'))}</strong>Tennis mean max dip</div>
  <div><strong>{pct((dens_pairs.get('both_hit_pct') or {}).get('d10'))}</strong>Both sides ≥10¢</div>
  <div><strong>{fmt_cents((near.get('median')))}</strong>Near-50 median dip</div>
  <div><strong>{fmt_cents((far.get('median')))}</strong>Lopsided median dip</div>
</div>

<h2>Verdict in one paragraph</h2>
<div class="note card">
<p>On tennis, players <em>do</em> routinely cheapen after T0 — median max dip
<strong>{fmt_cents(dens_ov.get('median'))}</strong>, mean
<strong>{fmt_cents(dens_ov.get('mean'))}</strong> (dense live tape, N={dens_ov.get('n')} sides).
Your coin-flip hypothesis is correct: 40–59¢ openers median-dip about
<strong>{fmt_cents(near.get('median'))}</strong>, while 0–19 / 80–99 openers only
about <strong>{fmt_cents(far.get('median'))}</strong>. A simultaneous −10¢ buy on
<em>both</em> sides appears in about
<strong>{pct((dens_pairs.get('both_hit_pct') or {}).get('d10'))}</strong> of matches;
optimistic cost ~0.82 before fees (~18¢ theoretical lock). That is a real research
candidate — not a free lunch, and not something to underwrite on 90/10 matches.</p>
</div>

<h2>Recommendations — new systems to try</h2>

<div class="card rec">
<h3>1. TRY (paper / research first): Tennis dual-dip gap — System “G”</h3>
<p><strong>Rule sketch:</strong> At T0 on tennis moneyline, require both Yes asks in
<strong>25–75¢</strong> (skip lopsided). Independently rest / watch for each side’s
first print ≤ T0 − <strong>10¢</strong>. When <em>both</em> have filled (or been
marked filled on the research tape), you own Yes+Yes with target cost ≤ ~0.90
after ~2¢ fees. Hold to settlement (or flatten if all-in blows out — define later).</p>
<p><strong>Why:</strong> Dense tape both-hit ≥10¢ =
{pct((dens_pairs.get('both_hit_pct') or {}).get('d10'))} of {dens_pairs.get('n')} pairs;
mean optimistic edge ~{fmt_cents(((dens_pairs.get('opt_cost_when_both') or {}).get('d10') or {}).get('mean_edge_vs_1'))}
before fees. Near-50 is where the dips live.</p>
<p><strong>Gate before live:</strong> Replay with realistic fill model (touch ask +
documented taker fee, no exact T0−T fills). Require IS/OOS split on a larger Kalshi
in-play book. Do <strong>not</strong> wire beside B until that page is green.</p>
<p><strong>Variant to A/B:</strong> T=8¢ and T=12¢; band 30–70 vs 25–75; require
T0 all-in ≤ 1.05 (live B door) vs no door.</p>
</div>

<div class="card rec">
<h3>2. TRY (research): Independent one-side dip add — not a lock</h3>
<p><strong>Rule sketch:</strong> Same T0 band filter. Buy <em>one</em> extra Yes the
first time <em>that</em> player dips 10¢ / 15¢ from T0 — without waiting for the
other side. This is a directional add, not a gap lock.</p>
<p><strong>Why:</strong> Single-side ≥10¢ hit rate on dense tennis is
{pct((dens_ov.get('hit_pct') or {}).get('d10'))} — much higher than both-side.
Useful as a “buy the dump” sleeve, but PnL depends on whether the dumper recovers
or dies. Dense dip-extra pages already exist; this would be a band-restricted
rerun, not a new kitchen.</p>
<p><strong>Gate:</strong> Must show with-fee EV by decile and by favorite vs dog
before any live stake.</p>
</div>

<div class="card rec">
<h3>3. TRY (research): CFB Points Total dip / gain sleeve</h3>
<p><strong>Why:</strong> On this Kalshi pull, CFB totals had the jumpiest team-sport
tape (median dip ~17.5¢, ≥10¢ hit ~73%, N=40). That is small-N but loud enough to
justify a dedicated hist path study (buy T0 total Yes in 40–60, sell +G or ride).</p>
<p><strong>Gate:</strong> Expand N well past 40; separate Over vs Under; do not mix
with CFB moneyline or spread.</p>
</div>

<div class="card hold">
<h3>4. HOLD live A–E as-is from this page</h3>
<ul>
<li><strong>B</strong> (tennis crossover + fav dip D=0.25): this study is about
pre-cross dual dips from T0, not the post-cross fav GTC. Do not change D from here.</li>
<li><strong>C / D / E</strong> T0 band holds from the 30 Oct decile recs still stand.
This page does not reopen those freezes.</li>
</ul>
</div>

<div class="card skip">
<h3>5. SKIP / do not build</h3>
<ul>
<li><strong>90/10 dual-dip locks.</strong> Lopsided openers barely both-dip.
Dense far-decile median dip only {fmt_cents(far.get('median'))}; Kalshi far median
{fmt_cents(kal_far.get('median'))}.</li>
<li><strong>NFL spread dip factory.</strong> Kalshi NFL spread median max dip 0¢ in
this sample; sticky.</li>
<li><strong>Assuming Kolar/Moeller −10¢ both is typical every match.</strong>
Today Moeller only dipped ~7.5¢ from listed T0 on Poly last-trade.</li>
</ul>
</div>

<h2>Kolar vs Moeller (today)</h2>
<div class="note card">
<p>{esc(case.get('note'))}</p>
<ul>
{''.join(case_lis)}
</ul>
</div>

<h2>Tennis — max dip by T0 decile (dense live tape)</h2>
<p class="muted">Max dip = T0 Yes − minimum in-play Yes after kickoff. Hit% = share of
sides whose max dip cleared that threshold.</p>
<div class="swipe">
<table class="sortable">
<thead><tr>
<th>T0 decile</th><th class="num">N</th><th class="num">Mean</th><th class="num">Median</th>
<th class="num">p25</th><th class="num">p75</th><th class="num">p90</th>
<th class="num">≥5¢</th><th class="num">≥10¢</th><th class="num">≥15¢</th>
<th class="num">≥20¢</th><th class="num">≥25¢</th>
</tr></thead>
<tbody>
{''.join(tennis_decile_rows)}
</tbody>
</table>
</div>

<h2>Both-sides gap (dense tennis pairs, N={dens_pairs.get('n')})</h2>
<p class="muted">Optimistic: if both max-dips clear T, assume fills at exactly T0−T.
Ignores queue, ask/trade gap, and fees.</p>
<div class="swipe">
<table class="sortable">
<thead><tr>
<th>Both sides dip</th><th class="num">Hit % of matches</th><th class="num">N both-hit</th>
<th class="num">Mean cost</th><th class="num">Median cost</th><th class="num">Mean edge vs $1</th>
</tr></thead>
<tbody>
{''.join(both_rows)}
</tbody>
</table>
</div>

<h2>Favorite / dog / near-50 overlay (dense tennis)</h2>
<ul>
<li>Favorites: N={fav.get('n')}, mean {fmt_cents(fav.get('mean'))}, median {fmt_cents(fav.get('median'))}</li>
<li>Dogs: N={dog.get('n')}, mean {fmt_cents(dog.get('mean'))}, median {fmt_cents(dog.get('median'))}</li>
<li>Near coin-flip (40–59): N={near.get('n')}, median {fmt_cents(near.get('median'))}</li>
<li>Lopsided (0–19 or 80–99): N={far.get('n')}, median {fmt_cents(far.get('median'))}</li>
<li>Kalshi all-sports check: near-50 median {fmt_cents(kal_near.get('median'))} vs
lopsided {fmt_cents(kal_far.get('median'))}</li>
</ul>

<h2>Sport / bet type snapshot</h2>
<div class="swipe">
<table class="sortable">
<thead><tr>
<th>Market</th><th>Book</th><th class="num">N</th><th class="num">Mean dip</th>
<th class="num">Median</th><th class="num">Hit ≥10¢</th><th class="num">Hit ≥15¢</th>
</tr></thead>
<tbody>
{''.join(sport_rows)}
</tbody>
</table>
</div>

<h2>How this was measured</h2>
<div class="note">
<ul>
<li><strong>Book A</strong> — dense multi-venue tennis live tape (Oct 21), already
T0-labeled with max dip per side.</li>
<li><strong>Book B</strong> — Kalshi 1-minute Yes-ask candles from occurrence clock
to close; skip bad clocks (occurrence ≥ close); require ≥5 post-T0 bars.</li>
<li><strong>Book C</strong> — Polymarket CLOB last-trade (not ask).</li>
<li>Full machine table:
<code>docs/prediction_market/drop_from_t0_by_decile_20261102.html</code></li>
<li>Rebuild:
<code>python -u tools/pm_drop_from_t0_decile_20261102.py --per-series 40 --poly</code>
then
<code>python -u tools/_write_drop_from_t0_recs_20261102.py</code></li>
</ul>
<p class="muted">{esc(data.get('limitation'))}</p>
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
