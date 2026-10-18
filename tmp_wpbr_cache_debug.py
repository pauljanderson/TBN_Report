import sys
from pathlib import Path
sys.path.insert(0, "stock_analysis")
import duckdb
from wpbr_weekly_zone_cache import resolve_cache_db_path, reset_cache_stats, get_cache_stats, format_cache_stats
from wpbr_zones import compute_wpbr_touch_stream
import pandas as pd

CACHE = Path("drive/paul_experiments/wpbr_weekly_zone_cache_20261002/parity_cache.duckdb")
print("exists", CACHE.exists(), "size", CACHE.stat().st_size if CACHE.exists() else 0)
con = duckdb.connect(str(CACHE), read_only=True)
print("tables", con.execute("SHOW TABLES").fetchall())
print("meta", con.execute("SELECT * FROM symbol_daily_meta").fetchall())
print("weekly count", con.execute("SELECT symbol, count(*) FROM weekly_bars GROUP BY 1").fetchall())
print("stream", con.execute("SELECT symbol, config_hash, daily_fp, n_bars, length(payload) FROM wpbr_stream_cache").fetchall())
con.close()

df = pd.read_csv("data/newdata/data/AAPL.csv")
df["Date"] = pd.to_datetime(df["Date"])
df = df.set_index("Date").sort_index()
df = df[["Open","High","Low","Close","Volume"]].astype(float)
reset_cache_stats()
s1 = compute_wpbr_touch_stream(df, use_weekly_zone_cache=True, weekly_zone_cache_db=str(CACHE), cache_symbol="AAPL")
print("after1", format_cache_stats(), "zones", len(s1["wpbr_zone_events"]))
s2 = compute_wpbr_touch_stream(df, use_weekly_zone_cache=True, weekly_zone_cache_db=str(CACHE), cache_symbol="AAPL")
print("after2", format_cache_stats(), "zones", len(s2["wpbr_zone_events"]))
