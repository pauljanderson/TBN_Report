"""Per-symbol MarkTen engine stats for stop91 stamp (stacked 6-row format)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

STAMP = "260722151857"
OUT = Path(r"drive/wpbr_sheet_reconcile/_markten_variantC_SC_stop91_2016_20260722151842")
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
print("cols sample:", list(df.columns)[:30])
print("mapped pnl/pct/days:", pnl_c, pct_c, days_c)


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
    # engine stores percent points (22.0) not fractions
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
