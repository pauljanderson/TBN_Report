#!/usr/bin/env python3
"""RL EXIT A/B: SMA envelope TARGET off (control) vs original 20% daily-SMA envelope ON.

"20 DSMA" = original Rocket Launcher target: yesterday's 50-day SMA × rl_target_pct=1.20
(~20% above the daily SMA envelope), exit type TARGET, updated while the trade is open.

Control (reuse): no-SMA-target +20% then 60 trading bars from
  rl_no_sma_target_exit_ab_20260905 / runs / pct20_d60
  (rl_sma_target_off=1, rl_target_pct=1.20 hits-only, rl_exit_percent=0.20, rl_exit_days=60).
  Clock starts AFTER first +20% hit; rl_exit_days counts trading bars (time_counter).

Candidate (sma_env) — SAME freeze EXCEPT rl_sma_target_off=0:
  SMA50×1.20 TARGET is live and races the existing +20%/60-bar clock
  (stop first; then whichever of TARGET vs RL_EXIT_DAYS hits first).
  Entries and the +20%/60d clock are unchanged. Not a REPLACE of the clock.

IS = entry < 2024-01-01; OOS report-only; no OOS retune.
Research-only. Not gold. Not DailyRun.

Usage:
  python tools/rl_sma_envelope_target_vs_pct20_d60_ab.py --workers 8
  python tools/rl_sma_envelope_target_vs_pct20_d60_ab.py --summarize-only
  python tools/rl_sma_envelope_target_vs_pct20_d60_ab.py --skip-existing --workers 8
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import shutil
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
DATA_DIR = ROOT / "data" / "newdata" / "data"
STAMP = "20260924"
OUT_DIR = DRIVE / "paul_experiments" / f"rl_sma_envelope_target_vs_pct20_d60_ab_{STAMP}"
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
TH13 = 1.13
MIN_AVG_VOL = 10_000
MIN_TRIGGER_VOL = 5_000
CTRL_EXIT_DAYS = 60
CTRL_EXIT_PCT = 0.20
RL_TARGET_PCT = 1.20

CONTROL_ID = "control"
CANDIDATE_ID = "sma_env"
CAND_IDS = [CANDIDATE_ID]
ARM_ORDER = {CONTROL_ID: 0, CANDIDATE_ID: 1}
TAG = "RL-SMA-ENVELOPE-TARGET-VS-PCT20-D60"

REQUEST_PROMPT = """\
can you run an AB test with the orignal 20 DSMA moving average envelope as a target vs. control
"""

LAYMAN_TRANSLATION = """\
Control turns off the old “sell when price reaches about 20% above the 50-day moving average” \
target, and instead sells 60 trading days after the trade is up 20% from the buy price. This \
test turns that moving-average envelope target back on and lets it race the same +20%/60-day \
exit — first one to hit closes the trade. Same stock list and entries.
"""

INTERPRETATION = """\
"20 DSMA" = the original Rocket Launcher target: yesterday's 50-day SMA × rl_target_pct=1.20 \
(~20% above the daily SMA envelope), exit type TARGET, updated while the trade is open. \
Control research freeze has this OFF (rl_sma_target_off=1) and exits via +20% then 60 trading \
bars (RL_EXIT_DAYS). This arm sets rl_sma_target_off=0 so that TARGET is live again.
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


def _full_univ_symbols() -> list[str]:
    if not DATA_DIR.is_dir():
        return []
    return sorted(p.stem.upper() for p in DATA_DIR.glob("*.csv"))


def _count_full_univ() -> int:
    return len(_full_univ_symbols())


def _entry_freeze_v(*, sma_target_off: int) -> list[str]:
    """Shared freeze; arms differ only on SMA envelope TARGET (rl_sma_target_off)."""
    return [
        "rl_mode=true",
        "brt_zones=false",
        "yh_zones=false",
        "wpbr_zones=false",
        "indicator_buy=off",
        "rl_sma_qual=1",
        "ATR_LOW=off",
        "ATR_HIGH=off",
        "rl_slope_threshold=0",
        f"rl_dip_pct={HOUSE_DIP}",
        "rl_expansion=1.163",
        f"rl_stop_pct={HOUSE_STOP}",
        f"rl_target_pct={RL_TARGET_PCT}",
        f"rl_sma_target_off={sma_target_off}",
        f"rl_cut_the_losers={HOUSE_CUT}",
        f"rl_exit_percent={CTRL_EXIT_PCT}",
        f"rl_exit_days={CTRL_EXIT_DAYS}",
        "rl_exit_calendar_days=0",
        "rl_max_hold_bars=0",
        "rl_max_hold_calendar_days=0",
        "rl_post_target_reentry_bars=0",
        f"rl_too_high={TH13}",
        f"rl_min_avg_vol={MIN_AVG_VOL}",
        f"rl_min_trigger_vol={MIN_TRIGGER_VOL}",
    ]


def _arm_defs() -> list[dict[str, Any]]:
    syms = _full_univ_symbols()
    n = len(syms)
    return [
        {
            "id": CONTROL_ID,
            "label": (
                f"Control pct20_d60 (SMA TARGET off; +20% then {CTRL_EXIT_DAYS} trading bars)"
            ),
            "role": "control",
            "symbols": syms,
            "univ_n": n,
            "sma_target_off": 1,
            "exit_days": CTRL_EXIT_DAYS,
            "extra_v": _entry_freeze_v(sma_target_off=1),
            "reuse": True,
        },
        {
            "id": CANDIDATE_ID,
            "label": (
                f"sma_env SMA50×{RL_TARGET_PCT:.2f} TARGET ON, racing +20%/{CTRL_EXIT_DAYS}d"
            ),
            "role": "candidate",
            "symbols": syms,
            "univ_n": n,
            "sma_target_off": 0,
            "exit_days": CTRL_EXIT_DAYS,
            "extra_v": _entry_freeze_v(sma_target_off=0),
            "reuse": False,
        },
    ]


def _exit_mix(trades: list[dict[str, Any]]) -> dict[str, int]:
    """Count EXIT TYPE for TARGET / RL_EXIT_DAYS / STOP* / other."""
    c: Counter[str] = Counter()
    for t in trades or []:
        et = str(
            t.get("exit") or t.get("EXIT TYPE") or t.get("exit_type") or ""
        ).strip().upper()
        if et == "TARGET":
            c["TARGET"] += 1
        elif et == "RL_EXIT_DAYS":
            c["RL_EXIT_DAYS"] += 1
        elif et == "RL_EXIT_CAL":
            c["RL_EXIT_CAL"] += 1
        elif et in ("STOP_LOSS", "GAP_DOWN", "TRAIL_STOP", "TRAIL_STOP2") or et.startswith(
            "STOP"
        ):
            c["STOP"] += 1
        else:
            c["OTHER"] += 1
            if et:
                c[f"OTHER:{et}"] += 1
    return {
        "TARGET": int(c.get("TARGET", 0)),
        "RL_EXIT_DAYS": int(c.get("RL_EXIT_DAYS", 0)),
        "RL_EXIT_CAL": int(c.get("RL_EXIT_CAL", 0)),
        "STOP": int(c.get("STOP", 0)),
        "OTHER": int(c.get("OTHER", 0)),
        "N": len(trades or []),
    }


def _trade_days_held(t: dict[str, Any]) -> int:
    raw = t.get("days")
    if raw is None or raw == "":
        raw = t.get("DAYS HELD") or t.get("days_held") or t.get("hold_days") or 0
    try:
        return int(float(str(raw).strip() or 0))
    except ValueError:
        return 0


def _max_days_held(trades: list[dict[str, Any]]) -> int:
    mx = 0
    for t in trades or []:
        v = _trade_days_held(t)
        if v > mx:
            mx = v
    return mx


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
    if skip_existing and closed and closed.stat().st_size > 0:
        trades = load_trades(closed)
        if trades:
            return {
                "arm": arm,
                "ok": True,
                "skipped": True,
                "closed": closed,
                "trades": trades,
                "stamp": closed.stem.split("_")[-1],
                "summary": _find_latest(arm_dir, "RL_Summary_*.csv"),
                "equity_meta": _find_latest(arm_dir, "RL_EquityMeta_*.csv"),
                "report": _find_latest(arm_dir, "RL_Report_*.csv"),
                "elapsed_s": 0.0,
            }
    if arm.get("reuse"):
        closed = _find_latest(arm_dir, "RL_Closed_*.csv")
        trades = load_trades(closed) if closed else []
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


def _arm_verdict(aid: str, verdicts: dict[str, dict[str, tuple[str, str]]]) -> str:
    vis, nis = verdicts[aid]["is"]
    voos, noos = verdicts[aid]["oos"]
    if vis in ("KEEP", "LEAN KEEP") and voos in ("KEEP", "LEAN KEEP", "HOLD"):
        tag = vis if voos != "DISMISS" else "HOLD (OOS soft)"
        return f"**`{aid}` {tag}** IS `{vis}` ({nis}); OOS `{voos}` ({noos}). Research candidate != gold."
    if vis == "DISMISS":
        return f"**`{aid}` DISMISS** IS `{vis}` ({nis}); OOS `{voos}` ({noos})."
    return f"**`{aid}` HOLD** IS `{vis}` ({nis}); OOS `{voos}` ({noos})."


def _decision(verdicts: dict[str, dict[str, tuple[str, str]]]) -> str:
    keepish = {"KEEP", "LEAN KEEP"}
    vis = verdicts[CANDIDATE_ID]["is"][0]
    voos = verdicts[CANDIDATE_ID]["oos"][0]
    if vis in keepish:
        if voos == "DISMISS":
            return (
                f"**HOLD**. IS looked better for `{CANDIDATE_ID}` but OOS softened. "
                "Do not retune OOS. Research-only — SMA envelope TARGET is not gold."
            )
        return (
            f"IS keepish: `{CANDIDATE_ID}`={vis}. OOS report-only ({voos}). "
            "Research candidate ≠ gold ≠ DailyRun. SMA envelope TARGET is research-only."
        )
    if vis == "DISMISS":
        return (
            f"**DISMISS / do not adopt** the SMA50×1.20 envelope TARGET from this stamp. "
            f"IS `{vis}`; OOS `{voos}`. Research-only."
        )
    return (
        f"**HOLD — do not adopt the SMA50×1.20 envelope TARGET from this stamp yet.** "
        f"IS `{vis}`; OOS `{voos}`. Research-only."
    )


def write_closed_html(
    closed_csv: Path,
    out_html: Path,
    *,
    title: str,
    arm_id: str,
    sma_target_off: int,
    exit_days: int,
) -> Path:
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
        "DAYS_TO_20",
        "20_TO_CLOSE",
        "ORIGINAL STOP",
        "STOP LOSS AT CLOSE",
        "ORIGINAL TARGET",
        "MAX GAIN",
        "MAE",
    ]
    cols = [c for c in prefer if c in fieldnames]
    for c in fieldnames:
        if c not in cols:
            cols.append(c)
    cols = cols[:20]

    def _sort_type(name: str) -> str:
        u = name.upper()
        if "DATE" in u:
            return "date"
        if any(x in u for x in ("PNL", "PRICE", "DAYS", "GAIN", "MAE", "STOP", "TARGET", "AMOUNT", "%", "20_")):
            return "num"
        return "text"

    th = "".join(sortable_th(c, _sort_type(c)) for c in cols)
    body_parts: list[str] = []
    for r in rows:
        tds = "".join(f"<td>{html_mod.escape(str(r.get(c, '')))}</td>" for c in cols)
        body_parts.append(f"<tr>{tds}</tr>")

    row_trades = [{"DAYS HELD": r.get("DAYS HELD", "")} for r in rows]
    max_dh = _max_days_held(row_trades)
    if arm_id == CONTROL_ID:
        exit_note = (
            f"Control: <code>rl_sma_target_off={sma_target_off}</code> (SMA envelope TARGET off). "
            f"<code>rl_exit_percent={CTRL_EXIT_PCT}</code> then "
            f"<code>rl_exit_days={exit_days}</code> trading bars after first +20%. "
            f"Exit mix should be RL_EXIT_DAYS / STOP, not TARGET. Max DAYS HELD={max_dh}."
        )
    else:
        exit_note = (
            f"Candidate: <code>rl_sma_target_off={sma_target_off}</code> so yesterday's "
            f"50-day SMA × <code>rl_target_pct={RL_TARGET_PCT}</code> TARGET is live and races "
            f"the same +{CTRL_EXIT_PCT:.0%} / {exit_days} trading-bar clock "
            f"(stop first; same-bar lowest hit price wins). Max DAYS HELD={max_dh}."
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html_mod.escape(title)}</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; --accent:#5b9fd4; }}
*{{box-sizing:border-box}}
body{{margin:0;font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header{{padding:1.25rem 1rem 0.5rem;max-width:1600px;margin:0 auto}}
h1{{font-size:1.25rem;margin:0 0 .35rem}}
.muted{{color:var(--muted);font-size:.92rem}}
.callout{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem;margin:.75rem 0}}
main{{max-width:1600px;margin:0 auto;padding:0 1rem 2.5rem}}
section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem 1rem;margin:1rem 0}}
.table-wrap{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:.72rem;min-width:900px}}
th,td{{border-bottom:1px solid var(--line);padding:.3rem .35rem;text-align:right;white-space:nowrap}}
th:first-child,td:first-child{{text-align:left}}
{SORTABLE_TH_CSS.replace('th.sortable-th:hover{{background:#e8e4d8}}', 'th.sortable-th:hover{{background:#2a3545}}')}
</style>
</head>
<body>
<header>
<h1>{html_mod.escape(title)}</h1>
<p class="muted">Stamp <code>rl_sma_envelope_target_vs_pct20_d60_ab_{STAMP}</code>. Arm <code>{html_mod.escape(arm_id)}</code>.
Source <code>{html_mod.escape(closed_csv.name)}</code>. N={len(rows)}. Click column headers to sort.</p>
</header>
<main>
<div class="callout">
<strong>What you asked</strong>
<pre style="white-space:pre-wrap;font-size:.82rem">{html_mod.escape(REQUEST_PROMPT.strip())}</pre>
<p><strong>In plain English:</strong> {html_mod.escape(LAYMAN_TRANSLATION.strip())}</p>
</div>
<section>
<h2 style="color:var(--accent);font-size:1.05rem;margin:.2rem 0 .5rem">Closed trades — {html_mod.escape(arm_id)}</h2>
<p class="muted">{exit_note} Research-only. Entries and the +20%/60-bar clock are unchanged.</p>
<p class="muted"><strong>Interpretation:</strong> {html_mod.escape(INTERPRETATION.strip())}</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{th}</tr></thead>
<tbody>{''.join(body_parts)}</tbody></table></div>
</section>
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(html, encoding="utf-8")
    return out_html


def write_compare_html(
    packed: list[dict[str, Any]],
    verdicts: dict[str, dict[str, tuple[str, str]]],
    *,
    paul_note: str,
) -> Path:
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
        note = (
            "Paul/FIT/UW from host Summary + EquityMeta when present. Overlay Max DD ≠ host DD."
            if split_key == "m_full"
            else "Closed overlay $47,500 / $500k. Overlay Max DD ≠ host account DD."
        )
        sections.append(
            f'<section><h2>SMA envelope TARGET vs pct20_d60 — {split_title}</h2>'
            f'<p class="muted">Δ vs control (pct20_d60, SMA TARGET off, +20% then {CTRL_EXIT_DAYS} trading bars). {note} '
            f"Click column headers to sort.</p>"
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{th_std}</tr></thead>'
            f"<tbody>{body}</tbody></table></div></section>"
        )

    knob_th = "".join(
        sortable_th(a, b)
        for a, b in (
            ("Arm", "text"),
            ("rl_sma_target_off", "num"),
            ("rl_target_pct", "num"),
            ("rl_exit_percent", "num"),
            ("rl_exit_days", "num"),
            ("N full", "num"),
            ("Avg days", "num"),
            ("Max DAYS HELD", "num"),
            ("IS pick", "text"),
        )
    )
    knob_rows = []
    for p in packed:
        arm = p["arm"]
        aid = arm["id"]
        days = int(arm.get("exit_days") or 0)
        sma_off = int(arm.get("sma_target_off") or 0)
        trades = p.get("trades") or []
        max_dh = _max_days_held(trades)
        is_pick = verdicts[aid]["is"][0] if aid in verdicts else "—"
        if aid == CONTROL_ID:
            is_pick = "control"
        knob_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(aid)}</td>"
            f"<td>{sma_off}</td>"
            f"<td>{RL_TARGET_PCT:.2f}</td>"
            f"<td>{CTRL_EXIT_PCT:.2f}</td>"
            f"<td>{days}</td>"
            f"<td>{p['m_full']['n']}</td>"
            f"<td>{p['m_full'].get('avg_days', 0):.1f}</td>"
            f"<td>{max_dh}</td>"
            f"<td>{html_mod.escape(is_pick)}</td>"
            "</tr>"
        )
    knobs = (
        f'<section><h2>Arm knobs (EXIT — SMA envelope TARGET on vs off)</h2>'
        f'<p class="muted">Both arms: <code>rl_target_pct={RL_TARGET_PCT}</code>, '
        f"<code>rl_exit_percent={CTRL_EXIT_PCT}</code>, <code>rl_exit_days={CTRL_EXIT_DAYS}</code>, "
        f"same entries. Control: <code>rl_sma_target_off=1</code>. "
        f"Candidate: <code>rl_sma_target_off=0</code> so yesterday's 50-day SMA × 1.20 TARGET "
        f"races the +20%/60-bar clock. Click headers to sort.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{knob_th}</tr></thead>'
        f"<tbody>{''.join(knob_rows)}</tbody></table></div></section>"
    )

    mix_th = "".join(
        sortable_th(a, b)
        for a, b in (
            ("Arm", "text"),
            ("N", "num"),
            ("TARGET", "num"),
            ("RL_EXIT_DAYS", "num"),
            ("STOP", "num"),
            ("OTHER", "num"),
            ("% TARGET", "num"),
            ("% bars clock", "num"),
            ("% STOP", "num"),
        )
    )
    mix_rows = []
    for p in packed:
        aid = p["arm"]["id"]
        mix = _exit_mix(p.get("trades") or [])
        n = mix["N"] or 1
        mix_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(aid)}</td>"
            f"<td>{mix['N']}</td>"
            f"<td>{mix['TARGET']}</td>"
            f"<td>{mix['RL_EXIT_DAYS']}</td>"
            f"<td>{mix['STOP']}</td>"
            f"<td>{mix['OTHER']}</td>"
            f"<td>{100.0 * mix['TARGET'] / n:.1f}</td>"
            f"<td>{100.0 * mix['RL_EXIT_DAYS'] / n:.1f}</td>"
            f"<td>{100.0 * mix['STOP'] / n:.1f}</td>"
            "</tr>"
        )
    exit_mix_sec = (
        f'<section><h2>Exit mix (full book)</h2>'
        f'<p class="muted">Control should be <code>RL_EXIT_DAYS</code> / STOP (TARGET ≈ 0). '
        f"Candidate should show live <code>TARGET</code> racing <code>RL_EXIT_DAYS</code>. "
        f"Click headers to sort.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{mix_th}</tr></thead>'
        f"<tbody>{''.join(mix_rows)}</tbody></table></div></section>"
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
    pairs = [(f"{CANDIDATE_ID} − {CONTROL_ID}", by_id[CONTROL_ID], by_id[CANDIDATE_ID])]
    pw_sections = []
    for split_key, split_title in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
        rows = "".join(pairwise_delta_row(a, b, split_key, lbl) for lbl, a, b in pairs)
        pw_sections.append(
            f'<section><h2>Pairwise deltas — {split_title}</h2>'
            f'<p class="muted">Click headers to sort.</p>'
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{pw_th}</tr></thead>'
            f"<tbody>{rows}</tbody></table></div></section>"
        )

    n_univ = _count_full_univ()
    subtitle = (
        f"Stamp <code>rl_sma_envelope_target_vs_pct20_d60_ab_{STAMP}</code>. "
        f"Control = SMA TARGET off +20% then {CTRL_EXIT_DAYS} <strong>trading bars</strong> "
        f"(reuse pct20_d60). "
        f"Candidate <code>sma_env</code>: same clock, "
        f"<code>rl_sma_target_off=0</code> (yesterday's 50-day SMA × {RL_TARGET_PCT:.2f} TARGET). "
        f"Universe: full OHLC ({n_univ}). Research-only. Not gold / not DailyRun."
    )
    verdict_lis = "".join(f"<li>{_arm_verdict(aid, verdicts)}</li>" for aid in CAND_IDS)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL SMA envelope TARGET vs pct20_d60 A/B — {STAMP}</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; --accent:#5b9fd4; --ctrl:#243044; }}
*{{box-sizing:border-box}}
body{{margin:0;font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header{{padding:1.25rem 1rem 0.5rem;max-width:1400px;margin:0 auto}}
h1{{font-size:1.35rem;margin:0 0 .35rem}}
h2{{font-size:1.05rem;margin:1.25rem 0 .4rem;color:var(--accent)}}
.muted{{color:var(--muted);font-size:.92rem}}
.callout{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem;margin:.75rem 0}}
.req pre{{white-space:pre-wrap;font-family:ui-monospace,Consolas,monospace;font-size:.82rem;margin:.4rem 0 0;color:var(--text)}}
.req .layman{{margin:.55rem 0 0;font-size:.95rem}}
main{{max-width:1400px;margin:0 auto;padding:0 1rem 2.5rem}}
section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem 1rem;margin:1rem 0}}
.table-wrap{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:.78rem;min-width:1100px}}
th,td{{border-bottom:1px solid var(--line);padding:.35rem .4rem;text-align:right}}
th:first-child,td:first-child{{text-align:left}}
tr.ctrl-row{{background:var(--ctrl)}}
{SORTABLE_TH_CSS.replace('th.sortable-th:hover{{background:#e8e4d8}}', 'th.sortable-th:hover{{background:#2a3545}}')}
</style>
</head>
<body>
<header>
<h1>RL SMA envelope TARGET vs +20%/60-bar control</h1>
<p class="muted">{subtitle}</p>
</header>
<main>
<div class="callout req">
<strong>What you asked</strong>
<pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>
<p class="layman"><strong>In plain English:</strong> {html_mod.escape(LAYMAN_TRANSLATION.strip())}</p>
<p class="layman"><strong>Interpretation:</strong> {html_mod.escape(INTERPRETATION.strip())}</p>
</div>
<div class="callout">
<strong>Paul note:</strong> {html_mod.escape(paul_note)}
<ul>{verdict_lis}</ul>
<p>{html_mod.escape(_decision(verdicts))}</p>
<p class="muted">IS primary for KEEP/HOLD/DISMISS. OOS report-only — do not retune. Research-only. EXIT A/B.
<code>rl_sma_target_off=0</code> turns yesterday's 50-day SMA × 1.20 TARGET back on.
The +20% then 60 trading-bar clock stays on both arms. Stop is checked first.</p>
</div>
{knobs}
{exit_mix_sec}
{"".join(sections)}
{"".join(pw_sections)}
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
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
    baseline = [
        f"# BASELINE — `rl_sma_envelope_target_vs_pct20_d60_ab_{STAMP}`",
        "",
        "**Status:** RESEARCH only. EXIT A/B — turn the original SMA envelope TARGET back ON.",
        f"**Control:** SMA envelope TARGET off (`rl_sma_target_off=1`) +{CTRL_EXIT_PCT:.0%} then "
        f"{CTRL_EXIT_DAYS} **trading bars** "
        f"(reuse from `rl_no_sma_target_exit_ab_20260905` / `pct20_d60`).",
        f"**Candidate `{CANDIDATE_ID}`:** SAME freeze except `rl_sma_target_off=0`. "
        f"Yesterday's 50-day SMA × `rl_target_pct={RL_TARGET_PCT}` TARGET races the existing "
        f"+{CTRL_EXIT_PCT:.0%}/{CTRL_EXIT_DAYS}-bar clock (whichever hits first, after stop).",
        "",
        "Not gold. Not DailyRun.",
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
        "## Interpretation",
        "",
        INTERPRETATION.strip(),
        "",
        "## Hypothesis (EXIT A/B)",
        "",
        "Turning the original daily-SMA envelope target back on (SMA50 prior day × 1.20) "
        "may close some trades earlier than waiting 60 trading bars after a +20% gain. "
        "Same entries, same stop, same +20%/60-bar clock. One EXIT knob: `rl_sma_target_off` 1 → 0.",
        "",
        "## Freeze (identical except SMA TARGET)",
        "",
        "| Knob | Control | sma_env |",
        "|------|---------|---------|",
        "| `rl_mode` | true | true |",
        "| zones / `indicator_buy` | off | off |",
        "| `rl_sma_qual` | **1** | **1** |",
        "| ATR / `rl_slope_threshold` | off / **0** | off / **0** |",
        f"| `rl_dip_pct` | **{HOUSE_DIP}** | **{HOUSE_DIP}** |",
        "| `rl_expansion` | **1.163** | **1.163** |",
        f"| `rl_stop_pct` | **{HOUSE_STOP}** | **{HOUSE_STOP}** |",
        f"| `rl_cut_the_losers` | **{HOUSE_CUT}** (off) | **{HOUSE_CUT}** (off) |",
        f"| `rl_too_high` | **{TH13}** | **{TH13}** |",
        f"| `rl_min_avg_vol` | **{MIN_AVG_VOL}** | **{MIN_AVG_VOL}** |",
        f"| `rl_min_trigger_vol` | **{MIN_TRIGGER_VOL}** | **{MIN_TRIGGER_VOL}** |",
        f"| `rl_target_pct` | **{RL_TARGET_PCT}** (hits only) | **{RL_TARGET_PCT}** (live TARGET) |",
        "| `rl_sma_target_off` | **1** | **0** |",
        f"| `rl_exit_percent` | **{CTRL_EXIT_PCT}** | **{CTRL_EXIT_PCT}** |",
        f"| `rl_exit_days` | **{CTRL_EXIT_DAYS}** | **{CTRL_EXIT_DAYS}** |",
        "| `rl_exit_calendar_days` | **0** | **0** |",
        "| `rl_max_hold_bars` | **0** | **0** |",
        "| `rl_max_hold_calendar_days` | **0** | **0** |",
        "| `rl_post_target_reentry_bars` | **0** | **0** |",
        "",
        "## EXIT arms",
        "",
        "| Arm | rl_sma_target_off | Time rule |",
        "|-----|-------------------|-----------|",
        f"| `{CONTROL_ID}` (pct20_d60) | **1** | after +20%, wait {CTRL_EXIT_DAYS} trading bars (`RL_EXIT_DAYS`); no TARGET |",
        f"| `{CANDIDATE_ID}` | **0** | TARGET (SMA50×{RL_TARGET_PCT}) races the same +20%/{CTRL_EXIT_DAYS}d clock |",
        "",
        "## Universe / split",
        "",
        f"- Full OHLC pool under `data/newdata/data` (**{n_univ}**)",
        "- IS = entry < 2024-01-01; OOS report-only; no OOS retune",
        "",
        "## Semantics / race order",
        "",
        "- TARGET price = yesterday's 50-day SMA × `rl_target_pct` (1.20), updated each bar while open.",
        "- Engine: stop first → max-hold knobs (0 here) → same-bar race among SMA TARGET "
        "and timed `RL_EXIT_DAYS` (lowest hit price wins; timed compared at the +20% gate, fill at open).",
        "- `rl_exit_calendar_days` and from-entry max-hold stay 0. Entries unchanged.",
        "",
        "## Exit mix (full book)",
        "",
        "| Arm | N | TARGET | RL_EXIT_DAYS | STOP | OTHER | Max DAYS HELD |",
        "|-----|---|--------|--------------|------|-------|---------------|",
    ]
    for p in packed:
        mix = _exit_mix(p.get("trades") or [])
        arm = p["arm"]
        trades = p.get("trades") or []
        max_dh = _max_days_held(trades)
        baseline.append(
            f"| `{arm['id']}` | {mix['N']} | {mix['TARGET']} | {mix['RL_EXIT_DAYS']} | "
            f"{mix['STOP']} | {mix['OTHER']} | {max_dh} |"
        )
    baseline.extend(
        [
            "",
            "## Results",
            "",
            "| Arm | Stamp | N_full | OK |",
            "|-----|-------|--------|-----|",
        ]
    )
    for p in packed:
        arm = p["arm"]
        baseline.append(
            f"| `{arm['id']}` | `{p.get('stamp','')}` | {p['m_full']['n']} | "
            f"{'yes' if p.get('ok') else 'no'} |"
        )
    baseline.extend(["", "## Split metrics", ""])
    for aid in (CONTROL_ID, *CAND_IDS):
        baseline.append(f"- **{aid} IS:** {_md_split(by_id[aid], 'm_is')}")
        baseline.append(f"- **{aid} OOS:** {_md_split(by_id[aid], 'm_oos')}")
        baseline.append(f"- **{aid} FULL:** {_md_split(by_id[aid], 'm_full')}")
    baseline.extend(["", "## Verdict", ""])
    for aid in CAND_IDS:
        baseline.append(f"- {_arm_verdict(aid, verdicts)}")
    baseline.extend(
        [
            "",
            f"**Decision:** {_decision(verdicts)}",
            "",
            "## Selection-bias note",
            "",
            "One a-priori EXIT variant from Paul's ask (original 20% daily-SMA envelope target "
            "back on vs the frozen no-SMA +20%/60-bar control). Not tuned on OOS. "
            "Control reused Closed from pct20_d60.",
            "",
            "## Closed copies",
            "",
        ]
    )
    for c in closed:
        baseline.append(f"- `{c.as_posix()}`")
    baseline.extend(["", "## Closed HTML", ""])
    for c in closed_htmls:
        baseline.append(f"- `{c.as_posix()}`")
    baseline.extend(["", f"Compare: `{html_path.as_posix()}`", ""])
    (OUT_DIR / "BASELINE.md").write_text("\n".join(baseline) + "\n", encoding="utf-8")

    ab_plan = [
        f"# AB_PLAN — `rl_sma_envelope_target_vs_pct20_d60_ab_{STAMP}`",
        "",
        "## One-change EXIT A/B (SMA envelope TARGET on vs off)",
        "",
        f"- **Control:** `rl_sma_target_off=1`, `rl_exit_percent={CTRL_EXIT_PCT}`, "
        f"`rl_exit_days={CTRL_EXIT_DAYS}` (reuse pct20_d60).",
        f"- **Candidate:** SAME clock and entries, `rl_sma_target_off=0` so "
        f"yesterday's SMA50 × {RL_TARGET_PCT} TARGET is live (exit type TARGET).",
        "- **Engine:** stop first, then TARGET races RL_EXIT_DAYS (lowest same-bar price wins).",
        "- **Frozen:** entries = pct20_d60 freeze; +20%/60-bar clock unchanged; max-hold knobs 0.",
        "- **Split:** IS = entry < 2024-01-01; OOS report-only; no OOS retune.",
        "- **Promotion:** Research-only. Not gold. Not DailyRun.",
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
        "## Interpretation",
        "",
        INTERPRETATION.strip(),
        "",
    ]
    (OUT_DIR / "AB_PLAN.md").write_text("\n".join(ab_plan) + "\n", encoding="utf-8")

    summary = [
        f"# SUMMARY — `rl_sma_envelope_target_vs_pct20_d60_ab_{STAMP}`",
        "",
        f"**Decision:** {_decision(verdicts)}",
        "",
        "**Control:** SMA envelope TARGET off; +20% then 60 trading bars.",
        "**Candidate:** SMA50×1.20 TARGET on, racing that same clock.",
        "",
    ]
    for aid in CAND_IDS:
        summary.append(f"- {_arm_verdict(aid, verdicts)}")
    summary.append("")
    for aid in (CONTROL_ID, *CAND_IDS):
        mix = _exit_mix(by_id[aid].get("trades") or [])
        summary.append(
            f"- {aid} FULL: {_md_split(by_id[aid], 'm_full')} | "
            f"exit_mix TARGET={mix['TARGET']} EXIT_DAYS={mix['RL_EXIT_DAYS']} "
            f"STOP={mix['STOP']} OTHER={mix['OTHER']}"
        )
    summary.extend(
        [
            "",
            f"Compare: `{html_path.as_posix()}`",
            "",
        ]
    )
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(summary), encoding="utf-8")

def summarize(packed: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {p["arm"]["id"]: p for p in packed}
    control = by_id[CONTROL_ID]
    verdicts = {
        aid: {
            "is": verdict_vs_control(by_id[aid], control, "m_is"),
            "oos": verdict_vs_control(by_id[aid], control, "m_oos"),
        }
        for aid in CAND_IDS
    }
    vis = verdicts[CANDIDATE_ID]["is"][0]
    paul_note = (
        f"{CANDIDATE_ID} IS={vis}. EXIT: turn SMA50×1.20 envelope TARGET back on "
        f"(`rl_sma_target_off=0`) so it races the frozen +20%/{CTRL_EXIT_DAYS}-bar clock. "
        "IS primary; OOS report-only — do not retune. Research-only."
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
        days = int(arm.get("exit_days") or 0)
        sma_off = int(arm.get("sma_target_off") if arm.get("sma_target_off") is not None else 1)
        ch = write_closed_html(
            dest_csv,
            OUT_DIR / "closed" / f"{arm['id']}_closed.html",
            title=f"RL Closed — {arm['id']} (sma_target_off={sma_off})",
            arm_id=arm["id"],
            sma_target_off=sma_off,
            exit_days=days,
        )
        closed_htmls.append(ch)

    write_docs(packed, verdicts, closed, html_path, closed_htmls)
    print(
        f"[{TAG}] Wrote {html_path} closed_csv={len(closed)} closed_html={len(closed_htmls)}",
        flush=True,
    )
    for p in packed:
        arm = p["arm"]
        mix = _exit_mix(p.get("trades") or [])
        print(
            f"[{TAG}] {arm['id']}: TARGET={mix['TARGET']} "
            f"EXIT_DAYS={mix['RL_EXIT_DAYS']} STOP={mix['STOP']} OTHER={mix['OTHER']}",
            flush=True,
        )
    return {
        "verdicts": verdicts,
        "packed": packed,
        "html": html_path,
        "closed_htmls": closed_htmls,
        "closed": closed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    skip_existing = args.skip_existing or args.summarize_only

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    arms = _arm_defs()
    if not arms[0]["symbols"]:
        print(f"[{TAG}] Missing OHLC universe under data/newdata/data", flush=True)
        return 1

    py = _resolve_python()
    runs: list[dict[str, Any]] = []
    if args.summarize_only:
        for arm in arms:
            run = _load_arm_from_disk(arm)
            print(
                f"[{TAG}] load {arm['id']} ok={run['ok']} n={len(run.get('trades') or [])}",
                flush=True,
            )
            runs.append(run)
    else:
        ctrl = next(a for a in arms if a["id"] == CONTROL_ID)
        print(f"[{TAG}] starting {ctrl['id']} reuse={ctrl.get('reuse')} ...", flush=True)
        ctrl_run = run_live(py, ctrl, args.workers, skip_existing)
        print(
            f"[{TAG}] {ctrl['id']} ok={ctrl_run['ok']} n={len(ctrl_run.get('trades') or [])} "
            f"elapsed={ctrl_run.get('elapsed_s', 0):.0f}s skipped={ctrl_run.get('skipped')}",
            flush=True,
        )
        runs.append(ctrl_run)

        live = [a for a in arms if not a.get("reuse")]
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
            futs = {ex.submit(run_live, py, arm, args.workers, skip_existing): arm for arm in live}
            for fut in as_completed(futs):
                arm = futs[fut]
                run = fut.result()
                print(
                    f"[{TAG}] {arm['id']} ok={run['ok']} n={len(run.get('trades') or [])} "
                    f"elapsed={run.get('elapsed_s', 0):.0f}s skipped={run.get('skipped')} "
                    f"exit={run.get('exit_code')}",
                    flush=True,
                )
                runs.append(run)

    runs.sort(key=lambda r: ARM_ORDER.get(r["arm"]["id"], 99))
    if not all(r.get("ok") for r in runs):
        print(f"[{TAG}] One or more arms failed", flush=True)
        for r in runs:
            print(f"  {r['arm']['id']}: ok={r.get('ok')} exit={r.get('exit_code')}", flush=True)
        fail_html = OUT_DIR / "compare.html"
        fail_html.write_text(
            "<html><body><h1>RL SMA envelope TARGET vs pct20_d60 AB failed</h1>"
            "<p>One or more arms failed. Check runs/*/run.log.</p>"
            f"<pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>"
            f"<p>{html_mod.escape(LAYMAN_TRANSLATION.strip())}</p>"
            "</body></html>",
            encoding="utf-8",
        )
        ntfy = ROOT / "tools" / "ntfy_job_done.py"
        if ntfy.is_file():
            subprocess.run(
                [
                    py,
                    str(ntfy),
                    "--path",
                    str(fail_html),
                    "-t",
                    "RL SMA envelope TARGET AB FAILED",
                ],
                cwd=str(ROOT),
            )
        return 1

    packed = [pack_result(r) for r in runs]
    for p, r in zip(packed, runs):
        p["ok"] = r.get("ok")
        p["closed"] = r.get("closed")
        p["stamp"] = r.get("stamp")
        p["trades"] = r.get("trades") or []
    result = summarize(packed)

    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    if ntfy.is_file():
        paths = [str(result["html"])] + [str(p) for p in result.get("closed_htmls") or []]
        cmd = [py, str(ntfy)]
        for pth in paths:
            cmd.extend(["--path", pth])
        vbits = " ".join(f"{aid}={result['verdicts'][aid]['is'][0]}" for aid in CAND_IDS)
        cmd.extend(
            [
                "-t",
                "RL SMA envelope TARGET vs pct20_d60 AB",
                "-m",
                f"compare + closed; IS picks: {vbits}",
            ]
        )
        subprocess.run(cmd, cwd=str(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
