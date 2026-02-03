"""
IBKR Client Wrapper
Handles connection, data fetching, and order management via ib_insync
"""
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import logging

from ib_insync import IB, Stock, Index, Option, Contract, MarketOrder, LimitOrder, ComboLeg, Ticker
from ib_insync.order import Order

from config import IBKRConfig, BotConfig

logger = logging.getLogger(__name__)


class IBKRClient:
    """
    Wrapper around ib_insync for options trading operations
    """
    
    def __init__(self, config: IBKRConfig):
        self.config = config
        self.ib = IB()
        self._connected = False
        
    async def connect(self) -> bool:
        """Connect to IBKR TWS or Gateway"""
        try:
            await self.ib.connectAsync(
                host=self.config.host,
                port=self.config.port,
                clientId=self.config.client_id,
                timeout=self.config.timeout,
                readonly=self.config.readonly
            )
            self._connected = True
            logger.info(f"Connected to IBKR at {self.config.host}:{self.config.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to IBKR: {e}")
            self._connected = False
            return False
    
    def connect_sync(self) -> bool:
        """Synchronous connect for simpler usage"""
        try:
            self.ib.connect(
                host=self.config.host,
                port=self.config.port,
                clientId=self.config.client_id,
                timeout=self.config.timeout,
                readonly=self.config.readonly
            )
            self._connected = True
            logger.info(f"Connected to IBKR at {self.config.host}:{self.config.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to IBKR: {e}")
            self._connected = False
            return False
    
    def disconnect(self):
        """Disconnect from IBKR"""
        if self._connected:
            self.ib.disconnect()
            self._connected = False
            logger.info("Disconnected from IBKR")
    
    @property
    def is_connected(self) -> bool:
        return self._connected and self.ib.isConnected()
    
    # ============ Market Data ============
    
    def get_stock_price(self, symbol: str) -> Optional[float]:
        """Get current price for a stock/ETF"""
        try:
            contract = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(contract)
            
            ticker = self.ib.reqMktData(contract, '', False, False)
            self.ib.sleep(2)  # Wait for data
            
            price = ticker.marketPrice()
            self.ib.cancelMktData(contract)
            
            if price and price > 0:
                return price
            
            # Fallback to last price
            return ticker.last if ticker.last > 0 else ticker.close
            
        except Exception as e:
            logger.error(f"Error fetching price for {symbol}: {e}")
            return None
    
    def get_vix(self) -> Optional[float]:
        """Get current VIX level"""
        try:
            vix = Index('VIX', 'CBOE')
            self.ib.qualifyContracts(vix)
            
            ticker = self.ib.reqMktData(vix, '', False, False)
            self.ib.sleep(2)
            
            price = ticker.marketPrice()
            self.ib.cancelMktData(vix)
            
            if price and price > 0:
                return price
            return ticker.last if ticker.last > 0 else ticker.close
            
        except Exception as e:
            logger.error(f"Error fetching VIX: {e}")
            return None
    
    def get_historical_data(
        self, 
        symbol: str, 
        duration: str = "60 D",
        bar_size: str = "1 day"
    ) -> Optional[List[Dict]]:
        """
        Get historical OHLCV data for regime detection
        
        Args:
            symbol: Stock symbol
            duration: How far back (e.g., "60 D", "1 M")
            bar_size: Bar size (e.g., "1 day", "1 hour")
        """
        try:
            contract = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(contract)
            
            bars = self.ib.reqHistoricalData(
                contract,
                endDateTime='',
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow='TRADES',
                useRTH=True,
                formatDate=1
            )
            
            if bars:
                return [
                    {
                        'date': bar.date,
                        'open': bar.open,
                        'high': bar.high,
                        'low': bar.low,
                        'close': bar.close,
                        'volume': bar.volume
                    }
                    for bar in bars
                ]
            return None
            
        except Exception as e:
            logger.error(f"Error fetching historical data for {symbol}: {e}")
            return None
    
    # ============ Options Chain ============
    
    def get_options_chain(
        self, 
        symbol: str, 
        min_dte: int = 25, 
        max_dte: int = 50
    ) -> Optional[List[Option]]:
        """
        Get options chain for a symbol within DTE range
        """
        try:
            stock = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(stock)
            
            chains = self.ib.reqSecDefOptParams(
                stock.symbol, '', stock.secType, stock.conId
            )
            
            if not chains:
                logger.warning(f"No options chains found for {symbol}")
                return None
            
            # Use SMART exchange chain
            chain = next((c for c in chains if c.exchange == 'SMART'), chains[0])
            
            # Filter expirations by DTE
            today = datetime.now().date()
            valid_expirations = []
            
            for exp in chain.expirations:
                exp_date = datetime.strptime(exp, '%Y%m%d').date()
                dte = (exp_date - today).days
                if min_dte <= dte <= max_dte:
                    valid_expirations.append(exp)
            
            if not valid_expirations:
                logger.warning(f"No expirations in DTE range for {symbol}")
                return None
            
            # Get strikes for the nearest valid expiration
            target_exp = min(valid_expirations)
            
            # Build option contracts
            options = []
            for strike in chain.strikes:
                for right in ['C', 'P']:
                    opt = Option(symbol, target_exp, strike, right, 'SMART')
                    options.append(opt)
            
            return options
            
        except Exception as e:
            logger.error(f"Error fetching options chain for {symbol}: {e}")
            return None
    
    def get_option_greeks(self, option: Option) -> Optional[Dict[str, float]]:
        """Get Greeks for a single option"""
        try:
            self.ib.qualifyContracts(option)
            ticker = self.ib.reqMktData(option, '', False, False)
            self.ib.sleep(2)
            
            greeks = {}
            if ticker.modelGreeks:
                greeks = {
                    'delta': ticker.modelGreeks.delta,
                    'gamma': ticker.modelGreeks.gamma,
                    'theta': ticker.modelGreeks.theta,
                    'vega': ticker.modelGreeks.vega,
                    'iv': ticker.modelGreeks.impliedVol
                }
            
            self.ib.cancelMktData(option)
            return greeks if greeks else None
            
        except Exception as e:
            logger.error(f"Error fetching greeks: {e}")
            return None
    
    def get_options_with_greeks(
        self, 
        symbol: str, 
        expiration: str,
        strikes: List[float],
        right: str  # 'C' or 'P'
    ) -> List[Dict]:
        """
        Get multiple options with their Greeks
        Returns list of dicts with option details and greeks
        """
        results = []
        
        for strike in strikes:
            try:
                opt = Option(symbol, expiration, strike, right, 'SMART')
                self.ib.qualifyContracts(opt)
                
                ticker = self.ib.reqMktData(opt, '', False, False)
                self.ib.sleep(1)
                
                result = {
                    'symbol': symbol,
                    'expiration': expiration,
                    'strike': strike,
                    'right': right,
                    'contract': opt,
                    'bid': ticker.bid,
                    'ask': ticker.ask,
                    'mid': (ticker.bid + ticker.ask) / 2 if ticker.bid and ticker.ask else None,
                    'last': ticker.last,
                    'delta': None,
                    'gamma': None,
                    'theta': None,
                    'vega': None,
                    'iv': None
                }
                
                if ticker.modelGreeks:
                    result.update({
                        'delta': ticker.modelGreeks.delta,
                        'gamma': ticker.modelGreeks.gamma,
                        'theta': ticker.modelGreeks.theta,
                        'vega': ticker.modelGreeks.vega,
                        'iv': ticker.modelGreeks.impliedVol
                    })
                
                self.ib.cancelMktData(opt)
                results.append(result)
                
            except Exception as e:
                logger.error(f"Error fetching option {symbol} {strike} {right}: {e}")
                continue
        
        return results
    
    def get_expiration_for_dte(
        self, 
        symbol: str, 
        target_dte: int,
        min_dte: int,
        max_dte: int
    ) -> Optional[str]:
        """Find the best expiration date for target DTE"""
        try:
            stock = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(stock)
            
            chains = self.ib.reqSecDefOptParams(
                stock.symbol, '', stock.secType, stock.conId
            )
            
            if not chains:
                return None
            
            chain = next((c for c in chains if c.exchange == 'SMART'), chains[0])
            
            today = datetime.now().date()
            best_exp = None
            best_diff = float('inf')
            
            for exp in chain.expirations:
                exp_date = datetime.strptime(exp, '%Y%m%d').date()
                dte = (exp_date - today).days
                
                if min_dte <= dte <= max_dte:
                    diff = abs(dte - target_dte)
                    if diff < best_diff:
                        best_diff = diff
                        best_exp = exp
            
            return best_exp
            
        except Exception as e:
            logger.error(f"Error finding expiration: {e}")
            return None
    
    # ============ Order Execution ============
    
    def create_spread_order(
        self,
        legs: List[Dict],  # List of {'contract': Option, 'action': 'BUY'/'SELL', 'ratio': 1}
        order_type: str = 'LMT',
        limit_price: float = None,
        quantity: int = 1
    ) -> Optional[Order]:
        """
        Create a combo order for spreads
        """
        try:
            # Build combo legs
            combo_legs = []
            for leg in legs:
                contract = leg['contract']
                self.ib.qualifyContracts(contract)
                
                combo_leg = ComboLeg(
                    conId=contract.conId,
                    ratio=leg.get('ratio', 1),
                    action=leg['action'],
                    exchange='SMART'
                )
                combo_legs.append(combo_leg)
            
            # Create bag contract
            bag = Contract()
            bag.symbol = legs[0]['contract'].symbol
            bag.secType = 'BAG'
            bag.currency = 'USD'
            bag.exchange = 'SMART'
            bag.comboLegs = combo_legs
            
            # Create order
            if order_type == 'LMT' and limit_price is not None:
                order = LimitOrder(
                    action='BUY',  # For credit spreads, we BUY the combo at negative price
                    totalQuantity=quantity,
                    lmtPrice=limit_price
                )
            else:
                order = MarketOrder(
                    action='BUY',
                    totalQuantity=quantity
                )
            
            return bag, order
            
        except Exception as e:
            logger.error(f"Error creating spread order: {e}")
            return None, None
    
    def place_order(self, contract: Contract, order: Order) -> Optional[Any]:
        """Place an order and return the trade object"""
        try:
            trade = self.ib.placeOrder(contract, order)
            logger.info(f"Order placed: {trade}")
            return trade
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return None
    
    def cancel_order(self, order: Order) -> bool:
        """Cancel an open order"""
        try:
            self.ib.cancelOrder(order)
            return True
        except Exception as e:
            logger.error(f"Error canceling order: {e}")
            return False
    
    # ============ Portfolio ============
    
    def get_positions(self) -> List[Dict]:
        """Get all current positions"""
        positions = []
        for pos in self.ib.positions():
            positions.append({
                'account': pos.account,
                'contract': pos.contract,
                'position': pos.position,
                'avg_cost': pos.avgCost
            })
        return positions
    
    def get_open_orders(self) -> List[Any]:
        """Get all open orders"""
        return self.ib.openOrders()
    
    def get_account_summary(self) -> Dict[str, float]:
        """Get account summary values"""
        summary = {}
        for item in self.ib.accountSummary():
            if item.tag in ['NetLiquidation', 'TotalCashValue', 'BuyingPower', 'GrossPositionValue']:
                summary[item.tag] = float(item.value)
        return summary
    
    def sleep(self, seconds: float):
        """Sleep while keeping connection alive"""
        self.ib.sleep(seconds)
