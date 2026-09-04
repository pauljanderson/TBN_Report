#!/usr/bin/env python3
"""Quantitative analysis: long-term daily S/R zones vs 15-minute price action.

Scans BRT new131 + RL59 (or custom universes) where both daily CSV and 1m parquet
exist. Reuses zone defs from tools/lt_zones_daily_to_15m.py (252d H/L, swing
clusters, vec_zones POC/HVN/LVN). Measures proximity rates, 15m touch→bounce vs
break, and forward returns. Charts capped to top findings (appendix only).

Examples:
  python tools/lt_zones_15m_analysis.py
  python tools/lt_zones_15m_analysis.py --max-charts 6 --near-pct 0.015

Research HOLD unless evidence is strong. Not DailyRun-wired.
"""
from __future__ import annotations

import argparse
import html as html_mod
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
_TOOLS = Path(__file__).resolve().parent
_SA = _REPO / "stock_analysis"
for _p in (_SA, _REPO, _TOOLS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from intraday_1m import DEFAULT_1M_DIR  # noqa: E402

# Import zone engine from sibling tool (same freeze)
import lt_zones_daily_to_15m as lt  # noqa: E402

DEFAULT_STAMP = _REPO / "drive" / "paul_experiments" / "lt_zones_15m_analysis_20260824"
DEFAULT_DAILY = _REPO / "data" / "newdata" / "data"
DEFAULT_UNIVERSES = [
    _REPO / "drive" / "universes" / "BRT_new_from_paul_20260822.csv",  # BRT new131
    _REPO / "drive" / "universes" / "RL_universe.csv",  # RL59
]

ZONE_TYPES = ("yearly_high", "yearly_low", "poc", "hvn", "swing_sr", "lvn")
STRONG_TYPES = ("yearly_high", "yearly_low", "poc", "hvn", "swing_sr")
HORIZONS = (4, 8, 16)  # 15m bars → 1h / 2h / 4h

_SORTABLE_TABLE_SCRIPT = lt._SORTABLE_TABLE_SCRIPT


def _sortable_th(label: str, sort_type: str) -> str:
    return lt._sortable_th(label, sort_type)


def _load_universe(path: Path) -> list[str]:
    return lt._load_universe(path)


def resolve_pool(
    univ_paths: list[Path],
    *,
    data_dir: Path,
    in_dir: Path,
) -> tuple[list[str], dict]:
    """Union of universes with both daily CSV and 1m parquet."""
    pool: list[str] = []
    seen: set[str] = set()
    per_univ: dict[str, list[str]] = {}
    for up in univ_paths:
        if not up.is_file():
            per_univ[up.name] = []
            continue
        syms = _load_universe(up)
        per_univ[up.name] = syms
        for s in syms:
            if s not in seen:
                seen.add(s)
                pool.append(s)

    both: list[str] = []
    missing_daily = 0
    missing_1m = 0
    for s in pool:
        has_d = (data_dir / f"{s}.csv").is_file()
        has_1 = (in_dir / f"{s}.parquet").is_file()
        if not has_d:
            missing_daily += 1
        if not has_1:
            missing_1m += 1
        if has_d and has_1:
            both.append(s)

    meta = {
        "universe_files": [p.as_posix() for p in univ_paths],
        "per_univ_n": {k: len(v) for k, v in per_univ.items()},
        "union_n": len(pool),
        "both_daily_1m_n": len(both),
        "missing_daily": missing_daily,
        "missing_1m": missing_1m,
        "overlap_n": len(set(per_univ.get(univ_paths[0].name, [])) & set(per_univ.get(univ_paths[1].name, [])))
        if len(univ_paths) >= 2
        else 0,
    }
    return both, meta


def _bars_arrays(bars: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    o = bars["open"].to_numpy(float) if "open" in bars.columns else bars["Open"].to_numpy(float)
    h = bars["high"].to_numpy(float) if "high" in bars.columns else bars["High"].to_numpy(float)
    l = bars["low"].to_numpy(float) if "low" in bars.columns else bars["Low"].to_numpy(float)
    c = bars["close"].to_numpy(float) if "close" in bars.columns else bars["Close"].to_numpy(float)
    return o, h, l, c


def _visit_starts(intersect: np.ndarray) -> np.ndarray:
    """Indices where intersection turns True after False (or bar 0)."""
    if len(intersect) == 0:
        return np.array([], dtype=int)
    prev = np.roll(intersect, 1)
    prev[0] = False
    return np.flatnonzero(intersect & ~prev)


def classify_touch_outcomes(
    bars: pd.DataFrame,
    zones: list[lt.Zone],
    *,
    horizons: Iterable[int] = HORIZONS,
    min_bars: int = 40,
) -> list[dict]:
    """Detect 15m zone visits; score bounce vs break + forward return by horizon."""
    if bars is None or bars.empty or len(bars) < min_bars or not zones:
        return []
    _o, h, l, c = _bars_arrays(bars)
    n = len(c)
    rows: list[dict] = []
    hs = [int(x) for x in horizons]

    for z in zones:
        if z.zone_type not in ZONE_TYPES:
            continue
        lo, hi, mid = float(z.lo), float(z.hi), float(z.mid)
        if not (np.isfinite(lo) and np.isfinite(hi) and hi >= lo and mid > 0):
            continue
        intersect = (h >= lo) & (l <= hi)
        starts = _visit_starts(intersect)
        for i in starts:
            if i < 1 or i >= n - 1:
                continue
            # Need room for longest horizon
            if i + max(hs) >= n:
                continue
            prior = float(c[i - 1])
            if prior < lo:
                side = "resistance"  # approached from below
            elif prior > hi:
                side = "support"  # approached from above
            else:
                side = "inside"

            touch_px = float(c[i])
            for H in hs:
                j = i + H
                fwd_close = float(c[j])
                fwd_ret = (fwd_close / touch_px - 1.0) * 100.0
                # signed for "favorable" direction: support wants up, resistance wants down
                if side == "support":
                    fav_ret = fwd_ret
                    broke = bool(np.any(c[i : j + 1] < lo))
                    bounced = (not broke) and (fwd_close > mid)
                elif side == "resistance":
                    fav_ret = -fwd_ret
                    broke = bool(np.any(c[i : j + 1] > hi))
                    bounced = (not broke) and (fwd_close < mid)
                else:
                    fav_ret = abs(fwd_ret) * 0.0  # neutral / skip ranking
                    broke = bool(np.any(c[i : j + 1] < lo) or np.any(c[i : j + 1] > hi))
                    bounced = False

                if side == "inside":
                    outcome = "inside_ambiguous"
                elif broke:
                    outcome = "break"
                elif bounced:
                    outcome = "bounce"
                else:
                    outcome = "neutral"

                rows.append(
                    {
                        "symbol": z.symbol,
                        "zone_type": z.zone_type,
                        "side": side,
                        "outcome": outcome,
                        "horizon_bars": H,
                        "touch_i": int(i),
                        "touch_px": touch_px,
                        "zone_mid": mid,
                        "zone_lo": lo,
                        "zone_hi": hi,
                        "fwd_ret_pct": fwd_ret,
                        "fav_ret_pct": fav_ret if side != "inside" else float("nan"),
                        "confluence": z.confluence or "",
                        "strength": float(z.strength),
                        "touches_daily": int(z.touches),
                    }
                )
    return rows


def proximity_rows(
    symbol: str,
    price: float,
    zones: list[lt.Zone],
    near_pct: float,
) -> list[dict]:
    rows = []
    for z in zones:
        if z.lo <= price <= z.hi:
            d = 0.0
        else:
            d = min(abs(price - z.lo), abs(price - z.hi)) / max(price, 1e-9)
        rows.append(
            {
                "symbol": symbol,
                "zone_type": z.zone_type,
                "mid": z.mid,
                "lo": z.lo,
                "hi": z.hi,
                "dist_pct": d * 100.0,
                "near": d <= near_pct,
                "confluence": z.confluence or "",
                "strength": z.strength,
                "touches": z.touches,
            }
        )
    return rows


def aggregate_proximity(prox: pd.DataFrame, symbols_n: int) -> pd.DataFrame:
    rows = []
    for zt in ZONE_TYPES:
        sub = prox[prox["zone_type"] == zt]
        if sub.empty:
            rows.append(
                {
                    "zone_type": zt,
                    "symbols_with_type": 0,
                    "near_hits": 0,
                    "near_rate_pct": 0.0,
                    "median_dist_pct": float("nan"),
                    "p25_dist_pct": float("nan"),
                    "p75_dist_pct": float("nan"),
                }
            )
            continue
        # nearest zone of this type per symbol
        nearest = sub.sort_values("dist_pct").groupby("symbol", as_index=False).first()
        near_hits = int(nearest["near"].sum())
        rows.append(
            {
                "zone_type": zt,
                "symbols_with_type": int(nearest["symbol"].nunique()),
                "near_hits": near_hits,
                "near_rate_pct": 100.0 * near_hits / max(symbols_n, 1),
                "median_dist_pct": float(nearest["dist_pct"].median()),
                "p25_dist_pct": float(nearest["dist_pct"].quantile(0.25)),
                "p75_dist_pct": float(nearest["dist_pct"].quantile(0.75)),
            }
        )
    return pd.DataFrame(rows)


def aggregate_outcomes(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(
            columns=[
                "zone_type",
                "horizon_bars",
                "n_events",
                "n_support",
                "n_resistance",
                "bounce_n",
                "break_n",
                "neutral_n",
                "bounce_rate_pct",
                "break_rate_pct",
                "median_fwd_ret_pct",
                "median_fav_ret_pct",
                "mean_fav_ret_pct",
            ]
        )
    # Only directional approaches
    dir_ev = events[events["side"].isin(["support", "resistance"])].copy()
    rows = []
    for zt in ZONE_TYPES:
        for H in HORIZONS:
            sub = dir_ev[(dir_ev["zone_type"] == zt) & (dir_ev["horizon_bars"] == H)]
            if sub.empty:
                continue
            bounce_n = int((sub["outcome"] == "bounce").sum())
            break_n = int((sub["outcome"] == "break").sum())
            neutral_n = int((sub["outcome"] == "neutral").sum())
            n = len(sub)
            rows.append(
                {
                    "zone_type": zt,
                    "horizon_bars": H,
                    "n_events": n,
                    "n_support": int((sub["side"] == "support").sum()),
                    "n_resistance": int((sub["side"] == "resistance").sum()),
                    "bounce_n": bounce_n,
                    "break_n": break_n,
                    "neutral_n": neutral_n,
                    "bounce_rate_pct": 100.0 * bounce_n / n,
                    "break_rate_pct": 100.0 * break_n / n,
                    "median_fwd_ret_pct": float(sub["fwd_ret_pct"].median()),
                    "median_fav_ret_pct": float(sub["fav_ret_pct"].median()),
                    "mean_fav_ret_pct": float(sub["fav_ret_pct"].mean()),
                }
            )
    return pd.DataFrame(rows)


def rank_zone_types(prox_agg: pd.DataFrame, out_agg: pd.DataFrame, *, primary_h: int = 8) -> pd.DataFrame:
    """Composite research rank: bounce−break edge at primary horizon + near rate context."""
    rows = []
    out_h = out_agg[out_agg["horizon_bars"] == primary_h] if not out_agg.empty else out_agg
    for zt in ZONE_TYPES:
        p = prox_agg[prox_agg["zone_type"] == zt]
        o = out_h[out_h["zone_type"] == zt] if not out_h.empty else pd.DataFrame()
        near_rate = float(p["near_rate_pct"].iloc[0]) if len(p) else 0.0
        med_dist = float(p["median_dist_pct"].iloc[0]) if len(p) else float("nan")
        if len(o):
            bounce = float(o["bounce_rate_pct"].iloc[0])
            brk = float(o["break_rate_pct"].iloc[0])
            n_ev = int(o["n_events"].iloc[0])
            med_fav = float(o["median_fav_ret_pct"].iloc[0])
            edge = bounce - brk
        else:
            bounce = brk = med_fav = float("nan")
            n_ev = 0
            edge = float("nan")
        # Score: favor bounce edge with enough N; near_rate is descriptive only
        score = edge if np.isfinite(edge) and n_ev >= 20 else (edge * 0.5 if np.isfinite(edge) else -999.0)
        rows.append(
            {
                "zone_type": zt,
                "rank_score": score,
                "bounce_minus_break_pp": edge,
                "bounce_rate_pct": bounce,
                "break_rate_pct": brk,
                "n_events_h8": n_ev,
                "median_fav_ret_pct_h8": med_fav,
                "near_rate_pct": near_rate,
                "median_dist_pct": med_dist,
            }
        )
    df = pd.DataFrame(rows).sort_values("rank_score", ascending=False).reset_index(drop=True)
    df.insert(0, "rank", np.arange(1, len(df) + 1))
    return df


def pick_chart_symbols(
    prox: pd.DataFrame,
    events: pd.DataFrame,
    *,
    max_charts: int,
    near_pct: float,
) -> list[tuple[str, str]]:
    """Pick diverse top findings: near yearly, near POC/HVN, strong bounce examples."""
    picks: list[tuple[str, str]] = []
    used: set[str] = set()

    def add(sym: str, reason: str) -> None:
        if sym in used or len(picks) >= max_charts:
            return
        used.add(sym)
        picks.append((sym, reason))

    # Nearest yearly extremes
    for zt in ("yearly_high", "yearly_low"):
        sub = prox[(prox["zone_type"] == zt) & (prox["near"])].sort_values("dist_pct")
        for _, r in sub.head(3).iterrows():
            add(str(r["symbol"]), f"near {zt} ({r['dist_pct']:.2f}%)")

    # Near POC / HVN
    for zt in ("poc", "hvn"):
        sub = prox[(prox["zone_type"] == zt) & (prox["near"])].sort_values("dist_pct")
        for _, r in sub.head(2).iterrows():
            add(str(r["symbol"]), f"near {zt} ({r['dist_pct']:.2f}%)")

    # Bounce-heavy symbols at H=8 (if events exist)
    if not events.empty:
        h8 = events[(events["horizon_bars"] == 8) & (events["side"].isin(["support", "resistance"]))]
        if not h8.empty:
            g = (
                h8.assign(is_bounce=(h8["outcome"] == "bounce").astype(int))
                .groupby(["symbol", "zone_type"], as_index=False)
                .agg(n=("outcome", "size"), bounce_n=("is_bounce", "sum"), med_fav=("fav_ret_pct", "median"))
            )
            g = g[g["n"] >= 2].sort_values(["bounce_n", "med_fav"], ascending=[False, False])
            for _, r in g.head(8).iterrows():
                add(str(r["symbol"]), f"15m bounce sample {r['zone_type']} ({int(r['bounce_n'])}/{int(r['n'])})")

    # Fill with closest overall strong-type near hits
    strong_near = prox[prox["zone_type"].isin(STRONG_TYPES) & prox["near"]].sort_values("dist_pct")
    for _, r in strong_near.iterrows():
        add(str(r["symbol"]), f"near {r['zone_type']} ({r['dist_pct']:.2f}%)")
        if len(picks) >= max_charts:
            break

    return picks[:max_charts]


def write_baseline(path: Path, meta: dict, near_pct: float) -> None:
    text = f"""# LT daily zones on 15m — quantitative analysis baseline

**Stamp:** `lt_zones_15m_analysis_20260824`  
**Date:** 2026-08-24  
**Status:** Research analysis — **HOLD** unless bounce/break evidence is strong and replicated. **Not** gold. **Not** DailyRun-wired.

Prior stamp `lt_zones_15m_examples_20260823` was an **examples gallery**. This stamp is the **full quantitative scan**.

---

## Frozen definitions (same engine as `tools/lt_zones_daily_to_15m.py`)

### 1) Yearly high / low (rolling 252 trading days)

- `yearly_high` = max(High) over last **252** daily bars (not calendar YTD)
- `yearly_low` = min(Low) over last 252 daily bars
- Band: ±0.25% of level, or ~0.15×ATR14 if larger

### 2) Multi-touch swing S/R

- Fractal pivots `k=3`; cluster within **0.75%**; keep clusters with **≥3** touches
- Lookback up to 504 daily bars; max ~6 swing zones kept

### 3) Volume profile: Point of Control (POC) / High-Volume Node (HVN) / Low-Volume Node (LVN)

- Reuse `stock_analysis/vec_zones.py`: `VP_LOOKBACK=60`, `VP_BIN_PCT=0.005`, HVN ≥50% of POC bin, LVN valleys &lt;20% of POC
- This analysis includes **LVN** for completeness (charts still prioritize stronger types)

### Carry-forward

Zones are computed **as-of the last daily bar** and painted as horizontal bands on the available 15-minute window (1m resampled). No intraday zone rebuild within the 15m window (research simplification; daily levels treated as sticky).

### Near-threshold

A symbol is **near** a zone when distance from last daily close to the band is ≤ **{near_pct*100:.2f}%** of price (0 = inside band).

---

## Universe

| Source | Path | N (file) |
|--------|------|----------|
| BRT new131 | `drive/universes/BRT_new_from_paul_20260822.csv` | {meta.get('per_univ_n', {}).get('BRT_new_from_paul_20260822.csv', '?')} |
| RL59 | `drive/universes/RL_universe.csv` | {meta.get('per_univ_n', {}).get('RL_universe.csv', '?')} |
| Union | — | {meta.get('union_n', '?')} |
| Overlap | — | {meta.get('overlap_n', '?')} |
| **Analyzed (daily+1m)** | — | **{meta.get('both_daily_1m_n', '?')}** |

Missing daily among union: {meta.get('missing_daily', '?')}; missing 1m: {meta.get('missing_1m', '?')}.

---

## 15m touch → bounce / break (frozen)

- **Touch / visit start:** 15m bar intersects zone band `[lo, hi]`, and prior bar did not.
- **Side:** prior close &lt; lo → resistance test; prior close &gt; hi → support test; else inside/ambiguous (excluded from bounce rates).
- **Horizons:** 4 / 8 / 16 bars (1h / 2h / 4h on 15m).
- **Break:** any close beyond the far side of the band within the horizon.
- **Bounce:** no break and horizon close on the “favorable” side of zone mid (support → above mid; resistance → below mid).
- **Forward return:** close-to-close % from touch bar; **fav_ret** flips sign for resistance so “positive = zone held.”

Primary ranking horizon: **8 bars (2h)**.

---

## Data limits

- Yahoo / local 1m store is typically **~days to ~weeks**, not months. Many names have only ~1 RTH week of 15m bars → **small event N**, regime-sensitive.
- Zones are long-term daily; the 15m window is a short overlay. Do not treat bounce rates as a multi-year edge.
- Selection: ranking zone types after seeing full-table results is **in-sample**. OOS / walk-forward not run here.
- No trade system, sizing, or DailyRun wire.

---

## Freeze knobs

| Knob | Value |
|------|-------|
| Yearly window | 252d |
| Pivot k / cluster / min touches | 3 / 0.75% / 3 |
| VP | vec_zones defaults |
| Near % | {near_pct*100:.2f}% |
| Touch horizons | 4 / 8 / 16 × 15m |
| Include LVN in metrics | yes |
| Max appendix charts | capped (tool `--max-charts`) |

**Verdict default:** research **HOLD**. Promote only with wider history / walk-forward and quality (not count) confirmation.
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_analysis_html(
    out_path: Path,
    *,
    stamp_name: str,
    meta: dict,
    prox_agg: pd.DataFrame,
    out_agg: pd.DataFrame,
    rank_df: pd.DataFrame,
    chart_meta: list[dict],
    verdict: str,
    near_pct: float,
    n_symbols: int,
    n_events: int,
    bars_summary: dict,
) -> None:
    def tbl(df: pd.DataFrame, col_specs: list[tuple[str, str, str]]) -> str:
        """col_specs: (df_col, header, sort_type)"""
        head = "".join(_sortable_th(h, t) for _, h, t in col_specs)
        body = []
        for _, r in df.iterrows():
            cells = []
            for col, _, typ in col_specs:
                v = r.get(col, "")
                if pd.isna(v):
                    cells.append("<td>—</td>")
                elif typ == "num" and isinstance(v, (int, float, np.integer, np.floating)):
                    fv = float(v)
                    if abs(fv - round(fv)) < 1e-9 and abs(fv) >= 1:
                        cells.append(f"<td>{int(round(fv))}</td>")
                    else:
                        cells.append(f"<td>{fv:.2f}</td>")
                else:
                    cells.append(f"<td>{html_mod.escape(str(v))}</td>")
            body.append("<tr>" + "".join(cells) + "</tr>")
        return (
            f'<table class="sortable"><thead><tr>{head}</tr></thead>'
            f"<tbody>{''.join(body)}</tbody></table>"
        )

    # Format helpers for display frames
    prox_show = prox_agg.copy()
    out_show = out_agg.copy()
    rank_show = rank_df.copy()

    prox_table = tbl(
        prox_show,
        [
            ("zone_type", "Zone type", "text"),
            ("symbols_with_type", "Symbols w/ type", "num"),
            ("near_hits", "Near hits", "num"),
            ("near_rate_pct", "Near rate %", "num"),
            ("median_dist_pct", "Median dist %", "num"),
            ("p25_dist_pct", "P25 dist %", "num"),
            ("p75_dist_pct", "P75 dist %", "num"),
        ],
    )
    out_table = tbl(
        out_show,
        [
            ("zone_type", "Zone type", "text"),
            ("horizon_bars", "Horizon (bars)", "num"),
            ("n_events", "N events", "num"),
            ("n_support", "N support", "num"),
            ("n_resistance", "N resist", "num"),
            ("bounce_rate_pct", "Bounce %", "num"),
            ("break_rate_pct", "Break %", "num"),
            ("neutral_n", "Neutral N", "num"),
            ("median_fwd_ret_pct", "Med fwd ret %", "num"),
            ("median_fav_ret_pct", "Med fav ret %", "num"),
            ("mean_fav_ret_pct", "Mean fav ret %", "num"),
        ],
    )
    rank_table = tbl(
        rank_show,
        [
            ("rank", "Rank", "num"),
            ("zone_type", "Zone type", "text"),
            ("bounce_minus_break_pp", "Bounce−break pp (H8)", "num"),
            ("bounce_rate_pct", "Bounce %", "num"),
            ("break_rate_pct", "Break %", "num"),
            ("n_events_h8", "N events H8", "num"),
            ("median_fav_ret_pct_h8", "Med fav ret %", "num"),
            ("near_rate_pct", "Near rate %", "num"),
            ("median_dist_pct", "Med dist %", "num"),
            ("rank_score", "Score", "num"),
        ],
    )

    cards = []
    for cm in chart_meta:
        rel = cm.get("chart_rel", "")
        if not rel:
            continue
        cards.append(
            f'<figure class="card">'
            f'<figcaption><strong>{html_mod.escape(cm["symbol"])}</strong> — '
            f'{html_mod.escape(cm.get("reason", ""))}</figcaption>'
            f'<a href="{html_mod.escape(rel)}">'
            f'<img src="{html_mod.escape(rel)}" alt="{html_mod.escape(cm["symbol"])} 15m LT zones" loading="lazy"/>'
            f"</a></figure>"
        )

    univ_bits = ", ".join(f"{k}={v}" for k, v in (meta.get("per_univ_n") or {}).items())
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>LT zones 15m Analysis — {html_mod.escape(stamp_name)}</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1rem; color: #1a2332; background: #f4f6f8; }}
h1 {{ font-size: 1.4rem; margin: 0 0 0.35rem; }}
h2 {{ font-size: 1.1rem; margin-top: 1.4rem; }}
.sub {{ color: #546e7a; font-size: 0.92rem; margin-bottom: 1rem; }}
.note {{ background: #fff3e0; border-left: 4px solid #ef6c00; padding: 0.65rem 0.85rem; margin: 1rem 0; font-size: 0.9rem; }}
.hold {{ background: #eceff1; border-left: 4px solid #546e7a; padding: 0.65rem 0.85rem; margin: 1rem 0; font-size: 0.9rem; }}
table.sortable {{ border-collapse: collapse; width: 100%; background: #fff; font-size: 0.86rem; margin: 0.5rem 0 1rem; }}
th, td {{ border: 1px solid #e0e0e0; padding: 0.35rem 0.5rem; text-align: left; }}
th.sortable-th {{ cursor: pointer; user-select: none; white-space: nowrap; background: #e3f2fd; }}
th.sortable-th:hover {{ background: #bbdefb; }}
th.sortable-th .sort-ind::after {{ content: " \\2195"; opacity: 0.35; font-size: 0.75em; }}
th.sortable-th.sort-asc .sort-ind::after {{ content: " \\25B2"; opacity: 0.8; }}
th.sortable-th.sort-desc .sort-ind::after {{ content: " \\25BC"; opacity: 0.8; }}
.gallery {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; margin-top: 0.75rem; }}
.card {{ background: #fff; margin: 0; padding: 0.5rem; border: 1px solid #eee; }}
.card img {{ width: 100%; height: auto; display: block; }}
.card figcaption {{ font-size: 0.85rem; margin-bottom: 0.4rem; }}
code {{ background: #eee; padding: 0.05rem 0.25rem; border-radius: 3px; }}
@media (max-width: 640px) {{
  body {{ margin: 0.6rem; }}
  table.sortable {{ display: block; overflow-x: auto; -webkit-overflow-scrolling: touch; }}
}}
</style>
</head>
<body>
<h1>LT daily zones on 15m — Analysis</h1>
<p class="sub">Stamp <code>{html_mod.escape(stamp_name)}</code> · Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")} · Click column headers to sort</p>
<div class="hold"><strong>Verdict: {html_mod.escape(verdict)}</strong> — Research only. Not gold. Not DailyRun-wired. Short 15m history limits confidence.</div>
<div class="note">
<strong>Universe:</strong> BRT new131 + RL59 → union {meta.get('union_n')}, overlap {meta.get('overlap_n')}, analyzed with daily+1m <strong>{n_symbols}</strong> ({univ_bits}).
Near threshold ≤ {near_pct*100:.2f}%. Directional touch events (all horizons rows): {n_events}.
Median 15m bars/symbol: {bars_summary.get('median_bars', '—')}; p10–p90: {bars_summary.get('p10_bars', '—')}–{bars_summary.get('p90_bars', '—')}.
</div>

<h2>1. Zone-type rank (primary H=8 / 2h)</h2>
<p class="sub">Ranked by bounce% − break% at 8 bars (support/resistance approaches only). Low N → treat as provisional.</p>
{rank_table}

<h2>2. Proximity rates by zone type</h2>
<p class="sub">Share of scanned symbols whose last daily close is within {near_pct*100:.2f}% of at least one zone of that type (nearest zone per type).</p>
{prox_table}

<h2>3. Touch → bounce vs break + forward returns</h2>
<p class="sub">Visit starts on 15m; horizons 4/8/16 bars. Fav ret = signed so positive means zone held.</p>
{out_table}

<h2>Appendix — charts (top findings only)</h2>
<p class="sub">Capped visual appendix; full metrics are in the tables above and CSVs.</p>
<div class="gallery">
{''.join(cards) if cards else '<p>No charts generated.</p>'}
</div>
{_SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")


def decide_verdict(rank_df: pd.DataFrame, out_agg: pd.DataFrame) -> str:
    """Default HOLD; LEAN KEEP only if clear bounce edge with adequate N.

    Yearly H/L often show near-100% 'bounce' in a short 15m window simply because
    252d breakouts are rare over a few sessions — treat that as mechanical, not edge.
    """
    if rank_df.empty or out_agg.empty:
        return "HOLD (insufficient 15m evidence)"

    # Prefer multi-touch / VP types for promotion bar (not yearly extremes alone)
    candidates = rank_df[~rank_df["zone_type"].isin(["yearly_high", "yearly_low"])]
    if candidates.empty:
        return "HOLD (only yearly extremes scored — mechanical in short window)"

    top = candidates.iloc[0]
    edge = top.get("bounce_minus_break_pp")
    n = int(top.get("n_events_h8") or 0)
    med_fav = top.get("median_fav_ret_pct_h8")
    brk = top.get("break_rate_pct")
    # Suspicious: almost no breaks → definition/window artifact
    if np.isfinite(brk) and float(brk) < 5.0:
        return "HOLD (near-zero break rate looks mechanical — do not promote)"
    if (
        n >= 200
        and np.isfinite(edge)
        and float(edge) >= 20.0
        and np.isfinite(med_fav)
        and float(med_fav) > 0.05
    ):
        return "LEAN KEEP (provisional — still research-only; short 15m window)"
    return "HOLD (mixed / thin 15m sample — do not promote)"


def run_analysis(
    *,
    univ_paths: list[Path],
    data_dir: Path,
    in_dir: Path,
    out_dir: Path,
    near_pct: float,
    max_charts: int,
    include_lvn: bool,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    both, meta = resolve_pool(univ_paths, data_dir=data_dir, in_dir=in_dir)
    print(
        f"Pool: union={meta['union_n']} both_daily_1m={meta['both_daily_1m_n']} "
        f"per_univ={meta['per_univ_n']}",
        flush=True,
    )

    prox_rows: list[dict] = []
    event_rows: list[dict] = []
    bar_counts: list[int] = []
    zones_by_sym: dict[str, list[lt.Zone]] = {}
    daily_close: dict[str, float] = {}
    errors: list[dict] = []

    for i, sym in enumerate(both, 1):
        try:
            daily = lt._load_daily(sym, data_dir)
            if len(daily) < 60:
                errors.append({"symbol": sym, "error": "daily_lt_60"})
                continue
            zones = lt.compute_lt_zones(daily, sym, include_lvn=include_lvn)
            zones_by_sym[sym] = zones
            px = float(daily.iloc[-1]["Close"])
            daily_close[sym] = px
            prox_rows.extend(proximity_rows(sym, px, zones, near_pct))

            bars = lt.load_15m(sym, in_dir)
            if bars is None or bars.empty:
                errors.append({"symbol": sym, "error": "no_15m"})
                continue
            bar_counts.append(len(bars))
            # Include LVN in metrics; strong types already in zones
            event_rows.extend(classify_touch_outcomes(bars, zones))
        except Exception as e:  # noqa: BLE001
            errors.append({"symbol": sym, "error": str(e)[:200]})
        if i % 25 == 0 or i == len(both):
            print(f"  scanned {i}/{len(both)} … events so far {len(event_rows)}", flush=True)

    prox = pd.DataFrame(prox_rows)
    events = pd.DataFrame(event_rows)
    n_sym = len(daily_close)

    prox_agg = aggregate_proximity(prox, n_sym) if not prox.empty else aggregate_proximity(pd.DataFrame(columns=["zone_type", "symbol", "dist_pct", "near"]), n_sym)
    out_agg = aggregate_outcomes(events)
    rank_df = rank_zone_types(prox_agg, out_agg)

    bars_summary = {
        "median_bars": float(np.median(bar_counts)) if bar_counts else float("nan"),
        "p10_bars": float(np.percentile(bar_counts, 10)) if bar_counts else float("nan"),
        "p90_bars": float(np.percentile(bar_counts, 90)) if bar_counts else float("nan"),
        "symbols_with_15m": len(bar_counts),
    }

    # Persist tables
    prox.to_csv(out_dir / "proximity_by_symbol_zone.csv", index=False)
    prox_agg.to_csv(out_dir / "proximity_by_type.csv", index=False)
    if not events.empty:
        # Keep a lean events file (can be large)
        events.to_csv(out_dir / "touch_events_15m.csv", index=False)
    out_agg.to_csv(out_dir / "bounce_break_by_type.csv", index=False)
    rank_df.to_csv(out_dir / "zone_type_rank.csv", index=False)
    pd.DataFrame(errors).to_csv(out_dir / "scan_errors.csv", index=False)
    pd.DataFrame([{"symbol": s, "close": daily_close[s], "zones_n": len(zones_by_sym.get(s, []))} for s in sorted(daily_close)]).to_csv(
        out_dir / "symbols_scanned.csv", index=False
    )

    write_baseline(out_dir / "BASELINE.md", meta, near_pct)

    # Charts — appendix only, capped
    picks = pick_chart_symbols(prox, events, max_charts=max_charts, near_pct=near_pct)
    chart_meta: list[dict] = []
    charts_dir = out_dir / "charts"
    zones_dir = out_dir / "zones"
    for sym, reason in picks:
        try:
            zones = zones_by_sym.get(sym) or lt.compute_lt_zones(lt._load_daily(sym, data_dir), sym, include_lvn=include_lvn)
            zdf = lt.zones_to_frame(zones)
            zones_dir.mkdir(parents=True, exist_ok=True)
            zpath = zones_dir / f"{sym}_lt_zones.csv"
            zdf.to_csv(zpath, index=False)
            bars = lt.load_15m(sym, in_dir)
            if bars.empty:
                continue
            png = charts_dir / f"{sym}_15m_lt_zones.png"
            lt.plot_15m_with_zones(sym, bars, zones, png, title_note=reason[:60])
            chart_meta.append(
                {
                    "symbol": sym,
                    "reason": reason,
                    "chart_rel": f"charts/{png.name}",
                    "csv_rel": f"zones/{zpath.name}",
                }
            )
            print(f"chart {sym}: {reason}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] chart {sym}: {e}", flush=True)

    pd.DataFrame(chart_meta).to_csv(out_dir / "appendix_charts.csv", index=False)

    verdict = decide_verdict(rank_df, out_agg)
    n_events_dir = (
        int(len(events[events["side"].isin(["support", "resistance"])])) if not events.empty else 0
    )
    write_analysis_html(
        out_dir / "analysis.html",
        stamp_name=out_dir.name,
        meta=meta,
        prox_agg=prox_agg,
        out_agg=out_agg,
        rank_df=rank_df,
        chart_meta=chart_meta,
        verdict=verdict,
        near_pct=near_pct,
        n_symbols=n_sym,
        n_events=n_events_dir,
        bars_summary=bars_summary,
    )
    print(f"Wrote {out_dir / 'analysis.html'} verdict={verdict}", flush=True)
    return {
        "out_dir": out_dir,
        "verdict": verdict,
        "n_symbols": n_sym,
        "meta": meta,
        "rank_df": rank_df,
        "prox_agg": prox_agg,
        "out_agg": out_agg,
        "bars_summary": bars_summary,
        "n_charts": len(chart_meta),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="LT daily zones × 15m quantitative analysis")
    ap.add_argument("--universe", action="append", default=[], help="Universe CSV (repeatable)")
    ap.add_argument("--data-dir", default=str(DEFAULT_DAILY))
    ap.add_argument("--in-dir", default=str(DEFAULT_1M_DIR))
    ap.add_argument("--out-dir", default=str(DEFAULT_STAMP))
    ap.add_argument("--near-pct", type=float, default=0.015)
    ap.add_argument("--max-charts", type=int, default=6)
    ap.add_argument("--no-lvn", action="store_true", help="Exclude LVN from zone set")
    args = ap.parse_args()

    univ = [Path(p) for p in args.universe] if args.universe else list(DEFAULT_UNIVERSES)
    run_analysis(
        univ_paths=univ,
        data_dir=Path(args.data_dir),
        in_dir=Path(args.in_dir),
        out_dir=Path(args.out_dir),
        near_pct=float(args.near_pct),
        max_charts=int(args.max_charts),
        include_lvn=not bool(args.no_lvn),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
