import pandas as pd
import numpy as np

df = pd.read_csv(
    r"C:\Users\songg\Downloads\stockresearch\data\newdata\data\META.csv",
    parse_dates=["Date"],
).set_index("Date").sort_index()

cases = [
    ("139.68 vs 139.49", "2017-04-20", 298),
    ("144.25 vs 143.44", "2017-04-27", 316),
    ("740.91 vs 729.00", "2025-07-31", None),
]

for label, act_date, yh_bar in cases:
    print(f"--- {label} ---")
    if act_date in df.index:
        r = df.loc[act_date]
        print(f"Activation day {act_date}: High={r.High:.4f} Close={r.Close:.4f}")
    if yh_bar is not None and yh_bar < len(df):
        d = df.index[yh_bar]
        r = df.iloc[yh_bar]
        print(f"Engine yh_bar {yh_bar} ({d.date()}): High={r.High:.4f} rounded={round(r.High,2)}")

# Jul 2025 highs for 740.91
sub = df.loc["2025-07-01":"2025-07-31"]
print("--- Jul 2025 highs ---")
for d, r in sub.iterrows():
    if r.High >= 720:
        print(d.date(), f"High={r.High:.2f}")

# infer sheet band
for c, zl, zh in [(135.49, 133.46, 137.52), (740.91, 729.80, 752.02)]:
    print(f"center {c}: lower pct={(c-zl)/c*100:.3f}% upper pct={(zh-c)/c*100:.3f}%")
