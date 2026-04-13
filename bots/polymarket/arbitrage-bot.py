import os
import time
import json
import requests
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs

# Load environment variables
load_dotenv()

CONFIG_FILE = "arbitrage-bot.json"

def check_config():
    """Reads JSON config for live control."""
    try:
        if not os.path.exists(CONFIG_FILE):
            return {"paused": False}
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ Config Error: {e}")
        return {"paused": False}

def get_authenticated_client():
    """Initializes the client for Google/Magic Link users."""
    pk = os.getenv("PRIVATE_KEY")
    proxy = os.getenv("PROXY_ADDRESS") 

    print(f"🔗 Authenticating for Proxy Wallet: {proxy[:10] if proxy else 'None'}...")

    client = ClobClient(
        host=os.getenv("CLOB_API_URL"),
        key=pk,
        chain_id=int(os.getenv("CHAIN_ID")),
        signature_type=1,  # CRITICAL: Signature type 1 is for Google/Magic users
        funder=proxy       # CRITICAL: This is the address that holds your USDC
    )
    
    # Set L2 API Credentials
    creds = client.create_or_derive_api_creds()
    client.set_api_creds(creds)
    return client

def get_active_markets():
    """Fetches high-volume active events and extracts Token IDs."""
    url = "https://gamma-api.polymarket.com/events"
    params = {"active": "true", "closed": "false", "limit": 25, "order": "volume_24hr"}
    
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

def execute_trade(client, token_id, amount, current_price):
    """Executes a buy order. Corrects size math based on desired USDC spend."""
    try:
        # To spend exactly $1.20, we calculate shares based on current price
        # If price is 0.50, $1.20 buys 2.4 shares.
        shares = amount / current_price if current_price > 0 else 0
        
        order_args = OrderArgs(
            token_id=token_id,
            price=0.99, # Fills at best available price up to $0.99
            side="BUY",
            size=round(shares, 2) 
        )
        signed_order = client.create_order(order_args)
        resp = client.post_order(signed_order)
        return resp
    except Exception as e:
        print(f"🚨 Order Failed: {e}")
        return None

def run_bot():
    try:
        client = get_authenticated_client()
    except Exception as e:
        print(f"Initialization Failed: {e}")
        return

    print("--- 🚀 Polymarket Arbitrage Bot Active ---")
    
    while True:
        config = check_config()
        if config.get("emergency_stop"):
            print("🛑 EMERGENCY STOP. Exiting...")
            break
            
        markets = get_active_markets()
        print(f"\nScanning {len(markets)} markets...")
        
        for m in markets:
            # Internal check for zero-latency pausing
            config = check_config() 
            if config.get("paused"):
                print("⏸️ Bot is PAUSED. Standing by...")
                while check_config().get("paused"):
                    time.sleep(2)
                print("▶️ Resuming...")
                config = check_config()

            try:
                threshold = config.get("min_profit_margin_override") or float(os.getenv("MIN_PROFIT_MARGIN", 0.01))
                amount = config.get("max_trade_usdc_override") or float(os.getenv("MAX_TRADE_USDC", 1.2))

                # Fetch best Buy prices
                y_p = float(client.get_price(m['yes_id'], side="BUY")['price'])
                n_p = float(client.get_price(m['no_id'], side="BUY")['price'])
                
                total = y_p + n_p
                if total < (1.0 - threshold):
                    print(f"💰 ARB FOUND! Sum: {total:.3f} | {m['question']}")
                    execute_trade(client, m['yes_id'], amount, y_p)
                    execute_trade(client, m['no_id'], amount, n_p)
                else:
                    print(f"❌ {total:.3f} | {m['question'][:45]}...")
            except: 
                continue
            
        time.sleep(int(os.getenv("SCAN_INTERVAL", 10)))

if __name__ == "__main__":
    try:
        run_bot()
    except KeyboardInterrupt:
        print("\n👋 Bot stopped manually.")