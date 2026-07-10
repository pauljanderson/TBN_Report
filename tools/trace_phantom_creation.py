#!/usr/bin/env python3
"""Definitive per-bar zone-creation trace for the 3 phantom bars using CONFIRMED sheet constants."""
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

# CONFIRMED constants
PRE_BARS, PRE_PCT = 7, 0.12          # C17, C18
POST_BARS, POST_PCT = 7, 0.09        # C14, C15

idx = {f"{iso[i][:4]}-{iso[i][4:6]}-{iso[i][6:8]}": i for i in range(n)}

# Does the engine actually create a zone here?
l3 = rb.build_level3_for_cfg(
    df, cfg,
    *rb.compute_pivots(df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
                       realtime_filter_enabled=cfg.realtime_filter_enabled),
)
tp = l3["touch_price"].to_numpy(float)

for d in ("2017-02-07", "2019-06-03", "2021-10-04"):
    i = idx[d]
    print(f"=== {d} bar{i}  O{o[i]:.3f} H{h[i]:.3f} L{l[i]:.3f} C{c[i]:.3f} ===")
    print(f"  engine touch_price = {tp[i] if np.isfinite(tp[i]) else 'BLANK'}")
    # PL branch
    pre_hi = float(np.max(h[max(0, i - PRE_BARS):i]))
    pre_move = 1.0 - l[i] / pre_hi
    fwd = h[i + 1: i + POST_BARS + 1]
    fut_max = float(np.max(fwd))
    rise = fut_max / l[i] - 1.0
    argmax = i + 1 + int(np.argmax(fwd))
    print(f"  [PL] pre_hi={pre_hi:.3f} pre_move={pre_move*100:.2f}% (>= {PRE_PCT*100:.0f}%? "
          f"{pre_move>=PRE_PCT})")
    print(f"       fwd7 max H={fut_max:.3f} @ {iso[argmax]}  rise={rise*100:.2f}% (>= {POST_PCT*100:.0f}%? "
          f"{rise>=POST_PCT})")
    print(f"       fwd7 highs: {[round(float(x),3) for x in fwd]}")
    print()
