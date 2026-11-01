"""Written A–E recs from the combined Kalshi+Poly T0 decile page.

Report only. Does not place, cancel, or sell. Does not print secrets.
Does not start a second Tennis crossover (B). Does not leftover-GTC A.
Does not DailyRun. Does not retune live B/C/D/E. Does not rewrite dashboard.html.
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
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import report_page_extras  # noqa: E402
import t0_all_games_stats as t0  # noqa: E402
from compare_format import format_money  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP  # noqa: E402

ET = ZoneInfo("America/New_York")
SUB = STAMP / "kalshi_poly_combined_t0_decile_20261030"
SCORE = SUB / "slice_score.json"
PAGE = STAMP / "combined_t0_decile_system_recs_20261030.html"
PARENT = STAMP / "kalshi_poly_combined_t0_decile_20261030.html"
BASELINE = SUB / "RECS_BASELINE.md"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/combined_t0_decile_system_recs_20261030.html"
)

ASKED = (
    "OK. this is better. thank you. this mimics more what we have in reality. "
    "take a look at these results you just gave me, do your own analysis. tell me "
    "if you would recommend changes to any of our systems AND would you recommend "
    "any others?"
)
PLAIN = (
    "We sat with the combined Kalshi + Polymarket opening-price table — cheaper "
    "ticket after the shop’s take-a-trade fee when both listed the same game, "
    "otherwise the one shop — and asked two ordinary questions: should any of the "
    "five live systems change, and should we start a new one? A lock gap is Yes on "
    "one shop and No on the other when the pair is cheap enough. B tennis is both "
    "Yes at listed start if the pair is cheap enough, plus a resting dip order. C "
    "is college-football favorite moneyline (who wins the game) in 51–89 cents. D "
    "is favorite-to-cover spreads (whether a team beats a point line), skipping "
    "the National Football League (NFL), not Points Total (the over/under on "
    "combined score). E is tennis underdog moneyline, cheapest of four shops, "
    "skip if B already has the match. This tape starts April 2025, so there is no "
    "pre-2024 comparison. Polymarket history here is a last trade, not an ask. "
    "We did not change live code."
)
ANN = "omitted (same-day)"
ANN_NOTE = (
    "Ann ROR omitted — average days held is 0.0000 (same-day contracts; house "
    "formula would overflow on a near-zero hold)."
)
IS_NOTE = "n/a — no IS (all T0 ≥ 2024-01-01; this tape starts Apr 2025)"

HEADERS = [
    ("System", "text"),
    ("Tested by this book?", "text"),
    ("Advice", "text"),
    ("Slice used", "text"),
    ("N settled", "num"),
    ("Wins", "num"),
    ("Win%", "num"),
    ("With-fee P&L", "num"),
    ("Avg with-fee P&L", "num"),
    ("Ann ROR full", "text"),
    ("Ann ROR IS", "text"),
    ("Ann ROR OOS", "text"),
    ("Why", "text"),
]
CELL_HEADERS = [
    ("Book", "text"),
    ("Sport", "text"),
    ("Bet type", "text"),
    ("Decile", "text"),
    ("N settled", "num"),
    ("Wins", "num"),
    ("Win%", "num"),
    ("With-fee P&L", "num"),
    ("Avg with-fee P&L", "num"),
    ("Ann ROR full", "text"),
    ("Ann ROR IS", "text"),
    ("Ann ROR OOS", "text"),
    ("Note", "text"),
]
NEW_HEADERS = [
    ("Idea", "text"),
    ("One-sentence rule", "text"),
    ("N", "num"),
    ("Win%", "num"),
    ("Avg with-fee P&L", "num"),
    ("With-fee P&L", "num"),
    ("Turn on?", "text"),
    ("Why it is or is not just a selected green cell", "text"),
]


def esc(text) -> str:
    return html_mod.escape(str(text or ""), quote=True)


def money(value) -> str:
    if value is None:
        return "—"
    return format_money(value)


def avg_s(value) -> str:
    if value is None:
        return "—"
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):.4f}"


def pct(value) -> str:
    if value is None:
        return "—"
    return f"{value:.1f}"


def rec_row(rec: dict, extra: dict | None = None) -> list[str]:
    extra = extra or {}
    return [
        extra.get("system", ""),
        extra.get("tested", ""),
        extra.get("advice", ""),
        extra.get("slice", ""),
        str(rec.get("n") or 0) if rec else "—",
        str(rec.get("wins") or 0) if rec else "—",
        pct(rec.get("wr")) if rec else "—",
        money(rec.get("pnl")) if rec else "—",
        avg_s(rec.get("avg")) if rec else "—",
        ANN,
        IS_NOTE,
        ANN,
        extra.get("why", ""),
    ]


def cell_rows(book: str, rec: dict, note: str = "") -> list[list[str]]:
    rows = []
    for c in rec.get("cells") or []:
        rows.append(
            [
                book,
                c.get("sport") or "",
                c.get("kind") or "",
                c.get("decile") or "",
                str(c.get("n") or 0),
                str(c.get("wins") or 0),
                pct(c.get("wr")),
                money(c.get("pnl")),
                avg_s(c.get("avg")),
                ANN,
                IS_NOTE,
                ANN,
                note,
            ]
        )
    rows.append(
        [
            book,
            "pooled",
            rec.get("cells", [{}])[0].get("kind") if rec.get("cells") else "",
            extra_decile(rec),
            str(rec.get("n") or 0),
            str(rec.get("wins") or 0),
            pct(rec.get("wr")),
            money(rec.get("pnl")),
            avg_s(rec.get("avg")),
            ANN,
            IS_NOTE,
            ANN,
            "pooled from the cells above",
        ]
    )
    rows[-1]  # total-row applied by caller via class — t0.table total=
    return rows


def extra_decile(rec: dict) -> str:
    decs = [c.get("decile") for c in rec.get("cells") or [] if c.get("decile")]
    return ", ".join(decs) if decs else "—"


def pool_cells(cells: list[dict], deciles=None, sports=None) -> dict:
    n = w = pnl = 0.0
    kept = []
    for c in cells:
        if deciles and c.get("decile") not in deciles:
            continue
        if sports and c.get("sport") not in sports:
            continue
        n += c.get("n") or 0
        w += c.get("wins") or 0
        pnl += c.get("pnl") or 0
        kept.append(c)
    return {
        "n": int(n),
        "wins": int(w),
        "wr": (100.0 * w / n) if n else None,
        "nfee": int(n),
        "pnl": round(pnl, 4),
        "avg": (pnl / n) if n else None,
        "cells": kept,
    }


def main() -> str:
    score = json.loads(SCORE.read_text(encoding="utf-8"))
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET")
    c = score["C_cfb_ml_fav_50_89_both"]
    c70 = score["C_cfb_ml_70_89_both"]
    c_cheap = score["C_cfb_ml_fav_50_89_cheap"]
    d = score["D_spread_fav_50_89_ex_nfl_both"]
    d_cfb = score["D_cfb_spread_50_89_both"]
    d_cfb50 = score["D_cfb_spread_50_59_both"]
    d_cfb60 = score["D_cfb_spread_60_89_both"]
    d_hock = score["D_hockey_spread_50_89_both"]
    d_nfl = score["D_nfl_spread_50_89_both"]
    e = score["E_tennis_ml_10_49_cheap"]
    e0 = score["E_tennis_ml_0_49_cheap"]
    hockey40 = score["hockey_ml_40_49_cheap"]
    nfl_dog = score["nfl_ml_10_39_cheap"]
    t_spr = score["tennis_spread_10_49_cheap"]
    d50 = pool_cells(d["cells"], deciles=["50-59"])
    d_by = score["D_by_sport"]

    ae_rows = [
        rec_row(
            None,
            {
                "system": "A lock gap",
                "tested": "No",
                "advice": "not tested — no change",
                "slice": "not in this book",
                "why": "A is Yes on one shop + No on the other, after-fee ≤ $0.99, 1 contract, sequential. This book is one named Yes held to settlement. Dual-min’s tiny plus (N=2977, avg +$0.002) is overlap selection of the cheaper Yes, not a lock.",
            },
        ),
        rec_row(
            None,
            {
                "system": "B tennis crossover",
                "tested": "No",
                "advice": "not tested — HOLD D=0.25",
                "slice": "not in this book",
                "why": "B is both Yes at T0 if after-fee ≤ $1.05, 50-cross, Good-Til-Cancelled (GTC) dip D=0.25. This book is one-sided hold-to-settle. Prior dog+GTC-fav sweep was all D red. Tennis moneyline hold-to-settle being red here does not retune D.",
            },
        ),
        rec_row(
            c,
            {
                "system": "C CFB fav ML 51–89",
                "tested": "Yes — both-sides CFB moneyline 50–89 (not cheaper-Yes 0–49)",
                "advice": "HOLD 51–89",
                "slice": "college football · Moneyline · 50-59 + 60-69 + 70-79 + 80-89, both named Yes",
                "why": "Pooled avg +$0.0147 on N=1162, WR 73.0%. Thin plus. 60–69 is red. Cheaper-Yes 50–89 is N=18 (wrong book — C buys the favorite). Do not tighten to 70–89 from this table.",
            },
        ),
        rec_row(
            d,
            {
                "system": "D T0 spreads fav-to-cover 51–89, no NFL, not Points Total",
                "tested": "Yes — both-sides Spread 50–89 excluding pro football (sheet is a superset of live closest-to-50¢)",
                "advice": "HOLD 51–89",
                "slice": "Spread · 50-89 · exclude pro football / NFL · not Points Total",
                "why": f"Full 50–89 blob is red (N={d['n']}, avg {avg_s(d['avg'])}). Live D picks the line closest to 50¢, so 50–59 is the closer analog (N={d50['n']}, avg {avg_s(d50['avg'])}, thin plus, CFB-driven). CFB 60–89 is a large loser. Do not tighten to 60–89.",
            },
        ),
        rec_row(
            e,
            {
                "system": "E tennis T0 dog 11–49",
                "tested": "Yes — cheaper-Yes tennis moneyline 10–19 / 20–29 / 30–39 / 40–49",
                "advice": "HOLD 11–49",
                "slice": "tennis · Moneyline · 10-49 on the combined cheaper ticket",
                "why": "Every 10-cent dog bucket is red after fees (pooled N=13331, WR 30.5%, avg −$0.0262). Live 11-day tape was still green last we heard; this book is last-trade not ask, and does not apply cheapest-of-4 or skip-if-B. Do not widen to 0–49. Do not stop live from this page alone.",
            },
        ),
    ]
    # first two rows have empty N — rec_row(None) used "—" via `if rec else`
    # but rec_row with rec=None still fills N as "—" good.

    c_cell_rows = cell_rows("both-sides combined", c, "C lives on the favorite side")
    c_cell_rows = c_cell_rows[:-1]  # drop auto pooled; add labeled pooled + 70-89
    c_cell_rows.append(
        [
            "both-sides combined",
            "college football",
            "Moneyline",
            "50-89 pooled (live C analog, sheet includes 50.0)",
            str(c["n"]),
            str(c["wins"]),
            pct(c["wr"]),
            money(c["pnl"]),
            avg_s(c["avg"]),
            ANN,
            IS_NOTE,
            ANN,
            "HOLD 51–89. Thin plus. Mixed buckets.",
        ]
    )
    c_cell_rows.append(
        [
            "both-sides combined",
            "college football",
            "Moneyline",
            "70-89 (tighter band after seeing the table)",
            str(c70["n"]),
            str(c70["wins"]),
            pct(c70["wr"]),
            money(c70["pnl"]),
            avg_s(c70["avg"]),
            ANN,
            IS_NOTE,
            ANN,
            "selection on this same table. N halves. Do not retune.",
        ]
    )
    c_cell_rows.append(
        [
            "cheaper-Yes combined (wrong book for C)",
            "college football",
            "Moneyline",
            "50-89",
            str(c_cheap["n"]),
            str(c_cheap["wins"]),
            pct(c_cheap["wr"]),
            money(c_cheap["pnl"]),
            avg_s(c_cheap["avg"]),
            ANN,
            IS_NOTE,
            ANN,
            "mostly dogs leftover. Do not score C here.",
        ]
    )

    d_sport_rows = []
    for sport, rec in d_by.items():
        d_sport_rows.append(
            [
                "both-sides combined",
                sport,
                "Spread",
                "50-89",
                str(rec["n"]),
                str(rec["wins"]),
                pct(rec["wr"]),
                money(rec["pnl"]),
                avg_s(rec["avg"]),
                ANN,
                IS_NOTE,
                ANN,
                "D skip NFL already applied in this rollup",
            ]
        )
    d_sport_rows.append(
        [
            "both-sides combined",
            "ALL non-NFL",
            "Spread",
            "50-89 pooled",
            str(d["n"]),
            str(d["wins"]),
            pct(d["wr"]),
            money(d["pnl"]),
            avg_s(d["avg"]),
            ANN,
            IS_NOTE,
            ANN,
            "sheet superset of live closest-to-50¢",
        ]
    )
    d_sport_rows.append(
        [
            "both-sides combined",
            "ALL non-NFL",
            "Spread",
            "50-59 only (closest-to-50¢ analog)",
            str(d50["n"]),
            str(d50["wins"]),
            pct(d50["wr"]),
            money(d50["pnl"]),
            avg_s(d50["avg"]),
            ANN,
            IS_NOTE,
            ANN,
            "thin plus, CFB 50–59 driven. Not a KEEP of a tighter band.",
        ]
    )
    d_sport_rows.append(
        [
            "both-sides combined",
            "college football",
            "Spread",
            "50-59",
            str(d_cfb50["n"]),
            str(d_cfb50["wins"]),
            pct(d_cfb50["wr"]),
            money(d_cfb50["pnl"]),
            avg_s(d_cfb50["avg"]),
            ANN,
            IS_NOTE,
            ANN,
            "selected green cell on this table",
        ]
    )
    d_sport_rows.append(
        [
            "both-sides combined",
            "college football",
            "Spread",
            "60-89",
            str(d_cfb60["n"]),
            str(d_cfb60["wins"]),
            pct(d_cfb60["wr"]),
            money(d_cfb60["pnl"]),
            avg_s(d_cfb60["avg"]),
            ANN,
            IS_NOTE,
            ANN,
            "do not move live D here",
        ]
    )
    d_sport_rows.append(
        [
            "both-sides combined",
            "hockey",
            "Spread",
            "50-89",
            str(d_hock["n"]),
            str(d_hock["wins"]),
            pct(d_hock["wr"]),
            money(d_hock["pnl"]),
            avg_s(d_hock["avg"]),
            ANN,
            IS_NOTE,
            ANN,
            "green sport slice; selecting hockey-only D is the same table",
        ]
    )
    d_sport_rows.append(
        [
            "both-sides combined (D skips NFL)",
            "pro football",
            "Spread",
            "50-89",
            str(d_nfl["n"]),
            str(d_nfl["wins"]),
            pct(d_nfl["wr"]),
            money(d_nfl["pnl"]),
            avg_s(d_nfl["avg"]),
            ANN,
            IS_NOTE,
            ANN,
            "shown so the skip still has a number; not a D send",
        ]
    )

    d_cell_rows = cell_rows("both-sides combined", d, "exclude NFL / pro football")
    d_cell_rows = d_cell_rows[:-1]

    e_cell_rows = cell_rows("cheaper-Yes combined", e, "live E analog (sheet includes 10.0)")
    e_cell_rows = e_cell_rows[:-1]
    e_cell_rows.append(
        [
            "cheaper-Yes combined",
            "tennis",
            "Moneyline",
            "10-49 pooled",
            str(e["n"]),
            str(e["wins"]),
            pct(e["wr"]),
            money(e["pnl"]),
            avg_s(e["avg"]),
            ANN,
            IS_NOTE,
            ANN,
            "all four buckets red. HOLD 11–49. Do not stop live from this page.",
        ]
    )
    e_cell_rows.append(
        [
            "cheaper-Yes combined",
            "tennis",
            "Moneyline",
            "0-49 (wider)",
            str(e0["n"]),
            str(e0["wins"]),
            pct(e0["wr"]),
            money(e0["pnl"]),
            avg_s(e0["avg"]),
            ANN,
            IS_NOTE,
            ANN,
            "WR 30.5% → 23.4%. Do not add 0–9.",
        ]
    )

    new_rows = [
        [
            "None live",
            "I would not turn on a new one-contract hold-to-settle system from this one history table.",
            "—",
            "—",
            "—",
            "—",
            "No",
            "Default: do not add a live system from one hist horse-race. Highlighting green sport × bet × decile cells on this same page is selection bias. Dual-min’s tiny plus is overlap selection. Poly last-trade ≠ ask.",
        ],
        [
            "Tennis cheaper spread 10–49 (paper / next test only)",
            "Tennis T0 cheaper named spread Yes in 10–49¢, 1 contract, after-fee, hold to settle.",
            str(t_spr["n"]),
            pct(t_spr["wr"]),
            avg_s(t_spr["avg"]),
            money(t_spr["pnl"]),
            "I would not turn it on yet",
            "Largest quality+N green family on the cheaper-Yes book (20–29 avg +$0.11 N=188; 30–39 avg +$0.06 N=680; 40–49 avg +$0.02 N=1192). Still a selected green family on this same table. Last-trade ≠ ask. Tennis spread is a point/set line, not moneyline E.",
        ],
        [
            "NFL moneyline 10–39 cheaper Yes",
            "Pro football T0 cheaper named Yes in 10–39¢, 1 contract, after-fee, hold to settle.",
            str(nfl_dog["n"]),
            pct(nfl_dog["wr"]),
            avg_s(nfl_dog["avg"]),
            money(nfl_dog["pnl"]),
            "I would not turn it on yet",
            "Avg +$0.048 looks fine until you see N=155 split across three buckets. Named on the combined page already. Selected cell group.",
        ],
        [
            "Hockey moneyline 40–49 cheaper Yes",
            "Hockey T0 cheaper named Yes in 40–49¢, 1 contract, after-fee, hold to settle.",
            str(hockey40["n"]),
            pct(hockey40["wr"]),
            avg_s(hockey40["avg"]),
            money(hockey40["pnl"]),
            "I would not turn it on yet",
            "N=1027 is real; avg +$0.005 after fees is a half-cent. Quality over N: too thin. Named on the combined page already.",
        ],
        [
            "CFB spread 50–59 only (D subset)",
            "College football T0 favorite-to-cover spread Yes in 50–59¢, 1 contract, after-fee, hold to settle.",
            str(d_cfb50["n"]),
            pct(d_cfb50["wr"]),
            avg_s(d_cfb50["avg"]),
            money(d_cfb50["pnl"]),
            "I would not turn it on yet",
            "Best single cell on the D-relevant book (avg +$0.068, N=871). Picking it after seeing 60–89 go red is the same table. Live D already prefers closest-to-50¢. Do not retune D.",
        ],
    ]

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>Combined T0 decile — A–E recommendations (30 Oct)</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.callout.hold {{ border-color: #c4b5fd; background: #f5f3ff; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
h1 {{ margin: 0 0 0.4rem; }}
h2 {{ margin: 1.4rem 0 0.5rem; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
{report_page_extras.FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Combined T0 cheapest-ticket decile — would I change A–E, or add another?</h1>
<p class="note">Written {esc(now)}. Written recommendation only. Did not retune live A–E.
Did not start a second B. Did not leftover-GTC A. Did not DailyRun. Did not rewrite dashboard.html.
Click column headers to sort.</p>

<div class="callout"><h2>What you asked</h2><p>{esc(ASKED)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{esc(PLAIN)}</p></div>

<div class="callout hold">
<h2>Verdict — no live changes. I would not add another system.</h2>
<p>I would leave A–E alone. A and B are not tested by this hold-to-settle book.
C’s <em>favorite</em> college-football moneyline 50–89 slice is a thin plus
(N=1162, WR 73.0%, avg +$0.0147) — HOLD 51–89, do not tighten. D’s full
favorite-spread 50–89 blob excluding NFL is red (N=8438, avg −$0.0142); the
closer analog to live “closest line to 50¢” is 50–59, a thin plus driven by
college football — HOLD 51–89, do not move to 60–89. E’s tennis cheaper
moneyline 10–49 is red in every bucket (N=13331, avg −$0.0262) — HOLD 11–49
because the live 11-day tape was still green and this book is not E’s exact
rule (last-trade, no skip-if-B, no cheapest-of-4). I would not turn on a new
one-contract hold-to-settle system from this one table. Tennis cheaper spread
10–49 is the least-bad next test (N=2094, avg +$0.0418) and I would not turn
it on yet — it is a selected green family on this same page.</p>
</div>

<p class="note">Source:
<a href="kalshi_poly_combined_t0_decile_20261030.html">kalshi_poly_combined_t0_decile_20261030.html</a>
(Kalshi T0 Yes-ask + Polymarket T0 last-trade; cheaper after-fee when both listed
the same game; else the one shop; hold to settle). Book starts ~Apr 2025. In-sample
versus 2024-01-01 is empty (N=0). Treat the whole tape as one out-of-sample-ish
history. Quality (win%, with-fee average P&amp;L) over N. Do not judge on max
single trade. Dual-min tiny plus is overlap selection. Poly last-trade ≠ ask.
{esc(ANN_NOTE)}</p>

<h2>1. Each of A–E</h2>
{report_page_extras.SWIPE_NOTE_HTML}
{t0.table(HEADERS, ae_rows)}

<h2>C — college football moneyline favorite (score the favorite, not cheaper-Yes)</h2>
<p class="note">Live C is <code>0.50 &lt; px &lt; 0.90</code> (51–89¢). The cheaper-Yes
book is mostly dogs, so C is scored on <strong>both named Yes sides</strong>,
college football moneyline 50–89. Kalshi-only history had said C was unprofitable
(N=27, avg −$0.14). This combined book is the new evidence: a thin plus, mixed
buckets. HOLD the live 51–89 freeze. Tightening to 70–89 after seeing 60–69 go
red is selection on this table.</p>
{report_page_extras.SWIPE_NOTE_HTML}
{t0.table(CELL_HEADERS, c_cell_rows)}

<h2>D — T0 spreads, favorite to cover, no NFL, not Points Total</h2>
<p class="note">Live D skips NFL / pro football and Points Total, and takes the
one line closest to 50¢ (<code>pick_spread_line</code>). The sheet below is every
favorite-side spread Yes in 50–89, so it is a superset. Full 50–89 is red. The
50–59 analog (closest to how live D actually picks) is a thin plus driven by
college football 50–59. College football 60–89 is a large loser — that is why
I will not recommend moving D to 60–89. Hockey spreads are green as a sport
slice; cutting D to hockey-only after seeing this table is the same selection.
Live 11-day D was still green last Paul heard. HOLD 51–89.</p>
<h3>D rollups</h3>
{report_page_extras.SWIPE_NOTE_HTML}
{t0.table(CELL_HEADERS, d_sport_rows)}
<h3>D by 10-cent bucket (non-NFL spread, both-sides)</h3>
{report_page_extras.SWIPE_NOTE_HTML}
{t0.table(CELL_HEADERS, d_cell_rows)}

<h2>E — tennis moneyline underdog on the combined cheaper ticket</h2>
<p class="note">Live E is tennis T0 dog 11–49¢, cheapest of four shops, skip if B
already holds the match. This book scores tennis moneyline 10–19 / 20–29 / 30–39 /
40–49 on the combined cheaper Yes. Every bucket loses after fees. Adding 0–9
drops win% from 30.5 to 23.4. Live 11-day E was still green last Paul heard;
Kalshi-only hist had already said E was unprofitable. Combined hist agrees with
Kalshi-only on the sign. I still HOLD rather than stop: the live tape disagrees,
and this book is last-trade without skip-if-B / cheapest-of-4. Do not widen.</p>
{report_page_extras.SWIPE_NOTE_HTML}
{t0.table(CELL_HEADERS, e_cell_rows)}

<h2>A and B — not tested</h2>
<p class="note">A lock gap (Yes on one shop + No on the other, after-fee ≤ $0.99,
1 contract, sequential) is a two-leg pair. This T0-hold book never buys the other
side. No change to A from this page. Do not leftover-GTC A.</p>
<p class="note">B tennis (both Yes at listed start / T0 if after-fee ≤ $1.05;
50-cross; Good-Til-Cancelled (GTC) dip D=0.25) is not a one-sided hold-to-settle.
Tennis moneyline hold-to-settle being red here does not speak to the GTC favorite
fill. Prior dog+GTC-fav D sweep was all red. HOLD D=0.25. Did not start a second B.</p>

<h2>2. Any new system I would actually run?</h2>
<p class="note">No live add. Default stance: do not add a live system from one
history horse-race. Highlighting green sport × bet type × decile cells from this
same table is selection bias. Dual-min only (N=2977, avg +$0.002) is overlap
selection on games both shops listed — not a send rule. If a later test is
wanted, tennis cheaper spread 10–49 is the least-bad paper / next test, and I
would not turn it on yet.</p>
{report_page_extras.SWIPE_NOTE_HTML}
{t0.table(NEW_HEADERS, new_rows)}

<h2>Process</h2>
<ul>
<li>IS vs OOS: IS = entry_date &lt; 2024-01-01. This book starts April 2025, so
IS N=0. The whole tape is one out-of-sample-ish history. Do not retune on it.
KEEP / HOLD / DISMISS on this page is advice, not a live wire.</li>
<li>Cheaper-Yes is the main identity (one named Yes per market, usually 0–49).
C and D buy favorites, so they are scored on the both-sides 50–89 slice. E is
scored on cheaper-Yes tennis moneyline 10–49.</li>
<li>Kalshi T0 is Yes-ask. Polymarket T0 on this hist is last-trade on the global
Central Limit Order Book (CLOB), not an ask, not Polymarket US. Live C/D/E buy
asks. Sign disagreement between this book and the 11-day live tape can be that
gap, or short-tape variance.</li>
<li>Live D also requires a unique favorite and the line closest to 50¢. Live E
also requires a unique cheaper of four and skip-if-B. Those filters are not on
this sheet.</li>
<li>Annualized rate of return uses the house formula
<code>((1 + total_pnl / (brt_cash × n_trades)) ** (365 / avg_days_held) − 1) × 100</code>
and is omitted because hist end clock = T0 (same-day overflow guard).</li>
<li>Did not turn live systems off in code. Did not start a second B. Did not
leftover-GTC A. Did not DailyRun. Did not rewrite dashboard.html.</li>
</ul>

<p class="tiny">Parent:
<a href="kalshi_poly_combined_t0_decile_20261030.html">combined cheapest T0 decile (30 Oct)</a> · <a href="system_f_tennis_spread_20261030.html">F Tennis spread (30 Oct)</a>
· freeze <code>kalshi_poly_combined_t0_decile_20261030/BASELINE.md</code>
· cells <code>kalshi_poly_combined_t0_decile_20261030/slice_score.json</code>.
Generator: <code>tools/_write_combined_t0_decile_system_recs_20261030.py</code>.
File URL {esc(FILE_URL)}.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(html, encoding="utf-8")

    recs_md = f"""# Combined T0 decile — A–E written recs (30 Oct)

Written {now}. Advice only. Live A–E knobs were not patched.

## What you asked

{ASKED}

## In plain English

{PLAIN}

## Verdict

- **A** not tested — no change. This book is one-sided hold-to-settle, not Yes+No.
- **B** not tested — HOLD D=0.25. This book is not both-Yes + GTC. Prior D sweep all red.
- **C** HOLD 51–89. Both-sides CFB moneyline 50–89: N={c['n']} WR={c['wr']:.1f}% avg={c['avg']:.4f} pnl={c['pnl']:.2f}. Thin plus. Do not tighten to 70–89.
- **D** HOLD 51–89. Both-sides non-NFL spread 50–89: N={d['n']} WR={d['wr']:.1f}% avg={d['avg']:.4f} (red blob). 50–59 analog N={d50['n']} avg={d50['avg']:.4f} (thin plus). CFB 60–89 avg={d_cfb60['avg']:.4f}. Do not move to 60–89.
- **E** HOLD 11–49. Cheaper tennis ML 10–49: N={e['n']} WR={e['wr']:.1f}% avg={e['avg']:.4f}. All four buckets red. Do not widen. Do not stop live from this page.
- **New live system:** no. Tennis cheaper spread 10–49 is paper / next test only (N={t_spr['n']} avg={t_spr['avg']:.4f}); I would not turn it on yet.

Did not start a second B, leftover-GTC A, DailyRun, or rewrite dashboard.html.
"""
    BASELINE.write_text(recs_md, encoding="utf-8")

    parent = PARENT.read_text(encoding="utf-8")
    needle = (
        '<p class="tiny">Parent: <a href="sport_league_t0_decile_20261027.html">'
        "sport / league / T0 decile (27 Oct)</a>"
    )
    insert = (
        '<p class="note">Written recommendation (30 Oct): '
        '<a href="combined_t0_decile_system_recs_20261030.html">'
        "would I change A–E, or add another?</a> "
        "Advice only — live A–E were not patched from that page.</p>\n"
        + needle
    )
    if "combined_t0_decile_system_recs_20261030.html" not in parent:
        if needle not in parent:
            raise SystemExit("parent footer needle missing")
        parent = parent.replace(needle, insert, 1)
        top = (
            "Did not rewrite dashboard.html.</p>"
        )
        top_ins = (
            "Did not rewrite dashboard.html. "
            '<a href="combined_t0_decile_system_recs_20261030.html">'
            "A–E recommendations (30 Oct)</a>.</p>"
        )
        if top not in parent:
            raise SystemExit("parent top needle missing")
        parent = parent.replace(top, top_ins, 1)
        PARENT.write_text(parent, encoding="utf-8")

    freeze = (SUB / "BASELINE.md").read_text(encoding="utf-8")
    pointer = (
        "\n## Written recs (30 Oct, later the same morning)\n\n"
        "Paul asked for analysis of this combined book vs live A–E, and whether "
        "to add another system. Advice page: "
        "`combined_t0_decile_system_recs_20261030.html`. "
        "A not tested. B not tested (HOLD D=0.25). C HOLD 51–89. D HOLD 51–89. "
        "E HOLD 11–49. No new live system. Live knobs were not patched.\n"
    )
    if "Written recs (30 Oct" not in freeze:
        (SUB / "BASELINE.md").write_text(freeze.rstrip() + "\n" + pointer, encoding="utf-8")

    print("wrote", PAGE)
    return str(PAGE)


if __name__ == "__main__":
    main()
