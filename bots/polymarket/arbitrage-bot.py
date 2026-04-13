import os
import time
import json
import requests
from dotenv import load_dotenv
from py_clob_client.client import ClobClient

load_dotenv()

def get_authenticated_client():
    """Initializes the Polymarket CLOB client."""
    client = ClobClient(
        host=os.getenv("CLOB_API_URL"),
        key=os.getenv("PRIVATE_KEY"),
        chain_id=int(os.getenv("CHAIN_ID"))
    )
    # L2 credentials are required for price/order operations
    client.create_or_derive_api_creds()
    return client

def get_active_markets():
    """Fetches active events and extracts Token IDs for Yes/No pairs."""
    url = "https://gamma-api.polymarket.com/events"
    params = {
        "active": "true",
        "closed": "false",
        "limit": 15,
        "order": "volume_24hr",
        "ascending": "false"
    }
    
    valid_markets = []
    try:
        response = requests.get(url, params=params)
        events = response.json()
        
        for event in events:
            for market in event.get("markets", []):
                # Gamma API often returns IDs as a stringified list like '["123", "456"]'
                token_ids = market.get("clobTokenIds")
                if isinstance(token_ids, str):
                    token_ids = json.loads(token_ids)

                if token_ids and len(token_ids) == 2:
                    valid_markets.append({
                        "question": market.get("groupItemTitle") or event.get("title"),
                        "yes_id": token_ids[0],
                        "no_id": token_ids[1]
                    })
        return valid_markets
    except Exception as e:
        print(f"Discovery Error: {e}")
        return []

def scan_for_arbitrage(client, markets):
    """Calculates Yes + No cost for a list of markets."""
    print(f"\n--- Scanning {len(markets)} Tradable Markets ---")
    threshold = float(os.getenv("MIN_PROFIT_MARGIN", 0.01))
    
    for m in markets:
        try:
            # We want the 'Ask' price (the price to BUY right now)
            yes_data = client.get_price(m['yes_id'], side="BUY")
            no_data = client.get_price(m['no_id'], side="BUY")
            
            yes_price = float(yes_data['price'])
            no_price = float(no_data['price'])
            
            total_cost = yes_price + no_price
            profit = 1.0 - total_cost

            if total_cost < (1.0 - threshold):
                print(f"✅ ARB FOUND: {m['question']}")
                print(f"   Yes: {yes_price} | No: {no_price} | Sum: {total_cost:.3f}")
                print(f"   Potential Profit: {profit*100:.2f}%")
            else:
                # Truncate title for clean logging
                short_title = (m['question'][:45] + '..') if len(m['question']) > 45 else m['question']
                print(f"❌ {total_cost:.3f} | {short_title}")

        except Exception:
            # Skip if a market has no active orders (404)
            continue

if __name__ == "__main__":
    print("🚀 Starting Arbitrage Bot...")
    try:
        poly_client = get_authenticated_client()
        
        while True:
            # 1. Discover Markets
            active_list = get_active_markets()
            
            if active_list:
                # 2. Scan Prices
                scan_for_arbitrage(poly_client, active_list)
            else:
                print("Searching for active markets...")

            # 3. Wait to avoid API rate limits
            wait = int(os.getenv("SCAN_INTERVAL", 10))
            print(f"\nSleeping {wait}s...")
            time.sleep(wait)
            
    except KeyboardInterrupt:
        print("\nBot stopped by user.")