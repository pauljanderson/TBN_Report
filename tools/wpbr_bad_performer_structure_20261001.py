"""Describe pre-entry structure on the frozen WPBR bad-performer sample.

Sample: symbols with at least 5 closed trades and a win rate under 20% in the
adopted 3-year positive-growth book (control arm of the 2026-10-01 hurdle run).
A win is a closed trade with P&L percent above zero.

This script measures. It does not add, rank, or keep a filter.
"""
from __future__ import annotations

import csv
import html as html_mod
import math
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "stock_analysis"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from _gen_too_high_diff import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from report_page_extras import RESPONSIVE_TABLE_CSS, SWIPE_NOTE_HTML  # noqa: E402
from wpbr_zones import compute_wpbr_touch_stream  # noqa: E402

STAMP = "20261001"
CLOSED = ROOT / "tmp_wpbr_growth_min_pct_ab_20261001" / "control" / "WPBR_Closed_261001155729.csv"
DATA = ROOT / "data" / "newdata" / "data"
OUT = ROOT / "drive" / "paul_experiments" / f"wpbr_bad_performer_structure_{STAMP}"
LOOK = 756
BAND = 0.22
MIN_TRADES = 5
MAX_WR = 0.20

REQUEST_PROMPT = """Freeze the WPBR bad-performer sample as symbols with ≥5 trades and <20% win rate after the adopted 3-year positive-growth filter. Using full historical daily OHLC data for only those symbols, perform structural analysis of every WPBR trade. Look for repeated pre-entry characteristics, especially SMA100/SMA200 trend structure and persistence, prior WPBR resistance zones within 22% above the active entry zone, quality/path of the prior 3-year advance, and other objectively measurable price-structure commonalities. Do not create or optimize filters yet. Report repeated observations and their frequency across trades and symbols."""

LAYMAN = (
    "We took the research book that already requires the close to be higher than it was 756 trading sessions earlier. "
    "That is Pivot Break and Retest (WPBR) plus the adopted 3-year positive-growth rule. "
    "A bad performer here is a symbol with at least 5 closed trades in that book and a win rate under 20%. "
    "A win is a closed trade that made money. "
    "For every one of those trades we looked at the daily open, high, low, and close before the buy. "
    "We asked whether the same shapes keep showing up: where price sits versus the 100-day and 200-day simple moving averages (SMA100 and SMA200), "
    "how long price had already stayed above those averages, whether older WPBR zones sat within 22% above the zone being bought, "
    "and what the prior three-year rise looked like. "
    "Nothing here is a new buy rule. The counts are how often each shape appeared."
)


def _f(raw: Any) -> float:
    if raw is None:
        return float("nan")
    s = str(raw).strip().replace(",", "").replace("%", "").replace("$", "")
    if not s or s.lower() in {"nan", "none", "null"}:
        return float("nan")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def _ymd(raw: str) -> str:
    s = str(raw or "").strip().replace("-", "")[:8]
    return s if len(s) == 8 and s.isdigit() else ""


def _notify(paths: list[Path], message: str) -> None:
    cmd = [sys.executable, str(ROOT / "tools" / "ntfy_job_done.py"), "-t", "WPBR bad-performer structure"]
    for p in paths:
        cmd.extend(["--path", str(p)])
    cmd.extend(["-m", message])
    subprocess.run(cmd, cwd=str(ROOT), check=False)


def load_closed() -> list[dict[str, Any]]:
    rows = []
    with CLOSED.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _ymd(raw.get("DATE_OPENED") or "")
            if not opened:
                continue
            pnl = _f(raw.get("PNL_PCT"))
            rows.append({
                "symbol": str(raw.get("SYMBOL") or "").strip().upper(),
                "opened": opened,
                "pnl": pnl,
                "win": bool(math.isfinite(pnl) and pnl > 0),
                "zone_id": str(raw.get("WPBR_ZONE_ID") or "").strip(),
                "zone_top": _f(raw.get("ZONE_TOP")),
                "zone_bottom": _f(raw.get("ZONE_BOTTOM")),
                "sma200_state": str(raw.get("IND_PRICE_OVER_SMA200") or "").strip().upper(),
                "sma50_200": str(raw.get("IND_SMA50_OVER_SMA200") or "").strip().upper(),
                "px_sma50": str(raw.get("IND_PRICE_OVER_SMA50") or "").strip().upper(),
                "px_sma20": str(raw.get("IND_PRICE_OVER_SMA20") or "").strip().upper(),
                "gap_above": _f(raw.get("PCT_ENTRY_TO_BOTTOM_ZONE_ABOVE")),
                "zone_above": _f(raw.get("ZONE_ABOVE_CENTER")),
                "dist_52": _f(raw.get("DIST_TO_52W_HIGH_PCT_AT_TRIGGER")),
                "spy3": _f(raw.get("SPY_COMPARE_3Y")),
                "spy1": _f(raw.get("SPY_COMPARE_1Y")),
            })
    return rows


def freeze_symbols(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        bucket[row["symbol"]].append(row)
    out = []
    for sym, trades in bucket.items():
        n = len(trades)
        wins = sum(1 for t in trades if t["win"])
        if n >= MIN_TRADES and wins / n < MAX_WR:
            out.append({
                "symbol": sym,
                "n": n,
                "wins": wins,
                "wr": 100.0 * wins / n,
                "trades": trades,
            })
    out.sort(key=lambda r: (-r["n"], r["symbol"]))
    return out


def _sma(close: np.ndarray, period: int) -> np.ndarray:
    out = np.full(len(close), np.nan)
    if len(close) < period:
        return out
    c = np.cumsum(close)
    out[period - 1 :] = (c[period - 1 :] - np.concatenate(([0.0], c[:-period]))) / period
    return out


def _frac_above(close: np.ndarray, sma: np.ndarray, end: int, window: int) -> float:
    start = end - window + 1
    if start < 0 or end >= len(close):
        return float("nan")
    c = close[start : end + 1]
    s = sma[start : end + 1]
    if c.size != window or not np.all(np.isfinite(c) & (c > 0) & np.isfinite(s) & (s > 0)):
        return float("nan")
    return float(np.mean(c > s))


def _path_stats(close: np.ndarray, end: int) -> dict[str, float]:
    empty = {
        "gain": float("nan"),
        "early": float("nan"),
        "late": float("nan"),
        "giveback": float("nan"),
        "path_dd": float("nan"),
        "r2": float("nan"),
        "late_dominates": float("nan"),
        "deep_giveback": float("nan"),
        "deep_path_dd": float("nan"),
        "choppy": float("nan"),
    }
    start = end - LOOK
    if start < 0 or end >= len(close):
        return empty
    path = close[start : end + 1]
    if path.size != LOOK + 1 or not np.all(np.isfinite(path) & (path > 0)):
        return empty
    gain = path[-1] / path[0] - 1.0
    early = path[-252] / path[0] - 1.0
    late = path[-1] / path[-252] - 1.0
    peak = np.maximum.accumulate(path)
    dd = float(np.max((peak - path) / peak))
    giveback = float((path.max() - path[-1]) / path.max())
    logp = np.log(path)
    x = np.arange(logp.size, dtype=np.float64)
    x = x - x.mean()
    y = logp - logp.mean()
    den = float(np.dot(x, x) * np.dot(y, y))
    r2 = float((np.dot(x, y) ** 2) / den) if den > 0 else float("nan")
    return {
        "gain": gain,
        "early": early,
        "late": late,
        "giveback": giveback,
        "path_dd": dd,
        "r2": r2,
        "late_dominates": 1.0 if (late > early and late > 0) else 0.0,
        "deep_giveback": 1.0 if giveback >= 0.20 else 0.0,
        "deep_path_dd": 1.0 if dd >= 0.30 else 0.0,
        "choppy": 1.0 if math.isfinite(r2) and r2 < 0.30 else 0.0,
    }


def _load_ohlc(sym: str) -> pd.DataFrame | None:
    path = DATA / f"{sym}.csv"
    if not path.is_file():
        return None
    df = pd.read_csv(path)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date")
    for col in ("Open", "High", "Low", "Close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "Volume" in df.columns:
        df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce").fillna(0.0)
    else:
        df["Volume"] = 0.0
    return df.set_index("Date")


def zones_for(df: pd.DataFrame) -> list[dict[str, Any]]:
    stream = compute_wpbr_touch_stream(
        df,
        band_pct=0.015,
        strong_pre_pivot_bars=3,
        strong_pre_pivot_pct=0.10,
        strong_post_pivot_bars=3,
        strong_post_pivot_pct=0.10,
        strong_pivot_mode="either",
        breakout_confirmation=0.03,
        max_days_after_retest=2,
        retest_mode="stop_looking",
        zone_price_round_decimals=2,
        merge_overlapping_zones=False,
    )
    return list(stream.get("wpbr_zone_events") or [])


def analyze_symbol(pack: dict[str, Any]) -> list[dict[str, Any]]:
    sym = pack["symbol"]
    df = _load_ohlc(sym)
    if df is None or df.empty:
        print(f"[structure] missing OHLC {sym}", flush=True)
        return []
    close = df["Close"].to_numpy(dtype=np.float64)
    dates = df.index.strftime("%Y%m%d").to_numpy()
    sma100 = _sma(close, 100)
    sma200 = _sma(close, 200)
    events = zones_for(df)
    by_id = {str(ev.get("wpbr_zone_id") or ""): ev for ev in events}
    rows = []
    for trade in pack["trades"]:
        hits = np.flatnonzero(dates < trade["opened"])
        if hits.size == 0:
            continue
        i = int(hits[-1])
        px = float(close[i])
        s100 = float(sma100[i]) if np.isfinite(sma100[i]) else float("nan")
        s200 = float(sma200[i]) if np.isfinite(sma200[i]) else float("nan")
        ev = by_id.get(trade["zone_id"])
        active_upper = float(ev["zone_upper"]) if ev else trade["zone_top"]
        active_lower = float(ev["zone_lower"]) if ev else trade["zone_bottom"]
        n_band = 0
        n_still = 0
        nearest = float("nan")
        if math.isfinite(active_upper) and active_upper > 0:
            for other in events:
                if str(other.get("wpbr_zone_id") or "") == trade["zone_id"]:
                    continue
                born = int(other.get("activation_bar") if other.get("activation_bar") is not None else -1)
                if born < 0 or born >= i:
                    continue
                lo = float(other.get("zone_lower") or float("nan"))
                if not math.isfinite(lo) or lo <= active_upper:
                    continue
                gap = (lo - active_upper) / active_upper
                if gap <= BAND:
                    n_band += 1
                    nearest = gap if not math.isfinite(nearest) else min(nearest, gap)
                    if math.isfinite(px) and lo > px:
                        n_still += 1
        path = _path_stats(close, i)
        s200_63 = float(sma200[i - 63]) if i >= 63 and np.isfinite(sma200[i - 63]) else float("nan")
        s200_252 = float(sma200[i - 252]) if i >= 252 and np.isfinite(sma200[i - 252]) else float("nan")
        p100_252 = _frac_above(close, sma100, i, 252)
        p200_252 = _frac_above(close, sma200, i, 252)
        p100_756 = _frac_above(close, sma100, i, 756)
        p200_756 = _frac_above(close, sma200, i, 756)
        rows.append({
            "symbol": sym,
            "opened": trade["opened"],
            "win": trade["win"],
            "zone_matched": ev is not None,
            "px": px,
            "s100": s100,
            "s200": s200,
            "below_sma100": 1.0 if math.isfinite(s100) and s100 > 0 and px < s100 else (0.0 if math.isfinite(s100) and s100 > 0 else float("nan")),
            "below_sma200": 1.0 if math.isfinite(s200) and s200 > 0 and px < s200 else (0.0 if math.isfinite(s200) and s200 > 0 else float("nan")),
            "sma100_below_sma200": 1.0 if math.isfinite(s100) and math.isfinite(s200) and s100 > 0 and s200 > 0 and s100 < s200 else (
                0.0 if math.isfinite(s100) and math.isfinite(s200) and s100 > 0 and s200 > 0 else float("nan")
            ),
            "both_below": 1.0 if (
                math.isfinite(s100) and math.isfinite(s200) and px < s100 and px < s200
            ) else (
                0.0 if math.isfinite(s100) and math.isfinite(s200) and s100 > 0 and s200 > 0 else float("nan")
            ),
            "sma200_falling_63": 1.0 if math.isfinite(s200) and math.isfinite(s200_63) and s200 < s200_63 else (
                0.0 if math.isfinite(s200) and math.isfinite(s200_63) else float("nan")
            ),
            "sma200_falling_252": 1.0 if math.isfinite(s200) and math.isfinite(s200_252) and s200 < s200_252 else (
                0.0 if math.isfinite(s200) and math.isfinite(s200_252) else float("nan")
            ),
            "p100_252": p100_252,
            "p200_252": p200_252,
            "p100_756": p100_756,
            "p200_756": p200_756,
            "p200_252_under_half": 1.0 if math.isfinite(p200_252) and p200_252 < 0.50 else (0.0 if math.isfinite(p200_252) else float("nan")),
            "p200_756_under_half": 1.0 if math.isfinite(p200_756) and p200_756 < 0.50 else (0.0 if math.isfinite(p200_756) else float("nan")),
            "p100_252_under_half": 1.0 if math.isfinite(p100_252) and p100_252 < 0.50 else (0.0 if math.isfinite(p100_252) else float("nan")),
            "p100_756_under_half": 1.0 if math.isfinite(p100_756) and p100_756 < 0.50 else (0.0 if math.isfinite(p100_756) else float("nan")),
            "n_band": n_band,
            "n_still": n_still,
            "nearest_gap": nearest,
            "any_overhead_22": 1.0 if n_band > 0 else 0.0,
            "two_overhead_22": 1.0 if n_band >= 2 else 0.0,
            "overhead_still_above_price": 1.0 if n_still > 0 else 0.0,
            "close_overhead_10": 1.0 if math.isfinite(nearest) and nearest <= 0.10 else 0.0,
            "active_upper": active_upper,
            "active_lower": active_lower,
            **path,
        })
    print(f"[structure] {sym} trades={len(rows)} zones={len(events)} matched={sum(1 for r in rows if r['zone_matched'])}", flush=True)
    return rows


def _majority(rows: list[dict[str, Any]], key: str) -> tuple[int, int]:
    by: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        v = row.get(key)
        if isinstance(v, (int, float)) and math.isfinite(float(v)):
            by[row["symbol"]].append(float(v))
    hit = 0
    for vals in by.values():
        if vals and sum(1 for v in vals if v >= 0.5) / len(vals) >= 0.5:
            hit += 1
    return hit, len(by)


def _trade_rate(rows: list[dict[str, Any]], key: str) -> tuple[int, int]:
    defined = [row[key] for row in rows if isinstance(row.get(key), (int, float)) and math.isfinite(float(row[key]))]
    hit = sum(1 for v in defined if float(v) >= 0.5)
    return hit, len(defined)


def _quantiles(rows: list[dict[str, Any]], key: str) -> dict[str, float]:
    vals = [float(row[key]) for row in rows if isinstance(row.get(key), (int, float)) and math.isfinite(float(row[key]))]
    if not vals:
        return {"n": 0, "p25": float("nan"), "p50": float("nan"), "p75": float("nan")}
    arr = np.array(vals, dtype=np.float64)
    return {
        "n": len(vals),
        "p25": float(np.percentile(arr, 25)),
        "p50": float(np.percentile(arr, 50)),
        "p75": float(np.percentile(arr, 75)),
    }


BINARY: list[tuple[str, str, str]] = [
    ("below_sma100", "Trigger close under SMA100", "The close on the day before the buy is below the 100-day simple moving average."),
    ("below_sma200", "Trigger close under SMA200", "The close on the day before the buy is below the 200-day simple moving average."),
    ("both_below", "Trigger close under both SMA100 and SMA200", "Price is under both averages on the day before the buy."),
    ("sma100_below_sma200", "SMA100 under SMA200", "The shorter average sits below the longer one. The averages are not stacked upward."),
    ("sma200_falling_63", "SMA200 lower than 63 sessions earlier", "The 200-day average itself is falling over about three months."),
    ("sma200_falling_252", "SMA200 lower than 252 sessions earlier", "The 200-day average itself is falling over about one year."),
    ("p100_252_under_half", "Under half of the prior year closed above SMA100", "Of the 252 sessions ending on the trigger day, fewer than half closed strictly above SMA100. Counted only when every one of those sessions has a defined average."),
    ("p200_252_under_half", "Under half of the prior year closed above SMA200", "Same one-year window versus SMA200."),
    ("p100_756_under_half", "Under half of the prior 3 years closed above SMA100", "Of the 756 sessions ending on the trigger day, fewer than half closed strictly above SMA100."),
    ("p200_756_under_half", "Under half of the prior 3 years closed above SMA200", "Same three-year window versus SMA200."),
    ("any_overhead_22", "At least one prior zone within 22% above the entry zone", "A different WPBR zone, born before the trigger day, whose lower bound sits above this trade's zone upper bound, and that gap is 22% or less of the entry zone's upper bound."),
    ("two_overhead_22", "Two or more prior zones in that 22% band", "The same 22% band contains at least two earlier zones."),
    ("overhead_still_above_price", "One of those zones is still above the trigger close", "The lower bound is above the trigger close, so price has not already cleared that zone."),
    ("close_overhead_10", "Nearest zone in the 22% band is within 10%", "Among zones that qualify for the 22% band, the closest gap is 10% or less. Trades with no such zone count as no."),
    ("late_dominates", "The last year rose more than the two years before it", "Inside the exact 756-session window, the last 252 sessions gained more than the first 504, and the last year itself was up."),
    ("deep_giveback", "Trigger close is at least 20% under the 3-year high", "The highest close in the 756-session window is at least 20% above the trigger close."),
    ("deep_path_dd", "The 3-year path fell at least 30% from a close high", "Somewhere inside those 756 sessions, the close gave back at least 30% from a prior close high in the same window."),
    ("choppy", "The 3-year path is not a straight rise", "A straight-line fit to the log of the close over those 756 sessions explains under 30% of the path. That is a descriptive label for a jagged rise, not a buy rule."),
]


def _fmt_pct(v: float, nd: int = 1) -> str:
    if not math.isfinite(v):
        return "—"
    return f"{v:.{nd}f}%"


def _fmt_num(v: float, nd: int = 1, scale: float = 1.0, suffix: str = "") -> str:
    if not math.isfinite(v):
        return "—"
    return f"{v * scale:.{nd}f}{suffix}"


def _context_rows(all_rows: list[dict[str, Any]], bad_syms: set[str]) -> list[dict[str, Any]]:
    specs = [
        ("sma200_bear", "Recorded state: price under SMA200", lambda r: r["sma200_state"] == "BEAR"),
        ("stack_bear", "Recorded state: SMA50 under SMA200", lambda r: r["sma50_200"] == "BEAR"),
        ("sma50_bear", "Recorded state: price under SMA50", lambda r: r["px_sma50"] == "BEAR"),
        ("sma20_bear", "Recorded state: price under SMA20", lambda r: r["px_sma20"] == "BEAR"),
        ("gap22", "Recorded nearest zone above is 0 to 22% from the fill", lambda r: math.isfinite(r["gap_above"]) and r["zone_above"] > 0 and 0 < r["gap_above"] <= 22),
        ("no_above", "Recorded book has no zone above", lambda r: not (math.isfinite(r["zone_above"]) and r["zone_above"] > 0)),
        ("far_high", "Trigger close at least 10% under the 52-week high", lambda r: math.isfinite(r["dist_52"]) and r["dist_52"] >= 10),
        ("spy3_neg", "Three-year gain versus SPY is negative", lambda r: math.isfinite(r["spy3"]) and r["spy3"] < 0),
        ("spy1_neg", "One-year gain versus SPY is negative", lambda r: math.isfinite(r["spy1"]) and r["spy1"] < 0),
    ]
    out = []
    for key, label, fn in specs:
        def _rate(pool: list[dict[str, Any]]) -> tuple[float, int, int, float, int]:
            marked = []
            by: dict[str, list[bool]] = defaultdict(list)
            for row in pool:
                flag = bool(fn(row))
                marked.append(flag)
                by[row["symbol"]].append(flag)
            n = len(marked)
            hit = sum(1 for v in marked if v)
            sym_hit = sum(1 for vals in by.values() if vals and sum(1 for v in vals if v) / len(vals) >= 0.5)
            return (100.0 * hit / n if n else float("nan")), hit, n, (100.0 * sym_hit / len(by) if by else float("nan")), len(by)

        bad = _rate([r for r in all_rows if r["symbol"] in bad_syms])
        rest = _rate([r for r in all_rows if r["symbol"] not in bad_syms])
        out.append({
            "key": key,
            "label": label,
            "bad_pct": bad[0], "bad_hit": bad[1], "bad_n": bad[2], "bad_sym": bad[3], "bad_sn": bad[4],
            "rest_pct": rest[0], "rest_hit": rest[1], "rest_n": rest[2], "rest_sym": rest[3], "rest_sn": rest[4],
        })
    return out


def write_page(
    packs: list[dict[str, Any]],
    feat: list[dict[str, Any]],
    context: list[dict[str, Any]],
) -> tuple[Path, Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    esc = html_mod.escape
    n_trades = len(feat)
    n_sym = len(packs)
    wins = sum(1 for r in feat if r["win"])
    matched = sum(1 for r in feat if r["zone_matched"])
    obs = []
    for key, label, defin in BINARY:
        hit, n = _trade_rate(feat, key)
        sh, sn = _majority(feat, key)
        obs.append({
            "label": label,
            "defin": defin,
            "hit": hit,
            "n": n,
            "pct": 100.0 * hit / n if n else float("nan"),
            "sh": sh,
            "sn": sn,
            "sp": 100.0 * sh / sn if sn else float("nan"),
        })
    repeated = [o for o in obs if math.isfinite(o["pct"]) and o["pct"] >= 60 and math.isfinite(o["sp"]) and o["sp"] >= 60]
    repeated.sort(key=lambda o: (-o["pct"], o["label"]))

    def table(headers: list[tuple[str, str]], body: list[str]) -> str:
        head = "".join(sortable_th(h, k) for h, k in headers)
        return (
            SWIPE_NOTE_HTML
            + "<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>"
            + head
            + "</tr></thead><tbody>"
            + "".join(body)
            + "</tbody></table></div>"
        )

    rep_rows = []
    for o in repeated:
        rep_rows.append(
            "<tr>"
            f"<td>{esc(o['label'])}</td>"
            f"<td>{o['hit']} / {o['n']}</td><td>{_fmt_pct(o['pct'])}</td>"
            f"<td>{o['sh']} / {o['sn']}</td><td>{_fmt_pct(o['sp'])}</td>"
            f"<td>{esc(o['defin'])}</td></tr>"
        )
    if not rep_rows:
        rep_rows.append("<tr><td colspan=\"6\">No measured shape cleared 60% of trades and 60% of symbols.</td></tr>")

    all_rows = []
    for o in sorted(obs, key=lambda r: (-r["pct"] if math.isfinite(r["pct"]) else -1, r["label"])):
        all_rows.append(
            "<tr>"
            f"<td>{esc(o['label'])}</td>"
            f"<td>{o['hit']} / {o['n']}</td><td>{_fmt_pct(o['pct'])}</td>"
            f"<td>{o['sh']} / {o['sn']}</td><td>{_fmt_pct(o['sp'])}</td>"
            f"<td>{esc(o['defin'])}</td></tr>"
        )

    cont_specs = [
        ("p100_252", "Share of prior 252 closes above SMA100", 100, "%"),
        ("p200_252", "Share of prior 252 closes above SMA200", 100, "%"),
        ("p100_756", "Share of prior 756 closes above SMA100", 100, "%"),
        ("p200_756", "Share of prior 756 closes above SMA200", 100, "%"),
        ("gain", "3-year close-to-close gain", 100, "%"),
        ("early", "Gain over the first 504 sessions of that window", 100, "%"),
        ("late", "Gain over the last 252 sessions of that window", 100, "%"),
        ("giveback", "Giveback from the highest close in the window to the trigger close", 100, "%"),
        ("path_dd", "Deepest close-to-close drop inside the window", 100, "%"),
        ("r2", "How straight the log-price path is (1 = a straight line)", 1, ""),
        ("nearest_gap", "Gap to the nearest prior zone in the 22% band", 100, "%"),
        ("n_band", "Count of prior zones in the 22% band", 1, ""),
    ]
    cont_rows = []
    for key, label, scale, suffix in cont_specs:
        q = _quantiles(feat, key)
        nd = 0 if key == "n_band" else 1
        cont_rows.append(
            "<tr>"
            f"<td>{esc(label)}</td><td>{q['n']}</td>"
            f"<td>{_fmt_num(q['p25'], nd, scale, suffix)}</td>"
            f"<td>{_fmt_num(q['p50'], nd, scale, suffix)}</td>"
            f"<td>{_fmt_num(q['p75'], nd, scale, suffix)}</td></tr>"
        )

    ctx_rows = []
    for row in context:
        ctx_rows.append(
            "<tr>"
            f"<td>{esc(row['label'])}</td>"
            f"<td>{_fmt_pct(row['bad_pct'])}</td><td>{row['bad_hit']} / {row['bad_n']}</td>"
            f"<td>{_fmt_pct(row['bad_sym'])}</td>"
            f"<td>{_fmt_pct(row['rest_pct'])}</td><td>{row['rest_hit']} / {row['rest_n']}</td>"
            f"<td>{_fmt_pct(row['rest_sym'])}</td></tr>"
        )

    sym_rows = []
    by = defaultdict(list)
    for row in feat:
        by[row["symbol"]].append(row)
    for pack in packs:
        rows = by.get(pack["symbol"], [])
        def med(key: str) -> float:
            q = _quantiles(rows, key)
            return q["p50"]
        oh, on = _trade_rate(rows, "any_overhead_22")
        sym_rows.append(
            "<tr>"
            f"<td>{esc(pack['symbol'])}</td><td>{pack['n']}</td><td>{pack['wins']}</td><td>{_fmt_pct(pack['wr'])}</td>"
            f"<td>{_fmt_num(med('p200_756'), 0, 100, '%')}</td>"
            f"<td>{_fmt_num(med('gain'), 0, 100, '%')}</td>"
            f"<td>{_fmt_num(med('giveback'), 0, 100, '%')}</td>"
            f"<td>{oh} / {on}</td></tr>"
        )

    freeze = [
        f"Book: control arm of wpbr_growth_min_pct_3y_ab_20261001, closed file {CLOSED.name}. Adopted filter is growth_filter_enabled=true, growth_filter_strict_gt=true, growth_bars=756, growth_min_pct=0, min_history_bars=756, growth_history_slack_bars=0. Trigger close must be greater than the close exactly 756 sessions earlier.",
        f"Sample freeze: a symbol is in the sample when it has at least {MIN_TRADES} closed trades in that book and wins / trades is under {MAX_WR:.0%}. A win is P&L percent strictly above zero. The freeze is the {n_sym} symbols listed below, {n_trades} trades, {wins} wins.",
        "Trigger bar: the last daily bar whose date is strictly before DATE_OPENED. That is the day before the next-open fill.",
        "SMA100 and SMA200 are simple moving averages of the daily close, recomputed from that symbol's full CSV. A session counts as above only when the close is strictly above the average. A persistence window is used only when every session in it has a positive close and a defined average. Otherwise that trade is left out of that row's denominator.",
        "The 22% zone band uses the full prior WPBR zone list from the same production zone knobs (band 1.5%, strong pivot either side 3 bars and 10%, breakout confirmation 3%, retest window 2 days, no zone merge). A zone counts when its pivot week starts before the trigger bar, it is not this trade's zone id, its lower bound is above this trade's zone upper bound, and (lower − upper) / upper is 22% or less. This is wider than the recorded nearest-zone field, which looks back 504 sessions and measures from the fill price.",
        f"Zone id matched the recomputed list on {matched} of {n_trades} trades. A miss still uses ZONE_TOP and ZONE_BOTTOM from the closed trade and still excludes that zone id.",
        "Three-year path uses the close exactly 756 sessions before the trigger through the trigger close. Giveback, path drop, and the straight-line score are descriptions of that path. The 20%, 30%, and 0.30 cuts were named before the counts were read. They are labels, not searched thresholds.",
        "A symbol counts toward the symbol rate when the shape is true on at least half of that symbol's measured trades. The 60% callout is a reading aid for what showed up often. It is not a keep rule.",
        "The recorded-state table uses columns already on every closed trade in the same book. It is context, so a shape that is common to all WPBR trades is not read as special to this sample. It is not a filter test.",
        "Research only. Not gold. Not DailyRun. No new entry rule was added.",
    ]

    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>WPBR bad-performer structure</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; }}
*{{box-sizing:border-box}}
body{{margin:0;font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header,main{{max-width:1200px;margin:0 auto;padding:1rem}}
h1{{font-size:1.35rem;margin:0 0 .4rem}}
h2{{font-size:1.05rem;margin:0 0 .5rem}}
.muted{{color:var(--muted)}}
.callout,section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.9rem 1rem;margin:1rem 0}}
pre{{white-space:pre-wrap;font-size:.9rem}}
th,td{{border-bottom:1px solid var(--line);padding:.35rem .45rem;text-align:right;white-space:nowrap}}
th:first-child,td:first-child{{text-align:left}}
td:last-child{{text-align:left;white-space:normal;min-width:16rem}}
{SORTABLE_TH_CSS}
{RESPONSIVE_TABLE_CSS}
@media (max-width: 800px) {{
  table.sortable > thead > tr > th.sortable-th:first-child,
  table.sortable > tbody > tr > td:first-child {{ background:#1a2332; color:#e7ecf3; }}
}}
</style></head><body>
<header>
<h1>WPBR bad-performer price structure</h1>
<p class="muted">Pivot Break and Retest (WPBR). Description only. No new filter. Click a column header to sort. Swipe sideways to see more columns.</p>
</header>
<main>
<div class="callout"><h2>What you asked</h2>
<pre>{esc(REQUEST_PROMPT.strip())}</pre>
<p><strong>In plain English.</strong> {esc(LAYMAN)}</p>
</div>
<section><h2>What showed up often</h2>
<p class="muted">A shape is listed here when it is true on at least 60% of the measured trades and on at least half the trades of at least 60% of the symbols. Simple moving average is SMA. These lines are observations. They are not buy rules.</p>
{table([
    ("Observation", "text"), ("Trades", "num"), ("Trade rate", "num"),
    ("Symbols", "num"), ("Symbol rate", "num"), ("What was measured", "text"),
], rep_rows)}
</section>
<section><h2>Every measured shape</h2>
<p class="muted">{n_sym} symbols, {n_trades} trades, {wins} wins ({_fmt_pct(100.0 * wins / n_trades if n_trades else float('nan'))}). The trade rate uses only trades where that measurement existed. The symbol rate is the share of those symbols where at least half of the symbol's measured trades show the shape.</p>
{table([
    ("Observation", "text"), ("Trades", "num"), ("Trade rate", "num"),
    ("Symbols", "num"), ("Symbol rate", "num"), ("What was measured", "text"),
], all_rows)}
</section>
<section><h2>Levels, not yes-or-no cuts</h2>
<p class="muted">Median is the middle trade. P25 and P75 are the trades one quarter of the way in from each end. A blank nearest-zone gap means that trade had no prior zone in the 22% band, and those trades are left out of that row.</p>
{table([
    ("Measure", "text"), ("Trades measured", "num"), ("P25", "num"), ("Median", "num"), ("P75", "num"),
], cont_rows)}
</section>
<section><h2>Same book, recorded columns, for context</h2>
<p class="muted">These columns were already stored on every closed trade. Bad sample versus the other symbols in the same growth book. A high rate on both sides means the shape is ordinary for this WPBR book. This comparison was not used to invent a cutoff.</p>
{table([
    ("Recorded column", "text"),
    ("Bad trade rate", "num"), ("Bad trades", "num"), ("Bad symbol rate", "num"),
    ("Other trade rate", "num"), ("Other trades", "num"), ("Other symbol rate", "num"),
], ctx_rows)}
</section>
<section><h2>Frozen symbols</h2>
<p class="muted">Win rate is wins divided by closed trades in the adopted growth book. The last four columns are the middle trade for that symbol.</p>
{table([
    ("Symbol", "text"), ("Trades", "num"), ("Wins", "num"), ("Win rate", "num"),
    ("Median 3y share above SMA200", "num"), ("Median 3y gain", "num"),
    ("Median giveback", "num"), ("Trades with a zone in the 22% band", "text"),
], sym_rows)}
</section>
<section><h2>Freeze</h2><ul>{''.join(f'<li>{esc(line)}</li>' for line in freeze)}</ul></section>
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    html_path = OUT / "compare.html"
    html_path.write_text(page, encoding="utf-8")
    md = [
        "# WPBR bad-performer price structure",
        "",
        "Pivot Break and Retest (WPBR). Description only. No new filter.",
        "",
        "## What you asked",
        "",
        REQUEST_PROMPT.strip(),
        "",
        "## In plain English",
        "",
        LAYMAN,
        "",
        "## What showed up often",
        "",
    ]
    if repeated:
        for o in repeated:
            md.append(f"- {o['label']}: {_fmt_pct(o['pct'])} of trades ({o['hit']}/{o['n']}), {_fmt_pct(o['sp'])} of symbols ({o['sh']}/{o['sn']}).")
    else:
        md.append("- No measured shape cleared 60% of trades and 60% of symbols.")
    md.extend(["", "## Freeze", ""])
    md.extend(f"- {line}" for line in freeze)
    md.extend(["", "## Symbols", ""])
    for pack in packs:
        md.append(f"- {pack['symbol']}: {pack['n']} trades, {pack['wins']} wins, win rate {_fmt_pct(pack['wr'])}.")
    md_path = OUT / "BASELINE.md"
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    sym_path = OUT / "symbols.csv"
    with sym_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["SYMBOL", "TRADES", "WINS", "WIN_RATE_PCT"])
        for pack in packs:
            w.writerow([pack["symbol"], pack["n"], pack["wins"], f"{pack['wr']:.4f}"])
    feat_path = OUT / "trade_structure.csv"
    if feat:
        fields = list(feat[0].keys())
        with feat_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(feat)
    return html_path, md_path


def main() -> int:
    rows = load_closed()
    packs = freeze_symbols(rows)
    print(f"[structure] symbols={len(packs)} trades={sum(p['n'] for p in packs)}", flush=True)
    feat: list[dict[str, Any]] = []
    for pack in packs:
        feat.extend(analyze_symbol(pack))
    bad_syms = {p["symbol"] for p in packs}
    context = _context_rows(rows, bad_syms)
    html_path, md_path = write_page(packs, feat, context)
    print(f"[structure] wrote {html_path}", flush=True)
    _notify([html_path, md_path], f"Bad-performer structure: {len(packs)} symbols, {len(feat)} trades. Description only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
