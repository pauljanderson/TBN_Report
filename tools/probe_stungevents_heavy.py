#!/usr/bin/env python3
"""Quick probe: artists on Spotify '2026 heavy' → StungEvents search.

Usage (from repo root, with secrets/spotify.env already set up):
  python tools/probe_stungevents_heavy.py
  python tools/probe_stungevents_heavy.py --city "New York" --days 60

I cannot read your Spotify account from the cloud agent; run this locally.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sync_spotify_year_playlists import (  # noqa: E402
    DEFAULT_CACHE_PATH,
    DEFAULT_ENV_PATH,
    REPO_ROOT,
    build_client,
    load_env_file,
    playlist_names,
)

STUNG = "https://api.stungevents.com"
TRIBUTE_RE = re.compile(
    r"\b(tribute|cover|karaoke|party|night|candlelight|impersonat|sing[- ]along)\b",
    re.I,
)


def http_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "tbn-stung-probe/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        import json

        return json.load(resp)


def find_playlist_id(sp, name: str) -> str | None:
    offset = 0
    while True:
        page = sp.current_user_playlists(limit=50, offset=offset)
        items = page.get("items") or []
        for playlist in items:
            if playlist and playlist.get("name") == name:
                return playlist.get("id")
        offset += len(items)
        if page.get("next") is None:
            return None


def playlist_entry_track(entry: dict) -> dict:
    track = entry.get("track") or entry.get("item") or {}
    if track.get("type") and track.get("type") != "track":
        return {}
    return track


def artists_from_playlist(sp, playlist_name: str) -> list[str]:
    playlist_id = find_playlist_id(sp, playlist_name)
    if not playlist_id:
        raise SystemExit(f"Playlist not found: {playlist_name!r}")
    artists: dict[str, str] = {}
    offset = 0
    while True:
        page = sp.playlist_items(playlist_id, limit=50, offset=offset, additional_types=("track",))
        items = page.get("items") or []
        if not items:
            break
        for entry in items:
            track = playlist_entry_track(entry)
            album = (track.get("album") or {}) if track else {}
            for artist in album.get("artists") or track.get("artists") or []:
                name = (artist.get("name") or "").strip()
                if name:
                    artists.setdefault(name.casefold(), name)
        offset += len(items)
        if page.get("next") is None:
            break
        time.sleep(0.05)
    return sorted(artists.values(), key=str.casefold)


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


def looks_like_real_show(artist: str, event: dict) -> bool:
    title = event.get("title") or ""
    if TRIBUTE_RE.search(title):
        return False
    # Prefer titles that start with the artist name (common for headliners).
    head = title.split("—")[0].split("-")[0].strip()
    if artist.casefold() in head.casefold():
        return True
    # Also keep if category is concerts and artist is a clear token in title.
    tokens = re.findall(r"[a-z0-9]+", artist.casefold())
    title_cf = title.casefold()
    return bool(tokens) and all(tok in title_cf for tok in tokens if len(tok) > 2)


def search_artist_events(artist: str, days: int, city: str | None) -> list[dict]:
    q = urllib.parse.quote(artist)
    data = http_json(f"{STUNG}/search?q={q}")
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)
    city_cf = city.casefold() if city else None
    hits: list[dict] = []
    for event in data.get("events") or []:
        start = parse_start(event.get("start_utc"))
        if start is None or start < now or start > end:
            continue
        if city_cf:
            event_city = (event.get("city") or "").casefold()
            if not event_city.startswith(city_cf) and city_cf not in event_city:
                continue
        if not looks_like_real_show(artist, event):
            continue
        hits.append(event)
    hits.sort(key=lambda e: e.get("start_utc") or "")
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=datetime.now().year)
    parser.add_argument("--days", type=int, default=60, help="Upcoming window (default 60)")
    parser.add_argument("--city", type=str, default="", help='Optional city filter, e.g. "Boston"')
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_PATH)
    parser.add_argument("--cache-path", type=Path, default=DEFAULT_CACHE_PATH)
    parser.add_argument(
        "--include-noisy",
        action="store_true",
        help="Include tribute/cover-like titles (default: filter them out)",
    )
    args = parser.parse_args()

    load_env_file(args.env_file)
    load_env_file(REPO_ROOT / ".env")
    sp = build_client(args.cache_path)
    playlist_name = playlist_names(args.year, "spaced")["heavy"]
    print(f"Reading Spotify playlist {playlist_name!r} …")
    artists = artists_from_playlist(sp, playlist_name)
    print(f"Found {len(artists)} artist(s).\n")

    city = args.city.strip() or None
    any_hits = False
    for artist in artists:
        try:
            if args.include_noisy:
                # bypass filter by temporarily disabling tribute check via raw search
                q = urllib.parse.quote(artist)
                data = http_json(f"{STUNG}/search?q={q}")
                now = datetime.now(timezone.utc)
                end = now + timedelta(days=args.days)
                hits = []
                for event in data.get("events") or []:
                    start = parse_start(event.get("start_utc"))
                    if start is None or start < now or start > end:
                        continue
                    if city:
                        event_city = (event.get("city") or "").casefold()
                        if not event_city.startswith(city.casefold()) and city.casefold() not in event_city:
                            continue
                    hits.append(event)
                hits.sort(key=lambda e: e.get("start_utc") or "")
            else:
                hits = search_artist_events(artist, args.days, city)
        except Exception as exc:  # noqa: BLE001
            print(f"{artist}: StungEvents error: {exc}")
            continue
        if not hits:
            print(f"{artist}: (no matching shows in next {args.days}d)")
        else:
            any_hits = True
            print(f"{artist}: {len(hits)} show(s)")
            for event in hits[:8]:
                print(
                    f"  - {event.get('start_utc')} | {event.get('city')} | "
                    f"{event.get('venue_name')} | {event.get('title')}"
                )
            if len(hits) > 8:
                print(f"  … +{len(hits) - 8} more")
        time.sleep(0.15)

    if not any_hits:
        print(
            "\nNo shows matched. Try --city with your city, --include-noisy, "
            "or note StungEvents coverage may be thin for your artists."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
