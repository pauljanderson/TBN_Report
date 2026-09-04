#!/usr/bin/env python3
"""RL universe A/B: static ADV$2m 764 vs PIT 20d avg shares ≥ 500k.

Control: tradable 764 (VZ_tradable_2010_adv2m) under adopted 40_30d freeze.
Candidate: same 2010-first-bar + $5 as-of construction WITHOUT ADV$2m dollar gate;
          at RL trigger bar require avg_vol (20 sessions ending on trigger) ≥ 500,000 shares.

House freeze (adopted rl_adopt_exit_40_30d_20260831):
  cut=1000, exit 0.40/30d, dip 1.055, expansion 1.163, stop 0.934, target 1.20,
  too_high=0, flush=0.

IS = entry < 2024-01-01; OOS report-only. Research-only. Not gold. Not DailyRun.

Usage:
  python tools/rl_pit_vol500k_univ_ab.py
  python tools/rl_pit_vol500k_univ_ab.py --summarize-only
  python tools/rl_pit_vol500k_univ_ab.py --skip-existing --workers 12
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import shutil
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
DATA_DIR = ROOT / "data" / "newdata" / "data"
STAMP = "20260831"
OUT_DIR = DRIVE / "paul_experiments" / f"rl_pit_vol500k_univ_ab_{STAMP}"
CONTROL_UNIV = DRIVE / "universes" / "VZ_tradable_2010_adv2m_universe.csv"
REJECTS = DRIVE / "paul_experiments" / "vz_tradable_2010_adv2m_20260818" / "universe_rejects.csv"
CONTROL_REUSE = (
    DRIVE
    / "paul_experiments"
    / "rl_too_high_ab_after_40_30d_20260831"
    / "runs"
    / "control"
)
CONTROL_ID = "control_764"
CAND_ID = "pit_vol500k"
PIT_AVG_VOL_DAYS = 20
PIT_MIN_AVG_VOL = 500_000.0
FIRST_BAR_MAX = date(2010, 1, 4)
ASOF = date(2023, 12, 29)
MIN_CLOSE = 5.0
IS_CUT = date(2024, 1, 1)

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(DRIVE / "paul_experiments"))
from be_stop_replay_ab import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from compare_format import filter_html_compare_columns  # noqa: E402
from rl_univ_compare_lists import (  # noqa: E402
    build_cmd as _lists_build_cmd,
    compare_row,
    fmt_n,
    load_trades,
    pack_result,
    verdict_vs_control,
    write_metrics_csv,
    _find_latest,
    _resolve_python,
)
from vz_is_paul_universe_ab import load_universe_symbols  # noqa: E402
from _gen_too_high_diff import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT as DIFF_SORT_JS,
    SORTABLE_TH_CSS as DIFF_SORT_CSS,
    sortable_th as diff_sortable_th,
)


def _parse_d(s: Any) -> Optional[date]:
    t = str(s or "").strip()
    if not t:
        return None
    for cand, fmt in ((t[:10], "%Y-%m-%d"), (t.replace("-", "")[:8], "%Y%m%d")):
        try:
            return datetime.strptime(cand, fmt).date()
        except ValueError:
            continue
    return None


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(str(v).replace(",", "").replace("%", "").replace("$", ""))
    except (TypeError, ValueError):
        return default


def build_candidate_universe() -> tuple[list[str], dict[str, list[str]], Path]:
    """2010 + $5 as-of; drop ADV$2m. Prefer rejects CSV; fall back to rescanning."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    control = set(load_universe_symbols(CONTROL_UNIV))
    cand: list[str] = []
    membership: list[dict[str, str]] = []

    if REJECTS.is_file():
        with REJECTS.open(newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                sym = str(row.get("SYMBOL") or "").strip().upper()
                if not sym:
                    continue
                reason = str(row.get("reason") or "").strip()
                first = _parse_d(row.get("first_bar"))
                close = _f(row.get("asof_close"))
                # pass OR failed only on ADV$2m → eligible for candidate pool
                ok = reason == "pass" or reason.startswith("adv20<")
                if not (ok and first is not None and first <= FIRST_BAR_MAX and close >= MIN_CLOSE):
                    continue
                cand.append(sym)
                membership.append(
                    {
                        "SYMBOL": sym,
                        "bucket": "",  # filled below
                        "first_bar": str(row.get("first_bar") or ""),
                        "asof_date": str(row.get("asof_date") or ""),
                        "asof_close": str(row.get("asof_close") or ""),
                        "adv20_usd": str(row.get("adv20_usd") or ""),
                        "reject_reason": reason,
                    }
                )
    else:
        # Rescan: first_bar + $5 only
        for path in sorted(DATA_DIR.glob("*.csv")):
            sym = path.stem.upper()
            first = None
            asof_i = -1
            closes: list[float] = []
            dates: list[date] = []
            with path.open(newline="", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    d = _parse_d(row.get("Date") or row.get("DATE"))
                    if d is None:
                        continue
                    if first is None:
                        first = d
                    dates.append(d)
                    closes.append(_f(row.get("Close") or row.get("CLOSE")))
                    if d <= ASOF:
                        asof_i = len(dates) - 1
            if first is None or first > FIRST_BAR_MAX or asof_i < 0:
                continue
            if closes[asof_i] < MIN_CLOSE:
                continue
            cand.append(sym)
            bucket = "in_both" if sym in control else "in_candidate_only"
            membership.append(
                {
                    "SYMBOL": sym,
                    "bucket": bucket,
                    "first_bar": first.isoformat(),
                    "asof_date": dates[asof_i].isoformat(),
                    "asof_close": str(round(closes[asof_i], 4)),
                    "adv20_usd": "",
                    "reject_reason": "rescanned",
                }
            )
        for sym in sorted(control - set(cand)):
            membership.append(
                {
                    "SYMBOL": sym,
                    "bucket": "in_control_only",
                    "first_bar": "",
                    "asof_date": "",
                    "asof_close": "",
                    "adv20_usd": "",
                    "reject_reason": "in_control_not_candidate",
                }
            )

    cand = sorted(set(cand))
    # Fix buckets vs final sets
    cand_set = set(cand)
    for m in membership:
        s = m["SYMBOL"]
        in_c = s in control
        in_k = s in cand_set
        if in_c and in_k:
            m["bucket"] = "in_both"
        elif in_c:
            m["bucket"] = "in_control_only"
        elif in_k:
            m["bucket"] = "in_candidate_only"

    # Ensure every candidate/control has a row
    have = {m["SYMBOL"] for m in membership}
    for s in sorted(cand_set | control):
        if s not in have:
            membership.append(
                {
                    "SYMBOL": s,
                    "bucket": (
                        "in_both"
                        if s in control and s in cand_set
                        else ("in_control_only" if s in control else "in_candidate_only")
                    ),
                    "first_bar": "",
                    "asof_date": "",
                    "asof_close": "",
                    "adv20_usd": "",
                    "reject_reason": "backfill",
                }
            )

    membership.sort(key=lambda r: r["SYMBOL"])
    mem_path = OUT_DIR / "universe_membership.csv"
    with mem_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "SYMBOL",
                "bucket",
                "first_bar",
                "asof_date",
                "asof_close",
                "adv20_usd",
                "reject_reason",
            ],
        )
        w.writeheader()
        w.writerows(membership)

    buckets = {
        "in_both": [m["SYMBOL"] for m in membership if m["bucket"] == "in_both"],
        "in_control_only": [m["SYMBOL"] for m in membership if m["bucket"] == "in_control_only"],
        "in_candidate_only": [m["SYMBOL"] for m in membership if m["bucket"] == "in_candidate_only"],
    }
    counts_path = OUT_DIR / "universe_membership_counts.csv"
    with counts_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["bucket", "n"])
        w.writerow(["control_764", len(control)])
        w.writerow(["candidate_pool_2010_5usd", len(cand)])
        for k, v in buckets.items():
            w.writerow([k, len(v)])

    univ_path = OUT_DIR / "candidate_universe_2010_5usd.csv"
    univ_path.write_text(
        "# RESEARCH — 2010 first_bar + as-of Close>=$5; NO static ADV$2m\n"
        "# PIT liquidity applied at RL trigger: 20d avg shares >= 500000\n"
        "SYMBOL\n" + "\n".join(cand) + "\n",
        encoding="utf-8",
    )
    return cand, buckets, mem_path


def build_cmd(py: str, outdir: Path, workers: int, symbols: str, extra_v: list[str]) -> list[str]:
    cmd = _lists_build_cmd(py, outdir, workers, symbols)
    for v in extra_v:
        cmd.extend(["-v", v])
    return cmd


def _copy_control() -> dict[str, Any]:
    arm = {
        "id": CONTROL_ID,
        "label": "Control 764 (static ADV$2m)",
        "role": "control",
        "symbols": load_universe_symbols(CONTROL_UNIV),
        "extra_v": [],
    }
    dest = OUT_DIR / "runs" / CONTROL_ID
    dest.mkdir(parents=True, exist_ok=True)
    closed = _find_latest(CONTROL_REUSE, "RL_Closed_*.csv")
    if not closed:
        return {"arm": arm, "ok": False, "skipped": True, "trades": [], "stamp": ""}
    stamp = closed.stem.split("_")[-1]
    for pattern in (
        f"RL_Closed_{stamp}.csv",
        f"RL_Summary_{stamp}.csv",
        f"RL_EquityMeta_{stamp}.csv",
        f"RL_Report_{stamp}.csv",
        f"RL_EquityCurve_{stamp}.csv",
        f"RL_EquityCurve_Regular_{stamp}.csv",
    ):
        src = CONTROL_REUSE / pattern
        if src.is_file():
            shutil.copy2(src, dest / src.name)
    trades = load_trades(dest / closed.name)
    return {
        "arm": arm,
        "ok": len(trades) > 0,
        "skipped": True,
        "closed": dest / closed.name,
        "trades": trades,
        "stamp": stamp,
        "summary": _find_latest(dest, "RL_Summary_*.csv"),
        "equity_meta": _find_latest(dest, "RL_EquityMeta_*.csv"),
        "report": _find_latest(dest, "RL_Report_*.csv"),
        "elapsed_s": 0.0,
        "reuse_from": str(CONTROL_REUSE),
    }


def run_candidate(py: str, symbols: list[str], workers: int, skip_existing: bool) -> dict[str, Any]:
    arm = {
        "id": CAND_ID,
        "label": f"PIT vol≥{int(PIT_MIN_AVG_VOL/1000)}k×{PIT_AVG_VOL_DAYS}d (wider pool)",
        "role": "candidate",
        "symbols": symbols,
        "extra_v": [
            f"rl_avg_vol_days={PIT_AVG_VOL_DAYS}",
            f"rl_min_avg_vol={int(PIT_MIN_AVG_VOL)}",
        ],
    }
    arm_dir = OUT_DIR / "runs" / CAND_ID
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
                "summary": _find_latest(arm_dir, "RL_Summary_*.csv"),
                "equity_meta": _find_latest(arm_dir, "RL_EquityMeta_*.csv"),
                "report": _find_latest(arm_dir, "RL_Report_*.csv"),
                "elapsed_s": 0.0,
            }
    cmd = build_cmd(py, arm_dir, workers, ",".join(symbols), arm["extra_v"])
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


def _trade_key(t: dict[str, Any]) -> tuple:
    opened = t.get("opened")
    return (
        str(t.get("sym") or "").upper(),
        opened.isoformat() if opened else "",
        round(float(t.get("entry") or 0.0), 4),
    )


def write_trade_diff(ctrl: dict[str, Any], cand: dict[str, Any]) -> tuple[Path, dict[str, int]]:
    """ONLY_IN_CANDIDATE = new under PIT; ONLY_IN_CONTROL = dropped vs control."""
    c_map = {_trade_key(t): t for t in ctrl["trades"]}
    k_map = {_trade_key(t): t for t in cand["trades"]}
    same_keys = sorted(set(c_map) & set(k_map))
    only_c = sorted(set(c_map) - set(k_map))
    only_k = sorted(set(k_map) - set(c_map))

    changed: list[tuple[dict, dict]] = []
    same: list[tuple[dict, dict]] = []
    for k in same_keys:
        a, b = c_map[k], k_map[k]
        same_exit = (
            str(a.get("exit") or "").upper() == str(b.get("exit") or "").upper()
            and abs(float(a.get("pnl") or 0) - float(b.get("pnl") or 0)) < 1e-6
            and (a.get("closed") == b.get("closed"))
        )
        if same_exit:
            same.append((a, b))
        else:
            changed.append((a, b))

    meta = {
        "only_new": len(only_k),
        "only_old": len(only_c),
        "same": len(same),
        "changed": len(changed),
    }

    def row_html(tag: str, t: dict, other: Optional[dict] = None) -> str:
        opened = t["opened"].isoformat() if t.get("opened") else ""
        closed = t["closed"].isoformat() if t.get("closed") else ""
        pnl = float(t.get("pnl") or 0)
        days = float(t.get("days") or 0)
        extra = ""
        if other is not None:
            extra = (
                f"<td>{html_mod.escape(str(other.get('exit') or ''))}</td>"
                f"<td>{fmt_n(other.get('pnl'), 2)}</td>"
                f"<td>{other['closed'].isoformat() if other.get('closed') else ''}</td>"
            )
        return (
            f"<tr>"
            f"<td>{html_mod.escape(tag)}</td>"
            f"<td>{html_mod.escape(str(t.get('sym') or ''))}</td>"
            f"<td data-sort-value='{opened}'>{opened}</td>"
            f"<td>{fmt_n(t.get('entry'), 2)}</td>"
            f"<td>{html_mod.escape(str(t.get('exit') or ''))}</td>"
            f"<td data-sort-value='{pnl}'>{fmt_n(pnl, 2)}</td>"
            f"<td data-sort-value='{days}'>{fmt_n(days, 1)}</td>"
            f"<td data-sort-value='{closed}'>{closed}</td>"
            f"{extra}"
            f"</tr>"
        )

    th_simple = "".join(
        diff_sortable_th(a, b)
        for a, b in [
            ("Bucket", "text"),
            ("Symbol", "text"),
            ("Opened", "date"),
            ("Entry", "num"),
            ("Exit", "text"),
            ("PnL%", "num"),
            ("Days", "num"),
            ("Closed", "date"),
        ]
    )
    th_changed = "".join(
        diff_sortable_th(a, b)
        for a, b in [
            ("Bucket", "text"),
            ("Symbol", "text"),
            ("Opened", "date"),
            ("Entry", "num"),
            ("Exit ctrl", "text"),
            ("PnL% ctrl", "num"),
            ("Days", "num"),
            ("Closed ctrl", "date"),
            ("Exit cand", "text"),
            ("PnL% cand", "num"),
            ("Closed cand", "date"),
        ]
    )

    def table(title: str, body: str, th: str, note: str) -> str:
        return f"""
<section>
  <h2>{html_mod.escape(title)}</h2>
  <p class="muted">{html_mod.escape(note)}</p>
  <p class="muted">Click column headers to sort.</p>
  <table class="sortable"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>
</section>
"""

    body_new = "".join(row_html("ONLY_IN_CANDIDATE", k_map[k]) for k in only_k)
    body_old = "".join(row_html("ONLY_IN_CONTROL", c_map[k]) for k in only_c)
    body_same = "".join(row_html("SAME", a) for a, _ in same)
    body_chg = "".join(row_html("CHANGED", a, b) for a, b in changed)

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<title>RL PIT vol500k trade diff</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 24px; color: #1e293b; background: #f8fafc; }}
h1 {{ margin-bottom: 4px; }}
.muted {{ color: #64748b; font-size: 14px; }}
table {{ border-collapse: collapse; width: 100%; background: #fff; margin: 12px 0 28px; font-size: 13px; }}
th, td {{ border: 1px solid #e2e8f0; padding: 6px 8px; text-align: left; }}
th {{ background: #f1f5f9; }}
.summary {{ display: flex; gap: 16px; flex-wrap: wrap; margin: 12px 0 24px; }}
.summary div {{ background: #fff; border: 1px solid #e2e8f0; padding: 10px 14px; border-radius: 6px; }}
{DIFF_SORT_CSS}
</style></head><body>
<h1>RL trade diff — control 764 vs PIT vol ≥ 500k</h1>
<p class="muted">Control stamp {html_mod.escape(ctrl.get('stamp',''))} · Candidate stamp {html_mod.escape(cand.get('stamp',''))} · Research only</p>
<div class="summary">
  <div><b>ONLY_IN_CANDIDATE</b><br/>{len(only_k)} <span class="muted">trades not taken before</span></div>
  <div><b>ONLY_IN_CONTROL</b><br/>{len(only_c)} <span class="muted">used to take, don’t anymore</span></div>
  <div><b>SAME</b><br/>{len(same)}</div>
  <div><b>CHANGED</b><br/>{len(changed)} <span class="muted">same entry key, different exit/PnL</span></div>
</div>
{table("ONLY_IN_CANDIDATE — trades not taken before", body_new or "<tr><td colspan='8'>none</td></tr>", th_simple,
       "New under wider pool + PIT 20d avg shares ≥ 500k (or path-dependent extras).")}
{table("ONLY_IN_CONTROL — trades we used to take that we don’t anymore", body_old or "<tr><td colspan='8'>none</td></tr>", th_simple,
       "Present on static ADV$2m 764 book; absent under PIT candidate (failed PIT that day, or path dependency).")}
{table("SAME — identical entry + exit/PnL", body_same or "<tr><td colspan='8'>none</td></tr>", th_simple, "Matched on symbol + open + entry.")}
{table("CHANGED — same entry key, different outcome", body_chg or "<tr><td colspan='11'>none</td></tr>", th_changed,
       "Same symbol/open/entry; exit type, close date, or PnL differs (path dependency).")}
{DIFF_SORT_JS}
</body></html>
"""
    out = OUT_DIR / "trade_diff.html"
    out.write_text(html, encoding="utf-8")

    # CSV mirror
    csv_path = OUT_DIR / "trade_diff_summary.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["bucket", "n"])
        w.writerow(["ONLY_IN_CANDIDATE", len(only_k)])
        w.writerow(["ONLY_IN_CONTROL", len(only_c)])
        w.writerow(["SAME", len(same)])
        w.writerow(["CHANGED", len(changed)])
        w.writerow([])
        w.writerow(["bucket", "symbol", "opened", "entry", "exit", "pnl_pct", "days", "closed"])
        for k in only_k:
            t = k_map[k]
            w.writerow(
                [
                    "ONLY_IN_CANDIDATE",
                    t["sym"],
                    t["opened"],
                    t["entry"],
                    t["exit"],
                    t["pnl"],
                    t["days"],
                    t["closed"],
                ]
            )
        for k in only_c:
            t = c_map[k]
            w.writerow(
                [
                    "ONLY_IN_CONTROL",
                    t["sym"],
                    t["opened"],
                    t["entry"],
                    t["exit"],
                    t["pnl"],
                    t["days"],
                    t["closed"],
                ]
            )

    (OUT_DIR / "trade_diff_counts.json").write_text(
        str(meta).replace("'", '"'), encoding="utf-8"
    )
    return out, meta


def write_compare_html(packed: list[dict[str, Any]], verdicts: dict[str, tuple[str, str]], buckets: dict) -> Path:
    by_id = {p["arm"]["id"]: p for p in packed}
    baseline = by_id[CONTROL_ID]
    th_cols = filter_html_compare_columns(
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
            ("Sharpe (full)", "num"),
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
    th = "".join(sortable_th(a, b) for a, b in th_cols)
    sections = []
    for split_key, title in (("m_is", "IS"), ("m_oos", "OOS (report-only)"), ("m_full", "FULL book")):
        body = "".join(compare_row(p, split_key, baseline, "", CONTROL_ID) for p in packed)
        note = (
            "Paul/FIT/Sharpe/UW from host Summary + EquityMeta (full history only)."
            if split_key == "m_full"
            else "Closed overlay at $47,500 cash / $500k initial. Paul/FIT N/A on slices."
        )
        sections.append(
            f"<h2>{title}</h2><p class='muted'>{note} Click column headers to sort.</p>"
            f"<table class='sortable'><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"
        )

    v_is = verdicts.get("is", ("HOLD", ""))
    v_oos = verdicts.get("oos", ("HOLD", ""))
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<title>RL PIT vol500k universe AB</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 24px; color: #1e293b; background: #f8fafc; }}
h1 {{ margin-bottom: 4px; }}
.muted {{ color: #64748b; }}
table {{ border-collapse: collapse; width: 100%; background: #fff; margin: 12px 0 28px; font-size: 13px; }}
th, td {{ border: 1px solid #e2e8f0; padding: 6px 8px; text-align: left; }}
th {{ background: #f1f5f9; }}
.ctrl-row {{ background: #f8fafc; }}
.card {{ background: #fff; border: 1px solid #e2e8f0; padding: 12px 16px; margin: 12px 0; border-radius: 6px; }}
{SORTABLE_TH_CSS}
</style></head><body>
<h1>RL PIT vol ≥ 500k (20d) vs static ADV$2m 764</h1>
<p class="muted">Stamp {STAMP} · Research only · Not gold · Not DailyRun · Freeze: adopt 40_30d</p>
<div class="card">
  <b>Universe</b><br/>
  Control N={len(baseline['arm']['symbols'])} · Candidate pool N={len(by_id[CAND_ID]['arm']['symbols'])}<br/>
  in_both={len(buckets.get('in_both',[]))} ·
  in_candidate_only={len(buckets.get('in_candidate_only',[]))} ·
  in_control_only={len(buckets.get('in_control_only',[]))}
</div>
<div class="card">
  <b>Verdict vs control</b><br/>
  IS: <b>{html_mod.escape(v_is[0])}</b> — {html_mod.escape(v_is[1])}<br/>
  OOS: <b>{html_mod.escape(v_oos[0])}</b> — {html_mod.escape(v_oos[1])} (report-only; do not retune)
</div>
{''.join(sections)}
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    out = OUT_DIR / "compare.html"
    out.write_text(html, encoding="utf-8")
    return out


def write_docs(
    packed: list[dict[str, Any]],
    verdicts: dict[str, tuple[str, str]],
    buckets: dict,
    diff_counts: dict[str, int],
    cand_n: int,
) -> None:
    by_id = {p["arm"]["id"]: p for p in packed}
    ctrl, cand = by_id[CONTROL_ID], by_id[CAND_ID]
    v_is, v_oos = verdicts["is"], verdicts["oos"]

    # Overall AB verdict: IS primary; OOS softens → HOLD
    overall = v_is[0]
    if v_is[0] in ("LEAN KEEP", "KEEP") and v_oos[0] == "DISMISS":
        overall = "HOLD"
        overall_note = "IS quality up but OOS softens — HOLD (do not retune OOS)."
    elif v_is[0] == "DISMISS":
        overall = "DISMISS"
        overall_note = v_is[1]
    elif v_is[0] in ("LEAN KEEP", "KEEP") and v_oos[0] in ("LEAN KEEP", "KEEP", "HOLD"):
        overall = "LEAN KEEP" if v_is[0] == "LEAN KEEP" else "KEEP"
        overall_note = f"IS {v_is[0]}; OOS {v_oos[0]} — research candidate ≠ gold."
    else:
        overall = "HOLD"
        overall_note = f"IS {v_is[0]}; OOS {v_oos[0]}."

    baseline = f"""# BASELINE — `rl_pit_vol500k_univ_ab_{STAMP}`

**Status:** RESEARCH only. Universe / PIT liquidity identity A/B vs adopted 40_30d freeze.
Not gold. Not DailyRun. Do not overwrite `RL_universe.csv`.

## Hypothesis (one change family)

Replace **static as-of ADV$ ≥ $2,000,000** membership (764 construction) with a **PIT trigger-day**
check: **20-session average volume (shares) ≥ 500,000**.

Keep the same **2010 first-bar** and **as-of Close ≥ $5** gates as 764 construction; only the
ADV$2m dollar gate is dropped from the eligible list. Liquidity is enforced per signal on the
engine trigger bar.

## House freeze (identical on both arms except univ + PIT vol)

| Knob | Value |
|------|-------|
| `rl_cut_the_losers` | **1000** (OFF) |
| `rl_exit_percent` / `rl_exit_days` | **0.40 / 30** (adopt 40_30d) |
| `rl_dip_pct` | 1.055 |
| `rl_expansion` | 1.163 |
| `rl_stop_pct` | 0.934 |
| `rl_target_pct` | 1.20 |
| `rl_too_high` | 0 |
| flush / trails | off |
| cash | $47,500 |

## Control vs candidate

| Arm | Universe | Volume gate | Source |
|-----|----------|-------------|--------|
| `{CONTROL_ID}` | `VZ_tradable_2010_adv2m_universe.csv` (**{len(ctrl['arm']['symbols'])}**) | none (static ADV$2m already in list) | reuse `{CONTROL_REUSE.name}` / stamp `{ctrl.get('stamp','')}` |
| `{CAND_ID}` | 2010 + $5, **no** ADV$2m (**{cand_n}**) | `rl_avg_vol_days={PIT_AVG_VOL_DAYS}`, `rl_min_avg_vol={int(PIT_MIN_AVG_VOL)}` | live run stamp `{cand.get('stamp','')}` |

### PIT convention (engine)

- `avg_vol` = mean volume over the last `rl_avg_vol_days` sessions **ending on the trigger/signal bar** (inclusive), same rolling window RL already uses for `AVG_VOL`.
- Gate fires when building the entry (fill = next open): skip if `avg_vol < 500000` or window not warm.
- Surge gate `rl_vol_pct_threshold` stays **0** (off).

## Membership counts

| Bucket | N |
|--------|---|
| control_764 | {len(ctrl['arm']['symbols'])} |
| candidate_pool | {cand_n} |
| in_both | {len(buckets.get('in_both', []))} |
| in_candidate_only | {len(buckets.get('in_candidate_only', []))} |
| in_control_only | {len(buckets.get('in_control_only', []))} |

## IS / OOS

IS = `entry_date < 2024-01-01`; OOS = `entry_date >= 2024-01-01` (report-only; no OOS retune).

## Verdicts

| Split | Verdict | Note |
|-------|---------|------|
| IS | **{v_is[0]}** | {v_is[1]} |
| OOS | **{v_oos[0]}** | {v_oos[1]} |
| **Overall** | **{overall}** | {overall_note} |

## Trade diff (entry key = symbol + open + entry)

| Bucket | N | Meaning |
|--------|---|---------|
| ONLY_IN_CANDIDATE | {diff_counts.get('only_new', 0)} | trades not taken before |
| ONLY_IN_CONTROL | {diff_counts.get('only_old', 0)} | used to take, don’t anymore |
| SAME | {diff_counts.get('same', 0)} | identical outcome |
| CHANGED | {diff_counts.get('changed', 0)} | same entry, different exit/PnL |

## Selection-bias / promotion

- Arms pre-specified (Paul ask). Judge quality over N.
- Research candidate ≠ gold ≠ DailyRun.
- Engine knob `rl_min_avg_vol` default **0** (production unchanged); only candidate arm sets it.
"""
    (OUT_DIR / "BASELINE.md").write_text(baseline, encoding="utf-8")

    def _line(p: dict, key: str) -> str:
        m = p[key]
        return (
            f"N={m['n']} WR={m['wr']:.1f}% Avg={m['avg_pnl']:.2f}% WO_MAX={m['wo_max']:.2f}% "
            f"PF={m['pf']:.2f} AnnROR={fmt_n(m['ann_ror'], 2)} MaxDD={fmt_n(m['max_dd'], 2)}"
        )

    summary = f"""# SUMMARY — `rl_pit_vol500k_univ_ab_{STAMP}`

## Plain English (Paul)

What if we drop the **static ADV$2m** 764 membership screen and instead require
**≥ 500,000 average shares over the past 20 days on the RL trigger day**?

- **Eligible list** grows from **{len(ctrl['arm']['symbols'])}** → **{cand_n}** names (same 2010 history + $5; +{len(buckets.get('in_candidate_only', []))} that failed only ADV$2m).
- **Trades:** +{diff_counts.get('only_new', 0)} new (not taken before), −{diff_counts.get('only_old', 0)} dropped vs control, {diff_counts.get('same', 0)} same, {diff_counts.get('changed', 0)} path-changed.
- **AB verdict: {overall}** — {overall_note}

### IS
- Control: {_line(ctrl, 'm_is')}
- PIT cand: {_line(cand, 'm_is')} → **{v_is[0]}**

### OOS (report-only)
- Control: {_line(ctrl, 'm_oos')}
- PIT cand: {_line(cand, 'm_oos')} → **{v_oos[0]}**

### FULL
- Control: {_line(ctrl, 'm_full')}
- PIT cand: {_line(cand, 'm_full')}

## Paths

- Compare: `drive/paul_experiments/rl_pit_vol500k_univ_ab_{STAMP}/compare.html`
- Trade diff: `drive/paul_experiments/rl_pit_vol500k_univ_ab_{STAMP}/trade_diff.html`
- Membership: `drive/paul_experiments/rl_pit_vol500k_univ_ab_{STAMP}/universe_membership.csv`
- BASELINE: `drive/paul_experiments/rl_pit_vol500k_univ_ab_{STAMP}/BASELINE.md`
"""
    (OUT_DIR / "SUMMARY.md").write_text(summary, encoding="utf-8")
    (OUT_DIR / "OVERALL_VERDICT.txt").write_text(f"{overall}\n{overall_note}\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summarize-only", action="store_true")
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cand_syms, buckets, mem_path = build_candidate_universe()
    print(f"membership={mem_path}")
    print(
        f"control={len(load_universe_symbols(CONTROL_UNIV))} "
        f"candidate_pool={len(cand_syms)} "
        f"in_both={len(buckets['in_both'])} "
        f"cand_only={len(buckets['in_candidate_only'])} "
        f"ctrl_only={len(buckets['in_control_only'])}"
    )

    py = _resolve_python()
    if args.summarize_only:
        ctrl = _copy_control()
        arm_dir = OUT_DIR / "runs" / CAND_ID
        closed = _find_latest(arm_dir, "RL_Closed_*.csv")
        if not closed:
            print("ERROR: no candidate Closed for summarize-only")
            return 1
        cand = {
            "arm": {
                "id": CAND_ID,
                "label": f"PIT vol≥{int(PIT_MIN_AVG_VOL/1000)}k×{PIT_AVG_VOL_DAYS}d (wider pool)",
                "role": "candidate",
                "symbols": cand_syms,
            },
            "ok": True,
            "skipped": True,
            "closed": closed,
            "trades": load_trades(closed),
            "stamp": closed.stem.split("_")[-1],
            "summary": _find_latest(arm_dir, "RL_Summary_*.csv"),
            "equity_meta": _find_latest(arm_dir, "RL_EquityMeta_*.csv"),
            "report": _find_latest(arm_dir, "RL_Report_*.csv"),
        }
    else:
        ctrl = _copy_control()
        print(f"control ok={ctrl.get('ok')} stamp={ctrl.get('stamp')} n={len(ctrl.get('trades') or [])}")
        cand = run_candidate(py, cand_syms, args.workers, args.skip_existing)
        print(
            f"candidate ok={cand.get('ok')} stamp={cand.get('stamp')} "
            f"n={len(cand.get('trades') or [])} elapsed={cand.get('elapsed_s', 0):.0f}s "
            f"exit={cand.get('exit_code')}"
        )

    if not ctrl.get("ok") or not cand.get("ok"):
        print("ERROR: arms incomplete")
        return 1

    packed = [pack_result(ctrl), pack_result(cand)]
    by_id = {p["arm"]["id"]: p for p in packed}
    v_is = verdict_vs_control(by_id[CAND_ID], by_id[CONTROL_ID], "m_is")
    v_oos = verdict_vs_control(by_id[CAND_ID], by_id[CONTROL_ID], "m_oos")
    verdicts = {"is": v_is, "oos": v_oos}

    write_metrics_csv(packed, CAND_ID if v_is[0] in ("KEEP", "LEAN KEEP") else CONTROL_ID, OUT_DIR / "metrics_all.csv")
    compare = write_compare_html(packed, verdicts, buckets)
    diff, diff_counts = write_trade_diff(ctrl, cand)
    write_docs(packed, verdicts, buckets, diff_counts, len(cand_syms))

    # ntfy
    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    if ntfy.is_file():
        subprocess.run(
            [
                py,
                str(ntfy),
                "--path",
                str(compare),
                "--path",
                str(diff),
                "-t",
                "RL PIT vol500k AB done",
                "-m",
                f"IS {v_is[0]} / OOS {v_oos[0]} · pool {len(cand_syms)} vs 764 · "
                f"new={diff_counts.get('only_new')} dropped={diff_counts.get('only_old')}",
            ],
            cwd=str(ROOT),
        )

    print(f"compare={compare}")
    print(f"trade_diff={diff}")
    print(f"IS={v_is[0]} OOS={v_oos[0]}")
    print(
        f"diff only_new={diff_counts.get('only_new')} only_old={diff_counts.get('only_old')} "
        f"same={diff_counts.get('same')} changed={diff_counts.get('changed')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
