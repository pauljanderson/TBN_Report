#!/usr/bin/env python3
"""Build/update a Spotify playlist of artists with upcoming nearby shows.

Artist sources (union):
  - followed artists
  - artists with >= N liked songs (default 4)
  - artists on "{year} light|medium|heavy" playlists

Shows: StungEvents search, filtered by US state codes and upcoming days.
Songs (path 1): up to 10 tracks per artist — liked songs first, then Spotify
search. (/artists/{id}/top-tracks returns 403 on Dev Mode apps.)
Playlist: "upcoming shows" — created up front; each match is added as soon as
it's found (so long rate-limited runs still fill the playlist). Artists drop
off when re-checked with no local dates, or when stored dates are all past.

State file tracks artists, show dates, and track URIs for later setlist.fm work.

Examples:
  python tools/sync_spotify_upcoming_shows.py --states MA,RI --days 120 --dry-run
  python tools/sync_spotify_upcoming_shows.py --states MA,RI --days 120

  # Fill playlist from StungEvents results already on disk (no new Stung calls):
  python tools/sync_spotify_upcoming_shows.py --states MA,RI --days 120 --cache-only

  # Later, continue fetching only uncached artists (cached names are skipped):
  python tools/sync_spotify_upcoming_shows.py --states MA,RI --days 120

StungEvents free tier is ~1000 requests/day. Results are cached under
drive/spotify_upcoming_shows/stung_cache.json. Re-runs reuse that cache.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from spotify_json_cache import DEFAULT_LIBRARY_CACHE_HOURS, library_cache  # noqa: E402
from sync_spotify_year_playlists import (  # noqa: E402
    DEFAULT_CACHE_PATH,
    DEFAULT_ENV_PATH,
    REPO_ROOT,
    build_client,
    chunked,
    find_or_create_playlist,
    load_env_file,
    playlist_names,
)

DEFAULT_STATE_PATH = REPO_ROOT / "drive" / "spotify_upcoming_shows" / "state.json"
DEFAULT_STUNG_CACHE_PATH = REPO_ROOT / "drive" / "spotify_upcoming_shows" / "stung_cache.json"
PLAYLIST_NAME = "upcoming shows"
STUNG = "https://api.stungevents.com"
TRACKS_PER_ARTIST = 10
# Unauthenticated StungEvents cap is 1,000/day; leave headroom for retries.
DEFAULT_STUNG_DAILY_BUDGET = 900
DEFAULT_STUNG_DELAY_SEC = 0.75
DEFAULT_STUNG_CACHE_HOURS = 24


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


def fetch_followed_artists(
    sp,
    *,
    cache=None,
    sleep_s: float = 0.2,
    force_refresh: bool = False,
) -> dict[str, Artist]:
    """Followed artists, cached on disk when a JsonCache is provided."""
    if cache is not None and not force_refresh:
        cached = cache.get("followed_artists")
        if isinstance(cached, list):
            print(f"  cache hit: followed artists ({len(cached)})")
            bucket: dict[str, Artist] = {}
            for row in cached:
                artist_id = row.get("artist_id")
                name = row.get("name")
                if artist_id and name:
                    bucket[artist_id] = Artist(
                        artist_id=artist_id,
                        name=name,
                        sources=set(row.get("sources") or ["followed"]),
                    )
            return bucket

    bucket = {}
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
        time.sleep(sleep_s)

    if cache is not None:
        cache.set(
            "followed_artists",
            [
                {
                    "artist_id": artist.artist_id,
                    "name": artist.name,
                    "sources": sorted(artist.sources),
                }
                for artist in bucket.values()
            ],
        )
        print(f"  cached followed artists ({len(bucket)}) → {cache.path}")
    return bucket


def fetch_liked_artists(
    sp,
    min_liked: int,
    *,
    cache=None,
    sleep_s: float = 0.2,
    force_refresh: bool = False,
) -> tuple[dict[str, Artist], dict[str, list[str]]]:
    """Return (artists with >= min_liked primary credits, liked track URIs by artist id).

    The full Liked Songs scan is cached; min_liked filtering is applied in memory.
    """
    scan = None
    if cache is not None and not force_refresh:
        cached = cache.get("liked_library_scan")
        if isinstance(cached, dict):
            scan = cached
            print(
                f"  cache hit: liked library scan "
                f"(primary_artists={len(cached.get('primary_meta') or {})}, "
                f"liked_tracks={len(cached.get('liked_track_ids') or [])})"
            )

    if scan is None:
        counts: dict[str, set[str]] = {}
        meta: dict[str, dict] = {}
        liked_uris: dict[str, list[str]] = {}
        liked_track_ids: list[str] = []
        seen_uri: dict[str, set[str]] = {}
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
                track_uri = track.get("uri")
                artists = track.get("artists") or []
                if not track_id or not artists:
                    continue
                liked_track_ids.append(track_id)
                primary = artists[0]
                artist_id = primary.get("id")
                if artist_id:
                    counts.setdefault(artist_id, set()).add(track_id)
                    meta[artist_id] = {"id": artist_id, "name": primary.get("name") or ""}
                if track_uri:
                    for artist in artists:
                        aid = artist.get("id")
                        if not aid:
                            continue
                        already = seen_uri.setdefault(aid, set())
                        if track_uri in already:
                            continue
                        already.add(track_uri)
                        liked_uris.setdefault(aid, []).append(track_uri)
            offset += len(items)
            if page.get("next") is None:
                break
            time.sleep(sleep_s)

        scan = {
            "primary_counts": {aid: len(ids) for aid, ids in counts.items()},
            "primary_meta": meta,
            "liked_uris": liked_uris,
            "liked_track_ids": liked_track_ids,
        }
        if cache is not None:
            cache.set("liked_library_scan", scan)
            print(f"  cached liked library scan → {cache.path}")

    primary_counts = scan.get("primary_counts") or {}
    primary_meta = scan.get("primary_meta") or {}
    liked_uris = {aid: list(uris) for aid, uris in (scan.get("liked_uris") or {}).items()}

    bucket: dict[str, Artist] = {}
    for artist_id, count in primary_counts.items():
        if int(count) < min_liked:
            continue
        meta_row = primary_meta.get(artist_id) or {"id": artist_id, "name": ""}
        add_artist(bucket, meta_row, f"liked>={min_liked}")
    return bucket, liked_uris


def liked_track_ids_from_cache(cache) -> set[str] | None:
    """Return liked track IDs from library cache if present/fresh."""
    if cache is None:
        return None
    scan = cache.get("liked_library_scan")
    if not isinstance(scan, dict):
        return None
    ids = scan.get("liked_track_ids")
    if not isinstance(ids, list):
        return None
    return set(ids)


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


class StungRateLimitError(RuntimeError):
    """Raised when the daily StungEvents request budget is exhausted."""


class StungClient:
    """StungEvents search with disk cache, pacing, and 429 backoff."""

    def __init__(
        self,
        *,
        cache_path: Path,
        cache_hours: float,
        delay_sec: float,
        daily_budget: int,
        api_key: str | None = None,
        cache_only: bool = False,
        ignore_ttl: bool = False,
    ) -> None:
        self.cache_path = cache_path
        self.cache_hours = cache_hours
        self.delay_sec = delay_sec
        self.daily_budget = daily_budget
        self.api_key = (api_key or "").strip() or None
        self.cache_only = cache_only
        self.ignore_ttl = ignore_ttl
        self.cache = self._load_cache()
        self.network_calls = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self._last_call = 0.0
        today = datetime.now(timezone.utc).date().isoformat()
        usage = self.cache.setdefault("_meta", {})
        if usage.get("budget_date") != today:
            usage["budget_date"] = today
            usage["budget_used"] = 0
        self._budget_used = int(usage.get("budget_used") or 0)

    def cached_artist_count(self) -> int:
        return sum(1 for key, row in self.cache.items() if key != "_meta" and isinstance(row, dict))

    def _load_cache(self) -> dict:
        if not self.cache_path.is_file():
            return {"_meta": {}}
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"_meta": {}}
        if not isinstance(data, dict):
            return {"_meta": {}}
        data.setdefault("_meta", {})
        return data

    def save_cache(self) -> None:
        self.cache.setdefault("_meta", {})
        self.cache["_meta"]["budget_date"] = datetime.now(timezone.utc).date().isoformat()
        self.cache["_meta"]["budget_used"] = self._budget_used
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self.cache) + "\n", encoding="utf-8")

    def _cache_key(self, name: str) -> str:
        return name.strip().casefold()

    def _get_cached_events(self, name: str) -> list[dict] | None:
        row = self.cache.get(self._cache_key(name))
        if not isinstance(row, dict):
            return None
        fetched = parse_start(row.get("fetched_at"))
        if fetched is None:
            return None
        if not self.ignore_ttl:
            age = datetime.now(timezone.utc) - fetched
            if age > timedelta(hours=self.cache_hours):
                return None
        events = row.get("events")
        return list(events) if isinstance(events, list) else []

    def has_cache_entry(self, name: str) -> bool:
        return self._get_cached_events(name) is not None

    def _put_cache(self, name: str, events: list[dict]) -> None:
        self.cache[self._cache_key(name)] = {
            "name": name,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "events": events,
        }

    def _throttle(self) -> None:
        if self.delay_sec <= 0:
            return
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.delay_sec:
            time.sleep(self.delay_sec - elapsed)

    def fetch_events(self, name: str) -> list[dict] | None:
        """Return events list, or None if cache-only and this artist was never cached."""
        cached = self._get_cached_events(name)
        if cached is not None:
            self.cache_hits += 1
            return cached

        if self.cache_only:
            self.cache_misses += 1
            return None

        if self._budget_used >= self.daily_budget:
            raise StungRateLimitError(
                f"StungEvents daily budget exhausted ({self._budget_used}/{self.daily_budget}). "
                "Re-run tomorrow (cache will reuse today's results) or raise --stung-daily-budget / get an API key."
            )

        url = f"{STUNG}/search?q={urllib.parse.quote(name)}"
        headers = {"Accept": "application/json", "User-Agent": "tbn-upcoming-shows/1.1"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        attempts = 0
        while True:
            attempts += 1
            self._throttle()
            req = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.load(resp)
                self._last_call = time.monotonic()
                self.network_calls += 1
                self._budget_used += 1
                events = list(data.get("events") or [])
                self._put_cache(name, events)
                # Save after every successful call so Ctrl+C / pauses keep progress.
                self.save_cache()
                return events
            except urllib.error.HTTPError as exc:
                self._last_call = time.monotonic()
                if exc.code == 429 and attempts <= 6:
                    retry_after = exc.headers.get("Retry-After") if exc.headers else None
                    try:
                        wait = float(retry_after) if retry_after else min(60.0, 5.0 * attempts)
                    except ValueError:
                        wait = min(60.0, 5.0 * attempts)
                    print(f"  … StungEvents 429; sleeping {wait:.0f}s then retrying ({name})")
                    time.sleep(wait)
                    continue
                raise


def shows_from_events(events: list[dict], days: int, states: set[str]) -> list[Show]:
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)
    shows: list[Show] = []
    seen: set[tuple[str, str, str]] = set()
    for event in events:
        start = parse_start(event.get("start_utc"))
        if start is None or start < now or start > end:
            continue
        state = event_state(event)
        if states and state not in states:
            continue
        title = event.get("title") or ""
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


def artist_track_uris(
    sp,
    artist_id: str,
    artist_name: str,
    market: str,
    limit: int,
    liked_uris_by_artist: dict[str, list[str]],
) -> list[str]:
    """Build up to `limit` tracks without /artists/{id}/top-tracks (403 on Dev Mode).

    Prefer the user's liked songs for that artist, then fill via Spotify search.
    """
    uris: list[str] = []
    seen: set[str] = set()
    for uri in liked_uris_by_artist.get(artist_id, []):
        if uri in seen:
            continue
        seen.add(uri)
        uris.append(uri)
        if len(uris) >= limit:
            return uris

    try:
        page = sp.search(
            q=f'artist:"{artist_name}"',
            type="track",
            limit=min(10, max(limit, 1)),
            market=market,
        )
        items = ((page.get("tracks") or {}).get("items")) or []
        for track in items:
            uri = track.get("uri") if track else None
            if not uri or uri in seen:
                continue
            credited = {a.get("id") for a in (track.get("artists") or [])}
            if artist_id not in credited:
                continue
            seen.add(uri)
            uris.append(uri)
            if len(uris) >= limit:
                break
    except Exception:
        pass
    return uris[:limit]


def load_state(path: Path) -> dict:
    if not path.is_file():
        return {"artists": {}, "playlist_id": None, "playlist_name": PLAYLIST_NAME}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def artist_state_record(artist: Artist, shows: list[Show], uris: list[str]) -> dict:
    return {
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


def shows_all_past(shows: list[dict]) -> bool:
    if not shows:
        return True
    now = datetime.now(timezone.utc)
    for show in shows:
        start = parse_start(show.get("start_utc"))
        if start is not None and start >= now:
            return False
    return True


def uris_used_by_other_artists(state: dict, artist_id: str) -> set[str]:
    used: set[str] = set()
    for other_id, row in (state.get("artists") or {}).items():
        if other_id == artist_id:
            continue
        for uri in row.get("track_uris") or []:
            used.add(uri)
    return used


def playlist_add_uris(sp, playlist_id: str, uris: list[str]) -> None:
    for batch in chunked(uris, 100):
        sp.playlist_add_items(playlist_id, batch)
        time.sleep(0.05)


def playlist_remove_uris(sp, playlist_id: str, uris: list[str]) -> None:
    if not uris:
        return
    for batch in chunked(uris, 100):
        sp.playlist_remove_all_occurrences_of_items(playlist_id, batch)
        time.sleep(0.05)


def ensure_playlist(sp, state: dict) -> str:
    playlist_id = state.get("playlist_id")
    if playlist_id:
        try:
            sp.playlist(playlist_id, fields="id,name")
            return playlist_id
        except Exception:
            pass
    playlist_id = find_or_create_playlist(sp, PLAYLIST_NAME, dry_run=False)
    assert playlist_id
    return playlist_id


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
    stung_cache_path: Path,
    stung_delay_sec: float,
    stung_cache_hours: float,
    stung_daily_budget: int,
    stung_api_key: str | None,
    cache_only: bool,
) -> int:
    sp = build_client(cache_path)
    me = sp.current_user()
    print(f"Authenticated as {me.get('display_name') or me.get('id')}")

    state = load_state(state_path)
    state.setdefault("artists", {})
    state["playlist_name"] = PLAYLIST_NAME
    state["states"] = sorted(states)
    state["days"] = days
    state["year"] = year
    state["song_source"] = "liked_plus_search"

    playlist_id: str | None = None
    if not dry_run:
        playlist_id = ensure_playlist(sp, state)
        state["playlist_id"] = playlist_id
        print(f"Playlist ready: {PLAYLIST_NAME!r} ({playlist_id})")
        # Drop artists whose stored show dates are all in the past.
        expired = [
            aid
            for aid, row in list((state.get("artists") or {}).items())
            if shows_all_past(row.get("shows") or [])
        ]
        for aid in expired:
            row = state["artists"].pop(aid)
            removable = [
                uri
                for uri in (row.get("track_uris") or [])
                if uri not in uris_used_by_other_artists(state, aid)
            ]
            if removable:
                playlist_remove_uris(sp, playlist_id, removable)
            print(f"  removed expired: {row.get('name') or aid}")
        if expired:
            save_state(state_path, state)

    print("Collecting artists (followed / liked / year playlists) …")
    lib_cache = library_cache(ttl_hours=DEFAULT_LIBRARY_CACHE_HOURS)
    print(f"Library cache: {lib_cache.path} (ttl {DEFAULT_LIBRARY_CACHE_HOURS:g}h)")
    followed = fetch_followed_artists(sp, cache=lib_cache, sleep_s=0.2)
    liked, liked_uris_by_artist = fetch_liked_artists(sp, min_liked, cache=lib_cache, sleep_s=0.2)
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
    if len(artists) > stung_daily_budget:
        print(
            f"Note: {len(artists)} artists > StungEvents daily budget {stung_daily_budget}. "
            "Cache + re-runs will cover the rest; or register for a StungEvents API key (10k/day)."
        )
    print(f"Searching StungEvents in {sorted(states)} for next {days} day(s) …")
    print(
        f"StungEvents pacing: {stung_delay_sec:.2f}s between calls, "
        f"budget {stung_daily_budget}/day, cache {stung_cache_hours:g}h."
    )
    print("Song source: liked tracks first, then Spotify search (top-tracks API is blocked).")
    if cache_only:
        print("Cache-only mode — no new StungEvents HTTP calls; fill playlist from disk cache.")
    elif dry_run:
        print("Dry run — matches print only; playlist/state not updated live.")
    else:
        print("Live mode — adding each match to the playlist as soon as it's found.")

    stung = StungClient(
        cache_path=stung_cache_path,
        cache_hours=stung_cache_hours,
        delay_sec=stung_delay_sec,
        daily_budget=stung_daily_budget,
        api_key=stung_api_key,
        cache_only=cache_only,
        # In cache-only rebuilds, use whatever we already fetched even if > TTL.
        ignore_ttl=cache_only,
    )
    print(f"StungEvents disk cache: {stung_cache_path} ({stung.cached_artist_count()} artist entries)")

    matched_this_run = 0
    removed_this_run = 0
    skipped_uncached = 0
    budget_hit = False
    try:
        for index, artist in enumerate(sorted(artists.values(), key=lambda a: a.name.casefold()), start=1):
            try:
                events = stung.fetch_events(artist.name)
                if events is None:
                    # cache-only miss: do not treat as "no shows" and do not remove.
                    skipped_uncached += 1
                    continue
                shows = shows_from_events(events, days, states)
            except StungRateLimitError as exc:
                print(f"\n{exc}")
                budget_hit = True
                break
            except Exception as exc:  # noqa: BLE001
                print(f"  ! {artist.name}: StungEvents error: {exc}")
                continue

            if not shows:
                # Confirmed no upcoming local shows: remove if we had them before.
                # (Only when we actually had event data — never on cache-only miss.)
                if artist.artist_id in (state.get("artists") or {}):
                    row = state["artists"].pop(artist.artist_id)
                    removable = [
                        uri
                        for uri in (row.get("track_uris") or [])
                        if uri not in uris_used_by_other_artists(state, artist.artist_id)
                    ]
                    if not dry_run and playlist_id and removable:
                        playlist_remove_uris(sp, playlist_id, removable)
                    removed_this_run += 1
                    print(f"  removed (no upcoming local shows): {artist.name}")
                    if not dry_run:
                        state["updated_at"] = datetime.now(timezone.utc).isoformat()
                        save_state(state_path, state)
                elif index % 50 == 0:
                    print(
                        f"  … progress {index}/{len(artists)} "
                        f"(network={stung.network_calls}, cache_hits={stung.cache_hits})"
                    )
                continue

            uris = artist_track_uris(
                sp,
                artist.artist_id,
                artist.name,
                market,
                TRACKS_PER_ARTIST,
                liked_uris_by_artist,
            )
            prev = (state.get("artists") or {}).get(artist.artist_id) or {}
            prev_uris = list(prev.get("track_uris") or [])
            soonest = shows[0]
            place = f"{soonest.city}, {soonest.state}" if soonest.state else soonest.city
            print(
                f"  {artist.name}: {len(shows)} show(s); soonest {soonest.start_utc} @ {place} "
                f"({len(uris)} tracks) [{', '.join(sorted(artist.sources))}]"
            )

            if dry_run:
                matched_this_run += 1
                continue

            assert playlist_id
            if uris != prev_uris:
                obsolete = [
                    uri
                    for uri in prev_uris
                    if uri not in uris and uri not in uris_used_by_other_artists(state, artist.artist_id)
                ]
                if obsolete:
                    playlist_remove_uris(sp, playlist_id, obsolete)
                to_add = [uri for uri in uris if uri not in prev_uris]
                if to_add:
                    playlist_add_uris(sp, playlist_id, to_add)
                    print(f"    → added {len(to_add)} track(s) to {PLAYLIST_NAME!r}")
                elif obsolete:
                    print(f"    → refreshed tracks on {PLAYLIST_NAME!r}")
                else:
                    print("    → show dates refreshed")
            else:
                print("    → already on playlist; show dates refreshed")

            state.setdefault("artists", {})[artist.artist_id] = artist_state_record(artist, shows, uris)
            state["updated_at"] = datetime.now(timezone.utc).isoformat()
            save_state(state_path, state)
            matched_this_run += 1
    except KeyboardInterrupt:
        print("\nInterrupted — saving StungEvents cache/progress …")
        stung.save_cache()
        if not dry_run:
            state["updated_at"] = datetime.now(timezone.utc).isoformat()
            save_state(state_path, state)
        raise

    stung.save_cache()
    print(
        f"\nStungEvents calls this run: network={stung.network_calls}, "
        f"cache_hits={stung.cache_hits}, cache_misses={stung.cache_misses}, "
        f"budget_used_today={stung._budget_used}/{stung.daily_budget}"
    )
    print(
        f"Matched/added this run: {matched_this_run}; removed this run: {removed_this_run}; "
        f"skipped (uncached): {skipped_uncached}; "
        f"artists currently tracked: {len(state.get('artists') or {})}"
    )
    if budget_hit:
        print("Partial run OK — playlist already has whatever was found; re-run to continue.")
    if cache_only:
        print(
            "Cache-only done. To fetch remaining uncached artists later:\n"
            "  python tools/sync_spotify_upcoming_shows.py --states MA,RI --days 120"
        )
    if dry_run:
        print("Dry run complete — no playlist changes.")
    else:
        print(f"Live playlist: {PLAYLIST_NAME!r} ({state.get('playlist_id')})")
        print(f"State file: {state_path}")
        print(f"Stung cache: {stung_cache_path}")
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
    parser.add_argument(
        "--stung-cache-file",
        type=Path,
        default=DEFAULT_STUNG_CACHE_PATH,
        help="Disk cache for StungEvents search JSON (avoids re-querying same artists)",
    )
    parser.add_argument(
        "--stung-delay",
        type=float,
        default=DEFAULT_STUNG_DELAY_SEC,
        help=f"Seconds between StungEvents HTTP calls (default {DEFAULT_STUNG_DELAY_SEC})",
    )
    parser.add_argument(
        "--stung-cache-hours",
        type=float,
        default=DEFAULT_STUNG_CACHE_HOURS,
        help=f"Reuse cached StungEvents results for this many hours (default {DEFAULT_STUNG_CACHE_HOURS})",
    )
    parser.add_argument(
        "--stung-daily-budget",
        type=int,
        default=DEFAULT_STUNG_DAILY_BUDGET,
        help=f"Max StungEvents HTTP calls per UTC day (default {DEFAULT_STUNG_DAILY_BUDGET}; free tier is 1000)",
    )
    parser.add_argument(
        "--stung-api-key",
        default="",
        help="Optional StungEvents publisher API key (or set STUNGEVENTS_API_KEY in env)",
    )
    parser.add_argument(
        "--cache-only",
        action="store_true",
        help=(
            "One-off/rebuild: use only disk-cached StungEvents results (no new HTTP calls). "
            "Fills the playlist from artists already fetched; skips uncached artists."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_env_file(args.env_file)
    load_env_file(REPO_ROOT / ".env")
    states = {s.strip().upper() for s in args.states.split(",") if s.strip()}
    if not states:
        raise SystemExit("--states is required (e.g. MA,RI)")
    api_key = args.stung_api_key or os.environ.get("STUNGEVENTS_API_KEY") or ""
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
            stung_cache_path=args.stung_cache_file,
            stung_delay_sec=args.stung_delay,
            stung_cache_hours=args.stung_cache_hours,
            stung_daily_budget=args.stung_daily_budget,
            stung_api_key=api_key or None,
            cache_only=args.cache_only,
        )
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
