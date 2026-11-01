#!/usr/bin/env python3
"""Directional watchlist from long-term daily zones + recent location (research).

Heuristic only — NOT financial advice, NOT a KEEP trading system, NOT DailyRun.

Scores BRT new131 + RL59 (union with daily+1m when available) for up/down bias
using LT zones from tools/lt_zones_daily_to_15m.py plus prior-day / last-15m context.

Examples:
  python tools/lt_zones_direction_watch.py
  python tools/lt_zones_direction_watch.py --top 10 --near-pct 0.02
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
_TOOLS = Path(__file__).resolve().parent
_SA = _REPO / "stock_analysis"
for _p in (_SA, _REPO, _TOOLS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from intraday_1m import DEFAULT_1M_DIR  # noqa: E402
import lt_zones_daily_to_15m as lt  # noqa: E402

DEFAULT_STAMP = _REPO / "drive" / "paul_experiments" / "lt_zones_direction_watch_20260824"
DEFAULT_DAILY = _REPO / "data" / "newdata" / "data"
DEFAULT_UNIVERSES = [
    _REPO / "drive" / "universes" / "BRT_new_from_paul_20260822.csv",
    _REPO / "drive" / "universes" / "RL_universe.csv",
]

NEAR_PCT_DEFAULT = 0.02
SUPPORT_TYPES = {"yearly_low", "hvn", "swing_sr", "poc", "lvn"}
RESIST_TYPES = {"yearly_high", "hvn", "swing_sr", "poc", "lvn"}
TYPE_W = {
    "yearly_low": 1.0,
    "yearly_high": 1.0,
    "poc": 0.75,
    "hvn": 0.65,
    "swing_sr": 0.50,
    "lvn": 0.20,
}

_SORTABLE_TABLE_SCRIPT = lt._SORTABLE_TABLE_SCRIPT
SORTABLE_TH_CSS = """
  th.sortable-th { cursor:pointer; user-select:none; white-space:nowrap; }
  th.sortable-th:hover { background:#e8e6df; }
  th.sortable-th .sort-ind::after { content:" \\u2195"; opacity:0.35; font-size:0.85em; }
  th.sortable-th.sort-asc .sort-ind::after { content:" \\u25B2"; opacity:0.9; }
  th.sortable-th.sort-desc .sort-ind::after { content:" \\u25BC"; opacity:0.9; }
"""


def _sortable_th(label: str, sort_type: str) -> str:
    return lt._sortable_th(label, sort_type)


def resolve_pool(
    univ_paths: list[Path],
    *,
    data_dir: Path,
    in_dir: Path,
    require_1m: bool = True,
) -> tuple[list[str], dict]:
    pool: list[str] = []
    seen: set[str] = set()
    per_univ: dict[str, list[str]] = {}
    for up in univ_paths:
        if not up.is_file():
            per_univ[up.name] = []
            continue
        syms = lt._load_universe(up)
        per_univ[up.name] = syms
        for s in syms:
            if s not in seen:
                seen.add(s)
                pool.append(s)

    both: list[str] = []
    daily_only: list[str] = []
    missing_daily = 0
    missing_1m = 0
    for s in pool:
        has_d = (data_dir / f"{s}.csv").is_file()
        has_1 = (in_dir / f"{s}.parquet").is_file()
        if not has_d:
            missing_daily += 1
            continue
        if not has_1:
            missing_1m += 1
            daily_only.append(s)
            if not require_1m:
                both.append(s)
            continue
        both.append(s)

    names = [p.name for p in univ_paths]
    overlap = 0
    if len(names) >= 2:
        overlap = len(set(per_univ.get(names[0], [])) & set(per_univ.get(names[1], [])))

    meta = {
        "universe_files": [p.as_posix() for p in univ_paths],
        "per_univ_n": {k: len(v) for k, v in per_univ.items()},
        "union_n": len(pool),
        "scored_n": len(both),
        "daily_only_n": len(daily_only),
        "missing_daily": missing_daily,
        "missing_1m": missing_1m,
        "overlap_n": overlap,
    }
    return both, meta


def _last_price_and_bars(
    symbol: str,
    daily: pd.DataFrame,
    in_dir: Path,
) -> tuple[float, Optional[pd.DataFrame], str, Optional[pd.Timestamp]]:
    """Prefer last 15m close; fall back to daily close."""
    bars = None
    try:
        bars = lt.load_15m(symbol, in_dir=in_dir)
    except Exception:
        bars = None
    if bars is not None and not bars.empty:
        ccol = "close" if "close" in bars.columns else "Close"
        tcol = "ts" if "ts" in bars.columns else None
        px = float(bars[ccol].iloc[-1])
        ts = pd.to_datetime(bars[tcol].iloc[-1]) if tcol else None
        return px, bars, "15m_last", ts
    px = float(daily["Close"].iloc[-1])
    ts = pd.to_datetime(daily["Date"].iloc[-1])
    return px, None, "daily_close", ts


def _dist_to_zone(price: float, z: lt.Zone) -> float:
    if z.lo <= price <= z.hi:
        return 0.0
    return min(abs(price - z.lo), abs(price - z.hi)) / max(price, 1e-9)


def _nearest_side(
    price: float,
    zones: list[lt.Zone],
    *,
    side: str,
    near_pct: float,
) -> tuple[Optional[lt.Zone], float]:
    """Nearest zone below (support) or above (resistance), within near_pct if possible."""
    cands: list[tuple[float, lt.Zone]] = []
    for z in zones:
        d = _dist_to_zone(price, z)
        mid = float(z.mid)
        if side == "support":
            # below or intersecting from below / inside
            if mid > price * (1 + 0.002) and price < z.lo:
                continue
            if z.zone_type == "yearly_high":
                continue
            # prefer zones whose mid is at/below price, or band intersects
            if mid <= price * 1.002 or z.lo <= price <= z.hi:
                cands.append((d, z))
        else:
            if z.zone_type == "yearly_low":
                continue
            if mid >= price * 0.998 or z.lo <= price <= z.hi:
                cands.append((d, z))
    if not cands:
        return None, float("inf")
    cands.sort(key=lambda t: (t[0], -TYPE_W.get(t[1].zone_type, 0.3), -t[1].strength))
    z = cands[0][1]
    d = cands[0][0]
    if d > near_pct * 1.5:
        # still return nearest for context, but callers gate on near_pct
        return z, d
    return z, d


def score_symbol(
    symbol: str,
    *,
    data_dir: Path,
    in_dir: Path,
    near_pct: float,
    univ_tags: list[str],
) -> Optional[dict]:
    try:
        daily = lt._load_daily(symbol, data_dir)
    except Exception:
        return None
    if len(daily) < 60:
        return None

    zones = lt.compute_lt_zones(daily, symbol, include_lvn=False, max_swing=6)
    if not zones:
        return None

    price, bars15, price_src, price_ts = _last_price_and_bars(symbol, daily, in_dir)
    if not np.isfinite(price) or price <= 0:
        return None

    last = daily.iloc[-1]
    prev = daily.iloc[-2] if len(daily) >= 2 else last
    d_open = float(last["Open"])
    d_high = float(last["High"])
    d_low = float(last["Low"])
    d_close = float(last["Close"])
    p_high = float(prev["High"])
    p_low = float(prev["Low"])
    p_close = float(prev["Close"])
    day_range = max(d_high - d_low, 1e-9)
    prior_range = max(p_high - p_low, 1e-9)
    day_loc = (d_close - d_low) / day_range
    prior_loc = (p_close - p_low) / prior_range
    day_ret = (d_close - p_close) / max(p_close, 1e-9)

    yl = next((z for z in zones if z.zone_type == "yearly_low"), None)
    yh = next((z for z in zones if z.zone_type == "yearly_high"), None)
    poc = next((z for z in zones if z.zone_type == "poc"), None)

    yl_mid = float(yl.mid) if yl else float("nan")
    yh_mid = float(yh.mid) if yh else float("nan")
    poc_mid = float(poc.mid) if poc else float("nan")

    if np.isfinite(yl_mid) and np.isfinite(yh_mid) and yh_mid > yl_mid:
        yr_pos = (price - yl_mid) / (yh_mid - yl_mid)
        yr_pos = float(np.clip(yr_pos, 0.0, 1.0))
        dist_yl = (price - yl_mid) / price
        dist_yh = (yh_mid - price) / price
    else:
        yr_pos = 0.5
        dist_yl = dist_yh = float("nan")

    up = 0.0
    down = 0.0
    reasons_up: list[str] = []
    reasons_down: list[str] = []

    # --- Near support holding → up ---
    sup, d_sup = _nearest_side(price, zones, side="support", near_pct=near_pct)
    if sup is not None and d_sup <= near_pct and price >= float(sup.lo) * 0.999:
        w = TYPE_W.get(sup.zone_type, 0.4)
        prox = 1.0 - (d_sup / max(near_pct, 1e-9))
        pts = 42.0 * w * max(prox, 0.15)
        # confluence bonus
        if sup.confluence:
            pts *= 1.15
        up += pts
        reasons_up.append(
            f"holding near {sup.zone_type}@{sup.mid:.2f} (dist {d_sup*100:.2f}%)"
        )

    # --- Near resistance failing → down ---
    res, d_res = _nearest_side(price, zones, side="resistance", near_pct=near_pct)
    if res is not None and d_res <= near_pct and price <= float(res.hi) * 1.001:
        w = TYPE_W.get(res.zone_type, 0.4)
        prox = 1.0 - (d_res / max(near_pct, 1e-9))
        pts = 42.0 * w * max(prox, 0.15)
        if res.confluence:
            pts *= 1.15
        # failing: close in lower half of prior/day range or below zone mid after touch
        failing = day_loc < 0.45 or price < float(res.mid)
        if failing:
            pts *= 1.1
            reasons_down.append(
                f"failing near {res.zone_type}@{res.mid:.2f} (dist {d_res*100:.2f}%)"
            )
        else:
            reasons_down.append(
                f"near {res.zone_type}@{res.mid:.2f} (dist {d_res*100:.2f}%)"
            )
        down += pts

    # --- POC / HVN reclaim vs loss ---
    if poc is not None and np.isfinite(poc_mid):
        above_poc = price >= poc_mid
        # prior close vs POC
        prior_above = p_close >= poc_mid
        if above_poc and not prior_above:
            up += 14.0
            reasons_up.append(f"reclaimed POC@{poc_mid:.2f}")
        elif (not above_poc) and prior_above:
            down += 14.0
            reasons_down.append(f"lost POC@{poc_mid:.2f}")
        elif above_poc:
            up += 6.0
            reasons_up.append(f"holding above POC@{poc_mid:.2f}")
        else:
            down += 6.0
            reasons_down.append(f"below POC@{poc_mid:.2f}")

    # nearest HVN side as secondary magnet
    hvns = [z for z in zones if z.zone_type == "hvn"]
    if hvns:
        below = [z for z in hvns if z.mid <= price]
        above = [z for z in hvns if z.mid >= price]
        if below:
            zb = min(below, key=lambda z: _dist_to_zone(price, z))
            db = _dist_to_zone(price, zb)
            if db <= near_pct:
                up += 8.0 * (1.0 - db / near_pct)
                reasons_up.append(f"HVN support@{zb.mid:.2f}")
        if above:
            za = min(above, key=lambda z: _dist_to_zone(price, z))
            da = _dist_to_zone(price, za)
            if da <= near_pct:
                down += 8.0 * (1.0 - da / near_pct)
                reasons_down.append(f"HVN overhead@{za.mid:.2f}")

    # --- Distance to yearly H/L ---
    if np.isfinite(dist_yl) and np.isfinite(dist_yh):
        # mean-reversion lean near extremes (research heuristic)
        up += (1.0 - yr_pos) * 12.0
        down += yr_pos * 12.0
        if dist_yl <= near_pct:
            up += 18.0 * (1.0 - dist_yl / near_pct)
            reasons_up.append(f"near yearly low@{yl_mid:.2f}")
        if dist_yh <= near_pct:
            down += 18.0 * (1.0 - dist_yh / near_pct)
            reasons_down.append(f"near yearly high@{yh_mid:.2f}")

    # --- Short-term momentum (prior day / last session vs prior H/L) ---
    if day_loc >= 0.70:
        up += 7.0
        reasons_up.append(f"prior session closed strong (loc {day_loc:.2f})")
    elif day_loc <= 0.30:
        down += 7.0
        reasons_down.append(f"prior session closed weak (loc {day_loc:.2f})")

    if price > p_high:
        up += 10.0
        reasons_up.append("above prior-day high")
    elif price < p_low:
        down += 10.0
        reasons_down.append("below prior-day low")

    # open vs prior range (last session open as proxy for "vs overnight" when no Mon open yet)
    if d_open > p_high:
        up += 4.0
    elif d_open < p_low:
        down += 4.0

    up += max(0.0, day_ret) * 180.0
    down += max(0.0, -day_ret) * 180.0
    if abs(day_ret) >= 0.015:
        if day_ret > 0:
            reasons_up.append(f"day ret {day_ret*100:+.2f}%")
        else:
            reasons_down.append(f"day ret {day_ret*100:+.2f}%")

    # 15m session tilt vs daily close (if available)
    if bars15 is not None and len(bars15) >= 4:
        ccol = "close" if "close" in bars15.columns else "Close"
        last4 = bars15[ccol].astype(float).iloc[-4:]
        m15 = float(last4.iloc[-1] / last4.iloc[0] - 1.0)
        if m15 > 0.002:
            up += 5.0
        elif m15 < -0.002:
            down += 5.0

    net = up - down
    # confidence from |net| and zone clarity
    abs_net = abs(net)
    clear_zone = (sup is not None and d_sup <= near_pct) or (res is not None and d_res <= near_pct)
    if abs_net >= 35 and clear_zone:
        conf = "MED"
    elif abs_net >= 22:
        conf = "MED" if clear_zone else "LOW"
    else:
        conf = "LOW"
    # never claim HIGH for this research heuristic
    lean = "UP" if net > 8 else ("DOWN" if net < -8 else "CHOP")

    return {
        "symbol": symbol,
        "universe": ",".join(univ_tags) if univ_tags else "",
        "price": round(price, 4),
        "price_src": price_src,
        "price_ts": str(price_ts) if price_ts is not None else "",
        "daily_last": str(pd.to_datetime(last["Date"]).date()),
        "day_ret_pct": round(day_ret * 100.0, 3),
        "day_loc": round(day_loc, 3),
        "prior_loc": round(prior_loc, 3),
        "yr_pos": round(yr_pos, 3),
        "dist_yl_pct": round(dist_yl * 100.0, 3) if np.isfinite(dist_yl) else None,
        "dist_yh_pct": round(dist_yh * 100.0, 3) if np.isfinite(dist_yh) else None,
        "yl": round(yl_mid, 4) if np.isfinite(yl_mid) else None,
        "yh": round(yh_mid, 4) if np.isfinite(yh_mid) else None,
        "poc": round(poc_mid, 4) if np.isfinite(poc_mid) else None,
        "near_support": f"{sup.zone_type}@{sup.mid:.2f}" if (sup and d_sup <= near_pct) else "",
        "near_resist": f"{res.zone_type}@{res.mid:.2f}" if (res and d_res <= near_pct) else "",
        "d_sup_pct": round(d_sup * 100.0, 3) if np.isfinite(d_sup) else None,
        "d_res_pct": round(d_res * 100.0, 3) if np.isfinite(d_res) else None,
        "up_score": round(up, 2),
        "down_score": round(down, 2),
        "net_score": round(net, 2),
        "lean": lean,
        "confidence": conf,
        "reasons_up": "; ".join(reasons_up[:4]) if reasons_up else "",
        "reasons_down": "; ".join(reasons_down[:4]) if reasons_down else "",
        "n_zones": len(zones),
    }


def score_spy_detail(row: dict, daily: pd.DataFrame, zones: list[lt.Zone], near_pct: float) -> dict:
    """Extra narrative fields for SPY section."""
    last = daily.iloc[-1]
    prev = daily.iloc[-2]
    px = float(row["price"])
    p_hi, p_lo, p_c = float(prev["High"]), float(prev["Low"]), float(prev["Close"])
    vs_prior = "inside prior range"
    if px > p_hi:
        vs_prior = "above prior-day high"
    elif px < p_lo:
        vs_prior = "below prior-day low"
    poc = row.get("poc")
    poc_note = "n/a"
    if poc is not None:
        poc_note = "above POC" if px >= float(poc) else "below POC"
    return {
        **row,
        "spy_vs_prior_hl": vs_prior,
        "spy_prior_high": p_hi,
        "spy_prior_low": p_lo,
        "spy_prior_close": p_c,
        "spy_poc_note": poc_note,
        "spy_near_pct": near_pct,
        "spy_n_zones": len(zones),
    }


def write_baseline(path: Path, meta: dict, near_pct: float, asof: str) -> None:
    path.write_text(
        f"""# BASELINE — LT zones direction watch (research)

**Stamp:** `lt_zones_direction_watch_20260824`  
**As-of:** {asof}  
**Status:** research heuristic only — **not** financial advice, **not** a KEEP claim, **not** DailyRun-wired.

## Disclaimer

This ranking is an **educational / research screen** that combines long-term daily support/resistance zones with recent daily and 15-minute location. Zones are not a crystal ball. Short 1m history and weekend gaps (Monday morning uses Friday close / last 15m) limit confidence. Do **not** treat lists as trade instructions.

## Universe (frozen)

| Source | Path | N |
|--------|------|---|
| BRT new131 | `drive/universes/BRT_new_from_paul_20260822.csv` | {meta.get('per_univ_n', {}).get('BRT_new_from_paul_20260822.csv', '?')} |
| RL59 | `drive/universes/RL_universe.csv` | {meta.get('per_univ_n', {}).get('RL_universe.csv', '?')} |
| Union | — | {meta.get('union_n')} |
| Overlap | — | {meta.get('overlap_n')} |
| Scored (daily+1m preferred) | — | {meta.get('scored_n')} |
| Missing daily / missing 1m | — | {meta.get('missing_daily')} / {meta.get('missing_1m')} |

SPY is always scored for the index lean section (even if not in the union).

## Zone engine (frozen)

Reuses `tools/lt_zones_daily_to_15m.py` → `compute_lt_zones`:

- Yearly high / low: rolling 252d max High / min Low
- Swing S/R: fractal pivots (k=3) clustered ≥3 touches
- Volume profile POC / HVN via `stock_analysis.vec_zones` (LVN excluded here)

Near threshold: **{near_pct * 100:.1f}%** of price.

## Direction score (documented)

Single **net_score** = `up_score − down_score`. Top 10 net = up bias list; bottom 10 = down bias list (no duplicate names across lists).

| Component | Up bias | Down bias |
|-----------|---------|-----------|
| Near support holding (YL, HVN below, demand swing, POC) | + weighted by type × proximity | — |
| Near resistance failing (YH, HVN above, supply swing) | — | + weighted; extra if session weak |
| POC reclaim / loss vs prior close | reclaim / hold above | lost / below |
| Nearby HVN magnets | HVN below within near% | HVN above within near% |
| Yearly range location | closer to YL (+); near YL boost | closer to YH (+); near YH boost |
| Momentum | strong day loc, above prior high, positive day ret, last-hour 15m up | weak loc, below prior low, negative ret, 15m down |

Type weights: yearly H/L=1.0, POC=0.75, HVN=0.65, swing=0.50.

**Lean:** UP if net > 8, DOWN if net < −8, else CHOP.  
**Confidence:** only LOW or MED (never HIGH) — clear near-zone + |net|≥35 → MED; else usually LOW.

## Data limits

- Intraday as-of last available 15m bar (often prior session close on Monday morning).
- Daily CSVs under `data/newdata/data/`; 1m under `data/intraday/1m/` via DuckDB resample.
- No overnight Monday open in file → open-vs-prior uses **last session open** as weak proxy.
- Sibling stamp `lt_zones_15m_analysis_20260824` may share tools; this watchlist does not wait on its outcomes.

## Decision

**Research-only watchlist.** No KEEP / no DailyRun.
""",
        encoding="utf-8",
    )


def write_summary(
    path: Path,
    *,
    asof: str,
    up: pd.DataFrame,
    down: pd.DataFrame,
    spy: dict,
    meta: dict,
) -> None:
    def _fmt_list(df: pd.DataFrame, score_col: str) -> str:
        lines = []
        for i, r in enumerate(df.itertuples(index=False), 1):
            d = r._asdict() if hasattr(r, "_asdict") else dict(zip(df.columns, r))
            why = d.get("reasons_up") if score_col == "up_score" else d.get("reasons_down")
            if not why:
                why = d.get("reasons_up") or d.get("reasons_down") or "—"
            lines.append(
                f"{i}. **{d['symbol']}** — net {d['net_score']:+.1f} "
                f"(up {d['up_score']:.0f} / down {d['down_score']:.0f}, {d['lean']}/{d['confidence']}) "
                f"@ {d['price']:.2f} — {why}"
            )
        return "\n".join(lines)

    spy_lean = spy.get("lean", "CHOP")
    spy_conf = spy.get("confidence", "LOW")
    path.write_text(
        f"""# SUMMARY — Direction watch {asof[:10] if asof else '2026-08-24'}

Research heuristic only — **not** advice. Scored **{meta.get('scored_n')}** names from BRT new131 ∪ RL59 (plus SPY).

## SPY lean

**{spy_lean}** · confidence **{spy_conf}** · net **{spy.get('net_score', 0):+.1f}** · price **{spy.get('price', float('nan')):.2f}** ({spy.get('price_src')})

- vs prior day H/L: {spy.get('spy_vs_prior_hl', '—')}
- POC: {spy.get('spy_poc_note', '—')} (POC={spy.get('poc')})
- yearly position: {spy.get('yr_pos')} (0=YL … 1=YH); dist YL {spy.get('dist_yl_pct')}% / YH {spy.get('dist_yh_pct')}%
- near: support `{spy.get('near_support') or '—'}` · resist `{spy.get('near_resist') or '—'}`
- why up: {spy.get('reasons_up') or '—'}
- why down: {spy.get('reasons_down') or '—'}

## Top 10 up bias

{_fmt_list(up, 'up_score')}

## Top 10 down bias

{_fmt_list(down, 'down_score')}

## Limits

Short 1m history on some names; Monday morning uses Friday session as location proxy; zones ≠ forecast. Full table: `watch.html`.
""",
        encoding="utf-8",
    )


def _rows_html(df: pd.DataFrame, *, why_key: str = "reasons_up") -> str:
    out = []
    for r in df.itertuples(index=False):
        d = r._asdict() if hasattr(r, "_asdict") else dict(zip(df.columns, r))
        why = d.get(why_key) or d.get("reasons_up") or d.get("reasons_down") or ""
        out.append(
            "<tr>"
            f"<td>{html_mod.escape(str(d['symbol']))}</td>"
            f"<td class='num'>{float(d['net_score']):+.1f}</td>"
            f"<td class='num'>{float(d['up_score']):.1f}</td>"
            f"<td class='num'>{float(d['down_score']):.1f}</td>"
            f"<td>{html_mod.escape(str(d['lean']))}</td>"
            f"<td>{html_mod.escape(str(d['confidence']))}</td>"
            f"<td class='num'>{float(d['price']):.2f}</td>"
            f"<td class='num'>{float(d['day_ret_pct']):+.2f}</td>"
            f"<td class='num'>{float(d['yr_pos']):.2f}</td>"
            f"<td>{html_mod.escape(str(d.get('near_support') or '—'))}</td>"
            f"<td>{html_mod.escape(str(d.get('near_resist') or '—'))}</td>"
            f"<td>{html_mod.escape(str(d.get('poc') if d.get('poc') is not None else '—'))}</td>"
            f"<td>{html_mod.escape(str(why or '—'))}</td>"
            f"<td>{html_mod.escape(str(d.get('universe') or ''))}</td>"
            "</tr>"
        )
    return "\n".join(out)


def write_watch_html(
    path: Path,
    *,
    asof: str,
    up: pd.DataFrame,
    down: pd.DataFrame,
    spy: dict,
    meta: dict,
    chart_rels: list[tuple[str, str]],
) -> None:
    head = (
        _sortable_th("Symbol", "text")
        + _sortable_th("Net", "num")
        + _sortable_th("Up", "num")
        + _sortable_th("Down", "num")
        + _sortable_th("Lean", "text")
        + _sortable_th("Conf", "text")
        + _sortable_th("Price", "num")
        + _sortable_th("Day%", "num")
        + _sortable_th("YrPos", "num")
        + _sortable_th("Near support", "text")
        + _sortable_th("Near resist", "text")
        + _sortable_th("POC", "num")
        + _sortable_th("Why", "text")
        + _sortable_th("Univ", "text")
    )
    lean = spy.get("lean", "CHOP")
    conf = spy.get("confidence", "LOW")
    lean_cls = {"UP": "up", "DOWN": "down"}.get(str(lean), "chop")
    charts = ""
    for sym, rel in chart_rels:
        charts += (
            f'<figure class="card"><figcaption><strong>{html_mod.escape(sym)}</strong></figcaption>'
            f'<a href="{html_mod.escape(rel)}"><img src="{html_mod.escape(rel)}" alt="{html_mod.escape(sym)} zones" loading="lazy"/></a>'
            f"</figure>\n"
        )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>LT zones direction watch 2026-08-24</title>
<style>
  :root {{ --bg:#f7f5f0; --ink:#1c1b19; --muted:#5c584f; --line:#d9d4c8; --up:#1b5e20; --down:#b71c1c; --chop:#5d4037; }}
  body {{ font-family: "Segoe UI", system-ui, sans-serif; margin:0; background:var(--bg); color:var(--ink); line-height:1.45; }}
  main {{ max-width: 1180px; margin: 0 auto; padding: 1.25rem 1rem 3rem; }}
  h1 {{ font-size: 1.45rem; margin: 0 0 0.35rem; }}
  h2 {{ font-size: 1.15rem; margin: 1.6rem 0 0.5rem; }}
  .sub {{ color: var(--muted); font-size: 0.95rem; margin-bottom: 1rem; }}
  .disclaimer {{ background:#fff3e0; border:1px solid #ffcc80; padding:0.75rem 1rem; border-radius:6px; margin:1rem 0; }}
  .spy {{ border:1px solid var(--line); background:#fff; padding:1rem 1.1rem; border-radius:8px; }}
  .spy .lean {{ font-size:1.35rem; font-weight:700; }}
  .spy .lean.up {{ color:var(--up); }}
  .spy .lean.down {{ color:var(--down); }}
  .spy .lean.chop {{ color:var(--chop); }}
  table.sortable {{ width:100%; border-collapse:collapse; background:#fff; font-size:0.88rem; }}
  table.sortable th, table.sortable td {{ border-bottom:1px solid var(--line); padding:0.4rem 0.45rem; text-align:left; vertical-align:top; }}
  table.sortable th {{ background:#efece4; position:sticky; top:0; z-index:1; }}
  td.num {{ text-align:right; font-variant-numeric: tabular-nums; }}
  {SORTABLE_TH_CSS}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:1rem; margin-top:0.75rem; }}
  figure.card {{ margin:0; background:#fff; border:1px solid var(--line); border-radius:8px; padding:0.5rem; }}
  figure.card img {{ width:100%; height:auto; display:block; border-radius:4px; }}
  figcaption {{ font-size:0.9rem; margin-bottom:0.35rem; color:var(--muted); }}
  .hint {{ color:var(--muted); font-size:0.85rem; margin:0.25rem 0 0.75rem; }}
</style>
</head>
<body>
<main>
<h1>LT zones direction watch — Mon 2026-08-24</h1>
<p class="sub">As-of <strong>{html_mod.escape(asof)}</strong> · scored {meta.get('scored_n')} names (BRT new131 ∪ RL59) · Click column headers to sort</p>
<div class="disclaimer"><strong>Research only — not financial advice.</strong> Long-term daily zones + recent location heuristic. Not a KEEP system. Zones ≠ crystal ball; Monday morning uses Friday/last-15m context.</div>

<section class="spy">
<h2>SPY lean</h2>
<p class="lean {lean_cls}">{html_mod.escape(str(lean))} · {html_mod.escape(str(conf))} confidence · net {float(spy.get('net_score', 0)):+.1f}</p>
<ul>
  <li>Price <strong>{float(spy.get('price', 0)):.2f}</strong> ({html_mod.escape(str(spy.get('price_src','')))})</li>
  <li>vs prior day H/L: {html_mod.escape(str(spy.get('spy_vs_prior_hl','—')))} (prior H {float(spy.get('spy_prior_high',0)):.2f} / L {float(spy.get('spy_prior_low',0)):.2f})</li>
  <li>POC: {html_mod.escape(str(spy.get('spy_poc_note','—')))} @ {html_mod.escape(str(spy.get('poc')))}</li>
  <li>Yearly pos {float(spy.get('yr_pos',0.5)):.2f} · dist YL {html_mod.escape(str(spy.get('dist_yl_pct')))}% · YH {html_mod.escape(str(spy.get('dist_yh_pct')))}%</li>
  <li>Near support: {html_mod.escape(str(spy.get('near_support') or '—'))} · Near resist: {html_mod.escape(str(spy.get('near_resist') or '—'))}</li>
  <li>Why up: {html_mod.escape(str(spy.get('reasons_up') or '—'))}</li>
  <li>Why down: {html_mod.escape(str(spy.get('reasons_down') or '—'))}</li>
</ul>
</section>

<h2>Top 10 — up bias</h2>
<p class="hint">Highest net_score (up − down). Holding near support / POC reclaim / lower yearly location + momentum.</p>
<table class="sortable">
<thead><tr>{head}</tr></thead>
<tbody>
{_rows_html(up, why_key="reasons_up")}
</tbody>
</table>

<h2>Top 10 — down bias</h2>
<p class="hint">Lowest net_score. Near resistance failing / below POC / high in yearly range + weak momentum.</p>
<table class="sortable">
<thead><tr>{head}</tr></thead>
<tbody>
{_rows_html(down, why_key="reasons_down")}
</tbody>
</table>

<h2>Charts (optional)</h2>
<div class="cards">
{charts if charts else "<p class='hint'>No charts generated.</p>"}
</div>

<p class="sub">Universe union {meta.get('union_n')}, overlap {meta.get('overlap_n')}, missing 1m {meta.get('missing_1m')}. See BASELINE.md / SUMMARY.md.</p>
</main>
{_SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="LT zones directional watchlist (research)")
    ap.add_argument("--out-dir", default=str(DEFAULT_STAMP))
    ap.add_argument("--data-dir", default=str(DEFAULT_DAILY))
    ap.add_argument("--in-dir", default=str(DEFAULT_1M_DIR))
    ap.add_argument("--universe", action="append", default=[])
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--near-pct", type=float, default=NEAR_PCT_DEFAULT)
    ap.add_argument("--max-charts", type=int, default=5)
    ap.add_argument("--no-charts", action="store_true")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    charts_dir = out_dir / "charts"
    data_dir = Path(args.data_dir)
    in_dir = Path(args.in_dir)
    near_pct = float(args.near_pct)
    top_n = int(args.top)

    univ_paths = [Path(p) for p in args.universe] if args.universe else list(DEFAULT_UNIVERSES)
    pool, meta = resolve_pool(univ_paths, data_dir=data_dir, in_dir=in_dir, require_1m=True)

    # Tag symbols by universe membership
    univ_map: dict[str, list[str]] = {}
    for up in univ_paths:
        if not up.is_file():
            continue
        tag = "BRT" if "BRT_new" in up.name else ("RL" if "RL_" in up.name else up.stem[:12])
        for s in lt._load_universe(up):
            univ_map.setdefault(s, []).append(tag)

    # Ensure SPY scored
    if "SPY" not in pool and (data_dir / "SPY.csv").is_file():
        # allow SPY even without 1m for lean (but we know 1m exists)
        if (in_dir / "SPY.parquet").is_file() or True:
            pass
    symbols = list(pool)
    if "SPY" not in symbols:
        symbols.append("SPY")

    print(f"Scoring {len(symbols)} symbols (near_pct={near_pct})...", flush=True)
    rows: list[dict] = []
    for i, s in enumerate(symbols):
        r = score_symbol(
            s,
            data_dir=data_dir,
            in_dir=in_dir,
            near_pct=near_pct,
            univ_tags=univ_map.get(s, ["SPY"] if s == "SPY" else []),
        )
        if r:
            rows.append(r)
        if (i + 1) % 25 == 0:
            print(f"  … {i+1}/{len(symbols)}", flush=True)

    if not rows:
        print("No scored rows.", file=sys.stderr)
        return 2

    df = pd.DataFrame(rows).sort_values("net_score", ascending=False).reset_index(drop=True)
    df.to_csv(out_dir / "scores_all.csv", index=False)

    # Top up / bottom down without overlap
    up = df.head(top_n).copy()
    down_cand = df.sort_values("net_score", ascending=True)
    up_syms = set(up["symbol"])
    down = down_cand[~down_cand["symbol"].isin(up_syms)].head(top_n).copy()
    # If overlap forced small pool, allow remaining
    if len(down) < top_n:
        down = down_cand.head(top_n).copy()

    up.to_csv(out_dir / "watch_up_top10.csv", index=False)
    down.to_csv(out_dir / "watch_down_top10.csv", index=False)

    # SPY detail
    spy_row = df[df["symbol"] == "SPY"]
    if spy_row.empty:
        spy = {"lean": "CHOP", "confidence": "LOW", "net_score": 0, "price": float("nan")}
    else:
        spy = spy_row.iloc[0].to_dict()
        try:
            daily_spy = lt._load_daily("SPY", data_dir)
            zones_spy = lt.compute_lt_zones(daily_spy, "SPY", include_lvn=False)
            spy = score_spy_detail(spy, daily_spy, zones_spy, near_pct)
        except Exception as e:
            spy["spy_vs_prior_hl"] = f"detail_error:{e}"
            spy["spy_poc_note"] = spy.get("reasons_up") or ""

    asof_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    price_ts = spy.get("price_ts") or spy.get("daily_last") or ""
    asof = f"{asof_ts}; market data last ~ {price_ts}"

    # Charts: SPY + top 2 up + top 2 down
    chart_rels: list[tuple[str, str]] = []
    if not args.no_charts:
        chart_syms: list[str] = ["SPY"]
        for s in list(up["symbol"].head(2)) + list(down["symbol"].head(2)):
            if s not in chart_syms:
                chart_syms.append(s)
        chart_syms = chart_syms[: int(args.max_charts)]
        charts_dir.mkdir(parents=True, exist_ok=True)
        for s in chart_syms:
            try:
                daily = lt._load_daily(s, data_dir)
                zones = lt.compute_lt_zones(daily, s, include_lvn=False)
                bars = lt.load_15m(s, in_dir=in_dir)
                if bars is None or bars.empty:
                    continue
                # last ~8 sessions of 15m if long
                if len(bars) > 26 * 8:
                    bars = bars.iloc[-26 * 8 :].copy()
                png = charts_dir / f"{s}_15m_zones.png"
                note = ""
                hit = df[df["symbol"] == s]
                if not hit.empty:
                    note = f"net={hit.iloc[0]['net_score']:+.1f} {hit.iloc[0]['lean']}/{hit.iloc[0]['confidence']}"
                lt.plot_15m_with_zones(s, bars, zones, png, title_note=note)
                chart_rels.append((s, f"charts/{s}_15m_zones.png"))
                print(f"  chart {png}", flush=True)
            except Exception as e:
                print(f"  [warn] chart {s}: {e}", flush=True)

    write_baseline(out_dir / "BASELINE.md", meta, near_pct, asof)
    write_summary(out_dir / "SUMMARY.md", asof=asof, up=up, down=down, spy=spy, meta=meta)
    write_watch_html(
        out_dir / "watch.html",
        asof=asof,
        up=up,
        down=down,
        spy=spy,
        meta=meta,
        chart_rels=chart_rels,
    )

    # compact JSON for agents
    payload = {
        "asof": asof,
        "spy": {k: spy.get(k) for k in (
            "symbol", "lean", "confidence", "net_score", "price", "price_src",
            "spy_vs_prior_hl", "spy_poc_note", "poc", "yr_pos", "reasons_up", "reasons_down",
            "near_support", "near_resist",
        )},
        "up": up[["symbol", "net_score", "up_score", "down_score", "lean", "confidence", "price", "reasons_up"]].to_dict("records"),
        "down": down[["symbol", "net_score", "up_score", "down_score", "lean", "confidence", "price", "reasons_down"]].to_dict("records"),
        "meta": meta,
    }
    (out_dir / "watch_payload.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    print(f"Wrote {out_dir}", flush=True)
    print(f"SPY: {spy.get('lean')}/{spy.get('confidence')} net={spy.get('net_score')}", flush=True)
    print("UP:", ", ".join(up["symbol"].tolist()), flush=True)
    print("DOWN:", ", ".join(down["symbol"].tolist()), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
