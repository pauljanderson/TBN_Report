#!/usr/bin/env python3
"""DailyRun hook: trendline + VZ 6m charts, buy-low B score, holdings sells.

Universe = gettarget helds/opens ∪ live DailyRun Open ∪ Watchlist ∪ Scanner
∪ always-include (PaulTwenty ∪ SPY/APP/…) — deduped. Live sleeves come from
``dailyrun_system_status.live_trendline_systems`` (wired registry).

If a live-list name has no chart, generate it then score (no silent skip).
``buy_today.html`` always includes a Sell / caution holdings section (inverse
of buy-low B: weekly support DOWN and/or close through support).

Writes ``drive/paul_studies/trendlines_opens_latest/`` (charts + buy_today.html)
and copies ``drive/Trendlines_BuyToday_Latest.html`` + mobile inbox.

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
from trendlines_score_live import run_daily_score  # noqa: E402

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
    ap.add_argument("--skip-score", action="store_true", help="Charts only (tests)")
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

    py = sys.executable
    sym_file = out_dir / "_daily_symbols.txt"
    sym_file.write_text("\n".join(syms) + "\n", encoding="utf-8")

    _run(
        [
            py,
            str(_TOOLS / "gen_trendlines_tos_studies.py"),
            "--symbols-file",
            str(sym_file),
            "--stamp",
            "trendlines_opens_latest",
            "--stamp-dir",
            str(out_dir),
            "--intro",
            "Daily opens+helds+watch+scan universe: gettarget_positions + live DailyRun "
            "Open/Watchlist/Scanner + PaulTwenty + extras. Missing charts are generated, then scored.",
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

    if not args.skip_score:
        print("[trendlines_daily] scoring buy-low B + holdings sells (ensure missing charts first)")
        run_daily_score(
            args.drive,
            args.positions_csv,
            out_dir,
            skip_ntfy=True,
        )

    if not args.skip_ntfy:
        ntfy = [
            py,
            str(_TOOLS / "ntfy_job_done.py"),
            "--path",
            str(charts_index),
            "-t",
            "Trendlines charts + score",
            "-m",
            f"Daily trendlines+VZ+score — {len(syms)} symbols",
        ]
        score_html = out_dir / "buy_today.html"
        if score_html.is_file():
            ntfy[4:4] = ["--path", str(score_html)]
        _run(ntfy)

    print(f"[trendlines_daily] Done — {charts_index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
