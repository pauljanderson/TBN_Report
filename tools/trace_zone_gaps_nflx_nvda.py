#!/usr/bin/env python3
"""Deep trace for remaining NFLX/NVDA matured-zone gaps vs sheet ground truth."""
from __future__ import annotations

import sys
from dataclasses import asdict
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb

DATA = _REPO / "data" / "newdata" / "data"
GT = _REPO / "sheet_ce_ground_truth"


def r2(x: float) -> float:
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def sheet_triplets(sym: str) -> list[tuple[float, float, float]]:
    """Parse touch/lower/upper from export file."""
    p = _REPO / "tools" / "multisym_sheet_export.txt"
    text = p.read_text(encoding="utf-8")
    rows: list[tuple[float, float, float]] = []
    in_sym = False
    for line in text.splitlines():
        line = line.strip()
        if line == sym:
            in_sym = True
            continue
        if in_sym and line in ("AAPL", "AMZN", "META", "MSFT", "GOOGL", "NFLX", "NVDA", "TSLA"):
            break
        if not in_sym or not line.startswith("$"):
            continue
        parts = [x.replace("$", "") for x in line.split("\t")]
        if len(parts) >= 3:
            rows.append((float(parts[0]), float(parts[1]), float(parts[2])))
    return rows


def engine_touches(cfg: rb.BRTConfig, sym: str) -> list[dict]:
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
        warmup_bars=9,
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
            out.append(
                {
                    "date": dates[i],
                    "af": float(af),
                    "zl": float(zl),
                    "h": float(df["High"].iloc[i]),
                    "l": float(df["Low"].iloc[i]),
                    "rh": rb._round_zone_price(float(df["High"].iloc[i]), 2),
                    "rl": rb._round_zone_price(float(df["Low"].iloc[i]), 2),
                }
            )
    return out


def find_mismatch(sym: str, sheet_zl: float, eng_zl: float) -> None:
    base = asdict(rb.BRTConfig())
    base.update(rb.mts_sheet_parity_overrides())
    cfg = rb.BRTConfig(**base)
    trips = sheet_triplets(sym)
    touches = engine_touches(cfg, sym)

    sheet_row = next((t for t in trips if r2(t[1]) == sheet_zl), None)
    eng_row = next((t for t in touches if abs(t["zl"] - eng_zl) < 0.001), None)

    print(f"\n{'='*60}")
    print(f"{sym}: sheet zone {sheet_zl:.2f}  vs  engine zone {eng_zl:.2f}")
    print(f"{'='*60}")
    if sheet_row:
        af_s, raw_zl, zh = sheet_row
        print(f"  Sheet export:  AF={af_s:.4f}  raw_lower={raw_zl:.7f}  upper={zh:.4f}")
        print(f"                 ROUND(raw_lower,2)={r2(raw_zl):.2f}  AF*(1-C5)={r2(af_s*0.98):.2f}")
    else:
        print("  Sheet export:  (no matching triplet found)")

    if eng_row:
        print(f"  Engine pivot:  date={eng_row['date']}")
        print(f"                 H={eng_row['h']:.6f} L={eng_row['l']:.6f}")
        print(f"                 ROUND(H,2)={eng_row['rh']:.2f} ROUND(L,2)={eng_row['rl']:.2f}")
        print(f"                 AF={eng_row['af']:.2f}  zone_lower={eng_row['zl']:.2f}")
        if sheet_row:
            daf = eng_row["af"] - sheet_row[0]
            print(f"                 AF delta (engine - sheet) = {daf:+.4f}")
            # What sheet High would need for sheet AF?
            need_h = sheet_row[0]
            print(f"                 Sheet AF={need_h:.2f} implies ROUND(H,2)={need_h:.2f}")
            print(f"                 Yahoo H on that bar = {eng_row['h']:.4f}")

    # Sequence context: neighbors in ground truth
    gt = [float(x) for x in (GT / f"{sym}_ce.txt").read_text().splitlines() if x.strip()]
    for i, z in enumerate(gt):
        if abs(z - sheet_zl) < 0.011:
            lo = gt[max(0, i - 2) : i + 3]
            print(f"  Zone stream context (sheet file idx {i}): {[f'{x:.2f}' for x in lo]}")
            break


def main() -> None:
    find_mismatch("NFLX", 32.54, 32.55)
    find_mismatch("NVDA", 6.74, 6.75)
    find_mismatch("NVDA", 26.38, 26.39)


if __name__ == "__main__":
    main()
