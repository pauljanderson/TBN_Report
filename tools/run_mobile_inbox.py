#!/usr/bin/env python3
"""Poll drive/mobile_inbox/commands_pending.txt and run whitelist-only actions.

Unknown / free-text lines are ignored. No arbitrary shell. Archives executed
lines to drive/mobile_inbox/archive/commands_done_YYYYMMDD.log and ntfy notifies.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "drive" / "mobile_inbox"
PENDING = INBOX / "commands_pending.txt"
ARCHIVE_DIR = INBOX / "archive"
ET = ZoneInfo("America/New_York")

# Whitelist: token -> runner. Never map free text or user paths.
WHITELIST: dict[str, str] = {
    "ingest_trades": "ingest_trades",
    "apply_gettarget_patch": "apply_gettarget_patch",
    "run_gettarget": "run_gettarget",
    "regen_reports": "regen_reports",
    "publish_pages_push": "publish_pages_push",
    # Optional research sleeve — calls run_vz.bat with NO extra args (sibling may be editing CLI).
    "run_vz": "run_vz",
}


def _ntfy(title: str, message: str, paths: Optional[list[Path]] = None) -> None:
    script = ROOT / "tools" / "ntfy_job_done.py"
    cmd = [sys.executable, str(script), "-t", title, "-m", message]
    for p in paths or []:
        cmd.extend(["--path", str(p)])
    try:
        subprocess.run(cmd, cwd=str(ROOT), check=False)
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: ntfy failed: {exc}", file=sys.stderr)


def _run_bat(name: str, extra: list[str] | None = None) -> int:
    bat = ROOT / name
    if not bat.is_file():
        print(f"ERROR: missing {bat}", file=sys.stderr)
        return 2
    cmd = ["cmd", "/c", str(bat)]
    if extra:
        cmd.extend(extra)
    print(f"+ {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(ROOT))
    return int(proc.returncode)


def _run_py(rel: str, args: list[str] | None = None) -> int:
    script = ROOT / rel
    cmd = [sys.executable, str(script)] + (args or [])
    print(f"+ {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(ROOT))
    return int(proc.returncode)


def _action_ingest_trades() -> int:
    return _run_py("tools/ingest_mobile_trades.py")


def _action_apply_gettarget_patch() -> int:
    return _run_py("tools/ingest_mobile_trades.py", ["--apply-patch-only"])


def _action_run_gettarget() -> int:
    return _run_bat("run_gettarget.bat")


def _action_regen_reports() -> int:
    # Investment + monthly; no git push.
    rc1 = _run_py("generate_investment_report.py")
    rc2 = _run_py("generate_monthly_system_report.py")
    return rc1 or rc2


def _action_publish_pages_push() -> int:
    return _run_bat("publish_github_pages.bat", ["--push"])


def _action_run_vz() -> int:
    # No %* passthrough from phone — whitelist only, default freeze.
    return _run_bat("run_vz.bat")


ACTIONS: dict[str, Callable[[], int]] = {
    "ingest_trades": _action_ingest_trades,
    "apply_gettarget_patch": _action_apply_gettarget_patch,
    "run_gettarget": _action_run_gettarget,
    "regen_reports": _action_regen_reports,
    "publish_pages_push": _action_publish_pages_push,
    "run_vz": _action_run_vz,
}


def _read_pending(path: Path) -> list[tuple[str, str]]:
    """Return list of (raw_line, token) for executable whitelist lines."""
    if not path.is_file():
        return []
    out: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        raw = line.rstrip("\n")
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # First token only; ignore anything after whitespace (no args from phone).
        token = stripped.split()[0].strip().lower().replace("-", "_")
        # Allow aliases without underscores
        aliases = {
            "publishpagespush": "publish_pages_push",
            "publish_pages": "publish_pages_push",
            "gettarget": "run_gettarget",
            "ingest": "ingest_trades",
            "patch_gettarget": "apply_gettarget_patch",
            "apply_patch": "apply_gettarget_patch",
        }
        token = aliases.get(token, token)
        if token not in WHITELIST:
            print(f"IGNORE unknown command: {stripped!r}")
            continue
        out.append((raw, token))
    return out


def _archive_done(lines: list[str], results: list[str]) -> Path:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(ET).strftime("%Y%m%d")
    path = ARCHIVE_DIR / f"commands_done_{stamp}.log"
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S %Z")
    with path.open("a", encoding="utf-8") as f:
        for line, res in zip(lines, results):
            f.write(f"{now}\t{line}\t{res}\n")
    return path


def _reset_pending(path: Path, keep_comments: bool = True) -> None:
    header = (
        "# Mobile command inbox — one whitelist token per line.\n"
        "# Tokens: ingest_trades | apply_gettarget_patch | run_gettarget | "
        "regen_reports | publish_pages_push | run_vz\n"
        "# Unknown lines are ignored. No free-text shell.\n"
    )
    if keep_comments and path.is_file():
        kept = []
        for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            s = line.strip()
            if s.startswith("#") or not s:
                kept.append(line)
            # drop executed / unknown tokens from pending
        path.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")
        return
    path.write_text(header, encoding="utf-8")


def run_inbox(*, dry_run: bool = False) -> int:
    INBOX.mkdir(parents=True, exist_ok=True)
    if not PENDING.is_file():
        _reset_pending(PENDING, keep_comments=False)

    pending = _read_pending(PENDING)
    if not pending:
        print("No whitelist commands pending.")
        return 0

    print(f"Pending: {[t for _, t in pending]}")
    if dry_run:
        print("dry-run — not executing")
        return 0

    raw_lines: list[str] = []
    results: list[str] = []
    worst = 0
    for raw, token in pending:
        fn = ACTIONS[token]
        try:
            rc = int(fn())
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR running {token}: {exc}", file=sys.stderr)
            rc = 1
        status = f"rc={rc}"
        raw_lines.append(token)
        results.append(status)
        worst = worst or rc
        print(f"{token} -> {status}")

    log_path = _archive_done(raw_lines, results)
    _reset_pending(PENDING, keep_comments=True)

    guide = INBOX / "HOW_TO_MOBILE.html"
    ok = worst == 0
    title = "Mobile inbox OK" if ok else "Mobile inbox FAILED"
    body = (
        f"commands={','.join(raw_lines)} results={','.join(results)} "
        f"log={log_path.name}"
    )
    _ntfy(title, body, paths=[guide] if guide.is_file() else None)
    return worst


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Run whitelisted mobile inbox commands")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--list",
        action="store_true",
        help="Print whitelist tokens and exit",
    )
    args = p.parse_args(argv)
    if args.list:
        for tok in sorted(WHITELIST):
            print(tok)
        return 0
    return run_inbox(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
