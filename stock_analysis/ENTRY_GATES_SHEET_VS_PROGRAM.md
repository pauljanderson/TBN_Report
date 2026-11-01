# Side-by-side: sheet columns vs `rocket_brt.py` entry logic

Letters use **`sheet_column_reference.py`** (`SHEET_HEADERS`, Date in **D**). The live workbook is the **compact** layout (**D** through **CD**): the old Zone 1–10 ladder block is **gone**, so several letters (**DI** / **DO** / **DW**, etc.) from older notes no longer apply—use the module, not memory.

**Not** operands of **AL** (*BRT Rocket buy*):

| Column | Header | Role |
|--------|--------|------|
| **AI** | *Range Qualifier* | **Not** in **AL** `AND` |
| **BC** | *ATH filter* | **Not** in **AL** `AND` |

So **`tight_range_enabled`** in Python is **not** “sheet column **AI** parity” for the buy row; it is an extra program filter on the maturity window.

---

## 1. Sheet buy (**AL**) vs program

**Exact formula on your compact sheet:**

```text
=AND($AK2=TRUE,$AZ2=TRUE,COUNTIF($BY:$BY,$D2)>0)
```

| Operand | Column | Header | Meaning |
|---------|--------|--------|---------|
| `$AK2=TRUE` | **AK** | *Close above open* | Bullish bar |
| `$AZ2=TRUE` | **AZ** | *Growth 3 Year* | 3Y growth cell TRUE (see sheet’s own *AX*/*AY*/*AZ* / *BA* stack) |
| `COUNTIF($BY:$BY,$D2)>0` | **D** + **BY** | *Date* + *Retest Date* | Row date appears in the **BY** retest list |

**Program:** there is no single `AL` variable. After a **pending** touch matures, `rocket_brt.py` runs a **stack** of checks (TTL, candle, zone logic, growth, optional filters, simulated **BY**-style retest set, etc.), then can enter on the **next** bar. That stack is often **stricter** and **not 1:1** with the three-term **AL** unless you disable most gates and align growth/retest logic by hand.

**Rough analogues:** **AK** → `close > open` on `_eval_bar`; **AZ** → `growth_filter_enabled` + `growth_bars` (often 756); **BY** list → `sheet_dw_countif_entry_enabled` + internal `dw_dates_set` (name still says “DW” in code).

---

## 2. Quick letter map (compact sheet)

Unchanged from older layouts for these:

| Col | Header |
|-----|--------|
| **AG** / **AH** | *Zone Lower (touch band)* / *Zone Upper (touch band)* |
| **AI** | *Range Qualifier* |
| **AK** / **AL** | *Close above open* / *BRT Rocket buy* |
| **AQ** | *Exit type* — **not** the internal “AQ gate” / zone-eligible name in Python |
| **AX** … **AZ** | *Growth 1 / 2 / 3 Year* |
| **BB** | *Growth OK* |
| **BC** | *ATH filter* |
| **BG** … **BI** | *Matured touch price* / *Matured Zone lower* / *Matured zone upper* |

**Moved** after removing the ladder columns (old letters in parentheses):

| Col | Header |
|-----|--------|
| **BM** | *NEW FORMULA to check ALL zones* (was **DI**) |
| **BR** | *Breakout Date* (was **DO**) |
| **BY** | *Retest Date* (was **DW**) |
| **CB** | *BRT Summary* (not Python `consolidation_blocker_enabled`; that name predates this layout) |

Internal Python helpers still talk about **AQ**/**AK** “gates” (support/zone-eligible semantics)—those are **not** “sheet column **AQ** / **AK**” except that real **AK** is the bullish candle, which the program matches in spirit.

---

## 3. Program gates (pending loop) vs what **AL** alone checks

The sheet **AL** column only encodes **three** predicates (§1). The program may also enforce the following when the relevant flags are on:

| `rocket_brt.py` idea | Sheet analogue | Notes |
|----------------------|----------------|-------|
| Row-local / TTL (`entry_eval_mode`, `sheet_magic_touch`, `pending_max_bars`) | Touch / timing | **Not** in **AL** |
| Bullish candle | **AK** | Program uses OHLC; does not read **AK** |
| `entry_close_min_range_position` | Optional bar-position idea | **Not** in **AL** |
| `growth_filter_enabled` / `growth_bars` | **AZ** / **BB** area | Sheet uses high-water *AX*/*AY*/*AZ*/*BA*; Python uses close vs close *N* bars back—parity not automatic. **Missing lookback Close:** engine **FAIL**s (need a real `Close[eval−N]`; no $0 coerce). Sheet grids that pad pre-IPO OHLC as **$0** can still show AZ TRUE — intentional economics-over-parity divergence (2026-08-22). |
| `tight_range_enabled` | Not **AI** | Extra program-only filter |
| Zone-eligible / “DI” logic | **BM** + **BH:BI** history | When `sheet_di_gate_enabled` is on; **not** in **AL** |
| (removed) `sheet_active_zone_gates` + DE/DF/DG ladder prefetch | — | **Deleted from `rocket_brt.py`** — compact sheet has no Zone 1–10 ladder columns |
| `level_acceptance_*` | “BG” in **comments** | **BG** on the sheet is *Matured touch price*, not “acceptance 7/10” |
| `do_gate_enabled` / `dp_gate_enabled` | naming only vs **BR** / DP | Optional program gates |
| `sheet_dw_countif_entry_enabled` | **BY** retest set | Closest match to `COUNTIF($BY:$BY,$D2)` when enabled |
| `consolidation_blocker_enabled` | **Not** *BRT Summary* (**CB**) | Different meaning |
| `displacement_filter_enabled` | *rolling displacement* | Optional |

---

## 4. Extra numeric gates in `rocket_brt.py` (pending loop + RS path)

When set off their no-op defaults, the main pending entry loop and **relative-strength** entry path apply:

- `min_pivot_run_l_before_entry` / `min_pivot_run_h_before_entry` / `pivot_switch_h_to_l_filter`
- `min_hist_ann_ror_avg` (vs prior closed trades for that symbol in the current run)
- `min_rel_vol_at_entry` / `min_avg_volume_10d_at_entry`
- `min_atr_pct_at_entry` / `max_atr_pct_at_entry` (on **ATR_PCT_AT_ENTRY** = ATR14/entry×100)

**Market cap:** `min_market_cap` and **`max_market_cap`** filter closed/open **after** yfinance enrichment when either is **>0** (`0` = no op). Missing `market_cap` is **kept** (unknown is neither under-min nor over-max); only trades with a known cap outside the bound are dropped. Production **BRT / YH / WPBR** bats pass **`max_market_cap=0` / `min_market_cap=0`** so the engine default huge max bound cannot wipe Closed (same class of bug as AMD wipe).

For the legacy **OG** / **MTS** engines, see `rocket_brt_og.py` / `rocket_MTS.py` and `entry_filter_*` tri-state fields.

---

## 5. Stale snapshot warning: `SHEET_BI_DEPENDENCY_TREE.md`

That file may still describe an older grid (**BI** as buy, wide ladder, etc.). Prefer **`sheet_column_reference.py`** + this file for letters and formulas.
