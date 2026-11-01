import sys
from pathlib import Path
sys.path.insert(0, "stock_analysis")
from wpbr_zones import compute_wpbr_touch_stream
import pandas as pd
import traceback

CACHE = Path("drive/paul_experiments/wpbr_weekly_zone_cache_20261002/parity_cache.duckdb")
df = pd.read_csv("data/newdata/data/AAPL.csv")
df["Date"] = pd.to_datetime(df["Date"])
df = df.set_index("Date").sort_index()
df = df[["Open","High","Low","Close","Volume"]].astype(float)

# replicate cache prelude
import os
use_weekly_zone_cache = True
weekly_zone_cache_db = str(CACHE)
cache_symbol = "AAPL"
debug_symbol = None
_cache_sym = (cache_symbol or debug_symbol or "").strip().upper()
_use_cache = bool(use_weekly_zone_cache)
print("use", _use_cache, "sym", _cache_sym)
try:
    import wpbr_weekly_zone_cache as _cache_mod
    print("mod", _cache_mod.__file__)
    _cache_db = _cache_mod.resolve_cache_db_path(weekly_zone_cache_db or None)
    print("db", _cache_db)
    _cfg_hash = _cache_mod.config_hash(band_pct=0.015, band_pct_atr=0.0, strong_pre_pivot_bars=3, strong_pre_pivot_pct=0.1, strong_pre_pivot_pct_atr=0.0, strong_post_pivot_bars=3, strong_post_pivot_pct=0.1, strong_post_pivot_pct_atr=0.0, strong_pivot_mode="either", breakout_confirmation=0.03, max_days_after_retest=2, retest_mode="stop_looking", zone_price_round_decimals=2, min_pivot_date="", merge_overlapping_zones=False)
    print("cfg", _cfg_hash)
    _daily_fp = _cache_mod.daily_fingerprint(df)
    print("fp", _daily_fp)
    hit = _cache_mod.load_stream_cache(_cache_db, symbol=_cache_sym, cfg_hash=_cfg_hash, daily_fp=_daily_fp, n_bars=len(df), index=pd.DatetimeIndex(df.index))
    print("hit", hit is not None, _cache_mod.format_cache_stats())
except Exception:
    traceback.print_exc()
