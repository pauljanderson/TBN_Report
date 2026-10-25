#!/usr/bin/env python3
"""Build/update a Spotify playlist of artists with upcoming nearby shows.

Artist sources (union):
  - followed artists
  - artists with >= N liked songs (default 4)
  - artists on "{year} light|medium|heavy" playlists

Shows: StungEvents search, filtered by US state codes and upcoming days.
Songs (path 1): each artist's Spotify top tracks (fallback: search), up to 10.
Playlist: "upcoming shows" — replaced each run; artists drop off when all
their tracked show dates have passed.

State file tracks artists, show dates, and track URIs for later setlist.fm work.

Examples:
  python tools/sync_spotify_upcoming_shows.py --states MA,RI --days 60 --dry-run
  python tools/sync_spotify_upcoming_shows.py --states MA,RI --days 60
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sync_spotify_year_playlists import (  # noqa: E402
    DEFAULT_CACHE_PATH,
    DEFAULT_ENV_PATH,
    REPO_ROOT,
    build_client,
    chunked,
    find_or_create_playlist,
    load_env_file,
    playlist_names,
    replace_playlist_tracks,
)

DEFAULT_STATE_PATH = REPO_ROOT / "drive" / "spotify_upcoming_shows" / "state.json"
PLAYLIST_NAME = "upcoming shows"
STUNG = "https://api.stungevents.com"
TRACKS_PER_ARTIST = 10


@dataclass
class Artist:
    artist_id: str
    name: str
    sources: set[str] = field(default_factory=set)


@dataclass
class Show:
    start_utc: str
    city: str
    state: str
    country: str
    venue: str
    title: str


def http_json(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "tbn-upcoming-shows/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


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


def playlist_entry_track(entry: dict) -> dict:
    track = entry.get("track") or entry.get("item") or {}
    if track.get("type") and track.get("type") != "track":
        return {}
    return track


def add_artist(bucket: dict[str, Artist], artist_obj: dict | None, source: str) -> None:
    if not artist_obj:
        return
    artist_id = artist_obj.get("id")
    name = (artist_obj.get("name") or "").strip()
    if not artist_id or not name:
        return
    row = bucket.get(artist_id)
    if row is None:
        bucket[artist_id] = Artist(artist_id=artist_id, name=name, sources={source})
    else:
        row.sources.add(source)


def fetch_followed_artists(sp) -> dict[str, Artist]:
    bucket: dict[str, Artist] = {}
    after = None
    while True:
        page = sp.current_user_followed_artists(limit=50, after=after)
        artists = ((page or {}).get("artists") or {})
        items = artists.get("items") or []
        for artist in items:
            add_artist(bucket, artist, "followed")
        cursors = artists.get("cursors") or {}
        after = cursors.get("after")
        if not after or not items:
            break
        time.sleep(0.05)
    return bucket


def fetch_liked_artists(sp, min_liked: int) -> dict[str, Artist]:
    counts: dict[str, set[str]] = {}
    meta: dict[str, dict] = {}
    offset = 0
    while True:
        page = sp.current_user_saved_tracks(limit=50, offset=offset)
        items = page.get("items") or []
        if not items:
            break
        for entry in items:
            track = entry.get("track") or {}
            if not track or track.get("is_local"):
                continue
            track_id = track.get("id")
            artists = track.get("artists") or []
            if not track_id or not artists:
                continue
            # Count against primary (first-listed) artist.
            primary = artists[0]
            artist_id = primary.get("id")
            if not artist_id:
                continue
            counts.setdefault(artist_id, set()).add(track_id)
            meta[artist_id] = primary
        offset += len(items)
        if page.get("next") is None:
            break
        time.sleep(0.05)
    bucket: dict[str, Artist] = {}
    for artist_id, track_ids in counts.items():
        if len(track_ids) >= min_liked:
            add_artist(bucket, meta[artist_id], f"liked>={min_liked}")
    return bucket


def fetch_playlist_artists(sp, playlist_name: str) -> dict[str, Artist]:
    bucket: dict[str, Artist] = {}
    playlist_id = None
    offset = 0
    while True:
        page = sp.current_user_playlists(limit=50, offset=offset)
        items = page.get("items") or []
        for playlist in items:
            if playlist and playlist.get("name") == playlist_name:
                playlist_id = playlist.get("id")
                break
        if playlist_id or page.get("next") is None:
            break
        offset += len(items)
    if not playlist_id:
        return bucket

    offset = 0
    while True:
        page = sp.playlist_items(playlist_id, limit=50, offset=offset, additional_types=("track",))
        items = page.get("items") or []
        if not items:
            break
        for entry in items:
            track = playlist_entry_track(entry)
            if not track:
                continue
            for artist in track.get("artists") or []:
                add_artist(bucket, artist, f"playlist:{playlist_name}")
        offset += len(items)
        if page.get("next") is None:
            break
        time.sleep(0.05)
    return bucket


def merge_artists(*groups: dict[str, Artist]) -> dict[str, Artist]:
    out: dict[str, Artist] = {}
    for group in groups:
        for artist_id, artist in group.items():
            if artist_id not in out:
                out[artist_id] = Artist(artist_id=artist.artist_id, name=artist.name, sources=set(artist.sources))
            else:
                out[artist_id].sources |= artist.sources
                if artist.name:
                    out[artist_id].name = artist.name
    return out


def stung_shows_for_artist(name: str, days: int, states: set[str]) -> list[Show]:
    data = http_json(f"{STUNG}/search?q={urllib.parse.quote(name)}")
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)
    shows: list[Show] = []
    seen: set[tuple[str, str, str]] = set()
    for event in data.get("events") or []:
        start = parse_start(event.get("start_utc"))
        if start is None or start < now or start > end:
            continue
        state = event_state(event)
        if states and state not in states:
            continue
        title = event.get("title") or ""
        # Light noise filter: skip obvious tribute/cover nights.
        low = title.casefold()
        if any(tok in low for tok in ("tribute", "cover band", "karaoke", "candlelight")):
            continue
        key = (
            (event.get("start_utc") or "")[:10],
            (event.get("city") or "").casefold(),
            (event.get("venue_name") or "").casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        shows.append(
            Show(
                start_utc=event.get("start_utc") or "",
                city=event.get("city") or "",
                state=state,
                country=event.get("country") or "",
                venue=event.get("venue_name") or "",
                title=title,
            )
        )
    shows.sort(key=lambda s: s.start_utc)
    return shows


def artist_top_track_uris(sp, artist_id: str, artist_name: str, market: str, limit: int) -> list[str]:
    """Prefer artist top-tracks; fall back to track search if endpoint is unavailable."""
    try:
        page = sp.artist_top_tracks(artist_id, country=market)
        uris = [t["uri"] for t in (page.get("tracks") or []) if t and t.get("uri")]
        if uris:
            return uris[:limit]
    except Exception:
        pass

    # Fallback: search tracks by artist name.
    try:
        page = sp.search(q=f'artist:"{artist_name}"', type="track", limit=min(limit, 10), market=market)
        items = ((page.get("tracks") or {}).get("items")) or []
        uris: list[str] = []
        for track in items:
            if not track or not track.get("uri"):
                continue
            # Keep only if this artist is credited.
            credited = {a.get("id") for a in (track.get("artists") or [])}
            if artist_id in credited:
                uris.append(track["uri"])
            if len(uris) >= limit:
                break
        return uris
    except Exception:
        return []


def load_state(path: Path) -> dict:
    if not path.is_file():
        return {"artists": {}, "playlist_id": None, "playlist_name": PLAYLIST_NAME}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sync(
    *,
    year: int,
    states: set[str],
    days: int,
    min_liked: int,
    market: str,
    dry_run: bool,
    state_path: Path,
    cache_path: Path,
) -> int:
    sp = build_client(cache_path)
    me = sp.current_user()
    print(f"Authenticated as {me.get('display_name') or me.get('id')}")

    print("Collecting artists (followed / liked / year playlists) …")
    followed = fetch_followed_artists(sp)
    liked = fetch_liked_artists(sp, min_liked)
    names = playlist_names(year, "spaced")
    from_playlists: dict[str, Artist] = {}
    for tier in ("light", "medium", "heavy"):
        from_playlists.update(fetch_playlist_artists(sp, names[tier]))

    artists = merge_artists(followed, liked, from_playlists)
    print(
        f"Artist pool: {len(artists)} "
        f"(followed={len(followed)}, liked>={min_liked}={len(liked)}, "
        f"year-playlists={len(from_playlists)})"
    )
    print(f"Searching StungEvents in {sorted(states)} for next {days} day(s) …")

    upcoming: list[tuple[Artist, list[Show], list[str]]] = []
    for artist in sorted(artists.values(), key=lambda a: a.name.casefold()):
        try:
            shows = stung_shows_for_artist(artist.name, days, states)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {artist.name}: StungEvents error: {exc}")
            continue
        if not shows:
            continue
        uris = artist_top_track_uris(sp, artist.artist_id, artist.name, market, TRACKS_PER_ARTIST)
        upcoming.append((artist, shows, uris))
        soonest = shows[0]
        place = f"{soonest.city}, {soonest.state}" if soonest.state else soonest.city
        print(
            f"  {artist.name}: {len(shows)} show(s); soonest {soonest.start_utc} @ {place} "
            f"({len(uris)} tracks) [{', '.join(sorted(artist.sources))}]"
        )
        time.sleep(0.12)

    upcoming.sort(key=lambda row: row[1][0].start_utc if row[1] else "")

    track_uris: list[str] = []
    seen_uri: set[str] = set()
    for _artist, _shows, uris in upcoming:
        for uri in uris:
            if uri not in seen_uri:
                seen_uri.add(uri)
                track_uris.append(uri)

    print(
        f"\nMatched {len(upcoming)} artist(s) with nearby shows; "
        f"{len(track_uris)} unique track(s) for playlist {PLAYLIST_NAME!r}."
    )

    state = load_state(state_path)
    prev_ids = set(state.get("artists") or {})
    next_ids = {a.artist_id for a, _, _ in upcoming}
    removed = sorted(prev_ids - next_ids)
    if removed:
        print(f"Dropping {len(removed)} artist(s) with no remaining nearby dates.")

    new_state = {
        "playlist_name": PLAYLIST_NAME,
        "playlist_id": state.get("playlist_id"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "states": sorted(states),
        "days": days,
        "year": year,
        "song_source": "spotify_top_tracks",
        "artists": {
            artist.artist_id: {
                "name": artist.name,
                "sources": sorted(artist.sources),
                "shows": [
                    {
                        "start_utc": s.start_utc,
                        "city": s.city,
                        "state": s.state,
                        "country": s.country,
                        "venue": s.venue,
                        "title": s.title,
                    }
                    for s in shows
                ],
                "track_uris": uris,
                "setlistfm": None,  # reserved for path 2
            }
            for artist, shows, uris in upcoming
        },
    }

    if dry_run:
        print("Dry run — playlist not modified; state not written.")
        save_state(state_path.with_suffix(".dry-run.json"), new_state)
        print(f"Wrote dry-run state preview: {state_path.with_suffix('.dry-run.json')}")
        return 0

    playlist_id = state.get("playlist_id")
    if not playlist_id:
        playlist_id = find_or_create_playlist(sp, PLAYLIST_NAME, dry_run=False)
    else:
        # Ensure it still exists / recreate by name if missing.
        try:
            sp.playlist(playlist_id, fields="id,name")
        except Exception:
            playlist_id = find_or_create_playlist(sp, PLAYLIST_NAME, dry_run=False)

    assert playlist_id
    replace_playlist_tracks(sp, playlist_id, track_uris)
    new_state["playlist_id"] = playlist_id
    save_state(state_path, new_state)
    print(f"Updated playlist {PLAYLIST_NAME!r} ({playlist_id})")
    print(f"Wrote state {state_path}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, default=datetime.now().year)
    parser.add_argument(
        "--states",
        required=True,
        help='Comma-separated US state codes, e.g. "MA,RI"',
    )
    parser.add_argument("--days", type=int, default=60, help="Upcoming window in days (default 60)")
    parser.add_argument("--min-liked", type=int, default=4, help="Liked-song threshold for artist inclusion")
    parser.add_argument("--market", default="US", help="Market for top-tracks / search fallback (default US)")
    parser.add_argument("--dry-run", action="store_true", help="Print matches only; do not modify Spotify playlist")
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_PATH)
    parser.add_argument("--cache-path", type=Path, default=DEFAULT_CACHE_PATH)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_env_file(args.env_file)
    load_env_file(REPO_ROOT / ".env")
    states = {s.strip().upper() for s in args.states.split(",") if s.strip()}
    if not states:
        raise SystemExit("--states is required (e.g. MA,RI)")
    try:
        return sync(
            year=args.year,
            states=states,
            days=args.days,
            min_liked=args.min_liked,
            market=args.market,
            dry_run=args.dry_run,
            state_path=args.state_file,
            cache_path=args.cache_path,
        )
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
