from __future__ import annotations

import numpy as np
import pandas as pd


PY_CSV = (
    r"C:\Users\songg\Downloads\stockresearch\drive\BRT_SheetGateParity_AR_Mismatch_recent_CDmatch_only_NVDA.csv"
)
SHEET_CSV = (
    r"C:\Users\songg\Downloads\Rocket Launcher Key Levels_BRT Mark working - STONK_DATA 3.0 (2).csv"
)


def _fmt(x) -> str:
    if pd.isna(x):
        return "nan"
    return str(round(float(x), 4))


def main() -> None:
    m = pd.read_csv(PY_CSV)
    m["DATE"] = pd.to_datetime(m["DATE"], errors="coerce")

    # Debug targets: worst AR undercounts (AR_diff is AR - AR_sheet).
    sel = []
    for d in [-4, -3]:
        sub = m[m["AR_diff"] == d].sort_values("DATE")
        sel += (sub["DATE"].tolist() if d == -4 else sub["DATE"].head(8).tolist())

    seen = set()
    dates: list[pd.Timestamp] = []
    for dt in sel:
        key = dt.strftime("%Y-%m-%d")
        if key not in seen:
            seen.add(key)
            dates.append(dt)

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

    print(
        "DATE | AR_py | AR_sheet | DL_py | DM_py | DN_py | "
        "DL_sheet | DM_sheet | DG_sheet | Notes"
    )
    for dt in dates:
        dts = dt.strftime("%Y-%m-%d")
        row = m[m["DATE"].dt.strftime("%Y-%m-%d") == dts].iloc[0]

        DL = float(row["DL"]) if pd.notna(row["DL"]) else np.nan
        DM = float(row["DM"]) if pd.notna(row["DM"]) else np.nan
        DN = float(row["DN"]) if pd.notna(row["DN"]) else np.nan
        AR = float(row["AR"]) if pd.notna(row["AR"]) else np.nan
        ARs = float(row["AR_sheet"]) if pd.notna(row["AR_sheet"]) else np.nan

        dl_s = dm_s = dg_s = np.nan
        notes: list[str] = []
        if dts in sheet_map.index:
            sr = sheet_map.loc[dts]
            dl_s = float(sr.get("Active zone lower", np.nan)) if pd.notna(sr.get("Active zone lower", np.nan)) else np.nan
            dm_s = float(sr.get("Active zone upper", np.nan)) if pd.notna(sr.get("Active zone upper", np.nan)) else np.nan
            dg_s = float(sr.get("Active zone available row", np.nan)) if pd.notna(sr.get("Active zone available row", np.nan)) else np.nan

            if pd.isna(DL) and pd.isna(dl_s):
                notes.append("DL blank both")
            elif pd.isna(DL) and pd.notna(dl_s):
                notes.append("DL_py blank, DL_sheet present")
            elif pd.notna(DL) and pd.isna(dl_s):
                notes.append("DL_py present, DL_sheet blank")

            if pd.notna(DL) and pd.notna(dl_s):
                notes.append(f"DL_diff={DL - dl_s:.4f}")
            if pd.notna(DM) and pd.notna(dm_s):
                notes.append(f"DM_diff={DM - dm_s:.4f}")
        else:
            notes.append("date missing from sheet export")

        print(
            "{} | {} | {} | {} | {} | {} | {} | {} | {} | {}".format(
                dts,
                int(round(AR)) if pd.notna(AR) else -1,
                int(round(ARs)) if pd.notna(ARs) else -1,
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

