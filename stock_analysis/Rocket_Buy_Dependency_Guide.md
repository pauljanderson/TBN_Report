# Rocket Buy Dependency Guide

**Stale column letter:** On your current workbook, **Rocket Buy is column BI**, not BH. This file still says **BH** because it was written from an older layout; use **`SHEET_BI_DEPENDENCY_TREE.md`** for the BI / BC / BE / BW / BG formulas you are parity-testing against `rocket_brt.py`.

This document traces **Rocket buy** (historical column **BH** in this snapshot) and all columns it depends on, following every reference through to leaf inputs (raw OHLCV and constants).

---

## 1. Rocket Buy Formula

```
=AND($D2>=DATE(2019,1,1), $BV2=TRUE, OR($BB2=TRUE,$BB1=TRUE), $BD2=TRUE, $BF2=TRUE, OR($AJ2=TRUE,$AJ1=TRUE), OR($AP2=TRUE,$AP1=TRUE))
```

**Direct dependencies of Rocket buy (BH):**

| Column | Name | Also uses previous row |
|--------|------|------------------------|
| **D**  | Date | — |
| **BV** | Growth 3 Year | — |
| **BB** | Range Qualifier | ✓ BB1 |
| **BD** | Close above open | — |
| **BF** | Level Acceptance | — |
| **AJ** | Support test | ✓ AJ1 |
| **AP** | Zone Eligible Long | — |

---

## 2. Level-1 Dependencies (what each of those columns depends on)

### D (Date)
- **Leaf.** No further dependencies (raw data).

### BV (Growth 3 Year)
- **H** (Close), same row and row −756 (3-year lookback, ~252×3 trading days).
- **Leaf inputs:** H.

### BB (Range Qualifier)
- **F** (High), **G** (Low), row window, **C$7** (range threshold).
- **Leaf inputs:** F, G, C$7.

### BD (Close above open)
- **H** (Close) > **E** (Open).
- **Leaf inputs:** H, E.

### BF (Level Acceptance)
- **AJ** (Support test), **AL** (Support Evidence), **AO** (Break above Evidence), **W/X** (Zone Lower/Upper), **H** (Close), and long-window logic.
- So: **AJ, AL, AO, W, X, H** → trace **W, X, AL, AO** (AJ traced below).

### AJ (Support test)
- **AE** (Active Zone Lower), **AF** (Active Zone Upper), **H** (prior close), **G** (Low), **F** (High).
- **Maturity row:** Overlap for Support Test counts only from the **session after** zone maturity (not on the maturity bar where `touch_threshold` is reached).
- So: **AE, AF, H, G, F** → trace **AE, AF**.

### AP (Zone Eligible Long)
- **AE, AF** (Active Zone), **AL** (Support Evidence), **AM** (Resistance evidence), **AO** (Break above Evidence).
- So: **AE, AF, AL, AM, AO** → trace **AL, AM, AO**.

---

## 3. Level-2 Dependencies

### W, X (Zone Lower, Zone Upper)
- **V** (Touch Price), **C$5** (band %).
- **W** = V × (1 − C$5), **X** = V × (1 + C$5) (or equivalent).
- Trace **V**.

### AE, AF (Active Zone Lower / Upper)
- **AG** (Active Zone ID), **Y–AD** (Zone 1–3 Lower/Upper).
- **AG** = which zone the bar is in, from **W, X** and **Y–AD**.
- **Y–AD** (Zone 1–3 Lower/Upper) come from **V** and **C$5** (same band logic as W/X, per zone).
- So: **AG, Y, Z, AA, AB, AC, AD** → all ultimately from **V** and **C$5**.

### AL (Support Evidence)
- **AJ** (Support test), **AK** (Resistance test), **AG**, **V**, **AJ** in window (COUNTIFS).
- **Leaf-like:** AJ, AK, AG, V (AG and V traced above).

### AM (Resistance evidence)
- **AJ, AK, AG**, window counts.
- **Leaf-like:** AJ, AK, AG.

### AO (Break above Evidence)
- **AE, AF, H**, MAX(H) in window.
- **Leaf-like:** AE, AF, H.

---

## 4. Level-3: Touch Price and Pivots

### V (Touch Price)
- **J** (Pivot Highs), **K** (Pivot Lows), **F** (High), **G** (Low), **L** (Pivot High Price), **M** (Pivot low price).
- Optional strength / major pivot: **T** (Major Pivot High), **U** (Major Pivot Low).
- **Leaf-like:** J, K, F, G, L, M (and T, U if used).

### T (Major Pivot High), U (Major Pivot Low)
- Built from **J, K, L, M** and strength rules (often with look-ahead in full form).
- **Leaf-like:** J, K, L, M.

### J (Pivot Highs), K (Pivot Lows)
- **F** (High), **G** (Low), lookback window.
- **Leaf:** F, G.

### L (Pivot High Price), M (Pivot low price)
- **F, G** at pivot bars (from J/K).
- **Leaf:** F, G.

### N (Last Pivot High), O (Last Pivot Low)
- **J, K, L, M** (prior pivot state).
- **Leaf:** J, K, L, M → F, G.

---

## 5. Leaf Inputs (no further dependencies)

| Column / ref | Description |
|--------------|-------------|
| **D** | Date |
| **E** | Open |
| **F** | High |
| **G** | Low |
| **H** | Close |
| **I** | Volume (only if used elsewhere; not in Rocket buy path above) |
| **C$3** | Target % |
| **C$4** | Stop % (used downstream) |
| **C$5** | Zone band % |
| **C$7** | Range qualifier threshold |

---

## 6. Dependency Tree (Rocket buy → leaves)

```
Rocket buy (BH)
├── D (Date) ...................................................... [LEAF]
├── BV (Growth 3 Year)
│   └── H (Close) ............................................... [LEAF]
├── BB (Range Qualifier), BB1
│   └── F, G, C$7 .............................................. [LEAF]
├── BD (Close above open)
│   └── H, E .................................................... [LEAF]
├── BF (Level Acceptance)
│   └── AJ, AL, AO, W, X, H
│       └── W,X from V, C$5
│           └── V (Touch Price) → J,K,F,G,L,M (T,U) → F,G ....... [LEAF]
│       └── AL → AJ,AK,AG,V ..................................... (traced)
│       └── AO → AE,AF,H
│       └── H ................................................... [LEAF]
├── AJ (Support test), AJ1
│   └── AE, AF, H, G, F
│       └── AE,AF from AG, Y–AD → V, C$5 ........................ [LEAF: C$5]
│       └── H, G, F ............................................. [LEAF]
└── AP (Zone Eligible Long)
    └── AE, AF, AL, AM, AO
        └── AE,AF (as above)
        └── AL → AJ,AK,AG,V ..................................... (traced)
        └── AM → AJ,AK,AG
        └── AO → AE,AF,H

Touch & zone chain:
  V → W, X; Y–AD → AG → AE, AF
  J,K → F,G
  L,M → F,G
  T,U → J,K,L,M
```

---

## 7. Summary: Columns in dependency order (leaves → Rocket buy)

**Raw / constants:** D, E, F, G, H, I, C$3, C$5, C$7  

**Pivots:** J, K → L, M, N, O (from F, G)  

**Touch & zones:** F, G, J, K, L, M (→ T, U if used) → V → W, X; Y–AD → AG → AE, AF  

**Tests & evidence:** F, G, H, AE, AF → AJ, AK; AE, AF, H → AO; AJ, AK, AG, V → AL; AM; AL, AM, AO → AP  

**Rocket buy inputs:** F, G, C$7 → BB (Range Qualifier); H, E → BD (Close above open); V, C$5, zone/evidence → BF (Level Acceptance); H → BV (Growth 3 Year).  

**Rocket buy (BH):** D, BV, BB, BD, BF, AJ, AP (with BB1, AJ1).

---

## 8. Downstream of Rocket buy (what uses Rocket buy)

- **BK (In trade)** – TRUE when entered by Rocket buy (BH) and not yet exited; depends on BH and exit logic (e.g. exit hit today, Stop, Target).
- **BC (Target)** – depends on BK (In trade), exit hit today, E3, C$3 (and possibly BH).
- **BJ (Stop)** – entry/stop logic gated by being in a trade (BK).
- **Exit hit today** – uses Stop, Target, H, E; feeds BC and BK.
- **BM (Risk Reward), BN (Exit type), BO (Exit price), BP (Entry Price Active), BQ (Entry Date Active), BR (Peak High), BS (Current Drawdown), BT (Max Drawdown)** – all depend on being in a trade (BK), hence on Rocket buy (BH) and exit logic.

So the full chain is: **Leaf columns (D,E,F,G,H + constants) → Pivots/Zones/Evidence → BB, BD, BF, AJ, AP, BV → Rocket buy (BH) → BK (In trade), BC (Target), Stop, exit hit, Risk Reward, Exit type, Exit price, Entry price/date, Peak High, Drawdowns.**

This is the full dependency guide from Rocket buy back to all supporting columns and forward to the main trade and drawdown outputs.
