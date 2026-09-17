"""
Scanner 2 Configuration
------------------------
இதுல எல்லா settings ஒரே இடத்துல இருக்கும் — indices, thresholds, strikes count.
புது index/commodity சேர்க்கணும்னாலும், threshold மாத்தணும்னாலும் இந்த file-ஐ மட்டும் edit பண்ணா போதும்.
"""

# ---------------------------------------------------------
# Upstox instrument keys (NSE/BSE/MCX underlying symbols)
# NOTE: இதை Upstox Instruments master file-ல இருந்து confirm பண்ணிக்கோங்க
# (https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz)
# ---------------------------------------------------------

INDICES = {
    "NIFTY": {
        "underlying_key": "NSE_INDEX|Nifty 50",
        "exchange": "NSE_FO",
        "has_weekly": True,
        "has_monthly": True,
        "spike_threshold": 15,
        "strike_range": 30,
    },
    "BANKNIFTY": {
        "underlying_key": "NSE_INDEX|Nifty Bank",
        "exchange": "NSE_FO",
        "has_weekly": False,   # SEBI Nov-2024 circular prayakaram, monthly mattum
        "has_monthly": True,
        "spike_threshold": 15,
        "strike_range": 60,
    },
    "SENSEX": {
        "underlying_key": "BSE_INDEX|SENSEX",
        "exchange": "BSE_FO",
        "has_weekly": True,    # Thursday expiry
        "has_monthly": True,
        "spike_threshold": 15,
        "strike_range": 80,
    },
    "FINNIFTY": {
        "underlying_key": "NSE_INDEX|Nifty Fin Service",
        "exchange": "NSE_FO",
        "has_weekly": False,   # monthly mattum
        "has_monthly": True,
        "spike_threshold": 15,
        "strike_range": 30,
    },
}

MCX_COMMODITIES = {
    "CRUDEOIL": {
        "underlying_key": "MCX_FO|CRUDEOIL",
        "exchange": "MCX_FO",
        "spike_threshold": 10,
        "otm_strikes": 10,
    },
    "NATURALGAS": {
        "underlying_key": "MCX_FO|NATURALGAS",
        "exchange": "MCX_FO",
        "spike_threshold": 3,
        "otm_strikes": 10,
    },
    "GOLD": {
        "underlying_key": "MCX_FO|GOLD",
        "exchange": "MCX_FO",
        "spike_threshold": 20,
        "otm_strikes": 10,
    },
}

# Baseline store — ஒவ்வொரு strike-ன் opening premium இங்க save ஆகும்
BASELINE_FILE = "baseline_premiums.json"

# Alert பண்ணின strikes track பண்ண (ஒரே strike-க்கு repeat alert வராம இருக்க)
ALERTED_FILE = "alerted_strikes.json"

# Market timing (IST)
MARKET_OPEN = "09:15"
MARKET_CLOSE = "15:30"
BASELINE_CAPTURE_TIME = "09:16"   # market open ஆன 1 நிமிடம் கழிச்சு baseline எடுக்கும்
