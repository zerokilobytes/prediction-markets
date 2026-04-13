import os
import time
import json
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs

# Load environment variables
load_dotenv()

CONFIG_FILE = "arbitrage-bot.json"
TRADE_LOG = "arbitrage-bot-trades.json"
trades_completed = 0

def check_config():
    """Reads JSON config. No defaults - relies entirely on the file."""
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
    """Loads past trades to prevent duplicates."""
    if not os.path.exists(TRADE_LOG):
        return []
    try:
        with open(TRADE_LOG, 'r') as f:
            return json.load(f)
    except:
        return []

def has_traded_before(question):
    history = get_trade_history()
    return any(trade['question'] == question for trade in history)

def log_trade_json(market_data, total_sum, y_p, n_p, final_shares):
    """Logs detailed trade data including the final adjusted share count."""
    history = get_trade_history()
    new_entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "question": market_data['question'],
        "market_end_date": market_data['end_date'],
        "buy_price_yes": y_p,
        "buy_price_no": n_p,
        "total_cost_per_share": round(total_sum, 4),
        "shares_bought": final_shares,
        "total_usdc_spent": round(total_sum * final_shares, 2)
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
    url = "https://gamma-api.polymarket.com/events"
    params = {"active": "true", "closed": "false", "limit": 200, "order": "volume_24hr"}
    valid_markets = []
    
    forbidden_years = ["2027", "2028", "2029", "2030"] # Add years you don't want
    now = datetime.now(timezone.utc)
    cutoff_date = now + timedelta(days=max_days)
    
    try:
        resp = requests.get(url, params=params).json()
        for event in resp:
            for market in event.get("markets", []):
                title = market.get("groupItemTitle") or event.get("title") or ""
                
                # NEW: Keyword block for long-term years
                if any(year in title for year in forbidden_years):
                    continue

                end_date_str = market.get("endDate") 
                if not end_date_str: continue

                try:
                    m_end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                    if now < m_end_date <= cutoff_date:
                        ids = market.get("clobTokenIds")
                        if isinstance(ids, str): ids = json.loads(ids)
                        
                        if ids and len(ids) == 2:
                            valid_markets.append({
                                "question": title,
                                "yes_id": ids[0], "no_id": ids[1],
                                "end_date": end_date_str
                            })
                except ValueError: continue
        return valid_markets
    except Exception as e:
        return []

def execute_trade(client, token_id, share_count, is_paper):
    """Executes trade with a $1.05 USDC minimum floor for cheap shares."""
    if is_paper: return {"success": True, "final_shares": share_count}
    
    try:
        price_data = client.get_price(token_id, side="BUY")
        current_price = float(price_data['price'])
        
        # Polymarket usually requires ~$1.00 minimum order. 
        # If price is $0.05 and count is 1, cost is $0.05 (too low).
        actual_shares = share_count
        if (current_price * share_count) < 1.05:
            actual_shares = round(1.05 / current_price, 2)
            print(f"⚖️ Price {current_price} too low. Boosting to {actual_shares} shares for minimum order.")

        order_args = OrderArgs(
            token_id=token_id,
            price=0.99, # Safety cap
            side="BUY",
            size=float(actual_shares)
        )
        signed_order = client.create_order(order_args)
        resp = client.post_order(signed_order)
        return {"success": True, "final_shares": actual_shares} if resp.get("success") else None
    except Exception as e:
        print(f"🚨 Trade Error: {e}")
        return None

def run_bot():
    global trades_completed
    client = get_authenticated_client()
    print(f"--- 🚀 Arb Bot Active (Floor Logic Enabled) ---")
    
    while True:
        config = check_config()
        if config.get("emergency_stop"): break
        
        is_paper = config.get("paper_trading")
        max_allowed = config.get("max_trades_allowed")
        share_target = config.get("shares_per_trade")
        
        if trades_completed >= max_allowed:
            print(f"🏁 Limit reached ({trades_completed}/{max_allowed}).")
            break
            
        markets = get_active_markets(config.get("max_days_until_resolution"))
        mode_label = "🧪 PAPER" if is_paper else "💰 LIVE"
        print(f"\nScanning {len(markets)} short-term markets... [{mode_label}]")
        
        for m in markets:
            config = check_config() 
            if config.get("paused") or config.get("emergency_stop"): break
            if trades_completed >= max_allowed: break
            if has_traded_before(m['question']): continue

            try:
                y_p = float(client.get_price(m['yes_id'], side="BUY")['price'])
                n_p = float(client.get_price(m['no_id'], side="BUY")['price'])
                total = y_p + n_p

                if total < (1.0 - config.get("min_profit_margin")):
                    print(f"💰 ARB FOUND: {total:.3f} | {m['question']}")
                    
                    res_y = execute_trade(client, m['yes_id'], share_target, is_paper)
                    res_n = execute_trade(client, m['no_id'], share_target, is_paper)
                    
                    if res_y and res_n:
                        trades_completed += 1
                        # Log using the highest share count used between both sides
                        final_q = max(res_y['final_shares'], res_n['final_shares'])
                        log_trade_json(m, total, y_p, n_p, final_q)
                        print(f"✅ Trade {trades_completed} logged ({final_q} shares).")
            except Exception: continue
            
        time.sleep(config.get("scan_interval"))

if __name__ == "__main__":
    try:
        run_bot()
    except KeyboardInterrupt:
        print("\n👋 Stopped.")