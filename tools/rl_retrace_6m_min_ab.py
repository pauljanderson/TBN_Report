#!/usr/bin/env python3
"""RL ENTRY A/B: pct20_d60 control vs minimum 6-month retrace floors of 30/40/50.

RETRACE_6M_PCT = ((HIGH_6M - ENTRY_PRICE) / (HIGH_6M - LOW_6M)) * 100

HIGH_6M / LOW_6M are the highest daily high and lowest daily low in the
6 calendar months strictly before the entry date. Same function for the
gate and for the column on every arm. Lookback is rl_retrace_months=6.

Control is the frozen pct20_d60 book (no retrace floor). A/B/C re-simulate
that entry freeze and skip a buy when retrace is missing or below the floor.
Skipping a buy can free the name for a later entry.

IS = entry < 2024-01-01. OOS report-only. Pre-specified 30/40/50 grid.
Research-only. Not gold. Not DailyRun.
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

import duckdb
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
DATA_DIR = ROOT / "data" / "newdata" / "data"
STAMP = "20260926"
OUT_DIR = DRIVE / "paul_experiments" / f"rl_retrace_6m_min_ab_{STAMP}"
MONTHS = 6
RUNS_DIR = OUT_DIR / "runs"
CTRL_SRC = (
    DRIVE / "paul_experiments" / "rl_no_sma_target_exit_ab_20260905" / "runs" / "pct20_d60"
)
DB_PATH = ROOT / "data" / "ohlcv.duckdb"
CONTROL_DATA_END = "20260904"
HOUSE_STOP = 0.934
HOUSE_CUT = 1000
HOUSE_DIP = 1.055
TH13 = 1.13
MIN_AVG_VOL = 10_000
MIN_TRIGGER_VOL = 5_000

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "stock_analysis"))
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
    split_is_oos,
    verdict_vs_control,
    write_metrics_csv,
    _find_latest,
    _resolve_python,
)
from rocket_rl import rl_retrace_12m_pct  # noqa: E402

ARMS = (
    ("control", "Control pct20_d60 (no retrace floor)", 0.0, True),
    ("A_30", "A minimum 30% 6M retrace", 30.0, False),
    ("B_40", "B minimum 40% 6M retrace", 40.0, False),
    ("C_50", "C minimum 50% 6M retrace", 50.0, False),
)
CAND_IDS = ["A_30", "B_40", "C_50"]
TAG = "RL-RETRACE-6M-MIN"

REQUEST_PROMPT = """\
Can you run that again but use 6 months instead of 12. same reporting

Same four books as the 12-month test. Control, then minimum 30%, 40%, and 50%.
RETRACE_6M_PCT = ((HIGH_6M - ENTRY_PRICE) / (HIGH_6M - LOW_6M)) × 100
Compare shows Avg 6M Retrace and Median 6M Retrace for Control/A/B/C in IS, OOS, and FULL.
"""

LAYMAN = """\
Control is the usual pct20_d60 Rocket Launcher book: buy the dip, and sell 60 market days
after the trade is up 20%, with the moving-average profit target turned off.
The tests add one extra buy rule. Look at the highest high and the lowest low in the
6 calendar months before the buy. Retrace is how far the buy price has fallen from that
high, as a percent of the distance from the high down to the low. A keeps the buy only
when that give-back is at least 30%. B requires 40%. C requires 50%.
The buy day itself is not part of the high or the low. Every book, including control,
gets the same retrace number on each trade.
"""


def _control_v(floor: float) -> list[str]:
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
        "rl_exit_percent=0.20",
        "rl_exit_days=60",
        "rl_post_target_reentry_bars=0",
        f"rl_too_high={TH13}",
        f"rl_min_avg_vol={MIN_AVG_VOL}",
        f"rl_min_trigger_vol={MIN_TRIGGER_VOL}",
        f"rl_min_retrace_12m_pct={floor}",
        "rl_retrace_months=6",
    ]
    if floor > 0:
        vs.append(f"entry_end_date={CONTROL_DATA_END}")
    return vs


def _copy_control() -> Path:
    dest = RUNS_DIR / "control"
    dest.mkdir(parents=True, exist_ok=True)
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
    closed = _find_latest(dest, "RL_Closed_*.csv")
    if not closed:
        raise FileNotFoundError(CTRL_SRC)
    return closed


def _run_arm(py: str, arm_id: str, floor: float, workers: int) -> Path:
    arm_dir = RUNS_DIR / arm_id
    arm_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        py,
        str(SA / "rocket_tbn.py"),
        str(DATA_DIR),
        "-o",
        str(arm_dir),
        "-w",
        str(workers),
        "--aggressive",
        "--use-duckdb",
        "--no-regression",
    ]
    if PER_SYMBOL.is_file():
        cmd.extend(["--per-symbol-settings", str(PER_SYMBOL)])
    for v in _control_v(floor):
        cmd.extend(["-v", v])
    log_path = arm_dir / "run.log"
    t0 = time.time()
    with log_path.open("w", encoding="utf-8") as log:
        log.write("CMD: " + " ".join(cmd) + "\n\n")
        log.flush()
        proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(ROOT))
    closed = _find_latest(arm_dir, "RL_Closed_*.csv")
    print(
        f"[{TAG}] {arm_id} exit={proc.returncode} closed={closed.name if closed else None} "
        f"elapsed={time.time() - t0:.0f}s",
        flush=True,
    )
    if proc.returncode != 0 or not closed:
        raise RuntimeError(f"{arm_id} failed")
    return closed


def _load_bars(symbols: list[str]) -> dict[str, tuple[list[str], np.ndarray, np.ndarray]]:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    frame = con.execute(
        """
        SELECT upper(symbol) AS symbol, date, high, low
        FROM prices
        WHERE upper(symbol) IN (SELECT unnest(?))
        ORDER BY symbol, date
        """,
        [symbols],
    ).df()
    con.close()
    out: dict[str, tuple[list[str], np.ndarray, np.ndarray]] = {}
    if frame.empty:
        return out
    frame["date"] = frame["date"].astype(str).str.replace("-", "", regex=False)
    for sym, grp in frame.groupby("symbol", sort=False):
        out[str(sym)] = (
            grp["date"].tolist(),
            grp["high"].to_numpy(dtype=np.float64),
            grp["low"].to_numpy(dtype=np.float64),
        )
    return out


def _entry_index(dates: list[str], ymd: str) -> int:
    # First bar on the entry date. Window uses bars strictly before that index.
    try:
        return dates.index(ymd)
    except ValueError:
        return -1


def _retrace_for(pack: Optional[tuple[list[str], np.ndarray, np.ndarray]], ymd: str, entry: float) -> Optional[float]:
    if pack is None:
        return None
    idx = _entry_index(pack[0], ymd)
    if idx < 0:
        return None
    return rl_retrace_12m_pct(pack[0], pack[1], pack[2], idx, entry, months=MONTHS)


def _ymd_from_opened(raw: str) -> str:
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    return digits[:8]


def _enrich_csv(src: Path, dest: Path, bars: dict) -> None:
    with src.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = [{k: (v if v is not None else "") for k, v in raw.items()} for raw in reader]
    if "RETRACE_6M_PCT" not in fields:
        at = fields.index("ENTRY PRICE") + 1 if "ENTRY PRICE" in fields else 3
        fields.insert(at, "RETRACE_6M_PCT")
    for r in rows:
        sym = str(r.get("SYMBOL") or "").strip().upper()
        ymd = _ymd_from_opened(str(r.get("DATE OPENED") or ""))
        try:
            entry = float(str(r.get("ENTRY PRICE") or "").replace(",", ""))
        except ValueError:
            entry = float("nan")
        pct = _retrace_for(bars.get(sym), ymd, entry)
        r["RETRACE_6M_PCT"] = "" if pct is None else f"{pct:.4f}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _attach(trades: list[dict[str, Any]], bars: dict) -> None:
    for t in trades:
        opened = t["opened"]
        ymd = opened.strftime("%Y%m%d") if hasattr(opened, "strftime") else _ymd_from_opened(str(opened))
        t["retrace"] = _retrace_for(bars.get(t["sym"]), ymd, float(t.get("entry") or 0))


def _retrace_pair(trades: list[dict[str, Any]]) -> tuple[Optional[float], Optional[float], int]:
    vals = [float(t["retrace"]) for t in trades if t.get("retrace") is not None and math.isfinite(float(t["retrace"]))]
    if not vals:
        return None, None, 0
    return float(np.mean(vals)), float(np.median(vals)), len(vals)


def _sort_type(name: str) -> str:
    u = name.upper()
    if "DATE" in u:
        return "date"
    if any(x in u for x in ("PNL", "PRICE", "DAYS", "GAIN", "MAE", "STOP", "TARGET", "LOW_", "HIGH_", "RETRACE", "%")):
        return "num"
    return "text"


def _display(col: str, raw: str) -> str:
    val = str(raw or "")
    if _sort_type(col) == "date" and len(val) == 8 and val.isdigit():
        return f"{val[:4]}-{val[4:6]}-{val[6:8]}"
    return val


def write_closed_html(csv_path: Path, html_path: Path, *, arm_id: str, floor: float) -> None:
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    th = "".join(sortable_th(c, _sort_type(c)) for c in fields)
    body = []
    for r in rows:
        cells = "".join(
            f"<td>{html_mod.escape(_display(c, r.get(c, '') or ''))}</td>" for c in fields
        )
        body.append(f"<tr>{cells}</tr>")
    floor_note = (
        "No retrace floor. Every control trade is kept."
        if floor <= 0
        else f"Buy kept only when RETRACE_6M_PCT is at least {floor:.0f}."
    )
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>RL closed — {html_mod.escape(arm_id)} retrace floor</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; --accent:#5b9fd4; }}
body{{margin:0;font-family:ui-sans-serif,system-ui,Segoe UI,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header,main{{max-width:1600px;margin:0 auto;padding:1rem}}
.callout,section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem;margin:.75rem 0}}
.muted{{color:var(--muted)}}
.table-wrap{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:.72rem}}
th,td{{border-bottom:1px solid var(--line);padding:.28rem .35rem;text-align:right;white-space:nowrap}}
th:first-child,td:first-child{{text-align:left}}
{SORTABLE_TH_CSS.replace('th.sortable-th:hover{{background:#e8e4d8}}', 'th.sortable-th:hover{{background:#2a3545}}')}
</style></head><body>
<header><h1>Closed trades — {html_mod.escape(arm_id)}</h1>
<p class="muted">N={len(rows)}. {floor_note} All usual closed columns, plus RETRACE_6M_PCT after ENTRY PRICE. Click headers to sort.</p>
</header>
<main>
<div class="callout"><strong>What you asked</strong>
<pre style="white-space:pre-wrap;font-size:.82rem">{html_mod.escape(REQUEST_PROMPT.strip())}</pre>
<p><strong>In plain English:</strong> {html_mod.escape(LAYMAN.strip())}</p></div>
<section><p class="muted">{html_mod.escape(floor_note)} Formula: ((HIGH_6M − entry) / (HIGH_6M − LOW_6M)) × 100. The 6-month high and low use daily bars before the entry day, not the entry day itself.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{th}</tr></thead><tbody>{''.join(body)}</tbody></table></div>
</section></main>
{SORTABLE_TABLE_SCRIPT}
</body></html>"""
    html_path.write_text(html, encoding="utf-8")


def _fmt_ret(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:.2f}"


def write_compare(packed: list[dict[str, Any]], verdicts: dict[str, tuple[str, str]]) -> Path:
    baseline = next(p for p in packed if p["arm_id"] == "control")
    headers = filter_html_compare_columns(
        [
            ("Arm", "text"),
            ("Univ N", "num"),
            ("Trades", "num"),
            ("WR%", "num"),
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
            ("Δ Avg% vs ctrl", "num"),
            ("Δ WR vs ctrl", "num"),
            ("Δ PF vs ctrl", "num"),
            ("Δ Ann ROR vs ctrl", "num"),
            ("Δ Max DD vs ctrl", "num"),
            ("Δ Calmar vs ctrl", "num"),
            ("IS pick", "text"),
        ]
    )
    th = "".join(sortable_th(a, b) for a, b in headers)
    sections = []
    for key, title in (("m_is", "IS (entries before 2024)"), ("m_oos", "OOS (2024 on, report-only)"), ("m_full", "FULL")):
        # compare_row expects arm["id"], arm["label"], arm["symbols"]
        body = "".join(
            compare_row(p, key, baseline, "", "control") for p in packed
        )
        sections.append(
            f"<section><h2>{title}</h2><p class=\"muted\">Click headers to sort. Δ is the test minus control.</p>"
            f"<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div></section>"
        )

    ret_th = "".join(
        sortable_th(a, b)
        for a, b in (
            ("Arm", "text"),
            ("Split", "text"),
            ("Trades", "num"),
            ("N with retrace", "num"),
            ("Avg 6M Retrace", "num"),
            ("Median 6M Retrace", "num"),
        )
    )
    ret_rows = []
    for p in packed:
        for key, split_name, label in (
            ("is", "IS", p["arm"]["label"]),
            ("oos", "OOS", p["arm"]["label"]),
            ("full", "FULL", p["arm"]["label"]),
        ):
            avg, med, n_ok = p["retrace"][key]
            ret_rows.append(
                "<tr>"
                f"<td>{html_mod.escape(label)}</td><td>{split_name}</td>"
                f"<td>{p['retrace_n'][key]}</td><td>{n_ok}</td>"
                f"<td>{_fmt_ret(avg)}</td><td>{_fmt_ret(med)}</td></tr>"
            )
    ret_sec = (
        "<section><h2>6-month retrace — average and median</h2>"
        "<p class=\"muted\">Same formula on every book: ((HIGH_6M − entry) / (HIGH_6M − LOW_6M)) × 100. "
        "Average and median use trades that have a defined retrace. A blank range is left out of those two numbers. "
        "Click headers to sort.</p>"
        f"<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>{ret_th}</tr></thead>"
        f"<tbody>{''.join(ret_rows)}</tbody></table></div></section>"
    )
    vbits = "".join(
        f"<li><strong>{aid}</strong> IS {verdicts[aid][0]} — {html_mod.escape(verdicts[aid][1])}</li>"
        for aid in CAND_IDS
    )
    closed_links = "".join(
        f'<li><a href="closed/{aid}_closed.html">{html_mod.escape(label)}</a></li>'
        for aid, label in (
            ("control", "Control — no retrace floor"),
            ("A_30", "A minimum 30%"),
            ("B_40", "B minimum 40%"),
            ("C_50", "C minimum 50%"),
        )
    )
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>RL 6M retrace floor A/B</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; --accent:#5b9fd4; --ctrl:#243044; }}
*{{box-sizing:border-box}}
body{{margin:0;font-family:ui-sans-serif,system-ui,Segoe UI,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header,main{{max-width:1600px;margin:0 auto;padding:.5rem 1rem 2rem}}
h1{{font-size:1.3rem}} h2{{color:var(--accent);font-size:1.05rem}}
.muted{{color:var(--muted);font-size:.92rem}}
a{{color:var(--accent)}}
.callout,section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem;margin:.8rem 0}}
.callout pre{{white-space:pre-wrap;font-size:.82rem}}
.table-wrap{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:.78rem;min-width:980px}}
th,td{{border-bottom:1px solid var(--line);padding:.32rem .4rem;text-align:right}}
th:first-child,td:first-child,td:nth-child(2){{text-align:left}}
tr.ctrl-row{{background:var(--ctrl)}}
{SORTABLE_TH_CSS.replace('th.sortable-th:hover{{background:#e8e4d8}}', 'th.sortable-th:hover{{background:#2a3545}}')}
</style></head><body>
<header><h1>pct20_d60 control vs 6-month retrace floors of 30%, 40%, and 50%</h1>
<p class="muted">Stamp rl_retrace_6m_min_ab_{STAMP}. Control reused from pct20_d60 stamp 260905205015. Research-only. Not gold. Not DailyRun.</p>
</header>
<main>
<div class="callout"><strong>What you asked</strong>
<pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>
<p><strong>In plain English:</strong> {html_mod.escape(LAYMAN.strip())}</p></div>
<div class="callout"><strong>Paul note:</strong>
<ul>{vbits}</ul>
<p class="muted">Judge the floors on in-sample quality. 2024-on is shown and is not used to pick 30, 40, or 50. The three floors were named before the run. This does not change the live book.</p>
</div>
<section><h2>Closed trades</h2>
<p class="muted">Every usual closed column, plus RETRACE_6M_PCT right after ENTRY PRICE. Click a column header to sort.</p>
<ul>{closed_links}</ul>
</section>
{ret_sec}
{''.join(sections)}
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>"""
    path = OUT_DIR / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_baseline(packed: list[dict[str, Any]], verdicts: dict[str, tuple[str, str]]) -> None:
    by = {p["arm_id"]: p for p in packed}

    def cell(aid: str, key: str) -> str:
        avg, med, _n_ok = by[aid]["retrace"][key]
        n = by[aid]["retrace_n"][key]
        if avg is None or med is None:
            return f"— (N={n})"
        return f"{avg:.2f} / {med:.2f} (N={n})"

    def qual(aid: str) -> str:
        m = by[aid]["m_is"]
        o = by[aid]["m_oos"]
        label = "—" if aid == "control" else verdicts[aid][0]
        return (
            f"| {aid} | {m['n']} | {m['avg_pnl']:.2f} | {m['pf']:.2f} | {m['wr']:.1f} | {label} "
            f"| {o['avg_pnl']:.2f} | {o['pf']:.2f} | {o['n']} |"
        )

    lines = [
        "# BASELINE — `rl_retrace_6m_min_ab_20260926`",
        "",
        "**Status:** RESEARCH only. ENTRY filter A/B. Not gold. Not DailyRun. Do not adopt from this stamp.",
        "**Control:** frozen pct20_d60 stamp `260905205015` (reused, not re-run). Retrace floor off.",
        "**Tests:** same freeze, re-simulated. Skip the fill when `RETRACE_6M_PCT` is missing or below the floor.",
        "**Window:** 6 calendar months strictly before the entry date (`rl_retrace_months=6`).",
        "**Data cap (not a strategy knob):** candidates `entry_end_date=20260904`.",
        "**IS pick set:** entries before 2024-01-01. OOS is report-only. Floors 30 / 40 / 50 were set before the run.",
        "",
        "## What you asked",
        "",
        "```",
        REQUEST_PROMPT.strip(),
        "```",
        "",
        "## In plain English",
        "",
        LAYMAN.strip(),
        "",
        "## 6-month retrace (avg / median)",
        "",
        "| Arm | IS | OOS | FULL |",
        "|-----|----|-----|------|",
        f"| Control | {cell('control', 'is')} | {cell('control', 'oos')} | {cell('control', 'full')} |",
        f"| A 30% | {cell('A_30', 'is')} | {cell('A_30', 'oos')} | {cell('A_30', 'full')} |",
        f"| B 40% | {cell('B_40', 'is')} | {cell('B_40', 'oos')} | {cell('B_40', 'full')} |",
        f"| C 50% | {cell('C_50', 'is')} | {cell('C_50', 'oos')} | {cell('C_50', 'full')} |",
        "",
        "## Quality (IS is the decision split)",
        "",
        "| Arm | IS N | IS Avg% | IS PF | IS WR | IS label | OOS Avg% | OOS PF | OOS N |",
        "|-----|------|---------|-------|-------|----------|----------|--------|-------|",
        qual("control"),
        qual("A_30"),
        qual("B_40"),
        qual("C_50"),
        "",
        "OOS softening is a HOLD. Do not retune the floor on 2024+ results.",
        "",
    ]
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    py = _resolve_python()
    runs: list[tuple[str, str, float, Path]] = []
    for arm_id, label, floor, reuse in ARMS:
        arm_dir = RUNS_DIR / arm_id
        existing = _find_latest(arm_dir, "RL_Closed_*.csv") if arm_dir.is_dir() else None
        if reuse:
            closed = _copy_control()
        elif args.skip_existing and existing and existing.stat().st_size > 0:
            closed = existing
            print(f"[{TAG}] reuse {arm_id} {closed.name}", flush=True)
        else:
            closed = _run_arm(py, arm_id, floor, args.workers)
        runs.append((arm_id, label, floor, closed))

    symbols = sorted({p.stem.upper() for p in DATA_DIR.glob("*.csv")})
    bars = _load_bars(symbols)
    packed = []
    closed_htmls: list[Path] = []
    closed_dir = OUT_DIR / "closed"
    closed_dir.mkdir(exist_ok=True)
    for arm_id, label, floor, closed in runs:
        enriched = closed_dir / f"{arm_id}_closed.csv"
        _enrich_csv(closed, enriched, bars)
        trades = load_trades(closed)
        _attach(trades, bars)
        run = {
            "arm": {
                "id": arm_id,
                "label": label,
                "symbols": symbols,
            },
            "trades": trades,
            "closed": closed,
            "summary": _find_latest(RUNS_DIR / arm_id, "RL_Summary_*.csv"),
            "equity_meta": _find_latest(RUNS_DIR / arm_id, "RL_EquityMeta_*.csv"),
            "equity_curve": _find_latest(RUNS_DIR / arm_id, "RL_EquityCurve_*.csv"),
            "ok": True,
        }
        p = pack_result(run)
        p["arm_id"] = arm_id
        is_t, oos_t = split_is_oos(trades)
        p["retrace"] = {
            "is": _retrace_pair(is_t),
            "oos": _retrace_pair(oos_t),
            "full": _retrace_pair(trades),
        }
        p["retrace_n"] = {"is": len(is_t), "oos": len(oos_t), "full": len(trades)}
        below = [
            t for t in trades
            if floor > 0 and (t.get("retrace") is None or float(t["retrace"]) < floor - 1e-6)
        ]
        print(
            f"[{TAG}] {arm_id} n={len(trades)} below_floor={len(below)} "
            f"full avg/med={_fmt_ret(p['retrace']['full'][0])}/{_fmt_ret(p['retrace']['full'][1])}",
            flush=True,
        )
        packed.append(p)
        html_closed = closed_dir / f"{arm_id}_closed.html"
        write_closed_html(enriched, html_closed, arm_id=arm_id, floor=floor)
        closed_htmls.append(html_closed)

    control = next(p for p in packed if p["arm_id"] == "control")
    verdicts = {
        p["arm_id"]: verdict_vs_control(p, control, "m_is")
        for p in packed
        if p["arm_id"] != "control"
    }
    html_path = write_compare(packed, verdicts)
    write_metrics_csv(packed, "", OUT_DIR / "metrics_all.csv")
    write_baseline(packed, verdicts)
    print(f"[{TAG}] wrote {html_path}", flush=True)
    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    if ntfy.is_file():
        cmd = [py, str(ntfy), "--path", str(html_path)]
        for pth in closed_htmls:
            cmd.extend(["--path", str(pth)])
        bits = " ".join(f"{k}={v[0]}" for k, v in verdicts.items())
        cmd.extend(["-t", "RL 6M retrace floor AB", "-m", bits])
        subprocess.run(cmd, cwd=str(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
