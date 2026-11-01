"""Strategy B T0 under-$1 floor/stack note. Research page. Does not place orders."""
from __future__ import annotations

import html
import json
import re
import sys
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import live_lock_orders  # noqa: E402
import live_strategy_b  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW  # noqa: E402
from report_page_extras import (  # noqa: E402
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "strategy_b_t0_under_one_20261024.html"
DENSE = STAMP / "dense_inplay_yes_dip_20261021.html"
WATCH = RAW / "strategy_b_watch.json"
POLY_THETA = Decimal("0.0695")

ASKED = (
    "Paul on Strategy B T0 band [0.95, 1.20] from moutet_paul_t0_20261023.html: "
    "Why a lower end? Anything 0.99 or lower is an automatic win (two Yeses pay $1). "
    "He assumes it has never happened. If both Yes add up to less than $1 minus vig, "
    "buy again until we can't."
)

PLAIN = (
    "A Yes ticket pays $1 if that named tennis player wins. At the start (T0) Strategy B "
    "buys Yes on both players. Only one can win, so those two tickets always pay $1. "
    "If they cost 99 cents or less after the house cut (vig / fees), that first pair is "
    "already a locked win — we should want more of it, not skip it. The old 95-cent floor "
    "was a research freeze copied into live, not a lock rule. It skipped the cheapest "
    "(best) T0s: a 90-cent book would not send. The $1.20 ceiling is the vig/loss cap "
    "(Moutet 1.01 asks / about 1.035 all-in still sent). Live now: send if Yes-ask C is "
    "at most $1.20, no floor. After both legs confirm at least 1 contract, if all-in with "
    "fees is still under $1, buy another 1-contract T0 pair on the same match until the "
    "book has no size, cash is too low, a recheck is no longer under $1, or 10 pairs. "
    "Match-slot cap is matches, not contracts. D=0.25 is unchanged."
)


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


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
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{cells}</tr>")
    if total:
        cells = "".join(f"<td>{cell}</td>" for cell in total)
        body.append(f'<tr class="total-row">{cells}</tr>')
    return (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def _dec(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value.normalize(), "f")


def counts(values: list[Decimal | None]) -> dict:
    nums = [v for v in values if v is not None]
    return {
        "n": len(nums),
        "lt_100": sum(1 for v in nums if v < Decimal("1")),
        "lt_099": sum(1 for v in nums if v < Decimal("0.99")),
        "lt_095": sum(1 for v in nums if v < Decimal("0.95")),
        "eq_100": sum(1 for v in nums if v == Decimal("1")),
        "min": min(nums) if nums else None,
        "max": max(nums) if nums else None,
        "median": (sorted(nums)[len(nums) // 2] if nums else None),
    }


def buckets(values: list[Decimal | None]) -> list[tuple[str, int]]:
    nums = [v for v in values if v is not None]
    labels = [
        ("C < 0.95", lambda v: v < Decimal("0.95")),
        ("0.95 ≤ C < 0.99", lambda v: Decimal("0.95") <= v < Decimal("0.99")),
        ("0.99 ≤ C < 1.00", lambda v: Decimal("0.99") <= v < Decimal("1")),
        ("C = 1.00", lambda v: v == Decimal("1")),
        ("1.00 < C ≤ 1.01", lambda v: Decimal("1") < v <= Decimal("1.01")),
        ("1.01 < C ≤ 1.05", lambda v: Decimal("1.01") < v <= Decimal("1.05")),
        ("1.05 < C ≤ 1.20", lambda v: Decimal("1.05") < v <= Decimal("1.20")),
        ("C > 1.20", lambda v: v > Decimal("1.20")),
    ]
    return [(label, sum(1 for v in nums if pred(v))) for label, pred in labels]


def estimate_fee(venue: str, price: Decimal | None) -> Decimal | None:
    if price is None:
        return None
    spec = {"venue": str(venue or "").lower(), "fee_coefficient": POLY_THETA}
    return live_lock_orders.leg_fee(spec, price)


def parse_freeze() -> list[dict]:
    if not DENSE.is_file():
        return []
    text = DENSE.read_text(encoding="utf-8")
    start = text.find("<h2>7. Per-match dense tennis</h2>")
    end = text.find("<h2>8. Near-miss books", start)
    if start < 0 or end < 0:
        return []
    chunk = text[start:end]
    rows = []
    for match in re.finditer(
        r"<tr><td>(.*?)</td><td>(.*?)</td><td>(.*?)</td><td>(.*?)</td>"
        r"<td>(.*?)</td><td>(.*?)</td><td>(.*?)</td><td>(.*?)</td>",
        chunk,
    ):
        game = html.unescape(match.group(1))
        date = html.unescape(match.group(2))
        venue = html.unescape(match.group(3)).lower()
        t0_a = _dec(html.unescape(match.group(5)))
        t0_b = _dec(html.unescape(match.group(7)))
        c0 = _dec(html.unescape(match.group(8)))
        if c0 is None and t0_a is not None and t0_b is not None:
            c0 = t0_a + t0_b
        if not game or not venue or c0 is None:
            continue
        fee_a = estimate_fee(venue, t0_a)
        fee_b = estimate_fee(venue, t0_b)
        all_in = None
        if t0_a is not None and t0_b is not None and fee_a is not None and fee_b is not None:
            all_in = t0_a + t0_b + fee_a + fee_b
        rows.append(
            {
                "game": game,
                "date": date,
                "venue": venue,
                "t0_a": t0_a,
                "t0_b": t0_b,
                "wire": c0,
                "all_in": all_in,
            }
        )
    return rows


def _leg_wire(row: dict) -> Decimal | None:
    return _dec(row.get("yes_ask")) or _dec(row.get("price"))


def _leg_all_in(row: dict, venue: str, wire: Decimal | None) -> tuple[Decimal | None, Decimal | None]:
    fill = _dec(row.get("fill_px"))
    fee = _dec(row.get("fill_fee"))
    intent = str(row.get("intent") or "")
    cash = fill
    inverted = False
    if "BUY_SHORT" in intent:
        inverted = True
    if fill is not None and wire is not None and abs((fill + wire) - Decimal("1")) <= Decimal("0.02"):
        inverted = True
    if inverted or (fill is not None and wire is not None and abs(fill - wire) > Decimal("0.05")):
        cash = wire
    if cash is None:
        cash = wire
    if fee is None and cash is not None:
        fee = estimate_fee(venue, cash)
        if fee is None:
            fee = Decimal("0")
    if cash is None:
        return None, fee
    return cash + (fee or Decimal("0")), fee


def parse_live() -> tuple[list[dict], list[dict]]:
    if not WATCH.is_file():
        return [], []
    data = json.loads(WATCH.read_text(encoding="utf-8"))
    tickets = []
    for item in data.get("matches") or []:
        if not isinstance(item, dict):
            continue
        t0 = item.get("t0_yes") if isinstance(item.get("t0_yes"), dict) else {}
        a = t0.get("a") if isinstance(t0.get("a"), dict) else {}
        b = t0.get("b") if isinstance(t0.get("b"), dict) else {}
        wa, wb = _leg_wire(a), _leg_wire(b)
        wire = wa + wb if wa is not None and wb is not None else None
        venue = str(item.get("venue") or a.get("venue") or b.get("venue") or "")
        aa, fa = _leg_all_in(a, venue, wa)
        ab, fb = _leg_all_in(b, venue, wb)
        all_in = aa + ab if aa is not None and ab is not None else None
        sent = bool(a.get("filled") or b.get("filled") or a.get("fill_px") or b.get("fill_px"))
        tickets.append(
            {
                "game": str(item.get("game") or ""),
                "venue": venue,
                "stage": str(item.get("stage") or ""),
                "sent": sent,
                "opened_at": str(item.get("opened_at") or ""),
                "wire": wire,
                "all_in": all_in if sent else None,
                "yes_a": wa,
                "yes_b": wb,
                "fill_fee_a": fa if sent else None,
                "fill_fee_b": fb if sent else None,
                "note": str(item.get("note") or ""),
            }
        )
    skipped = [row for row in (data.get("skipped") or []) if isinstance(row, dict)]
    return tickets, skipped


def main() -> None:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    freeze = parse_freeze()
    tickets, skipped = parse_live()
    sent = [row for row in tickets if row["sent"]]
    freeze_wire = [row["wire"] for row in freeze]
    freeze_all = [row["all_in"] for row in freeze]
    live_wire = [row["wire"] for row in sent]
    live_all = [row["all_in"] for row in sent]
    cw, ca = counts(freeze_wire), counts(freeze_all)
    lw, la = counts(live_wire), counts(live_all)
    skip_floor = [
        row
        for row in skipped
        if "0.95" in str(row.get("reason") or "") or "outside" in str(row.get("reason") or "").lower()
    ]

    freeze_rows = [
        [
            esc(row["game"]),
            esc(row["date"]),
            esc(row["venue"]),
            esc(_money(row["t0_a"])),
            esc(_money(row["t0_b"])),
            esc(_money(row["wire"])),
            esc(_money(row["all_in"])),
        ]
        for row in freeze
    ]
    live_rows = [
        [
            esc(row["game"]),
            esc(row["venue"]),
            esc(row["stage"]),
            "yes" if row["sent"] else "no",
            esc(_money(row["yes_a"])),
            esc(_money(row["yes_b"])),
            esc(_money(row["wire"])),
            esc(_money(row["all_in"])),
            esc(row["opened_at"][:19]),
        ]
        for row in sent
    ]
    bucket_labels = [label for label, _pred in buckets([])]
    freeze_wire_b = dict(buckets(freeze_wire))
    freeze_all_b = dict(buckets(freeze_all))
    live_wire_b = dict(buckets(live_wire))
    live_all_b = dict(buckets(live_all))
    bucket_rows = [
        [
            esc(label),
            str(freeze_wire_b.get(label, 0)),
            str(freeze_all_b.get(label, 0)),
            str(live_wire_b.get(label, 0)),
            str(live_all_b.get(label, 0)),
        ]
        for label in bucket_labels
    ]

    count_rows = [
        ["182-book freeze, T0 Yes asks (wire)", str(cw["n"]), str(cw["lt_100"]), str(cw["lt_099"]), str(cw["lt_095"]), esc(_money(cw["min"])), esc(_money(cw["max"]))],
        ["182-book freeze, estimated all-in with fees", str(ca["n"]), str(ca["lt_100"]), str(ca["lt_099"]), str(ca["lt_095"]), esc(_money(ca["min"])), esc(_money(ca["max"]))],
        ["Live B sent T0, Yes asks (wire)", str(lw["n"]), str(lw["lt_100"]), str(lw["lt_099"]), str(lw["lt_095"]), esc(_money(lw["min"])), esc(_money(lw["max"]))],
        ["Live B sent T0, all-in fill + fee", str(la["n"]), str(la["lt_100"]), str(la["lt_099"]), str(la["lt_095"]), esc(_money(la["min"])), esc(_money(la["max"]))],
    ]

    freeze_note = (
        f"Parsed {len(freeze)} rows from dense_inplay_yes_dip_20261021.html section 7 "
        "(the 182-book D=25 universe). That set was already filtered to C in [0.95, 1.20], "
        "so C < 0.95 is zero by construction — the floor hid those books from the freeze. "
        "The same dense page scanned 434 tennis T0s and kept 354 competitive C-in-range; "
        "the other 80 failed C band or the 10¢–90¢ Yes band. All-in on the freeze is "
        "estimated (Kalshi fee 0 pre-fill; Gemini taker formula; Polymarket theta 0.0695)."
    )
    live_note = (
        f"Watch file has {len(tickets)} Strategy B match rows, {len(sent)} with a T0 fill. "
        "Wire C uses frozen Yes ask / price. BUY_SHORT fill_px that sums with the Yes ask to ~$1 "
        "is the inverted ledger (Wolff / Trungelliti), not Yes cash — all-in uses the Yes ask plus "
        "stored fill_fee. Kalshi often stored fill_fee 0 even when GET had fees (Moutet), so live "
        "all-in can be a few cents light. "
        f"Recent skip log rows mentioning the old band: {len(skip_floor)}."
    )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{CACHE_META}
<title>Strategy B T0 under $1 — 2026-10-24</title>
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 24px; color: #1e293b; line-height: 1.45; }}
h1 {{ font-size: 1.7rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.25rem; margin-top: 1.7rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 12px 14px; margin: 12px 0; }}
.note {{ color: #475569; font-size: 0.95rem; }}
.warn {{ background: #fef2f2; padding: 10px 12px; border: 1px solid #f87171; margin: 12px 0; }}
.ok {{ background: #f0fdf4; padding: 10px 12px; border: 1px solid #86efac; margin: 12px 0; }}
{SORTABLE_TH_CSS}
</style>
{FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Strategy B T0 under $1 (floor retired, stack wired)</h1>
<p class="note">Written {esc(now)}. Research live. Not gold. Not DailyRun. This page does not place orders. D=0.25 unchanged. Click column headers to sort.</p>

<div class="callout"><h2>What you asked</h2>
<p>{esc(ASKED)}</p>
</div>
<div class="callout"><h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>

<h2>Why C_LO=0.95 existed</h2>
<p>It was a <strong>freeze</strong>, not a lock. The 2026-10-21 tennis dual-Yes / dense in-play sims (<code>tennis_dual_yes_dip_no_20261021.py</code>, then the 182-book D=25 stamps) kept books whose two T0 Yes asks sat in [0.95, 1.20] and each Yes in (0.10, 0.90). Live Strategy B copied that band. 0.95 is the same number as the Yes+No lock-bot cap (LOCK_SUM / NET_MAX ≈ 0.95) and the 95¢ absorb print, but those are different machines. The floor was meant to keep “near $1, competitive” tennis moneylines. It was not “C below 0.95 is illegal.”</p>
<p>Paul is right: two Yes always pay $1, so C ≤ 0.99 after vig is an automatic win. The floor skipped the best T0s. C=0.90 would not send. Upper 1.20 is the vig/loss cap. Moutet vs Paul was 1.01 asks / ~1.035 all-in and still legal.</p>

<div class="ok">
<p><strong>Wired 24 Oct 2026.</strong> Live send: Yes-ask C ≤ 1.20, no 0.95 floor. Stack decision: all-in with fees &lt; $1. After venue confirm both legs qty ≥ 1, send another 1-contract IOC T0 pair on the same match until ask size &lt; 1, named balance deny, REST all-in ≥ $1, or 10 pairs. REST recheck before each send. MAX_OPEN_B_MATCHES is matches, not contracts. Size is 1 contract. D=0.25 unchanged. No GTC. Do not sell. No second Strategy B.</p>
</div>

<h2>Has C &lt; $1 ever happened?</h2>
<p class="note">{esc(freeze_note)} {esc(live_note)}</p>
{SWIPE_NOTE_HTML}
{table(
    [("Slice", "text"), ("N", "num"), ("C < 1.00", "num"), ("C < 0.99", "num"), ("C < 0.95", "num"), ("Min C", "num"), ("Max C", "num")],
    count_rows,
)}
<p>On the 182-book freeze, C &lt; 0.95 is <strong>never</strong> — the universe dropped those books. C &lt; 0.99 and C &lt; 1.00 are the rows that would now stack if live saw the same asks after fees. On live B tickets, wire C &lt; 0.95 / &lt; 0.99 was <strong>{"never" if lw["lt_095"] == 0 and lw["lt_099"] == 0 else "rare"}</strong> among sent T0s (count &lt;0.95 = {lw["lt_095"]}, &lt;0.99 = {lw["lt_099"]}, &lt;1.00 = {lw["lt_100"]} of {lw["n"]}). Watch <code>c</code> after the match can look cheap because later quotes overwrite; this table uses T0 Yes ask/price.</p>

<h2>C buckets</h2>
{SWIPE_NOTE_HTML}
{table(
    [("Bucket", "text"), ("Freeze wire", "num"), ("Freeze all-in est.", "num"), ("Live B wire", "num"), ("Live B all-in", "num")],
    bucket_rows,
)}

<h2>New stack rule</h2>
<ul>
<li><strong>Send:</strong> each Yes in (0.10, 0.90), Yes-ask C ≤ 1.20. C=0.90 sends. C=1.21 skips.</li>
<li><strong>Stack:</strong> only if all-in both-Yes with documented fees is strictly under $1. C=0.99 wire stacks when fees keep it under $1. C=1.01 does not. Fees can turn 0.99 wire into all-in ≥ $1 so no stack (Polymarket example).</li>
<li><strong>Each extra:</strong> 1 contract IOC, REST recheck both books, size ≥ 1, post-order venue confirm qty ≥ 1. One-leg extra is flattened (buy No); original T0 both-Yes stays. Stop.</li>
<li><strong>Cap:</strong> 10 T0 pairs per match including the first, plus remaining-cash named deny. Does not drain the account unbounded.</li>
<li><strong>Slots:</strong> stacking does not consume extra MAX_OPEN_B_MATCHES. That cap is matches.</li>
</ul>

<h2>Live B sent T0 tickets</h2>
<p class="note">One row per match that filled at least one T0 Yes. Click headers to sort.</p>
{SWIPE_NOTE_HTML}
{table(
    [("Match", "text"), ("Venue", "text"), ("Stage", "text"), ("Sent", "text"), ("Yes A", "num"), ("Yes B", "num"), ("Wire C", "num"), ("All-in C", "num"), ("Opened", "date")],
    live_rows,
)}

<h2>182-book freeze T0 C</h2>
<p class="note">Same keys as strategy_b_D_05_to_50_20261023 / dense in-play D=25. Wire C is T0 Yes A + Yes B. All-in adds estimated venue fees. Click headers to sort.</p>
{SWIPE_NOTE_HTML}
{table(
    [("Match", "text"), ("Date", "date"), ("Venue", "text"), ("T0 A", "num"), ("T0 B", "num"), ("Wire C", "num"), ("All-in est.", "num")],
    freeze_rows,
)}

<p class="note">Sources: <code>tools/live_strategy_b.py</code> C_LO comment + in_c_band / maybe_stack_t0; <code>tools/tennis_dual_yes_dip_no_20261021.py</code> C_LO, C_HI; dense HTML 182-book table; local <code>strategy_b_watch.json</code>. Tests in <code>tools/test_live_strategy_b.py</code>. job_status Strategy B block has a T0 C / stack line after the next rewrite. No secrets. Did not start a second B.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(page, encoding="utf-8")
    print(f"wrote {PAGE}")
    print("freeze", cw)
    print("freeze_all_in", ca)
    print("live_sent", lw)
    print("live_all_in", la)


if __name__ == "__main__":
    main()
