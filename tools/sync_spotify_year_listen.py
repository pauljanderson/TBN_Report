#!/usr/bin/env python3
"""Build "{year} listen" from followed-artist albums missing from year playlists.

Artist pool:
  - artists you follow

Candidate albums:
  - released in --year (default: current calendar year)
  - Spotify album-type releases only (not singles / appears_on)

Exclude an album if its album id already appears on any of:
  "{year} light" | "{year} medium" | "{year} heavy"

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
  Weekly is the sweet spot once the cache is warm (~40–120 calls/run). Cold start
  a large follow list over several days with --max-artists-fetch 40. Avoid stacking
  this on the same day as a full upcoming-shows or favorites-unlistened crawl.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
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


def playlist_album_ids(
    sp,
    playlist_id: str,
    *,
    budget: SpotifyBudget | None = None,
    sleep_s: float = 0.05,
) -> set[str]:
    """Album ids represented by tracks currently on a playlist."""
    album_ids: set[str] = set()
    offset = 0
    while True:
        page = spotify_call(
            sp.playlist_items,
            playlist_id,
            fields="items(track(album(id))),next",
            limit=100,
            offset=offset,
            budget=budget,
        )
        items = page.get("items") or []
        if not items:
            break
        for entry in items:
            track = entry.get("track") or {}
            album_id = ((track.get("album") or {}).get("id")) if track else None
            if album_id:
                album_ids.add(album_id)
        offset += len(items)
        if page.get("next") is None:
            break
        time.sleep(sleep_s)
    return album_ids


def year_playlist_album_ids(
    sp,
    year: int,
    name_style: str,
    *,
    budget: SpotifyBudget | None = None,
    sleep_s: float = 0.05,
) -> tuple[set[str], dict[str, str | None]]:
    """Return (album_ids on light/medium/heavy, playlist_id by tier)."""
    names = playlist_names(year, name_style)
    ids_by_tier: dict[str, str | None] = {}
    album_ids: set[str] = set()
    for tier, name in names.items():
        playlist_id = find_playlist_id(sp, name, budget=budget)
        ids_by_tier[tier] = playlist_id
        if not playlist_id:
            print(f"  missing playlist {name!r} — treating as empty")
            continue
        found = playlist_album_ids(sp, playlist_id, budget=budget, sleep_s=sleep_s)
        print(f"  {name!r}: {len(found)} album id(s)")
        album_ids |= found
    return album_ids, ids_by_tier


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
    while True:
        page = spotify_call(
            sp.artist_albums,
            artist.artist_id,
            include_groups="album",
            country=market,
            limit=50,
            offset=offset,
            budget=budget,
        )
        items = page.get("items") or []
        if not items:
            break
        for album in items:
            if not album or not album.get("id"):
                continue
            if release_year(album.get("release_date")) != year:
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
    dry_run: bool = False,
    budget: SpotifyBudget | None = None,
    sleep_s: float = 0.05,
    playlist_id: str | None = None,
) -> int:
    """Remove tracks whose album id is in album_ids from "{year} listen".

    Used by sync_spotify_year_playlists after it writes light/medium/heavy.
    Returns number of track URIs removed (0 if playlist missing / nothing to do).
    """
    if not album_ids:
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
            fields="items(track(uri,album(id))),next",
            limit=100,
            offset=offset,
            budget=budget,
        )
        items = page.get("items") or []
        if not items:
            break
        for entry in items:
            track = entry.get("track") or {}
            if not track:
                continue
            album_id = ((track.get("album") or {}).get("id")) if track else None
            uri = track.get("uri")
            if album_id in album_ids and uri:
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

    print(f"Reading album ids already on {year} light/medium/heavy …")
    on_year, _ = year_playlist_album_ids(
        sp, year, name_style, budget=budget, sleep_s=spotify_sleep
    )
    print(f"Year-playlist album ids: {len(on_year)}")

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
            if album.album_id in on_year:
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

    kept: dict[str, dict] = {}
    for album in sorted(
        candidates.values(), key=lambda a: (a.artists.casefold(), a.name.casefold())
    ):
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
    state["on_year_playlist_album_count"] = len(on_year)
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


def estimate_calls(followed: int, year_playlist_tracks: int, new_albums: int) -> dict[str, int]:
    """Rough HTTP call counts for planning (documented for --estimate)."""
    followed_pages = max(1, (followed + 49) // 50)
    # playlist list + 3 year playlists (assume ~100 tracks/page)
    year_pages = 3 + max(3, (year_playlist_tracks + 99) // 100)
    # warm: mostly cache; cold: 1 page per artist typical
    return {
        "auth_and_me": 1,
        "followed_refresh": followed_pages,
        "year_playlist_scan": year_pages + 5,
        "cold_discographies": followed,
        "warm_discographies": max(5, followed // 20),
        "new_album_tracks": max(new_albums, 1),
        "playlist_write": max(1, (new_albums * 10 + 99) // 100),
    }


def self_test() -> None:
    assert listen_playlist_name(2026) == "2026 listen"
    assert artist_albums_cache_key("abc", 2026, "US") == "artist_albums:abc:2026:album:US"
    est = estimate_calls(200, 300, 15)
    warm = (
        est["auth_and_me"]
        + est["year_playlist_scan"]
        + est["warm_discographies"]
        + est["new_album_tracks"]
        + est["playlist_write"]
    )
    cold = (
        est["auth_and_me"]
        + est["followed_refresh"]
        + est["year_playlist_scan"]
        + est["cold_discographies"]
        + est["new_album_tracks"]
        + est["playlist_write"]
    )
    assert warm < 100
    assert cold < 500
    print("self-test OK")
    print(f"  example warm (~200 follows): ~{warm} calls")
    print(f"  example cold (~200 follows): ~{cold} calls")


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
        help="Print call-count estimates for typical follow-list sizes and exit",
    )
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if args.estimate:
        print("Approximate Spotify HTTP calls (Development Mode — stay under your own budget):\n")
        for follows in (50, 100, 200, 400):
            est = estimate_calls(follows, year_playlist_tracks=follows, new_albums=max(5, follows // 20))
            warm = (
                est["auth_and_me"]
                + est["year_playlist_scan"]
                + est["warm_discographies"]
                + est["new_album_tracks"]
                + est["playlist_write"]
            )
            cold = (
                est["auth_and_me"]
                + est["followed_refresh"]
                + est["year_playlist_scan"]
                + est["cold_discographies"]
                + est["new_album_tracks"]
                + est["playlist_write"]
            )
            print(f"  {follows:>3} followed artists → warm ~{warm:>3} calls/run, cold ~{cold:>3} calls")
        print(
            "\nRecommended cadence: weekly (warm). "
            "Cold-start: daily for a few days with --max-artists-fetch 40 until caches fill, "
            "then weekly. Monthly also works if you do not mind a longer listen backlog. "
            "Default self-budget is 150 calls/UTC-day for this tool alone."
        )
        return 0

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
