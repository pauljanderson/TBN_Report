from pathlib import Path
p = Path(r"C:\Users\songg\Downloads\stockresearch\tools\run_spy_tc_strong_system.py")
lines = p.read_text(encoding="utf-8").splitlines()
for i, line in enumerate(lines[280:], start=281):
    print(f"{i}|{line}")
