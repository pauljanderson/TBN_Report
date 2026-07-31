"""Attribute every RS_BREAKDOWN_EXIT to its trigger leg, and measure the signal base rate per bar."""
import os, sys, collections
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stock_analysis'))
import rocket_brt as R
from brt_entry_indicators import build_entry_indicator_precompute, _ensure_gate_arrays

DATA = os.path.join('data', 'newdata', 'data')
spy = R.load_csv(os.path.join(DATA, 'SPY.csv'))

plus = pd.read_csv('drive/RS_Closed_260724133459.csv', low_memory=False)
bd = plus[plus.EXIT_TYPE == 'RS_BREAKDOWN_EXIT'].copy()

legs = collections.Counter()
base = collections.Counter()
missing = 0
checked = 0
fails = []

for sym, g in bd.groupby('SYMBOL'):
    p = os.path.join(DATA, f'{sym}.csv')
    if not os.path.exists(p):
        missing += len(g); continue
    df = R.load_csv(p)
    idx = pd.DatetimeIndex(pd.to_datetime(df.index)).strftime('%Y%m%d').tolist()
    pos = {d: i for i, d in enumerate(idx)}
    st, sp = R._align_stock_spy_close_for_rs(df, spy)
    pre = build_entry_indicator_precompute(df, symbol=sym, cache_dir=None, use_cache=True)
    if pre is None:
        missing += len(g); continue
    pre = _ensure_gate_arrays(pre)
    ts, ti, tl = pre.tc_short_sum, pre.tc_int_sum, pre.tc_long_sum

    # base rate over all bars with >=756 history (so all 3 horizons known)
    for t in range(756, len(idx)):
        e1, e2, e3 = R._rs_excess_pct_points(st, sp, t)
        spy_leg = (e1 is not None and e1 < 0) or (e2 is not None and e2 < 0) or (e3 is not None and e3 < 0)
        tc_leg = not (int(ts[t]) > 0 and int(ti[t]) > 0 and int(tl[t]) > 0)
        base['bars'] += 1
        if spy_leg: base['spy_leg'] += 1
        if tc_leg: base['tc_leg'] += 1
        if tc_leg and not spy_leg: base['tc_only'] += 1
        if int(ts[t]) <= 0: base['tc_short_le0'] += 1
        if int(ti[t]) <= 0: base['tc_int_le0'] += 1
        if int(tl[t]) <= 0: base['tc_long_le0'] += 1
        if int(ts[t]) == 0: base['tc_short_eq0'] += 1

    for d in g['DATE_CLOSED']:
        i = pos.get(str(d).replace('-', '')[:8])
        if i is None or i < 1:
            missing += 1; continue
        t = i - 1
        checked += 1
        e1, e2, e3 = R._rs_excess_pct_points(st, sp, t)
        spy_leg = (e1 is not None and e1 < 0) or (e2 is not None and e2 < 0) or (e3 is not None and e3 < 0)
        tc_leg = not (int(ts[t]) > 0 and int(ti[t]) > 0 and int(tl[t]) > 0)
        if not (spy_leg or tc_leg):
            fails.append((sym, d)); continue
        if spy_leg and tc_leg: legs['both'] += 1
        elif spy_leg: legs['spy_only'] += 1
        else: legs['tc_only'] += 1
        if tc_leg:
            if int(ts[t]) <= 0: legs['tc_short_le0'] += 1
            if int(ti[t]) <= 0: legs['tc_int_le0'] += 1
            if int(tl[t]) <= 0: legs['tc_long_le0'] += 1
            if int(ts[t]) == 0: legs['tc_short_exactly0'] += 1

print(f'breakdown exits checked={checked} unresolved(no signal found)={len(fails)} skipped={missing}')
print('\n--- trigger leg attribution (of verified exits) ---')
tot = sum(legs[k] for k in ('both', 'spy_only', 'tc_only'))
for k in ('tc_only', 'spy_only', 'both'):
    print(f'  {k:10s} {legs[k]:7d} ({100*legs[k]/max(tot,1):5.1f}%)')
print('  horizon detail (TC leg firing):')
for k in ('tc_short_le0', 'tc_int_le0', 'tc_long_le0', 'tc_short_exactly0'):
    print(f'    {k:20s} {legs[k]:7d}')
print('\n--- per-bar base rate (all bars >=756 history, plus-run symbols) ---')
b = base['bars']
for k in ('spy_leg', 'tc_leg', 'tc_only', 'tc_short_le0', 'tc_int_le0', 'tc_long_le0', 'tc_short_eq0'):
    print(f'  {k:16s} {base[k]:8d} / {b} = {100*base[k]/max(b,1):5.1f}%')
if fails[:10]:
    print('\nunresolved samples:', fails[:10])
