# Split stockresearch → TBN / PredictionsMarkets / Spotify

You currently keep three products in one folder:

`C:\Users\songg\Downloads\stockresearch`

This kit moves them to:

| Product | Local path | GitHub repo |
|---------|------------|-------------|
| TBN (stock systems, DailyRun, Pages) | `C:\Users\songg\code\TBN` | keep `pauljanderson/TBN_Report` |
| PredictionsMarkets (Kalshi/Poly/Gemini/Novig + kitchen) | `C:\Users\songg\code\PredictionsMarkets` | **new** `pauljanderson/PredictionsMarkets` |
| Spotify (playlists / liked / upcoming shows) | `C:\Users\songg\code\Spotify` | **new** `pauljanderson/Spotify` |

## Recommended approach (what these bats do)

1. **Copy** the whole monorepo to `code\TBN` (keeps `.git`, `data\`, `drive\`, `local\`, `secrets\`). Leaves Downloads as a backup.
2. **Extract** Predictions + Spotify file lists into sibling folders (plus their runtime `drive\` / `local\` / secrets).
3. **Rewrite** hardcoded `C:\Users\songg\Downloads\stockresearch` → each new root. `DailyRun.bat` now uses `cd /d "%~dp0"` so it follows the folder.
4. **Create GitHub remotes** with `gh` and push the two new repos. TBN keeps `TBN_Report`.
5. **Verify** layouts, smoke-test, then **prune** prediction/spotify source out of TBN.
6. Only after that: delete or archive `Downloads\stockresearch`.

Why not three full history filters? TBN needs the existing git history and Pages remote. Predictions/Spotify are fine as a clean import; their research one-offs do not need  the whole TBN history.

## Before you start

1. Push any uncommitted work: `git_checkin.bat --push`
2. Pull this PR / `repo_split\` onto the PC
3. Install [GitHub CLI](https://cli.github.com/) and run `gh auth login` once
4. Close Python jobs / pause Task Scheduler DailyRun while copying large `data\`
5. Optional: export Task Scheduler DailyRun XML

## Run (pick one)

**One shot:**

```bat
cd C:\Users\songg\Downloads\stockresearch\repo_split
RUN_ALL.bat
```

**Or step by step:**

```bat
00_preflight.bat
01_create_dirs.bat
02_move_tbn.bat
03_extract_predictions.bat
04_extract_spotify.bat
05_rewrite_paths.bat
06_github_remotes.bat
08_verify.bat
```

After smoke tests:

```bat
07_prune_tbn.bat
cd C:\Users\songg\code\TBN
git_checkin.bat --push -m "Prune PredictionsMarkets and Spotify into their own repos"
```

Override source path if needed:

```bat
set STOCKRESEARCH_SOURCE=D:\backup\stockresearch
02_move_tbn.bat
```

## After the split — make systems keep running

### TBN
- Task Scheduler → DailyRun → Program/Start-in → `C:\Users\songg\code\TBN`
- Cursor: open `C:\Users\songg\code\TBN`
- `data\` and stock `drive\` stay with TBN
- Pages remote stays `TBN_Report` (`pauljanderson.github.io/TBN_Report/…`)

### PredictionsMarkets
- Open `C:\Users\songg\code\PredictionsMarkets` in Cursor
- Confirm `secrets\` has Kalshi/Novig/Gemini/Poly keys (spotify.env stripped from this copy)
- Confirm stamp exists:
  - `drive\paul_experiments\prediction_market_arb_exhaustive_20261017\`
  - `local\paul_experiments\prediction_market_arb_exhaustive_20261017\raw\`
- Start/status: `run_prediction_status.bat`, kitchen: `run_pm_venue_kitchen_check.bat`
- Use **this** repo’s `git_pull.bat` (kitchen rebuild stays here)

### Spotify
- Open `C:\Users\songg\code\Spotify`
- `secrets\spotify.env` from example if missing
- `drive\spotify_*` caches should have been copied by `--runtime`
- `run_spotify_playlist_tasks.bat`

### Hardcoded paths
There are ~180 files that still mentioned `Downloads\stockresearch`. Step `05` rewrites them. Prefer `%~dp0` / `Path(__file__)` going forward. Audit anytime:

```bat
python repo_split\lib\rewrite_paths.py --root C:\Users\songg\code\TBN --audit-only
```

## Ownership cheat sheet

- **TBN:** `stock_analysis\`, `scripts\`, `tos\`, `DailyRun.bat`, report generators, TBN `tools\*`, `docs\systems|research|trendlines`, `data\`
- **PredictionsMarkets:** `tools\live_*` (venue), `kalshi_*`, `polymarket_*`, `novig_*`, `prediction_*`, `pm_*`, `venue_*`, kitchen writers, `docs\prediction_market\`, `.cursor\rules\paul-problem-protocol.mdc`
- **Spotify:** `tools\sync_spotify_*`, `organize_spotify_*`, `report_spotify_*`, `spotify_*`, AOTY/stung helpers, matching `run_*spotify*.bat`

Shared helper **copied** into PredictionsMarkets: `report_page_extras.py` (TBN keeps its own).

## Manifests

- `manifests\predictions_files.txt`
- `manifests\spotify_files.txt`
- `manifests\predictions_runtime.txt`
- `manifests\spotify_runtime.txt`

Edit those if something landed in the wrong bucket, then re-run the extract step.
