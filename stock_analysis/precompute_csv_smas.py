#!/usr/bin/env python3
"""
Recompute SMA20/30/50/100/200 from **Close** on Rocket Launcher ticker CSVs so
``portfolio_audit.awk`` can use columns 8–12 (packed ``raw_sma``) without the
rolling-SMA path (see ``PRECOMP_SMA_HITS`` / ``PRECOMP_SMA_MISS`` with ``-Instrument``).

Matches AWK logic: simple rolling arithmetic mean over **Close** (same as AWK ``clean($5)``),
``min_periods`` = full window; shorter history rows get 0.0.

Typical use (from repo root, before ``run_audit.ps1``):

  python stock_analysis/precompute_csv_smas.py --data-dir data/newdata/data

  python stock_analysis/precompute_csv_smas.py --data-dir data/newdata/data --dry-run
  python stock_analysis/precompute_csv_smas.py --data-dir data/newdata/data --jobs 8
  python stock_analysis/precompute_csv_smas.py --data-dir data/newdata/data --only AAPL,MSFT
"""
from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

SMA_COLS = [
    ("SMA20", 20),
    ("SMA30", 30),
    ("SMA50", 50),
    ("SMA100", 100),
    ("SMA200", 200),
]


def _find_close_series(df: pd.DataFrame) -> pd.Series:
    """AWK uses clean($5) as close — match **Close**, not Adj Close."""
    for c in df.columns:
        if str(c).strip().lower() == "close":
            return pd.to_numeric(df[c], errors="coerce")
    if df.shape[1] >= 5:
        s = pd.to_numeric(df.iloc[:, 4], errors="coerce")
        if s.notna().sum() > len(df) * 0.5:
            return s
    raise ValueError("no Close column")


def _process_one_csv(path: Path, dry_run: bool) -> tuple[str, str]:
    """Returns (path_str, status) status ok|skip|error|dry."""
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception as e:
        return str(path), f"error read: {e}"

    if df.shape[0] == 0:
        return str(path), "skip empty"

    try:
        close = _find_close_series(df)
    except ValueError as e:
        return str(path), f"skip {e}"

    out = df.copy()
    for col, win in SMA_COLS:
        ser = close.rolling(window=win, min_periods=win).mean()
        out[col] = ser.fillna(0.0).astype(float)

    # Keep $1–$7 as Date..Volume when present so AWK NF>=12 maps to SMA20..SMA200.
    sma_names = [x[0] for x in SMA_COLS]
    preferred_front = ["Date", "Open", "High", "Low", "Close", "Adj Close", "Volume"]
    front = [c for c in preferred_front if c in out.columns]
    mid = [c for c in out.columns if c not in front and c not in sma_names]
    tail = [c for c in sma_names if c in out.columns]
    out = out[front + mid + tail]

    if dry_run:
        return str(path), "dry ok"

    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        out.to_csv(tmp, index=False, lineterminator="\n", float_format="%.4f")
        os.replace(tmp, path)
    except Exception as e:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        return str(path), f"error write: {e}"
    return str(path), "ok"


def _worker(args: tuple[str, bool]) -> tuple[str, str]:
    p, dry = args
    return _process_one_csv(Path(p), dry)


def main() -> int:
    ap = argparse.ArgumentParser(description="Fill SMA20–SMA200 on RL ticker CSVs from Close.")
    ap.add_argument(
        "--data-dir",
        type=str,
        default="data/newdata/data",
        help="Directory of *.csv (default: data/newdata/data)",
    )
    ap.add_argument("--dry-run", action="store_true", help="Parse only; do not write files.")
    ap.add_argument("--jobs", type=int, default=1, help="Parallel workers (default: 1).")
    ap.add_argument("--limit", type=int, default=0, help="Process at most N files (0 = all).")
    ap.add_argument(
        "--only",
        type=str,
        default="",
        help="Comma-separated symbols (basename without .csv) to process; default all *.csv.",
    )
    args = ap.parse_args()

    repo = Path(__file__).resolve().parent.parent
    data_dir = Path(args.data_dir)
    if not data_dir.is_absolute():
        data_dir = repo / data_dir
    if not data_dir.is_dir():
        print(f"[precompute_csv_smas] not a directory: {data_dir}", file=sys.stderr)
        return 1

    paths = sorted(data_dir.glob("*.csv"))
    only = {x.strip().upper() for x in str(args.only).split(",") if x.strip()}
    if only:
        paths = [p for p in paths if p.stem.upper() in only]
    if args.limit and args.limit > 0:
        paths = paths[: int(args.limit)]

    if not paths:
        print(f"[precompute_csv_smas] no CSV files in {data_dir}", file=sys.stderr)
        return 1

    n_ok = n_skip = n_err = 0
    if int(args.jobs) <= 1:
        for p in paths:
            msg, st = _process_one_csv(p, bool(args.dry_run))
            if st.startswith("ok") or st == "dry ok":
                n_ok += 1
            elif st.startswith("skip"):
                n_skip += 1
            else:
                n_err += 1
                print(f"[precompute_csv_smas] {p.name}: {st}", file=sys.stderr)
    else:
        work = [(str(p), bool(args.dry_run)) for p in paths]
        with ProcessPoolExecutor(max_workers=int(args.jobs)) as ex:
            futs = {ex.submit(_worker, w): w[0] for w in work}
            for fut in as_completed(futs):
                msg, st = fut.result()
                if st.startswith("ok") or st == "dry ok":
                    n_ok += 1
                elif st.startswith("skip"):
                    n_skip += 1
                else:
                    n_err += 1
                    print(f"[precompute_csv_smas] {Path(msg).name}: {st}", file=sys.stderr)

    mode = "dry-run" if args.dry_run else "write"
    print(
        f"[precompute_csv_smas] {mode}: {len(paths)} files "
        f"(ok={n_ok}, skip={n_skip}, err={n_err}) in {data_dir}"
    )
    return 1 if n_err else 0


if __name__ == "__main__":
    sys.exit(main())
