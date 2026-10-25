#!/usr/bin/env python3
"""Tiny TTL JSON cache used by Spotify sync tools."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIBRARY_CACHE_PATH = REPO_ROOT / "drive" / "spotify_library_cache" / "library.json"
DEFAULT_LIBRARY_CACHE_HOURS = 24.0


class JsonCache:
    def __init__(self, path: Path, ttl_hours: float) -> None:
        self.path = path
        self.ttl_hours = ttl_hours
        self.data = self._load()

    def _load(self) -> dict:
        if not self.path.is_file():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data) + "\n", encoding="utf-8")

    def get(self, key: str):
        row = self.data.get(key)
        if not isinstance(row, dict) or "fetched_at" not in row or "value" not in row:
            return None
        try:
            fetched = datetime.fromisoformat(row["fetched_at"])
        except ValueError:
            return None
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        if self.ttl_hours >= 0 and datetime.now(timezone.utc) - fetched > timedelta(hours=self.ttl_hours):
            return None
        return row["value"]

    def set(self, key: str, value) -> None:
        self.data[key] = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "value": value,
        }
        self.save()


def library_cache(ttl_hours: float = DEFAULT_LIBRARY_CACHE_HOURS, path: Path | None = None) -> JsonCache:
    return JsonCache(path or DEFAULT_LIBRARY_CACHE_PATH, ttl_hours=ttl_hours)
