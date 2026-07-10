"""Re-entry analysis with trading sessions between close and next open."""
import csv
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

CLOSED = Path(r"C:\Users\songg\Downloads\stockresearch\Drive\IND_Closed_260523140100.csv")
DATA_DIR = Path(r"C:\Users\songg\Downloads\stockresearch\data\newdata\data")


def norm_ymd(s: str) -> str:
    s = str(s or "").strip()
    if len(s) >= 10 and s[4] == "-":
        return s[:10].replace("-", "")
    digits = "".join(c for c in s if c.isdigit())
    return digits[:8] if len(digits) >= 8 else ""


cal_cache: dict[str, list[str]] = {}


def load_cal(sym: str) -> list[str]:
    if sym not in cal_cache:
        df = pd.read_csv(DATA_DIR / f"{sym}.csv")
        dc = "Date" if "Date" in df.columns else df.columns[0]
        dates = sorted(pd.to_datetime(df[dc], errors="coerce").dropna().dt.normalize().unique())
        cal_cache[sym] = [d.strftime("%Y%m%d") for d in dates]
    return cal_cache[sym]


def pair_metrics(sym: str, close_ymd: str, open_ymd: str) -> dict | None:
    cal = load_cal(sym)
    idx = {d: i for i, d in enumerate(cal)}
    if close_ymd not in idx or open_ymd not in idx:
        return None
    ic, io = idx[close_ymd], idx[open_ymd]
    between = cal[ic + 1 : io]
    return {
        "gap_idx": io - ic,
        "n_between": len(between),
        "cal_days": (pd.Timestamp(open_ymd) - pd.Timestamp(close_ymd)).days,
        "between": between,
    }


def pct(n: int, d: int) -> float:
    return 100.0 * n / d if d else 0.0


trades: list[dict] = []
with CLOSED.open(newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        sym = row["SYMBOL"].strip()
        dop, dcl = norm_ymd(row["DATE_OPENED"]), norm_ymd(row["DATE_CLOSED"])
        if sym and dop and dcl:
            trades.append({"sym": sym, "open": dop, "close": dcl})

by_sym: dict[str, list] = defaultdict(list)
for t in trades:
    by_sym[t["sym"]].append(t)
for sym in by_sym:
    by_sym[sym].sort(key=lambda x: x["open"])

pairs: list[dict] = []
for sym, lst in by_sym.items():
    for i in range(1, len(lst)):
        prev, cur = lst[i - 1], lst[i]
        m = pair_metrics(sym, prev["close"], cur["open"])
        if m:
            pairs.append({"sym": sym, "prev_close": prev["close"], "cur_open": cur["open"], **m})

n_trades, n_pairs = len(trades), len(pairs)
ctr_between = Counter(p["n_between"] for p in pairs)

c_next_td = sum(1 for p in pairs if p["n_between"] == 0)
c_le1 = sum(1 for p in pairs if p["n_between"] <= 1)
c_le2 = sum(1 for p in pairs if p["n_between"] <= 2)
c_le5 = sum(1 for p in pairs if p["n_between"] <= 5)

print("IND_Closed_260523140100 — same-symbol re-entry timing")
print(f"Total closed trades: {n_trades}")
print(f"Symbols: {len(by_sym)}")
print(f"Consecutive trade pairs: {n_pairs} ({pct(n_pairs, n_trades):.1f}% of trades are 2nd+ on a symbol)")
print()
print("Sessions BETWEEN close day and next open (from each symbol OHLC calendar):")
print()
print(f"  Next trading day open (0 sessions between): {c_next_td} ({pct(c_next_td, n_pairs):.1f}% of pairs)")
print(f"  <=1 session between: {c_le1} ({pct(c_le1, n_pairs):.1f}%)")
print(f"  <=2 sessions between: {c_le2} ({pct(c_le2, n_pairs):.1f}%)  [often Fri close -> Tue open]")
print(f"  <=5 sessions between: {c_le5} ({pct(c_le5, n_pairs):.1f}%)")
print(f"  >5 sessions between: {n_pairs - c_le5} ({pct(n_pairs - c_le5, n_pairs):.1f}%)")
print()
print("Distribution (sessions between):")
for b in sorted(ctr_between)[:15]:
    print(f"  {b:2d}: {ctr_between[b]:4d} ({pct(ctr_between[b], n_pairs):5.1f}%)")
if len(ctr_between) > 15:
    print("  ...")
med = sorted(p["n_between"] for p in pairs)[len(pairs) // 2]
print(f"Median sessions between: {med}")
print()

ctr_cal_next = Counter(p["cal_days"] for p in pairs if p["n_between"] == 0)
if ctr_cal_next:
    print("Calendar days (close -> open) when open is next trading day:")
    for d in sorted(ctr_cal_next):
        print(f"  {d} days: {ctr_cal_next[d]} ({pct(ctr_cal_next[d], c_next_td):.1f}%)")

ctr_cal_2sess = Counter(p["cal_days"] for p in pairs if p["n_between"] == 2)
if ctr_cal_2sess:
    print()
    print("Calendar days when exactly 2 sessions between (common weekend gap):")
    for d in sorted(ctr_cal_2sess)[:8]:
        print(f"  {d} days: {ctr_cal_2sess[d]} ({pct(ctr_cal_2sess[d], ctr_between[2]):.1f}% of 2-session gaps)")

print()
print("Examples — 1 session between (fastest re-entries in this run):")
shown = 0
for p in pairs:
    if p["n_between"] == 1:
        print(
            f"  {p['sym']}: close {p['prev_close']} -> open {p['cur_open']}, "
            f"between={p['between']}, {p['cal_days']} calendar days"
        )
        shown += 1
print()
print("Examples — next trading day (0 between):")
shown = 0
for p in pairs:
    if p["n_between"] == 0:
        print(
            f"  {p['sym']}: close {p['prev_close']} -> open {p['cur_open']}, "
            f"{p['cal_days']} calendar days"
        )
        shown += 1
        if shown >= 5:
            break

print()
print("Examples — 2 sessions between:")
shown = 0
for p in pairs:
    if p["n_between"] == 2:
        print(
            f"  {p['sym']}: close {p['prev_close']} -> open {p['cur_open']}, "
            f"between={p['between']}, {p['cal_days']} calendar days"
        )
        shown += 1
        if shown >= 5:
            break

# symbols with many rapid re-entries
sym_rapid = Counter(p["sym"] for p in pairs if p["n_between"] <= 2)
print()
print("Symbols with most rapid re-entries (<=2 sessions between):")
for sym, c in sym_rapid.most_common(8):
    print(f"  {sym}: {c}")
