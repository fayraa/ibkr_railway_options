"""
Correlation Filter
Prevents stacking highly correlated positions

Problem:
- SPY, QQQ, IWM are ~80-95% correlated
- Opening bull put spreads on all 3 is essentially 3x the same bet
- One market drop hurts all positions simultaneously

Solution:
- Track correlation between underlyings
- Limit exposure to correlated assets
- Treat correlated positions as a single "risk unit"
"""
import logging
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class AssetClass(Enum):
    """Asset class categories"""
    BROAD_MARKET = "broad_market"      # SPY, VOO, IVV
    TECH = "tech"                       # QQQ, XLK
    SMALL_CAP = "small_cap"             # IWM, IJR
    SECTOR = "sector"                   # XLF, XLE, etc.
    BOND = "bond"                       # TLT, IEF
    COMMODITY = "commodity"             # GLD, SLV, USO
    VOLATILITY = "volatility"          # VXX, UVXY
    INDIVIDUAL = "individual"           # Single stocks


# Pre-defined correlation groups
# Assets in the same group are considered highly correlated
CORRELATION_GROUPS = {
    'US_EQUITY_BROAD': {
        'symbols': ['SPY', 'VOO', 'IVV', 'VTI', 'ITOT'],
        'correlation': 0.99,
        'asset_class': AssetClass.BROAD_MARKET,
    },
    'US_EQUITY_TECH': {
        'symbols': ['QQQ', 'XLK', 'VGT', 'FTEC'],
        'correlation': 0.95,
        'asset_class': AssetClass.TECH,
    },
    'US_EQUITY_SMALL': {
        'symbols': ['IWM', 'IJR', 'VB', 'SCHA'],
        'correlation': 0.95,
        'asset_class': AssetClass.SMALL_CAP,
    },
    'CROSS_EQUITY': {
        # Cross-group correlation (SPY-QQQ-IWM)
        'symbols': ['SPY', 'QQQ', 'IWM'],
        'correlation': 0.85,
        'asset_class': AssetClass.BROAD_MARKET,
    },
    'FINANCIALS': {
        'symbols': ['XLF', 'KRE', 'KBE', 'VFH'],
        'correlation': 0.90,
        'asset_class': AssetClass.SECTOR,
    },
    'ENERGY': {
        'symbols': ['XLE', 'OIH', 'VDE', 'XOP'],
        'correlation': 0.90,
        'asset_class': AssetClass.SECTOR,
    },
    'BONDS': {
        'symbols': ['TLT', 'IEF', 'BND', 'AGG'],
        'correlation': 0.95,
        'asset_class': AssetClass.BOND,
    },
    'GOLD': {
        'symbols': ['GLD', 'IAU', 'GDX', 'GDXJ'],
        'correlation': 0.90,
        'asset_class': AssetClass.COMMODITY,
    },
}


@dataclass
class CorrelationConfig:
    """Configuration for correlation filtering"""
    
    # Maximum positions in same correlation group
    max_positions_per_group: int = 1
    
    # Maximum positions in cross-correlated assets (e.g., SPY+QQQ+IWM)
    max_cross_equity_positions: int = 2
    
    # Correlation threshold to consider "highly correlated"
    high_correlation_threshold: float = 0.80
    
    # Whether to allow opposite directions in correlated assets
    # e.g., bull put on SPY + bear call on QQQ
    allow_opposite_directions: bool = True
    
    # Custom correlation overrides (symbol pair -> correlation)
    custom_correlations: Dict[Tuple[str, str], float] = field(default_factory=dict)


@dataclass
class PositionExposure:
    """Tracks exposure for correlation analysis"""
    symbol: str
    direction: str  # 'bullish', 'bearish', 'neutral'
    strategy: str   # 'bull_put_spread', 'bear_call_spread', 'iron_condor'
    delta_exposure: float  # Net delta
    notional_risk: float   # Max loss


class CorrelationFilter:
    """
    Filters new positions based on correlation with existing positions
    """
    
    def __init__(self, config: CorrelationConfig = None):
        self.config = config or CorrelationConfig()
        self._symbol_to_groups = self._build_symbol_map()
    
    def _build_symbol_map(self) -> Dict[str, List[str]]:
        """Map each symbol to its correlation groups"""
        symbol_map = {}
        for group_name, group_data in CORRELATION_GROUPS.items():
            for symbol in group_data['symbols']:
                if symbol not in symbol_map:
                    symbol_map[symbol] = []
                symbol_map[symbol].append(group_name)
        return symbol_map
    
    def get_correlation(self, symbol1: str, symbol2: str) -> float:
        """
        Get correlation between two symbols
        """
        if symbol1 == symbol2:
            return 1.0
        
        # Check custom overrides
        pair = tuple(sorted([symbol1, symbol2]))
        if pair in self.config.custom_correlations:
            return self.config.custom_correlations[pair]
        
        # Check if in same group
        groups1 = set(self._symbol_to_groups.get(symbol1, []))
        groups2 = set(self._symbol_to_groups.get(symbol2, []))
        
        common_groups = groups1 & groups2
        
        if common_groups:
            # Return highest correlation from common groups
            max_corr = 0
            for group in common_groups:
                max_corr = max(max_corr, CORRELATION_GROUPS[group]['correlation'])
            return max_corr
        
        # Check cross-equity correlation
        cross_equity = set(CORRELATION_GROUPS['CROSS_EQUITY']['symbols'])
        if symbol1 in cross_equity and symbol2 in cross_equity:
            return CORRELATION_GROUPS['CROSS_EQUITY']['correlation']
        
        # Default: assume low correlation for unknown pairs
        return 0.3
    
    def can_open_position(
        self,
        new_symbol: str,
        new_direction: str,
        existing_positions: List[PositionExposure]
    ) -> Tuple[bool, str]:
        """
        Check if we can open a new position given existing positions
        
        Args:
            new_symbol: Symbol for new position
            new_direction: 'bullish', 'bearish', or 'neutral'
            existing_positions: List of current positions
        
        Returns:
            (can_open, reason)
        """
        if not existing_positions:
            return True, "No existing positions"
        
        # Count positions in same groups
        new_groups = set(self._symbol_to_groups.get(new_symbol, []))
        
        group_counts = {}
        cross_equity_count = 0
        cross_equity_symbols = set(CORRELATION_GROUPS['CROSS_EQUITY']['symbols'])
        
        for pos in existing_positions:
            pos_groups = set(self._symbol_to_groups.get(pos.symbol, []))
            
            # Count by group
            for group in pos_groups:
                group_counts[group] = group_counts.get(group, 0) + 1
            
            # Count cross-equity
            if pos.symbol in cross_equity_symbols:
                cross_equity_count += 1
        
        # Check same-group limits
        for group in new_groups:
            if group in group_counts:
                if group_counts[group] >= self.config.max_positions_per_group:
                    return False, f"Max positions in {group} group reached"
        
        # Check cross-equity limit
        if new_symbol in cross_equity_symbols:
            if cross_equity_count >= self.config.max_cross_equity_positions:
                # Check if opposite direction is allowed
                if self.config.allow_opposite_directions:
                    # Check if new position is opposite to existing
                    for pos in existing_positions:
                        if pos.symbol in cross_equity_symbols:
                            if self._are_opposite_directions(new_direction, pos.direction):
                                return True, "Opposite direction allowed"
                
                return False, f"Max cross-equity positions ({self.config.max_cross_equity_positions}) reached"
        
        # Check high correlation with any existing position
        for pos in existing_positions:
            corr = self.get_correlation(new_symbol, pos.symbol)
            
            if corr >= self.config.high_correlation_threshold:
                # Same direction in highly correlated assets
                if not self._are_opposite_directions(new_direction, pos.direction):
                    if not self.config.allow_opposite_directions or new_direction == pos.direction:
                        return False, (
                            f"High correlation ({corr:.0%}) with {pos.symbol} "
                            f"in same direction"
                        )
        
        return True, "Passed correlation checks"
    
    def _are_opposite_directions(self, dir1: str, dir2: str) -> bool:
        """Check if two directions are opposite"""
        opposites = {
            ('bullish', 'bearish'),
            ('bearish', 'bullish'),
        }
        return (dir1, dir2) in opposites
    
    def get_correlated_positions(
        self,
        symbol: str,
        positions: List[PositionExposure]
    ) -> List[PositionExposure]:
        """Get all positions correlated with a symbol"""
        correlated = []
        
        for pos in positions:
            corr = self.get_correlation(symbol, pos.symbol)
            if corr >= self.config.high_correlation_threshold:
                correlated.append(pos)
        
        return correlated
    
    def calculate_effective_exposure(
        self,
        positions: List[PositionExposure]
    ) -> Dict[str, float]:
        """
        Calculate effective exposure accounting for correlation
        
        Returns exposure by correlation group
        """
        group_exposure = {}
        
        for pos in positions:
            groups = self._symbol_to_groups.get(pos.symbol, ['OTHER'])
            
            for group in groups:
                if group not in group_exposure:
                    group_exposure[group] = 0
                
                # Weight by direction
                direction_mult = {
                    'bullish': 1.0,
                    'bearish': -1.0,
                    'neutral': 0.0
                }.get(pos.direction, 0)
                
                group_exposure[group] += pos.notional_risk * direction_mult
        
        return group_exposure
    
    def get_diversification_score(
        self,
        positions: List[PositionExposure]
    ) -> float:
        """
        Calculate diversification score (0-1)
        1 = fully diversified, 0 = all in one correlated group
        """
        if not positions:
            return 1.0
        
        if len(positions) == 1:
            return 0.5
        
        # Calculate average correlation between all pairs
        total_corr = 0
        pairs = 0
        
        for i, pos1 in enumerate(positions):
            for pos2 in positions[i+1:]:
                total_corr += self.get_correlation(pos1.symbol, pos2.symbol)
                pairs += 1
        
        if pairs == 0:
            return 1.0
        
        avg_corr = total_corr / pairs
        
        # Convert to diversification score (low correlation = high diversification)
        return 1 - avg_corr


def get_direction_from_strategy(strategy: str) -> str:
    """Map strategy to direction"""
    direction_map = {
        'bull_put_spread': 'bullish',
        'bear_call_spread': 'bearish',
        'iron_condor': 'neutral',
    }
    return direction_map.get(strategy.lower(), 'neutral')


def format_correlation_matrix(symbols: List[str]) -> str:
    """Format correlation matrix for display"""
    filter = CorrelationFilter()
    
    lines = ["Correlation Matrix:"]
    header = "        " + " ".join(f"{s:>6}" for s in symbols)
    lines.append(header)
    
    for s1 in symbols:
        row = f"{s1:>6}  "
        for s2 in symbols:
            corr = filter.get_correlation(s1, s2)
            row += f"{corr:>6.0%} "
        lines.append(row)
    
    return "\n".join(lines)
