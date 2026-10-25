#!/usr/bin/env python3
"""Search StungEvents for a band/artist name.

Usage:
  python tools/stung_search.py "Built to Spill"
  python tools/stung_search.py "Built to Spill" --days 60
  python tools/stung_search.py "Built to Spill" --raw
"""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone


def parse_start(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace(" ", "T")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help='Artist/band name, e.g. "Built to Spill"')
    parser.add_argument("--days", type=int, default=0, help="Only upcoming events within N days (0 = all returned)")
    parser.add_argument("--raw", action="store_true", help="Print full JSON")
    args = parser.parse_args()

    url = "https://api.stungevents.com/search?q=" + urllib.parse.quote(args.query)
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "tbn-stung-search/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)

    if args.raw:
        print(json.dumps(data, indent=2))
        return 0

    events = data.get("events") or []
    if args.days > 0:
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=args.days)
        filtered = []
        for event in events:
            start = parse_start(event.get("start_utc"))
            if start is None or start < now or start > end:
                continue
            filtered.append(event)
        events = filtered

    if not events:
        print(f"No events for {args.query!r}")
        return 0

    for event in events:
        # State (US) is often only inside raw_schema_json.addressRegion
        state = ""
        raw = event.get("raw_schema_json")
        if raw:
            try:
                schema = json.loads(raw) if isinstance(raw, str) else raw
                state = ((schema.get("location") or {}).get("address") or {}).get("addressRegion") or ""
            except (TypeError, json.JSONDecodeError):
                state = ""
        place = event.get("city") or ""
        if state:
            place = f"{place}, {state}" if place else state
        country = event.get("country") or ""
        print(
            f"{event.get('start_utc')} | {place} | {country} | "
            f"{event.get('venue_name')} | {event.get('title')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
