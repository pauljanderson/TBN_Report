"""Check engine state on TSLA sheet-debug rows."""
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb

base = asdict(rb.BRTConfig())
base.update(rb.mts_sheet_parity_overrides())
cfg = rb.BRTConfig(**base)
df = rb.load_csv(str(_REPO / "data" / "newdata" / "data" / "TSLA.csv"))
iso = [str(x).replace("-", "")[:8] for x in df.index]
idx = {f"{s[:4]}-{s[4:6]}-{s[6:8]}": i for i, s in enumerate(iso)}
ph, pl, php, plp = rb.compute_pivots(
    df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
    realtime_filter_enabled=cfg.realtime_filter_enabled,
)
l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
n = len(df)
o, h, lo, c = [df[x].to_numpy(float) for x in "Open High Low Close".split()]
mbh, mbi = rb._precompute_mat_bh_bi_stream(
    l3["zone_low"].to_numpy(float), l3["zone_high"].to_numpy(float), 7, n
)
de, dfa, dg, ds = rb._precompute_sheet_active_zone_arrays(h, lo, mbh, mbi, n, cfg)
g = rb._precompute_mts_bi_gates(o, h, lo, c, de, dfa, dg, ds, mbh, mbi, n, cfg)

dates = (
    "2019-01-02", "2019-01-03", "2019-01-04", "2019-01-07",
    "2021-12-17", "2021-12-20", "2021-12-21", "2021-12-22",
)
c5 = cfg.band_pct
ce = mbh
cd = np.full(n, np.nan)
for j in range(n):
    if np.isfinite(ce[j]) and ce[j] > 0:
        cd[j] = ce[j] / (1.0 - c5)

for d in dates:
    i = df.index.get_loc(d)
    tp = l3["touch_price"].iloc[i]
    zl = l3["zone_low"].iloc[i]
    zh = l3["zone_high"].iloc[i]
    gb = i - 756
    print(f"{d} bar{i+2}  tp={tp}  zl={zl} zh={zh}")
    print(
        f"  active DK={de[i]:.2f} DL={dfa[i]:.2f} DM={int(dg[i])+2} DN={int(ds[i])}"
    )
  # sheet Growth 3Y (ATH): Close >= C26 * MAX(High, 756)
    c26 = float(getattr(cfg, "ath_filter_c26", 0.6))
    w = 756
    mx = float(np.max(h[max(0, i - w + 1) : i + 1]))
    g3_ath = c[i] >= c26 * mx
    print(
        f"  BW={g['bw'][i]} g3_ath={g3_ath} close={c[i]:.2f} "
        f"thr={c26 * mx:.2f} mx756={mx:.2f}"
    )
    print(
        f"  AK={g['ak'][i]} AW={g['aw'][i]} AM={g['am'][i]} AR={g['ar'][i]} "
        f"BC={g['bc'][i]} BE={g['be'][i]} BG={g['bg'][i]} BI={g['bi'][i]}"
    )
    if i > 0:
        print(
            f"  prev AR={g['ar'][i-1]} prev AW={g['aw'][i-1]} "
            f"prev BC={g['bc'][i-1]} prev DN={int(ds[i-1])}"
        )
    dk, dl_band = de[i], dfa[i]
    if np.isfinite(dk):
        hits = [
            (df.index[j].strftime("%Y-%m-%d"), round(cd[j], 2))
            for j in range(max(0, i - 20), i + 1)
            if np.isfinite(cd[j]) and dk <= cd[j] <= dl_band
        ]
        print(f"  CD in active band (last 21): {hits}")
    print()
