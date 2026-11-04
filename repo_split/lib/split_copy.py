#!/usr/bin/env python3
"""Copy owned files from the monorepo into PredictionsMarkets or Spotify.

Usage:
  python split_copy.py --target predictions --source ROOT --dest DEST
  python split_copy.py --target spotify --source ROOT --dest DEST
  python split_copy.py --target predictions --source ROOT --dest DEST --runtime
  python split_copy.py --prune-from-tbn --tbn ROOT   # delete moved code from TBN after verify
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from paths_config import (
    DEFAULT_PM,
    DEFAULT_SOURCE,
    DEFAULT_SPOTIFY,
    DEFAULT_TBN,
    read_manifest,
)


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        print(f"  skip missing runtime: {src}")
        return
    if src.is_file():
        _copy_file(src, dst)
        print(f"  file {src.name}")
        return
    if dst.exists():
        print(f"  runtime already exists: {dst}")
        return
    shutil.copytree(src, dst)
    print(f"  tree {src} -> {dst}")


def copy_manifest(source: Path, dest: Path, manifest_name: str) -> tuple[int, int]:
    copied = 0
    missing = 0
    for rel in read_manifest(manifest_name):
        src = source / rel
        dst = dest / rel
        if not src.exists():
            print(f"  MISSING {rel}")
            missing += 1
            continue
        _copy_file(src, dst)
        copied += 1
    return copied, missing


def copy_runtime(source: Path, dest: Path, runtime_manifest: str) -> None:
    print(f"=== runtime from {runtime_manifest} ===")
    for rel in read_manifest(runtime_manifest):
        _copy_tree(source / rel, dest / rel)


def write_scaffold(dest: Path, kind: str) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    gitignore = dest / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(
            "\n".join(
                [
                    "data/",
                    "Drive/",
                    "drive/",
                    "local/",
                    "logs/",
                    "*.duckdb",
                    "__pycache__/",
                    "*.pyc",
                    ".env",
                    "secrets/",
                    ".venv/",
                    "venv/",
                    "*.csv",
                    "*.png",
                    "*.jpg",
                    "*.log",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    if kind == "predictions":
        req = dest / "requirements.txt"
        if not req.exists():
            req.write_text(
                "\n".join(
                    [
                        "numpy>=2.2,<3",
                        "pandas>=2.3,<3",
                        "requests>=2.32",
                        "matplotlib>=3.10",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
        readme = dest / "README.md"
        if not readme.exists():
            readme.write_text(
                "# PredictionsMarkets\n\n"
                "Kalshi / Polymarket / Gemini / Novig live systems, kitchen dashboard, "
                "and venue↔kitchen reconcile.\n\n"
                "Split from the former stockresearch monorepo.\n"
                "Runtime stamp: `drive/paul_experiments/prediction_market_arb_exhaustive_20261017/`\n"
                "Local tape: `local/paul_experiments/prediction_market_arb_exhaustive_20261017/raw/`\n"
                "Secrets: `secrets/` (local only).\n",
                encoding="utf-8",
            )
        # Slim git_pull stays as copied from monorepo (has kitchen rebuild).

    if kind == "spotify":
        req = dest / "requirements.txt"
        if not req.exists():
            req.write_text("spotipy>=2.26\nrequests>=2.32\n", encoding="utf-8")
        readme = dest / "README.md"
        if not readme.exists():
            readme.write_text(
                "# Spotify\n\n"
                "Year playlists, liked songs, AOTY listen, upcoming shows.\n\n"
                "Split from the former stockresearch monorepo.\n"
                "Put `secrets/spotify.env` from `tools/spotify.env.example`.\n"
                "Caches live under `drive/spotify_*`.\n",
                encoding="utf-8",
            )


def prune_from_tbn(tbn: Path, manifest_names: list[str]) -> int:
    """Delete extracted code files from TBN after the new repos are verified."""
    deleted = 0
    for name in manifest_names:
        for rel in read_manifest(name):
            # Never delete shared helpers TBN still needs after PM extract.
            # These are copied into PredictionsMarkets; TBN keeps its own copy.
            # ntfy_job_done: used by hundreds of TBN WPBR/RL bats + PM live_lock.
            if rel in {
                "report_page_extras.py",
                "resolve_python.bat",
                "tools/ntfy_job_done.py",
            }:
                continue
            # TBN keeps its own git_pull after we rewrite it — do not delete via spotify.
            if name.startswith("spotify") and rel == "git_pull.bat":
                continue
            path = tbn / rel
            if path.is_file():
                path.unlink()
                deleted += 1
                print(f"  deleted {rel}")
            elif path.is_dir():
                shutil.rmtree(path)
                deleted += 1
                print(f"  deleted dir {rel}")
    return deleted


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["predictions", "spotify"])
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--dest", type=Path)
    ap.add_argument("--runtime", action="store_true", help="Also copy drive/local/secrets runtime dirs")
    ap.add_argument("--prune-from-tbn", action="store_true")
    ap.add_argument("--tbn", type=Path, default=DEFAULT_TBN)
    args = ap.parse_args()

    if args.prune_from_tbn:
        n = prune_from_tbn(
            args.tbn,
            ["predictions_files.txt", "spotify_files.txt"],
        )
        # Remove PM docs folder if empty parents remain
        pm_docs = args.tbn / "docs" / "prediction_market"
        if pm_docs.exists() and not any(pm_docs.rglob("*")):
            shutil.rmtree(pm_docs, ignore_errors=True)
        print(f"Pruned {n} paths from {args.tbn}")
        return 0

    if not args.target:
        print("--target required unless --prune-from-tbn", file=sys.stderr)
        return 2

    source = args.source
    if args.target == "predictions":
        dest = args.dest or DEFAULT_PM
        manifest = "predictions_files.txt"
        runtime = "predictions_runtime.txt"
        kind = "predictions"
    else:
        dest = args.dest or DEFAULT_SPOTIFY
        manifest = "spotify_files.txt"
        runtime = "spotify_runtime.txt"
        kind = "spotify"

    if not source.exists():
        print(f"Source not found: {source}", file=sys.stderr)
        return 1

    print(f"=== copy {kind}: {source} -> {dest} ===")
    write_scaffold(dest, kind)
    copied, missing = copy_manifest(source, dest, manifest)
    print(f"Copied {copied} files ({missing} missing)")

    if args.runtime:
        copy_runtime(source, dest, runtime)
        # Spotify: only need spotify.env from secrets if whole secrets was not listed as dir
        if kind == "spotify":
            src_env = source / "secrets" / "spotify.env"
            if src_env.exists():
                _copy_file(src_env, dest / "secrets" / "spotify.env")
                print("  copied secrets/spotify.env")
        if kind == "predictions":
            # Prefer venue secrets; copy whole secrets/ then remove spotify.env from PM copy
            sec = dest / "secrets"
            spot = sec / "spotify.env"
            if spot.exists():
                spot.unlink()
                print("  removed secrets/spotify.env from PredictionsMarkets copy")

    print("Done.")
    return 0 if missing == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
