#!/usr/bin/env python3
"""Build playlist of new albums from favorite artists you haven't engaged with yet.

Artist pool (union):
  - followed artists
  - artists with >= N liked songs (default 4)  ["liked a song >= 4 times" → 4+ likes]

Candidate albums:
  - released in --year (default: current calendar year)
  - album-type releases (not compilations / appears_on); optional singles via flag

Exclude an album if:
  - any of its tracks appear in your Spotify top tracks (short, medium, or long term), OR
  - you have liked any song on the album

Playlist: "Favorites not listened to yet"
  - rebuilt each run (replace contents) with all tracks from remaining albums

Caches Spotify list responses under drive/spotify_favorites_unlistened/ to reduce
rate-limit pressure on re-runs.

Examples:
  python tools/sync_spotify_favorites_unlistened.py --dry-run
  python tools/sync_spotify_favorites_unlistened.py
  python tools/sync_spotify_favorites_unlistened.py --year 2026 --include-singles
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from datetime import datetime
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


@dataclass
class CandidateAlbum:
    album_id: str
    name: str
    artists: str
    release_date: str
    artist_ids: set[str]


class SpotifyRateLimitError(RuntimeError):
    def __init__(self, retry_after: float | None = None, message: str = "") -> None:
        self.retry_after = retry_after
        hours = (retry_after or 0) / 3600.0
        detail = message or "Spotify rate limit (429)."
        if retry_after and retry_after > 0:
            detail += f" Retry-After ≈ {retry_after:.0f}s ({hours:.1f}h)."
        detail += " Stop the script and try again after that window; use cache on re-run."
        super().__init__(detail)


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
        # spotipy sometimes puts it in the message: "Retry will occur after: 80317 s"
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


def spotify_call(fn, *args, **kwargs):
    """Call a spotipy method; convert 429 into a fast, clear failure."""
    try:
        from spotipy.exceptions import SpotifyException
    except ImportError:
        SpotifyException = Exception  # type: ignore[misc, assignment]
    try:
        return fn(*args, **kwargs)
    except SpotifyException as exc:  # type: ignore[misc]
        status = getattr(exc, "http_status", None) or getattr(exc, "code", None)
        if status == 429 or "rate/request limit" in str(exc).casefold():
            raise SpotifyRateLimitError(_retry_after_seconds(exc), str(exc)) from exc
        raise


def fetch_top_album_ids(sp, cache: JsonCache, sleep_s: float) -> set[str]:
    cached = cache.get("top_album_ids")
    if isinstance(cached, list):
        print(f"  cache hit: top-track albums ({len(cached)})")
        return set(cached)

    album_ids: set[str] = set()
    for time_range in TOP_RANGES:
        page = spotify_call(sp.current_user_top_tracks, limit=50, offset=0, time_range=time_range)
        for track in page.get("items") or []:
            album_id = ((track.get("album") or {}).get("id")) if track else None
            if album_id:
                album_ids.add(album_id)
        time.sleep(sleep_s)
    cache.set("top_album_ids", sorted(album_ids))
    return album_ids


def fetch_liked_track_ids(sp, cache: JsonCache, lib_cache: JsonCache, sleep_s: float) -> set[str]:
    # Prefer the shared library scan cache (same data as followed/liked>=4).
    from_lib = liked_track_ids_from_cache(lib_cache)
    if from_lib is not None:
        print(f"  cache hit: liked tracks from library cache ({len(from_lib)})")
        return from_lib

    cached = cache.get("liked_track_ids")
    if isinstance(cached, list):
        print(f"  cache hit: liked tracks ({len(cached)})")
        return set(cached)

    liked: set[str] = set()
    offset = 0
    while True:
        page = spotify_call(sp.current_user_saved_tracks, limit=50, offset=offset)
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


def fetch_artist_year_albums(
    sp,
    artist: Artist,
    year: int,
    market: str,
    include_singles: bool,
    cache: JsonCache,
    sleep_s: float,
) -> list[CandidateAlbum]:
    cache_key = f"artist_albums:{artist.artist_id}:{year}:{'singles' if include_singles else 'album'}:{market}"
    cached = cache.get(cache_key)
    if isinstance(cached, list):
        return [
            CandidateAlbum(
                album_id=row["album_id"],
                name=row["name"],
                artists=row["artists"],
                release_date=row["release_date"],
                artist_ids=set(row.get("artist_ids") or []),
            )
            for row in cached
        ]

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
        }
        for a in albums.values()
    ]
    cache.set(cache_key, rows)
    return list(albums.values())


def album_track_ids_and_uris(
    sp, album_id: str, market: str, cache: JsonCache, sleep_s: float
) -> tuple[list[str], list[str]]:
    cache_key = f"album_tracks:{album_id}:{market}"
    cached = cache.get(cache_key)
    if isinstance(cached, dict):
        return list(cached.get("ids") or []), list(cached.get("uris") or [])

    ids: list[str] = []
    uris: list[str] = []
    offset = 0
    while True:
        page = spotify_call(sp.album_tracks, album_id, limit=50, offset=offset, market=market)
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
    return ids, uris


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
    spotify_sleep: float,
) -> int:
    sp = build_client(cache_path)
    me = spotify_call(sp.current_user)
    print(f"Authenticated as {me.get('display_name') or me.get('id')}")

    cache = JsonCache(data_dir / "spotify_cache.json", ttl_hours=cache_hours)
    lib_cache = library_cache(ttl_hours=cache_hours)
    print(f"Spotify response cache: {cache.path} (ttl {cache_hours:g}h)")
    print(f"Library cache: {lib_cache.path} (followed + liked>=N)")

    print("Collecting favorite artists (followed / liked) …")
    followed = fetch_followed_artists(sp, cache=lib_cache, sleep_s=spotify_sleep)
    time.sleep(spotify_sleep)
    liked_artists, _liked_uris = fetch_liked_artists(
        sp, min_liked, cache=lib_cache, sleep_s=spotify_sleep
    )
    artists = merge_artists(followed, liked_artists)
    print(
        f"Artist pool: {len(artists)} "
        f"(followed={len(followed)}, liked>={min_liked}={len(liked_artists)})"
    )

    print("Loading top-track albums (short / medium / long) and Liked Songs …")
    top_album_ids = fetch_top_album_ids(sp, cache, spotify_sleep)
    liked_track_ids = fetch_liked_track_ids(sp, cache, lib_cache, spotify_sleep)
    print(f"Top-track albums: {len(top_album_ids)}; liked tracks: {len(liked_track_ids)}")

    print(f"Scanning {year} albums for favorite artists …")
    candidates: dict[str, CandidateAlbum] = {}
    for index, artist in enumerate(sorted(artists.values(), key=lambda a: a.name.casefold()), start=1):
        try:
            for album in fetch_artist_year_albums(
                sp, artist, year, market, include_singles, cache, spotify_sleep
            ):
                candidates.setdefault(album.album_id, album)
        except SpotifyRateLimitError:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {artist.name}: {exc}")
        if index % 25 == 0:
            print(f"  … artists {index}/{len(artists)}; candidate albums so far: {len(candidates)}")
        time.sleep(spotify_sleep)

    print(f"Candidate {year} albums before filters: {len(candidates)}")

    kept: list[tuple[CandidateAlbum, list[str]]] = []
    skipped_top = 0
    skipped_liked = 0
    for album in sorted(candidates.values(), key=lambda a: (a.artists.casefold(), a.name.casefold())):
        if album.album_id in top_album_ids:
            skipped_top += 1
            continue
        try:
            track_ids, track_uris = album_track_ids_and_uris(
                sp, album.album_id, market, cache, spotify_sleep
            )
        except SpotifyRateLimitError:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"  ! album {album.artists} — {album.name}: {exc}")
            continue
        if not track_uris:
            continue
        if any(tid in liked_track_ids for tid in track_ids):
            skipped_liked += 1
            continue
        kept.append((album, track_uris))
        print(f"  KEEP {album.artists} — {album.name} ({album.release_date}) [{len(track_uris)} tracks]")
        time.sleep(spotify_sleep)

    print(
        f"\nKept {len(kept)} album(s); "
        f"skipped top-listened={skipped_top}, skipped any-liked={skipped_liked}"
    )

    track_uris: list[str] = []
    seen: set[str] = set()
    for _album, uris in kept:
        for uri in uris:
            if uri not in seen:
                seen.add(uri)
                track_uris.append(uri)

    print(f"Playlist {PLAYLIST_NAME!r} would contain {len(track_uris)} unique track(s).")

    if dry_run:
        print("Dry run — playlist not modified.")
        return 0

    playlist_id = find_or_create_playlist(sp, PLAYLIST_NAME, dry_run=False)
    assert playlist_id
    replace_playlist_tracks(sp, playlist_id, track_uris)
    print(f"Updated playlist {PLAYLIST_NAME!r} ({playlist_id})")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, default=datetime.now().year)
    parser.add_argument("--min-liked", type=int, default=4, help="Liked-song threshold for artist inclusion")
    parser.add_argument("--market", default="US")
    parser.add_argument(
        "--include-singles",
        action="store_true",
        help="Also include single/EP releases (default: full albums only)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_PATH)
    parser.add_argument("--cache-path", type=Path, default=DEFAULT_CACHE_PATH)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument(
        "--cache-hours",
        type=float,
        default=24.0,
        help="Reuse cached Spotify list responses for this many hours (default 24)",
    )
    parser.add_argument(
        "--spotify-sleep",
        type=float,
        default=DEFAULT_SPOTIFY_SLEEP,
        help=f"Seconds between Spotify calls (default {DEFAULT_SPOTIFY_SLEEP})",
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
            spotify_sleep=args.spotify_sleep,
        )
    except SpotifyRateLimitError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
