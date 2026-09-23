#!/usr/bin/env python3
"""Reconstruct Paul's live booked drawdown, May 20 – Sep 17 2026.

Research analysis only. Not a new system. Not gold. Does not change DailyRun sizing.
Writes drive/paul_experiments/live_drawdown_20260917/{BASELINE.md, report.html, compare.html}.
"""
from __future__ import annotations

import html as html_mod
import json
import subprocess
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
OUT = DRIVE / "paul_experiments" / "live_drawdown_20260917"
DOWNLOADS = Path(r"C:\Users\songg\Downloads")

WINDOW_START = date(2026, 5, 20)
ASOF = date(2026, 9, 17)
ASSUMED_START_EQ = 500_000.0
ASSUMED_END_EQ = 250_000.0

HOUSE_SLOTS = {
    "BRT": 47_500.0,
    "RL": 47_500.0,
    "YH": 47_500.0,
    "MTS": 47_500.0,
    "WPBR": 47_500.0,
    "RS": 47_500.0,
    "SB": 47_500.0,
    "IND": 47_500.0,
    "VZ": 45_000.0,
    "RSI": 10_000.0,
    "CS": 47_500.0,
    "MVCP": 47_500.0,
}

SYS_LONG = {
    "BRT": "Break and ReTest (BRT)",
    "RL": "Rocket Launcher (RL)",
    "YH": "Year High (YH)",
    "MTS": "Magic Touch (MTS)",
    "WPBR": "Weekly Pivot Break and Retest (WPBR)",
    "RS": "Relative Strength vs SPY (RS)",
    "SB": "StockBee (SB)",
    "VZ": "Volume Zone (VZ)",
    "RSI": "Relative Strength Index (RSI)",
    "IND": "Indicators (IND, deprecated)",
    "CS": "CAN SLIM (CS)",
    "MVCP": "Minervini Volatility Contraction Pattern (MVCP)",
}

MEGA = {
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "GOOG", "META", "TSLA", "AVGO", "TSM",
    "LLY", "JPM", "V", "UNH", "XOM", "MA", "WMT", "ORCL", "HD", "COST", "NFLX",
    "AMD", "CRM", "ADBE", "ACN", "QCOM", "INTC", "IBM", "PLTR", "BABA", "SHOP",
    "ASML", "TSM", "AMAT", "KLAC", "LRCX", "AVGO",
}

# Rough GICS-ish buckets for names that showed up in the live book.
SECTOR = {
    "F": "Consumer", "FEIM": "Tech", "HPQ": "Tech", "ADI": "Semis", "FSLR": "Energy",
    "GNRC": "Industrials", "CLF": "Materials", "HBM": "Materials", "YETI": "Consumer",
    "AEHR": "Semis", "CLS": "Tech", "EXTR": "Tech", "SANM": "Tech", "VSXY": "Unknown",
    "AOSL": "Semis", "FTRE": "Health", "PPTA": "Materials", "AMH": "REIT", "HLT": "Consumer",
    "BABA": "Comm", "AMKR": "Semis", "BDGIF": "Unknown", "ACN": "Tech", "AKAM": "Tech",
    "APLD": "Tech", "FHI": "Financials", "KFY": "Financials", "MRVL": "Semis", "ESS": "REIT",
    "INTC": "Semis", "MPWR": "Semis", "COHR": "Tech", "FRT": "REIT", "STLD": "Materials",
    "MTSI": "Semis", "SMTOY": "Industrials", "BEP": "Energy", "CRM": "Tech", "EME": "Industrials",
    "ENPH": "Energy", "EVR": "Financials", "TEAM": "Tech", "VLO": "Energy", "ATEYY": "Semis",
    "LUMN": "Comm", "PLTR": "Tech", "QCOM": "Semis", "MAKO": "Health", "AU": "Materials",
    "LYV": "Comm", "CRUS": "Semis", "FLEX": "Tech", "SHOP": "Tech", "TER": "Semis",
    "TECK": "Materials", "STX": "Tech", "TSLA": "Consumer", "META": "Comm", "KLAC": "Semis",
    "LRCX": "Semis", "BLBD": "Industrials", "CBOE": "Financials", "TWLO": "Tech", "UNM": "Financials",
    "CSGP": "REIT", "PTC": "Tech", "SE": "Comm", "TOELY": "Semis", "CIB": "Financials",
    "MOH": "Health", "FIX": "Industrials", "CENX": "Materials", "REAL": "Consumer",
    "BELFA": "Tech", "GHM": "Industrials", "JBL": "Tech", "LITE": "Tech", "DY": "Industrials",
    "LLY": "Health", "EFX": "Financials", "CCJ": "Energy", "DCO": "Industrials",
    "ENVA": "Financials", "FTAI": "Industrials", "POWL": "Industrials", "SENEA": "Consumer",
    "MSTR": "Financials", "ANET": "Tech", "PDEX": "Health", "CNM": "Industrials",
    "CECO": "Industrials", "CVNA": "Consumer", "TKO": "Comm", "GFI": "Materials",
    "APA": "Energy", "DKL": "Energy", "FTI": "Energy", "MTDR": "Energy", "TGB": "Materials",
    "TPC": "Industrials", "TSM": "Semis",
}


def _d(v) -> Optional[date]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    s = str(v).strip()
    if not s or s.lower() in ("nan", "none", ""):
        return None
    digits = s.replace(".0", "")
    if digits.isdigit() and len(digits) == 8:
        try:
            return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
        except ValueError:
            return None
    ts = pd.to_datetime(v, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.date()


def _f(v, default=0.0) -> float:
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _esc(s: Any) -> str:
    return html_mod.escape("" if s is None else str(s))


def _money(x: float) -> str:
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.0f}"


def _money2(x: float) -> str:
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.2f}"


def _pct(x: float) -> str:
    return f"{x:+.1f}%"


def _cls(x: float) -> str:
    return "pos" if x >= 0 else "neg"


def _th(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{typ}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{_esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _size_bucket(pv: float) -> str:
    if pv < 12_000:
        return "starter (~$7.5–10k)"
    if pv < 35_000:
        return "reduced (~$20–25k)"
    if pv < 60_000:
        return "house-ish (~$45–52k)"
    return "jumbo ($75–100k)"


def _cap_bucket(sym: str) -> str:
    return "mega-cap" if str(sym).upper() in MEGA else "mid/small"


SORT_JS = """
<script>
(function () {
  var MONTHS = {
    january:1, february:2, march:3, april:4, may:5, june:6,
    july:7, august:8, september:9, october:10, november:11, december:12
  };
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : 0;
    if (type === "text") return s.toUpperCase();
    if (type === "month") {
      var key = s.toLowerCase().split(/\\s/)[0];
      return MONTHS[key] || 0;
    }
    if (type === "date") {
      var iso = s.match(/(\\d{4})-(\\d{2})-(\\d{2})/);
      if (iso) return parseInt(iso[1] + iso[2] + iso[3], 10);
      var mdy = s.match(/(\\d{1,2})\\/(\\d{1,2})\\/(\\d{4})/);
      if (mdy) return parseInt(mdy[3] + mdy[1].padStart(2, "0") + mdy[2].padStart(2, "0"), 10);
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

CSS = """
* { box-sizing: border-box; }
body { font-family: Arial, Helvetica, sans-serif; color:#0f172a; margin:24px; max-width:1180px; }
h1 { margin-bottom:4px; font-size:clamp(1.25rem, 4vw, 1.7rem); }
h2 { font-size:1.15rem; margin-top:28px; }
h3 { font-size:1rem; margin:16px 0 8px; color:#334155; }
.sub { color:#64748b; margin-bottom:16px; line-height:1.5; font-size:0.95rem; }
.callout { background:#eef2ff; border:1px solid #c7d2fe; border-radius:12px; padding:14px 16px; margin:16px 0 22px; }
.callout h2 { margin-top:0; }
.callout p { margin:8px 0; line-height:1.5; }
.ask { background:#fff7ed; border-color:#fdba74; }
.cards { display:flex; flex-wrap:wrap; gap:12px; margin:16px 0 24px; }
.card { background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:14px 16px; min-width:180px; flex:1 1 200px; }
.card h3 { margin:0 0 8px; font-size:13px; color:#475569; font-weight:700; }
.metric { font-size:1.35rem; font-weight:700; line-height:1.2; }
.small { font-size:12px; color:#64748b; line-height:1.45; }
.pos { color:#16a34a; } .neg { color:#dc2626; }
.table-wrap { overflow-x:auto; margin:8px 0 20px; -webkit-overflow-scrolling:touch; }
table { border-collapse:collapse; font-size:12px; width:100%; min-width:640px; }
th, td { border:1px solid #e2e8f0; padding:7px 8px; text-align:left; vertical-align:top; }
th { background:#f1f5f9; }
th.sortable-th { cursor:pointer; user-select:none; white-space:nowrap; }
th.sortable-th:hover { background:#e2e8f0; }
.sort-ind { display:inline-block; width:0.9em; margin-left:4px; color:#94a3b8; font-size:10px; }
th.sort-asc .sort-ind::after { content:"▲"; color:#334155; }
th.sort-desc .sort-ind::after { content:"▼"; color:#334155; }
tr.total-row td { background:#f8fafc; border-top:2px solid #334155; font-weight:700; }
.note { background:#f8fafc; border-left:4px solid #6366f1; padding:10px 14px; margin:12px 0; font-size:13px; line-height:1.5; }
ul { line-height:1.55; }
code { background:#f1f5f9; padding:1px 4px; border-radius:4px; font-size:12px; }
"""


def discover() -> dict[str, Any]:
    info: dict[str, Any] = {
        "accounts": [],
        "history_for_account": [],
        "positions": [],
        "statements": [],
        "mobile": [],
        "mobile_archive": [],
        "engine_closed": {},
        "investment_html": [],
        "notes": [],
    }
    if DOWNLOADS.exists():
        for pat in ("Accounts_History*.csv", "*Accounts_History*.csv"):
            info["accounts"].extend(sorted(DOWNLOADS.glob(pat), key=lambda p: p.stat().st_mtime, reverse=True))
        info["history_for_account"] = sorted(
            DOWNLOADS.glob("History_for_Account*.csv"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        for pat in ("Portfolio_Positions*.csv", "*Positions*.csv", "*Account_Balance*", "*balances*"):
            info["positions"].extend(list(DOWNLOADS.glob(pat)))
        for pat in ("*statement*", "*Statement*", "*eDelivery*"):
            info["statements"].extend(list(DOWNLOADS.glob(pat)))
    inbox = DRIVE / "mobile_inbox"
    if inbox.exists():
        info["mobile"] = list(inbox.glob("mobile_trades*.csv"))
        arch = inbox / "archive"
        if arch.exists():
            info["mobile_archive"] = sorted(arch.glob("mobile_trades_done_*.csv"), reverse=True)[:20]
    for pfx in ("BRT", "RL", "YH", "MTS", "WPBR", "RS", "SB", "VZ", "RSI", "IND"):
        latest = DRIVE / f"{pfx}_LatestRun_Closed.csv"
        if latest.exists():
            info["engine_closed"][pfx] = latest
        else:
            cands = sorted(DRIVE.glob(f"{pfx}_Closed_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
            if cands:
                info["engine_closed"][pfx] = cands[0]
    # Also RL often mirrored as BRT_Closed_RL_*
    rl_mirrors = sorted(DRIVE.glob("BRT_Closed_RL_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if rl_mirrors and "RL" not in info["engine_closed"]:
        info["engine_closed"]["RL"] = rl_mirrors[0]
    for folder in (DRIVE, DRIVE / "paul_experiments", ROOT / "docs"):
        if folder.exists():
            info["investment_html"].extend(list(folder.glob("*nvestment*.html")))
            info["investment_html"].extend(list(folder.glob("*Investment*.html")))
    return info


def load_closed() -> pd.DataFrame:
    p = ROOT / "closed_positions_log.csv"
    df = pd.read_csv(p)
    df.columns = [c.strip().lower() for c in df.columns]
    df["buy_date"] = pd.to_datetime(df["buy_date"]).dt.date
    df["sell_date"] = pd.to_datetime(df["sell_date"]).dt.date
    for c in ("buy_price", "sell_price", "qty", "pnl_pct", "pnl_dollars", "original_qty", "purchase_value"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["system"] = df["system"].astype(str).str.upper().str.strip()
    df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
    df["purchase_value"] = df["purchase_value"].fillna(df["qty"] * df["buy_price"])
    df["source"] = "closed_positions_log"
    df["status"] = "closed"
    df["note"] = ""
    # Dedup exact (symbol, buy, sell, qty) — PPTA logged twice with 9¢ sell difference.
    df["_dupkey"] = (
        df["symbol"]
        + "|"
        + df["buy_date"].astype(str)
        + "|"
        + df["sell_date"].astype(str)
        + "|"
        + df["qty"].round(2).astype(str)
    )
    before = len(df)
    # Keep first recorded for identical keys (the 07-01 PPTA, drop 07-01 09:28 twin).
    df = df.sort_values(["recorded_at", "symbol"]).drop_duplicates("_dupkey", keep="first")
    dropped = before - len(df)
    if dropped:
        df.attrs["dedup_dropped"] = dropped
    df = df.drop(columns=["_dupkey"])
    # SMTOY: two lots same buy/sell dates, different qty/price — keep both, flag.
    sm = df["symbol"].eq("SMTOY")
    if sm.sum() > 1:
        df.loc[sm, "note"] = "Same symbol/window, two lots (possible split/ADR adjust). Both kept."
    return df.reset_index(drop=True)


def load_open() -> pd.DataFrame:
    pos = pd.read_csv(ROOT / "gettarget_positions.csv")
    pos.columns = [c.strip() for c in pos.columns]
    pos["symbol"] = pos["symbol"].astype(str).str.upper().str.strip()
    pos["system"] = pos["system"].astype(str).str.upper().str.strip()
    pos["purchase_date"] = pd.to_datetime(pos["purchase_date"]).dt.date
    pos["entry_price"] = pd.to_numeric(pos["entry_price"], errors="coerce")
    gt = pd.read_csv(ROOT / "getTarget_output.csv")
    gt.columns = [c.strip() for c in gt.columns]
    gt["Symbol"] = gt["Symbol"].astype(str).str.upper().str.strip()
    cur = {}
    for _, r in gt.iterrows():
        cur[str(r["Symbol"])] = {
            "current": _f(r.get("CurrentPrice")),
            "asof": str(r.get("AsOfDate") or r.get("AsOfUsed") or ""),
        }
    rows = []
    for _, r in pos.iterrows():
        info = cur.get(r["symbol"], {})
        rows.append(
            {
                "symbol": r["symbol"],
                "system": r["system"],
                "buy_date": r["purchase_date"],
                "buy_price": _f(r["entry_price"]),
                "sell_date": None,
                "sell_price": info.get("current"),
                "qty": None,
                "pnl_pct": None,
                "pnl_dollars": None,
                "purchase_value": None,
                "current_price": info.get("current"),
                "asof": info.get("asof"),
                "source": "gettarget_positions + getTarget_output",
                "status": "open",
                "note": "Qty not on gettarget_positions; filled from Fidelity if found.",
            }
        )
    return pd.DataFrame(rows)


def _norm_fidelity_cols(df: pd.DataFrame) -> pd.DataFrame:
    rename = {}
    for c in df.columns:
        k = str(c).strip().lower()
        if k in ("run date", "rundate", "date"):
            rename[c] = "run_date"
        elif k in ("action",):
            rename[c] = "action"
        elif k in ("symbol",):
            rename[c] = "symbol"
        elif k in ("quantity", "qty"):
            rename[c] = "qty"
        elif k in ("price",):
            rename[c] = "price"
        elif k in ("amount",):
            rename[c] = "amount"
        elif k in ("description",):
            rename[c] = "description"
        elif k in ("account", "account number"):
            rename[c] = "account"
    return df.rename(columns=rename)


def load_fidelity(paths: list[Path]) -> tuple[pd.DataFrame, list[str]]:
    notes = []
    frames = []
    seen = set()
    for p in paths[:24]:
        key = p.resolve()
        if key in seen:
            continue
        seen.add(key)
        try:
            raw = pd.read_csv(p)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Could not read {p.name}: {exc}")
            continue
        df = _norm_fidelity_cols(raw)
        if "run_date" not in df.columns or "action" not in df.columns:
            notes.append(f"{p.name}: not a Fidelity trade export (cols={list(raw.columns)[:8]})")
            continue
        df["_src"] = p.name
        frames.append(df)
        notes.append(f"Loaded {p.name} ({len(df)} rows, mtime {datetime.fromtimestamp(p.stat().st_mtime):%Y-%m-%d})")
    if not frames:
        return pd.DataFrame(), notes
    out = pd.concat(frames, ignore_index=True)
    if "account" in out.columns:
        acct = out["account"]
        if isinstance(acct, pd.DataFrame):
            acct = acct.iloc[:, 0]
        keep = acct.astype(str).str.contains("Individual", case=False, na=False)
        dropped = int((~keep).sum())
        out = out.loc[keep].copy()
        notes.append(f"Kept Individual-* rows only ({dropped} other-account rows dropped, e.g. COLLETTE TRAVEL).")
    if "symbol" in out.columns:
        out["symbol"] = out["symbol"].astype(str).str.upper().str.strip()
    def _series(frame: pd.DataFrame, name: str) -> Optional[pd.Series]:
        if name not in frame.columns:
            return None
        col = frame[name]
        return col.iloc[:, 0] if isinstance(col, pd.DataFrame) else col

    rd = _series(out, "run_date")
    if rd is not None:
        out["run_date"] = pd.to_datetime(rd, errors="coerce").dt.date
    qty_s = _series(out, "qty")
    if qty_s is not None:
        out["qty"] = pd.to_numeric(qty_s.astype(str).str.replace(",", ""), errors="coerce")
    px_s = _series(out, "price")
    if px_s is not None:
        out["price"] = pd.to_numeric(px_s.astype(str).str.replace("$", "").str.replace(",", ""), errors="coerce")
    if "amount" in out.columns:
        amt = out["amount"]
        if isinstance(amt, pd.DataFrame):
            amt = amt.iloc[:, 0]
        out["amount"] = pd.to_numeric(
            amt.astype(str).str.replace("$", "").str.replace(",", "").str.replace("(", "-").str.replace(")", ""),
            errors="coerce",
        )
    # Overlapping Fidelity re-downloads repeat the same YOU BOUGHT row.
    dedup_cols = [c for c in ("run_date", "action", "symbol", "qty", "price", "amount") if c in out.columns]
    before = len(out)
    if dedup_cols:
        out = out.drop_duplicates(dedup_cols, keep="first")
        notes.append(f"Deduped Fidelity rows {before} → {len(out)} on {dedup_cols}.")
    return out, notes


def attach_open_qty(opens: pd.DataFrame, fid: pd.DataFrame) -> pd.DataFrame:
    if opens.empty:
        return opens
    opens = opens.copy()
    if fid.empty or "action" not in fid.columns:
        return opens
    act = fid["action"].astype(str).str.upper()
    buys = fid[act.str.contains("YOU BOUGHT|BOUGHT", regex=True, na=False)].copy()
    for i, r in opens.iterrows():
        sub = buys[buys["symbol"] == r["symbol"]] if "symbol" in buys.columns else buys.iloc[0:0]
        if sub.empty:
            continue
        # Prefer same buy date
        same = sub[sub["run_date"] == r["buy_date"]] if "run_date" in sub.columns else sub.iloc[0:0]
        if same.empty:
            continue
        qty = float(same["qty"].abs().sum()) if "qty" in same.columns else None
        if qty and qty > 0:
            opens.at[i, "qty"] = qty
            px = _f(r["buy_price"])
            opens.at[i, "purchase_value"] = qty * px
            cur = _f(r.get("current_price"), px)
            opens.at[i, "pnl_dollars"] = (cur - px) * qty
            opens.at[i, "pnl_pct"] = ((cur / px) - 1.0) * 100 if px else 0.0
            opens.at[i, "note"] = f"Qty from Fidelity YOU BOUGHT on {r['buy_date']} ({same.iloc[0].get('_src', '')})"
    # Fallback: house slot if still missing qty
    for i, r in opens.iterrows():
        if r.get("qty") and _f(r.get("qty")) > 0:
            continue
        slot = HOUSE_SLOTS.get(str(r["system"]), 20_000.0)
        px = _f(r["buy_price"])
        if px <= 0:
            continue
        qty = slot / px
        opens.at[i, "qty"] = qty
        opens.at[i, "purchase_value"] = slot
        cur = _f(r.get("current_price"), px)
        opens.at[i, "pnl_dollars"] = (cur - px) * qty
        opens.at[i, "pnl_pct"] = ((cur / px) - 1.0) * 100 if px else 0.0
        opens.at[i, "note"] = f"Qty estimated from house slot ${_f(slot):,.0f} (no Fidelity lot)."
        opens.at[i, "qty_estimated"] = True
    return opens


def load_mobile(paths: list[Path]) -> pd.DataFrame:
    frames = []
    for p in paths:
        try:
            df = pd.read_csv(p)
        except Exception:
            continue
        df.columns = [c.strip().lower() for c in df.columns]
        df["_src"] = p.name
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def load_engine_closed(engine_map: dict[str, Path]) -> pd.DataFrame:
    frames = []
    for pfx, path in engine_map.items():
        try:
            df = pd.read_csv(path)
        except Exception:
            continue
        cols = {c.lower(): c for c in df.columns}
        def col(*names):
            want = {n.lower().replace(" ", "_") for n in names}
            for raw, orig in cols.items():
                key = raw.lower().replace(" ", "_")
                if key in want:
                    return orig
            return None
        tcol = col("TICKER", "SYMBOL")
        ocol = col("DATE_OPENED", "DATE OPENED", "ENTRY_DATE")
        ccol = col("DATE_CLOSED", "DATE CLOSED", "EXIT_DATE")
        pcol = col("PNL_PCT", "PNL %")
        dcol = col("PNL_DOLLARS", "PNL_DOLLARS")
        ecol = col("ENTRY_PRICE", "ENTRY PRICE")
        xcol = col("EXIT_PRICE", "EXIT PRICE")
        scol = col("SHARES", "QTY")
        if not tcol or not ocol:
            continue
        pct = df[pcol] if pcol else None
        if pct is not None:
            pct = pd.to_numeric(
                pct.astype(str).str.replace("%", "", regex=False), errors="coerce"
            )
        out = pd.DataFrame(
            {
                "symbol": df[tcol].astype(str).str.upper().str.strip(),
                "system": pfx,
                "buy_date": df[ocol].map(_d),
                "sell_date": df[ccol].map(_d) if ccol else None,
                "buy_price": pd.to_numeric(df[ecol], errors="coerce") if ecol else None,
                "sell_price": pd.to_numeric(df[xcol], errors="coerce") if xcol else None,
                "pnl_pct": pct,
                "pnl_dollars_house": pd.to_numeric(
                    df[dcol].astype(str).str.replace("$", "", regex=False).str.replace(",", "", regex=False),
                    errors="coerce",
                )
                if dcol
                else None,
                "shares_house": pd.to_numeric(df[scol], errors="coerce") if scol else None,
                "engine_file": path.name,
            }
        )
        frames.append(out)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def in_window(d: Optional[date], start=WINDOW_START, end=ASOF) -> bool:
    return d is not None and start <= d <= end


def enrich(closed: pd.DataFrame) -> pd.DataFrame:
    df = closed.copy()
    df["days_held"] = [
        (s - b).days if s and b else None for b, s in zip(df["buy_date"], df["sell_date"])
    ]
    df["house_slot"] = df["system"].map(HOUSE_SLOTS).fillna(47_500.0)
    df["slot_mult"] = df["purchase_value"] / df["house_slot"]
    df["size_bucket"] = df["purchase_value"].map(_size_bucket)
    df["cap_bucket"] = df["symbol"].map(_cap_bucket)
    df["sector"] = df["symbol"].map(lambda s: SECTOR.get(s, "Unknown"))
    df["win"] = df["pnl_dollars"] > 0
    # Window: closed or opened in live window (include pre-window entries that closed after go-live)
    df["in_live_window"] = [
        in_window(sd) or in_window(bd) for bd, sd in zip(df["buy_date"], df["sell_date"])
    ]
    return df


def realized_path(closed: pd.DataFrame, start_eq: float) -> pd.DataFrame:
    """Cash equity using realized PnL on sell dates. No mark-to-market."""
    ev = closed.groupby("sell_date", as_index=False)["pnl_dollars"].sum().sort_values("sell_date")
    eq = start_eq
    peak = start_eq
    rows = []
    for _, r in ev.iterrows():
        eq += float(r["pnl_dollars"])
        if eq > peak:
            peak = eq
        dd = eq - peak
        dd_pct = (dd / peak * 100.0) if peak else 0.0
        rows.append(
            {
                "date": r["sell_date"],
                "day_pnl": float(r["pnl_dollars"]),
                "equity": eq,
                "peak": peak,
                "dd": dd,
                "dd_pct": dd_pct,
            }
        )
    return pd.DataFrame(rows)


def concurrent_notional(closed: pd.DataFrame, opens: pd.DataFrame) -> pd.DataFrame:
    """Overlap lots: open on [buy_date, sell_date). Sell-date notional is already gone."""
    lots: list[tuple[date, Optional[date], float, str]] = []
    for _, r in closed.iterrows():
        bd, sd = r["buy_date"], r["sell_date"]
        pv = _f(r.get("purchase_value"))
        if not bd or pv <= 0:
            continue
        lots.append((bd, sd, pv, str(r["symbol"])))
    for _, r in opens.iterrows():
        bd = r["buy_date"]
        pv = _f(r.get("purchase_value"))
        if not bd or pv <= 0:
            continue
        lots.append((bd, None, pv, str(r["symbol"])))
    if not lots:
        return pd.DataFrame()
    start = min(b for b, _, _, _ in lots)
    days = []
    d = start
    while d <= ASOF:
        live = [(pv, sym) for b, s, pv, sym in lots if b <= d and (s is None or d < s)]
        days.append(
            {
                "date": d,
                "n_open": len(live),
                "notional": float(sum(pv for pv, _ in live)),
                "names": ",".join(sorted({sym for _, sym in live}))[:180],
            }
        )
        d += timedelta(days=1)
    return pd.DataFrame(days)


def weekly_clusters(closed: pd.DataFrame) -> pd.DataFrame:
    df = closed.copy()
    df["week"] = pd.to_datetime(df["sell_date"]).dt.to_period("W-FRI").astype(str)
    g = df.groupby("week").agg(
        n=("symbol", "count"),
        pnl=("pnl_dollars", "sum"),
        wins=("win", "sum"),
        purchase=("purchase_value", "sum"),
        losers=("pnl_dollars", lambda s: int((s < 0).sum())),
    ).reset_index()
    return g.sort_values("week")


def monthly_path(closed: pd.DataFrame) -> pd.DataFrame:
    df = closed.copy()
    df["month"] = pd.to_datetime(df["sell_date"]).dt.to_period("M").astype(str)
    g = df.groupby(["month", "system"]).agg(
        n=("symbol", "count"),
        pnl=("pnl_dollars", "sum"),
        wr=("win", "mean"),
        avg_pv=("purchase_value", "mean"),
    ).reset_index()
    tot = df.groupby("month").agg(n=("symbol", "count"), pnl=("pnl_dollars", "sum")).reset_index()
    tot["system"] = "ALL"
    tot["wr"] = df.groupby("month")["win"].mean().values
    tot["avg_pv"] = df.groupby("month")["purchase_value"].mean().values
    return pd.concat([g, tot], ignore_index=True).sort_values(["month", "system"])


def git_system_notes() -> list[str]:
    notes = [
        "Volume Zone (VZ) official DailyRun sleeve 2026-09-07: Paul78.142 + EXIT_atr4_s025_r15_ts20 "
        "(Average True Range / ATR 4% floor at trigger close; zone.lo − 0.25 ATR; 1.5R; 20-bar time stop). "
        "One-position-per-symbol lock 2026-09-15 — no pyramids.",
        "Relative Strength Index (RSI) house freeze: overbought 70 / oversold 30 / exit 70 / max trigger 60 / "
        "min ATR% 2.93 / time stop 20 / roll-from-max 8 (next open). ATR 2.93 adopted 2026-09-16; "
        "roll-8 adopt stamp rsi_roll_ab_20260916. A 7.18 distance-from-52-week-high wire was tried and reverted.",
        "Indicators (IND) is deprecated and excluded from getTarget scheduled targets. "
        "Minervini Volatility Contraction Pattern (MVCP) retired 2026-08-21 from DailyRun.",
        "These September wires cannot explain May–July jumbo losses. They can explain later paper vs live "
        "divergence (paper books now include RSI / VZ rules he did not have in May).",
        "Fidelity YOU BOUGHT rows in the Individual account are marked Margin — that is how ~$980k notional "
        "could sit on a ~$500k account.",
        "$500k + realized ≈ $308k vs Paul’s “now ~$250k”. Gap ~$58k: no statement CSV, Fidelity history is a "
        "rolling window (no large wire found in the files we have), open mark only −$1.7k. Could be an "
        "unlogged withdrawal, fees/margin interest, a start that was not exactly $500k, or a rounded current balance.",
    ]
    try:
        r = subprocess.run(
            [
                "git",
                "log",
                "--since=2026-05-20",
                "--until=2026-09-18",
                "--oneline",
                "--",
                "DailyRun.bat",
                "run_rsi.bat",
                "run_vz.bat",
                "getTarget.py",
                "generate_investment_report.py",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
        )
        lines = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
        if lines:
            notes.append("Git touches on DailyRun / getTarget / RSI / VZ since May 20 (newest first):")
            notes.extend(f"  - {ln}" for ln in lines[:25])
        else:
            notes.append("git log on DailyRun/getTarget/RSI/VZ since May 20 returned no commits (or git unavailable).")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"git log skipped: {exc}")
    return notes


def match_paper(live: pd.DataFrame, engine: pd.DataFrame) -> dict[str, Any]:
    if engine.empty:
        return {"ok": False, "reason": "No engine Closed CSVs found under drive/."}
    eng = engine[
        engine["buy_date"].apply(lambda d: d is not None and WINDOW_START <= d <= ASOF)
    ].copy()
    live_keys = set(zip(live["symbol"], live["buy_date"]))
    # Allow ±1 day match (next-open fill vs buy date)
    def near(sym, bd):
        if bd is None:
            return False
        for delta in (0, -1, 1, -2, 2):
            if (sym, bd + timedelta(days=delta)) in live_keys:
                return True
        return False

    eng["taken_live"] = [near(s, d) for s, d in zip(eng["symbol"], eng["buy_date"])]
    live2 = live.copy()
    eng_keys = set(zip(eng["symbol"], eng["buy_date"]))

    def live_in_eng(sym, bd):
        if bd is None:
            return False
        for delta in (0, -1, 1, -2, 2):
            if (sym, bd + timedelta(days=delta)) in eng_keys:
                return True
        return False

    live2["in_engine"] = [live_in_eng(s, d) for s, d in zip(live2["symbol"], live2["buy_date"])]
    return {
        "ok": True,
        "engine_n": int(len(eng)),
        "engine_taken": int(eng["taken_live"].sum()),
        "engine_not_taken": int((~eng["taken_live"]).sum()),
        "live_n": int(len(live2)),
        "live_in_engine": int(live2["in_engine"].sum()),
        "live_not_in_engine": int((~live2["in_engine"]).sum()),
        "live_extras": live2[~live2["in_engine"]].copy(),
        "engine_missed": eng[~eng["taken_live"]].copy(),
        "eng": eng,
        "live": live2,
    }


def fidelity_cash_moves(fid: pd.DataFrame) -> pd.DataFrame:
    if fid.empty or "action" not in fid.columns:
        return pd.DataFrame()
    act = fid["action"].astype(str)
    mask = act.str.contains(
        "Transferred|ELECTRONIC FUNDS TRANSFER|WIRE|JOURNAL|CONTRIBUTION|WITHDRAW|DEPOSIT",
        case=False,
        na=False,
    )
    cols = [c for c in ("run_date", "action", "amount", "description", "account", "_src") if c in fid.columns]
    return fid.loc[mask, cols].copy()


def html_table(headers: list[tuple[str, str]], rows: list[list[Any]], footer: Optional[list[Any]] = None) -> str:
    head = "".join(_th(h, t) for h, t in headers)
    body = []
    for r in rows:
        tds = "".join(f"<td>{c}</td>" for c in r)
        body.append(f"<tr>{tds}</tr>")
    foot = ""
    if footer:
        foot = '<tr class="total-row">' + "".join(f"<td>{c}</td>" for c in footer) + "</tr>"
    return (
        f'<table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(body)}{foot}</tbody></table>"
    )


def money_cell(x: float) -> str:
    return f'<span class="{_cls(x)}">{_money(x)}</span>'


def build_pages(ctx: dict[str, Any]) -> tuple[str, str, str]:
    closed: pd.DataFrame = ctx["closed"]
    opens: pd.DataFrame = ctx["opens"]
    path: pd.DataFrame = ctx["path"]
    conc: pd.DataFrame = ctx["conc"]
    monthly: pd.DataFrame = ctx["monthly"]
    weekly: pd.DataFrame = ctx["weekly"]
    paper = ctx["paper"]
    git_notes = ctx["git_notes"]
    sources = ctx["sources"]
    fid_notes = ctx["fid_notes"]
    cash_moves: pd.DataFrame = ctx["cash_moves"]
    unreal = ctx["unreal"]
    realized = ctx["realized"]
    start_eq = ctx["start_eq"]
    end_recon = ctx["end_recon"]
    peak_row = ctx["peak_row"]
    trough_row = ctx["trough_row"]
    turn_row = ctx["turn_row"]
    peak_conc = ctx["peak_conc"]
    jumbo_conc = ctx.get("jumbo_conc")

    # --- tables ---
    trade_rows = []
    for _, r in closed.sort_values("sell_date").iterrows():
        trade_rows.append(
            [
                _esc(r["symbol"]),
                _esc(r["system"]),
                r["buy_date"],
                r["sell_date"],
                r["days_held"],
                _money2(_f(r["buy_price"])),
                _money2(_f(r["sell_price"])),
                f"{_f(r['qty']):,.0f}",
                _money(_f(r["purchase_value"])),
                f"{_f(r['slot_mult']):.2f}×",
                _esc(r["size_bucket"]),
                f"{_f(r['pnl_pct']):+.2f}%",
                money_cell(_f(r["pnl_dollars"])),
                _esc(r["sector"]),
                _esc(r["cap_bucket"]),
                _esc(r.get("note") or ""),
            ]
        )
    trades_tbl = html_table(
        [
            ("Symbol", "text"),
            ("System", "text"),
            ("Buy", "date"),
            ("Sell", "date"),
            ("Days", "num"),
            ("Buy $", "num"),
            ("Sell $", "num"),
            ("Qty", "num"),
            ("Notional", "num"),
            ("vs house slot", "num"),
            ("Size era", "text"),
            ("PnL %", "num"),
            ("PnL $", "num"),
            ("Sector", "text"),
            ("Cap", "text"),
            ("Note", "text"),
        ],
        trade_rows,
        [
            f"{len(closed)} closed",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            _money(closed["purchase_value"].sum()),
            "",
            "",
            "",
            money_cell(realized),
            "",
            "",
            "",
        ],
    )

    losers = closed.nsmallest(20, "pnl_dollars")
    lose_rows = []
    for _, r in losers.iterrows():
        lose_rows.append(
            [
                _esc(r["symbol"]),
                _esc(r["system"]),
                r["buy_date"],
                r["sell_date"],
                _money(_f(r["purchase_value"])),
                f"{_f(r['pnl_pct']):+.1f}%",
                money_cell(_f(r["pnl_dollars"])),
                _esc(r["sector"]),
                _esc(r["size_bucket"]),
            ]
        )
    lose_tbl = html_table(
        [
            ("Symbol", "text"),
            ("System", "text"),
            ("Buy", "date"),
            ("Sell", "date"),
            ("Notional", "num"),
            ("PnL %", "num"),
            ("PnL $", "num"),
            ("Sector", "text"),
            ("Size era", "text"),
        ],
        lose_rows,
    )

    winners = closed.nlargest(10, "pnl_dollars")
    win_rows = [
        [
            _esc(r["symbol"]),
            _esc(r["system"]),
            r["sell_date"],
            _money(_f(r["purchase_value"])),
            f"{_f(r['pnl_pct']):+.1f}%",
            money_cell(_f(r["pnl_dollars"])),
        ]
        for _, r in winners.iterrows()
    ]
    win_tbl = html_table(
        [
            ("Symbol", "text"),
            ("System", "text"),
            ("Sell", "date"),
            ("Notional", "num"),
            ("PnL %", "num"),
            ("PnL $", "num"),
        ],
        win_rows,
    )

    sys = (
        closed.groupby("system")
        .agg(n=("symbol", "count"), pnl=("pnl_dollars", "sum"), wr=("win", "mean"), pv=("purchase_value", "mean"))
        .reset_index()
        .sort_values("pnl")
    )
    sys_rows = [
        [
            _esc(SYS_LONG.get(r["system"], r["system"])),
            int(r["n"]),
            f"{r['wr']*100:.0f}%",
            _money(r["pv"]),
            money_cell(r["pnl"]),
        ]
        for _, r in sys.iterrows()
    ]
    sys_tbl = html_table(
        [("System", "text"), ("N closed", "num"), ("Win %", "num"), ("Avg notional", "num"), ("Realized $", "num")],
        sys_rows,
        ["ALL", len(closed), f"{closed['win'].mean()*100:.0f}%", _money(closed["purchase_value"].mean()), money_cell(realized)],
    )

    mon_all = monthly[monthly["system"] == "ALL"]
    mon_rows = [
        [
            r["month"],
            int(r["n"]),
            f"{r['wr']*100:.0f}%",
            _money(r["avg_pv"]),
            money_cell(r["pnl"]),
        ]
        for _, r in mon_all.iterrows()
    ]
    mon_tbl = html_table(
        [("Month", "month"), ("N closed", "num"), ("Win %", "num"), ("Avg notional", "num"), ("Realized $", "num")],
        mon_rows,
    )

    # monthly by system pivot-ish
    mon_sys_rows = [
        [
            r["month"],
            _esc(r["system"]),
            int(r["n"]),
            f"{r['wr']*100:.0f}%",
            money_cell(r["pnl"]),
        ]
        for _, r in monthly[monthly["system"] != "ALL"].sort_values(["month", "pnl"]).iterrows()
    ]
    mon_sys_tbl = html_table(
        [("Month", "month"), ("System", "text"), ("N", "num"), ("Win %", "num"), ("Realized $", "num")],
        mon_sys_rows,
    )

    wk_rows = [
        [
            r["week"],
            int(r["n"]),
            int(r["losers"]),
            _money(r["purchase"]),
            money_cell(r["pnl"]),
        ]
        for _, r in weekly.iterrows()
    ]
    wk_tbl = html_table(
        [("Week ending Fri", "text"), ("Closed", "num"), ("Losers", "num"), ("Notional closed", "num"), ("PnL $", "num")],
        wk_rows,
    )

    path_rows = [
        [
            r["date"],
            money_cell(r["day_pnl"]),
            _money(r["equity"]),
            _money(r["peak"]),
            money_cell(r["dd"]),
            f"{r['dd_pct']:.1f}%",
        ]
        for _, r in path.iterrows()
    ]
    path_tbl = html_table(
        [
            ("Sell date", "date"),
            ("Day realized", "num"),
            ("Equity (assumed $500k + realized)", "num"),
            ("Peak", "num"),
            ("Drawdown $", "num"),
            ("DD %", "num"),
        ],
        path_rows,
    )

    sec = (
        closed.groupby("sector")
        .agg(n=("symbol", "count"), pnl=("pnl_dollars", "sum"))
        .reset_index()
        .sort_values("pnl")
    )
    sec_tbl = html_table(
        [("Sector (rough)", "text"), ("N", "num"), ("Realized $", "num")],
        [[_esc(r["sector"]), int(r["n"]), money_cell(r["pnl"])] for _, r in sec.iterrows()],
    )
    cap = closed.groupby("cap_bucket").agg(n=("symbol", "count"), pnl=("pnl_dollars", "sum")).reset_index()
    cap_tbl = html_table(
        [("Cap bucket", "text"), ("N", "num"), ("Realized $", "num")],
        [[_esc(r["cap_bucket"]), int(r["n"]), money_cell(r["pnl"])] for _, r in cap.iterrows()],
    )
    era = (
        closed.groupby("size_bucket")
        .agg(n=("symbol", "count"), pnl=("pnl_dollars", "sum"), pv=("purchase_value", "mean"))
        .reset_index()
        .sort_values("pnl")
    )
    era_tbl = html_table(
        [("Size era", "text"), ("N", "num"), ("Avg notional", "num"), ("Realized $", "num")],
        [[_esc(r["size_bucket"]), int(r["n"]), _money(r["pv"]), money_cell(r["pnl"])] for _, r in era.iterrows()],
    )

    open_rows = []
    for _, r in opens.iterrows():
        open_rows.append(
            [
                _esc(r["symbol"]),
                _esc(r["system"]),
                r["buy_date"],
                _money2(_f(r["buy_price"])),
                _money2(_f(r.get("current_price"))),
                f"{_f(r.get('qty')):,.0f}" if r.get("qty") else "—",
                _money(_f(r.get("purchase_value"))) if r.get("purchase_value") else "—",
                f"{_f(r.get('pnl_pct')):+.1f}%" if r.get("pnl_pct") is not None else "—",
                money_cell(_f(r.get("pnl_dollars"))) if r.get("pnl_dollars") is not None else "—",
                _esc(r.get("note") or ""),
            ]
        )
    open_tbl = html_table(
        [
            ("Symbol", "text"),
            ("System", "text"),
            ("Buy", "date"),
            ("Entry", "num"),
            ("Current", "num"),
            ("Qty", "num"),
            ("Notional", "num"),
            ("uPnL %", "num"),
            ("uPnL $", "num"),
            ("Note", "text"),
        ],
        open_rows,
        ["Open now", "", "", "", "", "", "", "", money_cell(unreal), ""],
    )

    extras_html = "<p class='small'>Engine Closed files were not found, so paper-vs-live name matching is incomplete.</p>"
    missed_html = extras_html
    paper_cards = ""
    if paper.get("ok"):
        extras = paper.get("live_extras")
        missed = paper.get("engine_missed")
        if extras is None or not isinstance(extras, pd.DataFrame) or extras.empty or "symbol" not in extras.columns:
            extras_html = "<p class='small'>No leftover live lots after ±2-day engine match (or extras table empty).</p>"
        else:
            sort_ex = extras.sort_values("buy_date") if "buy_date" in extras.columns else extras
            ex_rows = [
                [
                    _esc(r["symbol"]),
                    _esc(r["system"]),
                    r.get("buy_date"),
                    r.get("sell_date") or "open",
                    _money(_f(r.get("purchase_value"))),
                    money_cell(_f(r.get("pnl_dollars"))),
                ]
                for _, r in sort_ex.iterrows()
            ]
            extras_html = html_table(
                [("Symbol", "text"), ("System", "text"), ("Buy", "date"), ("Sell", "date"), ("Notional", "num"), ("PnL $", "num")],
                ex_rows[:80],
            )
        if missed is None or not isinstance(missed, pd.DataFrame) or missed.empty or "symbol" not in missed.columns:
            missed_html = "<p class='small'>No unmatched engine fills (or engine Closed lacked a ticker/date column).</p>"
        else:
            sort_ms = missed.sort_values("buy_date") if "buy_date" in missed.columns else missed
            ms_rows = [
                [
                    _esc(r["symbol"]),
                    _esc(r["system"]),
                    r.get("buy_date"),
                    r.get("sell_date") or "open/flat",
                    f"{_f(r.get('pnl_pct')):+.1f}%" if pd.notna(r.get("pnl_pct")) else "—",
                ]
                for _, r in sort_ms.head(80).iterrows()
            ]
            missed_html = html_table(
                [("Symbol", "text"), ("Engine", "text"), ("Signal/open", "date"), ("Engine close", "date"), ("Engine PnL %", "num")],
                ms_rows,
            )
        paper_cards = f"""
        <div class="cards">
          <div class="card"><h3>Engine fills since May 1 (house Closed)</h3><div class="metric">{paper['engine_n']}</div>
            <div class="small">LatestRun / latest Closed under drive/</div></div>
          <div class="card"><h3>Those also in the live book (±2d)</h3><div class="metric">{paper['engine_taken']}</div>
            <div class="small">{paper['engine_not_taken']} engine fills he did not book</div></div>
          <div class="card"><h3>Live closed lots in the window</h3><div class="metric">{paper['live_n']}</div>
            <div class="small">{paper['live_in_engine']} match an engine row · {paper['live_not_in_engine']} look extra / IND / date-skew</div></div>
        </div>
        """

    cash_html = "<p class='small'>No transfer/wire rows parsed from Fidelity exports.</p>"
    if cash_moves is not None and not cash_moves.empty:
        cr = []
        for _, r in cash_moves.iterrows():
            cr.append(
                [
                    r.get("run_date"),
                    _esc(r.get("action")),
                    money_cell(_f(r.get("amount"))) if r.get("amount") is not None else "—",
                    _esc(str(r.get("description") or "")[:80]),
                    _esc(r.get("_src")),
                ]
            )
        cash_html = html_table(
            [("Date", "date"), ("Action", "text"), ("Amount", "num"), ("Description", "text"), ("File", "text")],
            cr[:40],
        )

    src_lis = "".join(f"<li>{_esc(s)}</li>" for s in sources)
    fid_lis = "".join(f"<li>{_esc(s)}</li>" for s in fid_notes) or "<li>No Fidelity export found in Downloads.</li>"
    git_lis = "".join(f"<li>{_esc(s)}</li>" for s in git_notes)

    peak_d = peak_row["date"] if peak_row is not None else "—"
    peak_eq = _money(peak_row["equity"]) if peak_row is not None else "—"
    trough_d = trough_row["date"] if trough_row is not None else "—"
    trough_eq = _money(trough_row["equity"]) if trough_row is not None else "—"
    max_dd = trough_row["dd"] if trough_row is not None else 0
    max_dd_pct = trough_row["dd_pct"] if trough_row is not None else 0
    turn_d = turn_row["date"] if turn_row is not None else "—"
    turn_eq = _money(turn_row["equity"]) if turn_row is not None else "—"
    conc_txt = "n/a"
    if peak_conc is not None:
        conc_txt = (
            f"{peak_conc['date']}: {int(peak_conc['n_open'])} names, "
            f"{_money(peak_conc['notional'])} notional"
        )
    if jumbo_conc is not None and peak_conc is not None:
        if jumbo_conc["date"] != peak_conc["date"]:
            conc_txt += (
                f" · jumbo-era (through 20 Jul) peak {jumbo_conc['date']}: "
                f"{int(jumbo_conc['n_open'])} names, {_money(jumbo_conc['notional'])}"
            )

    asked = (
        "this looks great on paper. can you help me understand something. why have i lost $200k? "
        "i know at first i was being aggressive with my investments and it paid off until it didn't "
        "but can you analyze the trades i took and come up with an analysis of why i have lost so much? "
        "I know we've changed some of the systems. we basically went live toward the end of May"
    )

    layman = (
        "Paper reports pretend every name is a small, one-at-a-time slot. The live book from late May "
        "was the opposite: many full-size (often $75k–$100k) Indicators and Rocket Launcher names at once "
        "on a ~$500k account. Early winners in the last week of May / first days of June were real. "
        "Then a tight cluster of −4% to −14% losers on those jumbo lots — semiconductors and "
        "gold/materials especially — took five-figure bites. Later you cut size toward $20–25k; "
        "those months still leaked, but they are not where the $200k was made. System changes in "
        "September (Volume Zone one-name lock, Relative Strength Index Average True Range 2.93 + roll-8) "
        "came after the damage. We did not find a broker statement CSV with the official $500k → $250k "
        "balances; the closed ledger’s realized dollars are in the same neighborhood as a ~$200k hit "
        "once you allow for still-open marks and any cash you moved."
    )

    causes = f"""
    <ol>
      <li><strong>Size, not a bad single idea.</strong> House dummy slots are about $10k Relative Strength Index (RSI) /
      $45k Volume Zone (VZ) / $47.5k Break and ReTest (BRT) and Rocket Launcher (RL). From 26 May through mid-July
      most live lots were <em>1.6–2.1×</em> that — $75k to $100k a name. A routine −8% stop on a $100k lot is
      −$8k. The same stop on a house $47.5k lot is −$3.8k. Percent looks “normal”; dollars do not.</li>
      <li><strong>Book risk stacked.</strong> Peak concurrent notional we can reconstruct is
      <strong>{conc_txt}</strong>. Paper’s $2,500-per-name overlay warned that 1% × many names open is how a
      $250k account still gets a large drawdown. Live did that with 2%+ of the old $500k per name, several at once.</li>
      <li><strong>The slide starts after the first winning burst, not in September.</strong> Realized equity
      (start assumed $500k) peaked <strong>{peak_d} at {peak_eq}</strong>. The first lasting break is
      <strong>{turn_d}</strong> (equity {turn_eq}). Trough on this realized path:
      <strong>{trough_d} at {trough_eq}</strong> ({_money(max_dd)}, {max_dd_pct:.1f}% from peak). That is
      “it paid off until it didn’t.”</li>
      <li><strong>Indicators (IND, deprecated) + Rocket Launcher (RL) did most of the dollar damage</strong>,
      with a later Relative Strength vs SPY (RS) −12% stop cluster in August on smaller lots. Semis/tech
      and a few materials names (TECK, AU, PPTA, STLD) cluster in the same weeks — not ten unrelated unlucky picks.</li>
      <li><strong>Paper ≠ this book.</strong> Current DailyRun paper skips Indicators, sizes RSI at $10k, and
      (since 15 Sep) will not pyramid Volume Zone. Live took IND at jumbo size, took extra names the engine
      books do not show, and sized far above dummy. September RSI / VZ wires did not cause the May–July hole.</li>
    </ol>
    """

    body = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Live drawdown — why ~$200k (2026-09-17)</title>
<style>{CSS}</style>
</head><body>
<h1>Live booked drawdown — end of May through 17 Sep 2026</h1>
<p class="sub">Research reconstruction of the <strong>real Fidelity / getTarget book</strong>, not the $2,500 paper overlay.
Not a new system. Not gold. Generated {datetime.now():%Y-%m-%d %H:%M}.</p>

<div class="callout ask">
<h2>What you asked</h2>
<p>{_esc(asked)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>{_esc(layman)}</p>
</div>

<div class="cards">
  <div class="card"><h3>Starting equity used</h3><div class="metric">{_money(start_eq)}</div>
    <div class="small">Your figure. No broker statement CSV found with an official May balance.</div></div>
  <div class="card"><h3>Closed realized P&amp;L in window</h3><div class="metric {_cls(realized)}">{_money(realized)}</div>
    <div class="small">{len(closed)} closed lots after dropping 1 duplicate PPTA row. Click headers to sort tables.</div></div>
  <div class="card"><h3>Open mark (est.)</h3><div class="metric {_cls(unreal)}">{_money(unreal)}</div>
    <div class="small">{len(opens)} names on gettarget_positions as of {ASOF}.</div></div>
  <div class="card"><h3>Realized-path ending equity</h3><div class="metric {_cls(end_recon-start_eq)}">{_money(end_recon)}</div>
    <div class="small">$500k + realized only (no deposits, no full mark-to-market). You said ~$250k now.</div></div>
  <div class="card"><h3>Peak after go-live</h3><div class="metric">{peak_eq}</div>
    <div class="small">{peak_d} on realized closes. Then the slide.</div></div>
  <div class="card"><h3>Max realized drawdown</h3><div class="metric neg">{_money(max_dd)}</div>
    <div class="small">{max_dd_pct:.1f}% from peak · trough {trough_d}. Intra-trade marks were likely worse.</div></div>
</div>

<section>
<h2>The five concrete causes</h2>
{causes}
<p class="small">Tone check: aggression is already in the data. The useful part is <em>when</em> and <em>which lots</em> — jumbo Indicators / Rocket Launcher through mid-July — not a lecture about risk in the abstract.</p>
</section>

<section>
<h2>Path — “paid off until it didn’t”</h2>
<p class="small">Cash equity = assumed $500,000 plus <em>realized</em> closed P&amp;L on each sell date. Open marks and cash transfers are not in this curve. Click column headers to sort.</p>
<div class="note">Peak <strong>{peak_d} {peak_eq}</strong> · first lasting break <strong>{turn_d}</strong> · trough <strong>{trough_d} {trough_eq}</strong>.
Concurrent notional peak: <strong>{conc_txt}</strong>. House slot × 1 name is ~$47.5k; several $75–100k names at once is how a $500k account was fully (or over) deployed.</div>
<div class="table-wrap">{path_tbl}</div>
</section>

<section>
<h2>Monthly realized path</h2>
<p class="small">Closed P&amp;L by exit month. Click headers to sort.</p>
<div class="table-wrap">{mon_tbl}</div>
<h3>Same months, by system</h3>
<div class="table-wrap">{mon_sys_tbl}</div>
</section>

<section>
<h2>Weekly clusters</h2>
<p class="small">Exit-week buckets — this is where “one bad week in semis” shows up as a pile of red rows, not a mysterious drip.</p>
<div class="table-wrap">{wk_tbl}</div>
</section>

<section>
<h2>Which systems and names</h2>
<div class="table-wrap">{sys_tbl}</div>
<h3>Top losers (dollar)</h3>
<div class="table-wrap">{lose_tbl}</div>
<h3>Top winners (dollar) — the “it paid off” side</h3>
<div class="table-wrap">{win_tbl}</div>
<h3>Sector / cap / size era</h3>
<div class="table-wrap">{sec_tbl}</div>
<div class="table-wrap">{cap_tbl}</div>
<div class="table-wrap">{era_tbl}</div>
</section>

<section>
<h2>Open book now (not the hole)</h2>
<p class="small">These are small versus the June jumbo book. Unrealized is a mark, not a close.</p>
<div class="table-wrap">{open_tbl}</div>
</section>

<section>
<h2>Paper vs live</h2>
<p class="small">Paper Closed files are engine fills at <em>house dummy</em> dollars (about $47.5k Break and ReTest / Rocket Launcher, $45k Volume Zone, $10k Relative Strength Index). The $2,500 overlay stamp
<code>risk2500_monthly_20260917</code> then resizes those same fills so a stop is ~1% of a $250k account. Neither file is the live book.</p>
{paper_cards}
<h3>Live lots that do not match a current engine Closed row (±2 days)</h3>
<p class="small">Indicators (deprecated) will dominate this list — DailyRun paper no longer runs IND. Date skew and discretionary extras also land here.</p>
<div class="table-wrap">{extras_html}</div>
<h3>Engine fills since May 1 he did not book (first 80)</h3>
<p class="small">Paper can look great because it includes names he never sized, and excludes jumbo IND he did take. This is a match, not a claim he “should have” taken these.</p>
<div class="table-wrap">{missed_html}</div>
</section>

<section>
<h2>System changes since May — what can and cannot explain this</h2>
<ul>{git_lis}</ul>
<p class="small">DailyRun sizing was not changed for this stamp. Do not read this page as a request to rewire slots.</p>
</section>

<section>
<h2>Cash transfers (if Fidelity showed any)</h2>
<p class="small">If $200k left the account as a wire, that is not a trading loss. We looked.</p>
{cash_html}
</section>

<section>
<h2>All live closed trades in the reconstruction</h2>
<p class="small">Source: <code>closed_positions_log.csv</code> (the investment-report permanent ledger), window buy or sell on/after 2026-05-20 through 2026-09-17.
One PPTA Break and ReTest row was a same-qty duplicate and was dropped. Two SMTOY Indicators lots are both kept (possible split/ADR). Click headers to sort.</p>
<div class="table-wrap">{trades_tbl}</div>
</section>

<section>
<h2>Sources and honesty</h2>
<ul class="small">{src_lis}</ul>
<p class="small">Fidelity files:</p>
<ul class="small">{fid_lis}</ul>
<p class="small">We do <strong>not</strong> have a stamped May/September Fidelity statement with official equity. The ~$200k figure is yours; the ledger’s realized sum is the evidence we can check. Intra-trade drawdown on $75–100k lots would make the felt peak-to-trough larger than the realized curve. Research analysis only.</p>
</section>
{SORT_JS}
</body></html>
"""

    compare = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Live vs paper — drawdown compare 2026-09-17</title>
<style>{CSS}</style>
</head><body>
<h1>Live book vs paper books — same window</h1>
<p class="sub">Companion to <a href="report.html">report.html</a>. Not a KEEP/DISMISS adopt. Not gold. Click headers to sort.</p>
<div class="callout ask">
<h2>What you asked</h2>
<p>{_esc(asked)}</p>
</div>
<div class="callout">
<h2>In plain English</h2>
<p>Paper uses one small slot per signal. Live used many large slots at once, including a deprecated Indicators sleeve paper no longer runs. That is the divergence — not a secret September bug in Relative Strength Index.</p>
</div>
<div class="cards">
  <div class="card"><h3>Live realized</h3><div class="metric {_cls(realized)}">{_money(realized)}</div>
    <div class="small">{len(closed)} closed lots · avg notional {_money(closed['purchase_value'].mean())}</div></div>
  <div class="card"><h3>Live win %</h3><div class="metric">{closed['win'].mean()*100:.0f}%</div>
    <div class="small">W {int(closed['win'].sum())} · L {int((~closed['win']).sum())} · PF {_f(ctx['pf']):.2f}</div></div>
  <div class="card"><h3>Avg live notional</h3><div class="metric">{_money(closed['purchase_value'].mean())}</div>
    <div class="small">House BRT/RL dummy $47,500 · RSI $10,000 · VZ $45,000</div></div>
  <div class="card"><h3>Peak concurrent notional</h3><div class="metric">{_money(peak_conc['notional']) if peak_conc is not None else '—'}</div>
    <div class="small">{int(peak_conc['n_open']) if peak_conc is not None else '—'} names on {peak_conc['date'] if peak_conc is not None else '—'}</div></div>
</div>
<h2>By system (live booked)</h2>
<div class="table-wrap">{sys_tbl}</div>
<h2>Size era (this is the paper gap)</h2>
<div class="table-wrap">{era_tbl}</div>
<h2>Monthly live realized</h2>
<div class="table-wrap">{mon_tbl}</div>
{paper_cards}
<h2>Live lots not in current engine Closed</h2>
<div class="table-wrap">{extras_html}</div>
<p class="small">Full narrative and every trade: <a href="report.html">report.html</a>. Freeze notes: <a href="BASELINE.md">BASELINE.md</a>.</p>
{SORT_JS}
</body></html>
"""

    baseline = f"""# BASELINE — live_drawdown_20260917

**Status:** Research analysis of the **booked live account**. **Not a new system. Not gold. Not DailyRun.**

## What you asked

> this looks great on paper. can you help me understand something. why have i lost $200k? i know at first i was being aggressive with my investments and it paid off until it didn't but can you analyze the trades i took and come up with an analysis of why i have lost so much? I know we've changed some of the systems. we basically went live toward the end of May

## In plain English

Paper looks clean because each signal is a small one-name slot. The live book from late May put many $75k–$100k Indicators and Rocket Launcher names on at once. Early winners were real; a June–July cluster of ordinary −8% to −14% stops on those jumbo lots is most of the dollars. September Relative Strength Index / Volume Zone wires came after the hole.

## Window

- Go-live (Paul): **end of May 2026** — we use **2026-05-20 through 2026-09-17** (last week of May through as-of).
- Include closed lots that **bought or sold** in-window (pre-window $7.5k lots that exited after 20 May stay in, labeled starter size).
- Assumed start equity: **$500,000** (Paul). Assumed current: **~$250,000** (Paul).
- No official Fidelity statement CSV with those balances was found. Realized ledger is the check.

## Booked vs engine

| Layer | What it is |
|-------|------------|
| **Booked live** | `closed_positions_log.csv` + `gettarget_positions.csv` + `getTarget_output.csv` (+ Fidelity YOU BOUGHT qty when present) |
| **Engine / paper** | `drive/*_LatestRun_Closed.csv` (or latest `*_Closed_*.csv`) at house dummy dollars |
| **$2500 overlay** | `drive/paul_experiments/risk2500_monthly_20260917/` — same engine fills, resized. **Not this account.** |

Investment report Open/Closed is the same live ledger (`CLOSED_SINCE=2026-05-25` in `generate_investment_report.py`).

## House dummy slots (not changed)

- Relative Strength Index (RSI): **$10,000**
- Volume Zone (VZ): **$45,000**
- Break and ReTest (BRT) / Rocket Launcher (RL) / Year High (YH) / Magic Touch (MTS) / Weekly Pivot Break and Retest (WPBR) / Relative Strength vs SPY (RS) / StockBee (SB): **$47,500**

## Headline numbers (this run)

- Closed lots used: **{len(closed)}** (1 PPTA duplicate dropped)
- Realized P&L: **{realized:,.2f}**
- Open mark (est.): **{unreal:,.2f}**
- Realized-path peak: **{peak_d} {peak_eq}**
- Realized-path trough: **{trough_d} {trough_eq}** (DD {max_dd:,.0f} / {max_dd_pct:.1f}%)
- Turn date (first lasting break after peak): **{turn_d}**
- Peak concurrent notional: **{conc_txt}**

## Dedup / data holes

- PPTA BRT 2026-06-04 / 2026-06-05 qty 3719 logged twice (sell 23.72 vs 23.69). Kept first.
- SMTOY IND 2026-06-25 / 2026-07-02 appears as two lots ($16.48×736 and $74.30×92). Both kept; possible split/ADR.
- Open qty: Fidelity if found, else house-slot estimate (flagged).
- No broker statement → cannot confirm deposits/withdrawals vs trading P&L unless Fidelity action rows exist.
- Realized equity path **understates** felt drawdown (no daily mark-to-market on jumbo opens).

## System change notes (cannot rewrite May–July)

{chr(10).join('- ' + n for n in git_notes)}

## Decision

None. Analysis only. Do not change `DailyRun.bat` sizing from this stamp.

## Outputs

- `report.html` — full Paul-facing reconstruction
- `compare.html` — live vs paper / size-era
- this file
"""
    return body, compare, baseline


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    disc = discover()
    closed_all = load_closed()
    closed = enrich(closed_all)
    closed = closed[closed["in_live_window"]].copy()
    # Prefer sells in window for the "why did I lose" book; keep pre-window buys that closed after 5/20.
    closed = closed[closed["sell_date"].apply(lambda d: d is not None and d >= WINDOW_START)].copy()

    opens = load_open()
    fid_paths = disc["accounts"] + disc["history_for_account"]
    fid, fid_notes = load_fidelity(fid_paths)
    opens = attach_open_qty(opens, fid)
    cash_moves = fidelity_cash_moves(fid)

    mobile_paths = disc["mobile"] + disc["mobile_archive"]
    mobile = load_mobile(mobile_paths)
    if not mobile.empty:
        fid_notes.append(f"Mobile ingest rows: {len(mobile)} from {len(mobile_paths)} file(s).")
    else:
        fid_notes.append("No mobile_trades.csv in drive/mobile_inbox (pending or archive).")

    engine = load_engine_closed(disc["engine_closed"])
    paper = match_paper(pd.concat([closed, opens], ignore_index=True, sort=False), engine)

    realized = float(closed["pnl_dollars"].sum())
    unreal = float(pd.to_numeric(opens.get("pnl_dollars"), errors="coerce").fillna(0).sum()) if not opens.empty else 0.0
    wins = closed.loc[closed["pnl_dollars"] > 0, "pnl_dollars"].sum()
    losses = closed.loc[closed["pnl_dollars"] < 0, "pnl_dollars"].sum()
    pf = (wins / abs(losses)) if losses else float("inf")

    path = realized_path(closed, ASSUMED_START_EQ)
    if path.empty:
        peak_row = trough_row = turn_row = None
        end_recon = ASSUMED_START_EQ + realized
    else:
        peak_idx = int(path["equity"].idxmax())
        peak_row = path.loc[peak_idx]
        after = path.loc[peak_idx:]
        trough_idx = int(after["equity"].idxmin())
        trough_row = path.loc[trough_idx]
        # First day after peak that is ≥$10k below peak and never reclaims the peak.
        turn_row = None
        peak_eq = float(peak_row["equity"])
        for i in range(peak_idx + 1, len(path)):
            if float(path.iloc[i]["equity"]) <= peak_eq - 10_000:
                rest = path.iloc[i:]
                if rest["equity"].max() < peak_eq - 1:
                    turn_row = path.iloc[i]
                    break
        if turn_row is None and len(path) > peak_idx + 1:
            turn_row = path.iloc[peak_idx + 1]
        end_recon = float(path.iloc[-1]["equity"])

    conc = concurrent_notional(closed, opens)
    peak_conc = None
    jumbo_conc = None
    if not conc.empty:
        cwin = conc[(conc["date"] >= WINDOW_START) & (conc["date"] <= ASOF)]
        if not cwin.empty:
            peak_conc = cwin.loc[cwin["notional"].idxmax()]
        jwin = conc[(conc["date"] >= WINDOW_START) & (conc["date"] <= date(2026, 7, 20))]
        if not jwin.empty:
            jumbo_conc = jwin.loc[jwin["notional"].idxmax()]

    monthly = monthly_path(closed)
    weekly = weekly_clusters(closed)
    git_notes = git_system_notes()

    sources = [
        f"closed_positions_log.csv ({len(closed_all)} raw rows; {len(closed)} in sell-window after PPTA dedup)",
        "gettarget_positions.csv (open book)",
        "getTarget_output.csv (marks as of 2026-09-17)",
        "House dummy slots from DailyRun / rocket_rl_config rl_cash=$47,500, run_rsi.bat RSI_SHEET_NOTIONAL=$10,000, VZ sheet ~$45,000",
        "DailyRun.bat comments for VZ lock 2026-09-15, RSI ATR 2.93 + roll-8, IND deprecated, MVCP retired 2026-08-21",
        "drive/paul_experiments/risk2500_monthly_20260917/ (paper $2,500 overlay — not the live book)",
    ]
    if disc["engine_closed"]:
        sources.append(
            "Engine Closed: " + ", ".join(f"{k}={v.name}" for k, v in disc["engine_closed"].items())
        )
    else:
        sources.append("Engine LatestRun Closed: not found under drive/ (paper match incomplete)")
    if disc["investment_html"]:
        sources.append("Investment HTML found: " + ", ".join(p.name for p in disc["investment_html"][:5]))
    if disc["positions"]:
        sources.append("Position/balance-like files: " + ", ".join(p.name for p in disc["positions"][:8]))
    if disc["statements"]:
        sources.append("Statement-like files: " + ", ".join(p.name for p in disc["statements"][:8]))
    else:
        sources.append("No Fidelity statement PDF/CSV with official equity in Downloads (searched *statement*)")

    ctx = {
        "closed": closed,
        "opens": opens,
        "path": path,
        "conc": conc,
        "monthly": monthly,
        "weekly": weekly,
        "paper": paper,
        "git_notes": git_notes,
        "sources": sources,
        "fid_notes": fid_notes,
        "cash_moves": cash_moves,
        "unreal": unreal,
        "realized": realized,
        "start_eq": ASSUMED_START_EQ,
        "end_recon": end_recon,
        "peak_row": peak_row,
        "trough_row": trough_row,
        "turn_row": turn_row,
        "peak_conc": peak_conc,
        "jumbo_conc": jumbo_conc,
        "pf": pf,
    }
    report, compare, baseline = build_pages(ctx)
    (OUT / "report.html").write_text(report, encoding="utf-8")
    (OUT / "compare.html").write_text(compare, encoding="utf-8")
    (OUT / "BASELINE.md").write_text(baseline, encoding="utf-8")

    # Machine-readable summary for the parent agent
    summary = {
        "n_closed": int(len(closed)),
        "realized": realized,
        "unreal": unreal,
        "end_recon": end_recon,
        "peak_date": str(peak_row["date"]) if peak_row is not None else None,
        "peak_eq": float(peak_row["equity"]) if peak_row is not None else None,
        "turn_date": str(turn_row["date"]) if turn_row is not None else None,
        "trough_date": str(trough_row["date"]) if trough_row is not None else None,
        "trough_eq": float(trough_row["equity"]) if trough_row is not None else None,
        "max_dd": float(trough_row["dd"]) if trough_row is not None else None,
        "max_dd_pct": float(trough_row["dd_pct"]) if trough_row is not None else None,
        "peak_conc_date": str(peak_conc["date"]) if peak_conc is not None else None,
        "peak_conc_n": int(peak_conc["n_open"]) if peak_conc is not None else None,
        "peak_conc_notional": float(peak_conc["notional"]) if peak_conc is not None else None,
        "jumbo_conc_date": str(jumbo_conc["date"]) if jumbo_conc is not None else None,
        "jumbo_conc_n": int(jumbo_conc["n_open"]) if jumbo_conc is not None else None,
        "jumbo_conc_notional": float(jumbo_conc["notional"]) if jumbo_conc is not None else None,
        "by_system": {
            str(r["system"]): {"n": int(r["n"]), "pnl": float(r["pnl"])}
            for _, r in closed.groupby("system")
            .agg(n=("symbol", "count"), pnl=("pnl_dollars", "sum"))
            .reset_index()
            .iterrows()
        },
        "top_losers": [
            {
                "symbol": str(r["symbol"]),
                "system": str(r["system"]),
                "sell": str(r["sell_date"]),
                "pv": float(r["purchase_value"]),
                "pnl": float(r["pnl_dollars"]),
                "pct": float(r["pnl_pct"]),
            }
            for _, r in closed.nsmallest(8, "pnl_dollars").iterrows()
        ],
        "top_winners": [
            {
                "symbol": str(r["symbol"]),
                "system": str(r["system"]),
                "sell": str(r["sell_date"]),
                "pnl": float(r["pnl_dollars"]),
            }
            for _, r in closed.nlargest(5, "pnl_dollars").iterrows()
        ],
        "paper_ok": bool(paper.get("ok")),
        "paper": {
            k: paper[k]
            for k in ("engine_n", "engine_taken", "engine_not_taken", "live_n", "live_in_engine", "live_not_in_engine")
            if k in paper
        },
        "fid_notes": fid_notes,
        "engine_files": {k: v.name for k, v in disc["engine_closed"].items()},
        "outputs": [str(OUT / "report.html"), str(OUT / "compare.html"), str(OUT / "BASELINE.md")],
    }
    (OUT / "_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))
    print(f"Wrote {OUT / 'report.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
