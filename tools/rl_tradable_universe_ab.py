#!/usr/bin/env python3
"""RL from-scratch baseline: 2010 / ADV$2m tradable tape vs house 59 vs List2.

Universe identity only. Same freeze as list/Paul compares (dip=1.055).
Tradable names from VZ_tradable_2010_adv2m_universe.csv — OHLC traits as-of
2023-12-29, no RL PnL / Paul / FIT.

House 59 = legacy full-history whitelist (not honest OOS gold).
List2 = IS TPY/avg/WO_MAX winner-cut (context, not control).

OOS report-only. Research-only. Not gold. Do not overwrite RL_universe.csv.

Usage:
  python tools/rl_tradable_universe_ab.py
  python tools/rl_tradable_universe_ab.py --summarize-only
"""
from __future__ import annotations

import argparse
import html as html_mod
import shutil
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
DATA_DIR = ROOT / "data" / "newdata" / "data"
STAMP = "20260828"
OUT_DIR = DRIVE / "paul_experiments" / f"rl_tradable_2010_adv2m_{STAMP}"
PRIOR = DRIVE / "paul_experiments" / "rl_univ_compare_list1_list2_20260827"
UNIVERSE_CSV = DRIVE / "universes" / "VZ_tradable_2010_adv2m_universe.csv"
CONTROL_ID = "house59"

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(DRIVE / "paul_experiments"))
from be_stop_replay_ab import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from compare_format import filter_html_compare_columns  # noqa: E402
from rl_univ_compare_lists import (  # noqa: E402
    LIST2,
    build_cmd,
    compare_row,
    fmt_n,
    load_house_univ,
    load_trades,
    pack_result,
    pairwise_delta_row,
    verdict_vs_control,
    write_metrics_csv,
    _find_latest,
    _resolve_python,
)
from vz_is_paul_universe_ab import load_universe_symbols  # noqa: E402

CANDIDATE_IDS = ("tradable", "list2")
ARM_ORDER = {"tradable": 0, "list2": 1, CONTROL_ID: 2}


def _copy_reuse(arm: dict[str, Any]) -> dict[str, Any]:
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


def run_live(py: str, arm: dict[str, Any], workers: int, skip_existing: bool) -> dict[str, Any]:
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
    cmd = build_cmd(py, arm_dir, workers, ",".join(arm["symbols"]))
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


def _md_split(p: dict[str, Any], key: str) -> str:
    m = p[key]
    return (
        f"N={m['n']} WR={m['wr']:.1f}% Avg={m['avg_pnl']:.2f}% WO_MAX={m['wo_max']:.2f}% "
        f"PF={m['pf']:.2f} AnnROR={fmt_n(m['ann_ror'], 2)} MaxDD={fmt_n(m['max_dd'], 2)}"
    )


def write_compare_html(
    packed: list[dict[str, Any]],
    overlap: dict[str, list[str]],
    verdicts: dict[str, dict[str, tuple[str, str]]],
    n_trad: int,
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
        body = "".join(compare_row(p, split_key, baseline, "", CONTROL_ID) for p in packed)
        note = (
            "Paul/FIT/Sharpe/UW from host Summary + EquityMeta (full history only)."
            if split_key == "m_full"
            else "Closed overlay at $47,500 cash / $500k initial. Paul/FIT N/A on slices."
        )
        extra = ""
        if split_key == "m_oos":
            extra = (
                " Do not KEEP house 59 because OOS looks prettier (full-history whitelist). "
                "Do not retune knobs or drop names."
            )
        sections.append(
            f'<section><h2>RL tradable tape — {title}</h2>'
            f'<p class="muted">Split=<strong>{title.split()[0]}</strong>. Δ vs house 59 (legacy whitelist). {note}{extra} '
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
        ("tradable − house59", by_id[CONTROL_ID], by_id["tradable"]),
        ("tradable − list2", by_id["list2"], by_id["tradable"]),
        ("list2 − house59", by_id[CONTROL_ID], by_id["list2"]),
    ]
    pw_sections = []
    for split_key, title in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
        rows = "".join(pairwise_delta_row(a, b, split_key, lbl) for lbl, a, b in pairs)
        pw_sections.append(
            f'<section><h2>Pairwise deltas — {title}</h2>'
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
        v_lis.append(
            f"<li><strong>{html_mod.escape(aid)}</strong> vs house59 — IS: {html_mod.escape(vis)} ({html_mod.escape(nis)}); "
            f"OOS: {html_mod.escape(voos)} ({html_mod.escape(noos)}). Auto-KEEP/DISMISS vs 59 on OOS is not an adopt signal.</li>"
        )

    fail59 = overlap["house_fail"]
    fail_l2 = overlap["list2_fail"]
    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL tradable 2010 / ADV$2m vs house 59 — {STAMP}</title>
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
<h1>RL from-scratch baseline — tradable tape ({n_trad}) vs House 59 vs List2</h1>
<p class="muted">Stamp <code>rl_tradable_2010_adv2m_{STAMP}</code>. Universe identity only (not a knob AB).
House freeze: dip=1.055, expansion=1.163, rl_stop_pct=0.934, target=1.20, too_high=off, brt_zones=false, cash $47.5k.
Tradable screen: first bar ≤ 2010-01-04; as-of 2023-12-29 Close ≥ $5; 20-session ADV$ ≥ $2m. No RL PnL / Paul / FIT.
IS = entry &lt; 2024-01-01; OOS ≥ 2024-01-01 <strong>report-only</strong>. Research-only — not gold / not DailyRun.
Click column headers to sort.</p>
</header>
<main>
<div class="callout warn">
<strong>From scratch.</strong> The tradable tape is the honest parent universe (same recipe as VZ/BRT).
House 59 is a legacy full-history whitelist — do not KEEP it because OOS looks prettier.
List2 is an IS TPY/avg/WO_MAX winner-cut — context only. Do not overwrite
<code>drive/universes/RL_universe.csv</code>. Do not retune knobs on OOS.
</div>
<div class="callout">
<strong>Tradable ∩ House59:</strong> {len(overlap['trad_house'])} / 59
&nbsp;|&nbsp; <strong>House59 fail screen ({len(fail59)}):</strong> {html_mod.escape(", ".join(fail59))}<br/>
<strong>Tradable ∩ List2:</strong> {len(overlap['trad_list2'])} / 93
&nbsp;|&nbsp; <strong>List2 fail screen ({len(fail_l2)}):</strong> {html_mod.escape(", ".join(fail_l2))}
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


def write_baseline(
    packed: list[dict[str, Any]],
    overlap: dict[str, list[str]],
    n_trad: int,
    missing: list[str],
) -> None:
    by_id = {p["arm"]["id"]: p for p in packed}
    lines = [
        f"# BASELINE — `rl_tradable_2010_adv2m_{STAMP}`",
        "",
        "**Status:** RESEARCH only. **Not gold. Not DailyRun-wired.** Production `RL_universe.csv` was **not** overwritten.",
        "",
        "## Hypothesis (one knob)",
        "",
        "Universe identity only. Same RL freeze as `rl_univ_compare_list1_list2_20260827` / Paul8 stamp (`rl_dip_pct=1.055`).",
        f"Compare the **59-name production whitelist** vs a **{n_trad}-name 2010-tradable tape** ",
        "(listing age + price + dollar volume, no RL PnL / Paul / FIT). List2 IS winner-cut is a third column for context.",
        "",
        "## Screen freeze (selection honesty)",
        "",
        f"Universe file: `drive/universes/VZ_tradable_2010_adv2m_universe.csv` (reuse VZ/BRT tradable CSV). Copy in stamp: `tradable.csv`.",
        "",
        "- First bar on or before **2010-01-04**",
        "- As-of **2023-12-29**: Close ≥ **$5**; 20-session ADV$ ≥ **$2,000,000**",
        f"- **{n_trad}** names. Traits only — not an RL winner cut.",
        "",
        f"### {len(overlap['house_fail'])} of 59 fail this screen",
        "",
        "These stay on the **59-name production whitelist** and are **not** on the trait list:",
        "",
        f"`{', '.join(overlap['house_fail'])}`",
        "",
        "Do not treat the 59-name book as an honest 2010-tradable tape. It is a whitelist. Do not KEEP 59 because it looks prettier (selection).",
        "",
        "## Engine freeze (identical all arms)",
        "",
        "| Knob | Value |",
        "|------|-------|",
        "| `rl_dip_pct` | **1.055** |",
        "| `rl_expansion` | **1.163** |",
        "| `rl_stop_pct` | **0.934** |",
        "| `rl_target_pct` | **1.20** |",
        "| `rl_too_high` | **0 / off** |",
        "| `brt_zones` | **false** |",
        "| cash | **$47,500** |",
        "",
        "Do **not** retune knobs on this stamp. Do **not** drop names after seeing OOS.",
        "",
        "## Arms",
        "",
        f"- **Tradable {n_trad}**: live isolated `-s` on the trait list.",
        "- **List2** (93): IS 0.30 TPY / 2.5% avg / 2.0% WO_MAX winner-cut. Reuse `260827221824`. Context only.",
        "- **House59**: `drive/universes/RL_universe.csv`. Reuse `260827221824`. Legacy whitelist.",
        "",
        f"- Tradable ∩ House59 = {len(overlap['trad_house'])}",
        f"- Tradable ∩ List2 = {len(overlap['trad_list2'])}",
        f"- List2 fail screen ({len(overlap['list2_fail'])}): {', '.join(overlap['list2_fail'])}",
        "",
        "## IS / OOS",
        "",
        "- Split: IS = `entry_date < 2024-01-01`; OOS = `entry_date >= 2024-01-01`",
        "- OOS is **report-only**. Do not retune universe or knobs.",
        "- House 59 OOS looking better is unsurprising (selected on full history).",
        "",
        "## Missing OHLC",
        "",
        f"- {', '.join(missing) if missing else 'None'}",
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
            "## Snapshot",
            "",
            "| Book | IS | OOS | FULL |",
            "|------|----|-----|------|",
        ]
    )
    for aid in ("tradable", "list2", CONTROL_ID):
        p = by_id[aid]
        lines.append(
            f"| {aid} | {_md_split(p, 'm_is')} | {_md_split(p, 'm_oos')} | {_md_split(p, 'm_full')} |"
        )
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            "- `tradable.csv` / `list2.csv` / `rl_universe_59.csv`",
            "- `compare.html` — sortable IS / OOS / FULL + pairwise",
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
    n_trad: int,
) -> str:
    by_id = {p["arm"]["id"]: p for p in packed}
    t, l2, h = by_id["tradable"], by_id["list2"], by_id[CONTROL_ID]
    lines = [
        f"# SUMMARY — `rl_tradable_2010_adv2m_{STAMP}`",
        "",
        f"**From-scratch baseline.** Tradable tape ({n_trad}) vs house 59 whitelist vs List2 IS cut.",
        "Research only. Not gold / not DailyRun. Do not overwrite `RL_universe.csv`.",
        "",
        "## Freeze",
        "",
        "`rl_dip_pct=1.055`, `rl_expansion=1.163`, `rl_stop_pct=0.934`, `rl_target_pct=1.20`, "
        "`rl_too_high=0`, `brt_zones=false`, cash $47.5k.",
        "",
        f"**House59 fail screen ({len(overlap['house_fail'])}):** {', '.join(overlap['house_fail'])}",
        "",
        "## IS",
        "",
    ]
    for aid in ("tradable", "list2", CONTROL_ID):
        lines.append(f"- **{aid}** ({len(by_id[aid]['arm']['symbols'])}): {_md_split(by_id[aid], 'm_is')}")
    lines.extend(["", "## OOS (report-only)", ""])
    for aid in ("tradable", "list2", CONTROL_ID):
        lines.append(f"- **{aid}**: {_md_split(by_id[aid], 'm_oos')}")
    lines.extend(["", "## Auto-verdicts vs house 59 (not adopt)", ""])
    for aid in CANDIDATE_IDS:
        vis, nis = verdicts[aid]["is_vs59"]
        voos, noos = verdicts[aid]["oos_vs59"]
        lines.append(f"- **{aid}** IS `{vis}` ({nis}); OOS `{voos}` ({noos})")

    toos, hoos = t["m_oos"], h["m_oos"]
    bottom = (
        f"**DISMISS gold / KEEP research tape.** Tradable OOS Avg {toos['avg_pnl']:.2f}% / PF {toos['pf']:.2f} / "
        f"WR {toos['wr']:.1f}% vs house 59 Avg {hoos['avg_pnl']:.2f}% / PF {hoos['pf']:.2f} / WR {hoos['wr']:.1f}%. "
        "The 59 looking prettier on OOS is full-history selection, not an adopt-59 signal. "
        f"List2 OOS Avg {l2['m_oos']['avg_pnl']:.2f}% remains a failed IS winner-cut. "
        "Tradable quality is the honest from-scratch book (usually lower headline than a whitelist). "
        "Not gold. Do not wire DailyRun. Do not retune. Next rigor: walk-forward of a name rule, or random same-N sanity — not another Paul cut."
    )
    lines.extend(["", "## Bottom line", "", bottom, ""])
    text = "\n".join(lines) + "\n"
    (OUT_DIR / "SUMMARY.md").write_text(text, encoding="utf-8")
    return bottom


def summarize(
    packed: list[dict[str, Any]],
    overlap: dict[str, list[str]],
    n_trad: int,
    missing: list[str],
) -> dict[str, Any]:
    by_id = {p["arm"]["id"]: p for p in packed}
    control = by_id[CONTROL_ID]
    verdicts: dict[str, dict[str, tuple[str, str]]] = {}
    for aid in CANDIDATE_IDS:
        verdicts[aid] = {
            "is_vs59": verdict_vs_control(by_id[aid], control, "m_is"),
            "oos_vs59": verdict_vs_control(by_id[aid], control, "m_oos"),
        }
    write_compare_html(packed, overlap, verdicts, n_trad)
    write_metrics_csv(packed, "", OUT_DIR / "metrics_all.csv")
    write_baseline(packed, overlap, n_trad, missing)
    bottom = write_summary(packed, overlap, verdicts, n_trad)
    print(f"[RL-TRAD] Wrote {OUT_DIR / 'compare.html'}", flush=True)
    return {"verdicts": verdicts, "packed": packed, "bottom": bottom}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    skip_existing = (args.skip_existing or args.summarize_only) and not args.force

    trad = load_universe_symbols(UNIVERSE_CSV)
    house = load_house_univ()
    if not trad or not house:
        print("[RL-TRAD] Missing tradable or house universe", flush=True)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(UNIVERSE_CSV, OUT_DIR / "tradable.csv")
    (OUT_DIR / "list2.csv").write_text("\n".join(LIST2) + "\n", encoding="utf-8")
    (OUT_DIR / "rl_universe_59.csv").write_text("\n".join(house) + "\n", encoding="utf-8")

    missing = [s for s in trad if not (DATA_DIR / f"{s}.csv").is_file()]
    overlap = {
        "trad_house": sorted(set(trad) & set(house)),
        "trad_list2": sorted(set(trad) & set(LIST2)),
        "house_fail": sorted(set(house) - set(trad)),
        "list2_fail": sorted(set(LIST2) - set(trad)),
    }
    print(
        f"[RL-TRAD] Stamp {OUT_DIR} trad={len(trad)} house={len(house)} "
        f"house_fail={len(overlap['house_fail'])} missing={missing}",
        flush=True,
    )
    if missing:
        print("[RL-TRAD] Missing OHLC — abort", flush=True)
        return 1

    arms = [
        {
            "id": "tradable",
            "label": f"Tradable {len(trad)} (2010 / $5 / ADV$2m)",
            "role": "candidate",
            "symbols": trad,
            "reuse_dir": None,
        },
        {
            "id": "list2",
            "label": "List 2 (93, IS TPY/avg/WO_MAX cut)",
            "role": "candidate",
            "symbols": LIST2,
            "reuse_dir": PRIOR / "runs" / "list2",
        },
        {
            "id": CONTROL_ID,
            "label": "House RL (59, legacy whitelist)",
            "role": "control",
            "symbols": house,
            "reuse_dir": PRIOR / "runs" / CONTROL_ID,
        },
    ]

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
                print(f"[RL-TRAD] Missing Closed for {arm['id']}", flush=True)
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
                    or (_find_latest(src, "RL_Summary_*.csv") if src else None),
                    "equity_meta": _find_latest(arm_dir, "RL_EquityMeta_*.csv")
                    or (_find_latest(src, "RL_EquityMeta_*.csv") if src else None),
                    "report": _find_latest(arm_dir, "RL_Report_*.csv")
                    or (_find_latest(src, "RL_Report_*.csv") if src else None),
                }
            )
    else:
        for arm in arms:
            if arm.get("reuse_dir") and not args.force:
                run = _copy_reuse(arm)
                print(
                    f"[RL-TRAD] {arm['id']} reuse ok={run['ok']} n={len(run['trades'])} stamp={run.get('stamp')}",
                    flush=True,
                )
                runs.append(run)
            else:
                run = run_live(py, arm, args.workers, skip_existing)
                print(
                    f"[RL-TRAD] {arm['id']} ok={run['ok']} n={len(run['trades'])} "
                    f"elapsed={run.get('elapsed_s', 0):.0f}s skipped={run.get('skipped')}",
                    flush=True,
                )
                runs.append(run)

    runs.sort(key=lambda r: ARM_ORDER.get(r["arm"]["id"], 99))
    if not all(r.get("ok") for r in runs):
        print("[RL-TRAD] One or more arms failed", flush=True)
        for r in runs:
            print(f"  {r['arm']['id']}: ok={r.get('ok')} exit={r.get('exit_code')}", flush=True)
        return 1

    packed = [pack_result(r) for r in runs]
    result = summarize(packed, overlap, len(trad), missing)

    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    if ntfy.is_file():
        t = next(p for p in packed if p["arm"]["id"] == "tradable")
        h = next(p for p in packed if p["arm"]["id"] == CONTROL_ID)
        subprocess.run(
            [
                py,
                str(ntfy),
                "--path",
                str(OUT_DIR / "compare.html"),
                "-t",
                "RL tradable tape vs 59",
                "-m",
                (
                    f"OOS tradable Avg={t['m_oos']['avg_pnl']:.2f}% PF={t['m_oos']['pf']:.2f} "
                    f"vs house Avg={h['m_oos']['avg_pnl']:.2f}% PF={h['m_oos']['pf']:.2f}"
                ),
            ],
            cwd=str(ROOT),
        )
    print(result["bottom"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
