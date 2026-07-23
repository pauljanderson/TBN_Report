from pathlib import Path
import pandas as pd

STAMP = "260722174105"
OUT = Path(r"drive/wpbr_sheet_reconcile/_markten_variantC_SC_stop91_startfloor_halfup_scresume_20260722174203")
MARKTEN = ["AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA", "AU", "AMD", "NFLX"]
df = pd.read_csv(OUT / f"WPBR_Closed_{STAMP}.csv")
cols = {c.upper(): c for c in df.columns}

def col(*names):
    for n in names:
        if n.upper() in cols:
            return cols[n.upper()]
    return None

sym_c = col("SYMBOL")
pnl_c = col("PNL_DOLLARS", "PNL", "PROFIT", "PNL_DOLLAR", "DOLLAR_PNL", "TOTAL_PNL", "PNL_USD")
pct_c = col("PNL_PCT", "PROFIT_PCT", "PCT", "RETURN_PCT")
days_c = col("DAYS_HELD", "DAYS", "DAYS_IN_TRADE")
date_c = col("DATE_OPENED", "ENTRY_DATE", "OPEN_DATE", "DATE")

def has_date(sub, want):
    if not date_c:
        return False
    s = sub[date_c].astype(str)
    w = want.replace("-", "")
    return any(w in str(x).replace("-", "") or want in str(x) for x in s)

amzn = df[df[sym_c].astype(str).str.upper() == "AMZN"]
au = df[df[sym_c].astype(str).str.upper() == "AU"]
tsla = df[df[sym_c].astype(str).str.upper() == "TSLA"]
print("AMZN_n", len(amzn))
print("AMZN_has_2022-12-08", has_date(amzn, "2022-12-08"))
print("AU_has_2019-04-25", has_date(au, "2019-04-25"))
print("TSLA_has_2022-12-16", has_date(tsla, "2022-12-16"))
print("date_col", date_c)
print("AMZN_dates", amzn[date_c].astype(str).tolist() if date_c else None)
if date_c:
    s = au[date_c].astype(str)
    print("AU_hit", au[s.str.contains("2019-04-25") | s.str.contains("20190425")][[date_c, sym_c]].to_string(index=False))
    s = tsla[date_c].astype(str)
    print("TSLA_hit", tsla[s.str.contains("2022-12-16") | s.str.contains("20221216")][[date_c, sym_c]].to_string(index=False))

def fp(x):
    if pd.isna(x):
        return None
    t = str(x).replace("%", "").replace(",", "").replace("$", "").strip()
    try:
        return float(t)
    except Exception:
        return None

blocks = []
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
    blocks.append(block)
    print(block)
    print()

path = OUT / "_markten_stacked_stats.txt"
path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
print("wrote", path)
print("CONFIRM_AMZN_n_eq_8", len(amzn) == 8)
print("CONFIRM_AMZN_20221208", has_date(amzn, "2022-12-08"))
print("CONFIRM_AU_20190425", has_date(au, "2019-04-25"))
print("CONFIRM_TSLA_20221216", has_date(tsla, "2022-12-16"))
