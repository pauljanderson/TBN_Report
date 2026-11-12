#!/usr/bin/env python3
"""Early-rocket cascade + sheet/engine reconcile for WPBR pastes (post gate-bleed).

Stamp: _markten_gatebleed_20260722113454 / 260722113454
Skips AMD/GOOGL structural redo (sibling results folded into summary).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(REPO / "stock_analysis"))
from wpbr_zones import compute_wpbr_touch_stream  # noqa: E402

STAMP_DIR = REPO / "drive" / "wpbr_sheet_reconcile" / "_markten_gatebleed_20260722113454"
STAMP = "260722113454"
OLD_STAMP_DIR = REPO / "drive" / "wpbr_sheet_reconcile" / "_markten_retest_2016"
OLD_STAMP = "260722105625"
BASE = REPO / "drive" / "wpbr_sheet_reconcile"
DATA = REPO / "data" / "newdata" / "data"
MIN_DATE = "2016-01-01"

# Analyze these; AMD/GOOGL numbers from sibling folded later in summary writer.
ANALYZE = ["META", "NVDA", "NFLX", "AMZN", "TSLA", "AAPL", "MSFT"]


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


def load_sheet_zones(sym: Path) -> list[dict]:
    for name in ("zones.tsv", "sheet_zones.tsv"):
        p = sym / name
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


def load_sheet_trades(sym: Path) -> list[dict]:
    for name in ("trades.tsv", "sheet_trades.tsv"):
        p = sym / name
        if p.is_file():
            break
    else:
        return []
    lines = read_text_any(p).splitlines()
    # skip title row if present (symbol alone) and header
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
    # Still-open positions count as serialized fills
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


def analyze(sym: str) -> dict:
    out_dir = BASE / sym
    df = pd.read_csv(DATA / f"{sym}.csv", index_col=0, parse_dates=True)
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
        if not piv or piv < MIN_DATE:
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

    sheet_z = load_sheet_zones(out_dir)
    sheet_t = load_sheet_trades(out_dir)
    closed_new = load_closed(STAMP_DIR, STAMP, sym)
    closed_old = load_closed(OLD_STAMP_DIR, OLD_STAMP, sym) if (OLD_STAMP_DIR / f"WPBR_Closed_{OLD_STAMP}.csv").is_file() else []

    # pivot match
    sheet_pivs = {z["pivot"] for z in sheet_z}
    eng_pivs = set(eng)
    piv_match = len(sheet_pivs & eng_pivs)

    zone_ok = retest_ok = rocket_ok = rocket_where_sheet = 0
    rocket_sheet_fires = 0
    eng_only_rockets = []
    sheet_only_rockets = []
    retest_diffs = []
    for z in sheet_z:
        e = eng.get(z["pivot"])
        if not e:
            continue
        zl_ok = z["zlow"] is not None and abs(z["zlow"] - e["zlow"]) <= 0.02
        zh_ok = z["zhigh"] is not None and abs(z["zhigh"] - e["zhigh"]) <= 0.02
        bo_ok = z["bo"] == e["bo"]
        if zl_ok and zh_ok and bo_ok:
            zone_ok += 1
        if z["retest"] == e["retest"]:
            retest_ok += 1
        else:
            retest_diffs.append({"pivot": z["pivot"], "sheet": z["retest"], "eng": e["retest"]})
        if z["rocket"]:
            rocket_sheet_fires += 1
            if z["rocket"] == e["signal"]:
                rocket_where_sheet += 1
                rocket_ok += 1
            else:
                sheet_only_rockets.append({"pivot": z["pivot"], "sheet": z["rocket"], "eng": e["signal"]})
        else:
            if e["signal"]:
                eng_only_rockets.append(
                    {
                        "pivot": z["pivot"],
                        "sheet_rocket": None,
                        "eng_signal": e["signal"],
                        "eng_fill": e["fill"],
                        "zone_id": e["zone_id"],
                        "zlow": e["zlow"],
                        "zhigh": e["zhigh"],
                    }
                )
            else:
                rocket_ok += 1  # both blank

    # also pivots engine has that sheet doesn't — skip for rocket table
    n_pairs = len([z for z in sheet_z if z["pivot"] in eng])

    raw_fills = {e["fill"] for e in eng.values() if e["fill"] and e["fill"] >= MIN_DATE}
    # Also include fills from opportunities that may map to same dates
    for opp in stream.get("wpbr_entry_opportunities") or []:
        fb = opp.get("entry_fill_bar")
        fd = bar_to_date(idx, fb)
        if fd and fd >= MIN_DATE:
            raw_fills.add(fd)

    ser_new = {t["entry"] for t in closed_new}
    ser_old = {t["entry"] for t in closed_old}

    sheet_raw = []
    sheet_ser_new = []
    sheet_ser_old = []
    orphans = []
    trade_rows = []
    for t in sheet_t:
        in_raw = t["entry"] in raw_fills
        in_ser = t["entry"] in ser_new
        in_old = t["entry"] in ser_old
        sheet_raw.append(in_raw)
        sheet_ser_new.append(in_ser)
        sheet_ser_old.append(in_old)
        trade_rows.append({**t, "raw": in_raw, "ser_old": in_old, "ser_new": in_ser})
        if not in_raw:
            near_rocket = False
            for z in sheet_z:
                if not z["rocket"]:
                    continue
                d0 = pd.Timestamp(z["rocket"])
                d1 = pd.Timestamp(t["entry"])
                if abs((d1 - d0).days) <= 5:
                    near_rocket = True
                    break
            orphans.append({**t, "near_rocket": near_rocket})

    # Cascade walk: first engine-only serialized fill where sheet rocket blank on that zone
    # Build map fill -> zone rocket sheet status
    fill_to_zone = {}
    for e in eng.values():
        if e["fill"]:
            fill_to_zone[e["fill"]] = e
    sheet_rocket_by_pivot = {z["pivot"]: z["rocket"] for z in sheet_z}

    first_eng_only_ser = None
    for tr in closed_new:
        e = fill_to_zone.get(tr["entry"])
        # find zone with this fill
        matched_zone = None
        for piv, ez in eng.items():
            if ez["fill"] == tr["entry"]:
                matched_zone = (piv, ez)
                break
        if not matched_zone:
            # still engine-only if sheet has no rocket leading to this entry
            sheet_has = any(
                z["rocket"] and abs((pd.Timestamp(tr["entry"]) - pd.Timestamp(z["rocket"])).days) <= 5
                for z in sheet_z
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
            continue
        piv, ez = matched_zone
        sheet_r = sheet_rocket_by_pivot.get(piv)
        if not sheet_r:
            first_eng_only_ser = {
                "entry": tr["entry"],
                "exit": tr["exit"],
                "pivot": piv,
                "eng_signal": ez["signal"],
                "zone_id": ez["zone_id"],
                "reason": "sheet rocket blank on zone that engine filled",
            }
            break
        # sheet rocket later than engine signal?
        if sheet_r and ez["signal"] and sheet_r > ez["signal"]:
            first_eng_only_ser = {
                "entry": tr["entry"],
                "exit": tr["exit"],
                "pivot": piv,
                "eng_signal": ez["signal"],
                "sheet_rocket": sheet_r,
                "zone_id": ez["zone_id"],
                "reason": "engine signal earlier than sheet rocket",
            }
            break

    # Occupancy walk: which sheet trades blocked by first eng-only (and subsequent eng path)
    blocked = []
    if first_eng_only_ser and first_eng_only_ser.get("entry"):
        # Replay: engine takes closed_new in order; for each sheet trade that is raw but not ser,
        # see if any prior eng-only or any open window covers it
        for t in sheet_t:
            if t["entry"] in ser_new:
                continue
            if t["entry"] not in raw_fills:
                continue  # orphan / not cascade
            # find occupying trade
            occ = None
            for tr in closed_new:
                if tr["entry"] < t["entry"] <= (tr["exit"] or "9999"):
                    occ = tr
                    break
                # also: prior eng fill that diverted path — if first eng-only precedes and
                # something else occupies
            if occ:
                # is occupying trade sheet-matching?
                occ_is_sheet = occ["entry"] in {x["entry"] for x in sheet_t}
                if not occ_is_sheet or occ["entry"] == first_eng_only_ser["entry"]:
                    blocked.append(
                        {
                            "sheet_entry": t["entry"],
                            "occupied_by": occ["entry"],
                            "occ_exit": occ["exit"],
                            "occ_is_sheet": occ_is_sheet,
                        }
                    )
            else:
                # free slot but not serialized — unexpected post gate-bleed
                blocked.append(
                    {
                        "sheet_entry": t["entry"],
                        "occupied_by": None,
                        "occ_exit": None,
                        "occ_is_sheet": None,
                        "note": "free_slot_miss_post_gatebleed",
                    }
                )

    # Verdict heuristic
    n_ser = sum(sheet_ser_new)
    n_raw = sum(sheet_raw)
    n_sheet = len(sheet_t)
    cascade_blocks = [b for b in blocked if b.get("occupied_by")]
    free_misses = [b for b in blocked if not b.get("occupied_by")]
    if n_raw and n_ser == n_raw and not cascade_blocks:
        verdict = "ACCEPT_ENGINE"  # gate-bleed fixed; no cascade damage among raw-matched
        verdict_note = "All sheet∩raw fills serialize; early eng rockets did not block sheet raw set."
    elif cascade_blocks and first_eng_only_ser:
        # Did early rocket cause blocks?
        first_e = first_eng_only_ser["entry"]
        caused = [b for b in cascade_blocks if b["occupied_by"] and b["occupied_by"] >= first_e]
        if caused:
            verdict = "TIGHTEN_CANDIDATE"
            verdict_note = (
                f"First eng-only fill {first_e} precedes occupancy blocks of "
                f"{len(caused)} sheet raw fill(s)."
            )
        else:
            verdict = "MIXED"
            verdict_note = "Blocks exist but not clearly from first eng-only rocket."
    elif free_misses:
        verdict = "INVESTIGATE"
        verdict_note = f"{len(free_misses)} free-slot misses remain post gate-bleed."
    else:
        verdict = "ACCEPT_ENGINE"
        verdict_note = "Residuals are orphans / non-raw sheet rows, not cascade."

    result = {
        "symbol": sym,
        "stamp": STAMP,
        "n_sheet_zones": len(sheet_z),
        "n_eng_zones_ge2016": len(eng),
        "pivots_match": f"{piv_match}/{len(sheet_z)}",
        "zones_ok": f"{zone_ok}/{n_pairs}",
        "retest_ok": f"{retest_ok}/{n_pairs}",
        "rocket_ok_pairs": f"{rocket_ok}/{n_pairs}",
        "rocket_where_sheet_fires": f"{rocket_where_sheet}/{rocket_sheet_fires}",
        "eng_only_rockets": eng_only_rockets,
        "n_eng_only_rockets": len(eng_only_rockets),
        "retest_diffs": retest_diffs,
        "n_sheet_trades": n_sheet,
        "raw": f"{n_raw}/{n_sheet}",
        "ser_old": f"{sum(sheet_ser_old)}/{n_sheet}",
        "ser_new": f"{n_ser}/{n_sheet}",
        "orphans": orphans,
        "closed_new": closed_new,
        "closed_old_n": len(closed_old),
        "first_eng_only_ser": first_eng_only_ser,
        "blocked": blocked,
        "cascade_blocks": cascade_blocks,
        "verdict": verdict,
        "verdict_note": verdict_note,
        "sheet_trades": sheet_t,
        "trade_rows": trade_rows,
        "raw_fills_n": len(raw_fills),
    }
    return result


def write_ticker_status(r: dict) -> None:
    sym = r["symbol"]
    out = BASE / sym / f"{sym}_wpbr_reconcile_status.md"
    lines = []
    lines.append(f"# {sym} WPBR Sheet ↔ Engine Reconcile (post gate-bleed)")
    lines.append("")
    lines.append(f"**Engine stamp:** `{r['stamp']}` — `drive/wpbr_sheet_reconcile/_markten_gatebleed_20260722113454/`")
    lines.append(f"**Settings:** `retest_mode=stop_looking`, `start_date=2016-01-01`, `target_pct=1.22`, `stop_pct=0.89`.")
    lines.append(f"**Compare-to:** old MarkTen `{OLD_STAMP}` (pre gate-bleed).")
    lines.append("")
    lines.append("## Structure")
    lines.append("")
    lines.append("| Check | Result |")
    lines.append("|---|---|")
    lines.append(f"| Sheet zones | **{r['n_sheet_zones']}** |")
    lines.append(f"| Pivots match | **{r['pivots_match']}** |")
    lines.append(f"| Zones (bounds+BO) | **{r['zones_ok']}** |")
    lines.append(f"| Retest | **{r['retest_ok']}** |")
    lines.append(f"| Rocket (all pairs) | **{r['rocket_ok_pairs']}** |")
    lines.append(f"| Rocket where sheet fires | **{r['rocket_where_sheet_fires']}** |")
    lines.append(f"| Eng-only rockets (sheet blank) | **{r['n_eng_only_rockets']}** |")
    lines.append("")
    lines.append("## Trades")
    lines.append("")
    lines.append("| Metric | Result |")
    lines.append("|---|---|")
    lines.append(f"| Sheet closed | **{r['n_sheet_trades']}** |")
    lines.append(f"| Raw fills | **{r['raw']}** |")
    lines.append(f"| Serialized old `{OLD_STAMP}` | **{r['ser_old']}** |")
    lines.append(f"| Serialized post gate-bleed | **{r['ser_new']}** |")
    lines.append(f"| Engine closed (new) | **{len(r['closed_new'])}** |")
    lines.append("")
    lines.append("## Early-rocket cascade")
    lines.append("")
    fe = r["first_eng_only_ser"]
    if fe:
        lines.append(f"- **First eng-only serialized fill:** `{fe.get('entry')}` → exit `{fe.get('exit')}`")
        lines.append(f"- Pivot: `{fe.get('pivot')}` — {fe.get('reason')}")
    else:
        lines.append("- No eng-only serialized fill found (all serialized fills have sheet rockets within ±5d / same zone).")
    lines.append(f"- **Occupancy-blocked sheet raw fills:** {len(r['cascade_blocks'])}")
    for b in r["cascade_blocks"][:12]:
        lines.append(
            f"  - sheet `{b['sheet_entry']}` blocked by eng `{b['occupied_by']}` "
            f"(exit `{b['occ_exit']}`, sheet_match={b['occ_is_sheet']})"
        )
    free = [b for b in r["blocked"] if not b.get("occupied_by")]
    if free:
        lines.append(f"- **Free-slot misses (unexpected):** {len(free)}")
        for b in free[:8]:
            lines.append(f"  - `{b['sheet_entry']}`")
    if r["orphans"]:
        lines.append(f"- **Sheet orphans (not in engine raw):** {len(r['orphans'])}")
        for o in r["orphans"]:
            lines.append(f"  - `{o['entry']}` near_rocket={o['near_rocket']}")
    if r["eng_only_rockets"]:
        lines.append("")
        lines.append("### Eng-only rockets (sheet blank)")
        for er in r["eng_only_rockets"][:15]:
            lines.append(
                f"- pivot `{er['pivot']}` signal `{er['eng_signal']}` fill `{er['eng_fill']}` "
                f"z=({er['zlow']},{er['zhigh']})"
            )
    lines.append("")
    lines.append(f"**Verdict:** `{r['verdict']}` — {r['verdict_note']}")
    lines.append("")
    lines.append("## Sheet trades vs engine")
    lines.append("")
    lines.append("| Entry | Raw | Ser old | Ser new |")
    lines.append("|---|---|---|---|")
    for t in r.get("trade_rows") or []:
        lines.append(
            f"| `{t['entry']}` | {'YES' if t['raw'] else 'no'} | "
            f"{'YES' if t['ser_old'] else 'no'} | {'YES' if t['ser_new'] else 'no'} |"
        )

    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out}")


def main():
    # extract AAPL if needed
    aapl_z = BASE / "AAPL" / "zones.tsv"
    if not aapl_z.is_file():
        print("AAPL paste missing — run _aapl_extract_paste.py first")

    results = []
    for sym in ANALYZE:
        z = BASE / sym / "zones.tsv"
        if not z.is_file() and not (BASE / sym / "sheet_zones.tsv").is_file():
            print(f"SKIP {sym}: no zones paste")
            continue
        print(f"=== {sym} ===")
        r = analyze(sym)
        results.append(r)
        write_ticker_status(r)
        # per-ticker cascade deepdive short
        dd = BASE / sym / f"{sym}_cascade_deepdive.md"
        fe = r["first_eng_only_ser"]
        bl = r["cascade_blocks"]
        dd_lines = [
            f"# {sym} early-rocket cascade (stamp `{STAMP}`)",
            "",
            f"**Verdict:** `{r['verdict']}` — {r['verdict_note']}",
            "",
            f"- Eng-only rockets (sheet blank): **{r['n_eng_only_rockets']}**",
            f"- Raw: **{r['raw']}** | Ser old: **{r['ser_old']}** | Ser new: **{r['ser_new']}**",
            "",
            "## First engine-only serialized fill",
            "",
        ]
        if fe:
            dd_lines += [
                f"| Field | Value |",
                f"|---|---|",
                f"| Entry | `{fe.get('entry')}` |",
                f"| Exit | `{fe.get('exit')}` |",
                f"| Pivot | `{fe.get('pivot')}` |",
                f"| Reason | {fe.get('reason')} |",
                "",
            ]
        else:
            dd_lines.append("_None._")
            dd_lines.append("")
        dd_lines += ["## Occupancy → blocked sheet raw fills", ""]
        if not bl:
            dd_lines.append("_None among sheet∩raw._")
        else:
            dd_lines.append("| Sheet entry | Occupied by | Occ exit | Occ is sheet? |")
            dd_lines.append("|---|---|---|---|")
            for b in bl:
                dd_lines.append(
                    f"| `{b['sheet_entry']}` | `{b['occupied_by']}` | `{b['occ_exit']}` | {b['occ_is_sheet']} |"
                )
        dd_lines += ["", "## Engine serialized timeline", ""]
        dd_lines.append("| # | Entry → Exit | Sheet match? |")
        dd_lines.append("|---|---|---|")
        sheet_entries = {t["entry"] for t in r["sheet_trades"]}
        for i, tr in enumerate(r["closed_new"], 1):
            m = "MATCH" if tr["entry"] in sheet_entries else "engine-only"
            dd_lines.append(f"| E{i} | `{tr['entry']}` → `{tr['exit']}` | {m} |")
        dd.write_text("\n".join(dd_lines), encoding="utf-8")
        print(f"wrote {dd}")
        print(
            f"  piv={r['pivots_match']} retest={r['retest_ok']} rocket_sheet={r['rocket_where_sheet_fires']} "
            f"raw={r['raw']} ser={r['ser_old']}->{r['ser_new']} verdict={r['verdict']}"
        )

    payload = BASE / "_cascade_payload_gatebleed.json"
    # compact json
    compact = []
    for r in results:
        compact.append(
            {
                k: r[k]
                for k in [
                    "symbol",
                    "stamp",
                    "pivots_match",
                    "zones_ok",
                    "retest_ok",
                    "rocket_where_sheet_fires",
                    "n_eng_only_rockets",
                    "raw",
                    "ser_old",
                    "ser_new",
                    "verdict",
                    "verdict_note",
                    "first_eng_only_ser",
                    "cascade_blocks",
                    "orphans",
                    "eng_only_rockets",
                    "n_sheet_trades",
                    "closed_old_n",
                ]
                if k in r
            }
        )
    payload.write_text(json.dumps(compact, indent=2, default=str), encoding="utf-8")
    print(f"wrote {payload}")


if __name__ == "__main__":
    main()
