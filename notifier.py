"""
Telegram Notifier
Sends trade alerts and updates via Telegram
"""
import logging
import asyncio
from typing import Optional
from datetime import datetime

from telegram import Bot
from telegram.error import TelegramError

# Support both config versions
try:
    from config_v2 import TelegramConfig
except ImportError:
    from config import TelegramConfig

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """
    Sends notifications to Telegram
    """
    
    def __init__(self, config: TelegramConfig):
        self.config = config
        self.bot: Optional[Bot] = None
        self._enabled = config.enabled and config.bot_token and config.chat_id
        
        if self._enabled:
            self.bot = Bot(token=config.bot_token)
    
    async def send_message_async(self, message: str) -> bool:
        """Send a message asynchronously"""
        if not self._enabled or not self.bot:
            logger.info(f"Telegram disabled, would send: {message[:100]}...")
            return False
        
        try:
            await self.bot.send_message(
                chat_id=self.config.chat_id,
                text=message,
                parse_mode='HTML'
            )
            return True
        except TelegramError as e:
            logger.error(f"Telegram error: {e}")
            return False
    
    def send_message(self, message: str) -> bool:
        """Send a message synchronously"""
        if not self._enabled or not self.bot:
            logger.info(f"[TELEGRAM] {message}")
            return False
        
        try:
            # Run async in sync context
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Create new loop for sync call
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(
                        asyncio.run,
                        self.send_message_async(message)
                    )
                    return future.result()
            else:
                return loop.run_until_complete(self.send_message_async(message))
        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}")
            # Fallback: just log it
            logger.info(f"[TELEGRAM FALLBACK] {message}")
            return False
    
    def send_trade_signal(
        self,
        symbol: str,
        strategy: str,
        expiration: str,
        credit: float,
        max_loss: float,
        short_strike: float,
        long_strike: float,
        prob_otm: float = 0.0,
        iv_rank: float = 0.0,
        iv_hv_ratio: float = 0.0,
        confidence: float = 0.0
    ) -> bool:
        """Send a trade signal alert with IV metrics"""
        message = f"""
🔔 <b>NEW TRADE SIGNAL</b>

<b>{strategy.upper().replace('_', ' ')}</b> on <b>{symbol}</b>

📊 <b>Volatility Analysis</b>
IV Rank: {iv_rank:.0f}%
IV/HV Ratio: {iv_hv_ratio:.2f}x
Confidence: {confidence:.0%}

📅 Expiration: {expiration}
💰 Credit: ${credit:.2f}
⚠️ Max Loss: ${max_loss:.2f}
📊 R/R: {credit/max_loss:.1%}
🎯 Prob OTM: {prob_otm:.0%}

Short: {short_strike}
Long: {long_strike}
"""
        return self.send_message(message)
    
    def send_position_opened(
        self,
        symbol: str,
        strategy: str,
        expiration: str,
        credit: float,
        quantity: int,
        fill_price: float
    ) -> bool:
        """Send position opened alert"""
        message = f"""
✅ <b>POSITION OPENED</b>

<b>{strategy.upper().replace('_', ' ')}</b> on <b>{symbol}</b>

📅 Expiration: {expiration}
💰 Credit: ${fill_price:.2f} x {quantity}
📍 Total Credit: ${fill_price * quantity * 100:.2f}
"""
        return self.send_message(message)
    
    def send_position_closed(
        self,
        symbol: str,
        strategy: str,
        reason: str,
        realized_pnl: float,
        days_held: int
    ) -> bool:
        """Send position closed alert"""
        emoji = "🟢" if realized_pnl > 0 else "🔴"
        message = f"""
{emoji} <b>POSITION CLOSED</b>

<b>{strategy.upper().replace('_', ' ')}</b> on <b>{symbol}</b>

📍 Reason: {reason}
💰 Realized P&L: ${realized_pnl:.2f}
📅 Days held: {days_held}
"""
        return self.send_message(message)
    
    def send_daily_summary(
        self,
        open_positions: int,
        total_pnl: float,
        total_credit: float,
        positions_detail: str = "",
        net_delta: float = 0.0,
        net_theta: float = 0.0
    ) -> bool:
        """Send daily portfolio summary with Greeks"""
        emoji = "🟢" if total_pnl > 0 else "🔴"
        pnl_pct = total_pnl / total_credit if total_credit > 0 else 0
        
        message = f"""
📊 <b>DAILY SUMMARY</b>
{datetime.now().strftime('%Y-%m-%d %H:%M')} SGT

Open Positions: {open_positions}
{emoji} Total P&L: ${total_pnl:.2f} ({pnl_pct:.1%})
💰 Credit at Risk: ${total_credit:.2f}

<b>Portfolio Greeks</b>
Delta: {net_delta:+.1f}
Theta: ${net_theta:+.2f}/day

{positions_detail}
"""
        return self.send_message(message)
    
    def send_market_analysis(
        self,
        symbol: str,
        iv_rank: float,
        iv_hv_ratio: float,
        vix: float,
        term_structure: str,
        recommendation: str
    ) -> bool:
        """Send market analysis update"""
        vol_emoji = "🟢" if iv_rank > 50 else "🟡" if iv_rank > 30 else "🔴"
        
        message = f"""
📈 <b>MARKET ANALYSIS: {symbol}</b>

{vol_emoji} IV Rank: {iv_rank:.0f}%
📊 IV/HV: {iv_hv_ratio:.2f}x
🌡️ VIX: {vix:.1f}
📉 Term Structure: {term_structure}

💡 Recommendation: {recommendation}
"""
        return self.send_message(message)
    
    def send_regime_change(
        self,
        old_regime: str,
        new_regime: str,
        vix: float,
        trend: str
    ) -> bool:
        """Send regime change alert"""
        message = f"""
⚠️ <b>REGIME CHANGE</b>

{old_regime.upper()} → <b>{new_regime.upper()}</b>

VIX: {vix:.1f}
Trend: {trend}
"""
        return self.send_message(message)
    
    def send_roll_alert(
        self,
        symbol: str,
        reason: str,
        current_strikes: str,
        suggested_strikes: str,
        urgency: str
    ) -> bool:
        """Send position roll recommendation"""
        urgency_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(urgency, "⚪")
        
        message = f"""
🔄 <b>ROLL RECOMMENDATION</b>

<b>{symbol}</b>
{urgency_emoji} Urgency: {urgency.upper()}

📍 Reason: {reason}
Current: {current_strikes}
Suggested: {suggested_strikes}
"""
        return self.send_message(message)
    
    def send_error(self, error_message: str) -> bool:
        """Send error notification"""
        message = f"""
❌ <b>BOT ERROR</b>

{error_message}

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} SGT
"""
        return self.send_message(message)
    
    def send_startup(self) -> bool:
        """Send bot startup notification"""
        message = f"""
🤖 <b>OPTIONS BOT STARTED</b>

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} SGT
Mode: Paper Trading
Strategy: IV Rank + Credit Spreads

US Market Hours: 9:30 PM - 4:00 AM SGT
"""
        return self.send_message(message)
    
    def send_shutdown(self) -> bool:
        """Send bot shutdown notification"""
        message = f"""
🛑 <b>OPTIONS BOT STOPPED</b>

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} SGT
"""
        return self.send_message(message)
    
    def send_sleep(self, next_open: str = None) -> bool:
        """Send notification when bot goes to sleep outside market hours"""
        next_info = f"\nNext market open: {next_open}" if next_open else ""
        message = f"""
😴 <b>BOT SLEEPING</b>

Outside US market hours.{next_info}

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} SGT
"""
        return self.send_message(message)
    
    def send_wake(self) -> bool:
        """Send notification when bot wakes up at market open"""
        message = f"""
☀️ <b>BOT AWAKE</b>

US markets are open! Starting analysis...

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} SGT
"""
        return self.send_message(message)


class ConsoleNotifier:
    """
    Fallback notifier that just prints to console
    Useful for testing without Telegram
    """
    
    def send_message(self, message: str) -> bool:
        print(f"\n{'='*50}")
        print(message)
        print(f"{'='*50}\n")
        return True
    
    def send_trade_signal(self, **kwargs) -> bool:
        return self.send_message(f"TRADE SIGNAL: {kwargs}")
    
    def send_position_opened(self, **kwargs) -> bool:
        return self.send_message(f"POSITION OPENED: {kwargs}")
    
    def send_position_closed(self, **kwargs) -> bool:
        return self.send_message(f"POSITION CLOSED: {kwargs}")
    
    def send_daily_summary(self, **kwargs) -> bool:
        return self.send_message(f"DAILY SUMMARY: {kwargs}")
    
    def send_regime_change(self, **kwargs) -> bool:
        return self.send_message(f"REGIME CHANGE: {kwargs}")
    
    def send_error(self, error_message: str) -> bool:
        return self.send_message(f"ERROR: {error_message}")
    
    def send_startup(self) -> bool:
        return self.send_message("BOT STARTED")
    
    def send_shutdown(self) -> bool:
        return self.send_message("BOT STOPPED")
    
    def send_sleep(self, next_open: str = None) -> bool:
        return self.send_message(f"BOT SLEEPING - Outside market hours. Next open: {next_open}")
    
    def send_wake(self) -> bool:
        return self.send_message("BOT AWAKE - Markets open!")


def create_notifier(config: TelegramConfig) -> TelegramNotifier | ConsoleNotifier:
    """Factory function to create appropriate notifier"""
    if config.enabled and config.bot_token and config.chat_id:
        return TelegramNotifier(config)
    else:
        logger.info("Telegram not configured, using console notifier")
        return ConsoleNotifier()
