#!/usr/bin/env python3
"""Prove AMZN 2022-12-08 sheet-only phantom vs startfloor stamp 260722161242."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(r"C:\Users\songg\Downloads\stockresearch")
sys.path.insert(0, str(REPO / "stock_analysis"))
from wpbr_zones import compute_wpbr_touch_stream  # noqa: E402

AMZN = REPO / "drive" / "wpbr_sheet_reconcile" / "AMZN"
STAMP = (
    REPO
    / "drive"
    / "wpbr_sheet_reconcile"
    / "_markten_variantC_SC_stop91_startfloor_2016_20260722161052"
)
ST = "260722161242"
TARGET = "2022-12-08"


def read_text(p: Path) -> str:
    b = p.read_bytes()
    if b[:2] in (b"\xff\xfe", b"\xfe\xff") or (len(b) > 1 and b[1] == 0):
        for enc in ("utf-16", "utf-16-le"):
            try:
                return b.decode(enc)
            except Exception:
                pass
    return b.decode("utf-8", errors="ignore")


def nd(s):
    if s is None:
        return None
    s = str(s).strip().replace("$", "").replace(",", "")
    if s in {"", "#N/A", "None", "#DIV/0!", "nan", "NaT"}:
        return None
    if s.isdigit() and len(s) == 8:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    try:
        return pd.Timestamp(s).strftime("%Y-%m-%d")
    except Exception:
        return None


def nf(s):
    if s is None:
        return None
    s = str(s).replace("$", "").replace(",", "").replace("%", "").strip()
    if s in {"", "#N/A", "None", "#DIV/0!", "nan"}:
        return None
    try:
        return float(s)
    except Exception:
        return None


def bar_to_date(idx, b):
    if b is None:
        return None
    try:
        b = int(b)
    except Exception:
        return None
    if b < 0 or b >= len(idx):
        return None
    return pd.Timestamp(idx[b]).strftime("%Y-%m-%d")


print("=== 1) SHEET TRADE ROW ===")
trades = []
lines = read_text(AMZN / "trades.tsv").splitlines()
start = 0
for i, ln in enumerate(lines):
    if ln.strip().startswith("Entry Date"):
        start = i + 1
        break
for ln in lines[start:]:
    if not ln.strip():
        continue
    c = ln.split("\t")
    entry = nd(c[0])
    if not entry:
        continue
    row = {
        "entry": entry,
        "entry_px": nf(c[1]) if len(c) > 1 else None,
        "exit": nd(c[2]) if len(c) > 2 else None,
        "exit_px": nf(c[3]) if len(c) > 3 else None,
        "raw": ln[:220],
    }
    trades.append(row)
    if entry == TARGET:
        print("FOUND:", row)

print("sheet entries:", [t["entry"] for t in trades])
phantom = next(t for t in trades if t["entry"] == TARGET)

print("\n=== 2) SHEET ZONES ROCKETS ===")
zrows = []
zlines = read_text(AMZN / "zones.tsv").splitlines()
print("header cols count:", len(zlines[0].split("\t")))
print("header rocket col18 sample:", zlines[0].split("\t")[18] if len(zlines[0].split("\t")) > 18 else "N/A")
for ln in zlines[1:]:
    if not ln.strip():
        continue
    c = ln.split("\t") + [""] * 20
    piv = nd(c[9])
    if not piv:
        continue
    z = {
        "pivot": piv,
        "bo": nd(c[5]),
        "zlow": nf(c[6]),
        "zhigh": nf(c[7]),
        "conf": nd(c[13]),
        "next": nd(c[14]),
        "retest": nd(c[16]),
        "rocket": nd(c[18]),
    }
    zrows.append(z)

rockets = [z for z in zrows if z["rocket"]]
print(f"n_zones={len(zrows)} n_rockets={len(rockets)}")
print("all rockets:")
for z in rockets:
    print(
        f"  pivot={z['pivot']} retest={z['retest']} rocket={z['rocket']} "
        f"zone={z['zlow']}/{z['zhigh']}"
    )

near = []
for z in zrows:
    for d in (z["pivot"], z["retest"], z["rocket"], z["bo"], z["conf"]):
        if not d:
            continue
        if "2022-10" <= d <= "2023-03":
            near.append(z)
            break
print(f"\nzones with any date in 2022-10..2023-03: {len(near)}")
for z in near:
    print(
        f"  pivot={z['pivot']} bo={z['bo']} conf={z['conf']} retest={z['retest']} "
        f"rocket={z['rocket']} zone={z['zlow']}/{z['zhigh']}"
    )

# rocket within ±5 sessions of entry signal (=entry-1) or fill
sig_candidates = []
for z in rockets:
    rd = z["rocket"]
    if rd and abs((pd.Timestamp(rd) - pd.Timestamp(TARGET)).days) <= 10:
        sig_candidates.append(z)
print(f"\nrockets within ±10 calendar days of {TARGET}: {len(sig_candidates)}")
for z in sig_candidates:
    print(z)

print("\n=== 3) ENG CLOSED / OPEN / ENTRIES ===")
closed = pd.read_csv(STAMP / f"WPBR_Closed_{ST}.csv")
closed = closed[closed["SYMBOL"].astype(str).str.upper() == "AMZN"]
print("closed entries:", closed["DATE_OPENED"].tolist())
hit = closed[closed["DATE_OPENED"].astype(str).str.contains("2022")]
print("closed with 2022 open:", len(hit))

op = pd.read_csv(STAMP / f"WPBR_Open_{ST}.csv")
if "SYMBOL" in op.columns:
    op = op[op["SYMBOL"].astype(str).str.upper() == "AMZN"]
    print("open entries:", op["DATE_OPENED"].tolist() if len(op) else [])

ze = pd.read_csv(STAMP / f"WPBR_ZONES_ENTRIES_AMZN_{ST}.csv")
print("entries file cols:", list(ze.columns))
print("entries rows:", len(ze))
# print any 2022-11/12 / 2023-01
mask = ze.astype(str).apply(
    lambda s: s.str.contains(r"2022-1[01]|2022-12|2023-0[123]", regex=True)
).any(axis=1)
print("entries near window:", int(mask.sum()))
if mask.any():
    print(ze.loc[mask].to_string(index=False))

zz = pd.read_csv(STAMP / f"WPBR_ZONES_AMZN_{ST}.csv")
print("\nzones eng cols:", list(zz.columns))
maskz = zz.astype(str).apply(
    lambda s: s.str.contains(r"2022-1[01]|2022-12|2023-0[123]", regex=True)
).any(axis=1)
print("eng zones near window:", int(maskz.sum()))
if maskz.any():
    # compact print key cols
    cols = [
        c
        for c in zz.columns
        if any(
            k in c.lower()
            for k in (
                "pivot",
                "break",
                "retest",
                "signal",
                "fill",
                "rocket",
                "zone",
                "monday",
                "lower",
                "upper",
            )
        )
    ]
    print(zz.loc[maskz, cols].to_string(index=False))

print("\n=== 4) TOUCH STREAM (engine truth) ===")
# locate price file
candidates = [
    REPO / "data" / "newdata" / "data" / "AMZN.csv",
    REPO / "data" / "AMZN.csv",
]
px = None
for c in candidates:
    if c.is_file():
        px = c
        break
if px is None:
    # search
    hits = list((REPO / "data").rglob("AMZN.csv"))
    print("price search:", hits[:5])
    px = hits[0] if hits else None
print("price file:", px)
df = pd.read_csv(px)
# normalize
date_col = None
for c in df.columns:
    if c.lower() in ("date", "datetime", "timestamp"):
        date_col = c
        break
df[date_col] = pd.to_datetime(df[date_col])
df = df.set_index(date_col).sort_index()
# rename cols
rename = {}
for c in df.columns:
    cl = c.lower()
    if cl == "open":
        rename[c] = "Open"
    elif cl == "high":
        rename[c] = "High"
    elif cl == "low":
        rename[c] = "Low"
    elif cl == "close":
        rename[c] = "Close"
    elif cl == "volume":
        rename[c] = "Volume"
df = df.rename(columns=rename)

stream = compute_wpbr_touch_stream(
    df,
    band_pct=0.015,
    strong_pre_pivot_bars=3,
    strong_pre_pivot_pct=0.10,
    strong_post_pivot_bars=3,
    strong_post_pivot_pct=0.10,
    strong_pivot_mode="either",
    breakout_confirmation=0.03,
    max_days_after_retest=2,
    retest_mode="stop_looking",
    zone_price_round_decimals=2,
)
idx = pd.DatetimeIndex(df.index)

fills = []
signals = []
for ev in stream["wpbr_zone_events"]:
    sig = bar_to_date(idx, ev.get("entry_signal_bar"))
    fill = bar_to_date(idx, ev.get("entry_fill_bar"))
    piv = nd(ev["pivot_monday"])
    if fill:
        fills.append((fill, sig, piv, ev.get("zone_lower"), ev.get("zone_upper")))
    if sig:
        signals.append((sig, fill, piv))

print("all eng fills:", sorted({f[0] for f in fills}))
print("TARGET in fills?", any(f[0] == TARGET for f in fills))
print("TARGET-1 in signals?", any(s[0] == "2022-12-07" for s in signals))

# any signal/fill in Nov2022-Jan2023
print("\nsignals in 2022-11..2023-02:")
for s in signals:
    if "2022-11" <= s[0] <= "2023-02":
        print(" ", s)
print("fills in 2022-11..2023-02:")
for f in fills:
    if "2022-11" <= f[0] <= "2023-02":
        print(" ", f)

opps = stream.get("wpbr_entry_opportunities") or []
print(f"\nopportunities count={len(opps)}")
near_opps = []
for opp in opps:
    fd = bar_to_date(idx, opp.get("entry_fill_bar"))
    sd = bar_to_date(idx, opp.get("entry_signal_bar"))
    if (fd and "2022-11" <= fd <= "2023-02") or (sd and "2022-11" <= sd <= "2023-02"):
        near_opps.append((sd, fd, opp))
print(f"opps near window: {len(near_opps)}")
for sd, fd, opp in near_opps:
    print(" ", sd, fd, {k: opp.get(k) for k in list(opp)[:12]})

print("\n=== 5) OHLC check entry/exit ===")
# entry day open
for d in (TARGET, phantom["exit"]):
    if d is None:
        continue
    ts = pd.Timestamp(d)
    if ts in df.index:
        row = df.loc[ts]
        print(
            d,
            "O/H/L/C",
            float(row["Open"]),
            float(row["High"]),
            float(row["Low"]),
            float(row["Close"]),
        )
    else:
        print(d, "NOT IN INDEX")

ep = phantom["entry_px"]
xp = phantom["exit_px"]
o_entry = float(df.loc[pd.Timestamp(TARGET), "Open"])
print(f"sheet entry_px={ep} vs open={o_entry} match={abs(ep - o_entry) < 0.02}")
if phantom["exit"]:
    o_exit = float(df.loc[pd.Timestamp(phantom["exit"]), "Open"])
    print(f"sheet exit_px={xp} vs open={o_exit} match={abs(xp - o_exit) < 0.02}")
    print(f"1.22*entry={ep * 1.22:.4f} (gap-up style target check)")

print("\n=== 6) OCCUPANCY CONTEXT ===")
# Prior trade exit before phantom, next after
sorted_tr = sorted(trades, key=lambda t: t["entry"])
prev = [t for t in sorted_tr if t["entry"] < TARGET]
nxt = [t for t in sorted_tr if t["entry"] > TARGET]
print("prev sheet trade:", prev[-1] if prev else None)
print("next sheet trade:", nxt[0] if nxt else None)
# eng occupancy: was eng flat on 2022-12-08?
eng_closed_rows = []
for _, r in closed.iterrows():
    eng_closed_rows.append(
        {
            "entry": nd(str(r["DATE_OPENED"])),
            "exit": nd(str(r["DATE_CLOSED"])),
        }
    )
print("eng closed:", eng_closed_rows)
occupied = False
for t in eng_closed_rows:
    if t["entry"] and t["exit"] and t["entry"] <= TARGET < t["exit"]:
        occupied = True
        print("ENG OCCUPIED by", t)
if not occupied:
    print("ENG was FLAT on", TARGET, "- occupancy cannot explain missing fill")

print("\nDONE")
