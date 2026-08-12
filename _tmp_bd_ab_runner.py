"""Fill in the missing 2x2 cells: sell_breakdown x min_spy_compare_1y_at_trigger."""
import os, subprocess, sys, time

SYMS = ("CTAS,CASY,CW,BSX,FISV,HWM,PRI,CPRT,DHR,UNH,BRO,MCK,V,POOL,BR,TDY,TMO,AER,ORLY,ADBE,DECK,LOGI,"
        "PGR,CRZBY,QQQ,LII,ICE,ROL,COST,RBC,CHTR,GME,MSCI,WST,ESE,AZO,AXSM,FINMY,MCO,DG,CDW,EA,FIVN,FICO,"
        "ENSG,SPGI,MSI,AON,PFSI,BFC,CSGP,RCL,EME,GE,CRS,PH,WAB,IBKR,ZBRA,,CBOE,NFLX,NVDA,MSFT,SNPS,"
        "GMAB,GPN,FTI,INTU,JKHY,GNRC,ALGN,BWXT,BDGIF,META,STE,MA,IPAR,LOPE,NMIH,MYRG,PWR,DSGX,POWL,RNMBY,"
        "BLX,BIO,GOOG,WDC,NXST,TMUS,ABCB,MTD,PAYC,XPO,MLI,FIX,EPAM,FUNC,IDXX,AAPL,APP,AMZN")

BASE = ['rs_mode=true', 'brt_zones=false', 'yh_zones=false', 'wpbr_zones=false', 'rl_mode=false',
        'target_pct=1.25', 'stop_pct=0.88', 'stop_pct_is_multiplier=true', 'use_indicators=true',
        'indicator_buy=off', 'rs_require_tc_strong=true', 'growth_filter_enabled=false', 'atr_days=0',
        'too_high_multiplier=0', 'rs_max_pct_below_52w_high=0', 'rs_spy_int_tc_not_weak=false']

ARMS = [
    ('plus_spy40', ['sell_breakdown=breakdown_plus', 'min_spy_compare_1y_at_trigger=40']),
    ('only_spy0', ['sell_breakdown=breakdown_only', 'min_spy_compare_1y_at_trigger=0']),
]

for name, extra in ARMS:
    outdir = os.path.join('drive', 'paul_experiments', 'rs_sell_breakdown_ab', name)
    os.makedirs(outdir, exist_ok=True)
    cmd = [sys.executable, os.path.join('stock_analysis', 'rocket_brt.py'), os.path.join('data', 'newdata', 'data'),
           '-o', outdir, '-w', '8', '--no-regression', '--aggressive', '--relative-strength']
    for v in BASE + extra:
        cmd += ['-v', v]
    cmd += ['-s', SYMS]
    t0 = time.time()
    print(f'=== ARM {name} ===', flush=True)
    with open(os.path.join(outdir, 'run.log'), 'w', encoding='utf-8', errors='replace') as lg:
        rc = subprocess.call(cmd, stdout=lg, stderr=subprocess.STDOUT)
    print(f'    exit={rc} {time.time()-t0:.0f}s', flush=True)
print('ALL_ARMS_DONE', flush=True)
