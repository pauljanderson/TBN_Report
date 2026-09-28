"""WPBR full-universe A/B: breakout confirmation 0.04 and 0.05 vs production 0.03.

Control reuses tonight's full-universe production-knob run (confirmation 0.03).
One ENTRY knob: wpbr_breakout_confirmation.
IS = entry < 2024-01-01. OOS report-only. Research-only.

Usage:
  python tools/wpbr_bo_confirm_04_05_fulluniv_ab.py --workers 12
  python tools/wpbr_bo_confirm_04_05_fulluniv_ab.py --summarize-only
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
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
OUT_DIR = DRIVE / "paul_experiments" / f"wpbr_bo_confirm_04_05_fulluniv_ab_{STAMP}"
RUNS_DIR = OUT_DIR / "runs"
TAG = "WPBR-BO-CONFIRM"
CTRL_ID = "confirm03"

CTRL_SRC = DRIVE / "paul_experiments" / "wpbr_fulluniv_closed_20260927"
ARMS = (
    (CTRL_ID, None, "Control: confirmation 0.03"),
    ("confirm04", 0.04, "1: confirmation 0.04"),
    ("confirm05", 0.05, "2: confirmation 0.05"),
)
CAND_IDS = [aid for aid, val, _lbl in ARMS if val is not None]

REQUEST_PROMPT = """\
Can you run an AB test on WPBR with the full universe as the control vs. 1. changing breakout confirmation to .04 and 2. changing it to .05
"""

LAYMAN_TRANSLATION = """\
Pivot Break and Retest (WPBR) buys a pullback after a weekly shelf breaks. Production asks the weekly \
high to clear the top of that shelf by 3% before the pullback search starts. This test keeps every \
other production rule and runs it on every stock we have daily history for, not the short Mag9 list. \
Book 1 raises that clearance to 4%. Book 2 raises it to 5%. A higher number means fewer breakouts \
qualify. The years before 2024 decide the call. 2024 onward is shown and is not used to pick a number.
"""

INTERPRETATION = """\
Control reuses the 2026-09-27 full-universe run at wpbr_breakout_confirmation=0.03. Books 1 and 2 \
change only that confirmation, to 0.04 and 0.05. Stage 2 still needs a weekly high above the zone \
top times (1 + that number). Band stays 1.5%, strong pivots stay either-side 3 bars / 10%, retest \
window stays 2 days, second chance after a win stays on, stop stays 0.91 times entry, target stays \
1.22 times entry. No 2016 start-date cut. Indicators are recorded and do not gate buys. Universe is \
every CSV under data/newdata/data. Choosing a confirmation after seeing this table is in-sample \
selection. Research-only. Not gold. Not DailyRun.
"""

COMMON = [
    "wpbr_zones=true",
    "brt_zones=false",
    "yh_zones=false",
    "vec_zones=false",
    "band_pct=0.015",
    "strong_pre_pivot_bars=3",
    "strong_pre_pivot_pct=0.10",
    "strong_post_pivot_bars=3",
    "strong_post_pivot_pct=0.10",
    "strong_pivot_mode=either",
    "wpbr_max_days_after_retest=2",
    "wpbr_second_chance_after_win=true",
    "growth_filter_enabled=false",
    "min_spy_compare_1y_at_trigger=-1000",
    "ind_score_weights_path=",
    "too_high_multiplier=0",
    "target_pct=1.22",
    "stop_pct=0.91",
    "sheet_no_entry_same_bar_after_exit=false",
    "use_indicators=true",
    "max_market_cap=0",
    "min_market_cap=0",
]

SHOW = [
    ("SYMBOL", "Symbol", "text"),
    ("SIDE", "Side", "text"),
    ("DATE_OPENED", "Date opened", "date"),
    ("DATE_CLOSED", "Date closed", "date"),
    ("ENTRY_PRICE", "Entry price", "num"),
    ("EXIT_PRICE", "Exit price", "num"),
    ("PNL_PCT", "PnL %", "num"),
    ("PNL_DOLLARS", "PnL $", "num"),
    ("DAYS_HELD", "Days held", "num"),
    ("EXIT_TYPE", "Exit", "text"),
    ("STOP_PRICE", "Stop", "num"),
    ("TARGET_PRICE", "Target", "num"),
    ("ANN_ROR_PCT", "Ann. return %", "num"),
    ("SECTOR", "Sector", "text"),
    ("INDUSTRY", "Industry", "text"),
]

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(DRIVE / "paul_experiments"))
from be_stop_replay_ab import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from compare_format import filter_html_compare_columns  # noqa: E402
from rl_partial_vs_gap7_ab import _copy_patterns, _line  # noqa: E402
from rl_univ_compare_lists import (  # noqa: E402
    SA,
    _find_latest,
    _resolve_python,
    compare_row,
    load_trades,
    pack_result,
    pairwise_delta_row,
    verdict_vs_control,
    write_metrics_csv,
)


def _find_wpbr(folder: Path, kind: str) -> Path | None:
    return _find_latest(folder, f"WPBR_{kind}_*.csv")


def _copy_control() -> None:
    dest = RUNS_DIR / CTRL_ID
    dest.mkdir(parents=True, exist_ok=True)
    if not CTRL_SRC.is_dir():
        raise FileNotFoundError(f"missing control run dir: {CTRL_SRC}")
    for pat in (
        "WPBR_Closed_*.csv",
        "WPBR_Summary_*.csv",
        "WPBR_EquityMeta_*.csv",
        "WPBR_Report_*.csv",
        "WPBR_EquityCurve_*.csv",
        "WPBR_EquityCurve_Regular_*.csv",
    ):
        src = _find_latest(CTRL_SRC, pat)
        if src and src.is_file():
            target = dest / src.name
            if not target.is_file():
                target.write_bytes(src.read_bytes())


def _arm_complete(src_dir: Path) -> bool:
    closed = _find_wpbr(src_dir, "Closed")
    report = _find_wpbr(src_dir, "Report")
    meta = _find_wpbr(src_dir, "EquityMeta")
    curve = _find_latest(src_dir, "WPBR_EquityCurve_Regular_*.csv")
    return all(p is not None and p.is_file() and p.stat().st_size > 0 for p in (closed, report, meta, curve))


def _arm_from_dir(arm_id: str, label: str, role: str, src_dir: Path) -> dict[str, Any]:
    if not _arm_complete(src_dir):
        raise FileNotFoundError(f"incomplete outputs for {arm_id} under {src_dir}")
    closed = _find_wpbr(src_dir, "Closed")
    if not closed or not closed.is_file():
        raise FileNotFoundError(f"missing closed CSV for {arm_id} under {src_dir}")
    trades = load_trades(closed)
    syms = sorted(p.stem.upper() for p in DATA_DIR.glob("*.csv")) if DATA_DIR.is_dir() else []
    report = _find_wpbr(src_dir, "Report")
    return {
        "arm": {"id": arm_id, "label": label, "role": role, "univ_n": len(syms), "symbols": syms},
        "ok": len(trades) > 0,
        "closed": closed,
        "trades": trades,
        "stamp": closed.stem.split("_")[-1],
        "summary": _find_wpbr(src_dir, "Summary"),
        "equity_meta": _find_wpbr(src_dir, "EquityMeta"),
        "report": report,
        "equity_curve": _find_latest(src_dir, "WPBR_EquityCurve_Regular_*.csv")
        or _find_wpbr(src_dir, "EquityCurve"),
    }


def build_cmd(py: str, outdir: Path, workers: int, confirm: float) -> list[str]:
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
    for v in COMMON + [f"wpbr_breakout_confirmation={confirm}"]:
        cmd.extend(["-v", v])
    return cmd


def run_fresh(py: str, arm_id: str, label: str, confirm: float, workers: int, skip_existing: bool) -> dict[str, Any]:
    arm_dir = RUNS_DIR / arm_id
    arm_dir.mkdir(parents=True, exist_ok=True)
    if skip_existing and _arm_complete(arm_dir):
        return _arm_from_dir(arm_id, label, "candidate", arm_dir)
    cmd = build_cmd(py, arm_dir, workers, confirm)
    log_path = arm_dir / "run.log"
    t0 = time.time()
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write("CMD: " + " ".join(cmd) + "\n\n")
        log.flush()
        proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(ROOT))
    print(f"[{TAG}] {arm_id} elapsed={time.time() - t0:.0f}s exit={proc.returncode}", flush=True)
    run = _arm_from_dir(arm_id, label, "candidate", arm_dir)
    run["ok"] = proc.returncode == 0 and run["ok"]
    run["exit_code"] = proc.returncode
    return run


def _call(is_v: str, oos_v: str) -> str:
    if is_v == "DISMISS":
        return "DISMISS"
    if is_v in ("KEEP", "LEAN KEEP") and oos_v in ("DISMISS", "HOLD"):
        return "HOLD"
    if is_v in ("KEEP", "LEAN KEEP"):
        return is_v
    return "HOLD"


def _ymd(raw: str) -> str:
    s = (raw or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def write_closed_html(closed_csv: Path, out_html: Path, *, title: str, note: str) -> Path:
    rows: list[dict[str, str]] = []
    with closed_csv.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            rows.append(raw)

    def sort_type(name: str) -> str:
        return next(kind for key, _lab, kind in SHOW if key == name)

    th = "".join(sortable_th(lab, kind) for _k, lab, kind in SHOW)
    body = []
    for r in rows:
        tds = []
        for key, _lab, _kind in SHOW:
            val = r.get(key, "") or ""
            if key in {"DATE_OPENED", "DATE_CLOSED"}:
                val = _ymd(val)
            tds.append(f"<td>{html_mod.escape(val)}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    css = SORTABLE_TH_CSS.replace(
        "th.sortable-th:hover{background:#e8e4d8}",
        "th.sortable-th:hover{background:#2a3545}",
    )
    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html_mod.escape(title)}</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; --accent:#5b9fd4; }}
*{{box-sizing:border-box}}
body{{margin:0;font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header,main{{max-width:1600px;margin:0 auto;padding:1rem}}
h1{{font-size:1.3rem;margin:0 0 .35rem}}
.muted{{color:var(--muted);font-size:.92rem}}
.callout,section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.85rem 1rem;margin:1rem 0}}
pre{{white-space:pre-wrap;font-size:.88rem}}
.table-wrap{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:.78rem}}
th,td{{border-bottom:1px solid var(--line);padding:.3rem .4rem;text-align:right;white-space:nowrap}}
th:first-child,td:first-child{{text-align:left}}
{css}
</style></head><body>
<header><h1>{html_mod.escape(title)}</h1>
<p class="muted">Source <code>{html_mod.escape(closed_csv.name)}</code>. {len(rows):,} closed trades. Click column headers to sort.</p></header>
<main>
<div class="callout"><strong>What you asked</strong>
<pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>
<p><strong>In plain English.</strong> {html_mod.escape(LAYMAN_TRANSLATION.strip())}</p>
<p class="muted">{html_mod.escape(note)}</p></div>
<section><h2 style="color:var(--accent);font-size:1.05rem">Closed trades</h2>
<div class="table-wrap"><table class="sortable"><thead><tr>{th}</tr></thead>
<tbody>{''.join(body)}</tbody></table></div></section>
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    out_html.write_text(page, encoding="utf-8")
    return out_html


def write_html(packed, calls, verdicts, closed_pages: list[Path]) -> Path:
    by_id = {p["arm"]["id"]: p for p in packed}
    baseline = by_id[CTRL_ID]
    th = "".join(
        sortable_th(a, b)
        for a, b in filter_html_compare_columns(
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
                ("Max days UW", "num"),
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
    note = (
        "Control confirmation is 3%. Book 1 is 4%. Book 2 is 5%. "
        "Full stock universe. Deltas are versus control. Click column headers to sort."
    )
    sections = []
    for split_key, title in (("m_is", "In-sample (bought before 2024)"), ("m_oos", "Out-of-sample, report-only"), ("m_full", "Full book")):
        body = "".join(compare_row(p, split_key, baseline, "", CTRL_ID) for p in packed)
        sections.append(
            f"<section><h2>{title}</h2><p class=\"muted\">{note}</p>"
            f"<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>{th}</tr></thead>"
            f"<tbody>{body}</tbody></table></div></section>"
        )
    pw_th = "".join(
        sortable_th(a, b)
        for a, b in [
            ("Pair", "text"),
            ("Δ Trades", "num"),
            ("Δ Avg%", "num"),
            ("Δ WO_MAX", "num"),
            ("Δ WR", "num"),
            ("Δ PF", "num"),
            ("Δ Ann ROR", "num"),
            ("Δ Max DD", "num"),
        ]
    )
    pairs = [(f"{by_id[aid]['arm']['label']} − Control", baseline, by_id[aid]) for aid in CAND_IDS]
    pw = []
    for split_key, title in (("m_is", "In-sample"), ("m_oos", "Out-of-sample"), ("m_full", "Full book")):
        rows = "".join(pairwise_delta_row(a, b, split_key, lbl) for lbl, a, b in pairs)
        pw.append(
            f"<section><h2>Pairwise — {title}</h2>"
            f"<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>{pw_th}</tr></thead>"
            f"<tbody>{rows}</tbody></table></div></section>"
        )
    exit_names = sorted({e for p in packed for e in p["m_full"]["exits"]})
    exit_th = "".join(sortable_th(x, "text" if i == 0 else "num") for i, x in enumerate(["Arm", *exit_names]))
    exit_rows = []
    for p in packed:
        ex = p["m_full"]["exits"]
        n = p["m_full"]["n"] or 1
        cells = [html_mod.escape(p["arm"]["label"])]
        for name in exit_names:
            c = int(ex.get(name, 0))
            cells.append(f"{c:,} ({100.0 * c / n:.1f}%)")
        exit_rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    items = []
    for aid in CAND_IDS:
        vis, nis = verdicts[aid]["is"]
        voos, noos = verdicts[aid]["oos"]
        items.append(
            f"<li><strong>{html_mod.escape(by_id[aid]['arm']['label'])}: {html_mod.escape(calls[aid])}</strong> "
            f"IS <code>{html_mod.escape(vis)}</code> — {html_mod.escape(nis)} "
            f"OOS <code>{html_mod.escape(voos)}</code> — {html_mod.escape(noos)}</li>"
        )
    links = "".join(f'<li><a href="{html_mod.escape(p.name)}">{html_mod.escape(p.stem)}</a></li>' for p in closed_pages)
    css = SORTABLE_TH_CSS.replace(
        "th.sortable-th:hover{background:#e8e4d8}",
        "th.sortable-th:hover{background:#2a3545}",
    )
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>WPBR full universe — confirmation 0.04 and 0.05</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; --accent:#5b9fd4; --ctrl:#243044; }}
*{{box-sizing:border-box}}
body{{margin:0;font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header{{padding:1.25rem 1rem .5rem;max-width:1400px;margin:0 auto}}
h1{{font-size:1.35rem;margin:0 0 .35rem}}
h2{{font-size:1.05rem;margin:.2rem 0 .4rem;color:var(--accent)}}
.muted{{color:var(--muted);font-size:.92rem}}
.callout{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem;margin:.75rem 0}}
.req pre{{white-space:pre-wrap;font-family:ui-monospace,Consolas,monospace;font-size:.82rem;margin:.4rem 0 0}}
main{{max-width:1400px;margin:0 auto;padding:0 1rem 2.5rem}}
section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem 1rem;margin:1rem 0}}
.table-wrap{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:.78rem;min-width:900px}}
th,td{{border-bottom:1px solid var(--line);padding:.35rem .4rem;text-align:right;white-space:nowrap}}
th:first-child,td:first-child{{text-align:left}}
tr.ctrl-row{{background:var(--ctrl)}}
a{{color:var(--accent)}}
{css}
</style></head><body>
<header><h1>WPBR full universe, breakout confirmation 4% and 5%.</h1>
<p class="muted">Stamp <code>wpbr_bo_confirm_04_05_fulluniv_ab_{STAMP}</code>. Research-only. Not gold. Not DailyRun.</p></header>
<main>
<div class="callout req">
<strong>What you asked</strong>
<pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>
<p><strong>In plain English:</strong> {html_mod.escape(LAYMAN_TRANSLATION.strip())}</p>
<p><strong>Interpretation:</strong> {html_mod.escape(INTERPRETATION.strip())}</p>
</div>
<div class="callout"><strong>Calls versus control (confirmation 0.03)</strong>
<ul>{''.join(items)}</ul>
<p class="muted">Judge average gain and profit factor. A softer out-of-sample result is a hold. Research-only.</p></div>
<div class="callout"><strong>Closed-trade pages</strong><ul>{links}</ul></div>
{''.join(sections)}
<section><h2>How trades ended (full book)</h2>
<div class="table-wrap"><table class="sortable"><thead><tr>{exit_th}</tr></thead>
<tbody>{''.join(exit_rows)}</tbody></table></div></section>
{''.join(pw)}
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path = OUT_DIR / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_docs(packed, html_path, calls, verdicts) -> None:
    by_id = {p["arm"]["id"]: p for p in packed}
    lines = [
        f"# BASELINE — `wpbr_bo_confirm_04_05_fulluniv_ab_{STAMP}`",
        "",
        "**Status:** RESEARCH only. One knob: `wpbr_breakout_confirmation`. Full universe. Partial-exit rules do not apply; this is WPBR.",
        f"**Control `{CTRL_ID}`:** confirmation `0.03`. Reuse `{CTRL_SRC.as_posix()}`.",
        "**1 `confirm04`:** confirmation `0.04`.",
        "**2 `confirm05`:** confirmation `0.05`.",
        "Stop `0.91`, target `1.22`, band `0.015`, retest window 2 days, second chance after a win on. Not gold. Not DailyRun.",
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
        "## Split metrics",
        "",
    ]
    for aid, _val, label in ARMS:
        short = label.split(":")[0]
        for key, split in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
            lines.append(f"- **{short} {split}:** {_line(by_id[aid], key)}")
    lines.extend(["", "## Verdict versus control", ""])
    for aid in CAND_IDS:
        v, n = verdicts[aid]["is"]
        vo, no = verdicts[aid]["oos"]
        lines.append(f"- **`{aid}` {calls[aid]}** IS `{v}` ({n}); OOS `{vo}` ({no}).")
    lines.extend(["", "- OOS is report-only. Do not retune.", "", f"Compare: `{html_path.as_posix()}`", ""])
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")
    summary = [f"# SUMMARY — `wpbr_bo_confirm_04_05_fulluniv_ab_{STAMP}`", ""]
    for aid in CAND_IDS:
        v, n = verdicts[aid]["is"]
        vo, no = verdicts[aid]["oos"]
        summary.append(f"- **`{aid}` {calls[aid]}** IS `{v}` ({n}); OOS `{vo}` ({no}).")
    summary.append("")
    for aid, _val, label in ARMS:
        short = label.split(":")[0]
        for key, split in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
            summary.append(f"- {short} {split}: {_line(by_id[aid], key)}")
    summary.extend(["", f"Compare: `{html_path.as_posix()}`", ""])
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(summary), encoding="utf-8")


def _notify(py: str, paths: list[Path], message: str) -> None:
    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    if not ntfy.is_file():
        return
    cmd = [py, str(ntfy), "-t", "WPBR confirmation A/B", "-m", message]
    for p in paths:
        cmd.extend(["--path", str(p)])
    subprocess.run(cmd, cwd=str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    py = _resolve_python()
    skip = args.skip_existing or args.summarize_only

    def fail(msg: str) -> int:
        path = OUT_DIR / "compare.html"
        path.write_text(
            "<html><body><h1>WPBR confirmation test failed</h1>"
            f"<p>{html_mod.escape(msg)}</p>"
            f"<pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>"
            f"<p>{html_mod.escape(LAYMAN_TRANSLATION.strip())}</p></body></html>",
            encoding="utf-8",
        )
        _notify(py, [path], msg)
        print(f"[{TAG}] {msg}", flush=True)
        return 1

    runs: dict[str, dict[str, Any]] = {}
    try:
        _copy_control()
        runs[CTRL_ID] = _arm_from_dir(CTRL_ID, ARMS[0][2], "control", RUNS_DIR / CTRL_ID)
    except FileNotFoundError as exc:
        return fail(str(exc))

    fresh = [(aid, val, lbl) for aid, val, lbl in ARMS if val is not None]
    if skip:
        for aid, _val, lbl in fresh:
            try:
                runs[aid] = _arm_from_dir(aid, lbl, "candidate", RUNS_DIR / aid)
            except FileNotFoundError as exc:
                return fail(str(exc))
    else:
        with ThreadPoolExecutor(max_workers=len(fresh)) as ex:
            futs = {
                ex.submit(run_fresh, py, aid, lbl, val, args.workers, False): aid
                for aid, val, lbl in fresh
            }
            for fut in as_completed(futs):
                runs[futs[fut]] = fut.result()

    if not all(runs[aid].get("ok") for aid, _v, _l in ARMS):
        return fail("one or more arms failed")

    ordered = [runs[aid] for aid, _v, _l in ARMS]
    packed = [pack_result(r) for r in ordered]
    by_id = {p["arm"]["id"]: p for p in packed}
    verdicts = {
        aid: {
            "is": verdict_vs_control(by_id[aid], by_id[CTRL_ID], "m_is"),
            "oos": verdict_vs_control(by_id[aid], by_id[CTRL_ID], "m_oos"),
        }
        for aid in CAND_IDS
    }
    calls = {aid: _call(verdicts[aid]["is"][0], verdicts[aid]["oos"][0]) for aid in CAND_IDS}
    closed_pages = []
    for aid, _val, label in ARMS:
        note = f"{label}. Production WPBR rules otherwise. Full universe."
        closed_pages.append(
            write_closed_html(
                Path(runs[aid]["closed"]),
                OUT_DIR / f"closed_{aid}.html",
                title=f"WPBR closed — {label}",
                note=note,
            )
        )
    html_path = write_html(packed, calls, verdicts, closed_pages)
    write_metrics_csv(packed, "", OUT_DIR / "metrics_all.csv")
    write_docs(packed, html_path, calls, verdicts)
    for aid in CAND_IDS:
        print(f"[{TAG}] {aid} {calls[aid]} IS={verdicts[aid]['is'][0]} OOS={verdicts[aid]['oos'][0]}", flush=True)
    print(f"[{TAG}] Wrote {html_path}", flush=True)
    bits = " ".join(f"{aid}={calls[aid]}" for aid in CAND_IDS)
    _notify(py, [html_path, *closed_pages], f"WPBR full-universe confirmation 0.04 and 0.05. {bits}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
