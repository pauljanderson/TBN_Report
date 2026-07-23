#!/usr/bin/env python3
"""META-only reconcile vs startfloor halfup stamp 260722165827."""
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
STAMP_DIR_LABEL = "_markten_variantC_SC_stop91_startfloor_halfup_20260722165815"
BASE = REPO / "drive" / "wpbr_sheet_reconcile"
DATA = REPO / "data" / "newdata" / "data"
MIN_DATE = "2016-01-01"
SYM = "META"


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


def load_closed(sym: str) -> tuple[list[dict], pd.DataFrame]:
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
                        "open": True,
                    }
                )
    out.sort(key=lambda x: x["entry"] or "")
    return out, df


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
    missing_pivs = sorted(sheet_pivs - set(eng))
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
        "missing_pivots": missing_pivs,
    }


def stacked_from_closed(cdf: pd.DataFrame) -> dict:
    """6-value stacked: n, win%, avg profit%, win/loss, avg days, $PnL."""
    cols = {c.upper(): c for c in cdf.columns}

    def col(*names):
        for n in names:
            if n.upper() in cols:
                return cols[n.upper()]
        return None

    pnl_c = col("PNL_DOLLARS", "PNL", "PROFIT", "DOLLAR_PNL", "P&L")
    pct_c = col("PNL_PCT", "PROFIT_PCT", "RETURN_PCT", "PCT")
    days_c = col("DAYS_HELD", "HOLD_DAYS", "DAYS", "BARS_HELD")
    exit_c = col("EXIT_PRICE", "PRICE_CLOSED")
    entry_c = col("ENTRY_PRICE", "PRICE_OPENED")

    n = len(cdf)
    if n == 0:
        return {
            "n": 0,
            "win_pct": None,
            "avg_profit_pct": None,
            "win_loss": None,
            "avg_days": None,
            "dollar_pnl": None,
            "lines": ["0", "n/a", "n/a", "n/a", "n/a", "$0.00"],
        }

    if pct_c:
        pcts = cdf[pct_c].map(nf)
        pcts = pd.to_numeric(pcts, errors="coerce")
        if pcts.notna().any() and pcts.abs().median() < 1.5:
            pcts = pcts * 100.0
    elif exit_c and entry_c:
        pcts = (
            pd.to_numeric(cdf[exit_c], errors="coerce")
            / pd.to_numeric(cdf[entry_c], errors="coerce")
            - 1.0
        ) * 100.0
    else:
        pcts = pd.Series([float("nan")] * n)

    if pnl_c:
        pnls = cdf[pnl_c].map(nf)
        pnls = pd.to_numeric(pnls, errors="coerce")
    else:
        pnls = pd.Series([float("nan")] * n)

    if days_c:
        days = pd.to_numeric(cdf[days_c], errors="coerce")
    else:
        o = cdf.get(col("DATE_OPENED") or "DATE_OPENED")
        c = cdf.get(col("DATE_CLOSED") or "DATE_CLOSED")
        if o is not None and c is not None:
            days = (pd.to_datetime(c) - pd.to_datetime(o)).dt.days.astype(float)
        else:
            days = pd.Series([float("nan")] * n)

    wins = pcts[pcts > 0]
    losses = pcts[pcts <= 0]
    win_pct = 100.0 * len(wins) / n
    avg_profit = float(pcts.mean())
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0
    win_loss = (avg_win / abs(avg_loss)) if avg_loss != 0 else None
    avg_days = float(days.mean()) if days.notna().any() else None
    dollar = float(pnls.sum()) if pnls.notna().any() else None

    lines = [
        str(n),
        f"{win_pct:.1f}%",
        f"{avg_profit:.1f}%",
        f"{win_loss:.2f}" if win_loss is not None else "n/a",
        f"{avg_days:.1f}" if avg_days is not None else "n/a",
        f"${dollar:,.2f}" if dollar is not None else "n/a",
    ]
    return {
        "n": n,
        "win_pct": win_pct,
        "avg_profit_pct": avg_profit,
        "win_loss": win_loss,
        "avg_days": avg_days,
        "dollar_pnl": dollar,
        "lines": lines,
    }


def trade_forks(sheet_t: list[dict], closed: list[dict]) -> list[dict]:
    """Entry-matched pairs with exit/price disagreement (forks)."""
    by_entry = {t["entry"]: t for t in closed if t["entry"] and not t["open"]}
    forks = []
    for s in sheet_t:
        e = by_entry.get(s["entry"])
        if not e:
            continue
        exit_diff = s["exit"] and e["exit"] and s["exit"] != e["exit"]
        px_diff = (
            s["entry_px"] is not None
            and e["entry_px"] is not None
            and abs(s["entry_px"] - e["entry_px"]) > 0.02
        )
        exit_px_diff = (
            s["exit_px"] is not None
            and e["exit_px"] is not None
            and abs(s["exit_px"] - e["exit_px"]) > 0.05
        )
        if exit_diff or px_diff or exit_px_diff:
            forks.append(
                {
                    "entry": s["entry"],
                    "sheet_exit": s["exit"],
                    "eng_exit": e["exit"],
                    "sheet_entry_px": s["entry_px"],
                    "eng_entry_px": e["entry_px"],
                    "sheet_exit_px": s["exit_px"],
                    "eng_exit_px": e["exit_px"],
                }
            )
    return forks


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
    closed, cdf = load_closed(SYM)
    ser = {t["entry"] for t in closed}
    fair = structure_stats(sheet_z, eng)
    n_raw = n_ser = 0
    for t in sheet_t:
        n_raw += int(t["entry"] in raw_fills)
        n_ser += int(t["entry"] in ser)
    raw_orphans = [t["entry"] for t in sheet_t if t["entry"] not in raw_fills]
    ser_orphans = [t["entry"] for t in sheet_t if t["entry"] not in ser]
    eng_only_entries = sorted(ser - {t["entry"] for t in sheet_t})
    forks = trade_forks(sheet_t, closed)
    stacked = stacked_from_closed(cdf)

    # SC in log
    log = STAMP_DIR / "_run_log.txt"
    log_txt = read_text_any(log) if log.is_file() else ""
    sc_ok = (
        "wpbr_second_chance_after_win=true" in log_txt
        or "wpbr_second_chance_after_win=True" in log_txt
    )

    status = out_dir / f"{SYM}_wpbr_reconcile_status.md"
    lines: list[str] = []
    lines.append(
        f"# {SYM} WPBR reconcile — variant C + SC-on + startfloor halfup (`{STAMP}`)"
    )
    lines.append("")
    lines.append(
        f"**Engine:** `drive/wpbr_sheet_reconcile/{STAMP_DIR_LABEL}/` "
        f"(`{STAMP}`)"
    )
    lines.append(
        f"**SC:** `wpbr_second_chance_after_win=true` (log: **{sc_ok}**)"
    )
    lines.append(
        "**Floor:** `min_pivot_date=2016-01-01` (pre-2016 weekly pivots excluded)."
    )
    lines.append(
        "**Rounding:** zone bounds / pivot HALF_UP (halfup stamp)."
    )
    lines.append("**Paste:** breakouts/retests/rockets + trades only (OHLC/weekly unchanged).")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Pivots | {fair['pivots_match']} |")
    lines.append(f"| Zones | {fair['zones_ok']} |")
    lines.append(f"| Retest | {fair['retest_ok']} |")
    lines.append(f"| Rocket (sheet fires) | {fair['rocket_where_sheet_fires']} |")
    lines.append(f"| Raw | **{n_raw}/{len(sheet_t)}** |")
    lines.append(f"| Ser | **{n_ser}/{len(sheet_t)}** |")
    lines.append(f"| Eng closed (+open) | {len(closed)} |")
    lines.append(f"| Sheet trades ≥2016 | {len(sheet_t)} |")
    lines.append("")
    if raw_orphans:
        lines.append(f"**Raw orphans:** {', '.join(raw_orphans)}")
        lines.append("")
    if ser_orphans:
        lines.append(f"**Ser orphans:** {', '.join(ser_orphans)}")
        lines.append("")
    if eng_only_entries:
        lines.append(f"**Eng-only ser entries:** {', '.join(eng_only_entries)}")
        lines.append("")
    if forks:
        lines.append(f"**Trade forks ({len(forks)}):**")
        for f in forks[:20]:
            lines.append(
                f"- entry `{f['entry']}` sheet exit `{f['sheet_exit']}` @ {f['sheet_exit_px']} "
                f"vs eng `{f['eng_exit']}` @ {f['eng_exit_px']} "
                f"(entry_px sheet {f['sheet_entry_px']} vs eng {f['eng_entry_px']})"
            )
        lines.append("")
    else:
        lines.append("**Trade forks:** none (matched entries agree on exit/prices within tolerance).")
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
    if fair["missing_pivots"]:
        lines.append(f"**Sheet pivots missing in eng:** {', '.join(fair['missing_pivots'])}")
        lines.append("")

    lines.append("## Engine stacked (closed only)")
    lines.append("")
    lines.append("Order: trades → win% → avg profit% → win/loss → avg days → $PnL")
    lines.append("")
    lines.append("```")
    lines.append(SYM)
    for ln in stacked["lines"]:
        lines.append(ln)
    lines.append("```")
    lines.append("")
    lines.append(
        f"*Generated vs startfloor stamp `{STAMP}` "
        f"(`_tmp_META_startfloor_reconcile.py` / min_pivot_date={MIN_DATE}).*"
    )
    lines.append("")
    status.write_text("\n".join(lines), encoding="utf-8")

    parent = {
        "symbol": SYM,
        "stamp": STAMP,
        "stamp_dir": str(STAMP_DIR),
        "sc_in_run_log": sc_ok,
        "pivots": fair["pivots_match"],
        "zones": fair["zones_ok"],
        "retest": fair["retest_ok"],
        "rocket_sheet_fires": fair["rocket_where_sheet_fires"],
        "raw": f"{n_raw}/{len(sheet_t)}",
        "ser": f"{n_ser}/{len(sheet_t)}",
        "closed_n": len(closed),
        "closed_only_n": len(cdf),
        "sheet_trades": len(sheet_t),
        "raw_orphans": raw_orphans,
        "ser_orphans": ser_orphans,
        "eng_only_ser": eng_only_entries,
        "forks": forks,
        "n_eng_only_rockets": fair["n_eng_only"],
        "eng_only_rockets": fair["eng_only"][:15],
        "retest_mismatches": fair["retest_mismatches"][:20],
        "stacked": stacked,
        "status_md": str(status),
    }
    parent_path = out_dir / f"{SYM}_startfloor_{STAMP}_parent_summary.json"
    parent_path.write_text(json.dumps(parent, indent=2, default=str), encoding="utf-8")

    print("=== META startfloor reconcile ===")
    print(f"piv/zone/retest {fair['pivots_match']} / {fair['zones_ok']} / {fair['retest_ok']}")
    print(f"rocket {fair['rocket_where_sheet_fires']} raw {n_raw}/{len(sheet_t)} ser {n_ser}/{len(sheet_t)}")
    print(f"closed(+open)={len(closed)} closed_only={len(cdf)}")
    print(f"raw_orphans={raw_orphans}")
    print(f"ser_orphans={ser_orphans}")
    print(f"eng_only_ser={eng_only_entries}")
    print(f"forks={len(forks)}")
    print("stacked:", stacked["lines"])
    print(f"wrote {status}")
    print(f"wrote {parent_path}")
    print("CLOSED_COLS", list(cdf.columns))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
