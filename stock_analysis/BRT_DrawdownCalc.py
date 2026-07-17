"""
BRT_DrawdownCalc: Portfolio equity reconstruction and chart for BRT Closed/Open CSVs.
Mirrors DrawdownCalc.py: equity curve, position count, underwater periods, Max DD annotation.
"""
import os
import re
import sys
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# Matplotlib imported lazily in reconstruct_and_chart() to avoid subprocess import
# failures (e.g. optimizer workers on Windows). compute_equity_metrics does not need it.


def normalize_ohlc_columns(df):
    """Ensure DataFrame has 'Date' and 'Close' columns for OHLC-style ticker CSVs."""
    cols = [c.strip() for c in df.columns]
    df.columns = cols
    if "Date" not in df.columns and len(cols) >= 1:
        df = df.rename(columns={cols[0]: "Date"})
    close_candidates = [c for c in df.columns if re.search(r"^(adj\s*)?close$", c, re.I)]
    if "Close" not in df.columns:
        if close_candidates:
            df = df.rename(columns={close_candidates[0]: "Close"})
        elif len(df.columns) >= 5:
            df = df.rename(columns={df.columns[4]: "Close"})
    return df


def parse_trade_date(val):
    """Parse DATE_OPENED / DATE_CLOSED: int YYYYMMDD, float, or string."""
    if pd.isna(val):
        return None
    if isinstance(val, (int, float)):
        try:
            return pd.to_datetime(str(int(float(val))), format="%Y%m%d")
        except Exception:
            return pd.to_datetime(val)
    return pd.to_datetime(val)


def clean_numeric(val):
    if pd.isna(val):
        return 0.0
    if isinstance(val, str):
        val = str(val).replace("%", "").replace(",", "").strip()
        try:
            return float(val)
        except Exception:
            return 0.0
    return float(val)


def _parse_date(val):
    """Parse YYYYMMDD or YYYY-MM-DD to Timestamp. Handles int/float from CSV (e.g. 20230215.0)."""
    if val is None or (isinstance(val, str) and len(val) < 8):
        return None
    try:
        if isinstance(val, (int, float)):
            val = str(int(float(val)))
        s = str(val).strip()
        if "-" in s:
            return pd.Timestamp(s[:10])
        if len(s) >= 8:
            return pd.Timestamp(s[:4] + "-" + s[4:6] + "-" + s[6:8])
        return None
    except Exception:
        return None


def _trade_val(t, attr: str, key: str, default=None):
    """Get value from trade - supports BRTTrade (attribute) or dict (key). Avoids t.get() on objects."""
    if hasattr(t, attr):
        return getattr(t, attr, default)
    if isinstance(t, dict):
        return t.get(key, default)
    return default


def load_audit_row(base_dir: str, timestamp: str, file_prefix: str = "BRT") -> Optional[dict]:
    """
    Read first data row from {prefix}_Audit_Report_<ts>.csv or {prefix}_Report_<ts>.csv (same dir as Closed).
    ``file_prefix`` is ``BRT`` or ``MTS`` (matches rocket_brt / rocket_MTS output names).
    Returns dict with ``audit_cash`` (per-trade report notional) and ``source`` filename, or None.
    """
    cash_key = f"{file_prefix.lower()}_cash"  # brt_cash, mts_cash
    for name in (f"{file_prefix}_Audit_Report_{timestamp}.csv", f"{file_prefix}_Report_{timestamp}.csv"):
        path = os.path.join(base_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            df = pd.read_csv(path, index_col=False, nrows=1)
            if df.empty:
                continue
            df.columns = [str(c).strip() for c in df.columns]
            bc_col = next((c for c in df.columns if c.lower() == cash_key), None)
            if bc_col is None:
                continue
            bc = clean_numeric(df.iloc[0][bc_col])
            if bc <= 0:
                continue
            tot_col = next((c for c in df.columns if c.lower() == "total_pnl"), None)
            total_pnl = clean_numeric(df.iloc[0][tot_col]) if tot_col else None
            out: dict = {"audit_cash": float(bc), "source": name}
            if total_pnl is not None:
                out["Total_PNL"] = float(total_pnl)
            return out
        except Exception:
            continue
    return None


def load_brt_audit_row(base_dir: str, timestamp: str) -> Optional[dict]:
    """Backward-compatible alias for ``load_audit_row(..., file_prefix='BRT')``."""
    return load_audit_row(base_dir, timestamp, file_prefix="BRT")


def _pnl_csv_to_cash_scale(entry_p: float, exit_p: float, pnl_dollars: float, cash: float) -> float:
    """
    BRT_Closed often stores PNL_DOLLARS at a different per-trade notional than ``cash`` passed here.
    When entry/exit are reliable, scale CSV dollars so they match shares = cash/entry_price.
    """
    price_move = float(exit_p) - float(entry_p)
    if abs(price_move) < 1e-12 or abs(float(pnl_dollars)) < 1e-9 or float(entry_p) <= 0:
        return 1.0
    shares_csv = float(pnl_dollars) / price_move
    if abs(shares_csv) < 1e-12:
        return 1.0
    shares_target = float(cash) / float(entry_p)
    return shares_target / shares_csv


def _equity_calendar_dates_aggressive_only(
    closed: list,
    open_trades: list,
) -> list[pd.Timestamp]:
    """Business-day span from earliest trade open to last close (or today if any open positions)."""
    firsts: list[pd.Timestamp] = []
    lasts: list[pd.Timestamp] = []
    for t in closed:
        op = _parse_date(_trade_val(t, "date_opened", "DATE_OPENED"))
        cl = _parse_date(_trade_val(t, "date_closed", "DATE_CLOSED"))
        if op is not None:
            firsts.append(pd.Timestamp(op).normalize())
        if cl is not None:
            lasts.append(pd.Timestamp(cl).normalize())
    for t in open_trades:
        op = _parse_date(_trade_val(t, "date_opened", "DATE_OPENED"))
        if op is not None:
            firsts.append(pd.Timestamp(op).normalize())
    if not firsts:
        return []
    start = min(firsts)
    if open_trades:
        end = max(pd.Timestamp(datetime.now().date()), max(lasts) if lasts else start)
    else:
        end = max(lasts) if lasts else start
    if end < start:
        end = start
    return list(pd.bdate_range(start=start, end=end))


def _mean_daily_unique_symbols_active(
    all_dates: list,
    closed: list,
    open_trades: list,
) -> float:
    """
    Mean of daily counts of distinct symbols with at least one open trade (days with count > 0 only).
    Matches passive ``history_positions`` when each trade maps to one symbol per day in its window.
    """
    intervals: list[tuple[pd.Timestamp, pd.Timestamp, str]] = []
    for t in closed:
        sym = str(_trade_val(t, "symbol", "SYMBOL", "") or "").strip()
        op = _parse_date(_trade_val(t, "date_opened", "DATE_OPENED"))
        cl = _parse_date(_trade_val(t, "date_closed", "DATE_CLOSED"))
        if not sym or op is None or cl is None:
            continue
        intervals.append((pd.Timestamp(op).normalize(), pd.Timestamp(cl).normalize(), sym))
    end_open = pd.Timestamp(datetime.now().date())
    for t in open_trades:
        sym = str(_trade_val(t, "symbol", "SYMBOL", "") or "").strip()
        op = _parse_date(_trade_val(t, "date_opened", "DATE_OPENED"))
        if not sym or op is None:
            continue
        intervals.append((pd.Timestamp(op).normalize(), end_open, sym))
    pos_counts: list[float] = []
    for d in all_dates:
        dn = pd.Timestamp(d).normalize()
        active: set[str] = set()
        for a, b, sym in intervals:
            if a <= dn <= b:
                active.add(sym)
        c = len(active)
        if c > 0:
            pos_counts.append(float(c))
    return sum(pos_counts) / len(pos_counts) if pos_counts else 0.0


def _count_trades_missing_ticker(closed: list, open_trades: list, tickers: dict) -> int:
    n = 0
    for t in closed:
        sym = str(_trade_val(t, "symbol", "SYMBOL", "") or "").strip()
        df = tickers.get(sym) if sym else None
        if not sym or df is None:
            n += 1
    for t in open_trades:
        sym = str(_trade_val(t, "symbol", "SYMBOL", "") or "").strip()
        df = tickers.get(sym) if sym else None
        if not sym or df is None:
            n += 1
    return n


def _ticker_close_arrays(df) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """
    Return (date_i8_ns_sorted, close_f64) for fast np.searchsorted ffilled lookups.
    date_i8_ns is int64 nanoseconds since epoch (matches pd.Timestamp.value).
    """
    if df is None:
        return None
    d = df
    try:
        if "Date" not in d.columns:
            d = d.reset_index()
        if "Close" not in d.columns:
            d = normalize_ohlc_columns(d)
        if "Date" not in d.columns or "Close" not in d.columns:
            return None
        dt = pd.to_datetime(d["Date"], utc=False).values.astype("datetime64[ns]")
        date_i8 = dt.view("int64")
        closes = np.asarray(d["Close"], dtype=np.float64)
        if date_i8.size == 0:
            return None
        if not np.all(date_i8[:-1] <= date_i8[1:]):
            order = np.argsort(date_i8, kind="mergesort")
            date_i8 = date_i8[order]
            closes = closes[order]
        return (date_i8, closes)
    except Exception:
        return None


def _prior_business_day(ts: pd.Timestamp) -> pd.Timestamp:
    """Previous business day (for signal-bar MTM before entry open)."""
    return pd.Timestamp(pd.Timestamp(ts).normalize() - pd.offsets.BDay(1)).normalize()


def _equity_for_aggressive_sizing(
    cash: float,
    holdings: dict,
    signal_date: pd.Timestamp,
    _get_px,
) -> float:
    """Cash + mark-to-market of open holdings at signal-date closes."""
    gross = _gross_holdings_at(holdings, signal_date, _get_px)
    return float(cash) + gross


def _gross_holdings_at(
    holdings: dict,
    mark_date: pd.Timestamp,
    _get_px,
) -> float:
    gross = 0.0
    for h in holdings.values():
        px = _get_px(h["symbol"], mark_date, h["entry"], None)
        gross += float(h["shares"]) * px
    return gross


def _normalize_aggressive_sell(mode: Optional[str]) -> str:
    """false | average | losers | winners (case-insensitive)."""
    s = str(mode or "false").strip().lower()
    if s in ("false", "off", "0", "none", ""):
        return "false"
    if s in ("average", "avg", "equal"):
        return "average"
    if s in ("losers", "loser", "worst"):
        return "losers"
    if s in ("winners", "winner", "best"):
        return "winners"
    return "false"


def _holding_unrealized_pct(h: dict, px: float) -> float:
    entry = float(h.get("entry", 0) or 0)
    if entry <= 0.0 or not np.isfinite(px):
        return 0.0
    return (float(px) - entry) / entry * 100.0


def _append_aggressive_trim_log(
    trim_log: list[dict],
    *,
    date: pd.Timestamp,
    mode: str,
    hid: int,
    h: dict,
    shares_sold: float,
    px: float,
    reason: str,
    for_symbol: str,
) -> None:
    proceeds = float(shares_sold) * float(px)
    entry = float(h.get("entry", 0) or 0)
    pnl_pct = _holding_unrealized_pct(h, px)
    trim_log.append(
        {
            "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
            "mode": mode,
            "symbol": h.get("symbol", ""),
            "shares_sold": round(float(shares_sold), 6),
            "price": round(float(px), 4),
            "proceeds": round(proceeds, 2),
            "unrealized_pct": round(pnl_pct, 4),
            "reason": reason,
            "for_new_entry_symbol": for_symbol,
            "holding_id": hid,
            "entry_price": round(entry, 4),
        }
    )


def _sell_holding_shares(
    holdings: dict,
    cash: float,
    hid: int,
    h: dict,
    shares_to_sell: float,
    px: float,
    *,
    mark_date: pd.Timestamp,
    mode: str,
    trim_log: list[dict],
    reason: str,
    for_symbol: str,
) -> float:
    """Reduce holding by shares_to_sell; return updated cash."""
    sh = float(h.get("shares", 0) or 0)
    if sh <= 0.0 or shares_to_sell <= 0.0:
        return cash
    sold = min(sh, float(shares_to_sell))
    if sold <= 0.0:
        return cash
    cash += sold * float(px)
    remaining = sh - sold
    if remaining <= 1e-12:
        holdings.pop(hid, None)
    else:
        h["shares"] = remaining
    _append_aggressive_trim_log(
        trim_log,
        date=mark_date,
        mode=mode,
        hid=hid,
        h=h,
        shares_sold=sold,
        px=px,
        reason=reason,
        for_symbol=for_symbol,
    )
    return cash


def _aggressive_sell_for_amount(
    holdings: dict,
    cash: float,
    amount: float,
    mark_date: pd.Timestamp,
    mode: str,
    _get_px,
    *,
    trim_log: list[dict],
    reason: str,
    for_symbol: str,
) -> tuple[float, float]:
    """
    Liquidate existing holdings to free ``amount`` notional (market value).
    Returns (updated_cash, gross_notional_freed).
    """
    mode_n = _normalize_aggressive_sell(mode)
    need = max(0.0, float(amount))
    if mode_n == "false" or need <= 0.0 or not holdings:
        return cash, 0.0

    freed = 0.0
    if mode_n == "average":
        items: list[tuple[int, dict, float, float]] = []
        total_mv = 0.0
        for hid, h in list(holdings.items()):
            px = _get_px(h["symbol"], mark_date, h["entry"], None)
            mv = float(h["shares"]) * px
            if mv > 0.0:
                items.append((hid, h, px, mv))
                total_mv += mv
        if total_mv <= 0.0:
            return cash, 0.0
        frac = min(1.0, need / total_mv)
        for hid, h, px, mv in items:
            if freed >= need - 1e-6:
                break
            sell_sh = float(h["shares"]) * frac
            if sell_sh <= 0.0:
                continue
            cash = _sell_holding_shares(
                holdings,
                cash,
                hid,
                h,
                sell_sh,
                px,
                mark_date=mark_date,
                mode=mode_n,
                trim_log=trim_log,
                reason=reason,
                for_symbol=for_symbol,
            )
            freed += sell_sh * px
        return cash, freed

    reverse = mode_n == "winners"
    ranked: list[tuple[int, dict, float, float]] = []
    for hid, h in list(holdings.items()):
        px = _get_px(h["symbol"], mark_date, h["entry"], None)
        mv = float(h["shares"]) * px
        if mv <= 0.0:
            continue
        ranked.append((hid, h, px, _holding_unrealized_pct(h, px)))
    ranked.sort(key=lambda x: x[3], reverse=reverse)

    for hid, h, px, _pct in ranked:
        if freed >= need - 1e-6:
            break
        mv = float(h.get("shares", 0) or 0) * px
        if mv <= 0.0:
            continue
        still = need - freed
        if mv <= still + 1e-6:
            sell_sh = float(h["shares"])
        else:
            sell_sh = still / px
        cash = _sell_holding_shares(
            holdings,
            cash,
            hid,
            h,
            sell_sh,
            px,
            mark_date=mark_date,
            mode=mode_n,
            trim_log=trim_log,
            reason=reason,
            for_symbol=for_symbol,
        )
        freed += min(mv, still)
    return cash, freed


def _simulate_aggressive_share_level(
    all_dates: list[pd.Timestamp],
    closed: list,
    open_trades: list,
    tickers: dict,
    initial_account_size: float,
    avg_pos: float,
    aggressive_margin_interest: float,
    aggressive_max_multiple: float,
    aggressive_sizing_equity_cap: float = 10.0,
    margin_utilization: float = 1.0,
    aggressive_sell: str = "false",
) -> tuple[list[float], list[int], int, int, int, list[dict]]:
    """
    Aggressive ledger: each new entry sized up to
    ``current_equity * aggressive_max_multiple / avg_pos``, where *current_equity* is
    cash + MTM of open holdings at the **signal date** (prior business day to entry open).

    Total gross is capped at ``equity_at_signal * aggressive_max_multiple`` — a new entry
    only fills remaining room (``max_gross − current_gross``), so ~avg_pos slots share the
    2× equity budget instead of each open name taking a full slot (which blew up with 20+
    concurrent positions).

    When ``aggressive_sell`` is average|losers|winners, existing holdings are sold at the
    new entry open to free gross (and cash if needed) before sizing the entrant.

    Margin interest accrues daily on ``max(0, -cash)``.
    """
    if not all_dates:
        return [], [], 0, 0, 0, []

    leverage = max(float(aggressive_max_multiple), 1.0) * max(0.0, min(float(margin_utilization or 1.0), 1.0))
    avg_pos_f = max(float(avg_pos), 1e-9)
    sizing_eq_cap = max(float(aggressive_sizing_equity_cap), 1.0)
    daily_margin_rate = max(float(aggressive_margin_interest), 0.0) / 365.0
    sell_mode = _normalize_aggressive_sell(aggressive_sell)

    # Trade ledger
    trade_rows = []
    t_id = 0
    for t in closed:
        op = _parse_date(_trade_val(t, "date_opened", "DATE_OPENED"))
        cl = _parse_date(_trade_val(t, "date_closed", "DATE_CLOSED"))
        if op is None or cl is None:
            continue
        entry = float(_trade_val(t, "entry_price", "ENTRY_PRICE", 0) or 0)
        if entry <= 0:
            continue
        trade_rows.append(
            {
                "id": t_id,
                "symbol": str(_trade_val(t, "symbol", "SYMBOL", "") or "").strip(),
                "open": pd.Timestamp(op),
                "close": pd.Timestamp(cl),
                "entry": entry,
                "exit": float(_trade_val(t, "exit_price", "EXIT_PRICE", 0) or 0),
            }
        )
        t_id += 1
    for t in open_trades:
        op = _parse_date(_trade_val(t, "date_opened", "DATE_OPENED"))
        if op is None:
            continue
        entry = float(_trade_val(t, "entry_price", "ENTRY_PRICE", 0) or 0)
        if entry <= 0:
            continue
        trade_rows.append(
            {
                "id": t_id,
                "symbol": str(_trade_val(t, "symbol", "SYMBOL", "") or "").strip(),
                "open": pd.Timestamp(op),
                "close": None,
                "entry": entry,
                "exit": 0.0,
            }
        )
        t_id += 1

    by_open = defaultdict(list)
    by_close = defaultdict(list)
    for tr in trade_rows:
        by_open[pd.Timestamp(tr["open"]).normalize()].append(tr)
        if tr["close"] is not None:
            by_close[pd.Timestamp(tr["close"]).normalize()].append(tr)

    px_arrays: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for sym in {tr["symbol"] for tr in trade_rows}:
        arr = _ticker_close_arrays(tickers.get(sym))
        if arr is not None:
            px_arrays[sym] = arr

    def _get_px(symbol: str, d: pd.Timestamp, entry_px: float, close_px: Optional[float]) -> float:
        d_ns = int(pd.Timestamp(d).normalize().value)
        bundle = px_arrays.get(symbol)
        if bundle is None:
            if close_px and close_px >= entry_px * 0.1:
                return float(close_px)
            return float(entry_px)
        date_i8, closes = bundle
        j = int(np.searchsorted(date_i8, d_ns, side="right")) - 1
        if j >= 0:
            return float(closes[j])
        if close_px and close_px >= entry_px * 0.1:
            return float(close_px)
        return float(entry_px)

    holdings: dict[int, dict] = {}
    cash = float(initial_account_size)
    equity_values: list[float] = []
    pos_values: list[int] = []
    below_or_at_avg_days = 0
    margin_days = 0
    trimmed_days = 0
    trim_log: list[dict] = []

    for d in all_dates:
        d_n = pd.Timestamp(d).normalize()

        # Open: size from equity MTM at signal date (prior business day).
        day_trimmed = False
        for tr in by_open.get(d_n, []):
            signal_d = _prior_business_day(d_n)
            eq_sz = _equity_for_aggressive_sizing(cash, holdings, signal_d, _get_px)
            gross_sig = _gross_holdings_at(holdings, signal_d, _get_px)
            n_open = len(holdings)
            slot_div = max(avg_pos_f, float(n_open + 1))
            # Cap equity used for slot sizing to avoid 10y runaway compound on ~1000 trades.
            eq_for_slot = min(eq_sz, float(initial_account_size) * sizing_eq_cap)
            slot = eq_for_slot * leverage / slot_div
            max_gross = eq_for_slot * leverage
            room = max(0.0, max_gross - gross_sig)

            if sell_mode != "false" and holdings and slot > room + 1e-6:
                cash, _ = _aggressive_sell_for_amount(
                    holdings,
                    cash,
                    slot - room,
                    d_n,
                    sell_mode,
                    _get_px,
                    trim_log=trim_log,
                    reason="free_gross_for_new_entry",
                    for_symbol=str(tr["symbol"]),
                )
                day_trimmed = True
                gross_sig = _gross_holdings_at(holdings, signal_d, _get_px)
                room = max(0.0, max_gross - gross_sig)

            notional = min(slot, room)
            sh = notional / float(tr["entry"]) if tr["entry"] > 0 and notional > 0 else 0.0
            if sh <= 0:
                continue
            cost = sh * float(tr["entry"])

            if sell_mode != "false" and holdings and cash + 1e-6 < cost:
                cash, _ = _aggressive_sell_for_amount(
                    holdings,
                    cash,
                    cost - cash,
                    d_n,
                    sell_mode,
                    _get_px,
                    trim_log=trim_log,
                    reason="free_cash_for_new_entry",
                    for_symbol=str(tr["symbol"]),
                )
                day_trimmed = True

            cash -= cost
            holdings[tr["id"]] = {
                "symbol": tr["symbol"],
                "shares": float(sh),
                "entry": float(tr["entry"]),
                "exit": float(tr["exit"]),
                "close": tr["close"],
            }

        if day_trimmed:
            trimmed_days += 1

        # Close at end of session (before EOD interest).
        for tr in by_close.get(d_n, []):
            h = holdings.pop(tr["id"], None)
            if h is None:
                continue
            px = _get_px(h["symbol"], d_n, h["entry"], h["exit"])
            cash += float(h["shares"]) * px

        gross = 0.0
        for hid, h in holdings.items():
            px = _get_px(
                h["symbol"],
                d_n,
                h["entry"],
                h["exit"] if h["close"] is not None and d_n >= h["close"] else None,
            )
            gross += float(h["shares"]) * px

        equity_eod = cash + gross
        borrowed = max(0.0, -cash)
        if borrowed > 1e-6:
            margin_days += 1
        pos_n = len(holdings)
        if pos_n <= avg_pos_f + 1e-9:
            below_or_at_avg_days += 1

        interest = borrowed * daily_margin_rate
        cash -= interest
        equity_eod -= interest

        equity_values.append(equity_eod)
        pos_values.append(pos_n)

    return equity_values, pos_values, below_or_at_avg_days, margin_days, trimmed_days, trim_log


def compute_equity_metrics(
    closed: list,
    open_trades: list,
    tickers: dict,
    cash: float,
    initial_capital: Optional[float] = None,
    aggressive: bool = False,
    aggressive_margin_interest: float = 0.10,
    aggressive_max_multiple: float = 2.0,
    aggressive_avg_positions: Optional[float] = None,
    aggressive_sizing_equity_cap: float = 10.0,
    margin_utilization: float = 1.0,
    aggressive_sell: str = "false",
    *,
    skip_passive_mtm_for_aggressive: bool = False,
) -> dict:
    """
    Compute Max_Drawdown, Max_Days_Underwater, Pct_Days_Underwater from trade lists and ticker data.
    Called by rocket_brt to populate metrics. Works with BRTTrade objects (symbol, date_opened,
    date_closed, entry_price, exit_price, pnl_dollars) and tickers dict (symbol -> DataFrame with Date/Close).
    Returns dict with Max_Drawdown (float 0-1 or "N/A"), Max_Days_Underwater (int), Pct_Days_Underwater (float).

    ``cash`` is dollars per position (shares = cash / entry_price).

    **Starting equity for the curve:** if ``initial_capital`` is None (default), uses ``cash * 12``
    (legacy DrawdownCalc convention). For BRT_DrawdownCalc charts aligned with BRT_Report / Audit,
    pass ``initial_capital`` explicitly — e.g. the audit row ``brt_cash`` (often ``1e6 / Max_Positions``),
    so the curve starts at that level instead of ``cash * 12``.

    When ``skip_passive_mtm_for_aggressive`` is True and ``aggressive`` is True, passive OHLC is still
    computed for ``Max_Drawdown``; only the optional ``equity_values_regular`` snapshot may be omitted
    (saves memory on large runs). ``Aggressive_Max_Drawdown`` comes from the aggressive ledger when enabled.
    """
    initial_account_size = float(initial_capital) if initial_capital is not None else float(cash) * 12.0

    realized_pnl_events = defaultdict(float)
    unrealized_pnl_timeline = defaultdict(float)
    active_symbols_timeline = defaultdict(set)
    market_max_date = pd.to_datetime(datetime.now().date())
    missing_ticker_trades = 0

    # Cache normalized ticker DataFrames per symbol to avoid df.copy() per trade
    _ticker_cache: dict[str, pd.DataFrame] = {}

    def _get_ticker_df(symbol):
        if symbol in _ticker_cache:
            return _ticker_cache[symbol]
        df = tickers.get(symbol)
        if df is None:
            return None
        df = df.copy()
        if "Date" not in df.columns:
            df = df.reset_index()
        if "Close" not in df.columns:
            df = normalize_ohlc_columns(df)
        if "Date" not in df.columns or "Close" not in df.columns:
            return None
        df["Date"] = pd.to_datetime(df["Date"])
        _ticker_cache[symbol] = df
        return df

    for t in closed:
        sym = str(_trade_val(t, "symbol", "SYMBOL", "") or "").strip()
        start_dt = _parse_date(_trade_val(t, "date_opened", "DATE_OPENED"))
        end_dt = _parse_date(_trade_val(t, "date_closed", "DATE_CLOSED"))
        if start_dt is None or end_dt is None:
            continue
        entry_p = float(_trade_val(t, "entry_price", "ENTRY_PRICE", 0) or 0)
        shares = cash / entry_p if entry_p > 0 else 0
        exit_p = float(_trade_val(t, "exit_price", "EXIT_PRICE", 0) or 0)
        pnl_dollars = float(_trade_val(t, "pnl_dollars", "PNL_DOLLARS", 0) or 0)
        df_ticker = _get_ticker_df(sym)
        if df_ticker is None:
            # No ticker: count position + approximate unrealized PnL (linear) so Max_DD matches audit
            missing_ticker_trades += 1
            _pscale = _pnl_csv_to_cash_scale(entry_p, exit_p, pnl_dollars, cash)
            total_days = max(1, (end_dt - start_dt).days)
            for dt in pd.bdate_range(start=start_dt, end=end_dt):
                active_symbols_timeline[dt].add(sym)
                if dt < end_dt:
                    days_elapsed = (dt - start_dt).days
                    frac = min(1.0, days_elapsed / total_days)
                    unrealized_pnl_timeline[dt] += pnl_dollars * frac * _pscale
            realized_pnl_events[end_dt] = realized_pnl_events.get(end_dt, 0) + pnl_dollars * _pscale
            continue
        if df_ticker["Date"].max() > market_max_date:
            market_max_date = df_ticker["Date"].max()
        window = df_ticker[(df_ticker["Date"] >= start_dt) & (df_ticker["Date"] <= end_dt)].sort_values("Date")
        if window.empty:
            # No ticker data in range: count position + approximate unrealized (linear) for Max_DD
            missing_ticker_trades += 1
            _pscale = _pnl_csv_to_cash_scale(entry_p, exit_p, pnl_dollars, cash)
            total_days = max(1, (end_dt - start_dt).days)
            for dt in pd.bdate_range(start=start_dt, end=end_dt):
                active_symbols_timeline[dt].add(sym)
                if dt < end_dt:
                    days_elapsed = (dt - start_dt).days
                    frac = min(1.0, days_elapsed / total_days)
                    unrealized_pnl_timeline[dt] += pnl_dollars * frac * _pscale
            realized_pnl_events[end_dt] = realized_pnl_events.get(end_dt, 0) + pnl_dollars * _pscale
            continue
        n_window = len(window)
        for i, row in enumerate(window.itertuples(index=False)):
            dt = row.Date
            last_row = i == n_window - 1
            check_p = exit_p if (last_row and exit_p >= entry_p * 0.1) else row.Close
            pnl = (check_p - entry_p) * shares
            active_symbols_timeline[dt].add(sym)
            if last_row:
                # Use price path at ``cash`` sizing; CSV PNL_DOLLARS may be on a legacy notional (~47.5k).
                realized_pnl_events[dt] += pnl
            else:
                unrealized_pnl_timeline[dt] += pnl

    for t in open_trades:
        sym = str(_trade_val(t, "symbol", "SYMBOL", "") or "").strip()
        start_dt = _parse_date(_trade_val(t, "date_opened", "DATE_OPENED"))
        if start_dt is None:
            continue
        entry_p = float(_trade_val(t, "entry_price", "ENTRY_PRICE", 0) or 0)
        shares = cash / entry_p if entry_p > 0 else 0
        df_ticker = _get_ticker_df(sym)
        if df_ticker is None:
            # No ticker: still count position for chart
            missing_ticker_trades += 1
            for dt in pd.bdate_range(start=start_dt, end=market_max_date):
                active_symbols_timeline[dt].add(sym)
            continue
        end_dt = df_ticker["Date"].max()
        window = df_ticker[(df_ticker["Date"] >= start_dt) & (df_ticker["Date"] <= end_dt)].sort_values("Date")
        if window.empty:
            missing_ticker_trades += 1
            for dt in pd.bdate_range(start=start_dt, end=end_dt):
                active_symbols_timeline[dt].add(sym)
            continue
        for row in window.itertuples(index=False):
            dt = row.Date
            pnl = (row.Close - entry_p) * shares
            active_symbols_timeline[dt].add(sym)
            unrealized_pnl_timeline[dt] += pnl

    all_dates = sorted(active_symbols_timeline.keys())
    if not all_dates:
        return {"Max_Drawdown": "N/A", "Max_Days_Underwater": 0, "Pct_Days_Underwater": 0.0}

    # Include inactive business days explicitly so equity curve shows flat cash days with 0 positions.
    # End at market_max_date only when open trades exist; otherwise stop at last active day.
    curve_end = market_max_date if open_trades else all_dates[-1]
    full_dates = list(pd.bdate_range(start=all_dates[0], end=curve_end))
    for dt in full_dates:
        if dt not in active_symbols_timeline:
            active_symbols_timeline[dt] = set()
        if dt not in unrealized_pnl_timeline:
            unrealized_pnl_timeline[dt] = 0.0
    all_dates = full_dates

    running_realized = 0.0
    port_hwm = initial_account_size
    max_port_dd = 0.0
    history_equity = []
    history_positions = []
    underwater_days = 0
    current_underwater_streak = 0
    max_underwater_days = 0

    passive_equity_snapshot: Optional[list[float]] = None
    aggressive_max_dd_raw: float = 0.0
    aggressive_max_underwater_days: int = 0
    aggressive_pct_underwater: float = 0.0

    for dt in all_dates:
        running_realized += realized_pnl_events.get(dt, 0)
        current_floating = unrealized_pnl_timeline.get(dt, 0.0)
        current_equity = initial_account_size + running_realized + current_floating
        history_equity.append(current_equity)
        history_positions.append(len(active_symbols_timeline.get(dt, set())))
        if current_equity > port_hwm:
            port_hwm = current_equity
            current_underwater_streak = 0
        if port_hwm > 0:
            dd = (port_hwm - current_equity) / port_hwm
            if dd > max_port_dd:
                max_port_dd = dd
            if current_equity < port_hwm:
                current_underwater_streak += 1
                max_underwater_days = max(max_underwater_days, current_underwater_streak)
                underwater_days += 1
            else:
                current_underwater_streak = 0

    regular_max_dd = max_port_dd
    regular_max_underwater_days = max_underwater_days
    regular_pct_underwater = (underwater_days / len(all_dates) * 100) if all_dates else 0.0

    if aggressive and history_equity and history_positions:
        pos_nonzero = [float(p) for p in history_positions if float(p) > 0]
        avg_pos = float(aggressive_avg_positions) if aggressive_avg_positions and aggressive_avg_positions > 0 else (
            sum(pos_nonzero) / len(pos_nonzero) if pos_nonzero else 0.0
        )
        if avg_pos > 0:
            if not skip_passive_mtm_for_aggressive:
                passive_equity_snapshot = list(history_equity)
            (
                history_equity,
                history_positions,
                below_or_at_avg_days,
                margin_days,
                trimmed_days,
                trim_log,
            ) = _simulate_aggressive_share_level(
                all_dates,
                closed,
                open_trades,
                tickers,
                float(initial_account_size),
                float(avg_pos),
                float(aggressive_margin_interest),
                float(aggressive_max_multiple),
                float(aggressive_sizing_equity_cap),
                float(margin_utilization),
                _normalize_aggressive_sell(aggressive_sell),
            )
            aggressive_max_dd_raw, aggressive_max_underwater_days, aggressive_pct_underwater = (
                _underwater_and_max_dd_from_equity_series(history_equity, float(initial_account_size))
            )
            max_port_dd = regular_max_dd
            max_underwater_days = regular_max_underwater_days
            pct_underwater = regular_pct_underwater
        else:
            below_or_at_avg_days = 0
            margin_days = 0
            trimmed_days = 0
            trim_log = []
            pct_underwater = regular_pct_underwater
    else:
        below_or_at_avg_days = 0
        margin_days = 0
        trimmed_days = 0
        avg_pos = 0.0
        trim_log = []
        pct_underwater = (underwater_days / len(all_dates) * 100) if all_dates else 0.0

    out = {
        "Max_Drawdown": f"{max_port_dd:.2%}" if max_port_dd > 0 else "N/A",
        "Max_Days_Underwater": max_underwater_days,
        "Pct_Days_Underwater": f"{pct_underwater:.1f}%",
    }
    out["equity_dates"] = all_dates
    out["equity_values"] = history_equity
    out["equity_positions"] = history_positions
    if passive_equity_snapshot is not None and len(passive_equity_snapshot) == len(history_equity):
        out["equity_values_regular"] = passive_equity_snapshot
    out["_max_port_dd_raw"] = max_port_dd  # for run_audit chart annotation
    out["_missing_ticker_trades"] = missing_ticker_trades  # diagnostic: trades without ticker data
    out["_initial_account_size"] = float(initial_account_size)  # replay Max_DD from saved curve (rocket + DrawdownCalc)
    out["_final_equity"] = float(history_equity[-1]) if history_equity else float(initial_account_size)
    out["_equity_total_pnl"] = out["_final_equity"] - float(initial_account_size)
    out["_aggressive"] = bool(aggressive)
    if aggressive:
        out["Aggressive_Avg_Positions"] = round(float(avg_pos), 4) if avg_pos > 0 else 0.0
        out["Aggressive_Days_AtOrBelow_Avg"] = int(below_or_at_avg_days)
        out["Aggressive_Days_In_Margin"] = int(margin_days)
        out["Aggressive_Days_Trimmed_Over_2xAvg"] = int(trimmed_days)
        out["aggressive_trim_log"] = trim_log
        out["Aggressive_Max_Drawdown"] = (
            f"{aggressive_max_dd_raw:.2%}" if aggressive_max_dd_raw > 0 else "N/A"
        )
        out["_aggressive_max_dd_raw"] = float(aggressive_max_dd_raw)
        out["Aggressive_Max_Days_Underwater"] = int(aggressive_max_underwater_days)
        out["Aggressive_Pct_Days_Underwater"] = f"{aggressive_pct_underwater:.1f}%"
    return out


def _underwater_and_max_dd_from_equity_series(
    equity_values: list,
    initial_account_size: float,
) -> tuple[float, int, float]:
    """
    Running high-water-mark max drawdown + underwater day stats (same rules as compute_equity_metrics).
    """
    if not equity_values:
        return 0.0, 0, 0.0
    port_hwm = float(initial_account_size)
    max_port_dd = 0.0
    underwater_days = 0
    current_underwater_streak = 0
    max_underwater_days = 0
    for eq in equity_values:
        eq = float(eq)
        if eq > port_hwm:
            port_hwm = eq
            current_underwater_streak = 0
        if port_hwm > 0:
            dd = (port_hwm - eq) / port_hwm
            if dd > max_port_dd:
                max_port_dd = dd
            if eq < port_hwm:
                current_underwater_streak += 1
                max_underwater_days = max(max_underwater_days, current_underwater_streak)
                underwater_days += 1
            else:
                current_underwater_streak = 0
    pct_uw = (underwater_days / len(equity_values) * 100) if equity_values else 0.0
    return max_port_dd, max_underwater_days, pct_uw


def compute_realized_ledger_equity_metrics(
    closed: list,
    open_trades: list,
    initial_capital: float,
    *,
    extend_open_to_today: bool = True,
) -> dict:
    """
    Equity and Max_Drawdown from **BRT_Closed only**: account = initial_capital + cumulative
    ``PNL_DOLLARS`` realized on each ``DATE_CLOSED`` (no OHLC mark-to-market on open trades).

    This matches blotter / spreadsheet math from the Closed file. Daily series is flat between
    close dates and steps on days when trades settle; position counts use [DATE_OPENED, DATE_CLOSED]
    inclusively for closed trades and open through calendar end for ``open_trades``.
    """
    pnl_by_close: dict = defaultdict(float)
    intervals: list[tuple[pd.Timestamp, Optional[pd.Timestamp], str]] = []

    for t in closed:
        start_dt = _parse_date(_trade_val(t, "date_opened", "DATE_OPENED"))
        end_dt = _parse_date(_trade_val(t, "date_closed", "DATE_CLOSED"))
        if end_dt is None:
            continue
        pnl = float(_trade_val(t, "pnl_dollars", "PNL_DOLLARS", 0) or 0)
        d_end = pd.Timestamp(end_dt).normalize()
        pnl_by_close[d_end] += pnl
        if start_dt is not None:
            intervals.append(
                (pd.Timestamp(start_dt).normalize(), d_end, str(_trade_val(t, "symbol", "SYMBOL", "") or ""))
            )

    for t in open_trades:
        start_dt = _parse_date(_trade_val(t, "date_opened", "DATE_OPENED"))
        if start_dt is None:
            continue
        intervals.append(
            (pd.Timestamp(start_dt).normalize(), None, str(_trade_val(t, "symbol", "SYMBOL", "") or ""))
        )

    initial_f = float(initial_capital)
    if not pnl_by_close and not intervals:
        return {
            "Max_Drawdown": "N/A",
            "Max_Days_Underwater": 0,
            "Pct_Days_Underwater": "0.0%",
            "equity_dates": [],
            "equity_values": [],
            "equity_positions": [],
            "_max_port_dd_raw": 0.0,
            "_missing_ticker_trades": 0,
            "_initial_account_size": initial_f,
            "_equity_basis": "realized_ledger",
        }

    if pnl_by_close:
        close_dates_sorted = sorted(pnl_by_close.keys())
        last_close = close_dates_sorted[-1]
    else:
        close_dates_sorted = []
        last_close = max(iv[0] for iv in intervals)

    if intervals:
        first_open = min(iv[0] for iv in intervals)
    else:
        first_open = close_dates_sorted[0]

    end_cal = last_close
    if open_trades and extend_open_to_today:
        end_cal = max(last_close, pd.Timestamp(datetime.now().date()))
    elif open_trades:
        end_cal = max(last_close, max((iv[0] for iv in intervals), default=last_close))

    all_dates = list(pd.bdate_range(start=first_open, end=end_cal))
    sorted_pnls = sorted(pnl_by_close.items())
    pnl_i = 0
    pnl_cum = 0.0
    history_equity: list[float] = []
    history_positions: list[int] = []

    for d in all_dates:
        while pnl_i < len(sorted_pnls) and sorted_pnls[pnl_i][0] <= d:
            pnl_cum += sorted_pnls[pnl_i][1]
            pnl_i += 1
        history_equity.append(initial_f + pnl_cum)
        npos = 0
        for op, cl, _sym in intervals:
            if d < op:
                continue
            if cl is None:
                npos += 1
            elif d <= cl:
                npos += 1
        history_positions.append(npos)

    max_port_dd, max_uw_days, pct_uw = _underwater_and_max_dd_from_equity_series(history_equity, initial_f)

    return {
        "Max_Drawdown": f"{max_port_dd:.2%}" if max_port_dd > 0 else "N/A",
        "Max_Days_Underwater": max_uw_days,
        "Pct_Days_Underwater": f"{pct_uw:.1f}%",
        "equity_dates": all_dates,
        "equity_values": history_equity,
        "equity_positions": history_positions,
        "_max_port_dd_raw": max_port_dd,
        "_missing_ticker_trades": 0,
        "_initial_account_size": initial_f,
        "_equity_basis": "realized_ledger",
    }


def _apply_passive_equity_primary(metrics: dict, *, aggressive_chart: bool) -> None:
    """
    When a saved curve includes Equity_Regular (passive / audit-aligned), use it as the
    chart and Max_DD series unless --aggressive requests the dual-line aggressive view.
    """
    reg = metrics.get("equity_values_regular")
    dates = metrics.get("equity_dates") or []
    if aggressive_chart or not reg or len(reg) != len(dates):
        return
    init = metrics.get("_initial_account_size")
    try:
        init_f = float(init) if init is not None and str(init).strip() != "" else float("nan")
    except (TypeError, ValueError):
        init_f = float("nan")
    if not (init_f > 0 and np.isfinite(init_f)):
        init_f = float(metrics["equity_values"][0]) if metrics.get("equity_values") else float("nan")
    metrics["equity_values_aggressive_saved"] = list(metrics.get("equity_values") or [])
    metrics["equity_values"] = list(reg)
    metrics["_max_port_dd_raw"] = max_drawdown_from_equity_path(reg, init_f if init_f > 0 else None)
    metrics["Max_Drawdown"] = (
        f"{metrics['_max_port_dd_raw']:.2%}" if metrics["_max_port_dd_raw"] > 0 else "N/A"
    )
    metrics["_aggressive"] = False
    metrics["_chart_primary"] = "regular"
    print(
        "[OK] Chart/Max_DD use Equity_Regular (passive, aligns with audit Total_PNL). "
        "Pass --aggressive to overlay the aggressive ledger curve."
    )


def max_drawdown_from_equity_path(equity_values: list, initial_account_size: Optional[float] = None) -> float:
    """
    Same peak-to-trough rule as compute_equity_metrics: running high-water mark on the equity series.
    If initial_account_size is set, seed HWM with it (matches first loop iteration before day 1 equity).
    If None, seed with first equity point (legacy fallback for old saved curves without meta).
    """
    if not equity_values:
        return 0.0
    eqs = [float(x) for x in equity_values]
    port_hwm = float(initial_account_size) if initial_account_size is not None else eqs[0]
    max_port_dd = 0.0
    for eq in eqs:
        if eq > port_hwm:
            port_hwm = eq
        if port_hwm > 0:
            dd = (port_hwm - eq) / port_hwm
            if dd > max_port_dd:
                max_port_dd = dd
    return max_port_dd


def _canonical_equity_paths(base_dir: str, timestamp: str, file_prefix: str = "BRT") -> tuple[str, str]:
    curve = os.path.join(base_dir, f"{file_prefix}_EquityCurve_{timestamp}.csv")
    meta = os.path.join(base_dir, f"{file_prefix}_EquityMeta_{timestamp}.csv")
    return curve, meta


def load_canonical_equity_bundle(
    base_dir: str, timestamp: str, file_prefix: str = "BRT"
) -> Optional[tuple[list, list, list, dict, Optional[list[float]]]]:
    """
    Load {prefix}_EquityCurve_<ts>.csv (+ optional {prefix}_EquityMeta_<ts>.csv) from rocket_brt / rocket_MTS.
    Returns (equity_dates, equity_values, positions_list_or_empty, meta_dict, equity_regular_or_none) or None.
    Optional column ``Equity_Regular`` is the passive OHLC curve when the primary ``Equity`` column is aggressive.
    """
    curve_path, meta_path = _canonical_equity_paths(base_dir, timestamp, file_prefix)
    if not os.path.isfile(curve_path):
        return None
    try:
        df_c = pd.read_csv(curve_path, index_col=False)
        df_c.columns = [str(c).strip() for c in df_c.columns]
        dcol = next((c for c in df_c.columns if c.lower() == "date"), None)
        ecol = next((c for c in df_c.columns if c.lower() == "equity"), None)
        if dcol is None or ecol is None:
            return None
        dates = pd.to_datetime(df_c[dcol]).tolist()
        values = [float(x) for x in df_c[ecol].tolist()]
        pos_col = next((c for c in df_c.columns if c.lower() == "positions"), None)
        positions = [int(x) for x in df_c[pos_col].tolist()] if pos_col and len(df_c[pos_col]) == len(values) else []
        eq_reg_col = next((c for c in df_c.columns if c.lower() == "equity_regular"), None)
        regular_vals: Optional[list[float]] = None
        if eq_reg_col is not None and len(df_c[eq_reg_col]) == len(values):
            regular_vals = [float(x) for x in df_c[eq_reg_col].tolist()]
        meta: dict = {}
        if os.path.isfile(meta_path):
            df_m = pd.read_csv(meta_path, index_col=False)
            if not df_m.empty:
                row = df_m.iloc[0]
                for c in df_m.columns:
                    k = str(c).strip()
                    meta[k] = row[c]
        return (dates, values, positions, meta, regular_vals)
    except Exception:
        return None


def _resolve_ticker_dir(ticker_dir):
    """Resolve ticker_dir to absolute path. Matches rocket_brt/optimizer: data/newdata/data relative to repo."""
    ticker_dir = os.path.abspath(ticker_dir)
    if os.path.isfile(os.path.join(ticker_dir, "SPY.csv")):
        return ticker_dir
    script_dir = Path(__file__).parent.resolve()
    repo_root = script_dir.parent
    # Same default as rocket_brt and BRT_Optimizer: data/newdata/data
    for candidate in [
        repo_root / "data" / "newdata" / "data",
        repo_root / "data",
        script_dir.parent / "data" / "newdata" / "data",
    ]:
        if (candidate / "SPY.csv").exists():
            return str(candidate)
    return ticker_dir


def summarize_underwater_duration_days(durations) -> dict[str, float | int]:
    """
    Stats from underwater ``Duration_Days`` values.

    * avg — mean of all periods
    * p90_top10_avg — mean of the longest ceil(10% * n) periods (top decile by duration)
    """
    vals: list[float] = []
    for x in durations:
        try:
            f = float(x)
            if not math.isnan(f):
                vals.append(f)
        except (TypeError, ValueError):
            continue
    if not vals:
        return {"count": 0, "max": 0.0, "avg": 0.0, "p90_top10_avg": 0.0}
    n = len(vals)
    avg = sum(vals) / n
    k = max(1, math.ceil(n * 0.10))
    top = sorted(vals, reverse=True)[:k]
    p90_avg = sum(top) / len(top)
    return {"count": n, "max": max(vals), "avg": avg, "p90_top10_avg": p90_avg}


def generate_underwater_report(df_equity, timestamp, output_dir=None, prefix="BRT"):
    """Build underwater periods report. Writes {prefix}_underwater_{timestamp}.csv.

    Returns a dict with max/avg/p90 duration stats (empty periods → zeros).
    """
    df = df_equity.sort_values("Date").reset_index(drop=True)
    df["HWM"] = df["Equity"].cummax()
    df["Is_Underwater"] = df["Equity"] < df["HWM"]
    df["Drawdown_Group"] = (df["Is_Underwater"] != df["Is_Underwater"].shift()).cumsum()
    underwater_groups = df[df["Is_Underwater"]].groupby("Drawdown_Group")
    report_data = []
    for _, group in underwater_groups:
        hwm_idx = group.index[0] - 1
        hwm_date = pd.Timestamp(df.loc[hwm_idx, "Date"]) if hwm_idx >= 0 else pd.Timestamp(group["Date"].iloc[0])
        hwm_val = float(df.loc[hwm_idx, "Equity"]) if hwm_idx >= 0 else float(group["Equity"].iloc[0])
        trough_row = group.loc[group["Equity"].idxmin()]
        trough_date = trough_row["Date"]
        trough_val = float(trough_row["Equity"])
        dd_pct = (trough_val - hwm_val) / hwm_val * 100 if hwm_val else 0
        recovery_idx = group.index[-1] + 1
        hwm_ts = pd.Timestamp(hwm_date)
        trough_ts = pd.Timestamp(trough_date)
        days_to_trough = (trough_ts - hwm_ts).days
        if recovery_idx < len(df):
            recovery_date = df.loc[recovery_idx, "Date"]
            recovery_ts = pd.Timestamp(recovery_date)
            duration = (recovery_ts - hwm_ts).days
            days_since_trough = (recovery_ts - trough_ts).days
        else:
            recovery_date = "Still Underwater"
            today_ts = pd.Timestamp("today").normalize()
            duration = (today_ts - hwm_ts).days
            days_since_trough = (today_ts - trough_ts).days
        report_data.append({
            "HWM_Date": hwm_date,
            "HWM_Value": round(hwm_val, 2),
            "Trough_Date": trough_date,
            "Trough_Value": round(trough_val, 2),
            "Drawdown_Pct": round(dd_pct, 2),
            "Days_to_trough": days_to_trough,
            "Days_since_trough": days_since_trough,
            "Recovery_Date": recovery_date,
            "Duration_Days": duration,
        })
    report_df = pd.DataFrame(report_data).sort_values("Duration_Days", ascending=False)
    report_name = f"{prefix}_underwater_{timestamp}.csv"
    out_path = os.path.join(output_dir, report_name) if output_dir else report_name
    report_df.to_csv(out_path, index=False)
    summary = summarize_underwater_duration_days(
        report_df["Duration_Days"] if not report_df.empty else []
    )
    return {
        "max_duration_days": int(summary["max"]),
        "avg_days_underwater": round(float(summary["avg"]), 3),
        "p90_days_underwater": round(float(summary["p90_top10_avg"]), 3),
        "underwater_period_count": int(summary["count"]),
    }


def _parse_chart_date(val):
    """Parse date from CSV for chart (YYYYMMDD or YYYY-MM-DD)."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(int(float(val))) if isinstance(val, (int, float)) else str(val).strip()
    if not s:
        return None
    s = s.replace("-", "")[:8]
    if len(s) != 8:
        return None
    try:
        return pd.Timestamp(s[:4] + "-" + s[4:6] + "-" + s[6:8])
    except Exception:
        return None


def _draw_trade_bands_chart(symbol, df_ticker, closed_trades, open_trades, out_path, band_pct=0.02,
                            would_have_trades=None, start_ts=None, end_ts=None):
    """Draw chart: bands from closed (blue) and open (green/teal/coral); would-have (amber); verticals: closed=green/red, open=orange, would-have=magenta dashed."""
    try:
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
    except ImportError:
        return
    if "Date" not in df_ticker.columns or "Close" not in df_ticker.columns:
        return
    df = df_ticker.copy()
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").set_index("Date")
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(df.index, df["Close"], color="black", linewidth=1, label="Close")

    def in_range(ts):
        if ts is None:
            return True
        if start_ts is not None and ts < start_ts:
            return False
        if end_ts is not None and ts > end_ts:
            return False
        return True

    closed_trades = [t for t in closed_trades if in_range(_parse_chart_date(t.get("DATE_OPENED")))]
    open_trades = [t for t in open_trades if in_range(_parse_chart_date(t.get("DATE_OPENED")))]
    would_have_trades = would_have_trades or []
    would_have_trades = [t for t in would_have_trades if in_range(_parse_chart_date(t.get("WOULD_ENTER_DATE")) or _parse_date(t.get("WOULD_ENTER_DATE")))]

    def draw_band(zc_val, color, alpha_span=0.12, alpha_line=0.5):
        if not zc_val or float(zc_val) <= 0:
            return
        zc_f = float(zc_val)
        zl = zc_f * (1 - band_pct)
        zh = zc_f * (1 + band_pct)
        ax.axhline(y=zc_f, color=color, alpha=alpha_line, linewidth=0.8)
        ax.axhspan(zl, zh, alpha=alpha_span, color=color)

    seen_zc = set()
    for ct in closed_trades:
        zc = ct.get("ZONE_CENTER")
        if zc is not None and float(zc) > 0 and zc not in seen_zc:
            seen_zc.add(zc)
            draw_band(zc, "blue", alpha_span=0.12, alpha_line=0.4)
    for ot in open_trades:
        draw_band(ot.get("ZONE_CENTER"), "green", alpha_span=0.15, alpha_line=0.6)
        draw_band(ot.get("ZONE_ABOVE_CENTER"), "teal", alpha_span=0.1, alpha_line=0.5)
        draw_band(ot.get("ZONE_BELOW_CENTER"), "coral", alpha_span=0.1, alpha_line=0.5)
    seen_wh_zc = set()
    for wh in would_have_trades:
        zc = wh.get("ZONE_CENTER")
        if zc is not None and float(zc) > 0 and zc not in seen_wh_zc:
            seen_wh_zc.add(zc)
            draw_band(zc, "darkorange", alpha_span=0.08, alpha_line=0.45)

    for ct in closed_trades:
        dop = _parse_chart_date(ct.get("DATE_OPENED"))
        dcl = _parse_chart_date(ct.get("DATE_CLOSED"))
        if dop is not None:
            ax.axvline(x=dop, color="green", alpha=0.5, linestyle="--")
        if dcl is not None:
            ax.axvline(x=dcl, color="red", alpha=0.5, linestyle="--")
    for ot in open_trades:
        dop = _parse_chart_date(ot.get("DATE_OPENED"))
        if dop is not None:
            ax.axvline(x=dop, color="orange", alpha=0.6, linewidth=1.2, linestyle="-")
    for wh in would_have_trades:
        dop = _parse_chart_date(wh.get("WOULD_ENTER_DATE")) or _parse_date(wh.get("WOULD_ENTER_DATE"))
        if dop is not None:
            ax.axvline(x=dop, color="magenta", alpha=0.5, linewidth=1, linestyle=":")

    title = f"BRT: {symbol} - Bands (closed=blue, open=green"
    if would_have_trades:
        title += ", would-have=amber/magenta"
    title += ") | green/red=closed, orange=open"
    if would_have_trades:
        title += ", dotted=would-have"
    ax.set_title(title)
    ax.set_ylabel("Price")
    if start_ts is not None or end_ts is not None:
        xmin = start_ts if start_ts is not None else df.index.min()
        xmax = end_ts if end_ts is not None else df.index.max()
        ax.set_xlim(xmin, xmax)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()


def run_audit(
    closed_path,
    ticker_dir,
    cash: Optional[float] = None,
    output_dir=None,
    symbol=None,
    show_would_have=False,
    would_have_path=None,
    start_date=None,
    end_date=None,
    initial_capital=None,
    use_audit: bool = True,
    use_saved_equity: bool = False,
    no_saved_equity: bool = False,
    force_reconstruct: bool = False,
    aggressive: bool = False,
):
    """
    Reconstruct BRT portfolio equity from Closed (and optional Open) CSVs.

    When ``BRT_EquityCurve_<ts>.csv`` exists next to the Closed file (from rocket_brt), it is
    **loaded by default** so Max_DD matches the audit and BRT_EquityMeta. Use ``no_saved_equity``
    or ``force_reconstruct`` to rebuild from OHLC only.

    Saved curves from ``--aggressive`` rocket_brt runs store aggressive ``Equity`` plus ``Equity_Regular``
    (passive OHLC; aligns with audit ``Total_PNL``). **By default** this tool charts ``Equity_Regular``
    and Max_DD from that series. Pass ``aggressive=True`` only to overlay the aggressive ledger (blue)
    with passive (orange). OHLC rebuild uses passive sizing unless ``aggressive=True``.

    Otherwise uses ``compute_equity_metrics`` on OHLC (``initial_capital`` + realized + unrealized).
    closed_path: path to BRT_Closed_<timestamp>.csv
    ticker_dir: directory with per-symbol CSVs (use same path as rocket_brt's data_dir for band charts + SPY)
    cash: dollars per position (shares = cash / entry). Must match ``PNL_DOLLARS`` in BRT_Closed.
        Default None: read ``brt_cash`` from BRT_Audit_Report / BRT_Report next to the Closed file (same timestamp).
        Fallback 47500 if no audit (--no-audit or missing file).
    initial_capital: starting equity for the curve and SPY benchmark. Default None: 500,000.
        This is independent from per-trade ``cash`` / ``brt_cash``.
    use_audit: when True (default), load ``cash`` from audit CSVs if not passed explicitly.
    use_saved_equity: kept for callers; canonical curve is auto-used when the file exists unless
        no_saved_equity / force_reconstruct (passing True does not disable auto-load).
    no_saved_equity: when True, never read BRT_EquityCurve; always OHLC-reconstruct.
    force_reconstruct: rebuild from daily OHLC; ignores BRT_EquityCurve even if present.
    output_dir: where to write chart and CSVs (default: same dir as closed_path)
    symbol: if set, only trades for this symbol (e.g. NVDA) are used; default None = all symbols
    show_would_have: if True, load would-have CSV and draw those zones on band charts (different color)
    would_have_path: path to BRT_WouldHave_<ts>.csv (default: same dir as closed, same timestamp)
    start_date, end_date: optional YYYY-MM-DD to restrict band chart and timeline to a date range
    """
    base_dir = os.path.dirname(os.path.abspath(closed_path))
    out_dir = output_dir if output_dir is not None else base_dir
    ticker_dir = _resolve_ticker_dir(os.path.abspath(ticker_dir))
    print(f"[OK] Ticker dir: {ticker_dir}")
    if symbol:
        print(f"[OK] Symbol filter: {symbol.upper()}")

    filename = os.path.basename(closed_path)
    ts_match = re.search(r"(\d{12})", filename, re.IGNORECASE)
    timestamp = ts_match.group(1) if ts_match else "Report"
    if filename.startswith("MTS_Closed_"):
        file_prefix = "MTS"
    elif filename.startswith("IND_Closed_"):
        file_prefix = "IND"
    elif filename.startswith("BRT_Closed_"):
        file_prefix = "BRT"
    else:
        file_prefix = "BRT"
    _launcher = "rocket_brt" if file_prefix in ("BRT", "IND") else "rocket_MTS"
    audit_row = load_audit_row(base_dir, timestamp, file_prefix=file_prefix) if use_audit else None

    init_explicit: bool = initial_capital is not None
    if cash is None:
        if audit_row:
            cash = float(audit_row["audit_cash"])
            print(f"[OK] cash from {audit_row['source']}: {cash:,.0f}")
        else:
            cash = 47500.0
            print(
                f"[OK] cash default 47,500 (no {file_prefix}_Audit_Report / {file_prefix}_Report for this timestamp; "
                "use --cash or add audit CSV)"
            )
    else:
        print(f"[OK] cash (arg): {float(cash):,.0f}")

    if initial_capital is None:
        initial_capital = 500000.0
        print(f"[OK] initial_capital default: {initial_capital:,.0f}")
    elif init_explicit:
        print(f"[OK] initial_capital (arg): {float(initial_capital):,.0f}")

    _baseline = float(initial_capital)
    print(f"[OK] Equity baseline: initial_capital={_baseline:,.0f} (per-trade cash={float(cash):,.0f})")

    # Optional timeline (for band chart)
    start_ts = _parse_date(start_date) if start_date else None
    end_ts = _parse_date(end_date) if end_date else None
    if start_ts or end_ts:
        print(f"[OK] Timeline: {start_date or '...'} to {end_date or '...'}")
    open_path = os.path.join(base_dir, f"{file_prefix}_Open_{timestamp}.csv")
    would_have_path_resolved = would_have_path or os.path.join(base_dir, f"{file_prefix}_WouldHave_{timestamp}.csv")

    print(f"[FILE] CLOSED: {closed_path}")
    if os.path.exists(open_path):
        print(f"[FILE] OPEN:   {open_path}")
    else:
        print(f"[WARN] OPEN file not found: {open_path}")

    required_closed = ["SYMBOL", "DATE_OPENED", "ENTRY_PRICE", "DATE_CLOSED", "EXIT_PRICE"]
    try:
        df_closed = pd.read_csv(closed_path, index_col=False)
        df_closed.columns = [c.strip() for c in df_closed.columns]
        missing = [c for c in required_closed if c not in df_closed.columns]
        if missing:
            print(f"[ERR] Closed CSV missing columns: {missing}. Found: {list(df_closed.columns)[:15]}")
            return
    except Exception as e:
        print(f"[ERR] Loading CSV: {e}")
        return

    if symbol:
        sym_upper = str(symbol).strip().upper()
        df_closed = df_closed[df_closed["SYMBOL"].astype(str).str.strip().str.upper() == sym_upper]
        if df_closed.empty:
            print(f"[ERR] No rows for symbol {sym_upper} in {closed_path}")
            return

    df_open = pd.DataFrame()
    if os.path.exists(open_path):
        df_open = pd.read_csv(open_path, index_col=False)
        df_open.columns = [c.strip() for c in df_open.columns]
        if not all(c in df_open.columns for c in ["SYMBOL", "DATE_OPENED", "ENTRY_PRICE"]):
            df_open = pd.DataFrame()
        elif symbol:
            sym_upper = str(symbol).strip().upper()
            df_open = df_open[df_open["SYMBOL"].astype(str).str.strip().str.upper() == sym_upper]

    # Build closed list (dicts with keys matching compute_equity_metrics / _trade_val)
    closed = []
    for _, row in df_closed.iterrows():
        closed.append({
            "SYMBOL": str(row["SYMBOL"]).strip(),
            "DATE_OPENED": row["DATE_OPENED"],
            "DATE_CLOSED": row["DATE_CLOSED"],
            "ENTRY_PRICE": clean_numeric(row["ENTRY_PRICE"]),
            "EXIT_PRICE": clean_numeric(row["EXIT_PRICE"]),
            "PNL_DOLLARS": clean_numeric(row["PNL_DOLLARS"]) if "PNL_DOLLARS" in df_closed.columns else 0.0,
        })

    open_trades = []
    if not df_open.empty:
        for _, row in df_open.iterrows():
            open_trades.append({
                "SYMBOL": str(row["SYMBOL"]).strip(),
                "DATE_OPENED": row["DATE_OPENED"],
                "ENTRY_PRICE": clean_numeric(row["ENTRY_PRICE"]),
            })

    if audit_row and "Total_PNL" in audit_row and "PNL_DOLLARS" in df_closed.columns:
        sum_closed = sum(clean_numeric(x) for x in df_closed["PNL_DOLLARS"])
        exp = float(audit_row["Total_PNL"])
        if abs(exp) > 1e-6 and abs(sum_closed - exp) / abs(exp) > 0.02:
            print(
                f"[WARN] Sum(PNL_DOLLARS)={sum_closed:,.0f} vs audit Total_PNL={exp:,.0f} "
                f"({audit_row.get('source', '')}). Old {file_prefix}_Closed (pre-scale) or wrong --cash? "
                f"Re-run {_launcher} or pass --cash to match Closed."
            )

    # Load would-have entries (maturities blocked only by growth/tight_range/consolidation)
    would_have_by_symbol = {}
    if show_would_have and os.path.isfile(would_have_path_resolved):
        try:
            df_wh = pd.read_csv(would_have_path_resolved, index_col=False)
            df_wh.columns = [c.strip() for c in df_wh.columns]
            for c in ["SYMBOL", "ZONE_CENTER", "WOULD_ENTER_DATE", "REJECT_REASON"]:
                if c not in df_wh.columns:
                    df_wh = pd.DataFrame()
                    break
            if not df_wh.empty:
                if symbol:
                    sym_upper = str(symbol).strip().upper()
                    df_wh = df_wh[df_wh["SYMBOL"].astype(str).str.strip().str.upper() == sym_upper]
                for _, row in df_wh.iterrows():
                    sym_wh = str(row["SYMBOL"]).strip()
                    would_have_by_symbol.setdefault(sym_wh, []).append({
                        "ZONE_CENTER": clean_numeric(row.get("ZONE_CENTER")),
                        "WOULD_ENTER_DATE": row.get("WOULD_ENTER_DATE"),
                        "REJECT_REASON": row.get("REJECT_REASON", ""),
                    })
                print(f"[OK] Would-have: {would_have_path_resolved} ({sum(len(v) for v in would_have_by_symbol.values())} entries)")
        except Exception as e:
            print(f"[WARN] Could not load would-have CSV: {e}")
    elif show_would_have:
        print(f"[WARN] Would-have not found: {would_have_path_resolved} (run {_launcher} with --emit-would-have)")

    # Load tickers for all symbols in closed + open (same format as rocket_brt)
    symbols_needed = set()
    for t in closed:
        symbols_needed.add(t["SYMBOL"])
    for t in open_trades:
        symbols_needed.add(t["SYMBOL"])
    if show_would_have and would_have_by_symbol:
        symbols_needed.update(would_have_by_symbol.keys())
    tickers = {}
    missing_symbols = []
    for sym in sorted(symbols_needed):
        ticker_file = os.path.join(ticker_dir, f"{sym}.csv")
        if not os.path.exists(ticker_file):
            missing_symbols.append(sym)
            continue
        try:
            df_t = pd.read_csv(ticker_file)
            df_t = normalize_ohlc_columns(df_t)
            if "Date" not in df_t.columns or "Close" not in df_t.columns:
                missing_symbols.append(sym)
                continue
            df_t["Date"] = pd.to_datetime(df_t["Date"])
            if df_t.index.name == "Date" or "Date" not in df_t.columns:
                pass
            tickers[sym] = df_t
        except Exception as e:
            print(f"[WARN] Skip ticker {sym}: {e}")
            missing_symbols.append(sym)
    if missing_symbols:
        print(f"\n[WARN] MISSING TICKERS ({len(missing_symbols)} of {len(symbols_needed)}):")
        print(f"  ticker_dir used: {ticker_dir}")
        print(f"  Missing: {', '.join(missing_symbols[:20])}{' ...' if len(missing_symbols) > 20 else ''}")
        print(f"  Fix: Pass the SAME data dir as {_launcher}/optimizer (e.g. data/newdata/data)")
        print()

    metrics: dict
    used_canonical = False
    bundle = None
    curve_path, _curve_meta_path = _canonical_equity_paths(base_dir, timestamp, file_prefix)
    canonical_on_disk = os.path.isfile(curve_path)
    try_canonical = (
        canonical_on_disk
        and not no_saved_equity
        and not force_reconstruct
        and not symbol
    )
    if try_canonical:
        bundle = load_canonical_equity_bundle(base_dir, timestamp, file_prefix)
    if bundle is not None:
        eq_dates, eq_vals, eq_pos, meta, eq_regular_csv = bundle
        if eq_dates and eq_vals and len(eq_dates) == len(eq_vals):
            init_meta = meta.get("Initial_Account_Size")
            if init_meta is None or (isinstance(init_meta, float) and pd.isna(init_meta)):
                init_meta = meta.get("initial_account_size")
            initial_seed: Optional[float] = None
            if init_meta is not None and str(init_meta).strip() != "":
                try:
                    initial_seed = float(init_meta)
                except (TypeError, ValueError):
                    initial_seed = None
            if initial_seed is None and audit_row:
                try:
                    initial_seed = float(audit_row["audit_cash"])
                except (KeyError, TypeError, ValueError):
                    pass
            max_port_dd = max_drawdown_from_equity_path(eq_vals, initial_seed)
            frac_meta = meta.get("Max_Drawdown_fraction")
            if frac_meta is not None and str(frac_meta).strip() != "":
                try:
                    fm = float(frac_meta)
                    if abs(fm - max_port_dd) > 0.0005:
                        print(
                            f"[WARN] Max_DD replay {max_port_dd:.4f} vs meta {fm:.4f}; using replay from curve."
                        )
                except (TypeError, ValueError):
                    pass
            md_us: int = 0
            raw_mu = meta.get("Max_Days_Underwater")
            if raw_mu is not None and str(raw_mu).strip() != "":
                try:
                    md_us = int(float(raw_mu))
                except (TypeError, ValueError):
                    md_us = 0
            pct_uw = meta.get("Pct_Days_Underwater")
            if pct_uw is None or (isinstance(pct_uw, float) and pd.isna(pct_uw)):
                pct_uw_str = "0.0%"
            else:
                s = str(pct_uw).strip()
                pct_uw_str = s if s.endswith("%") else f"{float(s):.1f}%"
            pos_list = eq_pos if eq_pos and len(eq_pos) == len(eq_vals) else [0] * len(eq_vals)
            metrics = {
                "Max_Drawdown": f"{max_port_dd:.2%}" if max_port_dd > 0 else "N/A",
                "Max_Days_Underwater": md_us,
                "Pct_Days_Underwater": pct_uw_str,
                "equity_dates": eq_dates,
                "equity_values": eq_vals,
                "equity_positions": pos_list,
                "_max_port_dd_raw": max_port_dd,
                "_missing_ticker_trades": 0,
                "_aggressive": False,
            }
            ag_meta = meta.get("Aggressive") if meta else None
            if ag_meta is not None and str(ag_meta).strip() != "":
                metrics["_aggressive"] = str(ag_meta).strip().lower() in ("true", "1", "yes", "1.0")
            if eq_regular_csv is not None and len(eq_regular_csv) == len(eq_vals):
                metrics["equity_values_regular"] = eq_regular_csv
                metrics["_aggressive"] = True
            used_canonical = True
            cp, mp = _canonical_equity_paths(base_dir, timestamp, file_prefix)
            print(
                f"[OK] Canonical equity (matches {file_prefix}_Audit / {_launcher}): "
                f"{os.path.basename(cp)} / {os.path.basename(mp)}"
            )

    if not used_canonical:
        if missing_symbols:
            print(
                "[INFO] OHLC reconstruction may understate Max_DD when tickers are missing; "
                "use the full data directory."
            )
        metrics = compute_equity_metrics(
            closed,
            open_trades,
            tickers,
            cash,
            initial_capital=_baseline,
            aggressive=aggressive,
        )
        missing = metrics.get("_missing_ticker_trades", 0)
        if missing > 0:
            print(
                f"[INFO] {missing} trades had no ticker data; positions and Max_DD use linear PnL approximation "
                f"(use same ticker_dir as {_launcher} for exact match)"
            )
        if not metrics.get("equity_dates"):
            print("[ERR] No trade dates found. Pass ticker dir as second argument.")
            print(
                f"      Example: python BRT_DrawdownCalc.py <{file_prefix}_Closed_csv> "
                "\"C:\\...\\data\\newdata\\data\""
            )
            return
        if canonical_on_disk and try_canonical and not used_canonical:
            print(
                f"[WARN] {file_prefix}_EquityCurve present but invalid or unreadable; using OHLC "
                "(Max_DD may not match audit)."
            )
        elif canonical_on_disk and (no_saved_equity or force_reconstruct) and not symbol:
            print(
                "[INFO] OHLC rebuild (--no-saved-equity or --force-reconstruct); "
                f"Max_DD may be below audit when {_launcher} used --aggressive (e.g. ~8.7% vs ~10.7%)."
            )
        print(
            f"[OK] Max_DD from compute_equity_metrics (OHLC mark-to-market, total equity baseline={_baseline:,.0f}"
            + (", aggressive sizing on)." if aggressive else ").")
        )

    # Passive OHLC curve for dual-line chart when primary equity is aggressive (saved or recomputed).
    if (
        used_canonical
        and not symbol
        and tickers
        and metrics.get("equity_values_regular") is None
        and (metrics.get("_aggressive") or aggressive)
    ):
        try:
            passive_m = compute_equity_metrics(
                closed,
                open_trades,
                tickers,
                cash,
                initial_capital=_baseline,
                aggressive=False,
            )
            p_dates = passive_m.get("equity_dates") or []
            p_vals = passive_m.get("equity_values") or []
            canon_dates = metrics.get("equity_dates") or []
            if p_vals and canon_dates and len(p_vals) == len(canon_dates):
                metrics["equity_values_regular"] = list(p_vals)
            elif p_vals and p_dates and canon_dates:
                mreg = {pd.Timestamp(d).normalize(): float(v) for d, v in zip(p_dates, p_vals)}
                aligned = [mreg.get(pd.Timestamp(d).normalize()) for d in canon_dates]
                if aligned and all(x is not None for x in aligned):
                    metrics["equity_values_regular"] = [float(x) for x in aligned]  # type: ignore[arg-type]
        except Exception as e:
            print(f"[WARN] Could not add regular OHLC equity overlay: {e}", file=sys.stderr)

    _apply_passive_equity_primary(metrics, aggressive_chart=bool(aggressive))

    history_dates = metrics["equity_dates"]
    history_equity = metrics["equity_values"]
    history_positions = metrics["equity_positions"]
    max_port_dd = metrics["_max_port_dd_raw"]

    # Trough/peak for annotation (recompute from curve)
    trough_date = None
    peak_date_for_max_dd = history_dates[0]
    port_hwm = history_equity[0]
    current_hwm_date = history_dates[0]
    for i, dt in enumerate(history_dates):
        eq = history_equity[i]
        if eq > port_hwm:
            port_hwm = eq
            current_hwm_date = dt
        if port_hwm > 0 and (port_hwm - eq) / port_hwm >= max_port_dd - 1e-9:
            trough_date = dt
            peak_date_for_max_dd = current_hwm_date

    scope_label = f" ({symbol} only)" if symbol else ""
    print(f"[OK] Charting from {history_dates[0].date()} to {history_dates[-1].date()}{scope_label}")

    debug_df = pd.DataFrame({"Date": history_dates, "Equity": history_equity})
    eq_reg = metrics.get("equity_values_regular")
    if eq_reg is not None and len(eq_reg) == len(history_dates):
        debug_df["Equity_Regular"] = eq_reg
    if metrics.get("_chart_primary") == "regular":
        print("[OK] Chart: passive (Equity_Regular / audit-aligned)")
    elif eq_reg is not None and len(eq_reg) == len(history_dates) and aggressive:
        print("[OK] Chart: aggressive (primary) + regular (OHLC) overlay")
    debug_path = os.path.join(out_dir, f"{file_prefix}_daily_equity_debug.csv")
    debug_df.to_csv(debug_path, index=False)
    print(f"[FILE] Daily equity log: {debug_path}")
    if metrics.get("_aggressive") and metrics.get("aggressive_trim_log"):
        trim_df = pd.DataFrame(metrics.get("aggressive_trim_log"))
        trim_path = os.path.join(out_dir, f"{file_prefix}_aggressive_trim_log_{timestamp}.csv")
        trim_df.to_csv(trim_path, index=False)
        print(f"[FILE] Aggressive trim log: {trim_path}")

    uw_stats = generate_underwater_report(debug_df, timestamp, output_dir=out_dir, prefix=file_prefix)
    max_underwater = int(uw_stats.get("max_duration_days", 0) or 0)
    if max_underwater > 0:
        print(
            f"[FILE] Underwater report: {os.path.join(out_dir, f'{file_prefix}_underwater_{timestamp}.csv')} "
            f"(max duration {max_underwater} days; "
            f"avg {uw_stats.get('avg_days_underwater', 0):.3f}; "
            f"p90 {uw_stats.get('p90_days_underwater', 0):.3f})"
        )

    # --- SPY benchmark (same notional anchor as portfolio curve) ---
    spy_equity = []
    initial_account_size = _baseline
    spy_path = os.path.join(ticker_dir, "SPY.csv")
    if os.path.exists(spy_path):
        df_spy = pd.read_csv(spy_path)
        df_spy = normalize_ohlc_columns(df_spy)
        if "Date" in df_spy.columns and "Close" in df_spy.columns:
            df_spy["Date"] = pd.to_datetime(df_spy["Date"])
            df_spy = df_spy.sort_values("Date").set_index("Date")
            try:
                idx = df_spy.index.get_indexer([pd.Timestamp(history_dates[0])], method="ffill")[0]
                start_p = float(df_spy.iloc[idx]["Close"]) if idx >= 0 else None
            except Exception:
                start_p = float(df_spy.iloc[0]["Close"]) if len(df_spy) else None
            if start_p and start_p > 0:
                for dt in history_dates:
                    try:
                        idx = df_spy.index.get_indexer([pd.Timestamp(dt)], method="ffill")[0]
                        p = float(df_spy.iloc[idx]["Close"]) if idx >= 0 else start_p
                    except Exception:
                        p = start_p
                    spy_equity.append((p / start_p) * initial_account_size)

    # --- Chart ---
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    fig, ax1 = plt.subplots(figsize=(12, 6))
    primary_label = (
        f"{file_prefix} equity (aggressive)"
        if metrics.get("_aggressive") and aggressive
        else f"{file_prefix} Portfolio Equity"
    )
    ax1.plot(
        history_dates,
        history_equity,
        color="tab:blue",
        linewidth=2,
        label=primary_label,
    )
    eq_reg_plot = metrics.get("equity_values_regular")
    if (
        aggressive
        and eq_reg_plot is not None
        and len(eq_reg_plot) == len(history_dates)
        and metrics.get("_chart_primary") != "regular"
    ):
        ax1.plot(
            history_dates,
            eq_reg_plot,
            color="tab:orange",
            linestyle="--",
            linewidth=1.8,
            label="Regular (OHLC, per-trade cash)",
            alpha=0.92,
        )
    if spy_equity:
        ax1.plot(history_dates, spy_equity, color="black", linestyle="--", linewidth=1.2, label="SPY Benchmark", alpha=0.6)

    if trough_date:
        trough_val = history_equity[history_dates.index(trough_date)]
        ax1.annotate(
            f"Max DD: {max_port_dd:.1%}",
            xy=(trough_date, trough_val),
            xytext=(trough_date, trough_val * 0.9),
            arrowprops=dict(facecolor="black", shrink=0.05, width=1, headwidth=5),
            fontsize=10,
            fontweight="bold",
            color="darkred",
            ha="center",
        )

    ax1.set_ylabel("Total Value ($)", fontweight="bold")
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f"${x:,.0f}"))
    ax1.legend(loc="upper left")

    ax2 = ax1.twinx()
    y_max_pos = max(history_positions) + 2 if history_positions else 5
    ax2.step(history_dates, history_positions, where="post", color="tab:red", alpha=0.6, linewidth=1.5, label="Active Positions")
    ax2.set_ylabel("Active Positions", fontweight="bold")
    ax2.set_ylim(0, y_max_pos)
    ax2.set_xlim(history_dates[0], history_dates[-1])
    ax2.legend(loc="upper right")

    chart_title = f"{file_prefix} Portfolio{scope_label}: Equity, Growth & Positions (Drawdown)"
    plt.title(chart_title, fontsize=14, fontweight="bold")
    ax1.grid(True, linestyle="--", alpha=0.5)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.xticks(rotation=45)
    plt.tight_layout()

    save_name = (
        f"{file_prefix}_Portfolio_Performance_{symbol or 'All'}_{timestamp}.png"
        if symbol
        else f"{file_prefix}_Portfolio_Performance_{timestamp}.png"
    )
    save_path = os.path.join(out_dir, save_name)
    plt.savefig(save_path)
    print(f"[FILE] Chart: {save_path}")
    import shutil
    try:
        # Only overwrite "latest" for full-portfolio runs; single-symbol runs use latest_<SYMBOL>.png so they don't replace the main latest
        if symbol:
            latest_path = os.path.join(out_dir, f"{file_prefix}_Portfolio_Performance_latest_{symbol}.png")
        else:
            latest_path = os.path.join(out_dir, f"{file_prefix}_Portfolio_Performance_latest.png")
        shutil.copy2(save_path, latest_path)
        print(f"[FILE] Chart (latest): {latest_path}")
    except Exception as e:
        print(f"[WARN] Could not write latest: {e}")
    plt.close()

    # Charts: bands that resulted in trades (closed + open); optionally would-have (amber/magenta); timeline filter
    if ("ZONE_CENTER" in df_closed.columns or would_have_by_symbol) and tickers:
        max_band_charts = 20
        symbols_closed = set(df_closed["SYMBOL"].dropna().astype(str).str.strip()) if not df_closed.empty else set()
        symbols_open = set(df_open["SYMBOL"].dropna().astype(str).str.strip()) if not df_open.empty else set()
        symbols_with_trades = list(symbols_closed | symbols_open | (would_have_by_symbol.keys() if would_have_by_symbol else set()))
        drawn = 0
        for sym in symbols_with_trades:
            if drawn >= max_band_charts:
                break
            sym = str(sym).strip()
            if sym not in tickers:
                continue
            closed_trades_list = []
            if "ZONE_CENTER" in df_closed.columns:
                for _, row in df_closed[df_closed["SYMBOL"].astype(str).str.strip() == sym].iterrows():
                    closed_trades_list.append({
                        "ZONE_CENTER": clean_numeric(row.get("ZONE_CENTER")),
                        "DATE_OPENED": row.get("DATE_OPENED"),
                        "DATE_CLOSED": row.get("DATE_CLOSED"),
                    })
            open_trades_list = []
            if not df_open.empty and "ZONE_CENTER" in df_open.columns:
                for _, row in df_open[df_open["SYMBOL"].astype(str).str.strip() == sym].iterrows():
                    ot = {
                        "ZONE_CENTER": clean_numeric(row["ZONE_CENTER"]),
                        "DATE_OPENED": row.get("DATE_OPENED"),
                    }
                    if "ZONE_ABOVE_CENTER" in df_open.columns:
                        v = row.get("ZONE_ABOVE_CENTER")
                        if v is not None and str(v).strip() != "":
                            ot["ZONE_ABOVE_CENTER"] = clean_numeric(v)
                    if "ZONE_BELOW_CENTER" in df_open.columns:
                        v = row.get("ZONE_BELOW_CENTER")
                        if v is not None and str(v).strip() != "":
                            ot["ZONE_BELOW_CENTER"] = clean_numeric(v)
                    open_trades_list.append(ot)
            would_have_list = would_have_by_symbol.get(sym, [])
            if not closed_trades_list and not open_trades_list and not would_have_list:
                continue
            band_path = os.path.join(out_dir, f"{file_prefix}_TradeBands_{sym}_{timestamp}.png")
            _draw_trade_bands_chart(sym, tickers[sym], closed_trades_list, open_trades_list, band_path, band_pct=0.02,
                                    would_have_trades=would_have_list if show_would_have else None,
                                    start_ts=start_ts, end_ts=end_ts)
            drawn += 1
        if drawn > 0:
            print(f"[FILE] Trade-bands charts (closed + open" + (", would-have=amber/magenta" if show_would_have and would_have_by_symbol else "") + f"): {drawn} symbol(s)")

    print("\n" + "=" * 50)
    print(f"{file_prefix} PORTFOLIO PERFORMANCE SUMMARY{scope_label.upper()}")
    print("=" * 50)
    print(f"Max DD:        {max_port_dd:.2%}")
    print(f"Peak Date:     {peak_date_for_max_dd.date()}")
    print(f"Trough Date:   {trough_date.date() if trough_date else 'N/A'}")
    print(f"Max Positions: {max(history_positions) if history_positions else 0}")
    if metrics.get("_aggressive"):
        print(f"Aggressive avg positions: {metrics.get('Aggressive_Avg_Positions', 0)}")
        print(f"Aggressive <=avg days:   {metrics.get('Aggressive_Days_AtOrBelow_Avg', 0)}")
        print(f"Aggressive margin days:  {metrics.get('Aggressive_Days_In_Margin', 0)}")
        print(f"Aggressive trimmed days: {metrics.get('Aggressive_Days_Trimmed_Over_2xAvg', 0)}")
    print("=" * 50 + "\n")

    # Align BRT_Report / BRT_Audit_Report column order to match BRT_Optimization_Audit when present (BRT only)
    if file_prefix == "BRT":
        try:
            from BRT_Optimizer import AUDIT_COLS_ORDER
            for name in (f"BRT_Report_{timestamp}.csv", f"BRT_Audit_Report_{timestamp}.csv"):
                path = os.path.join(out_dir, name)
                if not os.path.isfile(path):
                    continue
                try:
                    df = pd.read_csv(path, index_col=False)
                    df.columns = [c.strip() for c in df.columns]
                    ordered = [c for c in AUDIT_COLS_ORDER if c in df.columns]
                    extra = [c for c in df.columns if c not in AUDIT_COLS_ORDER]
                    df = df[ordered + extra]
                    df.to_csv(path, index=False)
                    print(f"[OK] Aligned columns to optimizer order: {name}")
                except Exception as e:
                    print(f"[WARN] Could not align {name}: {e}")
        except ImportError:
            pass


if __name__ == "__main__":
    import argparse

    try:
        from DrawdownCalc import _resolve_closed_csv_argument
    except ImportError:
        _resolve_closed_csv_argument = None  # type: ignore[misc, assignment]

    p = argparse.ArgumentParser(
        description="Portfolio drawdown from BRT/IND/MTS Closed + Open CSVs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python BRT_DrawdownCalc.py Drive/IND_Closed_260602180527.csv\n"
            "  python BRT_DrawdownCalc.py 260602180527 --engine IND\n"
            "    (bare timestamp: use --engine when BRT and IND share the same ts)\n"
        ),
    )
    p.add_argument(
        "closed_csv",
        help="Path to *Closed_<timestamp>.csv, or 12-digit yyMMddHHmmss (searches Drive/, drive/, cwd)",
    )
    p.add_argument(
        "--engine",
        choices=("BRT", "IND", "MTS", "RL"),
        default=None,
        help="When closed_csv is a bare timestamp and multiple *Closed_<ts>.csv exist, force BRT/IND/MTS/RL",
    )
    p.add_argument("ticker_dir", nargs="?", default="data/newdata/data",
                   help="Directory with per-symbol CSVs (default: data/newdata/data, same as rocket_brt)")
    p.add_argument("--symbol", "-s", default=None, help="Run for this symbol only (e.g. NVDA). Default: all symbols in closed CSV.")
    p.add_argument(
        "--cash",
        type=float,
        default=None,
        help="Per-trade notional (default: read brt_cash from BRT_Audit_Report / BRT_Report next to Closed)",
    )
    p.add_argument(
        "--no-audit",
        action="store_true",
        help="Do not read per-trade cash from BRT_Audit_Report or BRT_Report (use --cash or default 47500)",
    )
    p.add_argument(
        "--initial-capital",
        type=float,
        default=500000.0,
        metavar="USD",
        help="Starting portfolio equity for chart & Max DD (default: 500000), independent of brt_cash.",
    )
    p.add_argument("--output-dir", default=None, help="Directory for chart and CSVs (default: same as closed file)")
    p.add_argument("--show-would-have", action="store_true",
                    help="Show zones that would have been purchased (growth/range/consolidation off) on band charts; requires BRT_WouldHave CSV")
    p.add_argument("--would-have-csv", default=None,
                    help="Path to BRT_WouldHave_<ts>.csv (default: same dir as closed file, same timestamp)")
    p.add_argument("--start-date", default=None, metavar="YYYY-MM-DD", help="Start of timeline for band chart (inclusive)")
    p.add_argument("--end-date", default=None, metavar="YYYY-MM-DD", help="End of timeline for band chart (inclusive)")
    p.add_argument(
        "--use-saved-equity",
        action="store_true",
        help="Optional. Canonical curve is already auto-loaded when BRT_EquityCurve_<ts>.csv exists.",
    )
    p.add_argument(
        "--no-saved-equity",
        action="store_true",
        help="Always rebuild from OHLC; ignore BRT_EquityCurve (Max_DD may not match audit if rocket_brt used --aggressive).",
    )
    p.add_argument(
        "--force-reconstruct",
        action="store_true",
        help="Same as forcing OHLC rebuild: ignores BRT_EquityCurve; full daily MTM from tickers.",
    )
    p.add_argument(
        "--aggressive",
        action="store_true",
        help="Chart aggressive Equity plus passive overlay; OHLC rebuild uses aggressive sizing. "
        "Default (omit flag): passive Equity_Regular only when present in saved curve; passive OHLC rebuild.",
    )
    args = p.parse_args()
    closed_path = args.closed_csv
    if _resolve_closed_csv_argument is not None:
        resolved, _ts_mode, _eng = _resolve_closed_csv_argument(
            args.closed_csv,
            engine_preference=getattr(args, "engine", None),
        )
        if resolved and os.path.isfile(resolved):
            closed_path = resolved
        elif re.fullmatch(r"\d{12}", (args.closed_csv or "").strip()):
            print(
                f"[ERR] No Closed CSV for timestamp {args.closed_csv!r}. "
                "Pass *Closed_<ts>.csv or use --engine IND|BRT|MTS|RL.",
                file=sys.stderr,
            )
            sys.exit(1)
    run_audit(
        closed_path,
        args.ticker_dir,
        cash=args.cash,
        output_dir=args.output_dir or None,
        symbol=args.symbol,
        show_would_have=args.show_would_have,
        would_have_path=args.would_have_csv,
        start_date=args.start_date,
        end_date=args.end_date,
        initial_capital=args.initial_capital,
        use_audit=not getattr(args, "no_audit", False),
        use_saved_equity=args.use_saved_equity,
        no_saved_equity=getattr(args, "no_saved_equity", False),
        force_reconstruct=getattr(args, "force_reconstruct", False),
        aggressive=args.aggressive,
    )
