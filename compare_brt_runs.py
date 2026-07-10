#!/usr/bin/env python3
"""Compare two BRT_Closed runs: find identical (symbol, date_opened) trades and summarize PNL delta by exit type."""
import csv
import sys
from pathlib import Path

def load_closed(path: str) -> dict[tuple[str, str], dict]:
    """Load BRT_Closed CSV, keyed by (SYMBOL, DATE_OPENED)."""
    rows = {}
    with open(path, "r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            key = (row["SYMBOL"], row["DATE_OPENED"])
            try:
                row["PNL_DOLLARS"] = float(row["PNL_DOLLARS"].replace(",", ""))
            except (ValueError, KeyError):
                row["PNL_DOLLARS"] = 0.0
            rows[key] = row
    return rows

def main():
    import sys
    repo = Path(__file__).resolve().parent
    drive = repo / "Drive"
    if len(sys.argv) >= 3:
        ts_new, ts_old = sys.argv[1], sys.argv[2]
    else:
        ts_new, ts_old = "260309151223", "260309145446"
    path_new = drive / f"BRT_Closed_{ts_new}.csv"
    path_old = drive / f"BRT_Closed_{ts_old}.csv"
    if not path_new.exists():
        path_new = repo / "drive" / f"BRT_Closed_{ts_new}.csv"
    if not path_old.exists():
        path_old = repo / "drive" / f"BRT_Closed_{ts_old}.csv"
    if not path_new.exists() or not path_old.exists():
        print(f"Files not found: {path_new} / {path_old}")
        sys.exit(1)
    new_rows = load_closed(str(path_new))
    old_rows = load_closed(str(path_old))
    common_keys = set(new_rows) & set(old_rows)
    # Group by EXIT_TYPE in the NEW run (ATR run)
    by_exit: dict[str, list[tuple[float, float, str, str]]] = {}
    for key in common_keys:
        n = new_rows[key]
        o = old_rows[key]
        exit_type = n.get("EXIT_TYPE", "")
        if exit_type not in ("ATR_TARGET", "ATR_Increment", "ATR_STOP"):
            continue
        pnl_new = n["PNL_DOLLARS"]
        pnl_old = o["PNL_DOLLARS"]
        delta = pnl_new - pnl_old
        by_exit.setdefault(exit_type, []).append((pnl_new, pnl_old, delta, f"{key[0]} {key[1]}"))
    print(f"Comparing {ts_new} (ATR) vs {ts_old} (legacy)")
    print(f"Common trades with ATR exit types: {sum(len(v) for v in by_exit.values())}")
    print()
    for exit_type in ("ATR_TARGET", "ATR_Increment", "ATR_STOP"):
        items = by_exit.get(exit_type, [])
        if not items:
            print(f"{exit_type}: 0 trades")
            continue
        total_delta = sum(t[2] for t in items)
        total_new = sum(t[0] for t in items)
        total_old = sum(t[1] for t in items)
        n = len(items)
        avg_delta = total_delta / n
        increased = sum(1 for t in items if t[2] > 0)
        decreased = sum(1 for t in items if t[2] < 0)
        unchanged = sum(1 for t in items if t[2] == 0)
        print(f"--- {exit_type} ({n} trades) ---")
        print(f"  Total PNL delta: ${total_delta:,.2f} (new ${total_new:,.2f} vs old ${total_old:,.2f})")
        print(f"  Avg PNL delta per trade: ${avg_delta:,.2f}")
        print(f"  Increased: {increased}, Decreased: {decreased}, Unchanged: {unchanged}")
        if total_delta > 0:
            print(f"  -> ATR {exit_type} INCREASED value by ${total_delta:,.2f}")
        elif total_delta < 0:
            print(f"  -> ATR {exit_type} DECREASED value by ${abs(total_delta):,.2f}")
        else:
            print(f"  -> No net change")
        print()
    # Overall summary
    all_atr = []
    for items in by_exit.values():
        all_atr.extend(items)
    if all_atr:
        total_delta = sum(t[2] for t in all_atr)
        print("--- OVERALL (all ATR exit types) ---")
        print(f"  Total PNL delta: ${total_delta:,.2f}")
        if total_delta > 0:
            print(f"  -> ATR mode INCREASED total value by ${total_delta:,.2f}")
        elif total_delta < 0:
            print(f"  -> ATR mode DECREASED total value by ${abs(total_delta):,.2f}")

if __name__ == "__main__":
    main()
