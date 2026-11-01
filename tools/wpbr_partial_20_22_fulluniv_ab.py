"""WPBR full-universe exit A/B. One change: the exit.

Control is the 2026-09-28 full-universe book: stop 0.91 (9% under the
trigger-day low) and a 100% sale at +22% (target_pct 1.22).

Partial 20 / Partial 22 keep that stop and sell 80% at +20% or +22%.
The leftover stop moves to the entry price. The leftover target is +40%.

Research only. Out of sample is report-only. Not gold. Not DailyRun.
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
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

from _gen_too_high_diff import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from compare_format import calmar_ratio, format_money, format_money_delta, overlay_ann_ror_max_dd  # noqa: E402

STAMP = "20260929"
IS_CUT = "20240101"
OUT_DIR = ROOT / "drive" / "paul_experiments" / f"wpbr_partial_20_22_fulluniv_ab_{STAMP}"
RUNS_DIR = ROOT / "tmp_wpbr_partial_ab_20260929"
CONTROL_DIR = ROOT / "tmp_wpbr_stop_ab_20260928" / "stop09"
TAG = f"wpbr_partial_20_22_fulluniv_ab_{STAMP}"
CASH = 47500.0
ACCOUNT = 500_000.0

# id, label, scale gain (0 = full exit at target_pct). Stop stays 0.91. Runner is +40%.
ARMS: list[tuple[str, str, float]] = [
    ("control", "Control", 0.0),
    ("p20", "Partial 20", 0.20),
    ("p22", "Partial 22", 0.22),
]

COMMON: dict[str, str] = {
    "wpbr_zones": "true",
    "brt_zones": "false",
    "yh_zones": "false",
    "vec_zones": "false",
    "band_pct": "0.015",
    "strong_pre_pivot_bars": "3",
    "strong_pre_pivot_pct": "0.10",
    "strong_post_pivot_bars": "3",
    "strong_post_pivot_pct": "0.10",
    "strong_pivot_mode": "either",
    "wpbr_breakout_confirmation": "0.03",
    "wpbr_max_days_after_retest": "2",
    "wpbr_second_chance_after_win": "true",
    "growth_filter_enabled": "false",
    "min_spy_compare_1y_at_trigger": "-1000",
    "ind_score_weights_path": "ind_score_weights_260609152353.json",
    "too_high_multiplier": "0",
    "target_pct": "1.22",
    "stop_pct": "0.91",
    "stop_loss_based": "trigger_low",
    "stop_pct_is_multiplier": "true",
    "use_indicators": "true",
    "max_market_cap": "0",
    "min_market_cap": "0",
    "sheet_no_entry_same_bar_after_exit": "false",
}

REQUEST_PROMPT = """Can you run an AB test on WPBR using the entire universe
Control: −9% stop, 100% exit at +22%
Partial 20: −9% stop → at +20% sell 80%, remaining 20% to BE, runner target +40%
Partial 22: −9% stop → at +22% sell 80%, remaining 20% to BE, runner target +40%"""

LAYMAN = (
    "We kept the Pivot Break and Retest (WPBR) buy rules the same and only changed how a winner is sold. "
    "The stop stays 9% under the low of the trigger day (the day before the buy). "
    "Control sells the whole position at +22% from the buy. "
    "Partial 20 sells 80% at +20%, moves the leftover stop to the buy price (breakeven), and tries to sell that leftover 20% at +40%. "
    "Partial 22 does the same sale, but the 80% comes off at +22% instead of +20%. The leftover still aims at +40%. "
    "If a day trades both the leftover stop and the +40% target, the stop is taken first. "
    "In-sample is entries before 2024. Out of sample is 2024 onward and is for reading only. "
    "This is a research test, not a live-system change."
)


def _notify(py: str, paths: list[Path], message: str) -> None:
    cmd = [py, str(ROOT / "tools" / "ntfy_job_done.py"), "-t", "WPBR partial 20/22"]
    for p in paths:
        cmd.extend(["--path", str(p)])
    cmd.extend(["-m", message])
    subprocess.run(cmd, cwd=str(ROOT), check=False)


def _latest(folder: Path, needle: str) -> Path:
    hits = sorted(folder.glob(f"WPBR_{needle}_*.csv"), key=lambda p: p.stat().st_mtime)
    if not hits:
        raise FileNotFoundError(f"no WPBR_{needle} in {folder}")
    return hits[-1]


def run_fresh(py: str, arm_id: str, gain: float, workers: int, symbols: str = "") -> Path:
    out = RUNS_DIR / arm_id
    if out.exists():
        for attempt in range(8):
            try:
                shutil.rmtree(out)
                break
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(2)
    out.mkdir(parents=True, exist_ok=True)
    cmd = [
        py, str(ROOT / "stock_analysis" / "rocket_tbn.py"), str(ROOT / "data" / "newdata" / "data"),
        "-o", str(out), "-w", str(workers), "--aggressive", "--use-duckdb", "--no-regression",
    ]
    if symbols:
        cmd.extend(["-s", symbols])
    knobs = dict(COMMON)
    if gain > 0:
        knobs["brt_scale_gain"] = f"{gain:.2f}"
        knobs["brt_scale_sell_frac"] = "0.80"
        knobs["brt_scale_stop_gain"] = "0"
        knobs["brt_scale_runner_gain"] = "0.40"
    for key, val in knobs.items():
        cmd.extend(["-v", f"{key}={val}"])
    log_path = RUNS_DIR / f"{arm_id}.log"
    print(f"[{TAG}] start {arm_id} scale_gain={gain:.2f} log={log_path}", flush=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.run(cmd, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        raise RuntimeError(f"{arm_id} exited {proc.returncode}. See {log_path}")
    print(f"[{TAG}] done {arm_id}", flush=True)
    return out


def _f(raw: Any, default: float = float("nan")) -> float:
    if raw is None:
        return default
    s = str(raw).strip().replace(",", "").replace("%", "").replace("$", "")
    if not s or s.lower() in {"nan", "none", "null"}:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _load(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = str(raw.get("DATE_OPENED") or "").strip()
            if len(opened) < 8:
                continue
            opened = opened[:8]
            closed = str(raw.get("DATE_CLOSED") or "").strip()
            closed = closed[:8] if len(closed) >= 8 else ""
            sold = _f(raw.get("SCALE_SOLD_FRAC"), 0.0)
            scale_date = str(raw.get("SCALE_DATE") or "").strip()[:8]
            full_days = _f(raw.get("DAYS_HELD"), 0.0)
            wdays = full_days
            if sold > 0 and len(scale_date) == 8 and len(opened) == 8 and len(closed) == 8:
                try:
                    od = datetime.strptime(opened, "%Y%m%d")
                    cd = datetime.strptime(closed, "%Y%m%d")
                    sd = datetime.strptime(scale_date, "%Y%m%d")
                    full = (cd - od).days
                    partial = max(0, (sd - od).days)
                    wdays = sold * partial + (1.0 - sold) * full
                except ValueError:
                    wdays = full_days
            rows.append(
                {
                    "opened": opened,
                    "closed": closed,
                    "pnl": _f(raw.get("PNL_PCT")),
                    "days": full_days,
                    "wdays": wdays if math.isfinite(wdays) else full_days,
                    "pnl_d": _f(raw.get("PNL_DOLLARS"), 0.0),
                    "exit": str(raw.get("EXIT_TYPE") or "").strip().upper(),
                    "scaled": sold > 0 or str(raw.get("EXIT_TYPE") or "").upper().startswith("SCALE+"),
                }
            )
    return rows


def _split(trades: list[dict[str, Any]], which: str) -> list[dict[str, Any]]:
    if which == "IS":
        return [t for t in trades if t["opened"] < IS_CUT]
    if which == "OOS":
        return [t for t in trades if t["opened"] >= IS_CUT]
    return list(trades)


def _metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(trades)
    empty = {
        "n": 0, "wins": 0, "losses": 0, "wr": float("nan"),
        "avg_win": float("nan"), "avg_loss": float("nan"), "rr": float("nan"),
        "avg_pnl": float("nan"), "wo_max": float("nan"), "pf": float("nan"),
        "expect_pct": float("nan"), "expect_d": float("nan"),
        "ann_ror": float("nan"), "max_dd": float("nan"), "calmar": float("nan"),
        "sharpe": float("nan"), "avg_days": float("nan"), "cap_days": 0.0,
        "tpy": float("nan"), "exits": {}, "scaled": 0, "scale_pct": float("nan"),
    }
    if n == 0:
        return empty
    pnls = [t["pnl"] for t in trades if math.isfinite(t["pnl"])]
    n = len(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    avg_win = sum(wins) / len(wins) if wins else float("nan")
    avg_loss = sum(losses) / len(losses) if losses else float("nan")
    mx = max(pnls) if pnls else float("nan")
    wo = (sum(pnls) - mx) / (n - 1) if n >= 2 and math.isfinite(mx) else float("nan")
    days = [t["days"] for t in trades if math.isfinite(t["days"]) and t["days"] > 0]
    parsed = []
    for t in trades:
        try:
            opened_d = datetime.strptime(t["opened"], "%Y%m%d").date()
            closed_d = datetime.strptime(t["closed"], "%Y%m%d").date() if t["closed"] else opened_d
        except ValueError:
            continue
        parsed.append({**t, "opened": opened_d, "closed": closed_d, "days": t["wdays"]})
    cap = overlay_ann_ror_max_dd(parsed, cash=CASH, initial_account=ACCOUNT)
    opens = [t["opened"] for t in parsed]
    closes = [t["closed"] for t in parsed]
    span = ((max(closes) - min(opens)).days / 365.25) if opens else 0.0
    scaled = sum(1 for t in trades if t["scaled"])
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "wr": (100.0 * len(wins) / n) if n else float("nan"),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "rr": (avg_win / abs(avg_loss)) if losses and math.isfinite(avg_win) and avg_loss != 0 else float("nan"),
        "avg_pnl": (sum(pnls) / n) if n else float("nan"),
        "wo_max": wo,
        "pf": (gp / gl) if gl > 0 else float("nan"),
        "expect_pct": (sum(pnls) / n) if n else float("nan"),
        "expect_d": (sum(t["pnl_d"] for t in trades) / n) if n else float("nan"),
        "ann_ror": cap.get("ann_ror", float("nan")),
        "max_dd": cap.get("max_dd", float("nan")),
        "calmar": (
            float(c) if (c := (calmar_ratio(cap.get("ann_ror"), cap.get("max_dd")) if calmar_ratio else cap.get("calmar"))) is not None
            and isinstance(c, (int, float)) and math.isfinite(float(c))
            else float("nan")
        ),
        "sharpe": cap.get("sharpe", float("nan")),
        "avg_days": (sum(days) / len(days)) if days else float("nan"),
        "cap_days": float(cap.get("capital_days") or 0.0),
        "tpy": (n / span) if span > 0.25 else float("nan"),
        "exits": dict(Counter(t["exit"] or "?" for t in trades)),
        "scaled": scaled,
        "scale_pct": (100.0 * scaled / n) if n else float("nan"),
    }


def _summary_means(path: Path) -> dict[str, float]:
    paul, fit, robust, wo, pf = [], [], [], [], []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if _f(row.get("TRADES"), 0) <= 0:
                continue
            for bucket, key in (
                (paul, "PAUL_SCORE"),
                (fit, "FIT_SCORE"),
                (robust, "FIT_SCORE_ROBUST"),
                (wo, "AVG_PNL_PCT_WO_MAX"),
                (pf, "PROFIT_FACTOR"),
            ):
                v = _f(row.get(key))
                if math.isfinite(v):
                    bucket.append(v)
    def mean(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else float("nan")
    return {
        "paul": mean(paul),
        "fit": mean(fit),
        "robust": mean(robust),
        "sym_wo": mean(wo),
        "sym_pf": mean(pf),
        "symbols": float(len(paul)),
    }


def _fmt(v: float, nd: int = 2, suffix: str = "") -> str:
    if v is None or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
        return "—"
    return f"{float(v):.{nd}f}{suffix}"


def _delta(v: float, base: float, nd: int = 2, suffix: str = "") -> str:
    if not (math.isfinite(v) and math.isfinite(base)):
        return "—"
    d = v - base
    sign = "+" if d > 0 else ""
    return f"{sign}{d:.{nd}f}{suffix}"


METRIC_ROWS: list[tuple[str, str, int, str, bool]] = [
    ("n", "Trades", 0, "", False),
    ("wins", "Wins", 0, "", False),
    ("losses", "Losses", 0, "", False),
    ("wr", "Win %", 1, "%", True),
    ("avg_win", "Avg win %", 2, "%", True),
    ("avg_loss", "Avg loss %", 2, "%", True),
    ("rr", "Realized reward/risk", 2, "", True),
    ("avg_pnl", "Avg P&L %", 2, "%", True),
    ("wo_max", "Avg P&L % w/o max", 2, "%", True),
    ("pf", "Profit factor", 2, "", True),
    ("expect_pct", "Expectancy %", 2, "%", True),
    ("expect_d", "Expectancy $", 2, "", True),
    ("ann_ror", "Ann ROR %", 2, "%", True),
    ("max_dd", "Max DD %", 2, "%", False),
    ("calmar", "Calmar", 2, "", True),
    ("sharpe", "Sharpe", 2, "", True),
    ("avg_days", "Avg calendar days", 1, "", False),
    ("cap_days", "Capital days (share-weighted)", 0, "", False),
    ("tpy", "Trades / year", 2, "", True),
    ("scaled", "Trades that scaled", 0, "", False),
    ("scale_pct", "Scale rate", 1, "%", False),
]


def _arm_freeze_html(books: list[dict[str, Any]]) -> list[str]:
    by_id = {b["id"] for b in books}
    lines = [
        "<li>Partial 20: brt_scale_gain=0.20, sell 80%, leftover stop at the entry, leftover target entry × 1.40.</li>"
        if "p20" in by_id else "",
        "<li>Partial 22: brt_scale_gain=0.22, same leftover rules.</li>" if "p22" in by_id else "",
        "<li>Partial 22 was not run on this pass.</li>" if "p22" not in by_id else "",
    ]
    return [line for line in lines if line]


def _arm_freeze_md(books: list[dict[str, Any]]) -> list[str]:
    by_id = {b["id"] for b in books}
    lines = []
    if "p20" in by_id:
        lines.append(
            "- Partial 20: `brt_scale_gain=0.20`, `brt_scale_sell_frac=0.80`, `brt_scale_stop_gain=0`, `brt_scale_runner_gain=0.40`."
        )
    if "p22" in by_id:
        lines.append("- Partial 22: `brt_scale_gain=0.22` and the same leftover rules.")
    else:
        lines.append("- Partial 22 was not run on this pass.")
    return lines


def _verdict(books: list[dict[str, Any]]) -> str:
    ctrl = next(b for b in books if b["id"] == "control")
    notes = []
    for b in books:
        if b["id"] == "control":
            continue
        i, c = b["slices"]["IS"], ctrl["slices"]["IS"]
        o = b["slices"]["OOS"]
        co = ctrl["slices"]["OOS"]
        better_is = (
            math.isfinite(i["avg_pnl"]) and math.isfinite(c["avg_pnl"]) and i["avg_pnl"] > c["avg_pnl"] + 0.05
            and math.isfinite(i["pf"]) and math.isfinite(c["pf"]) and i["pf"] >= c["pf"] - 0.02
        )
        worse_is = (
            math.isfinite(i["avg_pnl"]) and math.isfinite(c["avg_pnl"]) and i["avg_pnl"] < c["avg_pnl"] - 0.05
        )
        oos_soft = (
            math.isfinite(o["avg_pnl"]) and math.isfinite(co["avg_pnl"]) and o["avg_pnl"] < co["avg_pnl"] - 0.15
        )
        n_drop = c["n"] > 0 and i["n"] < 0.85 * c["n"]
        if better_is and oos_soft:
            call = "HOLD. In-sample quality is better, and out of sample is softer, so this is not a retune."
        elif better_is and n_drop:
            call = "HOLD. In-sample average is higher, but the trade count fell."
        elif better_is:
            call = "LEAN KEEP as research only. In-sample win quality improved and out of sample did not soften on average P&L. Not gold. Not a live change."
        elif worse_is:
            call = "DISMISS. In-sample average P&L is worse than selling everything at +22%."
        else:
            call = "HOLD. In-sample average P&L is close to control."
        notes.append(f"{b['label']}: {call}")
    return " ".join(notes)


def write_html(books: list[dict[str, Any]], means: dict[str, dict[str, float]]) -> Path:
    esc = html_mod.escape
    labels = [b["label"] for b in books]

    def num_cells(slice_name: str, key: str, nd: int, suffix: str) -> str:
        ctrl = books[0]["slices"][slice_name][key]
        out = []
        for i, b in enumerate(books):
            v = b["slices"][slice_name][key]
            if key == "expect_d":
                text = format_money(v)
                dtext = format_money_delta(v - ctrl) if math.isfinite(v) and math.isfinite(ctrl) else "—"
            else:
                text = _fmt(v, nd, suffix)
                dtext = _delta(v, ctrl, nd, suffix)
            out.append(f"<td class=\"num\">{esc(text)}</td>")
            if i:
                out.append(f"<td class=\"num\">{esc(dtext)}</td>")
        return "".join(out)

    head = "".join(
        sortable_th(lab, "text") + (sortable_th(f"Δ {lab}", "num") if i else "")
        for i, lab in enumerate(labels)
    )
    body_parts = []
    for slice_name in ("IS", "OOS", "FULL"):
        body_parts.append(f"<tr class=\"total-row\"><td colspan=\"{1 + len(labels) + (len(labels) - 1)}\">{slice_name}</td></tr>")
        for key, label, nd, suffix, _higher in METRIC_ROWS:
            body_parts.append(
                f"<tr><td>{esc(label)}</td>{num_cells(slice_name, key, nd, suffix)}</tr>"
            )

    exit_keys = sorted({k for b in books for k in b["slices"]["FULL"]["exits"]})
    exit_head = sortable_th("Exit", "text") + "".join(sortable_th(b["label"], "num") for b in books)
    exit_rows = []
    for k in exit_keys:
        cells = "".join(
            f"<td class=\"num\">{b['slices']['FULL']['exits'].get(k, 0)}</td>" for b in books
        )
        exit_rows.append(f"<tr><td>{esc(k)}</td>{cells}</tr>")

    fit_keys = [
        ("paul", "Mean Paul score", 2),
        ("fit", "Mean FIT score", 2),
        ("robust", "Mean robust FIT", 2),
        ("sym_wo", "Mean symbol Avg P&L % w/o max", 2),
        ("sym_pf", "Mean symbol profit factor", 2),
        ("symbols", "Symbols with trades", 0),
    ]
    fit_rows = []
    ctrl_m = means.get("control", {})
    for key, label, nd in fit_keys:
        cells = []
        base = ctrl_m.get(key, float("nan"))
        for i, b in enumerate(books):
            v = means.get(b["id"], {}).get(key, float("nan"))
            cells.append(f"<td class=\"num\">{esc(_fmt(v, nd))}</td>")
            if i:
                cells.append(f"<td class=\"num\">{esc(_delta(v, base, nd))}</td>")
        fit_rows.append(f"<tr><td>{esc(label)}</td>{''.join(cells)}</tr>")

    verdict = _verdict(books)
    page = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>WPBR partial 20 / 22</title>
<style>
body {{ font-family: Georgia, serif; margin: 24px; color: #1a1a1a; max-width: 1200px; }}
h1 {{ font-size: 1.4rem; }}
.callout {{ background: #f6f3ea; border: 1px solid #ddd; padding: 12px 16px; margin: 12px 0 20px; }}
table.sortable {{ border-collapse: collapse; width: 100%; margin: 8px 0 24px; font-size: 0.92rem; }}
td, th {{ border-bottom: 1px solid #e4e4e4; padding: 4px 8px; text-align: left; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
tr.total-row td {{ font-weight: 700; background: #f3f3f3; }}
{SORTABLE_TH_CSS}
</style></head><body>
<h1>WPBR partial exit, full universe</h1>
<div class="callout"><strong>What you asked</strong><pre>{esc(REQUEST_PROMPT.strip())}</pre>
<strong>In plain English</strong><p>{esc(LAYMAN)}</p></div>
<p>{esc(verdict)}</p>
<p>Click column headers to sort. In-sample is an entry date before 2024-01-01. Out of sample is that date and after. Deltas are versus Control. Lower is better for Max DD and for capital days. Ann ROR, Max DD, Calmar, and Sharpe are a closed-trade overlay at $47,500 per trade and a $500,000 account. Partial capital days count the 80% only until the scale sale and the leftover until the final sale. Symbol scores are full-book averages across names.</p>
<h2>IS / OOS / full book</h2>
<table class="sortable"><thead><tr>{sortable_th("Metric", "text")}{head}</tr></thead>
<tbody>{''.join(body_parts)}</tbody></table>
<h2>Full-book exit mix</h2>
<p>SCALE+ means the 80% sale happened and the label after the plus is how the leftover finished. A leftover stop is checked before the +40% target when both trade on the same day.</p>
<table class="sortable"><thead><tr>{exit_head}</tr></thead><tbody>{''.join(exit_rows)}</tbody></table>
<h2>Symbol scores, full book</h2>
<table class="sortable"><thead><tr>{sortable_th("Score", "text")}{head}</tr></thead>
<tbody>{''.join(fit_rows)}</tbody></table>
<h2>Freeze</h2>
<ul>
<li>Universe: every name under data/newdata/data. Same entry rules as the 2026-09-28 full-universe stop test.</li>
<li>Stop: 0.91 times the trigger-day low (9% under that low) on every arm.</li>
<li>Control: sell 100% at entry × 1.22. Book reused from the 2026-09-28 −9% run. The new scale switch was off there.</li>
{''.join(_arm_freeze_html(books))}
<li>The sale is 80% of the cash position. WPBR results are cash-weighted, so this is not rounded to whole shares.</li>
<li>A later second-chance buy after a target win still depends on a target-family exit. A leftover that stops at breakeven is not a target win, so the trade count can change.</li>
<li>This is an exit test. The winner, if any, was looked at on this same history, so the choice is in-sample. Out of sample was not used to pick a knob.</li>
</ul>
{SORTABLE_TABLE_SCRIPT}
</body></html>"""
    path = OUT_DIR / "compare.html"
    path.write_text(page, encoding="utf-8")
    return path


def write_baseline(books: list[dict[str, Any]], html_path: Path) -> None:
    lines = [
        f"# WPBR partial 20 / 22 ({STAMP})",
        "",
        "## What you asked",
        "",
        REQUEST_PROMPT.strip(),
        "",
        "## In plain English",
        "",
        LAYMAN,
        "",
        "## Verdict",
        "",
        _verdict(books),
        "",
        "Research only. Not gold. Not DailyRun. Out of sample was not used to choose an exit.",
        "",
        "## Freeze",
        "",
        "- System: WPBR (Pivot Break and Retest), full `data/newdata/data` universe.",
        "- Stop on every arm: `stop_pct=0.91`, `stop_loss_based=trigger_low` (9% under the trigger-day low).",
        "- Control: `target_pct=1.22`, scale off. Reused the 2026-09-28 −9% closed book (`tmp_wpbr_stop_ab_20260928/stop09`).",
        *_arm_freeze_md(books),
        "- Entry knobs match the 2026-09-28 stop test, including second chance after a target win.",
        "- IS: entry date before 2024-01-01. OOS: on or after that date. Report only.",
        f"- Compare: `{html_path.relative_to(ROOT).as_posix()}`",
        "",
    ]
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")


def _arm_dir(arm_id: str) -> Path:
    fresh = RUNS_DIR / arm_id
    if any(fresh.glob("WPBR_Closed_*.csv")):
        return fresh
    if arm_id == "control":
        return CONTROL_DIR
    return fresh


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--symbols", default="", help="Limit a smoke run to these symbols.")
    parser.add_argument(
        "--arms",
        default="control,p20,p22",
        help="Comma-separated arm ids. Use control,p20 to skip Partial 22.",
    )
    args = parser.parse_args()
    known = {aid: (aid, label, gain) for aid, label, gain in ARMS}
    selected = [p.strip() for p in args.arms.split(",") if p.strip()]
    unknown = [aid for aid in selected if aid not in known]
    if not selected or unknown:
        raise SystemExit(f"unknown or empty --arms {args.arms!r}; choose from {', '.join(known)}")
    arms = [known[aid] for aid in selected]
    global OUT_DIR
    if args.symbols:
        OUT_DIR = ROOT / "tmp_wpbr_partial_smoke_report"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    try:
        if not args.summarize_only:
            for aid, _label, gain in arms:
                if aid == "control" and not args.symbols and CONTROL_DIR.exists() and any(CONTROL_DIR.glob("WPBR_Closed_*.csv")):
                    print(f"[{TAG}] reuse control {CONTROL_DIR}", flush=True)
                    continue
                if gain <= 0 and not args.symbols:
                    run_fresh(py, aid, 0.0, args.workers, args.symbols)
                else:
                    run_fresh(py, aid, gain, args.workers, args.symbols)
        books = []
        means: dict[str, dict[str, float]] = {}
        for aid, label, gain in arms:
            folder = _arm_dir(aid) if not args.symbols else (RUNS_DIR / aid)
            trades = _load(_latest(folder, "Closed"))
            books.append(
                {
                    "id": aid,
                    "label": label,
                    "slices": {name: _metrics(_split(trades, name)) for name in ("IS", "OOS", "FULL")},
                }
            )
            means[aid] = _summary_means(_latest(folder, "Summary"))
        write_baseline(books, OUT_DIR / "compare.html")
        html_path = write_html(books, means)
        write_baseline(books, html_path)
    except Exception as exc:
        path = OUT_DIR / "compare.html"
        path.write_text(
            "<!DOCTYPE html><html><body><h1>WPBR partial test did not finish</h1>"
            f"<p>{html_mod.escape(str(exc))}</p>"
            f"<pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>"
            f"<p>{html_mod.escape(LAYMAN)}</p></body></html>",
            encoding="utf-8",
        )
        _notify(py, [path], f"WPBR partial test failed: {exc}")
        print(f"[{TAG}] FAIL {exc}", flush=True)
        return 1
    for b in books:
        full = b["slices"]["FULL"]
        print(
            f"[{TAG}] {b['label']} FULL N={full['n']} WR={full['wr']:.1f} avg={full['avg_pnl']:.2f} "
            f"PF={full['pf']:.2f} scaled={full['scaled']}",
            flush=True,
        )
    print(f"[{TAG}] Wrote {html_path}", flush=True)
    if not args.symbols:
        _notify(
            py,
            [html_path],
            "WPBR full-universe partial test: " + ", ".join(label for _aid, label, _gain in arms) + ". Compare page.",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
