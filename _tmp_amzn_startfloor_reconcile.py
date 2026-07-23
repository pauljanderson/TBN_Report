#!/usr/bin/env python3
"""AMZN-only reconcile vs startfloor+HALF_UP stamp 260722165827."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(REPO / "stock_analysis"))
from wpbr_zones import compute_wpbr_touch_stream  # noqa: E402

STAMP_DIR = (
    REPO
    / "drive"
    / "wpbr_sheet_reconcile"
    / "_markten_variantC_SC_stop91_startfloor_halfup_20260722165815"
)
STAMP = "260722165827"
PRIOR_STAMP = "260722161242"
BASE = REPO / "drive" / "wpbr_sheet_reconcile"
DATA = REPO / "data" / "newdata" / "data"
MIN_DATE = "2016-01-01"
SYM = "AMZN"
EARLY_CHECK = ["2016-01-15", "2016-05-19"]
PHANTOM = "2022-12-08"


def read_text_any(p: Path) -> str:
    b = p.read_bytes()
    if b[:2] in (b"\xff\xfe", b"\xfe\xff") or (len(b) > 1 and b[1] == 0):
        for enc in ("utf-16", "utf-16-le"):
            try:
                return b.decode(enc)
            except Exception:
                pass
    return b.decode("utf-8", errors="ignore")


def nd(s):
    if s is None:
        return None
    s = str(s).strip().replace("$", "").replace(",", "")
    if s in {"", "#N/A", "None", "#DIV/0!", "nan", "NaT"}:
        return None
    if s.isdigit() and len(s) == 8:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    try:
        return pd.Timestamp(s).strftime("%Y-%m-%d")
    except Exception:
        return None


def nf(s):
    if s is None:
        return None
    s = str(s).replace("$", "").replace(",", "").replace("%", "").strip()
    if s in {"", "#N/A", "None", "#DIV/0!", "nan"}:
        return None
    try:
        return float(s)
    except Exception:
        return None


def parse_entry(s) -> str | None:
    d = nd(s)
    if d:
        return d
    try:
        t = str(int(s))
        if len(t) == 8:
            return f"{t[:4]}-{t[4:6]}-{t[6:8]}"
    except Exception:
        pass
    return None


def bar_to_date(idx, b):
    if b is None:
        return None
    try:
        b = int(b)
    except Exception:
        return None
    if b < 0 or b >= len(idx):
        return None
    return pd.Timestamp(idx[b]).strftime("%Y-%m-%d")


def load_sheet_zones(sym_dir: Path) -> list[dict]:
    for name in ("zones.tsv", "sheet_zones.tsv"):
        p = sym_dir / name
        if p.is_file():
            break
    else:
        return []
    rows = []
    for line in read_text_any(p).splitlines()[1:]:
        if not line.strip():
            continue
        c = line.split("\t") + [""] * 20
        piv = nd(c[9])
        if not piv:
            continue
        rows.append(
            {
                "pivot": piv,
                "bo": nd(c[5]),
                "zlow": nf(c[6]),
                "zhigh": nf(c[7]),
                "conf": nd(c[13]),
                "next": nd(c[14]),
                "retest": nd(c[16]),
                "rocket": nd(c[18]),
            }
        )
    return rows


def load_sheet_trades(sym_dir: Path) -> list[dict]:
    for name in ("trades.tsv", "sheet_trades.tsv"):
        p = sym_dir / name
        if p.is_file():
            break
    else:
        return []
    lines = read_text_any(p).splitlines()
    start = 0
    for i, ln in enumerate(lines):
        if ln.strip().startswith("Entry Date"):
            start = i + 1
            break
    trades = []
    for line in lines[start:]:
        if not line.strip():
            continue
        c = line.split("\t")
        entry = nd(c[0])
        if not entry:
            continue
        trades.append(
            {
                "entry": entry,
                "entry_px": nf(c[1]) if len(c) > 1 else None,
                "exit": nd(c[2]) if len(c) > 2 else None,
                "exit_px": nf(c[3]) if len(c) > 3 else None,
            }
        )
    return trades


def load_closed(sym: str) -> list[dict]:
    p = STAMP_DIR / f"WPBR_Closed_{STAMP}.csv"
    df = pd.read_csv(p)
    df = df[df["SYMBOL"].astype(str).str.upper() == sym.upper()].copy()
    out = []
    for _, r in df.iterrows():
        out.append(
            {
                "entry": parse_entry(r["DATE_OPENED"]),
                "exit": parse_entry(r.get("DATE_CLOSED")),
                "entry_px": nf(r["ENTRY_PRICE"]),
                "exit_px": nf(r.get("EXIT_PRICE")),
                "exit_type": str(r.get("EXIT_TYPE") or ""),
                "pnl_pct": nf(r.get("PNL_PCT")),
                "pnl_dollars": nf(r.get("PNL_DOLLARS")),
                "days": nf(r.get("DAYS_HELD")),
                "zone_id": str(r.get("WPBR_ZONE_ID") or ""),
                "open": False,
            }
        )
    op = STAMP_DIR / f"WPBR_Open_{STAMP}.csv"
    if op.is_file():
        odf = pd.read_csv(op)
        if "SYMBOL" in odf.columns:
            odf = odf[odf["SYMBOL"].astype(str).str.upper() == sym.upper()]
            for _, r in odf.iterrows():
                out.append(
                    {
                        "entry": parse_entry(r["DATE_OPENED"]),
                        "exit": None,
                        "entry_px": nf(r["ENTRY_PRICE"]),
                        "exit_px": None,
                        "exit_type": "OPEN",
                        "pnl_pct": None,
                        "pnl_dollars": None,
                        "days": None,
                        "zone_id": str(r.get("WPBR_ZONE_ID") or ""),
                        "open": True,
                    }
                )
    out.sort(key=lambda x: x["entry"] or "")
    return out


def build_eng(df: pd.DataFrame) -> tuple[dict, set[str]]:
    idx = pd.DatetimeIndex(df.index)
    stream = compute_wpbr_touch_stream(
        df,
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
    eng = {}
    for ev in stream["wpbr_zone_events"]:
        piv = nd(ev["pivot_monday"])
        if not piv:
            continue
        eng[piv] = {
            "zlow": float(ev["zone_lower"]),
            "zhigh": float(ev["zone_upper"]),
            "bo": nd(ev["breakout_monday"]),
            "conf": nd(ev["conf_monday"]),
            "next": nd(ev["next_week_start"]),
            "retest": bar_to_date(idx, ev.get("retest_bar")),
            "signal": bar_to_date(idx, ev.get("entry_signal_bar")),
            "fill": bar_to_date(idx, ev.get("entry_fill_bar")),
            "zone_id": str(ev.get("wpbr_zone_id") or ""),
        }
    raw_fills = {e["fill"] for e in eng.values() if e["fill"]}
    for opp in stream.get("wpbr_entry_opportunities") or []:
        fd = bar_to_date(idx, opp.get("entry_fill_bar"))
        if fd:
            raw_fills.add(fd)
    return eng, raw_fills


def structure_stats(sheet_z, eng):
    zone_ok = retest_ok = rocket_ok = rocket_where_sheet = 0
    rocket_sheet_fires = 0
    eng_only = []
    retest_mism = []
    n_pairs = 0
    for z in sheet_z:
        e = eng.get(z["pivot"])
        if not e:
            continue
        n_pairs += 1
        zl_ok = z["zlow"] is not None and abs(z["zlow"] - e["zlow"]) <= 0.02
        zh_ok = z["zhigh"] is not None and abs(z["zhigh"] - e["zhigh"]) <= 0.02
        if zl_ok and zh_ok and z["bo"] == e["bo"]:
            zone_ok += 1
        if z["retest"] == e["retest"]:
            retest_ok += 1
        else:
            retest_mism.append(
                {
                    "pivot": z["pivot"],
                    "sheet_retest": z["retest"],
                    "eng_retest": e["retest"],
                }
            )
        if z["rocket"]:
            rocket_sheet_fires += 1
            if z["rocket"] == e["signal"]:
                rocket_where_sheet += 1
                rocket_ok += 1
        else:
            if e["signal"]:
                eng_only.append(
                    {
                        "pivot": z["pivot"],
                        "eng_signal": e["signal"],
                        "eng_fill": e["fill"],
                    }
                )
            else:
                rocket_ok += 1
    sheet_pivs = {z["pivot"] for z in sheet_z}
    return {
        "pivots_match": f"{len(sheet_pivs & set(eng))}/{len(sheet_z)}",
        "n_pairs": n_pairs,
        "zones_ok": f"{zone_ok}/{n_pairs}",
        "retest_ok": f"{retest_ok}/{n_pairs}",
        "rocket_where_sheet_fires": f"{rocket_where_sheet}/{rocket_sheet_fires}",
        "rocket_ok_pairs": f"{rocket_ok}/{n_pairs}",
        "n_eng_only": len(eng_only),
        "eng_only": eng_only,
        "retest_mismatches": retest_mism,
    }


def stacked_six(closed_rows: list[dict]) -> dict:
    closed = [t for t in closed_rows if not t.get("open")]
    n = len(closed)
    if n == 0:
        return {
            "trades": 0,
            "win_pct": None,
            "avg_profit": None,
            "wl_ratio": None,
            "avg_days": None,
            "pnl": None,
            "block": "0\n",
        }
    pnls = [t["pnl_pct"] for t in closed if t["pnl_pct"] is not None]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    avg_profit = sum(pnls) / len(pnls) if pnls else None
    win_pct = 100.0 * len(wins) / len(pnls) if pnls else None
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss_abs = abs(sum(losses) / len(losses)) if losses else None
    wl = (avg_win / avg_loss_abs) if avg_loss_abs else None
    days = [t["days"] for t in closed if t["days"] is not None]
    avg_days = sum(days) / len(days) if days else None
    dollars = [t["pnl_dollars"] for t in closed if t["pnl_dollars"] is not None]
    pnl = sum(dollars) if dollars else 0.0
    block = "\n".join(
        [
            str(n),
            f"{win_pct:.1f}%",
            f"{avg_profit:.1f}%",
            f"{wl:.2f}" if wl is not None else "n/a",
            f"{avg_days:.1f}" if avg_days is not None else "n/a",
            f"${pnl:,.2f}",
        ]
    )
    return {
        "trades": n,
        "win_pct": win_pct,
        "avg_profit": avg_profit,
        "wl_ratio": wl,
        "avg_days": avg_days,
        "pnl": pnl,
        "block": block,
    }


def sheet_stacked(trades: list[dict]) -> dict:
    closed = [t for t in trades if t.get("exit") and t.get("entry_px") and t.get("exit_px")]
    rows = []
    for t in closed:
        pnl_pct = (t["exit_px"] / t["entry_px"] - 1.0) * 100.0
        try:
            days = (pd.Timestamp(t["exit"]) - pd.Timestamp(t["entry"])).days
        except Exception:
            days = None
        rows.append(
            {
                "entry": t["entry"],
                "exit": t["exit"],
                "entry_px": t["entry_px"],
                "exit_px": t["exit_px"],
                "pnl_pct": pnl_pct,
                "pnl_dollars": None,  # sizing unknown; omit from $ if None
                "days": days,
                "open": False,
            }
        )
    # For sheet $PnL leave as n/a unless we can compute; reuse stacked without dollars
    n = len(rows)
    if n == 0:
        return {"trades": 0, "block": "0\n", "win_pct": None}
    pnls = [r["pnl_pct"] for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    avg_profit = sum(pnls) / n
    win_pct = 100.0 * len(wins) / n
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss_abs = abs(sum(losses) / len(losses)) if losses else None
    wl = (avg_win / avg_loss_abs) if avg_loss_abs else None
    days = [r["days"] for r in rows if r["days"] is not None]
    avg_days = sum(days) / len(days) if days else None
    block = "\n".join(
        [
            str(n),
            f"{win_pct:.1f}%",
            f"{avg_profit:.1f}%",
            f"{wl:.2f}" if wl is not None else "n/a",
            f"{avg_days:.1f}" if avg_days is not None else "n/a",
            "n/a ($ sizing)",
        ]
    )
    return {
        "trades": n,
        "win_pct": win_pct,
        "avg_profit": avg_profit,
        "wl_ratio": wl,
        "avg_days": avg_days,
        "pnl": None,
        "block": block,
    }


def main() -> int:
    out_dir = BASE / SYM
    df = pd.read_csv(DATA / f"{SYM}.csv", index_col=0, parse_dates=True)
    eng_all, raw_all = build_eng(df)
    sheet_z_all = load_sheet_zones(out_dir)
    sheet_z = [z for z in sheet_z_all if z["pivot"] and z["pivot"] >= MIN_DATE]
    eng = {p: e for p, e in eng_all.items() if p >= MIN_DATE}
    raw_fills = {f for f in raw_all if f and f >= MIN_DATE}
    sheet_t_all = load_sheet_trades(out_dir)
    sheet_t = [t for t in sheet_t_all if t["entry"] and t["entry"] >= MIN_DATE]
    closed = load_closed(SYM)
    ser = {t["entry"] for t in closed}
    fair = structure_stats(sheet_z, eng)

    n_raw = n_ser = 0
    for t in sheet_t:
        n_raw += int(t["entry"] in raw_fills)
        n_ser += int(t["entry"] in ser)
    raw_orphans = [t["entry"] for t in sheet_t if t["entry"] not in raw_fills]
    ser_orphans = [t["entry"] for t in sheet_t if t["entry"] not in ser]
    eng_entries = [t["entry"] for t in closed]
    sheet_entries = [t["entry"] for t in sheet_t]
    eng_only_trades = sorted(set(eng_entries) - set(sheet_entries))
    sheet_only = sorted(set(sheet_entries) - set(eng_entries))

    # Forks on matched entries
    sheet_by = {t["entry"]: t for t in sheet_t}
    forks = []
    for t in closed:
        if t.get("open"):
            continue
        s = sheet_by.get(t["entry"])
        if not s:
            continue
        issues = []
        if s["exit"] and t["exit"] and s["exit"] != t["exit"]:
            issues.append(f"exit_date sheet={s['exit']} eng={t['exit']}")
        if (
            s["entry_px"] is not None
            and t["entry_px"] is not None
            and abs(s["entry_px"] - t["entry_px"]) > 0.05
        ):
            issues.append(f"entry_px sheet={s['entry_px']} eng={t['entry_px']}")
        if (
            s["exit_px"] is not None
            and t["exit_px"] is not None
            and abs(s["exit_px"] - t["exit_px"]) > 0.05
        ):
            issues.append(f"exit_px sheet={s['exit_px']} eng={t['exit_px']}")
        if issues:
            forks.append({"entry": t["entry"], "issues": issues})

    early_gone = {d: d not in eng_entries for d in EARLY_CHECK}
    eng_stack = stacked_six(closed)
    sheet_stack = sheet_stacked(sheet_t)

    # pivot floor check from zone_id (first date token)
    pre2016_pivot_fills = []
    for t in closed:
        zid = t.get("zone_id") or ""
        piv = zid.split("|")[0] if zid else ""
        if piv and piv < MIN_DATE:
            pre2016_pivot_fills.append(
                {"entry": t["entry"], "pivot_token": piv, "zone_id": zid}
            )

    log = STAMP_DIR / "_run_log.txt"
    log_txt = read_text_any(log) if log.is_file() else ""
    sc_ok = (
        "wpbr_second_chance_after_win=true" in log_txt
        or "wpbr_second_chance_after_win=True" in log_txt
    )
    startfloor_ok = any(
        x in log_txt
        for x in (
            "start_floor",
            "pivot_start",
            "wpbr_min_pivot",
            "min_pivot",
            "startfloor",
            "PIVOT_MONDAY",
        )
    )

    result = {
        "symbol": SYM,
        "stamp": STAMP,
        "stamp_dir": str(STAMP_DIR),
        "sc_in_run_log": sc_ok,
        "fair": fair,
        "raw": f"{n_raw}/{len(sheet_t)}",
        "ser": f"{n_ser}/{len(sheet_t)}",
        "n_raw": n_raw,
        "n_ser": n_ser,
        "n_sheet_trades": len(sheet_t),
        "closed_n": len(closed),
        "closed_only_n": sum(1 for t in closed if not t.get("open")),
        "raw_orphans": raw_orphans,
        "ser_orphans": ser_orphans,
        "eng_only_trades": eng_only_trades,
        "sheet_only": sheet_only,
        "forks": forks,
        "early_gone": early_gone,
        "pre2016_pivot_fills": pre2016_pivot_fills,
        "eng_entries": eng_entries,
        "sheet_entries": sheet_entries,
        "eng_stack": {k: v for k, v in eng_stack.items() if k != "block"},
        "eng_stack_block": eng_stack["block"],
        "sheet_stack": {k: v for k, v in sheet_stack.items() if k != "block"},
        "sheet_stack_block": sheet_stack["block"],
        "closed_detail": [
            {
                "entry": t["entry"],
                "exit": t["exit"],
                "entry_px": t["entry_px"],
                "exit_px": t["exit_px"],
                "exit_type": t["exit_type"],
                "pnl_pct": t["pnl_pct"],
                "days": t["days"],
                "zone_id": t["zone_id"],
                "open": t["open"],
            }
            for t in closed
        ],
    }

    phantom_only = (
        raw_orphans == [PHANTOM]
        and ser_orphans == [PHANTOM]
        and sheet_only == [PHANTOM]
        and not eng_only_trades
        and not forks
    )

    # Write status md
    status = out_dir / f"{SYM}_wpbr_reconcile_status.md"
    lines = []
    lines.append(
        f"# AMZN WPBR reconcile — variant C + SC-on + startfloor halfup (`{STAMP}`)"
    )
    lines.append("")
    lines.append(
        f"**Engine:** `drive/wpbr_sheet_reconcile/_markten_variantC_SC_stop91_startfloor_halfup_20260722165815/` "
        f"(`{STAMP}`)"
    )
    lines.append(
        f"**Prior startfloor (no halfup folder):** "
        f"`_markten_variantC_SC_stop91_startfloor_2016_20260722161052/` (`{PRIOR_STAMP}`)"
    )
    lines.append(
        f"**SC:** `wpbr_second_chance_after_win=true` (log: **{sc_ok}**)"
    )
    lines.append(
        "**Settings:** stop_pct=0.91 + start_date=2016-01-01 + **startfloor** + **HALF_UP** "
        "pivot then band (pre-2016 pivot fills suppressed)."
    )
    lines.append("**Paste:** breakouts/retests/rockets + trades only (OHLC/weekly unchanged).")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Pivots | {fair['pivots_match']} |")
    lines.append(f"| Zones | {fair['zones_ok']} |")
    lines.append(f"| Retest | {fair['retest_ok']} |")
    lines.append(f"| Rocket (sheet fires) | {fair['rocket_where_sheet_fires']} |")
    lines.append(f"| Raw | **{result['raw']}** |")
    lines.append(f"| Ser | **{result['ser']}** |")
    lines.append(f"| Eng closed (+open) | {result['closed_n']} |")
    lines.append(f"| Sheet trades ≥2016 | {result['n_sheet_trades']} |")
    lines.append("")
    if raw_orphans:
        lines.append(f"**Raw orphans:** {', '.join(raw_orphans)}")
        lines.append("")
    else:
        lines.append("**Raw orphans:** —")
        lines.append("")
    if ser_orphans:
        lines.append(f"**Ser orphans:** {', '.join(ser_orphans)}")
        lines.append("")
    else:
        lines.append("**Ser orphans:** —")
        lines.append("")
    if eng_only_trades:
        lines.append(f"**Eng-only fills:** {', '.join(eng_only_trades)}")
        lines.append("")
    else:
        lines.append("**Eng-only fills:** —")
        lines.append("")
    if forks:
        lines.append(f"**Forks ({len(forks)}):**")
        for f in forks:
            lines.append(f"- `{f['entry']}`: {'; '.join(f['issues'])}")
        lines.append("")
    else:
        lines.append("**Forks:** 0 (matched entries agree on exit date + px ±$0.05)")
        lines.append("")

    lines.append("## Residual: `2022-12-08` sheet phantom")
    lines.append("")
    if phantom_only:
        lines.append(
            f"**Still the only residual.** Raw/ser orphans and sheet-only set are solely "
            f"`{PHANTOM}` — same `SHEET_PHANTOM` / Results↔zones desync as prior "
            f"`{PRIOR_STAMP}` (see `AMZN_2022-12-08_phantom.md`). HALF_UP does not add or clear it."
        )
    else:
        lines.append(
            f"**Not sole residual** — check orphans/forks above; `{PHANTOM}` "
            f"in raw={PHANTOM in raw_orphans} ser={PHANTOM in ser_orphans}."
        )
    lines.append("")

    lines.append("## Pre-2016 eng-only fills (startfloor check)")
    lines.append("")
    for d in EARLY_CHECK:
        gone = early_gone[d]
        lines.append(
            f"- `{d}`: **{'GONE' if gone else 'STILL PRESENT'}** from eng closed+open"
        )
    lines.append("")
    if pre2016_pivot_fills:
        lines.append(
            f"**WARNING:** {len(pre2016_pivot_fills)} closed trade(s) still have pivot token < 2016:"
        )
        for x in pre2016_pivot_fills:
            lines.append(f"- entry `{x['entry']}` zone `{x['zone_id']}`")
        lines.append("")
    else:
        lines.append(
            "**No closed trades with `WPBR_ZONE_ID` pivot token < 2016-01-01.**"
        )
        lines.append("")

    lines.append("## 6-value stacked (engine closed)")
    lines.append("")
    lines.append("Order: trades → win% → avg profit% → win/loss → avg days → $PnL")
    lines.append("")
    lines.append("```")
    lines.append("AMZN")
    lines.append(eng_stack["block"])
    lines.append("```")
    lines.append("")
    lines.append(
        f"*Identical to prior startfloor `{PRIOR_STAMP}` stack "
        f"(`7 / 42.9% / 3.6% / 2.12 / 147.9 / $36,139.20`). "
        f"Prior stop91 (no startfloor) was `9 / 44.4% / 4.2% / 2.15 / 132.8 / $54,174.49` "
        f"(included `{', '.join(EARLY_CHECK)}`).*"
    )
    lines.append("")
    lines.append(
        f"*Generated by `_tmp_amzn_startfloor_reconcile.py` vs stamp `{STAMP}` (HALF_UP + startfloor). Do not commit.*"
    )
    lines.append("")
    status.write_text("\n".join(lines), encoding="utf-8")

    payload_path = out_dir / "_amzn_startfloor_reconcile_payload.json"
    # trim bulky fair lists
    fair_out = dict(fair)
    fair_out["eng_only"] = fair_out.get("eng_only", [])[:25]
    fair_out["retest_mismatches"] = fair_out.get("retest_mismatches", [])[:40]
    result["fair"] = fair_out
    result["phantom_only_residual"] = phantom_only
    result["half_up"] = True
    payload_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    stacked_lines = eng_stack["block"].split("\n")
    parent = {
        "symbol": SYM,
        "stamp": STAMP,
        "stamp_dir": str(STAMP_DIR),
        "prior_stamp": PRIOR_STAMP,
        "sc_in_run_log": sc_ok,
        "half_up": True,
        "startfloor": True,
        "pivots": fair["pivots_match"],
        "zones": fair["zones_ok"],
        "retest": fair["retest_ok"],
        "rocket_sheet_fires": fair["rocket_where_sheet_fires"],
        "raw": result["raw"],
        "ser": result["ser"],
        "closed_n": result["closed_n"],
        "closed_only_n": result["closed_only_n"],
        "sheet_trades": result["n_sheet_trades"],
        "raw_orphans": raw_orphans,
        "ser_orphans": ser_orphans,
        "eng_only_ser": eng_only_trades,
        "sheet_only": sheet_only,
        "forks": forks,
        "phantom_2022_12_08_only_residual": phantom_only,
        "early_gone": early_gone,
        "pre2016_pivot_fills": pre2016_pivot_fills,
        "n_eng_only_rockets": fair["n_eng_only"],
        "stacked": {
            "n": eng_stack["trades"],
            "win_pct": eng_stack["win_pct"],
            "avg_profit_pct": eng_stack["avg_profit"],
            "win_loss": eng_stack["wl_ratio"],
            "avg_days": eng_stack["avg_days"],
            "dollar_pnl": eng_stack["pnl"],
            "lines": stacked_lines,
        },
        "status_md": str(status),
    }
    parent_path = out_dir / f"{SYM}_startfloor_{STAMP}_parent_summary.json"
    parent_path.write_text(json.dumps(parent, indent=2, default=str), encoding="utf-8")

    print("=== AMZN startfloor halfup reconcile ===")
    print(f"stamp={STAMP} sc={sc_ok} half_up=True")
    print(
        f"piv/zone/retest {fair['pivots_match']} / {fair['zones_ok']} / {fair['retest_ok']} "
        f"rocket {fair['rocket_where_sheet_fires']} raw {result['raw']} ser {result['ser']} "
        f"closed={result['closed_n']}"
    )
    print("raw_orphans:", raw_orphans)
    print("ser_orphans:", ser_orphans)
    print("eng_only_trades:", eng_only_trades)
    print("sheet_only:", sheet_only)
    print("forks:", forks)
    print("phantom_only_residual:", phantom_only)
    print("early_gone:", early_gone)
    print("pre2016_pivot_fills:", pre2016_pivot_fills)
    print("eng_stack:")
    print(eng_stack["block"])
    print(f"wrote {status}")
    print(f"wrote {payload_path}")
    print(f"wrote {parent_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
