#!/usr/bin/env python3
"""Volume Zone (VZ) one-knob A/B — ATR% gate at entry vs at trigger.

Control = house ``min_atr_pct_at_entry=4`` (ATR14 / fill price).
Candidate = research ``min_atr_pct_at_trigger=4`` (ATR14 / trigger close).

House Closed reused as control when freeze matches. Candidate is an isolated
``run_vz.bat -o`` live run (cooldown depends on which trades fire).

IS judges. OOS/FULL report-only. Research only — not gold / not DailyRun.
Does not flip the house DailyRun default.
"""
from __future__ import annotations

import argparse
import html as html_mod
import math
import os
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

from compare_format import format_money  # noqa: E402
from vz_lookback_zonegap_ab_20260907 import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    find_audit_in_dir,
    find_closed_in_dir,
    find_equity_in_dir,
    find_report_in_dir,
    find_summary_in_dir,
    load_closed,
    load_summary_pack,
    oos_softens,
    read_pin,
    read_report_row,
    score_pack,
    sortable_th,
    trade_key,
    verdict_is as _verdict_is_lookback,
)

STAMP = "vz_atr_trigger_vs_entry_ab_20260907"
OUT_DIR = REPO / "drive" / "paul_experiments" / STAMP
CAND_DIR = OUT_DIR / "cand_trigger"
HOUSE_PIN_PATH = REPO / "drive" / "VZ_house_last_run_ts.txt"
UNIV_PATH = REPO / "drive" / "universes" / "VZ_universe.csv"
IS_CUT = date(2024, 1, 1)

ORIGINAL_REQUEST = (
    "since we don't know the entry price when a VZ symbol hits the scanner, we "
    "should probably use ATR at trigger not ATR at entry. can you run an AB test "
    "on ATR at trigger vs. entry?"
)

PLAIN_ENGLISH = (
    "Volume Zone (VZ) waits for a high-volume price shelf, then buys the first "
    "bounce. The scanner sees the signal at today's close, but the house fill is "
    "tomorrow's open — a price we do not have yet. House currently requires "
    "Average True Range (ATR, a typical daily swing size) to be at least 4% of "
    "that unknown fill price. The candidate applies the same 4% floor to ATR vs "
    "today's close, which the scanner already knows. Everything else stays "
    "frozen. We judge on older history (entries before 2024). Newer history is "
    "shown only to see if the story holds up. Research only — this does not "
    "change the live DailyRun default."
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


def house_closed_path(pin: str) -> Path:
    p = REPO / "drive" / f"VZ_Closed_{pin}.csv"
    if p.exists():
        return p
    latest = REPO / "drive" / "VZ_LatestRun_Closed.csv"
    if latest.exists():
        return latest
    raise FileNotFoundError(f"house Closed missing for pin {pin}")


def audit_gate_fields(path: Optional[Path]) -> dict[str, Any]:
    row = read_report_row(path)
    return {
        "exit_name": str(row.get("vz_exit_name") or ""),
        "exit_bars": _f(row.get("vz_exit_bars")),
        "stop_atr": _f(row.get("vz_stop_atr_buffer")),
        "target_r": _f(row.get("vz_target_r")),
        "lookback": _f(row.get("vz_lookback_days")),
        "rw": _f(row.get("vz_retest_window")),
        "entry_on": str(row.get("vz_entry_on") or ""),
        "min_atr_entry": _f(row.get("vz_min_atr_pct_at_entry")),
        "min_atr_trigger": _f(row.get("vz_min_atr_pct_at_trigger")),
        "cd": _f(row.get("vz_cooldown_after_target_days")),
        "hvn": str(row.get("vz_require_hvn_overlap") or ""),
        "side": str(row.get("vz_trade_side") or ""),
    }


def house_freeze_ok(fields: dict[str, Any]) -> tuple[bool, str]:
    checks = [
        (str(fields.get("exit_name") or "") == "EXIT_atr4_s025_r15_ts20", "exit_name"),
        (abs(float(fields.get("exit_bars") or 0) - 20) < 0.1, "exit_bars"),
        (abs(float(fields.get("stop_atr") or 0) - 0.25) < 1e-6, "stop_atr"),
        (abs(float(fields.get("target_r") or 0) - 1.5) < 1e-6, "target_r"),
        (abs(float(fields.get("lookback") or 0) - 126) < 0.1, "lookback"),
        (abs(float(fields.get("rw") or 0) - 63) < 0.1, "rw"),
        (str(fields.get("entry_on") or "").lower() == "next_open", "entry_on"),
        (abs(float(fields.get("min_atr_entry") or 0) - 4.0) < 1e-6, "min_atr_entry"),
        (abs(float(fields.get("cd") or 0) - 10) < 0.1, "cooldown"),
    ]
    bad = [name for ok, name in checks if not ok]
    if bad:
        return False, "house freeze mismatch: " + ", ".join(bad)
    return True, "house freeze matches entry-ATR% 4 / EXIT_atr4_s025_r15_ts20"


def attach_atr_fields(trades: list[dict[str, Any]]) -> None:
    for t in trades:
        raw = t.get("raw") or {}
        t["atr_pct_entry"] = _f(raw.get("ATR_PCT_AT_ENTRY"))
        t["atr_pct_trigger"] = _f(raw.get("ATR_PCT_AT_TRIGGER"))
        t["atr14_entry"] = _f(raw.get("ATR_14_AT_ENTRY"))
        t["atr14_trigger"] = _f(raw.get("ATR_14_AT_TRIGGER"))


def run_isolated_trigger(out_dir: Path, workers: int) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = find_closed_in_dir(out_dir)
    if existing is not None:
        fields = audit_gate_fields(find_audit_in_dir(out_dir) or find_report_in_dir(out_dir))
        trig = _f(fields.get("min_atr_trigger"), 0.0)
        entry = _f(fields.get("min_atr_entry"), -1.0)
        if abs(trig - 4.0) < 1e-6 and abs(entry) < 1e-6:
            print(f"[cand] reuse {existing} trigger=4 entry=0", flush=True)
            return existing
        print(
            f"[cand] existing Closed entry={entry} trigger={trig}; rerunning",
            flush=True,
        )
    env = os.environ.copy()
    env.pop("VZ_SYMBOLS", None)
    env.pop("VZ_UNIVERSE_CSV", None)
    env["VZ_MIN_ATR_PCT"] = "0"
    env["VZ_WORKERS"] = str(workers)
    rel_out = out_dir.relative_to(REPO).as_posix().replace("/", "\\")
    cmd = (
        f"run_vz.bat drive\\universes\\VZ_universe.csv "
        f"-o {rel_out} "
        f"-v vz_min_atr_pct_at_entry=0 "
        f"-v vz_min_atr_pct_at_trigger=4.0"
    )
    pin_before = read_pin(HOUSE_PIN_PATH)
    print(f"[cand] {cmd}", flush=True)
    subprocess.run(cmd, shell=True, check=True, cwd=str(REPO), env=env)
    pin_after = read_pin(HOUSE_PIN_PATH)
    if pin_after != pin_before:
        raise RuntimeError(
            f"House pin changed {pin_before} -> {pin_after}; aborting"
        )
    closed = find_closed_in_dir(out_dir)
    if closed is None:
        raise FileNotFoundError(f"no Closed in {out_dir}")
    fields = audit_gate_fields(find_audit_in_dir(out_dir) or find_report_in_dir(out_dir))
    print(f"[cand] wrote {closed} gates={fields}", flush=True)
    trig = _f(fields.get("min_atr_trigger"), 0.0)
    entry = _f(fields.get("min_atr_entry"), -1.0)
    if abs(trig - 4.0) > 1e-6 or abs(entry) > 1e-6:
        raise RuntimeError(
            f"candidate gate mismatch: wanted entry=0 trigger=4 got {fields}"
        )
    return closed


def overlap_counts(
    ctrl: list[dict[str, Any]], cand: list[dict[str, Any]]
) -> dict[str, Any]:
    c_map = {trade_key(t): t for t in ctrl}
    k_map = {trade_key(t): t for t in cand}
    both = [c_map[k] for k in c_map if k in k_map]
    only_c = [t for k, t in c_map.items() if k not in k_map]
    only_k = [t for k, t in k_map.items() if k not in c_map]
    return {
        "both": len(both),
        "only_ctrl": len(only_c),
        "only_cand": len(only_k),
        "only_ctrl_trades": only_c,
        "only_cand_trades": only_k,
        "both_trades": both,
    }


def fmt_num(x: Any, nd: int = 2) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(v):
        return "—"
    return f"{v:.{nd}f}"


def fmt_delta(x: Any, nd: int = 2) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(v):
        return "—"
    return f"{v:+.{nd}f}"


def _exit_mix_s(exits: dict[str, int], n: int) -> str:
    if n <= 0:
        return ""
    return ", ".join(f"{k}={v}({100.0 * v / n:.0f}%)" for k, v in sorted(exits.items()))


def verdict_is(arm: str, m: dict[str, Any], ctrl: dict[str, Any]) -> tuple[str, str]:
    if arm == "CONTROL":
        return "CONTROL", "House freeze: ATR% at entry (fill) ≥ 4"
    v, why = _verdict_is_lookback(arm, m, ctrl)
    if v == "CONTROL":
        return "CONTROL", why
    return v, why


def pack_row_html(
    p: dict[str, Any],
    ctrl: dict[str, Any],
    key: str,
) -> str:
    m = p[key]
    c = ctrl[key]
    d_n = m["n"] - c["n"]
    d_wr = m["wr"] - c["wr"]
    d_r = m["avg_r"] - c["avg_r"]
    d_pnl = m["avg_pnl"] - c["avg_pnl"]
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
    fit = m["fit"]
    cls = ""
    if key == "is":
        if p["verdict"] in ("KEEP", "LEAN KEEP"):
            cls = "keep"
        elif p["verdict"] == "DISMISS":
            cls = "dismiss"
        elif p["verdict"] == "HOLD":
            cls = "hold"
    return (
        f"<tr class='{cls}'>"
        f"<td>{html_mod.escape(p['arm'])}</td>"
        f"<td>{html_mod.escape(p['knob'])}</td>"
        f"<td>{m['n']}</td><td>{fmt_num(m['wr'], 1)}</td>"
        f"<td>{fmt_num(m['avg_pnl'])}</td><td>{fmt_num(m['avg_r'])}</td>"
        f"<td>{fmt_num(m['avg_wo_max'])}</td>"
        f"<td>{fmt_num(m['ann_ror'])}</td><td>{fmt_num(m['max_dd'])}</td>"
        f"<td>{fmt_num(m['calmar'])}</td><td>{fmt_num(m['sharpe'])}</td>"
        f"<td>{fmt_num(m['pf'])}</td>"
        f"<td>{format_money(m.get('expectancy_d'))}</td>"
        f"<td>{fmt_num(m['avg_win'])}</td><td>{fmt_num(m['avg_loss'])}</td>"
        f"<td>{fmt_num(m['wl_count'])}</td><td>{fmt_num(m['wl_dollar'])}</td>"
        f"<td>{fmt_num(m['avg_days'], 1)}</td><td>{fmt_num(m['med_days'], 1)}</td>"
        f"<td>{fmt_num(m['p90_days'], 1)}</td><td>{fmt_num(m['capital_days'], 0)}</td>"
        f"<td>{format_money(m.get('profit_per_cd'))}</td>"
        f"<td>{m['losing_streak']}</td>"
        f"<td>{fmt_num(m['pct_max_sym'], 1)}</td><td>{fmt_num(m['pct_max_trade'], 1)}</td>"
        f"<td>{fmt_num(fit['mean_fit_r'])}</td><td>{fmt_num(fit['mean_paul'])}</td>"
        f"<td>{fmt_num(fit['mean_wo'])}</td><td>{fmt_num(fit['mean_outlier'], 1)}</td>"
        f"<td>{fmt_num(fit['mean_tpy'])}</td>"
        f"<td>{d_n:+d}</td><td>{fmt_delta(d_wr, 1)}</td><td>{fmt_delta(d_r)}</td>"
        f"<td>{fmt_delta(d_pnl)}</td><td>{fmt_delta(d_ror, 1)}</td>"
        f"<td>{fmt_delta(d_dd)}</td><td>{fmt_delta(m['pf'] - c['pf'])}</td>"
        f"<td>{html_mod.escape(p['verdict'] if key == 'is' else 'report-only')}</td>"
        f"<td>{html_mod.escape(p['why'] if key == 'is' else p.get('oos_note', ''))}</td>"
        f"<td>{html_mod.escape(_exit_mix_s(m['exits'], m['n']))}</td>"
        "</tr>"
    )


def write_trade_diff_local(
    out_path: Path,
    *,
    pin: str,
    ctrl_trades: list[dict[str, Any]],
    cand_trades: list[dict[str, Any]],
) -> None:
    c_map = {trade_key(t): t for t in ctrl_trades}
    k_map = {trade_key(t): t for t in cand_trades}
    only_c = [t for k, t in c_map.items() if k not in k_map]
    only_k = [t for k, t in k_map.items() if k not in c_map]
    both = [c_map[k] for k in c_map if k in k_map]

    def row_html(tag: str, t: dict[str, Any]) -> str:
        opened = t["opened"].isoformat() if t.get("opened") else ""
        closed = t["closed"].isoformat() if t.get("closed") else ""
        return (
            f"<tr><td>{html_mod.escape(tag)}</td>"
            f"<td>{html_mod.escape(t['sym'])}</td>"
            f"<td>{opened}</td><td>{fmt_num(t.get('entry'))}</td>"
            f"<td>{html_mod.escape(str(t.get('exit') or ''))}</td>"
            f"<td>{fmt_num(t.get('pnl'))}</td><td>{fmt_num(t.get('days'), 1)}</td>"
            f"<td>{closed}</td>"
            f"<td>{fmt_num(t.get('atr_pct_entry'))}</td>"
            f"<td>{fmt_num(t.get('atr_pct_trigger'))}</td></tr>"
        )

    th = "".join(
        sortable_th(a, b)
        for a, b in [
            ("Bucket", "text"),
            ("Symbol", "text"),
            ("Opened", "date"),
            ("Entry", "num"),
            ("Exit", "text"),
            ("PnL%", "num"),
            ("Days", "num"),
            ("Closed", "date"),
            ("ATR% entry", "num"),
            ("ATR% trigger", "num"),
        ]
    )
    body_old = "".join(
        row_html("ONLY_IN_CONTROL", t)
        for t in sorted(only_c, key=lambda x: (x["sym"], x["opened"]))
    )
    body_new = "".join(
        row_html("ONLY_IN_CANDIDATE", t)
        for t in sorted(only_k, key=lambda x: (x["sym"], x["opened"]))
    )
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>VZ ATR% trigger vs entry — trade diff</title>
<style>
body {{ font-family: Segoe UI, Georgia, serif; margin: 24px; color: #1a1a18; background: #fafaf8; }}
.muted {{ color: #5c5c56; }}
.callout {{ background:#eef2ff; border:1px solid #c7d2fe; padding:12px 14px; margin:1rem 0; }}
table.sortable {{ border-collapse: collapse; width: 100%; background: #fff; margin: 12px 0 28px; font-size: 13px; }}
table.sortable th, table.sortable td {{ border: 1px solid #d8d8d0; padding: 6px 8px; }}
table.sortable th {{ background: #f0f0ea; }}
blockquote {{ margin:0.4rem 0 0.8rem; color:#334155; }}
{SORTABLE_TH_CSS}
</style></head><body>
<h1>VZ Average True Range (ATR) % trigger vs entry — trade diff</h1>
<div class="callout">
  <p><strong>What you asked</strong></p>
  <blockquote>{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
  <p><strong>In plain English</strong></p>
  <p>Old rows are house trades that fail the trigger-bar 4% ATR floor (or get
  crowded out by cooldown). New rows are trades the scanner would take because
  trigger ATR% is ≥ 4 even though the fill-price ATR% was below 4 — or that
  appear after the different gate changes later cooldown. Research only.</p>
</div>
<p class="muted">House pin {html_mod.escape(pin)}. Click column headers to sort.</p>
<p>Exact overlap {len(both)} · Only-control {len(only_c)} · Only-candidate {len(only_k)}</p>
<h2>Old — only in control (entry ATR% gate)</h2>
<table class="sortable"><thead><tr>{th}</tr></thead><tbody>{body_old or "<tr><td colspan='10'>none</td></tr>"}</tbody></table>
<h2>New — only in candidate (trigger ATR% gate)</h2>
<table class="sortable"><thead><tr>{th}</tr></thead><tbody>{body_new or "<tr><td colspan='10'>none</td></tr>"}</tbody></table>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    out_path.write_text(html, encoding="utf-8")
    print(f"[diff] {out_path} old={len(only_c)} new={len(only_k)} both={len(both)}", flush=True)


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
    cand = next(p for p in packs if p["arm"] != "CONTROL")
    recs = [f"{cand['arm']}: {cand['verdict']} — {cand['why']}"]
    rec_html = "".join(f"<li>{html_mod.escape(x)}</li>" for x in recs)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>VZ ATR% at trigger vs entry A/B — 20260907</title>
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
  <h1>Volume Zone (VZ) Average True Range (ATR) % gate: trigger vs entry</h1>
  <p class="muted">Stamp {STAMP} · House pin {html_mod.escape(pin)} · Research only · not gold · not DailyRun</p>
  <div class="callout">
    <p><strong>What you asked</strong></p>
    <blockquote>{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
    <p><strong>In plain English</strong></p>
    <p>{html_mod.escape(PLAIN_ENGLISH)}</p>
  </div>
  <div class="rec">
    <p><strong>IS verdict</strong> (OOS/FULL report-only; OOS softens → HOLD, do not retune)</p>
    <ul>{rec_html}</ul>
    <p>Trade overlap (symbol + entry date + entry price): both {ov['both']} ·
    only-control {ov['only_ctrl']} · only-candidate {ov['only_cand']}.</p>
    <p class="muted">{html_mod.escape(house_note)}</p>
  </div>
  <p class="muted">Click column headers to sort. Total PnL $ / Sheet PnL $ omitted.
  IS/OOS Ann ROR, Max DD, Calmar, Sharpe are Closed-overlay (sheet $45k / $500k).
  Choosing after this table is in-sample selection — labeled research-only.</p>

  <h2>IS — judge (entry &lt; 2024-01-01)</h2>
  <table class="sortable"><thead><tr>{th}</tr></thead><tbody>{body_is}</tbody></table>

  <h2>OOS — report-only (entry ≥ 2024-01-01)</h2>
  <table class="sortable"><thead><tr>{th}</tr></thead><tbody>{body_oos}</tbody></table>

  <h2>FULL — report-only</h2>
  <table class="sortable"><thead><tr>{th}</tr></thead><tbody>{body_full}</tbody></table>

  <h2>Freeze (one knob: ATR% measurement point)</h2>
  <p>Universe Paul78.142 (<code>drive/universes/VZ_universe.csv</code>) · lookback 126 ·
  retest_window 63 · High-Low (HL) only · first_retest · min_touches ≥ 1 ·
  eps 0.005 · next_open · <code>EXIT_atr4_s025_r15_ts20</code> (stop 0.25 ATR under
  zone, target 1.5R, time stop 20) · High Volume Node (HVN) off · long ·
  cooldown 10d after TARGET · floor 4.0 ATR%.</p>
  <p>Control: <code>min_atr_pct_at_entry=4</code> (ATR14_at_entry / entry_price × 100).
  Candidate: <code>min_atr_pct_at_trigger=4</code> (ATR14_at_trigger / trigger_close × 100);
  entry gate off. DailyRun default is unchanged.</p>
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
    leftover: str,
) -> None:
    ctrl = next(p for p in packs if p["arm"] == "CONTROL")
    cand = next(p for p in packs if p["arm"] != "CONTROL")

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

    md = f"""# VZ ATR% at trigger vs entry A/B — 20260907

**Status:** research only — not gold — not DailyRun. Do not wire.

## What you asked

> {ORIGINAL_REQUEST}

## In plain English

{PLAIN_ENGLISH}

## Hypothesis (one knob)

House fill is `next_open` (T+1). The scanner knows the signal at trigger close.
`ATR14 / entry_price` uses a price you do not have yet. Candidate uses
Average True Range (ATR) % at the trigger bar (`ATR14 / trigger_close`) so the
live scanner can apply the same gate.

- **Control:** `min_atr_pct_at_entry=4` — ATR14 at entry / entry_price × 100 ≥ 4
- **Candidate:** `min_atr_pct_at_trigger=4` — ATR14 at trigger / trigger_close × 100 ≥ 4
  (`vz_min_atr_pct_at_entry=0`)

## Freeze (do not change)

| Knob | Value |
|------|-------|
| Universe | Paul78.142 (`drive/universes/VZ_universe.csv`) |
| lookback_days | 126 |
| retest_window | 63 |
| zone_kinds | HL-only |
| first_retest_only | true |
| min_touches_before_entry | ≥ 1 |
| retest_eps_pct | 0.005 |
| entry_on | next_open |
| Exit identity | `EXIT_atr4_s025_r15_ts20` |
| stop_atr_buffer | 0.25 ATR under zone |
| target_r | 1.5 |
| exit_bars (time stop) | 20 |
| require_hvn_overlap | false |
| trade_side | long |
| cooldown_after_target_days | 10 |
| ATR% floor | 4.0 |
| House pin (control book) | `{pin}` |

{house_note}

## IS / OOS

- **IS (judge):** `entry_date < 2024-01-01`
- **OOS (report-only):** `entry_date >= 2024-01-01` — do not retune
- KEEP / LEAN KEEP / HOLD / DISMISS on **IS quality** (WR, AvgR / expectancy, PF,
  Ann ROR, Max DD, Calmar, Sharpe, FIT). Quality over count. N collapse → not KEEP.

## Selection-bias note

This is a single pre-specified measurement-point A/B (entry vs trigger), not a
search grid. Judging KEEP/DISMISS after seeing the compare table is still
in-sample selection on IS. OOS is report-only. Research candidate ≠ gold ≠ DailyRun.

## Results

{blk("Control (ATR% at entry)", ctrl)}

{blk("Candidate (ATR% at trigger)", cand)}

- Overlap: both={ov['both']} only-control={ov['only_ctrl']} only-candidate={ov['only_cand']}
- **IS verdict:** {cand['verdict']} — {cand['why']}
- **OOS:** {cand.get('oos_note', 'report-only')}

## House recommendation

DailyRun should **stay on entry ATR%** unless this stamp is KEEP / LEAN KEEP
**and** a later promotion bar is met. This stamp alone does not flip the default.

## Implementation leftover

{leftover}

## Chronologic split

IS = entry_date < 2024-01-01; OOS = entry_date >= 2024-01-01.
"""
    path.write_text(md, encoding="utf-8")
    print(f"[md] {path}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--score-only", action="store_true")
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pin = read_pin(HOUSE_PIN_PATH)
    ctrl_path = house_closed_path(pin)
    house_audit = REPO / "drive" / f"VZ_Audit_Report_{pin}.csv"
    house_fields = audit_gate_fields(house_audit if house_audit.exists() else None)
    ok, house_note = house_freeze_ok(house_fields)
    if not ok:
        raise RuntimeError(house_note + f" fields={house_fields}")
    print(f"[ctrl] {ctrl_path} pin={pin} {house_note}", flush=True)

    if args.score_only:
        cand_path = find_closed_in_dir(CAND_DIR)
        if cand_path is None:
            raise FileNotFoundError(f"--score-only but no Closed in {CAND_DIR}")
    else:
        cand_path = run_isolated_trigger(CAND_DIR, args.workers)

    pin_final = read_pin(HOUSE_PIN_PATH)
    if pin_final != pin:
        raise RuntimeError(f"House pin changed during job {pin} -> {pin_final}")

    ctrl_trades = load_closed(ctrl_path)
    cand_trades = load_closed(cand_path)
    attach_atr_fields(ctrl_trades)
    attach_atr_fields(cand_trades)

    ctrl_eq = REPO / "drive" / f"VZ_EquityCurve_{pin}.csv"
    if not ctrl_eq.exists():
        ctrl_eq = REPO / "drive" / "VZ_LatestRun_EquityCurve.csv"
    cand_eq = find_equity_in_dir(CAND_DIR)
    ctrl_host = read_report_row(REPO / "drive" / f"VZ_Report_{pin}.csv")
    cand_host = read_report_row(find_report_in_dir(CAND_DIR))
    ctrl_sum = load_summary_pack(REPO / "drive" / f"VZ_Summary_{pin}.csv")
    cand_sum = load_summary_pack(find_summary_in_dir(CAND_DIR))

    ctrl_pack = score_pack(
        ctrl_trades,
        equity=ctrl_eq if ctrl_eq.exists() else None,
        host=ctrl_host or None,
        summary=ctrl_sum,
    )
    cand_pack = score_pack(
        cand_trades,
        equity=cand_eq,
        host=cand_host or None,
        summary=cand_sum,
    )
    ctrl_pack["arm"] = "CONTROL"
    ctrl_pack["knob"] = "ATR% at entry (house)"
    cand_pack["arm"] = "ATR_TRIGGER"
    cand_pack["knob"] = "ATR% at trigger (research)"
    v, why = verdict_is("ATR_TRIGGER", cand_pack["is"], ctrl_pack["is"])
    cand_pack["verdict"] = v
    cand_pack["why"] = why
    ctrl_pack["verdict"] = "CONTROL"
    ctrl_pack["why"] = "House freeze: ATR% at entry (fill) ≥ 4"
    if oos_softens(cand_pack["oos"], ctrl_pack["oos"]):
        cand_pack["oos_note"] = "OOS softens vs control (report-only; HOLD if IS was KEEP)"
        if cand_pack["verdict"] in ("KEEP", "LEAN KEEP"):
            cand_pack["verdict"] = "HOLD"
            cand_pack["why"] = cand_pack["why"] + " — OOS softened so IS KEEP → HOLD"
    else:
        cand_pack["oos_note"] = "OOS does not clearly soften vs control (still report-only)"
    ctrl_pack["oos_note"] = "house reference"

    ov = overlap_counts(ctrl_trades, cand_trades)
    leftover = (
        "Added research-only `vz_min_atr_pct_at_trigger` / `VzConfig.min_atr_pct_at_trigger` "
        "(default 0 = off) in `stock_analysis/rocket_vz.py` + TBN/audit mapping. "
        "`run_vz.bat` / DailyRun still pass only `vz_min_atr_pct_at_entry`. "
        "Candidate run: isolated `-o` + `-v vz_min_atr_pct_at_entry=0 "
        "-v vz_min_atr_pct_at_trigger=4.0`. Do not flip the DailyRun default from this stamp."
    )

    write_compare_html(
        OUT_DIR / "compare.html",
        pin=pin,
        packs=[ctrl_pack, cand_pack],
        ov=ov,
        house_note=house_note + f" Control book `{ctrl_path.name}`.",
    )
    write_trade_diff_local(
        OUT_DIR / "trade_diff.html",
        pin=pin,
        ctrl_trades=ctrl_trades,
        cand_trades=cand_trades,
    )
    write_baseline(
        OUT_DIR / "BASELINE.md",
        pin=pin,
        packs=[ctrl_pack, cand_pack],
        ov=ov,
        house_note=house_note + f" Control book `{ctrl_path.name}`.",
        leftover=leftover,
    )

    def _line(tag: str, m: dict[str, Any]) -> str:
        return (
            f"{tag} N={m['n']} WR={m['wr']:.1f}% AvgR={m['avg_r']:.3f} "
            f"AvgPnL%={m['avg_pnl']:.2f} PF={m['pf']:.2f} "
            f"AnnROR={m['ann_ror']:.1f} MaxDD={m['max_dd']:.2f}"
        )

    print("[IS control]", _line("CTRL", ctrl_pack["is"]))
    print("[IS cand]   ", _line("TRIG", cand_pack["is"]))
    print("[OOS control]", _line("CTRL", ctrl_pack["oos"]))
    print("[OOS cand]   ", _line("TRIG", cand_pack["oos"]))
    print(
        f"[verdict] {cand_pack['verdict']} — {cand_pack['why']} | "
        f"overlap both={ov['both']} only_c={ov['only_ctrl']} only_k={ov['only_cand']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
