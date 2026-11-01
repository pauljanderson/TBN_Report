"""Venue → kitchen miss ingest (bidirectional reconcile).

Tape→venue already lives in live_pm_settle_reconcile (kitchen oid → fills).
This module covers the other direction: venue settlements/fills that the
kitchen never booked (both_unfilled ghosts, unlabeled Kalshi losses).

Does not place, cancel, or sell. Bounded. Safe to call from reconcile_once.

    from pm_venue_miss_ingest import ingest_kalshi_settlements
    n = ingest_kalshi_settlements(store, settlements, fills=fills)
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
