"""
Google Sheets **YH tab** — column title alignment (data starts in column **D** = Date).

This workbook is **separate** from the BRT pivot sheet. Do not mix column letters between
``sheet_column_reference.py`` (BRT) and this module (YH); titles are stable, letters drift.

Use **column titles** in user-facing docs and traces; use this module when decoding formulas.

Parity order for YH runs: **zones (YH Level → Matured touch price) → breakout/retest → trades**.

Generated mapping: first data column = **D** (Date = index 0).
"""

from __future__ import annotations

# Row 1 headers, left-to-right (live YH sheet export 2026-03).
YH_SHEET_HEADERS: tuple[str, ...] = (
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
    "Breakout zone upper",
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
    "New 52 week high flag",
    "YH Level",
    "0.03 move away next",
    "Active YH Touch Price",
    "YH zone lower",
    "YH zone upper",
    "Active YH Level",
    "Next YH candidate",
)

# Titles the YH zone engine must match (avoid Excel letters in logs).
YH_ZONE_PARITY_TITLES: tuple[str, ...] = (
    "New 52 week high flag",
    "YH Level",
    "0.03 move away next",
    "Active YH Touch Price",
    "Active YH Level",
    "Next YH candidate",
    "Matured touch price",
    "Matured Zone lower",
    "Matured zone upper",
)

YH_BREAKOUT_PARITY_TITLES: tuple[str, ...] = (
    "Breakout zone upper",
    "Selected Break lower",
    "Breakout event",
    "Create Breakout record",
    "Breakout Date",
    "Retest Date",
    "Too fast retest",
)

YH_TOUCH_PRICE_NOTE = """
**Touch Price** on the YH sheet uses the pivot-confirmed formula family (Final Pivot High +
post-pivot tests → bar **High**). It feeds **TP Zone Lower / TP Zone Upper**, **not** the YH zone
ladder.

YH zones use a different path — see ``YH_BX_BY_FORMULAS`` and ``YH_ZONE_TOUCH_SEMANTICS``.
"""

YH_BX_BY_FORMULAS = """
## New 52 week high flag

``=IF(ROW()<255,"",IF(High > MAX(High of prior 252 rows), 1, ""))``

## YH Level

``=IF(New 52 week high flag = 1, High, "")`` — snapshot only; **not** the pending zone touch.

## 0.03 move away next

Serial handoff (prior row → today):

``=IF(Next YH candidate <> "", prior Next YH candidate,
  IF(prior 0.03 move away next = "", YH Level,
  IF(prior Active YH Level = "", prior 0.03 move away next,
  IF(YH Level <> "", YH Level, prior 0.03 move away next))))``

## Active YH Touch Price

``=IF(0.03 move away next = "", "", 0.03 move away next * (1 + move_away_pct))``
(display may round to cents; **move-away test** is ``High >= BZ*(1+pct)`` on **full precision**,
e.g. NVDA 2021-11-09: High 32.31 vs 31.37×1.03 = 32.3111 → no activation).

## Active YH Level

``=IF(0.03 move away next = "", "",
  IF(OR(prior Active YH Level = 0.03 move away next, High >= Active YH Touch Price),
     0.03 move away next, ""))``
(use raw High vs unrounded ``BZ*(1+pct)`` for the inequality; same as above.)

## Next YH candidate

``=IF(AND(YH Level <> "", Active YH Level <> ""), YH Level, "")``

## Matured touch price

On activation rows, equals **Active YH Level** (which equals **0.03 move away next** at activation).
"""

YH_ZONE_TOUCH_SEMANTICS = """
## Observed sheet behavior (AAPL zone #11, TSLA zone #2, NVDA zone #51)

| Symbol | Assignment BY | Next-bar BY | Matured touch | Next-bar bump |
|--------|---------------|-------------|---------------|---------------|
| AAPL | 43.75 (11/6) | 43.81 (11/7) | **43.81** | +0.14% → supersede |
| TSLA | 18.72 (2/13) | 19.16 (2/14) | **18.72** | +2.35% → keep |
| NVDA | 32.31 (11/9) | 32.76 (11/18) | **32.76** | +1.39% → supersede? |

Leading engine hypothesis: after a zone is assigned, allow **one next NEW_YH bar** to supersede
the pending touch **only if** ``(BY_next - BY_assign) / BY_assign`` is below a sheet threshold
(likely ~2%%; confirm from **Matured touch price** formula or config cell).

On move-away activation (``High >= ROUND(pending_touch * 1.03, 2)``):
- **Matured touch price** = frozen pending touch (43.81 for AAPL #11)
- Same-bar **YH Level** may show today's High (45.12 on 2018-02-27) because BX=1 on that bar —
  unrelated to the matured center.

Engine gap: ``compute_yh_touch_stream`` keeps the assignment-bar touch (43.75) and ignores the
qualified next-bar supersede (43.81).
"""


def _excel_col_num_to_letters(n: int) -> str:
    if n < 1:
        raise ValueError("column index must be >= 1")
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def excel_column_from_d(index_from_d: int) -> str:
    """Column letter when ``YH_SHEET_HEADERS[0]`` (Date) is in column **D**."""
    if index_from_d < 0 or index_from_d >= len(YH_SHEET_HEADERS):
        raise IndexError("index_from_d out of range of YH_SHEET_HEADERS")
    return _excel_col_num_to_letters(4 + index_from_d)


def header_index_by_letter(col_letters: str) -> int:
    col_letters = col_letters.strip().upper()
    n = 0
    for c in col_letters:
        if not ("A" <= c <= "Z"):
            raise ValueError(f"invalid column: {col_letters!r}")
        n = n * 26 + (ord(c) - ord("A") + 1)
    idx = n - 4
    if idx < 0 or idx >= len(YH_SHEET_HEADERS):
        raise ValueError(
            f"column {col_letters} not covered by YH_SHEET_HEADERS (len={len(YH_SHEET_HEADERS)})"
        )
    return idx


def title_to_column(title: str) -> str:
    """Resolve a header title to a column letter (for formula audits only)."""
    t = title.strip()
    for i, h in enumerate(YH_SHEET_HEADERS):
        if h == t:
            return excel_column_from_d(i)
    raise KeyError(f"title not in YH_SHEET_HEADERS: {title!r}")


# Key titles → column letter (from D=Date layout above; re-run title_to_column if headers move)
YH_KEY_COLUMNS: dict[str, str] = {
    "Date": excel_column_from_d(0),
    "High": excel_column_from_d(2),
    "Touch Price": excel_column_from_d(YH_SHEET_HEADERS.index("Touch Price")),
    "Target": excel_column_from_d(YH_SHEET_HEADERS.index("Target")),
    "Matured touch price": excel_column_from_d(YH_SHEET_HEADERS.index("Matured touch price")),
    "Matured Zone lower": excel_column_from_d(YH_SHEET_HEADERS.index("Matured Zone lower")),
    "Matured zone upper": excel_column_from_d(YH_SHEET_HEADERS.index("Matured zone upper")),
    "New 52 week high flag": excel_column_from_d(YH_SHEET_HEADERS.index("New 52 week high flag")),
    "YH Level": excel_column_from_d(YH_SHEET_HEADERS.index("YH Level")),
    "0.03 move away next": excel_column_from_d(YH_SHEET_HEADERS.index("0.03 move away next")),
    "Active YH Touch Price": excel_column_from_d(YH_SHEET_HEADERS.index("Active YH Touch Price")),
    "Active YH Level": excel_column_from_d(YH_SHEET_HEADERS.index("Active YH Level")),
    "Next YH candidate": excel_column_from_d(YH_SHEET_HEADERS.index("Next YH candidate")),
    "Breakout zone upper": excel_column_from_d(YH_SHEET_HEADERS.index("Breakout zone upper")),
    "Create Breakout record": excel_column_from_d(YH_SHEET_HEADERS.index("Create Breakout record")),
    "Retest Date": excel_column_from_d(YH_SHEET_HEADERS.index("Retest Date")),
}
