"""
Liquidity Filter
Ensures we only trade options with acceptable bid-ask spreads

Poor liquidity means:
- Wide spreads eat into credit
- Difficult fills
- Slippage on exit

Rules:
- Max bid-ask spread as % of mid price
- Minimum open interest
- Minimum daily volume
"""
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class LiquidityMetrics:
    """Liquidity metrics for an option"""
    symbol: str
    strike: float
    right: str  # 'C' or 'P'
    expiration: str
    
    bid: float
    ask: float
    mid: float
    spread: float
    spread_pct: float  # Spread as % of mid
    
    volume: int
    open_interest: int
    vol_oi_ratio: float
    
    is_liquid: bool
    rejection_reason: Optional[str]


@dataclass 
class LiquidityConfig:
    """Liquidity filter configuration"""
    # Bid-ask spread limits
    max_spread_pct: float = 0.10      # Max 10% spread
    max_spread_abs: float = 0.30      # Max $0.30 absolute spread
    
    # Volume requirements
    min_open_interest: int = 100      # Minimum OI
    min_daily_volume: int = 10        # Minimum volume (can be low for less active)
    
    # Combination requirements (for spreads)
    max_combo_spread_pct: float = 0.15  # Slightly higher for combos
    
    # Underlying-specific overrides
    # More liquid underlyings can have tighter requirements
    symbol_overrides: Dict[str, Dict] = None
    
    def __post_init__(self):
        if self.symbol_overrides is None:
            self.symbol_overrides = {
                'SPY': {
                    'max_spread_pct': 0.05,
                    'max_spread_abs': 0.10,
                    'min_open_interest': 500,
                },
                'QQQ': {
                    'max_spread_pct': 0.05,
                    'max_spread_abs': 0.15,
                    'min_open_interest': 300,
                },
                'IWM': {
                    'max_spread_pct': 0.08,
                    'max_spread_abs': 0.20,
                    'min_open_interest': 200,
                },
            }
    
    def get_limits(self, symbol: str) -> Dict:
        """Get limits for a specific symbol"""
        if symbol in self.symbol_overrides:
            base = {
                'max_spread_pct': self.max_spread_pct,
                'max_spread_abs': self.max_spread_abs,
                'min_open_interest': self.min_open_interest,
                'min_daily_volume': self.min_daily_volume,
            }
            base.update(self.symbol_overrides[symbol])
            return base
        return {
            'max_spread_pct': self.max_spread_pct,
            'max_spread_abs': self.max_spread_abs,
            'min_open_interest': self.min_open_interest,
            'min_daily_volume': self.min_daily_volume,
        }


class LiquidityFilter:
    """
    Filters options based on liquidity requirements
    """
    
    def __init__(self, config: LiquidityConfig = None):
        self.config = config or LiquidityConfig()
    
    def check_option(
        self,
        symbol: str,
        strike: float,
        right: str,
        expiration: str,
        bid: float,
        ask: float,
        volume: int = 0,
        open_interest: int = 0
    ) -> LiquidityMetrics:
        """
        Check if a single option meets liquidity requirements
        """
        limits = self.config.get_limits(symbol)
        
        # Calculate metrics
        mid = (bid + ask) / 2 if bid and ask else 0
        spread = ask - bid if bid and ask else float('inf')
        spread_pct = spread / mid if mid > 0 else float('inf')
        vol_oi_ratio = volume / open_interest if open_interest > 0 else 0
        
        # Check requirements
        rejection_reason = None
        is_liquid = True
        
        if spread_pct > limits['max_spread_pct']:
            is_liquid = False
            rejection_reason = f"Spread {spread_pct:.1%} > {limits['max_spread_pct']:.1%}"
        elif spread > limits['max_spread_abs']:
            is_liquid = False
            rejection_reason = f"Spread ${spread:.2f} > ${limits['max_spread_abs']:.2f}"
        elif open_interest < limits['min_open_interest']:
            is_liquid = False
            rejection_reason = f"OI {open_interest} < {limits['min_open_interest']}"
        elif bid <= 0 or ask <= 0:
            is_liquid = False
            rejection_reason = "No valid bid/ask"
        
        return LiquidityMetrics(
            symbol=symbol,
            strike=strike,
            right=right,
            expiration=expiration,
            bid=bid,
            ask=ask,
            mid=mid,
            spread=spread,
            spread_pct=spread_pct,
            volume=volume,
            open_interest=open_interest,
            vol_oi_ratio=vol_oi_ratio,
            is_liquid=is_liquid,
            rejection_reason=rejection_reason
        )
    
    def check_spread(
        self,
        short_leg: Dict,
        long_leg: Dict,
        symbol: str
    ) -> Tuple[bool, str, float]:
        """
        Check if a spread (combination of two options) is liquid
        
        Args:
            short_leg: Dict with bid, ask, volume, open_interest
            long_leg: Dict with bid, ask, volume, open_interest
            symbol: Underlying symbol
        
        Returns:
            (is_liquid, reason, estimated_fill_price)
        """
        # Check individual legs
        short_metrics = self.check_option(
            symbol=symbol,
            strike=short_leg.get('strike', 0),
            right=short_leg.get('right', 'P'),
            expiration=short_leg.get('expiration', ''),
            bid=short_leg.get('bid', 0),
            ask=short_leg.get('ask', 0),
            volume=short_leg.get('volume', 0),
            open_interest=short_leg.get('open_interest', 0)
        )
        
        long_metrics = self.check_option(
            symbol=symbol,
            strike=long_leg.get('strike', 0),
            right=long_leg.get('right', 'P'),
            expiration=long_leg.get('expiration', ''),
            bid=long_leg.get('bid', 0),
            ask=long_leg.get('ask', 0),
            volume=long_leg.get('volume', 0),
            open_interest=long_leg.get('open_interest', 0)
        )
        
        # If either leg is illiquid, reject
        if not short_metrics.is_liquid:
            return False, f"Short leg: {short_metrics.rejection_reason}", 0
        
        if not long_metrics.is_liquid:
            return False, f"Long leg: {long_metrics.rejection_reason}", 0
        
        # Calculate combo spread
        # For credit spread: sell short at bid, buy long at ask
        # Natural price = short_bid - long_ask (what we'd get filled at naturally)
        natural_credit = short_metrics.bid - long_metrics.ask
        
        # Mid price = short_mid - long_mid (theoretical fair value)
        mid_credit = short_metrics.mid - long_metrics.mid
        
        # Combo spread as % of mid credit
        if mid_credit > 0:
            combo_spread_pct = (mid_credit - natural_credit) / mid_credit
        else:
            combo_spread_pct = float('inf')
        
        if combo_spread_pct > self.config.max_combo_spread_pct:
            return False, f"Combo spread {combo_spread_pct:.1%} too wide", mid_credit
        
        # Estimate realistic fill (between natural and mid)
        estimated_fill = (natural_credit + mid_credit) / 2
        
        return True, "Liquid", estimated_fill
    
    def check_iron_condor(
        self,
        put_short: Dict,
        put_long: Dict,
        call_short: Dict,
        call_long: Dict,
        symbol: str
    ) -> Tuple[bool, str, float]:
        """
        Check if an iron condor (4 legs) is liquid
        """
        # Check put spread
        put_ok, put_reason, put_credit = self.check_spread(
            put_short, put_long, symbol
        )
        
        if not put_ok:
            return False, f"Put spread: {put_reason}", 0
        
        # Check call spread
        call_ok, call_reason, call_credit = self.check_spread(
            call_short, call_long, symbol
        )
        
        if not call_ok:
            return False, f"Call spread: {call_reason}", 0
        
        total_credit = put_credit + call_credit
        return True, "Liquid", total_credit
    
    def find_liquid_strikes(
        self,
        options_data: List[Dict],
        symbol: str,
        min_count: int = 5
    ) -> List[Dict]:
        """
        Filter options data to only liquid strikes
        
        Args:
            options_data: List of option dicts with bid/ask/volume/oi
            symbol: Underlying symbol
            min_count: Minimum number of liquid strikes required
        
        Returns:
            Filtered list of liquid options
        """
        liquid_options = []
        
        for opt in options_data:
            metrics = self.check_option(
                symbol=symbol,
                strike=opt.get('strike', 0),
                right=opt.get('right', 'P'),
                expiration=opt.get('expiration', ''),
                bid=opt.get('bid', 0),
                ask=opt.get('ask', 0),
                volume=opt.get('volume', 0),
                open_interest=opt.get('open_interest', 0)
            )
            
            if metrics.is_liquid:
                opt['liquidity_metrics'] = metrics
                liquid_options.append(opt)
            else:
                logger.debug(
                    f"Filtered out {symbol} {opt.get('strike')} {opt.get('right')}: "
                    f"{metrics.rejection_reason}"
                )
        
        if len(liquid_options) < min_count:
            logger.warning(
                f"Only {len(liquid_options)} liquid strikes found for {symbol} "
                f"(need {min_count})"
            )
        
        return liquid_options


def estimate_slippage(
    theoretical_credit: float,
    spread_pct: float
) -> float:
    """
    Estimate expected slippage based on spread width
    
    Rule of thumb: expect to give up ~25-50% of the spread
    """
    expected_slippage_pct = spread_pct * 0.35  # 35% of spread
    return theoretical_credit * (1 - expected_slippage_pct)


def format_liquidity_report(metrics: LiquidityMetrics) -> str:
    """Format liquidity metrics for display"""
    status = "✅ LIQUID" if metrics.is_liquid else "❌ ILLIQUID"
    
    return f"""
{status}: {metrics.symbol} {metrics.strike} {metrics.right}

Bid: ${metrics.bid:.2f}
Ask: ${metrics.ask:.2f}
Mid: ${metrics.mid:.2f}
Spread: ${metrics.spread:.2f} ({metrics.spread_pct:.1%})

Volume: {metrics.volume:,}
Open Interest: {metrics.open_interest:,}

{f'Rejection: {metrics.rejection_reason}' if metrics.rejection_reason else ''}
"""
