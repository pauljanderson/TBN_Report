#!/usr/bin/env python3
"""Regenerate Twin Beacon Networks (TBN) New Systems away-status HTML for Drive/phone.

Writes:
  drive/paul_experiments/tbn_new_systems/AWAY_STATUS.html
  drive/TBN_New_Systems_AWAY_STATUS.html  (Drive-root convenience copy)

Idempotent. Scans tbn_new_systems/ for HOW_TO_RUN / RESEARCH / ab_* comparison artifacts.
"""
from __future__ import annotations

import html as html_mod
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TBN_ROOT = REPO / "drive" / "paul_experiments" / "tbn_new_systems"
OUT_NESTED = TBN_ROOT / "AWAY_STATUS.html"
OUT_DRIVE_ROOT = REPO / "drive" / "TBN_New_Systems_AWAY_STATUS.html"

BADGE_CLASS = {
    "DONE": "badge-done",
    "IN PROGRESS": "badge-prog",
    "RESEARCH": "badge-research",
    "HOLD": "badge-hold",
    "STUB": "badge-stub",
}


@dataclass
class DocLink:
    label: str
    rel: str  # path relative to TBN_ROOT


@dataclass
class AbSuite:
    system_id: str
    name: str
    rel_dir: str
    arms: int = 0
    stamps: list[str] = field(default_factory=list)
    comparison: str | None = None
    readme: str | None = None
    verdict: str = ""
    control_stamp: str = ""
    control_pnl: str = ""
    best_arm: str = ""
    mtime: float = 0.0


@dataclass
class SystemCard:
    key: str
    title: str
    folder: str
    badge: str
    summary: str
    links: list[DocLink] = field(default_factory=list)
    run_cmds: list[str] = field(default_factory=list)


def _esc(s: str) -> str:
    return html_mod.escape(s, quote=True)


def _exists_any(folder: Path, names: list[str]) -> Path | None:
    for n in names:
        p = folder / n
        if p.is_file():
            return p
    return None


def _rel_to_tbn(path: Path) -> str:
    return path.relative_to(TBN_ROOT).as_posix()


def _href(rel_from_tbn: str, prefix: str) -> str:
    rel_from_tbn = rel_from_tbn.replace("\\", "/").lstrip("/")
    if not prefix:
        return rel_from_tbn
    return f"{prefix.rstrip('/')}/{rel_from_tbn}"


def _discover_links(folder: Path) -> list[DocLink]:
    links: list[DocLink] = []
    if not folder.is_dir():
        return links
    pairs = [
        ("HOW_TO_RUN.html", "How to run"),
        ("HOW_TO_RUN.md", "How to run (md)"),
        ("RESEARCH.html", "Research"),
        ("RESEARCH.md", "Research (md)"),
        ("README.md", "README"),
        ("DNA.md", "DNA"),
        ("10_theory.md", "Theory"),
        ("95_finalize.md", "Finalize"),
        ("SB_NEXT_BUILDS.html", "Next builds"),
        ("GOLD_UNIVERSE.md", "Gold universe"),
        ("STATUS_SNIPPET.md", "Status snippet"),
    ]
    seen_labels: set[str] = set()
    for fname, label in pairs:
        p = folder / fname
        if not p.is_file():
            continue
        # Prefer HTML over md for same logical label
        base_label = label.replace(" (md)", "")
        if base_label in seen_labels and fname.endswith(".md"):
            continue
        if fname.endswith(".html"):
            seen_labels.add(base_label)
            links.append(DocLink(base_label, _rel_to_tbn(p)))
        else:
            if base_label not in seen_labels:
                seen_labels.add(base_label)
                links.append(DocLink(label, _rel_to_tbn(p)))
    # AB comparisons
    for ab in sorted(folder.glob("ab_*")):
        if not ab.is_dir():
            continue
        cmp_html = ab / "comparison.html"
        if cmp_html.is_file():
            links.append(DocLink(f"AB {ab.name}", _rel_to_tbn(cmp_html)))
        elif (ab / "README.md").is_file():
            links.append(DocLink(f"AB {ab.name}", _rel_to_tbn(ab / "README.md")))
    return links


def _parse_ab_readme(text: str) -> tuple[str, str, str, str]:
    """Return (verdict_line, control_stamp, control_pnl, best_arm)."""
    verdict = ""
    m = re.search(
        r"##\s*Verdict\s*\n+(.*?)(?:\n##|\Z)",
        text,
        flags=re.I | re.S,
    )
    if m:
        lines = [
            ln.strip(" -*")
            for ln in m.group(1).splitlines()
            if ln.strip() and not ln.strip().startswith("|")
        ]
        verdict = " ".join(lines[:3])[:280]

    control_stamp = ""
    control_pnl = ""
    best_arm = ""
    m2 = re.search(r"Control PnL:\s*\*\*([0-9.+-]+)\*\*.*?`(\d{12})`", text, re.I | re.S)
    if m2:
        control_pnl = m2.group(1)
        control_stamp = m2.group(2)
    else:
        m2b = re.search(
            r"`00_control`\s*\|\s*`(\d{12})`\s*\|[^|]*\|[^|]*\|\s*([0-9.+-]+)",
            text,
        )
        if m2b:
            control_stamp = m2b.group(1)
            control_pnl = m2b.group(2)

    m3 = re.search(r"Best gated arm[^`]*`([^`]+)`", text, re.I)
    if m3:
        best_arm = m3.group(1)
    return verdict, control_stamp, control_pnl, best_arm


def _discover_ab_suites() -> list[AbSuite]:
    suites: list[AbSuite] = []
    if not TBN_ROOT.is_dir():
        return suites
    for system_dir in sorted(p for p in TBN_ROOT.iterdir() if p.is_dir()):
        for ab in sorted(system_dir.glob("ab_*")):
            if not ab.is_dir():
                continue
            arms = [d for d in ab.iterdir() if d.is_dir() and not d.name.startswith(".")]
            stamps: list[str] = []
            for arm in arms:
                st = arm / "STAMP.txt"
                if st.is_file():
                    raw = st.read_text(encoding="utf-8", errors="replace")
                    mm = re.search(r"stamp\s*=\s*(\d{12})", raw, re.I)
                    if mm:
                        stamps.append(mm.group(1))
                else:
                    for f in arm.glob("*_*_*.csv"):
                        mm = re.search(r"_(\d{12})\.", f.name)
                        if mm:
                            stamps.append(mm.group(1))
                            break
            cmp_rel = None
            if (ab / "comparison.html").is_file():
                cmp_rel = _rel_to_tbn(ab / "comparison.html")
            readme_rel = None
            verdict = control_stamp = control_pnl = best_arm = ""
            if (ab / "README.md").is_file():
                readme_rel = _rel_to_tbn(ab / "README.md")
                text = (ab / "README.md").read_text(encoding="utf-8", errors="replace")
                verdict, control_stamp, control_pnl, best_arm = _parse_ab_readme(text)
            # Meaningful only if comparison, readme with content, or arm stamps
            has_payload = bool(cmp_rel or stamps or (readme_rel and verdict))
            mtime = ab.stat().st_mtime
            if (ab / "comparison.html").is_file():
                mtime = max(mtime, (ab / "comparison.html").stat().st_mtime)
            suites.append(
                AbSuite(
                    system_id=system_dir.name,
                    name=ab.name,
                    rel_dir=_rel_to_tbn(ab),
                    arms=len(arms),
                    stamps=sorted(set(stamps)),
                    comparison=cmp_rel,
                    readme=readme_rel,
                    verdict=verdict,
                    control_stamp=control_stamp,
                    control_pnl=control_pnl,
                    best_arm=best_arm,
                    mtime=mtime,
                )
            )
            if not has_payload:
                # Keep empty scaffolds visible but mark in verdict
                if not suites[-1].verdict:
                    suites[-1].verdict = "Empty AB shell (no stamps / comparison yet)."
    suites.sort(key=lambda s: (-s.mtime, s.system_id, s.name))
    return suites


def _folder_state(folder: Path) -> dict:
    files = []
    if folder.is_dir():
        files = [
            p.name
            for p in folder.iterdir()
            if p.is_file() and p.name.lower() != "desktop.ini"
        ]
    return {
        "exists": folder.is_dir(),
        "files": files,
        "has_howto": bool(_exists_any(folder, ["HOW_TO_RUN.html", "HOW_TO_RUN.md"])),
        "has_research": bool(_exists_any(folder, ["RESEARCH.html", "RESEARCH.md"])),
        "has_theory": (folder / "10_theory.md").is_file() if folder.is_dir() else False,
        "has_finalize": (folder / "95_finalize.md").is_file() if folder.is_dir() else False,
        "has_dna": (folder / "DNA.md").is_file() if folder.is_dir() else False,
        "snippet": (
            (folder / "STATUS_SNIPPET.md").read_text(encoding="utf-8", errors="replace")
            if folder.is_dir() and (folder / "STATUS_SNIPPET.md").is_file()
            else ""
        ),
        "ab_dirs": (
            sorted(d.name for d in folder.glob("ab_*") if d.is_dir())
            if folder.is_dir()
            else []
        ),
    }


def _bat_exists(name: str) -> bool:
    return (REPO / name).is_file()


def _engine_exists(*rel_parts: str) -> bool:
    return (REPO.joinpath(*rel_parts)).is_file()


def _strip_md_inline(s: str) -> str:
    s = s.strip().strip("|").strip()
    s = re.sub(r"\\`", "`", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = s.replace("`", "").replace("\\", "")
    s = re.sub(r"\s*\|\s*", " — ", s)
    s = re.sub(r"\s+", " ", s).strip(" -—")
    return s


def _snippet_oneliner(snippet: str, fallback: str) -> str:
    """Prefer a concise line from STATUS_SNIPPET.md when present."""
    if not snippet:
        return fallback

    lines = snippet.splitlines()
    # Explicit one-liner blocks
    for i, line in enumerate(lines):
        if re.search(r"one-liner", line, re.I):
            for nxt in lines[i + 1 : i + 6]:
                t = nxt.strip().strip("`")
                if len(t) > 40 and ("run_" in t or "HOLD" in t or "research" in t.lower()):
                    return _strip_md_inline(t)[:320]

    # Snapshot / disposition table cells that mention run_ or DailyRun
    candidates: list[str] = []
    for line in lines:
        m = re.search(r"^\|([^|]+)\|([^|]+)\|?\s*$", line)
        if not m:
            continue
        cell = m.group(2).strip()
        if cell.lower() in {"value", "state", "----", "---"}:
            continue
        if len(cell) < 28:
            continue
        if any(k in cell for k in ("run_", "DailyRun", "HOLD", "standalone", "Research")):
            candidates.append(cell)
    if candidates:
        # Prefer longest informative cell
        best = max(candidates, key=len)
        cleaned = _strip_md_inline(best)
        if len(cleaned) >= 40:
            return cleaned[:320]

    return fallback


def _build_systems() -> list[SystemCard]:
    sb = TBN_ROOT / "stockbee_momentum_burst"
    mvcp = TBN_ROOT / "minervini_vcp"
    qull = TBN_ROOT / "qull_ep_htf"
    kell = TBN_ROOT / "kell_pac"
    oneil = TBN_ROOT / "oneil_canslim"

    sb_st = _folder_state(sb)
    mv_st = _folder_state(mvcp)
    qu_st = _folder_state(qull)
    ke_st = _folder_state(kell)
    on_st = _folder_state(oneil)

    gold_n = "?"
    gold_csv = sb / "GOLD_UNIVERSE.csv"
    if gold_csv.is_file():
        raw = gold_csv.read_text(encoding="utf-8", errors="replace").strip()
        gold_n = str(len([t for t in re.split(r"[,\s]+", raw) if t.strip()]))

    last_sb = ""
    ts_path = REPO / "drive" / "SB_last_run_ts.txt"
    if ts_path.is_file():
        last_sb = ts_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()[0]

    systems: list[SystemCard] = []

    # StockBee — usable / DailyRun wired
    sb_summary = (
        f"Momentum Burst engine usable: gold universe ({gold_n} names), "
        f"`run_sb.bat` / DailyRun step [10/14], host outputs SB_*. "
        f"Recent drive stamp {last_sb or 'n/a'}. "
        "Reconcile freeze: `sb_baseline_260803121109` (gold-56 Closed; replaces gold-97). "
        "Gate A/Bs (ATR/52w, MM+2Lynch, vol×50d) completed — none beat control on Total PnL."
    )
    systems.append(
        SystemCard(
            key="sb",
            title="StockBee (Momentum Burst)",
            folder="stockbee_momentum_burst",
            badge="DONE",
            summary=sb_summary,
            links=_discover_links(sb),
            run_cmds=[
                "run_sb.bat",
                "run_stockbee_burst.bat",
                "SB_ATR_52w_ab.bat",
                "SB_MM_2Lynch_ab.bat",
                "SB_Vol_ab.bat",
            ],
        )
    )

    # Minervini VCP — DailyRun wired (Theory knobs HOLD; promote despite challenge HOLD-on-knobs)
    if mv_st["has_howto"] and mv_st["has_finalize"]:
        mv_badge = "DONE"
        mv_summary = (
            "Minervini Specific Entry Point Analysis (SEPA) / Volatility Contraction Pattern (VCP) "
            "engine + HOW_TO_RUN; DailyRun step [11/14] via `run_mvcp.bat` (ALL universe; Theory knobs "
            "unchanged — RS≥80, vol 1.5×, depth_shrink 0.65, chase 5%, stop 0.92, target 1.25, "
            "time_stop 10, trail_arm 10%, cooldown 20). Reconcile freeze `260801215052`. "
            "Fundamentals deferred (OHLCV-only)."
        )
    elif mv_st["has_howto"]:
        mv_badge = "IN PROGRESS"
        mv_summary = "MVCP folder has HOW_TO_RUN but finalize incomplete."
    else:
        mv_badge = "STUB"
        mv_summary = "Minervini VCP folder missing expected docs."
    systems.append(
        SystemCard(
            key="mvcp",
            title="Minervini VCP (MVCP)",
            folder="minervini_vcp",
            badge=mv_badge,
            summary=mv_summary,
            links=_discover_links(mvcp),
            run_cmds=["run_mvcp.bat", "run_minervini_vcp.bat"],
        )
    )

    # Qull EP/HTF
    shortlist = TBN_ROOT / "02_qullamaggie_shortlist.md"
    qu_links = _discover_links(qull)
    if shortlist.is_file():
        qu_links.insert(0, DocLink("Shortlist", _rel_to_tbn(shortlist)))
    qu_cmds = [
        b
        for b in ("run_qull.bat", "run_qull_ab.bat", "run_qull_ab_prior_run.bat")
        if _bat_exists(b)
    ]
    qu_engine = _engine_exists("stock_analysis", "rocket_qull_ep_htf.py") or _engine_exists(
        "stock_analysis", "rocket_qull_htf.py"
    )
    if qu_st["has_howto"] and (qu_engine or qu_cmds):
        qu_badge = "IN PROGRESS"
        qu_fallback = (
            "Qullamaggie High Tight Flag (HTF) + Episodic Pivot (EP) proxy: research docs + runner present; "
            "DailyRun HOLD. True EP catalyst needs earnings/news (stubbed)."
        )
    elif qu_st["has_research"] or qu_st["has_howto"]:
        qu_badge = "RESEARCH"
        qu_fallback = "Qull EP/HTF research docs present; engine/runner incomplete."
    elif qu_st["exists"]:
        qu_badge = "STUB"
        qu_fallback = "Qull EP/HTF folder scaffold only."
    else:
        qu_badge = "STUB"
        qu_fallback = "Qull EP/HTF not started."
    systems.append(
        SystemCard(
            key="qull",
            title="Qull EP / HTF",
            folder="qull_ep_htf",
            badge=qu_badge,
            summary=_snippet_oneliner(qu_st["snippet"], qu_fallback),
            links=qu_links,
            run_cmds=qu_cmds,
        )
    )

    # Kell PAC
    ke_cmds = [b for b in ("run_kell.bat", "run_kell_ab.bat") if _bat_exists(b)]
    ke_engine = _engine_exists("stock_analysis", "rocket_kell_pac.py")
    if ke_st["has_howto"] and (ke_engine or ke_cmds):
        ke_badge = "IN PROGRESS"
        ke_fallback = (
            "Oliver Kell Price Action Cycle (PAC) / Wedge Pop: standalone research engine; "
            "not wired to rocket_tbn; DailyRun HOLD."
        )
    elif ke_st["has_research"] or ke_st["has_howto"]:
        ke_badge = "RESEARCH"
        ke_fallback = "Kell PAC research docs present; runner incomplete."
    elif ke_st["exists"]:
        ke_badge = "STUB"
        ke_fallback = "Folder kell_pac/ scaffold only."
    else:
        ke_badge = "STUB"
        ke_fallback = "Kell PAC not started."
    systems.append(
        SystemCard(
            key="kell",
            title="Kell PAC",
            folder="kell_pac",
            badge=ke_badge,
            summary=_snippet_oneliner(ke_st["snippet"], ke_fallback),
            links=_discover_links(kell),
            run_cmds=ke_cmds,
        )
    )

    # O'Neil CAN SLIM
    on_cmds = [b for b in ("run_canslim.bat", "run_canslim_ab.bat") if _bat_exists(b)]
    on_engine = _engine_exists("stock_analysis", "rocket_oneil_canslim.py")
    if on_st["has_howto"] and (on_engine or on_cmds):
        on_badge = "RESEARCH"
        on_fallback = (
            "William O'Neil CAN SLIM: price/RS/volume legs runnable (N/S/L/M); "
            "C/A/I soft-fill from yfinance DuckDB cache (gates default OFF); DailyRun HOLD."
        )
    elif on_st["has_research"] or on_st["has_howto"]:
        on_badge = "RESEARCH"
        on_fallback = "O'Neil CAN SLIM research docs present; runner incomplete."
    elif on_st["exists"]:
        on_badge = "STUB"
        on_fallback = (
            "Folder oneil_canslim/ scaffold only. Full CAN SLIM needs earnings data the OHLCV host lacks."
        )
    else:
        on_badge = "STUB"
        on_fallback = "O'Neil CAN SLIM not started."
    on_links = _discover_links(oneil)
    charter = TBN_ROOT / "00_PIPELINE_CHARTER.md"
    if charter.is_file():
        on_links.append(DocLink("Charter note", _rel_to_tbn(charter)))
    systems.append(
        SystemCard(
            key="oneil",
            title="O'Neil CAN SLIM",
            folder="oneil_canslim",
            badge=on_badge,
            summary=_snippet_oneliner(on_st["snippet"], on_fallback),
            links=on_links,
            run_cmds=on_cmds,
        )
    )
    return systems


def _sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{_esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


_SORTABLE_TABLE_SCRIPT = """
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : 0;
    if (type === "text") return s.toUpperCase();
    if (type === "date") {
      var iso = s.match(/(\\d{4})-(\\d{2})-(\\d{2})/);
      if (iso) return parseInt(iso[1] + iso[2] + iso[3], 10);
      var stamp = s.match(/(\\d{12})/);
      if (stamp) return parseInt(stamp[1], 10);
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
    var pinned = rows.filter(function (r) { return r.classList.contains("total-row"); });
    var movable = rows.filter(function (r) { return !r.classList.contains("total-row"); });
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
  function bindSortHeader(table, th, col) {
    function onActivate(e) {
      if (e.type === "touchend") e.preventDefault();
      var type = th.dataset.sort || "text";
      var dir = th.dataset.dir === "asc" ? -1 : 1;
      table.querySelectorAll("th.sortable-th").forEach(function (h) {
        h.dataset.dir = "";
        h.classList.remove("sort-asc", "sort-desc");
        h.setAttribute("aria-sort", "none");
      });
      th.dataset.dir = dir === 1 ? "asc" : "desc";
      th.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
      th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
      sortTable(table, col, type, dir);
    }
    th.addEventListener("click", onActivate);
    th.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onActivate(e); }
    });
    th.addEventListener("touchend", onActivate, { passive: false });
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("th.sortable-th").forEach(function (th, col) {
      bindSortHeader(table, th, col);
    });
  });
})();
</script>
"""


def _render_html(
    systems: list[SystemCard],
    suites: list[AbSuite],
    *,
    prefix: str,
    twin_note: str,
    now_local: str,
) -> str:
    def h(rel: str) -> str:
        return _esc(_href(rel, prefix))

    # Snapshot badges
    snap_cells = "".join(
        f'<tr><td data-label="System">{_esc(s.title)}</td>'
        f'<td data-label="Status"><span class="badge {BADGE_CLASS.get(s.badge, "badge-stub")}">'
        f"{_esc(s.badge)}</span></td>"
        f'<td data-label="Folder"><code>{_esc(s.folder)}</code></td></tr>\n'
        for s in systems
    )

    cards = []
    for s in systems:
        link_bits = []
        for lk in s.links:
            link_bits.append(f'<a href="{h(lk.rel)}">{_esc(lk.label)}</a>')
        # Always offer living STATUS + folder if present
        if (TBN_ROOT / s.folder).is_dir():
            link_bits.append(
                f'<a href="{h(s.folder + "/")}">Folder</a>'
            )
        links_html = " · ".join(link_bits) if link_bits else "<span class='muted'>No docs yet</span>"
        cmds = ""
        if s.run_cmds:
            cmds = (
                "<ul class='cmds'>"
                + "".join(f"<li><code>{_esc(c)}</code></li>" for c in s.run_cmds)
                + "</ul>"
            )
        cards.append(
            f"""
<section class="sys" id="{_esc(s.key)}">
  <div class="sys-head">
    <h2>{_esc(s.title)}</h2>
    <span class="badge {BADGE_CLASS.get(s.badge, "badge-stub")}">{_esc(s.badge)}</span>
  </div>
  <p class="sum">{_esc(s.summary)}</p>
  <p class="links">{links_html}</p>
  {cmds}
</section>"""
        )

    # What you can run today (only list bats that exist)
    run_today_candidates = [
        ("run_sb.bat", "StockBee gold universe (56) — production / DailyRun default"),
        ("run_stockbee_burst.bat", "Same as run_sb.bat (long name)"),
        ("run_mvcp.bat", "Minervini VCP ALL universe — production / DailyRun step [11/14]"),
        ("run_qull.bat", "Qull HTF / EP proxy seed run (DailyRun HOLD)"),
        ("run_qull_ab_prior_run.bat", "Qull A/B: prior-run floor sweep"),
        ("run_kell.bat", "Kell PAC Wedge Pop research run (standalone)"),
        ("run_kell_ab.bat", "Kell PAC A/B stub arms"),
        ("run_canslim.bat", "O'Neil CAN SLIM price-legs v0 (C/A/I stubbed)"),
        ("run_canslim_ab.bat", "CAN SLIM A/B: RS / pivot / volume"),
        ("SB_ATR_52w_ab.bat", "SB A/B: ATR% + distance to 52w high"),
        ("SB_MM_2Lynch_ab.bat", "SB A/B: Market Monitor + 2Lynch T-1 N"),
        ("SB_Vol_ab.bat", "SB A/B: volume vs prior 50d average"),
        ("update_tbn_away_status.bat", "Refresh this away-status page"),
    ]
    run_today = [(c, n) for c, n in run_today_candidates if _bat_exists(c)]
    run_rows = "".join(
        f'<tr><td data-label="Command"><code>{_esc(c)}</code></td>'
        f'<td data-label="Notes">{_esc(n)}</td></tr>\n'
        for c, n in run_today
    )

    # AB table
    ab_body = []
    for ab in suites:
        stamp_txt = ", ".join(ab.stamps[:6]) if ab.stamps else "—"
        if ab.stamps and len(ab.stamps) > 6:
            stamp_txt += f" (+{len(ab.stamps) - 6})"
        cmp_cell = "—"
        if ab.comparison:
            cmp_cell = f'<a href="{h(ab.comparison)}">comparison.html</a>'
        elif ab.readme:
            cmp_cell = f'<a href="{h(ab.readme)}">README</a>'
        ab_body.append(
            "<tr>"
            f'<td data-label="System"><code>{_esc(ab.system_id)}</code></td>'
            f'<td data-label="Suite"><a href="{h(ab.rel_dir + "/")}">{_esc(ab.name)}</a></td>'
            f'<td data-label="Arms">{ab.arms}</td>'
            f'<td data-label="Control stamp">{_esc(ab.control_stamp or "—")}</td>'
            f'<td data-label="Control PnL">{_esc(ab.control_pnl or "—")}</td>'
            f'<td data-label="Best arm">{_esc(ab.best_arm or "—")}</td>'
            f'<td data-label="Stamps">{_esc(stamp_txt)}</td>'
            f'<td data-label="Compare">{cmp_cell}</td>'
            f'<td data-label="Notes">{_esc(ab.verdict or "—")}</td>'
            "</tr>"
        )
    if not ab_body:
        ab_body.append(
            '<tr><td colspan="9">No ab_* folders discovered under tbn_new_systems.</td></tr>'
        )

    status_href = h("STATUS.html")
    checklist_href = h("NEW_SYSTEM_CHECKLIST.html")
    final_href = h("99_FINAL_RECOMMENDATION.html")
    compare_href = h("SYSTEMS_COMPARE.html")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta http-equiv="refresh" content="120" />
<title>TBN New Systems — Away Status</title>
<style>
  :root {{
    --bg: #f4f2ec;
    --ink: #1a1a18;
    --muted: #5c584f;
    --line: #d2cdc2;
    --card: #fffcf7;
    --accent: #1f4d3a;
    --accent2: #2c3e50;
    --done: #1f6b3a; --done-bg: #e3f2e8;
    --prog: #8a5a00; --prog-bg: #f7efd9;
    --research: #1d4e89; --research-bg: #e7f0f8;
    --hold: #5a3d6e; --hold-bg: #f0e8f5;
    --stub: #5a574f; --stub-bg: #ebe8e0;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: "Segoe UI", "Helvetica Neue", Georgia, serif;
    font-size: 15px;
    line-height: 1.5;
    color: var(--ink);
    background:
      linear-gradient(180deg, #e8efe9 0%, transparent 42%),
      linear-gradient(120deg, #f0ebe3 0%, transparent 50%),
      var(--bg);
  }}
  .wrap {{ max-width: 920px; margin: 0 auto; padding: 22px 16px 56px; }}
  header {{
    border-bottom: 2px solid var(--ink);
    padding-bottom: 12px;
    margin-bottom: 18px;
  }}
  .eyebrow {{
    margin: 0 0 4px;
    font-size: 0.7rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--accent);
    font-weight: 700;
  }}
  h1 {{
    margin: 0 0 6px;
    font-size: 1.55rem;
    letter-spacing: -0.02em;
    line-height: 1.15;
  }}
  h2 {{
    font-size: 1.08rem;
    margin: 26px 0 10px;
    padding-bottom: 4px;
    border-bottom: 1px solid var(--line);
  }}
  .lede {{ margin: 0; color: var(--muted); max-width: 62ch; }}
  .meta {{ margin: 8px 0 0; font-size: 0.82rem; color: var(--muted); }}
  .banner {{
    background: var(--card);
    border: 1px solid var(--line);
    border-left: 4px solid var(--accent);
    padding: 12px 14px;
    margin: 0 0 16px;
  }}
  .banner strong {{ color: var(--accent); }}
  .navlinks {{
    display: flex; flex-wrap: wrap; gap: 8px 14px;
    margin: 10px 0 0; font-size: 0.9rem;
  }}
  a {{ color: var(--accent2); }}
  .badge {{
    display: inline-block;
    font-size: 0.72rem;
    font-weight: 750;
    letter-spacing: 0.04em;
    padding: 2px 8px;
    border-radius: 2px;
    white-space: nowrap;
  }}
  .badge-done {{ background: var(--done-bg); color: var(--done); }}
  .badge-prog {{ background: var(--prog-bg); color: var(--prog); }}
  .badge-research {{ background: var(--research-bg); color: var(--research); }}
  .badge-hold {{ background: var(--hold-bg); color: var(--hold); }}
  .badge-stub {{ background: var(--stub-bg); color: var(--stub); }}
  .sys {{
    background: var(--card);
    border: 1px solid var(--line);
    padding: 12px 14px;
    margin: 0 0 12px;
  }}
  .sys-head {{
    display: flex; flex-wrap: wrap; align-items: center;
    gap: 8px 12px; margin-bottom: 6px;
  }}
  .sys-head h2 {{
    margin: 0; border: 0; padding: 0; font-size: 1.05rem;
  }}
  .sum {{ margin: 0 0 8px; }}
  .links {{ margin: 0; font-size: 0.9rem; }}
  .cmds {{ margin: 8px 0 0; padding-left: 1.1rem; }}
  .cmds li {{ margin: 0 0 3px; }}
  .muted {{ color: var(--muted); }}
  code {{
    font-family: Consolas, "Cascadia Mono", monospace;
    font-size: 0.84em;
    background: #efece4;
    padding: 0.05em 0.28em;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    background: var(--card);
    border: 1px solid var(--line);
    font-size: 0.88rem;
    margin: 0 0 12px;
  }}
  th, td {{
    text-align: left;
    padding: 7px 8px;
    border-bottom: 1px solid var(--line);
    vertical-align: top;
  }}
  th {{
    background: #efece4;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--muted);
  }}
  tr:last-child td {{ border-bottom: none; }}
  table.sortable th.sortable-th {{
    cursor: pointer; user-select: none; white-space: nowrap;
  }}
  th.sortable-th:hover {{ color: var(--ink); }}
  th.sortable-th .sort-ind {{ margin-left: 0.3em; opacity: 0.45; }}
  th.sortable-th.sort-asc .sort-ind::after {{ content: "▲"; opacity: 1; }}
  th.sortable-th.sort-desc .sort-ind::after {{ content: "▼"; opacity: 1; }}
  .hint {{ font-size: 0.85rem; color: var(--muted); margin: -4px 0 10px; }}
  ul.plain {{ margin: 0 0 12px; padding-left: 1.15rem; }}
  ul.plain li {{ margin: 0 0 6px; }}
  footer {{
    margin-top: 28px;
    font-size: 0.78rem;
    color: var(--muted);
    border-top: 1px solid var(--line);
    padding-top: 10px;
  }}
  @media (max-width: 640px) {{
    h1 {{ font-size: 1.28rem; }}
    table.stack, table.stack thead, table.stack tbody,
    table.stack th, table.stack td, table.stack tr {{ display: block; }}
    table.stack thead {{ display: none; }}
    table.stack tr {{
      border-bottom: 1px solid var(--line);
      padding: 8px 0;
    }}
    table.stack td {{
      border: none;
      padding: 2px 8px;
    }}
    table.stack td::before {{
      content: attr(data-label);
      display: block;
      font-size: 0.7rem;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <p class="eyebrow">Twin Beacon Networks (TBN) · remote Drive status</p>
    <h1>TBN New Systems — Away Status</h1>
    <p class="lede">Phone-friendly snapshot of new-system work. Auto-refreshes every 120s if Drive syncs a newer file. Full pipeline detail lives in the living STATUS hub.</p>
    <p class="meta"><strong>Last updated:</strong> {_esc(now_local)}</p>
    <p class="navlinks">
      <a href="{status_href}"><strong>Full STATUS.html</strong></a>
      <a href="{final_href}">Final recommendation</a>
      <a href="{compare_href}">Systems compare</a>
      <a href="{checklist_href}">New-system checklist</a>
    </p>
  </header>

  <div class="banner">
    <strong>Remote viewing:</strong> open this file from Google Drive sync
    (<code>drive/…</code>). {_esc(twin_note)}
  </div>

  <h2>Snapshot</h2>
  <p class="hint">Click column headers to sort.</p>
  <table class="sortable stack">
    <thead><tr>
      {_sortable_th("System", "text")}
      {_sortable_th("Status", "text")}
      {_sortable_th("Folder", "text")}
    </tr></thead>
    <tbody>
{snap_cells}    </tbody>
  </table>

  <h2>Systems</h2>
{"".join(cards)}

  <h2>What you can run today</h2>
  <p class="hint">From repo root. Click headers to sort.</p>
  <table class="sortable stack">
    <thead><tr>
      {_sortable_th("Command", "text")}
      {_sortable_th("Notes", "text")}
    </tr></thead>
    <tbody>
{run_rows}    </tbody>
  </table>

  <h2>Open limitations</h2>
  <ul class="plain">
    <li><strong>Earnings / fundamentals:</strong> host is OHLCV-first. Full O'Neil CAN SLIM (C/A earnings growth, etc.) and true catalyst Episodic Pivot (EP) need earnings/news feeds we do not have wired.</li>
    <li><strong>Minervini VCP (MVCP):</strong> DailyRun-wired on Theory knobs + ALL universe (reconcile <code>260801215052</code>); expand dilution / fill-chase notes remain open; fundamentals deferred.</li>
    <li><strong>StockBee promote:</strong> usable + DailyRun-wired on gold 56, but formal TBN “production promote” still framed as HOLD pending PO accept of risk freeze / filters.</li>
    <li><strong>Qull HTF / Kell PAC / CAN SLIM:</strong> research / early engines only — DailyRun HOLD; not full host-parity Audit for Kell/CS yet.</li>
    <li><strong>SB gate A/Bs:</strong> ATR+52w, MM+2Lynch, vol×50d — none beat control on Total PnL (see comparisons).</li>
    <li><strong>Human ToS:</strong> optional chart override still open for seed ToS folders under <code>drive/paul_studies/</code>.</li>
  </ul>

  <h2>Recent AB / stamps</h2>
  <p class="hint">Discovered under <code>*/ab_*</code>. Click headers to sort.</p>
  <table class="sortable">
    <thead><tr>
      {_sortable_th("System", "text")}
      {_sortable_th("Suite", "text")}
      {_sortable_th("Arms", "num")}
      {_sortable_th("Control stamp", "date")}
      {_sortable_th("Control PnL", "num")}
      {_sortable_th("Best arm", "text")}
      {_sortable_th("Stamps", "text")}
      {_sortable_th("Compare", "text")}
      {_sortable_th("Notes", "text")}
    </tr></thead>
    <tbody>
{"".join(ab_body)}
    </tbody>
  </table>

  <footer>
    Generated by <code>tools/update_tbn_away_status.py</code> ·
    refresh via <code>update_tbn_away_status.bat</code> ·
    meta refresh 120s · acronyms: Twin Beacon Networks (TBN), Volatility Contraction Pattern (VCP),
    Specific Entry Point Analysis (SEPA), High Tight Flag (HTF), Episodic Pivot (EP).
  </footer>
</div>
{_SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""


def _patch_status_hub() -> None:
    """Ensure STATUS.html links prominently to AWAY_STATUS.html."""
    status = TBN_ROOT / "STATUS.html"
    if not status.is_file():
        print(f"[warn] STATUS.html missing: {status}")
        return
    text = status.read_text(encoding="utf-8", errors="replace")
    marker = "AWAY_STATUS.html"
    away_link = (
        '<a href="AWAY_STATUS.html"><strong>Away status (remote Drive) →</strong></a>'
    )
    if marker in text and "Away status" in text:
        # Already linked; leave as-is unless nav missing the strong callout
        print("[ok] STATUS.html already references AWAY_STATUS.html")
        return

    banner = (
        '\n  <div class="card" style="border-left:4px solid #2a4a5c;margin:0 0 16px">'
        "\n    <p style=\"margin:0\">"
        '<strong>For remote Drive viewing:</strong> '
        '<a href="AWAY_STATUS.html"><strong>AWAY_STATUS.html</strong></a> '
        "(phone / another PC · auto-refresh 120s · also "
        '<code>drive/TBN_New_Systems_AWAY_STATUS.html</code>).'
        "</p>\n  </div>\n"
    )

    # Insert banner after opening header block
    if "</header>" in text and "For remote Drive viewing" not in text:
        text = text.replace("</header>", "</header>" + banner, 1)

    # Inject into navlinks if present
    nav_anchor = '<p class="navlinks">'
    if nav_anchor in text and away_link not in text:
        text = text.replace(
            nav_anchor,
            nav_anchor + "\n      " + away_link,
            1,
        )

    status.write_text(text, encoding="utf-8", newline="\n")
    print("[ok] Patched STATUS.html with AWAY_STATUS.html link")


def main() -> int:
    if not TBN_ROOT.is_dir():
        print(f"[error] Missing TBN root: {TBN_ROOT}")
        return 1

    now = datetime.now().astimezone()
    now_local = now.strftime("%Y-%m-%d %H:%M:%S %Z").strip()
    systems = _build_systems()
    suites = _discover_ab_suites()

    nested_html = _render_html(
        systems,
        suites,
        prefix="",
        twin_note="This copy lives next to STATUS.html under tbn_new_systems/.",
        now_local=now_local,
    )
    root_html = _render_html(
        systems,
        suites,
        prefix="paul_experiments/tbn_new_systems",
        twin_note="This is the Drive-root convenience copy; links point into paul_experiments/tbn_new_systems/.",
        now_local=now_local,
    )

    OUT_NESTED.parent.mkdir(parents=True, exist_ok=True)
    OUT_DRIVE_ROOT.parent.mkdir(parents=True, exist_ok=True)
    OUT_NESTED.write_text(nested_html, encoding="utf-8", newline="\n")
    OUT_DRIVE_ROOT.write_text(root_html, encoding="utf-8", newline="\n")
    print(f"[ok] Wrote {OUT_NESTED.relative_to(REPO)}")
    print(f"[ok] Wrote {OUT_DRIVE_ROOT.relative_to(REPO)}")

    _patch_status_hub()

    for s in systems:
        print(f"  - {s.title}: {s.badge}")
    print(f"  AB suites: {len(suites)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
