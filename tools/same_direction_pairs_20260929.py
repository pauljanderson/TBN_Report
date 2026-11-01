#!/usr/bin/env python3
"""Top persistent same-direction stock pairs, and whether a gap is open now.

Research note only. Does not change any live system.
"""
from __future__ import annotations

import html
import math
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "ohlcv.duckdb"
OUT_DIR = ROOT / "drive" / "paul_experiments" / "same_direction_pairs_20260929"
OUT_HTML = OUT_DIR / "report.html"

# Two equal halves inside this window. A pair has to keep step in both.
WINDOW_START = pd.Timestamp("2022-09-29")
HALF_SPLIT = pd.Timestamp("2024-09-29")
MIN_FULL_DAYS = 500
MIN_HALF_DAYS = 220
# Rank pairs whose lockstep survived both halves.
MIN_HALF_CORR = 0.55
GAP_Z = 2.0
MILD_Z = 1.5
# Fit the usual price link on everything except the last few weeks,
# then see where the latest close sits versus that link.
HOLDOUT_SESSIONS = 21
RECENT_PERSIST_DAYS = 5
# "Right now" is judged against the last year of the pair, not a four-year average
# that can be pulled around by a slow drift.
RECENT_FIT_DAYS = 252
SPLIT_FACTORS = (2, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 25, 30, 40, 50)
BUSINESS = {
    frozenset({"GOOG", "GOOGL"}): "Alphabet, two share classes",
    frozenset({"FOX", "FOXA"}): "Fox, two share classes",
    frozenset({"NWS", "NWSA"}): "News Corp, two share classes",
    frozenset({"CPT", "MAA"}): "Apartment landlords",
    frozenset({"PHM", "TOL"}): "Homebuilders",
    frozenset({"AMAT", "LRCX"}): "Chipmaking equipment",
    frozenset({"DHI", "LEN"}): "Homebuilders",
    frozenset({"MLM", "VMC"}): "Crushed stone and aggregates",
    frozenset({"KLAC", "LRCX"}): "Chipmaking equipment",
    frozenset({"LEN", "PHM"}): "Homebuilders",
}


ORIGINAL_REQUEST = (
    "find the top ten pairs of stocks that seem to move in the same direction "
    "at the same time relative to each other over time. then identify if there "
    "are any gaps currently between any of the pairs. give me a report and a ntfy please"
)


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def split_adjust(close: pd.Series) -> tuple[pd.Series, int]:
    """Scale pre-split prices so a round share split does not look like a crash.

    A day counts only when the raw price ratio is within 2% of a common split
    factor (2-for-1, 10-for-1, and the reverse). Real one-day crashes are rarely
    that exact.
    """
    c = close.to_numpy(dtype=np.float64)
    out = c.copy()
    hits = 0
    for i in range(1, len(c)):
        prev, cur = c[i - 1], c[i]
        if not (np.isfinite(prev) and np.isfinite(cur) and prev > 0 and cur > 0):
            continue
        ratio = cur / prev
        matched = None
        for factor in SPLIT_FACTORS:
            for target in (1.0 / factor, float(factor)):
                if abs(ratio - target) / target <= 0.02:
                    matched = target
                    break
            if matched is not None:
                break
        if matched is None:
            continue
        out[:i] *= matched
        hits += 1
    return pd.Series(out, index=close.index, name=close.name), hits


def ols_fit(x: np.ndarray, y: np.ndarray) -> tuple[float, float, np.ndarray]:
    """y = alpha + beta * x. Returns alpha, beta, residuals."""
    x_mean = float(np.mean(x))
    y_mean = float(np.mean(y))
    var_x = float(np.dot(x - x_mean, x - x_mean))
    if var_x <= 0:
        resid = y - y_mean
        return y_mean, 0.0, resid
    beta = float(np.dot(x - x_mean, y - y_mean) / var_x)
    alpha = y_mean - beta * x_mean
    return alpha, beta, y - (alpha + beta * x)


def same_sign_rate(a: pd.Series, b: pd.Series) -> float:
    both = pd.concat([a, b], axis=1, join="inner").dropna()
    both = both[(both.iloc[:, 0].abs() >= 0.001) | (both.iloc[:, 1].abs() >= 0.001)]
    if len(both) == 0:
        return float("nan")
    sign_a = np.sign(both.iloc[:, 0].to_numpy())
    sign_b = np.sign(both.iloc[:, 1].to_numpy())
    usable = (sign_a != 0) & (sign_b != 0)
    if int(usable.sum()) == 0:
        return float("nan")
    return float(np.mean(sign_a[usable] == sign_b[usable]))


def pair_corr(a: pd.Series, b: pd.Series) -> tuple[float, int]:
    both = pd.concat([a, b], axis=1, join="inner").dropna()
    n = int(len(both))
    if n < 30:
        return float("nan"), n
    return float(both.iloc[:, 0].corr(both.iloc[:, 1])), n


def load_prices() -> pd.DataFrame:
    con = duckdb.connect(str(DB), read_only=True)
    try:
        frame = con.execute(
            """
            SELECT symbol, date, close, volume
            FROM prices
            WHERE close IS NOT NULL AND close > 0
            """
        ).fetchdf()
    finally:
        con.close()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    return frame


def prepare_panels(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp, dict]:
    last_date = pd.Timestamp(raw["date"].max())
    counted: dict[str, int] = {}
    closes: dict[str, pd.Series] = {}
    for symbol, group in raw.groupby("symbol", sort=False):
        series = group.drop_duplicates("date").set_index("date").sort_index()["close"].astype(float)
        adjusted, hits = split_adjust(series)
        counted[symbol] = hits
        closes[symbol] = adjusted

    close_wide = pd.DataFrame(closes).sort_index()
    # Keep names that are still printing and have a long enough recent history.
    recent_ok = close_wide.loc[close_wide.index >= last_date - pd.Timedelta(days=10)].notna().any()
    window = close_wide.loc[close_wide.index >= WINDOW_START]
    enough = window.notna().sum() >= MIN_FULL_DAYS
    keep = recent_ok & enough
    close_wide = close_wide.loc[:, keep]

    log_close = np.log(close_wide.where(close_wide > 0))
    rets = log_close.diff()
    # One leftover corporate-action day should not pretend to be co-movement.
    rets = rets.where(rets.abs() <= math.log(1.40))
    rets_win = rets.loc[rets.index >= WINDOW_START]
    return close_wide, rets_win, last_date, {
        "symbols_in_db": int(raw["symbol"].nunique()),
        "symbols_used": int(close_wide.shape[1]),
        "split_adjustments": int(sum(counted[s] for s in close_wide.columns)),
        "last_date": last_date,
    }


def residualize_on_spy(rets: pd.DataFrame) -> pd.DataFrame | None:
    if "SPY" not in rets.columns:
        return None
    spy = rets["SPY"]
    out = {}
    spy_np = spy.to_numpy(dtype=float)
    for symbol in rets.columns:
        if symbol == "SPY":
            continue
        y = rets[symbol].to_numpy(dtype=float)
        mask = np.isfinite(y) & np.isfinite(spy_np)
        resid = np.full_like(y, np.nan, dtype=float)
        if int(mask.sum()) >= MIN_HALF_DAYS:
            alpha, beta, fitted_resid = ols_fit(spy_np[mask], y[mask])
            resid[mask] = fitted_resid
            _ = (alpha, beta)
        out[symbol] = pd.Series(resid, index=rets.index)
    return pd.DataFrame(out)


def rank_pairs(rets: pd.DataFrame) -> pd.DataFrame:
    early = rets.loc[rets.index < HALF_SPLIT]
    late = rets.loc[rets.index >= HALF_SPLIT]
    full = rets.corr(min_periods=MIN_FULL_DAYS)
    corr_early = early.corr(min_periods=MIN_HALF_DAYS)
    corr_late = late.corr(min_periods=MIN_HALF_DAYS)
    symbols = list(full.columns)
    rows = []
    for i, left in enumerate(symbols):
        for right in symbols[i + 1 :]:
            c_full = full.at[left, right]
            c_early = corr_early.at[left, right]
            c_late = corr_late.at[left, right]
            if not (np.isfinite(c_full) and np.isfinite(c_early) and np.isfinite(c_late)):
                continue
            if c_full < 0.60 or c_early < MIN_HALF_CORR or c_late < MIN_HALF_CORR:
                continue
            rows.append(
                {
                    "left": left,
                    "right": right,
                    "corr_full": float(c_full),
                    "corr_early": float(c_early),
                    "corr_late": float(c_late),
                    "score": float(min(c_early, c_late)),
                }
            )
    ranked = pd.DataFrame(rows)
    if ranked.empty:
        return ranked
    return ranked.sort_values(
        ["score", "corr_full", "left", "right"], ascending=[False, False, True, True]
    ).reset_index(drop=True)


def _link_distance(
    both: pd.DataFrame,
    left: str,
    right: str,
    hist: pd.DataFrame,
) -> tuple[float, float, float, float]:
    """Return z of the latest close, mean z of the last few sessions, percent, beta."""
    alpha, beta, resid_hist = ols_fit(hist[right].to_numpy(), hist[left].to_numpy())
    center = float(np.mean(resid_hist))
    scale = float(np.std(resid_hist, ddof=1))
    if not np.isfinite(scale) or scale <= 1e-8:
        return float("nan"), float("nan"), float("nan"), beta
    latest = both.iloc[-1]
    resid_now = float(latest[left] - (alpha + beta * latest[right]))
    z_now = (resid_now - center) / scale
    tail = both.iloc[-RECENT_PERSIST_DAYS:]
    resid_tail = tail[left].to_numpy() - (alpha + beta * tail[right].to_numpy())
    z_tail = float(np.mean((resid_tail - center) / scale))
    pct = 100.0 * (math.exp(resid_now - center) - 1.0)
    return z_now, z_tail, pct, beta


def gap_for_pair(
    left: str,
    right: str,
    log_close: pd.DataFrame,
) -> dict:
    both = log_close[[left, right]].dropna()
    both = both.loc[both.index >= WINDOW_START]
    if len(both) < MIN_FULL_DAYS + HOLDOUT_SESSIONS:
        return {"gap": "unknown"}
    hist = both.iloc[:-HOLDOUT_SESSIONS]
    z_long, _tail_long, pct_long, _beta_long = _link_distance(both, left, right, hist)
    recent_hist = hist.iloc[-RECENT_FIT_DAYS:]
    z_now, z_recent_mean, pct, beta = _link_distance(both, left, right, recent_hist)
    if not np.isfinite(z_now):
        return {"gap": "unknown"}
    if z_now >= 0:
        rich, cheap = left, right
    else:
        rich, cheap = right, left
    abs_z = abs(z_now)
    if abs_z >= GAP_Z and abs(z_recent_mean) >= MILD_Z:
        status = "open"
    elif abs_z >= MILD_Z:
        status = "mild"
    else:
        status = "closed"
    return {
        "gap": status,
        "beta": beta,
        "z_now": z_now,
        "z_recent_mean": z_recent_mean,
        "pct": pct,
        "z_long": z_long,
        "pct_long": pct_long,
        "rich": rich,
        "cheap": cheap,
        "n_fit": int(len(recent_hist)),
        "last_pair_date": both.index[-1],
    }


def fmt_num(value: float, digits: int = 2) -> str:
    if value is None or not np.isfinite(value):
        return "—"
    return f"{value:.{digits}f}"


def fmt_pct(value: float) -> str:
    if value is None or not np.isfinite(value):
        return "—"
    return f"{value:+.1f}%"


def build_rows(
    ranked: pd.DataFrame,
    rets: pd.DataFrame,
    resid_rets: pd.DataFrame | None,
    close_wide: pd.DataFrame,
) -> pd.DataFrame:
    log_close = np.log(close_wide.where(close_wide > 0))
    top = ranked.head(10).copy()
    records = []
    for rank, row in enumerate(top.itertuples(index=False), start=1):
        left, right = row.left, row.right
        sign_rate = same_sign_rate(rets[left], rets[right])
        _c, n_days = pair_corr(rets[left], rets[right])
        if resid_rets is not None and left in resid_rets and right in resid_rets:
            resid_corr, _n = pair_corr(resid_rets[left], resid_rets[right])
        else:
            resid_corr = float("nan")
        gap = gap_for_pair(left, right, log_close)
        records.append(
            {
                "rank": rank,
                "pair": f"{left} / {right}",
                "left": left,
                "right": right,
                "n_days": n_days,
                "corr_full": row.corr_full,
                "corr_early": row.corr_early,
                "corr_late": row.corr_late,
                "sign_rate": sign_rate,
                "resid_corr": resid_corr,
                "business": BUSINESS.get(frozenset({left, right}), ""),
                **gap,
            }
        )
    return pd.DataFrame(records)


def th(label: str, sort: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{_esc(label)}<span class="sort-ind"></span></th>'
    )


CSS = """
  :root {
    --bg: #f7f6f2; --ink: #1c1b19; --muted: #5a574f; --line: #d4d0c4;
    --card: #ffffff; --accent: #2a4a5c; --accent-soft: #e8eef2;
    --ok: #2d6a4f; --ok-bg: #e8f2ec; --warn: #8a5a12; --warn-bg: #f7efe0;
    --fill: #f0eee6; --bad: #9b2226; --bad-bg: #fdecea;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: "Segoe UI", "Helvetica Neue", Georgia, serif;
    font-size: 15px; line-height: 1.55; color: var(--ink);
    background:
      radial-gradient(ellipse 80% 50% at 10% -10%, #e4ebe8 0%, transparent 55%),
      radial-gradient(ellipse 60% 40% at 100% 0%, #ebe6dc 0%, transparent 50%),
      var(--bg);
  }
  .wrap { max-width: 1180px; margin: 0 auto; padding: 36px 24px 64px; }
  header.doc-head { border-bottom: 2px solid var(--ink); padding-bottom: 14px; margin-bottom: 22px; }
  .eyebrow {
    font-size: 0.72rem; letter-spacing: 0.14em; text-transform: uppercase;
    color: var(--accent); font-weight: 650; margin: 0 0 6px;
  }
  h1 { font-size: 1.7rem; margin: 0 0 6px; letter-spacing: -0.02em; line-height: 1.2; }
  h2 { font-size: 1.12rem; margin: 26px 0 10px; padding-bottom: 5px; border-bottom: 1px solid var(--line); }
  .lede { margin: 0; color: var(--muted); max-width: 78ch; }
  .meta-row { display: flex; flex-wrap: wrap; gap: 8px 16px; margin-top: 10px; font-size: 0.82rem; color: var(--muted); }
  p, li { margin: 0 0 10px; }
  ul { padding-left: 1.25rem; margin: 0 0 12px; }
  .callout { background: var(--accent-soft); border-left: 4px solid var(--accent); padding: 12px 14px; margin: 14px 0 18px; }
  .callout.warn { background: var(--warn-bg); border-left-color: var(--warn); }
  .callout.ok { background: var(--ok-bg); border-left-color: var(--ok); }
  .callout.bad { background: var(--bad-bg); border-left-color: var(--bad); }
  .card { background: var(--card); border: 1px solid var(--line); padding: 12px 14px; margin: 0 0 14px; }
  .table-wrap { overflow-x: auto; margin: 8px 0 16px; }
  table.sortable { border-collapse: collapse; width: 100%; font-size: 13px; }
  th, td { border: 1px solid var(--line); padding: 7px 8px; text-align: left; vertical-align: top; }
  thead th { background: var(--fill); }
  th.sortable-th { cursor: pointer; user-select: none; white-space: nowrap; }
  th.sortable-th:hover { background: #e8e4d8; }
  .sort-ind { display: inline-block; width: 0.9em; margin-left: 4px; color: #9a9588; font-size: 10px; }
  th.sort-asc .sort-ind::after { content: "\\25B2"; color: var(--ink); }
  th.sort-desc .sort-ind::after { content: "\\25BC"; color: var(--ink); }
  caption { text-align: left; font-size: 0.82rem; color: var(--muted); margin: 0 0 6px; caption-side: top; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  .gap-open { background: var(--bad-bg); font-weight: 700; }
  .gap-mild { background: var(--warn-bg); font-weight: 650; }
  .gap-closed { background: var(--ok-bg); }
  footer { margin-top: 28px; font-size: 0.8rem; color: var(--muted); border-top: 1px solid var(--line); padding-top: 12px; }
"""

SORT_JS = r"""
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : 0;
    if (type === "text") return s.toUpperCase();
    var n = s.replace(/[$,%+]/g, "").replace(/,/g, "");
    var v = parseFloat(n);
    return Number.isFinite(v) ? v : 0;
  }
  function sortTable(table, col, type, dir) {
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll("tr"));
    var pinned = rows.filter(function (r) { return r.classList.contains("total-row"); });
    var movable = rows.filter(function (r) { return !r.classList.contains("total-row"); });
    movable.sort(function (a, b) {
      var av = parseSortValue(a.cells[col] && a.cells[col].textContent, type);
      var bv = parseSortValue(b.cells[col] && b.cells[col].textContent, type);
      if (typeof av === "string" || typeof bv === "string") {
        return dir * String(av).localeCompare(String(bv));
      }
      return dir * (av - bv);
    });
    movable.concat(pinned).forEach(function (r) { tbody.appendChild(r); });
  }
  function bindSortHeader(table, th, col) {
    function onActivate(e) {
      if (e.type === "touchend") e.preventDefault();
      var type = th.dataset.sort || "text";
      var dir = th.dataset.dir === "asc" ? -1 : 1;
      table.querySelectorAll("th.sortable-th").forEach(function (h) {
        h.dataset.dir = "";
        h.classList.remove("sort-asc", "sort-desc");
        h.setAttribute("aria-sort", "none");
      });
      th.dataset.dir = dir === 1 ? "asc" : "desc";
      th.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
      th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
      sortTable(table, col, type, dir);
    }
    th.addEventListener("click", onActivate);
    th.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onActivate(e); }
    });
    th.addEventListener("touchend", onActivate, { passive: false });
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("th.sortable-th").forEach(function (th, col) {
      bindSortHeader(table, th, col);
    });
  });
})();
</script>
"""


def gap_cell(status: str) -> str:
    label = {"open": "Open gap", "mild": "Mild gap", "closed": "In line", "unknown": "—"}.get(status, status)
    cls = {"open": "gap-open", "mild": "gap-mild", "closed": "gap-closed"}.get(status, "")
    return f'<td class="{cls}">{_esc(label)}</td>'


def write_report(summary: dict, pairs: pd.DataFrame, n_candidates: int) -> None:
    last = summary["last_date"].strftime("%Y-%m-%d")
    open_n = int((pairs["gap"] == "open").sum()) if not pairs.empty else 0
    mild_n = int((pairs["gap"] == "mild").sum()) if not pairs.empty else 0

    headers = [
        ("Rank", "num"),
        ("Pair", "text"),
        ("What they are", "text"),
        ("Shared days", "num"),
        ("Lockstep, full window", "num"),
        ("Lockstep, earlier half", "num"),
        ("Lockstep, later half", "num"),
        ("Same-direction days", "num"),
        ("Lockstep after S&P 500", "num"),
        ("Gap now", "text"),
        ("Distance vs last year (z)", "num"),
        ("First ticker vs last year", "num"),
        ("First ticker vs four years", "num"),
        ("Which side is high", "text"),
    ]
    body_rows = []
    for rec in pairs.itertuples(index=False):
        rich = "—"
        if rec.gap in {"open", "mild"}:
            rich = f"{rec.rich} high, {rec.cheap} low"
        cells = [
            f'<td class="num">{rec.rank}</td>',
            f"<td>{_esc(rec.pair)}</td>",
            f"<td>{_esc(rec.business)}</td>",
            f'<td class="num">{rec.n_days}</td>',
            f'<td class="num">{fmt_num(rec.corr_full, 2)}</td>',
            f'<td class="num">{fmt_num(rec.corr_early, 2)}</td>',
            f'<td class="num">{fmt_num(rec.corr_late, 2)}</td>',
            f'<td class="num">{(100.0 * rec.sign_rate):.1f}%</td>',
            f'<td class="num">{fmt_num(rec.resid_corr, 2)}</td>',
            gap_cell(rec.gap),
            f'<td class="num">{fmt_num(rec.z_now, 2)}</td>',
            f'<td class="num">{fmt_pct(rec.pct)}</td>',
            f'<td class="num">{fmt_pct(rec.pct_long)}</td>',
            f"<td>{_esc(rich)}</td>",
        ]
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    def _side_sentence(rec) -> str:
        pct_abs = abs(float(rec.pct))
        return (
            f"{rec.pair} ({rec.business}): {rec.rich} is the high side and {rec.cheap} is the low side, "
            f"about {pct_abs:.1f}% apart versus their last-year line (z {float(rec.z_now):+.2f})."
        )

    detail_bits = [_side_sentence(rec) for rec in pairs.itertuples(index=False) if rec.gap == "open"]
    mild_bits = [_side_sentence(rec) for rec in pairs.itertuples(index=False) if rec.gap == "mild"]
    drift_bits = []
    for rec in pairs.itertuples(index=False):
        if rec.gap == "open":
            continue
        if abs(float(rec.pct_long)) >= 15 or abs(float(rec.pct)) >= 10:
            drift_bits.append(
                f"{rec.left} versus {rec.right} is still inside the last-year noise "
                f"(z {float(rec.z_now):+.2f}). {rec.left} is {float(rec.pct):+.1f}% versus that last-year line "
                f"and {float(rec.pct_long):+.1f}% versus the four-year line."
            )

    if open_n:
        verb = "is" if open_n == 1 else "are"
        gap_lead = (
            f"{open_n} of these ten {verb} in an open gap: at least two normal wiggles from the last-year line, "
            f"and that distance has held over the last {RECENT_PERSIST_DAYS} sessions. "
            + " ".join(detail_bits)
        )
        if mild_bits:
            gap_lead += " Mild, short of that bar: " + " ".join(mild_bits)
        gap_class = "bad"
    elif mild_n:
        verb = "is" if mild_n == 1 else "are"
        gap_lead = (
            f"None of the ten is a full gap. {mild_n} {verb} a milder distance, "
            "large enough to notice and smaller than the two-wiggle line. "
            + " ".join(mild_bits)
        )
        gap_class = "warn"
    else:
        gap_lead = "None of these ten pairs has a current gap. Each one is still inside the usual noise of its partner."
        gap_class = "ok"
    if drift_bits:
        gap_lead += " Slow drift, not a fresh gap: " + " ".join(drift_bits)

    head = "".join(th(label, sort) for label, sort in headers)
    table = (
        '<div class="table-wrap"><table class="sortable">'
        "<caption>Click column headers to sort. Lockstep is correlation of daily percent moves, "
        "from −1 (opposite) to +1 (identical).</caption>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table></div>"
    )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Same-direction stock pairs — {last}</title>
  <style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <header class="doc-head">
    <p class="eyebrow">Research note · not a live system</p>
    <h1>Ten stock pairs that have moved together, and where they sit today</h1>
    <p class="lede">Daily prices through {last}. Window {WINDOW_START.date().isoformat()} to {last}, split into two halves at {HALF_SPLIT.date().isoformat()}.</p>
  </header>

  <div class="callout">
    <strong>What you asked.</strong>
    <p>{_esc(ORIGINAL_REQUEST)}</p>
    <strong>In plain English.</strong>
    <p>We took every stock with a long daily price history in the warehouse and asked which pairs rise and fall on the same days, not just for a few months but across both halves of the last four years. The top ten are the pairs that kept that lockstep the best. A gap means one stock in a pair is now unusually high or low versus the other, compared with how the two have usually lined up. This page describes that distance. It is not a buy or sell instruction.</p>
  </div>

  <div class="callout {gap_class}">
    <strong>Gaps today.</strong>
    <p>{_esc(gap_lead)}</p>
  </div>

  <h2>The ten pairs</h2>
  <p>Rank is the weaker of the two half-window locksteps, so a pair that only clung together in one era falls down the list. Shared days are sessions where both stocks had a usable move. “Same-direction days” is how often they finished the day on the same side of flat. “Lockstep after S&amp;P 500” removes the market’s daily move (the S&amp;P 500 tracker, SPY) and checks whether the two still move together on their own. Two stocks can rise and fall on the same days while their price ratio slowly drifts; that daily lockstep is what the rank uses.</p>
  <p>A current gap is measured against the last {RECENT_FIT_DAYS} sessions before the final {HOLDOUT_SESSIONS}, so today is not used to draw the line. “First ticker vs last year” is how far the first name in the pair (the one before the slash) sits versus that line, in percent. Distance (z) counts the same miss in the pair’s own normal wiggles: 2 is a large miss, 0 is right on the line. “First ticker vs four years” is the same idea over the whole window. A big four-year number with a small last-year number means the pair drifted apart slowly and has been living at the new spacing, which is a re-rating more than a fresh gap.</p>
  {table}

  <h2>How a gap was called</h2>
  <ul>
    <li><strong>Open gap.</strong> Latest close is at least {GAP_Z:.0f} wiggles from the last-year line, and the average of the last {RECENT_PERSIST_DAYS} sessions is still at least {MILD_Z:.1f} wiggles away. A single odd print does not count.</li>
    <li><strong>Mild gap.</strong> Latest close is at least {MILD_Z:.1f} wiggles away, but it does not clear both bars above.</li>
    <li><strong>In line.</strong> The latest close is inside the usual noise of the pair.</li>
  </ul>
  <p>The line is a straight fit of the two log prices (ordinary least squares). Positive “first ticker vs last year” means the first ticker is expensive versus that line, and the second ticker is the cheaper side. The four-year column uses the same kind of fit on the whole window except those last {HOLDOUT_SESSIONS} sessions.</p>

  <h2>What was held fixed</h2>
  <div class="card">
    <ul>
      <li>Prices: <code>data/ohlcv.duckdb</code>, raw daily closes. Round share splits (within 2% of a 2-for-1, 10-for-1, and similar) were scaled out before the fit. Days with a leftover move bigger than 40% were ignored when measuring lockstep.</li>
      <li>Universe: {summary["symbols_used"]} symbols that still have a price in the last 10 days and at least {MIN_FULL_DAYS} sessions since {WINDOW_START.date().isoformat()}, out of {summary["symbols_in_db"]} symbols in the warehouse. {n_candidates} pairs cleared the minimum lockstep in both halves. Split scalings applied on the kept names: {summary["split_adjustments"]}.</li>
      <li>A pair needed at least {MIN_FULL_DAYS} shared days overall and {MIN_HALF_DAYS} in each half, with lockstep of at least {MIN_HALF_CORR:.2f} in each half and 0.60 overall, before it could be ranked.</li>
      <li>This is a description of co-movement. It is not an in-sample versus out-of-sample system test, and it is not wired to DailyRun.</li>
    </ul>
  </div>

  <footer>
    Written {pd.Timestamp.now().strftime("%Y-%m-%d")} · stamp same_direction_pairs_20260929 · source tools/same_direction_pairs_20260929.py
  </footer>
</div>
{SORT_JS}
</body>
</html>
"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(page, encoding="utf-8")


def write_baseline(summary: dict, pairs: pd.DataFrame, n_candidates: int) -> None:
    lines = [
        "# Same-direction pairs",
        "",
        "Research note. Not a trading system. Not DailyRun.",
        "",
        "## Original request",
        "",
        f"> {ORIGINAL_REQUEST}",
        "",
        "## In plain English",
        "",
        "Pairs that rose and fell on the same days across both halves of the last four years, then a check of whether one name is now unusually far from the other.",
        "",
        "## Freeze",
        "",
        f"- Window: {WINDOW_START.date()} through {summary['last_date'].date()}, half split {HALF_SPLIT.date()}.",
        f"- Rank: minimum of the two half correlations of daily log returns.",
        f"- Floor: full corr >= 0.60, each half >= {MIN_HALF_CORR}, days >= {MIN_FULL_DAYS} / {MIN_HALF_DAYS}.",
        f"- Current gap: OLS log-price link on the last {RECENT_FIT_DAYS} sessions before a {HOLDOUT_SESSIONS}-session holdout. Open if |z| >= {GAP_Z} and |mean z of last {RECENT_PERSIST_DAYS}| >= {MILD_Z}. Four-year percent is the same fit on the full window.",
        f"- Symbols used: {summary['symbols_used']} of {summary['symbols_in_db']}. Candidates above the floor: {n_candidates}.",
        "",
        "## Top ten",
        "",
        "| Rank | Pair | Full | Early | Late | Gap | z |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for rec in pairs.itertuples(index=False):
        lines.append(
            f"| {rec.rank} | {rec.pair} | {rec.corr_full:.2f} | {rec.corr_early:.2f} | {rec.corr_late:.2f} | {rec.gap} | {rec.z_now:.2f} |"
        )
    lines.append("")
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    raw = load_prices()
    close_wide, rets, _last, summary = prepare_panels(raw)
    # SPY may have been filtered out if we dropped it; keep a dedicated column.
    if "SPY" not in rets.columns and "SPY" in raw["symbol"].unique():
        spy = raw[raw["symbol"] == "SPY"].drop_duplicates("date").set_index("date").sort_index()["close"]
        spy_log = np.log(spy.where(spy > 0)).diff()
        rets = rets.copy()
        rets["SPY"] = spy_log.reindex(rets.index)
    ranked = rank_pairs(rets.drop(columns=["SPY"], errors="ignore"))
    resid = residualize_on_spy(rets)
    pairs = build_rows(ranked, rets, resid, close_wide)
    write_report(summary, pairs, n_candidates=int(len(ranked)))
    write_baseline(summary, pairs, n_candidates=int(len(ranked)))
    print(f"symbols {summary['symbols_used']} candidates {len(ranked)} wrote {OUT_HTML}")
    if not pairs.empty:
        cols = ["rank", "pair", "corr_full", "sign_rate", "resid_corr", "gap", "z_now", "pct", "pct_long"]
        print(pairs[cols].to_string(index=False))


if __name__ == "__main__":
    main()
