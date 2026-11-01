# AOTY highest-rated → `{year} listen` design

Goal: pull artist/album/genres from Album of the Year highest-rated pages
(e.g. `/ratings/6-highest-rated/2026/1`, `/…/2`, …), keep rows that match the
user’s favorite genres, and **append** matching albums to Spotify playlist
`{year} listen` only when they are **not** already on `{year} light|medium|heavy`
or already on `{year} listen`.

Related existing tool: `tools/sync_spotify_year_listen.py` (followed-artist →
listen; excludes year buckets by album id + normalized name key; Dev Mode
Spotify budget + `drive/spotify_year_listen/` caches).

---

## 1. Feasibility (spike findings)

### Listing pages already have the fields we need

From live WebFetch of pages 1, 2, and 10 (2026):

| Field | On listing page? | Notes |
| --- | --- | --- |
| Rank | Yes | `## N. Artist - Album` |
| Artist | Yes | Left of ` - ` in heading (collabs keep commas) |
| Album | Yes | Right of ` - ` |
| Release date | Usually | e.g. `March 20, 2026` |
| Genres | **Usually yes** | Primary + secondary tag lines (comma-separated) |
| Critic score | Often | Integer 0–100; sometimes missing |
| Review count | Often | `N reviews` |
| Detail URL / AOTY id | In real HTML (cover CDN paths); markdown extract is weaker | Prefer saving HTML when possible |

**Detail pages are not required** for a first genre filter. Use them only later
if listing genres look incomplete for sparse rows.

Pagination: ~25 albums/page. Page 10 ≈ ranks 226–250, scores ~77–79. So
`max_pages=4` ≈ top 100; `8` ≈ top 200; `10+` still useful if min score is low.

### robots.txt / politeness

`https://www.albumoftheyear.org/robots.txt` (sampled):

- General `User-agent: *` **does not** disallow `/ratings/…`.
- Disallows search/tag/account/feed/add-* and several user library paths.
- Explicitly `Disallow: /` for many AI bots (GPTBot, ClaudeBot, etc.).
- Some SEO bots get `Crawl-delay: 5`.

**Politeness:** ≤1 request / 5–10s, cache pages for days, small page range,
identify as a personal script in User-Agent, no parallel hammering.

**Cloudflare:** plain `curl`/requests from this environment get **403**
“Just a moment…”. Browser-class fetches (and Cursor WebFetch) can still read
content. Treat automated scrape as **fragile**; design ingest around saved
files first.

### Parse spike

`tools/parse_aoty_highest_rated.py` + `tools/fixtures/aoty_2026_page1_sample.md`
prove markdown listing → `{rank, artist, album, genres, score, reviews}` is easy.
Run: `python tools/parse_aoty_highest_rated.py --self-test`.

---

## 2. Approach options (ranked)

### A) Scrape AOTY → local JSON → genre filter → Spotify search → add

**Pros:** Fully automated weekly.  
**Cons:** Cloudflare; ToS/ethics gray area; HTML churn.  
**Fit:** Optional `--fetch` later (Playwright / user-browser cookie on the PC
that already runs `.bat` Spotify jobs), not the cloud agent.

### B) Manual / browser export → same pipeline from filter onward *(recommended start)*

**Pros:** Bypasses CF; user confirms pages; robots-friendly personal use.  
**Cons:** Manual step (save HTML or paste markdown for pages 1..N).  
**Fit:** Best MVP. Same Spotify matching/dedupe code as A.

### C) Hybrid: scrape rankings + detail-page genres with caching

**Pros:** Richest tags.  
**Cons:** N× more requests; usually unnecessary (listing already has genres).  
**Fit:** Only if genre miss-rate on listings is high after a dry run.

**Recommendation:** Ship **B now** (import saved listings), keep scrape as an
optional fetch plugin later. Shared core = parse → filter → Spotify match →
append. Prefer **not** C unless listing genres prove insufficient.

---

## 3. Architecture (fits TBN_Report patterns)

### Data flow

```
AOTY pages 1..N  (saved .html/.md  OR  optional local fetch)
        │
        ▼
tools/parse_aoty_highest_rated.py   →  drive/spotify_aoty_listen/rankings.json
        │
        ▼
genre filter (config) + min_score / min_reviews / max_albums
        │
        ▼
exclude if on {year} light|medium|heavy OR {year} listen
  (reuse album_id + album_name_key from sync_spotify_year_listen.py)
        │
        ▼
Spotify album search (cached) → album tracks → APPEND to "{year} listen"
        │
        ▼
state.json (source=aoty kept albums) + match cache
```

### Proposed files

| Path | Role |
| --- | --- |
| `tools/aoty_year_listen_design.md` | This design |
| `tools/parse_aoty_highest_rated.py` | Parse spike / future import helper |
| `tools/fixtures/aoty_2026_page1_sample.md` | Offline fixture |
| `tools/sync_spotify_aoty_listen.py` | Import+filter+match+append (shipped) |
| `tools/aoty_listen_config.example.json` | Committed example genres/thresholds (47 favorites) |
| `run_sync_spotify_aoty_listen.bat` | Thin wrapper like other Spotify runners |
| `drive/spotify_aoty_listen/config.json` | User genres + thresholds (`drive/` is gitignored) |
| `drive/spotify_aoty_listen/rankings.json` | Parsed AOTY rows (cached) |
| `drive/spotify_aoty_listen/pages/` | Saved HTML/MD inputs |
| `drive/spotify_aoty_listen/spotify_match_cache.json` | Search results TTL |
| `drive/spotify_aoty_listen/state.json` | Albums added with `source: aoty` |
| `drive/spotify_aoty_listen/spotify_budget.json` | Own daily call counter |

### Critical interaction with `sync_spotify_year_listen.py`

Year listen **full-rebuilds** the playlist from followed-artist candidates.
Blind appends from AOTY would be wiped on the next listen sync.

**Required when implementing:**

1. AOTY tool writes kept rows into `drive/spotify_aoty_listen/state.json`.
2. `sync_spotify_year_listen.py` loads that supplemental set (or a small shared
   helper) and **merges** `source=aoty` albums into `kept` before rewrite,
   still applying year-bucket exclusion (id + name key).
3. When year playlists later contain an album, both tools drop it (listen sync
   already scrubs; AOTY state should prune the same way).

Do **not** create a second “2026 aoty listen” unless the user prefers isolation.

### Favorite genres config

Committed template `tools/aoty_listen_config.example.json` (47 normalized
favorites, `min_score=70`, `min_reviews=5`, `max_pages=6`,
`max_albums_per_run=20`, `genre_match=any`).

Runtime copy: `drive/spotify_aoty_listen/config.json` (seeded on first run from
example if missing). Genre compare = casefold exact tag match against AOTY
tag strings (not Spotify’s limited genre list). Typo fix:
`ost-Punk Revival` → `Post-Punk Revival`.

---

## 4. Spotify matching, budgets, schedule

### Matching

- Query: `album:"{title}" artist:"{primary_artist}"` `type=album`.
- Accept only if normalized `album_name_key(artists, name)` equals AOTY key
  (same helper as year listen: NFKC casefold + collapsed whitespace + primary
  artist).
- Reject obvious deluxe/live mismatches unless name_key still matches.
- Cache search hits/misses; never guess on ambiguous multi-hit without a name_key win.
- False-positive risk is real for generic titles — dry-run must print
  `AOTY → Spotify` pairs for user review first.

### Call budget (Dev Mode)

Per accepted album ≈ `1 search + 1..N album_tracks` (+ shared year-playlist
scan if not reusing a warm index).

Defaults mirroring year listen:

- `--spotify-daily-budget` 80–100 for this tool alone.
- `--max-albums-per-run` 15.
- Do **not** stack same UTC day as a cold `sync_spotify_year_listen` or
  favorites-unlistened crawl.
- Warm weekly: rankings refresh cheap if pages are local; Spotify work is the cost.

### Scheduling

- **Weekly:** import new/changed AOTY pages + append new matches.
- **After** year light/medium/heavy sync when possible (so exclusion is fresh).
- Rankings pages: refresh weekly is enough; scores move slowly.

### Page range

Locked defaults: `max_pages=6` (top ~150), `min_score=70`, `min_reviews=5`,
`max_albums_per_run=20`.

---

## 5. Risks

| Risk | Mitigation |
| --- | --- |
| Cloudflare / scrape breakage | File-first ingest; optional local browser fetch later |
| Site ToS / abuse | Low rate, cache, personal use, small page cap; prefer manual save |
| Genre false negatives (sparse rows) | Skip untagged rows; optional detail fetch later |
| Spotify wrong album | Strict name_key; dry-run review; match cache |
| Listen rebuild wipes AOTY adds | Merge supplemental state into year_listen |
| Shared Spotify quota | Separate budget file + don’t stack heavy jobs |

---

## 6. Locked user decisions

1. **Favorite genres:** 47 tags (casefold match, dedupe; typo `ost-Punk Revival` →
   `Post-Punk Revival`). Match mode: **any** overlap with album AOTY genres.
   Full list lives in `tools/aoty_listen_config.example.json`.
2. **`min_reviews=5`**, **`min_score=70`**.
3. **`max_pages=6`** (~top 150), **`max_albums_per_run=20`**.
4. Target playlist = same **`{year} listen`**. Year-listen rebuild merges AOTY
   `source=aoty` kept albums from `drive/spotify_aoty_listen/state.json`.
5. Ingest v1: **saved pages only** (no Playwright in this PR).
6. Unmatched / ambiguous Spotify searches: print + skip (strict `album_name_key`).

---

## 7. How to run (shipped)

```bat
REM 1) Copy config (or let first run seed it)
copy tools\aoty_listen_config.example.json drive\spotify_aoty_listen\config.json

REM 2) Browser-save AOTY pages 1..6 as .html/.md into:
REM    drive\spotify_aoty_listen\pages\
REM    https://www.albumoftheyear.org/ratings/6-highest-rated/2026/1

REM 3) Dry-run, then apply
run_sync_spotify_aoty_listen.bat --dry-run
run_sync_spotify_aoty_listen.bat

REM Year-listen rebuild preserves AOTY albums via state merge:
run_sync_spotify_year_listen.bat
```

Offline checks:

```bat
python tools\parse_aoty_highest_rated.py --self-test
python tools\sync_spotify_aoty_listen.py --self-test
python tools\sync_spotify_year_listen.py --self-test
```

Optional local fetch (Playwright / browser cookie) remains future work — not in v1.
