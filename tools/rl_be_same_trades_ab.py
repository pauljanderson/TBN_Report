#!/usr/bin/env python3
"""Apples-to-apples RL Trail-1 BE overlay on one Closed stamp.

Does NOT re-run the engine, universe, or allocation. Replays local (or Yahoo)
OHLC on the exact Closed rows and classifies every trade:

  saved_loser   — original PnL < 0, armed, later tagged entry → BE (PO's 45 / ~$200k)
  cut_winner    — original PnL > 0, armed, later tagged entry → BE (giveback)
  armed_kept    — armed but never came back to entry; original exit kept
  never_armed   — MFE never reached the arm %
  missing_ohlc  — no bars; original exit kept

PO question: for the 14% test, keep the same 549 trades from RL_Closed_260814183604
and show whether saved losers are cancelled by winners that would have been
stopped at breakeven.

Usage:
  python tools/rl_be_same_trades_ab.py
  python tools/rl_be_same_trades_ab.py --closed drive/RL_Closed_260814183604.csv
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
DATA_DIR = ROOT / "data" / "newdata" / "data"
STAMP = "260814183604"
DEFAULT_CLOSED = [
    DRIVE / f"RL_Closed_{STAMP}.csv",
    DRIVE / "RL_LatestRun_Closed.csv",
    ROOT / "Drive" / f"RL_Closed_{STAMP}.csv",
    ROOT / "Drive" / "RL_LatestRun_Closed.csv",
]
RL_CASH = 47_500.0
IS_CUT = date(2024, 1, 1)
YAHOO_ALIAS = {"BRK.B": "BRK-B", "BF.B": "BF-B", "OCANF": "OGC"}

ARMS = [
    {"pct": 0.10, "key": "pct10", "label": "10% (reference)"},
    {"pct": 0.14, "key": "pct14", "label": "14% (PO historical)"},
    {"pct": 0.20, "key": "pct20", "label": "20% (wider)"},
]


def format_money(n: float) -> str:
    sign = "-" if n < 0 else ""
    return f"{sign}${abs(n):,.2f}"


def format_money_delta(n: float) -> str:
    sign = "+" if n >= 0 else "-"
    return f"{sign}${abs(n):,.2f}"


def _f(v: Any, default: float = 0.0) -> float:
    if v is None or v == "":
        return default
    s = str(v).strip().replace("%", "").replace(",", "").replace("$", "")
    if not s:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _parse_d(s: Any) -> Optional[date]:
    s = str(s or "").strip()
    if not s:
        return None
    compact = s.replace("-", "").replace("/", "")[:8]
    for cand, fmt in ((s[:10], "%Y-%m-%d"), (compact, "%Y%m%d"), (s[:10], "%m/%d/%Y")):
        try:
            return datetime.strptime(cand, fmt).date()
        except ValueError:
            continue
    return None


def _row_get(row: dict, *names: str) -> str:
    for n in names:
        if n in row and row[n] not in (None, ""):
            return str(row[n]).strip()
        for k, v in row.items():
            if str(k).strip() == n and v not in (None, ""):
                return str(v).strip()
    return ""


def max_gain_frac(raw: Any) -> float:
    """MAX GAIN is stored as a fraction (0.14 = 14%). Accept 14 as percent."""
    x = _f(raw)
    if abs(x) > 2.0:
        return x / 100.0
    return x


def load_closed(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _parse_d(_row_get(raw, "DATE OPENED", "DATE_OPENED"))
            closed = _parse_d(_row_get(raw, "DATE CLOSED", "DATE_CLOSED"))
            entry = _f(_row_get(raw, "ENTRY PRICE", "ENTRY_PRICE"))
            exit_px = _f(_row_get(raw, "EXIT PRICE", "EXIT_PRICE"))
            pnl = _f(_row_get(raw, "PNL %", "PNL_PCT"))
            days = _f(_row_get(raw, "DAYS HELD", "DAYS_HELD"))
            pnl_d = _f(_row_get(raw, "PNL_DOLLARS"))
            if pnl_d == 0.0 and pnl != 0.0:
                pnl_d = RL_CASH * pnl / 100.0
            elif abs(pnl_d) > 1e-9 and abs(pnl) < 1e-9:
                pnl = pnl_d / RL_CASH * 100.0
            sym = _row_get(raw, "SYMBOL").upper()
            if not sym or opened is None or closed is None or entry <= 0:
                continue
            rows.append(
                {
                    "sym": sym,
                    "opened": opened,
                    "closed": closed,
                    "entry": entry,
                    "exit_px": exit_px,
                    "pnl": pnl,
                    "days": days,
                    "pnl_d": pnl_d,
                    "exit": _row_get(raw, "EXIT TYPE", "EXIT_TYPE") or "UNKNOWN",
                    "orig_exit": _row_get(raw, "EXIT TYPE", "EXIT_TYPE") or "UNKNOWN",
                    "max_gain": max_gain_frac(_row_get(raw, "MAX GAIN", "MAX_GAIN")),
                    "max_price": _f(_row_get(raw, "MAX PRICE", "MAX_PRICE")),
                    "min_price": _f(_row_get(raw, "MIN PRICE", "MIN_PRICE")),
                    "days_to_10": _f(_row_get(raw, "DAYS_TO_10")),
                    "days_to_20": _f(_row_get(raw, "DAYS_TO_20")),
                }
            )
    return rows


_ohlc_cache: dict[str, Optional[pd.DataFrame]] = {}
_yahoo_batch: dict[str, Optional[pd.DataFrame]] = {}


def load_ohlc_csv(sym: str) -> Optional[pd.DataFrame]:
    path = DATA_DIR / f"{sym}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, usecols=lambda c: str(c).lower() in {"date", "open", "high", "low", "close"})
    cols = {str(c).lower(): c for c in df.columns}
    df = df.rename(
        columns={
            cols["date"]: "Date",
            cols["open"]: "Open",
            cols["high"]: "High",
            cols["low"]: "Low",
            cols["close"]: "Close",
        }
    )
    df["Date"] = pd.to_datetime(df["Date"]).dt.date
    df = df.sort_values("Date").drop_duplicates("Date")
    return df.set_index("Date")[["Open", "High", "Low", "Close"]].astype(float)


def prefetch_yahoo(symbols: list[str]) -> None:
    """One Yahoo batch, unadjusted (matches pygetallMore auto_adjust=False)."""
    missing = [s for s in symbols if load_ohlc_csv(s) is None]
    if not missing:
        print("[RL-BE] all OHLC present locally", flush=True)
        return
    try:
        import yfinance as yf
    except ImportError:
        print(f"[RL-BE] yfinance missing; {len(missing)} symbols have no local OHLC", flush=True)
        return
    ymap = {s: YAHOO_ALIAS.get(s, s) for s in sorted(set(missing))}
    ytickers = list(dict.fromkeys(ymap.values()))
    print(f"[RL-BE] Yahoo prefetch {len(ytickers)} symbols (auto_adjust=False) ...", flush=True)
    data = yf.download(
        ytickers,
        start="2010-01-01",
        end=datetime.now().strftime("%Y-%m-%d"),
        group_by="ticker",
        threads=True,
        auto_adjust=False,
        progress=False,
    )
    inv = {}
    for loc, y in ymap.items():
        inv.setdefault(y, []).append(loc)

    def _one(frame: pd.DataFrame) -> Optional[pd.DataFrame]:
        if frame is None or frame.empty:
            return None
        cols = {str(c).lower(): c for c in frame.columns}
        need = ("open", "high", "low", "close")
        if not all(k in cols for k in need):
            return None
        out = frame.rename(
            columns={
                cols["open"]: "Open",
                cols["high"]: "High",
                cols["low"]: "Low",
                cols["close"]: "Close",
            }
        )[["Open", "High", "Low", "Close"]].dropna()
        out.index = pd.to_datetime(out.index).date
        return out.sort_index()

    if isinstance(data.columns, pd.MultiIndex):
        for y in ytickers:
            try:
                frame = data[y]
            except KeyError:
                frame = None
            parsed = _one(frame) if frame is not None else None
            for loc in inv.get(y, []):
                _yahoo_batch[loc] = parsed
    else:
        parsed = _one(data)
        for loc in missing:
            _yahoo_batch[loc] = parsed
    got = sum(1 for s in missing if _yahoo_batch.get(s) is not None)
    print(f"[RL-BE] Yahoo filled {got}/{len(missing)}", flush=True)


def load_ohlc(sym: str) -> Optional[pd.DataFrame]:
    if sym in _ohlc_cache:
        return _ohlc_cache[sym]
    df = load_ohlc_csv(sym)
    if df is None:
        df = _yahoo_batch.get(sym)
    _ohlc_cache[sym] = df
    return df


def replay_be_pct(trade: dict[str, Any], ohlc: pd.DataFrame, pct: float) -> dict[str, Any]:
    """Arm on first High >= entry*(1+pct); subsequent Low/Open through entry → BE.

    Fill bar arms only (no BE that session). Never extends past original close.
    """
    entry = float(trade["entry"])
    arm_px = entry * (1.0 + float(pct))
    be = entry
    opened = trade["opened"]
    closed = trade["closed"]
    try:
        window = ohlc.loc[opened:closed]
    except Exception:
        return {**trade, "be_hit": False, "missing_bars": True, "armed": False, "bucket": "missing_ohlc"}
    if window.empty:
        return {**trade, "be_hit": False, "missing_bars": True, "armed": False, "bucket": "missing_ohlc"}
    dates = list(window.index)
    armed = False
    for i, d in enumerate(dates):
        o = float(window.loc[d, "Open"])
        h = float(window.loc[d, "High"])
        lo = float(window.loc[d, "Low"])
        if i == 0:
            if h >= arm_px:
                armed = True
            continue
        if (not armed) and h >= arm_px:
            armed = True
        if not armed:
            continue
        if o <= be:
            pnl = (o - entry) / entry * 100.0
            days = max((d - opened).days, 1)
            if abs(trade["pnl"]) > 1e-9:
                notional = trade["pnl_d"] / (trade["pnl"] / 100.0)
                pnl_d = notional * pnl / 100.0
            else:
                pnl_d = 0.0
            return _finish_be(trade, pnl, pnl_d, days, o, d, gap=True)
        if lo <= be:
            days = max((d - opened).days, 1)
            return _finish_be(trade, 0.0, 0.0, days, be, d, gap=False)
    bucket = "armed_kept" if armed else "never_armed"
    return {**trade, "be_hit": False, "missing_bars": False, "armed": armed, "bucket": bucket}


def _finish_be(trade: dict, pnl: float, pnl_d: float, days: float, exit_px: float, d: date, gap: bool) -> dict:
    orig = float(trade["pnl"])
    if orig < -1e-9:
        bucket = "saved_loser"
    elif orig > 1e-9:
        bucket = "cut_winner"
    else:
        bucket = "armed_kept"
    return {
        **trade,
        "pnl": pnl,
        "pnl_d": pnl_d,
        "days": float(days),
        "exit": "TRAIL_BE_GAP" if gap else "TRAIL_BE",
        "exit_px": exit_px,
        "be_date": d,
        "be_hit": True,
        "missing_bars": False,
        "armed": True,
        "bucket": bucket,
        "orig_pnl": orig,
        "orig_pnl_d": float(trade["pnl_d"]),
        "delta_pnl_d": pnl_d - float(trade["pnl_d"]),
    }


def apply_arm(ctrl: list[dict[str, Any]], pct: float) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in ctrl:
        df = load_ohlc(t["sym"])
        if df is None:
            out.append({**t, "be_hit": False, "missing_bars": True, "armed": False, "bucket": "missing_ohlc"})
            continue
        row = replay_be_pct(t, df, pct)
        if "orig_pnl" not in row:
            row["orig_pnl"] = t["pnl"]
            row["orig_pnl_d"] = t["pnl_d"]
            row["delta_pnl_d"] = float(row["pnl_d"]) - float(t["pnl_d"])
        out.append(row)
    return out


def book_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(trades)
    pnls = [float(t["pnl"]) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    pnl_d = sum(float(t["pnl_d"]) for t in trades)
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "wr": 100.0 * len(wins) / n if n else 0.0,
        "avg_pnl": (sum(pnls) / n) if n else 0.0,
        "avg_win": (sum(wins) / len(wins)) if wins else 0.0,
        "avg_loss": (sum(losses) / len(losses)) if losses else 0.0,
        "pf": (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0),
        "pnl_d": pnl_d,
        "avg_days": (sum(float(t["days"]) for t in trades) / n) if n else 0.0,
        "exits": dict(Counter(str(t.get("exit")) for t in trades)),
        "be_n": sum(1 for t in trades if t.get("be_hit")),
    }


def classify_max_gain(ctrl: list[dict[str, Any]], pct: float) -> dict[str, Any]:
    """Closed-file only: MAX GAIN >= pct and original loser. No OHLC / sequence."""
    armed = [t for t in ctrl if t["max_gain"] >= pct - 1e-9]
    losers = [t for t in armed if t["pnl"] < -1e-9]
    winners = [t for t in armed if t["pnl"] > 1e-9]
    return {
        "armed_n": len(armed),
        "loser_n": len(losers),
        "loser_pnl_d": sum(t["pnl_d"] for t in losers),
        "winner_n": len(winners),
        "winner_pnl_d": sum(t["pnl_d"] for t in winners),
        "losers": losers,
        "winners": winners,
    }


def buckets(trades: list[dict[str, Any]]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {
        "saved_loser": [],
        "cut_winner": [],
        "armed_kept": [],
        "never_armed": [],
        "missing_ohlc": [],
    }
    for t in trades:
        out.setdefault(str(t.get("bucket", "never_armed")), []).append(t)
    return out


def resolve_closed(explicit: Optional[Path]) -> Path:
    if explicit is not None:
        p = Path(explicit)
        if not p.is_file():
            raise FileNotFoundError(p)
        return p
    for p in DEFAULT_CLOSED:
        if p.is_file():
            return p
    raise FileNotFoundError(
        "Need RL_Closed_260814183604.csv (gitignored). "
        "Pass --closed PATH or copy it to drive/RL_Closed_260814183604.csv"
    )


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def trade_table(rows: list[dict], caption: str) -> str:
    headers = [
        ("Symbol", "text"),
        ("Opened", "date"),
        ("Closed", "date"),
        ("Entry", "num"),
        ("Orig exit", "text"),
        ("Orig PnL %", "num"),
        ("Orig PnL $", "num"),
        ("MAX GAIN", "num"),
        ("BE exit", "text"),
        ("New PnL $", "num"),
        ("Δ PnL $", "num"),
    ]
    th = "".join(sortable_th(a, b) for a, b in headers)
    body = []
    for t in sorted(rows, key=lambda r: abs(float(r.get("delta_pnl_d", -r["pnl_d"]))), reverse=True):
        body.append(
            "<tr>"
            + "".join(
                f"<td>{c}</td>"
                for c in (
                    html_mod.escape(t["sym"]),
                    str(t["opened"]),
                    str(t["closed"]),
                    f"{t['entry']:.2f}",
                    html_mod.escape(str(t.get("orig_exit", t.get("exit", "")))),
                    f"{t.get('orig_pnl', t['pnl']):.2f}%",
                    format_money(float(t.get("orig_pnl_d", t["pnl_d"]))),
                    f"{100.0 * t['max_gain']:.1f}%",
                    html_mod.escape(str(t.get("exit", "—")) if t.get("be_hit") else "—"),
                    format_money(float(t["pnl_d"])),
                    format_money_delta(float(t.get("delta_pnl_d", 0.0))),
                )
            )
            + "</tr>"
        )
    if not body:
        body.append('<tr><td colspan="11">None</td></tr>')
    return (
        f'<table class="sortable"><caption>{html_mod.escape(caption)}</caption>'
        f"<thead><tr>{th}</tr></thead><tbody>{''.join(body)}</tbody></table>"
    )


def write_html(
    closed_path: Path,
    ctrl: list[dict],
    results: list[dict],
    out_dir: Path,
    mg: dict[str, dict],
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ctrl_m = book_stats(ctrl)
    r14 = next(r for r in results if r["key"] == "pct14")
    b14 = r14["buckets"]
    saved = b14["saved_loser"]
    cut = b14["cut_winner"]
    saved_d = -sum(float(t.get("orig_pnl_d", t["pnl_d"])) for t in saved)
    cut_d = sum(float(t.get("orig_pnl_d", t["pnl_d"])) for t in cut)
    net_d = r14["m"]["pnl_d"] - ctrl_m["pnl_d"]
    mg14 = mg["pct14"]

    def arm_row(r: dict) -> str:
        m = r["m"]
        b = r["buckets"]
        s = b["saved_loser"]
        c = b["cut_winner"]
        s_d = -sum(float(t.get("orig_pnl_d", 0.0)) for t in s)
        c_d = sum(float(t.get("orig_pnl_d", 0.0)) for t in c)
        return (
            "<tr>"
            + "".join(
                f"<td>{x}</td>"
                for x in (
                    html_mod.escape(r["label"]),
                    str(m["n"]),
                    f"{m['wr']:.1f}%",
                    f"{m['avg_pnl']:.2f}%",
                    f"{m['pf']:.2f}",
                    format_money(m["pnl_d"]),
                    str(m["be_n"]),
                    f"{len(s)} / {format_money(s_d)} saved",
                    f"{len(c)} / {format_money(c_d)} given back",
                    format_money_delta(m["pnl_d"] - ctrl_m["pnl_d"]),
                    f"{len(b['armed_kept'])} armed kept · {len(b['never_armed'])} never armed · "
                    f"{len(b['missing_ohlc'])} missing OHLC",
                )
            )
            + "</tr>"
        )

    headers = [
        ("Arm", "text"),
        ("N", "num"),
        ("Win%", "num"),
        ("Avg PnL%", "num"),
        ("PF", "num"),
        ("Total PnL $", "num"),
        ("BE hits", "num"),
        ("Saved losers", "text"),
        ("Cut winners", "text"),
        ("Net Δ $ vs control", "num"),
        ("Other", "text"),
    ]
    th = "".join(sortable_th(a, b) for a, b in headers)
    ctrl_row = (
        "<tr>"
        + "".join(
            f"<td>{x}</td>"
            for x in (
                "control (no BE, same 549)",
                str(ctrl_m["n"]),
                f"{ctrl_m['wr']:.1f}%",
                f"{ctrl_m['avg_pnl']:.2f}%",
                f"{ctrl_m['pf']:.2f}",
                format_money(ctrl_m["pnl_d"]),
                "0",
                "—",
                "—",
                "—",
                html_mod.escape(str(dict(Counter(t["exit"] for t in ctrl)))),
            )
        )
        + "</tr>"
    )

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<title>RL same-trade BE overlay — {STAMP}</title>
<style>
:root {{ --bg:#f7f6f2; --ink:#1c1b19; --muted:#5a574f; --line:#d4d0c4; --fill:#f0eee6; --accent:#2a4a5c; }}
body {{ margin:0; font-family:"Segoe UI",Georgia,serif; font-size:15px; color:var(--ink); background:var(--bg); }}
.wrap {{ max-width:1280px; margin:0 auto; padding:32px 20px 64px; }}
h1 {{ font-size:1.55rem; margin:0 0 8px; }}
h2 {{ font-size:1.12rem; margin:28px 0 10px; border-bottom:1px solid var(--line); padding-bottom:4px; }}
.muted {{ color:var(--muted); font-size:0.9rem; }}
.callout {{ background:#e8eef2; border-left:4px solid var(--accent); padding:12px 14px; margin:14px 0; }}
.callout.warn {{ background:#f7efe0; border-left-color:#8a5a12; }}
.table-wrap {{ overflow-x:auto; margin:8px 0 16px; }}
table.sortable {{ border-collapse:collapse; width:100%; font-size:13px; }}
th, td {{ border:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top; }}
thead th {{ background:var(--fill); }}
th.sortable-th{{cursor:pointer;user-select:none;white-space:nowrap}}
caption {{ text-align:left; font-size:0.82rem; color:var(--muted); caption-side:top; margin:0 0 6px; }}
code {{ background:var(--fill); padding:0.08em 0.3em; font-size:0.86em; }}
</style></head><body>
<div class="wrap">
<p class="muted">Twin Beacon Networks · RL · same-trade overlay · not a new backtest · not DailyRun</p>
<h1>RL breakeven — same 549 trades as <code>RL_Closed_{STAMP}</code></h1>
<p>Control book: <code>{html_mod.escape(str(closed_path))}</code> · N={ctrl_m["n"]} ·
Win% {ctrl_m["wr"]:.1f} · Avg PnL {ctrl_m["avg_pnl"]:.2f}% · PF {ctrl_m["pf"]:.2f} ·
{format_money(ctrl_m["pnl_d"])}.</p>
<div class="callout"><strong>Did we keep the same trades?</strong> Yes. This is an OHLC overlay on the
Closed stamp. Entries, size ($47,500), and the trade list do not change. Early BE exits do
<strong>not</strong> free a slot for a replacement fill — that is the apples-to-apples the PO asked for.
A full engine re-run with trail on <em>would</em> change later trades via allocation; that is out of scope here.</div>
<div class="callout warn"><strong>14% vs PO note (45 losers / ~$200k):</strong>
Closed MAX GAIN ≥ 14% and original loser = <strong>{mg14["loser_n"]}</strong> trades totaling
<strong>{format_money(mg14["loser_pnl_d"])}</strong> (this is the “could have been avoided” bucket; no OHLC needed).
OHLC replay that actually tags entry after arming: <strong>{len(saved)}</strong> saved losers,
avoided <strong>{format_money(saved_d)}</strong>.
Winners that had already hit 14% then came back through entry:
<strong>{len(cut)}</strong> trades that give back <strong>{format_money(cut_d)}</strong>.
<strong>Net Δ vs control: {format_money_delta(net_d)}</strong>.
They do not have to cancel — the table below is the measured offset.</div>

<h2>Full book (N fixed)</h2>
<div class="table-wrap"><table class="sortable"><caption>Click headers to sort. N must match control.</caption>
<thead><tr>{th}</tr></thead><tbody>{ctrl_row}{''.join(arm_row(r) for r in results)}</tbody></table></div>

<h2>14% — saved losers (PO bucket)</h2>
<p class="muted">Original losers whose High reached entry×1.14, then a later bar tagged entry.
PnL goes to 0 (or the gap open if it opened through entry). Sorted by |Δ $|.</p>
<div class="table-wrap">{trade_table(saved, f"{len(saved)} saved losers")}</div>

<h2>14% — winners stopped at breakeven (the offset)</h2>
<p class="muted">Original winners that also tagged entry after arming. These are the trades the PO
expected would not fully cancel the saved losers.</p>
<div class="table-wrap">{trade_table(cut, f"{len(cut)} cut winners")}</div>

<h2>MAX GAIN closed-file check (no OHLC)</h2>
<p class="muted">If MAX GAIN is populated, this is what a spreadsheet count of “hit 14% then lost”
sees. Sequence (arm then later BE) still needs OHLC for winners.</p>
<ul>
<li>10%: armed {mg["pct10"]["armed_n"]}, losers {mg["pct10"]["loser_n"]} totaling {format_money(mg["pct10"]["loser_pnl_d"])}</li>
<li>14%: armed {mg["pct14"]["armed_n"]}, losers {mg["pct14"]["loser_n"]} totaling {format_money(mg["pct14"]["loser_pnl_d"])}</li>
<li>20%: armed {mg["pct20"]["armed_n"]}, losers {mg["pct20"]["loser_n"]} totaling {format_money(mg["pct20"]["loser_pnl_d"])}</li>
</ul>
<p class="muted">Generated by <code>tools/rl_be_same_trades_ab.py</code>.</p>
</div>
</body></html>
"""
    path = out_dir / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_csvs(results: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    fields = [
        "sym", "opened", "closed", "entry", "orig_pnl", "orig_pnl_d", "max_gain",
        "bucket", "be_hit", "pnl", "pnl_d", "delta_pnl_d", "exit", "be_date",
    ]
    for r in results:
        path = out_dir / f"{r['key']}_trades.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for t in r["trades"]:
                row = dict(t)
                row["opened"] = str(t["opened"])
                row["closed"] = str(t["closed"])
                row["be_date"] = str(t.get("be_date", ""))
                w.writerow(row)


def main() -> int:
    ap = argparse.ArgumentParser(description="Same-trade RL BE overlay (10/14/20%)")
    ap.add_argument("--closed", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=DRIVE / "paul_experiments" / f"rl_be_same_trades_{STAMP}")
    args = ap.parse_args()
    try:
        closed = resolve_closed(args.closed)
    except FileNotFoundError as e:
        print(f"[RL-BE] {e}", file=sys.stderr)
        return 2
    print(f"[RL-BE] loading {closed} ...", flush=True)
    ctrl = load_closed(closed)
    print(f"[RL-BE] N={len(ctrl)}", flush=True)
    if not ctrl:
        print("[RL-BE] empty Closed file", file=sys.stderr)
        return 2
    mg = {a["key"]: classify_max_gain(ctrl, a["pct"]) for a in ARMS}
    for a in ARMS:
        c = mg[a["key"]]
        print(
            f"  MAX GAIN {a['label']}: armed={c['armed_n']} "
            f"losers={c['loser_n']} {c['loser_pnl_d']:+,.0f}",
            flush=True,
        )
    prefetch_yahoo([t["sym"] for t in ctrl])
    results = []
    for arm in ARMS:
        trades = apply_arm(ctrl, arm["pct"])
        b = buckets(trades)
        m = book_stats(trades)
        saved_d = -sum(float(t.get("orig_pnl_d", 0.0)) for t in b["saved_loser"])
        cut_d = sum(float(t.get("orig_pnl_d", 0.0)) for t in b["cut_winner"])
        net = m["pnl_d"] - book_stats(ctrl)["pnl_d"]
        rec = {**arm, "trades": trades, "buckets": b, "m": m}
        results.append(rec)
        print(
            f"  OHLC {arm['label']}: BE={m['be_n']} WR={m['wr']:.1f} Avg={m['avg_pnl']:.2f} "
            f"saved={len(b['saved_loser'])}/{saved_d:,.0f} "
            f"cut={len(b['cut_winner'])}/{cut_d:,.0f} netΔ={net:+,.0f}",
            flush=True,
        )
    html_path = write_html(closed, ctrl, results, args.out, mg)
    write_csvs(results, args.out)
    print(f"[RL-BE] wrote {html_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
