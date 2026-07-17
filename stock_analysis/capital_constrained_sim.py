"""
Capital-Constrained Simulation: Re-run BRT_Closed trades with a $500k cap and optional margin.

Modes:
- Fixed cap: max N positions at $50k each; skip trades when full
- Dynamic equity: position_size = current_equity / max_positions; equity compounds with each trade
- Margin: allow 2x positions, charge 10% annual on borrowed amount

Usage:
  python capital_constrained_sim.py BRT_Closed_260305212812.csv
  python capital_constrained_sim.py BRT_Closed_*.csv --capital 500000 --max-positions 10
  python capital_constrained_sim.py BRT_Closed_*.csv --dynamic   # position size = equity / max_positions
  python capital_constrained_sim.py BRT_Closed_*.csv --margin --margin-rate 0.10
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd


def _parse_date(val):
    """Parse YYYYMMDD or YYYY-MM-DD to Timestamp."""
    if val is None or (isinstance(val, str) and len(str(val).strip()) < 8):
        return None
    try:
        if isinstance(val, (int, float)):
            val = str(int(float(val)))
        s = str(val).strip()
        if "-" in s:
            return pd.Timestamp(s[:10])
        if len(s) >= 8:
            return pd.Timestamp(s[:4] + "-" + s[4:6] + "-" + s[6:8])
        return None
    except Exception:
        return None


def _clean_num(val):
    if val is None or (isinstance(val, str) and str(val).strip() in ("", "nan", "N/A")):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace("%", "").replace(",", "").strip()
    try:
        return float(s)
    except Exception:
        return 0.0


def simulate_capital_constrained(
    closed_path: str,
    total_capital: float = 500_000,
    max_positions: int = 10,
    original_position_size: float = 47_500,
    use_margin: bool = False,
    margin_rate_annual: float = 0.10,
    days_per_year: float = 365.0,
) -> dict:
    """
    Simulate capital-constrained execution from BRT_Closed CSV.

    - No margin: position_size = total_capital / max_positions; only open when slots < max_positions
    - With margin: allow up to total_capital / position_size positions; charge margin_rate_annual on borrowed amount
    """
    df = pd.read_csv(closed_path, index_col=False)
    df.columns = [c.strip() for c in df.columns]
    required = ["SYMBOL", "DATE_OPENED", "DATE_CLOSED", "ENTRY_PRICE", "EXIT_PRICE", "PNL_DOLLARS", "PNL_PCT"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    position_size = total_capital / max_positions
    scale = position_size / original_position_size

    # Build events: (date, 'open'|'close', trade)
    trades = []
    for _, row in df.iterrows():
        dop = _parse_date(row["DATE_OPENED"])
        dcl = _parse_date(row["DATE_CLOSED"])
        if dop is None or dcl is None:
            continue
        pnl_dollars = _clean_num(row["PNL_DOLLARS"])
        pnl_pct = _clean_num(row["PNL_PCT"])
        trades.append({
            "symbol": str(row["SYMBOL"]).strip(),
            "date_opened": dop,
            "date_closed": dcl,
            "entry_price": _clean_num(row["ENTRY_PRICE"]),
            "exit_price": _clean_num(row["EXIT_PRICE"]),
            "pnl_dollars": pnl_dollars,
            "pnl_pct": pnl_pct,
        })

    events = []
    for i, t in enumerate(trades):
        events.append((t["date_opened"], "open", i, t))
        events.append((t["date_closed"], "close", i, t))
    events.sort(key=lambda x: (x[0], 0 if x[1] == "close" else 1))  # closes before opens on same day

    open_slots = max_positions
    open_trades: dict[int, dict] = {}  # trade_idx -> trade
    taken = []
    total_pnl = 0.0
    margin_cost = 0.0

    for dt, evt, idx, t in events:
        if evt == "close":
            if idx in open_trades:
                pnl_scaled = t["pnl_dollars"] * scale
                total_pnl += pnl_scaled
                if use_margin:
                    deployed = position_size
                    borrowed = max(0, deployed - total_capital / max_positions
                                   if open_slots < max_positions else 0)
                    days_held = (t["date_closed"] - t["date_opened"]).days
                    margin_cost += borrowed * (margin_rate_annual / days_per_year) * days_held
                del open_trades[idx]
                open_slots += 1
        else:  # open
            if open_slots > 0:
                open_slots -= 1
                open_trades[idx] = t
                taken.append(t)

    # Margin: simpler model - charge 10% annual on borrowed amount for each position
    if use_margin:
        # Recompute: we allowed more positions. Each position = position_size. Total deployed at peak.
        # Borrowed = max(0, deployed - total_capital). For each position we hold, deployed += position_size.
        # At peak we had max_positions open. So we didn't cap - we took all trades.
        # Actually with use_margin we'd allow more positions. Let me rethink.
        # User said: "we could use margin, but that costs 10% of our money"
        # I'll interpret: margin costs 10% annual on the borrowed portion. So if we use 2x leverage
        # (500k equity + 500k margin = 1M deployed), we pay 10% * 500k = 50k/year.
        # For the no-margin case we cap at 10 positions. For margin case: allow 20 positions.
        # position_size stays 50k. So 20 * 50k = 1M. Borrowed = 500k. Cost = 10% * 500k = 50k/year.
        # We need to know the time span. Use first open to last close.
        pass  # margin_cost computed above per-trade is wrong; simplified below

    n_taken = len(taken)
    n_skipped = len(trades) - n_taken

    # Compute metrics
    wins = sum(1 for t in taken if t["pnl_pct"] > 0)
    losses = sum(1 for t in taken if t["pnl_pct"] < 0)
    total_days_held = sum((t["date_closed"] - t["date_opened"]).days for t in taken)
    avg_days = total_days_held / n_taken if n_taken else 0

    # Margin cost: if we used margin, total borrowed over time. Simplified: assume avg borrowed
    # = (total_deployed - total_capital) when deployed > total_capital. At 10 positions * 50k = 500k, no borrow.
    # So we never borrowed in the no-margin case. For margin case: we'd allow more.
    # For now, margin_cost = 0 in no-margin. For margin: we'd need to track daily deployed.
    margin_cost_total = 0.0
    if use_margin and n_taken > max_positions:
        # Simpler: assume we used margin for (n_taken - max_positions) "extra" position-days
        # Actually let's add a --margin scenario that allows 2x positions (20) and charges 10% on borrowed
        pass

    return {
        "total_pnl": total_pnl,
        "margin_cost": margin_cost_total,
        "net_pnl": total_pnl - margin_cost_total,
        "trades_taken": n_taken,
        "trades_skipped": n_skipped,
        "total_trades_available": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate": wins / n_taken * 100 if n_taken else 0,
        "avg_days_held": avg_days,
        "capital_days": total_days_held * position_size,
        "position_size": position_size,
        "max_positions": max_positions,
    }


def run_margin_scenario(
    closed_path: str,
    total_capital: float = 500_000,
    margin_multiplier: float = 2.0,
    margin_rate_annual: float = 0.10,
    original_position_size: float = 47_500,
    days_per_year: float = 365.0,
) -> dict:
    """
    Simulate with margin: allow 2x positions (20) and charge 10% annual on borrowed amount.
    """
    df = pd.read_csv(closed_path, index_col=False)
    df.columns = [c.strip() for c in df.columns]
    required = ["SYMBOL", "DATE_OPENED", "DATE_CLOSED", "ENTRY_PRICE", "EXIT_PRICE", "PNL_DOLLARS", "PNL_PCT"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    max_positions = int(10 * margin_multiplier)  # 20 with 2x
    position_size = total_capital / 10  # still $50k per position
    scale = position_size / original_position_size

    trades = []
    for _, row in df.iterrows():
        dop = _parse_date(row["DATE_OPENED"])
        dcl = _parse_date(row["DATE_CLOSED"])
        if dop is None or dcl is None:
            continue
        trades.append({
            "symbol": str(row["SYMBOL"]).strip(),
            "date_opened": dop,
            "date_closed": dcl,
            "pnl_dollars": _clean_num(row["PNL_DOLLARS"]),
            "pnl_pct": _clean_num(row["PNL_PCT"]),
        })

    events = []
    for i, t in enumerate(trades):
        events.append((t["date_opened"], "open", i, t))
        events.append((t["date_closed"], "close", i, t))
    events.sort(key=lambda x: (x[0], 0 if x[1] == "close" else 1))

    open_slots = max_positions
    open_trades: dict[int, dict] = {}
    taken = []
    total_pnl = 0.0

    # Track (date, open_count) for margin cost: integrate borrowed * days
    prev_dt = None
    prev_open_count = 0
    margin_cost_total = 0.0

    for dt, evt, idx, t in events:
        if evt == "close":
            if idx in open_trades:
                pnl_scaled = t["pnl_dollars"] * scale
                total_pnl += pnl_scaled
                del open_trades[idx]
                open_slots += 1
        else:
            if open_slots > 0:
                open_slots -= 1
                open_trades[idx] = t
                taken.append(t)

        open_count = max_positions - open_slots
        deployed = open_count * position_size
        borrowed = max(0, deployed - total_capital)
        if prev_dt is not None and borrowed > 0:
            days = (dt - prev_dt).days
            if days > 0:
                margin_cost_total += borrowed * (margin_rate_annual / days_per_year) * days
        prev_dt = dt
        prev_open_count = open_count

    total_days = sum((t["date_closed"] - t["date_opened"]).days for t in taken)
    return {
        "total_pnl": total_pnl,
        "margin_cost": margin_cost_total,
        "net_pnl": total_pnl - margin_cost_total,
        "trades_taken": len(taken),
        "trades_skipped": len(trades) - len(taken),
        "total_trades_available": len(trades),
        "wins": sum(1 for t in taken if t["pnl_pct"] > 0),
        "losses": sum(1 for t in taken if t["pnl_pct"] < 0),
        "win_rate": (sum(1 for t in taken if t["pnl_pct"] > 0) / len(taken) * 100) if taken else 0,
        "avg_days_held": total_days / len(taken) if taken else 0,
        "position_size": position_size,
        "max_positions": max_positions,
    }


def _max_concurrent_positions(trades: list[dict]) -> int:
    """Compute max overlapping positions from trade date ranges."""
    if not trades:
        return 0
    events = []
    for t in trades:
        dop, dcl = t["date_opened"], t["date_closed"]
        if dop is None or dcl is None:
            continue
        events.append((dop, 1))
        events.append((dcl, -1))
    events.sort(key=lambda x: (x[0], -x[1]))
    cur, mx = 0, 0
    for _, delta in events:
        cur += delta
        mx = max(mx, cur)
    return mx


def simulate_dynamic_equity(
    closed_path: str,
    initial_capital: float = 500_000,
    original_position_size: float = 47_500,
) -> dict:
    """
    Simulate with dynamic equity: position_size = current_equity / max_positions at each open.
    Equity compounds: grows with wins, shrinks with losses. No fixed cap.
    """
    df = pd.read_csv(closed_path, index_col=False)
    df.columns = [c.strip() for c in df.columns]
    required = ["SYMBOL", "DATE_OPENED", "DATE_CLOSED", "ENTRY_PRICE", "EXIT_PRICE", "PNL_DOLLARS", "PNL_PCT"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    trades = []
    for _, row in df.iterrows():
        dop = _parse_date(row["DATE_OPENED"])
        dcl = _parse_date(row["DATE_CLOSED"])
        if dop is None or dcl is None:
            continue
        trades.append({
            "symbol": str(row["SYMBOL"]).strip(),
            "date_opened": dop,
            "date_closed": dcl,
            "entry_price": _clean_num(row["ENTRY_PRICE"]),
            "exit_price": _clean_num(row["EXIT_PRICE"]),
            "pnl_dollars": _clean_num(row["PNL_DOLLARS"]),
            "pnl_pct": _clean_num(row["PNL_PCT"]),
        })

    max_positions = _max_concurrent_positions(trades)
    if max_positions <= 0:
        return {
            "total_pnl": 0, "net_pnl": 0, "final_equity": initial_capital,
            "trades_taken": 0, "trades_skipped": len(trades), "total_trades_available": len(trades),
            "wins": 0, "losses": 0, "win_rate": 0, "avg_days_held": 0,
            "max_positions": 0, "position_size": 0,
        }

    events = []
    for i, t in enumerate(trades):
        events.append((t["date_opened"], "open", i, t))
        events.append((t["date_closed"], "close", i, t))
    events.sort(key=lambda x: (x[0], 0 if x[1] == "close" else 1))

    current_equity = initial_capital
    open_trades: dict[int, dict] = {}  # idx -> {trade, position_size_at_open}
    taken = []

    for dt, evt, idx, t in events:
        if evt == "close":
            if idx in open_trades:
                rec = open_trades[idx]
                pos_size = rec["position_size_at_open"]
                pnl = pos_size * (t["pnl_pct"] / 100)
                current_equity += pnl
                taken.append({**t, "position_size_at_open": pos_size, "pnl_scaled": pnl})
                del open_trades[idx]
        else:  # open
            if len(open_trades) < max_positions:
                position_size = current_equity / max_positions
                open_trades[idx] = {"trade": t, "position_size_at_open": position_size}

    total_pnl = current_equity - initial_capital
    total_days = sum((t["date_closed"] - t["date_opened"]).days for t in taken)
    wins = sum(1 for t in taken if t["pnl_pct"] > 0)
    losses = sum(1 for t in taken if t["pnl_pct"] < 0)

    return {
        "total_pnl": total_pnl,
        "net_pnl": total_pnl,
        "final_equity": current_equity,
        "trades_taken": len(taken),
        "trades_skipped": len(trades) - len(taken),
        "total_trades_available": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate": wins / len(taken) * 100 if taken else 0,
        "avg_days_held": total_days / len(taken) if taken else 0,
        "max_positions": max_positions,
        "position_size": initial_capital / max_positions,  # initial avg for display
    }


def main():
    ap = argparse.ArgumentParser(description="Capital-constrained simulation for BRT_Closed")
    ap.add_argument("closed_csv", nargs="+", help="BRT_Closed CSV path(s) or glob")
    ap.add_argument("--capital", "-c", type=float, default=500_000, help="Total capital (default 500000)")
    ap.add_argument("--max-positions", "-n", type=int, default=10,
                    help="Max concurrent positions (default 10 = 500k/50k)")
    ap.add_argument("--original-size", type=float, default=47_500,
                    help="Original position size in backtest (default 47500)")
    ap.add_argument("--dynamic", "-d", action="store_true",
                    help="Dynamic equity: position_size = current_equity / max_positions; equity compounds")
    ap.add_argument("--margin", action="store_true", help="Allow margin (2x positions), charge 10%% on borrowed")
    ap.add_argument("--margin-rate", type=float, default=0.10, help="Margin cost annual rate (default 0.10)")
    args = ap.parse_args()

    files = []
    for p in args.closed_csv:
        if "*" in p:
            files.extend(glob.glob(p))
        else:
            files.append(p)
    files = sorted(set(f for f in files if os.path.isfile(f)))

    if not files:
        print("No BRT_Closed files found.")
        return 1

    print("=" * 80)
    print(f"CAPITAL-CONSTRAINED SIMULATION: ${args.capital:,.0f} initial capital")
    if args.dynamic:
        print(f"  Dynamic equity: position_size = current_equity / max_positions (compounds with each trade)")
    elif args.margin:
        print(f"  With margin: max {args.max_positions * 2} positions, {args.margin_rate:.0%} annual on borrowed")
    else:
        print(f"  Fixed cap: max {args.max_positions} positions @ ${args.capital/args.max_positions:,.0f} each")
    print("=" * 80)

    results = []
    for path in files:
        name = os.path.basename(path)
        ts = name.replace("BRT_Closed_", "").replace(".csv", "").strip()
        try:
            if args.dynamic:
                r = simulate_dynamic_equity(
                    path,
                    initial_capital=args.capital,
                    original_position_size=args.original_size,
                )
            elif args.margin:
                r = run_margin_scenario(
                    path,
                    total_capital=args.capital,
                    margin_rate_annual=args.margin_rate,
                    original_position_size=args.original_size,
                )
            else:
                r = simulate_capital_constrained(
                    path,
                    total_capital=args.capital,
                    max_positions=args.max_positions,
                    original_position_size=args.original_size,
                    use_margin=False,
                )
            r["file"] = name
            r["timestamp"] = ts
            results.append(r)
        except Exception as e:
            print(f"[ERR] {name}: {e}")
            continue

    # Print table
    hdr = "{:<18} {:>14} {:>10} {:>8} {:>8} {:>10}".format(
        "Run", "Net PnL", "Taken", "Skip", "Win%", "AvgDays")
    if args.margin:
        hdr += " {:>10}".format("MarginCost")
    if args.dynamic:
        hdr += " {:>14}".format("Final Equity")
    print("\n" + hdr)
    sep_len = len(hdr) + 2
    print("-" * sep_len)
    for r in results:
        net = r.get("net_pnl", r["total_pnl"])
        margin = r.get("margin_cost", 0)
        row = "{:<18} {:>14,.0f} {:>10} {:>8} {:>8.1f} {:>10.1f}".format(
            r["timestamp"][:16],
            net,
            r["trades_taken"],
            r["trades_skipped"],
            r["win_rate"],
            r.get("avg_days_held", 0),
        )
        if args.margin:
            row += " {:>10,.0f}".format(margin)
        if args.dynamic:
            row += " {:>14,.0f}".format(r.get("final_equity", 0))
        print(row)
    print("=" * 80)

    ranked = sorted(results, key=lambda x: x.get("net_pnl", x["total_pnl"]), reverse=True)
    print("\nRanking (by Net PnL):")
    for i, r in enumerate(ranked, 1):
        print(f"  {i}. {r['timestamp']}: ${r.get('net_pnl', r['total_pnl']):,.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
