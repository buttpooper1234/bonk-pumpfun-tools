from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
import threading
import time
import sys
import io
import os
import json
from datetime import datetime, timedelta
from solana.rpc.api import Client
from solders.pubkey import Pubkey
from collections import defaultdict
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'mugetsu-style-scanner-secret'
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

# Token addresses for BONK/USD1 (you'll need to add the actual token addresses)
BONK_TOKEN = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"  # BONK token address
USD1_TOKEN = ""  # Add USD1 token address if known

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
        print(f"Error initializing client: {e}")
        return False

# ========== EXISTING FRESH WALLET FUNCTIONS ==========
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
    """Get wallet transaction count"""
    if client is None:
        return 999
    if tx_limit is None:
        tx_limit = MAX_HISTORY_LIMIT
    try:
        sigs = client.get_signatures_for_address(wallet_pubkey, limit=tx_limit + 1)
        return len(sigs.value)
    except:
        return 999

def analyze_transaction(tx_sig, check_time=None, tx_limit=None, pool_address=None):
    """Analyze transaction for fresh wallets"""
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
        buyer = details.transaction.message.account_keys[0].pubkey
        buyer_address = str(buyer)

        logs = meta.log_messages
        is_swap = any("Swap" in log or "Instruction: Swap" in log for log in logs)
        
        if is_swap:
            tx_count = get_wallet_tx_count(buyer, tx_limit)
            
            if tx_count <= tx_limit:
                tx_time = ""
                if tx.value.block_time:
                    tx_time = datetime.fromtimestamp(tx.value.block_time).strftime("%Y-%m-%d %H:%M:%S")
                
                wallet_data = {
                    'wallet': buyer_address,
                    'tx_count': tx_count,
                    'tx_time': tx_time,
                    'tx_sig': str(tx_sig),
                    'detection_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                socketio.emit('fresh_wallet', wallet_data)
                log_fresh_wallet(buyer_address, tx_count, tx_time, str(tx_sig), pool_address or "Unknown")
                return True
        return False
    except:
        return False

# ========== NEW FEATURES ==========

def get_token_holders(token_address, limit=50):
    """Get top token holders"""
    if client is None:
        return []
    try:
        # Use getProgramAccounts to get token holders
        # This is a simplified version - you may need to use token program
        token_pubkey = Pubkey.from_string(token_address)
        # Note: This requires more complex token account parsing
        # For now, return placeholder
        return []
    except Exception as e:
        print(f"Error getting holders: {e}")
        return []

def analyze_wallet_pnl(wallet_address, token_address):
    """Analyze wallet PnL for a specific token"""
    if client is None:
        return None
    try:
        wallet_pubkey = Pubkey.from_string(wallet_address)
        token_pubkey = Pubkey.from_string(token_address)
        
        # Get recent transactions
        sigs = client.get_signatures_for_address(wallet_pubkey, limit=300)
        
        total_bought = 0
        total_sold = 0
        current_balance = 0
        
        # Analyze transactions (simplified - would need full parsing)
        for sig_info in sigs.value[:50]:  # Limit to 50 for performance
            try:
                tx = client.get_transaction(sig_info.signature, max_supported_transaction_version=0, encoding="jsonParsed")
                # Parse transaction for token swaps
                # This is simplified - full implementation would parse all token transfers
                pass
            except:
                continue
        
        return {
            'wallet': wallet_address,
            'total_bought': total_bought,
            'total_sold': total_sold,
            'current_balance': current_balance,
            'pnl': total_sold - total_bought + current_balance
        }
    except Exception as e:
        print(f"Error analyzing wallet: {e}")
        return None

def get_funded_wallets(pool_address, hours=24):
    """Get wallets that received funding and bought from pool"""
    if client is None:
        return []
    try:
        pool_pubkey = Pubkey.from_string(pool_address)
        since_time = int((datetime.now() - timedelta(hours=hours)).timestamp())
        
        funded_wallets = []
        sigs = client.get_signatures_for_address(pool_pubkey, limit=100)
        
        for sig_info in sigs.value:
            if sig_info.block_time and sig_info.block_time >= since_time:
                try:
                    tx = client.get_transaction(sig_info.signature, max_supported_transaction_version=0, encoding="jsonParsed")
                    # Check if wallet received funding before buying
                    # Simplified - would need full transaction parsing
                    pass
                except:
                    continue
        
        return funded_wallets
    except Exception as e:
        print(f"Error getting funded wallets: {e}")
        return []

def get_common_traders(token1_address, token2_address):
    """Find common top traders between two tokens"""
    if client is None:
        return []
    try:
        # Get top traders for each token
        # This would require analyzing all transactions and calculating PnL
        # Simplified version
        return []
    except Exception as e:
        print(f"Error getting common traders: {e}")
        return []

# ========== SCAN LOOP (EXISTING) ==========
def scan_loop(pool_address, tx_limit):
    """Main scanning loop"""
    global scanning, current_pool, current_limit
    
    current_pool = pool_address
    current_limit = tx_limit
    seen_signatures = set()
    
    try:
        pool_pubkey = Pubkey.from_string(pool_address)
    except Exception as e:
        socketio.emit('error', {'message': f'Invalid pool address: {str(e)}'})
        scanning = False
        return
    
    if client is None:
        socketio.emit('error', {'message': 'RPC client not initialized'})
        scanning = False
        return
    
    socketio.emit('status', {'message': 'Scanning past 4 hours...', 'scanning': True})
    
    four_hours_ago = datetime.now() - timedelta(hours=4)
    four_hours_ago_timestamp = int(four_hours_ago.timestamp())
    historical_processed = 0
    before_sig = None
    
    try:
        for batch in range(20):
            if not scanning:
                break
            try:
                socketio.emit('status', {'message': f'Fetching batch {batch + 1}/20...', 'scanning': True})
                if before_sig:
                    response = client.get_signatures_for_address(pool_pubkey, limit=100, before=before_sig)
                else:
                    response = client.get_signatures_for_address(pool_pubkey, limit=100)
            except Exception as e:
                socketio.emit('status', {'message': f'RPC error: {str(e)}', 'scanning': True})
                time.sleep(2)
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
                    if tx_info.block_time < four_hours_ago_timestamp:
                        should_stop = True
                        break
                
                if analyze_transaction(tx_info.signature, check_time=four_hours_ago_timestamp, 
                                     tx_limit=tx_limit, pool_address=pool_address):
                    historical_processed += 1
            
            if should_stop:
                break
            
            if len(response.value) > 0:
                before_sig = response.value[-1].signature
            else:
                break
            
            time.sleep(0.5)
    
    except Exception as e:
        socketio.emit('error', {'message': f'Error: {str(e)}'})
    
    socketio.emit('status', {'message': f'Found {historical_processed} fresh wallets. Monitoring...', 'scanning': True})
    
    while scanning:
        try:
            response = client.get_signatures_for_address(pool_pubkey, limit=10)
            new_txs = []
            if response.value:
                for tx_info in response.value:
                    if tx_info.signature not in seen_signatures:
                        seen_signatures.add(tx_info.signature)
                        new_txs.append(tx_info.signature)
            
            for sig in new_txs:
                if not scanning:
                    break
                analyze_transaction(sig, tx_limit=tx_limit, pool_address=pool_address)
            
            time.sleep(CHECK_INTERVAL)
        except Exception as e:
            time.sleep(5)
    
    scanning = False
    socketio.emit('status', {'message': 'Scanning stopped', 'scanning': False})

# ========== API ROUTES ==========
@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/api/start', methods=['POST'])
def start_scan():
    global scanning, scan_thread
    if scanning:
        return jsonify({'error': 'Scan already running'}), 400
    
    data = request.json
    pool_address = data.get('pool', DEFAULT_POOL)
    tx_limit = data.get('limit', MAX_HISTORY_LIMIT)
    
    if not init_client():
        return jsonify({'error': 'Failed to initialize RPC client'}), 500
    
    scanning = True
    scan_thread = threading.Thread(target=scan_loop, args=(pool_address, tx_limit), daemon=True)
    scan_thread.start()
    
    return jsonify({'success': True, 'message': 'Scan started'})

@app.route('/api/stop', methods=['POST'])
def stop_scan():
    global scanning
    scanning = False
    return jsonify({'success': True, 'message': 'Scan stopped'})

@app.route('/api/top_holders', methods=['POST'])
def api_top_holders():
    data = request.json
    token_address = data.get('token', BONK_TOKEN)
    limit = data.get('limit', 50)
    
    holders = get_token_holders(token_address, limit)
    return jsonify({'success': True, 'holders': holders})

@app.route('/api/wallet_analyzer', methods=['POST'])
def api_wallet_analyzer():
    data = request.json
    wallet_address = data.get('wallet')
    token_address = data.get('token', BONK_TOKEN)
    
    if not wallet_address:
        return jsonify({'error': 'Wallet address required'}), 400
    
    result = analyze_wallet_pnl(wallet_address, token_address)
    if result:
        return jsonify({'success': True, 'data': result})
    return jsonify({'error': 'Failed to analyze wallet'}), 500

@app.route('/api/funded', methods=['POST'])
def api_funded():
    data = request.json
    pool_address = data.get('pool', DEFAULT_POOL)
    hours = data.get('hours', 24)
    
    wallets = get_funded_wallets(pool_address, hours)
    return jsonify({'success': True, 'wallets': wallets})

@app.route('/api/common_traders', methods=['POST'])
def api_common_traders():
    data = request.json
    token1 = data.get('token1', BONK_TOKEN)
    token2 = data.get('token2')
    
    if not token2:
        return jsonify({'error': 'Second token address required'}), 400
    
    traders = get_common_traders(token1, token2)
    return jsonify({'success': True, 'traders': traders})

@app.route('/api/status', methods=['GET'])
def get_status():
    return jsonify({
        'scanning': scanning,
        'pool': current_pool,
        'limit': current_limit
    })

if __name__ == '__main__':
    init_client()
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)

