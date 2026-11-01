"""Cache-bust, hard-reload, and shared sortable-table helpers for static HTML reports."""
from __future__ import annotations

import re

CACHE_META = """<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate"/>
<meta http-equiv="Pragma" content="no-cache"/>
<meta http-equiv="Expires" content="0"/>
"""

# GitHub Pages CDN may cache HTML despite meta tags; F5/Ctrl+R navigate with ?_=timestamp.
FORCE_RELOAD_SCRIPT = """<script>
(function () {
  "use strict";
  function cacheBustUrl() {
    var u = new URL(window.location.href);
    u.searchParams.set("_", String(Date.now()));
    return u.toString();
  }
  function forceHardReload(ev) {
    var k = ev.key;
    if (
      k === "F5" ||
      ((ev.ctrlKey || ev.metaKey) && (k === "r" || k === "R"))
    ) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
      window.location.replace(cacheBustUrl());
    }
  }
  window.addEventListener("keydown", forceHardReload, true);
  window.addEventListener("pageshow", function (ev) {
    if (ev.persisted) {
      window.location.replace(cacheBustUrl());
    }
  });
})();
</script>
"""

# Extra click-target rules for wide / horizontally scrollable tables.
# Pair with generator th.sortable-th hover styles; do not invent a new sort UX.
_SORTABLE_CLICK_CSS = """
th.sortable-th { pointer-events: auto; touch-action: manipulation; cursor: pointer; }
.sort-ind { display:inline-block; width:0.9em; margin-left:4px; color:#94a3b8; font-size:10px; }
th.sort-asc .sort-ind::after { content:"\\25B2"; color:#4c1d95; }
th.sort-desc .sort-ind::after { content:"\\25BC"; color:#4c1d95; }
"""

# Phone layout for data tables. Horizontal scroll plus a sticky first column
# (the row label). Do not turn the table into a card stack. Sort JS still
# pins tr.total-row and tr.table-total. Inject this inside <style>, and wrap
# each data table in <div class="table-wrap"> (legacy class "scroll" or "wrap"
# is accepted). One caption is enough: SWIPE_NOTE_HTML.
RESPONSIVE_TABLE_CSS = """
/* report-table-responsive */
.table-wrap, .scroll, .wrap {
  overflow: auto;
  max-height: calc(100vh - 8rem);
  width: 100%;
  -webkit-overflow-scrolling: touch;
}
.swipe-note { font-size: 12px; color: #64748b; margin: 4px 0 10px; }
table.sortable {
  width: 100%;
  border-collapse: collapse;
}
table.sortable th,
table.sortable td {
  border: 1px solid #d8dee9;
  padding: 6px 8px;
}
table.sortable thead th,
table.sortable > thead > tr > th.sortable-th {
  position: sticky;
  top: 0;
  background: #f8fafc;
  z-index: 2;
}
table.sortable th[data-sort="num"] { text-align: right; }
table.sortable > tbody > tr > td:first-child,
table.sortable > tbody > tr > th:first-child {
  position: sticky;
  left: 0;
  z-index: 1;
  background: #fff;
  box-shadow: 2px 0 0 rgba(0, 0, 0, 0.06);
}
table.sortable > thead > tr > th:first-child,
table.sortable > thead > tr > th.sortable-th:first-child {
  position: sticky;
  top: 0;
  left: 0;
  z-index: 4;
  background: #f8fafc;
}
table.sortable tr.total-row > td:first-child,
table.sortable tr.total-row > th:first-child,
table.sortable tr.table-total > td:first-child,
table.sortable tr.table-total > th:first-child {
  z-index: 2;
  background: #f8fafc;
}
table.sortable tbody tr:hover td,
table.sortable tbody tr:hover th {
  background: #f1f5f9;
}
@media (max-width: 800px) {
  .table-wrap table.sortable,
  .scroll table.sortable,
  .wrap table.sortable {
    width: max-content;
    min-width: 100%;
  }
  .table-wrap th, .table-wrap td,
  .scroll th, .scroll td,
  .wrap th, .wrap td {
    padding: 4px 6px;
    font-size: 12px;
  }
}
"""

SORTABLE_TH_CSS = _SORTABLE_CLICK_CSS + RESPONSIVE_TABLE_CSS

SWIPE_NOTE_HTML = '<p class="swipe-note">Swipe sideways to see more columns.</p>'

# Run once from the shared sort script so a forgotten wrapper still scrolls.
ENSURE_TABLE_WRAP_JS = """
  function ensureTableWraps() {
    document.querySelectorAll("table.sortable").forEach(function (table) {
      var parent = table.parentElement;
      if (!parent || !parent.classList) return;
      var cls = parent.classList;
      if (cls.contains("table-wrap") || cls.contains("scroll") || cls.contains("wrap")) return;
      var div = document.createElement("div");
      div.className = "table-wrap";
      parent.insertBefore(div, table);
      div.appendChild(table);
    });
  }
  function alignNumericColumns() {
    document.querySelectorAll("table.sortable").forEach(function (table) {
      var headRow = table.tHead && table.tHead.rows[0];
      if (!headRow || !table.tBodies[0]) return;
      var idx = [];
      for (var i = 0; i < headRow.cells.length; i++) {
        if (headRow.cells[i].getAttribute("data-sort") === "num") idx.push(i);
      }
      if (!idx.length) return;
      Array.prototype.forEach.call(table.tBodies[0].rows, function (tr) {
        idx.forEach(function (i) {
          if (tr.cells[i]) tr.cells[i].style.textAlign = "right";
        });
      });
    });
  }
  function bootTables() {
    ensureTableWraps();
    alignNumericColumns();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootTables);
  } else {
    bootTables();
  }
"""

# Shared sort JS for investment + monthly (and anyone else who imports it).
# Event delegation + cellIndex so overflow-x wrappers and squeezed columns
# still sort on header click / Enter / Space. Same arrows / data-sort types.
SORTABLE_TABLE_SCRIPT = """
<script>
(function () {
""" + ENSURE_TABLE_WRAP_JS + """
  var MONTHS = {
    january:1, february:2, march:3, april:4, may:5, june:6,
    july:7, august:8, september:9, october:10, november:11, december:12
  };
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : 0;
    if (type === "text") return s.toUpperCase();
    if (type === "month") {
      var key = s.toLowerCase().split(/\\s/)[0];
      return MONTHS[key] || 0;
    }
    if (type === "date") {
      var iso = s.match(/(\\d{4})-(\\d{2})-(\\d{2})/);
      if (iso) return parseInt(iso[1] + iso[2] + iso[3], 10);
      // Compact YYYYMMDD (VZ TRIGGER_DATE, RS/BRT DATE, RSI ASOF_DATE, etc.)
      var ymd = s.match(/^(\\d{8})$/);
      if (ymd) return parseInt(ymd[1], 10);
      var mdy = s.match(/(\\d{1,2})\\/(\\d{1,2})\\/(\\d{4})/);
      if (mdy) return parseInt(mdy[3] + mdy[1].padStart(2, "0") + mdy[2].padStart(2, "0"), 10);
      return 0;
    }
    var n = s.replace(/[$,%+]/g, "").replace(/,/g, "");
    var v = parseFloat(n);
    return Number.isFinite(v) ? v : 0;
  }
  function sortTable(table, col, type, dir) {
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll("tr"));
    var pinned = rows.filter(function (r) {
      return r.classList.contains("total-row") || r.classList.contains("table-total");
    });
    var movable = rows.filter(function (r) {
      return !r.classList.contains("total-row") && !r.classList.contains("table-total");
    });
    movable.sort(function (a, b) {
      var av = parseSortValue(a.cells[col] && a.cells[col].textContent, type);
      var bv = parseSortValue(b.cells[col] && b.cells[col].textContent, type);
      if (typeof av === "string" || typeof bv === "string") {
        return dir * String(av).localeCompare(String(bv));
      }
      return dir * (av - bv);
    });
    movable.concat(pinned).forEach(function (r) { tbody.appendChild(r); });
    var wrap = table.closest(".table-wrap, .scroll, .wrap");
    if (wrap) wrap.scrollTop = 0;
  }
  function headerCol(th) {
    if (typeof th.cellIndex === "number" && th.cellIndex >= 0) return th.cellIndex;
    var tr = th.parentElement;
    if (!tr) return 0;
    return Array.prototype.indexOf.call(tr.children, th);
  }
  var lastAt = 0;
  var lastTh = null;
  function onActivate(th) {
    var table = th.closest("table.sortable");
    if (!table) return;
    var now = Date.now();
    if (lastTh === th && now - lastAt < 400) return;
    lastTh = th;
    lastAt = now;
    var col = headerCol(th);
    var type = th.getAttribute("data-sort") || "text";
    var dir = th.getAttribute("data-dir") === "asc" ? -1 : 1;
    table.querySelectorAll("th.sortable-th").forEach(function (h) {
      h.setAttribute("data-dir", "");
      h.classList.remove("sort-asc", "sort-desc");
      h.setAttribute("aria-sort", "none");
    });
    th.setAttribute("data-dir", dir === 1 ? "asc" : "desc");
    th.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
    th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
    sortTable(table, col, type, dir);
  }
  function headerFromEvent(e) {
    var t = e.target;
    if (t && t.closest) {
      var direct = t.closest("th.sortable-th");
      if (direct) return direct;
    }
    if (typeof e.clientX !== "number" || typeof e.clientY !== "number") return null;
    var best = null;
    var bestZ = -Infinity;
    var bestArea = Infinity;
    var list = document.querySelectorAll("table.sortable th.sortable-th");
    for (var i = 0; i < list.length; i++) {
      var th = list[i];
      var r = th.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) continue;
      if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) continue;
      var z = parseInt(window.getComputedStyle(th).zIndex, 10);
      if (!isFinite(z)) z = 0;
      var area = r.width * r.height;
      if (!best || z > bestZ || (z === bestZ && area < bestArea)) {
        best = th;
        bestZ = z;
        bestArea = area;
      }
    }
    return best;
  }
  document.addEventListener("click", function (e) {
    var th = headerFromEvent(e);
    if (!th) return;
    onActivate(th);
  });
  document.addEventListener("pointerup", function (e) {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    var th = headerFromEvent(e);
    if (!th) return;
    onActivate(th);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Enter" && e.key !== " ") return;
    var th = headerFromEvent(e);
    if (!th) return;
    e.preventDefault();
    onActivate(th);
  });
})();
</script>
"""

_HEAD_EXTRAS_MARKER = "no-cache, no-store, must-revalidate"


def inject_report_page_extras(html: str) -> str:
    """Add cache meta + F5 hard-reload script immediately after <head>."""
    if _HEAD_EXTRAS_MARKER in html and "cacheBustUrl" in html:
        return html
    extras = CACHE_META + FORCE_RELOAD_SCRIPT
    if re.search(r"<head\b", html, flags=re.I):
        if _HEAD_EXTRAS_MARKER in html and "cacheBustUrl" not in html:
            return re.sub(r"(</head>)", FORCE_RELOAD_SCRIPT + r"\1", html, count=1, flags=re.I)
        if _HEAD_EXTRAS_MARKER not in html:
            return re.sub(r"(<head[^>]*>)", r"\1\n" + extras, html, count=1, flags=re.I)
        return html
    return extras + html
