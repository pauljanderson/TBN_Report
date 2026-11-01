"""Lock sequential hard-first report. Does not send. Does not print secrets."""
from __future__ import annotations

import html
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import report_page_extras  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW  # noqa: E402

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "lock_hard_leg_first_20261024.html"
ASKED = (
    "When the lock bot sends a dual order (Yes one venue + No the other, same settlement), "
    "do we know which side is least likely to fill at the price we just saw? Can we? "
    "He proposes: try to fill that harder side first; if we can't, give up if the gap has closed. "
    "Goal: avoid one leg open. Are we looking at all sports and spreads, moneyline, etc. for lock bot bets?"
)


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def parse_at(raw) -> datetime | None:
    if not raw:
        return None
    try:
        stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=ET)
    return stamp.astimezone(ET)


def dec(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace("$", "").replace(",", "").strip())
    except Exception:
        return None


def norm_mkt(raw) -> str:
    text = str(raw or "").lower().strip()
    if text in {"ml", "winner", "match", "game", "moneyline", ""}:
        return "moneyline"
    if text in {"spread", "spreads", "handicap"}:
        return "spread"
    if text in {"total", "totals", "over", "under"}:
        return "total"
    return text or "moneyline"


def is_lock_key(key, row=None) -> bool:
    if row and row.get("system") in {"spread_t0", "cfb_favorite", "tennis_crossover", "strategy_b"}:
        return False
    text = str(key or "")
    if text.startswith(("spread-t0", "cfb_favorite", "tennis-b", "strategy")):
        return False
    return True


def bits(key, row=None) -> tuple[str, str] | None:
    sport = str((row or {}).get("sport") or "")
    market = str((row or {}).get("market_type") or "")
    parts = str(key or "").split("\t")
    if not sport and parts:
        sport = parts[0]
    if not market and len(parts) >= 4:
        market = parts[3]
    sport = sport.lower()
    if sport.startswith("spread-t0") or sport.startswith("cfb_favorite"):
        return None
    return sport or "unknown", norm_mkt(market)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def table(headers: list[tuple[str, str]], rows: list[list[str]], total: list[str] | None = None) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        tds = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{tds}</tr>")
    if total:
        tds = "".join(f"<td>{cell}</td>" for cell in total)
        body.append(f'<tr class="total-row">{tds}</tr>')
    if not body:
        body.append("<tr>" + "".join("<td></td>" for _ in headers) + "</tr>")
    return (
        f"{report_page_extras.SWIPE_NOTE_HTML}"
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


def load_orders() -> list[dict]:
    path = RAW / "orders.jsonl"
    rows = []
    if not path.exists():
        return rows
    for line in path.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def load_considerations() -> list[dict]:
    path = RAW / "considerations.json"
    if not path.exists():
        return []
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = blob.get("rows") if isinstance(blob, dict) else blob
    return [row for row in (rows or []) if isinstance(row, dict)]


def coverage(orders: list[dict], now: datetime) -> dict:
    cut = now - timedelta(hours=48)
    claim = Counter()
    sent = Counter()
    one = Counter()
    both = Counter()
    claim48 = Counter()
    sent48 = Counter()
    one48 = Counter()
    both48 = Counter()
    claim_ats = []
    sents_by: dict[str, list[dict]] = defaultdict(list)
    for row in orders:
        key = row.get("bet_key")
        if not is_lock_key(key, row):
            continue
        pair = bits(key, row)
        if pair is None:
            continue
        event = row.get("event")
        stamp = parse_at(
            row.get("compared_at") or row.get("at") or row.get("sent_at") or row.get("quote_seen_at")
        )
        if event == "claim":
            claim[pair] += 1
            if stamp:
                claim_ats.append(stamp)
                if stamp >= cut:
                    claim48[pair] += 1
        elif event == "sent" and not row.get("system"):
            sent[pair] += 1
            sents_by[str(key)].append(row)
            if stamp and stamp >= cut:
                sent48[pair] += 1
        elif event == "one_leg":
            one[pair] += 1
            if stamp and stamp >= cut:
                one48[pair] += 1
        elif event == "both_unfilled":
            both[pair] += 1
            if stamp and stamp >= cut:
                both48[pair] += 1
    return {
        "claim": claim,
        "sent": sent,
        "one": one,
        "both": both,
        "claim48": claim48,
        "sent48": sent48,
        "one48": one48,
        "both48": both48,
        "first_claim": min(claim_ats) if claim_ats else None,
        "last_claim": max(claim_ats) if claim_ats else None,
        "sents_by": sents_by,
    }


def coverage_rows(counts: dict, claim_key: str, sent_key: str, one_key: str, both_key: str) -> tuple[list[list[str]], list[str]]:
    claim = counts[claim_key]
    sent = counts[sent_key]
    one = counts[one_key]
    both = counts[both_key]
    keys = sorted(set(claim) | set(sent) | set(one) | set(both))
    rows = []
    tot = [0, 0, 0, 0]
    for sport, market in keys:
        vals = [claim[(sport, market)], sent[(sport, market)], one[(sport, market)], both[(sport, market)]]
        for i, n in enumerate(vals):
            tot[i] += n
        rows.append([esc(sport), esc(market), str(vals[0]), str(vals[1]), str(vals[2]), str(vals[3])])
    total = ["Total", "", str(tot[0]), str(tot[1]), str(tot[2]), str(tot[3])]
    return rows, total


def one_leg_size_study(orders: list[dict], sents_by: dict[str, list[dict]]) -> dict:
    one_legs = [
        row for row in orders
        if row.get("event") == "one_leg" and is_lock_key(row.get("bet_key"), row)
    ]
    fill_venue = Counter()
    miss_venue = Counter()
    small_miss = 0
    large_miss = 0
    tie = 0
    unknown = 0
    details = []
    for row in one_legs:
        key = str(row.get("bet_key") or "")
        filled = str(row.get("venue") or "").lower()
        missed = str(row.get("second_venue") or "").lower()
        fill_venue[filled] += 1
        miss_venue[missed] += 1
        sizes = {}
        for sent in sents_by.get(key) or []:
            if sent.get("system"):
                continue
            venue = str(sent.get("venue") or "").lower()
            size = dec(sent.get("quote_size"))
            if size is not None:
                sizes[venue] = size
        filled_sz = sizes.get(filled)
        missed_sz = sizes.get(missed)
        pair = bits(key, row) or ("", "")
        tag = "unknown"
        if filled_sz is None or missed_sz is None:
            unknown += 1
        elif filled_sz == missed_sz:
            tie += 1
            tag = "tie"
        elif missed_sz < filled_sz:
            small_miss += 1
            tag = "small_miss"
        else:
            large_miss += 1
            tag = "large_miss"
        if tag != "unknown":
            details.append([
                esc(pair[0]),
                esc(pair[1]),
                esc(filled),
                esc(missed),
                esc(filled_sz),
                esc(missed_sz),
                esc(tag),
            ])
    known = small_miss + large_miss + tie
    return {
        "n": len(one_legs),
        "fill_venue": fill_venue,
        "miss_venue": miss_venue,
        "small_miss": small_miss,
        "large_miss": large_miss,
        "tie": tie,
        "unknown": unknown,
        "known": known,
        "details": details,
    }


def consider_window(rows: list[dict]) -> dict:
    by = Counter()
    sent = Counter()
    first = last = None
    for row in rows:
        sport = str(row.get("sport") or "unknown").lower()
        market = norm_mkt(row.get("market_type"))
        by[(sport, market)] += 1
        if str(row.get("decision") or "") == "sent":
            sent[(sport, market)] += 1
        stamp = parse_at(row.get("at"))
        if stamp is None:
            continue
        if first is None or stamp < first:
            first = stamp
        if last is None or stamp > last:
            last = stamp
    return {"n": len(rows), "by": by, "sent": sent, "first": first, "last": last}


def fmt_ts(stamp: datetime | None) -> str:
    if stamp is None:
        return "—"
    return stamp.strftime("%Y-%m-%d %H:%M ET")


def write_page() -> Path:
    import live_lock_orders
    import novig_live

    now = datetime.now(ET)
    orders = load_orders()
    cov = coverage(orders, now)
    study = one_leg_size_study(orders, cov["sents_by"])
    consider = consider_window(load_considerations())
    inc_rows, inc_tot = coverage_rows(cov, "claim", "sent", "one", "both")
    h48_rows, h48_tot = coverage_rows(cov, "claim48", "sent48", "one48", "both48")
    consider_rows = []
    for sport, market in sorted(consider["by"]):
        consider_rows.append([
            esc(sport),
            esc(market),
            str(consider["by"][(sport, market)]),
            str(consider["sent"][(sport, market)]),
        ])
    miss_rows = [
        [esc(venue or "blank"), str(study["miss_venue"][venue]), str(study["fill_venue"][venue])]
        for venue in sorted(set(study["miss_venue"]) | set(study["fill_venue"]))
    ]
    known = study["known"]
    small_pct = f"{(100 * study['small_miss'] / known):.0f}%" if known else "—"
    novig_orders = "on" if novig_live.orders_live() else "off (quotes still collected)"
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>Lock hard-leg first — 24 Oct 2026</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.banner {{ background: #fef3c7; border: 1px solid #d97706; padding: 10px 12px; margin: 0 0 14px; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
code {{ font-size: 0.92em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
{report_page_extras.FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Lock hard-leg first</h1>
<p class="banner"><strong>Research-candidate live. Not gold. Not DailyRun.</strong>
Written {esc(now.strftime("%Y-%m-%d %H:%M ET"))}. Sequential hard-first is wired in
<code>tools/live_lock_orders.py</code>. Simultaneous both-at-once is not the default dual send.
Did not sell tickets. Did not wire GTC. Did not start a second Strategy B.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>A lock is buying Yes in one shop and No in the other for the same result, so one side pays $1
and we keep the gap after fees. Until now both buys left at the same instant. Sometimes the easy
shop filled and the thin shop missed, leaving a naked bet. Paul asked to send the harder shop first.
If that one does not fill, we walk away. If it fills but the cheap gap is gone, we unwind that fill
on the same shop instead of sending the second buy. One leftover is still possible if the hard shop
fills and then the easy shop misses.</p>
</div>

<h2>Direct answers</h2>
<ol>
<li><strong>Do we know the least-likely fill?</strong> Yes, at send time, from the REST book we already
recheck: displayed ask size (and empty book / size under 1, which already blocks the pair).
We do not invent another API. Venue miss counts from the one-leg tape are a tie-break only.</li>
<li><strong>Hard first, then give up if the gap closed:</strong> Wired. Hard = smaller REST ask size.
Size tie uses frozen miss-venue rank (Gemini missed most often on historical one-legs), then the
pricier cash leg. Hard miss → no easy send, log <code>hard_miss_abort</code>, no leftover, no flatten,
no orders-stopped latch. Hard fill then gap illegal → flatten the hard fill, do not send easy.
Hard fill then gap still legal → send easy. Easy miss → flatten-first then leftover watch + latch as today.</li>
<li><strong>All sports / spreads / moneyline?</strong> The lock bot sends on every live catalog sport
the pollers quote, for moneyline, spread, and total, as long as it is the same settlement Yes+No.
It does not skip spreads or totals. Tennis is moneyline-only because MATCH books have no spread sibling.
NBA / pro basketball is not in the overnight catalog sport list, so it is not polled unless it appears
in <code>sports_queue.json</code>. Indiana/Michigan-style is same-contract Yes+No only (not favorite-cover
Yes vs the other team’s cover Yes). Novig is quoted; Novig orders are {esc(novig_orders)}.</li>
</ol>

<h2>Send path before this change</h2>
<p class="note">Click column headers to sort.</p>
{table(
    [("Step", "text"), ("What happened", "text")],
    [
        ["Qualify", "Same settlement Yes+No. Both displayed sizes ≥ 1. After-fee net ≤ 0.984. Both prices under $1. Not the closed Tennessee vs Indianapolis 13.5."],
        ["Order of legs", "Log order was alphabetical venue. Simultaneous HTTP ignored that order. Missing websocket moves used to list Kalshi first; that was listing only."],
        ["REST recheck", "Both books immediately before either HTTP. Ask price, ask size, fee, NET_MAX 0.984, both prices &lt; $1. Empty book or size &lt; 1 → send neither."],
        ["Dual send", "Thread pool: both IOC at once, 1 contract."],
        ["One fill", "Flatten filled contract on the same shop (not a 0.984 lock). Flatten miss → leftover watch + orders_stopped latch."],
        ["Phone", "Each order HTTP that actually left, and one-leg hold. Unchanged."],
    ],
)}

<h2>Coverage (lock claims vs HTTP vs leftovers)</h2>
<p class="note">A <strong>claim</strong> is a pair that passed qualify and was about to send (the lock bot’s “considered”).
<strong>Sent HTTP</strong> is a posted IOC on that sport × market (two rows per dual attempt when both left).
<strong>One-leg</strong> is a leftover after flatten also missed. Opportunities.html is a rolling 500-look diary
(after-fee ≤ 0.99); it is not the full inception book. Ledger/orders.jsonl is. First lock claim
{esc(fmt_ts(cov["first_claim"]))} through {esc(fmt_ts(cov["last_claim"]))}.</p>
<h3>Inception</h3>
{table(
    [("Sport", "text"), ("Market", "text"), ("Claims", "num"), ("Sent HTTP", "num"), ("One-leg", "num"), ("Both unfilled", "num")],
    inc_rows,
    inc_tot,
)}
<h3>Last 48 hours</h3>
{table(
    [("Sport", "text"), ("Market", "text"), ("Claims", "num"), ("Sent HTTP", "num"), ("One-leg", "num"), ("Both unfilled", "num")],
    h48_rows,
    h48_tot,
)}
<h3>opportunities.html window (newest 500 looks)</h3>
<p class="note">This window is currently {esc(consider["n"])} rows from {esc(fmt_ts(consider["first"]))} to
{esc(fmt_ts(consider["last"]))} (catalog denied CFB looks can crowd out older tennis sends). Spreads and totals
are on this page — lock does not skip them. That is a freeze of same-settlement Yes+No, not a bug.</p>
{table(
    [("Sport", "text"), ("Market", "text"), ("Looks", "num"), ("Sent in window", "num")],
    consider_rows,
    ["Total", "", str(consider["n"]), str(sum(consider["sent"].values()))],
)}

<h2>Universe freeze</h2>
{table(
    [("Knob", "text"), ("Rule", "text")],
    [
        ["Sports polled", "College football, NFL (pro football), MLB (pro baseball), soccer, NHL (pro hockey), tennis, plus catalog extras (golf, MMA, motorsports, chess) when matched. NBA / pro basketball is not in overnight_scan SPORT_ORDER."],
        ["Market types", "Moneyline, spread, and total. Tennis MATCH stays moneyline-only. Pollers synthesize spread/total sibling tickers when the catalog listed only one kind."],
        ["Same settlement", "Pair key is (kind, side, number): Yes on one venue + No on the other. Not Indiana −4.5 Yes vs Michigan −4.5 Yes. Opponent Yes is leftover-hedge only on 2-player moneyline."],
        ["Historical skip", "Closed Tennessee vs Indianapolis 13.5 never sent. Gemini flipped-No is not a buyable offer."],
        ["Novig", f"Always quoted. Orders {novig_orders}."],
        ["NET_MAX / size", "0.984 after documented fees. 1 contract. Kalshi fee $0 in the quote; Gemini/Polymarket/Novig use documented taker fees."],
        ["Fill truth", "Venue confirm qty ≥ 1. Kalshi HTTP 201 with fill_count 0 is a miss. Polymarket HTTP 200 is not a fill by itself."],
    ],
)}

<h2>Could we know the thin side?</h2>
<p><strong>Yes.</strong> REST recheck already stores displayed ask size on each leg (<code>quote_size</code>).
Empty book or size &lt; 1 already aborts the pair. That is the primary “least likely to fill” signal.
We did not add a new venue API. Optional tie-break: which venue was the miss more often on the flatten /
one-leg tape.</p>
{table(
    [("Venue", "text"), ("Was the miss", "num"), ("Was the fill", "num")],
    miss_rows,
    ["Total one-legs", str(study["n"]), ""],
)}
<p class="note">Inception lock one-legs: {esc(study["n"])}. Gemini was the miss most often ({esc(study["miss_venue"].get("gemini", 0))}),
then Kalshi ({esc(study["miss_venue"].get("kalshi", 0))}), then Polymarket ({esc(study["miss_venue"].get("polymarket", 0))}).
Frozen <code>VENUE_MISS_RANK</code> uses that order only when sizes tie.</p>

<h2>Historical: one-legs where the smaller size was the miss</h2>
<p class="note">Lock <code>sent</code> rows often omit <code>quote_size</code> (only later duals stored it).
Where both legs have a stored size: {esc(known)} of {esc(study["n"])} one-legs.
Smaller-size leg was the miss in <strong>{esc(study["small_miss"])} / {esc(known)}</strong> ({esc(small_pct)}).
Larger-size miss {esc(study["large_miss"])}. Ties {esc(study["tie"])}. Unknown size {esc(study["unknown"])}.
That is the number Paul asked for: sending the small size first would have matched the easy-fill / hard-miss
pattern on most sized leftovers. Sizes here can include later REST reprints on the same bet key, not only the
original dual print — treat as directional, not gold.</p>
{table(
    [("Sport", "text"), ("Market", "text"), ("Filled venue", "text"), ("Missed venue", "text"), ("Filled size", "num"), ("Missed size", "num"), ("Tag", "text")],
    study["details"],
)}

<h2>What you wired</h2>
<ol>
<li>REST recheck both books (ask, size, fee, NET_MAX 0.984, both &lt; $1).</li>
<li>Hard = smaller displayed ask size. Tie: historically worse fill venue, else pricier cash.</li>
<li>IOC hard only, 1 contract. Venue-confirm qty ≥ 1. Kalshi 201 fill_count 0 = miss. Poly 200 ≠ fill.</li>
<li>Hard miss → do not send easy. Recheck gap for the log. Give up. <code>hard_miss_abort</code>. No leftover, no flatten, no latch from a no-fill.</li>
<li>Hard fill → REST recheck easy + recompute all-in net. If net &gt; NET_MAX or easy size &lt; 1 or gap closed: flatten the hard fill (same-shop opposite, existing flatten, not 0.984). Do not send easy.</li>
<li>If still legal: IOC easy. Both fill → lock. Easy miss → flatten-first, then leftover watch + latch as today.</li>
</ol>
<p>Phone ntfy still fires on each order HTTP that actually left, and on one-leg hold. Tests: hard miss → no second send;
hard fill + gap closed → flatten not second send; hard fill + gap open → second send. Simultaneous dual IOC is removed
as the default. One-leg leftover is still possible if hard fills then easy misses and flatten also misses.</p>

<p class="tiny">Sources: <code>tools/live_lock_orders.py</code>, <code>tools/live_game_pollers.py</code>,
<code>overnight_scan.py</code> pair_contracts/directions, <code>opportunity_considerations.py</code>,
local <code>orders.jsonl</code> / <code>considerations.json</code>. NET_MAX={esc(live_lock_orders.send_line())}.
Reload: <code>python tools/prediction_job_control.py restart-lock</code> (leaves B/C/D). Research-candidate live.
Not gold. Not DailyRun. No secrets. No GTC. No second Strategy B.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(report_page_extras.inject_report_page_extras(page), encoding="utf-8")
    return PAGE


if __name__ == "__main__":
    path = write_page()
    print(path)
