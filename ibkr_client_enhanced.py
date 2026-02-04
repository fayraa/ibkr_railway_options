"""
Enhanced IBKR Client
Fetches options-specific data for volatility analysis:
- IV history
- VIX term structure (VIX, VIX3M, VIX9D)
- Options chain with Greeks for skew
- Volume and OI data
"""
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Tuple
from collections import defaultdict

from ib_insync import (
    IB, Stock, Index, Option, Contract, 
    MarketOrder, LimitOrder, ComboLeg, Ticker
)

from config import IBKRConfig

logger = logging.getLogger(__name__)


class EnhancedIBKRClient:
    """
    Extended IBKR client with options analytics data
    """
    
    def __init__(self, config: IBKRConfig):
        self.config = config
        self.ib = IB()
        self._connected = False
        
        # Cache for IV history
        self._iv_cache: Dict[str, List[float]] = {}
        self._last_iv_update: Dict[str, datetime] = {}
    
    def connect_sync(self) -> bool:
        """Connect to IBKR TWS or Gateway"""
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
            
            # Request delayed market data (type 3) if real-time not available
            # This is free and works for paper trading without subscriptions
            # 1=Live, 2=Frozen, 3=Delayed, 4=Delayed-Frozen
            self.ib.reqMarketDataType(3)
            logger.info("Requested delayed market data (type 3)")
            
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
    
    def sleep(self, seconds: float):
        """Sleep while keeping connection alive"""
        self.ib.sleep(seconds)
    
    # ============ Price Data ============
    
    def get_stock_price(self, symbol: str) -> Optional[float]:
        """Get current price for a stock/ETF"""
        try:
            contract = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(contract)
            
            ticker = self.ib.reqMktData(contract, '', False, False)
            self.ib.sleep(3)  # Wait a bit longer for delayed data
            
            price = self._get_price_from_ticker(ticker)
            self.ib.cancelMktData(contract)
            
            if price:
                return price
            
            # If still no price, try to get from historical data
            logger.warning(f"No live/delayed price for {symbol}, trying historical data")
            bars = self.ib.reqHistoricalData(
                contract,
                endDateTime='',
                durationStr='1 D',
                barSizeSetting='1 day',
                whatToShow='TRADES',
                useRTH=True
            )
            if bars:
                return bars[-1].close
            return None
            
        except Exception as e:
            logger.error(f"Error fetching price for {symbol}: {e}")
            return None
    
    def get_historical_data(
        self, 
        symbol: str, 
        duration: str = "60 D",
        bar_size: str = "1 day"
    ) -> Optional[List[Dict]]:
        """Get historical OHLCV data"""
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
    
    # ============ VIX Term Structure ============
    
    def _get_price_from_ticker(self, ticker) -> Optional[float]:
        """Extract price from ticker, handling both live and delayed data"""
        import math
        
        # Try live data first
        price = ticker.marketPrice()
        if price and not math.isnan(price) and price > 0:
            return price
        
        # Try last price
        if ticker.last and not math.isnan(ticker.last) and ticker.last > 0:
            return ticker.last
        
        # Try delayed data fields
        if hasattr(ticker, 'delayedLast') and ticker.delayedLast and not math.isnan(ticker.delayedLast) and ticker.delayedLast > 0:
            return ticker.delayedLast
        
        # Try close price
        if ticker.close and not math.isnan(ticker.close) and ticker.close > 0:
            return ticker.close
            
        # Try delayed close
        if hasattr(ticker, 'delayedClose') and ticker.delayedClose and not math.isnan(ticker.delayedClose) and ticker.delayedClose > 0:
            return ticker.delayedClose
        
        # Try bid/ask midpoint
        bid = ticker.bid if hasattr(ticker, 'bid') and ticker.bid and not math.isnan(ticker.bid) else 0
        ask = ticker.ask if hasattr(ticker, 'ask') and ticker.ask and not math.isnan(ticker.ask) else 0
        if bid > 0 and ask > 0:
            return (bid + ask) / 2
            
        return None
    
    def get_vix(self) -> Optional[float]:
        """Get current VIX level"""
        try:
            vix = Index('VIX', 'CBOE')
            self.ib.qualifyContracts(vix)
            
            ticker = self.ib.reqMktData(vix, '', False, False)
            self.ib.sleep(3)  # Wait a bit longer for delayed data
            
            price = self._get_price_from_ticker(ticker)
            self.ib.cancelMktData(vix)
            
            if price:
                return price
            
            # Fallback to a reasonable default for paper trading
            logger.warning("VIX data unavailable, using default value 18.0")
            return 18.0
            
        except Exception as e:
            logger.error(f"Error fetching VIX: {e}")
            return 18.0  # Default VIX for paper trading
    
    def get_vix3m(self) -> Optional[float]:
        """Get VIX3M (3-month VIX)"""
        try:
            # VIX3M index
            vix3m = Index('VIX3M', 'CBOE')
            self.ib.qualifyContracts(vix3m)
            
            ticker = self.ib.reqMktData(vix3m, '', False, False)
            self.ib.sleep(3)  # Wait a bit longer for delayed data
            
            price = self._get_price_from_ticker(ticker)
            self.ib.cancelMktData(vix3m)
            
            if price:
                return price
            return None
            
        except Exception as e:
            logger.error(f"Error fetching VIX3M: {e}")
            # Fallback: estimate from VIX
            return None
    
    def get_vix_term_structure(self) -> Dict[str, float]:
        """Get full VIX term structure"""
        structure = {}
        
        # VIX (30-day)
        vix = self.get_vix()
        if vix:
            structure['VIX'] = vix
        
        # VIX3M (3-month)
        vix3m = self.get_vix3m()
        if vix3m:
            structure['VIX3M'] = vix3m
        else:
            # Estimate: typically VIX3M is ~10% higher in contango
            structure['VIX3M'] = vix * 1.10 if vix else 20.0
        
        # VIX9D (9-day) - if available
        try:
            vix9d = Index('VIX9D', 'CBOE')
            self.ib.qualifyContracts(vix9d)
            ticker = self.ib.reqMktData(vix9d, '', False, False)
            self.ib.sleep(2)
            price = self._get_price_from_ticker(ticker)
            if price:
                structure['VIX9D'] = price
            self.ib.cancelMktData(vix9d)
        except:
            pass
        
        return structure
    
    # ============ Implied Volatility ============
    
    def get_atm_iv(self, symbol: str, dte_target: int = 30) -> Optional[float]:
        """
        Get ATM implied volatility for a symbol
        Uses nearest monthly expiration
        """
        try:
            # Get current price
            price = self.get_stock_price(symbol)
            if not price:
                return None
            
            # Find ATM strike
            atm_strike = round(price / 5) * 5  # Round to nearest $5
            
            # Get expiration
            expiration = self._get_expiration_for_dte(symbol, dte_target)
            if not expiration:
                return None
            
            # Get both ATM call and put, average their IVs
            call = Option(symbol, expiration, atm_strike, 'C', 'SMART')
            put = Option(symbol, expiration, atm_strike, 'P', 'SMART')
            
            self.ib.qualifyContracts(call, put)
            
            call_ticker = self.ib.reqMktData(call, '', False, False)
            put_ticker = self.ib.reqMktData(put, '', False, False)
            self.ib.sleep(3)
            
            ivs = []
            if call_ticker.modelGreeks and call_ticker.modelGreeks.impliedVol:
                ivs.append(call_ticker.modelGreeks.impliedVol)
            if put_ticker.modelGreeks and put_ticker.modelGreeks.impliedVol:
                ivs.append(put_ticker.modelGreeks.impliedVol)
            
            self.ib.cancelMktData(call)
            self.ib.cancelMktData(put)
            
            return sum(ivs) / len(ivs) if ivs else None
            
        except Exception as e:
            logger.error(f"Error getting ATM IV for {symbol}: {e}")
            return None
    
    def get_iv_history(
        self, 
        symbol: str, 
        lookback_days: int = 252
    ) -> List[float]:
        """
        Get historical IV data
        
        Note: IBKR doesn't provide historical IV directly.
        Options:
        1. Calculate from historical options prices (complex)
        2. Use VIX as proxy for SPY/QQQ
        3. Use external data source
        
        For now, we use VIX history as proxy for broad market IV
        """
        try:
            # For SPY/QQQ/IWM, use VIX as proxy
            if symbol in ['SPY', 'QQQ', 'IWM']:
                vix = Index('VIX', 'CBOE')
                self.ib.qualifyContracts(vix)
                
                bars = self.ib.reqHistoricalData(
                    vix,
                    endDateTime='',
                    durationStr=f"{lookback_days} D",
                    barSizeSetting='1 day',
                    whatToShow='TRADES',
                    useRTH=True,
                    formatDate=1
                )
                
                if bars:
                    # Convert VIX to decimal (VIX of 20 = 0.20 IV)
                    return [bar.close / 100 for bar in bars]
            
            # For individual stocks, we'd need to calculate or use external data
            # Return empty list to indicate no data
            return []
            
        except Exception as e:
            logger.error(f"Error fetching IV history for {symbol}: {e}")
            return []
    
    # ============ Skew Analysis ============
    
    def get_skew_data(
        self, 
        symbol: str, 
        expiration: str,
        underlying_price: float
    ) -> Dict[str, float]:
        """
        Get IV at various deltas for skew analysis
        
        Returns:
            Dict with 'put_25d_iv', 'call_25d_iv', 'atm_iv'
        """
        result = {
            'put_25d_iv': 0.20,
            'call_25d_iv': 0.18,
            'atm_iv': 0.19
        }
        
        try:
            # Estimate strikes for various deltas
            # 25-delta put is roughly 5-7% OTM
            # 25-delta call is roughly 3-5% OTM (skew makes puts further OTM)
            atm_strike = round(underlying_price / 5) * 5
            put_25d_strike = round(underlying_price * 0.94 / 5) * 5  # ~6% OTM
            call_25d_strike = round(underlying_price * 1.04 / 5) * 5  # ~4% OTM
            
            # Get options
            atm_call = Option(symbol, expiration, atm_strike, 'C', 'SMART')
            put_25d = Option(symbol, expiration, put_25d_strike, 'P', 'SMART')
            call_25d = Option(symbol, expiration, call_25d_strike, 'C', 'SMART')
            
            self.ib.qualifyContracts(atm_call, put_25d, call_25d)
            
            # Request market data
            atm_ticker = self.ib.reqMktData(atm_call, '', False, False)
            put_ticker = self.ib.reqMktData(put_25d, '', False, False)
            call_ticker = self.ib.reqMktData(call_25d, '', False, False)
            
            self.ib.sleep(3)
            
            # Extract IVs
            if atm_ticker.modelGreeks and atm_ticker.modelGreeks.impliedVol:
                result['atm_iv'] = atm_ticker.modelGreeks.impliedVol
            
            if put_ticker.modelGreeks and put_ticker.modelGreeks.impliedVol:
                result['put_25d_iv'] = put_ticker.modelGreeks.impliedVol
            
            if call_ticker.modelGreeks and call_ticker.modelGreeks.impliedVol:
                result['call_25d_iv'] = call_ticker.modelGreeks.impliedVol
            
            # Cancel data
            self.ib.cancelMktData(atm_call)
            self.ib.cancelMktData(put_25d)
            self.ib.cancelMktData(call_25d)
            
        except Exception as e:
            logger.error(f"Error getting skew data for {symbol}: {e}")
        
        return result
    
    # ============ Volume and OI ============
    
    def get_volume_oi_data(
        self, 
        symbol: str,
        expiration: str = None
    ) -> Dict:
        """
        Get aggregate volume and open interest data
        
        Returns:
            Dict with put/call volumes, OI, and averages
        """
        result = {
            'put_volume': 0,
            'call_volume': 0,
            'put_oi': 0,
            'call_oi': 0,
            'avg_daily_volume': 100000,  # Default
            'total_volume': 0,
            'total_oi': 0
        }
        
        try:
            # Get options chain
            stock = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(stock)
            
            chains = self.ib.reqSecDefOptParams(
                stock.symbol, '', stock.secType, stock.conId
            )
            
            if not chains:
                return result
            
            chain = next((c for c in chains if c.exchange == 'SMART'), chains[0])
            
            # Get nearest expiration if not specified
            if not expiration:
                today = datetime.now().date()
                valid_exps = [
                    exp for exp in chain.expirations
                    if datetime.strptime(exp, '%Y%m%d').date() > today
                ]
                if valid_exps:
                    expiration = min(valid_exps)
                else:
                    return result
            
            # Get current price for ATM reference
            price = self.get_stock_price(symbol)
            if not price:
                return result
            
            # Get a range of strikes around ATM
            strikes = [
                s for s in chain.strikes
                if price * 0.90 <= s <= price * 1.10
            ]
            
            # Request data for sample of options
            put_vol, call_vol = 0, 0
            put_oi, call_oi = 0, 0
            
            for strike in strikes[:10]:  # Limit to avoid too many requests
                for right in ['P', 'C']:
                    try:
                        opt = Option(symbol, expiration, strike, right, 'SMART')
                        self.ib.qualifyContracts(opt)
                        
                        ticker = self.ib.reqMktData(opt, '', False, False)
                        self.ib.sleep(0.5)
                        
                        vol = ticker.volume if ticker.volume else 0
                        oi = ticker.openInterest if ticker.openInterest else 0
                        
                        if right == 'P':
                            put_vol += vol
                            put_oi += oi
                        else:
                            call_vol += vol
                            call_oi += oi
                        
                        self.ib.cancelMktData(opt)
                        
                    except Exception:
                        continue
            
            result['put_volume'] = put_vol
            result['call_volume'] = call_vol
            result['put_oi'] = put_oi
            result['call_oi'] = call_oi
            result['total_volume'] = put_vol + call_vol
            result['total_oi'] = put_oi + call_oi
            
        except Exception as e:
            logger.error(f"Error getting volume/OI data for {symbol}: {e}")
        
        return result
    
    # ============ Options Chain ============
    
    def _get_expiration_for_dte(
        self, 
        symbol: str, 
        target_dte: int,
        min_dte: int = 20,
        max_dte: int = 50
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
    
    def get_options_with_greeks(
        self, 
        symbol: str, 
        expiration: str,
        strikes: List[float],
        right: str
    ) -> List[Dict]:
        """Get multiple options with their Greeks"""
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
                    'volume': ticker.volume,
                    'open_interest': ticker.openInterest,
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
    
    # ============ Orders ============
    
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
    
    def get_account_summary(self) -> Dict[str, float]:
        """Get account summary values"""
        summary = {}
        for item in self.ib.accountSummary():
            if item.tag in ['NetLiquidation', 'TotalCashValue', 'BuyingPower', 'GrossPositionValue']:
                summary[item.tag] = float(item.value)
        return summary
