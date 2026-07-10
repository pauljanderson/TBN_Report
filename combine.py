import os
import glob

data_path = 'data/newdata/data/*.csv' # Adjust if your path is different
output_file = 'ALL_DATA.csv'

files = glob.glob(data_path)
print(f"📦 Consolidating {len(files)} files...")

with open(output_file, 'w') as master:
    for f in files:
        symbol = os.path.basename(f).replace('.csv', '')
        with open(f, 'r') as ticker:
            # Add a marker line so AWK knows a new ticker has started
            master.write(f"NEW_TICKER,{symbol}\n")
            master.write(ticker.read())
            master.write("\n")

print(f"✅ Done! Created {output_file} (approx {os.path.getsize(output_file)/1e6:.2f} MB)")