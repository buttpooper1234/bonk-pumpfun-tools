# BONK & PumpFun Token Analysis Tools

Windows 98-style Solana token analysis tools for BONK/USD1 and PumpFun coins. Features fresh wallet scanner, wallet PnL analyzer, funded wallet tracker, floor price monitor, and AI-powered GitHub repository checks.

## 🎯 Features

- **🆕 Fresh Wallet Scanner**: Scans pools for wallets with low transaction counts (configurable limit)
- **📊 Wallet Analyzer**: Analyzes profit and loss (PnL) for specific tokens
- **💰 Funded Wallets**: Finds wallets that received funding and then bought tokens
- **📉 Floor Price Tracker**: Monitors minimum buy prices from pool transactions
- **🔍 GitHub Check**: AI-powered analysis of GitHub repository legitimacy
- **💚 PumpFun Support**: Dedicated tools for PumpFun coin analysis
- **🎨 Retro UI**: Windows 98-style interface with theme switching (BONK orange/yellow, PumpFun green/white)

## 📋 Prerequisites

- **Python 3.8 or higher** ([Download Python](https://www.python.org/downloads/))
- **pip** (Python package manager, usually included with Python)
- **Helius API Key** (free tier available) - See "Getting an API Key" section below
- **Git** (optional, for cloning the repository)

## 🚀 Installation

### Step 1: Clone or Download the Repository

If you have Git installed:
```bash
git clone https://github.com/buttpooper1234/bonk-pumpfun-tools.git
cd bonk-pumpfun-tools
```

Or download the ZIP file from GitHub and extract it to a folder.

### Step 2: Install Python Dependencies

Open a terminal/command prompt in the project folder and run:

```bash
pip install -r requirements.txt
```

This will install:
- `solana` - Solana Python SDK
- `solders` - Solana account and transaction handling
- `flask` - Web framework
- `flask-socketio` - Real-time WebSocket communication
- `requests` - HTTP library for API calls
- `python-dotenv` - Environment variable management

**Note for Windows users**: If you get permission errors, try:
```bash
python -m pip install -r requirements.txt
```

## 🔑 Getting an API Key (Helius RPC)

This application requires a Solana RPC endpoint. We recommend using **Helius** (free tier available with generous rate limits).

### Step 1: Get Your API Key

1. Go to [https://www.helius.dev/](https://www.helius.dev/)
2. Click **"Get Started"** or **"Sign Up"**
3. Create a free account
4. Once logged in, navigate to your **Dashboard**
5. Create a new API key (or use the default one)
6. Copy your API key (it will look like: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`)

**Free Tier Limits**: 
- 100,000 requests per day
- Perfect for personal use and testing

### Step 2: Create .env File

Create a file named `.env` in the project root folder with:

```
HELIUS_API_KEY=your-actual-api-key-here
```

**Important**: 
- Replace `your-actual-api-key-here` with your real API key from Helius
- Never commit the `.env` file to Git (it's already in `.gitignore`)
- The `.env.example` file is just a template - don't put your real key there

### Step 3: Verify Setup

The application will check your API key on startup. If there's an error, it will tell you what's wrong.

## ⚙️ Configuration (Optional)

You can customize these settings in `app.py` if needed:

```python
DEFAULT_POOL = "rnMLBLnUueJbBo6uZ3ibonk"  # Default pool address
MAX_HISTORY_LIMIT = 10                    # Default transaction limit for fresh wallets
CHECK_INTERVAL = 3                        # Seconds between checks (increase if rate limited)
```

## 🏃 Running the Application

### Start the Server

In your terminal/command prompt, navigate to the project folder and run:

```bash
python app.py
```

You should see output like:
```
============================================================
Starting BONK & PumpFun Token Analysis Tools
============================================================
RPC Endpoint: https://mainnet.helius-rpc.com/...
Server will start on http://localhost:5000
============================================================
 * Running on http://127.0.0.1:5000
```

### Access the Application

Open your web browser and go to:
```
http://localhost:5000
```

or

```
http://127.0.0.1:5000
```

## 📖 How to Use

### Fresh Wallet Scanner

1. Click the **"Fresh Wallets"** icon on the desktop
2. Enter a **BONK/USD1 pool address** (or PumpFun pool if using PumpFun theme)
3. Set the **Transaction Limit** (default: 10) - only wallets with this many transactions or fewer will be shown
4. Select a **Time Range** (30 minutes to 3 days)
5. Click **"Start Scan"**
6. Fresh wallets will appear in real-time with:
   - Wallet address
   - Transaction count
   - Transaction time
   - Current holding status (✓ HOLDING or ⚠️ SOLD ALL)
   - Links to view on Solscan

### Wallet Analyzer

1. Click the **"Wallet Analyzer"** icon
2. Enter a **Wallet Address**
3. Enter a **Token Address** (BONK/USD1 or PumpFun token)
4. Select a **Time Range**
5. Click **"Analyze Wallet"**
6. View:
   - Total bought/sold amounts
   - Current balance
   - Profit/Loss (PnL)
   - Average buy/sell prices
   - Transaction counts

**Note**: Only wallets currently holding tokens will be analyzed.

### Funded Wallets

1. Click the **"Funded Wallets"** icon
2. Enter a **Pool Address**
3. Select a **Time Range**
4. Click **"Get Funded Wallets"**
5. View wallets that:
   - Received funding (SOL transfers)
   - Then bought from the pool
   - Shows current holding status

### Floor Price

1. Click the **"Floor Price"** icon
2. Enter a **Pool Address**
3. Select a **Time Range**
4. Click **"Get Floor Price"**
5. View the minimum buy price from pool transactions

### GitHub Check

1. Click the **"GitHub Check"** icon
2. Enter a **GitHub Repository URL** (e.g., `https://github.com/user/repo`)
3. Optionally enter a **Token Address** for context
4. Click **"Check Repository"**
5. View AI-powered analysis:
   - Repository legitimacy score
   - Red/green flags
   - Detailed analysis
   - Verdict

### Theme Switching

- **BONK Theme** (default): Orange/yellow gradient theme
- **PumpFun Theme**: Green/white gradient theme
  - Click the **"PumpFun"** icon to switch to PumpFun theme
  - Click the **"BONK Tools"** icon to switch back to BONK theme

## 📁 Project Structure

```
bonk-pumpfun-tools/
├── app.py                    # Main Flask application
├── requirements.txt          # Python dependencies
├── scan_fresh.py            # Standalone fresh wallet scanner (CLI)
├── .env.example             # Environment variable template
├── .gitignore              # Git ignore rules
├── fresh_wallets.txt        # Log file for detected wallets (auto-generated)
├── templates/
│   ├── dashboard.html      # Main web interface
│   ├── dashboard_backup.html
│   ├── dashboard_win98.html
│   └── index.html
├── IMPLEMENTATION_GUIDE.md  # Development guide
└── PUMPFUN_PLAN.md         # PumpFun feature plan
```

## 🔧 Customization

### Changing the Port

Edit `app.py` at the bottom and change:

```python
if __name__ == '__main__':
    socketio.run(app, debug=False, host='0.0.0.0', port=5000)  # Change 5000 to your desired port
```

### Using a Different RPC Provider

If using QuickNode or another provider, modify the RPC_URL in `app.py`:

```python
# QuickNode example
RPC_URL = "https://your-endpoint.solana-mainnet.quiknode.pro/YOUR_API_KEY/"

# Alchemy example
RPC_URL = "https://solana-mainnet.g.alchemy.com/v2/YOUR_API_KEY"
```

### Adjusting Rate Limits

If you're getting rate limited, increase `CHECK_INTERVAL` in `app.py`:

```python
CHECK_INTERVAL = 5  # Increase from 3 to 5 seconds
```

## 🐛 Troubleshooting

### "ModuleNotFoundError" or Import Errors

Make sure all dependencies are installed:
```bash
pip install -r requirements.txt
```

### "Connection Error" or RPC Timeouts

1. Check your internet connection
2. Verify your API key is correct in the `.env` file
3. Check if you've exceeded your RPC provider's rate limits
4. Try increasing `CHECK_INTERVAL` in `app.py`

### Port Already in Use

If port 5000 is already in use:
1. Change the port in `app.py` (see "Customization" section)
2. Or stop the other application using port 5000

### "HELIUS_API_KEY not set" Error

1. Make sure you created a `.env` file in the project root
2. Check that the file contains: `HELIUS_API_KEY=your-key-here`
3. Make sure there are no spaces around the `=` sign
4. Restart the application

### Windows Console Encoding Issues

The application automatically fixes Windows console encoding. If you still see issues, ensure you're using Python 3.8+.

## 📝 Notes

- **Logs**: Fresh wallets are automatically logged to `fresh_wallets.txt`
- **Real-time Updates**: The application uses WebSockets for real-time wallet detection
- **Rate Limits**: Be mindful of your RPC provider's rate limits. Free tiers are usually sufficient for personal use.
- **Token Specificity**: 
  - BONK tab works with BONK/USD1 tokens only
  - PumpFun tab works with PumpFun coins only
- **Security**: Never share your `.env` file or commit it to Git. Your API key is private.

## 🤝 Contributing

Feel free to fork this project and customize it for your needs! Some ideas:
- Add support for other token types
- Implement additional analysis features
- Improve the UI/UX
- Add more RPC provider options
- Create mobile-responsive design

## ⚠️ Disclaimer

This tool is for educational and research purposes. Always do your own research (DYOR) before making any investment decisions. The authors are not responsible for any financial losses.

## 📄 License

MIT License - See [LICENSE](LICENSE) file for details.

## 🙏 Credits

Built with:
- Flask & Flask-SocketIO
- Solana Python SDK
- Helius RPC (or your chosen provider)

---

**Enjoy analyzing Solana tokens! 🚀**
