# WPBR Improve Hints — stamp `261002145352`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `small_target_wins` (1087 sym / 14200 trades)
- **Lever:** target_pct / expansion / partial_exit
- **Suggestion:** Many small TARGET wins — consider higher target or partial scale-out.
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACGL

## 2. `post_target_quick_stop` (1036 sym / 4417 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACGL
- **Evidence:** AAMI TARGET 2020-12-31 -> STOP 2021-01-27 (2d); AAMI TARGET 2026-01-22 -> STOP 2026-02-05 (0d); ABBV TARGET 2016-06-13 -> STOP 2016-06-17 (0d); ABBV TARGET 2020-06-30 -> STOP 2020-07-14 (0d); ABBV TARGET 2021-06-07 -> STOP 2021-08-10 (6d)

## 3. `false_start_2022_2023` (754 sym / 1397 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** A, AA, AAON, AAPL, AAT, ABBNY, ABG, ABM, ABR, ABT, ACA, ACAD, ACGL, ACLS, ACN, ACRS, ACU, ADBE, ADI, ADMA
- **Evidence:** AA 2022 STOP 11d -5.0%; ABBNY 2022 STOP 0d -0.4%; AAON 2022 STOP 4d -3.7%; ABR 2022 STOP 0d -2.5%; ABM 2022 STOP 0d -2.8%

## 4. `slow_target_grind` (581 sym / 1018 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** A, AAL, AAON, AAPL, AAT, ABG, ABR, ABT, ACGL, ACM, ACN, ACU, ADBE, ADI, ADNT, ADP, ADPT, AEE, AEIS, AEP
- **Evidence:** AAON TARGET 147d +20.0% (~0.14%/d) 2011-07-21; AAON TARGET 152d +8.1% (~0.05%/d) 2016-10-05; ABR TARGET 178d +25.1% (~0.14%/d) 2011-02-07; AAT TARGET 239d +20.0% (~0.08%/d) 2013-01-02; ABT TARGET 210d +20.0% (~0.10%/d) 2015-05-18

## 5. `fat_stops` (474 sym / 750 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AAL, AAMI, ABBNY, ABBV, ABG, ABR, ABUS, ACAD, ACLS, ACRS, ACU, ADMA, ADPT, ADSK, AEG, AEHR, AES, AFRM, AGI, AGM

## 6. `early_run_long_tail` (233 sym / 265 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** ACLS, ACU, ADI, ADNT, ADPT, AEIS, AGX, AGYS, AIT, ALB, ALLE, ALSN, AMAT, AMGN, AMN, AMTX, ANIP, AON, APG, APH
- **Evidence:** ACLS +10% by day 24 then held 93d exit +35.3% (GAP_UP); ADNT +10% by day 11 then held 92d exit +23.0% (TARGET); ADPT +10% by day 4 then held 148d exit +49.1% (TARGET); ACU +10% by day 8 then held 217d exit +20.4% (TARGET); ADI +10% by day 12 then held 194d exit +14.2% (TARGET)

## 7. `winner_peak_giveback` (58 sym / 63 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** ACRS, AER, AMTX, ANF, ANGO, APP, APPS, ARGX, ASM, BBIO, BKTI, CASH, CELH, CHCI, CLF, CLS, CORT, CXDO, DOCU, EGO
- **Evidence:** ACRS peak~75% -> exit +41.7% (giveback~33pp, 33d, TARGET); AER peak~32% -> exit +20.0% (giveback~12pp, 99d, TARGET); AMTX peak~90% -> exit +35.1% (giveback~55pp, 70d, TARGET); ANGO peak~20% -> exit +9.3% (giveback~11pp, 15d, TARGET); ANF peak~93% -> exit +68.1% (giveback~25pp, 532d, TARGET)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (41 sym / 9021 trades) — direction: expand, confidence: medium, 50.8% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (9021 trades, 51%, high) vs target_contract_approach_fail → contract (3558 trades, 10%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 9021/17771 TARGET exits (51%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 3558/34621 trades (10%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACGL
- **Evidence:** [A expand] AAMI +10% in 15d after TARGET; AAMI +5% in 15d after TARGET; AAMI +9% in 15d after TARGET; AAMI +7% in 15d after TARGET; ABBV +6% in 15d after TARGET; ABBV +6% in 15d after TARGET | [B contract] AAMI reached 76% of target then STOP; AAMI reached 62% of target then STOP; ABBV reached 78% of target then STOP; AA reached 70% of target then STOP; AA reached 80% of target then STOP; AA reached 51% of target then STOP

## 2. `stop_pct_tension_expand_vs_hold` (40 sym / 7979 trades) — direction: mixed, confidence: medium, 63.7% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (no clear lean — pick one A/B arm or segment trades): stop_expand_post_stop_rebound → expand (7666 trades, 61%, high) vs stop_ok_never_worked → hold (7979 trades, 64%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 7666/12531 STOP exits (61%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 7979/12531 STOPs (64%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACGL
- **Evidence:** [A expand] AAMI STOP 2018-02-14 then back above entry/15d; AAMI STOP 2019-03-15 then back above entry/15d; AAMI STOP 2020-07-14 then back above entry/15d; AAMI STOP 2020-12-14 then back above entry/15d; AAMI STOP 2026-02-05 then back above entry/15d; ABBV STOP 2016-06-17 then back above entry/15d | [B hold] AAMI MFE~1.5% STOP; AAMI MFE~0.0% STOP; AAMI MFE~1.0% STOP; AAMI MFE~0.0% STOP; AAMI MFE~0.4% STOP; AAMI MFE~1.3% STOP

## 3. `band_tighten_weak_fill` (1085 sym / 8470 trades) — direction: tighten, confidence: high, 24.5% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 8470/34621 trades (24%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACGL
- **Evidence:** AAMI MFE~1.5% STOP 1d; AAMI MFE~2.7% STOP 0d; AAMI MFE~0.0% STOP 14d; AAMI MFE~1.0% STOP 3d; AAMI MFE~0.0% STOP 1d; AAMI MFE~0.4% STOP 3d

## 4. `target_contract_slow_hold` (581 sym / 1018 trades) — direction: contract, confidence: low, 5.7% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 1018/17771 TARGET exits (6%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** A, AAL, AAON, AAPL, AAT, ABG, ABR, ABT, ACGL, ACM, ACN, ACU, ADBE, ADI, ADNT, ADP, ADPT, AEE, AEIS, AEP
- **Evidence:** AAON TARGET 147d +20.0% (~0.14%/d); AAON TARGET 152d +8.1% (~0.05%/d); ABR TARGET 178d +25.1% (~0.14%/d); AAT TARGET 239d +20.0% (~0.08%/d); ABT TARGET 210d +20.0% (~0.10%/d); ABT TARGET 317d +20.0% (~0.06%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
