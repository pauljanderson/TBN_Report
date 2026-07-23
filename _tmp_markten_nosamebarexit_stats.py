"""Per-symbol MarkTen stacked stats + TSLA 2022-12-16 spot-check for nosamebarexit run."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

STAMP = "260722171712"
OUT = Path(
    r"drive/wpbr_sheet_reconcile/_markten_variantC_SC_stop91_startfloor_halfup_nosamebarexit_20260722171645"
)
MARKTEN = ["AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA", "AU", "AMD", "NFLX"]

df = pd.read_csv(OUT / f"WPBR_Closed_{STAMP}.csv")
cols = {c.upper(): c for c in df.columns}


def col(*names: str) -> str | None:
    for n in names:
        if n.upper() in cols:
            return cols[n.upper()]
    return None


sym_c = col("SYMBOL")
pnl_c = col("PNL_DOLLARS", "PNL", "PROFIT", "PNL_DOLLAR", "DOLLAR_PNL", "TOTAL_PNL", "PNL_USD")
pct_c = col("PNL_PCT", "PROFIT_PCT", "PCT", "RETURN_PCT")
days_c = col("DAYS_HELD", "DAYS", "DAYS_IN_TRADE")
date_c = col("DATE_OPENED", "ENTRY_DATE", "OPEN_DATE", "DATE")

tsla = df[df[sym_c].astype(str).str.upper() == "TSLA"]
print("TSLA closed count", len(tsla))
if date_c:
    s = tsla[date_c].astype(str)
    hit = tsla[
        s.str.contains("20221216")
        | s.str.contains("2022-12-16")
        | s.str.contains("20221209")
        | s.str.contains("2022-12-09")
    ]
    show = [date_c]
    for c in [
        col("DATE_CLOSED", "EXIT_DATE", "CLOSE_DATE"),
        col("ENTRY_PRICE"),
        col("EXIT_PRICE"),
        pct_c,
        col("WPBR_ZONE_ID", "ZONE_ID"),
    ]:
        if c:
            show.append(c)
    print("TSLA Dec2022 window rows:")
    print(hit[show].to_string(index=False))
    has_1216 = any("20221216" in str(x) or "2022-12-16" in str(x) for x in tsla[date_c])
    print("has_20221216", has_1216)

rep = pd.read_csv(OUT / f"WPBR_Report_{STAMP}.csv")
flag_col = [c for c in rep.columns if "sheet_no_entry" in c.lower()]
print("Report sheet_no_entry:", {c: rep[c].iloc[0] for c in flag_col})
print("Report wpbr_zones:", rep[[c for c in rep.columns if c == "wpbr_zones"]].iloc[0].to_dict() if "wpbr_zones" in rep.columns else None)


def fp(x):
    if pd.isna(x):
        return None
    t = str(x).replace("%", "").replace(",", "").replace("$", "").strip()
    try:
        return float(t)
    except Exception:
        return None


blocks: list[str] = []
for sym in MARKTEN:
    s = df[df[sym_c].astype(str).str.upper() == sym]
    n = len(s)
    pcts = [fp(x) for x in s[pct_c]] if pct_c else []
    pcts = [p for p in pcts if p is not None]
    wins = [p for p in pcts if p > 0]
    losses = [p for p in pcts if p < 0]
    wr = 100.0 * len(wins) / n if n else 0.0
    avg = sum(pcts) / len(pcts) if pcts else 0.0
    aw = sum(wins) / len(wins) if wins else 0.0
    al = sum(losses) / len(losses) if losses else 0.0
    if losses and aw:
        wl = aw / abs(al)
    elif wins:
        wl = float("inf")
    else:
        wl = 0.0
    days = []
    if days_c:
        for x in s[days_c]:
            v = fp(x)
            if v is not None:
                days.append(v)
    avgd = sum(days) / len(days) if days else float("nan")
    dol = 0.0
    if pnl_c:
        for x in s[pnl_c]:
            v = fp(x)
            if v is not None:
                dol += v
    wl_s = f"{wl:.2f}" if wl != float("inf") else "inf"
    block = f"{sym}\n{n}\n{wr:.1f}%\n{avg:.1f}%\n{wl_s}\n{avgd:.1f}\n${dol:,.2f}"
    print(block)
    print()
    blocks.append(block)

(OUT / "_markten_stacked_stats.txt").write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
print("wrote", OUT / "_markten_stacked_stats.txt")
