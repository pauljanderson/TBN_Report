"""Score Paul's C/D/E band proposals vs the 27 Oct decile sheet.

Does not place, cancel, or sell. Does not start a second B. Does not bump
stake, leftover-GTC on A, D NFL, or retune B's C_LO / D=0.25. Band KEEP/HOLD
only — this job HOLD all three widths, so live C/D/E code is not patched.
"""
from __future__ import annotations

import html as html_mod
import json
import re
import sys
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import report_page_extras
from prediction_paths import DRIVE_STAMP as STAMP

try:
    from compare_format import format_money
except Exception:  # pragma: no cover
    def format_money(value, *, blank="—"):
        if value is None:
            return blank
        n = float(value)
        sign = "-" if n < 0 else ""
        return f"{sign}${abs(n):,.2f}"

ET = ZoneInfo("America/New_York")
PAGE = STAMP / "cde_band_decile_20261029.html"
JSON_PATH = STAMP / "sport_league_t0_decile_20261027.json"
HTML_PATH = STAMP / "sport_league_t0_decile_20261027.html"
FILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/cde_band_decile_20261029.html"
)
DECILE_URL = (
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/sport_league_t0_decile_20261027.html"
)

ASKED = (
    "Based on the latest decile report: "
    "file:///C:/Users/songg/Downloads/stockresearch/drive/paul_experiments/"
    "prediction_market_arb_exhaustive_20261017/sport_league_t0_decile_20261027.html "
    "I think we should change: system C from 50-89 to 70-89; system D to 60-89; "
    "system E tennis underdog from 0-49 (currently live is ~11-49 / 0.10<px<0.50). "
    "Live systems should match the sheet: deciles start at 0 and go to 9, not start "
    "at 1 and go to 9. If we change these, change the presentation too. Tell me if "
    "you agree or disagree."
)
PLAIN = (
    "We looked at the 10-cent price buckets on the sport / league sheet and asked "
    "whether C, D, and E should only bet the buckets that actually made money. "
    "C is college-football moneyline favorites (who wins the game). D is favorite-"
    "to-cover spreads (whether a team beats a point line), skipping NFL and skipping "
    "Points Total (the over/under on combined score). E is tennis underdogs — the "
    "cheaper player. Each proposal was scored on its own against today’s live freeze, "
    "on the 11-day four-platform tape and on Kalshi history separately. We did not "
    "blend those books. Picking a tighter band after seeing this table is in-sample "
    "selection. Tiny N is HOLD, not KEEP. If Kalshi history is worse than the live "
    "tape, HOLD — we do not retune to “fix” history. None of the three width changes "
    "cleared KEEP, so live C/D/E still send the old bands."
)

C_CUR = ["50-59", "60-69", "70-79", "80-89"]
C_NEW = ["70-79", "80-89"]
D_CUR = ["50-59", "60-69", "70-79", "80-89"]
D_NEW = ["60-69", "70-79", "80-89"]
E_CUR = ["10-19", "20-29", "30-39", "40-49"]
E_NEW = ["0-9", "10-19", "20-29", "30-39", "40-49"]
HEADERS = [
    ("Book", "text"),
    ("Arm", "text"),
    ("Deciles", "text"),
    ("N settled", "num"),
    ("Wins", "num"),
    ("Win%", "num"),
    ("N with fee", "num"),
    ("With-fee P&L", "num"),
    ("Avg with-fee P&L", "num"),
    ("Ann ROR full", "text"),
    ("Ann ROR IS", "text"),
    ("Ann ROR OOS", "text"),
    ("Note", "text"),
]
DEC_HEADERS = [
    ("Book", "text"),
    ("Sport", "text"),
    ("League", "text"),
    ("Bet type", "text"),
    ("Decile", "text"),
    ("N settled", "num"),
    ("Wins", "num"),
    ("Win%", "num"),
    ("N with fee", "num"),
    ("With-fee P&L", "num"),
    ("Avg with-fee P&L", "num"),
    ("Note", "text"),
]


def esc(value) -> str:
    return html_mod.escape("" if value is None else str(value))


def money(value, n_fee: int | None = None) -> str:
    if n_fee == 0 or value is None:
        return "—"
    return format_money(value)


def pct(n_win: int, n: int) -> str:
    if not n:
        return "—"
    return f"{100.0 * n_win / n:.1f}"


def add(rows: list[dict]) -> dict:
    n = nw = nf = 0
    pnl = 0.0
    anyp = False
    for rec in rows:
        if not rec:
            continue
        n += int(rec.get("n") or 0)
        nw += int(rec.get("n_win") or 0)
        nf += int(rec.get("n_fee") or 0)
        if rec.get("pnl_sum") is not None:
            pnl += float(rec["pnl_sum"])
            anyp = True
    return {
        "n": n,
        "n_win": nw,
        "n_fee": nf,
        "pnl": pnl if anyp else None,
        "avg": (pnl / nf) if nf and anyp else None,
        "wr": (100.0 * nw / n) if n else None,
    }


def get(cells: dict, sport: str, league: str, kind: str, dec: str) -> dict | None:
    return cells.get(f"{sport}|{league}|{kind}|{dec}")


def band(cells: dict, sport: str, league: str, kind: str, decs: list[str]) -> dict:
    recs = [get(cells, sport, league, kind, d) for d in decs]
    out = add([r for r in recs if r])
    out["by_dec"] = []
    for d, rec in zip(decs, recs):
        row = add([rec] if rec else [])
        row["decile"] = d
        out["by_dec"].append(row)
    return out


def d_spread(cells: dict, decs: list[str]) -> dict:
    recs = []
    by_sport: dict[str, list] = {}
    for key, rec in cells.items():
        sport, league, kind, dec = key.split("|")
        if kind != "Spread" or dec not in decs:
            continue
        if sport in {"pro football", "ALL"} or league in {"NFL", "ALL"}:
            continue
        recs.append(rec)
        by_sport.setdefault(sport, []).append(rec)
    out = add(recs)
    out["by_sport"] = {s: add(rs) for s, rs in sorted(by_sport.items())}
    return out


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_cell = False
        self.in_h2 = False
        self.in_h3 = False
        self.buf = ""
        self.h2 = ""
        self.h3 = ""
        self.row: list[str] = []
        self.cur_table: list[list[str]] = []
        self.tables: list[tuple[str, str, list]] = []
        self.capture = False

    def handle_starttag(self, tag, attrs):
        if tag == "h2":
            self.in_h2 = True
            self.buf = ""
        elif tag == "h3":
            self.in_h3 = True
            self.buf = ""
        elif tag == "table":
            self.cur_table = []
            self.capture = True
        elif tag in {"td", "th"} and self.capture:
            self.in_cell = True
            self.buf = ""

    def handle_endtag(self, tag):
        if tag == "h2":
            self.in_h2 = False
            self.h2 = re.sub(r"\s+", " ", self.buf).strip()
        elif tag == "h3":
            self.in_h3 = False
            self.h3 = re.sub(r"\s+", " ", self.buf).strip()
        elif tag in {"td", "th"} and self.capture:
            self.row.append(re.sub(r"\s+", " ", self.buf).strip())
            self.in_cell = False
        elif tag == "tr" and self.capture:
            if self.row:
                self.cur_table.append(self.row)
            self.row = []
        elif tag == "table" and self.capture:
            self.tables.append((self.h2, self.h3, self.cur_table))
            self.capture = False

    def handle_data(self, data):
        if self.in_h2 or self.in_h3 or self.in_cell:
            self.buf += data


def _parse_int(text: str) -> int:
    t = (text or "").replace(",", "").strip()
    if not t or t in {"—", "-"}:
        return 0
    try:
        return int(float(t))
    except ValueError:
        return 0


def _parse_pnl(text: str):
    t = (text or "").replace(",", "").replace("−", "-").replace("$", "").strip()
    if t in {"", "—", "-"}:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def parse_hist_cells(html_text: str) -> dict:
    parser = TableParser()
    parser.feed(html_text)
    out = {}
    for h2, _h3, table in parser.tables:
        if "Kalshi historical" not in h2 or not table:
            continue
        hdr = table[0]
        if "Decile" not in hdr or "Sport" not in hdr:
            continue
        idx = {name: i for i, name in enumerate(hdr)}
        for row in table[1:]:
            if len(row) <= idx.get("With-fee P&L", 8):
                continue
            sport = row[idx["Sport"]]
            league = row[idx["League"]]
            kind = row[idx["Bet type"]]
            dec = row[idx["Decile"]]
            out[f"{sport}|{league}|{kind}|{dec}"] = {
                "n": _parse_int(row[idx["N settled"]]),
                "n_win": _parse_int(row[idx["Wins"]]),
                "n_fee": _parse_int(row[idx["N with fee"]]),
                "pnl_sum": _parse_pnl(row[idx["With-fee P&L"]]),
            }
    return out


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{esc(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def table(headers: list[tuple[str, str]], rows: list[list[str]], *, total: list[str] | None = None) -> str:
    head = "".join(th(label, kind) for label, kind in headers)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    if total:
        body.append('<tr class="total-row">' + "".join(f"<td>{cell}</td>" for cell in total) + "</tr>")
    return (
        f"{report_page_extras.SWIPE_NOTE_HTML}"
        '<div class="table-wrap"><table class="sortable">'
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def metric_row(book: str, arm: str, decs: list[str], rec: dict, note: str) -> list[str]:
    return [
        esc(book),
        esc(arm),
        esc(", ".join(decs)),
        str(rec["n"]),
        str(rec["n_win"]),
        pct(rec["n_win"], rec["n"]),
        str(rec["n_fee"]),
        money(rec["pnl"], rec["n_fee"]),
        money(rec["avg"], rec["n_fee"]),
        "omitted (same-day)",
        "n/a (no IS; all T0 ≥ 2024-01-01)",
        "omitted (same-day) — whole book is OOS vs 2024-01-01",
        esc(note),
    ]


def dec_rows(book: str, sport: str, league: str, kind: str, rec: dict) -> list[list[str]]:
    rows = []
    for part in rec.get("by_dec") or []:
        tiny = "tiny N" if int(part["n"] or 0) < 20 else ""
        rows.append([
            esc(book),
            esc(sport),
            esc(league),
            esc(kind),
            esc(part["decile"]),
            str(part["n"]),
            str(part["n_win"]),
            pct(part["n_win"], part["n"]),
            str(part["n_fee"]),
            money(part["pnl"], part["n_fee"]),
            money(part["avg"], part["n_fee"]),
            esc(tiny),
        ])
    return rows


def score_all() -> dict:
    dump = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    live = dump.get("live_cells") or {}
    hist = parse_hist_cells(HTML_PATH.read_text(encoding="utf-8"))
    c_live_cur = band(live, "college football", "CFB", "Moneyline", C_CUR)
    c_live_new = band(live, "college football", "CFB", "Moneyline", C_NEW)
    c_hist_cur = band(hist, "college football", "CFB", "Moneyline", C_CUR)
    c_hist_new = band(hist, "college football", "CFB", "Moneyline", C_NEW)
    d_live_cur = d_spread(live, D_CUR)
    d_live_new = d_spread(live, D_NEW)
    d_hist_cur = d_spread(hist, D_CUR)
    d_hist_new = d_spread(hist, D_NEW)
    d_cfb_live_cur = band(live, "college football", "CFB", "Spread", D_CUR)
    d_cfb_live_new = band(live, "college football", "CFB", "Spread", D_NEW)
    d_cfb_hist_cur = band(hist, "college football", "CFB", "Spread", D_CUR)
    d_cfb_hist_new = band(hist, "college football", "CFB", "Spread", D_NEW)
    d_nfl_live = band(live, "pro football", "NFL", "Spread", D_CUR)
    e_live_cur = band(live, "tennis", "ALL", "Moneyline", E_CUR)
    e_live_new = band(live, "tennis", "ALL", "Moneyline", E_NEW)
    e_live_09 = band(live, "tennis", "ALL", "Moneyline", ["0-9"])
    e_hist_cur = band(hist, "tennis", "ALL", "Moneyline", E_CUR)
    e_hist_new = band(hist, "tennis", "ALL", "Moneyline", E_NEW)
    e_hist_09 = band(hist, "tennis", "ALL", "Moneyline", ["0-9"])
    return {
        "dump": dump,
        "live": live,
        "hist": hist,
        "c_live_cur": c_live_cur,
        "c_live_new": c_live_new,
        "c_hist_cur": c_hist_cur,
        "c_hist_new": c_hist_new,
        "d_live_cur": d_live_cur,
        "d_live_new": d_live_new,
        "d_hist_cur": d_hist_cur,
        "d_hist_new": d_hist_new,
        "d_cfb_live_cur": d_cfb_live_cur,
        "d_cfb_live_new": d_cfb_live_new,
        "d_cfb_hist_cur": d_cfb_hist_cur,
        "d_cfb_hist_new": d_cfb_hist_new,
        "d_nfl_live": d_nfl_live,
        "e_live_cur": e_live_cur,
        "e_live_new": e_live_new,
        "e_live_09": e_live_09,
        "e_hist_cur": e_hist_cur,
        "e_hist_new": e_hist_new,
        "e_hist_09": e_hist_09,
    }


def write_html(s: dict) -> str:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    c_l_cur, c_l_new = s["c_live_cur"], s["c_live_new"]
    c_h_cur, c_h_new = s["c_hist_cur"], s["c_hist_new"]
    d_l_cur, d_l_new = s["d_live_cur"], s["d_live_new"]
    d_h_cur, d_h_new = s["d_hist_cur"], s["d_hist_new"]
    e_l_cur, e_l_new = s["e_live_cur"], s["e_live_new"]
    e_h_cur, e_h_new = s["e_hist_cur"], s["e_hist_new"]

    verdict = table(
        [("Proposal", "text"), ("Agree?", "text"), ("Wired?", "text"), ("Why", "text")],
        [
            [
                "C 70–89 (from live 51–89 / sheet 50–89)",
                "DISAGREE — HOLD",
                "No. Live C stays 51–89¢ (0.50 &lt; px &lt; 0.90)",
                (
                    f"Live quality looks better (N={c_l_cur['n']} avg {money(c_l_cur['avg'], c_l_cur['n_fee'])} "
                    f"→ N={c_l_new['n']} avg {money(c_l_new['avg'], c_l_new['n_fee'])}) but N is tiny and "
                    f"halves. Kalshi hist 70–89 is N={c_h_new['n']} (one ticket, a loss). Hist 50–89 is "
                    f"already negative (N={c_h_cur['n']}, avg {money(c_h_cur['avg'], c_h_cur['n_fee'])}). "
                    "Hist inverts vs live. Tiny N → HOLD, not KEEP. Selection bias after seeing the sheet."
                ),
            ],
            [
                "D 60–89 (from live 51–89 / sheet 50–89)",
                "DISAGREE — HOLD",
                "No. Live D stays 51–89¢ (0.50 &lt; px &lt; 0.90)",
                (
                    f"Live non-NFL spread 50–89: N={d_l_cur['n']} WR {pct(d_l_cur['n_win'], d_l_cur['n'])}% "
                    f"avg {money(d_l_cur['avg'], d_l_cur['n_fee'])}. Proposed 60–89: N={d_l_new['n']} WR "
                    f"{pct(d_l_new['n_win'], d_l_new['n'])}% avg {money(d_l_new['avg'], d_l_new['n_fee'])}. "
                    "N holds up on the 11-day tape. Kalshi hist does not: 50–89 avg "
                    f"{money(d_h_cur['avg'], d_h_cur['n_fee'])} (N={d_h_cur['n']}) vs 60–89 avg "
                    f"{money(d_h_new['avg'], d_h_new['n_fee'])} (N={d_h_new['n']}) — win% up a bit, "
                    "avg P&amp;L worse, both large losers. Hist softens vs live → HOLD. Do not retune."
                ),
            ],
            [
                "E 0–49 (from live 11–49 / sheet 10–49)",
                "DISAGREE — HOLD",
                "No. Live E stays 11–49¢ (0.10 &lt; px &lt; 0.50)",
                (
                    f"Live tennis moneyline 10–49: N={e_l_cur['n']} WR {pct(e_l_cur['n_win'], e_l_cur['n'])}% "
                    f"avg {money(e_l_cur['avg'], e_l_cur['n_fee'])} on {e_l_cur['n_fee']} fee rows. "
                    f"0–49: N={e_l_new['n']} WR {pct(e_l_new['n_win'], e_l_new['n'])}% avg "
                    f"{money(e_l_new['avg'], e_l_new['n_fee'])}. Win% drops. The added 0–9 bucket is "
                    f"N={s['e_live_09']['n']} wins={s['e_live_09']['n_win']} (WR "
                    f"{pct(s['e_live_09']['n_win'], s['e_live_09']['n'])}%) with only "
                    f"{s['e_live_09']['n_fee']} fee rows. Kalshi hist 0–9: N={s['e_hist_09']['n']} WR "
                    f"{pct(s['e_hist_09']['n_win'], s['e_hist_09']['n'])}% avg "
                    f"{money(s['e_hist_09']['avg'], s['e_hist_09']['n_fee'])}. Hist 10–49 already loses; "
                    "adding 0–9 makes win% worse. KEEP needs quality up, not a cheaper longshot add-on."
                ),
            ],
            [
                "0-based decile edges (include 0/10/50/60/70.0, not 1/11/51)",
                "AGREE the sheet is 0-based; HOLD the live exclusive→inclusive flip",
                "No. Exclusive edges stay (51–89 / 11–49)",
                (
                    "Sheet 0=0–9¢ includes 0.0, 1=10–19 includes 10.0, 5=50–59 includes 50.0, "
                    "7=70–79 includes 70.0. Live C/D skip 50.0; live E skips 10.0. That is the "
                    "mismatch. We agree the labels should match the sheet. We did not wire it: "
                    "HOLD a band means do not change that live system, and flipping 50¢/10¢ by "
                    "itself is not a quality KEEP. 50–59 is a losing/flat bucket on both C and D; "
                    "10¢ sits on the left edge of E’s already-KEEP 10–49 freeze."
                ),
            ],
        ],
    )

    c_cmp = table(
        HEADERS,
        [
            metric_row("Live tape 17–29 Oct 2026", "C current freeze (sheet 50–89)", C_CUR, c_l_cur, "tiny N; 50–59 and 60–69 dragged avg negative"),
            metric_row("Live tape 17–29 Oct 2026", "C proposed 70–89", C_NEW, c_l_new, "tiny N; 6/6 on this 11-day book — selection bias"),
            metric_row("Kalshi hist Yes-ask Apr 2025–Oct 2026", "C current 50–89", C_CUR, c_h_cur, "Kalshi CFB moneyline T0 asks cluster at 0–49 and 90–99; 50–89 is sparse"),
            metric_row("Kalshi hist Yes-ask Apr 2025–Oct 2026", "C proposed 70–89", C_NEW, c_h_new, "N=1 loss. HOLD"),
        ],
    )
    d_cmp = table(
        HEADERS,
        [
            metric_row("Live tape 17–29 Oct 2026", "D current freeze, non-NFL spread 50–89", D_CUR, d_l_cur, "sheet is all fav-side spread Yes, not live ‘closest line to 50¢’ filter"),
            metric_row("Live tape 17–29 Oct 2026", "D proposed 60–89 non-NFL spread", D_NEW, d_l_new, "live quality up, N still ok; hist must confirm"),
            metric_row("Live tape 17–29 Oct 2026", "D CFB-only spread 50–89 (majority of D)", D_CUR, s["d_cfb_live_cur"], "matches the PPTX CFB box"),
            metric_row("Live tape 17–29 Oct 2026", "D CFB-only spread 60–89", D_NEW, s["d_cfb_live_new"], ""),
            metric_row("Live tape 17–29 Oct 2026", "NFL spread 50–89 (D skips NFL)", D_CUR, s["d_nfl_live"], "shown so the skip still has a number; not a D send"),
            metric_row("Kalshi hist Yes-ask Apr 2025–Oct 2026", "D current 50–89 non-NFL spread", D_CUR, d_h_cur, "large loser; do not blend with live"),
            metric_row("Kalshi hist Yes-ask Apr 2025–Oct 2026", "D proposed 60–89 non-NFL spread", D_NEW, d_h_new, "WR up, avg P&L worse than 50–89 hist → HOLD"),
            metric_row("Kalshi hist Yes-ask Apr 2025–Oct 2026", "D CFB-only spread 50–89", D_CUR, s["d_cfb_hist_cur"], ""),
            metric_row("Kalshi hist Yes-ask Apr 2025–Oct 2026", "D CFB-only spread 60–89", D_NEW, s["d_cfb_hist_new"], ""),
        ],
    )
    e_cmp = table(
        HEADERS,
        [
            metric_row("Live tape 17–29 Oct 2026", "E current freeze (sheet 10–49)", E_CUR, e_l_cur, "live exclusive 11–49; sheet 10–49 includes 10.0"),
            metric_row("Live tape 17–29 Oct 2026", "E proposed 0–49", E_NEW, e_l_new, "WR down; avg $ slightly up on incomplete 0–9 fees"),
            metric_row("Live tape 17–29 Oct 2026", "E added 0–9 only", ["0-9"], s["e_live_09"], "2 wins / 39; n_fee=9 (Novig omitted on most)"),
            metric_row("Kalshi hist Yes-ask Apr 2025–Oct 2026", "E current 10–49", E_CUR, e_h_cur, "N is real; avg negative"),
            metric_row("Kalshi hist Yes-ask Apr 2025–Oct 2026", "E proposed 0–49", E_NEW, e_h_new, "WR 30.6% → 26.0%"),
            metric_row("Kalshi hist Yes-ask Apr 2025–Oct 2026", "E added 0–9 only", ["0-9"], s["e_hist_09"], "2.0% WR loser"),
        ],
    )

    c_dec = table(
        DEC_HEADERS,
        dec_rows("Live tape", "college football", "CFB", "Moneyline", c_l_cur)
        + dec_rows("Kalshi hist", "college football", "CFB", "Moneyline", c_h_cur),
    )
    d_dec = table(
        DEC_HEADERS,
        dec_rows("Live tape", "college football", "CFB", "Spread", s["d_cfb_live_cur"])
        + dec_rows("Kalshi hist", "college football", "CFB", "Spread", s["d_cfb_hist_cur"]),
    )
    e_dec = table(
        DEC_HEADERS,
        dec_rows("Live tape", "tennis", "ALL", "Moneyline", e_l_new)
        + dec_rows("Kalshi hist", "tennis", "ALL", "Moneyline", e_h_new),
    )

    d_sport_rows = []
    for sport, rec in (d_l_cur.get("by_sport") or {}).items():
        d_sport_rows.append(metric_row("Live tape 50–89", sport, D_CUR, rec, "non-NFL spread"))
    for sport, rec in (d_l_new.get("by_sport") or {}).items():
        d_sport_rows.append(metric_row("Live tape 60–89", sport, D_NEW, rec, "non-NFL spread"))
    d_sport = table(HEADERS, d_sport_rows)

    freeze = table(
        [("System", "text"), ("Live freeze after this job", "text"), ("Code", "text"), ("Reload", "text")],
        [
            ["C college-football moneyline favorite", "51–89¢ (50 skipped, 90 skipped)", "<code>in_fav_band</code>: 0.50 &lt; px &lt; 0.90", "none — code unchanged"],
            ["D T0 spread fav-to-cover, closest to 50¢, no NFL, not Points Total", "51–89¢ (same helper as C)", "<code>in_fav_band</code> + <code>pick_spread_line</code>", "none — code unchanged"],
            ["E tennis T0 dog, cheapest of 4, skip-if-B, stake $1, max_open 2", "11–49¢ (10 skipped, 50 skipped)", "<code>in_dog_band</code>: 0.10 &lt; px &lt; 0.50", "none — code unchanged"],
            ["B tennis crossover", "untouched (C_LO=1.05 and D=0.25 dip not this job)", "did not restart B", "none"],
        ],
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{report_page_extras.CACHE_META}
<title>C/D/E band vs decile sheet 29 Oct 2026</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
.hold {{ background: #fef3c7; border-color: #f59e0b; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
h1 {{ margin: 0 0 0.4rem; }}
h2 {{ margin: 1.4rem 0 0.5rem; }}
code {{ font-size: 0.92em; }}
{report_page_extras.SORTABLE_TH_CSS}
</style>
{report_page_extras.FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>C / D / E price bands vs the 10-cent sheet</h1>
<p class="note">Written {esc(now)}. Named-Yes T0 tape, not the live kitchen fills.
Did not sell tickets, start a second Tennis crossover (B), bump stake, leftover-GTC on A,
wire D NFL, or retune B’s C_LO=1.05 / D=0.25 dip. Those are different knobs from C/D/E
price bands. Click column headers to sort.</p>

<div class="callout"><h2>What you asked</h2><p>{esc(ASKED)}</p></div>
<div class="callout"><h2>In plain English</h2><p>{esc(PLAIN)}</p></div>

<div class="callout hold">
<h2>Verdict — HOLD all three widths. Live C/D/E unchanged.</h2>
<p>Choosing 70–89 / 60–89 / 0–49 after seeing
<a href="{esc(DECILE_URL)}">sport_league_t0_decile_20261027.html</a>
is in-sample selection on a 13-day live tape (17–29 Oct 2026). Kalshi Yes-ask history
(Apr 2025–Oct 2026) is reported separately and is not blended. Polymarket last-trade
hist on that page is empty (N=0). KEEP needs win%, with-fee avg P&amp;L, and N that
does not collapse, on the relevant sport/type cells. Tiny N is HOLD. If history
softens vs live, HOLD — do not retune history. One-change honesty: each band vs the
current freeze, independently.</p>
</div>

<h2>Agree or disagree</h2>
<p class="note">Swipe sideways to see more columns.</p>
{verdict}

<h2>Live freeze after this job</h2>
{freeze}

<h2>Process</h2>
<ul>
<li>IS vs OOS: this tape has no in-sample row versus 2024-01-01 (every T0 is 2025–2026).
The <em>selection</em> is still in-sample on the 17–29 Oct live sheet. Kalshi hist is the
longer confirmation book, still all out-of-sample versus 2024-01-01, and it was not used
to pick a new band.</li>
<li>P&amp;L is buy one named Yes at T0 ask plus documented taker fee, hold to settlement.
A win pays $1. Novig rows often have no documented fee, so N_fee can be smaller than N.
Annualized rate of return is omitted — same-day holds overflow the house formula
<code>((1 + total_pnl / (brt_cash × n_trades)) ** (365 / avg_days_held) − 1) × 100</code>.</li>
<li>Sheet cells are named-Yes after one-venue pick, both sides. C uses CFB moneyline
50–89 (the favorite side). D uses Spread 50–89 excluding NFL / pro football and excluding
Points Total; live D also takes only the line closest to 50¢, so the sheet is a superset.
E uses tennis moneyline 0–49 (the dog side); live E also requires a unique cheaper of four
and skip-if-B, which the sheet does not apply.</li>
<li>Live exclusive edges today: C/D <code>0.50 &lt; px &lt; 0.90</code> (51–89¢),
E <code>0.10 &lt; px &lt; 0.50</code> (11–49¢). Paul previously wanted 50–89 printed;
code stayed 51–89. He now wants 70–89 / 60–89 / 0–49 with sheet-matching inclusive
left edges. We HOLD the widths, so we also left the exclusive edges.</li>
</ul>

<h2>C — college football moneyline favorite</h2>
<p class="note">Relevant cells: college football / CFB / Moneyline. Current freeze maps to
sheet 50–89 (live skips exact 50¢). Proposed 70–89 is sheet 7–8.</p>
{c_cmp}
<h3>C by 10-cent bucket</h3>
{c_dec}

<h2>D — T0 spreads, favorite to cover, no NFL, not Points Total</h2>
<p class="note">Relevant cells: Spread, exclude sport=pro football / league=NFL, exclude
Points Total. ALL-league rollups are not double-counted. Current freeze maps to sheet
50–89. Proposed 60–89 is sheet 6–8.</p>
{d_cmp}
<h3>D live tape by sport (non-NFL spread)</h3>
{d_sport}
<h3>D CFB spread by 10-cent bucket</h3>
{d_dec}

<h2>E — tennis moneyline underdog</h2>
<p class="note">Relevant cells: tennis / ALL / Moneyline 0–49. Current freeze maps to sheet
10–49 (live skips exact 10¢). Proposed 0–49 is sheet 0–4.</p>
{e_cmp}
<h3>E by 10-cent bucket (0–49)</h3>
{e_dec}

<p class="tiny">Sources: <code>{esc(JSON_PATH.as_posix())}</code>,
<code>tools/_write_sport_league_t0_decile_20261027.py</code> decile convention
(<code>[0.00,0.10)=0-9</code> … <code>[0.90,1.00]=90-99</code>),
<code>tools/prediction_systems.py</code> <code>in_fav_band</code> / <code>in_dog_band</code>,
<code>tools/live_t0_yes.py</code>, <code>tools/live_tennis_t0_dog.py</code>.
File URL {esc(FILE_URL)}. Did not mix sportsbook closes. Did not commit.</p>
{report_page_extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(html, encoding="utf-8")
    return str(PAGE)


def main() -> int:
    scored = score_all()
    path = write_html(scored)
    print(f"wrote {path}", flush=True)
    print(
        "HOLD C 70-89; HOLD D 60-89; HOLD E 0-49; "
        "agree 0-based labels, HOLD exclusive-edge flip; live C/D/E unchanged",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
