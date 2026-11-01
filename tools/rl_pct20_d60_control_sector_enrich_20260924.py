#!/usr/bin/env python3
"""Enrich pct20_d60 RL control Closed with sector / industry / index / mcap columns.

Reuse existing Closed from rl_no_sma_target_exit_ab_20260905 (no re-backtest).
Join local yfinance_cache.json (+ fundamentals_cache.duckdb fallback) and
current Wikipedia index constituent snapshots (S&P 500 + Nasdaq-100; Russell
1000/2000 when fetchable). Market cap at entry is a constant-share approximation:
current_mcap * (entry_price / current_price), same scaling as rocket_tbn.
"""

from __future__ import annotations

import csv
import html as html_mod
import json
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

from be_stop_replay_ab import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402

STAMP = REPO / "drive" / "paul_experiments" / "rl_pct20_d60_control_sector_enrich_20260924"
CLOSED_SRC = (
    REPO
    / "drive"
    / "paul_experiments"
    / "rl_no_sma_target_exit_ab_20260905"
    / "runs"
    / "pct20_d60"
    / "RL_Closed_260905205015.csv"
)
YF_CACHE = REPO / "yfinance_cache.json"
DUCK = REPO / "drive" / "fundamentals_cache.duckdb"
SP500_LOCAL = REPO / "drive" / "spx_diversification" / "sp500_constituents_wikipedia.txt"

ORIGINAL_REQUEST = (
    "can you run the control and add in a colunn for the sector/industry for each "
    "ticker and add the following Sector Industry / Sub-industry Index membership "
    "— S&P 500, Nasdaq-100, Russell, etc. Market cap at entry if availabl"
)
LAYMAN = (
    "We took the existing control Rocket Launcher (RL) trade list (pct20_d60 — "
    "20% profit target / 60-session calendar hold style exit) and added columns "
    "that say what business each stock is in, which big stock indexes it sits in "
    "today, and roughly how large the company was when we bought it. This is for "
    "browsing and slicing the book — not a new backtest."
)

FRONT_COLS = [
    "SYMBOL",
    "DATE OPENED",
    "Sector",
    "Industry / Sub-industry",
    "Index membership",
    "Market cap at entry",
    "Market cap current (snapshot)",
    "Mcap note",
]


def _load_yf_cache() -> dict[str, dict]:
    if not YF_CACHE.is_file():
        return {}
    try:
        raw = json.loads(YF_CACHE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _load_duck_fallback(symbols: set[str]) -> dict[str, dict]:
    """Fill sector/industry/mcap from fundamentals_cache.duckdb when JSON misses."""
    out: dict[str, dict] = {}
    if not DUCK.is_file() or not symbols:
        return out
    try:
        import duckdb
    except ImportError:
        return out
    try:
        con = duckdb.connect(str(DUCK), read_only=True)
    except Exception:
        return out
    try:
        # Prefer yf_symbol_info.raw_json; also scorecard has sector/industry for a few.
        rows = con.execute(
            """
            SELECT symbol, market_cap, raw_json
            FROM yf_symbol_info
            WHERE symbol IN (SELECT * FROM UNNEST(?))
            """,
            [list(symbols)],
        ).fetchall()
        for sym, mc, raw in rows:
            info: dict[str, Any] = {}
            if raw:
                try:
                    j = json.loads(raw) if isinstance(raw, str) else raw
                    if isinstance(j, dict):
                        if j.get("sector"):
                            info["sector"] = j["sector"]
                        if j.get("industry"):
                            info["industry"] = j["industry"]
                        if j.get("marketCap") is not None:
                            info["market_cap"] = j["marketCap"]
                        px = j.get("currentPrice") or j.get("regularMarketPrice")
                        if px is not None:
                            info["current_price"] = px
                except (TypeError, json.JSONDecodeError):
                    pass
            if mc is not None and "market_cap" not in info:
                info["market_cap"] = mc
            if info:
                out[str(sym).upper()] = info
        sc = con.execute(
            """
            SELECT symbol, sector, industry
            FROM yf_scorecard_metrics
            WHERE symbol IN (SELECT * FROM UNNEST(?))
            """,
            [list(symbols)],
        ).fetchall()
        for sym, sec, ind in sc:
            s = str(sym).upper()
            slot = out.setdefault(s, {})
            if sec and not slot.get("sector"):
                slot["sector"] = sec
            if ind and not slot.get("industry"):
                slot["industry"] = ind
    finally:
        con.close()
    return out


def _read_ticker_list(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    out: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip().upper().replace(".", "-")
        if s and not s.startswith("#"):
            out.add(s)
    return out


def _http_get(url: str, accept: str = "text/html,application/json,*/*") -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", "replace")


def _fetch_wiki_tickers(url: str, table_id: str | None = None) -> list[str]:
    html = _http_get(url)
    if table_id:
        m = re.search(
            rf'<table[^>]*id="{re.escape(table_id)}"[\s\S]*?</table>',
            html,
            flags=re.I,
        )
        tables = [m.group(0)] if m else []
    else:
        tables = re.findall(
            r'<table[^>]*class="[^"]*wikitable[^"]*"[^>]*>[\s\S]*?</table>',
            html,
            flags=re.I,
        )
    tickers: list[str] = []
    for table in tables:
        for row in re.findall(r"<tr[\s\S]*?</tr>", table)[1:]:
            tds = re.findall(r"<td[^>]*>([\s\S]*?)</td>", row)
            if not tds:
                continue
            # Prefer a cell that looks like a ticker (short, alnum).
            candidates = []
            for td in tds[:3]:
                sym = re.sub(r"<[^>]+>", "", td).strip().upper().replace(".", "-")
                sym = re.sub(r"\s+", "", sym)
                if re.fullmatch(r"[A-Z]{1,5}(-[A-Z])?", sym):
                    candidates.append(sym)
            if candidates:
                tickers.append(candidates[0])
        if len(tickers) >= 50:
            break
    seen: set[str] = set()
    out: list[str] = []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _fetch_nasdaq100() -> list[str]:
    """Current Nasdaq-100 constituents via nasdaq.com public JSON API."""
    raw = _http_get(
        "https://api.nasdaq.com/api/quote/list-type/nasdaq100",
        accept="application/json,text/plain,*/*",
    )
    payload = json.loads(raw)
    rows = (((payload.get("data") or {}).get("data") or {}).get("rows")) or []
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").strip().upper().replace(".", "-")
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
    return out


def _load_or_fetch_index(
    name: str,
    cache_path: Path,
    fetch_fn,
    *,
    min_n: int = 50,
) -> tuple[set[str], str]:
    """Return (tickers, source_note). Prefer local cache with enough names."""
    local = _read_ticker_list(cache_path)
    if len(local) >= min_n:
        return local, f"local cache {cache_path.as_posix()} (n={len(local)})"
    try:
        tickers = fetch_fn()
    except Exception as exc:  # noqa: BLE001
        if local:
            return local, (
                f"fetch failed ({type(exc).__name__}: {exc}); "
                f"kept thin local cache n={len(local)}"
            )
        return set(), f"fetch failed ({type(exc).__name__}: {exc})"
    if len(tickers) < min_n:
        if local:
            return local, (
                f"fetch too thin (n={len(tickers)}); kept local cache n={len(local)}"
            )
        return set(), f"fetch returned empty/thin (n={len(tickers)})"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text("\n".join(tickers) + "\n", encoding="utf-8")
    return set(tickers), f"fetched → {cache_path.as_posix()} (n={len(tickers)})"


def _fmt_mcap(v: float | None) -> str:
    if v is None:
        return ""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return ""
    if x >= 1e12:
        return f"{x / 1e12:.2f}T"
    if x >= 1e9:
        return f"{x / 1e9:.2f}B"
    if x >= 1e6:
        return f"{x / 1e6:.2f}M"
    return f"{x:.0f}"


def _parse_float(s: Any) -> float | None:
    if s is None:
        return None
    t = str(s).strip().replace(",", "").replace("$", "")
    if not t or t in {"—", "-", "N/A", "nan", "None"}:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _index_label(sym: str, memberships: dict[str, set[str]]) -> str:
    labels = []
    for name, members in memberships.items():
        if sym in members:
            labels.append(name)
    return "; ".join(labels) if labels else ""


def enrich() -> dict[str, Any]:
    if not CLOSED_SRC.is_file():
        raise FileNotFoundError(CLOSED_SRC)

    STAMP.mkdir(parents=True, exist_ok=True)
    (STAMP / "closed").mkdir(parents=True, exist_ok=True)
    (STAMP / "index_caches").mkdir(parents=True, exist_ok=True)

    with CLOSED_SRC.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        closed_rows = list(reader)
        base_fields = list(reader.fieldnames or [])

    symbols = {str(r.get("SYMBOL", "")).strip().upper() for r in closed_rows if r.get("SYMBOL")}
    yf = _load_yf_cache()
    duck = _load_duck_fallback(symbols)

    # Index membership (current snapshots — not point-in-time at entry)
    memberships: dict[str, set[str]] = {}
    index_sources: dict[str, str] = {}

    sp500_cache = STAMP / "index_caches" / "sp500_constituents.txt"
    if not sp500_cache.is_file() and SP500_LOCAL.is_file():
        sp500_cache.write_text(SP500_LOCAL.read_text(encoding="utf-8"), encoding="utf-8")
    sp500, note = _load_or_fetch_index(
        "S&P 500",
        sp500_cache,
        lambda: _fetch_wiki_tickers(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            table_id="constituents",
        ),
    )
    if not sp500 and SP500_LOCAL.is_file():
        sp500 = _read_ticker_list(SP500_LOCAL)
        note = f"repo {SP500_LOCAL.as_posix()} (n={len(sp500)})"
    memberships["S&P 500"] = sp500
    index_sources["S&P 500"] = note

    ndx_cache = STAMP / "index_caches" / "nasdaq100_constituents.txt"
    # Clear thin/empty prior cache so we re-fetch
    if ndx_cache.is_file() and len(_read_ticker_list(ndx_cache)) < 50:
        ndx_cache.unlink()
    ndx, note = _load_or_fetch_index(
        "Nasdaq-100",
        ndx_cache,
        _fetch_nasdaq100,
        min_n=80,
    )
    memberships["Nasdaq-100"] = ndx
    index_sources["Nasdaq-100"] = note

    # Russell: Wikipedia pages no longer ship constituent tables; iShares CSV is
    # bot-walled from this environment. Leave empty and label the gap clearly.
    for label, fname, wiki_url in [
        ("Russell 1000", "russell1000_constituents.txt", "https://en.wikipedia.org/wiki/Russell_1000_Index"),
        ("Russell 2000", "russell2000_constituents.txt", "https://en.wikipedia.org/wiki/Russell_2000_Index"),
    ]:
        cache = STAMP / "index_caches" / fname
        if cache.is_file() and len(_read_ticker_list(cache)) < 50:
            cache.unlink()
        members, note = _load_or_fetch_index(
            label,
            cache,
            lambda u=wiki_url: _fetch_wiki_tickers(u),
            min_n=200 if "2000" in label else 500,
        )
        if not members:
            note = (
                "unavailable in-repo / fetchable here — Wikipedia pages lack "
                "constituent tables; iShares holdings CSV bot-walled. Gap labeled."
            )
        memberships[label] = members
        index_sources[label] = note

    enriched: list[dict[str, str]] = []
    cov = {
        "n_trades": len(closed_rows),
        "n_symbols": len(symbols),
        "sector": 0,
        "industry": 0,
        "index_any": 0,
        "mcap_entry": 0,
        "mcap_current": 0,
        "index_by_name": {k: 0 for k in memberships},
    }

    for row in closed_rows:
        sym = str(row.get("SYMBOL", "")).strip().upper()
        info = dict(yf.get(sym) or {})
        # duck fills only missing fields
        for k, v in (duck.get(sym) or {}).items():
            if info.get(k) in (None, "") and v not in (None, ""):
                info[k] = v

        sector = str(info.get("sector") or "").strip()
        industry = str(info.get("industry") or "").strip()
        mc_cur = _parse_float(info.get("market_cap"))
        cur_px = _parse_float(info.get("current_price"))
        entry_px = _parse_float(row.get("ENTRY PRICE"))

        mc_entry = None
        mcap_note = ""
        if mc_cur is not None:
            if cur_px and cur_px > 0 and entry_px and entry_px > 0:
                mc_entry = mc_cur * (entry_px / cur_px)
                mcap_note = (
                    "approx entry = snapshot_mcap × (entry_price / current_price); "
                    f"cache as_of={info.get('as_of_date') or 'unknown'}; not true PIT shares"
                )
            else:
                mc_entry = mc_cur
                mcap_note = (
                    "snapshot mcap only (could not scale — missing entry or current price); "
                    f"cache as_of={info.get('as_of_date') or 'unknown'}"
                )

        idx = _index_label(sym, memberships)

        out = {
            "SYMBOL": row.get("SYMBOL", ""),
            "DATE OPENED": row.get("DATE OPENED", ""),
            "Sector": sector,
            "Industry / Sub-industry": industry,
            "Index membership": idx,
            "Market cap at entry": f"{mc_entry:.0f}" if mc_entry is not None else "",
            "Market cap current (snapshot)": f"{mc_cur:.0f}" if mc_cur is not None else "",
            "Mcap note": mcap_note,
        }
        for k in base_fields:
            if k in ("SYMBOL", "DATE OPENED"):
                continue
            out[k] = row.get(k, "")
        enriched.append(out)

        if sector:
            cov["sector"] += 1
        if industry:
            cov["industry"] += 1
        if idx:
            cov["index_any"] += 1
        if mc_entry is not None:
            cov["mcap_entry"] += 1
        if mc_cur is not None:
            cov["mcap_current"] += 1
        for name, members in memberships.items():
            if sym in members:
                cov["index_by_name"][name] += 1

    out_fields = FRONT_COLS + [c for c in base_fields if c not in ("SYMBOL", "DATE OPENED")]
    csv_path = STAMP / "closed" / "control_closed_enriched.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=out_fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(enriched)

    # Compact symbol map for audits
    sym_map_path = STAMP / "symbol_enrich_map.csv"
    seen_sym: set[str] = set()
    with sym_map_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=[
                "symbol",
                "sector",
                "industry",
                "index_membership",
                "market_cap_current",
                "yf_as_of",
            ],
        )
        w.writeheader()
        for row in enriched:
            s = str(row["SYMBOL"]).strip().upper()
            if s in seen_sym:
                continue
            seen_sym.add(s)
            info = yf.get(s) or duck.get(s) or {}
            w.writerow(
                {
                    "symbol": s,
                    "sector": row["Sector"],
                    "industry": row["Industry / Sub-industry"],
                    "index_membership": row["Index membership"],
                    "market_cap_current": row["Market cap current (snapshot)"],
                    "yf_as_of": info.get("as_of_date") or "",
                }
            )

    meta = {
        "closed_src": CLOSED_SRC.as_posix(),
        "csv": csv_path.as_posix(),
        "coverage": cov,
        "index_sources": index_sources,
        "index_sizes": {k: len(v) for k, v in memberships.items()},
        "mcap_method": (
            "Constant-share approximation: market_cap_at_entry = "
            "yfinance_cache.market_cap × (ENTRY PRICE / current_price). "
            "Not true point-in-time shares outstanding."
        ),
        "sector_source": "yfinance_cache.json (Yahoo sector/industry); DuckDB raw_json fallback",
        "index_caveat": (
            "Index membership is today's Wikipedia constituent snapshot projected "
            "onto historical trades (survivorship / not PIT)."
        ),
        "as_of": date.today().isoformat(),
    }
    (STAMP / "coverage.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {"enriched": enriched, "out_fields": out_fields, "meta": meta, "csv_path": csv_path}


def _pct(n: int, d: int) -> str:
    if d <= 0:
        return "—"
    return f"{100.0 * n / d:.1f}%"


def write_baseline(meta: dict[str, Any]) -> Path:
    cov = meta["coverage"]
    n = cov["n_trades"]
    lines = [
        "# BASELINE — RL pct20_d60 control Closed sector / index / mcap enrich",
        "",
        f"- Stamp: `{STAMP.as_posix()}`",
        f"- As of: {meta['as_of']}",
        f"- Control Closed source: `{meta['closed_src']}`",
        "- No re-backtest; enrich-only join onto existing Closed.",
        "",
        "## What you asked",
        "",
        ORIGINAL_REQUEST,
        "",
        "## In plain English",
        "",
        LAYMAN,
        "",
        "## Columns added",
        "",
        "- `Sector` — Yahoo Finance sector (GICS-like)",
        "- `Industry / Sub-industry` — Yahoo Finance industry string",
        "- `Index membership` — semicolon list among available: S&P 500, Nasdaq-100, Russell 1000, Russell 2000",
        "- `Market cap at entry` — approx USD (see method)",
        "- `Market cap current (snapshot)` — raw cache market cap",
        "- `Mcap note` — method / as-of label per trade",
        "",
        "## Data sources",
        "",
        f"- Sector / industry / mcap: `{YF_CACHE.name}` (+ `{DUCK.name}` fallback)",
        f"- Sector method: {meta['sector_source']}",
        f"- Mcap method: {meta['mcap_method']}",
        f"- Index caveat: {meta['index_caveat']}",
        "",
        "### Index sources",
        "",
    ]
    for name, note in meta["index_sources"].items():
        size = meta["index_sizes"].get(name, 0)
        lines.append(f"- **{name}** (n={size}): {note}")
    lines += [
        "",
        "## Coverage (of closed trades)",
        "",
        f"- N trades: {n}",
        f"- Unique symbols: {cov['n_symbols']}",
        f"- Sector filled: {cov['sector']} ({_pct(cov['sector'], n)})",
        f"- Industry filled: {cov['industry']} ({_pct(cov['industry'], n)})",
        f"- Any index membership: {cov['index_any']} ({_pct(cov['index_any'], n)})",
        f"- Market cap at entry: {cov['mcap_entry']} ({_pct(cov['mcap_entry'], n)})",
        f"- Market cap current: {cov['mcap_current']} ({_pct(cov['mcap_current'], n)})",
        "",
    ]
    for name, c in cov["index_by_name"].items():
        lines.append(f"- In {name}: {c} trades ({_pct(c, n)})")
    lines += [
        "",
        "## Gaps",
        "",
        "- Market cap is **not true point-in-time** (no historical shares × price series). "
        "It is a snapshot scaled by entry/current price.",
        "- Index membership is **current snapshot**, not membership on the entry date "
        "(survivorship bias).",
        "- **Russell 1000 / Russell 2000:** no reliable joinable constituent list in-repo; "
        "Wikipedia pages no longer publish tables; iShares holdings CSV is bot-walled here. "
        "Columns stay blank for Russell until a local cache is dropped in "
        "`index_caches/russell1000_constituents.txt` / `russell2000_constituents.txt`.",
        "- A handful of trades may still lack Yahoo sector/industry if absent from cache + DuckDB.",
        "",
        "## Artifacts",
        "",
        f"- Enriched CSV: `{meta['csv']}`",
        f"- HTML: `{ (STAMP / 'control_closed_enriched.html').as_posix() }`",
        f"- Symbol map: `{(STAMP / 'symbol_enrich_map.csv').as_posix()}`",
        "",
        "Research / browse only. Not gold. Not DailyRun.",
        "",
    ]
    path = STAMP / "BASELINE.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    (STAMP / "README.md").write_text("\n".join(lines), encoding="utf-8")
    return path


def write_html(enriched: list[dict[str, str]], out_fields: list[str], meta: dict[str, Any]) -> Path:
    cov = meta["coverage"]
    n = cov["n_trades"]

    # Prefer a readable front set + key trade cols for the HTML (full CSV has everything).
    html_cols = [
        "SYMBOL",
        "DATE OPENED",
        "Sector",
        "Industry / Sub-industry",
        "Index membership",
        "Market cap at entry",
        "Market cap current (snapshot)",
        "ENTRY PRICE",
        "DATE CLOSED",
        "DAYS HELD",
        "EXIT PRICE",
        "PNL %",
        "EXIT TYPE",
        "TRIGGER TYPE",
        "Mcap note",
    ]
    html_cols = [c for c in html_cols if c in out_fields or c in FRONT_COLS]

    def sort_type(col: str) -> str:
        if col in {"DATE OPENED", "DATE CLOSED"}:
            return "date"
        if col in {
            "Market cap at entry",
            "Market cap current (snapshot)",
            "ENTRY PRICE",
            "EXIT PRICE",
            "DAYS HELD",
            "PNL %",
        }:
            return "num"
        return "text"

    ths = "".join(sortable_th(c, sort_type(c)) for c in html_cols)
    body_rows = []
    for r in enriched:
        tds = []
        for c in html_cols:
            val = r.get(c, "")
            if c in {"Market cap at entry", "Market cap current (snapshot)"} and val:
                # Raw integer first so numeric header-sort works; pretty size in parens.
                try:
                    raw = f"{float(val):.0f}"
                    pretty = _fmt_mcap(float(val))
                    cell = f"{raw} ({pretty})"
                except ValueError:
                    cell = val
                tds.append(f"<td>{html_mod.escape(cell)}</td>")
            else:
                tds.append(f"<td>{html_mod.escape(str(val))}</td>")
        body_rows.append("<tr>" + "".join(tds) + "</tr>")

    idx_src_li = "".join(
        f"<li><strong>{html_mod.escape(k)}</strong> (n={meta['index_sizes'].get(k, 0)}): "
        f"{html_mod.escape(v)}</li>"
        for k, v in meta["index_sources"].items()
    )
    idx_cov_li = "".join(
        f"<li>{html_mod.escape(k)}: {v} trades ({_pct(v, n)})</li>"
        for k, v in cov["index_by_name"].items()
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL pct20_d60 control Closed — sector / index / mcap enrich</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:24px;color:#1c1b19;background:#faf9f6;line-height:1.45}}
h1{{font-size:1.45rem;margin:0 0 8px}}
h2{{font-size:1.1rem;margin:28px 0 10px}}
.callout{{background:#eef4fb;border:1px solid #c5d6ea;border-radius:8px;padding:14px 16px;margin:16px 0}}
.callout .layman{{margin:8px 0 0}}
.meta{{color:#5c574e;font-size:0.92rem}}
.cov{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin:12px 0 20px}}
.cov div{{background:#fff;border:1px solid #ddd8cc;border-radius:6px;padding:10px 12px}}
.cov strong{{display:block;font-size:1.15rem}}
table.sortable{{border-collapse:collapse;width:100%;font-size:12px;background:#fff}}
table.sortable th,table.sortable td{{border:1px solid #ddd8cc;padding:5px 7px;text-align:left;vertical-align:top}}
table.sortable th{{background:#f0ebe0;position:sticky;top:0;z-index:1}}
.note{{font-size:0.88rem;color:#5c574e;max-width:900px}}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>RL control Closed enrich — pct20_d60</h1>
<p class="meta">Stamp <code>{html_mod.escape(STAMP.as_posix())}</code> · as of {html_mod.escape(meta['as_of'])} ·
source <code>{html_mod.escape(Path(meta['closed_src']).name)}</code> · no re-backtest</p>

<div class="callout">
<strong>What you asked</strong>
<blockquote style="margin:8px 0 0">{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
<p class="layman"><strong>In plain English:</strong> {html_mod.escape(LAYMAN)}</p>
</div>

<h2>Coverage</h2>
<div class="cov">
  <div><span>Trades</span><strong>{n}</strong></div>
  <div><span>Symbols</span><strong>{cov['n_symbols']}</strong></div>
  <div><span>Sector</span><strong>{_pct(cov['sector'], n)}</strong><span class="meta">{cov['sector']} / {n}</span></div>
  <div><span>Industry</span><strong>{_pct(cov['industry'], n)}</strong><span class="meta">{cov['industry']} / {n}</span></div>
  <div><span>Any index</span><strong>{_pct(cov['index_any'], n)}</strong><span class="meta">{cov['index_any']} / {n}</span></div>
  <div><span>Mcap at entry</span><strong>{_pct(cov['mcap_entry'], n)}</strong><span class="meta">{cov['mcap_entry']} / {n}</span></div>
</div>
<ul class="note">
{idx_cov_li}
</ul>

<h2>Data notes</h2>
<ul class="note">
<li><strong>Sector / industry:</strong> {html_mod.escape(meta['sector_source'])}</li>
<li><strong>Market cap at entry:</strong> {html_mod.escape(meta['mcap_method'])}</li>
<li><strong>Index membership:</strong> {html_mod.escape(meta['index_caveat'])}</li>
</ul>
<ul class="note">{idx_src_li}</ul>
<p class="note">Full column set (including every original Closed field) is in
<code>{html_mod.escape(Path(meta['csv']).name)}</code>. Table below shows the enrich front + key trade fields.
Click column headers to sort.</p>

<h2>Closed trades (enriched)</h2>
<table class="sortable">
<thead><tr>{ths}</tr></thead>
<tbody>
{''.join(body_rows)}
</tbody>
</table>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    path = STAMP / "control_closed_enriched.html"
    path.write_text(html, encoding="utf-8")
    return path


def main() -> int:
    print(f"[enrich] loading {CLOSED_SRC}", flush=True)
    pack = enrich()
    print(f"[enrich] wrote {pack['csv_path']}  N={pack['meta']['coverage']['n_trades']}", flush=True)
    bl = write_baseline(pack["meta"])
    print(f"[enrich] wrote {bl}", flush=True)
    html_path = write_html(pack["enriched"], pack["out_fields"], pack["meta"])
    print(f"[enrich] wrote {html_path}", flush=True)
    cov = pack["meta"]["coverage"]
    n = cov["n_trades"]
    print(
        "[enrich] coverage "
        f"sector={cov['sector']}/{n} industry={cov['industry']}/{n} "
        f"index={cov['index_any']}/{n} mcap_entry={cov['mcap_entry']}/{n}",
        flush=True,
    )
    print("[enrich] index sources:", json.dumps(pack["meta"]["index_sources"], indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
