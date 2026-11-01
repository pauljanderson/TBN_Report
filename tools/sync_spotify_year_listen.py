#!/usr/bin/env python3
"""Build "{year} listen" from followed-artist albums missing from year playlists.

Artist pool:
  - artists you follow

Candidate albums:
  - released in --year (default: current calendar year)
  - Spotify album-type releases only (not singles / appears_on)

Exclude an album if it already appears on any of:
  "{year} light" | "{year} medium" | "{year} heavy"
Matched by Spotify album id OR a normalized primary-artist + album-name key
(casefold, collapsed whitespace). That catches alternate editions / regional
catalog ids that share the same title for the same primary artist.

Playlist: "{year} listen" — full album track lists for remaining candidates.
Re-runs rebuild the playlist, so albums that later land on light/medium/heavy
drop off automatically. sync_spotify_year_playlists.py also scrubs "{year} listen"
immediately after it writes the year buckets.

Optimizations (Dev Mode friendly):
  - Disk-cache followed artists + artist discographies + album tracks
  - Dirty-artist queue: new follows first, then missing discography cache
  - Per-run cap on discography fetches (--max-artists-fetch)
  - Daily Spotify HTTP budget (--spotify-daily-budget); resume next run

Examples:
  python tools/sync_spotify_year_listen.py --dry-run
  python tools/sync_spotify_year_listen.py --year 2026
  python tools/sync_spotify_year_listen.py --max-artists-fetch 40 --spotify-daily-budget 150
  python tools/sync_spotify_year_listen.py --cache-only

Call-budget guidance (Development Mode):
  Spotify does not publish a fixed daily number; Dev Mode has a rolling 30s rate
  limit plus an opaque account quota (429 reason QUOTA_EXCEEDED). This tool
  defaults to a self-imposed 150 calls/UTC-day and caches discographies for 14 days.
  Artist album pages are capped at limit=10 by Spotify (higher → 400 Invalid limit).
  Run --estimate to size calls from YOUR followed-artist count (library cache).
  Weekly once warm; cold-start large follow lists over several days. Avoid stacking
  this on the same day as a full upcoming-shows or favorites-unlistened crawl.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from spotify_json_cache import DEFAULT_LIBRARY_CACHE_HOURS, JsonCache, library_cache  # noqa: E402
from sync_spotify_upcoming_shows import Artist, fetch_followed_artists  # noqa: E402
from sync_spotify_year_playlists import (  # noqa: E402
    DEFAULT_CACHE_PATH,
    DEFAULT_ENV_PATH,
    REPO_ROOT,
    build_client,
    chunked,
    find_or_create_playlist,
    load_env_file,
    playlist_names,
    release_year,
    replace_playlist_tracks,
)

DEFAULT_DATA_DIR = REPO_ROOT / "drive" / "spotify_year_listen"
DEFAULT_SPOTIFY_SLEEP = 0.35
DEFAULT_MAX_ARTISTS_FETCH = 40
DEFAULT_SPOTIFY_DAILY_BUDGET = 150
DEFAULT_ALBUM_CACHE_HOURS = 336.0  # 14 days — new albums are infrequent
DEFAULT_LIBRARY_CACHE_HOURS_LOCAL = DEFAULT_LIBRARY_CACHE_HOURS


def listen_playlist_name(year: int) -> str:
    return f"{year} listen"


@dataclass
class CandidateAlbum:
    album_id: str
    name: str
    artists: str
    release_date: str
    source_artist_id: str = ""


@dataclass
class YearPlaylistIndex:
    """Albums already represented on light/medium/heavy for a year."""

    album_ids: set[str] = field(default_factory=set)
    name_keys: set[str] = field(default_factory=set)
    track_count: int = 0

    def __ior__(self, other: YearPlaylistIndex) -> YearPlaylistIndex:
        self.album_ids |= other.album_ids
        self.name_keys |= other.name_keys
        self.track_count += other.track_count
        return self


def normalized_text(value: str) -> str:
    """Casefold + collapse whitespace (NFKC)."""
    return " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())


def primary_artist_name(artists: str) -> str:
    """First listed album artist (Spotify joins with ', ')."""
    return (artists or "").split(",", 1)[0].strip()


def album_name_key(artists: str, name: str) -> str:
    """Stable key for matching alternate catalog ids of the same release title."""
    return f"{normalized_text(primary_artist_name(artists))}\x1f{normalized_text(name)}"


def artists_from_spotify_list(artists: list | None) -> str:
    return ", ".join(a.get("name", "") for a in (artists or []) if a.get("name"))


def album_on_year_playlists(
    album_id: str,
    artists: str,
    name: str,
    index: YearPlaylistIndex,
) -> bool:
    if album_id and album_id in index.album_ids:
        return True
    key = album_name_key(artists, name)
    return bool(key.strip("\x1f")) and key in index.name_keys


class SpotifyRateLimitError(RuntimeError):
    def __init__(self, retry_after: float | None = None, message: str = "") -> None:
        self.retry_after = retry_after
        hours = (retry_after or 0) / 3600.0
        detail = message or "Spotify rate limit (429)."
        if retry_after and retry_after > 0:
            detail += f" Retry-After ≈ {retry_after:.0f}s ({hours:.1f}h)."
        detail += " Stop and retry after that window; caches will resume progress."
        super().__init__(detail)


class SpotifyBudgetExceeded(RuntimeError):
    pass


class SpotifyBudget:
    """Count Spotify HTTP calls and stop before blowing Dev Mode quota."""

    def __init__(self, path: Path, daily_budget: int) -> None:
        self.path = path
        self.daily_budget = daily_budget
        self.used = 0
        self._load()

    def _load(self) -> None:
        today = datetime.now(timezone.utc).date().isoformat()
        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
        else:
            data = {}
        if data.get("date") != today:
            data = {"date": today, "used": 0}
        self.used = int(data.get("used") or 0)
        self._date = data["date"]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"date": self._date, "used": self.used}, indent=2) + "\n",
            encoding="utf-8",
        )

    def charge(self, n: int = 1) -> None:
        if self.used + n > self.daily_budget:
            self.save()
            raise SpotifyBudgetExceeded(
                f"Spotify daily budget exhausted ({self.used}/{self.daily_budget}). "
                "Re-run tomorrow; album/library caches keep progress."
            )
        self.used += n
        if self.used % 10 == 0:
            self.save()


def _retry_after_seconds(exc: Exception) -> float | None:
    headers = getattr(exc, "headers", None) or {}
    raw = None
    if isinstance(headers, dict):
        raw = headers.get("Retry-After") or headers.get("retry-after")
    else:
        try:
            raw = headers.get("Retry-After")  # type: ignore[attr-defined]
        except Exception:
            raw = None
    if raw is None:
        text = str(exc)
        marker = "Retry will occur after:"
        if marker in text:
            try:
                return float(text.split(marker, 1)[1].split("s", 1)[0].strip())
            except ValueError:
                return None
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def spotify_call(fn, *args, budget: SpotifyBudget | None = None, **kwargs):
    try:
        from spotipy.exceptions import SpotifyException
    except ImportError:
        SpotifyException = Exception  # type: ignore[misc, assignment]
    if budget is not None:
        budget.charge(1)
    try:
        return fn(*args, **kwargs)
    except SpotifyException as exc:  # type: ignore[misc]
        status = getattr(exc, "http_status", None) or getattr(exc, "code", None)
        if status == 429 or "rate/request limit" in str(exc).casefold():
            raise SpotifyRateLimitError(_retry_after_seconds(exc), str(exc)) from exc
        raise


def cache_get(cache: JsonCache, key: str, *, allow_stale: bool = False):
    value = cache.get(key)
    if value is not None:
        return value
    if not allow_stale:
        return None
    row = cache.data.get(key)
    if isinstance(row, dict) and "value" in row:
        return row["value"]
    return None


def artist_albums_cache_key(artist_id: str, year: int, market: str) -> str:
    return f"artist_albums:{artist_id}:{year}:album:{market}"


def load_state(path: Path, year: int) -> dict:
    if not path.is_file():
        return {
            "playlist_id": None,
            "playlist_name": listen_playlist_name(year),
            "artist_pool_ids": [],
            "kept_albums": {},
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    data.setdefault("kept_albums", {})
    data.setdefault("artist_pool_ids", [])
    data.setdefault("playlist_name", listen_playlist_name(year))
    return data


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def find_playlist_id(sp, name: str, budget: SpotifyBudget | None = None) -> str | None:
    offset = 0
    while True:
        page = spotify_call(sp.current_user_playlists, limit=50, offset=offset, budget=budget)
        items = page.get("items") or []
        for playlist in items:
            if playlist and playlist.get("name") == name:
                return playlist.get("id")
        offset += len(items)
        if page.get("next") is None:
            break
        time.sleep(0.05)
    return None


def playlist_album_index(
    sp,
    playlist_id: str,
    *,
    budget: SpotifyBudget | None = None,
    sleep_s: float = 0.05,
) -> YearPlaylistIndex:
    """Album ids + name keys represented by tracks currently on a playlist."""
    index = YearPlaylistIndex()
    offset = 0
    while True:
        # Avoid restrictive `fields=` — some spotipy/API combos return empty items.
        page = spotify_call(
            sp.playlist_items,
            playlist_id,
            limit=100,
            offset=offset,
            additional_types=("track",),
            budget=budget,
        )
        items = page.get("items") or []
        if not items:
            break
        for entry in items:
            track = entry.get("track") or {}
            if not track or track.get("is_local"):
                continue
            index.track_count += 1
            album = track.get("album") or {}
            album_id = album.get("id")
            if album_id:
                index.album_ids.add(album_id)
            album_name = album.get("name") or ""
            artists = artists_from_spotify_list(album.get("artists"))
            if not artists:
                artists = artists_from_spotify_list(track.get("artists"))
            if album_name and artists:
                index.name_keys.add(album_name_key(artists, album_name))
        offset += len(items)
        if page.get("next") is None:
            break
        time.sleep(sleep_s)
    return index


def playlist_album_ids(
    sp,
    playlist_id: str,
    *,
    budget: SpotifyBudget | None = None,
    sleep_s: float = 0.05,
) -> set[str]:
    """Album ids represented by tracks currently on a playlist."""
    return playlist_album_index(sp, playlist_id, budget=budget, sleep_s=sleep_s).album_ids


def year_playlist_album_ids(
    sp,
    year: int,
    name_style: str,
    *,
    budget: SpotifyBudget | None = None,
    sleep_s: float = 0.05,
) -> tuple[YearPlaylistIndex, dict[str, str | None]]:
    """Return (index of albums on light/medium/heavy, playlist_id by tier)."""
    names = playlist_names(year, name_style)
    ids_by_tier: dict[str, str | None] = {}
    index = YearPlaylistIndex()
    for tier, name in names.items():
        playlist_id = find_playlist_id(sp, name, budget=budget)
        ids_by_tier[tier] = playlist_id
        if not playlist_id:
            print(f"  missing playlist {name!r} — treating as empty")
            continue
        found = playlist_album_index(sp, playlist_id, budget=budget, sleep_s=sleep_s)
        print(
            f"  {name!r}: {found.track_count} track(s), "
            f"{len(found.album_ids)} album id(s), {len(found.name_keys)} name key(s)"
        )
        index |= found
    return index, ids_by_tier


def rows_to_albums(rows: list, source_artist_id: str = "") -> list[CandidateAlbum]:
    out: list[CandidateAlbum] = []
    for row in rows:
        out.append(
            CandidateAlbum(
                album_id=row["album_id"],
                name=row["name"],
                artists=row["artists"],
                release_date=row["release_date"],
                source_artist_id=source_artist_id or row.get("source_artist_id") or "",
            )
        )
    return out


def fetch_artist_year_albums(
    sp,
    artist: Artist,
    year: int,
    market: str,
    cache: JsonCache,
    sleep_s: float,
    budget: SpotifyBudget,
    *,
    allow_fetch: bool,
) -> tuple[list[CandidateAlbum], bool]:
    """Return (albums, fetched_from_network). Albums only — no singles."""
    cache_key = artist_albums_cache_key(artist.artist_id, year, market)
    fresh = cache.get(cache_key)
    if isinstance(fresh, list):
        return rows_to_albums(fresh, artist.artist_id), False
    stale = cache_get(cache, cache_key, allow_stale=True)
    if isinstance(stale, list) and not allow_fetch:
        return rows_to_albums(stale, artist.artist_id), False
    if not allow_fetch:
        return [], False

    albums: dict[str, CandidateAlbum] = {}
    offset = 0
    # Spotify capped Get Artist's Albums max limit at 10 (Feb 2026); 20/50 → 400 Invalid limit.
    page_limit = 10
    while True:
        page = spotify_call(
            sp.artist_albums,
            artist.artist_id,
            include_groups="album",
            country=market,
            limit=page_limit,
            offset=offset,
            budget=budget,
        )
        items = page.get("items") or []
        if not items:
            break
        # Results are newest-first; once every item on a page is older than --year, stop.
        page_years: list[int] = []
        for album in items:
            if not album or not album.get("id"):
                continue
            yr = release_year(album.get("release_date"))
            if yr is not None:
                page_years.append(yr)
            if yr != year:
                continue
            # Defensive: artist_albums can still surface odd groups.
            group = (album.get("album_group") or album.get("album_type") or "").casefold()
            if group and group not in {"album"}:
                continue
            album_id = album["id"]
            if album_id in albums:
                continue
            artist_names = ", ".join(
                a.get("name", "") for a in (album.get("artists") or []) if a.get("name")
            )
            albums[album_id] = CandidateAlbum(
                album_id=album_id,
                name=album.get("name") or "(unknown album)",
                artists=artist_names or artist.name,
                release_date=album.get("release_date") or "",
                source_artist_id=artist.artist_id,
            )
        offset += len(items)
        if page.get("next") is None:
            break
        if page_years and max(page_years) < year:
            break
        time.sleep(sleep_s)

    rows = [
        {
            "album_id": a.album_id,
            "name": a.name,
            "artists": a.artists,
            "release_date": a.release_date,
            "source_artist_id": a.source_artist_id,
        }
        for a in albums.values()
    ]
    cache.set(cache_key, rows)
    return list(albums.values()), True


def album_track_uris(
    sp,
    album_id: str,
    market: str,
    cache: JsonCache,
    sleep_s: float,
    budget: SpotifyBudget,
    *,
    allow_fetch: bool,
) -> tuple[list[str], bool]:
    cache_key = f"album_tracks:{album_id}:{market}"
    fresh = cache.get(cache_key)
    if isinstance(fresh, dict):
        return list(fresh.get("uris") or []), False
    stale = cache_get(cache, cache_key, allow_stale=True)
    if isinstance(stale, dict) and not allow_fetch:
        return list(stale.get("uris") or []), False
    if not allow_fetch:
        return [], False

    uris: list[str] = []
    offset = 0
    while True:
        page = spotify_call(
            sp.album_tracks, album_id, limit=50, offset=offset, market=market, budget=budget
        )
        items = page.get("items") or []
        if not items:
            break
        for track in items:
            if not track or track.get("is_local"):
                continue
            uri = track.get("uri")
            if uri:
                uris.append(uri)
        offset += len(items)
        if page.get("next") is None:
            break
        time.sleep(sleep_s)
    cache.set(cache_key, {"uris": uris})
    return uris, True


def prioritize_artists(
    artists: dict[str, Artist],
    prev_pool_ids: set[str],
    cache: JsonCache,
    year: int,
    market: str,
) -> list[Artist]:
    """New follows first, then missing discography cache, then everyone else."""

    def has_album_cache(artist_id: str) -> bool:
        key = artist_albums_cache_key(artist_id, year, market)
        return cache_get(cache, key, allow_stale=True) is not None

    new_artists = []
    missing_cache = []
    rest = []
    for artist in artists.values():
        if artist.artist_id not in prev_pool_ids:
            new_artists.append(artist)
        elif not has_album_cache(artist.artist_id):
            missing_cache.append(artist)
        else:
            rest.append(artist)

    key = lambda a: a.name.casefold()
    return sorted(new_artists, key=key) + sorted(missing_cache, key=key) + sorted(rest, key=key)


def scrub_listen_playlist_of_albums(
    sp,
    year: int,
    album_ids: set[str],
    *,
    name_keys: set[str] | None = None,
    dry_run: bool = False,
    budget: SpotifyBudget | None = None,
    sleep_s: float = 0.05,
    playlist_id: str | None = None,
) -> int:
    """Remove tracks matching year-playlist albums from "{year} listen".

    Matches by Spotify album id and/or normalized artist+album name key.
    Used by sync_spotify_year_playlists after it writes light/medium/heavy.
    Returns number of track URIs removed (0 if playlist missing / nothing to do).
    """
    keys = name_keys or set()
    if not album_ids and not keys:
        return 0
    name = listen_playlist_name(year)
    pid = playlist_id or find_playlist_id(sp, name, budget=budget)
    if not pid:
        return 0

    remove_uris: list[str] = []
    offset = 0
    while True:
        page = spotify_call(
            sp.playlist_items,
            pid,
            limit=100,
            offset=offset,
            additional_types=("track",),
            budget=budget,
        )
        items = page.get("items") or []
        if not items:
            break
        for entry in items:
            track = entry.get("track") or {}
            if not track or track.get("is_local"):
                continue
            album = track.get("album") or {}
            album_id = album.get("id")
            uri = track.get("uri")
            if not uri:
                continue
            matched = bool(album_id and album_id in album_ids)
            if not matched and keys:
                artists = artists_from_spotify_list(album.get("artists"))
                if not artists:
                    artists = artists_from_spotify_list(track.get("artists"))
                album_name = album.get("name") or ""
                if artists and album_name and album_name_key(artists, album_name) in keys:
                    matched = True
            if matched:
                remove_uris.append(uri)
        offset += len(items)
        if page.get("next") is None:
            break
        time.sleep(sleep_s)

    # Dedupe while preserving order
    seen: set[str] = set()
    unique = []
    for uri in remove_uris:
        if uri not in seen:
            seen.add(uri)
            unique.append(uri)

    if not unique:
        return 0
    if dry_run:
        print(f"  [dry-run] would remove {len(unique)} track(s) from {name!r}")
        return len(unique)

    for batch in chunked(unique, 100):
        spotify_call(sp.playlist_remove_all_occurrences_of_items, pid, batch, budget=budget)
        time.sleep(sleep_s)
    print(f"  Scrubbed {len(unique)} track(s) from {name!r} (albums now on year playlists).")
    return len(unique)


def sync(
    *,
    year: int,
    name_style: str,
    market: str,
    dry_run: bool,
    cache_path: Path,
    data_dir: Path,
    album_cache_hours: float,
    spotify_sleep: float,
    max_artists_fetch: int,
    spotify_daily_budget: int,
    cache_only: bool,
    refresh_followed: bool,
) -> int:
    sp = build_client(cache_path)
    budget = SpotifyBudget(data_dir / "spotify_budget.json", spotify_daily_budget)
    me = spotify_call(sp.current_user, budget=budget)
    print(f"Authenticated as {me.get('display_name') or me.get('id')}")
    print(f"Spotify daily budget: {budget.used}/{budget.daily_budget} used so far today (UTC)")

    album_cache = JsonCache(data_dir / "album_cache.json", ttl_hours=album_cache_hours)
    lib_cache = library_cache(ttl_hours=DEFAULT_LIBRARY_CACHE_HOURS_LOCAL)
    state_path = data_dir / "state.json"
    state = load_state(state_path, year)
    playlist_name = listen_playlist_name(year)

    print(f"Caches: library={lib_cache.path}")
    print(f"        albums={album_cache.path} (ttl {album_cache_hours:g}h)")
    print(f"Target playlist: {playlist_name!r}")

    print("Loading followed artists …")
    followed = fetch_followed_artists(
        sp,
        cache=lib_cache,
        sleep_s=spotify_sleep,
        force_refresh=refresh_followed,
    )
    prev_pool = set(state.get("artist_pool_ids") or [])
    new_count = sum(1 for aid in followed if aid not in prev_pool)
    print(f"Followed artists: {len(followed)} (new_since_last={new_count})")

    print(f"Reading albums already on {year} light/medium/heavy …")
    on_year, _ = year_playlist_album_ids(
        sp, year, name_style, budget=budget, sleep_s=spotify_sleep
    )
    print(
        f"Year-playlist index: {on_year.track_count} track(s), "
        f"{len(on_year.album_ids)} album id(s), {len(on_year.name_keys)} name key(s)"
    )
    if on_year.track_count and not on_year.album_ids:
        print(
            "  WARNING: year playlists have tracks but 0 album ids — "
            "exclusion would be incomplete; check playlist_items responses."
        )

    ordered = prioritize_artists(followed, prev_pool, album_cache, year, market)
    print(
        f"Discography queue: {len(ordered)} artists; "
        f"this run will fetch at most {0 if cache_only else max_artists_fetch} "
        f"uncached/new discographies"
        + (" (cache-only)" if cache_only else "")
    )

    candidates: dict[str, CandidateAlbum] = {}
    fetched_artists = 0
    cache_hits = 0
    stopped_early = False

    for index, artist in enumerate(ordered, start=1):
        key = artist_albums_cache_key(artist.artist_id, year, market)
        already_cached = cache_get(album_cache, key, allow_stale=True) is not None
        allow_fetch = (not cache_only) and (not already_cached) and (fetched_artists < max_artists_fetch)
        try:
            albums, did_fetch = fetch_artist_year_albums(
                sp,
                artist,
                year,
                market,
                album_cache,
                spotify_sleep,
                budget,
                allow_fetch=allow_fetch,
            )
        except SpotifyBudgetExceeded as exc:
            print(f"\n{exc}")
            stopped_early = True
            break
        except SpotifyRateLimitError:
            raise

        if did_fetch:
            fetched_artists += 1
            print(f"  fetched discography: {artist.name} ({len(albums)} {year} album(s))")
        elif already_cached:
            cache_hits += 1
        elif cache_only or fetched_artists >= max_artists_fetch:
            continue

        for album in albums:
            if album_on_year_playlists(album.album_id, album.artists, album.name, on_year):
                continue
            candidates.setdefault(album.album_id, album)

        if index % 50 == 0:
            print(
                f"  … queue {index}/{len(ordered)}; "
                f"candidates={len(candidates)}; fetched={fetched_artists}; cache_hits={cache_hits}"
            )
        if already_cached or not did_fetch:
            continue
        time.sleep(spotify_sleep)

    print(
        f"Candidate {year} albums not on year playlists: {len(candidates)} "
        f"(discography fetches={fetched_artists}, cache hits={cache_hits})"
    )

    # Drop stale kept_albums that now match year playlists (id or name key),
    # even if they are not rediscovered via discography this run.
    prev_kept = state.get("kept_albums") or {}
    if isinstance(prev_kept, dict):
        for album_id, row in list(prev_kept.items()):
            if not isinstance(row, dict):
                continue
            if album_on_year_playlists(
                str(row.get("album_id") or album_id),
                str(row.get("artists") or ""),
                str(row.get("name") or ""),
                on_year,
            ):
                prev_kept.pop(album_id, None)

    kept: dict[str, dict] = {}
    for album in sorted(
        candidates.values(), key=lambda a: (a.artists.casefold(), a.name.casefold())
    ):
        if album_on_year_playlists(album.album_id, album.artists, album.name, on_year):
            continue
        allow_track_fetch = not cache_only
        try:
            track_uris, _ = album_track_uris(
                sp,
                album.album_id,
                market,
                album_cache,
                spotify_sleep,
                budget,
                allow_fetch=allow_track_fetch,
            )
        except SpotifyBudgetExceeded as exc:
            print(f"\n{exc}")
            stopped_early = True
            break
        except SpotifyRateLimitError:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"  ! album {album.artists} — {album.name}: {exc}")
            continue
        if not track_uris:
            continue
        kept[album.album_id] = {
            "album_id": album.album_id,
            "name": album.name,
            "artists": album.artists,
            "release_date": album.release_date,
            "track_uris": track_uris,
            "source_artist_id": album.source_artist_id,
            "name_key": album_name_key(album.artists, album.name),
        }
        print(
            f"  KEEP {album.artists} — {album.name} ({album.release_date}) "
            f"[{len(track_uris)} tracks]"
        )

    track_uris: list[str] = []
    seen: set[str] = set()
    for row in sorted(
        kept.values(),
        key=lambda r: ((r.get("artists") or "").casefold(), (r.get("name") or "").casefold()),
    ):
        for uri in row.get("track_uris") or []:
            if uri not in seen:
                seen.add(uri)
                track_uris.append(uri)

    print(
        f"\nPlaylist {playlist_name!r}: {len(track_uris)} unique track(s) "
        f"from {len(kept)} album(s)."
    )

    state["artist_pool_ids"] = sorted(followed.keys())
    state["kept_albums"] = kept
    state["year"] = year
    state["market"] = market
    state["on_year_playlist_album_count"] = len(on_year.album_ids)
    state["on_year_playlist_name_key_count"] = len(on_year.name_keys)
    state["on_year_playlist_track_count"] = on_year.track_count
    state["playlist_name"] = playlist_name
    budget.save()

    if dry_run:
        save_state(state_path.with_suffix(".dry-run.json"), state)
        print(f"Dry run — wrote {state_path.with_suffix('.dry-run.json')}; playlist not modified.")
        print_call_guidance(budget, fetched_artists, cache_hits, stopped_early, cache_only, max_artists_fetch)
        return 0

    playlist_id = state.get("playlist_id")
    if playlist_id:
        # Verify id still resolves to the expected name; otherwise re-find/create.
        try:
            meta = spotify_call(sp.playlist, playlist_id, fields="id,name", budget=budget)
            if (meta or {}).get("name") != playlist_name:
                playlist_id = None
        except Exception:
            playlist_id = None
    if not playlist_id:
        # Unbudgeted helper (shared with year sync); then stamp our description.
        playlist_id = find_or_create_playlist(sp, playlist_name, dry_run=False)
    assert playlist_id
    try:
        spotify_call(
            sp.playlist_change_details,
            playlist_id,
            description=(
                f"Auto-synced: {year} albums from followed artists not yet on "
                f"{year} light/medium/heavy (sync_spotify_year_listen.py)"
            ),
            budget=budget,
        )
    except Exception:
        pass

    replace_playlist_tracks(sp, playlist_id, track_uris)
    state["playlist_id"] = playlist_id
    save_state(state_path, state)
    print(f"Updated playlist {playlist_name!r} ({playlist_id})")
    print(f"State: {state_path}")
    print_call_guidance(budget, fetched_artists, cache_hits, stopped_early, cache_only, max_artists_fetch)
    return 0


def print_call_guidance(
    budget: SpotifyBudget,
    fetched_artists: int,
    cache_hits: int,
    stopped_early: bool,
    cache_only: bool,
    max_artists_fetch: int,
) -> None:
    print(f"Spotify calls charged today (this tool): {budget.used}/{budget.daily_budget}")
    print(
        "Schedule tip: weekly once discographies are cached; "
        "cold-start large follow lists across several days with --max-artists-fetch 40. "
        "Do not stack with a heavy upcoming-shows / favorites crawl the same day."
    )
    if stopped_early or (not cache_only and fetched_artists >= max_artists_fetch and cache_hits >= 0):
        if stopped_early or (not cache_only and fetched_artists >= max_artists_fetch):
            print(
                "Partial discography coverage this run — re-run another day to continue the queue."
            )


def estimate_calls(
    followed: int,
    *,
    cached_discographies: int = 0,
    max_artists_fetch: int = DEFAULT_MAX_ARTISTS_FETCH,
    year_playlist_tracks: int = 0,
    new_albums: int | None = None,
    pages_per_discography: float = 1.5,
) -> dict[str, int]:
    """Rough HTTP call counts for planning (used by --estimate).

    Discography paging uses limit=10 (Spotify max); assume ~1.5 pages/artist on
    average when stopping early at albums older than --year.
    """
    uncached = max(0, followed - cached_discographies)
    fetch_this_run = min(uncached, max_artists_fetch) if max_artists_fetch > 0 else 0
    if new_albums is None:
        # Rough: a few percent of followed artists release a year-album you care about.
        new_albums = max(5, followed // 25)

    followed_pages = max(1, (followed + 49) // 50)
    # Find 3 year playlists among user playlists (~1–N pages) + read their tracks.
    year_pages = 5 + max(3, (year_playlist_tracks + 99) // 100)
    disco_calls = int(round(fetch_this_run * pages_per_discography))
    warm_disco = int(round(min(5, uncached) * pages_per_discography)) if uncached else 0

    return {
        "auth_and_me": 1,
        "followed_refresh": followed_pages,
        "year_playlist_scan": year_pages,
        "uncached_artists": uncached,
        "fetch_this_run": fetch_this_run,
        "discography_calls_this_run": disco_calls,
        "warm_discography_calls": warm_disco,
        "new_album_tracks": max(new_albums, 1),
        "playlist_write": max(1, (new_albums * 10 + 99) // 100),
        "cold_full_discographies": int(round(followed * pages_per_discography)),
    }


def sum_estimate(parts: dict[str, int], *keys: str) -> int:
    return sum(parts[k] for k in keys)


def count_cached_discographies(
    album_cache: JsonCache, artist_ids: list[str], year: int, market: str
) -> int:
    n = 0
    for artist_id in artist_ids:
        key = artist_albums_cache_key(artist_id, year, market)
        if cache_get(album_cache, key, allow_stale=True) is not None:
            n += 1
    return n


def load_followed_ids_for_estimate(
    *,
    env_file: Path,
    cache_path: Path,
    refresh: bool,
) -> tuple[list[str], str]:
    """Return (artist_ids, source_label) from library cache and/or live Spotify."""
    lib_cache = library_cache(ttl_hours=DEFAULT_LIBRARY_CACHE_HOURS_LOCAL)
    cached = lib_cache.get("followed_artists", allow_stale=True)
    if isinstance(cached, list) and cached and not refresh:
        ids = [row.get("artist_id") for row in cached if isinstance(row, dict) and row.get("artist_id")]
        fetched_at = ""
        row = lib_cache.data.get("followed_artists")
        if isinstance(row, dict):
            fetched_at = str(row.get("fetched_at") or "")
        label = f"library cache ({lib_cache.path}"
        if fetched_at:
            label += f", fetched_at={fetched_at}"
        label += ")"
        return ids, label

    load_env_file(env_file)
    load_env_file(REPO_ROOT / ".env")
    sp = build_client(cache_path)
    followed = fetch_followed_artists(sp, cache=lib_cache, sleep_s=0.2, force_refresh=True)
    return list(followed.keys()), "live Spotify followed-artists scan (cache refreshed)"


def print_personalized_estimate(args: argparse.Namespace) -> int:
    artist_ids, source = load_followed_ids_for_estimate(
        env_file=args.env_file,
        cache_path=args.cache_path,
        refresh=args.refresh_followed,
    )
    followed = len(artist_ids)
    album_cache = JsonCache(args.data_dir / "album_cache.json", ttl_hours=args.album_cache_hours)
    cached = count_cached_discographies(album_cache, artist_ids, args.year, args.market)
    uncached = max(0, followed - cached)

    est = estimate_calls(
        followed,
        cached_discographies=cached,
        max_artists_fetch=args.max_artists_fetch,
        year_playlist_tracks=max(100, followed // 2),
    )
    this_run = sum_estimate(
        est,
        "auth_and_me",
        "year_playlist_scan",
        "discography_calls_this_run",
        "new_album_tracks",
        "playlist_write",
    )
    # If followed cache is stale and we didn't refresh, one optional refresh adds pages.
    this_run_with_follow_refresh = this_run + est["followed_refresh"]

    warm = sum_estimate(
        est,
        "auth_and_me",
        "year_playlist_scan",
        "warm_discography_calls",
        "new_album_tracks",
        "playlist_write",
    )
    cold_full = sum_estimate(
        est,
        "auth_and_me",
        "followed_refresh",
        "year_playlist_scan",
        "cold_full_discographies",
        "new_album_tracks",
        "playlist_write",
    )

    days_at_cap = (
        (uncached + args.max_artists_fetch - 1) // args.max_artists_fetch
        if args.max_artists_fetch > 0 and uncached
        else 0
    )
    # Budget gate: discography pages dominate; require budget headroom for this_run.
    budget = args.spotify_daily_budget
    fits_budget = this_run <= budget

    print("Personalized Spotify call estimate (Development Mode)\n")
    print(f"  Followed artists:     {followed}  ← {source}")
    print(f"  Year:                 {args.year}  market={args.market}")
    print(f"  Discographies cached: {cached}/{followed}  (uncached={uncached})")
    print(f"  Per-run fetch cap:    {args.max_artists_fetch} artists")
    print(f"  Self-budget:          {budget} calls/UTC-day")
    print()
    print(f"  This run (defaults):  ~{this_run} calls")
    print(f"    + refresh followed: ~{this_run_with_follow_refresh} calls")
    print(f"  Warm weekly (caches filled): ~{warm} calls/run")
    print(f"  Full cold start (all {followed} artists, no cache): ~{cold_full} calls total")
    if uncached:
        print(
            f"  Days to finish cold queue at --max-artists-fetch {args.max_artists_fetch}: "
            f"~{days_at_cap} run(s)"
        )
    print()
    if not fits_budget:
        print(
            f"  WARNING: estimated ~{this_run} calls exceeds --spotify-daily-budget {budget}. "
            "Lower --max-artists-fetch or raise the budget."
        )
    elif uncached > args.max_artists_fetch:
        print(
            f"  Recommended cadence now: daily until ~{uncached} uncached artists are filled "
            f"(~{days_at_cap} days), then weekly."
        )
    else:
        print("  Recommended cadence: weekly (warm). Monthly also fine if you accept lag.")
    print(
        "  Tip: artist album pages are limited to 10 items each by Spotify; "
        "this estimate assumes ~1.5 pages/artist with early stop on older releases."
    )
    return 0


def self_test() -> None:
    assert listen_playlist_name(2026) == "2026 listen"
    assert artist_albums_cache_key("abc", 2026, "US") == "artist_albums:abc:2026:album:US"

    assert normalized_text("  American   Football ") == "american football"
    assert primary_artist_name("American Football, Someone Else") == "American Football"
    key_a = album_name_key("American Football", "American Football")
    key_b = album_name_key("  american   football ", "AMERICAN  FOOTBALL")
    key_c = album_name_key("American Football, Feat", "American Football")
    key_other = album_name_key("Different Band", "American Football")
    assert key_a == key_b == key_c
    assert key_a != key_other

    # Same title / primary artist, different Spotify album ids → treat as already on year lists.
    on_year = YearPlaylistIndex(
        album_ids={"medium-edition-id"},
        name_keys={album_name_key("American Football", "American Football")},
        track_count=10,
    )
    assert album_on_year_playlists(
        "medium-edition-id", "American Football", "American Football", on_year
    )
    assert album_on_year_playlists(
        "listen-candidate-id", "American Football", "American Football", on_year
    )
    assert not album_on_year_playlists(
        "other-id", "American Football", "Years", on_year
    )

    # Merge indexes accumulate tracks + keys.
    merged = YearPlaylistIndex()
    merged |= YearPlaylistIndex(album_ids={"a"}, name_keys={"k1"}, track_count=3)
    merged |= YearPlaylistIndex(album_ids={"b"}, name_keys={"k2"}, track_count=2)
    assert merged.album_ids == {"a", "b"}
    assert merged.name_keys == {"k1", "k2"}
    assert merged.track_count == 5

    est = estimate_calls(591, cached_discographies=0, max_artists_fetch=40)
    assert est["uncached_artists"] == 591
    assert est["fetch_this_run"] == 40
    this_run = sum_estimate(
        est,
        "auth_and_me",
        "year_playlist_scan",
        "discography_calls_this_run",
        "new_album_tracks",
        "playlist_write",
    )
    assert 50 < this_run < 200
    warm_est = estimate_calls(591, cached_discographies=591, max_artists_fetch=40)
    warm = sum_estimate(
        warm_est,
        "auth_and_me",
        "year_playlist_scan",
        "warm_discography_calls",
        "new_album_tracks",
        "playlist_write",
    )
    assert warm < 80
    print("self-test OK")
    print(f"  example 591 follows, cold first run (cap 40): ~{this_run} calls")
    print(f"  example 591 follows, warm weekly: ~{warm} calls")
    print(f"  album_name_key American Football example: {key_a!r}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, default=datetime.now().year)
    parser.add_argument(
        "--name-style",
        choices=("spaced", "underscore"),
        default="spaced",
        help="How year light/medium/heavy playlists are named (must match year sync)",
    )
    parser.add_argument("--market", default="US")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_PATH)
    parser.add_argument("--cache-path", type=Path, default=DEFAULT_CACHE_PATH)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument(
        "--album-cache-hours",
        type=float,
        default=DEFAULT_ALBUM_CACHE_HOURS,
        help=f"TTL for discography + album track caches (default {DEFAULT_ALBUM_CACHE_HOURS:g}h)",
    )
    parser.add_argument("--spotify-sleep", type=float, default=DEFAULT_SPOTIFY_SLEEP)
    parser.add_argument(
        "--max-artists-fetch",
        type=int,
        default=DEFAULT_MAX_ARTISTS_FETCH,
        help=f"Max artists to fetch discographies for per run (default {DEFAULT_MAX_ARTISTS_FETCH})",
    )
    parser.add_argument(
        "--spotify-daily-budget",
        type=int,
        default=DEFAULT_SPOTIFY_DAILY_BUDGET,
        help=f"Max Spotify HTTP calls per UTC day for this tool (default {DEFAULT_SPOTIFY_DAILY_BUDGET})",
    )
    parser.add_argument(
        "--cache-only",
        action="store_true",
        help="Do not fetch new discographies/album tracks; rebuild playlist from caches",
    )
    parser.add_argument(
        "--refresh-followed",
        action="store_true",
        help="Force refresh followed-artists library cache (extra Spotify pages)",
    )
    parser.add_argument(
        "--estimate",
        action="store_true",
        help="Estimate calls from YOUR followed-artist count (library cache or live Spotify)",
    )
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if args.estimate:
        try:
            return print_personalized_estimate(args)
        except KeyboardInterrupt:
            print("\nInterrupted.", file=sys.stderr)
            return 130

    load_env_file(args.env_file)
    load_env_file(REPO_ROOT / ".env")
    try:
        return sync(
            year=args.year,
            name_style=args.name_style,
            market=args.market,
            dry_run=args.dry_run,
            cache_path=args.cache_path,
            data_dir=args.data_dir,
            album_cache_hours=args.album_cache_hours,
            spotify_sleep=args.spotify_sleep,
            max_artists_fetch=args.max_artists_fetch,
            spotify_daily_budget=args.spotify_daily_budget,
            cache_only=args.cache_only,
            refresh_followed=args.refresh_followed,
        )
    except SpotifyRateLimitError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
