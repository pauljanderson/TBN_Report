"""Why the catalog 0.98 deny was not a live send vs NET_MAX 0.984.

Research only. Does not place, cancel, flatten, or sell. Does not print secrets.
Does not start a second live_strategy_b.py. Does not change NET_MAX.
"""
from __future__ import annotations

import html as html_lib
import json
import sys
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_lock_orders  # noqa: E402
import novig_live  # noqa: E402
import opportunity_considerations  # noqa: E402
import polymarket_us_live  # noqa: E402
import report_page_extras  # noqa: E402
import venue_pace  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW  # noqa: E402

PAGE = STAMP / "lock_098_deny_rounding_20261025.html"
LOG_PATH = RAW / "considerations.json"
# Freeze the diagnosis to the 0.984 line that was live when this stamp was written.
NET_MAX = Decimal("0.984")
HIST_LINE = "0.984"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/lock_098_deny_rounding_20261025.html"
)
OPP_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/opportunities.html"
)
ASKED = opportunity_considerations.ASKED_098
PLAIN = (
    "The row Paul saw was the overnight catalog scan, not a live poller. Catalog never "
    "sends, even at 0.97. The after-fee number printed as 0.98 because the catalog still "
    "rounded that field to cents before the log wrote it. The live send check does not "
    "round: it compares the true cost to 0.984. For the latest San Francisco vs Atlanta "
    "spreads that true cost is a hair over 0.984, so a live poller would also skip as "
    "over the cap. Indianapolis Minnesota moneyline was a true 0.9800, under the cap, "
    "and was denied only because it was catalog. The opportunities after-fee column now "
    "prints at least four decimal places and stores the send-check net, not the rounded cents."
)


def esc(value) -> str:
    return html_lib.escape(str(value if value is not None else ""), quote=True)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" aria-sort="none">'
        f"{esc(label)}<span class=\"sort-ind\"></span></th>"
    )


def kalshi_fee(price: Decimal) -> Decimal:
    return live_lock_orders.kalshi_fee_amount(price)


def pair_net(cand: dict) -> Decimal | None:
    return live_lock_orders.pair_net(opportunity_considerations._FeeScan(), cand)


LOOKS = [
    {
        "at": "2026-10-25T13:44:27-04:00",
        "sport": "pro football",
        "game": "San Francisco vs Atlanta",
        "market_type": "spread",
        "side": "SF",
        "number": "10.5",
        "yes_venue": "novig",
        "no_venue": "kalshi",
        "yes_price": "0.38",
        "no_price": "0.59",
        "yes_size": "3736",
        "no_size": "5322",
        "fee_coefficient": "0.06",
        "fee_charged": "WHEN_LIVE",
        "event_status": "OPEN_INGAME",
        "stored_net": "0.98",
        "source": "catalog scan",
        "latest": True,
    },
    {
        "at": "2026-10-25T13:44:27-04:00",
        "sport": "pro football",
        "game": "San Francisco vs Atlanta",
        "market_type": "spread",
        "side": "SF",
        "number": "4.5",
        "yes_venue": "novig",
        "no_venue": "kalshi",
        "yes_price": "0.59",
        "no_price": "0.38",
        "yes_size": "3447",
        "no_size": "34",
        "fee_coefficient": "0.06",
        "fee_charged": "WHEN_LIVE",
        "event_status": "OPEN_INGAME",
        "stored_net": "0.98",
        "source": "catalog scan",
        "latest": True,
    },
    {
        "at": "2026-10-25T13:29:43-04:00",
        "sport": "pro football",
        "game": "Indianapolis vs Minnesota",
        "market_type": "moneyline",
        "side": "Minnesota wins",
        "number": "",
        "yes_venue": "kalshi",
        "no_venue": "polymarket",
        "yes_price": "0.57",
        "no_price": "0.39",
        "yes_size": "68894.67",
        "no_size": "13386.58",
        "fee_coefficient": "0.0695",
        "stored_net": "0.98",
        "source": "catalog scan",
        "latest": False,
    },
]


def enrich(look: dict) -> dict:
    yes = Decimal(look["yes_price"])
    no = Decimal(look["no_price"])
    gross = yes + no
    novig_fee = None
    poly_fee = None
    gemini_fee = Decimal("0")
    k_fee = Decimal("0")
    if look["yes_venue"] == "novig":
        novig_fee = novig_live.taker_fee(
            yes, look.get("fee_coefficient"), look.get("fee_charged"), look.get("event_status")
        )
    if look["no_venue"] == "novig":
        novig_fee = novig_live.taker_fee(
            no, look.get("fee_coefficient"), look.get("fee_charged"), look.get("event_status")
        )
    if look["yes_venue"] == "polymarket":
        poly_fee = polymarket_us_live.taker_fee(yes, look.get("fee_coefficient"))
    if look["no_venue"] == "polymarket":
        poly_fee = polymarket_us_live.taker_fee(no, look.get("fee_coefficient"))
    if look["yes_venue"] == "kalshi":
        k_fee = kalshi_fee(yes)
    if look["no_venue"] == "kalshi":
        k_fee = kalshi_fee(no)
    send = pair_net(look)
    extra = Decimal("0")
    if novig_fee is not None:
        extra += novig_fee
    if poly_fee is not None:
        extra += poly_fee
    extra += gemini_fee
    all_in = gross + extra + k_fee
    vs = None if send is None else send - NET_MAX
    if send is None:
        live = "unknown"
    elif send > NET_MAX:
        live = "live would also deny (over cap)"
    else:
        live = "live would send (catalog is the only deny)"
    look = dict(look)
    look.update(
        {
            "gross": gross,
            "novig_fee": novig_fee,
            "poly_fee": poly_fee,
            "kalshi_fee": k_fee,
            "send_net": send,
            "all_in": all_in,
            "vs_cap": vs,
            "live": live,
            "money_rounded": Decimal(str(look["stored_net"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN),
        }
    )
    return look


def money4(value) -> str:
    if value is None:
        return ""
    return opportunity_considerations._fmt(value if isinstance(value, Decimal) else Decimal(str(value)))


def backfill_log(looks: list[dict]) -> int:
    """Attach fee fields so opportunities.html can recompute unrounded net. Do not drop rows."""
    patched = 0
    try:
        with venue_pace.FileLock(opportunity_considerations.LOCK_PATH):
            rows = opportunity_considerations._load(LOG_PATH.read_text(encoding="utf-8")) if LOG_PATH.exists() else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                for look in looks:
                    if (
                        str(row.get("at") or "") == look["at"]
                        and str(row.get("game") or "") == look["game"]
                        and str(row.get("market_type") or "") == look["market_type"]
                        and str(row.get("side") or "") == look["side"]
                        and str(row.get("number") or "") == look["number"]
                        and str(row.get("yes_venue") or "") == look["yes_venue"]
                        and str(row.get("no_venue") or "") == look["no_venue"]
                    ):
                        send = look.get("send_net")
                        row["source"] = "catalog scan"
                        if not str(row.get("trigger_source") or "").strip():
                            row["trigger_source"] = "catalog scan"
                        row["fee_coefficient"] = look.get("fee_coefficient") or ""
                        if look.get("fee_charged"):
                            row["fee_charged"] = look["fee_charged"]
                            row["event_status"] = look.get("event_status") or ""
                        if send is not None:
                            row["net"] = opportunity_considerations._fmt(send)
                        patched += 1
                        break
            tmp = LOG_PATH.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"rows": rows}, ensure_ascii=False), encoding="utf-8")
            tmp.replace(LOG_PATH)
    except Exception:
        return patched
    return patched


def write_page(looks: list[dict]) -> Path:
    line = HIST_LINE
    live = live_lock_orders.send_line()
    rows_html = []
    for look in looks:
        send = look["send_net"]
        over = send is not None and send > NET_MAX
        rows_html.append(
            "<tr>"
            f"<td>{esc(look['at'])}</td>"
            f"<td>{esc(look['sport'])}</td>"
            f"<td>{esc(look['game'])}</td>"
            f"<td>{esc(look['market_type'])}</td>"
            f"<td>{esc(look['side'])}</td>"
            f"<td>{esc(look['number'])}</td>"
            f"<td>Yes {esc(look['yes_venue'])} / No {esc(look['no_venue'])}</td>"
            f"<td>{esc(look['yes_price'])}</td>"
            f"<td>{esc(look['no_price'])}</td>"
            f"<td>{esc(money4(look['gross']))}</td>"
            f"<td>{esc(money4(look['novig_fee']) if look['novig_fee'] is not None else '0.0000')}</td>"
            f"<td>{esc(money4(look['poly_fee']) if look['poly_fee'] is not None else '0.0000')}</td>"
            f"<td>{esc(money4(look['kalshi_fee']))}</td>"
            f"<td>{esc(look['stored_net'])}</td>"
            f"<td>{esc(money4(send))}</td>"
            f"<td>{esc(money4(look['all_in']))}</td>"
            f"<td>{esc(money4(look['vs_cap']))}</td>"
            f"<td>{esc('yes' if over else 'no')}</td>"
            f"<td>{esc(look['source'])}</td>"
            f"<td>{esc(look['live'])}</td>"
            "</tr>"
        )
    latest = [look for look in looks if look.get("latest")]
    lead = latest[0] if latest else looks[0]
    table = (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + th("Time", "date")
        + th("Sport", "text")
        + th("Game", "text")
        + th("Market type", "text")
        + th("Side", "text")
        + th("Number", "num")
        + th("Venues", "text")
        + th("Yes ask", "num")
        + th("No ask", "num")
        + th("Gross", "num")
        + th("Novig fee", "num")
        + th("Poly fee", "num")
        + th("Kalshi fee (not in send check)", "num")
        + th("Printed (2 dp)", "num")
        + th("Send-check net", "num")
        + th("All-in with Kalshi fee", "num")
        + th("Send net minus 0.984", "num")
        + th("Over 0.984?", "text")
        + th("Source", "text")
        + th("If this had been live", "text")
        + "</tr></thead><tbody>"
        + "".join(rows_html)
        + "</tbody></table></div>"
    )
    body = f"""
<h1>Catalog 0.98 deny vs NET_MAX 0.984</h1>
<p class="note">America/New_York. Research only. Not gold. Not DailyRun. Did not sell. Did not start a second Tennis crossover. Tables below are the 0.984 diagnosis; they are not the live send line.</p>
<div class="callout"><h2>Live send cap (after this stamp)</h2>
<p>Rounding on the after-fee display is gone. Paul then bumped the live send cap to <strong>{esc(live)}</strong> via <code>--lock-net-max</code>. See <a href="lock_net_max_099_20261025.html">lock_net_max_099_20261025.html</a>. Tampa Bay vs Carolina 0.98399 is not retro-sent.</p>
</div>
<div class="callout"><h2>What you asked</h2><p>{esc(ASKED)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{esc(PLAIN)}</p></div>
<p class="note">Scan log: <a href="opportunities.html">opportunities.html</a>. Near misses: <a href="lock_near_misses_20261025.html">lock_near_misses_20261025.html</a>. Click column headers to sort.</p>
{report_page_extras.SWIPE_NOTE_HTML}
<h2>Verdict</h2>
<ul>
<li><strong>Catalog vs live:</strong> the matching skip is catalog scan. Source field is <code>catalog scan</code>. Catalog never sends, even at 0.97. Live send is pollers only, when send-check net ≤ {esc(line)}.</li>
<li><strong>Latest look:</strong> {esc(lead['game'])} {esc(lead['market_type'])} {esc(lead['side'])} {esc(lead['number'])} at {esc(lead['at'])}. Printed after-fee <strong>0.98</strong>. Unrounded send-check net <strong>{esc(money4(lead['send_net']))}</strong> vs NET_MAX <strong>{esc(line)}</strong> ({esc('over cap' if lead['send_net'] > NET_MAX else 'at or under cap')}).</li>
<li><strong>Rounding:</strong> yes. Catalog <code>money()</code> still does <code>quantize</code> to cents then <code>:.2f</code> before the log. 0.98414 becomes 0.98. The send check uses Decimal <code>net &gt; NET_MAX</code> and does not round first. Same class of bug as hair-0984 (0.98399 shown/compared wrong), except this time rounding hid a hair <em>over</em> 0.984 on the SF spreads.</li>
<li><strong>Display:</strong> opportunities after-fee cost now prints at least four decimal places from the send-check net (pair_net), not the rounded catalog string.</li>
<li><strong>Other live gates on the SF rows:</strong> size was ≥ 1 on both legs, gross 0.97 &lt; $1. Not a hard-first miss and not a balance skip (catalog never tried to send). The live SF poller’s Novig websocket had 0 messages at the health snapshot, so even a under-cap Novig quote might not have been seen live. Unrounded net was over 0.984 anyway.</li>
</ul>
<h2>The looks</h2>
{table}
<p class="note">Send-check net is asks plus Gemini / Polymarket / Novig documented taker fees. Kalshi is $0 on that check (same as live_lock_orders.pair_net). All-in with Kalshi fee is shown separately and is not the send line. Compare is Decimal, not float.</p>
<p class="tiny">Updated {esc(opportunity_considerations._now())}. NET_MAX={esc(line)}. {esc(FILE_URL)}</p>
"""
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>Catalog 0.98 deny vs 0.984</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.05rem; margin: 1.2rem 0 0.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; }}
.note {{ color: #475569; font-size: 14px; }}
.tiny {{ color: #64748b; font-size: 12px; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
{body}
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(page, encoding="utf-8")
    tmp.replace(PAGE)
    return PAGE


def main() -> None:
    looks = [enrich(look) for look in LOOKS]
    for look in looks:
        print(
            look["game"],
            look["number"],
            "stored",
            look["stored_net"],
            "send",
            money4(look["send_net"]),
            "all_in",
            money4(look["all_in"]),
            "vs",
            money4(look["vs_cap"]),
            look["live"],
            flush=True,
        )
    n = backfill_log(looks)
    print("backfilled", n, flush=True)
    path = write_page(looks)
    print("wrote", path, flush=True)
    opp = opportunity_considerations.write_page()
    print("opportunities", opp, flush=True)


if __name__ == "__main__":
    main()
