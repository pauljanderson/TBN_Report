#!/usr/bin/env python3
"""Research prototype: rolling max-vol day zones -> break -> retest entries.

Hypothesis formation only - not production gold. Single-symbol mode builds full
OC + HL zone history, detects touches / holds / breaks / retests, optional param
grid, charts, and HTML under drive/paul_experiments/.

Universe / PaulTwenty mode (--paultwenty or --universe) freezes RESEARCH_BASELINE,
scans full local history per symbol, writes analysis HTML + optional AB comparison.

Candidate v2 (--candidate-v2): HL-primary + first_retest + min_touches>=1, with
toy vs zone-ATR exit compare and chronologic IS/OOS split (holdout 2024+).

V2 exit AB (--v2-exit-ab): freeze candidate v2 entries + zone_atr05_ts40 primary exit,
re-score IS/OOS and one-change ABs under that exit (research candidate, not gold).

Adopted rw63 freeze (--v2-rw63): RESEARCH_CANDIDATE_V2_RW63 (same HL+gates as v2 but
retest_window=63) + zone_atr05_ts40; PaulTwenty re-run vs prior rw126 freeze.
Research baseline only - still not gold / not DailyRun.

Full-universe confirmation (--v2-rw63-fulluniv): same freeze on all local OHLC CSVs
(DailyRun ALL semantics under data/newdata/data); compare pooled metrics to the
PaulTwenty rw63 stamp. Research only - do not retune on OOS.

Examples:
  python tools/vol_zone_break_retest.py --symbol NVDA --lookback-days 126 --skip-grid
  python tools/vol_zone_break_retest.py --paultwenty --run-ab --stamp vol_zone_paultwenty_YYYYMMDD
  python tools/vol_zone_break_retest.py --candidate-v2 --run-ab --stamp vol_zone_hl_quality_YYYYMMDD
  python tools/vol_zone_break_retest.py --v2-exit-ab --stamp vol_zone_v2_exit_ab_YYYYMMDD
  python tools/vol_zone_break_retest.py --v2-rw63 --stamp vol_zone_v2_rw63_YYYYMMDD
  python tools/vol_zone_break_retest.py --v2-rw63-fulluniv --stamp vol_zone_v2_rw63_fulluniv_YYYYMMDD
"""
from __future__ import annotations

import argparse
import html as html_mod
import itertools
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable, Literal

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = REPO / "data" / "newdata" / "data"
DEFAULT_OUT_DIR = REPO / "drive" / "paul_experiments"

ZoneKind = Literal["OC", "HL"]
Approach = Literal["from_above", "from_below", "inside", "unknown"]

# ---------------------------------------------------------------------------
# Sortable HTML helpers (monthly-report convention)
# ---------------------------------------------------------------------------
SORTABLE_TH_CSS = """
th.sortable-th{cursor:pointer;user-select:none;white-space:nowrap}
th.sortable-th:hover{background:#e2e8f0}
th.sortable-th .sort-ind::after{content:" \\2195";opacity:.35;font-size:.85em}
th.sortable-th.sort-asc .sort-ind::after{content:" \\2191";opacity:.9}
th.sortable-th.sort-desc .sort-ind::after{content:" \\2193";opacity:.9}
"""

SORTABLE_TABLE_SCRIPT = """
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "-" || s === "-") return type === "text" ? "" : 0;
    if (type === "text") return s.toUpperCase();
    if (type === "date") {
      var iso = s.match(/(\\d{4})-(\\d{2})-(\\d{2})/);
      if (iso) return parseInt(iso[1] + iso[2] + iso[3], 10);
      return 0;
    }
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
  function bind(table) {
    var ths = table.querySelectorAll("th.sortable-th");
    ths.forEach(function (th, idx) {
      function activate() {
        var type = th.getAttribute("data-sort") || "text";
        var asc = !th.classList.contains("sort-asc");
        ths.forEach(function (x) {
          x.classList.remove("sort-asc", "sort-desc");
          x.setAttribute("aria-sort", "none");
        });
        th.classList.add(asc ? "sort-asc" : "sort-desc");
        th.setAttribute("aria-sort", asc ? "ascending" : "descending");
        sortTable(table, idx, type, asc ? 1 : -1);
      }
      th.addEventListener("click", activate);
      th.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activate(); }
      });
    });
  }
  document.querySelectorAll("table.sortable").forEach(bind);
})();
</script>
"""


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{html_mod.escape(sort_type)}" '
        f'tabindex="0" role="columnheader" aria-sort="none">'
        f"{html_mod.escape(label)}<span class=\"sort-ind\"></span></th>"
    )


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class Zone:
    zone_id: str
    kind: ZoneKind
    max_vol_idx: int
    max_vol_date: pd.Timestamp
    volume: int
    lo: float
    hi: float
    created_on_idx: int  # first day this bar is rolling max-vol winner
    created_on: pd.Timestamp
    last_winner_idx: int  # last day it was the rolling winner
    last_winner_date: pd.Timestamp


@dataclass
class TouchEvent:
    zone_id: str
    kind: ZoneKind
    bar_idx: int
    date: pd.Timestamp
    visit_id: int  # increments after leave; same visit = contiguous bars
    approach: Approach
    role: Literal["support", "resistance", "inside", "unknown"]
    is_hold: bool  # bounce without close-break of the approached side
    broke: bool  # close exited through the zone in approach direction
    low: float
    high: float
    close: float


@dataclass
class BreakEvent:
    zone_id: str
    kind: ZoneKind
    bar_idx: int
    date: pd.Timestamp
    direction: Literal["up", "down"]
    close: float
    break_pct: float  # (close-hi)/hi or (lo-close)/lo
    atr_mult: float  # distance / ATR14


@dataclass
class RetestSignal:
    zone_id: str
    kind: ZoneKind
    entry_idx: int
    entry_date: pd.Timestamp
    entry_price: float
    break_idx: int
    break_date: pd.Timestamp
    bars_after_break: int
    touch_count_all: int  # intersections (visits) before this entry bar
    touch_count_holds: int
    pre_break_touches: int
    post_break_touches: int
    strength: float
    stop: float
    params_tag: str
    break_dist_pct: float = 0.0  # (close-hi)/hi at upside break
    break_atr_mult: float = 0.0
    visit_n: int = 1  # 1 = first retest after break; later visits increment
    # Predictive timing: signal bar = first bar where retest is known (uses that bar's
    # Low/High/Close). Fill is either that bar's Close or the *next* bar's Open.
    # Never fill at Open of the signal bar (that would be look-ahead).
    signal_idx: int = -1
    signal_date: pd.Timestamp | None = None


@dataclass
class SysParams:
    lookback_days: int = 126
    break_pct: float = 0.0  # min close beyond zone edge as fraction of edge
    break_atr: float = 0.0  # min distance in ATR multiples (0 = off)
    break_window: int | None = None  # None = anytime after formation
    require_hold_bars: int = 0  # closes still beyond edge for N bars after break
    retest_window: int = 126  # bars after breakout to allow retest entry
    retest_eps_pct: float = 0.002  # allow low within eps of zone.hi (near-miss)
    entry_on: Literal["close", "next_open"] = "close"
    first_retest_only: bool = True
    zone_kinds: tuple[ZoneKind, ...] = ("OC", "HL")
    min_touches_before_entry: int = 0
    count_only_holds: bool = False
    count_pre_break_touches: bool = True
    touch_decay_halflife: float | None = None  # bars; None = equal weight
    approach_lookback: int = 5  # bars before touch to judge approach
    # lightweight exit for rough win-rate
    exit_bars: int = 20
    target_r: float = 2.0


# Research freeze (NOT production gold). Matches NVDA-shaped hypothesis.
RESEARCH_BASELINE = SysParams(
    lookback_days=126,
    break_pct=0.0,
    break_atr=0.0,
    break_window=None,
    require_hold_bars=0,
    retest_window=126,
    retest_eps_pct=0.005,
    entry_on="close",
    first_retest_only=False,
    zone_kinds=("OC", "HL"),
    min_touches_before_entry=0,
    count_only_holds=False,
    count_pre_break_touches=True,
    touch_decay_halflife=None,
    approach_lookback=5,
    exit_bars=20,
    target_r=2.0,
)

# Research candidate v2 (NOT gold): HL-primary + quality gates from PaulTwenty AB.
# Prior exit-AB control used retest_window=126; superseded as research baseline by rw63.
# Still research-only - eps remains NVDA-shaped in-sample history.
RESEARCH_CANDIDATE_V2 = SysParams(
    lookback_days=126,
    break_pct=0.0,
    break_atr=0.0,
    break_window=None,
    require_hold_bars=0,
    retest_window=126,
    retest_eps_pct=0.005,
    entry_on="close",
    first_retest_only=True,
    zone_kinds=("HL",),
    min_touches_before_entry=1,
    count_only_holds=False,
    count_pre_break_touches=True,
    touch_decay_halflife=None,
    approach_lookback=5,
    exit_bars=20,
    target_r=2.0,
)

# Adopted research freeze (NOT gold): LEAN KEEP arm 01_rw63 from vol_zone_v2_exit_ab_*.
# Same entry gates as candidate v2 except retest_window=63; primary exit zone_atr05_ts40.
RESEARCH_CANDIDATE_V2_RW63 = replace(RESEARCH_CANDIDATE_V2, retest_window=63)

# Chronologic holdout: tune/narrative through 2023; 2024+ is OOS (do not retune).
OOS_SPLIT_DATE = pd.Timestamp("2024-01-01")

DEFAULT_PAULTWENTY = REPO / "drive" / "universes" / "PaulTwenty_universe.csv"
DEFAULT_PAULTWENTY_RW63_STAMP = "vol_zone_v2_rw63_20260810"
DEFAULT_FULLUNIV_COMPARE_STAMP = DEFAULT_OUT_DIR / DEFAULT_PAULTWENTY_RW63_STAMP


@dataclass(frozen=True)
class ExitSpec:
    """Exit recipe applied to the same entry signals (research ranking, not gold)."""

    name: str
    label: str
    exit_bars: int = 20
    target_r: float = 2.0
    stop_atr_buffer: float = 0.0  # stop = zone.lo - buffer * ATR14[entry]


# Toy (prior stamp) vs zone-aware stops with ATR buffer under zone.lo.
EXIT_SPECS: tuple[ExitSpec, ...] = (
    ExitSpec("toy", "Toy: stop=zone.lo, 2R / 20d", exit_bars=20, target_r=2.0, stop_atr_buffer=0.0),
    ExitSpec(
        "zone_atr05",
        "Zone-stop: zone.lo-0.5*ATR, 2R / 20d",
        exit_bars=20,
        target_r=2.0,
        stop_atr_buffer=0.5,
    ),
    ExitSpec(
        "zone_atr05_ts40",
        "Zone-stop: zone.lo-0.5*ATR, 2R / 40d",
        exit_bars=40,
        target_r=2.0,
        stop_atr_buffer=0.5,
    ),
)

# Primary research exit for step-5 ABs (chosen in-sample on PaulTwenty exit compare).
PRIMARY_EXIT = next(e for e in EXIT_SPECS if e.name == "zone_atr05_ts40")
TOY_EXIT = next(e for e in EXIT_SPECS if e.name == "toy")

# Exit ABs: same zone.lo − 0.5·ATR stop; vary time stop only (label as EXIT arms).
EXIT_AB_SPECS: tuple[ExitSpec, ...] = (
    ExitSpec(
        "zone_atr05_ts20",
        "EXIT AB: zone.lo-0.5*ATR, 2R / 20d",
        exit_bars=20,
        target_r=2.0,
        stop_atr_buffer=0.5,
    ),
    ExitSpec(
        "zone_atr05_ts40",
        "EXIT AB control: zone.lo-0.5*ATR, 2R / 40d",
        exit_bars=40,
        target_r=2.0,
        stop_atr_buffer=0.5,
    ),
    ExitSpec(
        "zone_atr05_ts60",
        "EXIT AB: zone.lo-0.5*ATR, 2R / 60d",
        exit_bars=60,
        target_r=2.0,
        stop_atr_buffer=0.5,
    ),
)


@dataclass
class ScanResult:
    params: SysParams
    signals: list[RetestSignal]
    n_signals: int
    n_wins: int
    win_rate: float
    avg_pnl_pct: float
    feb26_may: bool
    feb26_jun: bool
    feb26_jul: bool
    tag: str


# ---------------------------------------------------------------------------
# Load / ATR / zones
# ---------------------------------------------------------------------------
def load_ohlcv(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, parse_dates=["Date"]).sort_values("Date").reset_index(drop=True)
    need = {"Date", "Open", "High", "Low", "Close", "Volume"}
    missing = need - set(df.columns)
    if missing:
        raise SystemExit(f"CSV missing columns {sorted(missing)}: {csv_path}")
    return df


def atr14(df: pd.DataFrame) -> np.ndarray:
    h = df["High"].to_numpy(dtype=np.float64)
    l = df["Low"].to_numpy(dtype=np.float64)
    c = df["Close"].to_numpy(dtype=np.float64)
    prev_c = np.roll(c, 1)
    prev_c[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    out = np.full_like(tr, np.nan)
    if len(tr) < 14:
        return out
    out[13] = tr[:14].mean()
    for i in range(14, len(tr)):
        out[i] = (out[i - 1] * 13 + tr[i]) / 14
    return out


def build_zones(df: pd.DataFrame, lookback_days: int) -> list[Zone]:
    """Every unique rolling max-vol winner becomes a persistent OC + HL zone."""
    n = len(df)
    if n <= lookback_days:
        raise ValueError(f"Need >{lookback_days} bars; got {n}")

    vol = df["Volume"].to_numpy(dtype=np.float64)
    opens = df["Open"].to_numpy(dtype=np.float64)
    highs = df["High"].to_numpy(dtype=np.float64)
    lows = df["Low"].to_numpy(dtype=np.float64)
    closes = df["Close"].to_numpy(dtype=np.float64)
    dates = df["Date"]

    # Walk day-by-day; track first/last active span per winner index
    first_active: dict[int, int] = {}
    last_active: dict[int, int] = {}
    order: list[int] = []

    for t in range(lookback_days - 1, n):
        w0 = t - lookback_days + 1
        winner = w0 + int(np.argmax(vol[w0 : t + 1]))
        if winner not in first_active:
            first_active[winner] = t
            order.append(winner)
        last_active[winner] = t

    zones: list[Zone] = []
    for w in order:
        row_date = pd.Timestamp(dates.iloc[w])
        created_t = first_active[w]
        last_t = last_active[w]
        vol_i = int(vol[w])
        # OC
        oc_lo, oc_hi = float(min(opens[w], closes[w])), float(max(opens[w], closes[w]))
        zones.append(
            Zone(
                zone_id=f"OC_{row_date.date()}",
                kind="OC",
                max_vol_idx=w,
                max_vol_date=row_date,
                volume=vol_i,
                lo=oc_lo,
                hi=oc_hi,
                created_on_idx=created_t,
                created_on=pd.Timestamp(dates.iloc[created_t]),
                last_winner_idx=last_t,
                last_winner_date=pd.Timestamp(dates.iloc[last_t]),
            )
        )
        # HL
        zones.append(
            Zone(
                zone_id=f"HL_{row_date.date()}",
                kind="HL",
                max_vol_idx=w,
                max_vol_date=row_date,
                volume=vol_i,
                lo=float(lows[w]),
                hi=float(highs[w]),
                created_on_idx=created_t,
                created_on=pd.Timestamp(dates.iloc[created_t]),
                last_winner_idx=last_t,
                last_winner_date=pd.Timestamp(dates.iloc[last_t]),
            )
        )
    return zones


# ---------------------------------------------------------------------------
# Event detection
# ---------------------------------------------------------------------------
def _bar_intersects(lo: float, hi: float, bar_lo: float, bar_hi: float) -> bool:
    return bar_lo <= hi and bar_hi >= lo


def _approach(
    closes: np.ndarray, bar_idx: int, zone: Zone, lookback: int
) -> Approach:
    start = max(zone.created_on_idx + 1, bar_idx - lookback)
    if start >= bar_idx:
        return "unknown"
    prior = closes[start:bar_idx]
    if len(prior) == 0:
        return "unknown"
    above = np.sum(prior > zone.hi)
    below = np.sum(prior < zone.lo)
    if above >= max(1, int(0.6 * len(prior))):
        return "from_above"
    if below >= max(1, int(0.6 * len(prior))):
        return "from_below"
    mid = (zone.lo + zone.hi) / 2.0
    if float(np.mean(prior)) > mid:
        return "from_above"
    if float(np.mean(prior)) < mid:
        return "from_below"
    return "inside"


def detect_touches(
    df: pd.DataFrame,
    zone: Zone,
    approach_lookback: int = 5,
    eps_pct: float = 0.0,
) -> list[TouchEvent]:
    """Primary touch: bar H-L overlaps [lo,hi] (optional eps expands band).

    Dedupe: at most one touch per bar; visit_id increments after leaving the zone
    (contiguous intersecting bars share one visit).
    """
    highs = df["High"].to_numpy(dtype=np.float64)
    lows = df["Low"].to_numpy(dtype=np.float64)
    closes = df["Close"].to_numpy(dtype=np.float64)
    dates = df["Date"]

    band_lo = zone.lo * (1.0 - eps_pct)
    band_hi = zone.hi * (1.0 + eps_pct)

    touches: list[TouchEvent] = []
    visit_id = 0
    in_zone = False

    for i in range(zone.created_on_idx + 1, len(df)):
        hit = _bar_intersects(band_lo, band_hi, float(lows[i]), float(highs[i]))
        if not hit:
            in_zone = False
            continue
        if not in_zone:
            visit_id += 1
            in_zone = True

        approach = _approach(closes, i, zone, approach_lookback)
        cl = float(closes[i])
        broke = False
        is_hold = False
        if approach == "from_above":
            role: Literal["support", "resistance", "inside", "unknown"] = "support"
            broke = cl < zone.lo
            is_hold = (not broke) and (cl >= zone.lo) and (
                float(lows[i]) <= zone.hi * (1.0 + eps_pct)
            )
            # hold = touched from above and closed back above mid or hi
            if not broke and cl >= (zone.lo + zone.hi) / 2.0:
                is_hold = True
            elif broke:
                is_hold = False
        elif approach == "from_below":
            role = "resistance"
            broke = cl > zone.hi
            is_hold = (not broke) and cl <= (zone.lo + zone.hi) / 2.0
        else:
            role = "inside" if approach == "inside" else "unknown"
            broke = cl < zone.lo or cl > zone.hi
            is_hold = not broke

        touches.append(
            TouchEvent(
                zone_id=zone.zone_id,
                kind=zone.kind,
                bar_idx=i,
                date=pd.Timestamp(dates.iloc[i]),
                visit_id=visit_id,
                approach=approach,
                role=role,
                is_hold=bool(is_hold and not broke),
                broke=broke,
                low=float(lows[i]),
                high=float(highs[i]),
                close=cl,
            )
        )
    return touches


def detect_breaks(
    df: pd.DataFrame,
    zone: Zone,
    atr: np.ndarray,
    break_pct: float = 0.0,
    break_atr: float = 0.0,
    break_window: int | None = None,
) -> list[BreakEvent]:
    """Break up: close > hi*(1+break_pct) and optionally > hi + break_atr*ATR.
    Break down: symmetric. First break in each direction after formation (within window).
    """
    closes = df["Close"].to_numpy(dtype=np.float64)
    dates = df["Date"]
    start = zone.created_on_idx + 1
    end = len(df) if break_window is None else min(len(df), start + break_window)

    events: list[BreakEvent] = []
    seen_up = False
    seen_down = False

    for i in range(start, end):
        cl = float(closes[i])
        a = float(atr[i]) if np.isfinite(atr[i]) else 0.0
        # up
        if not seen_up:
            pct_ok = cl >= zone.hi * (1.0 + break_pct)
            atr_ok = True if break_atr <= 0 else (a > 0 and (cl - zone.hi) >= break_atr * a)
            # require previously at/below (simple: any prior close <= hi since creation)
            prior = closes[start:i]
            was_below = len(prior) == 0 or bool(np.any(prior <= zone.hi))
            if pct_ok and atr_ok and was_below and cl > zone.hi:
                dist_pct = (cl - zone.hi) / zone.hi if zone.hi else 0.0
                atr_m = (cl - zone.hi) / a if a > 0 else 0.0
                events.append(
                    BreakEvent(
                        zone_id=zone.zone_id,
                        kind=zone.kind,
                        bar_idx=i,
                        date=pd.Timestamp(dates.iloc[i]),
                        direction="up",
                        close=cl,
                        break_pct=float(dist_pct),
                        atr_mult=float(atr_m),
                    )
                )
                seen_up = True
        if not seen_down:
            pct_ok = cl <= zone.lo * (1.0 - break_pct)
            atr_ok = True if break_atr <= 0 else (a > 0 and (zone.lo - cl) >= break_atr * a)
            prior = closes[start:i]
            was_above = len(prior) == 0 or bool(np.any(prior >= zone.lo))
            if pct_ok and atr_ok and was_above and cl < zone.lo:
                dist_pct = (zone.lo - cl) / zone.lo if zone.lo else 0.0
                atr_m = (zone.lo - cl) / a if a > 0 else 0.0
                events.append(
                    BreakEvent(
                        zone_id=zone.zone_id,
                        kind=zone.kind,
                        bar_idx=i,
                        date=pd.Timestamp(dates.iloc[i]),
                        direction="down",
                        close=cl,
                        break_pct=float(dist_pct),
                        atr_mult=float(atr_m),
                    )
                )
                seen_down = True
        if seen_up and seen_down:
            break
    return events


def _visit_summary(touches: list[TouchEvent]) -> list[TouchEvent]:
    """One representative event per visit (last bar of visit)."""
    by_visit: dict[int, TouchEvent] = {}
    for t in touches:
        by_visit[t.visit_id] = t  # keep last bar in visit
    return [by_visit[k] for k in sorted(by_visit)]


def strength_score(
    visits: list[TouchEvent],
    asof_idx: int,
    break_idx: int | None,
    *,
    count_only_holds: bool,
    count_pre_break: bool,
    decay_halflife: float | None,
) -> tuple[float, int, int, int, int]:
    """Return (strength, n_all, n_holds, n_pre, n_post) using visits strictly before asof_idx."""
    n_all = n_holds = n_pre = n_post = 0
    score = 0.0
    for v in visits:
        if v.bar_idx >= asof_idx:
            continue
        if break_idx is not None and not count_pre_break and v.bar_idx < break_idx:
            continue
        is_post = break_idx is not None and v.bar_idx > break_idx
        is_pre = break_idx is None or v.bar_idx < break_idx
        if count_only_holds and not v.is_hold:
            continue
        n_all += 1
        if v.is_hold:
            n_holds += 1
        if is_pre:
            n_pre += 1
        if is_post:
            n_post += 1
        w = 1.0
        if decay_halflife and decay_halflife > 0:
            age = asof_idx - v.bar_idx
            w = 0.5 ** (age / decay_halflife)
        # holds weigh more; breaks weigh less / negative
        if v.broke:
            score += -0.5 * w
        elif v.is_hold:
            score += 1.0 * w
        else:
            score += 0.4 * w
    return score, n_all, n_holds, n_pre, n_post


def generate_signals(
    df: pd.DataFrame,
    zone: Zone,
    touches: list[TouchEvent],
    breaks: list[BreakEvent],
    params: SysParams,
    params_tag: str,
) -> list[RetestSignal]:
    """After breakout-up: buy on support retest (HL overlap or eps near-miss from above).

    When first_retest_only is False, emit at most one signal per visit (first bar
    of each post-break visit / near-miss streak).
    """
    ups = [b for b in breaks if b.direction == "up"]
    if not ups:
        return []
    br = ups[0]

    closes = df["Close"].to_numpy(dtype=np.float64)
    opens = df["Open"].to_numpy(dtype=np.float64)
    lows = df["Low"].to_numpy(dtype=np.float64)
    highs = df["High"].to_numpy(dtype=np.float64)
    dates = df["Date"]

    if params.require_hold_bars > 0:
        for j in range(1, params.require_hold_bars + 1):
            k = br.bar_idx + j
            if k >= len(df) or float(closes[k]) < zone.hi:
                return []

    visits = _visit_summary(touches)
    signals: list[RetestSignal] = []
    end = min(len(df), br.bar_idx + 1 + params.retest_window)
    eps = params.retest_eps_pct
    band_lo = zone.lo * (1.0 - eps)
    band_hi = zone.hi * (1.0 + eps)

    in_touch = False
    for i in range(br.bar_idx + 1, end):
        approach = _approach(closes, i, zone, params.approach_lookback)
        hit = _bar_intersects(band_lo, band_hi, float(lows[i]), float(highs[i]))
        near = float(lows[i]) <= zone.hi * (1.0 + eps) and float(lows[i]) >= zone.hi * (
            1.0 - max(eps, 0.005)
        )
        active = bool(hit or near)
        if not active:
            in_touch = False
            continue
        if approach != "from_above":
            in_touch = True  # still inside a visit streak
            continue
        if float(closes[i]) < zone.lo:
            in_touch = True
            continue
        if in_touch:
            continue  # already signaled / skipped this visit
        in_touch = True

        strength, n_all, n_holds, n_pre, n_post = strength_score(
            visits,
            i,
            br.bar_idx,
            count_only_holds=params.count_only_holds,
            count_pre_break=params.count_pre_break_touches,
            decay_halflife=params.touch_decay_halflife,
        )
        touch_metric = n_holds if params.count_only_holds else n_all
        if touch_metric < params.min_touches_before_entry:
            continue

        # Signal known only after bar ``i`` completes (needs Low/High/Close of ``i``).
        signal_idx = i
        if params.entry_on == "next_open":
            if i + 1 >= len(df):
                continue
            entry_idx = i + 1
            entry_price = float(opens[entry_idx])
        else:
            # EOD fill: same bar close (available when signal is known). Forbidden:
            # buying opens[i] using lows[i] / closes[i] (look-ahead on signal morning).
            entry_idx = i
            entry_price = float(closes[entry_idx])

        sig = RetestSignal(
            zone_id=zone.zone_id,
            kind=zone.kind,
            entry_idx=entry_idx,
            entry_date=pd.Timestamp(dates.iloc[entry_idx]),
            entry_price=entry_price,
            break_idx=br.bar_idx,
            break_date=br.date,
            bars_after_break=entry_idx - br.bar_idx,
            touch_count_all=n_all,
            touch_count_holds=n_holds,
            pre_break_touches=n_pre,
            post_break_touches=n_post,
            strength=strength,
            stop=zone.lo,
            params_tag=params_tag,
            break_dist_pct=float(br.break_pct),
            break_atr_mult=float(br.atr_mult),
            visit_n=len(signals) + 1,
            signal_idx=signal_idx,
            signal_date=pd.Timestamp(dates.iloc[signal_idx]),
        )
        assert_predictive_entry(sig, params.entry_on)
        signals.append(sig)
        if params.first_retest_only:
            break

    return signals


def assert_predictive_entry(
    sig: RetestSignal,
    entry_on: Literal["close", "next_open"],
) -> None:
    """Hard guard: never buy the open of the signal bar (look-ahead).

    Bar rules
    ---------
    - **Signal bar** (``signal_idx``): first bar whose Low/High/Close make the retest
      known. Known only at/after that bar's close.
    - **entry_on=close**: fill at Close of signal bar (``entry_idx == signal_idx``).
      Not the morning of the signal day.
    - **entry_on=next_open**: fill at Open of the *next* bar
      (``entry_idx == signal_idx + 1``). Default for live / house runs.
    """
    if sig.signal_idx < 0:
        raise AssertionError("RetestSignal missing signal_idx (predictive timing)")
    if entry_on == "close":
        if sig.entry_idx != sig.signal_idx:
            raise AssertionError(
                f"entry_on=close requires entry_idx==signal_idx "
                f"(got entry={sig.entry_idx} signal={sig.signal_idx})"
            )
    elif entry_on == "next_open":
        if sig.entry_idx != sig.signal_idx + 1:
            raise AssertionError(
                f"entry_on=next_open requires entry_idx==signal_idx+1 "
                f"(got entry={sig.entry_idx} signal={sig.signal_idx})"
            )
    else:
        raise AssertionError(f"unknown entry_on={entry_on!r}")
    # Explicit forbid: fill bar before signal is known
    if sig.entry_idx < sig.signal_idx:
        raise AssertionError(
            f"look-ahead: entry_idx {sig.entry_idx} < signal_idx {sig.signal_idx}"
        )


def resolve_stop(
    sig: RetestSignal,
    atr: np.ndarray | None,
    stop_atr_buffer: float = 0.0,
) -> float:
    """Stop under zone.lo, optionally buffered by ATR multiples."""
    stop = float(sig.stop)
    if stop_atr_buffer > 0 and atr is not None and 0 <= sig.entry_idx < len(atr):
        a = float(atr[sig.entry_idx])
        if np.isfinite(a) and a > 0:
            stop = stop - stop_atr_buffer * a
    return stop


def simulate_exit(
    df: pd.DataFrame,
    sig: RetestSignal,
    *,
    exit_bars: int,
    target_r: float,
    stop: float | None = None,
) -> dict:
    """Exit at stop, target R, or time stop. Returns pnl%, R, reason, bars held.

    ``exit_reason``:
      - stop / target — hard exit hit
      - time — held through ``exit_bars`` trading days without stop/target
      - still_open — history ended before stop/target/time (as-of / end-of-data);
        not a closed time stop; house path emits these as Open, not Closed
    """
    highs = df["High"].to_numpy(dtype=np.float64)
    lows = df["Low"].to_numpy(dtype=np.float64)
    closes = df["Close"].to_numpy(dtype=np.float64)
    entry = float(sig.entry_price)
    stop_px = float(sig.stop if stop is None else stop)
    risk = max(entry - stop_px, entry * 0.005)
    target = entry + target_r * risk
    last_i = len(df) - 1
    time_i = int(sig.entry_idx) + int(exit_bars)
    end = min(last_i, time_i)
    for i in range(sig.entry_idx + 1, end + 1):
        if float(lows[i]) <= stop_px:
            pnl = (stop_px - entry) / entry * 100.0
            return {
                "pnl_pct": pnl,
                "r_mult": (stop_px - entry) / risk,
                "exit_reason": "stop",
                "bars_held": i - sig.entry_idx,
                "stop": stop_px,
                "target": target,
            }
        if float(highs[i]) >= target:
            pnl = (target - entry) / entry * 100.0
            return {
                "pnl_pct": pnl,
                "r_mult": target_r,
                "exit_reason": "target",
                "bars_held": i - sig.entry_idx,
                "stop": stop_px,
                "target": target,
            }
    bars_held = int(end - sig.entry_idx)
    pnl = (float(closes[end]) - entry) / entry * 100.0
    # Real time stop only when the full exit_bars window was available and held.
    if bars_held >= int(exit_bars) and end >= time_i:
        reason = "time"
    else:
        reason = "still_open"
    return {
        "pnl_pct": pnl,
        "r_mult": (pnl / 100.0 * entry) / risk if risk > 0 else 0.0,
        "exit_reason": reason,
        "bars_held": bars_held,
        "stop": stop_px,
        "target": target,
    }


def simulate_exit_spec(
    df: pd.DataFrame,
    sig: RetestSignal,
    spec: ExitSpec,
    atr: np.ndarray | None = None,
) -> dict:
    stop = resolve_stop(sig, atr, spec.stop_atr_buffer)
    out = simulate_exit(
        df, sig, exit_bars=spec.exit_bars, target_r=spec.target_r, stop=stop
    )
    out["exit_name"] = spec.name
    return out


def rough_pnl(
    df: pd.DataFrame, sig: RetestSignal, exit_bars: int, target_r: float
) -> float:
    """Exit at stop (zone.lo), target R, or time stop - return pnl %."""
    return float(
        simulate_exit(df, sig, exit_bars=exit_bars, target_r=target_r)["pnl_pct"]
    )


def rough_r(
    df: pd.DataFrame, sig: RetestSignal, exit_bars: int, target_r: float
) -> float:
    """Same toy exit as rough_pnl, expressed in R multiples of (entry-stop)."""
    return float(
        simulate_exit(df, sig, exit_bars=exit_bars, target_r=target_r)["r_mult"]
    )


# ---------------------------------------------------------------------------
# Feb26 case helpers
# ---------------------------------------------------------------------------
def feb26_case_report(
    df: pd.DataFrame,
    zones: list[Zone],
    params: SysParams,
) -> dict:
    """Touch / signal detail for the 2026-02-26 max-vol zone."""
    target = pd.Timestamp("2026-02-26")
    z_oc = next((z for z in zones if z.kind == "OC" and z.max_vol_date.normalize() == target), None)
    z_hl = next((z for z in zones if z.kind == "HL" and z.max_vol_date.normalize() == target), None)
    atr = atr14(df)
    out: dict = {"found": z_oc is not None, "months": {}}

    for kind, z in (("OC", z_oc), ("HL", z_hl)):
        if z is None:
            continue
        touches = detect_touches(df, z, params.approach_lookback, eps_pct=params.retest_eps_pct)
        visits = _visit_summary(touches)
        breaks = detect_breaks(
            df, z, atr, params.break_pct, params.break_atr, params.break_window
        )
        sigs = generate_signals(df, z, touches, breaks, params, f"case_{kind}")

        # Attribute a visit to every month it spans (use all touch bars, not only last)
        month_visits: dict[str, list[TouchEvent]] = {"May": [], "Jun": [], "Jul": []}
        touches_by_visit: dict[int, list[TouchEvent]] = {}
        for t in touches:
            touches_by_visit.setdefault(t.visit_id, []).append(t)
        for vid, bars in touches_by_visit.items():
            months_hit: set[str] = set()
            for t in bars:
                if t.date.year != 2026:
                    continue
                if t.date.month == 5:
                    months_hit.add("May")
                elif t.date.month == 6:
                    months_hit.add("Jun")
                elif t.date.month == 7:
                    months_hit.add("Jul")
            rep = bars[-1]
            for mk in months_hit:
                month_visits[mk].append(rep)

        # near-miss May (low within eps of hi without full intersect of raw band)
        may = df[(df["Date"] >= "2026-05-01") & (df["Date"] <= "2026-05-31")]
        near_rows = []
        for _, row in may.iterrows():
            low = float(row["Low"])
            raw_hit = _bar_intersects(z.lo, z.hi, low, float(row["High"]))
            near = low <= z.hi * (1.0 + params.retest_eps_pct) and low >= z.hi * (
                1.0 - max(params.retest_eps_pct, 0.005)
            )
            if near or raw_hit:
                near_rows.append(
                    {
                        "date": str(pd.Timestamp(row["Date"]).date()),
                        "low": low,
                        "gap_to_hi": low - z.hi,
                        "raw_intersect": raw_hit,
                        "near_miss": near and not raw_hit,
                    }
                )

        out[kind] = {
            "zone": z,
            "n_visits_total": len(visits),
            "n_holds_total": sum(1 for v in visits if v.is_hold),
            "month_visits": {k: len(v) for k, v in month_visits.items()},
            "month_holds": {
                k: sum(1 for x in v if x.is_hold) for k, v in month_visits.items()
            },
            "month_dates": {
                k: [str(x.date.date()) for x in v] for k, v in month_visits.items()
            },
            "breaks": breaks,
            "signals": sigs,
            "signal_months": {
                "May": any(s.entry_date.month == 5 and s.entry_date.year == 2026 for s in sigs),
                "Jun": any(s.entry_date.month == 6 and s.entry_date.year == 2026 for s in sigs),
                "Jul": any(s.entry_date.month == 7 and s.entry_date.year == 2026 for s in sigs),
            },
            "may_near": near_rows,
        }
    return out


# ---------------------------------------------------------------------------
# Backtest / grid
# ---------------------------------------------------------------------------
@dataclass
class ZoneEvents:
    zone: Zone
    touches0: list[TouchEvent]
    touches_eps: dict[float, list[TouchEvent]] = field(default_factory=dict)
    breaks_by_key: dict[tuple[float, float], list[BreakEvent]] = field(default_factory=dict)


def precompute_zone_events(
    df: pd.DataFrame,
    zones: list[Zone],
    atr: np.ndarray,
    approach_lookback: int,
    eps_list: Iterable[float],
    break_pcts: Iterable[float],
    break_atrs: Iterable[float],
) -> list[ZoneEvents]:
    out: list[ZoneEvents] = []
    eps_list = list(eps_list)
    break_keys = list(itertools.product(break_pcts, break_atrs))
    for z in zones:
        ze = ZoneEvents(zone=z, touches0=detect_touches(df, z, approach_lookback, 0.0))
        for eps in eps_list:
            ze.touches_eps[eps] = detect_touches(df, z, approach_lookback, eps)
        for bp, ba in break_keys:
            ze.breaks_by_key[(bp, ba)] = detect_breaks(
                df, z, atr, bp, ba, break_window=None
            )
        out.append(ze)
    return out


def run_system(
    df: pd.DataFrame,
    zones: list[Zone],
    atr: np.ndarray,
    params: SysParams,
    params_tag: str,
    cached: list[ZoneEvents] | None = None,
) -> tuple[list[RetestSignal], list[float]]:
    signals: list[RetestSignal] = []
    if cached is None:
        for z in zones:
            if z.kind not in params.zone_kinds:
                continue
            touches_eps = detect_touches(
                df, z, params.approach_lookback, eps_pct=params.retest_eps_pct
            )
            breaks = detect_breaks(
                df, z, atr, params.break_pct, params.break_atr, params.break_window
            )
            signals.extend(
                generate_signals(df, z, touches_eps, breaks, params, params_tag)
            )
    else:
        for ze in cached:
            z = ze.zone
            if z.kind not in params.zone_kinds:
                continue
            touches_eps = ze.touches_eps.get(params.retest_eps_pct)
            if touches_eps is None:
                touches_eps = detect_touches(
                    df, z, params.approach_lookback, params.retest_eps_pct
                )
            breaks = ze.breaks_by_key.get((params.break_pct, params.break_atr))
            if breaks is None:
                breaks = detect_breaks(
                    df, z, atr, params.break_pct, params.break_atr, params.break_window
                )
            signals.extend(
                generate_signals(df, z, touches_eps, breaks, params, params_tag)
            )

    signals.sort(key=lambda s: (s.entry_idx, s.kind))
    seen: set[tuple[str, int]] = set()
    uniq: list[RetestSignal] = []
    for s in signals:
        key = (s.kind, s.entry_idx)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(s)

    pnls = [rough_pnl(df, s, params.exit_bars, params.target_r) for s in uniq]
    return uniq, pnls


def params_tag(p: SysParams) -> str:
    kinds = "+".join(p.zone_kinds)
    return (
        f"bp{p.break_pct:.3f}_ba{p.break_atr:.1f}_rw{p.retest_window}_"
        f"eps{p.retest_eps_pct:.3f}_mt{p.min_touches_before_entry}_"
        f"hold{int(p.count_only_holds)}_pre{int(p.count_pre_break_touches)}_"
        f"{kinds}"
    )


def _feb26_month_flags(sigs: list[RetestSignal]) -> tuple[bool, bool, bool]:
    may = jun = jul = False
    for s in sigs:
        if "2026-02-26" not in s.zone_id:
            continue
        if s.entry_date.year != 2026:
            continue
        if s.entry_date.month == 5:
            may = True
        elif s.entry_date.month == 6:
            jun = True
        elif s.entry_date.month == 7:
            jul = True
    return may, jun, jul


def grid_search(
    df: pd.DataFrame, zones: list[Zone], atr: np.ndarray
) -> list[ScanResult]:
    break_pcts = [0.0, 0.005]
    break_atrs = [0.0, 0.25]
    retest_windows = [63, 126]
    eps_list = [0.0, 0.005]
    min_touches = [0, 1, 2]
    count_holds = [False, True]
    zone_kind_opts: list[tuple[ZoneKind, ...]] = [("OC",), ("HL",), ("OC", "HL")]

    print("precomputing zone events for grid...")
    cached = precompute_zone_events(
        df,
        zones,
        atr,
        approach_lookback=5,
        eps_list=eps_list,
        break_pcts=break_pcts,
        break_atrs=break_atrs,
    )

    results: list[ScanResult] = []
    for bp, ba, rw, eps, mt, ch, kinds in itertools.product(
        break_pcts, break_atrs, retest_windows, eps_list, min_touches, count_holds, zone_kind_opts
    ):
        p = SysParams(
            break_pct=bp,
            break_atr=ba,
            retest_window=rw,
            retest_eps_pct=eps,
            min_touches_before_entry=mt,
            count_only_holds=ch,
            zone_kinds=kinds,
            first_retest_only=False,  # allow multi retests for Feb26 months
            count_pre_break_touches=True,
        )
        tag = params_tag(p)
        sigs, pnls = run_system(df, zones, atr, p, tag, cached=cached)
        n = len(sigs)
        wins = sum(1 for x in pnls if x > 0)
        wr = wins / n if n else 0.0
        avg = float(np.mean(pnls)) if pnls else 0.0
        may, jun, jul = _feb26_month_flags(sigs)

        results.append(
            ScanResult(
                params=p,
                signals=sigs,
                n_signals=n,
                n_wins=wins,
                win_rate=wr,
                avg_pnl_pct=avg,
                feb26_may=may,
                feb26_jun=jun,
                feb26_jul=jul,
                tag=tag,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------
def _draw_candles(ax, dates, o, h, l, c, lw_wick=0.5, lw_body=1.6) -> None:
    up = c >= o
    ax.vlines(dates, l, h, color="0.35", lw=lw_wick, zorder=2)
    body_lo = np.minimum(o, c)
    body_hi = np.maximum(o, c)
    if np.any(up):
        ax.vlines(dates[up], body_lo[up], body_hi[up], color="#2ca02c", lw=lw_body, zorder=3)
    if np.any(~up):
        ax.vlines(dates[~up], body_lo[~up], body_hi[~up], color="#d62728", lw=lw_body, zorder=3)


def plot_annotated(
    df: pd.DataFrame,
    zones: list[Zone],
    signals: list[RetestSignal],
    feb_case: dict,
    out_path: Path,
    *,
    start: str | None = None,
    end: str | None = None,
    title: str = "",
) -> None:
    mask = pd.Series(True, index=df.index)
    if start:
        mask &= df["Date"] >= start
    if end:
        mask &= df["Date"] <= end
    plot_df = df.loc[mask].copy()
    if plot_df.empty:
        return

    dates = plot_df["Date"]
    o = plot_df["Open"].to_numpy()
    h = plot_df["High"].to_numpy()
    l = plot_df["Low"].to_numpy()
    c = plot_df["Close"].to_numpy()

    fig_w = max(16.0, min(36.0, 8.0 + len(plot_df) / 60.0))
    fig, ax = plt.subplots(figsize=(fig_w, 8))
    _draw_candles(ax, dates, o, h, l, c, lw_wick=0.4, lw_body=1.4)

    # Highlight Feb26 OC+HL zones across plot window
    for kind, color, alpha in (("OC", "#1f77b4", 0.18), ("HL", "#9467bd", 0.10)):
        zinfo = feb_case.get(kind)
        if not zinfo:
            continue
        z: Zone = zinfo["zone"]
        d0 = max(pd.Timestamp(plot_df["Date"].iloc[0]), z.created_on)
        d1 = pd.Timestamp(plot_df["Date"].iloc[-1])
        ax.axhspan(z.lo, z.hi, color=color, alpha=alpha, zorder=1, label=f"Feb26 {kind} zone")
        ax.axvline(z.max_vol_date, color="#ff7f0e", ls="--", lw=1.2, alpha=0.85, label="Feb26 max-vol")

        for br in zinfo["breaks"]:
            if br.direction == "up" and start and br.date >= pd.Timestamp(start):
                ax.scatter(
                    [br.date],
                    [br.close],
                    marker="^",
                    s=90,
                    color="#2ca02c",
                    zorder=6,
                    edgecolors="black",
                    linewidths=0.4,
                    label="Break up" if kind == "OC" else None,
                )

    # All signals in window
    first_buy = True
    for s in signals:
        if start and s.entry_date < pd.Timestamp(start):
            continue
        if end and s.entry_date > pd.Timestamp(end):
            continue
        ax.scatter(
            [s.entry_date],
            [s.entry_price],
            marker="o",
            s=55,
            color="#d62728" if s.kind == "OC" else "#e377c2",
            zorder=7,
            edgecolors="white",
            linewidths=0.5,
            label=("Retest buy OC" if s.kind == "OC" else "Retest buy HL") if first_buy else None,
        )
        first_buy = False

    # Annotate May/Jun/Jul near Feb26
    for kind in ("OC", "HL"):
        zinfo = feb_case.get(kind)
        if not zinfo:
            continue
        for s in zinfo["signals"]:
            if s.entry_date.year != 2026 or s.entry_date.month not in (5, 6, 7):
                continue
            ax.annotate(
                f"{kind} {s.entry_date.strftime('%m-%d')}",
                xy=(s.entry_date, s.entry_price),
                xytext=(8, 12 if kind == "OC" else -18),
                textcoords="offset points",
                fontsize=8,
                color="#d62728" if kind == "OC" else "#9467bd",
                arrowprops=dict(arrowstyle="->", color="0.4", lw=0.7),
            )

    ax.set_title(title or "Vol-zone break -> retest")
    ax.set_ylabel("Price")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper left", fontsize=8)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:,.2f}"))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.autofmt_xdate()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)


def plot_full_history_signals(
    df: pd.DataFrame,
    signals: list[RetestSignal],
    out_path: Path,
    title: str,
) -> None:
    # downsample: weekly for older, daily recent
    n = len(df)
    if n > 900:
        cut = max(0, n - 504)
        older = (
            df.iloc[:cut]
            .set_index("Date")
            .resample("W-FRI")
            .agg(Open=("Open", "first"), High=("High", "max"), Low=("Low", "min"), Close=("Close", "last"))
            .dropna()
            .reset_index()
        )
        recent = df.iloc[cut:]
        if len(older) and len(recent):
            older = older[older["Date"] < recent["Date"].iloc[0]]
        plot_df = pd.concat([older, recent], ignore_index=True)
    else:
        plot_df = df

    fig, ax = plt.subplots(figsize=(28, 8))
    _draw_candles(
        ax,
        plot_df["Date"],
        plot_df["Open"].to_numpy(),
        plot_df["High"].to_numpy(),
        plot_df["Low"].to_numpy(),
        plot_df["Close"].to_numpy(),
        lw_wick=0.3,
        lw_body=1.0,
    )
    for s in signals:
        ax.scatter(
            [s.entry_date],
            [s.entry_price],
            marker="o",
            s=28,
            color="#d62728" if s.kind == "OC" else "#9467bd",
            zorder=5,
            alpha=0.85,
        )
    ax.set_title(title)
    ax.grid(True, alpha=0.25)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:,.2f}"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------
def write_html_report(
    out_path: Path,
    *,
    symbol: str,
    df: pd.DataFrame,
    zones: list[Zone],
    baseline: ScanResult,
    grid: list[ScanResult],
    feb_case: dict,
    feb_case_mt1: dict,
    chart_paths: dict[str, Path],
) -> None:
    n_oc = sum(1 for z in zones if z.kind == "OC")
    n_hl = sum(1 for z in zones if z.kind == "HL")

    def _sig_rows(sigs: list[RetestSignal], limit: int = 80) -> str:
        rows = ""
        for s in sigs[:limit]:
            rows += (
                "<tr>"
                f"<td>{html_mod.escape(s.zone_id)}</td>"
                f"<td>{s.kind}</td>"
                f"<td>{s.break_date.date()}</td>"
                f"<td>{s.entry_date.date()}</td>"
                f"<td>{s.entry_price:.2f}</td>"
                f"<td>{s.bars_after_break}</td>"
                f"<td>{s.touch_count_all}</td>"
                f"<td>{s.touch_count_holds}</td>"
                f"<td>{s.strength:.2f}</td>"
                "</tr>"
            )
        return rows

    # Prefer grid rows that catch May+Jun+Jul
    grid_sorted = sorted(
        grid,
        key=lambda r: (
            -(int(r.feb26_may) + int(r.feb26_jun) + int(r.feb26_jul)),
            -r.n_signals,
            -r.win_rate,
        ),
    )
    top = grid_sorted[:40]
    grid_rows = ""
    for r in top:
        p = r.params
        grid_rows += (
            "<tr>"
            f"<td>{p.break_pct:.3f}</td>"
            f"<td>{p.break_atr:.2f}</td>"
            f"<td>{p.retest_window}</td>"
            f"<td>{p.retest_eps_pct:.3f}</td>"
            f"<td>{p.min_touches_before_entry}</td>"
            f"<td>{'holds' if p.count_only_holds else 'all'}</td>"
            f"<td>{'+'.join(p.zone_kinds)}</td>"
            f"<td>{r.n_signals}</td>"
            f"<td>{r.win_rate * 100:.1f}</td>"
            f"<td>{r.avg_pnl_pct:.2f}</td>"
            f"<td>{'Y' if r.feb26_may else '-'}</td>"
            f"<td>{'Y' if r.feb26_jun else '-'}</td>"
            f"<td>{'Y' if r.feb26_jul else '-'}</td>"
            "</tr>"
        )

    def _month_block(case: dict, label: str) -> str:
        parts = [f"<h3>{html_mod.escape(label)}</h3>"]
        for kind in ("OC", "HL"):
            info = case.get(kind)
            if not info:
                continue
            z: Zone = info["zone"]
            sm = info["signal_months"]
            parts.append(
                f"<p><b>{kind}</b> zone [{z.lo:.2f}, {z.hi:.2f}] - "
                f"visits total={info['n_visits_total']} (holds={info['n_holds_total']}). "
                f"May/Jun/Jul visit counts: "
                f"{info['month_visits']['May']}/"
                f"{info['month_visits']['Jun']}/"
                f"{info['month_visits']['Jul']} "
                f"(holds {info['month_holds']['May']}/"
                f"{info['month_holds']['Jun']}/"
                f"{info['month_holds']['Jul']}). "
                f"Signals fire May={sm['May']} Jun={sm['Jun']} Jul={sm['Jul']}.</p>"
            )
            if info["month_dates"]["May"] or info["month_dates"]["Jun"] or info["month_dates"]["Jul"]:
                parts.append(
                    "<ul>"
                    f"<li>May dates: {', '.join(info['month_dates']['May']) or '-'}</li>"
                    f"<li>Jun dates: {', '.join(info['month_dates']['Jun']) or '-'}</li>"
                    f"<li>Jul dates: {', '.join(info['month_dates']['Jul']) or '-'}</li>"
                    "</ul>"
                )
            if info.get("may_near"):
                parts.append("<p>May near-miss / intersect detail:</p><ul>")
                for row in info["may_near"]:
                    parts.append(
                        f"<li>{row['date']}: low={row['low']:.2f} gap_to_hi={row['gap_to_hi']:.3f} "
                        f"raw_intersect={row['raw_intersect']} near_miss={row['near_miss']}</li>"
                    )
                parts.append("</ul>")
            if info["signals"]:
                parts.append("<ul>")
                for s in info["signals"]:
                    parts.append(
                        f"<li>entry {s.entry_date.date()} @ {s.entry_price:.2f} "
                        f"(touches_all={s.touch_count_all}, holds={s.touch_count_holds}, "
                        f"strength={s.strength:.2f})</li>"
                    )
                parts.append("</ul>")
        return "\n".join(parts)

    chart_imgs = ""
    for name, path in chart_paths.items():
        rel = path.name
        chart_imgs += f'<h3>{html_mod.escape(name)}</h3><p><img src="{html_mod.escape(rel)}" style="max-width:100%;border:1px solid #ddd"/></p>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>VolZone Break->Retest Hypothesis - {html_mod.escape(symbol)}</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:24px;max-width:1100px;color:#1a1a1a;line-height:1.45}}
h1,h2,h3{{margin-top:1.4em}}
code,pre{{background:#f4f4f5;padding:2px 6px;border-radius:4px}}
pre{{padding:12px;overflow:auto}}
table.sortable{{border-collapse:collapse;width:100%;font-size:13px;margin:12px 0}}
table.sortable th,table.sortable td{{border:1px solid #cbd5e1;padding:6px 8px;text-align:left}}
table.sortable thead{{background:#f1f5f9}}
.note{{background:#fff7ed;border-left:4px solid #f97316;padding:10px 14px;margin:16px 0}}
.callout{{background:#eff6ff;border-left:4px solid #3b82f6;padding:10px 14px;margin:16px 0}}
.small{{color:#64748b;font-size:12px}}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Vol-zone break -> retest - research hypothesis ({html_mod.escape(symbol)})</h1>
<p class="small">In-sample research on a single ticker. Not production. Data {df['Date'].iloc[0].date()} -> {df['Date'].iloc[-1].date()} ({len(df)} bars).</p>

<div class="callout">
<strong>One-pager hypothesis.</strong> Rolling 6-month (126-bar) max-volume days define persistent Open–Close (OC) and High–Low (HL) price zones.
After price <em>breaks out</em> above a zone and later <em>returns from above</em>, buy the first support retest (bar range intersects the zone, or low within a small epsilon of zone high).
Zones that have already shown successful holds (bounces without breakdown) are treated as stronger for the next retest; touch count is a tunable confidence filter, not a hard physical law.
Stops conceptually sit under zone.lo; first research focus is signal quality (does the Feb26->May/Jun/Jul pattern fire?), not fully optimized exits.
</div>

<h2>1. Event definitions</h2>
<ul>
<li><b>Zone creation</b>: each day after lookback, trailing-window max-volume bar identity; when a new winner appears, create OC and HL zones that persist forever.</li>
<li><b>Touch / hit (primary)</b>: bar high/low overlaps [lo, hi]. Alternatives noted: close-in-band, wick-only - primary is H–L overlap.</li>
<li><b>Visit dedupe</b>: ≤1 touch event logged per bar; contiguous intersecting bars share one <code>visit_id</code>; leaving the band starts a new visit.</li>
<li><b>Support</b>: approach from above (prior closes mostly &gt; zone.hi), then touch; <b>hold</b> if close stays ≥ mid/zone and does not close below zone.lo.</li>
<li><b>Resistance</b>: approach from below; hold if rejects without close above zone.hi.</li>
<li><b>Break up / down</b>: close beyond zone.hi / zone.lo by <code>break_pct</code> and/or <code>break_atr</code>×ATR14.</li>
<li><b>Retest buy</b>: after break-up, within <code>retest_window</code> bars, first (or each) from-above touch / near-miss; entry at close or next open.</li>
</ul>

<h2>2. Do we count hits? Does that increase importance?</h2>
<div class="note">
<p><b>Yes - count them, and use holds as a strength signal.</b></p>
<p>Every zone tracks how often price revisits it (OC and HL separately). A raw intersection is a <em>hit</em>; a hit that bounces without breaking is a <em>hold</em>. More successful holds generally raise confidence that the next retest is tradeable - the market has already “agreed” the band matters.</p>
<p>A failed hold / breakdown can flip the zone’s role (former support -> resistance) or reset strength. Pre-breakout resistance taps are optional: they can count toward recognition of the band, but post-breakout support holds are the more direct confirmation for long retests.</p>
<p>Knobs: <code>min_touches_before_entry</code> (0 = allow first retest after breakout; ≥1 requires prior visits/holds), <code>count_only_holds</code>, <code>count_pre_break_touches</code>, and optional <code>touch_decay_halflife</code> so recent visits weigh more.</p>
</div>

<h2>3. Parameter dictionary</h2>
<table class="sortable">
<thead><tr>
{sortable_th("Knob", "text")}
{sortable_th("Meaning", "text")}
{sortable_th("Suggested start / range", "text")}
</tr></thead>
<tbody>
<tr><td>lookback_days</td><td>Trailing bars for max-vol identity</td><td>126 (~6m); try 84–189</td></tr>
<tr><td>break_pct</td><td>Min close beyond zone edge</td><td>0–1%</td></tr>
<tr><td>break_atr</td><td>Min distance in ATR multiples</td><td>0–0.5</td></tr>
<tr><td>break_window</td><td>Bars after formation to allow breakout</td><td>None (anytime) or 63–252</td></tr>
<tr><td>require_hold_bars</td><td>Closes must stay beyond edge after break</td><td>0–3</td></tr>
<tr><td>retest_window</td><td>Bars after breakout for retest entry</td><td>63–189</td></tr>
<tr><td>retest_eps_pct</td><td>Near-miss: low within eps of zone.hi</td><td>0–0.5% (May almost-touch)</td></tr>
<tr><td>entry_on</td><td>close vs next_open</td><td>close (research)</td></tr>
<tr><td>first_retest_only</td><td>One entry per zone after breakout</td><td>True for baseline</td></tr>
<tr><td>zone_kinds</td><td>OC / HL / both</td><td>HL catches wider band; OC tighter</td></tr>
<tr><td>min_touches_before_entry</td><td>Prior visits/holds required</td><td>0–2</td></tr>
<tr><td>count_only_holds</td><td>Strength from holds only</td><td>False default; True = stricter</td></tr>
<tr><td>count_pre_break_touches</td><td>Pre-break taps count toward min_touches</td><td>True (recognition)</td></tr>
<tr><td>touch_decay_halflife</td><td>Recency weight on visits</td><td>None or ~21–63 bars</td></tr>
<tr><td>exit_bars / target_r</td><td>Lightweight exit for rough WR</td><td>20 bars / 2R to stop under zone.lo</td></tr>
</tbody>
</table>
<p class="small">Click column headers to sort.</p>

<h2>4. Zone inventory</h2>
<p>Unique max-vol winners -> <b>{n_oc}</b> OC zones and <b>{n_hl}</b> HL zones kept in memory for entire history after lookback.</p>

<h2>5. Feb 26, 2026 case (May / Jun / Jul)</h2>
{_month_block(feb_case, "Baseline params (min_touches=0, eps allows May near-miss)")}
{_month_block(feb_case_mt1, "Same but min_touches_before_entry=1")}
<p><b>OC vs HL for May almost-touch:</b> May-4 low (~194.74) sits ~0.45–0.47 above both OC hi (194.27) and HL hi (194.29) - raw H–L does <em>not</em> intersect either band. With <code>retest_eps_pct≈0.002–0.005</code> the near-miss counts as a retest touch for both; HL does not uniquely save May here because the wick never reached the day’s high. Jun and Jul do produce raw intersections on both OC and HL.</p>

<h2>6. Baseline scan ({html_mod.escape(baseline.tag)})</h2>
<p>Signals: <b>{baseline.n_signals}</b>; rough win-rate (stop under zone.lo, 2R or {baseline.params.exit_bars}d): <b>{baseline.win_rate*100:.1f}%</b>; avg pnl% <b>{baseline.avg_pnl_pct:.2f}</b>. Feb26 months May/Jun/Jul fire: {baseline.feb26_may}/{baseline.feb26_jun}/{baseline.feb26_jul}.</p>
<p class="small">Exit metrics are illustrative only - in-sample NVDA, not walk-forward.</p>
<table class="sortable">
<thead><tr>
{sortable_th("Zone", "text")}
{sortable_th("Kind", "text")}
{sortable_th("Break", "date")}
{sortable_th("Entry", "date")}
{sortable_th("Price", "num")}
{sortable_th("Bars after break", "num")}
{sortable_th("Touches", "num")}
{sortable_th("Holds", "num")}
{sortable_th("Strength", "num")}
</tr></thead>
<tbody>
{_sig_rows(baseline.signals)}
</tbody>
</table>

<h2>7. Light parameter grid (in-sample)</h2>
<p>Sorted toward catching Feb26 May+Jun+Jul, then signal count. Honest caveat: this is exploratory in-sample search on one symbol - treat as hypothesis shaping, not gold params.</p>
<table class="sortable">
<thead><tr>
{sortable_th("break_pct", "num")}
{sortable_th("break_atr", "num")}
{sortable_th("retest_win", "num")}
{sortable_th("eps", "num")}
{sortable_th("min_touch", "num")}
{sortable_th("count", "text")}
{sortable_th("kinds", "text")}
{sortable_th("N sig", "num")}
{sortable_th("WR%", "num")}
{sortable_th("AvgPnL%", "num")}
{sortable_th("May", "text")}
{sortable_th("Jun", "text")}
{sortable_th("Jul", "text")}
</tr></thead>
<tbody>
{grid_rows}
</tbody>
</table>

<h2>8. Charts</h2>
{chart_imgs}

<h2>9. Design notes - breakout distance &amp; retest timing</h2>
<ul>
<li><b>Min breakout distance</b>: pure close &gt; hi is enough to mark structure; a small <code>break_pct</code> or ATR buffer reduces noise fakeouts but can delay the “break” stamp used for the retest clock.</li>
<li><b>Retest timeframe</b>: Feb26 breakout (mid-Apr) -> May near-miss (~15–20 bars), Jun (~45–55), Jul (~70–80). A <code>retest_window</code> of ~126 bars covers all three; 63 may keep May/Jun but risk cutting late Jul depending on first-only vs multi-entry.</li>
<li><b>min_touches</b>: with 0, first post-break retest can fire on May (if eps on). With ≥1, May may still fire if March/April visits count (pre-break), or be delayed to Jun if only post-break holds count.</li>
</ul>

<p class="small">Generated by tools/vol_zone_break_retest.py - research only.</p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")


# ---------------------------------------------------------------------------
# Universe / PaulTwenty research freeze
# ---------------------------------------------------------------------------
def load_universe_symbols(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8-sig")
    syms: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        # allow csv header / extra cols
        tok = s.split(",")[0].strip().upper()
        if tok and tok not in ("SYMBOL", "TICKER"):
            syms.append(tok)
    # preserve order, dedupe
    out: list[str] = []
    seen: set[str] = set()
    for s in syms:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def count_up_breaks(
    df: pd.DataFrame,
    zones: list[Zone],
    atr: np.ndarray,
    params: SysParams,
) -> int:
    n = 0
    for z in zones:
        if z.kind not in params.zone_kinds:
            continue
        breaks = detect_breaks(
            df, z, atr, params.break_pct, params.break_atr, params.break_window
        )
        n += sum(1 for b in breaks if b.direction == "up")
    return n


# House book Ann ROR (rocket_tbn.compute_metrics / compare_format.ann_ror_from_closed).
# With fixed-notional sizing, brt_cash cancels: (1 + mean(pnl_pct/100)) ** (365/avg_days) - 1.
RESEARCH_BRT_CASH = 47500.0
DAYS_PER_YEAR = 365.0


def ann_ror_from_signal_rows(
    rows: list[dict],
    *,
    brt_cash: float = RESEARCH_BRT_CASH,
    days_per_year: float = DAYS_PER_YEAR,
) -> float:
    """Book Ann ROR % from research signal rows (pnl_pct + bars_held as days held)."""
    n = len(rows)
    if n <= 0 or brt_cash <= 0:
        return 0.0
    days = [float(r.get("bars_held", 0) or 0) for r in rows]
    days_pos = [d for d in days if d > 0]
    if not days_pos:
        return 0.0
    avg_days = float(np.mean(days_pos))
    total_pnl = float(sum(float(r["pnl_pct"]) / 100.0 * brt_cash for r in rows))
    base = 1.0 + total_pnl / (brt_cash * n)
    if base <= 0 or avg_days <= 0:
        return 0.0
    return float((base ** (days_per_year / avg_days) - 1.0) * 100.0)


def metrics_from_pnls(pnls: list[float], rs: list[float] | None = None) -> dict:
    n = len(pnls)
    wins = sum(1 for x in pnls if x > 0)
    losses = sum(1 for x in pnls if x < 0)
    win_pnls = [x for x in pnls if x > 0]
    loss_pnls = [x for x in pnls if x < 0]
    sum_wins = float(sum(win_pnls)) if win_pnls else 0.0
    sum_losses = float(abs(sum(loss_pnls))) if loss_pnls else 0.0
    avg_win = float(np.mean(win_pnls)) if win_pnls else 0.0
    avg_loss = float(np.mean(loss_pnls)) if loss_pnls else 0.0
    pf = (sum_wins / sum_losses) if sum_losses > 0 else (sum_wins if sum_wins > 0 else 0.0)
    wl_ratio = (avg_win / abs(avg_loss)) if avg_loss < 0 else (avg_win if avg_win > 0 else 0.0)
    max_win = float(max(win_pnls)) if win_pnls else 0.0
    outlier_wins = (100.0 * max_win / sum_wins) if sum_wins > 0 else 0.0
    total = float(sum(pnls)) if pnls else 0.0
    outlier_pnl = (100.0 * max_win / total) if total > 0 and max_win > 0 else 0.0
    # Top-10 wins share of total positive PnL% (book concentration).
    top10 = sorted(win_pnls, reverse=True)[:10]
    outlier_top10_wins = (100.0 * float(sum(top10)) / sum_wins) if sum_wins > 0 else 0.0
    return {
        "n_signals": n,
        "n_wins": wins,
        "n_losses": losses,
        "win_rate": (wins / n) if n else 0.0,
        "avg_pnl_pct": float(np.mean(pnls)) if pnls else 0.0,
        "expectancy_pct": float(np.mean(pnls)) if pnls else 0.0,
        "avg_r": float(np.mean(rs)) if rs else 0.0,
        "median_pnl_pct": float(np.median(pnls)) if pnls else 0.0,
        "ann_ror": 0.0,
        "avg_days_held": 0.0,
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss,
        "profit_factor": float(pf),
        "win_loss_ratio": float(wl_ratio),
        "outlier_pct_of_wins": float(outlier_wins),
        "outlier_pct_of_pnl": float(outlier_pnl),
        "outlier_top10_pct_of_wins": float(outlier_top10_wins),
        "max_dd_pct": 0.0,
        "calmar": 0.0,
        "capital_days": 0.0,
        "avg_concurrent": 0.0,
        "exposure_pct": 0.0,
        "span_days": 0.0,
        "passive_total_pnl": 0.0,
        "passive_max_dd_pct": 0.0,
        "agg_total_pnl": 0.0,
        "agg_max_dd_pct": 0.0,
        "agg_ann_ror": 0.0,
    }


def _equity_path_from_rows(
    rows: list[dict],
    *,
    notional: float,
    init_capital: float,
) -> tuple[float, float, float, float, float, float]:
    """Cash equity path (PnL realized at exit; no MTM).

    Returns
    ``(total_pnl, max_dd_pct, capital_days, avg_concurrent, span_days, time_in_market_pct)``.
    Exit date ≈ entry_date + bars_held calendar days (research proxy).
    ``time_in_market_pct`` = % of span days with ≥1 open slot.
    """
    if not rows or notional <= 0 or init_capital <= 0:
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
    opens: dict[pd.Timestamp, int] = {}
    closes: dict[pd.Timestamp, list[float]] = {}
    capital_days = 0.0
    for r in rows:
        ed = pd.Timestamp(r["entry_date"]).normalize()
        held = max(0, int(r.get("bars_held", 0) or 0))
        xd = ed + pd.Timedelta(days=max(held, 1))
        pnl = float(r["pnl_pct"]) / 100.0 * notional
        capital_days += float(held if held > 0 else 1)
        opens[ed] = opens.get(ed, 0) + 1
        closes.setdefault(xd, []).append(pnl)
    all_days = sorted(set(opens) | set(closes))
    if not all_days:
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
    span_days = float((all_days[-1] - all_days[0]).days + 1)
    equity = float(init_capital)
    peak = equity
    max_dd = 0.0
    open_n = 0
    conc_sum = 0.0
    conc_n = 0
    days_in_mkt = 0
    total_pnl = 0.0
    # Walk every calendar day in span so time-in-market is well-defined.
    d = all_days[0]
    end = all_days[-1]
    day_delta = pd.Timedelta(days=1)
    while d <= end:
        open_n += int(opens.get(d, 0))
        if open_n > 0:
            days_in_mkt += 1
        conc_sum += float(open_n)
        conc_n += 1
        for pnl in closes.get(d, []):
            equity += float(pnl)
            total_pnl += float(pnl)
            open_n = max(0, open_n - 1)
        if equity > peak:
            peak = equity
        if peak > 0:
            dd = (peak - equity) / peak * 100.0
            if dd > max_dd:
                max_dd = dd
        d = d + day_delta
    avg_conc = (conc_sum / conc_n) if conc_n else 0.0
    tim = (100.0 * days_in_mkt / conc_n) if conc_n else 0.0
    return (
        float(total_pnl),
        float(max_dd),
        float(capital_days),
        float(avg_conc),
        float(span_days),
        float(tim),
    )


def enrich_signal_rows(
    symbol: str,
    df: pd.DataFrame,
    sigs: list[RetestSignal],
    params: SysParams,
    *,
    atr: np.ndarray | None = None,
    exit_spec: ExitSpec | None = None,
) -> list[dict]:
    rows: list[dict] = []
    spec = exit_spec or ExitSpec(
        "toy",
        "Toy",
        exit_bars=params.exit_bars,
        target_r=params.target_r,
        stop_atr_buffer=0.0,
    )
    for s in sigs:
        sim = simulate_exit_spec(df, s, spec, atr=atr)
        rows.append(
            {
                "symbol": symbol,
                "zone_id": s.zone_id,
                "kind": s.kind,
                "break_date": str(s.break_date.date()),
                "entry_date": str(s.entry_date.date()),
                "entry_price": round(s.entry_price, 4),
                "stop": round(float(sim["stop"]), 4),
                "zone_lo": round(s.stop, 4),
                "bars_after_break": s.bars_after_break,
                "touch_count_all": s.touch_count_all,
                "touch_count_holds": s.touch_count_holds,
                "pre_break_touches": s.pre_break_touches,
                "post_break_touches": s.post_break_touches,
                "strength": round(s.strength, 3),
                "break_dist_pct": round(s.break_dist_pct, 5),
                "break_atr_mult": round(s.break_atr_mult, 3),
                "visit_n": s.visit_n,
                "pnl_pct": round(float(sim["pnl_pct"]), 4),
                "r_mult": round(float(sim["r_mult"]), 4),
                "win": int(float(sim["pnl_pct"]) > 0),
                "exit_reason": sim["exit_reason"],
                "bars_held": int(sim["bars_held"]),
                "exit_name": spec.name,
                "params_tag": s.params_tag,
            }
        )
    return rows


def split_is_oos(
    rows: list[dict], split: pd.Timestamp = OOS_SPLIT_DATE
) -> tuple[list[dict], list[dict]]:
    """Chronologic split by entry_date. IS = before split; OOS = on/after."""
    is_rows: list[dict] = []
    oos_rows: list[dict] = []
    for r in rows:
        d = pd.Timestamp(r["entry_date"])
        if d < split:
            is_rows.append(r)
        else:
            oos_rows.append(r)
    return is_rows, oos_rows


_OPEN_EXIT_REASONS = frozenset({"still_open", "end_of_data"})


def _closed_signal_rows(rows: list[dict]) -> list[dict]:
    """Drop end-of-history MTM rows — not realized exits."""
    out: list[dict] = []
    for r in rows:
        reason = str(r.get("exit_reason", "") or "").strip().lower()
        if reason in _OPEN_EXIT_REASONS:
            continue
        out.append(r)
    return out


def summarize_signal_dicts(rows: list[dict]) -> dict:
    rows = _closed_signal_rows(rows)
    if not rows:
        return metrics_from_pnls([])
    pnls = [float(r["pnl_pct"]) for r in rows]
    rs = [float(r["r_mult"]) for r in rows]
    m = metrics_from_pnls(pnls, rs)
    days = [float(r.get("bars_held", 0) or 0) for r in rows]
    days_pos = [d for d in days if d > 0]
    m["avg_days_held"] = float(np.mean(days_pos)) if days_pos else 0.0
    m["ann_ror"] = ann_ror_from_signal_rows(rows)

    # Passive fixed-notional book path (research proxy; not full OHLC MTM).
    # Init capital ≈ notional × avg concurrent so Max DD is a portfolio-ish %.
    notional = RESEARCH_BRT_CASH
    pas_pnl, pas_dd, cap_days, avg_conc, span, tim = _equity_path_from_rows(
        rows, notional=notional, init_capital=notional
    )
    pas_init = notional * max(avg_conc, 1.0)
    if abs(pas_init - notional) > 1e-9:
        pas_pnl, pas_dd, cap_days, avg_conc, span, tim = _equity_path_from_rows(
            rows, notional=notional, init_capital=pas_init
        )
    m["passive_total_pnl"] = pas_pnl
    m["passive_max_dd_pct"] = pas_dd
    m["max_dd_pct"] = pas_dd
    m["capital_days"] = cap_days
    m["avg_concurrent"] = avg_conc
    m["span_days"] = span
    m["exposure_pct"] = tim  # % of calendar span days with ≥1 open
    m["calmar"] = (m["ann_ror"] / pas_dd) if pas_dd > 1e-9 else 0.0

    # Aggressive proxy: same account init, ~2× buying power (house-like margin multiple).
    # Larger per-trade notional -> higher $PnL and typically higher Max DD.
    agg_multiple = 2.0
    agg_notional = notional * agg_multiple
    agg_pnl, agg_dd, _, _, _, _ = _equity_path_from_rows(
        rows, notional=agg_notional, init_capital=pas_init
    )
    m["agg_total_pnl"] = agg_pnl
    m["agg_max_dd_pct"] = agg_dd
    # Aggressive Ann ROR: house formula with larger notional as brt_cash.
    m["agg_ann_ror"] = ann_ror_from_signal_rows(rows, brt_cash=agg_notional)
    return m


def bucket_bars_after_break(bars: int) -> str:
    if bars <= 5:
        return "1-5"
    if bars <= 21:
        return "6-21"
    if bars <= 63:
        return "22-63"
    if bars <= 126:
        return "64-126"
    return "127+"


def bucket_break_dist(pct: float) -> str:
    p = abs(pct) * 100.0
    if p < 0.25:
        return "<0.25%"
    if p < 1.0:
        return "0.25-1%"
    if p < 3.0:
        return "1-3%"
    return ">=3%"


def slice_table(rows: list[dict], key_fn) -> list[tuple[str, dict]]:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        k = str(key_fn(r))
        groups.setdefault(k, []).append(r)
    out = [(k, summarize_signal_dicts(v)) for k, v in groups.items()]
    out.sort(key=lambda x: (-x[1]["n_signals"], x[0]))
    return out


def write_baseline_md(path: Path, *, stamp: str, universe_path: Path, n_symbols: int) -> None:
    p = RESEARCH_BASELINE
    md = f"""# Vol-zone break -> retest - research baseline (NOT production)

**Stamp:** `{stamp}`  
**Status:** Research freeze only - **not** production gold, **not** DailyRun-wired.  
**Universe:** `{universe_path.as_posix()}` ({n_symbols} symbols, full local history where CSV exists)

## Frozen knobs (NVDA-shaped hypothesis)

| Knob | Value |
|------|-------|
| lookback_days | {p.lookback_days} |
| zone_kinds | {", ".join(p.zone_kinds)} (report OC / HL / combined) |
| break_pct | {p.break_pct} (close above zone.hi) |
| break_atr | {p.break_atr} |
| retest_eps_pct | {p.retest_eps_pct} (0.5% near-miss) |
| retest_window | {p.retest_window} |
| first_retest_only | {p.first_retest_only} (multi-visit) |
| min_touches_before_entry | {p.min_touches_before_entry} (also slice metrics at ≥1) |
| count_only_holds | {p.count_only_holds} |
| count_pre_break_touches | {p.count_pre_break_touches} |
| entry_on | {p.entry_on} |
| Toy exit (signal quality only) | stop under zone.lo, target {p.target_r}R or {p.exit_bars}d |

## Honest caveats

- `retest_eps_pct=0.005` was tuned on the NVDA Feb26->May near-miss case (in-sample).
- Toy 2R / 20d exit is for **relative** signal quality ranking only - not a tradeable system exit.
- Full-history PaulTwenty scan is in-sample; no walk-forward claim.
- Do **not** treat this freeze as gold or wire into production runners.

## Outputs in this stamp folder

- `VolZone_PaulTwenty_Analysis.html` - pooled + per-symbol + slices
- `signals_baseline.csv` - all baseline signals
- `per_symbol_baseline.csv` - per-symbol aggregates
- `comparison.html` / `ab_results.csv` - small AB grid vs baseline (if run)
- `AB_PLAN.md` - AB plan + keep/dismiss notes
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md, encoding="utf-8")


def write_ab_plan_md(path: Path) -> None:
    md = """# Vol-zone PaulTwenty - AB plan (vs research baseline)

Baseline = RESEARCH_BASELINE (eps=0.005, OC+HL, min_touches=0, first_retest_only=False, retest_window=126).

| Arm | Change | Why |
|-----|--------|-----|
| 00_baseline | - | Control |
| 01_eps0 | retest_eps_pct=0 | Test NVDA-tuned near-miss; quality vs count |
| 02_oc_only | zone_kinds=OC | Tighter body band vs HL |
| 03_hl_only | zone_kinds=HL | Wider wick band |
| 04_mt1 | min_touches_before_entry=1 | Require prior visits |
| 05_first_only | first_retest_only=True | First post-break retest only |
| 06_rw63 | retest_window=63 | Shorter retest clock |

Judge on **quality over count**: win rate, avg R / expectancy, and whether WR holds with fewer signals. Prefer keep only if expectancy/WR improve without collapsing sample to noise.
"""
    path.write_text(md, encoding="utf-8")


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}"


def _fmt_num(x: float, nd: int = 2) -> str:
    return f"{x:.{nd}f}"


def _metrics_cells(m: dict, *, include_ann_ror: bool = False) -> str:
    cells = (
        f"<td>{m['n_signals']}</td>"
        f"<td>{_fmt_pct(m['win_rate'])}</td>"
        f"<td>{_fmt_num(m['avg_pnl_pct'])}</td>"
        f"<td>{_fmt_num(m['avg_r'])}</td>"
        f"<td>{_fmt_num(m.get('median_pnl_pct', 0.0))}</td>"
    )
    if include_ann_ror:
        cells += f"<td>{_fmt_num(m.get('ann_ror', 0.0))}</td>"
    return cells


def _metrics_headers(*, include_ann_ror: bool = False) -> str:
    headers = (
        f"{sortable_th('N sig', 'num')}"
        f"{sortable_th('WR%', 'num')}"
        f"{sortable_th('AvgPnL%', 'num')}"
        f"{sortable_th('AvgR', 'num')}"
        f"{sortable_th('MedPnL%', 'num')}"
    )
    if include_ann_ror:
        headers += f"{sortable_th('Ann ROR%', 'num')}"
    return headers


def write_paultwenty_analysis_html(
    out_path: Path,
    *,
    stamp: str,
    universe_path: Path,
    symbol_rows: list[dict],
    all_signals: list[dict],
    skipped: list[dict],
    csv_signals: Path,
    csv_per_symbol: Path,
) -> None:
    pooled = summarize_signal_dicts(all_signals)
    oc_rows = [r for r in all_signals if r["kind"] == "OC"]
    hl_rows = [r for r in all_signals if r["kind"] == "HL"]
    # cross-kind unique entry days (symbol+entry_date)
    seen_day: set[tuple[str, str]] = set()
    combined_dedupe: list[dict] = []
    for r in sorted(all_signals, key=lambda x: (x["symbol"], x["entry_date"], x["kind"])):
        key = (r["symbol"], r["entry_date"])
        if key in seen_day:
            continue
        seen_day.add(key)
        combined_dedupe.append(r)

    mt0 = all_signals  # baseline already mt>=0
    mt1 = [r for r in all_signals if int(r["touch_count_all"]) >= 1]
    mt2 = [r for r in all_signals if int(r["touch_count_all"]) >= 2]
    first_visit = [r for r in all_signals if int(r["visit_n"]) == 1]
    later_visit = [r for r in all_signals if int(r["visit_n"]) >= 2]

    timing = slice_table(all_signals, lambda r: bucket_bars_after_break(int(r["bars_after_break"])))
    break_dist = slice_table(all_signals, lambda r: bucket_break_dist(float(r["break_dist_pct"])))
    touch_dist = slice_table(all_signals, lambda r: str(int(r["touch_count_all"])))

    sym_body = ""
    for row in symbol_rows:
        status = row.get("status", "ok")
        if status != "ok":
            sym_body += (
                "<tr>"
                f"<td>{html_mod.escape(row['symbol'])}</td>"
                f"<td>{html_mod.escape(status)}</td>"
                f"<td colspan='11'>{html_mod.escape(str(row.get('note', '')))}</td>"
                "</tr>"
            )
            continue
        m = row["metrics"]
        sym_body += (
            "<tr>"
            f"<td>{html_mod.escape(row['symbol'])}</td>"
            f"<td>ok</td>"
            f"<td>{row['n_bars']}</td>"
            f"<td>{row['date_start']} -> {row['date_end']}</td>"
            f"<td>{row['n_zones']}</td>"
            f"<td>{row['n_breaks_up']}</td>"
            f"{_metrics_cells(m)}"
            f"<td>{row['n_oc_sig']}</td>"
            f"<td>{row['n_hl_sig']}</td>"
            "</tr>"
        )

    def slice_rows_html(slices: list[tuple[str, dict]]) -> str:
        body = ""
        for label, m in slices:
            body += f"<tr><td>{html_mod.escape(label)}</td>{_metrics_cells(m)}</tr>"
        return body

    skipped_html = ""
    if skipped:
        skipped_html = "<ul>" + "".join(
            f"<li><b>{html_mod.escape(s['symbol'])}</b>: {html_mod.escape(s['note'])}</li>"
            for s in skipped
        ) + "</ul>"
    else:
        skipped_html = "<p>None - all universe symbols had usable local CSVs.</p>"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>VolZone PaulTwenty Analysis - {html_mod.escape(stamp)}</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:24px;max-width:1200px;color:#1a1a1a;line-height:1.45}}
h1,h2,h3{{margin-top:1.4em}}
code{{background:#f4f4f5;padding:2px 6px;border-radius:4px}}
table.sortable{{border-collapse:collapse;width:100%;font-size:13px;margin:12px 0}}
table.sortable th,table.sortable td{{border:1px solid #cbd5e1;padding:6px 8px;text-align:left}}
table.sortable thead{{background:#f1f5f9}}
.note{{background:#fff7ed;border-left:4px solid #f97316;padding:10px 14px;margin:16px 0}}
.callout{{background:#eff6ff;border-left:4px solid #3b82f6;padding:10px 14px;margin:16px 0}}
.small{{color:#64748b;font-size:12px}}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Vol-zone break -> retest - PaulTwenty analysis</h1>
<p class="small">Stamp <code>{html_mod.escape(stamp)}</code> · Universe <code>{html_mod.escape(str(universe_path))}</code> · Research only - <b>not production gold</b>.</p>

<div class="note">
<strong>Caveats.</strong> Baseline knobs (esp. <code>retest_eps_pct=0.005</code>) were shaped on the NVDA Feb26 case (in-sample).
Toy exit = stop under zone.lo, 2R target or 20 bars - for relative signal quality only. Full-history scan is in-sample; no walk-forward or production claim.
</div>

<div class="callout">
<strong>Research baseline freeze.</strong> lookback=126 · OC+HL · break close &gt; zone.hi (pct=0, atr=0) ·
retest_eps=0.5% · retest_window=126 · first_retest_only=False · min_touches=0 · entry=close · toy exit 2R/20d.
See <code>BASELINE.md</code> in this folder.
</div>

<h2>1. Pooled summary</h2>
<p>Click column headers to sort.</p>
<table class="sortable">
<thead><tr>
{sortable_th("Slice", "text")}
{_metrics_headers()}
</tr></thead>
<tbody>
<tr><td>All (OC+HL, kind-deduped per entry bar)</td>{_metrics_cells(pooled)}</tr>
<tr><td>OC only</td>{_metrics_cells(summarize_signal_dicts(oc_rows))}</tr>
<tr><td>HL only</td>{_metrics_cells(summarize_signal_dicts(hl_rows))}</tr>
<tr><td>Combined unique symbol+entry_date</td>{_metrics_cells(summarize_signal_dicts(combined_dedupe))}</tr>
<tr><td>min_touches ≥0 (baseline)</td>{_metrics_cells(summarize_signal_dicts(mt0))}</tr>
<tr><td>min_touches ≥1 (slice)</td>{_metrics_cells(summarize_signal_dicts(mt1))}</tr>
<tr><td>min_touches ≥2 (slice)</td>{_metrics_cells(summarize_signal_dicts(mt2))}</tr>
<tr><td>First visit after break</td>{_metrics_cells(summarize_signal_dicts(first_visit))}</tr>
<tr><td>Later visits (visit_n≥2)</td>{_metrics_cells(summarize_signal_dicts(later_visit))}</tr>
</tbody>
</table>

<h2>2. Per-symbol</h2>
<table class="sortable">
<thead><tr>
{sortable_th("Symbol", "text")}
{sortable_th("Status", "text")}
{sortable_th("Bars", "num")}
{sortable_th("Date range", "text")}
{sortable_th("#Zones", "num")}
{sortable_th("#Breaks↑", "num")}
{_metrics_headers()}
{sortable_th("OC sig", "num")}
{sortable_th("HL sig", "num")}
</tr></thead>
<tbody>
{sym_body}
</tbody>
</table>

<h2>3. OC vs HL</h2>
<p>Baseline runs both Open–Close (OC) and High–Low (HL) zones; signals keep both kinds on the same entry bar (dedupe key = kind+entry_idx). Unique symbol+entry_date row above collapses same-day OC/HL pairs.</p>
<table class="sortable">
<thead><tr>
{sortable_th("Kind", "text")}
{_metrics_headers()}
</tr></thead>
<tbody>
<tr><td>OC</td>{_metrics_cells(summarize_signal_dicts(oc_rows))}</tr>
<tr><td>HL</td>{_metrics_cells(summarize_signal_dicts(hl_rows))}</tr>
</tbody>
</table>

<h2>4. Timing: bars break -> retest</h2>
<table class="sortable">
<thead><tr>
{sortable_th("Bars after break", "text")}
{_metrics_headers()}
</tr></thead>
<tbody>
{slice_rows_html(timing)}
</tbody>
</table>

<h2>5. Break distance at upside break</h2>
<table class="sortable">
<thead><tr>
{sortable_th("Break dist", "text")}
{_metrics_headers()}
</tr></thead>
<tbody>
{slice_rows_html(break_dist)}
</tbody>
</table>

<h2>6. Touch-count distribution (at entry)</h2>
<table class="sortable">
<thead><tr>
{sortable_th("touch_count_all", "text")}
{_metrics_headers()}
</tr></thead>
<tbody>
{slice_rows_html(touch_dist)}
</tbody>
</table>

<h2>7. Skipped / missing data</h2>
{skipped_html}

<h2>8. CSV artifacts</h2>
<ul>
<li><a href="{html_mod.escape(csv_signals.name)}">{html_mod.escape(csv_signals.name)}</a> - all baseline signals</li>
<li><a href="{html_mod.escape(csv_per_symbol.name)}">{html_mod.escape(csv_per_symbol.name)}</a> - per-symbol aggregates</li>
<li><code>BASELINE.md</code> - frozen research params</li>
<li><code>AB_PLAN.md</code> / <code>comparison.html</code> - AB grid (if present)</li>
</ul>

<p class="small">Generated by tools/vol_zone_break_retest.py - research only.</p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")


def ab_arm_params() -> list[tuple[str, SysParams, str]]:
    b = RESEARCH_BASELINE
    return [
        ("00_baseline", b, "Research baseline control"),
        ("01_eps0", replace(b, retest_eps_pct=0.0), "No near-miss eps"),
        ("02_oc_only", replace(b, zone_kinds=("OC",)), "OC zones only"),
        ("03_hl_only", replace(b, zone_kinds=("HL",)), "HL zones only"),
        ("04_mt1", replace(b, min_touches_before_entry=1), "Require ≥1 prior touch"),
        ("05_first_only", replace(b, first_retest_only=True), "First retest only"),
        ("06_rw63", replace(b, retest_window=63), "Shorter retest window"),
    ]


def lean_ab(arm: str, m: dict, ctrl: dict) -> tuple[str, str]:
    if arm == "00_baseline":
        return "CONTROL", "Baseline reference"
    n, wr, avg_r = m["n_signals"], m["win_rate"], m["avg_r"]
    c_n, c_wr, c_r = ctrl["n_signals"], ctrl["win_rate"], ctrl["avg_r"]
    if n < max(20, int(0.15 * c_n)):
        return "DISMISS", f"Sample collapsed ({n} vs ctrl {c_n})"
    d_wr = wr - c_wr
    d_r = avg_r - c_r
    better_wr = d_wr >= 0.015
    better_r = d_r >= 0.03
    worse_wr = d_wr <= -0.02
    worse_r = d_r <= -0.03
    if better_wr and better_r:
        return "KEEP", "WR and AvgR both improve vs baseline"
    if better_wr and d_r >= -0.02:
        return "LEAN KEEP", "WR up; AvgR roughly holds"
    if better_r and d_wr >= -0.015:
        return "LEAN KEEP", "AvgR up; WR roughly holds"
    if worse_wr and worse_r:
        return "DISMISS", "WR and AvgR both worse"
    if worse_wr or worse_r:
        return "DISMISS", "Quality regresses on WR or AvgR"
    if d_wr > 0 and d_r > 0:
        return "LEAN KEEP", "Small quality lift on both WR and AvgR"
    return "HOLD", "Mixed / flat vs baseline - no clear edge"


def write_ab_comparison_html(
    out_path: Path,
    *,
    stamp: str,
    ab_rows: list[dict],
) -> None:
    ctrl = next((r for r in ab_rows if r["arm"] == "00_baseline"), None)
    ctrl_m = (ctrl or {}).get("metrics") or metrics_from_pnls([])
    body = ""
    for r in ab_rows:
        m = r["metrics"]
        lean, why = lean_ab(r["arm"], m, ctrl_m)
        r["lean"] = lean
        r["lean_why"] = why
        d_n = m["n_signals"] - ctrl_m["n_signals"]
        d_wr = (m["win_rate"] - ctrl_m["win_rate"]) * 100
        d_r = m["avg_r"] - ctrl_m["avg_r"]
        body += (
            "<tr>"
            f"<td>{html_mod.escape(r['arm'])}</td>"
            f"<td>{html_mod.escape(r['note'])}</td>"
            f"{_metrics_cells(m)}"
            f"<td>{d_n:+d}</td>"
            f"<td>{d_wr:+.1f}</td>"
            f"<td>{d_r:+.2f}</td>"
            f"<td>{html_mod.escape(lean)}</td>"
            f"<td>{html_mod.escape(why)}</td>"
            "</tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>VolZone PaulTwenty AB - {html_mod.escape(stamp)}</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:24px;max-width:1200px;color:#1a1a1a;line-height:1.45}}
h1,h2{{margin-top:1.4em}}
code{{background:#f4f4f5;padding:2px 6px;border-radius:4px}}
table.sortable{{border-collapse:collapse;width:100%;font-size:13px;margin:12px 0}}
table.sortable th,table.sortable td{{border:1px solid #cbd5e1;padding:6px 8px;text-align:left}}
table.sortable thead{{background:#f1f5f9}}
.note{{background:#fff7ed;border-left:4px solid #f97316;padding:10px 14px;margin:16px 0}}
.small{{color:#64748b;font-size:12px}}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Vol-zone PaulTwenty - AB vs research baseline</h1>
<p class="small">Stamp <code>{html_mod.escape(stamp)}</code> · Toy exit 2R/20d · Click headers to sort · Not production gold.</p>
<div class="note">
Judge on quality over count. KEEP/LEAN KEEP only when WR and/or AvgR improve without collapsing N to noise.
</div>
<table class="sortable">
<thead><tr>
{sortable_th("Arm", "text")}
{sortable_th("Change", "text")}
{_metrics_headers()}
{sortable_th("ΔN", "num")}
{sortable_th("ΔWR_pp", "num")}
{sortable_th("ΔAvgR", "num")}
{sortable_th("Lean", "text")}
{sortable_th("Why", "text")}
</tr></thead>
<tbody>
{body}
</tbody>
</table>
<p class="small">Generated by tools/vol_zone_break_retest.py - research only.</p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    out_path.write_text(html, encoding="utf-8")


def run_symbol_with_params(
    symbol: str,
    df: pd.DataFrame,
    zones: list[Zone],
    atr: np.ndarray,
    params: SysParams,
    cached: list[ZoneEvents] | None = None,
) -> tuple[list[RetestSignal], list[float], list[float]]:
    tag = params_tag(params)
    sigs, pnls = run_system(df, zones, atr, params, tag, cached=cached)
    rs = [rough_r(df, s, params.exit_bars, params.target_r) for s in sigs]
    return sigs, pnls, rs


def run_paultwenty(
    *,
    universe_path: Path,
    data_dir: Path,
    out_dir: Path,
    stamp: str,
    lookback_days: int,
    run_ab: bool,
) -> None:
    symbols = load_universe_symbols(universe_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_baseline_md(
        out_dir / "BASELINE.md",
        stamp=stamp,
        universe_path=universe_path,
        n_symbols=len(symbols),
    )
    write_ab_plan_md(out_dir / "AB_PLAN.md")

    params = replace(RESEARCH_BASELINE, lookback_days=lookback_days)
    symbol_rows: list[dict] = []
    skipped: list[dict] = []
    all_signals: list[dict] = []
    # cache per symbol for AB
    caches: dict[str, tuple[pd.DataFrame, list[Zone], np.ndarray, list[ZoneEvents] | None]] = {}

    print(f"PaulTwenty run stamp={stamp} symbols={len(symbols)} lookback={lookback_days}")
    for sym in symbols:
        csv_path = data_dir / f"{sym}.csv"
        if not csv_path.is_file():
            note = f"missing CSV: {csv_path}"
            print(f"  SKIP {sym}: {note}")
            skipped.append({"symbol": sym, "note": note})
            symbol_rows.append({"symbol": sym, "status": "missing", "note": note})
            continue
        try:
            df = load_ohlcv(csv_path)
            atr = atr14(df)
            zones = build_zones(df, lookback_days)
        except Exception as e:  # noqa: BLE001 - research runner: note and continue
            note = str(e)
            print(f"  SKIP {sym}: {note}")
            skipped.append({"symbol": sym, "note": note})
            symbol_rows.append({"symbol": sym, "status": "error", "note": note})
            continue

        n_breaks = count_up_breaks(df, zones, atr, params)
        sigs, pnls, rs = run_symbol_with_params(sym, df, zones, atr, params)
        rows = enrich_signal_rows(sym, df, sigs, params)
        all_signals.extend(rows)
        m = metrics_from_pnls(pnls, rs)
        n_oc = sum(1 for s in sigs if s.kind == "OC")
        n_hl = sum(1 for s in sigs if s.kind == "HL")
        print(
            f"  {sym}: bars={len(df)} zones={len(zones)} breaks_up={n_breaks} "
            f"sig={m['n_signals']} WR={m['win_rate']*100:.1f}% AvgR={m['avg_r']:.2f}"
        )
        symbol_rows.append(
            {
                "symbol": sym,
                "status": "ok",
                "n_bars": len(df),
                "date_start": str(pd.Timestamp(df["Date"].iloc[0]).date()),
                "date_end": str(pd.Timestamp(df["Date"].iloc[-1]).date()),
                "n_zones": len(zones),
                "n_breaks_up": n_breaks,
                "metrics": m,
                "n_oc_sig": n_oc,
                "n_hl_sig": n_hl,
                "n_signals": m["n_signals"],
                "win_rate": m["win_rate"],
                "avg_pnl_pct": m["avg_pnl_pct"],
                "avg_r": m["avg_r"],
            }
        )
        caches[sym] = (df, zones, atr, None)

    # CSVs
    csv_signals = out_dir / "signals_baseline.csv"
    csv_per_symbol = out_dir / "per_symbol_baseline.csv"
    if all_signals:
        pd.DataFrame(all_signals).to_csv(csv_signals, index=False)
    else:
        pd.DataFrame(
            columns=[
                "symbol",
                "zone_id",
                "kind",
                "break_date",
                "entry_date",
                "entry_price",
                "pnl_pct",
                "r_mult",
            ]
        ).to_csv(csv_signals, index=False)

    per_flat = []
    for row in symbol_rows:
        if row.get("status") != "ok":
            per_flat.append(
                {
                    "symbol": row["symbol"],
                    "status": row["status"],
                    "note": row.get("note", ""),
                }
            )
            continue
        m = row["metrics"]
        per_flat.append(
            {
                "symbol": row["symbol"],
                "status": "ok",
                "n_bars": row["n_bars"],
                "date_start": row["date_start"],
                "date_end": row["date_end"],
                "n_zones": row["n_zones"],
                "n_breaks_up": row["n_breaks_up"],
                "n_signals": m["n_signals"],
                "win_rate": m["win_rate"],
                "avg_pnl_pct": m["avg_pnl_pct"],
                "avg_r": m["avg_r"],
                "n_oc_sig": row["n_oc_sig"],
                "n_hl_sig": row["n_hl_sig"],
            }
        )
    pd.DataFrame(per_flat).to_csv(csv_per_symbol, index=False)

    html_path = out_dir / "VolZone_PaulTwenty_Analysis.html"
    write_paultwenty_analysis_html(
        html_path,
        stamp=stamp,
        universe_path=universe_path,
        symbol_rows=symbol_rows,
        all_signals=all_signals,
        skipped=skipped,
        csv_signals=csv_signals,
        csv_per_symbol=csv_per_symbol,
    )
    pooled = summarize_signal_dicts(all_signals)
    print(
        f"POOLED signals={pooled['n_signals']} WR={pooled['win_rate']*100:.1f}% "
        f"AvgPnL%={pooled['avg_pnl_pct']:.2f} AvgR={pooled['avg_r']:.2f}"
    )
    print(f"saved: {html_path}")
    print(f"saved: {csv_signals}")
    print(f"saved: {csv_per_symbol}")

    if not run_ab:
        print("AB skipped (pass --run-ab to execute small grid).")
        return

    # Precompute caches for AB eps/break keys used across arms
    eps_needed = sorted({a[1].retest_eps_pct for a in ab_arm_params()})
    break_pcts = sorted({a[1].break_pct for a in ab_arm_params()})
    break_atrs = sorted({a[1].break_atr for a in ab_arm_params()})
    print("precomputing zone events for AB...")
    for sym, (df, zones, atr, _) in list(caches.items()):
        cached = precompute_zone_events(
            df,
            zones,
            atr,
            approach_lookback=params.approach_lookback,
            eps_list=eps_needed,
            break_pcts=break_pcts,
            break_atrs=break_atrs,
        )
        caches[sym] = (df, zones, atr, cached)

    ab_rows: list[dict] = []
    ab_signal_frames: list[pd.DataFrame] = []
    for arm, arm_params, note in ab_arm_params():
        arm_params = replace(arm_params, lookback_days=lookback_days)
        all_rows: list[dict] = []
        for sym, (df, zones, atr, cached) in caches.items():
            sigs, _, _ = run_symbol_with_params(
                sym, df, zones, atr, arm_params, cached=cached
            )
            all_rows.extend(enrich_signal_rows(sym, df, sigs, arm_params))
        m = summarize_signal_dicts(all_rows)
        print(
            f"  AB {arm}: N={m['n_signals']} WR={m['win_rate']*100:.1f}% "
            f"AvgR={m['avg_r']:.2f} - {note}"
        )
        ab_rows.append({"arm": arm, "note": note, "metrics": m})
        if all_rows:
            df_arm = pd.DataFrame(all_rows)
            df_arm.insert(0, "arm", arm)
            ab_signal_frames.append(df_arm)

    # attach leans for CSV
    ctrl_m = ab_rows[0]["metrics"]
    for r in ab_rows:
        lean, why = lean_ab(r["arm"], r["metrics"], ctrl_m)
        r["lean"] = lean
        r["lean_why"] = why

    ab_csv = out_dir / "ab_results.csv"
    pd.DataFrame(
        [
            {
                "arm": r["arm"],
                "note": r["note"],
                "n_signals": r["metrics"]["n_signals"],
                "win_rate": r["metrics"]["win_rate"],
                "avg_pnl_pct": r["metrics"]["avg_pnl_pct"],
                "avg_r": r["metrics"]["avg_r"],
                "lean": r["lean"],
                "lean_why": r["lean_why"],
            }
            for r in ab_rows
        ]
    ).to_csv(ab_csv, index=False)
    if ab_signal_frames:
        pd.concat(ab_signal_frames, ignore_index=True).to_csv(
            out_dir / "signals_ab_all.csv", index=False
        )

    # append keep/dismiss to AB_PLAN
    plan_path = out_dir / "AB_PLAN.md"
    lines = ["\n## Results (auto)\n", "| Arm | N | WR% | AvgR | Lean | Why |", "|-----|---|-----|------|------|-----|"]
    for r in ab_rows:
        m = r["metrics"]
        lines.append(
            f"| {r['arm']} | {m['n_signals']} | {m['win_rate']*100:.1f} | "
            f"{m['avg_r']:.2f} | {r['lean']} | {r['lean_why']} |"
        )
    plan_path.write_text(plan_path.read_text(encoding="utf-8") + "\n".join(lines) + "\n", encoding="utf-8")

    cmp_path = out_dir / "comparison.html"
    write_ab_comparison_html(cmp_path, stamp=stamp, ab_rows=ab_rows)
    print(f"saved: {cmp_path}")
    print(f"saved: {ab_csv}")


# ---------------------------------------------------------------------------
# Research candidate v2 - HL-primary + quality gates + exit/OOS honesty
# ---------------------------------------------------------------------------
def write_candidate_v2_baseline_md(
    path: Path, *, stamp: str, universe_path: Path, n_symbols: int
) -> None:
    p = RESEARCH_CANDIDATE_V2
    md = f"""# Vol-zone break -> retest - research candidate v2 (NOT production)

**Stamp:** `{stamp}`  
**Status:** Research candidate only - **not** production gold, **not** DailyRun-wired.  
**Universe:** `{universe_path.as_posix()}` ({n_symbols} symbols, full local history where CSV exists)  
**Prior freeze:** `vol_zone_paultwenty_20260810` (OC+HL, multi-visit, min_touches=0, toy 2R/20d)

## Candidate knobs (HL-primary + quality gates)

| Knob | Value | vs prior baseline |
|------|-------|-------------------|
| lookback_days | {p.lookback_days} | same |
| zone_kinds | {", ".join(p.zone_kinds)} | was OC+HL -> **HL-primary** |
| break_pct / break_atr | {p.break_pct} / {p.break_atr} | same |
| retest_eps_pct | {p.retest_eps_pct} | same (keep; eps=0 dismissed) |
| retest_window | {p.retest_window} | same (AB may test 63) |
| first_retest_only | {p.first_retest_only} | was False -> **True** |
| min_touches_before_entry | {p.min_touches_before_entry} | was 0 -> **≥1** |
| entry_on | {p.entry_on} | same |
| Primary exit for ranking | toy 2R/{p.exit_bars}d at zone.lo | plus zone-ATR buffer exits in report |

## Honest caveats

- `retest_eps_pct=0.005` was tuned on the NVDA Feb26->May near-miss case (**in-sample**). Do not treat as OOS-validated.
- HL-primary + first_retest + min_touches≥1 came from the prior PaulTwenty AB (same history) - still **in-sample selection**.
- Chronologic split: IS = entry_date &lt; 2024-01-01; OOS = 2024+ holdout. **Do not retune on holdout.**
- Exits remain research ranking tools (toy vs zone.lo−k·ATR). Not a tradeable system claim.
- Do **not** wire into DailyRun or claim gold.

## Outputs in this stamp folder

- `VolZone_HL_Quality_v2.html` - candidate vs prior baseline, IS/OOS, exit compare, small AB
- `signals_candidate.csv` / `per_symbol_candidate.csv`
- `exit_comparison.csv` / `oos_split.csv` / `ab_results.csv`
- `BASELINE.md` / `AB_PLAN.md`
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md, encoding="utf-8")


def write_candidate_v2_ab_plan_md(path: Path) -> None:
    md = """# Vol-zone HL-quality candidate v2 - small AB

Control = RESEARCH_CANDIDATE_V2 (HL-only, first_retest_only=True, min_touches≥1, eps=0.005, retest_window=126).

| Arm | Change | Why |
|-----|--------|-----|
| 00_candidate | - | Control (lean-keep stack from prior AB) |
| 01_mt2 | min_touches_before_entry=2 | Stricter prior-touch filter |
| 02_rw63 | retest_window=63 | Shorter retest clock on HL+gates |

Judge on **quality over count** vs candidate control. KEEP/LEAN KEEP only if WR and/or AvgR improve without collapsing N. Do **not** retune using 2024+ OOS.
"""
    path.write_text(md, encoding="utf-8")


def candidate_ab_arm_params() -> list[tuple[str, SysParams, str]]:
    c = RESEARCH_CANDIDATE_V2
    return [
        ("00_candidate", c, "HL + first_retest + mt>=1"),
        ("01_mt2", replace(c, min_touches_before_entry=2), "min_touches>=2"),
        ("02_rw63", replace(c, retest_window=63), "retest_window=63 on HL+gates"),
    ]


def _exit_mix(rows: list[dict]) -> str:
    if not rows:
        return "-"
    from collections import Counter

    c = Counter(str(r.get("exit_reason", "?")) for r in rows)
    total = sum(c.values()) or 1
    parts = [f"{k}={v / total * 100:.0f}%" for k, v in sorted(c.items())]
    return ", ".join(parts)


def write_candidate_v2_html(
    out_path: Path,
    *,
    stamp: str,
    universe_path: Path,
    prior_stamp: str,
    candidate_params: SysParams,
    prior_metrics: dict,
    cand_metrics: dict,
    symbol_rows: list[dict],
    all_signals: list[dict],
    is_metrics: dict,
    oos_metrics: dict,
    exit_rows: list[dict],
    ab_rows: list[dict],
    recommendation: str,
    skipped: list[dict],
) -> None:
    split_s = str(OOS_SPLIT_DATE.date())
    p = candidate_params

    d_n = cand_metrics["n_signals"] - prior_metrics["n_signals"]
    d_wr = (cand_metrics["win_rate"] - prior_metrics["win_rate"]) * 100
    d_r = cand_metrics["avg_r"] - prior_metrics["avg_r"]

    sym_body = ""
    for row in symbol_rows:
        status = row.get("status", "ok")
        if status != "ok":
            sym_body += (
                "<tr>"
                f"<td>{html_mod.escape(row['symbol'])}</td>"
                f"<td>{html_mod.escape(status)}</td>"
                f"<td colspan='9'>{html_mod.escape(str(row.get('note', '')))}</td>"
                "</tr>"
            )
            continue
        m = row["metrics"]
        m_is = row.get("metrics_is") or metrics_from_pnls([])
        m_oos = row.get("metrics_oos") or metrics_from_pnls([])
        sym_body += (
            "<tr>"
            f"<td>{html_mod.escape(row['symbol'])}</td>"
            f"<td>ok</td>"
            f"<td>{row['n_bars']}</td>"
            f"<td>{row['date_start']} -> {row['date_end']}</td>"
            f"{_metrics_cells(m)}"
            f"<td>{m_is['n_signals']}</td>"
            f"<td>{_fmt_pct(m_is['win_rate'])}</td>"
            f"<td>{m_oos['n_signals']}</td>"
            f"<td>{_fmt_pct(m_oos['win_rate'])}</td>"
            "</tr>"
        )

    exit_body = ""
    for er in exit_rows:
        m = er["metrics"]
        exit_body += (
            "<tr>"
            f"<td>{html_mod.escape(er['name'])}</td>"
            f"<td>{html_mod.escape(er['label'])}</td>"
            f"{_metrics_cells(m)}"
            f"<td>{html_mod.escape(er.get('exit_mix', '-'))}</td>"
            f"<td>{html_mod.escape(er.get('note', ''))}</td>"
            "</tr>"
        )

    ab_body = ""
    ctrl_m = ab_rows[0]["metrics"] if ab_rows else metrics_from_pnls([])
    for r in ab_rows:
        m = r["metrics"]
        lean = r.get("lean", "")
        why = r.get("lean_why", "")
        d_n_ab = m["n_signals"] - ctrl_m["n_signals"]
        d_wr_ab = (m["win_rate"] - ctrl_m["win_rate"]) * 100
        d_r_ab = m["avg_r"] - ctrl_m["avg_r"]
        ab_body += (
            "<tr>"
            f"<td>{html_mod.escape(r['arm'])}</td>"
            f"<td>{html_mod.escape(r['note'])}</td>"
            f"{_metrics_cells(m)}"
            f"<td>{d_n_ab:+d}</td>"
            f"<td>{d_wr_ab:+.1f}</td>"
            f"<td>{d_r_ab:+.2f}</td>"
            f"<td>{html_mod.escape(lean)}</td>"
            f"<td>{html_mod.escape(why)}</td>"
            "</tr>"
        )

    skipped_html = (
        "<ul>"
        + "".join(
            f"<li><b>{html_mod.escape(s['symbol'])}</b>: {html_mod.escape(s['note'])}</li>"
            for s in skipped
        )
        + "</ul>"
        if skipped
        else "<p>None.</p>"
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>VolZone HL Quality v2 - {html_mod.escape(stamp)}</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:24px;max-width:1200px;color:#1a1a1a;line-height:1.45}}
h1,h2,h3{{margin-top:1.4em}}
code{{background:#f4f4f5;padding:2px 6px;border-radius:4px}}
table.sortable{{border-collapse:collapse;width:100%;font-size:13px;margin:12px 0}}
table.sortable th,table.sortable td{{border:1px solid #cbd5e1;padding:6px 8px;text-align:left}}
table.sortable thead{{background:#f1f5f9}}
.note{{background:#fff7ed;border-left:4px solid #f97316;padding:10px 14px;margin:16px 0}}
.callout{{background:#eff6ff;border-left:4px solid #3b82f6;padding:10px 14px;margin:16px 0}}
.ok{{background:#f0fdf4;border-left:4px solid #22c55e;padding:10px 14px;margin:16px 0}}
.small{{color:#64748b;font-size:12px}}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Vol-zone HL-quality - research candidate v2</h1>
<p class="small">Stamp <code>{html_mod.escape(stamp)}</code> · Universe <code>{html_mod.escape(str(universe_path))}</code> · Prior <code>{html_mod.escape(prior_stamp)}</code> · <b>Not production gold</b>.</p>

<div class="note">
<strong>Caveats.</strong> <code>retest_eps_pct=0.005</code> was shaped on NVDA Feb26 (in-sample).
HL+gates were selected from the prior PaulTwenty AB on the same history (in-sample selection).
OOS = entry dates on/after {split_s}; do not retune on holdout. Exits are ranking tools only.
</div>

<div class="callout">
<strong>Candidate v2 knobs.</strong>
lookback={p.lookback_days} · zone_kinds={"+".join(p.zone_kinds)} ·
retest_eps={p.retest_eps_pct} · retest_window={p.retest_window} ·
first_retest_only={p.first_retest_only} · min_touches≥{p.min_touches_before_entry} ·
entry={p.entry_on}. See <code>BASELINE.md</code>.
</div>

<h2>1. Candidate vs prior baseline (toy exit)</h2>
<p>Click column headers to sort. Prior = OC+HL, multi-visit, min_touches=0. Candidate = HL + first_retest + mt≥1. Same toy exit (zone.lo / 2R / 20d).</p>
<table class="sortable">
<thead><tr>
{sortable_th("Rule set", "text")}
{_metrics_headers()}
{sortable_th("ΔN", "num")}
{sortable_th("ΔWR pp", "num")}
{sortable_th("ΔAvgR", "num")}
</tr></thead>
<tbody>
<tr><td>Prior baseline ({html_mod.escape(prior_stamp)})</td>{_metrics_cells(prior_metrics)}<td>-</td><td>-</td><td>-</td></tr>
<tr><td>Candidate v2 (HL+gates)</td>{_metrics_cells(cand_metrics)}<td>{d_n:+d}</td><td>{d_wr:+.1f}</td><td>{d_r:+.2f}</td></tr>
</tbody>
</table>

<h2>2. IS vs OOS (candidate, toy exit)</h2>
<p>IS = entry_date &lt; {split_s}. OOS = entry_date ≥ {split_s} (holdout - not used to choose knobs).</p>
<table class="sortable">
<thead><tr>
{sortable_th("Split", "text")}
{_metrics_headers()}
</tr></thead>
<tbody>
<tr><td>In-sample (&lt;{split_s})</td>{_metrics_cells(is_metrics)}</tr>
<tr><td>OOS holdout (≥{split_s})</td>{_metrics_cells(oos_metrics)}</tr>
<tr><td>Full history</td>{_metrics_cells(cand_metrics)}</tr>
</tbody>
</table>

<h2>3. Exit comparison (same candidate signals)</h2>
<p>Same HL+gates entries; only stop / time recipe changes. Zone-stop = zone.lo − k·ATR14 at entry.</p>
<table class="sortable">
<thead><tr>
{sortable_th("Exit", "text")}
{sortable_th("Recipe", "text")}
{_metrics_headers()}
{sortable_th("Exit mix", "text")}
{sortable_th("Note", "text")}
</tr></thead>
<tbody>
{exit_body}
</tbody>
</table>

<h2>4. Per-symbol (candidate, toy)</h2>
<table class="sortable">
<thead><tr>
{sortable_th("Symbol", "text")}
{sortable_th("Status", "text")}
{sortable_th("Bars", "num")}
{sortable_th("Date range", "text")}
{_metrics_headers()}
{sortable_th("IS N", "num")}
{sortable_th("IS WR%", "num")}
{sortable_th("OOS N", "num")}
{sortable_th("OOS WR%", "num")}
</tr></thead>
<tbody>
{sym_body}
</tbody>
</table>

<h2>5. Small AB on HL+gates</h2>
<p>Control = candidate v2. Optional tighteners only.</p>
<table class="sortable">
<thead><tr>
{sortable_th("Arm", "text")}
{sortable_th("Change", "text")}
{_metrics_headers()}
{sortable_th("ΔN", "num")}
{sortable_th("ΔWR pp", "num")}
{sortable_th("ΔAvgR", "num")}
{sortable_th("Lean", "text")}
{sortable_th("Why", "text")}
</tr></thead>
<tbody>
{ab_body}
</tbody>
</table>

<div class="ok">
<strong>Next-step recommendation.</strong> {html_mod.escape(recommendation)}
</div>

<h2>6. Skipped / missing</h2>
{skipped_html}

<p class="small">Generated by tools/vol_zone_break_retest.py --candidate-v2 - research only.</p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")


def _recommend_candidate_v2(
    prior_m: dict,
    cand_m: dict,
    is_m: dict,
    oos_m: dict,
    exit_rows: list[dict],
    ab_rows: list[dict],
) -> str:
    parts: list[str] = []
    d_wr = (cand_m["win_rate"] - prior_m["win_rate"]) * 100
    d_r = cand_m["avg_r"] - prior_m["avg_r"]
    parts.append(
        f"Candidate vs prior: N {cand_m['n_signals']} (dN {cand_m['n_signals']-prior_m['n_signals']:+d}), "
        f"WR {cand_m['win_rate']*100:.1f}% ({d_wr:+.1f}pp), AvgR {cand_m['avg_r']:.2f} ({d_r:+.2f})."
    )
    if oos_m["n_signals"] > 0 and is_m["n_signals"] > 0:
        oos_gap = (oos_m["win_rate"] - is_m["win_rate"]) * 100
        parts.append(
            f"OOS WR {oos_m['win_rate']*100:.1f}% vs IS {is_m['win_rate']*100:.1f}% "
            f"({oos_gap:+.1f}pp on N_oos={oos_m['n_signals']})."
        )
        if oos_gap <= -5 or (oos_m["avg_r"] - is_m["avg_r"]) <= -0.15:
            parts.append("OOS softens vs IS - treat HL+gates as provisional, not gold.")
        elif oos_gap >= -2 and oos_m["avg_r"] >= is_m["avg_r"] - 0.05:
            parts.append("OOS roughly holds IS quality - still research-only.")
        else:
            parts.append("OOS mixed vs IS - keep researching exits before any claim.")
    # best exit by AvgR among non-toy if better
    toy = next((e for e in exit_rows if e["name"] == "toy"), None)
    alts = [e for e in exit_rows if e["name"] != "toy"]
    if toy and alts:
        best = max(alts, key=lambda e: e["metrics"]["avg_r"])
        if best["metrics"]["avg_r"] > toy["metrics"]["avg_r"] + 0.02:
            parts.append(
                f"Prefer {best['name']} over toy on AvgR "
                f"({best['metrics']['avg_r']:.2f} vs {toy['metrics']['avg_r']:.2f}); "
                "still not a production exit."
            )
        else:
            parts.append("Zone-ATR exits do not clearly beat toy on AvgR - keep toy for ranking.")
    for r in ab_rows:
        if r["arm"] == "00_candidate":
            continue
        lean = r.get("lean", "HOLD")
        parts.append(f"AB {r['arm']}: {lean} - {r.get('lean_why', '')}.")
    parts.append(
        "Next: walk-forward on a larger universe or true forward paper with zone-ATR stop; "
        "do not DailyRun-wire yet."
    )
    return " ".join(parts)


def run_candidate_v2(
    *,
    universe_path: Path,
    data_dir: Path,
    out_dir: Path,
    stamp: str,
    lookback_days: int,
    run_ab: bool,
    prior_stamp: str = "vol_zone_paultwenty_20260810",
) -> None:
    symbols = load_universe_symbols(universe_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_candidate_v2_baseline_md(
        out_dir / "BASELINE.md",
        stamp=stamp,
        universe_path=universe_path,
        n_symbols=len(symbols),
    )
    write_candidate_v2_ab_plan_md(out_dir / "AB_PLAN.md")

    prior_params = replace(RESEARCH_BASELINE, lookback_days=lookback_days)
    cand_params = replace(RESEARCH_CANDIDATE_V2, lookback_days=lookback_days)
    toy_exit = EXIT_SPECS[0]

    caches: dict[str, tuple[pd.DataFrame, list[Zone], np.ndarray, list[ZoneEvents] | None]] = {}
    symbol_rows: list[dict] = []
    skipped: list[dict] = []
    prior_signals: list[dict] = []
    cand_signals: list[dict] = []
    # raw signals for exit replay
    cand_raw: dict[str, list[RetestSignal]] = {}

    print(f"Candidate v2 stamp={stamp} symbols={len(symbols)} lookback={lookback_days}")
    for sym in symbols:
        csv_path = data_dir / f"{sym}.csv"
        if not csv_path.is_file():
            note = f"missing CSV: {csv_path}"
            print(f"  SKIP {sym}: {note}")
            skipped.append({"symbol": sym, "note": note})
            symbol_rows.append({"symbol": sym, "status": "missing", "note": note})
            continue
        try:
            df = load_ohlcv(csv_path)
            atr = atr14(df)
            zones = build_zones(df, lookback_days)
        except Exception as e:  # noqa: BLE001
            note = str(e)
            print(f"  SKIP {sym}: {note}")
            skipped.append({"symbol": sym, "note": note})
            symbol_rows.append({"symbol": sym, "status": "error", "note": note})
            continue

        prior_sigs, _, _ = run_symbol_with_params(sym, df, zones, atr, prior_params)
        prior_rows = enrich_signal_rows(sym, df, prior_sigs, prior_params, atr=atr, exit_spec=toy_exit)
        prior_signals.extend(prior_rows)

        cand_sigs, _, _ = run_symbol_with_params(sym, df, zones, atr, cand_params)
        cand_rows = enrich_signal_rows(sym, df, cand_sigs, cand_params, atr=atr, exit_spec=toy_exit)
        cand_signals.extend(cand_rows)
        cand_raw[sym] = cand_sigs
        caches[sym] = (df, zones, atr, None)

        m = summarize_signal_dicts(cand_rows)
        is_r, oos_r = split_is_oos(cand_rows)
        m_is = summarize_signal_dicts(is_r)
        m_oos = summarize_signal_dicts(oos_r)
        print(
            f"  {sym}: cand N={m['n_signals']} WR={m['win_rate']*100:.1f}% "
            f"IS={m_is['n_signals']}/{m_is['win_rate']*100:.1f}% "
            f"OOS={m_oos['n_signals']}/{m_oos['win_rate']*100:.1f}%"
        )
        symbol_rows.append(
            {
                "symbol": sym,
                "status": "ok",
                "n_bars": len(df),
                "date_start": str(pd.Timestamp(df["Date"].iloc[0]).date()),
                "date_end": str(pd.Timestamp(df["Date"].iloc[-1]).date()),
                "metrics": m,
                "metrics_is": m_is,
                "metrics_oos": m_oos,
                "n_signals": m["n_signals"],
                "win_rate": m["win_rate"],
                "avg_pnl_pct": m["avg_pnl_pct"],
                "avg_r": m["avg_r"],
            }
        )

    prior_m = summarize_signal_dicts(prior_signals)
    cand_m = summarize_signal_dicts(cand_signals)
    is_rows, oos_rows = split_is_oos(cand_signals)
    is_m = summarize_signal_dicts(is_rows)
    oos_m = summarize_signal_dicts(oos_rows)

    print(
        f"PRIOR  N={prior_m['n_signals']} WR={prior_m['win_rate']*100:.1f}% AvgR={prior_m['avg_r']:.2f}"
    )
    print(
        f"CAND   N={cand_m['n_signals']} WR={cand_m['win_rate']*100:.1f}% AvgR={cand_m['avg_r']:.2f}"
    )
    print(
        f"IS     N={is_m['n_signals']} WR={is_m['win_rate']*100:.1f}% AvgR={is_m['avg_r']:.2f}"
    )
    print(
        f"OOS    N={oos_m['n_signals']} WR={oos_m['win_rate']*100:.1f}% AvgR={oos_m['avg_r']:.2f}"
    )

    # Exit comparison on same candidate signals
    exit_rows: list[dict] = []
    exit_signal_frames: list[pd.DataFrame] = []
    for spec in EXIT_SPECS:
        rows: list[dict] = []
        for sym, (df, _zones, atr, _) in caches.items():
            sigs = cand_raw.get(sym, [])
            rows.extend(
                enrich_signal_rows(sym, df, sigs, cand_params, atr=atr, exit_spec=spec)
            )
        m = summarize_signal_dicts(rows)
        note = "primary ranking exit (matches prior stamp)" if spec.name == "toy" else "zone-aware stop research"
        exit_rows.append(
            {
                "name": spec.name,
                "label": spec.label,
                "metrics": m,
                "exit_mix": _exit_mix(rows),
                "note": note,
            }
        )
        print(
            f"  EXIT {spec.name}: N={m['n_signals']} WR={m['win_rate']*100:.1f}% "
            f"AvgR={m['avg_r']:.2f} mix={_exit_mix(rows)}"
        )
        if rows:
            exit_signal_frames.append(pd.DataFrame(rows))

    # Small AB
    ab_rows: list[dict] = []
    if run_ab:
        eps_needed = sorted({a[1].retest_eps_pct for a in candidate_ab_arm_params()})
        break_pcts = sorted({a[1].break_pct for a in candidate_ab_arm_params()})
        break_atrs = sorted({a[1].break_atr for a in candidate_ab_arm_params()})
        print("precomputing zone events for candidate AB...")
        for sym, (df, zones, atr, _) in list(caches.items()):
            cached = precompute_zone_events(
                df,
                zones,
                atr,
                approach_lookback=cand_params.approach_lookback,
                eps_list=eps_needed,
                break_pcts=break_pcts,
                break_atrs=break_atrs,
            )
            caches[sym] = (df, zones, atr, cached)

        for arm, arm_params, note in candidate_ab_arm_params():
            arm_params = replace(arm_params, lookback_days=lookback_days)
            all_rows: list[dict] = []
            for sym, (df, zones, atr, cached) in caches.items():
                sigs, _, _ = run_symbol_with_params(
                    sym, df, zones, atr, arm_params, cached=cached
                )
                all_rows.extend(
                    enrich_signal_rows(
                        sym, df, sigs, arm_params, atr=atr, exit_spec=toy_exit
                    )
                )
            m = summarize_signal_dicts(all_rows)
            ab_rows.append({"arm": arm, "note": note, "metrics": m})
            print(
                f"  AB {arm}: N={m['n_signals']} WR={m['win_rate']*100:.1f}% "
                f"AvgR={m['avg_r']:.2f} - {note}"
            )

        ctrl_m = ab_rows[0]["metrics"]
        for r in ab_rows:
            lean, why = lean_ab(r["arm"], r["metrics"], ctrl_m)
            if r["arm"] == "00_candidate":
                lean, why = "CONTROL", "Candidate v2 reference"
            r["lean"] = lean
            r["lean_why"] = why
    else:
        ab_rows = [
            {
                "arm": "00_candidate",
                "note": "HL + first_retest + mt>=1",
                "metrics": cand_m,
                "lean": "CONTROL",
                "lean_why": "AB skipped",
            }
        ]

    recommendation = _recommend_candidate_v2(
        prior_m, cand_m, is_m, oos_m, exit_rows, ab_rows
    )

    # CSVs
    csv_signals = out_dir / "signals_candidate.csv"
    csv_per = out_dir / "per_symbol_candidate.csv"
    pd.DataFrame(cand_signals).to_csv(csv_signals, index=False) if cand_signals else pd.DataFrame().to_csv(csv_signals, index=False)

    per_flat = []
    for row in symbol_rows:
        if row.get("status") != "ok":
            per_flat.append(
                {"symbol": row["symbol"], "status": row["status"], "note": row.get("note", "")}
            )
            continue
        m, m_is, m_oos = row["metrics"], row["metrics_is"], row["metrics_oos"]
        per_flat.append(
            {
                "symbol": row["symbol"],
                "status": "ok",
                "n_bars": row["n_bars"],
                "date_start": row["date_start"],
                "date_end": row["date_end"],
                "n_signals": m["n_signals"],
                "win_rate": m["win_rate"],
                "avg_pnl_pct": m["avg_pnl_pct"],
                "avg_r": m["avg_r"],
                "is_n": m_is["n_signals"],
                "is_wr": m_is["win_rate"],
                "is_avg_r": m_is["avg_r"],
                "oos_n": m_oos["n_signals"],
                "oos_wr": m_oos["win_rate"],
                "oos_avg_r": m_oos["avg_r"],
            }
        )
    pd.DataFrame(per_flat).to_csv(csv_per, index=False)

    pd.DataFrame(
        [
            {
                "exit": e["name"],
                "label": e["label"],
                "n_signals": e["metrics"]["n_signals"],
                "win_rate": e["metrics"]["win_rate"],
                "avg_pnl_pct": e["metrics"]["avg_pnl_pct"],
                "avg_r": e["metrics"]["avg_r"],
                "exit_mix": e["exit_mix"],
                "note": e["note"],
            }
            for e in exit_rows
        ]
    ).to_csv(out_dir / "exit_comparison.csv", index=False)

    pd.DataFrame(
        [
            {
                "split": "IS",
                "split_date": str(OOS_SPLIT_DATE.date()),
                "n_signals": is_m["n_signals"],
                "win_rate": is_m["win_rate"],
                "avg_pnl_pct": is_m["avg_pnl_pct"],
                "avg_r": is_m["avg_r"],
            },
            {
                "split": "OOS",
                "split_date": str(OOS_SPLIT_DATE.date()),
                "n_signals": oos_m["n_signals"],
                "win_rate": oos_m["win_rate"],
                "avg_pnl_pct": oos_m["avg_pnl_pct"],
                "avg_r": oos_m["avg_r"],
            },
            {
                "split": "FULL",
                "split_date": str(OOS_SPLIT_DATE.date()),
                "n_signals": cand_m["n_signals"],
                "win_rate": cand_m["win_rate"],
                "avg_pnl_pct": cand_m["avg_pnl_pct"],
                "avg_r": cand_m["avg_r"],
            },
            {
                "split": "PRIOR_BASELINE",
                "split_date": str(OOS_SPLIT_DATE.date()),
                "n_signals": prior_m["n_signals"],
                "win_rate": prior_m["win_rate"],
                "avg_pnl_pct": prior_m["avg_pnl_pct"],
                "avg_r": prior_m["avg_r"],
            },
        ]
    ).to_csv(out_dir / "oos_split.csv", index=False)

    if exit_signal_frames:
        pd.concat(exit_signal_frames, ignore_index=True).to_csv(
            out_dir / "signals_exit_all.csv", index=False
        )

    ab_csv = out_dir / "ab_results.csv"
    pd.DataFrame(
        [
            {
                "arm": r["arm"],
                "note": r["note"],
                "n_signals": r["metrics"]["n_signals"],
                "win_rate": r["metrics"]["win_rate"],
                "avg_pnl_pct": r["metrics"]["avg_pnl_pct"],
                "avg_r": r["metrics"]["avg_r"],
                "lean": r.get("lean", ""),
                "lean_why": r.get("lean_why", ""),
            }
            for r in ab_rows
        ]
    ).to_csv(ab_csv, index=False)

    # append AB results to plan
    plan_path = out_dir / "AB_PLAN.md"
    lines = [
        "\n## Results (auto)\n",
        "| Arm | N | WR% | AvgR | Lean | Why |",
        "|-----|---|-----|------|------|-----|",
    ]
    for r in ab_rows:
        m = r["metrics"]
        lines.append(
            f"| {r['arm']} | {m['n_signals']} | {m['win_rate']*100:.1f} | "
            f"{m['avg_r']:.2f} | {r.get('lean', '')} | {r.get('lean_why', '')} |"
        )
    lines.append("\n## Recommendation\n")
    lines.append(recommendation + "\n")
    plan_path.write_text(
        plan_path.read_text(encoding="utf-8") + "\n".join(lines) + "\n", encoding="utf-8"
    )

    html_path = out_dir / "VolZone_HL_Quality_v2.html"
    write_candidate_v2_html(
        html_path,
        stamp=stamp,
        universe_path=universe_path,
        prior_stamp=prior_stamp,
        candidate_params=cand_params,
        prior_metrics=prior_m,
        cand_metrics=cand_m,
        symbol_rows=symbol_rows,
        all_signals=cand_signals,
        is_metrics=is_m,
        oos_metrics=oos_m,
        exit_rows=exit_rows,
        ab_rows=ab_rows,
        recommendation=recommendation,
        skipped=skipped,
    )
    print(f"saved: {html_path}")
    print(f"saved: {csv_signals}")
    print(f"saved: {csv_per}")
    print(f"RECOMMENDATION: {recommendation}")


# ---------------------------------------------------------------------------
# Research candidate v2 + primary exit freeze - step-5 ABs under zone_atr05_ts40
# ---------------------------------------------------------------------------
def write_v2_exit_ab_baseline_md(
    path: Path, *, stamp: str, universe_path: Path, n_symbols: int, prior_stamp: str
) -> None:
    p = RESEARCH_CANDIDATE_V2
    e = PRIMARY_EXIT
    md = f"""# Vol-zone v2 + zone_atr05_ts40 - research candidate exit freeze (NOT gold)

**Stamp:** `{stamp}`  
**Status:** Research candidate only - **not** production gold, **not** DailyRun-wired.  
**Universe:** `{universe_path.as_posix()}` ({n_symbols} symbols, full local history where CSV exists)  
**Prior entry stamp:** `{prior_stamp}` (HL-quality candidate v2)  
**Prior baseline:** `vol_zone_paultwenty_20260810` (OC+HL, multi-visit, mt=0, toy exit)

## Frozen entry = candidate v2

| Knob | Value |
|------|-------|
| lookback_days | {p.lookback_days} |
| zone_kinds | {", ".join(p.zone_kinds)} (HL-only) |
| break_pct / break_atr | {p.break_pct} / {p.break_atr} |
| retest_eps_pct | {p.retest_eps_pct} |
| retest_window | {p.retest_window} |
| first_retest_only | {p.first_retest_only} |
| min_touches_before_entry | {p.min_touches_before_entry} |
| entry_on | {p.entry_on} |

## Frozen primary exit = `{e.name}` (research ranking)

| Piece | Formula / value |
|-------|-----------------|
| Stop | `zone.lo − 0.5 · ATR14[entry]` |
| Target | `{e.target_r}R` from entry vs stop distance |
| Time stop | `{e.exit_bars}` bars |
| Toy reference | stop=`zone.lo`, 2R / 20d (side-by-side only - not primary) |

## Label

**Research candidate exit** for step-5 ABs. Exit was chosen **in-sample** on PaulTwenty after comparing exits under candidate-v2 entries (highest AvgR / PnL% among compared exits). Re-report IS/OOS under this exit before interpreting ABs. Do **not** treat as production gold.

## Honest caveats

- Exit selection bias: `zone_atr05_ts40` won an in-sample exit horse-race on the same PaulTwenty history used for ABs.
- Entry knobs (HL / first_retest / mt≥1 / eps) were also selected in-sample on prior stamps.
- Chronologic split: IS = entry_date &lt; 2024-01-01; OOS = 2024+ holdout. **Do not retune on holdout.**
- Do **not** wire into DailyRun or claim gold.

## Outputs in this stamp folder

- `comparison.html` - freeze metrics, toy reference, IS/OOS, entry ABs, exit ABs
- `signals_primary.csv` / `per_symbol_primary.csv`
- `exit_side_by_side.csv` / `oos_split.csv` / `ab_results.csv` / `exit_ab_results.csv`
- `BASELINE.md` / `AB_PLAN.md`
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md, encoding="utf-8")


def write_v2_exit_ab_plan_md(path: Path) -> None:
    md = """# Vol-zone v2 exit freeze - AB plan (scored on zone_atr05_ts40)

Control = RESEARCH_CANDIDATE_V2 entries + primary exit `zone_atr05_ts40`
(stop = zone.lo − 0.5·ATR, target 2R, time stop 40d).

## Entry ABs (one change at a time; same primary exit)

| Arm | Change | Why |
|-----|--------|-----|
| 00_freeze | - | Control (v2 entry + zone_atr05_ts40) |
| 01_rw63 | retest_window=63 | Prior lean-keep under toy; re-check under primary exit |
| 02_mt0 | min_touches_before_entry=0 | Challenge: drop prior-touch gate |
| 03_mt2 | min_touches_before_entry=2 | Challenge: tighten prior-touch gate |
| 04_multi | first_retest_only=False | Challenge: allow later retest visits |
| 05_oc_only | zone_kinds=OC | Confirm HL still wins under this exit |
| 06_both | zone_kinds=OC+HL | Confirm HL-only still preferred |
| 07_eps0 | retest_eps_pct=0 | Confirm dismiss eps=0 |
| 08_break_pct05 | break_pct=0.005 | Optional cheap break minimum |
| 09_break_atr05 | break_atr=0.5 | Optional ATR break minimum |

## Exit ABs (same freeze entries; label as EXIT - not entry claims)

| Arm | Change |
|-----|--------|
| EXIT_ts20 | zone.lo−0.5·ATR, 2R / 20d |
| EXIT_ts40 | zone.lo−0.5·ATR, 2R / 40d (control) |
| EXIT_ts60 | zone.lo−0.5·ATR, 2R / 60d |

Judge on **quality over count** (WR, AvgR, AvgPnL%/expectancy). KEEP/LEAN KEEP only if quality improves without collapsing N. Do **not** retune using 2024+ OOS.
"""
    path.write_text(md, encoding="utf-8")


def v2_exit_entry_ab_arms() -> list[tuple[str, SysParams, str]]:
    c = RESEARCH_CANDIDATE_V2
    return [
        ("00_freeze", c, "v2 entry + zone_atr05_ts40 control"),
        ("01_rw63", replace(c, retest_window=63), "retest_window=63"),
        ("02_mt0", replace(c, min_touches_before_entry=0), "min_touches>=0 (challenge)"),
        ("03_mt2", replace(c, min_touches_before_entry=2), "min_touches>=2 (challenge)"),
        ("04_multi", replace(c, first_retest_only=False), "first_retest_only=False"),
        ("05_oc_only", replace(c, zone_kinds=("OC",)), "OC-only zones"),
        ("06_both", replace(c, zone_kinds=("OC", "HL")), "OC+HL zones"),
        ("07_eps0", replace(c, retest_eps_pct=0.0), "retest_eps_pct=0"),
        ("08_break_pct05", replace(c, break_pct=0.005), "break_pct=0.5%"),
        ("09_break_atr05", replace(c, break_atr=0.5), "break_atr=0.5"),
    ]


def lean_ab_v2_exit(arm: str, m: dict, ctrl: dict) -> tuple[str, str]:
    if arm in ("00_freeze", "EXIT_ts40"):
        return "CONTROL", "Freeze / exit control reference"
    n, wr, avg_r, avg_pnl = m["n_signals"], m["win_rate"], m["avg_r"], m["avg_pnl_pct"]
    c_n, c_wr, c_r, c_pnl = (
        ctrl["n_signals"],
        ctrl["win_rate"],
        ctrl["avg_r"],
        ctrl["avg_pnl_pct"],
    )
    if n < max(20, int(0.15 * c_n)):
        return "DISMISS", f"Sample collapsed ({n} vs ctrl {c_n})"
    d_wr = wr - c_wr
    d_r = avg_r - c_r
    d_pnl = avg_pnl - c_pnl
    better_wr = d_wr >= 0.015
    better_r = d_r >= 0.03
    better_pnl = d_pnl >= 0.15  # percentage points of pnl%
    worse_wr = d_wr <= -0.02
    worse_r = d_r <= -0.03
    worse_pnl = d_pnl <= -0.15
    if better_wr and better_r:
        return "KEEP", "WR and AvgR both improve vs freeze"
    if (better_r or better_pnl) and d_wr >= -0.015:
        return "LEAN KEEP", "AvgR/PnL up; WR roughly holds"
    if better_wr and d_r >= -0.02:
        return "LEAN KEEP", "WR up; AvgR roughly holds"
    if worse_wr and worse_r:
        return "DISMISS", "WR and AvgR both worse"
    if worse_wr or worse_r or worse_pnl:
        return "DISMISS", "Quality regresses on WR, AvgR, or PnL%"
    if d_wr > 0 and d_r > 0:
        return "LEAN KEEP", "Small quality lift on both WR and AvgR"
    return "HOLD", "Mixed / flat vs freeze - no clear edge"


def _keep_dismiss_note(arm: str, lean: str, why: str) -> str:
    if lean == "CONTROL":
        return "Reference freeze"
    if lean in ("KEEP", "LEAN KEEP"):
        return f"{lean}: {why}"
    if lean == "DISMISS":
        return f"DISMISS: {why}"
    return f"HOLD: {why}"


def write_v2_exit_comparison_html(
    out_path: Path,
    *,
    stamp: str,
    universe_path: Path,
    prior_stamp: str,
    freeze_params: SysParams,
    primary_exit: ExitSpec,
    freeze_m: dict,
    toy_m: dict,
    is_m: dict,
    oos_m: dict,
    symbol_rows: list[dict],
    entry_ab_rows: list[dict],
    exit_ab_rows: list[dict],
    recommendation: str,
    exit_answer: str,
    skipped: list[dict],
) -> None:
    split_s = str(OOS_SPLIT_DATE.date())
    p = freeze_params
    e = primary_exit

    oos_gap_wr = (oos_m["win_rate"] - is_m["win_rate"]) * 100 if is_m["n_signals"] and oos_m["n_signals"] else 0.0
    oos_gap_r = (oos_m["avg_r"] - is_m["avg_r"]) if is_m["n_signals"] and oos_m["n_signals"] else 0.0
    softens = oos_gap_wr <= -5 or oos_gap_r <= -0.15

    def ab_body(rows: list[dict], ctrl_m: dict) -> str:
        body = ""
        for r in rows:
            m = r["metrics"]
            d_n = m["n_signals"] - ctrl_m["n_signals"]
            d_wr = (m["win_rate"] - ctrl_m["win_rate"]) * 100
            d_r = m["avg_r"] - ctrl_m["avg_r"]
            d_pnl = m["avg_pnl_pct"] - ctrl_m["avg_pnl_pct"]
            body += (
                "<tr>"
                f"<td>{html_mod.escape(r['arm'])}</td>"
                f"<td>{html_mod.escape(r['note'])}</td>"
                f"{_metrics_cells(m)}"
                f"<td>{_fmt_num(m.get('expectancy_pct', m['avg_pnl_pct']))}</td>"
                f"<td>{d_n:+d}</td>"
                f"<td>{d_wr:+.1f}</td>"
                f"<td>{d_r:+.2f}</td>"
                f"<td>{d_pnl:+.2f}</td>"
                f"<td>{html_mod.escape(r.get('lean', ''))}</td>"
                f"<td>{html_mod.escape(r.get('keep_note', r.get('lean_why', '')))}</td>"
                "</tr>"
            )
        return body

    entry_ctrl = next((r["metrics"] for r in entry_ab_rows if r["arm"] == "00_freeze"), freeze_m)
    exit_ctrl = next((r["metrics"] for r in exit_ab_rows if r["arm"] == "EXIT_ts40"), freeze_m)

    sym_body = ""
    for row in symbol_rows:
        if row.get("status") != "ok":
            sym_body += (
                "<tr>"
                f"<td>{html_mod.escape(row['symbol'])}</td>"
                f"<td>{html_mod.escape(row.get('status', ''))}</td>"
                f"<td colspan='10'>{html_mod.escape(str(row.get('note', '')))}</td>"
                "</tr>"
            )
            continue
        m = row["metrics"]
        m_is = row.get("metrics_is") or metrics_from_pnls([])
        m_oos = row.get("metrics_oos") or metrics_from_pnls([])
        sym_body += (
            "<tr>"
            f"<td>{html_mod.escape(row['symbol'])}</td>"
            f"<td>ok</td>"
            f"<td>{row['n_bars']}</td>"
            f"<td>{row['date_start']} -> {row['date_end']}</td>"
            f"{_metrics_cells(m)}"
            f"<td>{m_is['n_signals']}</td>"
            f"<td>{_fmt_pct(m_is['win_rate'])}</td>"
            f"<td>{m_oos['n_signals']}</td>"
            f"<td>{_fmt_pct(m_oos['win_rate'])}</td>"
            "</tr>"
        )

    skipped_html = (
        "<ul>"
        + "".join(
            f"<li><b>{html_mod.escape(s['symbol'])}</b>: {html_mod.escape(s['note'])}</li>"
            for s in skipped
        )
        + "</ul>"
        if skipped
        else "<p>None.</p>"
    )

    softens_txt = (
        f"Yes - OOS softens vs IS (ΔWR {oos_gap_wr:+.1f}pp, ΔAvgR {oos_gap_r:+.2f})."
        if softens
        else f"OOS does not clearly soften (ΔWR {oos_gap_wr:+.1f}pp, ΔAvgR {oos_gap_r:+.2f}) - still research-only."
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>VolZone v2 exit AB - {html_mod.escape(stamp)}</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:24px;max-width:1240px;color:#1a1a1a;line-height:1.45}}
h1,h2,h3{{margin-top:1.4em}}
code{{background:#f4f4f5;padding:2px 6px;border-radius:4px}}
table.sortable{{border-collapse:collapse;width:100%;font-size:13px;margin:12px 0}}
table.sortable th,table.sortable td{{border:1px solid #cbd5e1;padding:6px 8px;text-align:left}}
table.sortable thead{{background:#f1f5f9}}
.note{{background:#fff7ed;border-left:4px solid #f97316;padding:10px 14px;margin:16px 0}}
.callout{{background:#eff6ff;border-left:4px solid #3b82f6;padding:10px 14px;margin:16px 0}}
.ok{{background:#f0fdf4;border-left:4px solid #22c55e;padding:10px 14px;margin:16px 0}}
.warn{{background:#fef2f2;border-left:4px solid #ef4444;padding:10px 14px;margin:16px 0}}
.small{{color:#64748b;font-size:12px}}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Vol-zone v2 + zone_atr05_ts40 - research candidate exit AB</h1>
<p class="small">Stamp <code>{html_mod.escape(stamp)}</code> · Universe <code>{html_mod.escape(str(universe_path))}</code> · Prior entry <code>{html_mod.escape(prior_stamp)}</code> · <b>Not production gold</b>.</p>

<div class="note">
<strong>Honesty / selection bias.</strong> Primary exit <code>{html_mod.escape(e.name)}</code> was chosen
<strong>in-sample</strong> on PaulTwenty after comparing exits under candidate-v2 entries (best AvgR / PnL% among compared exits).
Entry knobs were also in-sample from prior stamps. Re-score IS/OOS under this exit before reading ABs.
Expectancy here = mean trade PnL% (same as AvgPnL%). Do not DailyRun-wire.
</div>

<div class="callout">
<strong>Freeze.</strong>
Entry: lookback={p.lookback_days} · kinds={"+".join(p.zone_kinds)} · eps={p.retest_eps_pct} ·
rw={p.retest_window} · first_retest={p.first_retest_only} · mt≥{p.min_touches_before_entry}.
Exit: stop = zone.lo − 0.5·ATR14[entry], target {e.target_r}R, time stop {e.exit_bars}d.
</div>

<h2>1. Freeze metrics (primary exit) vs toy reference</h2>
<p>Click column headers to sort. Primary = <code>{html_mod.escape(e.name)}</code>. Toy is reference only.</p>
<table class="sortable">
<thead><tr>
{sortable_th("Exit", "text")}
{_metrics_headers()}
{sortable_th("Expectancy%", "num")}
{sortable_th("Role", "text")}
</tr></thead>
<tbody>
<tr><td>{html_mod.escape(e.name)} (primary)</td>{_metrics_cells(freeze_m)}<td>{_fmt_num(freeze_m.get('expectancy_pct', freeze_m['avg_pnl_pct']))}</td><td>Research candidate exit</td></tr>
<tr><td>toy (reference)</td>{_metrics_cells(toy_m)}<td>{_fmt_num(toy_m.get('expectancy_pct', toy_m['avg_pnl_pct']))}</td><td>Side-by-side only</td></tr>
</tbody>
</table>

<h2>2. IS / OOS under zone_atr05_ts40</h2>
<p>IS = entry_date &lt; {split_s}. OOS = entry_date ≥ {split_s}. Headline: {html_mod.escape(softens_txt)}</p>
<table class="sortable">
<thead><tr>
{sortable_th("Split", "text")}
{_metrics_headers()}
{sortable_th("Expectancy%", "num")}
</tr></thead>
<tbody>
<tr><td>In-sample (&lt;{split_s})</td>{_metrics_cells(is_m)}<td>{_fmt_num(is_m.get('expectancy_pct', is_m['avg_pnl_pct']))}</td></tr>
<tr><td>OOS holdout (≥{split_s})</td>{_metrics_cells(oos_m)}<td>{_fmt_num(oos_m.get('expectancy_pct', oos_m['avg_pnl_pct']))}</td></tr>
<tr><td>Full history (primary)</td>{_metrics_cells(freeze_m)}<td>{_fmt_num(freeze_m.get('expectancy_pct', freeze_m['avg_pnl_pct']))}</td></tr>
</tbody>
</table>

<h2>3. Entry ABs (scored on zone_atr05_ts40)</h2>
<p>One change at a time vs freeze. Quality-first keep/dismiss.</p>
<table class="sortable">
<thead><tr>
{sortable_th("Arm", "text")}
{sortable_th("Change", "text")}
{_metrics_headers()}
{sortable_th("Expectancy%", "num")}
{sortable_th("ΔN", "num")}
{sortable_th("ΔWR pp", "num")}
{sortable_th("ΔAvgR", "num")}
{sortable_th("ΔPnL%", "num")}
{sortable_th("Lean", "text")}
{sortable_th("Keep/dismiss note", "text")}
</tr></thead>
<tbody>
{ab_body(entry_ab_rows, entry_ctrl)}
</tbody>
</table>

<h2>4. Exit ABs (same freeze entries - EXIT label)</h2>
<p>Same candidate-v2 entries; only time stop changes. Stop formula fixed at zone.lo − 0.5·ATR. These are <b>exit</b> ABs, not entry claims.</p>
<table class="sortable">
<thead><tr>
{sortable_th("Arm", "text")}
{sortable_th("Change", "text")}
{_metrics_headers()}
{sortable_th("Expectancy%", "num")}
{sortable_th("ΔN", "num")}
{sortable_th("ΔWR pp", "num")}
{sortable_th("ΔAvgR", "num")}
{sortable_th("ΔPnL%", "num")}
{sortable_th("Lean", "text")}
{sortable_th("Keep/dismiss note", "text")}
</tr></thead>
<tbody>
{ab_body(exit_ab_rows, exit_ctrl)}
</tbody>
</table>

<h2>5. Per-symbol (primary exit)</h2>
<table class="sortable">
<thead><tr>
{sortable_th("Symbol", "text")}
{sortable_th("Status", "text")}
{sortable_th("Bars", "num")}
{sortable_th("Date range", "text")}
{_metrics_headers()}
{sortable_th("IS N", "num")}
{sortable_th("IS WR%", "num")}
{sortable_th("OOS N", "num")}
{sortable_th("OOS WR%", "num")}
</tr></thead>
<tbody>
{sym_body}
</tbody>
</table>

<div class="{'warn' if softens else 'ok'}">
<strong>Any reason not to use zone_atr05_ts40 as research candidate exit?</strong>
{html_mod.escape(exit_answer)}
</div>

<div class="ok">
<strong>Recommendation.</strong> {html_mod.escape(recommendation)}
</div>

<h2>6. Skipped / missing</h2>
{skipped_html}

<p class="small">Generated by tools/vol_zone_break_retest.py --v2-exit-ab - research only.</p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")


def _recommend_v2_exit_ab(
    freeze_m: dict,
    toy_m: dict,
    is_m: dict,
    oos_m: dict,
    entry_ab_rows: list[dict],
    exit_ab_rows: list[dict],
) -> tuple[str, str]:
    """Return (recommendation, exit_answer)."""
    parts: list[str] = []
    parts.append(
        f"Freeze under {PRIMARY_EXIT.name}: N={freeze_m['n_signals']}, "
        f"WR={freeze_m['win_rate']*100:.1f}%, AvgR={freeze_m['avg_r']:.2f}, "
        f"AvgPnL%/E={freeze_m['avg_pnl_pct']:.2f} "
        f"(toy ref AvgR={toy_m['avg_r']:.2f}, AvgPnL%={toy_m['avg_pnl_pct']:.2f})."
    )
    softens = False
    if oos_m["n_signals"] > 0 and is_m["n_signals"] > 0:
        oos_gap = (oos_m["win_rate"] - is_m["win_rate"]) * 100
        oos_gap_r = oos_m["avg_r"] - is_m["avg_r"]
        softens = oos_gap <= -5 or oos_gap_r <= -0.15
        parts.append(
            f"IS/OOS under primary: IS WR {is_m['win_rate']*100:.1f}% / AvgR {is_m['avg_r']:.2f} "
            f"(N={is_m['n_signals']}); OOS WR {oos_m['win_rate']*100:.1f}% / AvgR {oos_m['avg_r']:.2f} "
            f"(N={oos_m['n_signals']}; dWR {oos_gap:+.1f}pp, dAvgR {oos_gap_r:+.2f})."
        )
        if softens:
            parts.append("OOS still softens vs IS under this exit - provisional, not gold.")
        else:
            parts.append("OOS does not clearly soften under this exit - still research-only.")

    keeps: list[str] = []
    dismisses: list[str] = []
    for r in entry_ab_rows:
        if r["arm"] == "00_freeze":
            continue
        lean = r.get("lean", "HOLD")
        if lean in ("KEEP", "LEAN KEEP"):
            keeps.append(f"{r['arm']}={lean}")
        elif lean == "DISMISS":
            dismisses.append(r["arm"])
    if keeps:
        parts.append("Entry lean-keeps: " + ", ".join(keeps) + ".")
    if dismisses:
        parts.append("Entry dismiss: " + ", ".join(dismisses) + ".")

    for r in exit_ab_rows:
        if r["arm"] == "EXIT_ts40":
            continue
        parts.append(f"Exit AB {r['arm']}: {r.get('lean', 'HOLD')} - {r.get('lean_why', '')}.")

    parts.append("Next: walk-forward / larger universe; do not DailyRun-wire.")

    exit_answer = (
        "No good reason not to use zone_atr05_ts40 as the research candidate exit for step-5 ABs: "
        "it led the in-sample exit compare on AvgR/PnL% and is a coherent zone-ATR stop + longer clock. "
        "Honesty: exit choice was in-sample on PaulTwenty after comparing exits, so treat IS/OOS under "
        "this exit (and further walk-forward) as required before any stronger claim. "
        + (
            "OOS softens vs IS under this exit as well - provisional only."
            if softens
            else "OOS does not clearly soften here, but selection bias remains."
        )
        + " Not gold / not DailyRun."
    )
    return " ".join(parts), exit_answer


def run_v2_exit_ab(
    *,
    universe_path: Path,
    data_dir: Path,
    out_dir: Path,
    stamp: str,
    lookback_days: int,
    prior_stamp: str = "vol_zone_hl_quality_20260810",
) -> None:
    symbols = load_universe_symbols(universe_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_v2_exit_ab_baseline_md(
        out_dir / "BASELINE.md",
        stamp=stamp,
        universe_path=universe_path,
        n_symbols=len(symbols),
        prior_stamp=prior_stamp,
    )
    write_v2_exit_ab_plan_md(out_dir / "AB_PLAN.md")

    freeze_params = replace(RESEARCH_CANDIDATE_V2, lookback_days=lookback_days)
    primary = PRIMARY_EXIT
    toy = TOY_EXIT

    caches: dict[str, tuple[pd.DataFrame, list[Zone], np.ndarray, list[ZoneEvents] | None]] = {}
    symbol_rows: list[dict] = []
    skipped: list[dict] = []
    freeze_signals: list[dict] = []
    toy_signals: list[dict] = []
    freeze_raw: dict[str, list[RetestSignal]] = {}

    print(
        f"V2 exit AB stamp={stamp} symbols={len(symbols)} lookback={lookback_days} "
        f"primary_exit={primary.name}"
    )
    for sym in symbols:
        csv_path = data_dir / f"{sym}.csv"
        if not csv_path.is_file():
            note = f"missing CSV: {csv_path}"
            print(f"  SKIP {sym}: {note}")
            skipped.append({"symbol": sym, "note": note})
            symbol_rows.append({"symbol": sym, "status": "missing", "note": note})
            continue
        try:
            df = load_ohlcv(csv_path)
            atr = atr14(df)
            zones = build_zones(df, lookback_days)
        except Exception as e:  # noqa: BLE001
            note = str(e)
            print(f"  SKIP {sym}: {note}")
            skipped.append({"symbol": sym, "note": note})
            symbol_rows.append({"symbol": sym, "status": "error", "note": note})
            continue

        sigs, _, _ = run_symbol_with_params(sym, df, zones, atr, freeze_params)
        prim_rows = enrich_signal_rows(sym, df, sigs, freeze_params, atr=atr, exit_spec=primary)
        toy_rows = enrich_signal_rows(sym, df, sigs, freeze_params, atr=atr, exit_spec=toy)
        freeze_signals.extend(prim_rows)
        toy_signals.extend(toy_rows)
        freeze_raw[sym] = sigs
        caches[sym] = (df, zones, atr, None)

        m = summarize_signal_dicts(prim_rows)
        is_r, oos_r = split_is_oos(prim_rows)
        m_is = summarize_signal_dicts(is_r)
        m_oos = summarize_signal_dicts(oos_r)
        print(
            f"  {sym}: N={m['n_signals']} WR={m['win_rate']*100:.1f}% AvgR={m['avg_r']:.2f} "
            f"IS={m_is['n_signals']}/{m_is['win_rate']*100:.1f}% "
            f"OOS={m_oos['n_signals']}/{m_oos['win_rate']*100:.1f}%"
        )
        symbol_rows.append(
            {
                "symbol": sym,
                "status": "ok",
                "n_bars": len(df),
                "date_start": str(pd.Timestamp(df["Date"].iloc[0]).date()),
                "date_end": str(pd.Timestamp(df["Date"].iloc[-1]).date()),
                "metrics": m,
                "metrics_is": m_is,
                "metrics_oos": m_oos,
            }
        )

    freeze_m = summarize_signal_dicts(freeze_signals)
    toy_m = summarize_signal_dicts(toy_signals)
    is_rows, oos_rows = split_is_oos(freeze_signals)
    is_m = summarize_signal_dicts(is_rows)
    oos_m = summarize_signal_dicts(oos_rows)

    print(
        f"FREEZE {primary.name}: N={freeze_m['n_signals']} WR={freeze_m['win_rate']*100:.1f}% "
        f"AvgR={freeze_m['avg_r']:.2f} AvgPnL%={freeze_m['avg_pnl_pct']:.2f}"
    )
    print(
        f"TOY ref: N={toy_m['n_signals']} WR={toy_m['win_rate']*100:.1f}% "
        f"AvgR={toy_m['avg_r']:.2f} AvgPnL%={toy_m['avg_pnl_pct']:.2f}"
    )
    print(
        f"IS:  N={is_m['n_signals']} WR={is_m['win_rate']*100:.1f}% AvgR={is_m['avg_r']:.2f}"
    )
    print(
        f"OOS: N={oos_m['n_signals']} WR={oos_m['win_rate']*100:.1f}% AvgR={oos_m['avg_r']:.2f}"
    )

    # Entry ABs
    arms = v2_exit_entry_ab_arms()
    eps_needed = sorted({a[1].retest_eps_pct for a in arms})
    break_pcts = sorted({a[1].break_pct for a in arms})
    break_atrs = sorted({a[1].break_atr for a in arms})
    print("precomputing zone events for entry ABs...")
    for sym, (df, zones, atr, _) in list(caches.items()):
        cached = precompute_zone_events(
            df,
            zones,
            atr,
            approach_lookback=freeze_params.approach_lookback,
            eps_list=eps_needed,
            break_pcts=break_pcts,
            break_atrs=break_atrs,
        )
        caches[sym] = (df, zones, atr, cached)

    entry_ab_rows: list[dict] = []
    ab_signal_frames: list[pd.DataFrame] = []
    for arm, arm_params, note in arms:
        arm_params = replace(arm_params, lookback_days=lookback_days)
        all_rows: list[dict] = []
        for sym, (df, zones, atr, cached) in caches.items():
            sigs, _, _ = run_symbol_with_params(
                sym, df, zones, atr, arm_params, cached=cached
            )
            all_rows.extend(
                enrich_signal_rows(sym, df, sigs, arm_params, atr=atr, exit_spec=primary)
            )
        m = summarize_signal_dicts(all_rows)
        entry_ab_rows.append({"arm": arm, "note": note, "metrics": m})
        print(
            f"  AB {arm}: N={m['n_signals']} WR={m['win_rate']*100:.1f}% "
            f"AvgR={m['avg_r']:.2f} AvgPnL%={m['avg_pnl_pct']:.2f} - {note}"
        )
        if all_rows:
            df_arm = pd.DataFrame(all_rows)
            df_arm.insert(0, "arm", arm)
            ab_signal_frames.append(df_arm)

    ctrl_m = entry_ab_rows[0]["metrics"]
    for r in entry_ab_rows:
        lean, why = lean_ab_v2_exit(r["arm"], r["metrics"], ctrl_m)
        r["lean"] = lean
        r["lean_why"] = why
        r["keep_note"] = _keep_dismiss_note(r["arm"], lean, why)

    # Exit ABs on freeze entries
    exit_ab_rows: list[dict] = []
    for spec in EXIT_AB_SPECS:
        rows: list[dict] = []
        for sym, (df, _zones, atr, _) in caches.items():
            sigs = freeze_raw.get(sym, [])
            rows.extend(
                enrich_signal_rows(sym, df, sigs, freeze_params, atr=atr, exit_spec=spec)
            )
        m = summarize_signal_dicts(rows)
        arm = f"EXIT_ts{spec.exit_bars}"
        exit_ab_rows.append(
            {
                "arm": arm,
                "note": spec.label,
                "metrics": m,
                "exit_mix": _exit_mix(rows),
            }
        )
        print(
            f"  EXIT AB {arm}: N={m['n_signals']} WR={m['win_rate']*100:.1f}% "
            f"AvgR={m['avg_r']:.2f} mix={_exit_mix(rows)}"
        )

    exit_ctrl = next(r["metrics"] for r in exit_ab_rows if r["arm"] == "EXIT_ts40")
    for r in exit_ab_rows:
        lean, why = lean_ab_v2_exit(r["arm"], r["metrics"], exit_ctrl)
        r["lean"] = lean
        r["lean_why"] = why
        r["keep_note"] = _keep_dismiss_note(r["arm"], lean, why)

    recommendation, exit_answer = _recommend_v2_exit_ab(
        freeze_m, toy_m, is_m, oos_m, entry_ab_rows, exit_ab_rows
    )

    # CSVs
    pd.DataFrame(freeze_signals).to_csv(out_dir / "signals_primary.csv", index=False)
    pd.DataFrame(toy_signals).to_csv(out_dir / "signals_toy_ref.csv", index=False)

    per_flat = []
    for row in symbol_rows:
        if row.get("status") != "ok":
            per_flat.append(
                {"symbol": row["symbol"], "status": row["status"], "note": row.get("note", "")}
            )
            continue
        m, m_is, m_oos = row["metrics"], row["metrics_is"], row["metrics_oos"]
        per_flat.append(
            {
                "symbol": row["symbol"],
                "status": "ok",
                "n_bars": row["n_bars"],
                "date_start": row["date_start"],
                "date_end": row["date_end"],
                "n_signals": m["n_signals"],
                "win_rate": m["win_rate"],
                "avg_pnl_pct": m["avg_pnl_pct"],
                "expectancy_pct": m.get("expectancy_pct", m["avg_pnl_pct"]),
                "avg_r": m["avg_r"],
                "is_n": m_is["n_signals"],
                "is_wr": m_is["win_rate"],
                "is_avg_r": m_is["avg_r"],
                "oos_n": m_oos["n_signals"],
                "oos_wr": m_oos["win_rate"],
                "oos_avg_r": m_oos["avg_r"],
            }
        )
    pd.DataFrame(per_flat).to_csv(out_dir / "per_symbol_primary.csv", index=False)

    pd.DataFrame(
        [
            {
                "exit": primary.name,
                "label": primary.label,
                "role": "primary",
                "n_signals": freeze_m["n_signals"],
                "win_rate": freeze_m["win_rate"],
                "avg_pnl_pct": freeze_m["avg_pnl_pct"],
                "expectancy_pct": freeze_m.get("expectancy_pct", freeze_m["avg_pnl_pct"]),
                "avg_r": freeze_m["avg_r"],
            },
            {
                "exit": toy.name,
                "label": toy.label,
                "role": "reference",
                "n_signals": toy_m["n_signals"],
                "win_rate": toy_m["win_rate"],
                "avg_pnl_pct": toy_m["avg_pnl_pct"],
                "expectancy_pct": toy_m.get("expectancy_pct", toy_m["avg_pnl_pct"]),
                "avg_r": toy_m["avg_r"],
            },
        ]
    ).to_csv(out_dir / "exit_side_by_side.csv", index=False)

    pd.DataFrame(
        [
            {
                "split": "IS",
                "split_date": str(OOS_SPLIT_DATE.date()),
                "exit": primary.name,
                "n_signals": is_m["n_signals"],
                "win_rate": is_m["win_rate"],
                "avg_pnl_pct": is_m["avg_pnl_pct"],
                "expectancy_pct": is_m.get("expectancy_pct", is_m["avg_pnl_pct"]),
                "avg_r": is_m["avg_r"],
            },
            {
                "split": "OOS",
                "split_date": str(OOS_SPLIT_DATE.date()),
                "exit": primary.name,
                "n_signals": oos_m["n_signals"],
                "win_rate": oos_m["win_rate"],
                "avg_pnl_pct": oos_m["avg_pnl_pct"],
                "expectancy_pct": oos_m.get("expectancy_pct", oos_m["avg_pnl_pct"]),
                "avg_r": oos_m["avg_r"],
            },
            {
                "split": "FULL",
                "split_date": str(OOS_SPLIT_DATE.date()),
                "exit": primary.name,
                "n_signals": freeze_m["n_signals"],
                "win_rate": freeze_m["win_rate"],
                "avg_pnl_pct": freeze_m["avg_pnl_pct"],
                "expectancy_pct": freeze_m.get("expectancy_pct", freeze_m["avg_pnl_pct"]),
                "avg_r": freeze_m["avg_r"],
            },
            {
                "split": "FULL_TOY_REF",
                "split_date": str(OOS_SPLIT_DATE.date()),
                "exit": toy.name,
                "n_signals": toy_m["n_signals"],
                "win_rate": toy_m["win_rate"],
                "avg_pnl_pct": toy_m["avg_pnl_pct"],
                "expectancy_pct": toy_m.get("expectancy_pct", toy_m["avg_pnl_pct"]),
                "avg_r": toy_m["avg_r"],
            },
        ]
    ).to_csv(out_dir / "oos_split.csv", index=False)

    ab_csv = out_dir / "ab_results.csv"
    pd.DataFrame(
        [
            {
                "arm": r["arm"],
                "note": r["note"],
                "n_signals": r["metrics"]["n_signals"],
                "win_rate": r["metrics"]["win_rate"],
                "avg_pnl_pct": r["metrics"]["avg_pnl_pct"],
                "expectancy_pct": r["metrics"].get(
                    "expectancy_pct", r["metrics"]["avg_pnl_pct"]
                ),
                "avg_r": r["metrics"]["avg_r"],
                "lean": r.get("lean", ""),
                "lean_why": r.get("lean_why", ""),
                "keep_note": r.get("keep_note", ""),
            }
            for r in entry_ab_rows
        ]
    ).to_csv(ab_csv, index=False)

    pd.DataFrame(
        [
            {
                "arm": r["arm"],
                "note": r["note"],
                "n_signals": r["metrics"]["n_signals"],
                "win_rate": r["metrics"]["win_rate"],
                "avg_pnl_pct": r["metrics"]["avg_pnl_pct"],
                "expectancy_pct": r["metrics"].get(
                    "expectancy_pct", r["metrics"]["avg_pnl_pct"]
                ),
                "avg_r": r["metrics"]["avg_r"],
                "exit_mix": r.get("exit_mix", ""),
                "lean": r.get("lean", ""),
                "lean_why": r.get("lean_why", ""),
                "keep_note": r.get("keep_note", ""),
            }
            for r in exit_ab_rows
        ]
    ).to_csv(out_dir / "exit_ab_results.csv", index=False)

    if ab_signal_frames:
        pd.concat(ab_signal_frames, ignore_index=True).to_csv(
            out_dir / "signals_ab_all.csv", index=False
        )

    # Append results to AB_PLAN
    plan_path = out_dir / "AB_PLAN.md"
    lines = [
        "\n## Entry AB results (auto, scored on zone_atr05_ts40)\n",
        "| Arm | N | WR% | AvgR | AvgPnL% | Lean | Keep/dismiss |",
        "|-----|---|-----|------|---------|------|--------------|",
    ]
    for r in entry_ab_rows:
        m = r["metrics"]
        lines.append(
            f"| {r['arm']} | {m['n_signals']} | {m['win_rate']*100:.1f} | "
            f"{m['avg_r']:.2f} | {m['avg_pnl_pct']:.2f} | {r.get('lean', '')} | "
            f"{r.get('keep_note', '')} |"
        )
    lines += [
        "\n## Exit AB results (auto)\n",
        "| Arm | N | WR% | AvgR | AvgPnL% | Lean | Note |",
        "|-----|---|-----|------|---------|------|------|",
    ]
    for r in exit_ab_rows:
        m = r["metrics"]
        lines.append(
            f"| {r['arm']} | {m['n_signals']} | {m['win_rate']*100:.1f} | "
            f"{m['avg_r']:.2f} | {m['avg_pnl_pct']:.2f} | {r.get('lean', '')} | "
            f"{r.get('keep_note', '')} |"
        )
    lines.append("\n## IS/OOS under zone_atr05_ts40\n")
    lines.append(
        f"- IS: N={is_m['n_signals']} WR={is_m['win_rate']*100:.1f}% "
        f"AvgR={is_m['avg_r']:.2f} AvgPnL%={is_m['avg_pnl_pct']:.2f}\n"
        f"- OOS: N={oos_m['n_signals']} WR={oos_m['win_rate']*100:.1f}% "
        f"AvgR={oos_m['avg_r']:.2f} AvgPnL%={oos_m['avg_pnl_pct']:.2f}\n"
    )
    lines.append("\n## Exit answer\n")
    lines.append(exit_answer + "\n")
    lines.append("\n## Recommendation\n")
    lines.append(recommendation + "\n")
    plan_path.write_text(
        plan_path.read_text(encoding="utf-8") + "\n".join(lines) + "\n", encoding="utf-8"
    )

    html_path = out_dir / "comparison.html"
    write_v2_exit_comparison_html(
        html_path,
        stamp=stamp,
        universe_path=universe_path,
        prior_stamp=prior_stamp,
        freeze_params=freeze_params,
        primary_exit=primary,
        freeze_m=freeze_m,
        toy_m=toy_m,
        is_m=is_m,
        oos_m=oos_m,
        symbol_rows=symbol_rows,
        entry_ab_rows=entry_ab_rows,
        exit_ab_rows=exit_ab_rows,
        recommendation=recommendation,
        exit_answer=exit_answer,
        skipped=skipped,
    )
    print(f"saved: {html_path}")
    print(f"saved: {ab_csv}")
    print(f"EXIT ANSWER: {exit_answer}")
    print(f"RECOMMENDATION: {recommendation}")


# ---------------------------------------------------------------------------
# Adopted rw63 research freeze (LEAN KEEP from v2 exit AB) - not gold
# ---------------------------------------------------------------------------
def write_v2_rw63_baseline_md(
    path: Path,
    *,
    stamp: str,
    universe_path: Path,
    n_symbols: int,
    prior_exit_ab_stamp: str,
    prior_entry_stamp: str,
) -> None:
    p = RESEARCH_CANDIDATE_V2_RW63
    e = PRIMARY_EXIT
    md = f"""# Vol-zone v2 rw63 - adopted research freeze (NOT gold)

**Stamp:** `{stamp}`  
**Status:** Research candidate only - **not** production gold, **not** DailyRun-wired.  
**Universe:** `{universe_path.as_posix()}` ({n_symbols} symbols, full local history where CSV exists)

## Adoption

Adopted AB arm `01_rw63` (**LEAN KEEP**) from `{prior_exit_ab_stamp}` into the research freeze.
Prior research exit freeze used `retest_window=126` (same HL+gates + `zone_atr05_ts40`).

| Prior stamp | Role |
|-------------|------|
| `{prior_exit_ab_stamp}` | v2 + zone_atr05_ts40 exit AB (rw126 control; 01_rw63 = LEAN KEEP) |
| `{prior_entry_stamp}` | HL-quality candidate v2 entry stamp |
| `vol_zone_paultwenty_20260810` | Original PaulTwenty OC+HL multi-visit baseline |

## Frozen entry = candidate v2 + retest_window=63

| Knob | Value | vs prior rw126 freeze |
|------|-------|------------------------|
| lookback_days | {p.lookback_days} | same |
| zone_kinds | {", ".join(p.zone_kinds)} (HL-only) | same |
| break_pct / break_atr | {p.break_pct} / {p.break_atr} | same |
| retest_eps_pct | {p.retest_eps_pct} | same (eps=0 still dismissed) |
| retest_window | **{p.retest_window}** | was 126 -> **63** |
| first_retest_only | {p.first_retest_only} | same |
| min_touches_before_entry | {p.min_touches_before_entry} | same (mt0 still dismissed) |
| entry_on | {p.entry_on} | same |

## Frozen primary exit = `{e.name}` (unchanged)

| Piece | Formula / value |
|-------|-----------------|
| Stop | `zone.lo − 0.5 · ATR14[entry]` |
| Target | `{e.target_r}R` from entry vs stop distance |
| Time stop | `{e.exit_bars}` bars |

## Label

**Research baseline** for further vol-zone work under this stamp lineage. Still **research only** - not gold, not DailyRun.

## Confirmation from prior AB (not re-grid)

From `{prior_exit_ab_stamp}` under `zone_atr05_ts40`: `02_mt0` and `07_eps0` remain **DISMISS** (WR and AvgR both worse vs rw126 control). No full AB re-grid in this stamp.

## Honest caveats

- `01_rw63` was selected in-sample on PaulTwenty (LEAN KEEP vs rw126 freeze on same history).
- Exit `zone_atr05_ts40` and earlier entry gates were also in-sample selections.
- Chronologic split: IS = entry_date &lt; 2024-01-01; OOS = 2024+ holdout. **Do not retune on holdout.**
- Do **not** wire into DailyRun or claim gold.

## Outputs in this stamp folder

- `VolZone_V2_RW63_Adoption.html` - prior rw126 vs adopted rw63 + IS/OOS + per-symbol
- `signals_rw63.csv` / `signals_rw126_prior.csv`
- `per_symbol_rw63.csv` / `compare_pooled.csv` / `oos_split.csv`
- `BASELINE.md`
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md, encoding="utf-8")


def write_v2_rw63_adoption_html(
    out_path: Path,
    *,
    stamp: str,
    universe_path: Path,
    prior_exit_ab_stamp: str,
    prior_params: SysParams,
    new_params: SysParams,
    prior_m: dict,
    new_m: dict,
    is_m: dict,
    oos_m: dict,
    symbol_rows: list[dict],
    skipped: list[dict],
) -> None:
    split_s = str(OOS_SPLIT_DATE.date())
    e = PRIMARY_EXIT
    d_n = new_m["n_signals"] - prior_m["n_signals"]
    d_wr = (new_m["win_rate"] - prior_m["win_rate"]) * 100
    d_r = new_m["avg_r"] - prior_m["avg_r"]
    d_pnl = new_m["avg_pnl_pct"] - prior_m["avg_pnl_pct"]

    oos_gap_wr = (
        (oos_m["win_rate"] - is_m["win_rate"]) * 100
        if is_m["n_signals"] and oos_m["n_signals"]
        else 0.0
    )
    oos_gap_r = (
        (oos_m["avg_r"] - is_m["avg_r"]) if is_m["n_signals"] and oos_m["n_signals"] else 0.0
    )
    softens = oos_gap_wr <= -5 or oos_gap_r <= -0.15
    softens_txt = (
        f"Yes - OOS softens vs IS (ΔWR {oos_gap_wr:+.1f}pp, ΔAvgR {oos_gap_r:+.2f})."
        if softens
        else (
            f"OOS does not clearly soften (ΔWR {oos_gap_wr:+.1f}pp, ΔAvgR {oos_gap_r:+.2f}) "
            "- still research-only."
        )
    )

    sym_body = ""
    for row in symbol_rows:
        if row.get("status") != "ok":
            sym_body += (
                "<tr>"
                f"<td>{html_mod.escape(row['symbol'])}</td>"
                f"<td>{html_mod.escape(row.get('status', ''))}</td>"
                f"<td colspan='10'>{html_mod.escape(str(row.get('note', '')))}</td>"
                "</tr>"
            )
            continue
        mp = row["metrics_prior"]
        mn = row["metrics_new"]
        m_is = row.get("metrics_is") or metrics_from_pnls([])
        m_oos = row.get("metrics_oos") or metrics_from_pnls([])
        sym_body += (
            "<tr>"
            f"<td>{html_mod.escape(row['symbol'])}</td>"
            f"<td>ok</td>"
            f"<td>{mp['n_signals']}</td>"
            f"<td>{_fmt_pct(mp['win_rate'])}</td>"
            f"<td>{_fmt_num(mp['avg_r'])}</td>"
            f"<td>{_fmt_num(mp['avg_pnl_pct'])}</td>"
            f"<td>{mn['n_signals']}</td>"
            f"<td>{_fmt_pct(mn['win_rate'])}</td>"
            f"<td>{_fmt_num(mn['avg_r'])}</td>"
            f"<td>{_fmt_num(mn['avg_pnl_pct'])}</td>"
            f"<td>{m_is['n_signals']}</td>"
            f"<td>{m_oos['n_signals']}</td>"
            "</tr>"
        )

    skipped_html = (
        "<ul>"
        + "".join(
            f"<li><b>{html_mod.escape(s['symbol'])}</b>: {html_mod.escape(s['note'])}</li>"
            for s in skipped
        )
        + "</ul>"
        if skipped
        else "<p>None.</p>"
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>VolZone v2 rw63 adoption - {html_mod.escape(stamp)}</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:24px;max-width:1100px;color:#1a1a1a;line-height:1.45}}
h1,h2,h3{{margin-top:1.4em}}
code{{background:#f4f4f5;padding:2px 6px;border-radius:4px}}
table.sortable{{border-collapse:collapse;width:100%;font-size:13px;margin:12px 0}}
table.sortable th,table.sortable td{{border:1px solid #cbd5e1;padding:6px 8px;text-align:left}}
table.sortable thead{{background:#f1f5f9}}
.note{{background:#fff7ed;border-left:4px solid #f97316;padding:10px 14px;margin:16px 0}}
.callout{{background:#eff6ff;border-left:4px solid #3b82f6;padding:10px 14px;margin:16px 0}}
.ok{{background:#f0fdf4;border-left:4px solid #22c55e;padding:10px 14px;margin:16px 0}}
.small{{color:#64748b;font-size:12px}}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Vol-zone v2 rw63 - adopted research freeze</h1>
<p class="small">Stamp <code>{html_mod.escape(stamp)}</code> · Universe <code>{html_mod.escape(str(universe_path))}</code> · Prior exit-AB <code>{html_mod.escape(prior_exit_ab_stamp)}</code> · <b>Not production gold</b>.</p>

<div class="note">
<strong>Research only.</strong> Adopted <code>01_rw63</code> (LEAN KEEP) from the v2 exit AB into the research freeze.
Primary exit remains <code>{html_mod.escape(e.name)}</code>. Not gold / not DailyRun.
From prior AB: <code>02_mt0</code> and <code>07_eps0</code> remain <b>DISMISS</b> - no full re-grid here.
</div>

<div class="callout">
<strong>New freeze.</strong>
Entry: lookback={new_params.lookback_days} · HL-only · eps={new_params.retest_eps_pct} ·
<strong>rw={new_params.retest_window}</strong> · first_retest={new_params.first_retest_only} ·
mt≥{new_params.min_touches_before_entry}.
Exit: stop = zone.lo − 0.5·ATR14[entry], target {e.target_r}R, time stop {e.exit_bars}d.
Prior freeze identical except rw={prior_params.retest_window}.
</div>

<h2>1. Pooled: prior rw126 vs adopted rw63</h2>
<p>Click column headers to sort. Same primary exit <code>{html_mod.escape(e.name)}</code>.</p>
<table class="sortable">
<thead><tr>
{sortable_th("Freeze", "text")}
{sortable_th("rw", "num")}
{_metrics_headers()}
{sortable_th("Expectancy%", "num")}
{sortable_th("ΔN", "num")}
{sortable_th("ΔWR pp", "num")}
{sortable_th("ΔAvgR", "num")}
{sortable_th("ΔPnL%", "num")}
{sortable_th("Role", "text")}
</tr></thead>
<tbody>
<tr>
<td>prior_rw126</td><td>{prior_params.retest_window}</td>
{_metrics_cells(prior_m)}
<td>{_fmt_num(prior_m.get('expectancy_pct', prior_m['avg_pnl_pct']))}</td>
<td>-</td><td>-</td><td>-</td><td>-</td>
<td>Prior research exit freeze</td>
</tr>
<tr>
<td>adopted_rw63</td><td>{new_params.retest_window}</td>
{_metrics_cells(new_m)}
<td>{_fmt_num(new_m.get('expectancy_pct', new_m['avg_pnl_pct']))}</td>
<td>{d_n:+d}</td><td>{d_wr:+.1f}</td><td>{d_r:+.2f}</td><td>{d_pnl:+.2f}</td>
<td>New research baseline</td>
</tr>
</tbody>
</table>

<h2>2. IS / OOS under adopted rw63 + zone_atr05_ts40</h2>
<p>IS = entry_date &lt; {split_s}. OOS = entry_date ≥ {split_s}. Headline: {html_mod.escape(softens_txt)}</p>
<table class="sortable">
<thead><tr>
{sortable_th("Split", "text")}
{_metrics_headers()}
{sortable_th("Expectancy%", "num")}
</tr></thead>
<tbody>
<tr><td>In-sample (&lt;{split_s})</td>{_metrics_cells(is_m)}<td>{_fmt_num(is_m.get('expectancy_pct', is_m['avg_pnl_pct']))}</td></tr>
<tr><td>OOS holdout (≥{split_s})</td>{_metrics_cells(oos_m)}<td>{_fmt_num(oos_m.get('expectancy_pct', oos_m['avg_pnl_pct']))}</td></tr>
<tr><td>Full history (rw63)</td>{_metrics_cells(new_m)}<td>{_fmt_num(new_m.get('expectancy_pct', new_m['avg_pnl_pct']))}</td></tr>
</tbody>
</table>

<h2>3. Per-symbol (prior vs adopted)</h2>
<p>Click column headers to sort.</p>
<table class="sortable">
<thead><tr>
{sortable_th("Symbol", "text")}
{sortable_th("Status", "text")}
{sortable_th("Prior N", "num")}
{sortable_th("Prior WR%", "num")}
{sortable_th("Prior AvgR", "num")}
{sortable_th("Prior AvgPnL%", "num")}
{sortable_th("rw63 N", "num")}
{sortable_th("rw63 WR%", "num")}
{sortable_th("rw63 AvgR", "num")}
{sortable_th("rw63 AvgPnL%", "num")}
{sortable_th("rw63 IS N", "num")}
{sortable_th("rw63 OOS N", "num")}
</tr></thead>
<tbody>
{sym_body}
</tbody>
</table>

<div class="ok">
<strong>Confirmation.</strong> <code>retest_window=63</code> is now the research baseline under HL-only /
first_retest / mt≥1 / eps=0.005 + <code>{html_mod.escape(e.name)}</code>. Still research only.
mt0 and eps0 remain dismissed per prior AB stamp <code>{html_mod.escape(prior_exit_ab_stamp)}</code>.
</div>

<h2>4. Skipped / missing</h2>
{skipped_html}

<p class="small">Generated by tools/vol_zone_break_retest.py --v2-rw63 - research only.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")


def run_v2_rw63_freeze(
    *,
    universe_path: Path,
    data_dir: Path,
    out_dir: Path,
    stamp: str,
    lookback_days: int,
    prior_exit_ab_stamp: str = "vol_zone_v2_exit_ab_20260810",
    prior_entry_stamp: str = "vol_zone_hl_quality_20260810",
) -> None:
    symbols = load_universe_symbols(universe_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_v2_rw63_baseline_md(
        out_dir / "BASELINE.md",
        stamp=stamp,
        universe_path=universe_path,
        n_symbols=len(symbols),
        prior_exit_ab_stamp=prior_exit_ab_stamp,
        prior_entry_stamp=prior_entry_stamp,
    )

    prior_params = replace(RESEARCH_CANDIDATE_V2, lookback_days=lookback_days)
    new_params = replace(RESEARCH_CANDIDATE_V2_RW63, lookback_days=lookback_days)
    primary = PRIMARY_EXIT

    symbol_rows: list[dict] = []
    skipped: list[dict] = []
    prior_signals: list[dict] = []
    new_signals: list[dict] = []

    print(
        f"V2 rw63 adoption stamp={stamp} symbols={len(symbols)} lookback={lookback_days} "
        f"primary_exit={primary.name}"
    )
    for sym in symbols:
        csv_path = data_dir / f"{sym}.csv"
        if not csv_path.is_file():
            note = f"missing CSV: {csv_path}"
            print(f"  SKIP {sym}: {note}")
            skipped.append({"symbol": sym, "note": note})
            symbol_rows.append({"symbol": sym, "status": "missing", "note": note})
            continue
        try:
            df = load_ohlcv(csv_path)
            atr = atr14(df)
            zones = build_zones(df, lookback_days)
        except Exception as e:  # noqa: BLE001
            note = str(e)
            print(f"  SKIP {sym}: {note}")
            skipped.append({"symbol": sym, "note": note})
            symbol_rows.append({"symbol": sym, "status": "error", "note": note})
            continue

        prior_sigs, _, _ = run_symbol_with_params(sym, df, zones, atr, prior_params)
        new_sigs, _, _ = run_symbol_with_params(sym, df, zones, atr, new_params)
        prior_rows = enrich_signal_rows(
            sym, df, prior_sigs, prior_params, atr=atr, exit_spec=primary
        )
        new_rows = enrich_signal_rows(sym, df, new_sigs, new_params, atr=atr, exit_spec=primary)
        prior_signals.extend(prior_rows)
        new_signals.extend(new_rows)

        mp = summarize_signal_dicts(prior_rows)
        mn = summarize_signal_dicts(new_rows)
        is_r, oos_r = split_is_oos(new_rows)
        m_is = summarize_signal_dicts(is_r)
        m_oos = summarize_signal_dicts(oos_r)
        print(
            f"  {sym}: prior N={mp['n_signals']} -> rw63 N={mn['n_signals']} "
            f"WR={mn['win_rate']*100:.1f}% AvgR={mn['avg_r']:.2f} "
            f"IS={m_is['n_signals']} OOS={m_oos['n_signals']}"
        )
        symbol_rows.append(
            {
                "symbol": sym,
                "status": "ok",
                "n_bars": len(df),
                "date_start": str(pd.Timestamp(df["Date"].iloc[0]).date()),
                "date_end": str(pd.Timestamp(df["Date"].iloc[-1]).date()),
                "metrics_prior": mp,
                "metrics_new": mn,
                "metrics_is": m_is,
                "metrics_oos": m_oos,
            }
        )

    prior_m = summarize_signal_dicts(prior_signals)
    new_m = summarize_signal_dicts(new_signals)
    is_rows, oos_rows = split_is_oos(new_signals)
    is_m = summarize_signal_dicts(is_rows)
    oos_m = summarize_signal_dicts(oos_rows)

    print(
        f"PRIOR rw126: N={prior_m['n_signals']} WR={prior_m['win_rate']*100:.1f}% "
        f"AvgR={prior_m['avg_r']:.2f} AvgPnL%={prior_m['avg_pnl_pct']:.2f}"
    )
    print(
        f"ADOPTED rw63: N={new_m['n_signals']} WR={new_m['win_rate']*100:.1f}% "
        f"AvgR={new_m['avg_r']:.2f} AvgPnL%={new_m['avg_pnl_pct']:.2f}"
    )
    print(
        f"IS:  N={is_m['n_signals']} WR={is_m['win_rate']*100:.1f}% AvgR={is_m['avg_r']:.2f}"
    )
    print(
        f"OOS: N={oos_m['n_signals']} WR={oos_m['win_rate']*100:.1f}% AvgR={oos_m['avg_r']:.2f}"
    )

    pd.DataFrame(new_signals).to_csv(out_dir / "signals_rw63.csv", index=False)
    pd.DataFrame(prior_signals).to_csv(out_dir / "signals_rw126_prior.csv", index=False)

    per_flat = []
    for row in symbol_rows:
        if row.get("status") != "ok":
            per_flat.append(
                {"symbol": row["symbol"], "status": row["status"], "note": row.get("note", "")}
            )
            continue
        mp, mn = row["metrics_prior"], row["metrics_new"]
        m_is, m_oos = row["metrics_is"], row["metrics_oos"]
        per_flat.append(
            {
                "symbol": row["symbol"],
                "status": "ok",
                "n_bars": row["n_bars"],
                "date_start": row["date_start"],
                "date_end": row["date_end"],
                "prior_n": mp["n_signals"],
                "prior_wr": mp["win_rate"],
                "prior_avg_r": mp["avg_r"],
                "prior_avg_pnl_pct": mp["avg_pnl_pct"],
                "rw63_n": mn["n_signals"],
                "rw63_wr": mn["win_rate"],
                "rw63_avg_r": mn["avg_r"],
                "rw63_avg_pnl_pct": mn["avg_pnl_pct"],
                "rw63_is_n": m_is["n_signals"],
                "rw63_is_wr": m_is["win_rate"],
                "rw63_is_avg_r": m_is["avg_r"],
                "rw63_oos_n": m_oos["n_signals"],
                "rw63_oos_wr": m_oos["win_rate"],
                "rw63_oos_avg_r": m_oos["avg_r"],
            }
        )
    pd.DataFrame(per_flat).to_csv(out_dir / "per_symbol_rw63.csv", index=False)

    pd.DataFrame(
        [
            {
                "freeze": "prior_rw126",
                "retest_window": prior_params.retest_window,
                "exit": primary.name,
                "n_signals": prior_m["n_signals"],
                "win_rate": prior_m["win_rate"],
                "avg_pnl_pct": prior_m["avg_pnl_pct"],
                "expectancy_pct": prior_m.get("expectancy_pct", prior_m["avg_pnl_pct"]),
                "avg_r": prior_m["avg_r"],
                "role": "prior",
            },
            {
                "freeze": "adopted_rw63",
                "retest_window": new_params.retest_window,
                "exit": primary.name,
                "n_signals": new_m["n_signals"],
                "win_rate": new_m["win_rate"],
                "avg_pnl_pct": new_m["avg_pnl_pct"],
                "expectancy_pct": new_m.get("expectancy_pct", new_m["avg_pnl_pct"]),
                "avg_r": new_m["avg_r"],
                "role": "research_baseline",
            },
        ]
    ).to_csv(out_dir / "compare_pooled.csv", index=False)

    pd.DataFrame(
        [
            {
                "split": "IS",
                "split_date": str(OOS_SPLIT_DATE.date()),
                "freeze": "adopted_rw63",
                "exit": primary.name,
                "n_signals": is_m["n_signals"],
                "win_rate": is_m["win_rate"],
                "avg_pnl_pct": is_m["avg_pnl_pct"],
                "expectancy_pct": is_m.get("expectancy_pct", is_m["avg_pnl_pct"]),
                "avg_r": is_m["avg_r"],
            },
            {
                "split": "OOS",
                "split_date": str(OOS_SPLIT_DATE.date()),
                "freeze": "adopted_rw63",
                "exit": primary.name,
                "n_signals": oos_m["n_signals"],
                "win_rate": oos_m["win_rate"],
                "avg_pnl_pct": oos_m["avg_pnl_pct"],
                "expectancy_pct": oos_m.get("expectancy_pct", oos_m["avg_pnl_pct"]),
                "avg_r": oos_m["avg_r"],
            },
            {
                "split": "FULL",
                "split_date": str(OOS_SPLIT_DATE.date()),
                "freeze": "adopted_rw63",
                "exit": primary.name,
                "n_signals": new_m["n_signals"],
                "win_rate": new_m["win_rate"],
                "avg_pnl_pct": new_m["avg_pnl_pct"],
                "expectancy_pct": new_m.get("expectancy_pct", new_m["avg_pnl_pct"]),
                "avg_r": new_m["avg_r"],
            },
            {
                "split": "FULL_PRIOR_RW126",
                "split_date": str(OOS_SPLIT_DATE.date()),
                "freeze": "prior_rw126",
                "exit": primary.name,
                "n_signals": prior_m["n_signals"],
                "win_rate": prior_m["win_rate"],
                "avg_pnl_pct": prior_m["avg_pnl_pct"],
                "expectancy_pct": prior_m.get("expectancy_pct", prior_m["avg_pnl_pct"]),
                "avg_r": prior_m["avg_r"],
            },
        ]
    ).to_csv(out_dir / "oos_split.csv", index=False)

    html_path = out_dir / "VolZone_V2_RW63_Adoption.html"
    write_v2_rw63_adoption_html(
        html_path,
        stamp=stamp,
        universe_path=universe_path,
        prior_exit_ab_stamp=prior_exit_ab_stamp,
        prior_params=prior_params,
        new_params=new_params,
        prior_m=prior_m,
        new_m=new_m,
        is_m=is_m,
        oos_m=oos_m,
        symbol_rows=symbol_rows,
        skipped=skipped,
    )
    print(f"saved: {html_path}")
    print(
        "CONFIRMATION: RESEARCH_CANDIDATE_V2_RW63 is now the research baseline "
        "(rw63 + zone_atr05_ts40). mt0/eps0 still DISMISS from prior AB. Not gold."
    )


# ---------------------------------------------------------------------------
# Full-universe confirmation (rw63 freeze on DailyRun ALL OHLC set)
# ---------------------------------------------------------------------------
def list_full_ohlc_symbols(data_dir: Path) -> list[str]:
    """Broadest local set: every SYMBOL.csv under data_dir (DailyRun ALL semantics)."""
    if not data_dir.is_dir():
        return []
    return sorted({f.stem.upper() for f in data_dir.glob("*.csv") if f.is_file()})


def materialize_full_ohlc_universe(
    out_path: Path, data_dir: Path, *, symbols: list[str] | None = None
) -> list[str]:
    """Write a one-ticker-per-line universe CSV for provenance; return symbol list."""
    syms = symbols if symbols is not None else list_full_ohlc_symbols(data_dir)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Full OHLC universe - all local daily CSVs under data/newdata/data\n"
        "# Same semantics as DailyRun / run_*.bat ALL (engine scans all OHLC CSVs).\n"
        f"# Generated from: {data_dir.as_posix()}\n"
        f"# Symbol count: {len(syms)}\n"
    )
    out_path.write_text(header + "\n".join(syms) + "\n", encoding="utf-8")
    return syms


def _load_paultwenty_rw63_metrics(compare_stamp_dir: Path) -> tuple[dict, dict, dict]:
    """Load pooled FULL / IS / OOS metrics from the PaulTwenty rw63 adoption stamp."""
    empty = metrics_from_pnls([])
    oos_path = compare_stamp_dir / "oos_split.csv"
    compare_path = compare_stamp_dir / "compare_pooled.csv"
    full_m, is_m, oos_m = dict(empty), dict(empty), dict(empty)
    if oos_path.is_file():
        df = pd.read_csv(oos_path)
        for _, row in df.iterrows():
            split = str(row.get("split", "")).upper()
            m = {
                "n_signals": int(row["n_signals"]),
                "win_rate": float(row["win_rate"]),
                "avg_pnl_pct": float(row["avg_pnl_pct"]),
                "expectancy_pct": float(row.get("expectancy_pct", row["avg_pnl_pct"])),
                "avg_r": float(row["avg_r"]),
                "median_pnl_pct": 0.0,
                "n_wins": 0,
                "n_losses": 0,
            }
            if split == "FULL":
                full_m = m
            elif split == "IS":
                is_m = m
            elif split == "OOS":
                oos_m = m
    elif compare_path.is_file():
        df = pd.read_csv(compare_path)
        hit = df[df["freeze"].astype(str).str.contains("rw63", case=False)]
        if len(hit):
            row = hit.iloc[0]
            full_m = {
                "n_signals": int(row["n_signals"]),
                "win_rate": float(row["win_rate"]),
                "avg_pnl_pct": float(row["avg_pnl_pct"]),
                "expectancy_pct": float(row.get("expectancy_pct", row["avg_pnl_pct"])),
                "avg_r": float(row["avg_r"]),
                "median_pnl_pct": 0.0,
                "n_wins": 0,
                "n_losses": 0,
            }
    return full_m, is_m, oos_m


def write_v2_rw63_fulluniv_baseline_md(
    path: Path,
    *,
    stamp: str,
    universe_path: Path,
    n_symbols: int,
    data_dir: Path,
    paultwenty_stamp: str,
) -> None:
    p = RESEARCH_CANDIDATE_V2_RW63
    e = PRIMARY_EXIT
    md = f"""# Vol-zone v2 rw63 - full-universe confirmation (NOT gold)

**Stamp:** `{stamp}`  
**Status:** Research candidate only - **not** production gold, **not** DailyRun-wired.  
**Universe:** `{universe_path.as_posix()}` ({n_symbols} symbols)  
**Universe definition:** all local daily OHLC CSVs under `{data_dir.as_posix()}` - same as DailyRun / `run_*.bat ALL` (see `drive/universes/README.md`). Missing CSVs skipped cleanly; coverage reported in HTML/CSV.

## Frozen entry (unchanged from PaulTwenty research freeze)

| Knob | Value |
|------|-------|
| lookback_days | {p.lookback_days} |
| zone_kinds | {", ".join(p.zone_kinds)} (HL-only) |
| break_pct / break_atr | {p.break_pct} / {p.break_atr} |
| retest_eps_pct | {p.retest_eps_pct} |
| retest_window | **{p.retest_window}** |
| first_retest_only | {p.first_retest_only} |
| min_touches_before_entry | {p.min_touches_before_entry} |
| entry_on | {p.entry_on} |

## Frozen primary exit = `{e.name}` (unchanged)

| Piece | Formula / value |
|-------|-----------------|
| Stop | `zone.lo − 0.5 · ATR14[entry]` |
| Target | `{e.target_r}R` from entry vs stop distance |
| Time stop | `{e.exit_bars}` bars |

## Compare reference

PaulTwenty rw63 stamp: `{paultwenty_stamp}` (same freeze, 20-name universe).

## Honest caveats

- Entry/exit knobs were selected in-sample on PaulTwenty (selection bias). This stamp is a **wider-universe confirmation**, not a retune.
- Chronologic split: IS = entry_date &lt; 2024-01-01; OOS = 2024+ holdout. **Do not retune on holdout.**
- Still **research only** - not gold, not DailyRun.

## Outputs

- `VolZone_FullUniverse_Summary.html` - primary summary
- `signals_rw63.csv` / `per_symbol_rw63.csv` / `oos_split.csv` / `compare_pooled.csv`
- `FullOHLC_universe.csv` - materialized symbol list used for this run
- `BASELINE.md`
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md, encoding="utf-8")


def write_v2_rw63_fulluniv_html(
    out_path: Path,
    *,
    stamp: str,
    universe_path: Path,
    data_dir: Path,
    params: SysParams,
    full_m: dict,
    is_m: dict,
    oos_m: dict,
    pt_full: dict,
    pt_is: dict,
    pt_oos: dict,
    paultwenty_stamp: str,
    symbol_rows: list[dict],
    skipped: list[dict],
    n_attempted: int,
    n_with_data: int,
    n_with_signals: int,
    runtime_sec: float,
) -> None:
    split_s = str(OOS_SPLIT_DATE.date())
    e = PRIMARY_EXIT
    oos_gap_wr = (
        (oos_m["win_rate"] - is_m["win_rate"]) * 100
        if is_m["n_signals"] and oos_m["n_signals"]
        else 0.0
    )
    oos_gap_r = (
        (oos_m["avg_r"] - is_m["avg_r"]) if is_m["n_signals"] and oos_m["n_signals"] else 0.0
    )
    softens = oos_gap_wr <= -5 or oos_gap_r <= -0.15
    softens_txt = (
        f"Yes - OOS softens vs IS (ΔWR {oos_gap_wr:+.1f}pp, ΔAvgR {oos_gap_r:+.2f}). "
        "HOLD / investigate - do not retune OOS."
        if softens
        else (
            f"OOS does not clearly soften (ΔWR {oos_gap_wr:+.1f}pp, ΔAvgR {oos_gap_r:+.2f}) "
            "- still research-only; not gold."
        )
    )

    ok_rows = [r for r in symbol_rows if r.get("status") == "ok" and (r.get("metrics_new") or {}).get("n_signals", 0) > 0]
    by_avgr = sorted(
        ok_rows,
        key=lambda r: float((r.get("metrics_new") or {}).get("avg_r") or 0.0),
        reverse=True,
    )
    top = by_avgr[:15]
    bottom = list(reversed(by_avgr[-15:])) if len(by_avgr) >= 15 else list(reversed(by_avgr))

    def _sym_row(row: dict) -> str:
        if row.get("status") != "ok":
            return (
                "<tr>"
                f"<td>{html_mod.escape(row['symbol'])}</td>"
                f"<td>{html_mod.escape(row.get('status', ''))}</td>"
                f"<td colspan='8'>{html_mod.escape(str(row.get('note', '')))}</td>"
                "</tr>"
            )
        mn = row["metrics_new"]
        m_is = row.get("metrics_is") or metrics_from_pnls([])
        m_oos = row.get("metrics_oos") or metrics_from_pnls([])
        return (
            "<tr>"
            f"<td>{html_mod.escape(row['symbol'])}</td>"
            f"<td>ok</td>"
            f"<td>{mn['n_signals']}</td>"
            f"<td>{_fmt_pct(mn['win_rate'])}</td>"
            f"<td>{_fmt_num(mn['avg_r'])}</td>"
            f"<td>{_fmt_num(mn['avg_pnl_pct'])}</td>"
            f"<td>{m_is['n_signals']}</td>"
            f"<td>{_fmt_pct(m_is['win_rate']) if m_is['n_signals'] else '-'}</td>"
            f"<td>{m_oos['n_signals']}</td>"
            f"<td>{_fmt_pct(m_oos['win_rate']) if m_oos['n_signals'] else '-'}</td>"
            "</tr>"
        )

    def _mini_table(rows: list[dict], title: str) -> str:
        body = "".join(_sym_row(r) for r in rows)
        return f"""
<h3>{html_mod.escape(title)}</h3>
<table class="sortable">
<thead><tr>
{sortable_th("Symbol", "text")}
{sortable_th("Status", "text")}
{sortable_th("N", "num")}
{sortable_th("WR%", "num")}
{sortable_th("AvgR", "num")}
{sortable_th("AvgPnL%", "num")}
{sortable_th("IS N", "num")}
{sortable_th("IS WR%", "num")}
{sortable_th("OOS N", "num")}
{sortable_th("OOS WR%", "num")}
</tr></thead>
<tbody>
{body}
</tbody>
</table>
"""

    all_body = "".join(_sym_row(r) for r in symbol_rows)
    skipped_html = (
        "<ul>"
        + "".join(
            f"<li><b>{html_mod.escape(s['symbol'])}</b>: {html_mod.escape(s['note'])}</li>"
            for s in skipped[:50]
        )
        + (f"<li>… and {len(skipped) - 50} more</li>" if len(skipped) > 50 else "")
        + "</ul>"
        if skipped
        else "<p>None - all attempted symbols had usable local CSVs.</p>"
    )
    runtime_txt = f"{runtime_sec / 60.0:.1f} min ({runtime_sec:.0f}s)"

    d_n = full_m["n_signals"] - pt_full["n_signals"]
    d_wr = (full_m["win_rate"] - pt_full["win_rate"]) * 100
    d_r = full_m["avg_r"] - pt_full["avg_r"]
    d_pnl = full_m["avg_pnl_pct"] - pt_full["avg_pnl_pct"]

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>VolZone Full Universe Summary - {html_mod.escape(stamp)}</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:24px;max-width:1200px;color:#1a1a1a;line-height:1.45}}
h1,h2,h3{{margin-top:1.4em}}
code{{background:#f4f4f5;padding:2px 6px;border-radius:4px}}
table.sortable{{border-collapse:collapse;width:100%;font-size:13px;margin:12px 0}}
table.sortable th,table.sortable td{{border:1px solid #cbd5e1;padding:6px 8px;text-align:left}}
table.sortable thead{{background:#f1f5f9}}
.note{{background:#fff7ed;border-left:4px solid #f97316;padding:10px 14px;margin:16px 0}}
.callout{{background:#eff6ff;border-left:4px solid #3b82f6;padding:10px 14px;margin:16px 0}}
.ok{{background:#f0fdf4;border-left:4px solid #22c55e;padding:10px 14px;margin:16px 0}}
.small{{color:#64748b;font-size:12px}}
a{{color:#1d4ed8}}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Vol-zone v2 rw63 - full-universe confirmation</h1>
<p class="small">Stamp <code>{html_mod.escape(stamp)}</code> · Universe <code>{html_mod.escape(str(universe_path))}</code> · Data <code>{html_mod.escape(str(data_dir))}</code> · Runtime {html_mod.escape(runtime_txt)} · <b>Not production gold</b>.</p>

<div class="note">
<strong>Research only.</strong> Same freeze as PaulTwenty stamp <code>{html_mod.escape(paultwenty_stamp)}</code>:
HL-only · first_retest · mt≥1 · eps={params.retest_eps_pct} · <strong>rw={params.retest_window}</strong> ·
exit <code>{html_mod.escape(e.name)}</code> (zone.lo − 0.5·ATR, {e.target_r}R, {e.exit_bars}d).
Knobs were PaulTwenty-tuned (selection bias on entry + exit). This is a wider-universe report - <b>do not retune on OOS</b>, do not DailyRun-wire.
</div>

<div class="callout">
<strong>Prior PaulTwenty HTML (missed links).</strong>
<ul>
<li><a href="../vol_zone_paultwenty_20260810/VolZone_PaulTwenty_Analysis.html">VolZone_PaulTwenty_Analysis.html</a></li>
<li><a href="../vol_zone_v2_rw63_20260810/VolZone_V2_RW63_Adoption.html">VolZone_V2_RW63_Adoption.html</a></li>
<li><a href="../vol_zone_v2_exit_ab_20260810/comparison.html">vol_zone_v2_exit_ab comparison.html</a></li>
</ul>
</div>

<h2>1. Coverage</h2>
<table class="sortable">
<thead><tr>
{sortable_th("Metric", "text")}
{sortable_th("Count", "num")}
</tr></thead>
<tbody>
<tr><td>Symbols attempted (universe list)</td><td>{n_attempted}</td></tr>
<tr><td>With usable local CSV / loaded</td><td>{n_with_data}</td></tr>
<tr><td>With ≥1 signal (rw63 + {html_mod.escape(e.name)})</td><td>{n_with_signals}</td></tr>
<tr><td>Skipped / missing / error</td><td>{len(skipped)}</td></tr>
</tbody>
</table>
<p class="small">Universe = all <code>*.csv</code> stems under data/newdata/data (DailyRun ALL). Skip missing cleanly.</p>

<h2>2. Pooled metrics - full univ vs PaulTwenty (same freeze)</h2>
<p>Click column headers to sort. Exit <code>{html_mod.escape(e.name)}</code>.</p>
<table class="sortable">
<thead><tr>
{sortable_th("Universe", "text")}
{_metrics_headers()}
{sortable_th("Expectancy%", "num")}
{sortable_th("ΔN vs PT", "num")}
{sortable_th("ΔWR pp", "num")}
{sortable_th("ΔAvgR", "num")}
{sortable_th("ΔPnL%", "num")}
</tr></thead>
<tbody>
<tr>
<td>PaulTwenty ({html_mod.escape(paultwenty_stamp)})</td>
{_metrics_cells(pt_full)}
<td>{_fmt_num(pt_full.get('expectancy_pct', pt_full['avg_pnl_pct']))}</td>
<td>-</td><td>-</td><td>-</td><td>-</td>
</tr>
<tr>
<td>Full OHLC universe (this stamp)</td>
{_metrics_cells(full_m)}
<td>{_fmt_num(full_m.get('expectancy_pct', full_m['avg_pnl_pct']))}</td>
<td>{d_n:+d}</td><td>{d_wr:+.1f}</td><td>{d_r:+.2f}</td><td>{d_pnl:+.2f}</td>
</tr>
</tbody>
</table>

<h2>3. IS / OOS (full universe) - report only</h2>
<p>IS = entry_date &lt; {split_s}. OOS = entry_date ≥ {split_s}. Headline: {html_mod.escape(softens_txt)}</p>
<table class="sortable">
<thead><tr>
{sortable_th("Split", "text")}
{sortable_th("Universe", "text")}
{_metrics_headers()}
{sortable_th("Expectancy%", "num")}
</tr></thead>
<tbody>
<tr><td>IS</td><td>Full</td>{_metrics_cells(is_m)}<td>{_fmt_num(is_m.get('expectancy_pct', is_m['avg_pnl_pct']))}</td></tr>
<tr><td>OOS</td><td>Full</td>{_metrics_cells(oos_m)}<td>{_fmt_num(oos_m.get('expectancy_pct', oos_m['avg_pnl_pct']))}</td></tr>
<tr><td>FULL</td><td>Full</td>{_metrics_cells(full_m)}<td>{_fmt_num(full_m.get('expectancy_pct', full_m['avg_pnl_pct']))}</td></tr>
<tr><td>IS</td><td>PaulTwenty</td>{_metrics_cells(pt_is)}<td>{_fmt_num(pt_is.get('expectancy_pct', pt_is['avg_pnl_pct']))}</td></tr>
<tr><td>OOS</td><td>PaulTwenty</td>{_metrics_cells(pt_oos)}<td>{_fmt_num(pt_oos.get('expectancy_pct', pt_oos['avg_pnl_pct']))}</td></tr>
<tr><td>FULL</td><td>PaulTwenty</td>{_metrics_cells(pt_full)}<td>{_fmt_num(pt_full.get('expectancy_pct', pt_full['avg_pnl_pct']))}</td></tr>
</tbody>
</table>

<h2>4. Per-symbol - top / bottom by AvgR</h2>
<p>Among symbols with ≥1 signal. Click headers to sort.</p>
{_mini_table(top, "Top 15 by AvgR")}
{_mini_table(bottom, "Bottom 15 by AvgR")}

<h2>5. Per-symbol - full table</h2>
<p>Click column headers to sort. {n_attempted} rows.</p>
<table class="sortable">
<thead><tr>
{sortable_th("Symbol", "text")}
{sortable_th("Status", "text")}
{sortable_th("N", "num")}
{sortable_th("WR%", "num")}
{sortable_th("AvgR", "num")}
{sortable_th("AvgPnL%", "num")}
{sortable_th("IS N", "num")}
{sortable_th("IS WR%", "num")}
{sortable_th("OOS N", "num")}
{sortable_th("OOS WR%", "num")}
</tr></thead>
<tbody>
{all_body}
</tbody>
</table>

<h2>6. Skipped / missing / errors</h2>
{skipped_html}

<div class="ok">
<strong>Takeaway.</strong> Full-universe scan under the frozen rw63 + <code>{html_mod.escape(e.name)}</code> recipe.
Compare quality (WR / AvgR / AvgPnL%) to PaulTwenty - do not judge primarily on trade count.
Still research candidate ≠ gold ≠ DailyRun.
</div>

<p class="small">Generated by tools/vol_zone_break_retest.py --v2-rw63-fulluniv - research only.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")


def run_v2_rw63_fulluniv(
    *,
    data_dir: Path,
    out_dir: Path,
    stamp: str,
    lookback_days: int,
    universe_path: Path | None = None,
    paultwenty_stamp: str = DEFAULT_PAULTWENTY_RW63_STAMP,
    progress_every: int = 25,
) -> None:
    """Run RESEARCH_CANDIDATE_V2_RW63 + zone_atr05_ts40 on full local OHLC universe."""
    t0 = time.perf_counter()
    out_dir.mkdir(parents=True, exist_ok=True)

    if universe_path is None:
        universe_path = out_dir / "FullOHLC_universe.csv"
        symbols = materialize_full_ohlc_universe(universe_path, data_dir)
    else:
        # If caller points at a dir listing file that already exists, use it;
        # if path does not exist, materialize full OHLC list there.
        if universe_path.is_file():
            symbols = load_universe_symbols(universe_path)
            # also copy provenance list into stamp folder
            prov = out_dir / "FullOHLC_universe.csv"
            if universe_path.resolve() != prov.resolve():
                materialize_full_ohlc_universe(prov, data_dir, symbols=symbols)
        else:
            universe_path.parent.mkdir(parents=True, exist_ok=True)
            symbols = materialize_full_ohlc_universe(universe_path, data_dir)

    write_v2_rw63_fulluniv_baseline_md(
        out_dir / "BASELINE.md",
        stamp=stamp,
        universe_path=universe_path,
        n_symbols=len(symbols),
        data_dir=data_dir,
        paultwenty_stamp=paultwenty_stamp,
    )

    params = replace(RESEARCH_CANDIDATE_V2_RW63, lookback_days=lookback_days)
    primary = PRIMARY_EXIT
    compare_dir = DEFAULT_OUT_DIR / paultwenty_stamp
    pt_full, pt_is, pt_oos = _load_paultwenty_rw63_metrics(compare_dir)

    symbol_rows: list[dict] = []
    skipped: list[dict] = []
    all_signals: list[dict] = []
    n_with_data = 0
    n_with_signals = 0

    print(
        f"V2 rw63 FULLUNIV stamp={stamp} symbols={len(symbols)} lookback={lookback_days} "
        f"exit={primary.name} data_dir={data_dir}"
    )
    for i, sym in enumerate(symbols, 1):
        csv_path = data_dir / f"{sym}.csv"
        if not csv_path.is_file():
            note = f"missing CSV: {csv_path}"
            skipped.append({"symbol": sym, "note": note})
            symbol_rows.append({"symbol": sym, "status": "missing", "note": note})
            continue
        try:
            df = load_ohlcv(csv_path)
            atr = atr14(df)
            zones = build_zones(df, lookback_days)
        except Exception as e:  # noqa: BLE001
            note = str(e)
            skipped.append({"symbol": sym, "note": note})
            symbol_rows.append({"symbol": sym, "status": "error", "note": note})
            continue

        n_with_data += 1
        sigs, _, _ = run_symbol_with_params(sym, df, zones, atr, params)
        rows = enrich_signal_rows(sym, df, sigs, params, atr=atr, exit_spec=primary)
        all_signals.extend(rows)
        mn = summarize_signal_dicts(rows)
        is_r, oos_r = split_is_oos(rows)
        m_is = summarize_signal_dicts(is_r)
        m_oos = summarize_signal_dicts(oos_r)
        if mn["n_signals"] > 0:
            n_with_signals += 1
        symbol_rows.append(
            {
                "symbol": sym,
                "status": "ok",
                "n_bars": len(df),
                "date_start": str(pd.Timestamp(df["Date"].iloc[0]).date()),
                "date_end": str(pd.Timestamp(df["Date"].iloc[-1]).date()),
                "metrics_new": mn,
                "metrics_is": m_is,
                "metrics_oos": m_oos,
            }
        )
        if progress_every > 0 and (i % progress_every == 0 or i == len(symbols)):
            elapsed = time.perf_counter() - t0
            rate = i / elapsed if elapsed > 0 else 0.0
            eta = (len(symbols) - i) / rate if rate > 0 else 0.0
            print(
                f"  [{i}/{len(symbols)}] {sym}: N={mn['n_signals']} "
                f"WR={mn['win_rate']*100:.1f}% AvgR={mn['avg_r']:.2f} "
                f"| signals_so_far={len(all_signals)} "
                f"| {elapsed/60:.1f}m elapsed, ETA {eta/60:.1f}m"
            )

    full_m = summarize_signal_dicts(all_signals)
    is_rows, oos_rows = split_is_oos(all_signals)
    is_m = summarize_signal_dicts(is_rows)
    oos_m = summarize_signal_dicts(oos_rows)
    runtime_sec = time.perf_counter() - t0

    print(
        f"FULLUNIV rw63: N={full_m['n_signals']} WR={full_m['win_rate']*100:.1f}% "
        f"AvgR={full_m['avg_r']:.2f} AvgPnL%={full_m['avg_pnl_pct']:.2f}"
    )
    print(
        f"IS:  N={is_m['n_signals']} WR={is_m['win_rate']*100:.1f}% AvgR={is_m['avg_r']:.2f}"
    )
    print(
        f"OOS: N={oos_m['n_signals']} WR={oos_m['win_rate']*100:.1f}% AvgR={oos_m['avg_r']:.2f}"
    )
    print(
        f"PaulTwenty ref: N={pt_full['n_signals']} WR={pt_full['win_rate']*100:.1f}% "
        f"AvgR={pt_full['avg_r']:.2f}"
    )
    print(
        f"Coverage: attempted={len(symbols)} with_data={n_with_data} "
        f"with_signals={n_with_signals} skipped={len(skipped)} runtime={runtime_sec/60:.1f}m"
    )

    pd.DataFrame(all_signals).to_csv(out_dir / "signals_rw63.csv", index=False)

    per_flat = []
    for row in symbol_rows:
        if row.get("status") != "ok":
            per_flat.append(
                {"symbol": row["symbol"], "status": row["status"], "note": row.get("note", "")}
            )
            continue
        mn, m_is, m_oos = row["metrics_new"], row["metrics_is"], row["metrics_oos"]
        per_flat.append(
            {
                "symbol": row["symbol"],
                "status": "ok",
                "n_bars": row["n_bars"],
                "date_start": row["date_start"],
                "date_end": row["date_end"],
                "rw63_n": mn["n_signals"],
                "rw63_wr": mn["win_rate"],
                "rw63_avg_r": mn["avg_r"],
                "rw63_avg_pnl_pct": mn["avg_pnl_pct"],
                "rw63_is_n": m_is["n_signals"],
                "rw63_is_wr": m_is["win_rate"],
                "rw63_is_avg_r": m_is["avg_r"],
                "rw63_oos_n": m_oos["n_signals"],
                "rw63_oos_wr": m_oos["win_rate"],
                "rw63_oos_avg_r": m_oos["avg_r"],
            }
        )
    pd.DataFrame(per_flat).to_csv(out_dir / "per_symbol_rw63.csv", index=False)

    pd.DataFrame(
        [
            {
                "universe": "PaulTwenty",
                "stamp_ref": paultwenty_stamp,
                "retest_window": params.retest_window,
                "exit": primary.name,
                "n_signals": pt_full["n_signals"],
                "win_rate": pt_full["win_rate"],
                "avg_pnl_pct": pt_full["avg_pnl_pct"],
                "expectancy_pct": pt_full.get("expectancy_pct", pt_full["avg_pnl_pct"]),
                "avg_r": pt_full["avg_r"],
                "role": "paultwenty_ref",
            },
            {
                "universe": "FullOHLC",
                "stamp_ref": stamp,
                "retest_window": params.retest_window,
                "exit": primary.name,
                "n_signals": full_m["n_signals"],
                "win_rate": full_m["win_rate"],
                "avg_pnl_pct": full_m["avg_pnl_pct"],
                "expectancy_pct": full_m.get("expectancy_pct", full_m["avg_pnl_pct"]),
                "avg_r": full_m["avg_r"],
                "role": "fulluniv_confirmation",
            },
        ]
    ).to_csv(out_dir / "compare_pooled.csv", index=False)

    pd.DataFrame(
        [
            {
                "split": "IS",
                "split_date": str(OOS_SPLIT_DATE.date()),
                "universe": "FullOHLC",
                "freeze": "adopted_rw63",
                "exit": primary.name,
                "n_signals": is_m["n_signals"],
                "win_rate": is_m["win_rate"],
                "avg_pnl_pct": is_m["avg_pnl_pct"],
                "expectancy_pct": is_m.get("expectancy_pct", is_m["avg_pnl_pct"]),
                "avg_r": is_m["avg_r"],
            },
            {
                "split": "OOS",
                "split_date": str(OOS_SPLIT_DATE.date()),
                "universe": "FullOHLC",
                "freeze": "adopted_rw63",
                "exit": primary.name,
                "n_signals": oos_m["n_signals"],
                "win_rate": oos_m["win_rate"],
                "avg_pnl_pct": oos_m["avg_pnl_pct"],
                "expectancy_pct": oos_m.get("expectancy_pct", oos_m["avg_pnl_pct"]),
                "avg_r": oos_m["avg_r"],
            },
            {
                "split": "FULL",
                "split_date": str(OOS_SPLIT_DATE.date()),
                "universe": "FullOHLC",
                "freeze": "adopted_rw63",
                "exit": primary.name,
                "n_signals": full_m["n_signals"],
                "win_rate": full_m["win_rate"],
                "avg_pnl_pct": full_m["avg_pnl_pct"],
                "expectancy_pct": full_m.get("expectancy_pct", full_m["avg_pnl_pct"]),
                "avg_r": full_m["avg_r"],
            },
            {
                "split": "IS",
                "split_date": str(OOS_SPLIT_DATE.date()),
                "universe": "PaulTwenty",
                "freeze": "adopted_rw63",
                "exit": primary.name,
                "n_signals": pt_is["n_signals"],
                "win_rate": pt_is["win_rate"],
                "avg_pnl_pct": pt_is["avg_pnl_pct"],
                "expectancy_pct": pt_is.get("expectancy_pct", pt_is["avg_pnl_pct"]),
                "avg_r": pt_is["avg_r"],
            },
            {
                "split": "OOS",
                "split_date": str(OOS_SPLIT_DATE.date()),
                "universe": "PaulTwenty",
                "freeze": "adopted_rw63",
                "exit": primary.name,
                "n_signals": pt_oos["n_signals"],
                "win_rate": pt_oos["win_rate"],
                "avg_pnl_pct": pt_oos["avg_pnl_pct"],
                "expectancy_pct": pt_oos.get("expectancy_pct", pt_oos["avg_pnl_pct"]),
                "avg_r": pt_oos["avg_r"],
            },
            {
                "split": "FULL",
                "split_date": str(OOS_SPLIT_DATE.date()),
                "universe": "PaulTwenty",
                "freeze": "adopted_rw63",
                "exit": primary.name,
                "n_signals": pt_full["n_signals"],
                "win_rate": pt_full["win_rate"],
                "avg_pnl_pct": pt_full["avg_pnl_pct"],
                "expectancy_pct": pt_full.get("expectancy_pct", pt_full["avg_pnl_pct"]),
                "avg_r": pt_full["avg_r"],
            },
        ]
    ).to_csv(out_dir / "oos_split.csv", index=False)

    # coverage sidecar
    pd.DataFrame(
        [
            {
                "n_attempted": len(symbols),
                "n_with_data": n_with_data,
                "n_with_signals": n_with_signals,
                "n_skipped": len(skipped),
                "runtime_sec": round(runtime_sec, 1),
                "universe_path": str(universe_path),
                "data_dir": str(data_dir),
            }
        ]
    ).to_csv(out_dir / "coverage.csv", index=False)

    html_path = out_dir / "VolZone_FullUniverse_Summary.html"
    write_v2_rw63_fulluniv_html(
        html_path,
        stamp=stamp,
        universe_path=universe_path,
        data_dir=data_dir,
        params=params,
        full_m=full_m,
        is_m=is_m,
        oos_m=oos_m,
        pt_full=pt_full,
        pt_is=pt_is,
        pt_oos=pt_oos,
        paultwenty_stamp=paultwenty_stamp,
        symbol_rows=symbol_rows,
        skipped=skipped,
        n_attempted=len(symbols),
        n_with_data=n_with_data,
        n_with_signals=n_with_signals,
        runtime_sec=runtime_sec,
    )
    print(f"saved: {html_path}")
    print(
        "FULLUNIV confirmation complete under RESEARCH_CANDIDATE_V2_RW63 + zone_atr05_ts40. "
        "Research only - not gold."
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Vol-zone break/retest research prototype")
    ap.add_argument("--symbol", default="NVDA", help="Single-symbol mode (default)")
    ap.add_argument(
        "--universe",
        type=Path,
        default=None,
        help="Universe CSV path (e.g. drive/universes/PaulTwenty_universe.csv). "
        "When set, runs full-history baseline across all symbols.",
    )
    ap.add_argument(
        "--paultwenty",
        action="store_true",
        help=f"Shortcut: --universe {DEFAULT_PAULTWENTY.name}",
    )
    ap.add_argument("--symbols", default="", help="Comma-separated symbol list (overrides universe file contents)")
    ap.add_argument("--lookback-days", type=int, default=126)
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument(
        "--stamp",
        default="",
        help="Output stamp folder name under out-dir (default vol_zone_paultwenty_YYYYMMDD)",
    )
    ap.add_argument("--run-ab", action="store_true", help="Run small AB grid vs baseline (universe mode)")
    ap.add_argument(
        "--candidate-v2",
        action="store_true",
        help="Run HL-primary + quality-gates research candidate v2 (IS/OOS, exit compare, optional AB)",
    )
    ap.add_argument(
        "--v2-exit-ab",
        action="store_true",
        help="Freeze candidate v2 + zone_atr05_ts40 primary exit; IS/OOS + entry/exit ABs scored on that exit",
    )
    ap.add_argument(
        "--v2-rw63",
        action="store_true",
        help="Adopt RESEARCH_CANDIDATE_V2_RW63 (retest_window=63) as research freeze; "
        "PaulTwenty compare vs prior rw126 under zone_atr05_ts40 (not gold)",
    )
    ap.add_argument(
        "--v2-rw63-fulluniv",
        action="store_true",
        help="Confirm RESEARCH_CANDIDATE_V2_RW63 + zone_atr05_ts40 on full local OHLC "
        "universe (DailyRun ALL / all data/newdata/data/*.csv). Optional --universe path; "
        "default materializes FullOHLC_universe.csv in the stamp folder.",
    )
    ap.add_argument(
        "--prior-stamp",
        default="vol_zone_paultwenty_20260810",
        help="Label for prior baseline stamp (candidate-v2 / v2-exit-ab / v2-rw63 report)",
    )
    ap.add_argument("--skip-grid", action="store_true", help="Single-symbol: skip NVDA param grid")
    args = ap.parse_args()

    universe_mode = (
        bool(args.universe)
        or args.paultwenty
        or bool(args.symbols.strip())
        or args.candidate_v2
        or args.v2_exit_ab
        or args.v2_rw63
        or args.v2_rw63_fulluniv
    )
    if universe_mode:
        if args.paultwenty and args.universe is None:
            universe_path = DEFAULT_PAULTWENTY
        elif args.universe is not None:
            universe_path = args.universe
        elif args.v2_rw63_fulluniv:
            universe_path = None  # materialize from data_dir
        elif args.candidate_v2 or args.v2_exit_ab or args.v2_rw63:
            universe_path = DEFAULT_PAULTWENTY
        else:
            # symbols-only: write a temp list path label
            universe_path = Path("(symbols)")
        if args.v2_rw63_fulluniv:
            stamp = args.stamp.strip() or (
                "vol_zone_v2_rw63_fulluniv_" + pd.Timestamp.now().strftime("%Y%m%d")
            )
        elif args.v2_rw63:
            stamp = args.stamp.strip() or (
                "vol_zone_v2_rw63_" + pd.Timestamp.now().strftime("%Y%m%d")
            )
        elif args.v2_exit_ab:
            stamp = args.stamp.strip() or (
                "vol_zone_v2_exit_ab_" + pd.Timestamp.now().strftime("%Y%m%d")
            )
        elif args.candidate_v2:
            stamp = args.stamp.strip() or (
                "vol_zone_hl_quality_" + pd.Timestamp.now().strftime("%Y%m%d")
            )
        else:
            stamp = args.stamp.strip() or (
                "vol_zone_paultwenty_" + pd.Timestamp.now().strftime("%Y%m%d")
            )
        out_dir = args.out_dir / stamp if args.out_dir == DEFAULT_OUT_DIR else args.out_dir
        if args.symbols.strip():
            # materialize a tiny universe file in out_dir for provenance
            out_dir.mkdir(parents=True, exist_ok=True)
            universe_path = out_dir / "symbols_requested.txt"
            syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
            universe_path.write_text("\n".join(syms) + "\n", encoding="utf-8")
        if args.v2_rw63_fulluniv:
            pt_stamp = args.prior_stamp
            if pt_stamp in (
                "vol_zone_paultwenty_20260810",
                "vol_zone_hl_quality_20260810",
                "vol_zone_v2_exit_ab_20260810",
            ):
                pt_stamp = DEFAULT_PAULTWENTY_RW63_STAMP
            run_v2_rw63_fulluniv(
                data_dir=args.data_dir,
                out_dir=out_dir,
                stamp=stamp,
                lookback_days=args.lookback_days,
                universe_path=universe_path,
                paultwenty_stamp=pt_stamp,
            )
        elif args.v2_rw63:
            prior_exit = args.prior_stamp
            if prior_exit in (
                "vol_zone_paultwenty_20260810",
                "vol_zone_hl_quality_20260810",
            ):
                prior_exit = "vol_zone_v2_exit_ab_20260810"
            run_v2_rw63_freeze(
                universe_path=universe_path,
                data_dir=args.data_dir,
                out_dir=out_dir,
                stamp=stamp,
                lookback_days=args.lookback_days,
                prior_exit_ab_stamp=prior_exit,
                prior_entry_stamp="vol_zone_hl_quality_20260810",
            )
        elif args.v2_exit_ab:
            prior = args.prior_stamp
            if prior == "vol_zone_paultwenty_20260810":
                prior = "vol_zone_hl_quality_20260810"
            run_v2_exit_ab(
                universe_path=universe_path,
                data_dir=args.data_dir,
                out_dir=out_dir,
                stamp=stamp,
                lookback_days=args.lookback_days,
                prior_stamp=prior,
            )
        elif args.candidate_v2:
            run_candidate_v2(
                universe_path=universe_path,
                data_dir=args.data_dir,
                out_dir=out_dir,
                stamp=stamp,
                lookback_days=args.lookback_days,
                run_ab=args.run_ab,
                prior_stamp=args.prior_stamp,
            )
        else:
            run_paultwenty(
                universe_path=universe_path,
                data_dir=args.data_dir,
                out_dir=out_dir,
                stamp=stamp,
                lookback_days=args.lookback_days,
                run_ab=args.run_ab,
            )
        return

    sym = args.symbol.strip().upper()
    csv_path = args.data_dir / f"{sym}.csv"
    if not csv_path.is_file():
        raise SystemExit(f"Missing CSV: {csv_path}")

    df = load_ohlcv(csv_path)
    atr = atr14(df)
    try:
        zones = build_zones(df, args.lookback_days)
    except ValueError as e:
        raise SystemExit(str(e)) from e
    print(f"symbol={sym} bars={len(df)} zones={len(zones)} (OC+HL)")

    baseline_params = replace(RESEARCH_BASELINE, lookback_days=args.lookback_days)
    tag = params_tag(baseline_params)
    sigs, pnls = run_system(df, zones, atr, baseline_params, tag)
    wins = sum(1 for x in pnls if x > 0)
    baseline = ScanResult(
        params=baseline_params,
        signals=sigs,
        n_signals=len(sigs),
        n_wins=wins,
        win_rate=wins / len(sigs) if sigs else 0.0,
        avg_pnl_pct=float(np.mean(pnls)) if pnls else 0.0,
        feb26_may=any(
            s.entry_date.year == 2026 and s.entry_date.month == 5 and "2026-02-26" in s.zone_id
            for s in sigs
        ),
        feb26_jun=any(
            s.entry_date.year == 2026 and s.entry_date.month == 6 and "2026-02-26" in s.zone_id
            for s in sigs
        ),
        feb26_jul=any(
            s.entry_date.year == 2026 and s.entry_date.month == 7 and "2026-02-26" in s.zone_id
            for s in sigs
        ),
        tag=tag,
    )
    print(
        f"baseline signals={baseline.n_signals} WR={baseline.win_rate*100:.1f}% "
        f"Feb26 May/Jun/Jul={baseline.feb26_may}/{baseline.feb26_jun}/{baseline.feb26_jul}"
    )

    feb_case = feb26_case_report(df, zones, baseline_params)
    mt1 = replace(baseline_params, min_touches_before_entry=1)
    feb_case_mt1 = feb26_case_report(df, zones, mt1)

    for kind in ("OC", "HL"):
        info = feb_case.get(kind)
        if not info:
            print(f"Feb26 {kind}: not found")
            continue
        print(
            f"Feb26 {kind}: visits May/Jun/Jul="
            f"{info['month_visits']['May']}/{info['month_visits']['Jun']}/{info['month_visits']['Jul']} "
            f"signals May/Jun/Jul="
            f"{info['signal_months']['May']}/{info['signal_months']['Jun']}/{info['signal_months']['Jul']}"
        )
        for s in info["signals"]:
            print(
                f"  {kind} entry {s.entry_date.date()} touches={s.touch_count_all} "
                f"holds={s.touch_count_holds}"
            )
    print("Feb26 with min_touches=1:")
    for kind in ("OC", "HL"):
        info = feb_case_mt1.get(kind)
        if not info:
            continue
        sm = info["signal_months"]
        print(
            f"  {kind} signals May/Jun/Jul={sm['May']}/{sm['Jun']}/{sm['Jul']} "
            f"n_entries={len(info['signals'])}"
        )

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    zoom = out_dir / f"VolZone_BreakRetest_{sym}_2025_2026.png"
    full = out_dir / f"VolZone_BreakRetest_{sym}.png"
    plot_annotated(
        df,
        zones,
        sigs,
        feb_case,
        zoom,
        start="2025-10-01",
        end="2026-08-10",
        title=f"{sym} - Feb26 vol-zone break & retest buys (OC+HL, research)",
    )
    plot_full_history_signals(
        df,
        sigs,
        full,
        title=f"{sym} - vol-zone retest entries (full history, baseline params)",
    )
    print(f"saved: {zoom}")
    print(f"saved: {full}")

    if args.skip_grid:
        grid: list[ScanResult] = [baseline]
    else:
        print("running parameter grid...")
        grid = grid_search(df, zones, atr)
        catch = [r for r in grid if r.feb26_may and r.feb26_jun and r.feb26_jul]
        print(f"grid size={len(grid)}; combos catching May+Jun+Jul={len(catch)}")

    html_path = out_dir / "VolZone_BreakRetest_Hypothesis.html"
    write_html_report(
        html_path,
        symbol=sym,
        df=df,
        zones=zones,
        baseline=baseline,
        grid=grid,
        feb_case=feb_case,
        feb_case_mt1=feb_case_mt1,
        chart_paths={
            "Full history signals": full,
            "2025–2026 zoom (Feb26 case)": zoom,
        },
    )
    print(f"saved: {html_path}")

    print("---")
    print(
        "HYPOTHESIS: Persistent zones from rolling 6m max-vol days become "
        "support after upside break; buy from-above retests. Touch/hold counts "
        "raise zone confidence (min_touches knob). May needs eps near-miss; "
        "Jun/Jul are raw intersects on OC and HL."
    )


if __name__ == "__main__":
    main()
