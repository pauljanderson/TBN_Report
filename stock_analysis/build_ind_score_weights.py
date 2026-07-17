"""
Build ind_score_weights.json from an IND_Closed (or BRT_Closed) CSV,
or from an IND_Correlation_* CSV (IND_<id>_LAST vs PNL_PCT Pearson r, scaled).
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

from brt_entry_indicators import INDICATOR_IDS, default_new_ind_score_weights_output_path


def backup_ind_score_weights(out_path: Path) -> Path | None:
    """Copy existing weights JSON aside using its last-modified time in the filename."""
    if not out_path.is_file():
        return None
    mtime = datetime.fromtimestamp(out_path.stat().st_mtime)
    stamp = mtime.strftime("%Y%m%d_%H%M%S")
    backup_path = out_path.with_name(f"{out_path.stem}_{stamp}{out_path.suffix}")
    shutil.copy2(out_path, backup_path)
    return backup_path


def _pnl_pct(raw: str) -> float | None:
    s = (raw or "").strip().replace("%", "").replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def build_weights(closed_csv: Path) -> dict:
    rows = list(csv.DictReader(closed_csv.open(encoding="utf-8")))
    weights: dict[str, float] = {}
    meta: dict[str, dict] = {}
    for iid in INDICATOR_IDS:
        col = f"IND_{iid}"
        pnls = [
            p
            for r in rows
            if r.get(col) == "BULL" and (p := _pnl_pct(r.get("PNL_PCT", ""))) is not None
        ]
        if pnls:
            avg = sum(pnls) / len(pnls)
            weights[iid] = round(avg, 6)
            meta[iid] = {"n_bull": len(pnls), "avg_pnl_pct": weights[iid]}
        else:
            weights[iid] = 0.0
            meta[iid] = {"n_bull": 0, "avg_pnl_pct": 0.0}
    return {
        "source": closed_csv.name,
        "trades": len(rows),
        "description": "Weight per indicator = mean PNL_PCT when IND_<id> is BULL at entry",
        "weights": weights,
        "meta": meta,
    }


def _closed_avg_pnl(closed_csv: Path | None) -> float | None:
    if closed_csv is None or not closed_csv.is_file():
        return None
    rows = list(csv.DictReader(closed_csv.open(encoding="utf-8")))
    pnls = [p for r in rows if (p := _pnl_pct(r.get("PNL_PCT", ""))) is not None]
    return (sum(pnls) / len(pnls)) if pnls else None


def _closed_bull_meta(closed_csv: Path | None) -> dict[str, dict]:
    meta: dict[str, dict] = {}
    if closed_csv is None or not closed_csv.is_file():
        return meta
    rows = list(csv.DictReader(closed_csv.open(encoding="utf-8")))
    for iid in INDICATOR_IDS:
        col = f"IND_{iid}"
        n = sum(1 for r in rows if r.get(col) == "BULL")
        meta[iid] = {"n_bull": n}
    return meta


def build_weights_from_correlation(
    correlation_csv: Path,
    *,
    closed_csv: Path | None = None,
    scale_avg_pnl: float | None = None,
) -> dict:
    """Map IND_<id>_LAST ``R_PNL_PCT`` to indicator weights (scaled to ~avg trade PNL)."""
    corr = pd.read_csv(correlation_csv)
    r_map: dict[str, float] = {}
    r_total_map: dict[str, float] = {}
    for _, row in corr.iterrows():
        var = str(row.get("Variable", "") or "")
        if not var.startswith("IND_") or not var.endswith("_LAST"):
            continue
        iid = var[4:-5]
        if iid not in INDICATOR_IDS:
            continue
        r_pnl = row.get("R_PNL_PCT")
        if r_pnl is not None and r_pnl != "" and pd.notna(r_pnl):
            r_map[iid] = float(r_pnl)
        r_tot = row.get("R_Total")
        if r_tot is not None and r_tot != "" and pd.notna(r_tot):
            r_total_map[iid] = float(r_tot)

    avg_pnl = scale_avg_pnl
    if avg_pnl is None:
        avg_pnl = _closed_avg_pnl(closed_csv)
    if avg_pnl is None:
        avg_pnl = 1.5

    positive_rs = [v for v in r_map.values() if v > 0]
    scale = avg_pnl / (sum(positive_rs) / len(positive_rs)) if positive_rs else 1.0

    bull_meta = _closed_bull_meta(closed_csv)
    weights: dict[str, float] = {}
    meta: dict[str, dict] = {}
    for iid in INDICATOR_IDS:
        r = r_map.get(iid, 0.0)
        w = round(r * scale, 6)
        weights[iid] = w
        entry: dict[str, float | int] = {
            "r_pnl_pct": round(r, 6),
            "r_total": round(r_total_map.get(iid, 0.0), 6),
            "weight": w,
            "scale": round(scale, 6),
        }
        if iid in bull_meta:
            entry["n_bull"] = bull_meta[iid]["n_bull"]
        meta[iid] = entry

    trades = 0
    if closed_csv is not None and closed_csv.is_file():
        trades = sum(1 for _ in csv.DictReader(closed_csv.open(encoding="utf-8")))

    return {
        "source": correlation_csv.name,
        "trades": trades,
        "description": (
            "Weight per indicator = R_PNL_PCT(IND_<id>_LAST vs PNL_PCT) "
            f"× scale ({scale:.4f}); scale = avg_pnl / mean(positive r)"
        ),
        "weights": weights,
        "meta": meta,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Build timestamped ind_score_weights_<stamp>.json from Closed or Correlation CSV")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--closed", type=Path, help="IND_Closed_*.csv or BRT_Closed_*.csv (BULL mean PNL)")
    src.add_argument(
        "--correlation",
        type=Path,
        help="IND_Correlation_*.csv (uses IND_<id>_LAST R_PNL_PCT, scaled)",
    )
    p.add_argument(
        "--closed-for-meta",
        type=Path,
        default=None,
        help="Optional closed CSV for trade count / n_bull when using --correlation",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output JSON (default: stock_analysis/ind_score_weights_<YYYYMMDD_HHMMSS>.json)",
    )
    args = p.parse_args()
    out_path = args.output or default_new_ind_score_weights_output_path()
    if args.correlation is not None:
        closed = args.closed_for_meta
        if closed is None:
            # Same run: IND_Closed_<ts>.csv alongside IND_Correlation_<ts>.csv
            stem = args.correlation.stem.replace("_Correlation", "_Closed")
            candidate = args.correlation.with_name(f"{stem}.csv")
            closed = candidate if candidate.is_file() else None
        payload = build_weights_from_correlation(args.correlation, closed_csv=closed)
    else:
        payload = build_weights(args.closed)
    backup_path = backup_ind_score_weights(out_path)
    if backup_path is not None:
        print(f"Backed up previous weights to {backup_path.name}")
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out_path} ({payload['trades']} trades, {len(payload['weights'])} signals)")


if __name__ == "__main__":
    main()
