#!/usr/bin/env python3
"""AMZN second-chance miss diagnostic for 2022-12-08 (stamp 260722165827 halfup)."""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(REPO / "stock_analysis"))

from wpbr_zones import _half_up, find_wpbr_retest_and_signal  # noqa: E402

STAMP = "260722165827"
OUTDIR = (
    REPO
    / "drive"
    / "wpbr_sheet_reconcile"
    / "_markten_variantC_SC_stop91_startfloor_halfup_20260722165815"
)
AMZN_DIR = REPO / "drive" / "wpbr_sheet_reconcile" / "AMZN"
OUT_TXT = AMZN_DIR / "_amzn_sc_20221208_diag.txt"

ZL, ZH = 85.52, 88.12
ZONE_SUB = "85.5200|88.1200"
TARGET_FILL = "2022-12-08"
FIRST_EXIT_SHEET = "2020-04-14"


class Tee:
    def __init__(self, path: Path):
        self.path = path
        self.buf: list[str] = []

    def write(self, s: str = ""):
        print(s)
        self.buf.append(s if s.endswith("\n") else s + "\n")

    def section(self, title: str):
        self.write("")
        self.write("=" * 72)
        self.write(title)
        self.write("=" * 72)

    def flush(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("".join(self.buf), encoding="utf-8")


def nd(d):
    if d is None or (isinstance(d, float) and np.isnan(d)):
        return None
    s = str(d).strip().replace("$", "").replace(",", "")
    if s in {"", "#N/A", "None", "nan", "NaT", "#DIV/0!"}:
        return None
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) >= 8 and (s.replace(".0", "").isdigit() or len(digits) == 8):
        digits = digits[:8]
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    try:
        return pd.Timestamp(s).strftime("%Y-%m-%d")
    except Exception:
        return s


def nf(s):
    if s is None:
        return None
    t = str(s).replace("$", "").replace(",", "").replace("%", "").strip()
    if t in {"", "#N/A", "None", "nan"}:
        return None
    try:
        return float(t)
    except Exception:
        return None


def load_ohlc(sym: str = "AMZN") -> tuple[pd.DataFrame, str]:
    db = REPO / "data" / "ohlcv.duckdb"
    if db.is_file():
        try:
            con = duckdb.connect(str(db), read_only=True)
            dd = con.execute(
                "SELECT date, open, high, low, close, volume FROM prices "
                "WHERE upper(symbol)=? ORDER BY date",
                [sym.upper()],
            ).fetchdf()
            con.close()
            if len(dd):
                dd["date"] = pd.to_datetime(dd["date"])
                dd = dd.set_index("date").sort_index()
                dd.columns = ["Open", "High", "Low", "Close", "Volume"]
                return dd, f"duckdb:{db}"
        except Exception as e:
            print(f"[warn] DuckDB load failed: {e}", file=sys.stderr)
    csv_path = REPO / "data" / "newdata" / "data" / f"{sym}.csv"
    df = pd.read_csv(csv_path, index_col=0, parse_dates=True).sort_index()
    # normalize colnames
    rename = {c: c.title() for c in df.columns}
    df = df.rename(columns=rename)
    return df, f"csv:{csv_path}"


def bi(idx: pd.DatetimeIndex, d: str) -> int:
    ts = pd.Timestamp(d)
    if ts in idx:
        return int(idx.get_loc(ts))
    pos = int(idx.searchsorted(ts))
    if pos >= len(idx):
        raise KeyError(d)
    return pos


def bd(idx, b):
    if b is None:
        return None
    try:
        b = int(b)
    except Exception:
        return None
    if b < 0 or b >= len(idx):
        return None
    return pd.Timestamp(idx[b]).strftime("%Y-%m-%d")


def parse_pnl_win(pnl) -> tuple[float | None, bool | None]:
    if pnl is None or (isinstance(pnl, float) and np.isnan(pnl)):
        return None, None
    s = str(pnl).replace("%", "").strip()
    try:
        v = float(s)
    except Exception:
        return None, None
    return v, v > 0


def main():
    T = Tee(OUT_TXT)
    T.write(f"AMZN SC miss diagnostic 2022-12-08")
    T.write(f"Stamp: {STAMP}")
    T.write(f"Outdir: {OUTDIR}")
    T.write(f"Zone of interest: {ZL}-{ZH} (pivot ~2019-01-28)")
    T.write(f"Generated: {pd.Timestamp.now()}")

    closed_path = OUTDIR / f"WPBR_Closed_{STAMP}.csv"
    zones_path = OUTDIR / f"WPBR_ZONES_AMZN_{STAMP}.csv"
    entries_path = OUTDIR / f"WPBR_ZONES_ENTRIES_AMZN_{STAMP}.csv"

    closed = pd.read_csv(closed_path)
    zones = pd.read_csv(zones_path)
    entries = pd.read_csv(entries_path)

    # ------------------------------------------------------------------
    T.section("0) SHEET pastes (zones.tsv / trades.tsv) for zone 85.52-88.12")
    zlines = (AMZN_DIR / "zones.tsv").read_text(encoding="utf-8", errors="ignore").splitlines()
    if zlines:
        hdr = zlines[0].split("\t")
        T.write(f"zones.tsv header ({len(hdr)} cols): {hdr}")
        for ln in zlines[1:]:
            if "85.52" in ln or "88.12" in ln:
                cols = ln.split("\t")
                T.write("ZONE ROW RAW: " + ln)
                pairs = {hdr[i] if i < len(hdr) else f"col{i}": cols[i] if i < len(cols) else "" for i in range(max(len(hdr), len(cols)))}
                for k, v in pairs.items():
                    if v.strip():
                        T.write(f"  {k}: {v}")
                # Note: sheet zones paste has no Second Retest/Rocket/Entry columns
                T.write("NOTE: pasted zones.tsv has only first Daily Retest / Rocket Buy cols (no Second* fields).")
                T.write("Sheet user narrative Second Retest/Rocket/Entry map to OHLC rows 1746-1748:")
    ohlc_tsv = AMZN_DIR / "ohlc.tsv"
    if ohlc_tsv.is_file():
        olines = ohlc_tsv.read_text(encoding="utf-8", errors="ignore").splitlines()
        for r in (1746, 1747, 1748):
            if 1 <= r <= len(olines):
                # file may be 1-indexed data rows; print both line number and content
                T.write(f"  ohlc.tsv line {r}: {olines[r - 1] if r - 1 < len(olines) else 'N/A'}")
        # also find by date
        for ln in olines:
            if ln.startswith("12/6/2022") or ln.startswith("12/7/2022") or ln.startswith("12/8/2022"):
                T.write(f"  ohlc date match: {ln}")

    tlines = (AMZN_DIR / "trades.tsv").read_text(encoding="utf-8", errors="ignore").splitlines()
    T.write("trades.tsv:")
    for ln in tlines:
        T.write("  " + ln)
        if "12/8/2022" in ln or "3/26/2019" in ln:
            T.write("  ^ relevant trade")

    # ------------------------------------------------------------------
    T.section("1) Eng Closed: first trade on zone 85.52-88.12")
    amzn = closed[closed["SYMBOL"].astype(str).str.upper() == "AMZN"].copy()
    zone_mask = amzn["WPBR_ZONE_ID"].astype(str).str.contains(ZONE_SUB, regex=False) | (
        amzn["WPBR_ZONE_ID"].astype(str).str.contains("85.52", regex=False)
        & amzn["WPBR_ZONE_ID"].astype(str).str.contains("88.12", regex=False)
    )
    ztrades = amzn[zone_mask].copy()
    T.write(f"AMZN closed trades total: {len(amzn)}")
    T.write(f"Trades matching zone ~{ZL}-{ZH}: {len(ztrades)}")
    show_cols = [
        "SYMBOL",
        "DATE_OPENED",
        "DATE_CLOSED",
        "ENTRY_PRICE",
        "EXIT_PRICE",
        "PNL_PCT",
        "EXIT_TYPE",
        "WPBR_ZONE_ID",
        "ZONE_CENTER",
    ]
    if len(ztrades):
        first = ztrades.iloc[0]
        pnl_v, is_win = parse_pnl_win(first["PNL_PCT"])
        exit_d = nd(first["DATE_CLOSED"])
        T.write(f"FIRST trade DATE_OPENED={nd(first['DATE_OPENED'])} DATE_CLOSED={exit_d}")
        T.write(f"  ENTRY={first['ENTRY_PRICE']} EXIT={first['EXIT_PRICE']} PNL={first['PNL_PCT']} EXIT_TYPE={first['EXIT_TYPE']}")
        T.write(f"  WPBR_ZONE_ID={first['WPBR_ZONE_ID']}")
        T.write(f"  WIN? {is_win} (pnl_pct parsed={pnl_v})")
        T.write(f"  Exit vs sheet Proven exit {FIRST_EXIT_SHEET}: match={exit_d == FIRST_EXIT_SHEET}")
        T.write("ALL eng trades for this zone_id:")
        T.write(ztrades[show_cols].to_string(index=False))
    else:
        T.write("NO matching zone trades found.")
        first = None
        exit_d = None
        is_win = None

    # ------------------------------------------------------------------
    T.section("2) WPBR_ZONES_AMZN + WPBR_ZONES_ENTRIES_AMZN for zone")
    zm = zones[
        zones["WPBR_ZONE_ID"].astype(str).str.contains(ZONE_SUB, regex=False)
        | (
            zones["ZONE_LOW"].round(2).eq(ZL)
            & zones["ZONE_HIGH"].round(2).eq(ZH)
        )
    ]
    T.write(f"Matching ZONES rows: {len(zm)}")
    zcols = [
        "WPBR_ZONE_ID",
        "PIVOT_MONDAY",
        "ZONE_LOW",
        "ZONE_HIGH",
        "BREAKOUT_MONDAY",
        "CONF_MONDAY",
        "RETEST_BAR",
        "ENTRY_SIGNAL_BAR",
        "ENTRY_FILL_BAR",
        "HAS_TRADE",
    ]
    if len(zm):
        T.write(zm[zcols].to_string(index=False))
        zrow = zm.iloc[0]
    else:
        zrow = None
        T.write("(none)")

    T.write("")
    T.write(f"ENTRIES file rows: {len(entries)}")
    T.write(entries.to_string(index=False))
    # entries near zone
    if "ZONE_LOW" in entries.columns:
        em = entries[
            ((entries["ZONE_LOW"].astype(float).round(2) - ZL).abs() < 0.05)
            & ((entries["ZONE_HIGH"].astype(float).round(2) - ZH).abs() < 0.05)
        ]
        T.write(f"Entries matching zl/zh ~{ZL}/{ZH}: {len(em)}")
        if len(em):
            T.write(em.to_string(index=False))

    # ------------------------------------------------------------------
    T.section("3) OHLC load + key windows")
    df, src = load_ohlc("AMZN")
    T.write(f"OHLC source: {src}")
    T.write(f"bars={len(df)} range={df.index.min().date()}..{df.index.max().date()}")
    idx = df.index
    lo = df["Low"].to_numpy(float)
    hi = df["High"].to_numpy(float)
    cl = df["Close"].to_numpy(float)
    op = df["Open"].to_numpy(float)
    n = len(df)

    def dump_window(label, start_d, end_d):
        T.write(f"\n--- {label} ({start_d} .. {end_d}) ---")
        a = bi(idx, start_d)
        b = bi(idx, end_d)
        for i in range(a, b + 1):
            d = pd.Timestamp(idx[i]).strftime("%Y-%m-%d")
            T.write(
                f"  {d} i={i} O={op[i]:.4f} H={hi[i]:.4f} L={lo[i]:.4f} C={cl[i]:.4f} "
                f"| HU L={_half_up(lo[i]):.2f} C={_half_up(cl[i]):.2f} O={_half_up(op[i]):.2f}"
            )

    dump_window("First trade period ~2019-03", "2019-03-18", "2019-03-29")

    T.write("\n--- Days after first exit (2020-04-15 .. 2020-05-15) looking for abandon Close < 85.52 ---")
    a = bi(idx, "2020-04-15")
    b = bi(idx, "2020-05-15")
    abandon_early = []
    for i in range(a, b + 1):
        cl_r = _half_up(cl[i])
        ab = cl_r < ZL
        d = pd.Timestamp(idx[i]).strftime("%Y-%m-%d")
        flag = " ABANDON" if ab else ""
        T.write(
            f"  {d} i={i} O={op[i]:.4f} H={hi[i]:.4f} L={lo[i]:.4f} C={cl[i]:.4f} "
            f"HU_C={cl_r:.2f}{flag}"
        )
        if ab:
            abandon_early.append(d)

    dump_window("Second chance window Dec 2022", "2022-12-01", "2022-12-15")

    # ------------------------------------------------------------------
    T.section("4) find_wpbr_retest_and_signal (scan after first exit, stop_at ~2022-12-08)")
    if exit_d is None:
        exit_d = FIRST_EXIT_SHEET
    exit_bar = bi(idx, exit_d)
    scan_start = exit_bar + 1
    stop_at = bi(idx, TARGET_FILL)
    T.write(f"first_exit={exit_d} exit_bar={exit_bar}")
    T.write(f"scan_start={bd(idx, scan_start)} (bar {scan_start}) = day after exit")
    T.write(f"stop_at={TARGET_FILL} (bar {stop_at})")
    T.write(f"zone_lower={ZL} zone_upper={ZH} retest_mode=stop_looking max_days_after_retest=2")

    for mode in ("stop_looking", "keep_looking"):
        for stop in (stop_at, None):
            rt, sig, fill = find_wpbr_retest_and_signal(
                lo,
                cl,
                op,
                scan_start=scan_start,
                zone_lower=ZL,
                zone_upper=ZH,
                max_days_after_retest=2,
                n=n,
                stop_at=stop,
                retest_mode=mode,
            )
            stop_label = TARGET_FILL if stop is not None else "None(end)"
            T.write(
                f"  mode={mode:13s} stop_at={stop_label:12s} -> "
                f"retest={bd(idx, rt)} signal={bd(idx, sig)} fill={bd(idx, fill)} "
                f"(bars rt={rt} sig={sig} fill={fill})"
            )

    # Also try scan from next_week_start after first conf (first opportunity path) for reference
    if zrow is not None and int(zrow["ENTRY_FILL_BAR"]) >= 0:
        T.write(
            f"\nStamp zone first path: RETEST_BAR={int(zrow['RETEST_BAR'])} "
            f"({bd(idx, int(zrow['RETEST_BAR']))}) "
            f"SIGNAL={int(zrow['ENTRY_SIGNAL_BAR'])} ({bd(idx, int(zrow['ENTRY_SIGNAL_BAR']))}) "
            f"FILL={int(zrow['ENTRY_FILL_BAR'])} ({bd(idx, int(zrow['ENTRY_FILL_BAR']))})"
        )

    # ------------------------------------------------------------------
    T.section("5) Day-by-day walk exit+1 -> 2022-12-08 (abandon / retest / green)")
    abandon_days = []
    retest_cands = []
    green_days = []
    first_abandon = None
    first_retest = None
    for i in range(scan_start, stop_at + 1):
        lo_r = _half_up(lo[i])
        cl_r = _half_up(cl[i])
        op_r = _half_up(op[i])
        d = pd.Timestamp(idx[i]).strftime("%Y-%m-%d")
        is_ab = cl_r < ZL
        is_rt = lo_r <= ZH and cl_r > ZH
        is_gr = cl_r > op_r and cl_r > ZH
        if is_ab:
            abandon_days.append(d)
            if first_abandon is None:
                first_abandon = d
        if is_rt:
            retest_cands.append(d)
            if first_retest is None:
                first_retest = d
        if is_gr:
            green_days.append(d)

    T.write(f"bars scanned: {stop_at - scan_start + 1}")
    T.write(f"abandon days (Close HU < {ZL}): count={len(abandon_days)}")
    T.write(f"  first_abandon={first_abandon}")
    if abandon_days:
        T.write(f"  first 20: {abandon_days[:20]}")
        T.write(f"  last 10: {abandon_days[-10:]}")
    T.write(f"retest candidates (Low<=zh & Close>zh HU): count={len(retest_cands)}")
    T.write(f"  first_retest={first_retest}")
    if retest_cands:
        T.write(f"  first 20: {retest_cands[:20]}")
        # highlight Dec 2022
        dec = [d for d in retest_cands if d.startswith("2022-12")]
        T.write(f"  in 2022-12: {dec}")
    T.write(f"green signal days (Close>Open & Close>zh HU): count={len(green_days)}")
    if green_days:
        T.write(f"  first 20: {green_days[:20]}")
        decg = [d for d in green_days if d.startswith("2022-12")]
        T.write(f"  in 2022-12: {decg}")

    # Detailed Nov 2022 first-retest window + Dec 2022
    T.write("\nDetailed bars around first retest 2022-11-04 (and +2 signal window):")
    for d in ["2022-11-02", "2022-11-03", "2022-11-04", "2022-11-07", "2022-11-08", "2022-11-09", "2022-11-10"]:
        if pd.Timestamp(d) not in idx:
            T.write(f"  {d}: not a trading day")
            continue
        i = bi(idx, d)
        lo_r = _half_up(lo[i])
        cl_r = _half_up(cl[i])
        op_r = _half_up(op[i])
        is_ab = cl_r < ZL
        is_rt = lo_r <= ZH and cl_r > ZH
        is_gr = cl_r > op_r and cl_r > ZH
        T.write(
            f"  {d} O={op[i]:.4f}->{op_r:.2f} L={lo[i]:.4f}->{lo_r:.2f} C={cl[i]:.4f}->{cl_r:.2f} "
            f"abandon={is_ab} retest={is_rt} green={is_gr}"
        )

    T.write("\nDetailed Dec 2022 classification (HALF_UP compares; skip non-sessions):")
    for d in [f"2022-12-{dd:02d}" for dd in range(1, 16)]:
        if pd.Timestamp(d) not in idx:
            continue
        i = bi(idx, d)
        lo_r = _half_up(lo[i])
        cl_r = _half_up(cl[i])
        op_r = _half_up(op[i])
        is_ab = cl_r < ZL
        is_rt = lo_r <= ZH and cl_r > ZH
        is_gr = cl_r > op_r and cl_r > ZH
        T.write(
            f"  {d} O={op[i]:.4f}->{op_r:.2f} L={lo[i]:.4f}->{lo_r:.2f} C={cl[i]:.4f}->{cl_r:.2f} "
            f"abandon={is_ab} retest={is_rt} green={is_gr} "
            f"| raw_retest(L<=zh&C>zh)={lo[i] <= ZH and cl[i] > ZH} "
            f"raw_ab(C<zl)={cl[i] < ZL}"
        )

    # ------------------------------------------------------------------
    T.section("6) Float vs HALF_UP on Dec 2022 bars vs zl/zh")
    for d in ("2022-12-06", "2022-12-07", "2022-12-08", "2022-12-09"):
        try:
            i = bi(idx, d)
        except Exception:
            T.write(f"  {d}: missing")
            continue
        T.write(f"  {d}:")
        for name, val in (("Open", op[i]), ("High", hi[i]), ("Low", lo[i]), ("Close", cl[i])):
            hu = _half_up(val)
            T.write(f"    {name:5s} raw={val:.10f} half_up={hu:.2f}")
        T.write(f"    zl={ZL} zh={ZH}")
        T.write(
            f"    Low_raw <= zh? {lo[i] <= ZH} | Low_HU <= zh? {_half_up(lo[i]) <= ZH}"
        )
        T.write(
            f"    Close_raw > zh? {cl[i] > ZH} | Close_HU > zh? {_half_up(cl[i]) > ZH}"
        )
        T.write(
            f"    Close_raw < zl? {cl[i] < ZL} | Close_HU < zl? {_half_up(cl[i]) < ZL}"
        )
        T.write(
            f"    Close_raw > Open_raw? {cl[i] > op[i]} | Close_HU > Open_HU? {_half_up(cl[i]) > _half_up(op[i])}"
        )

    # Sheet OHLC for same dates
    sheet_ohlc = AMZN_DIR / "ohlc.tsv"
    if sheet_ohlc.is_file():
        T.write("\nSheet ohlc.tsv Dec 2022:")
        for ln in sheet_ohlc.read_text(encoding="utf-8", errors="ignore").splitlines():
            if any(ln.startswith(x) for x in ("12/6/2022", "12/7/2022", "12/8/2022", "12/9/2022")):
                T.write("  " + ln)

    # ------------------------------------------------------------------
    T.section("7) Eng SC second purchase for AMZN on this stamp?")
    # opportunity_index not in Closed CSV — infer: same WPBR_ZONE_ID appearing twice
    # or any zone with 2+ fills
    amzn2 = amzn.copy()
    amzn2["_zid"] = amzn2["WPBR_ZONE_ID"].astype(str)
    vc = amzn2["_zid"].value_counts()
    multi = vc[vc >= 2]
    T.write(f"AMZN zone_ids with 2+ closed trades: {len(multi)}")
    if len(multi):
        T.write(multi.to_string())
        for zid in multi.index:
            T.write(f"\n  trades for {zid}:")
            T.write(amzn2[amzn2["_zid"] == zid][show_cols].to_string(index=False))
    else:
        T.write("NONE — AMZN has no repeated WPBR_ZONE_ID (no eng SC second purchase).")

    target_zid_count = int(vc.get(str(first["WPBR_ZONE_ID"]), 0)) if first is not None else 0
    T.write(f"\nCount for zone of interest: {target_zid_count} (SC second would need 2)")
    T.write(f"Eng has SC second purchase on 85.52-88.12? {target_zid_count >= 2}")
    T.write(f"Eng has ANY AMZN SC second purchase (any zone)? {len(multi) > 0}")

    # Check open too
    open_path = OUTDIR / f"WPBR_Open_{STAMP}.csv"
    if open_path.is_file():
        opdf = pd.read_csv(open_path)
        o_amzn = opdf[opdf["SYMBOL"].astype(str).str.upper() == "AMZN"] if "SYMBOL" in opdf.columns else opdf
        T.write(f"\nOpen AMZN rows: {len(o_amzn)}")
        if len(o_amzn) and "WPBR_ZONE_ID" in o_amzn.columns:
            T.write(o_amzn[[c for c in show_cols if c in o_amzn.columns]].to_string(index=False))

    # Dec 2022 fill absent?
    fills_dec = amzn[amzn["DATE_OPENED"].astype(str).str.contains("20221208") | amzn["DATE_OPENED"].astype(str).eq("2022-12-08")]
    # DATE_OPENED is YYYYMMDD int/str
    amzn["_do"] = amzn["DATE_OPENED"].map(nd)
    T.write(f"\nEng AMZN fill on 2022-12-08: {len(amzn[amzn['_do']==TARGET_FILL])} rows")
    T.write("All AMZN entry dates: " + ", ".join(amzn["_do"].astype(str).tolist()))

    # ------------------------------------------------------------------
    T.section("8) List eng trades with that zone_id (repeat)")
    if len(ztrades):
        T.write(ztrades[show_cols].to_string(index=False))
    else:
        T.write("(none)")

    # ------------------------------------------------------------------
    T.section("9) AU peek: SC 2019-04-25 present in same halfup stamp?")
    au = closed[closed["SYMBOL"].astype(str).str.upper() == "AU"].copy()
    au["_do"] = au["DATE_OPENED"].map(nd)
    au_sc = au[au["_do"] == "2019-04-25"]
    T.write(f"AU closed trades: {len(au)}")
    T.write(f"AU DATE_OPENED=2019-04-25 rows: {len(au_sc)}")
    if len(au_sc):
        T.write(au_sc[show_cols].to_string(index=False))
        zid = str(au_sc.iloc[0]["WPBR_ZONE_ID"])
        same = au[au["WPBR_ZONE_ID"].astype(str) == zid]
        T.write(f"\nAll AU trades on same zone_id {zid}: {len(same)} (expect 2 if SC)")
        T.write(same[show_cols].to_string(index=False))
        T.write(f"AU SC 2019-04-25 PRESENT: True")
    else:
        T.write("AU SC 2019-04-25 PRESENT: False")

    # ------------------------------------------------------------------
    T.section("SUMMARY / VERDICT")
    T.write(f"First eng trade on 85.52-88.12: WIN={is_win}, exit={exit_d} (sheet {FIRST_EXIT_SHEET})")
    T.write(f"first_abandon after exit+1 before/on 2022-12-08: {first_abandon}")
    T.write(f"first_retest candidate in window: {first_retest}")
    rt, sig, fill = find_wpbr_retest_and_signal(
        lo, cl, op, scan_start=scan_start, zone_lower=ZL, zone_upper=ZH,
        max_days_after_retest=2, n=n, stop_at=stop_at, retest_mode="stop_looking",
    )
    T.write(
        f"find_wpbr stop_looking to 2022-12-08: retest={bd(idx,rt)} signal={bd(idx,sig)} fill={bd(idx,fill)}"
    )
    T.write(
        "MECHANICS: stop_looking takes the FIRST retest after scan_start; then needs a green "
        "Close>Open & Close>zh within max_days_after_retest=2 (inclusive of retest bar)."
    )
    if first_abandon and (first_retest is None or first_abandon < (first_retest or "9999")):
        T.write(
            "LIKELY ROOT: abandon-kill under stop_looking — Close < zl occurred "
            f"on {first_abandon} BEFORE any valid retest, so SC resume emits None."
        )
    elif first_retest and bd(idx, rt) == first_retest and bd(idx, fill) is None:
        T.write(
            f"LIKELY ROOT: SC resume finds first retest on {first_retest} but NO green signal "
            "within +2 bars -> (retest, None, None). Later Dec 6-8 retest/green bars are "
            "IGNORED because the scan already committed to the earlier failed retest window. "
            "Sheet Results 12/8/2022 has no Second Rocket in zones.tsv (only first rocket 3/25/2019)."
        )
    elif bd(idx, fill) == TARGET_FILL:
        T.write("Engine WOULD fill 2022-12-08 from find_wpbr — investigate occupancy/SC wiring.")
    elif bd(idx, fill) is None:
        T.write(
            "find_wpbr returns no fill by 2022-12-08. Sheet Results 12/8/2022 is orphaned "
            "vs zones paste (zones only show first rocket 3/25/2019)."
        )
    T.write(f"AU SC 2019-04-25 in stamp: {len(au_sc) > 0}")
    T.write(f"Full output saved to: {OUT_TXT}")

    T.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
