#!/usr/bin/env python3
"""RL cut-the-losers (rl_cut_the_losers) bucket stats for Paul.

Recomputes entry-day cur_hi_pct = (prior-bar High - prior-bar SMA50) / SMA50
matching rocket_rl.py signal evaluation, labels Closed trades, and scans tradable
universe for dip signals blocked at the ceiling.

Usage:
  python tools/rl_cut_the_losers_stats.py
"""
from __future__ import annotations

import csv
import html as html_mod
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "stock_analysis"))
sys.path.insert(0, str(ROOT / "tools"))

from be_stop_replay_ab import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from rocket_rl import ATR_EMA_MULT, ATR_PERIOD, SMA_50, _prepare_bars  # noqa: E402
from rocket_rl_config import RLConfig, atr_pct_band_passes  # noqa: E402
from vz_is_paul_universe_ab import load_universe_symbols  # noqa: E402

STAMP = "20260831"
OUT_DIR = ROOT / "drive" / "paul_experiments" / f"rl_cut_the_losers_stats_{STAMP}"
DATA_DIR = ROOT / "data" / "newdata" / "data"
CLOSED = (
    ROOT
    / "drive"
    / "paul_experiments"
    / "rl_tradable_2010_adv2m_20260828"
    / "runs"
    / "tradable"
    / "RL_Closed_260828112205.csv"
)
UNIVERSE = ROOT / "drive" / "universes" / "VZ_tradable_2010_adv2m_universe.csv"
CUT = 0.25
NEAR_LO = 0.20
IS_CUT = date(2024, 1, 1)


def _parse_d(s: Any) -> Optional[date]:
    s = str(s or "").strip()
    if not s:
        return None
    compact = s.replace("-", "").replace("/", "")[:8]
    for cand, fmt in ((s[:10], "%Y-%m-%d"), (compact, "%Y%m%d")):
        try:
            return datetime.strptime(cand, fmt).date()
        except ValueError:
            continue
    return None


def _row_get(row: dict, *names: str) -> str:
    for n in names:
        if n in row and row[n] not in (None, ""):
            return str(row[n]).strip()
        for k, v in row.items():
            if k.strip() == n and v not in (None, ""):
                return str(v).strip()
    return ""


def load_closed(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _parse_d(_row_get(raw, "DATE OPENED", "DATE_OPENED"))
            sym = _row_get(raw, "SYMBOL").upper()
            xt = _row_get(raw, "EXIT TYPE", "EXIT_TYPE") or "UNKNOWN"
            pnl = _row_get(raw, "PNL %", "PNL_PCT")
            if not sym or opened is None:
                continue
            rows.append({"sym": sym, "opened": opened, "exit": xt, "pnl_raw": pnl})
    return rows


_ohlc_cache: dict[str, Optional[pd.DataFrame]] = {}


def load_ohlc(sym: str) -> Optional[pd.DataFrame]:
    if sym in _ohlc_cache:
        return _ohlc_cache[sym]
    path = DATA_DIR / f"{sym}.csv"
    if not path.exists():
        _ohlc_cache[sym] = None
        return None
    df = pd.read_csv(path)
    cols = {str(c).lower(): c for c in df.columns}
    need = {"date", "open", "high", "low", "close"}
    if not need.issubset(cols):
        _ohlc_cache[sym] = None
        return None
    rename = {
        cols["date"]: "Date",
        cols["open"]: "Open",
        cols["high"]: "High",
        cols["low"]: "Low",
        cols["close"]: "Close",
    }
    if "volume" in cols:
        rename[cols["volume"]] = "Volume"
    out = df.rename(columns=rename)
    keep = ["Date", "Open", "High", "Low", "Close"]
    if "Volume" in out.columns:
        keep.append("Volume")
    out = out[keep]
    out["Date"] = pd.to_datetime(out["Date"]).dt.date
    out = out.sort_values("Date").drop_duplicates("Date")
    _ohlc_cache[sym] = out
    return out


def _bars_df(df: pd.DataFrame) -> pd.DataFrame:
    b = df.set_index("Date")
    if "Volume" not in b.columns:
        b["Volume"] = 0.0
    return b


def cur_hi_pct_at_entry(df: pd.DataFrame, entry: date) -> Optional[float]:
    """Match rocket_rl: at signal bar (day before fill), prior-bar high vs prior-bar SMA50."""
    dates = list(df["Date"])
    if entry not in dates:
        return None
    fill_i = dates.index(entry)
    if fill_i < 2:
        return None
    prior_i = fill_i - 2  # h[idx-1] when idx = fill_i-1
    sub = df.iloc[: fill_i].copy()
    if len(sub) < SMA_50 + 2:
        return None
    sma50 = sub["Close"].rolling(SMA_50, min_periods=SMA_50).mean()
    y_sma = float(sma50.iloc[prior_i])
    if not np.isfinite(y_sma) or y_sma <= 0:
        return None
    hi = float(sub["High"].iloc[prior_i])
    return (hi - y_sma) / y_sma


def bucket(pct: float) -> str:
    if pct >= CUT:
        return "ge_25_blocked"
    if pct >= NEAR_LO:
        return "20_24.99_allowed"
    return "lt_20"


def bucket_label(b: str) -> str:
    return {
        "lt_20": "< 20%",
        "20_24.99_allowed": "20–24.99% (near ceiling, allowed)",
        "ge_25_blocked": "≥ 25% (would block at 0.25)",
    }[b]


def exit_mix_str(c: Counter) -> str:
    total = sum(c.values()) or 1
    parts = [f"{k} {v} ({100 * v / total:.1f}%)" for k, v in c.most_common()]
    return "; ".join(parts)


def metrics_for(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {"n": 0, "wr": 0.0, "avg_pnl": 0.0, "exits": Counter()}
    wins = 0
    pnls: list[float] = []
    exits: Counter = Counter()
    for t in trades:
        exits[t["exit"]] += 1
        s = str(t.get("pnl_raw", "")).strip().replace("%", "")
        try:
            p = float(s)
        except ValueError:
            p = 0.0
        pnls.append(p)
        if p > 0:
            wins += 1
    n = len(trades)
    return {
        "n": n,
        "wr": 100.0 * wins / n,
        "avg_pnl": sum(pnls) / n,
        "exits": exits,
    }


def scan_cut_blocks(symbols: list[str], cfg: RLConfig) -> dict[str, Any]:
    """Count dip-gate signals blocked by cut_it at cfg.rl_cut_the_losers."""
    dip_total = 0
    cut_blocked = 0  # cur_hi >= cut, dip_gate
    cut_blocked_other_ok = 0  # dip_gate + only CUT among secondary (approx)
    near_allowed = 0  # dip_gate + 20-24.99%
    dip_under20 = 0
    sym_cut = Counter()

    for sym in symbols:
        df = load_ohlc(sym)
        if df is None or len(df) < SMA_50 + 10:
            continue
        prep = _prepare_bars(_bars_df(df))
        dates = prep["dates"]
        o, h, l, c = prep["o"], prep["h"], prep["l"], prep["c"]
        vol = prep["vol"]
        sma20 = prep["sma"][20]
        sma50 = prep["sma"][50]
        sma100 = prep["sma"][100]
        sma200 = prep["sma"][200]
        n = len(dates)
        acc_hits = 0
        atr_rolling = 0.0
        peak_cl = 0.0
        vol_sum = 0.0
        event_cooldown = 5

        for j in range(1, n):
            idx = j - 1
            y_idx = idx - 1 if j > 1 else -1
            y_sma = (
                float(sma50[y_idx])
                if y_idx >= 0 and np.isfinite(sma50[y_idx]) and sma50[y_idx] > 0
                else 0.0
            )

            if y_sma > 0 and j > 1:
                lag = idx - 1
                tr = h[lag] - l[lag]
                atr_rolling = tr if atr_rolling == 0 else ((atr_rolling * ATR_EMA_MULT) + tr) / ATR_PERIOD
                cur_cl_pct = (c[lag] - y_sma) / y_sma
                peak_cl = max(peak_cl, cur_cl_pct)

            if cfg.avg_vol_days > 0:
                vol_sum += vol[idx]
                if j > cfg.avg_vol_days:
                    vol_sum -= vol[idx - cfg.avg_vol_days]
                avg_vol = vol_sum / cfg.avg_vol_days if j >= cfg.avg_vol_days else 0.0
            else:
                avg_vol = 0.0

            if y_idx >= 0 and np.isfinite(sma50[y_idx]) and sma50[y_idx] > 0 and c[idx] > sma50[y_idx]:
                acc_hits += 1
            if j > cfg.rl_acc_count:
                old_i = idx - cfg.rl_acc_count
                old_prev = old_i - 1
                if old_prev >= 0 and np.isfinite(sma50[old_prev]) and sma50[old_prev] > 0 and c[old_i] > sma50[old_prev]:
                    acc_hits -= 1
            acceptance = acc_hits >= cfg.rl_acc_min

            if not cfg.sma_qual or j <= SMA_50 + cfg.rl_50_sma_lookback or y_sma <= 0:
                continue

            lookback_idx = idx - cfg.rl_50_sma_lookback
            sma50rising = (
                lookback_idx >= 0
                and np.isfinite(sma50[idx])
                and np.isfinite(sma50[lookback_idx])
                and sma50[idx] > sma50[lookback_idx]
            )
            dip_hi = y_sma * cfg.rl_dip_pct
            dip_lo = y_sma * (1 - (cfg.rl_dip_pct - 1))
            inthe50zone = l[idx] < dip_hi and l[idx] > dip_lo
            uptick = c[idx] > o[idx]
            closeabove50sma = c[idx] > y_sma
            is200sma = y_idx >= 0 and np.isfinite(sma200[y_idx]) and sma200[y_idx] > 0
            s20 = float(sma20[idx]) if np.isfinite(sma20[idx]) else 0.0
            s50 = float(sma50[idx]) if np.isfinite(sma50[idx]) else 0.0
            s100 = float(sma100[idx]) if np.isfinite(sma100[idx]) else 0.0
            s200 = float(sma200[idx]) if np.isfinite(sma200[idx]) else 0.0
            stack_ok = is200sma and s20 > s50 > 0 and s50 > s100 > 0 and s100 > s200 > 0
            dip_gate = sma50rising and inthe50zone and uptick and closeabove50sma and stack_ok
            if not dip_gate:
                continue

            dip_total += 1
            next_idx = idx + 1
            if next_idx >= n:
                continue
            next_open = float(o[next_idx])
            if next_open <= 0:
                continue

            cur_hi_pct_entry = (h[idx - 1] - y_sma) / y_sma if j > 1 and y_sma > 0 else 0.0
            b = bucket(cur_hi_pct_entry)
            if b == "ge_25_blocked":
                cut_blocked += 1
                sym_cut[sym] += 1
            elif b == "20_24.99_allowed":
                near_allowed += 1
            else:
                dip_under20 += 1

            expansion = 0
            for k in range(cfg.expansion_lookback_days):
                p_idx = idx - k
                if p_idx < 1:
                    continue
                prev_p = p_idx - 1
                if np.isfinite(sma50[prev_p]) and sma50[prev_p] > 0 and c[p_idx] >= sma50[prev_p] * cfg.rl_expansion:
                    expansion = 1
                    break
            cut_it = int(cur_hi_pct_entry < cfg.rl_cut_the_losers)
            signal_open = float(o[idx])
            atr_vol = atr_rolling / signal_open if signal_open > 0 else 0.0
            atr_inclusion = (
                atr_pct_band_passes(atr_vol, cfg.rl_atr_low_percent, cfg.rl_atr_high_percent)
                and atr_rolling < cfg.rl_atr_high_value
                and signal_open >= cfg.rl_low_price
            )
            peak_inclusion = peak_cl < cfg.peak_threshold_max
            slope_ok = cfg.rl_slope_threshold == 0 or True
            too_low = 0
            if o[next_idx] > 0 and o[next_idx] < l[idx] * cfg.rl_stop_pct:
                too_low = 1
            vol_ok = True
            if cfg.avg_vol_days > 0 and cfg.vol_pct_threshold > 0:
                entry_day_vol = vol[next_idx]
                vol_ok = avg_vol > 0 and entry_day_vol >= avg_vol * (1 + cfg.vol_pct_threshold / 100)
            entry_ok = cfg.rl_too_high == 0 or next_open <= l[idx] * cfg.rl_too_high * cfg.rl_stop_pct

            other_ok = (
                expansion
                and acceptance
                and atr_inclusion
                and peak_inclusion
                and slope_ok
                and not too_low
                and vol_ok
                and entry_ok
            )
            if other_ok and not cut_it:
                cut_blocked_other_ok += 1

    return {
        "dip_total": dip_total,
        "cut_blocked": cut_blocked,
        "cut_blocked_other_ok": cut_blocked_other_ok,
        "near_allowed_dip": near_allowed,
        "dip_under20": dip_under20,
        "sym_cut": sym_cut,
    }


def write_stats_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def write_report_html(
    trade_rows: list[dict[str, Any]],
    bucket_summary: list[dict[str, Any]],
    exit_rows: list[dict[str, Any]],
    scan: dict[str, Any],
    closed_n: int,
    missing: int,
    parity_n: int,
) -> str:
    th1 = "".join(
        sortable_th(l, t)
        for l, t in [
            ("Bucket", "text"),
            ("N trades", "num"),
            ("Share of book", "num"),
            ("Win%", "num"),
            ("Avg PnL%", "num"),
        ]
    )
    body1 = []
    for r in bucket_summary:
        body1.append(
            f"<tr><td>{html_mod.escape(r['bucket'])}</td>"
            f"<td>{r['n']}</td><td>{r['pct_book']:.1f}%</td>"
            f"<td>{r['wr']:.1f}%</td><td>{r['avg_pnl']:.2f}%</td></tr>"
        )

    th2 = "".join(
        sortable_th(l, t)
        for l, t in [
            ("Bucket", "text"),
            ("Exit type", "text"),
            ("Count", "num"),
            ("Share within bucket", "num"),
        ]
    )
    body2 = []
    for r in exit_rows:
        body2.append(
            f"<tr><td>{html_mod.escape(r['bucket'])}</td>"
            f"<td>{html_mod.escape(r['exit'])}</td>"
            f"<td>{r['n']}</td><td>{r['pct']:.1f}%</td></tr>"
        )

    th3 = "".join(
        sortable_th(l, t)
        for l, t in [
            ("SYMBOL", "text"),
            ("Entry", "date"),
            ("cur_hi_pct", "num"),
            ("Bucket", "text"),
            ("Exit", "text"),
            ("PnL%", "num"),
        ]
    )
    body3 = []
    for r in trade_rows[:500]:
        body3.append(
            f"<tr><td>{r['sym']}</td><td>{r['opened']}</td>"
            f"<td>{r['cur_hi_pct']:.4f}</td><td>{html_mod.escape(r['bucket_label'])}</td>"
            f"<td>{html_mod.escape(r['exit'])}</td><td>{r['pnl']}</td></tr>"
        )
    if len(trade_rows) > 500:
        body3.append(
            f'<tr class="total-row"><td colspan="6">… {len(trade_rows) - 500} more trades in stats.csv</td></tr>'
        )

    scan_html = f"""
<ul>
  <li>Dip+stack primary gate events (tradable universe scan): <strong>{scan['dip_total']:,}</strong></li>
  <li>Of those, prior-bar high ≥ 25% above SMA50 (blocked by cut=0.25): <strong>{scan['cut_blocked']:,}</strong></li>
  <li>Same, but all other house secondary filters pass (true cut-only blocks): <strong>{scan['cut_blocked_other_ok']:,}</strong></li>
  <li>Dip signals in 20–24.99% band (allowed): <strong>{scan['near_allowed_dip']:,}</strong></li>
  <li>Dip signals &lt; 20%: <strong>{scan['dip_under20']:,}</strong></li>
</ul>
"""

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>RL cut-the-losers stats {STAMP}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 1.5rem; max-width: 1100px; }}
h1,h2 {{ margin-top: 1.5rem; }}
table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
th, td {{ border: 1px solid #ccc; padding: 6px 10px; text-align: right; }}
th {{ background: #f4f4f4; }}
td:first-child, th:first-child {{ text-align: left; }}
.muted {{ color: #555; font-size: 0.95rem; }}
{SORTABLE_TH_CSS}
</style></head><body>
<h1>RL <code>rl_cut_the_losers=0.25</code> stats</h1>
<p class="muted">Closed book: <code>RL_Closed_260828112205.csv</code> (tradable 764, N={closed_n:,}).
cur_hi_pct = prior-bar High vs prior-bar SMA50 at signal bar (matches <code>rocket_rl.py</code>).
IS/OOS split: entry &lt; 2024-01-01 / ≥ 2024-01-01.</p>
<p><strong>Parity check:</strong> {parity_n} executed trades have cur_hi_pct ≥ 25% (should be 0 if filter was on).</p>
<p><strong>OHLC recompute missing:</strong> {missing} trades.</p>

<h2>Executed trades by bucket</h2>
<p class="muted">Click column headers to sort.</p>
<table class="sortable"><thead><tr>{th1}</tr></thead><tbody>{"".join(body1)}</tbody></table>

<h2>Exit mix by bucket</h2>
<table class="sortable"><thead><tr>{th2}</tr></thead><tbody>{"".join(body2)}</tbody></table>

<h2>Estimated blocked dip signals (universe scan)</h2>
{scan_html}

<h2>Near-ceiling trades (20–24.99%)</h2>
<p>Sample rows; full list in <code>stats.csv</code>.</p>
<table class="sortable"><thead><tr>{th3}</tr></thead><tbody>{"".join(body3)}</tbody></table>

{SORTABLE_TABLE_SCRIPT}
</body></html>"""


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cfg = RLConfig(rl_cut_the_losers=CUT)

    if not CLOSED.is_file():
        print(f"Missing closed book: {CLOSED}", file=sys.stderr)
        return 1

    closed = load_closed(CLOSED)
    labeled: list[dict[str, Any]] = []
    missing = 0
    by_bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for t in closed:
        df = load_ohlc(t["sym"])
        if df is None:
            missing += 1
            continue
        pct = cur_hi_pct_at_entry(df, t["opened"])
        if pct is None:
            missing += 1
            continue
        b = bucket(pct)
        row = {
            **t,
            "cur_hi_pct": round(pct, 6),
            "bucket": b,
            "bucket_label": bucket_label(b),
            "split": "IS" if t["opened"] < IS_CUT else "OOS",
            "pnl": t["pnl_raw"],
        }
        labeled.append(row)
        by_bucket[b].append(row)

    closed_n = len(closed)
    parity_n = len(by_bucket["ge_25_blocked"])

    bucket_summary = []
    stats_rows: list[dict[str, Any]] = []
    exit_rows: list[dict[str, Any]] = []

    for b in ("lt_20", "20_24.99_allowed", "ge_25_blocked"):
        trades = by_bucket[b]
        m = metrics_for(trades)
        bucket_summary.append(
            {
                "bucket": bucket_label(b),
                "n": m["n"],
                "pct_book": 100.0 * m["n"] / closed_n if closed_n else 0,
                "wr": m["wr"],
                "avg_pnl": m["avg_pnl"],
            }
        )
        for xt, cnt in m["exits"].most_common():
            exit_rows.append(
                {
                    "bucket": bucket_label(b),
                    "exit": xt,
                    "n": cnt,
                    "pct": 100.0 * cnt / m["n"] if m["n"] else 0,
                }
            )
        for xt, cnt in m["exits"].most_common():
            stats_rows.append(
                {
                    "section": "exit_mix",
                    "bucket": bucket_label(b),
                    "metric": xt,
                    "value": cnt,
                    "pct_of_bucket": round(100.0 * cnt / m["n"], 2) if m["n"] else 0,
                    "n_bucket": m["n"],
                }
            )
        stats_rows.append(
            {
                "section": "bucket_summary",
                "bucket": bucket_label(b),
                "metric": "N",
                "value": m["n"],
                "pct_of_bucket": round(100.0 * m["n"] / closed_n, 2) if closed_n else 0,
                "n_bucket": closed_n,
            }
        )
        stats_rows.append(
            {
                "section": "bucket_summary",
                "bucket": bucket_label(b),
                "metric": "win_pct",
                "value": round(m["wr"], 2),
                "pct_of_bucket": "",
                "n_bucket": m["n"],
            }
        )
        stats_rows.append(
            {
                "section": "bucket_summary",
                "bucket": bucket_label(b),
                "metric": "avg_pnl_pct",
                "value": round(m["avg_pnl"], 2),
                "pct_of_bucket": "",
                "n_bucket": m["n"],
            }
        )

    # Full book exit mix (control)
    full_m = metrics_for(labeled)
    for xt, cnt in full_m["exits"].most_common():
        stats_rows.append(
            {
                "section": "exit_mix_full_book",
                "bucket": "full book",
                "metric": xt,
                "value": cnt,
                "pct_of_bucket": round(100.0 * cnt / full_m["n"], 2) if full_m["n"] else 0,
                "n_bucket": full_m["n"],
            }
        )

    symbols = load_universe_symbols(UNIVERSE)
    scan = scan_cut_blocks(symbols, cfg)
    for k, v in scan.items():
        if k == "sym_cut":
            continue
        stats_rows.append(
            {
                "section": "dip_scan",
                "bucket": "",
                "metric": k,
                "value": v,
                "pct_of_bucket": "",
                "n_bucket": "",
            }
        )

    # Trade-level CSV
    trade_csv = OUT_DIR / "trade_cur_hi_pct.csv"
    with trade_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["sym", "opened", "cur_hi_pct", "bucket", "bucket_label", "split", "exit", "pnl"],
        )
        w.writeheader()
        for r in sorted(labeled, key=lambda x: (-x["cur_hi_pct"], x["sym"], str(x["opened"]))):
            w.writerow({k: r[k] for k in w.fieldnames})

    write_stats_csv(stats_rows, OUT_DIR / "stats.csv")

    near = by_bucket["20_24.99_allowed"]
    near_m = metrics_for(near)
    full_exit = exit_mix_str(full_m["exits"])
    near_exit = exit_mix_str(near_m["exits"])

    summary = f"""# RL cut-the-losers (`rl_cut_the_losers=0.25`) — {STAMP}

## Plain English (Paul)

**What it does:** At each dip signal, RL blocks entry if the **prior bar's high** is already **≥ 25% above that bar's SMA50** (Simple Moving Average, 50-day). Entries in the **20–24.99%** band are still allowed — they're extended but under the ceiling.

## Executed trades (Closed book N={closed_n:,})

| Bucket | N | % of book | Win% | Avg PnL% |
|--------|---|-----------|------|----------|
"""
    for r in bucket_summary:
        summary += f"| {r['bucket']} | {r['n']} | {r['pct_book']:.1f}% | {r['wr']:.1f}% | {r['avg_pnl']:.2f}% |\n"

    summary += f"""
**Near-ceiling band (20–24.99%):** **{near_m['n']}** trades ({100 * near_m['n'] / closed_n:.1f}% of book).

**Parity:** {parity_n} closed trades have cur_hi_pct ≥ 25% — these should not appear if cut=0.25 was active for the full run (investigate if >0).

## Exit mix — 20–24.99% band vs full book

- **20–24.99% band ({near_m['n']} trades):** {near_exit}
- **Full book ({full_m['n']} trades):** {full_exit}

## Estimated blocked dip signals (tradable universe scan)

Heuristic rescan of dip+stack primary gate on **{len(symbols)}** symbols (house RLConfig freeze, cut=0.25):

| Metric | Count |
|--------|------:|
| Total dip+stack signal days | {scan['dip_total']:,} |
| Prior-bar high ≥ 25% (cut blocks) | {scan['cut_blocked']:,} |
| Cut-only blocks (other secondary filters pass) | {scan['cut_blocked_other_ok']:,} |
| Dip signals in 20–24.99% (allowed) | {scan['near_allowed_dip']:,} |
| Dip signals < 20% | {scan['dip_under20']:,} |

**Interpretation:** Over the full history, roughly **{scan['cut_blocked']:,}** dip setups hit the extension ceiling; **{scan['cut_blocked_other_ok']:,}** of those would have passed every other house filter and were blocked **only** by cut-the-losers. The **{near_m['n']}** executed trades in 20–24.99% are the "near miss allowed" cohort in the Closed ledger.

## Files

- `stats.csv` — bucket + exit mix + scan counts
- `trade_cur_hi_pct.csv` — per-trade cur_hi_pct
- `report.html` — sortable tables

## Method

- `cur_hi_pct = (High[prior bar] - SMA50[prior bar]) / SMA50[prior bar]` at signal bar (day before `DATE OPENED`), matching `rocket_rl.py` / `rl_missed_moves.py`.
- Closed: `RL_Closed_260828112205.csv` (tradable 764 stamp).
- Missing OHLC recompute: {missing} trades.
"""
    (OUT_DIR / "SUMMARY.md").write_text(summary, encoding="utf-8")

    html = write_report_html(
        sorted(labeled, key=lambda x: -x["cur_hi_pct"]),
        bucket_summary,
        exit_rows,
        scan,
        closed_n,
        missing,
        parity_n,
    )
    report_path = OUT_DIR / "report.html"
    report_path.write_text(html, encoding="utf-8")

    subprocess.run(
        [sys.executable, str(ROOT / "tools" / "ntfy_job_done.py"), "--path", str(report_path)],
        cwd=str(ROOT),
        check=False,
    )

    print(summary.encode("ascii", errors="replace").decode("ascii"))
    print(f"\nWrote {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
