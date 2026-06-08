#!/usr/bin/env python3
"""Copy latest HTML reports into docs/ for GitHub Pages (stable URLs, refresh = latest)."""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DRIVE = ROOT / "Drive"
DEFAULT_DOCS = ROOT / "docs"

CACHE_META = """<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate"/>
<meta http-equiv="Pragma" content="no-cache"/>
<meta http-equiv="Expires" content="0"/>
"""

NAV_FOOTER = """
<p style="margin-top:2rem;color:#666;font-size:0.85rem;">
  <a href="index.html">Scanner open report</a>
  · <a href="investment.html">Investment report</a>
  · Refresh this page for the latest copy.
</p>
"""


def _resolve_drive(drive: Path) -> Path:
    d = drive.resolve()
    if d.is_dir():
        return d
    alt = ROOT / "drive"
    if alt.is_dir():
        return alt.resolve()
    raise FileNotFoundError(f"Drive folder not found: {drive}")


def _inject_cache_headers(html: str) -> str:
    if "no-cache, no-store, must-revalidate" in html:
        return html
    if re.search(r"<head\b", html, flags=re.I):
        return re.sub(r"(<head[^>]*>)", r"\1\n" + CACHE_META, html, count=1, flags=re.I)
    return CACHE_META + html


def _inject_nav_footer(html: str, *, show_nav: bool) -> str:
    if not show_nav or "investment.html" in html and "Scanner open report" in html:
        return html
    if "</body>" in html.lower():
        return re.sub(r"</body>", NAV_FOOTER + "\n</body>", html, count=1, flags=re.I)
    return html + NAV_FOOTER


def prepare_html_for_pages(src: Path, dst: Path, *, show_nav: bool = False) -> None:
    text = src.read_text(encoding="utf-8")
    text = _inject_cache_headers(text)
    text = _inject_nav_footer(text, show_nav=show_nav)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(text, encoding="utf-8")


def publish_scanner(*, drive: Path, docs_dir: Path, show_nav: bool) -> Path:
    src = drive / "Scanner_Open_Report_Latest.html"
    if not src.is_file():
        raise FileNotFoundError(f"Missing {src}. Run generate_scanner_open_report.py first.")
    dst = docs_dir / "index.html"
    prepare_html_for_pages(src, dst, show_nav=show_nav)
    return dst


def publish_investment(*, drive: Path, docs_dir: Path, show_nav: bool) -> Path:
    src = drive / "Investment_Report_Latest.html"
    if not src.is_file():
        raise FileNotFoundError(f"Missing {src}. Run generate_investment_report.py first.")
    dst = docs_dir / "investment.html"
    prepare_html_for_pages(src, dst, show_nav=show_nav)
    return dst


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
    )


def git_push_docs(repo_root: Path, docs_dir: Path, message: str) -> None:
    if not (repo_root / ".git").is_dir():
        raise RuntimeError(f"Not a git repo: {repo_root}. Run git init and add a remote first.")

    rel_docs = docs_dir.resolve().relative_to(repo_root.resolve())
    status = _git(["status", "--porcelain", "--", str(rel_docs)], repo_root)
    if status.returncode != 0:
        raise RuntimeError(status.stderr.strip() or "git status failed")
    if not status.stdout.strip():
        print("[pages] No changes under docs/ — skip commit.")
        return

    for step in (
        ["add", "--", str(rel_docs)],
        ["commit", "-m", message],
        ["push"],
    ):
        proc = _git(step, repo_root)
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout).strip()
            raise RuntimeError(f"git {' '.join(step)} failed: {err}")
    print("[pages] Pushed to GitHub. Pages may take 1-2 minutes to update.")


def main() -> int:
    p = argparse.ArgumentParser(
        description="Publish Latest HTML reports to docs/ for GitHub Pages"
    )
    p.add_argument("--drive", type=Path, default=DEFAULT_DRIVE)
    p.add_argument("--docs", type=Path, default=DEFAULT_DOCS)
    p.add_argument(
        "--scanner-only",
        action="store_true",
        help="Publish scanner report only (default: scanner + investment if present)",
    )
    p.add_argument(
        "--with-investment",
        action="store_true",
        help="Also publish Investment_Report_Latest.html (default: yes if file exists)",
    )
    p.add_argument(
        "--push",
        action="store_true",
        help="git add docs/, commit, and push (repo must exist with remote)",
    )
    p.add_argument(
        "--message",
        default=None,
        help="Git commit message (default: auto timestamp)",
    )
    args = p.parse_args()

    drive = _resolve_drive(args.drive)
    docs_dir = args.docs.resolve()
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / ".nojekyll").touch(exist_ok=True)

    published: list[Path] = []
    scanner_dst = publish_scanner(drive=drive, docs_dir=docs_dir, show_nav=False)
    published.append(scanner_dst)
    print(f"[pages] Wrote {scanner_dst}")

    include_investment = args.with_investment or not args.scanner_only
    inv_src = drive / "Investment_Report_Latest.html"
    show_nav = False
    if include_investment and inv_src.is_file():
        inv_dst = publish_investment(drive=drive, docs_dir=docs_dir, show_nav=False)
        published.append(inv_dst)
        show_nav = True
        print(f"[pages] Wrote {inv_dst}")
    elif include_investment and not inv_src.is_file():
        print(f"[pages] Skipped investment (no {inv_src.name})")

    if show_nav:
        for path in published:
            text = path.read_text(encoding="utf-8")
            path.write_text(_inject_nav_footer(text, show_nav=True), encoding="utf-8")

    if args.push:
        from datetime import datetime

        msg = args.message or f"Update reports {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        git_push_docs(ROOT, docs_dir, msg)

    print(
        "[pages] GitHub Pages: enable Settings > Pages > Deploy from branch > main > /docs"
    )
    print("[pages] Live URL (after first push): https://<user>.github.io/<repo>/")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"[pages] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
