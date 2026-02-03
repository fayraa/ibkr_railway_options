"""
Regime Detector
Determines market regime based on VIX, trend, and momentum indicators
"""
import logging
from typing import Optional, Dict, List
from dataclasses import dataclass
from datetime import datetime

import pandas as pd
import numpy as np

from config import Regime, RegimeConfig

logger = logging.getLogger(__name__)


@dataclass
class RegimeAnalysis:
    """Complete regime analysis result"""
    regime: Regime
    confidence: float  # 0-1 confidence score
    vix_level: float
    vix_regime: str  # 'low', 'normal', 'high', 'extreme'
    trend: str  # 'bullish', 'bearish', 'neutral'
    trend_strength: float
    rsi: float
    rsi_signal: str  # 'oversold', 'neutral', 'overbought'
    timestamp: datetime
    details: Dict


class RegimeDetector:
    """
    Detects market regime using multiple indicators:
    - VIX level (volatility environment)
    - Price trend (SMA crossover)
    - RSI (momentum/mean reversion)
    """
    
    def __init__(self, config: RegimeConfig):
        self.config = config
    
    def analyze(
        self, 
        vix: float, 
        price_history: List[Dict],
        symbol: str = "SPY"
    ) -> RegimeAnalysis:
        """
        Full regime analysis
        
        Args:
            vix: Current VIX level
            price_history: List of OHLCV dicts with 'close' prices
            symbol: Symbol being analyzed
        
        Returns:
            RegimeAnalysis with complete breakdown
        """
        # Convert to DataFrame
        df = pd.DataFrame(price_history)
        if 'close' not in df.columns:
            raise ValueError("price_history must contain 'close' column")
        
        # Calculate indicators
        vix_regime, vix_score = self._analyze_vix(vix)
        trend, trend_strength = self._analyze_trend(df)
        rsi, rsi_signal = self._calculate_rsi(df)
        
        # Combine signals to determine regime
        regime, confidence = self._determine_regime(
            vix_regime=vix_regime,
            vix_score=vix_score,
            trend=trend,
            trend_strength=trend_strength,
            rsi_signal=rsi_signal
        )
        
        return RegimeAnalysis(
            regime=regime,
            confidence=confidence,
            vix_level=vix,
            vix_regime=vix_regime,
            trend=trend,
            trend_strength=trend_strength,
            rsi=rsi,
            rsi_signal=rsi_signal,
            timestamp=datetime.now(),
            details={
                'symbol': symbol,
                'fast_sma': df['close'].rolling(self.config.fast_sma).mean().iloc[-1],
                'slow_sma': df['close'].rolling(self.config.slow_sma).mean().iloc[-1],
                'current_price': df['close'].iloc[-1]
            }
        )
    
    def _analyze_vix(self, vix: float) -> tuple[str, float]:
        """
        Analyze VIX level
        Returns: (regime_label, score from 0-1)
        """
        if vix < self.config.vix_low:
            return 'low', 0.2
        elif vix < self.config.vix_high:
            return 'normal', 0.5
        elif vix < self.config.vix_extreme:
            return 'high', 0.8
        else:
            return 'extreme', 1.0
    
    def _analyze_trend(self, df: pd.DataFrame) -> tuple[str, float]:
        """
        Analyze price trend using SMA crossover
        Returns: (trend_direction, strength 0-1)
        """
        close = df['close']
        
        fast_sma = close.rolling(self.config.fast_sma).mean()
        slow_sma = close.rolling(self.config.slow_sma).mean()
        
        if fast_sma.iloc[-1] is None or slow_sma.iloc[-1] is None:
            return 'neutral', 0.0
        
        # Calculate percentage difference
        diff_pct = (fast_sma.iloc[-1] - slow_sma.iloc[-1]) / slow_sma.iloc[-1]
        
        # Determine trend direction
        if diff_pct > self.config.trend_threshold:
            trend = 'bullish'
        elif diff_pct < -self.config.trend_threshold:
            trend = 'bearish'
        else:
            trend = 'neutral'
        
        # Trend strength (capped at 1.0)
        strength = min(abs(diff_pct) / (self.config.trend_threshold * 2), 1.0)
        
        return trend, strength
    
    def _calculate_rsi(self, df: pd.DataFrame) -> tuple[float, str]:
        """
        Calculate RSI and determine signal
        Returns: (rsi_value, signal)
        """
        close = df['close']
        delta = close.diff()
        
        gain = (delta.where(delta > 0, 0)).rolling(window=self.config.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.config.rsi_period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        current_rsi = rsi.iloc[-1]
        
        if pd.isna(current_rsi):
            return 50.0, 'neutral'
        
        if current_rsi < self.config.rsi_oversold:
            signal = 'oversold'
        elif current_rsi > self.config.rsi_overbought:
            signal = 'overbought'
        else:
            signal = 'neutral'
        
        return current_rsi, signal
    
    def _determine_regime(
        self,
        vix_regime: str,
        vix_score: float,
        trend: str,
        trend_strength: float,
        rsi_signal: str
    ) -> tuple[Regime, float]:
        """
        Combine all signals to determine overall regime
        Returns: (Regime, confidence)
        """
        # Extreme VIX = no trade
        if vix_regime == 'extreme':
            return Regime.UNKNOWN, 0.9
        
        # High VIX environment - focus on selling premium
        if vix_regime == 'high':
            # In high vol, lean towards iron condors unless strong trend
            if trend_strength > 0.7:
                if trend == 'bullish':
                    return Regime.BULLISH, 0.6
                elif trend == 'bearish':
                    return Regime.BEARISH, 0.6
            return Regime.HIGH_VOL, 0.7
        
        # Normal/Low VIX - follow trend
        if trend == 'bullish':
            # Bullish trend, not overbought
            if rsi_signal != 'overbought':
                confidence = 0.6 + (trend_strength * 0.3)
                return Regime.BULLISH, confidence
            else:
                # Overbought in uptrend - sideways/cautious
                return Regime.SIDEWAYS, 0.5
        
        elif trend == 'bearish':
            # Bearish trend, not oversold
            if rsi_signal != 'oversold':
                confidence = 0.6 + (trend_strength * 0.3)
                return Regime.BEARISH, confidence
            else:
                # Oversold in downtrend - sideways/cautious
                return Regime.SIDEWAYS, 0.5
        
        else:
            # Neutral trend
            if vix_regime == 'low':
                # Low vol, no trend = sideways range
                return Regime.SIDEWAYS, 0.7
            else:
                return Regime.SIDEWAYS, 0.5
    
    def get_regime_summary(self, analysis: RegimeAnalysis) -> str:
        """Generate human-readable regime summary"""
        lines = [
            f"📊 Regime Analysis ({analysis.timestamp.strftime('%Y-%m-%d %H:%M')})",
            f"",
            f"Overall Regime: {analysis.regime.value.upper()}",
            f"Confidence: {analysis.confidence:.0%}",
            f"",
            f"VIX: {analysis.vix_level:.1f} ({analysis.vix_regime})",
            f"Trend: {analysis.trend} (strength: {analysis.trend_strength:.0%})",
            f"RSI: {analysis.rsi:.1f} ({analysis.rsi_signal})",
        ]
        
        if analysis.details:
            lines.extend([
                f"",
                f"Fast SMA: {analysis.details.get('fast_sma', 0):.2f}",
                f"Slow SMA: {analysis.details.get('slow_sma', 0):.2f}",
                f"Price: {analysis.details.get('current_price', 0):.2f}"
            ])
        
        return "\n".join(lines)


def quick_regime_check(vix: float, trend: str) -> Regime:
    """
    Quick regime determination without full analysis
    Useful for simple checks
    """
    if vix > 35:
        return Regime.UNKNOWN
    elif vix > 25:
        return Regime.HIGH_VOL
    elif trend == 'bullish':
        return Regime.BULLISH
    elif trend == 'bearish':
        return Regime.BEARISH
    else:
        return Regime.SIDEWAYS
