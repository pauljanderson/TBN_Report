#!/usr/bin/env python3
"""Design page: realistic-aggressive risk-size recipes (no 16-year compound).

Stamp: drive/paul_experiments/risk_size_ideas_20260917/

Verifies Paul's MSFT participation math from on-disk daily (and 1m if present)
plus shop float / shares outstanding. Lists a handful of size recipes.
Does not run a wallet. Not gold. Not DailyRun.
"""
from __future__ import annotations

import html as html_mod
import json
import math
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

from compare_format import format_money  # noqa: E402

STAMP = "risk_size_ideas_20260917"
OUT_DIR = REPO / "drive" / "paul_experiments" / STAMP
DAILY_DIR = REPO / "data" / "newdata" / "data"
SNAPSHOT_CSV = REPO / "drive" / "paul_experiments" / "All_Symbols_Earnings_Snapshot.csv"
FUND_DB = REPO / "drive" / "fundamentals_cache.duckdb"
ASOF = date(2026, 9, 17)
ET = ZoneInfo("America/New_York")
FROZEN_ASOF = 5_935_426.95
FROZEN_SPY = 2_254_118.95
UNCAPPED_ASOF = 5_596_536_080_411.02
PUB_TEN_ASOF = 220_085_282_576.45
ACCOUNT = 250_000.0
SYMBOLS = ("MSFT", "NVDA", "AMD", "AU")  # mega, mega, large, mid (frozen peak name)
OPTIONAL = ("FEIM",)  # 10% lid peak name — include if daily exists
EQUITIES = (
    ("250k", 250_000.0),
    ("6M", 6_000_000.0),
    ("50M", 50_000_000.0),
    ("1B", 1_000_000_000.0),
)

PAUL_ASK = (
    "He still likes 1% risk as a baseline, but sees it go ludicrous. "
    "Why not 1% until risk is $10k, or 0.9% until $12k, or even $50k? "
    "Why not risk more with more money? What is realistic? Cap by % of shares traded? "
    "MSFT example: he thinks 0.0024% of outstanding trades daily; 1/100 of that = "
    "0.000024% outstanding ≈ 18k shares ≈ $9M. At $1B AUM that might be reasonable. "
    "Flat $2,500 risk feels too timid. Come up with a handful of realistic yet aggressive ideas."
)

LAYMAN = (
    "The frozen $2,500 was an honesty knob so the 16-year paper book could not "
    "keep risking 1% of a growing mountain — it was not a claim that live risk "
    "should stay $2,500 forever. One percent per name is a fine instinct until "
    "you stack it: 15 names × 1% = 15% of the account at risk at once (that is "
    "why paper went to $5.60T and why live June 12 put about $979k into names "
    "on a ~$500k account). This page does not re-run 16 years. It checks the "
    "MSFT share-count math on the shop’s daily tape, then offers a short menu "
    "of lids that stay aggressive at $250k / $6M and still make sense at $50M / $1B. "
    "Average Daily Volume 20 (ADV20) = mean shares traded over the last 20 daily bars. "
    "Assets Under Management (AUM) here just means account equity. "
    "Indicators (IND) is the old live sleeve; it is out of the frozen 5-sys book."
)


def _esc(s: Any) -> str:
    return html_mod.escape("" if s is None else str(s))


def _fmt_sh(x: Optional[float]) -> str:
    if x is None or not math.isfinite(float(x)):
        return "—"
    v = float(x)
    if abs(v) >= 1_000_000:
        return f"{v:,.0f}"
    return f"{v:,.1f}" if abs(v) < 100 else f"{v:,.0f}"


def _fmt_pct(x: Optional[float], digits: int = 4) -> str:
    if x is None or not math.isfinite(float(x)):
        return "—"
    return f"{float(x):.{digits}f}%"


def _fmt_mult(x: Optional[float]) -> str:
    if x is None or not math.isfinite(float(x)):
        return "—"
    return f"{float(x):,.4f}×"


def _sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{_esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


SORTABLE_JS = """
<script>
(function(){
  function parseCell(td, type){
    var t=(td.textContent||"").trim().replace(/[$,%×x]/g,"").replace(/,/g,"");
    if(type==="num"){var n=parseFloat(t); return isNaN(n)?null:n;}
    if(type==="date"||type==="month"){return t;}
    return t.toLowerCase();
  }
  function bind(table){
    var ths=table.querySelectorAll("th.sortable-th");
    ths.forEach(function(th, colIdx){
      function go(){
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
      }
      th.addEventListener("click", go);
      th.addEventListener("keydown", function(e){
        if(e.key==="Enter"||e.key===" "){e.preventDefault(); go();}
      });
    });
  }
  document.querySelectorAll("table.sortable").forEach(bind);
})();
</script>
"""


def _daily_path(sym: str) -> Path:
    return DAILY_DIR / f"{sym}.csv"


def _load_daily(sym: str) -> pd.DataFrame:
    p = _daily_path(sym)
    df = pd.read_csv(p)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"]).sort_values("Date")
    df = df[df["Date"].dt.date <= ASOF]
    for col in ("Open", "High", "Low", "Close", "Volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.reset_index(drop=True)


def _atr20(df: pd.DataFrame) -> float:
    h = df["High"].to_numpy(float)
    lo = df["Low"].to_numpy(float)
    c = df["Close"].to_numpy(float)
    n = len(df)
    if n < 2:
        return float("nan")
    tr = [float(h[0] - lo[0])]
    for i in range(1, n):
        tr.append(
            max(
                float(h[i] - lo[i]),
                abs(float(h[i] - c[i - 1])),
                abs(float(lo[i] - c[i - 1])),
            )
        )
    last = tr[-20:] if len(tr) >= 20 else tr
    return float(sum(last) / len(last))


def _fundamentals() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    want = set(SYMBOLS) | set(OPTIONAL)
    if FUND_DB.exists():
        try:
            import duckdb

            con = duckdb.connect(str(FUND_DB), read_only=True)
            rows = con.execute(
                """
                SELECT symbol, as_of, market_cap, float_shares, raw_json, fetched_at
                FROM yf_symbol_info
                WHERE symbol IN ({})
                """.format(",".join("?" * len(want))),
                list(want),
            ).fetchall()
            con.close()
            for symbol, as_of, mcap, fl, raw, fetched in rows:
                so = None
                fl_raw = None
                if raw:
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        payload = {}
                    so = payload.get("sharesOutstanding") or payload.get(
                        "shares_outstanding"
                    )
                    fl_raw = payload.get("floatShares") or payload.get("float_shares")
                    if so is None and isinstance(payload, dict):
                        info = payload.get("info") or payload
                        if isinstance(info, dict):
                            so = info.get("sharesOutstanding")
                            fl_raw = fl_raw or info.get("floatShares")
                try:
                    so_f = float(so) if so is not None else None
                except (TypeError, ValueError):
                    so_f = None
                try:
                    fl_f = float(fl_raw) if fl_raw is not None else (
                        float(fl) if fl is not None else None
                    )
                except (TypeError, ValueError):
                    fl_f = float(fl) if fl is not None else None
                out[str(symbol)] = {
                    "source": "fundamentals_cache.duckdb yf_symbol_info",
                    "as_of": str(as_of) if as_of is not None else None,
                    "fetched_at": str(fetched) if fetched is not None else None,
                    "market_cap": float(mcap) if mcap is not None else None,
                    "float_shares": fl_f,
                    "shares_outstanding": so_f,
                }
        except Exception as exc:  # noqa: BLE001 — fall back to snapshot
            out["_error"] = {"source": "duckdb", "error": str(exc)}
    if SNAPSHOT_CSV.exists():
        try:
            snap = pd.read_csv(SNAPSHOT_CSV)
            snap["symbol"] = snap["symbol"].astype(str)
            for _, row in snap[snap["symbol"].isin(want)].iterrows():
                sym = str(row["symbol"])
                rec = out.setdefault(sym, {"source": "All_Symbols_Earnings_Snapshot.csv"})
                if rec.get("float_shares") is None and pd.notna(row.get("float_shares")):
                    rec["float_shares"] = float(row["float_shares"])
                    rec["source"] = rec.get("source") or "All_Symbols_Earnings_Snapshot.csv"
                if rec.get("market_cap") is None and pd.notna(row.get("market_cap")):
                    rec["market_cap"] = float(row["market_cap"])
                if rec.get("as_of") is None and pd.notna(row.get("as_of")):
                    rec["as_of"] = str(row["as_of"])
        except Exception as exc:  # noqa: BLE001
            out["_snap_error"] = {"error": str(exc)}
    return out


def _last_day_1m_volume(sym: str) -> dict[str, Any]:
    info: dict[str, Any] = {
        "has_file": False,
        "volume": None,
        "n_bars": 0,
        "path": None,
        "tape_min": None,
        "tape_max": None,
    }
    try:
        from stock_analysis.intraday_1m import DEFAULT_1M_DIR, read_1m

        p = DEFAULT_1M_DIR / f"{sym}.parquet"
        info["path"] = str(p)
        if not p.exists():
            return info
        df = read_1m(sym)
        if df is None or df.empty:
            return info
        info["has_file"] = True
        ts = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(ET)
        info["tape_min"] = str(ts.min())
        info["tape_max"] = str(ts.max())
        sub = df.loc[ts.dt.date == ASOF]
        info["n_bars"] = int(len(sub))
        if sub.empty:
            return info
        vol_col = "volume" if "volume" in sub.columns else (
            "Volume" if "Volume" in sub.columns else None
        )
        if vol_col:
            info["volume"] = float(pd.to_numeric(sub[vol_col], errors="coerce").sum())
    except Exception as exc:  # noqa: BLE001
        info["error"] = str(exc)
    return info


def _measure(sym: str, fund: dict[str, dict[str, Any]]) -> dict[str, Any]:
    df = _load_daily(sym)
    last = df.iloc[-1]
    close = float(last["Close"])
    last_vol = float(last["Volume"])
    last_date = last["Date"].date().isoformat()
    tail = df.tail(20)
    adv = float(tail["Volume"].mean())
    atr = _atr20(df)
    frow = fund.get(sym, {})
    so = frow.get("shares_outstanding")
    fl = frow.get("float_shares")
    denom = so if so and so > 0 else (fl if fl and fl > 0 else None)
    denom_kind = (
        "shares_outstanding"
        if so and so > 0
        else ("float_shares" if fl and fl > 0 else None)
    )
    adv_vs_so = (100.0 * adv / denom) if denom else None
    m1 = _last_day_1m_volume(sym)
    return {
        "symbol": sym,
        "tier": {
            "MSFT": "mega",
            "NVDA": "mega",
            "AMD": "large",
            "AU": "mid (frozen $2,500 peak name)",
            "FEIM": "small/mid (10% lid peak name)",
        }.get(sym, ""),
        "last_date": last_date,
        "close": close,
        "last_volume": last_vol,
        "n_daily": int(len(df)),
        "adv20_shares": adv,
        "adv20_dollars": adv * close,
        "atr20": atr,
        "atr20_pct": (100.0 * atr / close) if close else None,
        "shares_outstanding": so,
        "float_shares": fl,
        "share_denom": denom,
        "share_denom_kind": denom_kind,
        "fund_as_of": frow.get("as_of"),
        "fund_source": frow.get("source"),
        "market_cap": frow.get("market_cap"),
        "adv_vs_denom_pct": adv_vs_so,
        "p01_adv_shares": adv * 0.01,
        "p01_adv_dollars": adv * 0.01 * close,
        "p001_adv_shares": adv * 0.001,
        "p001_adv_dollars": adv * 0.001 * close,
        "p10_adv_shares": adv * 0.10,
        "p10_adv_dollars": adv * 0.10 * close,
        "m1": m1,
        "daily_path": str(_daily_path(sym)),
    }


def _risk_at(equity: float, rmax: float) -> float:
    return min(0.01 * equity, rmax)


def _notional_from_risk(risk: float, stop_dist: float) -> float:
    if stop_dist <= 0 or not math.isfinite(stop_dist):
        return float("nan")
    return risk / stop_dist * (risk / risk)  # keep finite


def _shares_from_risk(risk: float, stop_dist: float) -> Optional[float]:
    if stop_dist is None or stop_dist <= 0 or not math.isfinite(stop_dist):
        return None
    return risk / stop_dist


def build_rows(measures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return measures


def write_baseline(facts: dict[str, Any]) -> None:
    msft = next(m for m in facts["names"] if m["symbol"] == "MSFT")
    lines = [
        f"# BASELINE — {STAMP}",
        "",
        "**Status:** Design page only. **Not gold. Not DailyRun.** No wallet re-run.",
        "",
        "## What you asked",
        "",
        f"> {PAUL_ASK}",
        "",
        "## In plain English",
        "",
        LAYMAN,
        "",
        "## Honesty first",
        "",
        "- Frozen **$2,500** (`risk2500_frozen_20260917`) was an honesty knob so 1% of a growing pile could not print $5.60T / $220B. As-of **$5,935,426.95** vs SPY **$2,254,118.95**. HOLD research. It is not a life sentence for live risk.",
        "- 1% **per name** stacks: 15 names × 1% = 15% book risk. That is the June-12 / paper-explode mechanism.",
        "",
        "## Frozen knobs (this page)",
        "",
        f"- As-of date for tape: **{ASOF.isoformat()}**",
        f"- Daily OHLCV: `{DAILY_DIR.as_posix()}`",
        "- ADV20 = mean Volume of last 20 daily bars on or before as-of (not invented).",
        "- Share count: `yf_symbol_info.sharesOutstanding` from raw JSON when present; else `float_shares`. Labeled.",
        "- No 16-year compound. No DailyRun wire. OOS not used to pick a ceiling.",
        "",
        "## MSFT check",
        "",
        f"- Last close **{msft['last_date']}** {_money(msft['close'])}; last daily volume {_fmt_sh(msft['last_volume'])}.",
        f"- ADV20 **{_fmt_sh(msft['adv20_shares'])}** shares ≈ {format_money(msft['adv20_dollars'])}.",
        f"- Share denom ({msft.get('share_denom_kind') or 'missing'}): {_fmt_sh(msft.get('share_denom'))} (source: {msft.get('fund_source') or 'none'}; Yahoo floatShares else sharesOutstanding).",
        f"- ADV / denom = {_fmt_pct(msft.get('adv_vs_denom_pct'), 4)} vs his **0.0024%** (~113× if both are percents; kind read = stray % on 0.0024 ≈ 0.24%).",
        f"- 1% ADV = {_fmt_sh(msft['p01_adv_shares'])} shares ≈ {format_money(msft['p01_adv_dollars'])}.",
        f"- 0.1% ADV = {_fmt_sh(msft['p001_adv_shares'])} shares ≈ {format_money(msft['p001_adv_dollars'])} (his 18k / ~$9M is 0.09% ADV / $8.96M at last close).",
        f"- 10% ADV = {_fmt_sh(msft['p10_adv_shares'])} shares ≈ {format_money(msft['p10_adv_dollars'])}.",
        f"- 0.0024% of shop float = {_fmt_sh((msft['share_denom'] or 0) * 0.0024 / 100.0)} sh; 1/100 of that = 1,779 sh — not 18k.",
        "",
        "## Recommended next run (not started)",
        "",
        "- `risk = min(0.01 × BOM Closed-only equity, $50k)` **and** `shares ≤ 1% × ADV20`.",
        "- Ask him to pick ceiling **$10k vs $50k** before spending a wallet pass.",
        "- Not a cheap overlay on the frozen $2,500 book (1% path is a different compound; ADV almost never binds at $2,500).",
        "- Not gold. Not DailyRun.",
        "",
    ]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _money(x: Optional[float]) -> str:
    if x is None or not math.isfinite(float(x)):
        return "—"
    return format_money(float(x))


def _idea_cells_ceiling(rmax: float) -> dict[str, str]:
    cells = {}
    for key, eq in EQUITIES:
        r = _risk_at(eq, rmax)
        bind = "ceiling binds" if 0.01 * eq > rmax + 1e-9 else "still 1%"
        cells[key] = f"{_money(r)}/name ({bind})"
    return cells


def _msft_adv_line(msft: dict[str, Any], p: float, equity: float) -> str:
    risk = 0.01 * equity
    stop = float(msft["atr20"])
    sh_risk = _shares_from_risk(risk, stop)
    cap = p * float(msft["adv20_shares"])
    px = float(msft["close"])
    if sh_risk is None:
        return "—"
    sh = min(sh_risk, cap)
    bind = "ADV binds" if sh_risk > cap + 1e-9 else "risk binds"
    return (
        f"{_fmt_sh(sh)} sh / {_money(sh * px)} notional "
        f"({bind}; 1% risk {_money(risk)})"
    )


def build_html(facts: dict[str, Any], generated: datetime) -> str:
    names: list[dict[str, Any]] = facts["names"]
    msft = next(m for m in names if m["symbol"] == "MSFT")
    his_adv_pct = 0.0024
    our_pct = msft.get("adv_vs_denom_pct")
    slip = None
    if our_pct and our_pct > 0:
        slip = our_pct / his_adv_pct

    adv_head = "".join(
        _sortable_th(h, t)
        for h, t in (
            ("Name", "text"),
            ("Tier", "text"),
            ("Last close", "num"),
            ("Last daily vol", "num"),
            ("ADV20 shares", "num"),
            ("ADV20 $", "num"),
            ("Share count", "num"),
            ("Count kind", "text"),
            ("ADV / count", "num"),
            ("1% ADV sh / $", "text"),
            ("0.1% ADV sh / $", "text"),
            ("10% ADV sh / $", "text"),
            ("ATR20", "num"),
            ("1m as-of vol", "num"),
        )
    )
    adv_body = []
    for m in names:
        m1v = (m.get("m1") or {}).get("volume")
        adv_body.append(
            "<tr>"
            f"<td><strong>{_esc(m['symbol'])}</strong></td>"
            f"<td>{_esc(m['tier'])}</td>"
            f"<td>{_money(m['close'])}<div class='small'>{_esc(m['last_date'])}</div></td>"
            f"<td>{_fmt_sh(m['last_volume'])}</td>"
            f"<td>{_fmt_sh(m['adv20_shares'])}</td>"
            f"<td>{_money(m['adv20_dollars'])}</td>"
            f"<td>{_fmt_sh(m.get('share_denom'))}</td>"
            f"<td>{_esc(m.get('share_denom_kind') or 'not in shop')}</td>"
            f"<td>{_fmt_pct(m.get('adv_vs_denom_pct'), 4)}</td>"
            f"<td>{_fmt_sh(m['p01_adv_shares'])} / {_money(m['p01_adv_dollars'])}</td>"
            f"<td>{_fmt_sh(m['p001_adv_shares'])} / {_money(m['p001_adv_dollars'])}</td>"
            f"<td>{_fmt_sh(m['p10_adv_shares'])} / {_money(m['p10_adv_dollars'])}</td>"
            f"<td>{_money(m['atr20'])} <span class='small'>({_fmt_pct(m.get('atr20_pct'), 2)})</span></td>"
            f"<td>{_fmt_sh(m1v) if m1v else '—'}</td>"
            "</tr>"
        )

    c10 = _idea_cells_ceiling(10_000)
    c25 = _idea_cells_ceiling(25_000)
    c50 = _idea_cells_ceiling(50_000)

    ideas = [
        {
            "name": "1% + dollar ceiling",
            "freeze": "risk = min(0.01 × equity, Rmax); Rmax ∈ {$10k, $25k, $50k}; aggressive = $50k",
            "e250k": c50["250k"] + f" · $10k option {c10['250k']}",
            "e6m": f"$50k → {c50['6M']}; $25k → {c25['6M']}; $10k → {c10['6M']}",
            "e50m": f"all ceilings bind: $10k / $25k / $50k per name",
            "e1b": "same $10k / $25k / $50k — 1% of $1B would have been $10M/name without a lid",
            "stops": "YES — risk stops growing once equity > Rmax / 0.01 ($1M at $10k, $5M at $50k). $5T needs unbounded 1%.",
        },
        {
            "name": "1% + ADV participation",
            "freeze": "shares = min(risk / stop_dist, p × ADV20); p=1% aggressive-tradeable; p=0.1% = his ~$9M MSFT; p=10% moves the tape",
            "e250k": _msft_adv_line(msft, 0.01, 250_000),
            "e6m": _msft_adv_line(msft, 0.01, 6_000_000),
            "e50m": _msft_adv_line(msft, 0.01, 50_000_000),
            "e1b": _msft_adv_line(msft, 0.01, 1_000_000_000)
            + f" · his $9M ≈ 0.1% ADV ({_money(msft['p001_adv_dollars'])})",
            "stops": "YES on the names that printed the $5T (tight-stop / thinner tape). Mega still allows huge $ at 1% ADV — pair with a dollar ceiling.",
        },
        {
            "name": "Book-level 1% (not per name)",
            "freeze": "sum(open $ risk to stop) ≤ B × equity; B=0.01 default; aggressive B=0.02–0.05; split across names",
            "e250k": "B=1% → $2,500 total book risk (not $2,500 × 10). B=5% → $12,500 book / ~$1,250 if 10 names.",
            "e6m": "B=1% → $60k total book (vs $60k × 8 = $480k if per-name). B=5% → $300k book.",
            "e50m": "B=1% → $500k book; B=5% → $2.5M book. Still needs ADV or a name lid at mid/small.",
            "e1b": "B=1% → $10M book; B=5% → $50M book. This is how you risk more with more money without 15× stacking.",
            "stops": "YES — kills the 15 × 1% stack that made paper and June 12 ($979k on ~$500k). $5T was per-name 1% compounded.",
        },
        {
            "name": "Sqrt / step-up 1%",
            "freeze": "1% until E*=$1M, then risk = 0.01×E*×√(E/E*); or step 1% → $1M, 0.5% after, 0.25% after $10M",
            "e250k": "still $2,500/name (below E*)",
            "e6m": f"sqrt from $1M: {_money(10_000 * math.sqrt(6_000_000 / 1_000_000))}/name · step 0.5% = {_money(0.005 * 6_000_000)}/name",
            "e50m": f"sqrt: {_money(10_000 * math.sqrt(50_000_000 / 1_000_000))}/name · step 0.25% = {_money(0.0025 * 50_000_000)}/name",
            "e1b": f"sqrt: {_money(10_000 * math.sqrt(1_000_000_000 / 1_000_000))}/name · step 0.25% = {_money(2_500_000)}/name — still fat without ADV",
            "stops": "Sqrt: YES, $5T dies. Step 0.25% after $10M: SLOWS a lot; can still get huge over 16 years if you never add a dollar/ADV lid. Pair it.",
        },
        {
            "name": "Liquidity-tier notional",
            "freeze": "mega notional ≤ $5–10M (his MSFT ~$9M if ADV supports); mid ≤ 1% ADV20 (or $1M); small ≤ 1% ADV20 (or $250k)",
            "e250k": "1% risk usually binds first (MSFT 2% stop ≈ $125k notional). Tier is slack at this size.",
            "e6m": f"MSFT 1% ADV = {_money(msft['p01_adv_dollars'])}; $10M mega lid is slack. AU 1% ADV = "
            + _money(next(x['p01_adv_dollars'] for x in names if x['symbol']=='AU'))
            + " — mid lid binds sooner.",
            "e50m": "Mega $10M lid binds on fat MSFT risk. Mid/small already ADV-bound.",
            "e1b": f"Mega $9–10M ≈ 0.9–1.0% AUM and ≈ 0.1% of MSFT ADV ({_money(msft['p001_adv_dollars'])} is the 0.1% print). Reasonable if you can work the order. Not 2% of a mid-cap.",
            "stops": "YES — CFG / FEIM-class notionals cannot reach trillions under a small/mid tier.",
        },
        {
            "name": "Three lids (mention only)",
            "freeze": "risk = min(1% × E, Rmax) AND notional ≤ 10% × E AND shares ≤ p × ADV20; only the binding lid matters",
            "e250k": "usually the 1% risk lid",
            "e6m": "risk ~$60k; 10% name = $600k notional; ADV slack on MSFT — risk still binds on mega, name/ADV on mid",
            "e50m": "10% name = $5M notional and/or $50k ceiling — both tighter than raw 1%",
            "e1b": "all three can bind; do not shop p and Rmax on the same pass",
            "stops": "YES if any lid is real. Mention only — do not run a 3-knob shop.",
        },
    ]

    idea_head = "".join(
        _sortable_th(h, t)
        for h, t in (
            ("Idea", "text"),
            ("Freeze (one line)", "text"),
            ("$250k", "text"),
            ("$6M (frozen as-of class)", "text"),
            ("$50M", "text"),
            ("$1B", "text"),
            ("Stops $5T?", "text"),
        )
    )
    idea_body = []
    for it in ideas:
        idea_body.append(
            "<tr>"
            f"<td><strong>{_esc(it['name'])}</strong></td>"
            f"<td>{_esc(it['freeze'])}</td>"
            f"<td>{_esc(it['e250k'])}</td>"
            f"<td>{_esc(it['e6m'])}</td>"
            f"<td>{_esc(it['e50m'])}</td>"
            f"<td>{_esc(it['e1b'])}</td>"
            f"<td>{_esc(it['stops'])}</td>"
            "</tr>"
        )

    work_head = "".join(
        _sortable_th(h, t)
        for h, t in (
            ("Clip", "text"),
            ("MSFT shares", "num"),
            ("MSFT $", "num"),
            ("% of ADV20", "num"),
            ("% of share count", "num"),
            ("vs his 18k / $9M", "text"),
        )
    )
    clips = [
        ("His quote (18k sh / ~$9M)", 18_000.0, 18_000.0 * msft["close"]),
        ("0.1% of ADV20", msft["p001_adv_shares"], msft["p001_adv_dollars"]),
        ("1% of ADV20 (aggressive-tradeable)", msft["p01_adv_shares"], msft["p01_adv_dollars"]),
        ("10% of ADV20 (moves the tape)", msft["p10_adv_shares"], msft["p10_adv_dollars"]),
        (
            "1/100 of his 0.0024% of outstanding (if we had his %)",
            (msft["share_denom"] * 0.0024 / 100.0 / 100.0) if msft.get("share_denom") else None,
            None,
        ),
        (
            "True 0.0024% of share count (ADV-like if his % were right)",
            (msft["share_denom"] * 0.0024 / 100.0) if msft.get("share_denom") else None,
            None,
        ),
    ]
    work_rows = []
    for label, sh, dol in clips:
        if sh is None:
            work_rows.append(
                f"<tr><td>{_esc(label)}</td><td>—</td><td>—</td><td>—</td><td>—</td><td>need share count</td></tr>"
            )
            continue
        dol = dol if dol is not None else sh * msft["close"]
        pct_adv = 100.0 * sh / msft["adv20_shares"] if msft["adv20_shares"] else None
        pct_so = (
            100.0 * sh / msft["share_denom"] if msft.get("share_denom") else None
        )
        vs = f"{_fmt_mult(sh / 18_000.0)} his share count"
        work_rows.append(
            "<tr>"
            f"<td>{_esc(label)}</td>"
            f"<td>{_fmt_sh(sh)}</td>"
            f"<td>{_money(dol)}</td>"
            f"<td>{_fmt_pct(pct_adv, 3)}</td>"
            f"<td>{_fmt_pct(pct_so, 6)}</td>"
            f"<td>{_esc(vs)}</td>"
            "</tr>"
        )

    slip_txt = (
        f"On-disk ADV20 / shop float is <strong>{_fmt_pct(our_pct, 4)}</strong> — "
        f"about <strong>{slip:.0f}×</strong> the 0.0024% figure. Kind read: a percent "
        f"sign landed on 0.0024, which is already the decimal for ~0.24% "
        f"(true print is 0.27%). His <strong>18k shares / ~$9M</strong> is a separate "
        f"check that lands on <strong>0.09% of ADV20</strong> "
        f"({_fmt_sh(msft['p001_adv_shares'])} sh / {_money(msft['p001_adv_dollars'])} "
        f"at 0.1% ADV), not on 1/100 of 0.0024% of float "
        f"(that arithmetic is 1,779 sh / ~$886k)."
        if slip
        else "Share count was not in the shop — ADV% of outstanding cannot be finished; ADV shares still check the 18k / $9M line."
    )

    m1_note = []
    for m in names:
        mm = m.get("m1") or {}
        span = ""
        if mm.get("tape_min") or mm.get("tape_max"):
            span = f" tape {mm.get('tape_min') or '?'} → {mm.get('tape_max') or '?'}"
        if mm.get("volume"):
            m1_note.append(
                f"{m['symbol']} 1m as-of volume {_fmt_sh(mm['volume'])} "
                f"({mm.get('n_bars', 0)} bars{span})"
            )
        elif mm.get("has_file"):
            m1_note.append(
                f"{m['symbol']} 1m file present but no {ASOF.isoformat()} bars{span}"
            )
        else:
            m1_note.append(f"{m['symbol']} no 1m parquet")
    m1_line = "; ".join(m1_note)

    sources = [
        f"daily: {DAILY_DIR.as_posix()} last 20 Volume bars through {ASOF.isoformat()}",
        f"fundamentals: {FUND_DB.as_posix()} yf_symbol_info raw_json sharesOutstanding / floatShares (fallback All_Symbols_Earnings_Snapshot.csv)",
        "1m: data/intraday/1m/{SYM}.parquet if present — last-print check only, not the ADV source",
        "frozen honesty stamp: risk2500_frozen_20260917 (as-of $5,935,426.95 vs SPY $2,254,118.95; HOLD)",
        "uncapped 5-sys 1% sell-winner as-of $5,596,536,080,411.02; 10% lid sibling $220,085,282,576.45",
        "live stacking example (given): June 12 ≈ $979k on ~$500k",
        "Indicators (IND) out of the 5-sys frozen book",
        "No 16-year compound this stamp. Not gold. Not DailyRun.",
    ]

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Risk-size ideas — ceiling + liquidity — {STAMP}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin:24px; color:#0f172a; }}
h1 {{ font-size:1.5rem; margin-bottom:4px; }}
h2 {{ font-size:1.15rem; margin-top:28px; }}
h3 {{ font-size:1rem; margin:16px 0 8px; color:#334155; }}
.sub {{ color:#64748b; margin-bottom:20px; line-height:1.5; font-size:0.95rem; }}
.ask {{ background:#fff7ed; border:1px solid #fdba74; border-radius:10px; padding:14px 16px; margin:16px 0; }}
.ask h2 {{ margin-top:8px; font-size:1rem; }}
.ask h2:first-child {{ margin-top:0; }}
blockquote {{ margin:8px 0 12px; color:#9a3412; }}
.lead {{ background:#ecfdf5; border:1px solid #6ee7b7; border-radius:10px; padding:14px 16px; margin:12px 0 20px; }}
.hold {{ background:#eef2ff; border:1px solid #c7d2fe; border-radius:10px; padding:12px 14px; margin:12px 0 20px; }}
.warn {{ background:#fef2f2; border:1px solid #fecaca; border-radius:10px; padding:12px 14px; margin:12px 0; }}
.cards {{ display:flex; flex-wrap:wrap; gap:12px; margin:16px 0 24px; }}
.card {{ background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:14px 16px; min-width:200px; flex:1 1 220px; }}
.card-shared {{ background:#ecfdf5; border-color:#6ee7b7; }}
.card h3 {{ margin:0 0 8px; font-size:13px; color:#475569; font-weight:700; }}
.metric {{ font-size:1.35rem; font-weight:700; line-height:1.2; }}
.small {{ font-size:12px; color:#64748b; }}
.muted {{ color:#94a3b8; }}
ol.ideas {{ margin:8px 0 0 20px; line-height:1.55; }}
table {{ border-collapse:collapse; font-size:12px; width:100%; }}
th, td {{ border:1px solid #e2e8f0; padding:7px 8px; text-align:left; vertical-align:top; }}
th {{ background:#f1f5f9; }}
th.sortable-th {{ cursor:pointer; user-select:none; white-space:normal; }}
th.sortable-th:hover {{ background:#e2e8f0; }}
.sort-ind {{ display:inline-block; width:0.9em; margin-left:4px; color:#94a3b8; font-size:10px; }}
th.sort-asc .sort-ind::after {{ content:"▲"; color:#334155; }}
th.sort-desc .sort-ind::after {{ content:"▼"; color:#334155; }}
tr.total-row th, tr.total-row td {{ background:#f8fafc; border-top:2px solid #334155; }}
ul.sources {{ font-size:12px; color:#475569; line-height:1.6; }}
body {{ max-width: none; }}
.table-wrap {{ max-height: none !important; overflow: visible !important; }}
table, table.sortable {{ width: 100%; min-width: 0; }}
th, td {{ overflow-wrap: anywhere; }}
</style></head><body>
<h1>Risk-size ideas — 1% is fine with a ceiling and a liquidity cap</h1>
<p class="sub">
Stamp <code>{STAMP}</code> · as-of {ASOF.isoformat()} · design page ·
<strong>Not gold. Not DailyRun.</strong>
Generated {generated.strftime("%Y-%m-%d %H:%M %Z")}. Click column headers to sort.
</p>

<div class="lead">
  <h2>Lead</h2>
  <p><strong>$2,500 was honesty, not a life sentence.</strong>
  The frozen 5-sys book (StockBee / Relative Strength Index / Volume Zone / Magic Touch / Rocket Launcher;
  Indicators / IND out) killed $5.60T / $220B and finished
  <strong>{format_money(FROZEN_ASOF)}</strong> vs SPY <strong>{format_money(FROZEN_SPY)}</strong>.
  That knob exists so 1% of a growing mountain cannot reprint the trillion path.
  His 1% instinct is fine <strong>with a dollar ceiling and a liquidity cap</strong>.</p>
  <p>1% <em>per name</em> stacks: 15 names × 1% = 15% book risk. That is why paper exploded
  <em>and</em> why live June 12 was ~$979k on a ~$500k account. Flat $2,500 forever is too timid
  once the account is real; unbounded 1% is too wild once the account is huge.</p>
</div>

<div class="ask">
<h2>What you asked</h2>
<blockquote>{_esc(PAUL_ASK)}</blockquote>
<h2>In plain English</h2>
<p>{_esc(LAYMAN)}</p>
</div>

<div class="cards">
  <div class="card card-shared">
    <h3>Frozen $2,500 as-of</h3>
    <div class="metric">{format_money(FROZEN_ASOF)}</div>
    <div class="small">vs SPY {format_money(FROZEN_SPY)} · HOLD research · stamp risk2500_frozen_20260917</div>
  </div>
  <div class="card">
    <h3>MSFT last close</h3>
    <div class="metric">{_money(msft['close'])}</div>
    <div class="small">{_esc(msft['last_date'])} · daily vol {_fmt_sh(msft['last_volume'])}</div>
  </div>
  <div class="card">
    <h3>MSFT ADV20</h3>
    <div class="metric">{_fmt_sh(msft['adv20_shares'])}</div>
    <div class="small">{_money(msft['adv20_dollars'])} · {_fmt_pct(msft.get('adv_vs_denom_pct'), 3)} of {_esc(msft.get('share_denom_kind') or 'share count')}</div>
  </div>
  <div class="card">
    <h3>His 18k / ~$9M is</h3>
    <div class="metric">~0.1% of ADV</div>
    <div class="small">not 1/100 of 0.0024% outstanding · {_money(msft['p001_adv_dollars'])} on this tape</div>
  </div>
</div>

<h2>MSFT math — kindly corrected</h2>
<p>{slip_txt}
ADV20 on this shop tape is tens of millions of shares (usual MSFT), not a few hundred thousand.
Use the 18k / $9M line as <strong>0.1% of ADV</strong> — a conservative clip and a reasonable
~$1B AUM ticket if you can work the order. It is <em>not</em> 1% of ADV
({_fmt_sh(msft['p01_adv_shares'])} / {_money(msft['p01_adv_dollars'])}) and it is not 10% of ADV
({_fmt_sh(msft['p10_adv_shares'])} / {_money(msft['p10_adv_dollars'])}, which moves the tape).
0.0024% of the shop float ({_fmt_sh(msft.get('share_denom'))}) is
{_fmt_sh((msft['share_denom'] * 0.0024 / 100.0) if msft.get('share_denom') else None)} shares /
{_money((msft['share_denom'] * 0.0024 / 100.0 * msft['close']) if msft.get('share_denom') else None)}
≈ 0.89% of ADV — closer to a 1% ADV clip than to his 18k.</p>
<p class="small">Shop field is <code>float_shares</code> (Yahoo <code>floatShares</code>,
else <code>sharesOutstanding</code> fallback) from {_esc(msft.get('fund_source') or 'n/a')},
as-of {_esc(msft.get('fund_as_of') or 'n/a')}. MSFT 7.41B is the usual outstanding-class count.
1-minute tape (Yahoo, short history) is a last-print check only — ADV20 is daily Volume.
{_esc(m1_line)}.</p>

<div class="table-wrap">
<p class="small">On-disk daily through {ASOF.isoformat()}. Click headers to sort.</p>
<table class="sortable">
<caption class="small">Participation vs outstanding / float — MSFT plus mega / large / mid from the same store</caption>
<thead><tr>{adv_head}</tr></thead>
<tbody>
{''.join(adv_body)}
</tbody>
</table>
</div>

<div class="table-wrap">
<table class="sortable">
<caption class="small">MSFT clips vs his 18k / $9M (price = last daily close)</caption>
<thead><tr>{work_head}</tr></thead>
<tbody>
{''.join(work_rows)}
</tbody>
</table>
</div>

<h2>What is realistic for an account</h2>
<ul>
<li><strong>$250k:</strong> 1% = $2,500/name is already aggressive if 10 names are open (10% book).
Live $75–100k lots were 15–20% of the old $500k <em>per name</em>.</li>
<li><strong>$6M paper as-of</strong> (frozen {_money(FROZEN_ASOF)}): raw 1% = $60k/name; 8 names = $480k risk;
2× deploy = $12M. Needs an ADV cap or a book-risk cap or it becomes June-12 again.</li>
<li><strong>$1B:</strong> raw 1% = $10M/name. MSFT {_money(msft['p001_adv_dollars'])} (0.1% ADV) is ~0.9% AUM
and {_fmt_pct(100.0 * msft['p001_adv_dollars'] / msft['adv20_dollars'], 3)} of ADV dollars.
Reasonable if you can work the order. Not 2% of a mid-cap (see AU 1% ADV = {_money(next(x['p01_adv_dollars'] for x in names if x['symbol']=='AU'))}).</li>
</ul>

<h2>Six realistic-aggressive ideas</h2>
<ol class="ideas">
<li><strong>1% + dollar ceiling</strong> — stay 1% until the dollar lid. Aggressive lid = $50k. At $250k this is still $2,500; the ceiling only binds after equity &gt; Rmax / 0.01.</li>
<li><strong>1% + ADV cap</strong> — never more than p × ADV20 shares. p=1% is aggressive but usually tradeable; 10% moves the tape; his $9M is ~0.1%.</li>
<li><strong>Book-level 1%</strong> — total open risk ≤ 1% (2–5% aggressive) of equity, split across names. Stops 15 × 1%.</li>
<li><strong>Sqrt / step-up</strong> — full 1% until $1M, then grow like √E (or 0.5% / 0.25% steps) so $10M does not take $100k/name.</li>
<li><strong>Liquidity-tier notional</strong> — mega $5–10M, mid / small = 1% ADV. Aggressive mega matches his MSFT ballpark if ADV supports it.</li>
<li><strong>Three lids</strong> — 1% risk + 10% name notional + ADV. Mention only; do not run a 3-knob shop.</li>
</ol>

<div class="table-wrap">
<p class="small">Each row is one freeze. $6M is the frozen-as-of class (actual {_money(FROZEN_ASOF)}). MSFT ADV lines use on-disk ATR20 as the example stop distance — illustration, not a live stop. Click headers to sort.</p>
<table class="sortable">
<thead><tr>{idea_head}</tr></thead>
<tbody>
{''.join(idea_body)}
</tbody>
</table>
</div>

<div class="hold">
<h2>One recommended next test — not started</h2>
<p><strong>Recipe:</strong> <code>risk = min(0.01 × BOM Closed-only equity, $50k)</code>
<strong>and</strong> <code>shares ≤ 1% × ADV20</code>.</p>
<p>That pair is the aggressive-realistic one: still $2,500 at $250k, still growing through the
low millions, $50k/name once the account is past $5M, and MSFT cannot become a $500M line at $1B
AUM (1% ADV caps notional near {_money(msft['p01_adv_dollars'])}; his $9M is the tighter 0.1% cousin).
It would have stopped $5T. It is <em>not</em> a cheap overlay on the frozen $2,500 book
(ADV almost never binds at $2,500; the 1% path is a different 16-year compound).
<strong>Pick the ceiling first: $10k (more timid, closer to frozen) vs $50k (aggressive).</strong>
Do not retune on Out-of-Sample. Not gold. Not DailyRun.</p>
</div>

<div class="warn">
<p><strong>Not run tonight.</strong> No new 16-year wallet. No DailyRun wire.
10% name cap + frozen $2,500 remains a later yes/no from the frozen stamp — separate from this menu.</p>
</div>

<h2>Sources</h2>
<ul class="sources">
{''.join(f'<li>{_esc(s)}</li>' for s in sources)}
</ul>
{SORTABLE_JS}
</body></html>
"""


def run() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fund = _fundamentals()
    syms = list(SYMBOLS)
    for s in OPTIONAL:
        if _daily_path(s).exists():
            syms.append(s)
    names = [_measure(s, fund) for s in syms]
    facts = {
        "stamp": STAMP,
        "asof": ASOF.isoformat(),
        "frozen_asof": FROZEN_ASOF,
        "spy_asof": FROZEN_SPY,
        "uncapped_asof": UNCAPPED_ASOF,
        "published_10pct": PUB_TEN_ASOF,
        "fundamentals_errors": {k: fund[k] for k in fund if k.startswith("_")},
        "names": names,
        "recommended": "risk=min(0.01*E, 50000) AND shares<=0.01*ADV20; pick $10k vs $50k; not started",
        "not_gold": True,
        "dailyrun": False,
    }
    (OUT_DIR / "facts.json").write_text(json.dumps(facts, indent=2, default=str), encoding="utf-8")
    now = datetime.now(tz=ET)
    html = build_html(facts, now)
    (OUT_DIR / "compare.html").write_text(html, encoding="utf-8")
    write_baseline(facts)
    print(f"wrote {OUT_DIR / 'compare.html'}", flush=True)
    print(f"wrote {OUT_DIR / 'BASELINE.md'}", flush=True)
    msft = names[0]
    print(
        f"MSFT close={msft['close']:.2f} ADV20={msft['adv20_shares']:.0f} "
        f"ADV$={msft['adv20_dollars']:.0f} denom={msft.get('share_denom')} "
        f"ADV/denom={msft.get('adv_vs_denom_pct')}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
