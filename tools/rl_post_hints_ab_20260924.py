#!/usr/bin/env python3
"""RL one-knob A/B batch from post-analysis hints (2026-09-24).

Control (reuse): no-SMA-target +20% then 60 trading bars on the full OHLC pool
  (~1,126) from rl_no_sma_target_exit_ab_20260905 / pct20_d60.

Candidates are independent one-knob (or one-policy) changes. Not gold. Not DailyRun.

Usage:
  python tools/rl_post_hints_ab_20260924.py --jobs 3 --workers 4
  python tools/rl_post_hints_ab_20260924.py --summarize-only
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
DATA_DIR = ROOT / "data" / "newdata" / "data"
STAMP = "20260924"
OUT_DIR = DRIVE / "paul_experiments" / f"rl_post_hints_ab_{STAMP}"
RUNS_DIR = OUT_DIR / "runs"
CTRL_SRC = (
    DRIVE
    / "paul_experiments"
    / "rl_no_sma_target_exit_ab_20260905"
    / "runs"
    / "pct20_d60"
)

HOUSE_STOP = 0.934
HOUSE_CUT = 1000
HOUSE_DIP = 1.055
HOUSE_EXP = 1.163
TH13 = 1.13
MIN_AVG_VOL = 10_000
MIN_TRIGGER_VOL = 5_000
CONTROL_ID = "control"
TAG = "RL-HINTS"

REQUEST_PROMPT = """\
thanks. let's run post analysis and identify AB tests to wire and run. let's see if there are any improvements we can make. feel free to try a lot
"""

LAYMAN_TRANSLATION = """\
Rocket Launcher (RL) buys dips toward a rising 50-day average after a prior pop, \
then (on this research book) sells after the trade is up 20% and another 60 trading days pass, \
or at the stop. We kept the full major-index list (about 1,126 names) and did not drop \
stocks for past win rate or sector. Each test changes one rule: skip buys when the broad \
market looks weak, sell if that weakness starts, wait for a bigger gain before the time clock, \
shorten or lengthen that clock, require a cleaner close above the 50-day average, \
re-buy after a target only if the averages are still stacked, require the 50-day average \
to have been rising longer, or sit out after a huge one-day shock.
"""

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(DRIVE / "paul_experiments"))
from be_stop_replay_ab import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from compare_format import filter_html_compare_columns  # noqa: E402
from rl_univ_compare_lists import (  # noqa: E402
    PER_SYMBOL,
    SA,
    compare_row,
    fmt_n,
    load_trades,
    pack_result,
    pairwise_delta_row,
    verdict_vs_control,
    write_metrics_csv,
    _find_latest,
    _resolve_python,
)

# id, label, plain knob, hypothesis kind, extra -v overrides
CANDIDATES: list[dict[str, Any]] = [
    {
        "id": "spy_block",
        "label": "Block new buys when SPY intermediate outlook is Weak",
        "knob": "block_entries_when_spy_int_weak=true",
        "kind": "ENTRY",
        "overrides": {"block_entries_when_spy_int_weak": "true"},
    },
    {
        "id": "spy_exit",
        "label": "Exit at open when SPY intermediate outlook turns Weak",
        "knob": "exit_when_spy_int_turns_weak=true",
        "kind": "EXIT",
        "overrides": {"exit_when_spy_int_turns_weak": "true"},
    },
    {
        "id": "pct30",
        "label": "Start 60-day clock after +30% (was +20%)",
        "knob": "rl_exit_percent=0.30",
        "kind": "EXIT",
        "overrides": {"rl_exit_percent": "0.30"},
    },
    {
        "id": "pct40",
        "label": "Start 60-day clock after +40% (was +20%)",
        "knob": "rl_exit_percent=0.40",
        "kind": "EXIT",
        "overrides": {"rl_exit_percent": "0.40"},
    },
    {
        "id": "d40",
        "label": "After +20%, wait 40 trading days (was 60)",
        "knob": "rl_exit_days=40",
        "kind": "EXIT",
        "overrides": {"rl_exit_days": "40"},
    },
    {
        "id": "d90",
        "label": "After +20%, wait 90 trading days (was 60)",
        "knob": "rl_exit_days=90",
        "kind": "EXIT",
        "overrides": {"rl_exit_days": "90"},
    },
    {
        "id": "acc10",
        "label": "Require 10 of last 10 closes above the 50-day average (was 8 of 10)",
        "knob": "rl_acc_min=10",
        "kind": "ENTRY",
        "overrides": {"rl_acc_min": "10"},
    },
    {
        "id": "restack",
        "label": "For 10 bars after a target, re-buy only if 20-day average is ≥5% above 50-day",
        "knob": "rl_post_target_reentry_bars=10 mode=min_stack",
        "kind": "ENTRY",
        "overrides": {
            "rl_post_target_reentry_bars": "10",
            "rl_post_target_reentry_mode": "min_stack",
        },
    },
    {
        "id": "lb8",
        "label": "50-day average must be rising over 8 bars (was 4)",
        "knob": "rl_50_sma_lookback=8",
        "kind": "ENTRY",
        "overrides": {"rl_50_sma_lookback": "8"},
    },
    {
        "id": "shock20",
        "label": "Sit out after a one-day move larger than 20% (rehab stays 120 days)",
        "knob": "rl_shock_threshold=0.20",
        "kind": "ENTRY",
        "overrides": {"rl_shock_threshold": "0.20"},
    },
]
CAND_IDS = [c["id"] for c in CANDIDATES]
ARM_ORDER = {CONTROL_ID: 0, **{cid: i + 1 for i, cid in enumerate(CAND_IDS)}}


def _full_univ_symbols() -> list[str]:
    if not DATA_DIR.is_dir():
        return []
    return sorted(p.stem.upper() for p in DATA_DIR.glob("*.csv"))


def _count_full_univ() -> int:
    return len(_full_univ_symbols())


def _freeze_v(overrides: dict[str, str] | None = None) -> list[str]:
    kv = {
        "rl_mode": "true",
        "brt_zones": "false",
        "yh_zones": "false",
        "wpbr_zones": "false",
        "indicator_buy": "off",
        "rl_sma_qual": "1",
        "ATR_LOW": "off",
        "ATR_HIGH": "off",
        "rl_slope_threshold": "0",
        "rl_dip_pct": str(HOUSE_DIP),
        "rl_expansion": str(HOUSE_EXP),
        "rl_stop_pct": str(HOUSE_STOP),
        "rl_target_pct": "1.2",
        "rl_sma_target_off": "1",
        "rl_cut_the_losers": str(HOUSE_CUT),
        "rl_exit_percent": "0.20",
        "rl_exit_days": "60",
        "rl_exit_calendar_days": "0",
        "rl_max_hold_bars": "0",
        "rl_max_hold_calendar_days": "0",
        "rl_post_target_reentry_bars": "0",
        "rl_too_high": str(TH13),
        "rl_min_avg_vol": str(MIN_AVG_VOL),
        "rl_min_trigger_vol": str(MIN_TRIGGER_VOL),
        "block_entries_when_spy_int_weak": "false",
        "exit_when_spy_int_turns_weak": "false",
        "rl_acc_min": "8",
        "rl_50_sma_lookback": "4",
        "rl_shock_threshold": "0",
    }
    if overrides:
        kv.update(overrides)
    return [f"{k}={v}" for k, v in kv.items()]


def _arm_defs() -> list[dict[str, Any]]:
    syms = _full_univ_symbols()
    n = len(syms)
    arms: list[dict[str, Any]] = [
        {
            "id": CONTROL_ID,
            "label": "Control +20% then 60 trading days",
            "knob": "(freeze)",
            "kind": "CONTROL",
            "symbols": syms,
            "univ_n": n,
            "extra_v": _freeze_v(),
            "reuse": True,
        }
    ]
    for c in CANDIDATES:
        arms.append(
            {
                "id": c["id"],
                "label": c["label"],
                "knob": c["knob"],
                "kind": c["kind"],
                "symbols": syms,
                "univ_n": n,
                "extra_v": _freeze_v(c["overrides"]),
                "reuse": False,
            }
        )
    return arms


def build_cmd(py: str, outdir: Path, workers: int, extra_v: list[str]) -> list[str]:
    cmd = [
        py,
        str(SA / "rocket_tbn.py"),
        str(DATA_DIR),
        "-o",
        str(outdir),
        "-w",
        str(workers),
        "--aggressive",
        "--use-duckdb",
        "--no-regression",
    ]
    if PER_SYMBOL.is_file():
        cmd.extend(["--per-symbol-settings", str(PER_SYMBOL)])
    for v in extra_v:
        cmd.extend(["-v", v])
    return cmd


def _copy_control_run() -> Path:
    dest = RUNS_DIR / CONTROL_ID
    dest.mkdir(parents=True, exist_ok=True)
    if not CTRL_SRC.is_dir():
        raise FileNotFoundError(f"missing control run dir: {CTRL_SRC}")
    for pat in (
        "RL_Closed_*.csv",
        "RL_Summary_*.csv",
        "RL_EquityMeta_*.csv",
        "RL_Report_*.csv",
        "RL_EquityCurve_*.csv",
    ):
        src = _find_latest(CTRL_SRC, pat)
        if src and src.is_file():
            shutil.copy2(src, dest / src.name)
    return dest


def run_live(py: str, arm: dict[str, Any], workers: int, skip_existing: bool) -> dict[str, Any]:
    arm_dir = RUNS_DIR / arm["id"]
    arm_dir.mkdir(parents=True, exist_ok=True)
    if arm.get("reuse"):
        _copy_control_run()
    closed = _find_latest(arm_dir, "RL_Closed_*.csv")
    if (skip_existing or arm.get("reuse")) and closed and closed.stat().st_size > 0:
        trades = load_trades(closed)
        return {
            "arm": arm,
            "ok": len(trades) > 0,
            "skipped": True,
            "closed": closed,
            "trades": trades,
            "stamp": closed.stem.split("_")[-1] if closed else "",
            "summary": _find_latest(arm_dir, "RL_Summary_*.csv"),
            "equity_meta": _find_latest(arm_dir, "RL_EquityMeta_*.csv"),
            "report": _find_latest(arm_dir, "RL_Report_*.csv"),
            "elapsed_s": 0.0,
        }

    cmd = build_cmd(py, arm_dir, workers, arm.get("extra_v") or [])
    log_path = arm_dir / "run.log"
    t0 = time.time()
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write("CMD: " + " ".join(cmd) + "\n\n")
        log.flush()
        proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(ROOT))
    closed = _find_latest(arm_dir, "RL_Closed_*.csv")
    trades = load_trades(closed) if closed else []
    return {
        "arm": arm,
        "ok": proc.returncode == 0 and len(trades) > 0,
        "skipped": False,
        "closed": closed,
        "trades": trades,
        "stamp": closed.stem.split("_")[-1] if closed else "",
        "elapsed_s": time.time() - t0,
        "exit_code": proc.returncode,
        "summary": _find_latest(arm_dir, "RL_Summary_*.csv"),
        "equity_meta": _find_latest(arm_dir, "RL_EquityMeta_*.csv"),
        "report": _find_latest(arm_dir, "RL_Report_*.csv"),
    }


def _load_arm_from_disk(arm: dict[str, Any]) -> dict[str, Any]:
    arm_dir = RUNS_DIR / arm["id"]
    if arm.get("reuse") and not _find_latest(arm_dir, "RL_Closed_*.csv"):
        _copy_control_run()
    closed = _find_latest(arm_dir, "RL_Closed_*.csv")
    if not closed or not closed.is_file():
        return {"arm": arm, "ok": False, "skipped": True, "trades": [], "stamp": ""}
    trades = load_trades(closed)
    return {
        "arm": arm,
        "ok": len(trades) > 0,
        "skipped": True,
        "closed": closed,
        "trades": trades,
        "stamp": closed.stem.split("_")[-1],
        "summary": _find_latest(arm_dir, "RL_Summary_*.csv"),
        "equity_meta": _find_latest(arm_dir, "RL_EquityMeta_*.csv"),
        "report": _find_latest(arm_dir, "RL_Report_*.csv"),
    }


def _stamp_closed_copies(packed: list[dict[str, Any]]) -> list[Path]:
    closed_dir = OUT_DIR / "closed"
    closed_dir.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    for p in packed:
        src = p.get("closed")
        if not src or not Path(src).is_file():
            continue
        src = Path(src)
        dest = closed_dir / f"{p['arm']['id']}_{src.name}"
        shutil.copy2(src, dest)
        out.append(dest)
    return out


def _md_split(p: dict[str, Any], key: str) -> str:
    m = p[key]
    return (
        f"N={m['n']} WR={m['wr']:.1f}% Avg={m['avg_pnl']:.2f}% WO_MAX={m['wo_max']:.2f}% "
        f"PF={m['pf']:.2f} AnnROR={fmt_n(m['ann_ror'], 2)} MaxDD_overlay={fmt_n(m['max_dd'], 2)} "
        f"avg_days={m.get('avg_days', 0):.1f}"
    )


def _guard_n(aid: str, vis: str, nis: str, cand: dict[str, Any], ctrl: dict[str, Any]) -> tuple[str, str]:
    """KEEP-style labels require IS quality without a collapsed trade count."""
    cn, nn = ctrl["m_is"]["n"], cand["m_is"]["n"]
    if cn > 0 and nn < 0.75 * cn and vis in ("KEEP", "LEAN KEEP"):
        return "HOLD", nis + f"; N collapsed {nn} vs ctrl {cn} (<75%) — not a keep"
    return vis, nis


def _arm_verdict(aid: str, verdicts: dict[str, dict[str, tuple[str, str]]]) -> str:
    vis, nis = verdicts[aid]["is"]
    voos, noos = verdicts[aid]["oos"]
    if vis in ("KEEP", "LEAN KEEP") and voos == "DISMISS":
        return f"**`{aid}` HOLD (OOS soft)** IS `{vis}` ({nis}); OOS `{voos}` ({noos})."
    if vis in ("KEEP", "LEAN KEEP"):
        return (
            f"**`{aid}` {vis}** IS `{vis}` ({nis}); OOS `{voos}` ({noos}). "
            "Research candidate ≠ gold ≠ DailyRun."
        )
    if vis == "DISMISS":
        return f"**`{aid}` DISMISS** IS `{vis}` ({nis}); OOS `{voos}` ({noos})."
    return f"**`{aid}` HOLD** IS `{vis}` ({nis}); OOS `{voos}` ({noos})."


def _decision(verdicts: dict[str, dict[str, tuple[str, str]]]) -> str:
    keepish = {"KEEP", "LEAN KEEP"}
    is_keep = [aid for aid in CAND_IDS if verdicts[aid]["is"][0] in keepish]
    is_hold = [aid for aid in CAND_IDS if verdicts[aid]["is"][0] == "HOLD"]
    is_dismiss = [aid for aid in CAND_IDS if verdicts[aid]["is"][0] == "DISMISS"]
    bits = "; ".join(f"{aid}={verdicts[aid]['is'][0]}" for aid in CAND_IDS)
    if is_keep:
        oos_soft = [aid for aid in is_keep if verdicts[aid]["oos"][0] == "DISMISS"]
        if oos_soft:
            return (
                f"**HOLD**. IS looked better for {', '.join(is_keep)} but OOS softened for "
                f"{', '.join(oos_soft)}. Do not retune OOS. Research-only. Not DailyRun. Not gold."
            )
        return (
            f"IS keepish: {', '.join(is_keep)}. OOS report-only. "
            "Research candidate ≠ gold ≠ DailyRun. Do not wire DailyRun from this stamp."
        )
    return (
        f"**HOLD — do not adopt a knob from this stamp yet.** No IS KEEP/LEAN KEEP ({bits}). "
        f"DISMISS={', '.join(is_dismiss) or 'none'}; HOLD={', '.join(is_hold) or 'none'}. "
        "Research-only. Not DailyRun. Not gold."
    )


def write_closed_html(closed_csv: Path, out_html: Path, *, title: str, arm_id: str, knob: str) -> Path:
    rows: list[dict[str, str]] = []
    with closed_csv.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        for raw in reader:
            rows.append({k: (v if v is not None else "") for k, v in raw.items()})
    prefer = [
        "SYMBOL",
        "DATE OPENED",
        "DATE CLOSED",
        "ENTRY PRICE",
        "EXIT PRICE",
        "PNL %",
        "PNL_DOLLARS",
        "DAYS HELD",
        "EXIT TYPE",
        "ORIGINAL STOP",
        "MAX GAIN",
        "MAE",
    ]
    cols = [c for c in prefer if c in fieldnames]
    for c in fieldnames:
        if c not in cols:
            cols.append(c)
    cols = cols[:16]

    def _sort_type(name: str) -> str:
        u = name.upper()
        if "DATE" in u:
            return "date"
        if any(x in u for x in ("PNL", "PRICE", "DAYS", "GAIN", "MAE", "STOP", "TARGET", "%")):
            return "num"
        return "text"

    th = "".join(sortable_th(c, _sort_type(c)) for c in cols)
    body = "".join(
        "<tr>" + "".join(f"<td>{html_mod.escape(str(r.get(c, '')))}</td>" for c in cols) + "</tr>"
        for r in rows
    )
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>{html_mod.escape(title)}</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; --accent:#5b9fd4; }}
body{{margin:0;font-family:ui-sans-serif,system-ui,Segoe UI,sans-serif;background:var(--bg);color:var(--text)}}
header,main{{max-width:1600px;margin:0 auto;padding:1rem}}
.muted{{color:var(--muted)}}
.callout{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem}}
table{{border-collapse:collapse;width:100%;font-size:.72rem}}
th,td{{border-bottom:1px solid var(--line);padding:.3rem .35rem;text-align:right;white-space:nowrap}}
th:first-child,td:first-child{{text-align:left}}
{SORTABLE_TH_CSS.replace('th.sortable-th:hover{{background:#e8e4d8}}', 'th.sortable-th:hover{{background:#2a3545}}')}
</style></head><body>
<header><h1>{html_mod.escape(title)}</h1>
<p class="muted">Arm <code>{html_mod.escape(arm_id)}</code> knob <code>{html_mod.escape(knob)}</code>. N={len(rows)}. Click headers to sort.</p>
<div class="callout"><strong>What you asked</strong>
<pre style="white-space:pre-wrap">{html_mod.escape(REQUEST_PROMPT.strip())}</pre>
<p><strong>In plain English:</strong> {html_mod.escape(LAYMAN_TRANSLATION.strip())}</p></div>
</header>
<main><div style="overflow-x:auto"><table class="sortable"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div></main>
{SORTABLE_TABLE_SCRIPT}
</body></html>"""
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(html, encoding="utf-8")
    return out_html


def write_compare_html(packed: list[dict[str, Any]], verdicts: dict[str, dict[str, tuple[str, str]]], *, paul_note: str) -> Path:
    by_id = {p["arm"]["id"]: p for p in packed}
    baseline = by_id[CONTROL_ID]
    th_std = "".join(
        sortable_th(a, b)
        for a, b in filter_html_compare_columns(
            [
                ("Arm", "text"),
                ("Univ N", "num"),
                ("Trades", "num"),
                ("WR%", "num"),
                ("Sheet PnL $", "num"),
                ("Total PnL $", "num"),
                ("Avg PnL%", "num"),
                ("Avg% w/o max", "num"),
                ("Avg win%", "num"),
                ("Avg loss%", "num"),
                ("PF", "num"),
                ("Ann ROR%", "num"),
                ("Max DD%", "num"),
                ("Calmar", "num"),
                ("Sharpe", "num"),
                ("Expect $", "num"),
                ("Avg days", "num"),
                ("Cap days", "num"),
                ("PPCD", "num"),
                ("Lose streak", "num"),
                ("Trades/yr", "num"),
                ("Mean Paul", "num"),
                ("Mean FIT", "num"),
                ("Mean robust FIT", "num"),
                ("Max UW days", "num"),
                ("Δ Sheet $ vs ctrl", "num"),
                ("Δ Avg% vs ctrl", "num"),
                ("Δ WR vs ctrl", "num"),
                ("Δ PF vs ctrl", "num"),
                ("Δ Ann ROR vs ctrl", "num"),
                ("Δ Max DD vs ctrl", "num"),
                ("Δ Calmar vs ctrl", "num"),
                ("IS pick", "text"),
            ]
        )
    )
    sections = []
    for split_key, split_title in (("m_is", "IS"), ("m_oos", "OOS (report-only)"), ("m_full", "FULL book")):
        body = "".join(compare_row(p, split_key, baseline, "", CONTROL_ID) for p in packed)
        sections.append(
            f'<section><h2>Post-hint A/B — {split_title}</h2>'
            f'<p class="muted">Delta versus control (+20% then 60 trading days). '
            f"Click column headers to sort.</p>"
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{th_std}</tr></thead>'
            f"<tbody>{body}</tbody></table></div></section>"
        )
    knob_th = "".join(
        sortable_th(a, b)
        for a, b in (
            ("Arm", "text"),
            ("Kind", "text"),
            ("Knob", "text"),
            ("N full", "num"),
            ("Avg days", "num"),
            ("IS pick", "text"),
        )
    )
    knob_rows = []
    for p in packed:
        arm = p["arm"]
        aid = arm["id"]
        is_pick = "—" if aid == CONTROL_ID else verdicts[aid]["is"][0]
        knob_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(aid)}</td>"
            f"<td>{html_mod.escape(arm.get('kind',''))}</td>"
            f"<td>{html_mod.escape(arm.get('knob',''))}</td>"
            f"<td>{p['m_full']['n']}</td>"
            f"<td>{p['m_full'].get('avg_days', 0):.1f}</td>"
            f"<td>{html_mod.escape(is_pick)}</td></tr>"
        )
    pw_th = "".join(
        sortable_th(a, b)
        for a, b in filter_html_compare_columns(
            [
                ("Pair (B − A)", "text"),
                ("Δ Trades", "num"),
                ("Δ Avg%", "num"),
                ("Δ WO_MAX", "num"),
                ("Δ WR", "num"),
                ("Δ PF", "num"),
                ("Δ Sheet $", "num"),
                ("Δ Ann ROR", "num"),
                ("Δ Max DD", "num"),
            ]
        )
    )
    pairs = [(f"{cid} − {CONTROL_ID}", by_id[CONTROL_ID], by_id[cid]) for cid in CAND_IDS]
    pw_sections = []
    for split_key, split_title in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
        rows = "".join(pairwise_delta_row(a, b, split_key, lbl) for lbl, a, b in pairs)
        pw_sections.append(
            f'<section><h2>Pairwise deltas — {split_title}</h2>'
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{pw_th}</tr></thead>'
            f"<tbody>{rows}</tbody></table></div></section>"
        )
    verdict_lis = "".join(f"<li>{_arm_verdict(aid, verdicts)}</li>" for aid in CAND_IDS)
    n_univ = _count_full_univ()
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL post-hint A/B — {STAMP}</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; --accent:#5b9fd4; --ctrl:#243044; }}
body{{margin:0;font-family:ui-sans-serif,system-ui,Segoe UI,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header,main{{max-width:1400px;margin:0 auto;padding:1rem}}
h1{{font-size:1.35rem;margin:0 0 .35rem}}
h2{{font-size:1.05rem;color:var(--accent)}}
.muted{{color:var(--muted);font-size:.92rem}}
.callout{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem;margin:.75rem 0}}
section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem;margin:1rem 0}}
.table-wrap{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:.78rem;min-width:1100px}}
th,td{{border-bottom:1px solid var(--line);padding:.35rem .4rem;text-align:right}}
th:first-child,td:first-child,td:nth-child(3){{text-align:left}}
tr.ctrl-row{{background:var(--ctrl)}}
pre{{white-space:pre-wrap;font-size:.82rem}}
{SORTABLE_TH_CSS.replace('th.sortable-th:hover{{background:#e8e4d8}}', 'th.sortable-th:hover{{background:#2a3545}}')}
</style></head><body>
<header>
<h1>Rocket Launcher post-hint A/B</h1>
<p class="muted">Stamp <code>rl_post_hints_ab_{STAMP}</code>. Control reused from pct20_d60
(stamp 260905205015). Universe: full OHLC pool ({n_univ} files). Research only. Not gold. Not DailyRun.</p>
</header>
<main>
<div class="callout"><strong>What you asked</strong>
<pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>
<p><strong>In plain English:</strong> {html_mod.escape(LAYMAN_TRANSLATION.strip())}</p></div>
<div class="callout"><strong>Paul note:</strong> {html_mod.escape(paul_note)}
<ul>{verdict_lis}</ul>
<p>{html_mod.escape(_decision(verdicts))}</p></div>
<section><h2>Arm knobs</h2>
<p class="muted">Everything else stays on the control freeze. Click headers to sort.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{knob_th}</tr></thead>
<tbody>{''.join(knob_rows)}</tbody></table></div></section>
{''.join(sections)}
{''.join(pw_sections)}
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>"""
    out_path = OUT_DIR / "compare.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path


def write_docs(
    packed: list[dict[str, Any]],
    verdicts: dict[str, dict[str, tuple[str, str]]],
    closed: list[Path],
    html_path: Path,
    closed_htmls: list[Path],
) -> None:
    by_id = {p["arm"]["id"]: p for p in packed}
    n_univ = _count_full_univ()
    lines = [
        f"# BASELINE — `rl_post_hints_ab_{STAMP}`",
        "",
        "**Status:** RESEARCH only. One-knob ENTRY or EXIT arms on the frozen wide-universe book.",
        "**Control:** Simple Moving Average (SMA) envelope TARGET off; timed exit +20% then 60 trading days "
        "(`pct20_d60`, closed stamp `260905205015` from `rl_no_sma_target_exit_ab_20260905`).",
        "Not gold. Not DailyRun. Do not wire `run_rl.bat`.",
        "",
        "## What you asked",
        "",
        "```",
        REQUEST_PROMPT.strip(),
        "```",
        "",
        "## In plain English",
        "",
        LAYMAN_TRANSLATION.strip(),
        "",
        "## Universe vs DailyRun",
        "",
        f"- This stamp uses the full OHLC pool under `data/newdata/data` (**{n_univ}** files). It is not shrunk.",
        "- `DailyRun.bat` still calls `run_rl.bat`, which loads `drive/universes/RL_universe.csv` "
        "(59 names) with `rl_too_high=0`, `rl_exit_percent=0.40`, `rl_exit_days=30`, and no volume floors. "
        "That production file was not changed and is not this control.",
        "- The universe study said keep the external ~1,126 major-index pool and do not add "
        "performance filters. Entry and exit tests here use that pool.",
        "- IS = `entry_date < 2024-01-01`. OOS is report-only. No OOS retune.",
        "- Selection bias: arms were chosen from rule-based ImproveHints "
        "(`drive/RL_ImproveHints_260924183606.md`, production 59-name run) plus engine knobs "
        "that recent wide-universe stamps had not already dismissed. Hints are hypotheses, not a keep.",
        "",
        "## Freeze (control)",
        "",
        "| Knob | Value |",
        "|------|-------|",
        "| `rl_mode` / `indicator_buy` / zones | true / off / off |",
        "| `rl_sma_qual` | 1 |",
        "| ATR bands / `rl_slope_threshold` | off / 0 |",
        f"| `rl_dip_pct` | {HOUSE_DIP} |",
        f"| `rl_expansion` | {HOUSE_EXP} |",
        f"| `rl_stop_pct` | {HOUSE_STOP} (signal-day low × 0.934) |",
        "| `rl_target_pct` / `rl_sma_target_off` | 1.2 / 1 (target not a live exit) |",
        f"| `rl_cut_the_losers` | {HOUSE_CUT} (off) |",
        "| `rl_exit_percent` / `rl_exit_days` | 0.20 / 60 |",
        f"| `rl_too_high` | {TH13} |",
        f"| `rl_min_avg_vol` / `rl_min_trigger_vol` | {MIN_AVG_VOL} / {MIN_TRIGGER_VOL} |",
        "| `rl_post_target_reentry_bars` | 0 |",
        "| `rl_acc_min` / `rl_acc_count` | 8 / 10 |",
        "| `rl_50_sma_lookback` | 4 |",
        "| `rl_shock_threshold` | 0 (off) |",
        "",
        "## Arms",
        "",
        "| Arm | Kind | Knob |",
        "|-----|------|------|",
        "| `control` | — | freeze above |",
    ]
    for c in CANDIDATES:
        lines.append(f"| `{c['id']}` | {c['kind']} | `{c['knob']}` — {c['label']} |")
    lines.extend(
        [
            "",
            "`restack` sets two fields that define one policy (window + mode). "
            "Cooldown `mode=none` was already DISMISS on the tradable book (`rl_post_target_reentry_tradable_20260828`) "
            "and was not repeated. Default mode `stop_loss` would also change the stop, so it was not used alone.",
            "",
            "## Not re-run (already dismissed or flat on a recent stamp)",
            "",
            "- Expansion 1.15 / 1.16 / 1.17 — DISMISS (`rl_expansion_115_116_117_ab_20260924`).",
            "- SMA envelope target on, with or without the 60-day clock — DISMISS.",
            "- Calendar max-hold 150 / 200 / 250 — DISMISS or HOLD.",
            "- Tighter dip band — DISMISS or HOLD (`rl_dip_pct_ab_20260923`).",
            "- Partials, break-even runners, profit-protect matrix A–L — DISMISS on average return.",
            "- Chandelier and lock-in trails — DISMISS.",
            "- Stop percent grid and fixed entry stops — DISMISS (`rl_stop_ab_20260826`).",
            "- Slope gate 0.05 / 0.0643 — PO DISMISS.",
            "- Performance universe filters (trade count, expectancy, +20% hit rate, ATR/volume screens, sector bans) — out of scope.",
            "",
            "## Results",
            "",
            "| Arm | Stamp | N_full | OK |",
            "|-----|-------|--------|-----|",
        ]
    )
    for p in packed:
        lines.append(
            f"| `{p['arm']['id']}` | `{p.get('stamp','')}` | {p['m_full']['n']} | {'yes' if p.get('ok') else 'no'} |"
        )
    lines.extend(["", "## Split metrics", ""])
    for aid in (CONTROL_ID, *CAND_IDS):
        lines.append(f"- **{aid} IS:** {_md_split(by_id[aid], 'm_is')}")
        lines.append(f"- **{aid} OOS:** {_md_split(by_id[aid], 'm_oos')}")
        lines.append(f"- **{aid} FULL:** {_md_split(by_id[aid], 'm_full')}")
    lines.extend(["", "## Verdict", ""])
    for aid in CAND_IDS:
        lines.append(f"- {_arm_verdict(aid, verdicts)}")
    lines.extend(["", f"**Decision:** {_decision(verdicts)}", "", "## Closed copies", ""])
    for c in closed:
        lines.append(f"- `{c.as_posix()}`")
    lines.extend(["", "## Closed HTML", ""])
    for c in closed_htmls:
        lines.append(f"- `{c.as_posix()}`")
    lines.extend(["", f"Compare: `{html_path.as_posix()}`", ""])
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary = [
        f"# SUMMARY — `rl_post_hints_ab_{STAMP}`",
        "",
        "## What you asked",
        "",
        REQUEST_PROMPT.strip(),
        "",
        "## In plain English",
        "",
        LAYMAN_TRANSLATION.strip(),
        "",
        f"**Decision:** {_decision(verdicts)}",
        "",
    ]
    for aid in CAND_IDS:
        summary.append(f"- {_arm_verdict(aid, verdicts)}")
    summary.append("")
    for aid in (CONTROL_ID, *CAND_IDS):
        summary.append(f"- {aid} FULL: {_md_split(by_id[aid], 'm_full')}")
    summary.extend(["", f"Compare: `{html_path.as_posix()}`", ""])
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(summary) + "\n", encoding="utf-8")

    plan = [
        f"# AB_PLAN — `rl_post_hints_ab_{STAMP}`",
        "",
        "One hypothesis per arm. Control freeze unchanged except the named knob.",
        f"Universe N={n_univ}. IS before 2024-01-01. OOS report-only.",
        "",
    ]
    for c in CANDIDATES:
        plan.append(f"- **{c['id']}** ({c['kind']}): {c['label']}. Knob `{c['knob']}`.")
    (OUT_DIR / "AB_PLAN.md").write_text("\n".join(plan) + "\n", encoding="utf-8")


def summarize(packed: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {p["arm"]["id"]: p for p in packed}
    control = by_id[CONTROL_ID]
    verdicts: dict[str, dict[str, tuple[str, str]]] = {}
    for aid in CAND_IDS:
        vis, nis = verdict_vs_control(by_id[aid], control, "m_is")
        vis, nis = _guard_n(aid, vis, nis, by_id[aid], control)
        voos, noos = verdict_vs_control(by_id[aid], control, "m_oos")
        verdicts[aid] = {"is": (vis, nis), "oos": (voos, noos)}
    bits = "; ".join(f"{aid} IS={verdicts[aid]['is'][0]}" for aid in CAND_IDS)
    paul_note = (
        f"{bits}. Independent one-knob arms on frozen +20%/60d wide-universe control. "
        "OOS report-only. Research-only. Not DailyRun. Not gold."
    )
    html_path = write_compare_html(packed, verdicts, paul_note=paul_note)
    closed = _stamp_closed_copies(packed)
    write_metrics_csv(packed, "", OUT_DIR / "metrics_all.csv")
    closed_htmls: list[Path] = []
    for p in packed:
        src = p.get("closed")
        if not src or not Path(src).is_file():
            continue
        arm = p["arm"]
        dest_csv = next((c for c in closed if c.name.startswith(arm["id"] + "_")), Path(src))
        ch = write_closed_html(
            dest_csv,
            OUT_DIR / "closed" / f"{arm['id']}_closed.html",
            title=f"RL Closed — {arm['id']}",
            arm_id=arm["id"],
            knob=str(arm.get("knob") or ""),
        )
        closed_htmls.append(ch)
    write_docs(packed, verdicts, closed, html_path, closed_htmls)
    print(f"[{TAG}] Wrote {html_path}", flush=True)
    return {"verdicts": verdicts, "html": html_path, "closed_htmls": closed_htmls}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    skip_existing = args.skip_existing or args.summarize_only
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    arms = _arm_defs()
    if not arms[0]["symbols"]:
        print(f"[{TAG}] Missing OHLC universe", flush=True)
        return 1
    py = _resolve_python()
    runs: list[dict[str, Any]] = []
    if args.summarize_only:
        for arm in arms:
            runs.append(_load_arm_from_disk(arm))
    else:
        ctrl = next(a for a in arms if a["id"] == CONTROL_ID)
        print(f"[{TAG}] control reuse ...", flush=True)
        runs.append(run_live(py, ctrl, args.workers, True))
        live = [a for a in arms if not a.get("reuse")]
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
            futs = {ex.submit(run_live, py, arm, args.workers, skip_existing): arm for arm in live}
            for fut in as_completed(futs):
                arm = futs[fut]
                run = fut.result()
                print(
                    f"[{TAG}] {arm['id']} ok={run['ok']} n={len(run.get('trades') or [])} "
                    f"elapsed={run.get('elapsed_s', 0):.0f}s exit={run.get('exit_code')}",
                    flush=True,
                )
                runs.append(run)
    runs.sort(key=lambda r: ARM_ORDER.get(r["arm"]["id"], 99))
    if not all(r.get("ok") for r in runs):
        print(f"[{TAG}] One or more arms failed", flush=True)
        for r in runs:
            print(f"  {r['arm']['id']}: ok={r.get('ok')} exit={r.get('exit_code')}", flush=True)
        return 1
    packed = [pack_result(r) for r in runs]
    for p, r in zip(packed, runs):
        p["ok"] = r.get("ok")
        p["closed"] = r.get("closed")
        p["stamp"] = r.get("stamp")
    summarize(packed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
