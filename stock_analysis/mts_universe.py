"""Official MTS backtest universe (MTS_Optimizer, generate_investment_report).

Keep in sync with the default MTS_SYMBOLS list in run_mts.bat (DailyRun / standalone launcher).
"""

MTS_SYMBOLS = [
    "AAON", "ABCB", "ABG", "ACA", "ACU", "ALG", "AMD", "AMN", "APP", "ARES",
    "ATEYY", "AU", "BBW", "BELFA", "BWLP", "CHCI", "CIEN", "CLS", "CMC", "COHR",
    "COKE", "CRS", "CRWD", "CSTM", "CVCO", "DDS", "DECK", "DKL", "DKS", "DXCM",
    "DY", "ENVA", "ESP", "EVR", "FEIM", "FN", "FRD", "FTAI", "HWKN", "IBP",
    "IESC", "IR", "JOE", "LMAT", "LOGI", "LRCX", "LUGDF", "LULU", "MATX", "MOD",
    "MPWR", "MTSI", "MTZ", "MYRG", "NEO", "NGL", "NVDA", "NVMI", "NXPI", "OR",
    "PFSI", "PLUS", "POOL", "POWL", "PTC", "QXO", "RMBS", "SANM", "SCCO", "SGI",
    "SHOP", "SIMO", "SKYW", "TATT", "TBBK", "TER", "TOELY", "TPH", "TRT", "TWLO",
    "UHS", "URI", "UTI", "VSEC", "WDAY", "WOR", "XPO",
]

MTS_SYMBOLS_CSV = ",".join(MTS_SYMBOLS)
