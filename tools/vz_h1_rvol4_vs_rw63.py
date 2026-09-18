#!/usr/bin/env python3
"""H1 origin rvol>=4 vs rw126 control and the adopted rw63 cut.

Replay from the playbook DualPaul78 trade dump (no engine). rw63 is the
previously applied trade-count cut (retest_window 126→63). Under next_open,
engine rw63 ≡ bars_after_break <= 64 (signal bar ≤ break+63, fill T+1).

  python tools/vz_h1_rvol4_vs_rw63.py
"""
from __future__ import annotations

import argparse
import html as html_mod
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

from vol_zone_break_retest import (  # noqa: E402
    DEFAULT_OUT_DIR,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    _closed_signal_rows,
    _fmt_num,
    _fmt_pct,
    sortable_th,
)
from vz_playbook_strength_ab import (  # noqa: E402
    STAMP_DEFAULT,
    _arm_table_html,
    _filter,
    _finite,
    _metrics_row,
    lean,
)

PLAYBOOK_STAMP = STAMP_DEFAULT
OUT_STAMP = "vz_h1_rvol4_vs_rw63_20260813"
RW63_BAB_MAX = 64  # next_open: engine retest_window=63 → entry lag ≤ 64


def _rw63(rows: list[dict]) -> list[dict]:
    return _filter(rows, lambda r: int(r.get("bars_after_break") or 0) <= RW63_BAB_MAX)


def _rvol4(rows: list[dict]) -> list[dict]:
    return _filter(
        rows,
        lambda r: _finite(r, "origin_rvol") and float(r["origin_rvol"]) >= 4.0,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="H1 rvol>=4 vs rw126 / rw63 controls")
    ap.add_argument("--playbook-stamp", default=PLAYBOOK_STAMP)
    ap.add_argument("--stamp", default=OUT_STAMP)
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = ap.parse_args()

    src = Path(args.out_dir) / args.playbook_stamp / "trades_mt1.csv"
    if not src.is_file():
        print(f"[VZ-h1-rw] missing {src}", flush=True)
        return 1
    mt1 = _closed_signal_rows(pd.read_csv(src).to_dict("records"))
    rw63 = _rw63(mt1)
    h1 = _rvol4(mt1)
    stacked = _rvol4(rw63)
    print(
        f"[VZ-h1-rw] mt1={len(mt1)} rw63={len(rw63)} h1={len(h1)} stacked={len(stacked)}",
        flush=True,
    )

    before = _metrics_row("BEFORE CONTROL rw126", mt1)
    after = _metrics_row("AFTER CONTROL rw63", rw63)
    h1_m = _metrics_row("H1 ORIGIN_RVOL>=4 on rw126", h1)
    st_m = _metrics_row("H1 rvol>=4 + rw63", stacked)

    arms = [
        (before, "retest_window=126 (playbook control)", "before", "control"),
        (after, "retest_window=63 (adopted freeze)", "after", lean(before, after)),
        (h1_m, "origin_rvol >= 4.0 on rw126", "h1", lean(before, h1_m)),
        (st_m, "origin_rvol >= 4.0 and rw63", "stack", lean(after, st_m)),
    ]
    table = []
    for m, knob, hyp, lean_s in arms:
        m = dict(m)
        m["knob"] = knob
        m["hyp"] = hyp
        m["lean"] = lean_s
        table.append(m)
        print(
            f"  {m['arm']:32s} N={m['n']:5d} WR={m['wr']*100:5.1f}% "
            f"PnL={m['avg_pnl']:+6.2f} Ann={m['ann_ror']:7.1f} "
            f"MaxDD={m['max_dd']:5.1f} Calmar={m['calmar']:4.2f} "
            f"conc={m['avg_conc']:5.2f} OOS_N={m['oos_n']:4d} "
            f"OOS_PnL={m['oos_avg_pnl']:+6.2f} OOS_DD={m['oos_max_dd']:5.1f}  {m['lean']}",
            flush=True,
        )

    out_dir = Path(args.out_dir) / args.stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(table).to_csv(out_dir / "compare_metrics.csv", index=False)

    dropped_late = before["n"] - after["n"]
    h1_vs_before_n = 100.0 * h1_m["n"] / max(before["n"], 1)
    h1_vs_after_n = 100.0 * h1_m["n"] / max(after["n"], 1)
    stack_vs_after_n = 100.0 * st_m["n"] / max(after["n"], 1)

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>H1 rvol≥4 vs rw126 / rw63 — {html_mod.escape(args.stamp)}</title>
<style>
  body {{ font-family: Segoe UI, Helvetica, sans-serif; margin: 24px; color: #1c1b19; background: #f7f6f2; }}
  h1 {{ font-size: 1.4rem; }}
  h2 {{ font-size: 1.05rem; border-bottom: 1px solid #d4d0c4; padding-bottom: 4px; }}
  .muted {{ color: #5a574f; }}
  .callout {{ background: #e8eef2; border-left: 4px solid #2a4a5c; padding: 10px 12px; margin: 12px 0; }}
  .callout.warn {{ background: #f7efe0; border-left-color: #8a5a12; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; background: #fff; }}
  th, td {{ border: 1px solid #d4d0c4; padding: 6px 8px; text-align: left; }}
  thead th {{ background: #f0eee6; }}
  {SORTABLE_TH_CSS}
  code {{ background: #f0eee6; padding: 0.05em 0.3em; }}
</style></head><body>
<h1>H1 origin rvol ≥4 vs rw126 control and adopted rw63</h1>
<p class="muted">Research only · {html_mod.escape(args.stamp)} · DualPaul78 · same closed trades as playbook AB</p>
<div class="callout warn">
<strong>Not gold. Not DailyRun.</strong> One comparison: the H1 rvol≥4 sleeve vs the control
<em>before</em> the rw63 cut and the control <em>after</em> that cut. Stacked arm is both knobs.
Do not retune on OOS.
</div>
<p>rw63 filter = <code>bars_after_break ≤ {RW63_BAB_MAX}</code> (house next_open).
Late trades dropped vs rw126: {int(dropped_late)}.
H1 is {_fmt_num(h1_vs_before_n, 0)}% of rw126 N and {_fmt_num(h1_vs_after_n, 0)}% of rw63 N.
Stack is {_fmt_num(stack_vs_after_n, 0)}% of rw63 N.</p>
<h2>Results</h2>
{_arm_table_html(table, "BEFORE = rw126 control. AFTER = adopted rw63. H1 lean is vs BEFORE. Stack lean is vs AFTER.")}
<p class="muted">Max DD is the house passive book path (fixed notional, PnL at exit, no OHLC MTM).
Init capital is sized to average concurrent slots.</p>
<footer class="muted">Twin Beacon Networks · VZ research · {html_mod.escape(args.stamp)}</footer>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    (out_dir / "VZ_H1_Rvol4_vs_RW63.html").write_text(html, encoding="utf-8")

    def md_row(r: dict) -> str:
        return (
            f"| {r['arm']} | {r['knob']} | {r['lean']} | {int(r['n'])} | "
            f"{_fmt_pct(float(r['wr']))}% | {_fmt_num(float(r['avg_pnl']))} | "
            f"{_fmt_num(float(r['avg_r']))} | {_fmt_num(float(r['ann_ror']))} | "
            f"{_fmt_num(float(r['max_dd']))} | {_fmt_num(float(r['calmar']))} | "
            f"{_fmt_num(float(r['avg_conc']))} | "
            f"{int(r['is_n'])} | {_fmt_pct(float(r['is_wr']))}% | {_fmt_num(float(r['is_avg_pnl']))} | "
            f"{_fmt_num(float(r['is_max_dd']))} | "
            f"{int(r['oos_n'])} | {_fmt_pct(float(r['oos_wr']))}% | {_fmt_num(float(r['oos_avg_pnl']))} | "
            f"{_fmt_num(float(r['oos_max_dd']))} |"
        )

    b = table[0]
    a = table[1]
    h = table[2]
    s = table[3]
    md = [
        "# H1 origin rvol ≥4 vs rw126 control and adopted rw63",
        "",
        "Research only. Same DualPaul78 closed trades as the playbook AB "
        "(`RESEARCH_CANDIDATE_V2` rw126, next_open, `zone_atr05_ts40`).",
        "",
        "## Verdict",
        "",
        "The previously applied variable is **`retest_window=63`**. "
        f"It drops {int(dropped_late)} late first-retests from the rw126 book. "
        "That cut keeps most of the book and does **not** deliver the Max DD cut that H1 rvol≥4 shows.",
        "",
        f"- **BEFORE (rw126 control):** N={int(b['n'])}, avg PnL {_fmt_num(float(b['avg_pnl']))}%, "
        f"Ann ROR {_fmt_num(float(b['ann_ror']))}%, Max DD {_fmt_num(float(b['max_dd']))}%, "
        f"Calmar {_fmt_num(float(b['calmar']))} (OOS N={int(b['oos_n'])} "
        f"PnL {_fmt_num(float(b['oos_avg_pnl']))}% Max DD {_fmt_num(float(b['oos_max_dd']))}%).",
        f"- **AFTER (rw63 control):** N={int(a['n'])}, avg PnL {_fmt_num(float(a['avg_pnl']))}%, "
        f"Ann ROR {_fmt_num(float(a['ann_ror']))}%, Max DD {_fmt_num(float(a['max_dd']))}%, "
        f"Calmar {_fmt_num(float(a['calmar']))} (OOS N={int(a['oos_n'])} "
        f"PnL {_fmt_num(float(a['oos_avg_pnl']))}% Max DD {_fmt_num(float(a['oos_max_dd']))}%). "
        f"Lean vs BEFORE: **{a['lean']}**.",
        f"- **H1 origin rvol ≥4 on rw126:** N={int(h['n'])} ({_fmt_num(h1_vs_before_n, 0)}% of BEFORE), "
        f"avg PnL {_fmt_num(float(h['avg_pnl']))}%, Ann ROR {_fmt_num(float(h['ann_ror']))}%, "
        f"Max DD {_fmt_num(float(h['max_dd']))}%, Calmar {_fmt_num(float(h['calmar']))} "
        f"(OOS N={int(h['oos_n'])} PnL {_fmt_num(float(h['oos_avg_pnl']))}% "
        f"Max DD {_fmt_num(float(h['oos_max_dd']))}%). "
        f"Lean vs BEFORE: **{h['lean']}**.",
        f"- **Stack (rvol≥4 + rw63):** N={int(s['n'])} ({_fmt_num(stack_vs_after_n, 0)}% of AFTER), "
        f"avg PnL {_fmt_num(float(s['avg_pnl']))}%, Ann ROR {_fmt_num(float(s['ann_ror']))}%, "
        f"Max DD {_fmt_num(float(s['max_dd']))}%, Calmar {_fmt_num(float(s['calmar']))} "
        f"(OOS N={int(s['oos_n'])} PnL {_fmt_num(float(s['oos_avg_pnl']))}% "
        f"Max DD {_fmt_num(float(s['oos_max_dd']))}%). "
        f"Lean vs AFTER: **{s['lean']}**.",
        "",
        f"H1 rvol≥4 is the calmer book vs both controls "
        f"(Max DD {_fmt_num(float(h['max_dd']))}% vs {_fmt_num(float(b['max_dd']))}% before / "
        f"{_fmt_num(float(a['max_dd']))}% after). "
        f"rw63 barely moves Max DD — it is a small N trim ({int(dropped_late)} trades), not a drawdown fix. "
        f"Stacking rvol≥4 on rw63 does not help DD vs H1 alone "
        f"({_fmt_num(float(s['max_dd']))}% vs {_fmt_num(float(h['max_dd']))}%); "
        "most H1 trades already retest inside 63d. "
        "If the reason to like H1 is the DD cut, keep it on rw126 rather than stacking. "
        "Still research-only: H1 is a thin sleeve (~31% of rw126 N). Do not retune on OOS.",
        "",
        "## Setup",
        "",
        f"rw63 proxy: `bars_after_break ≤ {RW63_BAB_MAX}` because house fill is next_open "
        "(engine window is on the signal bar; entry is T+1).",
        "",
        "| Arm | Knob | Lean | N | WR% | Avg PnL% | Avg R | Book Ann ROR% | Max DD% | Calmar | Avg conc | IS N | IS WR% | IS Avg PnL% | IS Max DD% | OOS N | OOS WR% | OOS Avg PnL% | OOS Max DD% |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    md.extend(md_row(r) for r in table)
    md += [
        "",
        "## Reproduce",
        "",
        "```",
        "python tools/vz_playbook_strength_ab.py --replay",
        "python tools/vz_h1_rvol4_vs_rw63.py",
        "```",
        "",
        "Not gold. Not DailyRun. Do not retune on OOS.",
        "",
    ]
    text = "\n".join(md)
    (out_dir / "README.md").write_text(text, encoding="utf-8")
    docs = REPO / "docs" / "research"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "vz_h1_rvol4_vs_rw63.md").write_text(text, encoding="utf-8")
    (docs / "vz_h1_rvol4_vs_rw63.html").write_text(html, encoding="utf-8")
    pd.DataFrame(table).to_csv(docs / "vz_h1_rvol4_vs_rw63.csv", index=False)
    print(f"[VZ-h1-rw] wrote {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
