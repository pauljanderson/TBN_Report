#!/usr/bin/env python3
"""Compare BRT_Closed output against a manual trade list. Outputs a grouped diff report.
Uses fuzzy matching: treats trades as same if symbol + exit_date match and entry dates within 2 days."""
import csv
import re
import sys
from pathlib import Path
from datetime import datetime

ENTRY_DATE_TOLERANCE_DAYS = 2  # Allow entry dates to differ by up to this many days (covers next-open convention)

def parse_manual_date(s: str) -> str:
    """Parse M/D/YYYY to YYYYMMDD."""
    try:
        parts = s.strip().split("/")
        if len(parts) == 3:
            m, d, y = int(parts[0]), int(parts[1]), int(parts[2])
            return f"{y:04d}{m:02d}{d:02d}"
    except (ValueError, IndexError):
        pass
    return ""

def parse_manual_line(line: str) -> dict | None:
    """Parse a manual list row. Returns dict or None if header/invalid."""
    # Tab or multiple spaces; columns: Stock, Entry Date, Entry Price, Exit Date, Exit Price, Profit %, Days, Result, Profit $
    parts = re.split(r'\t+|\s{2,}', line.strip())
    if len(parts) < 7:
        return None
    if parts[0].lower() == "stock" or parts[0] == "Stock":
        return None
    try:
        entry_d = parse_manual_date(parts[1])
        if not entry_d:
            return None
        entry_p = float(parts[2].replace("$", "").replace(",", ""))
        exit_d = parse_manual_date(parts[3])
        exit_p = float(parts[4].replace("$", "").replace(",", ""))
        pct = parts[5].replace("%", "").strip()
        days = int(parts[6])
        result = parts[7] if len(parts) > 7 else ""
        profit_d = parts[8] if len(parts) > 8 else ""
        return {
            "symbol": parts[0].upper(),
            "entry_date": entry_d,
            "entry_price": entry_p,
            "exit_date": exit_d,
            "exit_price": exit_p,
            "profit_pct": pct,
            "days": days,
            "result": result,
            "profit_dollars": profit_d,
        }
    except (ValueError, IndexError):
        return None

def load_manual(text: str) -> list[dict]:
    manual = []
    for line in text.strip().split("\n"):
        row = parse_manual_line(line)
        if row:
            manual.append(row)
    return manual

def load_brt(path: str) -> list[dict]:
    rows = []
    with open(path, newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append({
                "symbol": row.get("SYMBOL", "").upper(),
                "entry_date": row.get("DATE_OPENED", "").replace("-", ""),
                "entry_price": float(row.get("ENTRY_PRICE", 0)),
                "exit_date": row.get("DATE_CLOSED", "").replace("-", ""),
                "exit_price": float(row.get("EXIT_PRICE", 0)),
                "profit_pct": row.get("PNL_PCT", "").replace("%", "").strip(),
                "days": int(row.get("DAYS_HELD", 0)),
                "exit_type": row.get("EXIT_TYPE", ""),
                "profit_dollars": row.get("PNL_DOLLARS", ""),
            })
    return rows

def key(symbol: str, entry_date: str) -> str:
    return f"{symbol}|{entry_date}"


def parse_yyyymmdd(s: str) -> datetime | None:
    """Parse YYYYMMDD to datetime."""
    if len(s) != 8:
        return None
    try:
        return datetime(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def entry_dates_within_tolerance(e1: str, e2: str) -> bool:
    """True if two YYYYMMDD entry dates are within ENTRY_DATE_TOLERANCE_DAYS."""
    d1, d2 = parse_yyyymmdd(e1), parse_yyyymmdd(e2)
    if d1 is None or d2 is None:
        return False
    return abs((d1 - d2).days) <= ENTRY_DATE_TOLERANCE_DAYS


def fuzzy_match_pairs(brt: list[dict], manual: list[dict]) -> list[tuple[dict, dict, bool]]:
    """Find (brt_trade, manual_trade, entry_date_differs) pairs. Each trade matched at most once."""
    used_brt = set()
    used_manual = set()
    pairs: list[tuple[dict, dict, bool]] = []
    # Sort by symbol, exit_date for deterministic matching
    for b in sorted(brt, key=lambda r: (r["symbol"], r["exit_date"], r["entry_date"])):
        if id(b) in used_brt:
            continue
        best_m = None
        best_entry_diff = 999
        for m in manual:
            if id(m) in used_manual:
                continue
            if b["symbol"] != m["symbol"] or b["exit_date"] != m["exit_date"]:
                continue
            if not entry_dates_within_tolerance(b["entry_date"], m["entry_date"]):
                continue
            e1, e2 = parse_yyyymmdd(b["entry_date"]), parse_yyyymmdd(m["entry_date"])
            diff = abs((e1 - e2).days) if e1 and e2 else 999
            if diff < best_entry_diff:
                best_entry_diff = diff
                best_m = m
        if best_m is not None:
            used_brt.add(id(b))
            used_manual.add(id(best_m))
            entry_differs = b["entry_date"] != best_m["entry_date"]
            pairs.append((b, best_m, entry_differs))
    return pairs


def compare(brt_path: str, manual_text: str, out_path: str) -> None:
    brt = load_brt(brt_path)
    manual = load_manual(manual_text)
    pairs = fuzzy_match_pairs(brt, manual)
    matched_brt = {id(b) for b, m, _ in pairs}
    matched_manual = {id(m) for b, m, _ in pairs}
    only_brt = [r for r in brt if id(r) not in matched_brt]
    only_manual = [r for r in manual if id(r) not in matched_manual]
    manual_symbols = {r["symbol"] for r in manual}
    only_brt_relevant = [r for r in only_brt if r["symbol"] in manual_symbols]

    exact_match = []
    fuzzy_match = []
    material_diffs = []  # Price/exit/days differences (entry-date-only doesn't count as material)
    for b, m, entry_differs in pairs:
        diff_parts = []
        if abs(float(b["entry_price"]) - float(m["entry_price"])) > 0.02:
            diff_parts.append(f"entry_price: BRT={b['entry_price']} manual={m['entry_price']}")
        if abs(float(b["exit_price"]) - float(m["exit_price"])) > 0.02:
            diff_parts.append(f"exit_price: BRT={b['exit_price']} manual={m['exit_price']}")
        if b["exit_date"] != m["exit_date"]:
            diff_parts.append(f"exit_date: BRT={b['exit_date']} manual={m['exit_date']}")
        if abs(int(b["days"]) - int(m["days"])) > 1:
            diff_parts.append(f"days: BRT={b['days']} manual={m['days']}")
        b_pct = float(b["profit_pct"]) if b["profit_pct"] else 0
        m_pct = float(m["profit_pct"]) if m["profit_pct"] else 0
        if abs(b_pct - m_pct) > 0.5:
            diff_parts.append(f"profit_pct: BRT={b['profit_pct']}% manual={m['profit_pct']}%")
        if entry_differs:
            diff_parts.append(f"entry_date: BRT={b['entry_date']} manual={m['entry_date']} (next-open convention)")
        if diff_parts:
            material_diffs.append((b, m, diff_parts))
        if entry_differs:
            fuzzy_match.append((b, m))
        else:
            exact_match.append((b, m))

    # Material = price/exit/days differ; entry-date-only is expected (next-open convention)
    material_diffs_list = [(b, m, p) for b, m, p in material_diffs if any("entry_date" not in x for x in p)]
    n_match_ok = len(pairs) - len(material_diffs_list)
    lines = [
        "# BRT vs Manual Trade Comparison (Fuzzy Match)",
        "",
        f"**BRT file:** {brt_path}",
        f"**Manual list:** (provided trades)",
        f"*Fuzzy matching: same symbol + exit_date, entry dates within {ENTRY_DATE_TOLERANCE_DAYS} days*",
        "",
        "---",
        "",
        "## Summary",
        "",
        "| Group | Count |",
        "|-------|-------|",
        f"| Matched (fuzzy or exact) | {len(pairs)} |",
        f"| - Exact match (same entry date) | {len(exact_match)} |",
        f"| - Fuzzy match (entry date off 1-2 days) | {len(fuzzy_match)} |",
        f"| - Matched but with price/other differences | {len(material_diffs_list)} |",
        f"| - Matched, no material difference | {n_match_ok} |",
        f"| BRT only (symbols in manual list) | {len(only_brt_relevant)} |",
        f"| Manual only | {len(only_manual)} |",
        "",
        "---",
        "",
        "## 1. In BRT only (symbols that appear in manual list)",
        "",
        "Trades in BRT with no fuzzy match in manual:",
        "",
    ]
    for r in sorted(only_brt_relevant, key=lambda x: (x["symbol"], x["entry_date"])):
        lines.append(f"- **{r['symbol']}** Entry {r['entry_date']} @ {r['entry_price']} -> Exit {r['exit_date']} @ {r['exit_price']} ({r['profit_pct']}%, {r['days']}d)")
    if not only_brt_relevant:
        lines.append("*None*")
    lines.extend(["", "---", "", "## 2. In Manual only", "", "Trades in manual with no fuzzy match in BRT:", ""])
    for r in sorted(only_manual, key=lambda x: (x["symbol"], x["entry_date"])):
        lines.append(f"- **{r['symbol']}** Entry {r['entry_date']} @ {r['entry_price']} -> Exit {r['exit_date']} @ {r['exit_price']} ({r['profit_pct']}%, {r['days']}d)")
    if not only_manual:
        lines.append("*None*")
    lines.extend(["", "---", "", "## 3. Matched but with differences", "", "Matched trades with price/exit/days differences:", ""])
    for b, m, parts in material_diffs_list:
        lines.append(f"- **{b['symbol']}** BRT entry {b['entry_date']} / manual entry {m['entry_date']}")
        for p in parts:
            lines.append(f"  - {p}")
    if not material_diffs_list:
        lines.append("*None (all matched trades agree on prices)*")
    lines.extend(["", "---", "", "## 4. Matched, no material difference", "", f"*{n_match_ok} trades* (entry date may differ by 1-2 days; prices/exit align)", ""])
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Wrote {out_path}")

if __name__ == "__main__":
    # Usage: python compare_brt_manual.py BRT_Closed_260301140936.csv manual_trades.txt
    # manual_trades.txt contains the pasted manual list
    if len(sys.argv) < 3:
        print("Usage: compare_brt_manual.py <brt_closed.csv> <manual_trades.txt> [out.md]")
        sys.exit(1)
    brt_path = sys.argv[1]
    with open(sys.argv[2]) as f:
        manual_text = f.read()
    out_path = sys.argv[3] if len(sys.argv) > 3 else "BRT_vs_Manual_Comparison.md"
    compare(brt_path, manual_text, out_path)
