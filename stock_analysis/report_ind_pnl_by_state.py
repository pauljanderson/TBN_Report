"""Report avg PnL by BULL/BEAR/NEUTRAL for each IND_* indicator on a Closed CSV."""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from brt_entry_indicators import INDICATOR_IDS

STATES = ("BULL", "BEAR", "NEUTRAL")


def _pnl_series(raw: pd.Series) -> pd.Series:
    return pd.to_numeric(raw.astype(str).str.replace("%", "", regex=False), errors="coerce")


def build_report(closed_csv: Path) -> tuple[pd.DataFrame, int]:
    cols = ["PNL_PCT"] + [f"IND_{iid}" for iid in INDICATOR_IDS]
    stats = {iid: {st: [] for st in STATES} for iid in INDICATOR_IDS}
    total_rows = 0

    for ch in pd.read_csv(closed_csv, usecols=cols, chunksize=100_000, low_memory=False):
        ch = ch.copy()
        ch["pnl"] = _pnl_series(ch["PNL_PCT"])
        ch = ch.dropna(subset=["pnl"])
        total_rows += len(ch)
        for iid in INDICATOR_IDS:
            col = f"IND_{iid}"
            if col not in ch.columns:
                continue
            ser = ch[col].astype(str).str.strip().str.upper()
            for state in STATES:
                mask = ser == state
                if mask.any():
                    stats[iid][state].extend(ch.loc[mask, "pnl"].tolist())

    rows: list[dict] = []
    for iid in INDICATOR_IDS:
        for state in STATES:
            pnls = stats[iid][state]
            n = len(pnls)
            if n == 0:
                rows.append(
                    {
                        "Indicator": iid,
                        "State": state,
                        "N": 0,
                        "Avg_PnL_Pct": None,
                        "Win_Rate_Pct": None,
                        "Total_PnL_Pct": None,
                    }
                )
            else:
                avg = sum(pnls) / n
                win = 100.0 * sum(1 for p in pnls if p > 0) / n
                rows.append(
                    {
                        "Indicator": iid,
                        "State": state,
                        "N": n,
                        "Avg_PnL_Pct": round(avg, 4),
                        "Win_Rate_Pct": round(win, 2),
                        "Total_PnL_Pct": round(sum(pnls), 2),
                    }
                )
    return pd.DataFrame(rows), total_rows


def write_markdown(df: pd.DataFrame, path: Path, *, closed_name: str, total_rows: int) -> None:
    lines = [
        "# IND indicator PnL by state",
        "",
        f"Source: `{closed_name}`",
        f"Trades analyzed: {total_rows:,}",
        "",
        "States are as stored on the trigger bar (`IND_*` columns at entry signal).",
        "",
    ]
    for iid in INDICATOR_IDS:
        sub = df[df["Indicator"] == iid]
        if int(sub["N"].sum()) == 0:
            continue
        lines.append(f"## {iid}")
        lines.append("")
        lines.append("| State | N | Avg PnL % | Win % |")
        lines.append("|-------|---:|----------:|------:|")
        for _, r in sub.iterrows():
            if int(r["N"]) == 0:
                continue
            lines.append(
                f"| {r['State']} | {int(r['N']):,} | {float(r['Avg_PnL_Pct']):+.4f} | {float(r['Win_Rate_Pct']):.1f} |"
            )
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description="IND indicator avg PnL by BULL/BEAR/NEUTRAL")
    p.add_argument("--closed", type=Path, required=True, help="IND_Closed_*.csv")
    p.add_argument("-o", "--output", type=Path, default=None, help="Output CSV path")
    args = p.parse_args()

    closed = args.closed.resolve()
    run_id = closed.stem.replace("IND_Closed_", "")
    out_csv = args.output or closed.parent / f"IND_Indicator_PnL_By_State_{run_id}.csv"
    out_md = out_csv.with_suffix(".md")

    df, total_rows = build_report(closed)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    write_markdown(df, out_md, closed_name=closed.name, total_rows=total_rows)
    print(f"Wrote {out_csv}")
    print(f"Wrote {out_md}")
    print(f"Trades: {total_rows:,}")


if __name__ == "__main__":
    main()
