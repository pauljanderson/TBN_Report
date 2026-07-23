#!/usr/bin/env python3
"""MarkTen reconcile vs SC-resume stamp 260722174041. Compare ser vs prior 260722171712. Do not commit."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(REPO / "stock_analysis"))
from wpbr_zones import _round_bounds, compute_wpbr_touch_stream  # noqa: E402

STAMP_DIR = (
    REPO
    / "drive"
    / "wpbr_sheet_reconcile"
    / "_markten_variantC_SC_stop91_startfloor_halfup_scresume_20260722174137"
)
STAMP = "260722174041"
PRIOR_DIR = (
    REPO
    / "drive"
    / "wpbr_sheet_reconcile"
    / "_markten_variantC_SC_stop91_startfloor_halfup_nosamebarexit_20260722171645"
)
PRIOR_STAMP = "260722171712"
BASE = REPO / "drive" / "wpbr_sheet_reconcile"
DATA = REPO / "data" / "newdata" / "data"
MIN_DATE = "2016-01-01"
MARKTEN = ["AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA", "AU", "AMD", "NFLX"]
FOCUS = {
    "AMZN": ["2022-12-08"],
    "AU": ["2019-04-25"],
    "TSLA": ["2022-12-16"],
}
NFLX_FOCUS = ["2022-05-13", "2023-10-16", "2023-10-17"]


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


def load_closed_from(stamp_dir: Path, stamp: str, sym: str) -> list[dict]:
    p = stamp_dir / f"WPBR_Closed_{stamp}.csv"
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
                "open": False,
            }
        )
    op = stamp_dir / f"WPBR_Open_{stamp}.csv"
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
                        "open": True,
                    }
                )
    out.sort(key=lambda x: x["entry"] or "")
    return out


def load_closed(sym: str) -> list[dict]:
    return load_closed_from(STAMP_DIR, STAMP, sym)


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
        min_pivot_date=MIN_DATE,
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


def structure_stats(sheet_z: list[dict], eng: dict) -> dict:
    zone_ok = retest_ok = rocket_ok = rocket_where_sheet = rocket_sheet_fires = 0
    n_pairs = 0
    eng_only = []
    retest_mism = []
    for z in sheet_z:
        piv = z["pivot"]
        e = eng.get(piv)
        if not e:
            continue
        n_pairs += 1
        if (
            z["zlow"] is not None
            and z["zhigh"] is not None
            and abs(e["zlow"] - z["zlow"]) < 0.02
            and abs(e["zhigh"] - z["zhigh"]) < 0.02
        ):
            zone_ok += 1
        if (z["retest"] or None) == (e["retest"] or None):
            retest_ok += 1
        else:
            retest_mism.append(
                {
                    "pivot": piv,
                    "sheet_retest": z["retest"],
                    "eng_retest": e["retest"],
                }
            )
        if z["rocket"]:
            rocket_sheet_fires += 1
            if e["signal"] == z["rocket"] or e["fill"] and abs(
                (pd.Timestamp(e["fill"]) - pd.Timestamp(z["rocket"])).days
            ) <= 2:
                # sheet rocket = signal day typically; also accept fill next open
                rocket_where_sheet += 1
                rocket_ok += 1
            elif e["signal"]:
                # signal present near rocket
                try:
                    if abs((pd.Timestamp(e["signal"]) - pd.Timestamp(z["rocket"])).days) <= 1:
                        rocket_where_sheet += 1
                        rocket_ok += 1
                    else:
                        rocket_ok += 0
                except Exception:
                    pass
            else:
                pass
        else:
            if e["signal"]:
                eng_only.append(
                    {
                        "pivot": piv,
                        "eng_signal": e["signal"],
                        "eng_fill": e["fill"],
                    }
                )
            else:
                rocket_ok += 1
    # Simpler rocket match used by prior scripts: signal == sheet rocket day
    rocket_where_sheet = 0
    rocket_sheet_fires = 0
    rocket_ok = 0
    eng_only = []
    for z in sheet_z:
        piv = z["pivot"]
        e = eng.get(piv)
        if not e:
            continue
        if z["rocket"]:
            rocket_sheet_fires += 1
            if e["signal"] == z["rocket"]:
                rocket_where_sheet += 1
                rocket_ok += 1
            elif e["signal"]:
                # count as miss for where-sheet-fires but still pair
                pass
            else:
                pass
        else:
            if e["signal"]:
                eng_only.append(
                    {
                        "pivot": piv,
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


def fork_count(sheet_t: list[dict], closed: list[dict]) -> tuple[int, list[str]]:
    by_entry = {t["entry"]: t for t in closed if t["entry"]}
    forks = []
    for t in sheet_t:
        e = by_entry.get(t["entry"])
        if not e:
            continue
        if t["exit"] and e["exit"] and t["exit"] != e["exit"]:
            forks.append(f"{t['entry']} exit sheet={t['exit']} eng={e['exit']}")
            continue
        if (
            t["exit_px"] is not None
            and e.get("exit_px") is not None
            and abs(t["exit_px"] - e["exit_px"]) > 0.05
        ):
            forks.append(
                f"{t['entry']} exit_px sheet={t['exit_px']} eng={e['exit_px']}"
            )
    return len(forks), forks


def analyze(sym: str) -> dict:
    out_dir = BASE / sym
    df = pd.read_csv(DATA / f"{sym}.csv", index_col=0, parse_dates=True)
    eng_all, raw_all = build_eng(df)
    sheet_z_all = load_sheet_zones(out_dir)
    sheet_z = [z for z in sheet_z_all if z["pivot"] and z["pivot"] >= MIN_DATE]
    eng = {p: e for p, e in eng_all.items() if p >= MIN_DATE}
    raw_fills = {f for f in raw_all if f and f >= MIN_DATE}
    sheet_t_all = load_sheet_trades(out_dir)
    sheet_t = [t for t in sheet_t_all if t["entry"] and t["entry"] >= MIN_DATE]
    closed = load_closed(sym)
    prior = load_closed_from(PRIOR_DIR, PRIOR_STAMP, sym)
    ser = {t["entry"] for t in closed}
    prior_ser = {t["entry"] for t in prior}
    fair = structure_stats(sheet_z, eng)
    n_raw = n_ser = n_prior_ser = 0
    for t in sheet_t:
        n_raw += int(t["entry"] in raw_fills)
        n_ser += int(t["entry"] in ser)
        n_prior_ser += int(t["entry"] in prior_ser)
    raw_orphans = [t["entry"] for t in sheet_t if t["entry"] not in raw_fills]
    ser_orphans = [t["entry"] for t in sheet_t if t["entry"] not in ser]
    prior_ser_orphans = [t["entry"] for t in sheet_t if t["entry"] not in prior_ser]
    sheet_only_new = sorted(set(ser_orphans) - set(prior_ser_orphans))  # worse
    cleared = sorted(set(prior_ser_orphans) - set(ser_orphans))
    eng_only_fills = sorted(ser - {t["entry"] for t in sheet_t})
    prior_eng_only = sorted(prior_ser - {t["entry"] for t in sheet_t})
    new_eng_only = sorted(set(eng_only_fills) - set(prior_eng_only))
    lost_eng_only = sorted(set(prior_eng_only) - set(eng_only_fills))
    n_forks, forks = fork_count(sheet_t, closed)
    return {
        "symbol": sym,
        "fair": fair,
        "raw": f"{n_raw}/{len(sheet_t)}",
        "ser": f"{n_ser}/{len(sheet_t)}",
        "prior_ser": f"{n_prior_ser}/{len(sheet_t)}",
        "n_raw": n_raw,
        "n_ser": n_ser,
        "n_prior_ser": n_prior_ser,
        "n_sheet_trades": len(sheet_t),
        "raw_orphans": raw_orphans,
        "ser_orphans": ser_orphans,
        "prior_ser_orphans": prior_ser_orphans,
        "ser_cleared": cleared,
        "ser_regressed": sheet_only_new,
        "closed_n": len(closed),
        "prior_closed_n": len(prior),
        "sheet_entries": [t["entry"] for t in sheet_t],
        "eng_entries": [t["entry"] for t in closed],
        "eng_only_fills": eng_only_fills,
        "new_eng_only": new_eng_only,
        "lost_eng_only": lost_eng_only,
        "n_forks": n_forks,
        "forks": forks[:20],
        "raw_fills": sorted(raw_fills),
        "focus_hits": {
            d: d in ser for d in FOCUS.get(sym, [])
        },
    }


def confirm_engine() -> dict:
    src = (REPO / "stock_analysis" / "wpbr_zones.py").read_text(encoding="utf-8")
    rbr = (REPO / "stock_analysis" / "rocket_brt.py").read_text(encoding="utf-8")
    sample = _round_bounds(100.125, 0.015, 2)
    log = STAMP_DIR / "_run_log.txt"
    log_txt = read_text_any(log) if log.is_file() else ""
    # Report CSV also encodes flags
    rep = STAMP_DIR / f"WPBR_Report_{STAMP}.csv"
    rep_txt = read_text_any(rep) if rep.is_file() else ""
    sc_ok = (
        "wpbr_second_chance_after_win=true" in log_txt
        or "wpbr_second_chance_after_win=True" in log_txt
        or ",True," in rep_txt  # SC column True in report — weak
    )
    # Prefer Report column parse
    if rep.is_file():
        rdf = pd.read_csv(rep)
        if "wpbr_second_chance_after_win" in rdf.columns:
            sc_ok = bool(rdf["wpbr_second_chance_after_win"].iloc[0])
    sc_resume_fix = (
        "Failed rocket window: unlock later SC retests" in rbr
        or "resume_scan_bar\"] = _window_end + 1" in rbr
        or "_window_end = int(_rt) + int(_max_d)" in rbr
    )
    return {
        "has_HALF_UP": "ROUND_HALF_UP" in src,
        "doc_variant_C": "variant C" in src,
        "sample": {"tp": sample[0], "zl": sample[1], "zh": sample[2]},
        "expected": {"tp": 100.13, "zl": 98.63, "zh": 101.63},
        "gatebleed_wpbr_bypass": (
            "wpbr_retest_entry (all BRT entry gates bypassed)" in rbr
            or "pass: wpbr_retest_entry (BRT sheet gates skipped)" in rbr
        ),
        "sc_in_run_log": sc_ok,
        "sc_resume_fix_in_engine": sc_resume_fix,
        "sc_flag_name": "wpbr_second_chance_after_win",
    }


def stacked_block(sym: str) -> str:
    txt = (STAMP_DIR / "_markten_stacked_stats.txt").read_text(encoding="utf-8")
    parts = txt.strip().split("\n\n")
    for p in parts:
        if p.startswith(sym + "\n"):
            return p
    return f"{sym}\n?"


def write_ticker_status(r: dict, eng: dict) -> Path:
    sym = r["symbol"]
    fair = r["fair"]
    out = BASE / sym / f"{sym}_wpbr_reconcile_status.md"
    lines: list[str] = []
    lines.append(f"# {sym} WPBR reconcile — SC-resume (`{STAMP}`)")
    lines.append("")
    lines.append(
        f"**Engine:** `drive/wpbr_sheet_reconcile/_markten_variantC_SC_stop91_startfloor_halfup_scresume_20260722174137/` "
        f"(`{STAMP}`)"
    )
    lines.append(
        f"**Prior:** `_markten_variantC_SC_stop91_startfloor_halfup_nosamebarexit_20260722171645/` "
        f"(`{PRIOR_STAMP}`)"
    )
    lines.append(
        f"**SC:** `wpbr_second_chance_after_win=true` (report: **{eng['sc_in_run_log']}**); "
        f"SC resume advance: **{eng['sc_resume_fix_in_engine']}**"
    )
    lines.append(
        "**Settings:** stop_pct=0.91 + start_date=2016-01-01 + startfloor + HALF_UP + SC resume unlock."
    )
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Pivots | {fair['pivots_match']} |")
    lines.append(f"| Zones | {fair['zones_ok']} |")
    lines.append(f"| Retest | {fair['retest_ok']} |")
    lines.append(f"| Rocket (sheet fires) | {fair['rocket_where_sheet_fires']} |")
    lines.append(f"| Raw | **{r['raw']}** |")
    lines.append(f"| Ser | **{r['ser']}** (prior `{PRIOR_STAMP}`: {r['prior_ser']}) |")
    lines.append(f"| Eng closed (+open) | {r['closed_n']} (prior {r['prior_closed_n']}) |")
    lines.append(f"| Sheet trades ≥2016 | {r['n_sheet_trades']} |")
    lines.append(f"| Forks | {r['n_forks']} |")
    lines.append("")
    if r["raw_orphans"]:
        lines.append(f"**Raw orphans:** {', '.join(r['raw_orphans'])}")
        lines.append("")
    if r["ser_orphans"]:
        lines.append(f"**Ser orphans:** {', '.join(r['ser_orphans'])}")
        lines.append("")
    if r["ser_cleared"]:
        lines.append(f"**Ser cleared vs prior:** {', '.join(r['ser_cleared'])}")
        lines.append("")
    if r["ser_regressed"]:
        lines.append(f"**Ser REGRESSED vs prior:** {', '.join(r['ser_regressed'])}")
        lines.append("")
    if r["new_eng_only"]:
        lines.append(f"**New eng-only fills:** {', '.join(r['new_eng_only'])}")
        lines.append("")
    elif r["eng_only_fills"]:
        lines.append(f"**Eng-only fills:** {', '.join(r['eng_only_fills'])}")
        lines.append("")
    if r["forks"]:
        lines.append("**Forks:**")
        for f in r["forks"]:
            lines.append(f"- {f}")
        lines.append("")
    if r["focus_hits"]:
        lines.append("## Focus confirms")
        lines.append("")
        for d, ok in r["focus_hits"].items():
            lines.append(f"- `{d}` in eng ser: **{ok}**")
        lines.append("")
    lines.append("## 6-value stacked (engine closed)")
    lines.append("")
    lines.append("```")
    lines.append(stacked_block(sym))
    lines.append("```")
    lines.append("")
    lines.append(
        f"*Generated vs SC-resume stamp `{STAMP}` (vs prior `{PRIOR_STAMP}`). Do not commit.*"
    )
    lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def write_status(results: list[dict], eng: dict) -> Path:
    out = BASE / "VARIANT_C_SC_FINAL_MARKTEN_STATUS.md"
    lines: list[str] = []
    lines.append("# WPBR MarkTen — FINAL SC-resume (stop 0.91 + startfloor + HALF_UP)")
    lines.append("")
    lines.append(
        "**Engine outdir:** `drive/wpbr_sheet_reconcile/_markten_variantC_SC_stop91_startfloor_halfup_scresume_20260722174137/`"
    )
    lines.append(f"**Stamp:** `{STAMP}`")
    lines.append(
        f"**Prior baseline:** `_markten_variantC_SC_stop91_startfloor_halfup_nosamebarexit_20260722171645/` "
        f"(`{PRIOR_STAMP}`)"
    )
    lines.append(
        "**Settings:** variant C HALF_UP + startfloor (`start_date=2016-01-01`) + "
        "`stop_pct=0.91` + `target_pct=1.22` + `wpbr_second_chance_after_win=true` + "
        "`sheet_no_entry_same_bar_after_exit=false` + **SC resume advance after exhausted rocket window**."
    )
    lines.append("")
    lines.append("## Engine confirmation")
    lines.append("")
    s = eng["sample"]
    e = eng["expected"]
    ok = s == e
    lines.append(
        f"- Variant C `_round_bounds` HALF_UP: **{eng['has_HALF_UP']}**; sample → "
        f"{s['tp']}/{s['zl']}/{s['zh']} (expected {e['tp']}/{e['zl']}/{e['zh']}) → "
        f"**{'PASS' if ok else 'FAIL'}**"
    )
    lines.append(
        f"- Gate-bleed WPBR bypass: **{eng['gatebleed_wpbr_bypass']}**"
    )
    lines.append(
        f"- Second chance in Report: **{eng['sc_in_run_log']}**"
    )
    lines.append(
        f"- SC resume unlock in `rocket_brt.py`: **{eng['sc_resume_fix_in_engine']}**"
    )
    lines.append(
        "- DailyRun / `run_wpbr.bat`: target 1.22, stop 0.91, start_date 2016, SC on, nosamebarexit"
    )
    lines.append("")
    lines.append("## Focus confirms")
    lines.append("")
    by = {r["symbol"]: r for r in results}
    for sym, dates in FOCUS.items():
        r = by[sym]
        for d in dates:
            lines.append(
                f"- **{sym} `{d}`:** eng ser **{r['focus_hits'].get(d)}** "
                f"(closed={r['closed_n']})"
            )
    lines.append("")
    lines.append("## Reconciled vs this stamp")
    lines.append("")
    lines.append(
        "| Ticker | Pivots | Zones | Retest | Rocket | Raw | Ser | Prior ser | Eng closed | Δser | Notes |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---:|---|---|")
    total_ser = total_sheet = total_prior = 0
    regressions = []
    for sym in MARKTEN:
        r = by[sym]
        fair = r["fair"]
        total_ser += r["n_ser"]
        total_sheet += r["n_sheet_trades"]
        total_prior += r["n_prior_ser"]
        dser = r["n_ser"] - r["n_prior_ser"]
        dser_s = f"+{dser}" if dser > 0 else str(dser)
        notes = []
        if r["ser_cleared"]:
            notes.append(f"cleared: {', '.join(r['ser_cleared'])}")
        if r["ser_regressed"]:
            notes.append(f"REGRESSED: {', '.join(r['ser_regressed'])}")
            regressions.append(f"{sym}: {', '.join(r['ser_regressed'])}")
        if r["new_eng_only"]:
            notes.append(f"new eng-only: {', '.join(r['new_eng_only'])}")
        if r["raw_orphans"] and not r["ser_orphans"]:
            notes.append(f"raw-only orphans: {', '.join(r['raw_orphans'])}")
        elif r["raw_orphans"]:
            notes.append(f"raw orphans: {', '.join(r['raw_orphans'])}")
        if r["ser_orphans"] and set(r["ser_orphans"]) != set(r["raw_orphans"]):
            notes.append(f"ser orphans: {', '.join(r['ser_orphans'])}")
        if fair["n_eng_only"]:
            notes.append(f"{fair['n_eng_only']} eng-only rocket(s)")
        if r["n_forks"]:
            notes.append(f"{r['n_forks']} fork(s)")
        lines.append(
            f"| {sym} | {fair['pivots_match']} | {fair['zones_ok']} | {fair['retest_ok']} | "
            f"{fair['rocket_where_sheet_fires']} | **{r['raw']}** | **{r['ser']}** | "
            f"{r['prior_ser']} | {r['closed_n']} | {dser_s} | {'; '.join(notes) or '—'} |"
        )
    lines.append("")
    pct = 100.0 * total_ser / total_sheet if total_sheet else 0.0
    prior_pct = 100.0 * total_prior / total_sheet if total_sheet else 0.0
    lines.append(
        f"### Ser rollup: **{total_ser} / {total_sheet}** ({pct:.1f}%) "
        f"vs prior `{PRIOR_STAMP}` **{total_prior} / {total_sheet}** ({prior_pct:.1f}%) "
        f"— Δ **{total_ser - total_prior:+d}**"
    )
    lines.append("")
    if regressions:
        lines.append("### Adverse ser regressions vs prior")
        lines.append("")
        for x in regressions:
            lines.append(f"- {x}")
        lines.append("")
    else:
        lines.append("### Adverse ser regressions vs prior: **none**")
        lines.append("")
    lines.append("## Residuals")
    lines.append("")
    for sym in MARKTEN:
        r = by[sym]
        if r["raw_orphans"] or r["ser_orphans"] or r["new_eng_only"] or r["n_forks"]:
            lines.append(
                f"- **{sym}:** raw `{', '.join(r['raw_orphans']) or '—'}`; "
                f"ser `{', '.join(r['ser_orphans']) or '—'}`; "
                f"new eng-only `{', '.join(r['new_eng_only']) or '—'}`; "
                f"forks={r['n_forks']}"
            )
    lines.append("")
    lines.append("## Engine stacked results (closed trades)")
    lines.append("")
    lines.append("Order per symbol: trades → win% → avg profit% → win/loss → avg days → $PnL")
    lines.append("")
    lines.append("```")
    stack = (STAMP_DIR / "_markten_stacked_stats.txt").read_text(encoding="utf-8").rstrip()
    lines.append(stack)
    lines.append("```")
    lines.append("")
    lines.append("## Artifacts")
    lines.append("")
    lines.append(
        f"- Engine: `drive/wpbr_sheet_reconcile/_markten_variantC_SC_stop91_startfloor_halfup_scresume_20260722174137/` (`{STAMP}`)"
    )
    lines.append("- Status: `drive/wpbr_sheet_reconcile/VARIANT_C_SC_FINAL_MARKTEN_STATUS.md`")
    lines.append("- Stacked: `.../_markten_stacked_stats.txt`")
    lines.append("- `run_wpbr.bat` / DailyRun WPBR step aligned to this parity baseline")
    lines.append("")
    lines.append("*Do not commit.*")
    lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def main() -> int:
    eng = confirm_engine()
    print("engine:", eng)
    results = []
    for sym in MARKTEN:
        print(f"=== {sym} ===")
        r = analyze(sym)
        results.append(r)
        fair = r["fair"]
        print(
            f"  piv/zone/retest {fair['pivots_match']} / {fair['zones_ok']} / {fair['retest_ok']} "
            f"rocket {fair['rocket_where_sheet_fires']} raw {r['raw']} ser {r['ser']} "
            f"(prior {r['prior_ser']}) closed={r['closed_n']} "
            f"cleared={r['ser_cleared']} regressed={r['ser_regressed']} "
            f"focus={r['focus_hits']}"
        )
        write_ticker_status(r, eng)
    summary = write_status(results, eng)
    payload = {
        "stamp": STAMP,
        "stamp_dir": str(STAMP_DIR),
        "prior_stamp": PRIOR_STAMP,
        "engine": eng,
        "results": [
            {
                k: v
                for k, v in r.items()
                if k
                not in {
                    "raw_fills",
                    "sheet_entries",
                    "eng_entries",
                }
            }
            for r in results
        ],
    }
    for r in payload["results"]:
        fair = dict(r["fair"])
        fair["eng_only"] = fair.get("eng_only", [])[:25]
        fair["retest_mismatches"] = fair.get("retest_mismatches", [])[:40]
        r["fair"] = fair
    payload_path = BASE / "_variantC_SC_final_scresume_reconcile_payload.json"
    payload_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"wrote {summary}")
    print(f"wrote {payload_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
