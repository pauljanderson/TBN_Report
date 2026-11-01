#!/usr/bin/env python3
"""Parse spike: AOTY highest-rated listing pages → structured rows.

Supports:
  - Markdown extracts (WebFetch / browser "copy as markdown") like
    tools/fixtures/aoty_2026_page1_sample.md
  - Saved HTML listing pages if Cloudflare/browser save succeeded
    (looks for albumBlock-ish heading patterns; best-effort)

Does NOT fetch the live site (plain HTTP gets Cloudflare 403 from this
environment). Prefer saving pages locally, then:

  python tools/parse_aoty_highest_rated.py tools/fixtures/aoty_2026_page1_sample.md
  python tools/parse_aoty_highest_rated.py --self-test

See tools/aoty_year_listen_design.md for the full pipeline design.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

HEADING_RE = re.compile(
    r"^##\s+(\d+)\.\s+(.+?)\s+-\s+(.+?)\s*$",
    re.MULTILINE,
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


def parse_html_listing(html: str) -> list[AotyListingRow]:
    """Best-effort HTML parse when a saved page is available.

    Live AOTY markup uses album list blocks; without a clean HTML sample from
    this environment (Cloudflare challenge), this falls back to stripping tags
    into text and reusing the markdown heading heuristic when possible.
    """
    # Collapse tags → text, keep newlines for heading detection.
    text = re.sub(r"(?i)<br\s*/?>", "\n", html)
    text = re.sub(r"(?i)</(?:p|div|li|h\d)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    # Promote "N. Artist - Album" lines into markdown headings if present.
    promoted = []
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^(\d+)\.\s+(.+?)\s+-\s+(.+)$", line)
        if m:
            promoted.append(f"## {m.group(1)}. {m.group(2)} - {m.group(3)}")
        else:
            promoted.append(line)
    return parse_markdown_listing("\n".join(promoted))


def parse_listing_file(path: Path) -> list[AotyListingRow]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    suffix = path.suffix.casefold()
    if suffix in {".html", ".htm"}:
        return parse_html_listing(raw)
    return parse_markdown_listing(raw)


def filter_by_genres(
    rows: list[AotyListingRow],
    favorites: list[str],
    *,
    match: str = "any",
) -> list[AotyListingRow]:
    fav = {g.casefold().strip() for g in favorites if g.strip()}
    if not fav:
        return list(rows)
    out: list[AotyListingRow] = []
    for row in rows:
        tags = {g.casefold() for g in row.genres}
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
    fixture = Path(__file__).resolve().parent / "fixtures" / "aoty_2026_page1_sample.md"
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
    print("self-test OK")
    print(json.dumps([asdict(r) for r in rows], indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, help="Saved .md/.html listing page")
    parser.add_argument("--genre", action="append", default=[], help="Favorite genre (repeatable)")
    parser.add_argument(
        "--match",
        choices=("any", "all"),
        default="any",
        help="Genre filter: any overlapping tag (default) or all required",
    )
    parser.add_argument("--min-score", type=int, default=None)
    parser.add_argument("--json", action="store_true", help="Print JSON array")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        self_test()
        return 0
    if not args.path:
        parser.error("path is required unless --self-test")

    rows = parse_listing_file(args.path)
    if args.genre:
        rows = filter_by_genres(rows, args.genre, match=args.match)
    if args.min_score is not None:
        rows = [r for r in rows if r.score is not None and r.score >= args.min_score]

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
