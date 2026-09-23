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
SORTABLE_TH_CSS = """
th.sortable-th { position: relative; z-index: 3; pointer-events: auto; }
thead { position: relative; z-index: 3; }
"""

# Shared sort JS for investment + monthly (and anyone else who imports it).
# Event delegation + cellIndex so overflow-x wrappers and squeezed columns
# still sort on header click / Enter / Space. Same arrows / data-sort types.
SORTABLE_TABLE_SCRIPT = """
<script>
(function () {
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
    if (!t || !t.closest) return null;
    return t.closest("th.sortable-th");
  }
  document.addEventListener("click", function (e) {
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
