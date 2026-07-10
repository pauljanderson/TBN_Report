#!/usr/bin/env python3
"""Validate engine DK/DL/DM/DN vs unlimited-zone sheet ground truth.

Ground truth: ``nvda_active_zones_unlimited.tsv`` (repo root), one bar per line::

    lower<TAB>upper<TAB>avail_row<TAB>zone_id

Blank line = no active zone on that bar.

Run: python tools/parse_nvda_zone_truth.py
"""
from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path
from typing import Optional

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))

import numpy as np  # noqa: E402
import rocket_brt as rb  # noqa: E402

TRUTH = _REPO / "nvda_active_zones_unlimited.tsv"
# Sheet ROW() = engine 0-based bar index + offset (header + parameter rows).
SHEET_ROW_OFFSET = 2


def _money(s: str) -> Optional[float]:
    s = (s or "").strip().replace("$", "").replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def load_truth() -> list[dict]:
    rows: list[dict] = []
    lines = TRUTH.read_text(encoding="utf-8").splitlines()
    if lines and "Active zone lower" in lines[0]:
        lines = lines[1:]
    for line in lines:
        parts = line.split("\t")
        parts += [""] * (4 - len(parts))
        lower, upper, avail, zid = parts[:4]
        rows.append({
            "lower": _money(lower),
            "upper": _money(upper),
            "avail_row": int(avail) if avail.strip().isdigit() else None,
            "zone_id": int(zid) if zid.strip().isdigit() else None,
        })
    return rows


def run_engine():
    data_dir = _REPO / "data" / "newdata" / "data"
    sym = "NVDA"
    base = asdict(rb.BRTConfig())
    base.update(rb.mts_sheet_parity_overrides())
    base["debug_dump_active_zones"] = True
    cfg = rb.BRTConfig(**base)

    df = rb.load_csv(str(data_dir / f"{sym}.csv"))
    bench = rb._load_benchmark_local(data_dir)
    ph, pl, php, plp = rb.compute_pivots(
        df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    struct = rb.compute_market_structure(df, ph, pl, php, plp)
    l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
    rb.run_brt_backtest(sym, df, cfg, php, plp, struct, l3, benchmark_df=bench)
    return df, rb._LAST_ACTIVE_ZONE_ARRAYS


def main() -> int:
    if not TRUTH.exists():
        print(f"Missing truth file: {TRUTH}")
        return 1
    truth = load_truth()
    df, arrs = run_engine()
    if arrs is None:
        print("No active-zone arrays captured.")
        return 1
    de, dfa, dg, ds = arrs
    n = len(df)
    idx = df.index
    m = min(n, len(truth))

    all_match = both_blank = 0
    dk_dl_dm_dn_match = 0
    active_rows = 0
    mismatches: list[str] = []

    for i in range(m):
        t = truth[i]
        t_active = t["lower"] is not None
        e_active = np.isfinite(de[i])
        if not t_active and not e_active:
            both_blank += 1
            all_match += 1
            continue
        if t_active != e_active:
            if len(mismatches) < 40:
                d = str(idx[i])[:10]
                eng = (
                    f"${de[i]:.2f}-${dfa[i]:.2f} row{int(dg[i])} id{int(ds[i])}"
                    if e_active else "(blank)"
                )
                tr = (
                    f"${t['lower']:.2f}-${t['upper']:.2f} row{t['avail_row']} id{t['zone_id']}"
                    if t_active else "(blank)"
                )
                mismatches.append(f"  bar {i} {d}: engine {eng} vs truth {tr}")
            continue
        active_rows += 1
        eng_low = round(float(de[i]), 2)
        eng_up = round(float(dfa[i]), 2)
        eng_row = int(dg[i])
        eng_id = int(ds[i])
        ok = (
            abs(eng_low - t["lower"]) <= 0.02
            and abs(eng_up - t["upper"]) <= 0.02
            and eng_row + SHEET_ROW_OFFSET == t["avail_row"]
            and eng_id == t["zone_id"]
        )
        if ok:
            dk_dl_dm_dn_match += 1
            all_match += 1
        elif len(mismatches) < 40:
            d = str(idx[i])[:10]
            mismatches.append(
                f"  bar {i} {d}: engine ${eng_low}-${eng_up} row{eng_row} id{eng_id} "
                f"vs truth ${t['lower']:.2f}-${t['upper']:.2f} row{t['avail_row']} id{t['zone_id']}"
            )

    print(f"Bars compared: {m}")
    print(f"Both blank:              {both_blank}")
    print(f"Active bars:             {active_rows}")
    print(f"DK/DL/DM/DN exact match: {dk_dl_dm_dn_match}/{active_rows} active "
          f"({100*dk_dl_dm_dn_match/max(active_rows,1):.1f}%)")
    print(f"All rows match:          {all_match}/{m} ({100*all_match/max(m,1):.1f}%)")
    if mismatches:
        print(f"\nFirst mismatches ({len(mismatches)} shown):")
        print("\n".join(mismatches))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
