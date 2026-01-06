# Implementation Guide: Full Feature Implementation

## Overview
This document outlines what's needed to fully implement each tab in the Mugetsu-style analyzer.

---

## ✅ **1. Fresh Wallets Tab** - FULLY IMPLEMENTED
**Status:** Complete and working

**What it does:**
- Scans pool transactions for swaps
- Identifies wallets with ≤10 transactions
- Logs to `fresh_wallets.txt`
- Real-time monitoring via SocketIO

**Implementation:** Already complete in `app.py` (`analyze_transaction`, `scan_loop`)

---

## 🔨 **2. Top Holders Tab** - NEEDS IMPLEMENTATION

### What's Missing:
- **SPL Token Account Parsing**: Need to fetch all token accounts holding a specific token
- **Balance Aggregation**: Calculate total balance per wallet
- **Percentage Calculation**: Calculate % of total supply

### Implementation Steps:

1. **Get Token Mint Address** (already have from input)

2. **Fetch All Token Accounts**:
   ```python
   # Use getProgramAccounts to find all token accounts for this mint
   from solana.rpc.commitment import Confirmed
   from solders.rpc.responses import GetProgramAccountsResp
   
   # Token Program ID: TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA
   TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
   
   # Get all accounts owned by token program
   # Filter by mint address in account data
   ```

3. **Parse Account Data**:
   - Each token account has: `owner` (wallet), `amount` (balance), `mint` (token)
   - Use `base64` decoding to parse account data
   - Or use `getProgramAccounts` with filters

4. **Aggregate by Wallet**:
   - Group token accounts by owner wallet
   - Sum balances per wallet
   - Sort by balance descending

5. **Calculate Percentages**:
   - Get token supply: `client.get_token_supply(token_mint)`
   - Calculate: `(wallet_balance / total_supply) * 100`

### Required Libraries:
- `base64` (built-in) for account data parsing
- `struct` (built-in) for binary data parsing
- Or use `spl-token` Python library if available

### API Endpoint to Update:
- `get_token_holders()` in `app.py` (currently returns empty list)

---

## 🔨 **3. Wallet Analyzer Tab** - NEEDS IMPLEMENTATION

### What's Missing:
- **Transaction History Parsing**: Parse last 300 transactions
- **Swap Detection**: Identify buy/sell transactions for specific token
- **Amount Calculation**: Calculate token amounts bought/sold
- **Price Calculation**: Calculate average buy/sell prices
- **PnL Calculation**: Net profit/loss

### Implementation Steps:

1. **Get Wallet Transactions**:
   ```python
   # Already have: get_signatures_for_address()
   sigs = client.get_signatures_for_address(wallet_pubkey, limit=300)
   ```

2. **Parse Each Transaction**:
   - Use `analyze_transaction()` pattern from Fresh Wallets
   - Check if transaction involves the target token
   - Determine if it's a BUY or SELL:
     - BUY: Wallet receives target token, sends SOL/other token
     - SELL: Wallet sends target token, receives SOL/other token

3. **Extract Token Amounts**:
   - Parse transaction `preBalances` and `postBalances`
   - Or parse `preTokenBalances` and `postTokenBalances` (for SPL tokens)
   - Calculate difference = amount bought/sold

4. **Calculate Prices**:
   - For each swap, calculate price: `sol_amount / token_amount`
   - Track average buy price and average sell price

5. **Calculate Current Balance**:
   - Get current token balance from token account
   - Or sum all buys minus all sells

6. **Calculate PnL**:
   ```python
   total_bought = sum(all_buy_amounts)
   total_sold = sum(all_sell_amounts)
   current_balance = get_current_token_balance(wallet, token)
   
   # Unrealized PnL: (current_balance * current_price) - (current_balance * avg_buy_price)
   # Realized PnL: (total_sold * avg_sell_price) - (total_bought * avg_buy_price)
   ```

### Required Data Structures:
- Track: `buys[]`, `sells[]`, `amounts`, `prices`, `timestamps`

### API Endpoint to Update:
- `analyze_wallet_pnl()` in `app.py` (currently returns placeholder)

---

## 🔨 **4. Funded Wallets Tab** - NEEDS IMPLEMENTATION

### What's Missing:
- **Funding Transaction Detection**: Identify SOL/token transfers TO wallets
- **Buy Transaction Correlation**: Link funding to subsequent buys
- **Time Window Analysis**: Check if buy happened within X minutes of funding

### Implementation Steps:

1. **Scan Pool Transactions** (similar to Fresh Wallets):
   ```python
   # Get all transactions from pool
   sigs = client.get_signatures_for_address(pool_pubkey, limit=1000)
   ```

2. **For Each Buy Transaction**:
   - Extract buyer wallet (already done in `analyze_transaction`)
   - Check buyer's recent transaction history

3. **Check for Funding**:
   ```python
   # Get buyer's last 50 transactions
   buyer_sigs = client.get_signatures_for_address(buyer_pubkey, limit=50)
   
   for sig in buyer_sigs:
       tx = client.get_transaction(sig)
       # Check if transaction is a TRANSFER (not swap)
       # Look for: "Transfer" in logs, or check instruction type
       # Check if transfer is TO the buyer (not FROM)
       # Check timestamp - must be within last 24 hours and before the buy
   ```

4. **Identify Transfer Transactions**:
   - Look for `System Program` transfers (SOL)
   - Look for `Token Program` transfers (SPL tokens)
   - Check `preBalances`/`postBalances` changes
   - Verify recipient is the buyer wallet

5. **Time Correlation**:
   - Funding time < Buy time
   - Buy time - Funding time < threshold (e.g., 1 hour)

6. **Return Results**:
   ```python
   {
       'wallet': buyer_address,
       'funding_amount': sol_or_token_amount,
       'funding_time': timestamp,
       'buy_time': buy_timestamp,
       'time_diff_minutes': minutes_between,
       'funding_tx': funding_signature,
       'buy_tx': buy_signature
   }
   ```

### API Endpoint to Update:
- `get_funded_wallets()` in `app.py` (currently returns empty list)

---

## 🔨 **5. Common Traders Tab** - NEEDS IMPLEMENTATION

### What's Missing:
- **PnL Calculation for Token 1**: Use Wallet Analyzer logic
- **PnL Calculation for Token 2**: Use Wallet Analyzer logic
- **Trader Ranking**: Rank by combined PnL
- **Overlap Detection**: Find wallets profitable in both

### Implementation Steps:

1. **Get Top Traders for Token 1**:
   - Scan all transactions involving Token 1
   - For each wallet, calculate PnL (use Wallet Analyzer logic)
   - Rank by PnL, take top 50

2. **Get Top Traders for Token 2**:
   - Same process for Token 2
   - Rank by PnL, take top 50

3. **Find Common Wallets**:
   ```python
   token1_traders = {wallet: pnl for wallet, pnl in top_50_token1}
   token2_traders = {wallet: pnl for wallet, pnl in top_50_token2}
   
   common = {}
   for wallet in token1_traders:
       if wallet in token2_traders:
           common[wallet] = {
               'token1_pnl': token1_traders[wallet],
               'token2_pnl': token2_traders[wallet],
               'combined_pnl': token1_traders[wallet] + token2_traders[wallet]
           }
   ```

4. **Filter MEV Bots**:
   - Common bot addresses (can maintain a list)
   - Or filter by transaction patterns (many small trades)

5. **Sort and Return**:
   - Sort by combined PnL
   - Return top results

### Dependencies:
- Requires Wallet Analyzer to be implemented first
- Can reuse `analyze_wallet_pnl()` function

### API Endpoint to Update:
- `get_common_traders()` in `app.py` (currently returns empty list)

---

## 🔨 **6. Floor Price Tab** - NEEDS IMPLEMENTATION

### What's Missing:
- **Buy Transaction Parsing**: Extract all buy transactions from pool
- **Price Extraction**: Calculate price from each buy
- **Minimum Price Tracking**: Track lowest price over time
- **Real-time Updates**: Update as new transactions occur

### Implementation Steps:

1. **Scan Pool Transactions** (similar to Fresh Wallets):
   ```python
   # Get transactions from pool within time range
   sigs = client.get_signatures_for_address(pool_pubkey, limit=1000)
   ```

2. **For Each Transaction**:
   - Check if it's a swap (already done in `analyze_transaction`)
   - Determine if it's a BUY (token amount increases in pool, SOL decreases)
   - Extract amounts:
     - SOL amount sent
     - Token amount received

3. **Calculate Price**:
   ```python
   price = sol_amount / token_amount
   ```

4. **Track Minimum**:
   ```python
   floor_price = min(all_buy_prices)
   floor_tx = transaction_with_floor_price
   floor_time = timestamp_of_floor_price
   ```

5. **Real-time Monitoring**:
   - Similar to Fresh Wallets live monitoring
   - Check new transactions
   - Update floor price if new buy is lower

6. **Return Results**:
   ```python
   {
       'floor_price': min_price,
       'floor_price_sol': min_price_in_sol,
       'floor_tx': signature,
       'floor_time': timestamp,
       'current_price': latest_buy_price,
       'total_buys_analyzed': count,
       'price_history': [(time, price), ...]  # Optional: for chart
   }
   ```

### API Endpoint to Update:
- `get_floor_price()` in `app.py` (currently returns placeholder)

---

## 📦 **Required Dependencies**

### Already Installed:
- `solana` - Solana RPC client
- `solders` - Solana data structures
- `flask` - Web framework
- `flask-socketio` - Real-time updates

### May Need to Add:
- `base58` - For address encoding/decoding (may already be in solders)
- `struct` - For binary data parsing (built-in)
- `base64` - For account data decoding (built-in)

### Optional but Helpful:
- `pandas` - For data analysis (if doing complex calculations)
- `numpy` - For numerical operations (if calculating statistics)

---

## 🎯 **Implementation Priority**

1. **Floor Price** - Easiest, similar to Fresh Wallets logic
2. **Wallet Analyzer** - Core functionality, needed for Common Traders
3. **Funded Wallets** - Moderate complexity, reuses transaction parsing
4. **Top Holders** - Requires SPL token account parsing (more complex)
5. **Common Traders** - Depends on Wallet Analyzer being complete

---

## 🔍 **Key Solana Concepts Needed**

1. **SPL Token Accounts**:
   - Token accounts are separate from wallet accounts
   - Each token account has: owner, mint, amount
   - Use `getProgramAccounts` to find all token accounts for a mint

2. **Transaction Parsing**:
   - `preBalances` / `postBalances` - SOL balance changes
   - `preTokenBalances` / `postTokenBalances` - SPL token balance changes
   - `log_messages` - Program logs (for swap detection)
   - `instructions` - Transaction instructions

3. **Program IDs**:
   - Token Program: `TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA`
   - System Program: `11111111111111111111111111111111`
   - Raydium Program: Various (need to identify from transaction)

---

## 📝 **Notes**

- All implementations should follow the same error handling pattern as `analyze_transaction()`
- Use retry logic for RPC calls (already implemented in Fresh Wallets)
- Consider rate limiting - Helius API has limits
- Cache results where possible to reduce RPC calls
- Use async/threading for long-running operations (already set up)

---

## 🚀 **Quick Start for Each Feature**

### Top Holders:
```python
# 1. Get token mint
# 2. Use getProgramAccounts with Token Program filter
# 3. Parse account data to extract owner + balance
# 4. Aggregate and sort
```

### Wallet Analyzer:
```python
# 1. Get wallet's last 300 transactions
# 2. For each, check if it involves target token
# 3. Parse token balance changes
# 4. Calculate PnL
```

### Funded Wallets:
```python
# 1. Get pool transactions (buys)
# 2. For each buyer, check their recent transactions
# 3. Find transfers TO the buyer
# 4. Check time correlation
```

### Common Traders:
```python
# 1. Get top 50 traders for token1 (using Wallet Analyzer)
# 2. Get top 50 traders for token2 (using Wallet Analyzer)
# 3. Find intersection
# 4. Filter bots, sort by combined PnL
```

### Floor Price:
```python
# 1. Get pool transactions
# 2. Filter for buys
# 3. Calculate price for each buy
# 4. Track minimum
```



