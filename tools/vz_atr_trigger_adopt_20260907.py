#!/usr/bin/env python3
"""Volume Zone (VZ) operational adopt — ATR% gate at trigger.

Paul override after HOLD-quality A/B
``vz_atr_trigger_vs_entry_ab_20260907``. Not KEEP. Not gold.
House DailyRun now uses trigger ATR% >= 4; entry gate off.

Writes ``drive/paul_experiments/vz_atr_trigger_adopt_20260907/``
(BASELINE.md + adopt.html), freezes reconcile golden, updates writeup pin.
"""
from __future__ import annotations

import html as html_mod
import json
import math
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

from compare_format import format_money  # noqa: E402
from vz_atr_trigger_vs_entry_ab_20260907 import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    _exit_mix_s,
    audit_gate_fields,
    find_audit_in_dir,
    find_closed_in_dir,
    find_equity_in_dir,
    find_report_in_dir,
    find_summary_in_dir,
    fmt_delta,
    fmt_num,
    load_closed,
    load_summary_pack,
    overlap_counts,
    pack_row_html,
    read_pin,
    read_report_row,
    score_pack,
    sortable_th,
)
from vz_lookback_zonegap_ab_20260907 import oos_softens  # noqa: E402

STAMP = "vz_atr_trigger_adopt_20260907"
OUT_DIR = REPO / "drive" / "paul_experiments" / STAMP
HOUSE_PIN_PATH = REPO / "drive" / "VZ_house_last_run_ts.txt"
CTRL_PIN = "260907143957"  # last entry-priced house pin (AB control)
CFG_PATH = REPO / "drive" / "paul_experiments" / "reconcile_gate_config.json"
WRITEUP = REPO / "tools" / "_gen_system_writeups.py"
IS_CUT = date(2024, 1, 1)

ORIGINAL_REQUEST = (
    "the numbers are all slightly lower when using ATR_PCT at trigger vs. the "
    "control of ATR_PCT_AT_ENTRY. but it is far easier to know on the trigger "
    "date if we want to enter the trade or not if we use TRIGGER instead of "
    "entry. agree? if so, let's adopt this change"
)

PLAIN_ENGLISH = (
    "Volume Zone (VZ) waits for a high-volume price shelf, then buys the first "
    "bounce. The live scanner sees the signal at today's close, but the house "
    "fill is tomorrow's open — a price we do not have yet. An earlier test "
    "compared requiring Average True Range (ATR, a typical daily swing) to be "
    "at least 4% of that unknown fill versus 4% of today's close. Quality was "
    "slightly worse at the trigger (HOLD, not KEEP). Paul still asked to switch "
    "so the scanner can decide the same day. This job flips DailyRun to the "
    "trigger 4% floor only. We are not calling this gold and we did not retune "
    "the 4% number."
)


def _f(v: Any, default: float = float("nan")) -> float:
    if v is None or v == "":
        return default
    s = str(v).strip().replace("%", "").replace(",", "").replace("$", "")
    if not s or s.upper() in {"N/A", "NONE", "NAN"}:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def adopted_freeze_ok(fields: dict[str, Any]) -> tuple[bool, str]:
    checks = [
        (str(fields.get("exit_name") or "") == "EXIT_atr4_s025_r15_ts20", "exit_name"),
        (abs(float(fields.get("exit_bars") or 0) - 20) < 0.1, "exit_bars"),
        (abs(float(fields.get("stop_atr") or 0) - 0.25) < 1e-6, "stop_atr"),
        (abs(float(fields.get("target_r") or 0) - 1.5) < 1e-6, "target_r"),
        (abs(float(fields.get("lookback") or 0) - 126) < 0.1, "lookback"),
        (abs(float(fields.get("rw") or 0) - 63) < 0.1, "rw"),
        (str(fields.get("entry_on") or "").lower() == "next_open", "entry_on"),
        (abs(float(fields.get("min_atr_entry") or 0) - 0.0) < 1e-6, "min_atr_entry"),
        (abs(float(fields.get("min_atr_trigger") or 0) - 4.0) < 1e-6, "min_atr_trigger"),
        (abs(float(fields.get("cd") or 0) - 10) < 0.1, "cooldown"),
    ]
    bad = [name for ok, name in checks if not ok]
    if bad:
        return False, "adopted freeze mismatch: " + ", ".join(bad)
    return True, "house freeze matches trigger-ATR% 4 / entry gate 0 / EXIT_atr4_s025_r15_ts20"


def freeze_golden(pin: str) -> Path:
    dest = REPO / "drive" / "paul_experiments" / f"vz_baseline_{pin}" / "engine_closed"
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    for src in (REPO / "drive").glob(f"VZ_*_{pin}.*"):
        shutil.copy2(src, dest / src.name)
        copied += 1
    closed = dest / f"VZ_Closed_{pin}.csv"
    if not closed.is_file():
        raise FileNotFoundError(f"golden Closed missing after copy: {closed}")
    n_closed = sum(1 for _ in closed.open(encoding="utf-8-sig")) - 1
    readme = f"""# VZ reconcile baseline freeze — stamp `{pin}`

Frozen **engine Closed** for the DailyRun reconcile gate after the operational
adopt of the Average True Range (ATR) % floor at **trigger close**.

**Do not invent trades** — this folder is a copy of a real `drive/VZ_*_{pin}.*`
house run (`run_vz.bat` defaults after the trigger-gate adopt).

## Stamp / date

| Item | Value |
|---|---|
| Engine stamp | **`{pin}`** (ATR% at trigger adopt 2026-09-07) |
| Golden Closed | `engine_closed/VZ_Closed_{pin}.csv` (**{n_closed}** trades) |
| Universe | Paul78.142 — [`drive/universes/VZ_universe.csv`](../../universes/VZ_universe.csv) |
| Gate config | `../reconcile_gate_config.json` → system **`VZ`** |
| Runner | `run_vz.bat` → `rocket_tbn -v vz_mode=true` |
| Adopt stamp | [`../vz_atr_trigger_adopt_20260907/`](../vz_atr_trigger_adopt_20260907/) |
| Prior golden | `260907093231` (entry-priced 4% / PO adopt s025) |

## Why this stamp

Paul asked to measure the 4% ATR floor at the trigger close so the scanner can
decide on the signal date. Quality A/B vs entry-priced 4% was **HOLD** (slightly
worse). This is an operational / scanner-live override — **not KEEP, not gold**.
Entry gate is off (one gate only).

## Levers (house freeze)

| Lever | Value |
|---|---|
| Universe | Paul78.142 (142) |
| zone_kinds | HL only |
| first_retest_only | true |
| min_touches | ≥1 |
| retest_eps_pct | 0.005 |
| lookback / retest_window | 126 / 63 |
| entry_on | next_open |
| exit | `EXIT_atr4_s025_r15_ts20` |
| stop_atr | 0.25 |
| target_r | 1.5 |
| exit_bars | 20 |
| min_atr_pct_at_trigger | **4.0** (atr4 = ATR14/trigger_close ≥ 4%) |
| min_atr_pct_at_entry | **0** (off) |
| require_hvn_overlap | false |
| trade_side | long |
| cooldown_after_target_days | 10 |

## Layout

```
vz_baseline_{pin}/
  README.md
  engine_closed/
    VZ_Closed_{pin}.csv
    …
```

Source originals remain under `drive/VZ_*_{pin}.*`.
"""
    (dest.parent / "README.md").write_text(readme, encoding="utf-8")
    print(f"[freeze] {dest} copied={copied} closed_n={n_closed}", flush=True)
    return closed


def update_reconcile_config(pin: str, n_closed: int) -> None:
    c = json.loads(CFG_PATH.read_text(encoding="utf-8"))
    for s in c["systems"]:
        if s["id"] == "VZ":
            s["baseline"] = {
                "mode": "single_file",
                "path": (
                    f"drive/paul_experiments/vz_baseline_{pin}/"
                    f"engine_closed/VZ_Closed_{pin}.csv"
                ),
            }
            s["freeze_note"] = (
                f"Paul78.142 + EXIT_atr4_s025_r15_ts20 / stop 0.25 / ts20 / cd10; "
                f"atr4 = 4% ATR floor at trigger close (entry gate off); "
                f"operational adopt 2026-09-07 after HOLD AB; golden {pin}."
            )
            break
    note = c.get("notes", "")
    marker = f"VZ re-frozen {pin}"
    if marker not in note:
        c["notes"] = (
            note.rstrip()
            + f" {marker} after operational adopt ATR% at trigger "
            f"(prior 260907093231 entry-priced 4%)."
        )
    CFG_PATH.write_text(json.dumps(c, indent=2) + "\n", encoding="utf-8")
    print(f"[cfg] VZ golden -> {pin} (n={n_closed})", flush=True)


def update_writeup_golden(pin: str) -> None:
    text = WRITEUP.read_text(encoding="utf-8")
    new_cell = (
        f'"<code>drive/paul_experiments/vz_baseline_{pin}/</code> '
        f'(trigger-gate adopt <code>vz_atr_trigger_adopt_20260907</code>; '
        f'prior PO s025 <code>vz_baseline_260907093231</code>)"'
    )
    if f"vz_baseline_{pin}" in text:
        print(f"[writeup] already points at {pin}", flush=True)
        return
    old_cells = [
        '"<code>drive/paul_experiments/vz_baseline_260907093231/</code> (PO adopt <code>vz_tbn_adopt_s025_paul78_20260907</code>; trigger-gate adopt will re-freeze after house pin)"',
        '"<code>drive/paul_experiments/vz_baseline_260907093231/</code> (PO adopt <code>vz_tbn_adopt_s025_paul78_20260907</code>)"',
    ]
    updated = False
    for old in old_cells:
        if old in text:
            text = text.replace(old, new_cell)
            updated = True
            break
    if not updated:
        print("[writeup] WARN: no 260907093231 freeze line to replace", flush=True)
        return
    WRITEUP.write_text(text, encoding="utf-8")
    print(f"[writeup] freeze line -> {pin}", flush=True)


def write_compare_html(
    path: Path,
    *,
    pin: str,
    packs: list[dict[str, Any]],
    ov: dict[str, Any],
    house_note: str,
) -> None:
    ctrl = next(p for p in packs if p["arm"] == "CONTROL")
    th = "".join(
        sortable_th(a, b)
        for a, b in [
            ("Arm", "text"),
            ("Knob", "text"),
            ("N", "num"),
            ("Win %", "num"),
            ("Avg PnL %", "num"),
            ("AvgR", "num"),
            ("Book AVG_PNL_PCT_WO_MAX", "num"),
            ("Ann ROR %", "num"),
            ("Max DD %", "num"),
            ("Calmar", "num"),
            ("Sharpe", "num"),
            ("Profit factor", "num"),
            ("Expectancy $", "num"),
            ("Avg win %", "num"),
            ("Avg loss %", "num"),
            ("Win/Loss ratio (count)", "num"),
            ("Win/Loss ratio $", "num"),
            ("Avg days held", "num"),
            ("Median days held", "num"),
            ("P90 days held", "num"),
            ("Capital days", "num"),
            ("Profit per capital day", "num"),
            ("Losing streak", "num"),
            ("Pct PnL max symbol", "num"),
            ("Pct PnL max trade", "num"),
            ("Mean FIT Robust", "num"),
            ("Mean Paul Score", "num"),
            ("Mean AVG_PNL_PCT_WO_MAX", "num"),
            ("Mean OUTLIER_PCT_OF_WINS", "num"),
            ("Mean AVG_TRADES_PER_YEAR", "num"),
            ("ΔN", "num"),
            ("ΔWR pp", "num"),
            ("ΔAvgR", "num"),
            ("ΔPnL%", "num"),
            ("ΔAnnROR pp", "num"),
            ("ΔMaxDD pp", "num"),
            ("ΔPF", "num"),
            ("Verdict", "text"),
            ("Why / OOS note", "text"),
            ("Exit mix", "text"),
        ]
    )
    body_is = "\n".join(pack_row_html(p, ctrl, "is") for p in packs)
    body_oos = "\n".join(pack_row_html(p, ctrl, "oos") for p in packs)
    body_full = "\n".join(pack_row_html(p, ctrl, "full") for p in packs)
    adopted = next(p for p in packs if p["arm"] != "CONTROL")
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>VZ ATR% at trigger — operational adopt 20260907</title>
<style>
  body {{ margin:0; padding:28px; font-family:"Segoe UI",Georgia,serif; background:#fafaf8; color:#1a1a18; }}
  .wrap {{ max-width:1800px; margin:0 auto; }}
  h1 {{ font-size:1.4rem; }}
  h2 {{ font-size:1.12rem; margin-top:1.8rem; }}
  .muted {{ color:#5c5c56; }}
  .callout {{ background:#eef2ff; border:1px solid #c7d2fe; padding:14px 16px; margin:1rem 0; }}
  .rec {{ background:#fffbeb; border:1px solid #fde68a; padding:14px 16px; margin:1rem 0; }}
  table.sortable {{ border-collapse:collapse; width:100%; font-size:12px; margin-bottom:1.4rem; }}
  table.sortable th, table.sortable td {{ border:1px solid #d8d8d0; padding:5px 7px; vertical-align:top; }}
  table.sortable th {{ background:#f0f0ea; }}
  tr.keep {{ background:#ecfdf5; }}
  tr.dismiss {{ background:#fef2f2; }}
  tr.hold {{ background:#fffbeb; }}
  blockquote {{ margin:0.4rem 0 0.8rem; color:#334155; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<div class="wrap">
  <h1>Volume Zone (VZ) Average True Range (ATR) % at trigger — operational adopt</h1>
  <p class="muted">Stamp {STAMP} · New house pin {html_mod.escape(pin)} ·
  DailyRun default flipped · <strong>not KEEP · not gold</strong></p>
  <div class="callout">
    <p><strong>What you asked</strong></p>
    <blockquote>{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
    <p><strong>In plain English</strong></p>
    <p>{html_mod.escape(PLAIN_ENGLISH)}</p>
  </div>
  <div class="rec">
    <p><strong>Honesty</strong></p>
    <ul>
      <li>Prior A/B <code>vz_atr_trigger_vs_entry_ab_20260907</code> was
      <strong>HOLD on IS quality</strong> (WR 60.5% vs 60.9%, AvgR 0.489 vs 0.535;
      OOS also slightly softer). This adopt is a <strong>product / scanner-live
      choice</strong>, not a quality KEEP and not walk-forward gold.</li>
      <li>Exit token stays <code>EXIT_atr4_s025_r15_ts20</code>.
      <strong>atr4</strong> now means ATR14 / trigger_close ≥ 4%, not entry fill.</li>
      <li>One gate only: <code>vz_min_atr_pct_at_trigger=4</code>,
      <code>vz_min_atr_pct_at_entry=0</code>.</li>
      <li>Choosing after the A/B table on the same book is still
      <strong>in-sample / operational override</strong>. OOS is report-only;
      the 4% floor was not retuned.</li>
    </ul>
    <p>Trade overlap (symbol + entry date + entry price): both {ov['both']} ·
    only-control {ov['only_ctrl']} · only-adopted {ov['only_cand']}.</p>
    <p class="muted">{html_mod.escape(house_note)}</p>
    <p class="muted">Adopted arm IS label below is HOLD (quality) — we still
    wired DailyRun because Paul asked for scanner identity.</p>
  </div>
  <p class="muted">Click column headers to sort. Total PnL $ / Sheet PnL $ omitted.
  IS/OOS Ann ROR, Max DD, Calmar, Sharpe are Closed-overlay (sheet $45k / $500k)
  unless FULL host Audit is used on the adopted pin.</p>

  <h2>IS — report under adopted freeze (entry &lt; 2024-01-01; judge was HOLD)</h2>
  <table class="sortable"><thead><tr>{th}</tr></thead><tbody>{body_is}</tbody></table>

  <h2>OOS — report-only (entry ≥ 2024-01-01)</h2>
  <table class="sortable"><thead><tr>{th}</tr></thead><tbody>{body_oos}</tbody></table>

  <h2>FULL — report-only</h2>
  <table class="sortable"><thead><tr>{th}</tr></thead><tbody>{body_full}</tbody></table>

  <h2>Freeze after adopt (one knob: ATR% measurement point)</h2>
  <p>Universe Paul78.142 (<code>drive/universes/VZ_universe.csv</code>) · lookback 126 ·
  retest_window 63 · High-Low (HL) only · first_retest · min_touches ≥ 1 ·
  eps 0.005 · next_open · <code>EXIT_atr4_s025_r15_ts20</code>
  (<strong>atr4</strong> = 4% ATR floor <em>at trigger</em>, not a 4-ATR stop;
  s025 = stop 0.25 ATR under zone; r15 = 1.5R; ts20 = 20) ·
  High Volume Node (HVN) off · long · cooldown 10d after TARGET.</p>
  <p>Control (prior house): <code>min_atr_pct_at_entry=4</code>
  (ATR14_at_entry / entry_price × 100).
  Adopted DailyRun: <code>min_atr_pct_at_trigger=4</code>
  (ATR14_at_trigger / trigger_close × 100); entry gate off.
  Adopted IS verdict on the compare: {html_mod.escape(adopted['verdict'])}
  — {html_mod.escape(adopted['why'])}.</p>
</div>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")
    print(f"[html] {path}", flush=True)


def write_baseline(
    path: Path,
    *,
    pin: str,
    packs: list[dict[str, Any]],
    ov: dict[str, Any],
    house_note: str,
) -> None:
    ctrl = next(p for p in packs if p["arm"] == "CONTROL")
    adopted = next(p for p in packs if p["arm"] != "CONTROL")

    def blk(name: str, p: dict[str, Any]) -> str:
        lines = [f"### {name}"]
        for slice_name, label in (("is", "IS"), ("oos", "OOS"), ("full", "FULL")):
            m = p[slice_name]
            lines.append(
                f"- **{label}** N={m['n']} WR={m['wr']:.1f}% AvgPnL%={m['avg_pnl']:.2f} "
                f"AvgR={m['avg_r']:.3f} PF={m['pf']:.2f} AnnROR={m['ann_ror']:.1f} "
                f"MaxDD={m['max_dd']:.2f} Calmar={m['calmar']:.2f} Sharpe={m['sharpe']:.2f}"
            )
        return "\n".join(lines)

    md = f"""# BASELINE — VZ ATR% at trigger operational adopt `20260907`

**Status:** DailyRun official TBN sleeve — **operational adopt after HOLD AB**.
**Not KEEP. Not walk-forward gold.**

House pin: `{pin}`. Exit token unchanged: `EXIT_atr4_s025_r15_ts20`.
**atr4** is now ATR14 / trigger_close ≥ 4% (scanner-known), not entry fill.

## What you asked

> {ORIGINAL_REQUEST}

## In plain English

{PLAIN_ENGLISH}

## Honesty / selection

- Prior AB `vz_atr_trigger_vs_entry_ab_20260907` was **HOLD on IS quality**
  (WR 60.5% vs 60.9%, AvgR 0.489 vs 0.535; OOS also slightly softer).
- This adopt is a **product / scanner-live choice**, not a quality KEEP and
  not walk-forward gold. Labeled **operational override**.
- Choosing after the A/B table on the same Paul78.142 book is still
  **in-sample selection / operational override**.
- OOS is **report-only**. Do **not** retune the 4% floor. Do not retune OOS.
- One gate only: trigger 4%. Entry gate off. Both on would be a tighter
  two-gate system — not what Paul asked.

## Frozen knobs (one change: ATR% measurement point)

| Knob | Value |
|------|-------|
| Universe | `drive/universes/VZ_universe.csv` = Paul78.142 (142) |
| zone_kinds | HL only |
| first_retest_only | true |
| min_touches | ≥1 |
| retest_eps_pct | 0.005 |
| lookback / retest_window | 126 / 63 |
| entry_on | next_open |
| exit | `EXIT_atr4_s025_r15_ts20` (atr4 = **trigger** 4%) |
| stop_atr | 0.25 |
| target_r | 1.5 |
| exit_bars | 20 |
| min_atr_pct_at_trigger | **4.0** (house / DailyRun) |
| min_atr_pct_at_entry | **0** (off) |
| require_hvn_overlap | false |
| trade_side | long |
| cooldown_after_target_days | 10 |

Delta from prior house: `vz_min_atr_pct_at_entry=4` / `vz_min_atr_pct_at_trigger=0`
→ `vz_min_atr_pct_at_entry=0` / `vz_min_atr_pct_at_trigger=4`. Same 4% floor,
same exit token; measurement point moved to trigger close.

## Chronologic split

- IS = `entry_date < 2024-01-01` (reported; quality was HOLD)
- OOS = `entry_date >= 2024-01-01` — **report-only**. Do not retune.

{house_note}

{blk("Control (prior house — ATR% at entry)", ctrl)}

{blk("Adopted DailyRun (ATR% at trigger)", adopted)}

- Overlap: both={ov["both"]} only-control={ov["only_ctrl"]} only-adopted={ov["only_cand"]}
- **IS quality label:** {adopted["verdict"]} — {adopted["why"]}
- **OOS:** {adopted.get("oos_note", "report-only")}
- **DailyRun action:** wired anyway (scanner identity). Do not read this as KEEP/gold.

## House pin / reconcile

- House pin: `drive/VZ_house_last_run_ts.txt` = **`{pin}`**
- Reconcile golden: `drive/paul_experiments/vz_baseline_{pin}/`
- Prior golden: `260907093231` (entry-priced 4%)
- Gate: `reconcile_gate_config.json` VZ `enabled: true`

## Exit token decode

`EXIT_atr4_s025_r15_ts20`:

- **atr4** = 14-day ATR ≥ 4% of **trigger close** (not a 4-ATR stop; not entry)
- **s025** = stop at zone.lo − 0.25×ATR
- **r15** = 1.5R target
- **ts20** = 20-bar time stop
"""
    path.write_text(md, encoding="utf-8")
    print(f"[md] {path}", flush=True)


def main() -> int:
    pin = read_pin(HOUSE_PIN_PATH)
    if pin == CTRL_PIN:
        raise SystemExit(
            f"house pin is still {CTRL_PIN} (entry-priced control). "
            "Run house run_vz.bat after the default flip first."
        )
    closed = REPO / "drive" / f"VZ_Closed_{pin}.csv"
    if not closed.is_file():
        raise FileNotFoundError(closed)
    fields = audit_gate_fields(
        find_audit_in_dir(REPO / "drive")
        or find_report_in_dir(REPO / "drive")
        or (REPO / "drive" / f"VZ_Audit_Report_{pin}.csv")
    )
    # Prefer the pin-specific audit if present
    pin_audit = REPO / "drive" / f"VZ_Audit_Report_{pin}.csv"
    if pin_audit.is_file():
        fields = audit_gate_fields(pin_audit)
    ok, note = adopted_freeze_ok(fields)
    if not ok:
        raise SystemExit(f"{note}; fields={fields}")

    ctrl_closed = REPO / "drive" / f"VZ_Closed_{CTRL_PIN}.csv"
    if not ctrl_closed.is_file():
        raise FileNotFoundError(ctrl_closed)

    ctrl_trades = load_closed(ctrl_closed)
    ad_trades = load_closed(closed)
    ctrl_eq = REPO / "drive" / f"VZ_EquityCurve_{CTRL_PIN}.csv"
    ad_eq = REPO / "drive" / f"VZ_EquityCurve_{pin}.csv"
    ctrl_host = read_report_row(REPO / "drive" / f"VZ_Audit_Report_{CTRL_PIN}.csv")
    ad_host = read_report_row(pin_audit if pin_audit.is_file() else None)
    ctrl_sum = load_summary_pack(REPO / "drive" / f"VZ_Summary_{CTRL_PIN}.csv")
    ad_sum = load_summary_pack(REPO / "drive" / f"VZ_Summary_{pin}.csv")

    ctrl_pack = score_pack(
        ctrl_trades,
        equity=ctrl_eq if ctrl_eq.is_file() else None,
        host=ctrl_host or None,
        summary=ctrl_sum,
    )
    ad_pack = score_pack(
        ad_trades,
        equity=ad_eq if ad_eq.is_file() else None,
        host=ad_host or None,
        summary=ad_sum,
    )
    from vz_atr_trigger_vs_entry_ab_20260907 import verdict_is  # noqa: WPS433

    v, why = verdict_is("ATR_TRIGGER", ad_pack["is"], ctrl_pack["is"])
    oos_note = ""
    if oos_softens(ad_pack["oos"], ctrl_pack["oos"]):
        oos_note = "OOS softens vs control (report-only; do not retune)"
    else:
        oos_note = "OOS report-only"
    packs = [
        {
            "arm": "CONTROL",
            "knob": "ATR% at entry (prior house)",
            "verdict": "CONTROL",
            "why": "Prior DailyRun: ATR% at entry (fill) ≥ 4",
            "oos_note": "house reference",
            **ctrl_pack,
        },
        {
            "arm": "ADOPTED",
            "knob": "ATR% at trigger (DailyRun now)",
            "verdict": v,
            "why": why,
            "oos_note": oos_note,
            **ad_pack,
        },
    ]
    ov = overlap_counts(ctrl_trades, ad_trades)
    house_note = (
        f"{note}. Control book `VZ_Closed_{CTRL_PIN}.csv`. "
        f"Adopted house pin `{pin}` / `VZ_Closed_{pin}.csv`."
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_baseline(
        OUT_DIR / "BASELINE.md",
        pin=pin,
        packs=packs,
        ov=ov,
        house_note=house_note,
    )
    write_compare_html(
        OUT_DIR / "adopt.html",
        pin=pin,
        packs=packs,
        ov=ov,
        house_note=house_note,
    )
    golden = freeze_golden(pin)
    n_closed = sum(1 for _ in golden.open(encoding="utf-8-sig")) - 1
    update_reconcile_config(pin, n_closed)
    update_writeup_golden(pin)
    print(f"[done] pin={pin} n={n_closed} verdict={v}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
