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
    """Reads the JSON config file for dynamic updates."""
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"🚨 Config Error: {e}")
        return None

def get_authenticated_client():
    """Initializes the Polymarket CLOB client."""
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
    """Calculates the current 5-min window Unix timestamp."""
    return (int(time.time()) // 300) * 300

def get_btc_market_data(window_ts):
    """Fetches token IDs for the specific 5m BTC market slug."""
    slug = f"btc-updown-5m-{window_ts}"
    url = f"https://gamma-api.polymarket.com/events?slug={slug}"
    try:
        resp = requests.get(url).json()
        if not resp or "markets" not in resp[0]: return None
        market = resp[0]["markets"][0]
        ids = json.loads(market["clobTokenIds"])
        return {
            "up": ids[0], 
            "down": ids[1], 
            "question": market.get("groupItemTitle") or resp[0].get("title")
        }
    except:
        return None

def get_binance_price():
    """Fetches live BTC price for telemetry logs."""
    try:
        url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDC"
        return float(requests.get(url).json()['price'])
    except:
        return 0.0

def run_btc_bot():
    global trades_completed, last_traded_window
    
    client = get_authenticated_client()
    print("--- 🏎️ BTC 5-Min Sniper [Analytics Mode] ---")
    
    while True:
        config = load_config()
        if not config: 
            time.sleep(5)
            continue

        # 1. TRADE LIMIT CHECK
        if trades_completed >= config["max_trades_allowed"]:
            print(f"🏁 Max trades reached ({trades_completed}). Stopping bot.")
            break

        now_ts = int(time.time())
        window_ts = get_current_btc_window()
        seconds_into_window = now_ts % 300
        countdown = 280 - seconds_into_window

        # 2. HEARTBEAT TELEMETRY (Every 10 seconds)
        if seconds_into_window % 10 == 0:
            btc_price = get_binance_price()
            mode = "🧪 PAPER" if config["paper_trading"] else "💰 LIVE"
            status = "🔥 SNIPE ZONE" if countdown <= 0 else f"Waiting ({countdown}s)"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] BTC: ${btc_price:,.2f} | {status} | Mode: {mode}")

        # 3. PREVENT DOUBLE-TRADING THE SAME WINDOW
        if window_ts == last_traded_window:
            time.sleep(1); continue

        # 4. THE SNIPE ZONE (Last 20 seconds of the window)
        if 280 <= seconds_into_window <= 298:
            m_data = get_btc_market_data(window_ts)
            if not m_data:
                time.sleep(1); continue
                
            try:
                # Check current market pricing
                up_price = float(client.get_price(m_data["up"], side="BUY")['price'])
                
                # Logic: Snipe the 'UP' token if it's below our profit gap
                if up_price < (1.0 - config["min_profit_gap"]):
                    
                    # --- CALCULATION LOGIC ---
                    shares_to_buy = round(config["target_spend_usd"] / up_price, 1)
                    if shares_to_buy < 1: shares_to_buy = 1.0
                    
                    total_spent = round(shares_to_buy * up_price, 2)
                    potential_payout = round(shares_to_buy * 1.0, 2)
                    potential_profit = round(potential_payout - total_spent, 2)
                    roi = round((potential_profit / total_spent) * 100, 1)

                    print(f"\n🎯 Snipe Triggered! [{m_data['question']}]")
                    print(f"   💵 Price: ${up_price} | Shares: {shares_to_buy}")
                    print(f"   📊 Est. Cost: ${total_spent} | Potential Payout: ${potential_payout}")
                    print(f"   📈 Potential Profit: ${potential_profit} ({roi}% ROI)")
                    
                    if not config["paper_trading"]:
                        order = OrderArgs(
                            token_id=m_data["up"], 
                            price=0.99, 
                            side="BUY", 
                            size=shares_to_buy
                        )
                        client.post_order(client.create_order(order))
                        print("   ✅ LIVE Order Sent.")
                    else:
                        print("   🧪 PAPER Trade Recorded (No funds moved).")
                    
                    trades_completed += 1
                    last_traded_window = window_ts
                    print(f"   🏁 Trade {trades_completed}/{config['max_trades_allowed']} complete.\n")
                    
            except Exception as e:
                print(f"⚠️ Market Error: {e}")

        time.sleep(1) 

if __name__ == "__main__":
    try:
        run_btc_bot()
    except KeyboardInterrupt:
        print("\n👋 Sniper stopped.")