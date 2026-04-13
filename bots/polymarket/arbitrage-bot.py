import os
import time
import json
import requests
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs

load_dotenv()

CONFIG_FILE = "arbitrage-bot.json"

def check_config():
    """Reads JSON config to handle live pausing/stops."""
    try:
        if not os.path.exists(CONFIG_FILE):
            return {"paused": False}
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ Config Error: {e}")
        return {"paused": False}

def get_authenticated_client():
    """Initializes the Polymarket CLOB client with L2 credentials."""
    pk = os.getenv("PRIVATE_KEY")
    client = ClobClient(
        host=os.getenv("CLOB_API_URL"),
        key=pk,
        chain_id=int(os.getenv("CHAIN_ID"))
    )
    # Derive and set API credentials for signing orders
    creds = client.create_or_derive_api_creds()
    client.set_api_creds(creds)
    return client

def get_active_markets():
    """Fetches high-volume active events and extracts Token IDs."""
    url = "https://gamma-api.polymarket.com/events"
    params = {"active": "true", "closed": "false", "limit": 20, "order": "volume_24hr"}
    valid_markets = []
    try:
        resp = requests.get(url, params=params).json()
        for event in resp:
            for market in event.get("markets", []):
                ids = market.get("clobTokenIds")
                if isinstance(ids, str): ids = json.loads(ids)
                if ids and len(ids) == 2:
                    valid_markets.append({
                        "question": market.get("groupItemTitle") or event.get("title"),
                        "yes_id": ids[0], 
                        "no_id": ids[1]
                    })
        return valid_markets
    except: return []

def execute_trade(client, token_id, amount):
    """Robust order placement using the standard create/post workflow."""
    try:
        # We use a high price limit (0.99) to simulate a Market Order
        order_args = OrderArgs(
            token_id=token_id,
            price=0.99, 
            side="BUY",
            size=amount / 0.5 # Share estimation; adjust based on liquidity/size requirements
        )
        signed_order = client.create_order(order_args)
        resp = client.post_order(signed_order)
        return resp
    except Exception as e:
        print(f"🚨 Order Failed for {token_id[:8]}: {e}")
        return None

def run_bot():
    client = get_authenticated_client()
    print("--- 🚀 Polymarket Arbitrage Bot Active ---")
    
    while True:
        # Check config at the start of the loop
        config = check_config()
        if config.get("emergency_stop"):
            print("🛑 EMERGENCY STOP. Exiting...")
            break
            
        markets = get_active_markets()
        print(f"\nScanning {len(markets)} markets...")
        
        for m in markets:
            # --- REACTIVE MID-SCAN PAUSE CHECK ---
            config = check_config() 
            if config.get("paused"):
                print("⏸️ Bot is PAUSED. Standing by...")
                while check_config().get("paused"):
                    time.sleep(2) # Poll the JSON every 2 seconds
                print("▶️ Resuming scan...")
                # Re-fetch config after unpausing
                config = check_config()

            try:
                # Use JSON overrides if present, otherwise fallback to .env
                threshold = config.get("min_profit_margin_override") or float(os.getenv("MIN_PROFIT_MARGIN", 0.01))
                amount = config.get("max_trade_usdc_override") or float(os.getenv("MAX_TRADE_USDC", 5.0))

                # Fetch best Buy prices (Asks)
                y_p = float(client.get_price(m['yes_id'], side="BUY")['price'])
                n_p = float(client.get_price(m['no_id'], side="BUY")['price'])
                
                total = y_p + n_p
                if total < (1.0 - threshold):
                    print(f"💰 ARB FOUND! Sum: {total:.3f} | {m['question']}")
                    execute_trade(client, m['yes_id'], amount)
                    execute_trade(client, m['no_id'], amount)
                else:
                    print(f"❌ {total:.3f} | {m['question'][:45]}...")
            except: 
                continue
            
        # Rest between full scanning cycles
        wait_time = int(os.getenv("SCAN_INTERVAL", 10))
        time.sleep(wait_time)

if __name__ == "__main__":
    try:
        run_bot()
    except KeyboardInterrupt:
        print("\n👋 Bot stopped manually.")