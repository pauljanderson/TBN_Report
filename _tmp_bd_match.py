"""Find matching entries between off and plus, and show earlier exit under plus."""
import pandas as pd

off = pd.read_csv('drive/RS_Closed_260724133554.csv', low_memory=False)
plus = pd.read_csv('drive/RS_Closed_260724133459.csv', low_memory=False)

# normalize keys
for d in (off, plus):
    d['DATE_OPENED'] = d['DATE_OPENED'].astype(str).str.replace('-', '').str[:8]
    d['DATE_CLOSED'] = d['DATE_CLOSED'].astype(str).str.replace('-', '').str[:8]

# only+off both had min_spy=40, so entries for only/off should mostly match.
# Plus had min_spy=0, so more entries; for matched entries, compare exit.

m = off.merge(plus, on=['SYMBOL','DATE_OPENED'], suffixes=('_off','_plus'), how='inner')
print(f'off trades={len(off)} plus={len(plus)} matched_same_entry={len(m)}')
m['DAYS_off'] = pd.to_numeric(m['DAYS_HELD_off'], errors='coerce')
m['DAYS_plus'] = pd.to_numeric(m['DAYS_HELD_plus'], errors='coerce')
m['earlier'] = m['DATE_CLOSED_plus'] < m['DATE_CLOSED_off']
m['same'] = m['DATE_CLOSED_plus'] == m['DATE_CLOSED_off']
m['later'] = m['DATE_CLOSED_plus'] > m['DATE_CLOSED_off']
print(f'  plus exited earlier: {m.earlier.sum()}  same day: {m.same.sum()}  later: {m.later.sum()}')
print(f'  avg days off={m.DAYS_off.mean():.1f}  plus={m.DAYS_plus.mean():.1f}')
print(f'  median days off={m.DAYS_off.median():.1f}  plus={m.DAYS_plus.median():.1f}')

# Show a few concrete long-held off trades that exited earlier under plus via breakdown
long = m[(m.earlier) & (m.EXIT_TYPE_plus == 'RS_BREAKDOWN_EXIT')].sort_values('DAYS_off', ascending=False).head(8)
print('\n--- long-held OFF trades that exited earlier under PLUS via breakdown ---')
cols = ['SYMBOL','DATE_OPENED','DATE_CLOSED_off','EXIT_TYPE_off','DAYS_off','PNL_PCT_off',
        'DATE_CLOSED_plus','EXIT_TYPE_plus','DAYS_plus','PNL_PCT_plus']
print(long[cols].to_string(index=False))

# also show how many unique entry dates per symbol for each mode (slot recycle proxy)
print('\n--- trades per symbol (top 10 by plus count) ---')
c = plus.groupby('SYMBOL').size().sort_values(ascending=False).head(10)
c2 = off.groupby('SYMBOL').size().reindex(c.index).fillna(0).astype(int)
print(pd.DataFrame({'plus':c, 'off':c2}))
