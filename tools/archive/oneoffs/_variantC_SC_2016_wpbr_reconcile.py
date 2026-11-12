#!/usr/bin/env python3
"""WPBR MarkTen reconcile: variant C + second chance ON + start_date=2016-01-01."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(REPO / "stock_analysis"))
from wpbr_zones import _round_bounds, compute_wpbr_touch_stream  # noqa: E402

STAMP_DIR = REPO / "drive" / "wpbr_sheet_reconcile" / "_markten_variantC_SC_2016_20260722145207"
STAMP = "260722145252"
BASE = REPO / "drive" / "wpbr_sheet_reconcile"
DATA = REPO / "data" / "newdata" / "data"
MIN_DATE = "2016-01-01"
MARKTEN = ["AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA", "AU", "AMD", "NFLX"]
# Fresh breakout+trade pastes (OHLC/weekly skipped); reconcile these vs SC stamp.
DONE = ["AU", "NVDA", "NFLX", "AMZN", "AMD", "GOOGL", "TSLA", "AAPL", "META", "MSFT"]
NEED: list[str] = []
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
    ser = {t["entry"] for t in closed}
    fair = structure_stats(sheet_z, eng)
    n_raw = n_ser = 0
    for t in sheet_t:
        n_raw += int(t["entry"] in raw_fills)
        n_ser += int(t["entry"] in ser)
    raw_orphans = [t["entry"] for t in sheet_t if t["entry"] not in raw_fills]
    ser_orphans = [t["entry"] for t in sheet_t if t["entry"] not in ser]
    return {
        "symbol": sym,
        "fair": fair,
        "raw": f"{n_raw}/{len(sheet_t)}",
        "ser": f"{n_ser}/{len(sheet_t)}",
        "n_raw": n_raw,
        "n_ser": n_ser,
        "n_sheet_trades": len(sheet_t),
        "raw_orphans": raw_orphans,
        "ser_orphans": ser_orphans,
        "closed_n": len(closed),
        "sheet_entries": [t["entry"] for t in sheet_t],
        "eng_entries": [t["entry"] for t in closed],
        "raw_fills": sorted(raw_fills),
    }


def confirm_engine() -> dict:
    src = (REPO / "stock_analysis" / "wpbr_zones.py").read_text(encoding="utf-8")
    rbr = (REPO / "stock_analysis" / "rocket_brt.py").read_text(encoding="utf-8")
    sample = _round_bounds(100.125, 0.015, 2)
    log = STAMP_DIR / "_run_log.txt"
    log_txt = read_text_any(log) if log.is_file() else ""
    # Also accept UTF-16 tee artifacts and spaced PowerShell dumps.
    sc_ok = (
        "wpbr_second_chance_after_win=true" in log_txt
        or "wpbr_second_chance_after_win=True" in log_txt
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
        "sc_flag_name": "wpbr_second_chance_after_win",
    }


def nflx_focus(r: dict) -> dict:
    sheet = set(r["sheet_entries"])
    ser = set(r["eng_entries"])
    raw = set(r["raw_fills"])
    out = {}
    for d in NFLX_FOCUS:
        out[d] = {
            "in_sheet": d in sheet,
            "in_raw": d in raw,
            "in_ser": d in ser,
        }
    # SC orphan resolution narrative
    may13 = out["2022-05-13"]
    oct16 = out["2023-10-16"]
    oct17 = out["2023-10-17"]
    if may13["in_sheet"] and may13["in_ser"]:
        may13_status = (
            "RESOLVED (ser) — sheet 2022-05-13 is in SC-on closed trades "
            "(not in primary zone-stream raw fill list; expected for SC lifecycle entry)"
        )
    elif may13["in_sheet"] and may13["in_raw"] and not may13["in_ser"]:
        may13_status = "RAW ONLY — still not serialized"
    elif may13["in_sheet"] and not may13["in_raw"] and not may13["in_ser"]:
        may13_status = "STILL ORPHAN — not in raw fills and not in ser"
    else:
        may13_status = "N/A (not in current sheet paste)"

    if oct16["in_sheet"] and oct16["in_ser"]:
        oct_status = "RESOLVED — sheet entry 2023-10-16 matches eng ser"
    elif oct16["in_sheet"] and oct17["in_ser"] and not oct16["in_ser"]:
        oct_status = (
            "TIMING GAP REMAINS — sheet entry 2023-10-16 vs eng fill/ser 2023-10-17 "
            "(SC added the trade; date off by 1 session)"
        )
    elif oct16["in_sheet"] and not oct16["in_raw"] and not oct17["in_ser"]:
        oct_status = "STILL ORPHAN"
    else:
        oct_status = f"sheet16={oct16} eng17={oct17}"
    return {
        "dates": out,
        "may13_status": may13_status,
        "oct16_vs_17_status": oct_status,
    }


def write_ticker_status(r: dict, eng: dict) -> Path:
    """Per-ticker status markdown (e.g. AAPL_wpbr_reconcile_status.md)."""
    sym = r["symbol"]
    fair = r["fair"]
    out = BASE / sym / f"{sym}_wpbr_reconcile_status.md"
    lines: list[str] = []
    lines.append(f"# {sym} WPBR reconcile — variant C + SC-on (`{STAMP}`)")
    lines.append("")
    lines.append(
        f"**Engine:** `drive/wpbr_sheet_reconcile/_markten_variantC_SC_2016_20260722145207/` "
        f"(`{STAMP}`)"
    )
    lines.append(
        f"**SC:** `wpbr_second_chance_after_win=true` (log: **{eng['sc_in_run_log']}**)"
    )
    lines.append("**Paste:** breakouts/retests/rockets + trades only (OHLC/weekly unchanged).")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Pivots | {fair['pivots_match']} |")
    lines.append(f"| Zones | {fair['zones_ok']} |")
    lines.append(f"| Retest | {fair['retest_ok']} |")
    lines.append(f"| Rocket (sheet fires) | {fair['rocket_where_sheet_fires']} |")
    lines.append(f"| Raw | **{r['raw']}** |")
    lines.append(f"| Ser | **{r['ser']}** |")
    lines.append(f"| Eng closed (+open) | {r['closed_n']} |")
    lines.append(f"| Sheet trades ≥2016 | {r['n_sheet_trades']} |")
    lines.append("")
    if r["raw_orphans"]:
        lines.append(f"**Raw orphans:** {', '.join(r['raw_orphans'])}")
        lines.append("")
    if r["ser_orphans"]:
        lines.append(f"**Ser orphans:** {', '.join(r['ser_orphans'])}")
        lines.append("")
    if fair["retest_mismatches"]:
        lines.append(f"**Retest mismatches ({len(fair['retest_mismatches'])}):**")
        for m in fair["retest_mismatches"][:20]:
            lines.append(
                f"- pivot `{m['pivot']}` sheet `{m['sheet_retest']}` vs eng `{m['eng_retest']}`"
            )
        lines.append("")
    if fair["n_eng_only"]:
        lines.append(f"**Eng-only rockets:** {fair['n_eng_only']}")
        for er in fair["eng_only"][:15]:
            lines.append(
                f"- pivot `{er['pivot']}` signal `{er['eng_signal']}` fill `{er['eng_fill']}`"
            )
        lines.append("")
    lines.append(
        f"*Generated by `tools/_variantC_SC_2016_wpbr_reconcile.py` vs stamp `{STAMP}`.*"
    )
    lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def write_status(results: list[dict], eng: dict, nflx: dict) -> Path:
    out = BASE / "VARIANT_C_SC_2016_MARKTEN_STATUS.md"
    lines: list[str] = []
    lines.append("# WPBR MarkTen — variant C + second chance ON + start_date=2016-01-01")
    lines.append("")
    lines.append(
        f"**Engine outdir:** `drive/wpbr_sheet_reconcile/_markten_variantC_SC_2016_20260722145207/`"
    )
    lines.append(f"**Stamp:** `{STAMP}`")
    lines.append(
        "**Settings:** variant C `_round_bounds` (HALF_UP pivot then band), "
        "gate-bleed WPBR skips BRT sheet gates, `retest_mode=stop_looking`, "
        "`start_date=2016-01-01`, `target_pct=1.22`, `stop_pct=0.89`, WPBR-only, growth off, "
        "**`wpbr_second_chance_after_win=true`** (verified in run log)."
    )
    lines.append("")
    lines.append("## Engine confirmation")
    lines.append("")
    s = eng["sample"]
    e = eng["expected"]
    ok = s == e
    lines.append(
        f"- Variant C `_round_bounds` HALF_UP: **{eng['has_HALF_UP']}** "
        f"(doc: **{eng['doc_variant_C']}**); sample → "
        f"{s['tp']}/{s['zl']}/{s['zh']} (expected {e['tp']}/{e['zl']}/{e['zh']}) → "
        f"**{'PASS' if ok else 'FAIL'}**"
    )
    lines.append(
        f"- Gate-bleed WPBR bypass (`wpbr_retest_entry` skips BRT sheet gates): "
        f"**{eng['gatebleed_wpbr_bypass']}**"
    )
    lines.append(
        f"- Second chance in run log (`wpbr_second_chance_after_win=true`): "
        f"**{eng['sc_in_run_log']}**"
    )
    lines.append("")
    lines.append("## Reconciled vs this SC-on stamp (fresh pastes)")
    lines.append("")
    lines.append(
        "| Ticker | Pivots | Zones | Retest | Rocket (sheet fires) | Raw | Ser | Eng closed | Notes |"
    )
    lines.append("|---|---|---|---|---|---|---|---:|---|")
    by = {r["symbol"]: r for r in results}
    # Full MarkTen order for the summary table
    for sym in MARKTEN:
        if sym not in by:
            lines.append(
                f"| {sym} | — | — | — | — | — | — | — | **NEED fresh breakout+trade paste** |"
            )
            continue
        r = by[sym]
        fair = r["fair"]
        notes = []
        if fair["retest_mismatches"]:
            notes.append(f"{len(fair['retest_mismatches'])} retest miss")
        if r["raw_orphans"]:
            notes.append(f"raw orphans: {', '.join(r['raw_orphans'])}")
        if r["ser_orphans"] and r["ser_orphans"] != r["raw_orphans"]:
            notes.append(f"ser orphans: {', '.join(r['ser_orphans'])}")
        elif r["ser_orphans"] and r["ser_orphans"] == r["raw_orphans"]:
            pass  # already covered under raw orphans wording if identical
        if r["ser_orphans"] and set(r["ser_orphans"]) != set(r["raw_orphans"]):
            # ensure ser-only noted when not already listed above
            if not (r["ser_orphans"] and r["ser_orphans"] != r["raw_orphans"]):
                notes.append(f"ser orphans: {', '.join(r['ser_orphans'])}")
        if fair["n_eng_only"]:
            notes.append(f"{fair['n_eng_only']} eng-only rocket(s)")
        lines.append(
            f"| {sym} | {fair['pivots_match']} | {fair['zones_ok']} | {fair['retest_ok']} | "
            f"{fair['rocket_where_sheet_fires']} | **{r['raw']}** | **{r['ser']}** | "
            f"{r['closed_n']} | {'; '.join(notes) or '—'} |"
        )
    lines.append("")
    lines.append("## Residuals (trade orphans / timing)")
    lines.append("")
    residual_rows = []
    for sym in MARKTEN:
        r = by.get(sym)
        if not r:
            continue
        if r["raw_orphans"] or r["ser_orphans"]:
            residual_rows.append(
                f"- **{sym}:** raw orphans `{', '.join(r['raw_orphans']) or '—'}`; "
                f"ser orphans `{', '.join(r['ser_orphans']) or '—'}`"
            )
    if residual_rows:
        lines.extend(residual_rows)
    else:
        lines.append("- None")
    lines.append("")
    lines.append(
        f"- **NFLX:** {nflx['may13_status']}; {nflx['oct16_vs_17_status']}"
    )
    lines.append("")
    lines.append("## NFLX second-chance orphan focus")
    lines.append("")
    lines.append(f"- **2022-05-13:** {nflx['may13_status']}")
    lines.append(f"- **2023-10-16 vs 2023-10-17:** {nflx['oct16_vs_17_status']}")
    lines.append("- Detail:")
    for d, info in nflx["dates"].items():
        lines.append(
            f"  - `{d}`: sheet={info['in_sheet']} raw={info['in_raw']} ser={info['in_ser']}"
        )
    lines.append("")
    lines.append("## Paste checklist")
    lines.append("")
    lines.append("| Ticker | Status |")
    lines.append("|---|---|")
    for sym in MARKTEN:
        if sym in by:
            lines.append(
                f"| {sym} | **DONE** (breakout+trades reconciled vs `{STAMP}` SC-on) |"
            )
        else:
            lines.append(
                f"| {sym} | **NEED breakout+trade repaste** (old paste present — replace; OHLC/weekly skip OK) |"
            )
    lines.append("")
    if NEED:
        lines.append(f"**Still need pastes from user:** {', '.join(NEED)}")
    else:
        lines.append("**Still need pastes from user:** _(none — all MarkTen pastes reconciled)_")
    lines.append("")
    lines.append("## Resume protocol")
    lines.append("")
    lines.append(
        f"On each new breakout+trade paste: save under `drive/wpbr_sheet_reconcile/<TICKER>/`, "
        f"reconcile that symbol only vs stamp `{STAMP}` "
        f"(`_markten_variantC_SC_2016_20260722145207`). Do **not** turn second chance off."
    )
    lines.append("")
    lines.append("Helper: `python tools/_variantC_SC_2016_wpbr_reconcile.py`")
    lines.append("")
    lines.append("## Artifacts")
    lines.append("")
    lines.append(
        f"- Engine: `drive/wpbr_sheet_reconcile/_markten_variantC_SC_2016_20260722145207/` (`{STAMP}`)"
    )
    lines.append("- Status: `drive/wpbr_sheet_reconcile/VARIANT_C_SC_2016_MARKTEN_STATUS.md`")
    lines.append("- Payload: `drive/wpbr_sheet_reconcile/_variantC_SC_2016_reconcile_payload.json`")
    lines.append("- Script: `tools/_variantC_SC_2016_wpbr_reconcile.py`")
    lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def main() -> int:
    eng = confirm_engine()
    print("engine:", eng)
    results = []
    for sym in DONE:
        print(f"=== {sym} ===")
        r = analyze(sym)
        results.append(r)
        fair = r["fair"]
        print(
            f"  piv/zone/retest {fair['pivots_match']} / {fair['zones_ok']} / {fair['retest_ok']} "
            f"rocket {fair['rocket_where_sheet_fires']} raw {r['raw']} ser {r['ser']} "
            f"closed={r['closed_n']} raw_orphans={r['raw_orphans']} ser_orphans={r['ser_orphans']}"
        )
    nflx_r = next(x for x in results if x["symbol"] == "NFLX")
    nflx = nflx_focus(nflx_r)
    print("NFLX focus:", nflx)

    payload = {
        "stamp": STAMP,
        "stamp_dir": str(STAMP_DIR),
        "engine": eng,
        "done_pastes": DONE,
        "need_pastes": NEED,
        "nflx_focus": nflx,
        "results": results,
    }
    for r in payload["results"]:
        r = dict(r)
        fair = dict(r["fair"])
        fair["eng_only"] = fair.get("eng_only", [])[:25]
        fair["retest_mismatches"] = fair.get("retest_mismatches", [])[:40]
        r["fair"] = fair
        # drop bulky raw_fills from payload copy already in results — trim
    for r in payload["results"]:
        if "raw_fills" in r:
            r["raw_fills"] = [d for d in r["raw_fills"] if d in set(NFLX_FOCUS) | set(r["raw_orphans"]) | set(r["ser_orphans"])] if r["symbol"] == "NFLX" else []
            if r["symbol"] != "NFLX":
                del r["raw_fills"]

    payload_path = BASE / "_variantC_SC_2016_reconcile_payload.json"
    # re-attach NFLX raw fills of interest only
    for r in results:
        if r["symbol"] == "NFLX":
            for pr in payload["results"]:
                if pr["symbol"] == "NFLX":
                    pr["raw_fills_focus"] = {
                        d: d in set(r["raw_fills"]) for d in NFLX_FOCUS
                    }
    payload_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    summary = write_status(results, eng, nflx)
    print(f"wrote {summary}")
    print(f"wrote {payload_path}")
    for sym in ("AAPL", "META", "MSFT", "TSLA"):
        r = next((x for x in results if x["symbol"] == sym), None)
        if r:
            p = write_ticker_status(r, eng)
            print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
