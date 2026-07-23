#!/usr/bin/env python3
"""Deep-dive MTS gate trace for NVDA Sep-Oct 2019 (sheet Sep 17 vs Python Oct 7)."""
from __future__ import annotations

import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))

import numpy as np  # noqa: E402
import rocket_brt as rb  # noqa: E402


def iso_to_i(index_iso: list[str], d: str) -> int:
    key = d.replace("-", "")
    for i, s in enumerate(index_iso):
        if s.replace("-", "").startswith(key):
            return i
    raise KeyError(d)


def run_trace(start: str = "2019-08-01", end: str = "2019-10-31") -> None:
    data_dir = _REPO / "data" / "newdata" / "data"
    base = asdict(rb.BRTConfig())
    base.update(rb.mts_sheet_parity_overrides())
    cfg = rb.BRTConfig(**base)

    df = rb.load_csv(str(data_dir / "NVDA.csv"))
    ph, pl, php, plp = rb.compute_pivots(
        df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    struct = rb.compute_market_structure(df, ph, pl, php, plp)
    l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)

    open_arr = df["Open"].to_numpy(dtype=float)
    high_arr = df["High"].to_numpy(dtype=float)
    low_arr = df["Low"].to_numpy(dtype=float)
    close_arr = df["Close"].to_numpy(dtype=float)
    n = len(df)
    index_iso = [str(x).replace("-", "")[:8] for x in df.index]

    lag = int(getattr(cfg, "strong_post_pivot_bars", 7) or 7)
    mat_bh, mat_bi = rb._precompute_mat_bh_bi_stream(
        np.asarray(l3["zone_low"], dtype=float),
        np.asarray(l3["zone_high"], dtype=float),
        lag, n,
    )
    de, dfa, dg, ds = rb._precompute_sheet_active_zone_arrays(
        high_arr, low_arr, mat_bh, mat_bi, n, cfg,
    )
    gates = rb._precompute_mts_bi_gates(
        open_arr, high_arr, low_arr, close_arr,
        de, dfa, dg, ds, mat_bh, mat_bi, n, cfg,
    )

    # DP first-touch (engine pending trigger)
    do_arr = np.zeros(n, dtype=bool)
    for i in range(n):
        if np.isfinite(ds[i]) and (not np.isfinite(dg[i]) or i > dg[i]):
            do_arr[i] = True
    dp = np.zeros(n, dtype=bool)
    for i in range(n):
        if not do_arr[i]:
            continue
        if i == 0 or not do_arr[i - 1] or ds[i] != ds[i - 1]:
            dp[i] = True

    si = iso_to_i(index_iso, start)
    ei = iso_to_i(index_iso, end)

    hdr = (
        "date       O      H      L      C    "
        "DK-DL(avail,id)          AR AW "
        "AK AM AQ  BC  BG  BW BE  BI  DP"
    )
    print(hdr)
    print("-" * len(hdr))

    bi_true_days: list[str] = []
    aw_true_days: list[str] = []

    for i in range(si, ei + 1):
        d = f"{index_iso[i][:4]}-{index_iso[i][4:6]}-{index_iso[i][6:8]}"
        dk_s = (
            f"${de[i]:.2f}-${dfa[i]:.2f} r{int(dg[i])+2} id{int(ds[i])}"
            if np.isfinite(de[i]) else "----"
        )
        row = (
            f"{d} {open_arr[i]:6.2f} {high_arr[i]:6.2f} {low_arr[i]:6.2f} {close_arr[i]:6.2f} "
            f"{dk_s:26s} "
            f"{gates['ar'][i]:2d} {int(gates['aw'][i]):2d} "
            f"{int(gates['ak'][i]):2d} {int(gates['am'][i]):2d} {int(gates['aq'][i]):2d} "
            f"{int(gates['bc'][i]):2d} {int(gates['bg'][i]):2d} "
            f"{int(gates['bw'][i]):2d} {int(gates['be'][i]):2d} "
            f"{int(gates['bi'][i]):2d} {int(dp[i]):2d}"
        )
        # Only print interesting rows
        interesting = any([
            gates["aw"][i], gates["bi"][i], gates["ak"][i], gates["am"][i],
            dp[i], d in ("2019-09-16", "2019-09-17", "2019-09-18", "2019-10-04", "2019-10-07", "2019-10-08"),
        ])
        if interesting:
            print(row)
        if gates["bi"][i]:
            bi_true_days.append(d)
        if gates["aw"][i]:
            aw_true_days.append(d)

    print("\n=== Sep 17 2019 AM deep-dive ===")
    i17 = iso_to_i(index_iso, "2019-09-17")
    dn17 = int(ds[i17])
    c10 = int(getattr(cfg, "lookback_long", 503))
    print(
        f"bar={i17} DN={dn17} zone ${de[i17]:.2f}-${dfa[i17]:.2f} "
        f"sheet_DM_row={int(dg[i17])+2}"
    )
    print(
        f"AK={gates['ak'][i17]} AM={gates['am'][i17]} AQ={gates['aq'][i17]} "
        f"AW={gates['aw'][i17]} BI={gates['bi'][i17]} AR={gates['ar'][i17]} "
        f"BC={gates['bc'][i17]} BG={gates['bg'][i17]} BE={gates['be'][i17]}"
    )
    s = max(0, i17 - c10)
    print(f"AK events with DN={dn17} in [{s}..{i17}]:")
    cnt = 0
    for k in range(s, i17 + 1):
        if gates["ak"][k] and np.isfinite(ds[k]) and int(ds[k]) == dn17:
            cnt += 1
            d = f"{index_iso[k][:4]}-{index_iso[k][4:6]}-{index_iso[k][6:8]}"
            print(
                f"  #{cnt} bar{k} {d} DN={int(ds[k])} "
                f"${de[k]:.2f}-${dfa[k]:.2f} sheet_row={int(dg[k])+2}"
            )
    print(f"AM count={cnt} (need >=3)")

    print(f"\n=== All AK with DN={dn17} in full C10 window [{s}..{i17}] ===")
    for k in range(s, i17 + 1):
        if gates["ak"][k] and np.isfinite(ds[k]) and int(ds[k]) == dn17:
            d = f"{index_iso[k][:4]}-{index_iso[k][4:6]}-{index_iso[k][6:8]}"
            print(f"  {d} bar{k} ${de[k]:.2f}-${dfa[k]:.2f} row={int(dg[k])+2}")

    # Bars where zone 720 bounds active but AK false (potential sheet-only AK)
    print("\n=== Zone $4.31-$4.49 active, AK=FALSE, in Aug-Sep 2019 ===")
    for i, s in enumerate(index_iso):
        if s < "20190801" or s > "20190930":
            continue
        if not (np.isfinite(de[i]) and 4.28 <= de[i] <= 4.32):
            continue
        if gates["ak"][i]:
            continue
        d = f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        prev_c = close_arr[i - 1] if i > 0 else float("nan")
        print(
            f"  {d} DN={int(ds[i])} H={high_arr[i]:.2f} L={low_arr[i]:.2f} "
            f"C={close_arr[i]:.2f} prevC={prev_c:.2f} DL={dfa[i]:.2f} "
            f"row>{int(dg[i])}? {i>dg[i]} prevC>DL? {prev_c>dfa[i]}"
        )

    print("\n=== AW days with full gate breakdown (Jul-Oct 2019) ===")
    for i, s in enumerate(index_iso):
        if s < "20190701" or s > "20191031":
            continue
        if not gates["aw"][i]:
            continue
        d = f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        dn_i = int(ds[i]) if np.isfinite(ds[i]) else -1
        print(
            f"  {d} DN={dn_i} AR={gates['ar'][i]} "
            f"AK={int(gates['ak'][i])} AM={int(gates['am'][i])} AQ={int(gates['aq'][i])} "
            f"BC={int(gates['bc'][i])} BG={int(gates['bg'][i])} BE={int(gates['be'][i])} "
            f"BI={int(gates['bi'][i])}"
        )

    # Sep 18 check (sheet entry may be next-day open from Sep 17 trigger)
    i18 = iso_to_i(index_iso, "2019-09-18")
    print("\n=== Sep 18 2019 (next bar after sheet trigger) ===")
    print(
        f"O={open_arr[i18]:.2f} C={close_arr[i18]:.2f} BE={gates['be'][i18]} "
        f"AQ={gates['aq'][i18]} BI={gates['bi'][i18]}"
    )

    print("\n=== All AK events 2018-2019 (any zone) ===")
    for i, s in enumerate(index_iso):
        if s < "20180101" or s > "20191231" or not gates["ak"][i]:
            continue
        d = f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        print(
            f"  {d} DN={int(ds[i]) if np.isfinite(ds[i]) else -1} "
            f"${de[i]:.2f}-${dfa[i]:.2f} row={int(dg[i])+2 if np.isfinite(dg[i]) else -1}"
        )

    for i, s in enumerate(index_iso):
        if not s.startswith("2019") or not gates["ak"][i]:
            continue
        if not (4.28 <= de[i] <= 4.32):
            continue
        d = f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        print(
            f"  {d} bar{i} DN={int(ds[i])} ${de[i]:.2f}-${dfa[i]:.2f} "
            f"sheet_row={int(dg[i])+2}"
        )

    print("\n=== All 2019 AK with DN=8 ===")
    for i, s in enumerate(index_iso):
        if not s.startswith("2019") or not gates["ak"][i]:
            continue
        if not (np.isfinite(ds[i]) and int(ds[i]) == 8):
            continue
        d = f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        print(
            f"  {d} bar{i} ${de[i]:.2f}-${dfa[i]:.2f} sheet_row={int(dg[i])+2}"
        )

    print("\n=== AW magic-touch event days ===")
    print(", ".join(aw_true_days) or "(none)")
    print("\n=== BI MTS buy TRUE days ===")
    print(", ".join(bi_true_days) or "(none)")

    # Run backtest and find trades in window
    closed, *_ = rb.run_brt_backtest(
        "NVDA", df, cfg, php, plp, struct, l3,
        benchmark_df=rb._load_benchmark_local(data_dir),
    )
    print("\n=== Python trades Aug-Dec 2019 ===")
    for t in sorted(closed, key=lambda x: x.date_opened):
        ped = str(t.date_opened).replace("-", "")[:8]
        if ped < "20190801" or ped > "20191231":
            continue
        print(
            f"  opened {t.date_opened} @ ${t.entry_price:.2f}  "
            f"closed {t.date_closed} pnl {t.pnl_pct:+.2f}%"
        )


if __name__ == "__main__":
    run_trace()
