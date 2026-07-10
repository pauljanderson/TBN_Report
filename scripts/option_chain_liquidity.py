#!/usr/bin/env python3
"""
Standalone: yfinance option-chain liquidity snapshot (spread, volume, open interest).

Uses the earliest listed expiration whose **calendar** days to expiry are at least
``--min-days-to-expiry`` (default 45). If Yahoo lists nothing that far out, uses the
farthest expiration and records that in ``note``. Strikes are then filtered to a band
around the underlying last close (``--band``).

Spread % is computed on rows whose option mid (bid/ask average) is at least $0.02 so
deep OTM penny quotes do not dominate. ``pct_wide_spread`` is the share of those rows
with spread as a fraction of mid above 5% (see ``WIDE_SPREAD_PCT`` in code).

Summary includes ``min_spread_pct`` (minimum over the same priced rows). A second table lists
every contract tied at that minimum (same expiration as the summary), with strike, C/P,
volume, open interest, bid/ask, spread, **yahoo_in_the_money** (Yahoo's ITM flag), and
**moneyness** (ITM / ATM / OTM from spot vs strike; ATM = within ``ATM_BAND_REL`` of spot,
see constant in code).

**Delta:** Yahoo does not ship delta in the chain payload. The detail table includes
``delta_bs`` — a **Black–Scholes European** delta from spot, strike, calendar time to the
chosen expiry, chain ``impliedVolatility`` (clamped for stability), a fixed risk-free rate
(``RISK_FREE_BS``), and dividend yield from ``ticker.info`` when available (else 0).
This is an **approximation** (American options, corporate actions, bad IV on illiquid lines).

Yahoo Finance data can be delayed or incomplete; treat as indicative, not a live trading feed.

Dependencies: pip install yfinance pandas

Example:
  python scripts/option_chain_liquidity.py
  python scripts/option_chain_liquidity.py --symbols MSFT,AAPL --band 0.12 --min-days-to-expiry 45

With ``--csv out.csv`` the script also writes ``out_tightest_spread.csv`` and ``out_band.csv``
(contract-level columns including moneyness and ``yahoo_in_the_money``), using the same column
order as the console tables.

**Yahoo rate limits:** unauthenticated yfinance traffic is throttled. Use a smaller ``-s`` list,
``--delay-between-symbols 0.5`` (or 1–2s) for hundreds of tickers, and/or ``--yahoo-retries`` /
``--yahoo-base-wait`` if you still see ``YFRateLimitError``. There is no official quota; spacing
runs by several minutes is safer than hammering the API back-to-back.
"""

from __future__ import annotations

import argparse
import math
import random
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except ImportError as e:  # pragma: no cover
    print("Install yfinance: pip install yfinance", file=sys.stderr)
    raise SystemExit(2) from e


def _yahoo_transient(exc: BaseException) -> bool:
    """True for rate limits and common transient network failures worth retrying."""
    n = type(exc).__name__
    if n in (
        "YFRateLimitError",
        "ConnectionError",
        "TimeoutError",
        "ReadTimeoutError",
        "ChunkedEncodingError",
    ):
        return True
    s = str(exc).lower()
    return "rate limit" in s or "too many requests" in s or "temporarily unavailable" in s


def _yahoo_call(fn: Callable[[], Any], max_retries: int, base_wait_sec: float) -> Any:
    """Run ``fn`` with retries and exponential backoff + jitter on transient Yahoo errors."""
    mr = max(1, int(max_retries))
    last: BaseException | None = None
    for attempt in range(mr):
        try:
            return fn()
        except BaseException as e:
            last = e
            if not _yahoo_transient(e):
                raise
            if attempt >= mr - 1:
                raise
            delay = float(base_wait_sec) * (2**attempt) * (0.5 + random.random())
            time.sleep(delay)
    raise last if last is not None else RuntimeError("yahoo_call exhausted")


# Default watchlist (edit or pass --symbols).
DEFAULT_SYMBOLS = [
    "A",
    "AA",
    "AAL",
    "AAMI",
    "AAON",
    "AAP",
    "AAT",
    "ABBNY",
    "ABBV",
    "ABCB",
    "ABG",
    "ABM",
    "ABNB",
    "ABR",
    "ABT",
    "ABUS",
    "ACA",
    "ACAD",
    "ACLS",
    "ACM",
    "ACN",
    "ACRS",
    "ACU",
    "ADBE",
    "ADI",
    "ADMA",
    "ADM",
    "ADNT",
    "ADP",
    "ADPT",
    "ADSK",
    "AEG",
    "AEHR",
    "AEIS",
    "AEM",
    "AEO",
    "AER",
    "AFG",
    "AFL",
    "AGI",
    "AGM",
    "AGNC",
    "AGO",
    "AGX",
    "AGYS",
    "AHCO",
    "AHH",
    "AHT",
    "AI",
    "AIG",
    "AIR",
    "AIT",
    "AIZ",
    "AJG",
    "AKAM",
    "AKR",
    "AKTS",
    "AL",
    "ALB",
    "ALBY",
    "ALDX",
    "ALEC",
    "ALEX",
    "ALFVY",
    "ALG",
    "ALGM",
    "ALGN",
    "ALL",
    "ALLE",
    "ALNY",
    "ALNT",
    "ALSN",
    "AMAT",
    "AMCR",
    "AMD",
    "AME",
    "AMG",
    "AMGN",
    "AMH",
    "AMKR",
    "AMN",
    "AMP",
    "AMRC",
    "AMRZ",
    "AMT",
    "AMTX",
    "AMWD",
    "AMWL",
    "AMZN",
    "AN",
    "ANAB",
    "ANDE",
    "ANET",
    "ANF",
    "ANGO",
    "ANIK",
    "ANIP",
    "ANNX",
    "AON",
    "AOS",
    "AOSL",
    "AOUT",
    "APA",
    "APAM",
    "APD",
    "APG",
    "APH",
    "APLD",
    "APPS",
    "APTV",
    "APYX",
    "ARE",
    "ARES",
    "ARW",
    "ASH",
    "ASM",
    "ASMIY",
    "ASML",
    "ATEN",
    "ATEYY",
    "ATGE",
    "ATI",
    "ATLC",
    "ATO",
    "ATR",
    "ATUSF",
    "AU",
    "AUGO",
    "AVA",
    "AVAV",
    "AVGO",
    "AVY",
    "AWK",
    "AWI",
    "AX",
    "AXP",
    "AXSM",
    "AYI",
    "AZO",
    "B",
    "BA",
    "BAC",
    "BAESY",
    "BALL",
    "BANC",
    "BANF",
    "BAP",
    "BAX",
    "BBIO",
    "BBVA",
    "BBW",
    "BC",
    "BCH",
    "BDGIF",
    "BDX",
    "BELFA",
    "BELFB",
    "BEN",
    "BEP",
    "BFC",
    "BIIB",
    "BIO",
    "BK",
    "BKHYY",
    "BKNG",
    "BKR",
    "BKTI",
    "BKV",
    "BLBD",
    "BLD",
    "BLHK",
    "BLK",
    "BLX",
    "BMRN",
    "BMY",
    "BN",
    "BPOP",
    "BR",
    "BRO",
    "BSX",
    "BURL",
    "BVN",
    "BWA",
    "BWLP",
    "BWXT",
    "BX",
    "BXMT",
    "BXP",
    "BYD",
    "C",
    "CACI",
    "CAMT",
    "CASH",
    "CASY",
    "CAT",
    "CBRE",
    "CBOE",
    "CCBG",
    "CCJ",
    "CDE",
    "CDNS",
    "CDW",
    "CE",
    "CECO",
    "CELH",
    "CENX",
    "CF",
    "CFG",
    "CGC",
    "CHCI",
    "CHDN",
    "CHEF",
    "CHRW",
    "CHTR",
    "CHYM",
    "CI",
    "CIB",
    "CIEN",
    "CINF",
    "CL",
    "CLF",
    "CLS",
    "CLX",
    "CM",
    "CMC",
    "CMCL",
    "CME",
    "CMG",
    "CMI",
    "CMS",
    "CNC",
    "CNM",
    "CNO",
    "CNP",
    "CNQ",
    "CNQ",
    "CNX",
    "COF",
    "COHR",
    "COKE",
    "COO",
    "COP",
    "COR",
    "CPA",
    "CPB",
    "CPRT",
    "CPT",
    "CRH",
    "CRL",
    "CRM",
    "CRS",
    "CRUS",
    "CRZBY",
    "CSCO",
    "CSGP",
    "CSTM",
    "CSX",
    "CTAS",
    "CTRE",
    "CTS",
    "CTSH",
    "CTVA",
    "CVCO",
    "CVX",
    "CW",
    "CWCO",
    "CWK",
    "CYD",
    "CYTK",
    "CZR",
    "D",
    "DAL",
    "DBSDY",
    "DCO",
    "DD",
    "DDS",
    "DE",
    "DECK",
    "DG",
    "DGII",
    "DHI",
    "DHR",
    "DHT",
    "DIS",
    "DKL",
    "DLTR",
    "DNBBY",
    "DOCN",
    "DOV",
    "DRD",
    "DRI",
    "DRS",
    "DSGX",
    "DTE",
    "DUK",
    "DVA",
    "DVN",
    "DXC",
    "DXCM",
    "DXPE",
    "DY",
    "EA",
    "EADSY",
    "EAT",
    "EBAY",
    "EBKDY",
    "EC",
    "ECL",
    "ECVT",
    "ED",
    "EDVMF",
    "EFX",
    "EGO",
    "EGP",
    "EHC",
    "EIX",
    "EL",
    "EME",
    "EMN",
    "EMR",
    "ENPH",
    "ENS",
    "ENSG",
    "ENVA",
    "EOG",
    "EQIX",
    "EQR",
    "ES",
    "ESEA",
    "ESE",
    "ESLT",
    "ESOA",
    "ESP",
    "ESS",
    "ETN",
    "ETR",
    "EVR",
    "EVRG",
    "EW",
    "EXC",
    "EXEL",
    "EXLS",
    "EXPD",
    "EXPE",
    "EXR",
    "EXTR",
    "EZPW",
    "F",
    "FANG",
    "FAST",
    "FBAK",
    "FBIN",
    "FBP",
    "FCFS",
    "FCX",
    "FDS",
    "FE",
    "FEDU",
    "FEIM",
    "FERG",
    "FHB",
    "FHI",
    "FFIV",
    "FINMY",
    "FIS",
    "FISV",
    "FITB",
    "FIX",
    "FLG",
    "FLEX",
    "FMC",
    "FMX",
    "FN",
    "FNF",
    "FNV",
    "FOXA",
    "FRBA",
    "FRD",
    "FRO",
    "FRT",
    "FSI",
    "FTAI",
    "FTNT",
    "FTRE",
    "FTV",
    "FUNC",
    "GD",
    "GCT",
    "GDDY",
    "GE",
    "GEV",
    "GFI",
    "GH",
    "GHM",
    "GILD",
    "GIS",
    "GL",
    "GLW",
    "GM",
    "GMAB",
    "GOOG",
    "GOOGL",
    "GPC",
    "GPN",
    "GRAL",
    "GRMN",
    "GS",
    "GSHD",
    "GTX",
    "GVA",
    "GWW",
    "HALO",
    "HAS",
    "HBAN",
    "HBM",
    "HCA",
    "HCI",
    "HD",
    "HDLMY",
    "HG",
    "HGV",
    "HIG",
    "HII",
    "HL",
    "HLI",
    "HLT",
    "HMY",
    "HOLX",
    "HRL",
    "HROW",
    "HSBC",
    "HST",
    "HSY",
    "HTHIY",
    "HUBB",
    "HUM",
    "HUN",
    "HWBK",
    "HWKN",
    "HWM",
    "IBKR",
    "IBP",
    "ICE",
    "IDCC",
    "IDR",
    "IDXX",
    "IESC",
    "IEX",
    "IFF",
    "IIIN",
    "IMVT",
    "INCY",
    "INFY",
    "ING",
    "INOD",
    "INSM",
    "INTC",
    "INTU",
    "IP",
    "IPAR",
    "IQV",
    "IR",
    "IRM",
    "IRMD",
    "ISNPY",
    "ISRG",
    "ITIC",
    "ITRN",
    "ITT",
    "ITW",
    "IVZ",
    "JBL",
    "JBHT",
    "JCI",
    "JKHY",
    "JMIA",
    "JNJ",
    "JOE",
    "JPM",
    "KAJMY",
    "KB",
    "KBCSY",
    "KEY",
    "KEYS",
    "KGC",
    "KIM",
    "KINS",
    "KLAC",
    "KMB",
    "KMI",
    "KMX",
    "KO",
    "KR",
    "KSS",
    "KTOS",
    "L",
    "LAUR",
    "LDOS",
    "LEA",
    "LECO",
    "LEN",
    "LET",
    "LEU",
    "LH",
    "LHX",
    "LII",
    "LIN",
    "LINC",
    "LITE",
    "LLY",
    "LMAT",
    "LMB",
    "LMT",
    "LMND",
    "LNC",
    "LNT",
    "LOPE",
    "LOW",
    "LPG",
    "LRCX",
    "LSCC",
    "LUGDF",
    "LUMN",
    "LUV",
    "LVS",
    "LW",
    "LYB",
    "LYV",
    "MA",
    "MAR",
    "MARUY",
    "MAS",
    "MAT",
    "MATX",
    "MC",
    "MCD",
    "MCK",
    "MCO",
    "MCRI",
    "MDGL",
    "MDT",
    "MDLZ",
    "MELI",
    "META",
    "MFC",
    "MGA",
    "MGIC",
    "MGM",
    "MHK",
    "MITSY",
    "MKC",
    "MLI",
    "MLM",
    "MMM",
    "MOD",
    "MNST",
    "MOS",
    "MPC",
    "MPWR",
    "MRK",
    "MRVL",
    "MS",
    "MSFT",
    "MT",
    "MTB",
    "MTD",
    "MTG",
    "MTSI",
    "MTX",
    "MTZ",
    "MU",
    "MWA",
    "MYRG",
    "NBHC",
    "NDAQ",
    "NEE",
    "NEM",
    "NFLX",
    "NG",
    "NGD",
    "NGL",
    "NGVC",
    "NIC",
    "NKE",
    "NMIH",
    "NNI",
    "NOC",
    "NOW",
    "NPO",
    "NRG",
    "NTRA",
    "NUE",
    "NVDA",
    "NVMI",
    "NWPX",
    "NXPI",
    "NXST",
    "NXT",
    "OCANF",
    "ODC",
    "ODFL",
    "OI",
    "OMAB",
    "OMER",
    "ONDS",
    "ONTO",
    "OPY",
    "OR",
    "ORCL",
    "ORI",
    "ORLY",
    "OSIS",
    "OVCHY",
    "PAAS",
    "PAC",
    "PAG",
    "PANW",
    "PATK",
    "PCVX",
    "PDEX",
    "PEP",
    "PFE",
    "PFS",
    "PFSI",
    "PGR",
    "PH",
    "PHG",
    "PIPR",
    "PLD",
    "PLPC",
    "PLUS",
    "PLXS",
    "PM",
    "PNFP",
    "PNRG",
    "POWL",
    "PPIH",
    "PPTA",
    "PRI",
    "PRIM",
    "PSIX",
    "PWR",
    "PYPL",
    "QCOM",
    "QQQ",
    "QXO",
    "R",
    "RBA",
    "RBC",
    "RBCAA",
    "RCL",
    "RCMT",
    "RDNT",
    "REAL",
    "REGN",
    "RELX",
    "RF",
    "RGC",
    "RGLD",
    "RGS",
    "RJF",
    "RMBS",
    "RNMBY",
    "ROP",
    "ROST",
    "RTX",
    "RUSHB",
    "RVTY",
    "RXEEY",
    "RY",
    "RYAAY",
    "RYI",
    "SAFRY",
    "SAIA",
    "SAIC",
    "SANM",
    "SAR",
    "SBCF",
    "SBGSY",
    "SBH",
    "SBS",
    "SBUX",
    "SCCO",
    "SCHW",
    "SENEA",
    "SGGKY",
    "SGI",
    "SHC",
    "SHOO",
    "SIEGY",
    "SIETY",
    "SII",
    "SIM",
    "SIMO",
    "SKYW",
    "SLF",
    "SMID",
    "SMTOY",
    "SNA",
    "SNDR",
    "SNDX",
    "SNEX",
    "SNFCA",
    "SNPS",
    "SNX",
    "SO",
    "SONY",
    "SPRY",
    "SPXC",
    "SPXCY",
    "SPY",
    "SRCE",
    "SRPT",
    "SSUMY",
    "ST",
    "STLD",
    "STN",
    "STRL",
    "STT",
    "STX",
    "SUBCY",
    "SUPN",
    "SWK",
    "SYF",
    "SYK",
    "T",
    "TALO",
    "TAP",
    "TATT",
    "TAYD",
    "TBBK",
    "TCI",
    "TECH",
    "TECK",
    "TER",
    "TFC",
    "TGB",
    "TGLS",
    "TGS",
    "TGT",
    "THC",
    "THG",
    "TIMB",
    "TIPT",
    "TKO",
    "TLRY",
    "TMO",
    "TMUS",
    "TOELY",
    "TOL",
    "TORXF",
    "TOWN",
    "TPC",
    "TPH",
    "TPR",
    "TRT",
    "TRV",
    "TSEM",
    "TSLA",
    "TSM",
    "TSSI",
    "TT",
    "TTMI",
    "TWO",
    "TX",
    "TXN",
    "TYL",
    "UAL",
    "UAN",
    "UBS",
    "UNH",
    "UNM",
    "UPS",
    "URI",
    "UTHR",
    "UTI",
    "UUUU",
    "V",
    "VECO",
    "VIK",
    "VIRT",
    "VLO",
    "VLVLY",
    "VLY",
    "VMI",
    "VOYA",
    "VRDN",
    "VSCO",
    "VSEC",
    "VZ",
    "WBS",
    "WCC",
    "WDC",
    "WELL",
    "WES",
    "WF",
    "WINA",
    "WLDN",
    "WM",
    "WMB",
    "WMT",
    "WOLF",
    "WOR",
    "WPM",
    "WRB",
    "WRLD",
    "WSBC",
    "WTFC",
    "WTS",
    "WWD",
    "XOM",
    "XPEL",
    "XPO",
    "YETI",
    "YUM",
    "ZETA",
    "ZFSVF",
    "ZIJMY",
    "ZION",
    "ZM",
    "ZTS",
    "ZURVY",
    "ZWS",
    "BABA",
    "BIDU",
    "BILL",
    "BILI",
    "BNTX",
    "CHKP",
    "CRWD",
    "DDOG",
    "DOCU",
    "ESTC",
    "FIVN",
    "FSLY",
    "HUBS",
    "LOGI",
    "MDB",
    "NET",
    "OKTA",
    "PAYC",
    "PINS",
    "PLTR",
    "PTC",
    "RNG",
    "SE",
    "SHOP",
    "SNOW",
    "SSNC",
    "TEAM",
    "TENB",
    "TTD",
    "TWLO",
    "U",
    "VRSN",
    "WDAY",
    "WIX",
    "ZS",
    "ALGN",
    "ALNY",
    "AMN",
    "ARGX",
    "BSX",
    "DXCM",
    "EW",
    "EXAS",
    "HALO",
    "IDXX",
    "IQV",
    "ISRG",
    "MRNA",
    "NEO",
    "NVAX",
    "NVCR",
    "PACB",
    "RMD",
    "VRTX",
    "ABG",
    "AGCO",
    "BBY",
    "CASY",
    "CHRW",
    "CPRI",
    "DKS",
    "DPZ",
    "DRI",
    "HOG",
    "JACK",
    "KSS",
    "LAD",
    "LCII",
    "M",
    "MAT",
    "NKE",
    "NWL",
    "ORLY",
    "PAG",
    "POOL",
    "PVH",
    "RL",
    "ROST",
    "SBUX",
    "SEE",
    "SHW",
    "SYY",
    "TGT",
    "TJX",
    "TPR",
    "TSCO",
    "TSN",
    "ULTA",
    "VFC",
    "WHR",
    "WYNN",
    "YUM",
    "AME",
    "APC",
    "CAT",
    "CMI",
    "DE",
    "DOV",
    "EOG",
    "ETN",
    "FAST",
    "FTV",
    "GD",
    "GWW",
    "HAL",
    "HON",
    "ITW",
    "JCI",
    "KBR",
    "LMT",
    "MMM",
    "MPC",
    "NOC",
    "ODFL",
    "OXY",
    "PH",
    "ROK",
    "ROP",
    "RSG",
    "SLB",
    "VLO",
    "WAB",
    "WM",
    "XYL",
    "AMP",
    "BLK",
    "CUBE",
    "EXR",
    "FICO",
    "GLPI",
    "GS",
    "IVZ",
    "MS",
    "NTRS",
    "O",
    "PNC",
    "PRU",
    "PSA",
    "SBAC",
    "SCHW",
    "STT",
    "SYF",
    "TFC",
    "TROW",
    "USB",
    "WFC",
    "AA",
    "AAL",
    "AFG",
    "ALB",
    "AMKR",
    "APA",
    "ARW",
    "ASH",
    "ATI",
    "AVT",
    "BC",
    "BWA",
    "CE",
    "CIEN",
    "CINF",
    "CLF",
    "CMC",
    "CNC",
    "CNP",
    "CORT",
    "CRS",
    "CSL",
    "DHI",
    "DY",
    "EME",
    "EMN",
    "ETR",
    "EVR",
    "EXPE",
    "FDS",
    "FLEX",
    "FLS",
    "FMC",
    "FNF",
    "FRT",
    "FTI",
    "G",
    "GGAL",
    "GME",
    "GNTX",
    "GPK",
    "GVA",
    "HI",
    "HP",
    "HURC",
    "ICL",
    "IDA",
    "IDR",
    "IEX",
    "ITT",
    "JBHT",
    "JBLU",
    "KEX",
    "KFY",
    "LBRT",
    "LITE",
    "LNC",
    "LRCX",
    "LSTR",
    "LUV",
    "LVS",
    "MAN",
    "MAS",
    "MCK",
    "MDU",
    "MIDD",
    "MKC",
    "MLM",
    "MMS",
    "MODV",
    "MORN",
    "MTDR",
    "MTX",
    "MUR",
    "NBIX",
    "NBR",
    "NDSN",
    "NE",
    "NEE",
    "NFG",
    "NLY",
    "NMR",
    "NNN",
    "NOV",
    "NRG",
    "NSC",
    "NTAP",
    "NVST",
    "NWS",
    "NXPI",
    "NYT",
    "OC",
    "OGE",
    "OHI",
    "OI",
    "OKE",
    "OLED",
    "OMC",
    "ON",
    "OSK",
    "OTIS",
    "PANW",
    "PAYX",
    "PB",
    "PBI",
    "PCAR",
    "PCG",
    "PEG",
    "PENN",
    "PFG",
    "PG",
    "PHM",
    "PKG",
    "PLD",
    "PLT",
    "PNR",
    "PNW",
    "PPG",
    "PPL",
    "PSX",
    "PTC",
    "PWR",
    "QRVO",
    "REG",
    "RHI",
    "RIG",
    "RJF",
    "ROL",
    "RTX",
    "SLG",
    "SNPS",
    "SO",
    "SPG",
    "SPGI",
    "SRE",
    "STE",
    "STX",
    "STZ",
    "SWK",
    "SWKS",
    "SYK",
    "TDG",
    "TDY",
    "TEL",
    "TER",
    "TFX",
    "TTWO",
    "TXN",
    "TXT",
    "TYL",
    "UA",
    "UDR",
    "UHS",
    "UNP",
    "URI",
    "VNO",
    "VRSK",
    "VTR",
    "VTRS",
    "WAT",
    "WDC",
    "WEC",
    "WRB",
    "WST",
    "WU",
    "WY",
    "XEL",
    "XRAY",
    "XRX",
    "ZBH",
    "ZBRA",
    "ZION",
    "AAPL",
    "ABNB",
    "ACGL",
    "AEP",
    "AES",
    "ALNY",
    "APP",
    "ARM",
    "ASML",
    "AVB",
    "AXON",
    "BBWI",
    "BKNG",
    "BKR",
    "CAG",
    "CAH",
    "CARR",
    "CB",
    "CCEP",
    "CEG",
    "CHD",
    "CMCSA",
    "COST",
    "CPAY",
    "CPRT",
    "DASH",
    "DGX",
    "DLR",
    "DOC",
    "DOW",
    "DTE",
    "DUK",
    "EG",
    "ELV",
    "EPAM",
    "EXC",
    "FER",
    "FICO",
    "FOX",
    "FSLR",
    "GEHC",
    "GEN",
    "GNRC",
    "GOOG",
    "HPE",
    "HPQ",
    "HST",
    "IBM",
    "IDXX",
    "INSM",
    "INVH",
    "IT",
    "J",
    "KDP",
    "KHC",
    "KVUE",
    "LULU",
    "MAA",
    "MET",
    "MO",
    "MOH",
    "MPWR",
    "MSCI",
    "MSI",
    "NVR",
    "NWSA",
    "O",
    "OTIS",
    "PAYC",
    "PCG",
    "PPL",
    "REG",
    "SJM",
    "SOLV",
    "SRE",
    "STZ",
    "TRGP",
    "TRMB",
    "TRV",
    "VICI",
    "VLTO",
    "VMC",
    "WBD",
    "WEC",
    "WST",
    "WTW",
    "XEL",
]


def _parse_symbols(s: str) -> list[str]:
    return [x.strip().upper() for x in s.split(",") if x.strip()]


def _parse_option_expiry(exp_str: str) -> date | None:
    """Parse Yahoo-style expiry string (usually YYYY-MM-DD)."""
    raw = str(exp_str).strip()[:10]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _select_expiration(
    exps: list[str],
    min_days: int,
    as_of: date | None = None,
) -> tuple[str, list[str]]:
    """
    Pick earliest expiration with (expiry_date - as_of).days >= min_days.
    If none qualify, use farthest listed expiry and append explanation notes.
    """
    notes: list[str] = []
    if as_of is None:
        as_of = date.today()
    parsed: list[tuple[str, date]] = []
    for e in exps:
        d = _parse_option_expiry(e)
        if d is not None:
            parsed.append((e, d))
    if not parsed:
        return exps[0], ["could_not_parse_expirations; using first raw expiry string"]

    parsed.sort(key=lambda x: x[1])
    min_days = max(0, int(min_days))

    if min_days == 0:
        return parsed[0][0], notes

    ok = [(e, d) for e, d in parsed if (d - as_of).days >= min_days]
    if ok:
        ok.sort(key=lambda x: x[1])
        return ok[0][0], notes

    e_far, d_far = parsed[-1]
    days_out = (d_far - as_of).days
    notes.append(f"no_expiry_ge_{min_days}d_calendar; using_farthest_listed {e_far} ({days_out}d out)")
    return e_far, notes


def _last_close(ticker: yf.Ticker, max_retries: int = 6, base_wait_sec: float = 2.5) -> float:
    def _fetch() -> float:
        h = ticker.history(period="5d", auto_adjust=True)
        if h is None or h.empty or "Close" not in h.columns:
            return float("nan")
        return float(h["Close"].iloc[-1])

    return float(_yahoo_call(_fetch, max_retries, base_wait_sec))


def _mid(bid: float, ask: float) -> float:
    if bid > 0 and ask > 0:
        return 0.5 * (bid + ask)
    if ask > 0:
        return ask
    if bid > 0:
        return bid
    return float("nan")


@dataclass
class LiquidityRow:
    symbol: str
    last_price: float
    expiration: str
    n_rows: int
    n_calls: int
    n_puts: int
    total_oi: int
    total_volume: int
    median_spread_abs: float
    median_spread_pct: float
    mean_spread_pct: float
    min_spread_pct: float
    pct_wide_spread: float  # fraction with spread_pct > WIDE_SPREAD_PCT or invalid mid
    note: str


WIDE_SPREAD_PCT = 0.05  # 5% of mid considered "wide" for summary stat
# Relative distance |strike-spot|/spot <= this counts as ATM for our moneyness label (Yahoo has no ATM bit).
ATM_BAND_REL = 0.005

# Black–Scholes delta (European); Yahoo chain has no delta field.
RISK_FREE_BS = 0.045  # annualized, fixed (not fetched from curve)
IV_MIN_BS = 0.03  # clamp implied vol (as decimal, e.g. 0.25 = 25%) for stable d1
IV_MAX_BS = 2.5


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _sigma_for_bs(iv_raw: object) -> float | None:
    """Turn chain IV into a BS vol; return None if unusable."""
    if iv_raw is None or (isinstance(iv_raw, float) and iv_raw != iv_raw):
        return None
    try:
        v = float(iv_raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v <= 0:
        return None
    return min(max(v, IV_MIN_BS), IV_MAX_BS)


def _bs_d1(S: float, K: float, T: float, r: float, sigma: float, q: float) -> float:
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return float("nan")
    return (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))


def _years_to_expiry(exp_d: date | None, as_of: date | None = None) -> float:
    if exp_d is None:
        return 30.0 / 365.25
    if as_of is None:
        as_of = date.today()
    days = max((exp_d - as_of).days, 1)
    return days / 365.25


def _bs_delta(spot: float, strike: float, T: float, r: float, sigma: float, q: float, right: str) -> float:
    d1 = _bs_d1(spot, strike, T, r, sigma, q)
    if d1 != d1:
        return float("nan")
    nd1 = _norm_cdf(d1)
    rc = (right or "").strip().upper()[:1]
    if rc == "P":
        return nd1 - 1.0
    return nd1


def _moneyness_label(spot: float, strike: float, right: str) -> str:
    """
    ITM / ATM / OTM vs last underlying price.
    Call: ITM if strike < spot, OTM if strike > spot.
    Put:  ITM if strike > spot, OTM if strike < spot.
    ATM if strike is within ATM_BAND_REL of spot (both sides).
    """
    if not (spot == spot and spot > 0 and strike == strike):
        return ""
    rcp = (right or "").strip().upper()[:1]
    rel = abs(float(strike) - float(spot)) / float(spot)
    if rel <= ATM_BAND_REL:
        return "ATM"
    if rcp == "C":
        return "ITM" if float(strike) < float(spot) else "OTM"
    if rcp == "P":
        return "ITM" if float(strike) > float(spot) else "OTM"
    return ""


def _yahoo_in_the_money_str(row: pd.Series, columns: pd.Index) -> str:
    if "inTheMoney" not in columns:
        return ""
    v = row.get("inTheMoney")
    if pd.isna(v):
        return ""
    return "yes" if bool(v) else "no"


def _contract_export_row(
    symbol: str,
    spot: float,
    exp: str,
    r: pd.Series,
    cols_ix: pd.Index,
    T_years: float,
    div_yield: float,
) -> dict[str, object]:
    """One option row for CSV / detail tables (same schema as _TIGHTEST_COLS)."""
    csym = r["contractSymbol"] if "contractSymbol" in cols_ix and pd.notna(r.get("contractSymbol")) else ""
    cp = str(r.get("right", "") or "")
    stk = float(r["strike"]) if pd.notna(r["strike"]) else float("nan")
    iv_raw = r.get("impliedVolatility") if "impliedVolatility" in cols_ix else float("nan")
    iv_out = float(iv_raw) if pd.notna(iv_raw) else float("nan")
    sig = _sigma_for_bs(iv_raw)
    d_bs = float("nan")
    if sig is not None and spot == spot and stk == stk and T_years > 0:
        d_bs = _bs_delta(float(spot), float(stk), float(T_years), RISK_FREE_BS, float(sig), float(div_yield), cp)
    return {
        "symbol": symbol,
        "underlying_last": float(spot) if spot == spot else float("nan"),
        "expiration": exp,
        "contract_symbol": str(csym) if csym is not None else "",
        "call_put": cp,
        "strike": stk,
        "moneyness": _moneyness_label(spot, stk, cp),
        "yahoo_in_the_money": _yahoo_in_the_money_str(r, cols_ix),
        "bid": float(r["_bid"]) if pd.notna(r["_bid"]) else float("nan"),
        "ask": float(r["_ask"]) if pd.notna(r["_ask"]) else float("nan"),
        "mid": float(r["_mid"]) if pd.notna(r["_mid"]) else float("nan"),
        "spread_abs": float(r["_spread"]) if pd.notna(r["_spread"]) else float("nan"),
        "spread_pct": float(r["_spread_pct"]) if pd.notna(r["_spread_pct"]) else float("nan"),
        "implied_volatility": iv_out,
        "delta_bs": d_bs,
        "volume": int(r["volume"]) if pd.notna(r["volume"]) else 0,
        "open_interest": int(r["openInterest"]) if pd.notna(r["openInterest"]) else 0,
    }


_TIGHTEST_COLS = [
    "symbol",
    "underlying_last",
    "expiration",
    "contract_symbol",
    "call_put",
    "strike",
    "moneyness",
    "yahoo_in_the_money",
    "bid",
    "ask",
    "mid",
    "spread_abs",
    "spread_pct",
    "implied_volatility",
    "delta_bs",
    "volume",
    "open_interest",
]


def _empty_tightest_df() -> pd.DataFrame:
    return pd.DataFrame(columns=_TIGHTEST_COLS)


def _tightest_details(
    symbol: str,
    spot: float,
    exp: str,
    priced: pd.DataFrame,
    T_years: float,
    div_yield: float,
) -> tuple[float, pd.DataFrame]:
    """Rows tied at min spread_pct among priced (finite spread_pct)."""
    pc = priced.dropna(subset=["_spread_pct"])
    if pc.empty:
        return float("nan"), _empty_tightest_df()
    m = float(pc["_spread_pct"].min())
    tight = pc.loc[np.isclose(pc["_spread_pct"].to_numpy(dtype=float), m, rtol=0.0, atol=1e-12)].copy()
    rows: list[dict] = []
    cols_ix = tight.columns
    for _, r in tight.iterrows():
        rows.append(_contract_export_row(symbol, spot, exp, r, cols_ix, T_years, div_yield))
    return m, pd.DataFrame(rows, columns=_TIGHTEST_COLS)


def summarize_chain(
    symbol: str,
    band: float,
    min_days_to_expiry: int = 45,
    *,
    yahoo_max_retries: int = 6,
    yahoo_base_wait_sec: float = 2.5,
) -> tuple[LiquidityRow, pd.DataFrame, pd.DataFrame]:
    """
    band: include strikes where strike is within [1-band, 1+band] * spot (e.g. 0.15 = ±15%).
    min_days_to_expiry: use earliest expiration at least this many calendar days ahead.
    Returns (summary row, tightest-spread rows, all strike-band rows) for CSV export.
    """
    t = yf.Ticker(symbol)
    spot = _last_close(t, yahoo_max_retries, yahoo_base_wait_sec)
    note_parts: list[str] = []

    try:
        exps = _yahoo_call(lambda: list(t.options), yahoo_max_retries, yahoo_base_wait_sec)
    except Exception as e:  # noqa: BLE001
        return (
            LiquidityRow(
                symbol,
                spot,
                "",
                0,
                0,
                0,
                0,
                0,
                float("nan"),
                float("nan"),
                float("nan"),
                float("nan"),
                float("nan"),
                f"options list error: {e}",
            ),
            _empty_tightest_df(),
            _empty_tightest_df(),
        )

    if not exps:
        return (
            LiquidityRow(
                symbol,
                spot,
                "",
                0,
                0,
                0,
                0,
                0,
                float("nan"),
                float("nan"),
                float("nan"),
                float("nan"),
                float("nan"),
                "no option expirations returned",
            ),
            _empty_tightest_df(),
            _empty_tightest_df(),
        )

    exp, exp_notes = _select_expiration(exps, min_days_to_expiry)
    note_parts.extend(exp_notes)
    try:
        oc = _yahoo_call(lambda: t.option_chain(exp), yahoo_max_retries, yahoo_base_wait_sec)
    except Exception as e:  # noqa: BLE001
        return (
            LiquidityRow(
                symbol,
                spot,
                exp,
                0,
                0,
                0,
                0,
                0,
                float("nan"),
                float("nan"),
                float("nan"),
                float("nan"),
                float("nan"),
                f"option_chain error: {e}",
            ),
            _empty_tightest_df(),
            _empty_tightest_df(),
        )

    calls = oc.calls.copy()
    puts = oc.puts.copy()
    calls["right"] = "C"
    puts["right"] = "P"
    for df in (calls, puts):
        for c in ("bid", "ask", "strike", "volume", "openInterest", "impliedVolatility"):
            if c not in df.columns:
                df[c] = float("nan") if c in ("bid", "ask", "strike", "impliedVolatility") else 0

    calls["volume"] = pd.to_numeric(calls["volume"], errors="coerce").fillna(0).astype(int)
    puts["volume"] = pd.to_numeric(puts["volume"], errors="coerce").fillna(0).astype(int)
    calls["openInterest"] = pd.to_numeric(calls["openInterest"], errors="coerce").fillna(0).astype(int)
    puts["openInterest"] = pd.to_numeric(puts["openInterest"], errors="coerce").fillna(0).astype(int)

    chain = pd.concat([calls, puts], ignore_index=True)

    if not (spot == spot and spot > 0):
        note_parts.append("spot_unavailable_using_all_strikes")
        sub = chain
    else:
        lo = spot * (1.0 - band)
        hi = spot * (1.0 + band)
        sub = chain[(chain["strike"] >= lo) & (chain["strike"] <= hi)]
        if sub.empty:
            note_parts.append("no_strikes_in_band_using_full_chain")
            sub = chain

    bid = pd.to_numeric(sub["bid"], errors="coerce")
    ask = pd.to_numeric(sub["ask"], errors="coerce")
    sub = sub.assign(_bid=bid, _ask=ask)
    sub["_mid"] = sub.apply(lambda r: _mid(float(r["_bid"]), float(r["_ask"])), axis=1)
    sub["_spread"] = (sub["_ask"] - sub["_bid"]).clip(lower=0)
    sub["_spread_pct"] = sub["_spread"] / sub["_mid"].replace(0, float("nan"))
    # Spread % is meaningless when mid is tiny; score liquidity on "priced" quotes only.
    min_mid = 0.02
    priced = sub[sub["_mid"] >= min_mid]

    n = len(sub)
    if n == 0:
        return (
            LiquidityRow(
                symbol,
                spot,
                exp,
                0,
                0,
                0,
                0,
                0,
                float("nan"),
                float("nan"),
                float("nan"),
                float("nan"),
                float("nan"),
                "empty chain slice; " + "; ".join(note_parts),
            ),
            _empty_tightest_df(),
            _empty_tightest_df(),
        )

    n_calls = int((sub["right"] == "C").sum())
    n_puts = int((sub["right"] == "P").sum())
    total_oi = int(sub["openInterest"].sum())
    total_vol = int(sub["volume"].sum())
    exp_d = _parse_option_expiry(exp)
    T_years = _years_to_expiry(exp_d)
    div_y = 0.0
    try:
        inf = _yahoo_call(lambda: t.info, yahoo_max_retries, yahoo_base_wait_sec)
        if isinstance(inf, dict):
            dy = inf.get("dividendYield")
            if dy is not None and isinstance(dy, (int, float)) and float(dy) == float(dy):
                div_y = float(dy)
    except Exception:  # noqa: BLE001
        div_y = 0.0
    cols_ix_sub = sub.columns
    band_rows = [_contract_export_row(symbol, spot, exp, row, cols_ix_sub, T_years, div_y) for _, row in sub.iterrows()]
    band_df = pd.DataFrame(band_rows, columns=_TIGHTEST_COLS)

    med_abs = float(sub["_spread"].median())
    min_spread_pct = float("nan")
    detail_df = _empty_tightest_df()
    if len(priced) > 0:
        med_pct = float(priced["_spread_pct"].median(skipna=True))
        mean_pct = float(priced["_spread_pct"].mean(skipna=True))
        wide = priced["_spread_pct"].isna() | (priced["_spread_pct"] > WIDE_SPREAD_PCT)
        pct_wide = float(wide.mean())
        min_spread_pct, detail_df = _tightest_details(symbol, spot, exp, priced, T_years, div_y)
    else:
        med_pct = float("nan")
        mean_pct = float("nan")
        pct_wide = float("nan")
        note_parts.append(f"no_quotes_mid_ge_{min_mid}")

    note = "; ".join(note_parts) if note_parts else "ok"
    return (
        LiquidityRow(
            symbol,
            spot,
            exp,
            n,
            n_calls,
            n_puts,
            total_oi,
            total_vol,
            med_abs,
            med_pct,
            mean_pct,
            min_spread_pct,
            pct_wide,
            note,
        ),
        detail_df,
        band_df,
    )


def _write_contract_csv(df: pd.DataFrame, path: str) -> None:
    """Write contract-level columns in a fixed order (matches console / docs)."""
    df.reindex(columns=_TIGHTEST_COLS).to_csv(path, index=False, na_rep="")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Option chain liquidity via yfinance (expiry >= N days, near-ATM band)."
    )
    ap.add_argument(
        "--symbols",
        "-s",
        default=",".join(DEFAULT_SYMBOLS),
        help="Comma-separated tickers (default: built-in list).",
    )
    ap.add_argument(
        "--band",
        type=float,
        default=0.15,
        help="Strike band around last close as fraction (default 0.15 = ±15%%).",
    )
    ap.add_argument(
        "--min-days-to-expiry",
        type=int,
        default=45,
        help="Use earliest expiration at least this many calendar days from today (default 45). "
        "If Yahoo has no such expiry, uses farthest listed and notes it.",
    )
    ap.add_argument(
        "--csv",
        metavar="PATH",
        default="",
        help="If set, write summary results to this CSV path.",
    )
    ap.add_argument(
        "--csv-details",
        metavar="PATH",
        default="",
        help="Write tightest-spread contract rows (ties) to this CSV. If omitted but --csv is set, "
        "uses <csv_stem>_tightest_spread.csv next to the summary file.",
    )
    ap.add_argument(
        "--csv-band",
        metavar="PATH",
        default="",
        help="Write every contract in the strike band (moneyness, delta_bs, etc.). "
        "If omitted but --csv is set, uses <csv_stem>_band.csv next to the summary file.",
    )
    ap.add_argument(
        "--delay-between-symbols",
        type=float,
        default=0.0,
        metavar="SEC",
        help="Sleep SEC after each symbol (omit last). Use ~0.3–1.5 for large lists to reduce Yahoo throttling.",
    )
    ap.add_argument(
        "--yahoo-retries",
        type=int,
        default=6,
        help="Attempts per Yahoo HTTP-backed call on rate limit / transient errors (default 6).",
    )
    ap.add_argument(
        "--yahoo-base-wait",
        type=float,
        default=2.5,
        help="Base seconds for exponential backoff between retries (default 2.5).",
    )
    args = ap.parse_args()
    symbols = _parse_symbols(args.symbols)
    rows: list[LiquidityRow] = []
    detail_parts: list[pd.DataFrame] = []
    band_parts: list[pd.DataFrame] = []
    for idx, sym in enumerate(symbols):
        try:
            summ, det, band = summarize_chain(
                sym,
                band=float(args.band),
                min_days_to_expiry=int(args.min_days_to_expiry),
                yahoo_max_retries=int(args.yahoo_retries),
                yahoo_base_wait_sec=float(args.yahoo_base_wait),
            )
        except BaseException as e:
            if _yahoo_transient(e):
                print(f"{sym}: Yahoo error after retries ({e!r}); skipping row details.", file=sys.stderr)
                summ = LiquidityRow(
                    sym,
                    float("nan"),
                    "",
                    0,
                    0,
                    0,
                    0,
                    0,
                    float("nan"),
                    float("nan"),
                    float("nan"),
                    float("nan"),
                    float("nan"),
                    f"yahoo_error_after_retries: {e!s}",
                )
                det = _empty_tightest_df()
                band = _empty_tightest_df()
            else:
                raise
        rows.append(summ)
        detail_parts.append(det)
        band_parts.append(band)
        dly = float(args.delay_between_symbols)
        if dly > 0.0 and idx + 1 < len(symbols):
            time.sleep(dly)

    df = pd.DataFrame([r.__dict__ for r in rows])
    # Human-friendly column order
    cols = [
        "symbol",
        "last_price",
        "expiration",
        "n_rows",
        "n_calls",
        "n_puts",
        "total_oi",
        "total_volume",
        "median_spread_abs",
        "median_spread_pct",
        "mean_spread_pct",
        "min_spread_pct",
        "pct_wide_spread",
        "note",
    ]
    df = df[cols]
    df_detail = pd.concat(detail_parts, ignore_index=True) if detail_parts else _empty_tightest_df()
    df_band = pd.concat(band_parts, ignore_index=True) if band_parts else _empty_tightest_df()
    with pd.option_context("display.max_rows", None, "display.width", 200, "display.float_format", lambda x: f"{x:.4f}"):
        print(df.to_string(index=False))
    print("\n--- Tightest spread % (mid >= $0.02); all contracts tied at min for that symbol ---\n")
    with pd.option_context("display.max_rows", None, "display.width", 220, "display.float_format", lambda x: f"{x:.6f}"):
        print(df_detail.to_string(index=False))
    if args.csv:
        df.to_csv(args.csv, index=False)
        print(f"\nWrote {args.csv}", file=sys.stderr)
    detail_path = args.csv_details
    if not detail_path and args.csv:
        p = Path(args.csv)
        detail_path = str(p.with_name(p.stem + "_tightest_spread" + p.suffix))
    if detail_path:
        _write_contract_csv(df_detail, detail_path)
        print(f"Wrote {detail_path}", file=sys.stderr)
    band_path = args.csv_band
    if not band_path and args.csv:
        p2 = Path(args.csv)
        band_path = str(p2.with_name(p2.stem + "_band" + p2.suffix))
    if band_path:
        _write_contract_csv(df_band, band_path)
        print(f"Wrote {band_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
