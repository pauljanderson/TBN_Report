#!/usr/bin/env python3
"""Update TSLA_ce.txt from sheet raw CE list (ROUND_HALF_UP to 2dp) and diff vs engine."""
from __future__ import annotations

import difflib
import sys
from dataclasses import asdict
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb

RAW = """
9.2120000 15.6702000 17.6008000 13.3084000 12.2696000 18.7768000 19.8058000 25.4506000
19.2570000 15.9838000 20.4526000 24.4216000 21.2856000 19.3550000 25.3134000 18.8258000
21.3836000 16.4836000 17.0226000 20.6976000 16.1896000 24.7940000 19.2178000 22.1578000
19.4334000 18.2476000 17.6498000 16.6208000 19.3452000 15.1018000 11.5640000 14.5236000
16.2484000 22.2656000 38.8374000 63.3080000 61.7302000 39.9546000 22.9026000 36.5834000
29.1648000 50.6268000 44.0216000 56.8302000 44.6292000 55.0956000 67.1300000 117.2766000
110.3480000 89.2780000 164.1500000 107.7608000 150.9004000 114.7580000 146.6374000 152.1940000
123.8426000 147.8134000 129.3698000 198.5480000 213.7478000 185.0044000 227.0366000 288.9334000
254.8294000 202.2034000 285.4838000 176.2334000 193.0600000 255.0548000 178.6834000 207.6228000
406.2100000 319.6760000 392.6370000 310.4934000 289.4626000 394.6166000 320.1366000 364.4326000
258.7200000 309.6016000 228.6634000 290.6974000 246.9698000 376.6042000 317.8826000 356.7886000
268.4220000 312.1300000 222.1366000 202.7228000 258.9258000 204.5162000 247.0286000 211.8466000
249.8804000 307.3378000 308.3766000 260.4252000 225.2236000 194.6182000 232.6520000 173.5776000
196.8036000 162.8662000 194.9416000 99.7738000 183.8578000 213.2970000 160.6318000 203.6342000
149.3226000 271.4502000 235.8860000 293.3042000 208.1128000 273.4004000 229.8884000 198.4598000
190.1886000 221.8426000 176.4588000 157.2998000 180.5650000 157.2998000 136.0240000 194.8926000
265.5800000 228.4282000 210.4158000 178.3600000 223.6556000 230.3000000 259.5628000 268.0692000
234.1024000 351.4672000 303.0356000 354.6914000 478.7692000 407.1018000 456.0234000 365.5792000
430.9452000 318.5980000 359.9932000 212.6796000 217.8344000 286.0130000 209.9650000 218.3342000
267.7458000 350.3892000 282.9946000 331.2400000 342.0004000 461.3350000 403.2210000 464.5886000
375.1244000 420.3612000 376.0848000 488.8534000 427.6230000 330.4952000 401.0944000 444.3320000
385.7574000 436.6880000 372.5470000 424.2028000
""".split()


def r2(x: float) -> float:
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def main() -> int:
    sheet = [f"{r2(float(x)):.2f}" for x in RAW if x.strip()]
    out = _REPO / "sheet_ce_ground_truth" / "TSLA_ce.txt"
    out.write_text("\n".join(sheet) + "\n")
    print(f"Wrote {len(sheet)} CE values to {out}")

    base = asdict(rb.BRTConfig())
    base.update(rb.mts_sheet_parity_overrides())
    cfg = rb.BRTConfig(**base)
    df = rb.load_csv(str(_REPO / "data" / "newdata" / "data" / "TSLA.csv"))
    ph, pl, php, plp = rb.compute_pivots(
        df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
    mbh, _ = rb._precompute_mat_bh_bi_stream(
        l3["zone_low"].to_numpy(float), l3["zone_high"].to_numpy(float), 7, len(df)
    )
    eng = [f"{mbh[i]:.2f}" for i in range(len(df)) if np.isfinite(mbh[i]) and mbh[i] > 0]
    sm = difflib.SequenceMatcher(a=sheet, b=eng, autojunk=False)
    print(f"Engine {len(eng)}  ratio {sm.ratio():.4f}")
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if tag in ("replace", "delete"):
            for k in range(i1, i2):
                print(f"  sheet-only CE={sheet[k]}")
        if tag in ("replace", "insert"):
            for k in range(j1, j2):
                print(f"  engine-only CE={eng[k]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
