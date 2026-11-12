from pathlib import Path
p = Path("_tmp_amzn_sc_20221208_diag.py")
lines = p.read_text(encoding="utf-8").splitlines(True)
out = []
i = 0
while i < len(lines):
    if 'em = entries[' in lines[i] and i + 1 < len(lines) and 'ZONE_LOW' in lines[i+1] and '| ((' in "".join(lines[i:i+5]):
        # skip broken first assignment through its closing ]
        # find end of first em = block
        j = i
        while j < len(lines) and not (lines[j].strip() == "]" and "em =" not in lines[j]):
            j += 1
        # skip to after first ]
        j += 1
        # skip comment line about fix
        while j < len(lines) and (lines[j].strip().startswith("# fix") or lines[j].strip() == ""):
            if lines[j].strip().startswith("# fix"):
                j += 1
                break
            j += 1
        # keep the clean second em = block as-is (next lines)
        continue
    out.append(lines[i])
    i += 1
text = "".join(out)
# simpler: just rewrite the whole section by regex
import re
text = p.read_text(encoding="utf-8")
pat = r"    # entries near zone\n    if \"ZONE_LOW\" in entries.columns:\n        em = entries\[[\s\S]*?T.write\(em.to_string\(index=False\)\)\n"
repl = '''    # entries near zone
    if "ZONE_LOW" in entries.columns:
        em = entries[
            ((entries["ZONE_LOW"].astype(float).round(2) - ZL).abs() < 0.05)
            & ((entries["ZONE_HIGH"].astype(float).round(2) - ZH).abs() < 0.05)
        ]
        T.write(f"Entries matching zl/zh ~{ZL}/{ZH}: {len(em)}")
        if len(em):
            T.write(em.to_string(index=False))
'''
new, n = re.subn(pat, repl, text, count=1)
print("replacements", n)
if n != 1:
    # show context
    idx = text.find("# entries near zone")
    print(repr(text[idx:idx+500]))
    raise SystemExit(1)
p.write_text(new, encoding="utf-8")
print("ok")
