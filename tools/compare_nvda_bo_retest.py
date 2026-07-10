#!/usr/bin/env python3
"""Compare NVDA sheet breakout ledger vs engine YH_breakout_and_retest export."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.reconcile_nvda_retest_entries import _parse_mdy, load_engine_retest  # noqa: E402


def _money(s) -> float:
    import re
    return float(re.sub(r"[^0-9.\-]", "", str(s)))


def load_ledger() -> pd.DataFrame:
    df = pd.read_csv(ROOT / "tools/nvda_breakout_ledger_full.tsv", sep="\t", dtype=str)
    df.columns = [c.strip() for c in df.columns]
    # Some pasted rows omit trailing columns; keep rows where Retest Date looks like a date.
    rt_raw = df["Retest Date"].fillna("").astype(str).str.strip()
    df = df[rt_raw.str.contains("/", regex=False) & rt_raw.str.len().ge(8)].copy()
    df["bo_iso"] = df["Breakout Date"].map(_parse_mdy)
    df["rt_iso"] = df["Retest Date"].map(_parse_mdy)
    df["zl"] = df["Zone Lower"].map(_money)
    df["zu"] = df["Zone Upper"].map(_money)
    df["mr"] = pd.to_numeric(df["Main Row"], errors="coerce")
    return df.dropna(subset=["mr", "rt_iso"])


def key_row(mr: int, bo: str, zl: float, zu: float, rt: str) -> tuple:
    return (mr, bo, round(zl, 2), round(zu, 2), rt)


def main() -> None:
    run_id = sys.argv[1] if len(sys.argv) > 1 else "260620194127"
    eng = load_engine_retest(run_id)
    led = load_ledger()

    eng_keys = set()
    for _, r in eng.iterrows():
        eng_keys.add(
            key_row(
                int(r["Main Row"]),
                _parse_mdy(r["Breakout Date"]),
                _money(r["Zone Lower"]),
                _money(r["Zone Upper"]),
                _parse_mdy(r["Retest Date"]),
            )
        )

    led_keys = set()
    for _, r in led.iterrows():
        if not r["rt_iso"]:
            continue
        led_keys.add(
            key_row(int(r["mr"]), r["bo_iso"], r["zl"], r["zu"], r["rt_iso"])
        )

    both = eng_keys & led_keys
    eng_only = eng_keys - led_keys
    led_only = led_keys - eng_keys

    print(f"Run {run_id}")
    print(f"Engine retest rows (with RT): {len(eng_keys)}")
    print(f"Sheet ledger retest rows: {len(led_keys)}")
    print(f"Matched keys (MR, BO, zone@2dp, RT): {len(both)}")
    print(f"Engine only: {len(eng_only)}  Ledger only: {len(led_only)}")

    # Retest date shifts: same MR+BO+zone but different RT
    print("\n--- Retest DATE mismatch (same MR+BO+zone, different RT) ---")
    n_shift = 0
    for ek in eng_only:
        mr, bo, zl, zu, rt = ek
        for lk in led_only:
            if lk[0] == mr and lk[1] == bo and lk[2] == zl and lk[3] == zu:
                print(f"  MR{mr} BO {bo} zone ${zl}-${zu}: engine RT {rt}  ledger RT {lk[4]}")
                n_shift += 1
    if not n_shift:
        print("  (none by MR+BO+zone)")

    print("\n--- Sample engine-only (first 15) ---")
    for k in sorted(eng_only)[:15]:
        print(f"  MR{k[0]} BO {k[1]} ${k[2]}-${k[3]} RT {k[4]}")

    print("\n--- Sample ledger-only (first 15) ---")
    for k in sorted(led_only)[:15]:
        print(f"  MR{k[0]} BO {k[1]} ${k[2]}-${k[3]} RT {k[4]}")

    # Sheet trade triggers missing engine RT on that calendar day
    from tools.compare_nvda_sheet import load_sheet, next_td  # noqa: E402

    meta = pd.read_csv(ROOT / "data/newdata/data/NVDA.csv", parse_dates=["Date"])
    iso = [d.strftime("%Y-%m-%d") for d in meta.sort_values("Date").Date]
    sheet = load_sheet()
    sheet["purch_d"] = sheet.trigger_d.map(lambda d: next_td(iso, d) if d in iso else "")

    eng_rt_dates = {k[4] for k in eng_keys}
    led_rt_dates = {k[4] for k in led_keys}
    print("\n--- Sheet triggers: RT date in engine export? ---")
    for _, s in sheet.iterrows():
        t = s.trigger_d
        in_eng = t in eng_rt_dates
        in_led = t in led_rt_dates
        if not in_eng:
            near_eng = sorted(eng_rt_dates, key=lambda d: abs((pd.Timestamp(d) - pd.Timestamp(t)).days))[:1]
            near = near_eng[0] if near_eng else ""
            delta = (pd.Timestamp(near) - pd.Timestamp(t)).days if near else ""
            print(
                f"  trig {t} purch {s.purch_d}: eng_RT={in_eng} led_RT={in_led}"
                + (f" nearest_eng_RT={near} ({delta:+d}d)" if near else "")
            )


if __name__ == "__main__":
    main()
