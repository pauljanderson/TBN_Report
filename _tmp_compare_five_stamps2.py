import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch\drive")
EXP = Path(r"C:\Users\songg\Downloads\stockresearch\drive\paul_experiments")
stamps = [
    "260731232940",
    "260731231739",
    "260731231707",
    "260801093239",
    "260731125650",
]
MAX_QUICK_STOP_DAYS = 10


def safe_num(x):
    if x is None or x == "" or str(x).strip().upper() == "N/A":
        return 0.0
    s = str(x).replace("%", "").replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def ymd8(raw):
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else digits


def closed_year(row):
    raw = str(row.get("DATE_CLOSED") or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) >= 4:
        return int(digits[:4])
    return 0


def ptqs_stats(rows):
    by = defaultdict(list)
    for r in rows:
        sym = str(r.get("SYMBOL") or "").strip().upper()
        if sym:
            by[sym].append(r)
    n = 0
    pnl = 0.0
    for trades in by.values():
        trades.sort(
            key=lambda r: (
                ymd8(r.get("DATE_OPENED")),
                ymd8(r.get("DATE_CLOSED")),
            )
        )
        for i, r in enumerate(trades):
            if i + 1 >= len(trades):
                break
            et = str(r.get("EXIT_TYPE") or "").strip().upper()
            if "TARGET" not in et:
                continue
            nxt = trades[i + 1]
            nxt_et = str(nxt.get("EXIT_TYPE") or "").strip().upper()
            if "STOP" not in nxt_et:
                continue
            days = int(safe_num(nxt.get("DAYS_HELD", 0)))
            if days > MAX_QUICK_STOP_DAYS:
                continue
            n += 1
            pnl += safe_num(nxt.get("PNL_DOLLARS", 0))
    return n, pnl


def stop22_stats(rows):
    n = 0
    pnl = 0.0
    for r in rows:
        et = str(r.get("EXIT_TYPE") or "").strip().upper()
        if "STOP" not in et:
            continue
        if closed_year(r) not in (2022, 2023):
            continue
        n += 1
        pnl += safe_num(r.get("PNL_DOLLARS", 0))
    return n, pnl


# Find arm folders mentioning these stamps
print("=== ARM FOLDER LOOKUP ===")
if EXP.exists():
    for arm in sorted(EXP.rglob("RS_Audit_Report_*.csv")):
        stem = arm.stem.replace("RS_Audit_Report_", "")
        if stem in stamps:
            print(f"{stem}: {arm.parent.relative_to(EXP)}")

print("\n=== PER-STAMP SUMMARY ===")
for s in stamps:
    with open(ROOT / f"RS_Closed_{s}.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    with open(ROOT / f"RS_Audit_Report_{s}.csv", newline="", encoding="utf-8") as f:
        a = next(csv.DictReader(f))
    ptqs_n, ptqs_pnl = ptqs_stats(rows)
    s22_n, s22_pnl = stop22_stats(rows)
    opens = [r.get("DATE_OPENED") for r in rows if r.get("DATE_OPENED")]
    closes = [r.get("DATE_CLOSED") for r in rows if r.get("DATE_CLOSED")]
    syms = sorted({r["SYMBOL"].strip().upper() for r in rows if r.get("SYMBOL")})
    print(f"\n{s}")
    print(f"  traded={len(syms)} MA={'MA' in syms} syms={syms}")
    print(f"  date open {min(opens)}..{max(opens)}  close {min(closes)}..{max(closes)}")
    print(
        f"  cd={a['symbol_reentry_cooldown_days']} "
        f"spy_tc_not_weak={a['rs_spy_int_tc_not_weak']} "
        f"exit_spy_weak={a['exit_when_spy_int_turns_weak']} "
        f"entry_start={a['entry_start_date']!r} "
        f"brt_cash={float(a['brt_cash']):.2f} "
        f"max_pos={a['Max_Positions']}"
    )
    print(
        f"  trades={a['Total_Trades']} PnL={float(a['Total_PNL']):,.0f} "
        f"Agg={float(a['Aggressive_Total_PNL']):,.0f} "
        f"AROR={float(a['Ann_ROR']):.2f} DD={float(a['Max_DD']):.2f} "
        f"AggDD={float(a['Aggressive_Max_DD']):.2f}"
    )
    print(
        f"  WR={float(a['Pct_Wins']):.1f}% Exp$={float(a['Expectancy']):,.2f} "
        f"Exp%={float(a['Expectancy_Pct']):.2f} PF={float(a['Profit_Factor']):.2f} "
        f"$/capday={float(a['Profit_Per_Capital_Day']):.2f}"
    )
    print(f"  PTQS_n={ptqs_n} PTQS$={ptqs_pnl:,.0f}  STOP22_n={s22_n} STOP22$={s22_pnl:,.0f}")
