#!/usr/bin/env python3
"""Promote locked live-style freeze into official docs / Drive history pages.

1) Re-runs (or reuses) risk_1pct_50k_adv_17name wallet monthly/compare
2) Writes docs/live_style.html — compound-growth story + year path
3) Copies stamp HTML into docs/live_style_monthly.html + docs/live_style_compare.html
4) Injects a callout into docs/monthly.html and docs/system_performance.html when present
5) Updates drive/paul_experiments/LIVE_STYLE_FREEZE.md as official

Does NOT change engine Closed notionals (reconcile stays house-scaled).
"""
from __future__ import annotations

import html as html_mod
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "stock_analysis"))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

from live_style_sizing import (  # noqa: E402
    ACCOUNT_START,
    FREEZE_STAMP,
    NAME_CAP_FRAC,
    ensure_account_json,
    freeze_dict,
)
from compare_format import format_money  # noqa: E402

ET = ZoneInfo("America/New_York")
STAMP_DIR = REPO / "drive" / "paul_experiments" / FREEZE_STAMP
DOCS = REPO / "docs"
DRIVE = REPO / "drive"
POINTER = REPO / "drive" / "paul_experiments" / "LIVE_STYLE_FREEZE.md"

CALLOUT = """
<div class="ask live-style-official" style="margin:16px 0;padding:14px 16px;background:#f0fdf4;border:1px solid #86efac;border-radius:10px;">
  <h2 style="margin:0 0 8px;font-size:1.05rem;color:#166534;">Official live-style sizing + compound growth</h2>
  <p style="margin:0 0 8px;font-size:14px;line-height:1.45;">
    Live buy size (every getTarget system; official mix SB / RSI / VZ / MTS / RL / WRL): risk = min(1% beginning-of-month equity, $50k),
    shares ≤ 1% ADV20, notional ≤ 17.5% of current equity.
    See <a href="live_style.html"><strong>compound growth (live-style)</strong></a>
    · <a href="live_style_monthly.html">wallet monthly</a>
    · <a href="investment.html">investment report Suggested shares</a>.
    Engine Closed rows on this page still use house dummy notionals for reconcile.
  </p>
</div>
"""


def _rerun_freeze() -> dict[str, Any]:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "risk_1pct_50k_adv_17name_20260917",
        REPO / "tools" / "risk_1pct_50k_adv_17name_20260917.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["risk_1pct_50k_adv_17name_20260917"] = mod
    spec.loader.exec_module(mod)
    rc = mod.run()
    if rc != 0:
        raise RuntimeError(f"freeze re-run failed rc={rc}")
    return json.loads((STAMP_DIR / "summary.json").read_text(encoding="utf-8"))


def _load_summary() -> dict[str, Any]:
    path = STAMP_DIR / "summary.json"
    if not path.is_file():
        return _rerun_freeze()
    return json.loads(path.read_text(encoding="utf-8"))


def _year_rows_from_stamp() -> list[dict[str, Any]]:
    """Prefer overlay path from stamped monthly if needed; use summary early years."""
    summ = _load_summary()
    live = summ.get("live175") or {}
    spy_2012 = float(summ.get("spy_2012") or 0)
    spy_end = float(summ.get("spy_tr_end") or 0)
    return [
        {
            "label": "Locked 17.5% live-style (compound wallet)",
            "y2010": live.get("eq_2010"),
            "y2011": live.get("eq_2011"),
            "y2012": live.get("eq_2012"),
            "asof": live.get("end"),
            "max_dd": live.get("max_dd_pct"),
        },
        {
            "label": "Prior 10% name freeze (history)",
            "y2010": (summ.get("prior10") or {}).get("eq_2010"),
            "y2011": (summ.get("prior10") or {}).get("eq_2011"),
            "y2012": (summ.get("prior10") or {}).get("eq_2012"),
            "asof": (summ.get("prior10") or {}).get("end"),
            "max_dd": (summ.get("prior10") or {}).get("max_dd_pct"),
        },
        {
            "label": "SPY $250k total return",
            "y2010": None,
            "y2011": None,
            "y2012": spy_2012,
            "asof": spy_end,
            "max_dd": summ.get("spy_max_dd_pct"),
        },
    ]


def _m(v: Any) -> str:
    if v is None:
        return "—"
    try:
        return format_money(float(v))
    except (TypeError, ValueError):
        return "—"


def _pct(v: Any) -> str:
    try:
        return f"{float(v):.2f}%"
    except (TypeError, ValueError):
        return "—"


def build_live_style_html(summ: dict[str, Any], acct_note: str) -> str:
    live = summ.get("live175") or {}
    now = datetime.now(tz=ET).strftime("%Y-%m-%d %H:%M %Z")
    fz = freeze_dict()
    rows_html = ""
    for r in _year_rows_from_stamp():
        rows_html += (
            "<tr>"
            f"<td>{html_mod.escape(r['label'])}</td>"
            f"<td>{_m(r['y2010'])}</td>"
            f"<td>{_m(r['y2011'])}</td>"
            f"<td>{_m(r['y2012'])}</td>"
            f"<td>{_m(r['asof'])}</td>"
            f"<td>{_pct(r['max_dd'])}</td>"
            "</tr>"
        )
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Live-style compound growth — official</title>
<style>
body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; max-width: none; width: auto; color: #0f172a; }}
.table-wrap {{ overflow: visible !important; max-height: none !important; }}
table {{ width: 100%; }}
h1 {{ font-size: 1.4rem; margin-bottom: 0.25rem; }}
.sub {{ color: #64748b; margin-bottom: 1rem; }}
.ask {{ background: #f0fdf4; border: 1px solid #86efac; border-radius: 10px; padding: 14px 16px; margin: 16px 0; }}
.ask h2 {{ margin: 0 0 8px; font-size: 1.05rem; color: #166534; }}
table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
th, td {{ border: 1px solid #e2e8f0; padding: 8px 10px; text-align: left; }}
th {{ background: #f8fafc; }}
.metric {{ font-size: 1.5rem; font-weight: 700; }}
.cards {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0; }}
.card {{ flex: 1 1 200px; border: 1px solid #e2e8f0; border-radius: 10px; padding: 12px 14px; background: #fff; }}
.small {{ color: #64748b; font-size: 12px; }}
a {{ color: #1d4ed8; }}
</style></head><body>
<h1>Official live-style freeze — compound growth</h1>
<p class="sub">Generated {html_mod.escape(now)}. Stamp <code>{html_mod.escape(FREEZE_STAMP)}</code>.
Not DailyRun Closed identity — wallet overlay for live sizing + historical compound path.</p>

<div class="ask">
  <p>When the five live sleeves flash a buy (StockBee / Relative Strength Index / Volume Zone /
  Magic Touch / Rocket Launcher), we print how many shares to buy using one recipe:
  risk the smaller of 1% of the month-start account and $50,000; never more than 1% of that
  name’s recent average daily volume; never more than 17.5% of the account in one ticker.
  Watchlist Suggested shares are a <strong>range until fill</strong>; getTarget locks the exact
  count after the paid price. The path below is the same recipe as a paper wallet from 2010.
  Engine scorecards still use house dummy dollar sizes so we do not break reconcile.
  Name cap is <strong>17.5%</strong> (10% was the prior research freeze).</p>
</div>

<div class="cards">
  <div class="card">
    <h3>YE2012</h3>
    <div class="metric">{_m(live.get('eq_2012'))}</div>
    <div class="small">vs SPY {_m(summ.get('spy_2012'))}</div>
  </div>
  <div class="card">
    <h3>As-of</h3>
    <div class="metric">{_m(live.get('end'))}</div>
    <div class="small">Max DD {_pct(live.get('max_dd_pct'))}</div>
  </div>
  <div class="card">
    <h3>Name cap</h3>
    <div class="metric">{NAME_CAP_FRAC:.1%}</div>
    <div class="small">+ min(1% BOM, $50k) + 1% ADV20</div>
  </div>
</div>

<section>
<h2>Locked freeze</h2>
<ul>
  <li>risk = min(1% beginning-of-month equity, $50,000)</li>
  <li>shares ≤ 1% ADV20</li>
  <li>notional ≤ 17.5% current equity</li>
  <li>Official 6-sys: SB, RSI, VZ, MTS, RL, WRL · start {format_money(ACCOUNT_START)} · RSI ÷ 0.0651 · not gold</li>
  <li>Leftover 5-sys pin (SB/RSI/VZ/MTS/RL) still on system_performance year path</li>
  <li>Live equity inputs: <code>drive/live_style_account.json</code> — {html_mod.escape(acct_note)}</li>
</ul>
<pre class="small">{html_mod.escape(json.dumps(fz, indent=2))}</pre>
</section>

<section>
<h2>Compound path (wallet)</h2>
<p class="small">Click through for full month ledger and canonical compares.</p>
<table>
<thead><tr>
<th>Book</th><th>2010</th><th>2011</th><th>2012</th><th>As-of</th><th>Max DD%</th>
</tr></thead>
<tbody>{rows_html}</tbody>
</table>
<p>
  <a href="live_style_monthly.html">Full wallet monthly</a> ·
  <a href="live_style_compare.html">Compare vs prior 10%</a> ·
  <a href="investment.html">Investment report (Suggested shares)</a> ·
  <a href="monthly.html">House monthly (engine dollars)</a> ·
  <a href="system_performance.html">Historical performance</a>
</p>
</section>
</body></html>"""


def _inject_callout(path: Path) -> bool:
    if not path.is_file():
        return False
    html = path.read_text(encoding="utf-8")
    if "live-style-official" in html:
        return True
    # Insert after <body> or after first <h1>…</h1>
    m = re.search(r"(<body[^>]*>)", html, flags=re.I)
    if m:
        i = m.end()
        html = html[:i] + CALLOUT + html[i:]
    else:
        html = CALLOUT + html
    path.write_text(html, encoding="utf-8")
    return True


def _strip_published_prompts(html: str) -> str:
    """Pages-published copies must not carry experiment 'What you asked' blocks."""
    html = re.sub(
        r'<div class="ask">\s*<h2>\s*What you asked\s*</h2>.*?</div>',
        "",
        html,
        count=1,
        flags=re.I | re.S,
    )
    html = re.sub(
        r"<h2>\s*What you asked\s*</h2>.*?(?=<h2>|<section|</body>)",
        "",
        html,
        count=1,
        flags=re.I | re.S,
    )
    html = re.sub(
        r"<h2>\s*In plain English\s*</h2>.*?(?=<h2>|<section|</body>)",
        "",
        html,
        count=1,
        flags=re.I | re.S,
    )
    if "table-uncap" not in html and "</style>" in html:
        html = html.replace(
            "</style>",
            "body { max-width: none !important; width: auto; }\n"
            ".table-wrap { max-height: none !important; overflow: visible !important; }\n"
            "table, table.sortable { width: 100%; min-width: 0; }\n</style>",
            1,
        )
    return html


def _copy_stamp_html() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    for src_name, dst_name in (
        ("monthly.html", "live_style_monthly.html"),
        ("compare.html", "live_style_compare.html"),
    ):
        src = STAMP_DIR / src_name
        if src.is_file():
            text = src.read_text(encoding="utf-8", errors="replace")
            (DOCS / dst_name).write_text(_strip_published_prompts(text), encoding="utf-8")
            print(f"[live-style] copied+stripped {src} -> {DOCS / dst_name}")


def write_pointer() -> None:
    POINTER.write_text(
        "\n".join(
            [
                "# Live-style freeze (OFFICIAL)",
                "",
                f"**Stamp:** `{FREEZE_STAMP}`",
                "",
                "## Locked lids (live buy size)",
                "",
                "- risk = min(1% beginning-of-month equity, $50,000)",
                "- shares ≤ 1% ADV20",
                "- notional ≤ **17.5%** of current equity",
                "",
                "## Wired surfaces",
                "",
                "- `stock_analysis/live_style_sizing.py` — source of truth",
                "- `drive/live_style_account.json` — BOM + current equity for Suggested shares",
                "- `generate_investment_report.py` — Suggested shares on every scanner including WRL",
                "- `docs/live_style.html` — compound growth story (Pages)",
                "- `docs/live_style_monthly.html` / `docs/live_style_compare.html` — wallet path",
                "",
                "## Unchanged on purpose",
                "",
                "- Engine Closed / house monthly dollar scale (reconcile / gold identity)",
                "- Old 5-sys pin leftover on system_performance year path",
                "- BRT / YH / WPBR / RS / IND scanners (not in the official 6-sys compound wallet)",
                "",
                "Not gold promotion of Closed books. Live sizing + research wallet = official recipe.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def run(*, rerun: bool = False) -> int:
    ensure_account_json()
    acct = ensure_account_json()
    if rerun or not (STAMP_DIR / "summary.json").is_file():
        print("[live-style] re-running freeze stamp …", flush=True)
        summ = _rerun_freeze()
    else:
        summ = _load_summary()
        print(f"[live-style] reuse stamp summary {STAMP_DIR}", flush=True)

    _copy_stamp_html()
    html = build_live_style_html(
        summ,
        acct_note=f"BOM ${acct.bom_equity:,.0f} · current ${acct.current_equity:,.0f}",
    )
    out = DOCS / "live_style.html"
    out.write_text(html, encoding="utf-8")
    print(f"[live-style] wrote {out}", flush=True)

    # Drive mirror for ntfy / local
    drive_out = DRIVE / "Live_Style_Compound_Latest.html"
    drive_out.write_text(html, encoding="utf-8")
    shutil.copy2(out, drive_out)

    for name in ("monthly.html", "system_performance.html"):
        ok = _inject_callout(DOCS / name)
        print(f"[live-style] callout {name}: {'ok' if ok else 'missing'}", flush=True)

    write_pointer()
    print(f"[live-style] wrote {POINTER}", flush=True)
    return 0


if __name__ == "__main__":
    rerun = "--rerun" in sys.argv
    raise SystemExit(run(rerun=rerun))
