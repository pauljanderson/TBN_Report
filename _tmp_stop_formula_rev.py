#!/usr/bin/env python3
"""Reverse-engineer sheet stop vs engine stop for MarkTen LOSS exits."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(REPO))
from _tmp_markten_full_inv import (  # noqa
    BASE,
    DATA,
    MARKTEN,
    STAMP,
    STAMP_DIR,
    eng_date,
    load_sheet_trades,
    nf,
    nd,
)

closed = pd.read_csv(STAMP_DIR / f"WPBR_Closed_{STAMP}.csv")
closed["entry"] = closed["DATE_OPENED"].map(eng_date)
closed["exit"] = closed["DATE_CLOSED"].map(eng_date)


def load_ohlc(sym: str) -> pd.DataFrame:
    df = pd.read_csv(DATA / f"{sym}.csv")
    df.columns = [c.lower().replace(" ", "_") for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def signal_low(df: pd.DataFrame, entry: str, close_above: str | None) -> float | None:
    # Prefer CLOSE_ABOVE_DATE (signal) if present; else day before entry
    if close_above:
        d = eng_date(close_above) or nd(close_above)
        if d and pd.Timestamp(d) in df.index:
            return float(df.loc[d, "low"])
    # fallback: previous session before entry
    loc = df.index.get_indexer([pd.Timestamp(entry)], method="pad")[0]
    if loc <= 0:
        return None
    return float(df.iloc[loc - 1]["low"])


rows = []
for sym in MARKTEN:
    df = load_ohlc(sym)
    sheet = {t["entry"]: t for t in load_sheet_trades(BASE / sym)}
    e_sym = closed[closed["SYMBOL"].astype(str).str.upper() == sym]
    for _, er in e_sym.iterrows():
        d = er["entry"]
        if d not in sheet:
            continue
        st = sheet[d]
        if st.get("result") != "LOSS" and not (
            st.get("exit_px") and er.get("EXIT_TYPE") and "STOP" in str(er["EXIT_TYPE"]).upper()
        ):
            # include exit price mismatches on STOP days too
            if st.get("exit") != er.get("exit") and st.get("exit_px"):
                pass
            elif st.get("exit") == er.get("exit") and st.get("exit_px") and not (
                abs(float(st["exit_px"]) - float(er["EXIT_PRICE"])) < 0.03
            ):
                pass
            else:
                continue
        if st.get("exit_px") is None:
            continue
        entry_px = float(er["ENTRY_PRICE"])
        eng_stop = float(er["STOP_PRICE"])
        sheet_exit_px = float(st["exit_px"])
        sig_l = signal_low(df, d, er.get("CLOSE_ABOVE_DATE"))
        rows.append(
            {
                "sym": sym,
                "entry": d,
                "sheet_exit": st.get("exit"),
                "eng_exit": er.get("exit"),
                "sheet_px": sheet_exit_px,
                "eng_stop": eng_stop,
                "eng_exit_px": float(er["EXIT_PRICE"]) if er.get("EXIT_PRICE") is not None else None,
                "entry_px": entry_px,
                "sig_low": sig_l,
                "sheet_over_eng_stop": sheet_exit_px - eng_stop,
                "sheet_vs_entry_089": sheet_exit_px - entry_px * 0.89,
                "sheet_vs_sig_089": (sheet_exit_px - sig_l * 0.89) if sig_l else None,
                "sheet_vs_entry_09": sheet_exit_px - entry_px * 0.90,
                "sheet_vs_sig_09": (sheet_exit_px - sig_l * 0.90) if sig_l else None,
                "implied_mult_vs_sig": (sheet_exit_px / sig_l) if sig_l else None,
                "implied_mult_vs_entry": sheet_exit_px / entry_px,
                "same_day": st.get("exit") == er.get("exit"),
                "exit_type": er.get("EXIT_TYPE"),
            }
        )

out = pd.DataFrame(rows)
print(f"n={len(out)}")
# Focus cases where sheet exit likely IS the sheet stop (LOSS / STOP family)
focus = out[out["sheet_px"] > out["eng_stop"] + 0.02].copy()
print(f"sheet_px > eng_stop: {len(focus)}")
print("\nImplied mult vs signal low (sheet_exit/sig_low):")
print(focus["implied_mult_vs_sig"].describe())
print("\nImplied mult vs entry:")
print(focus["implied_mult_vs_entry"].describe())
print("\n|sheet - entry*0.89| median", focus["sheet_vs_entry_089"].abs().median())
print("|sheet - sig*0.89| median", focus["sheet_vs_sig_089"].abs().median())
print("|sheet - entry*0.90| median", focus["sheet_vs_entry_09"].abs().median())
print("|sheet - sig*0.90| median", focus["sheet_vs_sig_09"].abs().median())

# Best matching formula among candidates
cands = {
    "entry*0.89": lambda r: r["entry_px"] * 0.89,
    "sig*0.89": lambda r: r["sig_low"] * 0.89 if r["sig_low"] else None,
    "entry*0.90": lambda r: r["entry_px"] * 0.90,
    "sig*0.90": lambda r: r["sig_low"] * 0.90 if r["sig_low"] else None,
    "entry*0.91": lambda r: r["entry_px"] * 0.91,
    "sig*0.91": lambda r: r["sig_low"] * 0.91 if r["sig_low"] else None,
    "round2(sig)*0.89": lambda r: round(r["sig_low"], 2) * 0.89 if r["sig_low"] else None,
    "round2(sig)*0.90": lambda r: round(r["sig_low"], 2) * 0.90 if r["sig_low"] else None,
    "round2(entry*0.89)": lambda r: round(r["entry_px"] * 0.89, 2),
    "round2(sig*0.89)": lambda r: round(r["sig_low"] * 0.89, 2) if r["sig_low"] else None,
}

print("\nBest formula hits (abs err <= 0.03):")
for name, fn in cands.items():
    hits = 0
    errs = []
    for _, r in focus.iterrows():
        pred = fn(r)
        if pred is None:
            continue
        err = abs(pred - r["sheet_px"])
        errs.append(err)
        if err <= 0.03:
            hits += 1
    if errs:
        print(f"  {name}: hits={hits}/{len(errs)} median_err={pd.Series(errs).median():.4f}")

print("\nSample rows (NFLX + a few others):")
show = focus[focus["sym"].isin(["NFLX", "AAPL", "AMD", "TSLA"])].head(20)
for _, r in show.iterrows():
    ms = f"{r.implied_mult_vs_sig:.4f}" if r.implied_mult_vs_sig is not None and pd.notna(r.implied_mult_vs_sig) else "None"
    print(
        f"{r.sym} {r.entry}: sheet_px={r.sheet_px:.2f} eng_stop={r.eng_stop:.2f} entry={r.entry_px:.2f} sigL={r.sig_low} "
        f"mult_sig={ms} mult_ent={r.implied_mult_vs_entry:.4f} same_day={r.same_day} {r.sheet_exit}->{r.eng_exit}"
    )

# Check: is sheet_px ~= first-touch day Low somehow? or Close?
print("\n=== NFLX Aug special ===")
nflx = focus[(focus.sym == "NFLX") & (focus.entry == "2023-08-21")].iloc[0]
print(nflx.to_dict())
