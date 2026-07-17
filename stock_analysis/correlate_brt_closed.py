#!/usr/bin/env python3
"""
Analyze BRT_Closed CSV: correlation of each numeric column with PNL_PCT, ANN_ROR_PCT,
and POST_ENTRY_GAIN_HIT (when present).

Output: CSV with one row per variable and columns:
Variable, R_PNL_PCT, R_ANN_ROR_PCT, R_POST_ENTRY_GAIN_HIT, R_Total.

Predictor rows exclude look-ahead labels and entry-bar-only fields (see CORRELATION_VAR_EXCLUDE).
Usage: python correlate_brt_closed.py <BRT_Closed_*.csv> [output.csv]
Or call run_correlation_report(closed_csv_path, output_csv_path) from rocket_brt after each run.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


def parse_pct(s):
    if pd.isna(s) or s == "":
        return None
    s = str(s).strip().replace("%", "").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


# Omit from single- and pair-correlation sweeps (outcome-adjacent, look-ahead, or entry-bar-only).
CORRELATION_VAR_EXCLUDE = frozenset({
    "DAYS_HELD_FIRST_UP_10PCT",
    "ATR_PCT_AT_ENTRY",
    "DAYS_HELD_FIRST_UP_20PCT",
    "DIST_TO_52W_HIGH_PCT",
    "REL_VOL_AT_ENTRY",
    "AVG_VOLUME_10D_AT_ENTRY",
    "HIGH_52W_AT_ENTRY",
    "DATE_FIRST_UP_20PCT",
    "ATR_14_AT_ENTRY",
    "DATE_FIRST_UP_10PCT",
    # Look-ahead / not knowable at trigger (purchase is D+1; trigger metrics use *_AT_TRIGGER).
    "ENTRY_MAJOR_PIVOT",
    "TOUCH_COUNT_MAJOR",
    "ENTRY_PIVOT_WAS_STRONG",
    "VOLUME_AT_ENTRY",
    "REALTIME_SCORE",
})

CORRELATION_TARGETS = ("PNL_PCT", "ANN_ROR_PCT", "POST_ENTRY_GAIN_HIT")

CORRELATION_TARGET_COLUMNS = {
    "PNL_PCT": "R_PNL_PCT",
    "ANN_ROR_PCT": "R_ANN_ROR_PCT",
    "POST_ENTRY_GAIN_HIT": "R_POST_ENTRY_GAIN_HIT",
}

BASE_EXCLUDE = {
    "SYMBOL", "DATE_OPENED", "DATE_CLOSED", "EXIT_TYPE", "STRUCT_HIGH", "STRUCT_LOW",
    "ENTRY_PIVOT_TYPE", "ENTRY_STRUCT_REGIME", "MATURITY_DATE", "CLOSE_ABOVE_DATE",
    "PNL_DOLLARS", "DAYS_HELD", "EXIT_PRICE", "MAX_PRICE",
}
_IND_CORR_NUMERIC = frozenset({"IND_DIFF", "IND_SCORE"})


def is_correlation_var_excluded(name: str) -> bool:
    u = str(name).upper()
    if u in CORRELATION_VAR_EXCLUDE:
        return True
    if u.startswith("Z_") and u[2:] in CORRELATION_VAR_EXCLUDE:
        return True
    return False


def corr_skip_col(name: str) -> bool:
    name_u = name.upper()
    if name_u in _IND_CORR_NUMERIC:
        return False
    if name.startswith("IND_"):
        return not name_u.endswith("_LAST") and not name_u.startswith("IND_ENTRY_")
    return False


def run_correlation_report(closed_csv_path: str, output_csv_path: str) -> None:
    """
    Compute correlations of each variable vs CORRELATION_TARGETS.
    Write a CSV: one row per variable, R_* columns per target, R_Total.
    """
    path = Path(closed_csv_path)
    if not path.exists():
        return
    df = pd.read_csv(path, low_memory=False)
    n = len(df)

    df["PNL_PCT"] = df["PNL_PCT"].map(parse_pct)
    df["ANN_ROR_PCT"] = df["ANN_ROR_PCT"].map(parse_pct)
    df = df.dropna(subset=["PNL_PCT", "ANN_ROR_PCT"])

    numeric_cols = []
    for c in df.columns:
        if c in BASE_EXCLUDE or corr_skip_col(c) or is_correlation_var_excluded(c):
            continue
        s = df[c]
        if s.dtype == object:
            conv = pd.to_numeric(
                s.replace("", None)
                .replace(r"^\s*$", None, regex=True)
                .astype(str)
                .str.replace("%", "", regex=False)
                .str.replace(",", "", regex=False),
                errors="coerce",
            )
            if conv.notna().sum() >= n // 2:
                numeric_cols.append(c)
                df[c] = conv
        elif pd.api.types.is_numeric_dtype(s):
            numeric_cols.append(c)

    if "PNL_PCT" not in numeric_cols:
        numeric_cols.append("PNL_PCT")
    if "ANN_ROR_PCT" not in numeric_cols:
        numeric_cols.append("ANN_ROR_PCT")

    corr_df = df[numeric_cols].astype(float)
    corr_df = corr_df.dropna(how="all", axis=1)

    targets = [t for t in CORRELATION_TARGETS if t in corr_df.columns]
    row_vars = [c for c in corr_df.columns if c not in targets]

    rows = []
    ref_stats_rows = []
    for var in row_vars:
        row: dict[str, object] = {"Variable": var}
        total = 0.0
        any_r = False
        for t in targets:
            out_key = CORRELATION_TARGET_COLUMNS[t]
            r = float("nan")
            valid = corr_df[t].notna() & corr_df[var].notna()
            if valid.sum() >= 2:
                r = corr_df.loc[valid, [var, t]].corr().iloc[0, 1]
            row[out_key] = r if not pd.isna(r) else ""
            if not pd.isna(r):
                total += r
                any_r = True
        row["R_Total"] = total if any_r else float("nan")
        rows.append(row)

        ser = corr_df[var].dropna()
        if len(ser) >= 2:
            ref_stats_rows.append({"Variable": var, "Mean": float(ser.mean()), "Std": float(ser.std())})
        else:
            ref_stats_rows.append({"Variable": var, "Mean": "", "Std": ""})

    out_df = pd.DataFrame(rows)

    def sort_key(i):
        v = out_df.iloc[i]["R_Total"]
        if pd.isna(v):
            return -1e9
        return abs(float(v))

    out_df = out_df.reindex(sorted(range(len(out_df)), key=sort_key, reverse=True))

    out = Path(output_csv_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(out, index=False, float_format="%.4f", na_rep="")

    ref_path = out.parent / "BRT_ReferenceStats.csv"
    ref_df = pd.DataFrame(ref_stats_rows)
    ref_df.to_csv(ref_path, index=False, float_format="%.6f", na_rep="")

    pairs_path = out.with_name(out.name.replace("_Correlation_", "_Correlation_Pairs_", 1))
    _sa = Path(__file__).resolve().parent
    if str(_sa) not in sys.path:
        sys.path.insert(0, str(_sa))
    from report_ind_pair_correlation import run_correlation_pairs_report

    run_correlation_pairs_report(closed_csv_path, str(out), str(pairs_path))


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path or not Path(path).exists():
        print("Usage: python correlate_brt_closed.py <BRT_Closed_*.csv> [output.csv]", file=sys.stderr)
        sys.exit(1)
    out_path = sys.argv[2] if len(sys.argv) > 2 else str(Path(path).with_name("BRT_Correlation.csv"))
    run_correlation_report(path, out_path)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
