"""Autopsy: opportunities SENT both-filled for TB-CAR + New Mexico St. was a ghost.

Research only. Does not sell, start B, bump stake, or wire D NFL.
Does not print secrets. Fill-history GET is read-only.
"""
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

import kalshi_private  # noqa: E402
import live_lock_orders  # noqa: E402
import novig_live  # noqa: E402
import opportunity_considerations  # noqa: E402
import polymarket_us_live  # noqa: E402
import report_page_extras  # noqa: E402
from prediction_paths import DRIVE_STAMP as STAMP, RAW_DIR as RAW  # noqa: E402

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "false_sent_tbcar_nms_20261026.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/false_sent_tbcar_nms_20261026.html"
)
ASKED = opportunity_considerations.ASKED_FALSE_SENT
PLAIN = (
    "Paul saw a green SENT row that looked like we bought both sides of a Tampa Bay vs "
    "Carolina football spread. The same row named New Mexico State covering 9.5 points, "
    "said Yes on Kalshi and No on Novig, then claimed Kalshi and Polymarket both filled "
    "one contract. He opened Kalshi and Polymarket and found no such ticket. That is "
    "because the row is a ghost: a leftover log slot from a unit test, not an order. "
    "The bot never posted this pair. There is no order id. HTTP 201 with fill count 0 "
    "is an empty cancel, not a fill. We struck the mixed rows, and the log will not call "
    "HTTP-OK a fill unless that venue’s fill-history quantity is at least 1."
)
NEEDLES = (
    "tampa",
    "carolina",
    "buccaneer",
    "panther",
    "new mexico",
    "nmsu",
    "nms",
)
TARGET_AT = "2026-10-26T18:37:39"


def esc(value) -> str:
    return html_lib.escape(str("" if value is None else value), quote=True)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{esc(kind)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def table(headers: list[tuple[str, str]], rows: list[list[str]], caption: str = "") -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        tds = "".join(f"<td>{cell}</td>" for cell in row)
        body.append(f"<tr>{tds}</tr>")
    cap = f"<p class=\"note\">{esc(caption)}</p>" if caption else ""
    return (
        f"{cap}{report_page_extras.SWIPE_NOTE_HTML}"
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


def _blob(value) -> str:
    try:
        return json.dumps(value, default=str).lower()
    except Exception:
        return str(value).lower()


def _hits(value) -> bool:
    blob = _blob(value)
    return any(mark in blob for mark in NEEDLES)


def _iso_ok(text: str) -> bool:
    return TARGET_AT[:16] in (text or "")


def load_considerations() -> list[dict]:
    path = opportunity_considerations.LOG_PATH
    if not path.exists():
        return []
    return opportunity_considerations._load(path.read_text(encoding="utf-8"))


def mixed_rows(rows: list[dict]) -> list[dict]:
    return [row for row in rows if opportunity_considerations.is_mixed_game_side_ghost(row)]


def target_rows(rows: list[dict]) -> list[dict]:
    return [row for row in rows if _iso_ok(str(row.get("at") or ""))]


def scan_jsonl(path: Path, limit: int = 400000) -> dict:
    out = {
        "path": str(path),
        "exists": path.exists(),
        "n": 0,
        "order_posts": 0,
        "filled_events": 0,
        "hits": [],
        "window_events": [],
    }
    if not path.exists():
        return out
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            out["n"] += 1
            low = raw.lower()
            in_window = "2026-10-26t18:3" in low or "2026-10-26t22:3" in low
            hit = _hits(raw)
            is_post = '"kind": "order"' in raw or '"kind":"order"' in raw
            is_filled = '"event": "filled"' in raw or '"event":"filled"' in raw
            if is_post:
                out["order_posts"] += 1
            if is_filled:
                out["filled_events"] += 1
            if in_window and (is_post or is_filled or hit or '"event": "sent"' in raw):
                try:
                    row = json.loads(raw)
                except json.JSONDecodeError:
                    row = {"raw": raw[:240]}
                bit = {
                    "at": row.get("at") or row.get("ts") or row.get("t") or "",
                    "event": row.get("event") or row.get("kind") or "",
                    "venue": row.get("venue") or "",
                    "game": row.get("game") or row.get("title") or "",
                    "order_id": row.get("order_id") or row.get("orderId") or "",
                    "http": row.get("http_status") or row.get("status") or "",
                }
                out["window_events"].append(bit)
            if hit and ("2026-10-26" in low) and len(out["hits"]) < 12:
                try:
                    row = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                out["hits"].append({
                    "at": row.get("at") or row.get("ts") or "",
                    "event": row.get("event") or row.get("kind") or "",
                    "game": str(row.get("game") or "")[:80],
                    "venue": row.get("venue") or "",
                    "order_id": str(row.get("order_id") or row.get("orderId") or "")[:40],
                })
            if out["n"] >= limit:
                break
    return out


def _parse(text: str):
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def pull_venues() -> dict:
    """Read-only fill-history. No order ids on the ghost row, so scan recent fills."""
    out: dict = {}

    kalshi_pages = []
    kalshi_rows = []
    try:
        cursor = ""
        for _ in range(3):
            query = {"limit": "200"}
            if cursor:
                query["cursor"] = cursor
            status, text = kalshi_private.get_fills(query, timeout=20)
            kalshi_pages.append({"http": status, "bytes": len(text or "")})
            data = _parse(text) if status == 200 else None
            batch = []
            if isinstance(data, dict):
                batch = data.get("fills") or data.get("items") or []
                cursor = str(data.get("cursor") or "")
            if not isinstance(batch, list):
                batch = []
            for item in batch:
                if isinstance(item, dict):
                    kalshi_rows.append({
                        "ticker": item.get("ticker") or item.get("market_ticker") or "",
                        "order_id": item.get("order_id") or "",
                        "count": item.get("count_fp") or item.get("count") or item.get("fill_count") or "",
                        "ts": item.get("ts") or item.get("created_time") or "",
                        "side": item.get("side") or "",
                    })
            if not cursor or not batch:
                break
        matching = [row for row in kalshi_rows if _hits(row)]
        out["kalshi"] = {
            "endpoint": "GET /trade-api/v2/portfolio/fills",
            "http_pages": kalshi_pages,
            "n": len(kalshi_rows),
            "matching_tb_nms": len(matching),
            "sample": kalshi_rows[:8],
            "matching": matching[:8],
        }
    except Exception as exc:
        out["kalshi"] = {
            "endpoint": "GET /trade-api/v2/portfolio/fills",
            "error": type(exc).__name__,
            "http_pages": kalshi_pages,
        }

    poly_pages = []
    poly_rows = []
    try:
        cursor = ""
        for _ in range(4):
            query = {
                "limit": "100",
                "types": "ACTIVITY_TYPE_TRADE",
                "sortOrder": "SORT_ORDER_DESCENDING",
            }
            if cursor:
                query["cursor"] = cursor
            status, text = polymarket_us_live.get_activities(query, timeout=20)
            poly_pages.append({"http": status, "bytes": len(text or "")})
            data = _parse(text) if status == 200 else None
            batch = data.get("activities") if isinstance(data, dict) else []
            if not isinstance(batch, list):
                batch = []
            for item in batch:
                if not isinstance(item, dict):
                    continue
                order = item.get("order") if isinstance(item.get("order"), dict) else {}
                poly_rows.append({
                    "id": item.get("id") or order.get("id") or "",
                    "slug": item.get("marketSlug") or item.get("slug") or "",
                    "title": item.get("title") or item.get("marketTitle") or "",
                    "cum": order.get("cumQuantity") or item.get("cumQuantity") or "",
                    "ts": item.get("timestamp") or item.get("transactTime") or "",
                })
            cursor = str(data.get("nextCursor") or "") if isinstance(data, dict) else ""
            if bool(data.get("eof")) if isinstance(data, dict) else False:
                break
            if not cursor or not batch:
                break
        matching = [row for row in poly_rows if _hits(row)]
        out["polymarket"] = {
            "endpoint": "GET /v1/portfolio/activities",
            "http_pages": poly_pages,
            "n": len(poly_rows),
            "matching_tb_nms": len(matching),
            "sample": poly_rows[:8],
            "matching": matching[:8],
        }
    except Exception as extra:
        out["polymarket"] = {
            "endpoint": "GET /v1/portfolio/activities",
            "error": type(extra).__name__,
            "http_pages": poly_pages,
        }

    try:
        status, text = novig_live.list_fills({"limit": "100"}, timeout=20)
        data = _parse(text) if status == 200 else None
        items = []
        if isinstance(data, dict):
            raw_items = data.get("items")
            if isinstance(raw_items, list):
                items = [row for row in raw_items if isinstance(row, dict)]
        matching = [row for row in items if _hits(row)]
        slim = []
        for row in items[:8]:
            slim.append({
                "orderId": row.get("orderId") or "",
                "qty": row.get("qty") or "",
                "ts": row.get("transactTime") or row.get("ts") or "",
            })
        out["novig"] = {
            "endpoint": "GET /v3/portfolio/fills",
            "http": status,
            "n": len(items),
            "matching_tb_nms": len(matching),
            "sample": slim,
        }
    except Exception as extra:
        out["novig"] = {
            "endpoint": "GET /v3/portfolio/fills",
            "error": type(extra).__name__,
        }
    return out


def _row_cells(row: dict) -> list[str]:
    venues = f"Yes {row.get('yes_venue') or ''} / No {row.get('no_venue') or ''}"
    return [
        esc(row.get("at") or ""),
        esc(row.get("sport") or ""),
        esc(row.get("game") or ""),
        esc(row.get("side") or ""),
        esc(row.get("number") or ""),
        esc(venues),
        esc(row.get("yes_size") or ""),
        esc(row.get("no_size") or ""),
        esc(row.get("net") or ""),
        esc(row.get("decision") or ""),
        esc(row.get("reason") or ""),
        esc(row.get("venue_return") or ""),
        esc(row.get("order_id") or row.get("kalshi_ticker") or ""),
    ]


def write_page(facts: dict) -> Path:
    mixed = facts["mixed"]
    target = facts["target"]
    venues = facts["venues"]
    orders = facts["orders"]
    order_io = facts["order_io"]
    struck = facts["struck"]
    target_table = table(
        [
            ("Time ET", "date"),
            ("Sport", "text"),
            ("Game", "text"),
            ("Side", "text"),
            ("Number", "num"),
            ("Venues", "text"),
            ("Yes size", "num"),
            ("No size", "num"),
            ("After-fee", "num"),
            ("Decision now", "text"),
            ("Reason now", "text"),
            ("Venue return (as logged)", "text"),
            ("Ids / ticker", "text"),
        ],
        [_row_cells(row) for row in target] or [[esc("no 18:37:39 row left in log")]],
        "The 18:37:39 ET cluster. Click column headers to sort.",
    )
    mixed_table = table(
        [
            ("Time ET", "date"),
            ("Sport", "text"),
            ("Game", "text"),
            ("Side", "text"),
            ("Number", "num"),
            ("Venues", "text"),
            ("Yes size", "num"),
            ("No size", "num"),
            ("After-fee", "num"),
            ("Decision now", "text"),
            ("Reason now", "text"),
            ("Venue return (as logged)", "text"),
            ("Ids / ticker", "text"),
        ],
        [_row_cells(row) for row in mixed],
        f"{len(mixed)} mixed-label ghost row(s) in the 500-row log.",
    )

    def venue_block(name: str, row: dict) -> str:
        if not isinstance(row, dict):
            return f"<p class=\"note\">{esc(name)}: no pull.</p>"
        err = row.get("error")
        extra = f" error {err}" if err else ""
        matching = row.get("matching_tb_nms")
        http = row.get("http")
        if http in (None, ""):
            pages = row.get("http_pages") or []
            codes = [str(p.get("http")) for p in pages if isinstance(p, dict)]
            http = ",".join(codes) if codes else ""
        return (
            f"<p><strong>{esc(name)}</strong> {esc(row.get('endpoint') or '')}. "
            f"HTTP {esc(http)}. "
            f"Fills read: {esc(row.get('n'))}. TB/NMS matches: {esc(matching)}. "
            f"{esc(extra)}</p>"
        )

    orders_bits = (
        f"exists={orders.get('exists')} lines={orders.get('n')} "
        f"filled_events={orders.get('filled_events')} window_rows={len(orders.get('window_events') or [])} "
        f"tb/nms hits on 2026-10-26={len(orders.get('hits') or [])}"
    )
    io_bits = (
        f"exists={order_io.get('exists')} lines={order_io.get('n')} "
        f"kind=order posts in file={order_io.get('order_posts')} "
        f"window rows={len(order_io.get('window_events') or [])}"
    )
    body = f"""
<h1>False sent — Tampa Bay vs Carolina + New Mexico St.</h1>
<p class="note">America/New_York. Research only. Not gold. Not DailyRun. Not on GitHub Pages.</p>
<div class="callout"><h2>What you asked</h2><p>{esc(ASKED)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{esc(PLAIN)}</p></div>
<div class="callout"><h2>Verdict</h2>
<p><strong>Ghost. Not a real fill.</strong> Execute was not called for this pair. No Kalshi, Polymarket, or Novig order id. Quantity 0 vs the claimed fill 1. The 18:37:39 row is a leaked unit-test diary, not a ticket Paul owns.</p>
</div>
<h2>What the 18:37:39 row actually was</h2>
<p>Opportunities is not an opportunities.jsonl. The page is rebuilt from <code>local/.../raw/considerations.json</code> (500 rows). The 18:37:39.168-04:00 line is one of three identical 7-row clusters (18:36:30, 18:37:00, 18:37:32). Those clusters match <code>test_simultaneous_legs_and_only_a_one_leg_latches</code> calling mocked HTTP 201 into the live log: hard miss Gemini; one-leg Gemini/Kalshi flatten miss; both Gemini+Poly “fill 1”; both Kalshi+Poly “fill 1”; denied Novig (not two live venues); one-leg Poly flatten miss; hard miss Gemini 0/0.4. Sizes 2564.12 / 2579.64 exist only in the test fixture <code>_nmsu_under_send_line()</code>. Pair column Yes kalshi / No novig is that fixture. HTTP names kalshi / polymarket because the mocked send used those venues. Game title Tampa Bay vs Carolina leaked from <code>test_house_three_open_venues_zero_allows_send</code> leftover <code>threading.local()</code> consider slot.</p>
{target_table}
<h2>Mixed-label rows (all ghosts)</h2>
{mixed_table}
<h2>Local tape — was execute even called?</h2>
<p><strong>orders.jsonl:</strong> {esc(orders_bits)}. No filled / sent POST for this pair at 18:37. Catalog-verify execute handoff (agent e024dec1) did not send TB-CAR + NMS. Last real live “order both legs filled” in overnight_scan.log that evening was Minnesota vs Detroit at 15:21 ET. TB-CAR watch file last line is 2026-10-25 closed. one_leg_watch.json had no leftover at 18:37 (Dencheva stopped 16:11).</p>
<p><strong>order_io.jsonl:</strong> {esc(io_bits)}. 18:37 window is book GETs (Novig, Kalshi LACLAR), not order POSTs. We did not invent venue orders.</p>
<h2>Venue fill-history GET</h2>
<p>No order id on the row, so this is a recent-fill scan for Tampa / Carolina / New Mexico. Qty on this ghost is 0. Empty Poly activities must not override a real cumQuantity; here there is no cumQuantity and no aggressor id. Empty positions GET must not drop a confirmed fill while OPEN; here there is no confirmed fill.</p>
{venue_block("Kalshi", venues.get("kalshi") or {})}
{venue_block("Polymarket US", venues.get("polymarket") or {})}
{venue_block("Novig", venues.get("novig") or {})}
<h2>Why the labels mixed</h2>
<p>One thread-local consider slot. A house-cap unit test set sport=pro football, title=Tampa Bay vs Carolina, candidate=New Mexico St. over 9.5 Yes kalshi / No novig, sizes 2564.12 / 2579.64, net 0.98392, then restored the real <code>_log_consider</code> without clearing <code>_consider</code>. The next test called <code>_send_pair</code> seven times with mocked 201s while logging to live <code>considerations.json</code>. Catalog verify writing into the wrong slot is the same class of bug in production; leftover watch may still send a later pair if one-leg latched, but this row is not that. HTTP text said polymarket because that is who the mock posted; the leftover candidate still said novig.</p>
<h2>Fix shipped</h2>
<p>Struck {esc(struck)} mixed row(s) in considerations.json (decision denied, ghost flag). opportunities.html rebuilt with overlay. <code>_send_pair</code> rebinds consider to this pair; leftover TB-CAR + NMS is dropped. <code>execute_locks</code> denies mixed game/side before send. Tape fill qty ignores nested book qtyDecimal; HTTP 201 with fill_count 0 is fill 0, not fill 1. Mixed labels cannot record as sent. Sibling pages (Johnson glossary 7f751e24, orders.html all-systems e2103ec3) were not reverted. No sell. No second B. No stake bump. No D NFL wire.</p>
<p class="note">Log: <a href="opportunities.html">opportunities.html</a>. Click column headers to sort.</p>
<p class="tiny">Written {esc(datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"))}. {esc(FILE_URL)}. Sources: considerations.json, orders.jsonl, order_io.jsonl, Kalshi GET /portfolio/fills, Polymarket GET /portfolio/activities, Novig GET /portfolio/fills. Research only.</p>
"""
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>False sent TB-CAR + NMS — 26 Oct 2026</title>
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
    page = report_page_extras.inject_report_page_extras(page)
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(page, encoding="utf-8")
    tmp.replace(PAGE)
    return PAGE


def main() -> None:
    rows = load_considerations()
    mixed_before = mixed_rows(rows)
    target_before = target_rows(mixed_before) or target_rows(rows)
    orders = scan_jsonl(live_lock_orders.ORDERS)
    order_io = scan_jsonl(live_lock_orders.ORDER_IO)
    venues = pull_venues()
    opportunity_considerations.write_page()
    after = load_considerations()
    mixed_after = mixed_rows(after)
    struck = sum(1 for row in mixed_after if row.get("ghost"))
    facts = {
        "mixed": mixed_after or mixed_before,
        "target": target_rows(mixed_after) or target_before,
        "venues": venues,
        "orders": orders,
        "order_io": order_io,
        "struck": struck,
    }
    path = write_page(facts)
    print(path)
    print("struck", struck, "mixed", len(mixed_after), "target", len(facts["target"]))
    print("orders window", len(orders.get("window_events") or []), "io window", len(order_io.get("window_events") or []))
    for name in ("kalshi", "polymarket", "novig"):
        row = venues.get(name) or {}
        print(name, "n", row.get("n"), "match", row.get("matching_tb_nms"), "err", row.get("error"))


if __name__ == "__main__":
    main()
