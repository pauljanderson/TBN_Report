#!/usr/bin/env python3
"""WPBR MarkTen reconcile: variant C + start_date=2016-01-01 vs existing sheet pastes.

Existing pastes may still blank rockets before 2019 (old sheet gate). User will replace
pastes with full 2016+ exports (no rocket gate). This pass flags that mismatch.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(REPO / "stock_analysis"))
from wpbr_zones import _round_bounds, compute_wpbr_touch_stream  # noqa: E402

STAMP_DIR = REPO / "drive" / "wpbr_sheet_reconcile" / "_markten_variantC_2016_20260722134127"
STAMP = "260722134152"
BASE = REPO / "drive" / "wpbr_sheet_reconcile"
DATA = REPO / "data" / "newdata" / "data"
MIN_DATE = "2016-01-01"
OLD_ROCKET_GATE = "2019-01-01"
MARKTEN = ["AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA", "AU", "AMD", "NFLX"]
FOCUS_RETEST = ["NVDA", "AMZN"]


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


def parse_entry(s) -> str | None:
    d = nd(s)
    if d:
        return d
    # YYYYMMDD int from engine CSV
    try:
        t = str(int(s))
        if len(t) == 8:
            return f"{t[:4]}-{t[4:6]}-{t[6:8]}"
    except Exception:
        pass
    return None


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


def load_closed(stamp_dir: Path, stamp: str, sym: str) -> list[dict]:
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


def structure_stats(sheet_z, eng, *, suppress_eng_signal_before: str | None = None):
    zone_ok = retest_ok = rocket_ok = rocket_where_sheet = 0
    rocket_sheet_fires = 0
    eng_only_rockets = []
    retest_mismatches = []
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
            retest_mismatches.append(
                {
                    "pivot": z["pivot"],
                    "sheet_retest": z["retest"],
                    "eng_retest": e["retest"],
                    "zlow": e["zlow"],
                    "zhigh": e["zhigh"],
                }
            )
        eng_sig = e["signal"]
        if suppress_eng_signal_before and eng_sig and eng_sig < suppress_eng_signal_before:
            eng_sig = None
        if z["rocket"]:
            rocket_sheet_fires += 1
            if z["rocket"] == eng_sig:
                rocket_where_sheet += 1
                rocket_ok += 1
        else:
            if eng_sig:
                eng_only_rockets.append(
                    {
                        "pivot": z["pivot"],
                        "eng_signal": eng_sig,
                        "eng_fill": e["fill"],
                        "pre2019_signal": bool(eng_sig and eng_sig < OLD_ROCKET_GATE),
                    }
                )
            else:
                rocket_ok += 1
    sheet_pivs = {z["pivot"] for z in sheet_z}
    return {
        "n_sheet_zones": len(sheet_z),
        "n_eng_in_window": len(eng),
        "pivots_match": f"{len(sheet_pivs & set(eng))}/{len(sheet_z)}",
        "n_pairs": n_pairs,
        "zones_ok": f"{zone_ok}/{n_pairs}",
        "retest_ok": f"{retest_ok}/{n_pairs}",
        "rocket_ok_pairs": f"{rocket_ok}/{n_pairs}",
        "rocket_where_sheet_fires": f"{rocket_where_sheet}/{rocket_sheet_fires}",
        "eng_only_rockets": eng_only_rockets,
        "n_eng_only_rockets": len(eng_only_rockets),
        "n_eng_only_pre2019_signal": sum(1 for r in eng_only_rockets if r.get("pre2019_signal")),
        "retest_mismatches": retest_mismatches,
    }


def has_paste(sym: str) -> bool:
    d = BASE / sym
    return (d / "zones.tsv").is_file() or (d / "sheet_zones.tsv").is_file()


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

    closed = load_closed(STAMP_DIR, STAMP, sym)
    closed_pre2016 = [t for t in closed if t["entry"] and t["entry"] < MIN_DATE]
    closed_2016_2018 = [
        t for t in closed if t["entry"] and MIN_DATE <= t["entry"] < OLD_ROCKET_GATE
    ]

    st_fair = structure_stats(sheet_z, eng)
    # Old paste rocket gate mirror (sheet blanks <2019)
    st_gate = structure_stats(sheet_z, eng, suppress_eng_signal_before=OLD_ROCKET_GATE)

    ser = {t["entry"] for t in closed}
    trade_rows = []
    orphans = []
    n_raw = n_ser = 0
    for t in sheet_t:
        in_raw = t["entry"] in raw_fills
        in_ser = t["entry"] in ser
        n_raw += int(in_raw)
        n_ser += int(in_ser)
        trade_rows.append({**t, "raw": in_raw, "ser": in_ser})
        if not in_raw:
            orphans.append(t["entry"])

    return {
        "symbol": sym,
        "n_sheet_zones_all": len(sheet_z_all),
        "n_sheet_zones_ge2016": len(sheet_z),
        "n_sheet_trades_all": len(sheet_t_all),
        "n_sheet_trades_ge2016": len(sheet_t),
        "fair": st_fair,
        "old_gate_mirror": st_gate,
        "raw": f"{n_raw}/{len(sheet_t)}",
        "ser": f"{n_ser}/{len(sheet_t)}",
        "n_raw": n_raw,
        "n_ser": n_ser,
        "orphans": orphans,
        "closed_n": len(closed),
        "closed_pre2016_n": len(closed_pre2016),
        "closed_2016_2018_n": len(closed_2016_2018),
        "trade_rows": trade_rows,
        "retest_mismatches": st_fair["retest_mismatches"],
        "eng_only_pre2019": [
            r for r in st_fair["eng_only_rockets"] if r.get("pre2019_signal")
        ][:15],
    }


def confirm_variant_c() -> dict:
    src = Path(REPO / "stock_analysis" / "wpbr_zones.py").read_text(encoding="utf-8")
    sample = _round_bounds(100.125, 0.015, 2)
    return {
        "has_HALF_UP": "ROUND_HALF_UP" in src,
        "doc_says_variant_C": "variant C" in src,
        "sample_100_125_band_1_5pct": {"tp": sample[0], "zl": sample[1], "zh": sample[2]},
        "expected": {"tp": 100.13, "zl": 98.63, "zh": 101.63},
    }


def write_status(results: list[dict], missing: list[str], vc: dict) -> Path:
    out = BASE / "VARIANT_C_2016_MARKTEN_STATUS.md"
    lines: list[str] = []
    lines.append("# WPBR MarkTen — variant C + start_date=2016-01-01")
    lines.append("")
    lines.append(f"**Engine outdir:** `drive/wpbr_sheet_reconcile/_markten_variantC_2016_20260722134127/`")
    lines.append(f"**Stamp:** `{STAMP}`")
    lines.append(
        "**Settings:** variant C `_round_bounds` (HALF_UP pivot then band), "
        "`retest_mode=stop_looking` (default), `start_date=2016-01-01` → `entry_start_date`, "
        "`target_pct=1.22`, `stop_pct=0.89`, WPBR-only zones, growth off, "
        "`--aggressive --use-duckdb --no-regression`."
    )
    lines.append("")
    lines.append("## Variant C confirmation")
    lines.append("")
    lines.append(
        f"- `_round_bounds` uses Decimal `ROUND_HALF_UP`: **{vc['has_HALF_UP']}** "
        f"(doc mentions variant C: **{vc['doc_says_variant_C']}**)"
    )
    s = vc["sample_100_125_band_1_5pct"]
    e = vc["expected"]
    ok = s == e
    lines.append(
        f"- Sample `_round_bounds(100.125, 0.015, 2)` → "
        f"tp={s['tp']}, zl={s['zl']}, zh={s['zh']} "
        f"(expected {e['tp']}/{e['zl']}/{e['zh']}) → **{'PASS' if ok else 'FAIL'}**"
    )
    lines.append("")
    lines.append("## Important — paste refresh in progress")
    lines.append("")
    lines.append(
        "User is **undoing** the sheet’s arbitrary rocket date gate (was later-than 1/1/2019) "
        "and will **repaste all MarkTen sheet data from 1/1/2016**. Numbers below compare this "
        "engine stamp to **existing** pastes, which may still blank pre-2019 rockets. "
        "Expect rocket / ser diffs on the 2016–2018 window until new pastes land."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Cross-ticker summary vs **current** pastes (≥2016)")
    lines.append("")
    lines.append(
        "| Ticker | Pivots | Zones | Retest | Rocket (sheet fires) | Raw | Ser | Eng closed | Eng-only rockets (sig <2019) | Notes |"
    )
    lines.append("|---|---|---|---|---|---|---|---:|---:|---|")
    for r in results:
        fair = r["fair"]
        gate = r["old_gate_mirror"]
        note = []
        if fair["retest_mismatches"]:
            note.append(f"{len(fair['retest_mismatches'])} retest miss")
        if r["orphans"]:
            note.append(f"{len(r['orphans'])} orphan(s)")
        if r["eng_only_pre2019"]:
            note.append("old paste rocket-gate blanks likely")
        lines.append(
            f"| {r['symbol']} | {fair['pivots_match']} | {fair['zones_ok']} | {fair['retest_ok']} | "
            f"{fair['rocket_where_sheet_fires']} "
            f"(gate-mirror {gate['rocket_where_sheet_fires']}) | "
            f"**{r['raw']}** | **{r['ser']}** | {r['closed_n']} "
            f"(2016–18: {r['closed_2016_2018_n']}) | "
            f"{fair['n_eng_only_pre2019_signal']} | {'; '.join(note) or '—'} |"
        )
    for s in MARKTEN:
        if s not in {r["symbol"] for r in results}:
            lines.append(f"| {s} | — | — | — | — | — | — | — | — | **NO PASTE** |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## NVDA / AMZN retest focus (variant C)")
    lines.append("")
    for sym in FOCUS_RETEST:
        r = next((x for x in results if x["symbol"] == sym), None)
        if not r:
            lines.append(f"### {sym}")
            lines.append("")
            lines.append("_No paste — cannot compare retests yet._")
            lines.append("")
            continue
        fair = r["fair"]
        lines.append(f"### {sym}")
        lines.append("")
        lines.append(
            f"- Sheet zones ≥2016: **{r['n_sheet_zones_ge2016']}** / all-paste {r['n_sheet_zones_all']}"
        )
        lines.append(
            f"- Retest match: **{fair['retest_ok']}** "
            f"(pivots {fair['pivots_match']}, zones {fair['zones_ok']})"
        )
        mism = r["retest_mismatches"]
        if mism:
            lines.append(f"- Retest mismatches ({len(mism)}):")
            for m in mism[:20]:
                lines.append(
                    f"  - pivot `{m['pivot']}` sheet `{m['sheet_retest']}` vs eng `{m['eng_retest']}` "
                    f"z=({m['zlow']},{m['zhigh']})"
                )
        else:
            lines.append("- Retest mismatches: **none** on paired ≥2016 pivots")
        if r["eng_only_pre2019"]:
            lines.append(
                f"- Eng-only rockets with signal <2019 (old paste gate class): {len(r['eng_only_pre2019'])} shown"
            )
            for er in r["eng_only_pre2019"][:8]:
                lines.append(
                    f"  - pivot `{er['pivot']}` signal `{er['eng_signal']}` fill `{er['eng_fill']}`"
                )
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Paste checklist (user must (re)paste all MarkTen)")
    lines.append("")
    lines.append(
        "Repaste from sheet starting **1/1/2016** with **no** later-than-2019 rocket gate. "
        "Save under `drive/wpbr_sheet_reconcile/<TICKER>/` as `zones.tsv` + `trades.tsv` "
        "(optional: `sheet_weekly.tsv`, `ohlc.tsv`, `_raw_user_paste.txt`)."
    )
    lines.append("")
    lines.append("| Ticker | Current paste | Action |")
    lines.append("|---|---|---|")
    for s in MARKTEN:
        d = BASE / s
        has_z = (d / "zones.tsv").is_file() or (d / "sheet_zones.tsv").is_file()
        has_t = (d / "trades.tsv").is_file() or (d / "sheet_trades.tsv").is_file()
        if s == "AU" and not has_z and not has_t:
            status = "**NEVER had a paste** — first paste needed"
        elif has_z and has_t:
            status = "EXISTS (old; may still have 2019 rocket gate) → **REPLACE**"
        elif has_z or has_t:
            status = "PARTIAL → **COMPLETE + REPLACE**"
        else:
            status = "**MISSING** → paste needed"
        lines.append(f"| {s} | {'zones+trades' if (has_z and has_t) else ('partial' if (has_z or has_t) else 'none')} | {status} |")
    lines.append("")
    lines.append(
        "**Full list to (re)paste:** AAPL, AMZN, GOOGL, META, MSFT, NVDA, TSLA, AU, AMD, NFLX"
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Resume protocol (per ticker)")
    lines.append("")
    lines.append("When a new paste arrives for one ticker:")
    lines.append("")
    lines.append("1. Save files under `drive/wpbr_sheet_reconcile/<TICKER>/`")
    lines.append(
        f"2. Re-reconcile **that symbol only** vs stamp `{STAMP}` "
        f"(`_markten_variantC_2016_20260722134127`) — do not rerun the full MarkTen engine "
        "unless code/`start_date` changes"
    )
    lines.append("3. Update this status doc’s per-ticker row")
    lines.append("")
    lines.append("Helper: `python tools/_variantC_2016_wpbr_reconcile.py` (edits stamp path at top if needed).")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Artifacts")
    lines.append("")
    lines.append(f"- Engine: `drive/wpbr_sheet_reconcile/_markten_variantC_2016_20260722134127/` (`{STAMP}`)")
    lines.append("- Status: `drive/wpbr_sheet_reconcile/VARIANT_C_2016_MARKTEN_STATUS.md`")
    lines.append("- Payload: `drive/wpbr_sheet_reconcile/_variantC_2016_reconcile_payload.json`")
    lines.append("- Script: `tools/_variantC_2016_wpbr_reconcile.py`")
    lines.append("")
    if missing:
        lines.append(f"**Still missing any paste:** {', '.join(missing)}")
        lines.append("")

    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def main() -> int:
    vc = confirm_variant_c()
    print("variant C:", vc)
    missing = [s for s in MARKTEN if not has_paste(s)]
    print("missing pastes:", missing or "(none)")
    results = []
    for sym in MARKTEN:
        if not has_paste(sym):
            print(f"SKIP {sym}: no paste")
            continue
        print(f"=== {sym} ===")
        r = analyze(sym)
        results.append(r)
        fair = r["fair"]
        print(
            f"  piv/zone/retest {fair['pivots_match']} / {fair['zones_ok']} / {fair['retest_ok']} "
            f"rocket {fair['rocket_where_sheet_fires']} "
            f"raw {r['raw']} ser {r['ser']} "
            f"eng_only_pre2019={fair['n_eng_only_pre2019_signal']} closed={r['closed_n']}"
        )
        if sym in FOCUS_RETEST and r["retest_mismatches"]:
            for m in r["retest_mismatches"][:10]:
                print(f"    retest miss pivot={m['pivot']} sheet={m['sheet_retest']} eng={m['eng_retest']}")

    payload = {
        "stamp": STAMP,
        "stamp_dir": str(STAMP_DIR),
        "min_date": MIN_DATE,
        "variant_c": vc,
        "missing_pastes": missing,
        "paste_checklist": MARKTEN,
        "results": results,
    }
    # slim rockets
    for r in payload["results"]:
        for key in ("fair", "old_gate_mirror"):
            if key in r and isinstance(r[key], dict):
                d = dict(r[key])
                d["eng_only_rockets"] = d.get("eng_only_rockets", [])[:25]
                d["retest_mismatches"] = d.get("retest_mismatches", [])[:40]
                r[key] = d
    payload_path = BASE / "_variantC_2016_reconcile_payload.json"
    payload_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    summary = write_status(results, missing, vc)
    print(f"wrote {summary}")
    print(f"wrote {payload_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
