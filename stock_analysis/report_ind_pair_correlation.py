"""Pairwise variable combos: R_Total for z(A)+z(B) on Closed CSV (same targets as correlate_brt_closed)."""
from __future__ import annotations

import argparse
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

from correlate_brt_closed import (
    BASE_EXCLUDE,
    CORRELATION_TARGET_COLUMNS,
    CORRELATION_TARGETS,
    corr_skip_col,
    is_correlation_var_excluded,
    parse_pct,
)

TARGETS = CORRELATION_TARGETS


def _prepare_closed_df(closed_csv: Path) -> tuple[pd.DataFrame, list[str]]:
    df = pd.read_csv(closed_csv, low_memory=False)
    n = len(df)
    df["PNL_PCT"] = df["PNL_PCT"].map(parse_pct)
    df["ANN_ROR_PCT"] = df["ANN_ROR_PCT"].map(parse_pct)
    df = df.dropna(subset=["PNL_PCT", "ANN_ROR_PCT"])

    numeric_cols: list[str] = []
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

    for t in TARGETS:
        if t in df.columns and t not in numeric_cols:
            numeric_cols.append(t)

    corr_df = df[numeric_cols].astype(float)
    row_vars = [c for c in corr_df.columns if c not in TARGETS]
    return corr_df, row_vars


def _pearson_r(x: np.ndarray, y: np.ndarray) -> float:
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 2:
        return float("nan")
    a = x[mask]
    b = y[mask]
    if a.std() == 0 or b.std() == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def _r_total_for_array(x: np.ndarray, corr_df: pd.DataFrame) -> tuple[float, dict[str, float]]:
    rs: dict[str, float] = {}
    total = 0.0
    any_r = False
    for t in TARGETS:
        if t not in corr_df.columns:
            continue
        y = corr_df[t].to_numpy(dtype=float)
        r = _pearson_r(x, y)
        rs[t] = r
        if not np.isnan(r):
            total += r
            any_r = True
    return (total if any_r else float("nan")), rs


def _zscore_col(ser: pd.Series) -> np.ndarray | None:
    arr = ser.to_numpy(dtype=np.float64)
    m = np.nanmean(arr)
    s = np.nanstd(arr)
    if not np.isfinite(s) or s < 1e-12:
        return None
    z = (arr - m) / s
    z = np.clip(z, -10.0, 10.0)
    return z


def _load_single_r_totals(correlation_csv: Path) -> tuple[dict[str, float], set[str]]:
    """Return (var -> R_Total, vars with a computed single-variable R_Total)."""
    if not correlation_csv.is_file():
        return {}, set()
    df = pd.read_csv(correlation_csv)
    out: dict[str, float] = {}
    valid: set[str] = set()
    for _, row in df.iterrows():
        var = str(row.get("Variable", "")).strip()
        if not var:
            continue
        raw = row.get("R_Total", "")
        if pd.isna(raw) or str(raw).strip() == "":
            continue
        try:
            out[var] = float(raw)
            valid.add(var)
        except (TypeError, ValueError):
            pass
    return out, valid


def build_pair_report(
    closed_csv: Path,
    *,
    correlation_csv: Path | None = None,
    variables: list[str] | None = None,
    min_nonnull_frac: float = 0.5,
    top_n: int = 50,
) -> tuple[pd.DataFrame, int]:
    corr_df, row_vars = _prepare_closed_df(closed_csv)
    n_trades = len(corr_df)

    singles: dict[str, float] = {}
    valid_singles: set[str] = set()
    if correlation_csv:
        singles, valid_singles = _load_single_r_totals(correlation_csv)

    if variables:
        want = {v.strip() for v in variables if v.strip()}
        vars_use = [v for v in row_vars if v in want]
    elif valid_singles:
        vars_use = [v for v in row_vars if v in valid_singles]
    else:
        vars_use = list(row_vars)

    zcols: dict[str, np.ndarray] = {}
    for v in vars_use:
        if v not in corr_df.columns:
            continue
        nonnull = corr_df[v].notna().mean()
        if nonnull < min_nonnull_frac:
            continue
        z = _zscore_col(corr_df[v])
        if z is not None:
            zcols[v] = z

    usable = sorted(zcols.keys())
    rows: list[dict] = []
    for a, b in combinations(usable, 2):
        combo = zcols[a] + zcols[b]
        r_total, rs = _r_total_for_array(combo, corr_df)
        r_a = singles.get(a, float("nan"))
        r_b = singles.get(b, float("nan"))
        best_single = max(
            (x for x in (r_a, r_b) if not np.isnan(x)),
            default=float("nan"),
        )
        synergy = (
            float(r_total - best_single)
            if not np.isnan(r_total) and not np.isnan(best_single)
            else float("nan")
        )
        rows.append(
            {
                "Var_A": a,
                "Var_B": b,
                "Combo": "z(A)+z(B)",
                "N": int(np.isfinite(combo).sum()),
                **{
                    CORRELATION_TARGET_COLUMNS[t]: rs.get(t, float("nan"))
                    for t in TARGETS
                },
                "R_Total": r_total,
                "R_Total_A": r_a,
                "R_Total_B": r_b,
                "Synergy_vs_best_single": synergy,
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return out, n_trades

    out = out.sort_values("R_Total", ascending=False, na_position="last").reset_index(drop=True)
    return out, n_trades


def run_correlation_pairs_report(
    closed_csv_path: str,
    correlation_csv_path: str,
    output_csv_path: str,
) -> None:
    """Write ``{PREFIX}_Correlation_Pairs_<ts>.csv`` for a completed run."""
    closed = Path(closed_csv_path)
    corr = Path(correlation_csv_path)
    out = Path(output_csv_path)
    if not closed.is_file() or not corr.is_file():
        return
    df, _ = build_pair_report(closed, correlation_csv=corr)
    if df.empty:
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, float_format="%.4f", na_rep="")


def write_markdown(
    df: pd.DataFrame,
    path: Path,
    *,
    closed_name: str,
    correlation_name: str,
    n_trades: int,
    top_n: int = 40,
) -> None:
    lines = [
        "# Pairwise correlation (highest R_Total)",
        "",
        f"Source closed: `{closed_name}`",
        f"Source singles: `{correlation_name}`",
        f"Trades: {n_trades:,}",
        "",
        "Combo variable: **z(Var_A) + z(Var_B)** (standardized sum).",
        "R_Total = sum of Pearson r vs PNL_PCT, ANN_ROR_PCT, POST_ENTRY_GAIN_HIT (same as `correlate_brt_closed`).",
        "Synergy = pair R_Total − max(single R_Total of A, B) from the correlation report.",
        "",
        f"## Top {min(top_n, len(df))} pairs by R_Total",
        "",
        "| Rank | Var_A | Var_B | R_Total | R_PNL | R_POST | R_Total_A | R_Total_B | Synergy |",
        "|-----:|-------|-------|--------:|------:|-------:|----------:|----------:|--------:|",
    ]
    for rank, (_, row) in enumerate(df.head(top_n).iterrows(), start=1):

        def _f(col: str, nd: int = 4) -> str:
            v = row.get(col)
            if pd.isna(v):
                return ""
            return f"{float(v):+.{nd}f}"

        lines.append(
            f"| {rank} | {row['Var_A']} | {row['Var_B']} | {_f('R_Total')} | "
            f"{_f('R_PNL_PCT')} | {_f('R_POST_ENTRY_GAIN_HIT')} | "
            f"{_f('R_Total_A', 4)} | {_f('R_Total_B', 4)} | {_f('Synergy_vs_best_single')} |"
        )
    lines.append("")
    meaningful = df[
        df["Synergy_vs_best_single"].notna() & (df["Synergy_vs_best_single"] > 0.001)
    ].head(min(20, top_n))
    if not meaningful.empty:
        lines.extend(
            [
                "## Top pairs by synergy (pair R_Total beats best single)",
                "",
                "| Rank | Var_A | Var_B | R_Total | Synergy | R_Total_A | R_Total_B |",
                "|-----:|-------|-------|--------:|--------:|----------:|----------:|",
            ]
        )
        for rank, (_, row) in enumerate(meaningful.iterrows(), start=1):

            def _f2(col: str, nd: int = 4) -> str:
                v = row.get(col)
                if pd.isna(v):
                    return ""
                return f"{float(v):+.{nd}f}"

            lines.append(
                f"| {rank} | {row['Var_A']} | {row['Var_B']} | {_f2('R_Total')} | "
                f"{_f2('Synergy_vs_best_single')} | {_f2('R_Total_A')} | {_f2('R_Total_B')} |"
            )
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Pairwise variable R_Total report (z(A)+z(B) on Closed CSV)"
    )
    p.add_argument(
        "--correlation",
        type=Path,
        required=True,
        help="IND_Correlation_<run>.csv (variable list + single R_Total reference)",
    )
    p.add_argument(
        "--closed",
        type=Path,
        default=None,
        help="IND_Closed_<run>.csv (default: sibling of correlation file)",
    )
    p.add_argument("-o", "--output", type=Path, default=None)
    p.add_argument("--top", type=int, default=50, help="Rows in markdown summary")
    args = p.parse_args()

    corr_path = args.correlation.resolve()
    closed_path = args.closed or corr_path.with_name(
        corr_path.name.replace("_Correlation_", "_Closed_")
    )
    closed_path = closed_path.resolve()
    if not closed_path.is_file():
        raise FileNotFoundError(f"Closed CSV not found: {closed_path}")

    out_csv = args.output or corr_path.with_name(
        corr_path.name.replace("_Correlation_", "_Correlation_Pairs_")
    )
    out_md = out_csv.with_suffix(".md")

    df, n_trades = build_pair_report(closed_path, correlation_csv=corr_path)
    if df.empty:
        raise RuntimeError("No pair rows produced (check variable coverage).")

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False, float_format="%.4f", na_rep="")
    write_markdown(
        df,
        out_md,
        closed_name=closed_path.name,
        correlation_name=corr_path.name,
        n_trades=n_trades,
        top_n=args.top,
    )
    best = df.iloc[0]
    print(f"Wrote {out_csv}")
    print(f"Wrote {out_md}")
    print(f"Trades: {n_trades:,} · Pairs: {len(df):,}")
    print(
        f"Best pair: {best['Var_A']} + {best['Var_B']} "
        f"R_Total={float(best['R_Total']):+.4f} "
        f"(A={float(best['R_Total_A']):+.4f}, B={float(best['R_Total_B']):+.4f}, "
        f"synergy={float(best['Synergy_vs_best_single']):+.4f})"
    )


if __name__ == "__main__":
    main()
