# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Canonical map: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)** — read it before non-trivial changes. It holds the authority table, the DailyRun step list, the system roster, the data plane and the tech-debt register. This file only summarizes it and adds working rules.

## What this repo is

TBN (Twin Beacon Networks) is an equities research and live-ops platform. It is Windows-first and driven by `.bat` launchers. The parts:
- **Engines:** many strategy "systems" run as backtests.
- **Open book:** a human-edited positions file gets live stops and targets.
- **Reports:** published to GitHub Pages under `docs/` (remote `pauljanderson/TBN_Report`, branch `main`).

It is **not** an auto-trader; fills stay manual. The prediction-market kitchen (Kalshi, Polymarket, Gemini, Novig) moved to the separate `PredictionsMarkets` repo. Spotify tooling moved to the `Spotify` repo. Any PM or Spotify leftovers here are prune candidates, not live code.

## Commands

The working tree is on Windows (`C:\Users\songg\code\TBN`, seen from WSL as `/mnt/c/Users/songg/code/TBN`). Run batch files through `cmd.exe /c` from WSL. Python is 3.10 from python.org; `resolve_python.bat` sets `%PY%`. Install deps with `pip install -r requirements.txt`.

```bat
DailyRun.bat -w 8                 rem full nightly pipeline; --noGet skips data refresh; logs\DailyRun_*.log
run_brt.bat / run_yh.bat / run_mts.bat / run_wpbr.bat / run_rs.bat / run_sb.bat / run_vz.bat / run_rsi.bat / run_wrl.bat
set BRT_SYMBOLS=AAPL,MSFT & run_brt.bat    rem small universe
run_brt.bat path\to\universe.csv  |  run_brt.bat ALL                     rem universe override
run_gettarget.bat                 rem recompute getTarget_output.csv from gettarget_positions.csv
publish_github_pages.bat --push   rem regenerate docs/*.html and push to origin/main
run_update_data.bat               rem OHLCV refresh (stock_analysis/pygetallMore.py)
```

Direct engine call: `python stock_analysis\rocket_tbn.py data\newdata\data -o drive -v key=value ...`. Production parameter profiles are frozen inside each `run_*.bat`, so change the bat rather than ad-hoc flags when altering live behaviour. Trailing args to a `run_*.bat` are forwarded to the engine.

**Tests:** there is no pytest config. Tests are `tools/test_*.py` files with a self-running `main()`, and they also work under pytest. Run one with `python tools/test_gettarget_empty_book.py` (or `python -m pytest tools/test_x.py::test_name` if pytest is installed). The regression anchors are:
- `tools/test_gettarget_empty_book.py`
- `tools/test_publish_pages_push.py`
- the reconcile gate (`run_reconcile_gate.bat`)
- the RL AWK-vs-Python compare (DailyRun step 3c)

Several `tools/test_*poly*` / autopsy tests are PM leftovers.

## Architecture essentials

- **One shared engine, many systems.** `stock_analysis/rocket_tbn.py` (20k+ lines) hosts BRT, WPBR, YH, MTS, RL, RS, and others, selected by `-v` flags. Output prefixes stay system-named (`BRT_Closed_<ts>.csv`, etc.) in `drive/`.
  - **TBN** = the engine/platform. **BRT** = one system. Never rename `brt_zones` / `BRT_*` artifacts to TBN (`docs/TBN_VS_BRT.md`).
  - `rocket_brt.py` and `rocket_rs.py` are shims into it. SB and a few other engines are standalone files beside it.
- **DailyRun flow:** data refresh (auto-skips if fresh) → fund scorecard → RL (AWK `portfolio_audit.awk` is authoritative; Python RL must match it, and a mismatch fails the run) → parallel wave of ≤8 engines (`tools/dailyrun_wave.py`) → copy stamped outputs to `*_LatestRun_*` → reconcile gate against frozen Closed baselines → getTarget → publish. Step labels like `n/13` and `14/14` are historical and don't match reality.
- **Live sleeve list:** `DailyRun.bat` plus `DAILYRUN_REGISTRY` / `REPORT_ORDER` in `tools/dailyrun_system_status.py` are the only source of truth for wired systems. Adding a sleeve means updating all of these:
  - the bat step
  - the registry and report order
  - the system write-up (`tools/_gen_system_writeups.py` → `docs/systems/`)
  - reconcile coverage
- **IND is deprecated, and MVCP is retired.** Don't re-wire them.
- **Open book:** Paul edits `gettarget_positions.csv` (authoritative open lots). `getTarget.py` writes `getTarget_output.csv` and never touches positions. An empty, header-only book is valid: it must exit 0. `stock_analysis/live_style_sizing.py` computes Suggested shares. `generate_investment_report.py` and `scripts/publish_github_pages.py` render `docs/`.
- **Data:** canonical daily OHLCV is `data/newdata/data/{SYM}.csv`, mirrored in `data/ohlcv.duckdb`. DuckDB on Windows allows a single writer, so use read-only opens during the wave. Per-symbol approved params are in `stock_analysis/Per_Symbol_Optimized_Settings_Approved_Latest.json`.
- **Gitignored state:** `data/`, `drive/`, `local/` and `secrets/` are gitignored. Frozen experiment evidence and adopt notes live in `drive/paul_experiments/<stamp>/`.

## Working conventions

- **Research A/Bs** (`*_ab.bat`, `tools/_*.py` one-offs, root `tmp_*` dirs) are throwaway experiments, not runbook code. Freeze adopted results under `drive/paul_experiments/`. Production changes go into the `run_*.bat` profile, plus a reconcile baseline refresh if Closed output changes intentionally.
- **Production changes are governed.** Any change to a wired launcher, its universe CSV, the per-symbol JSON, or sizing/risk limits drifts `governance/production_lock.json` and halts new buys until `python tools/adopt.py --system <SYS> --change "..." --evidence drive/honest_bt/<stamp>` records it. Adoption needs a PIT `PASS` from `tools/honest_bt/score.py` and fits a 1-per-system / 3-total quarterly budget, or an explicit `--override` reason. Never edit the lock by hand.
- **Honest backtests** (`tools/honest_bt/`) are the bar for "does this system have an edge": survivor-free data, point-in-time universe, costs. In-sample curated-universe results are not evidence. Harness runs must never write to `drive/` root (it preflights and aborts if they would).
- **Archives:** `archive/root_oneoffs/`, `tools/archive/` hold retired one-offs. Don't wire anything from there.
- **Generated pages:** files under `docs/` (`investment.html`, `monthly.html`, `live_style*.html`, `index.html`, …) are regenerated on publish. Edit the generator, not the HTML. `docs/index.html` is the scanner-open report by design.
- **Paths:** use repo-relative paths. Many `tools/_*.py` files still hardcode `Downloads\stockresearch`, a legacy twin tree; don't copy that pattern.
- **Git noise:** the large `git status` diff is mostly CRLF/whitespace churn from the Windows checkout plus split-prune deletions. Check `git diff --ignore-all-space` before assuming files really changed, and don't mass-commit it.
- **When Paul reports a problem** with your output (a mismatch, a wrong number, a broken page), always answer three questions, then ship the fix and the prevention in the same turn when possible:
  1. How did this happen? Give the exact root cause.
  2. What are you doing to fix it?
  3. What are you doing so this, and anything like it, never happens again? That means a class-level guard plus a test or automated check.
