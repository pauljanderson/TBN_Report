#!/usr/bin/env python3
"""VZ adopt EXIT_ts20 research freeze + stop-width ABs — stamp 20260906.

New control = prior improve-priority EXIT_ts20 overlay identity:
  same full-univ Closed ``260906140457`` entries, exit_bars=20,
  stop atr 0.25, target 1.5R (rest of run_vz freeze unchanged).

One-knob stop arms vs that control (exit_bars frozen at 20).
Primary judge lens: Ann ROR + Max DD (+ Sharpe) on IS; AvgPnL%/PF reported.
OOS report-only. Research only — not gold / not DailyRun.
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import math
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

from vol_zone_break_retest import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    sortable_th,
)
from vz_improve_priority_ab_20260906 import (  # noqa: E402
    CLOSED_PATH,
    CONTROL_STAMP,
    ExitArm,
    apply_exit_arm,
    fmt_num,
    get_ohlc,
    load_house_closed,
    metrics_pack,
    oos_softens,
    split_trades,
    write_arm_csv,
)

DEFAULT_OUT = REPO / "drive" / "paul_experiments" / "vz_ts20_adopt_stop_ab_20260906"
PRIOR_STAMP = "vz_improve_priority_ab_20260906"
IS_CUT = date(2024, 1, 1)

CTRL_STOP_ATR = 0.25
CTRL_TARGET_R = 1.5
CTRL_EXIT_BARS = 20  # adopted EXIT_ts20
CTRL_EXIT_NAME = "EXIT_atr4_s025_r15_ts20"


@dataclass(frozen=True)
class StopArm:
    name: str
    label: str
    stop_atr: float


STOP_ARMS: list[StopArm] = [
    StopArm(
        "EXIT_stop_atr0125",
        "stop_atr_buffer 0.25→0.125 (tighter)",
        stop_atr=0.125,
    ),
    StopArm(
        "EXIT_stop_atr03",
        "stop_atr_buffer 0.25→0.30 (slightly wider)",
        stop_atr=0.30,
    ),
    StopArm(
        "EXIT_stop_atr05",
        "stop_atr_buffer 0.25→0.50 (wider — prior LEAN KEEP on ts40)",
        stop_atr=0.50,
    ),
    StopArm(
        "EXIT_stop_atr075",
        "stop_atr_buffer 0.25→0.75 (wider+)",
        stop_atr=0.75,
    ),
]


def _to_exit_arm(stop: StopArm) -> ExitArm:
    return ExitArm(
        name=stop.name,
        label=stop.label,
        hypothesis="one-knob stop vs adopted ts20 control",
        stop_atr=stop.stop_atr,
        target_r=CTRL_TARGET_R,
        exit_bars=CTRL_EXIT_BARS,
    )


def score_arm_is_capital(
    arm: str, m_is: dict, ctrl_is: dict, m_full: dict, ctrl_full: dict
) -> tuple[str, str]:
    """KEEP/HOLD/DISMISS on IS capital lens (Ann ROR + MaxDD + Sharpe)."""
    if arm in ("00_freeze", "CONTROL", "EXIT_ts20"):
        return (
            "CONTROL",
            "Adopted EXIT_ts20 research freeze (exit_bars=20; Paul Ann ROR/MaxDD lens)",
        )
    if m_is["n_signals"] < max(20, int(0.15 * ctrl_is["n_signals"])):
        return "DISMISS", f"IS sample collapsed ({m_is['n_signals']} vs ctrl {ctrl_is['n_signals']})"

    def d(a: float, b: float) -> float:
        if math.isfinite(a) and math.isfinite(b):
            return a - b
        return float("nan")

    d_ror = d(m_is["ann_ror"], ctrl_is["ann_ror"])
    d_dd = d(m_is["max_dd"], ctrl_is["max_dd"])  # lower better
    d_sh = d(m_is.get("sharpe", float("nan")), ctrl_is.get("sharpe", float("nan")))
    d_pnl = m_is["avg_pnl_pct"] - ctrl_is["avg_pnl_pct"]
    d_wr = (m_is["win_rate"] - ctrl_is["win_rate"]) * 100

    ror_up = math.isfinite(d_ror) and d_ror >= 3.0
    ror_soft = math.isfinite(d_ror) and d_ror >= 1.0
    ror_down = math.isfinite(d_ror) and d_ror <= -3.0
    dd_better = math.isfinite(d_dd) and d_dd <= -1.0
    dd_ok = (not math.isfinite(d_dd)) or d_dd <= 2.0
    dd_worse = math.isfinite(d_dd) and d_dd >= 3.0
    sh_up = math.isfinite(d_sh) and d_sh >= 0.05
    sh_ok = (not math.isfinite(d_sh)) or d_sh >= -0.05

    note = (
        f"IS ΔAnnROR {fmt_num(d_ror)}pp ΔMaxDD {fmt_num(d_dd) if not math.isfinite(d_dd) else f'{d_dd:+.2f}'}pp "
        f"ΔSharpe {fmt_num(d_sh) if not math.isfinite(d_sh) else f'{d_sh:+.2f}'} "
        f"(AvgPnL% d{d_pnl:+.2f} WR d{d_wr:+.1f}pp full-book context)"
    )

    if ror_up and dd_ok and sh_ok:
        return "LEAN KEEP", f"IS capital lift (Ann ROR up, MaxDD holds) — {note}"
    if ror_soft and dd_better and sh_ok:
        return "LEAN KEEP", f"IS MaxDD improves with Ann ROR holding up — {note}"
    if ror_up and dd_ok and sh_up:
        return "KEEP", f"IS Ann ROR + Sharpe up, MaxDD ok — {note}"
    if ror_down and dd_worse:
        return "DISMISS", f"IS Ann ROR down and MaxDD worse — {note}"
    if ror_down and d_pnl <= -0.15:
        return "DISMISS", f"IS Ann ROR and AvgPnL% both worse — {note}"
    if (math.isfinite(d_ror) and abs(d_ror) < 3.0) and (
        (not math.isfinite(d_dd)) or abs(d_dd) < 2.0
    ):
        return "HOLD", f"IS flat on Ann ROR / MaxDD — {note}"
    if ror_down or (dd_worse and not ror_up):
        return "DISMISS", f"IS capital regresses — {note}"
    return "HOLD", f"IS mixed on capital lens — {note}"


def build_html(
    out_path: Path,
    *,
    packs: list[dict[str, Any]],
    recommendation: str,
) -> None:
    ctrl = next(p for p in packs if p["arm"] == "00_freeze")

    def row_class(v: str) -> str:
        if v in ("KEEP", "LEAN KEEP"):
            return "keep"
        if v == "DISMISS":
            return "dismiss"
        if v == "HOLD":
            return "hold"
        return ""

    body_full = []
    for p in packs:
        m = p["full"]
        c = ctrl["full"]
        d_n = m["n_signals"] - c["n_signals"]
        d_wr = (m["win_rate"] - c["win_rate"]) * 100
        d_r = m["avg_r"] - c["avg_r"]
        d_pnl = m["avg_pnl_pct"] - c["avg_pnl_pct"]
        d_ror = (
            m["ann_ror"] - c["ann_ror"]
            if math.isfinite(m["ann_ror"]) and math.isfinite(c["ann_ror"])
            else float("nan")
        )
        d_dd = (
            m["max_dd"] - c["max_dd"]
            if math.isfinite(m["max_dd"]) and math.isfinite(c["max_dd"])
            else float("nan")
        )
        d_cal = (
            m["calmar"] - c["calmar"]
            if math.isfinite(m["calmar"]) and math.isfinite(c["calmar"])
            else float("nan")
        )
        d_sh = (
            m["sharpe"] - c["sharpe"]
            if math.isfinite(m.get("sharpe", float("nan")))
            and math.isfinite(c.get("sharpe", float("nan")))
            else float("nan")
        )
        body_full.append(
            "<tr class='{cls}'>"
            "<td>{arm}</td><td>{kind}</td><td>{knob}</td>"
            "<td>{n}</td><td>{wr}</td><td>{avg}</td><td>{avgr}</td><td>{med}</td>"
            "<td>{wo}</td><td>{ror}</td><td>{dd}</td><td>{cal}</td><td>{sh}</td>"
            "<td>{pf}</td><td>{adays}</td>"
            "<td>{dn}</td><td>{dwr}</td><td>{dr}</td><td>{dpnl}</td><td>{dror}</td>"
            "<td>{ddd}</td><td>{dcal}</td><td>{dsh}</td>"
            "<td>{verdict}</td><td>{why}</td><td>{mix}</td>"
            "</tr>".format(
                cls=row_class(p["verdict"]),
                arm=html_mod.escape(p["arm"]),
                kind=html_mod.escape(p["kind"]),
                knob=html_mod.escape(p["knob"]),
                n=m["n_signals"],
                wr=fmt_num(m["win_rate"] * 100, 1),
                avg=fmt_num(m["avg_pnl_pct"]),
                avgr=fmt_num(m["avg_r"]),
                med=fmt_num(m["med_pnl_pct"]),
                wo=fmt_num(m["wo_max"]),
                ror=fmt_num(m["ann_ror"]),
                dd=fmt_num(m["max_dd"]),
                cal=fmt_num(m["calmar"]),
                sh=fmt_num(m.get("sharpe", float("nan"))),
                pf=fmt_num(m["pf"]),
                adays=fmt_num(m["avg_days"], 1),
                dn=f"{d_n:+d}",
                dwr=f"{d_wr:+.1f}",
                dr=f"{d_r:+.2f}",
                dpnl=f"{d_pnl:+.2f}",
                dror=fmt_num(d_ror) if not math.isfinite(d_ror) else f"{d_ror:+.1f}",
                ddd=fmt_num(d_dd) if not math.isfinite(d_dd) else f"{d_dd:+.2f}",
                dcal=fmt_num(d_cal) if not math.isfinite(d_cal) else f"{d_cal:+.2f}",
                dsh=fmt_num(d_sh) if not math.isfinite(d_sh) else f"{d_sh:+.2f}",
                verdict=html_mod.escape(p["verdict"]),
                why=html_mod.escape(p["why"]),
                mix=html_mod.escape(m["exit_mix"]),
            )
        )

    body_split = []
    for p in packs:
        for slice_name, key in (("Full", "full"), ("IS", "is"), ("OOS", "oos")):
            m = p[key]
            c = ctrl[key]
            d_ror = (
                m["ann_ror"] - c["ann_ror"]
                if math.isfinite(m["ann_ror"]) and math.isfinite(c["ann_ror"])
                else float("nan")
            )
            d_dd = (
                m["max_dd"] - c["max_dd"]
                if math.isfinite(m["max_dd"]) and math.isfinite(c["max_dd"])
                else float("nan")
            )
            d_sh = (
                m["sharpe"] - c["sharpe"]
                if math.isfinite(m.get("sharpe", float("nan")))
                and math.isfinite(c.get("sharpe", float("nan")))
                else float("nan")
            )
            body_split.append(
                "<tr class='{cls}'><td>{arm}</td><td>{sl}</td><td>{n}</td><td>{wr}</td>"
                "<td>{avg}</td><td>{avgr}</td><td>{ror}</td><td>{dd}</td><td>{cal}</td>"
                "<td>{sh}</td><td>{pf}</td>"
                "<td>{dror}</td><td>{ddd}</td><td>{dsh}</td></tr>".format(
                    cls=row_class(p["verdict"]),
                    arm=html_mod.escape(p["arm"]),
                    sl=slice_name,
                    n=m["n_signals"],
                    wr=fmt_num(m["win_rate"] * 100, 1),
                    avg=fmt_num(m["avg_pnl_pct"]),
                    avgr=fmt_num(m["avg_r"]),
                    ror=fmt_num(m["ann_ror"]),
                    dd=fmt_num(m["max_dd"]),
                    cal=fmt_num(m["calmar"]),
                    sh=fmt_num(m.get("sharpe", float("nan"))),
                    pf=fmt_num(m["pf"]),
                    dror=fmt_num(d_ror) if not math.isfinite(d_ror) else f"{d_ror:+.1f}",
                    ddd=fmt_num(d_dd) if not math.isfinite(d_dd) else f"{d_dd:+.2f}",
                    dsh=fmt_num(d_sh) if not math.isfinite(d_sh) else f"{d_sh:+.2f}",
                )
            )

    th_full = "".join(
        [
            sortable_th("Arm", "text"),
            sortable_th("Kind", "text"),
            sortable_th("Knob", "text"),
            sortable_th("N", "num"),
            sortable_th("WR%", "num"),
            sortable_th("AvgPnL%", "num"),
            sortable_th("AvgR", "num"),
            sortable_th("MedPnL%", "num"),
            sortable_th("WO_MAX%", "num"),
            sortable_th("Ann ROR%", "num"),
            sortable_th("Max DD%", "num"),
            sortable_th("Calmar", "num"),
            sortable_th("Sharpe", "num"),
            sortable_th("PF", "num"),
            sortable_th("AvgDays", "num"),
            sortable_th("ΔN", "num"),
            sortable_th("ΔWR pp", "num"),
            sortable_th("ΔAvgR", "num"),
            sortable_th("ΔPnL%", "num"),
            sortable_th("ΔAnnROR pp", "num"),
            sortable_th("ΔMaxDD pp", "num"),
            sortable_th("ΔCalmar", "num"),
            sortable_th("ΔSharpe", "num"),
            sortable_th("Verdict", "text"),
            sortable_th("Why", "text"),
            sortable_th("Exit mix", "text"),
        ]
    )
    th_split = "".join(
        [
            sortable_th("Arm", "text"),
            sortable_th("Slice", "text"),
            sortable_th("N", "num"),
            sortable_th("WR%", "num"),
            sortable_th("AvgPnL%", "num"),
            sortable_th("AvgR", "num"),
            sortable_th("Ann ROR%", "num"),
            sortable_th("Max DD%", "num"),
            sortable_th("Calmar", "num"),
            sortable_th("Sharpe", "num"),
            sortable_th("PF", "num"),
            sortable_th("ΔAnnROR pp", "num"),
            sortable_th("ΔMaxDD pp", "num"),
            sortable_th("ΔSharpe", "num"),
        ]
    )

    rec_cls = "hold"
    if "LEAN KEEP" in recommendation or recommendation.startswith("KEEP"):
        rec_cls = "keep"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>VZ ts20 adopt + stop AB — vz_ts20_adopt_stop_ab_20260906</title>
<style>
  body {{ margin:0; padding:28px; font-family:"Segoe UI",Georgia,serif; background:#fafaf8; color:#1a1a18; }}
  .wrap {{ max-width:1680px; margin:0 auto; }}
  h1 {{ font-size:1.45rem; }}
  h2 {{ font-size:1.15rem; margin-top:1.8rem; }}
  .muted {{ color:#5c5c56; }}
  .callout {{ background:#eef2ff; border:1px solid #c7d2fe; padding:14px 16px; margin:1rem 0; }}
  .rec {{ background:#f0f0ea; border:1px solid #d8d8d0; padding:14px 16px; margin:1rem 0; }}
  .rec.keep {{ background:#ecfdf5; }}
  .rec.hold {{ background:#fffbeb; }}
  table.sortable {{ border-collapse:collapse; width:100%; font-size:12.5px; margin-bottom:1.4rem; }}
  table.sortable th, table.sortable td {{ border:1px solid #d8d8d0; padding:5px 7px; vertical-align:top; }}
  table.sortable th {{ background:#f0f0ea; }}
  tr.keep {{ background:#ecfdf5; }}
  tr.dismiss {{ background:#fef2f2; }}
  tr.hold {{ background:#fffbeb; }}
  code {{ font-size:0.92em; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<div class="wrap">
  <h1>VZ ts20 adopt + stop AB — vz_ts20_adopt_stop_ab_20260906</h1>

  <div class="callout">
    <p><strong>What you asked</strong></p>
    <p>Adopt <code>EXIT_ts20</code> as the new Volume Zone (VZ) research freeze, then
    re-run stop-width A/Bs (<code>EXIT_stop_atr*</code>) against that new control to see
    if stops still improve in-sample.</p>
    <p><strong>In plain English</strong></p>
    <p>We shortened the default hold to 20 days (Paul prefers annual return and drawdown
    over average trade profit). Then we only changed how far the stop sits under the
    zone — tighter or wider — and asked whether any stop change still helps on the
    capital scorecard. Out-of-sample is report-only. Research only — not DailyRun.</p>
  </div>

  <p class="muted">
    Research only (not gold / not DailyRun). New control = adopted
    <code>{CTRL_EXIT_NAME}</code> overlay on full-univ Closed <code>{CONTROL_STAMP}</code>
    (same entries as improve-priority; exit_bars=<b>20</b>, stop 0.25·ATR, 1.5R, cd=10).
    Prior expectancy/AvgPnL% DISMISS of ts20 stays labeled historically; adopt lens =
    Ann ROR / Max DD. IS = entry &lt; 2024-01-01; OOS report-only.
    Click column headers to sort. Overlay Ann ROR / Max DD / Calmar / Sharpe via
    $45k sheet / $500k seed (shared compare_format helpers).
  </p>

  <div class="rec {rec_cls}">
    <strong>Recommendation</strong>
    <pre style="white-space:pre-wrap;margin:0.6rem 0 0;font-family:inherit">{html_mod.escape(recommendation)}</pre>
  </div>

  <h2>One-knob stop arms vs ts20 control (full book)</h2>
  <p class="muted">Primary judge = IS Ann ROR + Max DD (+ Sharpe). AvgPnL%/PF reported. Click headers to sort.</p>
  <table class="sortable"><thead><tr>{th_full}</tr></thead><tbody>
  {''.join(body_full)}
  </tbody></table>

  <h2>IS / OOS / Full (Closed overlay)</h2>
  <p class="muted">OOS is report-only — do not retune if OOS softens. Click column headers to sort.</p>
  <table class="sortable"><thead><tr>{th_split}</tr></thead><tbody>
  {''.join(body_split)}
  </tbody></table>
</div>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    out_path.write_text(html, encoding="utf-8")


def recommend(packs: list[dict[str, Any]]) -> str:
    ctrl = next(p for p in packs if p["arm"] == "00_freeze")
    lines: list[str] = []
    lines.append(
        "New research freeze control: **EXIT_ts20** / "
        f"`{CTRL_EXIT_NAME}` (exit_bars=20, stop 0.25·ATR, 1.5R) on full-univ Closed "
        f"`{CONTROL_STAMP}` — adopted from `{PRIOR_STAMP}` on Paul capital scorecard "
        "(Ann ROR / Max DD). Historical expectancy/AvgPnL% DISMISS of ts20 remains labeled. "
        "Not gold / not DailyRun-wired."
    )

    keeps = [p for p in packs if p["verdict"] in ("KEEP", "LEAN KEEP")]
    final_keeps: list[dict[str, Any]] = []
    for p in keeps:
        if oos_softens(p["oos"], ctrl["oos"]):
            p["verdict"] = "HOLD"
            p["why"] = (
                p["why"]
                + " | OOS softens vs control OOS — HOLD (do not adopt / do not retune OOS)"
            )
            lines.append(f"{p['arm']}: IS LEAN KEEP -> HOLD after OOS soften gate.")
        else:
            final_keeps.append(p)

    if final_keeps:
        names = ", ".join(p["arm"] for p in final_keeps)
        lines.append(
            f"Research LEAN KEEP vs ts20 (not gold / not DailyRun): {names}."
        )
    else:
        lines.append(
            "No clear one-knob stop LEAN KEEP vs ts20 on IS Ann ROR / Max DD "
            "(after OOS soften gate)."
        )

    lines.append(
        f"HOLD count: {len([p for p in packs if p['verdict']=='HOLD'])}; "
        f"DISMISS count: {len([p for p in packs if p['verdict']=='DISMISS'])}; "
        f"LEAN KEEP count: {len([p for p in packs if p['verdict'] in ('KEEP','LEAN KEEP')])}."
    )
    lines.append(
        "Selection bias labeled (ts20 chosen from improve-priority on same Closed book "
        "via Ann ROR/MaxDD preference after AvgPnL% DISMISS). Research only."
    )

    for p in packs:
        if p["arm"] == "00_freeze":
            continue
        mi, ci = p["is"], ctrl["is"]
        d_ror = (
            mi["ann_ror"] - ci["ann_ror"]
            if math.isfinite(mi["ann_ror"]) and math.isfinite(ci["ann_ror"])
            else float("nan")
        )
        d_dd = (
            mi["max_dd"] - ci["max_dd"]
            if math.isfinite(mi["max_dd"]) and math.isfinite(ci["max_dd"])
            else float("nan")
        )
        d_sh = (
            mi["sharpe"] - ci["sharpe"]
            if math.isfinite(mi.get("sharpe", float("nan")))
            and math.isfinite(ci.get("sharpe", float("nan")))
            else float("nan")
        )
        lines.append(
            f"  - {p['arm']}: {p['verdict']} — IS AnnROR {fmt_num(mi['ann_ror'])} "
            f"(d{fmt_num(d_ror) if not math.isfinite(d_ror) else f'{d_ror:+.1f}'}) "
            f"MaxDD {fmt_num(mi['max_dd'])} "
            f"(d{fmt_num(d_dd) if not math.isfinite(d_dd) else f'{d_dd:+.2f}'}) "
            f"Sharpe {fmt_num(mi.get('sharpe', float('nan')))} "
            f"(d{fmt_num(d_sh) if not math.isfinite(d_sh) else f'{d_sh:+.2f}'}) "
            f"| AvgPnL% {mi['avg_pnl_pct']:.2f} PF {fmt_num(mi['pf'])} "
            f"| OOS AnnROR {fmt_num(p['oos']['ann_ror'])} MaxDD {fmt_num(p['oos']['max_dd'])}"
        )
    return "\n".join(lines)


def write_baseline(out: Path) -> None:
    md = f"""# VZ EXIT_ts20 adopt + stop AB — research only (NOT gold)

**Stamp folder:** `drive/paul_experiments/vz_ts20_adopt_stop_ab_20260906/`  
**Prior stamp:** `drive/paul_experiments/{PRIOR_STAMP}/`  
**Control pin:** full-univ Closed `{CONTROL_STAMP}` + adopted **EXIT_ts20**  
**Status:** Research candidate — **not** gold, **not** DailyRun-wired.

## What you asked

Adopt `EXIT_ts20` as the new VZ research freeze, then rerun `EXIT_stop_atr*` ABs vs that
new control to see if stops improve IS.

## In plain English

Same full-universe entries; hold cut to 20 days (Paul prefers annual return and drawdown
over average trade profit). Then test only stop distance under the zone. OOS report-only.

## Adoption / selection note

- Prior improve-priority scored `EXIT_ts20` **DISMISS** on expectancy / Avg PnL% vs ts40.
- Paul capital scorecard preference: **Ann ROR / Max DD** (ts20 lifted Ann ROR and cut Max DD).
- This stamp **adopts EXIT_ts20** as the research freeze control for stop ABs.
- Historical AvgPnL% DISMISS remains labeled — do not erase it.
- Selection bias: ts20 chosen after seeing improve-priority on the same Closed book.

## Frozen control (identity)

| Knob | Value |
|------|-------|
| Universe | Full-univ Closed `{CONTROL_STAMP}` (1118 symbols; same book as ImprovePriority) |
| House univ note | DailyRun/house pin remains `VZ_universe.csv` (VZ_new56); this AB dual-books full-univ evidence |
| zone_kinds | HL only |
| first_retest_only | true |
| min_touches | ≥1 |
| retest_eps_pct | 0.005 |
| lookback / retest_window | 126 / 63 |
| entry_on | next_open |
| exit | `{CTRL_EXIT_NAME}` — zone.lo−0.25·ATR, 1.5R, **time-stop 20**; min_atr_pct=4.0 |
| require_hvn_overlap | false |
| trade_side | long |
| cooldown_after_target_days | **10** |
| Sheet notional | $45,000 |

## Arms (one knob = stop_atr_buffer; exit_bars frozen at 20)

| Arm | Knob |
|-----|------|
| `00_freeze` / EXIT_ts20 | stop 0.25 (control) |
| `EXIT_stop_atr0125` | 0.125 (tighter) |
| `EXIT_stop_atr03` | 0.30 (slightly wider) |
| `EXIT_stop_atr05` | 0.50 (wider; prior LEAN KEEP on old ts40 control) |
| `EXIT_stop_atr075` | 0.75 (wider+) |

## Chronologic split

- IS = `entry_date < 2024-01-01` — **KEEP/HOLD/DISMISS judged here** (Ann ROR + Max DD + Sharpe)
- OOS = `entry_date >= 2024-01-01` — **report-only; do not retune**

## Method

- Closed overlay exit replay on `{CONTROL_STAMP}` entries.
- Control = re-sim EXIT_ts20 (exit_bars=20, stop 0.25, target 1.5R).
- Stop arms change only `stop_atr_buffer`; everything else frozen at ts20 control.

## Outputs

- `compare.html` — sortable canonical metrics + Ann ROR + Max DD + Calmar + Sharpe + IS/OOS
- `metrics.csv` / arm Closed CSVs
- `BASELINE.md` / `AB_PLAN.md`

## DailyRun

**Not wired.** Research pin docs updated; `DailyRun.bat` untouched.
"""
    (out / "BASELINE.md").write_text(md, encoding="utf-8")
    plan = """# AB plan — VZ ts20 adopt + stop width

## Control

Adopt EXIT_ts20 (exit_bars=20, stop 0.25·ATR, 1.5R) on full-univ Closed 260906140457.

## Arms (overlay)

1. EXIT_stop_atr0125 — tighter
2. EXIT_stop_atr03 — slight widen (optional cheap)
3. EXIT_stop_atr05 — wider
4. EXIT_stop_atr075 — wider+

Judge IS on Ann ROR + Max DD (+ Sharpe). OOS report-only.
"""
    (out / "AB_PLAN.md").write_text(plan, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--closed", type=Path, default=CLOSED_PATH)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    write_baseline(out)

    print(f"Loading Closed {args.closed}")
    base = load_house_closed(args.closed)
    print(f"  trades={len(base)}")
    if not base:
        print("ERROR: no trades")
        return 1

    syms = sorted({t["symbol"] for t in base})
    print(f"Warming OHLC for {len(syms)} symbols…")
    for s in syms:
        get_ohlc(s)

    ctrl_arm = ExitArm(
        name="EXIT_ts20",
        label="adopted control: exit_bars=20, stop 0.25, 1.5R",
        hypothesis="Paul capital scorecard Ann ROR/MaxDD adopt",
        stop_atr=CTRL_STOP_ATR,
        target_r=CTRL_TARGET_R,
        exit_bars=CTRL_EXIT_BARS,
    )

    packs: list[dict[str, Any]] = []

    def add_pack(
        arm: str,
        kind: str,
        knob: str,
        trades: list[dict[str, Any]],
        *,
        verdict: str = "",
        why: str = "",
    ) -> None:
        full = metrics_pack(trades)
        is_rows, oos_rows = split_trades(trades)
        is_m = metrics_pack(is_rows)
        oos_m = metrics_pack(oos_rows)
        if not verdict:
            if packs:
                verdict, why = score_arm_is_capital(
                    arm, is_m, packs[0]["is"], full, packs[0]["full"]
                )
            else:
                verdict, why = "CONTROL", "reference"
        packs.append(
            {
                "arm": arm,
                "kind": kind,
                "knob": knob,
                "full": full,
                "is": is_m,
                "oos": oos_m,
                "verdict": verdict,
                "why": why,
                "trades": trades,
            }
        )
        write_arm_csv(out / f"closed_{arm}.csv", trades)
        print(
            f"  {arm}: N={full['n_signals']} WR={full['win_rate']*100:.1f}% "
            f"Avg={full['avg_pnl_pct']:.2f} ROR={fmt_num(full['ann_ror'])} "
            f"DD={fmt_num(full['max_dd'])} IS_ROR={fmt_num(is_m['ann_ror'])} "
            f"IS_DD={fmt_num(is_m['max_dd'])} -> {verdict}"
        )

    print("Building ts20 control overlay…")
    ctrl_trades = apply_exit_arm(base, ctrl_arm)
    add_pack(
        "00_freeze",
        "CONTROL",
        f"{CTRL_EXIT_NAME} (exit_bars=20)",
        ctrl_trades,
        verdict="CONTROL",
        why="Adopted EXIT_ts20 research freeze (Paul Ann ROR/MaxDD lens)",
    )

    exit_arms = [_to_exit_arm(s) for s in STOP_ARMS]
    print(f"Replaying {len(exit_arms)} stop arms ({args.workers} workers)…")
    exit_results: dict[str, list[dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {ex.submit(apply_exit_arm, base, arm): arm for arm in exit_arms}
        for fut in as_completed(futs):
            arm = futs[fut]
            trades = fut.result()
            exit_results[arm.name] = trades
            print(f"  done {arm.name} N={len(trades)}")

    for arm in exit_arms:
        add_pack(arm.name, "EXIT", arm.label, exit_results[arm.name])

    ctrl = packs[0]
    for p in packs[1:]:
        v, w = score_arm_is_capital(p["arm"], p["is"], ctrl["is"], p["full"], ctrl["full"])
        p["verdict"], p["why"] = v, w

    rec = recommend(packs)
    html_path = out / "compare.html"
    build_html(html_path, packs=packs, recommendation=rec)

    with (out / "metrics.csv").open("w", newline="", encoding="utf-8") as f:
        cols = [
            "arm",
            "kind",
            "verdict",
            "slice",
            "N",
            "WR_pct",
            "AvgPnL_pct",
            "AvgR",
            "MedPnL_pct",
            "WO_MAX_pct",
            "Ann_ROR_pct",
            "Max_DD_pct",
            "Calmar",
            "Sharpe",
            "Sharpe_source",
            "PF",
            "Sheet_PnL",
            "AvgDays",
            "why",
        ]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for p in packs:
            for sl, key in (("full", "full"), ("IS", "is"), ("OOS", "oos")):
                m = p[key]
                w.writerow(
                    {
                        "arm": p["arm"],
                        "kind": p["kind"],
                        "verdict": p["verdict"],
                        "slice": sl,
                        "N": m["n_signals"],
                        "WR_pct": round(m["win_rate"] * 100, 3),
                        "AvgPnL_pct": round(m["avg_pnl_pct"], 4),
                        "AvgR": round(m["avg_r"], 4),
                        "MedPnL_pct": round(m["med_pnl_pct"], 4),
                        "WO_MAX_pct": round(m["wo_max"], 4),
                        "Ann_ROR_pct": m["ann_ror"] if math.isfinite(m["ann_ror"]) else "",
                        "Max_DD_pct": m["max_dd"] if math.isfinite(m["max_dd"]) else "",
                        "Calmar": m["calmar"] if math.isfinite(m["calmar"]) else "",
                        "Sharpe": m.get("sharpe", "")
                        if isinstance(m.get("sharpe"), (int, float))
                        and math.isfinite(float(m.get("sharpe")))
                        else "",
                        "Sharpe_source": m.get("sharpe_source", ""),
                        "PF": round(m["pf"], 4),
                        "Sheet_PnL": round(m["sheet_pnl"], 2),
                        "AvgDays": round(m["avg_days"], 3),
                        "why": p["why"],
                    }
                )

    base_md = out / "BASELINE.md"
    text = base_md.read_text(encoding="utf-8")
    marker = "\n## Auto results\n"
    if marker in text:
        text = text.split(marker)[0].rstrip() + "\n"
    text += marker + "\n```\n" + rec + "\n```\n"
    base_md.write_text(text, encoding="utf-8")

    print("\n=== RECOMMENDATION ===")
    try:
        print(rec)
    except UnicodeEncodeError:
        print(rec.encode("ascii", "replace").decode("ascii"))
    print(f"\nWrote {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
