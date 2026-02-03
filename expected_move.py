"""
Expected Move Calculator
Calculates expected move from ATM straddle pricing

Why straddle-based expected move?
- Market-implied, not theoretical
- Includes actual supply/demand for options
- Accounts for skew and term structure
- What market makers are actually pricing in

Formula:
Expected Move = ATM Straddle Price × 0.85
(The 0.85 multiplier adjusts for the fact that you need price
to move BEYOND the straddle to profit from buying it)

Uses:
- Strike selection (set short strikes outside expected move)
- Probability estimation
- Risk assessment
- Comparing to historical realized moves
"""
import logging
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
from datetime import datetime
import math

logger = logging.getLogger(__name__)


@dataclass
class ExpectedMoveData:
    """Expected move calculation result"""
    symbol: str
    underlying_price: float
    expiration: str
    dte: int
    
    # Straddle pricing
    atm_strike: float
    call_price: float
    put_price: float
    straddle_price: float
    
    # Expected move
    expected_move_dollars: float
    expected_move_pct: float
    
    # Range (1 standard deviation)
    upper_bound: float  # Price + expected move
    lower_bound: float  # Price - expected move
    
    # Implied volatility (annualized, backed out from straddle)
    implied_vol: float
    
    # Historical comparison
    realized_move_20d: Optional[float] = None
    move_ratio: Optional[float] = None  # Expected / Realized
    
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


class ExpectedMoveCalculator:
    """
    Calculates expected move from straddle pricing
    """
    
    # Standard multiplier (85% of straddle captures ~1 std dev move)
    STRADDLE_MULTIPLIER = 0.85
    
    def __init__(self):
        pass
    
    def calculate_from_straddle(
        self,
        symbol: str,
        underlying_price: float,
        atm_strike: float,
        call_price: float,
        put_price: float,
        expiration: str,
        dte: int,
        historical_moves: List[float] = None
    ) -> ExpectedMoveData:
        """
        Calculate expected move from ATM straddle prices
        
        Args:
            symbol: Underlying symbol
            underlying_price: Current price
            atm_strike: ATM strike price
            call_price: ATM call mid price
            put_price: ATM put mid price
            expiration: Expiration date string
            dte: Days to expiration
            historical_moves: List of historical daily moves (for comparison)
        """
        # Straddle price = call + put
        straddle_price = call_price + put_price
        
        # Expected move (85% of straddle)
        expected_move = straddle_price * self.STRADDLE_MULTIPLIER
        expected_move_pct = expected_move / underlying_price
        
        # Bounds
        upper_bound = underlying_price + expected_move
        lower_bound = underlying_price - expected_move
        
        # Back out implied volatility
        # Simplified: IV ≈ (Straddle / Price) * sqrt(365/DTE) * 100
        if dte > 0:
            implied_vol = (straddle_price / underlying_price) * math.sqrt(365 / dte)
        else:
            implied_vol = 0
        
        # Compare to historical
        realized_move = None
        move_ratio = None
        
        if historical_moves and len(historical_moves) >= 20:
            # Calculate realized volatility over same period
            realized_move = self._calculate_realized_move(
                historical_moves, 
                dte
            )
            if realized_move > 0:
                move_ratio = expected_move_pct / realized_move
        
        return ExpectedMoveData(
            symbol=symbol,
            underlying_price=underlying_price,
            expiration=expiration,
            dte=dte,
            atm_strike=atm_strike,
            call_price=call_price,
            put_price=put_price,
            straddle_price=straddle_price,
            expected_move_dollars=expected_move,
            expected_move_pct=expected_move_pct,
            upper_bound=upper_bound,
            lower_bound=lower_bound,
            implied_vol=implied_vol,
            realized_move_20d=realized_move,
            move_ratio=move_ratio
        )
    
    def calculate_from_iv(
        self,
        symbol: str,
        underlying_price: float,
        implied_vol: float,
        dte: int
    ) -> Tuple[float, float, float]:
        """
        Calculate expected move from IV directly
        
        Expected Move = Price × IV × sqrt(DTE/365)
        
        Returns:
            (expected_move_dollars, upper_bound, lower_bound)
        """
        expected_move = underlying_price * implied_vol * math.sqrt(dte / 365)
        
        upper = underlying_price + expected_move
        lower = underlying_price - expected_move
        
        return expected_move, upper, lower
    
    def _calculate_realized_move(
        self,
        daily_moves: List[float],
        forward_days: int
    ) -> float:
        """
        Calculate realized move over historical period
        
        Uses 20-day realized volatility scaled to forward_days
        """
        if len(daily_moves) < 20:
            return 0
        
        # Calculate standard deviation of daily returns
        recent_moves = daily_moves[-20:]
        
        import numpy as np
        daily_std = np.std(recent_moves)
        
        # Scale to forward period
        # Volatility scales with sqrt(time)
        forward_move = daily_std * math.sqrt(forward_days)
        
        return forward_move
    
    def get_probability_otm(
        self,
        strike: float,
        underlying_price: float,
        expected_move: float,
        is_put: bool
    ) -> float:
        """
        Estimate probability of option expiring OTM
        
        Uses normal distribution approximation
        Based on number of standard deviations away
        """
        if expected_move <= 0:
            return 0.5
        
        # Distance from current price to strike as multiple of expected move
        distance = abs(strike - underlying_price)
        std_devs = distance / expected_move
        
        # Approximate probability using normal CDF
        # P(OTM) for put = P(price > strike) = 1 - CDF(-std_devs)
        # P(OTM) for call = P(price < strike) = CDF(std_devs)
        
        # Simplified normal CDF approximation
        prob = self._normal_cdf(std_devs)
        
        if is_put:
            return prob  # Put OTM when price stays above
        else:
            return prob  # Call OTM when price stays below
    
    def _normal_cdf(self, x: float) -> float:
        """Approximate standard normal CDF"""
        # Using error function approximation
        import math
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))
    
    def suggest_strikes(
        self,
        expected_move_data: ExpectedMoveData,
        target_prob_otm: float = 0.70,
        spread_width: float = 5.0
    ) -> Dict[str, Tuple[float, float]]:
        """
        Suggest strikes for credit spreads based on expected move
        
        Args:
            expected_move_data: Expected move calculation
            target_prob_otm: Target probability of expiring OTM
            spread_width: Width of spreads
        
        Returns:
            Dict with 'put_spread' and 'call_spread' strike tuples
        """
        price = expected_move_data.underlying_price
        em = expected_move_data.expected_move_dollars
        
        # For 70% prob OTM, go ~1 standard deviation out
        # For 85% prob OTM, go ~1.5 standard deviations out
        multiplier = {
            0.70: 1.0,
            0.75: 1.15,
            0.80: 1.28,
            0.85: 1.44,
        }.get(target_prob_otm, 1.0)
        
        target_distance = em * multiplier
        
        # Put spread (below market)
        put_short = round((price - target_distance) / 5) * 5  # Round to $5
        put_long = put_short - spread_width
        
        # Call spread (above market)
        call_short = round((price + target_distance) / 5) * 5
        call_long = call_short + spread_width
        
        return {
            'put_spread': (put_short, put_long),
            'call_spread': (call_short, call_long),
            'expected_move': em,
            'target_distance': target_distance,
        }


def calculate_weekly_expected_moves(
    symbol: str,
    underlying_price: float,
    atm_straddles: Dict[str, Tuple[float, float]],  # expiration -> (call, put)
) -> List[ExpectedMoveData]:
    """
    Calculate expected moves for multiple expirations
    
    Useful for:
    - Choosing optimal expiration
    - Understanding term structure of expected moves
    """
    calculator = ExpectedMoveCalculator()
    results = []
    
    today = datetime.now().date()
    
    for exp, (call_price, put_price) in atm_straddles.items():
        exp_date = datetime.strptime(exp, '%Y%m%d').date()
        dte = (exp_date - today).days
        
        if dte <= 0:
            continue
        
        # Find nearest ATM strike
        atm_strike = round(underlying_price / 5) * 5
        
        em_data = calculator.calculate_from_straddle(
            symbol=symbol,
            underlying_price=underlying_price,
            atm_strike=atm_strike,
            call_price=call_price,
            put_price=put_price,
            expiration=exp,
            dte=dte
        )
        
        results.append(em_data)
    
    return sorted(results, key=lambda x: x.dte)


def format_expected_move_report(data: ExpectedMoveData) -> str:
    """Format expected move for display"""
    
    move_ratio_str = ""
    if data.move_ratio:
        if data.move_ratio > 1.2:
            move_ratio_str = f"📈 Implied > Realized ({data.move_ratio:.2f}x) - RICH"
        elif data.move_ratio < 0.8:
            move_ratio_str = f"📉 Implied < Realized ({data.move_ratio:.2f}x) - CHEAP"
        else:
            move_ratio_str = f"➡️ Implied ≈ Realized ({data.move_ratio:.2f}x)"
    
    return f"""
📊 EXPECTED MOVE: {data.symbol}
{'='*50}

Current Price: ${data.underlying_price:.2f}
Expiration: {data.expiration} ({data.dte} DTE)

ATM STRADDLE ({data.atm_strike}):
  Call: ${data.call_price:.2f}
  Put: ${data.put_price:.2f}
  Total: ${data.straddle_price:.2f}

EXPECTED MOVE:
  ± ${data.expected_move_dollars:.2f} ({data.expected_move_pct:.1%})
  
  Upper: ${data.upper_bound:.2f}
  Lower: ${data.lower_bound:.2f}

IMPLIED VOL: {data.implied_vol:.1%} (annualized)

{move_ratio_str}

STRIKE SUGGESTIONS (70% Prob OTM):
  Put spread below: ${data.lower_bound:.0f}
  Call spread above: ${data.upper_bound:.0f}
"""


def format_multi_expiration_moves(moves: List[ExpectedMoveData]) -> str:
    """Format expected moves across multiple expirations"""
    
    lines = [
        "EXPECTED MOVE BY EXPIRATION",
        "=" * 60,
        f"{'Expiration':<12} {'DTE':>5} {'Move $':>10} {'Move %':>8} {'IV':>8}",
        "-" * 60,
    ]
    
    for em in moves:
        lines.append(
            f"{em.expiration:<12} {em.dte:>5} "
            f"${em.expected_move_dollars:>8.2f} {em.expected_move_pct:>7.1%} "
            f"{em.implied_vol:>7.1%}"
        )
    
    return "\n".join(lines)
