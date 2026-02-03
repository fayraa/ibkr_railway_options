"""
Options Market Analyzer
Analyzes options-specific metrics for premium selling decisions:
- IV Rank / IV Percentile
- VIX Term Structure
- Expected vs Realized Move
- Put/Call Skew
- Unusual Volume/OI
- Earnings Calendar
"""
import logging
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class VolatilityRegime(Enum):
    """Volatility environment classification"""
    RICH = "rich"           # IV high relative to history - SELL premium
    FAIR = "fair"           # IV normal - selective selling
    CHEAP = "cheap"         # IV low - avoid selling or BUY premium
    EXTREME = "extreme"     # Crisis levels - no trade


class TermStructure(Enum):
    """VIX term structure state"""
    CONTANGO = "contango"       # Normal - front < back, complacency
    FLAT = "flat"               # Transitional
    BACKWARDATION = "backwardation"  # Fear - front > back


class SkewRegime(Enum):
    """Put/Call skew classification"""
    PUT_RICH = "put_rich"       # Puts expensive - sell puts
    NEUTRAL = "neutral"         # Balanced
    CALL_RICH = "call_rich"     # Calls expensive - sell calls (rare)


@dataclass
class OptionsAnalysis:
    """Complete options market analysis"""
    symbol: str
    timestamp: datetime
    
    # Volatility metrics
    current_iv: float              # Current implied volatility
    iv_rank: float                 # 0-100, where current IV sits in 52-week range
    iv_percentile: float           # % of days IV was lower
    hv_20: float                   # 20-day historical volatility
    iv_hv_ratio: float             # IV/HV - >1 means IV is rich
    
    # Term structure
    vix: float
    vix3m: float                   # 3-month VIX
    term_structure: TermStructure
    term_slope: float              # (VIX3M - VIX) / VIX
    
    # Expected move
    expected_move_pct: float       # Implied expected move for DTE
    realized_move_20d: float       # Actual 20-day realized move
    move_ratio: float              # Expected / Realized
    
    # Skew
    put_iv: float                  # 25-delta put IV
    call_iv: float                 # 25-delta call IV
    skew: float                    # Put IV - Call IV
    skew_regime: SkewRegime
    
    # Flow
    put_call_ratio: float          # Volume-based
    oi_put_call_ratio: float       # Open interest based
    volume_vs_avg: float           # Today's volume / 20-day avg
    unusual_activity: bool
    
    # Earnings
    days_to_earnings: Optional[int]
    earnings_within_dte: bool
    
    # Overall regime
    vol_regime: VolatilityRegime
    confidence: float
    
    # Trade recommendation
    recommendation: str            # 'sell_premium', 'buy_premium', 'no_trade'
    recommended_strategy: str      # Specific strategy suggestion
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'timestamp': self.timestamp.isoformat(),
            'iv_rank': self.iv_rank,
            'iv_percentile': self.iv_percentile,
            'iv_hv_ratio': self.iv_hv_ratio,
            'term_structure': self.term_structure.value,
            'term_slope': self.term_slope,
            'skew_regime': self.skew_regime.value,
            'vol_regime': self.vol_regime.value,
            'recommendation': self.recommendation,
            'confidence': self.confidence
        }


@dataclass
class FlowSignal:
    """Unusual options flow signal"""
    symbol: str
    timestamp: datetime
    strike: float
    expiration: str
    right: str  # 'C' or 'P'
    volume: int
    open_interest: int
    vol_oi_ratio: float
    is_sweep: bool
    sentiment: str  # 'bullish', 'bearish', 'neutral'
    size_category: str  # 'small', 'medium', 'large', 'block'


class OptionsMarketAnalyzer:
    """
    Analyzes options market conditions for premium selling
    """
    
    def __init__(self, config: Dict = None):
        self.config = config or self._default_config()
    
    def _default_config(self) -> Dict:
        return {
            # IV Rank thresholds
            'iv_rank_high': 50,      # Above this = rich premium
            'iv_rank_low': 30,       # Below this = cheap premium
            'iv_rank_extreme': 80,   # Above this = potential crisis
            
            # IV/HV ratio
            'iv_hv_rich': 1.2,       # IV 20%+ above HV = rich
            'iv_hv_cheap': 0.9,      # IV below HV = cheap
            
            # Term structure
            'contango_threshold': 0.05,    # VIX3M 5%+ above VIX
            'backwardation_threshold': -0.02,  # VIX above VIX3M
            
            # Expected move
            'move_ratio_rich': 1.3,  # Expected 30%+ above realized
            
            # Skew
            'skew_rich_threshold': 3.0,  # Put IV 3+ points above call IV
            
            # Flow
            'unusual_volume_mult': 2.0,  # 2x average = unusual
            'vol_oi_unusual': 0.5,       # Volume > 50% of OI = unusual
            
            # Earnings
            'earnings_buffer_days': 7,   # Avoid if earnings within X days
        }
    
    def analyze(
        self,
        symbol: str,
        current_iv: float,
        iv_history: List[float],      # 252 days of IV
        price_history: List[Dict],    # OHLCV data
        vix: float,
        vix3m: float,
        options_chain_data: Dict,     # Pricing/greeks for skew
        volume_data: Dict,            # Volume and OI
        earnings_date: Optional[datetime] = None,
        target_dte: int = 35
    ) -> OptionsAnalysis:
        """
        Full options market analysis
        """
        now = datetime.now()
        
        # Calculate IV Rank and Percentile
        iv_rank, iv_percentile = self._calculate_iv_rank(current_iv, iv_history)
        
        # Calculate Historical Volatility
        hv_20 = self._calculate_hv(price_history, window=20)
        iv_hv_ratio = current_iv / hv_20 if hv_20 > 0 else 1.0
        
        # Term Structure
        term_structure, term_slope = self._analyze_term_structure(vix, vix3m)
        
        # Expected vs Realized Move
        expected_move = self._calculate_expected_move(current_iv, target_dte)
        realized_move = self._calculate_realized_move(price_history, 20)
        move_ratio = expected_move / realized_move if realized_move > 0 else 1.0
        
        # Skew Analysis
        put_iv, call_iv, skew, skew_regime = self._analyze_skew(options_chain_data)
        
        # Flow Analysis
        pcr, oi_pcr, vol_vs_avg, unusual = self._analyze_flow(volume_data)
        
        # Earnings Check
        days_to_earnings = None
        earnings_within_dte = False
        if earnings_date:
            days_to_earnings = (earnings_date - now.date()).days if isinstance(earnings_date, datetime) else (earnings_date - now.date()).days
            earnings_within_dte = 0 < days_to_earnings <= target_dte
        
        # Determine Volatility Regime
        vol_regime = self._determine_vol_regime(
            iv_rank, iv_hv_ratio, vix, term_structure
        )
        
        # Generate Recommendation
        recommendation, strategy, confidence = self._generate_recommendation(
            vol_regime=vol_regime,
            iv_rank=iv_rank,
            iv_hv_ratio=iv_hv_ratio,
            term_structure=term_structure,
            skew_regime=skew_regime,
            earnings_within_dte=earnings_within_dte,
            move_ratio=move_ratio
        )
        
        return OptionsAnalysis(
            symbol=symbol,
            timestamp=now,
            current_iv=current_iv,
            iv_rank=iv_rank,
            iv_percentile=iv_percentile,
            hv_20=hv_20,
            iv_hv_ratio=iv_hv_ratio,
            vix=vix,
            vix3m=vix3m,
            term_structure=term_structure,
            term_slope=term_slope,
            expected_move_pct=expected_move,
            realized_move_20d=realized_move,
            move_ratio=move_ratio,
            put_iv=put_iv,
            call_iv=call_iv,
            skew=skew,
            skew_regime=skew_regime,
            put_call_ratio=pcr,
            oi_put_call_ratio=oi_pcr,
            volume_vs_avg=vol_vs_avg,
            unusual_activity=unusual,
            days_to_earnings=days_to_earnings,
            earnings_within_dte=earnings_within_dte,
            vol_regime=vol_regime,
            confidence=confidence,
            recommendation=recommendation,
            recommended_strategy=strategy
        )
    
    def _calculate_iv_rank(
        self, 
        current_iv: float, 
        iv_history: List[float]
    ) -> Tuple[float, float]:
        """
        Calculate IV Rank and IV Percentile
        
        IV Rank = (Current - 52wk Low) / (52wk High - 52wk Low) * 100
        IV Percentile = % of days where IV was lower than current
        """
        if not iv_history or len(iv_history) < 20:
            return 50.0, 50.0
        
        iv_min = min(iv_history)
        iv_max = max(iv_history)
        
        # IV Rank
        if iv_max - iv_min > 0:
            iv_rank = ((current_iv - iv_min) / (iv_max - iv_min)) * 100
        else:
            iv_rank = 50.0
        
        # IV Percentile
        days_lower = sum(1 for iv in iv_history if iv < current_iv)
        iv_percentile = (days_lower / len(iv_history)) * 100
        
        return min(max(iv_rank, 0), 100), min(max(iv_percentile, 0), 100)
    
    def _calculate_hv(
        self, 
        price_history: List[Dict], 
        window: int = 20
    ) -> float:
        """Calculate historical volatility (annualized)"""
        if len(price_history) < window + 1:
            return 0.20  # Default 20%
        
        closes = [bar['close'] for bar in price_history[-window-1:]]
        returns = np.diff(np.log(closes))
        
        hv = np.std(returns) * np.sqrt(252)  # Annualize
        return hv
    
    def _analyze_term_structure(
        self, 
        vix: float, 
        vix3m: float
    ) -> Tuple[TermStructure, float]:
        """
        Analyze VIX term structure
        
        Contango (normal): VIX3M > VIX - market calm
        Backwardation: VIX > VIX3M - fear, near-term uncertainty
        """
        if vix <= 0:
            return TermStructure.FLAT, 0.0
        
        slope = (vix3m - vix) / vix
        
        if slope > self.config['contango_threshold']:
            return TermStructure.CONTANGO, slope
        elif slope < self.config['backwardation_threshold']:
            return TermStructure.BACKWARDATION, slope
        else:
            return TermStructure.FLAT, slope
    
    def _calculate_expected_move(
        self, 
        iv: float, 
        dte: int
    ) -> float:
        """
        Calculate expected move as percentage
        Expected Move ≈ IV * sqrt(DTE/365)
        """
        return iv * np.sqrt(dte / 365)
    
    def _calculate_realized_move(
        self, 
        price_history: List[Dict],
        days: int = 20
    ) -> float:
        """Calculate actual realized move over period"""
        if len(price_history) < days:
            return 0.10
        
        recent = price_history[-days:]
        highs = [bar['high'] for bar in recent]
        lows = [bar['low'] for bar in recent]
        
        # Average true range as percentage
        closes = [bar['close'] for bar in recent]
        avg_close = np.mean(closes)
        
        # Calculate range
        price_range = max(highs) - min(lows)
        return price_range / avg_close if avg_close > 0 else 0.10
    
    def _analyze_skew(
        self, 
        options_chain_data: Dict
    ) -> Tuple[float, float, float, SkewRegime]:
        """
        Analyze put/call skew
        
        Put skew = demand for downside protection
        Typically puts trade at higher IV than equidistant calls
        """
        put_iv = options_chain_data.get('put_25d_iv', 20.0)
        call_iv = options_chain_data.get('call_25d_iv', 18.0)
        
        skew = put_iv - call_iv
        
        if skew > self.config['skew_rich_threshold']:
            regime = SkewRegime.PUT_RICH
        elif skew < -self.config['skew_rich_threshold']:
            regime = SkewRegime.CALL_RICH
        else:
            regime = SkewRegime.NEUTRAL
        
        return put_iv, call_iv, skew, regime
    
    def _analyze_flow(
        self, 
        volume_data: Dict
    ) -> Tuple[float, float, float, bool]:
        """
        Analyze options flow
        
        Returns:
            put_call_ratio: Volume-based P/C ratio
            oi_put_call_ratio: Open interest P/C ratio
            volume_vs_avg: Today's volume vs 20-day average
            unusual_activity: Boolean flag
        """
        put_volume = volume_data.get('put_volume', 100000)
        call_volume = volume_data.get('call_volume', 100000)
        put_oi = volume_data.get('put_oi', 500000)
        call_oi = volume_data.get('call_oi', 500000)
        avg_volume = volume_data.get('avg_daily_volume', 200000)
        
        pcr = put_volume / call_volume if call_volume > 0 else 1.0
        oi_pcr = put_oi / call_oi if call_oi > 0 else 1.0
        
        total_volume = put_volume + call_volume
        vol_vs_avg = total_volume / avg_volume if avg_volume > 0 else 1.0
        
        unusual = vol_vs_avg > self.config['unusual_volume_mult']
        
        return pcr, oi_pcr, vol_vs_avg, unusual
    
    def _determine_vol_regime(
        self,
        iv_rank: float,
        iv_hv_ratio: float,
        vix: float,
        term_structure: TermStructure
    ) -> VolatilityRegime:
        """
        Determine overall volatility regime for premium selling
        """
        # Extreme conditions - crisis
        if vix > 35 or iv_rank > self.config['iv_rank_extreme']:
            return VolatilityRegime.EXTREME
        
        # Rich premium environment
        rich_signals = 0
        if iv_rank > self.config['iv_rank_high']:
            rich_signals += 1
        if iv_hv_ratio > self.config['iv_hv_rich']:
            rich_signals += 1
        if term_structure == TermStructure.BACKWARDATION:
            rich_signals += 1  # Fear = rich puts
        
        if rich_signals >= 2:
            return VolatilityRegime.RICH
        
        # Cheap premium - avoid selling
        if iv_rank < self.config['iv_rank_low'] and iv_hv_ratio < self.config['iv_hv_cheap']:
            return VolatilityRegime.CHEAP
        
        return VolatilityRegime.FAIR
    
    def _generate_recommendation(
        self,
        vol_regime: VolatilityRegime,
        iv_rank: float,
        iv_hv_ratio: float,
        term_structure: TermStructure,
        skew_regime: SkewRegime,
        earnings_within_dte: bool,
        move_ratio: float
    ) -> Tuple[str, str, float]:
        """
        Generate trading recommendation based on all factors
        
        Returns:
            recommendation: 'sell_premium', 'buy_premium', 'no_trade'
            strategy: Specific strategy
            confidence: 0-1 confidence score
        """
        # No trade conditions
        if vol_regime == VolatilityRegime.EXTREME:
            return 'no_trade', 'none', 0.9
        
        if earnings_within_dte:
            return 'no_trade', 'none', 0.8
        
        # Cheap premium - consider buying or skip
        if vol_regime == VolatilityRegime.CHEAP:
            return 'no_trade', 'wait_for_iv_expansion', 0.7
        
        # Rich premium - SELL
        if vol_regime == VolatilityRegime.RICH:
            confidence = 0.6
            
            # Adjust confidence based on supporting factors
            if move_ratio > self.config['move_ratio_rich']:
                confidence += 0.1  # Expected > realized = edge
            
            if term_structure == TermStructure.CONTANGO:
                confidence += 0.05  # Normal market
            
            # Strategy selection based on skew
            if skew_regime == SkewRegime.PUT_RICH:
                # Puts are expensive - focus on selling puts
                strategy = 'bull_put_spread'
                confidence += 0.05
            elif skew_regime == SkewRegime.CALL_RICH:
                # Rare but possible - sell calls
                strategy = 'bear_call_spread'
            else:
                # Balanced - iron condor
                strategy = 'iron_condor'
            
            return 'sell_premium', strategy, min(confidence, 0.95)
        
        # Fair regime - selective selling
        if vol_regime == VolatilityRegime.FAIR:
            # Only trade if we have edge (IV > HV)
            if iv_hv_ratio > 1.0 and iv_rank > 40:
                if skew_regime == SkewRegime.PUT_RICH:
                    return 'sell_premium', 'bull_put_spread', 0.55
                else:
                    return 'sell_premium', 'iron_condor', 0.50
            else:
                return 'no_trade', 'wait_for_better_setup', 0.6
        
        return 'no_trade', 'none', 0.5


def analyze_unusual_flow(
    options_data: List[Dict],
    avg_volumes: Dict[str, float]
) -> List[FlowSignal]:
    """
    Scan for unusual options activity
    
    Args:
        options_data: List of option quotes with volume/OI
        avg_volumes: Average daily volume by strike
    
    Returns:
        List of FlowSignal for unusual activity
    """
    signals = []
    
    for opt in options_data:
        strike = opt.get('strike')
        volume = opt.get('volume', 0)
        oi = opt.get('open_interest', 1)
        
        # Skip if no meaningful volume
        if volume < 100:
            continue
        
        avg_vol = avg_volumes.get(str(strike), volume / 2)
        vol_oi_ratio = volume / oi if oi > 0 else 0
        
        # Check for unusual activity
        is_unusual = (
            volume > avg_vol * 2 or  # 2x average
            vol_oi_ratio > 0.5       # High volume relative to OI
        )
        
        if is_unusual:
            # Determine sentiment
            # Simplified: buying calls or selling puts = bullish
            # This would need trade direction data for accuracy
            right = opt.get('right', 'C')
            sentiment = 'neutral'  # Would need more data
            
            # Size category
            if volume > 10000:
                size = 'block'
            elif volume > 5000:
                size = 'large'
            elif volume > 1000:
                size = 'medium'
            else:
                size = 'small'
            
            signals.append(FlowSignal(
                symbol=opt.get('symbol', ''),
                timestamp=datetime.now(),
                strike=strike,
                expiration=opt.get('expiration', ''),
                right=right,
                volume=volume,
                open_interest=oi,
                vol_oi_ratio=vol_oi_ratio,
                is_sweep=False,  # Would need exchange data
                sentiment=sentiment,
                size_category=size
            ))
    
    return signals


def format_analysis_report(analysis: OptionsAnalysis) -> str:
    """Format analysis for display/notification"""
    
    # Regime emoji
    regime_emoji = {
        VolatilityRegime.RICH: "🟢",
        VolatilityRegime.FAIR: "🟡", 
        VolatilityRegime.CHEAP: "🔴",
        VolatilityRegime.EXTREME: "⚠️"
    }
    
    term_emoji = {
        TermStructure.CONTANGO: "📈",
        TermStructure.FLAT: "➡️",
        TermStructure.BACKWARDATION: "📉"
    }
    
    return f"""
📊 OPTIONS ANALYSIS: {analysis.symbol}
{analysis.timestamp.strftime('%Y-%m-%d %H:%M')}

{regime_emoji.get(analysis.vol_regime, '')} Vol Regime: {analysis.vol_regime.value.upper()}
Confidence: {analysis.confidence:.0%}

📈 VOLATILITY
IV Rank: {analysis.iv_rank:.0f}%
IV Percentile: {analysis.iv_percentile:.0f}%
Current IV: {analysis.current_iv:.1%}
20-day HV: {analysis.hv_20:.1%}
IV/HV Ratio: {analysis.iv_hv_ratio:.2f}x

{term_emoji.get(analysis.term_structure, '')} TERM STRUCTURE
VIX: {analysis.vix:.1f}
VIX3M: {analysis.vix3m:.1f}
Structure: {analysis.term_structure.value}
Slope: {analysis.term_slope:+.1%}

📐 EXPECTED MOVE
Expected ({analysis.expected_move_pct:.1%}) vs Realized ({analysis.realized_move_20d:.1%})
Ratio: {analysis.move_ratio:.2f}x

↔️ SKEW
Put IV (25Δ): {analysis.put_iv:.1%}
Call IV (25Δ): {analysis.call_iv:.1%}
Skew: {(analysis.put_iv - analysis.call_iv)*100:+.1f} pts ({analysis.skew_regime.value})

📊 FLOW
P/C Ratio: {analysis.put_call_ratio:.2f}
Volume vs Avg: {analysis.volume_vs_avg:.1f}x
{"⚡ UNUSUAL ACTIVITY" if analysis.unusual_activity else "Normal activity"}

📅 EARNINGS
{"⚠️ Earnings within DTE - AVOID" if analysis.earnings_within_dte else "No earnings conflict"}

💡 RECOMMENDATION
{analysis.recommendation.upper().replace('_', ' ')}
Strategy: {analysis.recommended_strategy}
"""
