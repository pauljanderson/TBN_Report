#!/usr/bin/env python3
"""RSI-only high-water stop: keep 40/50/60/70/80% of the gain vs the current RSI exit.

Research only. Does not edit the all-system stamp, DailyRun, or the live watch.
Does not retune on out-of-sample.
"""
from __future__ import annotations

import html as html_mod
import json
import math
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
_PE = _REPO / "drive" / "paul_experiments"
_TOOLS = _REPO / "tools"
for _p in (_PE, _TOOLS, _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import hwm_stop_keep_40_50_60_20261015 as hwm  # noqa: E402
from compare_format import format_money, is_excluded_html_compare_label  # noqa: E402
from report_page_extras import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, SWIPE_NOTE_HTML  # noqa: E402

# Same overlay math as the all-system test, plus the next two keep fractions.
KS = (0.40, 0.50, 0.60, 0.70, 0.80)
hwm.KS = KS

STAMP = "rsi_hwm_stop_70_80_20261015"
OUT = _PE / STAMP
ARMS = ("control", "k40", "k50", "k60", "k70", "k80")
KEEP_ARMS = ("k40", "k50", "k60", "k70", "k80")
ARM_LABEL = {
    "control": "Control",
    "k40": "Keep 40%",
    "k50": "Keep 50%",
    "k60": "Keep 60%",
    "k70": "Keep 70%",
    "k80": "Keep 80%",
}
ARM_K = {"k40": 0.40, "k50": 0.50, "k60": 0.60, "k70": 0.70, "k80": 0.80}

ASK = (
    "thanks. i like the results for RSI. this makes sense, we are jumping on stocks "
    "that are rising, and once they start coming back, we should get out. "
    "60% > 50% > 40%. let's compare this one system to 70% and 80%. "
    "no need to show the keep N numbers as they always match the control N."
)

PLAIN = (
    "This page is only the Relative Strength Index (RSI) system. RSI already has a "
    "finished list of closed trades and its own way of getting out. That current exit "
    "is the control and is left unchanged. The new idea watches the highest daily high "
    "after the buy (the high-water mark) and lifts the stop so it keeps part of that "
    "gain. Keep 40% puts the stop at 40% of the rise from the buy to that high. "
    "Keep 50%, 60%, 70%, and 80% keep a larger share, so the stop sits closer to the "
    "high and you give back less of the gain before getting out. Example: buy at $100, "
    "later daily high $110 (up 10%). Keep 50% stops at $105. Keep 70% stops at $107. "
    "Keep 80% stops at $108. Today's stop uses only highs through yesterday. If the "
    "open is already through the stop, the sell is at the open. If the low tags the "
    "stop, the sell is at the stop. If that stop never hits, the original exit still "
    "stands. The new stop is used only when it is tighter than RSI's original stop. "
    "This is not Rocket Launcher's partial exit (sell most at +20%, rest at entry or +40%). "
    "Trade count is the same on every arm, so N is shown once for the whole slice."
)


def load_ohlc_csv(symbols: set[str]):
    """Warehouse source files. Used when data/ohlcv.duckdb is locked by another job."""
    root = _REPO / "data" / "newdata" / "data"
    out = {}
    missing = []
    for sym in sorted(symbols):
        path = root / f"{sym}.csv"
        if not path.exists():
            missing.append(sym)
            continue
        raw = pd.read_csv(path, usecols=["Date", "Open", "High", "Low"])
        dt = pd.to_datetime(raw["Date"], errors="coerce")
        ymd = (dt.dt.year * 10000 + dt.dt.month * 100 + dt.dt.day).astype("int64")
        ok = dt.notna()
        g = raw.loc[ok].copy()
        g["ymd"] = ymd[ok].to_numpy()
        g = g.sort_values("ymd")
        out[sym] = (
            g["ymd"].to_numpy(dtype=np.int64),
            g["Open"].to_numpy(dtype=np.float64),
            g["High"].to_numpy(dtype=np.float64),
            g["Low"].to_numpy(dtype=np.float64),
        )
    return out, missing


def load_ohlc(symbols: set[str]):
    try:
        bars = hwm.load_ohlc(symbols)
        return bars, "data/ohlcv.duckdb prices", []
    except Exception as exc:
        print(f"duckdb locked or unreadable ({exc}); reading data/newdata/data CSV", flush=True)
        bars, missing = load_ohlc_csv(symbols)
        return bars, "data/newdata/data CSV (same warehouse source; duckdb was locked)", missing


def build_rows(df, ohlc, dollars):
    stats = Counter()
    rows = {a: [] for a in ARMS}
    symbols = df["symbol"].to_numpy()
    opened = df["opened"].to_numpy(dtype=np.int64)
    closed = df["closed"].to_numpy(dtype=np.int64)
    entry = df["entry"].to_numpy(dtype=float)
    pnl = df["pnl"].to_numpy(dtype=float)
    days = df["days"].to_numpy(dtype=float)
    stop = df["stop"].to_numpy(dtype=float)
    exit_type = df["exit_type"].astype(str).to_numpy()
    industry = df["industry"].astype(str).to_numpy()
    side = df["side"].astype(str).to_numpy()
    for i in range(len(df)):
        sym = str(symbols[i])
        op_i = int(opened[i])
        cl_i = int(closed[i])
        en = float(entry[i])
        book_pnl = float(pnl[i])
        book_d = float(dollars[i])
        book_days = (
            float(days[i])
            if days[i] == days[i] and days[i] > 0
            else hwm._calendar_days(op_i, cl_i, float("nan"))
        )
        notion = abs(book_d) / (abs(book_pnl) / 100.0) if abs(book_pnl) > 1e-6 else float("nan")
        if not (notion == notion and notion > 0):
            notion = abs(book_d) if book_pnl == 0 else float("nan")
        side_i = str(side[i])
        if side_i not in {"LONG", "L", "", "NAN"}:
            stats["short_skipped"] += 1
            continue
        replay = hwm.replay_trade(ohlc.get(sym), op_i, cl_i, en, float(stop[i]))
        if replay == "missing":
            stats["missing_ohlc"] += 1
            continue
        assert isinstance(replay, dict)
        base = {
            "symbol": sym,
            "opened": hwm._ymd_to_date(op_i),
            "closed": hwm._ymd_to_date(cl_i),
            "pnl": book_pnl,
            "pnl_d": book_d,
            "days": book_days,
            "exit_type": exit_type[i] or "UNKNOWN",
            "industry": industry[i],
        }
        rows["control"].append(base)
        stats["kept"] += 1
        for arm, k in ARM_K.items():
            hit = replay.get(k)
            if hit is None:
                rows[arm].append(dict(base))
                continue
            exit_ymd, exit_px, tag = hit
            new_pnl = (exit_px - en) / en * 100.0
            new_d = notion * new_pnl / 100.0 if notion == notion and notion > 0 else book_d
            rows[arm].append(
                {
                    "symbol": sym,
                    "opened": hwm._ymd_to_date(op_i),
                    "closed": hwm._ymd_to_date(exit_ymd),
                    "pnl": new_pnl,
                    "pnl_d": new_d,
                    "days": hwm._calendar_days(op_i, exit_ymd, book_days),
                    "exit_type": tag,
                    "industry": industry[i],
                }
            )
            stats[f"hit_{arm}"] += 1
    return rows, dict(stats)


def _finite(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def beats_control(m: dict, c: dict) -> bool:
    need = ("ann_ror", "avg_pnl_pct", "win_pct")
    if any(_finite(m.get(k)) is None or _finite(c.get(k)) is None for k in need):
        return False
    if _finite(m["ann_ror"]) <= _finite(c["ann_ror"]):
        return False
    if _finite(m["avg_pnl_pct"]) <= _finite(c["avg_pnl_pct"]):
        return False
    if _finite(m["win_pct"]) < _finite(c["win_pct"]) - 1.0:
        return False
    pf_m, pf_c = _finite(m.get("profit_factor")), _finite(c.get("profit_factor"))
    if pf_m is not None and pf_c is not None and pf_m < pf_c - 1e-9:
        return False
    dd_m, dd_c = _finite(m.get("max_dd")), _finite(c.get("max_dd"))
    if dd_m is not None and dd_c is not None and dd_m > dd_c + 2.0:
        return False
    return True


def beats_60(m: dict, k60: dict) -> str:
    """better / flat / worse versus the 60% arm on in-sample quality."""
    a_ann, b_ann = _finite(m.get("ann_ror")), _finite(k60.get("ann_ror"))
    a_avg, b_avg = _finite(m.get("avg_pnl_pct")), _finite(k60.get("avg_pnl_pct"))
    if None in (a_ann, b_ann, a_avg, b_avg):
        return "unscored"
    if abs(a_ann - b_ann) < 0.25 and abs(a_avg - b_avg) < 0.05:
        return "flat"
    # Quality: both average return and annualized rate of return have to improve.
    # A higher annualized rate from a shorter hold with a lower average return is not a win.
    if a_ann > b_ann and a_avg > b_avg:
        wr_m, wr_60 = _finite(m.get("win_pct")), _finite(k60.get("win_pct"))
        if wr_m is not None and wr_60 is not None and wr_m < wr_60 - 1.0:
            return "worse"
        return "better"
    return "worse"


def judge(slices: dict) -> dict[str, str]:
    is_map = slices["IS"]
    ctrl = is_map["control"]
    k60 = is_map["k60"]
    vs60 = {arm: beats_60(is_map[arm], k60) for arm in ("k70", "k80")}
    def _pair(arm: str) -> str:
        m = is_map[arm]
        return (
            f"{ARM_LABEL[arm]} win rate {_finite(m.get('win_pct')):.2f}%, "
            f"average return {_finite(m.get('avg_pnl_pct')):.2f}%, "
            f"annualized rate of return {_finite(m.get('ann_ror')):.2f}%"
        )

    better = [ARM_LABEL[a] for a, tag in vs60.items() if tag == "better"]
    k60_txt = _pair("k60")
    if better:
        lead = (
            "On the in-sample book, "
            + " and ".join(better)
            + " beat keep 60% on both average return and annualized rate of return "
            "(win rate did not drop by more than 1 point). "
            + k60_txt
            + ". "
            + _pair("k70")
            + ". "
            + _pair("k80")
            + "."
        )
    else:
        lead = (
            "On the in-sample book, the 60% result still leads. "
            "Keep 70% and keep 80% do not beat 60% on quality: average return is lower than 60% "
            f"({_finite(k60.get('avg_pnl_pct')):.2f}% at 60%, "
            f"{_finite(is_map['k70'].get('avg_pnl_pct')):.2f}% at 70%, "
            f"{_finite(is_map['k80'].get('avg_pnl_pct')):.2f}% at 80%) "
            "even though the annualized rate of return is higher, because the tighter stop shortens the hold. "
            "That higher annualized rate is not treated as a win over 60%. "
            "Out-of-sample is not used to pick 70% or 80%."
        )
    passers = [a for a in KEEP_ARMS if beats_control(is_map[a], ctrl)]
    if not ctrl.get("n"):
        verdict, why = "NO IS", "No in-sample trades."
    elif not passers:
        verdict = "DISMISS"
        why = "No keep fraction beat RSI control on in-sample quality. " + lead
    else:
        def ann_key(arm: str) -> float:
            v = _finite(is_map[arm].get("ann_ror"))
            return v if v is not None else -1e18

        is_best = max(passers, key=ann_key)
        verdict = "LEAN KEEP"
        why = (
            f"In-sample quality versus control still favors {ARM_LABEL[is_best]} "
            "among the fractions that beat control. "
            + lead
            + " This horse race is in-sample selection: 40/50/60 were already seen, and 70/80 are the next step on the same RSI book."
        )
        oos_c, oos_b = slices["OOS"]["control"], slices["OOS"][is_best]
        soft = []
        if _finite(oos_b.get("ann_ror")) is not None and _finite(oos_c.get("ann_ror")) is not None:
            if _finite(oos_b["ann_ror"]) < _finite(oos_c["ann_ror"]):
                soft.append("out-of-sample annualized rate of return is below control")
        if _finite(oos_b.get("avg_pnl_pct")) is not None and _finite(oos_c.get("avg_pnl_pct")) is not None:
            if _finite(oos_b["avg_pnl_pct"]) < _finite(oos_c["avg_pnl_pct"]):
                soft.append("out-of-sample average return is below control")
        if soft:
            verdict = "HOLD"
            why += " Out-of-sample softened (" + "; ".join(soft) + "). HOLD. The keep fraction was not changed to chase out-of-sample."
        else:
            why += " Out-of-sample did not soften versus control on those two. Still research only, not gold."
    return {"verdict": verdict, "line": why, "vs60": vs60}


def _fmt(v: Any, kind: str) -> str:
    return hwm._fmt_cell(v, kind)


def _delta_cell(dlt: Optional[float], kind: str) -> str:
    if dlt is None:
        return "<td>—</td>"
    if kind == "money":
        shown = format_money(dlt)
        if dlt > 0:
            shown = "+" + shown
        return f"<td>{html_mod.escape(shown)}</td>"
    return f"<td>{_fmt(dlt, kind if kind != 'int' else 'num')}</td>"


def render(res: dict) -> str:
    def headline(mode: str, title: str) -> str:
        n = res["slices"][mode]["control"]["n"]
        heads = "".join(
            [
                hwm._th("Arm", "text"),
                hwm._th("Win rate", "num"),
                hwm._th("Avg return", "num"),
                hwm._th("Ann ROR", "num"),
            ]
        )
        body = []
        for arm in ARMS:
            m = res["slices"][mode][arm]
            body.append(
                "<tr>"
                f"<td>{html_mod.escape(ARM_LABEL[arm])}</td>"
                f"<td>{_fmt(m['win_pct'], 'pct')}</td>"
                f"<td>{_fmt(m['avg_pnl_pct'], 'pct')}</td>"
                f"<td>{_fmt(m['ann_ror'], 'pct')}</td>"
                "</tr>"
            )
        return (
            f"<h2>{html_mod.escape(title)}</h2>\n"
            f"<p>N = {int(n):,} on every arm (control and each keep fraction). "
            "Keep-fraction N is omitted because it matches the control.</p>\n"
            f"{SWIPE_NOTE_HTML}\n<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>{heads}</tr></thead><tbody>"
            + "".join(body)
            + "</tbody></table></div>"
        )

    def canon(mode: str) -> str:
        n = res["slices"][mode]["control"]["n"]
        heads = [hwm._th("Metric", "text"), hwm._th("Control", "num")]
        for arm in KEEP_ARMS:
            heads.append(hwm._th(ARM_LABEL[arm], "num"))
            heads.append(hwm._th(f"Δ {ARM_LABEL[arm]}", "num"))
        body = []
        for label, key, _typ, kind in hwm.METRIC_SPEC:
            if key == "n" or is_excluded_html_compare_label(label):
                continue
            cval = res["slices"][mode]["control"].get(key)
            cells = [
                f"<td>{html_mod.escape(label)}</td>",
                f"<td>{_fmt(cval, kind)}</td>",
            ]
            for arm in KEEP_ARMS:
                aval = res["slices"][mode][arm].get(key)
                cells.append(f"<td>{_fmt(aval, kind)}</td>")
                cells.append(_delta_cell(hwm._delta(aval, cval), kind))
            body.append("<tr>" + "".join(cells) + "</tr>")
        return (
            f"<h2>Canonical compare — {html_mod.escape(mode)}</h2>\n"
            f"<p>N = {int(n):,} once for this slice. Absolute values and the change versus the RSI control. "
            "Annualized rate of return uses <code>compare_format.ann_ror_from_closed</code>. "
            "Max drawdown and Sharpe use exit-date equity seeded at $500,000 "
            "(no daily equity curve on the overlay). "
            "Profit concentration is blank when total profit is not positive. "
            "Days underwater, open-position counts, aggressive paths, and Paul / FIT scores "
            "are not recomputed: this test does not rebuild a daily portfolio or a Summary file.</p>\n"
            f"{SWIPE_NOTE_HTML}\n<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>"
            + "".join(heads)
            + "</tr></thead><tbody>"
            + "".join(body)
            + "</tbody></table></div>"
        )

    j = res["judge"]
    exit_rows = []
    for mode in ("FULL", "IS", "OOS"):
        for arm in ARMS:
            mix = res["slices"][mode][arm].get("exit_mix") or {}
            n = res["slices"][mode][arm]["n"] or 0
            for xt, cnt in sorted(mix.items(), key=lambda kv: (-kv[1], kv[0])):
                pct = (100.0 * cnt / n) if n else None
                exit_rows.append(
                    "<tr>"
                    f"<td>{html_mod.escape(ARM_LABEL[arm])}</td>"
                    f"<td>{mode}</td>"
                    f"<td>{html_mod.escape(str(xt))}</td>"
                    f"<td>{cnt}</td>"
                    f"<td>{_fmt(pct, 'pct')}</td>"
                    "</tr>"
                )
    st = res["stats"]
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RSI high-water stop 40 through 80</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 24px; color: #0f172a; line-height: 1.45; }}
h1 {{ font-size: 1.4rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; border-radius: 10px; padding: 12px 14px; margin: 12px 0; }}
.banner {{ background: #fff7ed; border: 1px solid #fdba74; border-radius: 10px; padding: 12px 14px; margin: 12px 0; }}
code {{ font-size: 0.92em; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Relative Strength Index (RSI): high-water stop at 40% through 80%</h1>
<p>Research only. Not gold. Not DailyRun. Out-of-sample is report-only. 40/50/60 were already seen on this same RSI book; 70% and 80% are the next step on that same history, so the horse race is in-sample selection.</p>
<div class="callout">
<h2>What you asked</h2>
<p>{html_mod.escape(ASK)}</p>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN)}</p>
</div>
<div class="banner">
<p><strong>Control</strong> is RSI's current closed book and the exit that book already used. Entries are not rerun and positions are not resized. This is not the Rocket Launcher partial exit.</p>
<p><strong>High-water mark</strong> is the highest daily high since the entry fill, from the warehouse daily open-high-low-close ({html_mod.escape(res['ohlc_src'])}). On the entry day the high can set the mark for the next day, and that same day is not stopped out by its own high.</p>
<p><strong>Keep fraction.</strong> Stop = entry + k × (high-water mark − entry), for k of 0.40, 0.50, 0.60, 0.70, and 0.80. A higher k sits closer to the high and gives back less of the gain. The stop checked on day T uses the mark through day T−1 only. If the new stop is not above RSI's original stop, the original stop stays.</p>
<p><strong>Call.</strong> {html_mod.escape(j['verdict'])}. {html_mod.escape(j['line'])}</p>
<p>In-sample means entry before 2024-01-01. Out-of-sample means entry on or after 2024-01-01. Judge on in-sample quality. Do not pick 70% or 80% because out-of-sample looks better.</p>
<p>The first mention of annualized rate of return is this sentence. After that, Ann ROR is the house formula <code>((1 + total profit / (slot cash × N)) ^ (365 / average days held) − 1) × 100</code> via <code>compare_format.ann_ror_from_closed</code>. Slot cash: {html_mod.escape(res['cash_src'])}.</p>
</div>
<p>Click column headers to sort. Swipe sideways to see more columns.</p>
{headline("FULL", "Full book")}
{headline("IS", "In-sample (entry before 2024-01-01)")}
{headline("OOS", "Out-of-sample (entry on or after 2024-01-01) — report only")}
{canon("FULL")}
{canon("IS")}
{canon("OOS")}
<h2>Coverage</h2>
<p>Scored {st.get('kept', 0):,}. Shorts left out {st.get('short_skipped', 0):,}. No daily path {st.get('missing_ohlc', 0):,}. Stop hits 40/50/60/70/80 = {st.get('hit_k40', 0):,}/{st.get('hit_k50', 0):,}/{st.get('hit_k60', 0):,}/{st.get('hit_k70', 0):,}/{st.get('hit_k80', 0):,}. Slot cash {html_mod.escape(format_money(res['cash']))}.</p>
<h2>Exit mix</h2>
<p>HWM_GAP is a sell at the open because the open was already through the high-water stop. HWM_STOP is a sell at the stop price because the low tagged it. Other labels are the book's original exit type. N in this table is the count of that exit, not a second book size.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable"><thead><tr>
{hwm._th("Arm", "text")}{hwm._th("Slice", "text")}{hwm._th("Exit", "text")}{hwm._th("N", "num")}{hwm._th("% of arm", "num")}
</tr></thead><tbody>
{''.join(exit_rows)}
</tbody></table></div>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""


def write_baseline(res: dict) -> None:
    j = res["judge"]
    st = res["stats"]
    lines = [
        "# RSI high-water stop keep 40/50/60/70/80 — 2026-10-15",
        "",
        "Research only. Not gold. Not DailyRun. No knob was chosen from out-of-sample.",
        "",
        "## What you asked",
        "",
        f"> {ASK}",
        "",
        "## In plain English",
        "",
        PLAIN,
        "",
        "## Freeze",
        "",
        "- System: Relative Strength Index (RSI) only. Control = `Drive/RSI_LatestRun_Closed.csv` and the exit that book already used.",
        "- Not the Rocket Launcher partial exit (80% at +20%, leftover stop at entry, leftover at +40%).",
        "- Overlay arms k = 0.40, 0.50, 0.60, 0.70, 0.80. Stop = entry + k × (high-water mark − entry). Same overlay rules as `hwm_stop_keep_40_50_60_20261015`.",
        f"- High-water mark = highest daily high since the fill. Bars: {res['ohlc_src']}. Not a 15-minute high.",
        "- No lookahead: day T uses the mark through T−1. Entry-day high sets the next day's mark and does not stop out the entry day.",
        "- Open through the stop fills at the open; else a low through the stop fills at the stop; else the original exit stands.",
        "- New stop is used only when it is strictly above the original stop (never loosen).",
        "- In-sample: entry_date < 2024-01-01. Out-of-sample: entry_date >= 2024-01-01. Full book reported too.",
        "- N matches across arms, so N is printed once per slice, not as a keep-fraction column.",
        "- Annualized rate of return: `compare_format.ann_ror_from_closed`, days_per_year 365. Slot cash = Closed median implied notional. Report capacity_brt_cash only when within 25% of that median.",
        "- Max DD and Sharpe: exit-date equity, seed $500,000. Not a daily mark-to-market curve.",
        "- Selection bias: 40/50/60 were already seen. 70/80 are the next step on the same RSI book. OOS is report-only.",
        "",
        "## Coverage",
        "",
        f"- Slot {format_money(res['cash'])}. {res['cash_src']}.",
        f"- Scored {st.get('kept', 0):,}; shorts left out {st.get('short_skipped', 0):,}; no OHLC path {st.get('missing_ohlc', 0):,}.",
        f"- Stop hits 40/50/60/70/80 = {st.get('hit_k40', 0):,}/{st.get('hit_k50', 0):,}/{st.get('hit_k60', 0):,}/{st.get('hit_k70', 0):,}/{st.get('hit_k80', 0):,}.",
        f"- Stop column `{res['stop_col'] or 'none'}`.",
        "",
        "## In-sample call versus 60%",
        "",
        f"**{j['verdict']}.** {j['line']}",
        "",
        f"- Keep 70% versus 60% (in-sample): {j['vs60']['k70']}.",
        f"- Keep 80% versus 60% (in-sample): {j['vs60']['k80']}.",
        "",
        "## Not computed",
        "",
        "Days underwater, concurrent position counts, aggressive PnL, and Paul / FIT scores need a daily equity curve or a rebuilt Summary. This page does not invent them.",
        "",
        "## Promotion",
        "",
        "Research candidate at most. Not gold. Not wired to DailyRun.",
        "",
    ]
    (OUT / "BASELINE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def slim_metrics(m: dict) -> dict:
    out = {}
    for _label, key, _typ, _kind in hwm.METRIC_SPEC:
        v = m.get(key)
        if isinstance(v, float) and not math.isfinite(v):
            v = None
        out[key] = v
    out["exit_mix"] = m.get("exit_mix") or {}
    out["ann_note"] = m.get("ann_note") or ""
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    df, meta = hwm.load_trades("RSI")
    cash, cash_src, dollars = hwm.slot_cash(df, "RSI")
    print(f"loaded {len(df):,} cash {cash:,.2f}", flush=True)
    ohlc, ohlc_src, ohlc_missing = load_ohlc(set(df["symbol"].tolist()))
    print(f"ohlc symbols {len(ohlc):,} via {ohlc_src} missing {len(ohlc_missing)}", flush=True)
    arms, stats = build_rows(df, ohlc, dollars)
    slices = {}
    for mode in ("FULL", "IS", "OOS"):
        slices[mode] = {}
        for arm in ARMS:
            part = hwm._slice(arms[arm], mode)
            slices[mode][arm] = hwm.book_metrics(part, cash)
            if slices[mode][arm]["ann_ror"] is None and slices[mode][arm]["ann_note"]:
                print(f"{mode} {arm}: {slices[mode][arm]['ann_note']}", flush=True)
    # N must match within a slice.
    for mode in ("FULL", "IS", "OOS"):
        ns = {arm: slices[mode][arm]["n"] for arm in ARMS}
        if len(set(ns.values())) != 1:
            raise SystemExit(f"N mismatch on {mode}: {ns}")
    res = {
        "cash": cash,
        "cash_src": cash_src,
        "stats": stats,
        "slices": slices,
        "stop_col": meta.get("stop_col") or "",
        "ohlc_src": ohlc_src,
        "ohlc_missing": ohlc_missing,
        "judge": {},
    }
    res["judge"] = judge(slices)
    (OUT / "compare.html").write_text(render(res), encoding="utf-8")
    write_baseline(res)
    dump = {
        "cash": cash,
        "cash_src": cash_src,
        "stats": stats,
        "judge": res["judge"],
        "slices": {mode: {arm: slim_metrics(slices[mode][arm]) for arm in ARMS} for mode in slices},
    }
    (OUT / "metrics.json").write_text(json.dumps(dump, indent=2), encoding="utf-8")
    print(res["judge"]["verdict"])
    print(res["judge"]["line"])
    for mode in ("FULL", "IS", "OOS"):
        n = slices[mode]["control"]["n"]
        print(f"--- {mode} N={n} ---")
        for arm in ARMS:
            m = slices[mode][arm]
            print(
                f"{ARM_LABEL[arm]:12} WR {m['win_pct']:.2f}  AVG {m['avg_pnl_pct']:.2f}  ANN {m['ann_ror']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
