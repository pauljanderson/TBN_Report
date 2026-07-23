#!/usr/bin/env python3
"""Post-hoc BRT VOL_SURGE state quantification from Closed + .indcache trigger states.

Evidence class: screening on already-taken trades (not portfolio capital BT).
Uses drive/IND_Signal_Overlay_PnL_Trades_States.csv when present, else rebuilds.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
_TOOLS = _REPO / "tools"
_SA = _REPO / "stock_analysis"
for p in (_REPO, _SA, _TOOLS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from analyze_ind_diff_at_trigger_pnl import _load_brt_like, _trade_stats  # noqa: E402
from analyze_ind_signal_overlay_pnl import enrich_states  # noqa: E402

OUT_ROOT = _REPO / "drive" / "brt_vol_surge_exp"
STATES_CSV = _REPO / "drive" / "IND_Signal_Overlay_PnL_Trades_States.csv"
CLOSED = _REPO / "drive" / "BRT_LatestRun_Closed.csv"
CACHE = _REPO / "data" / "newdata" / "data" / ".brt_indicator_cache"


def _equity_dd(pnl_pct: pd.Series) -> float:
    """Simple cumulative %-PnL path max drawdown (post-hoc, equal-weight trades)."""
    if pnl_pct.empty:
        return float("nan")
    eq = (1.0 + pnl_pct.fillna(0.0) / 100.0).cumprod()
    peak = eq.cummax()
    dd = (eq / peak - 1.0) * 100.0
    return float(dd.min()) if len(dd) else float("nan")


def quantify(df: pd.DataFrame) -> pd.DataFrame:
    base = df[(df["system"] == "BRT") & df["ok"].fillna(False)].dropna(subset=["pnl_pct"]).copy()
    rows = []
    for lab in ("ALL", "BULL", "BEAR", "NEUTRAL"):
        sub = base if lab == "ALL" else base[base["lab_VOL_SURGE"] == lab]
        n = len(sub)
        if n == 0:
            rows.append({"state": lab, "n": 0})
            continue
        st = _trade_stats(sub)
        rows.append(
            {
                "state": lab,
                "n": n,
                "coverage_pct": 100.0 * n / max(1, len(base)),
                "avg_pnl_pct": float(sub["pnl_pct"].mean()),
                "median_pnl_pct": float(sub["pnl_pct"].median()),
                "total_pnl_pct": float(sub["pnl_pct"].sum()),
                "total_pnl_dollars": float(
                    pd.to_numeric(sub.get("pnl_dollars"), errors="coerce").sum()
                ),
                "win_rate": float((sub["pnl_pct"] > 0).mean()),
                "profit_factor": st.get("profit_factor", float("nan")),
                "lift_vs_all_pp": float(sub["pnl_pct"].mean()) - float(base["pnl_pct"].mean()),
                "simple_cum_max_dd_pct": _equity_dd(sub["pnl_pct"].reset_index(drop=True)),
                "encoding": "VOL_SURGE: BULL if vol/SMA20>1.5, BEAR if <0.6, else NEUTRAL; "
                "int states +1/0/-1; trigger=session before DATE_OPENED",
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    if not args.rebuild and STATES_CSV.is_file():
        print(f"[posthoc] loading {STATES_CSV}")
        all_states = pd.read_csv(STATES_CSV, low_memory=False)
        brt = all_states[all_states["system"] == "BRT"].copy()
    else:
        print(f"[posthoc] enriching from {CLOSED}")
        trades = _load_brt_like(CLOSED, "BRT")
        brt = enrich_states(trades, CACHE, workers=int(args.workers))
        brt.to_csv(OUT_ROOT / "BRT_Trades_States.csv", index=False)

    # Timing sanity: trigger_ymd should be prior calendar session to entry
    ok = brt[brt["ok"].fillna(False)].copy()
    if "trigger_ymd" in ok.columns and "entry" in ok.columns:
        ok["entry_i"] = pd.to_numeric(ok["entry"], errors="coerce")
        ok["trig_i"] = pd.to_numeric(ok["trigger_ymd"], errors="coerce")
        lag = (ok["entry_i"] - ok["trig_i"]).dropna()
        print(
            f"[posthoc] timing check: n_ok={len(ok)}  "
            f"entry-trigger median calendar days={float(lag.median()):.1f}  "
            f"min={float(lag.min()):.0f} max={float(lag.max()):.0f}"
        )

    tbl = quantify(brt)
    csv_path = OUT_ROOT / "posthoc_vol_surge_by_state.csv"
    md_path = OUT_ROOT / "posthoc_vol_surge_by_state.md"
    tbl.to_csv(csv_path, index=False)

    lines = [
        "# BRT VOL_SURGE — post-hoc by state",
        "",
        "## Evidence class",
        "",
        "Post-hoc screen on **already taken** BRT closed trades with IND states at the "
        "**trigger bar** (session before `DATE_OPENED`) from `.brt_indicator_cache`.",
        "Not a portfolio capital backtest — capital path / crowding effects absent.",
        "",
        "## Encoding / timing",
        "",
        "- `VOL_SURGE`: BULL if volume / 20d SMA > 1.5; BEAR if < 0.6; else NEUTRAL.",
        "- Internal ints: `+1` BULL, `0` NEUTRAL, `-1` BEAR (`_state_tri`).",
        "- Trigger = prior symbol session vs entry open date (same as overlay analysis).",
        "",
        "## Results",
        "",
        "| State | N | Avg% | Med% | Total% | WR% | PF | Lift pp | Simple DD% |",
        "|-------|--:|-----:|-----:|-------:|----:|---:|--------:|-----------:|",
    ]
    for _, r in tbl.iterrows():
        if int(r.get("n", 0) or 0) == 0:
            lines.append(f"| {r['state']} | 0 | — | — | — | — | — | — | — |")
            continue
        lines.append(
            f"| {r['state']} | {int(r['n'])} | {r['avg_pnl_pct']:.2f} | {r['median_pnl_pct']:.2f} | "
            f"{r['total_pnl_pct']:.1f} | {100*r['win_rate']:.1f} | {r['profit_factor']:.2f} | "
            f"{r['lift_vs_all_pp']:+.2f} | {r['simple_cum_max_dd_pct']:.1f} |"
        )
    harmful = tbl[tbl["state"] != "ALL"].sort_values("avg_pnl_pct")
    worst = harmful.iloc[0] if len(harmful) else None
    lines.extend(["", "## Post-hoc verdict", ""])
    if worst is not None:
        lines.append(
            f"**Most harmful state (avg PnL):** `{worst['state']}` "
            f"(n={int(worst['n'])}, avg={worst['avg_pnl_pct']:.2f}%, "
            f"lift={worst['lift_vs_all_pp']:+.2f} pp, PF={worst['profit_factor']:.2f})."
        )
    lines.append("")
    lines.append(f"Wrote `{csv_path.relative_to(_REPO)}`.")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(tbl.to_string(index=False))
    print(f"[posthoc] wrote {csv_path}")
    print(f"[posthoc] wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
