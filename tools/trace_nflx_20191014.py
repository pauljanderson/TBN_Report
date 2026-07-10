#!/usr/bin/env python3
"""NFLX 2019-10-14 vs 10-21 trade: formula-by-formula deep dive."""
from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb  # noqa: E402

# GoogleFinance / sheet OHLC (user paste)
GF_OHLC = {
    "2019-10-11": (28.48, 28.79, 27.59, 28.29),
    "2019-10-14": (28.39, 28.69, 28.20, 28.55),
    "2019-10-21": (27.29, 27.99, 26.90, 27.81),
}

SHEET_ZONE = {
    "2019-10-11": (26.5776, 27.66, 721, 7),
    "2019-10-14": (28.6748, 29.85, 590, 13),
    "2019-10-21": (26.5776, 27.66, 721, 7),
}


def run_pipeline(df: pd.DataFrame, cfg: rb.BRTConfig, label: str) -> dict:
    ph, pl, php, plp = rb.compute_pivots(
        df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
    n = len(df)
    o, h, lo, c = [df[x].to_numpy(float) for x in ["Open", "High", "Low", "Close"]]
    mbh, mbi = rb._precompute_mat_bh_bi_stream(
        l3["zone_low"].to_numpy(float), l3["zone_high"].to_numpy(float), 7, n
    )
    ce_all = np.asarray(mbh, dtype=np.float64)
    cf_all = np.asarray(mbi, dtype=np.float64)
    de, dfa, dg, ds = rb._precompute_sheet_active_zone_arrays(h, lo, mbh, mbi, n, cfg)
    g = rb._precompute_mts_bi_gates(o, h, lo, c, de, dfa, dg, ds, mbh, mbi, n, cfg)
    return {
        "df": df, "o": o, "h": h, "lo": lo, "c": c,
        "ce": ce_all, "cf": cf_all, "de": de, "dfa": dfa, "dg": dg, "ds": ds, "g": g,
        "label": label,
    }


def ohlc_diff(df: pd.DataFrame) -> None:
    print("\n=== OHLC: Engine CSV vs GoogleFinance (sheet) ===")
    print(f"{'Date':12} {'Field':5} {'CSV':>10} {'GF':>10} {'Delta':>10} {'Match'}")
    for d, (go, gh, gl, gc) in GF_OHLC.items():
        row = df.loc[pd.Timestamp(d)]
        for name, csv_v, gf_v in [
            ("Open", row["Open"], go),
            ("High", row["High"], gh),
            ("Low", row["Low"], gl),
            ("Close", row["Close"], gc),
        ]:
            delta = float(csv_v) - gf_v
            ok = abs(delta) < 0.02
            flag = "ok" if ok else "** MISMATCH"
            if not ok or name == "Low":
                print(f"{d:12} {name:5} {float(csv_v):10.4f} {gf_v:10.4f} {delta:+10.4f} {flag}")


def overlap_on_day(st: dict, d: str, focus_j: int | None = None) -> None:
    df, h, lo = st["df"], st["h"], st["lo"]
    ce, cf = st["ce"], st["cf"]
    de, dfa, dg, ds = st["de"], st["dfa"], st["dg"], st["ds"]
    i = df.index.get_loc(pd.Timestamp(d))
    print(f"\n--- Overlap {st['label']} on {d} (H={h[i]:.4f} L={lo[i]:.4f}) ---")
    print(f"  Engine active: DK={de[i]:.4f} DL={dfa[i]:.4f} DM={int(dg[i])} DN={int(ds[i])}")
    if d in SHEET_ZONE:
        sdk, sdl, sdm, sdn = SHEET_ZONE[d]
        print(f"  Sheet active:  DK={sdk:.4f} DL={sdl:.4f} DM={sdm} DN={sdn}")
    cands = []
    for j in range(i + 1):
        if not (np.isfinite(ce[j]) and ce[j] > 0 and np.isfinite(cf[j])):
            continue
        ov = h[i] >= ce[j] and lo[i] <= cf[j]
        if not ov and j != focus_j:
            continue
        cnt = sum(1 for k in range(j, i + 1) if np.isfinite(ce[k]) and ce[k] > 0)
        note = ""
        if j == int(dg[i]):
            note = " <-- engine pick"
        if d in SHEET_ZONE and abs(ce[j] - SHEET_ZONE[d][0]) < 0.02:
            note += " [sheet zone band]"
        cands.append((j, ce[j], cf[j], cnt, ov, note))
    cands.sort(key=lambda x: -x[0])
    for j, zl, zu, cnt, ov, note in cands[:8]:
        print(
            f"  j={j:4d} {df.index[j].date()} CE={zl:.4f} CF={zu:.4f} DN={cnt} "
            f"ov={'Y' if ov else 'N'}{note}"
        )
    # zone DN=7 band (~719 maturity)
    for j in [719, 588, 528]:
        if j <= i and np.isfinite(ce[j]):
            cf_j = cf[j]
            print(
                f"  zone j={j}: L<={cf_j:.4f}? {lo[i] <= cf_j}  "
                f"(L={lo[i]:.4f}) H>={ce[j]:.4f}? {h[i] >= ce[j]}"
            )


def gate_row(st: dict, d: str) -> None:
    df, g, de, dfa, dg, ds = st["df"], st["g"], st["de"], st["dfa"], st["dg"], st["ds"]
    o, h, lo, c = st["o"], st["h"], st["lo"], st["c"]
    i = df.index.get_loc(pd.Timestamp(d))
    ip = i - 1 if i >= 1 else i
    print(f"\n--- Gates {st['label']} {d} ---")
    print(
        f"  Zone DN={int(ds[i])} DK={de[i]:.4f} DL={dfa[i]:.4f} DM={int(dg[i])}"
    )
    if i >= 1 and np.isfinite(dfa[i]):
        print(
            f"  AK parts: C[-1]={c[ip]:.4f}>DL? {c[ip] > dfa[i]} | "
            f"L={lo[i]:.4f}<=DL? {lo[i] <= dfa[i]} | H={h[i]:.4f}>=DK? {h[i] >= de[i]} | "
            f"i>DM? {i > dg[i]}"
        )
    bc_ok = g["bc"][i] or (g["bc"][i - 1] if i >= 1 else False)
    aq_ok = g["aq"][i] or (g["aq"][i - 1] if i >= 1 else False)
    print(
        f"  AK={int(g['ak'][i])} AM={int(g['am'][i])} AQ={int(g['aq'][i])} "
        f"AW={int(g['aw'][i])} BC={int(g['bc'][i])} BC[-1]={int(g['bc'][i-1]) if i else 0} "
        f"BE={int(g['be'][i])} BG={int(g['bg'][i])} BI={int(g['bi'][i])}"
    )
    print(f"  BC_ok={bc_ok} AQ_ok={aq_ok}")
    if g["bi"][i] and i + 1 < len(df):
        print(f"  -> fill {df.index[i+1].date()} @ {df['Open'].iloc[i+1]:.2f}")


def bi_bars(st: dict, start: str, end: str) -> None:
    df, g, ds, de, dfa = st["df"], st["g"], st["ds"], st["de"], st["dfa"]
    t0, t1 = pd.Timestamp(start), pd.Timestamp(end)
    print(f"\n  BI=1 bars ({st['label']}) {start}..{end}:")
    for i, d in enumerate(df.index):
        if d < t0 or d > t1 or not g["bi"][i]:
            continue
        fill = df["Open"].iloc[i + 1] if i + 1 < len(df) else float("nan")
        print(
            f"    {d.date()} DN={int(ds[i])} {de[i]:.2f}-{dfa[i]:.2f} "
            f"-> fill {df.index[i+1].date() if i+1<len(df) else '?'} @ {fill:.2f}"
        )


def main() -> None:
    base = asdict(rb.BRTConfig())
    base.update(rb.mts_sheet_parity_overrides())
    cfg = rb.BRTConfig(**base)

    df_yahoo = rb.load_csv(str(_REPO / "data" / "newdata" / "data" / "NFLX.csv"))
    ohlc_diff(df_yahoo)

    st_y = run_pipeline(df_yahoo, cfg, "Yahoo CSV")
    dates = [
        "2019-10-09", "2019-10-10", "2019-10-11", "2019-10-14",
        "2019-10-15", "2019-10-18", "2019-10-21", "2019-10-22",
    ]
    print("\n" + "=" * 72)
    print("Yahoo CSV pipeline")
    print("=" * 72)
    hdr = "Date       O      H      L      C | DN  DK-DL        | AK AM AQ BG BI"
    print(hdr)
    for d in dates:
        i = st_y["df"].index.get_loc(pd.Timestamp(d))
        print(
            f"{d} {st_y['o'][i]:6.2f} {st_y['h'][i]:6.2f} {st_y['lo'][i]:6.2f} {st_y['c'][i]:6.2f} | "
            f"{int(st_y['ds'][i]):2d}  {st_y['de'][i]:.2f}-{st_y['dfa'][i]:.2f} | "
            f"{int(st_y['g']['ak'][i])}  {int(st_y['g']['am'][i])}  {int(st_y['g']['aq'][i])}  "
            f"{int(st_y['g']['bg'][i])}  {int(st_y['g']['bi'][i])}"
        )

    overlap_on_day(st_y, "2019-10-11")
    for d in ["2019-10-11", "2019-10-14", "2019-10-21"]:
        gate_row(st_y, d)
    bi_bars(st_y, "2019-10-01", "2019-10-25")

    # GoogleFinance: patch 10/11 Low (only confirmed mismatch)
    df_gf = df_yahoo.copy()
    for d, (o, hi, lo, cl) in GF_OHLC.items():
        ts = pd.Timestamp(d)
        df_gf.loc[ts, ["Open", "High", "Low", "Close"]] = [o, hi, lo, cl]

    st_g = run_pipeline(df_gf, cfg, "GoogleFinance")
    print("\n" + "=" * 72)
    print("GoogleFinance OHLC (10/11 Low=27.59 patched; other pasted days too)")
    print("=" * 72)
    for d in dates:
        i = st_g["df"].index.get_loc(pd.Timestamp(d))
        print(
            f"{d} DN={int(st_g['ds'][i]):2d} AK={int(st_g['g']['ak'][i])} "
            f"AQ={int(st_g['g']['aq'][i])} BG={int(st_g['g']['bg'][i])} BI={int(st_g['g']['bi'][i])}"
        )
    overlap_on_day(st_g, "2019-10-11")
    for d in ["2019-10-11", "2019-10-14", "2019-10-21"]:
        gate_row(st_g, d)
    bi_bars(st_g, "2019-10-01", "2019-10-25")

    # Backtest compare
    ph, pl, php, plp = rb.compute_pivots(
        df_gf, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    struct = rb.compute_market_structure(df_gf, ph, pl, php, plp)
    l3 = rb.build_level3_for_cfg(df_gf, cfg, ph, pl, php, plp)
    closed, *_ = rb.run_brt_backtest("NFLX", df_gf, cfg, php, plp, struct, l3)
    for t in closed:
        trig = getattr(t, "close_above_date", "") or ""
        if "201910" in trig.replace("-", ""):
            print(
                f"\n  GF backtest: trig={trig} open={getattr(t,'date_opened','')} "
                f"@ {getattr(t,'entry_price',0):.2f} pnl={getattr(t,'pnl_pct',0):+.2f}%"
            )


if __name__ == "__main__":
    main()
