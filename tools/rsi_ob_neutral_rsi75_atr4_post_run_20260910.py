#!/usr/bin/env python3
"""Post-run (no charts, no Yahoo) on rsi75+atr4 CONTROL Closed book."""
from __future__ import annotations

import csv
import html as html_mod
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "stock_analysis") not in sys.path:
    sys.path.insert(0, str(ROOT / "stock_analysis"))

from rocket_post_analysis import (  # noqa: E402
    enrich_closed_csv_with_one_liners,
    enrich_summary_csv_with_avg_days_held,
    enrich_summary_csv_with_fit,
    enrich_summary_csv_with_yfinance,
    write_improve_hints,
)
from post_run_analysis import (  # noqa: E402
    write_improve_priority_html,
    write_symbol_assessments_html,
)

OUT = ROOT / "drive" / "paul_experiments" / "rsi_ob_neutral_rsi75_atr4_20260910"
CLOSED = OUT / "RSIN_Closed_20260910.csv"
SUMMARY = OUT / "RSIN_Summary_20260910.csv"
DATA = ROOT / "data" / "newdata" / "data"
TS = "20260910"
PREFIX = "RSIN"
ASK = (
    "lets take this RSI Neutral-after-OB — full-universe Closed, post-run, "
    "one-knob A/Bs and run it using both rsiexit75 and atr4"
)
LAYMAN = (
    "This is the after-the-run checkup on the new baseline that freezes both prior "
    "leans: sell when RSI hits 75, and only buy livelier names (ATR% at least 4). "
    "Research only — not gold, not DailyRun. One-knob A/B compare lives in "
    "<code>compare.html</code> in this same stamp."
)


def _prepend_ask(path: Path) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    if "What you asked" in text:
        return
    block = (
        '<div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;'
        'padding:.75rem 1rem;margin:1rem 0;max-width:76rem">'
        "<h2>What you asked</h2>"
        f"<blockquote>{html_mod.escape(ASK)}</blockquote>"
        "<h2>In plain English</h2>"
        f"<p>{LAYMAN}</p>"
        "<p style='color:#9a3412;font-size:.9rem'><strong>Selection honesty:</strong> "
        "control combines two leans from an earlier in-sample horse-race "
        "(<code>rsi_ob_neutral_tune_ab_20260910</code>), then re-scored under freeze. "
        "Research only · not gold · not DailyRun.</p></div>"
    )
    if "<body" in text.lower():
        idx = text.lower().find("<body")
        gt = text.find(">", idx)
        text = text[: gt + 1] + block + text[gt + 1 :]
    else:
        text = block + text
    path.write_text(text, encoding="utf-8")


def _read(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if not CLOSED.is_file():
        print(f"ERROR missing {CLOSED}", flush=True)
        return 1
    print("one-liners…", flush=True)
    enrich_closed_csv_with_one_liners(CLOSED)
    if SUMMARY.is_file():
        enrich_summary_csv_with_yfinance(SUMMARY, no_yfinance=True)
        enrich_summary_csv_with_avg_days_held(SUMMARY, CLOSED)
        enrich_summary_csv_with_fit(SUMMARY, CLOSED, prefix=PREFIX)
    print("ImproveHints…", flush=True)
    write_improve_hints(CLOSED, OUT, TS, prefix=PREFIX, drive_dir=OUT, data_dir=DATA)

    closed_rows = _read(CLOSED)
    summary_rows = _read(SUMMARY)
    by_sym: dict[str, list] = defaultdict(list)
    for r in closed_rows:
        sym = str(r.get("SYMBOL") or "").strip().upper()
        if sym:
            by_sym[sym].append(r)
    symbols = sorted(by_sym)

    assess = OUT / f"{PREFIX}_SymbolAssessments_{TS}.html"
    print("SymbolAssessments…", flush=True)
    write_symbol_assessments_html(
        path=assess, ts=TS, prefix=PREFIX, dip_pct=1.055,
        summary_rows=summary_rows, closed_by_sym=by_sym, symbols=symbols,
        chart_dir=None, missed_by_sym=None,
    )
    _prepend_ask(assess)

    prio = OUT / f"{PREFIX}_ImprovePriority_{TS}.html"
    print("ImprovePriority…", flush=True)
    write_improve_priority_html(
        path=prio, ts=TS, prefix=PREFIX, closed_rows=closed_rows,
        miss_themes=None, drive_dir=OUT, data_dir=DATA,
    )
    _prepend_ask(prio)
    for p in OUT.glob(f"{PREFIX}_ImproveHints_{TS}.*"):
        if p.suffix == ".html":
            _prepend_ask(p)
    print(f"Wrote {assess.name} {prio.name}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
