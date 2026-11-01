#!/usr/bin/env python3
"""Parse spike: AOTY highest-rated listing pages → structured rows.

Supports:
  - Markdown extracts (WebFetch / browser "copy as markdown") like
    tools/fixtures/aoty_2026_page1_sample.md
  - Browser Save-as-HTML listing pages (Chrome/Edge full document) with
    albumListRow / albumListTitle / albumListGenre / scoreValue / scoreText
    (Cloudflare blocks plain curl — use saved pages)
  - Encoding quirks common on Windows saves: UTF-8 BOM, UTF-16 LE/BE
  - Markup variants: id=rank-N optional, class/id order, en/em dashes,
    albumBlock, JSON-LD ItemList, loose tag-stripped text

Does NOT fetch the live site (plain HTTP gets Cloudflare 403 from this
environment). Prefer saving pages locally, then:

  python tools/parse_aoty_highest_rated.py tools/fixtures/aoty_2026_page1_sample.md
  python tools/parse_aoty_highest_rated.py tools/fixtures/aoty_2026_page1_sample.html
  python tools/parse_aoty_highest_rated.py --self-test
  python tools/parse_aoty_highest_rated.py --debug drive/spotify_aoty_listen/pages/

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
# Also accept en/em dashes between artist and album.
PLAIN_HEADING_RE = re.compile(
    r"^(\d+)\s*\.\s+(.+?)\s+[-–—]\s+(.+)$"
)
DATE_RE = re.compile(
    r"^(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},\s+\d{4}\s*$"
)
SCORE_RE = re.compile(r"^(\d{1,3})\s*$")
REVIEWS_RE = re.compile(r"^(\d+)\s+reviews?\s*$", re.IGNORECASE)
SKIP_LINE_RE = re.compile(
    r"^(Vinyl|Bandcamp|SoundCloud|Critic Score|Page image:|#+\s|The Highest|"
    r"The Best Albums|\d{4}\s*$|Amazon|Spotify|iTunes|Apple Music|Music|"
    r"Just a moment|Checking your browser)",
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
# Primary: id="rank-N" present (attribute order flexible via separate alt).
ALBUM_LIST_ROW_RE = re.compile(
    r'<div[^>]*\bid=["\']rank-(\d+)["\'][^>]*\bclass=["\'][^"\']*\balbumListRow\b[^"\']*["\'][^>]*>(.*?)'
    r'(?=<div[^>]*\bid=["\']rank-\d+["\']|$)',
    re.IGNORECASE | re.DOTALL,
)
ALBUM_LIST_ROW_CLASS_FIRST_RE = re.compile(
    r'<div[^>]*\bclass=["\'][^"\']*\balbumListRow\b[^"\']*["\'][^>]*\bid=["\']rank-(\d+)["\'][^>]*>(.*?)'
    r'(?=<div[^>]*\b(?:id=["\']rank-\d+|class=["\'][^"\']*\balbumListRow\b)|$)',
    re.IGNORECASE | re.DOTALL,
)
ALBUM_LIST_ROW_ALT_RE = re.compile(
    r'<div[^>]*\bclass=["\'][^"\']*\balbumListRow\b[^"\']*["\'][^>]*>(.*?)'
    r'(?=<div[^>]*\bclass=["\'][^"\']*\balbumListRow\b|$)',
    re.IGNORECASE | re.DOTALL,
)
# Some list surfaces use albumBlock / albumListItem instead of albumListRow.
ALBUM_BLOCK_RE = re.compile(
    r'<(?:div|li|article)[^>]*\bclass=["\'][^"\']*\b(?:albumBlock|albumListItem)\b[^"\']*["\'][^>]*>(.*?)'
    r'(?=<(?:div|li|article)[^>]*\bclass=["\'][^"\']*\b(?:albumBlock|albumListItem)\b|$)',
    re.IGNORECASE | re.DOTALL,
)
POSITION_RE = re.compile(
    r'itemprop=["\']position["\'][^>]*>\s*(\d+)\s*<',
    re.IGNORECASE,
)
ALBUM_LIST_RANK_RE = re.compile(
    r'class=["\'][^"\']*\balbumListRank\b[^"\']*["\'][^>]*>(.*?)</span>',
    re.IGNORECASE | re.DOTALL,
)
RANK_TEXT_RE = re.compile(r"(\d+)\s*\.")
TITLE_LINK_RE = re.compile(
    r'class=["\'][^"\']*\b(?:albumListTitle|listLargeTitle)\b[^"\']*["\'][^>]*>.*?<a[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
# meta itemprop=name with either attribute order; allow HTML entities in content.
META_NAME_RE = re.compile(
    r'<meta\b(?=[^>]*\bitemprop=["\']name["\'])(?=[^>]*\bcontent=["\']([^"\']+)["\'])[^>]*>',
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
    r'class=["\'][^"\']*\b(?:scoreValue|listScoreValue)\b[^"\']*["\'][^>]*>\s*(\d{1,3})\s*<',
    re.IGNORECASE,
)
SCORE_TEXT_RE = re.compile(
    r'class=["\'][^"\']*\b(?:scoreText|listScoreText)\b[^"\']*["\'][^>]*>\s*(?:<strong>)?\s*(\d+)\s*(?:</strong>)?\s*(?:reviews?|ratings?)',
    re.IGNORECASE | re.DOTALL,
)
# Album detail anchors (Chrome Save-as often keeps these even when class names shift).
ALBUM_HREF_TITLE_RE = re.compile(
    r'<a\b[^>]*href=["\'][^"\']*/album/\d+-[^"\']+["\'][^>]*>([^<]{3,200})</a>',
    re.IGNORECASE,
)
ALBUM_ALT_TITLE_RE = re.compile(
    r'<img\b[^>]*\balt=["\']([^"\']{3,200})["\']',
    re.IGNORECASE,
)
JSON_LD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")
# Artist/album separators seen in live pages + smart-punctuation saves.
TITLE_SPLIT_RE = re.compile(r"\s+[-–—]\s+")


@dataclass
class AotyListingRow:
    rank: int
    artist: str
    album: str
    release_date: str | None = None
    genres: list[str] = field(default_factory=list)
    score: int | None = None
    reviews: int | None = None


@dataclass
class ListingFileDebug:
    path: str
    page: int
    bytes: int
    encoding: str
    album_list_row_count: int
    album_block_count: int
    album_href_count: int
    sample_stripped: str
    rows_parsed: int
    parse_path: str
    notes: list[str] = field(default_factory=list)


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
        if lowered in {
            "soundcloud",
            "bandcamp",
            "vinyl",
            "critic score",
            "amazon",
            "spotify",
            "itunes",
            "music",
            "apple music",
        }:
            return False
        return True
    return False


def parse_markdown_listing(text: str) -> list[AotyListingRow]:
    """Parse WebFetch-style markdown for one highest-rated listing page."""
    # Normalize smart dashes in headings so HEADING_RE (ASCII hyphen) still works.
    text = TITLE_SPLIT_RE.sub(" - ", text)
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
    title = re.sub(r"\s+", " ", title)
    if not title:
        return None
    parts = TITLE_SPLIT_RE.split(title, maxsplit=1)
    if len(parts) != 2:
        return None
    artist, album = parts[0].strip(), parts[1].strip()
    if not artist or not album:
        return None
    return artist, album


def _rank_from_chunk(chunk: str, rank_hint: int | None = None) -> int | None:
    rank = rank_hint
    m_pos = POSITION_RE.search(chunk)
    if m_pos:
        rank = int(m_pos.group(1))
    if rank is None:
        m_rank = ALBUM_LIST_RANK_RE.search(chunk)
        if m_rank:
            m_num = RANK_TEXT_RE.search(_strip_tags(m_rank.group(1)))
            if m_num:
                rank = int(m_num.group(1))
    if rank is None:
        # Bare "12." near the start of the chunk (tag-stripped prefix).
        prefix = _strip_tags(chunk[:240])
        m_num = RANK_TEXT_RE.match(prefix)
        if m_num:
            rank = int(m_num.group(1))
    return rank


def _parse_album_list_row(chunk: str, rank_hint: int | None = None) -> AotyListingRow | None:
    """Parse one albumListRow / albumBlock inner HTML block from a browser-saved page."""
    rank = _rank_from_chunk(chunk, rank_hint=rank_hint)
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
    if not title:
        m_href = ALBUM_HREF_TITLE_RE.search(chunk)
        if m_href:
            title = html_lib.unescape(m_href.group(1)).strip()
    if not title:
        m_alt = ALBUM_ALT_TITLE_RE.search(chunk)
        if m_alt:
            title = html_lib.unescape(m_alt.group(1)).strip()
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
            if label and label not in genres and not SKIP_LINE_RE.match(label):
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


def _dedupe_rows(rows: list[AotyListingRow]) -> list[AotyListingRow]:
    seen_ranks: set[int] = set()
    seen_keys: set[tuple[str, str]] = set()
    out: list[AotyListingRow] = []
    for row in rows:
        key = (row.artist.casefold(), row.album.casefold())
        if row.rank in seen_ranks or key in seen_keys:
            continue
        seen_ranks.add(row.rank)
        seen_keys.add(key)
        out.append(row)
    out.sort(key=lambda r: r.rank)
    return out


def _parse_json_ld_listing(html: str) -> list[AotyListingRow]:
    rows: list[AotyListingRow] = []
    for match in JSON_LD_RE.finditer(html):
        raw = match.group(1).strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        candidates = data if isinstance(data, list) else [data]
        for block in candidates:
            if not isinstance(block, dict):
                continue
            items = block.get("itemListElement") or block.get("itemList") or []
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                rank = item.get("position")
                node = item.get("item") if isinstance(item.get("item"), dict) else item
                name = ""
                if isinstance(node, dict):
                    name = str(node.get("name") or "")
                    if not name and isinstance(node.get("album"), dict):
                        name = str(node["album"].get("name") or "")
                if not name:
                    name = str(item.get("name") or "")
                split = _split_artist_album(name)
                if not split:
                    # JSON-LD sometimes separates artist + album.
                    artist = ""
                    album = ""
                    if isinstance(node, dict):
                        album = str(node.get("name") or "")
                        by = node.get("byArtist") or node.get("author")
                        if isinstance(by, dict):
                            artist = str(by.get("name") or "")
                        elif isinstance(by, list) and by and isinstance(by[0], dict):
                            artist = str(by[0].get("name") or "")
                    if artist and album:
                        split = (artist.strip(), album.strip())
                if not split:
                    continue
                try:
                    rank_i = int(rank) if rank is not None else (len(rows) + 1)
                except (TypeError, ValueError):
                    rank_i = len(rows) + 1
                artist, album = split
                rows.append(AotyListingRow(rank=rank_i, artist=artist, album=album))
    return _dedupe_rows(rows)


def _parse_href_title_listing(html: str) -> list[AotyListingRow]:
    """Last-resort: unique /album/N-… anchor texts that look like Artist - Album."""
    rows: list[AotyListingRow] = []
    seen: set[tuple[str, str]] = set()
    for match in ALBUM_HREF_TITLE_RE.finditer(html):
        title = html_lib.unescape(match.group(1)).strip()
        split = _split_artist_album(title)
        if not split:
            continue
        key = (split[0].casefold(), split[1].casefold())
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            AotyListingRow(rank=len(rows) + 1, artist=split[0], album=split[1])
        )
    return rows


def _parse_text_fallback(html: str) -> list[AotyListingRow]:
    # Fallback: collapse tags → text, keep newlines for heading detection.
    text = re.sub(r"(?i)<br\s*/?>", "\n", html)
    text = re.sub(r"(?i)</(?:p|div|li|h\d)>", "\n", text)
    text = TAG_RE.sub(" ", text)
    text = html_lib.unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
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


def parse_html_listing(html: str) -> list[AotyListingRow]:
    """Parse browser-saved AOTY highest-rated HTML (albumListRow markup).

    Primary path: structured albumList* classes from Chrome/Edge Save Page As.
    Fallbacks: albumBlock, JSON-LD, /album/ href titles, then strip tags and
    reuse the markdown heading heuristic (also accepts "1 . Artist - Album"
    and en/em dashes).
    """
    rows: list[AotyListingRow] = []

    for match in ALBUM_LIST_ROW_RE.finditer(html):
        row = _parse_album_list_row(match.group(2), rank_hint=int(match.group(1)))
        if row is not None:
            rows.append(row)
    if not rows:
        for match in ALBUM_LIST_ROW_CLASS_FIRST_RE.finditer(html):
            row = _parse_album_list_row(match.group(2), rank_hint=int(match.group(1)))
            if row is not None:
                rows.append(row)
    if not rows:
        for match in ALBUM_LIST_ROW_ALT_RE.finditer(html):
            row = _parse_album_list_row(match.group(1))
            if row is not None:
                rows.append(row)
    if not rows:
        for match in ALBUM_BLOCK_RE.finditer(html):
            row = _parse_album_list_row(match.group(1))
            if row is not None:
                rows.append(row)

    if rows:
        return _dedupe_rows(rows)

    json_rows = _parse_json_ld_listing(html)
    if json_rows:
        return json_rows

    href_rows = _parse_href_title_listing(html)
    if href_rows:
        return href_rows

    return _parse_text_fallback(html)


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
    Ignores Chrome *_files companion folders (only files, not dirs).
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


def detect_and_decode(raw: bytes) -> tuple[str, str]:
    """Decode listing bytes; handle UTF-8 BOM and UTF-16 LE/BE (Windows saves)."""
    if raw.startswith(b"\xff\xfe"):
        return raw.decode("utf-16-le", errors="replace"), "utf-16-le"
    if raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16-be", errors="replace"), "utf-16-be"
    # UTF-16 without BOM: many NULs in the first chunk of otherwise-ASCII HTML.
    sample = raw[:4000]
    if sample and sample[1:2] == b"\x00" and sample[0:1] != b"\x00":
        # Likely UTF-16-LE without BOM (e.g. '<\x00h\x00t\x00m\x00l')
        if sample[0:1] in (b"<", b"\r", b"\n", b" ") or sample[0:1].isalpha():
            return raw.decode("utf-16-le", errors="replace"), "utf-16-le-nobom"
    if sample and sample[0:1] == b"\x00" and sample[1:2] != b"\x00":
        return raw.decode("utf-16-be", errors="replace"), "utf-16-be-nobom"
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="replace"), "utf-8-bom"
    return raw.decode("utf-8", errors="replace"), "utf-8"


def read_listing_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    text, encoding = detect_and_decode(raw)
    # Normalize newlines early so regexes see a stable shape.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text, encoding


def _sample_stripped(text: str, n: int = 200) -> str:
    stripped = TAG_RE.sub(" ", text)
    stripped = html_lib.unescape(stripped)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    return stripped[:n]


def diagnose_listing_file(path: Path) -> tuple[list[AotyListingRow], ListingFileDebug]:
    """Parse one listing file and return rows + verbose diagnostics for --debug."""
    notes: list[str] = []
    try:
        raw = path.read_bytes()
    except OSError as exc:
        dbg = ListingFileDebug(
            path=str(path),
            page=page_number_from_path(path),
            bytes=0,
            encoding="?",
            album_list_row_count=0,
            album_block_count=0,
            album_href_count=0,
            sample_stripped="",
            rows_parsed=0,
            parse_path="error",
            notes=[f"read error: {exc}"],
        )
        return [], dbg

    text, encoding = detect_and_decode(raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    suffix = path.suffix.casefold()
    row_count = len(re.findall(r"\balbumListRow\b", text, flags=re.IGNORECASE))
    block_count = len(
        re.findall(r"\b(?:albumBlock|albumListItem)\b", text, flags=re.IGNORECASE)
    )
    href_count = len(re.findall(r"/album/\d+-", text, flags=re.IGNORECASE))
    sample = _sample_stripped(text)

    if "just a moment" in text.casefold() or "cf-browser-verification" in text.casefold():
        notes.append(
            "looks like a Cloudflare interstitial — re-save after the real page loads"
        )
    if row_count == 0 and href_count == 0 and suffix in {".html", ".htm"}:
        notes.append(
            "no albumListRow /album/ links — empty shell or HTML-only save of a "
            "JS-rendered page; use Chrome 'Webpage, Complete' after albums are visible"
        )
    if encoding.startswith("utf-16"):
        notes.append(f"decoded as {encoding} (Windows Unicode save)")

    parse_path = "markdown"
    if suffix in {".html", ".htm"}:
        # Probe which strategy would win (mirrors parse_html_listing order).
        if list(ALBUM_LIST_ROW_RE.finditer(text)) or list(
            ALBUM_LIST_ROW_CLASS_FIRST_RE.finditer(text)
        ):
            parse_path = "albumListRow+id"
        elif list(ALBUM_LIST_ROW_ALT_RE.finditer(text)):
            parse_path = "albumListRow"
        elif list(ALBUM_BLOCK_RE.finditer(text)):
            parse_path = "albumBlock"
        elif _parse_json_ld_listing(text):
            parse_path = "json-ld"
        elif _parse_href_title_listing(text):
            parse_path = "album-href"
        else:
            parse_path = "text-fallback"
        rows = parse_html_listing(text)
    else:
        rows = parse_markdown_listing(text)

    if not rows:
        notes.append("parsed 0 rows")
        if row_count > 0:
            notes.append(
                "albumListRow present but title/rank extract failed "
                "(dash variant, missing title link, or unexpected markup)"
            )

    dbg = ListingFileDebug(
        path=str(path),
        page=page_number_from_path(path),
        bytes=len(raw),
        encoding=encoding,
        album_list_row_count=row_count,
        album_block_count=block_count,
        album_href_count=href_count,
        sample_stripped=sample,
        rows_parsed=len(rows),
        parse_path=parse_path,
        notes=notes,
    )
    return rows, dbg


def format_listing_debug(dbg: ListingFileDebug) -> str:
    lines = [
        f"[debug] {dbg.path}",
        f"  page={dbg.page} bytes={dbg.bytes} encoding={dbg.encoding} "
        f"albumListRow={dbg.album_list_row_count} albumBlock={dbg.album_block_count} "
        f"album_href={dbg.album_href_count} rows={dbg.rows_parsed} via={dbg.parse_path}",
        f"  sample: {dbg.sample_stripped!r}",
    ]
    for note in dbg.notes:
        lines.append(f"  note: {note}")
    return "\n".join(lines)


def parse_listing_file(path: Path) -> list[AotyListingRow]:
    text, _encoding = read_listing_text(path)
    suffix = path.suffix.casefold()
    if suffix in {".html", ".htm"}:
        return parse_html_listing(text)
    return parse_markdown_listing(text)


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

    # Real-ish Wayback-derived fixture (modern id=rank-N markup, no wayback URLs).
    realish = fixtures / "aoty_wayback_listrow_sample.html"
    if realish.is_file():
        real_rows = parse_listing_file(realish)
        assert len(real_rows) >= 3, real_rows
        assert real_rows[0].artist and real_rows[0].album
        assert real_rows[0].score is not None

    # No id="rank-N" / no itemprop=position — rank from albumListRank text only.
    no_id_html = (
        '<div class="albumListRow"><h2 class="albumListTitle">'
        '<span class="albumListRank">3. </span>'
        '<a href="/album/1-x-y.php">No Id Artist - No Id Album</a></h2>'
        '<div class="albumListDate">January 2, 2026</div>'
        '<div class="albumListGenre"><a href="/genre/1/">Dream Pop</a></div>'
        '<div class="scoreValue">81</div>'
        '<div class="scoreText"><strong>6</strong> reviews</div></div>'
    )
    no_id_rows = parse_html_listing(no_id_html)
    assert len(no_id_rows) == 1, no_id_rows
    assert no_id_rows[0].rank == 3
    assert no_id_rows[0].artist == "No Id Artist"
    assert no_id_rows[0].album == "No Id Album"
    assert no_id_rows[0].score == 81 and no_id_rows[0].reviews == 6
    assert no_id_rows[0].genres == ["Dream Pop"]

    # class before id attribute order.
    class_first = (
        '<div class="albumListRow" id="rank-2"><h2 class="albumListTitle">'
        '<span itemprop="position">2</span>'
        '<a href="/album/2-a-b.php">Class First - Album Two</a>'
        '<meta content="Class First - Album Two" itemprop="name"/>'
        "</h2><div class=\"scoreValue\">77</div>"
        '<div class="scoreText"><strong>4</strong> reviews</div></div>'
    )
    cf_rows = parse_html_listing(class_first)
    assert len(cf_rows) == 1 and cf_rows[0].artist == "Class First"
    assert cf_rows[0].rank == 2

    # En-dash / em-dash titles (smart punctuation).
    en = parse_html_listing(
        '<div id="rank-1" class="albumListRow"><h2 class="albumListTitle">'
        "<a>En Dash Artist – En Dash Album</a></h2></div>"
    )
    assert len(en) == 1 and en[0].artist == "En Dash Artist" and en[0].album == "En Dash Album"
    em = parse_html_listing(
        '<div id="rank-1" class="albumListRow"><h2 class="albumListTitle">'
        "<a>Em Dash Artist — Em Dash Album</a></h2></div>"
    )
    assert len(em) == 1 and em[0].album == "Em Dash Album"

    # JSON-LD ItemList fallback.
    ld = parse_html_listing(
        '<script type="application/ld+json">'
        '{"@type":"ItemList","itemListElement":['
        '{"position":1,"item":{"name":"Json Artist - Json Album"}}]}'
        "</script>"
    )
    assert len(ld) == 1 and ld[0].artist == "Json Artist" and ld[0].album == "Json Album"

    # UTF-16 LE with BOM (common Windows "Unicode" save).
    import tempfile

    utf16_body = html_fixture.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        p16 = Path(tmp) / "utf16.html"
        p16.write_bytes(b"\xff\xfe" + utf16_body.encode("utf-16-le"))
        rows16 = parse_listing_file(p16)
        assert len(rows16) >= 5 and rows16[0].artist == "Phoebe Bridgers"
        _rows_d, dbg = diagnose_listing_file(p16)
        assert dbg.encoding.startswith("utf-16")
        assert dbg.rows_parsed >= 5

        # CRLF + UTF-8 BOM.
        p_bom = Path(tmp) / "bom.html"
        p_bom.write_bytes(b"\xef\xbb\xbf" + utf16_body.replace("\n", "\r\n").encode("utf-8"))
        assert parse_listing_file(p_bom)[0].artist == "Phoebe Bridgers"

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
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print per-file ingest diagnostics (encoding, albumListRow count, sample)",
    )
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
        if not files:
            print(f"No listing files in {args.path}", file=sys.stderr)
        for path in files:
            if args.debug:
                file_rows, dbg = diagnose_listing_file(path)
                print(format_listing_debug(dbg), file=sys.stderr)
            else:
                file_rows = parse_listing_file(path)
            for row in file_rows:
                key = (row.artist.casefold(), row.album.casefold())
                if key in seen:
                    continue
                seen.add(key)
                rows.append(row)
    else:
        if args.debug:
            rows, dbg = diagnose_listing_file(args.path)
            print(format_listing_debug(dbg), file=sys.stderr)
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
