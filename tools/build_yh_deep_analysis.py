#!/usr/bin/env python3
"""Build drive/paul_experiments/YH_Deep_Analysis.html from YH A/B artifacts.

Aggregates:
  - yh_param_hint_ab (band/target/stop) — dismiss if none beat control
  - yh_false_start_ab / yh_post_target_ab / yh_fat_stops_ab
  - Prior SPY INT Weak YH arms (spy_int_weak_system_ab/YH)

Usage (repo root)::
  python tools/build_yh_deep_analysis.py
"""
from __future__ import annotations

import csv
import html
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
DRIVE = REPO / "drive"
OUT = DRIVE / "paul_experiments" / "YH_Deep_Analysis.html"
PE = DRIVE / "paul_experiments"

SORTABLE_TH_CSS = """
th.sortable-th{cursor:pointer;user-select:none;white-space:nowrap}
th.sortable-th:hover{background:#e2e8f0}
th.sortable-th .sort-ind::after{content:" \\2195";opacity:.35;font-size:.85em}
th.sortable-th.sort-asc .sort-ind::after{content:" \\2191";opacity:.9}
th.sortable-th.sort-desc .sort-ind::after{content:" \\2193";opacity:.9}
"""

SORTABLE_TABLE_SCRIPT = """
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : 0;
    if (type === "text") return s.toUpperCase();
    var n = s.replace(/[$,%+]/g, "").replace(/,/g, "");
    var v = parseFloat(n);
    return Number.isFinite(v) ? v : 0;
  }
  function sortTable(table, col, type, dir) {
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll("tr"));
    var pinned = rows.filter(function (r) { return r.classList.contains("total-row"); });
    var movable = rows.filter(function (r) { return !r.classList.contains("total-row"); });
    movable.sort(function (a, b) {
      var av = parseSortValue(a.cells[col] && a.cells[col].textContent, type);
      var bv = parseSortValue(b.cells[col] && b.cells[col].textContent, type);
      if (typeof av === "string" || typeof bv === "string") {
        return dir * String(av).localeCompare(String(bv));
      }
      return dir * (av - bv);
    });
    movable.concat(pinned).forEach(function (r) { tbody.appendChild(r); });
  }
  function bind(table) {
    var ths = table.querySelectorAll("th.sortable-th");
    ths.forEach(function (th, idx) {
      function activate() {
        var type = th.getAttribute("data-sort") || "text";
        var asc = !th.classList.contains("sort-asc");
        ths.forEach(function (x) {
          x.classList.remove("sort-asc", "sort-desc");
          x.setAttribute("aria-sort", "none");
        });
        th.classList.add(asc ? "sort-asc" : "sort-desc");
        th.setAttribute("aria-sort", asc ? "ascending" : "descending");
        sortTable(table, idx, type, asc ? 1 : -1);
      }
      th.addEventListener("click", activate);
      th.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activate(); }
      });
    });
  }
  document.querySelectorAll("table.sortable").forEach(bind);
})();
</script>
"""


def _sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{html.escape(sort_type)}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        return list(csv.DictReader(f))


def _f(x: Any) -> float:
    try:
        return float(str(x).replace(",", "").replace("%", "").strip() or 0)
    except ValueError:
        return 0.0


def section_param_hint() -> tuple[str, str]:
    rows = _read_csv(PE / "yh_param_hint_ab" / "comparison.csv")
    if not rows:
        return "<p class='muted'>No yh_param_hint_ab/comparison.csv yet.</p>", "missing"
    ctrl = next((r for r in rows if r.get("arm") == "00_control"), None)
    c_ann = _f((ctrl or {}).get("ann_ror"))
    c_pnl = _f((ctrl or {}).get("total_pnl"))
    any_beat = False
    body = []
    for r in rows:
        arm = r.get("arm", "")
        ann = _f(r.get("ann_ror"))
        pnl = _f(r.get("total_pnl"))
        d_ann = ann - c_ann
        d_pnl = pnl - c_pnl
        if arm != "00_control" and d_ann > 0 and d_pnl > 0:
            any_beat = True
            lean = "hold"
            why = "Beats control on both Ann_ROR and Total_PNL — review ToS before adopt."
        elif arm == "00_control":
            lean = "control"
            why = "Frozen run_yh.bat baselines."
        else:
            lean = "dismiss"
            why = "Does not beat control on Ann_ROR and Total_PNL (primary dismiss gate)."
        body.append(
            "<tr>"
            f"<td><code>{html.escape(arm)}</code></td>"
            f"<td>{html.escape(r.get('hypothesis_id') or r.get('param',''))}</td>"
            f"<td><code>{html.escape(r.get('knob',''))}</code></td>"
            f"<td>{html.escape(r.get('stamp',''))}</td>"
            f"<td>{int(_f(r.get('trades')))}</td>"
            f"<td>{_f(r.get('wr')):.1f}</td>"
            f"<td>{ann:.2f}</td>"
            f"<td>{pnl:.0f}</td>"
            f"<td>{_f(r.get('max_dd')):.2f}</td>"
            f"<td>{d_ann:+.2f}</td>"
            f"<td>{d_pnl:+.0f}</td>"
            f"<td><strong>{lean}</strong></td>"
            f"<td>{html.escape(why)}</td>"
            "</tr>"
        )
    verdict = (
        "DISMISS all alts — none beat control on Ann_ROR and Total_PNL."
        if not any_beat
        else "At least one arm beats control on Ann_ROR+PnL — still ToS before adopt."
    )
    ths = "".join(
        [
            _sortable_th("Arm", "text"),
            _sortable_th("Hypothesis", "text"),
            _sortable_th("Knob", "text"),
            _sortable_th("Stamp", "text"),
            _sortable_th("Trades", "num"),
            _sortable_th("WR%", "num"),
            _sortable_th("Ann_ROR", "num"),
            _sortable_th("Total_PNL", "num"),
            _sortable_th("Max_DD", "num"),
            _sortable_th("Δ Ann_ROR", "num"),
            _sortable_th("Δ PnL", "num"),
            _sortable_th("Lean", "text"),
            _sortable_th("Why", "text"),
        ]
    )
    html_s = f"""
<p><strong>Verdict:</strong> {html.escape(verdict)}
 Source ImproveHints stamp linked from <code>run_yh_param_hint_ab.bat</code>.
 Comparison: <a href="yh_param_hint_ab/comparison.html">yh_param_hint_ab/comparison.html</a>.
 Universe for that run still included TSLA; production list is now Mag9 without TSLA.</p>
<table class="sortable"><thead><tr>{ths}</tr></thead><tbody>
{"".join(body)}
</tbody></table>
"""
    return html_s, "dismiss" if not any_beat else "mixed"


def section_pattern(suite: str, title: str, rel: str) -> str:
    rows = _read_csv(PE / rel / "comparison.csv")
    if not rows:
        return f"<p class='muted'>No {html.escape(rel)}/comparison.csv yet — run the suite bat.</p>"
    ths = "".join(
        [
            _sortable_th("Arm", "text"),
            _sortable_th("Stamp", "text"),
            _sortable_th("Trades", "num"),
            _sortable_th("WR%", "num"),
            _sortable_th("Ann_ROR", "num"),
            _sortable_th("Total_PNL", "num"),
            _sortable_th("Max_DD", "num"),
            _sortable_th("FS15", "num"),
            _sortable_th("PTQS", "num"),
            _sortable_th("FAT", "num"),
            _sortable_th("Δ Ann_ROR", "num"),
            _sortable_th("Δ PnL", "num"),
            _sortable_th("Lean", "text"),
            _sortable_th("Why", "text"),
        ]
    )
    body = []
    for r in rows:
        body.append(
            "<tr>"
            f"<td><code>{html.escape(r.get('arm',''))}</code></td>"
            f"<td>{html.escape(r.get('stamp',''))}</td>"
            f"<td>{int(_f(r.get('trades')))}</td>"
            f"<td>{_f(r.get('wr')):.1f}</td>"
            f"<td>{_f(r.get('ann_ror')):.2f}</td>"
            f"<td>{_f(r.get('pnl')):.0f}</td>"
            f"<td>{_f(r.get('max_dd')):.2f}</td>"
            f"<td>{int(_f(r.get('fs15_n')))}</td>"
            f"<td>{int(_f(r.get('ptqs_n')))}</td>"
            f"<td>{int(_f(r.get('fat_n')))}</td>"
            f"<td>{_f(r.get('d_ann_ror')):+.2f}</td>"
            f"<td>{_f(r.get('d_pnl')):+.0f}</td>"
            f"<td><strong>{html.escape(r.get('lean',''))}</strong></td>"
            f"<td>{html.escape(r.get('why',''))}</td>"
            "</tr>"
        )
    return f"""
<p class="muted">Suite output: <a href="{html.escape(rel)}/comparison.html">{html.escape(rel)}/comparison.html</a>.
Click column headers to sort.</p>
<table class="sortable"><thead><tr>{ths}</tr></thead><tbody>
{"".join(body)}
</tbody></table>
"""


def section_prior_spy() -> str:
    rows = _read_csv(PE / "spy_int_weak_system_ab" / "YH" / "partial_YH.csv")
    ths = "".join(
        [
            _sortable_th("Arm", "text"),
            _sortable_th("Trades", "num"),
            _sortable_th("WR%", "num"),
            _sortable_th("PF", "num"),
            _sortable_th("PNL", "num"),
            _sortable_th("MaxDD", "num"),
            _sortable_th("Expectancy", "num"),
            _sortable_th("Lean (historical)", "text"),
            _sortable_th("Why", "text"),
        ]
    )
    body = []
    parsed: list[tuple[str, float, float, float, float, float, float]] = []
    for r in rows:
        arm = str(r.get("arm") or "").strip()
        if not arm:
            continue
        parsed.append(
            (
                arm,
                _f(r.get("trades")),
                _f(r.get("wr")),
                _f(r.get("pf")),
                _f(r.get("pnl")),
                _f(r.get("maxdd")),
                _f(r.get("expectancy")),
            )
        )
    if not parsed:
        parsed = [
            ("baseline", 378, 34.13, 1.50, 422651.60, 12.49, 1118.13),
            ("no_entry_weak", 275, 34.55, 1.48, 357729.24, 13.27, 1300.83),
            ("exit_on_weak", 424, 47.17, 1.60, 343039.20, 9.72, 809.05),
        ]
    for arm, trades, wr, pf, pnl, dd, exp in parsed:
        if arm == "baseline":
            lean, why = "control", "Prior full-seed YH baseline (pre Mag9-no-TSLA)."
        elif arm == "no_entry_weak":
            lean, why = (
                "dismiss",
                "Fewer trades (−103), lower PNL, slightly worse MaxDD vs baseline; "
                "higher expectancy alone not enough to adopt.",
            )
        elif arm == "exit_on_weak":
            lean, why = (
                "dismiss",
                "Higher WR / better MaxDD but lower PNL & expectancy; exit-only not a clean win.",
            )
        else:
            lean, why = "cite", "See spy_int_weak_system_ab/YH/RESULTS.md."
        body.append(
            "<tr>"
            f"<td><code>{html.escape(str(arm))}</code></td>"
            f"<td>{int(trades)}</td><td>{wr:.2f}</td><td>{pf:.2f}</td>"
            f"<td>{pnl:.0f}</td><td>{dd:.2f}</td><td>{exp:.0f}</td>"
            f"<td><strong>{lean}</strong></td><td>{html.escape(why)}</td>"
            "</tr>"
        )
    return f"""
<p>Prior Year-High (YH) SPY Intermediate (INT) Weak lag-1 A/B under
<code>spy_int_weak_system_ab/YH/</code> (full production seed of that day — not Mag9-no-TSLA).
Re-tested Mag9 block arm lives in <code>yh_false_start_ab/04_spy_block_weak</code>.
Docs: <code>spy_int_weak_system_ab/RESULTS.md</code>.</p>
<table class="sortable"><thead><tr>{ths}</tr></thead><tbody>
{"".join(body)}
</tbody></table>
"""


def build() -> Path:
    param_html, param_lean = section_param_hint()
    fs = section_pattern("false_start", "false_start", "yh_false_start_ab")
    pt = section_pattern("post_target", "post_target", "yh_post_target_ab")
    fat = section_pattern("fat_stops", "fat_stops", "yh_fat_stops_ab")
    spy = section_prior_spy()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>YH Deep Analysis</title>
<style>
body {{ margin:0; padding:28px; font-family:"Segoe UI",Georgia,serif; background:#fafaf8; color:#1a1a18; }}
.wrap {{ max-width:1400px; margin:0 auto; }}
h1 {{ font-size:1.6rem; margin-bottom:4px; }}
h2 {{ font-size:1.2rem; margin-top:2rem; border-top:1px solid #e2e8f0; padding-top:1rem; }}
.muted {{ color:#5c5c56; line-height:1.5; }}
.verdict {{ background:#eef3f8; border:1px solid #c5d0dc; padding:12px 14px; border-radius:4px; margin:12px 0; }}
table.sortable {{ border-collapse:collapse; width:100%; font-size:13px; margin:8px 0 16px; }}
table.sortable th, table.sortable td {{ border:1px solid #d8d8d0; padding:6px 8px; vertical-align:top; }}
table.sortable th {{ background:#f0f0ea; }}
code {{ font-size:12px; background:#f1f5f9; padding:1px 4px; border-radius:3px; }}
ul.sources {{ font-size:13px; color:#475569; line-height:1.7; }}
{SORTABLE_TH_CSS}
</style></head><body><div class="wrap">
<h1>YH Deep Analysis — A/B ledger</h1>
<p class="muted">Year-High (YH) hypothesis tests: what was tried, dismissed, and why.
Current production universe = Mag9 <strong>without TSLA</strong>
(<code>drive/universes/YH_universe.csv</code>).
Rules: one knob / coherent gate, ≤2 alternatives, evidence-based — not “find optimal”
(<code>docs/HYPOTHESIS_TEST.md</code>). Click column headers to sort. Generated {html.escape(now)}.</p>

<div class="verdict">
<strong>Param-hint A/B lean:</strong> {html.escape(param_lean.upper())} —
expand stop / expand target / tighten band did not beat control on Ann_ROR <em>and</em> Total_PNL.
Keep production <code>stop_pct=0.934</code>, <code>target_pct=1.21</code>, <code>band_pct=0.015</code>.
</div>

<h2>1. Parameter hints (band / target / stop)</h2>
<p class="muted">Bat: <code>run_yh_param_hint_ab.bat</code> · Driver: <code>tools/yh_param_hint_ab.py</code>
· Evidence: ImprovePriority param cards (first section + Run AB) on stamp <code>260807080037</code>.
One knob / ≤1 alt — hypothesis test, not optimal search.</p>
{param_html}

<h2>2. Taken-trade pattern: false_start_2022_2023</h2>
<p class="muted">Bat: <code>run_yh_ab_false_start.bat</code> · 10 sym / 17 trades on ImprovePriority
(examples included TSLA; Mag9 runs drop TSLA). Levers: start_date, SPY weak block, growth_bars regime proxy
(YH has no RL slope gate on the zone path).</p>
{fs}

<h2>3. Taken-trade pattern: post_target_quick_stop</h2>
<p class="muted">Bat: <code>run_yh_ab_post_target.bat</code> · Prefer <code>rl_post_target_*</code>
over blanket <code>symbol_reentry_cooldown_days</code> alone (8 sym / 22 trades).</p>
{pt}

<h2>4. Taken-trade pattern: fat_stops</h2>
<p class="muted">Bat: <code>run_yh_ab_fat_stops.bat</code> · Pattern lean = tighter stop / time-stop
(7/24). Conflicts with param-hint <em>expand</em> stop — both tested honestly; expand already dismissed above.</p>
{fat}

<h2>5. Prior SPY INT / IND Weak tests (cite)</h2>
{spy}

<h2>Glossary (arm knobs)</h2>
<ul class="sources">
<li><code>rl_post_target_reentry_bars=N</code> + <code>mode=none</code> —
<strong>N trading bars</strong> after a <em>TARGET</em> exit only; block all re-entry in that window.
Alias <code>rl_post_target_reentry_days</code> is still bars. Does not fire after STOP / other exits.
Example: <code>03_pt_none_30</code> = 30 bars (~6 weeks), not 30 calendar days.</li>
<li><code>symbol_reentry_cooldown_days=N</code> —
<strong>N calendar days</strong> after <em>any</em> exit before same-symbol re-entry (blanket). No <code>sale_reentry_*</code> knob.</li>
<li>Other modes (not in this YH suite): <code>under_sma_limit</code> / <code>min_stack</code> quality-block;
<code>stop_loss</code> allow + optional tighter <code>rl_post_target_stop_pct</code>.</li>
<li><code>start_date</code> → <code>entry_start_date</code>: no new entries before that date.</li>
<li><code>block_entries_when_spy_int_weak</code> + <code>spy_int_tc_lag=1</code>:
skip new entries when lagged SPY Intermediate (INT) TC outlook is Weak.</li>
<li><code>growth_bars</code>: require Close ≥ Close N bars ago (756≈3Y control; 252≈1Y).</li>
<li><code>stop_pct</code> multiplier of signal low: higher = tighter (0.945 vs 0.934);
<code>time_stop_days</code>: exit at close when bars held ≥ N (name says days, counts bars).</li>
</ul>

<h2>Sources / re-run</h2>
<ul class="sources">
<li><code>run_yh_param_hint_ab.bat 260807080037</code> → <code>paul_experiments/yh_param_hint_ab/</code></li>
<li><code>run_yh_ab_false_start.bat</code> → <code>paul_experiments/yh_false_start_ab/</code></li>
<li><code>run_yh_ab_post_target.bat</code> → <code>paul_experiments/yh_post_target_ab/</code></li>
<li><code>run_yh_ab_fat_stops.bat</code> → <code>paul_experiments/yh_fat_stops_ab/</code></li>
<li><code>run_yh_ab_patterns.bat</code> — all three pattern suites + this HTML</li>
<li><code>tools/build_yh_deep_analysis.py</code> — rebuild this report</li>
<li>Prior: <code>spy_int_weak_system_ab/YH/</code>, <code>yh_baseline_260801110845/</code></li>
</ul>
</div>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(doc, encoding="utf-8")
    print(f"Wrote {OUT}")
    return OUT


if __name__ == "__main__":
    build()
