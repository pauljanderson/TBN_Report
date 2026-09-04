#!/usr/bin/env python3
"""House adopt: RL timed exit +40% entry MTM then 30d (arm 40_30d).

Paul override: prior AB rl_entry_exit_ab_20260831 judged 40_30d IS LEAN KEEP /
OOS DISMISS vs 40d@29% control; vs cut_off_only (no time stop) this stamp
documents the adopt. Wire run_rl.bat / RLConfig / AWK defaults.

Usage:
  python tools/rl_adopt_exit_40_30d.py
  python tools/rl_adopt_exit_40_30d.py --prod-stamp 260831HHMMSS
"""
from __future__ import annotations

import argparse
import html as html_mod
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
STAMP = "20260831"
OUT_DIR = DRIVE / "paul_experiments" / f"rl_adopt_exit_40_30d_{STAMP}"
SRC_AB = DRIVE / "paul_experiments" / f"rl_entry_exit_ab_{STAMP}"
CONTROL_ID = "cut_off_only"  # prior house-ish: cut OFF + no time stop
ADOPT_ID = "40_30d"

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(DRIVE / "paul_experiments"))
from be_stop_replay_ab import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from compare_format import filter_html_compare_columns  # noqa: E402
from rl_univ_compare_lists import (  # noqa: E402
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


def _load(arm_id: str, label: str, role: str) -> dict[str, Any]:
    arm_dir = SRC_AB / "runs" / arm_id
    closed = _find_latest(arm_dir, "RL_Closed_*.csv")
    if not closed:
        raise FileNotFoundError(f"Missing Closed for {arm_id} under {arm_dir}")
    trades = load_trades(closed)
    # compare_row expects arm["symbols"]; univ size unknown from Closed alone — use 764
    arm = {"id": arm_id, "label": label, "role": role, "symbols": ["_"] * 764}
    return {
        "arm": arm,
        "ok": len(trades) > 0,
        "closed": closed,
        "trades": trades,
        "stamp": closed.stem.split("_")[-1],
        "summary": _find_latest(arm_dir, "RL_Summary_*.csv"),
        "equity_meta": _find_latest(arm_dir, "RL_EquityMeta_*.csv"),
        "report": _find_latest(arm_dir, "RL_Report_*.csv"),
    }


def _md_split(p: dict[str, Any], key: str) -> str:
    m = p[key]
    return (
        f"N={m['n']} WR={m['wr']:.1f}% Avg={m['avg_pnl']:.2f}% WO_MAX={m['wo_max']:.2f}% "
        f"PF={m['pf']:.2f} AnnROR={fmt_n(m['ann_ror'], 2)} MaxDD_overlay={fmt_n(m['max_dd'], 2)}"
    )


def write_compare_html(packed: list[dict[str, Any]], verdicts: dict[str, tuple[str, str]]) -> Path:
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
    th = "".join(sortable_th(a, b) for a, b in th_cols)
    sections = []
    for split_key, title in (("m_is", "IS"), ("m_oos", "OOS (report-only)"), ("m_full", "FULL book")):
        body = "".join(compare_row(p, split_key, baseline, "", CONTROL_ID) for p in packed)
        sections.append(
            f'<section><h2>Adopt 40_30d vs cut OFF / no time stop — {title}</h2>'
            f'<p class="muted">Prior context = cut_the_losers OFF + exit_days=10000. '
            f"Adopted = +40% then 30d. Click column headers to sort.</p>"
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
    pw_rows = ""
    for split_key, title in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
        rows = pairwise_delta_row(by_id[CONTROL_ID], by_id[ADOPT_ID], split_key, f"{ADOPT_ID} − {CONTROL_ID}")
        pw_rows += (
            f'<section><h2>Pairwise — {title}</h2>'
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{pw_th}</tr></thead>'
            f"<tbody>{rows}</tbody></table></div></section>"
        )

    vis, nis = verdicts["is"]
    voos, noos = verdicts["oos"]
    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL adopt exit 40_30d — {STAMP}</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; --accent:#5b9fd4; --ctrl:#243044; }}
*{{box-sizing:border-box}}
body{{margin:0;font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header{{padding:1.25rem 1rem 0.5rem;max-width:1400px;margin:0 auto}}
h1{{font-size:1.35rem;margin:0 0 .35rem}}
h2{{font-size:1.05rem;margin:1.25rem 0 .4rem;color:var(--accent)}}
.muted{{color:var(--muted);font-size:.92rem}}
.callout{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem;margin:.75rem 0}}
.warn{{border-color:#a67c2a}}
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
<h1>RL house adopt — +40% then 30d timed exit</h1>
<p class="muted">Stamp <code>rl_adopt_exit_40_30d_{STAMP}</code>. Tradable 764 Closed reused from
<code>rl_entry_exit_ab_{STAMP}</code>. Knobs: <code>rl_exit_percent=0.40</code>,
<code>rl_exit_days=30</code>, <code>rl_cut_the_losers=1000</code>. Click headers to sort.</p>
</header>
<main>
<div class="callout warn">
<strong>Selection / PO override:</strong> Prior AB <code>rl_entry_exit_ab_20260831</code> vs
<strong>40d@29% control</strong> judged <code>40_30d</code> IS <code>LEAN KEEP</code> /
OOS <code>DISMISS</code> (softened). Paul adopted anyway — <strong>not</strong> an OOS retune.
Table below is vs <strong>cut OFF + no time stop</strong> (prior preferred baseline context);
that pairwise can look DISMISS on Avg%/PF because the time stop cuts winners short vs unlimited hold.
</div>
{"".join(sections)}
{pw_rows}
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path = OUT_DIR / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_docs(
    packed: list[dict[str, Any]],
    verdicts: dict[str, tuple[str, str]],
    prod_stamp: str,
) -> None:
    by_id = {p["arm"]["id"]: p for p in packed}
    vis, nis = verdicts["is"]
    voos, noos = verdicts["oos"]
    prior = by_id[CONTROL_ID]
    adopt = by_id[ADOPT_ID]

    baseline = f"""# BASELINE — `rl_adopt_exit_40_30d_{STAMP}`

**House adopt (Paul override).** Production / DailyRun timed exit changed to
**+40% entry MTM then 30 days** (`rl_exit_percent=0.40`, `rl_exit_days=30`).
Also freeze **`rl_cut_the_losers=1000` (OFF)** as house baseline.

## Selection honesty (required)

Prior one-family AB `rl_entry_exit_ab_{STAMP}` arm **`40_30d`** vs Paul 40d@29% control:

| Split | Verdict | Note |
|-------|---------|------|
| IS | **LEAN KEEP** | Avg% 3.87 vs 3.52; PF 1.63 vs 1.59 |
| OOS | **DISMISS** | Avg% 3.54 vs 3.65; PF 1.61 vs 1.64 — **softened** |

Paul directed adopt **anyway**. This stamp follows that request — **not** a silent KEEP from OOS,
**not** an OOS retune. Label: **selection / PO override**; research→prod if DailyRun-wired.

Compare HTML vs **cut OFF + no time stop** (`cut_off_only`, exit_days=10000) — Paul's preferred
pre-adopt baseline context (cut already OFF).

## New house freeze

| Knob | Prior typical prod | New house |
|------|-------------------|-----------|
| `rl_exit_percent` | **0.29** | **0.40** |
| `rl_exit_days` | **10000** (≈off) / research 40 | **30** |
| `rl_cut_the_losers` | config **0.25** (bat often unset) | **1000** (OFF) |
| `rl_dip_pct` | 1.055 | 1.055 |
| `rl_expansion` | 1.163 | 1.163 |
| `rl_stop_pct` | 0.934 | 0.934 |
| `rl_target_pct` | 1.20 (SMA50) | 1.20 — **stays live** |
| `rl_too_high` | 0 | 0 |
| trails / flush | off | off |
| Universe (ABs) | tradable 764 | same |
| Reconcile univ | `RL_universe.csv` (59) | same |

## Engine: knobs match AB arm

```text
curr_profit_pct = (high − entry) / entry
has_hit_time when curr_profit_pct >= rl_exit_percent   # 0.40
RL_EXIT_DAYS when time_counter >= rl_exit_days         # 30
```

Same knobs as `rl_entry_exit_ab_{STAMP}` / `40_30d`.

## Wired production defaults

- `run_rl.bat` / `run_audit.bat` / `run_audit.ps1`
- `stock_analysis/rocket_rl_config.py`, `rocket_tbn.py` (`RLConfig` / `BRTConfig`)
- `stock_analysis/portfolio_audit.awk` BEGIN defaults
- Research helper `tools/rl_univ_compare_lists.py` `RL_COMMON_V`
- Docs via `tools/_gen_system_writeups.py` → `docs/systems/rl.html`

## Tradable 764 Closed (reuse AB)

| Arm | Stamp | Role |
|-----|-------|------|
| `cut_off_only` | `{prior.get('stamp','')}` | prior context (control for this stamp) |
| `40_30d` | `{adopt.get('stamp','')}` | **adopted** |

## 59-univ reconcile golden

| Item | Value |
|------|-------|
| Engine stamp | **`{prod_stamp or '(pending run_rl.bat)'}`** |
| Prior golden | `260827175608` (dip=1.055; exit 0.29/10000; cut default) |
| Gate | `reconcile_gate_config.json` → system **RL** |

## Promotion label

| Stage | Status |
|-------|--------|
| Research AB | `rl_entry_exit_ab_{STAMP}` — 40_30d IS LEAN KEEP / **OOS DISMISS** |
| House default + reconcile | **This stamp** — Paul override wire |
| Gold sheet parity | Not claimed beyond engine↔engine gate |
"""
    (OUT_DIR / "BASELINE.md").write_text(baseline, encoding="utf-8")

    summary = f"""# SUMMARY — `rl_adopt_exit_40_30d_{STAMP}`

## What changed

House timed exit → **+40% entry MTM, then 30 days** (`rl_exit_percent=0.40`, `rl_exit_days=30`).
`rl_cut_the_losers=1000` (OFF). SMA50 × 1.20 target unchanged.

**Paul override:** AB `40_30d` was IS LEAN KEEP / OOS DISMISS vs 40d@29%; adopt anyway.
OOS caveat stays on the record — do not retune OOS.

### Production defaults updated

- `run_rl.bat`, `run_audit.bat`, `run_audit.ps1`
- `rocket_rl_config.py`, `rocket_tbn.py`, `portfolio_audit.awk`
- `tools/rl_univ_compare_lists.py` `RL_COMMON_V`
- `tools/_gen_system_writeups.py` (regenerate `docs/systems/rl.html`)

## Tradable 764 (vs cut OFF / no time stop)

### IS
- **{CONTROL_ID}**: {_md_split(prior, 'm_is')}
- **{ADOPT_ID}**: {_md_split(adopt, 'm_is')} → verdict vs context **{vis}** ({nis})

### OOS (report-only)
- **{CONTROL_ID}**: {_md_split(prior, 'm_oos')}
- **{ADOPT_ID}**: {_md_split(adopt, 'm_oos')} → **{voos}** ({noos})

### FULL
- **{CONTROL_ID}**: {_md_split(prior, 'm_full')}
- **{ADOPT_ID}**: {_md_split(adopt, 'm_full')}

## Reconcile

Prod stamp: `{prod_stamp or 'run after wire'}`. Prior golden `260827175608`.

## Paths

- HTML: `drive/paul_experiments/rl_adopt_exit_40_30d_{STAMP}/compare.html`
- BASELINE: `drive/paul_experiments/rl_adopt_exit_40_30d_{STAMP}/BASELINE.md`
- Source AB: `drive/paul_experiments/rl_entry_exit_ab_{STAMP}/`
"""
    (OUT_DIR / "SUMMARY.md").write_text(summary, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prod-stamp", default="", help="59-univ RL_Closed stamp after run_rl.bat")
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    runs = [
        _load(CONTROL_ID, "Prior: cut OFF, no time stop (exit_days=10000)", "control"),
        _load(ADOPT_ID, "Adopted: +40% then 30d", "candidate"),
    ]
    packed = [pack_result(r) for r in runs]
    by_id = {p["arm"]["id"]: p for p in packed}
    verdicts = {
        "is": verdict_vs_control(by_id[ADOPT_ID], by_id[CONTROL_ID], "m_is"),
        "oos": verdict_vs_control(by_id[ADOPT_ID], by_id[CONTROL_ID], "m_oos"),
    }
    # Remap compare_row control id expectation
    write_compare_html(packed, verdicts)
    write_metrics_csv(packed, "", OUT_DIR / "metrics_all.csv")
    write_docs(packed, verdicts, args.prod_stamp)

    # Copy Closed refs for convenience
    ref = OUT_DIR / "runs"
    for r in runs:
        dest = ref / r["arm"]["id"]
        dest.mkdir(parents=True, exist_ok=True)
        src = r["closed"]
        if src and src.is_file():
            shutil.copy2(src, dest / src.name)

    py = _resolve_python()
    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    if ntfy.is_file():
        subprocess.run(
            [
                py,
                str(ntfy),
                "--path",
                str(OUT_DIR / "compare.html"),
                "-t",
                "RL adopt 40_30d",
                "-m",
                f"Paul override wire +40%/30d · cut OFF · IS {verdicts['is'][0]} OOS {verdicts['oos'][0]} vs no time stop",
            ],
            cwd=str(ROOT),
            check=False,
        )
    print(f"[ADOPT] Wrote {OUT_DIR}", flush=True)
    print(f"[ADOPT] IS={verdicts['is']} OOS={verdicts['oos']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
