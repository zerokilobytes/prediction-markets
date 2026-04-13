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
trades_completed = 0

def check_config():
    """Reads JSON config for live control with updated defaults."""
    # Python booleans must be Capitalized
    defaults = {
        "paused": False, 
        "paper_trading": True, 
        "max_trades_allowed": 1,
        "scan_interval": 10,
        "min_profit_margin": 0.01,
        "max_trade_usdc": 1.2,
        "emergency_stop": False
    }
    try:
        if not os.path.exists(CONFIG_FILE):
            return defaults
        with open(CONFIG_FILE, 'r') as f:
            # Merges the JSON file on top of the Python defaults
            return {**defaults, **json.load(f)}
    except Exception as e:
        print(f"⚠️ Config Error: {e}")
        return defaults

def get_authenticated_client():
    """Initializes the client using .env credentials."""
    pk = os.getenv("PRIVATE_KEY")
    proxy = os.getenv("PROXY_ADDRESS") 
    print(f"🔗 Authenticating for Proxy Wallet: {proxy[:10] if proxy else 'None'}...")
    
    client = ClobClient(
        host=os.getenv("CLOB_API_URL"),
        key=pk,
        chain_id=int(os.getenv("CHAIN_ID")),
        signature_type=1,
        funder=proxy
    )
    
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
                        "yes_id": ids[0], "no_id": ids[1]
                    })
        return valid_markets
    except Exception: return []

def execute_trade(client, token_id, amount, is_paper):
    """Executes a buy order or simulates it."""
    if is_paper:
        print(f"📝 [PAPER] Simulating Buy: {amount} USDC on {token_id[:8]}")
        return {"success": True}
        
    try:
        limit_price = 0.99
        shares = amount / limit_price 
        order_args = OrderArgs(
            token_id=token_id,
            price=limit_price, 
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
    global trades_completed
    try:
        client = get_authenticated_client()
    except Exception as e:
        print(f"Initialization Failed: {e}")
        return

    print("--- 🚀 Polymarket Arbitrage Bot Active ---")
    
    while True:
        # Load fresh config at start of scan
        config = check_config()
        is_paper = config.get("paper_trading", True)
        max_allowed = config.get("max_trades_allowed", 1)
        wait_time = config.get("scan_interval", 10)

        if config.get("emergency_stop"):
            print("🛑 EMERGENCY STOP. Exiting...")
            break

        if trades_completed >= max_allowed:
            print(f"🏁 Session limit reached ({trades_completed}/{max_allowed}).")
            break
            
        markets = get_active_markets()
        mode_label = "🧪 PAPER MODE" if is_paper else "💰 LIVE MODE"
        print(f"\nScanning {len(markets)} markets... [{mode_label} | {trades_completed}/{max_allowed}]")
        
        for m in markets:
            config = check_config() 
            if config.get("paused"):
                print("⏸️ Bot is PAUSED. Standing by...")
                while check_config().get("paused"):
                    time.sleep(2)
                print("▶️ Resuming...")

            try:
                threshold = config.get("min_profit_margin", 0.01)
                amount = config.get("max_trade_usdc", 1.2)

                y_p = float(client.get_price(m['yes_id'], side="BUY")['price'])
                n_p = float(client.get_price(m['no_id'], side="BUY")['price'])
                
                total = y_p + n_p
                if total < (1.0 - threshold):
                    print(f"💰 ARB FOUND! Sum: {total:.3f} | {m['question']}")
                    
                    res_y = execute_trade(client, m['yes_id'], amount, is_paper)
                    res_n = execute_trade(client, m['no_id'], amount, is_paper)
                    
                    if res_y and res_n:
                        trades_completed += 1
                        print(f"✅ Trade {trades_completed} logged.")
                        
                        if trades_completed >= max_allowed:
                            print(f"🏁 Limit hit ({trades_completed}). Ending scan.")
                            return 
                else:
                    pass 
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                continue
            
        time.sleep(wait_time)

if __name__ == "__main__":
    try:
        run_bot()
    except KeyboardInterrupt:
        print("\n👋 Bot stopped manually via Ctrl+C.")