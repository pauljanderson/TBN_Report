#!/usr/bin/env python3
"""Smoke-check that each split repo has the files it needs to boot."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from paths_config import DEFAULT_PM, DEFAULT_SPOTIFY, DEFAULT_TBN


def check(label: str, root: Path, required: list[str]) -> list[str]:
    errs: list[str] = []
    if not root.exists():
        return [f"{label}: root missing: {root}"]
    for rel in required:
        if not (root / rel).exists():
            errs.append(f"{label}: missing {rel}")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tbn", type=Path, default=DEFAULT_TBN)
    ap.add_argument("--pm", type=Path, default=DEFAULT_PM)
    ap.add_argument("--spotify", type=Path, default=DEFAULT_SPOTIFY)
    args = ap.parse_args()

    errs: list[str] = []
    errs += check(
        "TBN",
        args.tbn,
        [
            "DailyRun.bat",
            "stock_analysis/rocket_brt.py",
            "resolve_python.bat",
            "git_checkin.bat",
            "requirements.txt",
        ],
    )
    # TBN should NOT still own Spotify/PM launchers after prune (warn only if present before prune)
    errs += check(
        "PredictionsMarkets",
        args.pm,
        [
            "tools/prediction_paths.py",
            "tools/live_lock_orders.py",
            "tools/write_dashboard.py",
            "tools/pm_venue_kitchen_check.py",
            "run_prediction_start.bat",
            "run_pm_venue_kitchen_check.bat",
            "report_page_extras.py",
            "resolve_python.bat",
        ],
    )
    errs += check(
        "Spotify",
        args.spotify,
        [
            "tools/sync_spotify_year_playlists.py",
            "tools/spotify.env.example",
            "run_sync_spotify_year_playlists.bat",
            "run_spotify_playlist_tasks.bat",
            "resolve_python.bat",
            "requirements.txt",
        ],
    )

    # Soft checks
    warns: list[str] = []
    if (args.tbn / "tools" / "live_lock_orders.py").exists():
        warns.append("TBN still contains live_lock_orders.py (run 07_prune_tbn.bat after verify)")
    if (args.tbn / "tools" / "sync_spotify_year_playlists.py").exists():
        warns.append("TBN still contains Spotify tools (run 07_prune_tbn.bat after verify)")
    if not (args.pm / "secrets").exists():
        warns.append("PredictionsMarkets has no secrets/ yet — copy venue keys before live trading")
    if not (args.spotify / "secrets" / "spotify.env").exists():
        warns.append("Spotify missing secrets/spotify.env — copy from old secrets or fill example")

    for w in warns:
        print(f"WARN: {w}")
    if errs:
        print("FAIL:")
        for e in errs:
            print(f"  {e}")
        return 1
    print("OK: TBN, PredictionsMarkets, and Spotify layouts look bootable.")
    print(f"  TBN:               {args.tbn}")
    print(f"  PredictionsMarkets:{args.pm}")
    print(f"  Spotify:           {args.spotify}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
