import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock_analysis"))

import pandas as pd
from rocket_brt import BRTConfig, compute_pivots, compute_touch_stream, load_csv

sym = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
cfg = BRTConfig()
cfg.brt_zones = True
cfg.yh_zones = False
cfg.band_pct = 0.02

df = load_csv(str(ROOT / "data/newdata/data" / f"{sym}.csv"))
ph, pl, ph_price, pl_price = compute_pivots(
    df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
    realtime_filter_enabled=cfg.realtime_filter_enabled,
)
l3 = compute_touch_stream(
    df,
    ph,
    pl,
    ph_price,
    pl_price,
    cfg.band_pct,
    cfg.lookback_long,
    cfg.touch_threshold,
    cfg.lookback_short,
    strong_pivots_enabled=cfg.strong_pivots_enabled,
    strong_pre_pivot_bars=cfg.strong_pre_pivot_bars,
    strong_pre_pivot_pct=cfg.strong_pre_pivot_pct,
    strong_post_pivot_bars=cfg.strong_post_pivot_bars,
    strong_post_pivot_pct=cfg.strong_post_pivot_pct,
    strong_pivot_mode=cfg.strong_pivot_mode,
    zone_maturity_model=cfg.zone_maturity_model,
    sheet_maturity_lag_bars=cfg.sheet_maturity_lag_bars,
)

print(f"{sym}: pivot_high={(ph==1).sum()} touch={l3['touch_price'].notna().sum()} matured={l3['matured_now'].sum()}")
print("--- touches ---")
for i in range(len(df)):
    if pd.notna(l3["touch_price"].iloc[i]):
        d = str(df.index[i])[:10]
        print(d, float(l3["zone_center"].iloc[i]), "matured", bool(l3["matured_now"].iloc[i]))
print("--- matured ---")
for i in range(len(df)):
    if l3["matured_now"].iloc[i]:
        d = str(df.index[i])[:10]
        print(d, float(l3["zone_center"].iloc[i]), float(l3["zone_low"].iloc[i]), float(l3["zone_high"].iloc[i]))

# strong_pivots off
l3b = compute_touch_stream(
    df, ph, pl, ph_price, pl_price, cfg.band_pct, cfg.lookback_long, cfg.touch_threshold, cfg.lookback_short,
    strong_pivots_enabled=False,
    zone_maturity_model=cfg.zone_maturity_model,
    sheet_maturity_lag_bars=cfg.sheet_maturity_lag_bars,
)
print(f"no-strong-filter: touch={l3b['touch_price'].notna().sum()} matured={l3b['matured_now'].sum()}")
