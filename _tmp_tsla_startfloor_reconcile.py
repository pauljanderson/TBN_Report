#!/usr/bin/env python3
"""TSLA-only reconcile vs startfloor+HALF_UP stamp 260722165827."""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path
from statistics import mean

import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(REPO / "stock_analysis"))
from wpbr_zones import compute_wpbr_touch_stream  # noqa: E402

STAMP_DIR = REPO / "drive/wpbr_sheet_reconcile/_markten_variantC_SC_stop91_startfloor_halfup_20260722165815"
STAMP = "260722165827"
PRIOR_DIR = REPO / "drive/wpbr_sheet_reconcile/_markten_variantC_SC_stop91_startfloor_2016_20260722161052"
PRIOR = "260722161242"
BASE = REPO / "drive/wpbr_sheet_reconcile/TSLA"
DATA = REPO / "data/newdata/data/TSLA.csv"
MIN_DATE = "2016-01-01"
SYM = "TSLA"


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


def read_text_any(p: Path) -> str:
    b = p.read_bytes()
    if b[:2] in (b"\xff\xfe", b"\xfe\xff") or (len(b) > 1 and b[1] == 0):
        for enc in ("utf-16", "utf-16-le"):
            try:
                return b.decode(enc)
            except Exception:
                pass
    return b.decode("utf-8", errors="ignore")


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


def load_sheet_zones():
    for name in ("zones.tsv", "sheet_zones.tsv"):
        p = BASE / name
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


def load_sheet_trades():
    for name in ("trades.tsv", "sheet_trades.tsv"):
        p = BASE / name
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
                "result": (c[6] if len(c) > 6 else "").strip(),
                "pnl_dol": nf(c[7]) if len(c) > 7 else None,
            }
        )
    return trades


def load_closed(stamp_dir, stamp):
    p = stamp_dir / f"WPBR_Closed_{stamp}.csv"
    df = pd.read_csv(p)
    df = df[df["SYMBOL"].astype(str).str.upper() == SYM].copy()
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
                "days": nf(r.get("DAYS_HELD")),
                "pnl_dol": nf(r.get("PNL_DOLLARS")),
                "zone_id": str(r.get("WPBR_ZONE_ID") or ""),
                "open": False,
            }
        )
    op = stamp_dir / f"WPBR_Open_{stamp}.csv"
    if op.is_file():
        odf = pd.read_csv(op)
        if "SYMBOL" in odf.columns:
            odf = odf[odf["SYMBOL"].astype(str).str.upper() == SYM]
            for _, r in odf.iterrows():
                out.append(
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
    out.sort(key=lambda x: x["entry"] or "")
    return out


def build_eng(df, min_pivot_date=None):
    idx = pd.DatetimeIndex(df.index)
    kwargs = dict(
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
    sig = inspect.signature(compute_wpbr_touch_stream)
    used_kw = False
    if min_pivot_date and "min_pivot_date" in sig.parameters:
        kwargs["min_pivot_date"] = min_pivot_date
        used_kw = True
    stream = compute_wpbr_touch_stream(df, **kwargs)
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
            "pivot_monday": piv,
        }
    raw_fills = {e["fill"] for e in eng.values() if e["fill"]}
    for opp in stream.get("wpbr_entry_opportunities") or []:
        fd = bar_to_date(idx, opp.get("entry_fill_bar"))
        if fd:
            raw_fills.add(fd)
    return eng, raw_fills, used_kw


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
        "sheet_only_pivots": sorted(sheet_pivs - set(eng)),
        "eng_only_pivots": sorted(set(eng) - sheet_pivs),
    }


def stacked(closed):
    rows = [t for t in closed if not t["open"] and t["pnl_pct"] is not None]
    n = len(rows)
    if n == 0:
        return {"n": 0}
    wins = [t for t in rows if t["pnl_pct"] > 0]
    losses = [t for t in rows if t["pnl_pct"] <= 0]
    win_pct = 100 * len(wins) / n
    avg_profit = mean(t["pnl_pct"] for t in rows)
    avg_win = mean(t["pnl_pct"] for t in wins) if wins else 0.0
    avg_loss_abs = abs(mean(t["pnl_pct"] for t in losses)) if losses else 0.0
    wl = (avg_win / avg_loss_abs) if avg_loss_abs else None
    avg_days = mean(t["days"] for t in rows if t["days"] is not None)
    pnl = sum(t["pnl_dol"] or 0 for t in rows)
    return {
        "n": n,
        "win_pct": win_pct,
        "avg_profit": avg_profit,
        "wl": wl,
        "avg_days": avg_days,
        "pnl": pnl,
        "n_wins": len(wins),
        "n_losses": len(losses),
    }


def load_zone_pivots(path):
    if not path.is_file():
        return []
    df = pd.read_csv(path)
    piv_col = None
    for c in df.columns:
        if "PIVOT" in c.upper() and "MON" in c.upper():
            piv_col = c
            break
    if piv_col is None:
        for c in df.columns:
            if c.upper() == "PIVOT_MONDAY":
                piv_col = c
                break
    out = []
    for _, r in df.iterrows():
        piv = nd(r[piv_col]) if piv_col else None
        zid = str(r.get("WPBR_ZONE_ID") or r.get("ZONE_ID") or "")
        out.append({"pivot": piv, "zone_id": zid})
    return out


def enrich_with_zone_csv(rows, stamp_dir, stamp):
    zp = stamp_dir / f"WPBR_ZONES_{SYM}_{stamp}.csv"
    if not zp.is_file():
        return [{**t, "pivot_monday": None} for t in rows]
    dfz = pd.read_csv(zp)
    id_col = None
    for c in dfz.columns:
        if c.upper() in ("WPBR_ZONE_ID", "ZONE_ID"):
            id_col = c
            break
    piv_col = None
    for c in dfz.columns:
        if "PIVOT" in c.upper() and "MON" in c.upper():
            piv_col = c
            break
    m = {}
    if id_col and piv_col:
        for _, r in dfz.iterrows():
            m[str(r[id_col])] = nd(r[piv_col])
    out = []
    for t in rows:
        piv = m.get(t["zone_id"])
        out.append({**t, "pivot_monday": piv})
    return out


def main() -> int:
    sheet_z_all = load_sheet_zones()
    sheet_z = [z for z in sheet_z_all if z["pivot"] and z["pivot"] >= MIN_DATE]
    sheet_t_all = load_sheet_trades()
    sheet_t = [t for t in sheet_t_all if t["entry"] and t["entry"] >= MIN_DATE]
    closed = load_closed(STAMP_DIR, STAMP)
    prior_closed = load_closed(PRIOR_DIR, PRIOR)

    df = pd.read_csv(DATA, index_col=0, parse_dates=True)
    eng_all, raw_all, used_kw = build_eng(df, min_pivot_date=MIN_DATE)
    eng = {p: e for p, e in eng_all.items() if p >= MIN_DATE}
    raw_fills = {f for f in raw_all if f and f >= MIN_DATE}
    fair = structure_stats(sheet_z, eng)

    ser = {t["entry"] for t in closed}
    sheet_entries = {t["entry"] for t in sheet_t}
    n_raw = sum(1 for t in sheet_t if t["entry"] in raw_fills)
    n_ser = sum(1 for t in sheet_t if t["entry"] in ser)
    raw_orphans = [t["entry"] for t in sheet_t if t["entry"] not in raw_fills]
    ser_orphans = [t["entry"] for t in sheet_t if t["entry"] not in ser]
    eng_only_entries = sorted(ser - sheet_entries)
    prior_eng_only = sorted({t["entry"] for t in prior_closed} - sheet_entries)
    cleared_vs_prior = sorted(
        {t["entry"] for t in prior_closed} - {t["entry"] for t in closed}
    )
    added_vs_prior = sorted(
        {t["entry"] for t in closed} - {t["entry"] for t in prior_closed}
    )

    sheet_by = {t["entry"]: t for t in sheet_t}
    forks = []
    matched = []
    for t in closed:
        if t["open"]:
            continue
        s = sheet_by.get(t["entry"])
        if not s:
            continue
        issues = []
        if s["exit"] and t["exit"] and s["exit"] != t["exit"]:
            issues.append(f"exit {s['exit']} vs {t['exit']}")
        if (
            s["entry_px"] is not None
            and t["entry_px"] is not None
            and abs(s["entry_px"] - t["entry_px"]) > 0.05
        ):
            issues.append(f"entry_px {s['entry_px']} vs {t['entry_px']}")
        if (
            s["exit_px"] is not None
            and t["exit_px"] is not None
            and abs(s["exit_px"] - t["exit_px"]) > 0.05
        ):
            issues.append(f"exit_px {s['exit_px']} vs {t['exit_px']}")
        if issues:
            forks.append({"entry": t["entry"], "issues": issues})
        else:
            matched.append(t["entry"])

    closed_e = enrich_with_zone_csv(closed, STAMP_DIR, STAMP)
    prior_e = enrich_with_zone_csv(prior_closed, PRIOR_DIR, PRIOR)
    pre2016_piv_now = [
        t for t in closed_e if t.get("pivot_monday") and t["pivot_monday"] < MIN_DATE
    ]
    pre2016_piv_prior = [
        t for t in prior_e if t.get("pivot_monday") and t["pivot_monday"] < MIN_DATE
    ]
    early_eng_only_prior = [t for t in prior_e if t["entry"] in set(prior_eng_only)]

    zones_csv = STAMP_DIR / f"WPBR_ZONES_{SYM}_{STAMP}.csv"
    znow = load_zone_pivots(zones_csv)
    zpre = [z for z in znow if z["pivot"] and z["pivot"] < MIN_DATE]

    trade_mism = []
    for t in closed:
        if t["open"]:
            continue
        s = sheet_by.get(t["entry"])
        if not s:
            continue
        diffs = []
        if (
            s.get("pnl_pct") is not None
            and t.get("pnl_pct") is not None
            and abs(s["pnl_pct"] - t["pnl_pct"]) > 0.15
        ):
            diffs.append(f"pnl% {s['pnl_pct']} vs {t['pnl_pct']}")
        if (
            s.get("days") is not None
            and t.get("days") is not None
            and abs(s["days"] - t["days"]) > 0.5
        ):
            diffs.append(f"days {s['days']} vs {t['days']}")
        if diffs:
            trade_mism.append({"entry": t["entry"], "diffs": diffs})

    payload = {
        "stamp": STAMP,
        "stamp_dir": str(STAMP_DIR),
        "min_pivot_kw_used": used_kw,
        "fair": fair,
        "raw": f"{n_raw}/{len(sheet_t)}",
        "ser": f"{n_ser}/{len(sheet_t)}",
        "n_sheet": len(sheet_t),
        "closed_n": len(closed),
        "closed_n_ex_open": sum(1 for t in closed if not t["open"]),
        "open_n": sum(1 for t in closed if t["open"]),
        "raw_orphans": raw_orphans,
        "ser_orphans": ser_orphans,
        "eng_only_entries": eng_only_entries,
        "prior_eng_only": prior_eng_only,
        "cleared_vs_prior": cleared_vs_prior,
        "added_vs_prior": added_vs_prior,
        "pre2016_piv_now": [
            {"entry": t["entry"], "pivot": t.get("pivot_monday"), "zone": t["zone_id"]}
            for t in pre2016_piv_now
        ],
        "pre2016_piv_prior": [
            {"entry": t["entry"], "pivot": t.get("pivot_monday"), "zone": t["zone_id"]}
            for t in pre2016_piv_prior
        ],
        "zones_pre2016_count": len(zpre),
        "early_eng_only_prior": [
            {
                "entry": t["entry"],
                "pivot": t.get("pivot_monday"),
                "zone": t["zone_id"],
                "cleared": t["entry"] not in ser,
            }
            for t in early_eng_only_prior
        ],
        "forks": forks,
        "matched_n": len(matched),
        "trade_mism": trade_mism,
        "stacked": stacked(closed),
        "stacked_prior": stacked(prior_closed),
        "eng_entries": [t["entry"] for t in closed],
        "sheet_entries": [t["entry"] for t in sheet_t],
        "closed_detail": [
            {
                "entry": t["entry"],
                "exit": t["exit"],
                "entry_px": t["entry_px"],
                "exit_px": t["exit_px"],
                "exit_type": t["exit_type"],
                "pnl_pct": t["pnl_pct"],
                "days": t["days"],
                "pnl_dol": t["pnl_dol"],
                "pivot_monday": t.get("pivot_monday"),
                "zone_id": t["zone_id"],
                "open": t["open"],
            }
            for t in closed_e
        ],
    }
    outp = BASE / "_startfloor_reconcile_payload.json"
    outp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(json.dumps(payload, indent=2, default=str))
    print("WROTE", outp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
