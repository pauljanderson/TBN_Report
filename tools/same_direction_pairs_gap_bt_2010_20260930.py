#!/usr/bin/env python3
"""Same-direction pairs, 2010 through the latest daily price.

Replays the gap-fill rules from same_direction_pairs_gap_bt_20260929.
The pair menu uses the correlation floor named in same_direction_pairs_20260929
(full-window lockstep at least 0.60, each half at least 0.55) and keeps every
pair that clears it. Session floors are the 20260929 day counts times four,
because this window is about four times as long. That menu is frozen before
any profit and loss is read.

Research only. Not gold. Not DailyRun.
"""
from __future__ import annotations

import html
import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
from compare_format import format_money, parse_number  # noqa: E402

import duckdb

DB = ROOT / "data" / "ohlcv.duckdb"
OUT_DIR = ROOT / "drive" / "paul_experiments" / "same_direction_pairs_gap_bt_2010_20260930"
OUT_HTML = OUT_DIR / "report.html"
PRIOR_HTML = (
    ROOT / "drive" / "paul_experiments" / "same_direction_pairs_gap_bt_20260929" / "report.html"
)
PRIOR_PAIRS_BASELINE = (
    ROOT / "drive" / "paul_experiments" / "same_direction_pairs_20260929" / "BASELINE.md"
)

# Window. The warehouse itself starts on the first session of 2010.
WINDOW_START = pd.Timestamp("2010-01-01")
IS_CUT = pd.Timestamp("2024-01-01")
# A name counts as having 2010 history when it printed at least once in 2010.
HAS_2010_BY = pd.Timestamp("2010-12-31")

# Correlation floor, copied from the 20260929 write-up before this replay's P&L.
FULL_CORR_MIN = 0.60
HALF_CORR_MIN = 0.55
# 20260929 used 500 shared days and 220 in each half on a four-year window.
# This window is about four times as long, so the session floors are 4x.
# Frozen here, not after seeing results.
MIN_FULL_DAYS = 2000
MIN_HALF_DAYS = 880

# Gap-fill rules, copied from the 20260929 replay.
LOOKBACK = 252
ENTRY_Z = 2.0
EXIT_Z = 0.5
STAKE = 10_000.0
HOLDOUT_SESSIONS = 21
RECENT_FIT_DAYS = 252
RECENT_PERSIST_DAYS = 5
MILD_Z = 1.5
GAP_HTML_CAP = 500

ORIGINAL_REQUEST = (
    "can we take this project same_direction_pairs_gap_bt_20260929 and run it "
    "starting back with our data in 2010. look at enough data to identify highly "
    "correlated stocks and identify gaps between them and show me the past 16 years "
    "worth of correlations and gaps, and what would have happened if we filled gaps "
    "with stocks that were correlated. i would like more data than just the last "
    "couple years and top ten"
)

PRIOR_TOP10 = [
    ("GOOG", "GOOGL"),
    ("FOX", "FOXA"),
    ("NWS", "NWSA"),
    ("CPT", "MAA"),
    ("PHM", "TOL"),
    ("AMAT", "LRCX"),
    ("DHI", "LEN"),
    ("MLM", "VMC"),
    ("KLAC", "LRCX"),
    ("LEN", "PHM"),
]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PAIRS_MOD = _load("same_direction_pairs_20260929", ROOT / "tools" / "same_direction_pairs_20260929.py")
BT_MOD = _load(
    "same_direction_pairs_gap_bt_20260929",
    ROOT / "tools" / "same_direction_pairs_gap_bt_20260929.py",
)


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def rolling_link_vec(y: np.ndarray, x: np.ndarray) -> dict[str, np.ndarray]:
    """Prior-252 ordinary least squares line, excluding the signal day. Vectorized."""
    y = np.asarray(y, dtype=np.float64)
    x = np.asarray(x, dtype=np.float64)
    n = len(y)
    z = np.full(n, np.nan)
    pct = np.full(n, np.nan)
    alpha = np.full(n, np.nan)
    beta = np.full(n, np.nan)
    center = np.full(n, np.nan)
    scale = np.full(n, np.nan)
    if n <= LOOKBACK:
        return {"z": z, "pct": pct, "alpha": alpha, "beta": beta, "center": center, "scale": scale}
    if not (np.isfinite(y).all() and np.isfinite(x).all()):
        raise ValueError("rolling link expects finite log prices")
    cx = np.cumsum(x)
    cy = np.cumsum(y)
    cxx = np.cumsum(x * x)
    cxy = np.cumsum(x * y)
    cyy = np.cumsum(y * y)
    idx = np.arange(LOOKBACK, n)
    end = idx - 1
    start = idx - LOOKBACK

    def wsum(c: np.ndarray) -> np.ndarray:
        prev = np.zeros(len(idx), dtype=np.float64)
        has = start > 0
        prev[has] = c[start[has] - 1]
        return c[end] - prev

    sx = wsum(cx)
    sy = wsum(cy)
    sxx = wsum(cxx)
    sxy = wsum(cxy)
    syy = wsum(cyy)
    nobs = float(LOOKBACK)
    var_x = nobs * sxx - sx * sx
    beta_v = np.zeros(len(idx), dtype=np.float64)
    good = var_x > 1e-18
    beta_v[good] = (nobs * sxy[good] - sx[good] * sy[good]) / var_x[good]
    alpha_v = (sy - beta_v * sx) / nobs
    sse = (
        syy
        - 2.0 * alpha_v * sy
        - 2.0 * beta_v * sxy
        + nobs * alpha_v * alpha_v
        + 2.0 * alpha_v * beta_v * sx
        + beta_v * beta_v * sxx
    )
    sse = np.maximum(sse, 0.0)
    sd = np.sqrt(sse / (nobs - 1.0))
    ok = np.isfinite(sd) & (sd > 1e-12)
    resid_i = y[idx] - (alpha_v + beta_v * x[idx])
    with np.errstate(over="ignore"):
        pct_v = 100.0 * (np.exp(resid_i) - 1.0)
    z[idx[ok]] = resid_i[ok] / sd[ok]
    pct[idx[ok]] = pct_v[ok]
    alpha[idx[ok]] = alpha_v[ok]
    beta[idx[ok]] = beta_v[ok]
    center[idx[ok]] = 0.0
    scale[idx[ok]] = sd[ok]
    return {"z": z, "pct": pct, "alpha": alpha, "beta": beta, "center": center, "scale": scale}


def _self_check_rolling() -> None:
    rng = np.random.default_rng(0)
    x = np.cumsum(rng.normal(0.0, 0.01, 900)) + 4.0
    y = 0.3 + 0.85 * x + rng.normal(0.0, 0.008, 900)
    ref = BT_MOD.rolling_link(y, x)
    mine = rolling_link_vec(y, x)
    for key in ("z", "pct", "alpha", "beta"):
        diff = np.nanmax(np.abs(ref[key] - mine[key]))
        if not np.isfinite(diff) or diff > 1e-6:
            raise SystemExit(f"Rolling line check failed on {key}: max abs diff {diff}")
    scale_diff = np.nanmax(np.abs(ref["scale"] - mine["scale"]))
    if not np.isfinite(scale_diff) or scale_diff > 1e-6:
        raise SystemExit(f"Rolling line check failed on scale: max abs diff {scale_diff}")
    print(f"rolling line check ok (max |dz| {np.nanmax(np.abs(ref['z'] - mine['z'])):.2e})", flush=True)


def _fmt_pct(value: float, digits: int = 1) -> str:
    if value is None or not np.isfinite(value):
        return "—"
    return f"{value:+.{digits}f}%"


def _fmt_px(value: float) -> str:
    if value is None or not np.isfinite(value):
        return "—"
    return f"{value:,.2f}"


def _fmt_z(value: float) -> str:
    if value is None or not np.isfinite(value):
        return "—"
    return f"{value:+.2f}"


def _fmt_corr(value: float) -> str:
    if value is None or not np.isfinite(value):
        return "—"
    return f"{value:.2f}"


def _th(label: str, sort: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{_esc(label)}<span class="sort-ind"></span></th>'
    )


def _num(text: str) -> str:
    return f'<td class="num">{_esc(text)}</td>'


def _txt(text: str) -> str:
    return f"<td>{_esc(text)}</td>"


def load_raw() -> pd.DataFrame:
    con = duckdb.connect(str(DB), read_only=True)
    try:
        frame = con.execute(
            """
            SELECT symbol, date, open, close
            FROM prices
            WHERE close IS NOT NULL AND close > 0
              AND date >= DATE '2010-01-01'
            """
        ).fetchdf()
    finally:
        con.close()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    frame = frame.drop_duplicates(["symbol", "date"], keep="first")
    return frame


def adjust_symbol(group: pd.DataFrame) -> tuple[pd.Series, pd.Series, int]:
    series = group.set_index("date").sort_index()
    close = series["close"].astype(float)
    open_ = series["open"].astype(float)
    adj, hits = PAIRS_MOD.split_adjust(close)
    scale = (adj / close).replace([np.inf, -np.inf], np.nan)
    open_adj = open_ * scale
    return adj, open_adj, hits


def build_prices(raw: pd.DataFrame) -> tuple[dict[str, pd.Series], dict[str, pd.Series], dict]:
    closes: dict[str, pd.Series] = {}
    opens: dict[str, pd.Series] = {}
    hits_total = 0
    symbols = raw["symbol"].nunique()
    for i, (symbol, group) in enumerate(raw.groupby("symbol", sort=False), start=1):
        adj, open_adj, hits = adjust_symbol(group)
        closes[str(symbol)] = adj
        opens[str(symbol)] = open_adj
        hits_total += hits
        if i % 200 == 0:
            print(f"adjusted {i} of {symbols}", flush=True)
    close_wide = pd.DataFrame(closes).sort_index()
    close_wide = close_wide.loc[close_wide.index >= WINDOW_START]
    last_date = pd.Timestamp(close_wide.index.max())
    first_date = pd.Timestamp(close_wide.index.min())
    recent_ok = close_wide.loc[close_wide.index >= last_date - pd.Timedelta(days=10)].notna().any()
    n_obs = close_wide.notna().sum()
    firsts = close_wide.apply(lambda s: s.first_valid_index())
    has_2010 = firsts.notna() & (firsts <= HAS_2010_BY)
    on_first = close_wide.iloc[0].notna() if len(close_wide) else pd.Series(dtype=bool)
    enough = n_obs >= MIN_FULL_DAYS
    keep = recent_ok & has_2010 & enough
    summary = {
        "symbols_in_db": int(symbols),
        "first_date": first_date,
        "last_date": last_date,
        "sessions": int(len(close_wide)),
        "with_2010_print": int(has_2010.sum()),
        "start_after_2010": int((~has_2010).sum()),
        "on_first_session": int(on_first.sum()) if len(on_first) else 0,
        "universe": int(keep.sum()),
        "universe_on_first_session": int((keep & on_first).sum()) if len(on_first) else 0,
        "recent_and_2010_but_short": int((recent_ok & has_2010 & ~enough).sum()),
        "split_adjustments": int(hits_total),
    }
    kept_cols = list(close_wide.columns[keep])
    close_wide = close_wide.loc[:, kept_cols]
    opens = {s: opens[s] for s in kept_cols}
    print(
        f"universe {summary['universe']} of {summary['symbols_in_db']} "
        f"with a 2010 print, recent, and >= {MIN_FULL_DAYS} sessions. "
        f"span {first_date.date()} to {last_date.date()}",
        flush=True,
    )
    return close_wide, opens, summary


def _half_split(index: pd.DatetimeIndex) -> pd.Timestamp:
    """Calendar midpoint of the study window, snapped to the first session on or after it."""
    last = pd.Timestamp(index.max())
    mid = WINDOW_START + (last - WINDOW_START) / 2
    after = index[index >= mid]
    if len(after) == 0:
        raise RuntimeError("No sessions on or after the calendar midpoint")
    return pd.Timestamp(after[0])


def rank_pairs(rets: pd.DataFrame, half: pd.Timestamp) -> tuple[pd.DataFrame, pd.Timestamp]:
    print(f"correlating {rets.shape[1]} symbols, half split {half.date()}", flush=True)
    work = rets.drop(columns=["SPY"], errors="ignore")
    early = work.loc[work.index < half]
    late = work.loc[work.index >= half]
    full = work.corr(min_periods=MIN_FULL_DAYS)
    corr_early = early.corr(min_periods=MIN_HALF_DAYS)
    corr_late = late.corr(min_periods=MIN_HALF_DAYS)
    symbols = list(full.columns)
    fv = full.to_numpy()
    ev = corr_early.reindex(index=symbols, columns=symbols).to_numpy()
    lv = corr_late.reindex(index=symbols, columns=symbols).to_numpy()
    ok = np.isfinite(work.to_numpy())
    n_full = ok.astype(np.int32).T @ ok.astype(np.int32)
    ok_e = np.isfinite(early.reindex(columns=symbols).to_numpy())
    ok_l = np.isfinite(late.reindex(columns=symbols).to_numpy())
    n_early = ok_e.astype(np.int32).T @ ok_e.astype(np.int32)
    n_late = ok_l.astype(np.int32).T @ ok_l.astype(np.int32)
    ii, jj = np.triu_indices(len(symbols), k=1)
    mask = (
        np.isfinite(fv[ii, jj])
        & np.isfinite(ev[ii, jj])
        & np.isfinite(lv[ii, jj])
        & (fv[ii, jj] >= FULL_CORR_MIN)
        & (ev[ii, jj] >= HALF_CORR_MIN)
        & (lv[ii, jj] >= HALF_CORR_MIN)
        & (n_full[ii, jj] >= MIN_FULL_DAYS)
        & (n_early[ii, jj] >= MIN_HALF_DAYS)
        & (n_late[ii, jj] >= MIN_HALF_DAYS)
    )
    rows = pd.DataFrame(
        {
            "left": [symbols[i] for i in ii[mask]],
            "right": [symbols[j] for j in jj[mask]],
            "corr_full": fv[ii[mask], jj[mask]],
            "corr_early": ev[ii[mask], jj[mask]],
            "corr_late": lv[ii[mask], jj[mask]],
            "n_full": n_full[ii[mask], jj[mask]].astype(int),
            "n_early": n_early[ii[mask], jj[mask]].astype(int),
            "n_late": n_late[ii[mask], jj[mask]].astype(int),
        }
    )
    if rows.empty:
        return rows, half
    rows["score"] = rows[["corr_early", "corr_late"]].min(axis=1)
    rows = rows.sort_values(
        ["score", "corr_full", "left", "right"], ascending=[False, False, True, True]
    ).reset_index(drop=True)
    rows.insert(0, "rank", np.arange(1, len(rows) + 1))
    print(f"pairs at or above the floor: {len(rows)}", flush=True)
    return rows, half


def _pairwise_corr(a: np.ndarray, b: np.ndarray, min_n: int) -> tuple[np.ndarray, np.ndarray]:
    mask = np.isfinite(a) & np.isfinite(b)
    a0 = np.where(mask, a, 0.0)
    b0 = np.where(mask, b, 0.0)
    n = mask.sum(axis=0).astype(np.float64)
    sa = a0.sum(axis=0)
    sb = b0.sum(axis=0)
    saa = np.square(a0).sum(axis=0)
    sbb = np.square(b0).sum(axis=0)
    sab = (a0 * b0).sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        cov = sab - sa * sb / n
        va = saa - sa * sa / n
        vb = sbb - sb * sb / n
        corr = cov / np.sqrt(va * vb)
    bad = (n < min_n) | (va <= 0) | (vb <= 0) | ~np.isfinite(corr)
    corr = corr.astype(np.float64)
    corr[bad] = np.nan
    return corr, n


def year_columns(rets: pd.DataFrame, pairs: pd.DataFrame) -> tuple[pd.DataFrame, list[int]]:
    if pairs.empty:
        return pairs, []
    years = sorted(int(y) for y in pd.Index(rets.index.year).unique())
    left = rets[pairs["left"].tolist()].to_numpy()
    right = rets[pairs["right"].tolist()].to_numpy()
    year_arr = rets.index.year.to_numpy()
    for year in years:
        mask = year_arr == year
        corr, _n = _pairwise_corr(left[mask], right[mask], 30)
        pairs[f"y{year}"] = corr
    return pairs, years


def decorate_pairs(pairs: pd.DataFrame, rets: pd.DataFrame, close_wide: pd.DataFrame) -> pd.DataFrame:
    if pairs.empty:
        return pairs
    spy = rets["SPY"].to_numpy(dtype=float) if "SPY" in rets.columns else None
    left_mat = rets[pairs["left"].tolist()].to_numpy()
    right_mat = rets[pairs["right"].tolist()].to_numpy()
    sign = np.full(len(pairs), np.nan)
    for i in range(len(pairs)):
        a = pd.Series(left_mat[:, i], index=rets.index)
        b = pd.Series(right_mat[:, i], index=rets.index)
        sign[i] = PAIRS_MOD.same_sign_rate(a, b)
    pairs["sign_rate"] = sign
    if spy is not None:
        resid_l = np.full_like(left_mat, np.nan)
        resid_r = np.full_like(right_mat, np.nan)
        for i in range(len(pairs)):
            for src, dest in ((left_mat[:, i], resid_l[:, i]), (right_mat[:, i], resid_r[:, i])):
                mask = np.isfinite(src) & np.isfinite(spy)
                if int(mask.sum()) < MIN_HALF_DAYS:
                    continue
                _a, _b, fitted = PAIRS_MOD.ols_fit(spy[mask], src[mask])
                dest[mask] = fitted
        resid_corr, _n = _pairwise_corr(resid_l, resid_r, 30)
        pairs["resid_corr"] = resid_corr
    else:
        pairs["resid_corr"] = np.nan
    top10 = {frozenset(p) for p in PRIOR_TOP10}
    pairs["in_prior_top10"] = [
        "Yes" if frozenset((r.left, r.right)) in top10 else "No" for r in pairs.itertuples(index=False)
    ]
    pairs["business"] = [
        PAIRS_MOD.BUSINESS.get(frozenset({r.left, r.right}), "") for r in pairs.itertuples(index=False)
    ]
    gaps = []
    log_close = np.log(close_wide.where(close_wide > 0))
    for rec in pairs.itertuples(index=False):
        gaps.append(_gap_now(str(rec.left), str(rec.right), log_close))
    gap_df = pd.DataFrame(gaps)
    pairs = pd.concat([pairs.reset_index(drop=True), gap_df], axis=1)
    return year_columns(rets, pairs)[0]


def _link_now(hist_x, hist_y, now_x, now_y, tail_x, tail_y):
    alpha, beta, resid_hist = PAIRS_MOD.ols_fit(np.asarray(hist_x, float), np.asarray(hist_y, float))
    center = float(np.mean(resid_hist))
    scale = float(np.std(resid_hist, ddof=1))
    if not np.isfinite(scale) or scale <= 1e-8:
        return float("nan"), float("nan"), float("nan")
    resid_now = float(now_y - (alpha + beta * now_x))
    z_now = (resid_now - center) / scale
    resid_tail = np.asarray(tail_y, float) - (alpha + beta * np.asarray(tail_x, float))
    z_tail = float(np.mean((resid_tail - center) / scale))
    pct = 100.0 * (math.exp(resid_now - center) - 1.0)
    return z_now, z_tail, pct


def _gap_now(left: str, right: str, log_close: pd.DataFrame) -> dict:
    if left not in log_close.columns or right not in log_close.columns:
        return {"gap": "unknown", "z_now": np.nan, "pct": np.nan, "pct_long": np.nan, "rich": "", "cheap": ""}
    both = log_close[[left, right]].dropna()
    empty = {"gap": "unknown", "z_now": np.nan, "pct": np.nan, "pct_long": np.nan, "rich": "", "cheap": ""}
    if len(both) < RECENT_FIT_DAYS + HOLDOUT_SESSIONS:
        return empty
    hist = both.iloc[:-HOLDOUT_SESSIONS]
    recent = hist.iloc[-RECENT_FIT_DAYS:]
    latest = both.iloc[-1]
    tail = both.iloc[-RECENT_PERSIST_DAYS:]
    z_now, z_tail, pct = _link_now(
        recent[right], recent[left], latest[right], latest[left], tail[right], tail[left]
    )
    _z_long, _t, pct_long = _link_now(
        hist[right], hist[left], latest[right], latest[left], tail[right], tail[left]
    )
    if not np.isfinite(z_now):
        return empty
    if z_now >= 0:
        rich, cheap = left, right
    else:
        rich, cheap = right, left
    abs_z = abs(z_now)
    if abs_z >= ENTRY_Z and abs(z_tail) >= MILD_Z:
        status = "open"
    elif abs_z >= MILD_Z:
        status = "mild"
    else:
        status = "closed"
    return {"gap": status, "z_now": z_now, "pct": pct, "pct_long": pct_long, "rich": rich, "cheap": cheap}


def build_panels(pairs: pd.DataFrame, close_wide: pd.DataFrame, opens: dict[str, pd.Series]) -> list[dict]:
    panels = []
    for rec in pairs.itertuples(index=False):
        left, right = str(rec.left), str(rec.right)
        frame = pd.DataFrame(
            {
                "open_l": opens[left],
                "close_l": close_wide[left],
                "open_r": opens[right],
                "close_r": close_wide[right],
            }
        ).dropna()
        frame = frame[(frame["open_l"] > 0) & (frame["open_r"] > 0) & (frame["close_l"] > 0) & (frame["close_r"] > 0)]
        if len(frame) <= LOOKBACK:
            continue
        sig = rolling_link_vec(np.log(frame["close_l"].to_numpy()), np.log(frame["close_r"].to_numpy()))
        panel = {
            "left": left,
            "right": right,
            "label": rec.business or "",
            "rank": int(rec.rank),
            "dates": pd.DatetimeIndex(frame.index),
            "open_l": frame["open_l"].to_numpy(dtype=float),
            "open_r": frame["open_r"].to_numpy(dtype=float),
            "close_l": frame["close_l"].to_numpy(dtype=float),
            "close_r": frame["close_r"].to_numpy(dtype=float),
        }
        panel.update(sig)
        panel["loc"] = {pd.Timestamp(d): i for i, d in enumerate(panel["dates"])}
        panels.append(panel)
        if len(panels) % 50 == 0:
            print(f"lines fitted {len(panels)}", flush=True)
    print(f"tradable panels {len(panels)}", flush=True)
    return panels


def _next_session(panel: dict, after: pd.Timestamp) -> pd.Timestamp | None:
    pos = panel["dates"].searchsorted(pd.Timestamp(after), side="right")
    if pos >= len(panel["dates"]):
        return None
    return pd.Timestamp(panel["dates"][pos])


def _at(panel: dict, date: pd.Timestamp) -> int | None:
    return panel["loc"].get(pd.Timestamp(date))


def _frozen_z(panel: dict, date: pd.Timestamp, alpha: float, beta: float, center: float, scale: float) -> float:
    i = _at(panel, date)
    if i is None or scale <= 1e-12:
        return float("nan")
    resid = math.log(panel["close_l"][i]) - (alpha + beta * math.log(panel["close_r"][i]))
    return (resid - center) / scale


def _leg_pnl(shares: int, entry: float, exit_px: float, side: str) -> float:
    if side == "long":
        return shares * (exit_px - entry)
    return shares * (entry - exit_px)


def _side_prices(panel: dict, i: int, which: str, long_sym: str, short_sym: str, left: str) -> tuple[float, float]:
    if which == "close":
        px_l, px_r = float(panel["close_l"][i]), float(panel["close_r"][i])
    else:
        px_l, px_r = float(panel["open_l"][i]), float(panel["open_r"][i])
    long_px = px_l if long_sym == left else px_r
    short_px = px_l if short_sym == left else px_r
    return long_px, short_px


def run_backtest(panels: list[dict]) -> tuple[list[dict], pd.DataFrame, dict, set[tuple]]:
    all_dates = sorted(set().union(*[set(p["dates"]) for p in panels])) if panels else []
    all_dates = [pd.Timestamp(d) for d in all_dates if pd.Timestamp(d) >= WINDOW_START]
    best_on: dict[pd.Timestamp, tuple] = {}
    gap_count_by_date: dict[pd.Timestamp, int] = {}
    for panel in panels:
        z = panel["z"]
        pct = panel["pct"]
        for i, d in enumerate(panel["dates"]):
            d = pd.Timestamp(d)
            if d < WINDOW_START:
                continue
            zi = float(z[i])
            pi = float(pct[i])
            if not (np.isfinite(zi) and np.isfinite(pi)):
                continue
            if abs(zi) < ENTRY_Z:
                continue
            gap_count_by_date[d] = gap_count_by_date.get(d, 0) + 1
            ap = abs(pi)
            cur = best_on.get(d)
            if cur is None or ap > cur[0]:
                best_on[d] = (ap, panel, i, zi, pi)

    position: dict | None = None
    pending_entry: dict | None = None
    pending_exit: dict | None = None
    trades: list[dict] = []
    gap_days = 0
    skipped_busy = 0
    equity_rows: list[dict] = []
    realized = 0.0
    last_unreal = 0.0
    filled_signals: set[tuple] = set()

    def mark(pos: dict, date: pd.Timestamp) -> float | None:
        panel = pos["panel"]
        i = _at(panel, date)
        if i is None:
            return None
        long_px, short_px = _side_prices(panel, i, "close", pos["long"], pos["short"], pos["left"])
        return _leg_pnl(pos["shares_long"], pos["entry_long"], long_px, "long") + _leg_pnl(
            pos["shares_short"], pos["entry_short"], short_px, "short"
        )

    for date in all_dates:
        if pending_exit is not None and position is not None and date >= pending_exit["fill_on"]:
            panel = position["panel"]
            i = _at(panel, date)
            if i is not None:
                long_px, short_px = _side_prices(panel, i, "open", position["long"], position["short"], position["left"])
                long_pnl = _leg_pnl(position["shares_long"], position["entry_long"], long_px, "long")
                short_pnl = _leg_pnl(position["shares_short"], position["entry_short"], short_px, "short")
                realized += long_pnl + short_pnl
                z_exit = _frozen_z(
                    panel, pending_exit["signal_date"],
                    position["alpha"], position["beta"], position["center"], position["scale"],
                )
                trades.append({
                    **{k: v for k, v in position.items() if k != "panel"},
                    "exit_date": date,
                    "exit_signal_date": pending_exit["signal_date"],
                    "exit_long": long_px,
                    "exit_short": short_px,
                    "long_pnl": long_pnl,
                    "short_pnl": short_pnl,
                    "net": long_pnl + short_pnl,
                    "z_exit": z_exit,
                    "status": "closed",
                    "reason": "Back near the entry line",
                })
                position = None
                pending_exit = None

        if pending_entry is not None and position is None and date >= pending_entry["fill_on"]:
            panel = pending_entry["panel"]
            i = _at(panel, date)
            if i is not None:
                long_px, short_px = _side_prices(
                    panel, i, "open", pending_entry["long"], pending_entry["short"], pending_entry["left"]
                )
                shares_long = int(STAKE // long_px) if long_px > 0 else 0
                shares_short = int(STAKE // short_px) if short_px > 0 else 0
                if shares_long > 0 and shares_short > 0:
                    position = {
                        **pending_entry,
                        "entry_date": date,
                        "entry_long": long_px,
                        "entry_short": short_px,
                        "shares_long": shares_long,
                        "shares_short": shares_short,
                        "worst": None,
                        "closest_abs_z": None,
                    }
                    filled_signals.add((pending_entry["left"], pending_entry["right"], pd.Timestamp(pending_entry["signal_date"])))
                pending_entry = None

        if position is not None:
            panel = position["panel"]
            i = _at(panel, date)
            if i is not None and date >= position["entry_date"]:
                mtm = mark(position, date)
                if mtm is not None:
                    position["worst"] = mtm if position["worst"] is None else min(position["worst"], mtm)
                if pending_exit is None and date > position["entry_date"]:
                    z_now = _frozen_z(
                        panel, date, position["alpha"], position["beta"], position["center"], position["scale"]
                    )
                    if np.isfinite(z_now):
                        position["closest_abs_z"] = (
                            abs(z_now)
                            if position["closest_abs_z"] is None
                            else min(position["closest_abs_z"], abs(z_now))
                        )
                    if np.isfinite(z_now) and abs(z_now) <= EXIT_Z:
                        fill_on = _next_session(panel, date)
                        if fill_on is not None:
                            pending_exit = {"signal_date": date, "fill_on": fill_on, "z": z_now}

        if position is None and pending_entry is None and pending_exit is None:
            found = best_on.get(date)
            if found is not None:
                _ap, panel, i, zi, pi = found
                gap_days += 1
                if pi >= 0:
                    short_sym, long_sym = panel["left"], panel["right"]
                else:
                    short_sym, long_sym = panel["right"], panel["left"]
                fill_on = _next_session(panel, date)
                if fill_on is not None:
                    pending_entry = {
                        "panel": panel,
                        "left": panel["left"],
                        "right": panel["right"],
                        "label": panel["label"],
                        "long": long_sym,
                        "short": short_sym,
                        "signal_date": date,
                        "z_entry": zi,
                        "pct_entry": pi,
                        "abs_pct": abs(pi),
                        "alpha": float(panel["alpha"][i]),
                        "beta": float(panel["beta"][i]),
                        "center": float(panel["center"][i]),
                        "scale": float(panel["scale"][i]),
                        "fill_on": fill_on,
                    }
        elif position is not None and date in gap_count_by_date:
            skipped_busy += 1

        unreal = 0.0
        if position is not None:
            marked = mark(position, date)
            if marked is None:
                marked = last_unreal
            else:
                last_unreal = marked
            unreal = marked
        else:
            last_unreal = 0.0
        equity_rows.append({"date": date, "equity": STAKE + realized + unreal, "in_trade": position is not None})

    if position is not None and all_dates:
        panel = position["panel"]
        last = max(d for d in panel["dates"] if pd.Timestamp(d) <= all_dates[-1])
        i = _at(panel, pd.Timestamp(last))
        long_px, short_px = _side_prices(panel, i, "close", position["long"], position["short"], position["left"])
        long_pnl = _leg_pnl(position["shares_long"], position["entry_long"], long_px, "long")
        short_pnl = _leg_pnl(position["shares_short"], position["entry_short"], short_px, "short")
        z_exit = _frozen_z(
            panel, pd.Timestamp(last), position["alpha"], position["beta"], position["center"], position["scale"]
        )
        reason = "Still open at the last price"
        if pending_exit is not None:
            reason = "Lined up on the last signal day; the next open is not in the file yet"
        trades.append({
            **{k: v for k, v in position.items() if k != "panel"},
            "exit_date": pd.NaT,
            "mark_date": pd.Timestamp(last),
            "exit_signal_date": pending_exit["signal_date"] if pending_exit else pd.NaT,
            "exit_long": long_px,
            "exit_short": short_px,
            "long_pnl": long_pnl,
            "short_pnl": short_pnl,
            "net": long_pnl + short_pnl,
            "z_exit": z_exit,
            "status": "open",
            "reason": reason,
        })

    equity = pd.DataFrame(equity_rows)
    meta = {
        "gap_days_taken": gap_days,
        "days_busy_with_a_gap": skipped_busy,
        "days": len(all_dates),
        "gap_sessions": int(sum(gap_count_by_date.values())),
    }
    return trades, equity, meta, filled_signals


def collect_gaps(panels: list[dict], filled_signals: set[tuple]) -> tuple[pd.DataFrame, pd.DataFrame]:
    day_rows = []
    episodes = []
    for panel in panels:
        z = panel["z"]
        pct = panel["pct"]
        dates = panel["dates"]
        mask = np.isfinite(z) & np.isfinite(pct) & (np.abs(z) >= ENTRY_Z)
        run_start = None
        for i, flag in enumerate(mask):
            if flag and run_start is None:
                run_start = i
            last = i == len(mask) - 1
            if run_start is not None and ((not flag) or last):
                end = i if flag and last else i - 1
                sl = slice(run_start, end + 1)
                local = np.abs(pct[sl])
                k = run_start + int(np.nanargmax(local))
                zi = float(z[k])
                pi = float(pct[k])
                if pi >= 0:
                    high, low = panel["left"], panel["right"]
                else:
                    high, low = panel["right"], panel["left"]
                signal_dates = []
                for j in range(run_start, end + 1):
                    d = pd.Timestamp(dates[j])
                    key = (panel["left"], panel["right"], d)
                    taken = key in filled_signals
                    signal_dates.append(taken)
                    day_rows.append({
                        "date": d.date().isoformat(),
                        "left": panel["left"],
                        "right": panel["right"],
                        "z": float(z[j]),
                        "gap_pct": float(pct[j]),
                        "high": panel["left"] if pct[j] >= 0 else panel["right"],
                        "low": panel["right"] if pct[j] >= 0 else panel["left"],
                        "filled": "Yes" if taken else "No",
                    })
                episodes.append({
                    "start": pd.Timestamp(dates[run_start]).date().isoformat(),
                    "widest": pd.Timestamp(dates[k]).date().isoformat(),
                    "end": pd.Timestamp(dates[end]).date().isoformat(),
                    "sessions": int(end - run_start + 1),
                    "left": panel["left"],
                    "right": panel["right"],
                    "high": high,
                    "low": low,
                    "z": zi,
                    "gap_pct": pi,
                    "filled": "Yes" if any(signal_dates) else "No",
                })
                run_start = None
    days = pd.DataFrame(day_rows)
    eps = pd.DataFrame(episodes)
    return days, eps


def _days_held(entry, exit_date) -> int | None:
    if pd.isna(exit_date):
        return None
    return int((pd.Timestamp(exit_date) - pd.Timestamp(entry)).days)


def _metrics(closed: list[dict], years: float) -> dict:
    blank = {
        "n": 0, "wins": 0, "losses": 0, "win_pct": float("nan"), "avg_pct": float("nan"),
        "median_pct": float("nan"), "best": float("nan"), "worst": float("nan"),
        "avg_win": float("nan"), "avg_loss": float("nan"), "pf": float("nan"),
        "total": 0.0, "expectancy": 0.0, "avg_days": float("nan"), "median_days": float("nan"),
        "wo_max": float("nan"), "outlier": float("nan"), "tpy": float("nan"), "streak": 0,
    }
    if not closed:
        return blank
    ordered = sorted(closed, key=lambda t: pd.Timestamp(t["entry_date"]))
    nets = np.array([t["net"] for t in ordered], dtype=float)
    pcts = nets / STAKE * 100.0
    days = np.array([_days_held(t["entry_date"], t["exit_date"]) for t in ordered], dtype=float)
    wins = nets[nets > 0]
    losses = nets[nets <= 0]
    win_pcts = pcts[pcts > 0]
    gross_win = float(wins.sum()) if len(wins) else 0.0
    gross_loss = float(-losses.sum()) if len(losses) else 0.0
    if gross_loss > 0:
        pf = gross_win / gross_loss
    elif gross_win > 0:
        pf = float("inf")
    else:
        pf = float("nan")
    if (pcts > 0).any():
        wo = np.delete(pcts, int(np.argmax(pcts)))
        wo_max = float(np.mean(wo)) if len(wo) else float("nan")
        outlier = float(win_pcts.max() / win_pcts.sum() * 100.0) if len(win_pcts) and win_pcts.sum() > 0 else float("nan")
    else:
        wo_max = float(np.mean(pcts))
        outlier = float("nan")
    streak = best = 0
    for net in nets:
        if net <= 0:
            streak += 1
            best = max(best, streak)
        else:
            streak = 0
    return {
        "n": int(len(ordered)),
        "wins": int((nets > 0).sum()),
        "losses": int((nets <= 0).sum()),
        "win_pct": 100.0 * float((nets > 0).mean()),
        "avg_pct": float(np.mean(pcts)),
        "median_pct": float(np.median(pcts)),
        "best": float(pcts.max()),
        "worst": float(pcts.min()),
        "avg_win": float(np.mean(wins) / STAKE * 100.0) if len(wins) else float("nan"),
        "avg_loss": float(np.mean(losses) / STAKE * 100.0) if len(losses) else float("nan"),
        "pf": float(pf) if np.isfinite(pf) else pf,
        "total": float(nets.sum()),
        "expectancy": float(np.mean(nets)),
        "avg_days": float(np.mean(days)),
        "median_days": float(np.median(days)),
        "wo_max": wo_max,
        "outlier": outlier,
        "tpy": float(len(ordered) / years) if years > 0 else float("nan"),
        "streak": int(best),
    }


def _equity_stats(equity: pd.DataFrame) -> dict:
    empty = {
        "max_dd": float("nan"), "ann": float("nan"), "sharpe": float("nan"),
        "end": STAKE, "calmar": float("nan"), "pct_uw": float("nan"), "max_uw_days": 0,
    }
    if equity.empty:
        return empty
    eq = equity["equity"].to_numpy(dtype=float)
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    max_dd = float(dd.min() * 100.0)
    start_d = pd.Timestamp(equity["date"].iloc[0])
    end_d = pd.Timestamp(equity["date"].iloc[-1])
    years = max((end_d - start_d).days / 365.0, 1 / 365)
    ann = float((eq[-1] / STAKE) ** (1.0 / years) - 1.0) * 100.0 if eq[-1] > 0 else float("nan")
    rets = pd.Series(eq).pct_change().dropna()
    if len(rets) > 5 and float(rets.std(ddof=1)) > 0:
        sharpe = float(rets.mean() / rets.std(ddof=1) * math.sqrt(252))
    else:
        sharpe = float("nan")
    calmar = ann / abs(max_dd) if np.isfinite(ann) and np.isfinite(max_dd) and abs(max_dd) > 1e-9 else float("nan")
    below = eq < peak
    pct_uw = float(below.mean() * 100.0)
    max_uw = run = 0
    for flag in below:
        if flag:
            run += 1
            max_uw = max(max_uw, run)
        else:
            run = 0
    return {
        "max_dd": max_dd, "ann": ann, "sharpe": sharpe, "end": float(eq[-1]),
        "calmar": float(calmar) if np.isfinite(calmar) else float("nan"),
        "pct_uw": pct_uw, "max_uw_days": int(max_uw), "years": years,
    }


def _pf_text(stats: dict) -> str:
    if stats["n"] and stats["wins"] == stats["n"] and stats["n"] > 0 and not np.isfinite(stats["pf"]):
        return "no losing trades"
    if stats["pf"] is None or not np.isfinite(stats["pf"]):
        return "—"
    return f"{stats['pf']:.2f}"


def _scrape_prior() -> dict[str, str]:
    if not PRIOR_HTML.exists():
        return {}
    text = PRIOR_HTML.read_text(encoding="utf-8")
    out = {}
    import re
    for label, value in re.findall(r"<td>(.*?)</td><td>(.*?)</td>", text):
        out[html.unescape(label)] = html.unescape(value)
    return out


def _prior_num(prior: dict[str, str], label: str) -> float:
    return parse_number(prior.get(label, "")) if prior else None


SORT_JS = PAIRS_MOD.SORT_JS.replace(
    'if (type === "text") return s.toUpperCase();',
    'if (type === "text" || type === "date" || type === "month") return s.toUpperCase();',
)


def _table(headers: list[tuple[str, str]], rows: list[str], caption: str) -> str:
    head = "".join(_th(label, sort) for label, sort in headers)
    body = "".join(rows)
    return (
        '<div class="table-wrap"><table class="sortable">'
        f"<caption>{caption}</caption>"
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def _metric_row(name: str, stats: dict) -> str:
    cells = [
        _txt(name),
        _num(str(stats["n"])),
        _num("—" if not stats["n"] else f"{stats['win_pct']:.1f}%"),
        _num(_fmt_pct(stats["avg_pct"])),
        _num(_fmt_pct(stats["median_pct"])),
        _num(_fmt_pct(stats["best"])),
        _num(_fmt_pct(stats["worst"])),
        _num(_pf_text(stats)),
        _num(_fmt_pct(stats["avg_pct"]) if stats["n"] else "—"),
        _num(_fmt_pct(stats["wo_max"])),
        _num("—" if not np.isfinite(stats["avg_days"]) else f"{stats['avg_days']:.0f}"),
        _num("—" if not np.isfinite(stats["median_days"]) else f"{stats['median_days']:.0f}"),
        _num("—" if not np.isfinite(stats["tpy"]) else f"{stats['tpy']:.2f}"),
    ]
    return "<tr>" + "".join(cells) + "</tr>"


def write_outputs(
    summary: dict,
    pairs: pd.DataFrame,
    years: list[int],
    half: pd.Timestamp,
    trades: list[dict],
    equity: pd.DataFrame,
    meta: dict,
    gap_days: pd.DataFrame,
    episodes: pd.DataFrame,
) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pairs.to_csv(OUT_DIR / "pairs_correlation.csv", index=False)
    gap_days.to_csv(OUT_DIR / "gap_days.csv", index=False)
    episodes.to_csv(OUT_DIR / "gap_events.csv", index=False)

    trade_rows = []
    for i, t in enumerate(trades, start=1):
        exit_label = pd.Timestamp(t["exit_date"]).date().isoformat() if t["status"] == "closed" else ""
        trade_rows.append({
            "n": i,
            "status": t["status"],
            "left": t["left"],
            "right": t["right"],
            "signal_date": pd.Timestamp(t["signal_date"]).date().isoformat(),
            "entry_date": pd.Timestamp(t["entry_date"]).date().isoformat(),
            "exit_date": exit_label,
            "long": t["long"],
            "shares_long": t["shares_long"],
            "entry_long": t["entry_long"],
            "exit_long": t["exit_long"],
            "short": t["short"],
            "shares_short": t["shares_short"],
            "entry_short": t["entry_short"],
            "exit_short": t["exit_short"],
            "z_entry": t["z_entry"],
            "pct_entry": t["pct_entry"],
            "z_exit": t["z_exit"],
            "closest_abs_z": t.get("closest_abs_z"),
            "days_held": _days_held(t["entry_date"], t["exit_date"] if t["status"] == "closed" else t.get("mark_date")),
            "long_pnl": t["long_pnl"],
            "short_pnl": t["short_pnl"],
            "net": t["net"],
            "net_pct": t["net"] / STAKE * 100.0,
            "worst": t.get("worst"),
            "reason": t["reason"],
        })
    pd.DataFrame(trade_rows).to_csv(OUT_DIR / "trades.csv", index=False)

    closed = [t for t in trades if t["status"] == "closed"]
    still = [t for t in trades if t["status"] == "open"]
    eq_stats = _equity_stats(equity)
    years_span = float(eq_stats.get("years", 1.0))
    full = _metrics(closed, years_span)
    is_stats = _metrics([t for t in closed if pd.Timestamp(t["entry_date"]) < IS_CUT], years_span)
    oos_stats = _metrics([t for t in closed if pd.Timestamp(t["entry_date"]) >= IS_CUT], years_span)
    # Per-split trades per year uses that slice's calendar length, not the full span.
    if not equity.empty:
        is_years = max((min(pd.Timestamp(equity["date"].iloc[-1]), IS_CUT) - pd.Timestamp(equity["date"].iloc[0])).days / 365.0, 1 / 365)
        oos_years = max((pd.Timestamp(equity["date"].iloc[-1]) - IS_CUT).days / 365.0, 1 / 365)
        is_stats["tpy"] = is_stats["n"] / is_years if is_stats["n"] else float("nan")
        oos_stats["tpy"] = oos_stats["n"] / oos_years if oos_stats["n"] else float("nan")

    last = summary["last_date"].date().isoformat()
    first = summary["first_date"].date().isoformat()
    prior = _scrape_prior()
    prior_n = prior.get("Closed trades", "3")
    prior_avg = prior.get("Closed average result on the $10,000 stake", "+1.8%")
    prior_med = prior.get("Closed median result", "+1.5%")
    prior_wr = prior.get("Closed wins", "3 (100.0%)")
    prior_pf = prior.get("Closed profit factor", "no losing trades")
    prior_is_n = prior.get("Earlier entries (before 2024) trades", "")
    prior_oos_n = prior.get("Later entries (2024 on) trades", "")
    prior_dd = prior.get("Worst peak-to-trough drop of that account", "")

    n_eps = int(len(episodes))
    n_filled_eps = int((episodes["filled"] == "Yes").sum()) if n_eps else 0
    n_gap_days = int(len(gap_days))
    n_filled_days = int((gap_days["filled"] == "Yes").sum()) if n_gap_days else 0

    end_vs = eq_stats["end"] - STAKE
    change = ("+" + format_money(end_vs)) if end_vs >= 0 else format_money(end_vs)
    if full["n"] == 0 and not still:
        lead = "The rule never found a gap wide enough to trade."
        lead_class = "warn"
    else:
        open_note = ""
        if still:
            t = still[-1]
            held = _days_held(t["entry_date"], t["mark_date"])
            open_note = (
                f" Bought {t['long']} and shorted {t['short']} on {pd.Timestamp(t['entry_date']).date().isoformat()}, "
                f"and that position is still open after {held} calendar days. "
                f"Marked to the last price it is {format_money(t['net'])}. "
                f"While it is open, no new pair is taken."
            )
        trade_word = "trade" if full["n"] == 1 else "trades"
        win_word = "win" if full["wins"] == 1 else "wins"
        lead = (
            f"{full['n']} {trade_word} finished, {full['wins']} {win_word} ({full['win_pct']:.1f}% of closed trades), "
            f"average {_fmt_pct(full['avg_pct'])}, median {_fmt_pct(full['median_pct'])}. "
            f"Combined closed result {format_money(full['total'])} on the $10,000 stake per leg. "
            f"With the open mark included, the account sits at {format_money(eq_stats['end'])} "
            f"({change} versus the starting stake)."
            + open_note
        )
        lead_class = "ok" if end_vs > 0 else "bad"

    top10_kept = []
    top10_missing = []
    kept_set = {frozenset((r.left, r.right)) for r in pairs.itertuples(index=False)} if len(pairs) else set()
    for a, b in PRIOR_TOP10:
        label = f"{a} / {b}"
        if frozenset((a, b)) in kept_set:
            top10_kept.append(label)
        else:
            top10_missing.append(label)

    examples = _example_sentences(trades)

    metric_headers = [
        ("Slice", "text"), ("Closed trades", "num"), ("Win rate", "num"), ("Average", "num"),
        ("Median", "num"), ("Best", "num"), ("Worst", "num"), ("Profit factor", "num"),
        ("Expectancy", "num"), ("Average without the biggest win", "num"),
        ("Average days held", "num"), ("Median days held", "num"), ("Trades per year", "num"),
    ]
    metric_caption = (
        "Click column headers to sort. Win rate, average, median, best, and worst are the closed-trade "
        "result on the $10,000 stake. Profit factor is winning dollars divided by losing dollars. "
        "Expectancy is the average percent per closed trade. "
        "In-sample (IS) is an entry before 1 Jan 2024. Out-of-sample (OOS) is an entry on or after that date. "
        "OOS is a report only. A still-open position is not in these rows."
    )
    metric_table = _table(
        metric_headers,
        [
            _metric_row("Full book", full),
            _metric_row("IS, entry before 2024", is_stats),
            _metric_row("OOS, entry from 2024 on", oos_stats),
        ],
        metric_caption,
    )

    account_headers = [("Item", "text"), ("Value", "text")]
    account_rows = [
        ("Starting stake marked on the account path", format_money(STAKE)),
        ("Account at the end, stake plus closed results and the open mark", format_money(eq_stats["end"])),
        ("Worst peak-to-trough drop of that account", _fmt_pct(eq_stats["max_dd"])),
        ("Yearly pace of that account", _fmt_pct(eq_stats["ann"]) if np.isfinite(eq_stats["ann"]) else "not defined, the account finished below zero"),
        ("Calmar (yearly pace divided by the size of that drop)", "—" if not np.isfinite(eq_stats["calmar"]) else f"{eq_stats['calmar']:.2f}"),
        ("Sharpe of daily account changes (descriptive, risk-free rate zero)", "—" if not np.isfinite(eq_stats["sharpe"]) else f"{eq_stats['sharpe']:.2f}"),
        ("Share of days the account was under its peak", _fmt_pct(eq_stats["pct_uw"]).replace("+", "")),
        ("Longest stretch under the peak (sessions)", str(eq_stats["max_uw_days"])),
        ("Expectancy per closed trade", format_money(full["expectancy"]) if full["n"] else "—"),
        ("Longest losing streak", str(full["streak"])),
        ("Days scanned", str(meta["days"])),
        ("Days a new gap was taken", str(meta["gap_days_taken"])),
        ("Days a gap was on the board while a trade was open", str(meta["days_busy_with_a_gap"])),
        ("Still open", str(len(still))),
        ("Gap sessions across all kept pairs", f"{n_gap_days:,}"),
        ("Gap stretches (consecutive sessions beyond the bar)", f"{n_eps:,}"),
        ("Stretches the book actually filled", str(n_filled_eps)),
    ]
    account_body = "".join(f"<tr>{_txt(a)}{_txt(b)}</tr>" for a, b in account_rows)
    account_table = _table(account_headers, [account_body], "Click column headers to sort.")

    compare_headers = [
        ("Metric", "text"), ("2022–2026 top ten", "text"), ("2010–2026 floor", "text"), ("Difference", "text"),
    ]
    compare_pairs = [
        ("Closed trades", prior.get("Closed trades", "—"), str(full["n"])),
        ("Win rate", prior_wr, "—" if not full["n"] else f"{full['win_pct']:.1f}%"),
        ("Average result", prior_avg, _fmt_pct(full["avg_pct"])),
        ("Median result", prior_med, _fmt_pct(full["median_pct"])),
        ("Profit factor", prior_pf, _pf_text(full)),
        ("Average days held", prior.get("Closed average calendar days held", "—"), "—" if not np.isfinite(full["avg_days"]) else f"{full['avg_days']:.0f}"),
        ("IS closed trades (entry before 2024)", prior_is_n or "—", str(is_stats["n"])),
        ("OOS closed trades (entry from 2024 on)", prior_oos_n or "—", str(oos_stats["n"])),
        ("Worst account drop", prior_dd or "—", _fmt_pct(eq_stats["max_dd"])),
    ]
    compare_body = []
    for label, old, new in compare_pairs:
        old_n = parse_number(old) if old else None
        new_n = parse_number(new) if new else None
        if old_n is None or new_n is None:
            delta = "—"
        else:
            delta = f"{new_n - old_n:+.2f}"
        compare_body.append(f"<tr>{_txt(label)}{_txt(old or '—')}{_txt(new)}{_txt(delta)}</tr>")
    compare_table = _table(
        compare_headers,
        compare_body,
        "Click column headers to sort. The difference is this book minus the 29 Sep 2026 top-ten replay. "
        "Dollar totals are left off this comparison. Quality is win rate, average, median, profit factor, and the account drop.",
    )

    corr_headers = [
        ("Rank", "num"), ("First ticker", "text"), ("Second ticker", "text"), ("What they are", "text"),
        ("Shared days", "num"), ("Earlier-half days", "num"), ("Later-half days", "num"),
        ("Lockstep, full window", "num"), ("Lockstep, earlier half", "num"), ("Lockstep, later half", "num"),
        ("Weaker half", "num"), ("Same-direction days", "num"), ("Lockstep after S&P 500", "num"),
        ("Gap today", "text"), ("Distance today (z)", "num"), ("First ticker vs last year", "num"),
        ("First ticker vs 2010–2026 line", "num"), ("High side today", "text"),
        ("In the old top ten", "text"),
    ]
    corr_rows = []
    for rec in pairs.itertuples(index=False):
        rich = "—"
        if rec.gap in {"open", "mild"} and rec.rich:
            rich = f"{rec.rich} high, {rec.cheap} low"
        gap_label = {"open": "Open gap", "mild": "Mild gap", "closed": "In line", "unknown": "—"}.get(rec.gap, rec.gap)
        corr_rows.append(
            "<tr>"
            + _num(str(rec.rank))
            + _txt(rec.left)
            + _txt(rec.right)
            + _txt(rec.business or "—")
            + _num(str(int(rec.n_full)))
            + _num(str(int(rec.n_early)))
            + _num(str(int(rec.n_late)))
            + _num(_fmt_corr(rec.corr_full))
            + _num(_fmt_corr(rec.corr_early))
            + _num(_fmt_corr(rec.corr_late))
            + _num(_fmt_corr(rec.score))
            + _num("—" if not np.isfinite(rec.sign_rate) else f"{100.0 * rec.sign_rate:.1f}%")
            + _num(_fmt_corr(rec.resid_corr))
            + _txt(gap_label)
            + _num(_fmt_z(rec.z_now))
            + _num(_fmt_pct(rec.pct))
            + _num(_fmt_pct(rec.pct_long))
            + _txt(rich)
            + _txt(rec.in_prior_top10)
            + "</tr>"
        )
    corr_table = _table(
        corr_headers,
        corr_rows,
        "Click column headers to sort. Lockstep is the correlation of daily log moves, from −1 (opposite) to +1 (lockstep). "
        "The first ticker is the one earlier in the alphabet. Positive “first ticker vs last year” means that name is the expensive side. "
        "Rank is only a label. Every pair at or above the floor is listed, not a top ten. "
        f"{len(pairs)} pairs.",
    )

    year_headers = [("Pair", "text")] + [(str(y), "num") for y in years]
    year_rows = []
    for rec in pairs.itertuples(index=False):
        cells = [_txt(f"{rec.left} / {rec.right}")]
        for y in years:
            cells.append(_num(_fmt_corr(getattr(rec, f"y{y}"))))
        year_rows.append("<tr>" + "".join(cells) + "</tr>")
    year_table = _table(
        year_headers,
        year_rows,
        "Click column headers to sort. Each number is that calendar year’s lockstep. "
        "A dash means fewer than 30 shared days. These years were not used to choose the pairs. "
        "The choice used the full window and the two halves only.",
    )

    if n_eps <= GAP_HTML_CAP:
        show_eps = episodes
        gap_cap_note = f"All {n_eps} stretches are on this page. Every stretch is also in gap_events.csv, and every session is in gap_days.csv ({n_gap_days:,} sessions, {n_filled_days} of them were the morning the book filled)."
    else:
        filled_eps = episodes[episodes["filled"] == "Yes"]
        rest = episodes[episodes["filled"] != "Yes"].copy()
        rest["_abs"] = rest["gap_pct"].abs()
        rest = rest.sort_values("_abs", ascending=False)
        room = max(GAP_HTML_CAP - len(filled_eps), 0)
        show_eps = pd.concat([filled_eps, rest.head(room)], ignore_index=True)
        gap_cap_note = (
            f"This page shows {len(show_eps)} stretches: every stretch the book filled"
            f"{'' if len(filled_eps) <= GAP_HTML_CAP else ' (the filled list itself is inside the cap)'} "
            f"and the widest others, up to {GAP_HTML_CAP} rows. "
            f"gap_events.csv has all {n_eps:,} stretches. gap_days.csv has every session beyond the bar ({n_gap_days:,} rows)."
        )
    gap_headers = [
        ("Widest day", "date"), ("Started", "date"), ("Ended", "date"), ("Sessions", "num"),
        ("First ticker", "text"), ("Second ticker", "text"), ("High side", "text"), ("Low side", "text"),
        ("Gap at the widest day (z)", "num"), ("Gap at the widest day", "num"), ("Filled", "text"),
    ]
    gap_body = []
    if len(show_eps):
        ordered = show_eps.sort_values(["widest", "left", "right"])
        for rec in ordered.itertuples(index=False):
            gap_body.append(
                "<tr>"
                + _txt(rec.widest)
                + _txt(rec.start)
                + _txt(rec.end)
                + _num(str(int(rec.sessions)))
                + _txt(rec.left)
                + _txt(rec.right)
                + _txt(rec.high)
                + _txt(rec.low)
                + _num(_fmt_z(rec.z))
                + _num(_fmt_pct(rec.gap_pct))
                + _txt(rec.filled)
                + "</tr>"
            )
    gap_table = _table(
        gap_headers,
        gap_body,
        "Click column headers to sort. A stretch is consecutive sessions where the pair was at least 2 wiggles "
        "off the prior 252-session line, the same bar the replay uses. "
        "“Gap at the widest day” is the first ticker versus that line; positive means the first ticker was expensive. "
        "Filled means the book bought the cheap side and shorted the expensive side on one of those sessions. "
        + gap_cap_note,
    )

    trade_headers = [
        ("#", "num"), ("Pair", "text"), ("Signal", "date"), ("Bought on", "date"), ("Closed on", "date"),
        ("Bought", "text"), ("Shares bought", "num"), ("Buy price", "num"), ("Sold long at", "num"),
        ("Shorted", "text"), ("Shares short", "num"), ("Short sale", "num"), ("Covered at", "num"),
        ("Gap at signal (z)", "num"), ("Gap at signal", "num"), ("Gap at exit (z)", "num"),
        ("Days held", "num"), ("Net", "num"), ("Net on $10k stake", "num"), ("Why it ended", "text"),
    ]
    trade_body = []
    net_sum = 0.0
    for i, t in enumerate(trades, start=1):
        exit_label = pd.Timestamp(t["exit_date"]).date().isoformat() if t["status"] == "closed" else "Still open"
        held = _days_held(t["entry_date"], t["exit_date"] if t["status"] == "closed" else t.get("mark_date"))
        if t["status"] == "closed":
            net_sum += t["net"]
        cls = ' class="open-row"' if t["status"] == "open" else ""
        cells = [
            _num(str(i)),
            _txt(f"{t['left']} / {t['right']}"),
            _txt(pd.Timestamp(t["signal_date"]).date().isoformat()),
            _txt(pd.Timestamp(t["entry_date"]).date().isoformat()),
            _txt(exit_label),
            _txt(t["long"]),
            _num(str(t["shares_long"])),
            _num(_fmt_px(t["entry_long"])),
            _num(_fmt_px(t["exit_long"])),
            _txt(t["short"]),
            _num(str(t["shares_short"])),
            _num(_fmt_px(t["entry_short"])),
            _num(_fmt_px(t["exit_short"])),
            _num(_fmt_z(t["z_entry"])),
            _num(_fmt_pct(t["pct_entry"])),
            _num(_fmt_z(t["z_exit"])),
            _num("—" if held is None else str(held)),
            _num(format_money(t["net"])),
            _num(_fmt_pct(t["net"] / STAKE * 100.0)),
            _txt(t["reason"]),
        ]
        trade_body.append(f"<tr{cls}>{''.join(cells)}</tr>")
    trade_body.append(
        '<tr class="total-row">'
        + _txt("")
        + _txt("Closed net")
        + _txt("") * 15
        + _num(format_money(net_sum))
        + _num(_fmt_pct(net_sum / STAKE * 100.0) if full["n"] else "—")
        + _txt("Sum of finished trades. The open mark is not in this sum.")
        + "</tr>"
    )
    trade_table = _table(
        trade_headers,
        trade_body,
        "Click column headers to sort. One row is one round trip. "
        "The open row, if any, is marked to the last close and is not a finished trade. "
        "Positive “gap at signal” means the first ticker was the expensive one. "
        "The total row stays at the bottom.",
    )

    kept_sentence = (
        ", ".join(top10_kept) if top10_kept else "none"
    )
    missing_sentence = ", ".join(top10_missing) if top10_missing else "none"
    plain = (
        "A same-direction pair is two stocks that tend to finish the day up together and down together, "
        "not just for a few months. A gap is a day when one of them is unusually expensive versus the line "
        "the two have kept over the prior year of closes. Filling the gap means buying about $10,000 of the "
        "cheap one and shorting about $10,000 of the expensive one the next morning, then holding both until "
        "the prices come back near the line we used on the day we spotted the gap. "
        "The earlier page only used the last few years and only the ten tightest pairs. "
        "This page uses the daily prices from 2010 through the latest day in the warehouse, and it keeps every "
        "pair that clears the same correlation floor that earlier write-up named, not a top-ten cut."
    )
    universe_note = (
        f"The warehouse runs from {first} through {last} "
        f"({summary['sessions']} sessions, {summary['symbols_in_db']} symbols). "
        f"There is no price on 1 Jan 2010; the first session is {first}. "
        f"{summary['with_2010_print']} symbols printed at least once in 2010. "
        f"{summary['start_after_2010']} start later than 2010 and were left out of the pair menu. "
        f"Of the names with a 2010 print, {summary['universe']} are still printing in the last 10 days "
        f"and have at least {MIN_FULL_DAYS} sessions; that is the pairing universe. "
        f"{summary['universe_on_first_session']} of those {summary['universe']} have a price on {first}. "
        f"The rest of the universe start later in 2010. "
        f"{summary['recent_and_2010_but_short']} recent names have a 2010 print but fewer than {MIN_FULL_DAYS} sessions, so they were left out. "
        f"The old top ten that still clear this long-history floor: {kept_sentence}. "
        f"Not in this menu: {missing_sentence}. "
        "FOX and FOXA first print in this warehouse in March 2019, and NWS and NWSA in June 2013, so they have no 2010 history. "
        "GOOG and GOOGL do have a price on 2010-01-04 in this file; their daily moves in the early years match to many decimals."
    )

    stuck_note = ""
    if still:
        open_trade = still[-1]
        open_on = pd.Timestamp(open_trade["entry_date"]).date().isoformat()
        later = ""
        if pd.Timestamp(open_trade["entry_date"]) < IS_CUT and oos_stats["n"] == 0:
            later = ", including every session from 2024 on"
        stuck_note = (
            " The finished count is smaller because that rule holds one pair until it lines up. "
            f"After {open_on} the book was still short {open_trade['short']} and long {open_trade['long']}, "
            f"so the later gaps{later} were not filled."
        )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Same-direction gaps since 2010 — {last}</title>
  <style>{PAIRS_MOD.CSS}
  tr.open-row td {{ background: var(--warn-bg); }}
  tr.total-row td {{ font-weight: 700; background: var(--fill); }}
  .wrap {{ max-width: 1280px; }}
  </style>
</head>
<body>
<div class="wrap">
  <header class="doc-head">
    <p class="eyebrow">Research replay · not gold · not DailyRun</p>
    <h1>Sixteen years of pairs that move together, and the gaps between them</h1>
    <p class="lede">Daily prices from {first} through {last}. One book, about ${STAKE:,.0f} on each leg, whole shares. Fills at the next open.</p>
  </header>

  <div class="callout">
    <strong>What you asked.</strong>
    <p>{_esc(ORIGINAL_REQUEST)}</p>
    <strong>In plain English.</strong>
    <p>{_esc(plain)}</p>
  </div>

  <div class="callout {lead_class}">
    <strong>What the fills did.</strong>
    <p>{_esc(lead)}</p>
  </div>

  <div class="callout warn">
    <strong>How to read this.</strong>
    <p>The correlation floor was copied from the 29 Sep 2026 write-up before this profit and loss was calculated: daily lockstep of at least {FULL_CORR_MIN:.2f} over the whole window and at least {HALF_CORR_MIN:.2f} in each half. The earlier page used that floor and then printed only the top ten. This page keeps every pair that clears the floor. The required shared days are the old 500 and 220 multiplied by four ({MIN_FULL_DAYS} and {MIN_HALF_DAYS}), because this window is about four times as long. That was frozen before the results. Which names clear the floor still uses the full {first[:4]}–{last[:4]} history, so the menu is in-sample (IS). Entries before 1 Jan 2024 and entries from that date on are both shown. The later block is out-of-sample (OOS) as a report only. Nothing was retuned after seeing it. Dividends and the cost of borrowing shares for the short are not in the dollars. This is not gold and it is not wired to DailyRun.</p>
  </div>

  <h2>The rule that was frozen</h2>
  <ul>
    <li>Same-direction pair: two stocks whose daily log moves rise and fall together. The line between their prices is an ordinary least squares (OLS) fit. The Standard &amp; Poor’s 500 (S&amp;P 500) tracker SPY is used only as a side check. It is not one of the pair legs, and it is not a filter.</li>
    <li>Keep a pair when full-window lockstep is at least {FULL_CORR_MIN:.2f}, each half (split at {half.date().isoformat()}, the calendar midpoint) is at least {HALF_CORR_MIN:.2f}, and the pair has at least {MIN_FULL_DAYS} shared days and {MIN_HALF_DAYS} in each half. The original study did not name a leader and a lagger. It names the high side and the low side when a gap is open.</li>
    <li>A tradable gap: the latest close is at least {ENTRY_Z:.0f} wiggles (a standard score of {ENTRY_Z:.0f}) off the prior {LOOKBACK} sessions, stopping the day before the signal. If several pairs qualify and the book is flat, take the largest percent gap.</li>
    <li>Fill: short the high side, buy the low side, about ${STAKE:,.0f} of whole shares each, at the next open. The line is then frozen. Exit when a later close is within {EXIT_Z:.1f} wiggles of that same line. Sell and cover at the next open. One pair at a time. No time limit and no extra stop.</li>
    <li>One book at a time means most gaps are shown and not filled. The replay does not take a second pair while the first is open. That is the same rule as the short top-ten replay.</li>
  </ul>
  <p>{_esc(universe_note)}</p>
  {examples}

  <h2>Closed-trade results</h2>
  {metric_table}

  <h2>The account path</h2>
  <p>The path starts at the $10,000 stake, adds finished results, and marks an open trade to the close. The yearly pace and the Sharpe ratio describe that path. They are not a forecast.</p>
  {account_table}

  <h2>Same idea, longer history</h2>
    <p>The 29 Sep 2026 replay used ten pairs from 29 Sep 2022 onward. It finished { _esc(prior_n) } trades, average { _esc(prior_avg) }, median { _esc(prior_med) }. This book uses the same entry, the same exit, and the same one-pair-at-a-time stake, on the longer window and on every pair above the floor.{stuck_note}</p>
  {compare_table}

  <h2>Every pair above the floor</h2>
  <p>{len(pairs)} pairs. “Gap today” uses the same current-gap check as the earlier pair note: the last {RECENT_FIT_DAYS} sessions before a {HOLDOUT_SESSIONS}-session pause, open when the latest close is at least {ENTRY_Z:.0f} wiggles away and the last {RECENT_PERSIST_DAYS} sessions still average at least {MILD_Z:.1f}. The replay further down uses the prior-{LOOKBACK}-session line and does not use that pause. “Lockstep after S&amp;P 500” removes SPY’s daily move. Two stocks can still move together because the market moved. A weaker number there means more of the lockstep was the market.</p>
  {corr_table}

  <h2>Lockstep by calendar year</h2>
  {year_table}

  <h2>Gaps</h2>
  <p>{_esc(gap_cap_note)}</p>
  {gap_table}

  <h2>Every fill</h2>
  {trade_table}

  <footer>
    Written {pd.Timestamp.now().strftime("%Y-%m-%d")} · stamp same_direction_pairs_gap_bt_2010_20260930 · source tools/same_direction_pairs_gap_bt_2010_20260930.py
  </footer>
</div>
{SORT_JS}
</body>
</html>
"""
    OUT_HTML.write_text(page, encoding="utf-8")

    lines = [
        "# Same-direction pairs, gap fill, from 2010",
        "",
        "Research only. Not gold. Not DailyRun.",
        "",
        "The pair menu was chosen on the full 2010–latest correlation window, so membership is in-sample.",
        "The correlation floor and the session floors were frozen before this profit and loss was read.",
        "OOS (entry date on or after 2024-01-01) is report-only. Nothing was retuned on it.",
        "",
        "## Original request",
        "",
        f"> {ORIGINAL_REQUEST}",
        "",
        "## In plain English",
        "",
        plain,
        "",
        "## Freeze",
        "",
        f"- Prices: `{DB.relative_to(ROOT).as_posix()}`, first session {first}, last session {last}. No row exists for 2010-01-01.",
        f"- Universe: {summary['universe']} symbols that printed on or before {HAS_2010_BY.date()}, still print in the last 10 days, and have at least {MIN_FULL_DAYS} sessions. {summary['start_after_2010']} symbols start after 2010 and were excluded. {summary['universe_on_first_session']} of the universe have a price on {first}.",
        f"- SPY is the S&P 500 tracker used only for the residual side check. It is not a pair leg.",
        f"- Correlation cutoff (from the 20260929 write-up, before this P&L): full daily log-return correlation >= {FULL_CORR_MIN:.2f}, each half >= {HALF_CORR_MIN:.2f}.",
        f"- Half split: calendar midpoint of {WINDOW_START.date()} and {last}, first session on or after that point: {half.date()}.",
        f"- Session floors: {MIN_FULL_DAYS} shared days and {MIN_HALF_DAYS} in each half (four times the 20260929 floors of 500 and 220). Frozen before results.",
        f"- Pairs kept: {len(pairs)}. Not a top-ten cut.",
        f"- Gap and fill, copied from same_direction_pairs_gap_bt_20260929: |z| >= {ENTRY_Z:.0f} on a {LOOKBACK}-session OLS log-price line that excludes the signal day. Biggest |percent| wins. Short the high side, buy the low side, ${STAKE:.0f} per leg, whole shares, next open. Exit when |z| <= {EXIT_Z:.1f} on the frozen entry line, next open. One position. No time stop. The original study does not define a leader versus a lagger.",
        f"- Current-gap column only: last {RECENT_FIT_DAYS} sessions before a {HOLDOUT_SESSIONS}-session holdout. Open if |z| >= {ENTRY_Z:.0f} and |mean z of last {RECENT_PERSIST_DAYS}| >= {MILD_Z:.1f}.",
        f"- IS / OOS: entry_date < {IS_CUT.date()} / entry_date >= {IS_CUT.date()}. Report only.",
        f"- Costs left out: dividends, borrow, commission.",
        f"- Closed trades: {full['n']}. Win rate: {full['win_pct'] if full['n'] else float('nan'):.2f}%. Average: {full['avg_pct'] if full['n'] else float('nan'):.2f}%. Median: {full['median_pct'] if full['n'] else float('nan'):.2f}%.",
        f"- IS closed: {is_stats['n']}, average {is_stats['avg_pct'] if is_stats['n'] else float('nan'):.2f}%. OOS closed: {oos_stats['n']}, average {oos_stats['avg_pct'] if oos_stats['n'] else float('nan'):.2f}%.",
        "",
        "## Versus the 20260929 top-ten replay",
        "",
        f"- That book: closed trades {prior_n}, win rate {prior_wr}, average {prior_avg}, median {prior_med}, profit factor {prior_pf}.",
        f"- This book: closed trades {full['n']}, win rate {full['win_pct'] if full['n'] else float('nan'):.1f}%, average {full['avg_pct'] if full['n'] else float('nan'):.1f}%, median {full['median_pct'] if full['n'] else float('nan'):.1f}%, profit factor {_pf_text(full)}.",
        "- Same entry, same exit, same one-position stake. Wider history and every pair above the floor instead of ten names.",
        "",
    ]
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT_HTML}", flush=True)


def _example_sentences(trades: list[dict]) -> str:
    closed = [t for t in trades if t["status"] == "closed"]
    if not trades:
        return "<p>No gap was filled.</p>"
    picks: list[dict] = []
    if closed:
        picks.append(min(closed, key=lambda t: t["net"]))
        picks.append(max(closed, key=lambda t: t["net"]))
        ordered = sorted(closed, key=lambda t: pd.Timestamp(t["entry_date"]))
        picks.append(ordered[0])
        picks.append(ordered[len(ordered) // 2])
        picks.append(ordered[-1])
    for t in trades:
        if t["status"] == "open":
            picks.append(t)
    seen = set()
    unique = []
    for t in picks:
        key = (t["left"], t["right"], str(t["signal_date"]))
        if key in seen:
            continue
        seen.add(key)
        unique.append(t)
        if len(unique) == 5:
            break
    if len(unique) < 5:
        for t in trades:
            key = (t["left"], t["right"], str(t["signal_date"]))
            if key in seen:
                continue
            seen.add(key)
            unique.append(t)
            if len(unique) == 5:
                break
    bits = []
    for t in unique:
        direction = f"short {t['short']} (the high side) and bought {t['long']} (the low side)"
        gap = f"the gap was {_fmt_pct(t['pct_entry'])} with z {_fmt_z(t['z_entry'])}"
        if t["status"] == "closed":
            end = (
                f"closed on {pd.Timestamp(t['exit_date']).date().isoformat()} "
                f"for {format_money(t['net'])} ({_fmt_pct(t['net'] / STAKE * 100.0)} on the stake)"
            )
        else:
            closest = t.get("closest_abs_z")
            closest_bit = ""
            if closest is not None and np.isfinite(closest):
                closest_bit = f" The closest that frozen gap later got was {closest:.2f} wiggles, and the rule only exits at {EXIT_Z:.1f}."
            end = f"it is still open, marked {format_money(t['net'])} at the last close.{closest_bit}"
        bits.append(
            f"<li>{_esc(t['left'])} / {_esc(t['right'])} signaled "
            f"{pd.Timestamp(t['signal_date']).date().isoformat()}. {gap}. "
            f"The book went {direction}, filled the next open, and {end}.</li>"
        )
    return "<h2>How the fills resolved</h2><ul>" + "".join(bits) + "</ul>"


def _prepare_returns(close_wide: pd.DataFrame, summary: dict) -> pd.DataFrame:
    log_close = np.log(close_wide.where(close_wide > 0))
    rets = log_close.diff()
    rets = rets.where(rets.abs() <= math.log(1.40))
    if "SPY" not in rets.columns:
        # SPY may have failed the universe filter. Load it as the market side check only.
        print("SPY not in the pairing universe; residual check will be blank if it cannot be aligned", flush=True)
    return rets


def main() -> None:
    _self_check_rolling()
    raw = load_raw()
    print(f"loaded rows {len(raw)}", flush=True)
    close_wide, opens, summary = build_prices(raw)
    del raw
    rets = _prepare_returns(close_wide, summary)
    if "SPY" not in rets.columns:
        spy_raw_note = "SPY missing from filtered universe"
        print(spy_raw_note, flush=True)
    half = _half_split(rets.index)
    pairs, half = rank_pairs(rets, half)
    if "SPY" not in rets.columns:
        pass
    print("decorating pairs", flush=True)
    # Keep SPY returns available for the residual check even if we dropped it from pairing.
    if "SPY" not in rets.columns:
        rets = rets.copy()
    pairs = decorate_pairs(pairs, rets, close_wide)
    _pairs_years = [int(c[1:]) for c in pairs.columns if str(c).startswith("y") and str(c)[1:].isdigit()]
    print("fitting pair lines", flush=True)
    panels = build_panels(pairs, close_wide, opens) if len(pairs) else []
    print("replaying fills", flush=True)
    trades, equity, meta, filled = run_backtest(panels)
    print("collecting gaps", flush=True)
    gap_days, episodes = collect_gaps(panels, filled)
    write_outputs(summary, pairs, _pairs_years, half, trades, equity, meta, gap_days, episodes)
    closed = [t for t in trades if t["status"] == "closed"]
    print(
        f"SUMMARY pairs {len(pairs)} gap_days {len(gap_days)} episodes {len(episodes)} "
        f"trades {len(trades)} closed {len(closed)}",
        flush=True,
    )


if __name__ == "__main__":
    main()
