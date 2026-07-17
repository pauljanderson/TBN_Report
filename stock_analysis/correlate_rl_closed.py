#!/usr/bin/env python3
"""
Correlate Rocket Launcher closed-trade fields with outcomes (higher PNL %, annualized ROR).

Reads ``RL_Closed_*.csv`` (column names with spaces, ``PNL %``, ``ANNUALIZED ROR``, etc.),
treats every other numeric column as a candidate driver, and writes a report shaped like
``BRT_Correlation_*.csv``: ``Variable``, ``R_PNL_PCT``, ``R_ANN_ROR_PCT``,
``R_POST_ENTRY_GAIN_HIT``, ``R_Total``.

Usage::

    python stock_analysis/correlate_rl_closed.py path/to/RL_Closed_ts.csv [RL_Correlation_ts.csv]

Or call ``run_rl_correlation_report(closed_csv_path, output_csv_path)`` from ``rl_emit_brt_mirror``.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

from correlate_brt_closed import (
    CORRELATION_TARGET_COLUMNS,
    CORRELATION_TARGETS,
    is_correlation_var_excluded,
)

# RL_Closed header names (AWK export)
_COL_PNL = "PNL %"
_COL_ANN = "ANNUALIZED ROR"
_COL_PIVOT_STRONG = "ENTRY_PIVOT_WAS_STRONG"
_COL_POST_GAIN = "POST_ENTRY_GAIN_HIT"

# Identifiers / non-numeric outcome labels (not used as correlation *predictors*)
_EXCLUDE_ID = {
    "SYMBOL",
    "DATE OPENED",
    "DATE CLOSED",
    "EXIT TYPE",
    "PARTIAL_DATE",
}


def _parse_pct(s) -> float | None:
    if pd.isna(s) or s == "":
        return None
    t = str(s).strip().replace("%", "").replace(",", "")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _parse_number(s) -> float | None:
    """ANNUALIZED ROR may appear as -0.5655, 13.2105, or with %."""
    if pd.isna(s) or s == "":
        return None
    t = str(s).strip().replace("%", "").replace(",", "")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _coerce_object_numeric(s: pd.Series) -> pd.Series | None:
    conv = pd.to_numeric(
        s.replace("", None)
        .replace(r"^\s*$", None, regex=True)
        .astype(str)
        .str.replace("%", "", regex=False)
        .str.replace(",", "", regex=False),
        errors="coerce",
    )
    if conv.notna().sum() >= 2:
        return conv
    return None


def run_rl_correlation_report(closed_csv_path: str, output_csv_path: str) -> None:
    path = Path(closed_csv_path)
    if not path.exists():
        return
    df = pd.read_csv(path, low_memory=False)
    df.columns = [str(c).strip() for c in df.columns]
    if len(df) < 2:
        return
    if _COL_PNL not in df.columns:
        print(f"[correlate_rl_closed] Missing {_COL_PNL!r} in {path}; skip.", file=sys.stderr)
        return

    work = df.copy()
    work["PNL_PCT"] = work[_COL_PNL].map(_parse_pct)
    work = work.dropna(subset=["PNL_PCT"])
    if len(work) < 2:
        return

    if _COL_ANN in work.columns:
        work["ANN_ROR_PCT"] = work[_COL_ANN].map(_parse_number)
    else:
        work["ANN_ROR_PCT"] = float("nan")

    # Optional BRT-style columns if present on enriched RL export
    for col, internal in (
        (_COL_PIVOT_STRONG, "ENTRY_PIVOT_WAS_STRONG"),
        (_COL_POST_GAIN, "POST_ENTRY_GAIN_HIT"),
    ):
        if col in work.columns:
            conv = _coerce_object_numeric(work[col])
            if conv is not None:
                work[internal] = conv
            else:
                work[internal] = pd.to_numeric(work[col], errors="coerce")
        else:
            work[internal] = float("nan")

    exclude = set(_EXCLUDE_ID)
    exclude.update({_COL_PNL, _COL_ANN, "PNL_PCT", "ANN_ROR_PCT", *CORRELATION_TARGETS})

    numeric_cols: list[str] = []
    for c in work.columns:
        if c in exclude or is_correlation_var_excluded(c):
            continue
        s = work[c]
        if s.dtype == object:
            conv = _coerce_object_numeric(s)
            if conv is not None:
                numeric_cols.append(c)
                work[c] = conv
        elif pd.api.types.is_numeric_dtype(s):
            numeric_cols.append(c)

    target_internals: list[str] = ["PNL_PCT"]
    if "ANN_ROR_PCT" in work.columns and work["ANN_ROR_PCT"].notna().sum() >= 2:
        target_internals.append("ANN_ROR_PCT")
    if "POST_ENTRY_GAIN_HIT" in work.columns and work["POST_ENTRY_GAIN_HIT"].notna().sum() >= 2:
        target_internals.append("POST_ENTRY_GAIN_HIT")

    row_vars = [c for c in numeric_cols if c not in target_internals]

    target_defs = [(t, CORRELATION_TARGET_COLUMNS[t]) for t in CORRELATION_TARGETS]

    corr_cols = list(dict.fromkeys(row_vars + target_internals))
    corr_df = work[corr_cols].apply(pd.to_numeric, errors="coerce")
    corr_df = corr_df.dropna(how="all", axis=1)

    targets_present = [t for t in target_internals if t in corr_df.columns]
    row_vars = [c for c in corr_df.columns if c not in targets_present]

    rows: list[dict[str, object]] = []
    ref_stats_rows: list[dict[str, object]] = []

    for var in row_vars:
        out_row: dict[str, object] = {"Variable": var}
        for _, out_key in target_defs:
            out_row[out_key] = ""
        r_vals: list[float] = []
        for internal, out_key in target_defs:
            if internal not in corr_df.columns:
                out_row[out_key] = ""
                continue
            valid = corr_df[internal].notna() & corr_df[var].notna()
            if valid.sum() < 2:
                out_row[out_key] = ""
                continue
            r = corr_df.loc[valid, [var, internal]].corr().iloc[0, 1]
            if pd.isna(r):
                out_row[out_key] = ""
            else:
                out_row[out_key] = float(r)
                r_vals.append(float(r))

        total = sum(r_vals) if r_vals else float("nan")
        out_row["R_Total"] = total if r_vals else float("nan")
        rows.append(out_row)

        ser = corr_df[var].dropna()
        if len(ser) >= 2:
            ref_stats_rows.append({"Variable": var, "Mean": float(ser.mean()), "Std": float(ser.std())})
        else:
            ref_stats_rows.append({"Variable": var, "Mean": "", "Std": ""})

    out_df = pd.DataFrame(rows)

    def sort_key(i: int) -> float:
        v = out_df.iloc[i]["R_Total"]
        if pd.isna(v):
            return -1e9
        return abs(float(v))

    out_df = out_df.reindex(sorted(range(len(out_df)), key=sort_key, reverse=True))

    out = Path(output_csv_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(out, index=False, float_format="%.4f", na_rep="")

    # Per-run reference stats (timestamped name when output is RL_Correlation_<ts>.csv)
    m = re.match(r"^RL_Correlation_(.+)\.csv$", out.name, re.I)
    if m:
        ref_path = out.parent / f"RL_ReferenceStats_{m.group(1)}.csv"
    else:
        ref_path = out.parent / "RL_ReferenceStats.csv"
    ref_df = pd.DataFrame(ref_stats_rows)
    ref_df.to_csv(ref_path, index=False, float_format="%.6f", na_rep="")

    pairs_path = out.with_name(out.name.replace("_Correlation_", "_Correlation_Pairs_", 1))
    try:
        import tempfile

        from report_ind_pair_correlation import run_correlation_pairs_report
    except ImportError:
        from stock_analysis.report_ind_pair_correlation import run_correlation_pairs_report  # type: ignore[no-redef]
        import tempfile

    tmp_path: Path | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(suffix=".csv")
        import os

        os.close(fd)
        tmp_path = Path(tmp_name)
        work.to_csv(tmp_path, index=False)
        run_correlation_pairs_report(str(tmp_path), str(out), str(pairs_path))
    except Exception as e:
        print(f"[correlate_rl_closed] Correlation pairs skipped: {e}", file=sys.stderr)
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path or not Path(path).exists():
        print(
            "Usage: python correlate_rl_closed.py <RL_Closed_*.csv> [RL_Correlation_*.csv]",
            file=sys.stderr,
        )
        return 1
    out_path = (
        sys.argv[2]
        if len(sys.argv) > 2
        else str(Path(path).with_name(Path(path).name.replace("RL_Closed_", "RL_Correlation_")))
    )
    run_rl_correlation_report(path, out_path)
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
