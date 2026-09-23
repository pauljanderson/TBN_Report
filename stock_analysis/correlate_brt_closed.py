#!/usr/bin/env python3
"""
Analyze Closed CSV (BRT/YH/SB/RSI/…): correlation of each numeric column with PNL_PCT,
ANN_ROR_PCT, and POST_ENTRY_GAIN_HIT (when present).

Output: CSV with one row per variable and columns:
Variable, R_PNL_PCT, R_ANN_ROR_PCT, R_POST_ENTRY_GAIN_HIT, R_Total.

Purpose: find features known at **trigger** (or at worst **entry**) that
correlate with entering a winning trade. Outcome columns stay Y-only
(PNL_PCT / ANN_ROR_PCT / POST_ENTRY_GAIN_HIT). Lagging X — exit-bar,
hold-path, after-the-fill — are dropped (e.g. RSI14_AT_EXIT, MAE/MFE,
DAYS_HELD, EXIT_TYPE, realized R).

For SB, burst DNA on Closed (PCT_DAY, DCR, RANGE_EXP, VOL_RATIO, VOL_VS_50,
SIGNAL_LOW, RISK_PCT, MM_RATIO, T1_*) is included automatically after
``_splice_burst_dna_columns`` in ``rocket_stockbee_burst``.
SIGNAL_DATE is on Closed but excluded here (date stamp in BASE_EXCLUDE).
Note: VOL_RATIO = V[T]/V[T−1]; VOL_VS_50 = V[T]/mean(prior 50d volume).

See BASE_EXCLUDE / CORRELATION_VAR_EXCLUDE / is_correlation_var_excluded.
Usage: python correlate_brt_closed.py <BRT_Closed_*.csv> [output.csv]
Or call run_correlation_report(closed_csv_path, output_csv_path) from rocket_brt / SB after each run.
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
# Prefer *_AT_TRIGGER. Entry-bar peers stay listed here when the house already
# chose trigger snapshots (purchase is D+1).
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
    # Realized R at exit (STOP ~ -1, TARGET +1.5, TIME = (exit-entry)/risk).
    # Outcome leak spliced onto Closed DNA — not a trigger-time / pre-trade correlate.
    "R_MULT",
    "R_MULTIPLE",
    # Exit-bar / hold-path (also caught by suffix / pattern rules below).
    "RSI14_AT_EXIT",
})

# Hold-path / after-fill outcome fields. Known only after the trade starts
# (or ends). Used as X they leak the result. Spaces in RL headers normalize
# to these names (DAYS HELD → DAYS_HELD, MAX DRAW DOWN → MAX_DRAW_DOWN).
_LAGGING_CORR_EXACT = frozenset({
    "MAE",
    "MFE",
    "MAE_PCT",
    "MFE_PCT",
    "MAX_PRICE",
    "MIN_PRICE",
    "DAYS_HELD",
    "EXIT_PRICE",
    "EXIT_TYPE",
    "PNL_DOLLARS",
    "DATE_CLOSED",
    "WIN",
    "WIN_FLAG",
    "IS_WIN",
    "MAX_DRAW_DOWN",
    "MAX_DRAWDOWN",
    "MAX_DD",
    "DRAW_DOWN",
    "DRAWDOWN",
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
    "BREAKOUT_DATE", "SIGNAL_DATE", "LAST_ATH_DATE_AT_ENTRY",
    "PNL_DOLLARS", "DAYS_HELD", "EXIT_PRICE", "MAX_PRICE",
}
_IND_CORR_NUMERIC = frozenset({"IND_DIFF", "IND_SCORE"})


def _corr_norm_name(name: str) -> str:
    """Uppercase identifier: spaces/hyphens → underscore (RL 'DAYS HELD' → DAYS_HELD)."""
    return str(name).strip().upper().replace(" ", "_").replace("-", "_")


def _is_lagging_corr_name(u: str) -> bool:
    """True when *u* (already normalized) is not knowable at trigger / entry."""
    if u in CORRELATION_VAR_EXCLUDE or u in _LAGGING_CORR_EXACT:
        return True
    if u.endswith("_AT_EXIT") or u.endswith("_ON_EXIT"):
        return True
    if u.startswith("MAE_") or u.startswith("MFE_"):
        return True
    if u.startswith("DAYS_HELD"):
        return True
    if u.startswith("DATE_FIRST_UP"):
        return True
    # Path-to-target after fill (DAYS_TO_10 …). DAYS_TO_TIME_STOP is the
    # remaining calendar to the frozen time-stop — known at entry.
    if u.startswith("DAYS_TO_") and u != "DAYS_TO_TIME_STOP":
        return True
    if u.endswith("_TO_CLOSE"):
        return True
    # Peak/trough RSI along the hold — not the freeze gate MAX_RSI_TRIGGER.
    if "MAX_RSI" in u and "TRIGGER" not in u:
        return True
    if "MIN_RSI" in u and "TRIGGER" not in u:
        return True
    if u.endswith("_IN_TRADE") or u.endswith("_DURING_TRADE") or u.endswith("_IN_HOLD"):
        return True
    return False


def is_correlation_var_excluded(name: str) -> bool:
    u = _corr_norm_name(name)
    if _is_lagging_corr_name(u):
        return True
    if u.startswith("Z_") and _is_lagging_corr_name(u[2:]):
        return True
    return False


def correlation_pairs_path(correlation_csv_path: str | Path) -> Path:
    """Sibling Pairs CSV for a singles correlation file.

    Stamped ``*_Correlation_<ts>.csv`` → ``*_Correlation_Pairs_<ts>.csv``.
    Alias ``*_LatestRun_Correlation.csv`` has no ``_Correlation_`` infix —
    map that to ``*_LatestRun_Correlation_Pairs.csv`` (do not overwrite singles).
    """
    out = Path(correlation_csv_path)
    name = out.name
    if "_Correlation_Pairs_" in name or name.endswith("_Correlation_Pairs.csv"):
        return out
    if "_Correlation_" in name:
        return out.with_name(name.replace("_Correlation_", "_Correlation_Pairs_", 1))
    if name.endswith("_Correlation.csv"):
        return out.with_name(name[: -len(".csv")] + "_Pairs.csv")
    return out.with_name(out.stem + "_Pairs.csv")


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

    pairs_path = correlation_pairs_path(out)
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
