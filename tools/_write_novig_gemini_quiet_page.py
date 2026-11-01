"""Rebuild Novig/Gemini quiet HTML from already-pulled venue + log dumps. Read-only."""
from __future__ import annotations

import html as html_lib
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW  # noqa: E402
from report_page_extras import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
    inject_report_page_extras,
)

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "novig_gemini_quiet_20261023.html"
DUMP = RAW / "_novig_gemini_quiet_20261023.json"
RECOUNT = RAW / "_novig_gemini_quiet_recount.json"

ASKED = (
    "why do we still have 0 orders on Novig? and why haven't we had any orders on Gemini in a while?"
)
PLAIN = (
    "A prediction market is a ticket that costs between 0 and $1 and pays $1 if that named result happens. "
    "Kalshi, Gemini, Polymarket US, and Novig are the four shops. The lock bot only buys both sides of the same "
    "result when the two prices plus the documented fees add up to at most 0.984 (the live send cap). "
    "It uses the cheaper legal Yes shop and the cheaper legal No shop. Strategy B never sends Novig; it only "
    "uses Kalshi, Gemini, and Polymarket on tennis Yes tickets. Immediate-or-cancel (IOC) means fill now or cancel. "
    "This page pulled Novig and Gemini history from the shops themselves and counted looks, HTTP posts, and denials "
    "from the live log. A diary row that says “sent” is not a fill unless the shop and the HTTP tape agree. "
    "This page does not place, cancel, sell, or start a second Strategy B."
)


def esc(value) -> str:
    return html_lib.escape("" if value is None else str(value), quote=True)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{esc(label)}<span class="sort-ind"></span></th>'
    )


def td(value, kind: str = "text") -> str:
    extra = ' class="num"' if kind == "num" else ""
    return f"<td{extra}>{esc('' if value is None else value)}</td>"


def table(headers: list[tuple[str, str]], rows: list[list], total: list | None = None) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        cells = "".join(td(cell, headers[i][1] if i < len(headers) else "text") for i, cell in enumerate(row))
        body.append(f"<tr>{cells}</tr>")
    if total is not None:
        cells = "".join(td(cell, headers[i][1] if i < len(headers) else "text") for i, cell in enumerate(total))
        body.append(f'<tr class="total-row">{cells}</tr>')
    if not body:
        body.append("<tr>" + "".join(td("") for _ in headers) + "</tr>")
    return (
        f"{SWIPE_NOTE_HTML}<div class=\"table-wrap\"><table class=\"sortable\">"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    dump = load(DUMP)
    rec = load(RECOUNT)
    stamp = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    acc = dump.get("novig_account") or {}
    nf = dump.get("novig_fills") or {}
    gf = dump.get("gemini_filled") or {}
    slots = dump.get("slots") or {}
    win = rec.get("consider") or {}
    since = win.get("since_2351") or {}
    all500 = win.get("all500") or {}
    io = rec.get("order_io") or {}
    by_s = since.get("by_venue") or {}
    by_a = all500.get("by_venue") or {}
    fills = list(gf.get("fills") or [])
    fills.sort(key=lambda r: r.get("ts") or "")
    last_fill = fills[-1] if fills else {}

    look_rows = []
    for venue in ("kalshi", "polymarket", "gemini", "novig"):
        v = by_s.get(venue) or {}
        look_rows.append([
            venue,
            v.get("looks"),
            v.get("sent"),
            v.get("denied"),
            v.get("under_cap"),
            ", ".join(f"{a} {b}" for a, b in (v.get("sports") or [])[:4]),
            ", ".join(f"{a} {b}" for a, b in (v.get("partners") or [])[:4]),
        ])
    look_all = []
    for venue in ("kalshi", "polymarket", "gemini", "novig"):
        v = by_a.get(venue) or {}
        look_all.append([
            venue,
            v.get("looks"),
            v.get("sent"),
            v.get("denied"),
            v.get("under_cap"),
            ", ".join(f"{a} {b}" for a, b in (v.get("sports") or [])[:4]),
        ])
    pair_rows = [[p, n] for p, n in (since.get("pairs") or [])]
    pair_all = [[p, n] for p, n in (all500.get("pairs") or [])]
    deny_rows = []
    for venue in ("kalshi", "polymarket", "gemini", "novig"):
        for reason, n in ((by_s.get(venue) or {}).get("reasons") or []):
            deny_rows.append([venue, reason, n])
    fill_rows = [[
        r.get("time_et"), r.get("ticker"), r.get("event"), r.get("outcome"),
        r.get("side"), r.get("qty"), r.get("price"), r.get("status"),
    ] for r in fills]
    last8 = [[
        r.get("timestamp"), r.get("symbol"), r.get("outcome"), r.get("price"),
        r.get("http"), r.get("status"), r.get("filled"),
    ] for r in (io.get("last_8_gemini_orders") or [])]
    novig_samples = [[
        r.get("at"), r.get("sport"), r.get("game"), r.get("yes_venue"), r.get("no_venue"),
        r.get("net"), r.get("decision"), r.get("reason"),
    ] for r in ((by_a.get("novig") or {}).get("samples") or [])]
    gemini_samples = [[
        r.get("at"), r.get("sport"), r.get("game"), r.get("yes_venue"), r.get("no_venue"),
        r.get("net"), r.get("decision"), r.get("reason"),
    ] for r in ((by_a.get("gemini") or {}).get("samples") or [])]
    b_rows = [[r.get("game"), r.get("stage"), r.get("venue"), r.get("opened_at")] for r in (slots.get("b_open") or [])]
    skip = slots.get("lock_last_skip") or {}
    http_pages = ", ".join(str(p.get("http")) for p in (nf.get("http_pages") or []) if isinstance(p, dict))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Novig zero and Gemini quiet — 23 Oct 2026</title>
<style>
body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.2rem; color: #1e293b; background: #fff; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.3rem; }}
h2 {{ font-size: 1.05rem; margin: 1.2rem 0 0.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; }}
.warn {{ background: #fff7ed; border-color: #fdba74; }}
.ok {{ background: #f0fdf4; border-color: #86efac; }}
.note {{ color: #475569; font-size: 14px; }}
ul, ol {{ margin-top: 0.3rem; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Why Novig is still 0, and why Gemini has been quiet</h1>
<p class="note">America/New_York. Written {esc(stamp)}. Research live. Not gold. Not DailyRun. Read-only: venue fill history + live deny logs + HTTP tape. This page does not place, cancel, flatten, sell, GTC, or start a second Strategy B. Click column headers to sort.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<div class="callout warn">
<h2>Novig — actual why (0 fills, still)</h2>
<p>The shop itself still has <strong>no fills</strong>. GET /v3/portfolio/fills HTTP {esc(http_pages)}: {esc(nf.get('n'))} row(s), {esc(nf.get('n_house'))} with quantity at least 1. order_io has <strong>0 Novig POSTs ever</strong> (847 book reads historically, last book GET 2026-10-21 23:28:41 ET). orders.jsonl has 0 Novig rows.</p>
<p>This is <strong>not a dead key or empty wallet</strong>. Live read this morning: NOVIG_ORDERS_ENABLED={esc(acc.get('NOVIG_ORDERS_ENABLED'))}, orders_live()={esc(acc.get('orders_live'))}, trading_key_ready={esc(acc.get('trading_key_ready'))} ({esc(acc.get('trading_key_note'))}), keys present={esc(acc.get('keys_present'))}, balance HTTP {esc(acc.get('balance_http'))} = ${esc(acc.get('balance_usd'))}. Disk last-good at 07:59 ET was also $10.00. That is enough for a $1 lock leg.</p>
<p>Strategy B never sends Novig. Only the lock bot can. The lock bot <em>does</em> build Kalshi / Gemini / Polymarket vs Novig pairs in code (<code>live_game_pollers._compared</code> → <code>novig_live.novig_candidates</code>).</p>
<p>In the kept opportunities diary (newest 500 distinct looks, {esc(all500.get('first'))} through {esc(all500.get('last'))}) Novig appeared in <strong>1 look</strong>: 2026-10-23 07:20:26 ET, college football Indiana vs Michigan, Kalshi Yes / Novig No, after-fee cost <strong>0.99</strong>, denied because that is above the 0.984 send line. It was <em>not</em> under NET_MAX. Since last night’s 23:51:39 ET restart: still that 1 look, 0 sent, 0 at or under 0.984.</p>
<p><strong>Last Novig ask in a lock look under 0.984:</strong> not in the 500-row diary. The only Novig look we can still see is 0.99, which is above the send cap. Older looks have rotated out of the 500-row file. We are not guessing an earlier one.</p>
<p>Overnight the lock flow was tennis (370 of 373 looks since 23:51). Those pairs were Kalshi/Polymarket. Novig HTTP book GETs also stopped appearing in order_io after 2026-10-21 23:28:41 ET (0 Novig HTTP since the 23:51 restart). Quotes can still arrive by websocket/cache — Indiana vs Michigan did log a Novig No price — but nothing under 0.984 was sent.</p>
</div>

<div class="callout warn">
<h2>Gemini — actual why (quiet on fills and on HTTP posts)</h2>
<p><strong>Last Gemini house fill on the venue:</strong> {esc(last_fill.get('time_et') or 'none')} {esc(last_fill.get('ticker'))} {esc(last_fill.get('event'))} {esc(last_fill.get('outcome'))} qty {esc(last_fill.get('qty'))} @ {esc(last_fill.get('price'))}, status {esc(last_fill.get('status'))}. That is Middle Tennessee vs FIU Over 48.5 Yes at 0.44, matching the three-ticket history (TB/CLE 2026-10-18 19:46:13 ET Yes 0.97; CAR/CGY 2026-10-18 21:41:57 ET Calgary Yes 0.99; MTN/FIU 2026-10-20 21:35:10 ET).</p>
<p><strong>Last Gemini HTTP POST in order_io:</strong> 2026-10-20 21:41:00 ET, GEMI-NCAAF-2610202300-MTN-FIU-T-O47 Yes 0.48, HTTP 201, venue status cancelled, filled 0. Last Gemini book GET: 2026-10-21 23:26:22 ET (NMSU/SHSU moneyline). <strong>0 Gemini HTTP rows since 23:51 ET Oct 22</strong> (no book GET, no POST). Venue cancelled-history and unfiltered history pulls this morning also returned 0 new tickets.</p>
<p>Gemini cash is not the reason. balances.json at 07:59 ET: Gemini $25.56. History API HTTP 200.</p>
<p>In the 500-row diary Gemini appeared in <strong>4 looks, all college football, all Kalshi Yes / Gemini No</strong>. Tennis (495 of 500 looks) never had Gemini as a Yes or No shop. Tennis poller rows start with an empty Gemini book list, so Gemini sports lists are not in the tennis-heavy overnight lock flow unless a college-football poller is also up.</p>
<p>The diary has two “sent” rows for New Mexico State vs Sam Houston (2026-10-22 23:49:27 ET, before the 23:51 restart, and 2026-10-23 08:21:36 ET) saying “gemini HTTP 201 fill 0 cancelled.” <strong>Those are diary-only.</strong> orders.jsonl has no <code>sent_at</code> at those timestamps. order_io has no Gemini POST then — only Kalshi book reads. Same class of false “sent” as the earlier Sam Houston 9.5 diary. The sibling deny at the same second is “This pair is not two live order venues, so it was not sent.” Truth = shops + HTTP tape: no Gemini POST after 2026-10-20 21:41 ET.</p>
<p>Since 23:51 the HTTP posts that <em>did</em> leave the box were Kalshi and Polymarket only (Li vs Tagger lock, then Strategy B tennis Yes tickets). Gemini was not on those legs.</p>
</div>

<div class="callout ok">
<h2>Broken vs never the cheapest legal leg</h2>
<p><strong>Novig is not broken as a shop connection.</strong> Flag on, trading key, $10, fills GET empty. It is unused because it is almost never in a logged pair, and the one pair we still have was 0.99 — above 0.984. Kalshi/Polymarket won 370 of 373 looks since 23:51.</p>
<p><strong>Gemini is not API-dead.</strong> History HTTP 200, cash $25.56. It is unused because (1) overnight lock flow is tennis and Gemini is not on those tennis books, (2) when it was the cheap No on college football, the last <em>real</em> POST was Oct 20 21:41 and it cancelled empty, (3) diary “sends” this morning are not on the HTTP tape.</p>
<p><strong>Lock 0/3 vs Strategy B 2/2:</strong> Lock open slots now {esc(slots.get('lock_open_n'))} / {esc(slots.get('lock_max'))} — not full, so lock 0/3 is not why Novig/Gemini had no posts. Strategy B is {esc(slots.get('b_open_n'))} / {esc(slots.get('b_max'))} (watch field currently_open={esc(slots.get('b_currently_open_field'))}): Machac vs Khachanov waiting_fav_dip (Kalshi, opened 2026-10-22 06:45), Moutet vs Paul waiting_cross (Kalshi, opened 2026-10-23 07:53, T0 filled ~08:00). B 2/2 only blocks <em>new lock-bot pairs on those same tennis matches</em>. It does not turn Novig or Gemini off as shops. Strategy B never sends Novig anyway.</p>
<p>orders_stopped.json is <strong>absent now</strong> (latch off). After Li vs Tagger, flatten missed at 00:21:53 ET; the leftover watch stopped a second later (stop_reason recorded as the old 8:00 AM ET deadline). The diary then has 161 “Orders stopped after a one-leg fill” denials on Kalshi/Polymarket tennis looks. That can pause <em>new</em> lock sends while a leftover/latch is on; it does not explain Gemini’s last real POST on Oct 20, two days earlier. Last lock skip file: {esc(skip.get('at'))} {esc(skip.get('game'))} {esc(skip.get('reason'))}.</p>
<p>Live window for the counts below: <strong>2026-10-22 23:51:39 ET</strong> supervisor start pid 31924, deadline None (Paul’s last-night restart). A later supervisor start at 2026-10-23 08:13:18 ET pid 16800 also has deadline None; we did not use that as the window because it would hide overnight tennis. Opportunities keeps 500 distinct looks; this window used {esc(since.get('n'))} of {esc(all500.get('n'))} stored rows.</p>
</div>

<h2>Looks vs sends vs denials since 23:51:39 ET Oct 22</h2>
<p class="note">A look is an opportunities row at or under 0.99 after fees. “Sent” here is the diary label — Gemini’s two diary sends are not on the HTTP tape. A venue is counted if it is the Yes shop or the No shop. Click headers to sort.</p>
{table(
    [("Venue", "text"), ("Looks", "num"), ("Diary sent", "num"), ("Denied", "num"), ("At or under 0.984", "num"), ("Sports", "text"), ("Yes/No role", "text")],
    look_rows,
    ["all looks in window", since.get("n"), "", "", "", ", ".join(f"{a} {b}" for a, b in (since.get("sports") or [])), ""],
)}

<h2>Which pair shops won (since 23:51)</h2>
{table([("Yes / No pair", "text"), ("Looks", "num")], pair_rows)}

<h2>Same counts on the full 500-row diary (from {esc(all500.get('first'))})</h2>
{table(
    [("Venue", "text"), ("Looks", "num"), ("Diary sent", "num"), ("Denied", "num"), ("At or under 0.984", "num"), ("Sports", "text")],
    look_all,
)}
{table([("Yes / No pair", "text"), ("Looks", "num")], pair_all)}

<h2>Deny reasons since 23:51 (diary text, truncated)</h2>
{table([("Venue in pair", "text"), ("Reason", "text"), ("N", "num")], deny_rows)}

<h2>Every Novig look still in the diary</h2>
{table(
    [("When", "date"), ("Sport", "text"), ("Game", "text"), ("Yes shop", "text"), ("No shop", "text"), ("Net", "num"), ("Decision", "text"), ("Reason", "text")],
    novig_samples,
)}

<h2>Every Gemini look still in the diary</h2>
<p class="note">The two “sent” rows are diary-only. HTTP tape and venue history do not have matching Gemini posts.</p>
{table(
    [("When", "date"), ("Sport", "text"), ("Game", "text"), ("Yes shop", "text"), ("No shop", "text"), ("Net", "num"), ("Decision", "text"), ("Reason", "text")],
    gemini_samples,
)}

<h2>Gemini venue fills (qty at least 1, status filled)</h2>
<p class="note">POST /v1/prediction-markets/orders/history status=filled, from 2026-10-01 through this morning. HTTP {esc(gf.get('http'))}, n={esc(gf.get('n'))}, house={esc(gf.get('n_house'))}.</p>
{table(
    [("Time ET", "date"), ("Symbol", "text"), ("Event", "text"), ("Outcome", "text"), ("Side", "text"), ("Qty", "num"), ("Price", "num"), ("Status", "text")],
    fill_rows,
)}

<h2>Last eight Gemini HTTP POSTs in order_io</h2>
<p class="note">None after 2026-10-20 21:41 ET. 932 Gemini order rows in the whole file; 0 since 23:51.</p>
{table(
    [("When", "date"), ("Symbol", "text"), ("Outcome", "text"), ("Limit", "num"), ("HTTP", "num"), ("Venue status", "text"), ("Filled qty", "num")],
    last8,
)}

<h2>Lock vs Strategy B slots right now</h2>
{table(
    [("Strategy B open game", "text"), ("Stage", "text"), ("Venue", "text"), ("Opened", "date")],
    b_rows,
)}
<p class="note">Lock open bet_keys: {esc(', '.join(slots.get('lock_open') or []) or '(none)')}. NET_MAX={esc(slots.get('net_max'))}. Strategy B novig_orders field: {esc(slots.get('b_novig_orders'))}.</p>

<h2>Supervisor starts (from live_supervisor.log)</h2>
{table(
    [("Time ET", "date"), ("Line", "text")],
    [[h.get("time_et"), h.get("line")] for h in ((dump.get("restart") or {}).get("recent") or [])],
)}

<p class="note">Sources: Novig GET /v3/portfolio/fills and balance; Gemini POST /v1/prediction-markets/orders/history; local considerations.json (500-row cap), order_io.jsonl, orders.jsonl, strategy_b_watch.json, lock_last_skip.json, balances.json, live_supervisor.log. Code: live_lock_orders.py, live_strategy_b.py, novig_live.py, live_game_pollers._compared. Sibling owns orders_performance.html. No secrets. No tickets sold. No second Strategy B.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(inject_report_page_extras(html), encoding="utf-8")
    tmp.replace(PAGE)
    print("wrote", PAGE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
