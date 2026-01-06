from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
import threading
import time
import sys
import io
import os
from datetime import datetime, timedelta
from solana.rpc.api import Client
from solders.pubkey import Pubkey
from solders.rpc.requests import GetProgramAccounts
from solders.rpc.config import RpcAccountInfoConfig, RpcProgramAccountsConfig
from solders.rpc.responses import GetProgramAccountsResp
import base64
import struct
from collections import defaultdict
import requests
import re
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'fresh-wallet-scanner-secret'
socketio = SocketIO(app, cors_allowed_origins="*")

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Configuration
HELIUS_API_KEY = os.getenv('HELIUS_API_KEY', '')
if not HELIUS_API_KEY:
    print("=" * 60)
    print("ERROR: HELIUS_API_KEY environment variable not set!")
    print("=" * 60)
    print("Please set it using one of these methods:")
    print("1. Create a .env file with: HELIUS_API_KEY=your-key-here")
    print("2. Or set environment variable: export HELIUS_API_KEY='your-key-here'")
    print("3. Windows: set HELIUS_API_KEY=your-key-here")
    print("=" * 60)
    exit(1)

RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
DEFAULT_POOL = "rnMLBLnUueJveGpLCS2BGsY3McJGRXZ8bqQ8eBWbonk"
MAX_HISTORY_LIMIT = 10
CHECK_INTERVAL = 3
LOG_FILE = "fresh_wallets.txt"

# Global state
client = None
scanning = False
scan_thread = None
current_pool = None
current_limit = MAX_HISTORY_LIMIT

def init_client():
    global client
    try:
        client = Client(RPC_URL, timeout=30)
        return True
    except Exception as e:
        return False

def check_config():
    """Check if configuration is valid"""
    if not HELIUS_API_KEY:
        return False, "HELIUS_API_KEY not set"
    try:
        test_client = Client(RPC_URL, timeout=10)
        # Quick test - get latest blockhash
        test_client.get_latest_blockhash()
        return True, "OK"
    except Exception as e:
        return False, f"RPC connection failed: {str(e)}"

def log_fresh_wallet(wallet_address, tx_count, tx_time, tx_sig, pool_address):
    """Logs fresh wallet to file"""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"""
{'='*80}
FRESH WALLET DETECTED
{'='*80}
Detection Time: {timestamp}
Pool Address: {pool_address}
Wallet Address: {wallet_address}
Transaction Count: {tx_count}
Transaction Time: {tx_time if tx_time else 'N/A'}
Transaction Signature: {tx_sig}
Solscan Link: https://solscan.io/tx/{tx_sig}
Wallet Link: https://solscan.io/account/{wallet_address}
{'-'*80}

"""
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_entry)
    except Exception as e:
        print(f"Error writing to log: {e}")

def get_wallet_tx_count(wallet_pubkey, tx_limit=None):
    """Get wallet transaction count - OPTIMIZED"""
    if client is None:
        return 999
    if tx_limit is None:
        tx_limit = MAX_HISTORY_LIMIT
    try:
        # OPTIMIZED: Only fetch what we need, use smaller limit
        sigs = client.get_signatures_for_address(wallet_pubkey, limit=tx_limit + 1)
        count = len(sigs.value) if sigs.value else 0
        # If we got exactly tx_limit + 1, wallet has more transactions
        if count > tx_limit:
            return 999
        return count
    except:
        # OPTIMIZED: Return 999 (not fresh) on error to skip
        return 999

def get_wallet_token_balance(wallet_address, token_mint):
    """Check if wallet currently holds the token (balance > 0)"""
    if client is None:
        return 0
    try:
        wallet_pubkey = Pubkey.from_string(wallet_address)
        token_mint_pubkey = Pubkey.from_string(token_mint)
        
        # Get all token accounts for this wallet with this mint
        # Using dict format for filter (Solana RPC API format)
        token_accounts = client.get_token_accounts_by_owner(
            wallet_pubkey,
            {"mint": token_mint_pubkey},
            encoding="jsonParsed"
        )
        
        if not token_accounts.value:
            return 0
        
        # Sum up all token account balances for this mint
        total_balance = 0
        for account in token_accounts.value:
            try:
                # Access parsed account data
                if hasattr(account, 'account') and hasattr(account.account, 'data'):
                    data = account.account.data
                    if isinstance(data, dict):
                        parsed = data.get('parsed', {})
                        info = parsed.get('info', {})
                        token_amount = info.get('tokenAmount', {})
                        balance = token_amount.get('uiAmount', 0) or token_amount.get('amount', 0)
                        if balance:
                            total_balance += float(balance)
                    elif hasattr(data, 'parsed'):
                        info = data.parsed.get('info', {}) if isinstance(data.parsed, dict) else {}
                        token_amount = info.get('tokenAmount', {}) if isinstance(info, dict) else {}
                        balance = token_amount.get('uiAmount', 0) if isinstance(token_amount, dict) else 0
                        if balance:
                            total_balance += float(balance)
            except Exception as e:
                print(f"[DEBUG] Error parsing token account: {e}")
                continue
        
        return total_balance
    except Exception as e:
        print(f"[DEBUG] Error checking token balance: {e}")
        return 0

def is_pumpswap_pool(pool_address):
    """Check if pool address is owned by PumpSwap program"""
    if client is None:
        return False
    try:
        pool_pubkey = Pubkey.from_string(pool_address)
        account_info = client.get_account_info(pool_pubkey, encoding="jsonParsed")
        if account_info.value and account_info.value.owner:
            owner = str(account_info.value.owner)
            return owner == PUMPSWAP_PROGRAM_ID
    except Exception as e:
        print(f"[DEBUG] Error checking PumpSwap pool: {e}")
    return False

def get_token_mint_from_pool(pool_address):
    """Extract token mint address from pool"""
    if client is None:
        return None
    try:
        pool_pubkey = Pubkey.from_string(pool_address)
        # Get pool account data to find token mint
        # This is pool-specific, but for most DEX pools, we can get it from account data
        account_info = client.get_account_info(pool_pubkey, encoding="jsonParsed")
        if account_info.value and account_info.value.data:
            data = account_info.value.data
            if isinstance(data, dict):
                # Try to find mint in parsed data
                parsed = data.get('parsed', {})
                info = parsed.get('info', {})
                # Different pools store mint differently
                mint = info.get('tokenMint') or info.get('mint') or info.get('tokenA', {}).get('mint')
                if mint:
                    return mint
    except Exception as e:
        print(f"[DEBUG] Error getting token mint from pool: {e}")
    return None

def get_token_mint_from_transaction(tx):
    """Extract token mint from transaction"""
    try:
        meta = tx.value.transaction.meta
        if not meta or not meta.pre_token_balances:
            return None
        
        # Get token mint from pre_token_balances or post_token_balances
        for balance in meta.pre_token_balances or []:
            mint = balance.mint
            if mint:
                return str(mint)
        for balance in meta.post_token_balances or []:
            mint = balance.mint
            if mint:
                return str(mint)
    except:
        pass
    return None

def analyze_transaction(tx_sig, check_time=None, tx_limit=None, pool_address=None, token_mint=None):
    """Analyze transaction for fresh wallets - shows all wallets including those that sold"""
    if client is None:
        return False
    if tx_limit is None:
        tx_limit = MAX_HISTORY_LIMIT
    
    try:
        tx = client.get_transaction(tx_sig, max_supported_transaction_version=0, encoding="jsonParsed")
        if not tx.value:
            return False

        if check_time is not None:
            block_time = tx.value.block_time
            if block_time is None or block_time < check_time:
                return False

        details = tx.value.transaction
        meta = tx.value.transaction.meta
        # Try to find the buyer from account keys (first signer is usually the buyer)
        buyer_address = None
        account_keys = details.transaction.message.account_keys
        if account_keys and len(account_keys) > 0:
            # First account is usually the signer/buyer
            buyer = account_keys[0].pubkey
            buyer_address = str(buyer)
        
        # If we can't find buyer from account keys, try to find from token balance changes
        if not buyer_address and meta.post_token_balances:
            # Look for accounts that received tokens (buyers)
            for post_bal in meta.post_token_balances:
                if post_bal.owner and post_bal.ui_token_amount.ui_amount:
                    amount = float(post_bal.ui_token_amount.ui_amount or 0)
                    if amount > 0:
                        # Check if this account had less tokens before
                        pre_amount = 0
                        for pre_bal in (meta.pre_token_balances or []):
                            if pre_bal.account_index == post_bal.account_index and pre_bal.mint == post_bal.mint:
                                pre_amount = float(pre_bal.ui_token_amount.ui_amount or 0)
                                break
                        if amount > pre_amount:
                            buyer_address = str(post_bal.owner)
                            break
        
        if not buyer_address:
            return False

        # OPTIMIZED: Check swap first before expensive wallet check
        if not meta:
            return False
            
        logs = meta.log_messages or []
        # Check for various transaction types: Swap (DEX), Buy/Sell (PumpFun), or token transfers
        is_swap = any("Swap" in log or "Instruction: Swap" in log for log in logs)
        is_pumpfun = any(
            "Buy" in log or "Sell" in log or 
            "pump" in log.lower() or 
            PUMPFUN_PROGRAM_ID in log or
            PUMPSWAP_PROGRAM_ID in log or
            "pumpswap" in log.lower() or
            "Instruction: Migrate" in log or
            "migrate" in log.lower()
            for log in logs
        )
        
        # Also check account keys for program involvement
        account_keys = details.transaction.message.account_keys
        has_pumpfun_program = False
        if account_keys:
            for key in account_keys:
                try:
                    key_str = str(key.pubkey)
                    if key_str == PUMPFUN_PROGRAM_ID or key_str == PUMPSWAP_PROGRAM_ID:
                        has_pumpfun_program = True
                        break
                except:
                    continue
        # Also check for token balance changes which indicate a buy/sell
        # This is the most reliable way - check if buyer received tokens
        has_token_balance_change = False
        if meta.post_token_balances:
            # Check if buyer_address received any tokens
            for post_bal in meta.post_token_balances:
                # Check if this balance belongs to the buyer
                if post_bal.owner and str(post_bal.owner) == buyer_address:
                    post_amount = float(post_bal.ui_token_amount.ui_amount or 0)
                    if post_amount > 0:
                        # Find corresponding pre balance
                        pre_amount = 0
                        if meta.pre_token_balances:
                            for pre_bal in meta.pre_token_balances:
                                if (pre_bal.account_index == post_bal.account_index and 
                                    pre_bal.mint == post_bal.mint):
                                    pre_amount = float(pre_bal.ui_token_amount.ui_amount or 0)
                                    break
                        # If post amount > pre amount, buyer received tokens (it's a buy)
                        if post_amount > pre_amount:
                            has_token_balance_change = True
                            break
                if has_token_balance_change:
                    break
        
        # Accept if it's a swap, PumpFun transaction, PumpSwap transaction, or has token balance increase
        if is_swap or is_pumpfun or has_pumpfun_program or has_token_balance_change:
            # Convert buyer_address back to Pubkey for get_wallet_tx_count
            try:
                buyer_pubkey = Pubkey.from_string(buyer_address)
            except:
                return False
            tx_count = get_wallet_tx_count(buyer_pubkey, tx_limit)
            
            if tx_count <= tx_limit:
                # Get token mint if not provided
                if not token_mint:
                    token_mint = get_token_mint_from_transaction(tx)
                    if not token_mint and pool_address:
                        token_mint = get_token_mint_from_pool(pool_address)
                
                # Check current balance to show if wallet has sold
                current_balance = None
                has_sold = False
                if token_mint:
                    current_balance = get_wallet_token_balance(buyer_address, token_mint)
                    if current_balance <= 0:
                        has_sold = True
                else:
                    # If we can't determine token mint, skip balance check
                    print(f"[DEBUG] Could not determine token mint for transaction {tx_sig}")
                
                tx_time = ""
                if tx.value.block_time:
                    tx_time = datetime.fromtimestamp(tx.value.block_time).strftime("%Y-%m-%d %H:%M:%S")
                
                # Emit to web interface - show all wallets, including those that sold
                wallet_data = {
                    'wallet': buyer_address,
                    'tx_count': tx_count,
                    'tx_time': tx_time,
                    'tx_sig': str(tx_sig),
                    'detection_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'current_balance': current_balance if token_mint else None,
                    'has_sold': has_sold
                }
                socketio.emit('fresh_wallet', wallet_data)
                
                # OPTIMIZED: Log asynchronously (don't block)
                try:
                    log_fresh_wallet(buyer_address, tx_count, tx_time, str(tx_sig), pool_address or "Unknown")
                except:
                    pass  # Don't fail on log errors
                
                return True
        return False
    except Exception as e:
        print(f"[DEBUG] Error in analyze_transaction: {e}")
        return False

def scan_loop(pool_address, tx_limit, hours=4):
    """Main scanning loop"""
    global scanning, current_pool, current_limit
    
    current_pool = pool_address
    current_limit = tx_limit
    seen_signatures = set()
    
    print(f"[DEBUG] Starting scan for pool: {pool_address}, limit: {tx_limit}")
    
    # Initialize log file
    try:
        if not os.path.exists(LOG_FILE) or os.path.getsize(LOG_FILE) == 0:
            with open(LOG_FILE, 'w', encoding='utf-8') as f:
                f.write(f"""
{'='*80}
FRESH WALLET SCANNER LOG
{'='*80}
Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Target Pool: {pool_address}
Freshness Limit: {tx_limit} transactions or less
RPC: {RPC_URL}
{'='*80}

""")
    except Exception as e:
        print(f"[DEBUG] Error initializing log file: {e}")
    
    # Validate pool address
    try:
        pool_pubkey = Pubkey.from_string(pool_address)
        print(f"[DEBUG] Pool address validated: {pool_address}")
    except Exception as e:
        error_msg = f'Invalid pool address: {str(e)}'
        print(f"[DEBUG] {error_msg}")
        socketio.emit('error', {'message': error_msg})
        socketio.emit('status', {'message': error_msg, 'scanning': False})
        scanning = False
        return
    
    # Check client
    if client is None:
        error_msg = 'RPC client not initialized'
        print(f"[DEBUG] {error_msg}")
        socketio.emit('error', {'message': error_msg})
        socketio.emit('status', {'message': error_msg, 'scanning': False})
        scanning = False
        return
    
    socketio.emit('status', {'message': 'Validating pool address...', 'scanning': True})
    time.sleep(0.5)
    
    # Calculate time range
    hours_text = f"{hours} hour{'s' if hours != 1 else ''}" if hours >= 1 else f"{int(hours * 60)} minutes"
    socketio.emit('status', {'message': f'Scanning past {hours_text} of transactions...', 'scanning': True})
    
    # Scan past specified hours
    time_ago = datetime.now() - timedelta(hours=hours)
    time_ago_timestamp = int(time_ago.timestamp())
    
    # Calculate number of batches needed (roughly 5 batches per hour)
    max_batches = min(20, max(3, int(hours * 5)))
    historical_processed = 0
    before_sig = None
    
    try:
        # Scan batches based on time range
        for batch in range(max_batches):
            if not scanning:
                break
            try:
                socketio.emit('status', {'message': f'Fetching batch {batch + 1}/{max_batches}...', 'scanning': True})
                if before_sig:
                    response = client.get_signatures_for_address(pool_pubkey, limit=100, before=before_sig)
                else:
                    response = client.get_signatures_for_address(pool_pubkey, limit=100)
                print(f"[DEBUG] Batch {batch + 1}: Got {len(response.value) if response.value else 0} transactions")
            except Exception as e:
                error_msg = f'RPC error in batch {batch + 1}: {str(e)}'
                print(f"[DEBUG] {error_msg}")
                socketio.emit('status', {'message': error_msg, 'scanning': True})
                time.sleep(1)
                continue
            
            if not response.value or len(response.value) == 0:
                break
            
            should_stop = False
            for tx_info in response.value:
                if not scanning:
                    break
                if tx_info.signature in seen_signatures:
                    continue
                
                seen_signatures.add(tx_info.signature)
                
                if tx_info.block_time is not None:
                    if tx_info.block_time < time_ago_timestamp:
                        should_stop = True
                        break
                
                if analyze_transaction(tx_info.signature, check_time=time_ago_timestamp, 
                                     tx_limit=tx_limit, pool_address=pool_address):
                    historical_processed += 1
            
            if should_stop:
                break
            
            if len(response.value) > 0:
                before_sig = response.value[-1].signature
            else:
                break
            
            # Reduced delay for faster processing
            time.sleep(0.2)
            socketio.emit('progress', {'batch': batch + 1, 'found': historical_processed})
    
    except Exception as e:
        error_msg = f'Error scanning history: {str(e)}'
        print(f"[DEBUG] {error_msg}")
        socketio.emit('error', {'message': error_msg})
    
    status_msg = f'Historical scan complete! Found {historical_processed} fresh wallet(s). Now monitoring for new transactions...'
    print(f"[DEBUG] {status_msg}")
    socketio.emit('status', {'message': status_msg, 'scanning': True})
    
    # Live monitoring
    retry_count = 0
    max_retries = 5
    
    while scanning:
        try:
            response = client.get_signatures_for_address(pool_pubkey, limit=10)
            retry_count = 0
            
            new_txs = []
            if response.value:
                for tx_info in response.value:
                    if tx_info.signature not in seen_signatures:
                        seen_signatures.add(tx_info.signature)
                        new_txs.append(tx_info.signature)
            
            if new_txs:
                print(f"[DEBUG] Found {len(new_txs)} new transactions")
            
            for sig in new_txs:
                if not scanning:
                    break
                # Try to get token mint from pool for balance checking
                token_mint = get_token_mint_from_pool(pool_address)
                analyze_transaction(sig, tx_limit=tx_limit, pool_address=pool_address, token_mint=token_mint)
            
            time.sleep(CHECK_INTERVAL)
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            retry_count += 1
            error_msg = f'Connection error ({retry_count}/{max_retries}): {str(e)}'
            print(f"[DEBUG] {error_msg}")
            socketio.emit('status', {'message': error_msg, 'scanning': True})
            if retry_count >= max_retries:
                socketio.emit('error', {'message': f'Max retries reached: {str(e)}'})
                time.sleep(10)
                retry_count = 0
            else:
                time.sleep(min(5 * retry_count, 15))
    
    scanning = False
    print("[DEBUG] Scan stopped")
    socketio.emit('status', {'message': 'Scanning stopped', 'scanning': False})

@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/old')
def old_index():
    return render_template('index.html')

@app.route('/api/start', methods=['POST'])
def start_scan():
    global scanning, scan_thread
    
    if scanning:
        return jsonify({'error': 'Scan already running'}), 400
    
    data = request.json
    pool_address = data.get('pool', DEFAULT_POOL)
    tx_limit = data.get('limit', MAX_HISTORY_LIMIT)
    hours = data.get('hours', 4)  # Default to 4 hours
    
    if not init_client():
        return jsonify({'error': 'Failed to initialize RPC client'}), 500
    
    scanning = True
    scan_thread = threading.Thread(target=scan_loop, args=(pool_address, tx_limit, hours), daemon=True)
    scan_thread.start()
    
    return jsonify({'success': True, 'message': 'Scan started'})

@app.route('/api/stop', methods=['POST'])
def stop_scan():
    global scanning
    scanning = False
    return jsonify({'success': True, 'message': 'Scan stopped'})

@app.route('/api/status', methods=['GET'])
def get_status():
    return jsonify({
        'scanning': scanning,
        'pool': current_pool,
        'limit': current_limit
    })

@app.route('/api/logs', methods=['GET'])
def get_logs():
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                content = f.read()
            return jsonify({'logs': content})
        return jsonify({'logs': 'No logs yet'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ========== NEW MUGETSU-STYLE FEATURES ==========
BONK_TOKEN = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
PUMPFUN_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMPSWAP_PROGRAM_ID = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
PUMPFUN_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMPSWAP_PROGRAM_ID = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"

def get_token_holders(token_address, limit=50):
    """Get top token holders by scanning transactions and tracking balances"""
    if client is None:
        return []
    
    try:
        token_pubkey = Pubkey.from_string(token_address)
    except Exception as e:
        print(f"[DEBUG] Error parsing token address: {e}")
        return []
    
    # Track balances per wallet
    wallet_balances = defaultdict(float)
    seen_wallets = set()
    
    try:
        # Get token supply for percentage calculation
        supply_response = client.get_token_supply(token_pubkey)
        total_supply = 0
        if supply_response.value:
            total_supply = float(supply_response.value.ui_amount or 0)
        
        # Scan recent transactions to find token holders
        # This is a heuristic approach - we'll look for token transfers
        # Get recent signatures for the token mint (if supported) or scan transfers
        
        # Alternative: Scan transactions from known token accounts
        # We'll look for transactions that involve this token
        
        # For now, we'll use a simplified approach:
        # Scan recent token transfers by looking at transaction history
        # This won't be 100% accurate but will find active holders
        
        # Get recent transactions (we'll scan a limited set)
        # Note: This is computationally expensive, so we limit to recent activity
        
        max_scans = 100  # Limit scans to avoid rate limits
        scanned = 0
        
        # Try to find holders by scanning token account transactions
        # This is a simplified heuristic - not all holders will be found
        
        # For production, you'd want to use:
        # 1. getProgramAccounts with memcmp filter (most accurate)
        # 2. Or use a token indexing service API
        
        # Return empty for now - this requires advanced RPC calls
        # The UI will show a helpful message explaining this
        
        return []
        
    except Exception as e:
        print(f"[DEBUG] Error getting token holders: {e}")
        return []

def analyze_wallet_pnl(wallet_address, token_address):
    """Analyze wallet PnL for a specific token"""
    if client is None:
        return None
    
    try:
        wallet_pubkey = Pubkey.from_string(wallet_address)
        token_pubkey = Pubkey.from_string(token_address)
    except:
        return None
    
    total_bought = 0.0
    total_sold = 0.0
    total_sol_spent = 0.0
    total_sol_received = 0.0
    buy_count = 0
    sell_count = 0
    
    # Get wallet's recent transactions (last 300)
    try:
        sigs = client.get_signatures_for_address(wallet_pubkey, limit=300)
        if not sigs.value:
            return {
                'wallet': wallet_address,
                'total_bought': 0,
                'total_sold': 0,
                'current_balance': 0,
                'pnl': 0,
                'buy_count': 0,
                'sell_count': 0,
                'avg_buy_price': 0,
                'avg_sell_price': 0
            }
    except Exception as e:
        print(f"[DEBUG] Error getting wallet transactions: {e}")
        return None
    
    # Analyze each transaction
    for tx_info in sigs.value:
        try:
            tx = client.get_transaction(tx_info.signature, max_supported_transaction_version=0, encoding="jsonParsed")
            if not tx.value:
                continue
            
            meta = tx.value.transaction.meta
            if not meta:
                continue
            
            # Check if transaction involves the target token
            pre_token_balances = meta.pre_token_balances or []
            post_token_balances = meta.post_token_balances or []
            
            # Find token balance changes for our target token
            token_balance_change = 0.0
            for post_bal in post_token_balances:
                if hasattr(post_bal, 'mint') and str(post_bal.mint) == token_address:
                    # Find corresponding pre balance
                    pre_bal = None
                    for p in pre_token_balances:
                        if hasattr(p, 'account_index') and hasattr(post_bal, 'account_index'):
                            if p.account_index == post_bal.account_index and hasattr(p, 'mint') and str(p.mint) == token_address:
                                pre_bal = p
                                break
                    
                    if pre_bal:
                        pre_amount = float(pre_bal.ui_token_amount.ui_amount or 0)
                        post_amount = float(post_bal.ui_token_amount.ui_amount or 0)
                        token_balance_change = post_amount - pre_amount
                    else:
                        # New token account
                        post_amount = float(post_bal.ui_token_amount.ui_amount or 0)
                        token_balance_change = post_amount
            
            # If token balance increased, it's a buy
            if token_balance_change > 0:
                # Calculate SOL spent (simplified - look at SOL balance change)
                pre_balances = meta.pre_balances or []
                post_balances = meta.post_balances or []
                
                if len(pre_balances) > 0 and len(post_balances) > 0:
                    # Wallet is usually first account (index 0)
                    if len(pre_balances) > 0 and len(post_balances) > 0:
                        sol_change = (post_balances[0] - pre_balances[0]) / 1e9  # Convert to SOL
                        if sol_change < 0:  # SOL decreased = spent
                            total_bought += token_balance_change
                            total_sol_spent += abs(sol_change)
                            buy_count += 1
            
            # If token balance decreased, it's a sell
            elif token_balance_change < 0:
                # Calculate SOL received
                pre_balances = meta.pre_balances or []
                post_balances = meta.post_balances or []
                
                if len(pre_balances) > 0 and len(post_balances) > 0:
                    sol_change = (post_balances[0] - pre_balances[0]) / 1e9
                    if sol_change > 0:  # SOL increased = received
                        total_sold += abs(token_balance_change)
                        total_sol_received += sol_change
                        sell_count += 1
        
        except Exception as e:
            # Skip individual transaction errors
            continue
    
    # Calculate current balance (get from token account)
    current_balance = get_wallet_token_balance(wallet_address, token_address)
    if current_balance <= 0:
        # If wallet doesn't currently hold tokens, return None to indicate no current holdings
        return None
    
    # Calculate PnL
    avg_buy_price = total_sol_spent / total_bought if total_bought > 0 else 0
    avg_sell_price = total_sol_received / total_sold if total_sold > 0 else 0
    
    # Realized PnL: profit from sells
    realized_pnl = total_sol_received - (total_sold * avg_buy_price) if total_bought > 0 else 0
    
    # Unrealized PnL: would need current price (simplified to 0 for now)
    unrealized_pnl = 0
    
    total_pnl = realized_pnl + unrealized_pnl
    
    return {
        'wallet': wallet_address,
        'total_bought': round(total_bought, 2),
        'total_sold': round(total_sold, 2),
        'current_balance': round(current_balance, 2),
        'pnl': round(total_pnl, 4),
        'realized_pnl': round(realized_pnl, 4),
        'unrealized_pnl': round(unrealized_pnl, 4),
        'buy_count': buy_count,
        'sell_count': sell_count,
        'avg_buy_price': round(avg_buy_price, 9) if avg_buy_price > 0 else 0,
        'avg_sell_price': round(avg_sell_price, 9) if avg_sell_price > 0 else 0,
        'total_sol_spent': round(total_sol_spent, 4),
        'total_sol_received': round(total_sol_received, 4)
    }

def get_funded_wallets(pool_address, hours=24):
    """Get wallets that received funding and then bought from pool - only returns wallets currently holding tokens"""
    if client is None:
        return []
    
    try:
        pool_pubkey = Pubkey.from_string(pool_address)
    except:
        return []
    
    # Get token mint from pool for balance checking
    token_mint = get_token_mint_from_pool(pool_address)
    
    funded_wallets = []
    seen_buyers = set()
    
    # Calculate time range
    time_ago = datetime.now() - timedelta(hours=hours)
    time_ago_timestamp = int(time_ago.timestamp())
    
    # Get transactions from pool
    max_batches = min(20, max(3, int(hours * 5)))
    before_sig = None
    
    try:
        for batch in range(max_batches):
            try:
                if before_sig:
                    response = client.get_signatures_for_address(pool_pubkey, limit=50, before=before_sig)
                else:
                    response = client.get_signatures_for_address(pool_pubkey, limit=50)
            except Exception as e:
                print(f"[DEBUG] Funded wallets RPC error: {e}")
                break
            
            if not response.value or len(response.value) == 0:
                break
            
            should_stop = False
            for tx_info in response.value:
                if tx_info.block_time is not None and tx_info.block_time < time_ago_timestamp:
                    should_stop = True
                    break
                
                # Analyze transaction for buy
                try:
                    tx = client.get_transaction(tx_info.signature, max_supported_transaction_version=0, encoding="jsonParsed")
                    if not tx.value:
                        continue
                    
                    # Check if it's a swap
                    meta = tx.value.transaction.meta
                    if not meta or not meta.log_messages:
                        continue
                    
                    logs = meta.log_messages
                    is_swap = any("Swap" in log or "Instruction: Swap" in log for log in logs)
                    
                    if not is_swap:
                        continue
                    
                    # Get buyer (signer)
                    details = tx.value.transaction
                    buyer = details.transaction.message.account_keys[0].pubkey
                    buyer_address = str(buyer)
                    
                    if buyer_address in seen_buyers:
                        continue
                    
                    seen_buyers.add(buyer_address)
                    buy_time = tx.value.block_time
                    
                    # Check buyer's recent transactions for funding
                    try:
                        buyer_sigs = client.get_signatures_for_address(buyer, limit=50)
                        if not buyer_sigs.value:
                            continue
                        
                        funding_found = False
                        funding_amount = 0.0
                        funding_time = None
                        funding_tx = None
                        
                        for buyer_tx_info in buyer_sigs.value:
                            # Only check transactions before the buy
                            if buyer_tx_info.block_time and buy_time and buyer_tx_info.block_time >= buy_time:
                                continue
                            
                            try:
                                buyer_tx = client.get_transaction(buyer_tx_info.signature, max_supported_transaction_version=0, encoding="jsonParsed")
                                if not buyer_tx.value:
                                    continue
                                
                                buyer_meta = buyer_tx.value.transaction.meta
                                if not buyer_meta:
                                    continue
                                
                                # Check if it's a transfer (not a swap)
                                buyer_logs = buyer_meta.log_messages or []
                                is_transfer = any("Transfer" in log for log in buyer_logs) and not any("Swap" in log for log in buyer_logs)
                                
                                if is_transfer:
                                    # Check if SOL was received (balance increased)
                                    pre_balances = buyer_meta.pre_balances or []
                                    post_balances = buyer_meta.post_balances or []
                                    
                                    if len(pre_balances) > 0 and len(post_balances) > 0:
                                        sol_change = (post_balances[0] - pre_balances[0]) / 1e9
                                        if sol_change > 0:  # SOL received
                                            # Check time difference (funding should be within 24 hours before buy)
                                            if buyer_tx_info.block_time:
                                                time_diff = buy_time - buyer_tx_info.block_time
                                                if time_diff <= 86400:  # 24 hours in seconds
                                                    funding_found = True
                                                    funding_amount = sol_change
                                                    funding_time = datetime.fromtimestamp(buyer_tx_info.block_time).strftime("%Y-%m-%d %H:%M:%S")
                                                    funding_tx = str(buyer_tx_info.signature)
                                                    break
                            
                            except Exception as e:
                                continue
                        
                        if funding_found:
                            # Check current balance to show if wallet has sold
                            current_balance = None
                            has_sold = False
                            if token_mint:
                                current_balance = get_wallet_token_balance(buyer_address, token_mint)
                                if current_balance <= 0:
                                    has_sold = True
                            
                            buy_time_str = datetime.fromtimestamp(buy_time).strftime("%Y-%m-%d %H:%M:%S") if buy_time else "N/A"
                            funded_wallets.append({
                                'wallet': buyer_address,
                                'funding_amount': round(funding_amount, 4),
                                'funding_time': funding_time,
                                'buy_time': buy_time_str,
                                'funding_tx': funding_tx,
                                'buy_tx': str(tx_info.signature),
                                'current_balance': current_balance if token_mint else None,
                                'has_sold': has_sold
                            })
                    
                    except Exception as e:
                        continue
                
                except Exception as e:
                    continue
                
                before_sig = tx_info.signature
            
            if should_stop:
                break
        
        return funded_wallets
        
    except Exception as e:
        print(f"[DEBUG] Funded wallets error: {e}")
        return []

def check_github_repo(token_address=None, repo_url=None):
    """AI-powered analysis of GitHub repository legitimacy and plausibility"""
    result = {
        'repo': {
            'exists': False,
            'verified': False,
            'name': None,
            'url': None,
            'stars': 0,
            'forks': 0,
            'last_updated': None,
            'description': None
        },
        'analysis': {
            'plausibility_score': 0,
            'verdict': 'Unknown',
            'is_legitimate': False,
            'red_flags': [],
            'green_flags': [],
            'detailed_analysis': '',
            'recommendation': ''
        }
    }
    
    try:
        # If repo URL is provided, analyze it
        if repo_url:
            # Extract owner/repo from URL
            match = re.search(r'github\.com/([^/]+)/([^/]+)', repo_url)
            if match:
                owner, repo_name = match.groups()
                repo_name = repo_name.rstrip('/')
                
                # Get repository details
                api_url = f"https://api.github.com/repos/{owner}/{repo_name}"
                response = requests.get(api_url, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # Basic repo info
                    result['repo'] = {
                        'exists': True,
                        'verified': True,
                        'name': data.get('full_name', f"{owner}/{repo_name}"),
                        'url': data.get('html_url', repo_url),
                        'stars': data.get('stargazers_count', 0),
                        'forks': data.get('forks_count', 0),
                        'last_updated': data.get('updated_at', 'N/A'),
                        'description': data.get('description', ''),
                        'created_at': data.get('created_at', 'N/A'),
                        'language': data.get('language', 'Unknown'),
                        'size': data.get('size', 0),  # Size in KB
                        'has_issues': data.get('has_issues', False),
                        'has_wiki': data.get('has_wiki', False),
                        'has_pages': data.get('has_pages', False),
                        'is_archived': data.get('archived', False),
                        'is_fork': data.get('fork', False),
                        'default_branch': data.get('default_branch', 'main')
                    }
                    
                    # Perform AI-style analysis
                    analysis = analyze_repository_legitimacy(owner, repo_name, data)
                    result['analysis'] = analysis
                    
                elif response.status_code == 404:
                    result['analysis'] = {
                        'plausibility_score': 0,
                        'verdict': 'Repository Not Found',
                        'is_legitimate': False,
                        'red_flags': ['Repository does not exist'],
                        'green_flags': [],
                        'detailed_analysis': 'The GitHub repository URL provided does not exist or is private.',
                        'recommendation': '⚠️ This repository cannot be verified. Be cautious.'
                    }
                    result['repo']['url'] = repo_url
                    result['repo']['name'] = f"{owner}/{repo_name}"
                else:
                    result['analysis'] = {
                        'plausibility_score': 0,
                        'verdict': 'Access Denied',
                        'is_legitimate': False,
                        'red_flags': ['Cannot access repository'],
                        'green_flags': [],
                        'detailed_analysis': f'Unable to access repository. Status: {response.status_code}',
                        'recommendation': '⚠️ Repository may be private or access is restricted.'
                    }
        
        # If token address is provided, try to find associated repo
        elif token_address:
            result['repo']['name'] = f"Token: {token_address[:20]}..."
            result['repo']['url'] = None
            result['analysis'] = {
                'plausibility_score': 0,
                'verdict': 'No Repository URL Provided',
                'is_legitimate': False,
                'red_flags': ['No GitHub repository URL provided'],
                'green_flags': [],
                'detailed_analysis': 'Please provide a GitHub repository URL to analyze.',
                'recommendation': 'Enter a GitHub repository URL to get AI analysis.'
            }
        
    except Exception as e:
        print(f"[DEBUG] GitHub check error: {e}")
        result['error'] = str(e)
        result['analysis'] = {
            'plausibility_score': 0,
            'verdict': 'Analysis Error',
            'is_legitimate': False,
            'red_flags': [f'Error during analysis: {str(e)}'],
            'green_flags': [],
            'detailed_analysis': f'An error occurred while analyzing the repository: {str(e)}',
            'recommendation': 'Please try again or check the repository URL.'
        }
    
    return result

def analyze_repository_legitimacy(owner, repo_name, repo_data):
    """AI-style analysis of repository legitimacy"""
    score = 0
    max_score = 100
    red_flags = []
    green_flags = []
    analysis_parts = []
    
    # 1. Check repository age and activity
    try:
        created_at = repo_data.get('created_at', '')
        updated_at = repo_data.get('updated_at', '')
        if created_at and updated_at:
            from datetime import datetime
            created = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            updated = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
            age_days = (datetime.now(updated.tzinfo) - created).days
            last_update_days = (datetime.now(updated.tzinfo) - updated).days
            
            if age_days > 30:
                score += 10
                green_flags.append(f'Repository is {age_days} days old (established)')
            else:
                score -= 5
                red_flags.append(f'Repository is very new ({age_days} days old)')
            
            if last_update_days < 30:
                score += 10
                green_flags.append('Recently updated (active development)')
            elif last_update_days > 180:
                score -= 10
                red_flags.append(f'Not updated in {last_update_days} days (inactive)')
    except:
        pass
    
    # 2. Check stars and forks (engagement indicators)
    stars = repo_data.get('stargazers_count', 0)
    forks = repo_data.get('forks_count', 0)
    
    if stars > 100:
        score += 15
        green_flags.append(f'High engagement: {stars} stars')
    elif stars > 10:
        score += 5
        green_flags.append(f'Moderate engagement: {stars} stars')
    elif stars == 0:
        score -= 10
        red_flags.append('No stars (no community interest)')
    
    if forks > 10:
        score += 5
        green_flags.append(f'{forks} forks (active community)')
    
    # 3. Check repository size (empty repos are suspicious)
    size_kb = repo_data.get('size', 0)
    if size_kb > 100:
        score += 10
        green_flags.append(f'Repository has substantial code ({size_kb} KB)')
    elif size_kb < 10:
        score -= 15
        red_flags.append(f'Very small repository ({size_kb} KB) - possibly empty or minimal')
    
    # 4. Check if it's a fork (forks can be legitimate but original is better)
    is_fork = repo_data.get('fork', False)
    if is_fork:
        score -= 5
        red_flags.append('This is a fork (not original repository)')
    
    # 5. Check if archived
    is_archived = repo_data.get('archived', False)
    if is_archived:
        score -= 15
        red_flags.append('Repository is archived (no longer maintained)')
    
    # 6. Check for description
    description = repo_data.get('description', '')
    if description and len(description) > 20:
        score += 5
        green_flags.append('Has detailed description')
    elif not description:
        score -= 5
        red_flags.append('No description provided')
    
    # 7. Check language (Solana projects should have Rust, TypeScript, etc.)
    language = repo_data.get('language', '')
    crypto_languages = ['Rust', 'TypeScript', 'JavaScript', 'Python', 'Solidity', 'Move']
    if language in crypto_languages:
        score += 10
        green_flags.append(f'Uses {language} (common for crypto projects)')
    elif language:
        score += 3
        green_flags.append(f'Uses {language}')
    else:
        score -= 5
        red_flags.append('No primary language detected')
    
    # 8. Get repository contents to check for README and proper structure
    try:
        contents_url = f"https://api.github.com/repos/{owner}/{repo_name}/contents"
        contents_response = requests.get(contents_url, timeout=10)
        if contents_response.status_code == 200:
            contents = contents_response.json()
            has_readme = any(item.get('name', '').upper().startswith('README') for item in contents if item.get('type') == 'file')
            has_src = any(item.get('name', '').lower() in ['src', 'lib', 'contracts', 'programs'] for item in contents if item.get('type') == 'dir')
            
            if has_readme:
                score += 10
                green_flags.append('Has README file (good documentation)')
            else:
                score -= 10
                red_flags.append('No README file (poor documentation)')
            
            if has_src:
                score += 10
                green_flags.append('Has source code directory (proper structure)')
            else:
                score -= 5
                red_flags.append('No obvious source code directory')
    except:
        pass
    
    # 9. Check commit activity
    try:
        commits_url = f"https://api.github.com/repos/{owner}/{repo_name}/commits"
        commits_response = requests.get(commits_url, params={'per_page': 10}, timeout=10)
        if commits_response.status_code == 200:
            commits = commits_response.json()
            commit_count = len(commits)
            
            if commit_count >= 10:
                score += 10
                green_flags.append(f'Has {commit_count}+ commits (active development)')
            elif commit_count > 0:
                score += 3
                green_flags.append(f'Has {commit_count} commits')
            else:
                score -= 15
                red_flags.append('No commits found (empty repository)')
    except:
        pass
    
    # 10. Check for issues and pull requests (community engagement)
    try:
        issues_url = f"https://api.github.com/repos/{owner}/{repo_name}/issues"
        issues_response = requests.get(issues_url, params={'state': 'all', 'per_page': 5}, timeout=10)
        if issues_response.status_code == 200:
            issues = issues_response.json()
            if len(issues) > 0:
                score += 5
                green_flags.append('Has issues/PRs (community engagement)')
    except:
        pass
    
    # Calculate final score and verdict
    score = max(0, min(100, score))  # Clamp between 0-100
    
    if score >= 70:
        verdict = '✅ Highly Legitimate'
        is_legitimate = True
        recommendation = '✅ This repository appears legitimate and well-maintained. Good signs of active development.'
    elif score >= 50:
        verdict = '⚠️ Moderately Plausible'
        is_legitimate = True
        recommendation = '⚠️ This repository seems plausible but has some concerns. Review carefully before investing.'
    elif score >= 30:
        verdict = '⚠️ Suspicious'
        is_legitimate = False
        recommendation = '⚠️ This repository has several red flags. Exercise caution.'
    else:
        verdict = '❌ Highly Suspicious'
        is_legitimate = False
        recommendation = '❌ This repository shows many red flags. Strongly recommend avoiding.'
    
    # Build detailed analysis
    analysis_parts.append(f"**Plausibility Score: {score}/100**")
    analysis_parts.append(f"**Verdict: {verdict}**")
    analysis_parts.append("")
    
    if green_flags:
        analysis_parts.append("**✅ Positive Indicators:**")
        for flag in green_flags:
            analysis_parts.append(f"  • {flag}")
        analysis_parts.append("")
    
    if red_flags:
        analysis_parts.append("**❌ Red Flags:**")
        for flag in red_flags:
            analysis_parts.append(f"  • {flag}")
        analysis_parts.append("")
    
    analysis_parts.append(f"**💡 Recommendation:** {recommendation}")
    
    detailed_analysis = "\n".join(analysis_parts)
    
    return {
        'plausibility_score': score,
        'verdict': verdict,
        'is_legitimate': is_legitimate,
        'red_flags': red_flags,
        'green_flags': green_flags,
        'detailed_analysis': detailed_analysis,
        'recommendation': recommendation
    }

def scan_pumpfun_token(token_address, hours=4):
    """Scan PumpFun token - placeholder implementation"""
    # PumpFun tokens are identified by specific program IDs or metadata
    # Full implementation would:
    # 1. Verify token is a PumpFun token (check program ID or metadata)
    # 2. Get token information from PumpFun API or on-chain data
    # 3. Analyze trading activity
    # 4. Return token details
    
    return {
        'tokens': [],
        'note': 'PumpFun scanner - implementation plan in PUMPFUN_PLAN.md'
    }

def get_floor_price(pool_address, hours=4):
    """Get floor price (minimum buy price) from pool transactions"""
    if client is None:
        return None
    
    try:
        pool_pubkey = Pubkey.from_string(pool_address)
    except:
        return None
    
    floor_price = None
    floor_tx = None
    floor_time = None
    total_buys = 0
    current_price = None
    
    # Calculate time range
    time_ago = datetime.now() - timedelta(hours=hours)
    time_ago_timestamp = int(time_ago.timestamp())
    
    # Get transactions from pool
    max_batches = min(20, max(3, int(hours * 5)))
    before_sig = None
    
    try:
        for batch in range(max_batches):
            try:
                if before_sig:
                    response = client.get_signatures_for_address(pool_pubkey, limit=50, before=before_sig)
                else:
                    response = client.get_signatures_for_address(pool_pubkey, limit=50)
            except Exception as e:
                print(f"[DEBUG] Floor price RPC error: {e}")
                break
            
            if not response.value or len(response.value) == 0:
                break
            
            should_stop = False
            for tx_info in response.value:
                if tx_info.block_time is not None and tx_info.block_time < time_ago_timestamp:
                    should_stop = True
                    break
                
                # Analyze transaction for buy
                try:
                    tx = client.get_transaction(tx_info.signature, max_supported_transaction_version=0, encoding="jsonParsed")
                    if not tx.value:
                        continue
                    
                    # Check if it's a swap
                    meta = tx.value.transaction.meta
                    if not meta or not meta.log_messages:
                        continue
                    
                    logs = meta.log_messages
                    is_swap = any("Swap" in log or "Instruction: Swap" in log for log in logs)
                    
                    if not is_swap:
                        continue
                    
                    # Check token balance changes to determine if it's a buy
                    # For a buy: SOL decreases, token increases in pool
                    # We need to check pre/post token balances
                    pre_token_balances = meta.pre_token_balances or []
                    post_token_balances = meta.post_token_balances or []
                    
                    # Try to find price from balance changes
                    # This is simplified - in reality, we'd need to parse the swap instruction
                    # For now, we'll use a heuristic: if there are token balance changes, it's likely a swap
                    
                    # Get SOL amount from balance changes
                    pre_balances = meta.pre_balances or []
                    post_balances = meta.post_balances or []
                    
                    if len(pre_balances) > 0 and len(post_balances) > 0:
                        # Find the pool's account index (usually one of the first accounts)
                        # For simplicity, we'll estimate based on the largest balance change
                        sol_change = 0
                        for i in range(min(len(pre_balances), len(post_balances))):
                            change = post_balances[i] - pre_balances[i]
                            if abs(change) > abs(sol_change):
                                sol_change = change
                        
                        # If SOL decreased in pool, it's a buy (someone bought tokens with SOL)
                        if sol_change < 0:
                            sol_amount = abs(sol_change) / 1e9  # Convert lamports to SOL
                            
                            # Try to get token amount from token balances
                            token_amount = 0
                            for post_bal in post_token_balances:
                                for pre_bal in pre_token_balances:
                                    if post_bal.account_index == pre_bal.account_index:
                                        token_change = float(post_bal.ui_token_amount.ui_amount or 0) - float(pre_bal.ui_token_amount.ui_amount or 0)
                                        if token_change > 0:
                                            token_amount = token_change
                                            break
                            
                            # If we can't get token amount from balances, estimate from price
                            # This is a simplified approach - full implementation would parse swap instruction
                            if token_amount == 0:
                                # Estimate: assume a reasonable price range (this is a fallback)
                                # In production, you'd parse the actual swap instruction
                                continue
                            
                            if token_amount > 0:
                                price = sol_amount / token_amount
                                total_buys += 1
                                
                                # Update current price (most recent)
                                if current_price is None:
                                    current_price = price
                                
                                # Update floor price (minimum)
                                if floor_price is None or price < floor_price:
                                    floor_price = price
                                    floor_tx = str(tx_info.signature)
                                    if tx.value.block_time:
                                        floor_time = datetime.fromtimestamp(tx.value.block_time).strftime("%Y-%m-%d %H:%M:%S")
                
                except Exception as e:
                    # Skip individual transaction errors
                    continue
                
                before_sig = tx_info.signature
            
            if should_stop:
                break
        
        if floor_price is not None:
            return {
                'floor_price': floor_price,
                'floor_price_sol': floor_price,
                'floor_tx': floor_tx,
                'floor_time': floor_time,
                'current_price': current_price,
                'total_buys_analyzed': total_buys
            }
        return None
        
    except Exception as e:
        print(f"[DEBUG] Floor price error: {e}")
        return None

@app.route('/api/github_check', methods=['POST'])
def api_github_check():
    data = request.json
    token_address = data.get('token')
    repo_url = data.get('repo')
    
    if not token_address and not repo_url:
        return jsonify({'error': 'Token address or repository URL required'}), 400
    
    result = check_github_repo(token_address, repo_url)
    return jsonify({'success': True, **result})

@app.route('/api/wallet_analyzer', methods=['POST'])
def api_wallet_analyzer():
    data = request.json
    wallet_address = data.get('wallet')
    token_address = data.get('token', BONK_TOKEN)
    time_range = data.get('timeRange', 4)
    if not wallet_address:
        return jsonify({'error': 'Wallet address required'}), 400
    
    # Check if wallet currently holds tokens before analyzing
    current_balance = get_wallet_token_balance(wallet_address, token_address)
    if current_balance <= 0:
        return jsonify({
            'success': False,
            'error': 'Wallet does not currently hold this token',
            'current_balance': 0
        }), 400
    
    result = analyze_wallet_pnl(wallet_address, token_address)
    if result:
        return jsonify({'success': True, 'data': result, 'timeRange': time_range})
    # Return placeholder data if analysis fails
    return jsonify({
        'success': True, 
        'data': {
            'wallet': wallet_address,
            'total_bought': 0,
            'total_sold': 0,
            'current_balance': 0,
            'pnl': 0,
            'note': 'Full PnL analysis requires transaction parsing - currently showing placeholder'
        },
        'timeRange': time_range
    })

@app.route('/api/funded', methods=['POST'])
def api_funded():
    data = request.json
    pool_address = data.get('pool', DEFAULT_POOL)
    hours = data.get('hours', 24)
    time_range = data.get('timeRange', hours)  # Support both
    if time_range:
        hours = time_range
    wallets = get_funded_wallets(pool_address, hours)
    return jsonify({'success': True, 'wallets': wallets})

@app.route('/api/pumpfun_scan', methods=['POST'])
def api_pumpfun_scan():
    data = request.json
    token_address = data.get('token')
    time_range = data.get('timeRange', 4)
    
    if not token_address:
        return jsonify({'error': 'Token address required'}), 400
    
    result = scan_pumpfun_token(token_address, time_range)
    return jsonify({'success': True, **result})

@app.route('/api/floor_price', methods=['POST'])
def api_floor_price():
    data = request.json
    pool_address = data.get('pool', DEFAULT_POOL)
    hours = data.get('hours', 4)
    time_range = data.get('timeRange', hours)
    if time_range:
        hours = time_range
    result = get_floor_price(pool_address, hours)
    if result:
        return jsonify({'success': True, 'data': result})
    return jsonify({'error': 'Failed to get floor price'}), 500

if __name__ == '__main__':
    # Check configuration before starting
    config_ok, config_msg = check_config()
    if not config_ok:
        print(f"Configuration Error: {config_msg}")
        exit(1)
    
    print("=" * 60)
    print("Starting BONK & PumpFun Token Analysis Tools")
    print("=" * 60)
    print(f"RPC Endpoint: {RPC_URL.split('?')[0]}...")
    print(f"Server will start on http://localhost:5000")
    print("=" * 60)
    
    init_client()
    socketio.run(app, debug=False, host='0.0.0.0', port=5000)

