@echo off
REM Options Bot Startup Script for Windows
REM Make sure TWS or IB Gateway is running first!

echo ============================================
echo    OPTIONS CREDIT SPREAD BOT
echo ============================================
echo.

REM Check if TWS/Gateway is likely running
netstat -an | find "7497" >nul
if %errorlevel%==0 (
    echo [OK] Port 7497 is open - TWS/Gateway detected
) else (
    echo [WARNING] Port 7497 not found
    echo Please start TWS or IB Gateway first!
    echo.
    echo TWS: Enable API at Configure ^> API ^> Settings
    echo      Check "Enable ActiveX and Socket Clients"
    echo      Port: 7497 ^(paper^) or 7496 ^(live^)
    echo.
    pause
    exit /b 1
)

echo.
echo Starting bot...
echo.

REM Activate venv if exists
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

REM Run the bot
python main_v2.py %1

pause
