#!/usr/bin/env python3
"""Experiment-only: long when SPY_COMPARE 1Y/2Y/3Y > 0 AND all IND_TC_*_OUTLOOK = Strong.

Non-production research harness. Production DailyRun path: stock_analysis/rocket_rs.py via run_rs.bat
(outputs RS_Closed|Open|Scanner|Summary_* to drive/).

MarkTen first. Entry = next open after signal close (BRT scan convention).
Exits: target_pct=1.2 (20%) OR stop_pct=0.92 (8%). No zones / trailing.

Sizing: fixed notional = $1,000,000 / max_positions (default 10 → $100k), matching BRT_Report.
SPY_COMPARE_* = excess total return vs SPY in percentage points over 252/504/756 bars
(same as rocket_brt._rs_excess_pct_points).
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
SA = REPO / "stock_analysis"
for p in (REPO, SA):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from brt_entry_indicators import (  # noqa: E402
    _ensure_gate_arrays,
    _tc_outlook_label,
    build_entry_indicator_precompute,
    resolve_indicator_cache_dir,
)
from rocket_brt import (  # noqa: E402
    _RS_SPY_LAG_3Y,
    _align_stock_spy_close_for_rs,
    _rs_excess_pct_points,
    _rs_pass_all_horizons_vs_spy,
    load_csv,
)

MARKTEN = ["AAPL", "AMD", "AMZN", "AU", "META", "MSFT", "NVDA", "NFLX", "GOOGL", "TSLA"]
EXPANDED14 = MARKTEN + ["TSM", "AVGO", "MU", "LLY"]
DEFAULT_OUT = REPO / "drive" / "davey_experiments" / "spy_tc_strong_system"
TARGET_PCT = 1.2
STOP_PCT = 0.92
INITIAL_CAPITAL = 1_000_000.0
MAX_POSITIONS = 10


@dataclass
class Trade:
    SYMBOL: str
    SIDE: str
    DATE_SIGNAL: str
    DATE_OPENED: str
    ENTRY_PRICE: float
    STOP_PRICE: float
    TARGET_PRICE: float
    DATE_CLOSED: str
    EXIT_PRICE: float
    EXIT_TYPE: str
    DAYS_HELD: int
    PNL_PCT: float
    PNL_DOLLARS: float
    SPY_COMPARE_1Y: float
    SPY_COMPARE_2Y: float
    SPY_COMPARE_3Y: float
    IND_TC_SHORT_OUTLOOK: str
    IND_TC_INT_OUTLOOK: str
    IND_TC_LONG_OUTLOOK: str


def _iso(d: Any) -> str:
    if hasattr(d, "strftime"):
        return d.strftime("%Y-%m-%d")
    s = str(d)[:10]
    return s


def _exit_long(
    *,
    entry: float,
    stop: float,
    target: float,
    op: float,
    hi: float,
    lo: float,
) -> tuple[Optional[str], Optional[float]]:
    """Same-bar priority: gap through stop → stop at open; gap through target → target at open;
    else stop if low<=stop; else target if high>=target. (stop before target if both touch)."""
    if op <= stop:
        return "STOP", float(op)
    if op >= target:
        return "TARGET", float(op)
    if lo <= stop:
        return "STOP", float(stop)
    if hi >= target:
        return "TARGET", float(target)
    return None, None


def backtest_symbol(
    sym: str,
    df: pd.DataFrame,
    spy_df: pd.DataFrame,
    *,
    notional: float,
    data_dir: Path,
    target_pct: float = TARGET_PCT,
    stop_pct: float = STOP_PCT,
    liquidate_at_end: bool = True,
) -> list[Trade]:
    aligned = _align_stock_spy_close_for_rs(df, spy_df)
    if aligned is None:
        return []
    st, sp = aligned
    n = len(df)
    if n < _RS_SPY_LAG_3Y + 2:
        return []

    pre = build_entry_indicator_precompute(
        df,
        symbol=sym,
        cache_dir=resolve_indicator_cache_dir(None, data_dir=data_dir),
        use_cache=True,
    )
    if pre is None:
        print(f"[WARN] {sym}: indicator precompute unavailable", flush=True)
        return []
    pre = _ensure_gate_arrays(pre)
    if pre.tc_short_sum is None or pre.tc_int_sum is None or pre.tc_long_sum is None:
        print(f"[WARN] {sym}: TC outlook arrays missing", flush=True)
        return []
    tc_ok = (
        (pre.tc_short_sum > 0)
        & (pre.tc_int_sum > 0)
        & (pre.tc_long_sum > 0)
    )

    open_arr = df["Open"].to_numpy(dtype=np.float64)
    high_arr = df["High"].to_numpy(dtype=np.float64)
    low_arr = df["Low"].to_numpy(dtype=np.float64)
    dates = df.index

    trades: list[Trade] = []
    search_from = _RS_SPY_LAG_3Y
    while search_from <= n - 2:
        signal_t = -1
        tc_meta: dict[str, str] = {}
        sc1 = sc2 = sc3 = None
        for t in range(search_from, n - 1):
            if not bool(tc_ok[t]):
                continue
            if not _rs_pass_all_horizons_vs_spy(st, sp, t):
                continue
            e1, e2, e3 = _rs_excess_pct_points(st, sp, t)
            if e1 is None or e2 is None or e3 is None:
                continue
            if not (e1 > 0 and e2 > 0 and e3 > 0):
                continue
            signal_t = t
            sc1, sc2, sc3 = float(e1), float(e2), float(e3)
            tc_meta = {
                "IND_TC_SHORT_OUTLOOK": _tc_outlook_label(int(pre.tc_short_sum[t])),
                "IND_TC_INT_OUTLOOK": _tc_outlook_label(int(pre.tc_int_sum[t])),
                "IND_TC_LONG_OUTLOOK": _tc_outlook_label(int(pre.tc_long_sum[t])),
            }
            break
        if signal_t < 0:
            break

        entry_bar = signal_t + 1
        entry = float(open_arr[entry_bar])
        if not np.isfinite(entry) or entry <= 0:
            search_from = signal_t + 1
            continue
        stop = entry * stop_pct
        target = entry * target_pct
        exit_type: Optional[str] = None
        exit_px: Optional[float] = None
        exit_bar = -1
        for i in range(entry_bar + 1, n):
            et, ep = _exit_long(
                entry=entry,
                stop=stop,
                target=target,
                op=float(open_arr[i]),
                hi=float(high_arr[i]),
                lo=float(low_arr[i]),
            )
            if et is not None:
                exit_type, exit_px, exit_bar = et, ep, i
                break
        if exit_type is None:
            if not liquidate_at_end:
                break
            exit_bar = n - 1
            exit_type = "EOD"
            exit_px = float(df["Close"].iloc[exit_bar])

        pnl_pct = (float(exit_px) / entry - 1.0) * 100.0
        days = max(int((dates[exit_bar] - dates[entry_bar]).days), 0)
        trades.append(
            Trade(
                SYMBOL=sym,
                SIDE="LONG",
                DATE_SIGNAL=_iso(dates[signal_t]),
                DATE_OPENED=_iso(dates[entry_bar]),
                ENTRY_PRICE=round(entry, 4),
                STOP_PRICE=round(stop, 4),
                TARGET_PRICE=round(target, 4),
                DATE_CLOSED=_iso(dates[exit_bar]),
                EXIT_PRICE=round(float(exit_px), 4),
                EXIT_TYPE=exit_type,
                DAYS_HELD=days,
                PNL_PCT=round(pnl_pct, 4),
                PNL_DOLLARS=round(notional * pnl_pct / 100.0, 2),
                SPY_COMPARE_1Y=round(float(sc1), 4),
                SPY_COMPARE_2Y=round(float(sc2), 4),
                SPY_COMPARE_3Y=round(float(sc3), 4),
                IND_TC_SHORT_OUTLOOK=tc_meta.get("IND_TC_SHORT_OUTLOOK", ""),
                IND_TC_INT_OUTLOOK=tc_meta.get("IND_TC_INT_OUTLOOK", ""),
                IND_TC_LONG_OUTLOOK=tc_meta.get("IND_TC_LONG_OUTLOOK", ""),
            )
        )
        # Resume scan after exit bar (one position at a time per symbol).
        search_from = exit_bar + 1 if exit_bar >= 0 else signal_t + 1

    return trades


def _portfolio_max_dd(trades: list[Trade], *, capital: float, max_pos: int) -> float:
    """Chronological slot sim: skip new entries when max_pos open; MaxDD on equity."""
    if not trades:
        return 0.0
    notional = capital / max(max_pos, 1)
    events: list[tuple[pd.Timestamp, str, Trade]] = []
    for t in trades:
        events.append((pd.Timestamp(t.DATE_OPENED), "open", t))
        events.append((pd.Timestamp(t.DATE_CLOSED), "close", t))
    events.sort(key=lambda x: (x[0], 0 if x[1] == "close" else 1))

    equity = capital
    peak = capital
    max_dd = 0.0
    open_slots = 0
    accepted: set[int] = set()
    trade_ids = {id(t): t for t in trades}

    for ts, kind, t in events:
        tid = id(t)
        if kind == "open":
            if open_slots >= max_pos:
                continue
            open_slots += 1
            accepted.add(tid)
        else:
            if tid not in accepted:
                continue
            open_slots = max(0, open_slots - 1)
            # Scale PnL to current notional convention (fixed slot size).
            pnl = notional * (t.PNL_PCT / 100.0)
            equity += pnl
            peak = max(peak, equity)
            dd = (peak - equity) / peak * 100.0 if peak > 0 else 0.0
            max_dd = max(max_dd, dd)
    return float(max_dd)


def summarize(trades: list[Trade], *, capital: float, max_pos: int) -> dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {
            "Total_Trades": 0,
            "Wins": 0,
            "Win_Rate_Pct": 0.0,
            "Profit_Factor": 0.0,
            "Total_PNL": 0.0,
            "Max_DD_Pct": 0.0,
            "Expectancy": 0.0,
            "Avg_Days_Held": 0.0,
            "Target_Exits": 0,
            "Stop_Exits": 0,
            "EOD_Exits": 0,
        }
    wins = [t for t in trades if t.PNL_DOLLARS > 0]
    losses = [t for t in trades if t.PNL_DOLLARS <= 0]
    gp = sum(t.PNL_DOLLARS for t in wins)
    gl = abs(sum(t.PNL_DOLLARS for t in losses))
    pf = (gp / gl) if gl > 1e-9 else (float("inf") if gp > 0 else 0.0)
    total = sum(t.PNL_DOLLARS for t in trades)
    return {
        "Total_Trades": n,
        "Wins": len(wins),
        "Win_Rate_Pct": round(100.0 * len(wins) / n, 2),
        "Profit_Factor": round(pf, 3) if pf != float("inf") else None,
        "Total_PNL": round(total, 2),
        "Max_DD_Pct": round(_portfolio_max_dd(trades, capital=capital, max_pos=max_pos), 2),
        "Expectancy": round(total / n, 2),
        "Avg_Days_Held": round(sum(t.DAYS_HELD for t in trades) / n, 1),
        "Target_Exits": sum(1 for t in trades if t.EXIT_TYPE == "TARGET"),
        "Stop_Exits": sum(1 for t in trades if t.EXIT_TYPE == "STOP"),
        "EOD_Exits": sum(1 for t in trades if t.EXIT_TYPE == "EOD"),
        "Notional_Per_Slot": round(capital / max(max_pos, 1), 2),
        "Initial_Capital": capital,
        "Max_Positions": max_pos,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--symbols",
        default=",".join(MARKTEN),
        help="Comma-separated symbols (default MarkTen). Prefer --expanded14 for 14-name universe.",
    )
    ap.add_argument(
        "--expanded14",
        action="store_true",
        help="Use MarkTen + TSM,AVGO,MU,LLY (overrides --symbols).",
    )
    ap.add_argument(
        "--symbols-file",
        default="",
        help="Path to newline/comma-separated symbols file (overrides --symbols / --expanded14).",
    )
    ap.add_argument(
        "--data-dir",
        default=str(REPO / "data" / "newdata" / "data"),
    )
    ap.add_argument("--out", "--out-dir", dest="out", default=str(DEFAULT_OUT))
    ap.add_argument("--capital", type=float, default=INITIAL_CAPITAL)
    ap.add_argument("--max-positions", type=int, default=MAX_POSITIONS)
    ap.add_argument(
        "--target",
        "--target-pct",
        dest="target_pct",
        type=float,
        default=TARGET_PCT,
        help="Exit target as multiple of entry (e.g. 1.2)",
    )
    ap.add_argument(
        "--stop",
        "--stop-pct",
        dest="stop_pct",
        type=float,
        default=STOP_PCT,
        help="Exit stop as multiple of entry (e.g. 0.92)",
    )
    ap.add_argument(
        "--tag",
        default="",
        help="Optional arm tag inserted into output filenames (e.g. t120_s092).",
    )
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    if str(getattr(args, "symbols_file", "") or "").strip():
        sf = Path(str(args.symbols_file).strip())
        raw = sf.read_text(encoding="utf-8")
        parts: list[str] = []
        for line in raw.splitlines():
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            parts.extend(line.replace(",", " ").split())
        symbols = [s.strip().upper() for s in parts if s.strip()]
    elif args.expanded14:
        symbols = list(EXPANDED14)
    else:
        symbols = [s.strip().upper() for s in str(args.symbols).split(",") if s.strip()]
    max_pos = int(args.max_positions)
    notional = float(args.capital) / max(max_pos, 1)
    target_pct = float(args.target_pct)
    stop_pct = float(args.stop_pct)

    spy_path = data_dir / "SPY.csv"
    if not spy_path.is_file():
        raise SystemExit(f"Missing SPY.csv at {spy_path}")
    spy_df = load_csv(str(spy_path))

    all_trades: list[Trade] = []
    per_sym: dict[str, int] = {}
    t0 = datetime.now()
    for sym in symbols:
        path = data_dir / f"{sym}.csv"
        if not path.is_file():
            print(f"[SKIP] {sym}: no CSV", flush=True)
            continue
        print(f"[RUN] {sym} target={target_pct} stop={stop_pct} ...", flush=True)
        df = load_csv(str(path))
        trades = backtest_symbol(
            sym,
            df,
            spy_df,
            notional=notional,
            data_dir=data_dir,
            target_pct=target_pct,
            stop_pct=stop_pct,
        )
        per_sym[sym] = len(trades)
        all_trades.extend(trades)
        print(f"  -> {len(trades)} trades", flush=True)

    all_trades.sort(key=lambda t: (t.DATE_OPENED, t.SYMBOL))
    stamp = datetime.now().strftime("%y%m%d%H%M%S")
    tag = str(args.tag).strip()
    tag_part = f"_{tag}" if tag else ""
    closed_path = outdir / f"SPY_TC_STRONG_Closed{tag_part}_{stamp}.csv"
    summary_path = outdir / f"SPY_TC_STRONG_Summary{tag_part}_{stamp}.json"
    md_path = outdir / (f"RESULTS{tag_part}.md" if tag else "RESULTS.md")

    closed_df = pd.DataFrame([asdict(t) for t in all_trades])
    closed_df.to_csv(closed_path, index=False)

    metrics = summarize(all_trades, capital=float(args.capital), max_pos=max_pos)
    metrics["symbols"] = symbols
    metrics["trades_per_symbol"] = per_sym
    metrics["target_pct"] = target_pct
    metrics["stop_pct"] = stop_pct
    metrics["tag"] = tag or None
    metrics["elapsed_s"] = round((datetime.now() - t0).total_seconds(), 1)
    metrics["closed_csv"] = str(closed_path)
    metrics["entry_rules"] = (
        "SPY_COMPARE_1Y/2Y/3Y > 0 (excess vs SPY, pct points, 252/504/756 bars) AND "
        "IND_TC_SHORT/INT/LONG_OUTLOOK == Strong; buy next open"
    )
    metrics["caveats"] = [
        "Experiment-only; does not modify production bats.",
        "Entry: signal on close when all 6 gates pass; fill next open (BRT RS/IND scan convention).",
        "One position at a time per symbol; portfolio MaxDD uses max_positions slot cap.",
        "Exit priority same bar: gap stop → gap target → intraday stop → intraday target.",
        "No slippage/commission; no trailing; EOD liquidate if still open.",
        "SPY_COMPARE_* = (stock_return - SPY_return)*100 over trading-day lags (engine definition).",
    ]
    summary_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    sample = closed_df.head(15) if not closed_df.empty else closed_df
    lines = [
        f"# SPY_COMPARE > 0 + TC Strong — target={target_pct} stop={stop_pct}",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Metrics",
        "",
        f"| Metric | Value |",
        f"| --- | --- |",
        f"| Target / Stop | {target_pct} / {stop_pct} |",
        f"| Trades | {metrics['Total_Trades']} |",
        f"| Win rate % | {metrics['Win_Rate_Pct']} |",
        f"| Profit factor | {metrics['Profit_Factor']} |",
        f"| Total PNL ($) | {metrics['Total_PNL']} |",
        f"| Max DD % (slot-capped) | {metrics['Max_DD_Pct']} |",
        f"| Expectancy ($) | {metrics['Expectancy']} |",
        f"| Avg days held | {metrics['Avg_Days_Held']} |",
        f"| Target / Stop / EOD exits | {metrics['Target_Exits']} / {metrics['Stop_Exits']} / {metrics['EOD_Exits']} |",
        f"| Notional / slot | ${metrics['Notional_Per_Slot']:,.0f} (= $1M / {max_pos}) |",
        "",
        "## Trades per symbol",
        "",
        "```",
        json.dumps(per_sym, indent=2),
        "```",
        "",
        "## Sample trades (first 15)",
        "",
    ]
    if sample.empty:
        lines.append("_No trades._")
    else:
        cols = [
            "SYMBOL",
            "DATE_OPENED",
            "DATE_CLOSED",
            "EXIT_TYPE",
            "PNL_PCT",
            "PNL_DOLLARS",
            "SPY_COMPARE_1Y",
            "SPY_COMPARE_2Y",
            "SPY_COMPARE_3Y",
        ]
        header = "| " + " | ".join(cols) + " |"
        sep = "| " + " | ".join("---" for _ in cols) + " |"
        lines.append(header)
        lines.append(sep)
        for _, row in sample[cols].iterrows():
            cells = [str(row[c]) for c in cols]
            lines.append("| " + " | ".join(cells) + " |")
    lines.extend(
        [
            "",
            "## Caveats",
            "",
            *[f"- {c}" for c in metrics["caveats"]],
            "",
            f"- Closed CSV: `{closed_path}`",
            f"- Summary JSON: `{summary_path}`",
            "",
        ]
    )
    md_path.write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps(metrics, indent=2), flush=True)
    print(f"Wrote {closed_path}", flush=True)
    print(f"Wrote {summary_path}", flush=True)
    print(f"Wrote {md_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
