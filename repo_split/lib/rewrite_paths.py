#!/usr/bin/env python3
"""Rewrite hardcoded stockresearch paths after the three-repo move.

Also hard-fixes a few known critical bats to use %~dp0 instead of absolute cds.

Usage:
  python rewrite_paths.py --root C:\\Users\\songg\\code\\TBN --new-root C:\\Users\\songg\\code\\TBN
  python rewrite_paths.py --root C:\\Users\\songg\\code\\PredictionsMarkets --new-root C:\\Users\\songg\\code\\PredictionsMarkets
  python rewrite_paths.py --root C:\\Users\\songg\\code\\Spotify --new-root C:\\Users\\songg\\code\\Spotify
  python rewrite_paths.py --audit-only --root ROOT
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from paths_config import OLD_ROOT_STRINGS, TEXT_SUFFIXES

SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "data",
    "local",
    "drive",
    "Drive",
    "drive_real_materialize",
    "drive_robocopy_backup",
    "logs",
    "secrets",
    ".cursor",
}


def _skip_dir(path: Path) -> bool:
    for part in path.parts:
        if part in SKIP_DIR_NAMES:
            return True
        # Experiment / scratch trees (tmp_wpbr_*, etc.)
        if part.startswith("tmp_") or part.startswith("_tmp_"):
            return True
    return False


def iter_text_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if _skip_dir(path):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {
            "Dockerfile",
            "Makefile",
        }:
            continue
        yield path


def audit(root: Path) -> list[tuple[Path, int]]:
    hits: list[tuple[Path, int]] = []
    for path in iter_text_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        count = 0
        for old in OLD_ROOT_STRINGS:
            count += text.count(old)
        # also catch path without drive letter variants used in comments
        count += len(re.findall(r"(?i)Downloads[\\/]+stockresearch", text))
        if count:
            hits.append((path, count))
    return hits


def rewrite_file(path: Path, new_root: str) -> int:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 0
    original = text
    new_fwd = new_root.replace("\\", "/")
    new_bwd = new_root.replace("/", "\\")

    def _repl(match: re.Match[str]) -> str:
        s = match.group(0)
        return new_bwd if "\\" in s else new_fwd

    text = re.sub(
        r"(?i)C:[\\/]Users[\\/]songg[\\/]Downloads[\\/]stockresearch",
        _repl,
        text,
    )
    if text != original:
        path.write_text(text, encoding="utf-8", newline="\n")
        return 1
    return 0


def fix_critical_bats(root: Path) -> list[str]:
    """Force DailyRun and known absolute-cd bats to use %~dp0."""
    fixed: list[str] = []
    daily = root / "DailyRun.bat"
    if daily.exists():
        text = daily.read_text(encoding="utf-8", errors="ignore")
        new = re.sub(
            r'(?im)^cd /d "C:\\Users\\songg\\(?:Downloads\\stockresearch|code\\TBN)"\s*$',
            r'cd /d "%~dp0"',
            text,
        )
        new = re.sub(
            r'(?im)^cd /d "C:/Users/songg/(?:Downloads/stockresearch|code/TBN)"\s*$',
            r'cd /d "%~dp0"',
            new,
        )
        if new != text:
            daily.write_text(new, encoding="utf-8", newline="\n")
            fixed.append("DailyRun.bat -> cd /d \"%~dp0\"")

    merge = root / "merge_thin_first_into_gtc.bat"
    if merge.exists():
        text = merge.read_text(encoding="utf-8", errors="ignore")
        new = text
        for old in OLD_ROOT_STRINGS:
            new = new.replace(old, str(root))
        # Prefer batch-relative
        new = re.sub(
            r'(?im)^cd /d "C:\\Users\\songg\\(?:Downloads\\stockresearch|code\\PredictionsMarkets)"\s*$',
            r'cd /d "%~dp0"',
            new,
        )
        if new != text:
            merge.write_text(new, encoding="utf-8", newline="\n")
            fixed.append("merge_thin_first_into_gtc.bat")

    # TBN git_pull: strip kitchen rebuild (PM owns that)
    git_pull = root / "git_pull.bat"
    if git_pull.exists() and (root / "DailyRun.bat").exists() and not (
        root / "tools" / "live_lock_orders.py"
    ).exists():
        text = git_pull.read_text(encoding="utf-8", errors="ignore")
        if "run_rebuild_kitchen_dashboard.bat" in text:
            slim = """@echo off
rem Pull the latest main from GitHub onto this PC (TBN).
setlocal EnableExtensions
cd /d "%~dp0"

echo === git pull origin main ===
git checkout main
if errorlevel 1 (
  echo Could not switch to main.
  goto :done
)
git pull origin main
if errorlevel 1 (
  echo Pull failed. Commit/stash local edits, then retry.
  goto :done
)
echo.
echo Up to date with origin/main.
git log -1 --oneline
echo.
echo Kitchen/prediction dashboard rebuild lives in PredictionsMarkets now.
echo Run that repo's git_pull.bat or run_rebuild_kitchen_dashboard.bat there.

:done
echo.
pause
exit /b 0
"""
            git_pull.write_text(slim, encoding="utf-8", newline="\n")
            fixed.append("git_pull.bat (TBN slim — kitchen moved)")

    # Strip spotipy from TBN requirements if present and no spotify tools
    req = root / "requirements.txt"
    if req.exists() and not (root / "tools" / "sync_spotify_year_playlists.py").exists():
        text = req.read_text(encoding="utf-8")
        lines = [
            ln
            for ln in text.splitlines()
            if "spotipy" not in ln.lower() and "Spotify year-playlist" not in ln
        ]
        new = "\n".join(lines).rstrip() + "\n"
        if new != text:
            req.write_text(new, encoding="utf-8")
            fixed.append("requirements.txt (removed spotipy)")

    return fixed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--new-root", type=Path, help="Absolute path that replaces stockresearch")
    ap.add_argument("--audit-only", action="store_true")
    args = ap.parse_args()

    root = args.root
    if not root.exists():
        print(f"Root not found: {root}", file=sys.stderr)
        return 1

    if args.audit_only:
        hits = audit(root)
        print(f"Hardcoded stockresearch hits in {root}: {len(hits)} files")
        for path, count in sorted(hits, key=lambda x: (-x[1], str(x[0])))[:80]:
            print(f"  {count:4d}  {path.relative_to(root)}")
        if len(hits) > 80:
            print(f"  ... {len(hits) - 80} more")
        return 0 if not hits else 1

    new_root = str(args.new_root or root)
    changed = 0
    for path in iter_text_files(root):
        changed += rewrite_file(path, new_root)
    fixed = fix_critical_bats(root)
    print(f"Rewrote {changed} files under {root}")
    for item in fixed:
        print(f"  critical: {item}")
    leftovers = audit(root)
    print(f"Remaining stockresearch string hits: {len(leftovers)} files")
    for path, count in leftovers[:20]:
        print(f"  {count:4d}  {path.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
