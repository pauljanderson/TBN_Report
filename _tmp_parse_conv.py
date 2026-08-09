from pathlib import Path
import re
from html.parser import HTMLParser

pe = Path(r"C:\Users\songg\Downloads\stockresearch\drive\paul_experiments")

class TableExtract(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self._in_table = False
        self._in_tr = False
        self._in_cell = False
        self._cell_tag = None
        self._cur_table = None
        self._cur_row = None
        self._cur_cell = []
        self._capture = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table":
            self._in_table = True
            self._cur_table = {"cls": attrs.get("class",""), "rows": []}
        elif self._in_table and tag == "tr":
            self._in_tr = True
            self._cur_row = []
        elif self._in_table and tag in ("td","th"):
            self._in_cell = True
            self._cell_tag = tag
            self._cur_cell = []
        elif tag == "br" and self._in_cell:
            self._cur_cell.append(" | ")

    def handle_endtag(self, tag):
        if tag in ("td","th") and self._in_cell:
            text = "".join(self._cur_cell).strip()
            text = re.sub(r"\s+", " ", text)
            self._cur_row.append(text)
            self._in_cell = False
        elif tag == "tr" and self._in_tr:
            if self._cur_row:
                self._cur_table["rows"].append(self._cur_row)
            self._in_tr = False
        elif tag == "table" and self._in_table:
            self.tables.append(self._cur_table)
            self._in_table = False

    def handle_data(self, data):
        if self._in_cell:
            self._cur_cell.append(data)

for name in ["All_Systems_Convergence_LatestRun.html", "SB_System_Convergence_LatestRun.html"]:
    html = (pe / name).read_text(encoding="utf-8", errors="replace")
    p = TableExtract()
    p.feed(html)
    print(f"\n======== {name} tables={len(p.tables)} ========")
    for i, t in enumerate(p.tables[:8]):
        rows = t["rows"]
        if not rows:
            continue
        header = " | ".join(rows[0][:12])
        if "Ann_ROR" in header or "System" in header or "stamp" in header.lower() or "Avg" in header:
            print(f"\n-- table {i} class={t['cls']!r} rows={len(rows)} --")
            print("HDR:", header)
            for r in rows[1:40]:
                print(" | ".join(r[:12]))
