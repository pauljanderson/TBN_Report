"""Confirm AMZN/AU/TSLA + stacked 6-value for scresume MarkTen stamp. Do not commit."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

STAMP = "260722174041"
OUT = Path(
    "drive/wpbr_sheet_reconcile/_markten_variantC_SC_stop91_startfloor_halfup_scresume_20260722174137"
)
MARKTEN = ["AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA", "AU", "AMD", "NFLX"]

df = pd.read_csv(OUT / f"WPBR_Closed_{STAMP}.csv")
sym_c = "SYMBOL"
date_c = "DATE_OPENED"
pnl_c = "PNL_DOLLARS" if "PNL_DOLLARS" in df.columns else None
pct_c = "PNL_PCT" if "PNL_PCT" in df.columns else None
days_c = "DAYS_HELD" if "DAYS_HELD" in df.columns else None

checks = {
    "AMZN": ("2022-12-08", "20221208"),
    "AU": ("2019-04-25", "20190425"),
    "TSLA": ("2022-12-16", "20221216"),
}
for sym, dates in checks.items():
    s = df[df[sym_c].astype(str).str.upper() == sym]
    entries = s[date_c].astype(str).tolist()
    hit = any(any(d in str(x) for d in dates) for x in entries)
    print(f"{sym} closed={len(s)} has_target={hit}")
    if sym == "AMZN":
        print("  entries:", sorted(set(pd.to_datetime(s[date_c]).dt.strftime("%Y-%m-%d"))))


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
