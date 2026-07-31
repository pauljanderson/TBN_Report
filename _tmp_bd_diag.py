import csv, collections, sys
import pandas as pd

stamps = {
    'plus': '260724133459',
    'only': '260724133531',
    'off':  '260724133554',
}

# --- 1. diff Report params ---
rows = {}
for k, s in stamps.items():
    with open(f'drive/RS_Report_{s}.csv', newline='', encoding='utf-8') as f:
        r = list(csv.reader(f))
    hdr, val = r[0], r[1]
    rows[k] = dict(zip(hdr, val))

hdr_keys = list(rows['plus'].keys())
print('=== PARAM DIFFS (plus | only | off) ===')
for key in hdr_keys:
    vals = [rows[k].get(key) for k in ('plus','only','off')]
    if len(set(vals)) > 1:
        print(f'{key:45s} {vals[0]:>22s} | {vals[1]:>22s} | {vals[2]:>22s}')

print()
metrics = ['Total_Trades','Total_PNL','Profit_Factor','Pct_Wins','Avg_Win_Pct','Avg_Loss_Pct','Avg_PNL_Pct',
           'Avg_Days_Held','Median_Days_Held','P90_Days','Max_DD','Ann_ROR','Max_Positions','Score',
           'Aggressive_Total_PNL','Aggressive_Max_DD','Aggressive_Avg_Positions','brt_cash','initial_capital',
           'Capital_Days','Profit_Per_Capital_Day','sell_breakdown']
print('=== KEY METRICS ===')
print(f"{'metric':32s} {'plus':>16s} {'only':>16s} {'off':>16s}")
for m in metrics:
    print(f"{m:32s} {rows['plus'].get(m,''):>16s} {rows['only'].get(m,''):>16s} {rows['off'].get(m,''):>16s}")

# --- 2. exit type histograms ---
print()
for k, s in stamps.items():
    df = pd.read_csv(f'drive/RS_Closed_{s}.csv', low_memory=False)
    print(f'--- {k} ({s}) rows={len(df)} symbols={df["Symbol"].nunique() if "Symbol" in df else "?"} ---')
    col = None
    for c in ('EXIT_TYPE','Exit_Type','exit_type','Exit Type'):
        if c in df.columns:
            col = c; break
    if col is None:
        print('  columns:', list(df.columns)[:60])
    else:
        vc = df[col].fillna('<NA>').value_counts()
        for kk, vv in vc.items():
            sub = df[df[col].fillna('<NA)')==kk] if False else df[df[col].fillna('<NA>')==kk]
            pnl = sub['PNL'].sum() if 'PNL' in sub else float('nan')
            days = sub['Days_Held'].mean() if 'Days_Held' in sub else float('nan')
            print(f'  {kk:28s} n={vv:6d} ({100*vv/len(df):5.1f}%)  pnl={pnl:14.0f}  avgdays={days:7.1f}')
    if k == 'plus':
        print('  closed columns:', list(df.columns))
