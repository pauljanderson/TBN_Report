#!/usr/bin/env python3
"""RL EXIT A/B: 9% stop from the entry price vs control signal-low stop.

Control (reuse): no-SMA-target +20% then 60d from rl_no_sma_target_exit_ab_20260905
  (rl_sma_target_off=1, rl_exit_percent=0.20, rl_exit_days=60, th113_vol entry freeze)
  with house stop = signal-day low × rl_stop_pct 0.934.

Candidate (one EXIT knob — protective stop only):
  stop9 → rl_stop_anchor=entry_open, rl_entry_stop_pct=0.91
          (stop = fill × 0.91). Fill gates still use rl_stop_pct=0.934.

IS = entry < 2024-01-01; OOS report-only; no OOS retune.
Research-only. Not gold. Not DailyRun.

Usage:
  python tools/rl_entry_stop_9pct_ab.py
  python tools/rl_entry_stop_9pct_ab.py --summarize-only
  python tools/rl_entry_stop_9pct_ab.py --skip-existing --jobs 1 --workers 8
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
OUT_DIR = DRIVE / "paul_experiments" / f"rl_entry_stop_9pct_ab_{STAMP}"
RUNS_DIR = OUT_DIR / "runs"

CTRL_SRC = (
    DRIVE
    / "paul_experiments"
    / "rl_no_sma_target_exit_ab_20260905"
    / "runs"
    / "pct20_d60"
)

HOUSE_STOP = 0.934
ENTRY_STOP = 0.91
HOUSE_CUT = 1000
HOUSE_DIP = 1.055
HOUSE_EXP = 1.163
TH13 = 1.13
MIN_AVG_VOL = 10_000
MIN_TRIGGER_VOL = 5_000

CONTROL_ID = "control"
CAND_ID = "stop9"
CAND_IDS = [CAND_ID]
ARM_ORDER = {CONTROL_ID: 0, CAND_ID: 1}
TAG = "RL-STOP9"

REQUEST_PROMPT = """\
Can you run an AB test vs control, the test group will have a 9% stop based on the entry price.  same reporting as before
"""

LAYMAN_TRANSLATION = """\
Control sells a loser when price falls through a level tied to the dip day's low \
(that low times 0.934, about 6.6% under the low — not a fixed percent under the price you paid). \
The test instead puts the stop exactly 9% under the fill price (entry times 0.91). \
Who gets bought stays the same. Whichever comes first still closes the trade: that stop, \
or the existing +20% gain followed by 60 trading days.
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


def _freeze_v(*, entry_stop: bool) -> list[str]:
    v = [
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
        f"rl_expansion={HOUSE_EXP}",
        f"rl_stop_pct={HOUSE_STOP}",
        "rl_target_pct=1.2",
        "rl_sma_target_off=1",
        f"rl_cut_the_losers={HOUSE_CUT}",
        "rl_exit_percent=0.20",
        "rl_exit_days=60",
        "rl_exit_calendar_days=0",
        "rl_max_hold_bars=0",
        "rl_max_hold_calendar_days=0",
        "rl_post_target_reentry_bars=0",
        f"rl_too_high={TH13}",
        f"rl_min_avg_vol={MIN_AVG_VOL}",
        f"rl_min_trigger_vol={MIN_TRIGGER_VOL}",
    ]
    if entry_stop:
        v.extend(
            [
                "rl_stop_anchor=entry_open",
                f"rl_entry_stop_pct={ENTRY_STOP}",
            ]
        )
    else:
        v.extend(["rl_stop_anchor=signal_low", "rl_entry_stop_pct=0"])
    return v


def _arm_defs() -> list[dict[str, Any]]:
    syms = _full_univ_symbols()
    n = len(syms)
    return [
        {
            "id": CONTROL_ID,
            "label": "Control stop = signal low × 0.934",
            "role": "control",
            "symbols": syms,
            "univ_n": n,
            "extra_v": _freeze_v(entry_stop=False),
            "reuse": True,
        },
        {
            "id": CAND_ID,
            "label": "Test stop = entry × 0.91 (9% below fill)",
            "role": "candidate",
            "symbols": syms,
            "univ_n": n,
            "extra_v": _freeze_v(entry_stop=True),
            "reuse": False,
        },
    ]


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
        return f"**`{aid}` {tag}** IS `{vis}` ({nis}); OOS `{voos}` ({noos}). Research candidate ≠ gold."
    if vis == "DISMISS":
        return f"**`{aid}` DISMISS** IS `{vis}` ({nis}); OOS `{voos}` ({noos})."
    return f"**`{aid}` HOLD** IS `{vis}` ({nis}); OOS `{voos}` ({noos})."


def _decision(verdicts: dict[str, dict[str, tuple[str, str]]]) -> str:
    vis = verdicts[CAND_ID]["is"][0]
    voos = verdicts[CAND_ID]["oos"][0]
    if vis in ("KEEP", "LEAN KEEP") and voos == "DISMISS":
        return (
            "**HOLD**. In-sample (IS) looked better for the 9% entry stop, but "
            "out-of-sample (OOS) softened. Do not retune on OOS. Research-only."
        )
    if vis in ("KEEP", "LEAN KEEP"):
        return (
            f"**{vis}** on IS for the 9% entry stop. OOS is `{voos}` (report-only). "
            "Research candidate ≠ gold ≠ DailyRun."
        )
    if vis == "DISMISS":
        return "**DISMISS** the 9% entry stop on IS quality. OOS is report-only. Research-only."
    return "**HOLD** — IS quality is flat vs control. Research-only."


def _stop_ratio_note(closed_csv: Path) -> str:
    ratios: list[float] = []
    with closed_csv.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            try:
                entry = float(str(raw.get("ENTRY PRICE", "")).replace(",", "") or 0)
                stop = float(str(raw.get("ORIGINAL STOP", "")).replace(",", "") or 0)
            except ValueError:
                continue
            if entry > 0 and stop > 0:
                ratios.append(stop / entry)
    if not ratios:
        return "Stop/entry check: no ORIGINAL STOP rows."
    ratios.sort()
    mid = ratios[len(ratios) // 2]
    off = sum(1 for r in ratios if abs(r - ENTRY_STOP) > 0.002)
    return (
        f"Test ORIGINAL STOP / ENTRY PRICE: n={len(ratios)} median={mid:.4f} "
        f"min={ratios[0]:.4f} max={ratios[-1]:.4f} off_0.91_by_gt_0.002={off}."
    )


def write_closed_html(closed_csv: Path, out_html: Path, *, title: str, arm_id: str) -> Path:
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
        "STOP LOSS AT CLOSE",
        "ORIGINAL TARGET",
        "MAX GAIN",
        "MAE",
    ]
    cols = [c for c in prefer if c in fieldnames]
    for c in fieldnames:
        if c not in cols:
            cols.append(c)
    cols = cols[:18]

    def _sort_type(name: str) -> str:
        u = name.upper()
        if "DATE" in u:
            return "date"
        if any(x in u for x in ("PNL", "PRICE", "DAYS", "GAIN", "MAE", "STOP", "TARGET", "AMOUNT", "%")):
            return "num"
        return "text"

    th = "".join(sortable_th(c, _sort_type(c)) for c in cols)
    body_parts: list[str] = []
    for r in rows:
        tds = "".join(f"<td>{html_mod.escape(str(r.get(c, '')))}</td>" for c in cols)
        body_parts.append(f"<tr>{tds}</tr>")

    stop_line = (
        "Protective stop = entry price × 0.91 (9% below the fill)."
        if arm_id == CAND_ID
        else "Protective stop = signal-day low × 0.934."
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
<p class="muted">Stamp <code>rl_entry_stop_9pct_ab_{STAMP}</code>. Arm <code>{html_mod.escape(arm_id)}</code>.
{html_mod.escape(stop_line)} Source <code>{html_mod.escape(closed_csv.name)}</code>.
N={len(rows)}. Click column headers to sort.</p>
</header>
<main>
<div class="callout">
<strong>What you asked</strong>
<pre style="white-space:pre-wrap;font-size:.82rem">{html_mod.escape(REQUEST_PROMPT.strip())}</pre>
<p><strong>In plain English:</strong> {html_mod.escape(LAYMAN_TRANSLATION.strip())}</p>
</div>
<section>
<h2 style="color:var(--accent);font-size:1.05rem;margin:.2rem 0 .5rem">Closed trades — {html_mod.escape(arm_id)}</h2>
<p class="muted">Same exits otherwise: +20% then 60 trading days, Simple Moving Average (SMA) envelope target off. Research-only.</p>
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
    stop_note: str,
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
            else "Closed overlay $47,500 / $500k. Overlay Max DD ≠ host account DD. "
            "IS/OOS/FULL Max DD each re-seed independently — not composable."
        )
        sections.append(
            f'<section><h2>9% entry stop A/B — {split_title}</h2>'
            f'<p class="muted">Δ vs control (signal-day low × 0.934). {note} '
            f"Click column headers to sort.</p>"
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{th_std}</tr></thead>'
            f"<tbody>{body}</tbody></table></div></section>"
        )

    knob_th = "".join(
        sortable_th(a, b)
        for a, b in (
            ("Arm", "text"),
            ("Stop rule", "text"),
            ("N full", "num"),
            ("Avg days", "num"),
            ("IS pick", "text"),
        )
    )
    knob_rows = []
    rules = {
        CONTROL_ID: "signal-day low × 0.934",
        CAND_ID: "entry price × 0.91 (9% below fill)",
    }
    for p in packed:
        arm = p["arm"]
        aid = arm["id"]
        is_pick = "—" if aid == CONTROL_ID else verdicts[aid]["is"][0]
        knob_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(aid)}</td>"
            f"<td>{html_mod.escape(rules.get(aid, ''))}</td>"
            f"<td>{p['m_full']['n']}</td>"
            f"<td>{p['m_full'].get('avg_days', 0):.1f}</td>"
            f"<td>{html_mod.escape(is_pick)}</td>"
            "</tr>"
        )
    knobs = (
        f'<section><h2>Arm knobs (EXIT — protective stop only)</h2>'
        f'<p class="muted">Entry filters stay frozen, including the too-high fill line '
        f"(signal low × {TH13} × {HOUSE_STOP}). Click headers to sort.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{knob_th}</tr></thead>'
        f"<tbody>{''.join(knob_rows)}</tbody></table></div></section>"
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
    pairs = [(f"{CAND_ID} − {CONTROL_ID}", by_id[CONTROL_ID], by_id[CAND_ID])]
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
        f"Stamp <code>rl_entry_stop_9pct_ab_{STAMP}</code>. "
        f"Control stop = signal-day low × 0.934. Test stop = entry × 0.91. "
        f"Universe: full OHLC ({n_univ}). Not gold / not DailyRun."
    )
    verdict_lis = "".join(f"<li>{_arm_verdict(aid, verdicts)}</li>" for aid in CAND_IDS)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL 9% entry stop A/B — {STAMP}</title>
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
<h1>RL 9% entry stop vs control</h1>
<p class="muted">{subtitle}</p>
</header>
<main>
<div class="callout req">
<strong>What you asked</strong>
<pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>
<p class="layman"><strong>In plain English:</strong> {html_mod.escape(LAYMAN_TRANSLATION.strip())}</p>
</div>
<div class="callout">
<strong>Paul note:</strong> {html_mod.escape(paul_note)}
<ul>{verdict_lis}</ul>
<p>{html_mod.escape(_decision(verdicts))}</p>
<p class="muted">{html_mod.escape(stop_note)}</p>
</div>
{knobs}
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
    stop_note: str,
) -> None:
    by_id = {p["arm"]["id"]: p for p in packed}
    n_univ = _count_full_univ()
    lines = [
        f"# BASELINE — `rl_entry_stop_9pct_ab_{STAMP}`",
        "",
        "**Status:** RESEARCH only. One-change EXIT knob (protective stop) on frozen pct20_d60.",
        "**Control:** signal-day low × `rl_stop_pct` **0.934** (reuse from `rl_no_sma_target_exit_ab_20260905`).",
        "**Candidate `stop9`:** `rl_stop_anchor=entry_open`, `rl_entry_stop_pct=0.91` "
        "(stop = fill × 0.91). Fill gates stay on `rl_stop_pct=0.934`.",
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
        "## Freeze (identical except the protective stop)",
        "",
        "| Knob | Value |",
        "|------|-------|",
        f"| `rl_too_high` | **{TH13}** (fill gate still uses `rl_stop_pct`) |",
        f"| `rl_min_avg_vol` | **{MIN_AVG_VOL}** |",
        f"| `rl_min_trigger_vol` | **{MIN_TRIGGER_VOL}** |",
        f"| `rl_dip_pct` | **{HOUSE_DIP}** |",
        f"| `rl_expansion` | **{HOUSE_EXP}** |",
        f"| `rl_stop_pct` | **{HOUSE_STOP}** (fill gates; control stop multiplier) |",
        "| `rl_target_pct` | **1.20** (hits only; sma_target_off=1) |",
        "| `rl_sma_target_off` | **1** |",
        "| `rl_exit_percent` / `rl_exit_days` | **0.20 / 60** trading bars after +20% |",
        "| `rl_exit_calendar_days` | **0** |",
        "| `rl_max_hold_bars` / `rl_max_hold_calendar_days` | **0 / 0** |",
        f"| `rl_cut_the_losers` | **{HOUSE_CUT}** (off) |",
        "",
        "## EXIT arms",
        "",
        "| Arm | Protective stop |",
        "|-----|-----------------|",
        f"| `{CONTROL_ID}` | signal-day low × **{HOUSE_STOP}** |",
        f"| `{CAND_ID}` | entry price × **{ENTRY_STOP}** (9% below the fill) |",
        "",
        "## Stop check",
        "",
        stop_note,
        "",
        "## Universe / split",
        "",
        f"- Full open-high-low-close (OHLC) pool under `data/newdata/data` (**{n_univ}**)",
        "- In-sample (IS) = entry date before 2024-01-01; out-of-sample (OOS) is report-only; no OOS retune",
        "- Per-symbol settings file still applies when present. It can change `rl_stop_pct` on the fill gate. "
        "It does not move the test protective stop off entry × 0.91.",
        "",
        "## Results",
        "",
        "| Arm | Stamp | N_full | OK |",
        "|-----|-------|--------|-----|",
    ]
    for p in packed:
        arm = p["arm"]
        lines.append(
            f"| `{arm['id']}` | `{p.get('stamp','')}` | {p['m_full']['n']} | "
            f"{'yes' if p.get('ok') else 'no'} |"
        )
    lines.extend(["", "## Split metrics", ""])
    for aid in (CONTROL_ID, *CAND_IDS):
        lines.append(f"- **{aid} IS:** {_md_split(by_id[aid], 'm_is')}")
        lines.append(f"- **{aid} OOS:** {_md_split(by_id[aid], 'm_oos')}")
        lines.append(f"- **{aid} FULL:** {_md_split(by_id[aid], 'm_full')}")
    lines.extend(["", "## Verdict", ""])
    for aid in CAND_IDS:
        lines.append(f"- {_arm_verdict(aid, verdicts)}")
    lines.extend(
        [
            "",
            f"**Decision:** {_decision(verdicts)}",
            "",
            "## Selection-bias note",
            "",
            "One a-priori stop from Paul's ask (9% under the entry price). Not tuned on OOS.",
            "",
            "## Closed copies",
            "",
        ]
    )
    for c in closed:
        lines.append(f"- `{c.as_posix()}`")
    lines.extend(["", "## Closed HTML", ""])
    for c in closed_htmls:
        lines.append(f"- `{c.as_posix()}`")
    lines.extend(["", f"Compare: `{html_path.as_posix()}`", ""])
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary = [
        f"# SUMMARY — `rl_entry_stop_9pct_ab_{STAMP}`",
        "",
        f"**Decision:** {_decision(verdicts)}",
        "",
    ]
    for aid in CAND_IDS:
        summary.append(f"- {_arm_verdict(aid, verdicts)}")
    summary.append("")
    summary.append(stop_note)
    summary.append("")
    for aid in (CONTROL_ID, *CAND_IDS):
        summary.append(f"- {aid} FULL: {_md_split(by_id[aid], 'm_full')}")
    summary.extend(["", f"Compare: `{html_path.as_posix()}`", ""])
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
    vis = verdicts[CAND_ID]["is"][0]
    stop_note = "Stop/entry check: missing closed file."
    cand_closed = by_id[CAND_ID].get("closed")
    if cand_closed and Path(cand_closed).is_file():
        stop_note = _stop_ratio_note(Path(cand_closed))
    paul_note = (
        f"{CAND_ID} IS={vis}. One EXIT knob (protective stop = entry × 0.91) "
        "on frozen pct20_d60. Fill gates unchanged. OOS report-only; no OOS retune. Research-only."
    )
    html_path = write_compare_html(packed, verdicts, paul_note=paul_note, stop_note=stop_note)
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
        )
        closed_htmls.append(ch)

    write_docs(packed, verdicts, closed, html_path, closed_htmls, stop_note)
    print(f"[{TAG}] {stop_note}", flush=True)
    print(
        f"[{TAG}] Wrote {html_path} closed_csv={len(closed)} closed_html={len(closed_htmls)}",
        flush=True,
    )
    return {
        "verdicts": verdicts,
        "packed": packed,
        "html": html_path,
        "closed_htmls": closed_htmls,
        "closed": closed,
        "stop_note": stop_note,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--jobs", type=int, default=1)
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
            "<html><body><h1>RL 9% entry stop AB failed</h1>"
            "<p>One or more arms failed. Check runs/*/run.log.</p></body></html>",
            encoding="utf-8",
        )
        ntfy = ROOT / "tools" / "ntfy_job_done.py"
        if ntfy.is_file():
            subprocess.run(
                [py, str(ntfy), "--path", str(fail_html), "-t", "RL 9pct entry stop AB FAILED"],
                cwd=str(ROOT),
            )
        return 1

    packed = [pack_result(r) for r in runs]
    for p, r in zip(packed, runs):
        p["ok"] = r.get("ok")
        p["closed"] = r.get("closed")
        p["stamp"] = r.get("stamp")
    result = summarize(packed)

    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    if ntfy.is_file():
        paths = [str(result["html"])] + [str(p) for p in result.get("closed_htmls") or []]
        cmd = [py, str(ntfy)]
        for pth in paths:
            cmd.extend(["--path", pth])
        vis = result["verdicts"][CAND_ID]["is"][0]
        cmd.extend(
            [
                "-t",
                "RL 9pct entry stop AB done",
                "-m",
                f"compare + closed; IS pick: {CAND_ID}={vis}",
            ]
        )
        subprocess.run(cmd, cwd=str(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
