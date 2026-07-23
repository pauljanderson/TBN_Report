#!/usr/bin/env python3
"""WPBR MarkTen reconcile with start_date=2019-01-01 vs sheet pastes.

Compares engine stamp under _markten_start2019_* to pasted sheet zones/trades.
Fairness filter: sheet/engine structure + trades on/after 2019-01-01.
Also reports raw (unfiltered) eng-only rockets and closed-trade pre-2019 counts.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(REPO / "stock_analysis"))
from wpbr_zones import compute_wpbr_touch_stream  # noqa: E402

STAMP_DIR = REPO / "drive" / "wpbr_sheet_reconcile" / "_markten_start2019_20260722125713"
STAMP = "260722125727"
GATEBLEED_DIR = REPO / "drive" / "wpbr_sheet_reconcile" / "_markten_gatebleed_20260722113454"
GATEBLEED_STAMP = "260722113454"
BASE = REPO / "drive" / "wpbr_sheet_reconcile"
DATA = REPO / "data" / "newdata" / "data"
MIN_DATE = "2019-01-01"
MARKTEN = ["AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA", "AU", "AMD", "NFLX"]
PASTED = ["META", "NVDA", "NFLX", "AMZN", "AMD", "GOOGL", "TSLA", "AAPL", "MSFT"]


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
                "pnl": c[4].strip() if len(c) > 4 else "",
                "result": c[6].strip() if len(c) > 6 else "",
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
                "entry": nd(r["DATE_OPENED"]),
                "exit": nd(r["DATE_CLOSED"]),
                "entry_px": nf(r["ENTRY_PRICE"]),
                "exit_px": nf(r["EXIT_PRICE"]),
                "exit_type": str(r.get("EXIT_TYPE", "")),
                "pnl": nf(r["PNL_PCT"]),
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
                        "entry": nd(r["DATE_OPENED"]),
                        "exit": None,
                        "entry_px": nf(r["ENTRY_PRICE"]),
                        "exit_px": None,
                        "exit_type": "OPEN",
                        "pnl": None,
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
                        "zlow": e["zlow"],
                        "zhigh": e["zhigh"],
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
    }


def analyze(sym: str) -> dict:
    out_dir = BASE / sym
    df = pd.read_csv(DATA / f"{sym}.csv", index_col=0, parse_dates=True)
    eng_all, raw_all = build_eng(df)

    # Fairness window: pivots on/after MIN_DATE (sheet paste may include earlier rows)
    sheet_z_all = load_sheet_zones(out_dir)
    sheet_z = [z for z in sheet_z_all if z["pivot"] and z["pivot"] >= MIN_DATE]
    eng = {p: e for p, e in eng_all.items() if p >= MIN_DATE}
    raw_fills = {f for f in raw_all if f and f >= MIN_DATE}

    sheet_t_all = load_sheet_trades(out_dir)
    sheet_t = [t for t in sheet_t_all if t["entry"] and t["entry"] >= MIN_DATE]

    closed_new = load_closed(STAMP_DIR, STAMP, sym)
    closed_gb = (
        load_closed(GATEBLEED_DIR, GATEBLEED_STAMP, sym)
        if (GATEBLEED_DIR / f"WPBR_Closed_{GATEBLEED_STAMP}.csv").is_file()
        else []
    )
    closed_gb_ge2019 = [t for t in closed_gb if t["entry"] and t["entry"] >= MIN_DATE]
    closed_new_pre = [t for t in closed_new if t["entry"] and t["entry"] < MIN_DATE]

    st_fair = structure_stats(sheet_z, eng)
    # Mirror sheet rocket gate: blank eng signals before 2019 even on ge-2019 pivots
    st_gate = structure_stats(sheet_z, eng, suppress_eng_signal_before=MIN_DATE)
    # Unfiltered eng-only on full sheet (shows pre-2019 blanks)
    st_full = structure_stats(sheet_z_all, eng_all)

    ser_new = {t["entry"] for t in closed_new}
    ser_gb = {t["entry"] for t in closed_gb}
    ser_gb_ge = {t["entry"] for t in closed_gb_ge2019}

    sheet_raw = []
    sheet_ser = []
    sheet_ser_gb = []
    orphans = []
    trade_rows = []
    for t in sheet_t:
        in_raw = t["entry"] in raw_fills
        in_ser = t["entry"] in ser_new
        in_gb = t["entry"] in ser_gb_ge
        sheet_raw.append(in_raw)
        sheet_ser.append(in_ser)
        sheet_ser_gb.append(in_gb)
        trade_rows.append({**t, "raw": in_raw, "ser": in_ser, "ser_gb2019": in_gb})
        if not in_raw:
            near_rocket = any(
                z["rocket"]
                and abs((pd.Timestamp(t["entry"]) - pd.Timestamp(z["rocket"])).days) <= 5
                for z in sheet_z
                if z["rocket"]
            )
            orphans.append({**t, "near_rocket": near_rocket})

    # Eng-only rockets with signal < 2019 (the sheet-gate class)
    eng_only_pre2019 = [
        er for er in st_full["eng_only_rockets"] if er["eng_signal"] and er["eng_signal"] < MIN_DATE
    ]
    eng_only_ge2019 = [
        er for er in st_fair["eng_only_rockets"] if er["eng_signal"] and er["eng_signal"] >= MIN_DATE
    ]

    # Occupancy: first serialized eng fill with no sheet rocket within ±5d
    sheet_rocket_by_pivot = {z["pivot"]: z["rocket"] for z in sheet_z_all}
    first_eng_only_ser = None
    for tr in closed_new:
        matched = None
        for piv, ez in eng_all.items():
            if ez["fill"] == tr["entry"]:
                matched = (piv, ez)
                break
        if matched:
            piv, ez = matched
            sheet_r = sheet_rocket_by_pivot.get(piv)
            if not sheet_r:
                first_eng_only_ser = {
                    "entry": tr["entry"],
                    "exit": tr["exit"],
                    "pivot": piv,
                    "eng_signal": ez["signal"],
                    "reason": "sheet rocket blank on zone that engine filled",
                }
                break
        else:
            sheet_has = any(
                z["rocket"]
                and abs((pd.Timestamp(tr["entry"]) - pd.Timestamp(z["rocket"])).days) <= 5
                for z in sheet_z_all
                if z["rocket"]
            )
            if not sheet_has:
                first_eng_only_ser = {
                    "entry": tr["entry"],
                    "exit": tr["exit"],
                    "pivot": None,
                    "reason": "serialized fill with no sheet rocket within ±5d",
                }
                break

    # Cascade blocks among sheet∩raw not serialized
    blocked = []
    closed_sorted = sorted(closed_new, key=lambda x: x["entry"] or "")
    for t, in_raw, in_ser in zip(sheet_t, sheet_raw, sheet_ser):
        if not in_raw or in_ser:
            continue
        entry = t["entry"]
        occ = None
        for tr in closed_sorted:
            if not tr["entry"] or tr["entry"] > entry:
                break
            if tr["exit"] is None or tr["exit"] > entry or (
                tr["exit"] == entry and not tr.get("open")
            ):
                # open through entry (or exit same day occupies under one-slot)
                if tr["exit"] is None or tr["exit"] >= entry:
                    occ = tr
                    break
        # simpler occupancy: last closed with entry<=sheet_entry and (exit is None or exit>sheet_entry)
        occ = None
        for tr in closed_sorted:
            if tr["entry"] and tr["entry"] <= entry:
                if tr["exit"] is None or tr["exit"] > entry:
                    occ = tr
        if occ is None:
            # also exit-same-day block
            for tr in closed_sorted:
                if tr["entry"] and tr["entry"] <= entry and tr["exit"] == entry:
                    occ = tr
        blocked.append(
            {
                "sheet_entry": entry,
                "occupied_by": occ["entry"] if occ else None,
                "occ_exit": occ["exit"] if occ else None,
                "occ_is_sheet": (occ["entry"] in {x["entry"] for x in sheet_t}) if occ else None,
            }
        )

    n_sheet = len(sheet_t)
    n_raw = sum(sheet_raw)
    n_ser = sum(sheet_ser)
    cascade_blocks = [b for b in blocked if b.get("occupied_by")]

    return {
        "symbol": sym,
        "stamp": STAMP,
        "n_sheet_zones_all": len(sheet_z_all),
        "n_sheet_zones_ge2019": len(sheet_z),
        "fair": st_fair,
        "fair_gate_mirror": st_gate,
        "full": st_full,
        "n_eng_only_pre2019": len(eng_only_pre2019),
        "eng_only_pre2019": eng_only_pre2019[:12],
        "n_eng_only_ge2019": len(eng_only_ge2019),
        "eng_only_ge2019": eng_only_ge2019[:12],
        "n_sheet_trades_all": len(sheet_t_all),
        "n_sheet_trades_ge2019": n_sheet,
        "raw": f"{n_raw}/{n_sheet}",
        "ser": f"{n_ser}/{n_sheet}",
        "ser_gb_ge2019": f"{sum(sheet_ser_gb)}/{n_sheet}",
        "n_raw": n_raw,
        "n_ser": n_ser,
        "orphans": orphans,
        "closed_new_n": len(closed_new),
        "closed_new_pre2019_n": len(closed_new_pre),
        "closed_gb_n": len(closed_gb),
        "closed_gb_ge2019_n": len(closed_gb_ge2019),
        "closed_gb_pre2019_n": len(closed_gb) - len(closed_gb_ge2019),
        "first_eng_only_ser": first_eng_only_ser,
        "blocked": blocked,
        "cascade_blocks": cascade_blocks,
        "trade_rows": trade_rows,
    }


def has_paste(sym: str) -> bool:
    d = BASE / sym
    return (d / "zones.tsv").is_file() or (d / "sheet_zones.tsv").is_file()


def write_summary(results: list[dict], missing: list[str]) -> Path:
    out = BASE / "START_2019_RECONCILE_SUMMARY.md"
    lines = []
    lines.append("# WPBR MarkTen — start_date=2019-01-01 sheet reconcile")
    lines.append("")
    lines.append(f"**Engine outdir:** `drive/wpbr_sheet_reconcile/_markten_start2019_20260722125713/`")
    lines.append(f"**Stamp:** `{STAMP}`")
    lines.append(
        "**Settings:** `retest_mode=stop_looking` (default), "
        "`start_date=2019-01-01` → `entry_start_date` (warmup history retained; entries gated), "
        "`target_pct=1.22`, `stop_pct=0.89`, WPBR-only zones, growth off, "
        "`--aggressive --use-duckdb --no-regression --print-zones`."
    )
    lines.append(
        f"**Compare-to (occupancy/trades):** gate-bleed stamp `{GATEBLEED_STAMP}` "
        f"under `_markten_gatebleed_20260722113454/` (start was 2016-01-01)."
    )
    lines.append("")
    lines.append("## Fairness filter")
    lines.append("")
    lines.append(
        "Sheet pastes still include pre-2019 weekly zones. For match rates below, "
        "**pivots / trades are restricted to on-or-after 2019-01-01**. "
        "Engine closed/open under this stamp already have **zero** entries before 2019 "
        "(confirmed across MarkTen)."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Cross-ticker summary (pasted tickers, ≥2019)")
    lines.append("")
    lines.append(
        "| Ticker | Piv/zone/retest | Rocket where sheet fires | Eng-only rockets (≥2019 sig) | "
        "Raw | Ser (2019 run) | Ser gatebleed ≥2019 | Eng closed | Notes |"
    )
    lines.append("|---|---|---|---:|---|---|---|---:|---|")
    for r in results:
        fair = r["fair"]
        notes = []
        if r["orphans"]:
            notes.append(f"{len(r['orphans'])} orphan(s)")
        if r["cascade_blocks"]:
            notes.append(f"{len(r['cascade_blocks'])} occupancy miss")
        if r["n_eng_only_ge2019"]:
            notes.append(f"{r['n_eng_only_ge2019']} eng-only≥2019")
        if r["closed_new_pre2019_n"]:
            notes.append(f"UNEXPECTED pre2019 closed={r['closed_new_pre2019_n']}")
        note = "; ".join(notes) if notes else "—"
        lines.append(
            f"| {r['symbol']} | {fair['pivots_match']} / {fair['zones_ok']} / {fair['retest_ok']} | "
            f"{fair['rocket_where_sheet_fires']} | {r['n_eng_only_ge2019']} | "
            f"**{r['raw']}** | **{r['ser']}** | {r['ser_gb_ge2019']} | {r['closed_new_n']} | {note} |"
        )
    lines.append("")
    lines.append("### Pre-2019 early-rocket class (does it disappear?)")
    lines.append("")
    lines.append(
        "| Ticker | Eng-only rockets with signal **<2019** (full sheet vs full eng structure) | "
        "Gatebleed closed **<2019** | This run closed **<2019** |"
    )
    lines.append("|---|---:|---:|---:|")
    for r in results:
        lines.append(
            f"| {r['symbol']} | {r['n_eng_only_pre2019']} | "
            f"{r['closed_gb_pre2019_n']} | **{r['closed_new_pre2019_n']}** |"
        )
    lines.append("")
    lines.append(
        "**Verdict on occupancy/trade list:** Yes — with `start_date=2019-01-01`, "
        "engine **closed/open trades have no pre-2019 entries**, so the early-rocket "
        "occupancy path that dominated the 2016-start gatebleed deep-dives "
        "(first eng-only ser fills in 2016–2018) **cannot appear in the serialized trade list**."
    )
    lines.append("")
    lines.append(
        "**Verdict on weekly structure:** `start_date` maps to `entry_start_date` only — "
        "warmup/history still loads, so `compute_wpbr_touch_stream` / zone dumps still "
        "contain pre-2019 pivots, BOs, retests, and **raw signal/fill bars**. "
        "Those are not sheet rockets (sheet blanks via its 1/1/2019 rocket gate) and are "
        "not serialized as trades under this run. Optional compare that mirrors the sheet "
        "gate (`suppress eng signal <2019`) is reported per ticker as `rocket_gate_mirror`."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Per-ticker detail")
    lines.append("")
    for r in results:
        fair = r["fair"]
        gate = r["fair_gate_mirror"]
        lines.append(f"### {r['symbol']}")
        lines.append("")
        lines.append(
            f"- Sheet zones: {r['n_sheet_zones_all']} total → **{r['n_sheet_zones_ge2019']}** ≥2019"
        )
        lines.append(
            f"- Structure ≥2019: pivots **{fair['pivots_match']}**, zones **{fair['zones_ok']}**, "
            f"retest **{fair['retest_ok']}**, rocket-where-sheet-fires **{fair['rocket_where_sheet_fires']}**"
        )
        lines.append(
            f"- Rocket match if eng signals <2019 blanked (sheet-gate mirror): "
            f"**{gate['rocket_where_sheet_fires']}** eng-only≥2019-after-mirror={gate['n_eng_only_rockets']}"
        )
        lines.append(
            f"- Trades ≥2019: sheet **{r['n_sheet_trades_ge2019']}** "
            f"(all-paste {r['n_sheet_trades_all']}) → raw **{r['raw']}**, ser **{r['ser']}** "
            f"(gatebleed ≥2019 ser {r['ser_gb_ge2019']})"
        )
        lines.append(
            f"- Engine closed+open this stamp: **{r['closed_new_n']}** "
            f"(pre-2019: **{r['closed_new_pre2019_n']}**); "
            f"gatebleed closed+open: {r['closed_gb_n']} (pre-2019: {r['closed_gb_pre2019_n']})"
        )
        fe = r["first_eng_only_ser"]
        if fe:
            lines.append(
                f"- First eng-only serialized fill (≥2019 run): `{fe.get('entry')}` "
                f"exit `{fe.get('exit')}` pivot `{fe.get('pivot')}` — {fe.get('reason')}"
            )
        else:
            lines.append("- First eng-only serialized fill: _none_")
        if r["cascade_blocks"]:
            lines.append(f"- Occupancy-blocked sheet∩raw: {len(r['cascade_blocks'])}")
            for b in r["cascade_blocks"][:8]:
                lines.append(
                    f"  - sheet `{b['sheet_entry']}` blocked by `{b['occupied_by']}` "
                    f"(exit `{b['occ_exit']}`)"
                )
        if r["orphans"]:
            lines.append(f"- Orphans (not in engine raw ≥2019): {len(r['orphans'])}")
            for o in r["orphans"][:8]:
                lines.append(f"  - `{o['entry']}` near_rocket={o['near_rocket']}")
        if r["eng_only_ge2019"]:
            lines.append("- Eng-only rockets (sheet blank, eng signal ≥2019), sample:")
            for er in r["eng_only_ge2019"][:6]:
                lines.append(
                    f"  - pivot `{er['pivot']}` signal `{er['eng_signal']}` fill `{er['eng_fill']}`"
                )
        lines.append("")
        lines.append("| Entry ≥2019 | Raw | Ser |")
        lines.append("|---|---|---|")
        for t in r["trade_rows"]:
            lines.append(
                f"| `{t['entry']}` | {'YES' if t['raw'] else 'no'} | {'YES' if t['ser'] else 'no'} |"
            )
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## MarkTen coverage gap (needs user sheet copy/paste)")
    lines.append("")
    lines.append("| Symbol | Paste folder | zones.tsv / trades.tsv |")
    lines.append("|---|---|---|")
    for s in MARKTEN:
        d = BASE / s
        has_z = (d / "zones.tsv").is_file() or (d / "sheet_zones.tsv").is_file()
        has_t = (d / "trades.tsv").is_file() or (d / "sheet_trades.tsv").is_file()
        status = "OK" if (has_z and has_t) else ("PARTIAL" if (has_z or has_t) else "**MISSING — paste needed**")
        folder = f"`{s}/`" if d.is_dir() else "_no folder_"
        lines.append(f"| {s} | {folder} | {status} |")
    lines.append("")
    if missing:
        lines.append(
            f"**User still needs to copy/paste:** {', '.join(missing)} "
            f"(under `drive/wpbr_sheet_reconcile/<TICKER>/` as `zones.tsv` + `trades.tsv`)."
        )
    else:
        lines.append("All MarkTen symbols have sheet pastes.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Sheet 1/1/2019 rocket gate vs ACCEPT_ENGINE")
    lines.append("")
    lines.append(
        "The Google Sheet blanks **Rocket Buy** unless the date is after **1/1/2019**. "
        "That is an intentional armed-set / display gate, not a geometry disagreement."
    )
    lines.append("")
    lines.append(
        "Prior gatebleed work (`EARLY_ROCKET_CASCADE.md`) recommended **ACCEPT_ENGINE**: "
        "pre-2019 eng-only rockets exist, but after gate-bleed they do **not** block "
        "sheet∩raw fills (they exit before the sheet trade window). That policy is about "
        "keeping valid WPBR setups the sheet never armed."
    )
    lines.append("")
    lines.append(
        "Running the engine with `start_date=2019-01-01` aligns the **trade ledger** with "
        "the sheet’s rocket gate (no pre-2019 serialized fills). It does **not** erase "
        "pre-2019 weekly structure in history. Product choice:"
    )
    lines.append("")
    lines.append(
        "| Mode | Effect |"
    )
    lines.append("|---|---|")
    lines.append(
        "| Sheet gate only (engine from 2016) | Eng can still fire/fill pre-2019; ACCEPT_ENGINE "
        "keeps those; sheet shows blanks |"
    )
    lines.append(
        "| Engine `start_date=2019-01-01` (this run) | No pre-2019 entries in closed/open; "
        "early-rocket occupancy diffs vanish from the trade list; structure history remains |"
    )
    lines.append("")
    lines.append(
        "No pivot HALF_UP change in this pass (optional; see `PIVOT_ROUND_ANALYSIS.md` if needed)."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Artifacts")
    lines.append("")
    lines.append(f"- Engine: `drive/wpbr_sheet_reconcile/_markten_start2019_20260722125713/` (`{STAMP}`)")
    lines.append("- This summary: `drive/wpbr_sheet_reconcile/START_2019_RECONCILE_SUMMARY.md`")
    lines.append("- Reconcile script: `tools/_start2019_wpbr_reconcile.py`")
    lines.append("- Payload JSON: `drive/wpbr_sheet_reconcile/_start2019_reconcile_payload.json`")
    lines.append("")

    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def main() -> int:
    missing = [s for s in MARKTEN if not has_paste(s)]
    print("MarkTen missing pastes:", missing or "(none)")
    results = []
    for sym in PASTED:
        if not has_paste(sym):
            print(f"SKIP {sym}: no paste")
            continue
        print(f"=== {sym} ===")
        r = analyze(sym)
        results.append(r)
        print(
            f"  fair piv/zone/retest {r['fair']['pivots_match']} / {r['fair']['zones_ok']} / {r['fair']['retest_ok']} "
            f"rocket_sheet {r['fair']['rocket_where_sheet_fires']} "
            f"raw {r['raw']} ser {r['ser']} "
            f"eng_only_pre2019={r['n_eng_only_pre2019']} ge2019={r['n_eng_only_ge2019']} "
            f"closed_pre={r['closed_new_pre2019_n']}"
        )

    payload = {
        "stamp": STAMP,
        "stamp_dir": str(STAMP_DIR),
        "min_date": MIN_DATE,
        "missing_pastes": missing,
        "results": results,
    }
    payload_path = BASE / "_start2019_reconcile_payload.json"
    # trim bulky lists for JSON
    slim = []
    for r in results:
        slim.append(
            {
                k: v
                for k, v in r.items()
                if k
                not in {
                    "eng_only_pre2019",
                    "eng_only_ge2019",
                    "trade_rows",
                    "blocked",
                    "fair",
                    "fair_gate_mirror",
                    "full",
                }
                or k
                in {
                    "fair",
                    "fair_gate_mirror",
                    "full",
                    "eng_only_pre2019",
                    "eng_only_ge2019",
                    "trade_rows",
                    "blocked",
                    "cascade_blocks",
                    "orphans",
                    "first_eng_only_ser",
                }
            }
        )
        # keep fair/full without huge rocket lists for size
        for key in ("fair", "fair_gate_mirror", "full"):
            if key in slim[-1] and isinstance(slim[-1][key], dict):
                d = dict(slim[-1][key])
                d["eng_only_rockets"] = d.get("eng_only_rockets", [])[:20]
                slim[-1][key] = d
    payload["results"] = slim
    payload_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    summary = write_summary(results, missing)
    print(f"wrote {summary}")
    print(f"wrote {payload_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
