#!/usr/bin/env python3
"""Scalp x HL volume-zone break->reenter->continue / touches / LVN+HVN (research).

Observational only. Short Yahoo 1m window. Not gold. Not DailyRun.

  python tools/scalp_zone_retest_lvn_hvn_ab.py
  python tools/scalp_zone_retest_lvn_hvn_ab.py --limit-syms 40
"""
from __future__ import annotations

import argparse
import csv
import html as html_lib
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "stock_analysis"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import scalp_filtered_timestop_ab as filt  # noqa: E402
import scalp_open15_reversal_ab as ab  # noqa: E402
from compare_format import format_money  # noqa: E402
from intraday_1m import DEFAULT_1M_DIR, ET, read_1m, resample_ohlcv  # noqa: E402
from vec_zones import VP_BIN_PCT, VP_LOOKBACK, DailyVolumeProfile, compute_volume_profile  # noqa: E402
from vol_zone_break_retest import Zone, build_zones, detect_touches, load_ohlcv  # noqa: E402

DRIVE = ROOT / "drive"
DATA_DIR = ROOT / "data" / "newdata" / "data"
DEFAULT_STAMP = "scalp_zone_retest_lvn_hvn_20260823"
DEFAULT_SOURCE = "scalp_full_levers_20260822"
SYSTEM = "scalp"

LOOKBACK_DAYS = 126
ZONE_KIND = "HL"
RETEST_EPS = 0.005
APPROACH_LB = 5

SORT_CSS = """
th.sortable-th{cursor:pointer;user-select:none;white-space:nowrap}
th.sortable-th:hover{background:#e2e8f0}
th.sortable-th .sort-ind::after{content:" \\2195";opacity:.35;font-size:.85em}
th.sortable-th.sort-asc .sort-ind::after{content:" \\2191";opacity:.9}
th.sortable-th.sort-desc .sort-ind::after{content:" \\2193";opacity:.9}
@media (max-width:720px){body{font-size:14px}table.sortable{display:block;overflow-x:auto;-webkit-overflow-scrolling:touch}}
"""
SORT_JS = r"""
<script>
(function(){
  function parseVal(text,type){
    var s=String(text||"").trim();
    if(!s||s==="-"||s==="—")return type==="text"?"":0;
    if(type==="text")return s.toUpperCase();
    if(type==="date"){var m=s.match(/(\d{4})-(\d{2})-(\d{2})/);return m?parseInt(m[1]+m[2]+m[3],10):0;}
    var v=parseFloat(s.replace(/[$,%+]/g,"").replace(/,/g,""));
    return Number.isFinite(v)?v:0;
  }
  function sortTable(table,col,type,dir){
    var tb=table.tBodies[0]; if(!tb)return;
    var rows=Array.from(tb.querySelectorAll("tr"));
    var pin=rows.filter(function(r){return r.classList.contains("total-row");});
    var mov=rows.filter(function(r){return !r.classList.contains("total-row");});
    mov.sort(function(a,b){
      var av=parseVal(a.cells[col]&&a.cells[col].textContent,type);
      var bv=parseVal(b.cells[col]&&b.cells[col].textContent,type);
      if(typeof av==="string"||typeof bv==="string")return dir*String(av).localeCompare(String(bv));
      return dir*(av-bv);
    });
    mov.concat(pin).forEach(function(r){tb.appendChild(r);});
  }
  document.querySelectorAll("table.sortable").forEach(function(table){
    var ths=table.querySelectorAll("th.sortable-th");
    ths.forEach(function(th,idx){
      function go(){
        var type=th.getAttribute("data-sort")||"text";
        var asc=!th.classList.contains("sort-asc");
        ths.forEach(function(x){x.classList.remove("sort-asc","sort-desc");});
        th.classList.add(asc?"sort-asc":"sort-desc");
        sortTable(table,idx,type,asc?1:-1);
      }
      th.addEventListener("click",go);
      th.addEventListener("keydown",function(e){if(e.key==="Enter"||e.key===" "){e.preventDefault();go();}});
    });
  });
})();
</script>
"""


def th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{html_lib.escape(sort_type)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_lib.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def fmt_num(v: Any, nd: int = 2) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    if isinstance(v, float) and abs(v) == float("inf"):
        return "inf"
    try:
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return str(v)


def winner_user(t: dict[str, Any]) -> bool:
    return (
        str(t.get("entirely_out") or "") == "entirely_out"
        and str(t.get("range_atr_bucket") or "") == "40_60pct"
        and filt.passes_shape_side(t)
    )


def winner_full(t: dict[str, Any]) -> bool:
    return filt.passes_shared_filters(t) and filt.passes_shape_side(t)


def touch_bucket(n: int) -> str:
    if n <= 0:
        return "0"
    if n >= 4:
        return "4+"
    return str(n)


@dataclass
class Hit:
    hit: bool
    zone_id: str = ""
    zone_lo: float = float("nan")
    zone_hi: float = float("nan")
    touches: int = 0
    pattern: str = ""


def scan_pattern(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    zlo: float,
    zhi: float,
    *,
    bias: str,
    eps: float = RETEST_EPS,
) -> bool:
    band_lo = float(zlo) * (1.0 - eps)
    band_hi = float(zhi) * (1.0 + eps)
    state = "none"
    for i in range(len(closes)):
        lo, hi, cl = float(lows[i]), float(highs[i]), float(closes[i])
        intersects = lo <= band_hi and hi >= band_lo
        if bias == "lower":
            broke = lo < float(zlo) or cl < float(zlo)
            cont = broke
        else:
            broke = hi > float(zhi) or cl > float(zhi)
            cont = broke
        if state == "none":
            if broke:
                state = "broken"
        elif state == "broken":
            if intersects:
                state = "reentered"
        elif state == "reentered" and cont:
            return True
    return False


def visits_before(df: pd.DataFrame, zone: Zone, asof: int) -> int:
    touches = detect_touches(df, zone, approach_lookback=APPROACH_LB, eps_pct=RETEST_EPS)
    return len({t.visit_id for t in touches if t.bar_idx <= asof})


def lvn_hvn(
    hi: np.ndarray,
    lo: np.ndarray,
    cl: np.ndarray,
    vol: np.ndarray,
    asof: int,
    zlo: float,
    zhi: float,
    cache: dict[int, Optional[DailyVolumeProfile]],
) -> str:
    if asof not in cache:
        cache[asof] = compute_volume_profile(
            hi, lo, cl, vol, asof, lookback=VP_LOOKBACK, bin_pct=VP_BIN_PCT
        )
    prof = cache[asof]
    if prof is None:
        return "no_profile"
    hvn = bool(prof.overlaps_hvn_or_poc(zlo, zhi))
    lvn = bool(prof.crosses_lvn(zlo, zhi))
    if hvn and lvn:
        return "lvn+hvn"
    if hvn:
        return "hvn_only"
    if lvn:
        return "lvn_only"
    return "neither"


def active_zones(zones: list[Zone], asof: int, *, carry: bool) -> list[Zone]:
    out: list[Zone] = []
    for z in zones:
        if z.kind != ZONE_KIND or z.created_on_idx > asof:
            continue
        if carry:
            if asof <= z.last_winner_idx:
                out.append(z)
        elif z.created_on_idx == asof:
            out.append(z)
    return out


def best_hit(
    zones: list[Zone],
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    *,
    side: str,
    daily: pd.DataFrame,
    asof: int,
) -> Hit:
    bias = "upper" if side == "long" else "lower"
    want = "upper_cont" if side == "long" else "lower_cont"
    best: Optional[Hit] = None
    for z in zones:
        ok = scan_pattern(highs, lows, closes, z.lo, z.hi, bias=bias)
        n = visits_before(daily, z, asof)
        cand = Hit(hit=ok, zone_id=z.zone_id, zone_lo=z.lo, zone_hi=z.hi, touches=n, pattern=want if ok else "")
        if ok:
            return cand
        if best is None or n > best.touches:
            best = cand
    return best or Hit(hit=False)


@dataclass
class SymCache:
    daily: pd.DataFrame
    zones: list[Zone]
    date_idx: dict[date, int]
    vp: dict[int, Optional[DailyVolumeProfile]]
    bars5: dict[date, pd.DataFrame]
    loaded1: bool = False
    df1: Optional[pd.DataFrame] = None


def load_sym(sym: str) -> Optional[SymCache]:
    path = DATA_DIR / f"{sym}.csv"
    if not path.exists():
        return None
    try:
        daily = load_ohlcv(path)
        if len(daily) <= LOOKBACK_DAYS:
            return None
        zones = build_zones(daily, LOOKBACK_DAYS)
    except Exception:
        return None
    di = {pd.Timestamp(ts).date(): i for i, ts in enumerate(daily["Date"])}
    return SymCache(daily=daily, zones=zones, date_idx=di, vp={}, bars5={})


def asof_idx(cache: SymCache, session: date) -> Optional[int]:
    prior = sorted(d for d in cache.date_idx if d < session)
    return cache.date_idx[prior[-1]] if prior else None


def day5(cache: SymCache, sym: str, session: date) -> pd.DataFrame:
    if session in cache.bars5:
        return cache.bars5[session]
    if not cache.loaded1:
        try:
            cache.df1 = read_1m(sym, DEFAULT_1M_DIR)
        except Exception:
            cache.df1 = None
        cache.loaded1 = True
    if cache.df1 is None or cache.df1.empty:
        cache.bars5[session] = pd.DataFrame()
        return cache.bars5[session]
    try:
        df5 = resample_ohlcv(cache.df1, "5min")
    except Exception:
        cache.bars5[session] = pd.DataFrame()
        return cache.bars5[session]
    if df5 is None or df5.empty:
        cache.bars5[session] = pd.DataFrame()
        return cache.bars5[session]
    ts = pd.to_datetime(df5["ts"], utc=True).dt.tz_convert(ET)
    day = df5.loc[ts.dt.date == session].copy().reset_index(drop=True)
    cache.bars5[session] = day
    return day


def parse_session(raw: Any) -> date:
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    return pd.Timestamp(raw).date()


def annotate(t: dict[str, Any], cache: SymCache, sym: str) -> dict[str, Any]:
    out = dict(t)
    session = parse_session(t["session"])
    asof = asof_idx(cache, session)
    blanks = {
        "zone_asof_idx": asof if asof is not None else "",
        "zone_carry_avail": 0,
        "zone_day_avail": 0,
        "pattern_carry": 0,
        "pattern_day": 0,
        "pattern_daily_carry": 0,
        "pattern_tf": "",
        "pattern_name": "",
        "matched_zone_id": "",
        "matched_zone_lo": "",
        "matched_zone_hi": "",
        "touch_count": 0,
        "touch_bucket": "0",
        "lvn_hvn": "no_zone",
        "pop": "all",
    }
    out.update(blanks)
    if asof is None:
        return out

    carry = active_zones(cache.zones, asof, carry=True)
    dayz = active_zones(cache.zones, asof, carry=False)
    out["zone_carry_avail"] = len(carry)
    out["zone_day_avail"] = len(dayz)
    side = str(t.get("side") or "")

    hi_d = cache.daily["High"].to_numpy(dtype=np.float64)
    lo_d = cache.daily["Low"].to_numpy(dtype=np.float64)
    cl_d = cache.daily["Close"].to_numpy(dtype=np.float64)
    vol_d = cache.daily["Volume"].to_numpy(dtype=np.float64)

    hit_c = Hit(hit=False)
    hit_d = Hit(hit=False)
    used_tf = ""

    bars = day5(cache, sym, session)
    entry_ts = pd.Timestamp(t["entry_ts"])
    if entry_ts.tzinfo is None:
        entry_ts = entry_ts.tz_localize(ET)
    else:
        entry_ts = entry_ts.tz_convert(ET)

    if not bars.empty:
        ts5 = pd.to_datetime(bars["ts"], utc=True).dt.tz_convert(ET)
        pre = bars.loc[ts5 < entry_ts]
        if len(pre) >= 2:
            h = pre["high"].to_numpy(dtype=np.float64)
            l = pre["low"].to_numpy(dtype=np.float64)
            c = pre["close"].to_numpy(dtype=np.float64)
            hit_c = best_hit(carry, h, l, c, side=side, daily=cache.daily, asof=asof)
            hit_d = best_hit(dayz, h, l, c, side=side, daily=cache.daily, asof=asof)
            used_tf = "5m"

    # Daily fallback / secondary (prior 20 sessions through asof)
    start = max(0, asof - 19)
    dh = best_hit(
        carry,
        hi_d[start : asof + 1],
        lo_d[start : asof + 1],
        cl_d[start : asof + 1],
        side=side,
        daily=cache.daily,
        asof=asof,
    )
    out["pattern_daily_carry"] = 1 if dh.hit else 0
    if used_tf == "" and carry:
        hit_c = dh
        hit_d = best_hit(
            dayz,
            hi_d[start : asof + 1],
            lo_d[start : asof + 1],
            cl_d[start : asof + 1],
            side=side,
            daily=cache.daily,
            asof=asof,
        )
        used_tf = "daily"

    out["pattern_carry"] = 1 if hit_c.hit else 0
    out["pattern_day"] = 1 if hit_d.hit else 0
    out["pattern_tf"] = used_tf

    ref = hit_c if hit_c.zone_id else None
    if ref is None and carry:
        entry = float(t["entry"])
        z = min(carry, key=lambda zz: abs(0.5 * (zz.lo + zz.hi) - entry))
        ref = Hit(hit=False, zone_id=z.zone_id, zone_lo=z.lo, zone_hi=z.hi, touches=visits_before(cache.daily, z, asof))

    if ref and ref.zone_id:
        out["matched_zone_id"] = ref.zone_id
        out["matched_zone_lo"] = round(ref.zone_lo, 4)
        out["matched_zone_hi"] = round(ref.zone_hi, 4)
        out["touch_count"] = int(ref.touches)
        out["touch_bucket"] = touch_bucket(int(ref.touches))
        out["pattern_name"] = ref.pattern
        out["lvn_hvn"] = lvn_hvn(hi_d, lo_d, cl_d, vol_d, asof, ref.zone_lo, ref.zone_hi, cache.vp)
    return out


def metrics_row(label: str, trades: list[dict[str, Any]], vs: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    m = ab.metrics_from_trades(trades, include_slices=False)
    row: dict[str, Any] = {
        "arm": label,
        "N": m.get("N"),
        "Win%": m.get("Win%"),
        "Avg_PnL_%": m.get("Avg_PnL_%"),
        "AVG_PNL_PCT_WO_MAX": m.get("AVG_PNL_PCT_WO_MAX"),
        "Expectancy_%": m.get("Expectancy_%"),
        "Expectancy_$": m.get("Expectancy_$"),
        "Profit_Factor": m.get("Profit_Factor"),
        "Sheet_PnL_$": m.get("Sheet_PnL_$", m.get("Total_PnL_$")),
        "Total_PnL_$": m.get("Total_PnL_$"),
        "Max_DD_%": m.get("Max_DD_%"),
        "Ann_ROR_%": m.get("Ann_ROR_%"),
        "verdict": "—",
    }
    if vs is not None:
        for k, dk in (
            ("N", "ΔN"),
            ("Avg_PnL_%", "ΔAvg_PnL_%"),
            ("Win%", "ΔWin%"),
            ("Profit_Factor", "ΔPF"),
            ("Sheet_PnL_$", "ΔSheet_PnL_$"),
        ):
            a, b = vs.get(k), row.get(k)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)) and math.isfinite(float(a)) and math.isfinite(float(b)):
                row[dk] = float(b) - float(a)
            else:
                row[dk] = ""
    return row


def verdict(ctrl: dict[str, Any], cand: dict[str, Any], thin: int = 20) -> str:
    n = int(cand.get("N") or 0)
    if n < thin:
        return "HOLD"
    ca, ka = ctrl.get("Avg_PnL_%"), cand.get("Avg_PnL_%")
    cp, kp = ctrl.get("Profit_Factor"), cand.get("Profit_Factor")
    if not all(isinstance(x, (int, float)) and math.isfinite(float(x)) for x in (ca, ka, cp, kp)):
        return "HOLD"
    n0 = int(ctrl.get("N") or 0)
    if n0 > 0 and n < 0.25 * n0:
        return "HOLD"
    if float(ka) > float(ca) and float(kp) >= float(cp):
        return "LEAN KEEP" if n < 50 else "KEEP"
    if float(ka) < float(ca) and float(kp) < float(cp):
        return "DISMISS"
    return "HOLD"


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("note\nempty\n", encoding="utf-8")
        return
    keys: list[str] = []
    seen: set[str] = set()
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k)
                keys.append(k)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


COLS = [
    ("arm", "Arm", "text"),
    ("N", "N", "num"),
    ("Win%", "Win%", "num"),
    ("Avg_PnL_%", "Avg PnL%", "num"),
    ("AVG_PNL_PCT_WO_MAX", "AvgPnL% w/o max", "num"),
    ("Expectancy_%", "Expectancy%", "num"),
    ("Expectancy_$", "Expectancy $", "money"),
    ("Profit_Factor", "PF", "num"),
    ("Sheet_PnL_$", "Sheet PnL $", "money"),
    ("Max_DD_%", "Max DD%", "num"),
    ("ΔAvg_PnL_%", "ΔAvg vs ctrl", "num"),
    ("ΔPF", "ΔPF vs ctrl", "num"),
    ("verdict", "Verdict", "text"),
]


def table_html(title: str, note: str, rows: list[dict[str, Any]]) -> str:
    head = "".join(th(lab, "num" if st == "money" else st) for _, lab, st in COLS)
    body = []
    for r in rows:
        cells = []
        for key, _lab, st in COLS:
            v = r.get(key, "")
            if st == "money" and isinstance(v, (int, float)) and math.isfinite(float(v)):
                cells.append(f"<td>{format_money(v)}</td>")
            elif st == "num":
                if key in ("N", "ΔN"):
                    try:
                        cells.append(f"<td>{int(v)}</td>")
                    except (TypeError, ValueError):
                        cells.append("<td>0</td>")
                else:
                    nd = 4 if "PnL_%" in key or "Expectancy_%" in key else 2
                    cells.append(f"<td>{fmt_num(v, nd)}</td>")
            else:
                cells.append(f"<td>{html_lib.escape(str(v))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    if not body:
        body.append(f"<tr><td colspan='{len(COLS)}'>No rows</td></tr>")
    return (
        f"<section><h2>{html_lib.escape(title)}</h2>"
        f"<p>{html_lib.escape(note)} Click headers to sort.</p>"
        f'<table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table></section>"
    )


def write_baseline(path: Path, source: str, n_all: int, n_filt: int, n_full: int) -> None:
    path.write_text(
        f"""# BASELINE — Scalp + HL volume zone retest / LVN+HVN — `{DEFAULT_STAMP}`

**System:** `{SYSTEM}` · research only · **not** DailyRun · **not** gold.

Aligns **carried daily HL max-vol zones** (`vol_zone_break_retest.build_zones`) to the scalp
`setup_bar_0p05` book. Short Yahoo 1m window → **no chronological IS/OOS**.
Arms are labeled separately (pattern / carry / touches / LVN+HVN) — do not AND into a silent multi-knob KEEP.

## Source

| Item | Value |
|------|--------|
| Source stamp | `{source}` |
| Trades | `trades_stop_setup_bar_0p05.csv` |
| All N | **{n_all}** |
| Winner sleeve (user) | `entirely_out` ∧ `40_60pct` ∧ shape×side OR → **N={n_filt}** |
| Full prior (+ mid_5m_20m) | as `scalp_filtered_timestop_20260822` → **N={n_full}** |
| Stop / target / time | frozen from source |

## Zone freeze

| Knob | Value |
|------|--------|
| Kind | **HL** (H–L of rolling max-volume day) |
| Lookback | **{LOOKBACK_DAYS}** |
| Retest eps | **{RETEST_EPS}** |
| Approach lookback | **{APPROACH_LB}** |
| As-of | prior daily bar before session |
| VP | lookback {VP_LOOKBACK}, bin {VP_BIN_PCT} |

### A — Lower / upper continuation

- **Lower (short):** break below `zone.lo` → re-enter `[lo,hi]` → continue lower (5m pre-entry; daily fallback if no 1m).
- **Upper (long):** break above `zone.hi` → re-enter → continue higher.

### B — Carry-forward

- **ON:** active while max-vol day remains lookback winner (`created_on_idx ≤ asof ≤ last_winner_idx`).
- **OFF:** only zones first minted on asof (`created_on_idx == asof`).

### C — Touches

Distinct `visit_id` from `detect_touches` through asof. Buckets 0 / 1 / 2 / 3 / 4+.

### D — LVN + HVN

| Label | Meaning |
|-------|---------|
| lvn+hvn | HVN/POC overlap and LVN cross |
| hvn_only / lvn_only | single gate |
| neither / no_profile / no_zone | no dual / missing |

## Honesty

Research-only. Quality over N. Thin sleeves → HOLD. No DailyRun wire.
""",
        encoding="utf-8",
    )


def write_summary(
    path: Path,
    verdicts: dict[str, str],
    sections: dict[str, list[dict[str, Any]]],
    n_all: int,
    n_filt: int,
    n_full: int,
) -> None:
    lines = [
        f"# SUMMARY — `{DEFAULT_STAMP}`",
        "",
        f"All N={n_all}. Winner (eo∧40_60∧shape) N={n_filt}. Full+mid N={n_full}.",
        "",
        "## Verdicts",
        "",
    ]
    for k, v in verdicts.items():
        lines.append(f"- **{k}:** {v}")
    for title, key in (
        ("Pattern (all)", "pattern"),
        ("Touches (all)", "touch"),
        ("LVN/HVN (all)", "lvn"),
        ("Populations", "pop"),
    ):
        lines.extend(["", f"## {title}", ""])
        for r in sections.get(key, []):
            lines.append(
                f"- `{r['arm']}`: N={r['N']} WR={fmt_num(r.get('Win%'))} "
                f"Avg={fmt_num(r.get('Avg_PnL_%'), 4)} PF={fmt_num(r.get('Profit_Factor'))} "
                f"→ {r.get('verdict')}"
            )
    lines.extend(
        [
            "",
            "## Bottom line",
            "",
            "Observational scalp×zone study on a short 1m window. Prefer HOLD unless a single "
            "arm clearly lifts Avg PnL% and PF without collapsing N. Winner sleeve stays descriptive.",
            "",
            f"See `compare.html` under `drive/paul_experiments/{DEFAULT_STAMP}/`.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_compare(
    path: Path,
    sections: list[tuple[str, str, list[dict[str, Any]]]],
    n_all: int,
    n_filt: int,
    n_full: int,
    source: str,
) -> None:
    body = "\n".join(table_html(t, n, rows) for t, n, rows in sections)
    path.write_text(
        f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html_lib.escape(DEFAULT_STAMP)}</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:1rem 1.25rem;color:#0f172a;background:#f8fafc;line-height:1.45}}
h1{{font-size:1.35rem}}h2{{font-size:1.1rem;margin:1.4rem 0 .4rem}}
p,.meta{{color:#334155;max-width:60rem}}
table.sortable{{border-collapse:collapse;width:100%;max-width:1100px;background:#fff;margin:.5rem 0 1rem;font-size:.92rem}}
th,td{{border:1px solid #cbd5e1;padding:.35rem .5rem;text-align:left}}th{{background:#e2e8f0}}
tr:nth-child(even){{background:#f1f5f9}}code{{background:#e2e8f0;padding:.05rem .25rem;border-radius:3px}}
{SORT_CSS}
</style></head><body>
<h1>Scalp × volume zones — pattern / touches / LVN+HVN</h1>
<p class="meta">Stamp <code>{html_lib.escape(DEFAULT_STAMP)}</code> · source <code>{html_lib.escape(source)}</code> ·
system <code>{SYSTEM}</code> · research only.</p>
<p class="meta">N all={n_all} · winner={n_filt} · full+mid={n_full}. IS/OOS N/A. Click headers to sort.</p>
{body}
{SORT_JS}
</body></html>
""",
        encoding="utf-8",
    )


def run(source_stamp: str, stamp: str, limit_syms: Optional[int]) -> Path:
    out = DRIVE / "paul_experiments" / stamp
    out.mkdir(parents=True, exist_ok=True)

    source = filt.load_setup_bar_trades(source_stamp)
    by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in source:
        by_sym[str(t["symbol"]).upper()].append(t)
    syms = sorted(by_sym)
    if limit_syms is not None:
        syms = syms[:limit_syms]

    annotated: list[dict[str, Any]] = []
    miss = 0
    for i, sym in enumerate(syms):
        if i % 50 == 0:
            print(f"[{i+1}/{len(syms)}] {sym}", flush=True)
        cache = load_sym(sym)
        if cache is None:
            miss += 1
            for t in by_sym[sym]:
                row = dict(t)
                row.update(
                    {
                        "zone_asof_idx": "",
                        "zone_carry_avail": 0,
                        "zone_day_avail": 0,
                        "pattern_carry": 0,
                        "pattern_day": 0,
                        "pattern_daily_carry": 0,
                        "pattern_tf": "",
                        "pattern_name": "",
                        "matched_zone_id": "",
                        "matched_zone_lo": "",
                        "matched_zone_hi": "",
                        "touch_count": 0,
                        "touch_bucket": "0",
                        "lvn_hvn": "no_daily",
                        "pop": "all",
                    }
                )
                annotated.append(row)
            continue
        for t in by_sym[sym]:
            annotated.append(annotate(t, cache, sym))

    write_csv(out / "trades_annotated.csv", annotated)

    def sub(pred) -> list[dict[str, Any]]:
        return [t for t in annotated if pred(t)]

    all_m = metrics_row("all_trades", annotated)

    pattern_specs = [
        ("all_trades", lambda t: True, False),
        ("pattern_carry_hit", lambda t: int(t.get("pattern_carry") or 0) == 1, True),
        ("pattern_carry_miss", lambda t: int(t.get("pattern_carry") or 0) == 0, False),
        ("pattern_day_hit", lambda t: int(t.get("pattern_day") or 0) == 1, True),
        ("pattern_day_miss", lambda t: int(t.get("pattern_day") or 0) == 0, False),
        ("pattern_daily_carry_hit", lambda t: int(t.get("pattern_daily_carry") or 0) == 1, True),
        ("lower_cont_short", lambda t: t.get("pattern_name") == "lower_cont", True),
        ("upper_cont_long", lambda t: t.get("pattern_name") == "upper_cont", True),
        ("long_only", lambda t: t.get("side") == "long", False),
        ("short_only", lambda t: t.get("side") == "short", False),
        ("long_pattern_hit", lambda t: t.get("side") == "long" and int(t.get("pattern_carry") or 0) == 1, True),
        ("short_pattern_hit", lambda t: t.get("side") == "short" and int(t.get("pattern_carry") or 0) == 1, True),
    ]
    pattern_rows = []
    for lab, pred, judge in pattern_specs:
        r = metrics_row(lab, sub(pred), vs=None if lab == "all_trades" else all_m)
        if judge:
            r["verdict"] = verdict(all_m, r)
        pattern_rows.append(r)

    carry_hit = metrics_row("carry_pattern_hit", sub(lambda t: int(t.get("pattern_carry") or 0) == 1), vs=all_m)
    day_hit = metrics_row("daymint_pattern_hit", sub(lambda t: int(t.get("pattern_day") or 0) == 1), vs=all_m)
    carry_hit["verdict"] = verdict(all_m, carry_hit)
    day_hit["verdict"] = verdict(all_m, day_hit)
    carry_rows = [
        {**all_m, "verdict": "control"},
        carry_hit,
        day_hit,
        {
            **metrics_row("carry_vs_day", sub(lambda t: int(t.get("pattern_carry") or 0) == 1), vs=day_hit),
            "verdict": "HOLD" if int(day_hit.get("N") or 0) < 20 else verdict(day_hit, carry_hit),
        },
    ]

    touch_rows = []
    for b in ("0", "1", "2", "3", "4+"):
        r = metrics_row(f"touches_{b}", sub(lambda t, bb=b: str(t.get("touch_bucket") or "0") == bb), vs=all_m)
        r["verdict"] = verdict(all_m, r) if b != "0" else "—"
        touch_rows.append(r)
    touch_ge2 = metrics_row(
        "touches_2plus",
        sub(lambda t: str(t.get("touch_bucket") or "0") in ("2", "3", "4+")),
        vs=all_m,
    )
    touch_ge2["verdict"] = verdict(all_m, touch_ge2)
    touch_rows.append(touch_ge2)

    lvn_rows = []
    for lab in ("lvn+hvn", "hvn_only", "lvn_only", "neither", "no_profile", "no_zone", "no_daily"):
        r = metrics_row(lab, sub(lambda t, L=lab: str(t.get("lvn_hvn") or "") == L), vs=all_m)
        if lab in ("lvn+hvn", "hvn_only", "lvn_only"):
            r["verdict"] = verdict(all_m, r)
        lvn_rows.append(r)
    hvn_any = metrics_row(
        "hvn_any",
        sub(lambda t: str(t.get("lvn_hvn") or "") in ("hvn_only", "lvn+hvn")),
        vs=all_m,
    )
    hvn_any["verdict"] = verdict(all_m, hvn_any)
    lvn_rows.append(hvn_any)

    winners = [t for t in annotated if winner_user(t)]
    fulls = [t for t in annotated if winner_full(t)]
    w_m = metrics_row("winner", winners)
    pop_rows = [
        {**all_m, "verdict": "control"},
        {
            **metrics_row("winner_eo_4060_shape", winners, vs=all_m),
            "verdict": "HOLD" if len(winners) < 20 else verdict(all_m, w_m),
        },
        {**metrics_row("full_mid_stack", fulls, vs=all_m), "verdict": "HOLD"},
        {
            **metrics_row("winner_pattern_hit", [t for t in winners if int(t.get("pattern_carry") or 0) == 1], vs=w_m),
            "verdict": "HOLD",
        },
        {
            **metrics_row("winner_pattern_miss", [t for t in winners if int(t.get("pattern_carry") or 0) == 0], vs=w_m),
            "verdict": "HOLD",
        },
    ]
    w_touch = [
        {**metrics_row(f"winner_touches_{b}", [t for t in winners if str(t.get("touch_bucket") or "0") == b]), "verdict": "HOLD"}
        for b in ("0", "1", "2", "3", "4+")
    ]
    w_lvn = [
        {**metrics_row(f"winner_{lab}", [t for t in winners if str(t.get("lvn_hvn") or "") == lab]), "verdict": "HOLD"}
        for lab in ("lvn+hvn", "hvn_only", "lvn_only", "neither", "no_profile", "no_zone", "no_daily")
    ]

    write_csv(out / "metrics_pattern.csv", pattern_rows)
    write_csv(out / "metrics_carry.csv", carry_rows)
    write_csv(out / "metrics_touch.csv", touch_rows)
    write_csv(out / "metrics_lvn_hvn.csv", lvn_rows)
    write_csv(out / "metrics_pop.csv", pop_rows)
    write_csv(out / "metrics_winner_touch.csv", w_touch)
    write_csv(out / "metrics_winner_lvn_hvn.csv", w_lvn)

    verdicts = {
        "A_pattern_carry_vs_all": str(carry_hit.get("verdict", "HOLD")),
        "B_carry_vs_daymint": "HOLD" if int(day_hit.get("N") or 0) < 20 else verdict(day_hit, carry_hit),
        "C_touches_2plus": str(touch_ge2.get("verdict", "HOLD")),
        "D_lvn+hvn": next(str(r["verdict"]) for r in lvn_rows if r["arm"] == "lvn+hvn"),
        "D_hvn_any": str(hvn_any.get("verdict", "HOLD")),
        "winner_sleeve": "HOLD",
        "full_mid_sleeve": "HOLD",
    }

    write_baseline(out / "BASELINE.md", source_stamp, len(annotated), len(winners), len(fulls))
    write_summary(
        out / "SUMMARY.md",
        verdicts,
        {"pattern": pattern_rows, "touch": touch_rows, "lvn": lvn_rows, "pop": pop_rows},
        len(annotated),
        len(winners),
        len(fulls),
    )
    write_compare(
        out / "compare.html",
        [
            ("A) Pattern hit quality (all)", "Break→re-enter→continue vs miss.", pattern_rows),
            ("B) Carry vs day-mint", "Persistent zones vs first-minted-on-asof.", carry_rows),
            ("C) Touch buckets (all)", "Visits on matched HL zone through prior close.", touch_rows),
            ("D) LVN / HVN (all)", "Daily VP gate on matched zone.", lvn_rows),
            ("Populations", "Winner = eo∧40_60∧shape; full+mid ultra-thin.", pop_rows),
            ("Winner — touches", "Thin N → HOLD only.", w_touch),
            ("Winner — LVN/HVN", "Thin N → HOLD only.", w_lvn),
        ],
        len(annotated),
        len(winners),
        len(fulls),
        source_stamp,
    )
    (out / "COVERAGE.txt").write_text(
        f"annotated={len(annotated)} miss_daily={miss} winner={len(winners)} full_mid={len(fulls)} "
        f"pattern_carry_hits={sum(1 for t in annotated if int(t.get('pattern_carry') or 0)==1)} "
        f"tf_5m={sum(1 for t in annotated if t.get('pattern_tf')=='5m')} "
        f"tf_daily={sum(1 for t in annotated if t.get('pattern_tf')=='daily')}\n",
        encoding="utf-8",
    )
    print("Wrote", out)
    print("Verdicts", verdicts)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-stamp", default=DEFAULT_SOURCE)
    ap.add_argument("--stamp", default=DEFAULT_STAMP)
    ap.add_argument("--limit-syms", type=int, default=None)
    args = ap.parse_args()
    run(args.source_stamp, args.stamp, args.limit_syms)


if __name__ == "__main__":
    main()
