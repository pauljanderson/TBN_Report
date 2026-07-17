from __future__ import annotations

import numpy as np
import pandas as pd


# Source of "which dates are worst" (from the earlier AR-mismatch run).
AR_MISMATCH_FILTERED_CSV = (
    r"C:\Users\songg\Downloads\stockresearch\drive\BRT_SheetGateParity_AR_Mismatch_recent_CDmatch_only_NVDA.csv"
)

# Latest python parity dump that includes DE/DF/DG alongside DL/DM/DN.
PY_PARITY_LATEST_CSV = r"C:\Users\songg\Downloads\stockresearch\drive\BRT_SheetGateParity_NVDA_260326164157.csv"

SHEET_CSV = r"C:\Users\songg\Downloads\Rocket Launcher Key Levels_BRT Mark working - STONK_DATA 3.0 (2).csv"


def _fmt(x) -> str:
    if pd.isna(x):
        return "nan"
    return str(round(float(x), 4))


def main() -> None:
    m = pd.read_csv(AR_MISMATCH_FILTERED_CSV)
    m["DATE"] = pd.to_datetime(m["DATE"], errors="coerce")

    # Worst AR undercounts from the mismatch-filtered set:
    sel_dates: list[pd.Timestamp] = []
    for d in [-4, -3]:
        sub = m[m["AR_diff"] == d].sort_values("DATE")
        sel_dates += (sub["DATE"].tolist() if d == -4 else sub["DATE"].head(8).tolist())

    # Unique dates, stable order
    seen: set[str] = set()
    dates: list[pd.Timestamp] = []
    for dt in sel_dates:
        key = dt.strftime("%Y-%m-%d")
        if key not in seen:
            seen.add(key)
            dates.append(dt)

    p = pd.read_csv(PY_PARITY_LATEST_CSV)
    p["DATE"] = pd.to_datetime(p["DATE"], errors="coerce")

    s = pd.read_csv(SHEET_CSV)
    s["DATE"] = pd.to_datetime(s["Date"], errors="coerce")
    s["Active zone lower"] = pd.to_numeric(
        s["Active zone lower"].astype(str).str.replace("[$,]", "", regex=True), errors="coerce"
    )
    s["Active zone upper"] = pd.to_numeric(
        s["Active zone upper"].astype(str).str.replace("[$,]", "", regex=True), errors="coerce"
    )
    s["Active zone available row"] = pd.to_numeric(s["Active zone available row"], errors="coerce")
    s["Long window Rolling touch count "] = pd.to_numeric(
        s["Long window Rolling touch count "], errors="coerce"
    )

    sheet_map = s.set_index(s["DATE"].dt.strftime("%Y-%m-%d"))
    py_map = p.set_index(p["DATE"].dt.strftime("%Y-%m-%d"))

    print(
        "DATE | AR_py | AR_sheet | "
        "DE/DF/DG (raw) | DL/DM/DN (asof) | "
        "Sheet zone (low/high/DG) | Key Notes"
    )
    for dt in dates:
        dts = dt.strftime("%Y-%m-%d")
        if dts not in py_map.index or dts not in sheet_map.index:
            continue

        pr = py_map.loc[dts]
        sr = sheet_map.loc[dts]

        # Extract python parity cols (raw ladder and gated/as-of)
        DE, DF, DG = pr.get("DE", np.nan), pr.get("DF", np.nan), pr.get("DG", np.nan)
        DL, DM, DN = pr.get("DL", np.nan), pr.get("DM", np.nan), pr.get("DN", np.nan)
        AR = pr.get("AR", np.nan)

        # Extract sheet cols
        dl_s = sr.get("Active zone lower", np.nan)
        dm_s = sr.get("Active zone upper", np.nan)
        dg_s = sr.get("Active zone available row", np.nan)
        ARs = sr.get("Long window Rolling touch count ", np.nan)

        notes: list[str] = []
        if pd.isna(DL) and pd.notna(dl_s):
            notes.append("DL_py blank while sheet zone present")
        if pd.notna(DL) and pd.notna(dl_s) and abs(float(DL) - float(dl_s)) > 1e-6:
            notes.append("DL differs from sheet low")
        if pd.isna(DM) and pd.notna(dm_s):
            notes.append("DM_py blank while sheet zone present")
        if pd.notna(DM) and pd.notna(dm_s) and abs(float(DM) - float(dm_s)) > 1e-6:
            notes.append("DM differs from sheet high")
        if pd.notna(DN) and pd.notna(dg_s) and abs(float(DN) - float(dg_s)) > 1e-6:
            notes.append("DN differs from sheet DG")

        print(
            "{} | {} | {} | "
            "DE/DF/DG={} , {} , {} | DL/DM/DN={} , {} , {} | "
            "sheetLow/High/DG={} , {} , {} | {}".format(
                dts,
                int(round(float(AR))) if pd.notna(AR) else -1,
                int(round(float(ARs))) if pd.notna(ARs) else -1,
                _fmt(DE),
                _fmt(DF),
                _fmt(DG),
                _fmt(DL),
                _fmt(DM),
                _fmt(DN),
                _fmt(dl_s),
                _fmt(dm_s),
                _fmt(dg_s),
                "; ".join(notes),
            )
        )


if __name__ == "__main__":
    main()

