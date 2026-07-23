from pathlib import Path

src = Path(__file__).with_name("_reconcile_amzn_all.py")
dst = Path(__file__).with_name("_reconcile_meta_all.py")
t = src.read_text(encoding="utf-8")
t = t.replace("AMZN", "META").replace("amzn", "meta").replace("Amzn", "Meta")
t = t.replace(
    "WIN_END = datetime(2026, 7, 17).date()",
    "WIN_END = datetime(2026, 7, 21).date()",
)
t = t.replace('STAMP = "260720143523"', 'STAMP = "260721152237"')
# Tighten META paste detection (avoid false positives from other text)
t = t.replace(
    'and ("META\\nDate" in text or "META\\r\\nDate" in text or text.lstrip().startswith("META"))',
    'and ("META\\nDate\\tOpen" in text or "META\\r\\nDate\\tOpen" in text '
    'or text.lstrip().startswith("META\\nDate") or text.lstrip().startswith("META\\r\\nDate"))',
)
dst.write_text(t, encoding="utf-8")
print(f"wrote {dst} ({dst.stat().st_size} bytes)")
assert "AMZN" not in t
