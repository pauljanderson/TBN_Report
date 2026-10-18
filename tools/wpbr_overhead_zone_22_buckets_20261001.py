"""Score the adopted 3-year-growth WPBR book by overhead-zone count.

Buckets are 0, 1, 2, 3, 4, and 5+ qualifying prior zones within 22% above
the entry zone. Counts come from the whole-book measurement already saved.
Measurement only. No filter.
"""
from __future__ import annotations

import csv
import html as html_mod
import math
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from _gen_too_high_diff import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from compare_format import format_money  # noqa: E402
from report_page_extras import RESPONSIVE_TABLE_CSS, SWIPE_NOTE_HTML  # noqa: E402

STAMP = "20261001"
IS_CUT = "20240101"
CLOSED = ROOT / "tmp_wpbr_growth_min_pct_ab_20261001" / "control" / "WPBR_Closed_261001155729.csv"
COUNTS = ROOT / "drive" / "paul_experiments" / "wpbr_overhead_zone_22_wholebook_20261001" / "trade_zone_counts.csv"
OUT = ROOT / "drive" / "paul_experiments" / f"wpbr_overhead_zone_22_buckets_{STAMP}"
BUCKETS = ("0", "1", "2", "3", "4", "5+")

REQUEST_PROMPT = """Using the adopted 3-year-growth WPBR book, measure performance by the number of qualifying prior overhead WPBR zones within +22% of the active entry-zone upper edge. Bucket every trade by 0, 1, 2, 3, 4, and 5+ zones. Report IS (pre-2024), OOS (2024+), and FULL for each bucket: trades, WR, Avg P&L, PF, Avg winner, Avg loser, and expectancy. Measurement only—do not build or optimize a filter."""

LAYMAN = (
    "We stayed on the same Pivot Break and Retest (WPBR) research book that already requires the stock to be higher than it was 756 trading sessions earlier. "
    "Each closed trade already has a count of older WPBR zones whose bottom sits above the top of the zone being bought, and no more than 22% above that top. "
    "We grouped the trades into six piles: no such zone, one, two, three, four, and five or more. "
    "For buys before 2024, buys from 2024 onward, and the whole book, we wrote down how those piles actually closed. "
    "This is a description of the piles. It is not a new rule that says to skip one of them."
)


def _f(raw: Any) -> float:
    if raw is None:
        return float("nan")
    s = str(raw).strip().replace(",", "").replace("%", "").replace("$", "")
    if not s or s.lower() in {"nan", "none", "null"}:
        return float("nan")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def _ymd(raw: str) -> str:
    s = str(raw or "").strip().replace("-", "")[:8]
    return s if len(s) == 8 and s.isdigit() else ""


def _bucket(n: int) -> str:
    return "5+" if n >= 5 else str(n)


def _notify(paths: list[Path], message: str) -> None:
    cmd = [sys.executable, str(ROOT / "tools" / "ntfy_job_done.py"), "-t", "WPBR zone-count buckets"]
    for p in paths:
        cmd.extend(["--path", str(p)])
    cmd.extend(["-m", message])
    subprocess.run(cmd, cwd=str(ROOT), check=False)


def load_rows() -> list[dict[str, Any]]:
    counts: dict[tuple[str, str], int] = {}
    with COUNTS.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            if str(raw.get("measured") or "") != "1":
                continue
            key = (str(raw["symbol"]).strip().upper(), _ymd(raw["opened"]))
            counts[key] = int(float(raw["n_band"]))
    rows = []
    with CLOSED.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            sym = str(raw.get("SYMBOL") or "").strip().upper()
            opened = _ymd(raw.get("DATE_OPENED") or "")
            key = (sym, opened)
            if key not in counts or not opened:
                continue
            pnl = _f(raw.get("PNL_PCT"))
            if not math.isfinite(pnl):
                continue
            rows.append({
                "symbol": sym,
                "opened": opened,
                "bucket": _bucket(counts[key]),
                "pnl": pnl,
                "pnl_d": _f(raw.get("PNL_DOLLARS")),
            })
    return rows


def _metrics(trades: list[dict[str, Any]]) -> dict[str, float]:
    empty = {
        "n": 0, "wr": float("nan"), "avg": float("nan"), "pf": float("nan"),
        "avg_win": float("nan"), "avg_loss": float("nan"),
        "expect": float("nan"), "expect_d": float("nan"),
    }
    pnls = [t["pnl"] for t in trades]
    n = len(pnls)
    if n == 0:
        return empty
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    dollars = [t["pnl_d"] for t in trades if math.isfinite(t["pnl_d"])]
    return {
        "n": n,
        "wr": 100.0 * len(wins) / n,
        "avg": sum(pnls) / n,
        "pf": (gp / gl) if gl > 0 else float("nan"),
        "avg_win": sum(wins) / len(wins) if wins else float("nan"),
        "avg_loss": sum(losses) / len(losses) if losses else float("nan"),
        "expect": sum(pnls) / n,
        "expect_d": (sum(dollars) / len(dollars)) if dollars else float("nan"),
    }


def _pct(v: float, nd: int = 1) -> str:
    return "—" if not isinstance(v, (int, float)) or not math.isfinite(float(v)) else f"{float(v):.{nd}f}%"


def _num(v: float, nd: int = 2) -> str:
    return "—" if not isinstance(v, (int, float)) or not math.isfinite(float(v)) else f"{float(v):.{nd}f}"


def _cell(key: str, v: float) -> str:
    if key == "n":
        return str(int(v))
    if key == "pf":
        return _num(v, 2)
    if key == "expect_d":
        return format_money(v) if math.isfinite(v) else "—"
    if key == "wr":
        return _pct(v, 1)
    return _pct(v, 2)


METRIC_ROWS = (
    ("n", "Trades", "num"),
    ("wr", "Win rate", "num"),
    ("avg", "Avg P&L %", "num"),
    ("pf", "Profit factor", "num"),
    ("avg_win", "Avg winner %", "num"),
    ("avg_loss", "Avg loser %", "num"),
    ("expect", "Expectancy %", "num"),
    ("expect_d", "Expectancy $", "num"),
)


def write_page(slices: dict[str, dict[str, dict[str, float]]]) -> tuple[Path, Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    esc = html_mod.escape
    sections = []
    md_parts = []
    for name in ("IS", "OOS", "FULL"):
        head = sortable_th("Metric", "text") + "".join(sortable_th(b, "num") for b in BUCKETS)
        body = []
        md_header = ["Metric", *BUCKETS]
        md_parts.append(f"| {' | '.join(md_header)} |")
        md_parts.append("| " + " | ".join("---" for _ in md_header) + " |")
        for key, label, _kind in METRIC_ROWS:
            cells = [f"<td>{esc(label)}</td>"]
            md_cells = [label]
            for b in BUCKETS:
                text = _cell(key, slices[name][b][key])
                cells.append(f"<td>{esc(text)}</td>")
                md_cells.append(text)
            body.append("<tr>" + "".join(cells) + "</tr>")
            md_parts.append("| " + " | ".join(md_cells) + " |")
        sections.append(
            f"<section><h2>{name}</h2>"
            + SWIPE_NOTE_HTML
            + "<div class=\"table-wrap\"><table class=\"sortable\">"
            + f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div></section>"
        )
        md_parts.append("")
    titles = {"IS": "## IS", "OOS": "## OOS", "FULL": "## FULL"}
    md_body = []
    cursor = 0
    # rebuild markdown with headings by walking sections in order
    grouped: dict[str, list[str]] = {}
    current = None
    for name in ("IS", "OOS", "FULL"):
        grouped[name] = []
    # md_parts is sequential blocks of table + blank per slice
    block: list[str] = []
    blocks: list[list[str]] = []
    for line in md_parts:
        if line == "" and block:
            blocks.append(block)
            block = []
        elif line != "":
            block.append(line)
    if block:
        blocks.append(block)
    freeze = [
        "Book: control arm of wpbr_growth_min_pct_3y_ab_20261001, the adopted 3-year positive-growth filter. Closed file WPBR_Closed_261001155729.csv. growth_filter_enabled=true, growth_filter_strict_gt=true, growth_bars=756, growth_min_pct=0.",
        "Zone counts are the already measured n_band values in wpbr_overhead_zone_22_wholebook_20261001/trade_zone_counts.csv. A qualifying zone has its lower edge strictly above the active entry zone's upper edge, and that gap is 22% or less of the upper edge. The count is taken on the day before the buy.",
        "Buckets are 0, 1, 2, 3, 4, and 5 or more. They were named in the request. They were not searched.",
        "In-sample (IS) is DATE_OPENED before 2024-01-01. Out of sample (OOS) is DATE_OPENED on or after 2024-01-01. FULL is both. Out of sample is report-only.",
        "Win rate is the share of closed trades with P&L percent above zero. Profit factor (PF) is the sum of winning P&L percents divided by the absolute sum of losing P&L percents. Average winner and average loser use those same percent results. Expectancy percent is the average closed P&L percent. Expectancy dollars is the average closed P&L dollars.",
        "Measurement only. No bucket was chosen as a buy rule. Research only. Not gold. Not DailyRun.",
    ]
    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>WPBR performance by 22% zone count</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; }}
*{{box-sizing:border-box}}
body{{margin:0;font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header,main{{max-width:1100px;margin:0 auto;padding:1rem}}
h1{{font-size:1.35rem;margin:0 0 .4rem}}
h2{{font-size:1.05rem;margin:0 0 .5rem}}
.muted{{color:var(--muted)}}
.callout,section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.9rem 1rem;margin:1rem 0}}
pre{{white-space:pre-wrap;font-size:.9rem}}
th,td{{border-bottom:1px solid var(--line);padding:.35rem .45rem;text-align:right;white-space:nowrap}}
th:first-child,td:first-child{{text-align:left}}
{SORTABLE_TH_CSS}
{RESPONSIVE_TABLE_CSS}
@media (max-width: 800px) {{
  table.sortable > thead > tr > th.sortable-th:first-child,
  table.sortable > tbody > tr > td:first-child {{ background:#1a2332; color:#e7ecf3; }}
}}
</style></head><body>
<header>
<h1>WPBR results by overhead zone count</h1>
<p class="muted">Pivot Break and Retest (WPBR). Adopted 3-year-growth book. Measurement only. No new filter. Click a column header to sort. Swipe sideways to see more columns.</p>
</header>
<main>
<div class="callout"><h2>What you asked</h2>
<pre>{esc(REQUEST_PROMPT.strip())}</pre>
<p><strong>In plain English.</strong> {esc(LAYMAN)}</p>
</div>
<section><h2>How to read the tables</h2>
<p class="muted">IS is in-sample: buys before 2024. OOS is out of sample: 2024 onward. FULL is both. Win rate (WR) is the share of trades that made money. Profit factor (PF) compares the size of the winners with the size of the losers. Expectancy percent is the same average as Avg P&amp;L %. Expectancy $ is that average in dollars. Out of sample is shown for reading. It was not used to pick a bucket.</p>
</section>
{''.join(sections)}
<section><h2>Freeze</h2><ul>{''.join(f'<li>{esc(line)}</li>' for line in freeze)}</ul></section>
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    html_path = OUT / "compare.html"
    html_path.write_text(page, encoding="utf-8")
    md = [
        "# WPBR results by overhead zone count",
        "",
        "Pivot Break and Retest (WPBR). Measurement only. No new filter.",
        "",
        "## What you asked",
        "",
        REQUEST_PROMPT.strip(),
        "",
        "## In plain English",
        "",
        LAYMAN,
        "",
    ]
    for name, block in zip(("IS", "OOS", "FULL"), blocks):
        md.extend([f"## {name}", ""])
        md.extend(block)
        md.append("")
    md.extend(["## Freeze", ""])
    md.extend(f"- {line}" for line in freeze)
    md_path = OUT / "BASELINE.md"
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    return html_path, md_path


def main() -> int:
    rows = load_rows()
    slices: dict[str, dict[str, dict[str, float]]] = {}
    for name, pred in (
        ("IS", lambda t: t["opened"] < IS_CUT),
        ("OOS", lambda t: t["opened"] >= IS_CUT),
        ("FULL", lambda t: True),
    ):
        chosen = [t for t in rows if pred(t)]
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for t in chosen:
            grouped[t["bucket"]].append(t)
        slices[name] = {b: _metrics(grouped.get(b, [])) for b in BUCKETS}
    html_path, md_path = write_page(slices)
    full = slices["FULL"]
    bits = [f"{b} n={int(full[b]['n'])} avg={_pct(full[b]['avg'])}" for b in BUCKETS]
    msg = "Zone-count buckets, full book: " + "; ".join(bits)
    print(msg, flush=True)
    print(f"wrote {html_path}", flush=True)
    _notify([html_path, md_path], msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
