from __future__ import annotations

import pandas as pd


NVDA_CSV = r"C:/Users/songg/Downloads/stockresearch/data/newdata/data/NVDA.csv"
PARITY_CSV = r"C:/Users/songg/Downloads/stockresearch/drive/BRT_SheetGateParity_NVDA_260326164157.csv"


def main() -> None:
    nv = pd.read_csv(NVDA_CSV)
    nv["Date"] = pd.to_datetime(nv["Date"], errors="coerce")
    nv_map = {d.strftime("%Y-%m-%d"): i for i, d in enumerate(nv["Date"])}

    p = pd.read_csv(PARITY_CSV)
    # parity dump already has DATE as YYYY-MM-DD strings
    for d in ["2022-08-01", "2022-08-02", "2019-07-18", "2019-08-30", "2019-09-10"]:
        row = p[p["DATE"] == d].iloc[0]
        dg = float(row["DG"]) if pd.notna(row["DG"]) else float("nan")
        i = nv_map[d]
        print(f"{d}: i={i} DG={dg} i-DG={i-dg} pass_if_(i-DG)>=7? {(i-dg)>=7}")


if __name__ == "__main__":
    main()

