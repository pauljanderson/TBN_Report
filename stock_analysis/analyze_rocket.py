import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# --- CONFIGURATION ---
FILE_PATH = 'drive/RL_Closed_260208080649.csv'
STARTING_CAPITAL = 516000.00  # Adjust based on your actual bankroll
PER_TRADE_CASH = 47500.00

# 1. Load and Clean Data
df = pd.read_csv(FILE_PATH)
# Convert "29.93%" or "29.93" to decimal 0.2993
df['PNL_decimal'] = df['PNL %'].str.replace('%', '').astype(float) / 100
df['DATE CLOSED'] = pd.to_datetime(df['DATE CLOSED'], format='%Y%m%d')
df = df.sort_values('DATE CLOSED')

# 2. Equity Curve Math
df['Trade_Profit'] = df['PNL_decimal'] * PER_TRADE_CASH
df['Equity'] = STARTING_CAPITAL + df['Trade_Profit'].cumsum()
df['Peak'] = df['Equity'].cummax()
df['Drawdown_Pct'] = ((df['Peak'] - df['Equity']) / df['Peak']) * 100

# 3. Calculate Metrics
total_ret = (df['Equity'].iloc[-1] - STARTING_CAPITAL) / STARTING_CAPITAL
years = (df['DATE CLOSED'].max() - df['DATE CLOSED'].min()).days / 365.25
cagr = (1 + total_ret)**(1/years) - 1

# Sharpe/Sortino (Daily resampled)
daily = df.set_index('DATE CLOSED')['Trade_Profit'].resample('D').sum() / STARTING_CAPITAL
sharpe = (daily.mean() / daily.std()) * np.sqrt(252)
downside_std = daily[daily < 0].std()
sortino = (daily.mean() / downside_std) * np.sqrt(252)

# 4. Visualization
plt.figure(figsize=(12, 6))
plt.plot(df['DATE CLOSED'], df['Equity'], label=f'Rocket Launcher (CAGR: {cagr:.1%})', color='#007acc', lw=2)
plt.fill_between(df['DATE CLOSED'], STARTING_CAPITAL, df['Equity'], alpha=0.1, color='#007acc')
plt.title('Portfolio Equity Curve: The Rocket Launcher')
plt.ylabel('Account Value ($)')
plt.grid(True, alpha=0.3)
plt.legend()
plt.savefig('rocket_equity_curve.png')
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), sharex=True, gridspec_kw={'height_ratios': [3, 1]})

# Plot 1: Equity
ax1.plot(df['DATE CLOSED'], df['Equity'], color='#007acc', lw=2)
ax1.set_title('Portfolio Equity Curve')

# Plot 2: Drawdown
ax2.fill_between(df['DATE CLOSED'], 0, -df['Drawdown_Pct'], color='red', alpha=0.3)
ax2.set_ylabel('Drawdown %')
plt.savefig('equity_drawdown_analysis.png')

print(f"--- PERFORMANCE REPORT ---")
print(f"Total Return: {total_ret:.2%}")
print(f"CAGR:         {cagr:.2%}")
print(f"Sharpe:       {sharpe:.2f}")
print(f"Sortino:      {sortino:.2f}")
print(f"Final Equity: ${df['Equity'].iloc[-1]:,.2f}")