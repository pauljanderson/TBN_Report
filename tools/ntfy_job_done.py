#!/usr/bin/env python3
"""Notify phone via ntfy when an AI job finishes posting HTML to Drive.

Topics (public ntfy.sh; no secrets):
  drive/mark_experiments/**  -> https://ntfy.sh/mark_ai_job_done
  other Drive HTML           -> https://ntfy.sh/paul_ai_job_done

A job that writes both folders POSTs twice, each body listing only that side's paths.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Sequence

PAUL_TOPIC = "paul_ai_job_done"
MARK_TOPIC = "mark_ai_job_done"
NTFY_BASE = "https://ntfy.sh"
DEFAULT_TITLE = "AI job done"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _rel_path(path: Path) -> str:
    root = _repo_root()
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _norm(path: Path) -> str:
    return _rel_path(path).replace("\\", "/").lower()


def _is_mark_path(path: Path) -> bool:
    rel = _norm(path)
    return "/mark_experiments/" in f"/{rel}/" or rel.startswith("drive/mark_experiments/")


def _topics_for_paths(paths: Sequence[Path], audience: str) -> dict[str, list[Path]]:
    """Map ntfy topic -> paths that belong on that ping."""
    if audience == "mark":
        return {MARK_TOPIC: list(paths)}
    if audience == "paul":
        return {PAUL_TOPIC: list(paths)}
    if not paths:
        return {PAUL_TOPIC: []}
    mark = [p for p in paths if _is_mark_path(p)]
    paul = [p for p in paths if not _is_mark_path(p)]
    out: dict[str, list[Path]] = {}
    if mark:
        out[MARK_TOPIC] = mark
    if paul:
        out[PAUL_TOPIC] = paul
    return out


def _build_message(message: str | None, paths: Sequence[Path]) -> str:
    if message:
        return message
    if not paths:
        return "AI job done — HTML on Drive"
    rels = [_rel_path(p) for p in paths]
    if len(rels) == 1:
        return f"AI job done — HTML on Drive: {rels[0]}"
    joined = "; ".join(rels)
    return f"AI job done — HTML on Drive ({len(rels)} files): {joined}"


# A few short waits. 429 and timeouts are common when many trade pings fire together.
_RETRY_BACKOFF_S = (1.0, 2.0, 4.0)
_RETRY_STATUSES = frozenset({0, 408, 429, 500, 502, 503, 504})


def _retry_after_seconds(header: str | None) -> float | None:
    if not header:
        return None
    try:
        seconds = float(header.strip())
    except ValueError:
        return None
    if seconds < 0:
        return None
    return min(seconds, 8.0)


def _post_once(url: str, data: str, title: str) -> tuple[int, float | None]:
    """Return HTTP status and a short Retry-After, if the server sent one.

    Status 0 means the request never got an HTTP response (timeout or network).
    """
    headers = {"Title": title}
    try:
        import requests

        try:
            resp = requests.post(url, data=data.encode("utf-8"), headers=headers, timeout=12)
        except Exception as exc:  # noqa: BLE001 — never break pipelines
            print(f"WARNING: ntfy notify failed ({exc})", file=sys.stderr)
            return 0, None
        return int(resp.status_code), _retry_after_seconds(resp.headers.get("Retry-After"))
    except ImportError:
        pass

    try:
        from urllib.error import HTTPError, URLError
        from urllib.request import Request, urlopen

        req = Request(url, data=data.encode("utf-8"), headers=headers, method="POST")
        with urlopen(req, timeout=12) as resp:
            raw = resp.headers.get("Retry-After") if getattr(resp, "headers", None) else None
            return int(getattr(resp, "status", 200) or 200), _retry_after_seconds(raw)
    except HTTPError as exc:
        raw = exc.headers.get("Retry-After") if getattr(exc, "headers", None) else None
        return int(exc.code), _retry_after_seconds(raw)
    except (URLError, TimeoutError, OSError) as exc:
        print(f"WARNING: ntfy notify failed ({exc})", file=sys.stderr)
        return 0, None
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: ntfy notify failed ({exc})", file=sys.stderr)
        return 0, None


def _post(url: str, data: str, title: str) -> int:
    """POST once, then a few short retries on rate limit, timeout, or a server error."""
    status, retry_after = _post_once(url, data, title)
    for delay in _RETRY_BACKOFF_S:
        if status and 200 <= status < 300:
            return status
        if status not in _RETRY_STATUSES:
            return status
        wait = retry_after if retry_after is not None else delay
        print(
            f"WARNING: ntfy HTTP {status or 'timeout'} retry in {wait:.0f}s",
            file=sys.stderr,
        )
        time.sleep(wait)
        status, retry_after = _post_once(url, data, title)
    return status


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="POST a phone notification when an AI job writes HTML under drive/."
    )
    parser.add_argument("-m", "--message", default=None, help="Notification body")
    parser.add_argument("-t", "--title", default=DEFAULT_TITLE, help="Notification title")
    parser.add_argument(
        "-p",
        "--path",
        action="append",
        default=[],
        dest="paths",
        help="HTML path under drive/ (repeatable)",
    )
    parser.add_argument(
        "--audience",
        choices=("auto", "mark", "paul"),
        default="auto",
        help="auto = mark_experiments paths to Mark's topic, everything else to Paul's",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="No-op (reserved); kept for CLI compatibility",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    paths = [Path(p) for p in args.paths]
    grouped = _topics_for_paths(paths, args.audience)
    for topic, topic_paths in grouped.items():
        body = _build_message(args.message, topic_paths)
        url = f"{NTFY_BASE}/{topic}"
        status = _post(url, body, args.title)
        if status and 200 <= status < 300:
            print(f"ntfy ok HTTP {status} topic={topic}: {body}")
        elif status:
            print(f"WARNING: ntfy HTTP {status} topic={topic}: {body}", file=sys.stderr)
    # Always exit 0 so pipelines are not broken by notify failures.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
