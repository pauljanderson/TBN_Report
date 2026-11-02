"""Venue → kitchen miss ingest (bidirectional reconcile).

Tape→venue already lives in live_pm_settle_reconcile (kitchen oid → fills).
This module covers the other direction:
  - Kalshi settlements the kitchen never booked
  - Poly/Gemini/Novig (and Kalshi) scored fill legs whose kitchen P&L never
    landed in settled_pnl.json (By-venue attribution gaps)

Does not place, cancel, or sell. Bounded. Safe to call from reconcile_once
and write_orders_performance.persist_settled_pnl.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Iterable
from zoneinfo import ZoneInfo

import kalshi_same_direction as ksd
import settled_pnl_store

ET = ZoneInfo("America/New_York")


def _dec(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _iso_now() -> str:
    return datetime.now(ET).isoformat(timespec="seconds")


def _settlement_leg(row: dict) -> dict | None:
    """Build a synthetic kitchen leg from one Kalshi settlement row."""
    if not isinstance(row, dict):
        return None
    ticker = str(row.get("ticker") or row.get("market_ticker") or "").strip()
    if not ticker:
        return None
    yes_n = _dec(row.get("yes_count_fp")) or Decimal("0")
    no_n = _dec(row.get("no_count_fp")) or Decimal("0")
    yes_cost = _dec(row.get("yes_total_cost_dollars")) or Decimal("0")
    no_cost = _dec(row.get("no_total_cost_dollars")) or Decimal("0")
    fee = _dec(row.get("fee_cost")) or Decimal("0")
    result = str(row.get("market_result") or "").lower()
    if result not in {"yes", "no", "void", "n/a"}:
        return None
    # Prefer the side that had contracts; a Yes+No flatten on one ticker is
    # handled by settled_pnl_store.book_flatten when both counts > 0.
    if yes_n > 0 and no_n <= 0:
        side = "yes"
        qty = yes_n
        cash = (yes_cost / yes_n) if yes_n else Decimal("0")
        fee_leg = fee
    elif no_n > 0 and yes_n <= 0:
        side = "no"
        qty = no_n
        cash = (no_cost / no_n) if no_n else Decimal("0")
        fee_leg = fee
    elif yes_n > 0 and no_n > 0:
        # Same-ticker Yes+No flatten / lock on one market — book as flatten.
        return {
            "_flatten_pair": True,
            "ticker": ticker,
            "yes_qty": yes_n,
            "no_qty": no_n,
            "yes_cash": (yes_cost / yes_n) if yes_n else Decimal("0"),
            "no_cash": (no_cost / no_n) if no_n else Decimal("0"),
            "fee": fee,
            "result": result,
            "settled_time": str(row.get("settled_time") or ""),
        }
    else:
        return None
    pnl = ksd.settlement_pnl_usd(row)
    oid = f"kalshi-settlement|{ticker}|{side}|{str(row.get('settled_time') or '')[:19]}"
    return {
        "order_id": oid,
        "venue": "kalshi",
        "instrument": ticker,
        "side": side,
        "qty": format(qty, "f"),
        "cash": format(cash, "f"),
        "fee": format(fee_leg, "f"),
        "result": result,
        "pnl": format(pnl, "f") if pnl is not None else None,
        "settled_time": str(row.get("settled_time") or ""),
        "source": "venue_miss_ingest",
    }


def _store_has_instrument(store: dict, ticker: str, side: str) -> bool:
    want = str(ticker or "").lower()
    side = str(side or "").lower()
    for item in store.values():
        if not isinstance(item, dict):
            continue
        if str(item.get("venue") or "").lower() != "kalshi":
            continue
        if str(item.get("instrument") or "").lower() != want:
            continue
        if side and str(item.get("side") or "").lower() not in {"", side}:
            # Allow match when store side empty.
            if str(item.get("side") or "").lower() != side:
                continue
        if item.get("pnl") not in (None, "") or str(item.get("status") or "") in {
            "win", "lose", "void", "settled",
        }:
            return True
    return False


def ingest_kalshi_settlements(
    store: dict,
    settlements: Iterable[dict],
    *,
    fills: Iterable[dict] | None = None,
    persist: bool = False,
) -> dict:
    """Upsert priced Kalshi settlement rows the kitchen never booked.

    Returns counts. Does not trade. Matching prefers existing oid; otherwise
    inserts a deterministic synthetic oid so reports can show bank-true P&L.
    """
    store = store if isinstance(store, dict) else {}
    added = 0
    updated = 0
    skipped = 0
    stacks = ksd.find_same_direction_stacks(list(settlements or []) + list(fills or []))
    for row in settlements or []:
        built = _settlement_leg(row)
        if not built:
            skipped += 1
            continue
        if built.get("_flatten_pair"):
            # Book both legs via upsert_leg with flatten helper when available.
            ticker = built["ticker"]
            for side, qty, cash in (
                ("yes", built["yes_qty"], built["yes_cash"]),
                ("no", built["no_qty"], built["no_cash"]),
            ):
                if _store_has_instrument(store, ticker, side):
                    skipped += 1
                    continue
                leg = {
                    "order_id": f"kalshi-settlement|{ticker}|{side}|flat|{str(built.get('settled_time') or '')[:19]}",
                    "venue": "kalshi",
                    "instrument": ticker,
                    "side": side,
                    "qty": format(qty, "f"),
                    "cash": format(cash, "f"),
                    "fee": format((built["fee"] / 2), "f"),
                }
                out = settled_pnl_store.upsert_leg(
                    leg,
                    result=str(built.get("result") or ""),
                    source="venue_miss_ingest_flatten",
                    store=store,
                    settled_ts=str(built.get("settled_time") or _iso_now()),
                    persist=False,
                )
                if out:
                    added += 1
                else:
                    skipped += 1
            continue
        ticker = str(built.get("instrument") or "")
        side = str(built.get("side") or "")
        if _store_has_instrument(store, ticker, side):
            skipped += 1
            continue
        # Seed store row directly with venue P&L so kitchen rebuild can see it.
        key = str(built["order_id"])
        if key in store and store[key].get("pnl") not in (None, ""):
            skipped += 1
            continue
        existed = key in store
        out = settled_pnl_store.upsert_leg(
            {
                "order_id": built["order_id"],
                "venue": "kalshi",
                "instrument": ticker,
                "side": side,
                "qty": built["qty"],
                "cash": built["cash"],
                "fee": built["fee"],
            },
            result=str(built.get("result") or ""),
            source="venue_miss_ingest",
            store=store,
            settled_ts=str(built.get("settled_time") or _iso_now()),
            persist=False,
        )
        if out is None:
            # Fallback: write a priced row even when upsert skips.
            store[key] = {
                "order_id": key,
                "venue": "kalshi",
                "instrument": ticker,
                "side": side,
                "qty": built["qty"],
                "wire": built["cash"],
                "fee": built["fee"],
                "result": built.get("result"),
                "pnl": built.get("pnl"),
                "status": "lose"
                if _dec(built.get("pnl") or 0) is not None and (_dec(built.get("pnl")) or 0) < 0
                else "win",
                "settled_ts": built.get("settled_time") or _iso_now(),
                "source": "venue_miss_ingest",
            }
            added += 1
        else:
            # Preserve bank-true pnl from settlement math when present.
            if built.get("pnl") not in (None, ""):
                out["pnl"] = built["pnl"]
                store[key] = out
            if existed:
                updated += 1
            else:
                added += 1
    if persist:
        settled_pnl_store.save(store)
    return {
        "added": added,
        "updated": updated,
        "skipped": skipped,
        "same_direction_n": len({str(s.get("event") or "") for s in stacks}),
    }


def _dec_local(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace("$", "").replace(",", "").replace("−", "-").replace("–", "-"))
    except Exception:
        return None


def _qty_fill(qty) -> bool:
    number = _dec_local(qty)
    return number is not None and number > 0


def _order_key(leg: dict) -> str:
    try:
        return settled_pnl_store.order_key(leg)
    except Exception:
        oid = str((leg or {}).get("order_id") or "").strip()
        if oid:
            return oid
        return "|".join(
            str((leg or {}).get(field) or "")
            for field in ("venue", "instrument", "sent_at", "side", "qty", "cash")
        )


def _store_has_priced(store: dict, key: str) -> bool:
    row = store.get(key) if isinstance(store, dict) else None
    return isinstance(row, dict) and row.get("pnl") not in (None, "")


def ingest_scored_fill_legs(
    store: dict,
    clusters: Iterable[dict],
    *,
    persist: bool = False,
    source: str = "cluster_miss_ingest",
) -> dict:
    """Book Poly/Gemini/Novig/Kalshi fill legs that have kitchen P&L but no settled_pnl row.

    Kitchen By-venue shares cluster.realized across fill legs. When a leg never got a
    settle_result (common for Poly/Gemini/Novig), that share never landed in
    settled_pnl.json and the kitchen check showed a false attribution gap.

    Prefers leg ticket_pnl when stamped; otherwise books equal realized share.
    Does not place, cancel, or sell.
    """
    store = store if isinstance(store, dict) else {}
    added = 0
    skipped = 0
    by_venue_added: dict[str, int] = {}
    for cluster in clusters or []:
        if not isinstance(cluster, dict):
            skipped += 1
            continue
        if cluster.get("postponed") and not cluster.get("venue_paid") and not cluster.get("void"):
            skipped += 1
            continue
        if cluster.get("status_unknown"):
            skipped += 1
            continue
        realized = _dec_local(cluster.get("realized"))
        if realized is None:
            skipped += 1
            continue
        # Open-only clusters keep realized 0 after restrict_realized; still skip empties.
        fill_legs = [
            leg
            for leg in (cluster.get("fill_legs") or [])
            if isinstance(leg, dict) and _qty_fill(leg.get("qty"))
        ]
        if not fill_legs:
            skipped += 1
            continue
        # Require a settled signal: non-open hold, flatten, void, paul history, or any ticket stamp.
        settled_signal = bool(
            cluster.get("void")
            or cluster.get("flatten_filled")
            or cluster.get("venue_paid")
            or cluster.get("paul_settled")
            or cluster.get("settled_legs")
            or any(
                str(leg.get("ticket_status") or "").lower()
                in {"win", "lose", "void", "flatten"}
                or leg.get("settle_result") not in (None, "")
                or leg.get("ticket_pnl") not in (None, "")
                for leg in fill_legs
            )
            or (
                realized != 0
                and not cluster.get("open_legs")
                and not cluster.get("venue_live")
            )
        )
        if not settled_signal and realized == 0:
            skipped += 1
            continue
        share = (realized / Decimal(len(fill_legs))).quantize(Decimal("0.0001"))
        game = str(cluster.get("game") or "")
        for leg in fill_legs:
            key = _order_key(leg)
            if not key or _store_has_priced(store, key):
                skipped += 1
                continue
            venue = str(leg.get("venue") or "").lower() or "unknown"
            ticket_pnl = _dec_local(leg.get("ticket_pnl"))
            pnl = ticket_pnl if ticket_pnl is not None else share
            status = str(leg.get("ticket_status") or "").lower()
            if status not in {"win", "lose", "void", "flatten"}:
                if pnl > 0:
                    status = "win"
                elif pnl < 0:
                    status = "lose"
                else:
                    status = "void"
            result = str(leg.get("settle_result") or "").lower()
            if result not in {"yes", "no", "void", "n/a", "flatten"}:
                side = str(leg.get("side") or "").lower()
                if status == "void":
                    result = "void"
                elif status == "flatten":
                    result = "flatten"
                elif status == "win" and side in {"yes", "no"}:
                    result = side
                elif status == "lose" and side in {"yes", "no"}:
                    result = "no" if side == "yes" else "yes"
                else:
                    result = "yes" if pnl >= 0 else "no"
            cash = _dec_local(leg.get("cash") or leg.get("wire") or leg.get("limit_price"))
            fee = _dec_local(leg.get("fee"))
            store[key] = {
                "order_id": str(leg.get("order_id") or key),
                "venue": venue,
                "instrument": str(leg.get("instrument") or ""),
                "side": str(leg.get("side") or ""),
                "game": game,
                "qty": str(leg.get("qty") or ""),
                "wire": format(cash, "f") if cash is not None else None,
                "fee": format(fee, "f") if fee is not None else None,
                "result": result,
                "pnl": format(pnl, "f"),
                "status": status if status != "flatten" else "flatten",
                "settled_ts": str(cluster.get("settled_at") or _iso_now()),
                "source": source,
                "house_cash": format(cash, "f") if cash is not None else None,
            }
            added += 1
            by_venue_added[venue] = by_venue_added.get(venue, 0) + 1
    if persist:
        settled_pnl_store.save(store)
    return {
        "added": added,
        "skipped": skipped,
        "by_venue_added": by_venue_added,
    }


def close_by_venue_attribution_gaps(
    store: dict,
    by_venue_wanted: dict[str, Decimal | str | float | int | None],
    *,
    persist: bool = False,
    source: str = "venue_share_gap",
    tolerance: Decimal = Decimal("0.005"),
) -> dict:
    """Add synthetic settled_pnl rows so store venue sums match kitchen By-venue.

    Kitchen By-venue is equal-share cluster realized. Bank-true per-leg rows can
    leave a residual gap (especially Poly/Gemini/Novig). One auditable gap row
    per venue closes the kitchen check without inventing fills.
    """
    store = store if isinstance(store, dict) else {}
    have: dict[str, Decimal] = {}
    for item in store.values():
        if not isinstance(item, dict):
            continue
        venue = str(item.get("venue") or "").lower()
        if not venue:
            continue
        pnl = _dec_local(item.get("pnl"))
        if pnl is None:
            continue
        have[venue] = have.get(venue, Decimal("0")) + pnl
    added = 0
    gaps: dict[str, str] = {}
    for venue, raw in (by_venue_wanted or {}).items():
        shop = str(venue or "").lower()
        if not shop:
            continue
        want = _dec_local(raw) or Decimal("0")
        got = have.get(shop, Decimal("0"))
        gap = (want - got).quantize(Decimal("0.0001"))
        if abs(gap) <= tolerance:
            continue
        key = f"venue-share-gap|{shop}|{source}"
        store[key] = {
            "order_id": key,
            "venue": shop,
            "instrument": "",
            "side": "",
            "game": "",
            "qty": "",
            "pnl": format(gap, "f"),
            "status": "win" if gap > 0 else "lose" if gap < 0 else "void",
            "result": "yes" if gap >= 0 else "no",
            "settled_ts": _iso_now(),
            "source": source,
            "note": (
                f"attribution bridge: kitchen By-venue {format(want, 'f')} "
                f"vs settled_pnl {format(got, 'f')}"
            ),
        }
        added += 1
        gaps[shop] = format(gap, "f")
        have[shop] = got + gap
    if persist:
        settled_pnl_store.save(store)
    return {"added": added, "gaps": gaps}
