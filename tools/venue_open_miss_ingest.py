"""Venue open positions + recent fills → kitchen tape (dashboard source).

When a sportsbook shows a live position or a today fill the kitchen never
booked onto orders.jsonl, append a claim+sent pair the dashboard clusterer
understands, then rebuild orders_performance / dashboard.

Orphan event=filled rows alone are invisible to write_orders_performance
(cluster_lock_attempts requires a preceding claim). Always write claim+sent.

Does not place, cancel, or sell.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterable
from zoneinfo import ZoneInfo

from prediction_paths import RAW_DIR as RAW, ensure_dirs

ET = ZoneInfo("America/New_York")
ORDERS = RAW / "orders.jsonl"


def _dec(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace("$", "").replace(",", ""))
    except Exception:
        return None


def _iso_now() -> str:
    return datetime.now(ET).isoformat(timespec="seconds")


def _parse_when(value) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        stamp = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            if text.isdigit():
                # Kalshi/unix seconds or ms.
                n = int(text)
                if n > 10_000_000_000:
                    n = n / 1000.0
                stamp = datetime.fromtimestamp(n, tz=ET)
            else:
                stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=ET)
    return stamp.astimezone(ET)


def _instrument_of(row: dict) -> str:
    return str(
        row.get("instrument")
        or row.get("ticker")
        or row.get("market_ticker")
        or row.get("slug")
        or ""
    ).strip()


def _side_of(row: dict) -> str:
    raw = str(row.get("side") or row.get("outcome") or row.get("pay") or "").strip().lower()
    if raw in {"yes", "no"}:
        return raw
    if raw in {"bid", "buy", "long"}:
        return "yes"
    if raw in {"ask", "sell", "short"}:
        return "no"
    pos = _dec(row.get("position_fp") or row.get("position") or row.get("qty"))
    if pos is not None and pos < 0:
        return "no"
    yes_n = _dec(row.get("yes_count_fp"))
    no_n = _dec(row.get("no_count_fp"))
    if yes_n is not None and yes_n > 0:
        return "yes"
    if no_n is not None and no_n > 0:
        return "no"
    return "yes"


def _qty_of(row: dict) -> Decimal:
    for key in (
        "qty",
        "confirm_qty",
        "count_fp",
        "count",
        "fill_count",
        "size",
        "position_fp",
        "position",
        "yes_count_fp",
        "no_count_fp",
        "netPositionDecimal",
        "net",
    ):
        qty = _dec(row.get(key))
        if qty is not None and abs(qty) > 0:
            return abs(qty)
    return Decimal("0")


def _tape_has(instrument: str, venue: str, side: str, rows: list[dict]) -> bool:
    want_i = instrument.lower()
    want_v = venue.lower()
    want_s = side.lower()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("venue") or "").lower() != want_v:
            continue
        inst = _instrument_of(row).lower()
        if inst != want_i:
            # Also match bet_key venue-open|venue-fill tabs.
            key = str(row.get("bet_key") or "").lower()
            if want_i and want_i not in key:
                continue
        event = str(row.get("event") or "")
        if event in {"claim", "sent", "filled", "one_leg"}:
            row_side = str(row.get("outcome") or row.get("side") or "").lower()
            if not want_s or not row_side or row_side == want_s:
                return True
        if event == "flatten_filled":
            return True
    return False


def _read_orders() -> list[dict]:
    if not ORDERS.exists():
        return []
    out: list[dict] = []
    try:
        import json

        for line in ORDERS.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict):
                out.append(row)
    except OSError:
        return []
    return out


def _append_order(row: dict) -> None:
    import json

    ensure_dirs()
    with ORDERS.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def claim_sent_pair(
    *,
    venue: str,
    instrument: str,
    side: str,
    qty: Decimal,
    game: str = "",
    when: str | None = None,
    source: str = "venue_open_miss_ingest",
    kind: str = "open",
    order_id: str = "",
    limit_price: str = "",
    note: str = "",
) -> list[dict]:
    """Build claim+sent rows the dashboard clusterer can score as fills."""
    shop = str(venue or "").lower()
    inst = str(instrument or "").strip()
    pay = str(side or "yes").lower()
    if pay not in {"yes", "no"}:
        pay = "yes"
    stamp = when or _iso_now()
    prefix = "venue-open" if kind == "open" else "venue-fill"
    bet_key = f"{prefix}\t{shop}\t{inst}\t{pay}"
    oid = order_id or f"{prefix}|{shop}|{inst}|{pay}"
    claim = {
        "event": "claim",
        "bet_key": bet_key,
        "game": game or inst,
        "sport": "",
        "compared_at": stamp,
        "source": source,
        "venue": shop,
        "instrument": inst,
        "side": pay,
        "outcome": pay,
    }
    sent = {
        "event": "sent",
        "bet_key": bet_key,
        "game": game or inst,
        "venue": shop,
        "instrument": inst,
        "side": pay,
        "outcome": pay,
        "confirm_qty": format(qty, "f"),
        "confirm_known": True,
        "qty": format(qty, "f"),
        "size": format(qty, "f"),
        "http_status": 200,
        "sent_at": stamp,
        "at": stamp,
        "order_id": oid,
        "source": source,
        "step": prefix,
        "system": "venue_sync",
        "limit_price": limit_price or "",
        "note": note
        or (
            "venue open position missing from kitchen tape; booked for dashboard sync"
            if kind == "open"
            else "venue fill missing from kitchen tape; booked for dashboard sync"
        ),
    }
    return [claim, sent]


def ingest_open_positions(
    positions: Iterable[dict],
    *,
    venue: str,
    tape: list[dict] | None = None,
    persist: bool = True,
) -> dict:
    """Append claim+sent rows for venue opens missing from the kitchen tape."""
    shop = str(venue or "").lower()
    rows = list(tape) if tape is not None else _read_orders()
    added = 0
    skipped = 0
    same_direction_n = 0
    written: list[dict] = []
    for pos in positions:
        if not isinstance(pos, dict):
            skipped += 1
            continue
        inst = _instrument_of(pos)
        qty = _qty_of(pos)
        if not inst or qty <= 0:
            skipped += 1
            continue
        # Kalshi whole contracts; Poly can be fractional leftovers.
        if shop == "kalshi" and qty < 1:
            skipped += 1
            continue
        side = _side_of(pos)
        if _tape_has(inst, shop, side, rows):
            skipped += 1
            continue
        pair = claim_sent_pair(
            venue=shop,
            instrument=inst,
            side=side,
            qty=qty,
            game=str(pos.get("title") or pos.get("game") or inst),
            when=_iso_now(),
            source="venue_open_miss_ingest",
            kind="open",
        )
        written.extend(pair)
        rows.extend(pair)
        added += 1
    if persist and written:
        for row in written:
            _append_order(row)
        _schedule_rebuild()
        try:
            import kalshi_same_direction as ksd

            stacks = ksd.find_same_direction_stacks(rows)
            same_direction_n = len(stacks)
        except Exception:
            same_direction_n = 0
    return {
        "added": added,
        "skipped": skipped,
        "same_direction_n": same_direction_n,
        "venue": shop,
        "written": written,
    }


def ingest_recent_fills(
    fills: Iterable[dict],
    *,
    venue: str,
    tape: list[dict] | None = None,
    persist: bool = True,
    since: datetime | None = None,
) -> dict:
    """Book venue fills from today (ET) that never hit orders.jsonl."""
    shop = str(venue or "").lower()
    rows = list(tape) if tape is not None else _read_orders()
    start = since or datetime.now(ET).replace(hour=0, minute=0, second=0, microsecond=0)
    added = 0
    skipped = 0
    written: list[dict] = []
    for fill in fills:
        if not isinstance(fill, dict):
            skipped += 1
            continue
        inst = _instrument_of(fill)
        qty = _qty_of(fill)
        if not inst or qty <= 0:
            skipped += 1
            continue
        if shop == "kalshi" and qty < 1:
            skipped += 1
            continue
        when = (
            _parse_when(fill.get("created_time"))
            or _parse_when(fill.get("created_ts"))
            or _parse_when(fill.get("ts"))
            or _parse_when(fill.get("timestamp"))
            or _parse_when(fill.get("filled_at"))
            or _parse_when(fill.get("at"))
        )
        if when is None or when < start:
            skipped += 1
            continue
        side = _side_of(fill)
        if _tape_has(inst, shop, side, rows):
            skipped += 1
            continue
        oid = str(
            fill.get("order_id")
            or fill.get("trade_id")
            or fill.get("fill_id")
            or fill.get("id")
            or ""
        )
        pair = claim_sent_pair(
            venue=shop,
            instrument=inst,
            side=side,
            qty=qty,
            game=str(fill.get("title") or fill.get("game") or inst),
            when=when.isoformat(timespec="seconds"),
            source="venue_fill_miss_ingest",
            kind="fill",
            order_id=oid or f"venue-fill|{shop}|{inst}|{side}|{when.isoformat(timespec='seconds')}",
            limit_price=str(fill.get("yes_price") or fill.get("price") or fill.get("avg_price") or ""),
            note="venue fill missing from kitchen tape; booked for dashboard sync",
        )
        written.extend(pair)
        rows.extend(pair)
        added += 1
    if persist and written:
        for row in written:
            _append_order(row)
        _schedule_rebuild()
    return {
        "added": added,
        "skipped": skipped,
        "venue": shop,
        "written": written,
        "since": start.isoformat(timespec="seconds"),
    }


def _schedule_rebuild() -> None:
    try:
        import orders_performance_refresh

        orders_performance_refresh.schedule_rebuild("venue_open_miss_ingest")
    except Exception:
        pass


def rebuild_dashboard_now(*, reason: str = "venue_sync") -> dict:
    """Synchronous kitchen + dashboard rewrite so Paul sees trades without waiting."""
    import os

    out = {"reason": reason, "orders_performance": False, "dashboard": False}
    # Prevent ingest→main→ingest recursion.
    prev = os.environ.get("SKIP_VENUE_SYNC_INGEST")
    os.environ["SKIP_VENUE_SYNC_INGEST"] = "1"
    try:
        try:
            import write_orders_performance as wop

            code = wop.main()
            out["orders_performance"] = code == 0
        except Exception as exc:
            out["orders_performance_error"] = f"{type(exc).__name__}: {exc}"
        try:
            import write_dashboard as wd

            code = wd.main()
            out["dashboard"] = code == 0
        except Exception as exc:
            out["dashboard_error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if prev is None:
            os.environ.pop("SKIP_VENUE_SYNC_INGEST", None)
        else:
            os.environ["SKIP_VENUE_SYNC_INGEST"] = prev
    return out


def _kalshi_rows_from_payload(payload: dict | None) -> list[dict]:
    body = (payload or {}).get("body") if isinstance(payload, dict) else {}
    if not isinstance(body, dict):
        # dump_kalshi_recon nests under positions.body
        if isinstance(payload, dict) and isinstance(payload.get("market_positions"), list):
            body = payload
        else:
            body = {}
    rows: list[dict] = []
    for item in body.get("market_positions") or []:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or "").strip()
        if not ticker:
            continue
        rows.append(
            {
                "venue": "kalshi",
                "ticker": ticker,
                "instrument": ticker,
                "position_fp": item.get("position_fp") or item.get("position"),
                "position": item.get("position_fp") or item.get("position"),
                "yes_count_fp": item.get("yes_count_fp"),
                "no_count_fp": item.get("no_count_fp"),
                "title": item.get("title") or ticker,
            }
        )
    return rows


def _kalshi_fills_from_payload(payload: dict | None) -> list[dict]:
    rows: list[dict] = []
    if not isinstance(payload, dict):
        return rows
    body = payload.get("body") if isinstance(payload.get("body"), dict) else payload
    fills = body.get("fills") if isinstance(body, dict) else None
    if fills is None and isinstance(payload.get("fills"), list):
        fills = payload.get("fills")
    if not isinstance(fills, list):
        return rows
    for item in fills:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or item.get("market_ticker") or "").strip()
        if not ticker:
            continue
        rows.append(
            {
                "venue": "kalshi",
                "ticker": ticker,
                "instrument": ticker,
                "side": item.get("side") or item.get("action"),
                "count_fp": item.get("count_fp") or item.get("count"),
                "qty": item.get("count_fp") or item.get("count"),
                "yes_price": item.get("yes_price") or item.get("price"),
                "created_time": item.get("created_time") or item.get("ts"),
                "order_id": item.get("order_id") or item.get("trade_id") or item.get("fill_id"),
                "title": item.get("title") or ticker,
            }
        )
    return rows


def _poly_rows_from_payload(payload: dict | None) -> list[dict]:
    rows: list[dict] = []
    if not isinstance(payload, dict):
        return rows
    # write_orders_performance shape: rows=[{slug, net, outcome, ...}]
    for item in payload.get("rows") or []:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug") or item.get("instrument") or "").strip()
        if not slug:
            continue
        rows.append(
            {
                "venue": "polymarket",
                "slug": slug,
                "instrument": slug,
                "qty": item.get("net") or item.get("qty") or item.get("position"),
                "side": item.get("outcome") or item.get("side"),
                "outcome": item.get("outcome") or item.get("side"),
                "title": item.get("title") or slug,
            }
        )
    if rows:
        return rows
    # Raw signed GET body: {positions: {slug: {...}}}
    positions = payload.get("positions")
    if isinstance(positions, dict):
        for slug, item in positions.items():
            if not isinstance(item, dict):
                continue
            meta = item.get("marketMetadata") if isinstance(item.get("marketMetadata"), dict) else {}
            rows.append(
                {
                    "venue": "polymarket",
                    "slug": str(slug),
                    "instrument": str(slug),
                    "qty": item.get("netPositionDecimal") or item.get("netPosition"),
                    "side": meta.get("outcome") or item.get("outcome"),
                    "outcome": meta.get("outcome") or item.get("outcome"),
                    "title": meta.get("title") or str(slug),
                }
            )
    return rows


def _poly_fills_from_payload(payload: dict | None) -> list[dict]:
    rows: list[dict] = []
    if not isinstance(payload, dict):
        return rows
    fills = payload.get("fills")
    if isinstance(fills, dict):
        fills = fills.get("fills") or fills.get("data") or fills.get("trades") or []
    if not isinstance(fills, list):
        return rows
    for item in fills:
        if not isinstance(item, dict):
            continue
        slug = str(
            item.get("slug")
            or item.get("instrument")
            or item.get("market")
            or item.get("ticker")
            or ""
        ).strip()
        if not slug:
            continue
        rows.append(
            {
                "venue": "polymarket",
                "slug": slug,
                "instrument": slug,
                "qty": item.get("size") or item.get("qty") or item.get("amount") or item.get("fill_count"),
                "side": item.get("outcome") or item.get("side") or item.get("intent"),
                "outcome": item.get("outcome") or item.get("side"),
                "created_time": item.get("created_at")
                or item.get("timestamp")
                or item.get("matchTime")
                or item.get("ts"),
                "order_id": item.get("order_id") or item.get("id") or item.get("trade_id"),
                "price": item.get("price") or item.get("avg_price"),
                "title": item.get("title") or slug,
            }
        )
    return rows


def load_kalshi_open_positions(*, live: bool = False) -> list[dict]:
    """Prefer on-disk recon/cache; optionally refresh via signed GET."""
    import json

    ensure_dirs()
    if live:
        try:
            import cheaper_same_bet

            return _kalshi_rows_from_payload(cheaper_same_bet.fetch_positions())
        except Exception:
            pass
    for path in (
        RAW / "kalshi_recon_dump" / "kalshi_recon_dump_latest.json",
        RAW / "kalshi_positions_pull.json",
        RAW / "pm_recon_dump" / "pm_recon_dump_latest.json",
    ):
        if not path.is_file():
            continue
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(blob, dict):
            continue
        if path.name.startswith("pm_"):
            block = ((blob.get("venues") or {}).get("kalshi") or {}).get("positions") or {}
            rows = _kalshi_rows_from_payload(block if isinstance(block, dict) else {})
        elif "kalshi_recon_dump" in str(path):
            rows = _kalshi_rows_from_payload(blob.get("positions") or blob)
        else:
            rows = _kalshi_rows_from_payload(blob)
        if rows:
            return rows
    return []


def load_poly_open_positions(*, live: bool = False) -> list[dict]:
    import json

    ensure_dirs()
    if live:
        try:
            import write_orders_performance as wop

            return _poly_rows_from_payload(wop.fetch_polymarket_positions())
        except Exception:
            pass
    for path in (
        RAW / "polymarket_positions_pull.json",
        RAW / "pm_recon_dump" / "pm_recon_dump_latest.json",
    ):
        if not path.is_file():
            continue
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(blob, dict):
            continue
        if path.name.startswith("pm_"):
            block = ((blob.get("venues") or {}).get("polymarket") or {}).get("positions") or {}
            rows = _poly_rows_from_payload(block if isinstance(block, dict) else {})
        else:
            # pull file may wrap body
            rows = _poly_rows_from_payload(blob.get("body") or blob)
            if not rows:
                rows = _poly_rows_from_payload(blob)
        if rows:
            return rows
    return []


def load_kalshi_recent_fills() -> list[dict]:
    import json

    ensure_dirs()
    for path in (
        RAW / "kalshi_recon_dump" / "kalshi_recon_dump_latest.json",
        RAW / "pm_recon_dump" / "pm_recon_dump_latest.json",
    ):
        if not path.is_file():
            continue
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(blob, dict):
            continue
        if path.name.startswith("pm_"):
            block = ((blob.get("venues") or {}).get("kalshi") or {}).get("fills") or {}
            rows = _kalshi_fills_from_payload(block if isinstance(block, dict) else {})
        else:
            rows = _kalshi_fills_from_payload(blob.get("fills") or blob)
        if rows:
            return rows
    return []


def load_poly_recent_fills() -> list[dict]:
    import json

    ensure_dirs()
    for path in (
        RAW / "pm_recon_dump" / "pm_recon_dump_latest.json",
        RAW / "polymarket_fills_pull.json",
    ):
        if not path.is_file():
            continue
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(blob, dict):
            continue
        if path.name.startswith("pm_"):
            block = (blob.get("venues") or {}).get("polymarket") or {}
            rows = _poly_fills_from_payload(block if isinstance(block, dict) else {})
        else:
            rows = _poly_fills_from_payload(blob)
        if rows:
            return rows
    return []


def ingest_from_venue_pulls(
    *,
    persist: bool = True,
    live: bool = False,
    include_fills: bool = True,
    rebuild: bool = False,
) -> dict:
    """Venue open books (+ today fills) → orders.jsonl → optional dashboard rebuild."""
    kalshi = load_kalshi_open_positions(live=live)
    poly = load_poly_open_positions(live=live)
    tape = _read_orders()
    k_rep = ingest_open_positions(kalshi, venue="kalshi", tape=tape, persist=persist)
    for row in k_rep.get("written") or []:
        tape.append(row)
    p_rep = ingest_open_positions(poly, venue="polymarket", tape=tape, persist=persist)
    for row in p_rep.get("written") or []:
        tape.append(row)
    k_fill = {"added": 0, "skipped": 0}
    p_fill = {"added": 0, "skipped": 0}
    if include_fills:
        k_fill = ingest_recent_fills(
            load_kalshi_recent_fills(), venue="kalshi", tape=tape, persist=persist
        )
        for row in k_fill.get("written") or []:
            tape.append(row)
        p_fill = ingest_recent_fills(
            load_poly_recent_fills(), venue="polymarket", tape=tape, persist=persist
        )
        for row in p_fill.get("written") or []:
            tape.append(row)
    combined_added = (
        int(k_rep.get("added") or 0)
        + int(p_rep.get("added") or 0)
        + int(k_fill.get("added") or 0)
        + int(p_fill.get("added") or 0)
    )
    same_n = 0
    try:
        import kalshi_same_direction as ksd

        same_n = len(ksd.find_same_direction_stacks(tape))
    except Exception:
        same_n = max(int(k_rep.get("same_direction_n") or 0), int(p_rep.get("same_direction_n") or 0))
    rebuild_rep = None
    if rebuild and combined_added:
        rebuild_rep = rebuild_dashboard_now(reason="venue_sync_ingest")
    return {
        "added": combined_added,
        "skipped": int(k_rep.get("skipped") or 0)
        + int(p_rep.get("skipped") or 0)
        + int(k_fill.get("skipped") or 0)
        + int(p_fill.get("skipped") or 0),
        "same_direction_n": same_n,
        "kalshi": {k: v for k, v in k_rep.items() if k != "written"},
        "polymarket": {k: v for k, v in p_rep.items() if k != "written"},
        "kalshi_fills": {k: v for k, v in k_fill.items() if k != "written"},
        "polymarket_fills": {k: v for k, v in p_fill.items() if k != "written"},
        "kalshi_open_n": len(kalshi),
        "poly_open_n": len(poly),
        "rebuild": rebuild_rep,
    }
