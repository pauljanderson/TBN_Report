#!/usr/bin/env python3
"""Drop-from-T0 findings with band-specific required dips (2026-11-04).

Research only. Does not place, cancel, or amend orders. Does not print secrets.
Does not touch orders_stopped.json. Does not start Strategy B.
Not gold. Not DailyRun.

Band rule (per side, from that side's T0 Yes):
  - T0 in [0.20, 0.49]  → required dip D = 0.05 (5¢)
  - T0 in [0.50, 0.89]  → required dip D = 0.03 (3¢)
  - Exactly 0.50 → 3¢ (upper band)
  - T0 < 0.20 or T0 ≥ 0.90 → excluded from the band rule (still shown in
    uniform-dip decile tables for comparison)

Same sources / methodology as tools/pm_drop_from_t0_decile_20261102.py:
  Book A = dense multi-venue tennis live tape (Oct 21 HTML)
  Book B = cached Kalshi 1-min yes_ask sides (hist/drop_from_t0_20261102)
  Book C = cached Polymarket CLOB last-trade sides

Default: --report-only rebuild from on-disk jsonl + dense HTML (no API pull).
Optional --pull reuses the 20261102 puller.
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import statistics as st
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import report_page_extras  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP  # noqa: E402

# Reuse loaders / summarizers / uniform THRESH from the 2026-11-02 study.
import pm_drop_from_t0_decile_20261102 as base  # noqa: E402

ET = ZoneInfo("America/New_York")
OUT_DIR = ROOT / "docs" / "prediction_market"
PAGE = OUT_DIR / "drop_from_t0_band_dips_20261104.html"
JSON_OUT = OUT_DIR / "drop_from_t0_band_dips_20261104.json"
DRIVE_PAGE = STAMP / "drop_from_t0_band_dips_20261104.html"
DRIVE_JSON = STAMP / "drop_from_t0_band_dips_20261104.json"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/drop_from_t0_band_dips_20261104.html"
)

# Prior uniform-dip report for side-by-side KPIs when present.
PRIOR_JSON = OUT_DIR / "drop_from_t0_by_decile_20261102.json"

D_LOW = 0.05   # 20–49
D_HIGH = 0.03  # 50–89

ASKED = (
    "Rerun drop-from-T0 findings with price-dependent dip thresholds: "
    "5¢ when the side’s T0 Yes is in 20–49, 3¢ when T0 Yes is in 50–89. "
    "How does gap-buy frequency and optimistic lock edge compare to the "
    "uniform-dip 2026-11-02 report (esp. both ≥5¢ / ≥10¢)?"
)
PLAIN = (
    "Same max-dip definition as 2026-11-02 (T0 Yes − min Yes after T0). "
    "Band rule assigns each side its own required dip from that side’s T0: "
    "D=5¢ on [0.20, 0.49], D=3¢ on [0.50, 0.89] (exactly 0.50 → 3¢). "
    "Sides with T0 < 0.20 or ≥ 0.90 are excluded from the band rule but remain "
    "in the uniform-dip decile tables. Both-sides band hit requires both legs "
    "eligible and each clearing its own D. Optimistic cost = T0a−Da + T0b−Db."
)


def _out(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


def esc(value) -> str:
    return html_mod.escape("" if value is None else str(value))


def now_et() -> datetime:
    return datetime.now(ET)


def required_dip(t0) -> float | None:
    """Band D from T0 Yes. None = excluded (<20¢ or ≥90¢).

    Edges (documented):
      - 0.20 inclusive → 5¢
      - 0.49 inclusive → 5¢
      - 0.50 inclusive → 3¢
      - 0.89 inclusive → 3¢
      - <0.20 or ≥0.90 → excluded
    """
    if t0 is None:
        return None
    try:
        p = float(t0)
    except (TypeError, ValueError):
        return None
    if 0.20 - 1e-12 <= p <= 0.49 + 1e-12:
        return D_LOW
    if 0.50 - 1e-12 <= p <= 0.89 + 1e-12:
        return D_HIGH
    return None


def band_label(t0) -> str | None:
    d = required_dip(t0)
    if d == D_LOW:
        return "20-49_D05"
    if d == D_HIGH:
        return "50-89_D03"
    return None


def annotate_side(side: dict) -> dict:
    row = dict(side)
    t0 = row.get("t0_px")
    d = required_dip(t0)
    row["band_label"] = band_label(t0)
    row["band_required_dip"] = d
    row["band_eligible"] = d is not None
    dip = row.get("max_dip")
    if d is None or dip is None:
        row["band_hit"] = False
    else:
        row["band_hit"] = bool(float(dip) + 1e-12 >= float(d))
    return row


def annotate_pair(pair: dict) -> dict:
    row = dict(pair)
    fa = row.get("t0_fav")
    do = row.get("t0_dog")
    da = required_dip(fa)
    dd = required_dip(do)
    row["band_D_fav"] = da
    row["band_D_dog"] = dd
    row["band_both_eligible"] = da is not None and dd is not None
    hit = False
    cost = None
    if row["band_both_eligible"]:
        hit = (
            float(row["dip_fav"]) + 1e-12 >= float(da)
            and float(row["dip_dog"]) + 1e-12 >= float(dd)
        )
        if hit:
            cost = round(float(fa) + float(do) - float(da) - float(dd), 4)
    row["band_both_hit"] = hit
    row["band_opt_cost"] = cost
    return row


def summarize_band_sides(sides: list[dict]) -> dict:
    ann = [annotate_side(s) for s in sides]
    elig = [s for s in ann if s.get("band_eligible")]
    hits = [s for s in elig if s.get("band_hit")]
    by_band: dict[str, dict] = {}
    for lab, d_req in (("20-49_D05", D_LOW), ("50-89_D03", D_HIGH)):
        bag = [s for s in ann if s.get("band_label") == lab]
        if not bag:
            by_band[lab] = {"n": 0, "required_dip": d_req}
            continue
        n_hit = sum(1 for s in bag if s.get("band_hit"))
        dips = [float(s["max_dip"]) for s in bag if s.get("max_dip") is not None]
        by_band[lab] = {
            "n": len(bag),
            "required_dip": d_req,
            "hit_n": n_hit,
            "hit_pct": round(100.0 * n_hit / len(bag), 1),
            "mean_max_dip": round(st.mean(dips), 4) if dips else None,
            "median_max_dip": round(st.median(dips), 4) if dips else None,
        }
    return {
        "n_sides": len(ann),
        "n_eligible": len(elig),
        "eligible_pct": round(100.0 * len(elig) / len(ann), 1) if ann else 0.0,
        "n_band_hit": len(hits),
        "band_hit_pct_of_eligible": (
            round(100.0 * len(hits) / len(elig), 1) if elig else None
        ),
        "band_hit_pct_of_all": (
            round(100.0 * len(hits) / len(ann), 1) if ann else None
        ),
        "by_band": by_band,
        "excluded_n": len(ann) - len(elig),
        "excluded_note": "T0 < 0.20 or T0 ≥ 0.90",
    }


def summarize_band_pairs(pairs: list[dict]) -> dict:
    ann = [annotate_pair(p) for p in pairs]
    if not ann:
        return {"n": 0}
    elig = [p for p in ann if p.get("band_both_eligible")]
    hits = [p for p in ann if p.get("band_both_hit")]
    costs = [float(p["band_opt_cost"]) for p in hits if p.get("band_opt_cost") is not None]
    # uniform comparison on same pair set
    uni = {}
    for t in base.THRESH:
        key = f"d{int(t * 100):02d}"
        both = [p for p in ann if (p.get("both_hit") or {}).get(key)]
        uni[key] = {
            "hit_pct": round(100.0 * len(both) / len(ann), 1),
            "n": len(both),
        }
    out = {
        "n": len(ann),
        "both_eligible_n": len(elig),
        "both_eligible_pct": round(100.0 * len(elig) / len(ann), 1),
        "band_both_hit_n": len(hits),
        "band_both_hit_pct_of_all": round(100.0 * len(hits) / len(ann), 1),
        "band_both_hit_pct_of_eligible": (
            round(100.0 * len(hits) / len(elig), 1) if elig else None
        ),
        "uniform_both_hit": uni,
        "opt_cost_when_band_both": (
            {
                "n": len(costs),
                "mean_cost": round(st.mean(costs), 4),
                "median_cost": round(st.median(costs), 4),
                "mean_edge_vs_1": round(1.0 - st.mean(costs), 4),
            }
            if costs
            else {"n": 0}
        ),
    }
    return out


def band_decile_rows(sides: list[dict]) -> list[dict]:
    """Per starting-price decile: n, mean/median max dip, band D, band hit%."""
    rows = []
    for band in base.DECADES:
        bag = [s for s in sides if base.decile_of(s.get("t0_px")) == band]
        if not bag:
            continue
        # representative D from band midpoint
        mid = (int(band.split("-")[0]) + 0.5) / 100.0
        d = required_dip(mid)
        ann = [annotate_side(s) for s in bag]
        elig = [s for s in ann if s.get("band_eligible")]
        hit_n = sum(1 for s in elig if s.get("band_hit"))
        summ = base.summarize_dips(bag)
        rows.append({
            "decile": band,
            "n": summ.get("n"),
            "mean": summ.get("mean"),
            "median": summ.get("median"),
            "percentiles": summ.get("percentiles"),
            "hit_pct_uniform": summ.get("hit_pct"),
            "band_required_dip": d,
            "band_eligible_n": len(elig),
            "band_hit_n": hit_n,
            "band_hit_pct": (
                round(100.0 * hit_n / len(elig), 1) if elig else None
            ),
        })
    return rows


def build_band_book(name: str, sides: list[dict], pairs: list[dict] | None = None) -> dict:
    pairs = pairs if pairs is not None else base.pair_event_sides(sides)
    # Ensure uniform both_hit keys exist (dense loader already sets them;
    # pair_event_sides also sets them).
    book = base.build_book(name, sides, pairs)
    book["band_sides"] = summarize_band_sides(sides)
    book["band_pairs"] = summarize_band_pairs(pairs)
    book["band_deciles"] = band_decile_rows(sides)
    # Tennis moneyline slice convenience
    tennis_sides = [
        s for s in sides
        if str(s.get("sport")) == "tennis" and str(s.get("kind")) == "moneyline"
    ]
    if tennis_sides and name != "A_dense_tennis_live_tape":
        tennis_pairs = base.pair_event_sides(tennis_sides)
        book["band_tennis_ml"] = {
            "sides": summarize_band_sides(tennis_sides),
            "pairs": summarize_band_pairs(tennis_pairs),
        }
    return book


def fmt_px(x) -> str:
    if x is None:
        return "—"
    return f"{100.0 * float(x):.1f}¢"


def pct(x) -> str:
    if x is None:
        return "—"
    return f"{float(x):.1f}%"


def load_prior_kpis() -> dict:
    if not PRIOR_JSON.is_file():
        return {}
    try:
        data = json.loads(PRIOR_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out = {}
    books = data.get("books") or {}
    for key in ("A_dense_tennis_live_tape", "B_kalshi_yes_ask", "C_poly_clob_last_trade"):
        b = books.get(key) or {}
        ps = b.get("pairs_summary") or {}
        out[key] = {
            "n_pairs": ps.get("n"),
            "both_d05": (ps.get("both_hit_pct") or {}).get("d05"),
            "both_d10": (ps.get("both_hit_pct") or {}).get("d10"),
            "opt_d10": (ps.get("opt_cost_when_both") or {}).get("d10"),
            "opt_d05": (ps.get("opt_cost_when_both") or {}).get("d05"),
            "overall_median": (b.get("overall") or {}).get("median"),
        }
    return out


def html_report(payload: dict) -> str:
    books = payload.get("books") or {}
    prior = payload.get("prior_uniform_20261102") or {}
    rule = payload.get("band_rule") or {}

    sections = []
    for book_name, book in books.items():
        bs = book.get("band_sides") or {}
        bp = book.get("band_pairs") or {}
        by = bs.get("by_band") or {}
        low = by.get("20-49_D05") or {}
        high = by.get("50-89_D03") or {}
        cost = bp.get("opt_cost_when_band_both") or {}
        uni = bp.get("uniform_both_hit") or {}
        prior_b = prior.get(book_name) or {}

        decile_rows = []
        for r in book.get("band_deciles") or []:
            d_req = r.get("band_required_dip")
            d_lab = "excl." if d_req is None else f"{int(round(100 * float(d_req)))}¢"
            hu = r.get("hit_pct_uniform") or {}
            p = (r.get("percentiles") or {})
            decile_rows.append(
                "<tr>"
                f"<td>{esc(r.get('decile'))}</td>"
                f"<td class='num'>{r.get('n')}</td>"
                f"<td class='num'>{fmt_px(r.get('mean'))}</td>"
                f"<td class='num'>{fmt_px(r.get('median'))}</td>"
                f"<td class='num'>{fmt_px(p.get('p75'))}</td>"
                f"<td class='num'>{esc(d_lab)}</td>"
                f"<td class='num'>{pct(r.get('band_hit_pct'))}</td>"
                f"<td class='num'>{pct(hu.get('d05'))}</td>"
                f"<td class='num'>{pct(hu.get('d10'))}</td>"
                "</tr>"
            )

        tennis_extra = ""
        tm = book.get("band_tennis_ml")
        if tm:
            tps = tm.get("pairs") or {}
            tcost = tps.get("opt_cost_when_band_both") or {}
            tennis_extra = (
                f"<p><strong>Tennis ML only:</strong> pairs N={tps.get('n')}, "
                f"band both-hit {pct(tps.get('band_both_hit_pct_of_all'))} "
                f"(N={tps.get('band_both_hit_n')}); "
                f"optimistic mean cost {fmt_px(tcost.get('mean_cost'))}, "
                f"edge {fmt_px(tcost.get('mean_edge_vs_1'))}.</p>"
            )

        sections.append(f"""
<h2>{esc(book_name)}</h2>
<div class="kpi">
  <div><strong>{pct(bs.get('band_hit_pct_of_eligible'))}</strong>Side band-hit (of eligible)</div>
  <div><strong>{pct(bp.get('band_both_hit_pct_of_all'))}</strong>Both-sides band-hit (of pairs)</div>
  <div><strong>{fmt_px(cost.get('mean_edge_vs_1'))}</strong>Mean optimistic edge when both hit</div>
  <div><strong>{pct((uni.get('d05') or {}).get('hit_pct'))}</strong>Uniform both ≥5¢</div>
  <div><strong>{pct((uni.get('d10') or {}).get('hit_pct'))}</strong>Uniform both ≥10¢</div>
</div>
<ul>
<li>Sides N={bs.get('n_sides')}; eligible (T0 20–89) N={bs.get('n_eligible')}
({pct(bs.get('eligible_pct'))}); excluded {bs.get('excluded_n')} ({esc(bs.get('excluded_note'))}).</li>
<li>20–49 / D=5¢: N={low.get('n')}, hit {pct(low.get('hit_pct'))},
median max dip {fmt_px(low.get('median_max_dip'))}.</li>
<li>50–89 / D=3¢: N={high.get('n')}, hit {pct(high.get('hit_pct'))},
median max dip {fmt_px(high.get('median_max_dip'))}.</li>
<li>Pairs N={bp.get('n')}; both legs eligible {pct(bp.get('both_eligible_pct'))}
(N={bp.get('both_eligible_n')}); band both-hit
{pct(bp.get('band_both_hit_pct_of_all'))} of all /
{pct(bp.get('band_both_hit_pct_of_eligible'))} of eligible
(N={bp.get('band_both_hit_n')}).</li>
<li>When band both-hit: mean cost {fmt_px(cost.get('mean_cost'))},
median {fmt_px(cost.get('median_cost'))}, mean edge vs $1
{fmt_px(cost.get('mean_edge_vs_1'))} (N={cost.get('n')}).</li>
<li>Prior uniform report (2026-11-02) on this book: both ≥5¢
{pct(prior_b.get('both_d05'))}, both ≥10¢ {pct(prior_b.get('both_d10'))};
10¢ mean edge {fmt_px(((prior_b.get('opt_d10') or {}).get('mean_edge_vs_1')))}.</li>
</ul>
{tennis_extra}
<div class="swipe">
<table class="sortable">
<thead><tr>
<th>T0 decile</th><th class="num">N</th><th class="num">Mean dip</th>
<th class="num">Median</th><th class="num">p75</th>
<th class="num">Band D</th><th class="num">Band hit%</th>
<th class="num">Hit≥5¢%</th><th class="num">Hit≥10¢%</th>
</tr></thead>
<tbody>
{''.join(decile_rows)}
</tbody>
</table>
</div>
""")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Drop from T0 — band-specific dips 2026-11-04</title>
<style>
body {{ font-family: Georgia, 'Times New Roman', serif; margin: 1.5rem; color: #1a1a1a;
  background: linear-gradient(#f7f4ef, #efe8dc); min-height: 100vh; }}
h1,h2,h3 {{ font-family: 'Segoe UI', system-ui, sans-serif; }}
.muted {{ color: #555; }}
.note {{ max-width: 54rem; line-height: 1.45; }}
.card {{ background: #fff; border: 1px solid #d8d0c2; border-radius: 6px;
  padding: 0.9rem 1.1rem; margin: 0.8rem 0; max-width: 54rem; }}
table {{ border-collapse: collapse; width: 100%; background: #fff; font-size: 0.88rem; }}
th, td {{ border: 1px solid #ccc; padding: 0.35rem 0.45rem; text-align: left; }}
th {{ background: #ebe4d8; }}
td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.kpi {{ display: flex; flex-wrap: wrap; gap: 0.75rem; margin: 0.75rem 0 1rem; }}
.kpi div {{ background: #fff; border: 1px solid #d8d0c2; border-radius: 6px;
  padding: 0.65rem 0.9rem; min-width: 8.5rem; }}
.kpi strong {{ display: block; font-size: 1.25rem; font-family: 'Segoe UI', system-ui, sans-serif; }}
.swipe {{ overflow-x: auto; }}
code {{ background: #f0ebe3; padding: 0.05rem 0.3rem; border-radius: 3px; }}
</style>
{report_page_extras.SORTABLE_TH_CSS}
</head>
<body>
<h1>Drop from T0 — band-specific dips (5¢ @ 20–49 / 3¢ @ 50–89)</h1>
<p class="muted">Written {esc(payload.get('written_at_et'))}. Research only. Not gold. Not DailyRun.</p>
<div class="note card">
<p><strong>Asked:</strong> {esc(ASKED)}</p>
<p>{esc(PLAIN)}</p>
<p><strong>Band rule:</strong> {esc(json.dumps(rule))}</p>
<p>{esc(payload.get('limitation') or '')}</p>
</div>
{''.join(sections)}
<p class="muted">Rebuild:
<code>python -u tools/pm_drop_from_t0_band_dips_20261104.py --report-only</code>
then
<code>python -u tools/_write_drop_from_t0_recs_20261104.py</code>.
Prior uniform page:
<code>docs/prediction_market/drop_from_t0_by_decile_20261102.html</code>.</p>
<p class="muted">Local file URL: <a href="{esc(FILE_URL)}">{esc(FILE_URL)}</a></p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""


def assemble_payload(*, report_only: bool) -> dict:
    dense_sides, dense_pairs = base.load_dense_tennis_sides()
    done = base.load_jsonl_map(base.SIDE_JSONL, "ticker")
    kalshi_sides = [r for r in done.values() if r.get("usable")]
    poly_done = base.load_jsonl_map(base.POLY_JSONL, "ticker")
    poly_sides = [r for r in poly_done.values() if r.get("usable")]

    _out(
        f"loaded dense_sides={len(dense_sides)} dense_pairs={len(dense_pairs)} "
        f"kalshi={len(kalshi_sides)} poly={len(poly_sides)}"
    )

    books = {}
    if dense_sides:
        books["A_dense_tennis_live_tape"] = build_band_book(
            "A_dense_tennis_live_tape", dense_sides, dense_pairs
        )
    if kalshi_sides:
        books["B_kalshi_yes_ask"] = build_band_book("B_kalshi_yes_ask", kalshi_sides)
    if poly_sides:
        books["C_poly_clob_last_trade"] = build_band_book(
            "C_poly_clob_last_trade", poly_sides
        )

    # Self-check required_dip edges
    assert required_dip(0.20) == D_LOW
    assert required_dip(0.49) == D_LOW
    assert required_dip(0.50) == D_HIGH
    assert required_dip(0.89) == D_HIGH
    assert required_dip(0.199) is None
    assert required_dip(0.90) is None

    return {
        "written_at_et": now_et().strftime("%Y-%m-%d %H:%M %Z"),
        "asked": ASKED,
        "plain": PLAIN,
        "band_rule": {
            "D_20_49": D_LOW,
            "D_50_89": D_HIGH,
            "inclusive_20": True,
            "inclusive_49": True,
            "exactly_50": D_HIGH,
            "inclusive_89": True,
            "exclude_lt_20": True,
            "exclude_ge_90": True,
        },
        "limitation": (
            "Optimistic both-side fills at exactly T0−D ignore queue, ask/trade gap, "
            "and fees. Band edge is thinner than uniform −10¢ (System G sketch) because "
            "D is only 3–5¢. Same source books as 2026-11-02; default rebuild is "
            "report-only from cached Kalshi/Poly jsonl + dense Oct 21 HTML. "
            "Local price_memory is not on this cloud VM."
        ),
        "prior_uniform_20261102": load_prior_kpis(),
        "books": books,
        "pull": {
            "report_only": report_only,
            "n_kalshi_sides": len(kalshi_sides),
            "n_dense_sides": len(dense_sides),
            "n_poly_sides": len(poly_sides),
            "source_jsonl": str(base.SIDE_JSONL),
            "dense_html": str(base.dense_html_path() or ""),
        },
        "comparison_verdict_seed": _verdict_seed(books),
    }


def _verdict_seed(books: dict) -> dict:
    """Compact numbers for the recs writer / Paul summary."""
    a = (books.get("A_dense_tennis_live_tape") or {}).get("band_pairs") or {}
    b = (books.get("B_kalshi_yes_ask") or {}).get("band_pairs") or {}
    bt = ((books.get("B_kalshi_yes_ask") or {}).get("band_tennis_ml") or {}).get("pairs") or {}
    return {
        "dense_band_both_hit_pct": a.get("band_both_hit_pct_of_all"),
        "dense_uniform_d05": ((a.get("uniform_both_hit") or {}).get("d05") or {}).get("hit_pct"),
        "dense_uniform_d10": ((a.get("uniform_both_hit") or {}).get("d10") or {}).get("hit_pct"),
        "dense_band_mean_edge": ((a.get("opt_cost_when_band_both") or {}).get("mean_edge_vs_1")),
        "dense_band_mean_cost": ((a.get("opt_cost_when_band_both") or {}).get("mean_cost")),
        "kalshi_all_band_both_hit_pct": b.get("band_both_hit_pct_of_all"),
        "kalshi_tennis_band_both_hit_pct": bt.get("band_both_hit_pct_of_all"),
        "kalshi_tennis_band_mean_edge": (
            (bt.get("opt_cost_when_band_both") or {}).get("mean_edge_vs_1")
        ),
    }


def write_outputs(payload: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    PAGE.write_text(html_report(payload), encoding="utf-8")
    try:
        STAMP.mkdir(parents=True, exist_ok=True)
        DRIVE_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        DRIVE_PAGE.write_text(html_report(payload), encoding="utf-8")
    except OSError as exc:
        _out(f"stamp write skipped: {exc}")
    _out(f"wrote {PAGE}")
    _out(f"wrote {JSON_OUT}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--report-only",
        action="store_true",
        default=True,
        help="Rebuild from cached jsonl + dense HTML (default)",
    )
    ap.add_argument(
        "--pull",
        action="store_true",
        help="Also run 20261102 Kalshi/Poly pull before rebuild (needs network)",
    )
    ap.add_argument("--per-series", type=int, default=60)
    ap.add_argument("--poly", action="store_true")
    ap.add_argument("--poly-events", type=int, default=40)
    args = ap.parse_args()

    if args.pull:
        ns = argparse.Namespace(
            per_series=args.per_series,
            tennis_only=False,
            poly=args.poly,
            poly_events=args.poly_events,
            series=None,
            report_only=False,
        )
        _out("running base pull (20261102)…")
        base.run_pull(ns)

    payload = assemble_payload(report_only=not args.pull)
    write_outputs(payload)
    seed = payload.get("comparison_verdict_seed") or {}
    _out(
        "verdict_seed "
        + json.dumps(seed, sort_keys=True)
    )


if __name__ == "__main__":
    main()
