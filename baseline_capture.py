"""
Baseline Capture Script
-------------------------
Market open ஆன உடனே (9:16 AM) ஒரு தடவை run ஆகி, ஒவ்வொரு index/commodity-க்கும்
Weekly + Monthly (applicable-ஆ இருக்கிறதுக்கு) spot price-ஐ base வெச்சு,
strike_range points-க்குள் வர்ற strikes-ன் OPENING premium-ஐ baseline_premiums.json-ல save பண்ணும்.
இதுக்கு அப்புறம் தான் scanner.py ஓடி, spike detect பண்ணும்.
"""

import os
import json
import gzip
import requests
import pytz
from datetime import datetime, date

from config import INDICES, MCX_COMMODITIES, BASELINE_FILE

IST = pytz.timezone("Asia/Kolkata")

UPSTOX_ACCESS_TOKEN = os.environ["UPSTOX_ACCESS_TOKEN"]
HEADERS = {
    "Authorization": f"Bearer {UPSTOX_ACCESS_TOKEN}",
    "Accept": "application/json",
}

INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"
_instruments_cache = None


def load_instruments_master():
    """
    Upstox full instruments master file download பண்ணி cache பண்றது.
    MCX commodities-க்கு exact instrument_key இதுல இருந்து தான் கண்டுபிடிக்க முடியும்
    (hardcode பண்ண முடியாது, internal numeric token இருக்கும்).
    """
    global _instruments_cache
    if _instruments_cache is not None:
        return _instruments_cache

    print("[INFO] Instruments master file download பண்றேன்...")
    resp = requests.get(INSTRUMENTS_URL, timeout=60)
    resp.raise_for_status()
    raw = gzip.decompress(resp.content)
    _instruments_cache = json.loads(raw)
    print(f"[INFO] {len(_instruments_cache)} instruments load ஆனது.")
    return _instruments_cache


def get_mcx_futures_instrument_key(commodity_name):
    """
    MCX commodity-க்கு (CRUDEOIL/NATURALGAS/GOLD) nearest-expiry FUTURES
    contract-ன் instrument_key-ஐ master file-ல இருந்து கண்டுபிடிக்கும்.
    இதுவே ATM base price (spot substitute) calculate பண்ண பயன்படும்.
    """
    instruments = load_instruments_master()
    matches = [
        i for i in instruments
        if i.get("segment") == "MCX_FO"
        and i.get("instrument_type") == "FUT"
        and i.get("asset_symbol", "").upper() == commodity_name.upper()
    ]
    if not matches:
        # fallback: name field-ல commodity name start ஆகுதான்னு பாரு
        matches = [
            i for i in instruments
            if i.get("segment") == "MCX_FO"
            and i.get("instrument_type") == "FUT"
            and i.get("name", "").upper().startswith(commodity_name.upper())
        ]
    if not matches:
        raise Exception(
            f"[MCX LOOKUP FAIL] '{commodity_name}' க்கு MCX_FO futures contract "
            f"instruments master-ல கிடைக்கல. Symbol name மாறியிருக்கலாம்."
        )
    # Nearest expiry contract எடு
    matches.sort(key=lambda x: x.get("expiry", ""))
    nearest = matches[0]
    print(f"[MCX FUT] {commodity_name} -> {nearest['instrument_key']} (expiry {nearest.get('expiry')})")
    return nearest["instrument_key"]


def get_spot_price(underlying_key):
    url = "https://api.upstox.com/v2/market-quote/ltp"
    params = {"instrument_key": underlying_key}
    resp = requests.get(url, headers=HEADERS, params=params)
    resp.raise_for_status()
    body = resp.json()
    data = body.get("data", {})
    if not data:
        raise Exception(
            f"[SPOT PRICE FAIL] instrument_key='{underlying_key}' க்கு data காலியா "
            f"வந்துச்சு. Full response: {body}. "
            f"இந்த instrument_key தப்பா இருக்கலாம் - Upstox instruments master "
            f"file-ல verify பண்ணு."
        )
    first_key = list(data.keys())[0]
    return data[first_key]["last_price"]


def get_nearest_expiry(underlying_key, weekly=True):
    """
    Upstox /option/contract endpoint எல்லா available expiries கொடுக்கும்.
    Weekly=True na nearest expiry edukkanum (indru expiry naal-um SERI, past
    illama), False na (monthly) andha month-oda last expiry edukkanum.

    Bug fix: முன்ன "expiries[0]" (string-sorted முதலாவது) எடுத்தோம் - ஆனா
    expiry day அன்னிக்கே, Upstox சில நேரம் list order மாறி, "இன்னிக்கு"
    expiry-க்கு பதிலா "அடுத்த வாரம்" expiry முதலாவதா வந்திடுச்சு. இப்போ
    today's date-ஐ விட முன்னாடி இல்லாத (>=today) expiries-ல இருந்து மட்டும்
    நெருக்கமான ஒண்ணை explicit-ஆ தேர்ந்தெடுக்கிறோம்.
    """
    url = "https://api.upstox.com/v2/option/contract"
    params = {"instrument_key": underlying_key}
    resp = requests.get(url, headers=HEADERS, params=params)
    resp.raise_for_status()
    contracts = resp.json()["data"]

    all_expiries = sorted(set(c["expiry"] for c in contracts))
    print(f"[EXPIRY LIST] {underlying_key} -> {all_expiries}")

    today_ist = datetime.now(IST).date()
    parsed = [(datetime.strptime(e, "%Y-%m-%d").date(), e) for e in all_expiries]
    upcoming = sorted([p for p in parsed if p[0] >= today_ist], key=lambda p: p[0])

    if weekly:
        if not upcoming:
            raise Exception(
                f"[EXPIRY FAIL] {underlying_key} - இன்னிக்கு ({today_ist}) அல்லது "
                f"அதுக்கு பிறகான expiry ஒண்ணும் கிடைக்கல. All expiries: {all_expiries}"
            )
        chosen = upcoming[0][1]
        print(f"[EXPIRY CHOSEN] weekly -> {chosen} (today={today_ist})")
        return chosen

    # monthly = current month-oda last expiry date (இன்னிக்கை விட முன்ன இல்லாதது)
    current_month = today_ist.month
    month_expiries = [e for d, e in upcoming if d.month == current_month]
    chosen = month_expiries[-1] if month_expiries else (upcoming[-1][1] if upcoming else all_expiries[-1])
    print(f"[EXPIRY CHOSEN] monthly -> {chosen} (today={today_ist})")
    return chosen


def fetch_option_chain(underlying_key, expiry_date):
    url = "https://api.upstox.com/v2/option/chain"
    params = {"instrument_key": underlying_key, "expiry_date": expiry_date}
    resp = requests.get(url, headers=HEADERS, params=params)
    resp.raise_for_status()
    return resp.json()["data"]


def select_strikes(chain_data, spot_price, strike_range):
    """
    Fixed count-க்கு பதிலா, spot price ± strike_range points range-க்குள்
    வர்ற strikes மட்டும் select பண்ணும்:
    - CE OTM = spot-க்கு மேல (spot, spot+range]
    - CE ITM = spot-க்கு கீழ் [spot-range, spot)
    - PE OTM = spot-க்கு கீழ் [spot-range, spot)
    - PE ITM = spot-க்கு மேல் (spot, spot+range]
    (ITM/OTM திசை Call/Put-க்கு எதிர் எதிர் என்பதால இப்படி தனித்தனியா)
    """
    strikes = sorted(chain_data, key=lambda x: x["strike_price"])

    upper_band = [s for s in strikes if spot_price < s["strike_price"] <= spot_price + strike_range]
    lower_band = [s for s in strikes if spot_price - strike_range <= s["strike_price"] <= spot_price]

    ce_otm = upper_band
    ce_itm = lower_band
    pe_otm = lower_band
    pe_itm = upper_band

    return ce_otm, ce_itm, pe_otm, pe_itm


def capture_baseline_for_symbol(symbol_name, symbol_config, contract_type, weekly, baseline, is_mcx=False):
    if is_mcx:
        underlying_key = get_mcx_futures_instrument_key(symbol_name)
    else:
        underlying_key = symbol_config["underlying_key"]

    print(f"[TRY] {symbol_name}_{contract_type} - underlying_key='{underlying_key}'")

    spot = get_spot_price(underlying_key)
    expiry = get_nearest_expiry(underlying_key, weekly=weekly)
    chain_data = fetch_option_chain(underlying_key, expiry)

    ce_otm, ce_itm, pe_otm, pe_itm = select_strikes(
        chain_data, spot, symbol_config["strike_range"]
    )

    key = f"{symbol_name}_{contract_type}"
    baseline[key] = {}

    def store_strikes(strike_list, opt_field, opt_label, moneyness):
        for s in strike_list:
            if opt_field in s and s[opt_field]:
                sym = s[opt_field]["instrument_key"]
                premium = s[opt_field]["market_data"]["ltp"]
                baseline[key][sym] = {
                    "premium": premium,
                    "strike": s.get("strike_price"),
                    "option_type": opt_label,
                    "moneyness": moneyness,
                }

    store_strikes(ce_otm, "call_options", "CE", "OTM")
    store_strikes(ce_itm, "call_options", "CE", "ITM")
    store_strikes(pe_otm, "put_options", "PE", "OTM")
    store_strikes(pe_itm, "put_options", "PE", "ITM")

    baseline[key + "_expiry"] = expiry

    print(
        f"[BASELINE SET] {key} - CE(OTM {len(ce_otm)}, ITM {len(ce_itm)}) "
        f"PE(OTM {len(pe_otm)}, ITM {len(pe_itm)}), expiry {expiry}"
    )


def main():
    baseline = {}

    for name, cfg in INDICES.items():
        if cfg["has_weekly"]:
            capture_baseline_for_symbol(name, cfg, "WEEKLY", True, baseline)
        if cfg["has_monthly"]:
            capture_baseline_for_symbol(name, cfg, "MONTHLY", False, baseline)

    # MCX commodities - Upstox API currently option chain support MCX-க்கு இல்லாததால
    # (Upstox official docs: "Option chain currently not available for MCX Exchange"),
    # இப்போதைக்கு DISABLE பண்ணிருக்கோம். பின்னாடி வேற data source (Opstra/Quantsapp)
    # வெச்சு separate-ஆ approach பண்ணலாம்.
    # for name, cfg in MCX_COMMODITIES.items():
    #     capture_baseline_for_symbol(name, cfg, "MONTHLY", False, baseline, is_mcx=True)

    with open(BASELINE_FILE, "w") as f:
        json.dump(baseline, f, indent=2)

    print(f"Baseline capture முடிந்தது. {BASELINE_FILE} save ஆனது.")


if __name__ == "__main__":
    main()
