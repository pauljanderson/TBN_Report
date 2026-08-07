import csv
import re
from pathlib import Path

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch\drive")
stamps = {
    "260731232940": "biggest aggressive PnL",
    "260731231739": "best AROR",
    "260731231707": "minimum drawdown",
    "260801093239": "highest expectancy",
    "260731125650": "max PnL",
}

audits = {}
for s in stamps:
    with open(ROOT / f"RS_Audit_Report_{s}.csv", newline="", encoding="utf-8") as f:
        audits[s] = next(csv.DictReader(f))

print("=== UNIVERSE (Profile) ===")
for s in stamps:
    path = ROOT / f"BRT_Profile_Symbols_{s}.csv"
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    cols = list(rows[0].keys()) if rows else []
    sym_col = None
    for c in cols:
        if c.lower() in ("symbol", "ticker", "sym"):
            sym_col = c
            break
    if not sym_col:
        # often first column is symbol-like
        print(s, "headers:", cols[:12], "n=", len(rows))
        if rows:
            print("  sample:", {k: rows[0][k] for k in cols[:8]})
        continue
    syms = sorted({r[sym_col].strip().upper() for r in rows if r.get(sym_col)})
    print(f"{s} n={len(syms)}: {','.join(syms)}")

print("\n=== DIFFERING CONFIG KEYS ===")
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
    "Pct_Trades_Post_Entry_Gain_Hit", "Timestamp_Drive",
}
all_keys = list(audits[next(iter(stamps))].keys())
diffs = []
for k in all_keys:
    if k in metricish:
        continue
    vals = {s: str(audits[s].get(k, "")) for s in stamps}
    if len(set(vals.values())) > 1:
        diffs.append(k)
print("keys:", diffs)
for k in diffs:
    print(f"\n{k}:")
    for s in stamps:
        print(f"  {s}: {audits[s].get(k)}")

print("\n=== METRICS ===")
metrics = [
    "Total_Trades", "Total_PNL", "Aggressive_Total_PNL", "Ann_ROR", "Max_DD",
    "Aggressive_Max_DD", "Pct_Wins", "Expectancy", "Expectancy_Pct", "Profit_Factor",
    "Profit_Per_Capital_Day", "Capital_Days", "Avg_Positions", "Max_Positions",
    "Avg_Days_Held", "Score", "brt_cash", "symbol_reentry_cooldown_days",
]
for s, label in stamps.items():
    a = audits[s]
    print(f"\n{s} ({label})")
    for m in metrics:
        print(f"  {m}: {a.get(m)}")

print("\n=== IMPROVE HINTS PTQS/STOP22 ===")
for s in stamps:
    md = ROOT / f"RS_ImproveHints_{s}.md"
    csvp = ROOT / f"RS_ImproveHints_{s}.csv"
    text = ""
    if md.exists():
        text = md.read_text(encoding="utf-8", errors="replace")
    elif csvp.exists():
        text = csvp.read_text(encoding="utf-8", errors="replace")
    # search PTQS / STOP
    hits = []
    for pat in [r"PTQS[^\n]{0,80}", r"STOP22[^\n]{0,80}", r"STOP_22[^\n]{0,80}",
                r"ptqs[^\n]{0,80}", r"stop22[^\n]{0,80}"]:
        hits.extend(re.findall(pat, text, flags=re.I))
    print(f"\n{s} md_exists={md.exists()} csv_exists={csvp.exists()} len={len(text)}")
    for h in hits[:12]:
        print(" ", h[:100])
    # also scan first lines of md for summary scores
    if md.exists():
        lines = text.splitlines()[:40]
        for ln in lines:
            if re.search(r"PTQS|STOP|score|Score|quality", ln, re.I):
                print("  L:", ln[:120])

# Closed trade symbol counts as fallback
print("\n=== CLOSED SYMBOL COUNTS ===")
for s in stamps:
    with open(ROOT / f"RS_Closed_{s}.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    cols = rows[0].keys() if rows else []
    sym_col = next((c for c in cols if c.lower() in ("symbol", "ticker")), None)
    if not sym_col:
        print(s, "closed cols", list(cols)[:10])
        continue
    syms = sorted({r[sym_col].strip().upper() for r in rows if r.get(sym_col)})
    print(f"{s} closed_n={len(rows)} unique_syms={len(syms)}: {','.join(syms)}")
