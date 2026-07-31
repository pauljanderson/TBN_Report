from pathlib import Path

p = Path(
    r"C:\Users\songg\.cursor\projects\c-Users-songg-Downloads-stockresearch\canvases\spy-tc-weak-ab-results.canvas.tsx"
)
s = p.read_text(encoding="utf-8")
rows = sum(1 for line in s.splitlines() if "horizon:" in line and "system:" in line)
print("absolute", str(p.resolve()))
print("data_rows", rows)
print("default_export", "export default function SpyTcWeakAbResults" in s)
print("only_cursor_canvas", s.count("from ") == 1 and 'from "cursor/canvas"' in s)
print("ts_helpers_ok", "computePatternStats" in s and "PatternStats()" not in s)
