from pathlib import Path
p = Path("_tmp_amzn_sc_20221208_diag.py")
lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
out = []
i = 0
while i < len(lines):
    # Drop the first broken em = entries[ ... ] block (uses bare | without parens)
    if lines[i].lstrip().startswith("em = entries[") and i + 2 < len(lines) and "| ((" in lines[i + 2]:
        # skip until closing ]
        while i < len(lines) and lines[i].strip() != "]":
            i += 1
        i += 1  # skip ]
        # skip following blank or comment about fix
        while i < len(lines) and (
            lines[i].strip() == ""
            or lines[i].lstrip().startswith("# fix operator")
        ):
            i += 1
        continue
    out.append(lines[i])
    i += 1
p.write_text("".join(out), encoding="utf-8")
print("patched lines", len(lines), "->", len(out))
