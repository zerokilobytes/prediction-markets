import os
import time
import json
import requests
from datetime import datetime
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs

load_dotenv()

CONFIG_FILE = "btc-bot-config.json"
trades_completed = 0
last_traded_window = 0

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"🚨 Config Error: {e}")
        return None

def get_authenticated_client():
    client = ClobClient(
        host=os.getenv("CLOB_API_URL"),
        key=os.getenv("PRIVATE_KEY"),
        chain_id=int(os.getenv("CHAIN_ID")),
        signature_type=1,
        funder=os.getenv("PROXY_ADDRESS")
    )
    client.set_api_creds(client.create_or_derive_api_creds())
    return client

def get_current_btc_window():
    return (int(time.time()) // 300) * 300

def get_btc_market_data(window_ts):
    slug = f"btc-updown-5m-{window_ts}"
    url = f"https://gamma-api.polymarket.com/events?slug={slug}"
    try:
        resp = requests.get(url).json()
        if not resp or "markets" not in resp[0]: return None
        market = resp[0]["markets"][0]
        ids = json.loads(market["clobTokenIds"])
        return {"up": ids[0], "down": ids[1], "question": market.get("groupItemTitle")}
    except: return None

def get_binance_price():
    try:
        url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDC"
        return float(requests.get(url).json()['price'])
    except: return 0.0

def run_btc_bot():
    global trades_completed, last_traded_window
    client = get_authenticated_client()
    print("--- 🎰 BTC Lottery Sniper [v2.0 Fixed] ---")
    
    while True:
        config = load_config()
        if not config or trades_completed >= config["max_trades_allowed"]:
            if trades_completed >= config.get("max_trades_allowed", 0):
                print(f"🏁 Target trades reached ({trades_completed}).")
                break
            time.sleep(5); continue

        now_ts = int(time.time())
        window_ts = get_current_btc_window()
        seconds_into_window = now_ts % 300
        countdown = 280 - seconds_into_window

        if seconds_into_window % 10 == 0:
            btc_price = get_binance_price()
            mode = "🧪 PAPER" if config["paper_trading"] else "💰 LIVE"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] BTC: ${btc_price:,.2f} | Snipe in: {max(0, countdown)}s | Mode: {mode}")

        if window_ts == last_traded_window:
            time.sleep(1); continue

        # SNIPE ZONE
        if 280 <= seconds_into_window <= 298:
            m_data = get_btc_market_data(window_ts)
            if not m_data: continue
            
            try:
                # Fetch current ask prices
                up_price = float(client.get_price(m_data["up"], side="BUY")['price'])
                down_price = float(client.get_price(m_data["down"], side="BUY")['price'])
                
                target_token, target_price = None, 0
                
                if 0 < up_price <= config["max_buy_price"]:
                    target_token, target_price = m_data["up"], up_price
                elif 0 < down_price <= config["max_buy_price"]:
                    target_token, target_price = m_data["down"], down_price

                # Check for "Division by Zero" crash
                if target_token and target_price > 0:
                    shares_to_buy = round(config["target_spend_usd"] / target_price, 1)
                    if shares_to_buy < 1: shares_to_buy = 1.0

                    # LOGGING
                    total_spent = round(shares_to_buy * target_price, 2)
                    potential_win = round(shares_to_buy * 1.0, 2)
                    print(f"\n🎯 Snipe Found! Price: ${target_price} | Cost: ${total_spent} | Payout: ${potential_win}")

                    if not config["paper_trading"]:
                        # THE BALANCE FIX:
                        # Don't use 0.99. Use market price + a small buffer (0.01).
                        # This tells the exchange "I'll pay up to $X", preventing 
                        # it from locking your entire wallet for one trade.
                        safety_limit = min(0.99, target_price + 0.01)
                        
                        order = OrderArgs(
                            token_id=target_token, 
                            price=safety_limit, 
                            side="BUY", 
                            size=shares_to_buy
                        )
                        client.post_order(client.create_order(order))
                        print(f"   ✅ LIVE Order Sent (Limit: ${safety_limit})")
                    else:
                        print("   🧪 PAPER Trade Recorded.")
                    
                    trades_completed += 1
                    last_traded_window = window_ts
                    print(f"   🏁 {trades_completed}/{config['max_trades_allowed']} complete.\n")
                    
            except Exception as e:
                # Catch zero division or empty order books silently
                if "float division by zero" not in str(e):
                    print(f"⚠️ Market Error: {e}")

        time.sleep(1)

if __name__ == "__main__":
    run_btc_bot()