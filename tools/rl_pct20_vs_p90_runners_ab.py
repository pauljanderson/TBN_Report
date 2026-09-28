#!/usr/bin/env python3
"""RL EXIT A/B: 100% at +20% vs four 90/10 runners.

A (reuse): 100% exits at entry × 1.20. No time clock.
B: sell 90% at +20%, leftover stop to breakeven, leftover exits at +40%.
C: sell 90% at +20%, original stop stays, leftover exits at +40%.
D: sell 90% at +20%, leftover stop to breakeven, leftover exits at +50%.
E: sell 90% at +20%, original stop stays, leftover exits at +50%.

Scale-out fills at the gain price, or at the open if the bar opens through it.
The original-stop ladders use stop_gain=-1, which sits below the original stop
(entry × 0.934), so that stop is left in place.
IS = entry < 2024-01-01; OOS report-only; no OOS retune.
Research-only. Not gold. Not DailyRun.

Usage:
  python tools/rl_pct20_vs_p90_runners_ab.py --workers 4
  python tools/rl_pct20_vs_p90_runners_ab.py --summarize-only
  python tools/rl_pct20_vs_p90_runners_ab.py --skip-existing --workers 4
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
STAMP = "20260927"
OUT_DIR = DRIVE / "paul_experiments" / f"rl_pct20_vs_p90_runners_ab_{STAMP}"
RUNS_DIR = OUT_DIR / "runs"

CTRL_SRC = (
    DRIVE
    / "paul_experiments"
    / "rl_control_vs_live_vs_pct20_notime_ab_20260927"
    / "runs"
    / "pct20_notime"
)
CONTROL_DATA_END = "20260904"

HOUSE_STOP = 0.934
HOUSE_CUT = 1000
HOUSE_DIP = 1.055
TH13 = 1.13
MIN_AVG_VOL = 10_000
MIN_TRIGGER_VOL = 5_000

CONTROL_ID = "simple_20"
# id, ladder, leftover target, short note
CANDIDATES: list[tuple[str, str, float, str]] = [
    ("p90_be_40", "0.20:0.90:0", 0.40, "90% @ +20% → BE; leftover @ +40%"),
    ("p90_orig_40", "0.20:0.90:-1", 0.40, "90% @ +20%, original stop; leftover @ +40%"),
    ("p90_be_50", "0.20:0.90:0", 0.50, "90% @ +20% → BE; leftover @ +50%"),
    ("p90_orig_50", "0.20:0.90:-1", 0.50, "90% @ +20%, original stop; leftover @ +50%"),
]
CAND_IDS = [c[0] for c in CANDIDATES]
ARM_ORDER = {CONTROL_ID: 0, **{cid: i + 1 for i, cid in enumerate(CAND_IDS)}}
TAG = "RL-P20-VS-P90-RUNNERS"

REQUEST_PROMPT = """\
please run again using  A — Simple: Sell 100% at +20%.

B — 90/10 + BE → +40: Sell 90% at +20%, move the remaining 10% stop to breakeven, exit the remaining 10% at +40%.

C — 90/10 + Original Stop → +40: Sell 90% at +20%, keep the original stop on the remaining 10%, exit the remaining 10% at +40%.

D — 90/10 + BE → +50: Sell 90% at +20%, move the remaining 10% stop to breakeven, exit the remaining 10% at +50%.

E — 90/10 + Original Stop → +50: Sell 90% at +20%, keep the original stop on the remaining 10%, exit the remaining 10% at +50%.
"""

LAYMAN_TRANSLATION = """\
All five books buy the same dips. A sells the whole position the moment the price is 20% above \
the buy. The other four sell 90% at that same 20% mark and try to sell the last 10% at a higher \
price. B and D move that leftover's stop up to the buy price, so it can't turn into a loss. \
C and E leave the original stop in place, about 6.6% under the buy. B and C try to sell the \
leftover at 40% above the buy. D and E try to sell it at 50% above the buy. If the leftover \
hits its stop first, it sells there. There is no time limit. A leftover that never hits its \
target and never hits its stop can stay open.
"""

INTERPRETATION = """\
A is the simple +20% book already run (rl_entry_target_pct=0.20, moving-average target off, \
time clock off). B through E use the same entries and sell 90% of the original shares (whole \
shares) when the high reaches +20%. B and D then set the leftover stop to the entry price \
(ladder 0.20:0.90:0). C and E use ladder 0.20:0.90:-1, a stop step below the original stop \
(entry × 0.934), so the original stop stays. The leftover exits at +40% on B and C \
(rl_entry_target_pct=0.40) and at +50% on D and E (rl_entry_target_pct=0.50). Fills are at \
that gain price, or at the open if the day opens through it. If a day trades both the stop \
and the leftover target, the stop is checked first. New buys stop after 2026-09-04. \
Research-only.
"""

FOLLOWUP_PROMPT = """\
Important: For B–E, calculate Capital Days, PPCD, and Annualized ROR using capital-weighted exposure. Once 90% is sold at +20%, only 10% of the original capital remains occupied until the runner exits. Do not charge the runner as a full position for its remaining holding period.
"""

REMAIN_FRAC = 0.10

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(DRIVE / "paul_experiments"))
from be_stop_replay_ab import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from compare_format import (  # noqa: E402
    ann_ror_from_closed,
    calmar_ratio,
    filter_html_compare_columns,
)
from rl_univ_compare_lists import (  # noqa: E402
    IS_CUT,
    PER_SYMBOL,
    RL_CASH,
    SA,
    _f,
    _parse_d,
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


def _entry_freeze_v(*, ladder: str | None, entry_target: float = 0.20) -> list[str]:
    """Same buys as the simple +20% book. Runners add a 90% scale-out and a leftover target."""
    entry_tgt = entry_target
    vs = [
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
        "rl_target_pct=1.2",
        "rl_sma_target_off=1",
        f"rl_cut_the_losers={HOUSE_CUT}",
        "rl_exit_percent=0",
        "rl_exit_days=0",
        "rl_exit_calendar_days=0",
        "rl_max_hold_bars=0",
        "rl_max_hold_calendar_days=0",
        f"rl_entry_target_pct={entry_tgt}",
        "rl_post_target_reentry_bars=0",
        f"rl_too_high={TH13}",
        f"rl_min_avg_vol={MIN_AVG_VOL}",
        f"rl_min_trigger_vol={MIN_TRIGGER_VOL}",
        f"entry_end_date={CONTROL_DATA_END}",
    ]
    if ladder:
        vs.append(f"rl_scale_ladder={ladder}")
    return vs


def _arm_defs() -> list[dict[str, Any]]:
    syms = _full_univ_symbols()
    n = len(syms)
    arms: list[dict[str, Any]] = [
        {
            "id": CONTROL_ID,
            "label": "A: 100% exit at +20% from entry (no time)",
            "role": "control",
            "symbols": syms,
            "univ_n": n,
            "ladder": "",
            "entry_target": 0.20,
            "extra_v": _entry_freeze_v(ladder=None, entry_target=0.20),
            "reuse": True,
        },
    ]
    for cid, ladder, tgt, note in CANDIDATES:
        arms.append(
            {
                "id": cid,
                "label": note,
                "role": "candidate",
                "symbols": syms,
                "univ_n": n,
                "ladder": ladder,
                "entry_target": tgt,
                "extra_v": _entry_freeze_v(ladder=ladder, entry_target=tgt),
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


def exit_mix(closed: Path | None) -> dict[str, int]:
    c: Counter[str] = Counter()
    n = 0
    if closed and Path(closed).is_file():
        with Path(closed).open(newline="", encoding="utf-8-sig") as f:
            for raw in csv.DictReader(f):
                n += 1
                et = (raw.get("EXIT TYPE") or "").strip().upper() or "OTHER"
                if et in ("STOP_LOSS", "GAP_DOWN"):
                    c["STOP"] += 1
                elif et == "ENTRY_TARGET":
                    c["ENTRY_TARGET"] += 1
                elif et == "TRAIL_STOP":
                    c["TRAIL_STOP"] += 1
                else:
                    c["OTHER"] += 1
    return {
        "N": n,
        "STOP": int(c.get("STOP", 0)),
        "ENTRY_TARGET": int(c.get("ENTRY_TARGET", 0)),
        "TRAIL_STOP": int(c.get("TRAIL_STOP", 0)),
        "OTHER": int(c.get("OTHER", 0)),
    }


def count_partials(closed: Path | None) -> int:
    if not closed or not closed.is_file():
        return 0
    n = 0
    with closed.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            v = (raw.get("PARTIAL_DATE") or "").strip()
            if v and v.upper() not in ("N/A", "NONE", "0"):
                n += 1
    return n


def _exposure_days(days_held: float, opened, partial) -> float:
    """Full slot until the +20% sale day (inclusive). After that, only the leftover fraction."""
    if days_held <= 0:
        return 0.0
    if opened is None or partial is None:
        return float(days_held)
    full_days = (partial - opened).days + 1
    if full_days < 1:
        full_days = 1
    if full_days > days_held:
        full_days = int(days_held)
    runner_days = float(days_held) - float(full_days)
    return float(full_days) + runner_days * REMAIN_FRAC


def _closed_exposure_rows(closed_path: Path) -> list[dict[str, Any]]:
    """One row per Closed trade load_trades would keep, with exposure days attached."""
    out: list[dict[str, Any]] = []
    if not closed_path or not Path(closed_path).is_file():
        return out
    with Path(closed_path).open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _parse_d(raw.get("DATE OPENED") or raw.get("DATE_OPENED"))
            if opened is None:
                continue
            days = _f(raw.get("DAYS HELD") or raw.get("DAYS_HELD"))
            partial_raw = (raw.get("PARTIAL_DATE") or "").strip()
            partial = None
            if partial_raw and partial_raw.upper() not in ("N/A", "NONE", "0"):
                partial = _parse_d(partial_raw)
            pnl = _f(raw.get("PNL %") or raw.get("PNL_PCT"))
            pnl_d = _f(raw.get("PNL_DOLLARS"))
            if pnl_d == 0.0 and pnl != 0.0:
                pnl_d = RL_CASH * pnl / 100.0
            out.append(
                {
                    "opened": opened,
                    "days": days,
                    "pnl_d": pnl_d,
                    "exposure": _exposure_days(days, opened, partial),
                    "partial": partial is not None,
                }
            )
    return out


def _apply_exposure_metrics(m: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    """Replace Capital Days, PPCD, Ann ROR, and Calmar using capital-weighted days."""
    if not rows or m.get("n", 0) <= 0:
        return
    cap = float(sum(r["exposure"] for r in rows))
    pnl_d = float(m.get("pnl_d") or 0.0)
    n = int(m["n"])
    avg_exp = cap / n if n else 0.0
    ann = ann_ror_from_closed(
        total_pnl=pnl_d,
        n_trades=n,
        avg_days_held=avg_exp,
        brt_cash=RL_CASH,
    )
    ann_f = float(ann) if ann is not None else float("nan")
    m["cap_days"] = cap
    m["ppc"] = (pnl_d / cap) if cap else float("nan")
    m["ann_ror"] = ann_f
    m["exposure_avg"] = avg_exp
    cal = calmar_ratio(ann_f, m.get("max_dd"))
    m["calmar"] = float(cal) if cal is not None else float("nan")


def apply_capital_weights(packed: list[dict[str, Any]]) -> None:
    """B–E: after the 90% sale, only 10% of the slot is still tied up."""
    for p in packed:
        if p["arm"]["id"] == CONTROL_ID:
            continue
        rows = _closed_exposure_rows(p.get("closed"))
        if len(rows) != int(p["m_full"]["n"]):
            print(
                f"[{TAG}] exposure row mismatch {p['arm']['id']}: "
                f"csv={len(rows)} metrics={p['m_full']['n']}",
                flush=True,
            )
        is_rows = [r for r in rows if r["opened"] < IS_CUT]
        oos_rows = [r for r in rows if r["opened"] >= IS_CUT]
        _apply_exposure_metrics(p["m_full"], rows)
        _apply_exposure_metrics(p["m_is"], is_rows)
        _apply_exposure_metrics(p["m_oos"], oos_rows)


def _md_split(p: dict[str, Any], key: str) -> str:
    m = p[key]
    return (
        f"N={m['n']} WR={m['wr']:.1f}% Avg={m['avg_pnl']:.2f}% WO_MAX={m['wo_max']:.2f}% "
        f"PF={m['pf']:.2f} AnnROR={fmt_n(m['ann_ror'], 2)} MaxDD_overlay={fmt_n(m['max_dd'], 2)} "
        f"avg_days={m.get('avg_days', 0):.1f}"
        + (
            f" wtd_days={m['exposure_avg']:.1f}"
            if isinstance(m.get("exposure_avg"), float)
            else ""
        )
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


def write_closed_html(closed_csv: Path, out_html: Path, *, title: str) -> Path:
    """Sortable Closed trades HTML for the candidate arm."""
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
        "PARTIAL_DATE",
        "PARTIAL_EXIT_AMOUNT",
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
    # Cap width for mobile readability — keep core + a few extras
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
<p class="muted">Stamp <code>rl_pct20_vs_p90_runners_ab_{STAMP}</code>. Source <code>{html_mod.escape(closed_csv.name)}</code>. N={len(rows)}. Click column headers to sort.</p>
</header>
<main>
<div class="callout">
<strong>What you asked</strong>
<pre style="white-space:pre-wrap;font-size:.82rem">{html_mod.escape(REQUEST_PROMPT.strip())}</pre>
<pre style="white-space:pre-wrap;font-size:.82rem">{html_mod.escape(FOLLOWUP_PROMPT.strip())}</pre>
<p><strong>In plain English:</strong> {html_mod.escape(LAYMAN_TRANSLATION.strip())}</p>
<p><strong>Interpretation:</strong> {html_mod.escape(INTERPRETATION.strip())}</p>
</div>
<section>
<h2 style="color:var(--accent);font-size:1.05rem;margin:.2rem 0 .5rem">Closed trades</h2>
<p class="muted">A sells 100% at +20%. B–E sell 90% at +20%. B and D then use a breakeven stop. C and E keep the original stop. B and C sell the leftover at +40%. D and E sell it at +50%. Research-only.</p>
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
    n_partial: dict[str, int],
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
            "Paul/FIT/UW from host Summary + EquityMeta when present. Overlay Max DD ≠ host DD. "
            "Capital Days, profit per capital day, and annualized return on B–E count a full slot only through the +20% sale day, then 10% of a slot until the leftover exits."
            if split_key == "m_full"
            else "Closed overlay $47,500 / $500k. Overlay Max DD ≠ host account DD. "
            "Capital Days, profit per capital day, and annualized return on B–E count a full slot only through the +20% sale day, then 10% of a slot until the leftover exits. Avg days is still calendar time the trade was open."
        )
        sections.append(
            f'<section><h2>Full +20% vs 90/10 runners — {split_title}</h2>'
            f'<p class="muted">Δ vs control ({CONTROL_ID}). {note} Click column headers to sort.</p>'
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{th_std}</tr></thead>'
            f"<tbody>{body}</tbody></table></div></section>"
        )

    knob_th = "".join(
        sortable_th(a, b)
        for a, b in (
            ("Arm", "text"),
            ("Ladder", "text"),
            ("Leftover target", "num"),
            ("Partials N", "num"),
            ("N full", "num"),
            ("Avg days", "num"),
        )
    )
    knob_rows = []
    for p in packed:
        arm = p["arm"]
        aid = arm["id"]
        ladder = arm.get("ladder") or "(off)"
        tgt = float(arm.get("entry_target") or 0)
        knob_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(aid)}</td>"
            f"<td><code>{html_mod.escape(ladder)}</code></td>"
            f"<td>{tgt:.2f}</td>"
            f"<td>{n_partial.get(aid, 0)}</td>"
            f"<td>{p['m_full']['n']}</td>"
            f"<td>{p['m_full'].get('avg_days', 0):.1f}</td>"
            "</tr>"
        )
    knobs = (
        f'<section><h2>Arm knobs (FULL)</h2>'
        f'<p class="muted">Same entries. A sells 100% at +20%. B–E sell 90% at +20%. Click headers to sort.</p>'
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{knob_th}</tr></thead>'
        f"<tbody>{''.join(knob_rows)}</tbody></table></div></section>"
    )

    exit_mix_sec = ""
    mix_th = "".join(
        sortable_th(a, b)
        for a, b in (
            ("Arm", "text"),
            ("N", "num"),
            ("STOP", "num"),
            ("ENTRY_TARGET (leftover target, or full +20% on A)", "num"),
            ("TRAIL_STOP (breakeven)", "num"),
            ("OTHER", "num"),
        )
    )
    mix_rows = []
    for p in packed:
        mix = exit_mix(p.get("closed"))
        mix_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(p['arm']['id'])}</td>"
            f"<td>{mix['N']}</td>"
            f"<td>{mix['STOP']}</td>"
            f"<td>{mix['ENTRY_TARGET']}</td>"
            f"<td>{mix['TRAIL_STOP']}</td>"
            f"<td>{mix['OTHER']}</td>"
            "</tr>"
        )
    exit_mix_sec = (
        '<section><h2>Exit mix (full book)</h2>'
        '<p class="muted">A should be STOP plus ENTRY_TARGET (the full +20% sale). '
        "B and D can show TRAIL_STOP when the leftover is sold at the buy price. "
        "C and E keep the original stop, so those leftover stop-outs stay in STOP. "
        "ENTRY_TARGET on B–E is the leftover sold at +40% or +50%. Click headers to sort.</p>"
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
    pairs = [
        (f"{aid} − {CONTROL_ID}", by_id[CONTROL_ID], by_id[aid]) for aid in CAND_IDS
    ]
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
        f"Stamp <code>rl_pct20_vs_p90_runners_ab_{STAMP}</code>. "
        f"A = 100% exit at +20% (reuse pct20_notime). "
        f"B–E sell 90% at +20% with a 10% runner to +40% or +50%. "
        f"Universe: full OHLC ({n_univ}). Not gold / not DailyRun."
    )
    verdict_lis = "".join(f"<li>{_arm_verdict(aid, verdicts)}</li>" for aid in CAND_IDS)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL +20% vs 90/10 runners — {STAMP}</title>
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
<h1>A sells 100% at +20%. B–E sell 90% at +20% and keep a 10% runner.</h1>
<p class="muted">{subtitle}</p>
</header>
<main>
<div class="callout req">
<strong>What you asked</strong>
<pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>
<pre>{html_mod.escape(FOLLOWUP_PROMPT.strip())}</pre>
<p class="layman"><strong>In plain English:</strong> {html_mod.escape(LAYMAN_TRANSLATION.strip())}</p>
<p class="layman"><strong>Interpretation:</strong> {html_mod.escape(INTERPRETATION.strip())}</p>
</div>
<div class="callout">
<strong>Paul note:</strong> {html_mod.escape(paul_note)}
<ul>{verdict_lis}</ul>
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
    n_partial: dict[str, int],
) -> None:
    by_id = {p["arm"]["id"]: p for p in packed}
    n_univ = _count_full_univ()
    baseline = [
        f"# BASELINE — `rl_pct20_vs_p90_runners_ab_{STAMP}`",
        "",
        "**Status:** RESEARCH only. EXIT A/B on the simple +20% entry freeze.",
        f"**A `{CONTROL_ID}`:** 100% exits at +20% (`rl_entry_target_pct=0.20`). "
        "Reuse `rl_control_vs_live_vs_pct20_notime_ab_20260927` / `pct20_notime`, stamp `260927081643`.",
        "**B `p90_be_40`:** ladder `0.20:0.90:0`, leftover target +40%.",
        "**C `p90_orig_40`:** ladder `0.20:0.90:-1` (original stop stays), leftover target +40%.",
        "**D `p90_be_50`:** ladder `0.20:0.90:0`, leftover target +50%.",
        "**E `p90_orig_50`:** ladder `0.20:0.90:-1` (original stop stays), leftover target +50%.",
        "Not gold. Not DailyRun.",
        "",
        "## What you asked",
        "",
        "```",
        REQUEST_PROMPT.strip(),
        "```",
        "",
        "```",
        FOLLOWUP_PROMPT.strip(),
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
        "## Entry freeze (entries identical; sells differ)",
        "",
        "| Knob | Value |",
        "|------|-------|",
        f"| `rl_too_high` | **{TH13}** |",
        f"| `rl_min_avg_vol` | **{MIN_AVG_VOL}** |",
        f"| `rl_min_trigger_vol` | **{MIN_TRIGGER_VOL}** |",
        f"| `rl_dip_pct` | **{HOUSE_DIP}** |",
        "| `rl_expansion` | **1.163** |",
        f"| `rl_stop_pct` | **{HOUSE_STOP}** |",
        "| `rl_target_pct` | **1.20** (hits only; sma_target_off=1) |",
        "| `rl_sma_target_off` | **1** |",
        "| `rl_exit_percent` / `rl_exit_days` | **0 / 0** (no time clock) |",
        "| `rl_entry_target_pct` | **0.20 on A; 0.40 on B/C; 0.50 on D/E** |",
        "| `rl_scale_ladder` | off on A; `0.20:0.90:0` on B/D; `0.20:0.90:-1` on C/E |",
        f"| `rl_cut_the_losers` | **{HOUSE_CUT}** (off) |",
        "",
        "## EXIT arms",
        "",
        "| Arm | Ladder | Notes |",
        "|-----|--------|-------|",
        f"| `{CONTROL_ID}` | off | 100% at +20% |",
        "| `p90_be_40` | `0.20:0.90:0` | 90% @ +20% → BE; leftover @ +40% |",
        "| `p90_orig_40` | `0.20:0.90:-1` | 90% @ +20%, original stop stays; leftover @ +40% |",
        "| `p90_be_50` | `0.20:0.90:0` | 90% @ +20% → BE; leftover @ +50% |",
        "| `p90_orig_50` | `0.20:0.90:-1` | 90% @ +20%, original stop stays; leftover @ +50% |",
        "",
        "## Universe / split",
        "",
        f"- Full OHLC pool under `data/newdata/data` (**{n_univ}**)",
        "- IS = entry < 2024-01-01; OOS report-only; no OOS retune",
        "",
        "## Capital-weighted hold (B–E only)",
        "",
        "Capital Days, profit per capital day, and annualized return treat one closed trade-day of a "
        "full position as one capital day. Through the day the 90% piece is sold (inclusive), the "
        "trade still uses a full slot. Every later calendar day uses 10% of a slot until the leftover "
        "exits. Trades that never sell the 90% piece stay at a full slot. A is unchanged (no partial). "
        "Avg days in the tables is still calendar time the trade was open. Max drawdown is still the "
        "closed exit replay. Calmar uses the capital-weighted annualized return over that drawdown.",
        "",
        "## Results",
        "",
        "| Arm | Stamp | N_full | Partials | OK |",
        "|-----|-------|--------|----------|-----|",
    ]
    for p in packed:
        arm = p["arm"]
        baseline.append(
            f"| `{arm['id']}` | `{p.get('stamp','')}` | {p['m_full']['n']} | "
            f"{n_partial.get(arm['id'], 0)} | {'yes' if p.get('ok') else 'no'} |"
        )
    baseline.extend(
        [
            "",
            "## Split metrics",
            "",
            f"- **A IS:** {_md_split(by_id[CONTROL_ID], 'm_is')}",
            f"- **A OOS:** {_md_split(by_id[CONTROL_ID], 'm_oos')}",
            f"- **A FULL:** {_md_split(by_id[CONTROL_ID], 'm_full')}",
        ]
    )
    for aid in CAND_IDS:
        baseline.extend(
            [
                f"- **{aid} IS:** {_md_split(by_id[aid], 'm_is')}",
                f"- **{aid} OOS:** {_md_split(by_id[aid], 'm_oos')}",
                f"- **{aid} FULL:** {_md_split(by_id[aid], 'm_full')}",
            ]
        )
    baseline.extend(
        [
            "",
            "## Verdict",
            "",
        ]
    )
    for aid in CAND_IDS:
        baseline.append(f"- {_arm_verdict(aid, verdicts)}")
    baseline.extend(
        [
            "",
            "## Selection-bias note",
            "",
            "A through E were specified before this run. A sells 100% at +20%. "
            "B–E sell 90% at +20% and keep a 10% runner: breakeven or the original stop, "
            "then +40% or +50%. Not tuned on OOS. Picking a winner after seeing "
            "this table is in-sample selection.",
            "",
            "## Closed copies",
            "",
        ]
    )
    for c in closed:
        baseline.append(f"- `{c.as_posix()}`")
    baseline.extend(["", f"Compare: `{html_path.as_posix()}`", ""])
    (OUT_DIR / "BASELINE.md").write_text("\n".join(baseline) + "\n", encoding="utf-8")

    summary = [
        f"# SUMMARY — `rl_pct20_vs_p90_runners_ab_{STAMP}`",
        "",
    ]
    for aid in CAND_IDS:
        summary.append(f"- {_arm_verdict(aid, verdicts)}")
    summary.extend(
        [
            "",
            f"- A FULL: {_md_split(by_id[CONTROL_ID], 'm_full')}",
        ]
    )
    for aid in CAND_IDS:
        summary.append(f"- {aid} FULL: {_md_split(by_id[aid], 'm_full')}")
    summary.extend(
        [
            "- Partials: "
            + ", ".join(f"{aid}={n_partial.get(aid, 0)}" for aid in (CONTROL_ID, *CAND_IDS)),
            "",
            f"Compare: `{html_path.as_posix()}`",
            "",
        ]
    )
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(summary), encoding="utf-8")


def summarize(packed: list[dict[str, Any]]) -> dict[str, Any]:
    apply_capital_weights(packed)
    by_id = {p["arm"]["id"]: p for p in packed}
    control = by_id[CONTROL_ID]
    verdicts = {
        aid: {
            "is": verdict_vs_control(by_id[aid], control, "m_is"),
            "oos": verdict_vs_control(by_id[aid], control, "m_oos"),
        }
        for aid in CAND_IDS
    }
    n_partial = {p["arm"]["id"]: count_partials(p.get("closed")) for p in packed}
    bits = ", ".join(f"{aid} IS={verdicts[aid]['is'][0]}" for aid in CAND_IDS)
    paul_note = (
        f"{bits}. OOS is report-only — do not retune. "
        "A softer out-of-sample result is a hold, not a reason to change the plan. "
        "Judge average gain and profit factor, not trade count. Research-only."
    )
    html_path = write_compare_html(packed, verdicts, n_partial, paul_note=paul_note)
    closed = _stamp_closed_copies(packed)
    write_metrics_csv(packed, "", OUT_DIR / "metrics_all.csv")
    write_docs(packed, verdicts, closed, html_path, n_partial)

    closed_htmls: list[Path] = []
    for p in packed:
        src = p.get("closed")
        if not src or not Path(src).is_file():
            continue
        arm_id = p["arm"]["id"]
        dest_csv = next((c for c in closed if c.name.startswith(arm_id + "_")), Path(src))
        label = p["arm"].get("label") or arm_id
        closed_htmls.append(
            write_closed_html(
                dest_csv,
                OUT_DIR / "closed" / f"{arm_id}_closed.html",
                title=f"RL Closed — {arm_id} ({label})",
            )
        )
    print(
        f"[{TAG}] Wrote {html_path} closed={len(closed)} partials={n_partial} "
        f"closed_html={len(closed_htmls)}",
        flush=True,
    )
    return {
        "verdicts": verdicts,
        "packed": packed,
        "n_partial": n_partial,
        "html": html_path,
        "closed_htmls": closed_htmls,
        "closed": closed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
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
        reused = [a for a in arms if a.get("reuse")]
        fresh = [a for a in arms if not a.get("reuse")]
        for arm in reused:
            print(f"[{TAG}] starting {arm['id']} reuse=True ...", flush=True)
            run = run_live(py, arm, args.workers, skip_existing)
            print(
                f"[{TAG}] {arm['id']} ok={run['ok']} n={len(run.get('trades') or [])} "
                f"elapsed={run.get('elapsed_s', 0):.0f}s skipped={run.get('skipped')}",
                flush=True,
            )
            runs.append(run)
        with ThreadPoolExecutor(max_workers=max(1, len(fresh))) as ex:
            futs = {
                ex.submit(run_live, py, arm, args.workers, skip_existing): arm for arm in fresh
            }
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
        # Still try to write a short failure note if control exists
        fail_html = OUT_DIR / "compare.html"
        fail_html.write_text(
            "<html><body><h1>RL +20% vs 90/10 runners AB failed</h1>"
            "<p>One or more arms failed. Check runs/*/run.log.</p>"
            f"<pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>"
            f"<p>{html_mod.escape(LAYMAN_TRANSLATION.strip())}</p>"
            "</body></html>",
            encoding="utf-8",
        )
        ntfy = ROOT / "tools" / "ntfy_job_done.py"
        if ntfy.is_file():
            subprocess.run(
                [py, str(ntfy), "--path", str(fail_html), "-t", "RL +20% vs 90/10 runners AB FAILED"],
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
        cmd.extend(
            [
                "-t",
                "RL +20% vs 90/10 runners",
                "-m",
                "A 100% at +20%. B–E are 90/10 runners: BE or original stop, then +40% or +50%. "
                + " ".join(
                    f"{aid}={result['verdicts'][aid]['is'][0]}" for aid in CAND_IDS
                ),
            ]
        )
        subprocess.run(cmd, cwd=str(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
