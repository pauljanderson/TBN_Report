#!/usr/bin/env python3
"""RL universe compare: Paul8 / Paul78 (IS winner-cuts) vs List1 / List2 / house 59.

Paul8 / Paul78 selected on IS full-univ Summary 260828105155 (entry_end=2023-12-31).
That stamp has no OOS — these two arms are live full-history isolated -s runs.
List1 / List2 / house59 reuse the 20260827 isolated Closed (same freeze).

IS for Paul arms is circular (they were cut on IS Paul). OOS is report-only.
Question: does OOS hold up better than List2? Research-only. Not gold / not DailyRun.

Usage:
  python tools/rl_univ_compare_paul8_paul78.py
  python tools/rl_univ_compare_paul8_paul78.py --summarize-only
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
DATA_DIR = ROOT / "data" / "newdata" / "data"
SA = ROOT / "stock_analysis"
STAMP = "20260828"
OUT_DIR = DRIVE / "paul_experiments" / f"rl_univ_compare_paul8_paul78_{STAMP}"
PRIOR = DRIVE / "paul_experiments" / "rl_univ_compare_list1_list2_20260827"
IS_SUMMARY = DRIVE / "RL_Summary_260828105155.csv"
HOUSE_UNIV = DRIVE / "universes" / "RL_universe.csv"
PER_SYMBOL = SA / "Per_Symbol_Optimized_Settings_Approved_Latest.json"
IS_CUT = date(2024, 1, 1)
CONTROL_ID = "house59"

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(DRIVE / "paul_experiments"))
from be_stop_replay_ab import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from compare_format import filter_html_compare_columns  # noqa: E402
from rl_univ_compare_lists import (  # noqa: E402
    LIST1,
    LIST2,
    RL_COMMON_V,
    book_stats,
    build_cmd,
    compare_row,
    fmt_n,
    load_equity_meta,
    load_house_univ,
    load_summary_aggs,
    load_trades,
    pack_result,
    pairwise_delta_row,
    split_is_oos,
    verdict_vs_control,
    write_metrics_csv,
    _find_latest,
    _resolve_python,
)

# Exact IS Paul==8 on RL_Summary_260828105155 (56)
PAUL8 = [
    "ABUS", "AEHR", "AGI", "AGX", "AMRC", "AVAV", "AX", "BBWI", "BELFA", "BLDR",
    "CCJ", "CF", "CRWD", "DXPE", "ENVA", "FANG", "FIVN", "GFI", "GHM", "HCI",
    "HIMS", "HUBS", "IESC", "INOD", "IRMD", "LMAT", "LMB", "LULU", "M", "MELI",
    "MOD", "MTDR", "MU", "NFLX", "NGVC", "NMIH", "NTRA", "NVDA", "P", "PDEX",
    "PSIX", "RNG", "SAIA", "SBS", "SIMO", "SMID", "SNFCA", "STLD", "TALO", "TGB",
    "TGLS", "TPC", "TPL", "WLDN", "WRLD", "ZM",
]
# Paul 7 on the same Summary (46) — Paul78 = Paul8 ∪ these
PAUL7 = [
    "ACAD", "AHCO", "ALNY", "AMTX", "ANDE", "ANIP", "APA", "APPS", "APYX", "ARGX",
    "AVGO", "BBW", "CMCL", "COP", "CORT", "CYTK", "CZR", "DDS", "DVN", "EDVMF",
    "ESOA", "EXEL", "FINMY", "FSI", "GGAL", "IDR", "JBLU", "LAD", "MRNA", "MTZ",
    "NVAX", "OKTA", "PATK", "PAYC", "RDNT", "RMBS", "SHOP", "STX", "TBBK", "TECK",
    "TENB", "UTI", "VRT", "WDAY", "WPM", "XPEL",
]
PAUL78 = PAUL8 + [s for s in PAUL7 if s not in set(PAUL8)]

CANDIDATE_IDS = ("list1", "list2", "paul8", "paul78")
ARM_ORDER = {"list1": 0, "list2": 1, "paul8": 2, "paul78": 3, CONTROL_ID: 4}


def _missing_ohlc(symbols: list[str]) -> list[str]:
    return [s for s in symbols if not (DATA_DIR / f"{s}.csv").is_file()]


def build_arms(house: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "id": "list1",
            "label": "List 1 (95, TPY/avg/WO_MAX 0.30/2.0/1.0)",
            "role": "candidate",
            "symbols": LIST1,
            "csv_name": "list1.csv",
            "reuse_dir": PRIOR / "runs" / "list1",
        },
        {
            "id": "list2",
            "label": "List 2 (93, TPY/avg/WO_MAX 0.30/2.5/2.0)",
            "role": "candidate",
            "symbols": LIST2,
            "csv_name": "list2.csv",
            "reuse_dir": PRIOR / "runs" / "list2",
        },
        {
            "id": "paul8",
            "label": "Paul8 (56, IS Paul==8 on 260828105155)",
            "role": "candidate",
            "symbols": PAUL8,
            "csv_name": "paul8.csv",
            "reuse_dir": None,
        },
        {
            "id": "paul78",
            "label": "Paul78 (102, IS Paul 7–8 on 260828105155)",
            "role": "candidate",
            "symbols": PAUL78,
            "csv_name": "paul78.csv",
            "reuse_dir": None,
        },
        {
            "id": CONTROL_ID,
            "label": "House RL (59, legacy whitelist)",
            "role": "control",
            "symbols": house,
            "csv_name": "rl_universe_59.csv",
            "reuse_dir": PRIOR / "runs" / CONTROL_ID,
        },
    ]


def write_univ_csvs(house: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "list1.csv").write_text("\n".join(LIST1) + "\n", encoding="utf-8")
    (OUT_DIR / "list2.csv").write_text("\n".join(LIST2) + "\n", encoding="utf-8")
    (OUT_DIR / "paul8.csv").write_text("\n".join(PAUL8) + "\n", encoding="utf-8")
    (OUT_DIR / "paul78.csv").write_text("\n".join(PAUL78) + "\n", encoding="utf-8")
    (OUT_DIR / "rl_universe_59.csv").write_text("\n".join(house) + "\n", encoding="utf-8")
    all_syms = list(dict.fromkeys(LIST1 + LIST2 + PAUL8 + PAUL78 + house))
    missing = _missing_ohlc(all_syms)
    overlap = {
        "paul8_list2": sorted(set(PAUL8) & set(LIST2)),
        "paul78_list2": sorted(set(PAUL78) & set(LIST2)),
        "paul8_house": sorted(set(PAUL8) & set(house)),
        "paul78_house": sorted(set(PAUL78) & set(house)),
        "paul8_only_vs_l2": sorted(set(PAUL8) - set(LIST2)),
        "list2_only_vs_p8": sorted(set(LIST2) - set(PAUL8)),
        "paul78_only_vs_l2": sorted(set(PAUL78) - set(LIST2)),
        "list2_only_vs_p78": sorted(set(LIST2) - set(PAUL78)),
        "paul7": list(PAUL7),
    }
    return missing, overlap


def load_reused(arm: dict[str, Any]) -> dict[str, Any]:
    src = arm["reuse_dir"]
    closed = _find_latest(src, "RL_Closed_*.csv")
    if not closed:
        return {"arm": arm, "ok": False, "skipped": True, "trades": [], "stamp": "", "closed": None}
    dest = OUT_DIR / "runs" / arm["id"]
    dest.mkdir(parents=True, exist_ok=True)
    stamp = closed.stem.split("_")[-1]
    for pattern in (
        f"RL_Closed_{stamp}.csv",
        f"RL_Summary_{stamp}.csv",
        f"RL_EquityMeta_{stamp}.csv",
        f"RL_Report_{stamp}.csv",
    ):
        f = src / pattern
        if f.is_file():
            shutil.copy2(f, dest / f.name)
    trades = load_trades(closed)
    return {
        "arm": arm,
        "ok": len(trades) > 0,
        "skipped": True,
        "closed": dest / closed.name if (dest / closed.name).is_file() else closed,
        "trades": trades,
        "stamp": stamp,
        "summary": _find_latest(dest, "RL_Summary_*.csv") or _find_latest(src, "RL_Summary_*.csv"),
        "equity_meta": _find_latest(dest, "RL_EquityMeta_*.csv") or _find_latest(src, "RL_EquityMeta_*.csv"),
        "report": _find_latest(dest, "RL_Report_*.csv") or _find_latest(src, "RL_Report_*.csv"),
        "elapsed_s": 0.0,
    }


def run_arm(py: str, arm: dict[str, Any], workers: int, skip_existing: bool) -> dict[str, Any]:
    if arm.get("reuse_dir") and not skip_existing:
        # Reuse prior isolated stamp unless --force (skip_existing False + reuse still copies)
        pass
    if arm.get("reuse_dir"):
        reused = load_reused(arm)
        if reused.get("ok"):
            return reused
        print(f"[RL-P8] reuse failed for {arm['id']} at {arm['reuse_dir']}", flush=True)
    arm_dir = OUT_DIR / "runs" / arm["id"]
    arm_dir.mkdir(parents=True, exist_ok=True)
    closed = _find_latest(arm_dir, "RL_Closed_*.csv")
    if skip_existing and closed and closed.stat().st_size > 0:
        trades = load_trades(closed)
        if trades:
            stamp = closed.stem.split("_")[-1]
            return {
                "arm": arm,
                "ok": True,
                "skipped": True,
                "closed": closed,
                "trades": trades,
                "stamp": stamp,
                "summary": _find_latest(arm_dir, "RL_Summary_*.csv"),
                "equity_meta": _find_latest(arm_dir, "RL_EquityMeta_*.csv"),
                "report": _find_latest(arm_dir, "RL_Report_*.csv"),
                "elapsed_s": 0.0,
            }
    symbols = ",".join(arm["symbols"])
    cmd = build_cmd(py, arm_dir, workers, symbols)
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
        "summary": _find_latest(arm_dir, "RL_Summary_*.csv"),
        "equity_meta": _find_latest(arm_dir, "RL_EquityMeta_*.csv"),
        "report": _find_latest(arm_dir, "RL_Report_*.csv"),
    }


def write_compare_html(
    packed: list[dict[str, Any]],
    overlap: dict[str, list[str]],
    verdicts: dict[str, dict[str, tuple[str, str]]],
) -> Path:
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
            ("Δ Sheet $ vs 59", "num"),
            ("Δ Avg% vs 59", "num"),
            ("Δ WR vs 59", "num"),
            ("Δ PF vs 59", "num"),
            ("Δ Ann ROR vs 59", "num"),
            ("Δ Max DD vs 59", "num"),
            ("Δ Calmar vs 59", "num"),
            ("IS pick", "text"),
        ]
    )
    th = "".join(sortable_th(a, b) for a, b in th_cols)
    sections = []
    for split_key, title in (("m_is", "IS"), ("m_oos", "OOS (report-only)"), ("m_full", "FULL book")):
        body = "".join(
            compare_row(p, split_key, baseline, "", CONTROL_ID) for p in packed
        )
        note = (
            "Paul/FIT/Sharpe/UW from host Summary + EquityMeta (full history only)."
            if split_key == "m_full"
            else "Closed overlay at $47,500 cash / $500k initial. Paul/FIT N/A on slices."
        )
        extra = ""
        if split_key == "m_is":
            extra = " IS for Paul8/Paul78 is circular (cut on this IS Paul). Do not adopt from IS rank."
        elif split_key == "m_oos":
            extra = " OOS is the question vs List2 and vs house 59. Do not retune. Do not drop names from OOS."
        sections.append(
            f'<section><h2>RL universe compare — {title}</h2>'
            f'<p class="muted">Split=<strong>{title.split()[0]}</strong>. Δ vs house 59 (legacy whitelist, not honest OOS gold). {note}{extra} '
            f"Click column headers to sort.</p>"
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{th}</tr></thead>'
            f"<tbody>{body}</tbody></table></div></section>"
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
        ("paul8 − list2", by_id["list2"], by_id["paul8"]),
        ("paul78 − list2", by_id["list2"], by_id["paul78"]),
        ("paul8 − house59", by_id[CONTROL_ID], by_id["paul8"]),
        ("paul78 − house59", by_id[CONTROL_ID], by_id["paul78"]),
        ("list2 − house59", by_id[CONTROL_ID], by_id["list2"]),
        ("list1 − house59", by_id[CONTROL_ID], by_id["list1"]),
        ("paul78 − paul8", by_id["paul8"], by_id["paul78"]),
        ("list2 − list1", by_id["list1"], by_id["list2"]),
    ]
    pw_sections = []
    for split_key, title in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
        rows = "".join(pairwise_delta_row(a, b, split_key, lbl) for lbl, a, b in pairs)
        pw_sections.append(
            f'<section><h2>Pairwise deltas — {title}</h2>'
            f'<p class="muted">Read <code>paul8 − list2</code> on OOS first: does the tighter Paul cut hold up better than List2?</p>'
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{pw_th}</tr></thead>'
            f"<tbody>{rows}</tbody></table></div></section>"
        )

    exit_rows = []
    for p in packed:
        ex = p["m_full"]["exits"]
        tot = max(p["m_full"]["n"], 1)
        exit_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(p['arm']['label'])}</td>"
            f"<td>{ex.get('TARGET', 0)} ({100*ex.get('TARGET',0)/tot:.1f}%)</td>"
            f"<td>{ex.get('STOP_LOSS', 0)} ({100*ex.get('STOP_LOSS',0)/tot:.1f}%)</td>"
            f"<td>{ex.get('GAP_DOWN', 0)}</td>"
            f"<td>{ex.get('GAP_UP', 0)}</td>"
            f"<td>{ex.get('TIME', 0)}</td>"
            "</tr>"
        )

    v_lis = []
    for aid in CANDIDATE_IDS:
        vis, nis = verdicts[aid]["is_vs59"]
        voos, noos = verdicts[aid]["oos_vs59"]
        vl2, nl2 = verdicts[aid]["oos_vs_list2"]
        v_lis.append(
            f"<li><strong>{html_mod.escape(aid)}</strong> vs house59 — IS: {html_mod.escape(vis)} ({html_mod.escape(nis)}); "
            f"OOS: {html_mod.escape(voos)} ({html_mod.escape(noos)}). "
            f"OOS vs List2: {html_mod.escape(vl2)} ({html_mod.escape(nl2)})</li>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL Paul8 / Paul78 vs List1 / List2 / 59 — {STAMP}</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; --accent:#5b9fd4; --ctrl:#243044; }}
*{{box-sizing:border-box}}
body{{margin:0;font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header{{padding:1.25rem 1rem 0.5rem;max-width:1400px;margin:0 auto}}
h1{{font-size:1.35rem;margin:0 0 .35rem}}
h2{{font-size:1.05rem;margin:1.25rem 0 .4rem;color:var(--accent)}}
.muted{{color:var(--muted);font-size:.92rem}}
.callout{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem;margin:.75rem 0}}
.warn{{border-color:#b45309}}
main{{max-width:1400px;margin:0 auto;padding:0 1rem 2.5rem}}
section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem 1rem;margin:1rem 0}}
.table-wrap{{overflow-x:auto;-webkit-overflow-scrolling:touch}}
table{{border-collapse:collapse;width:100%;font-size:.78rem;min-width:1100px}}
th,td{{border-bottom:1px solid var(--line);padding:.35rem .4rem;text-align:right}}
th:first-child,td:first-child{{text-align:left}}
tr.ctrl-row{{background:var(--ctrl)}}
{SORTABLE_TH_CSS.replace('th.sortable-th:hover{{background:#e8e4d8}}', 'th.sortable-th:hover{{background:#2a3545}}')}
@media (max-width:700px){{ table{{font-size:.72rem;min-width:900px}} }}
</style>
</head>
<body>
<header>
<h1>RL universe — Paul8 (56) / Paul78 (102) vs List1 / List2 / House 59</h1>
<p class="muted">Stamp <code>rl_univ_compare_paul8_paul78_{STAMP}</code>. Universe identity only (not a knob AB).
House freeze: dip=1.055, expansion=1.163, rl_stop_pct=0.934, target=1.20, too_high=off, brt_zones=false, cash $47.5k.
IS = entry &lt; 2024-01-01; OOS ≥ 2024-01-01 <strong>report-only</strong>. Research-only — not gold / not DailyRun.
Click column headers to sort.</p>
</header>
<main>
<div class="callout warn">
<strong>Selection honesty.</strong> Paul8 / Paul78 are integer Paul winner-cuts on IS Summary
<code>260828105155</code> (full univ, <code>entry_end_date=2023-12-31</code>). That stamp has no OOS —
these two arms are new full-history isolated <code>-s</code> runs. List1 / List2 / house59 reuse
<code>rl_univ_compare_list1_list2_20260827</code> (same freeze). House 59 is a legacy full-history
whitelist, not an honest OOS gold. Do not retune knobs. Do not drop OOS losers.
</div>
<div class="callout">
<strong>List1 gates (IS):</strong> 0.30 TPY, 2.0% avg PnL, 1.0% avg PnL without biggie.<br/>
<strong>List2 gates (IS):</strong> 0.30 TPY, 2.5% avg PnL, 2.0% avg PnL without biggie.<br/>
<strong>Paul8:</strong> {len(PAUL8)} names, PAUL_SCORE==8 on 260828105155.<br/>
<strong>Paul78:</strong> {len(PAUL78)} names, PAUL_SCORE in {{7,8}} (Paul8 + {len(PAUL7)} Paul7).<br/>
<strong>Overlap Paul8∩List2:</strong> {len(overlap['paul8_list2'])} &nbsp;|&nbsp;
<strong>Paul8 not in List2:</strong> {len(overlap['paul8_only_vs_l2'])} — {html_mod.escape(", ".join(overlap['paul8_only_vs_l2']))}<br/>
<strong>Overlap Paul78∩List2:</strong> {len(overlap['paul78_list2'])} &nbsp;|&nbsp;
<strong>Paul78 not in List2:</strong> {len(overlap['paul78_only_vs_l2'])} — {html_mod.escape(", ".join(overlap['paul78_only_vs_l2']))}<br/>
<strong>List2 not in Paul78:</strong> {len(overlap['list2_only_vs_p78'])} — {html_mod.escape(", ".join(overlap['list2_only_vs_p78']))}
<ul>{"".join(v_lis)}</ul>
</div>
{"".join(sections)}
{"".join(pw_sections)}
<section>
<h2>Exit mix (FULL)</h2>
<p class="muted">Counts and % from Closed EXIT_TYPE.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>
{sortable_th("Arm", "text")}{sortable_th("TARGET", "text")}{sortable_th("STOP_LOSS", "text")}
{sortable_th("GAP_DOWN", "num")}{sortable_th("GAP_UP", "num")}{sortable_th("TIME", "num")}
</tr></thead><tbody>{"".join(exit_rows)}</tbody></table></div>
</section>
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path = OUT_DIR / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def _md_split(p: dict[str, Any], key: str) -> str:
    m = p[key]
    return (
        f"N={m['n']} WR={m['wr']:.1f}% Avg={m['avg_pnl']:.2f}% WO_MAX={m['wo_max']:.2f}% "
        f"PF={m['pf']:.2f} AnnROR={fmt_n(m['ann_ror'], 2)} MaxDD={fmt_n(m['max_dd'], 2)}"
    )


def write_baseline(packed: list[dict[str, Any]], missing: list[str], overlap: dict[str, list[str]]) -> None:
    lines = [
        f"# BASELINE — `rl_univ_compare_paul8_paul78_{STAMP}`",
        "",
        "**Universe compare** (not a stop/knob AB). Research candidate ≠ gold ≠ DailyRun.",
        "",
        "Paul8 / Paul78 = **in-sample Paul winner-cuts** on `RL_Summary_260828105155` ",
        "(full univ, `entry_end_date=2023-12-31`). That Closed has **no OOS**. ",
        "These two arms are isolated full-history `-s` runs under the same freeze as List1/List2/house59.",
        "",
        "## House RL freeze (identical all arms)",
        "",
        "| Knob | Value | Source |",
        "|------|-------|--------|",
        "| `rl_dip_pct` | **1.055** | `run_rl.bat` / prior list compare |",
        "| `rl_expansion` | **1.163** | `RLConfig` |",
        "| `rl_stop_pct` | **0.934** | `RLConfig` |",
        "| `rl_target_pct` | **1.20** | `RLConfig` |",
        "| `rl_too_high` | **0 / off** | `run_rl.bat` |",
        "| `brt_zones` | **false** | `run_rl.bat` |",
        "| cash | **$47,500** | house RL |",
        "",
        "Do **not** retune knobs on this stamp. Do **not** drop names after seeing OOS.",
        "",
        "## Universes",
        "",
        f"- **List1** (95): IS full-univ screen **0.30 TPY, 2.0% avg PnL, 1.0% WO_MAX**. Reuse `260827221824`.",
        f"- **List2** (93): IS screen **0.30 TPY, 2.5% avg PnL, 2.0% WO_MAX** (List1 minus IDR, RDNT). Reuse `260827221824`.",
        f"- **Paul8** ({len(PAUL8)}): `PAUL_SCORE==8` on `260828105155`. Live isolated run.",
        f"- **Paul78** ({len(PAUL78)}): `PAUL_SCORE` in {{7,8}} on the same Summary (Paul8 + {len(PAUL7)} Paul7). Live isolated run.",
        f"- **House59**: `drive/universes/RL_universe.csv` — **legacy full-history whitelist**, not OOS-validated. Reuse `260827221824`.",
        "",
        f"- Paul8 ∩ List2 = {len(overlap['paul8_list2'])}; Paul8 not in List2 = {', '.join(overlap['paul8_only_vs_l2']) or '(none)'}",
        f"- Paul78 ∩ List2 = {len(overlap['paul78_list2'])}; Paul78 not in List2 = {', '.join(overlap['paul78_only_vs_l2']) or '(none)'}",
        f"- List2 not in Paul78 = {', '.join(overlap['list2_only_vs_p78']) or '(none)'}",
        "",
        "## IS / OOS",
        "",
        "- Split: IS = `entry_date < 2024-01-01`; OOS = `entry_date >= 2024-01-01`",
        "- Paul8 / Paul78 IS metrics are **circular** (cut on IS Paul). Use IS only as context.",
        "- OOS is **report-only**. Question: does either Paul cut hold up better than List2?",
        "- House 59 looking better on OOS is unsurprising (selected on full history).",
        "",
        "## Missing OHLC",
        "",
        f"- {', '.join(missing) if missing else 'None — all symbols present under data/newdata/data/'}",
        "",
        "## Arms",
        "",
        "| Arm | Stamp | N_full | OK |",
        "|-----|-------|--------|-----|",
    ]
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
            "- `list1.csv` / `list2.csv` / `paul8.csv` / `paul78.csv` / `rl_universe_59.csv`",
            "- `compare.html` — sortable IS / OOS / FULL + pairwise vs List2 and house 59",
            "- `metrics_all.csv`",
            "- `SUMMARY.md`",
            "- `runs/<arm>/RL_*`",
        ]
    )
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_summary(
    packed: list[dict[str, Any]],
    overlap: dict[str, list[str]],
    verdicts: dict[str, dict[str, tuple[str, str]]],
) -> None:
    by_id = {p["arm"]["id"]: p for p in packed}
    lines = [
        f"# SUMMARY — `rl_univ_compare_paul8_paul78_{STAMP}`",
        "",
        "**Universe compare.** Research only. Not gold / not DailyRun.",
        "",
        "Paul8 / Paul78 = IS Paul winner-cuts on `260828105155`. OOS report-only. "
        "House 59 is a legacy whitelist. Question: OOS vs List2.",
        "",
        "## Freeze",
        "",
        "`rl_dip_pct=1.055`, `rl_expansion=1.163`, `rl_stop_pct=0.934`, `rl_target_pct=1.20`, "
        "`rl_too_high=0`, `brt_zones=false`, cash $47.5k.",
        "",
        f"**Paul8 ∩ List2:** {len(overlap['paul8_list2'])}  |  **Paul8 not in List2:** {', '.join(overlap['paul8_only_vs_l2']) or '(none)'}",
        f"**Paul78 ∩ List2:** {len(overlap['paul78_list2'])}  |  **List2 not in Paul78:** {', '.join(overlap['list2_only_vs_p78']) or '(none)'}",
        "",
        "## IS (circular for Paul arms)",
        "",
    ]
    for aid in ("list1", "list2", "paul8", "paul78", CONTROL_ID):
        p = by_id[aid]
        lines.append(f"- **{aid}** ({len(p['arm']['symbols'])}): {_md_split(p, 'm_is')}")
    lines.extend(["", "## OOS (report-only)", ""])
    for aid in ("list1", "list2", "paul8", "paul78", CONTROL_ID):
        p = by_id[aid]
        lines.append(f"- **{aid}**: {_md_split(p, 'm_oos')}")
    lines.extend(["", "## Verdicts", ""])
    for aid in CANDIDATE_IDS:
        vis, nis = verdicts[aid]["is_vs59"]
        voos, noos = verdicts[aid]["oos_vs59"]
        vl2, nl2 = verdicts[aid]["oos_vs_list2"]
        lines.append(
            f"- **{aid}** vs house59 IS `{vis}` ({nis}); OOS `{voos}` ({noos}). "
            f"OOS vs List2 `{vl2}` ({nl2})"
        )
    l2o = by_id["list2"]["m_oos"]
    p8o = by_id["paul8"]["m_oos"]
    p78o = by_id["paul78"]["m_oos"]
    better_p8 = p8o["avg_pnl"] > l2o["avg_pnl"] + 0.05 and p8o["pf"] >= l2o["pf"] - 0.03
    better_p78 = p78o["avg_pnl"] > l2o["avg_pnl"] + 0.05 and p78o["pf"] >= l2o["pf"] - 0.03
    if better_p8 or better_p78:
        who = []
        if better_p8:
            who.append("Paul8")
        if better_p78:
            who.append("Paul78")
        oos_line = (
            f"**OOS vs List2:** {', '.join(who)} prints higher Avg%/PF than List2 on this holdout — "
            "still a winner-cut, still not gold. HOLD unless walk-forward / tradable tape next. Do not retune."
        )
    else:
        oos_line = (
            "**OOS vs List2:** neither Paul cut clearly beats List2 on quality (Avg% / PF). "
            "DISMISS as a rescue of the IS name-list process. Next: tradable tape, not another Paul cut. "
            "Do not retune. Do not adopt house 59 as from-scratch gold."
        )
    lines.extend(["", "## Bottom line", "", oos_line, ""])
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def summarize(
    packed: list[dict[str, Any]],
    missing: list[str],
    overlap: dict[str, list[str]],
) -> dict[str, Any]:
    by_id = {p["arm"]["id"]: p for p in packed}
    control = by_id[CONTROL_ID]
    list2 = by_id["list2"]
    verdicts: dict[str, dict[str, tuple[str, str]]] = {}
    for aid in CANDIDATE_IDS:
        verdicts[aid] = {
            "is_vs59": verdict_vs_control(by_id[aid], control, "m_is"),
            "oos_vs59": verdict_vs_control(by_id[aid], control, "m_oos"),
            "oos_vs_list2": (
                ("n/a", "self")
                if aid == "list2"
                else verdict_vs_control(by_id[aid], list2, "m_oos")
            ),
        }
    write_compare_html(packed, overlap, verdicts)
    write_metrics_csv(packed, "", OUT_DIR / "metrics_all.csv")
    write_baseline(packed, missing, overlap)
    write_summary(packed, overlap, verdicts)
    print(f"[RL-P8] Wrote {OUT_DIR / 'compare.html'}", flush=True)
    return {"verdicts": verdicts, "packed": packed}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--force", action="store_true", help="Re-run Paul arms even if Closed exists")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    skip_existing = (args.skip_existing or args.summarize_only) and not args.force

    house = load_house_univ()
    if not house:
        print("[RL-P8] Missing house universe", flush=True)
        return 1
    if len(PAUL8) != 56 or len(PAUL78) != 102:
        print("[RL-P8] Unexpected Paul list lengths", flush=True)
        return 1
    if not set(PAUL8).issubset(set(PAUL78)):
        print("[RL-P8] Paul8 not subset of Paul78", flush=True)
        return 1

    arms = build_arms(house)
    missing, overlap = write_univ_csvs(house)
    print(f"[RL-P8] Stamp {OUT_DIR}", flush=True)
    print(
        f"[RL-P8] L1={len(LIST1)} L2={len(LIST2)} P8={len(PAUL8)} P78={len(PAUL78)} "
        f"house={len(house)} missing_ohlc={missing}",
        flush=True,
    )
    if missing:
        print("[RL-P8] Missing OHLC — abort", flush=True)
        return 1

    py = _resolve_python()
    runs: list[dict[str, Any]] = []
    if args.summarize_only:
        for arm in arms:
            arm_dir = OUT_DIR / "runs" / arm["id"]
            closed = _find_latest(arm_dir, "RL_Closed_*.csv")
            src = arm.get("reuse_dir")
            if not closed and src:
                closed = _find_latest(src, "RL_Closed_*.csv")
            if not closed:
                print(f"[RL-P8] Missing Closed for {arm['id']}", flush=True)
                return 1
            trades = load_trades(closed)
            runs.append(
                {
                    "arm": arm,
                    "ok": len(trades) > 0,
                    "skipped": True,
                    "closed": closed,
                    "trades": trades,
                    "stamp": closed.stem.split("_")[-1],
                    "summary": _find_latest(arm_dir, "RL_Summary_*.csv")
                    or ( _find_latest(src, "RL_Summary_*.csv") if src else None),
                    "equity_meta": _find_latest(arm_dir, "RL_EquityMeta_*.csv")
                    or ( _find_latest(src, "RL_EquityMeta_*.csv") if src else None),
                    "report": _find_latest(arm_dir, "RL_Report_*.csv")
                    or ( _find_latest(src, "RL_Report_*.csv") if src else None),
                }
            )
    else:
        live = [a for a in arms if not a.get("reuse_dir") or args.force]
        reused_arms = [a for a in arms if a.get("reuse_dir") and not args.force]
        for arm in reused_arms:
            run = load_reused(arm)
            print(
                f"[RL-P8] {arm['id']} reuse ok={run['ok']} n={len(run['trades'])} stamp={run.get('stamp')}",
                flush=True,
            )
            runs.append(run)
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
            futs = {ex.submit(run_arm, py, arm, args.workers, skip_existing): arm for arm in live}
            for fut in as_completed(futs):
                arm = futs[fut]
                run = fut.result()
                print(
                    f"[RL-P8] {arm['id']} ok={run['ok']} n={len(run['trades'])} "
                    f"elapsed={run.get('elapsed_s', 0):.0f}s skipped={run.get('skipped')}",
                    flush=True,
                )
                runs.append(run)

    runs.sort(key=lambda r: ARM_ORDER.get(r["arm"]["id"], 99))
    if not all(r.get("ok") for r in runs):
        print("[RL-P8] One or more arms failed", flush=True)
        for r in runs:
            print(f"  {r['arm']['id']}: ok={r.get('ok')} exit={r.get('exit_code')}", flush=True)
        if not any(r.get("trades") for r in runs):
            return 1

    packed = [pack_result(r) for r in runs]
    result = summarize(packed, missing, overlap)

    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    if ntfy.is_file():
        p8 = next(p for p in packed if p["arm"]["id"] == "paul8")
        l2 = next(p for p in packed if p["arm"]["id"] == "list2")
        subprocess.run(
            [
                py,
                str(ntfy),
                "--path",
                str(OUT_DIR / "compare.html"),
                "-t",
                "RL Paul8/78 vs List2 vs 59",
                "-m",
                (
                    f"OOS Paul8 Avg={p8['m_oos']['avg_pnl']:.2f}% PF={p8['m_oos']['pf']:.2f} "
                    f"vs List2 Avg={l2['m_oos']['avg_pnl']:.2f}% PF={l2['m_oos']['pf']:.2f}"
                ),
            ],
            cwd=str(ROOT),
        )
    return 0 if all(r.get("ok") for r in packed) else 1


if __name__ == "__main__":
    raise SystemExit(main())
