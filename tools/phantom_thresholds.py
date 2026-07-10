#!/usr/bin/env python3
"""Compute exact pre-pivot & touch-pullback % for the 3 phantom PL/PH creations vs thresholds."""
import sys
from dataclasses import asdict
from pathlib import Path
import numpy as np

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb

base = asdict(rb.BRTConfig())
base.update(rb.mts_sheet_parity_overrides())
cfg = rb.BRTConfig(**base)
df = rb.load_csv(str(_REPO / "data" / "newdata" / "data" / "NVDA.csv"))
n = len(df)
iso = [str(x).replace("-", "")[:8] for x in df.index]
o, h, l, c = [df[x].to_numpy(float) for x in "Open High Low Close".split()]

pre_bars = int(cfg.strong_pre_pivot_bars)      # 7
pre_pct = float(cfg.strong_pre_pivot_pct)      # 0.12
tpb = int(getattr(cfg, "sheet_touch_pullback_bars", 10) or 10)
tp_pct = float(cfg.strong_post_pivot_pct)      # 0.09
post_bars = int(cfg.strong_post_pivot_bars)    # 7
disp = float(cfg.pivot_disp)                   # 0.06

def dts(i):
    return f"{iso[i][:4]}-{iso[i][4:6]}-{iso[i][6:8]}"

# (pivot_bar, origin) for the 3 phantoms
PH = [(276, "PH"), (858, "PL"), (1448, "PL")]
print(f"params: pre_bars={pre_bars} pre_pct={pre_pct:.3f}  tpb={tpb} tp_pct={tp_pct:.3f}  "
      f"post_bars={post_bars} disp={disp:.3f}\n")

for pb, org in PH:
    print(f"=== {dts(pb)} bar{pb} {org} ===  O{o[pb]:.3f} H{h[pb]:.3f} L{l[pb]:.3f} C{c[pb]:.3f}")
    if org == "PH":
        pre_lo = float(np.min(l[max(0, pb - pre_bars):pb]))
        pre_move = h[pb] / pre_lo - 1.0
        fut_min = float(np.min(l[pb + 1: pb + tpb + 1]))
        pull = 1.0 - fut_min / h[pb]
        fut_min_post = float(np.min(l[pb + 1: pb + post_bars + 1]))
        postdrop = fut_min_post / h[pb] - 1.0
        print(f"  pre-move (H/preLo-1)  = {pre_move*100:.2f}%  (need >= {pre_pct*100:.1f}%)  "
              f"{'PASS' if pre_move>=pre_pct else 'FAIL'}")
        print(f"  touch-pullback        = {pull*100:.2f}%  (need >= {tp_pct*100:.1f}%)  "
              f"{'PASS' if pull>=tp_pct else 'FAIL'}")
        print(f"  post-drop (final PH)  = {postdrop*100:.2f}%  (need <= -{disp*100:.1f}%)  "
              f"{'PASS' if postdrop<=-disp else 'FAIL'}")
    else:
        pre_hi = float(np.max(h[max(0, pb - pre_bars):pb]))
        pre_move = 1.0 - l[pb] / pre_hi
        fut_max = float(np.max(h[pb + 1: pb + tpb + 1]))
        rise = fut_max / l[pb] - 1.0
        fut_max_post = float(np.max(h[pb + 1: pb + post_bars + 1]))
        postrise = fut_max_post / l[pb] - 1.0
        print(f"  pre-move (1-Lo/preHi) = {pre_move*100:.2f}%  (need >= {pre_pct*100:.1f}%)  "
              f"{'PASS' if pre_move>=pre_pct else 'FAIL'}")
        print(f"  touch-pullback (rise) = {rise*100:.2f}%  (need >= {tp_pct*100:.1f}%)  "
              f"{'PASS' if rise>=tp_pct else 'FAIL'}")
        print(f"  post-rise (final PL)  = {postrise*100:.2f}%  (need >= {disp*100:.1f}%)  "
              f"{'PASS' if postrise>=disp else 'FAIL'}")
    print()
