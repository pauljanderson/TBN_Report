"""Premarket outlook: current quote vs MAX_ENTRY_OPEN for latest IND scanner."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parent.parent
DRIVE = ROOT / "Drive"


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def latest_scanner() -> Path:
    best = None
    for p in DRIVE.glob("IND_Scanner_*.csv"):
        m = re.match(r"IND_Scanner_(\d{12})\.csv", p.name)
        if not m:
            continue
        if best is None or m.group(1) > best[0]:
            best = (m.group(1), p)
    if best is None:
        raise FileNotFoundError("No IND_Scanner CSV in Drive")
    return best[1]


def main() -> None:
    import yfinance as yf

    path = latest_scanner()
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    now_et = datetime.now(ET)
    print(f"Scanner: {path.name}")
    print(f"Now: {now_et.strftime('%Y-%m-%d %H:%M')} ET")
    print()

    rows = []
    for _, r in df.iterrows():
        sym = str(r.get("SYMBOL", "")).strip().upper()
        if not sym:
            continue
        max_o = _num(r.get("MAX_ENTRY_OPEN"))
        close = _num(r.get("CLOSE"))
        signal = str(r.get("DATE", "")).strip()
        t = yf.Ticker(sym)
        info = {}
        try:
            info = t.fast_info
        except Exception:
            pass
        pre = getattr(info, "pre_market_price", None) if hasattr(info, "pre_market_price") else None
        last = getattr(info, "last_price", None) if hasattr(info, "last_price") else None
        reg = getattr(info, "regular_market_price", None) if hasattr(info, "regular_market_price") else None
        # fast_info is dict-like in recent yfinance
        if isinstance(info, dict) or hasattr(info, "get"):
            try:
                pre = pre or info.get("preMarketPrice") or info.get("pre_market_price")
                last = last or info.get("lastPrice") or info.get("last_price")
                reg = reg or info.get("regularMarketPrice") or info.get("regular_market_price")
            except Exception:
                pass
        try:
            pre = pre or (info["preMarketPrice"] if "preMarketPrice" in info else None)
        except Exception:
            pass
        try:
            last = last or (info["lastPrice"] if "lastPrice" in info else None)
        except Exception:
            pass

        # Fallback: 1m premarket bars today
        px = pre or last or reg
        src = "fast_info"
        if px is None or (isinstance(px, float) and px != px):
            try:
                intraday = t.history(period="1d", interval="1m", prepost=True)
                if not intraday.empty:
                    px = float(intraday["Close"].dropna().iloc[-1])
                    src = "1m_prepost"
            except Exception:
                px = None

        outlook = "unknown"
        detail = "no quote"
        if px is not None and max_o:
            if px <= max_o:
                outlook = "on track BUY"
                detail = f"pre/last {px:.2f} <= max {max_o:.4f}"
            else:
                outlook = "likely IGNORE"
                detail = f"pre/last {px:.2f} > max {max_o:.4f} (+{(px/max_o-1)*100:.2f}%)"
        chg = None
        if px is not None and close:
            chg = (px / close - 1) * 100

        rows.append(
            {
                "symbol": sym,
                "signal": signal,
                "close": close,
                "max_entry": max_o,
                "quote": px,
                "chg_vs_close_pct": chg,
                "outlook": outlook,
                "detail": detail,
                "source": src,
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        print("No symbols.")
        return

    on_track = out[out["outlook"] == "on track BUY"].sort_values("symbol")
    likely_ignore = out[out["outlook"] == "likely IGNORE"].sort_values("symbol")
    unknown = out[~out["outlook"].isin(["on track BUY", "likely IGNORE"])].sort_values("symbol")

    print(f"=== On track for BUY at open ({len(on_track)}) ===")
    for _, r in on_track.iterrows():
        chg = f", {r['chg_vs_close_pct']:+.2f}% vs Fri close" if r["chg_vs_close_pct"] is not None else ""
        print(f"  {r['symbol']:5}  {r['detail']}{chg}")

    print(f"\n=== Likely IGNORE — above max entry ({len(likely_ignore)}) ===")
    for _, r in likely_ignore.iterrows():
        chg = f", {r['chg_vs_close_pct']:+.2f}% vs Fri close" if r["chg_vs_close_pct"] is not None else ""
        print(f"  {r['symbol']:5}  {r['detail']}{chg}")

    if len(unknown):
        print(f"\n=== No premarket quote ({len(unknown)}) ===")
        for _, r in unknown.iterrows():
            print(f"  {r['symbol']:5}  signal={r['signal']}")

    stale = out[out["signal"] != "20260605"]
    if len(stale):
        print(f"\n=== Stale signal (will IGNORE regardless) ===")
        for _, r in stale.iterrows():
            print(f"  {r['symbol']:5}  signal={r['signal']}")

    print("\nNote: Official BUY/IGNORE uses the 09:30 ET open, not premarket. Re-run after 09:30:")
    print("  python generate_scanner_open_report.py --drive drive")


if __name__ == "__main__":
    main()
