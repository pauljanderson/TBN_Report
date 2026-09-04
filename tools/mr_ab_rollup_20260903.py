#!/usr/bin/env python3
"""Rollup HTML for mean_reversion_ab_20260903 (4 child stamps).

Usage:
  python tools/mr_ab_rollup_20260903.py
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from be_stop_replay_ab import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from mr_ab_common import PARENT_OUT, PARENT_STAMP, esc  # noqa: E402

CHILDREN = [
    ("01_rl_rsi2_gate", "RL + RSI(2)<10 gate", "ENTRY overlay"),
    ("02_brt_recent_loser", "BRT 21d return < 0", "ENTRY overlay"),
    ("03_rl_valuation_dualbook", "RL Valuation ≥60 dual-book", "dual-book"),
    ("04_brt_zscore_exit", "BRT zscore_exit ON", "EXIT AB"),
]


def parse_summary(path: Path) -> dict[str, str]:
    out = {"overall": "—", "is": "—", "oos": "—", "note": ""}
    if not path.is_file():
        return out
    text = path.read_text(encoding="utf-8")
    m = re.search(r"\*\*Overall \(research\):\*\* \*\*([^*]+)\*\* — (.+)", text)
    if m:
        out["overall"] = m.group(1).strip()
        out["note"] = m.group(2).strip()
    # first candidate IS/OOS lines
    is_m = re.search(r"→ (KEEP|LEAN KEEP|HOLD|DISMISS)\s*$", text, re.M)
    # Prefer explicit IS/OOS from Overall note
    is2 = re.search(r"IS=([A-Z ]+)", out["note"])
    oos2 = re.search(r"OOS=([A-Z ]+)", out["note"])
    if is2:
        out["is"] = is2.group(1).strip()
    if oos2:
        out["oos"] = oos2.group(1).strip().split(";")[0].strip()
    if is_m and out["is"] == "—":
        out["is"] = is_m.group(1)
    return out


def main() -> int:
    PARENT_OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for cid, label, kind in CHILDREN:
        child = PARENT_OUT / cid
        summ = parse_summary(child / "SUMMARY.md")
        href = f"{cid}/compare.html"
        base = f"{cid}/BASELINE.md"
        rows.append(
            "<tr>"
            f"<td>{esc(cid)}</td>"
            f"<td>{esc(label)}</td>"
            f"<td>{esc(kind)}</td>"
            f"<td><strong>{esc(summ['overall'])}</strong></td>"
            f"<td>{esc(summ['is'])}</td>"
            f"<td>{esc(summ['oos'])}</td>"
            f'<td><a href="{esc(href)}">compare.html</a> · <a href="{esc(base)}">BASELINE</a></td>'
            f"<td>{esc(summ['note'][:180])}</td>"
            "</tr>"
        )

    parent_summary = f"""# SUMMARY — `{PARENT_STAMP}`

Parent rollup for the four recommended mean-reversion (MR) ABs from
`mean_reversion_systems_research_20260902`.

**Status:** RESEARCH-ONLY — not gold / not DailyRun / not committed by this job.

## Children

| # | Stamp | Verdict |
|---|-------|---------|
"""
    for cid, label, _kind in CHILDREN:
        summ = parse_summary(PARENT_OUT / cid / "SUMMARY.md")
        parent_summary += f"| {cid} | {label} | **{summ['overall']}** |\n"
    parent_summary += f"""
## Control identities

- **RL (AB1, AB3):** prod freeze from `run_rl.bat` — dip 1.055, cut_the_losers=1000 (OFF),
  `rl_exit_percent=0.40`, `rl_exit_days=30`; Closed
  `rl_entry_exit_ab_20260831/runs/40_30d/RL_Closed_260831203843.csv` (tradable 764).
- **BRT (AB2, AB4):** DailyRun freeze from `run_brt.bat`; AB2 overlays `BRT_LatestRun_Closed.csv`;
  AB4 re-runs control vs zscore_exit on `BRT_universe.csv`.

## Process

One knob each; IS/OOS (`entry < 2024-01-01` / report-only OOS); quality over count;
canonical compare metrics; research candidate ≠ gold ≠ DailyRun.

## Paths

- Rollup: `drive/paul_experiments/{PARENT_STAMP}/compare.html`
"""
    (PARENT_OUT / "SUMMARY.md").write_text(parent_summary + "\n", encoding="utf-8")
    (PARENT_OUT / "BASELINE.md").write_text(
        f"""# BASELINE — `{PARENT_STAMP}`

Parent stamp for four MR ABs recommended by `mean_reversion_systems_research_20260902`.

See child `BASELINE.md` files for frozen knobs. Research-only.
""",
        encoding="utf-8",
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Mean-reversion AB rollup 2026-09-03</title>
<style>
body {{ font-family: "Segoe UI", Tahoma, sans-serif; margin: 24px; color: #0f172a; max-width: 1100px; }}
h1 {{ font-size: 1.35rem; }}
.meta, .small {{ color: #475569; font-size: 13px; }}
.warn {{ background: #fff7ed; border: 1px solid #fdba74; padding: 10px 12px; border-radius: 6px; margin: 12px 0; font-size: 13px; }}
.table-wrap {{ overflow-x: auto; }}
table {{ border-collapse: collapse; font-size: 12px; width: 100%; }}
th, td {{ border: 1px solid #e2e8f0; padding: 6px 8px; text-align: left; vertical-align: top; }}
th {{ background: #f1f5f9; }}
{SORTABLE_TH_CSS}
a {{ color: #1d4ed8; }}
</style>
</head>
<body>
<p class="meta">Stamp <code>{PARENT_STAMP}</code> · Research-only rollup · Source survey
<code>mean_reversion_systems_research_20260902</code></p>
<h1>Mean-reversion ABs — rollup (2026-09-03)</h1>
<div class="warn"><strong>Not DailyRun / not gold.</strong> One-knob ABs; OOS report-only;
KEEP/HOLD/DISMISS on quality. Click headers to sort.</div>
<div class="table-wrap"><table class="sortable"><thead><tr>
{sortable_th("#", "text")}
{sortable_th("Experiment", "text")}
{sortable_th("Type", "text")}
{sortable_th("Overall", "text")}
{sortable_th("IS", "text")}
{sortable_th("OOS", "text")}
{sortable_th("Links", "text")}
{sortable_th("Note", "text")}
</tr></thead><tbody>
{"".join(rows)}
</tbody></table></div>
<p class="small">Generated {date.today().isoformat()} · see child BASELINE.md for freezes</p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path = PARENT_OUT / "compare.html"
    path.write_text(html, encoding="utf-8")
    print(f"[rollup] wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
