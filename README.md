# Options Credit Spread Trading Bot

Automated options trading bot for IBKR that trades credit spreads based on market regime detection.

## Features

- **Regime Detection**: Analyzes VIX, trend (SMA crossover), and RSI to determine market regime
- **Automatic Strategy Selection**:
  - Bullish regime → Bull Put Spreads
  - Bearish regime → Bear Call Spreads  
  - Sideways/High Vol → Iron Condors
- **Position Management**: Tracks open positions with profit targets and stop losses
- **Telegram Notifications**: Trade alerts, daily summaries, regime changes
- **Risk Management**: Position sizing, max positions, DTE-based exits

## Prerequisites

1. **IBKR Account**: You need an Interactive Brokers account
2. **TWS or IB Gateway**: Download and install from [IBKR](https://www.interactivebrokers.com/en/trading/tws.php)
3. **Python 3.10+**: Required for the bot
4. **Telegram Bot** (optional): For notifications

## Setup Instructions

### Step 1: IBKR Paper Trading Setup

1. Log into your IBKR account
2. Go to **Account Settings** → **Paper Trading** → Enable paper trading
3. Download **Trader Workstation (TWS)** or **IB Gateway**
4. Log into TWS/Gateway with your paper trading credentials

### Step 2: Configure TWS/Gateway API

1. In TWS: **File** → **Global Configuration** → **API** → **Settings**
2. Enable these options:
   - ☑️ Enable ActiveX and Socket Clients
   - ☑️ Allow connections from localhost only
   - ☐ Read-Only API (UNCHECK this!)
3. Set Socket port: **7497** (paper) or 7496 (live)
4. Click **Apply** and **OK**

### Step 3: Install the Bot

```bash
# Clone/download the bot files to a directory
cd options_bot

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Step 4: Configure the Bot

Edit `config.py` to customize settings:

```python
# IBKR Connection
@dataclass
class IBKRConfig:
    host: str = "127.0.0.1"
    port: int = 7497  # 7497 for paper, 7496 for live
    client_id: int = 1

# Telegram (optional)
@dataclass  
class TelegramConfig:
    bot_token: str = "YOUR_BOT_TOKEN"  # Get from @BotFather
    chat_id: str = "YOUR_CHAT_ID"      # Get from @userinfobot
    enabled: bool = True

# Spread parameters
@dataclass
class SpreadConfig:
    underlyings: List[str] = ["SPY", "QQQ", "IWM"]
    target_delta: float = 0.25      # Short strike delta
    spread_width: int = 5           # Dollar width
    target_dte: int = 35            # Days to expiration

# Risk management
@dataclass
class RiskConfig:
    max_risk_per_trade: float = 100.0  # Max $ risk per trade
    max_positions: int = 5              # Max concurrent positions
    profit_target_pct: float = 0.50     # Close at 50% profit
    stop_loss_multiplier: float = 2.0   # Close at 2x loss
```

### Step 5: Run the Bot

```bash
# Test mode - single scan without executing
python main.py test

# View portfolio
python main.py portfolio

# Full automated mode
python main.py run
```

## How It Works

### Regime Detection

The bot analyzes three factors:

1. **VIX Level**
   - < 15: Low volatility
   - 15-25: Normal
   - 25-35: High volatility
   - > 35: Extreme (no trades)

2. **Trend (SMA)**
   - Fast SMA (20) > Slow SMA (50) by 2%+ → Bullish
   - Fast SMA < Slow SMA by 2%+ → Bearish
   - Otherwise → Sideways

3. **RSI (14)**
   - < 30: Oversold
   - > 70: Overbought
   - 30-70: Neutral

### Strategy Selection

| Regime | Strategy | Logic |
|--------|----------|-------|
| Bullish | Bull Put Spread | Sell put below market, collect premium |
| Bearish | Bear Call Spread | Sell call above market, collect premium |
| Sideways | Iron Condor | Sell both sides, profit from range |
| High Vol | Iron Condor | Rich premiums, sell both sides |
| Extreme | No Trade | Too risky |

### Exit Rules

Positions are closed when:
- **Profit Target**: P&L reaches 50% of credit received
- **Stop Loss**: P&L reaches 2x credit as a loss
- **DTE Exit**: 21 days until expiration (avoid gamma risk)

## File Structure

```
options_bot/
├── config.py           # Configuration settings
├── ibkr_client.py      # IBKR API wrapper
├── regime_detector.py  # Market regime analysis
├── spread_builder.py   # Credit spread construction
├── executor.py         # Order execution
├── position_manager.py # Position tracking
├── notifier.py         # Telegram notifications
├── main.py             # Main bot loop
├── requirements.txt    # Dependencies
├── positions.json      # Persisted positions (auto-created)
└── options_bot.log     # Log file (auto-created)
```

## Telegram Setup (Optional)

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow prompts
3. Copy the bot token
4. Message [@userinfobot](https://t.me/userinfobot) to get your chat ID
5. Add both to `config.py`

## Troubleshooting

### "Failed to connect to IBKR"
- Ensure TWS/Gateway is running
- Check the port (7497 for paper, 7496 for live)
- Verify API is enabled in TWS settings
- Make sure "Read-Only API" is unchecked

### "No options chains found"
- Market might be closed
- Symbol might not have options
- Try again during market hours

### "Could not get price for XYZ"
- Market data subscription needed
- Check IBKR market data permissions

### "Order rejected"
- Check buying power
- Verify option contract exists
- Check trading permissions

## Important Notes

⚠️ **This is for paper trading / educational purposes**

- Always test thoroughly before any live trading
- Understand the risks of options trading
- Past performance doesn't guarantee future results
- This bot is a starting point, not financial advice

## Customization Ideas

1. **Add more underlyings**: Edit `SpreadConfig.underlyings`
2. **Adjust delta**: Higher delta = more premium, more risk
3. **Change DTE**: Longer DTE = more theta, slower decay
4. **Add filters**: IV rank, earnings dates, etc.
5. **Integrate your FX regime signals**: Use macro data to inform regime

## Next Steps

1. Run in test mode to verify everything works
2. Monitor paper trades for a few weeks
3. Analyze results and adjust parameters
4. Consider additional filters (IV rank, earnings, etc.)
5. Only consider live trading after extensive testing

Good luck! 🎯
