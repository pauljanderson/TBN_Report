import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib.lines import Line2D
import os

# --- CONFIGURATION ---
# Replace with your actual RL_Closed filename
CLOSED_TRADES_FILE = r"C:\Users\songg\Downloads\stockresearch\drive\RL_Closed_260207145958.csv" 
DATA_DIR = r"C:\Users\songg\Downloads\stockresearch\data\newdata\data"
OUTPUT_PLOT = "trade_behaviors_tri_color.png"

def clean_num(val):
    """Strips %, $, commas, and converts string to float."""
    if pd.isna(val): return 0
    if isinstance(val, (int, float)): return val
    cleaned = str(val).replace('%', '').replace('$', '').replace(',', '').strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0

def to_iso(d):
    """Standardizes dates to YYYYMMDD string format."""
    return str(d).replace("-", "").replace("/", "").strip()

def plot_trade_behaviors():
    # 1. Load the closed trades
    if not os.path.exists(CLOSED_TRADES_FILE):
        print(f"Error: {CLOSED_TRADES_FILE} not found. Check the path in the script.")
        return
    
    print("Loading closed trades...")
    df_closed = pd.read_csv(CLOSED_TRADES_FILE)
    
    # Clean numeric columns
    df_closed['PNL %'] = df_closed['PNL %'].apply(clean_num)
    df_closed['ENTRY PRICE'] = df_closed['ENTRY PRICE'].apply(clean_num)
    df_closed['DAYS HELD'] = df_closed['DAYS HELD'].apply(clean_num)

    # --- REMOVE THE OUTLIER ---
    # Finding the "massive" trade: max(PNL % * DAYS HELD)
    if not df_closed.empty:
        outlier_idx = (df_closed['PNL %'] * df_closed['DAYS HELD']).idxmax()
        outlier_sym = df_closed.loc[outlier_idx, 'SYMBOL']
        outlier_pnl = df_closed.loc[outlier_idx, 'PNL %']
        print(f"Removing the massive outlier: {outlier_sym} ({outlier_pnl:.2f}% over {df_closed.loc[outlier_idx, 'DAYS HELD']} days)")
        df_closed = df_closed.drop(outlier_idx)
    
    plt.figure(figsize=(14, 8))
    ax = plt.gca()
    
    trade_count = 0
    win_count = 0
    loss_count = 0
    be_count = 0

    # 2. Process each trade
    for index, row in df_closed.iterrows():
        symbol = row['SYMBOL']
        entry_iso = to_iso(row['DATE OPENED'])
        exit_iso = to_iso(row['DATE CLOSED'])
        
        file_path = os.path.join(DATA_DIR, f"{symbol}.csv")
        if not os.path.exists(file_path):
            continue
            
        try:
            df_ticker = pd.read_csv(file_path)
            df_ticker['ISO_DATE'] = df_ticker.iloc[:, 0].apply(to_iso)
            
            mask = (df_ticker['ISO_DATE'] >= entry_iso) & (df_ticker['ISO_DATE'] <= exit_iso)
            trade_window = df_ticker.loc[mask].copy()
            
            if trade_window.empty:
                continue
                
            prices = trade_window.iloc[:, 4].values # Close prices
            entry_anchor = row['ENTRY PRICE']
            
            if entry_anchor == 0: continue
            
            pct_movement = ((prices - entry_anchor) / entry_anchor) * 100
            days_held_idx = range(len(pct_movement))
            
            # --- TRI-COLOR LOGIC ---
            pnl = row['PNL %']
            if pnl > 0:
                color = 'green'
                win_count += 1
            elif pnl < 0:
                color = 'red'
                loss_count += 1
            else:
                color = 'grey'
                be_count += 1
                
            plt.plot(days_held_idx, pct_movement, color=color, alpha=0.25, linewidth=1)
            trade_count += 1
        except Exception as e:
            continue

    # 3. Chart Aesthetics & Tick Marking
    plt.axhline(0, color='black', linewidth=1.5, linestyle='-') # Entry Baseline
    
    # Set vertical axis ticks at 10% increments
    ax.yaxis.set_major_locator(ticker.MultipleLocator(10))
    
    # Add Legend for clarity
    legend_elements = [
        Line2D([0], [0], color='green', lw=2, label=f'Wins ({win_count})'),
        Line2D([0], [0], color='red', lw=2, label=f'Losses ({loss_count})'),
        Line2D([0], [0], color='grey', lw=2, label=f'Break Even ({be_count})')
    ]
    ax.legend(handles=legend_elements, loc='upper left')

    plt.title(f"Portfolio Behavior: {trade_count} Trades (Outlier Removed)", fontsize=14)
    plt.xlabel("Trading Days Since Entry", fontsize=12)
    plt.ylabel("% Profit / Loss from Entry Price", fontsize=12)
    plt.grid(True, which='both', linestyle=':', alpha=0.4)
    
    print(f"Successfully plotted {trade_count} trades. Wins: {win_count}, Losses: {loss_count}, BE: {be_count}")
    print(f"Saving plot to {OUTPUT_PLOT}...")
    plt.savefig(OUTPUT_PLOT, dpi=300)
    plt.show()

if __name__ == "__main__":
    plot_trade_behaviors()