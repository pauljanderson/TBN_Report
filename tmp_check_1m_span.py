import duckdb
from pathlib import Path

p = Path("data/intraday/1m")
files = list(p.glob("*.parquet"))
print("files", len(files))
con = duckdb.connect()
glob = (p / "*.parquet").as_posix()
q = "select min(ts) as mn, max(ts) as mx, count(*) as n from read_parquet('" + glob + "')"
print(con.execute(q).fetchdf())
