#!/usr/bin/env python3
"""Sync Spotify playlists from Liked Songs for a release year.

Buckets (per album released in --year):
  1 liked track  -> "{year} light"
  2-3 liked      -> "{year} medium"
  4+ liked      -> "{year} heavy"

Each playlist is filled with *all* tracks from albums in that bucket (not only
the liked ones). Re-run after likes/unlikes; contents are replaced to match.

After writing light/medium/heavy, albums now on those playlists are scrubbed from
the companion "{year} listen" playlist (see tools/sync_spotify_year_listen.py).
Pass --skip-listen-scrub to disable that step.

Setup (one-time):
  1. Create an app at https://developer.spotify.com/dashboard
  2. Add Redirect URI http://127.0.0.1:8888/callback
  3. Copy tools/spotify.env.example -> secrets/spotify.env and fill credentials
  4. pip install -r requirements.txt
  5. python tools/sync_spotify_year_playlists.py --dry-run
  6. python tools/sync_spotify_year_playlists.py

Requires Spotify Premium for Web API access.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = REPO_ROOT / "secrets" / "spotify.env"
DEFAULT_CACHE_PATH = REPO_ROOT / "secrets" / ".spotify_token_cache"

SCOPES = (
    "user-library-read",
    "playlist-read-private",
    "playlist-modify-private",
    "playlist-modify-public",
    # Used by report / upcoming-shows tools (shared token cache).
    "user-top-read",
    "user-read-recently-played",
    "user-follow-read",
)

# Playlist display names for --name-style spaced (user default).
SPACED_NAMES = {
    "light": "{year} light",
    "medium": "{year} medium",
    "heavy": "{year} heavy",
}
# Matches tools/organize_spotify_playlists.py CSV task naming.
UNDERSCORE_NAMES = {
    "light": "{year}_light",
    "medium": "{year}_medium",
    "heavy": "{year}_heavy",
}


@dataclass
class AlbumBucket:
    album_id: str
    name: str
    artists: str
    release_date: str
    liked_track_ids: set[str] = field(default_factory=set)

    @property
    def liked_count(self) -> int:
        return len(self.liked_track_ids)

    @property
    def tier(self) -> str:
        n = self.liked_count
        if n >= 4:
            return "heavy"
        if n >= 2:
            return "medium"
        return "light"


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def resolve_credentials() -> tuple[str, str, str]:
    """Accept SPOTIFY_* or Spotipy's SPOTIPY_* names."""
    client_id = os.environ.get("SPOTIFY_CLIENT_ID") or os.environ.get("SPOTIPY_CLIENT_ID") or ""
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET") or os.environ.get("SPOTIPY_CLIENT_SECRET") or ""
    redirect = (
        os.environ.get("SPOTIFY_REDIRECT_URI")
        or os.environ.get("SPOTIPY_REDIRECT_URI")
        or "http://127.0.0.1:8888/callback"
    )
    return client_id, client_secret, redirect


def playlist_names(year: int, style: str) -> dict[str, str]:
    templates = UNDERSCORE_NAMES if style == "underscore" else SPACED_NAMES
    return {tier: template.format(year=year) for tier, template in templates.items()}


def release_year(release_date: str | None) -> int | None:
    if not release_date:
        return None
    text = release_date.strip()
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    return None


def chunked(items: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def build_client(cache_path: Path):
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
    except ImportError as exc:
        raise SystemExit(
            "spotipy is required. Install with: pip install 'spotipy>=2.26'\n"
            f"Import error: {exc}"
        ) from exc

    client_id, client_secret, redirect_uri = resolve_credentials()
    if not client_id or not client_secret:
        raise SystemExit(
            "Missing Spotify credentials.\n"
            f"Copy {REPO_ROOT / 'tools' / 'spotify.env.example'} to {DEFAULT_ENV_PATH}\n"
            "and set SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET."
        )

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    auth = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=" ".join(SCOPES),
        cache_path=str(cache_path),
        open_browser=True,
    )
    # retries=0 / status_retries=0: fail immediately on Spotify 429 (Retry-After can be
    # many hours). Callers catch and continue from caches instead of blocking the terminal.
    return spotipy.Spotify(auth_manager=auth, retries=0, status_retries=0, backoff_factor=0.0)


def fetch_liked_albums_for_year(sp, year: int) -> dict[str, AlbumBucket]:
    """Return album_id -> AlbumBucket for liked tracks whose album released in year."""
    albums: dict[str, AlbumBucket] = {}
    offset = 0
    limit = 50
    total_liked = 0
    while True:
        page = sp.current_user_saved_tracks(limit=limit, offset=offset)
        items = page.get("items") or []
        if not items:
            break
        for entry in items:
            track = entry.get("track") or {}
            if not track or track.get("is_local"):
                continue
            track_id = track.get("id")
            album = track.get("album") or {}
            album_id = album.get("id")
            if not track_id or not album_id:
                continue
            total_liked += 1
            if release_year(album.get("release_date")) != year:
                continue
            artists = ", ".join(a.get("name", "") for a in (album.get("artists") or []) if a.get("name"))
            bucket = albums.get(album_id)
            if bucket is None:
                bucket = AlbumBucket(
                    album_id=album_id,
                    name=album.get("name") or "(unknown album)",
                    artists=artists or "(unknown artist)",
                    release_date=album.get("release_date") or "",
                )
                albums[album_id] = bucket
            bucket.liked_track_ids.add(track_id)
        offset += len(items)
        if page.get("next") is None:
            break
        # Gentle pacing for large libraries
        time.sleep(0.05)
    print(f"Scanned {total_liked} liked track(s); {len(albums)} album(s) from {year}.")
    return albums


def fetch_album_track_uris(sp, album_id: str) -> list[str]:
    uris: list[str] = []
    offset = 0
    limit = 50
    while True:
        page = sp.album_tracks(album_id, limit=limit, offset=offset)
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
    return uris


def find_or_create_playlist(sp, name: str, dry_run: bool) -> str | None:
    """Return playlist id for exact name match among current user's playlists."""
    offset = 0
    limit = 50
    while True:
        page = sp.current_user_playlists(limit=limit, offset=offset)
        items = page.get("items") or []
        for playlist in items:
            if playlist and playlist.get("name") == name:
                return playlist.get("id")
        offset += len(items)
        if page.get("next") is None:
            break
    if dry_run:
        print(f"  [dry-run] would create playlist: {name!r}")
        return None
    # POST /me/playlists (POST /users/{id}/playlists was removed in Feb 2026).
    created = sp.current_user_playlist_create(
        name=name,
        public=False,
        description="Auto-synced from Liked Songs by sync_spotify_year_playlists.py",
    )
    print(f"  Created playlist: {name!r}")
    return created["id"]


def replace_playlist_tracks(sp, playlist_id: str, track_uris: list[str]) -> None:
    """Replace playlist contents (batched; Spotify max 100 URIs per call)."""
    if not track_uris:
        sp.playlist_replace_items(playlist_id, [])
        return
    first, *rest_batches = list(chunked(track_uris, 100))
    sp.playlist_replace_items(playlist_id, first)
    for batch in rest_batches:
        sp.playlist_add_items(playlist_id, batch)
        time.sleep(0.05)


def group_by_tier(albums: dict[str, AlbumBucket]) -> dict[str, list[AlbumBucket]]:
    groups: dict[str, list[AlbumBucket]] = {"light": [], "medium": [], "heavy": []}
    for album in albums.values():
        if album.liked_count < 1:
            continue
        groups[album.tier].append(album)
    for tier in groups:
        groups[tier].sort(key=lambda a: (a.artists.casefold(), a.name.casefold()))
    return groups


def print_plan(groups: dict[str, list[AlbumBucket]], names: dict[str, str]) -> None:
    for tier in ("light", "medium", "heavy"):
        albums = groups[tier]
        print(f"\n{names[tier]} — {len(albums)} album(s)")
        for album in albums:
            print(
                f"  [{album.liked_count} liked] {album.artists} — {album.name} "
                f"({album.release_date})"
            )


def sync(
    year: int,
    name_style: str,
    dry_run: bool,
    cache_path: Path,
    *,
    scrub_listen: bool = True,
) -> int:
    names = playlist_names(year, name_style)
    sp = build_client(cache_path)
    me = sp.current_user()
    print(f"Authenticated as {me.get('display_name') or me.get('id')}")

    albums = fetch_liked_albums_for_year(sp, year)
    groups = group_by_tier(albums)
    print_plan(groups, names)

    if dry_run:
        print("\nDry run only — no playlists were created or modified.")
        if scrub_listen:
            year_album_ids = {album.album_id for album in albums.values() if album.liked_count >= 1}
            print(
                f"Would scrub {len(year_album_ids)} year-playlist album id(s) "
                f"from {year} listen (if present)."
            )
        return 0

    for tier in ("light", "medium", "heavy"):
        playlist_name = names[tier]
        print(f"\nSyncing {playlist_name!r} …")
        playlist_id = find_or_create_playlist(sp, playlist_name, dry_run=False)
        assert playlist_id

        track_uris: list[str] = []
        seen: set[str] = set()
        for album in groups[tier]:
            for uri in fetch_album_track_uris(sp, album.album_id):
                if uri not in seen:
                    seen.add(uri)
                    track_uris.append(uri)
            time.sleep(0.05)

        replace_playlist_tracks(sp, playlist_id, track_uris)
        print(f"  Wrote {len(track_uris)} track(s) from {len(groups[tier])} album(s).")

    if scrub_listen:
        year_album_ids = {album.album_id for album in albums.values() if album.liked_count >= 1}
        print(f"\nScrubbing {year} listen of albums now on light/medium/heavy …")
        # Local import avoids a circular import at module load time.
        from sync_spotify_year_listen import scrub_listen_playlist_of_albums  # noqa: WPS433

        scrub_listen_playlist_of_albums(sp, year, year_album_ids, dry_run=False)

    print("\nDone.")
    return 0


def self_test() -> None:
    """Offline checks for bucketing / naming (no Spotify credentials needed)."""
    assert release_year("2026-03-01") == 2026
    assert release_year("2025") == 2025
    assert release_year("") is None

    names = playlist_names(2026, "spaced")
    assert names == {"light": "2026 light", "medium": "2026 medium", "heavy": "2026 heavy"}
    assert playlist_names(2026, "underscore")["heavy"] == "2026_heavy"

    a1 = AlbumBucket("a", "Album", "Artist", "2026-01-01", {"t1"})
    a2 = AlbumBucket("b", "Album", "Artist", "2026-01-01", {"t1", "t2"})
    a3 = AlbumBucket("c", "Album", "Artist", "2026-01-01", {"t1", "t2", "t3"})
    a4 = AlbumBucket("d", "Album", "Artist", "2026-01-01", {"t1", "t2", "t3", "t4"})
    assert a1.tier == "light"
    assert a2.tier == "medium"
    assert a3.tier == "medium"
    assert a4.tier == "heavy"

    groups = group_by_tier({"a": a1, "b": a2, "c": a3, "d": a4})
    assert [x.album_id for x in groups["light"]] == ["a"]
    assert [x.album_id for x in groups["medium"]] == ["b", "c"]
    assert [x.album_id for x in groups["heavy"]] == ["d"]
    print("self-test OK")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--year",
        type=int,
        default=datetime.now().year,
        help="Album release calendar year (default: current year)",
    )
    parser.add_argument(
        "--name-style",
        choices=("spaced", "underscore"),
        default="spaced",
        help='Playlist names: spaced="2026 light" / "2026 medium" / "2026 heavy" (default); '
        'underscore="2026_light" (matches CSV organizer)',
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print bucket plan only; do not create or modify playlists",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_PATH,
        help=f"Env file with credentials (default: {DEFAULT_ENV_PATH})",
    )
    parser.add_argument(
        "--cache-path",
        type=Path,
        default=DEFAULT_CACHE_PATH,
        help=f"OAuth token cache path (default: {DEFAULT_CACHE_PATH})",
    )
    parser.add_argument(
        "--skip-listen-scrub",
        action="store_true",
        help='Do not remove matching albums from the "{year} listen" playlist after sync',
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run offline unit checks and exit",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    load_env_file(args.env_file)
    # Also allow a repo-root .env if present
    load_env_file(REPO_ROOT / ".env")
    try:
        return sync(
            args.year,
            args.name_style,
            args.dry_run,
            args.cache_path,
            scrub_listen=not args.skip_listen_scrub,
        )
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
