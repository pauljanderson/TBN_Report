import pandas as pd
import os
import sys
from typing import Optional, Tuple
from collections import defaultdict
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import re
from datetime import datetime
import numpy as np


def normalize_ohlc_columns(df):
    """Ensure DataFrame has 'Date' and 'Close' columns for OHLC-style ticker/SPY CSVs."""
    cols = [c.strip() for c in df.columns]
    df.columns = cols
    if 'Date' not in df.columns and len(cols) >= 1:
        df = df.rename(columns={cols[0]: 'Date'})
    close_candidates = [c for c in df.columns if re.search(r'^(adj\s*)?close$', c, re.I)]
    if 'Close' not in df.columns:
        if close_candidates:
            df = df.rename(columns={close_candidates[0]: 'Close'})
        elif len(df.columns) >= 5:
            df = df.rename(columns={df.columns[4]: 'Close'})
    return df


def parse_trade_date(val):
    """Parse DATE OPENED / DATE CLOSED from RL CSV: int YYYYMMDD, float, or string."""
    if pd.isna(val):
        return None
    if isinstance(val, (int, float)):
        try:
            return pd.to_datetime(str(int(float(val))), format='%Y%m%d')
        except Exception:
            return pd.to_datetime(val)
    return pd.to_datetime(val)


def diagnostic_check(df, label):
    print(f"\n--- DIAGNOSTIC: {label} ---")
    print(f"Columns Found: {list(df.columns)}")
    print("First 2 rows of data:")
    print(df.head(2))
    # Check for the expected date columns
    date_cols = [c for c in df.columns if 'DATE' in c.upper()]
    print(f"Detected Date Columns: {date_cols}")
    for col in date_cols:
        print(f"Sample values in {col}: {df[col].head(3).tolist()}")

def clean_numeric(val):
    if pd.isna(val):
        return 0.0
    if isinstance(val, str):
        was_pct = '%' in val
        val = val.replace('%', '').replace(',', '').strip()
        try:
            x = float(val)
            return x / 100.0 if was_pct else x
        except Exception:
            return 0.0
    return float(val)

def calculate_stagnation(df_sys, df_spy):
    # Merge on Date
    merged = pd.merge(df_sys, df_spy, on='Date', suffixes=('_Sys', '_SPY'))
    
    # Rolling 20-day returns
    merged['Ret_Sys'] = merged['Equity'].pct_change(20)
    merged['Ret_SPY'] = merged['SPY_Price'].pct_change(20)
    
    # Define Stagnation
    merged['Is_Stagnant'] = (merged['Ret_SPY'] > 0.02) & (merged['Ret_Sys'] < 0.005)
    
    return round(merged['Is_Stagnant'].mean() * 100, 2) # Returns percentage

def generate_underwater_report(df_equity, timestamp, output_dir=None):
    """Build underwater (drawdown) periods report. Writes RL_underwater_<timestamp>.csv to output_dir or cwd."""
    df = df_equity.sort_values('Date').reset_index(drop=True)
    df['HWM'] = df['Equity'].cummax()
    df['Is_Underwater'] = df['Equity'] < df['HWM']
    df['Drawdown_Group'] = (df['Is_Underwater'] != df['Is_Underwater'].shift()).cumsum()
    underwater_groups = df[df['Is_Underwater']].groupby('Drawdown_Group')
    report_data = []
    for _, group in underwater_groups:
        hwm_idx = group.index[0] - 1
        hwm_date = pd.Timestamp(df.loc[hwm_idx, 'Date']) if hwm_idx >= 0 else pd.Timestamp(group['Date'].iloc[0])
        hwm_val = float(df.loc[hwm_idx, 'Equity']) if hwm_idx >= 0 else float(group['Equity'].iloc[0])
        trough_row = group.loc[group['Equity'].idxmin()]
        trough_date = trough_row['Date']
        trough_val = float(trough_row['Equity'])
        dd_pct = (trough_val - hwm_val) / hwm_val * 100 if hwm_val else 0
        recovery_idx = group.index[-1] + 1
        hwm_ts = pd.Timestamp(hwm_date)
        trough_ts = pd.Timestamp(trough_date)
        days_to_trough = (trough_ts - hwm_ts).days
        if recovery_idx < len(df):
            recovery_date = df.loc[recovery_idx, 'Date']
            recovery_ts = pd.Timestamp(recovery_date)
            duration = (recovery_ts - hwm_ts).days
            days_since_trough = (recovery_ts - trough_ts).days
        else:
            recovery_date = "Still Underwater"
            today_ts = pd.Timestamp('today').normalize()
            duration = (today_ts - hwm_ts).days
            days_since_trough = (today_ts - trough_ts).days
        report_data.append({
            'HWM_Date': hwm_date,
            'HWM_Value': round(hwm_val, 2),
            'Trough_Date': trough_date,
            'Trough_Value': round(trough_val, 2),
            'Drawdown_Pct': round(dd_pct, 2),
            'Days_to_trough': days_to_trough,
            'Days_since_trough': days_since_trough,
            'Recovery_Date': recovery_date,
            'Duration_Days': duration
        })
    underwater_report = pd.DataFrame(report_data).sort_values('Duration_Days', ascending=False)
    report_name = f"RL_underwater_{timestamp}.csv"
    out_path = os.path.join(output_dir, report_name) if output_dir else report_name
    underwater_report.to_csv(out_path, index=False)
    return underwater_report['Duration_Days'].max() if not underwater_report.empty else 0

def update_rocketlauncher_summary(summary_path, metrics_dict):
    """Appends new metrics as columns to the last row of rocketlauncher.csv"""
    try:
        df = pd.read_csv(summary_path)
        # Add new columns if they don't exist
        for key, value in metrics_dict.items():
            df.loc[df.index[-1], key] = value
        
        df.to_csv(summary_path, index=False)
        print(f"[OK] Summary updated in {summary_path}")
    except Exception as e:
        print(f"[ERR] Error updating summary: {e}")

# Example Integration Logic:
# metrics = {
#     'MAX_UNDERWATER': max_underwater_days,
#     'ULCER_INDEX': round(ui, 2),
#     'YEARLY_SHARPE': round(sharpe, 2),
#     'YEARLY_SORTINO': round(sortino, 2),
#     'YEARLY_PF': round(pf, 2),
#     'STAGNATION_SCORE': f"{round(stagnation, 2)}%"
# }
# update_rocketlauncher_summary('rocketlauncher.csv', metrics)

def _resolve_ticker_dir(ticker_dir):
    """If ticker_dir has SPY.csv, return it (absolute). Else try common repo layouts and return first that has SPY.csv."""
    ticker_dir = os.path.abspath(ticker_dir)
    if os.path.isfile(os.path.join(ticker_dir, "SPY.csv")):
        return ticker_dir
    script_dir = os.path.dirname(os.path.abspath(__file__))
    for parts in [("..", "data", "newdata", "data"), ("..", "..", "data", "newdata", "data"), ("..", "data"), ("data", "newdata", "data")]:
        candidate = os.path.normpath(os.path.join(script_dir, *parts))
        if os.path.isfile(os.path.join(candidate, "SPY.csv")):
            return candidate
    return ticker_dir


# Engines searched when resolving a bare 12-digit timestamp (order only affects listing, not selection).
_CLOSED_ORDER = (
    ("BRT", "BRT_Closed_"),
    ("IND", "IND_Closed_"),
    ("MTS", "MTS_Closed_"),
    ("RL", "RL_Closed_"),
)


def _closed_search_roots() -> list[str]:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    roots = [
        os.path.normpath(os.path.join(script_dir, "..", "Drive")),
        os.path.normpath(os.path.join(script_dir, "..", "drive")),
        os.path.normpath(os.path.join(script_dir, "Drive")),
        os.path.normpath(os.path.join(script_dir, "drive")),
        os.path.normpath(os.getcwd()),
        os.path.normpath(os.path.join(os.getcwd(), "Drive")),
        os.path.normpath(os.path.join(os.getcwd(), "drive")),
    ]
    out: list[str] = []
    seen: set[str] = set()
    for root in roots:
        if root in seen or not os.path.isdir(root):
            continue
        seen.add(root)
        out.append(root)
    return out


def _find_all_closed_by_timestamp(timestamp: str) -> list[tuple[str, str]]:
    """
    Locate every *Closed_<timestamp>.csv (12-digit yyMMddHHmmss) under Drive/drive roots.
    Returns [(absolute_path, engine), ...] with engine in BRT | IND | MTS | RL.
    """
    ts = re.sub(r"\D", "", str(timestamp).strip())
    if len(ts) != 12:
        return []
    found: dict[str, tuple[str, str]] = {}
    for root in _closed_search_roots():
        for engine, prefix in _CLOSED_ORDER:
            fn = f"{prefix}{ts}.csv"
            ap = os.path.normpath(os.path.join(root, fn))
            if os.path.isfile(ap):
                found[ap] = (ap, engine)
    matches = list(found.values())
    matches.sort(key=lambda x: os.path.getmtime(x[0]), reverse=True)
    return matches


def _find_closed_by_timestamp(
    timestamp: str,
    engine_preference: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Resolve Closed CSV for a bare timestamp. When multiple engines share the same ts
    (e.g. DailyRun BRT then IND), prefer --engine if set, else the newest file by mtime.
    """
    matches = _find_all_closed_by_timestamp(timestamp)
    if not matches:
        return None, None
    pref = (engine_preference or "").strip().upper()
    if pref:
        for path, eng in matches:
            if eng == pref:
                return path, eng
        avail = ", ".join(f"{eng}={os.path.basename(p)}" for p, eng in matches)
        print(
            f"[WARN] --engine {pref} not found for timestamp {timestamp}; available: {avail}",
            file=sys.stderr,
        )
    if len(matches) == 1:
        return matches[0]
    lines = [f"  {eng}: {p} (mtime {os.path.getmtime(p):.0f})" for p, eng in matches]
    print(
        f"[WARN] Multiple Closed CSVs for timestamp {timestamp}:\n"
        + "\n".join(lines)
        + f"\n[OK] Using newest: {matches[0][1]} -> {matches[0][0]} "
        "(pass --engine IND|BRT|MTS|RL to force a specific run)",
    )
    return matches[0]


def _engine_from_closed_basename(path: str) -> str:
    bn = os.path.basename(path)
    if bn.startswith("BRT_Closed_"):
        return "BRT"
    if bn.startswith("MTS_Closed_"):
        return "MTS"
    if bn.startswith("IND_Closed_"):
        return "IND"
    return "RL"


def _resolve_closed_csv_argument(
    closed_arg: str,
    engine_preference: Optional[str] = None,
) -> Tuple[str, bool, str]:
    """
    Returns (path, used_timestamp_only_arg, engine) where engine is RL | BRT | IND | MTS.
    """
    s = (closed_arg or "").strip()
    if not s:
        return s, False, "RL"
    if os.path.isfile(s):
        ap = os.path.abspath(s)
        return ap, False, _engine_from_closed_basename(ap)
    if re.fullmatch(r"\d{12}", s):
        found, eng = _find_closed_by_timestamp(s, engine_preference=engine_preference)
        if found and eng:
            print(f"[OK] Timestamp {s} -> {found} ({eng})")
            return found, True, eng
    return s, False, "RL"


def run_audit(closed_path, ticker_dir, cash=47500, output_dir=None, diagnose=False):
    """
    Reconstruct portfolio equity from Closed (and optional Open) CSVs and ticker data.
    closed_path: path to RL_Closed_<timestamp>.csv
    ticker_dir: directory containing per-symbol CSVs and optionally SPY.csv
    cash: position size per trade (default 47500)
    output_dir: where to write chart and daily_equity_debug.csv (default: same dir as closed_path)
    diagnose: if True, print column diagnostics after loading CSVs
    """
    base_dir = os.path.dirname(os.path.abspath(closed_path))
    out_dir = output_dir if output_dir is not None else base_dir
    # Resolve ticker_dir to absolute; if it has no SPY.csv, try common repo paths
    ticker_dir = os.path.abspath(ticker_dir)
    resolved = _resolve_ticker_dir(ticker_dir)
    if resolved != ticker_dir:
        print(f"[OK] Ticker dir has no SPY.csv; using: {resolved}")
        ticker_dir = resolved
    filename = os.path.basename(closed_path)
    ts_match = re.search(r'(\d{12})', filename, re.IGNORECASE)
    timestamp = ts_match.group(1) if ts_match else "Report"
    open_path = os.path.join(base_dir, f"RL_Open_{timestamp}.csv")
    db_closed_path = os.path.join(base_dir, f"DB_Closed_{timestamp}.csv")
    db_open_path = os.path.join(base_dir, f"DB_Open_{timestamp}.csv")

    print(f"[FILE] CLOSED: {closed_path}")
    if os.path.exists(open_path):
        print(f"[FILE] OPEN:   {open_path}")
    else:
        print(f"[WARN] OPEN file not found: {open_path}")
    if os.path.exists(db_closed_path):
        print(f"[FILE] DB CLOSED: {db_closed_path}")
    if os.path.exists(db_open_path):
        print(f"[FILE] DB OPEN:   {db_open_path}")

    try:
        df_closed = pd.read_csv(closed_path, index_col=False)
        df_closed.columns = [c.strip() for c in df_closed.columns]
        required_closed = ['SYMBOL', 'DATE OPENED', 'ENTRY PRICE', 'DATE CLOSED', 'EXIT PRICE']
        missing = [c for c in required_closed if c not in df_closed.columns]
        if missing:
            print(f"[ERR] Closed CSV missing columns: {missing}. Found: {list(df_closed.columns)[:15]}...")
            return
        # Prefer PNL % for realized PnL to avoid wrong equity when EXIT PRICE column is misread (e.g. as %)
        use_pnl_pct = 'PNL %' in df_closed.columns
        if use_pnl_pct:
            print("[OK] Using PNL % column for closed-trade realized PnL (avoids EXIT PRICE column issues)")
        if diagnose:
            diagnostic_check(df_closed, "CLOSED TRADES")

        df_open = pd.DataFrame()
        if os.path.exists(open_path):
            df_open = pd.read_csv(open_path, index_col=False)
            df_open.columns = [c.strip() for c in df_open.columns]
            required_open = ['SYMBOL', 'DATE OPENED', 'ENTRY PRICE']
            missing_open = [c for c in required_open if c not in df_open.columns]
            if missing_open:
                print(f"[WARN] Open CSV missing columns: {missing_open}; skipping open trades.")
                df_open = pd.DataFrame()
            elif diagnose:
                diagnostic_check(df_open, "OPEN TRADES")
    except Exception as e:
        print(f"[ERR] Loading CSV: {e}")
        return

    # Load DB Closed/Open for position-count chart (same timestamp)
    df_db_closed = pd.DataFrame()
    df_db_open = pd.DataFrame()
    if os.path.exists(db_closed_path):
        try:
            df_db_closed = pd.read_csv(db_closed_path, index_col=False)
            df_db_closed.columns = [c.strip() for c in df_db_closed.columns]
        except Exception as e:
            print(f"[WARN] Could not load DB Closed: {e}")
    if os.path.exists(db_open_path):
        try:
            df_db_open = pd.read_csv(db_open_path, index_col=False)
            df_db_open.columns = [c.strip() for c in df_db_open.columns]
        except Exception as e:
            print(f"[WARN] Could not load DB Open: {e}")

    # Single load used for all processing; no re-read from disk
    task_list = [('Closed', df_closed)]
    if not df_open.empty:
        task_list.append(('Open', df_open))
        print(f"[OK] Using open trades: {len(df_open)} rows")

    RL_CASH = cash
    initial_account_size = RL_CASH * 12
    realized_pnl_events = defaultdict(float)
    unrealized_pnl_timeline = defaultdict(float)
    active_symbols_timeline = defaultdict(set)
    active_symbols_timeline_db = defaultdict(set)
    market_max_date = pd.to_datetime(datetime.now().date())

    print("[OK] Extracting daily trade data...")

    for file_type, df in task_list:
        count = 0
        for _, trade in df.iterrows():
            symbol = str(trade['SYMBOL']).strip()
            ticker_file = os.path.join(ticker_dir, f"{symbol}.csv")
            if not os.path.exists(ticker_file):
                continue
            try:
                df_ticker = pd.read_csv(ticker_file)
                df_ticker = normalize_ohlc_columns(df_ticker)
                if 'Date' not in df_ticker.columns or 'Close' not in df_ticker.columns:
                    raise ValueError(f"ticker file missing Date/Close columns: {list(df_ticker.columns)}")
                df_ticker['Date'] = pd.to_datetime(df_ticker['Date'])
                if df_ticker['Date'].max() > market_max_date:
                    market_max_date = df_ticker['Date'].max()

                start_dt = parse_trade_date(trade['DATE OPENED'])
                if start_dt is None:
                    raise ValueError("DATE OPENED could not be parsed")
                entry_p = clean_numeric(trade['ENTRY PRICE'])
                shares = RL_CASH / entry_p

                if file_type == 'Closed':
                    end_dt = parse_trade_date(trade['DATE CLOSED'])
                    if end_dt is None:
                        raise ValueError("DATE CLOSED could not be parsed")
                    actual_exit_p = clean_numeric(trade['EXIT PRICE'])
                    # If EXIT PRICE looks like a % (e.g. misread column), use ticker Close on exit day for mark
                    if actual_exit_p > 0 and (actual_exit_p < 1 or actual_exit_p < entry_p * 0.1):
                        actual_exit_p = None  # will use last row Close in window
                else:
                    end_dt = df_ticker['Date'].max()
                    actual_exit_p = df_ticker.iloc[-1]['Close']

                window = df_ticker[(df_ticker['Date'] >= start_dt) & (df_ticker['Date'] <= end_dt)].sort_values('Date')
                if window.empty:
                    continue
                for i, row in enumerate(window.to_dict('records')):
                    dt = row['Date']
                    last_row = (i == len(window) - 1)
                    if last_row and actual_exit_p is not None:
                        check_p = actual_exit_p
                    else:
                        check_p = row['Close']
                    pnl = (check_p - entry_p) * shares
                    active_symbols_timeline[dt].add(symbol)
                    if last_row and file_type == 'Closed':
                        if use_pnl_pct:
                            pct_val = clean_numeric(trade['PNL %'])
                            if abs(pct_val) > 1.5:
                                pct_val = pct_val / 100.0
                            realized_pnl_events[dt] += pct_val * RL_CASH
                        else:
                            realized_pnl_events[dt] += pnl
                    else:
                        unrealized_pnl_timeline[dt] += pnl
                count += 1
            except Exception as e:
                print(f"[WARN] Skip {symbol} ({file_type}): {e}")
                continue
        print(f"   [OK] Processed {count} {file_type} trades.")
        if count == 0 and file_type == 'Closed':
            sample_syms = list(df['SYMBOL'].head(3).astype(str).str.strip()) if len(df) else []
            print(f"[ERR] No Closed trades could be loaded. Ticker dir used: {ticker_dir}")
            print(f"      Example symbols in CSV: {sample_syms}. Check that second argument is the directory")
            print(f"      containing <SYMBOL>.csv and SPY.csv (e.g. ..\\data\\newdata\\data)")

    # Build DB position count timeline (same scale as RL) from DB_Closed / DB_Open
    task_list_db = [('Closed', df_db_closed)]
    if not df_db_open.empty and all(c in df_db_open.columns for c in ['SYMBOL', 'DATE OPENED', 'ENTRY PRICE']):
        task_list_db.append(('Open', df_db_open))
    for file_type, df in task_list_db:
        if df.empty or 'SYMBOL' not in df.columns or 'DATE OPENED' not in df.columns:
            continue
        req = ['SYMBOL', 'DATE OPENED', 'ENTRY PRICE', 'DATE CLOSED', 'EXIT PRICE'] if file_type == 'Closed' else ['SYMBOL', 'DATE OPENED', 'ENTRY PRICE']
        if any(c not in df.columns for c in req):
            continue
        for _, trade in df.iterrows():
            symbol = str(trade['SYMBOL']).strip()
            ticker_file = os.path.join(ticker_dir, f"{symbol}.csv")
            if not os.path.exists(ticker_file):
                continue
            try:
                df_ticker = pd.read_csv(ticker_file)
                df_ticker = normalize_ohlc_columns(df_ticker)
                if 'Date' not in df_ticker.columns or 'Close' not in df_ticker.columns:
                    continue
                df_ticker['Date'] = pd.to_datetime(df_ticker['Date'])
                start_dt = parse_trade_date(trade['DATE OPENED'])
                if start_dt is None:
                    continue
                if file_type == 'Closed':
                    end_dt = parse_trade_date(trade['DATE CLOSED'])
                    if end_dt is None:
                        continue
                else:
                    end_dt = pd.to_datetime(df_ticker['Date'].max())
                window = df_ticker[(df_ticker['Date'] >= start_dt) & (df_ticker['Date'] <= end_dt)].sort_values('Date')
                if window.empty:
                    continue
                for dt in window['Date'].tolist():
                    active_symbols_timeline_db[dt].add(symbol)
            except Exception:
                continue
    if active_symbols_timeline_db:
        print(f"[OK] DB position timeline: {len(active_symbols_timeline_db)} dates with at least one DB position")

    all_dates = sorted(active_symbols_timeline.keys())
    if not all_dates:
        print("[ERR] No trade dates found. Did you pass the ticker data directory as the second argument?")
        print(f"      Example: python DrawdownCalc.py <closed_csv> \"C:\\...\\data\\newdata\\data\"")
        return

    # Extension logic
    if market_max_date > all_dates[-1]:
        last_date = all_dates[-1]
        date_range = pd.date_range(start=last_date, end=market_max_date)
        for gap_dt in date_range:
            if gap_dt not in active_symbols_timeline:
                active_symbols_timeline[gap_dt] = active_symbols_timeline[last_date]
                unrealized_pnl_timeline[gap_dt] = unrealized_pnl_timeline[last_date]
        all_dates = sorted(active_symbols_timeline.keys())

    print(f"[OK] Charting from {all_dates[0].date()} to {all_dates[-1].date()}")

    # --- RECONSTRUCTION & DRAWDOWN CALC ---
    history_dates, history_equity, history_positions = [], [], []
    history_positions_db = []
    running_realized_pnl = 0.0
    port_hwm = initial_account_size 
    max_port_dd = 0.0
    trough_date = None
    peak_date_for_max_dd = all_dates[0]
    current_hwm_date = all_dates[0]

    for dt in all_dates:
        running_realized_pnl += realized_pnl_events.get(dt, 0)
        current_floating = unrealized_pnl_timeline.get(dt, 0.0)
        active_count = len(active_symbols_timeline.get(dt, set()))
        active_count_db = len(active_symbols_timeline_db.get(dt, set()))
        current_equity = initial_account_size + running_realized_pnl + current_floating
        
        if current_equity > port_hwm:
            port_hwm = current_equity
            current_hwm_date = dt
        
        if port_hwm > 0:
            dd = (port_hwm - current_equity) / port_hwm
            if dd > max_port_dd:
                max_port_dd = dd
                trough_date = dt
                peak_date_for_max_dd = current_hwm_date

        history_dates.append(dt)
        history_equity.append(current_equity)
        history_positions.append(active_count)
        history_positions_db.append(active_count_db)

    debug_df = pd.DataFrame({'Date': history_dates, 'Equity': history_equity})
    debug_path = os.path.join(out_dir, 'daily_equity_debug.csv')
    debug_df.to_csv(debug_path, index=False)
    print(f"[FILE] Daily equity log: {debug_path}")

    max_underwater = generate_underwater_report(debug_df, timestamp, output_dir=out_dir)
    if max_underwater > 0:
        print(f"[FILE] Underwater report: {os.path.join(out_dir, f'RL_underwater_{timestamp}.csv')} (max duration {max_underwater} days)")

    # --- SPY BENCHMARK ---
    spy_equity = []
    spy_path = os.path.join(ticker_dir, "SPY.csv")
    if os.path.exists(spy_path):
        df_spy = pd.read_csv(spy_path)
        df_spy = normalize_ohlc_columns(df_spy)
        if 'Date' in df_spy.columns and 'Close' in df_spy.columns:
            df_spy['Date'] = pd.to_datetime(df_spy['Date'])
            df_spy = df_spy.sort_values('Date').set_index('Date')
            # Use last available SPY date on or before portfolio start (avoid KeyError if start isn't a trading day)
            try:
                idx = df_spy.index.get_indexer([pd.Timestamp(all_dates[0])], method='ffill')[0]
                if idx >= 0:
                    start_p = float(df_spy.iloc[idx]['Close'])
                else:
                    start_p = None
            except Exception:
                start_p = float(df_spy.iloc[0]['Close']) if len(df_spy) else None
            if start_p and start_p > 0:
                for dt in all_dates:
                    try:
                        idx = df_spy.index.get_indexer([pd.Timestamp(dt)], method='ffill')[0]
                        p = float(df_spy.iloc[idx]['Close']) if idx >= 0 else start_p
                    except Exception:
                        p = start_p
                    spy_equity.append((p / start_p) * initial_account_size)

    # --- CHART GENERATION ---
    fig, ax1 = plt.subplots(figsize=(12, 6))
    ax1.plot(history_dates, history_equity, color='tab:blue', linewidth=2, label='Portfolio Equity')
    if spy_equity:
        ax1.plot(history_dates, spy_equity, color='black', linestyle='--', linewidth=1.2, label='SPY Benchmark', alpha=0.6)
    
    if trough_date:
        trough_val = history_equity[history_dates.index(trough_date)]
        ax1.annotate(f'Max DD: {max_port_dd:.1%}', 
                     xy=(trough_date, trough_val),
                     xytext=(trough_date, trough_val * 0.9), 
                     arrowprops=dict(facecolor='black', shrink=0.05, width=1, headwidth=5),
                     fontsize=10, fontweight='bold', color='darkred', ha='center')

    ax1.set_ylabel('Total Value ($)', fontweight='bold')
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))
    ax1.legend(loc='upper left')

    ax2 = ax1.twinx()
    y_max_pos = max(max(history_positions), max(history_positions_db) if history_positions_db else 0) + 5
    ax2.step(history_dates, history_positions, where='post', color='tab:red', alpha=0.5, linewidth=1.5, label='RL Positions')
    ax2.step(history_dates, history_positions_db, where='post', color='tab:green', alpha=0.5, linewidth=1.5, label='DB Positions')
    ax2.set_ylabel('Active Positions', fontweight='bold')
    ax2.set_ylim(0, y_max_pos)
    ax2.set_xlim(history_dates[0], history_dates[-1])
    ax2.legend(loc='upper right')

    plt.title(f'Portfolio Reconstruction vs SPY (True Max DD)', fontsize=14, fontweight='bold')
    ax1.grid(True, linestyle='--', alpha=0.5)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    plt.xticks(rotation=45)
    
    save_name = f"Portfolio_Performance_{timestamp if timestamp else 'Report'}.png"
    save_path = os.path.join(out_dir, save_name)
    plt.tight_layout()
    plt.savefig(save_path)
    print(f"[FILE] Chart: {save_path}")
    # Also write to stable name so the same file updates every run (open this one to always see latest)
    latest_path = os.path.join(out_dir, "Portfolio_Performance_latest.png")
    try:
        import shutil
        shutil.copy2(save_path, latest_path)
        print(f"[FILE] Chart (latest): {latest_path}")
    except Exception as e:
        print(f"[WARN] Could not write Portfolio_Performance_latest.png: {e}")
    plt.close()

    print("\n" + "="*50)
    print("PORTFOLIO PERFORMANCE SUMMARY")
    print("="*50)
    print(f"Max DD:        {max_port_dd:.2%}")
    print(f"Peak Date:     {peak_date_for_max_dd.date()}")
    print(f"Trough Date:   {trough_date.date() if trough_date else 'N/A'}")
    print("="*50 + "\n")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(
        description="Portfolio drawdown: RL (this file) or BRT/MTS via BRT_DrawdownCalc; Closed/Open CSVs + tickers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python DrawdownCalc.py Drive/RL_Closed_260419073004.csv data/newdata/data\n"
            "  python DrawdownCalc.py 260419073636\n"
            "  python DrawdownCalc.py 260602180527 --engine IND\n"
            "    (bare timestamp: newest Closed wins; use --engine when BRT and IND share a ts)\n"
        ),
    )
    p.add_argument(
        "closed_csv",
        help=(
            "Path to RL_Closed_ / BRT_Closed_ / MTS_Closed_<timestamp>.csv, OR a 12-digit yyMMddHHmmss only "
            "(searches Drive/, drive/, cwd)."
        ),
    )
    p.add_argument(
        "ticker_dir",
        nargs="?",
        default="data/",
        help="Directory with per-symbol CSVs (default: data/; auto-upgraded if SPY.csv missing)",
    )
    p.add_argument("--cash", type=float, default=47500, help="Position size per trade (default: 47500; BRT/IND/MTS: read from audit unless --no-audit)")
    p.add_argument("--output-dir", default=None, help="Directory for chart and debug CSV (default: same as closed file)")
    p.add_argument("--diagnose", action="store_true", help="Print column diagnostics after loading CSVs")
    p.add_argument(
        "--no-saved-equity",
        action="store_true",
        help="BRT/IND/MTS only: rebuild equity from OHLC; ignore saved EquityCurve CSV",
    )
    p.add_argument(
        "--force-reconstruct",
        action="store_true",
        help="BRT/IND/MTS only: same as --no-saved-equity (always OHLC rebuild)",
    )
    p.add_argument(
        "--engine",
        choices=("BRT", "IND", "MTS", "RL"),
        default=None,
        help="When closed_csv is a 12-digit timestamp and multiple *Closed_<ts>.csv exist, force BRT/IND/MTS/RL",
    )
    p.add_argument(
        "--aggressive",
        action="store_true",
        help="BRT/IND/MTS only: chart aggressive Equity + passive overlay; default is passive-only when Equity_Regular exists",
    )
    p.add_argument(
        "--initial-capital",
        type=float,
        default=None,
        metavar="USD",
        help="BRT/IND/MTS only: starting equity for chart & Max DD (default 500000)",
    )
    p.add_argument(
        "--no-audit",
        action="store_true",
        help="BRT/IND/MTS only: do not read brt_cash from audit CSV",
    )
    args = p.parse_args()
    closed_path, ts_mode, engine = _resolve_closed_csv_argument(
        args.closed_csv,
        engine_preference=getattr(args, "engine", None),
    )
    if args.ticker_dir == "data/" and (ts_mode or engine in ("BRT", "MTS")):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        preferred = os.path.normpath(os.path.join(script_dir, "..", "data", "newdata", "data"))
        if os.path.isdir(preferred):
            args.ticker_dir = preferred
            print(f"[OK] Ticker dir (default upgrade): {args.ticker_dir}")
    if not closed_path or not os.path.isfile(closed_path):
        print(
            f"[ERR] No Closed CSV for {args.closed_csv!r}. "
            "Pass *Closed_<ts>.csv, or a 12-digit timestamp (searches Drive/ and drive/). "
            "Use --engine IND when BRT and IND share the same timestamp.",
            file=sys.stderr,
        )
        sys.exit(1)
    if engine in ("BRT", "IND", "MTS"):
        try:
            from BRT_DrawdownCalc import run_audit as brt_drawdown_run
        except ImportError as exc:
            print(f"[ERR] Could not import BRT_DrawdownCalc: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"[OK] Running BRT_DrawdownCalc for {engine} ({os.path.basename(closed_path)})")
        brt_drawdown_run(
            closed_path,
            args.ticker_dir,
            cash=None if not getattr(args, "no_audit", False) else args.cash,
            output_dir=args.output_dir or None,
            initial_capital=args.initial_capital,
            use_audit=not getattr(args, "no_audit", False),
            no_saved_equity=bool(getattr(args, "no_saved_equity", False)),
            force_reconstruct=bool(getattr(args, "force_reconstruct", False)),
            aggressive=bool(getattr(args, "aggressive", False)),
        )
    else:
        run_audit(
            closed_path,
            args.ticker_dir,
            cash=args.cash,
            output_dir=args.output_dir or None,
            diagnose=args.diagnose,
        )