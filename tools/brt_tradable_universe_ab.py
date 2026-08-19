#!/usr/bin/env python3
"""BRT 42-name production vs 764-name 2010/ADV$2m tradable tape (optional ALL).

Universe identity A/B only. Freeze = current run_brt.bat knobs.
NOT gold / NOT DailyRun. OOS report-only.

Stamps:
  Control 42: BRT_Closed_260819120607.csv (DailyRun production whitelist)
  ALL (reuse, not re-run): BRT_Closed_260803154217.csv if present
  Candidate 764: live run_brt.bat on VZ_tradable_2010_adv2m_universe.csv
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import math
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    format_money,
    format_money_delta,
    overlay_ann_ror_max_dd,
    parse_number,
)
from vz_is_paul_universe_ab import (  # noqa: E402
    SORT_JS,
    _f,
    _parse_d,
    fmt_n,
    load_universe_symbols,
    sortable_th,
    split_is_oos,
)

DRIVE = ROOT / "drive"
OUT_DIR = DRIVE / "paul_experiments" / "brt_tradable_2010_adv2m_20260819"
UNIVERSE_CSV = DRIVE / "universes" / "VZ_tradable_2010_adv2m_universe.csv"
PROD_UNIV = DRIVE / "universes" / "BRT_universe.csv"
HTML_PATH = OUT_DIR / "compare.html"
BASELINE_PATH = OUT_DIR / "BASELINE.md"
IS_CUT = date(2024, 1, 1)
CONTROL_STAMP = "260819120607"
ALL_STAMP = "260803154217"
SHEET = 45_000.0
KNOWN_OTHER = {CONTROL_STAMP, ALL_STAMP}

# Eight of 42 fail the 2010/ADV$2m screen (IPO / listing age). Stay on whitelist.
TRAIT_FAIL_VS_42 = ("ABBV", "BABA", "CRWD", "META", "MPC", "PPTA", "SHOP", "TSLA")


def load_closed(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _parse_d(raw.get("DATE_OPENED") or raw.get("DATE OPENED") or "")
            if opened is None:
                continue
            sym = str(raw.get("SYMBOL") or "").strip().upper()
            if not sym:
                continue
            closed = _parse_d(raw.get("DATE_CLOSED") or raw.get("DATE CLOSED") or "")
            pnl = _f(raw.get("PNL_PCT") or raw.get("PNL %"))
            entry = _f(raw.get("ENTRY_PRICE") or raw.get("ENTRY PRICE"))
            stop = _f(raw.get("STOP_PRICE") or raw.get("STOP PRICE"))
            r_col = _f(raw.get("R_MULT") or raw.get("R_MULTIPLE"))
            risk_pct = ((entry - stop) / entry * 100.0) if entry > 0 and stop > 0 else 0.0
            r_mult = r_col if r_col else (pnl / risk_pct if risk_pct > 1e-9 else 0.0)
            rows.append(
                {
                    "sym": sym,
                    "opened": opened,
                    "closed": closed,
                    "pnl": pnl,
                    "r": r_mult,
                    "days": _f(raw.get("DAYS_HELD") or raw.get("DAYS HELD")),
                    "pnl_d": _f(raw.get("PNL_DOLLARS") or raw.get("PNL $")),
                    "exit": str(raw.get("EXIT_TYPE") or raw.get("EXIT TYPE") or "").strip(),
                    "win_pct": _f(raw.get("PNL_PCT") or raw.get("PNL %")),
                }
            )
    return rows


def book_stats(trades: list[dict[str, Any]], *, cash: float) -> dict[str, Any]:
    n = len(trades)
    empty = {
        "n": 0,
        "wins": 0,
        "losses": 0,
        "wr": 0.0,
        "avg_pnl": 0.0,
        "avg_pnl_wo_max": 0.0,
        "avg_r": 0.0,
        "pf": 0.0,
        "sheet": 0.0,
        "pnl_d": 0.0,
        "avg_days": 0.0,
        "med_days": 0.0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "expectancy": 0.0,
        "expectancy_pct": 0.0,
        "syms": 0,
        "ann_ror": float("nan"),
        "max_dd": float("nan"),
        "capital_days": 0.0,
        "profit_per_cd": 0.0,
        "exit_counts": {},
    }
    if n == 0:
        return empty
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    if n >= 2:
        mx = max(pnls)
        avg_wo = (sum(pnls) - mx) / (n - 1)
    else:
        avg_wo = sum(pnls) / n
    days = [t["days"] for t in trades]
    avg_days = sum(days) / n
    ov = overlay_ann_ror_max_dd(trades, cash=cash if cash > 0 else SHEET)
    pnl_d = float(ov.get("pnl_d") or sum(t["pnl_d"] for t in trades))
    cap_d = float(ov.get("capital_days") or sum(days))
    exits = Counter(str(t.get("exit") or "").strip() or "?" for t in trades)
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "wr": 100.0 * len(wins) / n,
        "avg_pnl": sum(pnls) / n,
        "avg_pnl_wo_max": avg_wo,
        "avg_r": sum(t["r"] for t in trades) / n,
        "pf": (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0),
        "sheet": sum(p / 100.0 * SHEET for p in pnls),
        "pnl_d": pnl_d,
        "avg_days": avg_days,
        "med_days": sorted(days)[n // 2],
        "avg_win": (sum(wins) / len(wins)) if wins else 0.0,
        "avg_loss": (sum(losses) / len(losses)) if losses else 0.0,
        "expectancy": pnl_d / n,
        "expectancy_pct": sum(pnls) / n,
        "syms": len({t["sym"] for t in trades}),
        "ann_ror": ov["ann_ror"],
        "max_dd": ov["max_dd"],
        "capital_days": cap_d,
        "profit_per_cd": (pnl_d / cap_d) if cap_d > 0 else 0.0,
        "exit_counts": dict(exits),
        "ann_ror_note": ov.get("note") or "",
    }


def load_report(stamp: str) -> Optional[dict[str, Any]]:
    path = DRIVE / f"BRT_Report_{stamp}.csv"
    if not path.is_file():
        return None
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return None
    return dict(rows[0])


def load_summary_agg(stamp: str) -> dict[str, Any]:
    path = DRIVE / f"BRT_Summary_{stamp}.csv"
    out = {
        "mean_paul": float("nan"),
        "sum_paul": float("nan"),
        "mean_fit": float("nan"),
        "sum_fit": float("nan"),
        "mean_fit_robust": float("nan"),
        "sum_fit_robust": float("nan"),
        "mean_wo_max": float("nan"),
        "mean_outlier": float("nan"),
        "mean_tpy": float("nan"),
        "n_sym": 0,
    }
    if not path.is_file():
        return out
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8-sig")))
    if not rows:
        return out
    pauls = [_f(r.get("PAUL_SCORE")) for r in rows]
    fits = [_f(r.get("FIT_SCORE")) for r in rows]
    rfs = [_f(r.get("FIT_SCORE_ROBUST")) for r in rows]
    wos = [_f(r.get("AVG_PNL_PCT_WO_MAX")) for r in rows]
    outs = [_f(r.get("OUTLIER_PCT_OF_WINS")) for r in rows]
    tpy = [_f(r.get("AVG_TRADES_PER_YEAR")) for r in rows]
    n = len(rows)
    out.update(
        {
            "mean_paul": sum(pauls) / n,
            "sum_paul": sum(pauls),
            "mean_fit": sum(fits) / n,
            "sum_fit": sum(fits),
            "mean_fit_robust": sum(rfs) / n,
            "sum_fit_robust": sum(rfs),
            "mean_wo_max": sum(wos) / n,
            "mean_outlier": sum(outs) / n,
            "mean_tpy": sum(tpy) / n,
            "n_sym": n,
        }
    )
    return out


def cash_from_report(rep: Optional[dict[str, Any]]) -> float:
    if not rep:
        return SHEET
    for k in ("brt_cash", "sheet_brt_cash", "effective_brt_cash"):
        v = parse_number(rep.get(k))
        if v is not None and v > 0:
            return float(v)
    return SHEET


def detect_live_stamp(explicit: str = "") -> str:
    if explicit:
        return explicit.strip()
    ts_file = DRIVE / "BRT_last_run_ts.txt"
    if ts_file.is_file():
        ts = ts_file.read_text(encoding="utf-8").strip()
        closed = DRIVE / f"BRT_Closed_{ts}.csv"
        if ts and ts not in KNOWN_OTHER and closed.is_file():
            return ts
    newest = ""
    newest_m = 0.0
    for p in DRIVE.glob("BRT_Closed_*.csv"):
        stem = p.stem.replace("BRT_Closed_", "")
        if stem.startswith("RL_"):
            continue
        if not stem.isdigit() or len(stem) != 12:
            continue
        if stem in KNOWN_OTHER:
            continue
        m = p.stat().st_mtime
        if m > newest_m:
            newest_m = m
            newest = stem
    return newest


def pack(
    name: str,
    trades: list[dict[str, Any]],
    overlay: Optional[dict[str, Any]],
    cash: float,
    summary: Optional[dict[str, Any]] = None,
    universe_n: int = 0,
) -> dict[str, Any]:
    is_t, oos_t = split_is_oos(trades)
    return {
        "name": name,
        "full": book_stats(trades, cash=cash),
        "is": book_stats(is_t, cash=cash),
        "oos": book_stats(oos_t, cash=cash),
        "overlay": overlay,
        "cash": cash,
        "summary": summary or {},
        "universe_n": universe_n,
        "n_trades_loaded": len(trades),
    }


def _nan(v: Any) -> bool:
    try:
        return v is None or (isinstance(v, float) and not math.isfinite(v))
    except TypeError:
        return True


def fmt_pct(v: Any, nd: int = 2) -> str:
    if _nan(v):
        return "—"
    return f"{float(v):,.{nd}f}"


def cell_for(key: str, stats: dict[str, Any]) -> str:
    money = {"sheet", "pnl_d", "expectancy", "profit_per_cd"}
    ints = {"n", "wins", "losses", "syms"}
    pct1 = {"wr"}
    pct2 = {"avg_pnl", "avg_pnl_wo_max", "avg_r", "pf", "avg_days", "med_days", "avg_win", "avg_loss", "expectancy_pct"}
    v = stats.get(key)
    if key in money:
        return format_money(v)
    if key in ints:
        return fmt_n(v, 0)
    if key in {"ann_ror", "max_dd"}:
        return fmt_pct(v, 2)
    if key in pct1:
        return fmt_n(v, 1)
    if key in pct2:
        return fmt_n(v, 2)
    if key == "capital_days":
        return fmt_n(v, 0)
    return fmt_n(v, 2)


def delta_txt(key: str, a: Any, b: Any) -> str:
    if _nan(a) or _nan(b):
        return "—"
    d = float(b) - float(a)
    money = {"sheet", "pnl_d", "expectancy", "profit_per_cd"}
    ints = {"n", "wins", "losses", "syms", "capital_days"}
    if key in money:
        return format_money_delta(d)
    if key in ints:
        return f"{d:+,.0f}"
    if key in {"wr"}:
        return f"{d:+.1f}"
    return f"{d:+.2f}"


def overlay_cell(ov: Optional[dict[str, Any]], key: str, kind: str) -> str:
    if not ov:
        return "—"
    raw = ov.get(key, "")
    if raw in ("", None):
        return "—"
    if kind == "money":
        return format_money(_f(raw))
    if kind == "int":
        return fmt_n(_f(raw), 0)
    if kind == "pct1":
        return fmt_n(_f(raw), 1)
    return fmt_n(_f(raw), 2)


def verdict_for(
    trad: dict[str, Any],
    prod: dict[str, Any],
    all_p: Optional[dict[str, Any]],
) -> tuple[str, str]:
    """Honest tape vs production whitelist. Do not KEEP because 42 looks prettier."""
    t_oos = trad["oos"]
    p_oos = prod["oos"]
    notes = []
    notes.append(
        "Production 42 is a whitelist, not a Paul/FIT cut. Eight names fail the 2010 screen "
        f"({', '.join(TRAIT_FAIL_VS_42)}) and stay on the 42 list only. Do not KEEP 42 as the "
        "honest tape because it looks prettier (selection)."
    )
    if all_p:
        a_oos = all_p["oos"]
        d_wr = t_oos["wr"] - a_oos["wr"]
        d_avg = t_oos["avg_pnl"] - a_oos["avg_pnl"]
        vs_prod_wr = t_oos["wr"] - p_oos["wr"]
        notes.append(
            f"OOS vs prior-wide: ΔWR {d_wr:+.1f}pp, ΔAvgPnL {d_avg:+.2f}pp "
            f"(prior-wide OOS WR {a_oos['wr']:.1f}%, AvgPnL {a_oos['avg_pnl']:.2f}; "
            f"{all_p['full']['syms']} names traded). "
            f"Overlay Max DD tradable {trad['full']['max_dd']:.2f}% vs prior-wide {all_p['full']['max_dd']:.2f}% "
            f"vs 42 {prod['full']['max_dd']:.2f}%."
        )
        notes.append(
            f"OOS vs 42 whitelist: ΔWR {vs_prod_wr:+.1f}pp — 42 is selected; do not treat that gap as an "
            "adopt-42 signal. OOS is report-only; do not retune."
        )
        # 764 is the honest tape analog. Gold is dismissed if it looks like a wide book
        # (lower WR / Ann ROR vs 42, DD not better). KEEP research tape if it remains a
        # fair 2010 listing/liquidity book vs the prior-wide stamp (no extra collapse required).
        collapsed_vs_wide = d_wr < -2.0 or d_avg < -0.40
        like_wide_vs_42 = vs_prod_wr < -1.5 or (
            not _nan(trad["full"]["ann_ror"])
            and not _nan(prod["full"]["ann_ror"])
            and trad["full"]["ann_ror"] + 2.0 < prod["full"]["ann_ror"]
        )
        if like_wide_vs_42:
            extra = (
                " 764-name quality is a wide tape vs the 42 whitelist (lower WR / Ann ROR). "
                "DISMISS as gold or DailyRun replacement (same class as VZ ALL vs a selected book). "
            )
            if collapsed_vs_wide:
                extra += (
                    "Vs the reused prior-wide stamp, OOS WR/AvgPnL also soften — treat that stamp as "
                    f"{all_p['full']['syms']} names traded (not a full CSV ALL) and older vintage; still not a quality upgrade. "
                )
            extra += (
                "KEEP as the honest 2010-tradable research tape analog of VZ tradable — not a quality upgrade."
            )
            return ("DISMISS gold / KEEP research tape", " ".join(notes) + extra)
        if t_oos["wr"] >= a_oos["wr"] + 2.0 and t_oos["avg_pnl"] >= a_oos["avg_pnl"] + 0.30:
            return (
                "KEEP research tape",
                " ".join(notes)
                + " Tradable OOS quality beats the prior-wide stamp without using 42-whitelist beauty. "
                "Still research-only — not gold / not DailyRun.",
            )
        return (
            "HOLD research tape",
            " ".join(notes)
            + " Mixed vs prior-wide. HOLD as tape definition; do not gold or DailyRun. Do not retune OOS.",
        )
    # No ALL column: still do not KEEP vs 42 on beauty.
    vs_prod_wr = t_oos["wr"] - p_oos["wr"]
    notes.append(
        f"No live ALL reuse in the verdict table was missing — OOS vs 42 ΔWR {vs_prod_wr:+.1f}pp. "
        "ALL Closed 260803154217 should be the comparable wide tape."
    )
    return (
        "HOLD research tape",
        " ".join(notes) + " Not gold / not DailyRun.",
    )


def write_html(packed: list[dict[str, Any]], verdict: str, why: str, extra: dict[str, Any]) -> None:
    specs = [
        ("Universe size (file)", "universe_n_row"),
        ("Names traded", "syms"),
        ("Closed N", "n"),
        ("Wins", "wins"),
        ("Losses", "losses"),
        ("Win %", "wr"),
        ("Avg PnL %", "avg_pnl"),
        ("Avg PnL % wo max", "avg_pnl_wo_max"),
        ("Avg win %", "avg_win"),
        ("Avg loss %", "avg_loss"),
        ("AvgR", "avg_r"),
        ("Profit factor", "pf"),
        ("Sheet PnL $", "sheet"),
        ("Total PnL $ (Closed)", "pnl_d"),
        ("Expectancy $", "expectancy"),
        ("Expectancy %", "expectancy_pct"),
        ("Ann ROR % (Closed overlay)", "ann_ror"),
        ("Max DD % (Closed overlay)", "max_dd"),
        ("Capital days", "capital_days"),
        ("Profit / capital day $", "profit_per_cd"),
        ("Avg days held", "avg_days"),
        ("Median days held", "med_days"),
    ]
    trad = packed[-1]
    ctrl = packed[0]
    all_idx = 1 if len(packed) >= 3 else None
    splits = (
        ("full", "Full book"),
        ("is", "IS (entry &lt; 2024-01-01)"),
        ("oos", "OOS (entry ≥ 2024-01-01) — report-only"),
    )
    chunks: list[str] = []
    for sk, slabel in splits:
        body = ""
        for label, key in specs:
            body += f"<tr><td>{html_mod.escape(label)}</td>"
            for p in packed:
                if key == "universe_n_row":
                    body += f'<td class="num">{p.get("universe_n") or "—"}</td>'
                else:
                    body += f'<td class="num">{cell_for(key, p[sk])}</td>'
            if key == "universe_n_row":
                d42 = (trad.get("universe_n") or 0) - (ctrl.get("universe_n") or 0)
                body += f'<td class="num">{d42:+,}</td>'
                if all_idx is not None:
                    da = (trad.get("universe_n") or 0) - (packed[all_idx].get("universe_n") or 0)
                    body += f'<td class="num">{da:+,}</td>'
            else:
                body += f'<td class="num">{delta_txt(key, ctrl[sk][key], trad[sk][key])}</td>'
                if all_idx is not None:
                    body += f'<td class="num">{delta_txt(key, packed[all_idx][sk][key], trad[sk][key])}</td>'
            body += "</tr>"
        head = sortable_th("Metric", "text") + "".join(sortable_th(p["name"], "num") for p in packed)
        head += sortable_th("Δ 764 vs 42", "num")
        if all_idx is not None:
            head += sortable_th("Δ 764 vs ALL", "num")
        chunks.append(
            f"<h2>{slabel}</h2>"
            f'<p class="small">Click column headers to sort. Ann ROR / Max DD on IS and OOS are Closed-overlay '
            f"(sheet/brt_cash + exit-date equity replay at $500k), not a separate live IS/OOS Report.</p>"
            f'<table class="sortable"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'
        )

    ov_specs = [
        ("Ann ROR % (Report)", "Ann_ROR", "pct1"),
        ("Max DD % (Report)", "Max_DD", "pct1"),
        ("Aggressive Total PnL $", "Aggressive_Total_PNL", "money"),
        ("Aggressive Max DD %", "Aggressive_Max_DD", "pct1"),
        ("Report Total PnL $", "Total_PNL", "money"),
        ("Report sheet PnL $", "sheet_PnL", "money"),
        ("Capital days", "Capital_Days", "int"),
        ("Profit / capital day $", "Profit_Per_Capital_Day", "money"),
        ("Max positions", "Max_Positions", "int"),
        ("Avg positions", "Avg_Positions", "pct2"),
        ("Losing streak", "Losing_Streak", "int"),
        ("Expectancy $", "Expectancy", "money"),
        ("% PnL top 10", "Pct_PNL_Top10", "pct1"),
        ("% PnL max symbol", "Pct_PNL_Max_Symbol", "pct1"),
        ("% PnL max trade", "Pct_PNL_Max_Trade", "pct1"),
        ("brt_cash", "brt_cash", "money"),
        ("stop_pct", "stop_pct", "pct2"),
        ("target_pct", "target_pct", "pct2"),
        ("too_high_multiplier", "too_high_multiplier", "pct2"),
        ("band_pct", "band_pct", "pct2"),
        ("growth_filter_enabled", "growth_filter_enabled", "text"),
        ("min_market_cap", "min_market_cap", "pct2"),
        ("max_market_cap", "max_market_cap", "pct2"),
    ]
    ov_body = ""
    for label, key, kind in ov_specs:
        ov_body += f"<tr><td>{html_mod.escape(label)}</td>"
        for p in packed:
            if kind == "text":
                ov_body += f"<td>{html_mod.escape(str((p.get('overlay') or {}).get(key, '—')))}</td>"
            else:
                ov_body += f'<td class="num">{overlay_cell(p.get("overlay"), key, kind)}</td>'
        ov_body += "</tr>"
    ov_head = sortable_th("Live Report overlay", "text") + "".join(
        sortable_th(p["name"], "num") for p in packed
    )

    sm_specs = [
        ("Summary names", "n_sym"),
        ("Σ Paul Score", "sum_paul"),
        ("Mean Paul Score", "mean_paul"),
        ("Σ FIT_SCORE", "sum_fit"),
        ("Mean FIT_SCORE", "mean_fit"),
        ("Σ FIT_SCORE_ROBUST", "sum_fit_robust"),
        ("Mean FIT_SCORE_ROBUST", "mean_fit_robust"),
        ("Mean AVG_PNL_PCT_WO_MAX", "mean_wo_max"),
        ("Mean OUTLIER_PCT_OF_WINS", "mean_outlier"),
        ("Mean AVG_TRADES_PER_YEAR", "mean_tpy"),
    ]
    sm_body = ""
    for label, key in sm_specs:
        sm_body += f"<tr><td>{html_mod.escape(label)}</td>"
        for p in packed:
            sm = p.get("summary") or {}
            v = sm.get(key, float("nan"))
            nd = 0 if key == "n_sym" else 2
            sm_body += f'<td class="num">{fmt_n(v, nd) if not _nan(v) else "—"}</td>'
        sm_body += "</tr>"
    sm_head = sortable_th("Symbol aggregates (Summary)", "text") + "".join(
        sortable_th(p["name"], "num") for p in packed
    )

    exit_keys: list[str] = []
    seen: set[str] = set()
    for p in packed:
        for k in p["full"].get("exit_counts", {}):
            if k not in seen:
                seen.add(k)
                exit_keys.append(k)
    exit_body = ""
    for ek in sorted(exit_keys):
        exit_body += f"<tr><td>{html_mod.escape(ek)}</td>"
        for p in packed:
            n = int(p["full"].get("exit_counts", {}).get(ek, 0))
            tot = max(int(p["full"]["n"]), 1)
            exit_body += f'<td class="num">{n:,} ({100.0 * n / tot:.1f}%)</td>'
        exit_body += "</tr>"
    exit_head = sortable_th("EXIT_TYPE (full)", "text") + "".join(
        sortable_th(p["name"], "num") for p in packed
    )

    fail8 = ", ".join(TRAIT_FAIL_VS_42)
    all_note = extra.get("all_note", "")
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>BRT tradable 2010 / ADV$2m vs production 42</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 24px; color: #1a1a1a; max-width: 1600px; }}
h1 {{ font-size: 1.35rem; margin: 0 0 8px; }}
h2 {{ font-size: 1.1rem; margin: 28px 0 8px; }}
.sub, .small {{ color: #555; line-height: 1.45; }}
.card {{ background: #f7f8fa; border: 1px solid #e2e5ea; padding: 12px 14px; border-radius: 6px; margin: 12px 0; }}
table.sortable {{ border-collapse: collapse; width: 100%; font-size: 0.88rem; margin: 8px 0 16px; }}
table.sortable th, table.sortable td {{ border-bottom: 1px solid #e5e7eb; padding: 6px 8px; text-align: left; }}
table.sortable th {{ background: #f0f2f5; }}
td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
th.sortable-th {{ cursor: pointer; user-select: none; white-space: nowrap; }}
th.sortable-th:hover {{ background: #e4e4dc; }}
.sort-ind {{ display: inline-block; width: 0.9em; margin-left: 4px; color: #94a3b8; font-size: 10px; }}
th.sort-asc .sort-ind::after {{ content: "▲"; color: #334155; }}
th.sort-desc .sort-ind::after {{ content: "▼"; color: #334155; }}
code {{ background: #eee; padding: 1px 4px; border-radius: 3px; }}
</style>
</head>
<body>
<h1>BRT tradable universe (2010 / ADV$2m, 764) vs production 42</h1>
<p class="sub">Universe identity only. Knobs = current <code>run_brt.bat</code>:
<code>stop_pct=0.934</code>, <code>target_pct=1.21</code>, <code>too_high_multiplier=0</code>,
<code>band_pct=0.0154</code>, strong-pivot 7/8.1% and 7/10.8%, <code>breakout_bars=100</code>,
tight-range 35%/105, sheet touch + red-to-green, growth filter on, caps off
(<code>min_market_cap=0</code>, <code>max_market_cap=0</code>). Per-symbol overlay JSON is empty <code>{{}}</code>.
IS = entry &lt; 2024-01-01; OOS report-only. Judge quality (WR, Avg PnL%, AvgR, PF, Ann ROR, Max DD), not trade count.
<strong>Not gold / not DailyRun.</strong> Click column headers to sort.</p>
<div class="card">
<strong>Verdict: {html_mod.escape(verdict)}</strong>
<p>{html_mod.escape(why)}</p>
<p>Eight of 42 fail the 2010 screen and stay on the whitelist only: <code>{html_mod.escape(fail8)}</code>.
Production CSV <code>drive/universes/BRT_universe.csv</code> was not overwritten.
Tradable names: <code>drive/universes/VZ_tradable_2010_adv2m_universe.csv</code>.</p>
<p>{html_mod.escape(all_note)}</p>
</div>
{"".join(chunks)}
<h2>Report overlay (full-book capital path)</h2>
<p class="small">ALL stamp is older vintage (2026-08-03) — knobs match; bars through that date only. Click headers to sort.</p>
<table class="sortable"><thead><tr>{ov_head}</tr></thead><tbody>{ov_body}</tbody></table>
<h2>Summary aggregates (Paul / FIT)</h2>
<p class="small">Click column headers to sort. Mean FIT/Paul is not the KEEP trigger; quality rows above are.</p>
<table class="sortable"><thead><tr>{sm_head}</tr></thead><tbody>{sm_body}</tbody></table>
<h2>Exit mix</h2>
<p class="small">Click column headers to sort.</p>
<table class="sortable"><thead><tr>{exit_head}</tr></thead><tbody>{exit_body}</tbody></table>
<p class="small">Stamp folder: <code>drive/paul_experiments/brt_tradable_2010_adv2m_20260819/</code>
&nbsp; Freeze: <code>BASELINE.md</code>
&nbsp; Initial account for overlay Max DD: ${DEFAULT_INITIAL_ACCOUNT:,.0f}</p>
{SORT_JS}
</body>
</html>
"""
    HTML_PATH.write_text(html, encoding="utf-8")


def write_baseline(packed: list[dict[str, Any]], verdict: str, why: str, extra: dict[str, Any]) -> None:
    ctrl = packed[0]
    trad = packed[-1]
    all_p = packed[1] if len(packed) >= 3 else None

    def snap(p: dict[str, Any], sk: str) -> str:
        s = p[sk]
        ar = s["ann_ror"]
        dd = s["max_dd"]
        ars = f"{ar:.2f}" if not _nan(ar) else "—"
        dds = f"{dd:.2f}" if not _nan(dd) else "—"
        return (
            f"{s['n']} / {s['wr']:.1f}% / {s['avg_pnl']:.2f} / {s['avg_r']:.2f} / {s['pf']:.2f} / "
            f"AnnROR {ars}% / MaxDD {dds}%"
        )

    ov_lines = []
    for p in packed:
        ov = p.get("overlay") or {}
        if ov:
            ov_lines.append(
                f"- {p['name']}: Report Ann ROR {_f(ov.get('Ann_ROR')):.2f}% / Max DD {_f(ov.get('Max_DD')):.2f}% "
                f"/ Aggressive Max DD {_f(ov.get('Aggressive_Max_DD')):.2f}% / stamp `{extra.get('stamps', {}).get(p['name'], '')}`"
            )
    all_md = ""
    if all_p:
        all_md = (
            f"| ALL (reuse `{ALL_STAMP}`, vintage 2026-08-03) | {snap(all_p, 'full')} | {snap(all_p, 'is')} | {snap(all_p, 'oos')} |\n"
        )
    md = f"""# BASELINE — BRT tradable 2010 / ADV$2m (2026-08-19)

**Status:** RESEARCH only. **Not gold. Not DailyRun-wired.** Production `BRT_universe.csv` was **not** overwritten.

## Hypothesis (one knob)

Universe identity only. Same BRT freeze as current `run_brt.bat`. Compare the **42-name production whitelist** vs a **764-name 2010-tradable tape** (listing age + price + dollar volume, no BRT PnL / Paul / FIT). Optional third column: existing ALL Closed (not re-run).

## Screen freeze (selection honesty)

Universe file: `drive/universes/VZ_tradable_2010_adv2m_universe.csv` (reuse VZ tradable CSV).

- First bar on or before **2010-01-04**
- As-of **2023-12-29**: Close ≥ **$5**; 20-session ADV$ ≥ **$2,000,000**
- **764** names. Traits only — not a BRT winner cut.

### Eight of 42 fail this screen

These stay on the **42-name production whitelist** (`drive/universes/BRT_universe.csv`) and are **not** on the trait list:

`ABBV`, `BABA`, `CRWD`, `META`, `MPC`, `PPTA`, `SHOP`, `TSLA`

Do not treat the 42-name book as an honest 2010-tradable tape. It is a whitelist. Do not KEEP 42 because it looks prettier (selection).

## Engine freeze (same as `run_brt.bat` — do not mutate)

- `stop_pct=0.934`, `target_pct=1.21`, `too_high_multiplier=0`, `band_pct=0.0154`
- Strong-pivot: 7 bars / 8.1% pre, 7 bars / 10.8% post
- `breakout_bars=100`, tight-range 35% / 105
- `brt_sheet_touch=true`, `sheet_red_to_green_entry_enabled=true`
- `growth_filter_enabled=true`
- Caps **off**: `min_market_cap=0`, `max_market_cap=0`
- `min_spy_compare_1y_at_trigger=-1000`, `min_ind_score=-1`, `compute_beta=true`, `brt_zones=true`, `yh_zones=false`
- `--aggressive`, `--no-regression`, `--print-zones`, 32 workers
- Per-symbol overlay: `Per_Symbol_Optimized_Settings_Approved_Latest.json` is empty `{{}}` (effectively off)

Do not silently mutate this freeze. New stamp or explicit delta if knobs change.

## Compare stamps

- Production 42: `drive/BRT_Closed_{CONTROL_STAMP}.csv` / `BRT_Report_{CONTROL_STAMP}.csv`
- Tradable 764 live: `drive/BRT_Closed_{extra.get('live_stamp', '?')}.csv`
- ALL reuse (not re-run): `drive/BRT_Closed_{ALL_STAMP}.csv` — same core knobs; **data vintage 2026-08-03** (older last bar than the 42 and 764 sleeves). {extra.get('all_note', '')}

IS / OOS: `entry_date < 2024-01-01` vs `>= 2024-01-01`. OOS is **report-only** — do not retune universe or knobs on OOS.

## Snapshot (Closed N / WR / AvgPnL% / AvgR / PF / overlay Ann ROR / overlay Max DD)

| Book | Full | IS | OOS |
|------|------|----|-----|
| Production 42 | {snap(ctrl, 'full')} | {snap(ctrl, 'is')} | {snap(ctrl, 'oos')} |
{all_md}| Tradable 764 | {snap(trad, 'full')} | {snap(trad, 'is')} | {snap(trad, 'oos')} |

Report (full-book capital path):

{chr(10).join(ov_lines) if ov_lines else '(no Report overlay)'}

IS/OOS Ann ROR and Max DD are Closed-overlay (`compare_format.overlay_ann_ror_max_dd`) using stamp `brt_cash` and $500k initial account. Full-book Report Ann ROR / Max DD remain the live aggressive-path numbers.

## Verdict

**{verdict}**

{why}

Promotion bar: research candidate only. Not gold. Do not wire DailyRun from this stamp. Do not replace `BRT_universe.csv`.
"""
    BASELINE_PATH.write_text(md, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live-stamp", default="", help="764-name live BRT stamp")
    ap.add_argument("--control-stamp", default=CONTROL_STAMP)
    ap.add_argument("--all-stamp", default=ALL_STAMP)
    ap.add_argument("--no-all", action="store_true", help="Omit ALL column even if Closed exists")
    args = ap.parse_args()

    trad_list = load_universe_symbols(UNIVERSE_CSV)
    prod_list = load_universe_symbols(PROD_UNIV)
    trad_syms = set(trad_list)
    prod_syms = set(prod_list)

    live_stamp = detect_live_stamp(args.live_stamp)
    if not live_stamp:
        print("ERROR: no live BRT Closed stamp for tradable run", file=sys.stderr)
        return 1
    live_path = DRIVE / f"BRT_Closed_{live_stamp}.csv"
    if not live_path.is_file():
        print(f"ERROR: missing {live_path}", file=sys.stderr)
        return 1

    ctrl_trades = load_closed(DRIVE / f"BRT_Closed_{args.control_stamp}.csv")
    live_trades = load_closed(live_path)
    ctrl_rep = load_report(args.control_stamp)
    live_rep = load_report(live_stamp)
    ctrl_cash = cash_from_report(ctrl_rep)
    live_cash = cash_from_report(live_rep)

    packed = [
        pack(
            f"Production 42 ({args.control_stamp})",
            ctrl_trades,
            ctrl_rep,
            ctrl_cash,
            load_summary_agg(args.control_stamp),
            universe_n=len(prod_list),
        ),
    ]
    all_note = "ALL column omitted."
    all_path = DRIVE / f"BRT_Closed_{args.all_stamp}.csv"
    if not args.no_all and all_path.is_file():
        all_trades = load_closed(all_path)
        all_rep = load_report(args.all_stamp)
        packed.append(
            pack(
                f"Prior wide {len({t['sym'] for t in all_trades})}n ({args.all_stamp})",
                all_trades,
                all_rep,
                cash_from_report(all_rep),
                load_summary_agg(args.all_stamp),
                universe_n=len({t["sym"] for t in all_trades}),
            )
        )
        all_note = (
            f"Prior-wide reused from disk (`BRT_Closed_{args.all_stamp}.csv`, 2026-08-03 vintage, "
            f"{len({t['sym'] for t in all_trades})} names traded — not a full CSV ALL). "
            "Not re-run. Core knobs match current bat; last bar is older than the 42 and 764 sleeves."
        )
    packed.append(
        pack(
            f"Tradable 764 ({live_stamp})",
            live_trades,
            live_rep,
            live_cash,
            load_summary_agg(live_stamp),
            universe_n=len(trad_list),
        )
    )

    all_p = packed[1] if len(packed) >= 3 else None
    verdict, why = verdict_for(packed[-1], packed[0], all_p)
    extra = {
        "all_note": all_note,
        "live_stamp": live_stamp,
        "stamps": {p["name"]: "" for p in packed},
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_html(packed, verdict, why, extra)
    write_baseline(packed, verdict, why, extra)

    fail8 = sorted(prod_syms - trad_syms)
    print("TRAIT_FAIL_VS_42", fail8)
    print("EXPECTED", list(TRAIT_FAIL_VS_42))

    def dump(tag: str, p: dict[str, Any]) -> None:
        for sk in ("full", "is", "oos"):
            s = p[sk]
            ar = s["ann_ror"]
            dd = s["max_dd"]
            print(
                f"{tag:36} {sk:4} N={s['n']:5} names={s['syms']:4} "
                f"WR={s['wr']:5.1f} avg={s['avg_pnl']:6.2f} avgR={s['avg_r']:5.2f} "
                f"PF={s['pf']:4.2f} AnnROR={ar if not _nan(ar) else float('nan'):7.2f} "
                f"MaxDD={dd if not _nan(dd) else float('nan'):6.2f}"
            )

    for p in packed:
        dump(p["name"], p)
        ov = p.get("overlay") or {}
        if ov:
            print(
                f"{'  Report':36}      AnnROR={_f(ov.get('Ann_ROR')):.2f} "
                f"MaxDD={_f(ov.get('Max_DD')):.2f}"
            )
    print("LIVE_STAMP", live_stamp)
    print("VERDICT", verdict)
    print("HTML", HTML_PATH)
    print("BASELINE", BASELINE_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
