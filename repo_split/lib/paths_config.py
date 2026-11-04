"""Shared path defaults for the three-repo split on Paul's Windows PC."""
from __future__ import annotations

from pathlib import Path

# Source monorepo (current location on Paul's machine)
DEFAULT_SOURCE = Path(r"C:\Users\songg\Downloads\stockresearch")

# Target roots
DEFAULT_TBN = Path(r"C:\Users\songg\code\TBN")
DEFAULT_PM = Path(r"C:\Users\songg\code\PredictionsMarkets")
DEFAULT_SPOTIFY = Path(r"C:\Users\songg\code\Spotify")

# GitHub
GITHUB_OWNER = "pauljanderson"
TBN_REMOTE = f"https://github.com/{GITHUB_OWNER}/TBN_Report.git"
PM_REPO_NAME = "PredictionsMarkets"
SPOTIFY_REPO_NAME = "Spotify"

OLD_ROOT_STRINGS = [
    r"C:\Users\songg\Downloads\stockresearch",
    r"C:/Users/songg/Downloads/stockresearch",
    r"c:\Users\songg\Downloads\stockresearch",
    r"c:/Users/songg/Downloads/stockresearch",
]

TEXT_SUFFIXES = {
    ".py",
    ".bat",
    ".ps1",
    ".awk",
    ".md",
    ".txt",
    ".json",
    ".html",
    ".yml",
    ".yaml",
    ".mdc",
    ".example",
}


def repo_split_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def manifests_dir() -> Path:
    return repo_split_dir() / "manifests"


def read_manifest(name: str) -> list[str]:
    path = manifests_dir() / name
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line.replace("\\", "/"))
    return lines
