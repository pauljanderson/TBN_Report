#!/usr/bin/env python3
"""RL ENTRY A/B: frozen pct20_d60 Control vs one pre-entry 20-bar 7% absolute-gap filter.

Control (reuse, not re-run): rl_no_sma_target_exit_ab_20260905 / runs / pct20_d60
  stamp 260905205015. SMA envelope TARGET off, +20% then 60 trading bars,
  th113 volume entry freeze. Same -v list as that run's log.

Candidate (gap7): identical -v plus ONLY
  rl_pre_entry_gap_bars=20
  rl_pre_entry_gap_pct=7
  Reject a fill when any of the 20 completed bars before the entry date has
  ABS((Open / prior close) - 1) * 100 >= 7. Entry-day gap is not included.

IS = entry_date < 2024-01-01 (2010-2023). OOS = entry_date >= 2024-01-01, report-only.
Research-only. Not gold. Not DailyRun.

Usage:
  python tools/rl_pre_entry_gap7_ab.py --workers 8
  python tools/rl_pre_entry_gap7_ab.py --summarize-only
  python tools/rl_pre_entry_gap7_ab.py --skip-existing --workers 8
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
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
DATA_DIR = ROOT / "data" / "newdata" / "data"
STAMP = "20260925"
OUT_DIR = DRIVE / "paul_experiments" / f"rl_pre_entry_gap7_ab_{STAMP}"
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
GAP_BARS = 20
GAP_PCT = 7.0
IS_YMD = "20240101"
# Last session the frozen 2026-09-05 control snapshot could trade. Not a strategy knob.
CONTROL_DATA_END = "20260904"

CONTROL_ID = "control"
CANDIDATE_ID = "gap7"
TAG = "RL-PRE-ENTRY-GAP7"

REQUEST_PROMPT = """\
Run a clean RL A/B test against the frozen Control.

Control: current frozen RL rules unchanged.

Test: add ONE new entry qualification rule only. Before an RL entry is allowed, calculate the largest absolute overnight opening gap during the 20 completed trading bars immediately preceding the RL entry date.

For each of those 20 bars:

Gap % = ABS((Open / Prior Trading Day Close) - 1) × 100

Test rule: reject the RL entry if ANY of those 20 bars had an absolute opening gap of 7.0% or greater. Allow the entry only when the largest absolute gap is less than 7.0%.

Do not include the RL entry-day gap in the calculation. Use only the 20 completed trading bars before entry.

Change nothing else. Same universe, entry rules, stop, +20%/60-trading-day exit mechanics, sizing, and all other frozen Control settings.

Run the test over the full historical dataset.
"""

LAYMAN_TRANSLATION = """\
Rocket Launcher (RL) buys a dip and, on this control book, sells after the trade is up 20% and then 60 more market days, or sooner if the stop hits. The test keeps every one of those rules. The only new rule is a pre-buy check: look at the 20 completed trading days before the buy day, and measure how far each morning's open jumped from the prior close, up or down. If any of those 20 days jumped 7% or more, skip the buy. The buy day's own opening jump is not part of that check. Adoption uses only the 2010-2023 results. 2024-through-now is shown for information and is not used to pick the 7% cutoff.
"""

ONLY_CHANGE = (
    "The only strategy change is the new pre-entry filter: skip the buy when any of the "
    "20 completed trading days immediately before the entry date opened 7.0% or more away "
    "from the prior close (absolute gap). The entry day's own gap is not counted. "
    "Other entry rules, stop, +20% then 60 trading-day exit, sizing, and every other "
    "frozen Control setting stay as they were. "
    "Buys are also stopped after 2026-09-04, the last session in the frozen Control "
    "price snapshot, so bars added since that run cannot create extra trades."
)

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "stock_analysis"))
sys.path.insert(0, str(DRIVE / "paul_experiments"))
from be_stop_replay_ab import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from compare_format import filter_html_compare_columns, format_money_delta  # noqa: E402
from rl_univ_compare_lists import (  # noqa: E402
    PER_SYMBOL,
    SA,
    compare_row,
    fmt_n,
    load_trades,
    pack_result,
    verdict_vs_control,
    write_metrics_csv,
    _find_latest,
    _resolve_python,
)
from rocket_rl import rl_pre_entry_gap_status  # noqa: E402


def _full_univ_symbols() -> list[str]:
    if not DATA_DIR.is_dir():
        return []
    return sorted(p.stem.upper() for p in DATA_DIR.glob("*.csv"))


def _control_v() -> list[str]:
    """Exact -v list from the frozen pct20_d60 run log (260905205015)."""
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
        "rl_target_pct=1.2",
        "rl_sma_target_off=1",
        f"rl_cut_the_losers={HOUSE_CUT}",
        f"rl_exit_percent={CTRL_EXIT_PCT}",
        f"rl_exit_days={CTRL_EXIT_DAYS}",
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
            "label": "Control pct20_d60 (frozen)",
            "role": "control",
            "symbols": syms,
            "univ_n": n,
            "extra_v": _control_v(),
            "reuse": True,
        },
        {
            "id": CANDIDATE_ID,
            "label": "gap7 (20-bar abs gap < 7%)",
            "role": "candidate",
            "symbols": syms,
            "univ_n": n,
            "extra_v": _control_v()
            + [
                f"rl_pre_entry_gap_bars={GAP_BARS}",
                f"rl_pre_entry_gap_pct={GAP_PCT}",
                f"entry_end_date={CONTROL_DATA_END}",
            ],
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
    closed = _find_latest(dest, "RL_Closed_*.csv")
    if not closed or not closed.is_file():
        raise FileNotFoundError(f"control closed file missing under {CTRL_SRC}")
    n = sum(1 for _ in csv.DictReader(closed.open(encoding="utf-8-sig", newline="")))
    if n != 2802:
        raise RuntimeError(f"frozen control closed count is {n}, expected 2802 ({closed})")
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
            "stamp": closed.stem.split("_")[-1],
            "summary": _find_latest(arm_dir, "RL_Summary_*.csv"),
            "equity_meta": _find_latest(arm_dir, "RL_EquityMeta_*.csv"),
            "report": _find_latest(arm_dir, "RL_Report_*.csv"),
            "elapsed_s": 0.0,
        }

    cmd = build_cmd(py, arm_dir, workers, arm.get("extra_v") or [])
    log_path = arm_dir / "run.log"
    t0 = time.time()
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write("ONLY_CHANGE: " + ONLY_CHANGE + "\n\n")
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


def _load_ohlc_index(symbol: str) -> dict[str, int] | None:
    path = DATA_DIR / f"{symbol}.csv"
    if not path.is_file():
        return None
    dates: list[str] = []
    opens: list[float] = []
    closes: list[float] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            dates.append(str(row["Date"])[:10].replace("-", ""))
            opens.append(float(row["Open"]))
            closes.append(float(row["Close"]))
    return {"dates": dates, "index": {d: i for i, d in enumerate(dates)}, "o": opens, "c": closes}  # type: ignore[return-value]


def scan_control_rejections(closed_csv: Path) -> dict[str, Any]:
    """How many frozen Control fills fail the 7% / 20-bar rule (path-independent)."""
    buckets = ("IS", "OOS", "FULL")
    counts: dict[str, Counter[str]] = {b: Counter() for b in buckets}
    cache: dict[str, Any] = {}
    with closed_csv.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for raw in rows:
        sym = str(raw.get("SYMBOL") or "").strip().upper()
        opened = str(raw.get("DATE OPENED") or "").strip()
        split = "IS" if opened < IS_YMD else "OOS"
        if sym not in cache:
            cache[sym] = _load_ohlc_index(sym)
        book = cache[sym]
        if book is None:
            status = "missing_file"
        else:
            idx = book["index"].get(opened)
            if idx is None:
                status = "missing_bar"
            else:
                status = rl_pre_entry_gap_status(book["o"], book["c"], idx, GAP_BARS, GAP_PCT)["status"]
        for bucket in (split, "FULL"):
            counts[bucket][status] += 1
    out: dict[str, Any] = {"n": len(rows)}
    for bucket in buckets:
        c = counts[bucket]
        out[bucket] = {
            "n": sum(c.values()),
            "gap": int(c.get("gap", 0)),
            "allow": int(c.get("allow", 0)),
            "short": int(c.get("short", 0)),
            "bad_price": int(c.get("bad_price", 0)),
            "missing_file": int(c.get("missing_file", 0)),
            "missing_bar": int(c.get("missing_bar", 0)),
        }
    return out


def _d(b: float, a: float) -> float:
    return b - a


def _fmt_delta(v: float, nd: int = 2) -> str:
    if v != v:
        return "—"
    return f"{v:+.{nd}f}"


def pairwise_full_row(control: dict[str, Any], cand: dict[str, Any], split_key: str) -> str:
    a, b = control[split_key], cand[split_key]

    def num(key: str, nd: int = 2) -> str:
        return _fmt_delta(_d(float(b[key]), float(a[key])), nd)

    exp = _d(float(b["exp_d"]), float(a["exp_d"]))
    ppc = _d(float(b["ppc"]), float(a["ppc"]))
    return (
        "<tr>"
        f"<td>gap7 − Control</td>"
        f"<td data-sort-value=\"{_d(b['n'], a['n'])}\">{int(b['n']) - int(a['n']):+d}</td>"
        f"<td data-sort-value=\"{_d(b['wr'], a['wr'])}\">{num('wr')}</td>"
        f"<td data-sort-value=\"{_d(b['avg_pnl'], a['avg_pnl'])}\">{num('avg_pnl')}</td>"
        f"<td data-sort-value=\"{_d(b['wo_max'], a['wo_max'])}\">{num('wo_max')}</td>"
        f"<td data-sort-value=\"{_d(b['avg_win'], a['avg_win'])}\">{num('avg_win')}</td>"
        f"<td data-sort-value=\"{_d(b['avg_loss'], a['avg_loss'])}\">{num('avg_loss')}</td>"
        f"<td data-sort-value=\"{_d(b['pf'], a['pf'])}\">{num('pf', 3)}</td>"
        f"<td data-sort-value=\"{_d(b['ann_ror'], a['ann_ror'])}\">{num('ann_ror')}</td>"
        f"<td data-sort-value=\"{_d(b['max_dd'], a['max_dd'])}\">{num('max_dd')}</td>"
        f"<td data-sort-value=\"{_d(b['calmar'], a['calmar'])}\">{num('calmar')}</td>"
        f"<td data-sort-value=\"{_d(b['sharpe'], a['sharpe'])}\">{num('sharpe')}</td>"
        f"<td data-sort-value=\"{exp}\">{format_money_delta(exp)}</td>"
        f"<td data-sort-value=\"{_d(b['avg_days'], a['avg_days'])}\">{num('avg_days')}</td>"
        f"<td data-sort-value=\"{ppc}\">{format_money_delta(ppc)}</td>"
        f"<td data-sort-value=\"{_d(b['lose_streak'], a['lose_streak'])}\">{int(b['lose_streak']) - int(a['lose_streak']):+d}</td>"
        f"<td data-sort-value=\"{_d(b['tpy'], a['tpy'])}\">{num('tpy')}</td>"
        "</tr>"
    )


def _exit_mix_line(trades: list[dict[str, Any]]) -> str:
    c = Counter(str(t.get("exit") or "?").strip().upper() for t in trades)
    parts = [f"{k}={v}" for k, v in c.most_common(8)]
    return ", ".join(parts)


def _arm_verdict(verdicts: dict[str, dict[str, tuple[str, str]]]) -> str:
    vis, nis = verdicts[CANDIDATE_ID]["is"]
    voos, noos = verdicts[CANDIDATE_ID]["oos"]
    if vis == "DISMISS":
        return f"**`gap7` DISMISS** IS `{vis}` ({nis}); OOS `{voos}` ({noos}). Do not adopt. OOS was not used to set the 7% bar."
    if vis in ("KEEP", "LEAN KEEP"):
        return (
            f"**`gap7` {vis}** on IS ({nis}). OOS `{voos}` ({noos}) is report-only — do not retune the 7% threshold. "
            "Research-only, not gold, not DailyRun."
        )
    return f"**`gap7` HOLD** IS `{vis}` ({nis}); OOS `{voos}` ({noos}). Do not adopt from this stamp. OOS was not used to set the 7% bar."


def write_closed_html(closed_csv: Path, out_html: Path, *, title: str, arm_id: str, note: str) -> Path:
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
    body = "".join(
        "<tr>" + "".join(f"<td>{html_mod.escape(str(r.get(c, '')))}</td>" for c in cols) + "</tr>"
        for r in rows
    )
    css = SORTABLE_TH_CSS.replace(
        "th.sortable-th:hover{background:#e8e4d8}",
        "th.sortable-th:hover{background:#2a3545}",
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
.callout pre{{white-space:pre-wrap;font-family:ui-monospace,Consolas,monospace;font-size:.82rem;margin:.4rem 0 0}}
main{{max-width:1600px;margin:0 auto;padding:0 1rem 2.5rem}}
section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem 1rem;margin:1rem 0}}
.table-wrap{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:.72rem;min-width:900px}}
th,td{{border-bottom:1px solid var(--line);padding:.3rem .35rem;text-align:right;white-space:nowrap}}
th:first-child,td:first-child{{text-align:left}}
{css}
</style>
</head>
<body>
<header>
<h1>{html_mod.escape(title)}</h1>
<p class="muted">Stamp <code>rl_pre_entry_gap7_ab_{STAMP}</code>. Arm <code>{html_mod.escape(arm_id)}</code>.
Source <code>{html_mod.escape(closed_csv.name)}</code>. N={len(rows)}. Click column headers to sort.</p>
</header>
<main>
<div class="callout">
<strong>What you asked</strong>
<pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>
<p><strong>In plain English:</strong> {html_mod.escape(LAYMAN_TRANSLATION.strip())}</p>
</div>
<section>
<h2 style="color:var(--accent);font-size:1.05rem;margin:.2rem 0 .5rem">Closed trades — {html_mod.escape(arm_id)}</h2>
<p class="muted">{note}</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{th}</tr></thead>
<tbody>{body}</tbody></table></div>
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
    rejected: dict[str, Any],
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
    for split_key, split_title in (
        ("m_is", "IS (2010–2023)"),
        ("m_oos", "OOS (2024–present, report-only)"),
        ("m_full", "FULL"),
    ):
        body = "".join(compare_row(p, split_key, baseline, "", CONTROL_ID) for p in packed)
        sections.append(
            f"<section><h2>{html_mod.escape(split_title)}</h2>"
            f'<p class="muted">Click column headers to sort. Profit per capital day is PPCD. '
            f"In-sample (IS) is entries before 2024-01-01. Out-of-sample (OOS) is entries on or after that date.</p>"
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{th_std}</tr></thead>'
            f"<tbody>{body}</tbody></table></div></section>"
        )

    pw_th = "".join(
        sortable_th(a, b)
        for a, b in (
            ("Pair", "text"),
            ("Δ Trades", "num"),
            ("Δ WR%", "num"),
            ("Δ Avg P&L%", "num"),
            ("Δ Avg P&L% w/o max", "num"),
            ("Δ Avg Winner%", "num"),
            ("Δ Avg Loser%", "num"),
            ("Δ Profit Factor", "num"),
            ("Δ Ann ROR%", "num"),
            ("Δ Max DD%", "num"),
            ("Δ Calmar", "num"),
            ("Δ Sharpe", "num"),
            ("Δ Expectancy $", "num"),
            ("Δ Avg Days", "num"),
            ("Δ PPCD", "num"),
            ("Δ Losing Streak", "num"),
            ("Δ Trades/Year", "num"),
        )
    )
    pw_sections = []
    for split_key, split_title in (
        ("m_is", "IS"),
        ("m_oos", "OOS"),
        ("m_full", "FULL"),
    ):
        row = pairwise_full_row(by_id[CONTROL_ID], by_id[CANDIDATE_ID], split_key)
        pw_sections.append(
            f"<section><h2>Pairwise deltas — {split_title} (gap7 − Control)</h2>"
            f'<p class="muted">Positive Δ Avg P&amp;L% means the gap filter made the average trade larger. '
            f"Positive Δ Max DD% means the drawdown got worse. Click headers to sort.</p>"
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{pw_th}</tr></thead>'
            f"<tbody>{row}</tbody></table></div></section>"
        )

    rej_th = "".join(
        sortable_th(a, b)
        for a, b in (
            ("Split", "text"),
            ("Control trades", "num"),
            ("Rejected by 7% gap", "num"),
            ("Allowed", "num"),
            ("Short history", "num"),
            ("Bad price", "num"),
            ("Missing file", "num"),
            ("Missing bar", "num"),
        )
    )
    rej_rows = []
    for bucket in ("IS", "OOS", "FULL"):
        r = rejected[bucket]
        rej_rows.append(
            "<tr>"
            f"<td>{bucket}</td>"
            f"<td>{r['n']}</td>"
            f"<td>{r['gap']}</td>"
            f"<td>{r['allow']}</td>"
            f"<td>{r['short']}</td>"
            f"<td>{r['bad_price']}</td>"
            f"<td>{r['missing_file']}</td>"
            f"<td>{r['missing_bar']}</td>"
            "</tr>"
        )
    rej_sec = (
        "<section><h2>Control trades rejected by the 7% gap rule</h2>"
        "<p class=\"muted\">Counted on the frozen Control closed trades themselves, one entry at a time. "
        "This is not candidate trade count minus control trade count. A rejected entry can free the name "
        "for a later buy, so the book-size change can differ from this count. "
        "Short history means fewer than 20 completed bars existed before the entry; those are not in the 7% column. "
        "Click headers to sort.</p>"
        f'<div class="table-wrap"><table class="sortable"><thead><tr>{rej_th}</tr></thead>'
        f"<tbody>{''.join(rej_rows)}</tbody></table></div></section>"
    )

    n_univ = len(_full_univ_symbols())
    subtitle = (
        f"Stamp <code>rl_pre_entry_gap7_ab_{STAMP}</code>. "
        f"Control reused from pct20_d60 stamp 260905205015 ({rejected['n']} closed trades). "
        f"Candidate adds <code>rl_pre_entry_gap_bars={GAP_BARS}</code> and "
        f"<code>rl_pre_entry_gap_pct={GAP_PCT}</code> only. "
        f"Current price-file folder has {n_univ} names (the frozen control run logged 1113 on 2026-09-05). "
        "Research-only. Not gold. Not DailyRun."
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL pre-entry 7% gap A/B — {STAMP}</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; --accent:#5b9fd4; --ctrl:#243044; }}
*{{box-sizing:border-box}}
body{{margin:0;font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header{{padding:1.25rem 1rem 0.5rem;max-width:1600px;margin:0 auto}}
h1{{font-size:1.35rem;margin:0 0 .35rem}}
h2{{font-size:1.05rem;margin:1.25rem 0 .4rem;color:var(--accent)}}
.muted{{color:var(--muted);font-size:.92rem}}
.callout{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem;margin:.75rem 0}}
.req pre{{white-space:pre-wrap;font-family:ui-monospace,Consolas,monospace;font-size:.82rem;margin:.4rem 0 0;color:var(--text)}}
.req .layman{{margin:.55rem 0 0;font-size:.95rem}}
main{{max-width:1600px;margin:0 auto;padding:0 1rem 2.5rem}}
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
<h1>RL pre-entry 20-bar 7% absolute-gap filter vs frozen Control</h1>
<p class="muted">{subtitle}</p>
</header>
<main>
<div class="callout req">
<strong>What you asked</strong>
<pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>
<p class="layman"><strong>In plain English:</strong> {html_mod.escape(LAYMAN_TRANSLATION.strip())}</p>
<p class="layman"><strong>Only change:</strong> {html_mod.escape(ONLY_CHANGE)}</p>
</div>
<div class="callout">
<strong>Paul note:</strong> {html_mod.escape(paul_note)}
<p>{_arm_verdict(verdicts)}</p>
<p class="muted">Adoption uses in-sample (IS, entries before 2024-01-01) only. Out-of-sample (OOS, 2024–present) is report-only and was not used to choose 7.0% or 20 bars. Research-only. Simple Moving Average (SMA) envelope target stays off. Exit stays +20% then 60 trading days. Profit per capital day (PPCD). Maximum drawdown (Max DD). Win rate (WR).</p>
</div>
{rej_sec}
{"".join(sections)}
{"".join(pw_sections)}
<section>
<h2>Exit mix (full book)</h2>
<p class="muted">Control: {_exit_mix_line(by_id[CONTROL_ID].get("trades") or [])}</p>
<p class="muted">gap7: {_exit_mix_line(by_id[CANDIDATE_ID].get("trades") or [])}</p>
</section>
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    out = OUT_DIR / "compare.html"
    out.write_text(html, encoding="utf-8")
    return out


def write_docs(
    packed: list[dict[str, Any]],
    verdicts: dict[str, dict[str, tuple[str, str]]],
    rejected: dict[str, Any],
    html_path: Path,
) -> None:
    by_id = {p["arm"]["id"]: p for p in packed}

    def split_line(aid: str, key: str) -> str:
        m = by_id[aid][key]
        return (
            f"N={m['n']} WR={m['wr']:.2f}% Avg={m['avg_pnl']:.2f}% WO_MAX={m['wo_max']:.2f}% "
            f"AvgWin={m['avg_win']:.2f}% AvgLoss={m['avg_loss']:.2f}% PF={m['pf']:.3f} "
            f"AnnROR={fmt_n(m['ann_ror'], 2)} MaxDD={fmt_n(m['max_dd'], 2)} "
            f"Calmar={fmt_n(m['calmar'], 2)} Sharpe={fmt_n(m['sharpe'], 2)} "
            f"Expect$={m['exp_d']:.2f} AvgDays={m['avg_days']:.2f} PPCD={fmt_n(m['ppc'], 4)} "
            f"LoseStreak={m['lose_streak']} TPY={fmt_n(m['tpy'], 2)}"
        )

    lines = [
        f"# BASELINE — `rl_pre_entry_gap7_ab_{STAMP}`",
        "",
        "**Status:** RESEARCH only. One entry knob. Not gold. Not DailyRun.",
        "**Control:** frozen pct20_d60 closed stamp `260905205015` (reused, not re-run).",
        f"**Candidate:** same command plus `rl_pre_entry_gap_bars={GAP_BARS}` and `rl_pre_entry_gap_pct={GAP_PCT}`.",
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
        "## Only changed variable",
        "",
        ONLY_CHANGE,
        "",
        "If there are not 20 completed bars with a prior close before the entry date, the buy is not allowed. "
        "That is the same qualification (you can pass only when the largest of those 20 gaps is under 7%), not a second knob. "
        "Those rare cases are listed separately from the 7% rejections below.",
        "",
        f"Current CSV folder name count: {len(_full_univ_symbols())}. The frozen control log said 1113 symbols on 2026-09-05. "
        "The candidate uses today's price files with the same engine flags. Any names added since that snapshot are a data difference, not a second strategy knob.",
        "",
        "## Freeze",
        "",
        "| Knob | Control | gap7 |",
        "|------|---------|------|",
        "| `rl_too_high` | 1.13 | 1.13 |",
        "| `rl_dip_pct` | 1.055 | 1.055 |",
        "| `rl_expansion` | 1.163 | 1.163 |",
        "| `rl_stop_pct` | 0.934 | 0.934 |",
        "| `rl_sma_target_off` | 1 | 1 |",
        "| `rl_exit_percent` / `rl_exit_days` | 0.20 / 60 trading bars | 0.20 / 60 trading bars |",
        "| volume floors | 10000 avg / 5000 trigger | same |",
        "| cash | $47,500 | $47,500 |",
        "| pre-entry gap bars / pct | off (0 / 0) | 20 / 7.0 |",
        f"| entry end (snapshot align) | data ended 2026-09-04 | `{CONTROL_DATA_END}` |",
        "",
        "IS = entry date before 2024-01-01. OOS is report-only. No OOS retune of the 7% threshold.",
        "",
        "## Control trades rejected by the 7% rule",
        "",
        "| Split | Control trades | Rejected by 7% gap | Allowed | Short history |",
        "|-------|----------------|--------------------|---------|---------------|",
    ]
    for bucket in ("IS", "OOS", "FULL"):
        r = rejected[bucket]
        lines.append(
            f"| {bucket} | {r['n']} | {r['gap']} | {r['allow']} | {r['short']} |"
        )
    lines.extend(
        [
            "",
            "## Results (gap7 − Control is the pairwise sign)",
            "",
            f"- control IS: {split_line(CONTROL_ID, 'm_is')}",
            f"- gap7 IS: {split_line(CANDIDATE_ID, 'm_is')}",
            f"- control OOS: {split_line(CONTROL_ID, 'm_oos')}",
            f"- gap7 OOS: {split_line(CANDIDATE_ID, 'm_oos')}",
            f"- control FULL: {split_line(CONTROL_ID, 'm_full')}",
            f"- gap7 FULL: {split_line(CANDIDATE_ID, 'm_full')}",
            "",
            "## Verdict",
            "",
            _arm_verdict(verdicts),
            "",
            f"Compare: `{html_path.as_posix()}`",
            "",
        ]
    )
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")


def _notify(paths: list[Path]) -> None:
    helper = ROOT / "tools" / "ntfy_job_done.py"
    cmd = [sys.executable, str(helper), "-t", "RL 7% gap A/B"]
    for p in paths:
        cmd.extend(["--path", str(p)])
    subprocess.run(cmd, cwd=str(ROOT), check=False)


def summarize(packed: list[dict[str, Any]]) -> None:
    by_id = {p["arm"]["id"]: p for p in packed}
    control = by_id[CONTROL_ID]
    closed = control.get("closed")
    if not closed:
        raise RuntimeError("control closed path missing")
    rejected = scan_control_rejections(Path(closed))
    verdicts = {
        CANDIDATE_ID: {
            "is": verdict_vs_control(by_id[CANDIDATE_ID], control, "m_is"),
            "oos": verdict_vs_control(by_id[CANDIDATE_ID], control, "m_oos"),
        }
    }
    vis = verdicts[CANDIDATE_ID]["is"][0]
    paul_note = (
        f"gap7 IS={vis}. The only strategy change is the 20-bar absolute opening-gap filter at 7%. "
        "IS is the adoption basis. OOS is report-only — do not retune the threshold. Research-only."
    )
    closed_dir = OUT_DIR / "closed"
    closed_dir.mkdir(parents=True, exist_ok=True)
    for p in packed:
        src = p.get("closed")
        if src and Path(src).is_file():
            shutil.copy2(src, closed_dir / f"{p['arm']['id']}_{Path(src).name}")
    write_metrics_csv(packed, "", OUT_DIR / "metrics_all.csv")
    html_path = write_compare_html(packed, verdicts, rejected, paul_note=paul_note)
    closed_htmls: list[Path] = []
    notes = {
        CONTROL_ID: (
            "Frozen Control. Simple Moving Average (SMA) envelope target off. "
            "Sell after the trade is up 20%, then 60 trading days, or sooner at the stop."
        ),
        CANDIDATE_ID: (
            "Same Control rules, plus the pre-entry filter: skip the buy if any of the 20 "
            "completed days before entry opened 7% or more away from the prior close. "
            "Buys end 2026-09-04 to match the frozen Control snapshot."
        ),
    }
    for p in packed:
        src = p.get("closed")
        if not src or not Path(src).is_file():
            continue
        aid = p["arm"]["id"]
        dest = closed_dir / f"{aid}_closed.html"
        closed_htmls.append(
            write_closed_html(
                Path(src),
                dest,
                title=f"RL Closed — {aid}",
                arm_id=aid,
                note=notes.get(aid, ""),
            )
        )
    write_docs(packed, verdicts, rejected, html_path)
    _notify([html_path, *closed_htmls])
    print(f"[{TAG}] compare {html_path}", flush=True)
    for bucket in ("IS", "OOS", "FULL"):
        r = rejected[bucket]
        print(
            f"[{TAG}] rejected {bucket}: gap={r['gap']} allow={r['allow']} "
            f"short={r['short']} n={r['n']}",
            flush=True,
        )
    print(f"[{TAG}] {_arm_verdict(verdicts)}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--summarize-only", action="store_true")
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    arms = _arm_defs()
    py = _resolve_python()
    runs: list[dict[str, Any]] = []
    if args.summarize_only:
        runs = [_load_arm_from_disk(a) for a in arms]
    else:
        for arm in arms:
            print(f"[{TAG}] start {arm['id']}", flush=True)
            runs.append(run_live(py, arm, args.workers, args.skip_existing))
    if not all(r.get("ok") for r in runs):
        for r in runs:
            print(f"[{TAG}] FAIL {r['arm']['id']} ok={r.get('ok')} exit={r.get('exit_code')}", flush=True)
        return 1
    packed = [pack_result(r) for r in runs]
    summarize(packed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
