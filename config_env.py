"""
Environment-aware configuration loader
Reads settings from environment variables for Docker/Railway deployment
"""
import os
from config_v2 import (
    BotConfig, IBKRConfig, TelegramConfig, 
    VolatilityConfig, FlowConfig, SpreadConfig, 
    RiskConfig, TradingConfig
)


def load_config_from_env() -> BotConfig:
    """
    Load configuration from environment variables
    Falls back to defaults if not set
    """
    config = BotConfig()
    
    # IBKR Settings
    config.ibkr.host = os.getenv('IBKR_HOST', '127.0.0.1')
    config.ibkr.port = int(os.getenv('IBKR_PORT', '4001'))  # 4001 for Gateway, 7497 for TWS
    config.ibkr.client_id = int(os.getenv('IBKR_CLIENT_ID', '1'))
    
    # Telegram Settings
    config.telegram.bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    config.telegram.chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
    config.telegram.enabled = bool(config.telegram.bot_token and config.telegram.chat_id)
    
    # Trading Settings
    trading_mode = os.getenv('IBKR_TRADING_MODE', 'paper').lower()
    config.trading.paper_trading = (trading_mode == 'paper')
    
    # Timezone (default to Singapore)
    config.trading.local_timezone = os.getenv('LOCAL_TIMEZONE', 'Asia/Singapore')
    
    # Auto-execute (disable for signal-only mode)
    config.trading.auto_execute = os.getenv('AUTO_EXECUTE', 'true').lower() == 'true'
    
    # Risk Settings (can override via env)
    if os.getenv('MAX_RISK_PER_TRADE'):
        config.risk.max_risk_per_trade = float(os.getenv('MAX_RISK_PER_TRADE'))
    
    if os.getenv('MAX_POSITIONS'):
        config.risk.max_positions = int(os.getenv('MAX_POSITIONS'))
    
    # Underlyings to trade
    if os.getenv('UNDERLYINGS'):
        config.spread.underlyings = os.getenv('UNDERLYINGS').split(',')
    
    return config


def print_config_summary(config: BotConfig):
    """Print configuration summary for logging"""
    print(f"""
╔═══════════════════════════════════════════════════════════╗
║              CONFIGURATION SUMMARY                        ║
╚═══════════════════════════════════════════════════════════╝

IBKR Connection:
  Host: {config.ibkr.host}
  Port: {config.ibkr.port}
  
Trading Mode:
  Paper Trading: {config.trading.paper_trading}
  Auto Execute: {config.trading.auto_execute}
  
Telegram:
  Enabled: {config.telegram.enabled}
  
Risk Settings:
  Max Risk/Trade: ${config.risk.max_risk_per_trade}
  Max Positions: {config.risk.max_positions}
  
Underlyings: {', '.join(config.spread.underlyings)}
""")
