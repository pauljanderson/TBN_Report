#!/usr/bin/env python3
"""Dated yfinance option-chain archive (snapshot history, not a trading system).

Stores one row per contract: symbol, expiry, type (C/P), strike, bid, ask, mid,
lastPrice, volume, openInterest, impliedVolatility, plus snapshot_date / fetched_at.

Default universe is PaulTwenty + UNH (N=21) via data/options/options_universe.csv.
Default expiries: first 6 listed (nearest first). Same calendar day overwrites.

Yahoo Finance (yfinance) quotes are a live/delayed snapshot — homemade history,
not official end-of-day OPRA / CBOE. Archive only; not gold; not a DailyRun sleeve.

Exit 0 by default (--soft-fail) so Yahoo flakes cannot break stock DailyRun.
"""

from __future__ import annotations

import argparse
import html as html_mod
import json
import sys
import time
import traceback
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from option_chain_liquidity import (  # noqa: E402
    _last_close,
    _mid,
    _parse_option_expiry,
    _yahoo_call,
)

try:
    import yfinance as yf
except ImportError as e:  # pragma: no cover
    print("Install yfinance: pip install yfinance", file=sys.stderr)
    raise SystemExit(2) from e

ARCHIVE_ROOT = ROOT / "data" / "options" / "yfinance_chain"
UNIVERSE_CSV = ROOT / "data" / "options" / "options_universe.csv"
DRIVE_OPTIONS = ROOT / "drive" / "options"
STAMP_DIR = ROOT / "drive" / "paul_experiments" / "options_chain_archive_20260917"

DEFAULT_MAX_EXPIRIES = 6
DEFAULT_DELAY_SYMBOL = 0.75
DEFAULT_DELAY_EXPIRY = 0.35

# PaulTwenty (drive/universes/PaulTwenty_universe.csv) + UNH. N=21.
DEFAULT_UNIVERSE: tuple[str, ...] = (
    "NVDA",
    "GOOG",
    "GOOGL",
    "AAPL",
    "MSFT",
    "AMZN",
    "TSM",
    "AVGO",
    "META",
    "TSLA",
    "LLY",
    "JPM",
    "MU",
    "WMT",
    "AMD",
    "V",
    "ASML",
    "XOM",
    "JNJ",
    "MA",
    "UNH",
)

CHAIN_COLS = [
    "snapshot_date",
    "fetched_at",
    "symbol",
    "expiry",
    "type",
    "strike",
    "bid",
    "ask",
    "mid",
    "lastPrice",
    "volume",
    "openInterest",
    "impliedVolatility",
    "contractSymbol",
    "underlying_last",
]

PAUL_ASKED = (
    "i would like to be able to save it on an ongoing basis so we can look at it over time, can we do that?"
)

PLAIN_ENGLISH = (
    "Each run takes a snapshot of Yahoo Finance option quotes for a small list of "
    "big names and saves that day's file. Later you can open any date, pick a "
    "ticker, and sort bid / ask / last / implied volatility. This is homemade "
    "snapshot history so we can look at the same contract over time — not a "
    "trading system, not official exchange end-of-day data."
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_symbols(s: str) -> list[str]:
    return [x.strip().upper() for x in s.split(",") if x.strip()]


def load_universe(path: Path | None, symbols_cli: str) -> list[str]:
    if symbols_cli.strip():
        return _parse_symbols(symbols_cli)
    src = path if path is not None else UNIVERSE_CSV
    if src.exists():
        out: list[str] = []
        for line in src.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            tok = raw.split(",")[0].strip().upper()
            if tok and tok not in out:
                out.append(tok)
        if out:
            return out
    return list(DEFAULT_UNIVERSE)


def ensure_universe_file() -> Path:
    UNIVERSE_CSV.parent.mkdir(parents=True, exist_ok=True)
    if not UNIVERSE_CSV.exists():
        lines = [
            "# Options chain archive universe — edit this file to widen later.",
            "# Freeze 2026-09-17: PaulTwenty + UNH. N=21.",
            "# Archive only (yfinance snapshot). Not a scanner. Not gold.",
            *DEFAULT_UNIVERSE,
        ]
        UNIVERSE_CSV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return UNIVERSE_CSV


def select_first_n_expiries(exps: list[str], n: int) -> list[str]:
    """First N listed expiries, nearest calendar date first. Freeze: N=6."""
    parsed: list[tuple[str, date]] = []
    for e in exps:
        d = _parse_option_expiry(e)
        if d is not None:
            parsed.append((str(e), d))
    parsed.sort(key=lambda x: x[1])
    n = max(1, int(n))
    return [e for e, _ in parsed[:n]]


def _num(v: Any, default: float = float("nan")) -> float:
    try:
        if v is None or (isinstance(v, float) and v != v):
            return default
        if pd.isna(v):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _int(v: Any) -> int:
    x = _num(v, 0.0)
    if x != x:
        return 0
    try:
        return int(x)
    except (TypeError, ValueError):
        return 0


def _normalize_side(df: pd.DataFrame, right: str) -> pd.DataFrame:
    out = df.copy()
    out["right"] = right
    for c, fill in (
        ("bid", float("nan")),
        ("ask", float("nan")),
        ("strike", float("nan")),
        ("lastPrice", float("nan")),
        ("impliedVolatility", float("nan")),
        ("volume", 0),
        ("openInterest", 0),
        ("contractSymbol", ""),
    ):
        if c not in out.columns:
            out[c] = fill
    return out


def fetch_symbol_chains(
    symbol: str,
    max_expiries: int,
    *,
    yahoo_max_retries: int,
    yahoo_base_wait_sec: float,
    delay_between_expiries: float,
    snapshot_date: str,
    fetched_at: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """All strikes on the first N listed expiries. One row per contract."""
    meta: dict[str, Any] = {
        "symbol": symbol,
        "ok": False,
        "n_contracts": 0,
        "expiries": [],
        "note": "",
        "underlying_last": None,
    }
    t = yf.Ticker(symbol)
    try:
        spot = _last_close(t, yahoo_max_retries, yahoo_base_wait_sec)
    except Exception as e:  # noqa: BLE001
        meta["note"] = f"spot_error: {e}"
        spot = float("nan")
    meta["underlying_last"] = None if spot != spot else float(spot)

    try:
        exps = _yahoo_call(lambda: list(t.options), yahoo_max_retries, yahoo_base_wait_sec)
    except Exception as e:  # noqa: BLE001
        meta["note"] = f"options_list_error: {e}"
        return pd.DataFrame(columns=CHAIN_COLS), meta

    if not exps:
        meta["note"] = "no_expiries"
        return pd.DataFrame(columns=CHAIN_COLS), meta

    chosen = select_first_n_expiries(exps, max_expiries)
    meta["expiries"] = chosen
    rows: list[dict[str, Any]] = []
    notes: list[str] = []

    for i, exp in enumerate(chosen):
        try:
            oc = _yahoo_call(lambda e=exp: t.option_chain(e), yahoo_max_retries, yahoo_base_wait_sec)
        except Exception as e:  # noqa: BLE001
            notes.append(f"{exp}: {e}")
            continue
        calls = _normalize_side(oc.calls, "C")
        puts = _normalize_side(oc.puts, "P")
        chain = pd.concat([calls, puts], ignore_index=True)
        for _, r in chain.iterrows():
            bid = _num(r.get("bid"))
            ask = _num(r.get("ask"))
            csym = r.get("contractSymbol")
            rows.append(
                {
                    "snapshot_date": snapshot_date,
                    "fetched_at": fetched_at,
                    "symbol": symbol,
                    "expiry": exp,
                    "type": str(r.get("right") or "")[:1],
                    "strike": _num(r.get("strike")),
                    "bid": bid,
                    "ask": ask,
                    "mid": _mid(bid, ask) if (bid == bid or ask == ask) else float("nan"),
                    "lastPrice": _num(r.get("lastPrice")),
                    "volume": _int(r.get("volume")),
                    "openInterest": _int(r.get("openInterest")),
                    "impliedVolatility": _num(r.get("impliedVolatility")),
                    "contractSymbol": "" if csym is None or (isinstance(csym, float) and csym != csym) else str(csym),
                    "underlying_last": float(spot) if spot == spot else float("nan"),
                }
            )
        if delay_between_expiries > 0 and i + 1 < len(chosen):
            time.sleep(delay_between_expiries)

    df = pd.DataFrame(rows, columns=CHAIN_COLS) if rows else pd.DataFrame(columns=CHAIN_COLS)
    meta["n_contracts"] = int(len(df))
    meta["ok"] = bool(len(df))
    meta["note"] = "; ".join(notes) if notes else ("ok" if meta["ok"] else "empty_chain")
    return df, meta


def symbol_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(
            columns=[
                "symbol",
                "n_contracts",
                "n_calls",
                "n_puts",
                "n_expiries",
                "underlying_last",
                "median_iv",
                "median_spread",
                "median_spread_pct",
                "total_volume",
                "total_oi",
            ]
        )
    work = df.copy()
    work["spread"] = (work["ask"] - work["bid"]).clip(lower=0)
    work["spread_pct"] = work["spread"] / work["mid"].replace(0, float("nan"))
    priced = work["mid"] >= 0.02
    rows = []
    for sym, g in work.groupby("symbol", sort=False):
        gp = g.loc[priced.reindex(g.index).fillna(False)]
        rows.append(
            {
                "symbol": sym,
                "n_contracts": int(len(g)),
                "n_calls": int((g["type"] == "C").sum()),
                "n_puts": int((g["type"] == "P").sum()),
                "n_expiries": int(g["expiry"].nunique()),
                "underlying_last": float(g["underlying_last"].dropna().iloc[0])
                if g["underlying_last"].notna().any()
                else float("nan"),
                "median_iv": float(g["impliedVolatility"].median(skipna=True)),
                "median_spread": float(gp["spread"].median(skipna=True)) if len(gp) else float("nan"),
                "median_spread_pct": float(gp["spread_pct"].median(skipna=True)) if len(gp) else float("nan"),
                "total_volume": int(g["volume"].sum()),
                "total_oi": int(g["openInterest"].sum()),
            }
        )
    return pd.DataFrame(rows)


def write_day_archive(
    df: pd.DataFrame,
    summary: pd.DataFrame,
    manifest: dict[str, Any],
    day_dir: Path,
) -> Path:
    """Idempotent: same calendar day overwrites parquet + manifest (no run-id)."""
    day_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = day_dir / "chain.parquet"
    df.to_parquet(parquet_path, index=False)
    summ_path = day_dir / "symbol_summary.csv"
    summary.to_csv(summ_path, index=False)
    man_path = day_dir / "manifest.json"
    man_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    latest = ARCHIVE_ROOT / "latest.json"
    latest.write_text(
        json.dumps(
            {
                "snapshot_date": manifest.get("snapshot_date"),
                "path": str(day_dir.as_posix()),
                "parquet": str(parquet_path.as_posix()),
                "n_contracts": manifest.get("n_contracts"),
                "n_symbols_ok": manifest.get("n_symbols_ok"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return parquet_path


def list_snapshot_manifests() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not ARCHIVE_ROOT.exists():
        return out
    for man in sorted(ARCHIVE_ROOT.glob("*/manifest.json")):
        try:
            payload = json.loads(man.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        payload["_dir"] = str(man.parent)
        out.append(payload)
    out.sort(key=lambda m: str(m.get("snapshot_date") or ""), reverse=True)
    return out


def load_day_frame(snapshot_date: str) -> pd.DataFrame:
    path = ARCHIVE_ROOT / snapshot_date / "chain.parquet"
    if not path.exists():
        return pd.DataFrame(columns=CHAIN_COLS)
    return pd.read_parquet(path)


def _sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


SORTABLE_TH_CSS = """
th.sortable-th { cursor:pointer; user-select:none; white-space:nowrap; }
th.sortable-th:hover { background:#e2e8f0; }
.sort-ind { display:inline-block; width:0.9em; margin-left:4px; color:#94a3b8; font-size:10px; }
th.sort-asc .sort-ind::after { content:"▲"; color:#334155; }
th.sort-desc .sort-ind::after { content:"▼"; color:#334155; }
tr.total-row th, tr.total-row td { background:#f8fafc; border-top:2px solid #334155; }
"""

SORTABLE_TABLE_SCRIPT = """
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : 0;
    if (type === "text") return s.toUpperCase();
    if (type === "date") {
      var iso = s.match(/(\\d{4})-(\\d{2})-(\\d{2})/);
      if (iso) return parseInt(iso[1] + iso[2] + iso[3], 10);
      return 0;
    }
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
  function bindSortHeader(table, th, col) {
    function onActivate(e) {
      if (e.type === "touchend") e.preventDefault();
      var type = th.dataset.sort || "text";
      var dir = th.dataset.dir === "asc" ? -1 : 1;
      table.querySelectorAll("th.sortable-th").forEach(function (h) {
        h.dataset.dir = "";
        h.classList.remove("sort-asc", "sort-desc");
        h.setAttribute("aria-sort", "none");
      });
      th.dataset.dir = dir === 1 ? "asc" : "desc";
      th.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
      th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
      sortTable(table, col, type, dir);
    }
    th.addEventListener("click", onActivate);
    th.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onActivate(e); }
    });
    th.addEventListener("touchend", onActivate, { passive: false });
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("th.sortable-th").forEach(function (th, col) {
      bindSortHeader(table, th, col);
    });
  });
})();
</script>
"""

PAGE_CSS = f"""
:root {{ color-scheme: light; }}
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 24px; color:#0f172a; background:#fff; }}
h1 {{ font-size: 22px; margin: 0 0 8px; }}
h2 {{ font-size: 16px; margin: 28px 0 8px; }}
.sub, .small {{ color:#475569; font-size:13px; line-height:1.5; }}
.callout {{ background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px 14px; margin:14px 0; }}
.callout h2 {{ margin-top:0; }}
.warn {{ background:#fff7ed; border-color:#fdba74; }}
.table-wrap {{ overflow-x:auto; margin:8px 0; }}
table {{ border-collapse:collapse; font-size:12px; width:100%; }}
th, td {{ border:1px solid #e2e8f0; padding:6px 8px; text-align:left; }}
th {{ background:#f1f5f9; }}
{SORTABLE_TH_CSS}
a {{ color:#1d4ed8; }}
.filters {{ display:flex; flex-wrap:wrap; gap:10px; align-items:end; margin:10px 0 6px; }}
.filters label {{ font-size:12px; color:#334155; display:flex; flex-direction:column; gap:4px; }}
.filters select, .filters input {{ min-width:120px; padding:4px 6px; }}
.muted {{ color:#64748b; }}
"""


def _fmt_num(v: Any, nd: int = 2) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if x != x:
        return "—"
    return f"{x:.{nd}f}"


def _fmt_iv(v: Any) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if x != x:
        return "—"
    return f"{100.0 * x:.1f}%"


def _fmt_pct(v: Any) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if x != x:
        return "—"
    return f"{100.0 * x:.1f}%"


def _asked_block() -> str:
    return f"""
<div class="callout">
  <h2>What you asked</h2>
  <p>{html_mod.escape(PAUL_ASKED)}</p>
  <h2>In plain English</h2>
  <p>{html_mod.escape(PLAIN_ENGLISH)}</p>
  <p class="small">
    <strong>yfinance</strong> is the Yahoo Finance Python library — it returns a live or delayed
    quote snapshot (not a historical CBOE file).
    <strong>Bid</strong> is what buyers are offering;
    <strong>ask</strong> is what sellers want;
    <strong>implied volatility (IV)</strong> is Yahoo’s option-implied vol on that line (shown as a percent).
    Mid is the average of bid and ask when both exist.
  </p>
</div>
"""


def _nav(index_href: str, baseline_href: str | None = None) -> str:
    extra = (
        f' · <a href="{html_mod.escape(baseline_href)}">BASELINE.md</a>'
        if baseline_href
        else ""
    )
    return (
        f'<p class="small"><a href="{html_mod.escape(index_href)}">All snapshot dates</a>'
        f"{extra} · archive only — not a scanner, not gold</p>"
    )


def render_index_html(
    manifests: list[dict[str, Any]],
    *,
    latest_summary: pd.DataFrame | None,
    latest_date: str | None,
    day_href_fn,
    index_title: str,
    baseline_href: str | None,
) -> str:
    date_head = "".join(
        _sortable_th(label, kind)
        for label, kind in (
            ("Snapshot date", "date"),
            ("Fetched (UTC)", "text"),
            ("Names OK", "num"),
            ("Names tried", "num"),
            ("Contracts", "num"),
            ("Expiries / name", "num"),
            ("Warnings", "num"),
            ("Open day", "text"),
        )
    )
    date_rows = []
    for m in manifests:
        d = str(m.get("snapshot_date") or "")
        href = day_href_fn(d)
        warns = m.get("n_symbols_failed") or 0
        date_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(d)}</td>"
            f"<td>{html_mod.escape(str(m.get('fetched_at') or ''))}</td>"
            f"<td>{int(m.get('n_symbols_ok') or 0)}</td>"
            f"<td>{int(m.get('n_symbols') or 0)}</td>"
            f"<td>{int(m.get('n_contracts') or 0)}</td>"
            f"<td>{int(m.get('max_expiries') or 0)}</td>"
            f"<td>{int(warns)}</td>"
            f'<td><a href="{html_mod.escape(href)}">Open {html_mod.escape(d)}</a></td>'
            "</tr>"
        )
    if not date_rows:
        date_body = '<tr><td colspan="8" class="muted">No snapshots yet.</td></tr>'
    else:
        date_body = "".join(date_rows)

    latest_block = ""
    if latest_summary is not None and not latest_summary.empty and latest_date:
        latest_block = (
            f"<h2>Latest snapshot — {html_mod.escape(latest_date)}</h2>"
            '<p class="small">One row per name. Click column headers to sort. '
            f'<a href="{html_mod.escape(day_href_fn(latest_date))}">Open the full chain</a>.</p>'
            + _summary_table(latest_summary)
        )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html_mod.escape(index_title)}</title>
<style>{PAGE_CSS}</style></head><body>
<h1>Option chain archive</h1>
<p class="sub">Homemade dated snapshots of Yahoo Finance option quotes. Not official EOD OPRA. Not a DailyRun trading sleeve.</p>
{_asked_block()}
{_nav("#dates", baseline_href)}
<div class="callout warn">
  <p class="small"><strong>Archive only.</strong> Not a scanner. Not gold. Do not treat DailyRun as “options trading.”
  Re-running the same calendar day <em>overwrites</em> that day’s parquet (no run-id).</p>
</div>
<h2 id="dates">Available snapshot dates</h2>
<p class="small">Click column headers to sort. A new date appears when DailyRun (or <code>run_options_chain.bat</code>) finishes a fetch.</p>
<div class="table-wrap">
<table class="sortable">
  <thead><tr>{date_head}</tr></thead>
  <tbody>{date_body}</tbody>
</table>
</div>
{latest_block}
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""


def _summary_table(summary: pd.DataFrame) -> str:
    head = "".join(
        _sortable_th(label, kind)
        for label, kind in (
            ("Symbol", "text"),
            ("Contracts", "num"),
            ("Calls", "num"),
            ("Puts", "num"),
            ("Expiries", "num"),
            ("Spot", "num"),
            ("Median IV", "num"),
            ("Median spread $", "num"),
            ("Median spread %", "num"),
            ("Volume", "num"),
            ("Open interest", "num"),
        )
    )
    body = []
    for _, r in summary.iterrows():
        body.append(
            "<tr>"
            f"<td>{html_mod.escape(str(r['symbol']))}</td>"
            f"<td>{int(r['n_contracts'])}</td>"
            f"<td>{int(r['n_calls'])}</td>"
            f"<td>{int(r['n_puts'])}</td>"
            f"<td>{int(r['n_expiries'])}</td>"
            f"<td>{_fmt_num(r['underlying_last'], 2)}</td>"
            f"<td>{_fmt_iv(r['median_iv'])}</td>"
            f"<td>{_fmt_num(r['median_spread'], 3)}</td>"
            f"<td>{_fmt_pct(r['median_spread_pct'])}</td>"
            f"<td>{int(r['total_volume'])}</td>"
            f"<td>{int(r['total_oi'])}</td>"
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def render_day_html(
    snapshot_date: str,
    df: pd.DataFrame,
    summary: pd.DataFrame,
    manifest: dict[str, Any],
    *,
    index_href: str,
    baseline_href: str | None,
) -> str:
    symbols = sorted({str(s) for s in df["symbol"].dropna().unique()}) if not df.empty else []
    expiries = sorted({str(s) for s in df["expiry"].dropna().unique()}) if not df.empty else []
    sym_opts = "".join(f'<option value="{html_mod.escape(s)}">{html_mod.escape(s)}</option>' for s in symbols)
    exp_opts = "".join(f'<option value="{html_mod.escape(s)}">{html_mod.escape(s)}</option>' for s in expiries)

    head = "".join(
        _sortable_th(label, kind)
        for label, kind in (
            ("Symbol", "text"),
            ("Expiry", "date"),
            ("Type", "text"),
            ("Strike", "num"),
            ("Bid", "num"),
            ("Ask", "num"),
            ("Mid", "num"),
            ("Last", "num"),
            ("Volume", "num"),
            ("Open interest", "num"),
            ("IV", "num"),
            ("Contract", "text"),
        )
    )
    body = []
    for _, r in df.iterrows():
        body.append(
            "<tr"
            f' data-symbol="{html_mod.escape(str(r["symbol"]))}"'
            f' data-expiry="{html_mod.escape(str(r["expiry"]))}"'
            f' data-type="{html_mod.escape(str(r["type"]))}">'
            f"<td>{html_mod.escape(str(r['symbol']))}</td>"
            f"<td>{html_mod.escape(str(r['expiry']))}</td>"
            f"<td>{html_mod.escape(str(r['type']))}</td>"
            f"<td>{_fmt_num(r['strike'], 2)}</td>"
            f"<td>{_fmt_num(r['bid'], 2)}</td>"
            f"<td>{_fmt_num(r['ask'], 2)}</td>"
            f"<td>{_fmt_num(r['mid'], 2)}</td>"
            f"<td>{_fmt_num(r['lastPrice'], 2)}</td>"
            f"<td>{int(r['volume']) if pd.notna(r['volume']) else 0}</td>"
            f"<td>{int(r['openInterest']) if pd.notna(r['openInterest']) else 0}</td>"
            f"<td>{_fmt_iv(r['impliedVolatility'])}</td>"
            f"<td>{html_mod.escape(str(r.get('contractSymbol') or ''))}</td>"
            "</tr>"
        )
    failed = manifest.get("failed") or []
    fail_note = ""
    if failed:
        bits = ", ".join(f"{html_mod.escape(str(x.get('symbol')))} ({html_mod.escape(str(x.get('note')))})" for x in failed)
        fail_note = f'<div class="callout warn"><p class="small">Yahoo warnings this day: {bits}</p></div>'

    n = int(len(df))
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Option chain {html_mod.escape(snapshot_date)}</title>
<style>{PAGE_CSS}</style></head><body>
<h1>Option chain — {html_mod.escape(snapshot_date)}</h1>
<p class="sub">
  {n:,} contracts · {int(manifest.get('n_symbols_ok') or 0)} names ·
  first {int(manifest.get('max_expiries') or 0)} listed expiries ·
  fetched {html_mod.escape(str(manifest.get('fetched_at') or ''))} UTC.
  Click column headers to sort.
</p>
{_asked_block()}
{_nav(index_href, baseline_href)}
{fail_note}
<h2>Per-name summary</h2>
<p class="small">Click column headers to sort.</p>
{_summary_table(summary)}
<h2>Contracts</h2>
<p class="small">Filter the table (does not change the saved parquet). Click column headers to sort.</p>
<div class="filters">
  <label>Symbol
    <select id="f-symbol"><option value="">All</option>{sym_opts}</select>
  </label>
  <label>Expiry
    <select id="f-expiry"><option value="">All</option>{exp_opts}</select>
  </label>
  <label>Type
    <select id="f-type"><option value="">All</option><option value="C">Calls</option><option value="P">Puts</option></select>
  </label>
  <span class="small" id="f-count"></span>
</div>
<div class="table-wrap">
<table class="sortable" id="chain-table">
  <thead><tr>{head}</tr></thead>
  <tbody>{''.join(body)}</tbody>
</table>
</div>
<script>
(function () {{
  var table = document.getElementById("chain-table");
  var tbody = table && table.tBodies[0];
  var countEl = document.getElementById("f-count");
  function applyFilter() {{
    if (!tbody) return;
    var s = (document.getElementById("f-symbol").value || "").toUpperCase();
    var e = document.getElementById("f-expiry").value || "";
    var t = (document.getElementById("f-type").value || "").toUpperCase();
    var rows = tbody.querySelectorAll("tr");
    var shown = 0;
    rows.forEach(function (tr) {{
      var ok = true;
      if (s && (tr.getAttribute("data-symbol") || "") !== s) ok = false;
      if (e && (tr.getAttribute("data-expiry") || "") !== e) ok = false;
      if (t && (tr.getAttribute("data-type") || "") !== t) ok = false;
      tr.style.display = ok ? "" : "none";
      if (ok) shown += 1;
    }});
    if (countEl) countEl.textContent = shown + " rows shown";
  }}
  ["f-symbol", "f-expiry", "f-type"].forEach(function (id) {{
    var el = document.getElementById(id);
    if (el) el.addEventListener("change", applyFilter);
  }});
  applyFilter();
}})();
</script>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""


def write_html_views(snapshot_date: str | None) -> list[Path]:
    manifests = list_snapshot_manifests()
    latest_date = snapshot_date or (str(manifests[0]["snapshot_date"]) if manifests else None)
    latest_summary = pd.DataFrame()
    if latest_date:
        latest_df = load_day_frame(latest_date)
        latest_summary = symbol_summary(latest_df)

    DRIVE_OPTIONS.mkdir(parents=True, exist_ok=True)
    STAMP_DIR.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for m in manifests:
        d = str(m.get("snapshot_date") or "")
        if not d:
            continue
        day_df = load_day_frame(d)
        day_sum = symbol_summary(day_df)
        day_html = render_day_html(
            d,
            day_df,
            day_sum,
            m,
            index_href="index.html",
            baseline_href="../paul_experiments/options_chain_archive_20260917/BASELINE.md",
        )
        day_path = DRIVE_OPTIONS / f"{d}.html"
        day_path.write_text(day_html, encoding="utf-8")
        written.append(day_path)

    def day_href_options(d: str) -> str:
        return f"{d}.html"

    def day_href_stamp(d: str) -> str:
        return f"../../options/{d}.html"

    idx_options = DRIVE_OPTIONS / "index.html"
    idx_options.write_text(
        render_index_html(
            manifests,
            latest_summary=latest_summary,
            latest_date=latest_date,
            day_href_fn=day_href_options,
            index_title="Option chain archive",
            baseline_href="../paul_experiments/options_chain_archive_20260917/BASELINE.md",
        ),
        encoding="utf-8",
    )
    written.append(idx_options)

    idx_stamp = STAMP_DIR / "index.html"
    idx_stamp.write_text(
        render_index_html(
            manifests,
            latest_summary=latest_summary,
            latest_date=latest_date,
            day_href_fn=day_href_stamp,
            index_title="Option chain archive — 20260917",
            baseline_href="BASELINE.md",
        ),
        encoding="utf-8",
    )
    written.append(idx_stamp)
    return written


def run_fetch(
    symbols: list[str],
    *,
    max_expiries: int,
    delay_symbol: float,
    delay_expiry: float,
    yahoo_retries: int,
    yahoo_base_wait: float,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    snapshot_date = date.today().isoformat()
    fetched_at = _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
    parts: list[pd.DataFrame] = []
    per: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for i, sym in enumerate(symbols):
        print(f"[options-chain] {sym} ({i + 1}/{len(symbols)})", flush=True)
        try:
            df, meta = fetch_symbol_chains(
                sym,
                max_expiries,
                yahoo_max_retries=yahoo_retries,
                yahoo_base_wait_sec=yahoo_base_wait,
                delay_between_expiries=delay_expiry,
                snapshot_date=snapshot_date,
                fetched_at=fetched_at,
            )
        except BaseException as e:  # noqa: BLE001 — never abort the book on one name
            print(f"[options-chain] WARN {sym}: {e}", file=sys.stderr, flush=True)
            meta = {
                "symbol": sym,
                "ok": False,
                "n_contracts": 0,
                "expiries": [],
                "note": f"yahoo_error: {e}",
                "underlying_last": None,
            }
            df = pd.DataFrame(columns=CHAIN_COLS)
        per.append(meta)
        if meta.get("ok") and not df.empty:
            parts.append(df)
        else:
            failed.append({"symbol": meta.get("symbol"), "note": meta.get("note")})
        if delay_symbol > 0 and i + 1 < len(symbols):
            time.sleep(delay_symbol)

    chain = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=CHAIN_COLS)
    manifest = {
        "snapshot_date": snapshot_date,
        "fetched_at": fetched_at,
        "source": "yfinance.Ticker.option_chain",
        "source_note": "live_or_delayed_snapshot_not_opra_eod",
        "archive_only": True,
        "gold": False,
        "scanner": False,
        "idempotent": "overwrite_same_calendar_day",
        "universe_file": str(UNIVERSE_CSV.as_posix()),
        "symbols": symbols,
        "n_symbols": len(symbols),
        "n_symbols_ok": int(sum(1 for m in per if m.get("ok"))),
        "n_symbols_failed": len(failed),
        "failed": failed,
        "max_expiries": int(max_expiries),
        "expiry_rule": f"first_{int(max_expiries)}_listed_nearest_first",
        "n_contracts": int(len(chain)),
        "per_symbol": per,
        "columns": CHAIN_COLS,
    }
    return chain, manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Save a dated yfinance option-chain snapshot (archive only)."
    )
    ap.add_argument("--symbols", "-s", default="", help="Comma-separated tickers (overrides --universe).")
    ap.add_argument(
        "--universe",
        default=str(UNIVERSE_CSV),
        help="CSV/txt of tickers, one per line (default data/options/options_universe.csv).",
    )
    ap.add_argument(
        "--max-expiries",
        type=int,
        default=DEFAULT_MAX_EXPIRIES,
        help=f"First N listed expiries, nearest first (default {DEFAULT_MAX_EXPIRIES}).",
    )
    ap.add_argument("--delay-between-symbols", type=float, default=DEFAULT_DELAY_SYMBOL)
    ap.add_argument("--delay-between-expiries", type=float, default=DEFAULT_DELAY_EXPIRY)
    ap.add_argument("--yahoo-retries", type=int, default=6)
    ap.add_argument("--yahoo-base-wait", type=float, default=2.5)
    ap.add_argument("--html-only", action="store_true", help="Rebuild Drive HTML from existing snapshots.")
    ap.add_argument(
        "--soft-fail",
        action="store_true",
        default=True,
        help="Exit 0 even if Yahoo flakes (default). DailyRun-safe.",
    )
    ap.add_argument("--strict", action="store_true", help="Exit 1 if no contracts saved.")
    args = ap.parse_args(argv)

    soft = bool(args.soft_fail) and not bool(args.strict)

    try:
        ensure_universe_file()
        if args.html_only:
            paths = write_html_views(None)
            print(f"[options-chain] wrote {len(paths)} HTML files", flush=True)
            return 0

        symbols = load_universe(Path(args.universe), args.symbols)
        print(
            f"[options-chain] archive {len(symbols)} names × first {int(args.max_expiries)} expiries "
            f"(overwrite same calendar day)",
            flush=True,
        )
        chain, manifest = run_fetch(
            symbols,
            max_expiries=int(args.max_expiries),
            delay_symbol=float(args.delay_between_symbols),
            delay_expiry=float(args.delay_between_expiries),
            yahoo_retries=int(args.yahoo_retries),
            yahoo_base_wait=float(args.yahoo_base_wait),
        )
        summary = symbol_summary(chain)
        day = str(manifest["snapshot_date"])
        day_dir = ARCHIVE_ROOT / day
        write_day_archive(chain, summary, manifest, day_dir)
        print(
            f"[options-chain] wrote {day_dir / 'chain.parquet'} "
            f"rows={manifest['n_contracts']} ok={manifest['n_symbols_ok']}/{manifest['n_symbols']}",
            flush=True,
        )
        if manifest["n_symbols_failed"]:
            print(
                f"[options-chain] WARN {manifest['n_symbols_failed']} name(s) failed: "
                + ", ".join(str(x.get("symbol")) for x in manifest["failed"]),
                file=sys.stderr,
                flush=True,
            )
        write_html_views(day)
        if manifest["n_contracts"] == 0 and args.strict:
            return 1
        return 0
    except Exception as e:  # noqa: BLE001 — DailyRun must not die on Yahoo
        print(f"[options-chain] WARN unhandled: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        if soft:
            try:
                write_html_views(None)
            except Exception:
                pass
            return 0
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
