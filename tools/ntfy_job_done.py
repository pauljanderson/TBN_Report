#!/usr/bin/env python3
"""Notify phone via ntfy when an AI job finishes posting HTML to Drive.

Topics (public ntfy.sh; no secrets):
  drive/mark_experiments/**  -> https://ntfy.sh/mark_ai_job_done
  other Drive HTML           -> https://ntfy.sh/paul_ai_job_done

A job that writes both folders POSTs twice, each body listing only that side's paths.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import NamedTuple, Sequence

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


# Short waits for timeouts and server errors only. A 429 is not in this set:
# ntfy.sh allows about 250 messages/day per IP, and three quick retries burn that budget.
_RETRY_BACKOFF_S = (1.0, 2.0, 4.0)
_RETRY_STATUSES = frozenset({0, 408, 500, 502, 503, 504})
# Honor Retry-After only when it is a few minutes or less. A multi-hour daily reset
# must not block the pipeline.
_RETRY_AFTER_MAX_S = 180.0
# This PC often gets an AAAA for ntfy.sh first, then the IPv6 route hangs until the
# connect timeout. Try IPv4 first. Connect and read are separate so a slow body
# does not eat the connect budget.
_CONNECT_TIMEOUT_S = 20.0
_READ_TIMEOUT_S = 30.0


def _gai_ipv4_first(orig):
    """getaddrinfo wrapper: IPv4 before IPv6, and add an A lookup if only AAAA came back."""

    def getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        results = list(orig(host, port, family, type, proto, flags))
        if family not in (0, socket.AF_UNSPEC):
            return results
        if not any(row[0] == socket.AF_INET for row in results):
            try:
                results = list(orig(host, port, socket.AF_INET, type, proto, flags)) + results
            except OSError:
                pass
        results.sort(key=lambda row: 0 if row[0] == socket.AF_INET else 1)
        return results

    return getaddrinfo


class _HttpResult(NamedTuple):
    status: int
    retry_after_s: float | None
    body: str


def _retry_after_seconds(header: str | None) -> float | None:
    """Seconds from a Retry-After header (delta-seconds or HTTP-date). Uncapped."""
    if not header:
        return None
    text = header.strip()
    try:
        seconds = float(text)
    except ValueError:
        try:
            when = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        seconds = (when - datetime.now(timezone.utc)).total_seconds()
    if seconds < 0:
        return 0.0
    return seconds


def _clip_body(raw: bytes | str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = raw
    text = text.strip()
    if len(text) > 2000:
        return text[:2000]
    return text


def _json_obj(body: str) -> dict:
    if not body:
        return {}
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _is_daily_quota(body: str) -> bool:
    payload = _json_obj(body)
    if payload.get("code") == 42908:
        return True
    error = str(payload.get("error") or body or "").lower()
    return "daily" in error and "quota" in error


def _reset_note(body: str, retry_after_s: float | None) -> str:
    """Clock time to log when the daily cap is hit. Body wins over a header guess."""
    payload = _json_obj(body)
    for key in ("reset", "reset_at", "resets", "retry_at", "limit_reset"):
        value = payload.get(key)
        if value not in (None, ""):
            return f"reset from body {key}={value}"
    if retry_after_s is not None and retry_after_s > 0:
        when = datetime.now(timezone.utc) + timedelta(seconds=retry_after_s)
        return (
            f"Retry-After {retry_after_s:.0f}s "
            f"(about {when.strftime('%Y-%m-%d %H:%M UTC')})"
        )
    next_midnight = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) + timedelta(days=1)
    return (
        "429 body did not include a reset time; "
        "ntfy resets the daily message limit at midnight UTC "
        f"(next {next_midnight.strftime('%Y-%m-%d %H:%M UTC')})"
    )


def _post_once(url: str, data: str, title: str) -> _HttpResult:
    """Return HTTP status, Retry-After seconds, and a short response body.

    Status 0 means the request never got an HTTP response (timeout or network).
    """
    headers = {"Title": title}
    orig_gai = socket.getaddrinfo
    socket.getaddrinfo = _gai_ipv4_first(orig_gai)
    try:
        return _post_once_resolved(url, data, headers)
    finally:
        socket.getaddrinfo = orig_gai


def _post_once_resolved(url: str, data: str, headers: dict[str, str]) -> _HttpResult:
    try:
        import requests

        try:
            resp = requests.post(
                url,
                data=data.encode("utf-8"),
                headers=headers,
                timeout=(_CONNECT_TIMEOUT_S, _READ_TIMEOUT_S),
            )
        except Exception as exc:  # noqa: BLE001 — never break pipelines
            print(f"WARNING: ntfy notify failed ({exc})", file=sys.stderr)
            return _HttpResult(0, None, "")
        return _HttpResult(
            int(resp.status_code),
            _retry_after_seconds(resp.headers.get("Retry-After")),
            _clip_body(resp.text),
        )
    except ImportError:
        pass

    try:
        from urllib.error import HTTPError, URLError
        from urllib.request import Request, urlopen

        req = Request(url, data=data.encode("utf-8"), headers=headers, method="POST")
        with urlopen(req, timeout=_READ_TIMEOUT_S) as resp:
            raw = resp.headers.get("Retry-After") if getattr(resp, "headers", None) else None
            return _HttpResult(
                int(getattr(resp, "status", 200) or 200),
                _retry_after_seconds(raw),
                _clip_body(resp.read()),
            )
    except HTTPError as exc:
        raw = exc.headers.get("Retry-After") if getattr(exc, "headers", None) else None
        try:
            err_body = exc.read()
        except Exception:  # noqa: BLE001
            err_body = b""
        return _HttpResult(int(exc.code), _retry_after_seconds(raw), _clip_body(err_body))
    except (URLError, TimeoutError, OSError) as exc:
        print(f"WARNING: ntfy notify failed ({exc})", file=sys.stderr)
        return _HttpResult(0, None, "")
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: ntfy notify failed ({exc})", file=sys.stderr)
        return _HttpResult(0, None, "")


def _log_rate_limit(result: _HttpResult, *, retrying: bool) -> None:
    payload = _json_obj(result.body)
    error = str(payload.get("error") or result.body or "rate limited")
    if _is_daily_quota(result.body):
        detail = f"daily message quota; {_reset_note(result.body, result.retry_after_s)}"
    elif result.retry_after_s is not None:
        detail = f"Retry-After {result.retry_after_s:.0f}s"
    else:
        detail = "no Retry-After; not retrying"
    action = "one retry" if retrying else "not retrying"
    print(
        f"WARNING: ntfy HTTP 429 ({action}): {error}; {detail}",
        file=sys.stderr,
    )


def _post(url: str, data: str, title: str) -> int:
    """POST once. Retry timeouts and 5xx briefly. Do not storm ntfy on HTTP 429."""
    result = _post_once(url, data, title)
    if result.status and 200 <= result.status < 300:
        return result.status
    if result.status == 429:
        short_wait = (
            result.retry_after_s is not None
            and result.retry_after_s <= _RETRY_AFTER_MAX_S
            and not _is_daily_quota(result.body)
        )
        _log_rate_limit(result, retrying=short_wait)
        if not short_wait or result.retry_after_s is None:
            return result.status
        time.sleep(result.retry_after_s)
        result = _post_once(url, data, title)
        if result.status == 429:
            _log_rate_limit(result, retrying=False)
        return result.status
    for delay in _RETRY_BACKOFF_S:
        if result.status and 200 <= result.status < 300:
            return result.status
        if result.status not in _RETRY_STATUSES:
            return result.status
        wait = delay
        if (
            result.retry_after_s is not None
            and result.retry_after_s <= _RETRY_AFTER_MAX_S
        ):
            wait = result.retry_after_s
        print(
            f"WARNING: ntfy HTTP {result.status or 'timeout'} retry in {wait:.0f}s",
            file=sys.stderr,
        )
        time.sleep(wait)
        result = _post_once(url, data, title)
    return result.status


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
