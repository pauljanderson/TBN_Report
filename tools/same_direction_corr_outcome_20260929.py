#!/usr/bin/env python3
"""Walk-forward test: does a tighter pair correlation make a gap fade pay?

Research only. Correlation menus use a trailing 500 trading days, refreshed
every 21 sessions. Nothing is refit after seeing the 2024+ results.
"""
from __future__ import annotations

import html
import importlib.util
import math
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
from compare_format import format_money  # noqa: E402

DB = ROOT / "data" / "ohlcv.duckdb"
OUT_DIR = ROOT / "drive" / "paul_experiments" / "same_direction_corr_outcome_20260929"
OUT_HTML = OUT_DIR / "report.html"

LOOKBACK = 500
REFRESH = 21
ENTRY_Z = 2.0
EXIT_Z = 0.5
HOLD_63 = 63
HOLD_126 = 126
MAX_ABS_PCT = 80.0
STAKE = 10_000.0
IS_CUT = pd.Timestamp("2024-01-01")
MIN_BIN_N = 30
# Frozen before the run. Lower edge is the candidate minimum correlation.
BINS: list[tuple[float, float, str]] = [
    (0.00, 0.30, "Under 0.30"),
    (0.30, 0.50, "0.30 to 0.50"),
    (0.50, 0.70, "0.50 to 0.70"),
    (0.70, 0.85, "0.70 to 0.85"),
    (0.85, 0.95, "0.85 to 0.95"),
    (0.95, 1.01, "0.95 and up"),
]

ORIGINAL_REQUEST = (
    "I was thinking more along the lines of on day 500 identify up to that point, "
    "the top 10 most correlated stocks and the biggest gap, or maybe the top 100 and "
    "the biggest gap. Let's measure the correlation with the outcome. Is it those that "
    "are highly correlated? Have a better outcome, and is there a minimum correlation? "
    "We should look at if we were going to implement this as an actual system."
)


def _load_style():
    path = ROOT / "tools" / "same_direction_pairs_20260929.py"
    spec = importlib.util.spec_from_file_location("pairs_style", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


STYLE = _load_style()


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def load_panel() -> tuple[pd.DatetimeIndex, list[str], np.ndarray, np.ndarray, np.ndarray]:
    con = duckdb.connect(str(DB), read_only=True)
    try:
        frame = con.execute(
            """
            SELECT symbol, date, open, close
            FROM prices
            WHERE close > 0 AND open > 0 AND symbol <> 'SPY'
            """
        ).fetchdf()
    finally:
        con.close()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    opens: dict[str, pd.Series] = {}
    closes: dict[str, pd.Series] = {}
    for symbol, group in frame.groupby("symbol", sort=False):
        bars = group.drop_duplicates("date").set_index("date").sort_index()
        close_adj, _hits = STYLE.split_adjust(bars["close"].astype(float))
        scale = (close_adj / bars["close"].astype(float)).replace([np.inf, -np.inf], np.nan)
        open_adj = bars["open"].astype(float) * scale
        closes[str(symbol)] = close_adj
        opens[str(symbol)] = open_adj
    close_w = pd.DataFrame(closes).sort_index()
    open_w = pd.DataFrame(opens).sort_index().reindex(close_w.index)
    recent = close_w.iloc[-10:].notna().any()
    cover = close_w.notna().mean() >= 0.60
    keep = [s for s in close_w.columns if bool(recent.get(s, False) and cover.get(s, False))]
    keep = sorted(keep)
    close_w = close_w[keep]
    open_w = open_w[keep]
    log_c = np.log(close_w.to_numpy(dtype=float))
    log_r = np.full_like(log_c, np.nan)
    log_r[1:] = log_c[1:] - log_c[:-1]
    # A one-day corporate-action leftover should not set the correlation.
    log_r = np.where(np.isfinite(log_r) & (np.abs(log_r) > math.log(1.40)), np.nan, log_r)
    return pd.DatetimeIndex(close_w.index), keep, log_c, log_r, open_w.to_numpy(dtype=float)


def _usable_window(arr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return a filled (T, K) array and the column indexes kept."""
    finite = np.isfinite(arr)
    keep = finite.mean(axis=0) >= 0.95
    idx = np.flatnonzero(keep)
    sub = arr[:, idx].copy()
    if sub.size == 0:
        return sub, idx
    mask = np.isfinite(sub)
    # Neutral fill: a missing day gets that stock's own average in the window.
    counts = mask.sum(axis=0)
    sums = np.where(mask, sub, 0.0).sum(axis=0)
    means = np.divide(sums, counts, out=np.zeros_like(sums), where=counts > 0)
    sub = np.where(mask, sub, means)
    return sub, idx


def window_matrices(log_c: np.ndarray, log_r: np.ndarray, t: int) -> dict | None:
    """Trailing link ending yesterday, evaluated on today's close at index t."""
    if t < LOOKBACK + 1:
        return None
    prices = log_c[t - LOOKBACK : t]
    rets = log_r[t - LOOKBACK + 1 : t + 1]
    # rets row aligned so the last return is the move into yesterday (index t-1).
    if prices.shape[0] != LOOKBACK or rets.shape[0] != LOOKBACK:
        return None
    px, px_idx = _usable_window(prices)
    rt, rt_idx = _usable_window(rets)
    common = np.intersect1d(px_idx, rt_idx)
    if common.size < 30:
        return None
    px_map = {int(g): i for i, g in enumerate(px_idx)}
    rt_map = {int(g): i for i, g in enumerate(rt_idx)}
    px = np.column_stack([px[:, px_map[int(g)]] for g in common])
    rt = np.column_stack([rt[:, rt_map[int(g)]] for g in common])
    n = px.shape[0]
    px_c = px - px.mean(axis=0)
    rt_c = rt - rt.mean(axis=0)
    px_var = (px_c * px_c).sum(axis=0) / (n - 1)
    rt_var = (rt_c * rt_c).sum(axis=0) / (n - 1)
    good = (px_var > 1e-12) & (rt_var > 1e-12)
    if int(good.sum()) < 30:
        return None
    common = common[good]
    px_c = px_c[:, good]
    rt_c = rt_c[:, good]
    px = px[:, good]
    px_var = px_var[good]
    rt_var = rt_var[good]
    px_cov = (px_c.T @ px_c) / (n - 1)
    rt_cov = (rt_c.T @ rt_c) / (n - 1)
    px_std = np.sqrt(px_var)
    rt_std = np.sqrt(rt_var)
    with np.errstate(invalid="ignore", divide="ignore"):
        px_corr = px_cov / np.outer(px_std, px_std)
        rt_corr = rt_cov / np.outer(rt_std, rt_std)
        beta = px_cov / px_var[None, :]
    r2 = np.clip(px_corr * px_corr, 0.0, 0.999999)
    resid_var = px_var[:, None] * (1.0 - r2)
    scale = np.sqrt(np.maximum(resid_var, 0.0))
    today = log_c[t, common]
    mean_px = px.mean(axis=0)
    alpha = mean_px[:, None] - beta * mean_px[None, :]
    # Left symbol is the row (dependent), right symbol is the column.
    resid = today[:, None] - alpha - beta * today[None, :]
    with np.errstate(invalid="ignore", divide="ignore"):
        z = resid / scale
    z = np.where(scale > 1e-6, z, np.nan)
    # Alpha stored for forward replay is mean_y - beta * mean_x, residual mean 0.
    return {
        "idx": common,
        "rt_corr": rt_corr,
        "alpha": alpha,
        "beta": beta,
        "scale": scale,
        "z": z,
        "resid": resid,
    }


def _top_pairs(stats: dict, k: int) -> list[dict]:
    corr = stats["rt_corr"]
    n = corr.shape[0]
    iu = np.triu_indices(n, k=1)
    vals = corr[iu]
    finite = np.isfinite(vals) & (vals > 0)
    if not finite.any():
        return []
    order_local = np.flatnonzero(finite)
    take = min(k, order_local.size)
    chosen = order_local[np.argpartition(vals[order_local], -take)[-take:]]
    chosen = chosen[np.argsort(vals[chosen])[::-1]]
    rows = []
    for pos in chosen:
        li = int(iu[0][pos])
        rj = int(iu[1][pos])
        rows.append(_pair_record(stats, li, rj, float(vals[pos]), rank=len(rows) + 1))
    return rows


def _pair_record(stats: dict, li: int, rj: int, corr: float, rank: int | None) -> dict:
    gi = int(stats["idx"][li])
    gj = int(stats["idx"][rj])
    resid = float(stats["resid"][li, rj])
    return {
        "li": li,
        "rj": rj,
        "i": gi,
        "j": gj,
        "corr": corr,
        "rank": rank,
        "alpha": float(stats["alpha"][li, rj]),
        "beta": float(stats["beta"][li, rj]),
        "scale": float(stats["scale"][li, rj]),
        "z": float(stats["z"][li, rj]),
        "resid": resid,
        "pct": 100.0 * (math.exp(resid) - 1.0) if np.isfinite(resid) else float("nan"),
    }


def _biggest_in_bin(stats: dict, lo: float, hi: float, busy: set[tuple[int, int]]) -> dict | None:
    corr = stats["rt_corr"]
    z = stats["z"]
    n = corr.shape[0]
    iu = np.triu_indices(n, k=1)
    c = corr[iu]
    zz = z[iu]
    resid = stats["resid"][iu]
    pct = 100.0 * (np.exp(resid) - 1.0)
    ok = (
        np.isfinite(c) & np.isfinite(zz) & np.isfinite(pct)
        & (c >= lo) & (c < hi)
        & (np.abs(zz) >= ENTRY_Z)
        & (np.abs(pct) <= MAX_ABS_PCT)
    )
    if not ok.any():
        return None
    cand = np.flatnonzero(ok)
    # Skip pairs already in a study trade. Scan from the widest percent gap down.
    order = cand[np.argsort(np.abs(pct[cand]))[::-1]]
    for pos in order:
        li = int(iu[0][pos])
        rj = int(iu[1][pos])
        gi = int(stats["idx"][li])
        gj = int(stats["idx"][rj])
        if (gi, gj) in busy:
            continue
        rec = _pair_record(stats, li, rj, float(c[pos]), rank=None)
        rec["pct"] = float(pct[pos])
        return rec
    return None


def _verify_z(log_c: np.ndarray, stats: dict, t: int) -> None:
    corr = stats["rt_corr"]
    n = corr.shape[0]
    iu = np.triu_indices(n, k=1)
    if iu[0].size == 0:
        return
    pos = int(np.nanargmax(np.where(np.isfinite(corr[iu]), corr[iu], -np.inf)))
    li = int(iu[0][pos])
    rj = int(iu[1][pos])
    gi = int(stats["idx"][li])
    gj = int(stats["idx"][rj])
    y = log_c[t - LOOKBACK : t, gi]
    x = log_c[t - LOOKBACK : t, gj]
    if not (np.isfinite(y).all() and np.isfinite(x).all() and np.isfinite(log_c[t, gi])):
        return
    alpha, beta, resid = STYLE.ols_fit(x, y)
    scale = float(np.std(resid, ddof=1))
    z_ref = (float(log_c[t, gi]) - (alpha + beta * float(log_c[t, gj]))) / scale
    z_mat = float(stats["z"][li, rj])
    if not (np.isfinite(z_ref) and abs(z_ref - z_mat) < 1e-6):
        raise RuntimeError(f"z check failed ref {z_ref} matrix {z_mat}")


def _shares(price: float) -> int:
    if not np.isfinite(price) or price <= 0:
        return 0
    return int(STAKE // price)


def _pnl(shares_long: int, entry_long: float, exit_long: float, shares_short: int, entry_short: float, exit_short: float) -> float:
    return shares_long * (exit_long - entry_long) + shares_short * (entry_short - exit_short)


def _sides(rec: dict, symbols: list[str]) -> tuple[str, str, int, int]:
    """Return long symbol, short symbol, long index, short index."""
    if rec["pct"] >= 0:
        short_i, long_i = rec["i"], rec["j"]
    else:
        short_i, long_i = rec["j"], rec["i"]
    return symbols[long_i], symbols[short_i], long_i, short_i


def _price_ok(opens: np.ndarray, t: int, a: int, b: int) -> bool:
    if t < 0 or t >= opens.shape[0]:
        return False
    return bool(np.isfinite(opens[t, a]) and np.isfinite(opens[t, b]) and opens[t, a] > 0 and opens[t, b] > 0)


def run_study(
    dates: pd.DatetimeIndex,
    symbols: list[str],
    log_c: np.ndarray,
    opens: np.ndarray,
) -> tuple[list[dict], list[dict], dict]:
    """Refresh-day bin trades, plus daily top-10 and top-100 one-slot books."""
    t_count = len(dates)
    refresh_points = list(range(LOOKBACK + 1, t_count - 1, REFRESH))
    menus: dict[int, list[dict]] = {}
    cutoffs: list[dict] = []
    latest_top10: list[dict] = []
    checked = False

    study_open: dict[tuple[int, int], dict] = {}
    study_done: list[dict] = []
    pending_study: list[dict] = []

    books = {
        "top10_open": {"cap": None, "label": "Top 10, hold until they line up"},
        "top10_cap": {"cap": HOLD_126, "label": "Top 10, line up or six months"},
        "top100_open": {"cap": None, "label": "Top 100, hold until they line up"},
        "top100_cap": {"cap": HOLD_126, "label": "Top 100, line up or six months"},
    }
    for book in books.values():
        book["position"] = None
        book["pending_entry"] = None
        book["pending_exit"] = None
        book["trades"] = []
        book["realized"] = 0.0
        book["last_unreal"] = 0.0
        book["equity"] = []

    current_menu: list[dict] = []

    def frozen_z(pos: dict, t: int) -> float:
        yi = log_c[t, pos["y_i"]]
        xi = log_c[t, pos["x_i"]]
        if not (np.isfinite(yi) and np.isfinite(xi)):
            return float("nan")
        resid = float(yi - (pos["alpha"] + pos["beta"] * xi))
        return resid / pos["scale"]

    def open_trade_from(rec: dict, entry_t: int) -> dict | None:
        long_name, short_name, long_i, short_i = _sides(rec, symbols)
        if not _price_ok(opens, entry_t, long_i, short_i):
            return None
        entry_long = float(opens[entry_t, long_i])
        entry_short = float(opens[entry_t, short_i])
        shares_long = _shares(entry_long)
        shares_short = _shares(entry_short)
        if shares_long <= 0 or shares_short <= 0:
            return None
        # y is the left symbol (row), x is the right symbol (column).
        return {
            "i": rec["i"],
            "j": rec["j"],
            "y_i": rec["i"],
            "x_i": rec["j"],
            "pair": f"{symbols[rec['i']]} / {symbols[rec['j']]}",
            "long": long_name,
            "short": short_name,
            "long_i": long_i,
            "short_i": short_i,
            "shares_long": shares_long,
            "shares_short": shares_short,
            "entry_long": entry_long,
            "entry_short": entry_short,
            "entry_t": entry_t,
            "entry_date": dates[entry_t],
            "signal_date": dates[rec["signal_t"]],
            "corr": rec["corr"],
            "z_entry": rec["z"],
            "pct_entry": rec["pct"],
            "alpha": rec["alpha"],
            "beta": rec["beta"],
            "scale": rec["scale"],
            "bin": rec.get("bin", ""),
            "rank": rec.get("rank"),
            "pnl21": None,
            "pnl63": None,
            "pnl126": None,
            "align_date": None,
            "align_pnl": None,
            "capped63_pnl": None,
            "capped126_pnl": None,
        }

    def mark_horizons(trade: dict, t: int) -> None:
        held = t - trade["entry_t"]
        if held not in (HOLD_63 // 3, HOLD_63, HOLD_126) and held != 21:
            return
        if not _price_ok(opens, t, trade["long_i"], trade["short_i"]):
            return
        net = _pnl(
            trade["shares_long"], trade["entry_long"], float(opens[t, trade["long_i"]]),
            trade["shares_short"], trade["entry_short"], float(opens[t, trade["short_i"]]),
        )
        if held == 21:
            trade["pnl21"] = net
        elif held == HOLD_63:
            trade["pnl63"] = net
            if trade["capped63_pnl"] is None:
                trade["capped63_pnl"] = trade["align_pnl"] if trade["align_pnl"] is not None else net
        elif held == HOLD_126:
            trade["pnl126"] = net
            if trade["capped126_pnl"] is None:
                trade["capped126_pnl"] = trade["align_pnl"] if trade["align_pnl"] is not None else net

    def close_book(book: dict, t: int, reason: str) -> None:
        pos = book["position"]
        if pos is None or not _price_ok(opens, t, pos["long_i"], pos["short_i"]):
            return
        exit_long = float(opens[t, pos["long_i"]])
        exit_short = float(opens[t, pos["short_i"]])
        net = _pnl(pos["shares_long"], pos["entry_long"], exit_long, pos["shares_short"], pos["entry_short"], exit_short)
        book["realized"] += net
        book["trades"].append({
            **pos,
            "exit_date": dates[t],
            "exit_long": exit_long,
            "exit_short": exit_short,
            "net": net,
            "reason": reason,
            "status": "closed",
            "days": int((dates[t] - pos["entry_date"]).days),
        })
        book["position"] = None
        book["pending_exit"] = None
        book["last_unreal"] = 0.0

    for t in range(LOOKBACK + 1, t_count):
        # Fills at today's open.
        still_pending = []
        for rec in pending_study:
            if t < rec["fill_t"]:
                still_pending.append(rec)
                continue
            opened = open_trade_from(rec, t)
            if opened is None:
                if t > rec["fill_t"] + 3:
                    study_open.pop((rec["i"], rec["j"]), None)
                    continue
                still_pending.append(rec)
                continue
            study_open[(rec["i"], rec["j"])] = opened
        pending_study = still_pending

        for book in books.values():
            if book["pending_exit"] is not None and book["position"] is not None and t >= book["pending_exit"]["fill_t"]:
                close_book(book, t, book["pending_exit"]["reason"])
            if book["pending_entry"] is not None and book["position"] is None and t >= book["pending_entry"]["fill_t"]:
                opened = open_trade_from(book["pending_entry"], t)
                if opened is None:
                    if t > book["pending_entry"]["fill_t"] + 3:
                        book["pending_entry"] = None
                else:
                    book["position"] = opened
                    book["pending_entry"] = None

        for trade in study_open.values():
            if trade["entry_t"] is None or t <= trade["entry_t"]:
                continue
            mark_horizons(trade, t)
            if trade["align_pnl"] is None:
                z_now = frozen_z(trade, t)
                if np.isfinite(z_now) and abs(z_now) <= EXIT_Z and _price_ok(opens, t + 1 if t + 1 < t_count else -1, trade["long_i"], trade["short_i"]):
                    # Exit next open. Record here only as a signal; fill is handled when t advances.
                    trade["align_signal_t"] = t

        # Alignment fills for study trades (signal was yesterday).
        finished_keys = []
        for key, trade in study_open.items():
            sig = trade.get("align_signal_t")
            if sig is None or t != sig + 1:
                continue
            if not _price_ok(opens, t, trade["long_i"], trade["short_i"]):
                continue
            net = _pnl(
                trade["shares_long"], trade["entry_long"], float(opens[t, trade["long_i"]]),
                trade["shares_short"], trade["entry_short"], float(opens[t, trade["short_i"]]),
            )
            trade["align_date"] = dates[t]
            trade["align_pnl"] = net
            if trade["capped63_pnl"] is None and (t - trade["entry_t"]) <= HOLD_63:
                trade["capped63_pnl"] = net
            if trade["capped126_pnl"] is None and (t - trade["entry_t"]) <= HOLD_126:
                trade["capped126_pnl"] = net
            # Keep the trade alive so later fixed-horizon marks still print.
            if trade["pnl126"] is not None or (t_count - 1 - trade["entry_t"]) < HOLD_126 and t > trade["entry_t"] + HOLD_126:
                finished_keys.append(key)
        # Retire trades that have their 126-day mark or have run out of calendar after that horizon.
        for key, trade in list(study_open.items()):
            if trade["entry_t"] is None:
                continue
            if trade["pnl126"] is not None or t - trade["entry_t"] > HOLD_126:
                study_done.append(trade)
                finished_keys.append(key)
        for key in set(finished_keys):
            study_open.pop(key, None)

        # New rankings.
        if t in set(refresh_points) or (t - (LOOKBACK + 1)) % REFRESH == 0:
            stats = window_matrices(log_c, log_r_holder, t) if False else window_matrices(log_c, log_r, t)
            if stats is not None:
                if not checked:
                    _verify_z(log_c, stats, t)
                    checked = True
                menu = _top_pairs(stats, 100)
                menus[t] = menu
                current_menu = menu
                if menu:
                    cutoffs.append({
                        "date": dates[t],
                        "top10": menu[min(9, len(menu) - 1)]["corr"],
                        "top100": menu[-1]["corr"] if len(menu) >= 100 else menu[-1]["corr"],
                        "n": len(menu),
                    })
                    latest_top10 = menu[:10]
                busy = set(study_open) | {(p["i"], p["j"]) for p in pending_study}
                for lo, hi, label in BINS:
                    rec = _biggest_in_bin(stats, lo, hi, busy)
                    if rec is None or t + 1 >= t_count:
                        continue
                    rec["bin"] = label
                    rec["signal_t"] = t
                    rec["fill_t"] = t + 1
                    pending_study.append(rec)
                    busy.add((rec["i"], rec["j"]))

        # Daily books use the latest menu versus today's close.
        if current_menu:
            live = []
            for rec in current_menu:
                yi = log_c[t, rec["i"]]
                xi = log_c[t, rec["j"]]
                if not (np.isfinite(yi) and np.isfinite(xi)) or rec["scale"] <= 1e-6:
                    continue
                resid = float(yi - (rec["alpha"] + rec["beta"] * xi))
                pct = 100.0 * (math.exp(resid) - 1.0)
                z_now = resid / rec["scale"]
                if not (np.isfinite(z_now) and np.isfinite(pct)):
                    continue
                if abs(z_now) < ENTRY_Z or abs(pct) > MAX_ABS_PCT:
                    continue
                row = dict(rec)
                row["z"] = z_now
                row["pct"] = pct
                row["resid"] = resid
                row["signal_t"] = t
                live.append(row)
            live.sort(key=lambda r: abs(r["pct"]), reverse=True)

            for name, book in books.items():
                k = 10 if name.startswith("top10") else 100
                pool = [r for r in live if (r.get("rank") or 999) <= k]
                pos = book["position"]
                if pos is not None and book["pending_exit"] is None and t > pos["entry_t"]:
                    z_now = frozen_z(pos, t)
                    reason = None
                    if np.isfinite(z_now) and abs(z_now) <= EXIT_Z:
                        reason = "Back near the entry line"
                    elif book["cap"] is not None and (t - pos["entry_t"]) >= book["cap"]:
                        reason = "Six-month cap"
                    if reason is not None and t + 1 < t_count:
                        book["pending_exit"] = {"fill_t": t + 1, "reason": reason}
                if pos is None and book["pending_entry"] is None and book["pending_exit"] is None and pool and t + 1 < t_count:
                    choice = dict(pool[0])
                    choice["signal_t"] = t
                    choice["fill_t"] = t + 1
                    book["pending_entry"] = choice

        for book in books.values():
            unreal = 0.0
            pos = book["position"]
            if pos is not None and np.isfinite(log_c[t, pos["long_i"]]) and np.isfinite(log_c[t, pos["short_i"]]):
                # Mark on close, reconstructed from the open-price ledger using close via log_c exp.
                long_px = float(math.exp(log_c[t, pos["long_i"]]))
                short_px = float(math.exp(log_c[t, pos["short_i"]]))
                unreal = _pnl(pos["shares_long"], pos["entry_long"], long_px, pos["shares_short"], pos["entry_short"], short_px)
                book["last_unreal"] = unreal
            elif pos is not None:
                unreal = book["last_unreal"]
            book["equity"].append(STAKE + book["realized"] + unreal)

    for trade in study_open.values():
        study_done.append(trade)
    for book in books.values():
        pos = book["position"]
        if pos is None:
            continue
        last = t_count - 1
        if not (np.isfinite(log_c[last, pos["long_i"]]) and np.isfinite(log_c[last, pos["short_i"]])):
            continue
        exit_long = float(math.exp(log_c[last, pos["long_i"]]))
        exit_short = float(math.exp(log_c[last, pos["short_i"]]))
        net = _pnl(pos["shares_long"], pos["entry_long"], exit_long, pos["shares_short"], pos["entry_short"], exit_short)
        book["trades"].append({
            **pos,
            "exit_date": pd.NaT,
            "mark_date": dates[last],
            "exit_long": exit_long,
            "exit_short": exit_short,
            "net": net,
            "reason": "Still open at the last price",
            "status": "open",
            "days": int((dates[last] - pos["entry_date"]).days),
        })

    meta = {
        "symbols": len(symbols),
        "refreshes": len(cutoffs),
        "first": dates[refresh_points[0]].date().isoformat() if refresh_points else "—",
        "last": dates[-1].date().isoformat(),
        "median_top10": float(np.median([c["top10"] for c in cutoffs])) if cutoffs else float("nan"),
        "median_top100": float(np.median([c["top100"] for c in cutoffs])) if cutoffs else float("nan"),
        "latest_top10": [
            {"pair": f"{symbols[r['i']]} / {symbols[r['j']]}", "corr": r["corr"]}
            for r in latest_top10
        ],
        "latest_date": dates[max(menus)].date().isoformat() if menus else "—",
    }
    return study_done, books, meta


# Filled in load so window_matrices can see returns. Set in main before run.
log_r: np.ndarray


def _spearman(x: list[float], y: list[float]) -> float:
    if len(x) < 8:
        return float("nan")
    rx = pd.Series(x).rank().to_numpy()
    ry = pd.Series(y).rank().to_numpy()
    if float(np.std(rx)) == 0 or float(np.std(ry)) == 0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def _fmt_pct(value: float, digits: int = 1) -> str:
    if value is None or not np.isfinite(value):
        return "—"
    return f"{value:+.{digits}f}%"


def _fmt_num(value: float, digits: int = 2) -> str:
    if value is None or not np.isfinite(value):
        return "—"
    return f"{value:.{digits}f}"


def _bin_stats(trades: list[dict], label: str, start: pd.Timestamp | None, end: pd.Timestamp | None) -> dict:
    rows = []
    for t in trades:
        d = pd.Timestamp(t["entry_date"])
        if start is not None and d < start:
            continue
        if end is not None and d >= end:
            continue
        if t.get("bin") != label or t.get("pnl63") is None:
            continue
        rows.append(t)
    if not rows:
        return {"n": 0, "wins": 0, "win": float("nan"), "avg": float("nan"), "median": float("nan"),
                "align": float("nan"), "avg126": float("nan"), "spearman_x": [], "spearman_y": []}
    pnl = np.array([t["pnl63"] for t in rows], dtype=float) / STAKE * 100.0
    have126 = [t["pnl126"] for t in rows if t.get("pnl126") is not None]
    aligned = [t for t in rows if t.get("align_pnl") is not None and t.get("align_date") is not None and (pd.Timestamp(t["align_date"]) - pd.Timestamp(t["entry_date"])).days <= 140]
    return {
        "n": len(rows),
        "wins": int((pnl > 0).sum()),
        "win": 100.0 * float((pnl > 0).mean()),
        "avg": float(np.mean(pnl)),
        "median": float(np.median(pnl)),
        "align": 100.0 * len(aligned) / len(rows),
        "avg126": float(np.mean(np.array(have126) / STAKE * 100.0)) if have126 else float("nan"),
        "spearman_x": [t["corr"] for t in rows],
        "spearman_y": [float(t["pnl63"]) / STAKE * 100.0 for t in rows],
    }


def _book_stats(trades: list[dict], equity: list[float], start: pd.Timestamp | None, end: pd.Timestamp | None) -> dict:
    closed = []
    for t in trades:
        if t["status"] != "closed":
            continue
        d = pd.Timestamp(t["entry_date"])
        if start is not None and d < start:
            continue
        if end is not None and d >= end:
            continue
        closed.append(t)
    open_n = sum(1 for t in trades if t["status"] == "open" and (start is None or pd.Timestamp(t["entry_date"]) >= (start or pd.Timestamp.min)) and (end is None or pd.Timestamp(t["entry_date"]) < end))
    if not closed:
        return {"n": 0, "wins": 0, "win": float("nan"), "avg": float("nan"), "median_days": float("nan"),
                "pf": float("nan"), "max_dd": float("nan"), "open": open_n, "avg_corr": float("nan")}
    nets = np.array([t["net"] for t in closed], dtype=float)
    pcts = nets / STAKE * 100.0
    days = np.array([t["days"] for t in closed], dtype=float)
    wins = nets[nets > 0].sum()
    losses = -nets[nets <= 0].sum()
    pf = float(wins / losses) if losses > 0 else float("nan")
    # Drawdown on the full path; period slices still report that book's whole-path DD when start is None.
    max_dd = float("nan")
    if start is None and equity:
        eq = np.array(equity, dtype=float)
        peak = np.maximum.accumulate(eq)
        max_dd = float((eq / peak - 1.0).min() * 100.0)
    return {
        "n": len(closed),
        "wins": int((nets > 0).sum()),
        "win": 100.0 * float((nets > 0).mean()),
        "avg": float(np.mean(pcts)),
        "median_days": float(np.median(days)),
        "pf": pf,
        "max_dd": max_dd,
        "open": open_n,
        "avg_corr": float(np.mean([t["corr"] for t in closed])),
    }


def _floor_text(is_rows: list[dict], oos_rows: list[dict]) -> tuple[str, str]:
    def ok(row: dict) -> bool:
        return row["n"] >= MIN_BIN_N and np.isfinite(row["avg"]) and row["avg"] > 0 and row["win"] >= 50

    flags = [ok(r) for r in is_rows]
    floor_label = None
    for k, row in enumerate(is_rows):
        if flags[k] and all(flags[k:]):
            floor_label = row["label"]
            break
    if floor_label is None:
        prose = (
            "On buys from before 2024, no correlation band cleared a simple bar "
            f"(at least {MIN_BIN_N} finished three-month trades, more winners than losers, "
            "and a positive average) together with every tighter band above it. "
            "There is not a clean minimum correlation to switch on."
        )
        tone = "warn"
    else:
        prose = (
            f"On buys from before 2024, the average three-month trade turned up once pairs were in "
            f"“{floor_label}” and stayed up in every tighter band above that. "
            "That early-year line is the minimum we would write down. It was not chosen by looking at 2024 onward."
        )
        # OOS check of that floor and above.
        start = next(i for i, r in enumerate(is_rows) if r["label"] == floor_label)
        oos_flags = [ok(r) for r in oos_rows[start:]]
        if oos_flags and all(oos_flags):
            prose += " Entries from 2024 on stayed positive in those same bands."
            tone = "ok"
        elif any(r["n"] < MIN_BIN_N for r in oos_rows[start:]):
            prose += " Entries from 2024 on are too few in at least one of those bands to confirm it. Hold."
            tone = "warn"
        else:
            prose += " Entries from 2024 on did not stay positive in those same bands. Hold. Do not lower or raise the line to chase the later years."
            tone = "bad"
    return prose, tone


def _th(label: str, sort: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{_esc(label)}<span class="sort-ind"></span></th>'
    )


def _table(headers: list[tuple[str, str]], rows: list[list[str]], caption: str) -> str:
    head = "".join(_th(a, b) for a, b in headers)
    body = []
    for row in rows:
        tds = []
        for i, cell in enumerate(row):
            sort = headers[i][1]
            if sort == "text":
                tds.append(f"<td>{cell}</td>")
            else:
                tds.append(f'<td class="num">{cell}</td>')
        body.append("<tr>" + "".join(tds) + "</tr>")
    return (
        '<div class="table-wrap"><table class="sortable">'
        f"<caption>{caption} Click column headers to sort.</caption>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def _book_menu_sentence(books: dict) -> tuple[str, str]:
    """Compare the six-month-cap books on entries before 2024. Report 2024 on, do not retune."""
    a = _book_stats(books["top10_cap"]["trades"], books["top10_cap"]["equity"], None, IS_CUT)
    b = _book_stats(books["top100_cap"]["trades"], books["top100_cap"]["equity"], None, IS_CUT)
    ao = _book_stats(books["top10_cap"]["trades"], [], IS_CUT, None)
    bo = _book_stats(books["top100_cap"]["trades"], [], IS_CUT, None)
    if a["n"] < 8 or b["n"] < 8 or not np.isfinite(a["avg"]) or not np.isfinite(b["avg"]):
        return (
            "The one-trade-at-a-time books do not have enough finished trades before 2024 to prefer the top 10 menu or the top 100 menu.",
            "warn",
        )
    early_prefers_10 = a["avg"] > b["avg"] + 0.5
    early_prefers_100 = b["avg"] > a["avg"] + 0.5
    if not early_prefers_10 and not early_prefers_100:
        text = (
            f"Before 2024 the top 10 menu averaged {_fmt_pct(a['avg'])} per finished trade and the top 100 menu averaged {_fmt_pct(b['avg'])}. "
            "That gap is small. There is no reason yet to prefer one list length."
        )
        pref = None
    elif early_prefers_10:
        text = (
            f"Before 2024 the tighter list did better: top 10 averaged {_fmt_pct(a['avg'])} per finished trade, "
            f"top 100 averaged {_fmt_pct(b['avg'])}."
        )
        pref = "top10"
    else:
        text = (
            f"Before 2024 the wider list did better: top 100 averaged {_fmt_pct(b['avg'])} per finished trade, "
            f"top 10 averaged {_fmt_pct(a['avg'])}."
        )
        pref = "top100"
    if pref == "top10" and np.isfinite(ao["avg"]) and np.isfinite(bo["avg"]):
        if ao["avg"] > bo["avg"]:
            text += f" From 2024 on, top 10 still led ({_fmt_pct(ao['avg'])} versus {_fmt_pct(bo['avg'])})."
            tone = "ok"
        else:
            text += f" From 2024 on that lead disappeared (top 10 {_fmt_pct(ao['avg'])}, top 100 {_fmt_pct(bo['avg'])}). Hold."
            tone = "warn"
    elif pref == "top100" and np.isfinite(ao["avg"]) and np.isfinite(bo["avg"]):
        if bo["avg"] > ao["avg"]:
            text += f" From 2024 on, top 100 still led ({_fmt_pct(bo['avg'])} versus {_fmt_pct(ao['avg'])})."
            tone = "ok"
        else:
            text += f" From 2024 on that lead disappeared (top 100 {_fmt_pct(bo['avg'])}, top 10 {_fmt_pct(ao['avg'])}). Hold."
            tone = "warn"
    else:
        tone = "warn"
    text += " This comparison uses the version that also closes at six months, so one pair cannot occupy the account for years."
    return text, tone


def write_report(study: list[dict], books: dict, meta: dict) -> None:
    periods = [
        ("All years", None, None),
        ("Before 2024", None, IS_CUT),
        ("2024 on", IS_CUT, None),
    ]
    bin_headers = [
        ("Correlation", "text"), ("When the buy happened", "text"), ("Trades", "num"),
        ("Win %", "num"), ("Average result, 3 months", "num"), ("Median, 3 months", "num"),
        ("Lined up within about 6 months", "num"), ("Average result, 6 months", "num"),
    ]
    bin_rows = []
    is_for_floor = []
    oos_for_floor = []
    spearman_bits = []
    for _lo, _hi, label in BINS:
        is_row = _bin_stats(study, label, None, IS_CUT)
        oos_row = _bin_stats(study, label, IS_CUT, None)
        is_row["label"] = label
        oos_row["label"] = label
        is_for_floor.append(is_row)
        oos_for_floor.append(oos_row)
        for period, start, end in periods:
            st = _bin_stats(study, label, start, end)
            bin_rows.append([
                _esc(label), _esc(period), str(st["n"]),
                _fmt_pct(st["win"]).replace("+", ""),
                _fmt_pct(st["avg"]), _fmt_pct(st["median"]),
                _fmt_pct(st["align"]).replace("+", ""),
                _fmt_pct(st["avg126"]),
            ])
        if is_row["spearman_x"]:
            spearman_bits.append((label, is_row, oos_row))

    all_is = [t for t in study if pd.Timestamp(t["entry_date"]) < IS_CUT and t.get("pnl63") is not None]
    all_oos = [t for t in study if pd.Timestamp(t["entry_date"]) >= IS_CUT and t.get("pnl63") is not None]
    sp_is = _spearman([t["corr"] for t in all_is], [t["pnl63"] / STAKE * 100.0 for t in all_is])
    sp_oos = _spearman([t["corr"] for t in all_oos], [t["pnl63"] / STAKE * 100.0 for t in all_oos])
    floor_prose, floor_tone = _floor_text(is_for_floor, oos_for_floor)
    menu_prose, menu_tone = _book_menu_sentence(books)

    book_headers = [
        ("Book", "text"), ("When bought", "text"), ("Finished trades", "num"), ("Win %", "num"),
        ("Average result", "num"), ("Median days held", "num"), ("Profit factor", "num"),
        ("Worst account drop", "num"), ("Still open", "num"), ("Average correlation at entry", "num"),
    ]
    book_rows = []
    for key in ("top10_open", "top10_cap", "top100_open", "top100_cap"):
        book = books[key]
        for period, start, end in periods:
            st = _book_stats(book["trades"], book["equity"], start, end)
            pf = "no losing trades" if st["n"] and st["wins"] == st["n"] else _fmt_num(st["pf"])
            book_rows.append([
                _esc(book["label"]), _esc(period), str(st["n"]),
                _fmt_pct(st["win"]).replace("+", ""), _fmt_pct(st["avg"]),
                _fmt_num(st["median_days"], 0), pf,
                _fmt_pct(st["max_dd"]), str(st["open"]),
                _fmt_num(st["avg_corr"]),
            ])

    # Blotters for the two capped books, the versions a system could actually run.
    blotter_headers = [
        ("#", "num"), ("Pair", "text"), ("Correlation", "num"), ("Bought", "text"),
        ("Shares", "num"), ("Buy price", "num"), ("Shorted", "text"), ("Shares", "num"),
        ("Short price", "num"), ("Opened", "text"), ("Closed", "text"),
        ("Long exit", "num"), ("Cover", "num"), ("Days", "num"), ("Net", "num"),
        ("On the $10k stake", "num"), ("Why", "text"),
    ]
    blotters = []
    for key in ("top10_cap", "top100_cap"):
        book = books[key]
        rows = []
        for n, t in enumerate(book["trades"], start=1):
            closed = t["status"] == "closed"
            rows.append([
                str(n), _esc(t["pair"]), _fmt_num(t["corr"]), _esc(t["long"]),
                str(t["shares_long"]), f"{t['entry_long']:.2f}", _esc(t["short"]),
                str(t["shares_short"]), f"{t['entry_short']:.2f}",
                pd.Timestamp(t["entry_date"]).date().isoformat(),
                pd.Timestamp(t["exit_date"]).date().isoformat() if closed else "Still open",
                f"{t['exit_long']:.2f}", f"{t['exit_short']:.2f}",
                str(t["days"]), format_money(t["net"]),
                _fmt_pct(t["net"] / STAKE * 100.0), _esc(t["reason"]),
            ])
        blotters.append((book["label"], _table(
            blotter_headers, rows,
            "One row is one round trip. Net is the long plus the short. ",
        )))

    top10_now = "".join(
        f"<li>{_esc(r['pair'])} — correlation {_fmt_num(r['corr'])}</li>" for r in meta["latest_top10"]
    )
    sp_sentence = (
        f"Across every band, the rank-link between a pair’s correlation and its three-month result "
        f"was {_fmt_num(sp_is)} before 2024 ({len(all_is)} trades) and {_fmt_num(sp_oos)} from 2024 on "
        f"({len(all_oos)} trades). A figure near zero means tighter correlation did not line up with a better trade. "
        "A figure near one would mean it did."
    )

    # Open-ended books: did they get stuck?
    stuck = []
    for key in ("top10_open", "top100_open"):
        for t in books[key]["trades"]:
            if t["status"] == "open" or t["days"] >= 400:
                stuck.append(f"{books[key]['label']}: {t['pair']} bought {pd.Timestamp(t['entry_date']).date().isoformat()}, {t['reason'].lower()}.")
    stuck_text = " ".join(stuck) if stuck else "The hold-until-lined-up books did not leave a multi-year position sitting open in this sample."

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Correlation versus gap-fade outcome</title>
  <style>{STYLE.CSS}
  .wrap {{ max-width: 1180px; }}
  </style>
</head>
<body>
<div class="wrap">
  <header class="doc-head">
    <p class="eyebrow">Research · not a live system</p>
    <h1>Does a tighter correlation make the gap trade work?</h1>
    <p class="lede">Walk-forward from {meta['first']} through {meta['last']}. Each ranking uses only the prior {LOOKBACK} trading days. {meta['symbols']} stocks. {meta['refreshes']} ranking dates.</p>
  </header>

  <div class="callout">
    <strong>What you asked.</strong>
    <p>{_esc(ORIGINAL_REQUEST)}</p>
    <strong>In plain English.</strong>
    <p>Once two stocks have about two years of daily history, we ask how often they rose and fell on the same days. We keep the ten tightest pairs, and also the hundred tightest. We also slice pairs into correlation bands, including loose ones, so we can see whether tighter really pays. The trade is the same idea as before: buy the cheap stock, short the expensive one, about $10,000 of whole shares on each side. The bands answer “is there a minimum correlation?” The two lists answer “what would we actually run?”</p>
  </div>

  <div class="callout {floor_tone}">
    <strong>Minimum correlation.</strong>
    <p>{_esc(floor_prose)}</p>
    <p>{_esc(sp_sentence)}</p>
  </div>

  <div class="callout {menu_tone}">
    <strong>If this were a system.</strong>
    <p>{_esc(menu_prose)}</p>
    <p>One pair at a time. The wide-open version waits until the two prices line back up, with no time limit. That is what locked the earlier replay in News Corp for years. The six-month version closes at the lineup or at {HOLD_126} trading days, whichever comes first. The six-month line was set because of that stuck trade. It was not searched across a grid of holding times.</p>
    <p>{_esc(stuck_text)}</p>
  </div>

  <h2>How a day is scored</h2>
  <ul>
    <li>Look back {LOOKBACK} trading days, about two years. Score each pair on daily percent moves (Pearson correlation). Positive one means they moved the same way. The ranking refreshes every {REFRESH} trading days, about a month, and never uses a later day.</li>
    <li>The gap is how far today’s price sits from a straight line fit through those same prior closes (ordinary least squares). A tradable gap is at least {ENTRY_Z:.0f} of that pair’s normal wiggles, and not a wild print bigger than {MAX_ABS_PCT:.0f}%.</li>
    <li>Among the pairs allowed into a list or a band, take the widest percent gap. Short the high stock, buy the low stock, at the next open.</li>
    <li>The three-month and six-month columns below are fixed holds, so every trade is measured the same way. “Lined up” means the frozen entry line was touched again (within {EXIT_Z:.1f} wiggles) inside about six months.</li>
    <li>The band test can hold several pairs at once. Those averages are not the profit of one account. The system books below hold one pair at a time. That is the version you could run.</li>
    <li>Buys before 1 Jan 2024 are the years used to ask if a minimum exists. 2024 onward is only a check. The warehouse is names we still have prices for, so dead companies are missing. Dividends and borrow cost are not in the dollars. Not wired to DailyRun.</li>
  </ul>
  <p>Across the ranking dates, the 10th pair’s correlation sat around {_fmt_num(meta['median_top10'])} and the 100th around {_fmt_num(meta['median_top100'])}. So “top 100” is already a tight club. The loose bands below exist so a minimum, if there is one, is not hidden inside that club.</p>

  <h2>Latest top 10, as of { _esc(meta['latest_date']) }</h2>
  <p>These are the ten tightest pairs on the last ranking date, using only the prior {LOOKBACK} sessions. They illustrate the menu. They were not chosen by eye.</p>
  <ul>{top10_now}</ul>

  <h2>Correlation band versus the trade result</h2>
  <p>Each row is the widest qualifying gap in that band on a ranking date, then held as its own trade. Win % and the averages use the result after three months of sessions (63 trading days). Six months is 126 trading days.</p>
  {_table(bin_headers, bin_rows, "Bands were frozen before the run. ")}

  <h2>One account, one pair at a time</h2>
  <p>Average result is the finished trade’s net divided by the $10,000 stake. Worst account drop is the deepest decline of that stake plus closed and open marks, and it is filled in on the “all years” rows. Profit factor is winning dollars divided by losing dollars.</p>
  {_table(book_headers, book_rows, "Four frozen books. ")}

  <h2>What the six-month books actually bought</h2>
  {''.join(f'<h3>{_esc(title)}</h3>{table}' for title, table in blotters)}

  <footer>
    Written {pd.Timestamp.now().strftime("%Y-%m-%d")} · stamp same_direction_corr_outcome_20260929 · source tools/same_direction_corr_outcome_20260929.py
  </footer>
</div>
{STYLE.SORT_JS}
</body>
</html>
"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(page, encoding="utf-8")
    (OUT_DIR / "BASELINE.md").write_text(
        "\n".join([
            "# Correlation versus gap-fade outcome",
            "",
            "Research only. Not DailyRun.",
            "",
            "## Original request",
            "",
            f"> {ORIGINAL_REQUEST}",
            "",
            "## In plain English",
            "",
            "After two years of history, rank pairs by how often they moved together, trade the widest gap, and see whether tighter correlation made the trade better.",
            "",
            "## Freeze",
            "",
            f"- Lookback {LOOKBACK} sessions, refresh every {REFRESH}, entry |z| >= {ENTRY_Z}, exit |z| <= {EXIT_Z}.",
            f"- Bins: {', '.join(label for _a, _b, label in BINS)}.",
            "- Menus: top 10 and top 100 by trailing return correlation.",
            f"- Study outcome: fixed {HOLD_63}-session result. Floor rule uses entries before {IS_CUT.date()} only: N>={MIN_BIN_N}, win%>=50, average>0, and every tighter bin also passes.",
            f"- System books: one position. Open-ended exit, and a {HOLD_126}-session cap set because a prior replay stayed open for years. Cap was not grid-searched.",
            f"- Stake ${STAKE:.0f} per leg. No dividends, borrow, or commission.",
            f"- Median 10th-pair correlation {meta['median_top10']:.2f}; median 100th-pair correlation {meta['median_top100']:.2f}.",
            "",
            "## Read",
            "",
            floor_prose,
            "",
            menu_prose,
            "",
        ]),
        encoding="utf-8",
    )


def main() -> None:
    global log_r
    dates, symbols, log_c, log_r, opens = load_panel()
    print(f"symbols {len(symbols)} days {len(dates)} {dates[0].date()} {dates[-1].date()}", flush=True)
    study, books, meta = run_study(dates, symbols, log_c, opens)
    print(f"study trades {len(study)} refreshes {meta['refreshes']}", flush=True)
    for key, book in books.items():
        closed = [t for t in book["trades"] if t["status"] == "closed"]
        print(f"{key} closed {len(closed)} open {sum(t['status']=='open' for t in book['trades'])}", flush=True)
    write_report(study, books, meta)
    print(f"wrote {OUT_HTML}", flush=True)


if __name__ == "__main__":
    main()
