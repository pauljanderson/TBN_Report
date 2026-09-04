#!/usr/bin/env python3
"""Scalp AB: open vs prior close + first 15m bar color filters (research only).

Control freeze: stamped open-15 fade book (LOD/HOD ±0.1%, open15 target, 11:30),
prefer shorts-only LEAN KEEP as primary house research freeze.

Arm A (bullish open/bar): day open > prior close AND first 15m green (C>O).
Arm B (bearish open/bar): day open < prior close AND first 15m red (C<O).

Honesty: scalp shorts already require open15 green; longs require open15 red.
So Arm A on shorts ≈ gap-up filter; Arm B on shorts ≈ empty (wrong-side).
Arm B on longs ≈ gap-down filter; Arm A on longs ≈ empty.

Usage:
  python tools/scalp_open_15m_color_ab.py
  python tools/scalp_open_15m_color_ab.py --stamp scalp_open_15m_color_ab_20260902
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import math
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "stock_analysis"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import scalp_open15_reversal_ab as ab  # noqa: E402
from compare_format import format_money  # noqa: E402

DRIVE = ROOT / "drive"
DEFAULT_STAMP = "scalp_open_15m_color_ab_20260902"
CONTROL_SOURCE_STAMP = "scalp_full_levers_20260822"
CONTROL_TRADES_REL = f"paul_experiments/{CONTROL_SOURCE_STAMP}/trades_control.csv"
SHORTS_LEAN_STAMP = "scalp_shorts_only_and_symbol_summary_20260827"
SYSTEM = "scalp"
CANONICAL_OOS = date(2024, 1, 1)


def _coerce_trade(row: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = dict(row)
    for k in (
        "pnl_pct",
        "pnl_usd",
        "shares",
        "entry",
        "stop",
        "target",
        "exit",
        "r_mult",
        "lod",
        "hod",
        "setup_h",
        "setup_l",
        "atr_prior",
        "adv_prior",
        "open15_o",
        "open15_h",
        "open15_l",
        "open15_c",
        "open15_range",
        "range_vs_atr",
        "prior_close",
        "day_open",
        "gap_vs_prior_pct",
    ):
        v = out.get(k)
        if v in ("", None):
            continue
        try:
            out[k] = float(v)
        except (TypeError, ValueError):
            pass
    return out


def load_control_trades(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as f:
        return [_coerce_trade(r) for r in csv.DictReader(f)]


def prior_close_map(daily) -> dict[date, float]:
    """Session D → Close of prior session (look-ahead safe)."""
    dates = list(daily["Date"])
    closes = list(daily["Close"].astype(float))
    out: dict[date, float] = {}
    for i in range(1, len(dates)):
        out[dates[i]] = float(closes[i - 1])
    return out


def tag_trades(trades: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, int]:
    """Attach prior_close / open15 color / arm flags. Returns (tagged, n_ok, n_miss)."""
    cache: dict[str, dict[date, float]] = {}
    tagged: list[dict[str, Any]] = []
    n_ok = 0
    n_miss = 0
    for t in trades:
        sym = str(t.get("symbol") or "").upper()
        sess = str(t.get("session") or t.get("entry_date") or "")[:10]
        try:
            d = datetime.strptime(sess, "%Y-%m-%d").date()
        except ValueError:
            n_miss += 1
            continue
        if sym not in cache:
            daily = ab.load_ohlc(sym)
            cache[sym] = prior_close_map(daily) if daily is not None else {}
        pc = cache[sym].get(d)
        o15_o = float(t.get("open15_o") or float("nan"))
        o15_c = float(t.get("open15_c") or float("nan"))
        if pc is None or not math.isfinite(pc) or not math.isfinite(o15_o) or not math.isfinite(o15_c):
            n_miss += 1
            out = dict(t)
            out["tag_ok"] = 0
            out["skip_reason"] = "missing_prior_close_or_open15"
            tagged.append(out)
            continue
        green = o15_c > o15_o
        red = o15_c < o15_o
        gap_up = o15_o > pc
        gap_down = o15_o < pc
        arm_a = gap_up and green
        arm_b = gap_down and red
        out = dict(t)
        out.update(
            {
                "tag_ok": 1,
                "prior_close": round(pc, 6),
                "day_open": round(o15_o, 6),
                "gap_vs_prior_pct": round((o15_o / pc - 1.0) * 100.0, 6) if pc else "",
                "open15_color": "green" if green else ("red" if red else "doji"),
                "gap_vs_prior": "up" if gap_up else ("down" if gap_down else "flat"),
                "arm_a_bull": 1 if arm_a else 0,
                "arm_b_bear": 1 if arm_b else 0,
            }
        )
        n_ok += 1
        tagged.append(out)
    return tagged, n_ok, n_miss


def session_span(trades: list[dict[str, Any]]) -> tuple[str, str, int]:
    sessions = sorted({str(t.get("session") or "")[:10] for t in trades if t.get("session")})
    if not sessions:
        return "", "", 0
    return sessions[0], sessions[-1], len(sessions)


def write_trades_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("note\nno_trades\n", encoding="utf-8")
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


def pick_verdict(
    ctrl: dict[str, Any],
    cand: dict[str, Any],
    *,
    arm_label: str,
    wrong_side: bool = False,
    note_extra: str = "",
) -> str:
    """Quality over N; research only. Canonical IS/OOS N/A on Yahoo 1m window."""
    cn = int(ctrl.get("N") or 0)
    kn = int(cand.get("N") or 0)
    note = (
        f"N {cn}->{kn}; full-sample only (canonical IS/OOS N/A - Yahoo 1m short window). "
        "Research only; not gold, not DailyRun."
    )
    if note_extra:
        note = f"{note} {note_extra}"
    if wrong_side:
        return (
            f"DISMISS - {arm_label} structurally wrong-side for this book "
            f"(open15 color contradicts scalp side gate). {note}"
        )
    if kn < 30:
        return f"HOLD - {arm_label} thin N={kn} vs control. {note}"
    c_avg = ctrl.get("Avg_PnL_%")
    k_avg = cand.get("Avg_PnL_%")
    c_pf = ctrl.get("Profit_Factor")
    k_pf = cand.get("Profit_Factor")
    c_dd = ctrl.get("Max_DD_%")
    k_dd = cand.get("Max_DD_%")
    if not (
        isinstance(c_avg, float)
        and isinstance(k_avg, float)
        and math.isfinite(c_avg)
        and math.isfinite(k_avg)
    ):
        return f"HOLD - {arm_label} insufficient Avg PnL% for compare. {note}"

    dd_ok = True
    if isinstance(k_dd, float) and isinstance(c_dd, float) and math.isfinite(k_dd) and math.isfinite(c_dd):
        dd_ok = abs(k_dd) <= abs(c_dd) * 1.15 + 0.5
    pf_ok = (
        not isinstance(k_pf, float)
        or not isinstance(c_pf, float)
        or not math.isfinite(k_pf)
        or not math.isfinite(c_pf)
        or k_pf >= c_pf - 0.05
    )
    better = (k_avg > c_avg + 0.01) and pf_ok and dd_ok
    worse = k_avg < c_avg - 0.02
    if worse:
        return f"DISMISS - {arm_label} Avg PnL% worse than control. {note}"
    if better:
        return (
            f"LEAN KEEP - {arm_label} improves Avg PnL% / PF / DD vs control on this short window. "
            f"{note} Selection bias labeled (filter chosen after idea; same freeze book)."
        )
    return f"HOLD - {arm_label} flat/mixed vs control. {note}"


def _num_cell(v: Any, nd: int = 2) -> str:
    return f"<td>{ab._fmt_num(v, nd)}</td>"


def _money_cell(v: Any) -> str:
    if isinstance(v, (int, float)) and math.isfinite(float(v)):
        return f"<td>{format_money(v)}</td>"
    return "<td>—</td>"


def _delta(a: Any, b: Any) -> float:
    if (
        isinstance(a, (int, float))
        and isinstance(b, (int, float))
        and math.isfinite(float(a))
        and math.isfinite(float(b))
    ):
        return float(a) - float(b)
    return float("nan")


def write_compare_html(
    path: Path,
    *,
    stamp: str,
    book_note: str,
    cov: str,
    rows: list[dict[str, Any]],
    exit_blocks: list[tuple[str, dict[str, Any]]],
    verdicts: list[str],
) -> None:
    # Omit Total/Sheet PnL $ from HTML compare per CANONICAL_COMPARE_METRICS.
    cols = [
        ("arm", "text"),
        ("role", "text"),
        ("N", "num"),
        ("Wins", "num"),
        ("Losses", "num"),
        ("Win%", "num"),
        ("Avg_PnL_%", "num"),
        ("AVG_PNL_PCT_WO_MAX", "num"),
        ("Profit_Factor", "num"),
        ("Expectancy_%", "num"),
        ("Max_DD_%", "num"),
        ("Ann_ROR_%", "num"),
        ("ΔN_vs_ctrl", "num"),
        ("ΔAvg_PnL_%", "num"),
        ("ΔPF", "num"),
        ("ΔMax_DD_%", "num"),
        ("verdict", "text"),
    ]
    head = "".join(ab.sortable_th(c, t) for c, t in cols)
    body = []
    for r in rows:
        cells = []
        for c, t in cols:
            v = r.get(c, "")
            if c in ("arm", "role", "verdict"):
                cells.append(f"<td>{html_mod.escape(str(v))}</td>")
            elif c in ("N", "Wins", "Losses", "ΔN_vs_ctrl") and isinstance(v, (int, float)) and math.isfinite(float(v)):
                cells.append(f"<td>{int(v)}</td>")
            elif c in ("Avg_PnL_%", "AVG_PNL_PCT_WO_MAX", "Expectancy_%", "ΔAvg_PnL_%") or (
                isinstance(c, str) and c.startswith("ΔAvg")
            ):
                cells.append(_num_cell(v, 4))
            else:
                cells.append(_num_cell(v, 2))
        body.append("<tr>" + "".join(cells) + "</tr>")

    def exit_mix_html(title: str, m: dict[str, Any]) -> str:
        em = m.get("exit_mix") or {}
        if not em:
            return f"<h2>{html_mod.escape(title)}</h2><p>No exit mix.</p>"
        h = ab.sortable_th("exit_type", "text") + ab.sortable_th("N", "num") + ab.sortable_th("pct", "num")
        n = int(m.get("N") or 0) or sum(int(v) for v in em.values())
        b = "".join(
            f"<tr><td>{html_mod.escape(str(k))}</td><td>{int(v)}</td>"
            f"<td>{(100.0 * int(v) / n) if n else float('nan'):.1f}</td></tr>"
            for k, v in sorted(em.items(), key=lambda kv: -int(kv[1]))
        )
        return f"""<h2>{html_mod.escape(title)}</h2>
<table class="sortable"><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>"""

    verd_html = "".join(f"<li>{html_mod.escape(v)}</li>" for v in verdicts)
    exit_html = "".join(exit_mix_html(title, m) for title, m in exit_blocks)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Scalp open/15m color AB — {html_mod.escape(stamp)}</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1rem 1.25rem; color: #0f172a; background: #f8fafc; }}
h1,h2 {{ color: #0f172a; font-size: 1.2rem; }}
.note {{ background: #fff7ed; border-left: 4px solid #f97316; padding: .75rem 1rem; margin: 1rem 0; font-size: .92rem; }}
.verdict {{ font-weight: 600; margin: .5rem 0; }}
table {{ border-collapse: collapse; width: 100%; background: #fff; margin: .75rem 0 1.25rem; font-size: .82rem; }}
th, td {{ border: 1px solid #cbd5e1; padding: .3rem .4rem; text-align: left; }}
th {{ background: #e2e8f0; }}
{ab.SORT_CSS}
code {{ background: #e2e8f0; padding: .1rem .3rem; border-radius: 3px; }}
ul {{ margin: .4rem 0 .8rem 1.2rem; }}
</style>
</head>
<body>
<h1>Scalp — open vs prior close + first 15m color AB</h1>
<p>Stamp <code>{html_mod.escape(stamp)}</code> · System <code>{SYSTEM}</code> · <strong>research only</strong></p>
<p><strong>Book:</strong> {html_mod.escape(book_note)}</p>
<div class="verdict">Verdicts</div>
<ul>{verd_html}</ul>
<div class="note">
<strong>Acronyms.</strong> LOD = Low of Day; HOD = High of Day; ATR = Average True Range;
ADV$ = Average Dollar Volume; WR% = Win Rate percent; PF = Profit Factor;
IS/OOS = In-Sample / Out-Of-Sample; RTH = Regular Trading Hours.<br/>
<strong>Control freeze.</strong> Open-15 fade from <code>{CONTROL_SOURCE_STAMP}</code>:
long when open15 loser (red); short when open15 winner (green); entry next 5m open after
hammer/engulf setup; stop LOD/HOD ±0.1%; target open15 opposite extreme; time-stop 11:30 ET.
Universe = all symbols with 1m under <code>data/intraday/1m/</code>.
House research lean from <code>{SHORTS_LEAN_STAMP}</code>: <strong>shorts-only LEAN KEEP</strong>
(primary control for Arm A).<br/>
<strong>Arms (filters on existing signals — one change = open/color gate).</strong><br/>
• <code>Ctrl_LS</code> = long+short control book (tagged with prior close).<br/>
• <code>Ctrl_S</code> = shorts-only (primary house freeze).<br/>
• <code>A_bull_*</code> = day open (<code>open15_o</code>) &gt; prior close <strong>AND</strong> open15 green.<br/>
• <code>B_bear_*</code> = day open &lt; prior close <strong>AND</strong> open15 red.<br/>
<strong>Side honesty.</strong> Engine already forces shorts→green open15 and longs→red open15.
Arm A on shorts ≈ gap-up filter; Arm B on shorts ≈ empty (wrong-side for short fade).
Arm B on longs ≈ gap-down filter; Arm A on longs ≈ empty.<br/>
<strong>IS/OOS:</strong> Canonical split (entry &lt; {CANONICAL_OOS.isoformat()}) is <strong>N/A</strong>
— Yahoo 1m window is short and entirely post-2024. Full-sample only.<br/>
<strong>Coverage.</strong> {html_mod.escape(cov)}<br/>
Click column headers to sort. Quality over trade count. Total/Sheet PnL$ omitted from HTML
(per canonical compare); see metrics CSV. Research ≠ gold ≠ DailyRun.
</div>
<h2>Arm compare</h2>
<table class="sortable">
<thead><tr>{head}</tr></thead>
<tbody>{''.join(body)}</tbody>
</table>
{exit_html}
{ab.SORT_JS}
</body>
</html>"""
    path.write_text(html, encoding="utf-8")


def write_baseline(
    path: Path,
    *,
    stamp: str,
    book_note: str,
    cov: str,
    n_src: int,
    n_ok: int,
    n_miss: int,
    metrics: dict[str, dict[str, Any]],
    verdicts: list[str],
) -> None:
    m_ls = metrics["Ctrl_LS"]
    m_s = metrics["Ctrl_S"]
    m_l = metrics["Ctrl_L"]
    m_a_s = metrics["A_bull_filter_S"]
    m_b_s = metrics["B_bear_filter_S"]
    m_a_ls = metrics["A_bull_filter_LS"]
    m_b_ls = metrics["B_bear_filter_LS"]
    m_b_l = metrics["descriptive_B_bear_L"]
    verd_block = "\n".join("- " + v for v in verdicts)
    text = f"""# BASELINE — Scalp open / 15m color AB — `{stamp}`

**System:** `{SYSTEM}` · research only · **not** DailyRun · **not** gold.

## Control freeze (identity)

| Item | Value |
|------|--------|
| Source trades | `{book_note}` |
| Prior freeze stamp | `{CONTROL_SOURCE_STAMP}` |
| House lean | Shorts-only **LEAN KEEP** from `{SHORTS_LEAN_STAMP}` (primary control for Arm A) |
| Universe | All symbols with 1m parquet under `data/intraday/1m/` (same as levers pack) |
| Entry | Open-15 fade: long on open15 loser (red) + 5m hammer/engulf below; short on open15 winner (green) + 5m bearish hammer/engulf above |
| Stop | Long: **0.1% below LOD**; Short: **0.1% above HOD** |
| Target | open-15 opposite extreme |
| Time stop | **11:30 ET** bar open |
| Sheet | $45,000 / trade · 0 bps |
| Intraday data | `data/intraday/1m/{{SYM}}.parquet` (Yahoo 1m; short retention) |
| Daily OHLC | `data/newdata/data/{{SYM}}.csv` (prior close) |

## Hypothesis (one-knob filters)

Filter **existing** scalp signals — do not invent a new entry system.

| Arm | Definition |
|-----|------------|
| Ctrl_LS | Long+short control book (tagged) |
| Ctrl_S | Shorts-only subset (**primary control**) |
| Ctrl_L | Longs-only reference |
| A_bull_filter_S | Ctrl_S intersect (day open > prior close and open15 green) |
| B_bear_filter_S | Ctrl_S intersect (day open < prior close and open15 red) |
| A_bull_filter_LS | Ctrl_LS intersect Arm A |
| B_bear_filter_LS | Ctrl_LS intersect Arm B |
| descriptive_B_bear_L | Longs-only intersect Arm B (aligns with long open15 red; descriptive) |
| descriptive_A_bull_L | Longs-only intersect Arm A (expect empty; descriptive) |

**Day open** = `open15_o` (left-labeled 09:30 ET 15m open = Regular Trading Hours open).
**Prior close** = previous session Close from daily OHLC (no look-ahead).

## Side mapping honesty

| Scalp side | Open15 color (engine) | Arm A (bull) | Arm B (bear) |
|------------|----------------------|--------------|--------------|
| Short | Always green | approx gap-up filter (`open > prior close`) | Wrong-side (needs red) -> expect N=0 |
| Long | Always red | Wrong-side (needs green) -> expect N=0 | approx gap-down filter (`open < prior close`) |

## Coverage / IS-OOS honesty

{cov}

- Source N={n_src} · tagged OK={n_ok} · missing prior close={n_miss}
- Canonical IS (`entry_date < {CANONICAL_OOS.isoformat()}`) / OOS: **N/A** (Yahoo 1m short window, all post-2024).
- Report **full-sample only**. Do not invent a fake OOS.
- Selection bias: filters applied to a frozen stamped book after the idea — research candidate only.

## Snapshot metrics (full-sample)

| Arm | N | WR% | Avg PnL% | PF | Max DD% |
|-----|---|-----|----------|----|---------|
| Ctrl_LS | {m_ls.get('N')} | {ab._fmt_num(m_ls.get('Win%'))} | {ab._fmt_num(m_ls.get('Avg_PnL_%'), 4)} | {ab._fmt_num(m_ls.get('Profit_Factor'))} | {ab._fmt_num(m_ls.get('Max_DD_%'))} |
| Ctrl_S | {m_s.get('N')} | {ab._fmt_num(m_s.get('Win%'))} | {ab._fmt_num(m_s.get('Avg_PnL_%'), 4)} | {ab._fmt_num(m_s.get('Profit_Factor'))} | {ab._fmt_num(m_s.get('Max_DD_%'))} |
| Ctrl_L | {m_l.get('N')} | {ab._fmt_num(m_l.get('Win%'))} | {ab._fmt_num(m_l.get('Avg_PnL_%'), 4)} | {ab._fmt_num(m_l.get('Profit_Factor'))} | {ab._fmt_num(m_l.get('Max_DD_%'))} |
| A_bull_filter_S | {m_a_s.get('N')} | {ab._fmt_num(m_a_s.get('Win%'))} | {ab._fmt_num(m_a_s.get('Avg_PnL_%'), 4)} | {ab._fmt_num(m_a_s.get('Profit_Factor'))} | {ab._fmt_num(m_a_s.get('Max_DD_%'))} |
| B_bear_filter_S | {m_b_s.get('N')} | {ab._fmt_num(m_b_s.get('Win%'))} | {ab._fmt_num(m_b_s.get('Avg_PnL_%'), 4)} | {ab._fmt_num(m_b_s.get('Profit_Factor'))} | {ab._fmt_num(m_b_s.get('Max_DD_%'))} |
| A_bull_filter_LS | {m_a_ls.get('N')} | {ab._fmt_num(m_a_ls.get('Win%'))} | {ab._fmt_num(m_a_ls.get('Avg_PnL_%'), 4)} | {ab._fmt_num(m_a_ls.get('Profit_Factor'))} | {ab._fmt_num(m_a_ls.get('Max_DD_%'))} |
| B_bear_filter_LS | {m_b_ls.get('N')} | {ab._fmt_num(m_b_ls.get('Win%'))} | {ab._fmt_num(m_b_ls.get('Avg_PnL_%'), 4)} | {ab._fmt_num(m_b_ls.get('Profit_Factor'))} | {ab._fmt_num(m_b_ls.get('Max_DD_%'))} |
| descriptive_B_bear_L | {m_b_l.get('N')} | {ab._fmt_num(m_b_l.get('Win%'))} | {ab._fmt_num(m_b_l.get('Avg_PnL_%'), 4)} | {ab._fmt_num(m_b_l.get('Profit_Factor'))} | {ab._fmt_num(m_b_l.get('Max_DD_%'))} |

## Verdicts

{verd_block}

## Artifacts

- `compare.html` / `metrics_ab.csv`
- `trades_tagged.csv` / `trades_Ctrl_S.csv` / `trades_A_bull_filter_S.csv` / `trades_B_bear_filter_S.csv`
- `trades_A_bull_filter_LS.csv` / `trades_B_bear_filter_LS.csv`
- `BASELINE.md` / `SUMMARY.md`
"""
    path.write_text(text, encoding="utf-8")


def write_summary(
    path: Path,
    *,
    stamp: str,
    book_note: str,
    cov: str,
    metrics: dict[str, dict[str, Any]],
    verdicts: list[str],
) -> None:
    lines = [
        f"# SUMMARY — `{stamp}`",
        "",
        "**Research only** · Scalp open-15 fade · open vs prior close + first 15m color filters.",
        "",
        "## Book",
        "",
        book_note,
        "",
        f"Coverage: {cov}",
        "",
        "## Arms vs control",
        "",
        "| Arm | N | WR% | Avg PnL% | PF | PnL$ | Max DD% |",
        "|-----|---|-----|----------|----|------|---------|",
    ]
    order = [
        "Ctrl_LS",
        "Ctrl_S",
        "Ctrl_L",
        "A_bull_filter_S",
        "B_bear_filter_S",
        "A_bull_filter_LS",
        "B_bear_filter_LS",
        "descriptive_B_bear_L",
        "descriptive_A_bull_L",
    ]
    for arm in order:
        m = metrics[arm]
        lines.append(
            f"| {arm} | {m.get('N')} | {ab._fmt_num(m.get('Win%'))} | "
            f"{ab._fmt_num(m.get('Avg_PnL_%'), 4)} | {ab._fmt_num(m.get('Profit_Factor'))} | "
            f"{format_money(m.get('Total_PnL_$') or 0)} | {ab._fmt_num(m.get('Max_DD_%'))} |"
        )
    lines.extend(
        [
            "",
            "## Verdicts",
            "",
            *[f"- {v}" for v in verdicts],
            "",
            "IS/OOS: canonical split N/A — full-sample only.",
            "",
            "## Paths",
            "",
            f"- `drive/paul_experiments/{stamp}/compare.html`",
            f"- `drive/paul_experiments/{stamp}/BASELINE.md`",
            f"- `drive/paul_experiments/{stamp}/SUMMARY.md`",
            f"- `drive/paul_experiments/{stamp}/metrics_ab.csv`",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def metric_row(
    arm: str,
    role: str,
    m: dict[str, Any],
    *,
    ctrl: Optional[dict[str, Any]] = None,
    verdict: str = "",
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "arm": arm,
        "role": role,
        "verdict": verdict,
        "N": m.get("N"),
        "Wins": m.get("Wins"),
        "Losses": m.get("Losses"),
        "Win%": m.get("Win%"),
        "Avg_PnL_%": m.get("Avg_PnL_%"),
        "AVG_PNL_PCT_WO_MAX": m.get("AVG_PNL_PCT_WO_MAX"),
        "Profit_Factor": m.get("Profit_Factor"),
        "Total_PnL_$": m.get("Total_PnL_$"),
        "Sheet_PnL_$": m.get("Sheet_PnL_$", m.get("Total_PnL_$")),
        "Expectancy_%": m.get("Expectancy_%"),
        "Max_DD_%": m.get("Max_DD_%"),
        "Ann_ROR_%": m.get("Ann_ROR_%"),
    }
    if ctrl is None:
        row["ΔN_vs_ctrl"] = 0
        row["ΔAvg_PnL_%"] = 0.0
        row["ΔPF"] = 0.0
        row["ΔMax_DD_%"] = 0.0
    else:
        row["ΔN_vs_ctrl"] = int(m.get("N") or 0) - int(ctrl.get("N") or 0)
        row["ΔAvg_PnL_%"] = _delta(m.get("Avg_PnL_%"), ctrl.get("Avg_PnL_%"))
        row["ΔPF"] = _delta(m.get("Profit_Factor"), ctrl.get("Profit_Factor"))
        row["ΔMax_DD_%"] = _delta(m.get("Max_DD_%"), ctrl.get("Max_DD_%"))
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description="Scalp open/15m color filter AB")
    ap.add_argument("--stamp", default=DEFAULT_STAMP)
    ap.add_argument(
        "--trades",
        default="",
        help=f"Control trades CSV (default: drive/{CONTROL_TRADES_REL})",
    )
    args = ap.parse_args()
    stamp = str(args.stamp).strip() or DEFAULT_STAMP
    out_dir = DRIVE / "paul_experiments" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    trades_path = Path(args.trades) if args.trades else ROOT / "drive" / CONTROL_TRADES_REL
    if not trades_path.exists():
        print(f"ERROR: missing control trades {trades_path}", flush=True)
        return 1

    book_note = (
        f"Stamped control book `{CONTROL_SOURCE_STAMP}/trades_control.csv` "
        f"(stop_arm=control_lod_hod_0p1, time_stop=11:30, long+short)"
    )
    src = load_control_trades(trades_path)
    print(f"Loaded {len(src)} control trades from {trades_path}", flush=True)

    tagged, n_ok, n_miss = tag_trades(src)
    ok = [t for t in tagged if int(t.get("tag_ok") or 0) == 1]
    shorts = [t for t in ok if str(t.get("side")) == "short"]
    longs = [t for t in ok if str(t.get("side")) == "long"]

    books: dict[str, list[dict[str, Any]]] = {
        "Ctrl_LS": ok,
        "Ctrl_S": shorts,
        "Ctrl_L": longs,
        "A_bull_filter_S": [t for t in shorts if int(t.get("arm_a_bull") or 0) == 1],
        "B_bear_filter_S": [t for t in shorts if int(t.get("arm_b_bear") or 0) == 1],
        "A_bull_filter_LS": [t for t in ok if int(t.get("arm_a_bull") or 0) == 1],
        "B_bear_filter_LS": [t for t in ok if int(t.get("arm_b_bear") or 0) == 1],
        "descriptive_B_bear_L": [t for t in longs if int(t.get("arm_b_bear") or 0) == 1],
        "descriptive_A_bull_L": [t for t in longs if int(t.get("arm_a_bull") or 0) == 1],
    }

    metrics = {k: ab.metrics_from_trades(v, include_slices=False) for k, v in books.items()}

    smin, smax, nsess = session_span(ok)
    n_sym = len({str(t.get("symbol")) for t in ok})
    cov = (
        f"1m under `data/intraday/1m/` · tagged {n_ok}/{len(src)} "
        f"(missing prior close {n_miss}) · {n_sym} symbols · "
        f"session span {smin} → {smax} ({nsess} distinct sessions); "
        f"Yahoo 1m short retention - full-sample only."
    )

    side_contam = (
        "Note: vs Ctrl_LS this arm mostly drops the opposite side "
        "(A keeps shorts; B keeps longs) - not a pure open/color one-knob on a fixed side."
    )
    v_a_s = pick_verdict(metrics["Ctrl_S"], metrics["A_bull_filter_S"], arm_label="A_bull_filter_S")
    v_b_s = pick_verdict(
        metrics["Ctrl_S"],
        metrics["B_bear_filter_S"],
        arm_label="B_bear_filter_S",
        wrong_side=True,
    )
    v_a_ls = pick_verdict(
        metrics["Ctrl_LS"],
        metrics["A_bull_filter_LS"],
        arm_label="A_bull_filter_LS",
        note_extra=side_contam,
    )
    v_b_ls = pick_verdict(
        metrics["Ctrl_LS"],
        metrics["B_bear_filter_LS"],
        arm_label="B_bear_filter_LS",
        note_extra=side_contam,
    )
    v_b_l = pick_verdict(
        metrics["Ctrl_L"],
        metrics["descriptive_B_bear_L"],
        arm_label="descriptive_B_bear_L",
        note_extra="Compare is vs longs-only (fairer than vs Ctrl_LS).",
    )
    v_a_l = pick_verdict(
        metrics["Ctrl_L"],
        metrics["descriptive_A_bull_L"],
        arm_label="descriptive_A_bull_L",
        wrong_side=True,
    )
    verdicts = [
        f"[primary vs Ctrl_S] {v_a_s}",
        f"[primary vs Ctrl_S] {v_b_s}",
        f"[secondary vs Ctrl_LS] {v_a_ls}",
        f"[secondary vs Ctrl_LS] {v_b_ls}",
        f"[descriptive vs longs-only] {v_b_l}",
        f"[descriptive vs longs-only] {v_a_l}",
    ]

    # Persist trades
    write_trades_csv(out_dir / "trades_tagged.csv", tagged)
    for arm, rows in books.items():
        write_trades_csv(out_dir / f"trades_{arm}.csv", rows)

    compare_rows = [
        metric_row("Ctrl_LS", "control long+short", metrics["Ctrl_LS"], verdict="reference"),
        metric_row("Ctrl_S", "primary control (shorts LEAN KEEP freeze)", metrics["Ctrl_S"], verdict="primary control"),
        metric_row("Ctrl_L", "longs-only reference", metrics["Ctrl_L"], verdict="reference"),
        metric_row(
            "A_bull_filter_S",
            "Arm A on shorts (gap-up AND green)",
            metrics["A_bull_filter_S"],
            ctrl=metrics["Ctrl_S"],
            verdict=v_a_s,
        ),
        metric_row(
            "B_bear_filter_S",
            "Arm B on shorts (wrong-side)",
            metrics["B_bear_filter_S"],
            ctrl=metrics["Ctrl_S"],
            verdict=v_b_s,
        ),
        metric_row(
            "A_bull_filter_LS",
            "Arm A on long+short (side-contaminated vs Ctrl_LS)",
            metrics["A_bull_filter_LS"],
            ctrl=metrics["Ctrl_LS"],
            verdict=v_a_ls,
        ),
        metric_row(
            "B_bear_filter_LS",
            "Arm B on long+short (side-contaminated vs Ctrl_LS)",
            metrics["B_bear_filter_LS"],
            ctrl=metrics["Ctrl_LS"],
            verdict=v_b_ls,
        ),
        metric_row(
            "descriptive_B_bear_L",
            "descriptive longs AND Arm B vs longs-only",
            metrics["descriptive_B_bear_L"],
            ctrl=metrics["Ctrl_L"],
            verdict=v_b_l,
        ),
        metric_row(
            "descriptive_A_bull_L",
            "descriptive longs AND Arm A (wrong-side)",
            metrics["descriptive_A_bull_L"],
            ctrl=metrics["Ctrl_L"],
            verdict=v_a_l,
        ),
    ]

    # metrics CSV (includes money columns)
    keys = list(compare_rows[0].keys())
    with (out_dir / "metrics_ab.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(compare_rows)

    write_compare_html(
        out_dir / "compare.html",
        stamp=stamp,
        book_note=book_note,
        cov=cov,
        rows=compare_rows,
        exit_blocks=[
            ("Exit mix — Ctrl_S (primary)", metrics["Ctrl_S"]),
            ("Exit mix — A_bull_filter_S", metrics["A_bull_filter_S"]),
            ("Exit mix — B_bear_filter_S", metrics["B_bear_filter_S"]),
            ("Exit mix — Ctrl_LS", metrics["Ctrl_LS"]),
            ("Exit mix — A_bull_filter_LS", metrics["A_bull_filter_LS"]),
            ("Exit mix — B_bear_filter_LS", metrics["B_bear_filter_LS"]),
        ],
        verdicts=verdicts,
    )
    write_baseline(
        out_dir / "BASELINE.md",
        stamp=stamp,
        book_note=book_note,
        cov=cov,
        n_src=len(src),
        n_ok=n_ok,
        n_miss=n_miss,
        metrics=metrics,
        verdicts=verdicts,
    )
    write_summary(
        out_dir / "SUMMARY.md",
        stamp=stamp,
        book_note=book_note,
        cov=cov,
        metrics=metrics,
        verdicts=verdicts,
    )

    print(f"Wrote {out_dir}", flush=True)
    for arm in (
        "Ctrl_LS",
        "Ctrl_S",
        "Ctrl_L",
        "A_bull_filter_S",
        "B_bear_filter_S",
        "A_bull_filter_LS",
        "B_bear_filter_LS",
        "descriptive_B_bear_L",
        "descriptive_A_bull_L",
    ):
        m = metrics[arm]
        print(
            f"  {arm}: N={m.get('N')} Avg={ab._fmt_num(m.get('Avg_PnL_%'), 4)} "
            f"PF={ab._fmt_num(m.get('Profit_Factor'))} DD={ab._fmt_num(m.get('Max_DD_%'))}",
            flush=True,
        )
    for v in verdicts:
        print(f"VERDICT: {v}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
