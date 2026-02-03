"""
Configuration settings for the Options Trading Bot
"""
from dataclasses import dataclass, field
from typing import List
from enum import Enum


class Regime(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    SIDEWAYS = "sideways"
    HIGH_VOL = "high_volatility"
    UNKNOWN = "unknown"


class Strategy(Enum):
    BULL_PUT_SPREAD = "bull_put_spread"
    BEAR_CALL_SPREAD = "bear_call_spread"
    IRON_CONDOR = "iron_condor"
    NO_TRADE = "no_trade"


@dataclass
class IBKRConfig:
    """Interactive Brokers connection settings"""
    host: str = "127.0.0.1"
    port: int = 7497  # 7497 for paper, 7496 for live
    client_id: int = 1
    timeout: int = 30
    readonly: bool = False


@dataclass
class TelegramConfig:
    """Telegram notification settings"""
    bot_token: str = ""  # Your Telegram bot token
    chat_id: str = ""    # Your Telegram chat ID
    enabled: bool = True


@dataclass
class RegimeConfig:
    """Regime detection parameters"""
    # VIX thresholds
    vix_low: float = 15.0      # Below this = low vol environment
    vix_high: float = 25.0     # Above this = high vol environment
    vix_extreme: float = 35.0  # Above this = no trade
    
    # Trend detection (SMA-based)
    fast_sma: int = 20
    slow_sma: int = 50
    trend_threshold: float = 0.02  # 2% above/below for trend confirmation
    
    # RSI settings
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0


@dataclass
class SpreadConfig:
    """Credit spread construction parameters"""
    # Underlyings to trade
    underlyings: List[str] = field(default_factory=lambda: ["SPY", "QQQ", "IWM"])
    
    # Strike selection
    target_delta: float = 0.25       # Short strike delta (0.15-0.30)
    delta_range: tuple = (0.15, 0.35)  # Acceptable delta range
    spread_width: int = 5            # Dollar width of spreads
    
    # DTE targeting
    min_dte: int = 25
    max_dte: int = 50
    target_dte: int = 35
    
    # Premium requirements
    min_credit: float = 0.50         # Minimum credit to collect
    min_credit_pct: float = 0.10     # Min credit as % of width (10%)


@dataclass
class RiskConfig:
    """Risk management parameters"""
    # Position sizing
    max_risk_per_trade: float = 100.0    # Max dollar risk per trade
    max_positions: int = 5               # Max concurrent positions
    max_delta_exposure: float = 50.0     # Max portfolio delta
    
    # Exit rules
    profit_target_pct: float = 0.50      # Close at 50% of max profit
    stop_loss_multiplier: float = 2.0    # Close at 2x credit received
    min_dte_exit: int = 21               # Close positions at 21 DTE
    
    # Allocation per underlying
    max_positions_per_underlying: int = 2


@dataclass
class TradingConfig:
    """Trading schedule and behavior"""
    # Trading hours (Eastern Time)
    market_open_hour: int = 9
    market_open_minute: int = 30
    market_close_hour: int = 16
    market_close_minute: int = 0
    
    # Entry timing
    entry_start_hour: int = 10      # Don't enter before 10 AM
    entry_end_hour: int = 15        # Don't enter after 3 PM
    
    # How often to check for signals (seconds)
    scan_interval: int = 300        # 5 minutes
    position_check_interval: int = 60  # 1 minute
    
    # Paper trading mode
    paper_trading: bool = True


@dataclass
class BotConfig:
    """Master configuration"""
    ibkr: IBKRConfig = field(default_factory=IBKRConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    regime: RegimeConfig = field(default_factory=RegimeConfig)
    spread: SpreadConfig = field(default_factory=SpreadConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)


# Regime to Strategy mapping
REGIME_STRATEGY_MAP = {
    Regime.BULLISH: Strategy.BULL_PUT_SPREAD,
    Regime.BEARISH: Strategy.BEAR_CALL_SPREAD,
    Regime.SIDEWAYS: Strategy.IRON_CONDOR,
    Regime.HIGH_VOL: Strategy.IRON_CONDOR,  # Premium is rich
    Regime.UNKNOWN: Strategy.NO_TRADE,
}


def load_config() -> BotConfig:
    """
    Load configuration. In production, you'd load from env vars or a file.
    For now, returns default config that you can modify.
    """
    config = BotConfig()
    
    # Override with your settings
    # config.telegram.bot_token = "your_token_here"
    # config.telegram.chat_id = "your_chat_id_here"
    
    return config
