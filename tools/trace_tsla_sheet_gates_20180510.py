#!/usr/bin/env python3
"""Simulate sheet pivot columns J-M (N=Final PH) for 2018-05-10."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock_analysis"))
from rocket_brt import _sheet_price_near, _round_zone_price  # noqa: E402

df = pd.read_csv(ROOT / "data/newdata/data/TSLA.csv", parse_dates=["Date"], index_col="Date")
hi = df["High"].values.astype(float)
lo = df["Low"].values.astype(float)
n = len(df)
W = 4
POST = 7
FUT = 0.06
DEDUP = 0.01
C17 = 7
C18 = 0.081
C14 = 7
C15 = 0.108


def j_local_high(t: int) -> bool:
    w0, w1 = max(0, t - W), min(n, t + W + 1)
    return bool(np.isclose(hi[t], np.max(hi[w0:w1]), rtol=0, atol=1e-6))


def k_post_pullback(t: int) -> bool:
    if t + POST >= n:
        return False
    return (np.min(lo[t + 1 : t + POST + 1]) / hi[t] - 1.0) <= -FUT


def l_no_dup_ph(t: int, pivot_high_label: np.ndarray, pivot_high_px: np.ndarray) -> bool:
    """Sheet L: no prior 'Pivot High' in N with T within 1% of F."""
    f = hi[t]
    w0 = max(1, t - W)  # MAX(2,ROW()-4) in 1-based → bar index t-W .. t-1
    for j in range(max(0, t - W), t):
        if pivot_high_label[j] and _sheet_price_near(pivot_high_px[j], f, DEDUP):
            return False
    return True


def m_not_also_pl(t: int, pivot_low_label: np.ndarray, pivot_low_px: np.ndarray) -> bool:
    """Sheet M: NOT( local low AND 6% future rise AND no dup PL in window )."""
    w0, w1 = max(0, t - W), min(n, t + W + 1)
    is_ll = bool(np.isclose(lo[t], np.min(lo[w0:w1]), rtol=0, atol=1e-6))
    if not is_ll or t + POST >= n:
        return True
    fut_max = float(np.max(hi[t + 1 : t + POST + 1]))
    rise = (fut_max / lo[t] - 1.0) >= FUT
    if not rise:
        return True
    for j in range(max(0, t - W), t):
        if pivot_low_label[j] and _sheet_price_near(pivot_low_px[j], lo[t], DEDUP):
            return True  # dup exists → inner AND false → M true
    return False  # also pivot low → M false


def ad_pre_strong(t: int, n_label: bool) -> bool:
    if not n_label:
        return False
    pre = lo[max(0, t - C17) : t]
    if pre.size == 0:
        return False
    return (hi[t] / float(np.min(pre)) - 1.0) >= C18


def touch_af(t: int, n_label: bool, ad: bool) -> float | None:
    if not (n_label and ad):
        return None
    if t + C14 >= n:
        return None
    pb = 1.0 - float(np.min(lo[t + 1 : t + C14 + 1])) / hi[t]
    if pb < C15:
        return None
    return _round_zone_price(hi[t], 2)


# Forward pass building N/S labels like sheet
pivot_high_label = np.zeros(n, dtype=bool)
pivot_low_label = np.zeros(n, dtype=bool)
pivot_high_px = np.full(n, np.nan)
pivot_low_px = np.full(n, np.nan)
final_n = np.zeros(n, dtype=bool)
touch = np.full(n, np.nan)

for t in range(9, n):
    J = j_local_high(t)
    K = k_post_pullback(t)
    L = l_no_dup_ph(t, pivot_high_label, pivot_high_px)
    M = m_not_also_pl(t, pivot_low_label, pivot_low_px)
    N = J and K and L and M
    final_n[t] = N
    if N:
        pivot_high_label[t] = True
        pivot_high_px[t] = hi[t]

    # pivot low side (simplified O-R mirror)
    w0, w1 = max(0, t - W), min(n, t + W + 1)
    O = bool(np.isclose(lo[t], np.min(lo[w0:w1]), rtol=0, atol=1e-6))
    P = (np.max(hi[t + 1 : t + POST + 1]) / lo[t] - 1.0) >= FUT if t + POST < n else False
    Q = True
    for j in range(max(0, t - W), t):
        if pivot_low_label[j] and _sheet_price_near(pivot_low_px[j], lo[t], DEDUP):
            Q = False
            break
    R = not (
        j_local_high(t)
        and k_post_pullback(t)
        and all(
            not (pivot_high_label[j] and _sheet_price_near(pivot_high_px[j], hi[t], DEDUP))
            for j in range(max(0, t - W), t)
        )
    )
    S = O and P and Q and R
    if S:
        pivot_low_label[t] = True
        pivot_low_px[t] = lo[t]

    ad = ad_pre_strong(t, N)
    tp = touch_af(t, N, ad)
    if tp is not None:
        touch[t] = tp

# Report May 2018
print("=== Sheet-style gate trace (Yahoo TSLA.csv) ===\n")
for d in pd.date_range("2018-04-25", "2018-05-15", freq="B"):
    if d not in df.index:
        continue
    t = df.index.get_loc(d)
    J = j_local_high(t)
    K = k_post_pullback(t)
    L = l_no_dup_ph(t, pivot_high_label, pivot_high_px)
    M = m_not_also_pl(t, pivot_low_label, pivot_low_px)
    N = final_n[t]
    ad = ad_pre_strong(t, N)
    tp = touch[t] if np.isfinite(touch[t]) else None
    print(
        f"{d.date()} H={hi[t]:.4f} L={lo[t]:.4f}  "
        f"J={J} K={K} L={L} M={M} -> N={N} AD={ad} TP={tp}"
    )

t = df.index.get_loc(pd.Timestamp("2018-05-10"))
print(f"\n=== 2018-05-10 M (Not also Pivot Low) detail ===")
w0, w1 = max(0, t - W), min(n, t + W + 1)
is_ll = bool(np.isclose(lo[t], np.min(lo[w0:w1]), rtol=0, atol=1e-6))
fut_max = float(np.max(hi[t + 1 : t + POST + 1]))
print(f"  local_low={is_ll}  future_rise={(fut_max/lo[t]-1)*100:.2f}%")
print(f"  M returns {m_not_also_pl(t, pivot_low_label, pivot_low_px)}")
