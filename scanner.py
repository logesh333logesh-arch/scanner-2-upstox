"""
Scanner 2: Options Premium Spike Scanner (v2 — rolling reference)
--------------------------------------------------------------------
Logic:
1. Market open (9:16 AM) ஆனதும் ஒரு தடவை run ஆகி, ஒவ்வொரு index/commodity-க்கும்
   ATM strike கண்டுபிடிச்சு, அதுக்கு மேல 10 OTM CE + 10 OTM PE strikes-ன்
   OPENING premium-ஐ baseline-ஆ JSON file-ல save பண்ணும். (baseline_capture.py)
   -- இந்த baseline இப்போ strike SELECTION-க்கு மட்டும் use ஆகும்
      (எந்த strikes track பண்ணணும்), spike COMPARISON-க்கு இல்ல.

2. அதுக்கு அப்புறம் ஒவ்வொரு run-லயும் (cron every N mins), current premium-ஐ
   *இந்த run-க்கு* முந்தைய run-ல save பண்ணின premium-உடன் (rolling reference)
   compare பண்ணி, spike threshold தாண்டினா Telegram alert அனுப்பும்.
   -- இது day-open fixed baseline-க்கு பதிலா, ரொலிங் 1-run-முன்ன reference
      வெச்சு, spike-ஐ அது நடக்கும் போதே catch பண்ணும் (delay குறைவு).

3. reference_premiums.json-ல ஒவ்வொரு strike-ஓட கடைசி-பார்த்த premium +
   timestamp வெச்சுக்கும். ஒவ்வொரு run முடிவுலயும் இது update ஆகி, repo-க்கு
   commit+push ஆகணும் (workflow file-ல step சேர்க்கப்பட்டிருக்கும்).

4. "ஒரு strike ஒரு தடவை மட்டும் alert" logic நீக்கப்பட்டது — rolling
   reference model-ல ஒவ்வொரு run-மும் reference தானாகவே முன்னேறுதால்,
   தொடர்ந்து பெரிய moves வந்தா தொடர்ந்து alert வரும் (spam ஆகாது, ஏன்னா
   ஒவ்வொரு அடுத்த run-க்கும் ஒரு புது, பெரிய move தேவை).
"""

import os
import json
import requests
from datetime import datetime, timezone
import pytz

from config import INDICES, MCX_COMMODITIES, BASELINE_FILE, ALERTED_FILE

UPSTOX_ACCESS_TOKEN = os.environ["UPSTOX_ACCESS_TOKEN"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

IST = pytz.timezone("Asia/Kolkata")
HEADERS = {
    "Authorization": f"Bearer {UPSTOX_ACCESS_TOKEN}",
    "Accept": "application/json",
}

# Rolling reference file — replaces the fixed day-open baseline as the
# spike-comparison anchor. BASELINE_FILE is still used, but only to know
# WHICH strikes to track (selected once at market open).
PRICE_HISTORY_FILE = "reference_premiums.json"
MAX_REFERENCE_AGE_MINUTES = 30  # if last saved price is older than this, re-seed instead of comparing


# -----------------------------------------------------------
# Step 1: Option chain fetch பண்றது (Upstox Option Chain API)
# -----------------------------------------------------------
def fetch_option_chain(underlying_key, expiry_date):
    """
    Upstox /option/chain endpoint - ஒரு underlying + expiry-க்கு
    எல்லா strikes-ன் CE/PE data (LTP உட்பட) கொடுக்கும்.
    """
    url = "https://api.upstox.com/v2/option/chain"
    params = {"instrument_key": underlying_key, "expiry_date": expiry_date}
    resp = requests.get(url, headers=HEADERS, params=params)
    resp.raise_for_status()
    return resp.json()["data"]


# -----------------------------------------------------------
# Step 2: ATM கண்டுபிடிச்சு, அதுக்கு மேல N OTM strikes select பண்றது
# -----------------------------------------------------------
def select_otm_strikes(chain_data, spot_price, num_strikes):
    """
    chain_data ல ஒவ்வொரு entry-லயும் strike_price இருக்கும்.
    ATM = spot price-க்கு மிக அருகான strike.
    அதுக்கு மேல (higher) இருக்கிற num_strikes எடுக்கறோம்
    (CE-க்கு OTM = ATM-க்கு மேல, PE-க்கு OTM = ATM-க்கு கீழ் — ஆனா
    உங்க requirement படி 'ATM-க்கு மேல இருக்கிற 10' எடுக்கறோம், CE & PE ரெண்டுக்கும்).
    """
    strikes = sorted(chain_data, key=lambda x: x["strike_price"])
    atm_index = min(
        range(len(strikes)),
        key=lambda i: abs(strikes[i]["strike_price"] - spot_price),
    )
    selected = strikes[atm_index: atm_index + num_strikes]
    return selected


# -----------------------------------------------------------
# Step 3: Baseline (strike selection) + rolling reference (comparison anchor)
# -----------------------------------------------------------
def load_baseline():
    if not os.path.exists(BASELINE_FILE):
        raise FileNotFoundError(
            f"{BASELINE_FILE} கிடைக்கல. Market open-ல baseline_capture.py "
            "run ஆகி இருக்கணும் — அது இல்லாம எந்த strikes track பண்ணணும்னு தெரியாது."
        )
    with open(BASELINE_FILE, "r") as f:
        return json.load(f)


def load_price_history():
    if not os.path.exists(PRICE_HISTORY_FILE):
        return {}
    try:
        with open(PRICE_HISTORY_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_price_history(history):
    with open(PRICE_HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def get_reference(history, ref_key):
    """Returns (reference_premium, age_minutes) or None if no usable
    (not-too-stale) saved price exists for this strike."""
    entry = history.get(ref_key)
    if not entry:
        return None
    try:
        saved_time = datetime.fromisoformat(entry["timestamp"])
        age_minutes = (datetime.now(timezone.utc) - saved_time).total_seconds() / 60
    except (KeyError, ValueError):
        return None
    if age_minutes > MAX_REFERENCE_AGE_MINUTES:
        return None
    return entry["premium"], age_minutes


def update_reference(history, ref_key, premium):
    history[ref_key] = {
        "premium": premium,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# -----------------------------------------------------------
# Step 4: Telegram alert அனுப்றது
# -----------------------------------------------------------
def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    # parse_mode Markdown எடுத்துடுறோம் - strike symbols-ல '_' '|' போன்ற
    # characters இருக்கும், அது Markdown-ஐ confuse பண்ணி 400 error தரும்.
    # Plain text-ஆ அனுப்பினா எந்த character வந்தாலும் problem வராது.
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    resp = requests.post(url, json=payload)
    resp.raise_for_status()


# -----------------------------------------------------------
# Step 5: ஒவ்வொரு index/commodity-க்கும் spike check பண்றது
# -----------------------------------------------------------
def check_spikes_for_symbol(symbol_name, symbol_config, contract_type, baseline, history):
    """
    contract_type = "WEEKLY" or "MONTHLY" (indices-க்கு), or "MONTHLY" (MCX-க்கு)
    """
    key = f"{symbol_name}_{contract_type}"
    if key not in baseline:
        print(f"[SKIP] {key} - baseline இல்ல")
        return

    threshold = symbol_config["spike_threshold"]
    strikes_baseline = baseline[key]  # { "NSE_FO|12345": {...}, ... } - key is instrument_key
    expiry_used = baseline.get(key + "_expiry", "N/A")

    # Current premiums fetch பண்ணு (option chain call)
    chain_data = fetch_option_chain(
        symbol_config["underlying_key"], expiry_used
    )

    # chain_data-ல இருந்து instrument_key -> current LTP dictionary build பண்ணு
    current_ltp_by_key = {}
    for c in chain_data:
        for opt_type in ["call_options", "put_options"]:
            if opt_type in c and c[opt_type]:
                ik = c[opt_type].get("instrument_key")
                ltp = c[opt_type].get("market_data", {}).get("ltp")
                if ik is not None:
                    current_ltp_by_key[ik] = ltp

    for strike_symbol, strike_info in strikes_baseline.items():
        if strike_symbol.endswith("_expiry"):
            continue

        strike_price = strike_info["strike"]
        option_type = strike_info["option_type"]
        moneyness = strike_info.get("moneyness", "OTM")

        current_premium = current_ltp_by_key.get(strike_symbol)
        if current_premium is None:
            print(f"[NO MATCH] {strike_symbol} - current chain data-ல இந்த instrument_key கிடைக்கல")
            continue

        ref_key = f"{key}_{strike_symbol}"
        ref = get_reference(history, ref_key)

        # ஒவ்வொரு run-லயும் reference-ஐ இப்போதைக்கு current premium-ஆ
        # முன்னேற்றி வெக்கறோம் — rolling window தொடர்ந்து நகரும்.
        update_reference(history, ref_key, current_premium)

        if ref is None:
            # முதல் run (இன்னைக்கு) அல்லது run gap ஆல reference stale —
            # இப்போ seed பண்றோம் மட்டும், இந்த run-ல compare பண்ண ஒண்ணும் இல்ல.
            print(f"[SEED] {key} | Strike {strike_price} {option_type} | reference seeded @ ₹{current_premium}")
            continue

        reference_premium, age_minutes = ref
        spike = current_premium - reference_premium
        print(
            f"[CHECK] {key} | Strike {strike_price} {option_type} | ref({age_minutes:.0f}m ago)=₹{reference_premium} "
            f"current=₹{current_premium} spike=₹{round(spike,2)} threshold=₹{threshold}"
        )

        if spike >= threshold:
            # CE/PE மற்றும் Weekly/Monthly-க்கு தனி emoji - ஒரே பார்வையில
            # அடையாளம் தெரிய (பச்சை=Call, சிவப்பு=Put)
            option_emoji = "🟢" if option_type == "CE" else "🔴"
            contract_emoji = "⏳" if contract_type == "WEEKLY" else "📅"
            moneyness_emoji = "ℹ️" if moneyness == "ITM" else "🅾️"
            index_emoji = {
                "NIFTY": "💸",
                "BANKNIFTY": "🏛️",
                "SENSEX": "💰",
                "FINNIFTY": "🧷",
            }.get(symbol_name, "⚪")
            msg = (
                f"🚨 Premium Spike Alert\n"
                f"Index: {index_emoji} {symbol_name}\n"
                f"Contract: {contract_emoji} {contract_type}\n"
                f"Strike: {strike_price} {option_emoji} {option_type} ({moneyness_emoji} {moneyness})\n"
                f"Expiry: {expiry_used}\n"
                f"Reference Premium ({age_minutes:.0f}m ago): ₹{reference_premium}\n"
                f"Current Premium: ₹{current_premium}\n"
                f"Spike: ₹{round(spike, 2)} (Threshold: ₹{threshold})"
            )
            send_telegram_alert(msg)
            print(f"[ALERT SENT] {symbol_name} {strike_price}{option_type} - spike ₹{spike}")


# -----------------------------------------------------------
# Main
# -----------------------------------------------------------
def main():
    now = datetime.now(IST)
    print(f"Scanner run started: {now}")

    baseline = load_baseline()
    history = load_price_history()

    for name, cfg in INDICES.items():
        if cfg["has_weekly"]:
            check_spikes_for_symbol(name, cfg, "WEEKLY", baseline, history)
        if cfg["has_monthly"]:
            check_spikes_for_symbol(name, cfg, "MONTHLY", baseline, history)

    # MCX commodities - Upstox option chain API MCX-க்கு support இல்லாததால DISABLE
    # for name, cfg in MCX_COMMODITIES.items():
    #     check_spikes_for_symbol(name, cfg, "MONTHLY", baseline, history)

    save_price_history(history)
    print("Scanner run முடிந்தது.")


if __name__ == "__main__":
    main()
