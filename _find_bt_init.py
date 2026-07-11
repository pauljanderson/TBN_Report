from pathlib import Path
import re

t = Path("stock_analysis/rocket_MTS.py").read_text(encoding="utf-8")
for m in re.finditer(r"^\s*_acc_bt\(\"bt_init\"", t, re.M):
    line = t[: m.start()].count("\n") + 1
    print("bt_init at line", line)
