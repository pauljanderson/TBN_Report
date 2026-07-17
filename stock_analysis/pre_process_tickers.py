import sys
import pandas as pd
import glob
import os

def pre_process_tickers(directory_path):
    # Get all CSV files in the directory
    files = glob.glob(os.path.join(directory_path, "*.csv"))
    print(f"Found {len(files)} files. Starting SMA pre-calculation...")

    for file in files:
        try:
            # Load the data
            df = pd.read_csv(file)
            
            # Standardize column names to ensure math works
            df.columns = [c.strip().capitalize() for c in df.columns]
            
            # Sort by date to ensure rolling windows are accurate
            df['Date'] = pd.to_datetime(df['Date'])
            df = df.sort_values('Date')

            # Calculate SMAs using vectorized Pandas logic (very fast)
            df['Sma20'] = df['Close'].rolling(window=20).mean()
            df['Sma30'] = df['Close'].rolling(window=30).mean()
            df['Sma50'] = df['Close'].rolling(window=50).mean()
            df['Sma100'] = df['Close'].rolling(window=100).mean()
            df['Sma200'] = df['Close'].rolling(window=200).mean()

            # Add ATR calculation
            high_low = df['High'] - df['Low']
            high_close = (df['High'] - df['Close'].shift()).abs()
            low_close = (df['Low'] - df['Close'].shift()).abs()
            ranges = pd.concat([high_low, high_close, low_close], axis=1)
            true_range = ranges.max(axis=1)
            df['Atr14'] = true_range.rolling(window=14).mean()

            # Save back to CSV, rounding to 4 decimals
            df.to_csv(file, index=False, float_format='%.4f')
            print(f"Processed: {os.path.basename(file)}")
            
        except Exception as e:
            print(f"Error processing {file}: {e}")

    print("Pre-processing complete. Your CSVs now contain SMA columns.")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Fixed the name here to match the def above
        pre_process_tickers(sys.argv[1])
    else:
        print("Please provide a directory path.")