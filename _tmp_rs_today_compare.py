"""RS same-day clusters recount + today vs Jan2025 vs Apr2026 regime compare."""
from __future__ import annotations

import csv
import html
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")
GOLD = (
    ROOT
    / "drive/paul_experiments/rs_baseline_260807141317/engine_closed/RS_Closed_260807141317.csv"
)
LATEST = ROOT / "drive/RS_LatestRun_Closed.csv"
WATCH = ROOT / "drive/RS_LatestRun_Watchlist.csv"
SPY = ROOT / "data/newdata/data/SPY.csv"
QQQ = ROOT / "data/newdata/data/QQQ.csv"
DATA = ROOT / "data/newdata/data"
OUT_HTML = ROOT / "drive/paul_experiments/RS_SameDay_Entry_Clusters.html"
OUT_COMPARE = ROOT / "drive/paul_experiments/RS_SameDay_Entry_Clusters_TodayCompare.html"
OUT_JSON = ROOT / "_tmp_rs_sameday_clusters.json"
OUT_COMPARE_JSON = ROOT / "_tmp_rs_today_compare.json"

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


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{html.escape(sort_type)}" '
        f'tabindex="0" role="columnheader" aria-sort="none">'
        f"{html.escape(label)}<span class=\"sort-ind\"></span></th>"
    )


def parse_pct(s):
    if s is None or s == "":
        return None
    return float(str(s).replace("%", "").replace(",", "").strip())


def parse_num(s):
    if s is None or s == "":
        return None
    return float(str(s).replace(",", "").strip())


def ymd(s):
    s = str(s).strip()
    if len(s) == 8 and s.isdigit():
        return datetime.strptime(s, "%Y%m%d")
    return datetime.strptime(s[:10], "%Y-%m-%d")


def fmt_date(s):
    return ymd(s).strftime("%Y-%m-%d")


def agg(trades):
    pn = [parse_pct(t["PNL_PCT"]) for t in trades]
    dol = [parse_num(t["PNL_DOLLARS"]) for t in trades]
    dh = [parse_num(t["DAYS_HELD"]) for t in trades]
    w = sum(1 for p in pn if p is not None and p > 0)
    l = sum(1 for p in pn if p is not None and p <= 0)
    return {
        "n": len(trades),
        "wins": w,
        "losses": l,
        "wr": 100.0 * w / len(trades) if trades else 0.0,
        "avg_pnl": statistics.mean(pn) if pn else 0.0,
        "med_pnl": statistics.median(pn) if pn else 0.0,
        "sum_pnl": sum(dol) if dol else 0.0,
        "avg_days": statistics.mean(dh) if dh else 0.0,
        "symbols": sorted({t["SYMBOL"] for t in trades}),
    }


def fmt_pct(x: float) -> str:
    return f"{x:+.2f}%" if x != 0 else "0.00%"


def fmt_pct_plain(x: float) -> str:
    return f"{x:.1f}%"


def fmt_money(x: float) -> str:
    return f"${x:,.0f}"


def cls_for(x: float) -> str:
    if x > 0:
        return "pos"
    if x < 0:
        return "neg"
    return ""


def load_ohlc(path: Path):
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    out = []
    for r in rows:
        out.append(
            {
                "date": r["Date"][:10],
                "open": float(r["Open"]),
                "high": float(r["High"]),
                "low": float(r["Low"]),
                "close": float(r["Close"]),
                "volume": float(r["Volume"] or 0),
                "sma20": float(r.get("SMA20") or 0) or None,
                "sma50": float(r.get("SMA50") or 0) or None,
                "sma200": float(r.get("SMA200") or 0) or None,
            }
        )
    return out


def idx_on_or_before(bars, date_str: str) -> int:
    # date_str YYYY-MM-DD
    for i in range(len(bars) - 1, -1, -1):
        if bars[i]["date"] <= date_str:
            return i
    return 0


def ret(bars, i, n):
    if i - n < 0:
        return None
    a = bars[i - n]["close"]
    b = bars[i]["close"]
    return 100.0 * (b / a - 1.0) if a else None


def dist_ma(bars, i, key):
    c = bars[i]["close"]
    m = bars[i].get(key)
    if not m:
        return None
    return 100.0 * (c / m - 1.0)


def realized_vol(bars, i, n=20):
    if i < n:
        return None
    rets = []
    for j in range(i - n + 1, i + 1):
        a = bars[j - 1]["close"]
        b = bars[j]["close"]
        if a:
            rets.append(math.log(b / a))
    if len(rets) < n:
        return None
    return 100.0 * statistics.stdev(rets) * math.sqrt(252)


def regime_for(bars_spy, bars_qqq, date_str: str) -> dict:
    i = idx_on_or_before(bars_spy, date_str)
    j = idx_on_or_before(bars_qqq, date_str)
    spy = bars_spy[i]
    qqq = bars_qqq[j]
    return {
        "as_of": spy["date"],
        "requested": date_str,
        "spy_close": spy["close"],
        "qqq_close": qqq["close"],
        "spy_1d": ret(bars_spy, i, 1),
        "spy_5d": ret(bars_spy, i, 5),
        "spy_20d": ret(bars_spy, i, 20),
        "qqq_1d": ret(bars_qqq, j, 1),
        "qqq_5d": ret(bars_qqq, j, 5),
        "qqq_20d": ret(bars_qqq, j, 20),
        "spy_vs_sma20": dist_ma(bars_spy, i, "sma20"),
        "spy_vs_sma50": dist_ma(bars_spy, i, "sma50"),
        "spy_vs_sma200": dist_ma(bars_spy, i, "sma200"),
        "qqq_vs_sma20": dist_ma(bars_qqq, j, "sma20"),
        "qqq_vs_sma50": dist_ma(bars_qqq, j, "sma50"),
        "qqq_vs_sma200": dist_ma(bars_qqq, j, "sma200"),
        "spy_rv20": realized_vol(bars_spy, i, 20),
        "qqq_rv20": realized_vol(bars_qqq, j, 20),
        "spy_above_sma20": (spy["sma20"] or 0) > 0 and spy["close"] > spy["sma20"],
        "spy_above_sma50": (spy["sma50"] or 0) > 0 and spy["close"] > spy["sma50"],
        "spy_above_sma200": (spy["sma200"] or 0) > 0 and spy["close"] > spy["sma200"],
    }


def try_vix(date_str: str):
    try:
        import duckdb

        con = duckdb.connect(str(ROOT / "data/ohlcv.duckdb"), read_only=True)
        tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
        for cand in tables:
            cols = [c[0].lower() for c in con.execute(f"DESCRIBE {cand}").fetchall()]
            if "vix" in cand.lower() or any("vix" in c for c in cols):
                print("VIX-ish table", cand, cols[:20])
        # common patterns
        for q in [
            "SELECT * FROM vix ORDER BY date DESC LIMIT 1",
            "SELECT * FROM VIX ORDER BY Date DESC LIMIT 1",
            "SELECT * FROM market_index WHERE symbol='VIX' LIMIT 5",
        ]:
            try:
                print("try", q, con.execute(q).fetchall()[:3])
            except Exception:
                pass
        # list all tables briefly
        for t in tables:
            if "vix" in t.lower() or "index" in t.lower() or "breadth" in t.lower():
                print("table", t)
        con.close()
    except Exception as e:
        print("duckdb vix lookup failed", e)
    # CSV fallback
    for p in [
        DATA / "VIX.csv",
        DATA / "^VIX.csv",
        ROOT / "data/VIX.csv",
    ]:
        if p.exists():
            bars = load_ohlc(p)
            i = idx_on_or_before(bars, date_str)
            return bars[i]["close"], bars[i]["date"]
    return None, None


def load_symbol_bars(sym: str):
    p = DATA / f"{sym}.csv"
    if not p.exists():
        return None
    return load_ohlc(p)


def symbol_prebuy_stats(sym: str, as_of: str) -> dict | None:
    bars = load_symbol_bars(sym)
    if not bars:
        return None
    i = idx_on_or_before(bars, as_of)
    if i < 5:
        return None
    # consecutive down closes ending at as_of (or day before entry?)
    # For historical entries, DATE_OPENED is entry day; prior down days = closes before entry.
    # For watchlist AS_OF, signal bar is as_of; prior down days before signal.
    end = i - 1  # prior day relative to as_of/entry
    if end < 1:
        return None
    down = 0
    k = end
    while k >= 1 and bars[k]["close"] < bars[k - 1]["close"]:
        down += 1
        k -= 1
    # extension vs 20d high / 52w high
    window20 = bars[max(0, end - 19) : end + 1]
    window252 = bars[max(0, end - 251) : end + 1]
    hi20 = max(b["high"] for b in window20)
    hi252 = max(b["high"] for b in window252)
    close = bars[end]["close"]
    pct20 = 100.0 * (close / hi20 - 1.0) if hi20 else None
    pct252 = 100.0 * (close / hi252 - 1.0) if hi252 else None
    # distance to SMA20/50
    sma20 = bars[end].get("sma20")
    sma50 = bars[end].get("sma50")
    vs20 = 100.0 * (close / sma20 - 1.0) if sma20 else None
    vs50 = 100.0 * (close / sma50 - 1.0) if sma50 else None
    # 5d return into as_of
    r5 = ret(bars, end, 5)
    return {
        "symbol": sym,
        "prior_close_date": bars[end]["date"],
        "consec_down": down,
        "pct_off_20d_high": pct20,
        "pct_off_52w_high": pct252,
        "vs_sma20": vs20,
        "vs_sma50": vs50,
        "ret_5d": r5,
    }


def cluster_character(symbols, as_of: str, closed_rows_by_sym=None):
    stats = []
    for s in symbols:
        st = symbol_prebuy_stats(s, as_of)
        if st:
            stats.append(st)
    sectors = Counter()
    industries = Counter()
    if closed_rows_by_sym:
        for s in symbols:
            r = closed_rows_by_sym.get(s)
            if r:
                sectors[r.get("SECTOR") or "?"] += 1
                industries[r.get("INDUSTRY") or "?"] += 1
    else:
        # try open/closed for sector
        pass
    return {
        "n": len(symbols),
        "symbols": symbols,
        "stats": stats,
        "median_consec_down": statistics.median([s["consec_down"] for s in stats]) if stats else None,
        "avg_consec_down": statistics.mean([s["consec_down"] for s in stats]) if stats else None,
        "median_off_20d": statistics.median([s["pct_off_20d_high"] for s in stats]) if stats else None,
        "median_off_52w": statistics.median([s["pct_off_52w_high"] for s in stats]) if stats else None,
        "median_vs_sma20": statistics.median([s["vs_sma20"] for s in stats if s["vs_sma20"] is not None]) if stats else None,
        "median_vs_sma50": statistics.median([s["vs_sma50"] for s in stats if s["vs_sma50"] is not None]) if stats else None,
        "median_ret5": statistics.median([s["ret_5d"] for s in stats if s["ret_5d"] is not None]) if stats else None,
        "n_near_20d_high": sum(1 for s in stats if s["pct_off_20d_high"] is not None and s["pct_off_20d_high"] >= -3),
        "n_down_ge2": sum(1 for s in stats if s["consec_down"] >= 2),
        "sectors": dict(sectors),
        "industries": dict(industries),
    }


def analyze_closed(path: Path):
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    by_open: dict[str, list] = defaultdict(list)
    for r in rows:
        by_open[r["DATE_OPENED"]].append(r)
    counts = sorted(((d, len(tr)) for d, tr in by_open.items()), key=lambda x: (-x[1], x[0]))
    max_n = counts[0][1] if counts else 0
    n_hist = Counter(nn for _, nn in counts)
    pnls = [parse_pct(r["PNL_PCT"]) for r in rows]
    dollars = [parse_num(r["PNL_DOLLARS"]) for r in rows]
    days = [parse_num(r["DAYS_HELD"]) for r in rows]
    wins = sum(1 for p in pnls if p is not None and p > 0)
    n = len(rows)
    base = {
        "n": n,
        "wr": 100.0 * wins / n,
        "avg_pnl": statistics.mean(pnls),
        "med_pnl": statistics.median(pnls),
        "sum_pnl": sum(dollars),
        "avg_days": statistics.mean(days),
    }
    high_days = [(d, by_open[d]) for d, nn in counts if nn >= 8]
    day_stats = []
    for d, trades in high_days:
        a = agg(trades)
        a["date"] = d
        a["date_fmt"] = fmt_date(d)
        # sector mix
        a["sectors"] = dict(Counter(t.get("SECTOR") or "?" for t in trades))
        a["industries"] = dict(Counter(t.get("INDUSTRY") or "?" for t in trades))
        day_stats.append(a)

    def pool(thresh: int):
        ts = []
        for d, nn in counts:
            if nn >= thresh:
                ts.extend(by_open[d])
        return agg(ts) if ts else None

    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "n_trades": n,
        "n_days": len(by_open),
        "max_n": max_n,
        "n_gt_12": sum(1 for _, nn in counts if nn > 12),
        "n_ge": {t: sum(1 for _, nn in counts if nn >= t) for t in (8, 10, 12)},
        "n_hist": {str(k): v for k, v in sorted(n_hist.items())},
        "top_counts": [(fmt_date(d), nn) for d, nn in counts[:40]],
        "day_stats": day_stats,
        "base": base,
        "pools": {
            str(t): (
                {k: (v if k != "symbols" else len(v)) for k, v in pool(t).items()}
                if pool(t)
                else None
            )
            for t in (8, 10, 12)
        },
        "by_open": by_open,
        "rows": rows,
    }


def fmt_opt(x, digits=2, suffix="%"):
    if x is None:
        return "—"
    return f"{x:+.{digits}f}{suffix}" if suffix == "%" else f"{x:.{digits}f}{suffix}"


def score_similarity(today_reg, hist_reg, today_char, hist_char, overlap_n, overlap_frac, breadth=None, hist_breadth_key=None):
    """Higher = more similar to hist.

    Weights prioritize RS cluster character (extension / leadership overlap)
    over raw SPY beta, because the Jan-vs-Apr distinction is crowded-at-highs
    failed multi-buy vs constructive multi-buy.
    """
    score = 0.0
    notes = []

    def close_num(a, b, scale):
        if a is None or b is None:
            return 0.0
        return max(0.0, 1.0 - abs(a - b) / scale)

    # Index tape (lower weight — all three dates are bull-structure)
    for key, w in [("spy_above_sma20", 0.5), ("spy_above_sma50", 0.5), ("spy_above_sma200", 0.5)]:
        if today_reg[key] == hist_reg[key]:
            score += w
            notes.append(f"+{w} same {key}={today_reg[key]}")

    for key, scale, w in [
        ("spy_5d", 5.0, 0.8),
        ("spy_20d", 10.0, 1.0),
        ("spy_vs_sma20", 5.0, 0.6),
        ("spy_vs_sma50", 8.0, 0.8),
        ("spy_vs_sma200", 12.0, 1.0),
        ("spy_rv20", 15.0, 0.8),
        ("qqq_20d", 10.0, 1.2),
        ("qqq_rv20", 15.0, 1.0),
    ]:
        s = w * close_num(today_reg.get(key), hist_reg.get(key), scale)
        score += s
        notes.append(f"+{s:.2f} {key}")

    # Cluster character (high weight — defines crowded vs constructive)
    for key, scale, w in [
        ("median_consec_down", 3.0, 1.5),
        ("median_off_20d", 8.0, 3.0),
        ("median_off_52w", 15.0, 2.5),
        ("median_vs_sma20", 10.0, 1.5),
        ("median_vs_sma50", 10.0, 2.5),
        ("median_ret5", 10.0, 1.0),
    ]:
        s = w * close_num(today_char.get(key), hist_char.get(key), scale)
        score += s
        notes.append(f"+{s:.2f} char.{key}")

    # Near-high crowding fingerprint
    t_near = today_char.get("n_near_20d_high")
    h_near = hist_char.get("n_near_20d_high")
    if t_near is not None and h_near is not None:
        s = 3.0 * close_num(float(t_near), float(h_near), 12.0)
        score += s
        notes.append(f"+{s:.2f} n_near_20d_high ({t_near} vs {h_near})")

    # Symbol / leadership overlap (high weight)
    ov = 6.0 * overlap_frac
    score += ov
    notes.append(f"+{ov:.2f} symbol_overlap {overlap_n}/{today_char['n']} ({overlap_frac:.0%})")

    # Tech-share similarity
    def tech_share(char):
        secs = char.get("sectors") or {}
        n = char.get("n") or 1
        return 100.0 * secs.get("Technology", 0) / n

    s = 1.5 * close_num(tech_share(today_char), tech_share(hist_char), 40.0)
    score += s
    notes.append(f"+{s:.2f} tech_share")

    if breadth and hist_breadth_key and breadth.get("today") and breadth.get(hist_breadth_key):
        s = 1.0 * close_num(
            breadth["today"].get("pct_above_sma50"),
            breadth[hist_breadth_key].get("pct_above_sma50"),
            40.0,
        )
        score += s
        notes.append(f"+{s:.2f} breadth_sma50")

    return score, notes

def main():
    print("=== Closed recount ===")
    gold = analyze_closed(GOLD)
    latest = analyze_closed(LATEST)
    print(
        f"GOLD maxN={gold['max_n']} N>12={gold['n_gt_12']} N>=8={gold['n_ge'][8]} trades={gold['n_trades']}"
    )
    print(
        f"LATEST maxN={latest['max_n']} N>12={latest['n_gt_12']} N>=8={latest['n_ge'][8]} trades={latest['n_trades']}"
    )
    for a in gold["day_stats"]:
        print(
            f"  {a['date_fmt']} N={a['n']} WR={a['wr']:.1f}% avg={a['avg_pnl']:.2f} "
            f"syms={','.join(a['symbols'])}"
        )

    spy = load_ohlc(SPY)
    qqq = load_ohlc(QQQ)
    today_date = spy[-1]["date"]
    print(f"\nLatest SPY session: {today_date}")

    wl = list(csv.DictReader(WATCH.open(encoding="utf-8")))
    would_buy = [r for r in wl if r.get("ROW_TYPE") == "SCANNER"]
    today_syms = sorted({r["SYMBOL"] for r in would_buy})
    as_of_wl = would_buy[0]["AS_OF_DATE"] if would_buy else today_date.replace("-", "")
    as_of_fmt = fmt_date(as_of_wl) if len(as_of_wl) == 8 else as_of_wl
    print(f"Watchlist AS_OF={as_of_fmt} would-buy N={len(today_syms)}: {','.join(today_syms)}")

    # All gold-65 N≥8 cluster dates (canonical order by N desc then date)
    hist_days = sorted(gold["day_stats"], key=lambda a: (-a["n"], a["date_fmt"]))
    hist_keys = []
    date_map = {"today": as_of_fmt}
    for a in hist_days:
        key = a["date_fmt"]  # YYYY-MM-DD used as stable label
        hist_keys.append(key)
        date_map[key] = a["date_fmt"]

    regimes = {k: regime_for(spy, qqq, d) for k, d in date_map.items()}
    for k in ["today"] + hist_keys:
        print(k, regimes[k])

    try_vix(as_of_fmt)
    vix = {"today": try_csv_vix(as_of_fmt)}
    for k in hist_keys:
        vix[k] = try_csv_vix(k)
    print("VIX", {k: vix[k] for k in ["today"] + hist_keys[:2]})

    def map_trades(trades):
        return {t["SYMBOL"]: t for t in trades}

    open_path = ROOT / "drive/RS_LatestRun_Open.csv"
    open_rows = list(csv.DictReader(open_path.open(encoding="utf-8"))) if open_path.exists() else []
    closed_rows = latest["rows"]
    sector_lookup = {}
    for r in closed_rows + open_rows:
        sector_lookup[r["SYMBOL"]] = {
            "SECTOR": r.get("SECTOR") or "?",
            "INDUSTRY": r.get("INDUSTRY") or "?",
        }
    sum_path = ROOT / "drive/RS_LatestRun_Summary.csv"
    if sum_path.exists():
        for r in csv.DictReader(sum_path.open(encoding="utf-8")):
            if r.get("SYMBOL"):
                sector_lookup[r["SYMBOL"]] = {
                    "SECTOR": r.get("SECTOR") or sector_lookup.get(r["SYMBOL"], {}).get("SECTOR", "?"),
                    "INDUSTRY": r.get("INDUSTRY")
                    or sector_lookup.get(r["SYMBOL"], {}).get("INDUSTRY", "?"),
                }

    today_char = cluster_character(today_syms, as_of_fmt)
    today_char["sectors"] = dict(
        Counter(sector_lookup.get(s, {}).get("SECTOR", "?") for s in today_syms)
    )
    today_char["industries"] = dict(
        Counter(sector_lookup.get(s, {}).get("INDUSTRY", "?") for s in today_syms)
    )

    breadth = approx_breadth(date_map)

    comparisons = []
    chars = {"today": {k: v for k, v in today_char.items() if k != "stats"}}
    char_stats = {"today": today_char["stats"]}
    outcomes = {}

    for a in hist_days:
        d = a["date_fmt"]
        raw = d.replace("-", "")
        trades = gold["by_open"].get(raw) or gold["by_open"].get(d) or []
        if not trades:
            # try fuzzy key
            for k, v in gold["by_open"].items():
                if fmt_date(k) == d:
                    trades = v
                    break
        syms = sorted({t["SYMBOL"] for t in trades})
        hchar = cluster_character(syms, d, map_trades(trades))
        chars[d] = {k: v for k, v in hchar.items() if k != "stats"}
        char_stats[d] = hchar["stats"]
        ov = sorted(set(today_syms) & set(syms))
        ov_frac = len(ov) / max(1, len(today_syms))
        score, notes = score_similarity(
            regimes["today"],
            regimes[d],
            today_char,
            hchar,
            len(ov),
            ov_frac,
            breadth=breadth,
            hist_breadth_key=d,
        )
        oc = {
            "wr": a["wr"],
            "avg_pnl": a["avg_pnl"],
            "med_pnl": a["med_pnl"],
            "sum_pnl": a["sum_pnl"],
            "symbols": syms,
            "n": a["n"],
        }
        outcomes[d] = oc
        cmp = {
            "date": d,
            "n_hist": a["n"],
            "score": score,
            "notes": notes,
            "overlap": ov,
            "overlap_n": len(ov),
            "overlap_frac": ov_frac,
            "regime": regimes[d],
            "char": chars[d],
            "outcomes": oc,
            "today_char_snip": {
                "n_near_20d_high": today_char.get("n_near_20d_high"),
                "median_off_20d": today_char.get("median_off_20d"),
                "median_vs_sma50": today_char.get("median_vs_sma50"),
            },
            "today_regime_snip": {
                "spy_20d": regimes["today"].get("spy_20d"),
                "spy_rv20": regimes["today"].get("spy_rv20"),
                "qqq_20d": regimes["today"].get("qqq_20d"),
            },
        }
        cmp["why"] = one_line_why(cmp)
        comparisons.append(cmp)
        print(f"score {d} N={a['n']} = {score:.2f} ov={ov} | {cmp['why']}")

    comparisons.sort(key=lambda x: (-x["score"], -x["n_hist"], x["date"]))
    for rank, c in enumerate(comparisons, 1):
        c["rank"] = rank

    winner = comparisons[0]
    runner = comparisons[1] if len(comparisons) > 1 else None
    # Back-compat keys for older summary block
    score_jan = next((c["score"] for c in comparisons if c["date"] == "2025-01-22"), None)
    score_apr = next((c["score"] for c in comparisons if c["date"] == "2026-04-08"), None)
    closer = winner["date"]

    payload = {
        "today_date": as_of_fmt,
        "spy_last": today_date,
        "would_buy_n": len(today_syms),
        "would_buy": today_syms,
        "gold": {
            "max_n": gold["max_n"],
            "n_gt_12": gold["n_gt_12"],
            "n_ge": gold["n_ge"],
            "day_stats": [
                {k: v for k, v in a.items() if k != "date"} for a in gold["day_stats"]
            ],
            "top_counts": gold["top_counts"],
            "n_hist": gold["n_hist"],
            "base": gold["base"],
            "pools": gold["pools"],
            "path": gold["path"],
        },
        "latestrun": {
            "max_n": latest["max_n"],
            "n_gt_12": latest["n_gt_12"],
            "n_ge": latest["n_ge"],
            "n_trades": latest["n_trades"],
            "path": latest["path"],
            "same_ge8_dates": [a["date_fmt"] for a in latest["day_stats"]]
            == [a["date_fmt"] for a in gold["day_stats"]],
        },
        "hist_dates": hist_keys,
        "regimes": regimes,
        "vix": vix,
        "chars": chars,
        "char_stats": char_stats,
        "outcomes": outcomes,
        "comparisons": [
            {
                "rank": c["rank"],
                "date": c["date"],
                "n_hist": c["n_hist"],
                "score": c["score"],
                "why": c["why"],
                "overlap": c["overlap"],
                "overlap_n": c["overlap_n"],
                "overlap_frac": c["overlap_frac"],
                "outcomes": c["outcomes"],
                "notes": c["notes"],
            }
            for c in comparisons
        ],
        "winner": winner["date"],
        "runner_up": runner["date"] if runner else None,
        "winner_score": winner["score"],
        "runner_score": runner["score"] if runner else None,
        # legacy pairwise fields
        "overlap_jan": next((c["overlap"] for c in comparisons if c["date"] == "2025-01-22"), []),
        "overlap_apr": next((c["overlap"] for c in comparisons if c["date"] == "2026-04-08"), []),
        "score_jan": score_jan,
        "score_apr": score_apr,
        "notes_jan": next((c["notes"] for c in comparisons if c["date"] == "2025-01-22"), []),
        "notes_apr": next((c["notes"] for c in comparisons if c["date"] == "2026-04-08"), []),
        "closer": closer,
        "breadth": breadth,
        "jan_outcomes": outcomes.get("2025-01-22"),
        "apr_outcomes": outcomes.get("2026-04-08"),
    }
    OUT_COMPARE_JSON.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {OUT_COMPARE_JSON}")
    runner_s = f"{runner['score']:.2f}" if runner else "n/a"
    print(
        f"WINNER {winner['date']} score={winner['score']:.2f}; "
        f"runner-up {runner['date'] if runner else '—'} score={runner_s}"
    )

    write_clusters_html(gold, latest, payload)
    write_compare_html(payload, gold)
    print(f"Wrote {OUT_HTML}")
    print(f"Wrote {OUT_COMPARE}")


def try_csv_vix(date_str):
    for p in [DATA / "VIX.csv", DATA / "^VIX.csv", ROOT / "data/VIX.csv", ROOT / "data/newdata/VIX.csv"]:
        if p.exists():
            bars = load_ohlc(p)
            i = idx_on_or_before(bars, date_str)
            return {"close": bars[i]["close"], "date": bars[i]["date"], "path": str(p)}
    # duckdb
    try:
        import duckdb

        con = duckdb.connect(str(ROOT / "data/ohlcv.duckdb"), read_only=True)
        tabs = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
        for t in tabs:
            cols = [c[0] for c in con.execute(f'DESCRIBE "{t}"').fetchall()]
            col_l = [c.lower() for c in cols]
            if "vix" in t.lower():
                date_col = next((c for c in cols if c.lower() in ("date", "dt", "timestamp")), cols[0])
                close_col = next(
                    (c for c in cols if c.lower() in ("close", "adj_close", "value", "vix")),
                    cols[-1],
                )
                q = f'SELECT "{date_col}", "{close_col}" FROM "{t}" WHERE CAST("{date_col}" AS VARCHAR) <= ? ORDER BY "{date_col}" DESC LIMIT 1'
                row = con.execute(q, [date_str]).fetchone()
                if row:
                    return {"close": float(row[1]), "date": str(row[0])[:10], "path": f"duckdb:{t}"}
            # symbol column
            if "symbol" in col_l and any(x in col_l for x in ("close", "adj_close", "value")):
                sym_col = cols[col_l.index("symbol")]
                date_col = next((c for c in cols if c.lower() in ("date", "dt")), None)
                close_col = next((c for c in cols if c.lower() in ("close", "adj_close", "value")), None)
                if date_col and close_col:
                    try:
                        q = (
                            f'SELECT "{date_col}", "{close_col}" FROM "{t}" '
                            f'WHERE "{sym_col}" IN (\'VIX\',\'^VIX\') AND CAST("{date_col}" AS VARCHAR) <= ? '
                            f'ORDER BY "{date_col}" DESC LIMIT 1'
                        )
                        row = con.execute(q, [date_str]).fetchone()
                        if row:
                            return {
                                "close": float(row[1]),
                                "date": str(row[0])[:10],
                                "path": f"duckdb:{t}",
                            }
                    except Exception:
                        pass
        con.close()
    except Exception as e:
        print("vix duck", e)
    return None


def approx_breadth(date_map: dict[str, str]):
    """% of available RS-relevant tickers above SMA50 on each date (from Summary universe).

    date_map: label -> YYYY-MM-DD (include 'today' plus each hist cluster date key).
    """
    sum_path = ROOT / "drive/RS_LatestRun_Summary.csv"
    if not sum_path.exists():
        return None
    syms = [
        r["SYMBOL"]
        for r in csv.DictReader(sum_path.open(encoding="utf-8"))
        if r.get("SYMBOL") and r["SYMBOL"] != "TOTAL"
    ]
    out = {}
    for label, d in date_map.items():
        above20 = above50 = above200 = n = 0
        for s in syms:
            bars = load_symbol_bars(s)
            if not bars:
                continue
            i = idx_on_or_before(bars, d)
            b = bars[i]
            if not b.get("sma50"):
                continue
            n += 1
            if b.get("sma20") and b["close"] > b["sma20"]:
                above20 += 1
            if b["close"] > b["sma50"]:
                above50 += 1
            if b.get("sma200") and b["close"] > b["sma200"]:
                above200 += 1
        out[label] = {
            "n": n,
            "pct_above_sma20": 100.0 * above20 / n if n else None,
            "pct_above_sma50": 100.0 * above50 / n if n else None,
            "pct_above_sma200": 100.0 * above200 / n if n else None,
        }
        print(label, "breadth", out[label])
    return out


def one_line_why(cmp: dict) -> str:
    """Short resemblance rationale for ranked table."""
    bits = []
    ov = cmp.get("overlap") or []
    bits.append(f"overlap {len(ov)}/{cmp['n_hist']} ({', '.join(ov[:4]) or 'none'}{'...' if len(ov) > 4 else ''})")
    hc = cmp.get("char") or {}
    tc = cmp.get("today_char_snip") or {}
    if hc.get("n_near_20d_high") is not None and tc.get("n_near_20d_high") is not None:
        bits.append(f"near-20d {tc['n_near_20d_high']} vs {hc['n_near_20d_high']}")
    if hc.get("median_off_20d") is not None and tc.get("median_off_20d") is not None:
        bits.append(
            f"med%off20d {tc['median_off_20d']:+.1f} vs {hc['median_off_20d']:+.1f}"
        )
    hr = cmp.get("regime") or {}
    tr = cmp.get("today_regime_snip") or {}
    if hr.get("spy_20d") is not None and tr.get("spy_20d") is not None:
        bits.append(f"SPY20d {tr['spy_20d']:+.1f} vs {hr['spy_20d']:+.1f}")
    if hr.get("spy_rv20") is not None and tr.get("spy_rv20") is not None:
        bits.append(f"RV20 {tr['spy_rv20']:.0f} vs {hr['spy_rv20']:.0f}")
    return "; ".join(bits)


def write_clusters_html(gold, latest, payload):
    base = gold["base"]
    max_n = gold["max_n"]
    day_stats = gold["day_stats"]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    verdict = (
        f"<strong>Max same-day N = {max_n}</strong> on the canonical gold-65 / LatestRun books. "
        f"<strong>No day exceeded 12</strong> on gold-65 "
        f"(<code>260807141317</code>) or LatestRun Closed "
        f"(max also {latest['max_n']}; N&gt;12 days = {latest['n_gt_12']}). "
        f"Exactly <strong>{gold['n_ge'][12]}</strong> days hit N=12: "
        f"2025-01-22 (disaster) and 2026-04-08 (fine). "
        f"Older experimental Closed stamps (non-gold universes/params) can show N&gt;12; "
        f"those are out of scope for this gold-65 recount."
    )

    thresh_rows = []
    for t in (8, 10, 12):
        p = gold["pools"].get(str(t))
        nd = gold["n_ge"][t]
        if not p:
            thresh_rows.append(
                f"<tr><td>≥{t}</td><td>{nd}</td><td colspan='7'>— no days —</td></tr>"
            )
            continue
        d_wr = p["wr"] - base["wr"]
        d_avg = p["avg_pnl"] - base["avg_pnl"]
        d_days = p["avg_days"] - base["avg_days"]
        thresh_rows.append(
            "<tr>"
            f"<td>≥{t}</td>"
            f"<td>{nd}</td>"
            f"<td>{p['n']}</td>"
            f"<td>{p['wins']}/{p['losses']}</td>"
            f"<td class='{cls_for(d_wr)}'>{fmt_pct_plain(p['wr'])} ({d_wr:+.1f}pp)</td>"
            f"<td class='{cls_for(p['avg_pnl'])}'>{fmt_pct(p['avg_pnl'])}</td>"
            f"<td class='{cls_for(p['med_pnl'])}'>{fmt_pct(p['med_pnl'])}</td>"
            f"<td class='{cls_for(p['sum_pnl'])}'>{fmt_money(p['sum_pnl'])}</td>"
            f"<td>{p['avg_days']:.1f} ({d_days:+.1f})</td>"
            "</tr>"
        )

    detail_rows = []
    for a in day_stats:
        d_wr = a["wr"] - base["wr"]
        d_avg = a["avg_pnl"] - base["avg_pnl"]
        d_days = a["avg_days"] - base["avg_days"]
        syms = ", ".join(a["symbols"])
        sec = ", ".join(f"{k}×{v}" for k, v in sorted(a.get("sectors", {}).items(), key=lambda x: -x[1]))
        detail_rows.append(
            "<tr>"
            f"<td>{html.escape(a['date_fmt'])}</td>"
            f"<td>{a['n']}</td>"
            f"<td>{html.escape(syms)}</td>"
            f"<td>{html.escape(sec)}</td>"
            f"<td>{a['wins']}/{a['losses']}</td>"
            f"<td class='{cls_for(d_wr)}'>{fmt_pct_plain(a['wr'])} ({d_wr:+.1f}pp)</td>"
            f"<td class='{cls_for(a['avg_pnl'])}'>{fmt_pct(a['avg_pnl'])}</td>"
            f"<td class='{cls_for(a['med_pnl'])}'>{fmt_pct(a['med_pnl'])}</td>"
            f"<td class='{cls_for(a['sum_pnl'])}'>{fmt_money(a['sum_pnl'])}</td>"
            f"<td>{a['avg_days']:.1f} ({d_days:+.1f})</td>"
            "</tr>"
        )

    top_rows = []
    for d, nn in gold["top_counts"][:30]:
        top_rows.append(f"<tr><td>{html.escape(d)}</td><td>{nn}</td></tr>")

    hist_rows = []
    for nn in sorted((int(k) for k in gold["n_hist"]), reverse=True):
        hist_rows.append(f"<tr><td>{nn}</td><td>{gold['n_hist'][str(nn)]}</td></tr>")

    comps = payload.get("comparisons") or []
    winner = payload.get("winner") or payload.get("closer")
    runner = payload.get("runner_up")
    wscore = payload.get("winner_score")
    rscore = payload.get("runner_score")
    rank_bits = []
    for c in comps[:3]:
        rank_bits.append(f"{c['date']} ({c['score']:.1f})")
    today_section = f"""
<section>
<h2>Today vs all gold-65 N≥8 cluster dates</h2>
<div class="def">
  <strong>Today</strong> = latest RS session <code>{html.escape(payload['today_date'])}</code>
  (SPY last bar {html.escape(payload['spy_last'])}).
  Would-buy / same-day entry pressure: <strong>{payload['would_buy_n']}</strong> names
  ({html.escape(', '.join(payload['would_buy']))}).
  <br><strong>Verdict:</strong> most resembles <strong>{html.escape(str(winner))}</strong>
  (score {wscore:.1f}{f'; runner-up {html.escape(str(runner))} ({rscore:.1f})' if runner and rscore is not None else ''}).
  Top-3: {html.escape(', '.join(rank_bits))}.
  Full ranked write-up:
  <a href="RS_SameDay_Entry_Clusters_TodayCompare.html">RS_SameDay_Entry_Clusters_TodayCompare.html</a>.
</div>
</section>
"""

    page = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>RS Same-Day Entry Clusters</title>
<style>
body {{ font-family: system-ui, sans-serif; margin:24px; color:#0f172a; max-width:1400px; }}
h1 {{ font-size:1.5rem; margin-bottom:4px; }}
h2 {{ font-size:1.15rem; margin-top:28px; }}
.sub {{ color:#64748b; margin-bottom:20px; line-height:1.5; font-size:0.95rem; }}
.small {{ font-size:12px; color:#64748b; }}
.pos {{ color:#16a34a; }} .neg {{ color:#dc2626; }}
.table-wrap {{ overflow-x:auto; margin:8px 0; }}
table {{ border-collapse:collapse; font-size:12px; width:100%; }}
th, td {{ border:1px solid #e2e8f0; padding:7px 8px; text-align:left; vertical-align:top; }}
th {{ background:#f1f5f9; }}
th.sortable-th {{ cursor:pointer; user-select:none; white-space:nowrap; }}
th.sortable-th:hover {{ background:#e2e8f0; }}
.sort-ind {{ display:inline-block; width:0.9em; margin-left:4px; color:#94a3b8; font-size:10px; }}
th.sort-asc .sort-ind::after {{ content:"▲"; color:#334155; }}
th.sort-desc .sort-ind::after {{ content:"▼"; color:#334155; }}
tr.total-row th, tr.total-row td {{ background:#f8fafc; border-top:2px solid #334155; }}
code {{ font-size:11px; background:#f1f5f9; padding:1px 4px; border-radius:3px; }}
.def {{ background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px 14px; margin:12px 0 20px; font-size:0.92rem; line-height:1.5; }}
.verdict {{ font-size:1.05rem; margin:12px 0 8px; }}
a {{ color:#0369a1; }}
</style></head><body>
<h1>RS Same-Day Entry Clusters</h1>
<p class="sub">
  Gold-65 Closed stamp <code>260807141317</code>
  (<code>{html.escape(gold['path'])}</code>).
  Cross-check: LatestRun Closed (<code>{html.escape(latest['path'])}</code>,
  {latest['n_trades']} trades) — same max N and same N≥8 calendar dates.
  Primary metric: entries opened on the same calendar day (<code>DATE_OPENED</code>).
  Generated {now}. Book size: {base['n']} closed trades.
</p>

<div class="def verdict">
  {verdict}
</div>

<div class="def">
  <strong>Book baseline:</strong>
  WR {fmt_pct_plain(base['wr'])},
  avg PNL% {fmt_pct(base['avg_pnl'])},
  median PNL% {fmt_pct(base['med_pnl'])},
  sum PnL$ {fmt_money(base['sum_pnl'])},
  avg days held {base['avg_days']:.1f}.
  Deltas in tables are vs this baseline (pp = percentage points).
</div>

{today_section}

<section>
<h2>Threshold pools (all trades on days with N≥threshold)</h2>
<p class="small">Click column headers to sort.</p>
<div class="table-wrap">
<table class="sortable">
  <thead><tr>
    {sortable_th("Threshold", "text")}
    {sortable_th("# Days", "num")}
    {sortable_th("# Trades", "num")}
    {sortable_th("W/L", "text")}
    {sortable_th("WR (Δpp)", "num")}
    {sortable_th("Avg PNL%", "num")}
    {sortable_th("Med PNL%", "num")}
    {sortable_th("Sum PnL$", "num")}
    {sortable_th("Avg days (Δ)", "num")}
  </tr></thead>
  <tbody>
    {''.join(thresh_rows)}
    <tr class="total-row">
      <td><strong>Book baseline</strong></td>
      <td>—</td>
      <td>{base['n']}</td>
      <td>—</td>
      <td>{fmt_pct_plain(base['wr'])}</td>
      <td class="{cls_for(base['avg_pnl'])}">{fmt_pct(base['avg_pnl'])}</td>
      <td class="{cls_for(base['med_pnl'])}">{fmt_pct(base['med_pnl'])}</td>
      <td class="{cls_for(base['sum_pnl'])}">{fmt_money(base['sum_pnl'])}</td>
      <td>{base['avg_days']:.1f}</td>
    </tr>
  </tbody>
</table>
</div>
</section>

<section>
<h2>All high-activity days (N≥8) — full metrics</h2>
<p class="small">Click column headers to sort. Comprehensive list of every day with ≥8 same-day RS entries. Symbols alphabetical.</p>
<div class="table-wrap">
<table class="sortable">
  <thead><tr>
    {sortable_th("DATE_OPENED", "date")}
    {sortable_th("N", "num")}
    {sortable_th("Symbols", "text")}
    {sortable_th("Sectors", "text")}
    {sortable_th("W/L", "text")}
    {sortable_th("WR (Δpp)", "num")}
    {sortable_th("Avg PNL%", "num")}
    {sortable_th("Med PNL%", "num")}
    {sortable_th("Sum PnL$", "num")}
    {sortable_th("Avg days (Δ)", "num")}
  </tr></thead>
  <tbody>
    {''.join(detail_rows) if detail_rows else '<tr><td colspan="10">No days with N≥8</td></tr>'}
  </tbody>
</table>
</div>
</section>

<section>
<h2>Distribution of same-day N</h2>
<p class="small">Click column headers to sort.</p>
<div class="table-wrap">
<table class="sortable" style="max-width:320px">
  <thead><tr>
    {sortable_th("N entries", "num")}
    {sortable_th("# Days", "num")}
  </tr></thead>
  <tbody>{''.join(hist_rows)}</tbody>
</table>
</div>
</section>

<section>
<h2>Top DATE_OPENED by entry count</h2>
<p class="small">Click column headers to sort.</p>
<div class="table-wrap">
<table class="sortable" style="max-width:420px">
  <thead><tr>
    {sortable_th("DATE_OPENED", "date")}
    {sortable_th("N entries", "num")}
  </tr></thead>
  <tbody>
    {''.join(top_rows)}
  </tbody>
</table>
</div>
</section>

{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    OUT_HTML.write_text(page, encoding="utf-8")

    # refresh json
    summary = {
        "source": gold["path"],
        "stamp": "260807141317",
        "latestrun_source": latest["path"],
        "latestrun_max_n": latest["max_n"],
        "latestrun_n_gt_12": latest["n_gt_12"],
        "baseline": gold["base"],
        "max_same_day_n": gold["max_n"],
        "n_days_gt_12": gold["n_gt_12"],
        "n_days_ge": {str(k): v for k, v in gold["n_ge"].items()},
        "n_hist": gold["n_hist"],
        "top_counts": gold["top_counts"],
        "day_stats": [
            {
                **{k: v for k, v in a.items() if k not in ("symbols", "date")},
                "symbols": a["symbols"],
            }
            for a in day_stats
        ],
        "pools": gold["pools"],
        "today_compare": {
            "today": payload["today_date"],
            "winner": payload.get("winner") or payload.get("closer"),
            "runner_up": payload.get("runner_up"),
            "winner_score": payload.get("winner_score"),
            "runner_score": payload.get("runner_score"),
            "closer": payload["closer"],
            "score_apr": payload.get("score_apr"),
            "score_jan": payload.get("score_jan"),
            "would_buy_n": payload["would_buy_n"],
            "ranked": [
                {"rank": c["rank"], "date": c["date"], "score": c["score"], "why": c["why"]}
                for c in (payload.get("comparisons") or [])
            ],
        },
    }
    OUT_JSON.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")


def write_compare_html(payload, gold):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    r = payload["regimes"]
    c = payload["chars"]
    b = payload.get("breadth") or {}
    comps = payload.get("comparisons") or []
    hist_dates = payload.get("hist_dates") or [x["date"] for x in comps]
    winner = payload.get("winner") or (comps[0]["date"] if comps else "?")
    runner = payload.get("runner_up")
    wscore = payload.get("winner_score")
    rscore = payload.get("runner_score")
    # Column order: Today + ranked hist dates (winner first among hist)
    col_labels = ["today"] + hist_dates
    # Prefer ranked order for secondary tables' emphasis but keep N-desc for wide tables
    ranked_dates = [x["date"] for x in comps]

    def fmt_cell(v, fmt="pct"):
        if isinstance(v, bool):
            return "Yes" if v else "No"
        if v is None:
            return "—"
        if fmt == "pct":
            return f"{v:+.2f}%"
        if fmt == "num":
            return f"{v:.2f}"
        return str(v)

    def reg_row(metric, key, fmt="pct"):
        cells = [fmt_cell((r.get(lab) or {}).get(key), fmt) for lab in col_labels]
        return (
            f"<tr><td>{html.escape(metric)}</td>"
            + "".join(f"<td>{x}</td>" for x in cells)
            + "</tr>"
        )

    def char_row(metric, key, fmt="num"):
        cells = []
        for lab in col_labels:
            ch = c.get(lab) or {}
            cells.append(fmt_cell(ch.get(key), fmt))
        return (
            f"<tr><td>{html.escape(metric)}</td>"
            + "".join(f"<td>{x}</td>" for x in cells)
            + "</tr>"
        )

    breadth_rows = ""
    if b:
        for metric, key in [
            ("% RS univ. > SMA20", "pct_above_sma20"),
            ("% RS univ. > SMA50", "pct_above_sma50"),
            ("% RS univ. > SMA200", "pct_above_sma200"),
            ("Universe N", "n"),
        ]:
            cells = []
            for lab in col_labels:
                v = (b.get(lab) or {}).get(key)
                if v is None:
                    cells.append("—")
                elif key == "n":
                    cells.append(str(int(v)))
                else:
                    cells.append(f"{v:.1f}%")
            breadth_rows += (
                f"<tr><td>{html.escape(metric)}</td>"
                + "".join(f"<td>{x}</td>" for x in cells)
                + "</tr>"
            )

    col_headers = sortable_th("Today", "text") + "".join(
        sortable_th(d, "text") for d in hist_dates
    )

    rank_rows = []
    for cmp in comps:
        oc = cmp.get("outcomes") or {}
        mark = ""
        if cmp["date"] == winner:
            mark = " ★ winner"
        elif runner and cmp["date"] == runner:
            mark = " · runner-up"
        rank_rows.append(
            "<tr>"
            f"<td>{cmp['rank']}</td>"
            f"<td>{html.escape(cmp['date'])}{html.escape(mark)}</td>"
            f"<td>{cmp['n_hist']}</td>"
            f"<td>{cmp['score']:.2f}</td>"
            f"<td>{cmp['overlap_n']}/{payload['would_buy_n']}</td>"
            f"<td>{html.escape(', '.join(cmp['overlap']) or '—')}</td>"
            f"<td>{oc.get('wr', 0):.1f}%</td>"
            f"<td class='{cls_for(oc.get('avg_pnl', 0))}'>{oc.get('avg_pnl', 0):+.2f}%</td>"
            f"<td>{html.escape(cmp.get('why') or '')}</td>"
            "</tr>"
        )

    def sym_table(label, stats, sectors, industries, outcomes=None):
        rows = []
        for s in stats:
            rows.append(
                "<tr>"
                f"<td>{html.escape(s['symbol'])}</td>"
                f"<td>{s['consec_down']}</td>"
                f"<td>{fmt_opt(s['pct_off_20d_high'])}</td>"
                f"<td>{fmt_opt(s['pct_off_52w_high'])}</td>"
                f"<td>{fmt_opt(s['vs_sma20'])}</td>"
                f"<td>{fmt_opt(s['vs_sma50'])}</td>"
                f"<td>{fmt_opt(s['ret_5d'])}</td>"
                "</tr>"
            )
        sec = ", ".join(f"{k}×{v}" for k, v in sorted(sectors.items(), key=lambda x: -x[1]))
        ind = ", ".join(f"{k}×{v}" for k, v in sorted(industries.items(), key=lambda x: -x[1])[:8])
        out_note = ""
        if outcomes:
            out_note = (
                f" Realized cluster: WR {outcomes['wr']:.1f}%, "
                f"avg PNL% {outcomes['avg_pnl']:+.2f}%."
            )
        return f"""
<section>
<h2>{html.escape(label)}</h2>
<div class="def">Sectors: {html.escape(sec)}. Top industries: {html.escape(ind)}.{out_note}</div>
<p class="small">Click column headers to sort. Pre-buy stats use bars through prior close before as-of/entry.</p>
<div class="table-wrap">
<table class="sortable">
<thead><tr>
{sortable_th("Symbol", "text")}
{sortable_th("Consec down", "num")}
{sortable_th("% off 20d high", "num")}
{sortable_th("% off 52w high", "num")}
{sortable_th("vs SMA20", "num")}
{sortable_th("vs SMA50", "num")}
{sortable_th("5d ret", "num")}
</tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</div>
</section>
"""

    # Evidence bullets from winner + runner
    t = r["today"]
    w = r.get(winner) or {}
    wc = c.get(winner) or {}
    tc = c.get("today") or {}
    win_cmp = next((x for x in comps if x["date"] == winner), None)
    run_cmp = next((x for x in comps if runner and x["date"] == runner), None)
    evidence = []
    evidence.append(
        f"Would-buy pressure today is N={payload['would_buy_n']} "
        f"(peak historical same-day N on gold-65 is 12)."
    )
    if win_cmp:
        if run_cmp:
            evidence.append(
                f"Highest resemblance score is {winner} at {win_cmp['score']:.1f} "
                f"(runner-up {runner} at {run_cmp['score']:.1f})."
            )
        else:
            evidence.append(
                f"Highest resemblance score is {winner} at {win_cmp['score']:.1f}."
            )
        evidence.append(
            f"Symbol overlap with {winner}: {win_cmp['overlap_n']}/{payload['would_buy_n']} "
            f"({', '.join(win_cmp['overlap']) or 'none'})."
        )
    evidence.append(
        f"SPY structure today above SMA20/50/200 = "
        f"{t.get('spy_above_sma20')}/{t.get('spy_above_sma50')}/{t.get('spy_above_sma200')}; "
        f"{winner} = {w.get('spy_above_sma20')}/{w.get('spy_above_sma50')}/{w.get('spy_above_sma200')}."
    )
    evidence.append(
        f"Crowding fingerprint today: near-20d-high {tc.get('n_near_20d_high')}/{tc.get('n')}, "
        f"median %off 20d {fmt_opt(tc.get('median_off_20d'))}, "
        f"median vs SMA50 {fmt_opt(tc.get('median_vs_sma50'))} — "
        f"vs {winner}: near-20d {wc.get('n_near_20d_high')}/{wc.get('n')}, "
        f"%off20d {fmt_opt(wc.get('median_off_20d'))}, "
        f"vsSMA50 {fmt_opt(wc.get('median_vs_sma50'))}."
    )
    if b and b.get("today") and b.get(winner):
        evidence.append(
            f"RS-universe breadth (% > SMA50): today {b['today']['pct_above_sma50']:.1f}% "
            f"vs {winner} {b[winner]['pct_above_sma50']:.1f}%."
        )

    why_win = (win_cmp or {}).get("why") or ""
    nuance = (
        f" Across all {len(comps)} gold-65 N≥8 dates, {winner} wins on the blended "
        f"regime + RS-cluster-character + symbol-overlap score"
        + (f"; {runner} is closest alternative." if runner else ".")
    )

    # Character summary table (today + ranked)
    char_sum_rows = []
    for lab in ["today"] + ranked_dates:
        ch = c.get(lab) or {}
        ov = "—"
        if lab != "today":
            cmp = next((x for x in comps if x["date"] == lab), None)
            ov = f"{cmp['overlap_n']}" if cmp else "—"
        oc = (payload.get("outcomes") or {}).get(lab) or {}
        wr_s = f"{oc['wr']:.1f}%" if oc else "— (would-buy)"
        avg_s = f"{oc['avg_pnl']:+.2f}%" if oc else "—"
        mark = ""
        if lab == winner:
            mark = " ★"
        elif lab == runner:
            mark = " ·"
        char_sum_rows.append(
            "<tr>"
            f"<td>{html.escape(lab)}{html.escape(mark)}</td>"
            f"<td>{ch.get('n', '—')}</td>"
            f"<td>{ov}</td>"
            f"<td>{fmt_opt(ch.get('median_off_20d'))}</td>"
            f"<td>{fmt_opt(ch.get('median_vs_sma50'))}</td>"
            f"<td>{ch.get('n_near_20d_high', '—')}</td>"
            f"<td>{fmt_opt(ch.get('median_consec_down'), digits=1, suffix='')}</td>"
            f"<td>{wr_s}</td>"
            f"<td>{avg_s}</td>"
            "</tr>"
        )

    # Compact regime for today + top-3 only (readable)
    top3 = ranked_dates[:3]
    top_cols = ["today"] + top3
    top_headers = sortable_th("Metric", "text") + "".join(sortable_th(x, "text") for x in top_cols)

    def reg_row_top(metric, key, fmt="pct"):
        cells = [fmt_cell((r.get(lab) or {}).get(key), fmt) for lab in top_cols]
        return (
            f"<tr><td>{html.escape(metric)}</td>"
            + "".join(f"<td>{x}</td>" for x in cells)
            + "</tr>"
        )

    breadth_top = ""
    if b:
        for metric, key in [
            ("% RS univ. > SMA50", "pct_above_sma50"),
            ("% RS univ. > SMA200", "pct_above_sma200"),
        ]:
            cells = []
            for lab in top_cols:
                v = (b.get(lab) or {}).get(key)
                cells.append("—" if v is None else (str(int(v)) if key == "n" else f"{v:.1f}%"))
            breadth_top += (
                f"<tr><td>{html.escape(metric)}</td>"
                + "".join(f"<td>{x}</td>" for x in cells)
                + "</tr>"
            )

    # Full-width regime table headers
    full_headers = sortable_th("Metric", "text") + col_headers

    # Per-date symbol tables: today + winner + runner + others collapsed as sections
    sym_sections = [
        sym_table(
            f"Today would-buy list ({payload['today_date']})",
            payload["char_stats"]["today"],
            c["today"].get("sectors") or {},
            c["today"].get("industries") or {},
        )
    ]
    for d in ranked_dates:
        tag = ""
        if d == winner:
            tag = " — WINNER"
        elif d == runner:
            tag = " — runner-up"
        oc = (payload.get("outcomes") or {}).get(d)
        sym_sections.append(
            sym_table(
                f"{d} RS entries (N={(c.get(d) or {}).get('n', '?')}{tag})",
                payload["char_stats"].get(d) or [],
                (c.get(d) or {}).get("sectors") or {},
                (c.get(d) or {}).get("industries") or {},
                oc,
            )
        )

    vix_note = (
        "available " + html.escape(str(payload.get("vix")))
        if any((payload.get("vix") or {}).values())
        else "not found in local CSV/DuckDB under common names — omitted."
    )

    page = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>RS Same-Day Clusters — Today vs all N≥8 dates</title>
<style>
body {{ font-family: system-ui, sans-serif; margin:24px; color:#0f172a; max-width:1600px; }}
h1 {{ font-size:1.5rem; margin-bottom:4px; }}
h2 {{ font-size:1.15rem; margin-top:28px; }}
.sub {{ color:#64748b; margin-bottom:20px; line-height:1.5; font-size:0.95rem; }}
.small {{ font-size:12px; color:#64748b; }}
.pos {{ color:#16a34a; }} .neg {{ color:#dc2626; }}
.table-wrap {{ overflow-x:auto; margin:8px 0; }}
table {{ border-collapse:collapse; font-size:12px; width:100%; }}
th, td {{ border:1px solid #e2e8f0; padding:7px 8px; text-align:left; vertical-align:top; }}
th {{ background:#f1f5f9; }}
th.sortable-th {{ cursor:pointer; user-select:none; white-space:nowrap; }}
th.sortable-th:hover {{ background:#e2e8f0; }}
.sort-ind {{ display:inline-block; width:0.9em; margin-left:4px; color:#94a3b8; font-size:10px; }}
th.sort-asc .sort-ind::after {{ content:"▲"; color:#334155; }}
th.sort-desc .sort-ind::after {{ content:"▼"; color:#334155; }}
code {{ font-size:11px; background:#f1f5f9; padding:1px 4px; border-radius:3px; }}
.def {{ background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px 14px; margin:12px 0 20px; font-size:0.92rem; line-height:1.5; }}
.verdict {{ font-size:1.05rem; margin:12px 0 8px; }}
ul {{ line-height:1.55; }}
a {{ color:#0369a1; }}
</style></head><body>
<h1>Today vs all gold-65 N≥8 RS same-day clusters</h1>
<p class="sub">
  Today = <code>{html.escape(payload['today_date'])}</code> (latest available session / RS watchlist as-of;
  SPY last bar <code>{html.escape(payload['spy_last'])}</code>).
  Compared against every Relative Strength (RS) gold-65 Closed day with N≥8 same-day entries
  ({len(hist_dates)} dates). Generated {now}. Parent:
  <a href="RS_SameDay_Entry_Clusters.html">RS_SameDay_Entry_Clusters.html</a>.
</p>

<div class="def verdict">
  <strong>Verdict: most resembles {html.escape(str(winner))}
  (score {wscore:.1f})</strong>
  {f' — runner-up <strong>{html.escape(str(runner))}</strong> ({rscore:.1f}).' if runner and rscore is not None else '.'}
  {html.escape(nuance)}
  One-line: {html.escape(why_win)}.
</div>

<div class="def">
  <strong>Evidence:</strong>
  <ul>
    {''.join(f'<li>{html.escape(e)}</li>' for e in evidence)}
  </ul>
</div>

<section>
<h2>Ranked resemblance (all N≥8 dates)</h2>
<p class="small">Click column headers to sort. Score blends SPY/QQQ returns &amp; vol, distance to MAs,
RS would-buy crowding (near 20d highs, vs SMA50), symbol overlap, tech-share, and breadth.</p>
<div class="table-wrap">
<table class="sortable">
<thead><tr>
{sortable_th("Rank", "num")}
{sortable_th("Date", "date")}
{sortable_th("Hist N", "num")}
{sortable_th("Resemblance score", "num")}
{sortable_th("Overlap", "text")}
{sortable_th("Overlap symbols", "text")}
{sortable_th("Hist WR", "num")}
{sortable_th("Hist avg PNL%", "num")}
{sortable_th("Why (one line)", "text")}
</tr></thead>
<tbody>
{''.join(rank_rows)}
</tbody>
</table>
</div>
</section>

<section>
<h2>Cluster character snapshot (today + ranked)</h2>
<p class="small">Click column headers to sort.</p>
<div class="table-wrap">
<table class="sortable">
<thead><tr>
{sortable_th("Date", "date")}
{sortable_th("N", "num")}
{sortable_th("Overlap w/ today", "num")}
{sortable_th("Med % off 20d", "num")}
{sortable_th("Med vs SMA50", "num")}
{sortable_th("# near 20d high", "num")}
{sortable_th("Med consec down", "num")}
{sortable_th("Hist WR", "num")}
{sortable_th("Hist avg PNL%", "num")}
</tr></thead>
<tbody>
{''.join(char_sum_rows)}
</tbody>
</table>
</div>
</section>

<section>
<h2>Market regime — today vs top-3 resemblance</h2>
<p class="small">Click column headers to sort. Full 8-date regime table below.</p>
<div class="table-wrap">
<table class="sortable">
<thead><tr>
{top_headers}
</tr></thead>
<tbody>
{reg_row_top("As-of bar", "as_of", "str")}
{reg_row_top("SPY 1d %", "spy_1d")}
{reg_row_top("SPY 5d %", "spy_5d")}
{reg_row_top("SPY 20d %", "spy_20d")}
{reg_row_top("QQQ 5d %", "qqq_5d")}
{reg_row_top("QQQ 20d %", "qqq_20d")}
{reg_row_top("SPY vs SMA20", "spy_vs_sma20")}
{reg_row_top("SPY vs SMA50", "spy_vs_sma50")}
{reg_row_top("SPY vs SMA200", "spy_vs_sma200")}
{reg_row_top("QQQ vs SMA50", "qqq_vs_sma50")}
{reg_row_top("SPY RV20 (ann%)", "spy_rv20", "num")}
{reg_row_top("QQQ RV20 (ann%)", "qqq_rv20", "num")}
{reg_row_top("SPY > SMA20", "spy_above_sma20", "str")}
{reg_row_top("SPY > SMA50", "spy_above_sma50", "str")}
{reg_row_top("SPY > SMA200", "spy_above_sma200", "str")}
{breadth_top}
</tbody>
</table>
</div>
</section>

<section>
<h2>Market regime — today vs all N≥8 dates</h2>
<p class="small">Click column headers to sort. Columns: Today then hist dates by N desc.</p>
<div class="table-wrap">
<table class="sortable">
<thead><tr>
{full_headers}
</tr></thead>
<tbody>
{reg_row("As-of bar", "as_of", "str")}
{reg_row("SPY 1d %", "spy_1d")}
{reg_row("SPY 5d %", "spy_5d")}
{reg_row("SPY 20d %", "spy_20d")}
{reg_row("QQQ 1d %", "qqq_1d")}
{reg_row("QQQ 5d %", "qqq_5d")}
{reg_row("QQQ 20d %", "qqq_20d")}
{reg_row("SPY vs SMA20", "spy_vs_sma20")}
{reg_row("SPY vs SMA50", "spy_vs_sma50")}
{reg_row("SPY vs SMA200", "spy_vs_sma200")}
{reg_row("QQQ vs SMA20", "qqq_vs_sma20")}
{reg_row("QQQ vs SMA50", "qqq_vs_sma50")}
{reg_row("QQQ vs SMA200", "qqq_vs_sma200")}
{reg_row("SPY RV20 (ann%)", "spy_rv20", "num")}
{reg_row("QQQ RV20 (ann%)", "qqq_rv20", "num")}
{reg_row("SPY > SMA20", "spy_above_sma20", "str")}
{reg_row("SPY > SMA50", "spy_above_sma50", "str")}
{reg_row("SPY > SMA200", "spy_above_sma200", "str")}
{breadth_rows}
</tbody>
</table>
</div>
</section>

{''.join(sym_sections)}

<section>
<h2>Notes / data gaps</h2>
<ul class="small">
<li>VIX: {vix_note}</li>
<li>Max same-day Closed N remains 12 (no N&gt;12 on gold or LatestRun). See clusters page for all N≥8 days.</li>
<li>Similarity score is a transparent hand-weighted blend of MA structure, return/vol distance, cluster extension stats, symbol overlap, tech-share, and breadth — not a trained model.</li>
</ul>
</section>

{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    OUT_COMPARE.write_text(page, encoding="utf-8")


if __name__ == "__main__":
    main()
