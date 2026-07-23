"""Diagnose AU 2019-04-25 vs SC resume on zone 11.82-12.18 (read-only)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "stock_analysis"))

import numpy as np
import pandas as pd

from wpbr_zones import find_wpbr_retest_and_signal

df = pd.read_csv(r"drive/brt_sheet_reconcile/AU_sheet_ohlc.csv", parse_dates=["date"])
df = df.set_index("date").sort_index()
df.columns = ["Open", "High", "Low", "Close"]
lo = df["Low"].to_numpy(float)
cl = df["Close"].to_numpy(float)
op = df["Open"].to_numpy(float)
hi = df["High"].to_numpy(float)
n = len(df)
idx = df.index


def bi(d: str) -> int:
    ts = pd.Timestamp(d)
    if ts in idx:
        return int(idx.get_loc(ts))
    # nearest on/after
    pos = int(idx.searchsorted(ts))
    if pos >= len(idx):
        raise KeyError(d)
    return pos


zl, zh = 11.82, 12.18
exit_bar = bi("2019-02-20")
resume = exit_bar + 1
apr24 = bi("2019-04-24")
apr25 = bi("2019-04-25")

print("exit", idx[exit_bar].date(), "resume", idx[resume].date(), "resume_bar", resume)
print(
    "apr24",
    apr24,
    idx[apr24].date(),
    "OHLC",
    op[apr24],
    hi[apr24],
    lo[apr24],
    cl[apr24],
)
print(
    "apr25",
    apr25,
    idx[apr25].date(),
    "OHLC",
    op[apr25],
    hi[apr25],
    lo[apr25],
    cl[apr25],
)

print("\n=== Notable bars Feb21-Jun2019 (abandon/retest/Apr window) ===")
for i in range(resume, bi("2019-06-30") + 1):
    abandon = cl[i] < zl - 1e-9
    retest = lo[i] <= zh + 1e-9 and cl[i] > zh + 1e-9
    green = cl[i] > op[i] + 1e-12 and cl[i] > zh + 1e-9
    d = idx[i].date().isoformat()
    if abandon or retest or d in (
        "2019-04-23",
        "2019-04-24",
        "2019-04-25",
        "2019-04-26",
    ):
        print(
            f"{d} i={i} O={op[i]:.2f} H={hi[i]:.2f} L={lo[i]:.2f} C={cl[i]:.2f} "
            f"abandon={abandon} retest={retest} green_sig={green}"
        )

for mode in ("stop_looking", "keep_looking"):
    rt, sig, fill = find_wpbr_retest_and_signal(
        lo,
        cl,
        op,
        scan_start=resume,
        zone_lower=zl,
        zone_upper=zh,
        max_days_after_retest=2,
        n=n,
        stop_at=apr24,
        retest_mode=mode,
    )
    print(
        f"\nfind {mode} resume->apr24:",
        "rt",
        None if rt is None else str(idx[rt].date()),
        "sig",
        None if sig is None else str(idx[sig].date()),
        "fill",
        None if fill is None else str(idx[fill].date()),
    )

first_ab = None
for i in range(resume, n):
    if cl[i] < zl - 1e-9:
        first_ab = i
        break
print(
    "\nFIRST ABANDON after resume:",
    None if first_ab is None else f"{idx[first_ab].date()} C={cl[first_ab]:.2f} i={first_ab}",
)
if first_ab is not None:
    found = False
    for i in range(resume, first_ab):
        if lo[i] <= zh + 1e-9 and cl[i] > zh + 1e-9:
            print(
                "retest before abandon:",
                idx[i].date(),
                f"L={lo[i]:.2f} C={cl[i]:.2f}",
            )
            found = True
    if not found:
        print("NO retest between resume and first abandon -> stop_looking returns blank forever from this resume_scan_bar")

print("\n=== All L<=zh & C>zh bars Feb21-Jun2019 ===")
for i in range(resume, bi("2019-06-30") + 1):
    if lo[i] <= zh + 1e-9 and cl[i] > zh + 1e-9:
        prior_ok = cl[i - 1] >= zl - 1e-9
        print(
            f"{idx[i].date()} L={lo[i]:.2f} C={cl[i]:.2f} priorC={cl[i-1]:.2f} "
            f"prior_ok={prior_ok} green={cl[i] > op[i]}"
        )

w = df.loc["2019-02-21":"2019-05-31"]
print("\n=== Feb21-May31 vs zone ===")
print("min Low", float(w.Low.min()), "min Close", float(w.Close.min()), "max Close", float(w.Close.max()))
print("days Close < 11.82:", int((w.Close < 11.82).sum()))
print("days retest pattern:", int(((w.Low <= 12.18) & (w.Close > 12.18)).sum()))

# Compare successful SC zones: walk after first-trade exit
print("\n========== SUCCESSFUL SC CONTRAST ==========")
cases = [
    (
        "2020-10-28 SC",
        23.49,
        24.21,
        "2020-07-07",  # exit of first win on same zone
        "2020-10-27",  # signal
        "2020-10-28",  # fill
    ),
    (
        "2023-09-07 SC",
        16.20,
        16.70,
        "2023-03-15",
        "2023-09-06",
        "2023-09-07",
    ),
]
for name, zl2, zh2, exit_d, sig_d, fill_d in cases:
    eb = bi(exit_d)
    rs = eb + 1
    sb = bi(sig_d)
    print(f"\n--- {name} zone {zl2}-{zh2} exit {exit_d} resume {idx[rs].date()} ---")
    # first abandon / first retest after resume
    ab = None
    for i in range(rs, sb + 1):
        if cl[i] < zl2 - 1e-9:
            ab = i
            break
    print(
        "first abandon before/on signal:",
        None if ab is None else f"{idx[ab].date()} C={cl[ab]:.2f}",
    )
    rt, sig, fill = find_wpbr_retest_and_signal(
        lo,
        cl,
        op,
        scan_start=rs,
        zone_lower=zl2,
        zone_upper=zh2,
        max_days_after_retest=2,
        n=n,
        stop_at=sb,
        retest_mode="stop_looking",
    )
    print(
        "stop_looking @ signal day:",
        None if rt is None else str(idx[rt].date()),
        None if sig is None else str(idx[sig].date()),
        None if fill is None else str(idx[fill].date()),
        "expected fill",
        fill_d,
        "MATCH" if fill is not None and str(idx[fill].date()) == fill_d else "NO",
    )
    # also list intermediate retests that failed (would stick resume if signal skipped)
    print("retest-like bars resume->signal:")
    for i in range(rs, sb + 1):
        if lo[i] <= zh2 + 1e-9 and cl[i] > zh2 + 1e-9:
            green = cl[i] > op[i] + 1e-12 and cl[i] > zh2 + 1e-9
            print(f"  {idx[i].date()} L={lo[i]:.2f} C={cl[i]:.2f} green_sig={green}")

# First-opportunity precompute for 11.82 zone (already consumed)
print("\n=== First opportunity bars for 11.82 zone (precompute) ===")
# From zones CSV: RETEST 2260 SIGNAL 2261 FILL 2262
for label, d in [("retest", "2018-12-27"), ("signal", "2018-12-27"), ("fill", "2018-12-28")]:
    # resolve by bar indices from closed trade maturity
    pass
for i in (2260, 2261, 2262):
    if 0 <= i < n:
        print(i, idx[i].date(), f"O={op[i]:.2f} L={lo[i]:.2f} C={cl[i]:.2f}")

# Would Apr24 qualify as retest IF scan_start were somehow still open?
print("\n=== Apr24 standalone vs zone (not via resume) ===")
i = apr24
print(
    f"apr24 L<=zh={lo[i] <= zh} C>zh={cl[i] > zh} C<zl={cl[i] < zl} "
    f"green={cl[i] > op[i]} fill_open={op[apr25]:.2f}"
)

# After first purchase win, allow_second path: does price ever retest 11.82-12.18 again with rocket?
print("\n=== Any later stop_looking success if resume advanced past abandon? ===")
# Simulate advancing resume past each abandon/failed window like keep_looking would
scan = resume
found_any = []
while scan < bi("2020-01-01"):
    rt, sig, fill = find_wpbr_retest_and_signal(
        lo,
        cl,
        op,
        scan_start=scan,
        zone_lower=zl,
        zone_upper=zh,
        max_days_after_retest=2,
        n=n,
        stop_at=None,
        retest_mode="stop_looking",
    )
    if rt is None:
        # abandon or nothing: find abandon bar to jump past
        jumped = False
        for i in range(scan, n):
            if cl[i] < zl - 1e-9:
                scan = i + 1
                jumped = True
                break
        if not jumped:
            break
        continue
    if sig is not None and fill is not None:
        found_any.append((str(idx[rt].date()), str(idx[sig].date()), str(idx[fill].date())))
        scan = sig + 1
    else:
        # failed retest window — engine does NOT advance; show stuck behavior
        print(
            "STUCK on failed retest",
            idx[rt].date(),
            "no signal in window; engine leaves resume_scan_bar unchanged",
        )
        scan = rt + 1  # hypothetical advance for exploration only
print("hypothetical SC fills if abandon windows were skipped:", found_any[:10])
