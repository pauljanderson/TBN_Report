#!/usr/bin/env python3
"""META WPBR cascade sim: WHY stamp 260722105625 skipped free-slot raw fills.

Replays DailyRun/MarkTen WPBR path (run_wpbr-like + start_date/target/stop from
reconcile stamp 260722105625) and classifies every raw wpbr_entry_opportunity
fill that is not a closed-trade entry.
"""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "stock_analysis"))

import rocket_brt as rb  # noqa: E402
from wpbr_zones import compute_wpbr_touch_stream  # noqa: E402

DATA = REPO / "data" / "newdata" / "data" / "META.csv"
SPY = REPO / "data" / "newdata" / "data" / "SPY.csv"
MIN_DATE = "2016-01-01"
FOCUS = {
    "2018-06-12",
    "2019-12-04",
    "2020-03-20",
    "2021-04-21",
    "2025-08-25",
    "2025-08-27",
}

# MarkTen stamp 260722105625 + run_wpbr.bat zone params
WPBR_STREAM_KW = dict(
    band_pct=0.015,
    strong_pre_pivot_bars=3,
    strong_pre_pivot_pct=0.10,
    strong_post_pivot_bars=3,
    strong_post_pivot_pct=0.10,
    strong_pivot_mode="either",
    breakout_confirmation=0.03,
    max_days_after_retest=2,
    retest_mode="stop_looking",
    zone_price_round_decimals=2,
)


def _ymd(s: object) -> str:
    if s is None:
        return ""
    t = str(s).strip()
    if not t:
        return ""
    if len(t) >= 8 and t[:8].isdigit() and "-" not in t[:8]:
        return f"{t[:4]}-{t[4:6]}-{t[6:8]}"
    try:
        return pd.Timestamp(t).strftime("%Y-%m-%d")
    except Exception:
        return t


def _bar_date(idx: pd.DatetimeIndex, b: object) -> str | None:
    try:
        bi = int(b)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if bi < 0 or bi >= len(idx):
        return None
    return idx[bi].strftime("%Y-%m-%d")


def make_cfg() -> rb.BRTConfig:
    base = asdict(rb.BRTConfig())
    base.update(
        {
            "wpbr_zones": True,
            "brt_zones": False,
            "yh_zones": False,
            "vec_zones": False,
            "band_pct": 0.015,
            "strong_pre_pivot_bars": 3,
            "strong_pre_pivot_pct": 0.10,
            "strong_post_pivot_bars": 3,
            "strong_post_pivot_pct": 0.10,
            "strong_pivot_mode": "either",
            "wpbr_breakout_confirmation": 0.03,
            "wpbr_max_days_after_retest": 2,
            "wpbr_retest_mode": "stop_looking",
            "wpbr_second_chance_after_win": False,
            "growth_filter_enabled": False,
            "min_spy_compare_1y_at_trigger": -1000.0,
            "ind_score_weights_path": "",
            "too_high_multiplier": 0.0,
            "target_pct": 1.22,
            "stop_pct": 0.89,
            "stop_pct_is_multiplier": True,
            "entry_start_date": "2016-01-01",
            "use_indicators": False,
            "indicator_buy": "off",
            "zone_price_round_decimals": 2,
        }
    )
    return rb.BRTConfig(**base)


def load_meta() -> pd.DataFrame:
    df = pd.read_csv(DATA, index_col=0, parse_dates=True)
    df = df.sort_index()
    return df


def collect_raw_fills(df: pd.DataFrame) -> list[dict[str, Any]]:
    idx = pd.DatetimeIndex(df.index)
    stream = compute_wpbr_touch_stream(df, **WPBR_STREAM_KW)
    events = {str(e.get("wpbr_zone_id", "")): e for e in (stream.get("wpbr_zone_events") or [])}
    fills: list[dict[str, Any]] = []
    for opp in stream.get("wpbr_entry_opportunities") or []:
        fill_d = _bar_date(idx, opp.get("entry_fill_bar"))
        if not fill_d or fill_d < MIN_DATE:
            continue
        zid = str(opp.get("wpbr_zone_id", "") or "")
        ev = events.get(zid) or {}
        fills.append(
            {
                "fill": fill_d,
                "signal": _bar_date(idx, opp.get("entry_signal_bar")),
                "retest": _bar_date(idx, opp.get("retest_bar")),
                "zone_id": zid,
                "zlow": float(opp.get("zone_lower", float("nan"))),
                "zhigh": float(opp.get("zone_upper", float("nan"))),
                "signal_bar": int(opp.get("entry_signal_bar", -1)),
                "fill_bar": int(opp.get("entry_fill_bar", -1)),
                "pivot_monday": _ymd(ev.get("pivot_monday")),
                "opp": opp,
            }
        )
    fills.sort(key=lambda r: (r["fill"], r["zone_id"]))
    return fills


def run_backtest(df: pd.DataFrame, cfg: rb.BRTConfig, trace_dates: list[str] | None = None):
    ph, pl, php, plp = rb.compute_pivots(
        df,
        cfg.pivot_k,
        cfg.pivot_d,
        cfg.pivot_disp,
        cfg.pivot_m,
        realtime_filter_enabled=cfg.realtime_filter_enabled,
    )
    struct = rb.compute_market_structure(df, ph, pl, php, plp)
    l3 = rb.build_level3_for_cfg(df, cfg, ph, pl, php, plp)
    bench = None
    if SPY.exists():
        spy = pd.read_csv(SPY, index_col=0, parse_dates=True).sort_index()
        bench = spy
    if trace_dates:
        rb.set_trace_target("META", trace_dates)
    else:
        rb.set_trace_target(None, None)
    block_reasons: dict[str, int] = {}
    buf = io.StringIO()
    with redirect_stdout(buf):
        out = rb.run_brt_backtest(
            "META",
            df,
            cfg,
            php,
            plp,
            struct,
            l3,
            benchmark_df=bench,
            profile_block_reasons=block_reasons,
        )
    rb.set_trace_target(None, None)
    closed = out[0]
    open_trade = out[1]
    return closed, open_trade, buf.getvalue(), l3, block_reasons


def closed_rows(closed) -> list[dict[str, Any]]:
    rows = []
    for t in closed:
        rows.append(
            {
                "entry": _ymd(getattr(t, "date_opened", "")),
                "exit": _ymd(getattr(t, "date_closed", "")),
                "entry_px": float(getattr(t, "entry_price", 0.0) or 0.0),
                "exit_px": float(getattr(t, "exit_price", 0.0) or 0.0),
                "exit_type": str(getattr(t, "exit_type", "") or ""),
                "pnl_pct": float(getattr(t, "pnl_pct", 0.0) or 0.0),
                "zone_id": str(getattr(t, "wpbr_zone_id", "") or ""),
                "signal_date": _ymd(getattr(t, "close_above_date", "")),
            }
        )
    rows.sort(key=lambda r: r["entry"])
    return rows


def occupying_trade(entry: str, trades: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Trade whose hold interval covers fill date (entry <= fill <= exit)."""
    for t in trades:
        if not t["entry"] or not t["exit"]:
            continue
        if t["entry"] <= entry <= t["exit"]:
            return t
    return None


def prior_open_on_signal(signal: str, trades: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Open trade on signal bar (entry <= signal < exit) — pending dropped while open."""
    for t in trades:
        if not t["entry"] or not t["exit"]:
            continue
        if t["entry"] <= signal < t["exit"]:
            return t
        # same-day exit then reentry is allowed after exit handling; treat exit day as free after exit
        if t["entry"] <= signal <= t["exit"] and signal < t["exit"]:
            return t
    return None


def gate_snapshot(df: pd.DataFrame, signal: str) -> dict[str, Any]:
    """Local OHLC / red-to-green snapshot on signal bar (default WPBR gate still applied)."""
    idx = pd.DatetimeIndex(df.index)
    iso = {d.strftime("%Y-%m-%d"): i for i, d in enumerate(idx)}
    if signal not in iso:
        return {"ok": False, "reason": "signal_not_in_ohlc"}
    i = iso[signal]
    o = float(df["Open"].iloc[i])
    h = float(df["High"].iloc[i])
    lo = float(df["Low"].iloc[i])
    c = float(df["Close"].iloc[i])
    out: dict[str, Any] = {
        "ok": True,
        "signal": signal,
        "O": o,
        "H": h,
        "L": lo,
        "C": c,
        "green": c > o,
    }
    if i >= 1:
        po = float(df["Open"].iloc[i - 1])
        pc = float(df["Close"].iloc[i - 1])
        out["prior_date"] = idx[i - 1].strftime("%Y-%m-%d")
        out["prior_O"] = po
        out["prior_C"] = pc
        out["prior_red"] = pc <= po
        out["red_to_green"] = (pc <= po) and (c > o)
    else:
        out["red_to_green"] = False
    return out


def parse_trace_blocks(trace: str, zone_id: str | None = None) -> list[str]:
    lines = []
    for ln in trace.splitlines():
        if "[TRACE]" not in ln:
            continue
        if zone_id and zone_id.split("|")[0] not in ln and "zc=" in ln:
            # keep all TRACE lines for the day; zone filter is weak
            pass
        lines.append(ln.strip())
    return lines


def classify_skip(
    raw: dict[str, Any],
    closed: list[dict[str, Any]],
    df: pd.DataFrame,
    trace_by_signal: dict[str, str],
) -> dict[str, Any]:
    fill = raw["fill"]
    signal = raw["signal"] or ""
    ser = next((t for t in closed if t["entry"] == fill), None)
    if ser:
        return {
            "class": "SERIALIZED",
            "detail": f"closed entry {ser['entry']}->{ser['exit']} zone={ser['zone_id']}",
            "blocker": ser,
            "gates": None,
            "trace": [],
        }

    # Same zone serialized later via close_above_window gate retries (e.g. 8/25 raw → 8/27 entry)
    later_same = [
        t
        for t in closed
        if t["zone_id"] and t["zone_id"] == raw["zone_id"] and t["entry"] > fill
    ]
    if later_same:
        t = later_same[0]
        return {
            "class": "DELAYED_SAME_ZONE_FILL",
            "detail": (
                f"raw fill {fill} not taken; same zone serialized later as {t['entry']} "
                f"(close_above~{t['signal_date']}) after gate retries within close_above_window"
            ),
            "blocker": t,
            "gates": gate_snapshot(df, signal) if signal else None,
            "trace": [],
        }

    occ = occupying_trade(fill, closed)
    if occ:
        return {
            "class": "OVERLAPPED_OPEN_POSITION",
            "detail": (
                f"fill {fill} falls inside open trade {occ['entry']}->{occ['exit']} "
                f"zone={occ['zone_id']}"
            ),
            "blocker": occ,
            "gates": gate_snapshot(df, signal) if signal else None,
            "trace": [],
        }

    # pending dropped while open: open on signal day (engine drops from_retest_row pending)
    if signal:
        sig_occ = None
        for t in closed:
            if t["entry"] <= signal < t["exit"]:
                sig_occ = t
                break
        if sig_occ:
            return {
                "class": "PENDING_DROPPED_WHILE_OPEN",
                "detail": (
                    f"signal {signal} while open {sig_occ['entry']}->{sig_occ['exit']} "
                    f"zone={sig_occ['zone_id']} (from_retest_row pending not retained)"
                ),
                "blocker": sig_occ,
                "gates": gate_snapshot(df, signal),
                "trace": [],
            }

    gates = gate_snapshot(df, signal) if signal else None
    tr = parse_trace_blocks(trace_by_signal.get(signal or fill, ""))
    block_lines = [ln for ln in tr if "block:" in ln or "skip all new-entry" in ln]
    if block_lines:
        reasons = []
        for ln in block_lines:
            if "block:" in ln:
                reasons.append(ln.split("block:", 1)[1].strip())
            else:
                reasons.append(ln)
        return {
            "class": "GATE_BLOCKED",
            "detail": "; ".join(dict.fromkeys(reasons))[:500],
            "blocker": None,
            "gates": gates,
            "trace": block_lines[:12],
        }

    # Heuristic: default sheet_red_to_green is ON and NOT bypassed for WPBR
    if gates and gates.get("ok") and not gates.get("red_to_green"):
        return {
            "class": "GATE_BLOCKED",
            "detail": (
                "likely sheet_red_to_green_entry_enabled (default True; WPBR does not bypass): "
                f"prior_red={gates.get('prior_red')} green={gates.get('green')} "
                f"prior={gates.get('prior_date')} signal={signal}"
            ),
            "blocker": None,
            "gates": gates,
            "trace": tr[:8],
        }

    # free slot but not taken — other
    free_after = None
    priors = [t for t in closed if t["exit"] and t["exit"] < fill]
    if priors:
        last = max(priors, key=lambda t: t["exit"])
        free_after = last["exit"]
    return {
        "class": "OTHER_FREE_SLOT_NOT_TAKEN",
        "detail": (
            f"no overlapping closed trade; last prior exit={free_after}; "
            f"red_to_green={None if not gates else gates.get('red_to_green')}"
        ),
        "blocker": None,
        "gates": gates,
        "trace": tr[:12],
    }


def main() -> int:
    print("=" * 88)
    print("META WPBR cascade sim — stamp 260722105625 settings")
    print("=" * 88)
    df = load_meta()
    cfg = make_cfg()
    print(
        f"cfg: wpbr_zones={cfg.wpbr_zones} brt_zones={cfg.brt_zones} "
        f"retest_mode={cfg.wpbr_retest_mode} second_chance={cfg.wpbr_second_chance_after_win}"
    )
    print(
        f"    entry_start={cfg.entry_start_date} target={cfg.target_pct} stop={cfg.stop_pct} "
        f"growth={cfg.growth_filter_enabled} too_high={cfg.too_high_multiplier} "
        f"min_spy_1y={cfg.min_spy_compare_1y_at_trigger}"
    )
    print(
        f"    sheet_red_to_green={cfg.sheet_red_to_green_entry_enabled} "
        f"sheet_dw_countif={cfg.sheet_dw_countif_entry_enabled} "
        f"require_close_gt_open={cfg.require_close_gt_open}"
    )

    raw = collect_raw_fills(df)
    print(f"\n=== RAW wpbr_entry_opportunities fills from {MIN_DATE}+ : {len(raw)} ===")
    for r in raw:
        mark = " **" if r["fill"] in FOCUS else ""
        print(
            f"  fill={r['fill']}  signal={r['signal']}  retest={r['retest']}  "
            f"zone={r['zone_id']}{mark}"
        )

    # First pass: no trace
    closed_t, open_t, _, _, blocks = run_backtest(df, cfg, trace_dates=None)
    closed = closed_rows(closed_t)
    print("\n=== profile_block_reasons (top) ===")
    for k, v in sorted(blocks.items(), key=lambda kv: -kv[1])[:20]:
        print(f"  {k}: {v}")
    if open_t is not None:
        closed.append(
            {
                "entry": _ymd(getattr(open_t, "date_opened", "")),
                "exit": "OPEN",
                "entry_px": float(getattr(open_t, "entry_price", 0.0) or 0.0),
                "exit_px": 0.0,
                "exit_type": "OPEN",
                "pnl_pct": 0.0,
                "zone_id": str(getattr(open_t, "wpbr_zone_id", "") or ""),
                "signal_date": _ymd(getattr(open_t, "close_above_date", "")),
            }
        )

    print(f"\n=== CLOSED (serialized) trade entry dates : {len(closed)} ===")
    for t in closed:
        print(
            f"  {t['entry']} -> {t['exit']}  {t['exit_type']:>10}  "
            f"pnl={t['pnl_pct']:+.2f}%  zone={t['zone_id']}  signal~{t['signal_date']}"
        )

    # Trace focus signal dates (+ neighbors for pending TTL / delayed fill)
    focus_signals = []
    for r in raw:
        if r["fill"] in FOCUS or (r["signal"] and r["signal"] in FOCUS):
            if r["signal"]:
                focus_signals.append(r["signal"])
            focus_signals.append(r["fill"])
    focus_signals.extend(sorted(FOCUS))
    # delayed-fill eval days (close_above_window retries)
    focus_signals.extend(
        [
            "2018-11-26",
            "2018-11-27",
            "2018-11-28",
            "2018-11-29",
            "2025-08-22",
            "2025-08-25",
            "2025-08-26",
            "2025-08-27",
        ]
    )
    focus_signals = sorted(set(focus_signals))

    print(f"\n=== GATE TRACE on signals/fills: {focus_signals} ===")
    _, _, trace_txt, _, _ = run_backtest(df, cfg, trace_dates=focus_signals)
    # Split trace by loop date mentioned
    trace_by_day: dict[str, str] = {}
    for ln in trace_txt.splitlines():
        if "loop_i=" not in ln:
            continue
        # [TRACE] META loop_i=2018-06-11 ...
        try:
            part = ln.split("loop_i=", 1)[1]
            day = part.split()[0].strip()
        except Exception:
            continue
        trace_by_day.setdefault(day, "")
        trace_by_day[day] += ln + "\n"
    # Also stash full
    full_trace = trace_txt

    print("\n=== CLASSIFY raw fills that are NOT closed entries ===")
    skipped = []
    for r in raw:
        cls = classify_skip(r, [t for t in closed if t["exit"] != "OPEN"], df, trace_by_day)
        # attach signal-day traces even if classify used heuristic
        if r["signal"] and r["signal"] in trace_by_day and not cls["trace"]:
            cls["trace"] = parse_trace_blocks(trace_by_day[r["signal"]])[:12]
        if cls["class"] == "SERIALIZED":
            continue
        skipped.append((r, cls))
        flag = " <<FOCUS" if r["fill"] in FOCUS else ""
        print(f"\n-- fill {r['fill']} zone={r['zone_id']}{flag}")
        print(f"   signal={r['signal']} retest={r['retest']}")
        print(f"   CLASS: {cls['class']}")
        print(f"   DETAIL: {cls['detail']}")
        if cls.get("gates"):
            g = cls["gates"]
            print(
                f"   OHLC signal: prior={g.get('prior_date')} red={g.get('prior_red')} "
                f"signal_green={g.get('green')} red_to_green={g.get('red_to_green')} "
                f"O={g.get('O')} C={g.get('C')}"
            )
        for ln in cls.get("trace") or []:
            print(f"   TRACE: {ln}")

    # Focus deep-dives
    print("\n" + "=" * 88)
    print("FOCUS EXPLANATIONS")
    print("=" * 88)

    by_fill = {r["fill"]: r for r in raw}
    # 2018-06-12
    for label, fill in [
        ("2018-06-12 raw vs engine 2018-11-29", "2018-06-12"),
        ("2019-12-04", "2019-12-04"),
        ("2020-03-20", "2020-03-20"),
        ("2021-04-21", "2021-04-21"),
        ("2025-08-25 sheet vs 2025-08-27 engine", "2025-08-25"),
    ]:
        print(f"\n### {label}")
        r = by_fill.get(fill)
        if r is None and fill == "2025-08-25":
            # sheet fill may be engine signal+something else — find near
            near = [x for x in raw if x["fill"][:7] == "2025-08" or (x["signal"] or "")[:7] == "2025-08"]
            print(f"  no raw fill exactly on {fill}; August 2025 raw fills:")
            for x in near:
                print(f"    fill={x['fill']} signal={x['signal']} zone={x['zone_id']}")
            eng = [t for t in closed if t["entry"].startswith("2025-08")]
            for t in eng:
                print(f"  engine closed: {t['entry']}->{t['exit']} zone={t['zone_id']} signal~{t['signal_date']}")
            # explain 2-day offset using OHLC calendar
            idx = pd.DatetimeIndex(df.index)
            iso = [d.strftime("%Y-%m-%d") for d in idx]
            if "2025-08-25" in iso and "2025-08-27" in iso:
                i25 = iso.index("2025-08-25")
                i27 = iso.index("2025-08-27")
                print(f"  calendar: 2025-08-25 bar={i25}, 2025-08-27 bar={i27}, delta_bars={i27 - i25}")
                print(f"  sessions between: {iso[i25:i27+1]}")
            # find raw whose signal is 2025-08-26 (engine fill 27) or fill 27
            for x in raw:
                if x["fill"] == "2025-08-27" or x["signal"] == "2025-08-26":
                    g = gate_snapshot(df, x["signal"] or "")
                    print(
                        f"  engine-matching raw: fill={x['fill']} signal={x['signal']} "
                        f"zone={x['zone_id']} red_to_green={g.get('red_to_green')}"
                    )
            # sheet 8/25 vs engine 8/27: typically sheet rocket 8/22 -> fill 8/25,
            # engine may take a later signal from same or different zone once free
            for x in raw:
                if x["fill"] == "2025-08-25" or x["signal"] == "2025-08-22":
                    cls = classify_skip(x, [t for t in closed if t["exit"] != "OPEN"], df, trace_by_day)
                    print(
                        f"  sheet-like candidate fill={x['fill']} signal={x['signal']} "
                        f"zone={x['zone_id']} -> {cls['class']}: {cls['detail']}"
                    )
            continue

        if r is None:
            print(f"  (no raw opportunity with fill={fill})")
            continue
        cls = classify_skip(r, [t for t in closed if t["exit"] != "OPEN"], df, trace_by_day)
        print(f"  zone_id={r['zone_id']}")
        print(f"  signal={r['signal']} retest={r['retest']} fill={r['fill']}")
        print(f"  CLASS={cls['class']}")
        print(f"  {cls['detail']}")
        g = cls.get("gates") or gate_snapshot(df, r["signal"] or "")
        if g:
            print(
                f"  red_to_green={g.get('red_to_green')} prior={g.get('prior_date')} "
                f"prior_red={g.get('prior_red')} signal_green={g.get('green')}"
            )
        # show what engine took instead in the window
        after_free = [t for t in closed if t["entry"] > (r["fill"][:4] + "-01-01") and t["entry"] <= "2026-01-01"]
        # nearest later serialized entry
        later = [t for t in closed if t["entry"] > r["fill"]]
        earlier = [t for t in closed if t["exit"] != "OPEN" and t["exit"] < r["fill"]]
        if earlier:
            e = max(earlier, key=lambda t: t["exit"])
            print(f"  prior serialized exit: {e['entry']}->{e['exit']} zone={e['zone_id']}")
        if later:
            n = later[0]
            print(f"  next serialized entry: {n['entry']}->{n['exit']} zone={n['zone_id']}")
        sig = r["signal"] or ""
        if sig in trace_by_day:
            print("  TRACE lines:")
            for ln in parse_trace_blocks(trace_by_day[sig])[:15]:
                print(f"    {ln}")
        elif r["fill"] in trace_by_day:
            print("  TRACE lines (fill bar):")
            for ln in parse_trace_blocks(trace_by_day[r["fill"]])[:15]:
                print(f"    {ln}")

    # Summary counts
    from collections import Counter

    c = Counter(cls["class"] for _, cls in skipped)
    print("\n=== SKIP CLASS COUNTS ===")
    for k, v in c.most_common():
        print(f"  {k}: {v}")
    print(f"\nSerialized raw fills: {sum(1 for r in raw if any(t['entry']==r['fill'] for t in closed))}/{len(raw)}")

    # Dump any TRACE mentioning red_to_green / dw_countif for focus
    print("\n=== RAW TRACE SNIPPETS (focus-related) ===")
    for ln in full_trace.splitlines():
        if any(x.replace("-", "") in ln.replace("-", "") for x in FOCUS) or "red_to_green" in ln or "sheet_dw" in ln or "BY retest" in ln:
            if "[TRACE]" in ln or "[DEBUG" in ln:
                print(ln)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
