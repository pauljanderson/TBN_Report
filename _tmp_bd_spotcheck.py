"""Spot-check RS_BREAKDOWN_EXIT trades: recompute the breakdown signal on the prior bar."""
import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stock_analysis'))
import rocket_brt as R
from brt_entry_indicators import build_entry_indicator_precompute, _ensure_gate_arrays

DATA = r'data\newdata\data'

def load(sym):
    for ext in ('.csv',):
        p = os.path.join(DATA, sym + ext)
        if os.path.exists(p):
            return R.load_csv(p)
    raise FileNotFoundError(sym)

spy = load('SPY')

def pre_for(sym, df):
    pre = build_entry_indicator_precompute(df, symbol=sym, cache_dir=None, use_cache=True)
    if pre is not None:
        pre = _ensure_gate_arrays(pre)
    return pre

def analyze(sym, want_dates=None, closed=None):
    df = load(sym)
    n = len(df)
    idx = pd.DatetimeIndex(pd.to_datetime(df.index)).strftime('%Y%m%d').tolist()
    st, sp = R._align_stock_spy_close_for_rs(df, spy)
    pre = pre_for(sym, df)
    ts, ti, tl = pre.tc_short_sum, pre.tc_int_sum, pre.tc_long_sum
    pos = {d: i for i, d in enumerate(idx)}
    out = []
    for d in (want_dates or []):
        d8 = str(d).replace('-', '')[:8]
        i = pos.get(d8)
        if i is None:
            out.append((d8, 'NO_BAR', None)); continue
        sig = i - 1  # signal bar = prior session close; exit at this bar's open
        e1, e2, e3 = R._rs_excess_pct_points(st, sp, sig)
        bd = R._rs_breakdown_signal_at_bar(st, sp, pre, sig)
        entry_ok = R._rs_pass_all_horizons_vs_spy(st, sp, sig) and R._rs_tc_outlook_all_strong(pre, sig)
        out.append(dict(
            exit_date=d8, signal_date=idx[sig], bd_signal=bd, entry_cond_still_true=entry_ok,
            e1=None if e1 is None else round(e1, 2),
            e2=None if e2 is None else round(e2, 2),
            e3=None if e3 is None else round(e3, 2),
            tc_short=int(ts[sig]), tc_int=int(ti[sig]), tc_long=int(tl[sig]),
            spy_leg=bool((e1 is not None and e1 < 0) or (e2 is not None and e2 < 0) or (e3 is not None and e3 < 0)),
            tc_leg=not (int(ts[sig]) > 0 and int(ti[sig]) > 0 and int(tl[sig]) > 0),
        ))
    return out, (df, idx, st, sp, pre)


if __name__ == '__main__':
    plus = pd.read_csv('drive/RS_Closed_260724133459.csv', low_memory=False)
    bd = plus[plus.EXIT_TYPE == 'RS_BREAKDOWN_EXIT']
    # pick a spread of symbols, prefer longer holds so it's not trivially bar-2
    bd = bd.copy()
    bd['DAYS_HELD'] = pd.to_numeric(bd['DAYS_HELD'], errors='coerce')
    picks = []
    for sym in ['NVDA', 'AAPL', 'COST', 'NFLX', 'MSFT']:
        s = bd[bd.SYMBOL == sym].sort_values('DAYS_HELD', ascending=False)
        if len(s):
            picks.append((sym, s.head(3)))
    ok = bad = 0
    for sym, rows in picks:
        dates = [str(x)[:10] for x in rows['DATE_CLOSED'].tolist()]
        res, _ = analyze(sym, dates)
        print(f'=== {sym} ===')
        for r, (_, tr) in zip(res, rows.iterrows()):
            if not isinstance(r, dict):
                print('  ', r); continue
            flag = 'OK ' if r['bd_signal'] else 'FAIL'
            if r['bd_signal']:
                ok += 1
            else:
                bad += 1
            why = []
            if r['spy_leg']:
                why.append('SPY_COMPARE<0')
            if r['tc_leg']:
                why.append('TC not Strong')
            print(f"  {flag} entry {str(tr['DATE_OPENED'])[:10]} -> exit {r['exit_date']} (signal {r['signal_date']}, held {tr['DAYS_HELD']:.0f}d, pnl {tr['PNL_PCT']}) "
                  f"e1={r['e1']} e2={r['e2']} e3={r['e3']} TC(s/i/l)={r['tc_short']}/{r['tc_int']}/{r['tc_long']} -> {' + '.join(why) or 'NONE'}")
    print(f'\nverified breakdown-signal-present: {ok} ok / {bad} fail')

    # Sanity: exhaustive check over a sample of all breakdown exits across symbols
    print('\n=== bulk verification (200 random breakdown exits) ===')
    samp = bd.sample(n=min(200, len(bd)), random_state=7)
    per_sym = {}
    fails = []
    checked = 0
    for sym, g in samp.groupby('SYMBOL'):
        try:
            res, _ = analyze(sym, [str(x)[:10] for x in g['DATE_CLOSED'].tolist()])
        except Exception as e:
            print('  skip', sym, e); continue
        for r in res:
            if not isinstance(r, dict):
                continue
            checked += 1
            if not r['bd_signal']:
                fails.append((sym, r))
    print(f'  checked={checked} fails={len(fails)}')
    for sym, r in fails[:10]:
        print('   FAIL', sym, r)
