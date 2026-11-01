#!/usr/bin/env python3
"""RL EXIT A/B: +25%/60d vs th113_vol control (+29%/40d) on full universe.

One EXIT knob change on frozen th113_vol entry settings:
  Control: rl_exit_percent=0.29, rl_exit_days=40  (reuse th113_vol Closed)
  Candidate: rl_exit_percent=0.25, rl_exit_days=60

Entry freeze (both arms):
  rl_too_high=1.13, rl_min_avg_vol=10000, rl_min_trigger_vol=5000,
  dip=1.055, expansion=1.163, stop=0.934, target=1.20, cut OFF,
  SMA qual on, slope/ATR off. Full OHLC universe (= run_rl.bat ALL).

IS = entry < 2024-01-01; OOS report-only; no OOS retune.
Research-only. Not gold. Not DailyRun.

Usage:
  python tools/rl_exit_25_60d_th113vol_ab.py
  python tools/rl_exit_25_60d_th113vol_ab.py --summarize-only
  python tools/rl_exit_25_60d_th113vol_ab.py --skip-existing --workers 5
"""
from __future__ import annotations

import argparse
import html as html_mod
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
DATA_DIR = ROOT / "data" / "newdata" / "data"
STAMP = "20260905"
OUT_DIR = DRIVE / "paul_experiments" / f"rl_exit_25_60d_th113vol_{STAMP}"
RUNS_DIR = OUT_DIR / "runs"

# Control Closed from prior full-univ th113_vol stamp (29%/40d)
CTRL_SRC = (
    DRIVE
    / "paul_experiments"
    / "rl_too_high_vol_fulluniv_29_40d_20260904"
    / "runs"
    / "th113_vol"
)

HOUSE_STOP = 0.934
HOUSE_CUT = 1000
HOUSE_DIP = 1.055
TH13 = 1.13
MIN_AVG_VOL = 10_000
MIN_TRIGGER_VOL = 5_000

CONTROL_ID = "th113_vol_29_40d"
CAND_ID = "th113_vol_25_60d"
CTRL_EXIT_PCT = 0.29
CTRL_EXIT_DAYS = 40
CAND_EXIT_PCT = 0.25
CAND_EXIT_DAYS = 60

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


def _entry_freeze_v(exit_pct: float, exit_days: int) -> list[str]:
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
        f"rl_cut_the_losers={HOUSE_CUT}",
        f"rl_exit_percent={exit_pct}",
        f"rl_exit_days={exit_days}",
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
            "label": f"Control th113_vol +{CTRL_EXIT_PCT:.0%}/{CTRL_EXIT_DAYS}d",
            "role": "control",
            "symbols": syms,
            "univ_n": n,
            "exit_pct": CTRL_EXIT_PCT,
            "exit_days": CTRL_EXIT_DAYS,
            "extra_v": _entry_freeze_v(CTRL_EXIT_PCT, CTRL_EXIT_DAYS),
            "reuse": True,
        },
        {
            "id": CAND_ID,
            "label": f"Candidate th113_vol +{CAND_EXIT_PCT:.0%}/{CAND_EXIT_DAYS}d",
            "role": "candidate",
            "symbols": syms,
            "univ_n": n,
            "exit_pct": CAND_EXIT_PCT,
            "exit_days": CAND_EXIT_DAYS,
            "extra_v": _entry_freeze_v(CAND_EXIT_PCT, CAND_EXIT_DAYS),
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
    """Mirror control Closed/Summary/etc into OUT_DIR/runs/control arm."""
    dest = RUNS_DIR / CONTROL_ID
    dest.mkdir(parents=True, exist_ok=True)
    if not CTRL_SRC.is_dir():
        raise FileNotFoundError(f"missing control run dir: {CTRL_SRC}")
    for pat in ("RL_Closed_*.csv", "RL_Summary_*.csv", "RL_EquityMeta_*.csv", "RL_Report_*.csv", "RL_EquityCurve_*.csv"):
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
        f"PF={m['pf']:.2f} AnnROR={fmt_n(m['ann_ror'], 2)} MaxDD_overlay={fmt_n(m['max_dd'], 2)}"
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


def _th_cols() -> list[tuple[str, str]]:
    return filter_html_compare_columns(
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


def write_compare_html(
    packed: list[dict[str, Any]],
    verdicts: dict[str, dict[str, tuple[str, str]]],
    *,
    paul_note: str,
) -> Path:
    by_id = {p["arm"]["id"]: p for p in packed}
    baseline = by_id[CONTROL_ID]
    th = "".join(sortable_th(a, b) for a, b in _th_cols())
    sections = []
    for split_key, split_title in (("m_is", "IS"), ("m_oos", "OOS (report-only)"), ("m_full", "FULL book")):
        body = "".join(compare_row(p, split_key, baseline, "", CONTROL_ID) for p in packed)
        note = (
            "Paul/FIT/UW from host Summary + EquityMeta. Sharpe from host EquityCurve. "
            "Overlay Max DD ≠ host DD."
            if split_key == "m_full"
            else "Closed overlay $47,500 / $500k. Sharpe from host EquityCurve calendar slice. "
            "Overlay Max DD ≠ host account DD."
        )
        sections.append(
            f'<section><h2>RL exit 25%/60d vs th113_vol control — {split_title}</h2>'
            f'<p class="muted">Δ vs control. {note} Click column headers to sort.</p>'
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
        f"Stamp <code>rl_exit_25_60d_th113vol_{STAMP}</code>. "
        f"One EXIT knob: <code>rl_exit_percent</code>/<code>rl_exit_days</code>. "
        f"Entry freeze: too_high={TH13}, AVG_VOL≥{MIN_AVG_VOL:,}, TRIGGER_VOL≥{MIN_TRIGGER_VOL:,}. "
        f"Control = +{CTRL_EXIT_PCT:.0%}/{CTRL_EXIT_DAYS}d (reuse th113_vol). "
        f"Candidate = +{CAND_EXIT_PCT:.0%}/{CAND_EXIT_DAYS}d. "
        f"Universe: full OHLC ({n_univ}). Not gold / not DailyRun. "
        f"IS = entry &lt; 2024-01-01; OOS report-only. Click column headers to sort."
    )
    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL exit 25%/60d vs th113_vol control</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; --accent:#5b9fd4; --ctrl:#243044; }}
*{{box-sizing:border-box}}
body{{margin:0;font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header{{padding:1.25rem 1rem 0.5rem;max-width:1400px;margin:0 auto}}
h1{{font-size:1.35rem;margin:0 0 .35rem}}
h2{{font-size:1.05rem;margin:1.25rem 0 .4rem;color:var(--accent)}}
.muted{{color:var(--muted);font-size:.92rem}}
.callout{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem;margin:.75rem 0}}
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
<h1>RL exit +25%/60d vs th113_vol control (+29%/40d)</h1>
<p class="muted">{subtitle}</p>
</header>
<main>
<div class="callout">
<strong>Paul note:</strong> {html_mod.escape(paul_note)}
<ul><li>{_arm_verdict(CAND_ID, verdicts)}</li></ul>
</div>
{"".join(sections)}
{"".join(pw_sections)}
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    out_path = OUT_DIR / "compare.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path


def write_docs(packed: list[dict[str, Any]], verdicts: dict[str, dict[str, tuple[str, str]]], closed: list[Path], html_path: Path) -> None:
    by_id = {p["arm"]["id"]: p for p in packed}
    n_univ = _count_full_univ()
    baseline = [
        f"# BASELINE — `rl_exit_25_60d_th113vol_{STAMP}`",
        "",
        "**Status:** RESEARCH only. One EXIT knob (`rl_exit_percent` / `rl_exit_days`) vs th113_vol control.",
        f"**Control exit:** `rl_exit_percent={CTRL_EXIT_PCT}`, `rl_exit_days={CTRL_EXIT_DAYS}` (reuse th113_vol).",
        f"**Candidate exit:** `rl_exit_percent={CAND_EXIT_PCT}`, `rl_exit_days={CAND_EXIT_DAYS}`.",
        "Prod/DailyRun remains +40%/30d — do not confuse. Not gold. Not DailyRun.",
        "",
        "## Entry freeze (identical both arms)",
        "",
        "| Knob | Value |",
        "|------|-------|",
        f"| `rl_too_high` | **{TH13}** |",
        f"| `rl_min_avg_vol` | **{MIN_AVG_VOL}** |",
        f"| `rl_min_trigger_vol` | **{MIN_TRIGGER_VOL}** |",
        f"| `rl_dip_pct` | **{HOUSE_DIP}** |",
        "| `rl_expansion` | **1.163** |",
        f"| `rl_stop_pct` | **{HOUSE_STOP}** |",
        "| `rl_target_pct` | **1.20** |",
        f"| `rl_cut_the_losers` | **{HOUSE_CUT}** (off) |",
        "",
        "## Universe / split",
        "",
        f"- Full OHLC pool under `data/newdata/data` (**{n_univ}**), same as `run_rl.bat ALL`",
        "- IS = entry < 2024-01-01; OOS report-only; no OOS retune",
        "",
        "## Arms",
        "",
        "| Arm | exit% | days | Stamp | N_full | OK |",
        "|-----|-------|------|-------|--------|-----|",
    ]
    for p in packed:
        arm = p["arm"]
        baseline.append(
            f"| `{arm['id']}` | {arm['exit_pct']} | {arm['exit_days']} | "
            f"`{p.get('stamp','')}` | {p['m_full']['n']} | {'yes' if p.get('ok') else 'no'} |"
        )
    baseline.extend(
        [
            "",
            "## Verdict",
            "",
            f"- {_arm_verdict(CAND_ID, verdicts)}",
            "",
            "## Selection-bias note",
            "",
            "25%/60d chosen a priori from post-25 path analysis interest (not after seeing this AB OOS).",
            "",
            "## Closed copies",
            "",
        ]
    )
    for c in closed:
        baseline.append(f"- `{c.relative_to(ROOT).as_posix()}`")
    baseline.append("")
    (OUT_DIR / "BASELINE.md").write_text("\n".join(baseline), encoding="utf-8")

    summary = [
        f"# SUMMARY — `rl_exit_25_60d_th113vol_{STAMP}`",
        "",
        f"- {_arm_verdict(CAND_ID, verdicts)}",
        "",
        "## IS",
        "",
        f"- **{CONTROL_ID}**: {_md_split(by_id[CONTROL_ID], 'm_is')}",
        f"- **{CAND_ID}**: {_md_split(by_id[CAND_ID], 'm_is')}",
        "",
        "## OOS (report-only)",
        "",
        f"- **{CONTROL_ID}**: {_md_split(by_id[CONTROL_ID], 'm_oos')}",
        f"- **{CAND_ID}**: {_md_split(by_id[CAND_ID], 'm_oos')}",
        "",
        f"- HTML: `{html_path.relative_to(ROOT).as_posix()}`",
        "",
    ]
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(summary), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summarize-only", action="store_true")
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--workers", type=int, default=5)
    args = ap.parse_args()

    n_univ = _count_full_univ()
    if n_univ <= 0:
        print("[RL-25-60] No CSVs under data/newdata/data", flush=True)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    arms = _arm_defs()
    py = _resolve_python()
    t0 = time.time()
    runs: list[dict[str, Any]] = []

    if args.summarize_only:
        for arm in arms:
            run = _load_arm_from_disk(arm)
            print(f"[RL-25-60] load {arm['id']} ok={run['ok']} n={len(run.get('trades') or [])}", flush=True)
            runs.append(run)
    else:
        print(
            f"[RL-25-60] Full univ={n_univ} workers={args.workers} "
            f"ctrl={CTRL_EXIT_PCT}/{CTRL_EXIT_DAYS}d cand={CAND_EXIT_PCT}/{CAND_EXIT_DAYS}d",
            flush=True,
        )
        for arm in arms:
            run = run_live(py, arm, args.workers, args.skip_existing)
            print(
                f"[RL-25-60] {arm['id']} ok={run['ok']} n={len(run.get('trades') or [])} "
                f"elapsed={run.get('elapsed_s', 0):.0f}s skipped={run.get('skipped')} "
                f"exit={run.get('exit_code')}",
                flush=True,
            )
            runs.append(run)

    by_run = {r["arm"]["id"]: r for r in runs}
    missing = [aid for aid in (CONTROL_ID, CAND_ID) if aid not in by_run or not by_run[aid].get("ok")]
    if missing:
        print(f"[RL-25-60] Missing/failed arms: {missing}", flush=True)
        return 1

    packed = [pack_result(by_run[aid]) for aid in (CONTROL_ID, CAND_ID)]
    by_id = {p["arm"]["id"]: p for p in packed}
    control = by_id[CONTROL_ID]
    verdicts = {
        CAND_ID: {
            "is": verdict_vs_control(by_id[CAND_ID], control, "m_is"),
            "oos": verdict_vs_control(by_id[CAND_ID], control, "m_oos"),
        }
    }
    vis, nis = verdicts[CAND_ID]["is"]
    voos, noos = verdicts[CAND_ID]["oos"]
    paul_note = (
        f"EXIT one-knob: +{CAND_EXIT_PCT:.0%}/{CAND_EXIT_DAYS}d on th113_vol entry freeze vs "
        f"+{CTRL_EXIT_PCT:.0%}/{CTRL_EXIT_DAYS}d control. IS `{vis}` ({nis}); OOS `{voos}` ({noos}). "
        f"Research-only."
    )
    html_path = write_compare_html(packed, verdicts, paul_note=paul_note)
    closed = _stamp_closed_copies(packed)
    write_metrics_csv(packed, "", OUT_DIR / "metrics_all.csv")
    write_docs(packed, verdicts, closed, html_path)
    elapsed = time.time() - t0
    print(f"[RL-25-60] Wrote {html_path}", flush=True)
    print(f"[RL-25-60] Closed copies={len(closed)} total_s={elapsed:.0f}", flush=True)
    print(f"[RL-25-60] Verdict: {_arm_verdict(CAND_ID, verdicts)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
