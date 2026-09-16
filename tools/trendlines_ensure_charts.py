#!/usr/bin/env python3
"""Generate trendline + Vol Zone (VZ) charts when a live-list symbol has none.

Default for DailyRun / buy-today / overlay scoring: never silently skip a
name that is on a live list. If OHLC exists, build segments + PNG, then score.
If data truly does not exist (no local CSV), record NO DATA — do not fake a verdict.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
_TOOLS = _REPO / "tools"
_DATA = _REPO / "data" / "newdata" / "data"
DEFAULT_STAMP = _REPO / "drive" / "paul_studies" / "trendlines_opens_latest"


def ohlc_csv(symbol: str, data_dir: Path = _DATA) -> Path | None:
    sym = str(symbol or "").strip().upper()
    if not sym:
        return None
    for name in (f"{sym}.csv", f"{sym.replace('.', '-')}.csv"):
        path = data_dir / name
        if path.is_file():
            return path
    return None


def load_segments(stamp_dir: Path) -> dict[str, Any]:
    path = stamp_dir / "segments.json"
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    symbols = raw.get("symbols") or {}
    return symbols if isinstance(symbols, dict) else {}


def missing_chart_symbols(
    symbols: list[str],
    stamp_dir: Path,
) -> tuple[list[str], list[str], list[str]]:
    """Return (need_build, no_ohlc, already_ok)."""
    segs = load_segments(stamp_dir)
    charts = stamp_dir / "charts"
    need: list[str] = []
    no_ohlc: list[str] = []
    ok: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        sym = str(raw or "").strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        has_seg = bool((segs.get(sym) or {}).get("segments"))
        has_png = (charts / f"{sym}_tl_vz_6m.png").is_file()
        if has_seg and has_png:
            ok.append(sym)
            continue
        if ohlc_csv(sym) is None:
            no_ohlc.append(sym)
            print(f"[ensure_charts] NO DATA {sym}: no local OHLC CSV — cannot build chart")
            continue
        need.append(sym)
    return need, no_ohlc, ok


def ensure_charts(
    symbols: list[str],
    stamp_dir: Path | None = None,
    *,
    python_exe: str | None = None,
) -> dict[str, Any]:
    """Build missing segments + PNGs for ``symbols``. Merge into existing stamp."""
    stamp_dir = stamp_dir or DEFAULT_STAMP
    stamp_dir = stamp_dir if stamp_dir.is_absolute() else _REPO / stamp_dir
    stamp_dir.mkdir(parents=True, exist_ok=True)
    (stamp_dir / "charts").mkdir(parents=True, exist_ok=True)
    (stamp_dir / "studies").mkdir(parents=True, exist_ok=True)

    need, no_ohlc, ok = missing_chart_symbols(symbols, stamp_dir)
    result: dict[str, Any] = {
        "built": [],
        "no_ohlc": list(no_ohlc),
        "already_ok": list(ok),
        "failed": [],
        "stamp_dir": str(stamp_dir),
    }
    if not need:
        print(f"[ensure_charts] nothing to build ({len(ok)} already have charts, {len(no_ohlc)} no OHLC)")
        return result

    py = python_exe or sys.executable
    sym_file = stamp_dir / "_ensure_symbols.txt"
    sym_file.write_text("\n".join(need) + "\n", encoding="utf-8")
    print(f"[ensure_charts] building {len(need)} missing chart(s): {', '.join(need)}")

    tos = [
        py,
        str(_TOOLS / "gen_trendlines_tos_studies.py"),
        "--symbols-file",
        str(sym_file),
        "--stamp",
        stamp_dir.name,
        "--stamp-dir",
        str(stamp_dir),
        "--merge",
        "--intro",
        "Auto-built missing live-list charts (ensure_charts). Do not silently skip.",
    ]
    charts = [
        py,
        str(_TOOLS / "gen_trendlines_charts_html.py"),
        "--stamp-dir",
        str(stamp_dir),
        "--symbol-meta",
        str(stamp_dir / "symbol_meta.json"),
        "--only-missing",
        "--symbols",
        ",".join(need),
    ]
    for cmd in (tos, charts):
        print(f"[ensure_charts] {' '.join(cmd)}")
        proc = subprocess.run(cmd, cwd=str(_REPO))
        if proc.returncode != 0:
            result["failed"] = list(need)
            print(f"[ensure_charts] ERROR: command failed rc={proc.returncode}", file=sys.stderr)
            return result

    segs = load_segments(stamp_dir)
    charts_dir = stamp_dir / "charts"
    built: list[str] = []
    failed: list[str] = []
    for sym in need:
        if (segs.get(sym) or {}).get("segments") and (charts_dir / f"{sym}_tl_vz_6m.png").is_file():
            built.append(sym)
        else:
            failed.append(sym)
            print(f"[ensure_charts] still missing after build: {sym}")
    result["built"] = built
    result["failed"] = failed
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", default="", help="Comma-separated symbols")
    ap.add_argument("--symbols-file", type=Path, default=None)
    ap.add_argument("--stamp-dir", type=Path, default=DEFAULT_STAMP)
    args = ap.parse_args()
    syms: list[str] = []
    if args.symbols_file and args.symbols_file.is_file():
        text = args.symbols_file.read_text(encoding="utf-8")
        for part in text.replace(",", "\n").splitlines():
            if part.strip():
                syms.append(part.strip().upper())
    for part in str(args.symbols or "").split(","):
        if part.strip():
            syms.append(part.strip().upper())
    if not syms:
        print("No symbols given", file=sys.stderr)
        return 2
    out = ensure_charts(syms, args.stamp_dir)
    print(json.dumps({k: v for k, v in out.items() if k != "already_ok"} | {"n_ok": len(out["already_ok"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
