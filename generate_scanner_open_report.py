#!/usr/bin/env python3
"""At market open, classify scanner symbols into BUY vs IGNORE from session open vs entry band."""
from __future__ import annotations

import argparse
import shutil
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scanner_open_report_lib import (
    ET,
    evaluate_scanner_opens,
    market_status_message,
    poll_session_opens,
    resolve_scanner_csv,
    wait_until_market_open,
    write_scanner_open_csv,
    write_scanner_open_html,
)

ROOT = Path(__file__).resolve().parent
DRIVE = ROOT / "Drive"
DEFAULT_DATA_DIR = ROOT / "data" / "newdata" / "data"


def main() -> None:
    p = argparse.ArgumentParser(
        description="Scanner open report: BUY vs IGNORE at session open (too_high / too_low band)"
    )
    p.add_argument("--drive", type=Path, default=DRIVE, help="Drive folder with IND_Scanner_*.csv")
    p.add_argument("--prefix", choices=("IND", "BRT", "ind", "brt"), default="IND")
    p.add_argument("--run-ts", default=None, help="Scanner run stamp yyMMddHHmmss (default: latest)")
    p.add_argument("--scanner", type=Path, default=None, help="Explicit scanner CSV path")
    p.add_argument(
        "--use-csv-fallback",
        action="store_true",
        help="Only if Yahoo fails: fall back to local OHLC CSV (default: Yahoo only)",
    )
    p.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Local OHLC dir (only with --use-csv-fallback)",
    )
    p.add_argument(
        "--session-date",
        default=None,
        help="Session date YYYY-MM-DD (default: today America/New_York)",
    )
    p.add_argument(
        "--wait-for-open",
        action="store_true",
        help="Wait until 9:30 AM ET, then poll for opens until 9:45 AM ET",
    )
    p.add_argument(
        "--allow-stale-signal",
        action="store_true",
        help="Do not ignore rows whose signal DATE is not the prior trading session",
    )
    p.add_argument("-o", "--output", type=Path, default=None, help="HTML output path")
    p.add_argument("--no-copy-latest", action="store_true")
    p.add_argument(
        "--publish-github-pages",
        action="store_true",
        help="Copy Latest report to docs/index.html for GitHub Pages",
    )
    p.add_argument(
        "--push-github-pages",
        action="store_true",
        help="With --publish-github-pages: also git commit and push docs/",
    )
    args = p.parse_args()

    now_et = datetime.now(ET)
    if args.session_date:
        session = datetime.strptime(args.session_date, "%Y-%m-%d").date()
    else:
        session = now_et.date()

    prefix = str(args.prefix).upper()
    scanner_path, run_ts = resolve_scanner_csv(
        args.drive,
        prefix=prefix,
        run_ts=args.run_ts,
        scanner_path=args.scanner,
    )

    print(market_status_message(session, now_et))

    if args.wait_for_open:
        wait_until_market_open(now_et)

    rows = evaluate_scanner_opens(
        scanner_path,
        session_date=session,
        data_dir=args.data_dir if args.use_csv_fallback else None,
        use_csv_fallback=bool(args.use_csv_fallback),
        require_fresh_signal=not args.allow_stale_signal,
    )

    if args.wait_for_open:
        rows = poll_session_opens(
            rows,
            session_date=session,
            data_dir=args.data_dir if args.use_csv_fallback else None,
            use_csv_fallback=bool(args.use_csv_fallback),
            require_fresh_signal=not args.allow_stale_signal,
        )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    html_out = args.output or (args.drive / f"Scanner_Open_Report_{stamp}.html")
    csv_out = html_out.with_suffix(".csv")

    write_scanner_open_html(
        rows,
        html_out,
        session_date=session,
        scanner_path=scanner_path,
        run_ts=run_ts,
        generated_et=datetime.now(ET),
    )
    write_scanner_open_csv(
        rows,
        csv_out,
        session_date=session,
        scanner_path=scanner_path,
        run_ts=run_ts,
    )

    buy_n = sum(1 for r in rows if r.action == "BUY")
    ign_n = sum(1 for r in rows if r.action == "IGNORE")
    print(f"Scanner: {scanner_path.name} (run {run_ts})")
    print(f"Session: {session.isoformat()} · BUY {buy_n} · IGNORE {ign_n}")
    if buy_n and session == datetime.now(ET).date() and datetime.now(ET).hour < 9:
        print(
            "[WARN] BUY rows before 09:30 ET are unexpected — check OpenQuoteTimeET in the CSV.",
            flush=True,
        )
    print(f"Wrote {html_out}")
    print(f"Wrote {csv_out}")

    if not args.no_copy_latest:
        latest_html = args.drive / "Scanner_Open_Report_Latest.html"
        latest_csv = args.drive / "Scanner_Open_Report_Latest.csv"
        shutil.copy2(html_out, latest_html)
        shutil.copy2(csv_out, latest_csv)
        print(f"Copied to {latest_html}")
        print(f"Copied to {latest_csv}")

    if args.publish_github_pages:
        import sys

        scripts_dir = str(ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from publish_github_pages import git_push_docs, publish_scanner

        docs_dir = ROOT / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        (docs_dir / ".nojekyll").touch(exist_ok=True)
        dst = publish_scanner(drive=args.drive, docs_dir=docs_dir, show_nav=False)
        print(f"Published GitHub Pages: {dst}")
        if args.push_github_pages:
            msg = f"Scanner open report {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            git_push_docs(ROOT, docs_dir, msg)


if __name__ == "__main__":
    main()
