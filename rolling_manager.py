"""
Position Rolling Logic
Manages rolling positions instead of taking stop losses

Rolling = closing current position and opening new one at:
- Different strikes (further OTM)
- Different expiration (more time)
- Or both

Why roll instead of stop?
- Avoid locking in loss
- Give trade more time/room to work
- Collect additional credit to reduce cost basis

When to roll:
- Position approaching short strike
- Position at X% loss but not max loss
- DTE getting low but still have room
"""
import logging
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class RollType(Enum):
    """Types of rolls"""
    ROLL_OUT = "roll_out"           # Same strikes, later expiration
    ROLL_DOWN = "roll_down"         # Lower strikes (for puts)
    ROLL_UP = "roll_up"             # Higher strikes (for calls)
    ROLL_OUT_DOWN = "roll_out_down" # Later expiration + lower strikes
    ROLL_OUT_UP = "roll_out_up"     # Later expiration + higher strikes
    ROLL_WIDE = "roll_wide"         # Wider strikes (iron condor)


class RollReason(Enum):
    """Reason for rolling"""
    TESTED = "tested"               # Price approaching short strike
    LOSS_LIMIT = "loss_limit"       # At loss threshold
    DTE_MANAGEMENT = "dte_management"  # Time running out
    DEFENSIVE = "defensive"         # Market conditions changed
    PROFIT_LOCK = "profit_lock"     # Roll to lock partial profit


@dataclass
class RollCandidate:
    """A potential roll opportunity"""
    position_id: str
    symbol: str
    current_strategy: str
    
    # Current position details
    current_short_strike: float
    current_long_strike: float
    current_expiration: str
    current_dte: int
    entry_credit: float
    current_value: float  # Cost to close
    current_pnl: float
    current_pnl_pct: float
    
    # Why we might roll
    roll_reason: RollReason
    urgency: str  # 'low', 'medium', 'high'
    
    # Underlying price info
    underlying_price: float
    distance_to_short: float  # % distance from price to short strike
    
    # Suggested roll
    suggested_roll_type: RollType
    suggested_new_strikes: Tuple[float, float]
    suggested_new_expiration: str
    suggested_new_dte: int
    estimated_roll_credit: float  # Credit received from roll (can be debit)
    
    # Analysis
    new_distance_to_short: float
    break_even_price: float  # Price at which original + roll = break even
    max_loss_after_roll: float


@dataclass
class RollConfig:
    """Configuration for rolling decisions"""
    
    # When to consider rolling
    tested_threshold: float = 0.02    # Roll when price within 2% of short strike
    loss_threshold_pct: float = 1.0   # Roll at 100% of credit loss (1x)
    min_dte_to_roll: int = 7          # Don't roll if less than 7 DTE
    
    # Roll parameters
    roll_out_weeks: int = 2           # How many weeks to roll out
    roll_strike_increments: int = 1   # How many strikes to roll (1 = one strike width)
    
    # Credit requirements
    min_roll_credit: float = 0.10     # Minimum credit to accept for roll
    accept_debit_roll: bool = True    # Accept rolling for a debit
    max_debit_pct: float = 0.25       # Max debit as % of original credit
    
    # Maximum rolls
    max_rolls_per_position: int = 2   # Don't roll more than 2x
    
    # Iron condor specific
    ic_roll_tested_side_only: bool = True  # Only roll tested side of IC


class RollingManager:
    """
    Manages rolling decisions for positions
    """
    
    def __init__(self, config: RollConfig = None):
        self.config = config or RollConfig()
        self.roll_history: Dict[str, List[Dict]] = {}  # Track rolls per position
    
    def analyze_position_for_roll(
        self,
        position_id: str,
        symbol: str,
        strategy: str,
        short_strike: float,
        long_strike: float,
        expiration: str,
        entry_credit: float,
        current_value: float,
        underlying_price: float,
        available_expirations: List[str],
        available_strikes: List[float],
        roll_count: int = 0
    ) -> Optional[RollCandidate]:
        """
        Analyze if a position should be rolled
        
        Returns:
            RollCandidate if roll is recommended, None otherwise
        """
        # Check roll limit
        if roll_count >= self.config.max_rolls_per_position:
            logger.info(f"{position_id}: Max rolls ({self.config.max_rolls_per_position}) reached")
            return None
        
        # Calculate metrics
        exp_date = datetime.strptime(expiration, '%Y%m%d').date()
        dte = (exp_date - datetime.now().date()).days
        
        if dte < self.config.min_dte_to_roll:
            logger.info(f"{position_id}: DTE ({dte}) too low to roll")
            return None
        
        current_pnl = entry_credit - current_value
        current_pnl_pct = current_pnl / entry_credit if entry_credit > 0 else 0
        
        # Determine if position is tested (price near short strike)
        is_put = 'put' in strategy.lower()
        if is_put:
            distance_to_short = (underlying_price - short_strike) / underlying_price
            is_tested = distance_to_short < self.config.tested_threshold
        else:
            distance_to_short = (short_strike - underlying_price) / underlying_price
            is_tested = distance_to_short < self.config.tested_threshold
        
        # Determine roll reason
        roll_reason = None
        urgency = 'low'
        
        if is_tested:
            roll_reason = RollReason.TESTED
            urgency = 'high' if distance_to_short < 0.01 else 'medium'
        elif current_pnl_pct < -self.config.loss_threshold_pct:
            roll_reason = RollReason.LOSS_LIMIT
            urgency = 'medium'
        elif dte <= 21 and current_pnl_pct < 0:
            roll_reason = RollReason.DTE_MANAGEMENT
            urgency = 'medium'
        
        if not roll_reason:
            return None  # No roll needed
        
        # Determine roll type and new strikes
        roll_type, new_strikes = self._determine_roll_parameters(
            strategy=strategy,
            short_strike=short_strike,
            long_strike=long_strike,
            underlying_price=underlying_price,
            available_strikes=available_strikes,
            roll_reason=roll_reason
        )
        
        # Find new expiration
        new_expiration = self._find_roll_expiration(
            current_expiration=expiration,
            available_expirations=available_expirations,
            weeks_out=self.config.roll_out_weeks
        )
        
        if not new_expiration:
            logger.warning(f"{position_id}: No suitable expiration found for roll")
            return None
        
        new_exp_date = datetime.strptime(new_expiration, '%Y%m%d').date()
        new_dte = (new_exp_date - datetime.now().date()).days
        
        # Estimate roll credit (simplified - in production, get actual quotes)
        estimated_roll_credit = self._estimate_roll_credit(
            current_value=current_value,
            new_dte=new_dte,
            strike_change=new_strikes[0] - short_strike if is_put else short_strike - new_strikes[0]
        )
        
        # Calculate new distance
        if is_put:
            new_distance = (underlying_price - new_strikes[0]) / underlying_price
        else:
            new_distance = (new_strikes[0] - underlying_price) / underlying_price
        
        # Calculate break-even
        total_credit = entry_credit + estimated_roll_credit
        max_loss_after_roll = abs(new_strikes[1] - new_strikes[0]) - total_credit
        
        return RollCandidate(
            position_id=position_id,
            symbol=symbol,
            current_strategy=strategy,
            current_short_strike=short_strike,
            current_long_strike=long_strike,
            current_expiration=expiration,
            current_dte=dte,
            entry_credit=entry_credit,
            current_value=current_value,
            current_pnl=current_pnl,
            current_pnl_pct=current_pnl_pct,
            roll_reason=roll_reason,
            urgency=urgency,
            underlying_price=underlying_price,
            distance_to_short=distance_to_short,
            suggested_roll_type=roll_type,
            suggested_new_strikes=new_strikes,
            suggested_new_expiration=new_expiration,
            suggested_new_dte=new_dte,
            estimated_roll_credit=estimated_roll_credit,
            new_distance_to_short=new_distance,
            break_even_price=new_strikes[0] - total_credit if is_put else new_strikes[0] + total_credit,
            max_loss_after_roll=max_loss_after_roll
        )
    
    def _determine_roll_parameters(
        self,
        strategy: str,
        short_strike: float,
        long_strike: float,
        underlying_price: float,
        available_strikes: List[float],
        roll_reason: RollReason
    ) -> Tuple[RollType, Tuple[float, float]]:
        """Determine how to roll (direction and new strikes)"""
        
        width = abs(short_strike - long_strike)
        is_put = 'put' in strategy.lower()
        
        if roll_reason == RollReason.TESTED:
            # Roll away from price
            if is_put:
                # Roll down (lower strikes)
                new_short = self._find_next_strike(
                    short_strike, 
                    available_strikes, 
                    direction='down',
                    steps=self.config.roll_strike_increments
                )
                return RollType.ROLL_OUT_DOWN, (new_short, new_short - width)
            else:
                # Roll up (higher strikes)
                new_short = self._find_next_strike(
                    short_strike,
                    available_strikes,
                    direction='up',
                    steps=self.config.roll_strike_increments
                )
                return RollType.ROLL_OUT_UP, (new_short, new_short + width)
        
        else:
            # Just roll out for time
            return RollType.ROLL_OUT, (short_strike, long_strike)
    
    def _find_next_strike(
        self,
        current_strike: float,
        available_strikes: List[float],
        direction: str,
        steps: int = 1
    ) -> float:
        """Find next available strike in given direction"""
        sorted_strikes = sorted(available_strikes)
        
        try:
            current_idx = sorted_strikes.index(current_strike)
        except ValueError:
            # Current strike not in list, find nearest
            current_idx = min(
                range(len(sorted_strikes)),
                key=lambda i: abs(sorted_strikes[i] - current_strike)
            )
        
        if direction == 'down':
            new_idx = max(0, current_idx - steps)
        else:
            new_idx = min(len(sorted_strikes) - 1, current_idx + steps)
        
        return sorted_strikes[new_idx]
    
    def _find_roll_expiration(
        self,
        current_expiration: str,
        available_expirations: List[str],
        weeks_out: int
    ) -> Optional[str]:
        """Find expiration approximately X weeks further out"""
        current_date = datetime.strptime(current_expiration, '%Y%m%d').date()
        target_date = current_date + timedelta(weeks=weeks_out)
        
        valid_exps = [
            exp for exp in available_expirations
            if datetime.strptime(exp, '%Y%m%d').date() > current_date
        ]
        
        if not valid_exps:
            return None
        
        # Find closest to target
        return min(
            valid_exps,
            key=lambda exp: abs(
                (datetime.strptime(exp, '%Y%m%d').date() - target_date).days
            )
        )
    
    def _estimate_roll_credit(
        self,
        current_value: float,
        new_dte: int,
        strike_change: float
    ) -> float:
        """
        Estimate credit received from roll
        
        This is simplified - in production you'd get actual quotes.
        Generally:
        - More DTE = more credit
        - Rolling away from price = more credit
        """
        # Base: need to pay current_value to close
        close_cost = current_value
        
        # New position credit estimate
        # More DTE = sqrt(dte) roughly proportional
        # Rolling strikes helps if moving away from price
        
        base_credit = current_value * 1.2  # Assume ~20% more for extra time
        strike_adjustment = strike_change * 0.05  # $0.05 per $1 of strike change
        
        new_credit = base_credit + strike_adjustment
        
        # Net = new credit - close cost
        return new_credit - close_cost
    
    def should_roll(self, candidate: RollCandidate) -> Tuple[bool, str]:
        """
        Make final decision on whether to roll
        """
        # Don't roll for a big debit
        if candidate.estimated_roll_credit < -candidate.entry_credit * self.config.max_debit_pct:
            return False, f"Roll debit too large (${candidate.estimated_roll_credit:.2f})"
        
        # Don't roll if new position still not far from price
        if candidate.new_distance_to_short < self.config.tested_threshold:
            return False, "New strikes still too close to price"
        
        # High urgency = definitely roll
        if candidate.urgency == 'high':
            return True, f"High urgency roll due to {candidate.roll_reason.value}"
        
        # Medium urgency = roll if credit is acceptable
        if candidate.urgency == 'medium':
            if candidate.estimated_roll_credit >= self.config.min_roll_credit:
                return True, f"Roll for credit: ${candidate.estimated_roll_credit:.2f}"
            elif self.config.accept_debit_roll:
                return True, f"Defensive roll (small debit acceptable)"
        
        return False, "Roll not recommended"
    
    def record_roll(
        self,
        position_id: str,
        roll_candidate: RollCandidate,
        actual_credit: float
    ):
        """Record a completed roll"""
        if position_id not in self.roll_history:
            self.roll_history[position_id] = []
        
        self.roll_history[position_id].append({
            'timestamp': datetime.now().isoformat(),
            'roll_type': roll_candidate.suggested_roll_type.value,
            'reason': roll_candidate.roll_reason.value,
            'old_strikes': (roll_candidate.current_short_strike, roll_candidate.current_long_strike),
            'new_strikes': roll_candidate.suggested_new_strikes,
            'old_expiration': roll_candidate.current_expiration,
            'new_expiration': roll_candidate.suggested_new_expiration,
            'estimated_credit': roll_candidate.estimated_roll_credit,
            'actual_credit': actual_credit,
        })
    
    def get_roll_count(self, position_id: str) -> int:
        """Get number of times a position has been rolled"""
        return len(self.roll_history.get(position_id, []))


def format_roll_recommendation(candidate: RollCandidate, should: bool, reason: str) -> str:
    """Format roll recommendation for display/notification"""
    
    emoji = "🔄" if should else "⏸️"
    urgency_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(candidate.urgency, "")
    
    return f"""
{emoji} ROLL ANALYSIS: {candidate.symbol}

{urgency_emoji} Urgency: {candidate.urgency.upper()}
📋 Reason: {candidate.roll_reason.value}

CURRENT POSITION:
  Strategy: {candidate.current_strategy}
  Strikes: {candidate.current_short_strike}/{candidate.current_long_strike}
  Expiration: {candidate.current_expiration} ({candidate.current_dte} DTE)
  P&L: ${candidate.current_pnl:.2f} ({candidate.current_pnl_pct:.1%})
  Distance to short: {candidate.distance_to_short:.1%}

SUGGESTED ROLL ({candidate.suggested_roll_type.value}):
  New Strikes: {candidate.suggested_new_strikes[0]}/{candidate.suggested_new_strikes[1]}
  New Expiration: {candidate.suggested_new_expiration} ({candidate.suggested_new_dte} DTE)
  Estimated Credit: ${candidate.estimated_roll_credit:.2f}
  New Distance: {candidate.new_distance_to_short:.1%}

RECOMMENDATION: {"✅ ROLL" if should else "❌ DON'T ROLL"}
Reason: {reason}
"""
