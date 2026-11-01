"""Namigata vs Yoshimoto Polymarket autopsy HTML. Does not place orders."""
from __future__ import annotations

import html
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from prediction_paths import DRIVE_STAMP as STAMP  # noqa: E402
from report_page_extras import (  # noqa: E402
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
    inject_report_page_extras,
)

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "namigata_poly_20261024.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/namigata_poly_20261024.html"
)

ASKED = (
    "Paul's Polymarket portfolio popup: Junri Namigata vs. Natsuki Yoshimoto. "
    "Bought Namigata, Junri. Cost $0.19 @ 58%. To win $0.32. Account jollycobra4517, "
    "portfolio ~$34.19. He does not know which system. Open-count sync just dropped "
    "Namigata as a B phantom (Poly qty 0). He is looking at a live You bought toast — "
    "so that drop was likely wrong. Same family as Guajardo: HTTP/activities vs empty "
    "Poly positions list. Karim/Guidotti was fail-soft kept; Namigata was dropped. "
    "Fix that inconsistency. House tape every B/A/C/D send. Fetch Poly activities. "
    "Verdict. Restore if still unsettled. Do not sell. Do not flatten. Do not start a "
    "second live_strategy_b.py."
)


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def table(headers: list[tuple[str, str]], rows: list[list[str]], totals: list[str] | None = None) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{cells}</tr>")
    if totals:
        cells = "".join(f"<td>{cell}</td>" for cell in totals)
        body.append(f'<tr class="total-row">{cells}</tr>')
    return (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def main(b_pid: str = "", checked: str = "") -> None:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    b_pid = b_pid or "see job_status"
    checked = checked or now
    compare = table(
        [
            ("When ET", "date"),
            ("System", "text"),
            ("Player / side we meant", "text"),
            ("Poly wire", "text"),
            ("Limit", "num"),
            ("IOC", "text"),
            ("HTTP", "num"),
            ("Tape qty", "num"),
            ("Confirm at send", "text"),
            ("Poly activities now", "text"),
            ("Same?", "text"),
            ("House fill (≥1)?", "text"),
            ("Note", "text"),
        ],
        [
            [
                "2026-10-24 20:04:31",
                "B T0",
                "Yes Natsuki Yoshimoto (favorite, Yes ask 0.81)",
                "BUY_SHORT / Sold Yes Namigata @ 0.19 = 1 − 0.81",
                "0.190",
                "IOC",
                "200",
                "1",
                "activities GET qty 1.0000 @ 0.1900 order DA4V3W5011KJ",
                "1.0000 @ 0.19 aggressor DA4V3W5011KJ",
                "Same",
                "Yes",
                "House Yes Yoshimoto. Poly UI Sold Yes Namigata / Bought No. Not the 0.32 toast.",
            ],
            [
                "2026-10-24 20:04:31",
                "B T0",
                "Yes Junri Namigata (dog, Yes ask 0.29)",
                "BUY_LONG Yes Namigata @ 0.29",
                "0.290",
                "IOC",
                "200",
                "0.32",
                "activities GET qty 0.3200 (not house fill) @ 0.2900 order DA4V6VTG31MQ",
                "0.3200 @ 0.29 aggressor DA4V6VTG31MQ",
                "Same",
                "No — real 0.32 ticket",
                "Book only had 0.32 (quote_size 0.32). Partial is Paul's You bought toast.",
            ],
            [
                "2026-10-24 20:05:23",
                "B flatten",
                "Unwind filled Yes Yoshimoto (buy Yes Namigata)",
                "BUY_LONG Yes Namigata @ 0.56",
                "0.560",
                "IOC",
                "200",
                "1",
                "activities GET empty; this-order cumQuantity 1 @ 0.5600 order DA4VGMG011TB",
                "1.0000 @ 0.56 aggressor DA4VGMG011TB (history caught up)",
                "Same",
                "Yes",
                "Nets against the BUY_SHORT. Positions net leftover is the 0.32 Yes Namigata.",
            ],
        ],
    )
    systems = table(
        [
            ("System", "text"),
            ("Sent this match?", "text"),
            ("Why"),
        ]
        if False
        else [
            ("System", "text"),
            ("Sent this match?", "text"),
            ("Why", "text"),
        ],
        [
            ["A Lock gap", "No", "No lock-bot pair. B tennis-b keys only. one_leg_watch has no Namigata row."],
            [
                "B tennis crossover",
                "Yes",
                "strategy_b_watch tennis_namigayoshim_2026_10_24. T0 both-Yes + flatten of the filled Yoshimoto leg.",
            ],
            ["C CFB favorite", "No", "College football only. cfb_favorite_watch has no Namigata/Yoshimoto."],
            ["D T0 spreads", "No", "College football spreads only. spread_t0_watch has no this match."],
        ],
    )
    ui = table(
        [
            ("House", "text"),
            ("Poly wire / UI", "text"),
            ("Same market?", "text"),
        ],
        [
            [
                "Yes Yoshimoto @ 0.81 (BUY_SHORT 0.19)",
                "Sold Yes Namigata (~81¢) or Bought No Namigata @ 0.19",
                "Yes — one binary. Yes = Namigata. BUY_SHORT is the other seat.",
            ],
            [
                "Yes Namigata @ 0.29 qty 0.32",
                "Bought Yes · Namigata, Junri. Toast: cost $0.19 @ 58%, to win $0.32",
                "Yes. 0.32 × ~58¢ mark = $0.1856 ≈ $0.19. Fill was 29¢, not 58¢.",
            ],
            [
                "Flatten BUY_LONG Namigata @ 0.56 qty 1",
                "Bought Yes Namigata @ 56¢, nets vs the short",
                "Yes. Positions GET net 0.3200 Yes Namigata, expired false, MARKET_STATE_OPEN.",
            ],
        ],
    )
    mtm = table(
        [
            ("Slice", "text"),
            ("Qty", "num"),
            ("Fill / mark", "text"),
            ("Cash", "num"),
            ("Note", "text"),
        ],
        [
            ["T0 Yes Namigata leftover", "0.32", "fill 0.29 / bid 0.20 / ask 0.56", "0.0928", "Tiny. Bid mark slightly down; ask mark up. Toast 58% is the offer, not the fill."],
            ["T0 Yes Yoshimoto (short Namigata)", "1", "0.19 No / 0.81 Yes", "0.1900", "Flattened by the 0.56 BUY_LONG."],
            ["Flatten Yes Namigata", "1", "0.56", "0.5600", "Locks the short. Net positions drop this 1 vs 1."],
            ["Fees (θ 0.0695, tape)", "", "0.01 + 0.01 + ~0.02", "0.04", "Banker's cent. Exact cents from IOC / watch."],
        ],
        ["Net still open", "0.32 Yes Namigata", "bid 0.20 / ask 0.56", "~$0.09 at risk", "Did not sell. Did not flatten again."],
    )
    phantom = table(
        [
            ("Case", "text"),
            ("Poly positions GET", "text"),
            ("Confirm / activities", "text"),
            ("t0 filled flags", "text"),
            ("Old open-count", "text"),
            ("After fix", "text"),
        ],
        [
            [
                "Karim vs Guidotti",
                "slug missing (Yes+No can net 0)",
                "qty 1 + qty 1",
                "both True",
                "fail-soft keep if the whole Poly list is empty",
                "per-slug fail-soft still keeps a confirm fill when this slug is missing",
            ],
            [
                "Namigata vs Yoshimoto",
                "net 0.3200 Yes Namigata (filtered out because qty &lt; 1)",
                "0.32 activities + cumQuantity 0.32",
                "both False (flatten cleared the Yoshimoto flag)",
                "phantom drop — empty-looking book, fill_qty path required ≥ 1 and t0_filled",
                "0.32 is open B. Empty positions + activities 0.32 stays open.",
            ],
            [
                "Guajardo vs Brain (settled)",
                "empty after 50¢ expiry",
                "last leftover fill_qty 0",
                "Brain True historically",
                "phantom (correct after settlement)",
                "still phantom — no current confirm qty on the leftover",
            ],
        ],
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
{CACHE_META}
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Namigata vs Yoshimoto Poly — 24 Oct 2026</title>
{FORCE_RELOAD_SCRIPT}
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 24px; color: #1e293b; line-height: 1.45; }}
h1 {{ font-size: 1.7rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.25rem; margin-top: 1.7rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 12px 0; }}
.callout h2 {{ margin: 0 0 6px; }}
.warn {{ background: #fff7ed; border-color: #fdba74; }}
.ok {{ background: #f0fdf4; border-color: #86efac; }}
.note {{ color: #475569; font-size: 0.95rem; }}
code {{ font-size: 0.9em; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Junri Namigata vs Natsuki Yoshimoto — which system, and the phantom drop</h1>
<p class="note">Written {esc(now)}. Times America/New_York (EDT, UTC−4) on 2026-10-24. Research live. Not gold. Not DailyRun. No sells. No second Strategy B. No secrets.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>A Yes ticket pays $1 if that tennis player wins. <strong>Strategy B (tennis crossover)</strong> at the first trusted start (T0) tries to buy one Yes on each woman when the two Yes prices add up to something in the allowed band. Size 1. Immediate or Cancel (fill now or cancel). If only one side is a house fill (qty ≥ 1), B flattens that filled Yes. A leftover smaller than 1 is still a real Polymarket ticket.</p>
<p>Paul's toast — Bought Namigata, Junri, cost $0.19 @ 58%, to win $0.32 — is B's T0 Yes Namigata that only got <strong>0.32 shares</strong>. 0.32 × 58¢ ≈ 19¢. The fill price on the wire was 29¢. 58% is the live offer/mark on the popup, not the fill. Systems A, C, and D did not send this match.</p>
<p>Open-count then treated Polymarket's positions list as qty 0 because it ignored anything under 1 contract, and because flatten had cleared the “filled” flags. That dropped Namigata as a B phantom while Paul was staring at the live toast. Same family as Guajardo (activities/cumQuantity vs an empty-looking positions GET). Karim/Guidotti was kept when confirm qty was 1 and both T0 flags stayed true. Namigata's 0.32 was not.</p>
</div>

<div class="callout ok">
<h2>Verdict</h2>
<ul>
<li><strong>System:</strong> B Tennis crossover. Not A lock, not C college-football favorite, not D T0 spreads. Tape lock: tennis-b keys, strategy_b_watch row, three Poly IOC ids. Kalshi/Gemini/Novig fills on this slug: 0.</li>
<li><strong>What we bought:</strong> Yes Namigata leftover <strong>0.32 @ 29¢</strong> (Paul's toast). Plus a flattened 1-lot Yes Yoshimoto (wired BUY_SHORT Namigata @ 19¢) closed by BUY_LONG Namigata @ 56¢. Positions GET now: <strong>net 0.32 Yes Namigata</strong>, market still OPEN.</li>
<li><strong>Why 19¢:</strong> toast cost = 0.32 shares × ~58¢ mark ≈ $0.19. Not a 0.19-share ticket. Not the Yoshimoto BUY_SHORT 19¢ (that was qty 1, to-win $1). Fill was 29¢; book at T0 only had 0.32 size.</li>
<li><strong>T0 both-Yes?</strong> Sent. Yoshimoto house-filled 1. Namigata partial 0.32, not a house 1. <strong>50-cross extra?</strong> No. <strong>Leftover IOC?</strong> No — flatten of Yoshimoto filled, so leftover-watch never armed.</li>
<li><strong>Phantom-drop mistake:</strong> yes. Poly still holds 0.32. We did not sell it. We did not flatten it in this job.</li>
<li><strong>Fix:</strong> Poly qty &gt; 0 counts as open. Empty positions GET is not qty 0 when this order's cumQuantity / activities show a fill (including 0.32). Namigata restored as open B with extras/flatten armed off. Test: empty positions + activities 0.32 → still open. Live B reloaded once, PID {esc(b_pid)}.</li>
</ul>
</div>

<h2>We thought vs Poly said</h2>
<p class="note">Click column headers to sort. Match on aggressor order id. Swipe sideways to see more columns.</p>
{SWIPE_NOTE_HTML}
{compare}

<h2>Systems A / B / C / D</h2>
{SWIPE_NOTE_HTML}
{systems}

<h2>How Poly UI labels vs house Yes/No</h2>
{SWIPE_NOTE_HTML}
{ui}
<p>One Polymarket US market, slug <code>aec-utr-namjun-yosnat-2026-10-24</code>, title Junri Namigata vs. Natsuki Yoshimoto, outcome Yes = Namigata. House Yes Yoshimoto is BUY_SHORT on that same contract. Poly's activity list shows Sold Yes when we BUY_SHORT. Favorite/dog from T0 Yes asks: Yoshimoto 0.81 / Namigata 0.29 (C=1.10).</p>

<h2>Phantom drop vs Karim</h2>
<p class="note">Click column headers to sort. Swipe sideways to see more columns.</p>
{SWIPE_NOTE_HTML}
{phantom}

<h2>Mark-to-market if cheap</h2>
<p class="note">Public book still MARKET_STATE_OPEN. Best bid 20¢, best offer 56¢ (598 size) then 59¢. Wide. Cheap leftover. Unrealized depends on the mark; we did not sell.</p>
{SWIPE_NOTE_HTML}
{mtm}

<h2>Intended story</h2>
<p>T0 both-Yes: yes, B sent both. 50-cross extra dog: no. Favorite dip: no. Lock-bot Yes+No: no. Flatten: yes, of the filled Yoshimoto Yes, already on the tape at 20:05:23 ET — not this job. Restored row is <code>one_leg_miss</code> with <code>stopped</code> so B will not send another IOC or flatten. Slot counts as open B on job_status.</p>

<h2>Fix</h2>
<p><code>open_count_sync._poly_snapshot</code> no longer drops qty &lt; 1. <code>classify_match</code> treats Poly qty &gt; 0 as a real holding, and fail-soft-keeps a row when this slug's positions GET is empty/qty 0 but last_order / activities / cumQuantity show a fill (0.32 included). Flatten leftover restores to <code>one_leg_miss</code> + <code>stopped</code>, not <code>waiting_cross</code> (that would have armed a 50-cross extra on a dog already &gt; 50¢). Tests: <code>test_poly_empty_book_keeps_partial_032</code>, <code>test_poly_book_qty_032_is_open</code>, <code>test_reconcile_restores_flattened_poly_partial</code>. job_status Positions table includes Poly qty &gt; 0 so this row can tag <strong>B</strong>. One B reload. C/D/lock left alone. Did not sell.</p>

<p class="note">Sources: Polymarket US GET /v1/portfolio/activities (3 TRADE rows, aggressor ids DA4V3W5011KJ / DA4V6VTG31MQ / DA4VGMG011TB), GET /v1/portfolio/positions (n_all 1, net 0.3200 Yes Namigata, expired false), public book MARKET_STATE_OPEN bid 0.20 / offer 0.56; Kalshi fills 0; Gemini history 0 match; Novig fills 0. Local orders.jsonl, order_io.jsonl, strategy_b_watch.json. Code: open_count_sync.py, job_status_positions.py. Pulled {esc(now)}. Status Checked {esc(checked)}. Live B PID {esc(b_pid)}. File URL {esc(FILE_URL)}</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(inject_report_page_extras(page), encoding="utf-8")
    print(PAGE)


if __name__ == "__main__":
    main(*sys.argv[1:])
