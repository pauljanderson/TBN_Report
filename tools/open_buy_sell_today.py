#!/usr/bin/env python3
"""9:30 ET buy/sell page: last night's live gates, checked against today's open.

Sell only when the sell report already has the exit, or today's open is
through the stop. Buy only when a live system passed every gate on the
prior session and today's open is still allowed (inside the entry band
when one is printed, and above the stop). Share counts use the live-style
freeze at the opening price.

Writes docs/open_today.html. With --push, commits and pushes only that file
to origin/main so GitHub Pages can serve it.
"""
from __future__ import annotations

import argparse
import html
import math
import subprocess
import sys
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "stock_analysis"))

import report_page_extras as extras  # noqa: E402
from scanner_open_report_lib import (  # noqa: E402
    ET,
    OPEN_POLL_END_ET,
    OPEN_POLL_INTERVAL_SEC,
    fetch_session_opens_yfinance,
    market_status_message,
)
from live_style_sizing import load_account_state, size_trade  # noqa: E402

DRIVE = ROOT / "drive"
DOCS = ROOT / "docs"
PAGE = DOCS / "open_today.html"
POSITIONS = ROOT / "gettarget_positions.csv"
GETTARGET = ROOT / "getTarget_output.csv"
SELL = DRIVE / "Sell_Report_Latest.csv"
URL = "https://pauljanderson.github.io/TBN_Report/open_today.html"

# A missing Yahoo print is retried this many times, then the page is written anyway.
# Between tries we wait OPEN_POLL_INTERVAL_SEC (the existing 20s poll). Each try
# also has a wall-clock cap so one hung download cannot spin forever.
OPEN_FETCH_ATTEMPTS = 3
OPEN_FETCH_TIMEOUT_SEC = 60

LIVE = {"BRT", "RL", "YH", "MTS", "WPBR", "RS", "SB", "VZ", "RSI", "WRL"}
NAMES = {
    "BRT": "Breakout (BRT)",
    "RL": "Rocket Launcher (RL)",
    "YH": "Yearly High (YH)",
    "MTS": "Magic Touch (MTS)",
    "WPBR": "Weekly Pivot Break and Retest (WPBR)",
    "RS": "Relative Strength (RS)",
    "SB": "StockBee (SB)",
    "VZ": "Volume Zone (VZ)",
    "RSI": "Relative Strength Index (RSI)",
    "WRL": "Weekly Range / Swing (WRL)",
}


def _num(raw) -> float | None:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).strip().replace(",", "").replace("%", "")
    if not s or s.lower() in {"nan", "none", "null"}:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    if v != v:
        return None
    return v


def _ymd(raw) -> date | None:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).strip().replace("-", "")[:8]
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return datetime.strptime(s, "%Y%m%d").date()
    except ValueError:
        return None


def _prior_session(session: date) -> date:
    return (pd.Timestamp(session) - pd.offsets.BDay(1)).date()


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False, low_memory=False)


def _system_from_name(name: str) -> str | None:
    stem = name.split("_LatestRun_")[0].upper()
    return stem if stem in LIVE else None


def load_gettarget_index() -> dict[str, dict]:
    gt = _read_csv(GETTARGET)
    by_sym: dict[str, dict] = {}
    if gt.empty or "Symbol" not in gt.columns:
        return by_sym
    for _, r in gt.iterrows():
        sym = str(r.get("Symbol") or "").strip().upper()
        if not sym:
            continue
        stop = _num(r.get("StopTrailing")) or _num(r.get("StopInitial")) or _num(r.get("LimitPrice"))
        by_sym[sym] = {
            "symbol": sym,
            "system": str(r.get("System") or "").strip().upper(),
            "entry": _num(r.get("EntryPrice")),
            "file_price": _num(r.get("CurrentPrice")),
            "asof": str(r.get("AsOfDate") or ""),
            "stop": stop,
            "target": _num(r.get("TargetPrice")),
        }
    return by_sym


def load_holdings() -> list[dict]:
    pos = _read_csv(POSITIONS)
    by_sym = load_gettarget_index()
    rows = []
    if pos.empty:
        return list(by_sym.values())
    sym_col = "symbol" if "symbol" in pos.columns else "Symbol"
    for _, r in pos.iterrows():
        sym = str(r.get(sym_col) or "").strip().upper()
        if not sym:
            continue
        base = dict(by_sym.get(sym, {"symbol": sym, "system": "", "entry": None, "file_price": None, "asof": "", "stop": None, "target": None}))
        sys_name = str(r.get("system") or r.get("System") or base["system"]).strip().upper()
        if sys_name:
            base["system"] = sys_name
        ent = _num(r.get("entry_price") or r.get("EntryPrice"))
        if ent:
            base["entry"] = ent
        rows.append(base)
    return rows


def load_sells() -> dict[str, dict]:
    df = _read_csv(SELL)
    out: dict[str, dict] = {}
    if df.empty or "Symbol" not in df.columns:
        return out
    for _, r in df.iterrows():
        sym = str(r.get("Symbol") or "").strip().upper()
        if not sym:
            continue
        reason = str(r.get("ExitReason") or "").strip()
        when = str(r.get("SellWhen") or "").strip()
        out[sym] = {
            "reason": f"{reason} {when}".strip(),
            "system": str(r.get("System") or "").strip().upper(),
        }
    return out


def load_candidates() -> tuple[list[dict], list[dict]]:
    """Passed-all-gates rows, and WRL demand-zone watches."""
    passed: list[dict] = []
    waits: list[dict] = []
    for path in sorted(DRIVE.glob("*_LatestRun_Watchlist.csv")):
        system = _system_from_name(path.name)
        if system is None:
            continue
        df = _read_csv(path)
        if df.empty or "SYMBOL" not in df.columns:
            continue
        for _, r in df.iterrows():
            status = str(r.get("STATUS") or "").strip().upper()
            sym = str(r.get("SYMBOL") or "").strip().upper()
            if not sym:
                continue
            row = {
                "symbol": sym,
                "system": system,
                "status": status,
                "signal": _ymd(r.get("ENTRY_DATE") or r.get("AS_OF_DATE") or r.get("ASOF_DATE")),
                "close": _num(r.get("CLOSE") or r.get("LAST_CLOSE")),
                "stop": _num(r.get("STOP_LOSS") or r.get("STOP")),
                "target": _num(r.get("TARGET")),
                "max_entry": _num(r.get("MAX_ENTRY_OPEN")),
                "min_entry": _num(r.get("MIN_ENTRY_OPEN")),
                "too_high_mult": _num(r.get("TOO_HIGH_MULTIPLIER")) or 0.0,
                "range_low": _num(r.get("RANGE_LOW")),
                "swing_low": _num(r.get("SWING_LOW")),
                "allowed": str(r.get("ENTRY_ALLOWED") or "").strip(),
            }
            if "PASSED_ALL_GATES" in status:
                passed.append(row)
            elif system == "WRL" and status == "CLOSE_IN_DEMAND_ZONE":
                waits.append(row)
    return passed, waits


def _shares(sym: str, entry: float, stop: float | None, acct) -> tuple[int, str]:
    if stop is None or entry <= stop:
        return 0, "no stop under the open"
    sized = size_trade(
        symbol=sym,
        system="RS",
        entry=entry,
        stop=stop,
        bom_equity=acct.bom_equity,
        current_equity=acct.current_equity,
        asof=date.today(),
    )
    if not sized.sized:
        return 0, sized.skip_reason or "not sized"
    n = int(math.floor(sized.shares))
    return n, f"{sized.binding_lid}, about ${n * entry:,.0f}"


def classify(
    session: date,
    holdings: list[dict],
    sells: dict[str, str],
    passed: list[dict],
    waits: list[dict],
    opens: dict,
    acct,
) -> dict[str, list[dict]]:
    expected = _prior_session(session)
    held = {h["symbol"] for h in holdings}
    gt_index = load_gettarget_index()
    buckets = {"sell": [], "hold": [], "buy": [], "skip": []}

    seen = set()
    for h in holdings:
        sym = h["symbol"]
        seen.add(sym)
        q = opens.get(sym)
        op = q.price if q is not None else None
        stop = h.get("stop")
        reason = ""
        action = "hold"
        if sym in sells:
            action = "sell"
            reason = sells[sym]["reason"]
        elif op is not None and stop is not None and op <= stop + 1e-9:
            action = "sell"
            reason = f"Today's open {op:.2f} is through the stop {stop:.2f}."
        else:
            if op is None:
                reason = "No opening print yet. The file stop is still under the last saved price."
            else:
                reason = f"Open {op:.2f} is above the stop {stop:.2f}."
        buckets[action].append({**h, "open": op, "quote": q, "reason": reason})

    for sym, info in sells.items():
        if sym in seen:
            continue
        q = opens.get(sym)
        op = q.price if q is not None else None
        buckets["sell"].append(
            {
                "symbol": sym,
                "system": info["system"],
                "open": op,
                "quote": q,
                "stop": None,
                "file_price": None,
                "target": (gt_index.get(sym) or {}).get("target"),
                "reason": info["reason"] + " Not in the position file, but the sell report still says you are holding it.",
            }
        )

    for row in passed:
        sym = row["symbol"]
        q = opens.get(sym)
        op = q.price if q is not None else None
        why = ""
        keep = True
        if row["signal"] is not None and row["signal"] != expected:
            keep = False
            why = f"Signal date {row['signal'].isoformat()} is not the prior session {expected.isoformat()}."
        elif sym in held:
            keep = False
            why = "Already in the position file. Not a new buy."
        elif row["allowed"] in {"0", "0.0", "false", "False", "no"}:
            keep = False
            why = "Scanner says entry is not allowed."
        elif op is None:
            keep = False
            why = "No opening print from Yahoo yet."
        elif row["stop"] is not None and op <= row["stop"] + 1e-9:
            keep = False
            why = f"Open {op:.2f} is through the stop {row['stop']:.2f}."
        elif row["max_entry"] is not None and row["max_entry"] > 0 and op > row["max_entry"] + 1e-4:
            keep = False
            why = f"Too high. Open {op:.2f} is above the max entry {row['max_entry']:.2f}."
        elif row["min_entry"] is not None and row["min_entry"] > 0 and op < row["min_entry"] - 1e-4:
            keep = False
            why = f"Too low. Open {op:.2f} is under the min entry {row['min_entry']:.2f}."
        else:
            why = "Passed every gate on the prior session, and the open is still allowed."
            if not row["max_entry"]:
                why += " This system did not print an entry band, so a gap does not block the fill."
        shares, size_note = (0, "")
        if keep and op is not None:
            shares, size_note = _shares(sym, op, row["stop"], acct)
            if shares <= 0:
                keep = False
                why = f"Open is allowed, but share size came back empty ({size_note})."
        buy_at = op
        if not keep and row["max_entry"] is not None and row["max_entry"] > 0 and row["stop"] is not None:
            # A later print back inside the band would fill at the max entry.
            if op is not None and op > row["max_entry"] + 1e-4:
                buy_at = row["max_entry"]
        if not keep and buy_at is not None and row["stop"] is not None and buy_at > row["stop"] and shares <= 0:
            shares, size_note = _shares(sym, buy_at, row["stop"], acct)
            if shares > 0 and "Already" not in why and "not allowed" not in why.lower() and "through the stop" not in why:
                why += f" If it reaches {buy_at:.2f}, buy {shares} shares."
        item = {
            **row,
            "open": op,
            "quote": q,
            "reason": why,
            "shares": shares,
            "buy_at": buy_at,
            "size_note": size_note,
        }
        buckets["buy" if keep else "skip"].append(item)

    for row in waits:
        sym = row["symbol"]
        q = opens.get(sym)
        op = q.price if q is not None else None
        swing = row["swing_low"]
        rng = row["range_low"]
        if sym in held:
            why = "Already held. Not a new WRL buy."
            keep = False
        elif op is None:
            why = "No opening print yet. Buy only if the open is above the swing low and through the range low."
            keep = False
        elif swing is not None and op <= swing + 1e-9:
            why = f"Open {op:.2f} is through the swing low {swing:.2f}. No trade."
            keep = False
        elif rng is not None and op + 1e-9 < rng:
            why = (
                f"Open {op:.2f} is still inside the demand zone. "
                f"Buy only if price trades up through the range low {rng:.2f}."
            )
            keep = False
        else:
            why = f"Opened through the range low {rng:.2f} without going through the swing low. That is the WRL fill."
            keep = True
        shares, size_note = (0, "")
        buy_at = op if keep else None
        if (
            not keep
            and sym not in held
            and rng is not None
            and (swing is None or op is None or op > swing + 1e-9)
        ):
            # Still a buy-stop at the range low if price trades up through it.
            buy_at = rng
        if keep and op is not None:
            shares, size_note = _shares(sym, op, row["stop"], acct)
            if shares <= 0:
                keep = False
                why = f"WRL open is a fill, but share size came back empty ({size_note})."
                buy_at = rng
        if not keep and sym not in held and buy_at is not None and row["stop"] is not None and buy_at > row["stop"]:
            shares, size_note = _shares(sym, buy_at, row["stop"], acct)
            if shares > 0:
                why += f" If it reaches {buy_at:.2f}, buy {shares} shares."
        item = {
            **row,
            "open": op,
            "quote": q,
            "reason": why,
            "shares": shares,
            "buy_at": buy_at if not keep else op,
            "size_note": size_note,
        }
        buckets["buy" if keep else "skip"].append(item)
    return buckets


def _px(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "—"
    return f"{float(v):,.2f}"


def _td(text: str, num: bool = False) -> str:
    cls = ' style="text-align:right"' if num else ""
    return f"<td{cls}>{html.escape(text)}</td>"


def _th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" aria-sort="none">'
        f"{html.escape(label)}<span class=\"sort-ind\"></span></th>"
    )


def _table(headers: list[tuple[str, str]], rows: list[list[tuple[str, bool]]]) -> str:
    head = "".join(_th(h, k) for h, k in headers)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(_td(t, n) for t, n in row) + "</tr>")
    return (
        extras.SWIPE_NOTE_HTML
        + '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def _quote_txt(q) -> str:
    if q is None or q.quote_time_et is None:
        return "—"
    return q.quote_time_et.strftime("%H:%M ET")


def render(session: date, now: datetime, note: str, buckets: dict, acct) -> str:
    sell_rows = []
    for r in buckets["sell"]:
        sell_rows.append([
            (r["symbol"], False),
            (NAMES.get(r["system"], r["system"]), False),
            (_px(r.get("open")), True),
            (_quote_txt(r.get("quote")), False),
            (_px(r.get("stop")), True),
            (_px(r.get("target")), True),
            (_px(r.get("file_price")), True),
            (r["reason"], False),
        ])
    buy_rows = []
    for r in buckets["buy"]:
        buy_rows.append([
            (r["symbol"], False),
            (NAMES.get(r["system"], r["system"]), False),
            (str(r.get("shares") or "—"), True),
            (_px(r.get("open")), True),
            (_quote_txt(r.get("quote")), False),
            (_px(r.get("stop")), True),
            (_px(r.get("target")), True),
            (r.get("size_note") or "", False),
            (r["reason"], False),
        ])
    hold_rows = []
    for r in buckets["hold"]:
        hold_rows.append([
            (r["symbol"], False),
            (NAMES.get(r["system"], r["system"]), False),
            (_px(r.get("open")), True),
            (_px(r.get("stop")), True),
            (_px(r.get("target")), True),
            (r["reason"], False),
        ])
    skip_rows = []
    for r in buckets["skip"]:
        skip_rows.append([
            (r["symbol"], False),
            (NAMES.get(r["system"], r["system"]), False),
            (str(r["shares"]) if r.get("shares") else "—", True),
            (_px(r.get("buy_at")), True),
            (_px(r.get("open")), True),
            (_px(r.get("stop")), True),
            (_px(r.get("target")), True),
            (r.get("size_note") or "", False),
            (r["reason"], False),
        ])

    def section(title: str, headers, rows, empty: str) -> str:
        if not rows:
            return f"<h2>{html.escape(title)}</h2><p>{html.escape(empty)}</p>"
        return f"<h2>{html.escape(title)} ({len(rows)})</h2>" + _table(headers, rows)

    risk = min(0.01 * acct.bom_equity, 50000)
    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
{extras.CACHE_META}
{extras.FORCE_RELOAD_SCRIPT}
<title>Today's open buys and sells {session.isoformat()}</title>
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 0; background: #f7f5f0; color: #1c1917; }}
main {{ margin: 0 auto; padding: 24px 16px 64px; max-width: 1100px; }}
h1 {{ font-size: 1.6rem; margin: 0 0 8px; }}
h2 {{ font-size: 1.2rem; margin: 28px 0 8px; }}
.sub {{ color: #57534e; }}
{extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<main>
<h1>Today's open buys and sells</h1>
<p class="sub">{html.escape(session.isoformat())} · written {html.escape(now.strftime("%Y-%m-%d %H:%M"))} Eastern. {html.escape(note)}</p>
<p>A sell is a name you already hold whose system exit is on the sell report, or whose opening print is through its stop. A buy passed every live-system gate on the prior session, is not already held, and today's open is still above the stop and inside the entry band when the file printed one. Share count is the live-style size at that open: risk ${risk:,.0f} (1% of the ${acct.bom_equity:,.0f} account figure dated {html.escape(acct.asof)}), also capped by 1% of 20-day volume and 17.5% of equity. Whole shares, rounded down.</p>
{section("Sell", [("Symbol","text"),("System","text"),("Open","num"),("Quote","text"),("Stop","num"),("Target","num"),("Last file price","num"),("Why","text")], sell_rows, "None.")}
{section("Buy", [("Symbol","text"),("System","text"),("Shares","num"),("Open","num"),("Quote","text"),("Stop","num"),("Target","num"),("Size","text"),("Why","text")], buy_rows, "None.")}
{section("Hold", [("Symbol","text"),("System","text"),("Open","num"),("Stop","num"),("Target","num"),("Why","text")], hold_rows, "No tracked holdings are still above their stops.")}
{section("Do not buy yet", [("Symbol","text"),("System","text"),("Shares","num"),("Buy at","num"),("Open","num"),("Stop","num"),("Target","num"),("Size","text"),("Why","text")], skip_rows, "No passed names were blocked by the open.")}
<p class="sub">Position file gettarget_positions.csv. Stops from getTarget_output.csv. Signals from the latest live watchlists. Opens are the first Yahoo 1-minute bar at or after 9:30 Eastern. This is not a live quote after the open, and it is not DailyRun.</p>
<p class="sub"><a href="index.html">Scanner open report</a> · <a href="investment.html">Investment report</a> · <a href="open_today.html">Today's open buys and sells</a></p>
</main>
{extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    return body


def _symbols_needed(holdings, passed, waits) -> list[str]:
    syms = {h["symbol"] for h in holdings}
    syms.update(load_sells())
    syms.update(r["symbol"] for r in passed)
    syms.update(r["symbol"] for r in waits)
    return sorted(syms)


def _missing_opens(symbols: list[str], opens: dict) -> list[str]:
    missing = []
    for sym in symbols:
        quote = opens.get(sym)
        if quote is None or getattr(quote, "price", None) is None:
            missing.append(sym)
    return missing


def _keep_quotes(opens: dict, got: dict) -> None:
    for sym, quote in got.items():
        if quote is not None and getattr(quote, "price", None) is not None:
            opens[sym] = quote


def _fetch_once(symbols: list[str], session: date, now: datetime) -> tuple[dict, bool]:
    """One Yahoo batch. Returns (quotes, timed_out).

    yfinance's threaded download waits in a loop until every symbol returns.
    If one request never finishes, that wait never ends and this page is never
    written. The worker is a daemon so a timeout lets the page continue.
    """
    box: dict = {}

    def run() -> None:
        try:
            box["got"] = fetch_session_opens_yfinance(symbols, session, now_et=now)
        except Exception as exc:
            box["err"] = exc

    worker = threading.Thread(target=run, name="open-fetch", daemon=True)
    worker.start()
    worker.join(OPEN_FETCH_TIMEOUT_SEC)
    if worker.is_alive():
        print(
            f"open fetch still running after {OPEN_FETCH_TIMEOUT_SEC}s; not waiting on it",
            flush=True,
        )
        return {}, True
    if "err" in box:
        print(f"open fetch failed: {box['err']}", flush=True)
        return {}, False
    return box.get("got") or {}, False


def fetch_opens(symbols: list[str], session: date) -> tuple[dict, list[str]]:
    opens = {s: None for s in symbols}
    now = datetime.now(ET)
    if session == now.date() and now.time() < datetime.strptime("09:30", "%H:%M").time():
        got, _timed_out = _fetch_once(symbols, session, now)
        _keep_quotes(opens, got)
        return opens, _missing_opens(symbols, opens)
    deadline = datetime.combine(session, OPEN_POLL_END_ET, tzinfo=ET)
    missing = list(symbols)
    for attempt in range(1, OPEN_FETCH_ATTEMPTS + 1):
        now = datetime.now(ET)
        got, timed_out = _fetch_once(symbols, session, now)
        _keep_quotes(opens, got)
        missing = _missing_opens(symbols, opens)
        # A timed-out worker is still inside yfinance. Do not start another.
        if not missing or timed_out or now >= deadline or session != now.date() or attempt >= OPEN_FETCH_ATTEMPTS:
            if missing:
                shown = ", ".join(missing)
                print(
                    f"open fetch stopped after {attempt} of {OPEN_FETCH_ATTEMPTS} tries; "
                    f"missing: {shown}",
                    flush=True,
                )
            return opens, missing
        print(
            f"waiting for open prints ({attempt}/{OPEN_FETCH_ATTEMPTS}): {', '.join(missing[:12])}",
            flush=True,
        )
        time.sleep(OPEN_POLL_INTERVAL_SEC)
    return opens, missing


def publish(path: Path) -> None:
    rel = path.relative_to(ROOT).as_posix()
    def git(args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    add = git(["add", "--", rel])
    if add.returncode != 0:
        raise RuntimeError(add.stderr or add.stdout)
    status = git(["status", "--porcelain", "--", rel])
    if status.returncode != 0:
        raise RuntimeError(status.stderr or status.stdout)
    if not status.stdout.strip():
        print("page unchanged; not committing", flush=True)
        return
    msg = f"Publish today's open buy and sell page ({date.today().isoformat()})."
    commit = git(["commit", "-m", msg, "--", rel])
    if commit.returncode != 0:
        raise RuntimeError(commit.stderr or commit.stdout)
    branch = git(["rev-parse", "--abbrev-ref", "HEAD"])
    name = (branch.stdout or "").strip()
    if name == "main":
        push = git(["push", "origin", "main"])
    else:
        push = git(["push", "origin", "HEAD:main"])
    if push.returncode != 0:
        raise RuntimeError(push.stderr or push.stdout)
    print(push.stdout or push.stderr, flush=True)
    print(f"Pushed. Page: {URL}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Write today's open buy/sell page")
    ap.add_argument("--push", action="store_true", help="Commit and push docs/open_today.html to origin/main")
    ap.add_argument("--session", default="", help="YYYY-MM-DD session (default: today Eastern)")
    args = ap.parse_args()
    now = datetime.now(ET)
    session = date.fromisoformat(args.session) if args.session else now.date()
    if session.weekday() >= 5 and not args.session:
        print("Weekend. No regular-session open.", flush=True)
    holdings = load_holdings()
    sells = load_sells()
    passed, waits = load_candidates()
    symbols = _symbols_needed(holdings, passed, waits)
    print(f"session {session.isoformat()} symbols {len(symbols)} passed {len(passed)} wrl-wait {len(waits)}", flush=True)
    opens, missing = fetch_opens(symbols, session)
    acct = load_account_state()
    buckets = classify(session, holdings, sells, passed, waits, opens, acct)
    note = market_status_message(session, datetime.now(ET))
    if missing:
        note += " Opening print unavailable after retries: " + ", ".join(missing) + "."
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(render(session, datetime.now(ET), note, buckets, acct), encoding="utf-8")
    print(
        f"wrote {PAGE} sell={len(buckets['sell'])} buy={len(buckets['buy'])} "
        f"hold={len(buckets['hold'])} skip={len(buckets['skip'])}",
        flush=True,
    )
    if args.push:
        publish(PAGE)
    else:
        print(f"local only. URL after a push: {URL}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
