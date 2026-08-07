from pathlib import Path
import pandas as pd

data = Path("data/newdata/data")
syms = (
    "AXON,LULU,CMG,NVDA,TSLA,AMZN,META,NFLX,AMD,AVGO,ANET,CRM,CRWD,NET,SHOP,SNOW,CELH,DECK,"
    "PLTR,DDOG,ISRG,SMCI,UBER,PANW,NOW,ADBE,INTU,BKNG,MELI,SE,TTD,ZS,OKTA,MDB,TEAM,WDAY,"
    "APP,ARM,HOOD,COIN,AFRM,DKNG,ROKU,MSFT,GOOGL,AAPL,QCOM,MU,AMAT,LRCX,KLAC,CDNS,SNPS,"
    "FTNT,DASH,ABNB,PATH,RBLX,SOFI,MSTR"
).split(",")
print("count", len(syms))
missing, thin = [], []
for s in syms:
    p = data / f"{s}.csv"
    if not p.exists():
        missing.append(s)
        continue
    n = sum(1 for _ in open(p, encoding="utf-8", errors="ignore")) - 1
    if n < 300:
        thin.append((s, n))
print("missing", missing)
print("thin", thin)
text = Path("stock_analysis/pygetallMore.py").read_text(encoding="utf-8", errors="ignore")
not_in = [s for s in syms if f'"{s}"' not in text]
print("not in TICKERS", not_in)

print("\nA2 time-stop trades:")
a2 = pd.read_csv("drive/MVCP_Closed_260801155232.csv")
print(a2[a2.EXIT_TYPE == "TIME_STOP"][["SYMBOL", "DATE_OPENED", "DAYS_HELD", "PNL_PCT"]].to_string(index=False))
print("\nBaseline time-stop:")
b = pd.read_csv("drive/MVCP_Closed_260801122831.csv")
print(b[b.EXIT_TYPE == "TIME_STOP"][["SYMBOL", "DATE_OPENED", "DAYS_HELD", "PNL_PCT"]].to_string(index=False))
