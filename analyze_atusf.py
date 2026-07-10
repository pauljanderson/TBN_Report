import pandas as pd
import sys

# Load price data
df = pd.read_csv(r'C:\Users\songg\Downloads\stockresearch\data\newdata\data\ATUSF.csv')

# Get trigger date from command line or default
trigger_date_str = sys.argv[1] if len(sys.argv) > 1 else '2022-05-13'
trigger_low_price = float(sys.argv[2]) if len(sys.argv) > 2 else None

# Find the trigger date and lookback window
trigger_idx = df[df['Date'] == trigger_date_str].index[0]
lookback_start_idx = trigger_idx - 503  # 504 bars

print(f'=== ATUSF {trigger_date_str} Trigger Analysis ===')
print(f'Trigger date: {trigger_date_str} (bar {trigger_idx})')
print(f'Lookback window: {df.iloc[lookback_start_idx]["Date"]} to {trigger_date_str}')
print()

# Zone band around trigger price - use provided or detect from Low
if trigger_low_price is None:
    trigger_low = df[df['Date'] == trigger_date_str]['Low'].values[0]
else:
    trigger_low = trigger_low_price
band_pct = 0.02
zone_lower = trigger_low * (1 - band_pct)
zone_upper = trigger_low * (1 + band_pct)
print(f'Zone center (Low on trigger day): ${trigger_low:.2f}')
print(f'Zone band (+-2%): ${zone_lower:.2f} to ${zone_upper:.2f}')
print()

# Load pivots and find those in zone band within lookback
pivots = pd.read_csv(r'C:\Users\songg\Downloads\stockresearch\Drive\BRT_Pivots_260311123606.csv', header=None, low_memory=False)
pivots.columns = ['Symbol', 'Date', 'Type', 'Price', 'Class']
atusf_pivots = pivots[pivots['Symbol'] == 'ATUSF'].copy()
atusf_pivots['Date'] = pd.to_datetime(atusf_pivots['Date'])
atusf_pivots['Price'] = pd.to_numeric(atusf_pivots['Price'], errors='coerce')

lookback_start_date = pd.to_datetime(df.iloc[lookback_start_idx]['Date'])
trigger_date = pd.to_datetime('2021-03-03')

# Filter pivots in lookback window
in_window = atusf_pivots[(atusf_pivots['Date'] >= lookback_start_date) & (atusf_pivots['Date'] <= trigger_date)]

# Filter pivots in zone band
in_zone = in_window[(in_window['Price'] >= zone_lower) & (in_window['Price'] <= zone_upper)]

print('=== Pivots in Zone Band During Lookback ===')
print(f'(Zone: ${zone_lower:.2f} - ${zone_upper:.2f})')
print()
for _, row in in_zone.iterrows():
    print(f"{row['Date'].strftime('%Y-%m-%d')}: {row['Type']} @ ${row['Price']:.2f} ({row['Class']})")

print()
print(f'Total pivots in zone: {len(in_zone)}')
print(f'MAJOR pivots in zone: {len(in_zone[in_zone["Class"] == "MAJOR"])}')
print(f'MINOR pivots in zone: {len(in_zone[in_zone["Class"] == "MINOR"])}')

print()
print('=== Price Data Around Trigger ===')
for i in range(trigger_idx - 5, trigger_idx + 3):
    row = df.iloc[i]
    marker = ' <-- TRIGGER' if df.iloc[i]['Date'] == trigger_date_str else ''
    bullish = ' (C>O)' if row['Close'] > row['Open'] else ''
    print(f"{row['Date']}: O={row['Open']:.2f} H={row['High']:.2f} L={row['Low']:.2f} C={row['Close']:.2f}{bullish}{marker}")

# Check growth filter (756 trading days back)
growth_bars = 756
if trigger_idx >= growth_bars:
    price_now = df.iloc[trigger_idx]['Close']
    price_ago = df.iloc[trigger_idx - growth_bars]['Close']
    growth_pct = (price_now - price_ago) / price_ago * 100
    growth_date = df.iloc[trigger_idx - growth_bars]['Date']
    growth_pass = price_now > price_ago
    print()
    print('=== Growth Filter (756 bars) ===')
    print(f'Price on {trigger_date_str}: ${price_now:.2f}')
    print(f'Price on {growth_date} (756 bars ago): ${price_ago:.2f}')
    print(f'Growth: {growth_pct:.1f}%')
    print(f'Growth filter PASS: {growth_pass}')

# Check tight range (105 bars)
tight_range_lookback = 105
if trigger_idx >= tight_range_lookback:
    start_idx = trigger_idx - tight_range_lookback + 1
    window_high = df.iloc[start_idx:trigger_idx+1]['High'].max()
    window_low = df.iloc[start_idx:trigger_idx+1]['Low'].min()
    range_pct = (window_high / window_low) - 1
    tight_range_threshold = 0.35
    tight_range_pass = range_pct > tight_range_threshold
    print()
    print(f'=== Tight Range Filter ({tight_range_lookback} bars) ===')
    print(f'Window: {df.iloc[start_idx]["Date"]} to {trigger_date_str}')
    print(f'High: ${window_high:.2f}, Low: ${window_low:.2f}')
    print(f'Range: {range_pct:.1%} (threshold: {tight_range_threshold:.0%})')
    print(f'Tight range filter PASS: {tight_range_pass}')
