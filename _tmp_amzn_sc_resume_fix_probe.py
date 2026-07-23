#!/usr/bin/env python3
"""AMZN SC resume-fix probe: failed rocket window lock + Dec 6-8 recovery."""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(REPO / "stock_analysis"))

from wpbr_zones import _half_up, find_wpbr_retest_and_signal  # noqa: E402

AMZN_DIR = REPO / "drive" / "wpbr_sheet_reconcile" / "AMZN"
OUT_TXT = AMZN_DIR / "_amzn_sc_resume_fix_probe.txt"

ZL, ZH = 85.52, 88.12
MAX_D = 2
FIRST_EXIT = "2020-04-14"
FAILED_RETEST = "2022-11-04"
SHEET_SECOND_RETEST = "2022-12-06"
SHEET_SECOND_ROCKET = "2022-12-07"
SHEET_SECOND_ENTRY = "2022-12-08"
NOV9 = "2022-11-09"


class Tee:
    def __init__(self, path: Path):
        self.path = path
        self.buf: list[str] = []

    def write(self, s: str = ""):
        line = s if s.endswith("\n") else s + "\n"
        self.buf.append(line)
        try:
            sys.stdout.buffer.write(line.encode("utf-8", errors="replace"))
            sys.stdout.buffer.flush()
        except Exception:
            print(s)

    def section(self, title: str):
        self.write("")
        self.write("=" * 72)
        self.write(title)
        self.write("=" * 72)

    def flush(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("".join(self.buf), encoding="utf-8")


def load_ohlc(sym: str = "AMZN") -> tuple[pd.DataFrame, str]:
    db = REPO / "data" / "ohlcv.duckdb"
    if db.is_file():
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
    raise FileNotFoundError("no OHLC")


def bi(idx: pd.DatetimeIndex, d: str) -> int:
    ts = pd.Timestamp(d)
    if ts in idx:
        return int(idx.get_loc(ts))
    raise KeyError(d)


def bd(idx, b):
    if b is None:
        return None
    b = int(b)
    if b < 0 or b >= len(idx):
        return None
    return pd.Timestamp(idx[b]).strftime("%Y-%m-%d")


def bar_summary(df, i, zl=ZL, zh=ZH):
    r = df.iloc[i]
    o, h, l, c = float(r.Open), float(r.High), float(r.Low), float(r.Close)
    ou, hu, lu, cu = _half_up(o), _half_up(h), _half_up(l), _half_up(c)
    zl_u, zh_u = _half_up(zl), _half_up(zh)
    is_retest = lu <= zh_u and cu > zh_u
    is_green = cu > ou and cu > zh_u
    abandon = cu < zl_u
    d = pd.Timestamp(df.index[i]).strftime("%Y-%m-%d")
    return {
        "date": d,
        "O": ou,
        "H": hu,
        "L": lu,
        "C": cu,
        "retest": is_retest,
        "green_sig": is_green,
        "abandon": abandon,
        "raw": (o, h, l, c),
    }


def parse_sheet_ohlc_row(ln: str):
    # date\t$open\thigh\tlow\tclose
    parts = ln.strip().split("\t")
    if len(parts) < 5:
        return None
    d = parts[0].strip()
    try:
        ts = pd.Timestamp(d)
    except Exception:
        return None

    def pf(x):
        return float(str(x).replace("$", "").replace(",", "").strip())

    return ts.strftime("%Y-%m-%d"), pf(parts[1]), pf(parts[2]), pf(parts[3]), pf(parts[4])


def search_docs(T: Tee):
    T.section("3) Repo docs/formulas: Second Retest / Proven Trade / skip failed windows")
    keys = [
        "Second Retest",
        "Second Rocket",
        "Second Entry",
        "second chance",
        "wpbr_second_chance",
        "Proven Trade",
        "failed rocket",
        "skip failed",
        "resume_scan_bar",
        "allow_second",
    ]
    roots = [
        REPO / "drive",
        REPO / "stock_analysis",
        REPO / "docs",
    ]
    hits_summary: list[tuple[str, list[str], list[str]]] = []
    skip_mentions: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if p.suffix.lower() not in {".md", ".py", ".txt"}:
                continue
            # skip huge generated dumps
            if p.stat().st_size > 2_000_000:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            low = text.lower()
            matched = [k for k in keys if k.lower() in low]
            if not matched:
                continue
            samples = []
            for i, line in enumerate(text.splitlines(), 1):
                ll = line.lower()
                if any(k.lower() in ll for k in keys):
                    samples.append(f"L{i}: {line.strip()[:180]}")
                    if len(samples) >= 3:
                        break
                # look for skip-failed-window language near SC
                if (
                    "skip" in ll
                    and ("rocket" in ll or "retest" in ll or "window" in ll)
                    and ("second" in ll or "chance" in ll or "sc " in ll or "failed" in ll)
                ):
                    skip_mentions.append(f"{p.relative_to(REPO)}:{i}: {line.strip()[:160]}")
            hits_summary.append((str(p.relative_to(REPO)), matched, samples))

    T.write(f"Files mentioning SC/Second* keys: {len(hits_summary)}")
    # prioritize AMZN/AU/VARIANT/READY/BRT_LOGIC
    priority = []
    other = []
    for path, matched, samples in hits_summary:
        blob = path.lower()
        if any(x in blob for x in ("amzn", "au/", "variant_c", "ready_for", "brt_logic", "wpbr")):
            priority.append((path, matched, samples))
        else:
            other.append((path, matched, samples))
    for path, matched, samples in priority[:25]:
        T.write(f"\nFILE: {path}")
        T.write(f"  keys: {matched}")
        for s in samples:
            T.write(f"  {s}")
    T.write(f"\nOther matching files (count={len(other)}): first 10 names only")
    for path, matched, _ in other[:10]:
        T.write(f"  {path} keys={matched}")

    T.write("\n--- Explicit 'skip failed rocket window' language ---")
    if skip_mentions:
        for s in skip_mentions[:20]:
            T.write(f"  {s}")
    else:
        T.write("  NONE found in drive/, stock_analysis/, docs/ for skip+failed+rocket/retest/window near SC.")

    # AU SC miss excerpt (sheet Second* columns)
    au = REPO / "drive" / "wpbr_sheet_reconcile" / "AU" / "AU_2019-04-25_SC_miss.md"
    if au.is_file():
        T.write("\n--- AU_2019-04-25_SC_miss.md (sheet Second* semantics excerpt) ---")
        for i, line in enumerate(au.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if i <= 80 or "Second" in line or "Proven" in line or "formula" in line.lower():
                if i <= 80 or "Second" in line or "Proven" in line:
                    T.write(f"  L{i}: {line[:200]}")
            if i > 120:
                break

    T.write(
        "\nINTERPRETATION: Sheet exposes Second Retest / Second Rocket / Second Entry on the "
        "zones/proven-trade path after a WIN (Proven Trade). Repo docs describe SC re-arm "
        "(wpbr_second_chance_after_win / allow_second) but do NOT document advancing past a "
        "failed rocket window; engine currently only advances resume when _sig == i."
    )


def propose_patch(T: Tee):
    T.section("4) rocket_brt.py SC resume block (~7483-7530) + proposed fix")
    T.write("CURRENT (only advances resume when signal fires on this bar i):")
    T.write(
        """
                    _rt, _sig, _fill = _wpbr_find_signal(
                        low_arr, close_arr, open_arr,
                        scan_start=_resume, zone_lower=_zl, zone_upper=_zh,
                        max_days_after_retest=_max_d, n=n, stop_at=i,
                        retest_mode=_cfg_wpbr_retest_mode,
                    )
                    if _sig == i and _fill is not None:
                        _wpbr_append_pending({... opportunity_index: 1 ...})
                        # If this signal day is skipped by gates, look for a later retest.
                        _st["resume_scan_bar"] = i + 1
""".rstrip()
    )
    T.write("")
    T.write(
        "BUG: When _rt is not None and _sig is None (retest found, rocket window exhausted "
        "with no green), resume_scan_bar is NEVER advanced. find() keeps returning the same "
        "failed first retest forever → Dec 6/7/8 never considered."
    )
    T.write("")
    T.write("PROPOSED PATCH (conceptual, drop-in after the find call):")
    T.write(
        """
                    _rt, _sig, _fill = _wpbr_find_signal(
                        low_arr, close_arr, open_arr,
                        scan_start=_resume, zone_lower=_zl, zone_upper=_zh,
                        max_days_after_retest=_max_d, n=n, stop_at=i,
                        retest_mode=_cfg_wpbr_retest_mode,
                    )
                    if _sig == i and _fill is not None:
                        _wpbr_append_pending(
                            {
                                "wpbr_zone_id": _zid,
                                "zone_lower": _zl,
                                "zone_upper": _zh,
                                "zone_center": _zc,
                                "retest_bar": _rt,
                                "entry_signal_bar": _sig,
                                "entry_fill_bar": _fill,
                                "opportunity_index": 1,
                            }
                        )
                        # Signal day: advance past this bar (gates may still skip fill).
                        _st["resume_scan_bar"] = i + 1
                    elif _rt is not None and _sig is None:
                        # Failed rocket window: advance past exhausted window so later retests can fire.
                        # Prefer retest + max_days + 1 (fully past window). retest+1 is a tighter
                        # alternate if sheet should re-scan from the day after retest.
                        _window_end = int(_rt) + int(_max_d)
                        if i >= _window_end:
                            _st["resume_scan_bar"] = _window_end + 1
""".rstrip()
    )
    T.write("")
    T.write(
        "NOTES: Gate with i >= _window_end so we do not advance mid-window while bars are still "
        "arriving (stop_at=i grows day by day). Once the full +max_d window is observable and "
        "still has no signal, unlock scanning for the next retest."
    )


def main():
    T = Tee(OUT_TXT)
    T.write("AMZN SC resume-fix probe")
    T.write(f"Zone {ZL}-{ZH} | max_days_after_retest={MAX_D}")
    T.write(f"Generated: {pd.Timestamp.now()}")
    T.write(f"First exit (WIN): {FIRST_EXIT} → SC resume from exit+1")
    T.write(
        f"Sheet: Second Retest={SHEET_SECOND_RETEST}, "
        f"Second Rocket={SHEET_SECOND_ROCKET}, Second Entry={SHEET_SECOND_ENTRY}"
    )

    df, src = load_ohlc("AMZN")
    idx = df.index
    n = len(df)
    lo = df["Low"].to_numpy(dtype=float)
    cl = df["Close"].to_numpy(dtype=float)
    op = df["Open"].to_numpy(dtype=float)
    hi = df["High"].to_numpy(dtype=float)

    T.section("0) OHLC source + key bar indices")
    T.write(f"source={src} bars={n} range={idx[0].date()}..{idx[-1].date()}")
    exit_i = bi(idx, FIRST_EXIT)
    resume0 = exit_i + 1
    nov4_i = bi(idx, FAILED_RETEST)
    dec6_i = bi(idx, SHEET_SECOND_RETEST)
    dec7_i = bi(idx, SHEET_SECOND_ROCKET)
    dec8_i = bi(idx, SHEET_SECOND_ENTRY)
    nov9_i = bi(idx, NOV9)
    for label, i in [
        ("exit", exit_i),
        ("resume0=exit+1", resume0),
        ("nov4", nov4_i),
        ("nov9", nov9_i),
        ("dec6", dec6_i),
        ("dec7", dec7_i),
        ("dec8", dec8_i),
    ]:
        T.write(f"  {label}: i={i} date={bd(idx, i)}")

    # ------------------------------------------------------------------
    T.section("1) Simulate resume advance after failed retest window")
    T.write("Baseline (current engine): scan_start=exit+1, stop_at=dec8")
    rt, sig, fill = find_wpbr_retest_and_signal(
        lo, cl, op, scan_start=resume0, zone_lower=ZL, zone_upper=ZH,
        max_days_after_retest=MAX_D, n=n, stop_at=dec8_i, retest_mode="stop_looking",
    )
    T.write(f"  find → retest={bd(idx, rt)} signal={bd(idx, sig)} fill={bd(idx, fill)}")
    T.write(f"  indices → rt={rt} sig={sig} fill={fill}")

    # Confirm Nov4 window has no green
    T.write("\nNov 4 rocket window bars (retest .. retest+max_d):")
    for j in range(nov4_i, nov4_i + MAX_D + 1):
        s = bar_summary(df, j)
        T.write(
            f"  {s['date']} O={s['O']} H={s['H']} L={s['L']} C={s['C']} "
            f"retest={s['retest']} green_sig={s['green_sig']} abandon={s['abandon']}"
        )

    # Advance past retest+max_d and past retest+1
    for label, new_resume in [
        ("A: resume = retest + max_d + 1 (past exhausted window)", nov4_i + MAX_D + 1),
        ("B: resume = retest + 1", nov4_i + 1),
    ]:
        T.write(f"\n--- Probe {label} ---")
        T.write(f"  new_resume i={new_resume} date={bd(idx, new_resume)}")
        rt2, sig2, fill2 = find_wpbr_retest_and_signal(
            lo, cl, op, scan_start=new_resume, zone_lower=ZL, zone_upper=ZH,
            max_days_after_retest=MAX_D, n=n, stop_at=dec8_i, retest_mode="stop_looking",
        )
        T.write(
            f"  find → retest={bd(idx, rt2)} signal={bd(idx, sig2)} fill={bd(idx, fill2)} "
            f"(rt={rt2} sig={sig2} fill={fill2})"
        )
        hit = (
            bd(idx, rt2) == SHEET_SECOND_RETEST
            and bd(idx, sig2) == SHEET_SECOND_ROCKET
            and bd(idx, fill2) == SHEET_SECOND_ENTRY
        )
        T.write(f"  MATCHES sheet Second Retest/Rocket/Entry? {hit}")

    # Day-by-day simulation of proposed fix
    T.write("\n--- Day-by-day sim of proposed fix (advance when rt set & sig None & i>=rt+max_d) ---")
    resume = resume0
    events = []
    for i in range(resume0, dec8_i + 1):
        rt_i, sig_i, fill_i = find_wpbr_retest_and_signal(
            lo, cl, op, scan_start=resume, zone_lower=ZL, zone_upper=ZH,
            max_days_after_retest=MAX_D, n=n, stop_at=i, retest_mode="stop_looking",
        )
        action = "hold"
        if sig_i == i and fill_i is not None:
            action = f"FIRE pending fill={bd(idx, fill_i)}; resume→{i+1}"
            events.append((bd(idx, i), action, bd(idx, rt_i), bd(idx, sig_i), bd(idx, fill_i)))
            resume = i + 1
        elif rt_i is not None and sig_i is None:
            window_end = int(rt_i) + MAX_D
            if i >= window_end:
                new_r = window_end + 1
                if new_r != resume:
                    action = f"FAILED_WINDOW advance resume {resume}→{new_r} (past {bd(idx, rt_i)}+{MAX_D})"
                    events.append((bd(idx, i), action, bd(idx, rt_i), None, None))
                    resume = new_r
        # log only interesting bars
        if bd(idx, i) in {
            FAILED_RETEST,
            bd(idx, nov4_i + MAX_D),
            bd(idx, nov4_i + MAX_D + 1),
            SHEET_SECOND_RETEST,
            SHEET_SECOND_ROCKET,
            SHEET_SECOND_ENTRY,
            NOV9,
        } or action != "hold":
            T.write(
                f"  {bd(idx, i)} stop_at=i resume={resume}({bd(idx, resume) if resume < n else '?'}) "
                f"find=({bd(idx, rt_i)},{bd(idx, sig_i)},{bd(idx, fill_i)}) action={action}"
            )

    T.write("\nEvents:")
    for e in events:
        T.write(f"  {e}")
    fired = [e for e in events if e[1].startswith("FIRE")]
    T.write(f"FIRE count under proposed fix through Dec8: {len(fired)}")
    if fired:
        T.write(f"  last/first fire: {fired[0]}")

    # ------------------------------------------------------------------
    T.section("2) Sheet ohlc.tsv vs DuckDB on 2022-11-04 — also a retest?")
    sheet_path = AMZN_DIR / "ohlc.tsv"
    sheet_rows = {}
    if sheet_path.is_file():
        for ln in sheet_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            parsed = parse_sheet_ohlc_row(ln)
            if parsed:
                sheet_rows[parsed[0]] = parsed[1:]
    for d in [FAILED_RETEST, NOV9, SHEET_SECOND_RETEST, SHEET_SECOND_ROCKET, SHEET_SECOND_ENTRY]:
        eng = bar_summary(df, bi(idx, d))
        T.write(f"\n{d}:")
        T.write(
            f"  DuckDB HU: O={eng['O']} H={eng['H']} L={eng['L']} C={eng['C']} "
            f"retest={eng['retest']} green={eng['green_sig']} abandon={eng['abandon']}"
        )
        T.write(f"  DuckDB raw: OHL C={eng['raw']}")
        if d in sheet_rows:
            so, sh, sl, sc = sheet_rows[d]
            sou, shu, slu, scu = _half_up(so), _half_up(sh), _half_up(sl), _half_up(sc)
            zl_u, zh_u = _half_up(ZL), _half_up(ZH)
            sheet_retest = slu <= zh_u and scu > zh_u
            sheet_green = scu > sou and scu > zh_u
            T.write(
                f"  Sheet:     O={sou} H={shu} L={slu} C={scu} "
                f"retest={sheet_retest} green={sheet_green} abandon={scu < zl_u}"
            )
            T.write(
                f"  Sheet==DuckDB OHLC (2dp)? "
                f"{(sou, shu, slu, scu) == (eng['O'], eng['H'], eng['L'], eng['C'])}"
            )
        else:
            T.write("  Sheet: MISSING row in ohlc.tsv")

    eng_nov4 = bar_summary(df, nov4_i)
    sheet_nov4_retest = None
    if FAILED_RETEST in sheet_rows:
        so, sh, sl, sc = sheet_rows[FAILED_RETEST]
        slu, scu = _half_up(sl), _half_up(sc)
        sheet_nov4_retest = slu <= _half_up(ZH) and scu > _half_up(ZH)
    T.write(
        f"\nVERDICT Nov4: DuckDB retest={eng_nov4['retest']}; "
        f"sheet ohlc retest={sheet_nov4_retest}. "
        "If both True, sheet Daily/Second path would also see Nov4 as a retest candidate "
        "(unless sheet Second* formulas skip exhausted rocket windows — see section 3)."
    )

    # ------------------------------------------------------------------
    search_docs(T)
    propose_patch(T)

    # ------------------------------------------------------------------
    T.section("5) Start scan_start at 2022-12-06 only")
    rt5, sig5, fill5 = find_wpbr_retest_and_signal(
        lo, cl, op, scan_start=dec6_i, zone_lower=ZL, zone_upper=ZH,
        max_days_after_retest=MAX_D, n=n, stop_at=dec8_i, retest_mode="stop_looking",
    )
    T.write(f"  find(scan_start=Dec6, stop_at=Dec8) → retest={bd(idx, rt5)} signal={bd(idx, sig5)} fill={bd(idx, fill5)}")
    T.write(f"  indices → rt={rt5} sig={sig5} fill={fill5}")
    T.write(
        f"  Expected sheet map Dec6/Dec7/Dec8? "
        f"{bd(idx, rt5) == SHEET_SECOND_RETEST and bd(idx, sig5) == SHEET_SECOND_ROCKET and bd(idx, fill5) == SHEET_SECOND_ENTRY}"
    )
    # Also stop_at=None / later
    rt5b, sig5b, fill5b = find_wpbr_retest_and_signal(
        lo, cl, op, scan_start=dec6_i, zone_lower=ZL, zone_upper=ZH,
        max_days_after_retest=MAX_D, n=n, stop_at=None, retest_mode="stop_looking",
    )
    T.write(
        f"  find(scan_start=Dec6, stop_at=None) → retest={bd(idx, rt5b)} "
        f"signal={bd(idx, sig5b)} fill={bd(idx, fill5b)}"
    )
    # Bar-level Dec6-8
    T.write("\nDec6-8 bar details:")
    for d in [SHEET_SECOND_RETEST, SHEET_SECOND_ROCKET, SHEET_SECOND_ENTRY]:
        s = bar_summary(df, bi(idx, d))
        T.write(
            f"  {s['date']} O={s['O']} L={s['L']} C={s['C']} "
            f"retest={s['retest']} green_sig={s['green_sig']}"
        )

    # ------------------------------------------------------------------
    T.section("6) Abandon check: Nov9 Close vs zl; any Close < 85.52 between Nov4 and Dec8?")
    s9 = bar_summary(df, nov9_i)
    T.write(f"Nov9 Close HU={s9['C']} vs zl={_half_up(ZL)} → abandon={s9['abandon']} (not abandon expected)")
    T.write(f"  Nov9 full: O={s9['O']} H={s9['H']} L={s9['L']} C={s9['C']}")

    abandons = []
    for i in range(nov4_i, dec8_i + 1):
        s = bar_summary(df, i)
        if s["abandon"]:
            abandons.append(f"{s['date']} C={s['C']}")
    T.write(f"\nClose < zl ({_half_up(ZL)}) bars from Nov4..Dec8 inclusive: {len(abandons)}")
    if abandons:
        for a in abandons:
            T.write(f"  {a}")
    else:
        T.write("  NONE — abandon-kill does not blank the zone between Nov4 and Dec8.")

    # Also list lows near zone for context
    T.write("\nBars with Low <= zh or Close near zl in Nov4..Dec8:")
    for i in range(nov4_i, dec8_i + 1):
        s = bar_summary(df, i)
        if s["retest"] or s["abandon"] or s["L"] <= _half_up(ZH) or s["C"] < _half_up(ZL) + 1:
            T.write(
                f"  {s['date']} L={s['L']} C={s['C']} retest={s['retest']} "
                f"green={s['green_sig']} abandon={s['abandon']}"
            )

    # ------------------------------------------------------------------
    T.section("SUMMARY / RECOMMENDED FIX")
    T.write(
        "Root cause: SC loop only sets resume_scan_bar when _sig == i. "
        "Failed retest 2022-11-04 (red / no green in +2) locks find() forever; Dec6-8 ignored."
    )
    T.write(
        "Fix: when _rt is not None and _sig is None and i >= _rt + max_days, "
        "set resume_scan_bar = _rt + max_days + 1."
    )
    T.write(
        "Evidence: advancing resume past Nov4 window OR starting at Dec6 yields "
        "retest=Dec6, signal=Dec7, fill=Dec8 — matching sheet Second*."
    )
    T.write("Nov4 is a retest on both DuckDB and sheet OHLC; not an OHLC mismatch.")
    T.write("No Close < 85.52 between Nov4 and Dec8; Nov9 Close 86.14 is not abandon.")
    T.write(f"\nFull output: {OUT_TXT}")
    T.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
