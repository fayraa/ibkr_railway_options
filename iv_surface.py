"""
IV Surface Analysis
Analyzes implied volatility across strikes and expirations

The IV surface reveals:
1. Term Structure: How IV varies with time (contango/backwardation)
2. Skew: How IV varies with strike (put skew, call skew)
3. Smile: The overall shape across strikes
4. Relative Value: Which expirations/strikes are rich or cheap

Uses for trading:
- Find rich strikes to sell
- Identify optimal expirations
- Detect unusual IV patterns
- Calendar spread opportunities
"""
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import math

logger = logging.getLogger(__name__)


@dataclass
class StrikeIV:
    """IV data for a single strike"""
    strike: float
    call_iv: Optional[float]
    put_iv: Optional[float]
    call_delta: Optional[float]
    put_delta: Optional[float]
    
    @property
    def avg_iv(self) -> float:
        """Average of call and put IV"""
        ivs = [iv for iv in [self.call_iv, self.put_iv] if iv]
        return sum(ivs) / len(ivs) if ivs else 0


@dataclass
class ExpirationIV:
    """IV data for a single expiration"""
    expiration: str
    dte: int
    atm_iv: float
    strikes: List[StrikeIV]
    
    # Skew metrics
    put_25d_iv: Optional[float] = None
    call_25d_iv: Optional[float] = None
    skew: Optional[float] = None  # put_25d - call_25d
    
    # Term structure position
    iv_percentile_vs_history: Optional[float] = None


@dataclass
class IVSurface:
    """Complete IV surface for an underlying"""
    symbol: str
    underlying_price: float
    timestamp: datetime
    
    # By expiration
    expirations: List[ExpirationIV]
    
    # Overall metrics
    front_month_iv: float = 0.0
    back_month_iv: float = 0.0
    term_structure_slope: float = 0.0  # (back - front) / front
    
    # Skew summary
    avg_skew: float = 0.0
    
    # Recommendations
    rich_expirations: List[str] = field(default_factory=list)
    cheap_expirations: List[str] = field(default_factory=list)


class IVSurfaceAnalyzer:
    """
    Analyzes IV across the option surface
    """
    
    def __init__(self):
        pass
    
    def build_surface(
        self,
        symbol: str,
        underlying_price: float,
        options_data: Dict[str, List[Dict]],  # expiration -> list of option data
    ) -> IVSurface:
        """
        Build IV surface from options data
        
        Args:
            symbol: Underlying symbol
            underlying_price: Current price
            options_data: Dict mapping expiration to list of option dicts
                Each option dict should have: strike, right, iv, delta, bid, ask
        
        Returns:
            IVSurface with complete analysis
        """
        expirations = []
        today = datetime.now().date()
        
        for exp, options in sorted(options_data.items()):
            exp_date = datetime.strptime(exp, '%Y%m%d').date()
            dte = (exp_date - today).days
            
            if dte <= 0:
                continue
            
            # Group by strike
            strikes_data = self._group_by_strike(options)
            
            # Find ATM IV
            atm_strike = self._find_atm_strike(
                list(strikes_data.keys()), 
                underlying_price
            )
            atm_iv = self._get_atm_iv(strikes_data, atm_strike)
            
            # Find 25-delta IVs for skew
            put_25d_iv = self._find_delta_iv(strikes_data, -0.25, 'P')
            call_25d_iv = self._find_delta_iv(strikes_data, 0.25, 'C')
            
            skew = None
            if put_25d_iv and call_25d_iv:
                skew = put_25d_iv - call_25d_iv
            
            # Build strike list
            strike_ivs = []
            for strike, data in sorted(strikes_data.items()):
                strike_ivs.append(StrikeIV(
                    strike=strike,
                    call_iv=data.get('call_iv'),
                    put_iv=data.get('put_iv'),
                    call_delta=data.get('call_delta'),
                    put_delta=data.get('put_delta'),
                ))
            
            expirations.append(ExpirationIV(
                expiration=exp,
                dte=dte,
                atm_iv=atm_iv,
                strikes=strike_ivs,
                put_25d_iv=put_25d_iv,
                call_25d_iv=call_25d_iv,
                skew=skew,
            ))
        
        # Calculate term structure
        front_iv = expirations[0].atm_iv if expirations else 0
        back_iv = expirations[-1].atm_iv if len(expirations) > 1 else front_iv
        
        slope = (back_iv - front_iv) / front_iv if front_iv > 0 else 0
        
        # Average skew
        skews = [e.skew for e in expirations if e.skew is not None]
        avg_skew = sum(skews) / len(skews) if skews else 0
        
        # Find rich/cheap expirations
        rich_exps, cheap_exps = self._find_relative_value(expirations)
        
        return IVSurface(
            symbol=symbol,
            underlying_price=underlying_price,
            timestamp=datetime.now(),
            expirations=expirations,
            front_month_iv=front_iv,
            back_month_iv=back_iv,
            term_structure_slope=slope,
            avg_skew=avg_skew,
            rich_expirations=rich_exps,
            cheap_expirations=cheap_exps,
        )
    
    def _group_by_strike(
        self, 
        options: List[Dict]
    ) -> Dict[float, Dict]:
        """Group options by strike"""
        strikes = {}
        
        for opt in options:
            strike = opt.get('strike')
            if not strike:
                continue
            
            if strike not in strikes:
                strikes[strike] = {}
            
            right = opt.get('right', 'C')
            iv = opt.get('iv') or opt.get('implied_vol')
            delta = opt.get('delta')
            
            if right == 'C':
                strikes[strike]['call_iv'] = iv
                strikes[strike]['call_delta'] = delta
            else:
                strikes[strike]['put_iv'] = iv
                strikes[strike]['put_delta'] = delta
        
        return strikes
    
    def _find_atm_strike(
        self, 
        strikes: List[float], 
        price: float
    ) -> float:
        """Find ATM strike nearest to price"""
        if not strikes:
            return price
        return min(strikes, key=lambda s: abs(s - price))
    
    def _get_atm_iv(
        self, 
        strikes_data: Dict, 
        atm_strike: float
    ) -> float:
        """Get ATM IV (average of call and put)"""
        if atm_strike not in strikes_data:
            return 0
        
        data = strikes_data[atm_strike]
        ivs = []
        
        if data.get('call_iv'):
            ivs.append(data['call_iv'])
        if data.get('put_iv'):
            ivs.append(data['put_iv'])
        
        return sum(ivs) / len(ivs) if ivs else 0
    
    def _find_delta_iv(
        self,
        strikes_data: Dict,
        target_delta: float,
        right: str
    ) -> Optional[float]:
        """Find IV at target delta"""
        delta_key = 'call_delta' if right == 'C' else 'put_delta'
        iv_key = 'call_iv' if right == 'C' else 'put_iv'
        
        best_strike = None
        best_diff = float('inf')
        
        for strike, data in strikes_data.items():
            delta = data.get(delta_key)
            if delta is None:
                continue
            
            diff = abs(delta - target_delta)
            if diff < best_diff:
                best_diff = diff
                best_strike = strike
        
        if best_strike and best_strike in strikes_data:
            return strikes_data[best_strike].get(iv_key)
        
        return None
    
    def _find_relative_value(
        self,
        expirations: List[ExpirationIV]
    ) -> Tuple[List[str], List[str]]:
        """
        Find relatively rich and cheap expirations
        
        Uses IV vs sqrt(DTE) relationship:
        - If IV is higher than expected for DTE, it's rich
        - If IV is lower than expected for DTE, it's cheap
        """
        if len(expirations) < 2:
            return [], []
        
        rich = []
        cheap = []
        
        # Calculate expected IV based on term structure
        # Simple model: IV should scale roughly with sqrt(DTE) from front month
        front = expirations[0]
        base_iv = front.atm_iv
        base_dte = front.dte
        
        for exp in expirations[1:]:
            # Expected IV if term structure were flat in variance terms
            expected_iv = base_iv * math.sqrt(exp.dte / base_dte)
            
            # Compare to actual
            ratio = exp.atm_iv / expected_iv if expected_iv > 0 else 1
            
            if ratio > 1.05:  # 5%+ above expected
                rich.append(exp.expiration)
            elif ratio < 0.95:  # 5%+ below expected
                cheap.append(exp.expiration)
        
        return rich, cheap
    
    def find_best_expiration_for_selling(
        self,
        surface: IVSurface,
        min_dte: int = 25,
        max_dte: int = 50
    ) -> Optional[ExpirationIV]:
        """
        Find best expiration for selling premium
        
        Criteria:
        - Within DTE range
        - Highest IV relative to term structure
        - Good skew for put selling
        """
        candidates = [
            exp for exp in surface.expirations
            if min_dte <= exp.dte <= max_dte
        ]
        
        if not candidates:
            return None
        
        # Score each expiration
        scored = []
        for exp in candidates:
            score = 0
            
            # Higher IV = better
            score += exp.atm_iv * 100  # Weight IV heavily
            
            # Rich vs term structure = better
            if exp.expiration in surface.rich_expirations:
                score += 5
            elif exp.expiration in surface.cheap_expirations:
                score -= 5
            
            # Higher put skew = better for selling puts
            if exp.skew:
                score += exp.skew * 10
            
            scored.append((exp, score))
        
        # Return highest scored
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[0][0] if scored else None
    
    def find_calendar_spread_opportunities(
        self,
        surface: IVSurface,
        min_iv_diff_pct: float = 0.10
    ) -> List[Dict]:
        """
        Find calendar spread opportunities where term structure is inverted
        
        A calendar spread profits when:
        - Near-term IV is higher than later-term (sell near, buy far)
        - Or vice versa for the opposite trade
        """
        opportunities = []
        
        for i, near in enumerate(surface.expirations[:-1]):
            for far in surface.expirations[i+1:]:
                if far.dte - near.dte < 14:  # Need at least 2 weeks difference
                    continue
                
                iv_diff = near.atm_iv - far.atm_iv
                iv_diff_pct = iv_diff / far.atm_iv if far.atm_iv > 0 else 0
                
                if abs(iv_diff_pct) >= min_iv_diff_pct:
                    opportunities.append({
                        'near_exp': near.expiration,
                        'near_dte': near.dte,
                        'near_iv': near.atm_iv,
                        'far_exp': far.expiration,
                        'far_dte': far.dte,
                        'far_iv': far.atm_iv,
                        'iv_diff': iv_diff,
                        'iv_diff_pct': iv_diff_pct,
                        'trade': 'sell_near_buy_far' if iv_diff > 0 else 'buy_near_sell_far',
                    })
        
        return sorted(opportunities, key=lambda x: abs(x['iv_diff_pct']), reverse=True)


def format_iv_surface(surface: IVSurface) -> str:
    """Format IV surface for display"""
    
    term_emoji = "📈" if surface.term_structure_slope > 0.05 else "📉" if surface.term_structure_slope < -0.02 else "➡️"
    
    lines = [
        f"{'='*60}",
        f"IV SURFACE: {surface.symbol}",
        f"{'='*60}",
        f"Underlying: ${surface.underlying_price:.2f}",
        f"",
        f"{term_emoji} Term Structure: {surface.term_structure_slope:+.1%}",
        f"   Front IV: {surface.front_month_iv:.1%}",
        f"   Back IV: {surface.back_month_iv:.1%}",
        f"",
        f"Average Skew: {surface.avg_skew:+.1f} pts",
        f"",
        f"{'Expiration':<12} {'DTE':>5} {'ATM IV':>8} {'Skew':>8} {'Status':>10}",
        f"{'-'*50}",
    ]
    
    for exp in surface.expirations:
        status = ""
        if exp.expiration in surface.rich_expirations:
            status = "🟢 RICH"
        elif exp.expiration in surface.cheap_expirations:
            status = "🔴 CHEAP"
        
        skew_str = f"{exp.skew:+.1f}" if exp.skew else "N/A"
        
        lines.append(
            f"{exp.expiration:<12} {exp.dte:>5} {exp.atm_iv:>7.1%} "
            f"{skew_str:>8} {status:>10}"
        )
    
    if surface.rich_expirations:
        lines.extend([
            f"",
            f"💡 Rich expirations (good for selling): {', '.join(surface.rich_expirations)}",
        ])
    
    lines.append(f"{'='*60}")
    
    return "\n".join(lines)


def format_skew_chart(exp: ExpirationIV, price: float) -> str:
    """Format skew visualization for a single expiration"""
    
    lines = [
        f"SKEW CHART: {exp.expiration} ({exp.dte} DTE)",
        f"ATM: ${price:.0f} | IV: {exp.atm_iv:.1%}",
        "",
    ]
    
    # Create simple ASCII skew chart
    for strike_iv in exp.strikes:
        distance = strike_iv.strike - price
        distance_pct = distance / price * 100
        
        # Only show ±10% from ATM
        if abs(distance_pct) > 10:
            continue
        
        iv = strike_iv.avg_iv
        if not iv:
            continue
        
        # Normalize IV to bar length (20-40% IV -> 0-20 chars)
        bar_len = int((iv - 0.10) * 100)
        bar_len = max(0, min(30, bar_len))
        
        bar = "█" * bar_len
        marker = " *" if abs(distance_pct) < 1 else ""
        
        lines.append(
            f"{strike_iv.strike:>6.0f} ({distance_pct:+5.1f}%) | {bar} {iv:.1%}{marker}"
        )
    
    return "\n".join(lines)
