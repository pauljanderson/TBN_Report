#!/usr/bin/env python3
"""Score live opens / helds / watch / scan names with shop buy-low B trendlines.

Reuses frozen weekly-support proximity from ``trendline_slopes_buylow_ab.py``
(weekly support UP and |dist_pct| ≤ 2%). Does not invent knobs.

DailyRun hook (via ``trendlines_daily_publish.py``): ensure missing charts,
then write buy-today HTML next to the published trendline pack.
"""
from __future__ import annotations

import html as html_mod
import json
import math
import shutil
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
_TOOLS = _REPO / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from trendline_slopes_paultwenty import line_price_at, slope_metrics  # noqa: E402
from trendlines_ensure_charts import ensure_charts, ohlc_csv  # noqa: E402
from trendlines_opens_universe import (  # noqa: E402
    collect_opens_universe,
    meta_to_jsonable,
)

DRIVE = _REPO / "drive"
DEFAULT_STAMP = DRIVE / "paul_studies" / "trendlines_opens_latest"
DATA_DIR = _REPO / "data" / "newdata" / "data"
PROX_PCT = 2.0  # frozen weekly-support proximity — not a new knob
CHART_INDEX_REL = "../../paul_studies/trendlines_opens_latest/charts/index.html"

ORIGINAL_REQUEST = (
    "i like this report, but also can you remember to add in any sell signlas "
    "from the trendlines for any holdings I have currently? Also, can you "
    "generate a before and after of all stocks bought in all systems. which "
    "ones would we have bought if we were also doing the same analysis on "
    "them at the time of purchase? I would like to see if we improved our "
    "bottom line."
)

LAYMAN = (
    "1) If you already own a name, this same daily page should say when the "
    "trendline picture is a sell (broken support, falling weekly line) — not "
    "only buy-today. "
    "2) Replay every historical fill: at the entry date, would the same "
    "trendline rules have said buy, wait, or skip? Then compare the book we "
    "actually took vs the book we would have taken. Did the filter help the "
    "bottom line? "
    "3) DailyRun still auto-builds missing charts and scores opens, helds, "
    "watchlists, and scanners. The entry filter is a research overlay only — "
    "not a live buy gate."
)

SORT_CSS = """
th.sortable-th { cursor: pointer; user-select: none; white-space: nowrap; }
th.sortable-th:hover { background: #e2e8f0; }
th.sortable-th .sort-ind::after { content: " \\2195"; opacity: .35; font-size: .85em; }
th.sortable-th.sort-asc .sort-ind::after { content: " \\2191"; opacity: .9; }
th.sortable-th.sort-desc .sort-ind::after { content: " \\2193"; opacity: .9; }
"""

SORT_JS = r"""
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : 0;
    if (type === "text") return s.toUpperCase();
    if (type === "date") {
      var iso = s.match(/(\d{4})-(\d{2})-(\d{2})/);
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


def latest_ohlc(sym: str) -> tuple[date | None, float | None]:
    path = ohlc_csv(sym, DATA_DIR)
    if path is None:
        return None, None
    try:
        import pandas as pd

        df = pd.read_csv(path)
    except Exception:
        return None, None
    cols = {str(c).lower(): c for c in df.columns}
    if "date" not in cols or "close" not in cols:
        return None, None
    df = df.copy()
    df["_d"] = pd.to_datetime(df[cols["date"]], errors="coerce")
    df = df.dropna(subset=["_d"]).sort_values("_d")
    if df.empty:
        return None, None
    last = df.iloc[-1]
    d = last["_d"].date()
    try:
        px = float(last[cols["close"]])
    except (TypeError, ValueError):
        return d, None
    return d, px if math.isfinite(px) else None


def load_segments(stamp_dir: Path) -> dict[str, Any]:
    path = stamp_dir / "segments.json"
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw.get("symbols") or {}


def apply_buy_low_b(out: dict[str, Any]) -> dict[str, Any]:
    """Shop buy-low B + conservative inverse sell (no new knobs).

    BUY TODAY: weekly support UP and |dist_pct| ≤ 2%.
    SKIP (buy overlay): weekly support DOWN, close >2% below weekly support,
    or sitting on weekly resistance instead of support.
    SELL (holdings): weekly support DOWN and/or close >2% below weekly support
    — inverse of buy-low B. Near-resistance without a broken line is HOLD.
    """
    w_up = out["w_sup"] == "UP"
    w_down = out["w_sup"] == "DOWN"
    m_up = out["m_sup"] == "UP"
    m_down = out["m_sup"] == "DOWN"
    d_up = out["d_sup"] == "UP"
    d_down = out["d_sup"] == "DOWN"
    w_dist = out["w_dist"]
    w_res = out["w_res_dist"]
    prox = math.isfinite(w_dist) and abs(w_dist) <= PROX_PCT
    broken = math.isfinite(w_dist) and w_dist < -PROX_PCT
    extended = math.isfinite(w_dist) and w_dist > PROX_PCT
    near_w_res = math.isfinite(w_res) and abs(w_res) <= PROX_PCT
    closer_to_res = (
        math.isfinite(w_dist)
        and math.isfinite(w_res)
        and abs(w_res) < abs(w_dist)
        and w_res <= PROX_PCT
    )

    bits: list[str] = []
    bits.append(
        f"M/W/D support {out['m_sup'] or '—'} / {out['w_sup'] or '—'} / {out['d_sup'] or '—'}"
    )
    if math.isfinite(w_dist):
        bits.append(f"close is {w_dist:+.2f}% vs rising-or-falling weekly support")
    if math.isfinite(w_res):
        bits.append(f"{w_res:+.2f}% vs weekly resistance")

    if w_down or broken:
        out["verdict"] = "SKIP"
        out["rule"] = "weekly support DOWN or close >2% below weekly support"
        if w_down:
            bits.append("Weekly support is falling — trendline argues against buying now.")
        if broken:
            bits.append("Price is more than 2% under weekly support (broken).")
        out["note"] = " ".join(bits)
        out["hold_verdict"] = "SELL"
        out["hold_rule"] = "inverse of buy-low B: weekly support DOWN and/or close through support"
        return out
    if near_w_res and not prox:
        out["verdict"] = "SKIP"
        out["rule"] = "extended into weekly resistance (not near weekly support)"
        bits.append("Sitting near weekly resistance without being on rising weekly support.")
        out["note"] = " ".join(bits)
        out["hold_verdict"] = "HOLD"
        out["hold_rule"] = "near weekly resistance; line not broken — caution, not a sell"
        return out
    if closer_to_res and not (w_up and prox):
        out["verdict"] = "SKIP"
        out["rule"] = "closer to weekly resistance than support"
        bits.append("Closer to weekly resistance than to support.")
        out["note"] = " ".join(bits)
        out["hold_verdict"] = "HOLD"
        out["hold_rule"] = "closer to resistance than support; weekly support not broken"
        return out
    if w_up and prox and not (near_w_res and abs(w_res) < abs(w_dist)):
        out["verdict"] = "BUY TODAY"
        tags = ["B: weekly support UP + |dist|≤2%"]
        if m_up:
            tags.append("monthly support also UP")
        if d_down:
            tags.append("daily support DOWN (A-style pullback on higher-TF uptrend)")
        elif d_up:
            tags.append("daily support UP (C1-style all-up / continuation at the line)")
        out["rule"] = "; ".join(tags)
        bits.append("Price is on/near a rising weekly support — shop buy-low picture.")
        out["note"] = " ".join(bits)
        out["hold_verdict"] = "HOLD"
        out["hold_rule"] = "weekly support UP and price at the line — still a buy-low picture"
        return out
    if w_up and extended:
        out["verdict"] = "WAIT"
        out["rule"] = "weekly support UP but price >2% above the line (not a buy-low yet)"
        bits.append("Uptrend weekly support is intact, but price is not at the line.")
        if near_w_res:
            bits.append("Also near weekly resistance — wait for a pullback.")
        out["note"] = " ".join(bits)
        out["hold_verdict"] = "HOLD"
        out["hold_rule"] = "weekly support still UP — extended, not broken"
        return out
    if not out["w_sup"]:
        if m_down and d_down:
            out["verdict"] = "SKIP"
            out["rule"] = "no weekly support line; monthly and daily support DOWN"
            bits.append("No weekly support to lean on; lower-TF picture is down.")
            out["hold_verdict"] = "HOLD"
            out["hold_rule"] = "no weekly line to declare a break — conservative HOLD"
        elif m_up or d_up:
            out["verdict"] = "WAIT"
            out["rule"] = "no weekly support line — cannot apply buy-low B"
            bits.append("Missing weekly support line; do not fake a buy-low.")
            out["hold_verdict"] = "HOLD"
            out["hold_rule"] = "incomplete weekly geometry — do not fake a sell"
        else:
            out["verdict"] = "WAIT"
            out["rule"] = "incomplete weekly geometry"
            bits.append("Weekly support not available — hold for a cleaner picture.")
            out["hold_verdict"] = "HOLD"
            out["hold_rule"] = "incomplete weekly geometry"
        out["note"] = " ".join(bits)
        return out

    out["verdict"] = "WAIT"
    out["rule"] = "on a list but trendline is mixed / not a clean buy-low"
    bits.append("Not a clean weekly-support buy-low and not a hard skip.")
    out["note"] = " ".join(bits)
    out["hold_verdict"] = "HOLD"
    out["hold_rule"] = "mixed picture — weekly support not down or broken"
    return out


def holdings_sell_verdict(scored: dict[str, Any]) -> str:
    """SELL / HOLD / NO CHART / NO DATA for current holdings."""
    v = str(scored.get("verdict") or "")
    if v == "NO DATA":
        return "NO DATA"
    if v == "NO CHART":
        return "NO CHART"
    hv = str(scored.get("hold_verdict") or "")
    if hv in ("SELL", "HOLD"):
        return hv
    w_down = scored.get("w_sup") == "DOWN"
    try:
        w_dist = float(scored.get("w_dist"))
    except (TypeError, ValueError):
        w_dist = float("nan")
    broken = math.isfinite(w_dist) and w_dist < -PROX_PCT
    if w_down or broken:
        return "SELL"
    return "HOLD"


def is_holding_row(row: dict[str, Any]) -> bool:
    kinds = str(row.get("list_types") or "")
    if row.get("in_portfolio"):
        return True
    return "held" in kinds or "open" in kinds


def score_symbol(
    sym: str,
    seg_meta: dict[str, Any] | None,
    *,
    charts_dir: Path | None = None,
    asof: date | None = None,
    close: float | None = None,
) -> dict[str, Any]:
    charts_dir = charts_dir or (DEFAULT_STAMP / "charts")
    has_png = (charts_dir / f"{sym}_tl_vz_6m.png").is_file()
    if asof is None or close is None:
        live_asof, live_close = latest_ohlc(sym)
        if asof is None:
            asof = live_asof
        if close is None:
            close = live_close
    out: dict[str, Any] = {
        "has_chart": bool(has_png or (seg_meta and seg_meta.get("segments"))),
        "chart_last": (seg_meta or {}).get("last_date") or "",
        "px_date": asof.isoformat() if asof else "",
        "close": close,
        "m_sup": "",
        "w_sup": "",
        "d_sup": "",
        "d_res": "",
        "w_dist": float("nan"),
        "w_res_dist": float("nan"),
        "d_dist": float("nan"),
        "w_line": float("nan"),
        "verdict": "NO CHART",
        "note": "",
        "rule": "",
        "hold_verdict": "NO CHART",
        "hold_rule": "",
    }
    segs = (seg_meta or {}).get("segments") or []
    if not segs:
        if ohlc_csv(sym) is None:
            out["verdict"] = "NO DATA"
            out["hold_verdict"] = "NO DATA"
            out["note"] = "No local Open-High-Low-Close (OHLC) CSV — delisted or never downloaded."
        elif has_png:
            out["verdict"] = "NO CHART"
            out["hold_verdict"] = "NO CHART"
            out["note"] = "PNG exists but no frozen monthly/weekly/daily (M/W/D) segments — cannot score."
        else:
            out["verdict"] = "NO CHART"
            out["hold_verdict"] = "NO CHART"
            out["note"] = "No published trendline chart or segments.json row after ensure-charts."
        return out
    if close is None or asof is None:
        out["verdict"] = "NO DATA"
        out["hold_verdict"] = "NO DATA"
        out["note"] = "Have segments but no local OHLC close — cannot measure proximity."
        return out

    lines: dict[tuple[str, str], dict[str, Any]] = {}
    for s in segs:
        tf = str(s.get("timeframe") or "")
        side = str(s.get("side") or "")
        try:
            d1 = date.fromisoformat(str(s["d1"])[:10])
            d2 = date.fromisoformat(str(s["d2"])[:10])
            p1 = float(s["p1"])
            p2 = float(s["p2"])
        except (KeyError, TypeError, ValueError):
            continue
        sm = slope_metrics(d1, p1, d2, p2)
        line_px = line_price_at(d1, p1, d2, p2, asof)
        dist = (
            (close - line_px) / line_px * 100.0
            if math.isfinite(line_px) and line_px != 0
            else float("nan")
        )
        lines[(tf, side)] = {
            "dir": sm["direction"],
            "dist": dist,
            "line": line_px,
            "pct_day": sm["slope_pct_per_day"],
        }

    def _dir(tf: str, side: str) -> str:
        rec = lines.get((tf, side))
        return rec["dir"] if rec else ""

    def _dist(tf: str, side: str) -> float:
        rec = lines.get((tf, side))
        return float(rec["dist"]) if rec else float("nan")

    out["m_sup"] = _dir("monthly", "support")
    out["w_sup"] = _dir("weekly", "support")
    out["d_sup"] = _dir("daily", "support")
    out["d_res"] = _dir("daily", "resistance")
    out["w_dist"] = _dist("weekly", "support")
    out["w_res_dist"] = _dist("weekly", "resistance")
    out["d_dist"] = _dist("daily", "support")
    wline = lines.get(("weekly", "support"))
    out["w_line"] = float(wline["line"]) if wline else float("nan")
    return apply_buy_low_b(out)


def _fmt(v: Any, nd: int = 2) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(x):
        return "—"
    return f"{x:.{nd}f}"


def _sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{html_mod.escape(sort_type)}" '
        f'tabindex="0" role="columnheader" aria-sort="none">'
        f"{html_mod.escape(label)}<span class=\"sort-ind\"></span></th>"
    )


def _verdict_class(v: str) -> str:
    return {
        "BUY TODAY": "buy",
        "WAIT": "wait",
        "SKIP": "skip",
        "SELL": "sell",
        "HOLD": "hold",
        "NO CHART": "none",
        "NO DATA": "none",
    }.get(v, "")


def table_for(rows: list[dict[str, Any]], caption: str, chart_href: str) -> str:
    heads = [
        ("Symbol", "text"),
        ("System(s)", "text"),
        ("List type", "text"),
        ("Verdict", "text"),
        ("Close", "num"),
        ("Px date", "date"),
        ("M sup", "text"),
        ("W sup", "text"),
        ("D sup", "text"),
        ("W dist %", "num"),
        ("W res %", "num"),
        ("Trendline note", "text"),
        ("Chart", "text"),
    ]
    thead = "".join(_sortable_th(l, t) for l, t in heads)
    body = []
    for r in rows:
        href = f'{html_mod.escape(chart_href)}#{html_mod.escape(r["symbol"])}'
        chart = f'<a href="{href}">chart</a>' if r.get("has_chart") else "—"
        body.append(
            "<tr>"
            f'<td><a href="{href}">{html_mod.escape(r["symbol"])}</a></td>'
            f'<td>{html_mod.escape(r.get("systems") or "—")}</td>'
            f'<td>{html_mod.escape(r.get("list_types") or "—")}</td>'
            f'<td class="{_verdict_class(r["verdict"])}">{html_mod.escape(r["verdict"])}</td>'
            f'<td>{_fmt(r.get("close"))}</td>'
            f'<td>{html_mod.escape(r.get("px_date") or "—")}</td>'
            f'<td>{html_mod.escape(r.get("m_sup") or "—")}</td>'
            f'<td>{html_mod.escape(r.get("w_sup") or "—")}</td>'
            f'<td>{html_mod.escape(r.get("d_sup") or "—")}</td>'
            f'<td>{_fmt(r.get("w_dist"))}</td>'
            f'<td>{_fmt(r.get("w_res_dist"))}</td>'
            f'<td>{html_mod.escape(r.get("note") or "—")}</td>'
            f"<td>{chart}</td>"
            "</tr>"
        )
    return (
        f'<p class="meta">{html_mod.escape(caption)} Click column headers to sort.</p>'
        f'<table class="sortable"><thead><tr>{thead}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table>'
    )


def holdings_table_for(rows: list[dict[str, Any]], caption: str, chart_href: str) -> str:
    heads = [
        ("Symbol", "text"),
        ("System(s)", "text"),
        ("List type", "text"),
        ("Entry", "date"),
        ("Entry $", "num"),
        ("Verdict", "text"),
        ("Close", "num"),
        ("Px date", "date"),
        ("W sup", "text"),
        ("W dist %", "num"),
        ("Trendline note", "text"),
        ("Chart", "text"),
    ]
    thead = "".join(_sortable_th(l, t) for l, t in heads)
    body = []
    for r in rows:
        href = f'{html_mod.escape(chart_href)}#{html_mod.escape(r["symbol"])}'
        chart = f'<a href="{href}">chart</a>' if r.get("has_chart") else "—"
        hv = r.get("hold_verdict") or holdings_sell_verdict(r)
        body.append(
            "<tr>"
            f'<td><a href="{href}">{html_mod.escape(r["symbol"])}</a></td>'
            f'<td>{html_mod.escape(r.get("systems") or "—")}</td>'
            f'<td>{html_mod.escape(r.get("list_types") or "—")}</td>'
            f'<td>{html_mod.escape(r.get("purchase_date") or "—")}</td>'
            f'<td>{_fmt(r.get("entry_price"))}</td>'
            f'<td class="{_verdict_class(hv)}">{html_mod.escape(hv)}</td>'
            f'<td>{_fmt(r.get("close"))}</td>'
            f'<td>{html_mod.escape(r.get("px_date") or "—")}</td>'
            f'<td>{html_mod.escape(r.get("w_sup") or "—")}</td>'
            f'<td>{_fmt(r.get("w_dist"))}</td>'
            f'<td>{html_mod.escape(r.get("note") or "—")}</td>'
            f"<td>{chart}</td>"
            "</tr>"
        )
    return (
        f'<p class="meta">{html_mod.escape(caption)} Click column headers to sort.</p>'
        f'<table class="sortable"><thead><tr>{thead}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table>'
    )


def score_universe(
    symbols: list[str],
    meta: dict[str, Any],
    stamp_dir: Path,
    *,
    build_missing: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Ensure charts (default), then score each symbol. Returns (rows, ensure_info)."""
    ensure_info: dict[str, Any] = {}
    if build_missing:
        ensure_info = ensure_charts(symbols, stamp_dir)
    segs = load_segments(stamp_dir)
    charts_dir = stamp_dir / "charts"
    rows: list[dict[str, Any]] = []
    for sym in symbols:
        inv = meta.get(sym) or {}
        systems = inv.get("systems") or []
        watch = inv.get("watchlist_systems") or []
        scan = inv.get("scanner_systems") or []
        all_sys = sorted(set(list(systems) + list(watch) + list(scan)))
        kinds = inv.get("list_kinds") or []
        if not kinds:
            if inv.get("in_portfolio"):
                kinds.append("held")
            if systems:
                kinds.append("open")
            if watch:
                kinds.append("watch")
            if scan:
                kinds.append("scan")
        scored = score_symbol(sym, segs.get(sym), charts_dir=charts_dir)
        rows.append(
            {
                "symbol": sym,
                "systems": ", ".join(all_sys) if all_sys else "—",
                "list_types": ", ".join(kinds) if kinds else "—",
                "purchase_date": inv.get("purchase_date") or "",
                "entry_price": inv.get("entry_price"),
                "in_portfolio": bool(inv.get("in_portfolio")),
                **scored,
            }
        )
    return rows, ensure_info


def write_score_html(
    rows: list[dict[str, Any]],
    *,
    out_path: Path,
    ensure_info: dict[str, Any] | None = None,
    title: str = "DailyRun trendline score",
    extra_callout: str = "",
) -> Path:
    counts = defaultdict(int)
    for r in rows:
        counts[r["verdict"]] += 1
    n = {
        "BUY TODAY": int(counts["BUY TODAY"]),
        "WAIT": int(counts["WAIT"]),
        "SKIP": int(counts["SKIP"]),
        "NO CHART": int(counts["NO CHART"]),
        "NO DATA": int(counts["NO DATA"]),
    }
    buy_rows = [r for r in rows if r["verdict"] == "BUY TODAY"]
    wait_rows = [r for r in rows if r["verdict"] == "WAIT"]
    skip_rows = [r for r in rows if r["verdict"] == "SKIP"]
    none_rows = [r for r in rows if r["verdict"] in ("NO CHART", "NO DATA")]
    hold_rows = [r for r in rows if is_holding_row(r)]
    for r in hold_rows:
        r["hold_verdict"] = holdings_sell_verdict(r)
    sell_rows = [r for r in hold_rows if r.get("hold_verdict") == "SELL"]
    hold_ok = [r for r in hold_rows if r.get("hold_verdict") == "HOLD"]
    hold_none = [r for r in hold_rows if r.get("hold_verdict") in ("NO CHART", "NO DATA")]
    sell_lead = ", ".join(r["symbol"] for r in sell_rows) or "none"
    buy_lead = ", ".join(r["symbol"] for r in buy_rows) or "none"
    ab_href = "../../paul_experiments/trendline_entry_filter_ab_20260915/compare.html"
    if extra_callout:
        pass
    else:
        extra_callout = (
            '<div class="callout warn"><p><strong>Research overlay (not a live gate):</strong> '
            f'<a href="{ab_href}">Before/after at time of purchase</a> — would buy-low B '
            "have allowed the fills we already took? DailyRun still uses each system's "
            "frozen entry. Do not adopt the filter from this page.</p></div>"
        )
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    built = (ensure_info or {}).get("built") or []
    no_ohlc = (ensure_info or {}).get("no_ohlc") or []
    failed = (ensure_info or {}).get("failed") or []
    built_s = ", ".join(built) if built else "(none this run)"
    no_data_s = ", ".join(no_ohlc) if no_ohlc else "(none)"
    failed_s = ", ".join(failed) if failed else "(none)"
    chart_href = "charts/index.html" if out_path.parent.name == "trendlines_opens_latest" else CHART_INDEX_REL

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html_mod.escape(title)}</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1.5rem; color: #0f172a; background: #f8fafc; }}
h1 {{ font-size: 1.45rem; margin: 0 0 .35rem; }}
h2 {{ font-size: 1.15rem; margin: 1.6rem 0 .5rem; border-bottom: 1px solid #cbd5e1; padding-bottom: .25rem; }}
.meta, .caveat {{ color: #475569; font-size: .92rem; max-width: 78rem; }}
.callout {{ background: #fff; border: 1px solid #cbd5e1; border-radius: 8px; padding: .85rem 1.1rem; margin: .75rem 0; max-width: 78rem; }}
.ask {{ border-left: 4px solid #2563eb; }}
.plain {{ border-left: 4px solid #047857; }}
.warn {{ border-left: 4px solid #b45309; }}
.buy {{ color: #047857; font-weight: 700; }}
.wait {{ color: #b45309; font-weight: 700; }}
.skip, .sell {{ color: #b91c1c; font-weight: 700; }}
.hold {{ color: #0369a1; font-weight: 700; }}
.none {{ color: #64748b; font-weight: 600; }}
table.sortable {{ border-collapse: collapse; background: #fff; font-size: .86rem; margin: .5rem 0 1rem; max-width: 100%; }}
table.sortable th, table.sortable td {{ border: 1px solid #e2e8f0; padding: .35rem .5rem; text-align: left; vertical-align: top; }}
table.sortable th {{ background: #f1f5f9; }}
{SORT_CSS}
a {{ color: #1d4ed8; }}
ul {{ max-width: 78rem; }}
code {{ font-size: .88em; }}
</style>
</head>
<body>
<h1>{html_mod.escape(title)}</h1>
<p class="meta">Operational DailyRun overlay · shop buy-low B · not a freeze change · generated {html_mod.escape(generated)}</p>

<div class="callout ask">
<h2 style="margin-top:0;border:0">What you asked</h2>
<p>“{html_mod.escape(ORIGINAL_REQUEST)}”</p>
</div>

<div class="callout plain">
<h2 style="margin-top:0;border:0">In plain English</h2>
<p>{html_mod.escape(LAYMAN)}</p>
</div>
{extra_callout}

<div class="callout warn">
<p><strong>BUY TODAY:</strong> {html_mod.escape(buy_lead)}</p>
<p><strong>SELL holdings:</strong> {html_mod.escape(sell_lead)}</p>
<p>Counts — BUY TODAY {n['BUY TODAY']} · WAIT {n['WAIT']} · SKIP {n['SKIP']} · holdings SELL {len(sell_rows)} / HOLD {len(hold_ok)} / NO CHART {len(hold_none)} · unique names {len(rows)}</p>
<p>Charts generated this pass: {html_mod.escape(built_s)}. Still no Open-High-Low-Close (OHLC): {html_mod.escape(no_data_s)}. Build failed: {html_mod.escape(failed_s)}.</p>
</div>

<h2>How we decided</h2>
<ul>
<li><strong>Universe:</strong> gettarget helds/opens ∪ live DailyRun Open ∪ Watchlist ∪ Scanner (wired registry). Relative Strength Index (RSI) uses the house pin, not <code>RSIN_PaulScore5_IS</code>.</li>
<li><strong>Missing chart:</strong> generate monthly/weekly/daily (M/W/D) segments + PNG, then score. Do not leave a silent skip.</li>
<li><strong>BUY TODAY</strong> only when weekly support is UP and close is within the frozen <strong>{PROX_PCT:g}%</strong> band from <code>trendline_slopes_buylow_ab.py</code> hypothesis B.</li>
<li><strong>SELL holdings</strong> (conservative inverse of buy-low B, already used as SKIP on the buy overlay): weekly support DOWN and/or close more than {PROX_PCT:g}% under weekly support. Near resistance without a broken line is HOLD, not SELL. Not a DailyRun exit freeze.</li>
</ul>
<p class="caveat">Acronyms on first use: Break and ReTest (BRT); Volume Zone (VZ); Relative Strength Index (RSI); Rocket Launcher (RL); Pivot Break and Retest (WPBR); Year High (YH); StockBee (SB); Magic Touch (MTS); Relative Strength vs SPY (RS).</p>

<h2>Sell / caution holdings</h2>
<p class="meta">Current book = getTarget helds + LatestRun Open across wired DailyRun systems. Verdicts: SELL (broken or falling weekly support), HOLD (line intact or incomplete), NO CHART / NO DATA. Click column headers to sort.</p>
{holdings_table_for(sell_rows, f"{len(sell_rows)} holding(s) with a trendline SELL (weekly support DOWN or close through the line).", chart_href)}
{holdings_table_for(hold_ok, f"{len(hold_ok)} holding(s) with intact or mixed weekly support — HOLD, not a sell.", chart_href)}
{holdings_table_for(hold_none, f"{len(hold_none)} holding(s) still unscoreable after ensure-charts.", chart_href)}

<h2>Buy today</h2>
{table_for(buy_rows, f"{len(buy_rows)} name(s) on a live list and on/near rising weekly support.", chart_href)}

<h2>Watch / wait</h2>
{table_for(wait_rows, f"{len(wait_rows)} name(s) on a list but the trendline is messy, extended, or not yet at the line.", chart_href)}

<h2>Skip</h2>
{table_for(skip_rows, f"{len(skip_rows)} name(s) on a list but the trendline argues against buying now.", chart_href)}

<h2>No chart / no data</h2>
{table_for(none_rows, f"{len(none_rows)} name(s) still unscoreable after ensure-charts (true missing OHLC or failed build).", chart_href)}

<h2>Full book</h2>
{table_for(rows, f"All {len(rows)} unique symbols from opens / helds / watch / scan.", chart_href)}

{SORT_JS}
</body>
</html>
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def publish_score_copies(html_path: Path) -> list[Path]:
    """Land copies where Paul already looks."""
    copies: list[Path] = []
    latest = DRIVE / "Trendlines_BuyToday_Latest.html"
    shutil.copy2(html_path, latest)
    copies.append(latest)
    inbox = DRIVE / "mobile_inbox" / "results"
    inbox.mkdir(parents=True, exist_ok=True)
    inbox_html = inbox / "trendlines_buy_today.html"
    shutil.copy2(html_path, inbox_html)
    copies.append(inbox_html)
    return copies


def run_daily_score(
    drive: Path | None = None,
    positions_csv: Path | None = None,
    stamp_dir: Path | None = None,
    *,
    skip_ntfy: bool = False,
) -> Path:
    drive = drive or DRIVE
    stamp_dir = stamp_dir or DEFAULT_STAMP
    syms, meta = collect_opens_universe(drive, positions_csv)
    meta_j = meta_to_jsonable(meta)
    rows, ensure_info = score_universe(syms, meta_j, stamp_dir, build_missing=True)
    html_path = stamp_dir / "buy_today.html"
    write_score_html(rows, out_path=html_path, ensure_info=ensure_info)
    copies = publish_score_copies(html_path)
    summary = {
        "html": str(html_path),
        "copies": [str(p) for p in copies],
        "n_unique": len(rows),
        "counts": {
            v: sum(1 for r in rows if r["verdict"] == v)
            for v in ("BUY TODAY", "WAIT", "SKIP", "NO CHART", "NO DATA")
        },
        "buy_today": [r["symbol"] for r in rows if r["verdict"] == "BUY TODAY"],
        "holdings_sell": [
            r["symbol"]
            for r in rows
            if is_holding_row(r) and holdings_sell_verdict(r) == "SELL"
        ],
        "holdings_hold": [
            r["symbol"]
            for r in rows
            if is_holding_row(r) and holdings_sell_verdict(r) == "HOLD"
        ],
        "no_chart": [r["symbol"] for r in rows if r["verdict"] == "NO CHART"],
        "no_data": [r["symbol"] for r in rows if r["verdict"] == "NO DATA"],
        "ensure": {k: ensure_info.get(k) for k in ("built", "no_ohlc", "failed")},
    }
    (stamp_dir / "buy_today_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    if not skip_ntfy:
        import subprocess

        cmd = [
            sys.executable,
            str(_TOOLS / "ntfy_job_done.py"),
            "--path",
            str(html_path),
            "--path",
            str(DRIVE / "Trendlines_BuyToday_Latest.html"),
            "-t",
            "Trendline buy-today + sells",
            "-m",
            (
                f"DailyRun trend score — {len(rows)} names, BUY {summary['counts']['BUY TODAY']}, "
                f"SELL holdings {len(summary['holdings_sell'])}"
            ),
        ]
        subprocess.run(cmd, cwd=str(_REPO))
    return html_path


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--drive", type=Path, default=DRIVE)
    ap.add_argument("--positions-csv", type=Path, default=_REPO / "gettarget_positions.csv")
    ap.add_argument("--stamp-dir", type=Path, default=DEFAULT_STAMP)
    ap.add_argument("--skip-ntfy", action="store_true")
    args = ap.parse_args()
    run_daily_score(
        args.drive,
        args.positions_csv,
        args.stamp_dir,
        skip_ntfy=args.skip_ntfy,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
