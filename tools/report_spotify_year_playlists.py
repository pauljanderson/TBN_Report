#!/usr/bin/env python3
"""Report albums currently on the year light/medium/heavy playlists.

Spotify's Web API does **not** expose lifetime play counts. This report includes
the closest available signals for each album on those playlists:

  - liked_tracks: how many tracks from the album are in Liked Songs
  - top_*_best_rank: best rank (1 = most played affinity) among your top-50
    tracks for short (~4 weeks), medium (~6 months), long (~1 year)
  - top_*_track_count: how many of the album's tracks appear in that top-50
  - recent_plays: how many times a track from the album appears in your last
    50 recently-played items (rolling window only)

Outputs a console summary plus CSV/Markdown under drive/ by default.

Re-auth note: first run may open the browser again to grant top/recent scopes.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Reuse auth + naming from the sync tool.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sync_spotify_year_playlists import (  # noqa: E402
    DEFAULT_CACHE_PATH,
    DEFAULT_ENV_PATH,
    REPO_ROOT,
    build_client,
    load_env_file,
    playlist_names,
    release_year,
)

TIME_RANGES = ("short_term", "medium_term", "long_term")
RANGE_LABEL = {
    "short_term": "short",
    "medium_term": "medium",
    "long_term": "long",
}


@dataclass
class PlaylistAlbum:
    album_id: str
    name: str
    artists: str
    release_date: str
    playlist: str
    track_ids_on_playlist: set[str] = field(default_factory=set)

    @property
    def year(self) -> int | None:
        return release_year(self.release_date)


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
    """Support both legacy `track` and Feb-2026 `item` playlist item shapes."""
    track = entry.get("track") or entry.get("item") or {}
    if track.get("type") and track.get("type") != "track":
        return {}
    return track


def fetch_playlist_albums(sp, playlist_name: str) -> dict[str, PlaylistAlbum]:
    playlist_id = find_playlist_id(sp, playlist_name)
    if not playlist_id:
        print(f"Playlist not found: {playlist_name!r}")
        return {}

    albums: dict[str, PlaylistAlbum] = {}
    offset = 0
    while True:
        page = sp.playlist_items(playlist_id, limit=50, offset=offset, additional_types=("track",))
        items = page.get("items") or []
        if not items:
            break
        for entry in items:
            track = playlist_entry_track(entry)
            if not track or track.get("is_local"):
                continue
            track_id = track.get("id")
            album = track.get("album") or {}
            album_id = album.get("id")
            if not track_id or not album_id:
                continue
            row = albums.get(album_id)
            if row is None:
                artists = ", ".join(
                    a.get("name", "") for a in (album.get("artists") or []) if a.get("name")
                )
                row = PlaylistAlbum(
                    album_id=album_id,
                    name=album.get("name") or "(unknown album)",
                    artists=artists or "(unknown artist)",
                    release_date=album.get("release_date") or "",
                    playlist=playlist_name,
                )
                albums[album_id] = row
            row.track_ids_on_playlist.add(track_id)
        offset += len(items)
        if page.get("next") is None:
            break
        time.sleep(0.05)
    return albums


def fetch_liked_counts(sp) -> dict[str, int]:
    """album_id -> number of liked tracks on that album."""
    counts: dict[str, set[str]] = defaultdict(set)
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
            album_id = (track.get("album") or {}).get("id")
            if track_id and album_id:
                counts[album_id].add(track_id)
        offset += len(items)
        if page.get("next") is None:
            break
        time.sleep(0.05)
    return {album_id: len(ids) for album_id, ids in counts.items()}


def fetch_top_by_album(sp) -> dict[str, dict[str, dict]]:
    """album_id -> {range_label: {best_rank, track_count, track_ids}}."""
    by_album: dict[str, dict[str, dict]] = defaultdict(dict)
    for time_range in TIME_RANGES:
        label = RANGE_LABEL[time_range]
        page = sp.current_user_top_tracks(limit=50, offset=0, time_range=time_range)
        items = page.get("items") or []
        for rank, track in enumerate(items, start=1):
            if not track:
                continue
            album_id = (track.get("album") or {}).get("id")
            track_id = track.get("id")
            if not album_id or not track_id:
                continue
            slot = by_album[album_id].setdefault(
                label, {"best_rank": rank, "track_ids": set()}
            )
            slot["best_rank"] = min(slot["best_rank"], rank)
            slot["track_ids"].add(track_id)
        time.sleep(0.05)
    # freeze sets to counts
    result: dict[str, dict[str, dict]] = {}
    for album_id, ranges in by_album.items():
        result[album_id] = {
            label: {
                "best_rank": data["best_rank"],
                "track_count": len(data["track_ids"]),
            }
            for label, data in ranges.items()
        }
    return result


def fetch_recent_plays_by_album(sp) -> dict[str, int]:
    """album_id -> appearances in last ~50 recently played items."""
    counts: dict[str, int] = defaultdict(int)
    page = sp.current_user_recently_played(limit=50)
    for entry in page.get("items") or []:
        track = entry.get("track") or {}
        album_id = (track.get("album") or {}).get("id")
        if album_id:
            counts[album_id] += 1
    return dict(counts)


def build_rows(
    playlist_albums: dict[str, dict[str, PlaylistAlbum]],
    liked: dict[str, int],
    top: dict[str, dict[str, dict]],
    recent: dict[str, int],
) -> list[dict]:
    rows: list[dict] = []
    for playlist_name, albums in playlist_albums.items():
        for album in sorted(albums.values(), key=lambda a: (a.artists.casefold(), a.name.casefold())):
            top_info = top.get(album.album_id, {})
            row = {
                "playlist": playlist_name,
                "artist": album.artists,
                "album": album.name,
                "release_date": album.release_date,
                "release_year": album.year or "",
                "tracks_on_playlist": len(album.track_ids_on_playlist),
                "liked_tracks": liked.get(album.album_id, 0),
                "recent_plays_last50": recent.get(album.album_id, 0),
            }
            for label in ("short", "medium", "long"):
                info = top_info.get(label) or {}
                row[f"top_{label}_best_rank"] = info.get("best_rank", "")
                row[f"top_{label}_track_count"] = info.get("track_count", 0)
            rows.append(row)
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, year: int, rows: list[dict]) -> None:
    lines = [
        f"# Spotify year playlist listening report — {year}",
        "",
        "Spotify does not expose lifetime play counts via the Web API.",
        "Columns below use proxies: Liked Songs counts, Top Tracks ranks",
        "(short ≈ 4 weeks, medium ≈ 6 months, long ≈ 1 year; rank 1 = strongest affinity),",
        "and appearances in your last 50 recently played items.",
        "",
    ]
    current = None
    for row in rows:
        if row["playlist"] != current:
            current = row["playlist"]
            lines += ["", f"## {current}", ""]
            lines.append(
                "| Artist | Album | Liked | Top short (rank / #tracks) | "
                "Top medium | Top long | Recent (last 50) |"
            )
            lines.append("|---|---|---:|---|---|---|---:|")
        def top_cell(label: str) -> str:
            rank = row[f"top_{label}_best_rank"]
            count = row[f"top_{label}_track_count"]
            if rank == "" or rank is None:
                return "—"
            return f"{rank} / {count}"

        lines.append(
            f"| {row['artist']} | {row['album']} | {row['liked_tracks']} | "
            f"{top_cell('short')} | {top_cell('medium')} | {top_cell('long')} | "
            f"{row['recent_plays_last50']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def print_summary(rows: list[dict]) -> None:
    if not rows:
        print("No albums found on the year playlists.")
        return
    current = None
    for row in rows:
        if row["playlist"] != current:
            current = row["playlist"]
            print(f"\n=== {current} ({sum(1 for r in rows if r['playlist'] == current)} albums) ===")
            print(
                f"{'liked':>5}  {'rec50':>5}  {'topS':>6}  {'topM':>6}  {'topL':>6}  Artist — Album"
            )
        def rank(label: str) -> str:
            value = row[f"top_{label}_best_rank"]
            return str(value) if value != "" else "-"

        print(
            f"{row['liked_tracks']:5d}  {row['recent_plays_last50']:5d}  "
            f"{rank('short'):>6}  {rank('medium'):>6}  {rank('long'):>6}  "
            f"{row['artist']} — {row['album']}"
        )


def run_report(year: int, name_style: str, output_dir: Path, cache_path: Path) -> int:
    names = playlist_names(year, name_style)
    sp = build_client(cache_path)
    me = sp.current_user()
    print(f"Authenticated as {me.get('display_name') or me.get('id')}")
    print(
        "Note: Spotify has no lifetime listen-count API. "
        "Report uses liked counts + top-track ranks + last-50 recent plays."
    )

    playlist_albums: dict[str, dict[str, PlaylistAlbum]] = {}
    for tier in ("light", "medium", "heavy"):
        playlist_name = names[tier]
        print(f"Reading {playlist_name!r} …")
        playlist_albums[playlist_name] = fetch_playlist_albums(sp, playlist_name)

    print("Scanning Liked Songs …")
    liked = fetch_liked_counts(sp)
    print("Fetching top tracks (short / medium / long) …")
    top = fetch_top_by_album(sp)
    print("Fetching recently played (last 50) …")
    recent = fetch_recent_plays_by_album(sp)

    rows = build_rows(playlist_albums, liked, top, recent)
    print_summary(rows)

    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = output_dir / f"spotify_year_playlist_report_{year}_{stamp}.csv"
    md_path = output_dir / f"spotify_year_playlist_report_{year}_{stamp}.md"
    write_csv(csv_path, rows)
    write_markdown(md_path, year, rows)
    print(f"\nWrote {csv_path}")
    print(f"Wrote {md_path}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, default=datetime.now().year)
    parser.add_argument("--name-style", choices=("spaced", "underscore"), default="spaced")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "drive" / "spotify_year_playlist_report",
    )
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_PATH)
    parser.add_argument("--cache-path", type=Path, default=DEFAULT_CACHE_PATH)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_env_file(args.env_file)
    load_env_file(REPO_ROOT / ".env")
    try:
        return run_report(args.year, args.name_style, args.output_dir, args.cache_path)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
