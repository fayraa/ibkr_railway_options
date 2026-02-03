"""
Configuration settings for the Options Trading Bot
Enhanced version with volatility-focused parameters
"""
from dataclasses import dataclass, field
from typing import List
from enum import Enum


# ============ Enums ============

class Strategy(Enum):
    BULL_PUT_SPREAD = "bull_put_spread"
    BEAR_CALL_SPREAD = "bear_call_spread"
    IRON_CONDOR = "iron_condor"
    NO_TRADE = "no_trade"


# ============ IBKR Config ============

@dataclass
class IBKRConfig:
    """Interactive Brokers connection settings"""
    host: str = "127.0.0.1"
    port: int = 7497  # 7497 for paper, 7496 for live
    client_id: int = 1
    timeout: int = 30
    readonly: bool = False


# ============ Telegram Config ============

@dataclass
class TelegramConfig:
    """Telegram notification settings"""
    bot_token: str = ""  # Your Telegram bot token
    chat_id: str = ""    # Your Telegram chat ID
    enabled: bool = True


# ============ Volatility Analysis Config ============

@dataclass
class VolatilityConfig:
    """IV and volatility analysis parameters"""
    
    # IV Rank thresholds (0-100)
    iv_rank_rich: float = 50.0      # Above = rich premium, SELL
    iv_rank_fair: float = 30.0      # Below = cheap, don't sell
    iv_rank_extreme: float = 80.0   # Above = potential crisis, careful
    
    # IV/HV ratio (implied vs historical)
    iv_hv_rich: float = 1.2         # IV 20%+ above HV = edge
    iv_hv_cheap: float = 0.9        # IV below HV = no edge
    
    # VIX thresholds
    vix_low: float = 15.0           # Low vol environment
    vix_high: float = 25.0          # Elevated vol
    vix_extreme: float = 35.0       # Crisis - no new trades
    
    # Term structure
    contango_threshold: float = 0.05      # VIX3M 5%+ above VIX
    backwardation_threshold: float = -0.02  # Fear signal
    
    # Expected move ratio
    move_ratio_edge: float = 1.3    # Expected 30%+ above realized = edge
    
    # Skew
    skew_put_rich: float = 3.0      # Put IV 3+ pts above call = sell puts


# ============ Flow Analysis Config ============

@dataclass
class FlowConfig:
    """Options flow analysis parameters"""
    
    # Volume thresholds
    unusual_volume_mult: float = 2.0  # 2x average = unusual
    vol_oi_unusual: float = 0.5       # Volume > 50% OI
    
    # Put/Call ratio
    pcr_bullish: float = 0.7         # Below = bullish sentiment
    pcr_bearish: float = 1.3         # Above = bearish/fearful


# ============ Spread Construction Config ============

@dataclass
class SpreadConfig:
    """Credit spread construction parameters"""
    
    # Underlyings to trade
    underlyings: List[str] = field(default_factory=lambda: ["SPY", "QQQ", "IWM"])
    
    # Strike selection
    target_delta: float = 0.20       # Short strike delta
    delta_range: tuple = (0.12, 0.30)  # Acceptable delta range
    spread_width: int = 5            # Dollar width of spreads
    
    # DTE targeting
    min_dte: int = 25
    max_dte: int = 50
    target_dte: int = 35
    
    # Premium requirements
    min_credit: float = 0.50         # Minimum credit to collect
    min_credit_pct: float = 0.10     # Min credit as % of width (10%)
    
    # Probability
    min_prob_otm: float = 0.70       # Minimum probability of profit


# ============ Risk Management Config ============

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
    
    # Earnings avoidance
    earnings_buffer_days: int = 7        # No trades if earnings within X days


# ============ Trading Schedule Config ============

@dataclass
class TradingConfig:
    """Trading schedule and behavior"""
    
    # Timezone setting
    # Options: 'US/Eastern', 'Asia/Singapore', etc.
    timezone: str = 'US/Eastern'
    
    # Trading hours (in US Eastern Time - when US market is open)
    # These are converted to local time automatically
    market_open_hour: int = 9
    market_open_minute: int = 30
    market_close_hour: int = 16
    market_close_minute: int = 0
    
    # Entry timing - avoid first 30min and last hour
    entry_start_hour: int = 10
    entry_end_hour: int = 15
    
    # Scan intervals (seconds)
    scan_interval: int = 300        # 5 minutes between scans
    position_check_interval: int = 60  # 1 minute for position mgmt
    
    # Mode
    paper_trading: bool = True
    auto_execute: bool = True       # If False, only alerts (no execution)
    
    # Local timezone for display/notifications
    local_timezone: str = 'Asia/Singapore'  # Change this to your timezone


# ============ Master Config ============

@dataclass
class BotConfig:
    """Master configuration combining all settings"""
    ibkr: IBKRConfig = field(default_factory=IBKRConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    volatility: VolatilityConfig = field(default_factory=VolatilityConfig)
    flow: FlowConfig = field(default_factory=FlowConfig)
    spread: SpreadConfig = field(default_factory=SpreadConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)


def load_config() -> BotConfig:
    """
    Load configuration. Modify values here or load from env/file.
    """
    config = BotConfig()
    
    # ===== CUSTOMIZE YOUR SETTINGS HERE =====
    
    # Telegram (reuse from your Pokemon bot)
    # config.telegram.bot_token = "your_bot_token"
    # config.telegram.chat_id = "your_chat_id"
    
    # Adjust IV thresholds if needed
    # config.volatility.iv_rank_rich = 45.0
    
    # Change underlyings
    # config.spread.underlyings = ["SPY", "QQQ"]
    
    # Adjust risk
    # config.risk.max_risk_per_trade = 150.0
    
    return config


# ============ Decision Matrix ============

"""
TRADE DECISION MATRIX

This replaces the old SMA/RSI regime detection with volatility-focused logic.

┌─────────────────┬─────────────────┬─────────────────┬─────────────────┐
│ IV RANK         │ IV/HV RATIO     │ TERM STRUCTURE  │ ACTION          │
├─────────────────┼─────────────────┼─────────────────┼─────────────────┤
│ > 50 (Rich)     │ > 1.2 (Rich)    │ Any             │ SELL PREMIUM    │
│ > 50 (Rich)     │ > 1.0           │ Contango        │ SELL PREMIUM    │
│ > 50 (Rich)     │ > 1.0           │ Backwardation   │ SELL PUTS ONLY  │
│ 30-50 (Fair)    │ > 1.1           │ Contango        │ SELECTIVE SELL  │
│ 30-50 (Fair)    │ < 1.0           │ Any             │ NO TRADE        │
│ < 30 (Cheap)    │ Any             │ Any             │ NO TRADE / BUY  │
│ Any             │ Any             │ VIX > 35        │ NO TRADE        │
└─────────────────┴─────────────────┴─────────────────┴─────────────────┘

STRATEGY SELECTION (when selling)

┌─────────────────┬─────────────────┬─────────────────────────────────────┐
│ SKEW            │ FLOW            │ STRATEGY                            │
├─────────────────┼─────────────────┼─────────────────────────────────────┤
│ Put-rich (>3)   │ High P/C ratio  │ Bull Put Spread (rich put premium)  │
│ Neutral         │ Normal          │ Iron Condor (balanced)              │
│ Call-rich       │ Low P/C ratio   │ Bear Call Spread (rare)             │
│ Any             │ Unusual flow    │ Follow the flow direction           │
└─────────────────┴─────────────────┴─────────────────────────────────────┘

EXIT RULES (unchanged - these work well)

1. PROFIT TARGET: Close at 50% of max credit
2. STOP LOSS: Close at 2x credit loss  
3. TIME EXIT: Close at 21 DTE (avoid gamma risk)
4. EARNINGS: Close before earnings if within DTE
"""
