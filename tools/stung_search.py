#!/usr/bin/env python3
"""Search StungEvents for one or more bands, optionally filtered by US state.

Examples:
  python tools/stung_search.py "Built to Spill"
  python tools/stung_search.py "Built to Spill" "Kurt Vile" --states MA,RI --days 60
  python tools/stung_search.py --from-heavy --states MA,RI --days 60
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_TOOLS = Path(__file__).resolve().parent


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


def event_state(event: dict) -> str:
    raw = event.get("raw_schema_json")
    if not raw:
        return ""
    try:
        schema = json.loads(raw) if isinstance(raw, str) else raw
        region = ((schema.get("location") or {}).get("address") or {}).get("addressRegion") or ""
        return str(region).strip().upper()
    except (TypeError, json.JSONDecodeError):
        return ""


def search_stung(query: str) -> list[dict]:
    url = "https://api.stungevents.com/search?q=" + urllib.parse.quote(query)
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "tbn-stung-search/1.1"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    return list(data.get("events") or [])


def filter_events(events: list[dict], days: int, states: set[str]) -> list[dict]:
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days) if days > 0 else None
    out: list[dict] = []
    for event in events:
        if days > 0:
            start = parse_start(event.get("start_utc"))
            if start is None or start < now or (end and start > end):
                continue
        if states:
            st = event_state(event)
            if st not in states:
                continue
        out.append(event)
    out.sort(key=lambda e: e.get("start_utc") or "")
    return out


def format_event(event: dict) -> str:
    state = event_state(event)
    place = event.get("city") or ""
    if state:
        place = f"{place}, {state}" if place else state
    country = event.get("country") or ""
    return (
        f"{event.get('start_utc')} | {place} | {country} | "
        f"{event.get('venue_name')} | {event.get('title')}"
    )


def artists_from_heavy(year: int) -> list[str]:
    sys.path.insert(0, str(REPO_TOOLS))
    from probe_stungevents_heavy import artists_from_playlist  # noqa: WPS433
    from sync_spotify_year_playlists import (  # noqa: WPS433
        DEFAULT_CACHE_PATH,
        DEFAULT_ENV_PATH,
        REPO_ROOT,
        build_client,
        load_env_file,
        playlist_names,
    )

    load_env_file(DEFAULT_ENV_PATH)
    load_env_file(REPO_ROOT / ".env")
    sp = build_client(DEFAULT_CACHE_PATH)
    name = playlist_names(year, "spaced")["heavy"]
    print(f"Reading Spotify playlist {name!r} …", file=sys.stderr)
    return artists_from_playlist(sp, name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("bands", nargs="*", help='Band name(s), e.g. "Built to Spill" "Kurt Vile"')
    parser.add_argument(
        "--from-heavy",
        action="store_true",
        help="Use artists from Spotify '{year} heavy' playlist instead of positional bands",
    )
    parser.add_argument("--year", type=int, default=datetime.now().year, help="Year for --from-heavy (default: current)")
    parser.add_argument(
        "--states",
        type=str,
        default="",
        help='Comma-separated US state codes, e.g. "MA,RI" (from addressRegion in raw JSON)',
    )
    parser.add_argument("--days", type=int, default=0, help="Only upcoming within N days (0 = no date filter)")
    parser.add_argument("--raw", action="store_true", help="Print full JSON per band (ignores pretty filters formatting)")
    args = parser.parse_args()

    states = {s.strip().upper() for s in args.states.split(",") if s.strip()}

    if args.from_heavy:
        bands = artists_from_heavy(args.year)
    else:
        bands = list(args.bands)

    if not bands:
        parser.error('Provide band name(s) or --from-heavy')

    print(
        f"Searching {len(bands)} band(s)"
        + (f"; states={sorted(states)}" if states else "")
        + (f"; days={args.days}" if args.days else "")
        + " …",
        file=sys.stderr,
    )

    any_hits = False
    for band in bands:
        try:
            events = search_stung(band)
        except Exception as exc:  # noqa: BLE001
            print(f"{band}: error: {exc}")
            continue
        if args.raw and not states and args.days <= 0:
            print(json.dumps({"band": band, "events": events}, indent=2))
            any_hits = bool(events) or any_hits
            time.sleep(0.15)
            continue

        filtered = filter_events(events, args.days, states)
        if args.raw:
            print(json.dumps({"band": band, "events": filtered}, indent=2))
        elif not filtered:
            print(f"{band}: (no matching shows)")
        else:
            any_hits = True
            print(f"{band}: {len(filtered)} show(s)")
            for event in filtered:
                print(f"  - {format_event(event)}")
        time.sleep(0.15)

    if not any_hits and not args.raw:
        print("No matching shows.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
