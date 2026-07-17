import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

def plot_rocket_launcher_trades(symbol):
    # 1. Load Data
    df = pd.read_csv(f"data\AU.csv")
    df.columns = [c.upper() for c in df.columns]
    df['DATE'] = pd.to_datetime(df['DATE'])
    df = df.sort_values('DATE')

    # 2. Calculate Indicators (Matching your AWK logic)
    df['SMA50'] = df['CLOSE'].rolling(window=50).mean()
    df['SMA100'] = df['CLOSE'].rolling(window=100).mean()
    # Your target is anchored to the SMA50
    df['TARGET_ZONE'] = df['SMA50'] * 1.20 

    # 3. Load Trades
    trades = pd.read_csv("RL_Closed.csv")
    symbol_trades = trades[trades['SYMBOL'] == symbol].copy()
    symbol_trades['DATE OPENED'] = pd.to_datetime(symbol_trades['DATE OPENED'], format='%Y%m%d')
    symbol_trades['DATE CLOSED'] = pd.to_datetime(symbol_trades['DATE CLOSED'], format='%Y%m%d')

    # 4. Setup Plot
    fig, ax = plt.subplots(figsize=(16, 9))
    
    # Plot SMA Lines
    ax.plot(df.DATE, df.SMA50, label='50-day SMA', color='orange', alpha=0.8, lw=1.5)
    ax.plot(df.DATE, df.SMA100, label='100-day SMA', color='red', alpha=0.8, lw=1.5)
    
    # Plot Target Zone (dashed)
    ax.plot(df.DATE, df.TARGET_ZONE, label='20% Profit Target', color='green', linestyle='--', alpha=0.4)
    
    # Fill the "Rocket Zone" (Space between SMA50 and Target)
    ax.fill_between(df.DATE, df.SMA50, df.TARGET_ZONE, color='green', alpha=0.05, label='Optimal Profit Zone')

    # Candlestick Logic (Simplified for clarity)
    ax.vlines(df.DATE, df.LOW, df.HIGH, color='black', lw=0.5)
    
    # Plot BUY/SELL Markers
    for i, trade in symbol_trades.iterrows():
        # BUY Marker
        ax.scatter(trade['DATE OPENED'], trade['ENTRY PRICE'], color='green', marker='^', s=100, label='Entry' if i == 0 else "")
        # SELL Marker
        ax.scatter(trade['DATE CLOSED'], trade['EXIT PRICE'], color='red', marker='v', s=100, label='Exit' if i == 0 else "")
        
        # Connect Entry and Exit with a line to show the "flight"
        ax.plot([trade['DATE OPENED'], trade['DATE CLOSED']], [trade['ENTRY PRICE'], trade['EXIT PRICE']], 
                color='blue', linestyle=':', alpha=0.3)

    # Final Formatting
    ax.set_title(f"Rocket Launcher Execution Map: {symbol}", fontsize=16, fontweight='bold')
    ax.set_ylabel("Price ($)")
    ax.legend(loc='upper left')
    ax.grid(True, alpha=0.2)
    
    # Zoom to Trade activity
    if not symbol_trades.empty:
        ax.set_xlim(symbol_trades['DATE OPENED'].min() - pd.Timedelta(days=60), 
                    symbol_trades['DATE CLOSED'].max() + pd.Timedelta(days=60))

    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()

# Execution
plot_rocket_launcher_trades("AU")