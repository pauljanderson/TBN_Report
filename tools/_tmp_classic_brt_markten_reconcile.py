#!/usr/bin/env python3
"""Fixed classic BRT MarkTen sheet vs engine reconcile."""
from __future__ import annotations
import csv, re, sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")
OUT = ROOT / "drive" / "brt_sheet_reconcile"
DRIVE = ROOT / "drive"
TOOLS = ROOT / "tools"
STAMP = sys.argv[1] if len(sys.argv) > 1 else "260722175102"
WIN_START, WIN_END = date(2010,1,4), date(2026,6,5)
MARKTEN = ["AAPL","AMZN","GOOGL","META","MSFT","NVDA","TSLA","AU","AMD","NFLX"]
PRIOR = {
    "AAPL":"260720143523","AMZN":"260720185855","GOOGL":"260720143523",
    "META":"260721152701","MSFT":"260720143523","NVDA":"260720194240",
    "TSLA":"260720111055","AU":"260720215017","AMD":"260720165857","NFLX":"260720183518",
}
ZT, ET = 0.02, 0.05

def parse_date(s):
    if s is None: return None
    if isinstance(s,(int,float)) and not isinstance(s,bool):
        n=int(s)
        if 19000101 <= n <= 21001231:
            try: return datetime.strptime(str(n),"%Y%m%d").date()
            except ValueError: return None
    s=str(s).strip()
    if not s or s.lower() in ("nan","none"): return None
    if s.endswith(".0"): s=s[:-2]
    for fmt in ("%Y-%m-%d","%Y%m%d","%m/%d/%Y","%m/%d/%y","%Y-%m-%d %H:%M:%S"):
        try:
            ss=s[:19] if " " in s and len(s)>10 else s
            return datetime.strptime(ss, fmt if " " not in ss else "%Y-%m-%d %H:%M:%S").date()
        except ValueError: continue
    try:
        n=float(s)
        if 20000 < n < 60000:
            return (datetime(1899,12,30)+timedelta(days=int(n))).date()
        if 19000101 <= int(n) <= 21001231:
            return datetime.strptime(str(int(n)),"%Y%m%d").date()
    except Exception: pass
    return None

def parse_money(s):
    if s is None: return None
    s=str(s).strip().replace("$","").replace(",","").replace("%","")
    if not s or s.lower() in ("nan","none"): return None
    try: return round(float(s),4)
    except ValueError: return None

def within(a,b,tol):
    return a is not None and b is not None and abs(a-b)<=tol+1e-9

def uniq(rows):
    seen=set(); out=[]
    for r in rows:
        if r in seen: continue
        seen.add(r); out.append(r)
    return out

def load_sheet_zones(sym):
    for p in (OUT/f"{sym}_sheet_zones.csv", TOOLS/f"{sym.lower()}_brt_sheet_zones.tsv", TOOLS/f"{sym.lower()}_brt_sheet_zones.txt"):
        if not p.is_file(): continue
        rows=[]
        text=p.read_text(encoding="utf-8-sig")
        first=text.splitlines()[0] if text else ""
        delim="\t" if "\t" in first else ","
        if re.search(r"[A-Za-z]", first):
            for r in csv.DictReader(text.splitlines(), delimiter=delim):
                km={k.lower():k for k in r}
                def g(*ns):
                    for n in ns:
                        if n in km: return r[km[n]]
                        for lk,ok in km.items():
                            if n in lk: return r[ok]
                    return None
                c=parse_money(g("touch","center","zone_center","matured"))
                lo=parse_money(g("lower","zone_low","zone lower","low"))
                hi=parse_money(g("upper","zone_high","zone upper","high"))
                if None in (c,lo,hi): continue
                rows.append((round(c,2),round(lo,2),round(hi,2)))
        else:
            for line in text.splitlines():
                nums=[parse_money(x) for x in re.split(r"[\t, ]+", line.strip())]
                nums=[x for x in nums if x is not None]
                if len(nums)>=3: rows.append((round(nums[0],2),round(nums[1],2),round(nums[2],2)))
        return uniq(rows), p
    return [], None

def load_engine_zones(sym, stamp, window=True):
    p=DRIVE/f"BRT_ZONES_{sym}_{stamp}.csv"
    if not p.is_file(): return [], None
    rows=[]
    with p.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            mat=str(r.get("MATURED_NOW","")).strip()
            if mat and mat not in ("1","1.0","True","true"): continue
            d=parse_date(r.get("MATURITY_DATE") or r.get("DATE"))
            if window and d and not (WIN_START<=d<=WIN_END): continue
            c=parse_money(r.get("ZONE_CENTER") or r.get("TOUCH_PRICE"))
            lo=parse_money(r.get("ZONE_LOW"))
            hi=parse_money(r.get("ZONE_HIGH"))
            if None in (c,lo,hi): continue
            rows.append((round(c,2),round(lo,2),round(hi,2)))
    return uniq(rows), p

def mset_match(sheet, eng, tol):
    rem=list(eng); exact=near=0; so=[]
    for s in sheet:
        bi=None; bd=None; bex=False
        for i,e in enumerate(rem):
            if s==e: bi=i; bex=True; break
            d=max(abs(s[0]-e[0]),abs(s[1]-e[1]),abs(s[2]-e[2]))
            if d<=tol+1e-9 and (bd is None or d<bd): bi=i; bd=d
        if bi is None: so.append(s)
        else:
            if bex: exact+=1
            else: near+=1
            rem.pop(bi)
    return dict(exact=exact,near=near,matched=exact+near,sheet_n=len(sheet),eng_n=len(eng),sheet_only=len(so),eng_only=len(rem))

def load_sheet_bos(sym):
    for p in (TOOLS/f"{sym.lower()}_brt_sheet_breakouts.tsv", TOOLS/f"{sym.lower()}_brt_sheet_breakout_retest.tsv",
              OUT/f"{sym}_sheet_breakouts.csv", OUT/f"{sym}_sheet_breakout_retest.tsv", OUT/f"{sym}_sheet_breakout_retest.csv"):
        if not p.is_file(): continue
        rows=[]; text=p.read_text(encoding="utf-8-sig"); first=text.splitlines()[0]; delim="\t" if "\t" in first else ","
        for r in csv.DictReader(text.splitlines(), delimiter=delim):
            km={k.lower():k for k in r}
            def g(*ns):
                for n in ns:
                    if n in km: return r[km[n]]
                    for lk,ok in km.items():
                        if n in lk: return r[ok]
                return None
            d=parse_date(g("breakout date","bo date"))
            lo=parse_money(g("zone lower","lower"))
            hi=parse_money(g("zone upper","upper"))
            rd=parse_date(g("retest date"))
            if None in (d,lo,hi): continue
            if not (WIN_START<=d<=WIN_END): continue
            rows.append({"bo_date":d,"lower":round(lo,2),"upper":round(hi,2),"retest_date":rd})
        return rows, p
    return [], None

def load_engine_bos(sym, stamp):
    p=DRIVE/f"BRT_breakout_and_retest_{stamp}.csv"
    if not p.is_file(): return [], None
    rows=[]
    with p.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("SYMBOL") or "").upper()!=sym: continue
            d=parse_date(r.get("Breakout Date")); lo=parse_money(r.get("Zone Lower")); hi=parse_money(r.get("Zone Upper"))
            rd=parse_date(r.get("Retest Date"))
            if None in (d,lo,hi): continue
            if not (WIN_START<=d<=WIN_END): continue
            rows.append({"bo_date":d,"lower":round(lo,2),"upper":round(hi,2),"retest_date":rd})
    return rows, p

def match_bos(sheet, eng):
    rem=list(eng); matched=rt=so=0
    for s in sheet:
        hit=None
        for i,e in enumerate(rem):
            if e["bo_date"]==s["bo_date"] and within(e["lower"],s["lower"],ZT) and within(e["upper"],s["upper"],ZT):
                hit=i; break
        if hit is None: so+=1
        else:
            matched+=1; e=rem.pop(hit)
            if s["retest_date"]==e["retest_date"]: rt+=1
    return dict(matched=matched,sheet_n=len(sheet),eng_n=len(eng),sheet_only=so,eng_only=len(rem),rt_date=rt)

def load_sheet_trades(sym):
    cands=[OUT/f"{sym}_sheet_trades.csv", OUT/f"{sym.lower()}_brt_sheet_trades.tsv", TOOLS/f"{sym.lower()}_brt_sheet_trades.tsv",
           OUT/"tsla_brt_sheet_trades_authoritative_paste.tsv" if sym=="TSLA" else None]
    for p in cands:
        if not p or not p.is_file(): continue
        rows=[]; text=p.read_text(encoding="utf-8-sig"); first=text.splitlines()[0]; delim="\t" if "\t" in first else ","
        for r in csv.DictReader(text.splitlines(), delimiter=delim):
            km={k.lower().strip():k for k in r}
            def g(*ns):
                for n in ns:
                    if n in km: return r[km[n]]
                    for lk,ok in km.items():
                        if n.replace(" ","") in lk.replace(" ",""): return r[ok]
                return None
            td=parse_date(g("trigger date","confirm date","maturity date","signal date"))
            ed=parse_date(g("entry date","date opened"))
            xd=parse_date(g("exit date","date closed"))
            ep=parse_money(g("entry price","entry"))
            xp=parse_money(g("exit price","exit"))
            if td is None: td=ed
            if td is None or ep is None: continue
            if not (WIN_START<=td<=WIN_END): continue
            rows.append({"trigger":td,"entry":ed,"exit":xd,"entry_px":ep,"exit_px":xp})
        return rows, p
    return [], None

def load_engine_trades(sym, stamp):
    rows=[]
    for name, is_open in ((f"BRT_Closed_{stamp}.csv", False),(f"BRT_Open_{stamp}.csv", True)):
        p=DRIVE/name
        if not p.is_file(): continue
        with p.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if (r.get("SYMBOL") or "").upper()!=sym: continue
                td=parse_date(r.get("MATURITY_DATE") or r.get("CLOSE_ABOVE_DATE") or r.get("TRIGGER_DATE"))
                ed=parse_date(r.get("DATE_OPENED") or r.get("ENTRY_DATE"))
                xd=None if is_open else parse_date(r.get("DATE_CLOSED") or r.get("EXIT_DATE"))
                ep=parse_money(r.get("ENTRY_PRICE"))
                xp=parse_money(r.get("EXIT_PRICE"))
                if td is None: td=ed
                if td is None or ep is None: continue
                if not (WIN_START<=td<=WIN_END): continue
                rows.append({"trigger":td,"entry":ed,"exit":xd,"entry_px":ep,"exit_px":xp,"open":is_open})
    return rows

def match_trades(sheet, eng):
    rem=list(eng); matched=exit_m=px_m=so=0
    for s in sheet:
        hit=None
        for i,e in enumerate(rem):
            if within(e["entry_px"], s["entry_px"], ET) and (e["trigger"]==s["trigger"] or (s["entry"] and e["entry"]==s["entry"])):
                hit=i; break
            if within(e["entry_px"], s["entry_px"], ET) and s["exit"] and e["exit"] and s["exit"]==e["exit"]:
                hit=i; break
            if within(e["entry_px"], s["entry_px"], ET) and e["entry"] and s["trigger"] and abs((e["entry"]-s["trigger"]).days)<=2:
                hit=i; break
        if hit is None: so+=1
        else:
            matched+=1; e=rem.pop(hit)
            if s["exit"] and e["exit"] and s["exit"]==e["exit"]: exit_m+=1
            if s["exit_px"] is not None and within(e.get("exit_px"), s["exit_px"], ET): px_m+=1
    return dict(matched=matched,sheet_n=len(sheet),eng_n=len(eng),
                eng_closed=sum(1 for e in eng if not e.get("open")),
                sheet_only=so,eng_only=len(rem),exit_date=exit_m,exit_px=px_m)

def eng_vs_prior_zones(sym):
    a,_=load_engine_zones(sym, PRIOR[sym], window=False)
    b,_=load_engine_zones(sym, STAMP, window=False)
    return mset_match(a,b,ZT), len(a), len(b)

lines=[]
lines += [f"# Classic BRT MarkTen sheet reconcile — stamp `{STAMP}`", "",
          f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
          "- Settings: run_brt.bat equivalents + `max_market_cap=0`, `breakout_zone_pick=max`, `stop_loss_based=trigger_low`, **`wpbr_zones=false`**",
          f"- Universe: {', '.join(MARKTEN)}", f"- Window: {WIN_START} .. {WIN_END}",
          f"- Artifacts: `drive/BRT_Closed_{STAMP}.csv`, `BRT_breakout_and_retest_{STAMP}.csv`, `BRT_ZONES_*_{STAMP}.csv`",
          f"- Log: `drive/brt_sheet_reconcile/_classic_brt_markten_rerun.log`", ""]
lines += ["| Symbol | Zones ±$0.02 | BO date+zone | Retest date | Trades ±$0.05 | Exit date | Eng↔prior zones | Verdict |",
          "|---|---:|---:|---:|---:|---:|---:|---|"]

stats={}
details=[]
for sym in MARKTEN:
    sz,sp=load_sheet_zones(sym); ez,_=load_engine_zones(sym,STAMP); z=mset_match(sz,ez,ZT) if sz else dict(matched=0,sheet_n=0,eng_n=len(ez),exact=0,near=0,sheet_only=0,eng_only=len(ez))
    sb,_=load_sheet_bos(sym); eb,_=load_engine_bos(sym,STAMP); b=match_bos(sb,eb) if sb else dict(matched=0,sheet_n=0,eng_n=len(eb),sheet_only=0,eng_only=0,rt_date=0)
    st,_=load_sheet_trades(sym); et=load_engine_trades(sym,STAMP); t=match_trades(st,et) if st else dict(matched=0,sheet_n=0,eng_n=len(et),eng_closed=0,sheet_only=0,eng_only=0,exit_date=0,exit_px=0)
    ep, pn, cn = eng_vs_prior_zones(sym)
    z_ok=z["sheet_n"]>0 and z["matched"]==z["sheet_n"]
    b_ok=b["sheet_n"]>0 and b["matched"]==b["sheet_n"]
    t_ok=t["sheet_n"]>0 and t["matched"]==t["sheet_n"]
    if z["sheet_n"]==0 and b["sheet_n"]==0 and t["sheet_n"]==0: verd="NO_SHEET"
    elif z_ok and b_ok and t_ok: verd="PASS"
    elif z_ok and b_ok and t["matched"]>=max(t["sheet_n"]-3,0): verd="NEAR"
    elif z_ok and (b_ok or b["matched"]/max(b["sheet_n"],1)>=0.95): verd="ZONES_OK"
    else: verd="FAIL"
    stats[verd]=stats.get(verd,0)+1
    lines.append(
        f"| {sym} | {z['matched']}/{z['sheet_n']} (ex{z['exact']}+n{z['near']}; so{z['sheet_only']} eo{z['eng_only']}) "
        f"| {b['matched']}/{b['sheet_n']} (so{b['sheet_only']} eo{b['eng_only']}) "
        f"| {b['rt_date']}/{b['matched']} "
        f"| {t['matched']}/{t['sheet_n']} (so{t['sheet_only']} eo{t['eng_only']}; engC{t.get('eng_closed',0)}) "
        f"| {t['exit_date']}/{t['matched']} "
        f"| {ep['matched']}/{pn}->{cn} eo{ep['eng_only']} | **{verd}** |"
    )
    details.append((sym,z,b,t,ep,verd))

lines += ["","## Engine closed counts vs prior deep stamp","",
          "| Symbol | Prior | Prior n | New n | d |","|---|---|---:|---:|---:|"]
for sym in MARKTEN:
    def cnt(stamp):
        p=DRIVE/f"BRT_Closed_{stamp}.csv"
        if not p.is_file(): return None
        return sum(1 for r in csv.DictReader(p.open(encoding="utf-8-sig")) if (r.get("SYMBOL") or "").upper()==sym)
    a,b_=cnt(PRIOR[sym]),cnt(STAMP)
    d="n/a" if a is None or b_ is None else f"{b_-a:+d}"
    lines.append(f"| {sym} | `{PRIOR[sym]}` | {a} | {b_} | {d} |")

lines += ["","## Interpretation","",
"- Breakouts date+zone match is the strongest signal WPBR changes did not bleed into classic BRT BO path.",
"- Zones: +/-$0.02 multiset vs sheet; eng<->prior compares new run to last deep-reconcile stamp.",
"- Trades: entry price +/-$0.05 with trigger/entry-date proximity; sheet Trigger Date ~= engine MATURITY_DATE.",
"- Pre-existing known gaps: NVDA early BO cluster, AU small BO diffs, TSLA sheet-only trades on some pastes.",
""]
bo_full=sum(1 for _,_,b,_,_,_ in details if b["sheet_n"] and b["matched"]==b["sheet_n"])
z_full=sum(1 for _,z,_,_,_,_ in details if z["sheet_n"] and z["matched"]==z["sheet_n"])
t_full=sum(1 for _,_,_,t,_,_ in details if t["sheet_n"] and t["matched"]==t["sheet_n"])
lines.append(f"## Bottom line: PASS={stats.get('PASS',0)} NEAR={stats.get('NEAR',0)} ZONES_OK={stats.get('ZONES_OK',0)} FAIL={stats.get('FAIL',0)} / {len(MARKTEN)}")
lines.append(f"- Layer full-match counts: zones {z_full}/10, BOs {bo_full}/10, trades {t_full}/10")
md="\n".join(lines)+"\n"
outp=OUT/f"MARKTEN_classic_BRT_reconcile_{STAMP}.md"
outp.write_text(md, encoding="utf-8")
print(md)
print("Wrote", outp)
