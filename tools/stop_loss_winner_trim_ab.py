#!/usr/bin/env python3
"""Stop-loss winner-trim overlay AB — system by system, FULL / IS / OOS.

Rule (Paul): when a position exits at a stop loss, simultaneously sell half of
the currently open position with the largest unrealized dollar gain (same
system book). Keep the other half. If no open winners, do nothing.

Control = unmodified LatestRun Closed.
Candidate = Closed + trim legs; remaining half of trimmed winners scaled.

Research only — not DailyRun / not gold.
"""
from __future__ import annotations

import html as html_mod
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import duckdb
import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
_PE = _REPO / "drive" / "paul_experiments"
_DRIVE = _REPO / "Drive"
_TOOLS = _REPO / "tools"
for _p in (_PE, _TOOLS, _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    ann_ror_from_closed,
    filter_html_compare_metric_rows,
    format_money,
    is_excluded_html_compare_label,
    max_dd_pct_from_closed_pnl_by_date,
    sharpe_from_closed_pnl_by_date,
)
from report_page_extras import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

OUT = _PE / "stop_loss_winner_trim_ab_20261007"
DB = _REPO / "data" / "ohlcv.duckdb"
IS_CUT = date(2024, 1, 1)
SHEET_CASH = 47_500.0  # fallback only; prefer Report capacity_brt_cash (matches Closed $)

# Live / Recent DailyRun-style Closed files (skip MUD mega-research; skip IND deprecated optional)
SYSTEMS = [
    "BRT",
    "RL",
    "WPBR",
    "YH",
    "MTS",
    "RS",
    "SB",
    "VZ",
    "WRL",
    "RSI",
    "CS",
    "IND",
]

STOP_EXIT_TYPES = {
    "STOP_LOSS",
    "STOP",
    "GAP_DOWN",
    "ATR_STOP",
    "TRAIL_STOP",  # RL trailing stop (loss or giveback)
}

ASK = (
    "what would happen to each system's results, if when i sold a stock at a "
    "stop loss i simultaneously sold the stock being held that had the biggest "
    "gain to offset that loss. for example, if I have 3 stocks. one is sold at "
    "a loss of $2,500, one is currently at break even, and one is at a gain of "
    "$5,000, I sell half the position in the leading stock for $2,500. i keep "
    "half the position in the leading stock. if i have no stock with any gains, "
    "no sale is made. can you provide me a system by system analysis of what "
    "the performance looks like today and what it would look like if we "
    "implemented this strategy, and also split it by IS and OOS and full"
)
PLAIN = (
    "Today each system sells a whole loser at the stop and leaves winners alone. "
    "This test asks: on that same stop day, also sell half of whichever open "
    "winner is up the most in dollars (same system), and keep the other half. "
    "If nothing is in the green, skip the trim. We replay each system's Closed "
    "book as-is (control) versus with those half-trims (candidate), for the full "
    "history, before 2024 (in-sample), and 2024 onward (out-of-sample)."
)


def _th(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{typ}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _to_pct_number(s: pd.Series) -> pd.Series:
    """'12.5%' or 12.5 -> float percent points."""
    if pd.api.types.is_numeric_dtype(s):
        return pd.to_numeric(s, errors="coerce")
    t = s.astype(str).str.strip().str.replace("%", "", regex=False).str.replace(",", "", regex=False)
    return pd.to_numeric(t, errors="coerce")


def _to_money_number(s: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(s):
        return pd.to_numeric(s, errors="coerce")
    t = (
        s.astype(str)
        .str.strip()
        .str.replace("$", "", regex=False)
        .str.replace(",", "", regex=False)
        .str.replace("(", "-", regex=False)
        .str.replace(")", "", regex=False)
    )
    return pd.to_numeric(t, errors="coerce")


def _parse_dates(s: pd.Series) -> pd.Series:
    """Closed dates may be YYYYMMDD ints, ISO strings, or already timestamps."""
    if pd.api.types.is_datetime64_any_dtype(s):
        return pd.to_datetime(s, errors="coerce")
    # numeric YYYYMMDD
    num = pd.to_numeric(s, errors="coerce")
    if num.notna().mean() > 0.8 and float(num.dropna().median()) > 1e7:
        return pd.to_datetime(num.astype("Int64").astype(str), format="%Y%m%d", errors="coerce")
    return pd.to_datetime(s, errors="coerce")


def _norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    rename = {}
    for c in df.columns:
        k = str(c).strip().upper()
        k = k.replace("%", " PCT").replace("$", " DOLLARS").replace("?", "")
        k = "_".join(k.split())  # collapse spaces/underscores
        while "__" in k:
            k = k.replace("__", "_")
        rename[c] = k
    out = df.rename(columns=rename)
    aliases = {
        "DATE_OPENED": ["DATE_OPENED"],
        "DATE_CLOSED": ["DATE_CLOSED"],
        "ENTRY_PRICE": ["ENTRY_PRICE"],
        "EXIT_PRICE": ["EXIT_PRICE"],
        "EXIT_TYPE": ["EXIT_TYPE"],
        "PNL_PCT": ["PNL_PCT", "PNL"],
        "PNL_DOLLARS": ["PNL_DOLLARS"],
        "DAYS_HELD": ["DAYS_HELD"],
    }
    for want, opts in aliases.items():
        if want in out.columns:
            continue
        for o in opts:
            if o in out.columns:
                out[want] = out[o]
                break
    return out


def _closed_implied_cash(df: pd.DataFrame) -> Optional[float]:
    if df is None or len(df) == 0:
        return None
    if "PNL_DOLLARS" not in df.columns or "PNL_PCT" not in df.columns:
        return None
    pct = pd.to_numeric(df["PNL_PCT"], errors="coerce")
    doll = pd.to_numeric(df["PNL_DOLLARS"], errors="coerce")
    with np.errstate(divide="ignore", invalid="ignore"):
        impl = (doll.abs() / (pct.abs() / 100.0)).where(
            (pct.abs() > 1e-9) & doll.notna() & pct.notna()
        )
    med = float(impl.median()) if impl.notna().any() else float("nan")
    return med if math.isfinite(med) and med > 0 else None


def _cash_for(system: str, df: Optional[pd.DataFrame] = None) -> tuple[float, str]:
    """Cash that matches Closed PNL_DOLLARS scale — required for house Ann ROR.

    Prefer Closed median implied notional (dollars ÷ pct). That is what
    system_performance.html effectively uses when it quotes standalone Ann ROR
    next to Closed total profit. Report capacity_brt_cash is a fallback when it
    agrees within ~25%; otherwise Closed wins (VZ Closed is ~$45k while capacity
    can be ~$17k — using capacity would invent a huge Ann ROR).
    """
    closed_med = _closed_implied_cash(df) if df is not None else None
    rep_cash = None
    rep_src = ""
    reps = sorted(_DRIVE.glob(f"{system}_Report_*.csv"))
    if reps:
        try:
            r = pd.read_csv(reps[-1])
            row = r.iloc[0].to_dict()
            for key in ("capacity_brt_cash", "brt_cash", "sheet_brt_cash"):
                v = row.get(key)
                if v is None or (isinstance(v, float) and not math.isfinite(v)):
                    continue
                fv = float(v)
                if fv > 0:
                    rep_cash, rep_src = fv, f"Report.{key}={fv:.4f} ({reps[-1].name})"
                    break
        except Exception:
            pass

    if closed_med is not None:
        if rep_cash is not None and 0.75 <= (closed_med / rep_cash) <= 1.25:
            return closed_med, (
                f"Closed median implied={closed_med:.4f} "
                f"(~matches {rep_src})"
            )
        return closed_med, f"Closed median implied notional={closed_med:.4f}"
    if rep_cash is not None:
        return rep_cash, rep_src
    if system == "RSI":
        return 10_000.0, "RSI dummy $10k"
    return SHEET_CASH, "fallback sheet $47,500"


def load_closed(system: str) -> pd.DataFrame:
    path = _DRIVE / f"{system}_LatestRun_Closed.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_csv(path, low_memory=False)
    df = _norm_cols(df)
    need = ["SYMBOL", "DATE_OPENED", "DATE_CLOSED", "ENTRY_PRICE", "EXIT_TYPE", "PNL_PCT", "DAYS_HELD"]
    for c in need:
        if c not in df.columns:
            raise SystemExit(f"{system}: missing {c}; have {list(df.columns)[:25]}")
    df["SYMBOL"] = df["SYMBOL"].astype(str).str.upper().str.strip()
    df["DATE_OPENED"] = _parse_dates(df["DATE_OPENED"])
    df["DATE_CLOSED"] = _parse_dates(df["DATE_CLOSED"])
    df["ENTRY_PRICE"] = pd.to_numeric(df["ENTRY_PRICE"], errors="coerce")
    if "EXIT_PRICE" in df.columns:
        df["EXIT_PRICE"] = pd.to_numeric(df["EXIT_PRICE"], errors="coerce")
    else:
        df["EXIT_PRICE"] = np.nan
    df["PNL_PCT"] = _to_pct_number(df["PNL_PCT"])
    if "PNL_DOLLARS" in df.columns:
        df["PNL_DOLLARS"] = _to_money_number(df["PNL_DOLLARS"])
    else:
        df["PNL_DOLLARS"] = np.nan
    df["DAYS_HELD"] = pd.to_numeric(df["DAYS_HELD"], errors="coerce")
    df["EXIT_TYPE"] = df["EXIT_TYPE"].astype(str).str.strip().str.upper()
    # Infer per-trade notional from Closed dollars/pct (true size scale)
    pct = df["PNL_PCT"].to_numpy(dtype=float)
    dollars = df["PNL_DOLLARS"].to_numpy(dtype=float)
    cash_guess, _ = _cash_for(system, df)
    with np.errstate(divide="ignore", invalid="ignore"):
        inferred = np.where(
            np.isfinite(pct) & (np.abs(pct) > 1e-9) & np.isfinite(dollars),
            np.abs(dollars) / (np.abs(pct) / 100.0),
            cash_guess,
        )
    use_inf = np.isfinite(inferred) & (inferred > 0)
    notional = np.where(use_inf, inferred, cash_guess)
    rebuild_d = ~np.isfinite(dollars)
    dollars = np.where(rebuild_d, (pct / 100.0) * notional, dollars)
    df["ENTRY_NOTIONAL"] = notional
    df["PNL_DOLLARS"] = dollars
    entry = df["ENTRY_PRICE"].to_numpy(dtype=float)
    shares = np.where(np.isfinite(entry) & (entry > 0), notional / entry, np.nan)
    df["SHARES"] = shares
    # Fill exit price from pct when missing
    miss_exit = ~np.isfinite(df["EXIT_PRICE"].to_numpy(dtype=float))
    df.loc[miss_exit, "EXIT_PRICE"] = entry[miss_exit] * (1.0 + pct[miss_exit] / 100.0)
    df = df.dropna(subset=["DATE_OPENED", "DATE_CLOSED", "ENTRY_PRICE"]).copy()
    df = df.sort_values(["DATE_CLOSED", "DATE_OPENED", "SYMBOL"]).reset_index(drop=True)
    df["_tid"] = np.arange(len(df))
    return df


def load_price_panel(symbols: list[str]) -> dict[str, pd.Series]:
    """symbol -> Series(date -> close)."""
    if not symbols:
        return {}
    con = duckdb.connect(str(DB), read_only=True)
    try:
        # batch
        syms = sorted({s.upper() for s in symbols})
        q = """
        SELECT UPPER(symbol) AS symbol, CAST(date AS DATE) AS d, close
        FROM prices
        WHERE UPPER(symbol) IN (SELECT * FROM UNNEST(?))
        ORDER BY 1, 2
        """
        df = con.execute(q, [syms]).fetchdf()
    finally:
        con.close()
    out: dict[str, pd.Series] = {}
    if df.empty:
        return out
    for sym, g in df.groupby("symbol"):
        s = pd.Series(g["close"].to_numpy(dtype=float), index=pd.to_datetime(g["d"]))
        s = s[~s.index.duplicated(keep="last")].sort_index()
        out[str(sym)] = s
    return out


def mark_price(panel: dict[str, pd.Series], symbol: str, asof: pd.Timestamp) -> Optional[float]:
    s = panel.get(symbol.upper())
    if s is None or s.empty:
        return None
    # last close on or before asof
    idx = s.index.searchsorted(asof, side="right") - 1
    if idx < 0:
        return None
    px = float(s.iloc[idx])
    return px if math.isfinite(px) and px > 0 else None


@dataclass
class OpenLot:
    tid: int
    symbol: str
    opened: pd.Timestamp
    entry: float
    notional0: float
    shares0: float
    frac: float = 1.0  # remaining fraction of original
    final_pnl_d: float = 0.0
    final_exit: float = 0.0
    final_closed: Optional[pd.Timestamp] = None
    final_exit_type: str = ""
    final_days: float = 0.0
    trimmed: bool = False


@dataclass
class SimResult:
    control_trades: list[dict[str, Any]]
    # Cash-flow legs (includes WINNER_TRIM_50 rows) — for Max DD / Sharpe path
    candidate_cashflow: list[dict[str, Any]]
    # Same N as control; winner dollars = trim + remainder — for Ann ROR / quality
    candidate_economic: list[dict[str, Any]]
    n_stops: int = 0
    n_trims: int = 0
    n_stops_no_winner: int = 0
    trim_dollars: float = 0.0
    notes: list[str] = field(default_factory=list)


def _is_stop_loss(exit_type: str, pnl_d: float) -> bool:
    """Stop-like exit that lost money (trail stops that finished green do not trim)."""
    et = (exit_type or "").upper()
    if et not in STOP_EXIT_TYPES:
        return False
    return math.isfinite(pnl_d) and pnl_d < 0


def simulate(df: pd.DataFrame, panel: dict[str, pd.Series]) -> SimResult:
    control: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        control.append(
            {
                "symbol": r["SYMBOL"],
                "opened": r["DATE_OPENED"].date() if pd.notna(r["DATE_OPENED"]) else None,
                "closed": r["DATE_CLOSED"].date() if pd.notna(r["DATE_CLOSED"]) else None,
                "pnl": float(r["PNL_PCT"]) if pd.notna(r["PNL_PCT"]) else None,
                "pnl_d": float(r["PNL_DOLLARS"]) if pd.notna(r["PNL_DOLLARS"]) else 0.0,
                "days": float(r["DAYS_HELD"]) if pd.notna(r["DAYS_HELD"]) and r["DAYS_HELD"] > 0 else 1.0,
                "exit_type": r["EXIT_TYPE"],
                "kind": "full",
            }
        )

    # Event timeline: opens and closes
    opens = df.sort_values(["DATE_OPENED", "_tid"])
    by_close = df.sort_values(["DATE_CLOSED", "_tid"])

    open_book: dict[int, OpenLot] = {}
    oi = 0
    open_rows = opens.to_dict("records")
    cashflow: list[dict[str, Any]] = []
    # tid -> list of trim pnl dollars realized early
    trim_bank: dict[int, list[float]] = {}
    n_stops = n_trims = n_no = 0
    trim_dollars = 0.0

    for _, r in by_close.iterrows():
        close_dt = r["DATE_CLOSED"]
        # Admit opens with DATE_OPENED <= close_dt
        while oi < len(open_rows) and open_rows[oi]["DATE_OPENED"] <= close_dt:
            o = open_rows[oi]
            open_book[int(o["_tid"])] = OpenLot(
                tid=int(o["_tid"]),
                symbol=str(o["SYMBOL"]),
                opened=o["DATE_OPENED"],
                entry=float(o["ENTRY_PRICE"]),
                notional0=float(o["ENTRY_NOTIONAL"]),
                shares0=float(o["SHARES"]) if pd.notna(o["SHARES"]) else float("nan"),
                frac=1.0,
                final_pnl_d=float(o["PNL_DOLLARS"]),
                final_exit=float(o["EXIT_PRICE"]) if pd.notna(o["EXIT_PRICE"]) else float("nan"),
                final_closed=o["DATE_CLOSED"],
                final_exit_type=str(o["EXIT_TYPE"]),
                final_days=float(o["DAYS_HELD"]) if pd.notna(o["DAYS_HELD"]) and o["DAYS_HELD"] > 0 else 1.0,
            )
            oi += 1

        tid = int(r["_tid"])
        lot = open_book.get(tid)
        pnl_d = float(r["PNL_DOLLARS"])
        is_stop = _is_stop_loss(str(r["EXIT_TYPE"]), pnl_d)

        if is_stop:
            n_stops += 1
            best_tid = None
            best_gain = 0.0
            best_mark = None
            for otid, ol in open_book.items():
                if otid == tid or ol.frac <= 1e-9:
                    continue
                if ol.final_closed is not None and pd.Timestamp(ol.final_closed).normalize() == pd.Timestamp(close_dt).normalize():
                    continue
                mark = mark_price(panel, ol.symbol, close_dt)
                if mark is None or not math.isfinite(ol.entry) or ol.entry <= 0:
                    if (
                        ol.final_closed is not None
                        and math.isfinite(ol.final_exit)
                        and ol.final_days > 0
                    ):
                        elapsed = max((close_dt - ol.opened).days, 0)
                        t = min(elapsed / ol.final_days, 1.0)
                        mark = ol.entry + t * (ol.final_exit - ol.entry)
                    else:
                        continue
                ur_pct = (mark / ol.entry) - 1.0
                ur_d = ur_pct * ol.notional0 * ol.frac
                if ur_d > best_gain:
                    best_gain = ur_d
                    best_tid = otid
                    best_mark = mark

            if best_tid is not None and best_gain > 0 and best_mark is not None:
                n_trims += 1
                ol = open_book[best_tid]
                trim_pnl = 0.5 * best_gain
                days_to_trim = max((close_dt - ol.opened).days, 1)
                cashflow.append(
                    {
                        "symbol": ol.symbol,
                        "opened": ol.opened.date(),
                        "closed": close_dt.date() if hasattr(close_dt, "date") else close_dt,
                        "pnl": ((best_mark / ol.entry) - 1.0) * 100.0,
                        "pnl_d": trim_pnl,
                        "days": float(days_to_trim),
                        "exit_type": "WINNER_TRIM_50",
                        "kind": "trim",
                        "trigger_stop_symbol": r["SYMBOL"],
                        "trigger_stop_loss": pnl_d,
                    }
                )
                trim_bank.setdefault(best_tid, []).append(trim_pnl)
                trim_dollars += trim_pnl
                ol.frac *= 0.5
                ol.trimmed = True
            else:
                n_no += 1

        if lot is None:
            lot = OpenLot(
                tid=tid,
                symbol=str(r["SYMBOL"]),
                opened=r["DATE_OPENED"],
                entry=float(r["ENTRY_PRICE"]),
                notional0=float(r["ENTRY_NOTIONAL"]),
                shares0=float(r["SHARES"]) if pd.notna(r["SHARES"]) else float("nan"),
                frac=1.0,
                final_pnl_d=pnl_d,
                final_exit=float(r["EXIT_PRICE"]) if pd.notna(r["EXIT_PRICE"]) else float("nan"),
                final_closed=r["DATE_CLOSED"],
                final_exit_type=str(r["EXIT_TYPE"]),
                final_days=float(r["DAYS_HELD"]) if pd.notna(r["DAYS_HELD"]) and r["DAYS_HELD"] > 0 else 1.0,
            )
            open_book[tid] = lot

        rem = lot.frac
        if rem > 1e-9:
            cashflow.append(
                {
                    "symbol": lot.symbol,
                    "opened": lot.opened.date() if hasattr(lot.opened, "date") else lot.opened,
                    "closed": close_dt.date() if hasattr(close_dt, "date") else close_dt,
                    "pnl": float(r["PNL_PCT"]) if pd.notna(r["PNL_PCT"]) else None,
                    "pnl_d": pnl_d * rem,
                    "days": float(r["DAYS_HELD"]) if pd.notna(r["DAYS_HELD"]) and r["DAYS_HELD"] > 0 else 1.0,
                    "exit_type": str(r["EXIT_TYPE"]),
                    "kind": "remainder" if lot.trimmed else "full",
                    "frac": rem,
                }
            )
        open_book.pop(tid, None)

    # Economic book: one row per original trade; dollars = early trims + final remainder
    economic: list[dict[str, Any]] = []
    for t in control:
        # find matching by symbol/opened/closed — use control order with tid from df
        economic.append(dict(t))
    # Rebuild economic from df + trim_bank for accuracy
    economic = []
    for _, r in df.iterrows():
        tid = int(r["_tid"])
        pnl_d = float(r["PNL_DOLLARS"])
        early = sum(trim_bank.get(tid, []))
        # remaining frac after all trims: 0.5 ** n_trims_on_this_lot
        n_tr = len(trim_bank.get(tid, []))
        rem_frac = 0.5 ** n_tr if n_tr else 1.0
        econ_pnl = early + pnl_d * rem_frac
        notional = float(r["ENTRY_NOTIONAL"])
        if n_tr == 0:
            econ_pct = float(r["PNL_PCT"]) if pd.notna(r["PNL_PCT"]) else None
        else:
            econ_pct = (econ_pnl / notional * 100.0) if notional else None
        economic.append(
            {
                "symbol": r["SYMBOL"],
                "opened": r["DATE_OPENED"].date() if pd.notna(r["DATE_OPENED"]) else None,
                "closed": r["DATE_CLOSED"].date() if pd.notna(r["DATE_CLOSED"]) else None,
                "pnl": econ_pct,
                "pnl_d": econ_pnl,
                "days": float(r["DAYS_HELD"]) if pd.notna(r["DAYS_HELD"]) and r["DAYS_HELD"] > 0 else 1.0,
                "exit_type": str(r["EXIT_TYPE"]),
                "kind": "economic",
                "n_trims_on_lot": n_tr,
            }
        )

    return SimResult(
        control_trades=control,
        candidate_cashflow=cashflow,
        candidate_economic=economic,
        n_stops=n_stops,
        n_trims=n_trims,
        n_stops_no_winner=n_no,
        trim_dollars=trim_dollars,
    )


def _slice_trades(trades: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    if mode == "FULL":
        return trades
    out = []
    for t in trades:
        od = t.get("opened")
        if od is None:
            continue
        if isinstance(od, datetime):
            od = od.date()
        if mode == "IS" and od < IS_CUT:
            out.append(t)
        elif mode == "OOS" and od >= IS_CUT:
            out.append(t)
    return out


def book_metrics(
    trades: list[dict[str, Any]],
    cash: float,
    *,
    cashflow_for_equity: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Quality/Ann ROR from ``trades``; Max DD/Sharpe from cashflow path if given."""
    if not trades:
        return {
            "n": 0,
            "win_pct": None,
            "avg_pnl_pct": None,
            "avg_pnl_pct_wo_max": None,
            "expectancy_d": None,
            "profit_factor": None,
            "ann_ror": None,
            "max_dd": None,
            "calmar": None,
            "sharpe": None,
            "ppcd": None,
            "capital_days": 0.0,
            "avg_days": None,
            "total_pnl_d": 0.0,
        }
    pnl = np.array([t.get("pnl") if t.get("pnl") is not None else np.nan for t in trades], dtype=float)
    pnl_d = np.array([float(t.get("pnl_d") or 0.0) for t in trades], dtype=float)
    days = np.array([float(t.get("days") or 0.0) for t in trades], dtype=float)
    n = len(trades)
    wins = int(np.nansum(pnl_d > 0))
    win_pct = 100.0 * wins / n
    avg_pct = float(np.nanmean(pnl)) if np.isfinite(pnl).any() else None
    if np.isfinite(pnl).sum() > 1:
        finite = pnl[np.isfinite(pnl)]
        wo = float(np.mean(np.delete(finite, np.nanargmax(finite)))) if len(finite) > 1 else float(finite.mean())
    else:
        wo = avg_pct
    total = float(pnl_d.sum())
    sum_w = float(pnl_d[pnl_d > 0].sum())
    sum_l = float((-pnl_d[pnl_d < 0]).sum())
    pf = (sum_w / sum_l) if sum_l > 0 else (sum_w if sum_w > 0 else None)
    days_ok = days[days > 0]
    capital_days = float(days_ok.sum()) if len(days_ok) else 0.0
    avg_days = float(days_ok.mean()) if len(days_ok) else None
    ppcd = (total / capital_days) if capital_days > 0 else None
    ann = None
    if cash > 0 and n > 0 and avg_days and avg_days > 0:
        ann = ann_ror_from_closed(
            total_pnl=total, n_trades=n, avg_days_held=avg_days, brt_cash=cash
        )
    eq_src = cashflow_for_equity if cashflow_for_equity is not None else trades
    dated = []
    for t in eq_src:
        cd = t.get("closed")
        if cd is None:
            continue
        dated.append((cd, float(t.get("pnl_d") or 0.0)))
    mdd = max_dd_pct_from_closed_pnl_by_date(dated, initial_account=DEFAULT_INITIAL_ACCOUNT)
    sharpe = sharpe_from_closed_pnl_by_date(dated, initial_account=DEFAULT_INITIAL_ACCOUNT)
    calmar = None
    if ann is not None and mdd is not None and abs(mdd) > 1e-12:
        calmar = float(ann) / abs(float(mdd))
    return {
        "n": n,
        "win_pct": win_pct,
        "avg_pnl_pct": avg_pct,
        "avg_pnl_pct_wo_max": wo,
        "expectancy_d": float(pnl_d.mean()),
        "profit_factor": pf,
        "ann_ror": ann,
        "max_dd": mdd,
        "calmar": calmar,
        "sharpe": sharpe,
        "ppcd": ppcd,
        "capital_days": capital_days,
        "avg_days": avg_days,
        "total_pnl_d": total,
    }


def _fmt(v: Any, nd: int = 2) -> str:
    if v is None:
        return "—"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(x):
        return "—"
    return f"{x:,.{nd}f}"


def _fmt_pct(v: Any, nd: int = 2) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    return f"{float(v):.{nd}f}%"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%y%m%d%H%M%S")
    all_rows: list[dict[str, Any]] = []
    per_system: dict[str, Any] = {}

    for system in SYSTEMS:
        path = _DRIVE / f"{system}_LatestRun_Closed.csv"
        if not path.exists():
            print(f"SKIP {system}: no Closed", flush=True)
            continue
        print(f"=== {system} ===", flush=True)
        try:
            df = load_closed(system)
        except Exception as e:
            print(f"  load fail: {e}", flush=True)
            continue
        if len(df) == 0:
            print("  empty", flush=True)
            continue
        cash, cash_src = _cash_for(system, df)
        syms = df["SYMBOL"].unique().tolist()
        print(
            f"  trades={len(df):,} symbols={len(syms):,} cash=${cash:,.0f} ({cash_src})",
            flush=True,
        )
        print("  loading prices…", flush=True)
        panel = load_price_panel(syms)
        print(f"  price panel symbols={len(panel):,}", flush=True)
        sim = simulate(df, panel)
        print(
            f"  stops={sim.n_stops} trims={sim.n_trims} no_winner={sim.n_stops_no_winner} "
            f"trim$={sim.trim_dollars:,.0f}",
            flush=True,
        )

        sys_block = {
            "system": system,
            "cash": cash,
            "cash_source": cash_src,
            "n_control": len(sim.control_trades),
            "n_stops": sim.n_stops,
            "n_trims": sim.n_trims,
            "n_stops_no_winner": sim.n_stops_no_winner,
            "trim_dollars": sim.trim_dollars,
            "slices": {},
        }
        for mode in ("FULL", "IS", "OOS"):
            c_tr = _slice_trades(sim.control_trades, mode)
            a_econ = _slice_trades(sim.candidate_economic, mode)
            a_cf = _slice_trades(sim.candidate_cashflow, mode)
            c_m = book_metrics(c_tr, cash)
            a_m = book_metrics(a_econ, cash, cashflow_for_equity=a_cf)
            sys_block["slices"][mode] = {"control": c_m, "candidate": a_m}
            all_rows.append(
                {
                    "SYSTEM": system,
                    "SLICE": mode,
                    "ARM": "Control",
                    "N": c_m["n"],
                    "WIN_PCT": c_m["win_pct"],
                    "AVG_PNL_PCT": c_m["avg_pnl_pct"],
                    "AVG_PNL_PCT_WO_MAX": c_m["avg_pnl_pct_wo_max"],
                    "EXPECTANCY_D": c_m["expectancy_d"],
                    "PROFIT_FACTOR": c_m["profit_factor"],
                    "ANN_ROR": c_m["ann_ror"],
                    "MAX_DD": c_m["max_dd"],
                    "CALMAR": c_m["calmar"],
                    "SHARPE": c_m["sharpe"],
                    "PPCD": c_m["ppcd"],
                    "CAPITAL_DAYS": c_m["capital_days"],
                    "AVG_DAYS": c_m["avg_days"],
                    "TOTAL_PNL_D": c_m["total_pnl_d"],
                    "N_STOPS": sim.n_stops if mode == "FULL" else "",
                    "N_TRIMS": sim.n_trims if mode == "FULL" else "",
                    "TRIM_DOLLARS": sim.trim_dollars if mode == "FULL" else "",
                }
            )
            all_rows.append(
                {
                    "SYSTEM": system,
                    "SLICE": mode,
                    "ARM": "WinnerTrim50",
                    "N": a_m["n"],
                    "WIN_PCT": a_m["win_pct"],
                    "AVG_PNL_PCT": a_m["avg_pnl_pct"],
                    "AVG_PNL_PCT_WO_MAX": a_m["avg_pnl_pct_wo_max"],
                    "EXPECTANCY_D": a_m["expectancy_d"],
                    "PROFIT_FACTOR": a_m["profit_factor"],
                    "ANN_ROR": a_m["ann_ror"],
                    "MAX_DD": a_m["max_dd"],
                    "CALMAR": a_m["calmar"],
                    "SHARPE": a_m["sharpe"],
                    "PPCD": a_m["ppcd"],
                    "CAPITAL_DAYS": a_m["capital_days"],
                    "AVG_DAYS": a_m["avg_days"],
                    "TOTAL_PNL_D": a_m["total_pnl_d"],
                    "N_STOPS": sim.n_stops if mode == "FULL" else "",
                    "N_TRIMS": sim.n_trims if mode == "FULL" else "",
                    "TRIM_DOLLARS": sim.trim_dollars if mode == "FULL" else "",
                }
            )
            d_ann = None
            if c_m["ann_ror"] is not None and a_m["ann_ror"] is not None:
                d_ann = a_m["ann_ror"] - c_m["ann_ror"]
            print(
                f"  {mode}: ctrl AnnROR={_fmt_pct(c_m['ann_ror'])} "
                f"cand={_fmt_pct(a_m['ann_ror'])} d={_fmt_pct(d_ann)} "
                f"Avg% {_fmt(c_m['avg_pnl_pct'],4)} -> {_fmt(a_m['avg_pnl_pct'],4)} "
                f"PF {_fmt(c_m['profit_factor'])} -> {_fmt(a_m['profit_factor'])}",
                flush=True,
            )
        per_system[system] = sys_block

    # CSV
    res_df = pd.DataFrame(all_rows)
    csv_path = OUT / f"system_compare_{stamp}.csv"
    res_df.to_csv(csv_path, index=False)
    (OUT / "system_compare_latest.csv").write_text(csv_path.read_text(encoding="utf-8"), encoding="utf-8")
    (OUT / "summary.json").write_text(json.dumps(per_system, indent=2, default=str), encoding="utf-8")

    baseline = f"""# Stop-loss winner-trim AB

## What you asked

{ASK}

## In plain English

{PLAIN}

## Freeze

- Control: each system's `Drive/{{SYS}}_LatestRun_Closed.csv` as published
- Candidate: on each stop-like exit (`STOP_LOSS`, `GAP_DOWN`, `STOP`, `ATR_STOP`, `TRAIL_STOP`) with negative dollars, mark other open lots (same system) at that day's warehouse close; sell **half of remaining shares** of the largest unrealized **dollar** winner; keep the rest to the original exit
- If no open winner → no trim
- Marks from `data/ohlcv.duckdb` closes (linear path fallback if missing)
- **Ann ROR / quality** use an economic book (same trade count as control; winner dollars = early trim + scaled remainder). **Max DD / Sharpe** use cash-flow dates (trim day + final exit).
- **Slot cash = Report `capacity_brt_cash`** (matches Closed `PNL_DOLLARS` scale — same basis as system_performance.html standalone Ann ROR). Do **not** force sheet $47,500 when Closed is capacity-sized (WPBR ~$4.25k/trade). Fallback: Closed median implied notional, then $47,500.
- Max DD / Sharpe seed $500,000
- IS = entry before 2024-01-01; OOS = entry on/after
- Research only — selection of rule is narrative, not walk-forward gold

## Why AB Ann ROR used to disagree with system_performance.html

An earlier draft of this stamp used flat $47,500 for every system. WPBR Closed dollars are capacity-sized (~$4,255/trade), so Ann ROR printed ~1.7% instead of the live-page ~20%. RL Closed is already ~$47.5k/trade, so RL looked close. Fixed below.

## Outputs

- `{csv_path.name}`
- `compare.html`
"""
    (OUT / "BASELINE.md").write_text(baseline, encoding="utf-8")

    # HTML
    def metric_table(slice_name: str) -> str:
        ths = "".join(
            [
                _th("System", "text"),
                _th("Ctrl N", "num"),
                _th("Trim N", "num"),
                _th("Stops", "num"),
                _th("Trims", "num"),
                _th("Ctrl WR%", "num"),
                _th("Trim WR%", "num"),
                _th("Ctrl Avg%", "num"),
                _th("Trim Avg%", "num"),
                _th("Ctrl PF", "num"),
                _th("Trim PF", "num"),
                _th("Ctrl Ann ROR%", "num"),
                _th("Trim Ann ROR%", "num"),
                _th("Δ Ann ROR pp", "num"),
                _th("Ctrl MaxDD%", "num"),
                _th("Trim MaxDD%", "num"),
                _th("Ctrl PPCD", "num"),
                _th("Trim PPCD", "num"),
            ]
        )
        body = []
        for system in SYSTEMS:
            block = per_system.get(system)
            if not block:
                continue
            sl = block["slices"].get(slice_name)
            if not sl:
                continue
            c, a = sl["control"], sl["candidate"]
            d_ann = None
            if c["ann_ror"] is not None and a["ann_ror"] is not None:
                d_ann = a["ann_ror"] - c["ann_ror"]
            body.append(
                "<tr>"
                f"<td>{html_mod.escape(system)}</td>"
                f"<td>{c['n']:,}</td>"
                f"<td>{a['n']:,}</td>"
                f"<td>{block['n_stops'] if slice_name=='FULL' else '—'}</td>"
                f"<td>{block['n_trims'] if slice_name=='FULL' else '—'}</td>"
                f"<td>{_fmt_pct(c['win_pct'])}</td>"
                f"<td>{_fmt_pct(a['win_pct'])}</td>"
                f"<td>{_fmt(c['avg_pnl_pct'], 3)}</td>"
                f"<td>{_fmt(a['avg_pnl_pct'], 3)}</td>"
                f"<td>{_fmt(c['profit_factor'])}</td>"
                f"<td>{_fmt(a['profit_factor'])}</td>"
                f"<td>{_fmt_pct(c['ann_ror'])}</td>"
                f"<td>{_fmt_pct(a['ann_ror'])}</td>"
                f"<td>{_fmt_pct(d_ann)}</td>"
                f"<td>{_fmt_pct(c['max_dd'])}</td>"
                f"<td>{_fmt_pct(a['max_dd'])}</td>"
                f"<td>{format_money(c['ppcd'])}</td>"
                f"<td>{format_money(a['ppcd'])}</td>"
                "</tr>"
            )
        return (
            f"<h2>{html_mod.escape(slice_name)} — control vs half-trim-on-stop</h2>"
            f"{SWIPE_NOTE_HTML}<div class=\"table-wrap\"><table class=\"sortable\">"
            f"<thead><tr>{ths}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
        )

    # Per-system detail blocks FULL metrics
    detail_bits = []
    for system in SYSTEMS:
        block = per_system.get(system)
        if not block:
            continue
        rows_m = []
        for label, key, fmt in [
            ("Total trades", "n", "int"),
            ("Win %", "win_pct", "pct"),
            ("Avg PnL %", "avg_pnl_pct", "num"),
            ("Book AVG_PNL_PCT_WO_MAX", "avg_pnl_pct_wo_max", "num"),
            ("Expectancy $", "expectancy_d", "money"),
            ("Profit factor", "profit_factor", "num"),
            ("Ann ROR %", "ann_ror", "pct"),
            ("Max DD %", "max_dd", "pct"),
            ("Calmar", "calmar", "num"),
            ("Sharpe", "sharpe", "num"),
            ("Profit per capital day", "ppcd", "money"),
            ("Capital days", "capital_days", "num"),
            ("Avg days held", "avg_days", "num"),
        ]:
            if is_excluded_html_compare_label(label):
                continue
            for mode in ("FULL", "IS", "OOS"):
                c = block["slices"][mode]["control"]
                a = block["slices"][mode]["candidate"]
                cv, av = c.get(key), a.get(key)
                if fmt == "money":
                    sc, sa = format_money(cv), format_money(av)
                elif fmt == "pct":
                    sc, sa = _fmt_pct(cv), _fmt_pct(av)
                elif fmt == "int":
                    sc = "—" if cv is None else f"{int(cv):,}"
                    sa = "—" if av is None else f"{int(av):,}"
                else:
                    sc, sa = _fmt(cv, 3), _fmt(av, 3)
                rows_m.append((f"{mode} · {label}", sc, sa))
        rows_m = filter_html_compare_metric_rows(rows_m, label_index=0)
        ths = "".join([_th("Metric", "text"), _th("Control", "num"), _th("WinnerTrim50", "num")])
        body = "".join(
            f"<tr><td>{html_mod.escape(a)}</td><td>{html_mod.escape(b)}</td>"
            f"<td>{html_mod.escape(c)}</td></tr>"
            for a, b, c in rows_m
        )
        detail_bits.append(
            f"<h3>{html_mod.escape(system)}</h3>"
            f"<p class=\"small\">Stops={block['n_stops']:,} · Trims fired={block['n_trims']:,} · "
            f"Stops with no open winner={block['n_stops_no_winner']:,} · "
            f"Trim $ realized={format_money(block['trim_dollars'])} · "
            f"slot cash={format_money(block['cash'])} "
            f"(<code>{html_mod.escape(str(block.get('cash_source','')))}</code>)</p>"
            f"{SWIPE_NOTE_HTML}<div class=\"table-wrap\"><table class=\"sortable\">"
            f"<thead><tr>{ths}</tr></thead><tbody>{body}</tbody></table></div>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Stop-loss winner-trim AB</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:1.2rem;line-height:1.45;color:#222;max-width:1200px}}
.callout{{background:#f4f7fb;border-left:4px solid #2a6;padding:.8rem 1rem;margin:1rem 0}}
.callout.warn{{background:#f7efe0;border-left-color:#8a5a12}}
code{{font-family:ui-monospace,Consolas,monospace;font-size:.92em}}
.small{{color:#555;font-size:.92em}}
{SORTABLE_TH_CSS}
</style></head><body>
<h1>Stop-loss → trim half the biggest open winner</h1>
<div class="callout"><h2>What you asked</h2><p>{html_mod.escape(ASK)}</p>
<h2>In plain English</h2><p>{html_mod.escape(PLAIN)}</p></div>
<div class="callout warn">
<strong>Research only.</strong> Stop-like exits = <code>STOP_LOSS</code>, <code>GAP_DOWN</code>,
<code>STOP</code>, <code>ATR_STOP</code>, <code>TRAIL_STOP</code> with negative dollars. Trim = half
of the open lot with the largest unrealized dollar gain (warehouse close that day). Relative Strength
Index (RSI) has no stop-loss exits — control = candidate. Annualized rate of return (Ann ROR) / Avg% /
PF use the <em>economic</em> book (same N as control; dollars include early trims). Max DD / Sharpe use
the cash-flow path (trim hits the equity curve on the stop day). Slot cash is each system's Report
<code>capacity_brt_cash</code> so control Ann ROR matches
<a href="https://pauljanderson.github.io/TBN_Report/system_performance.html">system_performance</a>
standalone (not a flat $47.5k when Closed is capacity-sized). In-sample entry before 2024-01-01;
out-of-sample on/after. Not gold / not DailyRun.
</div>
<p>Click column headers to sort. Source: <code>Drive/*_LatestRun_Closed.csv</code> as of this run.</p>
{metric_table("FULL")}
{metric_table("IS")}
{metric_table("OOS")}
<h2>Per-system detail (FULL / IS / OOS rows)</h2>
{''.join(detail_bits)}
<p>CSV: <code>{html_mod.escape(csv_path.name)}</code></p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    html_path = OUT / "compare.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"Wrote {csv_path}", flush=True)
    print(f"Wrote {html_path}", flush=True)
    print(f"Wrote {OUT / 'BASELINE.md'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
