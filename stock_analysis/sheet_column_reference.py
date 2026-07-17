"""
Google Sheets **BRT tab** — column letter alignment (data starts in column **D** = Date).

**Separate workbook:** Year-High zones use a different sheet tab — see
``sheet_column_reference_yh.py``. Do not assume BRT column letters apply on the YH tab.

Use this module as the single source of truth for **BRT sheet column ↔ header name** mapping.
`rocket_brt.py` internal names like ``sheet_prefetched_support_evidence_arr`` (alias
``sheet_prefetched_ak_arr``) / ``_ak_at`` refer to **legacy ladder** semantics (support /
resistance evidence) and are **not** the same as Excel column **AK** on the sheet.

**Sheet corrections (vs older code comments):**
- **AI** = *Range Qualifier* — **not** an input to **AL** *BRT Rocket buy* (buy signal does not require it).
- **BC** = *NEW FORMULA to check ALL zones* (breakout upper pick) — **not** *ATH filter* (**AY** in D:BW layout).
- **AK** = *Close above open* (boolean), not a ladder “AK gate”.
- **AQ** = *Exit type* (not “zone eligible long / AQ gate”).
- **C27** (entry close range position / BE) is **unused** in this workbook (blank).
- **Live workbook (2026):** data columns **D** through **BW** (72 columns). No **CG:DC** zone stack.
  Matured zones are **AZ:BB** (*Matured touch price* / *lower* / *upper*). Breakout per-row uses
  **BC:BG**; ledger fields **BH:BO** (*Breakout Date* … *Retest Date*) sit on the same daily grid.
- **Main Row** in the ledger is ``MATCH(Breakout Date, D:D, 0)`` — not ``ROW()`` of the breakout bar
  with a mysterious offset. Engine ``main_row = bar_index + 2`` differs when the CSV starts before
  **D2** (e.g. CSV **2016-01-04** vs sheet **D2 = 2016-01-14** → engine row is **+8**).
- **Scan Start Row** = Main Row + **C19** (retest delay; default **2**). Same as
  ``sheet_breakout_scan_start_row_delta`` in ``rocket_brt.py``.
- **AL** legacy note: older docs used **AK**/**AZ** for buy gates; live sheet uses **AG**/**AV**/**BO** (see ``SHEET_ROCKET_BUY_FORMULA``).
- **CB** on the compact sheet is **BRT Summary** — **not** Python’s ``consolidation_blocker_enabled`` (old docs tied **CB** to a zone ladder that no longer exists in row 1).

**Breakout parity (proposal):** see ``BREAKOUT_PARITY_PROPOSAL`` below.

**Entry gates (sheet vs program):** see ``ENTRY_GATES_SHEET_VS_PROGRAM.md`` for a full gate-order
comparison with ``rocket_brt.py``.

Generated mapping: first column letter = ``D`` (Date = index 0). Column letter for
header index *i* is ``excel_column_from_d(0) + i``.
"""

from __future__ import annotations

# --- Ordered headers (row 1), left-to-right, first cell = Date in column D ---
# Authoritative layout (2026): **D:BW** — no CG:DC ladder; matured zones AZ:BB; breakout BC:BG; ledger BH:BO.
SHEET_HEADERS: tuple[str, ...] = (
    "Date",
    "Open",
    "High",
    "Low",
    "Close",
    "Volume",
    "Local High Test",
    "Post Pivot Pullback",
    "No dup Pivot High",
    "Not also Pivot Low",
    "Final Pivot High",
    "Local Low test",
    "Future Rise test",
    "No dup pivot low",
    "Not also pivot high",
    "Final pivot low",
    "Pivot High Price",
    "Pivot low price",
    "Last Pivot High",
    "Last Pivot low",
    "Major Pivot High",
    "Major Pivot Low",
    "Pre-strong pivot High",
    "Pre-Strong Pivot Low",
    "Touch Price",
    "TP Zone Lower",
    "TP Zone Upper",
    "Range Qualifier",
    "Target",
    "Close above open",
    "BRT Rocket buy",
    "Stop",
    "exit hit today",
    "IN trade",
    "Risk Reward",
    "Exit type",
    "Exit price",
    "Entry Price Active",
    "Entry Date Active",
    "Peak High",
    "Current Drawdown",
    "Max Drawdown",
    "Growth 1 Year",
    "Growth 2 Year",
    "Growth 3 Year",
    "Raw Growth",
    "Growth OK",
    "ATH filter",
    "Matured touch price",
    "Matured Zone lower",
    "Matured zone upper",
    "NEW FORMULA to check ALL zones",
    "Selected break upper",
    "Selected Break lower",
    "Breakout event",
    "Create Breakout record",
    "Breakout Date",
    "Zone Lower",
    "Zone Upper",
    "Breakout Active",
    "Main Row",
    "Scan Start Row",
    "retest Row",
    "Retest Date",
    "retest hit",
    "Too fast retest",
    "BRT Summary",
    "BRT Values",
    "Retest Lag days",
    "True Range",
    "ATR",
    "ATR %",
)

# Use these in logs/traces instead of Excel letters (letters drift when columns move).
ENTRY_GATE_SHEET_TITLES: dict[str, str] = {
    "close_above_open": "Close above open",
    "growth_3_year": "Growth 3 Year",
    "create_breakout_record": "Create Breakout record",
    "retest_date": "Retest Date",
    "brt_rocket_buy": "BRT Rocket buy",
}

SHEET_ROCKET_BUY_FORMULA = """
**AH** *BRT Rocket buy* (live sheet):
``=OR(AND($AG2=TRUE,$AV2=TRUE,COUNTIF($BO:$BO,$D2)>0,$H1<=$E1,$H2>$E2))``

| Operand | Column | Meaning |
|---------|--------|---------|
| AG | Close above open | Eval bar bullish |
| AV | Growth 3 Year | ``Close[eval] >= Close[eval-756]`` |
| BO | Retest Date | ``COUNTIF($BO:$BO,$D)>0`` on eval date **D** |
| H1<=E1 | Prior Close <= Prior Open | Red-to-green: prior bar red/flat |
| H2>E2 | Close > Open | Eval bar green |

Engine: ``sheet_red_to_green_entry_enabled`` + growth + ``sheet_dw_countif_entry_enabled``.
"""

# Per-row breakout detection (BC:BG on daily grid).
BREAKOUT_PER_ROW_COLUMNS: dict[str, str] = {
    "BC": "NEW FORMULA to check ALL zones",
    "BD": "Selected break upper",
    "BE": "Selected Break lower",
    "BF": "Breakout event",
    "BG": "Create Breakout record",
}

BREAKOUT_PER_ROW_FORMULAS = """
## BC:BG (daily grid row 2+)

**AZ** / **BA** / **BB** = *Matured touch price* / *Matured Zone lower* / *Matured zone upper*.

| Col | Header | Formula |
|-----|--------|---------|
| BC | NEW FORMULA to check ALL zones | ``MIN(FILTER(zU, prior_close<zU, close>=zU))`` over BA/BB pairs rows 2..ROW()-1 |
| BE | Selected Break lower | ``INDEX(FILTER(BA where BB=BC), 1)`` |
| BF | Breakout event | ``IF(BC="", "", 1)`` |
| BG | Create Breakout record | ``IF(BF=1, 1, "")`` |

**Cross rule:** prior **Close** ``H[row-1] < zone upper`` and current **Close** ``H[row] >= zone upper``.
**Pick rule (BC):** **MIN(zone upper)** among crossed matured bands (not MAX).
**AB touch pullback:** forward **C14** bars (periods to check = 10), not C10 (7). Maturity lag AZ:BB uses **C10**.
"""

# Ledger columns on the same row when BG=1 (export as tools/*_brt_sheet_breakout_retest.tsv).
BREAKOUT_LEDGER_COLUMNS: dict[str, str] = {
    "BH": "Breakout Date",
    "BI": "Zone Lower",
    "BJ": "Zone Upper",
    "BK": "Breakout Active",
    "BL": "Main Row",
    "BM": "Scan Start Row",
    "BN": "retest Row",
    "BO": "Retest Date",
    "BP": "retest hit",
    "BQ": "Too fast retest",
}

BREAKOUT_LEDGER_FORMULAS = """
## Ledger fields BH:BO (on breakout rows where BG=1)

| Col | Header | Typical formula |
|-----|--------|-----------------|
| BH | Breakout Date | **D** on breakout row |
| BI | Zone Lower | **BE** (Selected Break lower) |
| BJ | Zone Upper | **BC** (picked zone upper) |
| BK | Breakout Active | **BF** |
| BL | Main Row | ``MATCH(BH, D:D, 0)`` — **D2** = first data row (e.g. 2016-01-03) |
| BM | Scan Start Row | ``BL + C19`` — **C19** retest delay = **2** |
| BN | retest Row | First row where Low<=BJ, High>=BI, row>=BM |
| BO | Retest Date | ``INDEX(D:D, BN)`` |

**Main Row vs engine:** CSV may start before **D2** → engine row +8 when CSV begins 2016-01-04 and sheet **D2=2016-01-03**.
"""


def _excel_col_num_to_letters(n: int) -> str:
    """1-based Excel column index → letters (1=A, 4=D, 27=AA)."""
    if n < 1:
        raise ValueError("column index must be >= 1")
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def excel_column_from_d(index_from_d: int) -> str:
    """Column letter when ``SHEET_HEADERS[0]`` (Date) is in column **D** (Excel column 4)."""
    if index_from_d < 0 or index_from_d >= len(SHEET_HEADERS):
        raise IndexError("index_from_d out of range of SHEET_HEADERS")
    return _excel_col_num_to_letters(4 + index_from_d)


def header_index_by_letter(col_letters: str) -> int:
    """Excel column letters → index into ``SHEET_HEADERS`` (0 = Date)."""
    col_letters = col_letters.strip().upper()
    n = 0
    for c in col_letters:
        if not ("A" <= c <= "Z"):
            raise ValueError(f"invalid column: {col_letters!r}")
        n = n * 26 + (ord(c) - ord("A") + 1)
    idx = n - 4
    if idx < 0 or idx >= len(SHEET_HEADERS):
        raise ValueError(f"column {col_letters} not covered by SHEET_HEADERS (len={len(SHEET_HEADERS)})")
    return idx


# Key lookups (authoritative names → column letter from D)
KEY_COLUMNS: dict[str, str] = {
    "Date": excel_column_from_d(0),
    "Open": excel_column_from_d(1),
    "High": excel_column_from_d(2),
    "Low": excel_column_from_d(3),
    "Close": excel_column_from_d(4),
    "Touch Price": excel_column_from_d(SHEET_HEADERS.index("Touch Price")),
    "TP Zone Lower": excel_column_from_d(SHEET_HEADERS.index("TP Zone Lower")),
    "TP Zone Upper": excel_column_from_d(SHEET_HEADERS.index("TP Zone Upper")),
    "Range Qualifier": excel_column_from_d(SHEET_HEADERS.index("Range Qualifier")),
    "Close above open": excel_column_from_d(SHEET_HEADERS.index("Close above open")),
    "BRT Rocket buy": excel_column_from_d(SHEET_HEADERS.index("BRT Rocket buy")),
    "Exit type": excel_column_from_d(SHEET_HEADERS.index("Exit type")),
    "Matured Zone lower": excel_column_from_d(SHEET_HEADERS.index("Matured Zone lower")),
    "Matured zone upper": excel_column_from_d(SHEET_HEADERS.index("Matured zone upper")),
    "ATH filter": excel_column_from_d(SHEET_HEADERS.index("ATH filter")),
    "Breakout Date": "BH",
    "Retest Date": "BO",
    "Create Breakout record": "BG",
    "Main Row": "BL",
    "Scan Start Row": "BM",
}

# Quick letter → canonical header name (D:BW layout)
COLUMN_LETTER_TO_HEADER: dict[str, str] = {
    "AB": "Touch Price",
    "AC": "TP Zone Lower",
    "AD": "TP Zone Upper",
    "AG": "Close above open",
    "AH": "BRT Rocket buy",
    "AM": "Exit type",
    "AT": "Growth 1 Year",
    "AU": "Growth 2 Year",
    "AV": "Growth 3 Year",
    "AZ": "Matured touch price",
    "BA": "Matured Zone lower",
    "BB": "Matured zone upper",
    "BC": "NEW FORMULA to check ALL zones",
    "BE": "Selected Break lower",
    "BF": "Breakout event",
    "BG": "Create Breakout record",
    "BH": "Breakout Date",
    "BI": "Zone Lower",
    "BJ": "Zone Upper",
    "BO": "Retest Date",
}


BREAKOUT_PARITY_PROPOSAL = """
## Goal
Match the sheet’s breakout / retest pipeline so ``BRT Rocket buy`` and program entries
use the same prerequisites.

## Sheet-side (authoritative — live layout)
See ``BREAKOUT_LEDGER_FORMULAS`` and ``BREAKOUT_PER_ROW_COLUMNS`` in this module.
- **BG=1** rows feed the **BH:BQ** ledger via FILTER.
- **BO** (*Retest Date*) feeds buy gates via ``COUNTIF($BO:$BO, $D2)`` (letter may differ on buy row).
- **BM** = Main Row + **C19** (retest delay 2) — first bar eligible for **BN** retest scan.

## Program-side
1. **Breakout pick** — ``_sheet_pick_di_breakout_zone_long``: **MIN(zone upper)** among crossed
   matured BA/BB bands before the breakout bar (matches sheet **BC**).
2. **Retest** — overlap from ``breakout_bar + sheet_breakout_scan_start_row_delta`` (default 2).
3. **Too fast retest (BQ)** — not yet implemented in engine; checks overlap on Main Row + 1.
4. **Main Row export** — cosmetic +8 vs sheet when CSV starts before **D2**; compare dates not rows.

## What “correct” means
- **Sheet** is authoritative for column meaning and formula precedence.
- **Program** should match **BG** breakout creation, **BN/BO** retest, then buy gates.
"""
