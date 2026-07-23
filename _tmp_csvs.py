from pathlib import Path
# check shard_00 symbols against data csvs and find how many CSVs in data dir
data = Path(r"C:\Users\songg\Downloads\stockresearch\data\newdata\data")
csvs = sorted([p.stem.upper() for p in data.glob("*.csv")])
print("csv_n", len(csvs))
print("first20", csvs[:20])
print("last20", csvs[-20:])
# exclude obvious non-stocks
exclude = {"SPY"}
syms = [s for s in csvs if s not in exclude and not s.startswith(".")]
print("syms_ex_spy", len(syms))
