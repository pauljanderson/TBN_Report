"""Generate GOOGL_zones_trades.ts (zones only — no breakout dates in source)."""
from ts_common import write_ts_files

zones = [
    (20190722, 62.47, 64.37, 0),
    (20200831, 85.01, 87.60, 0),
    (20210215, 105.65, 108.87, 0),
    (20220704, 117.90, 121.49, 0),
    (20221128, 100.71, 103.78, 0),
    (20231009, 139.10, 143.34, 0),
    (20240129, 151.48, 156.09, 0),
    (20241111, 179.76, 185.23, 0),
]
entries = [20191204, 20201120, 20220524, 20230208, 20230613, 20240206, 20240806, 20241223]
exits = [20200312, 20210405, 20220922, 20230209, 20240125, 20240520, 20241211, 20250227]

EXTRA_HEADER = "No breakout dates in source data (clouds only)."

if __name__ == "__main__":
    write_ts_files("GOOGL", zones, entries, exits, extra_header=EXTRA_HEADER)
