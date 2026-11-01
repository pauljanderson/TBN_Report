"""Shared helpers for mean-reversion (MR) one-knob ABs (2026-09-03).

Research-only overlays / exit ABs. IS = entry < 2024-01-01; OOS report-only.
"""
from __future__ import annotations

import html as html_mod
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
DATA_DIR = ROOT / "data" / "newdata" / "data"
PARENT_STAMP = "mean_reversion_ab_20260903"
PARENT_OUT = DRIVE / "paul_experiments" / PARENT_STAMP
IS_CUT = date(2024, 1, 1)

RL_CASH = 47_500.0
BRT_CASH = 47_500.0

# Prod RL freeze (run_rl.bat / rocket_rl_config.py as of 2026-09-03)
RL_40_30D_CLOSED = (
    DRIVE
    / "paul_experiments"
    / "rl_entry_exit_ab_20260831"
    / "runs"
    / "40_30d"
    / "RL_Closed_260831203843.csv"
)
BRT_LATEST_CLOSED = DRIVE / "BRT_LatestRun_Closed.csv"
SCORES_INDUSTRY = (
    DRIVE / "paul_experiments" / "fund_scorecard_v1_industry_20260831" / "scores.csv"
)
SCORES_FALLBACK = DRIVE / "paul_experiments" / "fund_scorecard_v1_20260830" / "scores.csv"

sys_path_done = False


def ensure_paths() -> None:
    global sys_path_done
    if sys_path_done:
        return
    import sys

    for p in (ROOT / "tools", DRIVE / "paul_experiments"):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)
    sys_path_done = True


ensure_paths()

from be_stop_replay_ab import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    sortable_th,
)
from compare_format import filter_html_compare_columns, format_money  # noqa: E402
from rl_univ_compare_lists import (  # noqa: E402
    book_stats,
    load_trades,
    split_is_oos,
    verdict_vs_control,
)
import rl_univ_compare_lists as _rlul  # noqa: E402


def esc(x: object) -> str:
    return html_mod.escape("" if x is None else str(x))


def fmt_n(v: float, d: int = 2) -> str:
    if v is None or not math.isfinite(v):
        return "—"
    return f"{v:.{d}f}"


def fmt_pct(v: float, d: int = 2) -> str:
    if v is None or not math.isfinite(v):
        return "—"
    return f"{v:.{d}f}"


def stats_with_cash(trades: list[dict[str, Any]], cash: float) -> dict[str, Any]:
    prev = _rlul.RL_CASH
    try:
        _rlul.RL_CASH = cash
        return book_stats(trades)
    finally:
        _rlul.RL_CASH = prev


def pack_overlay_arm(
    arm_id: str,
    label: str,
    trades: list[dict[str, Any]],
    cash: float,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    is_t, oos_t = split_is_oos(trades)
    out: dict[str, Any] = {
        "id": arm_id,
        "label": label,
        "trades": trades,
        "n_keep_sym": len({t["sym"] for t in trades}),
        "m_full": stats_with_cash(trades, cash),
        "m_is": stats_with_cash(is_t, cash),
        "m_oos": stats_with_cash(oos_t, cash),
        "is_t": is_t,
        "oos_t": oos_t,
    }
    if extra:
        out.update(extra)
    return out


def overall_verdict(arm: dict[str, Any], control: dict[str, Any]) -> tuple[str, str, str, str]:
    packed_cand = {"m_is": arm["m_is"], "m_oos": arm["m_oos"], "m_full": arm["m_full"]}
    packed_ctrl = {
        "m_is": control["m_is"],
        "m_oos": control["m_oos"],
        "m_full": control["m_full"],
    }
    is_v, is_n = verdict_vs_control(packed_cand, packed_ctrl, "m_is")
    oos_v, oos_n = verdict_vs_control(packed_cand, packed_ctrl, "m_oos")
    tag = is_v
    note = f"IS={is_v} ({is_n}); OOS={oos_v} ({oos_n})"
    if is_v in ("KEEP", "LEAN KEEP") and oos_v == "DISMISS":
        tag = "HOLD"
        note += " → overall HOLD (OOS softens; no OOS retune)"
    return tag, is_v, oos_v, note


class OhlcCache:
    def __init__(self) -> None:
        self._bars: dict[str, dict[str, Any]] = {}

    def _path(self, sym: str) -> Optional[Path]:
        for name in (f"{sym}.csv", f"{sym}.CSV"):
            p = DATA_DIR / name
            if p.is_file():
                return p
        return None

    def bars(self, sym: str) -> Optional[dict[str, Any]]:
        if sym in self._bars:
            return self._bars[sym] or None
        path = self._path(sym)
        if path is None:
            self._bars[sym] = {}
            return None
        df = pd.read_csv(path)
        dcol = "Date" if "Date" in df.columns else "DATE"
        df[dcol] = pd.to_datetime(df[dcol], errors="coerce")
        df = df.dropna(subset=[dcol]).sort_values(dcol)
        dates = [d.date() for d in df[dcol]]
        close = pd.to_numeric(
            df["Close"] if "Close" in df.columns else df["CLOSE"], errors="coerce"
        ).to_numpy(dtype=np.float64)
        pack = {
            "dates": dates,
            "close": close,
            "date_to_i": {d: i for i, d in enumerate(dates)},
            "rsi2": wilder_rsi(close, 2),
        }
        self._bars[sym] = pack
        return pack

    def signal_idx(self, sym: str, opened: date) -> Optional[int]:
        """Last completed daily bar strictly before DATE_OPENED (no look-ahead)."""
        b = self.bars(sym)
        if not b:
            return None
        i = b["date_to_i"].get(opened)
        if i is not None:
            return i - 1 if i > 0 else None
        # opened may be a session not in calendar — find last date < opened
        dates = b["dates"]
        lo, hi = 0, len(dates) - 1
        ans = None
        while lo <= hi:
            mid = (lo + hi) // 2
            if dates[mid] < opened:
                ans = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return ans


def wilder_rsi(close: np.ndarray, period: int = 2) -> np.ndarray:
    n = len(close)
    out = np.full(n, np.nan, dtype=np.float64)
    if n < period + 1:
        return out
    delta = np.diff(close, prepend=np.nan)
    gain = np.where(np.isfinite(delta) & (delta > 0), delta, 0.0)
    loss = np.where(np.isfinite(delta) & (delta < 0), -delta, 0.0)
    # Seed with SMA of first `period` changes (bars 1..period)
    avg_g = float(np.nanmean(gain[1 : period + 1]))
    avg_l = float(np.nanmean(loss[1 : period + 1]))
    if avg_l == 0:
        out[period] = 100.0
    else:
        out[period] = 100.0 - (100.0 / (1.0 + avg_g / avg_l))
    for i in range(period + 1, n):
        avg_g = (avg_g * (period - 1) + gain[i]) / period
        avg_l = (avg_l * (period - 1) + loss[i]) / period
        if avg_l == 0:
            out[i] = 100.0
        else:
            out[i] = 100.0 - (100.0 / (1.0 + avg_g / avg_l))
    return out


def ret_nd(close: np.ndarray, i: int, n: int = 21) -> float:
    if i is None or i < n:
        return float("nan")
    c0, c1 = close[i - n], close[i]
    if not (math.isfinite(c0) and math.isfinite(c1)) or c0 == 0:
        return float("nan")
    return float(c1 / c0 - 1.0)


def build_compare_table(
    title: str,
    arms: list[dict[str, Any]],
    control: dict[str, Any],
    split_key: str,
) -> str:
    cols = [
        ("Arm", "text"),
        ("N keep sym", "num"),
        ("N", "num"),
        ("WR %", "num"),
        ("Avg PnL %", "num"),
        ("WO_MAX %", "num"),
        ("PF", "num"),
        ("Avg win %", "num"),
        ("Avg loss %", "num"),
        ("Ann ROR %", "num"),
        ("Max DD %", "num"),
        ("Calmar", "num"),
        ("Avg days", "num"),
        ("Med days", "num"),
        ("Cap days", "num"),
        ("Profit / cap day", "num"),
        ("Expectancy $", "num"),
        ("Lose streak", "num"),
        ("TPY", "num"),
        ("Δ Avg %", "num"),
        ("Δ WO_MAX", "num"),
        ("Δ PF", "num"),
        ("Δ WR", "num"),
        ("Δ Ann ROR", "num"),
        ("Δ Max DD", "num"),
        ("Δ Calmar", "num"),
        ("Verdict vs ctrl", "text"),
    ]
    cols = filter_html_compare_columns(cols)
    cols = [(a, b) for a, b in cols if "Sheet" not in a and "Total PnL" not in a]

    c = control[split_key]
    rows_html = []
    for arm in arms:
        m = arm[split_key]
        if arm["id"] == "control":
            verd, vnote = "CONTROL", "full Closed book"
        else:
            packed_cand = {"m_is": arm["m_is"], "m_oos": arm["m_oos"], "m_full": arm["m_full"]}
            packed_ctrl = {
                "m_is": control["m_is"],
                "m_oos": control["m_oos"],
                "m_full": control["m_full"],
            }
            verd, vnote = verdict_vs_control(packed_cand, packed_ctrl, split_key)

        def d(a: float, b: float) -> float:
            if not math.isfinite(a) or not math.isfinite(b):
                return float("nan")
            return a - b

        d_avg = d(m["avg_pnl"], c["avg_pnl"])
        d_wo = d(m["wo_max"], c["wo_max"])
        d_pf = d(m["pf"], c["pf"])
        d_wr = d(m["wr"], c["wr"])
        d_ann = d(m["ann_ror"], c["ann_ror"])
        d_dd = d(m["max_dd"], c["max_dd"])
        d_cal = d(m["calmar"], c["calmar"])

        cells = {
            "Arm": f'<td data-sort-value="{esc(arm["id"])}">{esc(arm["label"])}</td>',
            "N keep sym": f'<td data-sort-value="{arm["n_keep_sym"]}">{arm["n_keep_sym"]}</td>',
            "N": f'<td data-sort-value="{m["n"]}">{m["n"]}</td>',
            "WR %": f'<td data-sort-value="{m["wr"]}">{fmt_pct(m["wr"])}</td>',
            "Avg PnL %": f'<td data-sort-value="{m["avg_pnl"]}">{fmt_pct(m["avg_pnl"])}</td>',
            "WO_MAX %": f'<td data-sort-value="{m["wo_max"]}">{fmt_pct(m["wo_max"])}</td>',
            "PF": f'<td data-sort-value="{m["pf"]}">{fmt_n(m["pf"])}</td>',
            "Avg win %": f'<td data-sort-value="{m["avg_win"]}">{fmt_pct(m["avg_win"])}</td>',
            "Avg loss %": f'<td data-sort-value="{m["avg_loss"]}">{fmt_pct(m["avg_loss"])}</td>',
            "Ann ROR %": (
                f'<td data-sort-value="{m["ann_ror"] if math.isfinite(m["ann_ror"]) else ""}">'
                f'{fmt_pct(m["ann_ror"])}</td>'
            ),
            "Max DD %": (
                f'<td data-sort-value="{m["max_dd"] if math.isfinite(m["max_dd"]) else ""}">'
                f'{fmt_pct(m["max_dd"])}</td>'
            ),
            "Calmar": (
                f'<td data-sort-value="{m["calmar"] if math.isfinite(m["calmar"]) else ""}">'
                f'{fmt_n(m["calmar"])}</td>'
            ),
            "Avg days": f'<td data-sort-value="{m["avg_days"]}">{fmt_n(m["avg_days"], 1)}</td>',
            "Med days": f'<td data-sort-value="{m["med_days"]}">{fmt_n(m["med_days"], 1)}</td>',
            "Cap days": f'<td data-sort-value="{m["cap_days"]}">{fmt_n(m["cap_days"], 0)}</td>',
            "Profit / cap day": (
                f'<td data-sort-value="{m["ppc"] if math.isfinite(m["ppc"]) else ""}">'
                f'{format_money(m["ppc"]) if math.isfinite(m["ppc"]) else "—"}</td>'
            ),
            "Expectancy $": f'<td data-sort-value="{m["exp_d"]}">{format_money(m["exp_d"])}</td>',
            "Lose streak": f'<td data-sort-value="{m["lose_streak"]}">{m["lose_streak"]}</td>',
            "TPY": (
                f'<td data-sort-value="{m["tpy"] if math.isfinite(m["tpy"]) else ""}">'
                f'{fmt_n(m["tpy"])}</td>'
            ),
            "Δ Avg %": (
                f'<td data-sort-value="{d_avg if math.isfinite(d_avg) else ""}">'
                f'{fmt_n(d_avg)}</td>'
            ),
            "Δ WO_MAX": (
                f'<td data-sort-value="{d_wo if math.isfinite(d_wo) else ""}">'
                f'{fmt_n(d_wo)}</td>'
            ),
            "Δ PF": (
                f'<td data-sort-value="{d_pf if math.isfinite(d_pf) else ""}">'
                f'{fmt_n(d_pf)}</td>'
            ),
            "Δ WR": (
                f'<td data-sort-value="{d_wr if math.isfinite(d_wr) else ""}">'
                f'{fmt_n(d_wr)}</td>'
            ),
            "Δ Ann ROR": (
                f'<td data-sort-value="{d_ann if math.isfinite(d_ann) else ""}">'
                f'{fmt_n(d_ann)}</td>'
            ),
            "Δ Max DD": (
                f'<td data-sort-value="{d_dd if math.isfinite(d_dd) else ""}">'
                f'{fmt_n(d_dd)}</td>'
            ),
            "Δ Calmar": (
                f'<td data-sort-value="{d_cal if math.isfinite(d_cal) else ""}">'
                f'{fmt_n(d_cal)}</td>'
            ),
            "Verdict vs ctrl": (
                f'<td data-sort-value="{esc(verd)}" title="{esc(vnote)}">{esc(verd)}</td>'
            ),
        }
        cls = ' class="ctrl-row"' if arm["id"] == "control" else ""
        rows_html.append(
            f"<tr{cls}>" + "".join(cells[name] for name, _ in cols) + "</tr>"
        )

    thead = (
        "<tr>"
        + "".join(sortable_th(name, typ) for name, typ in cols)
        + "</tr>"
    )
    return (
        f"<h3>{esc(title)}</h3>"
        f'<p class="small">Click column headers to sort. Cash model ${cash_label(control)}.</p>'
        f'<div class="table-wrap"><table class="sortable"><thead>{thead}</thead>'
        f'<tbody>{"".join(rows_html)}</tbody></table></div>'
    )


def cash_label(control: dict[str, Any]) -> str:
    return f"{float(control.get('cash', RL_CASH)):,.0f}"


def write_stamp_html(
    out: Path,
    *,
    title: str,
    meta: str,
    warn: str,
    baseline_md_link: str,
    arms: list[dict[str, Any]],
    control: dict[str, Any],
    verdicts: dict[str, tuple[str, str, str, str]],
    extra_html: str = "",
) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    tables = [
        build_compare_table("FULL book", arms, control, "m_full"),
        build_compare_table("IS (entry < 2024-01-01)", arms, control, "m_is"),
        build_compare_table("OOS (entry ≥ 2024-01-01, report-only)", arms, control, "m_oos"),
    ]
    verd_rows = []
    for arm in arms:
        if arm["id"] == "control":
            continue
        tag, is_v, oos_v, note = verdicts[arm["id"]]
        verd_rows.append(
            f"<tr><td>{esc(arm['label'])}</td><td><strong>{esc(tag)}</strong></td>"
            f"<td>{esc(is_v)}</td><td>{esc(oos_v)}</td><td>{esc(note)}</td></tr>"
        )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{esc(title)}</title>
<style>
body {{ font-family: "Segoe UI", Tahoma, sans-serif; margin: 24px; color: #0f172a; background: #fff; max-width: 1200px; }}
h1 {{ font-size: 1.35rem; margin: 0 0 6px; }}
h2 {{ font-size: 1.1rem; margin: 24px 0 8px; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; }}
h3 {{ font-size: 1.0rem; margin: 18px 0 6px; }}
.sub, .meta, .small {{ color: #475569; font-size: 13px; line-height: 1.5; }}
.warn {{ background: #fff7ed; border: 1px solid #fdba74; padding: 10px 12px; border-radius: 6px; margin: 12px 0; font-size: 13px; }}
.info {{ background: #f8fafc; border: 1px solid #cbd5e1; padding: 10px 12px; border-radius: 6px; margin: 12px 0; font-size: 13px; }}
.table-wrap {{ overflow-x: auto; margin: 12px 0; }}
table {{ border-collapse: collapse; font-size: 12px; width: 100%; min-width: 900px; }}
th, td {{ border: 1px solid #e2e8f0; padding: 6px 8px; text-align: left; vertical-align: top; }}
th {{ background: #f1f5f9; }}
tr.ctrl-row {{ background: #f8fafc; }}
{SORTABLE_TH_CSS}
code {{ font-size: 12px; background: #f1f5f9; padding: 1px 4px; border-radius: 3px; }}
a {{ color: #1d4ed8; }}
</style>
</head>
<body>
<p class="meta">{meta}</p>
<h1>{esc(title)}</h1>
<div class="warn">{warn}</div>
<div class="info">Baseline: <a href="{esc(baseline_md_link)}">BASELINE.md</a>. Canonical metrics; no Sheet/Total PnL $ in HTML.</div>
{extra_html}
<h2>Verdicts (quality; OOS report-only)</h2>
<div class="table-wrap"><table class="sortable"><thead><tr>
{sortable_th("Arm", "text")}{sortable_th("Overall", "text")}{sortable_th("IS", "text")}{sortable_th("OOS", "text")}{sortable_th("Note", "text")}
</tr></thead><tbody>{"".join(verd_rows)}</tbody></table></div>
<h2>Compare tables</h2>
{"".join(tables)}
<footer class="small">Generated {date.today().isoformat()} · research-only · not DailyRun</footer>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path = out / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def md_split_line(m: dict[str, Any]) -> str:
    return (
        f"N={m['n']} WR={m['wr']:.1f}% Avg={m['avg_pnl']:.2f}% WO_MAX={m['wo_max']:.2f}% "
        f"PF={m['pf']:.2f} AnnROR={fmt_n(m['ann_ror'])} MaxDD={fmt_n(m['max_dd'])}"
    )


def write_summary_md(
    out: Path,
    *,
    stamp: str,
    hypothesis: str,
    knob: str,
    control_id: str,
    arms: list[dict[str, Any]],
    verdicts: dict[str, tuple[str, str, str, str]],
) -> Path:
    lines = [
        f"# SUMMARY — `{stamp}`",
        "",
        f"**Hypothesis:** {hypothesis}",
        f"**Single knob:** {knob}",
        f"**Control:** {control_id}",
        "**Status:** RESEARCH-ONLY — not gold / not DailyRun / not committed by this job.",
        "",
        "## IS / OOS quality",
        "",
    ]
    ctrl = next(a for a in arms if a["id"] == "control")
    lines.append(f"- **control IS:** {md_split_line(ctrl['m_is'])}")
    lines.append(f"- **control OOS:** {md_split_line(ctrl['m_oos'])}")
    for arm in arms:
        if arm["id"] == "control":
            continue
        tag, is_v, oos_v, note = verdicts[arm["id"]]
        lines.append(f"- **{arm['id']} IS:** {md_split_line(arm['m_is'])} → {is_v}")
        lines.append(f"- **{arm['id']} OOS:** {md_split_line(arm['m_oos'])} → {oos_v}")
        lines.append(f"  - **Overall (research):** **{tag}** — {note}")
    lines.extend(
        [
            "",
            "## Paths",
            "",
            f"- HTML: `drive/paul_experiments/{PARENT_STAMP}/{out.name}/compare.html`",
            f"- BASELINE: `drive/paul_experiments/{PARENT_STAMP}/{out.name}/BASELINE.md`",
            "",
        ]
    )
    path = out / "SUMMARY.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
