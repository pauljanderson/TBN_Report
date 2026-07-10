#!/usr/bin/env python3
"""Parse user-pasted MTS rows vs engine gates for TSLA/NFLX/NVDA mismatches."""
from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
import rocket_brt as rb  # noqa: E402

HEADER = (_REPO / "tools" / "sheet_extras_windows.tsv").read_text(encoding="utf-8").splitlines()[0].split("\t")

FOCUS = [
    "Support test",
    "Support Evidence",
    "Zone Eligible Long",
    "Long window Rolling touch count",
    "magic touch event",
    "Range Qualifier",
    "Close above open",
    "In the zone",
    "Level Acceptance",
    "Too High",
    "MTS buy",
    "IN trade",
    "Entry Price Active",
    "Entry Date Active",
    "Growth 3 Year",
    "Growth OK",
    "Active zone lower",
    "Active zone upper",
    "Active zone available row",
    "Active zone ID",
]

PASTE = _REPO / "tools" / "mismatch_paste.tsv"


def parse_row(line: str) -> dict[str, str]:
    cols = line.rstrip("\n").split("\t")
    out: dict[str, str] = {}
    for name in FOCUS:
        if name in HEADER:
            i = HEADER.index(name)
            out[name] = cols[i] if i < len(cols) else ""
    out["Date"] = cols[0] if cols else ""
    # Tail columns (Active zone block) when paste is shorter than full header width.
    if len(cols) >= 4:
        out["Active zone lower"] = out.get("Active zone lower") or cols[-4]
        out["Active zone upper"] = out.get("Active zone upper") or cols[-3]
        out["Active zone available row"] = out.get("Active zone available row") or cols[-2]
        out["Active zone ID"] = out.get("Active zone ID") or cols[-1]
    return out


def engine_row(sym: str, iso: str, cfg: rb.BRTConfig) -> dict[str, str]:
    import numpy as np

    df = rb.load_csv(str(_REPO / "data" / "newdata" / "data" / f"{sym}.csv"))
    if iso not in {d.strftime("%Y-%m-%d") for d in df.index}:
        return {"error": "missing date"}
    i = {d.strftime("%Y-%m-%d"): j for j, d in enumerate(df.index)}[iso]
    ph, pl, php, plp = rb.compute_pivots(
        df, cfg.pivot_k, cfg.pivot_d, cfg.pivot_disp, cfg.pivot_m,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
    n = len(df)
    mbh, mbi = rb._precompute_mat_bh_bi_stream(
        l3["zone_low"].to_numpy(float), l3["zone_high"].to_numpy(float), 7, n
    )
    h, lo, c, o = [df[x].to_numpy(float) for x in ("High", "Low", "Close", "Open")]
    de, dfa, dg, ds = rb._precompute_sheet_active_zone_arrays(h, lo, mbh, mbi, n, cfg)
    g = rb._precompute_mts_bi_gates(o, h, lo, c, de, dfa, dg, ds, mbh, mbi, n, cfg)
    _do = np.zeros(n, dtype=bool)
    for j in range(n):
        if np.isfinite(ds[j]) and (not np.isfinite(dg[j]) or j > dg[j]):
            _do[j] = True
    dp = np.zeros(n, dtype=bool)
    for j in range(n):
        if not _do[j]:
            continue
        if j == 0 or not _do[j - 1] or ds[j] != ds[j - 1]:
            dp[j] = True
    return {
        "Support test": str(bool(g["ak"][i])),
        "Support Evidence": str(bool(g["am"][i])),
        "Zone Eligible Long": str(bool(g["aq"][i])),
        "Long window Rolling touch count": str(int(g["ar"][i])),
        "magic touch event": str(bool(g["aw"][i])),
        "Range Qualifier": str(bool(g["bc"][i])),
        "Close above open": str(bool(g["be"][i])),
        "Level Acceptance": str(bool(g["bg"][i])),
        "MTS buy": str(bool(g["bi"][i])),
        "Active zone lower": f"{de[i]:.2f}" if np.isfinite(de[i]) else "",
        "Active zone upper": f"{dfa[i]:.2f}" if np.isfinite(dfa[i]) else "",
        "Active zone ID": str(int(ds[i])) if np.isfinite(ds[i]) else "",
        "DP": str(bool(dp[i])),
    }


def main() -> None:
    base = asdict(rb.BRTConfig())
    base.update(rb.mts_sheet_parity_overrides())
    cfg = rb.BRTConfig(**base)

    sym_by_section = {"TSLA": "TSLA", "NFLX": "NFLX", "NVDA": "NVDA"}
    current_sym = "TSLA"
    for line in PASTE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("#"):
            tag = line.lstrip("#").strip().rstrip(":").upper()
            if tag in ("TSLA", "NFLX", "NVDA", "AAPL", "AMZN", "META", "GOOGL", "MSFT"):
                current_sym = tag
                print(f"\n{'='*72}\n{current_sym}\n{'='*72}")
            continue
        row = parse_row(line)
        d = row.get("Date", "")
        # normalize date to ISO
        parts = d.replace("/", "-").split("-")
        if len(parts) == 3:
            mo, da, yr = parts if len(parts[0]) <= 2 else (parts[1], parts[2], parts[0])
            if len(yr) == 2:
                yr = "20" + yr
            iso = f"{yr}-{int(mo):02d}-{int(da):02d}"
        else:
            iso = d
        eng = engine_row(current_sym, iso, cfg)
        print(f"\n--- {iso} ---")
        for name in FOCUS + ["DP"]:
            if name not in row and name != "DP":
                continue
            sv = row.get(name, "")
            ev = eng.get(name, "")
            flag = "  " if sv.upper() == str(ev).upper() or sv == ev else "**"
            if name == "DP":
                print(f"  {flag} {'DP':35s} sheet=(n/a)     eng={ev}")
            else:
                print(f"  {flag} {name:35s} sheet={sv!s:12s} eng={ev}")


if __name__ == "__main__":
    main()
