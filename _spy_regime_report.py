"""SPY-regime overlay on normal system closed trades.

Keep a closed trade only if, on its ENTRY date, SPY Close was above its SMA20
(Report A) or SMA50 (Report B). Below the SMA => no new trades allowed that day.

Systems: BRT, IND, YH (rocket_brt layout) + RL (its own layout).
RL has no dollar column -> derive dollars = pnl_pct/100 * RL_CASH.
"""
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parent
DRIVE = ROOT / "Drive"
RL_CASH = 47500.0

# ---- SPY regime lookup ----
spy = pd.read_csv(ROOT / "data" / "newdata" / "data" / "SPY.csv")
spy["Date"] = pd.to_datetime(spy["Date"]).dt.strftime("%Y%m%d")
spy = spy.set_index("Date")
spy_close = spy["Close"].astype(float)
spy_sma20 = spy["SMA20"].astype(float)
spy_sma50 = spy["SMA50"].astype(float)

above20 = {d for d in spy.index if spy_sma20[d] > 0 and spy_close[d] > spy_sma20[d]}
above50 = {d for d in spy.index if spy_sma50[d] > 0 and spy_close[d] > spy_sma50[d]}
spy_dates = set(spy.index)

# Ordered SPY trading calendar -> map each date to the PRIOR trading day.
# Trigger date = session before entry (signal fires at trigger close; entry = next open).
spy_ordered = list(spy.index)
_prior = {spy_ordered[i]: spy_ordered[i - 1] for i in range(1, len(spy_ordered))}


def trigger_date(entry: str) -> str:
    return _prior.get(entry, "")


def _norm_date(v) -> str:
    s = str(v).strip().replace("-", "")
    return s[:8]


def _pct(v) -> float:
    s = str(v).strip().replace("%", "")
    if s == "" or s.lower() == "nan":
        return np.nan
    return float(s)


def load_brt_like(path: Path, system: str) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, low_memory=False)
    if df.empty:
        return pd.DataFrame()
    out = pd.DataFrame()
    out["symbol"] = df["SYMBOL"]
    out["entry"] = df["DATE_OPENED"].map(_norm_date)
    out["days"] = pd.to_numeric(df["DAYS_HELD"], errors="coerce")
    out["pnl_pct"] = df["PNL_PCT"].map(_pct)
    out["pnl_dollars"] = pd.to_numeric(df["PNL_DOLLARS"], errors="coerce")
    out["system"] = system
    return out


def load_rl(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, low_memory=False)
    if df.empty:
        return pd.DataFrame()
    out = pd.DataFrame()
    out["symbol"] = df["SYMBOL"]
    out["entry"] = df["DATE OPENED"].map(_norm_date)
    out["days"] = pd.to_numeric(df["DAYS HELD"], errors="coerce")
    out["pnl_pct"] = df["PNL %"].map(_pct)
    out["pnl_dollars"] = out["pnl_pct"] / 100.0 * RL_CASH
    out["system"] = "RL"
    return out


frames = [
    load_brt_like(DRIVE / "BRT_LatestRun_Closed.csv", "BRT"),
    load_brt_like(DRIVE / "IND_LatestRun_Closed.csv", "IND"),
    load_brt_like(DRIVE / "YH_LatestRun_Closed.csv", "YH"),
    load_rl(DRIVE / "RL_LatestRun_Closed.csv"),
]
trades = pd.concat([f for f in frames if not f.empty], ignore_index=True)
trades = trades.dropna(subset=["pnl_pct"])


def stats(df: pd.DataFrame) -> dict:
    n = len(df)
    if n == 0:
        return {"trades": 0}
    wins = df[df["pnl_pct"] > 0]
    losses = df[df["pnl_pct"] < 0]
    nw, nl = len(wins), len(losses)
    avg_win = wins["pnl_pct"].mean() if nw else 0.0
    avg_loss = losses["pnl_pct"].mean() if nl else 0.0
    payoff = (avg_win / abs(avg_loss)) if (nl and avg_loss != 0) else float("inf")
    return {
        "trades": n,
        "win_rate": nw / n * 100.0,
        "avg_profit_pct": df["pnl_pct"].mean(),
        "wl_ratio_counts": (nw / nl) if nl else float("inf"),
        "payoff": payoff,
        "avg_days": df["days"].mean(),
        "total_profit": df["pnl_dollars"].sum(),
        "wins": nw,
        "losses": nl,
    }


def show(title: str, df: pd.DataFrame):
    s = stats(df)
    print(f"\n===== {title} =====")
    if s["trades"] == 0:
        print("  (no trades)")
        return
    print(f"  Total trades      : {s['trades']}  ({s['wins']}W / {s['losses']}L)")
    print(f"  Win rate          : {s['win_rate']:.1f}%")
    print(f"  Average profit %   : {s['avg_profit_pct']:+.2f}%")
    print(f"  Win/Loss ratio     : {s['payoff']:.2f}  (avg win% / avg loss%)   |  counts {s['wl_ratio_counts']:.2f} (W:L)")
    print(f"  Avg days in trade  : {s['avg_days']:.1f}")
    print(f"  Total profit       : ${s['total_profit']:,.0f}")
    # per-system
    print("  by system:")
    for sysname in ["BRT", "IND", "RL", "YH"]:
        sub = df[df["system"] == sysname]
        ss = stats(sub)
        if ss["trades"] == 0:
            continue
        print(f"    {sysname:3}: {ss['trades']:4d} trades | win {ss['win_rate']:5.1f}% | avgP {ss['avg_profit_pct']:+6.2f}% | ${ss['total_profit']:>12,.0f}")


trades["trigger"] = trades["entry"].map(trigger_date)

baseline = trades
repA = trades[trades["trigger"].isin(above20)]
repB = trades[trades["trigger"].isin(above50)]

unmatched = trades[~trades["entry"].isin(spy_dates)]
no_trigger = trades[trades["trigger"] == ""]
print(f"Total closed trades loaded: {len(trades)}  (BRT/IND/YH + RL)")
print(f"Entries with no matching SPY date row: {len(unmatched)} | no prior-day trigger: {len(no_trigger)}")
print(f"SPY days > SMA20: {len(above20)} | > SMA50: {len(above50)} | total SPY days: {len(spy_dates)}")
print("(regime checked on TRIGGER date = trading day before entry)")

show("BASELINE — all trades (no SPY filter)", baseline)
show("REPORT A — trigger-day SPY Close > SMA20", repA)
show("REPORT B — trigger-day SPY Close > SMA50", repB)
