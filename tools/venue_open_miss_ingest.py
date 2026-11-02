"""Venue open positions → kitchen tape (dashboard source of truth).

When a sportsbook shows a live position the kitchen never booked onto
orders.jsonl, append a synthetic filled row and schedule a dashboard rebuild.
Settlements still flow through pm_venue_miss_ingest; this covers OPEN books.

Does not place, cancel, or sell.
"""
from __future__ import annotations

from datetime import datetime
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
    for key in ("qty", "position_fp", "position", "yes_count_fp", "no_count_fp", "size"):
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
            continue
        event = str(row.get("event") or "")
        if event in {"filled", "one_leg", "sent"}:
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
        for line in ORDERS.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                import json

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


def ingest_open_positions(
    positions: Iterable[dict],
    *,
    venue: str,
    tape: list[dict] | None = None,
    persist: bool = True,
) -> dict:
    """Append filled rows for venue opens missing from the kitchen tape."""
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
        oid = f"venue-open|{shop}|{inst}|{side}"
        row = {
            "event": "filled",
            "bet_key": oid,
            "game": str(pos.get("title") or pos.get("game") or inst),
            "venue": shop,
            "instrument": inst,
            "outcome": side,
            "side": side,
            "confirm_qty": format(qty, "f"),
            "confirm_known": True,
            "qty": format(qty, "f"),
            "source": "venue_open_miss_ingest",
            "order_id": oid,
            "at": _iso_now(),
            "note": "venue open position missing from kitchen tape; booked for dashboard sync",
        }
        written.append(row)
        rows.append(row)
        added += 1
    if persist and written:
        for row in written:
            _append_order(row)
        try:
            import orders_performance_refresh

            orders_performance_refresh.schedule_rebuild("venue_open_miss_ingest")
        except Exception:
            pass
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


def ingest_from_venue_pulls(*, persist: bool = True, live: bool = False) -> dict:
    """Venue open books → orders.jsonl → dashboard rebuild. Bidirectional sync."""
    kalshi = load_kalshi_open_positions(live=live)
    poly = load_poly_open_positions(live=live)
    tape = _read_orders()
    k_rep = ingest_open_positions(kalshi, venue="kalshi", tape=tape, persist=persist)
    for row in k_rep.get("written") or []:
        tape.append(row)
    p_rep = ingest_open_positions(poly, venue="polymarket", tape=tape, persist=persist)
    for row in p_rep.get("written") or []:
        tape.append(row)
    combined_added = int(k_rep.get("added") or 0) + int(p_rep.get("added") or 0)
    same_n = 0
    try:
        import kalshi_same_direction as ksd

        same_n = len(ksd.find_same_direction_stacks(tape))
    except Exception:
        same_n = max(int(k_rep.get("same_direction_n") or 0), int(p_rep.get("same_direction_n") or 0))
    return {
        "added": combined_added,
        "skipped": int(k_rep.get("skipped") or 0) + int(p_rep.get("skipped") or 0),
        "same_direction_n": same_n,
        "kalshi": {k: v for k, v in k_rep.items() if k != "written"},
        "polymarket": {k: v for k, v in p_rep.items() if k != "written"},
        "kalshi_open_n": len(kalshi),
        "poly_open_n": len(poly),
    }
