import os
import time
import json
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs

# Load environment variables
load_dotenv()

CONFIG_FILE = "arbitrage-bot.json"
TRADE_LOG = "arbitrage-bot-trades.json"
trades_completed = 0

def check_config():
    """Reads JSON config. If file is missing or broken, bot stops for safety."""
    try:
        if not os.path.exists(CONFIG_FILE):
            print(f"🚨 CRITICAL: {CONFIG_FILE} not found!")
            return {"emergency_stop": True}
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"🚨 Config Error: {e}")
        return {"emergency_stop": True}

def get_trade_history():
    """Loads the list of past trades from JSON."""
    if not os.path.exists(TRADE_LOG):
        return []
    try:
        with open(TRADE_LOG, 'r') as f:
            return json.load(f)
    except:
        return []

def has_traded_before(question):
    """Checks history to prevent duplicate trades."""
    history = get_trade_history()
    return any(trade['question'] == question for trade in history)

def log_trade_json(market_data, total_sum, y_p, n_p, amount):
    """Logs detailed trade data to the JSON file."""
    history = get_trade_history()
    new_entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "question": market_data['question'],
        "market_end_date": market_data['end_date'],
        "buy_price_yes": y_p,
        "buy_price_no": n_p,
        "total_cost_per_share": round(total_sum, 4),
        "expected_profit_per_share": round(1.0 - total_sum, 4),
        "usdc_spent_total": round(amount * 2, 2)
    }
    history.append(new_entry)
    with open(TRADE_LOG, 'w') as f:
        json.dump(history, f, indent=4)

def get_authenticated_client():
    """Initializes the client using .env credentials."""
    pk = os.getenv("PRIVATE_KEY")
    proxy = os.getenv("PROXY_ADDRESS") 
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

def get_active_markets(max_days):
    """Fetches and filters markets based on ending date."""
    url = "https://gamma-api.polymarket.com/events"
    params = {"active": "true", "closed": "false", "limit": 50, "order": "volume_24hr"}
    valid_markets = []
    cutoff_date = datetime.now() + timedelta(days=max_days)
    
    try:
        resp = requests.get(url, params=params).json()
        for event in resp:
            end_date_str = event.get("endDate")
            if end_date_str:
                clean_date = end_date_str.split('T')[0]
                end_date = datetime.strptime(clean_date, "%Y-%m-%d")
                if end_date > cutoff_date:
                    continue

            for market in event.get("markets", []):
                ids = market.get("clobTokenIds")
                if isinstance(ids, str): ids = json.loads(ids)
                if ids and len(ids) == 2:
                    valid_markets.append({
                        "question": market.get("groupItemTitle") or event.get("title"),
                        "yes_id": ids[0], 
                        "no_id": ids[1],
                        "end_date": end_date_str
                    })
        return valid_markets
    except Exception: return []

def execute_trade(client, token_id, amount, is_paper):
    """Executes a buy order or simulates it."""
    if is_paper:
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
        return client.post_order(signed_order)
    except Exception:
        return None

def run_bot():
    global trades_completed
    try:
        client = get_authenticated_client()
    except Exception as e:
        print(f"Initialization Failed: {e}")
        return

    print(f"--- 🚀 Arb Bot Active (Monitoring {CONFIG_FILE}) ---")
    
    while True:
        config = check_config()
        
        # Kill switch
        if config.get("emergency_stop"):
            print("🛑 STOPPED via Config or Missing File.")
            break

        is_paper = config.get("paper_trading")
        max_allowed = config.get("max_trades_allowed")
        wait_time = config.get("scan_interval")

        if trades_completed >= max_allowed:
            print(f"🏁 Limit reached ({trades_completed}/{max_allowed}).")
            break
            
        markets = get_active_markets(config.get("max_days_until_resolution"))
        mode_label = "🧪 PAPER MODE" if is_paper else "💰 LIVE MODE"
        print(f"\nScanning {len(markets)} markets... [{mode_label} | {trades_completed}/{max_allowed}]")
        
        for m in markets:
            config = check_config() # Real-time check
            if config.get("paused"):
                time.sleep(2)
                continue
            
            if has_traded_before(m['question']):
                continue

            try:
                amount = config.get("max_trade_usdc")
                y_p = float(client.get_price(m['yes_id'], side="BUY")['price'])
                n_p = float(client.get_price(m['no_id'], side="BUY")['price'])
                total = y_p + n_p

                if total < (1.0 - config.get("min_profit_margin")):
                    print(f"💰 ARB FOUND: {total:.3f} | {m['question']}")
                    
                    res_y = execute_trade(client, m['yes_id'], amount, is_paper)
                    res_n = execute_trade(client, m['no_id'], amount, is_paper)
                    
                    if res_y and res_n:
                        trades_completed += 1
                        log_trade_json(m, total, y_p, n_p, amount)
                        print(f"✅ Trade {trades_completed} logged.")
                        
                        if trades_completed >= max_allowed:
                            return 
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                continue
            
        time.sleep(wait_time)

if __name__ == "__main__":
    try:
        run_bot()
    except KeyboardInterrupt:
        print("\n👋 Stopped.")