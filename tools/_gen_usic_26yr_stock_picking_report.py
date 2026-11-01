# -*- coding: utf-8 -*-
"""Generate USIC / stock-picking championship strategy + systemizability report."""
from __future__ import annotations

import html
from pathlib import Path

OUT = Path("drive/paul_experiments/usic_stock_picking_26yr_strategies_20260920")
OUT.mkdir(parents=True, exist_ok=True)

SORTABLE_CSS = """
th.sortable-th{cursor:pointer;user-select:none;white-space:nowrap}
th.sortable-th:hover{background:#e2e8f0}
th.sortable-th .sort-ind::after{content:" \\2195";opacity:.35;font-size:.85em}
th.sortable-th.sort-asc .sort-ind::after{content:" \\2191";opacity:.9}
th.sortable-th.sort-desc .sort-ind::after{content:" \\2193";opacity:.9}
"""

SORTABLE_JS = """
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : 0;
    if (type === "text") return s.toUpperCase();
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


def th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def esc(s) -> str:
    return html.escape(str(s) if s is not None else "")


def score_class(n: float) -> str:
    if n >= 7:
        return "hi"
    if n >= 5:
        return "mid"
    return "lo"


# Year-end USIC podiums (modern era). Sources: Business Wire year-end releases + CTE compilation.
USIC_YEARS = [
    {
        "year": 2019,
        "n": 96,
        "spy_note": "SPX strong year",
        "boards": [
            ("$1m+ Stock", "Sean Goodsell", 10.1, "1st"),
            ("$20k+ Stock", "Leif Soreide", 60.9, "1st"),
            ("$20k+ Stock", "Sean Ryan", 51.8, "2nd"),
            ("$20k+ Stock", "Alok Bhatia", 19.5, "3rd"),
            ("$20k+ Enhanced Growth", "Travis Wilkerson", 31.6, "1st"),
        ],
    },
    {
        "year": 2020,
        "n": 124,
        "spy_note": "COVID crash + recovery melt-up",
        "boards": [
            ("$1m+ Stock", "George Tkaczuk", 119.1, "1st"),
            ("$1m+ Stock", "Bill Roller", 15.2, "2nd"),
            ("$1m+ Enhanced Growth", "Vivek Subramanyam", 60.6, "1st"),
            ("$20k+ Stock", "Oliver Kell", 941.1, "1st"),
            ("$20k+ Stock", "Tomas Claro", 497.0, "2nd"),
            ("$20k+ Stock", "Ryan Pierpont", 448.4, "3rd"),
            ("$20k+ Enhanced Growth", "Kenneth He Huang", 428.7, "1st"),
        ],
    },
    {
        "year": 2021,
        "n": 338,
        "spy_note": "Late-cycle bull / meme + growth",
        "boards": [
            ("$1m+ Stock", "Mark Minervini", 334.8, "1st"),
            ("$1m+ Stock", "Vibha Jha", 100.4, "2nd"),
            ("$1m+ Stock", "Hsiu-Ping Peng", 11.4, "3rd"),
            ("$20k+ Stock", "Pavel P. Sterba", 222.3, "1st"),
            ("$20k+ Stock", "Roy Mattox", 214.4, "2nd"),
            ("$20k+ Stock", "Ryan Pierpont", 201.0, "3rd"),
            ("$20k+ Enhanced Growth", "Salvador Palma", 186.3, "1st"),
        ],
    },
    {
        "year": 2022,
        "n": 326,
        "spy_note": "S&P 500 −19.4% bear; only ~8% of reporters profitable mid-year",
        "boards": [
            ("$1m+ Stock", "Sam Bhatia", 13.5, "1st"),
            ("$1m+ Stock", "Sean Goodsell", 5.9, "2nd"),
            ("$1m+ Stock", "Moritz Reinhart", 1.0, "3rd"),
            ("$1m+ Enhanced Growth", "Maziyar Yousefizad", 44.4, "1st"),
            ("$20k+ Stock", "Afzal Lokhandwala", 447.0, "1st"),
            ("$20k+ Stock", "Gemy Zhou", 440.4, "2nd"),
            ("$20k+ Stock", "Sean Ryan", 132.0, "3rd"),
            ("$20k+ Enhanced Growth", "Hieu Tuong", 200.3, "1st"),
        ],
    },
    {
        "year": 2023,
        "n": 352,
        "spy_note": "Narrow mega-cap rally + speculative rebound",
        "boards": [
            ("$1m+ Stock", "Tanmay Khandelwal", 129.0, "1st"),
            ("$1m+ Stock", "Vibha Jha", 69.7, "2nd"),
            ("$1m+ Stock", "Luis Carlos Tarin", 61.3, "3rd"),
            ("$1m+ Enhanced Growth", "Maziyar Yousefizad", 91.7, "1st"),
            ("$20k+ Stock", "Goverdhan Gajjala", 805.1, "1st"),
            ("$20k+ Stock", "Afzal Lokhandwala", 500.2, "2nd"),
            ("$20k+ Stock", "Miguel Zambrano Sánchez", 347.7, "3rd"),
            ("$20k+ Enhanced Growth", "Anthony Maffei", 309.0, "1st"),
        ],
    },
    {
        "year": 2024,
        "n": 451,
        "spy_note": "Broad speculative themes (AI / nuclear / etc.)",
        "boards": [
            ("$1m+ Stock", "Law Wai-Sum (J Law)", 353.9, "1st"),
            ("$1m+ Stock", "Judy Lai", 273.8, "2nd"),
            ("$1m+ Stock", "Deepak Uppal", 153.2, "3rd"),
            ("$1m+ Enhanced Growth", "Brandi Archer", 90.7, "1st"),
            ("$20k+ Stock", "Judy Lai", 449.1, "1st"),
            ("$20k+ Stock", "Christian Flanders", 433.5, "2nd"),
            ("$20k+ Stock", "Leos Mikulka", 409.6, "3rd"),
            ("$20k+ Enhanced Growth", "Brandon Frenchak", 482.6, "1st"),
        ],
    },
    {
        "year": 2025,
        "n": 579,
        "spy_note": "Continuation year; record stock % prints",
        "boards": [
            ("$1m+ Stock", "Law Wai-Sum (J Law)", 252.3, "1st"),
            ("$1m+ Stock", "Christian Flanders", 167.5, "2nd"),
            ("$1m+ Stock", "Clement Ang", 140.4, "3rd"),
            ("$1m+ Enhanced Growth", "Bob Weissman", 115.4, "1st"),
            ("$20k+ Stock", "Martin Luk", 969.8, "1st"),
            ("$20k+ Stock", "Rajnus Capital", 382.0, "2nd"),
            ("$20k+ Stock", "Adrian Law", 264.0, "3rd"),
            ("$20k+ Enhanced Growth", "Tito Adhikary", 2115.1, "1st"),
        ],
    },
]

# World Cup Stock Trading (gap-era stock contest). Archive standings ~2000–2009.
WC_STOCK = [
    (2000, "Steve Garner", 24),
    (2001, "Larry Jacobs", 3),
    (2002, "Tom Jensen", 71),
    (2003, "Jeff Stearns", 245),
    (2004, "Ash Matar", 26),
    (2005, "Chuck Hughes", 30),
    (2006, "Wenchen Zhang", 73),
    (2007, "Chuck Hughes / Legacy Publishing", 229),
    (2008, "Bryan Johnson", 48),
    (2009, "Chuck Hughes", 122),
]

# Detailed strategy profiles
PROFILES = [
    {
        "name": "Mark Minervini",
        "years": "1997 Stock (+155%); 2021 $1m+ Stock (+334.8%)",
        "school": "SEPA / VCP (Specific Entry Point Analysis / Volatility Contraction Pattern)",
        "style": "Stage-2 growth leaders; Trend Template; VCP pivot breakouts; Relative Strength (RS); risk-first exits",
        "rules": [
            "Trend Template: price above rising SMA50/150/200; SMA150 > SMA200; within ~25% of 52-week high; RS strong.",
            "Volatility Contraction Pattern (VCP): 2–6 contractions, each shallower; tight final coil; volume dry-up preferred.",
            "Buy pivot breakout with volume; hard initial stop under pivot/low; sell into strength / trail on structure.",
            "Market timing via leadership + index behavior; sit in cash when setups are scarce.",
        ],
        "discretion": "High on pattern quality, timing, and which leaders to size. Books are detailed; live execution still discretionary.",
        "sys": 8.0,
        "sys_label": "HIGHEST — already partially coded",
        "likelihood": (
            "Canonical Twin Beacon Networks (TBN) research control. The retired Minervini Volatility Contraction Pattern "
            "(MVCP) sleeve already encodes Trend Template + VCP geometry. Championship-scale returns still require aggressive "
            "concentration, discretionary filtering, and favorable regime — do not expect MVCP Closed stamps to match +334%. "
            "Primary 1997 figure is +155% (ignore secondary '255%' errors)."
        ),
        "repo": "docs/systems/mvcp.html · rocket_minervini_vcp.py (retired from DailyRun 2026-08-21; research runners kept)",
        "caveat": "MPA clients appear disproportionately on modern boards — pedigree is real; education funnel is also real.",
    },
    {
        "name": "David Ryan (CAN SLIM lineage)",
        "years": "Mid-1980s USIC stock titles (commonly 1985–87; Schwager flags 1986 as 2nd place — source conflict); ~+1,379% 3-yr compound in Market Wizards",
        "school": "CAN SLIM (Current earnings, Annual earnings, New product/high, Supply/demand, Leader/laggard, Institutional, Market direction)",
        "style": "IBD / William O'Neil growth breakouts; cup-with-handle / flat base; market direction filter; short-to-intermediate holds",
        "rules": [
            "Screen for accelerating EPS / sales + relative strength leaders.",
            "Buy proper bases (cup-with-handle, flat base, etc.) on volume breakouts.",
            "Cut losses ~7–8% from entry (classic O'Neil rule of thumb).",
            "Scale exposure with market direction (follow-through days / distribution).",
        ],
        "discretion": "Medium-high. CAN SLIM is rule-rich but chart bases and 'proper' pivots remain judgment calls.",
        "sys": 7.0,
        "sys_label": "HIGH — CS / SB overlap",
        "likelihood": (
            "Foundational parent of SEPA/VCP research. TBN already has CAN SLIM price-leg (CS). Use as control lineage, "
            "not as proof from 1980s contest structure alone."
        ),
        "repo": "getTarget.py CS mode; growth/breakout research stamps",
        "caveat": "Exact year labels conflict (Schwager vs modern 'three consecutive wins' shorthand).",
    },
    {
        "name": "Sean Ryan",
        "years": "2019–2025 every modern year profitable (no division title); organiser combined ~+6,232% vs SPX ~+205%",
        "school": "Chart-only discretionary swing (abandoned fundamentals); volume + RSI; themes; son of David Ryan — not Sean Goodsell",
        "style": "Anti-first-breakout timing; prefer second leg after consolidation; low win-rate / fat winners; occasional leveraged ETFs",
        "rules": [
            "Never risk more than ~1% of portfolio per trade (hard rule in interviews).",
            "Prefer second rally after consolidation over chasing the first breakout.",
            "Volume accumulation + Relative Strength Index (RSI) strengthening on entries; exit on RSI bearish divergence while price grinds up.",
            "Reported low win rate (~27%) with large winners — process is expectancy, not accuracy.",
        ],
        "discretion": "Risk % is hard; RSI divergence and 'second rally' are semi-rules; theme picking is discretionary.",
        "sys": 6.5,
        "sys_label": "HIGH persistence research",
        "likelihood": (
            "Best modern persistence case. Clean A/B vs classic VCP pivot-buy: delay first breakout, add RSI-divergence exits. "
            "Prefer multi-year quality metrics over max single-year %."
        ),
        "repo": "Natural A/B vs MVCP/SB breakout timing",
        "caveat": "Do not confuse with Sean Goodsell ($1m+ 2019/2022).",
    },
    {
        "name": "Leif Soreide",
        "years": "2019 $20k+ Stock (+60.9%) — first modern-era stock champion",
        "school": "CAN SLIM + Minervini-lineage SEPA/VCP; High Tight Flag (HTF) specialist; progressive exposure",
        "style": "Discretionary swing; Stage-2 leaders; VCP/HTF with ATR tightening; scale-out into strength",
        "rules": [
            "Universe: Stage-2 leaders, high Relative Strength (often 90s), strong groups; IPOs with wider stops.",
            "Entry: Volatility Contraction Pattern (VCP) / High Tight Flag (HTF) with Average True Range (ATR) tightening, volume dry-up, inside days; pullback buys near pivots; avoid extended breakouts.",
            "Exit: scale out into strength (~20% clips; ~30% rip common); trail remainder; tighten in chop.",
            "Risk: tight initial stops (~4–5% cited); small starts; add-backs only after confirmation; cut exposure in hostile tape.",
        ],
        "discretion": "Framework teachable; pattern quality, group leadership, and 'think beyond the pattern' remain discretionary.",
        "sys": 6.5,
        "sys_label": "HIGH — HTF / SEPA peer",
        "likelihood": (
            "Strong swing-sleeve research peer. Useful for High Tight Flag (HTF) / early-leader / progressive-exposure studies "
            "alongside MVCP. One contested year + education business — treat as method source, not expectancy proof."
        ),
        "repo": "HTF / VCP research adjacent to MVCP; progressive exposure sizing studies",
        "caveat": "Champion Team Trading commercial layer — verify free public rules before freezing knobs.",
    },
    {
        "name": "Oliver Kell",
        "years": "2020 $20k+ Stock (+941.1%)",
        "school": "CAN SLIM-influenced + proprietary Cycle of Price Action",
        "style": "Swing trade liquid high-beta leaders around 10/20 EMA; multi-timeframe (weekly → daily → 65-min); not day trading",
        "rules": [
            "Universe: innovative growth leaders with strong earnings/sales/RS; names that hold best in corrections.",
            "Named setups: Reversal Extension, Wedge Pop, EMA Crossback, Base n' Break; big gap-ups that don't fill.",
            "Aggressive when price holds above rising 10/20 EMA; defensive when rejected under declining EMAs.",
            "Trail with 10/20 EMA; sell into extensions from daily 10 EMA; ~3–5% loss tolerance cited; no averaging down.",
        ],
        "discretion": "EMA rules are systemizable; stock selection, 'cycle' phase, and when to press remain discretionary.",
        "sys": 7.0,
        "sys_label": "HIGH — EMA Crossback sleeve",
        "likelihood": (
            "Natural A/B arm vs VCP breakout: pullback-to-EMA continuation. Start with daily-only approximation of EMA "
            "Crossback + trail; decide later if 65-min timing is worth the complexity."
        ),
        "repo": "Closest existing: SB / VCP / RS zone retests — not a 1:1 Kell clone",
        "caveat": "2020 pandemic rebound is a huge regime caveat (all-cash into COVID low then press).",
    },
    {
        "name": "Law Wai-Sum (J Law)",
        "years": "2024 $1m+ Stock (+353.9%); 2025 $1m+ Stock (+252.3%); 2-yr compound ~+1,499%",
        "school": "Minervini-influenced + Multiple-Edge Trading Strategy (M.E.T.S.) / Multiple Edge Trading Area (M.E.T.A.)",
        "style": "Technical-first momentum; stack multiple edges at one price zone; strict % risk; often ~35% win rate with large R winners",
        "rules": [
            "Risk per trade capped ~1–1.5% of equity; stops non-negotiable.",
            "Prefer 21-day EMA + 63-day EMA (quarter-cycle framing) and Relative Strength vs index.",
            "M.E.T.A.: enter only when 3–5 independent edges converge (structure, RS, MA stack, sector, etc.).",
            "Size up only when market + sector + individual leader all confirm; otherwise hold cash.",
            "Public comments include opportunistic use of leveraged ETFs (e.g. TQQQ) when conditions stacked — Stock Division allows ETFs.",
        ],
        "discretion": "Medium. Framework is explicitly 'rules-based' in marketing; edge counting and confluence remain subjective.",
        "sys": 7.0,
        "sys_label": "HIGH research priority",
        "likelihood": (
            "Best modern $1m+ template to study after Minervini: capacity-aware, risk-capped, multi-edge confluence. "
            "Systemizable as a scored confluence entry + hard risk budget. Do not chase his contest leverage path."
        ),
        "repo": "Natural research neighbor to MVCP/SEPA + RS filters",
        "caveat": "Organiser describes him as a Minervini student; commercial education expanding (JLawStock).",
    },
    {
        "name": "Judy Lai",
        "years": "2024 $20k+ Stock (+449.1%); also 2nd $1m+ Stock (+273.8%) same year",
        "school": "Same household / process orbit as J Law (public detail thinner)",
        "style": "Growth/momentum stock trading consistent with M.E.T.S. family; dual-band presence is rare",
        "rules": [
            "Public rulebook less complete than J Law's YouTube curriculum.",
            "Operationally treat as correlated to Law's technical confluence + risk discipline until primary interviews say otherwise.",
        ],
        "discretion": "Unknown independently; correlated with Law Wai-Sum results (same-year dual podium).",
        "sys": 2.0,
        "sys_label": "LOW — no independent playbook",
        "likelihood": "If J Law sleeve is built, Judy is not a separate system — treat as same process family pending disclosure.",
        "repo": "—",
        "caveat": "Spectacular dual-board year but zero public playbook under her name — do not invent knobs.",
    },
    {
        "name": "Martin Luk",
        "years": "2024 $20k+ Stock (+283.1%); 2025 $20k+ Stock (+969.8%) record (passed Kell)",
        "school": "Momentum swing / pullback reclaim (AVWAP + EMA) + breakouts / Episodic Pivots (EP)",
        "style": "High Average Daily Range (ADR) leaders in hot themes; buy flushes that reclaim support; tiny stops → huge R:R; occasional 2x ETFs",
        "rules": [
            "Scan prior-day leaders, premarket gaps, 30-day movers; track theme upgrades across EMA strength lists (9>21>50).",
            "Prefer stocks up sharply over 1–6 months, >~5% ADR when hunting big R.",
            "Enter on pullback reclaim of Anchored Volume Weighted Average Price (AVWAP), 9/21/50 EMA, gap/horizontal support; also breakouts / EP gaps.",
            "Account risk ~0.5–1.5% per trade; stop often 1–5% of price (tight; progressed from wider stops).",
            "Trail / exit on closes below 9 or 21 EMA depending on extension; full exit on broad weakness days.",
        ],
        "discretion": "Medium on theme detection and which flush is 'the' entry. Structure is unusually concrete for a champion.",
        "sys": 7.0,
        "sys_label": "HIGH — clear knobs",
        "likelihood": (
            "Excellent one-knob AB material (ADR floor, AVWAP reclaim, EMA trail, tight LOD stops vs classic 7–8% SEPA stops). "
            "Championship path volatility (gave back hundreds of points in Dec 2025) warns against maximizing calendar-year %."
        ),
        "repo": "Adjacent to intraday HTF retest / zone research tools; not yet a named DailyRun sleeve",
        "caveat": "Tight stops on high-ADR names imply high turnover and whipsaw risk in non-theme regimes; capacity caution.",
    },
    {
        "name": "Goverdhan Gajjala",
        "years": "2023 $20k+ Stock (+805.1%)",
        "school": "Minervini Private Access psychology + proprietary low-float day-trade playbook",
        "style": "Long-only intraday momentum in volatile small-caps; 5-minute charts; ~5 named setups",
        "rules": [
            "Scanners: up ≥25% day, volume >1M, low float / volatile names.",
            "Five named setups: Bull Flag Breakout; EMA Kiss-and-Fly; Horizontal Fade; Intraday VCP; Reversal Squeeze.",
            "Wait for selling volume to dry; support at 9/21 EMA; partials after initial push; trail with short EMA.",
            "Account risk ~0.25% per trade reported; survived documented −44% month / 17 losers mid-2023 before finishing #1.",
        ],
        "discretion": "Setups named and relatively concrete; tape reading still discretionary.",
        "sys": 3.0,
        "sys_label": "LOW for EOD DailyRun (codeable intraday, bad capacity)",
        "likelihood": (
            "Poor fit for Twin Beacon Networks (TBN) end-of-day DailyRun. Intraday rules are codeable but low-float "
            "slippage destroys edges in honest backtests. Different game from SEPA swing."
        ),
        "repo": "No analogue; do not force into MVCP/SB",
        "caveat": "MPA client + day-trade reality — SEPA branding ≠ SEPA daily system. Business Insider reviewed statements.",
    },
    {
        "name": "Afzal Lokhandwala",
        "years": "2022 $20k+ Stock (+447%); 2023 $20k+ Stock 2nd (+500.2%)",
        "school": "Price/volume swing system (Champions Club curriculum)",
        "style": "Swing 10–30% over ~1–4 weeks; equities only (rejects options & intraday for core system); last-30-minutes execution",
        "rules": [
            "Explosive stocks under institutional accumulation (price/volume).",
            "Late-session scan; buy before/into breakouts when risk:reward favorable.",
            "Emphasizes predefined exits; example framing: risk 5% for 15% needs >25% win rate to profit.",
            "Defined stops; trade less; busy-professional routine (<60 min/day claimed).",
        ],
        "discretion": "Paid course claims clear buy/sell criteria; public free detail medium.",
        "sys": 6.0,
        "sys_label": "MEDIUM-HIGH — last-hour breakout A/B",
        "likelihood": (
            "Same family as momentum breakout swings; less earnings-template emphasis than SEPA. Good 'last-hour breakout' "
            "timing A/B idea. Persistence across 2022–23 (incl. tough tape) raises confidence vs one-hit wonders."
        ),
        "repo": "SB / momentum breakout research",
        "caveat": "Commercial course opacity — verify any claimed rules before coding.",
    },
    {
        "name": "Tanmay Khandelwal (TwoXCapital)",
        "years": "2023 $1m+ Stock (+129%)",
        "school": "B.E.S.T. (Big potential, Earnings, Strength, Trustworthy management)",
        "style": "Fundamentally driven multi-month growth investing; diversified book; cut losses fast (~avg loss ~−4.5% trade)",
        "rules": [
            "Screen big TAM / earnings / strength / management quality.",
            "Hold often many months; book partials; keep per-trade capital impact small on losers (~≤1%).",
            "Documented 2023 book: ~58 closed trades, mix of India-focused names in examples (competition allows foreign stocks).",
        ],
        "discretion": "Very high on fundamental judgment.",
        "sys": 3.5,
        "sys_label": "LOW-MEDIUM (screens only)",
        "likelihood": (
            "You can systematize screens (earnings acceleration, RS, market cap). You cannot honestly systematize "
            "'trustworthy management' without NLP/human review. Better as a research filter layer than a full system."
        ),
        "repo": "Fundamental overlays outside core TBN price engines",
        "caveat": "Different animal from VCP day/swing champions — longer holds, fundamental discretion.",
    },
    {
        "name": "Christian Flanders",
        "years": "2024 $20k+ Stock 2nd (+433.5%); 2025 $1m+ Stock 2nd (+167.5%) — rare band step-up",
        "school": "Discretionary momentum: VCP, High Tight Flags (HTF), Episodic Pivots (EP); poker-discipline risk",
        "style": "Leaders in leading sectors; progressive exposure; handful of A+ trades; size up when factors align",
        "rules": [
            "Relative Strength typically very high (self-reported often ≥98); powerful moves off 52-week lows.",
            "Favorite: Episodic Pivots (gap on major catalyst); also VCP/HTF with volume expansion.",
            "~5% max monthly drawdown threshold cited in secondary writeups; cut exposure hard when not working.",
            "Notable for surviving the step from small-band fireworks to $1m+ verification.",
        ],
        "discretion": "Setup taxonomy clear; A+ selection and max size timing are discretionary (poker background).",
        "sys": 6.5,
        "sys_label": "HIGH — EP + VCP + HTF freeze candidate",
        "likelihood": (
            "Nearly a Twin Beacon Networks (TBN) playbook twin: Episodic Pivot (EP) + VCP + HTF + progressive exposure. "
            "Build as a named A/B freeze, not a personality system. Concentration / small-N yearly winners = huge variance."
        ),
        "repo": "MVCP / SEPA / EP research",
        "caveat": "Some strategy detail from secondary articles — cross-check primary interviews before coding knobs.",
    },
    {
        "name": "Vibha Jha",
        "years": "2020 +155.2% (top female); 2021 $1m+ 2nd (+100.4%); 2023 $1m+ 2nd (+69.7%); 2024 $1m+ (+78.2%)",
        "school": "Hybrid: CAN SLIM positional growth + rules-based TQQQ (3× Nasdaq) swing overlay",
        "style": "6–8 core stock positions from IBD lists; when stock setups dry up, swing ProShares UltraPro QQQ (TQQQ) near moving averages",
        "rules": [
            "Stock universe: IBD 50 / Sector Leaders / IPO Leaders; earnings/sales growth screens.",
            "Stock entry: cup-with-handle / double bottom / Stage 1→2; buy retaking 50-day or 10-week.",
            "Stock exit: violate 10-week / 50-day moving average.",
            "TQQQ: buy near 50/21-day after ~10–15% pullback on higher lows; sell into strength (new highs + declining volume, Nasdaq distribution days, resistance rejects).",
        ],
        "discretion": "Stock side semi-discretionary CAN SLIM; TQQQ side closer to rules-based swing.",
        "sys": 7.0,
        "sys_label": "HIGH — stock + index overlay",
        "likelihood": (
            "Multi-year $1m+ persistence is gold. TQQQ overlay is highly systemizable and capacity-friendlier than microcaps. "
            "Build as two sleeves: SEPA-like stock book + 'index momentum when breadth dies' research arm. 3× leverage is a risk flag."
        ),
        "repo": "CS / SEPA stock sleeve + separate leveraged-ETF research (not DailyRun by default)",
        "caveat": "Leveraged ETF path risk and decay — freeze risk budget before any live wire.",
    },
    {
        "name": "George Tkaczuk",
        "years": "2020 $1m+ Stock (+119.1%); strong $1m+ prints again 2024 (+97.7%); multi-year persistence",
        "school": "IBD / CAN SLIM trend-following growth; weeks-to-months hold",
        "style": "High Relative Strength leaders; cash or inverse ETFs when weak; consistency over heroics",
        "rules": [
            "Universe: high Relative Strength leaders with demand/volume (IBD system).",
            "Buy as markets strengthen; technical setups from Investor's Business Daily (IBD) playbook.",
            "Hold until stock 'acts wrong'; scale to cash or buy inverse ETFs in weakness.",
            "Emphasizes cutting losses; capacity-honest $1m+ book.",
        ],
        "discretion": "IBD checklist is semi-rules-based; 'acts wrong' and market timing are discretionary.",
        "sys": 6.0,
        "sys_label": "MEDIUM-HIGH — capacity benchmark",
        "likelihood": (
            "Classic IBD/CAN SLIM institutional sleeve. Valuable because $1m+ size constrains microcap day-trade edges. "
            "Good capacity benchmark for Paul Twenty-style growth books."
        ),
        "repo": "CS / CAN SLIM research",
        "caveat": "Exit subjectivity remains; do not overfit 'acts wrong' labels.",
    },
    {
        "name": "Sam Bhatia / Sean Goodsell / Pavel Sterba (sparse disclosure)",
        "years": "Goodsell 2019 $1m+ (+10.1%) & 2022 2nd (+5.9%); Bhatia 2022 $1m+ (+13.5%); Sterba 2021 $20k+ (+222.3%)",
        "school": "Undisclosed / lightly disclosed (do not invent methods)",
        "style": "Bhatia/Goodsell = capital preservation at size in tough years; Sterba = one strong growth year with bio only",
        "rules": [
            "Public strategy detail insufficient for a frozen system.",
            "2022 $1m+ lesson: survive and stay positive when SPX −19.4% — process value ≫ headline %.",
            "Sterba: started ~$98k per Business Wire; no published entry/exit checklist found.",
        ],
        "discretion": "Unknown",
        "sys": 2.0,
        "sys_label": "LOW disclosure / HIGH lesson (bear-year survival)",
        "likelihood": (
            "System lesson: regime filters and risk-off modes as evaluation metrics. Do not clone +13.5% as an entry model. "
            "Do not invent a Sterba system from return alone."
        ),
        "repo": "Risk-off / market filter work across sleeves",
        "caveat": "Sean Goodsell ≠ Sean Ryan. Sterba is a leaderboard datapoint only.",
    },
    {
        "name": "Bryan Johnson (World Cup Stock — regime timer)",
        "years": "WC Stock 2008 (+48%); 2009 2nd (+95%)",
        "school": "Market-timing / crash-defense ('Tsunami Indicator') + short-to-intermediate market timer",
        "style": "Risk-on / risk-off for the stock book; cash/hedge when timer fires — selection system secondary",
        "rules": [
            "Candidate buy/sell from Short-to-Intermediate Market Timer (AAII / MetaStock materials).",
            "Tsunami major sell example stack (2008-09-04 'sell everything'): Rate of Decline >190; Normalized Nasdaq New Lows >40; "
            "Market Sentiment Index (MSI) thresholds; VIX 19–25 band (reconstruct exact formulas from his packets before coding).",
            "Book: Before the Bear Strikes.",
        ],
        "discretion": "Indicator stack is explicitly rules-based (rare among champions).",
        "sys": 8.0,
        "sys_label": "HIGHEST as market overlay (not stock picker)",
        "likelihood": (
            "Clearest published rule stack for a stock-cup winner — but as a REGIME OVERLAY (when to flat SEPA books), "
            "not a stock-selection system. Reconstruct formulas carefully; crash-year sample is tiny; threshold survivorship risk."
        ),
        "repo": "Market filter / risk-off research across sleeves",
        "caveat": "Do not promote as a stock-picking edge; promote as 'when not to trade' research.",
    },
    {
        "name": "Chuck Hughes (World Cup Stock era)",
        "years": "WC Stock: 2005 +30%, 2007 +229%, 2009 +122% (multi-time stock champ); also futures titles",
        "school": "Intermediate trend + Optioneering / PowerTrend (options leverage on trend stocks)",
        "style": "Index trend filter → leading sectors → 52-week-high leaders → fundamentals → EMA/Keltner/OBV → options structure",
        "rules": [
            "Example Intermediate Stock Trend checklist: SPX vs 20-month EMA; sector leaders; monthly price > 20-mo EMA; EMA50>EMA100; Keltner dip; rising On-Balance Volume (OBV).",
            "Options: often deep/slight ITM, limited extrinsic; debit spreads; strict money management (commercial variants differ).",
        ],
        "discretion": "Medium on stock filter; high on option strike/expiry selection.",
        "sys": 4.0,
        "sys_label": "MEDIUM stock filter / LOW options fidelity",
        "likelihood": (
            "Stock trend filter is systemizable; options overlay maps to Enhanced Growth, not Stock Division / not TBN equity sleeves. "
            "Prior legitimacy work flagged commercial funnel risk — research the filter, skip the funnel."
        ),
        "repo": "Prior stamp: world_cup_usic_traders_legit_20260831",
        "caveat": "Contest wins ≠ student results; sales/refund complaints appear in prior compare work.",
    },
    {
        "name": "Tito Adhikary / Maziyar Yousefizad (Enhanced Growth)",
        "years": "Adhikary 2025 $20k+ EG (+2,115.1%); Maziyar 2022–23 $1m+ EG (+44.4%, +91.7%)",
        "school": "Futures / long options allowed (Enhanced Growth)",
        "style": "Not a stock-picking system in the USIC Stock Division sense",
        "rules": [
            "Instrument set dominates the percentage. Do not compare to Stock Division winners.",
            "Maziyar: ex-bank risk analyst / fund bio; method not publicly detailed for equity replication.",
        ],
        "discretion": "N/A for equity system design",
        "sys": 1.5,
        "sys_label": "OUT OF SCOPE for stock systems",
        "likelihood": "Ignore for equity DailyRun. Label Enhanced Growth clearly whenever citing these names.",
        "repo": "—",
        "caveat": "Cross-division 'biggest return ever' tables are misleading by construction.",
    },
]

# Summary scoreboard rows for top of report
SUMMARY_ROWS = sorted(
    [
        {
            "name": p["name"],
            "window": p["years"].split(";")[0][:80],
            "school": p["school"][:70],
            "sys": p["sys"],
            "label": p["sys_label"],
            "fit": "Stock EOD" if p["sys"] >= 6 else ("Research only" if p["sys"] >= 3.5 else "Skip / out of scope"),
        }
        for p in PROFILES
    ],
    key=lambda r: -r["sys"],
)


def year_table() -> str:
    rows = []
    for y in USIC_YEARS:
        for board, name, ret, place in y["boards"]:
            rows.append(
                "<tr>"
                f"<td>{y['year']}</td>"
                f"<td>{y['n']}</td>"
                f"<td>{esc(board)}</td>"
                f"<td>{esc(place)}</td>"
                f"<td>{esc(name)}</td>"
                f"<td class='num'>{ret:+.1f}%</td>"
                f"<td>{esc(y['spy_note'])}</td>"
                "</tr>"
            )
    head = "".join(
        th(lbl, typ)
        for lbl, typ in (
            ("Year", "num"),
            ("Entrants", "num"),
            ("Board", "text"),
            ("Place", "text"),
            ("Trader", "text"),
            ("Return", "num"),
            ("Regime note", "text"),
        )
    )
    return (
        '<table class="sortable"><caption>Modern USIC year-end podiums (2019–2025). '
        "Click column headers to sort. Stock Division vs Enhanced Growth are not comparable.</caption>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def wc_table() -> str:
    rows = []
    for year, name, ret in WC_STOCK:
        rows.append(
            f"<tr><td>{year}</td><td>{esc(name)}</td><td class='num'>{ret:+.0f}%</td>"
            "<td>World Cup Championship of Stock Trading (Robbins archive)</td></tr>"
        )
    head = "".join(
        th(lbl, typ)
        for lbl, typ in (("Year", "num"), ("Champion", "text"), ("Return", "num"), ("Source note", "text"))
    )
    return (
        '<table class="sortable"><caption>Gap-era stock contest (approx. 2000–2009). '
        "Click headers to sort. Strategy disclosure is thin for most names.</caption>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def summary_table() -> str:
    rows = []
    for r in SUMMARY_ROWS:
        sc = score_class(r["sys"])
        rows.append(
            "<tr>"
            f"<td>{esc(r['name'])}</td>"
            f"<td>{esc(r['window'])}</td>"
            f"<td>{esc(r['school'])}</td>"
            f"<td class='num {sc}'>{r['sys']:.1f}</td>"
            f"<td>{esc(r['label'])}</td>"
            f"<td>{esc(r['fit'])}</td>"
            "</tr>"
        )
    head = "".join(
        th(lbl, typ)
        for lbl, typ in (
            ("Name / cluster", "text"),
            ("Headline result", "text"),
            ("School", "text"),
            ("Systemizability /10", "num"),
            ("Read", "text"),
            ("TBN fit", "text"),
        )
    )
    return (
        '<table class="sortable"><caption>Opinionated systemizability for building a Twin Beacon Networks (TBN) '
        "research/production sleeve. Click headers to sort.</caption>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def profile_cards() -> str:
    parts = []
    for i, p in enumerate(PROFILES, 1):
        sc = score_class(p["sys"])
        rules = "".join(f"<li>{esc(x)}</li>" for x in p["rules"])
        parts.append(
            f"""
<section class="profile" id="p{i}">
  <h3>{i}. {esc(p['name'])} <span class="badge {sc}">{p['sys']:.1f}/10</span></h3>
  <p class="meta"><strong>Results:</strong> {esc(p['years'])}</p>
  <p class="meta"><strong>School:</strong> {esc(p['school'])}</p>
  <p><strong>Style.</strong> {esc(p['style'])}</p>
  <p><strong>Public rules / process (as documented).</strong></p>
  <ul>{rules}</ul>
  <p><strong>Discretion vs rules.</strong> {esc(p['discretion'])}</p>
  <p><strong>Likelihood we can make it a system.</strong> {esc(p['likelihood'])}</p>
  <p class="meta"><strong>Repo touchpoint:</strong> {esc(p['repo'])}</p>
  <p class="caveat"><strong>Caveat:</strong> {esc(p['caveat'])}</p>
</section>
"""
        )
    return "\n".join(parts)


html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>26-Year Stock-Picking Championship Map — Strategies &amp; Systemizability</title>
  <style>
    :root {{
      --bg: #f1f5f9; --card: #fff; --text: #0f172a; --muted: #64748b;
      --border: #e2e8f0; --accent: #0f766e; --hi: #15803d; --mid: #b45309; --lo: #b91c1c;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
      background: var(--bg); color: var(--text); line-height: 1.55;
      margin: 0; padding: 1.25rem; max-width: 1100px; margin-inline: auto;
    }}
    header {{
      background: linear-gradient(135deg, #042f2e 0%, #0f766e 55%, #115e59 100%);
      color: #fff; padding: 1.75rem 2rem; border-radius: 12px; margin-bottom: 1.25rem;
    }}
    header h1 {{ margin: 0 0 .4rem; font-size: 1.55rem; }}
    header p {{ margin: 0; opacity: .9; font-size: .95rem; }}
    .callout {{
      background: #ecfdf5; border: 1px solid #a7f3d0; border-left: 5px solid var(--accent);
      border-radius: 0 10px 10px 0; padding: 1rem 1.25rem; margin-bottom: 1rem;
    }}
    .callout h2 {{ margin: 0 0 .5rem; font-size: 1.05rem; }}
    .callout p {{ margin: .35rem 0; font-size: .95rem; }}
    section.card, section.profile {{
      background: var(--card); border: 1px solid var(--border);
      border-radius: 10px; padding: 1.15rem 1.35rem; margin-bottom: 1rem;
    }}
    h2 {{ margin: 0 0 .75rem; font-size: 1.15rem; }}
    h3 {{ margin: 0 0 .5rem; font-size: 1.05rem; }}
    ul {{ margin: .35rem 0 .75rem; padding-left: 1.2rem; }}
    li {{ margin: .25rem 0; }}
    table {{ width: 100%; border-collapse: collapse; font-size: .82rem; margin-top: .4rem; }}
    th, td {{ border: 1px solid var(--border); padding: .4rem .5rem; text-align: left; vertical-align: top; }}
    th {{ background: #f1f5f9; font-weight: 600; }}
    caption {{ caption-side: top; text-align: left; font-size: .8rem; color: var(--muted); margin-bottom: .35rem; }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; }}
    .hi {{ color: var(--hi); }} .mid {{ color: var(--mid); }} .lo {{ color: var(--lo); }}
    {SORTABLE_CSS}
    .badge {{
      display: inline-block; font-size: .78rem; font-weight: 700;
      padding: .15rem .45rem; border-radius: 6px; margin-left: .35rem;
      background: #f1f5f9; color: var(--text);
    }}
    .badge.hi {{ background: #dcfce7; color: var(--hi); }}
    .badge.mid {{ background: #ffedd5; color: var(--mid); }}
    .badge.lo {{ background: #fee2e2; color: var(--lo); }}
    .meta {{ color: var(--muted); font-size: .9rem; }}
    .caveat {{ font-size: .88rem; color: #7c2d12; background: #fff7ed; padding: .6rem .75rem; border-radius: 6px; }}
    .toc a {{ color: var(--accent); }}
    .footnote {{ font-size: .8rem; color: var(--muted); margin-top: 1.5rem; border-top: 1px solid var(--border); padding-top: .75rem; }}
    nav.toc ul {{ columns: 2; gap: 1.5rem; }}
    @media (max-width: 720px) {{ nav.toc ul {{ columns: 1; }} }}
  </style>
</head>
<body>
  <header>
    <h1>26-Year Stock-Picking Championship Map</h1>
    <p>U.S. Investing Championship (USIC) + World Cup Stock gap years · Strategies · Systemizability for TBN · Generated 2026-09-20 · Not financial advice</p>
  </header>

  <div class="callout">
    <h2>What you asked</h2>
    <p>“Generate a detailed report for me of the last 26 years of world championship of stock picking and detail each of their strategies, and the likelihood we can make it into a system and give me a detailed report on each.”</p>
    <h2>In plain English</h2>
    <p>You want a year-by-year map of who won the big verified stock-picking contests, <em>how</em> they say they trade, and an honest grade on whether we can turn that playbook into a Twin Beacon Networks (TBN) rules-based sleeve (like the retired Minervini Volatility Contraction Pattern / MVCP work) — not a cheerleading list of huge percentages.</p>
    <p><strong>Key fact:</strong> The main stock-picking championship is the U.S. Investing Championship (USIC). It ran ~1983–1997, then went dark for ~20 years, then restarted in 2019. So “last 26 years” (≈2000–2025) is mostly a gap for USIC; we fill 2000–2009 with the Robbins World Cup Championship of Stock Trading where documented, then detail modern USIC 2019–2025 winners thoroughly.</p>
  </div>

  <section class="card">
    <h2>Paul note / bottom line</h2>
    <ul>
      <li><strong>One lineage dominates modern stock boards:</strong> O’Neil / Minervini Specific Entry Point Analysis (SEPA) / Volatility Contraction Pattern (VCP) / Relative Strength (RS) growth continuation — Soreide, Kell, Gajjala (MPA), Law/Lai, Flanders, Weissman, etc.</li>
      <li><strong>Best system candidates (score ≥7):</strong> Minervini SEPA/VCP (already coded as MVCP research), Bryan Johnson market-timer overlay, Oliver Kell EMA Crossback, Law M.E.T.S., Martin Luk ADR/AVWAP, Vibha Jha stock+TQQQ hybrid, CAN SLIM / David Ryan lineage.</li>
      <li><strong>Prefer multi-year names</strong> (Sean Ryan, Vibha Jha, Lokhandwala, Law, Flanders, Tkaczuk) over single fireworks years when picking research candidates.</li>
      <li><strong>Do not chase contest %:</strong> small-band + concentration + voluntary reporting + right-tail selection. 2022 ten-month print: only ~8% of reporters profitable.</li>
      <li><strong>Skip for DailyRun:</strong> low-float day-trade (Gajjala), Enhanced Growth options/futures blow-offs, opaque names without a rulebook (Sterba/Goodsell/Bhatia/Judy Lai).</li>
      <li><strong>Already learned the hard way:</strong> MVCP is retired from DailyRun (2026-08-21) — championship pedigree ≠ production expectancy.</li>
    </ul>
  </section>

  <section class="card">
    <h2>How to read the contest (acronyms)</h2>
    <ul>
      <li><strong>USIC</strong> — U.S. Investing Championship: calendar-year, real-money, statement-verified time-weighted return.</li>
      <li><strong>Stock Division</strong> — stocks/ETFs, leverage, option <em>writing</em>; no futures, no long options.</li>
      <li><strong>Enhanced Growth</strong> — futures and long options allowed (different game).</li>
      <li><strong>Bands</strong> — $20k+ vs $1m+; percentages are not comparable across bands.</li>
      <li><strong>SEPA</strong> — Specific Entry Point Analysis (Minervini). <strong>VCP</strong> — Volatility Contraction Pattern. <strong>CAN SLIM</strong> — William O’Neil growth checklist. <strong>RS</strong> — Relative Strength. <strong>ADR</strong> — Average Daily Range. <strong>AVWAP</strong> — Anchored Volume Weighted Average Price. <strong>EMA/SMA</strong> — Exponential/Simple Moving Average.</li>
    </ul>
  </section>

  <section class="card">
    <h2>Systemizability scoreboard</h2>
    {summary_table()}
  </section>

  <section class="card">
    <h2>Modern USIC results (2019–2025)</h2>
    {year_table()}
  </section>

  <section class="card">
    <h2>Gap years — World Cup Stock Trading (~2000–2009)</h2>
    <p class="meta">USIC was not running. Closest continuous “stock championship” record in this window is Robbins’ World Cup Championship of Stock Trading (archive standings). Most winners left little public system detail; Chuck Hughes is the documented multi-winner.</p>
    {wc_table()}
    <p class="meta">2010–2018: no clean public USIC stock championship series. Treat as a documentary hole, not “no traders existed.”</p>
  </section>

  <section class="card toc">
    <h2>Detailed reports (jump)</h2>
    <nav class="toc"><ul>
      {''.join(f'<li><a href="#p{i}">{esc(p["name"])}</a> — {p["sys"]:.1f}/10</li>' for i, p in enumerate(PROFILES, 1))}
    </ul></nav>
  </section>

  {profile_cards()}

  <section class="card">
    <h2>Recommended build order (if we turn this into systems work)</h2>
    <ol>
      <li><strong>Kell-style EMA Crossback / trail</strong> as one-knob A/B vs classic VCP pivot breakout (daily first).</li>
      <li><strong>Martin Luk pullback reclaim</strong> (ADR floor, AVWAP/EMA stack, tight stop) vs wider SEPA 7–8% stops.</li>
      <li><strong>Flanders/Soreide EP + HTF + VCP freeze</strong> (Episodic Pivot / High Tight Flag) — one setup taxonomy, IS/OOS, no OOS retune.</li>
      <li><strong>Sean Ryan timing A/B</strong> (anti-first-breakout + RSI divergence exits) vs control breakout.</li>
      <li><strong>Vibha Jha TQQQ overlay</strong> as separate research arm when stock setups dry up (hard risk budget; not DailyRun by default).</li>
      <li><strong>Bryan Johnson regime timer</strong> as risk-off overlay — reconstruct formulas; tiny crash sample = HOLD until walk-forward.</li>
      <li><strong>Law-style confluence + hard risk budget</strong> on top of existing RS/trend filters.</li>
      <li><strong>Revisit MVCP as research-only</strong> — do not re-wire DailyRun from contest nostalgia.</li>
      <li><strong>Explicitly park</strong> Gajjala-style low-float day trade and Enhanced Growth options paths.</li>
    </ol>
  </section>

  <p class="footnote">
    Sources: USIC Business Wire year-end releases (2019–2025); Complete Traders Edge USIC compilation (updated 2026-09-07);
    Robbins World Cup stock archive (Wayback); trader interviews / TraderLion / Business Insider (Gajjala, Sean Ryan) /
    J Law public materials / Martin Luk write-ups / AAII Bryan Johnson packet / Kell / Soreide interviews.
    Enriched 2026-09-20 from follow-up research pack (added Soreide, Sean Ryan split, Vibha Jha, Bryan Johnson timer, Tkaczuk/Flanders detail).
    Strategy descriptions are from public sources and may be incomplete.
    Championship returns ≠ GIPS composites ≠ student results ≠ TBN Closed stamp expectancy.
    Not investment advice. Generated 2026-09-20.
  </p>
  {SORTABLE_JS}
</body>
</html>
"""

out_path = OUT / "index.html"
out_path.write_text(html_doc, encoding="utf-8")
print(f"Wrote {out_path}")
