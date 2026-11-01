#!/usr/bin/env python3
"""STOCK_SUMMARY + UNIVERSE_RECOMMENDATION for maxrsi60 stamp (after enrich/post-run)."""
from __future__ import annotations

import html as html_mod
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "drive" / "paul_experiments") not in sys.path:
    sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    format_money,
    overlay_ann_ror_max_dd,
)

STAMP = "rsi_ob_neutral_rsi70_atr5_ts20_maxrsi60_20260911"
OUT = ROOT / "drive" / "paul_experiments" / STAMP
PRIOR = "rsi_ob_neutral_rsi70_atr5_ts20_20260911"
SUMMARY = OUT / "RSIN_Summary_20260911.csv"
CLOSED = OUT / "RSIN_Closed_20260911.csv"
PT_CLOSED = OUT / "closed_PaulTwenty.csv"
PT_BOOK = OUT / "compare_paultwenty_book.csv"
FULL_METRICS = OUT / "compare_book_metrics.csv"
ASK = (
    "lets adopt this ENTRY_max_rsi_60 and please five me a summary file of IS "
    "so i can pick a univwrse. feel free to make a universe recomendation"
)
NOTIONAL = 10_000.0
ACCOUNT = DEFAULT_INITIAL_ACCOUNT
IS_CUT = pd.Timestamp("2024-01-01")

SORT_CSS = """
th.sortable-th { cursor: pointer; user-select: none; white-space: nowrap; }
th.sortable-th:hover { background: #e2e8f0; }
th.sortable-th .sort-ind::after { content: " \\2195"; opacity: .35; font-size: .85em; }
th.sortable-th.sort-asc .sort-ind::after { content: " \\2191"; opacity: .9; }
th.sortable-th.sort-desc .sort-ind::after { content: " \\2193"; opacity: .9; }
body { font-family: Segoe UI, system-ui, sans-serif; margin: 1.5rem; color: #0f172a; background: #f8fafc; }
h1 { font-size: 1.35rem; } h2 { font-size: 1.1rem; border-bottom: 1px solid #cbd5e1; padding-bottom: .2rem; }
.meta { color: #475569; max-width: 78rem; }
.ask { background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; padding: .75rem 1rem; margin: .75rem 0; max-width: 78rem; }
.insight { background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .75rem 1rem; margin: .75rem 0; max-width: 78rem; }
.caveat { color: #9a3412; }
table.sortable { border-collapse: collapse; background: #fff; font-size: .84rem; margin: .5rem 0 1rem; }
table.sortable th, table.sortable td { border: 1px solid #e2e8f0; padding: .32rem .5rem; text-align: left; }
table.sortable th { background: #f1f5f9; }
.good { color: #166534; } .mixed { color: #854d0e; } .poor { color: #991b1b; }
"""
SORT_JS = r"""
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
  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("th.sortable-th").forEach(function (th, col) {
      th.addEventListener("click", function () {
        var type = th.dataset.sort || "text";
        var dir = th.dataset.dir === "asc" ? -1 : 1;
        table.querySelectorAll("th.sortable-th").forEach(function (h) {
          h.dataset.dir = ""; h.classList.remove("sort-asc", "sort-desc");
        });
        th.dataset.dir = dir === 1 ? "asc" : "desc";
        th.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
        sortTable(table, col, type, dir);
      });
    });
  });
})();
</script>
"""


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _f(x, d=2):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return float("nan")
    return v if np.isfinite(v) else float("nan")


def _pct_str(x, d=2):
    v = _f(x)
    return f"{v:.{d}f}%" if np.isfinite(v) else "—"


def _num_str(x, d=2):
    v = _f(x)
    return f"{v:.{d}f}" if np.isfinite(v) else "—"


def fit_bucket(fit_raw: object) -> str:
    s = str(fit_raw or "").strip().upper()
    if not s or s in ("NAN", "NONE", "—", "-"):
        return ""
    if "HIGH" in s:
        return "High"
    if "MED" in s:
        return "Medium"
    if "LOW" in s:
        return "Low"
    return s.title()


def plain_fit(row: dict) -> tuple[str, str]:
    """Return (label, css_class) good/mixed/poor one-liner basis."""
    n = int(_f(row.get("n")) or 0)
    wr = _f(row.get("win_pct"))
    avg = _f(row.get("avg_pnl"))
    fit = fit_bucket(row.get("fit"))
    if n <= 0:
        return "no trades", "mixed"
    if fit == "High" or (np.isfinite(avg) and avg >= 2.0 and np.isfinite(wr) and wr >= 55):
        return "good — tends to work with this cool-off + RSI70 exit", "good"
    if fit == "Low" or (np.isfinite(avg) and avg < 0) or (np.isfinite(wr) and wr < 45 and n >= 3):
        return "poor — weak or negative under this freeze", "poor"
    return "mixed — usable but not a clear edge name", "mixed"


def load_summary_rows() -> pd.DataFrame:
    if not SUMMARY.is_file():
        return pd.DataFrame()
    df = pd.read_csv(SUMMARY)
    return df


def _slice_stats(g: pd.DataFrame | None) -> tuple[int, float, float, float, float]:
    """Return n, win%, avg%, worst%, avg_days for a Closed slice."""
    if g is None or len(g) == 0:
        return 0, float("nan"), float("nan"), float("nan"), float("nan")
    pnls = g["_pnl"].to_numpy(dtype=float)
    days = g["_days"].to_numpy(dtype=float)
    wins = pnls[np.isfinite(pnls) & (pnls > 0)]
    n = int(np.isfinite(pnls).sum())
    wr = 100.0 * len(wins) / n if n else float("nan")
    avg = float(np.nanmean(pnls))
    worst = float(np.nanmin(pnls))
    avg_days = float(np.nanmean(days)) if np.any(np.isfinite(days)) else float("nan")
    return n, wr, avg, worst, avg_days


def closed_by_symbol() -> dict[str, pd.DataFrame]:
    if not CLOSED.is_file():
        return {}
    c = pd.read_csv(CLOSED)
    c["SYMBOL"] = c["SYMBOL"].astype(str).str.strip().str.upper()
    # normalize pnl
    if "PNL_PCT" in c.columns:
        c["_pnl"] = (
            c["PNL_PCT"].astype(str).str.replace("%", "", regex=False).astype(float)
        )
    else:
        c["_pnl"] = np.nan
    if "DAYS_HELD" in c.columns:
        c["_days"] = pd.to_numeric(c["DAYS_HELD"], errors="coerce")
    else:
        c["_days"] = np.nan
    # entry date for IS/OOS
    open_col = "DATE_OPENED" if "DATE_OPENED" in c.columns else None
    if open_col:
        c["_opened"] = pd.to_datetime(c[open_col], errors="coerce")
    else:
        c["_opened"] = pd.NaT
    out = {}
    for sym, g in c.groupby("SYMBOL"):
        out[str(sym)] = g
    return out


def build_stock_table() -> pd.DataFrame:
    summ = load_summary_rows()
    by = closed_by_symbol()
    rows = []
    # Prefer Summary as spine; fall back to Closed-only symbols
    syms = set()
    if not summ.empty:
        col = "SYMBOL" if "SYMBOL" in summ.columns else summ.columns[0]
        syms.update(str(x).strip().upper() for x in summ[col].dropna())
    syms.update(by.keys())
    for sym in sorted(syms):
        if not sym:
            continue
        srow = {}
        if not summ.empty and "SYMBOL" in summ.columns:
            hit = summ[summ["SYMBOL"].astype(str).str.upper() == sym]
            if not hit.empty:
                srow = hit.iloc[0].to_dict()
        g = by.get(sym)
        n, wr, avg, worst, avg_days = _slice_stats(g)
        if n <= 0:
            wr = _f(srow.get("WIN_PCT") or srow.get("WinPct"))
            avg = _f(
                str(srow.get("AVG_PNL_PCT") or srow.get("AVG_PNL") or "")
                .replace("%", "")
            )
            worst = float("nan")
            avg_days = _f(srow.get("AVG_DAYS_HELD") or srow.get("AVG_DAYS"))
            n = int(_f(srow.get("TRADES") or srow.get("N") or 0) or 0)
        # IS / OOS slices (entry < / >= 2024-01-01) — primary for universe pick
        if g is not None and "_opened" in g.columns:
            g_is = g[g["_opened"] < IS_CUT]
            g_oos = g[g["_opened"] >= IS_CUT]
        else:
            g_is = g_oos = None
        n_is, wr_is, avg_is, worst_is, days_is = _slice_stats(g_is)
        n_oos, wr_oos, avg_oos, worst_oos, days_oos = _slice_stats(g_oos)
        # FIT columns vary
        fit = (
            srow.get("FIT")
            or srow.get("FIT_LABEL")
            or srow.get("ROBUST_FIT")
            or srow.get("PaulFit")
            or ""
        )
        expect = _f(
            str(srow.get("EXPECTANCY_PCT") or srow.get("EXPECTANCY") or avg)
            .replace("%", "")
        )
        if not np.isfinite(expect):
            expect = avg
        sheet = _f(
            str(srow.get("SHEET_PNL") or srow.get("TOTAL_PNL_DOLLARS") or srow.get("PNL_DOLLARS") or "")
            .replace("$", "")
            .replace(",", "")
        )
        # Plain-English fit prefers IS quality (universe pick should not use OOS)
        is_row = {
            "n": n_is if n_is > 0 else n,
            "win_pct": wr_is if n_is > 0 else wr,
            "avg_pnl": avg_is if n_is > 0 else avg,
            "fit": fit_bucket(fit) or str(fit),
        }
        label, cls = plain_fit(is_row)
        row = {
            "symbol": sym,
            "n": n,
            "win_pct": wr,
            "avg_pnl": avg,
            "expectancy": expect,
            "sheet_pnl": sheet,
            "worst": worst,
            "avg_days": avg_days,
            "n_is": n_is,
            "win_is": wr_is,
            "avg_is": avg_is,
            "worst_is": worst_is,
            "days_is": days_is,
            "n_oos": n_oos,
            "win_oos": wr_oos,
            "avg_oos": avg_oos,
            "worst_oos": worst_oos,
            "days_oos": days_oos,
            "fit": fit_bucket(fit) or str(fit),
            "plain": label,
            "plain_cls": cls,
        }
        rows.append(row)
    return pd.DataFrame(rows)


def book_from_closed_csv(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    df = pd.read_csv(path)
    if df.empty:
        return {}
    trades = []
    for _, r in df.iterrows():
        pnl = float(str(r.get("PNL_PCT") or "0").replace("%", ""))
        days = int(float(r.get("DAYS_HELD") or 0) or 0)
        dolls = float(r.get("PNL_DOLLARS") or (NOTIONAL * pnl / 100.0))
        trades.append(
            {
                "opened": pd.Timestamp(r.get("DATE_OPENED")),
                "closed": pd.Timestamp(r.get("DATE_CLOSED")),
                "pnl": pnl,
                "pnl_d": dolls,
                "days": days,
                "exit_type": str(r.get("EXIT_TYPE") or ""),
            }
        )

    def metrics(subset: list[dict], label: str) -> dict:
        n = len(subset)
        if n <= 0:
            return {"slice": label, "n_trades": 0, "win_pct": float("nan"),
                    "avg_pnl_pct": float("nan"), "max_dd": float("nan"),
                    "ann_ror": float("nan"), "avg_days": float("nan")}
        pnls = np.array([t["pnl"] for t in subset], float)
        days = np.array([t["days"] for t in subset], float)
        wins = pnls[pnls > 0]
        overlay = overlay_ann_ror_max_dd(
            subset, cash=NOTIONAL, initial_account=ACCOUNT,
            pnl_d_key="pnl_d", days_key="days", closed_key="closed",
            opened_key="opened", pnl_pct_key="pnl",
        )
        return {
            "slice": label,
            "n_trades": n,
            "win_pct": 100.0 * len(wins) / n,
            "avg_pnl_pct": float(np.mean(pnls)),
            "max_dd": float(overlay.get("max_dd") or float("nan")),
            "ann_ror": float(overlay.get("ann_ror") or float("nan")),
            "avg_days": float(np.mean(days)),
        }

    full = metrics(trades, "FULL")
    is_ = metrics([t for t in trades if t["opened"] < IS_CUT], "IS")
    oos = metrics([t for t in trades if t["opened"] >= IS_CUT], "OOS")
    return {"FULL": full, "IS": is_, "OOS": oos}


def control_book_from_metrics() -> dict[str, dict]:
    if not FULL_METRICS.is_file():
        return book_from_closed_csv(OUT / "closed_CONTROL.csv")
    df = pd.read_csv(FULL_METRICS)
    ctrl = df[df["arm"] == "CONTROL"]
    out = {}
    for _, r in ctrl.iterrows():
        out[str(r["slice"])] = {
            "slice": str(r["slice"]),
            "n_trades": int(r["n_trades"]),
            "win_pct": float(r["win_pct"]),
            "avg_pnl_pct": float(r["avg_pnl_pct"]),
            "max_dd": float(r["max_dd"]),
            "ann_ror": float(r.get("ann_ror") or float("nan")),
            "avg_days": float(r.get("avg_days") or float("nan")),
        }
    return out


def write_stock_summary(df: pd.DataFrame) -> None:
    n_high = int((df["fit"] == "High").sum()) if "fit" in df.columns else 0
    n_med = int((df["fit"] == "Medium").sum()) if "fit" in df.columns else 0
    n_low = int((df["fit"] == "Low").sum()) if "fit" in df.columns else 0
    n_good = int((df["plain_cls"] == "good").sum())
    n_mixed = int((df["plain_cls"] == "mixed").sum())
    n_poor = int((df["plain_cls"] == "poor").sum())
    is_traded = df[df["n_is"] > 0] if "n_is" in df.columns else df
    n_is_syms = int(len(is_traded))

    md = [
        f"# STOCK_SUMMARY — {STAMP}",
        "",
        "Research only. Not gold. Not DailyRun.",
        "",
        "## What you asked",
        "",
        ASK,
        "",
        "## In plain English",
        "",
        "One row per stock under the preference-adopted freeze (trigger RSI < 60, sell RSI 70,",
        "ATR% ≥5, 20-day time stop). **IS columns** (entry before 2024-01-01) are the ones to",
        "use when picking a universe — OOS is report-only. Plain-English good/mixed/poor is",
        "scored from IS quality. See also `IS_STOCK_SUMMARY.md` / `.html` for the IS-only pick list.",
        "",
        "## Rollup",
        "",
        f"- Symbols with any trades: **{len(df)}** · with IS trades: **{n_is_syms}**",
        f"- FIT High / Medium / Low: **{n_high} / {n_med} / {n_low}** (blank FIT if not scored)",
        f"- Plain-English good / mixed / poor (IS-based): **{n_good} / {n_mixed} / {n_poor}**",
        "",
        "Deep briefs: `RSIN_SymbolAssessments_20260911.html`. Sortable: `STOCK_SUMMARY.html`, `IS_STOCK_SUMMARY.html`.",
        "",
        "| Symbol | IS N | IS Win% | IS Avg% | IS Worst% | FULL N | FULL Avg% | OOS N | OOS Avg% | FIT | Plain English |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    sort_df = df.sort_values(
        ["plain_cls", "avg_is", "avg_pnl"],
        ascending=[True, False, False],
        na_position="last",
    )
    for _, r in sort_df.iterrows():
        md.append(
            f"| {r['symbol']} | {int(r['n_is'])} | {_pct_str(r['win_is'])} | "
            f"{_pct_str(r['avg_is'], 3)} | {_pct_str(r['worst_is'])} | "
            f"{int(r['n'])} | {_pct_str(r['avg_pnl'], 3)} | "
            f"{int(r['n_oos'])} | {_pct_str(r['avg_oos'], 3)} | "
            f"{r['fit'] or '—'} | {r['plain']} |"
        )
    (OUT / "STOCK_SUMMARY.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    # Dedicated IS pick file (user asked for IS summary to choose universe)
    is_md = [
        f"# IS_STOCK_SUMMARY — {STAMP}",
        "",
        "In-sample only (entry_date < 2024-01-01). Use this to pick a research universe.",
        "OOS is not used for ranking. Research only · not gold · not DailyRun.",
        "",
        "## What you asked",
        "",
        ASK,
        "",
        "## In plain English",
        "",
        "How each stock behaved **before 2024** under the deeper cool-off system. Sort by",
        "IS Avg% / IS Win% / plain-English good to build a watchlist. Filtering High-FIT",
        "or good names here is selection bias on this history — fine as a research list,",
        "not a silent DailyRun wire.",
        "",
        f"Symbols with IS trades: **{n_is_syms}** · plain good/mixed/poor: "
        f"**{n_good} / {n_mixed} / {n_poor}**",
        "",
        "| Symbol | IS N | IS Win% | IS Avg% | IS Worst% | IS Avg days | FIT | Plain English |",
        "|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for _, r in is_traded.sort_values(
        ["plain_cls", "avg_is"], ascending=[True, False], na_position="last"
    ).iterrows():
        is_md.append(
            f"| {r['symbol']} | {int(r['n_is'])} | {_pct_str(r['win_is'])} | "
            f"{_pct_str(r['avg_is'], 3)} | {_pct_str(r['worst_is'])} | "
            f"{_num_str(r['days_is'], 1)} | {r['fit'] or '—'} | {r['plain']} |"
        )
    (OUT / "IS_STOCK_SUMMARY.md").write_text("\n".join(is_md) + "\n", encoding="utf-8")

    headers = [
        ("Symbol", "text"),
        ("IS N", "num"), ("IS Win %", "num"), ("IS Avg %", "num"), ("IS Worst %", "num"),
        ("FULL N", "num"), ("FULL Avg %", "num"),
        ("OOS N", "num"), ("OOS Avg %", "num"),
        ("FIT", "text"), ("Plain English", "text"),
    ]
    th = "".join(sortable_th(a, b) for a, b in headers)
    body = []
    for _, r in df.iterrows():
        body.append(
            "<tr>"
            f"<td>{html_mod.escape(r['symbol'])}</td>"
            f"<td>{int(r['n_is'])}</td>"
            f"<td>{_pct_str(r['win_is'])}</td>"
            f"<td>{_pct_str(r['avg_is'], 3)}</td>"
            f"<td>{_pct_str(r['worst_is'])}</td>"
            f"<td>{int(r['n'])}</td>"
            f"<td>{_pct_str(r['avg_pnl'], 3)}</td>"
            f"<td>{int(r['n_oos'])}</td>"
            f"<td>{_pct_str(r['avg_oos'], 3)}</td>"
            f"<td>{html_mod.escape(str(r['fit'] or '—'))}</td>"
            f"<td class='{r['plain_cls']}'>{html_mod.escape(r['plain'])}</td>"
            "</tr>"
        )
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>STOCK_SUMMARY — {STAMP}</title><style>{SORT_CSS}</style></head>
<body>
<h1>Per-stock summary — maxrsi60 control (IS highlighted)</h1>
<p class="meta">Stamp <code>{STAMP}</code> · research only · not gold · not DailyRun · click headers to sort</p>
<div class="ask">
<h2 style="margin-top:0;border:0">What you asked</h2>
<blockquote class="meta">{html_mod.escape(ASK)}</blockquote>
<h2>In plain English</h2>
<p>How each stock behaved under the preference-adopted freeze: buy only after a deeper
Relative Strength Index (RSI) cool-off (trigger RSI &lt; 60), Average True Range percent
(ATR%) ≥5, sell when RSI ≥70, flatten by day 20. <strong>Use IS columns to pick a universe</strong>
(entry before 2024). OOS is a holdout check only. Dedicated IS table:
<code>IS_STOCK_SUMMARY.html</code>.</p>
</div>
<div class="insight">
<p><strong>Rollup:</strong> {len(df)} symbols ({n_is_syms} with IS trades) · FIT High/Med/Low = {n_high}/{n_med}/{n_low}
· plain good/mixed/poor (IS-based) = {n_good}/{n_mixed}/{n_poor}.</p>
<p class="caveat">Selection honesty: ENTRY_max_rsi_60 was HOLD under <code>{PRIOR}</code>;
preference-adopted — not a KEEP from metrics. Filtering later by FIT/IS on this same history
is in-sample selection bias.</p>
</div>
<p class="meta">Deep briefs: <code>RSIN_SymbolAssessments_20260911.html</code> · IS-only:
<code>IS_STOCK_SUMMARY.html</code>.</p>
<table class="sortable"><thead><tr>{th}</tr></thead><tbody>{"".join(body)}</tbody></table>
{SORT_JS}
</body></html>
"""
    (OUT / "STOCK_SUMMARY.html").write_text(html, encoding="utf-8")

    # IS-only HTML
    is_headers = [
        ("Symbol", "text"), ("IS N", "num"), ("IS Win %", "num"), ("IS Avg %", "num"),
        ("IS Worst %", "num"), ("IS Avg days", "num"), ("FIT", "text"), ("Plain English", "text"),
    ]
    is_th = "".join(sortable_th(a, b) for a, b in is_headers)
    is_body = []
    for _, r in is_traded.iterrows():
        is_body.append(
            "<tr>"
            f"<td>{html_mod.escape(r['symbol'])}</td>"
            f"<td>{int(r['n_is'])}</td>"
            f"<td>{_pct_str(r['win_is'])}</td>"
            f"<td>{_pct_str(r['avg_is'], 3)}</td>"
            f"<td>{_pct_str(r['worst_is'])}</td>"
            f"<td>{_num_str(r['days_is'], 1)}</td>"
            f"<td>{html_mod.escape(str(r['fit'] or '—'))}</td>"
            f"<td class='{r['plain_cls']}'>{html_mod.escape(r['plain'])}</td>"
            "</tr>"
        )
    is_html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>IS_STOCK_SUMMARY — {STAMP}</title><style>{SORT_CSS}</style></head>
<body>
<h1>IS per-stock summary — pick a universe</h1>
<p class="meta">In-sample only (entry &lt; 2024-01-01) · stamp <code>{STAMP}</code> · research only</p>
<div class="ask">
<h2 style="margin-top:0;border:0">What you asked</h2>
<blockquote class="meta">{html_mod.escape(ASK)}</blockquote>
<h2>In plain English</h2>
<p>Sort by IS Avg% / Win% / plain-English good to choose names for a research universe.
Do not retune on OOS. High-FIT filters on this table are selection-biased — watchlist OK,
not a silent wire.</p>
</div>
<div class="insight">
<p><strong>{n_is_syms}</strong> symbols with IS trades · plain good/mixed/poor =
{n_good}/{n_mixed}/{n_poor}.</p>
</div>
<table class="sortable"><thead><tr>{is_th}</tr></thead><tbody>{"".join(is_body)}</tbody></table>
{SORT_JS}
</body></html>
"""
    (OUT / "IS_STOCK_SUMMARY.html").write_text(is_html, encoding="utf-8")


def write_universe_rec(stock_df: pd.DataFrame) -> str:
    full = control_book_from_metrics()
    pt = book_from_closed_csv(PT_CLOSED)
    if PT_BOOK.is_file() and not pt:
        bdf = pd.read_csv(PT_BOOK)
        pt = {}
        for _, r in bdf.iterrows():
            pt[str(r["slice"])] = {
                "n_trades": int(r["n_trades"]),
                "win_pct": float(r["win_pct"]),
                "avg_pnl_pct": float(r["avg_pnl_pct"]),
                "max_dd": float(r["max_dd"]),
                "ann_ror": float(r.get("ann_ror") or float("nan")),
                "avg_days": float(r.get("avg_days") or float("nan")),
            }

    n_high = int((stock_df["fit"] == "High").sum())
    n_med = int((stock_df["fit"] == "Medium").sum())
    n_low = int((stock_df["fit"] == "Low").sum())
    n_good = int((stock_df["plain_cls"] == "good").sum())
    n_poor = int((stock_df["plain_cls"] == "poor").sum())

    f_full = full.get("FULL", {})
    f_is = full.get("IS", {})
    f_oos = full.get("OOS", {})
    p_full = pt.get("FULL", {})
    p_is = pt.get("IS", {})
    p_oos = pt.get("OOS", {})

    # Recommendation logic: quality-over-count, judge primarily on IS
    verdict_bits = []
    rec = "hybrid"
    cmp_f = f_is if f_is and int(f_is.get("n_trades", 0) or 0) >= 20 else f_full
    cmp_p = p_is if p_is and int(p_is.get("n_trades", 0) or 0) >= 10 else p_full
    slice_label = "IS" if cmp_f is f_is else "FULL"
    if cmp_p and cmp_f:
        if (
            np.isfinite(cmp_p.get("avg_pnl_pct", float("nan")))
            and np.isfinite(cmp_f.get("avg_pnl_pct", float("nan")))
            and float(cmp_p["avg_pnl_pct"]) + 0.05 >= float(cmp_f["avg_pnl_pct"])
            and float(cmp_p.get("max_dd", 99)) <= float(cmp_f.get("max_dd", 99)) + 1.0
            and int(cmp_p.get("n_trades", 0)) >= 20
        ):
            rec = "PaulTwenty"
            verdict_bits.append(
                f"On {slice_label}, PaulTwenty matches or beats FullUniverse on Avg% / MaxDD "
                "with usable N — lean PaulTwenty for research focus."
            )
        elif n_high >= 8 and n_poor > n_good:
            rec = "High-FIT / IS-good hybrid (watchlist)"
            verdict_bits.append(
                "Full book is diluted by many poor-fit names; use IS_STOCK_SUMMARY good / High-FIT "
                "names as the research watchlist — selection-biased on this history, not a silent wire."
            )
        else:
            rec = "FullUniverse (research) + watch IS-good / High-FIT"
            verdict_bits.append(
                "Keep FullUniverse as the stamped research book so N stays honest; "
                "use IS_STOCK_SUMMARY good / High-FIT names as a watchlist, not a silent wire."
            )
    else:
        rec = "FullUniverse (research) + watch IS-good / High-FIT"
        verdict_bits.append(
            "PaulTwenty replay missing or thin — default to FullUniverse research book "
            "and treat IS-good / High-FIT names as a watchlist only."
        )
    if f_is:
        verdict_bits.append(
            f"FullUniverse IS: N={int(f_is.get('n_trades', 0)):,} "
            f"Win%={_pct_str(f_is.get('win_pct'))} Avg%={_pct_str(f_is.get('avg_pnl_pct'), 3)} "
            f"MaxDD={_pct_str(f_is.get('max_dd'))}."
        )
    if p_is:
        verdict_bits.append(
            f"PaulTwenty IS: N={int(p_is.get('n_trades', 0)):,} "
            f"Win%={_pct_str(p_is.get('win_pct'))} Avg%={_pct_str(p_is.get('avg_pnl_pct'), 3)} "
            f"MaxDD={_pct_str(p_is.get('max_dd'))}."
        )

    lines = [
        f"# UNIVERSE_RECOMMENDATION — {STAMP}",
        "",
        "Research recommendation only. Not gold. Not DailyRun. Do not wire from this note.",
        "",
        "## What you asked",
        "",
        ASK,
        "",
        "## In plain English",
        "",
        "Same system freeze (trigger RSI < 60, ATR% ≥5, sell RSI ≥70, 20-day time stop) on",
        "the full CSV universe vs PaulTwenty. Quality (Avg PnL%, win%, Max DD) matters more",
        "than how many trades show up. Filtering to High-FIT names using this same history",
        "is selection bias — fine as a research watchlist, not a silent promotion.",
        "",
        "## Books under the SAME freeze",
        "",
        "### FullUniverse (CONTROL)",
        "",
    ]
    for sl in ("FULL", "IS", "OOS"):
        b = full.get(sl, {})
        if not b:
            lines.append(f"- **{sl}**: missing")
            continue
        lines.append(
            f"- **{sl}** N={int(b.get('n_trades', 0)):,} Win%={_pct_str(b.get('win_pct'))} "
            f"Avg%={_pct_str(b.get('avg_pnl_pct'), 3)} MaxDD={_pct_str(b.get('max_dd'))} "
            f"AnnROR={_pct_str(b.get('ann_ror'))}"
        )
    lines += ["", "### PaulTwenty (same freeze replay)", ""]
    if not p_full:
        lines.append("- Missing `closed_PaulTwenty.csv` / book metrics.")
    else:
        for sl in ("FULL", "IS", "OOS"):
            b = pt.get(sl, {})
            if not b:
                lines.append(f"- **{sl}**: missing")
                continue
            lines.append(
                f"- **{sl}** N={int(b.get('n_trades', 0)):,} Win%={_pct_str(b.get('win_pct'))} "
                f"Avg%={_pct_str(b.get('avg_pnl_pct'), 3)} MaxDD={_pct_str(b.get('max_dd'))} "
                f"AnnROR={_pct_str(b.get('ann_ror'))}"
            )
    lines += [
        "",
        "## FIT / fit rollup (FullUniverse control Closed)",
        "",
        f"- FIT High / Medium / Low: **{n_high} / {n_med} / {n_low}**",
        f"- Plain-English good / mixed / poor: "
        f"**{n_good} / {int((stock_df['plain_cls']=='mixed').sum())} / {n_poor}**",
        "",
        "## Recommendation",
        "",
        f"**Verdict: {rec}**",
        "",
    ]
    for b in verdict_bits:
        lines.append(f"- {b}")
    lines += [
        "",
        "### Honesty / process",
        "",
        f"- Prior freeze `{PRIOR}`: ENTRY_max_rsi_60 was **HOLD** (not KEEP); this stamp is preference adopt.",
        "- OOS is report-only — do not retune the gate or universe on OOS lifts.",
        "- High-FIT-only lists picked on this Closed book are **in-sample selection**; "
        "re-score on a holdout universe or walk-forward before stronger claims.",
        "- Research only · not gold · not DailyRun.",
        "",
    ]
    text = "\n".join(lines)
    (OUT / "UNIVERSE_RECOMMENDATION.md").write_text(text + "\n", encoding="utf-8")

    # Short HTML companion
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>UNIVERSE_RECOMMENDATION — {STAMP}</title><style>{SORT_CSS}</style></head>
<body>
<h1>Universe recommendation</h1>
<div class="ask">
<h2 style="margin-top:0;border:0">What you asked</h2>
<blockquote>{html_mod.escape(ASK)}</blockquote>
<h2>In plain English</h2>
<p>Same freeze on FullUniverse vs PaulTwenty. Judge quality over trade count.
High-FIT filters on this history are selection-biased — research watchlist only.</p>
</div>
<div class="insight">
<p><strong>Verdict: {html_mod.escape(rec)}</strong></p>
<ul>{"".join(f"<li>{html_mod.escape(b)}</li>" for b in verdict_bits)}</ul>
<p class="caveat">Research only · not gold · not DailyRun · OOS report-only.</p>
</div>
<pre class="meta" style="white-space:pre-wrap">{html_mod.escape(text)}</pre>
</body></html>
"""
    (OUT / "UNIVERSE_RECOMMENDATION.html").write_text(html, encoding="utf-8")
    return rec


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    OUT.mkdir(parents=True, exist_ok=True)
    df = build_stock_table()
    if df.empty:
        print("WARN empty stock table — Summary/Closed missing?", flush=True)
    else:
        write_stock_summary(df)
        print(f"Wrote STOCK_SUMMARY.md/html  symbols={len(df)}", flush=True)
    rec = write_universe_rec(df if not df.empty else pd.DataFrame(
        columns=["fit", "plain_cls"]
    ))
    print(f"Wrote UNIVERSE_RECOMMENDATION.*  verdict={rec}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
