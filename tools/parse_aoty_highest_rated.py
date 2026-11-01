#!/usr/bin/env python3
"""Parse spike: AOTY highest-rated listing pages → structured rows.

Supports:
  - Markdown extracts (WebFetch / browser "copy as markdown") like
    tools/fixtures/aoty_2026_page1_sample.md
  - Browser Save-as-HTML listing pages (Chrome/Edge full document) with
    albumListRow / albumListTitle / albumListGenre / scoreValue / scoreText
    (Cloudflare blocks plain curl — use saved pages)

Does NOT fetch the live site (plain HTTP gets Cloudflare 403 from this
environment). Prefer saving pages locally, then:

  python tools/parse_aoty_highest_rated.py tools/fixtures/aoty_2026_page1_sample.md
  python tools/parse_aoty_highest_rated.py tools/fixtures/aoty_2026_page1_sample.html
  python tools/parse_aoty_highest_rated.py --self-test

See tools/aoty_year_listen_design.md for the full pipeline design.
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

HEADING_RE = re.compile(
    r"^##\s+(\d+)\.\s+(.+?)\s+-\s+(.+?)\s*$",
    re.MULTILINE,
)
# After tag-stripping, AOTY rank markup becomes "1 . Artist - Album" (space before .).
PLAIN_HEADING_RE = re.compile(
    r"^(\d+)\s*\.\s+(.+?)\s+-\s+(.+)$"
)
DATE_RE = re.compile(
    r"^(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},\s+\d{4}\s*$"
)
SCORE_RE = re.compile(r"^(\d{1,3})\s*$")
REVIEWS_RE = re.compile(r"^(\d+)\s+reviews?\s*$", re.IGNORECASE)
SKIP_LINE_RE = re.compile(
    r"^(Vinyl|Bandcamp|SoundCloud|Critic Score|Page image:|#+\s|The Highest|"
    r"The Best Albums|\d{4}\s*$)",
    re.IGNORECASE,
)
GENRE_LINE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 /&'.+-]*(?:,\s*[A-Za-z0-9 /&'.+-]+)+\s*$")
# Single-token genres still appear (e.g. "Doom Metal" alone, or "Doom Metal" without comma).
SINGLE_GENRE_RE = re.compile(
    r"^[A-Z][A-Za-z0-9 /&'.+-]{1,60}$"
)
PAGE_IN_NAME_RE = re.compile(r"(?i)\bPage\s+(\d+)\b")
LISTING_SUFFIXES = {".md", ".html", ".htm", ".txt"}

# Browser-saved AOTY highest-rated markup (albumList* classes).
ALBUM_LIST_ROW_RE = re.compile(
    r'<div[^>]*\bid=["\']rank-(\d+)["\'][^>]*\bclass=["\'][^"\']*\balbumListRow\b[^"\']*["\'][^>]*>(.*?)'
    r'(?=<div[^>]*\bid=["\']rank-\d+["\']|$)',
    re.IGNORECASE | re.DOTALL,
)
ALBUM_LIST_ROW_ALT_RE = re.compile(
    r'<div[^>]*\bclass=["\'][^"\']*\balbumListRow\b[^"\']*["\'][^>]*>(.*?)'
    r'(?=<div[^>]*\bclass=["\'][^"\']*\balbumListRow\b|$)',
    re.IGNORECASE | re.DOTALL,
)
POSITION_RE = re.compile(
    r'itemprop=["\']position["\'][^>]*>\s*(\d+)\s*<',
    re.IGNORECASE,
)
TITLE_LINK_RE = re.compile(
    r'class=["\'][^"\']*\balbumListTitle\b[^"\']*["\'][^>]*>.*?<a[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
META_NAME_RE = re.compile(
    r'<meta[^>]*itemprop=["\']name["\'][^>]*content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
DATE_DIV_RE = re.compile(
    r'class=["\'][^"\']*\balbumListDate\b[^"\']*["\'][^>]*>(.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)
GENRE_DIV_RE = re.compile(
    r'class=["\'][^"\']*\balbumListGenre\b[^"\']*["\'][^>]*>(.*?)(?:</div>\s*<div class=["\']albumListScore|</div>\s*<div class=["\']clear|$)',
    re.IGNORECASE | re.DOTALL,
)
GENRE_LINK_RE = re.compile(r"<a\b[^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
SCORE_VALUE_RE = re.compile(
    r'class=["\'][^"\']*\bscoreValue\b[^"\']*["\'][^>]*>\s*(\d{1,3})\s*<',
    re.IGNORECASE,
)
SCORE_TEXT_RE = re.compile(
    r'class=["\'][^"\']*\bscoreText\b[^"\']*["\'][^>]*>\s*(?:<strong>)?\s*(\d+)\s*(?:</strong>)?\s*reviews?',
    re.IGNORECASE | re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class AotyListingRow:
    rank: int
    artist: str
    album: str
    release_date: str | None = None
    genres: list[str] = field(default_factory=list)
    score: int | None = None
    reviews: int | None = None


def _split_genres(line: str) -> list[str]:
    parts = [p.strip() for p in line.split(",")]
    return [p for p in parts if p]


def _is_genre_line(line: str) -> bool:
    if not line or SKIP_LINE_RE.match(line):
        return False
    if DATE_RE.match(line) or SCORE_RE.match(line) or REVIEWS_RE.match(line):
        return False
    if GENRE_LINE_RE.match(line):
        return True
    # Allow short single genre tags that look like title case phrases.
    if SINGLE_GENRE_RE.match(line) and " - " not in line and not line.endswith(":"):
        # Reject obvious non-genre leftovers.
        lowered = line.casefold()
        if lowered in {"soundcloud", "bandcamp", "vinyl", "critic score"}:
            return False
        return True
    return False


def parse_markdown_listing(text: str) -> list[AotyListingRow]:
    """Parse WebFetch-style markdown for one highest-rated listing page."""
    matches = list(HEADING_RE.finditer(text))
    rows: list[AotyListingRow] = []
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]
        row = AotyListingRow(
            rank=int(match.group(1)),
            artist=match.group(2).strip(),
            album=match.group(3).strip(),
        )
        for raw in body.splitlines():
            line = raw.strip()
            if not line:
                continue
            if DATE_RE.match(line):
                row.release_date = line
                continue
            m_rev = REVIEWS_RE.match(line)
            if m_rev:
                row.reviews = int(m_rev.group(1))
                continue
            m_score = SCORE_RE.match(line)
            if m_score and row.score is None:
                # First bare integer after heading is critic score (when present).
                # Review counts are caught above; avoid treating rank leftovers as scores.
                value = int(m_score.group(1))
                if 0 <= value <= 100:
                    row.score = value
                continue
            if _is_genre_line(line):
                for g in _split_genres(line):
                    if g not in row.genres:
                        row.genres.append(g)
                continue
        rows.append(row)
    return rows


def _strip_tags(fragment: str) -> str:
    text = TAG_RE.sub(" ", fragment or "")
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _split_artist_album(title: str) -> tuple[str, str] | None:
    title = html_lib.unescape((title or "").strip())
    if " - " not in title:
        return None
    artist, album = title.split(" - ", 1)
    artist, album = artist.strip(), album.strip()
    if not artist or not album:
        return None
    return artist, album


def _parse_album_list_row(chunk: str, rank_hint: int | None = None) -> AotyListingRow | None:
    """Parse one albumListRow inner HTML block from a browser-saved page."""
    rank = rank_hint
    m_pos = POSITION_RE.search(chunk)
    if m_pos:
        rank = int(m_pos.group(1))
    if rank is None:
        return None

    title = ""
    m_link = TITLE_LINK_RE.search(chunk)
    if m_link:
        title = _strip_tags(m_link.group(1))
    if not title:
        m_meta = META_NAME_RE.search(chunk)
        if m_meta:
            title = html_lib.unescape(m_meta.group(1)).strip()
    split = _split_artist_album(title)
    if not split:
        return None
    artist, album = split

    release_date = None
    m_date = DATE_DIV_RE.search(chunk)
    if m_date:
        date_text = _strip_tags(m_date.group(1))
        if DATE_RE.match(date_text):
            release_date = date_text

    genres: list[str] = []
    m_genre = GENRE_DIV_RE.search(chunk)
    if m_genre:
        for gm in GENRE_LINK_RE.finditer(m_genre.group(1)):
            label = _strip_tags(gm.group(1))
            if label and label not in genres:
                genres.append(label)

    score = None
    m_score = SCORE_VALUE_RE.search(chunk)
    if m_score:
        value = int(m_score.group(1))
        if 0 <= value <= 100:
            score = value

    reviews = None
    m_rev = SCORE_TEXT_RE.search(chunk)
    if m_rev:
        reviews = int(m_rev.group(1))

    return AotyListingRow(
        rank=rank,
        artist=artist,
        album=album,
        release_date=release_date,
        genres=genres,
        score=score,
        reviews=reviews,
    )


def parse_html_listing(html: str) -> list[AotyListingRow]:
    """Parse browser-saved AOTY highest-rated HTML (albumListRow markup).

    Primary path: structured albumList* classes from Chrome/Edge Save Page As.
    Fallback: strip tags and reuse the markdown heading heuristic (also accepts
    the common "1 . Artist - Album" spacing after tag removal).
    """
    rows: list[AotyListingRow] = []
    seen_ranks: set[int] = set()

    matches = list(ALBUM_LIST_ROW_RE.finditer(html))
    if matches:
        for match in matches:
            rank_hint = int(match.group(1))
            row = _parse_album_list_row(match.group(2), rank_hint=rank_hint)
            if row is None or row.rank in seen_ranks:
                continue
            seen_ranks.add(row.rank)
            rows.append(row)
    else:
        for match in ALBUM_LIST_ROW_ALT_RE.finditer(html):
            row = _parse_album_list_row(match.group(1))
            if row is None or row.rank in seen_ranks:
                continue
            seen_ranks.add(row.rank)
            rows.append(row)

    if rows:
        rows.sort(key=lambda r: r.rank)
        return rows

    # Fallback: collapse tags → text, keep newlines for heading detection.
    text = re.sub(r"(?i)<br\s*/?>", "\n", html)
    text = re.sub(r"(?i)</(?:p|div|li|h\d)>", "\n", text)
    text = TAG_RE.sub(" ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    promoted = []
    for line in text.splitlines():
        line = line.strip()
        m = PLAIN_HEADING_RE.match(line)
        if m:
            promoted.append(f"## {m.group(1)}. {m.group(2)} - {m.group(3)}")
        else:
            promoted.append(line)
    return parse_markdown_listing("\n".join(promoted))


def page_number_from_path(path: Path) -> int:
    """Page index from filename/title: 'Page N' → N; otherwise treat as page 1.

    Browser Save-as titles look like:
      The Best Albums of 2026 - Album of The Year.html          → 1
      The Best Albums of 2026 _ Page 2 - Album of The Year.html → 2
    """
    m = PAGE_IN_NAME_RE.search(path.name)
    if m:
        return int(m.group(1))
    return 1


def discover_listing_files(pages_dir: Path, max_pages: int = 0) -> list[Path]:
    """List .html/.md/.txt pages sorted by Page N; optionally cap by page number.

    Discovers any *.html (filenames need not contain '6-highest-rated').
    When max_pages > 0, only files with page_number_from_path(p) <= max_pages
    are kept (so max_pages=6 uses pages 1–6 even if the user saved 16).
    """
    if not pages_dir.is_dir():
        return []
    files = [
        p
        for p in pages_dir.iterdir()
        if p.is_file() and p.suffix.casefold() in LISTING_SUFFIXES
    ]
    files.sort(key=lambda p: (page_number_from_path(p), p.name.casefold()))
    if max_pages > 0:
        files = [p for p in files if page_number_from_path(p) <= max_pages]
    return files


def parse_listing_file(path: Path) -> list[AotyListingRow]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    suffix = path.suffix.casefold()
    if suffix in {".html", ".htm"}:
        return parse_html_listing(raw)
    return parse_markdown_listing(raw)


# Known AOTY / paste typos → canonical display label (matched casefold).
GENRE_TYPO_FIXES: dict[str, str] = {
    "ost-punk revival": "Post-Punk Revival",
}


def fix_genre_typo(label: str) -> str:
    """Return display label with known typos corrected."""
    stripped = (label or "").strip()
    if not stripped:
        return ""
    fixed = GENRE_TYPO_FIXES.get(stripped.casefold())
    return fixed if fixed else stripped


def normalize_favorite_genres(raw: list[str]) -> list[str]:
    """Casefold-dedupe favorites; apply typo fixes; keep first-seen display form."""
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        fixed = fix_genre_typo(str(item))
        if not fixed:
            continue
        key = fixed.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(fixed)
    return out


def normalize_album_genres(genres: list[str]) -> list[str]:
    """Apply typo fixes + casefold dedupe to an album's AOTY tags."""
    return normalize_favorite_genres(genres)


def filter_by_genres(
    rows: list[AotyListingRow],
    favorites: list[str],
    *,
    match: str = "any",
) -> list[AotyListingRow]:
    fav = {fix_genre_typo(g).casefold() for g in favorites if str(g).strip()}
    fav.discard("")
    if not fav:
        return list(rows)
    out: list[AotyListingRow] = []
    for row in rows:
        tags = {fix_genre_typo(g).casefold() for g in row.genres}
        tags.discard("")
        if not tags:
            continue
        if match == "all":
            if fav <= tags:
                out.append(row)
        else:
            if tags & fav:
                out.append(row)
    return out


def self_test() -> None:
    fixtures = Path(__file__).resolve().parent / "fixtures"
    fixture = fixtures / "aoty_2026_page1_sample.md"
    rows = parse_listing_file(fixture)
    assert len(rows) >= 5, rows
    first = rows[0]
    assert first.rank == 1
    assert first.artist == "Phoebe Bridgers"
    assert first.album == "Lost Weekend"
    assert first.score == 91
    assert first.reviews == 32
    assert "Indie Folk" in first.genres
    assert "Ambient Pop" in first.genres

    converge = next(r for r in rows if r.rank == 4)
    assert converge.artist == "Converge"
    assert "Mathcore" in converge.genres
    assert converge.score == 87

    gilla = next(r for r in rows if r.rank == 8)
    assert "Noise Rock" in gilla.genres
    # Score missing on this fixture block; reviews present.
    assert gilla.score is None
    assert gilla.reviews == 19

    sparse = next(r for r in rows if r.rank == 10)
    assert sparse.genres == []
    assert sparse.reviews == 7

    matched = filter_by_genres(rows, ["Noise Rock", "Doom Metal"])
    names = {(r.artist, r.album) for r in matched}
    assert ("Neurosis", "An Undying Love for a Burning World") in names
    assert ("Gilla Band", "Pugnello") in names
    assert ("Phoebe Bridgers", "Lost Weekend") not in names

    # Browser-saved HTML (albumListRow / scoreValue / scoreText).
    html_fixture = fixtures / "aoty_2026_page1_sample.html"
    html_rows = parse_listing_file(html_fixture)
    assert len(html_rows) >= 5, html_rows
    h1 = html_rows[0]
    assert h1.rank == 1
    assert h1.artist == "Phoebe Bridgers"
    assert h1.album == "Lost Weekend"
    assert h1.score == 91
    assert h1.reviews == 32
    assert h1.release_date == "August 14, 2026"
    assert "Indie Folk" in h1.genres
    assert "Ambient Pop" in h1.genres
    assert "Folktronica" in h1.genres
    h_converge = next(r for r in html_rows if r.rank == 4)
    assert h_converge.artist == "Converge"
    assert "Mathcore" in h_converge.genres
    assert h_converge.score == 87
    h_gilla = next(r for r in html_rows if r.rank == 8)
    assert "Noise Rock" in h_gilla.genres
    assert h_gilla.score is None
    assert h_gilla.reviews == 19
    h_sparse = next(r for r in html_rows if r.rank == 10)
    assert h_sparse.artist.startswith("Pet Shop Boys")
    assert "&" in h_sparse.artist  # unescaped from &amp;
    assert h_sparse.album == "A Man from the Future"
    assert h_sparse.genres == []
    assert h_sparse.reviews == 7

    # Tag-strip fallback: space before period ("1 . Artist - Album").
    fallback_html = (
        "<html><body><div>1 . Fallback Artist - Fallback Album</div>"
        "<div>Indie Rock, Dream Pop</div><div>80</div><div>12 reviews</div></body></html>"
    )
    fb = parse_html_listing(fallback_html)
    assert len(fb) == 1 and fb[0].artist == "Fallback Artist"
    assert fb[0].album == "Fallback Album"
    assert fb[0].score == 80 and fb[0].reviews == 12

    # Page number from browser Save-as titles (page 1 has no "Page 1").
    assert page_number_from_path(Path("The Best Albums of 2026 - Album of The Year.html")) == 1
    assert page_number_from_path(Path("The Best Albums of 2026 _ Page 2 - Album of The Year.html")) == 2
    assert page_number_from_path(Path("The Best Albums of 2026 _ Page 16 - Album of The Year.html")) == 16

    # Typo fix + casefold dedupe for favorites / album tags.
    assert fix_genre_typo("ost-Punk Revival") == "Post-Punk Revival"
    assert normalize_favorite_genres(
        ["Indie Rock", "indie rock", "ost-Punk Revival", "Post-Punk Revival"]
    ) == ["Indie Rock", "Post-Punk Revival"]
    typo_row = AotyListingRow(
        rank=99,
        artist="Test",
        album="Typo Album",
        genres=["ost-Punk Revival", "Dream Pop"],
        score=80,
        reviews=10,
    )
    assert filter_by_genres([typo_row], ["Post-Punk Revival"]) == [typo_row]
    assert filter_by_genres([typo_row], ["ost-Punk Revival"]) == [typo_row]

    print("self-test OK")
    print(json.dumps([asdict(r) for r in rows], indent=2))
    print("--- html fixture ---")
    print(json.dumps([asdict(r) for r in html_rows], indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        help="Saved .md/.html listing page (or a directory of pages)",
    )
    parser.add_argument("--genre", action="append", default=[], help="Favorite genre (repeatable)")
    parser.add_argument(
        "--match",
        choices=("any", "all"),
        default="any",
        help="Genre filter: any overlapping tag (default) or all required",
    )
    parser.add_argument("--min-score", type=int, default=None)
    parser.add_argument("--min-reviews", type=int, default=None)
    parser.add_argument("--json", action="store_true", help="Print JSON array")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        self_test()
        return 0
    if not args.path:
        parser.error("path is required unless --self-test")

    if args.path.is_dir():
        files = discover_listing_files(args.path, max_pages=0)
        rows: list[AotyListingRow] = []
        seen: set[tuple[str, str]] = set()
        for path in files:
            for row in parse_listing_file(path):
                key = (row.artist.casefold(), row.album.casefold())
                if key in seen:
                    continue
                seen.add(key)
                rows.append(row)
    else:
        rows = parse_listing_file(args.path)

    if args.genre:
        rows = filter_by_genres(rows, normalize_favorite_genres(args.genre), match=args.match)
    if args.min_score is not None:
        rows = [r for r in rows if r.score is not None and r.score >= args.min_score]
    if args.min_reviews is not None:
        rows = [r for r in rows if r.reviews is not None and r.reviews >= args.min_reviews]

    if args.json:
        print(json.dumps([asdict(r) for r in rows], indent=2))
    else:
        for r in rows:
            genres = ", ".join(r.genres) if r.genres else "-"
            score = r.score if r.score is not None else "?"
            print(f"{r.rank:3d}. {r.artist} — {r.album}  [{score}]  ({genres})")
        print(f"# {len(rows)} row(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
