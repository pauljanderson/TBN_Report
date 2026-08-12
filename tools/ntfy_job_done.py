#!/usr/bin/env python3
"""Notify phone via ntfy when an AI job finishes posting HTML to Drive."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

NTFY_URL = "https://ntfy.sh/paul_ai_job_done"
DEFAULT_TITLE = "AI job done"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _rel_path(path: Path) -> str:
    root = _repo_root()
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


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


def _post(url: str, data: str, title: str) -> int:
    headers = {"Title": title}
    try:
        import requests

        resp = requests.post(url, data=data.encode("utf-8"), headers=headers, timeout=15)
        return int(resp.status_code)
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001 — never break pipelines
        print(f"WARNING: ntfy notify failed ({exc})", file=sys.stderr)
        return 0

    try:
        from urllib.error import URLError, HTTPError
        from urllib.request import Request, urlopen

        req = Request(url, data=data.encode("utf-8"), headers=headers, method="POST")
        with urlopen(req, timeout=15) as resp:
            return int(getattr(resp, "status", 200) or 200)
    except HTTPError as exc:
        return int(exc.code)
    except (URLError, TimeoutError, OSError) as exc:
        print(f"WARNING: ntfy notify failed ({exc})", file=sys.stderr)
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: ntfy notify failed ({exc})", file=sys.stderr)
        return 0


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
        "--open",
        action="store_true",
        help="No-op (reserved); kept for CLI compatibility",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    paths = [Path(p) for p in args.paths]
    body = _build_message(args.message, paths)
    status = _post(NTFY_URL, body, args.title)
    if status and 200 <= status < 300:
        print(f"ntfy ok HTTP {status}: {body}")
    elif status:
        print(f"WARNING: ntfy HTTP {status}: {body}", file=sys.stderr)
    # Always exit 0 so pipelines are not broken by notify failures.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
