"""Cache-bust and hard-reload helpers for static HTML reports (GitHub Pages)."""
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
