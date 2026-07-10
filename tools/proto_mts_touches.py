"""Prototype: reproduce the STONK_DATA sheet pivot -> strong -> Touch Price (AF)
pipeline EXACTLY, and validate against the NVDA ground-truth matured touches.

Sheet formulas (column letters -> local names):
  J Local High Test = High[i] == MAX(High[i-lw : i+lw])
  K Future move (high) = (MIN(Low[i+1:i+fw]) / High[i] - 1) <= -fm
  L No dup Pivot High = no prior FinalPivotHigh in [i-lw, i-1] with PivotHighPrice within +/-dedup of High[i]
  M Not also Pivot Low = NOT(localLow[i] AND futureMoveLow[i] AND noDupLow[i])
  N Final Pivot High = J AND K AND L AND M
  AD Pre-strong High = FinalPivotHigh AND (High[i]/MIN(Low[i-pre:i-1]) - 1) >= pre_pct
  AF Touch (high) = FinalPivotHigh AND AD AND (1 - MIN(Low[i+1:i+post])/High[i]) >= post_pct  -> High[i]
  (symmetric for lows)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "stock_analysis"))
sys.path.insert(0, str(_REPO / "tools"))
from rocket_brt import load_csv  # noqa: E402
from _nvda_matured_zone_gt import NVDA_MATURED_TOUCH as GT  # noqa: E402

# Sheet params (A1:C27)
LW = 4            # C23 pivot_local_window_bars (back & forward)
FW = 7            # future-move forward window (C14 periods=... hardcoded 7 in K)
FM = 0.06         # C21 pivot_future_move_pct
DEDUP = 0.01      # C22 pivot_dedup_tol_pct
PRE_BARS = 7      # C17
PRE_PCT = 0.12    # C18
POST_BARS = 7     # C14
POST_PCT = 0.09   # C15
BAND = 0.02       # C5


def compute(df, lw_back=LW, lw_fwd=LW, fw=FW):
    H = df["High"].to_numpy(float)
    L = df["Low"].to_numpy(float)
    n = len(H)

    def local_high(i):
        a = max(0, i - lw_back); b = min(n - 1, i + lw_fwd)
        return H[i] == H[a:b + 1].max()

    def local_low(i):
        a = max(0, i - lw_back); b = min(n - 1, i + lw_fwd)
        return L[i] == L[a:b + 1].min()

    def fut_move_high(i):
        if i + 1 >= n:
            return False
        b = min(n, i + fw + 1)
        return (L[i + 1:b].min() / H[i] - 1.0) <= -FM

    def fut_move_low(i):
        if i + 1 >= n:
            return False
        b = min(n, i + fw + 1)
        return (H[i + 1:b].max() / L[i] - 1.0) >= FM

    fph = np.zeros(n, bool)   # final pivot high
    fpl = np.zeros(n, bool)   # final pivot low
    php = np.full(n, np.nan)  # pivot high price
    plp = np.full(n, np.nan)  # pivot low price

    for i in range(n):
        if i <= 9:
            continue
        lh, ll = local_high(i), local_low(i)
        fmh, fml = fut_move_high(i), fut_move_low(i)
        # no-dup (references prior final pivots)
        ndh = True
        ndl = True
        lo = max(0, i - LW)
        for j in range(lo, i):
            if fph[j] and abs(php[j] - H[i]) <= H[i] * DEDUP:
                ndh = False
            if fpl[j] and abs(plp[j] - L[i]) <= L[i] * DEDUP:
                ndl = False
        # mutual exclusion
        not_also_low = not (ll and fml and ndl)
        not_also_high = not (lh and fmh and ndh)
        is_ph = lh and fmh and ndh and not_also_low
        is_pl = ll and fml and ndl and not_also_high
        if is_ph:
            fph[i] = True; php[i] = H[i]
        if is_pl:
            fpl[i] = True; plp[i] = L[i]

    touches = []  # (i, price)
    for i in range(n):
        if fph[i]:
            if i - PRE_BARS >= 0 and (H[i] / L[i - PRE_BARS:i].min() - 1.0) >= PRE_PCT:
                b = min(n, i + POST_BARS + 1)
                if i + 1 < n and (1.0 - L[i + 1:b].min() / H[i]) >= POST_PCT:
                    touches.append((i, H[i]))
        elif fpl[i]:
            if i - PRE_BARS >= 0 and (1.0 - L[i] / H[i - PRE_BARS:i].max()) >= PRE_PCT:
                b = min(n, i + POST_BARS + 1)
                if i + 1 < n and (H[i + 1:b].max() / L[i] - 1.0) >= POST_PCT:
                    touches.append((i, L[i]))
    return touches


def score(vals, gt, tol=0.02):
    rem = list(vals); matched = 0; missing = []
    for g in gt:
        best = None
        for e in rem:
            if abs(e - g) <= max(tol, g * tol) and (best is None or abs(e - g) < abs(best - g)):
                best = e
        if best is not None:
            rem.remove(best); matched += 1
        else:
            missing.append(g)
    return matched, missing, rem


def main():
    df = load_csv(str(_REPO / "data" / "newdata" / "data" / "NVDA.csv"))
    print("grid (lw_back, lw_fwd, fw) -> matched/extra/missing:")
    for lb in (4,):
        for lf in (4, 5, 6, 7):
            for fw in (5, 6, 7, 8, 9, 10):
                t = compute(df, lb, lf, fw)
                v = [round(x, 2) for _, x in t]
                m, miss, ex = score(v, GT)
                if m >= 104:
                    print(f"  lw_back={lb} lw_fwd={lf} fw={fw}: matched={m} missing={len(miss)} extra={len(ex)}")
    touches = compute(df)
    vals = [round(v, 2) for _, v in touches]
    m, miss, extra = score(vals, GT)
    print(f"proto touches={len(vals)}  sheet={len(GT)}  matched={m}  missing={len(miss)}  extra={len(extra)}")
    print("  MISSING:", miss)
    print("  EXTRA:", sorted(extra))
    dates = [str(d)[:10] for d in df.index]
    print("\n  first 12 proto touches:", [(dates[i], round(v, 2)) for i, v in touches[:12]])
    # Debug the extras: show date, side, and nearest kept touch in time.
    extra_set = set(round(x, 2) for x in extra)
    print("\n  EXTRA detail (date, price, prev_touch, next_touch):")
    for k, (i, v) in enumerate(touches):
        if round(v, 2) in extra_set:
            prv = touches[k - 1] if k > 0 else None
            nxt = touches[k + 1] if k + 1 < len(touches) else None
            print(f"    {dates[i]} ${round(v,2)}  prev={prv and (dates[prv[0]], round(prv[1],2))}  next={nxt and (dates[nxt[0]], round(nxt[1],2))}")


if __name__ == "__main__":
    main()
