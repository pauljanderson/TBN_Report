#!/usr/bin/env python3
"""Fetch followed Spotify artists, save library cache, print the full list.

Creates/updates:
  drive/spotify_library_cache/library.json  (key: followed_artists)

Examples:
  python tools/dump_spotify_followed.py
  python tools/dump_spotify_followed.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from spotify_json_cache import DEFAULT_LIBRARY_CACHE_HOURS, library_cache  # noqa: E402
from sync_spotify_upcoming_shows import connect_spotify, fetch_followed_artists  # noqa: E402
from sync_spotify_year_playlists import (  # noqa: E402
    DEFAULT_CACHE_PATH,
    DEFAULT_ENV_PATH,
    REPO_ROOT,
    load_env_file,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_PATH)
    parser.add_argument("--cache-path", type=Path, default=DEFAULT_CACHE_PATH)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full followed_artists JSON array instead of names",
    )
    args = parser.parse_args(argv)

    load_env_file(args.env_file)
    load_env_file(REPO_ROOT / ".env")

    sp, display_name = connect_spotify(args.cache_path, required=True)
    assert sp is not None
    print(f"Authenticated as {display_name}", file=sys.stderr)

    lib_cache = library_cache(ttl_hours=DEFAULT_LIBRARY_CACHE_HOURS)
    print(f"Writing: {lib_cache.path}", file=sys.stderr)
    followed = fetch_followed_artists(sp, cache=lib_cache, sleep_s=0.2, force_refresh=True)
    rows = sorted(followed.values(), key=lambda a: a.name.casefold())
    print(f"Followed artists: {len(rows)}", file=sys.stderr)

    if args.json:
        payload = [
            {"artist_id": a.artist_id, "name": a.name, "sources": sorted(a.sources)}
            for a in rows
        ]
        print(json.dumps(payload, indent=2))
    else:
        for artist in rows:
            print(artist.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
