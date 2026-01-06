import time
import sys
import io
import argparse
import os
from datetime import datetime, timedelta
from solana.rpc.api import Client
from solders.pubkey import Pubkey
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Fix Windows console encoding for emojis
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# --- CONFIGURATION ---
# 1. Paste your RPC URL (Free ones like 'api.mainnet-beta.solana.com' are slow/rate-limited)
#    For best results, use a private RPC from Helius, Quicknode, or Alchemy.
# Helius RPC (recommended - faster and more reliable)
HELIUS_API_KEY = os.getenv('HELIUS_API_KEY', '')
if not HELIUS_API_KEY:
    print("=" * 60)
    print("ERROR: HELIUS_API_KEY environment variable not set!")
    print("=" * 60)
    print("Please create a .env file with: HELIUS_API_KEY=your-key-here")
    print("Or set environment variable before running")
    print("=" * 60)
    exit(1)

RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"

# 2. DEFAULT POOL ADDRESS (can be overridden via command line argument)
#    Example: BONK/SOL Raydium Pool is '36pYp9v2ZfS3L9s3S9A1z3S9A1z3S9A1z3S9A1z3S9A1'
#    Usage: python scan_fresh.py --pool YOUR_POOL_ADDRESS
#    Or: python scan_fresh.py (will use default or prompt)
DEFAULT_POOL = "rnMLBLnUueJveGpLCS2BGsY3McJGRXZ8bqQ8eBWbonk" 

# 3. SETTINGS
MAX_HISTORY_LIMIT = 10   # Only alert if wallet has this many Tx or less
CHECK_INTERVAL = 3      # Seconds between checks (increase if getting rate limited)
LOG_FILE = "fresh_wallets.txt"  # File to save all detected fresh wallets

client = Client(RPC_URL)

def log_fresh_wallet(wallet_address, tx_count, tx_time, tx_sig):
    """
    Logs fresh wallet detection to a text file.
    """
    try:
        # Create log entry
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"""
{'='*80}
FRESH WALLET DETECTED
{'='*80}
Detection Time: {timestamp}
Wallet Address: {wallet_address}
Transaction Count: {tx_count}
Transaction Time: {tx_time if tx_time else 'N/A'}
Transaction Signature: {tx_sig}
Solscan Link: https://solscan.io/tx/{tx_sig}
Wallet Link: https://solscan.io/account/{wallet_address}
{'-'*80}

"""
        
        # Append to file
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_entry)
        
    except Exception as e:
        print(f"⚠️  Error writing to log file: {e}")

def get_wallet_tx_count(wallet_pubkey, tx_limit=None):
    """
    Checks if a wallet has <= tx_limit transactions.
    Returns the count if fresh, otherwise returns 999.
    """
    if tx_limit is None:
        tx_limit = MAX_HISTORY_LIMIT
    try:
        # Fetch just enough signatures to see if it crosses the threshold
        sigs = client.get_signatures_for_address(
            wallet_pubkey, 
            limit=tx_limit + 1
        )
        count = len(sigs.value)
        return count
    except Exception as e:
        # If we can't read the wallet, assume it's not fresh to be safe
        return 999

def analyze_transaction(tx_sig, check_time=None, tx_limit=None):
    """
    Fetches tx details to find the buyer and check freshness.
    check_time: If provided, only process if transaction is after this timestamp.
    tx_limit: Max transaction limit for fresh wallets (defaults to MAX_HISTORY_LIMIT)
    """
    if client is None:
        return False
    if tx_limit is None:
        tx_limit = MAX_HISTORY_LIMIT
    try:
        # Get transaction with parsed logs/meta
        tx = client.get_transaction(
            tx_sig, 
            max_supported_transaction_version=0,
            encoding="jsonParsed" 
        )
        
        if not tx.value:
            return False

        # Check if transaction is within time window (if specified)
        if check_time is not None:
            block_time = tx.value.block_time
            if block_time is None or block_time < check_time:
                return False

        # The 'Signer' (Initiator) is always the first account in the list
        details = tx.value.transaction
        meta = tx.value.transaction.meta
        
        # Determine the buyer (Signer is index 0)
        buyer = details.transaction.message.account_keys[0].pubkey
        buyer_address = str(buyer)

        # Check if they are actually swapping (look for log messages)
        logs = meta.log_messages
        is_swap = any("Swap" in log or "Instruction: Swap" in log for log in logs)
        
        if is_swap:
            # CHECK HISTORY
            tx_count = get_wallet_tx_count(buyer, tx_limit)
            
            if tx_count <= tx_limit:
                # Get transaction time for display
                tx_time = ""
                if tx.value.block_time:
                    tx_time = datetime.fromtimestamp(tx.value.block_time).strftime("%Y-%m-%d %H:%M:%S")
                
                # Display alert
                print(f"\n🚨 FRESH WALLET DETECTED 🚨")
                print(f"💰 Wallet: {buyer_address}")
                print(f"Nr of Txs: {tx_count} (Brand New!)")
                if tx_time:
                    print(f"⏰ Time: {tx_time}")
                print(f"🔗 Solscan: https://solscan.io/tx/{tx_sig}")
                print("-" * 30)
                
                # Log to file
                log_fresh_wallet(buyer_address, tx_count, tx_time, tx_sig)
                
                return True
            else:
                # Optional: Print skipped wallets to show it's working
                sys.stdout.write(f"\rSkipped old wallet ({tx_count} txs)...")
                sys.stdout.flush()
                return True

        return False

    except Exception as e:
        # Ignore individual tx errors (common with RPC timeouts)
        return False

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Scan for fresh wallets buying from a Solana pool')
    parser.add_argument('--pool', type=str, help='Pool address to monitor (e.g., Raydium pool address)')
    parser.add_argument('--limit', type=int, help=f'Max transaction limit for fresh wallets (default: {MAX_HISTORY_LIMIT})')
    args = parser.parse_args()
    
    # Get pool address from args, or prompt user, or use default
    if args.pool:
        TARGET_POOL = args.pool
    else:
        # Prompt user for pool address
        print(f"\n💡 Enter the pool address (or press Enter for default: {DEFAULT_POOL})")
        user_input = input("Pool address: ").strip()
        if user_input:
            TARGET_POOL = user_input
        else:
            TARGET_POOL = DEFAULT_POOL
    
    # Override limit if provided
    current_limit = MAX_HISTORY_LIMIT
    if args.limit:
        current_limit = args.limit
    
    print(f"\n--- 🕵️ STARTED FRESH WALLET SCANNER ---")
    print(f"Target Pool: {TARGET_POOL}")
    print(f"Freshness: {current_limit} txs or less")
    print(f"RPC: {RPC_URL}")
    print(f"📝 Logging to: {LOG_FILE}")
    
    # Initialize log file with header
    try:
        if not os.path.exists(LOG_FILE) or os.path.getsize(LOG_FILE) == 0:
            with open(LOG_FILE, 'w', encoding='utf-8') as f:
                f.write(f"""
{'='*80}
FRESH WALLET SCANNER LOG
{'='*80}
Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Target Pool: {TARGET_POOL}
Freshness Limit: {current_limit} transactions or less
RPC: {RPC_URL}
{'='*80}

""")
        else:
            # Append separator for new session
            with open(LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(f"\n\n{'='*80}\nNEW SCAN SESSION - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n{'='*80}\n\n")
    except Exception as e:
        print(f"⚠️  Warning: Could not initialize log file: {e}")
    
    # Validate pool address
    print("Validating pool address...", flush=True)
    try:
        pool_pubkey = Pubkey.from_string(TARGET_POOL)
        print("✓ Pool address valid", flush=True)
    except Exception as e:
        print(f"\n❌ Invalid pool address: {TARGET_POOL}")
        print(f"Error: {str(e)}")
        return
    
    seen_signatures = set()
    
    # Calculate timestamp for 4 hours ago
    four_hours_ago = datetime.now() - timedelta(hours=4)
    four_hours_ago_timestamp = int(four_hours_ago.timestamp())
    
    print(f"\n📊 Scanning past 4 hours of transactions...")
    print(f"Time window: {four_hours_ago.strftime('%Y-%m-%d %H:%M:%S')} to now")
    
    # Fetch historical transactions (past 4 hours)
    # We'll fetch in batches to cover 4 hours of activity
    historical_processed = 0
    before_sig = None
    
    try:
        # Fetch transactions in batches until we go back 4 hours
        for batch in range(20):  # Max 20 batches (2000 transactions)
            limit = 100
            try:
                if before_sig:
                    response = client.get_signatures_for_address(
                        pool_pubkey,
                        limit=limit,
                        before=before_sig
                    )
                else:
                    response = client.get_signatures_for_address(
                        pool_pubkey,
                        limit=limit
                    )
            except Exception as rpc_error:
                print(f"\n⚠️  RPC Error fetching batch {batch + 1}: {str(rpc_error)}")
                time.sleep(2)
                continue
            
            if not response.value or len(response.value) == 0:
                break
            
            batch_processed = 0
            should_stop = False
            for tx_info in response.value:
                if tx_info.signature in seen_signatures:
                    continue
                    
                seen_signatures.add(tx_info.signature)
                
                # Check block time from signature info (if available)
                # Note: block_time might be None for very recent transactions
                if tx_info.block_time is not None:
                    if tx_info.block_time < four_hours_ago_timestamp:
                        should_stop = True
                        break
                
                # Analyze transaction (will check time internally if block_time wasn't available)
                if analyze_transaction(tx_info.signature, check_time=four_hours_ago_timestamp, tx_limit=current_limit):
                    batch_processed += 1
                    historical_processed += 1
            
            if should_stop:
                break
            
            # Set before_sig for next batch
            if len(response.value) > 0:
                before_sig = response.value[-1].signature
            else:
                break
            
            # Small delay to avoid rate limiting
            time.sleep(0.5)
            
            sys.stdout.write(f"\rProcessed {historical_processed} fresh wallets from history... (batch {batch + 1})")
            sys.stdout.flush()
    
    except Exception as e:
        import traceback
        print(f"\n⚠️  Error scanning history: {str(e)}")
        print(f"Error type: {type(e).__name__}")
        print("Continuing with live monitoring...")
    
    print(f"\n✅ Historical scan complete! Found {historical_processed} fresh wallet(s) in past 4 hours.")
    print("\n🔍 Now monitoring for NEW buys...")

    retry_count = 0
    max_retries = 5
    
    while True:
        try:
            # Poll for new signatures
            response = client.get_signatures_for_address(
                Pubkey.from_string(TARGET_POOL), 
                limit=10
            )
            
            # Reset retry count on successful connection
            retry_count = 0
            
            # Process strictly new signatures
            new_txs = []
            if response.value:
                for tx_info in response.value:
                    if tx_info.signature not in seen_signatures:
                        seen_signatures.add(tx_info.signature)
                        new_txs.append(tx_info.signature)
            
            # Analyze new transactions
            for sig in new_txs:
                analyze_transaction(sig, tx_limit=current_limit)
                
            time.sleep(CHECK_INTERVAL)
            
        except KeyboardInterrupt:
            print("\nStopping scanner...")
            break
        except Exception as e:
            retry_count += 1
            error_msg = str(e) if str(e) else f"{type(e).__name__}"
            print(f"Connection Error ({retry_count}/{max_retries}): {error_msg} - Retrying...")
            
            if retry_count >= max_retries:
                print(f"\n❌ Max retries reached. Please check:")
                print(f"   1. Your RPC endpoint: {RPC_URL}")
                print(f"   2. Pool address is valid: {TARGET_POOL}")
                print(f"   3. Internet connection")
                print(f"\nTrying again in 10 seconds...")
                time.sleep(10)
                retry_count = 0
            else:
                time.sleep(min(5 * retry_count, 15))  # Exponential backoff, max 15 seconds

if __name__ == "__main__":
    main()

