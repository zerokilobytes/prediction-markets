import os
import time
from dotenv import load_dotenv
from eth_account import Account
# Corrected import name
from py_clob_client.client import ClobClient

load_dotenv()

def get_client():
    pk = os.getenv("PRIVATE_KEY")
    host = os.getenv("CLOB_API_URL")
    chain_id = int(os.getenv("CHAIN_ID"))
    
    # Initialize client
    client = ClobClient(host, key=pk, chain_id=chain_id)
    
    # Create or derive the API credentials (L2)
    client.create_or_derive_api_creds()
    return client

def run_arb_check(client, yes_id, no_id):
    try:
        # Fetch current mid-market prices
        yes_price = float(client.get_midpoint(yes_id))
        no_price = float(client.get_midpoint(no_id))
        
        sum_price = yes_price + no_price
        profit_margin = 1.0 - sum_price
        
        print(f"Yes: ${yes_price:.3f} | No: ${no_price:.3f} | Sum: ${sum_price:.3f}")
        
        target = float(os.getenv("MIN_PROFIT_MARGIN"))
        if profit_margin >= target:
            print(f"!!! ARBITRAGE FOUND: {profit_margin*100:.2f}% !!!")
        else:
            print("Scanning...")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    # You still need to find real Token IDs to put here
    YES_TOKEN = "PASTE_YES_ID_HERE"
    NO_TOKEN = "PASTE_NO_ID_HERE"

    poly_client = get_client()
    print(f"Bot Active for Market: {YES_TOKEN}")
    
    while True:
        run_arb_check(poly_client, YES_TOKEN, NO_TOKEN)
        time.sleep(5)