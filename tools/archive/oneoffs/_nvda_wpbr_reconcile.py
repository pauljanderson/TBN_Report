#!/usr/bin/env python3
"""NVDA WPBR sheet vs engine reconcile (stamp 260722105625, retest_mode=stop_looking)."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "stock_analysis"))
sys.path.insert(0, str(REPO / "tools"))

from wpbr_compare_filter import filter_wpbr_output_for_compare
from wpbr_zones import compute_wpbr_touch_stream

MIN_DATE = "2016-01-01"
RETEST_MODE = "stop_looking"
STAMP = "260722105625"
ENG_DIR = REPO / "drive" / "wpbr_sheet_reconcile" / "_markten_retest_2016"
BASE = REPO / "drive" / "wpbr_sheet_reconcile" / "NVDA"
DATA = REPO / "data" / "newdata" / "data" / "NVDA.csv"
ZONES = BASE / "zones.tsv"
WEEKLY = BASE / "sheet_weekly.tsv"
TRADES = BASE / "trades.tsv"
OHLC = BASE / "ohlc.tsv"
ENG_CLOSED = ENG_DIR / f"WPBR_Closed_{STAMP}.csv"
ENG_ZONES = ENG_DIR / f"WPBR_ZONES_NVDA_{STAMP}.csv"
STATUS = BASE / "NVDA_wpbr_reconcile_status.md"
OUT_TXT = BASE / "_full_reconcile_out.txt"


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
    s = str(s).replace("$", "").replace(",", "").strip()
    if s in {"", "#N/A", "None", "#DIV/0!", "nan"}:
        return None
    try:
        return float(s)
    except Exception:
        return None


def bar_date(idx, b):
    b = int(b) if b is not None and str(b) not in {"", "nan", "None"} else -1
    if b < 0:
        return None
    try:
        return pd.Timestamp(idx[b]).strftime("%Y-%m-%d")
    except Exception:
        return None


def load_sheet_zones():
    rows = ZONES.read_text(encoding="utf-8").splitlines()
    head = rows[0].split("\t")
    col = {h: i for i, h in enumerate(head)}
    out = {}
    for line in rows[1:]:
        if not line.strip():
            continue
        c = line.split("\t") + [""] * 20
        piv = nd(c[col["Pivot Date"]])
        if not piv:
            continue
        out[piv] = {
            "bo": nd(c[col["Breakout Date"]]),
            "zlow": nf(c[col["Zone Lower"]]),
            "zhigh": nf(c[col["Zone Upper"]]),
            "conf": nd(c[col["Conf Week Date"]]),
            "next": nd(c[col["Next week start date"]]),
            "retest": nd(c[col["Daily Retest Date"]]),
            "rocket": nd(c[col["Rocket Buy Date"]]),
        }
    return out


def load_weekly_pivots():
    rows = WEEKLY.read_text(encoding="utf-8").splitlines()
    head = rows[0].split("\t")
    col = {h: i for i, h in enumerate(head)}
    piv = {}
    n_weekly = 0
    for line in rows[1:]:
        if not line.strip():
            continue
        c = line.split("\t") + [""] * len(head)
        n_weekly += 1
        if c[col["Qualified Pivot"]].strip().upper() != "TRUE":
            continue
        d = nd(c[col["Weekly Date"]])
        piv[d] = {
            "swing_px": nf(c[col["Swing High price"]]),
            "zone_upper": nf(c[col["Pivot Zone upper helper"]]),
        }
    return piv, n_weekly


def load_sheet_trades():
    rows = TRADES.read_text(encoding="utf-8").splitlines()
    trades = []
    for line in rows[1:]:
        if not line.strip():
            continue
        c = line.split("\t")
        trades.append({
            "entry": nd(c[0]),
            "entry_px": nf(c[1]),
            "exit": nd(c[2]),
            "exit_px": nf(c[3]),
            "pnl": c[4] if len(c) > 4 else "",
            "res": c[6] if len(c) > 6 else "",
        })
    return trades


def engine_from_live(df: pd.DataFrame) -> dict:
    raw = compute_wpbr_touch_stream(
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
    )
    out = filter_wpbr_output_for_compare(raw, df, min_date=MIN_DATE)
    eng = {}
    for ev in out["wpbr_zone_events"]:
        piv = ev["pivot_monday"]
        eng[piv] = {
            "zlow": float(ev["zone_lower"]),
            "zhigh": float(ev["zone_upper"]),
            "bo": ev.get("breakout_monday") or None,
            "conf": ev.get("conf_monday") or None,
            "next": ev.get("next_week_start") or None,
            "retest": bar_date(df.index, ev.get("retest_bar", -1)),
            "signal": bar_date(df.index, ev.get("entry_signal_bar", -1)),
            "fill": bar_date(df.index, ev.get("entry_fill_bar", -1)),
        }
    fills = sorted(bar_date(df.index, b) for b in (out.get("wpbr_entry_fill_bars") or []))
    fills = [f for f in fills if f]
    return eng, fills, out


def main() -> int:
    lines: list[str] = []

    def P(s: str = "") -> None:
        lines.append(s)
        print(s)

    df = pd.read_csv(DATA, index_col=0, parse_dates=True)
    sheet_z = load_sheet_zones()
    weekly_piv, n_weekly = load_weekly_pivots()
    sheet_trades = load_sheet_trades()
    eng, raw_fills, _out = engine_from_live(df)

    ohlc_n = len(OHLC.read_text(encoding="utf-8").splitlines()) - 1
    eng_closed_all = pd.read_csv(ENG_CLOSED, dtype=str)
    eng_closed = eng_closed_all[eng_closed_all["SYMBOL"] == "NVDA"].reset_index(drop=True)
    eng_zones_csv_exists = ENG_ZONES.exists()
    eng_zones_n = 0
    if eng_zones_csv_exists:
        ez = pd.read_csv(ENG_ZONES)
        eng_zones_n = int((pd.to_datetime(ez["PIVOT_MONDAY"]) >= MIN_DATE).sum())

    P(f"=== NVDA WPBR FULL RECONCILE (sheet vs stamp {STAMP}, retest_mode={RETEST_MODE}) ===")
    P(f"Sheet: OHLC={ohlc_n} bars, weekly={n_weekly}, zones={len(sheet_z)}, trades={len(sheet_trades)}")
    P(f"Engine Closed NVDA rows: {len(eng_closed)} | ZONES file exists={eng_zones_csv_exists} "
      f"(pivot>={MIN_DATE}: {eng_zones_n}) | live zones>={MIN_DATE}: {len(eng)}")
    P("")

    # 1) weekly pivots
    P("=== 1) WEEKLY QUALIFIED PIVOTS vs ENGINE zones ===")
    n_qual = len(weekly_piv)
    wp_match_piv = wp_match_zone = 0
    wp_missing = []
    for d in sorted(weekly_piv):
        e = eng.get(d)
        wp = weekly_piv[d]
        if e:
            wp_match_piv += 1
            zu_ok = wp["zone_upper"] is not None and abs(wp["zone_upper"] - e["zhigh"]) <= 0.02
            if zu_ok:
                wp_match_zone += 1
            tag = "ZONE-OK" if zu_ok else f"ZONE-DIFF s={wp['zone_upper']} e={e['zhigh']}"
        else:
            wp_missing.append(d)
            tag = "ENGINE-MISSING"
        P(f"  {d}  swingpx={wp['swing_px']}  zoneUpper={wp['zone_upper']}  -> {tag}")
    P(f"Weekly pivots present as engine zone pivots: {wp_match_piv}/{n_qual}")
    P(f"Weekly zone-upper matches engine zhigh (+-0.02): {wp_match_zone}/{n_qual}")
    if wp_missing:
        P(f"Weekly qualified pivots with NO engine zone: {wp_missing}")
    P("")

    # 2) zone table
    P("=== 2) ZONE TABLE (sheet) vs ENGINE (matched by pivot date) ===")
    stats = {k: [0, 0] for k in ["zone", "bo", "conf", "next", "retest", "rocket"]}
    rocket_sheet_fire = [0, 0]  # match where sheet fires
    zone_missing = []
    mismatches: list[str] = []
    P(f"{'pivot':>10} {'zone':>5}{'bo':>4}{'conf':>5}{'next':>5}{'retest':>7}{'rocket':>7}  detail")
    for p in sorted(sheet_z):
        s = sheet_z[p]
        e = eng.get(p)
        if not e:
            zone_missing.append(p)
            P(f"{p:>10}  ENGINE-MISSING")
            mismatches.append(f"zone pivot {p}: ENGINE-MISSING")
            continue
        chk = {
            "zone": (
                s["zlow"] is not None
                and abs(s["zlow"] - e["zlow"]) <= 0.02
                and abs(s["zhigh"] - e["zhigh"]) <= 0.02
            ),
            "bo": (s["bo"] or None) == (e["bo"] or None),
            "conf": (s["conf"] or None) == (e["conf"] or None),
            "next": (s["next"] or None) == (e["next"] or None),
            "retest": (s["retest"] or None) == (e["retest"] or None),
            "rocket": (s["rocket"] or None) == (e["signal"] or None),
        }
        det = []
        for k, ok in chk.items():
            stats[k][1] += 1
            if ok:
                stats[k][0] += 1
            elif k == "rocket":
                det.append(f"rocket[s={s['rocket']} e_signal={e['signal']} e_fill={e['fill']}]")
            elif k == "retest":
                det.append(f"retest[s={s['retest']} e={e['retest']}]")
            elif k == "zone":
                det.append(f"zone[s={s['zlow']}/{s['zhigh']} e={e['zlow']}/{e['zhigh']}]")
            else:
                det.append(f"{k}[s={s[k]} e={e[k]}]")
        if s["rocket"]:
            rocket_sheet_fire[1] += 1
            if chk["rocket"]:
                rocket_sheet_fire[0] += 1
        if det:
            mismatches.append(f"{p}: {'; '.join(det)}")
        f = lambda ok: " OK " if ok else " XX "
        P(
            f"{p:>10} {f(chk['zone'])}{f(chk['bo'])}{f(chk['conf'])}{f(chk['next'])}"
            f"{f(chk['retest'])}{f(chk['rocket'])}  {' '.join(det)}"
        )
    P("")
    P("--- ZONE MATCH STATS ---")
    for k, (n, d) in stats.items():
        P(f"  {k:>7}: {n}/{d} ({100 * n / d:.0f}%)" if d else f"  {k:>7}: 0/0")
    P(f"  rocket where sheet fires: {rocket_sheet_fire[0]}/{rocket_sheet_fire[1]}")
    if zone_missing:
        P(f"Sheet zones with no engine zone: {zone_missing}")
    eng_only_piv = sorted(set(eng) - set(sheet_z))
    if eng_only_piv:
        P(f"Engine zones with no sheet zone ({len(eng_only_piv)}): {eng_only_piv}")
    P("")

    # 3) trades
    P("=== 3) CLOSED TRADES: sheet vs engine serialized ===")
    eng_entries = {nd(x) for x in eng_closed["DATE_OPENED"]}
    raw_set = set(raw_fills)
    sheet_entries = {t["entry"] for t in sheet_trades}
    P("Engine serialized closed trades:")
    for _, r in eng_closed.iterrows():
        do = nd(r["DATE_OPENED"])
        tag = "MATCH-SHEET" if do in sheet_entries else "engine-only"
        P(
            f"  {do}  {r['ENTRY_PRICE']:>8} -> {nd(r['DATE_CLOSED'])} {r['EXIT_PRICE']:>8} "
            f"{r.get('PNL_PCT', '?'):>8} {r.get('EXIT_TYPE', ''):<10} [{tag}]"
        )
    P("")
    sig_hits = sum(1 for t in sheet_trades if t["entry"] in raw_set)
    ser_hits = sum(1 for t in sheet_trades if t["entry"] in eng_entries)
    P("Sheet trade entry -> raw signal / serialized:")
    for t in sheet_trades:
        P(
            f"  {t['entry']}  raw={'YES' if t['entry'] in raw_set else 'no ':>3}  "
            f"serialized={'YES' if t['entry'] in eng_entries else 'no'}"
        )
    P("")
    P(f"Sheet trades: {len(sheet_trades)}")
    P(f"Sheet entries that ARE valid engine WPBR raw signals: {sig_hits}/{len(sheet_trades)}")
    P(f"Sheet entries that ARE engine serialized trades:      {ser_hits}/{len(sheet_trades)}")
    sheet_only = [t["entry"] for t in sheet_trades if t["entry"] not in raw_set]
    P(f"Sheet entries NOT in engine raw signals: {sheet_only}")
    P(f"Engine raw fills (>=2016): {' '.join(raw_fills)}")

    report = "\n".join(lines)
    OUT_TXT.write_text(report, encoding="utf-8")

    # status markdown
    def pct(n, d):
        return f"**{n} / {d}**" if d else "**0 / 0**"

    retest_n, retest_d = stats["retest"]
    zone_n, zone_d = stats["zone"]
    bo_n, bo_d = stats["bo"]
    conf_n, conf_d = stats["conf"]
    next_n, next_d = stats["next"]
    rocket_n, rocket_d = stats["rocket"]
    rf_n, rf_d = rocket_sheet_fire

    top_mm = mismatches[:12]
    mm_block = "\n".join(f"- `{m}`" for m in top_mm) if top_mm else "_None_"

    verdict = "PASS" if (
        wp_match_piv == n_qual
        and zone_n == zone_d
        and bo_n == bo_d
        and conf_n == conf_d
        and next_n == next_d
        and retest_n == retest_d
        and rf_n == rf_d
    ) else "PARTIAL"

    status = f"""# NVDA WPBR Sheet ↔ Engine Reconcile

**Engine stamp:** `{STAMP}` — MarkTen WPBR run with **`retest_mode=stop_looking`** (default),
`start_date=2016-01-01`, `target_pct=1.22`, `stop_pct=0.89`.
Artifacts under `drive/wpbr_sheet_reconcile/_markten_retest_2016/`.

**Sheet source:** user paste recovered from parent chat transcript
(`tools/_nvda_extract_paste.py` → `drive/wpbr_sheet_reconcile/NVDA/`).

| Table | Rows | File |
|---|---|---|
| Daily OHLC (1/4/2016–…) | **{ohlc_n}** bars | `ohlc.tsv` / `sheet_ohlc.tsv` / `.csv` |
| Weekly WPBR | **{n_weekly}** rows | `sheet_weekly.tsv` / `.csv` |
| Zones / BO / retest / rocket | **{len(sheet_z)}** zone rows | `zones.tsv` / `sheet_zones.tsv` / `.csv` |
| Closed trades | **{len(sheet_trades)}** | `trades.tsv` / `sheet_trades.tsv` / `.csv` |

**Engine files for stamp `{STAMP}`:** **YES** — NVDA was in the MarkTen run
(`BRT_Profile_Symbols_*` shows NVDA, 4161 bars). Present:
- `WPBR_Closed_{STAMP}.csv` (NVDA: **{len(eng_closed)}** closed)
- `WPBR_ZONES_NVDA_{STAMP}.csv` ({eng_zones_n} zones with pivot ≥ 2016; live compute: {len(eng)})
- `WPBR_Summary_{STAMP}.csv` (NVDA row: 4 trades)

---

## VERDICT

**{verdict}** on WPBR structure (pivots / zones / BO / confirm / next / retest / rocket-where-fired).
Serialized closed-trade parity is expected to be low due to one-position cascade (same pattern as META).

| Metric | Result |
|---|---|
| Qualified pivots → engine zone pivots | {pct(wp_match_piv, n_qual)} |
| Weekly zone-upper (±$0.02) | {pct(wp_match_zone, n_qual)} |
| Zone lower/upper (±$0.02) | {pct(zone_n, zone_d)} |
| Breakout Date | {pct(bo_n, bo_d)} |
| Conf Week Date | {pct(conf_n, conf_d)} |
| Next week start date | {pct(next_n, next_d)} |
| Daily Retest Date (`stop_looking`) | {pct(retest_n, retest_d)} |
| Rocket Buy Date vs engine **signal** (all pairs) | {pct(rocket_n, rocket_d)} |
| Rocket where sheet fires | {pct(rf_n, rf_d)} |
| Sheet trades = engine RAW signals | {pct(sig_hits, len(sheet_trades))} |
| Sheet trades = engine SERIALIZED | {pct(ser_hits, len(sheet_trades))} |
| Engine serialized closed (NVDA) | **{len(eng_closed)}** |

---

## Engine serialized closed trades (NVDA)

"""
    for _, r in eng_closed.iterrows():
        do = nd(r["DATE_OPENED"])
        tag = "MATCH-SHEET" if do in sheet_entries else "engine-only"
        status += (
            f"- `{do}` {r['ENTRY_PRICE']} → `{nd(r['DATE_CLOSED'])}` {r['EXIT_PRICE']} "
            f"{r.get('PNL_PCT','?')} {r.get('EXIT_TYPE','')} [{tag}]\n"
        )

    status += f"""
## Sheet trade coverage

| Entry | Raw signal | Serialized |
|---|---|---|
"""
    for t in sheet_trades:
        status += (
            f"| `{t['entry']}` | "
            f"{'YES' if t['entry'] in raw_set else 'no'} | "
            f"{'YES' if t['entry'] in eng_entries else 'no'} |\n"
        )

    status += f"""
Sheet entries **not** in engine raw signals: `{sheet_only}`

## Top mismatches

{mm_block}

Engine-only pivots (no sheet zone): `{eng_only_piv}`

---

*Reconcile scripts:* `tools/_nvda_extract_paste.py`, `tools/_nvda_wpbr_reconcile.py`  
*Full console dump:* `_full_reconcile_out.txt`
"""
    STATUS.write_text(status, encoding="utf-8")
    P("")
    P(f"Wrote {OUT_TXT}")
    P(f"Wrote {STATUS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
