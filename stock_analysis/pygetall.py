import yfinance as yf
import os
from datetime import datetime

# --- CONFIGURATION ---
DATA_DIR = "data"
# Start date set to Jan 23, 2019
START_DATE = "2019-01-23"

# End date is today (automatically includes the most recent close)
from datetime import datetime, timedelta
END_DATE = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

# Replace this list with your full set of tickers
# Based on your directory, I've initialized the first few:
TICKERS = [

    "ABCB", "ABNB", "ABT", "ACAD", "ACM", "ACU", "ADBE", "ADMA", "ADP", 

    "ADPT", "AEIS", "AEM", "AEO", "AFL", "AGM", "AGX", "AIT", "AIZ", 

    "ALG", "ALL", "ALSN", "AMKR", "AMZN", "AMRZ", "AON", "APA", "APH", "ARES", 

    "ASM", "ASML", "ATEN", "ATLC", "AU", "AUGO", "AXP", "B", "BAC", 

    "BANC", "BANF", "BFC", "BK", "BKTI", "BLBD", "BLK", "BLX", "BMRN", 

    "BN", "BPOP", "BSX", "BX", "BYD", "C", "CASH", "CASY", "CBRE", "CCBG", 

    "CCCX", "CDNS", "CGC", "CHCI", "CINF", "CLS", "CMC", "CMCL", "CME", "CNC", "CNM", "CNO", 

    "COF", "COHR", "COKE", "COR", "CPA", "CRM", "CRS", "CSCO", "CTAS", "CVCO", 

    "CVX", "CW", "CWCO", "CWK", "DAL", "DDS", "DGII", "DHT", "DIS", 

    "DOCN", "DRD", "DRI", "DRS", "DSGX", "DXC", "DY", "EAT", "EHC", 

    "EME", "ENSG", "ESE", "ESOA", "ETR", "EVR", "EXC", "EXEL", "EXLS", 

    "EXTR", "F", "FBP", "FCFS", "FERG", "FIX", "FLEX", "FN", "FNF", "FOXA", "FRBA", 

    "FRD", "FSI", "FUNC", "GD", "GFI", "GHM", "GLW", "GM", "GOOGL", 

    "GRAL", "GTX", "GVA", "GWW", "HALO", "HBAN", "HBM", "HCI", "HD", "HIG", 

    "HLI", "HLT", "HMY", "HTHIY", "HUBB", "HWBK", "HWKN", "IBKR", "ICE", 

    "IDCC", "IDR", "IESC", "IIIN", "IMVT", "INCY", "INFY", "INOD", "INTC", 

    "INTU", "IPAR", "IQV", "ITIC", "ITRN", "ITT", "IVZ", "JCI", "JMIA", "JNJ", 

    "JOE", "KGC", "KINS", "KLAC", "KO", "LDOS", "LH", "LII", "LITE", 

    "LMAT", "LMB", "LMND", "LOPE", "LRCX", "LYV", "MA", "MAT", 

    "MATX", "MC", "MCD", "MCO", "MCRI", "MDT", "MELI", "META", "MFC", 

    "MGA", "MGIC", "MLI", "MMC", "MMM", "MRVL", "MS", "MSFT", "MTG", 

    "MTSI", "MTZ", "MU", "MWA", "MYRG", "NDAQ", "NEM", "NFLX", "NG", 

    "NGD", "NGVC", "NKE", "NMIH", "NNI", "NOW", "NRG", "NTRA", "NUE", "NVDA", 

    "NVMI", "NXT", "ODC", "OFG", "ORCL", "ORI", "PAAS", "PAG", "PCVX", 

    "PDEX", "PEP", "PFE", "PFS", "PH", "PIPR", "PLPC", "PLUS", "PNFP", 

    "PNRG", "PPIH", "PRI", "PRIM", "PWR", "PYPL", "RBCAA", "RCL", "RCMT", 

    "RDNT", "REAL", "RELX", "RF", "RGC", "RGS", "RJF", "RMBS", "RUSHB", 

    "RYAAY", "SANM", "SAR", "SBH", "SBS", "SBUX", "SCHW", "SENEA", "SII", 

    "SKYW", "SLF", "SMID", "SNA", "SNDX", "SNFCA", "SNX", "SO", "SONY", 

    "SPRY", "SPY", "SRCE", "SRPT", "STN", "STRL", "STT", "SUPN", 

    "SYF", "T", "TAP", "TFC", "TGB", "TGLS", "TGT", "THG", "TIMB", "TIPT", 

    "TKO", "TLRY", "TMUS", "TOWN", "TPC", "TRT", "TRV", "TSLA", "TSM", "TSSI", "TT", 

    "TTMI", "TYL", "UAL", "UNH", "UNM", "UPS", "UTHR", "UTI", "VIK", 

    "VIRT", "VLY", "VMI", "VRDN", "VZ", "WBS", "WLDN", "WM", "WOLF", 

    "WOR", "WRB", "WRLD", "WTFC", "WTS", "XPEL", "XPO", "YUM", "ZETA", "ZM", "ZWS"

]
def main():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

    print(f"Downloading data for {len(TICKERS)} symbols from {START_DATE} to {END_DATE}...")

    # Single batch call for all tickers
    data = yf.download(TICKERS, start=START_DATE, end=END_DATE, group_by='ticker', threads=True, multi_level_index=False, auto_adjust=False)
    

    for ticker in TICKERS:
        try:
            df = data[ticker].dropna()
            if df.empty:
                continue
                
            output_file = os.path.join(DATA_DIR, f"{ticker}.csv")
            # Force columns: Date, Open, High, Low, Close, Adj Close, Volume
            df.to_csv(output_file)
            
        except Exception:
            print(f"Skipped: {ticker}")

    print("Update Complete.")

if __name__ == "__main__":
    main()