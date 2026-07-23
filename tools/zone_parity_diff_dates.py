#!/usr/bin/env python3
"""Map matured-zone sequence diffs to pivot (AF) dates per symbol."""
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

CE_DIR = _REPO / "sheet_ce_ground_truth"
DATA = _REPO / "data" / "newdata" / "data"


def load_sheet_zones(sym: str) -> list[str]:
    p = CE_DIR / f"{sym}_ce.txt"
    return [ln.strip() for ln in p.read_text().splitlines() if ln.strip()]


def engine_zone_stream(cfg: rb.BRTConfig, sym: str) -> tuple[list[str], list[int]]:
    df = rb.load_csv(str(DATA / f"{sym}.csv"))
    ph, pl, php, plp = rb.compute_pivots(
        df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
    zl = l3["zone_low"].to_numpy(float)
    dates = df.index.strftime("%Y-%m-%d").tolist()
    zones, idxs = [], []
    prev = None
    for i, v in enumerate(zl):
        if np.isfinite(v) and v > 0 and v != prev:
            zones.append(f"{v:.2f}")
            idxs.append(i)
            prev = v
    return zones, idxs


def touch_events(cfg: rb.BRTConfig, sym: str) -> list[tuple[str, float, float]]:
    df = rb.load_csv(str(DATA / f"{sym}.csv"))
    dates = df.index.strftime("%Y-%m-%d").tolist()
    lag = rb._effective_sheet_maturity_lag_bars(cfg)
    touch = rb.compute_sheet_brt_touch_stream(
        df,
        band_pct=cfg.band_pct,
        pivot_local_window=cfg.pivot_k,
        post_pivot_bars=cfg.strong_post_pivot_bars,
        pivot_future_move_pct=cfg.pivot_disp,
        dedup_tol_pct=rb._PIVOT_DEDUP_EPS,
        pre_pivot_bars=cfg.strong_pre_pivot_bars,
        pre_pivot_pct=cfg.strong_pre_pivot_pct,
        touch_pullback_pct=cfg.strong_post_pivot_pct,
        touch_pullback_bars=int(cfg.strong_post_pivot_bars or 7),
        maturity_lag=lag,
        warmup_bars=int(getattr(cfg, "brt_sheet_warmup_bars", 9) or 9),
        zone_price_round_decimals=cfg.zone_price_round_decimals,
        lookback_long=cfg.lookback_long,
        lookback_short=cfg.lookback_short,
        touch_threshold=cfg.touch_threshold,
        include_pivot_low_touches=bool(cfg.mts_zone_low_touches),
    )
    tp = touch["touch_price"].to_numpy(float)
    out = []
    for i, af in enumerate(tp):
        if np.isfinite(af) and af > 0:
            zl = rb._round_zone_price(af * (1.0 - cfg.band_pct), cfg.zone_price_round_decimals)
            out.append((dates[i], float(af), float(zl)))
    return out


def zone_to_pivot_date(touches: list[tuple[str, float, float]], zone: str) -> str | None:
    target = float(zone)
    for d, af, zl in touches:
        if abs(zl - target) < 0.005:
            return d
    return None


def main() -> int:
    syms = sys.argv[1:] or ["AAPL", "GOOGL", "NFLX", "NVDA", "TSLA"]
    base = asdict(rb.BRTConfig())
    base.update(rb.mts_sheet_parity_overrides())
    cfg = rb.BRTConfig(**base)

    for sym in syms:
        sheet = load_sheet_zones(sym)
        eng, eng_idx = engine_zone_stream(cfg, sym)
        touches = touch_events(cfg, sym)
        sm = difflib.SequenceMatcher(a=sheet, b=eng, autojunk=False)
        print(f"\n=== {sym} sheet={len(sheet)} engine={len(eng)} ratio={sm.ratio():.4f} ===")
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue
            if tag in ("replace", "delete"):
                for k in range(i1, i2):
                    z = sheet[k]
                    pd = zone_to_pivot_date(touches, z)
                    print(f"  sheet-only zone={z}  pivot~{pd or '?'}")
            if tag in ("replace", "insert"):
                for k in range(j1, j2):
                    z = eng[k]
                    # find touch that produced this zone
                    pd = zone_to_pivot_date(touches, z)
                    mat = eng_idx[k] if k < len(eng_idx) else None
                    mat_d = ""
                    df = rb.load_csv(str(DATA / f"{sym}.csv"))
                    if mat is not None:
                        mat_d = df.index.strftime("%Y-%m-%d")[mat]
                    print(f"  engine-only zone={z}  touch={pd or '?'}  matures~{mat_d}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
