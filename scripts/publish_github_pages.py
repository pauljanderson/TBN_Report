#!/usr/bin/env python3
"""Generate HTML reports, copy into docs/ for GitHub Pages, optionally git push."""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DRIVE = ROOT / "Drive"
DEFAULT_DOCS = ROOT / "docs"
LOGO_FILENAME = "TBN_Logo.png"
SHOWCASE_AAPL_IMAGE_FILENAME = "AAPL_Showcase.jpg"
LOGO_DOWNLOADS = Path(r"C:\Users\songg\Downloads") / LOGO_FILENAME
LOGO_DOCS = DEFAULT_DOCS / LOGO_FILENAME

NAV_FOOTER = """
<p style="margin-top:2rem;color:#666;font-size:0.85rem;">
  <a href="index.html">Scanner open report</a>
  · <a href="investment.html">Investment report</a>
  · <a href="convergence.html">System convergence</a>
  · <a href="monthly.html">Monthly report (all systems)</a>
  · <a href="system_performance.html">Historical performance</a>
  · <a href="system_setup_process.html">System setup process</a>
  · <a href="tbn_philosophy.html">TBN Philosophy</a>
  · Refresh this page for the latest copy.
</p>
"""

# Map of docs/systems/<name>.html <- relative path under drive/
SYSTEM_PAGE_SOURCES: dict[str, str] = {
    "rs.html": "systems/rs.html",
    "sb.html": "systems/sb.html",
    "vz.html": "systems/vz.html",
    "rl.html": "systems/rl.html",
    "yh.html": "systems/yh.html",
    "brt.html": "systems/brt.html",
    "wpbr.html": "systems/wpbr.html",
    "mts.html": "systems/mts.html",
    "ind.html": "systems/ind.html",
    "mvcp.html": "systems/mvcp.html",
    "index.html": "systems/index.html",
}


def _resolve_drive(drive: Path) -> Path:
    d = drive.resolve()
    if d.is_dir():
        return d
    alt = ROOT / "drive"
    if alt.is_dir():
        return alt.resolve()
    raise FileNotFoundError(f"Drive folder not found: {drive}")


def _has_philosophy_nav_link(html: str) -> bool:
    return bool(
        re.search(
            r'<a\s+href=["\'](?:\.\./)?tbn_philosophy\.html["\'][^>]*>\s*TBN Philosophy\s*</a>',
            html,
            flags=re.I | re.S,
        )
    )


def _inject_nav_footer(html: str, *, show_nav: bool) -> str:
    """Ensure the shared site footer nav includes TBN Philosophy.

    Only mutates the known footer <p style="margin-top:2rem..."> block (or appends
    NAV_FOOTER). Never rewrites in-body links that happen to mention setup process.
    """
    if not show_nav:
        return html

    footer_nav = re.compile(
        r'<p\s+style=["\']margin-top:2rem;color:#666;font-size:0\.85rem;["\']>.*?</p>',
        flags=re.I | re.S,
    )
    m = footer_nav.search(html)
    if m:
        block = m.group(0)
        if _has_philosophy_nav_link(block):
            return html
        if re.search(r'href=["\']system_setup_process\.html["\']', block, flags=re.I):
            new_block = re.sub(
                r'(<a\s+href=["\']system_setup_process\.html["\'][^>]*>.*?</a>)',
                r'\1\n  · <a href="tbn_philosophy.html">TBN Philosophy</a>',
                block,
                count=1,
                flags=re.I | re.S,
            )
        elif re.search(r'href=["\']system_performance\.html["\']', block, flags=re.I):
            new_block = re.sub(
                r'(<a\s+href=["\']system_performance\.html["\'][^>]*>.*?</a>)',
                r'\1\n  · <a href="system_setup_process.html">System setup process</a>'
                r'\n  · <a href="tbn_philosophy.html">TBN Philosophy</a>',
                block,
                count=1,
                flags=re.I | re.S,
            )
        elif re.search(r'href=["\']monthly\.html["\']', block, flags=re.I):
            new_block = re.sub(
                r'(<a\s+href=["\']monthly\.html["\'][^>]*>.*?</a>)',
                r'\1\n  · <a href="system_performance.html">Historical performance</a>'
                r'\n  · <a href="system_setup_process.html">System setup process</a>'
                r'\n  · <a href="tbn_philosophy.html">TBN Philosophy</a>',
                block,
                count=1,
                flags=re.I | re.S,
            )
        else:
            # Replace/append full footer
            new_block = NAV_FOOTER.strip()
        return html[: m.start()] + new_block + html[m.end() :]

    # Convergence-style compact footer (class="small" with report links)
    compact = re.compile(
        r'(<p class=["\']small["\']>.*?href=["\']system_setup_process\.html["\'].*?</p>)',
        flags=re.I | re.S,
    )
    cm = compact.search(html)
    if cm:
        block = cm.group(1)
        if _has_philosophy_nav_link(block):
            return html
        new_block = re.sub(
            r'(<a\s+href=["\']system_setup_process\.html["\'][^>]*>.*?</a>)',
            r'\1 · <a href="tbn_philosophy.html">TBN Philosophy</a>',
            block,
            count=1,
            flags=re.I | re.S,
        )
        return html[: cm.start()] + new_block + html[cm.end() :]

    if _has_philosophy_nav_link(html):
        # Header nav already has it (e.g. system_performance); still add footer if absent.
        pass

    if "</body>" in html.lower():
        return re.sub(r"</body>", NAV_FOOTER + "\n</body>", html, count=1, flags=re.I)
    return html + NAV_FOOTER


def _write_text_resilient(dst: Path, text: str, *, encoding: str = "utf-8", retries: int = 5) -> None:
    """Write HTML via temp+replace with retries.

    On Windows, Path.write_text on a large docs/*.html often raises OSError
    Errno 22 (Invalid argument) when the destination is locked by an IDE
    preview, browser, OneDrive, or AV — not because HTML content is invalid.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f".{dst.name}.{os.getpid()}.tmp")
    last_err: OSError | None = None
    for attempt in range(1, retries + 1):
        try:
            tmp.write_text(text, encoding=encoding)
            os.replace(tmp, dst)
            return
        except OSError as exc:
            last_err = exc
            try:
                if tmp.is_file():
                    tmp.unlink()
            except OSError:
                pass
            if attempt < retries:
                time.sleep(0.4 * attempt)
    assert last_err is not None
    hint = (
        f"Could not write {dst} after {retries} attempts ({last_err}). "
        "Close any IDE/browser tab previewing this file (and pause OneDrive sync if needed), then retry."
    )
    raise OSError(last_err.errno, hint, str(dst)) from last_err


def prepare_html_for_pages(src: Path, dst: Path, *, show_nav: bool = False) -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from report_page_extras import inject_report_page_extras

    text = src.read_text(encoding="utf-8")
    text = inject_report_page_extras(text)
    text = _inject_nav_footer(text, show_nav=show_nav)
    _write_text_resilient(dst, text)


def generate_investment_report(drive: Path) -> Path:
    """Build Investment_Report_Latest.html (same as generate_investment_report.py --drive)."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from generate_investment_report import CLOSED_SINCE, build_report

    out = build_report(
        drive_dir=_resolve_drive(drive),
        closed_since=CLOSED_SINCE,
    )
    latest = _resolve_drive(drive) / "Investment_Report_Latest.html"
    latest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(out, latest)
    print(f"[pages] Generated {out}")
    print(f"[pages] Copied to {latest}")
    sell_latest = _resolve_drive(drive) / "Sell_Report_Latest.csv"
    if sell_latest.is_file():
        print(f"[pages] Sell report: {sell_latest}")
    return latest


def generate_convergence_report(drive: Path) -> Path:
    """Build System_Convergence_Latest.html from latest IND/BRT/RL lists."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from generate_system_convergence_report import build_report

    _, out_html, cross, _same, multi_open = build_report(_resolve_drive(drive))
    multi_n = 0 if multi_open is None or multi_open.empty else int(multi_open["SYMBOL"].nunique())
    print(
        f"[pages] Convergence report: {len(cross)} cross-system overlaps, "
        f"{multi_n} multi-system opens -> {out_html}"
    )
    return out_html


def generate_monthly_backtest_report(drive: Path) -> Path:
    """Build Monthly_System_Report_Latest.html (calendar-year backtest P&L by system)."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from generate_monthly_system_report import build_report

    out = build_report(_resolve_drive(drive))
    print(f"[pages] Monthly system report -> {out}")
    return out


def generate_performance_report(drive: Path, docs_dir: Path) -> Path:
    """Build the historical per-system and combined portfolio report."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from generate_system_performance_report import build_report

    out, _payload = build_report(_resolve_drive(drive), docs_dir / "system_performance.html")
    print(f"[pages] Historical system performance -> {out}")
    return out


def publish_convergence(*, drive: Path, docs_dir: Path, show_nav: bool) -> Path:
    src = _resolve_drive(drive) / "System_Convergence_Latest.html"
    if not src.is_file():
        raise FileNotFoundError(f"Missing {src.name}")
    dst = docs_dir / "convergence.html"
    prepare_html_for_pages(src, dst, show_nav=show_nav)
    return dst


def publish_monthly_backtest(*, drive: Path, docs_dir: Path, show_nav: bool) -> Path:
    src = _resolve_drive(drive) / "Monthly_System_Report_Latest.html"
    if not src.is_file():
        raise FileNotFoundError(f"Missing {src.name}")
    dst = docs_dir / "monthly.html"
    prepare_html_for_pages(src, dst, show_nav=show_nav)
    return dst


def publish_setup_process(*, drive: Path, docs_dir: Path, show_nav: bool) -> Path:
    """Copy system_setup_process.html (static process doc) into docs/ for Pages."""
    src = _resolve_drive(drive) / "paul_experiments" / "system_setup_process.html"
    if not src.is_file():
        raise FileNotFoundError(f"Missing {src}")
    dst = docs_dir / "system_setup_process.html"
    prepare_html_for_pages(src, dst, show_nav=show_nav)
    return dst


def publish_philosophy(*, drive: Path, docs_dir: Path, show_nav: bool) -> Path:
    """Copy TBN_Philosophy.html into docs/tbn_philosophy.html for Pages."""
    src = _resolve_drive(drive) / "TBN_Philosophy.html"
    if not src.is_file():
        raise FileNotFoundError(f"Missing {src}")
    dst = docs_dir / "tbn_philosophy.html"
    prepare_html_for_pages(src, dst, show_nav=show_nav)
    return dst


def publish_system_pages(*, drive: Path, docs_dir: Path, show_nav: bool) -> list[Path]:
    """Copy drive/systems/*.html (and mapped guides) into docs/systems/."""
    drive_root = _resolve_drive(drive)
    out_dir = docs_dir / "systems"
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for dst_name, rel_src in SYSTEM_PAGE_SOURCES.items():
        src = drive_root / rel_src
        if not src.is_file():
            # Fallback: paul_experiments guides for RS/SB/VZ if systems/ missing
            alt_map = {
                "rs.html": "paul_experiments/RS_System_Guide.html",
                "sb.html": "paul_experiments/SB_System_Guide.html",
                "vz.html": "paul_experiments/VZ_System_Guide.html",
            }
            alt = alt_map.get(dst_name)
            if alt:
                src = drive_root / alt
        if not src.is_file():
            print(f"[pages] Skipped systems/{dst_name} (no source)")
            continue
        dst = out_dir / dst_name
        prepare_html_for_pages(src, dst, show_nav=show_nav)
        written.append(dst)
    return written


def publish_scanner(*, drive: Path, docs_dir: Path, show_nav: bool) -> Path:
    src = drive / "Scanner_Open_Report_Latest.html"
    if not src.is_file():
        raise FileNotFoundError(f"Missing {src}. Run generate_scanner_open_report.py first.")
    dst = docs_dir / "index.html"
    prepare_html_for_pages(src, dst, show_nav=show_nav)
    return dst


def ensure_logo_in_docs(docs_dir: Path) -> None:
    import sys

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from generate_investment_report import _build_web_logo

        _build_web_logo(docs_dir / LOGO_FILENAME)
    except ImportError:
        src = LOGO_DOWNLOADS if LOGO_DOWNLOADS.is_file() else LOGO_DOCS
        if not src.is_file():
            return
        dst = docs_dir / LOGO_FILENAME
        if src.resolve() != dst.resolve():
            shutil.copy2(src, dst)


def publish_investment(*, drive: Path, docs_dir: Path, show_nav: bool) -> Path:
    src = drive / "Investment_Report_Latest.html"
    if not src.is_file():
        raise FileNotFoundError(f"Missing {src}. Run generate_investment_report.py first.")
    dst = docs_dir / "investment.html"
    prepare_html_for_pages(src, dst, show_nav=show_nav)
    for img_name in (SHOWCASE_AAPL_IMAGE_FILENAME,):
        for src_dir in (drive, docs_dir, ROOT / "docs"):
            img_src = src_dir / img_name
            if img_src.is_file():
                img_dst = docs_dir / img_name
                if img_src.resolve() != img_dst.resolve():
                    shutil.copy2(img_src, img_dst)
                break
    return dst


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
    )


def _git_out(args: list[str], cwd: Path) -> str:
    proc = _git(args, cwd)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip() or f"git {' '.join(args)} failed")
    return (proc.stdout or "").strip()


def push_origin_main(repo_root: Path, branch: str) -> None:
    """Pages workflow (.github/workflows/publish-pages.yml) runs only on push to main.

    `git push` of a feature branch does not update the live site. Always push HEAD to
    origin/main when --push is used.
    """
    sha = _git_out(["rev-parse", "--short", "HEAD"], repo_root)
    origin_main = ""
    rev = _git(["rev-parse", "--short", "origin/main"], repo_root)
    if rev.returncode == 0:
        origin_main = (rev.stdout or "").strip()
    print(f"[pages] HEAD {sha} on {branch}" + (f" (origin/main {origin_main})" if origin_main else ""))
    if branch == "main":
        proc = _git(["push", "origin", "main"], repo_root)
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout).strip()
            raise RuntimeError(f"git push origin main failed: {err}")
        print("[pages] Pushed origin/main. Pages may take 1-2 minutes to update.")
        return

    print(
        f"[pages] Current branch is {branch}. GitHub Pages deploys only from main — "
        "pushing HEAD to origin/main so the live site updates."
    )
    proc = _git(["push", "origin", "HEAD:main"], repo_root)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(
            f"git push origin HEAD:main failed: {err}\n"
            f"HEAD is on {branch} ({sha}); origin/main was not updated.\n"
            f"To go live from Windows: git push origin {branch}:main"
        )
    print("[pages] Pushed origin/main. Pages may take 1-2 minutes to update.")


def git_push_docs(repo_root: Path, docs_dir: Path, message: str) -> None:
    if not (repo_root / ".git").is_dir():
        raise RuntimeError(f"Not a git repo: {repo_root}. Run git init and add a remote first.")

    rel_docs = docs_dir.resolve().relative_to(repo_root.resolve())
    rel_closed_log = (repo_root / "closed_positions_log.csv").resolve()
    paths_to_add: list[str] = [str(rel_docs)]
    if rel_closed_log.is_file():
        try:
            paths_to_add.append(str(rel_closed_log.relative_to(repo_root.resolve())))
        except ValueError:
            pass

    status = _git(["status", "--porcelain", "--", *paths_to_add], repo_root)
    if status.returncode != 0:
        raise RuntimeError(status.stderr.strip() or "git status failed")
    branch = _git_out(["rev-parse", "--abbrev-ref", "HEAD"], repo_root) or "HEAD"

    if not status.stdout.strip():
        print("[pages] No changes under docs/ or closed_positions_log.csv — skip commit.")
        push_origin_main(repo_root, branch)
        return

    for step in (
        ["add", "--", *paths_to_add],
        ["commit", "-m", message],
        ["push"],
    ):
        proc = _git(step, repo_root)
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout).strip()
            raise RuntimeError(f"git {' '.join(step)} failed: {err}")

    push_origin_main(repo_root, branch)


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
        "--no-generate",
        action="store_true",
        help="Skip generate_investment_report (only copy existing Latest HTML to docs/)",
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
    ensure_logo_in_docs(docs_dir)

    if not args.no_generate:
        generate_investment_report(drive)
        try:
            generate_convergence_report(drive)
        except Exception as exc:
            print(f"[pages] Convergence report skipped: {exc}", file=sys.stderr)
        try:
            generate_monthly_backtest_report(drive)
        except Exception as exc:
            print(f"[pages] Monthly backtest report skipped: {exc}", file=sys.stderr)
        try:
            generate_performance_report(drive, docs_dir)
        except Exception as exc:
            print(f"[pages] Historical performance report skipped: {exc}", file=sys.stderr)

    published: list[Path] = []
    scanner_src = drive / "Scanner_Open_Report_Latest.html"
    if scanner_src.is_file():
        scanner_dst = publish_scanner(drive=drive, docs_dir=docs_dir, show_nav=False)
        published.append(scanner_dst)
        print(f"[pages] Wrote {scanner_dst}")
    else:
        print(
            f"[pages] Skipped scanner index (no {scanner_src.name}; "
            "run generate_scanner_open_report.py at/after open)"
        )

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

    conv_src = drive / "System_Convergence_Latest.html"
    if include_investment and conv_src.is_file():
        conv_dst = publish_convergence(drive=drive, docs_dir=docs_dir, show_nav=False)
        published.append(conv_dst)
        print(f"[pages] Wrote {conv_dst}")
    elif include_investment and not conv_src.is_file():
        print(f"[pages] Skipped convergence (no {conv_src.name})")

    monthly_src = drive / "Monthly_System_Report_Latest.html"
    if include_investment and monthly_src.is_file():
        monthly_dst = publish_monthly_backtest(drive=drive, docs_dir=docs_dir, show_nav=False)
        published.append(monthly_dst)
        show_nav = True
        print(f"[pages] Wrote {monthly_dst}")
    elif include_investment and not monthly_src.is_file():
        print(f"[pages] Skipped monthly report (no {monthly_src.name})")

    performance_dst = docs_dir / "system_performance.html"
    if include_investment and performance_dst.is_file():
        published.append(performance_dst)
        show_nav = True
        print(f"[pages] Wrote {performance_dst}")
    elif include_investment:
        print(f"[pages] Skipped historical performance (no {performance_dst.name})")

    setup_src = _resolve_drive(drive) / "paul_experiments" / "system_setup_process.html"
    if setup_src.is_file():
        setup_dst = publish_setup_process(drive=drive, docs_dir=docs_dir, show_nav=False)
        published.append(setup_dst)
        show_nav = True
        print(f"[pages] Wrote {setup_dst}")
    else:
        print(f"[pages] Skipped setup process (no {setup_src})")

    philosophy_src = _resolve_drive(drive) / "TBN_Philosophy.html"
    if philosophy_src.is_file():
        phil_dst = publish_philosophy(drive=drive, docs_dir=docs_dir, show_nav=False)
        published.append(phil_dst)
        show_nav = True
        print(f"[pages] Wrote {phil_dst}")
    else:
        print(f"[pages] Skipped TBN Philosophy (no {philosophy_src})")

    system_pages = publish_system_pages(drive=drive, docs_dir=docs_dir, show_nav=False)
    if system_pages:
        # Do not inject root-relative footer into docs/systems/* (hrefs would break).
        print(f"[pages] Wrote {len(system_pages)} system description page(s) under {docs_dir / 'systems'}")

    if show_nav:
        for path in published:
            text = path.read_text(encoding="utf-8")
            _write_text_resilient(path, _inject_nav_footer(text, show_nav=True))

    if args.push:
        from datetime import datetime

        msg = args.message or f"Update reports {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        git_push_docs(ROOT, docs_dir, msg)

    print("[pages] Live URLs:")
    print("[pages]   Scanner:      https://pauljanderson.github.io/TBN_Report/")
    print("[pages]   Investment:   https://pauljanderson.github.io/TBN_Report/investment.html")
    print("[pages]   Convergence:  https://pauljanderson.github.io/TBN_Report/convergence.html")
    print("[pages]   Monthly:      https://pauljanderson.github.io/TBN_Report/monthly.html")
    print("[pages]   Performance:  https://pauljanderson.github.io/TBN_Report/system_performance.html")
    print("[pages]   Setup process: https://pauljanderson.github.io/TBN_Report/system_setup_process.html")
    print("[pages]   TBN Philosophy: https://pauljanderson.github.io/TBN_Report/tbn_philosophy.html")
    print("[pages]   Systems:      https://pauljanderson.github.io/TBN_Report/systems/")
    if args.push:
        print(
            "[pages] After origin/main updates, check Actions > Publish reports to Pages (~1-2 min)."
        )
    else:
        # Local docs/ alone does not update GitHub Pages — must commit + push (or use --push).
        if (ROOT / ".git").is_dir():
            rel_docs = docs_dir.resolve().relative_to(ROOT.resolve())
            st = _git(["status", "--porcelain", "--", str(rel_docs)], ROOT)
            if st.returncode == 0 and st.stdout.strip():
                print(
                    "[pages] NOTE: docs/ changed locally but was NOT pushed. "
                    "The live URLs above still serve the last GitHub deploy until you run:\n"
                    "        publish_github_pages.bat --push",
                    file=sys.stderr,
                )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"[pages] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
