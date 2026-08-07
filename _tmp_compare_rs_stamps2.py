import csv
import collections
from pathlib import Path

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")


def load(p):
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fnum(x):
    try:
        return float(str(x).replace("%", "").replace(",", ""))
    except Exception:
        return None


def analyze(stamp):
    rows = load(ROOT / f"drive/RS_Closed_{stamp}.csv")
    exits = collections.Counter(r.get("EXIT_TYPE", "") for r in rows)
    print(f"=== {stamp} EXIT_TYPE ===")
    for k, n in exits.most_common():
        subset = [r for r in rows if r.get("EXIT_TYPE") == k]
        pnls = [fnum(r["PNL_DOLLARS"]) for r in subset]
        pnls = [x for x in pnls if x is not None]
        pcts = [fnum(r["PNL_PCT"]) for r in subset]
        pcts = [x for x in pcts if x is not None]
        print(
            f"  {n:4d}  {k:20s}  pnl_sum={sum(pnls):,.0f}  avg_pct={sum(pcts)/len(pcts) if pcts else 0:.2f}"
        )
    atrs = [fnum(r.get("ATR_PCT_AT_TRIGGER")) for r in rows]
    atrs = [a for a in atrs if a is not None]
    over3 = [a for a in atrs if a > 3.0]
    print(
        f"  atr_pct_at_trigger: n={len(atrs)} mean={sum(atrs)/len(atrs):.3f} "
        f"max={max(atrs):.3f} pct>3={100*len(over3)/len(atrs):.1f}%"
    )
    return rows


c = analyze("260731212031")
t = analyze("260731204706")

ck = {(r["SYMBOL"], r["DATE_OPENED"]) for r in c}
tk = {(r["SYMBOL"], r["DATE_OPENED"]) for r in t}
only_ctrl = [r for r in t if (r["SYMBOL"], r["DATE_OPENED"]) not in ck]
only_cand = [r for r in c if (r["SYMBOL"], r["DATE_OPENED"]) not in tk]
print(f"\nOnly in ctrl: {len(only_ctrl)}  Only in cand: {len(only_cand)}")

atrs = [fnum(r.get("ATR_PCT_AT_TRIGGER")) for r in only_ctrl]
atrs = [a for a in atrs if a is not None]
print(
    f"Ctrl-only ATR_PCT_AT_TRIGGER: n={len(atrs)} mean={sum(atrs)/len(atrs) if atrs else 0:.3f} "
    f"min={min(atrs) if atrs else 0:.3f} max={max(atrs) if atrs else 0:.3f} "
    f"pct>3={100*sum(1 for a in atrs if a>3)/len(atrs) if atrs else 0:.1f}%"
)
pnls = [x for x in (fnum(r["PNL_DOLLARS"]) for r in only_ctrl) if x is not None]
pcts = [x for x in (fnum(r["PNL_PCT"]) for r in only_ctrl) if x is not None]
wins = sum(1 for p in pcts if p > 0)
print(
    f"Ctrl-only: trades={len(only_ctrl)} wins={wins} "
    f"win%={100*wins/len(pcts) if pcts else 0:.1f} "
    f"pnl_sum={sum(pnls):,.0f} avg_pct={sum(pcts)/len(pcts) if pcts else 0:.2f}"
)
print("Ctrl-only EXIT_TYPE:", dict(collections.Counter(r["EXIT_TYPE"] for r in only_ctrl)))
print("Ctrl-only atr>3:", sum(1 for a in atrs if a > 3), " atr<=3:", sum(1 for a in atrs if a <= 3))

# GAP_DOWN deep dive both
for label, rows in (("cand", c), ("ctrl", t)):
    gd = [r for r in rows if "GAP" in str(r.get("EXIT_TYPE", "")).upper()]
    stop = [r for r in rows if r.get("EXIT_TYPE") == "STOP"]
    # fat stop: PNL_PCT <= -15-ish or exit gap vs stop
    fat = []
    for r in stop:
        pct = fnum(r["PNL_PCT"])
        if pct is not None and pct <= -15:
            fat.append(r)
    print(f"\n{label}: GAP* exits={len(gd)}  STOP={len(stop)}  STOP pnl<=-15%={len(fat)}")
    if fat:
        fp = [fnum(r["PNL_DOLLARS"]) for r in fat]
        fp = [x for x in fp if x is not None]
        print(f"  fat-stop pnl_sum={sum(fp):,.0f} avg_pct={sum(fnum(r['PNL_PCT']) for r in fat)/len(fat):.2f}")

seed = "AAPL,NVDA,GOOGL,MSFT,AMZN,TSM,AVGO,META,LLY,JPM,WMT,MU,AMD,V,XOM,ASML,MA".split(",")
cs = {r["SYMBOL"] for r in c}
ts = {r["SYMBOL"] for r in t}
print("Cand missing seed:", [s for s in seed if s not in cs])
print("Ctrl missing seed:", [s for s in seed if s not in ts])
print("Cand MA trades:", sum(1 for r in c if r["SYMBOL"] == "MA"))
print("Ctrl MA trades:", sum(1 for r in t if r["SYMBOL"] == "MA"))

# only-cand details
if only_cand:
    pnls = [x for x in (fnum(r["PNL_DOLLARS"]) for r in only_cand) if x is not None]
    pcts = [x for x in (fnum(r["PNL_PCT"]) for r in only_cand) if x is not None]
    print(
        f"Cand-only: n={len(only_cand)} pnl={sum(pnls):,.0f} "
        f"avg_pct={sum(pcts)/len(pcts) if pcts else 0:.2f} "
        f"syms={sorted(set(r['SYMBOL'] for r in only_cand))}"
    )
    atrs2 = [fnum(r.get("ATR_PCT_AT_TRIGGER")) for r in only_cand]
    atrs2 = [a for a in atrs2 if a is not None]
    print(
        f"Cand-only ATR: mean={sum(atrs2)/len(atrs2) if atrs2 else 0:.3f} "
        f"max={max(atrs2) if atrs2 else 0:.3f}"
    )

for stamp in ("260731212031", "260731204706"):
    p = ROOT / f"drive/RS_ImproveHints_{stamp}.md"
    if p.exists():
        txt = p.read_text(encoding="utf-8").encode("ascii", "replace").decode("ascii")
        print(f"\n=== ImproveHints {stamp} ===")
        print(txt[:1500])
