#!/usr/bin/env python3
"""Create read-only Spotify playlist add/remove tasks from CSV exports."""

from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PLAYLISTS = ("heavy", "medium", "light")
FIELD_ALIASES = {
    "track_id": ("track uri", "track id", "spotify track uri", "spotify uri", "uri"),
    "album_id": ("album uri", "album id", "spotify album uri", "spotify album id"),
    "track": ("track name", "track", "name", "song name", "title"),
    "album": ("album name", "album", "release name"),
    "artist": (
        "artist name(s)",
        "artist names",
        "artist name",
        "artists",
        "artist",
    ),
    "album_artist": (
        "album artist name(s)",
        "album artist names",
        "album artist",
    ),
    "release": (
        "release date",
        "album release date",
        "release year",
        "album release year",
        "year",
    ),
}


@dataclass(frozen=True)
class Album:
    key: str
    artist: str
    name: str
    year: int | None
    album_id: str


@dataclass(frozen=True)
class Task:
    action: str
    playlist: str
    album: Album
    liked_count: int


def normalized_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def normalized_text(value: str) -> str:
    """Normalize case and whitespace only, preserving edition punctuation."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def clean_id(value: str, kind: str) -> str:
    value = value.strip()
    if not value:
        return ""
    match = re.search(rf"(?:spotify:{kind}:|open\.spotify\.com/{kind}/)([A-Za-z0-9]+)", value)
    return match.group(1) if match else value


def release_year(value: str) -> int | None:
    match = re.match(r"\s*(\d{4})", value or "")
    return int(match.group(1)) if match else None


def suffix_number(path: Path) -> int:
    match = re.search(r" \((\d+)\)\.csv$", path.name, re.IGNORECASE)
    return int(match.group(1)) if match else 0


def select_latest(input_dir: Path, logical_name: str) -> Path | None:
    escaped = re.escape(logical_name)
    pattern = re.compile(rf"^{escaped}(?: \((\d+)\))?\.csv$", re.IGNORECASE)
    matches = [p for p in input_dir.iterdir() if p.is_file() and pattern.fullmatch(p.name)]
    if not matches:
        return None
    return max(matches, key=lambda p: (p.stat().st_mtime_ns, suffix_number(p), p.name.casefold()))


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise ValueError("CSV has no header row")
            return list(reader), reader.fieldnames
    except UnicodeDecodeError:
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise ValueError("CSV has no header row")
            return list(reader), reader.fieldnames


def field_map(headers: Iterable[str], path: Path) -> dict[str, str | None]:
    available = {normalized_header(header): header for header in headers}
    result: dict[str, str | None] = {}
    for logical, aliases in FIELD_ALIASES.items():
        result[logical] = next(
            (available[normalized_header(alias)] for alias in aliases if normalized_header(alias) in available),
            None,
        )
    missing = [name for name in ("track", "album", "release") if not result[name]]
    if not result["artist"] and not result["album_artist"]:
        missing.append("artist or album artist")
    if missing:
        raise ValueError(
            f"{path.name}: missing required field(s) {', '.join(missing)}; "
            f"headers were: {', '.join(headers)}"
        )
    return result


def value(row: dict[str, str], fields: dict[str, str | None], logical: str) -> str:
    header = fields[logical]
    return (row.get(header, "") if header else "") or ""


def primary_artist(row: dict[str, str], fields: dict[str, str | None]) -> str:
    album_artist = value(row, fields, "album_artist").strip()
    track_artists = value(row, fields, "artist").strip()
    # Exportify separates multiple track artists with semicolons. When no
    # album-artist field exists, the first listed artist is the best available
    # stable proxy for the primary album artist across featured tracks.
    return album_artist or track_artists.split(";", 1)[0].strip()


def album_from_row(row: dict[str, str], fields: dict[str, str | None]) -> Album | None:
    name = value(row, fields, "album").strip()
    artist = primary_artist(row, fields)
    if not name or not artist:
        return None
    album_id = clean_id(value(row, fields, "album_id"), "album")
    fallback = f"{normalized_text(artist)}\x1f{normalized_text(name)}"
    key = f"id:{album_id}" if album_id else f"text:{fallback}"
    return Album(key, artist, name, release_year(value(row, fields, "release")), album_id)


def track_pair(row: dict[str, str], fields: dict[str, str | None]) -> tuple[str, str] | None:
    """Edition-independent song identity: normalized primary artist + track name.

    Deliberately excludes album name and track URI so the same song counts once
    whether it was liked/listed via a single or via the full album.
    """
    artist = primary_artist(row, fields)
    track = value(row, fields, "track").strip()
    if not artist or not track:
        return None
    return (normalized_text(artist), normalized_text(track))


def desired_albums(
    rows: list[dict[str, str]], fields: dict[str, str | None], year: int, warnings: list[str]
) -> tuple[dict[str, Album], dict[str, int], dict[str, set[str]], dict[str, set[tuple[str, str]]]]:
    seen_tracks: set[tuple[str, str]] = set()
    albums: dict[str, Album] = {}
    liked_tracks: dict[str, set[tuple[str, str]]] = defaultdict(set)
    skipped_incomplete = 0
    duplicate_editions = 0
    for row in rows:
        album = album_from_row(row, fields)
        pair = track_pair(row, fields)
        if album is None or pair is None:
            skipped_incomplete += 1
            continue
        if album.year != year:
            continue
        if pair in seen_tracks:
            duplicate_editions += 1
            continue
        seen_tracks.add(pair)
        albums.setdefault(album.key, album)
        liked_tracks[album.key].add(pair)
    if skipped_incomplete:
        warnings.append(f"Skipped {skipped_incomplete} liked-song row(s) missing artist, album, or track name.")
    if duplicate_editions:
        warnings.append(
            f"Deduplicated {duplicate_editions} liked track(s) by artist + track name "
            "(same song liked via multiple editions counts once)."
        )

    counts = {key: len(tracks) for key, tracks in liked_tracks.items()}
    desired: dict[str, set[str]] = {name: set() for name in PLAYLISTS}
    for key, count in counts.items():
        desired["heavy" if count >= 4 else "medium" if count >= 2 else "light"].add(key)
    return albums, counts, desired, dict(liked_tracks)


def current_albums(
    path: Path | None, playlist: str, warnings: list[str]
) -> tuple[dict[str, Album], dict[str, set[tuple[str, str]]], bool]:
    """Return albums on the playlist, each album's track pairs, and whether album IDs exist."""
    if path is None:
        warnings.append(f"Missing {playlist} playlist export; treating it as empty.")
        return {}, {}, False
    rows, headers = read_csv(path)
    fields = field_map(headers, path)
    albums: dict[str, Album] = {}
    album_tracks: dict[str, set[tuple[str, str]]] = defaultdict(set)
    skipped = 0
    for row in rows:
        album = album_from_row(row, fields)
        if album is None:
            skipped += 1
            continue
        albums.setdefault(album.key, album)
        pair = track_pair(row, fields)
        if pair is not None:
            album_tracks[album.key].add(pair)
    if skipped:
        warnings.append(f"{path.name}: skipped {skipped} row(s) missing artist or album.")
    return albums, dict(album_tracks), bool(fields["album_id"])


def create_tasks(
    albums: dict[str, Album],
    counts: dict[str, int],
    desired: dict[str, set[str]],
    liked_tracks: dict[str, set[tuple[str, str]]],
    current: dict[str, dict[str, Album]],
    current_tracks: dict[str, dict[str, set[tuple[str, str]]]],
    warnings: list[str],
) -> list[Task]:
    # A liked song's desired tier, independent of which album edition carries it.
    pair_tier: dict[tuple[str, str], str] = {}
    for playlist in PLAYLISTS:
        for key in desired[playlist]:
            for pair in liked_tracks.get(key, set()):
                pair_tier[pair] = playlist

    tasks: list[Task] = []
    suppressed_adds = 0
    suppressed_removes = 0
    for playlist in PLAYLISTS:
        current_keys = set(current[playlist])
        playlist_pairs = set().union(*current_tracks[playlist].values()) if current_tracks[playlist] else set()
        for key in current_keys - desired[playlist]:
            album = albums.get(key, current[playlist][key])
            # Conservative removal: keep the album if it carries any liked song
            # whose desired tier is this playlist (single vs full-album naming
            # mismatch means the song is already correctly represented here).
            if any(pair_tier.get(pair) == playlist for pair in current_tracks[playlist].get(key, set())):
                suppressed_removes += 1
                continue
            tasks.append(Task("REMOVE", playlist, album, counts.get(key, 0)))
        for key in desired[playlist] - current_keys:
            # Track-level check: if any liked track of this album already exists
            # on the playlist under any album (e.g. single vs full album), the
            # song is already represented and no add is needed.
            if liked_tracks.get(key, set()) & playlist_pairs:
                suppressed_adds += 1
                continue
            tasks.append(Task("ADD", playlist, albums[key], counts[key]))
    if suppressed_adds:
        warnings.append(
            f"Suppressed {suppressed_adds} ADD task(s) whose liked track(s) already appear on the "
            "target playlist under a different album edition."
        )
    if suppressed_removes:
        warnings.append(
            f"Suppressed {suppressed_removes} REMOVE task(s) for playlist albums that carry liked "
            "track(s) belonging on that playlist (edition naming mismatch)."
        )
    return sorted(
        tasks,
        key=lambda item: (
            PLAYLISTS.index(item.playlist),
            0 if item.action == "REMOVE" else 1,
            normalized_text(item.album.artist),
            normalized_text(item.album.name),
        ),
    )


def write_csv(path: Path, tasks: list[Task], year: int) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("action", "playlist", "artist", "album", "liked_count", "release_year", "album_id"),
        )
        writer.writeheader()
        for task in tasks:
            writer.writerow(
                {
                    "action": task.action,
                    "playlist": f"{year}_{task.playlist}",
                    "artist": task.album.artist,
                    "album": task.album.name,
                    "liked_count": task.liked_count,
                    "release_year": task.album.year or "",
                    "album_id": task.album.album_id,
                }
            )


def write_markdown(
    path: Path,
    year: int,
    selected: dict[str, Path | None],
    desired: dict[str, set[str]],
    tasks: list[Task],
    warnings: list[str],
) -> None:
    lines = [f"# Spotify playlist tasks — {year}", "", "This report is read-only; apply these tasks manually in Spotify.", ""]
    lines += ["## Selected source files", ""]
    for logical, source in selected.items():
        lines.append(f"- `{logical}`: `{source}`" if source else f"- `{logical}`: **MISSING**")
    lines += ["", "## Summary", ""]
    for playlist in PLAYLISTS:
        adds = sum(t.playlist == playlist and t.action == "ADD" for t in tasks)
        removes = sum(t.playlist == playlist and t.action == "REMOVE" for t in tasks)
        lines.append(
            f"- `{year}_{playlist}`: {len(desired[playlist])} desired album(s); "
            f"{adds} ADD, {removes} REMOVE"
        )
    if warnings:
        lines += ["", "## Warnings / data caveats", ""]
        lines += [f"- {warning}" for warning in warnings]
    for playlist in PLAYLISTS:
        lines += ["", f"## {year}_{playlist}", ""]
        playlist_tasks = [task for task in tasks if task.playlist == playlist]
        for action in ("REMOVE", "ADD"):
            lines += [f"### {action}", ""]
            action_tasks = [task for task in playlist_tasks if task.action == action]
            if not action_tasks:
                lines.append("- None")
            for task in action_tasks:
                year_text = task.album.year if task.album.year is not None else "unknown"
                lines.append(
                    f"- {task.album.artist} — {task.album.name} "
                    f"(liked: {task.liked_count}, release year: {year_text})"
                )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2026, help="Calendar release year (default: 2026)")
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path.home() / "Downloads",
        help="Directory containing Spotify CSV exports (default: user's Downloads)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=repo_root / "drive" / "spotify_playlist_tasks",
        help="Output directory (default: repo drive/spotify_playlist_tasks)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_dir = args.input_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    if not input_dir.is_dir():
        print(f"ERROR: input directory does not exist: {input_dir}", file=sys.stderr)
        return 2

    selected: dict[str, Path | None] = {
        "Liked_Songs": select_latest(input_dir, "Liked_Songs"),
        **{f"{args.year}_{name}": select_latest(input_dir, f"{args.year}_{name}") for name in PLAYLISTS},
    }
    liked_path = selected["Liked_Songs"]
    if liked_path is None:
        print("ERROR: no Liked_Songs[ (N)].csv export found.", file=sys.stderr)
        return 2

    warnings: list[str] = []
    try:
        liked_rows, liked_headers = read_csv(liked_path)
        liked_fields = field_map(liked_headers, liked_path)
        albums, counts, desired, liked_tracks = desired_albums(liked_rows, liked_fields, args.year, warnings)
        current: dict[str, dict[str, Album]] = {}
        current_tracks: dict[str, dict[str, set[tuple[str, str]]]] = {}
        album_id_sources = bool(liked_fields["album_id"])
        for playlist in PLAYLISTS:
            current[playlist], current_tracks[playlist], has_album_id = current_albums(
                selected[f"{args.year}_{playlist}"], playlist, warnings
            )
            album_id_sources = album_id_sources or has_album_id
    except (OSError, csv.Error, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not album_id_sources:
        warnings.append(
            "Exports contain no album ID/URI column. Album identity falls back to "
            "case/whitespace-normalized primary artist + album name (the first semicolon-separated track artist "
            "when album artist is absent); distinct editions with identical text cannot be distinguished."
        )

    tasks = create_tasks(albums, counts, desired, liked_tracks, current, current_tracks, warnings)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"spotify_playlist_tasks_{args.year}.md"
    csv_path = output_dir / f"spotify_playlist_tasks_{args.year}.csv"
    write_markdown(report_path, args.year, selected, desired, tasks, warnings)
    write_csv(csv_path, tasks, args.year)

    print("Selected source files:")
    for logical, source in selected.items():
        print(f"  {logical}: {source.name if source else 'MISSING'}")
    print("Desired albums and tasks:")
    for playlist in PLAYLISTS:
        adds = sum(t.playlist == playlist and t.action == "ADD" for t in tasks)
        removes = sum(t.playlist == playlist and t.action == "REMOVE" for t in tasks)
        print(f"  {args.year}_{playlist}: desired={len(desired[playlist])}, add={adds}, remove={removes}")
    for warning in warnings:
        print(f"WARNING: {warning}")
    print(f"Markdown report: {report_path}")
    print(f"Task CSV: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
