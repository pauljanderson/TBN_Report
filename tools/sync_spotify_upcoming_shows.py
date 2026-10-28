#!/usr/bin/env python3
"""Build/update a Spotify playlist of artists with upcoming nearby shows.

Artist sources (union):
  - followed artists
  - artists with >= N liked songs (default 4)
  - artists on "{year} light|medium|heavy" playlists

Shows: StungEvents search, filtered by US state codes, upcoming days, and
artist name appearing in the event title (description-only hits are ignored).
Tribute / fusion / "experience" shows are kept for calendar/state, but only
real headliner matches get songs on the Spotify playlist.
Songs (path 1): up to 10 tracks per artist — liked songs first, then Spotify
search. (/artists/{id}/top-tracks returns 403 on Dev Mode apps.)
Playlist: "upcoming shows" — created up front; each headliner match is added
as soon as it's found. Artists drop off when re-checked with no local dates,
or when stored dates are all past.

State file tracks artists, show dates, and track URIs for later setlist.fm work.

Examples:
  python tools/sync_spotify_upcoming_shows.py --states MA,RI --days 120 --dry-run
  python tools/sync_spotify_upcoming_shows.py --states MA,RI --days 120

  # Continue from cached favorites + keep calling StungEvents / updating Spotify:
  python tools/sync_spotify_upcoming_shows.py --states MA,RI --days 120 --continue-cached

  # Force-push everything already in state.json onto the Spotify playlist
  # (no StungEvents calls; requires Spotify API access):
  python tools/sync_spotify_upcoming_shows.py --states MA,RI --days 120 --apply-playlist

  # If Spotify is rate-limited (429), --continue-cached still runs StungEvents and saves
  # matches to state; use --apply-playlist once Spotify recovers.

  # Fill playlist from StungEvents results already on disk (no new Stung calls):
  python tools/sync_spotify_upcoming_shows.py --states MA,RI --days 120 --cache-only

StungEvents free tier is ~1000 requests/day. Results are cached under
drive/spotify_upcoming_shows/stung_cache.json. Favorite artists come from
drive/spotify_library_cache/library.json when using --continue-cached.
"""

from __future__ import annotations

import argparse
import json
import os
import re
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
    replace_playlist_tracks,
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
    playlist_eligible: bool = False
    kind: str = "headliner"  # headliner | tribute | related


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
    sp=None,
    *,
    cache=None,
    sleep_s: float = 0.2,
    force_refresh: bool = False,
    allow_stale: bool = False,
) -> dict[str, Artist]:
    """Followed artists, cached on disk when a JsonCache is provided."""
    if cache is not None and not force_refresh:
        cached = cache.get("followed_artists")
        stale = False
        if cached is None and allow_stale:
            cached = cache.get("followed_artists", allow_stale=True)
            stale = cached is not None
        if isinstance(cached, list):
            label = "stale cache hit" if stale else "cache hit"
            print(f"  {label}: followed artists ({len(cached)})")
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
        if allow_stale:
            raise SystemExit(
                "Library cache missing followed artists. "
                "Need a prior successful library scan in drive/spotify_library_cache/library.json."
            )

    if sp is None:
        raise SystemExit(
            "No followed-artists cache found and Spotify client unavailable. "
            "Run once with Spotify access to populate drive/spotify_library_cache/library.json."
        )

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
    sp=None,
    min_liked: int = 4,
    *,
    cache=None,
    sleep_s: float = 0.2,
    force_refresh: bool = False,
    allow_stale: bool = False,
) -> tuple[dict[str, Artist], dict[str, list[str]]]:
    """Return (artists with >= min_liked primary credits, liked track URIs by artist id).

    The full Liked Songs scan is cached; min_liked filtering is applied in memory.
    """
    scan = None
    if cache is not None and not force_refresh:
        cached = cache.get("liked_library_scan")
        stale = False
        if cached is None and allow_stale:
            cached = cache.get("liked_library_scan", allow_stale=True)
            stale = cached is not None
        if isinstance(cached, dict):
            scan = cached
            label = "stale cache hit" if stale else "cache hit"
            print(
                f"  {label}: liked library scan "
                f"(primary_artists={len(cached.get('primary_meta') or {})}, "
                f"liked_tracks={len(cached.get('liked_track_ids') or [])})"
            )
        elif allow_stale:
            raise SystemExit(
                "Library cache missing liked library scan. "
                "Need a prior successful library scan in drive/spotify_library_cache/library.json."
            )

    if scan is None:
        if sp is None:
            raise SystemExit(
                "No liked-library cache found and Spotify client unavailable. "
                "Run once with Spotify access to populate drive/spotify_library_cache/library.json."
            )
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


def liked_track_ids_from_cache(cache, *, allow_stale: bool = False) -> set[str] | None:
    """Return liked track IDs from library cache if present/fresh."""
    if cache is None:
        return None
    scan = cache.get("liked_library_scan", allow_stale=allow_stale)
    if not isinstance(scan, dict):
        return None
    ids = scan.get("liked_track_ids")
    if not isinstance(ids, list):
        return None
    return set(ids)


def prioritize_artists_for_stung(artists: dict[str, Artist], stung: "StungClient") -> list[Artist]:
    """Fetch StungEvents for never-cached artists first, then refresh/use cached ones."""
    missing: list[Artist] = []
    cached: list[Artist] = []
    for artist in sorted(artists.values(), key=lambda a: a.name.casefold()):
        if stung.has_any_cache(artist.name):
            cached.append(artist)
        else:
            missing.append(artist)
    return missing + cached


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

    def has_any_cache(self, name: str) -> bool:
        """True if we have any disk entry for this artist (even if TTL expired)."""
        row = self.cache.get(self._cache_key(name))
        return isinstance(row, dict) and "events" in row

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


# Shows with these hints stay on the calendar/state but never get playlist tracks.
PLAYLIST_BLOCK_HINTS = (
    "tribute",
    "cover band",
    "cover show",
    "karaoke",
    "candlelight",
    "fusion",
    "experience",
    "project",
    "celebration of",
    "symphony",
    "in the style of",
    "salute to",
    "plays the music of",
    "music of",
)


def _normalize_name(text: str) -> str:
    text = (text or "").casefold()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _strip_leading_the(text: str) -> str:
    return re.sub(r"^the\s+", "", text).strip()


def artist_phrase_pattern(artist_name: str) -> re.Pattern[str]:
    parts = re.findall(r"[a-z0-9]+", (artist_name or "").casefold())
    if not parts:
        return re.compile(r"(?!)")  # never matches
    body = r"[\s\-_/·]+".join(re.escape(p) for p in parts)
    return re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])", re.IGNORECASE)


def title_references_artist(title: str, artist_name: str) -> bool:
    """True when the artist phrase appears as whole words in the title."""
    if not (title or "").strip() or not (artist_name or "").strip():
        return False
    return artist_phrase_pattern(artist_name).search(title) is not None


def title_matches_artist(title: str, artist_name: str) -> bool:
    """Backward-compatible alias: calendar/track eligibility uses should_track_show."""
    return should_track_show(title, artist_name)


def headliner_segment(title: str) -> str:
    """Best-effort primary headliner from an event title."""
    text = (title or "").strip()
    text = re.sub(r"(?i)^(presents?|live\s*at)\s*:\s*", "", text).strip()
    for sep in (
        r"\s+w/\s+",
        r"\s+with\s+",
        r"\s+feat\.?\s+",
        r"\s+ft\.?\s+",
        r"\s+@\s+",
        r"\s+at\s+",
        r"\s+[—–\-]\s+",
        r"\s*:\s*",
    ):
        parts = re.split(sep, text, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) > 1 and parts[0].strip():
            text = parts[0].strip()
            break
    return text


def looks_like_tribute_or_related(title: str, artist_name: str) -> bool:
    """Tribute / fusion / experience / themed show related to the artist."""
    low = (title or "").casefold()
    if not low:
        return False
    if any(hint in low for hint in PLAYLIST_BLOCK_HINTS):
        return True
    if title_references_artist(title, artist_name) and re.search(
        r"\b(australian|ultimate|world'?s?\s+famous|famous|best)\b",
        low,
    ):
        return True
    return False


def is_real_headliner(title: str, artist_name: str) -> bool:
    """True when the title's headliner is the actual artist (playlist-safe)."""
    if not (title or "").strip() or not (artist_name or "").strip():
        return False
    low = title.casefold()
    if any(hint in low for hint in PLAYLIST_BLOCK_HINTS):
        return False
    head = _strip_leading_the(_normalize_name(headliner_segment(title)))
    art = _strip_leading_the(_normalize_name(artist_name))
    if not head or not art:
        return False
    if head == art:
        return True
    # "Artist Live", "Artist Tour 2026", "Artist Soft Opening", etc.
    return head.startswith(art + " ")


def should_track_show(title: str, artist_name: str) -> bool:
    """Keep for calendar/state: real headliner OR tribute/related mention.

    Drops false friends like query 'Pulp' vs title 'Slow Pulp'.
    """
    if is_real_headliner(title, artist_name):
        return True
    if title_references_artist(title, artist_name) and looks_like_tribute_or_related(
        title, artist_name
    ):
        return True
    return False


def classify_show(title: str, artist_name: str) -> tuple[bool, str] | None:
    """Return (playlist_eligible, kind) or None if the show should be ignored."""
    if is_real_headliner(title, artist_name):
        return True, "headliner"
    if title_references_artist(title, artist_name) and looks_like_tribute_or_related(
        title, artist_name
    ):
        return False, "tribute"
    return None


def shows_from_events(
    events: list[dict],
    days: int,
    states: set[str],
    *,
    artist_name: str,
) -> list[Show]:
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
        classified = classify_show(title, artist_name)
        if classified is None:
            continue
        playlist_eligible, kind = classified
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
                playlist_eligible=playlist_eligible,
                kind=kind,
            )
        )
    shows.sort(key=lambda s: s.start_utc)
    return shows


def show_row_playlist_eligible(show: dict, artist_name: str) -> bool:
    """Re-evaluate a stored show dict for playlist eligibility."""
    if "playlist_eligible" in show:
        return bool(show.get("playlist_eligible"))
    title = show.get("title") or ""
    classified = classify_show(title, artist_name)
    return bool(classified and classified[0])


def artist_has_playlist_eligible_show(row: dict) -> bool:
    name = (row.get("name") or "").strip()
    shows = row.get("shows") or []
    return any(show_row_playlist_eligible(show, name) for show in shows)


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
    When sp is None, return liked URIs only.
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

    if sp is None:
        return uris[:limit]

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


class PlaylistMirror:
    """Live + local URI index for the upcoming-shows playlist (prevents duplicate adds)."""

    def __init__(self, uris: list[str] | None = None) -> None:
        ordered: list[str] = []
        seen: set[str] = set()
        for uri in uris or []:
            if not uri or uri in seen:
                continue
            seen.add(uri)
            ordered.append(uri)
        self.ordered = ordered
        self.uris = seen

    def __contains__(self, uri: str) -> bool:
        return uri in self.uris

    def missing(self, uris: list[str]) -> list[str]:
        out: list[str] = []
        seen_batch: set[str] = set()
        for uri in uris:
            if not uri or uri in self.uris or uri in seen_batch:
                continue
            seen_batch.add(uri)
            out.append(uri)
        return out

    def note_added(self, uris: list[str]) -> None:
        for uri in uris:
            if not uri or uri in self.uris:
                continue
            self.uris.add(uri)
            self.ordered.append(uri)

    def note_removed(self, uris: list[str]) -> None:
        drop = {uri for uri in uris if uri}
        if not drop:
            return
        self.uris -= drop
        self.ordered = [uri for uri in self.ordered if uri not in drop]

    def save_to_state(self, state: dict) -> None:
        state["playlist_track_uris"] = list(self.ordered)
        state["playlist_track_uri_count"] = len(self.ordered)


def playlist_items_ordered(sp, playlist_id: str) -> list[str]:
    """Download playlist track URIs in order (includes duplicate occurrences)."""
    ordered: list[str] = []
    offset = 0
    while True:
        page = sp.playlist_items(
            playlist_id,
            fields="items(track(uri)),next",
            limit=100,
            offset=offset,
            additional_types=["track"],
        )
        items = page.get("items") or []
        for entry in items:
            track = playlist_entry_track(entry)
            uri = track.get("uri") if track else None
            if uri:
                ordered.append(uri)
        if not page.get("next"):
            break
        offset += len(items)
        if not items:
            break
        time.sleep(0.05)
    return ordered


def load_playlist_mirror(sp, playlist_id: str, state: dict | None = None) -> PlaylistMirror:
    """Fetch the live playlist into a mirror (preferred over stale state copy)."""
    ordered = playlist_items_ordered(sp, playlist_id)
    mirror = PlaylistMirror(ordered)
    if state is not None:
        mirror.save_to_state(state)
    print(f"  playlist mirror loaded: {len(ordered)} item(s), {len(mirror.uris)} unique URI(s)")
    return mirror


def playlist_add_missing(
    sp,
    playlist_id: str,
    uris: list[str],
    mirror: PlaylistMirror,
) -> list[str]:
    """Add only URIs not already on the playlist; update mirror."""
    missing = mirror.missing(uris)
    if not missing:
        return []
    playlist_add_uris(sp, playlist_id, missing)
    mirror.note_added(missing)
    return missing


def playlist_remove_tracked(
    sp,
    playlist_id: str,
    uris: list[str],
    mirror: PlaylistMirror | None = None,
) -> None:
    playlist_remove_uris(sp, playlist_id, uris)
    if mirror is not None:
        mirror.note_removed(uris)


def dedupe_playlist(sp, playlist_id: str, mirror: PlaylistMirror | None = None) -> int:
    """Collapse duplicate track occurrences; keep first-seen order. Returns removed count."""
    # Always re-read live playlist so duplicate occurrences are visible.
    ordered = playlist_items_ordered(sp, playlist_id)
    unique: list[str] = []
    seen: set[str] = set()
    for uri in ordered:
        if uri in seen:
            continue
        seen.add(uri)
        unique.append(uri)
    removed = len(ordered) - len(unique)
    if removed <= 0:
        if mirror is not None:
            mirror.ordered = list(unique)
            mirror.uris = set(unique)
        return 0
    replace_playlist_tracks(sp, playlist_id, unique)
    if mirror is not None:
        mirror.ordered = list(unique)
        mirror.uris = set(unique)
    print(f"  deduped playlist: removed {removed} duplicate occurrence(s); now {len(unique)} track(s)")
    return removed


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


def is_spotify_rate_limit(exc: BaseException) -> bool:
    status = getattr(exc, "http_status", None) or getattr(exc, "code", None)
    if status == 429:
        return True
    text = str(exc).casefold()
    return "rate/request limit" in text or "too many 429" in text or "retry-after" in text


def spotify_retry_after_seconds(exc: BaseException) -> float | None:
    headers = getattr(exc, "headers", None) or {}
    raw = None
    if isinstance(headers, dict):
        raw = headers.get("Retry-After") or headers.get("retry-after")
    else:
        try:
            raw = headers.get("Retry-After")  # type: ignore[attr-defined]
        except Exception:
            raw = None
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    text = str(exc)
    marker = "Retry will occur after:"
    if marker in text:
        try:
            return float(text.split(marker, 1)[1].split("s", 1)[0].strip())
        except ValueError:
            return None
    return None


def connect_spotify(cache_path: Path, *, required: bool):
    """Return (sp, display_name). When not required, return (None, None) on 429."""
    try:
        sp = build_client(cache_path)
        me = sp.current_user()
        return sp, (me.get("display_name") or me.get("id") or "?")
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        if is_spotify_rate_limit(exc):
            retry_after = spotify_retry_after_seconds(exc)
            hours = (retry_after or 0) / 3600.0
            detail = "Spotify rate-limited (429)."
            if retry_after and retry_after > 0:
                detail += f" Retry-After ≈ {retry_after:.0f}s ({hours:.1f}h)."
            if required:
                raise SystemExit(
                    f"{detail}\n"
                    "Cannot update the Spotify playlist until that window passes.\n"
                    "StungEvents matches are kept in drive/spotify_upcoming_shows/state.json — "
                    "re-run with --apply-playlist after the wait."
                ) from exc
            print(detail)
            print("Continuing without Spotify — StungEvents + state only; playlist sync deferred.")
            return None, None
        if required:
            raise
        raise


def artist_state_record(
    artist: Artist,
    shows: list[Show],
    uris: list[str],
    *,
    needs_playlist_sync: bool = False,
) -> dict:
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
                "playlist_eligible": bool(s.playlist_eligible),
                "kind": s.kind,
            }
            for s in shows
        ],
        "track_uris": uris,
        "needs_playlist_sync": bool(needs_playlist_sync),
        "setlistfm": None,  # reserved for path 2
    }


def scrub_title_mismatch_artists(
    state: dict,
    *,
    sp=None,
    playlist_id: str | None = None,
    dry_run: bool = False,
    mirror: PlaylistMirror | None = None,
) -> int:
    """Drop false-friend shows; strip playlist tracks for tribute-only artists.

    - Removes artists with no calendar-eligible shows
    - Keeps tribute/related shows in state for calendar
    - Removes Spotify tracks when no show is playlist-eligible (real headliner)
    Returns how many artists were fully removed (or would be, in dry-run).
    """
    removed = 0
    for artist_id, row in list((state.get("artists") or {}).items()):
        name = (row.get("name") or "").strip()
        shows = row.get("shows") or []
        kept: list[dict] = []
        for show in shows:
            title = show.get("title") or ""
            classified = classify_show(title, name) if name else None
            if classified is None:
                continue
            playlist_eligible, kind = classified
            updated = dict(show)
            updated["playlist_eligible"] = playlist_eligible
            updated["kind"] = kind
            kept.append(updated)

        label = name or artist_id
        if not kept:
            removed += 1
            if dry_run:
                print(f"  would remove (no title match): {label}")
                continue
            state["artists"].pop(artist_id, None)
            removable = [
                uri
                for uri in (row.get("track_uris") or [])
                if uri not in uris_used_by_other_artists(state, artist_id)
            ]
            if sp is not None and playlist_id and removable:
                try:
                    playlist_remove_tracked(sp, playlist_id, removable, mirror)
                except Exception as exc:  # noqa: BLE001
                    print(f"  ! playlist remove failed for {label}: {exc}")
            print(f"  removed (no title match): {label}")
            continue

        row["shows"] = kept
        if not any(s.get("playlist_eligible") for s in kept):
            # Calendar-only (tribute/related): do not keep this artist's songs on the playlist.
            uris = list(row.get("track_uris") or [])
            if uris:
                if dry_run:
                    print(f"  would strip playlist tracks (tribute/related only): {label} ({len(uris)})")
                else:
                    removable = [
                        uri for uri in uris if uri not in uris_used_by_other_artists(state, artist_id)
                    ]
                    if sp is not None and playlist_id and removable:
                        try:
                            playlist_remove_tracked(sp, playlist_id, removable, mirror)
                        except Exception as exc:  # noqa: BLE001
                            print(f"  ! playlist remove failed for {label}: {exc}")
                    row["track_uris"] = []
                    row["needs_playlist_sync"] = False
                    print(f"  stripped playlist tracks (tribute/related only): {label}")
            else:
                row["needs_playlist_sync"] = False
        elif dry_run and len(kept) != len(shows):
            print(f"  would prune shows for {label}: {len(shows) - len(kept)} dropped, {len(kept)} kept")
        elif len(kept) != len(shows):
            print(f"  pruned shows for {label}: {len(shows) - len(kept)} dropped, {len(kept)} kept")
    return removed


def flush_pending_playlist_artists(
    sp,
    playlist_id: str,
    state: dict,
    *,
    force_all: bool = False,
    liked_uris_by_artist: dict[str, list[str]] | None = None,
    market: str = "US",
    fill_missing_tracks: bool = False,
    mirror: PlaylistMirror | None = None,
) -> dict[str, int]:
    """Push tracked artists onto the Spotify playlist.

    By default only artists with needs_playlist_sync. With force_all=True, every
    tracked artist is reconciled (used by --apply-playlist).
    Downloads the live playlist first (or reuses mirror) so adds never duplicate.
    """
    if mirror is None:
        mirror = load_playlist_mirror(sp, playlist_id, state)
    liked_uris_by_artist = liked_uris_by_artist or {}
    stats = {"synced": 0, "added_tracks": 0, "already_ok": 0, "no_tracks": 0, "failed": 0}

    for artist_id, row in list((state.get("artists") or {}).items()):
        if not force_all and not row.get("needs_playlist_sync"):
            continue
        name = row.get("name") or artist_id
        if not artist_has_playlist_eligible_show(row):
            # Tribute/related calendar entries: ensure songs aren't on the playlist.
            uris_existing = list(row.get("track_uris") or [])
            if uris_existing:
                removable = [
                    uri
                    for uri in uris_existing
                    if uri not in uris_used_by_other_artists(state, artist_id)
                ]
                if removable:
                    try:
                        playlist_remove_tracked(sp, playlist_id, removable, mirror)
                        print(f"  → stripped tribute/related tracks: {name} ({len(removable)})")
                    except Exception as exc:  # noqa: BLE001
                        if is_spotify_rate_limit(exc):
                            raise
                        print(f"  ! strip failed for {name}: {exc}")
                row["track_uris"] = []
            row["needs_playlist_sync"] = False
            stats["already_ok"] += 1
            continue
        uris = list(row.get("track_uris") or [])
        if fill_missing_tracks and len(uris) < TRACKS_PER_ARTIST:
            filled = artist_track_uris(
                sp,
                artist_id,
                name if isinstance(name, str) else str(name),
                market,
                TRACKS_PER_ARTIST,
                liked_uris_by_artist,
            )
            if filled:
                uris = filled
                row["track_uris"] = uris

        if not uris:
            row["needs_playlist_sync"] = False
            stats["no_tracks"] += 1
            print(f"  ! {name}: no track URIs in state (liked cache empty / search failed)")
            continue
        missing = mirror.missing(uris)
        if not missing:
            row["needs_playlist_sync"] = False
            stats["already_ok"] += 1
            stats["synced"] += 1
            continue
        try:
            added = playlist_add_missing(sp, playlist_id, missing, mirror)
            row["needs_playlist_sync"] = False
            stats["synced"] += 1
            stats["added_tracks"] += len(added)
            print(f"  → playlist add: {name} ({len(added)} track(s))")
        except Exception as exc:  # noqa: BLE001
            if is_spotify_rate_limit(exc):
                print("  ! Spotify rate-limited while syncing playlist; stopping playlist pushes.")
                raise
            stats["failed"] += 1
            print(f"  ! playlist sync failed for {name}: {exc}")
    mirror.save_to_state(state)
    return stats


def apply_playlist_from_state(
    *,
    state_path: Path,
    cache_path: Path,
    market: str,
    min_liked: int,
    dry_run: bool,
) -> int:
    """Force Spotify playlist to match drive/.../state.json (no StungEvents calls)."""
    sp, display_name = connect_spotify(cache_path, required=True)
    assert sp is not None
    print(f"Authenticated as {display_name}")
    print("Mode: --apply-playlist (push state.json → Spotify 'upcoming shows', no StungEvents)")

    state = load_state(state_path)
    state.setdefault("artists", {})
    state["playlist_name"] = PLAYLIST_NAME
    tracked = len(state.get("artists") or {})
    pending = sum(1 for row in (state.get("artists") or {}).values() if row.get("needs_playlist_sync"))
    with_tracks = sum(1 for row in (state.get("artists") or {}).values() if row.get("track_uris"))
    print(f"State: {state_path}")
    print(f"Tracked artists: {tracked}; with track URIs: {with_tracks}; marked pending: {pending}")

    if dry_run:
        print("Dry run — scrub preview only; playlist not modified.")
        scrub_title_mismatch_artists(state, dry_run=True)
        return 0

    playlist_id = ensure_playlist(sp, state)
    state["playlist_id"] = playlist_id
    print(f"Playlist ready: {PLAYLIST_NAME!r} ({playlist_id})")
    mirror = load_playlist_mirror(sp, playlist_id, state)
    deduped = dedupe_playlist(sp, playlist_id, mirror)
    if deduped:
        mirror.save_to_state(state)

    print("Scrubbing artists whose show titles don't match the artist name …")
    scrubbed = scrub_title_mismatch_artists(
        state, sp=sp, playlist_id=playlist_id, dry_run=False, mirror=mirror
    )
    if scrubbed:
        print(f"Removed {scrubbed} title-mismatch artist(s).")

    lib_cache = library_cache(ttl_hours=DEFAULT_LIBRARY_CACHE_HOURS)
    liked_uris_by_artist: dict[str, list[str]] = {}
    try:
        _, liked_uris_by_artist = fetch_liked_artists(
            None, min_liked, cache=lib_cache, allow_stale=True, force_refresh=False
        )
    except SystemExit as exc:
        print(f"  note: could not load liked-track cache ({exc}); using state track_uris only")

    print(f"Reconciling all {len(state.get('artists') or {})} tracked artist(s) onto playlist …")
    stats = flush_pending_playlist_artists(
        sp,
        playlist_id,
        state,
        force_all=True,
        liked_uris_by_artist=liked_uris_by_artist,
        market=market,
        fill_missing_tracks=True,
        mirror=mirror,
    )
    mirror.save_to_state(state)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_state(state_path, state)

    print(
        f"\nPlaylist update done: added_tracks={stats['added_tracks']}, "
        f"artists_synced={stats['synced']}, already_ok={stats['already_ok']}, "
        f"no_tracks={stats['no_tracks']}, failed={stats['failed']}"
    )
    print(f"Open Spotify playlist: {PLAYLIST_NAME!r} ({playlist_id})")
    if stats["added_tracks"] == 0 and stats["no_tracks"] and not stats["already_ok"]:
        print(
            "Nothing was added — state has artists but no track URIs. "
            "Re-run without --apply-playlist once Spotify search works, or check library cache."
        )
    elif stats["added_tracks"] == 0 and stats["already_ok"]:
        print("Playlist already contained the tracked tracks; nothing new to add.")
    return 0 if stats["failed"] == 0 else 1


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
    favorites_only: bool,
    library_cache_only: bool,
) -> int:
    # With library cache we can gather artists + call StungEvents even if Spotify is 429.
    sp, display_name = connect_spotify(cache_path, required=not library_cache_only)
    spotify_ok = sp is not None
    if spotify_ok:
        print(f"Authenticated as {display_name}")

    state = load_state(state_path)
    state.setdefault("artists", {})
    state["playlist_name"] = PLAYLIST_NAME
    state["states"] = sorted(states)
    state["days"] = days
    state["year"] = year
    state["song_source"] = "liked_plus_search"

    playlist_id: str | None = None
    playlist_mirror: PlaylistMirror | None = None
    if not dry_run and spotify_ok:
        try:
            playlist_id = ensure_playlist(sp, state)
            state["playlist_id"] = playlist_id
            print(f"Playlist ready: {PLAYLIST_NAME!r} ({playlist_id})")
            playlist_mirror = load_playlist_mirror(sp, playlist_id, state)
            deduped = dedupe_playlist(sp, playlist_id, playlist_mirror)
            if deduped:
                playlist_mirror.save_to_state(state)
                save_state(state_path, state)
            # Drop false positives from before title-match filtering existed.
            print("Scrubbing artists whose show titles don't match the artist name …")
            scrubbed = scrub_title_mismatch_artists(
                state,
                sp=sp,
                playlist_id=playlist_id,
                dry_run=False,
                mirror=playlist_mirror,
            )
            if scrubbed:
                print(f"Removed {scrubbed} title-mismatch artist(s) from state/playlist.")
                playlist_mirror.save_to_state(state)
                state["updated_at"] = datetime.now(timezone.utc).isoformat()
                save_state(state_path, state)
            pending_stats = flush_pending_playlist_artists(
                sp, playlist_id, state, mirror=playlist_mirror
            )
            if pending_stats["synced"] or pending_stats["added_tracks"]:
                print(
                    f"Flushed pending playlist sync: "
                    f"artists={pending_stats['synced']}, tracks_added={pending_stats['added_tracks']}"
                )
                playlist_mirror.save_to_state(state)
                state["updated_at"] = datetime.now(timezone.utc).isoformat()
                save_state(state_path, state)
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
                    playlist_remove_tracked(sp, playlist_id, removable, playlist_mirror)
                print(f"  removed expired: {row.get('name') or aid}")
            if expired:
                if playlist_mirror is not None:
                    playlist_mirror.save_to_state(state)
                save_state(state_path, state)
        except Exception as exc:  # noqa: BLE001
            if library_cache_only and is_spotify_rate_limit(exc):
                print(f"Spotify became rate-limited during playlist setup ({exc}).")
                print("Continuing StungEvents-only; playlist sync deferred.")
                sp = None
                spotify_ok = False
                playlist_id = None
                playlist_mirror = None
            else:
                raise
    elif dry_run:
        print("Dry-run scrub preview (title mismatches):")
        scrub_title_mismatch_artists(state, dry_run=True)
    elif not dry_run and not spotify_ok:
        print("Skipping Spotify playlist setup (rate-limited). Scrubbing state only …")
        scrubbed = scrub_title_mismatch_artists(state, dry_run=False)
        if scrubbed:
            state["updated_at"] = datetime.now(timezone.utc).isoformat()
            save_state(state_path, state)
            print(f"Removed {scrubbed} title-mismatch artist(s) from state (playlist when Spotify is back).")
        print("Matches will be saved to state; playlist sync deferred.")

    print("Collecting artists …")
    lib_cache = library_cache(ttl_hours=DEFAULT_LIBRARY_CACHE_HOURS)
    print(f"Library cache: {lib_cache.path} (ttl {DEFAULT_LIBRARY_CACHE_HOURS:g}h)")
    if library_cache_only:
        print("Library cache-only — using followed/liked from disk (no Spotify library paging).")
        followed = fetch_followed_artists(
            None, cache=lib_cache, allow_stale=True, force_refresh=False
        )
        liked, liked_uris_by_artist = fetch_liked_artists(
            None, min_liked, cache=lib_cache, allow_stale=True, force_refresh=False
        )
        from_playlists: dict[str, Artist] = {}
    else:
        assert sp is not None
        followed = fetch_followed_artists(sp, cache=lib_cache, sleep_s=0.2, allow_stale=True)
        liked, liked_uris_by_artist = fetch_liked_artists(
            sp, min_liked, cache=lib_cache, sleep_s=0.2, allow_stale=True
        )
        from_playlists = {}
        if not favorites_only:
            names = playlist_names(year, "spaced")
            for tier in ("light", "medium", "heavy"):
                from_playlists.update(fetch_playlist_artists(sp, names[tier]))
        else:
            print("Favorites-only — skipping year light/medium/heavy playlist artists.")

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
    if spotify_ok:
        print("Song source: liked tracks first, then Spotify search (top-tracks API is blocked).")
    else:
        print("Song source: liked tracks from library cache only (Spotify search deferred).")
    if cache_only:
        print("Cache-only mode — no new StungEvents HTTP calls; fill playlist from disk cache.")
    elif dry_run:
        print("Dry run — matches print only; playlist/state not updated live.")
    elif spotify_ok:
        print("Live mode — adding each match to the playlist as soon as it's found.")
    else:
        print("Stung-only mode — saving matches to state; playlist updates when Spotify recovers.")

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
    ordered = prioritize_artists_for_stung(artists, stung)
    missing_stung = sum(1 for a in ordered if not stung.has_any_cache(a.name))
    print(f"Stung queue: {missing_stung} never-fetched first, then {len(ordered) - missing_stung} cached.")

    matched_this_run = 0
    removed_this_run = 0
    skipped_uncached = 0
    deferred_playlist = 0
    budget_hit = False
    try:
        for index, artist in enumerate(ordered, start=1):
            try:
                events = stung.fetch_events(artist.name)
                if events is None:
                    # cache-only miss: do not treat as "no shows" and do not remove.
                    skipped_uncached += 1
                    continue
                shows = shows_from_events(events, days, states, artist_name=artist.name)
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
                    if not dry_run and spotify_ok and playlist_id and removable:
                        try:
                            playlist_remove_tracked(sp, playlist_id, removable, playlist_mirror)
                            if playlist_mirror is not None:
                                playlist_mirror.save_to_state(state)
                        except Exception as exc:  # noqa: BLE001
                            if is_spotify_rate_limit(exc):
                                print("  ! Spotify rate-limited on remove; continuing Stung-only.")
                                sp = None
                                spotify_ok = False
                                playlist_id = None
                                playlist_mirror = None
                            else:
                                print(f"  ! playlist remove failed ({exc})")
                    removed_this_run += 1
                    print(f"  removed (no upcoming local shows): {artist.name}")
                    if not dry_run:
                        state["updated_at"] = datetime.now(timezone.utc).isoformat()
                        save_state(state_path, state)
                elif index % 50 == 0:
                    print(
                        f"  … progress {index}/{len(ordered)} "
                        f"(network={stung.network_calls}, cache_hits={stung.cache_hits})"
                    )
                continue

            prev = (state.get("artists") or {}).get(artist.artist_id) or {}
            prev_uris = list(prev.get("track_uris") or [])
            playlist_shows = [s for s in shows if s.playlist_eligible]
            calendar_only = not playlist_shows

            soonest = shows[0]
            place = f"{soonest.city}, {soonest.state}" if soonest.state else soonest.city
            kinds = ",".join(sorted({s.kind for s in shows}))
            print(
                f"  {artist.name}: {len(shows)} show(s) [{kinds}]; "
                f"soonest {soonest.start_utc} @ {place} "
                f"[{', '.join(sorted(artist.sources))}]"
            )

            uris: list[str] = []
            if calendar_only:
                print("    → calendar only (tribute/related) — no playlist tracks")
                # Drop any songs previously added for false headliner matches.
                if not dry_run and spotify_ok and playlist_id and prev_uris and sp is not None:
                    try:
                        if playlist_mirror is None:
                            playlist_mirror = load_playlist_mirror(sp, playlist_id, state)
                        removable = [
                            uri
                            for uri in prev_uris
                            if uri not in uris_used_by_other_artists(state, artist.artist_id)
                        ]
                        if removable:
                            playlist_remove_tracked(sp, playlist_id, removable, playlist_mirror)
                            playlist_mirror.save_to_state(state)
                            print(f"    → stripped {len(removable)} track(s) from {PLAYLIST_NAME!r}")
                    except Exception as exc:  # noqa: BLE001
                        if is_spotify_rate_limit(exc):
                            print("    ! Spotify rate-limited while stripping tribute tracks")
                            sp = None
                            spotify_ok = False
                            playlist_id = None
                            playlist_mirror = None
                        else:
                            print(f"    ! strip failed ({exc})")
                if dry_run:
                    matched_this_run += 1
                    continue
                state.setdefault("artists", {})[artist.artist_id] = artist_state_record(
                    artist, shows, [], needs_playlist_sync=False
                )
                state["updated_at"] = datetime.now(timezone.utc).isoformat()
                save_state(state_path, state)
                matched_this_run += 1
                continue

            if spotify_ok and sp is not None:
                try:
                    uris = artist_track_uris(
                        sp,
                        artist.artist_id,
                        artist.name,
                        market,
                        TRACKS_PER_ARTIST,
                        liked_uris_by_artist,
                    )
                except Exception as exc:  # noqa: BLE001
                    if is_spotify_rate_limit(exc):
                        print("  ! Spotify rate-limited on track lookup; continuing with liked-cache tracks.")
                        sp = None
                        spotify_ok = False
                        playlist_id = None
                        playlist_mirror = None
                        uris = list(liked_uris_by_artist.get(artist.artist_id, []))[:TRACKS_PER_ARTIST] or prev_uris
                    else:
                        print(
                            f"  ! {artist.name}: Spotify track lookup failed ({exc}); "
                            "saving show without new tracks"
                        )
                        uris = prev_uris
            else:
                uris = list(liked_uris_by_artist.get(artist.artist_id, []))[:TRACKS_PER_ARTIST] or prev_uris

            print(f"    → {len(uris)} playlist track(s) for headliner show(s)")

            if dry_run:
                matched_this_run += 1
                continue

            # Only add URIs missing from the live playlist mirror (downloaded at start).
            needs_playlist_sync = True
            if spotify_ok and playlist_id and sp is not None and uris:
                try:
                    if playlist_mirror is None:
                        playlist_mirror = load_playlist_mirror(sp, playlist_id, state)
                    obsolete = [
                        uri
                        for uri in prev_uris
                        if uri not in uris
                        and uri not in uris_used_by_other_artists(state, artist.artist_id)
                    ]
                    if obsolete:
                        playlist_remove_tracked(sp, playlist_id, obsolete, playlist_mirror)
                    added = playlist_add_missing(sp, playlist_id, uris, playlist_mirror)
                    if added:
                        print(f"    → added {len(added)} track(s) to {PLAYLIST_NAME!r}")
                        needs_playlist_sync = False
                    elif obsolete:
                        print(f"    → refreshed tracks on {PLAYLIST_NAME!r}")
                        needs_playlist_sync = False
                    else:
                        print("    → already on playlist; show dates refreshed")
                        needs_playlist_sync = False
                    playlist_mirror.save_to_state(state)
                except Exception as exc:  # noqa: BLE001
                    if is_spotify_rate_limit(exc):
                        print("    ! Spotify rate-limited on playlist write; saving for later sync")
                        sp = None
                        spotify_ok = False
                        playlist_id = None
                        playlist_mirror = None
                    else:
                        print(f"    ! playlist update failed ({exc}); show saved in state for retry")
                    needs_playlist_sync = True

            if needs_playlist_sync:
                deferred_playlist += 1
                print("    → saved to state (playlist sync pending)")

            state.setdefault("artists", {})[artist.artist_id] = artist_state_record(
                artist, shows, uris, needs_playlist_sync=needs_playlist_sync
            )
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

    # Final playlist reconcile: push ALL tracked artists onto Spotify when possible.
    playlist_stats: dict[str, int] | None = None
    if not dry_run:
        if not spotify_ok:
            print("\nRetrying Spotify connection for final playlist reconcile …")
            sp, display_name = connect_spotify(cache_path, required=False)
            spotify_ok = sp is not None
            if spotify_ok:
                print(f"Authenticated as {display_name}")
        if spotify_ok and sp is not None:
            try:
                playlist_id = ensure_playlist(sp, state)
                state["playlist_id"] = playlist_id
                print(f"\nFinal playlist reconcile → {PLAYLIST_NAME!r} ({playlist_id})")
                if playlist_mirror is None:
                    playlist_mirror = load_playlist_mirror(sp, playlist_id, state)
                    dedupe_playlist(sp, playlist_id, playlist_mirror)
                scrubbed = scrub_title_mismatch_artists(
                    state,
                    sp=sp,
                    playlist_id=playlist_id,
                    dry_run=False,
                    mirror=playlist_mirror,
                )
                if scrubbed:
                    print(f"Removed {scrubbed} title-mismatch artist(s) before reconcile.")
                playlist_stats = flush_pending_playlist_artists(
                    sp,
                    playlist_id,
                    state,
                    force_all=True,
                    liked_uris_by_artist=liked_uris_by_artist,
                    market=market,
                    fill_missing_tracks=True,
                    mirror=playlist_mirror,
                )
                playlist_mirror.save_to_state(state)
                state["updated_at"] = datetime.now(timezone.utc).isoformat()
                save_state(state_path, state)
                print(
                    f"Reconcile done: added_tracks={playlist_stats['added_tracks']}, "
                    f"artists_synced={playlist_stats['synced']}, "
                    f"already_ok={playlist_stats['already_ok']}, "
                    f"no_tracks={playlist_stats['no_tracks']}, "
                    f"failed={playlist_stats['failed']}"
                )
                print(
                    f"Spotify URL: https://open.spotify.com/playlist/{playlist_id}"
                )
            except Exception as exc:  # noqa: BLE001
                if is_spotify_rate_limit(exc):
                    print(f"Final playlist reconcile skipped — Spotify rate-limited ({exc}).")
                    spotify_ok = False
                else:
                    print(f"Final playlist reconcile failed: {exc}")
                    spotify_ok = False
        else:
            print("\nFinal playlist reconcile skipped — Spotify unavailable.")

    pending_left = sum(
        1 for row in (state.get("artists") or {}).values() if row.get("needs_playlist_sync")
    )
    print(
        f"\nStungEvents calls this run: network={stung.network_calls}, "
        f"cache_hits={stung.cache_hits}, cache_misses={stung.cache_misses}, "
        f"budget_used_today={stung._budget_used}/{stung.daily_budget}"
    )
    print(
        f"Matched this run: {matched_this_run}; removed this run: {removed_this_run}; "
        f"skipped (uncached): {skipped_uncached}; "
        f"playlist-deferred this run: {deferred_playlist}; "
        f"artists currently tracked: {len(state.get('artists') or {})}; "
        f"playlist pending: {pending_left}"
    )
    if budget_hit:
        print(
            "Partial run OK — StungEvents daily budget hit; progress is on disk.\n"
            "Continue tomorrow with:\n"
            "  python tools/sync_spotify_upcoming_shows.py --states MA,RI --days 120 --continue-cached"
        )
    if pending_left or (playlist_stats is None and not dry_run and not spotify_ok):
        print(
            "Playlist sync pending (Spotify was unavailable or rate-limited).\n"
            "When Spotify works again, force-push with:\n"
            "  python tools/sync_spotify_upcoming_shows.py --states MA,RI --days 120 --apply-playlist"
        )
    if cache_only:
        print(
            "Cache-only done. To fetch remaining uncached artists later:\n"
            "  python tools/sync_spotify_upcoming_shows.py --states MA,RI --days 120 --continue-cached"
        )
    if dry_run:
        print("Dry run complete — no playlist changes.")
    else:
        if state.get("playlist_id"):
            print(f"Live playlist: {PLAYLIST_NAME!r} ({state.get('playlist_id')})")
            print(f"Open: https://open.spotify.com/playlist/{state.get('playlist_id')}")
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
    parser.add_argument(
        "--continue-cached",
        action="store_true",
        help=(
            "Resume from disk: use cached favorite artists (followed + liked≥min), skip year "
            "playlists, keep calling StungEvents for never-fetched artists first, then "
            "force-reconcile the Spotify playlist from state at the end. If Spotify returns 429, "
            "continues StungEvents and saves matches for later --apply-playlist. Implies "
            "--favorites-only and --library-cache-only."
        ),
    )
    parser.add_argument(
        "--favorites-only",
        action="store_true",
        help="Only use followed + liked≥min artists (skip year light/medium/heavy playlists).",
    )
    parser.add_argument(
        "--library-cache-only",
        action="store_true",
        help=(
            "Load followed/liked artists from drive/spotify_library_cache/library.json only "
            "(no Spotify library paging). Still uses Spotify for playlist/track updates."
        ),
    )
    parser.add_argument(
        "--apply-playlist",
        action="store_true",
        help=(
            "Force-update the Spotify 'upcoming shows' playlist from state.json only "
            "(no StungEvents). Requires working Spotify API access. Scrubs title mismatches, "
            "fills missing track URIs from liked cache/search, and adds any missing tracks."
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
    favorites_only = bool(args.favorites_only or args.continue_cached)
    library_cache_only = bool(args.library_cache_only or args.continue_cached)
    try:
        if args.apply_playlist:
            return apply_playlist_from_state(
                state_path=args.state_file,
                cache_path=args.cache_path,
                market=args.market,
                min_liked=args.min_liked,
                dry_run=args.dry_run,
            )
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
            favorites_only=favorites_only,
            library_cache_only=library_cache_only,
        )
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
