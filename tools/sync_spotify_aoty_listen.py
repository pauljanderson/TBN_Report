#!/usr/bin/env python3
"""Append AOTY highest-rated albums to Spotify "{year} listen".

Ingest (v1 — no live scrape; Cloudflare blocks plain curl):
  1. Save AOTY highest-rated pages as .html or .md into
     drive/spotify_aoty_listen/pages/
     URLs look like:
       https://www.albumoftheyear.org/ratings/6-highest-rated/{year}/1
       …/{year}/2 … (max_pages from config, default 6 ≈ top 150)
  2. Or drop a pre-parsed rankings.json in the data dir.

Pipeline:
  parse pages → genre/score/reviews filter → exclude year light|medium|heavy
  and albums already on "{year} listen" → Spotify album search (strict
  album_name_key) → fetch album tracks → APPEND to "{year} listen".

State is written to drive/spotify_aoty_listen/state.json with source=aoty.
tools/sync_spotify_year_listen.py merges those kept albums when it rebuilds
the same playlist so AOTY adds are not wiped.

Config: copy tools/aoty_listen_config.example.json →
drive/spotify_aoty_listen/config.json

Examples:
  python tools/sync_spotify_aoty_listen.py --self-test
  python tools/sync_spotify_aoty_listen.py --dry-run
  python tools/sync_spotify_aoty_listen.py --year 2026

Call-budget guidance: defaults ~80 Spotify calls/UTC-day and
--max-albums-per-run 20. Do not stack with a cold year-listen sync the same day.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_aoty_highest_rated import (  # noqa: E402
    AotyListingRow,
    discover_listing_files,
    filter_by_genres,
    normalize_favorite_genres,
    page_number_from_path,
    parse_listing_file,
)
from spotify_json_cache import JsonCache  # noqa: E402
from sync_spotify_year_listen import (  # noqa: E402
    SpotifyBudget,
    SpotifyBudgetExceeded,
    SpotifyRateLimitError,
    YearPlaylistIndex,
    album_name_key,
    album_on_year_playlists,
    album_track_uris,
    artists_from_spotify_list,
    listen_playlist_name,
    playlist_album_index,
    primary_artist_name,
    spotify_call,
    year_playlist_album_ids,
)
from sync_spotify_year_playlists import (  # noqa: E402
    DEFAULT_CACHE_PATH,
    DEFAULT_ENV_PATH,
    REPO_ROOT,
    build_client,
    chunked,
    find_or_create_playlist,
    load_env_file,
)

DEFAULT_DATA_DIR = REPO_ROOT / "drive" / "spotify_aoty_listen"
DEFAULT_EXAMPLE_CONFIG = REPO_ROOT / "tools" / "aoty_listen_config.example.json"
DEFAULT_SPOTIFY_SLEEP = 0.35
DEFAULT_SPOTIFY_DAILY_BUDGET = 80
DEFAULT_MATCH_CACHE_HOURS = 336.0  # 14 days
DEFAULT_ALBUM_CACHE_HOURS = 336.0


# ---------------------------------------------------------------------------
# Config / genre helpers
# ---------------------------------------------------------------------------


def normalize_config_genres(raw: list) -> list[str]:
    """Dedupe + typo-fix favorite genres; preserve first-seen display form."""
    return normalize_favorite_genres([str(g) for g in raw if str(g).strip()])


def load_config(path: Path | None, example: Path) -> dict:
    """Load drive config, falling back to committed example."""
    candidates = [p for p in (path, example) if p is not None]
    data: dict = {}
    for candidate in candidates:
        if candidate.is_file():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                break
            except (OSError, json.JSONDecodeError) as exc:
                raise SystemExit(f"Invalid config JSON at {candidate}: {exc}") from exc
    if not data:
        raise SystemExit(
            f"No config found. Copy {example} → {DEFAULT_DATA_DIR / 'config.json'}"
        )
    genres = normalize_config_genres(list(data.get("favorite_genres") or []))
    data["favorite_genres"] = genres
    data.setdefault("genre_match", "any")
    data.setdefault("min_score", 70)
    data.setdefault("min_reviews", 5)
    data.setdefault("max_pages", 6)
    data.setdefault("max_albums_per_run", 20)
    data.setdefault("market", "US")
    data.setdefault("year", datetime.now().year)
    return data


def load_state(path: Path, year: int) -> dict:
    if not path.is_file():
        return {
            "playlist_id": None,
            "playlist_name": listen_playlist_name(year),
            "year": year,
            "kept_albums": {},
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    data.setdefault("kept_albums", {})
    data.setdefault("playlist_name", listen_playlist_name(year))
    data.setdefault("year", year)
    return data


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_aoty_kept_albums(data_dir: Path | None = None) -> dict[str, dict]:
    """Public helper for year-listen merge: source=aoty rows from state.json."""
    root = data_dir or DEFAULT_DATA_DIR
    path = root / "state.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    kept = data.get("kept_albums") or {}
    if not isinstance(kept, dict):
        return {}
    out: dict[str, dict] = {}
    for album_id, row in kept.items():
        if not isinstance(row, dict):
            continue
        source = str(row.get("source") or "aoty").casefold()
        if source != "aoty":
            continue
        aid = str(row.get("album_id") or album_id)
        if not aid:
            continue
        out[aid] = dict(row)
        out[aid]["album_id"] = aid
        out[aid]["source"] = "aoty"
    return out


def prune_aoty_state_against_year(
    data_dir: Path,
    year_index: YearPlaylistIndex,
) -> int:
    """Drop AOTY kept albums that now appear on year light/medium/heavy."""
    path = data_dir / "state.json"
    if not path.is_file():
        return 0
    try:
        raw_year = json.loads(path.read_text(encoding="utf-8")).get("year")
        year = int(raw_year) if raw_year else datetime.now().year
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        year = datetime.now().year
    state = load_state(path, year)
    kept = state.get("kept_albums") or {}
    if not isinstance(kept, dict):
        return 0
    removed = 0
    for album_id, row in list(kept.items()):
        if not isinstance(row, dict):
            kept.pop(album_id, None)
            removed += 1
            continue
        if album_on_year_playlists(
            str(row.get("album_id") or album_id),
            str(row.get("artists") or ""),
            str(row.get("name") or ""),
            year_index,
        ):
            kept.pop(album_id, None)
            removed += 1
    if removed:
        state["kept_albums"] = kept
        save_state(path, state)
    return removed


# ---------------------------------------------------------------------------
# Ingest / filter
# ---------------------------------------------------------------------------


def discover_page_files(pages_dir: Path, max_pages: int) -> list[Path]:
    """Discover *.html/*.md pages sorted by 'Page N' in the filename.

    Browser Save-as titles (e.g. 'The Best Albums of 2026 - …html',
    '… _ Page 2 - …html') do not need '6-highest-rated' in the name.
    Page 1 often has no 'Page 1' — treated as page 1.
    max_pages keeps files whose parsed page number is <= max_pages
    (so max_pages=6 uses pages 1–6 even if 16 were saved).
    """
    return discover_listing_files(pages_dir, max_pages=max_pages)


def ingest_rankings(
    *,
    pages_dir: Path,
    rankings_path: Path,
    max_pages: int,
) -> list[AotyListingRow]:
    """Parse saved pages and/or load rankings.json; write merged rankings.json."""
    by_key: dict[tuple[str, str], AotyListingRow] = {}

    if rankings_path.is_file():
        try:
            raw = json.loads(rankings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = []
        rows_raw = raw.get("rows") if isinstance(raw, dict) else raw
        if isinstance(rows_raw, list):
            for item in rows_raw:
                if not isinstance(item, dict):
                    continue
                try:
                    row = AotyListingRow(
                        rank=int(item.get("rank") or 0),
                        artist=str(item.get("artist") or ""),
                        album=str(item.get("album") or ""),
                        release_date=item.get("release_date"),
                        genres=list(item.get("genres") or []),
                        score=item.get("score"),
                        reviews=item.get("reviews"),
                    )
                except (TypeError, ValueError):
                    continue
                if row.artist and row.album:
                    by_key[(row.artist.casefold(), row.album.casefold())] = row

    page_files = discover_page_files(pages_dir, max_pages)
    for path in page_files:
        for row in parse_listing_file(path):
            key = (row.artist.casefold(), row.album.casefold())
            prev = by_key.get(key)
            if prev is None or (row.rank and (not prev.rank or row.rank < prev.rank)):
                by_key[key] = row

    rows = sorted(by_key.values(), key=lambda r: (r.rank or 10**9, r.artist, r.album))
    rankings_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "page_files": [str(p) for p in page_files],
        "count": len(rows),
        "rows": [asdict(r) for r in rows],
    }
    rankings_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return rows


def filter_candidates(
    rows: list[AotyListingRow],
    *,
    favorites: list[str],
    genre_match: str,
    min_score: int,
    min_reviews: int,
) -> list[AotyListingRow]:
    matched = filter_by_genres(rows, favorites, match=genre_match)
    out: list[AotyListingRow] = []
    for row in matched:
        if row.score is None or row.score < min_score:
            continue
        if row.reviews is None or row.reviews < min_reviews:
            continue
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# Spotify match
# ---------------------------------------------------------------------------


def match_cache_key(artist: str, album: str) -> str:
    return f"search:{album_name_key(artist, album)}"


def search_spotify_album(
    sp,
    artist: str,
    album: str,
    market: str,
    cache: JsonCache,
    budget: SpotifyBudget,
    *,
    allow_fetch: bool,
) -> dict | None:
    """Return Spotify album dict on strict name_key match, else None."""
    key = match_cache_key(artist, album)
    fresh = cache.get(key)
    if isinstance(fresh, dict):
        if fresh.get("miss"):
            return None
        return fresh.get("album")
    stale = None
    row = cache.data.get(key)
    if isinstance(row, dict) and "value" in row:
        stale = row["value"]
    if isinstance(stale, dict) and not allow_fetch:
        if stale.get("miss"):
            return None
        return stale.get("album")
    if not allow_fetch:
        return None

    primary = primary_artist_name(artist)
    query = f'album:"{album}" artist:"{primary}"'
    page = spotify_call(
        sp.search,
        q=query,
        type="album",
        limit=10,
        market=market,
        budget=budget,
    )
    items = ((page or {}).get("albums") or {}).get("items") or []
    target = album_name_key(artist, album)
    chosen = None
    for item in items:
        if not item or not item.get("id"):
            continue
        artists = artists_from_spotify_list(item.get("artists"))
        name = item.get("name") or ""
        if album_name_key(artists, name) == target:
            chosen = {
                "album_id": item["id"],
                "name": name,
                "artists": artists,
                "release_date": item.get("release_date") or "",
            }
            break
    if chosen is None:
        cache.set(key, {"miss": True, "query": query})
        return None
    cache.set(key, {"miss": False, "query": query, "album": chosen})
    return chosen


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


def sync(
    *,
    year: int,
    name_style: str,
    market: str,
    dry_run: bool,
    cache_path: Path,
    data_dir: Path,
    config: dict,
    spotify_sleep: float,
    spotify_daily_budget: int,
    max_albums_per_run: int,
    cache_only: bool,
) -> int:
    pages_dir = data_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    rankings_path = data_dir / "rankings.json"
    state_path = data_dir / "state.json"
    max_pages = int(config.get("max_pages") or 6)
    min_score = int(config.get("min_score") or 70)
    min_reviews = int(config.get("min_reviews") or 5)
    favorites = list(config.get("favorite_genres") or [])
    genre_match = str(config.get("genre_match") or "any")

    print(f"Config genres: {len(favorites)} (match={genre_match})")
    print(f"Thresholds: min_score={min_score} min_reviews={min_reviews} max_pages={max_pages}")
    print(f"Pages dir: {pages_dir}")
    print(
        "Save AOTY highest-rated HTML/MD into that folder "
        f"(browser Save Page As from …/ratings/6-highest-rated/{year}/1 .. /{max_pages}; "
        "any *.html title works — sorted by 'Page N', page 1 has no Page label). "
        f"max_pages={max_pages} keeps pages 1..{max_pages} only. "
        "Cloudflare blocks curl."
    )

    rows = ingest_rankings(
        pages_dir=pages_dir,
        rankings_path=rankings_path,
        max_pages=max_pages,
    )
    print(f"Ingested rankings: {len(rows)} row(s) → {rankings_path}")
    if not rows:
        print(
            "No rows. Drop saved pages into pages/ or a rankings.json, then re-run."
        )
        return 0

    candidates = filter_candidates(
        rows,
        favorites=favorites,
        genre_match=genre_match,
        min_score=min_score,
        min_reviews=min_reviews,
    )
    print(f"After genre/score/reviews filter: {len(candidates)} album(s)")

    sp = build_client(cache_path)
    budget = SpotifyBudget(data_dir / "spotify_budget.json", spotify_daily_budget)
    me = spotify_call(sp.current_user, budget=budget)
    print(f"Authenticated as {me.get('display_name') or me.get('id')}")
    print(f"Spotify daily budget: {budget.used}/{budget.daily_budget} used so far today (UTC)")

    match_cache = JsonCache(data_dir / "spotify_match_cache.json", ttl_hours=DEFAULT_MATCH_CACHE_HOURS)
    album_cache = JsonCache(data_dir / "album_cache.json", ttl_hours=DEFAULT_ALBUM_CACHE_HOURS)
    state = load_state(state_path, year)
    playlist_name = listen_playlist_name(year)

    print(f"Reading albums already on {year} light/medium/heavy …")
    on_year, _ = year_playlist_album_ids(
        sp, year, name_style, budget=budget, sleep_s=spotify_sleep
    )
    print(
        f"Year-playlist index: {on_year.track_count} track(s), "
        f"{len(on_year.album_ids)} album id(s), {len(on_year.name_keys)} name key(s)"
    )

    # Also exclude albums already on "{year} listen"
    listen_index = YearPlaylistIndex()
    listen_id = state.get("playlist_id") or None
    if not listen_id:
        listen_id = None
        offset = 0
        while True:
            page = spotify_call(sp.current_user_playlists, limit=50, offset=offset, budget=budget)
            items = page.get("items") or []
            for playlist in items:
                if playlist and playlist.get("name") == playlist_name:
                    listen_id = playlist.get("id")
                    break
            if listen_id or page.get("next") is None:
                break
            offset += len(items)
    if listen_id:
        listen_index = playlist_album_index(sp, listen_id, budget=budget, sleep_s=spotify_sleep)
        print(
            f"Listen playlist {playlist_name!r}: {listen_index.track_count} track(s), "
            f"{len(listen_index.album_ids)} album id(s), {len(listen_index.name_keys)} name key(s)"
        )
    else:
        print(f"Listen playlist {playlist_name!r} not found yet — will create on write.")

    # Prune prior AOTY kept that now sit on year buckets.
    prev_kept = state.get("kept_albums") or {}
    if isinstance(prev_kept, dict):
        for album_id, row in list(prev_kept.items()):
            if not isinstance(row, dict):
                prev_kept.pop(album_id, None)
                continue
            if album_on_year_playlists(
                str(row.get("album_id") or album_id),
                str(row.get("artists") or ""),
                str(row.get("name") or ""),
                on_year,
            ):
                print(
                    f"  prune AOTY state (now on year bucket): "
                    f"{row.get('artists')} — {row.get('name')}"
                )
                prev_kept.pop(album_id, None)

    exclude = YearPlaylistIndex(
        album_ids=set(on_year.album_ids) | set(listen_index.album_ids),
        name_keys=set(on_year.name_keys) | set(listen_index.name_keys),
        track_count=on_year.track_count + listen_index.track_count,
    )
    # Also exclude by prior AOTY kept ids/keys (already on listen via prior append).
    for album_id, row in (prev_kept or {}).items():
        if not isinstance(row, dict):
            continue
        exclude.album_ids.add(str(row.get("album_id") or album_id))
        artists = str(row.get("artists") or "")
        name = str(row.get("name") or "")
        if artists and name:
            exclude.name_keys.add(album_name_key(artists, name))

    added: dict[str, dict] = dict(prev_kept) if isinstance(prev_kept, dict) else {}
    new_track_uris: list[str] = []
    attempted = 0
    matched = 0
    skipped_exclude = 0
    skipped_nomatch = 0
    stopped_early = False

    for row in candidates:
        if attempted >= max_albums_per_run:
            print(f"Hit --max-albums-per-run {max_albums_per_run}; remaining deferred.")
            break
        aoty_key = album_name_key(row.artist, row.album)
        # Pre-exclude by AOTY name key against year/listen indexes.
        if aoty_key in exclude.name_keys:
            skipped_exclude += 1
            continue

        attempted += 1
        allow_fetch = not cache_only
        try:
            hit = search_spotify_album(
                sp,
                row.artist,
                row.album,
                market,
                match_cache,
                budget,
                allow_fetch=allow_fetch,
            )
        except SpotifyBudgetExceeded as exc:
            print(f"\n{exc}")
            stopped_early = True
            break
        except SpotifyRateLimitError:
            raise

        if not hit:
            skipped_nomatch += 1
            print(f"  MISS  {row.artist} — {row.album} (no strict name_key match)")
            continue

        album_id = hit["album_id"]
        artists = hit["artists"]
        name = hit["name"]
        if album_on_year_playlists(album_id, artists, name, exclude):
            skipped_exclude += 1
            print(f"  SKIP  {artists} — {name} (already on year bucket or listen)")
            continue

        try:
            track_uris, _ = album_track_uris(
                sp,
                album_id,
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
        except Exception as exc:  # noqa: BLE001
            print(f"  ! album tracks {artists} — {name}: {exc}")
            continue
        if not track_uris:
            print(f"  MISS  {artists} — {name} (no tracks)")
            continue

        matched += 1
        record = {
            "album_id": album_id,
            "name": name,
            "artists": artists,
            "release_date": hit.get("release_date") or row.release_date or "",
            "track_uris": track_uris,
            "source": "aoty",
            "name_key": album_name_key(artists, name),
            "aoty_rank": row.rank,
            "aoty_score": row.score,
            "aoty_reviews": row.reviews,
            "aoty_genres": list(row.genres),
            "aoty_artist": row.artist,
            "aoty_album": row.album,
        }
        added[album_id] = record
        new_track_uris.extend(track_uris)
        exclude.album_ids.add(album_id)
        exclude.name_keys.add(record["name_key"])
        print(
            f"  ADD   AOTY #{row.rank} {row.artist} — {row.album}  "
            f"→  {artists} — {name} [{len(track_uris)} tracks] "
            f"score={row.score} reviews={row.reviews} genres={', '.join(row.genres)}"
        )

    # Dedupe new URIs
    seen_uri: set[str] = set()
    unique_new: list[str] = []
    for uri in new_track_uris:
        if uri not in seen_uri:
            seen_uri.add(uri)
            unique_new.append(uri)

    print(
        f"\nMatched {matched} new album(s); "
        f"skipped_exclude={skipped_exclude} skipped_nomatch={skipped_nomatch}; "
        f"{len(unique_new)} new track URI(s) to append."
    )

    state["kept_albums"] = added
    state["year"] = year
    state["market"] = market
    state["playlist_name"] = playlist_name
    state["last_run"] = {
        "matched": matched,
        "skipped_exclude": skipped_exclude,
        "skipped_nomatch": skipped_nomatch,
        "attempted": attempted,
        "stopped_early": stopped_early,
    }
    budget.save()

    if dry_run:
        save_state(state_path.with_suffix(".dry-run.json"), state)
        print(f"Dry run — wrote {state_path.with_suffix('.dry-run.json')}; playlist not modified.")
        print(f"Spotify calls charged today (this tool): {budget.used}/{budget.daily_budget}")
        return 0

    if not unique_new and listen_id:
        save_state(state_path, state)
        print("Nothing new to append.")
        print(f"State: {state_path}")
        print(f"Spotify calls charged today (this tool): {budget.used}/{budget.daily_budget}")
        return 0

    playlist_id = listen_id
    if not playlist_id:
        playlist_id = find_or_create_playlist(sp, playlist_name, dry_run=False)
    assert playlist_id
    try:
        spotify_call(
            sp.playlist_change_details,
            playlist_id,
            description=(
                f"Auto-synced: {year} followed-artist albums + AOTY genre matches "
                f"not on {year} light/medium/heavy "
                f"(sync_spotify_year_listen + sync_spotify_aoty_listen)"
            ),
            budget=budget,
        )
    except Exception:
        pass

    if unique_new:
        for batch in chunked(unique_new, 100):
            spotify_call(sp.playlist_add_items, playlist_id, batch, budget=budget)
        print(f"Appended {len(unique_new)} track(s) to {playlist_name!r} ({playlist_id})")
    state["playlist_id"] = playlist_id
    save_state(state_path, state)
    print(f"State: {state_path}")
    print(f"Spotify calls charged today (this tool): {budget.used}/{budget.daily_budget}")
    print(
        "Note: sync_spotify_year_listen rebuilds this same playlist and re-merges "
        "AOTY kept albums from this state file so they are not wiped."
    )
    return 0


def self_test() -> None:
    # Genre normalize: typo fix + casefold dedupe
    genres = normalize_favorite_genres(
        [
            "Indie Rock",
            "indie rock",
            "ost-Punk Revival",
            "Post-Punk Revival",
            "  Ambient Pop ",
            "Ambient Pop",
        ]
    )
    assert genres == ["Indie Rock", "Post-Punk Revival", "Ambient Pop"], genres
    assert len(normalize_config_genres(json.loads(DEFAULT_EXAMPLE_CONFIG.read_text())["favorite_genres"])) == 47

    fixtures = Path(__file__).resolve().parent / "fixtures"
    fixture = fixtures / "aoty_2026_page1_sample.md"
    rows = parse_listing_file(fixture)
    favs = normalize_favorite_genres(["Indie Folk", "Noise Rock", "Post-Rock"])
    matched = filter_by_genres(rows, favs, match="any")
    names = {(r.artist, r.album) for r in matched}
    assert ("Phoebe Bridgers", "Lost Weekend") in names
    assert ("Neurosis", "An Undying Love for a Burning World") in names
    assert ("Gilla Band", "Pugnello") in names
    assert ("underscores", "U") not in names

    # Browser-saved HTML fixture (albumListRow)
    html_rows = parse_listing_file(fixtures / "aoty_2026_page1_sample.html")
    assert html_rows[0].artist == "Phoebe Bridgers"
    assert html_rows[0].score == 91 and html_rows[0].reviews == 32
    assert "Ambient Pop" in html_rows[0].genres

    # Score/reviews thresholds
    filtered = filter_candidates(
        rows,
        favorites=favs,
        genre_match="any",
        min_score=70,
        min_reviews=5,
    )
    assert all(r.score is not None and r.score >= 70 for r in filtered)
    assert all(r.reviews is not None and r.reviews >= 5 for r in filtered)
    # Gilla Band has reviews but no score in fixture → dropped
    assert ("Gilla Band", "Pugnello") not in {(r.artist, r.album) for r in filtered}

    # Page discovery: any *.html by "Page N" (not lexicographic / not URL slug)
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        pages = Path(tmp)
        names_to_touch = [
            "The Best Albums of 2026 _ Page 10 - Album of The Year.html",
            "The Best Albums of 2026 _ Page 2 - Album of The Year.html",
            "The Best Albums of 2026 - Album of The Year.html",
            "The Best Albums of 2026 _ Page 6 - Album of The Year.html",
        ]
        for name in names_to_touch:
            (pages / name).write_text("<html></html>", encoding="utf-8")
        (pages / "ignore-me.json").write_text("{}", encoding="utf-8")
        found = discover_page_files(pages, max_pages=6)
        assert [p.name for p in found] == [
            "The Best Albums of 2026 - Album of The Year.html",
            "The Best Albums of 2026 _ Page 2 - Album of The Year.html",
            "The Best Albums of 2026 _ Page 6 - Album of The Year.html",
        ]
        assert [page_number_from_path(p) for p in found] == [1, 2, 6]
        # max_pages must not pick Page 10 via lexicographic sort
        assert not any(page_number_from_path(p) == 10 for p in found)

    # Strict name_key matching (same helpers year-listen uses)
    key_a = album_name_key("Phoebe Bridgers", "Lost Weekend")
    key_b = album_name_key("  phoebe   bridgers ", "LOST  WEEKEND")
    key_c = album_name_key("Phoebe Bridgers, Someone", "Lost Weekend")
    assert key_a == key_b == key_c
    assert key_a != album_name_key("Other Artist", "Lost Weekend")

    on_year = YearPlaylistIndex(
        album_ids={"already-id"},
        name_keys={album_name_key("Neurosis", "An Undying Love for a Burning World")},
    )
    assert album_on_year_playlists(
        "other-id",
        "Neurosis",
        "An Undying Love for a Burning World",
        on_year,
    )
    assert not album_on_year_playlists(
        "fresh-id",
        "Phoebe Bridgers",
        "Lost Weekend",
        on_year,
    )

    # load_aoty_kept_albums only returns source=aoty
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        save_state(
            root / "state.json",
            {
                "year": 2026,
                "kept_albums": {
                    "a1": {
                        "album_id": "a1",
                        "name": "Lost Weekend",
                        "artists": "Phoebe Bridgers",
                        "source": "aoty",
                        "track_uris": ["spotify:track:1"],
                    },
                    "b1": {
                        "album_id": "b1",
                        "name": "Other",
                        "artists": "X",
                        "source": "followed",
                        "track_uris": ["spotify:track:2"],
                    },
                },
            },
        )
        kept = load_aoty_kept_albums(root)
        assert set(kept) == {"a1"}
        assert kept["a1"]["source"] == "aoty"

        removed = prune_aoty_state_against_year(
            root,
            YearPlaylistIndex(
                album_ids=set(),
                name_keys={album_name_key("Phoebe Bridgers", "Lost Weekend")},
            ),
        )
        assert removed == 1
        assert load_aoty_kept_albums(root) == {}

    print("self-test OK")
    print(f"  example config genre count: 47")
    print(f"  album_name_key sample: {key_a!r}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--year", type=int, default=None, help="Override config year")
    parser.add_argument(
        "--name-style",
        choices=("spaced", "underscore"),
        default="spaced",
        help="How year light/medium/heavy playlists are named",
    )
    parser.add_argument("--market", default=None, help="Override config market")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_PATH)
    parser.add_argument("--cache-path", type=Path, default=DEFAULT_CACHE_PATH)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Config JSON (default: <data-dir>/config.json, else example)",
    )
    parser.add_argument("--spotify-sleep", type=float, default=DEFAULT_SPOTIFY_SLEEP)
    parser.add_argument(
        "--spotify-daily-budget",
        type=int,
        default=DEFAULT_SPOTIFY_DAILY_BUDGET,
        help=f"Max Spotify HTTP calls/UTC-day for this tool (default {DEFAULT_SPOTIFY_DAILY_BUDGET})",
    )
    parser.add_argument(
        "--max-albums-per-run",
        type=int,
        default=None,
        help="Cap Spotify search/add attempts per run (default from config, usually 20)",
    )
    parser.add_argument(
        "--cache-only",
        action="store_true",
        help="Do not call Spotify search/album-tracks; use match + track caches only",
    )
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        self_test()
        return 0

    config_path = args.config or (args.data_dir / "config.json")
    config = load_config(config_path, DEFAULT_EXAMPLE_CONFIG)
    # Seed drive config from example when missing so the user can edit locally.
    if not (args.data_dir / "config.json").is_file() and DEFAULT_EXAMPLE_CONFIG.is_file():
        args.data_dir.mkdir(parents=True, exist_ok=True)
        target = args.data_dir / "config.json"
        target.write_text(DEFAULT_EXAMPLE_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Seeded {target} from example config — edit favorite_genres there if needed.")

    year = args.year if args.year is not None else int(config["year"])
    market = args.market or str(config.get("market") or "US")
    max_albums = (
        args.max_albums_per_run
        if args.max_albums_per_run is not None
        else int(config.get("max_albums_per_run") or 20)
    )

    load_env_file(args.env_file)
    load_env_file(REPO_ROOT / ".env")
    try:
        return sync(
            year=year,
            name_style=args.name_style,
            market=market,
            dry_run=args.dry_run,
            cache_path=args.cache_path,
            data_dir=args.data_dir,
            config=config,
            spotify_sleep=args.spotify_sleep,
            spotify_daily_budget=args.spotify_daily_budget,
            max_albums_per_run=max_albums,
            cache_only=args.cache_only,
        )
    except SpotifyRateLimitError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
