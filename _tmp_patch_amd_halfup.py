from pathlib import Path

p = Path(r"C:\Users\songg\Downloads\stockresearch\_tmp_amd_startfloor_reconcile.py")
text = p.read_text(encoding="utf-8")

text = text.replace(
    '"""AMD-only reconcile vs startfloor stamp 260722161242. Diagnose-only; no commit."""',
    '"""AMD-only reconcile vs startfloor+halfup stamp 260722165827. Diagnose-only; no commit."""',
    1,
)

if "import json" not in text:
    text = text.replace("from pathlib import Path", "import json\nfrom pathlib import Path", 1)

old_eng = "_markten_variantC_SC_stop91_startfloor_2016_20260722161052"
new_eng = "_markten_variantC_SC_stop91_startfloor_halfup_20260722165815"
text = text.replace(old_eng, new_eng)
text = text.replace('STAMP = "260722161242"', 'STAMP = "260722165827"', 1)

old_settings = (
    '        "**Settings:** variant C + SC-on + `stop_pct=0.91` + `start_date=2016-01-01` "\n'
    '        "+ **pivot startfloor** (`PIVOT_MONDAY >= 2016-01-01`)."'
)
new_settings = (
    '        "**Settings:** variant C + SC-on + `stop_pct=0.91` + `start_date=2016-01-01` "\n'
    '        "+ **pivot startfloor** (`PIVOT_MONDAY >= 2016-01-01`) + **half-up rounding** "\n'
    '        "(zone/pivot HALF_UP; halfup stamp)."'
)
if old_settings not in text:
    raise SystemExit("settings block not found:\n" + repr(text[text.find("Settings")-5:text.find("Settings")+250]))
text = text.replace(old_settings, new_settings, 1)

if "startfloor + halfup" not in text:
    text = text.replace(
        "variant C + SC-on + startfloor (`{STAMP}`)",
        "variant C + SC-on + startfloor + halfup (`{STAMP}`)",
    )

text = text.replace(
    'f"*Generated vs stamp `{STAMP}` (startfloor). Diagnose-only. No commit.*"',
    'f"*Generated vs stamp `{STAMP}` (startfloor + halfup). Diagnose-only. No commit.*"',
)

marker = '    print("PARENT_SUMMARY")'
if "AMD_startfloor_" not in text:
    if marker not in text:
        raise SystemExit("PARENT_SUMMARY marker not found")
    insert = '''    parent_path = BASE / f"AMD_startfloor_{STAMP}_parent_summary.json"
    parent_json = {
        "symbol": "AMD",
        "stamp": STAMP,
        "stamp_dir": str(OUT),
        "sc_in_run_log": eng_conf.get("sc_in_run_log"),
        "startfloor": True,
        "halfup": True,
        "pivots": fair["pivots_match"],
        "zones": fair["zones_ok"],
        "retest": fair["retest_ok"],
        "rocket_sheet_fires": fair["rocket_where_sheet_fires"],
        "raw": r["raw"],
        "ser": r["ser"],
        "closed_n": r["closed_n"],
        "sheet_trades": r["n_sheet_trades"],
        "raw_orphans": r["raw_orphans"],
        "ser_orphans": r["ser_orphans"],
        "exit_forks": len(forks),
        "full_identity": f"{full}/{r['n_sheet_trades']}",
        "early6_gone": len(early_present) == 0,
        "early6_still": early_present,
        "eng_only": eng_only,
        "sheet_only": sheet_only,
        "stacked_eng": eng_stack,
        "stacked_sheet": sh_stack,
        "status_md": str(status_path),
        "stacked_path": str(stack_path),
    }
    parent_path.write_text(json.dumps(parent_json, indent=2, default=str), encoding="utf-8")
    parent["parent_summary_json"] = str(parent_path)

'''
    text = text.replace(marker, insert + marker, 1)

p.write_text(text, encoding="utf-8")
print("OK")
print("halfup OUT", new_eng in text)
print("STAMP", 'STAMP = "260722165827"' in text)
print("settings halfup", "half-up rounding" in text)
print("title halfup", "startfloor + halfup" in text)
print("parent json", "AMD_startfloor_" in text)
print("json import", "import json" in text)
