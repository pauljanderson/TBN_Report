#!/usr/bin/env python3
"""Build playlist of new albums from favorite artists you haven't engaged with yet.

Artist pool (union):
  - followed artists
  - artists with >= N liked songs (default 4)

Candidate albums:
  - released in --year (default: current calendar year)
  - album-type releases (not compilations / appears_on); optional singles via flag

Exclude an album if:
  - any of its tracks appear in your Spotify top tracks (short, medium, or long term), OR
  - you have liked any song on the album

Playlist: "Favorites not listened to yet"

Optimizations (to stay under Dev Mode limits):
  - Disk-cache followed + liked library, top albums, artist discographies, album tracks
  - Dirty-artist queue: new favorites first, then artists missing album cache
  - Per-run cap on how many artists to fetch discographies for (--max-artists-fetch)
  - Daily Spotify HTTP budget (--spotify-daily-budget); resume next run from cache
  - Persist kept/rejected albums so track lists aren't re-fetched every run

Examples:
  python tools/sync_spotify_favorites_unlistened.py --dry-run
  python tools/sync_spotify_favorites_unlistened.py
  python tools/sync_spotify_favorites_unlistened.py --max-artists-fetch 50 --spotify-daily-budget 200
  python tools/sync_spotify_favorites_unlistened.py --cache-only   # no new discography fetches
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
from spotify_json_cache import (  # noqa: E402
    JsonCache,
    library_cache,
)
from sync_spotify_upcoming_shows import (  # noqa: E402
    Artist,
    fetch_followed_artists,
    fetch_liked_artists,
    liked_track_ids_from_cache,
    merge_artists,
)
from sync_spotify_year_playlists import (  # noqa: E402
    DEFAULT_CACHE_PATH,
    DEFAULT_ENV_PATH,
    REPO_ROOT,
    build_client,
    find_or_create_playlist,
    load_env_file,
    release_year,
    replace_playlist_tracks,
)

PLAYLIST_NAME = "Favorites not listened to yet"
TOP_RANGES = ("short_term", "medium_term", "long_term")
DEFAULT_DATA_DIR = REPO_ROOT / "drive" / "spotify_favorites_unlistened"
DEFAULT_SPOTIFY_SLEEP = 0.35
DEFAULT_MAX_ARTISTS_FETCH = 60
DEFAULT_SPOTIFY_DAILY_BUDGET = 250
DEFAULT_ALBUM_CACHE_HOURS = 168.0  # 1 week for artist discographies / album tracks


@dataclass
class CandidateAlbum:
    album_id: str
    name: str
    artists: str
    release_date: str
    artist_ids: set[str]
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


def artist_albums_cache_key(artist_id: str, year: int, include_singles: bool, market: str) -> str:
    return f"artist_albums:{artist_id}:{year}:{'singles' if include_singles else 'album'}:{market}"


def load_state(path: Path) -> dict:
    if not path.is_file():
        return {
            "playlist_id": None,
            "playlist_name": PLAYLIST_NAME,
            "artist_pool_ids": [],
            "kept_albums": {},
            "rejected_albums": {},
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    data.setdefault("kept_albums", {})
    data.setdefault("rejected_albums", {})
    data.setdefault("artist_pool_ids", [])
    data.setdefault("playlist_name", PLAYLIST_NAME)
    return data


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fetch_top_album_ids(sp, cache: JsonCache, sleep_s: float, budget: SpotifyBudget) -> set[str]:
    cached = cache_get(cache, "top_album_ids", allow_stale=True)
    fresh = cache.get("top_album_ids")
    if isinstance(fresh, list):
        print(f"  cache hit: top-track albums ({len(fresh)})")
        return set(fresh)
    if isinstance(cached, list):
        print(f"  stale cache: top-track albums ({len(cached)}) — refresh when budget allows")
        # Try refresh; on budget/rate limit keep stale.
        try:
            album_ids: set[str] = set()
            for time_range in TOP_RANGES:
                page = spotify_call(
                    sp.current_user_top_tracks,
                    limit=50,
                    offset=0,
                    time_range=time_range,
                    budget=budget,
                )
                for track in page.get("items") or []:
                    album_id = ((track.get("album") or {}).get("id")) if track else None
                    if album_id:
                        album_ids.add(album_id)
                time.sleep(sleep_s)
            cache.set("top_album_ids", sorted(album_ids))
            return album_ids
        except (SpotifyBudgetExceeded, SpotifyRateLimitError) as exc:
            print(f"  ! could not refresh top albums ({exc}); using stale cache")
            return set(cached)

    album_ids = set()
    for time_range in TOP_RANGES:
        page = spotify_call(
            sp.current_user_top_tracks,
            limit=50,
            offset=0,
            time_range=time_range,
            budget=budget,
        )
        for track in page.get("items") or []:
            album_id = ((track.get("album") or {}).get("id")) if track else None
            if album_id:
                album_ids.add(album_id)
        time.sleep(sleep_s)
    cache.set("top_album_ids", sorted(album_ids))
    return album_ids


def fetch_liked_track_ids(sp, cache: JsonCache, lib_cache: JsonCache, sleep_s: float, budget: SpotifyBudget) -> set[str]:
    from_lib = liked_track_ids_from_cache(lib_cache)
    if from_lib is not None:
        print(f"  cache hit: liked tracks from library cache ({len(from_lib)})")
        return from_lib

    fresh = cache.get("liked_track_ids")
    if isinstance(fresh, list):
        print(f"  cache hit: liked tracks ({len(fresh)})")
        return set(fresh)

    stale = cache_get(cache, "liked_track_ids", allow_stale=True)
    if isinstance(stale, list):
        print(f"  stale liked-track cache ({len(stale)}); refresh via library cache next time")
        return set(stale)

    liked: set[str] = set()
    offset = 0
    while True:
        page = spotify_call(sp.current_user_saved_tracks, limit=50, offset=offset, budget=budget)
        items = page.get("items") or []
        if not items:
            break
        for entry in items:
            track = entry.get("track") or {}
            track_id = track.get("id")
            if track_id and not track.get("is_local"):
                liked.add(track_id)
        offset += len(items)
        if page.get("next") is None:
            break
        time.sleep(sleep_s)
    cache.set("liked_track_ids", sorted(liked))
    return liked


def rows_to_albums(rows: list, source_artist_id: str = "") -> list[CandidateAlbum]:
    out: list[CandidateAlbum] = []
    for row in rows:
        out.append(
            CandidateAlbum(
                album_id=row["album_id"],
                name=row["name"],
                artists=row["artists"],
                release_date=row["release_date"],
                artist_ids=set(row.get("artist_ids") or []),
                source_artist_id=source_artist_id or row.get("source_artist_id") or "",
            )
        )
    return out


def fetch_artist_year_albums(
    sp,
    artist: Artist,
    year: int,
    market: str,
    include_singles: bool,
    cache: JsonCache,
    sleep_s: float,
    budget: SpotifyBudget,
    *,
    allow_fetch: bool,
) -> tuple[list[CandidateAlbum], bool]:
    """Return (albums, fetched_from_network)."""
    cache_key = artist_albums_cache_key(artist.artist_id, year, include_singles, market)
    fresh = cache.get(cache_key)
    if isinstance(fresh, list):
        return rows_to_albums(fresh, artist.artist_id), False
    stale = cache_get(cache, cache_key, allow_stale=True)
    if isinstance(stale, list) and not allow_fetch:
        return rows_to_albums(stale, artist.artist_id), False
    if not allow_fetch:
        return [], False

    include_groups = "album,single" if include_singles else "album"
    albums: dict[str, CandidateAlbum] = {}
    offset = 0
    while True:
        page = spotify_call(
            sp.artist_albums,
            artist.artist_id,
            include_groups=include_groups,
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
            album_id = album["id"]
            if album_id in albums:
                continue
            artist_names = ", ".join(
                a.get("name", "") for a in (album.get("artists") or []) if a.get("name")
            )
            artist_ids = {a.get("id") for a in (album.get("artists") or []) if a.get("id")}
            albums[album_id] = CandidateAlbum(
                album_id=album_id,
                name=album.get("name") or "(unknown album)",
                artists=artist_names or artist.name,
                release_date=album.get("release_date") or "",
                artist_ids=artist_ids,
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
            "artist_ids": sorted(a.artist_ids),
            "source_artist_id": a.source_artist_id,
        }
        for a in albums.values()
    ]
    cache.set(cache_key, rows)
    return list(albums.values()), True


def album_track_ids_and_uris(
    sp,
    album_id: str,
    market: str,
    cache: JsonCache,
    sleep_s: float,
    budget: SpotifyBudget,
    *,
    allow_fetch: bool,
) -> tuple[list[str], list[str], bool]:
    cache_key = f"album_tracks:{album_id}:{market}"
    fresh = cache.get(cache_key)
    if isinstance(fresh, dict):
        return list(fresh.get("ids") or []), list(fresh.get("uris") or []), False
    stale = cache_get(cache, cache_key, allow_stale=True)
    if isinstance(stale, dict) and not allow_fetch:
        return list(stale.get("ids") or []), list(stale.get("uris") or []), False
    if not allow_fetch:
        return [], [], False

    ids: list[str] = []
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
            track_id = track.get("id")
            uri = track.get("uri")
            if track_id:
                ids.append(track_id)
            if uri:
                uris.append(uri)
        offset += len(items)
        if page.get("next") is None:
            break
        time.sleep(sleep_s)
    cache.set(cache_key, {"ids": ids, "uris": uris})
    return ids, uris, True


def prioritize_artists(
    artists: dict[str, Artist],
    prev_pool_ids: set[str],
    cache: JsonCache,
    year: int,
    include_singles: bool,
    market: str,
) -> list[Artist]:
    """New favorites first, then missing discography cache, then everyone else."""

    def has_album_cache(artist_id: str) -> bool:
        key = artist_albums_cache_key(artist_id, year, include_singles, market)
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


def sync(
    *,
    year: int,
    min_liked: int,
    market: str,
    include_singles: bool,
    dry_run: bool,
    cache_path: Path,
    data_dir: Path,
    cache_hours: float,
    album_cache_hours: float,
    spotify_sleep: float,
    max_artists_fetch: int,
    spotify_daily_budget: int,
    cache_only: bool,
    refresh_library: bool,
) -> int:
    sp = build_client(cache_path)
    budget = SpotifyBudget(data_dir / "spotify_budget.json", spotify_daily_budget)
    print(f"Authenticated as {spotify_call(sp.current_user, budget=budget).get('display_name')}")
    print(f"Spotify daily budget: {budget.used}/{budget.daily_budget} used so far today (UTC)")

    # Short TTL for library/top; longer for discographies (separate cache file).
    cache = JsonCache(data_dir / "spotify_cache.json", ttl_hours=cache_hours)
    album_cache = JsonCache(data_dir / "album_cache.json", ttl_hours=album_cache_hours)
    lib_cache = library_cache(ttl_hours=cache_hours)
    state_path = data_dir / "state.json"
    state = load_state(state_path)

    print(f"Caches: library={lib_cache.path}")
    print(f"        lists={cache.path} (ttl {cache_hours:g}h)")
    print(f"        albums={album_cache.path} (ttl {album_cache_hours:g}h)")

    print("Collecting favorite artists (followed / liked) …")
    followed = fetch_followed_artists(
        sp, cache=lib_cache, sleep_s=spotify_sleep, force_refresh=refresh_library
    )
    time.sleep(spotify_sleep)
    liked_artists, _liked_uris = fetch_liked_artists(
        sp,
        min_liked,
        cache=lib_cache,
        sleep_s=spotify_sleep,
        force_refresh=refresh_library,
    )
    artists = merge_artists(followed, liked_artists)
    prev_pool = set(state.get("artist_pool_ids") or [])
    new_count = sum(1 for aid in artists if aid not in prev_pool)
    print(
        f"Artist pool: {len(artists)} "
        f"(followed={len(followed)}, liked>={min_liked}={len(liked_artists)}, new_since_last={new_count})"
    )

    print("Loading top-track albums + liked track ids …")
    top_album_ids = fetch_top_album_ids(sp, cache, spotify_sleep, budget)
    liked_track_ids = fetch_liked_track_ids(sp, cache, lib_cache, spotify_sleep, budget)
    print(f"Top-track albums: {len(top_album_ids)}; liked tracks: {len(liked_track_ids)}")

    ordered = prioritize_artists(artists, prev_pool, album_cache, year, include_singles, market)
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
        key = artist_albums_cache_key(artist.artist_id, year, include_singles, market)
        already_cached = cache_get(album_cache, key, allow_stale=True) is not None
        allow_fetch = (not cache_only) and (not already_cached) and (fetched_artists < max_artists_fetch)
        try:
            albums, did_fetch = fetch_artist_year_albums(
                sp,
                artist,
                year,
                market,
                include_singles,
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
            # No cache and not allowed to fetch this run.
            continue

        for album in albums:
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
        f"Candidate {year} albums available this run: {len(candidates)} "
        f"(discography fetches={fetched_artists}, cache hits={cache_hits})"
    )

    # Re-validate previously kept albums cheaply (may now be liked / in tops).
    kept: dict[str, dict] = dict(state.get("kept_albums") or {})
    rejected: dict[str, str] = dict(state.get("rejected_albums") or {})

    for album_id in list(kept.keys()):
        if album_id in top_album_ids:
            kept.pop(album_id)
            rejected[album_id] = "top_tracks"
            continue
        track_ids = kept[album_id].get("track_ids") or []
        if any(tid in liked_track_ids for tid in track_ids):
            kept.pop(album_id)
            rejected[album_id] = "liked_track"

    skipped_top = 0
    skipped_liked = 0
    skipped_cached_reject = 0
    newly_kept = 0

    for album in sorted(candidates.values(), key=lambda a: (a.artists.casefold(), a.name.casefold())):
        if album.album_id in kept:
            continue
        if album.album_id in top_album_ids:
            rejected[album.album_id] = "top_tracks"
            skipped_top += 1
            continue
        if rejected.get(album.album_id) == "liked_track":
            # Still need to verify tracks if we never stored them — fall through if no track cache.
            pass

        allow_track_fetch = not cache_only
        try:
            track_ids, track_uris, _ = album_track_ids_and_uris(
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
            if cache_only:
                continue
            skipped_cached_reject += 1
            continue
        if any(tid in liked_track_ids for tid in track_ids):
            rejected[album.album_id] = "liked_track"
            skipped_liked += 1
            continue

        kept[album.album_id] = {
            "album_id": album.album_id,
            "name": album.name,
            "artists": album.artists,
            "release_date": album.release_date,
            "track_ids": track_ids,
            "track_uris": track_uris,
            "source_artist_id": album.source_artist_id,
        }
        newly_kept += 1
        print(f"  KEEP {album.artists} — {album.name} ({album.release_date}) [{len(track_uris)} tracks]")

    print(
        f"\nKept albums total: {len(kept)} (new this run: {newly_kept}); "
        f"skipped top={skipped_top}, liked={skipped_liked}, no-tracks={skipped_cached_reject}"
    )

    track_uris: list[str] = []
    seen: set[str] = set()
    for row in sorted(kept.values(), key=lambda r: ((r.get("artists") or "").casefold(), (r.get("name") or "").casefold())):
        for uri in row.get("track_uris") or []:
            if uri not in seen:
                seen.add(uri)
                track_uris.append(uri)

    print(f"Playlist {PLAYLIST_NAME!r}: {len(track_uris)} unique track(s) from {len(kept)} album(s).")

    state["artist_pool_ids"] = sorted(artists.keys())
    state["kept_albums"] = kept
    state["rejected_albums"] = rejected
    state["year"] = year
    state["market"] = market
    budget.save()

    if dry_run:
        save_state(state_path.with_suffix(".dry-run.json"), state)
        print(f"Dry run — wrote {state_path.with_suffix('.dry-run.json')}; playlist not modified.")
        if stopped_early:
            print("Stopped early on budget — re-run later to continue the queue.")
        return 0

    playlist_id = state.get("playlist_id") or find_or_create_playlist(sp, PLAYLIST_NAME, dry_run=False)
    assert playlist_id
    replace_playlist_tracks(sp, playlist_id, track_uris)
    state["playlist_id"] = playlist_id
    save_state(state_path, state)
    print(f"Updated playlist {PLAYLIST_NAME!r} ({playlist_id})")
    print(f"State: {state_path}")
    print(f"Spotify calls charged today: {budget.used}/{budget.daily_budget}")
    if stopped_early or (not cache_only and fetched_artists >= max_artists_fetch):
        remaining = sum(
            1
            for a in ordered
            if cache_get(
                album_cache,
                artist_albums_cache_key(a.artist_id, year, include_singles, market),
                allow_stale=True,
            )
            is None
        )
        print(
            f"Partial discography coverage — ~{remaining} artists still lack album cache. "
            "Re-run another day to continue the queue."
        )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, default=datetime.now().year)
    parser.add_argument("--min-liked", type=int, default=4)
    parser.add_argument("--market", default="US")
    parser.add_argument("--include-singles", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_PATH)
    parser.add_argument("--cache-path", type=Path, default=DEFAULT_CACHE_PATH)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument(
        "--cache-hours",
        type=float,
        default=24.0,
        help="TTL for library/top-track caches (default 24)",
    )
    parser.add_argument(
        "--album-cache-hours",
        type=float,
        default=DEFAULT_ALBUM_CACHE_HOURS,
        help=f"TTL for artist discography + album track caches (default {DEFAULT_ALBUM_CACHE_HOURS:g}h)",
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
        help="Do not fetch new discographies/album tracks; rebuild playlist from caches + state",
    )
    parser.add_argument(
        "--refresh-library",
        action="store_true",
        help="Force refresh followed + liked library caches",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_env_file(args.env_file)
    load_env_file(REPO_ROOT / ".env")
    try:
        return sync(
            year=args.year,
            min_liked=args.min_liked,
            market=args.market,
            include_singles=args.include_singles,
            dry_run=args.dry_run,
            cache_path=args.cache_path,
            data_dir=args.data_dir,
            cache_hours=args.cache_hours,
            album_cache_hours=args.album_cache_hours,
            spotify_sleep=args.spotify_sleep,
            max_artists_fetch=args.max_artists_fetch,
            spotify_daily_budget=args.spotify_daily_budget,
            cache_only=args.cache_only,
            refresh_library=args.refresh_library,
        )
    except SpotifyRateLimitError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 2
    except SpotifyBudgetExceeded as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
