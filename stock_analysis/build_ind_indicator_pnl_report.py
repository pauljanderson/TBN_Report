"""
Average PNL_PCT by indicator state (BULL / BEAR / NEUTRAL) from IND_Closed CSV.

Uses IND_<id> columns at entry (trigger snapshot on closed trades).
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from brt_entry_indicators import INDICATOR_IDS

STATES = ("BULL", "BEAR", "NEUTRAL")


@dataclass
class _Bucket:
    n: int = 0
    pnl_sum: float = 0.0
    wins: int = 0

    def add(self, pnl: float) -> None:
        self.n += 1
        self.pnl_sum += pnl
        if pnl > 0:
            self.wins += 1

    @property
    def avg_pnl(self) -> float | None:
        return (self.pnl_sum / self.n) if self.n else None

    @property
    def win_rate(self) -> float | None:
        return (self.wins / self.n) if self.n else None


@dataclass
class _IndicatorStats:
    bull: _Bucket = field(default_factory=_Bucket)
    bear: _Bucket = field(default_factory=_Bucket)
    neutral: _Bucket = field(default_factory=_Bucket)
    other: _Bucket = field(default_factory=_Bucket)

    def bucket(self, state: str) -> _Bucket:
        s = (state or "").strip().upper()
        if s == "BULL":
            return self.bull
        if s == "BEAR":
            return self.bear
        if s == "NEUTRAL":
            return self.neutral
        return self.other


def _pnl_pct(raw: str) -> float | None:
    s = (raw or "").strip().replace("%", "").replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def build_indicator_pnl_report(closed_csv: Path) -> tuple[list[dict], int]:
    stats: dict[str, _IndicatorStats] = {iid: _IndicatorStats() for iid in INDICATOR_IDS}
    trade_n = 0
    cols = [f"IND_{iid}" for iid in INDICATOR_IDS]
    usecols = ["PNL_PCT", *cols]

    with closed_csv.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in usecols if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{closed_csv.name} missing columns: {missing[:5]}{'...' if len(missing) > 5 else ''}")
        for row in reader:
            pnl = _pnl_pct(row.get("PNL_PCT", ""))
            if pnl is None:
                continue
            trade_n += 1
            for iid in INDICATOR_IDS:
                state = row.get(f"IND_{iid}", "")
                stats[iid].bucket(str(state)).add(pnl)

    rows: list[dict] = []
    for iid in INDICATOR_IDS:
        st = stats[iid]
        entry: dict = {"indicator": iid}
        for label, b in (
            ("bull", st.bull),
            ("bear", st.bear),
            ("neutral", st.neutral),
        ):
            entry[f"n_{label}"] = b.n
            entry[f"avg_pnl_{label}"] = round(b.avg_pnl, 4) if b.avg_pnl is not None else ""
            entry[f"win_rate_{label}"] = round(b.win_rate, 4) if b.win_rate is not None else ""
        entry["n_other"] = st.other.n
        rows.append(entry)
    return rows, trade_n


def write_report_csv(rows: list[dict], out_path: Path, *, source: str, trades: int) -> None:
    headers = ["indicator"]
    for label in ("bull", "bear", "neutral"):
        headers.extend([f"n_{label}", f"avg_pnl_{label}", f"win_rate_{label}"])
    headers.append("n_other")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=headers, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {out_path} ({trades} trades, {len(rows)} indicators, source={source})")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Avg PNL_PCT by BULL/BEAR/NEUTRAL for each IND_* indicator on closed trades"
    )
    p.add_argument("--closed", type=Path, required=True, help="IND_Closed_*.csv")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output CSV (default: drive/IND_Indicator_PnL_<run_ts>.csv)",
    )
    args = p.parse_args()
    closed = args.closed.resolve()
    if not closed.is_file():
        raise SystemExit(f"Not found: {closed}")

    rows, trades = build_indicator_pnl_report(closed)
    if args.output is not None:
        out = args.output.resolve()
    else:
        stem = closed.stem.replace("IND_Closed_", "")
        drive = closed.parent
        out = drive / f"IND_Indicator_PnL_{stem}.csv"

    write_report_csv(rows, out, source=closed.name, trades=trades)

    latest = out.parent / "IND_Indicator_PnL_Latest.csv"
    if latest.resolve() != out.resolve():
        latest.write_text(out.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Wrote {latest}")


if __name__ == "__main__":
    main()
