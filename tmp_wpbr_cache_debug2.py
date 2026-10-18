import sys
from pathlib import Path
sys.path.insert(0, "stock_analysis")
import duckdb
from wpbr_weekly_zone_cache import reset_cache_stats, format_cache_stats, save_stream_cache, config_hash, daily_fingerprint
from wpbr_zones import compute_wpbr_touch_stream
import pandas as pd
import traceback

CACHE = Path("drive/paul_experiments/wpbr_weekly_zone_cache_20261002/parity_cache.duckdb")
con = duckdb.connect(str(CACHE), read_only=True)
print("stream rows", con.execute("SELECT symbol, config_hash, daily_fp, n_bars, octet_length(payload) FROM wpbr_stream_cache").fetchall())
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

# try MSFT save path explicitly
df2 = pd.read_csv("data/newdata/data/MSFT.csv")
df2["Date"] = pd.to_datetime(df2["Date"])
df2 = df2.set_index("Date").sort_index()
df2 = df2[["Open","High","Low","Close","Volume"]].astype(float)
try:
    s = compute_wpbr_touch_stream(df2, use_weekly_zone_cache=True, weekly_zone_cache_db=str(CACHE), cache_symbol="MSFT")
    print("MSFT zones", len(s["wpbr_zone_events"]), format_cache_stats())
except Exception:
    traceback.print_exc()
con = duckdb.connect(str(CACHE), read_only=True)
print("meta after", con.execute("SELECT symbol, n_bars FROM symbol_daily_meta").fetchall())
print("stream after", con.execute("SELECT symbol, n_bars, octet_length(payload) FROM wpbr_stream_cache").fetchall())
con.close()
