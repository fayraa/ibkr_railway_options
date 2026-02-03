# Railway Deployment Guide

Deploy the Options Bot with IB Gateway on Railway for 24/7 automated trading.

## Prerequisites

1. **Railway account** (https://railway.app)
2. **IBKR account** with:
   - Paper trading enabled
   - API access enabled
   - Know your username/password

## Step 1: Prepare Repository

Push the options_bot folder to a GitHub repo:

```bash
cd options_bot
git init
git add .
git commit -m "Options trading bot"
git remote add origin https://github.com/YOUR_USERNAME/options-bot.git
git push -u origin main
```

## Step 2: Create Railway Project

1. Go to https://railway.app/dashboard
2. Click **"New Project"**
3. Select **"Deploy from GitHub repo"**
4. Connect your GitHub and select the options-bot repo

## Step 3: Configure Environment Variables

In Railway dashboard, go to **Variables** and add:

### Required (as Secrets)
```
TWS_USERID=your_ibkr_username
TWS_PASSWORD=your_ibkr_password
TRADING_MODE=paper
```

### Optional
```
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
AUTO_EXECUTE=true
MAX_RISK_PER_TRADE=100
MAX_POSITIONS=5
UNDERLYINGS=SPY,QQQ,IWM
```

**Note:** The base image uses `TWS_USERID` and `TWS_PASSWORD` (not `IBKR_USERNAME`)

## Step 4: Deploy

Railway will automatically:
1. Build the Docker image
2. Start IB Gateway
3. Start the options bot
4. Connect them together

## Step 5: Monitor

### View Logs
- Click on your service in Railway dashboard
- Go to **"Logs"** tab
- You should see:
  - `[OK] IB Gateway is accepting connections!`
  - `Starting Options Bot`
  - Trade signals and analysis

### Check Status
The bot logs will show:
```
╔═══════════════════════════════════════════════════════════╗
║     OPTIONS CREDIT SPREAD TRADING BOT V2                  ║
╚═══════════════════════════════════════════════════════════╝
```

## Important Notes

### IBKR 2FA
- **Paper trading**: Usually no 2FA required
- **Live trading**: You may need to set up IBKR mobile 2FA

### Daily Restarts
IB Gateway restarts daily (IBKR requirement). The supervisor will:
1. Detect the restart
2. Wait for Gateway to come back
3. Reconnect the bot automatically

### Costs
- **Railway**: ~$5-20/month depending on usage
- **IBKR**: Commission only ($0.65/contract)

### Market Hours
Bot only trades during US market hours:
- Entry: 10:00 AM - 3:00 PM ET
- Management: 9:30 AM - 4:00 PM ET

Outside hours, it sleeps (minimal resource usage).

## Troubleshooting

### "Connection refused"
- Check IBKR_USERNAME and IBKR_PASSWORD are correct
- Verify paper trading is enabled on your IBKR account

### "No market data"
- Paper accounts have limited market data
- Data is only available during market hours

### Bot not starting
Check logs for:
1. IB Gateway startup errors
2. Authentication failures
3. Python errors

### Railway build fails
- Ensure all files are committed to git
- Check Dockerfile.railway exists
- Verify docker/ folder is included

## Switching to Live Trading

When ready for live trading:

1. Change environment variable:
   ```
   TRADING_MODE=live
   ```

2. Use live IBKR port (update if needed):
   ```
   IBKR_PORT=4001
   ```

3. Ensure your IBKR account has:
   - Options trading permissions
   - Sufficient buying power
   - Market data subscriptions

4. Start with small position sizes!

## Local Docker Testing

Test locally before deploying:

```bash
# Build
docker build -f Dockerfile.railway -t options-bot .

# Run
docker run -it \
  -e TWS_USERID=your_username \
  -e TWS_PASSWORD=your_password \
  -e TRADING_MODE=paper \
  options-bot
```

## Support

If you hit issues:
1. Check Railway logs first
2. Verify IBKR credentials work in TWS
3. Test locally with Docker before Railway
