"""Generate tools/_reconcile_msft_all.py from the AMD template."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = (ROOT / "tools" / "_reconcile_amd_all.py").read_text(encoding="utf-8")

# Order matters: do specific replacements before blanket AMD->MSFT
text = src
text = text.replace("260720165857", "260720143523")
text = text.replace("1/4/2010\t$9.7900", "1/4/2010\t$30.6500")
text = text.replace("here is some data for your AMD reconiciling", "__DROP_AMD_MARKER__")
text = text.replace("AMD", "MSFT")
text = text.replace("amd", "msft")
text = text.replace("datetime(2026, 7, 17).date()", "datetime(2026, 7, 20).date()")

# Replace extract_paste entirely
start = text.find("def extract_paste()")
end = text.find("def ensure_exports")
assert start > 0 and end > start, (start, end)

new_extract = r'''def extract_paste() -> str:
    """Prefer the latest full MSFT paste (OHLC + zones + BOs + trades)."""
    latest = None
    for line in TRANSCRIPT.read_text(encoding="utf-8").splitlines():
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("role") != "user":
            continue
        content = obj.get("message", {}).get("content", [])
        texts = []
        if isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text":
                    texts.append(c.get("text", ""))
        elif isinstance(content, str):
            texts.append(content)
        blob = "\n".join(texts)
        has_sections = (
            "Matured touch price" in blob
            and "Breakout Date" in blob
            and "Trigger Date" in blob
            and "Date\tOpen\tHigh\tLow\tClose" in blob
        )
        is_msft = (
            "MSFT\nDate\tOpen" in blob
            or "MSFT\r\nDate\tOpen" in blob
            or ("1/4/2010\t$30.6500" in blob and has_sections)
        )
        if has_sections and is_msft:
            latest = blob
    if not latest:
        raise SystemExit("MSFT paste not found in transcript")
    if "<user_query>" in latest:
        latest = latest[latest.find("<user_query>") + len("<user_query>") :]
    if "</user_query>" in latest:
        latest = latest[: latest.find("</user_query>")]
    latest = latest.strip()
    if latest.startswith("MSFT\n") or latest.startswith("MSFT\r\n"):
        first, _, rest = latest.partition("\n")
        if first.strip() == "MSFT" and rest:
            latest = rest
    if "Date\tOpen\tHigh\tLow\tClose" in latest:
        latest = latest[latest.find("Date\tOpen\tHigh\tLow\tClose") :]
    return latest


'''
text = text[:start] + new_extract + text[end:]

# Replace OHLC check
start = text.find("def check_2018_05_18")
if start < 0:
    start = text.find("def check_critical_bars")
end = text.find("def pick_trades_stamp")
assert start > 0 and end > start, (start, end)

new_ohlc = r'''def check_critical_bars():
    """Spot-check a few sheet OHLC bars vs engine MSFT.csv."""
    want_dates = ["2010-01-04", "2013-04-24", "2020-04-13", "2022-04-01"]
    sheet = {}
    with (OUT / "MSFT_sheet_ohlc.csv").open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            d = r.get("date")
            if d in want_dates:
                sheet[d] = (
                    float(r["open"]),
                    float(r["high"]),
                    float(r["low"]),
                    float(r["close"]),
                )
    eng = {}
    if MSFT_CSV.exists():
        with MSFT_CSV.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                d = (r.get("Date") or r.get("date") or "").strip()[:10]
                if d in want_dates:
                    eng[d] = (
                        round(float(r.get("Open") or r.get("open")), 4),
                        round(float(r.get("High") or r.get("high")), 4),
                        round(float(r.get("Low") or r.get("low")), 4),
                        round(float(r.get("Close") or r.get("close")), 4),
                    )
    mismatches = []
    checked = []
    for d, sbar in sheet.items():
        ebar = eng.get(d)
        if ebar is None:
            mismatches.append((d, sbar, None))
            continue
        ok = all(abs(round(a, 2) - round(b, 2)) <= 0.02 for a, b in zip(sbar, ebar))
        checked.append((d, sbar, ebar, ok))
        if not ok:
            mismatches.append((d, sbar, ebar))
    status = "MATCH" if checked and not mismatches else ("MISMATCH" if mismatches else "MISSING")
    return {
        "checked": checked,
        "mismatches": mismatches,
        "status": status,
        "sheet": sheet,
        "engine": eng,
    }


'''
text = text[:start] + new_ohlc + text[end:]

text = text.replace("ohlc_check = check_2018_05_18()", "ohlc_check = check_critical_bars()")
text = text.replace(
    'print("OHLC_2018_05_18", ohlc_check)',
    'print("OHLC_CHECK", ohlc_check.get("status"), ohlc_check.get("checked"))',
)

# Summary OHLC narrative
old_narr = '''    if ohlc_check.get("status") == "MATCH":
        lines.append(
            "- **2018-05-18 fix:** sheet bar now matches engine (`$13.06/$13.26/$12.91/$13.00`). "
            "Prior miss (sheet copy of 5/17) is resolved."
        )
    else:
        lines.append(
            f"- **2018-05-18 still mismatched:** sheet `{ohlc_check.get('sheet')}` vs engine `{ohlc_check.get('engine')}`."
        )
'''
new_narr = '''    if ohlc_check.get("status") == "MATCH":
        lines.append("- **OHLC spot-check:** sheet vs engine trading-day bars match at +/- $0.02.")
    elif ohlc_check.get("mismatches"):
        lines.append(f"- **OHLC mismatches:** {ohlc_check.get('mismatches')}")
    else:
        lines.append("- **OHLC spot-check:** incomplete (bars missing).")
'''
if old_narr in text:
    text = text.replace(old_narr, new_narr)
else:
    # fallback: already partially rewritten
    text = text.replace("2018-05-18 fix", "OHLC spot-check")
    text = text.replace("2018-05-18 still mismatched", "OHLC still mismatched")

text = text.replace(
    'f"- **2018-05-18 OHLC check:** sheet `{ohlc_check.get(\'sheet\')}` vs engine `{ohlc_check.get(\'engine\')}` -> **{ohlc_check.get(\'status\')}**",',
    'f"- **OHLC spot-check:** **{ohlc_check.get(\'status\')}** ({len(ohlc_check.get(\'checked\') or [])} bars)",',
)

# argparse: zones from 143523 (has ZONES file); BO/trades from default four-scenario
text = text.replace(
    '''    ap.add_argument("--zones-stamp", default="260720143523")
    ap.add_argument("--bo-stamp", default="260720143523")
''',
    '''    ap.add_argument("--zones-stamp", default="260720143523")
    ap.add_argument("--bo-stamp", default="260720165358")
''',
)
text = text.replace(
    'tstamp = pick_trades_stamp(args.trades_stamp or "260720143523")',
    'tstamp = pick_trades_stamp(args.trades_stamp or "260720165358")',
)

# Fix leftover drop marker in extract if any remained elsewhere
text = text.replace("__DROP_AMD_MARKER__", "MSFT_UNUSED_MARKER")

# Docstring
text = text.replace(
    "Reconcile MSFT BRT sheet (transcript paste) vs engine stamps 260720143523 (zones) / 260720165358 (BO+trades).",
    "Reconcile MSFT BRT sheet (transcript paste) vs engine.",
)
if "Reconcile MSFT BRT sheet" not in text[:200]:
    text = text.replace(
        "Reconcile MSFT BRT sheet (transcript paste) vs engine stamp 260720143523.",
        "Reconcile MSFT BRT sheet vs engine (zones 260720143523, BO/trades 260720165358).",
    )

out = ROOT / "tools" / "_reconcile_msft_all.py"
out.write_text(text, encoding="utf-8")
print("wrote", out)
print("AMD leftover", text.count("AMD"), "amd leftover", text.lower().count("amd"))
print("size", out.stat().st_size)
