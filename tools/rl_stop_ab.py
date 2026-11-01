#!/usr/bin/env python3
"""RL stop exploration AB — house freeze, full engine reruns.

Control: signal-bar Low × rl_stop_pct=0.934 (house).
Arms: rl_stop_pct grid, dip-zone low stops, entry/SMA50/ATR anchors.

Research-only. Not gold. Not DailyRun.

Usage:
  python tools/rl_stop_ab.py
  python tools/rl_stop_ab.py --summarize-only
  python tools/rl_stop_ab.py --smoke
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import json
import math
import os
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
DATA_DIR = ROOT / "data" / "newdata" / "data"
SA = ROOT / "stock_analysis"
STAMP = datetime.now().strftime("%Y%m%d")
OUT_DIR = DRIVE / "paul_experiments" / f"rl_stop_ab_{STAMP}"
UNIV_PATH = DRIVE / "universes" / "RL_universe.csv"
PER_SYMBOL = SA / "Per_Symbol_Optimized_Settings_Approved_Latest.json"
IS_CUT = date(2024, 1, 1)
RL_CASH = 47_500.0
INIT = 500_000.0

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(DRIVE / "paul_experiments"))
from be_stop_replay_ab import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th, verdict  # noqa: E402
from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    calmar_ratio,
    filter_html_compare_columns,
    format_calmar,
    format_money,
    format_money_delta,
    overlay_ann_ror_max_dd,
)

RL_COMMON_V = [
    "rl_mode=true",
    "brt_zones=false",
    "yh_zones=false",
    "wpbr_zones=false",
    "indicator_buy=off",
    "rl_sma_qual=1",
    "ATR_LOW=off",
    "ATR_HIGH=off",
    "rl_slope_threshold=0",
    "rl_too_high=0",
    "rl_dip_pct=1.041",
    "rl_expansion=1.163",
    "rl_target_pct=1.2",
    "rl_post_target_reentry_bars=0",
]

# STOP exploration stamp — multiple stop definitions; label selection bias in BASELINE.
ARMS: list[dict[str, Any]] = [
    {
        "id": "control",
        "label": "Control (signal_low × 0.934)",
        "role": "control",
        "stop_kind": "signal_low",
        "extra_v": [],
    },
    {
        "id": "stop_090",
        "label": "rl_stop_pct=0.90 (wider)",
        "role": "candidate",
        "stop_kind": "signal_low",
        "extra_v": ["rl_stop_pct=0.90"],
    },
    {
        "id": "stop_920",
        "label": "rl_stop_pct=0.920",
        "role": "candidate",
        "stop_kind": "signal_low",
        "extra_v": ["rl_stop_pct=0.920"],
    },
    {
        "id": "stop_925",
        "label": "rl_stop_pct=0.925 (prior grid)",
        "role": "reference",
        "stop_kind": "signal_low",
        "extra_v": ["rl_stop_pct=0.925"],
    },
    {
        "id": "stop_940",
        "label": "rl_stop_pct=0.940 (tighter)",
        "role": "candidate",
        "stop_kind": "signal_low",
        "extra_v": ["rl_stop_pct=0.940"],
    },
    {
        "id": "stop_945",
        "label": "rl_stop_pct=0.945",
        "role": "candidate",
        "stop_kind": "signal_low",
        "extra_v": ["rl_stop_pct=0.945"],
    },
    {
        "id": "dip_lo",
        "label": "Stop at dip zone low (SMA50×0.959)",
        "role": "candidate",
        "stop_kind": "dip_lo",
        "extra_v": ["rl_stop_anchor=dip_lo", "rl_stop_below_pct=0"],
    },
    {
        "id": "dip_lo_m1",
        "label": "Stop 1% below dip zone low",
        "role": "candidate",
        "stop_kind": "dip_lo",
        "extra_v": ["rl_stop_anchor=dip_lo", "rl_stop_below_pct=0.01"],
    },
    {
        "id": "dip_lo_m2",
        "label": "Stop 2% below dip zone low",
        "role": "candidate",
        "stop_kind": "dip_lo",
        "extra_v": ["rl_stop_anchor=dip_lo", "rl_stop_below_pct=0.02"],
    },
    {
        "id": "dip_lo_m3",
        "label": "Stop 3% below dip zone low",
        "role": "candidate",
        "stop_kind": "dip_lo",
        "extra_v": ["rl_stop_anchor=dip_lo", "rl_stop_below_pct=0.03"],
    },
    {
        "id": "entry_97",
        "label": "Stop entry×0.97 (3% below entry)",
        "role": "candidate",
        "stop_kind": "entry_open",
        "extra_v": ["rl_stop_anchor=entry_open", "rl_stop_pct=0.97"],
    },
    {
        "id": "entry_95",
        "label": "Stop entry×0.95 (5% below entry)",
        "role": "candidate",
        "stop_kind": "entry_open",
        "extra_v": ["rl_stop_anchor=entry_open", "rl_stop_pct=0.95"],
    },
    {
        "id": "sma50_99",
        "label": "Stop prior SMA50×0.99",
        "role": "candidate",
        "stop_kind": "sma50",
        "extra_v": ["rl_stop_anchor=sma50", "rl_stop_pct=0.99"],
    },
    {
        "id": "atr2",
        "label": "Stop entry − 2×ATR(14)",
        "role": "candidate",
        "stop_kind": "atr2",
        "extra_v": ["rl_stop_anchor=atr2"],
    },
]


def _resolve_python() -> str:
    env_py = os.environ.get("PY", "").strip()
    if env_py and Path(env_py).is_file():
        return env_py
    for p in (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Python/Python310/python.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Python/Python311/python.exe",
    ):
        if p.is_file():
            return str(p)
    return sys.executable


def load_universe(path: Path) -> str:
    syms: list[str] = []
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            s = line.strip().upper()
            if not s or s.startswith("#") or s == "SYMBOL":
                continue
            syms.append(s.split(",")[0].strip().upper())
    if not syms:
        raise RuntimeError(f"No symbols in {path}")
    return ",".join(syms)


def build_cmd(py: str, outdir: Path, workers: int, symbols: str, extra_v: list[str]) -> list[str]:
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
    for v in RL_COMMON_V + extra_v:
        cmd.extend(["-v", v])
    cmd.extend(["-s", symbols])
    return cmd


def _find_latest(outdir: Path, pattern: str) -> Optional[Path]:
    files = sorted(outdir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _parse_d(s: Any) -> Optional[date]:
    t = str(s or "").strip()
    if not t:
        return None
    compact = t.replace("-", "").replace("/", "")[:8]
    for cand, fmt in ((t[:10], "%Y-%m-%d"), (compact, "%Y%m%d"), (t[:10], "%m/%d/%Y")):
        try:
            return datetime.strptime(cand, fmt).date()
        except ValueError:
            continue
    return None


def _f(v: Any, default: float = 0.0) -> float:
    if v is None or v == "":
        return default
    s = str(v).strip().replace("%", "").replace(",", "").replace("$", "")
    if not s:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _row_get(row: dict, *names: str) -> str:
    for n in names:
        if n in row and row[n] not in (None, ""):
            return str(row[n]).strip()
        for k, v in row.items():
            if str(k).strip().upper().replace(" ", "_") == n.upper().replace(" ", "_") and v not in (None, ""):
                return str(v).strip()
    return ""


def load_trades(closed_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with closed_path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _parse_d(_row_get(raw, "DATE OPENED", "DATE_OPENED"))
            closed = _parse_d(_row_get(raw, "DATE CLOSED", "DATE_CLOSED"))
            if opened is None:
                continue
            pnl = _f(_row_get(raw, "PNL %", "PNL_PCT"))
            days = _f(_row_get(raw, "DAYS HELD", "DAYS_HELD"))
            pnl_d = _f(_row_get(raw, "PNL_DOLLARS"))
            if pnl_d == 0.0 and pnl != 0.0:
                pnl_d = RL_CASH * pnl / 100.0
            rows.append(
                {
                    "sym": _row_get(raw, "SYMBOL").upper(),
                    "opened": opened,
                    "closed": closed,
                    "pnl": pnl,
                    "days": days,
                    "pnl_d": pnl_d,
                    "exit": _row_get(raw, "EXIT TYPE", "EXIT_TYPE") or "?",
                }
            )
    return rows


def book_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(trades)
    empty: dict[str, Any] = {
        "n": 0,
        "wins": 0,
        "losses": 0,
        "wr": 0.0,
        "avg_pnl": 0.0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "pf": 0.0,
        "sheet": 0.0,
        "pnl_d": 0.0,
        "avg_days": 0.0,
        "med_days": 0.0,
        "cap_days": 0.0,
        "ppc": 0.0,
        "ann_ror": float("nan"),
        "max_dd": float("nan"),
        "calmar": float("nan"),
        "wo_max": 0.0,
        "exp_d": 0.0,
        "lose_streak": 0,
        "tpy": float("nan"),
        "exits": {},
    }
    if n == 0:
        return empty
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    mx = max(pnls)
    wo = (sum(pnls) - mx) / (n - 1) if n >= 2 else pnls[0]
    days = [t["days"] for t in trades if math.isfinite(t["days"]) and t["days"] > 0]
    cap = overlay_ann_ror_max_dd(trades, cash=RL_CASH, initial_account=INIT)
    sheet = sum(p / 100.0 * RL_CASH for p in pnls)
    pnl_d = sum(t["pnl_d"] for t in trades if math.isfinite(t["pnl_d"]))
    ann = cap["ann_ror"]
    dd = cap["max_dd"]
    cal = calmar_ratio(ann, dd) if calmar_ratio else float("nan")
    opens = [t["opened"] for t in trades if t["opened"]]
    closes = [t["closed"] for t in trades if t["closed"]]
    span = None
    if opens:
        lo = min(opens)
        hi = max(closes) if closes else max(opens)
        span = (hi - lo).days / 365.25
    tpy = (n / span) if span and span > 0 else float("nan")
    streak = cur = 0
    max_streak = 0
    for p in pnls:
        if p < 0:
            cur += 1
            max_streak = max(max_streak, cur)
        else:
            cur = 0
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "wr": 100.0 * len(wins) / n,
        "avg_pnl": sum(pnls) / n,
        "avg_win": (sum(wins) / len(wins)) if wins else 0.0,
        "avg_loss": (sum(losses) / len(losses)) if losses else 0.0,
        "pf": (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0),
        "sheet": sheet,
        "pnl_d": pnl_d,
        "avg_days": (sum(days) / len(days)) if days else 0.0,
        "med_days": sorted(days)[len(days) // 2] if days else 0.0,
        "cap_days": float(cap["capital_days"] or 0.0),
        "ppc": (pnl_d / cap["capital_days"]) if cap["capital_days"] else float("nan"),
        "ann_ror": ann,
        "max_dd": dd,
        "calmar": cal,
        "wo_max": wo,
        "exp_d": sheet / n,
        "lose_streak": max_streak,
        "tpy": tpy,
        "exits": dict(Counter(str(t.get("exit") or "?").strip().upper() for t in trades)),
    }


def split_is_oos(trades: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    return [t for t in trades if t["opened"] < IS_CUT], [t for t in trades if t["opened"] >= IS_CUT]


def run_arm(
    py: str,
    arm: dict[str, Any],
    symbols: str,
    workers: int,
    skip_existing: bool,
) -> dict[str, Any]:
    arm_dir = OUT_DIR / "runs" / arm["id"]
    arm_dir.mkdir(parents=True, exist_ok=True)
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
            }
    cmd = build_cmd(py, arm_dir, workers, symbols, arm["extra_v"])
    log_path = arm_dir / "run.log"
    t0 = time.time()
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write("CMD: " + " ".join(cmd) + "\n\n")
        log.flush()
        proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(ROOT))
    closed = _find_latest(arm_dir, "RL_Closed_*.csv")
    trades = load_trades(closed) if closed else []
    ok = proc.returncode == 0 and len(trades) > 0
    return {
        "arm": arm,
        "ok": ok,
        "skipped": False,
        "closed": closed,
        "trades": trades,
        "stamp": closed.stem.split("_")[-1] if closed else "",
        "elapsed_s": time.time() - t0,
        "exit_code": proc.returncode,
    }


def pack_result(run: dict[str, Any], ctrl_trades: list[dict[str, Any]]) -> dict[str, Any]:
    arm = run["arm"]
    trades = run["trades"]
    is_t, oos_t = split_is_oos(trades)
    is_c, oos_c = split_is_oos(ctrl_trades)
    m_full = book_stats(trades)
    m_is = book_stats(is_t)
    m_oos = book_stats(oos_t)
    m_ctrl_full = book_stats(ctrl_trades)
    m_ctrl_is = book_stats(is_c)
    m_ctrl_oos = book_stats(oos_c)
    if arm["role"] == "control":
        verd, note = "CONTROL", "House stop: signal-bar Low × rl_stop_pct=0.934"
    else:
        verd, note = verdict(m_ctrl_is, m_is, m_ctrl_oos, m_oos)
        if arm["role"] == "reference":
            verd = f"REF/{verd}" if verd != "CONTROL" else verd
    return {
        **run,
        "m_full": m_full,
        "m_is": m_is,
        "m_oos": m_oos,
        "m_ctrl_full": m_ctrl_full,
        "m_ctrl_is": m_ctrl_is,
        "m_ctrl_oos": m_ctrl_oos,
        "verd": verd,
        "note": note,
    }


def fmt_n(v: Any, nd: int = 2) -> str:
    if v is None:
        return "—"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(x):
        return "—"
    if nd == 0:
        return str(int(round(x)))
    return f"{x:.{nd}f}"


def compare_row(p: dict[str, Any], split_key: str, ctrl: dict[str, Any]) -> str:
    m = p[split_key]
    c = ctrl[split_key]
    arm = p["arm"]
    d_avg = m["avg_pnl"] - c["avg_pnl"]
    d_pf = m["pf"] - c["pf"]
    d_ann = m["ann_ror"] - c["ann_ror"] if math.isfinite(m["ann_ror"]) and math.isfinite(c["ann_ror"]) else float("nan")
    d_dd = m["max_dd"] - c["max_dd"] if math.isfinite(m["max_dd"]) and math.isfinite(c["max_dd"]) else float("nan")
    cls = "ctrl-row" if arm["role"] == "control" else ""
    stop_desc = arm.get("stop_kind", "signal_low")
    extra = ",".join(arm.get("extra_v") or [])
    return (
        f'<tr class="{cls}">'
        f'<td data-sort-value="{html_mod.escape(arm["label"])}">{html_mod.escape(arm["label"])}</td>'
        f'<td data-sort-value="{arm["role"]}">{arm["role"]}</td>'
        f'<td data-sort-value="{stop_desc}">{stop_desc}</td>'
        f'<td data-sort-value="{extra}"><code>{html_mod.escape(extra or "house")}</code></td>'
        f'<td data-sort-value="{m["n"]}">{m["n"]}</td>'
        f'<td data-sort-value="{m["wr"]}">{fmt_n(m["wr"], 2)}</td>'
        f'<td data-sort-value="{m["avg_pnl"]}">{fmt_n(m["avg_pnl"], 2)}</td>'
        f'<td data-sort-value="{m["wo_max"]}">{fmt_n(m["wo_max"], 2)}</td>'
        f'<td data-sort-value="{m["pf"]}">{fmt_n(m["pf"], 3)}</td>'
        f'<td data-sort-value="{m["ann_ror"]}">{fmt_n(m["ann_ror"], 2)}</td>'
        f'<td data-sort-value="{m["max_dd"]}">{fmt_n(m["max_dd"], 2)}</td>'
        f'<td data-sort-value="{m["exp_d"]}">{format_money(m["exp_d"])}</td>'
        f'<td data-sort-value="{m["avg_days"]}">{fmt_n(m["avg_days"], 2)}</td>'
        f'<td data-sort-value="{m["cap_days"]}">{fmt_n(m["cap_days"], 0)}</td>'
        f'<td data-sort-value="{m["ppc"]}">{format_money(m["ppc"]) if math.isfinite(m["ppc"]) else "—"}</td>'
        f'<td data-sort-value="{m["lose_streak"]}">{m["lose_streak"]}</td>'
        f'<td data-sort-value="{m["tpy"]}">{fmt_n(m["tpy"], 2)}</td>'
        f'<td data-sort-value="{d_avg if arm["role"] != "control" else ""}">'
        f'{"—" if arm["role"] == "control" else f"{d_avg:+.2f}"}</td>'
        f'<td data-sort-value="{d_pf if arm["role"] != "control" else ""}">'
        f'{"—" if arm["role"] == "control" else f"{d_pf:+.3f}"}</td>'
        f'<td data-sort-value="{d_ann if arm["role"] != "control" else ""}">'
        f'{"—" if arm["role"] == "control" else fmt_n(d_ann, 2)}</td>'
        f'<td data-sort-value="{d_dd if arm["role"] != "control" else ""}">'
        f'{"—" if arm["role"] == "control" else fmt_n(d_dd, 2)}</td>'
        f'<td data-sort-value="{p["verd"] if split_key == "m_is" else ""}">'
        f'{html_mod.escape(p["verd"] if split_key == "m_is" else "")}</td>'
        "</tr>"
    )


def write_compare_html(packed: list[dict[str, Any]]) -> Path:
    ctrl = packed[0]
    th_cols = filter_html_compare_columns(
        [
            ("Arm", "text"),
            ("Role", "text"),
            ("Stop kind", "text"),
            ("Override", "text"),
            ("N", "num"),
            ("WR%", "num"),
            ("Sheet PnL $", "num"),
            ("Avg PnL%", "num"),
            ("Avg% w/o max", "num"),
            ("PF", "num"),
            ("Ann ROR%", "num"),
            ("Max DD%", "num"),
            ("Expect $", "num"),
            ("Avg days", "num"),
            ("Cap days", "num"),
            ("PPCD", "num"),
            ("Lose streak", "num"),
            ("Trades/yr", "num"),
            ("Δ Sheet $", "num"),
            ("Δ Avg%", "num"),
            ("Δ PF", "num"),
            ("Δ Ann ROR", "num"),
            ("Δ Max DD", "num"),
            ("Verdict", "text"),
        ]
    )
    th = "".join(sortable_th(a, b) for a, b in th_cols)
    sections = []
    for split_key, title in (("m_is", "IS"), ("m_oos", "OOS (report-only)"), ("m_full", "FULL")):
        body = "".join(compare_row(p, split_key, ctrl) for p in packed)
        sections.append(
            f'<section><h2>RL stop AB — {title}</h2>'
            f'<p class="muted">Split=<strong>{title.split()[0]}</strong>. '
            f"Ann ROR / Max DD = Closed overlay at ${RL_CASH:,.0f} cash / ${INIT:,.0f} initial. "
            f"Click column headers to sort.</p>"
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{th}</tr></thead>'
            f"<tbody>{body}</tbody></table></div></section>"
        )
    exit_rows = []
    for p in packed:
        ex = p["m_full"]["exits"]
        exit_rows.append(
            f"<tr><td>{html_mod.escape(p['arm']['label'])}</td>"
            f"<td>{ex.get('TARGET', 0)}</td>"
            f"<td>{ex.get('STOP_LOSS', 0)}</td>"
            f"<td>{ex.get('GAP_DOWN', 0)}</td>"
            f"<td>{ex.get('GAP_UP', 0)}</td></tr>"
        )
    best_is = max(
        (p for p in packed if p["arm"]["role"] != "control"),
        key=lambda p: p["m_is"]["avg_pnl"],
        default=None,
    )
    verdict_bits = "; ".join(f"{p['arm']['id']}→{p['verd']}" for p in packed[:6])
    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL stop AB — {STAMP}</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; --accent:#5b9fd4; --ctrl:#243044; }}
body{{margin:0;font-family:ui-sans-serif,system-ui,Segoe UI,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header,main{{max-width:1200px;margin:0 auto;padding:0 1rem}}
header{{padding-top:1.25rem}}
h1{{font-size:1.35rem;margin:0 0 .35rem}}
h2{{font-size:1.05rem;margin:1.25rem 0 .4rem;color:var(--accent)}}
.muted{{color:var(--muted);font-size:.92rem}}
section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem 1rem;margin:1rem 0}}
.table-wrap{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:.82rem;min-width:900px}}
th,td{{border-bottom:1px solid var(--line);padding:.4rem .45rem;text-align:right}}
th:first-child,td:first-child,th:nth-child(2),td:nth-child(2),th:nth-child(3),td:nth-child(3),th:nth-child(4),td:nth-child(4){{text-align:left}}
tr.ctrl-row{{background:var(--ctrl)}}
{SORTABLE_TH_CSS}
code{{font-size:.85em}}
</style></head><body>
<header>
<h1>RL stop exploration AB — house freeze</h1>
<p class="muted">Stamp <code>rl_stop_ab_{STAMP}</code>. Control: <strong>signal-bar Low × rl_stop_pct=0.934</strong>
(−6.6% vs signal low). House dip=1.041, exp=1.163, target=1.2, too_high=off.
IS = entry &lt; 2024-01-01; OOS report-only. <strong>STOP exploration stamp</strong> — selection bias if picking among arms.
Research-only — not gold / not DailyRun.</p>
</header>
<main>
{"".join(sections)}
<section><h2>Exit mix (FULL)</h2>
<div class="table-wrap"><table class="sortable"><thead><tr>
{sortable_th("Arm","text")}{sortable_th("TARGET","num")}{sortable_th("STOP_LOSS","num")}
{sortable_th("GAP_DOWN","num")}{sortable_th("GAP_UP","num")}
</tr></thead><tbody>{"".join(exit_rows)}</tbody></table></div></section>
<p class="muted">Best IS Avg% (not KEEP): {html_mod.escape(best_is["arm"]["label"] if best_is else "n/a")}.
Generated by <code>tools/rl_stop_ab.py</code>.</p>
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>"""
    path = OUT_DIR / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_metrics_csv(packed: list[dict[str, Any]], path: Path) -> None:
    rows: list[dict[str, str]] = []
    for p in packed:
        for split, mk in (("full", "m_full"), ("is", "m_is"), ("oos", "m_oos")):
            s = p[mk]
            rows.append(
                {
                    "arm_id": p["arm"]["id"],
                    "arm_label": p["arm"]["label"],
                    "role": p["arm"]["role"],
                    "stop_kind": p["arm"].get("stop_kind", ""),
                    "split": split,
                    "n": str(s["n"]),
                    "wr_pct": fmt_n(s["wr"], 2),
                    "sheet_pnl": format_money(s["sheet"]),
                    "avg_pnl_pct": fmt_n(s["avg_pnl"], 2),
                    "wo_max": fmt_n(s["wo_max"], 2),
                    "pf": fmt_n(s["pf"], 3),
                    "ann_ror": fmt_n(s["ann_ror"], 2),
                    "max_dd": fmt_n(s["max_dd"], 2),
                    "calmar": format_calmar(s["ann_ror"], s["max_dd"]) if format_calmar else fmt_n(s["calmar"], 2),
                    "expect_d": format_money(s["exp_d"]),
                    "avg_days": fmt_n(s["avg_days"], 2),
                    "cap_days": fmt_n(s["cap_days"], 0),
                    "ppcd": format_money(s["ppc"]) if math.isfinite(s["ppc"]) else "",
                    "lose_streak": str(s["lose_streak"]),
                    "trades_yr": fmt_n(s["tpy"], 2),
                    "verdict": p["verd"] if split == "is" else "",
                    "stamp": p.get("stamp", ""),
                }
            )
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["arm_id"])
        w.writeheader()
        w.writerows(rows)


def write_baseline(packed: list[dict[str, Any]]) -> None:
    lines = [
        f"# BASELINE — `rl_stop_ab_{STAMP}`",
        "",
        "**Research only. Not gold. Not DailyRun. Do not wire `run_rl.bat`.**",
        "",
        f"Generated: {datetime.now():%Y-%m-%d %H:%M}. **STOP exploration** — multiple stop definitions under house entry freeze.",
        "",
        "## What is control stop today?",
        "",
        "| Item | Value |",
        "|------|-------|",
        "| Knob | **`rl_stop_pct`** |",
        "| Value | **0.934** |",
        "| Definition | **Stop = signal-bar Low × 0.934** (−6.6% below signal low) |",
        "| Also gates fills | `too_low`: skip fill if next open < signal Low × 0.934 |",
        "| Target (unchanged) | prior SMA50 × `rl_target_pct` = 1.20 |",
        "",
        "Python-only research anchors (`rl_stop_anchor`, `rl_stop_below_pct`) do **not** change fill gates.",
        "",
        "## Selection bias",
        "",
        "- Multi-arm STOP exploration on same history — label in-sample selection if picking a winner.",
        "- Prior `rl_stop_target_grid_dip105_exp115_20260822` tested stop×target on **non-house** dip/exp freeze — not comparable to this stamp.",
        "",
        "## Control freeze (house)",
        "",
        "| Knob | Value |",
        "|------|-------|",
        "| `rl_dip_pct` | **1.041** |",
        "| `rl_expansion` | **1.163** |",
        "| `rl_too_high` | **0.0 (off)** |",
        "| `rl_stop_pct` | **0.934** (control arm) |",
        "| `rl_target_pct` | **1.2** |",
        "| `rl_cash` | $47,500 |",
        "| Universe | drive/universes/RL_universe.csv (59) |",
        "",
        "## Arms",
        "",
        "| Arm | Stop definition | Role |",
        "|-----|-----------------|------|",
    ]
    for arm in ARMS:
        lines.append(f"| `{arm['id']}` | {arm['label']} | {arm['role']} |")
    lines.extend(
        [
            "",
            "## Method",
            "",
            "- Full RL engine reruns (`rocket_tbn.py` `rl_mode=true`) per arm.",
            "- `rl_stop_pct` arms also change `too_low` fill gate — not overlay-safe.",
            "- Dip/entry/SMA/ATR anchors: Python port only; AWK parity not claimed.",
            "",
            "## IS / OOS",
            "",
            "- **IS:** entry_date < 2024-01-01",
            "- **OOS:** entry_date ≥ 2024-01-01 — report-only",
            "",
            "## Arms completed",
            "",
            "| Arm | Stamp | N | OK |",
            "|-----|-------|---|-----|",
        ]
    )
    for p in packed:
        lines.append(
            f"| `{p['arm']['id']}` | `{p.get('stamp','')}` | {p['m_full']['n']} | "
            f"{'yes' if p.get('ok') else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            "- `compare.html` — sortable IS/OOS/full",
            "- `metrics_all.csv`",
            "- `SUMMARY.md`",
            "- `runs/<arm>/RL_*`",
        ]
    )
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_summary(packed: list[dict[str, Any]]) -> None:
    ctrl = packed[0]
    lines = [
        f"# SUMMARY — `rl_stop_ab_{STAMP}`",
        "",
        "**Research only. Not gold / not DailyRun.** Judge on **IS** vs control; OOS report-only.",
        "",
        "## Control stop (plain English)",
        "",
        "House RL stop is **`rl_stop_pct=0.934`**: protective stop at **signal-bar Low × 0.934** "
        "(6.6% below the signal bar's low). Same multiplier gates the **too-low** fill reject.",
        "",
        "## IS metrics (all arms vs control)",
        "",
        "| Arm | N | WR% | Avg% | WO_MAX | PF | Ann ROR | Max DD | Δ Avg% | Verdict |",
        "|-----|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for p in packed:
        m = p["m_is"]
        c = ctrl["m_is"]
        d_avg = m["avg_pnl"] - c["avg_pnl"]
        lines.append(
            f"| {p['arm']['label']} | {m['n']} | {m['wr']:.1f} | {m['avg_pnl']:.2f} | "
            f"{m['wo_max']:.2f} | {m['pf']:.2f} | {fmt_n(m['ann_ror'],1)} | {fmt_n(m['max_dd'],2)} | "
            f"{'—' if p['arm']['role']=='control' else f'{d_avg:+.2f}'} | **{p['verd']}** |"
        )
    lines.extend(["", "## OOS (report-only)", ""])
    for p in packed:
        m = p["m_oos"]
        c = ctrl["m_oos"]
        lines.append(
            f"- **{p['arm']['label']}**: N={m['n']}, Avg%={m['avg_pnl']:.2f} "
            f"(Δ vs ctrl {m['avg_pnl']-c['avg_pnl']:+.2f}pp), PF={m['pf']:.2f}"
        )
    best = max((p for p in packed if p["arm"]["role"] != "control"), key=lambda x: x["m_is"]["avg_pnl"], default=None)
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
        ]
    )
    keep_arms = [p for p in packed if p["verd"] in ("KEEP", "LEAN KEEP")]
    if keep_arms:
        lines.append(
            f"- **LEAN candidates (IS):** {', '.join(p['arm']['id'] for p in keep_arms)} — still research-only; "
            "confirm AWK parity before any promotion."
        )
    else:
        lines.append("- **No KEEP** — hold house **`rl_stop_pct=0.934`** (signal_low anchor).")
    if best:
        lines.append(
            f"- Best IS Avg% arm: **{best['arm']['label']}** ({best['m_is']['avg_pnl']:.2f}% vs control "
            f"{ctrl['m_is']['avg_pnl']:.2f}%) → **{best['verd']}**. Selection bias — not adopt from grid alone."
        )
    lines.extend(
        [
            "",
            "## Process notes",
            "",
            "- Quality over N; OOS soften → HOLD, do not retune.",
            "- Dip-zone / entry / SMA / ATR anchors are Python-port research levers.",
            "- Prior grid at dip=1.05/exp=1.15: best IS stop=0.93/tgt=1.25 but Ann ROR worse → HOLD.",
        ]
    )
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def summarize(packed: list[dict[str, Any]]) -> None:
    write_compare_html(packed)
    write_metrics_csv(packed, OUT_DIR / "metrics_all.csv")
    write_baseline(packed)
    write_summary(packed)
    print(f"[RL-STOP-AB] Wrote {OUT_DIR / 'compare.html'}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--smoke", action="store_true", help="Run control + 2 arms on 3 symbols")
    parser.add_argument("--skip-existing", action="store_true", default=False)
    parser.add_argument("--force", action="store_true", help="Re-run even if Closed exists")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--workers", type=int, default=5)
    args = parser.parse_args()
    skip_existing = args.skip_existing and not args.force

    py = _resolve_python()
    symbols = "AAPL,AMD,NVDA" if args.smoke else load_universe(UNIV_PATH)
    arms = ARMS[:3] if args.smoke else ARMS

    if args.summarize_only:
        runs_dir = OUT_DIR / "runs"
        if not runs_dir.is_dir():
            print(f"No runs under {runs_dir}", flush=True)
            return 1
        runs: list[dict[str, Any]] = []
        for arm in arms:
            closed = _find_latest(runs_dir / arm["id"], "RL_Closed_*.csv")
            if not closed:
                continue
            trades = load_trades(closed)
            runs.append(
                {
                    "arm": arm,
                    "ok": bool(trades),
                    "trades": trades,
                    "stamp": closed.stem.split("_")[-1],
                    "closed": closed,
                }
            )
        if not runs:
            return 1
        ctrl_trades = runs[0]["trades"]
        packed = [pack_result(r, ctrl_trades) for r in runs]
        summarize(packed)
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "runs").mkdir(exist_ok=True)
    print(f"[RL-STOP-AB] {len(arms)} arms · {len(symbols.split(','))} symbols · jobs={args.jobs}", flush=True)

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futs = {
            pool.submit(run_arm, py, arm, symbols, args.workers, skip_existing): arm
            for arm in arms
        }
        for fut in as_completed(futs):
            arm = futs[fut]
            try:
                res = fut.result()
            except Exception as e:
                res = {"arm": arm, "ok": False, "trades": [], "error": str(e)}
            status = "ok" if res.get("ok") else "FAIL"
            n = len(res.get("trades") or [])
            print(f"[RL-STOP-AB] {arm['id']}: {status} N={n} elapsed={res.get('elapsed_s', 0):.0f}s", flush=True)
            results.append(res)

    results.sort(key=lambda r: next(i for i, a in enumerate(arms) if a["id"] == r["arm"]["id"]))
    ctrl = next((r for r in results if r["arm"]["role"] == "control"), results[0])
    if not ctrl.get("trades"):
        print("[RL-STOP-AB] control run failed", flush=True)
        return 1
    packed = [pack_result(r, ctrl["trades"]) for r in results]
    summarize(packed)

    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    if ntfy.is_file():
        subprocess.run(
            [py, str(ntfy), "--path", str(OUT_DIR / "compare.html"), "-t", "RL stop AB"],
            cwd=str(ROOT),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
