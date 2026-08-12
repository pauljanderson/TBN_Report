#!/usr/bin/env python3
"""RS pre-buy tape stats: down-days and drop-from-high vs outcomes.

Hypothesis framing only — no production changes.

Reads gold-65 Closed (prefer 260807141317), joins DuckDB OHLC before DATE_OPENED,
publishes sortable HTML under drive/paul_experiments/.

Usage:
  python tools/rs_prebuy_down_days_drop_from_high.py
"""
from __future__ import annotations

import html as html_mod
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
OUT_DIR = DRIVE / "paul_experiments"
CLOSED_PATH = DRIVE / "RS_Closed_260807141317.csv"
DB_PATH = ROOT / "data" / "ohlcv.duckdb"
UNIVERSE_PATH = DRIVE / "universes" / "RS_universe.csv"
WATCHLIST_PATH = DRIVE / "RS_LatestRun_Watchlist.csv"
OPEN_PATH = DRIVE / "RS_LatestRun_Open.csv"

LOOKBACK_NS = list(range(1, 11))
HIGH_WINDOWS = (20, 52, 252)
DROP_THRESH = 0.10  # 10% off high
FORWARD_HORIZONS = (5, 10, 20)

SORTABLE_TH_CSS = """
th.sortable-th{cursor:pointer;user-select:none;white-space:nowrap}
th.sortable-th:hover{background:#e2e8f0}
th.sortable-th .sort-ind{opacity:.45;margin-left:.25em;font-size:.85em}
th.sortable-th.sort-asc .sort-ind::after{content:"▲";opacity:1}
th.sortable-th.sort-desc .sort-ind::after{content:"▼";opacity:1}
"""

SORTABLE_TABLE_SCRIPT = """
<script>
(function(){
  function parseCell(td, type){
    var t=(td.textContent||"").trim().replace(/[$,%]/g,"").replace(/,/g,"");
    if(type==="num"){var n=parseFloat(t); return isNaN(n)?null:n;}
    if(type==="date"||type==="month"){return t;}
    return t.toLowerCase();
  }
  function bind(table){
    var ths=table.querySelectorAll("th.sortable-th");
    ths.forEach(function(th, colIdx){
      th.addEventListener("click", function(){
        var type=th.getAttribute("data-sort")||"text";
        var asc=!th.classList.contains("sort-asc");
        ths.forEach(function(x){
          x.classList.remove("sort-asc","sort-desc");
          x.setAttribute("aria-sort","none");
        });
        th.classList.add(asc?"sort-asc":"sort-desc");
        th.setAttribute("aria-sort", asc?"ascending":"descending");
        var tbody=table.tBodies[0]; if(!tbody) return;
        var rows=[].slice.call(tbody.querySelectorAll("tr")).filter(function(r){
          return !r.classList.contains("total-row");
        });
        rows.sort(function(a,b){
          var av=parseCell(a.children[colIdx], type), bv=parseCell(b.children[colIdx], type);
          if(av==null&&bv==null) return 0;
          if(av==null) return 1; if(bv==null) return -1;
          if(av<bv) return asc?-1:1; if(av>bv) return asc?1:-1; return 0;
        });
        rows.forEach(function(r){tbody.appendChild(r);});
      });
      th.addEventListener("keydown", function(e){
        if(e.key==="Enter"||e.key===" "){e.preventDefault(); th.click();}
      });
    });
  }
  document.querySelectorAll("table.sortable").forEach(bind);
})();
</script>
"""


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{html_mod.escape(sort_type)}" '
        f'tabindex="0" role="columnheader" aria-sort="none">'
        f"{html_mod.escape(label)}<span class=\"sort-ind\"></span></th>"
    )


def parse_pnl_pct(s) -> float:
    if pd.isna(s):
        return float("nan")
    if isinstance(s, (int, float)):
        return float(s)
    t = str(s).strip().replace("%", "").replace(",", "")
    try:
        return float(t)
    except ValueError:
        return float("nan")


def parse_yyyymmdd(v) -> date:
    s = str(int(v)) if not isinstance(v, str) else str(v).strip()
    if "-" in s:
        return date.fromisoformat(s[:10])
    s = s.replace("/", "")[:8]
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def load_closed(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["SYMBOL"] = df["SYMBOL"].astype(str).str.upper().str.strip()
    df["DATE_OPENED_DT"] = df["DATE_OPENED"].map(parse_yyyymmdd)
    df["PNL_PCT_NUM"] = df["PNL_PCT"].map(parse_pnl_pct)
    df["WIN"] = df["PNL_PCT_NUM"] > 0
    df["DAYS_HELD"] = pd.to_numeric(df["DAYS_HELD"], errors="coerce")
    return df


def load_prices(symbols: list[str]) -> pd.DataFrame:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        syms = sorted({s.upper() for s in symbols})
        q = """
        SELECT UPPER(symbol) AS symbol, CAST(date AS DATE) AS date,
               open, high, low, close, volume
        FROM prices
        WHERE UPPER(symbol) IN (SELECT * FROM UNNEST(?))
        ORDER BY symbol, date
        """
        return con.execute(q, [syms]).fetchdf()
    finally:
        con.close()


def features_before_entry(px: pd.DataFrame, entry_dt: date) -> dict:
    """OHLC strictly before entry date (no look-ahead into entry session)."""
    hist = px[px["date"] < entry_dt].copy()
    out = {
        "ohlc_ok": False,
        "bars_before": 0,
        "prior_close": np.nan,
        "consec_down_closes": np.nan,
        "down_days_last_1": np.nan,
        "down_days_last_2": np.nan,
        "down_days_last_3": np.nan,
        "down_days_last_4": np.nan,
        "down_days_last_5": np.nan,
        "down_days_last_6": np.nan,
        "down_days_last_7": np.nan,
        "down_days_last_8": np.nan,
        "down_days_last_9": np.nan,
        "down_days_last_10": np.nan,
        "pct_off_high_20d": np.nan,
        "pct_off_high_52d": np.nan,
        "pct_off_high_252d": np.nan,
        "off_high_10pct_20d": False,
        "off_high_10pct_52d": False,
        "off_high_10pct_252d": False,
        "off_high_10pct_any": False,
        "days_since_20d_high": np.nan,
        "days_since_52d_high": np.nan,
    }
    if len(hist) < 2:
        return out

    closes = hist["close"].astype(float).values
    highs = hist["high"].astype(float).values
    n = len(closes)
    out["ohlc_ok"] = True
    out["bars_before"] = n
    out["prior_close"] = float(closes[-1])

    # Consecutive down closes ending at bar immediately before entry
    consec = 0
    for i in range(n - 1, 0, -1):
        if closes[i] < closes[i - 1]:
            consec += 1
        else:
            break
    out["consec_down_closes"] = consec

    # Down-day counts in last N sessions (close < prior close)
    down = np.zeros(n, dtype=bool)
    down[1:] = closes[1:] < closes[:-1]
    for N in LOOKBACK_NS:
        window = down[max(1, n - N) : n]
        out[f"down_days_last_{N}"] = int(window.sum()) if len(window) else 0

    prior = float(closes[-1])
    for w in HIGH_WINDOWS:
        seg_h = highs[max(0, n - w) : n]
        if len(seg_h) == 0 or prior <= 0:
            continue
        hi = float(np.nanmax(seg_h))
        if hi <= 0:
            continue
        pct_off = (hi - prior) / hi
        out[f"pct_off_high_{w}d"] = pct_off * 100.0
        flag = pct_off >= DROP_THRESH
        out[f"off_high_10pct_{w}d"] = bool(flag)
        # days since that window high (0 = yesterday was the high)
        idx_hi = int(np.nanargmax(seg_h))
        abs_idx = max(0, n - w) + idx_hi
        out[f"days_since_{w}d_high"] = int(n - 1 - abs_idx)

    out["off_high_10pct_any"] = bool(
        out["off_high_10pct_20d"] or out["off_high_10pct_52d"] or out["off_high_10pct_252d"]
    )
    return out


def features_asof_latest(px: pd.DataFrame) -> tuple[date | None, dict]:
    """Tape features as of latest available close (forced-buy / signal context)."""
    if px.empty:
        return None, features_before_entry(px, date(2099, 1, 1))
    last = px["date"].max()
    # Treat "buy next session after last close" → features use bars through last close
    # by using entry_dt = day after last (so last close is included as prior).
    if isinstance(last, pd.Timestamp):
        last_d = last.date()
    else:
        last_d = last
    from datetime import timedelta

    fake_entry = last_d + timedelta(days=1)
    return last_d, features_before_entry(px, fake_entry)


def enrich_trades(closed: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    by_sym = {s: g.reset_index(drop=True) for s, g in prices.groupby("symbol")}
    rows = []
    for r in closed.itertuples(index=False):
        sym = r.SYMBOL
        px = by_sym.get(sym)
        feats = features_before_entry(px if px is not None else pd.DataFrame(), r.DATE_OPENED_DT)
        rows.append(
            {
                "SYMBOL": sym,
                "DATE_OPENED": r.DATE_OPENED,
                "DATE_OPENED_DT": r.DATE_OPENED_DT,
                "ENTRY_PRICE": r.ENTRY_PRICE,
                "PNL_PCT": r.PNL_PCT_NUM,
                "WIN": bool(r.WIN),
                "DAYS_HELD": r.DAYS_HELD,
                "EXIT_TYPE": getattr(r, "EXIT_TYPE", ""),
                **feats,
            }
        )
    return pd.DataFrame(rows)


def baseline_stats(df: pd.DataFrame) -> dict:
    ok = df[df["ohlc_ok"]].copy()
    return {
        "n": int(len(ok)),
        "wr": float(ok["WIN"].mean()) if len(ok) else float("nan"),
        "avg_pnl": float(ok["PNL_PCT"].mean()) if len(ok) else float("nan"),
        "avg_days": float(ok["DAYS_HELD"].mean()) if len(ok) else float("nan"),
        "med_pnl": float(ok["PNL_PCT"].median()) if len(ok) else float("nan"),
    }


def bucket_table(
    df: pd.DataFrame,
    key: str,
    baseline: dict,
    *,
    min_n: int = 1,
) -> pd.DataFrame:
    ok = df[df["ohlc_ok"] & df[key].notna()].copy()
    rows = []
    for val, g in ok.groupby(key, dropna=False):
        n = len(g)
        if n < min_n:
            continue
        wr = float(g["WIN"].mean())
        avg_pnl = float(g["PNL_PCT"].mean())
        avg_days = float(g["DAYS_HELD"].mean())
        rows.append(
            {
                "bucket": val,
                "n": n,
                "win_rate": wr,
                "wr_lift_pp": (wr - baseline["wr"]) * 100.0,
                "avg_pnl_pct": avg_pnl,
                "pnl_lift_pp": avg_pnl - baseline["avg_pnl"],
                "avg_days_held": avg_days,
                "days_lift": avg_days - baseline["avg_days"],
                "med_pnl_pct": float(g["PNL_PCT"].median()),
            }
        )
    out = pd.DataFrame(rows)
    if len(out):
        out = out.sort_values("bucket")
    return out


def forward_up_rate(
    prices_by_sym: dict[str, pd.DataFrame],
    trades: pd.DataFrame,
    mask: pd.Series,
    horizons: tuple[int, ...] = FORWARD_HORIZONS,
) -> dict[int, dict]:
    """P(close after H sessions > entry prior close) for matching trades."""
    sub = trades[mask & trades["ohlc_ok"]].copy()
    out: dict[int, dict] = {}
    for H in horizons:
        ups = []
        for r in sub.itertuples(index=False):
            px = prices_by_sym.get(r.SYMBOL)
            if px is None or len(px) == 0:
                continue
            # entry session = first bar on/after DATE_OPENED
            after = px[px["date"] >= r.DATE_OPENED_DT]
            if len(after) <= H:
                continue
            entry_px = float(after.iloc[0]["open"])
            fut = float(after.iloc[H]["close"])
            ups.append(fut > entry_px)
        arr = np.array(ups, dtype=bool) if ups else np.array([], dtype=bool)
        out[H] = {
            "n": int(len(arr)),
            "p_up": float(arr.mean()) if len(arr) else float("nan"),
        }
    return out


def fmt_pct(x, digits=1) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "-"
    return f"{x:.{digits}f}%"


def fmt_num(x, digits=2) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "-"
    return f"{x:.{digits}f}"


def fmt_pp(x, digits=1) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "-"
    sign = "+" if x >= 0 else ""
    return f"{sign}{x:.{digits}f}pp"


def df_to_html_table(df: pd.DataFrame, col_meta: list[tuple[str, str, str]], caption: str = "") -> str:
    """col_meta: (col, label, sort_type)"""
    thead = "".join(sortable_th(lab, st) for _, lab, st in col_meta)
    body = []
    for _, r in df.iterrows():
        tds = []
        for col, _, st in col_meta:
            v = r[col]
            if st == "num":
                if col in ("win_rate",) or "rate" in col or col.endswith("_pct") and "lift" not in col:
                    if col == "win_rate" or col.startswith("p_up") or col.endswith("_rate"):
                        cell = fmt_pct(float(v) * 100.0 if abs(float(v)) <= 1.5 else float(v), 1)
                    elif "pct" in col:
                        cell = fmt_pct(float(v), 1)
                    else:
                        cell = fmt_num(v, 2)
                elif "lift_pp" in col or col.endswith("_lift_pp"):
                    cell = fmt_pp(float(v), 1)
                elif col in ("n", "bucket") or col.endswith("_n"):
                    cell = str(int(v)) if pd.notna(v) else "—"
                else:
                    cell = fmt_num(v, 2) if isinstance(v, float) else str(v)
            else:
                cell = "—" if pd.isna(v) else str(v)
            tds.append(f"<td>{html_mod.escape(cell)}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    cap = f"<caption>{html_mod.escape(caption)}</caption>" if caption else ""
    return (
        f'<table class="sortable">{cap}<thead><tr>{thead}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table>'
    )


def yes_no_lift(lift_pp: float, n: int, *, min_n: int = 30, thresh_pp: float = 2.0) -> str:
    if n < min_n or not np.isfinite(lift_pp):
        return "INCONCLUSIVE (thin / noisy)"
    if lift_pp >= thresh_pp:
        return "YES - positive lift vs baseline"
    if lift_pp <= -thresh_pp:
        return "YES - negative lift vs baseline"
    return "NO material lift (|dWR| < 2pp)"


def match_bucket_wr(bucket_df: pd.DataFrame, value) -> tuple[float, int, float]:
    """Return (wr, n, wr_lift_pp) for exact bucket match."""
    if bucket_df.empty:
        return float("nan"), 0, float("nan")
    hit = bucket_df[bucket_df["bucket"] == value]
    if hit.empty:
        # try numeric equality
        try:
            hit = bucket_df[np.isclose(bucket_df["bucket"].astype(float), float(value))]
        except Exception:
            hit = hit
    if hit.empty:
        return float("nan"), 0, float("nan")
    r = hit.iloc[0]
    return float(r["win_rate"]), int(r["n"]), float(r["wr_lift_pp"])


def nearest_drop_bucket(pct_off: float) -> str:
    if not np.isfinite(pct_off):
        return "unknown"
    if pct_off < 5:
        return "<5% off"
    if pct_off < 10:
        return "5-10% off"
    if pct_off < 15:
        return "10-15% off"
    if pct_off < 20:
        return "15-20% off"
    return ">=20% off"


def build_drop_bins(df: pd.DataFrame, col: str, baseline: dict) -> pd.DataFrame:
    ok = df[df["ohlc_ok"] & df[col].notna()].copy()

    def lab(x):
        return nearest_drop_bucket(float(x))

    ok["bucket"] = ok[col].map(lab)
    order = ["<5% off", "5-10% off", "10-15% off", "15-20% off", ">=20% off"]
    rows = []
    for b in order:
        g = ok[ok["bucket"] == b]
        if len(g) == 0:
            continue
        wr = float(g["WIN"].mean())
        rows.append(
            {
                "bucket": b,
                "n": len(g),
                "win_rate": wr,
                "wr_lift_pp": (wr - baseline["wr"]) * 100.0,
                "avg_pnl_pct": float(g["PNL_PCT"].mean()),
                "pnl_lift_pp": float(g["PNL_PCT"].mean()) - baseline["avg_pnl"],
                "avg_days_held": float(g["DAYS_HELD"].mean()),
                "days_lift": float(g["DAYS_HELD"].mean()) - baseline["avg_days"],
                "med_pnl_pct": float(g["PNL_PCT"].median()),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    closed = load_closed(CLOSED_PATH)
    source_label = f"gold-65 Closed `{CLOSED_PATH.name}` (stamp 260807141317; n={len(closed)})"

    TODAY_NAMES = (
        "ANET",
        "ENVA",
        "MTSI",
        "LITE",
        "DCO",
        "BELFA",
        "TER",
        "JBL",
        "CCJ",
        "FTAI",
        "TSM",
    )
    symbols = sorted(closed["SYMBOL"].unique().tolist())
    for extra in TODAY_NAMES:
        if extra not in symbols:
            symbols.append(extra)

    prices = load_prices(symbols)
    prices["date"] = pd.to_datetime(prices["date"]).dt.date
    by_sym = {s: g.reset_index(drop=True) for s, g in prices.groupby("symbol")}

    trades = enrich_trades(closed, prices)
    baseline = baseline_stats(trades)

    # --- bucket tables ---
    consec_tbl = bucket_table(trades, "consec_down_closes", baseline)
    down5_tbl = bucket_table(trades, "down_days_last_5", baseline)
    down10_tbl = bucket_table(trades, "down_days_last_10", baseline)

    # boolean 10% off high
    bool_rows = []
    for key, label in [
        ("off_high_10pct_20d", ">=10% off 20d high"),
        ("off_high_10pct_52d", ">=10% off 52d high"),
        ("off_high_10pct_252d", ">=10% off 252d high"),
        ("off_high_10pct_any", ">=10% off any (20/52/252)"),
    ]:
        for flag, g in trades[trades["ohlc_ok"]].groupby(key):
            wr = float(g["WIN"].mean())
            bool_rows.append(
                {
                    "feature": label,
                    "bucket": "YES" if flag else "NO",
                    "n": len(g),
                    "win_rate": wr,
                    "wr_lift_pp": (wr - baseline["wr"]) * 100.0,
                    "avg_pnl_pct": float(g["PNL_PCT"].mean()),
                    "pnl_lift_pp": float(g["PNL_PCT"].mean()) - baseline["avg_pnl"],
                    "avg_days_held": float(g["DAYS_HELD"].mean()),
                    "med_pnl_pct": float(g["PNL_PCT"].median()),
                }
            )
    bool_tbl = pd.DataFrame(bool_rows)

    drop20_bins = build_drop_bins(trades, "pct_off_high_20d", baseline)
    drop52_bins = build_drop_bins(trades, "pct_off_high_52d", baseline)
    drop252_bins = build_drop_bins(trades, "pct_off_high_252d", baseline)

    # Correlation-ish summaries (point-biserial / Spearman on ok rows)
    ok = trades[trades["ohlc_ok"]].copy()
    corr_rows = []
    for col, label in [
        ("consec_down_closes", "Consecutive down closes pre-entry"),
        ("down_days_last_5", "Down days in last 5"),
        ("down_days_last_10", "Down days in last 10"),
        ("pct_off_high_20d", "% off 20d high"),
        ("pct_off_high_52d", "% off 52d high"),
        ("pct_off_high_252d", "% off 252d high"),
    ]:
        x = pd.to_numeric(ok[col], errors="coerce")
        m = x.notna() & ok["PNL_PCT"].notna()
        if m.sum() < 10:
            continue
        # Spearman vs PNL% and vs WIN
        sp_pnl = float(x[m].corr(ok.loc[m, "PNL_PCT"], method="spearman"))
        sp_win = float(x[m].corr(ok.loc[m, "WIN"].astype(float), method="spearman"))
        corr_rows.append(
            {
                "feature": label,
                "n": int(m.sum()),
                "spearman_vs_pnl": sp_pnl,
                "spearman_vs_win": sp_win,
            }
        )
    corr_tbl = pd.DataFrame(corr_rows)

    # Verdicts
    # For consec downs: compare consec>=1 vs 0, and consec>=3 vs rest
    def mask_stats(mask: pd.Series) -> dict:
        g = ok[mask]
        if len(g) == 0:
            return {"n": 0, "wr": float("nan"), "avg_pnl": float("nan"), "lift_pp": float("nan")}
        wr = float(g["WIN"].mean())
        return {
            "n": len(g),
            "wr": wr,
            "avg_pnl": float(g["PNL_PCT"].mean()),
            "lift_pp": (wr - baseline["wr"]) * 100.0,
        }

    v_down1 = mask_stats(ok["consec_down_closes"] >= 1)
    v_down3 = mask_stats(ok["consec_down_closes"] >= 3)
    v_flat = mask_stats(ok["consec_down_closes"] == 0)
    v_off20 = mask_stats(ok["off_high_10pct_20d"] == True)  # noqa: E712
    v_off52 = mask_stats(ok["off_high_10pct_52d"] == True)  # noqa: E712
    v_not_off20 = mask_stats(ok["off_high_10pct_20d"] == False)  # noqa: E712

    # --- Named names today (ANET/ENVA + follow-ups) ---
    universe = set()
    if UNIVERSE_PATH.exists():
        u = pd.read_csv(UNIVERSE_PATH)
        col = "SYMBOL" if "SYMBOL" in u.columns else u.columns[0]
        universe = set(u[col].astype(str).str.upper().str.strip())

    wl = pd.read_csv(WATCHLIST_PATH) if WATCHLIST_PATH.exists() else pd.DataFrame()
    op = pd.read_csv(OPEN_PATH) if OPEN_PATH.exists() else pd.DataFrame()
    if len(wl):
        wl["SYMBOL"] = wl["SYMBOL"].astype(str).str.upper()
    if len(op):
        op["SYMBOL"] = op["SYMBOL"].astype(str).str.upper()

    latest_session = prices["date"].max()
    name_cards = []
    for sym in TODAY_NAMES:
        px = by_sym.get(sym, pd.DataFrame())
        asof, feats = features_asof_latest(px)
        in_univ = sym in universe or sym in set(closed["SYMBOL"])
        open_hit = op[op["SYMBOL"] == sym] if len(op) else pd.DataFrame()
        wl_hit = wl[wl["SYMBOL"] == sym] if len(wl) else pd.DataFrame()
        rs_signal = False
        signal_status = "no watchlist row"
        trigger_hint = ""
        entry_date = ""
        if len(wl_hit):
            signal_status = str(wl_hit.iloc[0].get("STATUS", ""))
            trigger_hint = str(wl_hit.iloc[0].get("TRIGGER_HINT", ""))
            entry_date = str(wl_hit.iloc[0].get("ENTRY_DATE", ""))
            rs_signal = "PASSED_ALL_GATES" in signal_status

        consec = feats.get("consec_down_closes")
        wr_c, n_c, lift_c = match_bucket_wr(consec_tbl, consec)
        off20 = bool(feats.get("off_high_10pct_20d"))
        off52 = bool(feats.get("off_high_10pct_52d"))
        # combined mask for empirical likelihood
        mask_joint = (
            (trades["ohlc_ok"])
            & (trades["consec_down_closes"] == consec)
            & (trades["off_high_10pct_20d"] == off20)
        )
        mask_consec = (trades["ohlc_ok"]) & (trades["consec_down_closes"] == consec)
        # Prefer joint if powered; else consec-only as primary estimate
        if mask_joint.sum() >= 15:
            mask = mask_joint
            match_label = "consec + 20d-off flag"
        else:
            mask = mask_consec
            match_label = "consec-down only (joint thin)"
        g = trades[mask]
        emp_wr = float(g["WIN"].mean()) if len(g) else float("nan")
        emp_n = int(len(g))
        emp_pnl = float(g["PNL_PCT"].mean()) if len(g) else float("nan")
        g_joint = trades[mask_joint]
        joint_wr = float(g_joint["WIN"].mean()) if len(g_joint) else float("nan")
        joint_n = int(len(g_joint))
        joint_pnl = float(g_joint["PNL_PCT"].mean()) if len(g_joint) else float("nan")

        # broader: same drop bin + consec
        drop_bin = nearest_drop_bucket(float(feats.get("pct_off_high_20d", np.nan)))
        mask2 = (
            trades["ohlc_ok"]
            & (trades["consec_down_closes"] == consec)
            & trades["pct_off_high_20d"].map(lambda x: nearest_drop_bucket(float(x)) == drop_bin)
        )
        g2 = trades[mask2]
        emp2_wr = float(g2["WIN"].mean()) if len(g2) else float("nan")
        emp2_n = int(len(g2))

        # drop-bin alone (powered)
        mask_drop = trades["ohlc_ok"] & trades["pct_off_high_20d"].map(
            lambda x: nearest_drop_bucket(float(x)) == drop_bin
        )
        g_drop = trades[mask_drop]
        drop_wr = float(g_drop["WIN"].mean()) if len(g_drop) else float("nan")
        drop_n = int(len(g_drop))

        fwd = forward_up_rate(by_sym, trades, mask)

        last_close = float(px.iloc[-1]["close"]) if len(px) else float("nan")
        name_cards.append(
            {
                "symbol": sym,
                "asof": asof,
                "last_close": last_close,
                "in_universe": in_univ,
                "is_open": len(open_hit) > 0,
                "rs_would_buy": rs_signal,
                "signal_status": signal_status,
                "trigger_hint": trigger_hint,
                "entry_date": entry_date,
                "feats": feats,
                "drop_bin_20d": drop_bin,
                "bucket_consec_wr": wr_c,
                "bucket_consec_n": n_c,
                "bucket_consec_lift": lift_c,
                "emp_wr": emp_wr,
                "emp_n": emp_n,
                "emp_pnl": emp_pnl,
                "match_label": match_label,
                "joint_wr": joint_wr,
                "joint_n": joint_n,
                "joint_pnl": joint_pnl,
                "emp2_wr": emp2_wr,
                "emp2_n": emp2_n,
                "drop_wr": drop_wr,
                "drop_n": drop_n,
                "fwd": fwd,
                "off20": off20,
                "off52": off52,
            }
        )

    # Save trade-level CSV for audit
    trade_csv = OUT_DIR / "RS_PreBuy_DownDays_DropFromHigh_trades.csv"
    trades.to_csv(trade_csv, index=False)

    # --- HTML ---
    def meta_table(df, cols):
        return df_to_html_table(df, cols, "Click column headers to sort")

    # Normalize win_rate display handling in df_to_html_table — use explicit formatters via string cols
    def prep_wr(df: pd.DataFrame) -> pd.DataFrame:
        d = df.copy()
        if "win_rate" in d.columns:
            d["win_rate_pct"] = d["win_rate"] * 100.0
        return d

    consec_h = prep_wr(consec_tbl)
    down5_h = prep_wr(down5_tbl)
    down10_h = prep_wr(down10_tbl)
    bool_h = prep_wr(bool_tbl)
    d20_h = prep_wr(drop20_bins)
    d52_h = prep_wr(drop52_bins)
    d252_h = prep_wr(drop252_bins)

    bucket_cols = [
        ("bucket", "Bucket", "text"),
        ("n", "N", "num"),
        ("win_rate_pct", "Win rate %", "num"),
        ("wr_lift_pp", "WR lift vs base (pp)", "num"),
        ("avg_pnl_pct", "Avg PNL%", "num"),
        ("pnl_lift_pp", "PNL% lift (pp)", "num"),
        ("avg_days_held", "Avg days held", "num"),
        ("med_pnl_pct", "Med PNL%", "num"),
    ]
    bool_cols = [
        ("feature", "Feature", "text"),
        ("bucket", "Bucket", "text"),
        ("n", "N", "num"),
        ("win_rate_pct", "Win rate %", "num"),
        ("wr_lift_pp", "WR lift vs base (pp)", "num"),
        ("avg_pnl_pct", "Avg PNL%", "num"),
        ("pnl_lift_pp", "PNL% lift (pp)", "num"),
        ("avg_days_held", "Avg days held", "num"),
        ("med_pnl_pct", "Med PNL%", "num"),
    ]
    corr_cols = [
        ("feature", "Feature", "text"),
        ("n", "N", "num"),
        ("spearman_vs_pnl", "Spearman vs PNL%", "num"),
        ("spearman_vs_win", "Spearman vs win", "num"),
    ]

    # Fix df_to_html for win_rate_pct / spearman
    def simple_table(df: pd.DataFrame, col_meta: list[tuple[str, str, str]], caption: str = "") -> str:
        thead = "".join(sortable_th(lab, st) for _, lab, st in col_meta)
        body = []
        for _, r in df.iterrows():
            tds = []
            for col, _, st in col_meta:
                v = r[col]
                if pd.isna(v):
                    cell = "—"
                elif col in ("win_rate_pct", "avg_pnl_pct", "med_pnl_pct", "pct_off"):
                    cell = f"{float(v):.1f}%"
                elif col in ("wr_lift_pp", "pnl_lift_pp"):
                    cell = fmt_pp(float(v), 1)
                elif col in ("spearman_vs_pnl", "spearman_vs_win"):
                    cell = f"{float(v):+.3f}"
                elif col in ("n",) or (isinstance(v, (int, np.integer))):
                    cell = str(int(v))
                elif st == "num" and isinstance(v, (float, int, np.floating, np.integer)):
                    cell = f"{float(v):.2f}"
                else:
                    cell = str(v)
                tds.append(f"<td>{html_mod.escape(cell)}</td>")
            body.append("<tr>" + "".join(tds) + "</tr>")
        cap = f"<caption>{html_mod.escape(caption)}</caption>" if caption else ""
        return (
            f'<table class="sortable">{cap}<thead><tr>{thead}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table>'
        )

    # Verdict narrative
    verdict_down = (
        f"Consecutive >=1 down close before entry: WR={v_down1['wr']*100:.1f}% "
        f"(n={v_down1['n']}, lift {fmt_pp(v_down1['lift_pp'])}) vs "
        f"0 down: WR={v_flat['wr']*100:.1f}% (n={v_flat['n']}). "
        f">=3 consec downs: WR={v_down3['wr']*100:.1f}% (n={v_down3['n']}, lift {fmt_pp(v_down3['lift_pp'])}). "
        f"Overall: {yes_no_lift(v_down1['lift_pp'], v_down1['n'])}."
    )
    verdict_drop = (
        f">=10% off 20d high: WR={v_off20['wr']*100:.1f}% (n={v_off20['n']}, lift {fmt_pp(v_off20['lift_pp'])}) vs "
        f"not: WR={v_not_off20['wr']*100:.1f}% (n={v_not_off20['n']}). "
        f">=10% off 52d high: WR={v_off52['wr']*100:.1f}% (n={v_off52['n']}, lift {fmt_pp(v_off52['lift_pp'])}). "
        f"Overall (20d): {yes_no_lift(v_off20['lift_pp'], v_off20['n'])}."
    )

    cards_html = []
    for c in name_cards:
        f = c["feats"]
        mode = (
            "RS would buy (watchlist PASSED_ALL_GATES; next-session open per engine)"
            if c["rs_would_buy"]
            else "Forced buy given current tape stats (no RS buy signal today)"
        )
        if c["is_open"]:
            mode = "Already OPEN in RS LatestRun - not a fresh buy"
        fwd_bits = ", ".join(
            f"H={h}: P(close&gt;entry open)={fmt_pct(v['p_up']*100 if np.isfinite(v['p_up']) else float('nan'))} (n={v['n']})"
            for h, v in c["fwd"].items()
        )
        cards_html.append(
            f"""
<section class="card">
  <h2>{html_mod.escape(c['symbol'])} - latest session {html_mod.escape(str(c['asof']))}</h2>
  <ul>
    <li><strong>Universe:</strong> {"YES - gold-65 / RS_universe" if c["in_universe"] else "NO"}</li>
    <li><strong>Open position:</strong> {"YES" if c["is_open"] else "NO"}</li>
    <li><strong>RS signal:</strong> {html_mod.escape(c["signal_status"])}</li>
    <li><strong>Entry date (watchlist):</strong> {html_mod.escape(c["entry_date"] or "-")}</li>
    <li><strong>Hint:</strong> {html_mod.escape(c["trigger_hint"] or "-")}</li>
    <li><strong>Answer framing:</strong> {html_mod.escape(mode)}</li>
    <li><strong>Last close:</strong> {fmt_num(c["last_close"], 2)}</li>
    <li><strong>Consec down closes:</strong> {f.get("consec_down_closes")}</li>
    <li><strong>Down days last 5 / 10:</strong> {f.get("down_days_last_5")} / {f.get("down_days_last_10")}</li>
    <li><strong>% off 20d / 52d / 252d high:</strong> {fmt_pct(f.get("pct_off_high_20d"))} / {fmt_pct(f.get("pct_off_high_52d"))} / {fmt_pct(f.get("pct_off_high_252d"))}</li>
    <li><strong>&gt;=10% off 20d / 52d:</strong> {c["off20"]} / {c["off52"]} (20d bin: {html_mod.escape(c["drop_bin_20d"])})</li>
  </ul>
  <h3>Historical conditional frequency (not a forecast)</h3>
  <ul>
    <li>Same consec-down bucket: WR={fmt_pct(c["bucket_consec_wr"]*100 if np.isfinite(c["bucket_consec_wr"]) else float("nan"))} (n={c["bucket_consec_n"]}, lift {fmt_pp(c["bucket_consec_lift"])})</li>
    <li>Primary match ({html_mod.escape(c["match_label"])}): WR={fmt_pct(c["emp_wr"]*100 if np.isfinite(c["emp_wr"]) else float("nan"))} (n={c["emp_n"]}), avg PNL%={fmt_pct(c["emp_pnl"])}</li>
    <li>Joint consec + 20d-off flag (may be thin): WR={fmt_pct(c["joint_wr"]*100 if np.isfinite(c["joint_wr"]) else float("nan"))} (n={c["joint_n"]}), avg PNL%={fmt_pct(c["joint_pnl"])}</li>
    <li>20d drop-bin alone ({html_mod.escape(c["drop_bin_20d"])}): WR={fmt_pct(c["drop_wr"]*100 if np.isfinite(c["drop_wr"]) else float("nan"))} (n={c["drop_n"]})</li>
    <li>Matched consec + 20d drop-bin: WR={fmt_pct(c["emp2_wr"]*100 if np.isfinite(c["emp2_wr"]) else float("nan"))} (n={c["emp2_n"]})</li>
    <li>Forward path (primary match): {fwd_bits}</li>
    <li><strong>Estimated P(up) ~ {fmt_pct(c["emp_wr"]*100 if np.isfinite(c["emp_wr"]) else float("nan"))}</strong> = historical RS Closed win rate in primary matching pre-buy bucket (full trade outcome, not same-day).</li>
  </ul>
</section>
"""
        )

    html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>RS Pre-Buy: Down Days and Drop From High</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:24px;max-width:1100px;color:#0f172a;background:#f8fafc}}
h1{{font-size:1.6rem;margin:0 0 .4rem}}
h2{{font-size:1.2rem;margin-top:1.6rem}}
h3{{font-size:1.05rem}}
.meta{{color:#475569;font-size:.95rem;margin-bottom:1rem}}
.verdict{{background:#ecfeff;border:1px solid #a5f3fc;padding:12px 14px;border-radius:8px;margin:12px 0}}
.card{{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:14px 16px;margin:14px 0}}
table.sortable{{border-collapse:collapse;width:100%;background:#fff;margin:10px 0 22px;font-size:.92rem}}
table.sortable th,table.sortable td{{border:1px solid #e2e8f0;padding:6px 8px;text-align:left}}
table.sortable thead th{{background:#f1f5f9}}
table.sortable caption{{caption-side:top;text-align:left;color:#64748b;font-size:.85rem;padding:4px 0}}
code{{background:#e2e8f0;padding:1px 4px;border-radius:3px}}
ul{{line-height:1.45}}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>RS Pre-Buy: Down Days and Drop From High</h1>
<p class="meta">
  Hypothesis analysis only (no production changes).<br/>
  Source: <strong>{html_mod.escape(source_label)}</strong><br/>
  OHLC: <code>data/ohlcv.duckdb</code> · features use bars <em>strictly before</em> <code>DATE_OPENED</code>.<br/>
  Baseline (OHLC-matched): n={baseline["n"]}, WR={baseline["wr"]*100:.1f}%, avg PNL%={baseline["avg_pnl"]:.1f}%, avg days={baseline["avg_days"]:.1f}.<br/>
  Context date: 2026-08-10 · latest OHLC session: <strong>{html_mod.escape(str(latest_session))}</strong>.
  Click column headers to sort.
</p>

<div class="verdict">
  <h2 style="margin-top:0">Q1 - Down days immediately prior to RS buy?</h2>
  <p>{html_mod.escape(verdict_down)}</p>
  <h2>Q2 - Quick ~10% drop from a new high before buy?</h2>
  <p>{html_mod.escape(verdict_drop)}</p>
</div>

<h2>Spearman correlations (rank)</h2>
{simple_table(corr_tbl, corr_cols, "Click column headers to sort")}

<h2>Consecutive down closes immediately prior</h2>
{simple_table(consec_h, bucket_cols, "Click column headers to sort")}

<h2>Down days in last 5 sessions</h2>
{simple_table(down5_h, bucket_cols, "Click column headers to sort")}

<h2>Down days in last 10 sessions</h2>
{simple_table(down10_h, bucket_cols, "Click column headers to sort")}

<h2>&gt;=10% off recent high (boolean)</h2>
{simple_table(bool_h, bool_cols, "Click column headers to sort")}

<h2>% off 20d high (binned)</h2>
{simple_table(d20_h, bucket_cols, "Click column headers to sort")}

<h2>% off 52d high (binned)</h2>
{simple_table(d52_h, bucket_cols, "Click column headers to sort")}

<h2>% off 252d high (binned)</h2>
{simple_table(d252_h, bucket_cols, "Click column headers to sort")}

<h2>Named names - today context (latest session)</h2>
<p class="meta">{html_mod.escape(", ".join(TODAY_NAMES))} · Click through each card below.</p>
{"".join(cards_html)}

<p class="meta">Trade-level export: <code>{html_mod.escape(str(trade_csv.relative_to(ROOT)))}</code></p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""

    out_path = OUT_DIR / "RS_PreBuy_DownDays_DropFromHigh.html"
    out_path.write_text(html_out, encoding="utf-8")

    # Console summary for parent agent
    print("=== SOURCE ===")
    print(source_label)
    print(f"baseline n={baseline['n']} WR={baseline['wr']*100:.2f}% avgPNL={baseline['avg_pnl']:.2f}%")
    print("=== Q1 DOWN DAYS ===")
    print(verdict_down)
    print(consec_tbl.to_string(index=False))
    print("=== Q2 10% OFF HIGH ===")
    print(verdict_drop)
    print(bool_tbl.to_string(index=False))
    print("=== NAMED NAMES ===")
    print(
        "symbol\tlast_close\tasof\tconsec\tpct_off_20d\trs_status\temp_wr\tvs_base_65.7\tuniv\topen\trs_buy"
    )
    for c in name_cards:
        f = c["feats"]
        emp = c["emp_wr"]
        emp_s = f"{emp*100:.1f}%" if np.isfinite(emp) else "—"
        vs = (
            f"{(emp - baseline['wr'])*100:+.1f}pp"
            if np.isfinite(emp)
            else "—"
        )
        pct20 = f.get("pct_off_high_20d")
        pct20_s = f"{float(pct20):.1f}%" if pct20 is not None and np.isfinite(pct20) else "—"
        status = c["signal_status"]
        if c["is_open"]:
            status = f"OPEN / {status}"
        elif c["rs_would_buy"]:
            status = f"would-buy / {status}"
        print(
            f"{c['symbol']}\t{fmt_num(c['last_close'], 2)}\t{c['asof']}\t"
            f"{f.get('consec_down_closes')}\t{pct20_s}\t{status}\t"
            f"{emp_s}\t{vs}\tuniv={c['in_universe']}\topen={c['is_open']}\trs_buy={c['rs_would_buy']}"
        )
    print("WROTE", out_path)


if __name__ == "__main__":
    main()
