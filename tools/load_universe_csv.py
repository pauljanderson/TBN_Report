#!/usr/bin/env python3
"""Load a one-ticker-per-line universe CSV into a single comma-separated line.

Usage:
  python tools/load_universe_csv.py PATH
  python tools/load_universe_csv.py PATH --out OUTFILE

Rules:
  - Blank lines and # comments ignored
  - Lines may be comma-separated (legacy one-liner GOLD format still works)
  - If file missing or empty → prints *
  - Sole token * or ALL → prints * (full scan). ALL among other tickers is Allstate.

Stdout (or --out file) is a single line: comma list or *.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def load_tickers(path: Path) -> list[str] | str:
    """Return ticker list, or '*' for full-scan sentinel.

    Full-scan sentinels (* / ALL) apply only when that is the *sole* token in the
    file. ALL is a real ticker (Allstate); treating it as a sentinel mid-list
    incorrectly forced pass_s=0 / full universe on expanded CSVs.
    """
    if not path.is_file():
        return "*"
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    tickers: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Strip inline comments: AAPL  # note
        if "#" in line:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
        for part in line.replace(";", ",").split(","):
            tok = part.strip().strip('"').strip("'").upper()
            if not tok:
                continue
            tickers.append(tok)
    if not tickers:
        return "*"
    # Sole-token sentinels only (* = full scan; ALL alone = legacy full-scan CSV)
    if len(tickers) == 1 and tickers[0] in ("*", "ALL"):
        return "*"
    # Bare * is never a symbol; drop if mixed with real tickers
    tickers = [t for t in tickers if t != "*"]
    if not tickers:
        return "*"
    # Dedupe preserving order (ALL among others is Allstate)
    seen: set[str] = set()
    out: list[str] = []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Load universe CSV → comma list or *")
    ap.add_argument("path", help="Path to universe CSV (one ticker per line)")
    ap.add_argument("--out", help="Write result to this file instead of stdout")
    args = ap.parse_args()
    result = load_tickers(Path(args.path))
    line = result if isinstance(result, str) else ",".join(result)
    if args.out:
        Path(args.out).write_text(line + "\n", encoding="utf-8")
    else:
        sys.stdout.write(line + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
