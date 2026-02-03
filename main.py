"""
Options Trading Bot - Main Entry Point
Orchestrates regime detection, spread building, execution, and position management
"""
import logging
import time
import signal
import sys
from datetime import datetime, time as dt_time
from typing import Optional

from config import (
    load_config, BotConfig, Regime, Strategy, 
    REGIME_STRATEGY_MAP
)
from ibkr_client import IBKRClient
from regime_detector import RegimeDetector, RegimeAnalysis
from spread_builder import SpreadBuilder, CreditSpread, IronCondor
from executor import OrderExecutor, OrderResult
from position_manager import PositionManager, format_portfolio_summary
from notifier import create_notifier, TelegramNotifier, ConsoleNotifier

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('options_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class OptionsBot:
    """
    Main bot class that runs the trading loop
    """
    
    def __init__(self, config: BotConfig):
        self.config = config
        self.running = False
        
        # Initialize components
        self.client = IBKRClient(config.ibkr)
        self.regime_detector = RegimeDetector(config.regime)
        self.spread_builder = SpreadBuilder(self.client, config.spread)
        self.executor = OrderExecutor(self.client, config.risk)
        self.position_manager = PositionManager(self.client, config.risk)
        self.notifier = create_notifier(config.telegram)
        
        # State
        self.current_regime: Optional[Regime] = None
        self.last_regime_check: Optional[datetime] = None
        self.last_position_check: Optional[datetime] = None
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)
    
    def _handle_shutdown(self, signum, frame):
        """Handle graceful shutdown"""
        logger.info("Shutdown signal received")
        self.running = False
    
    def start(self):
        """Start the bot"""
        logger.info("Starting Options Trading Bot...")
        
        # Connect to IBKR
        if not self.client.connect_sync():
            logger.error("Failed to connect to IBKR. Is TWS/Gateway running?")
            self.notifier.send_error("Failed to connect to IBKR")
            return
        
        self.running = True
        self.notifier.send_startup()
        
        logger.info("Bot started successfully")
        
        # Main loop
        try:
            self._run_loop()
        except Exception as e:
            logger.error(f"Bot error: {e}")
            self.notifier.send_error(str(e))
        finally:
            self.stop()
    
    def stop(self):
        """Stop the bot"""
        logger.info("Stopping bot...")
        self.running = False
        self.client.disconnect()
        self.notifier.send_shutdown()
        logger.info("Bot stopped")
    
    def _run_loop(self):
        """Main trading loop"""
        while self.running:
            try:
                now = datetime.now()
                
                # Check if market hours
                if not self._is_market_hours(now):
                    logger.debug("Outside market hours, sleeping...")
                    time.sleep(60)
                    continue
                
                # Check positions for exits
                if self._should_check_positions(now):
                    self._check_and_manage_positions()
                    self.last_position_check = now
                
                # Check for new trades
                if self._should_scan_for_trades(now):
                    self._scan_and_trade()
                    self.last_regime_check = now
                
                # Sleep before next iteration
                self.client.sleep(10)  # Keep connection alive
                
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                time.sleep(30)
    
    def _is_market_hours(self, now: datetime) -> bool:
        """Check if within market hours (Eastern Time)"""
        # Simple check - in production, use proper timezone handling
        current_time = now.time()
        market_open = dt_time(
            self.config.trading.market_open_hour,
            self.config.trading.market_open_minute
        )
        market_close = dt_time(
            self.config.trading.market_close_hour,
            self.config.trading.market_close_minute
        )
        
        # Also check if weekday
        if now.weekday() >= 5:  # Saturday = 5, Sunday = 6
            return False
        
        return market_open <= current_time <= market_close
    
    def _should_scan_for_trades(self, now: datetime) -> bool:
        """Check if we should scan for new trades"""
        if self.last_regime_check is None:
            return True
        
        elapsed = (now - self.last_regime_check).total_seconds()
        return elapsed >= self.config.trading.scan_interval
    
    def _should_check_positions(self, now: datetime) -> bool:
        """Check if we should update position values"""
        if self.last_position_check is None:
            return True
        
        elapsed = (now - self.last_position_check).total_seconds()
        return elapsed >= self.config.trading.position_check_interval
    
    def _scan_and_trade(self):
        """Scan for regime and execute trades"""
        logger.info("Scanning for trading opportunities...")
        
        # Get VIX
        vix = self.client.get_vix()
        if vix is None:
            logger.warning("Could not get VIX")
            return
        
        logger.info(f"Current VIX: {vix:.2f}")
        
        # Analyze regime for each underlying
        for symbol in self.config.spread.underlyings:
            try:
                self._process_symbol(symbol, vix)
            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")
    
    def _process_symbol(self, symbol: str, vix: float):
        """Process a single symbol for trading"""
        # Check if we can open new positions
        if not self.position_manager.can_open_new_position(symbol):
            logger.info(f"Position limit reached for {symbol}")
            return
        
        # Get price and historical data
        price = self.client.get_stock_price(symbol)
        if price is None:
            logger.warning(f"Could not get price for {symbol}")
            return
        
        historical = self.client.get_historical_data(symbol)
        if not historical:
            logger.warning(f"Could not get historical data for {symbol}")
            return
        
        # Detect regime
        analysis = self.regime_detector.analyze(vix, historical, symbol)
        logger.info(f"{symbol} regime: {analysis.regime.value} (confidence: {analysis.confidence:.0%})")
        
        # Check for regime change
        if self.current_regime and analysis.regime != self.current_regime:
            self.notifier.send_regime_change(
                old_regime=self.current_regime.value,
                new_regime=analysis.regime.value,
                vix=vix,
                trend=analysis.trend
            )
        self.current_regime = analysis.regime
        
        # Skip if low confidence or no trade regime
        if analysis.confidence < 0.5:
            logger.info(f"Low confidence ({analysis.confidence:.0%}), skipping")
            return
        
        strategy = REGIME_STRATEGY_MAP.get(analysis.regime, Strategy.NO_TRADE)
        if strategy == Strategy.NO_TRADE:
            logger.info(f"No trade for regime {analysis.regime.value}")
            return
        
        # Build spread
        spread = self.spread_builder.build_spread_for_regime(
            symbol, analysis.regime, price
        )
        
        if spread is None:
            logger.info(f"Could not build spread for {symbol}")
            return
        
        # Log the trade signal
        if isinstance(spread, CreditSpread):
            logger.info(
                f"Trade signal: {spread.strategy.value} {symbol} "
                f"{spread.short_leg.strike}/{spread.long_leg.strike} "
                f"for ${spread.credit:.2f} credit"
            )
            
            # Send signal alert
            self.notifier.send_trade_signal(
                symbol=symbol,
                strategy=spread.strategy.value,
                expiration=spread.expiration,
                credit=spread.credit,
                max_loss=spread.max_loss,
                short_strike=spread.short_leg.strike,
                long_strike=spread.long_leg.strike,
                prob_otm=spread.probability_otm
            )
            
            # Execute
            result = self.executor.execute_credit_spread(spread, quantity=1)
            
        else:  # IronCondor
            logger.info(
                f"Trade signal: Iron Condor {symbol} "
                f"P:{spread.put_short_leg.strike}/{spread.put_long_leg.strike} "
                f"C:{spread.call_short_leg.strike}/{spread.call_long_leg.strike} "
                f"for ${spread.total_credit:.2f} credit"
            )
            
            self.notifier.send_trade_signal(
                symbol=symbol,
                strategy='iron_condor',
                expiration=spread.expiration,
                credit=spread.total_credit,
                max_loss=spread.max_loss,
                short_strike=spread.put_short_leg.strike,
                long_strike=spread.call_short_leg.strike,
                prob_otm=spread.probability_otm
            )
            
            result = self.executor.execute_iron_condor(spread, quantity=1)
        
        # Handle result
        if result.success:
            logger.info(f"Order successful: {result.message}")
            
            # Track position
            position = self.position_manager.add_position(
                spread,
                quantity=1,
                fill_price=result.fill_price or (spread.credit if isinstance(spread, CreditSpread) else spread.total_credit)
            )
            
            self.notifier.send_position_opened(
                symbol=symbol,
                strategy=position.strategy,
                expiration=spread.expiration,
                credit=position.entry_credit,
                quantity=1,
                fill_price=position.entry_credit
            )
        else:
            logger.warning(f"Order failed: {result.message}")
            self.notifier.send_error(f"Order failed for {symbol}: {result.message}")
    
    def _check_and_manage_positions(self):
        """Check all positions and manage exits"""
        logger.debug("Checking positions...")
        
        # Update values
        self.position_manager.update_position_values()
        
        # Check for exit signals
        exits = self.position_manager.check_exit_signals()
        
        for exit_info in exits:
            position = exit_info['position']
            reason = exit_info['reason']
            
            logger.info(f"Exit signal for {position.position_id}: {reason}")
            
            # Close the position
            # Note: In a real implementation, you'd reconstruct the spread
            # and execute a closing order. For simplicity, we're just marking it closed.
            
            self.position_manager.close_position(
                position.position_id,
                reason,
                position.current_pnl
            )
            
            self.notifier.send_position_closed(
                symbol=position.symbol,
                strategy=position.strategy,
                reason=reason,
                realized_pnl=position.current_pnl,
                days_held=(datetime.now() - position.entry_date).days
            )
    
    def run_once(self):
        """Run a single scan cycle (useful for testing)"""
        if not self.client.is_connected:
            if not self.client.connect_sync():
                logger.error("Failed to connect")
                return
        
        # Get VIX
        vix = self.client.get_vix()
        logger.info(f"VIX: {vix}")
        
        # Process each symbol
        for symbol in self.config.spread.underlyings:
            logger.info(f"\n{'='*40}\nProcessing {symbol}\n{'='*40}")
            
            price = self.client.get_stock_price(symbol)
            logger.info(f"Price: {price}")
            
            historical = self.client.get_historical_data(symbol)
            if historical:
                logger.info(f"Got {len(historical)} bars of historical data")
            
            if vix and historical:
                analysis = self.regime_detector.analyze(vix, historical, symbol)
                logger.info(self.regime_detector.get_regime_summary(analysis))
                
                # Build spread (but don't execute)
                spread = self.spread_builder.build_spread_for_regime(
                    symbol, analysis.regime, price
                )
                
                if spread:
                    if isinstance(spread, CreditSpread):
                        logger.info(f"\nSpread: {spread.strategy.value}")
                        logger.info(f"Short: {spread.short_leg.strike}")
                        logger.info(f"Long: {spread.long_leg.strike}")
                        logger.info(f"Credit: ${spread.credit:.2f}")
                        logger.info(f"Max Loss: ${spread.max_loss:.2f}")
                    else:
                        logger.info(f"\nIron Condor:")
                        logger.info(f"Put spread: {spread.put_short_leg.strike}/{spread.put_long_leg.strike}")
                        logger.info(f"Call spread: {spread.call_short_leg.strike}/{spread.call_long_leg.strike}")
                        logger.info(f"Credit: ${spread.total_credit:.2f}")
    
    def show_portfolio(self):
        """Display current portfolio status"""
        summary = self.position_manager.get_portfolio_summary()
        print(format_portfolio_summary(summary))


def main():
    """Main entry point"""
    print("""
╔═══════════════════════════════════════════════════════════╗
║          OPTIONS CREDIT SPREAD TRADING BOT                ║
║                    Paper Trading Mode                     ║
╚═══════════════════════════════════════════════════════════╝
    """)
    
    # Load configuration
    config = load_config()
    
    # Create bot
    bot = OptionsBot(config)
    
    # Check for command line args
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        
        if cmd == 'test':
            # Run single test cycle
            logger.info("Running test cycle...")
            bot.run_once()
            
        elif cmd == 'portfolio':
            # Show portfolio
            bot.client.connect_sync()
            bot.show_portfolio()
            bot.client.disconnect()
            
        elif cmd == 'run':
            # Full run
            bot.start()
        
        else:
            print(f"Unknown command: {cmd}")
            print("Usage: python main.py [test|portfolio|run]")
    else:
        # Default: run the bot
        bot.start()


if __name__ == '__main__':
    main()
