import sys, inspect
sys.path.insert(0, "stock_analysis")
import wpbr_zones
print(wpbr_zones.__file__)
sig = inspect.signature(wpbr_zones.compute_wpbr_touch_stream)
print(sig)
src = inspect.getsource(wpbr_zones.compute_wpbr_touch_stream)
print("use_weekly_zone_cache" in src)
print([l for l in src.splitlines() if "cache" in l.lower()][:30])
