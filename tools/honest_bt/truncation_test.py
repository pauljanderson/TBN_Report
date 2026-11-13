#!/usr/bin/env python3
"""Truncation test: does any system's backtest use data from after the trade?

A backtest without look-ahead decides each trade only from bars up to that trade. So if we cut the
data off at date C and rerun, every trade OPENED BEFORE C must be identical to the full run (same
symbol, same open date, same entry price), and every trade CLOSED BEFORE C must close the same way.
Any difference means the full run used bars after C to make a decision before C. It also measures
backtest-vs-live consistency: live always runs at the end of the data, like the cut run.

Steps (each is resumable):
  prepare  sample N symbols (fixed seed) from data/pit_daily, write data/trunc/full and
           data/trunc/cut_<YYYYMMDD> (rows <= cut) for each cut date. SPY always included.
  run      every system on every data dir through run_honest.py (production launchers, preflight,
           drive-root guard): drive/honest_bt/<stamp>/trunc/<label>/<SYS>/
  compare  per system and cut: entries before the cut found only in the full run / only in the cut
           run / with a different entry price; closes before the cut that differ.
           Writes drive/honest_bt/<stamp>/trunc/truncation_report.csv and exits 1 if any system leaks.

  python tools/honest_bt/truncation_test.py prepare --n 500
  python tools/honest_bt/truncation_test.py run --stamp 20261113
  python tools/honest_bt/truncation_test.py compare --stamp 20261113
"""
from __future__ import annotations

import argparse
import random
import subprocess
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
from run_honest import SYSTEMS  # noqa: E402

SRC = REPO / "data" / "pit_daily"
TRUNC = REPO / "data" / "trunc"
CUTS = ["2020-06-30", "2021-09-30", "2022-12-30", "2024-03-28", "2025-06-30", "2026-08-31"]


def labels(cuts: list[str]) -> list[str]:
    return ["full"] + [f"cut_{c.replace('-', '')}" for c in cuts]


def prepare(n: int, seed: int, cuts: list[str]) -> None:
    syms = sorted(p.stem for p in SRC.glob("*.csv") if not p.stem.startswith("_") and p.stem != "SPY")
    pick = sorted(random.Random(seed).sample(syms, min(n, len(syms)))) + ["SPY"]
    for lab, cut in [("full", None)] + [(f"cut_{c.replace('-', '')}", c) for c in cuts]:
        d = TRUNC / lab
        d.mkdir(parents=True, exist_ok=True)
        for s in pick:
            src = (SRC / f"{s}.csv").read_text().splitlines(keepends=True)
            if cut is None:
                keep = src
            else:
                keep = [src[0]] + [ln for ln in src[1:] if ln[:10] <= cut]
            if len(keep) > 1:
                (d / f"{s}.csv").write_text("".join(keep))
        print(f"[trunc] {lab}: {len(list(d.glob('*.csv')))} files", flush=True)
    (TRUNC / "_symbols.txt").write_text("\n".join(pick) + "\n")


def run(stamp: str, systems: list[str], cuts: list[str]) -> int:
    rc = 0
    for lab in labels(cuts):
        cmd = [sys.executable, str(HERE / "run_honest.py"), "--variant", "custom", "--data-dir", f"data/trunc/{lab}",
               "--stamp", stamp, "--tag", f"trunc/{lab}", "--systems", ",".join(systems)]
        print(f"[trunc] running {lab}", flush=True)
        rc |= subprocess.call(cmd)
    return rc


def _trades(run_dir: Path, sys_code: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(entries from Closed+Open, closed trades) for one engine output dir."""
    def latest(kind):
        hits = [h for h in sorted(run_dir.glob(f"{sys_code}_{kind}_*.csv")) if h.stem.split(f"_{kind}_")[1].isdigit()]
        return pd.read_csv(hits[-1], low_memory=False) if hits else pd.DataFrame()
    c, o = latest("Closed"), latest("Open")
    def norm(df, closed):
        if df.empty:
            return pd.DataFrame({"symbol": pd.Series(dtype=str), "opened": pd.Series(dtype="datetime64[ns]"),
                                 "entry": pd.Series(dtype=float), "closed": pd.Series(dtype="datetime64[ns]"),
                                 "exit": pd.Series(dtype=float)})
        df.columns = [x.strip().upper().replace(" ", "_") for x in df.columns]
        out = pd.DataFrame({"symbol": df["SYMBOL"].astype(str).str.upper().str.strip(),
                            "opened": pd.to_datetime(df["DATE_OPENED"].astype(str).str[:8], format="%Y%m%d", errors="coerce"),
                            "entry": pd.to_numeric(df.get("ENTRY_PRICE"), errors="coerce").round(2)})
        if closed:
            out["closed"] = pd.to_datetime(df["DATE_CLOSED"].astype(str).str[:8], format="%Y%m%d", errors="coerce")
            out["exit"] = pd.to_numeric(df.get("EXIT_PRICE"), errors="coerce").round(2)
        out["opened"] = out["opened"].astype("datetime64[ns]")
        return out.dropna(subset=["opened"])
    cl = norm(c, True)
    entries = pd.concat([cl[["symbol", "opened", "entry"]], norm(o, False)[["symbol", "opened", "entry"]]], ignore_index=True)
    return entries, cl


def compare(stamp: str, systems: list[str], cuts: list[str]) -> int:
    root = REPO / "drive" / "honest_bt" / stamp / "trunc"
    rows = []
    for s in systems:
        full_e, full_c = _trades(root / "full" / s, s)
        for c in cuts:
            cut = pd.Timestamp(c)
            ce, cc = _trades(root / f"cut_{c.replace('-', '')}" / s, s)
            fe = full_e[full_e.opened < cut]
            ce = ce[ce.opened < cut]
            kf = set(zip(fe.symbol, fe.opened))
            kc = set(zip(ce.symbol, ce.opened))
            both = fe.merge(ce, on=["symbol", "opened"], suffixes=("_f", "_c"))
            px = int(((both.entry_f - both.entry_c).abs() > 0.011).sum())
            fcl = full_c[full_c.closed < cut]
            ccl = cc[cc.closed < cut]
            m = fcl.merge(ccl, on=["symbol", "opened"], how="outer", suffixes=("_f", "_c"), indicator=True)
            exit_diff = int((m["_merge"] != "both").sum() + ((m["_merge"] == "both") & (
                (m.closed_f != m.closed_c) | ((m.exit_f - m.exit_c).abs() > 0.011))).sum())
            rows.append({"system": s, "cut": c, "entries_full": len(kf), "entries_cut": len(kc),
                         "only_full": len(kf - kc), "only_cut": len(kc - kf), "entry_px_diff": px,
                         "exit_diff": exit_diff,
                         "leak": bool((kf ^ kc) or px or exit_diff)})
            for k in sorted(kf - kc)[:3]:
                rows[-1].setdefault("examples_only_full", "")
                rows[-1]["examples_only_full"] += f"{k[0]}@{k[1].date()} "
            for k in sorted(kc - kf)[:3]:
                rows[-1].setdefault("examples_only_cut", "")
                rows[-1]["examples_only_cut"] += f"{k[0]}@{k[1].date()} "
    df = pd.DataFrame(rows)
    df.to_csv(root / "truncation_report.csv", index=False)
    print(df.drop(columns=[c for c in df.columns if c.startswith("examples")]).to_string(index=False))
    summ = df.groupby("system").agg(cuts=("cut", "size"), leaks=("leak", "sum"), only_full=("only_full", "sum"),
                                    only_cut=("only_cut", "sum"), px=("entry_px_diff", "sum"), exits=("exit_diff", "sum"))
    print("\n" + summ.to_string())
    bad = summ[summ.leaks > 0].index.tolist()
    print(f"\n{'LEAK: ' + ', '.join(bad) if bad else 'clean: no system changed any pre-cut trade'}")
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["prepare", "run", "compare"])
    ap.add_argument("--stamp", default=pd.Timestamp.now().strftime("%Y%m%d"))
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--seed", type=int, default=20261113)
    ap.add_argument("--cuts", default=",".join(CUTS))
    ap.add_argument("--systems", default=",".join(SYSTEMS))
    a = ap.parse_args(argv)
    cuts = [c.strip() for c in a.cuts.split(",") if c.strip()]
    systems = [s.strip().upper() for s in a.systems.split(",") if s.strip()]
    if a.step == "prepare":
        prepare(a.n, a.seed, cuts)
        return 0
    if a.step == "run":
        return run(a.stamp, systems, cuts)
    return compare(a.stamp, systems, cuts)


if __name__ == "__main__":
    raise SystemExit(main())
