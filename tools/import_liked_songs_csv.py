#!/usr/bin/env python3
"""Import a Liked Songs CSV into drive/spotify_library_cache/library.json (0 Spotify calls).

Writes cache key `liked_library_scan` in the same shape as fetch_liked_artists():
  primary_counts, primary_meta, liked_uris, liked_track_ids

Also prints / writes an artist × liked-song count table.

Examples:
  python tools/import_liked_songs_csv.py "drive/spotify_library_cache/Liked_Songs.csv"
  python tools/import_liked_songs_csv.py "C:/Users/you/Downloads/Liked_Songs (4).csv" --min-liked 4
  python tools/import_liked_songs_csv.py Liked_Songs.csv --all --csv-out drive/spotify_library_cache/liked_artist_counts.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from spotify_json_cache import library_cache  # noqa: E402
from sync_spotify_year_playlists import REPO_ROOT  # noqa: E402

DEFAULT_CSV_CANDIDATES = [
    REPO_ROOT / "drive" / "spotify_library_cache" / "Liked_Songs.csv",
    REPO_ROOT / "drive" / "spotify_library_cache" / "Liked_Songs (4).csv",
    REPO_ROOT / "Liked_Songs.csv",
    REPO_ROOT / "Liked_Songs (4).csv",
]

# Common export column aliases (Exportify, Spotlistr, manual exports, etc.)
URI_COLS = ("track uri", "track_uri", "uri", "spotify uri", "spotify_uri", "track url", "url")
ID_COLS = ("track id", "track_id", "id", "spotify id", "spotify_id")
ARTIST_COLS = (
    "artist name(s)",
    "artist names",
    "artist name",
    "artist",
    "artists",
    "primary artist",
)
TRACK_COLS = ("track name", "track", "name", "song", "title")
ADDED_COLS = ("added at", "added_at", "liked at", "liked_at", "date added")


def _norm(header: str) -> str:
    return re.sub(r"\s+", " ", (header or "").strip().casefold())


def _pick(fieldnames: list[str], aliases: tuple[str, ...]) -> str | None:
    by_norm = {_norm(name): name for name in fieldnames if name}
    for alias in aliases:
        if alias in by_norm:
            return by_norm[alias]
    # substring fallback
    for norm_name, original in by_norm.items():
        for alias in aliases:
            if alias in norm_name:
                return original
    return None


def _track_id_from_uri(uri: str) -> str | None:
    text = (uri or "").strip()
    if not text:
        return None
    if text.startswith("spotify:track:"):
        return text.split(":")[-1] or None
    if "open.spotify.com/track/" in text:
        part = text.split("open.spotify.com/track/", 1)[1]
        return part.split("?", 1)[0].split("/", 1)[0] or None
    if re.fullmatch(r"[A-Za-z0-9]{22}", text):
        return text
    return None


def _primary_artist(raw: str) -> str:
    """First artist from Exportify-style 'A, B, C' or 'A; B' lists."""
    text = (raw or "").strip()
    if not text:
        return ""
    for sep in (";", ",", "/", "|", " feat.", " ft.", " featuring "):
        if sep in text.casefold() and sep in (";", ",", "/", "|"):
            return text.split(sep, 1)[0].strip()
    # feat. variants — keep full string as primary label if no clear multi-artist sep
    low = text.casefold()
    for sep in (" feat.", " ft.", " featuring "):
        if sep in low:
            idx = low.index(sep)
            return text[:idx].strip()
    return text


def _stable_artist_id(name: str) -> str:
    """Synthetic id when CSV has no Spotify artist id (CSV-only bootstrap)."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or "unknown"
    return f"csv:{slug}"


def load_liked_rows(path: Path) -> tuple[list[dict], dict[str, str]]:
    raw = path.read_text(encoding="utf-8-sig")
    sample = raw[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(raw.splitlines(), dialect=dialect)
    if not reader.fieldnames:
        raise SystemExit(f"No header row in {path}")

    uri_col = _pick(list(reader.fieldnames), URI_COLS)
    id_col = _pick(list(reader.fieldnames), ID_COLS)
    artist_col = _pick(list(reader.fieldnames), ARTIST_COLS)
    track_col = _pick(list(reader.fieldnames), TRACK_COLS)
    added_col = _pick(list(reader.fieldnames), ADDED_COLS)

    if not artist_col:
        raise SystemExit(
            f"Could not find an artist column in {path}.\n"
            f"Headers: {reader.fieldnames}\n"
            "Expected something like 'Artist Name(s)' / 'Artist' / 'Artists'."
        )
    if not uri_col and not id_col:
        raise SystemExit(
            f"Could not find a track URI/ID column in {path}.\n"
            f"Headers: {reader.fieldnames}\n"
            "Expected something like 'Track URI' / 'URI' / 'Track ID'."
        )

    cols = {
        "uri": uri_col or "",
        "id": id_col or "",
        "artist": artist_col,
        "track": track_col or "",
        "added": added_col or "",
    }
    rows: list[dict] = []
    for row in reader:
        artist_raw = (row.get(artist_col) or "").strip()
        if not artist_raw:
            continue
        uri = (row.get(uri_col) or "").strip() if uri_col else ""
        track_id = (row.get(id_col) or "").strip() if id_col else ""
        if not track_id:
            track_id = _track_id_from_uri(uri) or ""
        if not uri and track_id:
            uri = f"spotify:track:{track_id}"
        if not track_id and not uri:
            continue
        if not track_id:
            track_id = _track_id_from_uri(uri) or uri
        rows.append(
            {
                "track_id": track_id,
                "uri": uri or f"spotify:track:{track_id}",
                "artist": _primary_artist(artist_raw),
                "artist_raw": artist_raw,
                "track": (row.get(track_col) or "").strip() if track_col else "",
                "added_at": (row.get(added_col) or "").strip() if added_col else "",
            }
        )
    return rows, cols


def followed_name_index(cache) -> dict[str, dict]:
    """Map casefold artist name → {id, name} from followed_artists cache when present."""
    rows = cache.get("followed_artists", allow_stale=True)
    if not isinstance(rows, list):
        # allow_stale may still miss if key malformed; read raw
        raw = cache.data.get("followed_artists")
        if isinstance(raw, dict) and isinstance(raw.get("value"), list):
            rows = raw["value"]
        else:
            return {}
    out: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = (row.get("name") or "").strip()
        artist_id = row.get("artist_id") or row.get("id")
        if not name or not artist_id:
            continue
        out[name.casefold()] = {"id": artist_id, "name": name}
    return out


def build_scan(rows: list[dict], *, followed_by_name: dict[str, dict] | None = None) -> dict:
    followed_by_name = followed_by_name or {}
    counts: dict[str, set[str]] = defaultdict(set)
    meta: dict[str, dict] = {}
    liked_uris: dict[str, list[str]] = defaultdict(list)
    seen_uri: dict[str, set[str]] = defaultdict(set)
    liked_track_ids: list[str] = []
    seen_tracks: set[str] = set()
    matched_followed = 0

    for row in rows:
        track_id = row["track_id"]
        uri = row["uri"]
        name = row["artist"]
        if not name:
            continue
        followed = followed_by_name.get(name.casefold())
        if followed:
            artist_id = followed["id"]
            display_name = followed["name"]
            matched_followed += 1
        else:
            artist_id = _stable_artist_id(name)
            display_name = name
        if track_id not in seen_tracks:
            liked_track_ids.append(track_id)
            seen_tracks.add(track_id)
        counts[artist_id].add(track_id)
        meta[artist_id] = {"id": artist_id, "name": display_name}
        if uri and uri not in seen_uri[artist_id]:
            seen_uri[artist_id].add(uri)
            liked_uris[artist_id].append(uri)

    return {
        "primary_counts": {aid: len(ids) for aid, ids in counts.items()},
        "primary_meta": meta,
        "liked_uris": dict(liked_uris),
        "liked_track_ids": liked_track_ids,
        "source": "liked_songs_csv",
        "matched_followed_rows": matched_followed,
    }


def resolve_csv_path(explicit: Path | None) -> Path:
    if explicit is not None:
        path = explicit.expanduser()
        if not path.is_file():
            raise SystemExit(f"CSV not found: {path}")
        return path
    for candidate in DEFAULT_CSV_CANDIDATES:
        if candidate.is_file():
            return candidate
    raise SystemExit(
        "No Liked Songs CSV found.\n"
        "Copy your export to one of:\n"
        + "\n".join(f"  {p}" for p in DEFAULT_CSV_CANDIDATES)
        + "\nOr pass the path explicitly."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "csv_path",
        nargs="?",
        type=Path,
        default=None,
        help="Path to Liked Songs CSV (optional if placed under drive/spotify_library_cache/)",
    )
    parser.add_argument("--min-liked", type=int, default=4, help="Minimum liked songs for the filtered table (default 4)")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Print/write every artist with ≥1 liked song (not only --min-liked)",
    )
    parser.add_argument(
        "--csv-out",
        type=Path,
        default=REPO_ROOT / "drive" / "spotify_library_cache" / "liked_artist_counts.csv",
        help="Where to write the artist count table",
    )
    parser.add_argument(
        "--library-cache",
        type=Path,
        default=None,
        help="library.json path (default: drive/spotify_library_cache/library.json)",
    )
    args = parser.parse_args(argv)

    csv_path = resolve_csv_path(args.csv_path)
    rows, cols = load_liked_rows(csv_path)
    if not rows:
        raise SystemExit(f"No usable liked-song rows in {csv_path}")

    cache = library_cache(ttl_hours=-1, path=args.library_cache)  # ttl unused for set()
    followed_by_name = followed_name_index(cache)
    scan = build_scan(rows, followed_by_name=followed_by_name)
    cache.set("liked_library_scan", scan)

    counts = scan["primary_counts"]
    meta = scan["primary_meta"]
    table = [
        (meta[aid]["name"], int(count), aid)
        for aid, count in counts.items()
    ]
    table.sort(key=lambda row: (-row[1], row[0].casefold()))

    threshold = 1 if args.all else max(1, args.min_liked)
    filtered = [row for row in table if row[1] >= threshold]

    args.csv_out.parent.mkdir(parents=True, exist_ok=True)
    with args.csv_out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["artist", "liked_songs", "artist_id"])
        for name, count, aid in filtered:
            writer.writerow([name, count, aid])

    print(f"CSV: {csv_path}")
    print(f"Mapped columns: {cols}")
    print(f"Liked tracks imported: {len(scan['liked_track_ids'])}")
    print(f"Distinct primary artists: {len(table)}")
    print(f"Artists with liked_songs >= {threshold}: {len(filtered)}")
    if followed_by_name:
        print(
            f"Matched to followed Spotify IDs: {scan.get('matched_followed_rows', 0)} track-rows "
            f"({len(followed_by_name)} followed names available)"
        )
    else:
        print("No followed_artists in library cache yet — using csv: synthetic artist ids.")
    print(f"Cache updated: {cache.path} (key liked_library_scan)")
    print(f"Table written: {args.csv_out}")
    print()
    print(f"{'liked_songs':>11}  artist")
    for name, count, _aid in filtered[:50]:
        print(f"{count:>11}  {name}")
    if len(filtered) > 50:
        print(f"  … {len(filtered) - 50} more in {args.csv_out}")

    # Small machine-readable summary beside the cache.
    summary_path = cache.path.parent / "liked_import_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "csv": str(csv_path),
                "liked_tracks": len(scan["liked_track_ids"]),
                "artists_total": len(table),
                "artists_ge_threshold": len(filtered),
                "threshold": threshold,
                "table_csv": str(args.csv_out),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
