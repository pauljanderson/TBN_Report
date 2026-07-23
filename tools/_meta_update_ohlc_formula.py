#!/usr/bin/env python3
"""Merge META OHLC overrides into OHLC_override_formula.md (preserve all tickers)."""
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "drive" / "brt_sheet_reconcile"
PATH = OUT / "OHLC_override_formula.md"

# One continuous line — no breaks inside the formula.
FORMULA = (
    '=LET(d,D2,raw,IFERROR(QUERY(GOOGLEFINANCE(C$1,"all",d,d),"SELECT Col2,Col3,Col4,Col5,Col6 OFFSET 1",0),{0,0,0,0,0}),'
    "o,INDEX(raw,1,1),h,INDEX(raw,1,2),l,INDEX(raw,1,3),c,INDEX(raw,1,4),v,INDEX(raw,1,5),"
    'tsla,UPPER(TRIM(C$1))="TSLA",amd,UPPER(TRIM(C$1))="AMD",msft,UPPER(TRIM(C$1))="MSFT",'
    'nflx,UPPER(TRIM(C$1))="NFLX",nvda,UPPER(TRIM(C$1))="NVDA",au,UPPER(TRIM(C$1))="AU",'
    'meta,UPPER(TRIM(C$1))="META",'
    "oFix,IF(tsla,IFS(d=DATE(2025,5,22),331.9,d=DATE(2018,5,18),18.98,d=DATE(2018,3,13),21.91,TRUE,o),"
    "IF(AND(amd,d=DATE(2018,5,18)),13.06,"
    "IF(AND(nvda,d=DATE(2025,5,22)),132.23,"
    "IF(au,IFS(d=DATE(2024,10,15),27.29,d=DATE(2025,5,22),42.83,TRUE,o),o)))),"
    "hFix,IF(tsla,IFS(d=DATE(2025,5,22),347.27,d=DATE(2018,5,18),18.98,d=DATE(2018,3,13),23.15,"
    "d=DATE(2018,3,23),20.75,d=DATE(2021,3,1),239.67,d=DATE(2021,3,4),222.82,TRUE,h),"
    "IF(AND(amd,d=DATE(2018,5,18)),13.26,"
    "IF(AND(msft,d=DATE(2010,11,8)),28.87,"
    "IF(AND(nvda,d=DATE(2025,5,22)),134.25,"
    "IF(au,IFS(d=DATE(2015,8,24),8.31,d=DATE(2019,8,19),21.1,d=DATE(2024,10,15),27.69,"
    "d=DATE(2025,5,22),43.29,TRUE,h),"
    "IF(meta,IFS(d=DATE(2015,8,24),82.09,d=DATE(2018,3,23),166.6,d=DATE(2019,6,27),198.88,"
    "d=DATE(2016,7,5),114.2,TRUE,h),h))))),"
    "lFix,IF(tsla,IFS(d=DATE(2025,5,22),331.39,d=DATE(2018,3,13),21.77,d=DATE(2018,5,18),18.27,"
    "d=DATE(2014,8,14),17.1,d=DATE(2016,12,12),12.75,TRUE,l),"
    "IF(AND(amd,d=DATE(2018,5,18)),12.91,"
    "IF(AND(nflx,d=DATE(2019,7,10)),36.268,"
    "IF(AND(nvda,d=DATE(2025,5,22)),131.55,"
    "IF(au,IFS(d=DATE(2019,8,19),19.65,d=DATE(2024,10,15),27.17,d=DATE(2025,5,22),42.17,TRUE,l),"
    "IF(meta,IFS(d=DATE(2014,8,19),74.51,d=DATE(2016,5,10),119,TRUE,l),l)))))),"
    "cFix,IF(tsla,IFS(d=DATE(2025,5,22),341.04,d=DATE(2018,5,18),18.45,TRUE,c),"
    "IF(AND(amd,d=DATE(2018,5,18)),13,"
    "IF(AND(nvda,d=DATE(2025,5,22)),132.83,"
    "IF(au,IFS(d=DATE(2024,10,15),27.55,d=DATE(2025,5,22),42.88,TRUE,c),"
    "IF(AND(meta,d=DATE(2016,7,5)),114.2,c))))),"
    "{oFix,hFix,lFix,cFix,v})"
)

doc = f"""# BRT OHLC override formula (Google Sheets)

Combined `LET` + `GOOGLEFINANCE` + ticker-gated overrides for **TSLA**, **AMD**, **MSFT**, **NFLX**, **NVDA**, **AU**, and **META**.

- Ticker in `C$1`, date in column `D` (formula assumes row 2 → `D2`).
- Spills **Open, High, Low, Close, Volume** across five columns.
- **Hard preference:** paste as **one single line** (linebreaks split into multiple cells).

When adding a new ticker's date fixes, **merge** into this formula — never replace existing ticker overrides with only the new ticker.

---

## Paste-ready formula (copy as one line)

```excel
{FORMULA}
```

---

## Overrides included

### TSLA

| Date | Fields |
|------|--------|
| 2025-05-22 | O/H/L/C |
| 2018-05-18 | O/H/L/C |
| 2018-03-13 | O/H/L |
| 2018-03-23 | H |
| 2021-03-01 | H |
| 2021-03-04 | H |
| 2014-08-14 | L |
| 2016-12-12 | L |

### AMD

| Date | Fields |
|------|--------|
| 2018-05-18 | O/H/L/C (13.06 / 13.26 / 12.91 / 13) |

### MSFT

| Date | Fields |
|------|--------|
| 2010-11-08 | H only (28.87) — sheet paste had 27.05; creates engine zone $28.87/$28.43/$29.31 |

### NFLX

| Date | Fields |
|------|--------|
| 2019-07-10 | L only (36.268) — was sheet 37.74; **confirmed applied** 2026-07-20 19:08 paste — zone 35.34/36.44 retest now **2019-07-10** (matches eng) |

### NVDA

| Date | Fields |
|------|--------|
| 2025-05-22 | O/H/L/C (132.23 / 134.25 / 131.55 / 132.83) — sheet duplicated 2025-05-21 bar onto 5/22 |

### AU

| Date | Fields |
|------|--------|
| 2015-08-24 | H only (8.31) — sheet had 8.93; drives sheet-only zone $8.93/$8.79/$9.07 vs eng $8.88/$8.74/$9.02 |
| 2019-08-19 | H/L (21.1 / 19.65) — sheet 20.73/19.98; fixes retest on BO 2019-08-14 |
| 2024-10-15 | O/H/L/C (27.29 / 27.69 / 27.17 / 27.55) — sheet wrong bar; BO date 10/16 vs eng 10/15 |
| 2025-05-22 | O/H/L/C (42.83 / 43.29 / 42.17 / 42.88) — same date-class drift as TSLA/NVDA |

### META

| Date | Fields |
|------|--------|
| 2016-05-10 | L only (119) — sheet had 114.8; **critical** — trigger_low stop = L×0.934; wrong L keeps trade open past 2016-06-24 gap (sheet +21% to 2017-04-25 vs eng GAP_DOWN then re-entry 2016-07-22) |
| 2014-08-19 | L only (74.51) — sheet 74.77 |
| 2015-08-24 | H only (82.09) — sheet 87.14 |
| 2016-07-05 | H/C (114.2 / 114.2) — sheet H 114.11 / C 114.0 |
| 2018-03-23 | H only (166.6) — sheet 167.1 |
| 2019-06-27 | H only (198.88) — sheet 189.95 |

Also: delete **599** `$0.0000` OHLC rows (2010-01-04 … 2012-05-17 pre-IPO placeholders). Do not override zeros.

---

## Adapt

1. Change `D2` → your date cell on that row.
2. Keep ticker as `C$1` (or update both the `GOOGLEFINANCE` ref and the ticker gates).
3. Fill down: date stays relative; leave `C$1` absolute.
4. See also `TSLA_ohlc_override_formula.md` for TSLA-only history / notes (`d,d+1` variant and optional early Highs).
"""

PATH.write_text(doc, encoding="utf-8")
body = PATH.read_text(encoding="utf-8")
start = body.index("```excel\n") + len("```excel\n")
end = body.index("\n```", start)
formula = body[start:end]
assert "\n" not in formula, "formula must be one line"
assert 'meta,UPPER(TRIM(C$1))="META"' in formula
assert 'tsla,UPPER(TRIM(C$1))="TSLA"' in formula
assert "au,UPPER" in formula
print(f"wrote {PATH} formula_len={len(formula)}")
