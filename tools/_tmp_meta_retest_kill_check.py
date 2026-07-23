"""Check sheet Daily Retest Row kill-window vs engine for 7 META mismatches."""
from __future__ import annotations

from io import StringIO
from pathlib import Path

import pandas as pd

base = Path(r"C:\Users\songg\Downloads\stockresearch\drive\wpbr_sheet_reconcile\META")

lines = (base / "ohlc.tsv").read_text(encoding="utf-8").splitlines()
start = next(i for i, l in enumerate(lines) if l.startswith("Date\t"))
ohlc = pd.read_csv(StringIO("\n".join(lines[start:])), sep="\t")
ohlc["Date"] = pd.to_datetime(ohlc["Date"])
for c in ["Open", "High", "Low", "Close"]:
    ohlc[c] = ohlc[c].astype(str).str.replace("$", "", regex=False).astype(float)
ohlc = ohlc.reset_index(drop=True)
ohlc["sheet_row"] = ohlc.index + 2  # sheet row 2 = first data bar

zones = pd.read_csv(base / "zones.tsv", sep="\t")
for c in ["Zone Lower", "Zone Upper"]:
    zones[c] = zones[c].astype(str).str.replace("$", "", regex=False).astype(float)
for c in [
    "Pivot Date",
    "Breakout Date",
    "Conf Week Date",
    "Next week start date",
    "Daily Retest Date",
    "Rocket Buy Date",
]:
    if c in zones.columns:
        zones[c] = pd.to_datetime(zones[c], errors="coerce")

cases = [
    dict(
        n=1,
        pivot="2017-07-24",
        lower=172.86,
        upper=178.12,
        next_start="2017-12-04",
        eng_retest="2017-12-07",
    ),
    dict(
        n=2,
        pivot="2018-01-29",
        lower=192.39,
        upper=198.25,
        next_start="2018-07-16",
        eng_retest="2019-07-09",
    ),
    dict(
        n=3,
        pivot="2019-02-04",
        lower=169.88,
        upper=175.06,
        next_start="2019-04-22",
        eng_retest="2019-06-13",
    ),
    dict(
        n=4,
        pivot="2019-04-22",
        lower=195.50,
        upper=201.46,
        next_start="2019-07-29",
        eng_retest="2019-11-27",
    ),
    dict(
        n=5,
        pivot="2019-07-22",
        lower=205.53,
        upper=211.79,
        next_start="2020-01-13",
        eng_retest="2020-02-07",
    ),
    dict(
        n=6,
        pivot="2024-04-08",
        lower=523.52,
        upper=539.46,
        next_start="2024-09-23",
        eng_retest="2025-04-10",
    ),
    dict(
        n=7,
        pivot="2024-10-07",
        lower=593.91,
        upper=611.99,
        next_start="2024-12-16",
        eng_retest="2025-01-06",
    ),
]


def sheet_retest_row(bk, zl, zu):
    """Simulate sheet Daily Retest Row formula.

    INDEX(FILTER(ROW, D>=BK, G<=BD, H>BD,
                 ROW < IFERROR(INDEX(FILTER(ROW, D>=BK, H<BC),1),3001)), 1)
    BC=zl, BD=zu, BK=next_week_start
    """
    abandon = ohlc[(ohlc["Date"] >= bk) & (ohlc["Close"] < zl)]
    if len(abandon):
        cap_row = int(abandon.iloc[0]["sheet_row"])
        abandon_dt = abandon.iloc[0]["Date"]
    else:
        cap_row = 3001
        abandon_dt = None
    cands = ohlc[
        (ohlc["Date"] >= bk)
        & (ohlc["Low"] <= zu)
        & (ohlc["Close"] > zu)
        & (ohlc["sheet_row"] < cap_row)
    ]
    if len(cands):
        r = cands.iloc[0]
        return int(r["sheet_row"]), r["Date"], cap_row, abandon_dt
    return None, None, cap_row, abandon_dt


def engine_retest(bk, zl, zu):
    """Engine: Low<=upper & Close>upper & prior Close>=lower, unbounded from BK."""
    start_idx = ohlc.index[ohlc["Date"] >= bk]
    if len(start_idx) == 0:
        return None, None
    for i in range(int(start_idx[0]), len(ohlc)):
        if i <= 0:
            continue
        if ohlc.loc[i, "Low"] <= zu + 1e-9 and ohlc.loc[i, "Close"] > zu + 1e-9:
            if ohlc.loc[i - 1, "Close"] >= zl - 1e-9:
                return int(ohlc.loc[i, "sheet_row"]), ohlc.loc[i, "Date"]
    return None, None


print("OHLC bars:", len(ohlc), "from", ohlc.Date.min().date(), "to", ohlc.Date.max().date())
print()

for c in cases:
    pivot = pd.Timestamp(c["pivot"])
    zrow = zones[zones["Pivot Date"] == pivot]
    if len(zrow) == 0:
        print(f"CASE {c['n']}: pivot {c['pivot']} NOT FOUND in zones")
        continue
    z = zrow.iloc[0]
    zl = float(z["Zone Lower"])
    zu = float(z["Zone Upper"])
    bk = z["Next week start date"]
    sheet_rt = z["Daily Retest Date"]
    sheet_rt_row = z["Daily Retest Row"]

    srow, sdate, cap, abandon_dt = sheet_retest_row(bk, zl, zu)
    erow, edate = engine_retest(bk, zl, zu)

    eng_dt = pd.Timestamp(c["eng_retest"])
    between = ohlc[(ohlc["Date"] >= bk) & (ohlc["Date"] < eng_dt) & (ohlc["Close"] < zl)]

    # Also: any wick-hold candidates before abandon that sheet would miss due to prior-close?
    print(f"=== CASE #{c['n']} pivot={c['pivot']} zone={zl:.2f}-{zu:.2f} ===")
    print(f"  sheet Next-wk-start={bk.date()} sheet_retest={sheet_rt} row={sheet_rt_row}")
    print(f"  expected eng retest={c['eng_retest']}")
    print(
        f"  SIM sheet: row={srow} date={None if sdate is None else sdate.date()} "
        f"cap_row={cap} first_abandon={None if abandon_dt is None else abandon_dt.date()}"
    )
    print(f"  SIM engine: row={erow} date={None if edate is None else edate.date()}")
    print(f"  Close<lower bars BEFORE eng retest (count={len(between)}):")
    if len(between):
        for _, r in between.head(8).iterrows():
            print(
                f"    {r['Date'].date()} Close={r['Close']:.2f} < lower={zl:.2f} "
                f"(row {int(r['sheet_row'])})"
            )
        if len(between) > 8:
            print(f"    ... +{len(between) - 8} more")
    else:
        print("    (none)")

    if c["n"] == 1:
        win = ohlc[(ohlc["Date"] >= bk) & (ohlc["Date"] <= eng_dt + pd.Timedelta(days=2))]
        print("  OHLC window BK->eng+2:")
        for _, r in win.iterrows():
            flags = []
            if r["Close"] < zl:
                flags.append("CLOSE<LOWER")
            if r["Low"] <= zu and r["Close"] > zu:
                flags.append("WICK_HOLD")
            prev = ohlc.loc[r.name - 1, "Close"] if r.name > 0 else None
            if prev is not None and prev >= zl:
                flags.append(f"priorOK({prev:.2f})")
            elif prev is not None:
                flags.append(f"priorFAIL({prev:.2f})")
            print(
                f"    {r['Date'].date()} O={r['Open']:.2f} H={r['High']:.2f} "
                f"L={r['Low']:.2f} C={r['Close']:.2f}  {' '.join(flags)}"
            )
    print()

# Cross-check: for all 48 zones, does sheet sim match pasted Daily Retest Date?
print("=== Full 48-zone sheet-sim vs pasted Daily Retest Date ===")
match = miss_blank = miss_date = 0
for _, z in zones.iterrows():
    zl = float(z["Zone Lower"])
    zu = float(z["Zone Upper"])
    bk = z["Next week start date"]
    pasted = z["Daily Retest Date"]
    srow, sdate, cap, abandon_dt = sheet_retest_row(bk, zl, zu)
    if pd.isna(pasted) and sdate is None:
        match += 1
    elif pd.isna(pasted) and sdate is not None:
        miss_blank += 1
        print(f"  pasted BLANK but sim={sdate.date()} pivot={z['Pivot Date'].date()} cap={cap}")
    elif not pd.isna(pasted) and sdate is None:
        miss_date += 1
        print(f"  pasted={pasted.date()} but sim=BLANK pivot={z['Pivot Date'].date()} cap={cap}")
    elif pasted.normalize() == sdate.normalize():
        match += 1
    else:
        miss_date += 1
        print(
            f"  DATE DIFF pasted={pasted.date()} sim={sdate.date()} "
            f"pivot={z['Pivot Date'].date()}"
        )
print(f"match={match} pasted_blank_sim_has={miss_blank} date_mismatch={miss_date}")
