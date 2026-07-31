"""Deep-dive one concrete example: FUNC 20130621 entry under off vs plus."""
import os, sys
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stock_analysis'))
import rocket_brt as R
from brt_entry_indicators import build_entry_indicator_precompute, _ensure_gate_arrays

DATA = os.path.join('data','newdata','data')
spy = R.load_csv(os.path.join(DATA,'SPY.csv'))
df = R.load_csv(os.path.join(DATA,'FUNC.csv'))
idx = pd.DatetimeIndex(pd.to_datetime(df.index)).strftime('%Y%m%d').tolist()
pos = {d:i for i,d in enumerate(idx)}
st, sp = R._align_stock_spy_close_for_rs(df, spy)
pre = _ensure_gate_arrays(build_entry_indicator_precompute(df, symbol='FUNC', cache_dir=None, use_cache=True))

# Entry 20130621 (open) => signal bar was prior day 20130620
entry = '20130621'
exit_plus = '20130626'
i_entry = pos[entry]
i_exit = pos[exit_plus]
print(f'FUNC entry bar {entry} i={i_entry} open={df.Open.iloc[i_entry]:.4f}')
print(f'FUNC plus exit bar {exit_plus} i={i_exit} open={df.Open.iloc[i_exit]:.4f}')
print(f'  signal for exit = prior bar {idx[i_exit-1]}')

# Walk from entry+1 to exit and show when BD first armed
print('\nBar-by-bar after entry (until plus exit):')
for i in range(i_entry, i_exit+1):
    t = i  # evaluating at close of bar i for arming
    e1,e2,e3 = R._rs_excess_pct_points(st, sp, t)
    ts,ti,tl = int(pre.tc_short_sum[t]), int(pre.tc_int_sum[t]), int(pre.tc_long_sum[t])
    bd = R._rs_breakdown_signal_at_bar(st, sp, pre, t)
    note = ''
    if i == i_entry:
        note = 'ENTRY BAR (no arm/exit)'
    elif i == i_exit-1:
        note = 'SIGNAL BAR that arms pending'
    elif i == i_exit:
        note = 'EXIT OPEN'
    print(f'  {idx[i]} close={df.Close.iloc[i]:.3f} e1={None if e1 is None else round(e1,2)} '
          f'TC={ts}/{ti}/{tl} bd={bd} {note}')

# Also NVDA example that was TC-only
print('\n=== NVDA 20230224 entry / 20230406 exit ===')
df2 = R.load_csv(os.path.join(DATA,'NVDA.csv'))
idx2 = pd.DatetimeIndex(pd.to_datetime(df2.index)).strftime('%Y%m%d').tolist()
pos2 = {d:i for i,d in enumerate(idx2)}
st2, sp2 = R._align_stock_spy_close_for_rs(df2, spy)
pre2 = _ensure_gate_arrays(build_entry_indicator_precompute(df2, symbol='NVDA', cache_dir=None, use_cache=True))
i_ex = pos2['20230406']
t = i_ex - 1
e1,e2,e3 = R._rs_excess_pct_points(st2, sp2, t)
print(f'  signal {idx2[t]} e1={e1:.2f} e2={e2:.2f} e3={e3:.2f} '
      f'TC={int(pre2.tc_short_sum[t])}/{int(pre2.tc_int_sum[t])}/{int(pre2.tc_long_sum[t])} '
      f'bd={R._rs_breakdown_signal_at_bar(st2,sp2,pre2,t)}')
