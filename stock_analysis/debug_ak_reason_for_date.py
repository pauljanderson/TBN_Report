from __future__ import annotations

import numpy as np
import pandas as pd


NVDA_CSV = r"C:/Users/songg/Downloads/stockresearch/data/newdata/data/NVDA.csv"
PARITY_CSV = r"C:/Users/songg/Downloads/stockresearch/drive/BRT_SheetGateParity_NVDA_260326165702.csv"

TARGET_DATE = "2022-12-01"

# Must match the config used to generate PARITY_CSV.
ASOF_LAG = 7
AGE_ADJUST = 7


def _fmt(x) -> str:
    if pd.isna(x):
        return "nan"
    if isinstance(x, (float, np.floating)):
        return f"{x:.6f}".rstrip("0").rstrip(".") if abs(x) > 0 else "0"
    return str(x)


def main() -> None:
    df = pd.read_csv(NVDA_CSV)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.sort_values("Date").reset_index(drop=True)

    par = pd.read_csv(PARITY_CSV)
    par["DATE"] = pd.to_datetime(par["DATE"], errors="coerce")

    i_rows = df.index[df["Date"].dt.strftime("%Y-%m-%d") == TARGET_DATE].tolist()
    if not i_rows:
        print(f"Target date {TARGET_DATE} not found in NVDA.csv")
        return
    i = int(i_rows[0])

    p_rows = par.index[par["DATE"].dt.strftime("%Y-%m-%d") == TARGET_DATE].tolist()
    if not p_rows:
        print(f"Target date {TARGET_DATE} not found in parity dump")
        return

    p = par.loc[p_rows[0]]

    low = float(df.loc[i, "Low"])
    high = float(df.loc[i, "High"])
    close_prev = float(df.loc[i - 1, "Close"]) if i - 1 >= 0 else float("nan")

    zl = float(p["DE"]) if pd.notna(p["DE"]) else float("nan")
    zu = float(p["DF"]) if pd.notna(p["DF"]) else float("nan")
    dg = int(float(p["DG"])) if pd.notna(p["DG"]) else -1

    ok_zone = (
        np.isfinite(zl)
        and np.isfinite(zu)
        and zl > 0
        and zu > 0
        and dg >= 0
        and (((i - dg) + AGE_ADJUST) >= ASOF_LAG)
    )

    # rocket_brt AK logic:
    # ok = zone_ctx_at(i)[0] AND i > dg_j
    i_gt_dg = i > dg
    overlap = bool((low <= zu) and (high >= zl))
    close_ok = bool(np.isfinite(close_prev) and (close_prev > zu))

    ak_engine = bool(p["AK"]) if "AK" in p else None
    ak_recalc = bool(ok_zone and i_gt_dg and overlap and close_ok)

    print(f"Date={TARGET_DATE} bar_i={i}")
    print(f"parity AK={ak_engine}  (recalc={ak_recalc})")
    print(f"DE/DF/DG(raw) = { _fmt(zl)} / {_fmt(zu)} / {_fmt(dg)}")
    print(f"ASOF check: (i-dg)+AGE_ADJUST >= ASOF_LAG  -> {(i - dg) + AGE_ADJUST} >= {ASOF_LAG}")
    print(f"ok_zone={ok_zone} i>DG={i_gt_dg} overlap(Low/High vs [DE,DF])={overlap} close_prev(>DF)={close_ok}")
    print(f"Low={low:.4f} High={high:.4f} close_prev={close_prev:.4f} DF(zu)={zu:.4f}")


if __name__ == "__main__":
    main()

