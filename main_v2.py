"""
Options Trading Bot - Main Entry Point (V2)
Uses volatility-focused analysis instead of SMA/RSI
"""
import logging
import time
import signal
import sys
import os
from datetime import datetime, time as dt_time
from typing import Optional

# Use environment config if running in Docker/Railway
if os.getenv('IBKR_HOST'):
    from config_env import load_config_from_env as load_config, print_config_summary
else:
    from config_v2 import load_config
    print_config_summary = None

from config_v2 import BotConfig, Strategy
from ibkr_client_enhanced import EnhancedIBKRClient
from options_analyzer import (
    OptionsMarketAnalyzer, OptionsAnalysis, 
    VolatilityRegime, TermStructure, SkewRegime,
    format_analysis_report
)
from spread_builder import SpreadBuilder, CreditSpread, IronCondor
from executor import OrderExecutor, OrderResult
from position_manager import PositionManager, format_portfolio_summary
from notifier import create_notifier

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
    Main bot class using volatility-focused analysis
    """
    
    def __init__(self, config: BotConfig):
        self.config = config
        self.running = False
        
        # Initialize components
        self.client = EnhancedIBKRClient(config.ibkr)
        self.analyzer = OptionsMarketAnalyzer({
            'iv_rank_high': config.volatility.iv_rank_rich,
            'iv_rank_low': config.volatility.iv_rank_fair,
            'iv_rank_extreme': config.volatility.iv_rank_extreme,
            'iv_hv_rich': config.volatility.iv_hv_rich,
            'iv_hv_cheap': config.volatility.iv_hv_cheap,
            'contango_threshold': config.volatility.contango_threshold,
            'backwardation_threshold': config.volatility.backwardation_threshold,
            'move_ratio_rich': config.volatility.move_ratio_edge,
            'skew_rich_threshold': config.volatility.skew_put_rich,
            'unusual_volume_mult': config.flow.unusual_volume_mult,
            'vol_oi_unusual': config.flow.vol_oi_unusual,
            'earnings_buffer_days': config.risk.earnings_buffer_days,
        })
        self.spread_builder = SpreadBuilder(self.client, config.spread)
        self.executor = OrderExecutor(self.client, config.risk)
        self.position_manager = PositionManager(self.client, config.risk)
        self.notifier = create_notifier(config.telegram)
        
        # State
        self.last_analysis: dict[str, OptionsAnalysis] = {}
        self.last_scan_time: Optional[datetime] = None
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
        logger.info("Starting Options Trading Bot V2 (Volatility-Focused)...")
        
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
                if self._should_scan(now):
                    self._scan_and_trade()
                    self.last_scan_time = now
                
                # Sleep before next iteration
                self.client.sleep(10)
                
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                time.sleep(30)
    
    def _is_market_hours(self, now: datetime) -> bool:
        """Check if within US market hours (handles any timezone)"""
        try:
            import pytz
            
            # US Eastern timezone (where market hours are defined)
            eastern = pytz.timezone('US/Eastern')
            
            # Convert current time to Eastern
            if now.tzinfo is None:
                # Assume local time, get local timezone
                local_tz = pytz.timezone(self.config.trading.local_timezone)
                now = local_tz.localize(now)
            
            now_eastern = now.astimezone(eastern)
            current_time = now_eastern.time()
            
            market_open = dt_time(
                self.config.trading.market_open_hour,
                self.config.trading.market_open_minute
            )
            market_close = dt_time(
                self.config.trading.market_close_hour,
                self.config.trading.market_close_minute
            )
            
            # Check if weekend in US Eastern
            if now_eastern.weekday() >= 5:
                return False
            
            return market_open <= current_time <= market_close
            
        except ImportError:
            # Fallback if pytz not available - assume times are already correct
            current_time = now.time()
            market_open = dt_time(
                self.config.trading.market_open_hour,
                self.config.trading.market_open_minute
            )
            market_close = dt_time(
                self.config.trading.market_close_hour,
                self.config.trading.market_close_minute
            )
            
            if now.weekday() >= 5:
                return False
            
            return market_open <= current_time <= market_close
    
    def _should_scan(self, now: datetime) -> bool:
        """Check if we should scan for new trades"""
        if self.last_scan_time is None:
            return True
        
        elapsed = (now - self.last_scan_time).total_seconds()
        return elapsed >= self.config.trading.scan_interval
    
    def _should_check_positions(self, now: datetime) -> bool:
        """Check if we should update position values"""
        if self.last_position_check is None:
            return True
        
        elapsed = (now - self.last_position_check).total_seconds()
        return elapsed >= self.config.trading.position_check_interval
    
    def _scan_and_trade(self):
        """Scan for opportunities using volatility analysis"""
        logger.info("=" * 50)
        logger.info("SCANNING FOR OPPORTUNITIES")
        logger.info("=" * 50)
        
        # Get VIX term structure
        vix_data = self.client.get_vix_term_structure()
        vix = vix_data.get('VIX', 20.0)
        vix3m = vix_data.get('VIX3M', vix * 1.10)
        
        logger.info(f"VIX: {vix:.1f} | VIX3M: {vix3m:.1f}")
        
        # Analyze each underlying
        for symbol in self.config.spread.underlyings:
            try:
                self._process_symbol(symbol, vix, vix3m)
            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")
    
    def _process_symbol(self, symbol: str, vix: float, vix3m: float):
        """Process a single symbol with full volatility analysis"""
        logger.info(f"\n--- Analyzing {symbol} ---")
        
        # Check position limits
        if not self.position_manager.can_open_new_position(symbol):
            logger.info(f"Position limit reached for {symbol}")
            return
        
        # Get underlying price
        price = self.client.get_stock_price(symbol)
        if not price:
            logger.warning(f"Could not get price for {symbol}")
            return
        
        logger.info(f"{symbol} price: ${price:.2f}")
        
        # Get historical price data
        price_history = self.client.get_historical_data(symbol, duration="60 D")
        if not price_history:
            logger.warning(f"Could not get price history for {symbol}")
            return
        
        # Get IV history (uses VIX as proxy for index ETFs)
        iv_history = self.client.get_iv_history(symbol, lookback_days=252)
        
        # Get current ATM IV
        current_iv = self.client.get_atm_iv(symbol, dte_target=self.config.spread.target_dte)
        if not current_iv:
            # Fallback: estimate from VIX
            current_iv = vix / 100 * 1.1  # ETFs usually slightly higher than VIX
            logger.info(f"Using estimated IV: {current_iv:.1%}")
        else:
            logger.info(f"ATM IV: {current_iv:.1%}")
        
        # Get expiration for analysis
        expiration = self.client._get_expiration_for_dte(
            symbol, 
            self.config.spread.target_dte,
            self.config.spread.min_dte,
            self.config.spread.max_dte
        )
        
        if not expiration:
            logger.warning(f"No valid expiration for {symbol}")
            return
        
        # Get skew data
        skew_data = self.client.get_skew_data(symbol, expiration, price)
        
        # Get volume/OI data
        volume_data = self.client.get_volume_oi_data(symbol, expiration)
        
        # Run full analysis
        analysis = self.analyzer.analyze(
            symbol=symbol,
            current_iv=current_iv,
            iv_history=iv_history if iv_history else [current_iv] * 252,
            price_history=price_history,
            vix=vix,
            vix3m=vix3m,
            options_chain_data=skew_data,
            volume_data=volume_data,
            earnings_date=None,  # TODO: Add earnings calendar
            target_dte=self.config.spread.target_dte
        )
        
        # Store analysis
        self.last_analysis[symbol] = analysis
        
        # Log analysis
        logger.info(f"\n{format_analysis_report(analysis)}")
        
        # Make trade decision
        if analysis.recommendation == 'no_trade':
            logger.info(f"NO TRADE: {analysis.recommended_strategy}")
            return
        
        if analysis.confidence < 0.5:
            logger.info(f"Low confidence ({analysis.confidence:.0%}), skipping")
            return
        
        # Map recommendation to strategy
        strategy = self._map_strategy(analysis)
        if strategy == Strategy.NO_TRADE:
            return
        
        # Build and potentially execute spread
        self._build_and_execute(symbol, strategy, price, analysis)
    
    def _map_strategy(self, analysis: OptionsAnalysis) -> Strategy:
        """Map analysis recommendation to strategy enum"""
        if analysis.recommendation != 'sell_premium':
            return Strategy.NO_TRADE
        
        strat = analysis.recommended_strategy.lower()
        
        if 'put' in strat:
            return Strategy.BULL_PUT_SPREAD
        elif 'call' in strat:
            return Strategy.BEAR_CALL_SPREAD
        elif 'condor' in strat:
            return Strategy.IRON_CONDOR
        else:
            return Strategy.IRON_CONDOR  # Default
    
    def _build_and_execute(
        self, 
        symbol: str, 
        strategy: Strategy, 
        price: float,
        analysis: OptionsAnalysis
    ):
        """Build spread and execute if configured"""
        
        # Convert strategy enum to regime for spread builder
        # (This is a bridge between old and new systems)
        from config import Regime
        
        regime_map = {
            Strategy.BULL_PUT_SPREAD: Regime.BULLISH,
            Strategy.BEAR_CALL_SPREAD: Regime.BEARISH,
            Strategy.IRON_CONDOR: Regime.SIDEWAYS
        }
        
        regime = regime_map.get(strategy, Regime.SIDEWAYS)
        
        # Build spread
        spread = self.spread_builder.build_spread_for_regime(symbol, regime, price)
        
        if not spread:
            logger.info(f"Could not build {strategy.value} for {symbol}")
            return
        
        # Log trade signal
        if isinstance(spread, CreditSpread):
            signal_msg = (
                f"📊 TRADE SIGNAL: {spread.strategy.value} on {symbol}\n"
                f"IV Rank: {analysis.iv_rank:.0f}% | IV/HV: {analysis.iv_hv_ratio:.2f}x\n"
                f"Short: {spread.short_leg.strike} | Long: {spread.long_leg.strike}\n"
                f"Credit: ${spread.credit:.2f} | Max Loss: ${spread.max_loss:.2f}\n"
                f"Confidence: {analysis.confidence:.0%}"
            )
            
            self.notifier.send_message(signal_msg)
            
            # Execute if auto-execute enabled
            if self.config.trading.auto_execute:
                result = self.executor.execute_credit_spread(spread, quantity=1)
                self._handle_execution_result(spread, result, analysis)
            else:
                logger.info("Auto-execute disabled, signal only")
                
        else:  # Iron Condor
            signal_msg = (
                f"📊 TRADE SIGNAL: Iron Condor on {symbol}\n"
                f"IV Rank: {analysis.iv_rank:.0f}% | IV/HV: {analysis.iv_hv_ratio:.2f}x\n"
                f"Put: {spread.put_short_leg.strike}/{spread.put_long_leg.strike}\n"
                f"Call: {spread.call_short_leg.strike}/{spread.call_long_leg.strike}\n"
                f"Credit: ${spread.total_credit:.2f}\n"
                f"Confidence: {analysis.confidence:.0%}"
            )
            
            self.notifier.send_message(signal_msg)
            
            if self.config.trading.auto_execute:
                result = self.executor.execute_iron_condor(spread, quantity=1)
                self._handle_execution_result(spread, result, analysis)
    
    def _handle_execution_result(
        self, 
        spread: CreditSpread | IronCondor, 
        result: OrderResult,
        analysis: OptionsAnalysis
    ):
        """Handle order execution result"""
        if result.success:
            logger.info(f"✅ Order successful: {result.message}")
            
            # Track position
            credit = spread.credit if isinstance(spread, CreditSpread) else spread.total_credit
            position = self.position_manager.add_position(
                spread,
                quantity=1,
                fill_price=result.fill_price or credit
            )
            
            self.notifier.send_position_opened(
                symbol=spread.symbol,
                strategy=position.strategy,
                expiration=spread.expiration,
                credit=position.entry_credit,
                quantity=1,
                fill_price=position.entry_credit
            )
        else:
            logger.warning(f"❌ Order failed: {result.message}")
            self.notifier.send_error(f"Order failed for {spread.symbol}: {result.message}")
    
    def _check_and_manage_positions(self):
        """Check and manage existing positions"""
        logger.debug("Checking positions...")
        
        self.position_manager.update_position_values()
        
        exits = self.position_manager.check_exit_signals()
        
        for exit_info in exits:
            position = exit_info['position']
            reason = exit_info['reason']
            
            logger.info(f"Exit signal for {position.position_id}: {reason}")
            
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
        """Run a single analysis cycle (for testing)"""
        if not self.client.is_connected:
            if not self.client.connect_sync():
                logger.error("Failed to connect")
                return
        
        # Get VIX
        vix_data = self.client.get_vix_term_structure()
        vix = vix_data.get('VIX', 20.0)
        vix3m = vix_data.get('VIX3M', vix * 1.10)
        
        print(f"\n{'='*60}")
        print(f"VIX TERM STRUCTURE")
        print(f"{'='*60}")
        print(f"VIX: {vix:.1f}")
        print(f"VIX3M: {vix3m:.1f}")
        print(f"Slope: {(vix3m - vix) / vix * 100:+.1f}%")
        
        for symbol in self.config.spread.underlyings:
            self._process_symbol(symbol, vix, vix3m)
    
    def show_portfolio(self):
        """Display current portfolio"""
        summary = self.position_manager.get_portfolio_summary()
        print(format_portfolio_summary(summary))
    
    def show_last_analysis(self):
        """Display last analysis for each symbol"""
        for symbol, analysis in self.last_analysis.items():
            print(format_analysis_report(analysis))


def main():
    """Main entry point"""
    print("""
╔═══════════════════════════════════════════════════════════╗
║     OPTIONS CREDIT SPREAD TRADING BOT V2                  ║
║         Volatility-Focused Analysis                       ║
║              Paper Trading Mode                           ║
╚═══════════════════════════════════════════════════════════╝

Decision Logic:
• IV Rank > 50% + IV/HV > 1.2 → SELL PREMIUM
• IV Rank < 30% → NO TRADE (cheap premium)
• Put Skew Rich → Bull Put Spreads
• Neutral Skew → Iron Condors
• VIX > 35 → NO TRADE (crisis)
    """)
    
    config = load_config()
    bot = OptionsBot(config)
    
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        
        if cmd == 'test':
            logger.info("Running test cycle...")
            bot.run_once()
            
        elif cmd == 'portfolio':
            bot.client.connect_sync()
            bot.show_portfolio()
            bot.client.disconnect()
            
        elif cmd == 'analysis':
            bot.client.connect_sync()
            bot.run_once()
            bot.client.disconnect()
            
        elif cmd == 'run':
            bot.start()
        
        else:
            print(f"Unknown command: {cmd}")
            print("Usage: python main_v2.py [test|portfolio|analysis|run]")
    else:
        bot.start()


if __name__ == '__main__':
    main()
