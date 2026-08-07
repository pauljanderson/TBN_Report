#!/usr/bin/env python3
"""Load a one-ticker-per-line universe CSV into a single comma-separated line.

Usage:
  python tools/load_universe_csv.py PATH
  python tools/load_universe_csv.py PATH --out OUTFILE

Rules:
  - Blank lines and # comments ignored
  - Lines may be comma-separated (legacy one-liner GOLD format still works)
  - If file missing, empty, or first non-comment token is * / ALL → prints *

Stdout (or --out file) is a single line: comma list or *.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def load_tickers(path: Path) -> list[str] | str:
    """Return ticker list, or '*' for full-scan sentinel."""
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
            if tok in ("*", "ALL"):
                return "*"
            tickers.append(tok)
    if not tickers:
        return "*"
    # Dedupe preserving order
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
