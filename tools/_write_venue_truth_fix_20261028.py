"""Venue-fill + venue-settle source of truth report. No live orders. No commit."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from report_page_extras import FORCE_RELOAD_SCRIPT, SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS
from write_orders_performance import table

STAMP = Path("drive/paul_experiments/prediction_market_arb_exhaustive_20261017")
OUT = STAMP / "venue_truth_fix_20261028.html"
SLUG = "aec-atp-yutshi-yuhhsu-2026-10-27"


def d4(x) -> str:
    return f"{Decimal(str(x)):.4f}"


def money(x) -> str:
    v = Decimal(str(x))
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.4f}"


def main() -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    platforms = table(
        [
            ("Platform", "text"),
            ("Fill stored vs charged", "text"),
            ("Winner / redeem source", "text"),
            ("Fill-cash bug", "text"),
            ("Settle-from-name bug", "text"),
            ("Example order id", "text"),
        ],
        [
            [
                "Kalshi",
                "Confirm fills GET uses no_price_dollars / confirm avg_price as house cash. POST average_fill_price on a No is Yes-wire (Osborne 0.11 vs 0.89). Invert only that Yes-wire.",
                "Public market.result on that ticker. Each player is a separate contract, so result=yes means that named ticker paid $1.",
                "Was Y (No). Fixed 26 Oct (Osborne). Still N after that lock.",
                "N",
                "01a179a7-e628-7aef-9600-afe97ae29d38 (Osborne No 0.89)",
            ],
            [
                "Gemini",
                "Buy at outcome yes/no. avgExecutionPrice is the debit. Tape: three filled buys @ 0.97 / 0.99 / 0.44.",
                "resolutionSide on that symbol. Each outcome is its own contract.",
                "N",
                "N",
                "145828837349608483 (MTN-FIU Over 48.5 Yes 0.44)",
            ],
            [
                "Novig",
                "Fills GET cost × 100 / native qty is house cash. Fee from fill.fee (0 = uncharged). No invented $0.",
                "No market-result helper. We do not invent ticker-yes. Missing fee stays open, not a fake settle.",
                "N",
                "N (cannot invent)",
                "novig fills GET orderId (cost field)",
            ],
            [
                "Polymarket",
                "BUY_SHORT posts avgPx (often Yes-wire) and commissionSpreadPx (often the debit). Hsu DC618E1G11N2: charged 0.55+0.01, we stored 0.45+0.01. Per-order: copy the field that matches the house quote, else the complementary spread. Do not swap every SHORT onto spread.",
                "marketData.stats.settlementPx (dict {value, currency}) / POSITION_RESOLUTION. One slug, Yes = one named player. ticker result=yes is not $1 for every Yes {player}.",
                "Y — this job",
                "Y — this job (Shimizu close_hook result=yes vs settlementPx 0)",
                "DC618E1G11N2 (Hsu BUY_SHORT)",
            ],
        ],
    )
    before_after = table(
        [
            ("Leg", "text"),
            ("Order id", "text"),
            ("Label", "text"),
            ("Before cash", "num"),
            ("Venue cash", "num"),
            ("Fee", "num"),
            ("Before P&L (ticker=yes)", "num"),
            ("After P&L (settlementPx=0)", "num"),
        ],
        [
            ["T0 Shimizu", "DC618AJG51MQ", "Yes Yuta Shimizu", d4("0.4600"), d4("0.4600"), d4("0.0200"), money("0.52"), money("-0.48")],
            ["T0 Hsu", "DC618E1G11N2", "Yes Yu-Hsiou Hsu", d4("0.4500"), d4("0.5500"), d4("0.0100"), money("-0.46"), money("0.44")],
            ["Crossover Shimizu", "DC6CX7F011KJ", "Yes Yuta Shimizu", d4("0.6000"), d4("0.6000"), d4("0.0200"), money("0.38"), money("-0.62")],
        ],
        total=["Game", "", "", "", "", "", money("0.44"), money("-0.66")],
    )
    code = table(
        [
            ("File", "text"),
            ("What changed", "text"),
        ],
        [
            ["tools/venue_fill_confirm.py", "poly_house_cash per-order debit; money_px unwrap; confirm stamps house_cash so BUY_SHORT confirm cannot keep Yes-wire"],
            ["tools/order_ledger.py", "polymarket_fill cash is venue debit (Hsu 0.5500), not avgPx 0.4500"],
            ["tools/live_lock_orders.py", "_actual_fill_cash / _execution_price / _sent_row persist house_cash + fee + qty + venue order id"],
            ["tools/write_orders_performance.py", "fill_cash_fee uses quote + venue payload; ticker_result prefers settlementPx; backfill Poly when close_hook has no px; ticket P&L from venue result first"],
            ["tools/settled_pnl_store.py", "result_from_market unwraps settlementPx dict; stores settlementPx + house_cash; close_hook copies px"],
            ["tools/open_count_sync.py", "_poly_payload_fields reads marketData.stats.settlementPx dict; 0.0000 → result=no"],
            ["tools/test_shimizu_hsu_poly_autopsy.py", "Existing locks now PASS"],
            ["tools/test_venue_truth_platforms.py", "Kalshi / Gemini / Novig already-correct + Poly px-beats-ticker-yes"],
            ["tools/test_write_orders_performance.py", "BUY_SHORT without quote uses complementary spread; quote matching avg stays per-order"],
        ],
    )
    rescored = table(
        [
            ("Scan", "text"),
            ("Count", "num"),
            ("Note", "text"),
        ],
        [
            ["Filled Poly BUY_SHORT in order_io", "127", "ORDER_STATE_FILLED"],
            ["Old cash (avgPx) ≠ venue debit after per-order rule", "116", "Most SHORT avgPx was Yes-wire. Hsu is one of these (0.45 → 0.55)"],
            ["Already matched (avg was house, or equal)", "11", "Quote matched avg, or avg=spread"],
            ["Helper vs polymarket_fill mismatch after fix", "0", "Scan’s one Petrov row was spread 0.0000 on a nested node; real spread 0.5700"],
            ["Still disagree with venue debit", "0", "Petrov D8D022F010JF quote 0.65 was 8¢ off venue spread 0.57; we copied 0.57, not the quote"],
        ],
    )
    tests = table(
        [
            ("Test", "text"),
            ("Status", "text"),
            ("What it locks", "text"),
        ],
        [
            ["test_poly_book_settlement_px_zero_is_no", "PASS", "Book settlementPx {value: 0.0000} parses as result=no"],
            ["test_hsu_buy_short_cash_is_spread_0_55_not_avgpX_0_45", "PASS", "Hsu cash 0.5500, fee 0.0100"],
            ["test_hsu_won_shimizu_yes_tickets_lose", "PASS", "T0 −0.48 / +0.44 / cross −0.62 = game −0.66"],
            ["test_wrong_ticker_yes_would_invert_winner", "PASS", "Documents ticker=yes invert; book px is still no"],
            ["test_type_column_uses_quote_not_short_wire", "PASS", "Type column; dashboard has no What you asked"],
            ["test_kalshi_no_fill_is_confirm_house_not_yes_wire", "PASS", "Kalshi No 0.89 stays 0.89"],
            ["test_gemini_buy_avg_is_house_resolution_side_is_settle", "PASS", "Gemini avgExecutionPrice + resolutionSide"],
            ["test_novig_cost_is_house_no_invented_ticker_yes", "PASS", "Novig cost is cash; missing fee stays open"],
            ["test_poly_settlement_px_dict_beats_ticker_yes", "PASS", "settlementPx 0 beats stored result=yes"],
            ["test_ticker_result_scans_all_rows_for_settlement_px", "PASS", "close_hook yes without px cannot beat a later settlementPx 0"],
        ],
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Venue-fill + venue-settle source of truth 2026-10-28</title>
<style>
body {{ font-family: Georgia, serif; max-width: 1100px; margin: 24px auto; padding: 0 16px 64px; line-height: 1.45; color: #1a1a1a; }}
h1, h2, h3 {{ font-family: system-ui, sans-serif; }}
.callout {{ background: #f4f7fb; border: 1px solid #d8dee9; padding: 12px 16px; margin: 16px 0; }}
.warn {{ background: #fff6e8; border: 1px solid #e6c98a; padding: 12px 16px; margin: 16px 0; }}
code {{ font-size: 0.92em; }}
{SORTABLE_TH_CSS}
</style>
{FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Venue-fill + venue-settle as source of truth</h1>
<p>Stamp <code>prediction_market_arb_exhaustive_20261017</code>. Written {now}. Research only. Not gold. Not DailyRun. 1 contract still. NET_MAX 0.99 lock / C 1.05 tennis HOLD still. No commit.</p>

<div class="callout">
<h2>What you asked</h2>
<p>GO on the Shimizu/Hsu recommendation: venue-fill + venue-settle as source of truth. Copy what the platform charged on that order and what it paid at redeem. Never estimate. Also: is this just a Polymarket problem, or universal?</p>
<h2>In plain English</h2>
<p>We used to guess the cost of a bet from a price field that is not always the money that left the account, and we used to mark the winner from a ticker name instead of the platform’s redeem price. That inverted the Shimizu/Hsu tennis game and understated Hsu’s cost by 10 cents. This job copies the venue receipt on every fill and the venue redeem on every settle. Kalshi, Gemini, and Novig were already doing that (Kalshi No was fixed on 26 Oct). Polymarket was not. Kitchen P&amp;L now follows those stored venue fields.</p>
</div>

<h2>Universal vs Polymarket-only</h2>
<p><strong>Polymarket-only for these two money bugs today</strong>, with one Kalshi No precedent that is already locked. Gemini and Novig store the debit they charged and settle on that contract’s own result. Kalshi No used to store Yes-wire; Osborne’s confirm path already copies no_price. Polymarket is the platform with one slug for two named players plus a BUY_SHORT Yes-wire, so both bugs showed up on Shimizu/Hsu.</p>
{platforms}

<h2>Shimizu / Hsu before vs after</h2>
<p>Winner: Yu-Hsiou Hsu. ATP 7–5 3–6 6–4. Venue <code>settlementPx 0.0000</code> on Yes=Shimizu slug <code>{SLUG}</code>. Labels stay Yes {{player}} — that side pays when they win — but P&amp;L follows redeem. Hsu T0 is +0.44 on 0.56 cost (0.55+0.01). Game <strong>−0.66</strong> venue-true. Kitchen before was +0.44 with the inverted $1.</p>
{before_after}

<h2>What changed in code</h2>
{code}

<h2>Other Poly BUY_SHORT games rescored</h2>
<p>Per-order debit, not a global invert. Live tape: when a house quote is present it matches spread (or 1−avgPx) on almost every SHORT. Hsu-shaped (spread&gt;avg) and Varaksina-shaped (avg&gt;spread) both use the field that is the debit on that order. Blind spread rewrite was the wrong tool; copying the venue field was enough.</p>
{rescored}

<h2>Tests</h2>
{tests}

<p>No second B. No C=1.05 retune. No D NFL. No leftover GTC. No stake bump. No DailyRun wire.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    STAMP.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
