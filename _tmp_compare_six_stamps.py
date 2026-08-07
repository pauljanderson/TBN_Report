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
    "260731125117",
]
MAX_QUICK = 10


def sn(x):
    try:
        return float(str(x).replace("%", "").replace("$", "").replace(",", "").strip() or 0)
    except Exception:
        return 0.0


def ymd8(r):
    d = "".join(c for c in str(r or "") if c.isdigit())
    return d[:8]


def closed_year(row):
    d = "".join(c for c in str(row.get("DATE_CLOSED") or "") if c.isdigit())
    return int(d[:4]) if len(d) >= 4 else 0


def ptqs(rows):
    by = defaultdict(list)
    for r in rows:
        s = str(r.get("SYMBOL") or "").strip().upper()
        if s:
            by[s].append(r)
    n = pnl = 0
    for trades in by.values():
        trades.sort(key=lambda r: (ymd8(r.get("DATE_OPENED")), ymd8(r.get("DATE_CLOSED"))))
        for i, r in enumerate(trades):
            if i + 1 >= len(trades):
                break
            if "TARGET" not in str(r.get("EXIT_TYPE") or "").upper():
                continue
            nxt = trades[i + 1]
            if "STOP" not in str(nxt.get("EXIT_TYPE") or "").upper():
                continue
            if int(sn(nxt.get("DAYS_HELD", 0))) > MAX_QUICK:
                continue
            n += 1
            pnl += sn(nxt.get("PNL_DOLLARS", 0))
    return n, pnl


def s22(rows):
    n = pnl = 0
    for r in rows:
        if "STOP" not in str(r.get("EXIT_TYPE") or "").upper():
            continue
        if closed_year(r) not in (2022, 2023):
            continue
        n += 1
        pnl += sn(r.get("PNL_DOLLARS", 0))
    return n, pnl


print("=== ARM LOOKUP ===")
for arm in sorted(EXP.rglob("RS_Audit_Report_*.csv")):
    stem = arm.stem.replace("RS_Audit_Report_", "")
    if stem in stamps:
        print(stem, "->", arm.parent.relative_to(EXP))

a650 = next(csv.DictReader(open(ROOT / "RS_Audit_Report_260731125650.csv", encoding="utf-8")))
a117 = next(csv.DictReader(open(ROOT / "RS_Audit_Report_260731125117.csv", encoding="utf-8")))
metricish = {
    "Total_PNL", "Wins", "Losses", "BE", "Pct_Wins", "Pct_Losses", "Win_Loss_Ratio",
    "Win_Loss_Ratio_Dollar", "Total_Trades", "Profit_Factor", "Avg_Win_Pct", "Avg_Loss_Pct",
    "Avg_PNL_Pct", "Expectancy", "Expectancy_Pct", "Avg_Days_Held", "Median_Days_Held",
    "P90_Days", "Avg_Days_Underwater", "P90_Days_Underwater", "Capital_Days",
    "Profit_Per_Capital_Day", "Ann_ROR", "Max_DD", "Losing_Streak", "DD_Per_Trade",
    "CES_AVG", "CES_Median", "Pct_PNL_Top10", "Pct_PNL_Bottom10", "Max_Positions",
    "Avg_Positions", "Median_Positions", "Score", "Pct_PNL_Max_Symbol", "Pct_PNL_Max_Trade",
    "Pct_PNL_Max_Industry", "Aggressive_Total_PNL", "Aggressive_Max_DD",
    "Aggressive_Avg_Positions", "Aggressive_Days_AtOrBelow_Avg", "Aggressive_Days_In_Margin",
    "Aggressive_Days_Trimmed_Over_2xAvg", "Trades_With_Meteoric_Rise_History",
    "Pct_Trades_With_Meteoric_Rise_History", "Trades_With_Meteoric_Fall_History",
    "Pct_Trades_With_Meteoric_Fall_History", "Trades_Post_Entry_Gain_Hit",
    "Pct_Trades_Post_Entry_Gain_Hit", "Timestamp_Drive", "aggressive_avg_positions_actual",
}
print("\n=== 125117 vs 125650 CONFIG DIFFS ===")
for k in a117:
    if k in metricish:
        continue
    if str(a117.get(k, "")) != str(a650.get(k, "")):
        print(f"  {k}: 125117={a117.get(k)!r}  125650={a650.get(k)!r}")

print("\n=== 6-WAY ===")
for s in stamps:
    a = next(csv.DictReader(open(ROOT / f"RS_Audit_Report_{s}.csv", encoding="utf-8")))
    rows = list(csv.DictReader(open(ROOT / f"RS_Closed_{s}.csv", encoding="utf-8")))
    syms = sorted({r["SYMBOL"].strip().upper() for r in rows if r.get("SYMBOL")})
    pn, pp = ptqs(rows)
    snn, spp = s22(rows)
    ma = "MA" in syms
    print(
        f"{s}: bd={a.get('sell_breakdown')!r} cd={a.get('symbol_reentry_cooldown_days')} "
        f"spy={a.get('rs_spy_int_tc_not_weak')}/{a.get('exit_when_spy_int_turns_weak')} "
        f"start={a.get('entry_start_date')!r}"
    )
    print(
        f"  traded={len(syms)} MA={ma} med={a.get('Median_Days_Held')} avg={a.get('Avg_Days_Held')} "
        f"Score={a.get('Score')!r}"
    )
    print(
        f"  n={a['Total_Trades']} PnL={float(a['Total_PNL']):,.0f} "
        f"Agg={float(a['Aggressive_Total_PNL']):,.0f} AROR={float(a['Ann_ROR']):.2f} "
        f"DD={float(a['Max_DD']):.2f} AggDD={float(a['Aggressive_Max_DD']):.2f}"
    )
    print(
        f"  WR={float(a['Pct_Wins']):.1f}% Exp$={float(a['Expectancy']):,.2f} "
        f"Exp%={float(a['Expectancy_Pct']):.2f} PF={float(a['Profit_Factor']):.2f} "
        f"$/cd={float(a['Profit_Per_Capital_Day']):.2f}"
    )
    print(f"  PTQS={pn} / {pp:,.0f}  STOP22={snn} / {spp:,.0f}  syms={','.join(syms)}")
