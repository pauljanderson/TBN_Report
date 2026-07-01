#!/usr/bin/env python3
"""Compare Rocket Launcher outputs: legacy AWK run vs Python rl_mode=true run.

Usage:
  python tools/compare_rl_engine_outputs.py --output-dir drive --awk-ts 260629143410 --python-ts 260629181003

Compares RL_Closed, RL_Open, RL_Scanner, RL_Watchlist (CSV) when both sides exist.
Exits 0 only when all compared artifacts match.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RL_FILE_BASES = ("RL_Closed", "RL_Open", "RL_Scanner", "RL_Watchlist")

# Closed: trade keys + core fields (same as run_rl_parity.py)
CLOSED_KEY_COLS = ("SYMBOL", "DATE OPENED", "DATE CLOSED", "EXIT TYPE")
CLOSED_COMPARE_COLS = (
    "SYMBOL",
    "DATE OPENED",
    "DATE CLOSED",
    "ENTRY PRICE",
    "EXIT PRICE",
    "PNL %",
    "DAYS HELD",
    "EXIT TYPE",
    "ORIGINAL STOP",
    "ORIGINAL TARGET",
)


def _norm_header(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().upper())


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return []
        rows: list[dict[str, str]] = []
        for raw in reader:
            row = {_norm_header(k): (v or "").strip() for k, v in raw.items()}
            rows.append(row)
        return rows


def _floatish(s: str) -> float | None:
    s = s.replace("%", "").replace(",", "").replace("$", "").strip()
    if not s:
        return None
    try:
        return round(float(s), 4)
    except ValueError:
        return None


def _trade_key(row: dict[str, str], cols: tuple[str, ...]) -> tuple:
    return tuple(row.get(_norm_header(c), "") for c in cols)


def _compare_closed(awk_path: Path, py_path: Path, *, max_diffs: int = 20) -> list[str]:
    awk_rows = _load_csv(awk_path)
    py_rows = _load_csv(py_path)
    awk_map = {_trade_key(r, CLOSED_KEY_COLS): r for r in awk_rows}
    py_map = {_trade_key(r, CLOSED_KEY_COLS): r for r in py_rows}
    errors: list[str] = []

    for key in sorted(set(awk_map) - set(py_map)):
        errors.append(f"RL_Closed missing in Python: {key}")
    for key in sorted(set(py_map) - set(awk_map)):
        errors.append(f"RL_Closed extra in Python: {key}")

    for key in sorted(set(awk_map) & set(py_map)):
        g, c = awk_map[key], py_map[key]
        for col in CLOSED_COMPARE_COLS:
            nc = _norm_header(col)
            gv, cv = g.get(nc, ""), c.get(nc, "")
            if col in ("ENTRY PRICE", "EXIT PRICE", "ORIGINAL STOP", "ORIGINAL TARGET"):
                gf, cf = _floatish(gv), _floatish(cv)
                if gf is not None and cf is not None:
                    if abs(gf - cf) > 0.02:
                        errors.append(f"RL_Closed {key} {col}: AWK={gv} Python={cv}")
                elif gv != cv:
                    errors.append(f"RL_Closed {key} {col}: AWK={gv} Python={cv}")
            elif col == "PNL %":
                gf, cf = _floatish(gv), _floatish(cv)
                if gf is not None and cf is not None:
                    if abs(gf - cf) > 0.05:
                        errors.append(f"RL_Closed {key} {col}: AWK={gv} Python={cv}")
                elif gv != cv:
                    errors.append(f"RL_Closed {key} {col}: AWK={gv} Python={cv}")
            elif gv != cv:
                errors.append(f"RL_Closed {key} {col}: AWK={gv} Python={cv}")
            if len(errors) >= max_diffs:
                return errors
    return errors


def _row_key_open(row: dict[str, str]) -> tuple:
    return (
        row.get("SYMBOL", ""),
        row.get("DATE OPENED", ""),
    )


def _compare_table(
    label: str,
    awk_path: Path,
    py_path: Path,
    key_fn,
    *,
    float_cols: tuple[str, ...] = (),
    max_diffs: int = 20,
) -> list[str]:
    awk_rows = _load_csv(awk_path)
    py_rows = _load_csv(py_path)
    awk_map = {key_fn(r): r for r in awk_rows}
    py_map = {key_fn(r): r for r in py_rows}
    errors: list[str] = []

    for key in sorted(set(awk_map) - set(py_map)):
        errors.append(f"{label} missing in Python: {key}")
    for key in sorted(set(py_map) - set(awk_map)):
        errors.append(f"{label} extra in Python: {key}")

    cols = sorted(
        set(awk_rows[0].keys() if awk_rows else [])
        | set(py_rows[0].keys() if py_rows else [])
    )
    for key in sorted(set(awk_map) & set(py_map)):
        g, c = awk_map[key], py_map[key]
        for col in cols:
            gv, cv = g.get(col, ""), c.get(col, "")
            if col in float_cols:
                gf, cf = _floatish(gv), _floatish(cv)
                if gf is not None and cf is not None:
                    if abs(gf - cf) > 0.02:
                        errors.append(f"{label} {key} {col}: AWK={gv} Python={cv}")
                elif gv != cv:
                    errors.append(f"{label} {key} {col}: AWK={gv} Python={cv}")
            elif gv != cv:
                errors.append(f"{label} {key} {col}: AWK={gv} Python={cv}")
            if len(errors) >= max_diffs:
                return errors
    return errors


def compare_rl_runs(output_dir: Path, awk_ts: str, python_ts: str) -> tuple[bool, list[str]]:
    awk_ts = awk_ts.strip()
    python_ts = python_ts.strip()
    messages: list[str] = []
    ok = True

    messages.append(f"AWK run:    {awk_ts}")
    messages.append(f"Python run: {python_ts}")
    messages.append("")

    for base in RL_FILE_BASES:
        awk_path = output_dir / f"{base}_{awk_ts}.csv"
        py_path = output_dir / f"{base}_{python_ts}.csv"
        awk_exists = awk_path.is_file()
        py_exists = py_path.is_file()

        if not awk_exists and not py_exists:
            messages.append(f"{base}: skip (neither run produced file)")
            continue
        if awk_exists != py_exists:
            ok = False
            messages.append(
                f"{base}: FAIL — AWK={'yes' if awk_exists else 'no'} Python={'yes' if py_exists else 'no'}"
            )
            continue

        if base == "RL_Closed":
            diffs = _compare_closed(awk_path, py_path)
        elif base == "RL_Open":
            diffs = _compare_table("RL_Open", awk_path, py_path, _row_key_open, float_cols=("ENTRY PRICE", "CURRENT PRICE", "STOP LOSS", "TARGET", "PNL %"))
        elif base == "RL_Scanner":
            diffs = _compare_table(
                "RL_Scanner",
                awk_path,
                py_path,
                lambda r: (r.get("SYMBOL", ""), r.get("TRIGGER_DATE", "")),
                float_cols=("TRIGGER_CLOSE", "ENTRY_OPEN_REF", "STOP_LOSS", "TOO_HIGH_LINE", "TARGET"),
            )
        else:
            diffs = _compare_table(
                "RL_Watchlist",
                awk_path,
                py_path,
                lambda r: (r.get("SYMBOL", ""),),
                float_cols=("TRIGGER_CLOSE", "SMA50_REF", "SETUP_SCORE"),
            )

        if diffs:
            ok = False
            messages.append(f"{base}: FAIL ({len(diffs)} difference(s))")
            messages.extend(f"  {d}" for d in diffs[:15])
            if len(diffs) > 15:
                messages.append(f"  ... +{len(diffs) - 15} more")
        else:
            n_awk = len(_load_csv(awk_path))
            messages.append(f"{base}: PASS ({n_awk} rows)")

    return ok, messages


def main() -> int:
    ap = argparse.ArgumentParser(description="Compare AWK vs Python RL engine outputs")
    ap.add_argument("--output-dir", type=Path, default=ROOT / "drive")
    ap.add_argument("--awk-ts", required=True, help="Timestamp from legacy run_audit / AWK")
    ap.add_argument("--python-ts", required=True, help="Timestamp from rocket_brt rl_mode=true")
    args = ap.parse_args()

    out_dir = args.output_dir.resolve()
    ok, lines = compare_rl_runs(out_dir, args.awk_ts, args.python_ts)
    print("\n".join(lines))
    if ok:
        print("\nPASS: AWK and Python RL outputs match.")
        return 0
    print("\nFAIL: AWK vs Python RL output mismatch.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
