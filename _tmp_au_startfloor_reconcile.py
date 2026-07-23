"""AU-only reconcile vs startfloor stamp 260722161242."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(REPO / "stock_analysis"))
from wpbr_zones import compute_wpbr_touch_stream, _round_bounds  # noqa: E402

STAMP = "260722161242"
STAMP_DIR = (
    REPO
    / "drive"
    / "wpbr_sheet_reconcile"
    / "_markten_variantC_SC_stop91_startfloor_2016_20260722161052"
)
BASE = REPO / "drive" / "wpbr_sheet_reconcile"
DATA = REPO / "data" / "newdata" / "data"
MIN_DATE = "2016-01-01"
SYM = "AU"
FOCUS_GONE = "2016-02-11"


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


def parse_entry(s):
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


def load_sheet_zones(sym_dir: Path):
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


def load_sheet_trades(sym_dir: Path):
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
                "pnl_pct": nf(c[4]) if len(c) > 4 else None,
                "days": nf(c[5]) if len(c) > 5 else None,
                "pnl_dol": nf(c[7]) if len(c) > 7 else None,
            }
        )
    return trades


def stacked_block(label: str, rows: list[dict], pct_key="pnl_pct", days_key="days", dol_key="pnl_dol"):
    n = len(rows)
    pcts = [r[pct_key] for r in rows if r.get(pct_key) is not None]
    wins = [p for p in pcts if p > 0]
    losses = [p for p in pcts if p < 0]
    wr = 100.0 * len(wins) / n if n else 0.0
    avg = sum(pcts) / len(pcts) if pcts else 0.0
    aw = sum(wins) / len(wins) if wins else 0.0
    al = sum(losses) / len(losses) if losses else 0.0
    if losses and aw:
        wl = aw / abs(al)
    elif wins:
        wl = float("inf")
    else:
        wl = 0.0
    days = [r[days_key] for r in rows if r.get(days_key) is not None]
    avgd = sum(days) / len(days) if days else float("nan")
    dol = sum(r[dol_key] for r in rows if r.get(dol_key) is not None)
    wl_s = f"{wl:.2f}" if wl != float("inf") else "inf"
    return {
        "label": label,
        "n": n,
        "wr": wr,
        "avg": avg,
        "wl": wl,
        "avgd": avgd,
        "dol": dol,
        "line": f"{n}\n{wr:.1f}%\n{avg:.1f}%\n{wl_s}\n{avgd:.1f}\n${dol:,.2f}",
        "one": f"{n} → {wr:.1f}% → {avg:.1f}% → {wl_s} → {avgd:.1f} → ${dol:,.2f}",
    }


def main():
    out_dir = BASE / SYM
    df = pd.read_csv(DATA / f"{SYM}.csv", index_col=0, parse_dates=True)
    idx = pd.DatetimeIndex(df.index)

    # closed
    closed_df = pd.read_csv(STAMP_DIR / f"WPBR_Closed_{STAMP}.csv")
    cdf = closed_df[closed_df["SYMBOL"].astype(str).str.upper() == SYM].copy()
    print("closed cols ok; AU rows:", len(cdf))
    print("AU symbols unique:", closed_df["SYMBOL"].astype(str).str.upper().unique().tolist())

    closed = []
    for _, r in cdf.iterrows():
        closed.append(
            {
                "entry": parse_entry(r["DATE_OPENED"]),
                "exit": parse_entry(r.get("DATE_CLOSED")),
                "entry_px": nf(r["ENTRY_PRICE"]),
                "exit_px": nf(r["EXIT_PRICE"]),
                "exit_type": str(r.get("EXIT_TYPE") or ""),
                "pnl_pct": nf(r["PNL_PCT"]),
                "days": nf(r["DAYS_HELD"]),
                "pnl_dol": nf(r["PNL_DOLLARS"]),
                "zone_id": str(r.get("WPBR_ZONE_ID") or ""),
                "open": False,
            }
        )
    op = STAMP_DIR / f"WPBR_Open_{STAMP}.csv"
    if op.is_file():
        odf = pd.read_csv(op)
        if "SYMBOL" in odf.columns:
            odf = odf[odf["SYMBOL"].astype(str).str.upper() == SYM]
            for _, r in odf.iterrows():
                closed.append(
                    {
                        "entry": parse_entry(r["DATE_OPENED"]),
                        "exit": None,
                        "entry_px": nf(r["ENTRY_PRICE"]),
                        "exit_px": None,
                        "exit_type": "OPEN",
                        "pnl_pct": None,
                        "days": None,
                        "pnl_dol": None,
                        "zone_id": str(r.get("WPBR_ZONE_ID") or ""),
                        "open": True,
                    }
                )
    closed.sort(key=lambda x: x["entry"] or "")

    # raw fills from touch stream (structure)
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
            "retest": bar_to_date(idx, ev.get("retest_bar")),
            "signal": bar_to_date(idx, ev.get("entry_signal_bar")),
            "fill": bar_to_date(idx, ev.get("entry_fill_bar")),
        }
    raw_fills = {e["fill"] for e in eng.values() if e["fill"]}
    for opp in stream.get("wpbr_entry_opportunities") or []:
        fd = bar_to_date(idx, opp.get("entry_fill_bar"))
        if fd:
            raw_fills.add(fd)
    raw_fills = {f for f in raw_fills if f and f >= MIN_DATE}
    eng = {p: e for p, e in eng.items() if p >= MIN_DATE}

    sheet_z = [z for z in load_sheet_zones(out_dir) if z["pivot"] and z["pivot"] >= MIN_DATE]
    sheet_t = [t for t in load_sheet_trades(out_dir) if t["entry"] and t["entry"] >= MIN_DATE]

    # structure
    zone_ok = retest_ok = rocket_ok = rocket_where_sheet = 0
    rocket_sheet_fires = 0
    eng_only_rockets = []
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
                {"pivot": z["pivot"], "sheet_retest": z["retest"], "eng_retest": e["retest"]}
            )
        if z["rocket"]:
            rocket_sheet_fires += 1
            if z["rocket"] == e["signal"]:
                rocket_where_sheet += 1
                rocket_ok += 1
        else:
            if e["signal"]:
                eng_only_rockets.append(
                    {"pivot": z["pivot"], "eng_signal": e["signal"], "eng_fill": e["fill"]}
                )
            else:
                rocket_ok += 1
    sheet_pivs = {z["pivot"] for z in sheet_z}
    pivots_match = f"{len(sheet_pivs & set(eng))}/{len(sheet_z)}"

    ser = {t["entry"] for t in closed if t["entry"]}
    sheet_entries = {t["entry"] for t in sheet_t}
    n_raw = sum(1 for t in sheet_t if t["entry"] in raw_fills)
    n_ser = sum(1 for t in sheet_t if t["entry"] in ser)
    raw_orphans = [t["entry"] for t in sheet_t if t["entry"] not in raw_fills]
    ser_orphans = [t["entry"] for t in sheet_t if t["entry"] not in ser]
    sheet_only = sorted(sheet_entries - ser)
    eng_only = sorted(ser - sheet_entries)

    # forks on matched
    forks = []
    matched = []
    by_sheet = {t["entry"]: t for t in sheet_t}
    by_eng = {t["entry"]: t for t in closed if t["entry"]}
    for d in sorted(sheet_entries & ser):
        s = by_sheet[d]
        e = by_eng[d]
        issues = []
        if s["exit"] and e["exit"] and s["exit"] != e["exit"]:
            issues.append(f"exit_date sheet={s['exit']} eng={e['exit']}")
        if s["entry_px"] is not None and e["entry_px"] is not None:
            if abs(s["entry_px"] - e["entry_px"]) > 0.05:
                issues.append(f"entry_px sheet={s['entry_px']} eng={e['entry_px']}")
        if s["exit_px"] is not None and e["exit_px"] is not None:
            if abs(s["exit_px"] - e["exit_px"]) > 0.05:
                issues.append(f"exit_px sheet={s['exit_px']} eng={e['exit_px']}")
        matched.append(d)
        if issues:
            forks.append({"entry": d, "issues": issues})

    gone = FOCUS_GONE not in ser
    # also check zones entries fill bars for that date
    zent = STAMP_DIR / f"WPBR_ZONES_ENTRIES_{SYM}_{STAMP}.csv"
    zent_df = pd.read_csv(zent) if zent.is_file() else pd.DataFrame()
    fill_dates = []
    if not zent_df.empty:
        for _, r in zent_df.iterrows():
            # try common cols
            for c in ("ENTRY_FILL_DATE", "FILL_DATE", "DATE_OPENED", "ENTRY_DATE"):
                if c in zent_df.columns:
                    fill_dates.append(parse_entry(r[c]))
                    break
            else:
                # bar index
                if "ENTRY_FILL_BAR" in zent_df.columns:
                    fill_dates.append(bar_to_date(idx, r["ENTRY_FILL_BAR"]))

    sheet_stack = stacked_block("sheet", sheet_t)
    eng_closed_only = [t for t in closed if not t.get("open")]
    eng_stack = stacked_block("engine", eng_closed_only)

    payload = {
        "stamp": STAMP,
        "stamp_dir": str(STAMP_DIR),
        "pivots": pivots_match,
        "zones": f"{zone_ok}/{n_pairs}",
        "retest": f"{retest_ok}/{n_pairs}",
        "rocket_sheet_fires": f"{rocket_where_sheet}/{rocket_sheet_fires}",
        "raw": f"{n_raw}/{len(sheet_t)}",
        "ser": f"{n_ser}/{len(sheet_t)}",
        "closed_n": len(closed),
        "closed_closed_only": len(eng_closed_only),
        "sheet_n": len(sheet_t),
        "raw_orphans": raw_orphans,
        "ser_orphans": ser_orphans,
        "sheet_only": sheet_only,
        "eng_only": eng_only,
        "matched_n": len(matched),
        "forks": forks,
        "retest_mismatches": retest_mism[:20],
        "eng_only_rockets": eng_only_rockets[:15],
        "focus_2016_02_11_gone": gone,
        "focus_in_zone_entries": FOCUS_GONE in [d for d in fill_dates if d],
        "eng_entries": [t["entry"] for t in closed],
        "sheet_entries": [t["entry"] for t in sheet_t],
        "sheet_stack": sheet_stack,
        "eng_stack": eng_stack,
        "summary_row": None,
    }
    summ = STAMP_DIR / f"WPBR_Summary_{STAMP}.csv"
    if summ.is_file():
        sdf = pd.read_csv(summ)
        row = sdf[sdf["SYMBOL"].astype(str).str.upper() == SYM]
        if len(row):
            payload["summary_row"] = row.iloc[0].to_dict()

    out_json = BASE / SYM / "_au_startfloor_reconcile_payload.json"
    out_json.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: payload[k] for k in payload if k not in ("sheet_entries", "eng_entries")}, indent=2, default=str))
    print("wrote", out_json)
    print("FOCUS gone?", gone)
    print("ENG entries:", payload["eng_entries"])
    print("SHEET stack:", sheet_stack["one"])
    print("ENG stack:", eng_stack["one"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
