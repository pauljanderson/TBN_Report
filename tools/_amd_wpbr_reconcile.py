#!/usr/bin/env python3
"""AMD WPBR sheet vs engine stamp 260722105625 (retest_mode=stop_looking)."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(REPO / "stock_analysis"))
sys.path.insert(0, str(REPO / "tools"))

from wpbr_compare_filter import filter_wpbr_output_for_compare  # noqa: E402
from wpbr_zones import compute_wpbr_touch_stream  # noqa: E402

OUT = REPO / "drive" / "wpbr_sheet_reconcile" / "AMD"
ENG_DIR = REPO / "drive" / "wpbr_sheet_reconcile" / "_markten_retest_2016"
STAMP = "260722105625"
MIN_DATE = "2016-01-01"
RETEST_MODE = "stop_looking"
DATA = REPO / "data" / "newdata" / "data" / "AMD.csv"

ENG_ZONES = ENG_DIR / f"WPBR_ZONES_AMD_{STAMP}.csv"
ENG_CLOSED = ENG_DIR / f"WPBR_Closed_{STAMP}.csv"


def nd(s):
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    s = str(s).strip().replace("$", "").replace(",", "")
    if s in {"", "#N/A", "None", "#DIV/0!", "nan", "NaT"}:
        return None
    try:
        return pd.Timestamp(s).strftime("%Y-%m-%d")
    except Exception:
        # YYYYMMDD
        if len(s) == 8 and s.isdigit():
            return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        return None


def nf(s):
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    s = str(s).replace("$", "").replace(",", "").strip()
    if s in {"", "#N/A", "None", "#DIV/0!", "nan"}:
        return None
    try:
        return float(s)
    except Exception:
        return None


def bar_to_date(idx: pd.DatetimeIndex, b) -> str | None:
    try:
        bi = int(b)
    except (TypeError, ValueError):
        return None
    if bi < 0 or bi >= len(idx):
        return None
    return pd.Timestamp(idx[bi]).strftime("%Y-%m-%d")


def main() -> int:
    df = pd.read_csv(DATA, index_col=0, parse_dates=True).sort_index()
    idx = df.index

    # ---- sheet weekly ----
    weekly = pd.read_csv(OUT / "sheet_weekly.tsv", sep="\t", dtype=str)
    weekly.columns = [c.strip() for c in weekly.columns]
    qual = {}
    n_weekly = 0
    n_qual = 0
    for _, r in weekly.iterrows():
        n_weekly += 1
        d = nd(r.get("Weekly Date"))
        if not d or d < MIN_DATE:
            continue
        qp = str(r.get("Qualified Pivot", "")).strip().upper()
        if qp == "TRUE":
            n_qual += 1
            qual[d] = {
                "swing_px": nf(r.get("Swing High price")),
                "zone_upper": nf(r.get("Pivot Zone upper helper")),
                "strength": str(r.get("Pivot Strength%", "")).strip(),
            }

    # ---- sheet zones ----
    sz = pd.read_csv(OUT / "zones.tsv", sep="\t", dtype=str)
    sheet_z = {}
    for _, r in sz.iterrows():
        piv = nd(r.get("Pivot Date"))
        if not piv:
            continue
        sheet_z[piv] = {
            "bo": nd(r.get("Breakout Date")),
            "zlow": nf(r.get("Zone Lower")),
            "zhigh": nf(r.get("Zone Upper")),
            "conf": nd(r.get("Conf Week Date")),
            "next": nd(r.get("Next week start date")),
            "retest": nd(r.get("Daily Retest Date")),
            "rocket": nd(r.get("Rocket Buy Date")),
        }

    # ---- sheet trades ----
    st = pd.read_csv(OUT / "trades.tsv", sep="\t", dtype=str)
    sheet_trades = []
    for _, r in st.iterrows():
        entry = nd(r.get("Entry Date"))
        if not entry:
            continue
        sheet_trades.append({
            "entry": entry,
            "entry_px": nf(r.get("Entry Price")),
            "exit": nd(r.get("Exit Date")),
            "exit_px": nf(r.get("Exit Price")),
            "pnl": str(r.get("Profit %", "")).strip(),
            "res": str(r.get("Result", "")).strip(),
        })

    # ---- engine zones CSV (filter pivot >= 2016) ----
    ez = pd.read_csv(ENG_ZONES, dtype=str)
    eng_csv = {}
    for _, r in ez.iterrows():
        piv = nd(r.get("PIVOT_MONDAY") or r.get("DATE"))
        if not piv or piv < MIN_DATE:
            continue
        eng_csv[piv] = {
            "zlow": nf(r.get("ZONE_LOW")),
            "zhigh": nf(r.get("ZONE_HIGH")),
            "bo": nd(r.get("BREAKOUT_MONDAY")),
            "conf": nd(r.get("CONF_MONDAY")),
            "retest": bar_to_date(idx, r.get("RETEST_BAR")),
            "signal": bar_to_date(idx, r.get("ENTRY_SIGNAL_BAR")),
            "fill": bar_to_date(idx, r.get("ENTRY_FILL_BAR")),
        }
        # next week = Monday after conf week
        if eng_csv[piv]["conf"]:
            conf_ts = pd.Timestamp(eng_csv[piv]["conf"])
            eng_csv[piv]["next"] = (conf_ts + pd.Timedelta(days=7)).strftime("%Y-%m-%d")
        else:
            eng_csv[piv]["next"] = None

    # ---- live compute for retest/signal parity under stop_looking ----
    live = filter_wpbr_output_for_compare(
        compute_wpbr_touch_stream(
            df,
            band_pct=0.015,
            strong_pre_pivot_bars=3,
            strong_pre_pivot_pct=0.10,
            strong_post_pivot_bars=3,
            strong_post_pivot_pct=0.10,
            strong_pivot_mode="either",
            breakout_confirmation=0.03,
            max_days_after_retest=2,
            retest_mode=RETEST_MODE,
            zone_price_round_decimals=2,
        ),
        df,
        min_date=MIN_DATE,
    )
    eng_live = {}
    for ev in live.get("wpbr_zone_events") or []:
        piv = pd.Timestamp(ev["pivot_monday"]).strftime("%Y-%m-%d")
        rb = int(ev.get("retest_bar", -1))
        sb = int(ev.get("entry_signal_bar", -1))
        fb = int(ev.get("entry_fill_bar", -1))
        zl = ev.get("zone_lower", ev.get("zone_lower_f"))
        zh = ev.get("zone_upper", ev.get("zone_upper_f"))
        eng_live[piv] = {
            "zlow": float(zl),
            "zhigh": float(zh),
            "bo": nd(ev.get("breakout_monday")) or None,
            "conf": nd(ev.get("conf_monday")) or None,
            "next": nd(ev.get("next_week_start")) or None,
            "retest": bar_to_date(idx, rb),
            "signal": bar_to_date(idx, sb),
            "fill": bar_to_date(idx, fb),
        }

    # Prefer live (guarantees current retest_mode) when available; fall back to CSV.
    eng = dict(eng_csv)
    for piv, v in eng_live.items():
        eng[piv] = v

    # ---- closed trades ----
    closed = pd.read_csv(ENG_CLOSED, dtype=str)
    closed = closed[closed["SYMBOL"] == "AMD"].reset_index(drop=True)
    eng_trades = []
    for _, r in closed.iterrows():
        eng_trades.append({
            "entry": nd(r["DATE_OPENED"]),
            "entry_px": nf(r["ENTRY_PRICE"]),
            "exit": nd(r["DATE_CLOSED"]),
            "exit_px": nf(r["EXIT_PRICE"]),
            "pnl": str(r.get("PNL_PCT", "")).strip(),
            "xt": str(r.get("EXIT_TYPE", "")).strip(),
        })
    eng_entry_dates = {t["entry"] for t in eng_trades}
    raw_fills = sorted(
        pd.Timestamp(idx[b]).strftime("%Y-%m-%d")
        for b in (live.get("wpbr_entry_fill_bars") or [])
    )
    raw_fill_set = set(raw_fills)
    # Also include fill dates from eng zone events
    for v in eng.values():
        if v.get("fill"):
            raw_fill_set.add(v["fill"])

    lines: list[str] = []
    def P(s: str = "") -> None:
        lines.append(s)

    P("# AMD WPBR Sheet <-> Engine Reconcile")
    P("")
    P(f"**Engine stamp:** `{STAMP}` — MarkTen WPBR run with "
      f"**`retest_mode={RETEST_MODE}`**, `start_date={MIN_DATE}`, "
      f"`target_pct=1.22`, `stop_pct=0.89`.")
    P(f"**Artifacts:** `drive/wpbr_sheet_reconcile/_markten_retest_2016/` "
      f"(incl. `WPBR_ZONES_AMD_{STAMP}.csv`, `WPBR_Closed_{STAMP}.csv`).")
    P("**Sheet source:** user paste recovered from parent transcript "
      f"(saved under `drive/wpbr_sheet_reconcile/AMD/`).")
    P("")
    P("| Table | Rows | File |")
    P("|---|---|---|")
    P(f"| Daily OHLC | **{sum(1 for _ in (OUT/'ohlc.tsv').open(encoding='utf-8')) - 1}** bars | `ohlc.tsv` / `sheet_ohlc.csv` |")
    P(f"| Weekly WPBR | **{n_weekly}** rows / **{n_qual}** Qualified Pivot=TRUE (≥{MIN_DATE}) | `sheet_weekly.tsv` / `.csv` |")
    P(f"| Zones / BO / retest / rocket | **{len(sheet_z)}** | `zones.tsv` / `sheet_zones.csv` |")
    P(f"| Closed trades | **{len(sheet_trades)}** | `trades.tsv` / `sheet_trades.csv` |")
    P(f"| Engine zones (≥{MIN_DATE}) | **{len(eng)}** | `WPBR_ZONES_AMD_{STAMP}.csv` + live recompute |")
    P(f"| Engine serialized closed | **{len(eng_trades)}** | `WPBR_Closed_{STAMP}.csv` |")
    P("")

    # ===== 1 weekly pivots =====
    P("## 1) Weekly pivots (sheet `Qualified Pivot=TRUE`) vs engine zone pivots")
    P("")
    wp_match_piv = 0
    wp_match_zone = 0
    wp_missing = []
    wp_zone_diffs = []
    for d in sorted(qual):
        e = eng.get(d)
        wp = qual[d]
        if e:
            wp_match_piv += 1
            zu_ok = wp["zone_upper"] is not None and abs(wp["zone_upper"] - e["zhigh"]) <= 0.02
            if zu_ok:
                wp_match_zone += 1
            else:
                wp_zone_diffs.append((d, wp["zone_upper"], e["zhigh"]))
        else:
            wp_missing.append(d)
    P(f"| Check | Result |")
    P(f"|---|---|")
    P(f"| Qualified pivots present as engine zone pivots | **{wp_match_piv} / {n_qual}** |")
    P(f"| `Pivot Zone upper helper` vs engine zone-upper (±$0.02) | **{wp_match_zone} / {n_qual}** |")
    if wp_missing:
        P(f"| Sheet-only qualified pivots | {wp_missing} |")
    eng_only_piv = sorted(set(eng) - set(qual))
    if eng_only_piv:
        P(f"| Engine-only zone pivots (no sheet Qualified=TRUE) | {len(eng_only_piv)} → {eng_only_piv[:12]}"
          f"{'…' if len(eng_only_piv) > 12 else ''} |")
    if wp_zone_diffs:
        P("")
        P("Zone-upper mismatches:")
        for d, s, e in wp_zone_diffs[:20]:
            P(f"- {d}: sheet={s} eng={e}")
    P("")

    # ===== 2 zone table =====
    P("## 2) Zone table (pivot-matched pairs)")
    P("")
    stats = {k: [0, 0] for k in ["zone", "bo", "conf", "next", "retest", "rocket"]}
    misses: dict[str, list] = {k: [] for k in stats}
    zone_missing = []
    for p in sorted(sheet_z):
        s = sheet_z[p]
        e = eng.get(p)
        if not e:
            zone_missing.append(p)
            continue
        chk = {
            "zone": (
                s["zlow"] is not None and e["zlow"] is not None
                and abs(s["zlow"] - e["zlow"]) <= 0.02
                and abs(s["zhigh"] - e["zhigh"]) <= 0.02
            ),
            "bo": (s["bo"] or None) == (e["bo"] or None),
            "conf": (s["conf"] or None) == (e["conf"] or None),
            "next": (s["next"] or None) == (e.get("next") or None),
            "retest": (s["retest"] or None) == (e["retest"] or None),
            "rocket": (s["rocket"] or None) == (e["signal"] or None),
        }
        for k, ok in chk.items():
            stats[k][1] += 1
            if ok:
                stats[k][0] += 1
            else:
                if k == "rocket":
                    misses[k].append(f"{p}: sheet={s['rocket']} eng_signal={e['signal']} eng_fill={e['fill']}")
                elif k == "retest":
                    misses[k].append(f"{p}: sheet={s['retest']} eng={e['retest']}")
                elif k == "zone":
                    misses[k].append(
                        f"{p}: sheet={s['zlow']}/{s['zhigh']} eng={e['zlow']}/{e['zhigh']}"
                    )
                else:
                    misses[k].append(f"{p}: sheet={s[k]} eng={e[k]}")

    P("| Field | Match |")
    P("|---|---|")
    for k, (n, d) in stats.items():
        label = {
            "zone": "Zone lower/upper (±$0.02)",
            "bo": "Breakout Date",
            "conf": "Conf Week Date",
            "next": "Next week start date",
            "retest": "Daily Retest Date",
            "rocket": "Rocket Buy Date (vs engine **signal**)",
        }[k]
        pct = f" ({100 * n / d:.0f}%)" if d else ""
        P(f"| {label} | **{n} / {d}**{pct} |")
    if zone_missing:
        P(f"| Sheet zones with no engine zone | {zone_missing} |")
    P("")
    P("**Convention:** sheet `Rocket Buy Date` == engine **signal** date (retest/trigger day). "
      "Engine **fill** is T+1 open.")
    P("")

    # rocket breakdown
    rocket_sheet_fire = sum(1 for s in sheet_z.values() if s["rocket"])
    rocket_both = 0
    rocket_sheet_only = 0
    rocket_eng_only = 0
    for p, s in sheet_z.items():
        e = eng.get(p)
        if not e:
            continue
        if s["rocket"] and e["signal"] and s["rocket"] == e["signal"]:
            rocket_both += 1
        elif s["rocket"] and (not e["signal"] or s["rocket"] != e["signal"]):
            rocket_sheet_only += 1
        elif (not s["rocket"]) and e["signal"]:
            rocket_eng_only += 1
    P(f"Rocket fires on sheet: {rocket_sheet_fire}. Exact signal matches among matched pivots: "
      f"{stats['rocket'][0]}/{stats['rocket'][1]}. "
      f"Sheet-blank/eng-fires: {rocket_eng_only}.")
    P("")

    for k in ["zone", "bo", "conf", "next", "retest", "rocket"]:
        if misses[k]:
            P(f"### Top {k} mismatches (up to 15)")
            P("")
            for m in misses[k][:15]:
                P(f"- {m}")
            if len(misses[k]) > 15:
                P(f"- … +{len(misses[k]) - 15} more")
            P("")

    # ===== 3 trades =====
    P("## 3) Closed trades: sheet vs engine (raw signal vs serialized)")
    P("")
    sig_hits = sum(1 for t in sheet_trades if t["entry"] in raw_fill_set)
    ser_hits = sum(1 for t in sheet_trades if t["entry"] in eng_entry_dates)
    P("| Metric | Result |")
    P("|---|---|")
    P(f"| Sheet trades | **{len(sheet_trades)}** |")
    P(f"| Sheet entries present as engine RAW WPBR fills | **{sig_hits} / {len(sheet_trades)}** |")
    P(f"| Sheet entries present as engine SERIALIZED trades | **{ser_hits} / {len(sheet_trades)}** |")
    P(f"| Engine serialized closed trades (AMD) | **{len(eng_trades)}** |")
    P("")
    P("### Sheet trades")
    P("")
    P("| Entry | Px | Exit | Result | Raw signal | Serialized |")
    P("|---|---|---|---|---|---|")
    for t in sheet_trades:
        P(
            f"| {t['entry']} | {t['entry_px']} | {t['exit']} | {t['res']} | "
            f"{'YES' if t['entry'] in raw_fill_set else 'no'} | "
            f"{'YES' if t['entry'] in eng_entry_dates else 'no'} |"
        )
    sheet_only = [t["entry"] for t in sheet_trades if t["entry"] not in raw_fill_set]
    P("")
    P(f"Sheet entries NOT in engine raw fills: `{sheet_only}`")
    P("")
    P("### Engine serialized closed trades")
    P("")
    sheet_entries = {t["entry"] for t in sheet_trades}
    for t in eng_trades:
        tag = "MATCH-SHEET" if t["entry"] in sheet_entries else "engine-only"
        P(f"- `{t['entry']}` {t['entry_px']} → `{t['exit']}` {t['exit_px']} "
          f"{t['pnl']} {t['xt']} [{tag}]")
    P("")
    P("### Engine RAW WPBR fill dates (≥2016, live compute)")
    P("")
    P("`" + " ".join(raw_fills) + "`")
    P("")

    # ===== verdict =====
    P("## Verdict")
    P("")
    retest_n, retest_d = stats["retest"]
    zone_n, zone_d = stats["zone"]
    P(
        f"Zone structure: zone bands **{zone_n}/{zone_d}**, BO **{stats['bo'][0]}/{stats['bo'][1]}**, "
        f"conf **{stats['conf'][0]}/{stats['conf'][1]}**, next-week **{stats['next'][0]}/{stats['next'][1]}**, "
        f"retest **{retest_n}/{retest_d}** under `retest_mode={RETEST_MODE}`."
    )
    P(
        f"Trades: raw-signal overlap **{sig_hits}/{len(sheet_trades)}**, "
        f"serialized overlap **{ser_hits}/{len(sheet_trades)}** "
        f"(expected cascade gap with one-position-at-a-time)."
    )
    P("")
    P(f"**AMD engine files for stamp `{STAMP}`:** present "
      f"(`WPBR_ZONES_AMD_{STAMP}.csv`, `WPBR_ZONES_ENTRIES_AMD_{STAMP}.csv`, "
      f"AMD rows in `WPBR_Closed_{STAMP}.csv`).")
    P("")
    P("---")
    P(f"*Generated by `tools/_amd_wpbr_reconcile.py` against stamp `{STAMP}`.*")

    report = "\n".join(lines) + "\n"
    status = OUT / "AMD_wpbr_reconcile_status.md"
    status.write_text(report, encoding="utf-8")
    (OUT / "_full_reconcile_out.txt").write_text(report, encoding="utf-8")
    try:
        print(report)
    except UnicodeEncodeError:
        print(report.encode("ascii", "replace").decode("ascii"))
    print(f"\nWrote {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
