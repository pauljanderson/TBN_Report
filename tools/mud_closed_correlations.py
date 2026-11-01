#!/usr/bin/env python3
"""Compact correlation tables from MUD research Closed (Sheets-friendly).

The full Closed file is too large for Google Sheets (~845k rows). This writes:
  - mud_correlations.csv           (all slices combined)
  - mud_correlations_longs.csv     (LONG + IS_LONG + OOS_LONG only)
  - mud_correlations_shorts.csv    (SHORT + IS_SHORT + OOS_SHORT only)
  - mud_corr_matrix.csv            (pairwise Pearson, full book)
  - mud_corr_matrix_longs.csv
  - mud_corr_matrix_shorts.csv
  - correlations.html

Usage:
  python tools/mud_closed_correlations.py
  python tools/mud_closed_correlations.py --closed path/to/MUD_Closed.csv
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
_PE = _REPO / "drive" / "paul_experiments"
_TOOLS = _REPO / "tools"
for _p in (_PE, _TOOLS, _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from report_page_extras import (  # noqa: E402
    RESPONSIVE_TABLE_CSS,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

STAMP_DIR = _PE / "mud_system_L5_R1_20261005"
IS_CUT = date(2024, 1, 1)

FEATURE_COLS = [
    "LOOKBACK_RETURN_PCT",
    "RANK_PERCENTILE",
    "RANK_INDEX",
    "N_RANKED",
    "SLEEVE_SIZE",
    "VOLUME_AT_TRIGGER",
    "AVG_VOLUME_10D_AT_TRIGGER",
    "REL_VOL_AT_TRIGGER",
    "ATR_14_AT_TRIGGER",
    "ATR_PCT_AT_TRIGGER",
    "RSI14_AT_TRIGGER",
    "HIGH_52W_AT_TRIGGER",
    "DIST_TO_52W_HIGH_PCT_AT_TRIGGER",
    "VOLUME_AT_ENTRY",
    "AVG_VOLUME_10D_AT_ENTRY",
    "REL_VOL_AT_ENTRY",
    "ATR_14_AT_ENTRY",
    "ATR_PCT_AT_ENTRY",
    "RSI14_AT_ENTRY",
    "HIGH_52W_AT_ENTRY",
    "DIST_TO_52W_HIGH_PCT",
    "MARKET_CAP",
    "BETA",
    "FLOAT_SHARES",
    "SHORT_PERCENT_OF_FLOAT",
    "ENTRY_PRICE",
    "DAYS_HELD",
    "TRADING_DAYS_HELD",
]

LOG_SRC = {
    "LOG10_VOLUME_AT_TRIGGER": "VOLUME_AT_TRIGGER",
    "LOG10_AVG_VOLUME_10D_AT_TRIGGER": "AVG_VOLUME_10D_AT_TRIGGER",
    "LOG10_VOLUME_AT_ENTRY": "VOLUME_AT_ENTRY",
    "LOG10_MARKET_CAP": "MARKET_CAP",
    "LOG10_FLOAT_SHARES": "FLOAT_SHARES",
}

OUTCOME_COLS = ["PNL_PCT", "PNL_DOLLARS", "WIN"]

MATRIX_COLS = [
    "PNL_PCT",
    "LOOKBACK_RETURN_PCT",
    "RANK_PERCENTILE",
    "REL_VOL_AT_TRIGGER",
    "ATR_PCT_AT_TRIGGER",
    "RSI14_AT_TRIGGER",
    "DIST_TO_52W_HIGH_PCT_AT_TRIGGER",
    "LOG10_VOLUME_AT_TRIGGER",
    "LOG10_MARKET_CAP",
    "BETA",
    "SHORT_PERCENT_OF_FLOAT",
]


def _latest_closed(stamp: Path) -> Path:
    files = sorted(stamp.glob("MUD_Closed_*.csv"))
    if not files:
        raise SystemExit(f"No MUD_Closed_*.csv in {stamp}")
    return files[-1]


def _th(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{typ}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _corr_pair(a: pd.Series, b: pd.Series) -> tuple[Optional[float], Optional[float], int]:
    d = pd.concat([a, b], axis=1).dropna()
    d.columns = ["a", "b"]
    n = int(len(d))
    if n < 30:
        return None, None, n
    pear = float(d["a"].corr(d["b"], method="pearson"))
    spear = float(d["a"].corr(d["b"], method="spearman"))
    if not math.isfinite(pear):
        pear = None
    if not math.isfinite(spear):
        spear = None
    return pear, spear, n


def main() -> int:
    ap = argparse.ArgumentParser(description="MUD Closed correlations (Sheets-friendly)")
    ap.add_argument("--closed", type=Path, default=None)
    ap.add_argument("--out-dir", type=Path, default=STAMP_DIR)
    args = ap.parse_args()
    closed_path = args.closed or _latest_closed(args.out_dir)
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    usecols = (
        ["SYMBOL", "SIDE", "DATE_OPENED", "PNL_PCT", "PNL_DOLLARS"]
        + FEATURE_COLS
    )
    print(f"Reading {closed_path} …", flush=True)
    df = pd.read_csv(closed_path, usecols=lambda c: c in usecols, low_memory=False)
    df["DATE_OPENED"] = pd.to_datetime(df["DATE_OPENED"], errors="coerce")
    df["WIN"] = (pd.to_numeric(df["PNL_PCT"], errors="coerce") > 0).astype(float)
    for col in FEATURE_COLS + ["PNL_PCT", "PNL_DOLLARS"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for new, src in LOG_SRC.items():
        if src in df.columns:
            s = df[src]
            df[new] = np.where((s > 0) & np.isfinite(s), np.log10(s), np.nan)

    features = FEATURE_COLS + list(LOG_SRC.keys())
    side = df["SIDE"].astype(str).str.lower()
    is_mask = df["DATE_OPENED"] < pd.Timestamp(IS_CUT)
    oos_mask = df["DATE_OPENED"] >= pd.Timestamp(IS_CUT)
    long_mask = side == "long"
    short_mask = side == "short"
    slices: dict[str, pd.DataFrame] = {
        "FULL": df,
        "IS": df[is_mask],
        "OOS": df[oos_mask],
        "LONG": df[long_mask],
        "SHORT": df[short_mask],
        "IS_LONG": df[is_mask & long_mask],
        "IS_SHORT": df[is_mask & short_mask],
        "OOS_LONG": df[oos_mask & long_mask],
        "OOS_SHORT": df[oos_mask & short_mask],
    }

    fieldnames = [
        "SLICE",
        "FIELD",
        "WHEN",
        "OUTCOME",
        "PEARSON",
        "SPEARMAN",
        "ABS_PEARSON",
        "N",
    ]

    def _when(feat: str) -> str:
        if "TRIGGER" in feat:
            return "trigger"
        if "ENTRY" in feat or feat == "DIST_TO_52W_HIGH_PCT":
            return "entry"
        return "other"

    def _rows_for(slice_names: list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for slice_name in slice_names:
            sub = slices[slice_name]
            for feat in features:
                if feat not in sub.columns:
                    continue
                for outcome in OUTCOME_COLS:
                    pear, spear, n = _corr_pair(sub[feat], sub[outcome])
                    out.append(
                        {
                            "SLICE": slice_name,
                            "FIELD": feat,
                            "WHEN": _when(feat),
                            "OUTCOME": outcome,
                            "PEARSON": "" if pear is None else f"{pear:.6f}",
                            "SPEARMAN": "" if spear is None else f"{spear:.6f}",
                            "ABS_PEARSON": "" if pear is None else f"{abs(pear):.6f}",
                            "N": n,
                        }
                    )
        return out

    def _write_corr_csv(path: Path, rows: list[dict[str, Any]]) -> None:
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)

    long_slice_names = {"LONG", "IS_LONG", "OOS_LONG"}
    short_slice_names = {"SHORT", "IS_SHORT", "OOS_SHORT"}

    rows_out = _rows_for(list(slices.keys()))
    rows_long = [r for r in rows_out if r["SLICE"] in long_slice_names]
    rows_short = [r for r in rows_out if r["SLICE"] in short_slice_names]

    corr_csv = out_dir / "mud_correlations.csv"
    corr_long_csv = out_dir / "mud_correlations_longs.csv"
    corr_short_csv = out_dir / "mud_correlations_shorts.csv"
    _write_corr_csv(corr_csv, rows_out)
    _write_corr_csv(corr_long_csv, rows_long)
    _write_corr_csv(corr_short_csv, rows_short)

    # Pairwise Pearson matrices: full / longs / shorts
    mat_cols = [c for c in MATRIX_COLS if c in df.columns]
    mat_csv = out_dir / "mud_corr_matrix.csv"
    mat_long_csv = out_dir / "mud_corr_matrix_longs.csv"
    mat_short_csv = out_dir / "mud_corr_matrix_shorts.csv"
    df[mat_cols].corr(method="pearson").to_csv(mat_csv, float_format="%.6f")
    df.loc[long_mask, mat_cols].corr(method="pearson").to_csv(
        mat_long_csv, float_format="%.6f"
    )
    df.loc[short_mask, mat_cols].corr(method="pearson").to_csv(
        mat_short_csv, float_format="%.6f"
    )

    ask = (
        "is there any way you could split the correlation file up into "
        "correlation scores for shorts, and correlation scores for longs?"
    )
    plain = (
        "Yes. Google Sheets cannot open the full Most Up / Most Down (MUD) Closed book, "
        "so the correlation pack is now split: one file for long trades only, one for short "
        "trades only (each with full / in-sample / out-of-sample rows), plus matching pairwise "
        "matrices. Trigger fields are known on the signal close (predictive); entry fields are at fill."
    )

    def block(rows: list[dict[str, Any]], slice_name: str, outcome: str = "PNL_PCT") -> str:
        chunk = [
            r for r in rows if r["SLICE"] == slice_name and r["OUTCOME"] == outcome
        ]
        chunk.sort(key=lambda r: float(r["ABS_PEARSON"] or 0), reverse=True)
        ths = "".join(
            [
                _th("Field", "text"),
                _th("When", "text"),
                _th("Pearson vs " + outcome, "num"),
                _th("Spearman", "num"),
                _th("|Pearson|", "num"),
                _th("N", "num"),
            ]
        )
        body = []
        for r in chunk:
            body.append(
                "<tr>"
                f"<td>{html_mod.escape(r['FIELD'])}</td>"
                f"<td>{html_mod.escape(r['WHEN'])}</td>"
                f"<td>{r['PEARSON'] or '—'}</td>"
                f"<td>{r['SPEARMAN'] or '—'}</td>"
                f"<td>{r['ABS_PEARSON'] or '—'}</td>"
                f"<td>{r['N']:,}</td>"
                "</tr>"
            )
        return (
            f"<h3>{html_mod.escape(slice_name)} — vs {html_mod.escape(outcome)}</h3>"
            f"{SWIPE_NOTE_HTML}<div class=\"table-wrap\"><table class=\"sortable\">"
            f"<thead><tr>{ths}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
        )

    n_long = int(long_mask.sum())
    n_short = int(short_mask.sum())
    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>MUD correlations — L5_R1</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:1.2rem;line-height:1.45;color:#222}}
.callout{{background:#f4f7fb;border-left:4px solid #2a6;padding:.8rem 1rem;margin:1rem 0}}
code{{font-family:ui-monospace,Consolas,monospace}}
{SORTABLE_TH_CSS}
</style></head><body>
<h1>MUD (Most Up / Most Down) — correlations (Sheets-friendly)</h1>
<div class="callout"><h2>What you asked</h2><p>{html_mod.escape(ask)}</p>
<h2>In plain English</h2><p>{plain}</p></div>
<p>Source Closed: <code>{html_mod.escape(str(closed_path))}</code>
(N={len(df):,}; longs={n_long:,}; shorts={n_short:,}).</p>
<p>Paste into Sheets:</p>
<ul>
<li><code>mud_correlations_longs.csv</code> — long sleeve only (LONG / IS_LONG / OOS_LONG)</li>
<li><code>mud_correlations_shorts.csv</code> — short sleeve only (SHORT / IS_SHORT / OOS_SHORT)</li>
<li><code>mud_corr_matrix_longs.csv</code> / <code>mud_corr_matrix_shorts.csv</code> — pairwise matrices</li>
<li><code>mud_correlations.csv</code> — combined (still includes FULL / IS / OOS)</li>
</ul>
<p>Pearson = linear association. Spearman = rank association (better if a field is skewed, e.g. volume).
In-sample is entry before 2024-01-01; out-of-sample is on/after. Research only.</p>
<p>Click column headers to sort.</p>
<h2>Longs</h2>
{block(rows_long, "LONG")}
{block(rows_long, "IS_LONG")}
{block(rows_long, "OOS_LONG")}
<h2>Shorts</h2>
{block(rows_short, "SHORT")}
{block(rows_short, "IS_SHORT")}
{block(rows_short, "OOS_SHORT")}
<h2>Combined book (for reference)</h2>
{block(rows_out, "FULL")}
{block(rows_out, "IS")}
{block(rows_out, "OOS")}
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    html_path = out_dir / "correlations.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"Wrote {corr_csv} ({len(rows_out)} rows)", flush=True)
    print(f"Wrote {corr_long_csv} ({len(rows_long)} rows)", flush=True)
    print(f"Wrote {corr_short_csv} ({len(rows_short)} rows)", flush=True)
    print(f"Wrote {mat_csv}", flush=True)
    print(f"Wrote {mat_long_csv}", flush=True)
    print(f"Wrote {mat_short_csv}", flush=True)
    print(f"Wrote {html_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
