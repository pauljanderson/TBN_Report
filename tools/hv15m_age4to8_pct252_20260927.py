#!/usr/bin/env python3
"""Research freeze: clean-break zones aged 4–8 sessions, by distance under the 252-day high.

The age and yearly-high columns the user was looking at live on the clean-break
ledger (tools/hv15m_clean_break_n20_signal_ledger_20260927.py):

- Zone rule: highest-volume 15-minute candle that starts before 15:45
  (the 15:45 close is not used; the next-busiest earlier candle is). Not the
  mid-session-only slice, and not the raw set that lets the close win.
- Carry: 20 trading sessions, so ages 4 through 8 can still be active.
- Pattern the user inspected: clean break of the highest zone.
  The same filters are also scored on the other pattern families.

Not gold. Not DailyRun.
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import hv15m_clean_break_n20_signal_ledger_20260927 as led  # noqa: E402
import hv15m_day_zone_forward_20260925 as base  # noqa: E402

STAMP = ROOT / "drive" / "paul_experiments" / "hv15m_age4to8_pct252_20260927"
PARENT_SIGNALS = ROOT / "drive" / "paul_experiments" / "hv15m_day_zone_forward_20260925" / "signals.csv"
HALF_CUT = "2026-08-24"
AGES = (4, 5, 6, 7, 8)
N_CARRY = 20
ZONE_RULE = "ex_last_bar"
PRIMARY = "clean_break_highest"

ORIGINAL_REQUEST = (
    "re:hv15m the bigger pct_below_252d_high_at_signal_close the better and when zone age is "
    "4 , 5,6, 7, or 8 seems to be the sweet spot. can we build this into the system? "
    "i would like to see detailed results with a compare.html and a signals.csv please"
)
MORNING_REQUEST = (
    "Also, when the trigger is between the 9:30 candle and the 11:00 candle are the best. "
    "maybe we ignore anything after that as well."
)
MORNING_TIMES = ("09:30", "09:45", "10:00", "10:15", "10:30", "10:45", "11:00")

BUCKET_ORDER = (
    "above_252d_high",
    "0_to_5",
    "5_to_10",
    "10_to_20",
    "20_plus",
    "missing",
)
BUCKET_LABEL = {
    "above_252d_high": "Already above the 252-day high",
    "0_to_5": "0% to 5% below",
    "5_to_10": "5% to 10% below",
    "10_to_20": "10% to 20% below",
    "20_plus": "20% or more below",
    "missing": "Yearly high missing",
}
FLOOR_CANDIDATES = (
    (0.05, "at least 5% below"),
    (0.10, "at least 10% below"),
    (0.20, "at least 20% below"),
)


def _pct_bucket(p: float) -> str:
    if not np.isfinite(p):
        return "missing"
    if p < 0:
        return "above_252d_high"
    if p < 0.05:
        return "0_to_5"
    if p < 0.10:
        return "5_to_10"
    if p < 0.20:
        return "10_to_20"
    return "20_plus"


# Next-session score is about one trading day. Annualized rate of return (AnnRoR)
# is that simple return times 252. Not compound growth, and not a portfolio equity-curve Ann ROR.
HOLDING_TRADING_DAYS = 1
ANN_ROR_DAYS = 252


def _pct(x, digits=2) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{100.0 * float(x):.{digits}f}%"


def _ann(x, digits=2) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return _pct(float(x) * (ANN_ROR_DAYS / HOLDING_TRADING_DAYS), digits)


def _num(x) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{float(x):.0f}" if float(x) >= 10 else f"{float(x):.2f}"


def attach_252(df: pd.DataFrame) -> pd.DataFrame:
    symbols = sorted(df["symbol"].astype(str).str.upper().unique())
    daily = led.load_daily(symbols)
    pcts = []
    highs = []
    hdates = []
    nused = []
    for rec in df.itertuples(index=False):
        pack = daily.get(str(rec.symbol).upper())
        close = float(rec.signal_close) if rec.signal_close == rec.signal_close else float("nan")
        if not pack or not rec.signal_day:
            pcts.append(np.nan)
            highs.append(np.nan)
            hdates.append("")
            nused.append(0)
            continue
        i = led._prior_index(pack["day"], rec.signal_day)
        hi, hi_date, n = led._window_high(pack["day"], pack["high"], i + 1, led.YEAR_BARS, None)
        if n < led.MIN_YEAR_BARS:
            hi, hi_date = float("nan"), ""
        pcts.append(led._pct_below(hi, close))
        highs.append(hi)
        hdates.append(hi_date)
        nused.append(n)
    out = df.copy()
    out["high_252d"] = highs
    out["high_252d_date"] = hdates
    out["high_252d_lookback_days"] = nused
    out["pct_below_252d_high_at_signal_close"] = pcts
    return out


def _stats(g: pd.DataFrame) -> dict:
    n = int(len(g))
    if n == 0:
        return {"n": 0, "symbols": 0, "days": 0, "win": None, "avg": None, "med": None, "day_avg": None, "exp": None}
    fwd = g["fwd26"].to_numpy(dtype=float)
    by = g.groupby("day")["fwd26"].mean()
    return {
        "n": n,
        "symbols": int(g["symbol"].nunique()),
        "days": int(g["day"].nunique()),
        "win": float((fwd > 0).mean()),
        "avg": float(fwd.mean()),
        "med": float(np.median(fwd)),
        "day_avg": float(by.mean()),
        "exp": float(g["sym_r"].mean()),
    }


def _half(g: pd.DataFrame) -> tuple[dict, dict]:
    return _stats(g[g["day"] < HALF_CUT]), _stats(g[g["day"] >= HALF_CUT])


def choose_floor(age: pd.DataFrame) -> dict | None:
    """In-sample only. Full window of the age 4–8 clean-break book. Later half is not used."""
    usable = age[age["pct_bucket"] != "missing"]
    if usable.empty:
        return None
    means = []
    for key in BUCKET_ORDER:
        if key == "missing":
            continue
        sub = usable[usable["pct_bucket"] == key]
        if len(sub) < 20:
            return None
        means.append(float(sub["fwd26"].mean()))
    # Require a rising gradient, allowing 0.05 percentage points of noise.
    for a, b in zip(means, means[1:]):
        if b + 0.0005 < a:
            return None
    if means[-1] < means[0] + 0.0015:
        return None
    age_avg = float(age["fwd26"].mean())
    for floor, label in FLOOR_CANDIDATES:
        gated = age[age["pct_below_252d_high_at_signal_close"] >= floor]
        below = age[
            age["pct_below_252d_high_at_signal_close"].notna()
            & (age["pct_below_252d_high_at_signal_close"] < floor)
        ]
        if len(gated) < 40 or len(below) < 20:
            continue
        gavg = float(gated["fwd26"].mean())
        bavg = float(below["fwd26"].mean())
        if gavg >= age_avg + 0.001 and gavg > bavg:
            return {"floor": floor, "label": label, "n": int(len(gated)), "avg": gavg, "below_avg": bavg}
    return None


def scan() -> pd.DataFrame:
    cache = base.CACHE if base.CACHE.exists() else led.CACHE
    if not cache.exists():
        raise SystemExit(f"missing 15-minute cache at {cache}")
    print(f"bars {cache}", flush=True)
    bars = pd.read_parquet(cache)
    liquid, info = base.select_universe(bars)
    saved_ns = base.NS
    base.NS = (N_CARRY,)
    rows: list[dict] = []
    try:
        n_sym = 0
        for sym, g in liquid.groupby("symbol", sort=False):
            base.scan_symbol(str(sym), g, rows, zone_rule=ZONE_RULE, emit_baseline=False)
            n_sym += 1
            if n_sym % 100 == 0:
                print(f"  {n_sym} symbols, rows {len(rows):,}", flush=True)
    finally:
        base.NS = saved_ns
    df = pd.DataFrame(rows)
    df = df[df["N"] == N_CARRY].copy()
    print(f"signals {len(df):,}", flush=True)
    df = attach_252(df)
    df["zone_age"] = pd.to_numeric(df["zone_age"], errors="coerce")
    df["pct_bucket"] = [_pct_bucket(float(x) if x == x else float("nan")) for x in df["pct_below_252d_high_at_signal_close"]]
    df["in_age_4_8"] = df["zone_age"].isin(AGES)
    df["morning_gate"] = df["signal_time_et"].astype(str).isin(MORNING_TIMES)
    df["later_half"] = np.where(df["day"].astype(str) >= HALF_CUT, "yes", "no")
    df["zone_rule"] = ZONE_RULE
    info_path = STAMP / "coverage.json"
    STAMP.mkdir(parents=True, exist_ok=True)
    pd.Series(info).to_json(info_path)
    return df


def _arms_label(row) -> str:
    parts = ["unfiltered"]
    if bool(row.in_age_4_8):
        parts.append("age_4_8")
        parts.append(f"age_4_8_pct_{row.pct_bucket}")
        if bool(row.passes_candidate_floor):
            parts.append("age_4_8_plus_floor")
        if bool(row.morning_gate):
            parts.append("age_4_8_morning_0930_1100")
            parts.append(f"age_4_8_morning_pct_{row.pct_bucket}")
    if bool(row.morning_gate):
        parts.append("morning_0930_1100")
    return ";".join(parts)


def write_signals(df: pd.DataFrame, floor: dict | None) -> None:
    out = df.copy()
    floor_v = float(floor["floor"]) if floor else None
    if floor_v is None:
        out["passes_candidate_floor"] = False
    else:
        out["passes_candidate_floor"] = out["in_age_4_8"] & (
            out["pct_below_252d_high_at_signal_close"] >= floor_v
        )
    out["trigger_bar_time_et"] = out["signal_time_et"].astype(str)
    out["morning_gate"] = out["trigger_bar_time_et"].isin(MORNING_TIMES)
    out["AnnRoR"] = pd.to_numeric(out["fwd26"], errors="coerce") * (ANN_ROR_DAYS / HOLDING_TRADING_DAYS)
    out["arms"] = [_arms_label(r) for r in out.itertuples(index=False)]
    cols = [
        "symbol",
        "signal_day",
        "signal_time_et",
        "trigger_bar_time_et",
        "morning_gate",
        "pattern",
        "zone_date",
        "zone_age",
        "zone_lo",
        "zone_hi",
        "signal_close",
        "pct_below_252d_high_at_signal_close",
        "pct_bucket",
        "high_252d",
        "high_252d_date",
        "high_252d_lookback_days",
        "arms",
        "in_age_4_8",
        "passes_candidate_floor",
        "later_half",
        "day",
        "entry",
        "fwd26",
        "AnnRoR",
        "fwd52",
        "sym_r",
        "sym_win",
        "zone_r",
        "zone_win",
        "N",
        "zone_rule",
    ]
    path = STAMP / "signals.csv"
    out[cols].to_csv(path, index=False)
    print(f"wrote {path}", flush=True)


def _row_html(label: str, st: dict, early: dict, late: dict) -> str:
    return (
        "<tr>"
        f"<td>{html.escape(label)}</td>"
        f"<td>{st['n']}</td>"
        f"<td>{st['symbols']}</td>"
        f"<td>{st['days']}</td>"
        f"<td>{_pct(st['win'])}</td>"
        f"<td>{_pct(st['avg'])}</td>"
        f"<td>{_ann(st['avg'])}</td>"
        f"<td>{_pct(st['med'])}</td>"
        f"<td>{_pct(st['day_avg'])}</td>"
        f"<td>{'—' if st['exp'] is None else format(st['exp'], '.3f')}</td>"
        f"<td>{early['n']}</td>"
        f"<td>{_pct(early['avg'])}</td>"
        f"<td>{_ann(early['avg'])}</td>"
        f"<td>{_pct(early['med'])}</td>"
        f"<td>{late['n']}</td>"
        f"<td>{_pct(late['avg'])}</td>"
        f"<td>{_ann(late['avg'])}</td>"
        f"<td>{_pct(late['med'])}</td>"
        "</tr>"
    )


def _th(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{typ}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{html.escape(label)}<span class="sort-ind"></span></th>'
    )


def table_for(pattern: str, df: pd.DataFrame, floor: dict | None) -> str:
    g = df[df["pattern"] == pattern]
    rows = []
    arms = [("Unfiltered (all ages)", g)]
    for age in AGES:
        arms.append((f"Age {age} only", g[g["zone_age"] == age]))
    age = g[g["in_age_4_8"]]
    arms.append(("Age 4–8 pooled", age))
    for key in BUCKET_ORDER:
        arms.append((f"Age 4–8 and {BUCKET_LABEL[key]}", age[age["pct_bucket"] == key]))
    morning = age[age["morning_gate"]]
    arms.append(("Age 4–8 and trigger 09:30–11:00", morning))
    for key in BUCKET_ORDER:
        arms.append((f"Age 4–8, 09:30–11:00, and {BUCKET_LABEL[key]}", morning[morning["pct_bucket"] == key]))
    if floor and pattern == PRIMARY:
        gated = age[age["pct_below_252d_high_at_signal_close"] >= floor["floor"]]
        arms.append((f"Age 4–8 and {floor['label']} (in-sample floor)", gated))
    elif floor:
        gated = age[age["pct_below_252d_high_at_signal_close"] >= floor["floor"]]
        arms.append((f"Age 4–8 and same floor ({floor['label']})", gated))
    for label, sub in arms:
        e, l = _half(sub)
        rows.append(_row_html(label, _stats(sub), e, l))
    return "".join(rows)


def time_table(df: pd.DataFrame) -> str:
    """Age 4–8 clean breaks by the clock time of the trigger candle, morning and later."""
    g = df[(df["pattern"] == PRIMARY) & (df["in_age_4_8"])].copy()
    times = sorted(g["signal_time_et"].dropna().astype(str).unique(), key=lambda t: (int(t[:2]), int(t[3:5])) if len(t) >= 5 else (99, 99))
    rows = []
    for t in times:
        sub = g[g["signal_time_et"].astype(str) == t]
        label = f"{t} trigger" + (" (inside 09:30–11:00)" if t in MORNING_TIMES else " (after 11:00)")
        e, l = _half(sub)
        rows.append(_row_html(label, _stats(sub), e, l))
    after = g[~g["morning_gate"]]
    e, l = _half(after)
    rows.append(_row_html("All triggers after 11:00", _stats(after), e, l))
    morn = g[g["morning_gate"]]
    e, l = _half(morn)
    rows.append(_row_html("All triggers 09:30–11:00", _stats(morn), e, l))
    return "".join(rows)


def load_baseline() -> tuple[dict, dict, dict]:
    if not PARENT_SIGNALS.exists():
        empty = _stats(pd.DataFrame())
        return empty, empty, empty
    b = pd.read_csv(PARENT_SIGNALS)
    b = b[b["pattern"] == "baseline_1030"].copy()
    return _stats(b), *_half(b)


def verdict_text(df: pd.DataFrame, floor: dict | None, base_full: dict) -> tuple[str, str]:
    g = df[df["pattern"] == PRIMARY]
    raw = _stats(g)
    age = g[g["in_age_4_8"]]
    aged = _stats(age)
    raw_e, raw_l = _half(g)
    age_e, age_l = _half(age)
    age_helps = (
        aged["n"] >= 80
        and aged["avg"] is not None
        and raw["avg"] is not None
        and aged["avg"] > raw["avg"] + 0.001
        and aged["med"] is not None
        and raw["med"] is not None
        and aged["med"] > raw["med"]
    )
    late_ok = (
        age_l["n"] >= 30
        and age_l["avg"] is not None
        and raw_l["avg"] is not None
        and age_l["avg"] >= raw_l["avg"] - 0.001
        and (age_l["med"] is None or raw_l["med"] is None or age_l["med"] >= raw_l["med"] - 0.001)
    )
    if age_helps and late_ok:
        age_line = (
            f"Age 4–8 does help the clean break on this window: average {_pct(aged['avg'])} on {aged['n']} signals "
            f"versus unfiltered {_pct(raw['avg'])} on {raw['n']}, and the later half does not give the gain back "
            f"(later age 4–8 {_pct(age_l['avg'])} on {age_l['n']} versus later unfiltered {_pct(raw_l['avg'])}). "
            "That is still a short 2026 window. It is a research note, not a DailyRun rule."
        )
    elif age_helps and not late_ok:
        age_line = (
            f"Age 4–8 looks better on the pooled clean-break book ({_pct(aged['avg'])} on {aged['n']} versus "
            f"unfiltered {_pct(raw['avg'])} on {raw['n']}), but the later half does not confirm it "
            f"(later age 4–8 {_pct(age_l['avg'])} on {age_l['n']}, median {_pct(age_l['med'])}; "
            f"later unfiltered {_pct(raw_l['avg'])}). Do not freeze the age filter for trading."
        )
    else:
        age_line = (
            f"Age 4–8 does not clearly help the clean break. Unfiltered average {_pct(raw['avg'])} on {raw['n']} signals, "
            f"median {_pct(raw['med'])}. Age 4–8 average {_pct(aged['avg'])} on {aged['n']}, median {_pct(aged['med'])}. "
            f"Before {HALF_CUT}: unfiltered {_pct(raw_e['avg'])} ({raw_e['n']}), age 4–8 {_pct(age_e['avg'])} ({age_e['n']}). "
            f"On or after {HALF_CUT}: unfiltered {_pct(raw_l['avg'])} ({raw_l['n']}), age 4–8 {_pct(age_l['avg'])} ({age_l['n']})."
        )

    bits = []
    for key in BUCKET_ORDER:
        if key == "missing":
            continue
        sub = age[age["pct_bucket"] == key]
        st = _stats(sub)
        bits.append(f"{BUCKET_LABEL[key]}: {_pct(st['avg'])} on {st['n']} signals (median {_pct(st['med'])})")
    bucket_line = "Inside age 4–8, distance under the 252-day high: " + "; ".join(bits) + "."
    if floor:
        gated = age[age["pct_below_252d_high_at_signal_close"] >= floor["floor"]]
        ge, gl = _half(gated)
        gst = _stats(gated)
        floor_line = (
            f"An in-sample floor of {floor['label']} clears the age 4–8 book on the full window "
            f"({_pct(gst['avg'])} on {gst['n']} versus age-only {_pct(aged['avg'])} on {aged['n']}; "
            f"the part under the floor averaged {_pct(floor['below_avg'])}). "
            f"Later half of the gated book: {_pct(gl['avg'])} on {gl['n']} signals, median {_pct(gl['med'])}. "
            "The floor was chosen on this same short window, not on a holdout. Do not treat it as tuned."
        )
        follow = (
            "Worth a follow-up only as a labeled research slice if a longer tape still shows both the age band "
            "and the deeper-below-the-high lift. No freeze for trading, and not DailyRun."
        )
    else:
        floor_line = (
            "No single 252-day-high floor is adopted. The buckets are not a clean rising staircase with enough "
            "trades in each step, so picking a cutoff would be squeezing this short sample."
        )
        follow = "Nothing here is worth wiring. A longer history would be the follow-up, not a tighter cutoff on these nine weeks."
    morn = age[age["morning_gate"]] if "morning_gate" in age.columns else age.iloc[0:0]
    after = age[~age["morning_gate"]] if "morning_gate" in age.columns else age.iloc[0:0]
    ms, mf = _stats(morn), _stats(after)
    me, ml = _half(morn)
    morning_line = (
        f"Inside age 4–8, a trigger from the 09:30 candle through the 11:00 candle (11:00 included) "
        f"averages {_pct(ms['avg'])} on {ms['n']} signals, median {_pct(ms['med'])}. "
        f"Triggers after 11:00 average {_pct(mf['avg'])} on {mf['n']}. "
        f"Before {HALF_CUT} the morning slice is {_pct(me['avg'])} on {me['n']}; "
        f"on or after {HALF_CUT} it is {_pct(ml['avg'])} on {ml['n']}, median {_pct(ml['med'])}."
    )
    vs_base = (
        f"A plain 10:30 buy, no zone, averaged {_pct(base_full['avg'])} on {base_full['n']} signals over the same names and dates."
    )
    body = " ".join([age_line, bucket_line, morning_line, floor_line, vs_base, follow])
    if age_helps and late_ok:
        recommend = "research follow-up on age 4–8 only; not a trading freeze and not DailyRun"
    else:
        recommend = "no trading freeze"
    return body, recommend


def write_reports(df: pd.DataFrame, floor: dict | None) -> None:
    base_f, base_e, base_l = load_baseline()
    prose, recommend = verdict_text(df, floor, base_f)
    primary_rows = table_for(PRIMARY, df, floor)
    other = []
    for pattern in base.PATTERN_ORDER:
        if pattern in (PRIMARY, "baseline_1030"):
            continue
        other.append(
            f"<h3>{html.escape(base.PATTERN_LABEL[pattern])}</h3>"
            f"<table class=\"sortable\"><caption>Same age and yearly-high filters, for comparison. Not the book the age observation came from.</caption>"
            f"<thead><tr>{header_html()}</tr></thead><tbody>{table_for(pattern, df, floor)}</tbody></table>"
        )
    floor_say = (
        f"In-sample candidate floor: {floor['label']}. Chosen only because, on the full age 4–8 clean-break window, "
        f"deeper buckets were higher and this floor lifted the average without using the later half."
        if floor
        else "No candidate floor. The yearly-high buckets are shown, and none is adopted."
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>15-minute zone age 4–8 and distance under the yearly high</title>
<style>
body {{ font-family: system-ui, Segoe UI, sans-serif; margin: 24px auto; max-width: 1200px; padding: 0 16px 48px; color: #0f172a; line-height: 1.45; }}
h1 {{ font-size: 1.45rem; }}
h2 {{ font-size: 1.15rem; margin-top: 1.6rem; }}
.callout {{ background: #f8fafc; border-left: 4px solid #2563eb; padding: 12px 16px; margin: 12px 0 16px; }}
.callout.plain {{ border-left-color: #059669; }}
.note {{ color: #334155; font-size: 0.95rem; }}
table.sortable {{ border-collapse: collapse; width: 100%; font-size: 0.86rem; margin: 8px 0 18px; }}
th, td {{ border-bottom: 1px solid #e2e8f0; text-align: right; padding: 8px; }}
th:first-child, td:first-child {{ text-align: left; }}
caption {{ text-align: left; font-weight: 600; margin: 6px 0; }}
th.sortable-th {{ cursor: pointer; user-select: none; white-space: nowrap; }}
th.sortable-th:hover {{ background: #e2e8f0; }}
th.sortable-th .sort-ind::after {{ content: " \\2195"; opacity: .35; }}
th.sortable-th.sort-asc .sort-ind::after {{ content: " \\2191"; opacity: .9; }}
th.sortable-th.sort-desc .sort-ind::after {{ content: " \\2193"; opacity: .9; }}
</style>
</head>
<body>
<h1>Zone age 4–8 and distance under the 252-day high</h1>
<p class="note">Research only. Not gold. Not wired into DailyRun. Not the daily Volume Zone (VZ) system. Window about 2026-07-23 to 2026-09-24. Caution split {HALF_CUT} is inside this window, not a 2024 holdout.</p>
<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
<p>{html.escape(ORIGINAL_REQUEST)}</p>
<p>{html.escape(MORNING_REQUEST)}</p>
</div>
<div class="callout plain">
<h2 style="margin-top:0">In plain English</h2>
<p>You looked at the clean-break list and saw two things: older-but-not-stale zones (4 to 8 trading days old) seemed better, and trades further under the stock’s high of the past year seemed better. You also think the trigger works best from the 9:30 candle through the 11:00 candle, and that later triggers can be ignored. This page keeps that clean-break book and asks whether those filters actually improve the next session, compared with the same buys with no filter. The other patterns get the same filters so a clean-break fluke is easy to spot.</p>
<p>The zone is still the low-to-high of the day’s busiest 15-minute candle, excluding the 15:45 close (if the close is busiest, the next-busiest earlier candle is used). That zone may stay on the chart for 20 trading days. A buy is the next 15-minute open after a clean break of the highest such zone. “Age” is how many trading sessions have passed since the zone’s own day. Age 4 means the fourth session after the day it was born. The yearly-high figure is how far the signal candle’s close sits under the highest daily high of the prior 252 trading days, not counting the signal day. A bigger number means further below that high. A negative number means the close is already above it. The morning gate keeps a trigger only when that 15-minute candle starts at 9:30, 9:45, 10:00, 10:15, 10:30, 10:45, or 11:00 Eastern. The 11:00 candle is included. A trigger that starts at 11:15 or later is dropped.</p>
<p>Annualized rate of return (AnnRoR) was added beside every average next-session return, and as a column on signals.csv. It is that one-day return multiplied by 252. It is a simple scaling of the same one-day move, not compound growth and not a yearly portfolio return. A large AnnRoR does not change the verdict.</p>
</div>
<h2>Verdict</h2>
<p>{html.escape(prose)}</p>
<p>{html.escape(floor_say)} Recommendation tag: <strong>{html.escape(recommend)}</strong>.</p>
<p class="note">Click column headers to sort. The return is from the buy to the close 26 fifteen-minute bars later (about one regular session). The later half is buys on or after {HALF_CUT}. The 10:30 buy with no zone, from the prior study: average {_pct(base_f['avg'])}, before {HALF_CUT} {_pct(base_e['avg'])}, on or after {_pct(base_l['avg'])}.</p>
<h2>Clean break of the highest zone</h2>
<p class="note">This is the pattern family the age and yearly-high note came from. Carry is 20 trading sessions. Zone source: exclude the 15:45 bar.</p>
<table class="sortable">
<caption>Unfiltered versus age, then age 4–8 split by distance under the 252-day high.</caption>
<thead><tr>{header_html()}</tr></thead>
<tbody>
{primary_rows}
</tbody>
</table>
<h2>Trigger clock time inside age 4–8</h2>
<p>Each row is one start time of the trigger candle, still limited to zones that are 4 to 8 trading days old. Times through 11:00 are the morning gate. Later times are the ones the gate would drop. The last two rows pool those groups.</p>
<table class="sortable">
<caption>Does 9:30 through 11:00 beat later triggers, inside the age 4–8 clean-break book?</caption>
<thead><tr>{header_html()}</tr></thead>
<tbody>
{time_table(df)}
</tbody>
</table>
<h2>Same filters on the other patterns</h2>
<p class="note">Same zone rule and same 20-session carry. These were not the list where the age note was made.</p>
{"".join(other)}
</body>
<script>
(function () {{
  function parseSortValue(text, type) {{
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : NaN;
    if (type === "text") return s.toUpperCase();
    var n = s.replace(/[$,%+]/g, "").replace(/,/g, "");
    var v = parseFloat(n);
    return Number.isFinite(v) ? v : NaN;
  }}
  function sortTable(table, col, type, dir) {{
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll("tr"));
    rows.sort(function (a, b) {{
      var av = parseSortValue(a.cells[col] ? a.cells[col].textContent : "", type);
      var bv = parseSortValue(b.cells[col] ? b.cells[col].textContent : "", type);
      var aMiss = typeof av === "number" && !Number.isFinite(av);
      var bMiss = typeof bv === "number" && !Number.isFinite(bv);
      if (aMiss && bMiss) return 0;
      if (aMiss) return 1;
      if (bMiss) return -1;
      if (typeof av === "string" || typeof bv === "string") return dir * String(av).localeCompare(String(bv));
      return dir * (av - bv);
    }});
    rows.forEach(function (r) {{ tbody.appendChild(r); }});
  }}
  document.querySelectorAll("table.sortable").forEach(function (table) {{
    var headers = table.querySelectorAll("th.sortable-th");
    headers.forEach(function (th, col) {{
      function activate(ev) {{
        if (ev.type === "keydown" && ev.key !== "Enter" && ev.key !== " ") return;
        if (ev.type === "keydown") ev.preventDefault();
        var type = th.getAttribute("data-sort") || "text";
        var dir = th.classList.contains("sort-asc") ? -1 : 1;
        headers.forEach(function (h) {{ h.classList.remove("sort-asc", "sort-desc"); h.setAttribute("aria-sort", "none"); }});
        th.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
        th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
        sortTable(table, col, type, dir);
      }}
      th.addEventListener("click", activate);
      th.addEventListener("keydown", activate);
    }});
  }});
}})();
</script>
</html>
"""
    (STAMP / "compare.html").write_text(page, encoding="utf-8")
    g = df[df["pattern"] == PRIMARY]
    raw, aged = _stats(g), _stats(g[g["in_age_4_8"]])
    baseline_md = f"""# Research baseline — zone age 4–8 and distance under the 252-day high

Study id: `hv15m_age4to8_pct252_20260927`

Not gold. Not DailyRun. Not the daily Volume Zone (VZ) system.

## What you asked

> {ORIGINAL_REQUEST}

> {MORNING_REQUEST}

## In plain English

The clean-break list suggested three filters: keep a zone only when it is 4, 5, 6, 7, or 8 trading days old, prefer names whose signal close is further under the high of the past year, and keep the trigger only when its 15-minute candle starts from 9:30 through 11:00 Eastern (11:00 included). This stamp tests those filters on that same clean-break book, and shows the same filters on the other patterns so the compare is honest. Annualized rate of return (AnnRoR) is the next-session return multiplied by 252. It scales that one-day move. It is not a yearly portfolio return, and it does not change the verdict.

## Book

- Pattern the observation came from: **clean break of the highest zone**. A whole 15-minute bar sits above that zone’s high, the prior close did not, and it is the first time for that zone. Fill is the next 15-minute open.
- Zone: low to high of the day’s busiest 15-minute candle **before 15:45**. If the 15:45 bar has the most volume, it is not the zone; the busiest earlier candle is. This is not the mid-session-only slice (which drops the day when the open or the close wins) and not the raw set that lets the close win.
- Carry: **20 trading sessions**. Ages 6–8 would be impossible on a 5-session carry.
- Zone age: trading sessions since the zone’s birth day. Age 0 is later the same day. Age 4 is the fourth session after the birth session. The sweet spot asked for ages **exactly 4, 5, 6, 7, or 8**, reported one age at a time and pooled.
- Morning gate: the trigger 15-minute candle starts at 09:30, 09:45, 10:00, 10:15, 10:30, 10:45, or 11:00 US/Eastern. The 11:00 bar is included. A start of 11:15 or later fails the gate.
- `pct_below_252d_high_at_signal_close`: (highest daily high of the prior 252 trading days, strictly before the signal date, minus the signal candle’s close) divided by that high. Same formula as the clean-break ledger. A missing value means fewer than 20 daily bars before the signal. Bigger means further below the high.
- Date range: the same 15-minute store as the parent study, about 2026-07-23 through 2026-09-24. There is no pre-2024 history, so no 2024 in-sample / out-of-sample split is invented. Caution split: entry date before {HALF_CUT} versus on or after {HALF_CUT}. The later half is report-only. It is not used to pick a floor.
- Score: average and median move over the next 26 fifteen-minute bars, win rate (close up), and the same +1% before −1% path as the parent study. The no-zone comparison is the parent study’s 10:30 buy.
- Annualized rate of return (AnnRoR): next-session return times 252, because that window is about one trading day. On signals.csv the column is the same multiple of `fwd26`. On the tables it is that average, printed as a percent. Not compound growth. Not a portfolio equity-curve annualized rate of return. A large number is the one-day edge scaled by 252.

## Arms

1. Unfiltered clean break, carry 20, same zone rule.
2. Age 4, 5, 6, 7, and 8 separately, and pooled 4–8. This is the one-change age test.
3. Inside age 4–8 only, buckets of distance under the 252-day high: already above it, 0–5%, 5–10%, 10–20%, 20%+.
4. {floor_say}

## Headline (clean break)

- Unfiltered: {raw['n']} signals, average {_pct(raw['avg'])}, median {_pct(raw['med'])}.
- Age 4–8: {aged['n']} signals, average {_pct(aged['avg'])}, median {_pct(aged['med'])}.

## What we did not claim

Not a portfolio. Not gold. Not DailyRun. The floor, if any, is in-sample selection on this short window.
"""
    (STAMP / "BASELINE.md").write_text(baseline_md, encoding="utf-8")
    summary = f"""# Summary — zone age 4–8 and the 252-day high

## What you asked

> {ORIGINAL_REQUEST}

> {MORNING_REQUEST}

## In plain English

We kept the clean-break book (busiest 15-minute candle before the close, zone carried 20 trading days) and tested ages 4 through 8, a larger gap under the past year’s high, and a trigger only from the 9:30 candle through the 11:00 candle. Annualized rate of return (AnnRoR) on the table and in signals.csv is the next-session return multiplied by 252. It scales that one-day move. It is not a yearly portfolio return, and it does not change the verdict.

## Verdict

{prose}

Recommendation: {recommend}.

Unfiltered clean break: {raw['n']} signals, average {_pct(raw['avg'])}. Age 4–8: {aged['n']} signals, average {_pct(aged['avg'])}.

Full table: compare.html. One row per signal: signals.csv.
"""
    (STAMP / "SUMMARY.md").write_text(summary, encoding="utf-8")
    print(f"wrote {STAMP / 'compare.html'}", flush=True)


def header_html() -> str:
    return "".join(
        [
            _th("Slice", "text"),
            _th("Signals", "num"),
            _th("Symbols", "num"),
            _th("Days", "num"),
            _th("Win %", "num"),
            _th("Avg 26-bar", "num"),
            _th("AnnRoR", "num"),
            _th("Median", "num"),
            _th("Day-avg", "num"),
            _th("+1% expectancy", "num"),
            _th("Early n", "num"),
            _th("Early avg", "num"),
            _th("Early AnnRoR", "num"),
            _th("Early median", "num"),
            _th("Late n", "num"),
            _th("Late avg", "num"),
            _th("Late AnnRoR", "num"),
            _th("Late median", "num"),
        ]
    )


def load_scanned() -> pd.DataFrame:
    path = STAMP / "signals.csv"
    if path.exists() and "--rescan" not in sys.argv:
        print(f"reusing {path}", flush=True)
        df = pd.read_csv(path)
        df["zone_age"] = pd.to_numeric(df["zone_age"], errors="coerce")
        df["in_age_4_8"] = df["zone_age"].isin(AGES)
        if "pct_bucket" not in df.columns:
            df["pct_bucket"] = [
                _pct_bucket(float(x) if x == x else float("nan"))
                for x in df["pct_below_252d_high_at_signal_close"]
            ]
        df["morning_gate"] = df["signal_time_et"].astype(str).isin(MORNING_TIMES)
        df["later_half"] = np.where(df["day"].astype(str) >= HALF_CUT, "yes", "no")
        return df
    return scan()


def main() -> int:
    STAMP.mkdir(parents=True, exist_ok=True)
    df = load_scanned()
    primary_age = df[(df["pattern"] == PRIMARY) & (df["in_age_4_8"])]
    floor = choose_floor(primary_age)
    print("floor", floor, flush=True)
    write_signals(df, floor)
    write_reports(df, floor)
    g = df[df["pattern"] == PRIMARY]
    print("--- clean break ---", flush=True)
    print("unfiltered", _stats(g), flush=True)
    print("age48", _stats(g[g["in_age_4_8"]]), flush=True)
    age = g[g["in_age_4_8"]]
    for key in BUCKET_ORDER:
        print(key, _stats(age[age["pct_bucket"] == key]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
