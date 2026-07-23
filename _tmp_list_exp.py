from pathlib import Path
root = Path(r"C:\Users\songg\Downloads\stockresearch\drive\davey_experiments\spy_tc_strong_system")
print("exists", root.exists())
for p in sorted(root.rglob("*"))[:80]:
    print(p.relative_to(root))
