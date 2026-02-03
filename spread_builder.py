"""
Spread Builder
Constructs credit spreads and iron condors based on regime and parameters
"""
import logging
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass
from datetime import datetime

from ib_insync import Option

from config import Regime, Strategy, SpreadConfig, REGIME_STRATEGY_MAP
from ibkr_client import IBKRClient

logger = logging.getLogger(__name__)


@dataclass
class SpreadLeg:
    """Single leg of a spread"""
    contract: Option
    action: str  # 'BUY' or 'SELL'
    strike: float
    right: str  # 'C' or 'P'
    delta: float
    bid: float
    ask: float
    mid: float


@dataclass 
class CreditSpread:
    """Constructed credit spread ready for execution"""
    symbol: str
    strategy: Strategy
    expiration: str
    dte: int
    
    # Legs
    short_leg: SpreadLeg
    long_leg: SpreadLeg
    
    # Pricing
    credit: float  # Net credit received
    max_loss: float  # Max loss (width - credit)
    width: float  # Strike width
    
    # Risk metrics
    risk_reward: float  # Credit / Max Loss
    probability_otm: float  # Approximate probability of profit
    
    # Timing
    created_at: datetime
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'strategy': self.strategy.value,
            'expiration': self.expiration,
            'dte': self.dte,
            'short_strike': self.short_leg.strike,
            'long_strike': self.long_leg.strike,
            'credit': self.credit,
            'max_loss': self.max_loss,
            'width': self.width,
            'risk_reward': self.risk_reward,
            'prob_otm': self.probability_otm
        }


@dataclass
class IronCondor:
    """Constructed iron condor ready for execution"""
    symbol: str
    expiration: str
    dte: int
    
    # Put spread (bull put)
    put_short_leg: SpreadLeg
    put_long_leg: SpreadLeg
    
    # Call spread (bear call)
    call_short_leg: SpreadLeg
    call_long_leg: SpreadLeg
    
    # Pricing
    total_credit: float
    max_loss: float
    put_credit: float
    call_credit: float
    
    # Risk metrics
    risk_reward: float
    probability_otm: float
    
    created_at: datetime
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'strategy': 'iron_condor',
            'expiration': self.expiration,
            'dte': self.dte,
            'put_short': self.put_short_leg.strike,
            'put_long': self.put_long_leg.strike,
            'call_short': self.call_short_leg.strike,
            'call_long': self.call_long_leg.strike,
            'credit': self.total_credit,
            'max_loss': self.max_loss,
            'risk_reward': self.risk_reward
        }


class SpreadBuilder:
    """
    Builds credit spreads based on regime and configuration
    """
    
    def __init__(self, client: IBKRClient, config: SpreadConfig):
        self.client = client
        self.config = config
    
    def build_spread_for_regime(
        self, 
        symbol: str, 
        regime: Regime,
        underlying_price: float
    ) -> Optional[CreditSpread | IronCondor]:
        """
        Build the appropriate spread based on regime
        
        Args:
            symbol: Underlying symbol (SPY, QQQ, etc.)
            regime: Current market regime
            underlying_price: Current price of underlying
        
        Returns:
            CreditSpread or IronCondor, or None if can't build
        """
        strategy = REGIME_STRATEGY_MAP.get(regime, Strategy.NO_TRADE)
        
        if strategy == Strategy.NO_TRADE:
            logger.info(f"No trade signal for regime {regime}")
            return None
        
        logger.info(f"Building {strategy.value} for {symbol} in {regime.value} regime")
        
        if strategy == Strategy.BULL_PUT_SPREAD:
            return self._build_bull_put_spread(symbol, underlying_price)
        elif strategy == Strategy.BEAR_CALL_SPREAD:
            return self._build_bear_call_spread(symbol, underlying_price)
        elif strategy == Strategy.IRON_CONDOR:
            return self._build_iron_condor(symbol, underlying_price)
        
        return None
    
    def _build_bull_put_spread(
        self, 
        symbol: str, 
        underlying_price: float
    ) -> Optional[CreditSpread]:
        """
        Build a bull put spread (sell put, buy lower put)
        Profits when underlying stays above short strike
        """
        # Find expiration
        expiration = self.client.get_expiration_for_dte(
            symbol,
            self.config.target_dte,
            self.config.min_dte,
            self.config.max_dte
        )
        
        if not expiration:
            logger.error(f"No valid expiration found for {symbol}")
            return None
        
        # Calculate DTE
        from datetime import datetime
        exp_date = datetime.strptime(expiration, '%Y%m%d').date()
        dte = (exp_date - datetime.now().date()).days
        
        # Find strikes around target delta
        # Short put: sell at ~0.25 delta (OTM)
        # Long put: buy lower strike for protection
        
        short_strike = self._find_strike_by_delta(
            symbol, expiration, 'P', 
            self.config.target_delta, underlying_price
        )
        
        if not short_strike:
            logger.error("Could not find short strike")
            return None
        
        long_strike = short_strike - self.config.spread_width
        
        # Get pricing for both legs
        options_data = self.client.get_options_with_greeks(
            symbol, expiration, [short_strike, long_strike], 'P'
        )
        
        if len(options_data) < 2:
            logger.error("Could not get pricing for both legs")
            return None
        
        short_data = next((o for o in options_data if o['strike'] == short_strike), None)
        long_data = next((o for o in options_data if o['strike'] == long_strike), None)
        
        if not short_data or not long_data:
            return None
        
        # Calculate credit (sell short, buy long)
        # Use mid prices for estimation
        short_mid = short_data['mid'] or (short_data['bid'] + short_data['ask']) / 2
        long_mid = long_data['mid'] or (long_data['bid'] + long_data['ask']) / 2
        
        if not short_mid or not long_mid:
            logger.error("Invalid pricing data")
            return None
        
        credit = short_mid - long_mid
        width = short_strike - long_strike
        max_loss = width - credit
        
        # Validate minimum credit
        if credit < self.config.min_credit:
            logger.info(f"Credit {credit:.2f} below minimum {self.config.min_credit}")
            return None
        
        if credit / width < self.config.min_credit_pct:
            logger.info(f"Credit % {credit/width:.1%} below minimum {self.config.min_credit_pct:.1%}")
            return None
        
        # Build spread legs
        short_leg = SpreadLeg(
            contract=short_data['contract'],
            action='SELL',
            strike=short_strike,
            right='P',
            delta=short_data.get('delta', -0.25),
            bid=short_data['bid'],
            ask=short_data['ask'],
            mid=short_mid
        )
        
        long_leg = SpreadLeg(
            contract=long_data['contract'],
            action='BUY',
            strike=long_strike,
            right='P',
            delta=long_data.get('delta', -0.15),
            bid=long_data['bid'],
            ask=long_data['ask'],
            mid=long_mid
        )
        
        # Probability OTM approximation (1 - |delta|)
        prob_otm = 1 - abs(short_data.get('delta', 0.25))
        
        return CreditSpread(
            symbol=symbol,
            strategy=Strategy.BULL_PUT_SPREAD,
            expiration=expiration,
            dte=dte,
            short_leg=short_leg,
            long_leg=long_leg,
            credit=credit,
            max_loss=max_loss,
            width=width,
            risk_reward=credit / max_loss if max_loss > 0 else 0,
            probability_otm=prob_otm,
            created_at=datetime.now()
        )
    
    def _build_bear_call_spread(
        self, 
        symbol: str, 
        underlying_price: float
    ) -> Optional[CreditSpread]:
        """
        Build a bear call spread (sell call, buy higher call)
        Profits when underlying stays below short strike
        """
        expiration = self.client.get_expiration_for_dte(
            symbol,
            self.config.target_dte,
            self.config.min_dte,
            self.config.max_dte
        )
        
        if not expiration:
            return None
        
        exp_date = datetime.strptime(expiration, '%Y%m%d').date()
        dte = (exp_date - datetime.now().date()).days
        
        # Short call: sell at ~0.25 delta (OTM)
        short_strike = self._find_strike_by_delta(
            symbol, expiration, 'C',
            self.config.target_delta, underlying_price
        )
        
        if not short_strike:
            return None
        
        long_strike = short_strike + self.config.spread_width
        
        options_data = self.client.get_options_with_greeks(
            symbol, expiration, [short_strike, long_strike], 'C'
        )
        
        if len(options_data) < 2:
            return None
        
        short_data = next((o for o in options_data if o['strike'] == short_strike), None)
        long_data = next((o for o in options_data if o['strike'] == long_strike), None)
        
        if not short_data or not long_data:
            return None
        
        short_mid = short_data['mid'] or (short_data['bid'] + short_data['ask']) / 2
        long_mid = long_data['mid'] or (long_data['bid'] + long_data['ask']) / 2
        
        if not short_mid or not long_mid:
            return None
        
        credit = short_mid - long_mid
        width = long_strike - short_strike
        max_loss = width - credit
        
        if credit < self.config.min_credit:
            return None
        
        short_leg = SpreadLeg(
            contract=short_data['contract'],
            action='SELL',
            strike=short_strike,
            right='C',
            delta=short_data.get('delta', 0.25),
            bid=short_data['bid'],
            ask=short_data['ask'],
            mid=short_mid
        )
        
        long_leg = SpreadLeg(
            contract=long_data['contract'],
            action='BUY',
            strike=long_strike,
            right='C',
            delta=long_data.get('delta', 0.15),
            bid=long_data['bid'],
            ask=long_data['ask'],
            mid=long_mid
        )
        
        prob_otm = 1 - abs(short_data.get('delta', 0.25))
        
        return CreditSpread(
            symbol=symbol,
            strategy=Strategy.BEAR_CALL_SPREAD,
            expiration=expiration,
            dte=dte,
            short_leg=short_leg,
            long_leg=long_leg,
            credit=credit,
            max_loss=max_loss,
            width=width,
            risk_reward=credit / max_loss if max_loss > 0 else 0,
            probability_otm=prob_otm,
            created_at=datetime.now()
        )
    
    def _build_iron_condor(
        self, 
        symbol: str, 
        underlying_price: float
    ) -> Optional[IronCondor]:
        """
        Build an iron condor (bull put + bear call)
        Profits when underlying stays in range
        """
        expiration = self.client.get_expiration_for_dte(
            symbol,
            self.config.target_dte,
            self.config.min_dte,
            self.config.max_dte
        )
        
        if not expiration:
            return None
        
        exp_date = datetime.strptime(expiration, '%Y%m%d').date()
        dte = (exp_date - datetime.now().date()).days
        
        # Put side
        put_short_strike = self._find_strike_by_delta(
            symbol, expiration, 'P',
            self.config.target_delta, underlying_price
        )
        
        # Call side
        call_short_strike = self._find_strike_by_delta(
            symbol, expiration, 'C',
            self.config.target_delta, underlying_price
        )
        
        if not put_short_strike or not call_short_strike:
            return None
        
        put_long_strike = put_short_strike - self.config.spread_width
        call_long_strike = call_short_strike + self.config.spread_width
        
        # Get all legs
        put_data = self.client.get_options_with_greeks(
            symbol, expiration, [put_short_strike, put_long_strike], 'P'
        )
        call_data = self.client.get_options_with_greeks(
            symbol, expiration, [call_short_strike, call_long_strike], 'C'
        )
        
        if len(put_data) < 2 or len(call_data) < 2:
            return None
        
        put_short = next((o for o in put_data if o['strike'] == put_short_strike), None)
        put_long = next((o for o in put_data if o['strike'] == put_long_strike), None)
        call_short = next((o for o in call_data if o['strike'] == call_short_strike), None)
        call_long = next((o for o in call_data if o['strike'] == call_long_strike), None)
        
        if not all([put_short, put_long, call_short, call_long]):
            return None
        
        # Calculate credits
        put_credit = (put_short['mid'] or 0) - (put_long['mid'] or 0)
        call_credit = (call_short['mid'] or 0) - (call_long['mid'] or 0)
        total_credit = put_credit + call_credit
        
        max_loss = self.config.spread_width - total_credit
        
        if total_credit < self.config.min_credit * 1.5:  # Higher threshold for IC
            return None
        
        # Build legs
        put_short_leg = SpreadLeg(
            contract=put_short['contract'],
            action='SELL',
            strike=put_short_strike,
            right='P',
            delta=put_short.get('delta', -0.25),
            bid=put_short['bid'],
            ask=put_short['ask'],
            mid=put_short['mid'] or 0
        )
        
        put_long_leg = SpreadLeg(
            contract=put_long['contract'],
            action='BUY',
            strike=put_long_strike,
            right='P',
            delta=put_long.get('delta', -0.15),
            bid=put_long['bid'],
            ask=put_long['ask'],
            mid=put_long['mid'] or 0
        )
        
        call_short_leg = SpreadLeg(
            contract=call_short['contract'],
            action='SELL',
            strike=call_short_strike,
            right='C',
            delta=call_short.get('delta', 0.25),
            bid=call_short['bid'],
            ask=call_short['ask'],
            mid=call_short['mid'] or 0
        )
        
        call_long_leg = SpreadLeg(
            contract=call_long['contract'],
            action='BUY',
            strike=call_long_strike,
            right='C',
            delta=call_long.get('delta', 0.15),
            bid=call_long['bid'],
            ask=call_long['ask'],
            mid=call_long['mid'] or 0
        )
        
        # Probability both sides expire OTM
        put_prob = 1 - abs(put_short.get('delta', 0.25))
        call_prob = 1 - abs(call_short.get('delta', 0.25))
        combined_prob = put_prob * call_prob
        
        return IronCondor(
            symbol=symbol,
            expiration=expiration,
            dte=dte,
            put_short_leg=put_short_leg,
            put_long_leg=put_long_leg,
            call_short_leg=call_short_leg,
            call_long_leg=call_long_leg,
            total_credit=total_credit,
            max_loss=max_loss,
            put_credit=put_credit,
            call_credit=call_credit,
            risk_reward=total_credit / max_loss if max_loss > 0 else 0,
            probability_otm=combined_prob,
            created_at=datetime.now()
        )
    
    def _find_strike_by_delta(
        self,
        symbol: str,
        expiration: str,
        right: str,  # 'C' or 'P'
        target_delta: float,
        underlying_price: float
    ) -> Optional[float]:
        """
        Find the strike closest to target delta
        Uses underlying price to estimate strike range to query
        """
        # Estimate strike range (±15% from current price)
        if right == 'P':
            # For puts, look below current price
            strikes = [
                round(underlying_price * (1 - pct), 0)
                for pct in [0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.15]
            ]
        else:
            # For calls, look above current price
            strikes = [
                round(underlying_price * (1 + pct), 0)
                for pct in [0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.15]
            ]
        
        # Adjust strikes to valid increments (usually $1 or $5 for SPY/QQQ)
        strikes = list(set(strikes))
        strikes.sort()
        
        options_data = self.client.get_options_with_greeks(
            symbol, expiration, strikes, right
        )
        
        if not options_data:
            return None
        
        # Find strike closest to target delta
        best_strike = None
        best_diff = float('inf')
        
        for opt in options_data:
            if opt.get('delta') is None:
                continue
            
            delta = abs(opt['delta'])
            diff = abs(delta - target_delta)
            
            # Check if delta is in acceptable range
            if self.config.delta_range[0] <= delta <= self.config.delta_range[1]:
                if diff < best_diff:
                    best_diff = diff
                    best_strike = opt['strike']
        
        return best_strike


def format_spread_alert(spread: CreditSpread) -> str:
    """Format spread for Telegram alert"""
    return f"""
🔔 NEW TRADE SIGNAL

{spread.strategy.value.upper().replace('_', ' ')} on {spread.symbol}

📅 Expiration: {spread.expiration} ({spread.dte} DTE)
💰 Credit: ${spread.credit:.2f}
⚠️ Max Loss: ${spread.max_loss:.2f}
📊 Risk/Reward: {spread.risk_reward:.1%}
🎯 Prob OTM: {spread.probability_otm:.0%}

Short: {spread.short_leg.strike} {spread.short_leg.right}
Long: {spread.long_leg.strike} {spread.long_leg.right}
"""


def format_condor_alert(condor: IronCondor) -> str:
    """Format iron condor for Telegram alert"""
    return f"""
🔔 NEW TRADE SIGNAL

IRON CONDOR on {condor.symbol}

📅 Expiration: {condor.expiration} ({condor.dte} DTE)
💰 Total Credit: ${condor.total_credit:.2f}
⚠️ Max Loss: ${condor.max_loss:.2f}
📊 Risk/Reward: {condor.risk_reward:.1%}
🎯 Prob OTM: {condor.probability_otm:.0%}

PUT SIDE:
  Short: {condor.put_short_leg.strike}P (${condor.put_credit:.2f})
  Long: {condor.put_long_leg.strike}P

CALL SIDE:
  Short: {condor.call_short_leg.strike}C (${condor.call_credit:.2f})
  Long: {condor.call_long_leg.strike}C
"""
