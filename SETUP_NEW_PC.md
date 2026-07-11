# New PC setup (stockresearch)

Move from laptop to desktop with **git for code** and **Google Drive for run outputs**. This guide matches the repo layout as of 2026.

## Before shutting down the laptop

1. **Push all code**
   ```bat
   git_checkin.bat --push -m "pre-migration snapshot"
   ```
2. **Copy `data\`** (not in git — largest item)
   - `data\newdata\data\` — OHLCV CSVs (~1,200 symbols, 2010+)
   - `data\ohlcv.duckdb` — optional DuckDB cache (rebuildable from CSVs)
   - `data\rl_gold_universe.txt` — if you use it
3. **Confirm Google Drive synced** — recent files in your `drive\` or `Drive\` output folder
4. **Export Task Scheduler job** (if used)
   - Task Scheduler → find DailyRun → Export → save XML to Drive/USB
5. **Optional:** copy `C:\Users\songg\.cursor\` (skills/rules) if you want identical Cursor setup

## Recommended install path

Many scripts hardcode:

```
C:\Users\songg\Downloads\stockresearch
```

**Easiest migration:** use the same path on the new PC. Otherwise search/replace that string after clone (see Path audit below).

## New PC — automated setup

1. Install **Git for Windows**: https://git-scm.com/download/win  
2. Install **Python 3.10** from python.org (not Microsoft Store — Task Scheduler issues):
   ```bat
   winget install -e --id Python.Python.3.10 --scope user
   ```
3. Clone and run setup:
   ```bat
   setup_new_pc.bat --clone "C:\Users\songg\Downloads\stockresearch" --smoke
   ```
   Or if you already cloned manually:
   ```bat
   cd C:\Users\songg\Downloads\stockresearch
   setup_new_pc.bat --smoke
   ```
4. Restore **`data\`** from USB/old laptop into the repo root (or re-download):
   ```bat
   run_backfill_data_to_2010.bat
   ```
   Rebuilding DuckDB (optional):
   ```bat
   python scripts\build_ohlcv_duckdb.py --data-dir data\newdata\data --db-path data\ohlcv.duckdb --replace
   ```

## Google Drive

Install Google Drive desktop and sign in. Your synced folder should expose the same run outputs the batch files expect:

- `drive\last_run_ts.txt` — written by RL/BRT runs
- `Drive\` — some scripts use capital D; repo accepts either via fallbacks

If Drive mounts elsewhere, either symlink/junction into the repo or adjust paths in the scripts that point at `drive\`.

## Git identity (one time per machine)

```bat
git config --global user.name "Your Name"
git config --global user.email "your@email"
```

First `git push` will prompt for GitHub auth (browser, `gh auth login`, or personal access token).

Remote: `https://github.com/pauljanderson/TBN_Report.git`

## Task Scheduler (DailyRun)

Recreate the nightly job:

| Setting | Value |
|---------|--------|
| Program | `C:\Users\songg\Downloads\stockresearch\DailyRun.bat` |
| Start in | `C:\Users\songg\Downloads\stockresearch` |
| Run whether user is logged on or not | Yes |
| Python | Must be python.org under `%LOCALAPPDATA%\Programs\Python\Python310\` |

DailyRun steps (for reference): update data → warm cache → RL audit/parity → BRT → IND → YH → MTS → copy latest → getTarget → publish GitHub Pages.

Test manually first:
```bat
DailyRun.bat
```
Check `logs\DailyRun_*.log` if anything fails.

## Path audit

If you cannot use the recommended path, find hardcoded references:

```bat
setup_new_pc.bat
```

Or search manually for `C:\Users\songg` in `.py` and `.bat` files. Key files today:

- `DailyRun.bat`
- `stock_analysis\pygetallMore.py` — `DATA_DIR`, `DEFAULT_DB_PATH`
- `getTarget.py`
- `generate_investment_report.py`
- `scripts\publish_github_pages.py` — logo path under Downloads

## Per-symbol optimizer settings

Production DailyRun uses:

```
stock_analysis\Per_Symbol_Optimized_Settings_Approved_Latest.json
```

Set in `daily_run_env.bat` via `PER_SYMBOL_SETTINGS`. Copy from old laptop or regenerate:

```bat
run_per_symbol_optimizer.bat --wf-mode rolling --systems RL --workers 5
```

## Smoke tests after setup

```bat
run_update_data.bat
run_rl.bat
run_gettarget.bat
publish_github_pages.bat
```

## Cursor IDE

1. Install Cursor
2. Open folder: `C:\Users\songg\Downloads\stockresearch`
3. Copy old `%USERPROFILE%\.cursor\skills-cursor\` and rules if desired

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Access is denied` from Python in Task Scheduler | Install python.org 3.10; avoid Windows Store Python |
| Missing CSV / empty backtests | Restore `data\newdata\data\` or run backfill |
| `drive\last_run_ts.txt missing` | Run `run_rl.bat` once; check Drive sync path |
| Git push rejected | `git pull` then push again |
| Wrong per-symbol params | Confirm `PER_SYMBOL_SETTINGS` points at Approved JSON |

## Quick checklist

- [ ] `git push` from laptop
- [ ] Copy `data\` (or plan backfill)
- [ ] Google Drive syncing on new PC
- [ ] `setup_new_pc.bat --smoke` passes
- [ ] One manual `DailyRun.bat` OK
- [ ] Task Scheduler recreated
- [ ] GitHub Pages publish works (`publish_github_pages.bat --push`)
