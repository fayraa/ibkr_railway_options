"""
Portfolio Greeks Manager
Tracks and manages aggregate Greek exposure across all positions

Why it matters:
- Delta: Directional exposure to market moves
- Theta: Daily time decay (income for sellers)
- Vega: Exposure to volatility changes
- Gamma: Rate of delta change (acceleration risk)

For credit spread sellers:
- Want: Positive theta (collecting time decay)
- Monitor: Net delta (don't get too directional)
- Watch: Vega (positions hurt by IV expansion)
- Careful: Gamma near expiration
"""
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


@dataclass
class PositionGreeks:
    """Greeks for a single position"""
    position_id: str
    symbol: str
    strategy: str
    quantity: int
    
    # Individual Greeks (per contract)
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    
    # Position Greeks (quantity * per contract * 100)
    position_delta: float = 0.0
    position_gamma: float = 0.0
    position_theta: float = 0.0
    position_vega: float = 0.0
    
    # Additional metrics
    delta_dollars: float = 0.0  # Delta * underlying price * 100 * quantity
    theta_dollars: float = 0.0  # Daily theta in dollars
    
    # Metadata
    underlying_price: float = 0.0
    days_to_expiration: int = 0
    last_updated: datetime = None
    
    def __post_init__(self):
        if self.last_updated is None:
            self.last_updated = datetime.now()


@dataclass
class PortfolioGreeksSummary:
    """Aggregate Greeks across all positions"""
    # Net Greeks
    net_delta: float = 0.0
    net_gamma: float = 0.0
    net_theta: float = 0.0
    net_vega: float = 0.0
    
    # Dollar exposure
    delta_dollars: float = 0.0  # Equivalent stock exposure
    theta_dollars: float = 0.0  # Daily income/decay
    vega_dollars: float = 0.0   # P&L per 1% IV change
    
    # Beta-weighted delta (vs SPY)
    beta_weighted_delta: float = 0.0
    
    # By underlying
    delta_by_symbol: Dict[str, float] = field(default_factory=dict)
    theta_by_symbol: Dict[str, float] = field(default_factory=dict)
    
    # Risk metrics
    max_delta_risk: float = 0.0  # Worst case delta if all positions move against
    gamma_risk_1pct: float = 0.0  # Delta change for 1% underlying move
    
    # Position count
    total_positions: int = 0
    
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass
class GreeksLimits:
    """Risk limits for portfolio Greeks"""
    # Delta limits
    max_net_delta: float = 100.0      # Max net delta exposure
    max_delta_per_symbol: float = 50.0  # Max delta per underlying
    max_delta_dollars: float = 50000.0  # Max dollar delta exposure
    
    # Theta limits (usually positive for sellers)
    min_net_theta: float = 0.0        # Should be positive (collecting)
    
    # Vega limits
    max_net_vega: float = 500.0       # Exposure to vol changes
    
    # Gamma limits (especially near expiration)
    max_net_gamma: float = 50.0       # Acceleration risk
    
    # Warnings (softer limits)
    warn_delta_pct: float = 0.75      # Warn at 75% of limit


class PortfolioGreeksManager:
    """
    Manages and monitors portfolio-level Greeks
    """
    
    def __init__(self, limits: GreeksLimits = None):
        self.limits = limits or GreeksLimits()
        self.positions: Dict[str, PositionGreeks] = {}
        self._last_summary: Optional[PortfolioGreeksSummary] = None
    
    def update_position(
        self,
        position_id: str,
        symbol: str,
        strategy: str,
        quantity: int,
        short_delta: float,
        long_delta: float,
        short_gamma: float,
        long_gamma: float,
        short_theta: float,
        long_theta: float,
        short_vega: float,
        long_vega: float,
        underlying_price: float,
        dte: int
    ):
        """
        Update Greeks for a position (credit spread)
        
        For credit spreads:
        - Short leg: we sold, so delta/gamma/vega have opposite sign
        - Long leg: we bought, so delta/gamma/vega are as reported
        - Net = -short + long (we're short the spread)
        """
        # Calculate net Greeks per spread
        # For a credit spread we SOLD:
        # - We sold the short leg (negative position)
        # - We bought the long leg (positive position, but protective)
        
        net_delta = -short_delta + long_delta
        net_gamma = -short_gamma + long_gamma
        net_theta = -short_theta + long_theta  # Usually positive (good for sellers)
        net_vega = -short_vega + long_vega     # Usually negative (IV drop helps)
        
        # Scale by quantity and contract multiplier (100 shares per contract)
        multiplier = quantity * 100
        
        position_greeks = PositionGreeks(
            position_id=position_id,
            symbol=symbol,
            strategy=strategy,
            quantity=quantity,
            delta=net_delta,
            gamma=net_gamma,
            theta=net_theta,
            vega=net_vega,
            position_delta=net_delta * multiplier,
            position_gamma=net_gamma * multiplier,
            position_theta=net_theta * multiplier,
            position_vega=net_vega * multiplier,
            delta_dollars=net_delta * underlying_price * multiplier,
            theta_dollars=net_theta * multiplier,  # Already in dollars
            underlying_price=underlying_price,
            days_to_expiration=dte,
            last_updated=datetime.now()
        )
        
        self.positions[position_id] = position_greeks
        logger.debug(f"Updated Greeks for {position_id}: Δ={net_delta:.3f}, θ=${net_theta:.2f}")
    
    def update_iron_condor(
        self,
        position_id: str,
        symbol: str,
        quantity: int,
        put_short_greeks: Dict,
        put_long_greeks: Dict,
        call_short_greeks: Dict,
        call_long_greeks: Dict,
        underlying_price: float,
        dte: int
    ):
        """Update Greeks for an iron condor (4 legs)"""
        # Iron condor = short put spread + short call spread
        # Net delta should be close to 0 (neutral)
        
        net_delta = (
            -put_short_greeks.get('delta', 0) + put_long_greeks.get('delta', 0)
            - call_short_greeks.get('delta', 0) + call_long_greeks.get('delta', 0)
        )
        
        net_gamma = (
            -put_short_greeks.get('gamma', 0) + put_long_greeks.get('gamma', 0)
            - call_short_greeks.get('gamma', 0) + call_long_greeks.get('gamma', 0)
        )
        
        net_theta = (
            -put_short_greeks.get('theta', 0) + put_long_greeks.get('theta', 0)
            - call_short_greeks.get('theta', 0) + call_long_greeks.get('theta', 0)
        )
        
        net_vega = (
            -put_short_greeks.get('vega', 0) + put_long_greeks.get('vega', 0)
            - call_short_greeks.get('vega', 0) + call_long_greeks.get('vega', 0)
        )
        
        multiplier = quantity * 100
        
        position_greeks = PositionGreeks(
            position_id=position_id,
            symbol=symbol,
            strategy='iron_condor',
            quantity=quantity,
            delta=net_delta,
            gamma=net_gamma,
            theta=net_theta,
            vega=net_vega,
            position_delta=net_delta * multiplier,
            position_gamma=net_gamma * multiplier,
            position_theta=net_theta * multiplier,
            position_vega=net_vega * multiplier,
            delta_dollars=net_delta * underlying_price * multiplier,
            theta_dollars=net_theta * multiplier,
            underlying_price=underlying_price,
            days_to_expiration=dte,
            last_updated=datetime.now()
        )
        
        self.positions[position_id] = position_greeks
    
    def remove_position(self, position_id: str):
        """Remove a closed position"""
        if position_id in self.positions:
            del self.positions[position_id]
    
    def get_summary(self) -> PortfolioGreeksSummary:
        """Calculate portfolio-level Greeks summary"""
        summary = PortfolioGreeksSummary()
        
        for pos in self.positions.values():
            summary.net_delta += pos.position_delta
            summary.net_gamma += pos.position_gamma
            summary.net_theta += pos.position_theta
            summary.net_vega += pos.position_vega
            
            summary.delta_dollars += pos.delta_dollars
            summary.theta_dollars += pos.theta_dollars
            
            # By symbol
            symbol = pos.symbol
            summary.delta_by_symbol[symbol] = (
                summary.delta_by_symbol.get(symbol, 0) + pos.position_delta
            )
            summary.theta_by_symbol[symbol] = (
                summary.theta_by_symbol.get(symbol, 0) + pos.theta_dollars
            )
        
        summary.total_positions = len(self.positions)
        
        # Calculate risk metrics
        summary.gamma_risk_1pct = summary.net_gamma * 0.01  # Delta change for 1% move
        
        # Max delta risk (if all positions went max delta)
        for pos in self.positions.values():
            if pos.strategy in ['bull_put_spread', 'bear_call_spread']:
                # Max delta for a spread is bounded by strikes
                summary.max_delta_risk += abs(pos.quantity * 100)  # Simplified
        
        self._last_summary = summary
        return summary
    
    def check_limits(self) -> List[Tuple[str, str, float, float]]:
        """
        Check if any Greek limits are breached
        
        Returns:
            List of (metric, status, current, limit) tuples
        """
        summary = self.get_summary()
        breaches = []
        
        # Delta checks
        if abs(summary.net_delta) > self.limits.max_net_delta:
            breaches.append((
                'Net Delta',
                'BREACH',
                summary.net_delta,
                self.limits.max_net_delta
            ))
        elif abs(summary.net_delta) > self.limits.max_net_delta * self.limits.warn_delta_pct:
            breaches.append((
                'Net Delta',
                'WARNING',
                summary.net_delta,
                self.limits.max_net_delta
            ))
        
        # Per-symbol delta
        for symbol, delta in summary.delta_by_symbol.items():
            if abs(delta) > self.limits.max_delta_per_symbol:
                breaches.append((
                    f'{symbol} Delta',
                    'BREACH',
                    delta,
                    self.limits.max_delta_per_symbol
                ))
        
        # Delta dollars
        if abs(summary.delta_dollars) > self.limits.max_delta_dollars:
            breaches.append((
                'Delta $',
                'BREACH',
                summary.delta_dollars,
                self.limits.max_delta_dollars
            ))
        
        # Theta (should be positive for sellers)
        if summary.net_theta < self.limits.min_net_theta:
            breaches.append((
                'Net Theta',
                'WARNING',
                summary.net_theta,
                self.limits.min_net_theta
            ))
        
        # Vega
        if abs(summary.net_vega) > self.limits.max_net_vega:
            breaches.append((
                'Net Vega',
                'WARNING',
                summary.net_vega,
                self.limits.max_net_vega
            ))
        
        # Gamma
        if abs(summary.net_gamma) > self.limits.max_net_gamma:
            breaches.append((
                'Net Gamma',
                'WARNING',
                summary.net_gamma,
                self.limits.max_net_gamma
            ))
        
        return breaches
    
    def can_add_position(
        self,
        new_delta: float,
        new_symbol: str
    ) -> Tuple[bool, str]:
        """
        Check if adding a position would breach limits
        """
        summary = self.get_summary()
        
        # Check net delta
        projected_delta = summary.net_delta + new_delta
        if abs(projected_delta) > self.limits.max_net_delta:
            return False, f"Would breach net delta limit ({projected_delta:.1f} > {self.limits.max_net_delta})"
        
        # Check symbol delta
        current_symbol_delta = summary.delta_by_symbol.get(new_symbol, 0)
        projected_symbol_delta = current_symbol_delta + new_delta
        if abs(projected_symbol_delta) > self.limits.max_delta_per_symbol:
            return False, f"Would breach {new_symbol} delta limit"
        
        return True, "Within limits"
    
    def get_rebalancing_suggestions(self) -> List[str]:
        """
        Suggest trades to rebalance Greeks
        """
        summary = self.get_summary()
        suggestions = []
        
        # Too much positive delta (bullish)
        if summary.net_delta > self.limits.max_net_delta * 0.8:
            suggestions.append(
                f"Consider bear call spread to reduce delta "
                f"(current: {summary.net_delta:.1f})"
            )
        
        # Too much negative delta (bearish)
        elif summary.net_delta < -self.limits.max_net_delta * 0.8:
            suggestions.append(
                f"Consider bull put spread to increase delta "
                f"(current: {summary.net_delta:.1f})"
            )
        
        # Theta too low
        if summary.theta_dollars < 10 and summary.total_positions > 0:
            suggestions.append(
                f"Theta income low (${summary.theta_dollars:.2f}/day). "
                f"Consider higher-premium trades."
            )
        
        return suggestions


def format_greeks_report(summary: PortfolioGreeksSummary) -> str:
    """Format Greeks summary for display"""
    
    delta_emoji = "📈" if summary.net_delta > 0 else "📉" if summary.net_delta < 0 else "➡️"
    theta_emoji = "💰" if summary.theta_dollars > 0 else "💸"
    
    lines = [
        "═" * 50,
        "📊 PORTFOLIO GREEKS SUMMARY",
        "═" * 50,
        "",
        f"{delta_emoji} Net Delta: {summary.net_delta:+.1f}",
        f"   (${summary.delta_dollars:+,.0f} equivalent exposure)",
        "",
        f"⚡ Net Gamma: {summary.net_gamma:+.2f}",
        f"   (Δ changes {summary.gamma_risk_1pct:+.2f} per 1% move)",
        "",
        f"{theta_emoji} Net Theta: ${summary.theta_dollars:+.2f}/day",
        "",
        f"📊 Net Vega: {summary.net_vega:+.1f}",
        f"   (P&L per 1% IV change)",
        "",
        "─" * 50,
        "BY SYMBOL:",
    ]
    
    for symbol in sorted(summary.delta_by_symbol.keys()):
        delta = summary.delta_by_symbol[symbol]
        theta = summary.theta_by_symbol.get(symbol, 0)
        lines.append(f"  {symbol}: Δ={delta:+.1f}, θ=${theta:+.2f}/day")
    
    lines.extend([
        "",
        f"Total Positions: {summary.total_positions}",
        f"Updated: {summary.timestamp.strftime('%H:%M:%S')}",
        "═" * 50,
    ])
    
    return "\n".join(lines)
