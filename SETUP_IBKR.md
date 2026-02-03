# IBKR Local Setup Guide

## Quick Start (5 minutes)

### 1. Install Dependencies
```bash
cd options_bot
pip install -r requirements.txt
```

### 2. Configure TWS/Gateway

Open TWS or IB Gateway, then:

1. Go to **Configure** → **API** → **Settings**
2. Enable these options:
   - ☑️ Enable ActiveX and Socket Clients
   - ☑️ Read-Only API (uncheck this later for live trading)
   - ☐ Download open orders on connection
3. Set **Socket port**: `7497` (paper) or `7496` (live)
4. Add `127.0.0.1` to **Trusted IPs**
5. Click **Apply** and **OK**

### 3. Configure Telegram (Optional)

Edit `config_v2.py`:
```python
config.telegram.bot_token = "your_bot_token"
config.telegram.chat_id = "your_chat_id"
```

### 4. Run the Bot

**Test mode** (single scan, no trades):
```bash
python main_v2.py test
```

**Analysis mode** (shows what it would do):
```bash
python main_v2.py analysis
```

**Live mode** (full automation):
```bash
python main_v2.py run
```

Or use the startup scripts:
- Windows: `start_bot.bat`
- Mac/Linux: `./start_bot.sh`

---

## Deployment Options

### Option A: Run on Your PC (Simplest)
- Keep TWS/Gateway open
- Run bot in terminal or as scheduled task
- Works great for paper trading

### Option B: VPS with IB Gateway (24/7)
When ready for automation:

1. Get a VPS (DigitalOcean, Vultr, ~$6/month)
2. Install IB Gateway (headless version)
3. Use IBC (IB Controller) for auto-restart
4. Deploy bot alongside

I can provide detailed VPS setup when you're ready.

### Option C: Your PC + Keep Alive
- Use a keep-alive script to prevent sleep
- Schedule bot to run during market hours
- Good middle ground

---

## Testing Checklist

Before running live:

- [ ] TWS/Gateway API enabled on port 7497
- [ ] Paper trading account selected
- [ ] Run `python test_v2.py` - all tests pass
- [ ] Run `python main_v2.py test` - connects to IBKR
- [ ] Check Telegram notifications working
- [ ] Review positions in TWS match bot's tracking

---

## Common Issues

**"Connection refused"**
→ TWS/Gateway not running or API not enabled

**"Port 7497 not found"**
→ Check TWS API settings, restart TWS

**"No market data"**
→ Paper account may need market data subscription
→ Or run during market hours (9:30 AM - 4 PM ET)

**"Order rejected"**
→ Check buying power in TWS
→ Verify paper account has options permissions

---

## Market Hours

Bot only trades during:
- **Entry window**: 10:00 AM - 3:00 PM ET
- **Position management**: 9:30 AM - 4:00 PM ET

Outside these hours, it sleeps and waits.
