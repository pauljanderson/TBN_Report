#!/usr/bin/env python3
"""Render an HTML calendar of upcoming shows from local state.json (0 Spotify calls).

Reads:
  drive/spotify_upcoming_shows/state.json

Writes:
  drive/spotify_upcoming_shows/calendar.html

Examples:
  python tools/report_spotify_upcoming_shows_calendar.py
  python tools/report_spotify_upcoming_shows_calendar.py --open
"""

from __future__ import annotations

import argparse
import calendar as cal_mod
import html
import json
import re
import sys
import webbrowser
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sync_spotify_upcoming_shows import (  # noqa: E402
    DEFAULT_STATE_PATH,
    classify_show,
    parse_start,
)
from sync_spotify_year_playlists import REPO_ROOT  # noqa: E402

DEFAULT_OUT = REPO_ROOT / "drive" / "spotify_upcoming_shows" / "calendar.html"


@dataclass
class CalShow:
    artist: str
    title: str
    start: datetime
    city: str
    state: str
    venue: str
    country: str
    kind: str  # headliner | tribute
    playlist_eligible: bool

    @property
    def day(self) -> date:
        return self.start.astimezone(timezone.utc).date()

    @property
    def when_local_label(self) -> str:
        # Show UTC clock; venues are mixed TZ — date is the useful calendar key.
        return self.start.strftime("%Y-%m-%d %H:%M UTC")

    @property
    def place(self) -> str:
        bits = [b for b in (self.city, self.state) if b]
        place = ", ".join(bits)
        if self.country and self.country.upper() not in {"US", "UNITED STATES", "UNITED STATES OF AMERICA"}:
            place = f"{place} ({self.country})" if place else self.country
        return place


def load_shows(state_path: Path) -> tuple[list[CalShow], dict]:
    if not state_path.is_file():
        raise SystemExit(
            f"No state file at {state_path}\n"
            "Run sync_spotify_upcoming_shows.py first so shows are saved locally."
        )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    shows: list[CalShow] = []
    now = datetime.now(timezone.utc)
    for _aid, row in (state.get("artists") or {}).items():
        artist = (row.get("name") or "").strip() or "Unknown"
        for show in row.get("shows") or []:
            start = parse_start(show.get("start_utc"))
            if start is None or start < now:
                continue
            title = show.get("title") or ""
            if "playlist_eligible" in show and "kind" in show:
                playlist_eligible = bool(show.get("playlist_eligible"))
                kind = str(show.get("kind") or ("headliner" if playlist_eligible else "tribute"))
            else:
                classified = classify_show(title, artist)
                if classified is None:
                    continue
                playlist_eligible, kind = classified
            shows.append(
                CalShow(
                    artist=artist,
                    title=title,
                    start=start,
                    city=show.get("city") or "",
                    state=show.get("state") or "",
                    venue=show.get("venue") or "",
                    country=show.get("country") or "",
                    kind=kind,
                    playlist_eligible=playlist_eligible,
                )
            )
    shows.sort(key=lambda s: (s.start, s.artist.casefold()))
    return shows, state


def show_anchor(show: CalShow) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", show.artist.casefold()).strip("-") or "artist"
    return f"show-{int(show.start.timestamp())}-{slug}"


def month_span(shows: list[CalShow]) -> list[tuple[int, int]]:
    if not shows:
        today = datetime.now(timezone.utc).date()
        return [(today.year, today.month)]
    first = shows[0].day.replace(day=1)
    last = shows[-1].day.replace(day=1)
    months: list[tuple[int, int]] = []
    y, m = first.year, first.month
    while (y, m) <= (last.year, last.month):
        months.append((y, m))
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return months


def render_html(shows: list[CalShow], state: dict, out_path: Path) -> str:
    by_day: dict[date, list[CalShow]] = defaultdict(list)
    for show in shows:
        by_day[show.day].append(show)

    states = ", ".join(state.get("states") or []) or "—"
    days_window = state.get("days") or "—"
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    headliner_n = sum(1 for s in shows if s.playlist_eligible)
    tribute_n = len(shows) - headliner_n

    month_sections: list[str] = []
    for year, month in month_span(shows):
        month_name = cal_mod.month_name[month]
        weeks = cal_mod.Calendar(firstweekday=6).monthdatescalendar(year, month)  # Sun-start
        rows_html: list[str] = []
        for week in weeks:
            cells: list[str] = []
            for day in week:
                in_month = day.month == month
                day_shows = by_day.get(day, []) if in_month else []
                classes = ["day"]
                if not in_month:
                    classes.append("out")
                if day_shows:
                    classes.append("has-shows")
                if day == datetime.now(timezone.utc).date():
                    classes.append("today")
                chips = []
                for show in day_shows[:4]:
                    kind_cls = "chip-head" if show.playlist_eligible else "chip-trib"
                    tip = html.escape(
                        f"{show.artist} — {show.title}\n{show.venue}\n{show.place}\n{show.when_local_label}"
                    )
                    chips.append(
                        f'<a class="chip {kind_cls}" href="#{show_anchor(show)}"'
                        f' title="{tip}">{html.escape(show.artist)}</a>'
                    )
                more = ""
                if len(day_shows) > 4:
                    more = f'<div class="more">+{len(day_shows) - 4} more</div>'
                cells.append(
                    f'<td class="{" ".join(classes)}">'
                    f'<div class="dom">{day.day if in_month else ""}</div>'
                    f'<div class="chips">{"".join(chips)}{more}</div>'
                    f"</td>"
                )
            rows_html.append("<tr>" + "".join(cells) + "</tr>")

        month_sections.append(
            f"""
<section class="month" id="m-{year}-{month:02d}">
  <h2>{html.escape(month_name)} {year}</h2>
  <table class="cal" aria-label="{html.escape(month_name)} {year}">
    <thead><tr>
      <th>Sun</th><th>Mon</th><th>Tue</th><th>Wed</th><th>Thu</th><th>Fri</th><th>Sat</th>
    </tr></thead>
    <tbody>
      {"".join(rows_html)}
    </tbody>
  </table>
</section>
"""
        )

    list_items: list[str] = []
    for show in shows:
        kind_cls = "headliner" if show.playlist_eligible else "tribute"
        kind_label = "on playlist" if show.playlist_eligible else "calendar only"
        anchor = show_anchor(show)
        list_items.append(
            f"""
<article class="show {kind_cls}" id="{anchor}">
  <div class="when">
    <span class="date">{html.escape(show.day.isoformat())}</span>
    <span class="time">{html.escape(show.start.strftime("%H:%M UTC"))}</span>
  </div>
  <div class="body">
    <h3>{html.escape(show.artist)}</h3>
    <p class="title">{html.escape(show.title)}</p>
    <p class="meta">{html.escape(show.venue or "—")}</p>
    <p class="meta">{html.escape(show.place or "—")}</p>
  </div>
  <div class="badge">{kind_label}</div>
</article>
"""
        )

    if not shows:
        list_items.append('<p class="empty">No upcoming shows in state.json yet.</p>')

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Upcoming Shows</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,700&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet"/>
<style>
:root {{
  --ink: #12201c;
  --muted: #4a5c55;
  --paper: #f3efe6;
  --panel: rgba(255,252,246,0.82);
  --line: rgba(18,32,28,0.12);
  --head: #0f6b5c;
  --head-soft: #d7f0ea;
  --trib: #8a4b1f;
  --trib-soft: #f3e1cf;
  --glow: #c8f27a;
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  margin: 0;
  color: var(--ink);
  font-family: "IBM Plex Sans", system-ui, sans-serif;
  background:
    radial-gradient(1200px 600px at 10% -10%, rgba(200,242,122,0.35), transparent 55%),
    radial-gradient(900px 500px at 100% 0%, rgba(15,107,92,0.18), transparent 50%),
    linear-gradient(180deg, #e7f2ec 0%, var(--paper) 40%, #ebe4d7 100%);
  min-height: 100vh;
}}
.wrap {{ max-width: 1120px; margin: 0 auto; padding: 2.5rem 1.25rem 4rem; }}
.hero {{
  padding: 1.5rem 0 2rem;
  animation: rise 0.7s ease-out both;
}}
.brand {{
  font-family: Fraunces, Georgia, serif;
  font-weight: 700;
  font-size: clamp(2.6rem, 6vw, 4.2rem);
  line-height: 0.95;
  letter-spacing: -0.03em;
  margin: 0 0 0.75rem;
}}
.lede {{
  max-width: 36rem;
  color: var(--muted);
  font-size: 1.05rem;
  margin: 0 0 1.25rem;
}}
.stats {{
  display: flex; flex-wrap: wrap; gap: 0.6rem 1rem;
  color: var(--muted); font-size: 0.92rem;
}}
.stats strong {{ color: var(--ink); font-weight: 600; }}
.legend {{ display: flex; gap: 0.75rem; margin-top: 1rem; flex-wrap: wrap; }}
.legend span {{
  display: inline-flex; align-items: center; gap: 0.4rem;
  padding: 0.35rem 0.7rem; border-radius: 999px; font-size: 0.85rem;
  background: var(--panel); border: 1px solid var(--line);
}}
.swatch {{ width: 0.7rem; height: 0.7rem; border-radius: 50%; }}
.swatch.head {{ background: var(--head); }}
.swatch.trib {{ background: var(--trib); }}
.month {{
  margin: 1.75rem 0 2.5rem;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 1.25rem;
  padding: 1rem 1rem 1.25rem;
  backdrop-filter: blur(8px);
  animation: rise 0.8s ease-out both;
}}
.month h2 {{
  font-family: Fraunces, Georgia, serif;
  font-size: 1.6rem;
  margin: 0.25rem 0.4rem 0.9rem;
}}
.cal {{ width: 100%; border-collapse: separate; border-spacing: 0.35rem; table-layout: fixed; }}
.cal th {{
  font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.06em;
  color: var(--muted); font-weight: 600; padding: 0.2rem;
}}
.cal td.day {{
  vertical-align: top;
  height: 7.2rem;
  background: rgba(255,255,255,0.55);
  border: 1px solid var(--line);
  border-radius: 0.75rem;
  padding: 0.4rem;
}}
.cal td.out {{ background: transparent; border-color: transparent; }}
.cal td.today {{ outline: 2px solid var(--glow); outline-offset: -2px; }}
.cal td.has-shows {{ background: rgba(255,255,255,0.88); }}
.dom {{ font-size: 0.8rem; font-weight: 600; color: var(--muted); margin-bottom: 0.25rem; }}
.chips {{ display: flex; flex-direction: column; gap: 0.2rem; }}
.chip {{
  display: block;
  font-size: 0.72rem;
  line-height: 1.15;
  padding: 0.22rem 0.35rem;
  border-radius: 0.4rem;
  text-decoration: none;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: transform 0.15s ease, filter 0.15s ease;
}}
.chip:hover {{ transform: translateY(-1px); filter: brightness(0.97); }}
.chip-head {{ background: var(--head-soft); color: var(--head); }}
.chip-trib {{ background: var(--trib-soft); color: var(--trib); }}
.more {{ font-size: 0.7rem; color: var(--muted); padding-left: 0.2rem; }}
.list-head {{
  font-family: Fraunces, Georgia, serif;
  font-size: 1.8rem;
  margin: 2.5rem 0 1rem;
}}
.show {{
  display: grid;
  grid-template-columns: 7.5rem 1fr auto;
  gap: 1rem;
  align-items: start;
  padding: 1rem 1.1rem;
  margin-bottom: 0.65rem;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 1rem;
  animation: rise 0.6s ease-out both;
}}
.show:nth-child(odd) {{ animation-delay: 0.03s; }}
.show .when {{ font-variant-numeric: tabular-nums; }}
.show .date {{ display: block; font-weight: 600; }}
.show .time {{ display: block; color: var(--muted); font-size: 0.85rem; margin-top: 0.15rem; }}
.show h3 {{
  font-family: Fraunces, Georgia, serif;
  font-size: 1.25rem;
  margin: 0 0 0.25rem;
}}
.show .title {{ margin: 0 0 0.35rem; color: var(--ink); }}
.show .meta {{ margin: 0; color: var(--muted); font-size: 0.92rem; }}
.badge {{
  align-self: start;
  font-size: 0.75rem;
  font-weight: 600;
  padding: 0.35rem 0.6rem;
  border-radius: 999px;
  white-space: nowrap;
}}
.show.headliner .badge {{ background: var(--head-soft); color: var(--head); }}
.show.tribute .badge {{ background: var(--trib-soft); color: var(--trib); }}
.empty {{ color: var(--muted); }}
.foot {{ margin-top: 2rem; color: var(--muted); font-size: 0.85rem; }}
@keyframes rise {{
  from {{ opacity: 0; transform: translateY(10px); }}
  to {{ opacity: 1; transform: none; }}
}}
@media (max-width: 720px) {{
  .cal td.day {{ height: auto; min-height: 4.5rem; }}
  .chip {{ font-size: 0.65rem; }}
  .show {{ grid-template-columns: 1fr; gap: 0.4rem; }}
  .badge {{ justify-self: start; }}
}}
</style>
</head>
<body>
<main class="wrap">
  <header class="hero">
    <h1 class="brand">Upcoming Shows</h1>
    <p class="lede">Who’s playing near you, where, and when — from your local StungEvents sync. Headliners can feed the Spotify playlist; tributes stay on the calendar only.</p>
    <div class="stats">
      <span><strong>{len(shows)}</strong> shows</span>
      <span><strong>{headliner_n}</strong> headliner</span>
      <span><strong>{tribute_n}</strong> tribute/related</span>
      <span>states <strong>{html.escape(str(states))}</strong></span>
      <span>window <strong>{html.escape(str(days_window))}d</strong></span>
    </div>
    <div class="legend">
      <span><i class="swatch head"></i> Headliner (playlist)</span>
      <span><i class="swatch trib"></i> Tribute / related (calendar only)</span>
    </div>
  </header>

  {"".join(month_sections)}

  <h2 class="list-head">All shows</h2>
  <section class="list">
    {"".join(list_items)}
  </section>

  <p class="foot">Generated {html.escape(generated)} · source {html.escape(str(state.get("playlist_name") or "upcoming shows"))} state</p>
</main>
</body>
</html>
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")
    return str(out_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--open", action="store_true", help="Open the HTML file in your browser")
    args = parser.parse_args(argv)

    shows, state = load_shows(args.state_file)
    path = render_html(shows, state, args.out)
    print(f"Shows: {len(shows)}")
    print(f"Wrote: {path}")
    if args.open:
        webbrowser.open(Path(path).resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
