"""Mini AU backtest: does SC fire 2019-04-25 for zone 11.82-12.18?"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "stock_analysis"))

from rocket_brt import BRTConfig, run_brt_backtest
from ohlcv_store import load_symbol_df, resolve_db_path

db = resolve_db_path(None)
df = load_symbol_df("AU", db_path=db)
print("bars", len(df), df.index.min(), df.index.max())

# Confirm Apr24 OHLC from eng data
row = df.loc["2019-04-24"]
print("eng Apr24", float(row.Open), float(row.High), float(row.Low), float(row.Close))
row25 = df.loc["2019-04-25"]
print("eng Apr25", float(row25.Open), float(row25.High), float(row25.Low), float(row25.Close))

cfg = BRTConfig(
    wpbr_zones=True,
    brt_zones=False,
    yh_zones=False,
    vec_zones=False,
    band_pct=0.015,
    strong_pre_pivot_bars=3,
    strong_pre_pivot_pct=0.10,
    strong_post_pivot_bars=3,
    strong_post_pivot_pct=0.10,
    strong_pivot_mode="either",
    wpbr_breakout_confirmation=0.03,
    wpbr_max_days_after_retest=2,
    wpbr_retest_mode="stop_looking",
    wpbr_second_chance_after_win=True,
    growth_filter_enabled=False,
    min_spy_compare_1y_at_trigger=-1000.0,
    too_high_multiplier=0.0,
    target_pct=1.22,
    stop_pct=0.91,
    stop_pct_is_multiplier=True,
    entry_start_date="2016-01-01",
    use_indicators=False,
    indicator_buy="off",
    zone_price_round_decimals=2,
)

# Monkeypatch SC resume to log Apr 2019 window
import rocket_brt as rb
import wpbr_zones as wz

_orig = wz.find_wpbr_retest_and_signal
_calls = []


def _wrapped(*a, **k):
    rt, sig, fill = _orig(*a, **k)
    scan = k.get("scan_start", a[3] if len(a) > 3 else None)
    stop = k.get("stop_at")
    zl = k.get("zone_lower")
    zh = k.get("zone_upper")
    # only log zone of interest near Apr
    if zl is not None and abs(float(zl) - 11.82) < 1e-6 and stop is not None and 2335 <= int(stop) <= 2350:
        _calls.append(
            {
                "scan": scan,
                "stop": stop,
                "rt": rt,
                "sig": sig,
                "fill": fill,
                "mode": k.get("retest_mode"),
            }
        )
    return rt, sig, fill


wz.find_wpbr_retest_and_signal = _wrapped
# also patch the import used inside run if already bound — run_brt imports inside function

closed, open_t, *_rest = run_brt_backtest(df, "AU", cfg)
print("n_closed", len(closed))
for t in closed:
    d = str(getattr(t, "date_opened", ""))
    if d.startswith("2018") or d.startswith("2019") or d.startswith("2020"):
        print(
            d,
            getattr(t, "date_closed", ""),
            getattr(t, "entry_price", None),
            getattr(t, "pnl_pct", None),
            getattr(t, "wpbr_zone_id", ""),
        )

print("SC find calls near Apr for 11.82 zone:", len(_calls))
for c in _calls[:20]:
    print(c)

# dates of interest
want = {"20190425", "20190424", "20181228", "20201028", "20230907"}
print("hits:")
for t in closed:
    d = str(getattr(t, "date_opened", ""))[:8]
    if d in want:
        print("HIT", d, getattr(t, "wpbr_zone_id", ""), getattr(t, "entry_price", None))
