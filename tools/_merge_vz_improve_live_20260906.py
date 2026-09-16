#!/usr/bin/env python3
"""Merge live ENTRY_* arms into vz_improve_priority_ab_20260906 compare.html."""
from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

from compare_format import find_host_equity_curve_csv  # noqa: E402
import vz_improve_priority_ab_20260906 as ab  # noqa: E402

OUT = REPO / "drive" / "paul_experiments" / "vz_improve_priority_ab_20260906"
LIVE = OUT / "live"

ORDER = [
    ("00_freeze", "CONTROL", "EXIT_atr4_s025_r15 + cd=10 full-univ Closed", "baseline"),
    (
        "EXIT_stop_atr05",
        "EXIT",
        "stop_atr_buffer 0.25->0.50 (wider)",
        "stop_pct_tension_expand + peer_wider_stop_*",
    ),
    (
        "EXIT_stop_atr075",
        "EXIT",
        "stop_atr_buffer 0.25->0.75 (wider+)",
        "stop_pct_tension_expand + peer_wider_stop_* (stronger)",
    ),
    (
        "EXIT_stop_atr0125",
        "EXIT",
        "stop_atr_buffer 0.25->0.125 (tighter)",
        "fat_stops + stop_pct_tension contract lens",
    ),
    (
        "EXIT_target_r20",
        "EXIT",
        "target_r 1.5->2.0 (expand)",
        "target_pct_tension_expand + small_target_wins + peer_longer_hold",
    ),
    (
        "EXIT_target_r10",
        "EXIT",
        "target_r 1.5->1.0 (contract)",
        "target_pct_tension_contract lens",
    ),
    ("EXIT_ts20", "EXIT", "exit_bars 40->20 (cut losers)", "fat_stops (time-stop lever)"),
    (
        "EXIT_ts60",
        "EXIT",
        "exit_bars 40->60 (hold longer)",
        "peer_longer_hold_won_* / peer_target_after_our_stop_*",
    ),
    (
        "EXIT_trail_be1r",
        "EXIT",
        "trail: raise stop to breakeven after +1R MFE",
        "winner_peak_giveback",
    ),
    (
        "ENTRY_cd_target20",
        "ENTRY",
        "Skip entries <=20d after TARGET (vs house 10)",
        "post_target_quick_stop",
    ),
    (
        "ENTRY_spy_sma200",
        "ENTRY",
        "Require SPY Close > SMA200 on entry date",
        "false_start_2022_2023",
    ),
    (
        "ENTRY_start_2024",
        "ENTRY",
        "entry_start_date=2024-01-01 (drop pre-2024)",
        "false_start_2022_2023 (aggressive)",
    ),
]

LIVE_ARMS = [
    (
        "ENTRY_eps002",
        "ENTRY",
        "retest_eps_pct 0.005->0.002 (band tighten)",
        "band_tighten_weak_fill",
    ),
    (
        "ENTRY_eps0",
        "ENTRY",
        "retest_eps_pct 0.005->0.0 (band tighten stronger)",
        "band_tighten_weak_fill",
    ),
    (
        "ENTRY_mt2",
        "ENTRY",
        "min_touches 1->2 (stricter quality)",
        "band_tighten_weak_fill",
    ),
]


def load_closed_csv(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = ab._parse_d(raw.get("DATE_OPENED"))
            closed = ab._parse_d(raw.get("DATE_CLOSED"))
            if opened is None or closed is None:
                continue
            entry = ab._f(raw.get("ENTRY_PRICE"))
            pnl = ab._f(raw.get("PNL_PCT"), 0.0)
            pnl_d = ab._f(raw.get("PNL_DOLLARS"), pnl / 100.0 * ab.SHEET)
            days = ab._f(raw.get("DAYS_HELD"), 1.0)
            rows.append(
                {
                    "symbol": str(raw.get("SYMBOL", "")).upper(),
                    "opened": opened,
                    "closed": closed,
                    "entry": entry,
                    "pnl": pnl,
                    "pnl_d": pnl_d,
                    "days": max(1.0, days if math.isfinite(days) and days > 0 else 1.0),
                    "exit_type": ab._exit_type_norm(str(raw.get("EXIT_TYPE", ""))),
                    "r_mult": ab._f(raw.get("R_MULT"), 0.0),
                    "stop": ab._f(raw.get("STOP_PRICE")),
                    "target": ab._f(raw.get("TARGET_PRICE")),
                }
            )
    return rows


def _pack_arm(
    arm: str,
    kind: str,
    knob: str,
    hyp: str,
    trades: list[dict],
    *,
    equity_curve_path=None,
) -> dict:
    full = ab.metrics_pack(trades, equity_curve_path=equity_curve_path)
    is_r, oos_r = ab.split_trades(trades)
    return {
        "arm": arm,
        "kind": kind,
        "knob": knob,
        "hypothesis": hyp,
        "full": full,
        "is": ab.metrics_pack(
            is_r,
            equity_curve_path=equity_curve_path,
            end_date_exclusive=ab.IS_CUT,
        ),
        "oos": ab.metrics_pack(
            oos_r,
            equity_curve_path=equity_curve_path,
            start_date=ab.IS_CUT,
        ),
        "verdict": "",
        "why": "",
        "trades": trades,
    }


def main() -> int:
    packs: list[dict] = []
    for arm, kind, knob, hyp in ORDER:
        trades = load_closed_csv(OUT / f"closed_{arm}.csv")
        packs.append(_pack_arm(arm, kind, knob, hyp, trades))

    for arm, kind, knob, hyp in LIVE_ARMS:
        closed = sorted((LIVE / arm).glob("VZ_Closed_*.csv"))
        if not closed:
            print("MISSING", arm)
            continue
        trades = load_closed_csv(closed[-1])
        ab.write_arm_csv(OUT / f"closed_{arm}.csv", trades)
        eq = find_host_equity_curve_csv(LIVE / arm)
        full_pack = _pack_arm(arm, kind, knob, hyp, trades, equity_curve_path=eq)
        packs.append(full_pack)
        full = full_pack["full"]
        print(
            f"{arm}: N={full['n_signals']} WR={full['win_rate']*100:.1f}% "
            f"Avg={full['avg_pnl_pct']:.2f} Sharpe={ab.fmt_num(full.get('sharpe', float('nan')))} "
            f"src={full.get('sharpe_source','')}"
        )

    ctrl = packs[0]["full"]
    for p in packs:
        v, w = ab.score_arm(p["arm"], p["full"], ctrl)
        p["verdict"], p["why"] = v, w

    deferred = [
        "partial_exit / scale-out - no simulator -> DISMISS untestable",
        "Live entry arms scored via Closed overlay metrics pack (same IS/OOS cut). "
        "Sharpe: EquityCurve when present else Closed exit-date equity.",
    ]
    rec = ab.recommend(packs)
    ab.build_html(OUT / "compare.html", packs=packs, recommendation=rec, deferred=deferred)

    with (OUT / "metrics.csv").open("w", newline="", encoding="utf-8") as f:
        cols = [
            "arm",
            "kind",
            "verdict",
            "slice",
            "N",
            "WR_pct",
            "AvgPnL_pct",
            "AvgR",
            "MedPnL_pct",
            "WO_MAX_pct",
            "Ann_ROR_pct",
            "Max_DD_pct",
            "Calmar",
            "Sharpe",
            "Sharpe_source",
            "PF",
            "Sheet_PnL",
            "AvgDays",
            "why",
        ]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for p in packs:
            for sl, key in (("full", "full"), ("IS", "is"), ("OOS", "oos")):
                m = p[key]
                sh = m.get("sharpe", float("nan"))
                w.writerow(
                    {
                        "arm": p["arm"],
                        "kind": p["kind"],
                        "verdict": p["verdict"],
                        "slice": sl,
                        "N": m["n_signals"],
                        "WR_pct": round(m["win_rate"] * 100, 3),
                        "AvgPnL_pct": round(m["avg_pnl_pct"], 4),
                        "AvgR": round(m["avg_r"], 4),
                        "MedPnL_pct": round(m["med_pnl_pct"], 4),
                        "WO_MAX_pct": round(m["wo_max"], 4),
                        "Ann_ROR_pct": m["ann_ror"] if math.isfinite(m["ann_ror"]) else "",
                        "Max_DD_pct": m["max_dd"] if math.isfinite(m["max_dd"]) else "",
                        "Calmar": m["calmar"] if math.isfinite(m["calmar"]) else "",
                        "Sharpe": sh if isinstance(sh, (int, float)) and math.isfinite(float(sh)) else "",
                        "Sharpe_source": m.get("sharpe_source", ""),
                        "PF": round(m["pf"], 4),
                        "Sheet_PnL": round(m["sheet_pnl"], 2),
                        "AvgDays": round(m["avg_days"], 3),
                        "why": p["why"],
                    }
                )

    base = OUT / "BASELINE.md"
    text = base.read_text(encoding="utf-8")
    marker = "\n## Auto results\n"
    if marker in text:
        text = text.split(marker)[0].rstrip() + "\n"
    text += marker + "\n```\n" + rec + "\n```\n"
    base.write_text(text, encoding="utf-8")
    print(rec.encode("ascii", "replace").decode("ascii"))
    print("Wrote", OUT / "compare.html")
    ctrl_is = packs[0]["is"]
    print(
        "CONTROL IS Sharpe=",
        ab.fmt_num(ctrl_is.get("sharpe", float("nan"))),
        ctrl_is.get("sharpe_source", ""),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
