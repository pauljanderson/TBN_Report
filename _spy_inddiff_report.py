"""SPY IND_DIFF regime overlay on normal system closed trades.

Regime = SPY's daily trade-aligned (LONG) IND_DIFF from the same indicator engine
IND uses. In-regime day = IND_DIFF >= threshold. A normal-run trade qualifies if its
TRIGGER date (session before entry) is an in-regime day. Below threshold => no new entry.

Reports at IND_DIFF >= 0 (net bullish) and IND_DIFF >= 8 (production strength).
"""
import sys
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "stock_analysis"))
DRIVE = ROOT / "Drive"
RL_CASH = 47500.0

from brt_entry_indicators import build_entry_indicator_precompute, aligned_bull_bear_diff

# ---- SPY daily IND_DIFF series ----
spy = pd.read_csv(ROOT / "data" / "newdata" / "data" / "SPY.csv")
spy_df = spy.copy()
spy_df["Date"] = pd.to_datetime(spy_df["Date"])
spy_df = spy_df.set_index("Date")
pre = build_entry_indicator_precompute(spy_df, symbol="SPY", use_cache=False)
if pre is None:
    raise SystemExit("Could not build SPY indicator precompute")


def _norm(d) -> str:
    if hasattr(d, "strftime"):
        return d.strftime("%Y%m%d")
    return str(d)[:10].replace("-", "")


pre_dates = [_norm(d) for d in pre.dates]
diff_by_date = {}
for i, d in enumerate(pre_dates):
    v = aligned_bull_bear_diff(pre, i, "LONG")
    if v is not None:
        diff_by_date[d] = int(v)

regime0 = {d for d, v in diff_by_date.items() if v >= 0}
regime8 = {d for d, v in diff_by_date.items() if v >= 8}

# SPY trading calendar -> prior trading day (trigger = session before entry)
spy_cal = [_norm(d) for d in spy_df.index]
prior = {spy_cal[i]: spy_cal[i - 1] for i in range(1, len(spy_cal))}


def trigger_date(entry: str) -> str:
    return prior.get(entry, "")


# ---- normal-run closed trades ----
def _pct(v) -> float:
    s = str(v).strip().replace("%", "")
    if s == "" or s.lower() == "nan":
        return np.nan
    return float(s)


def _nd(v) -> str:
    return str(v).strip().replace("-", "")[:8]


def load_brt_like(path: Path, system: str) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, low_memory=False)
    if df.empty:
        return pd.DataFrame()
    out = pd.DataFrame()
    out["symbol"] = df["SYMBOL"]
    out["entry"] = df["DATE_OPENED"].map(_nd)
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
    out["entry"] = df["DATE OPENED"].map(_nd)
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
trades["trigger"] = trades["entry"].map(trigger_date)


def stats(df):
    n = len(df)
    if n == 0:
        return None
    wins = df[df["pnl_pct"] > 0]
    losses = df[df["pnl_pct"] < 0]
    nw, nl = len(wins), len(losses)
    aw = wins["pnl_pct"].mean() if nw else 0.0
    al = losses["pnl_pct"].mean() if nl else 0.0
    payoff = (aw / abs(al)) if (nl and al != 0) else float("inf")
    return dict(n=n, nw=nw, nl=nl, win=nw / n * 100, avg=df["pnl_pct"].mean(),
               payoff=payoff, wl=(nw / nl if nl else float("inf")),
               days=df["days"].mean(), profit=df["pnl_dollars"].sum())


def show(title, df):
    s = stats(df)
    print(f"\n===== {title} =====")
    if not s:
        print("  (no trades)")
        return
    print(f"  Total trades      : {s['n']}  ({s['nw']}W / {s['nl']}L)")
    print(f"  Win rate          : {s['win']:.1f}%")
    print(f"  Average profit %   : {s['avg']:+.2f}%")
    print(f"  Win/Loss ratio     : {s['payoff']:.2f}  (avg win% / avg loss%)  |  counts {s['wl']:.2f} (W:L)")
    print(f"  Avg days in trade  : {s['days']:.1f}")
    print(f"  Total profit       : ${s['profit']:,.0f}")
    print("  by system:")
    for sysname in ["BRT", "IND", "RL", "YH"]:
        ss = stats(df[df["system"] == sysname])
        if ss:
            print(f"    {sysname:3}: {ss['n']:4d} trades | win {ss['win']:5.1f}% | avgP {ss['avg']:+6.2f}% | ${ss['profit']:>12,.0f}")


print(f"SPY IND_DIFF computed for {len(diff_by_date)} bars "
      f"(range {min(diff_by_date.values())}..{max(diff_by_date.values())})")
print(f"In-regime days: IND_DIFF>=0 : {len(regime0)} | IND_DIFF>=8 : {len(regime8)} | total bars {len(diff_by_date)}")
print(f"Total closed trades loaded: {len(trades)}")
print("(regime checked on TRIGGER date = session before entry)")

show("BASELINE - all trades (no filter)", trades)
show("REPORT A - trigger-day SPY IND_DIFF >= 0", trades[trades["trigger"].isin(regime0)])
show("REPORT B - trigger-day SPY IND_DIFF >= 8", trades[trades["trigger"].isin(regime8)])
