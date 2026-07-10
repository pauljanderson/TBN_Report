import sys
from dataclasses import asdict
from pathlib import Path
import collections
import numpy as np

_REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb

base = asdict(rb.BRTConfig())
base.update(rb.mts_sheet_parity_overrides())
cfg = rb.BRTConfig(**base)
df = rb.load_csv(str(_REPO / "data" / "newdata" / "data" / "NVDA.csv"))
ph, pl, php, plp = rb.compute_pivots(
    df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
    realtime_filter_enabled=cfg.realtime_filter_enabled,
)
l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
origin = l3["zone_touch_origin"].to_numpy(int)
tp = l3["touch_price"].to_numpy(float)
n = len(df)
iso = [str(x).replace("-", "")[:8] for x in df.index]

mask = np.isfinite(tp) & (tp > 0)
cnt = collections.Counter(int(origin[i]) for i in range(n) if mask[i])
print("zone origin counts (1=PH-high, 2=PL-low):", dict(cnt))

# The 18 matched-trade zones came from these DL uppers (approx). Print all created zones with origin,
# grouped, so we can see how many real zones are PL vs PH.
print("\nAll created zones (date  tp  origin):")
for i in range(n):
    if not mask[i]:
        continue
    d = iso[i]
    org = "PH" if origin[i] == 1 else "PL"
    print(f"  {d[:4]}-{d[4:6]}-{d[6:8]}  tp={tp[i]:8.3f}  {org}")
