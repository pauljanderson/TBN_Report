#!/usr/bin/env python3
"""DailyRun hook: regenerate trendline + VZ 6m charts for opens universe.

Universe = gettarget_positions.csv ∪ drive/*_LatestRun_Open.csv ∪ investment-report
scanners (stamped to latest core run) ∪ always-include extras (SPY, APP, …) — deduped.
Writes stable output under drive/paul_studies/trendlines_opens_latest/ for GitHub Pages.

Skip: SKIP_TRENDLINES=1
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_TOOLS = _REPO / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from trendlines_opens_universe import collect_opens_universe, meta_to_jsonable  # noqa: E402

DEFAULT_OUT = _REPO / "drive" / "paul_studies" / "trendlines_opens_latest"
STAMP_DOC = _REPO / "drive" / "paul_experiments" / "trendlines_daily_publish_20260902"


def _run(cmd: list[str]) -> None:
    print(f"[trendlines_daily] {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(_REPO))
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--drive", type=Path, default=_REPO / "drive")
    ap.add_argument("--positions-csv", type=Path, default=_REPO / "gettarget_positions.csv")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--skip-ntfy", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="Smoke: cap symbol count")
    args = ap.parse_args()

    out_dir = args.out_dir if args.out_dir.is_absolute() else _REPO / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    syms, meta = collect_opens_universe(args.drive, args.positions_csv)
    if args.limit and args.limit > 0:
        syms = syms[: args.limit]

    meta_path = out_dir / "symbol_meta.json"
    meta_path.write_text(
        json.dumps(meta_to_jsonable({s: meta[s] for s in syms if s in meta}), indent=2),
        encoding="utf-8",
    )

    sym_csv = ",".join(syms)
    py = sys.executable

    _run(
        [
            py,
            str(_TOOLS / "gen_trendlines_tos_studies.py"),
            "--symbols",
            sym_csv,
            "--stamp",
            "trendlines_opens_latest",
            "--stamp-dir",
            str(out_dir),
            "--intro",
            "Daily opens+scanner universe: gettarget_positions + LatestRun opens + "
            "investment-report scanners + extras (SPY, APP, durable watchlist).",
        ]
    )

    _run(
        [
            py,
            str(_TOOLS / "gen_trendlines_charts_html.py"),
            "--stamp-dir",
            str(out_dir),
            "--symbol-meta",
            str(meta_path),
            *(["--limit", str(args.limit)] if args.limit else []),
        ]
    )

    charts_index = out_dir / "charts" / "index.html"
    if not charts_index.is_file():
        print(f"[trendlines_daily] ERROR: missing {charts_index}", file=sys.stderr)
        return 1

    STAMP_DOC.mkdir(parents=True, exist_ok=True)
    (STAMP_DOC / "last_run.json").write_text(
        json.dumps(
            {
                "generated": datetime.now().isoformat(timespec="seconds"),
                "n_symbols": len(syms),
                "charts_index": str(charts_index.relative_to(_REPO)).replace("\\", "/"),
                "out_dir": str(out_dir.relative_to(_REPO)).replace("\\", "/"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    if not args.skip_ntfy:
        _run(
            [
                py,
                str(_TOOLS / "ntfy_job_done.py"),
                "--path",
                str(charts_index),
                "-t",
                "Trendlines charts",
                "-m",
                f"Daily trendlines+VZ charts — {len(syms)} symbols",
            ]
        )

    print(f"[trendlines_daily] Done — {charts_index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
