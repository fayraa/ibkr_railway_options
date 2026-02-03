#!/bin/bash
# Options Bot Startup Script for Mac/Linux
# Make sure TWS or IB Gateway is running first!

echo "============================================"
echo "   OPTIONS CREDIT SPREAD BOT"
echo "============================================"
echo ""

# Check if TWS/Gateway is running
if lsof -i :7497 > /dev/null 2>&1; then
    echo "[OK] Port 7497 is open - TWS/Gateway detected"
else
    echo "[WARNING] Port 7497 not found"
    echo "Please start TWS or IB Gateway first!"
    echo ""
    echo "TWS: Enable API at Configure > API > Settings"
    echo "     Check 'Enable ActiveX and Socket Clients'"
    echo "     Port: 7497 (paper) or 7496 (live)"
    echo ""
    exit 1
fi

echo ""
echo "Starting bot..."
echo ""

# Activate venv if exists
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

# Run the bot
python main_v2.py ${1:-run}
