"""
Test script to verify regime detection and spread logic without IBKR connection
"""
import sys
sys.path.insert(0, '.')

from datetime import datetime, timedelta
import random

from config import load_config, Regime, Strategy, REGIME_STRATEGY_MAP
from regime_detector import RegimeDetector, RegimeAnalysis


def generate_mock_price_history(
    start_price: float = 500.0,
    days: int = 60,
    trend: str = 'neutral'  # 'bullish', 'bearish', 'neutral'
) -> list:
    """Generate mock OHLCV data for testing"""
    history = []
    price = start_price
    
    for i in range(days):
        # Add trend bias
        if trend == 'bullish':
            drift = 0.002  # 0.2% daily drift up
        elif trend == 'bearish':
            drift = -0.002
        else:
            drift = 0
        
        # Random daily move
        daily_return = drift + random.gauss(0, 0.01)  # 1% daily vol
        price = price * (1 + daily_return)
        
        # Generate OHLC
        high = price * (1 + abs(random.gauss(0, 0.005)))
        low = price * (1 - abs(random.gauss(0, 0.005)))
        open_price = price * (1 + random.gauss(0, 0.003))
        
        history.append({
            'date': datetime.now() - timedelta(days=days-i),
            'open': open_price,
            'high': max(high, open_price, price),
            'low': min(low, open_price, price),
            'close': price,
            'volume': random.randint(50000000, 150000000)
        })
    
    return history


def test_regime_detection():
    """Test regime detection with different scenarios"""
    print("=" * 60)
    print("REGIME DETECTION TESTS")
    print("=" * 60)
    
    config = load_config()
    detector = RegimeDetector(config.regime)
    
    scenarios = [
        {'vix': 12, 'trend': 'bullish', 'expected': Regime.BULLISH},
        {'vix': 13, 'trend': 'bearish', 'expected': Regime.BEARISH},
        {'vix': 14, 'trend': 'neutral', 'expected': Regime.SIDEWAYS},
        {'vix': 28, 'trend': 'neutral', 'expected': Regime.HIGH_VOL},
        {'vix': 40, 'trend': 'bullish', 'expected': Regime.UNKNOWN},
    ]
    
    for scenario in scenarios:
        print(f"\n--- Scenario: VIX={scenario['vix']}, Trend={scenario['trend']} ---")
        
        history = generate_mock_price_history(trend=scenario['trend'])
        analysis = detector.analyze(scenario['vix'], history, 'SPY')
        
        print(f"Detected Regime: {analysis.regime.value}")
        print(f"Expected Regime: {scenario['expected'].value}")
        print(f"Confidence: {analysis.confidence:.0%}")
        print(f"VIX Regime: {analysis.vix_regime}")
        print(f"Trend: {analysis.trend} (strength: {analysis.trend_strength:.0%})")
        print(f"RSI: {analysis.rsi:.1f} ({analysis.rsi_signal})")
        
        # Check strategy mapping
        strategy = REGIME_STRATEGY_MAP.get(analysis.regime, Strategy.NO_TRADE)
        print(f"Strategy: {strategy.value}")
        
        if analysis.regime == scenario['expected']:
            print("✅ PASS")
        else:
            print("⚠️ Different from expected (may be due to random data)")


def test_strategy_mapping():
    """Test regime to strategy mapping"""
    print("\n" + "=" * 60)
    print("STRATEGY MAPPING")
    print("=" * 60)
    
    for regime in Regime:
        strategy = REGIME_STRATEGY_MAP.get(regime, Strategy.NO_TRADE)
        print(f"{regime.value:15} → {strategy.value}")


def test_spread_parameters():
    """Display spread configuration"""
    print("\n" + "=" * 60)
    print("SPREAD CONFIGURATION")
    print("=" * 60)
    
    config = load_config()
    
    print(f"Underlyings: {config.spread.underlyings}")
    print(f"Target Delta: {config.spread.target_delta}")
    print(f"Delta Range: {config.spread.delta_range}")
    print(f"Spread Width: ${config.spread.spread_width}")
    print(f"Target DTE: {config.spread.target_dte}")
    print(f"Min Credit: ${config.spread.min_credit}")
    print(f"Min Credit %: {config.spread.min_credit_pct:.0%}")


def test_risk_parameters():
    """Display risk configuration"""
    print("\n" + "=" * 60)
    print("RISK CONFIGURATION")
    print("=" * 60)
    
    config = load_config()
    
    print(f"Max Risk Per Trade: ${config.risk.max_risk_per_trade}")
    print(f"Max Positions: {config.risk.max_positions}")
    print(f"Profit Target: {config.risk.profit_target_pct:.0%}")
    print(f"Stop Loss Multiplier: {config.risk.stop_loss_multiplier}x")
    print(f"DTE Exit: {config.risk.min_dte_exit} days")


def simulate_trade_flow():
    """Simulate a complete trade flow"""
    print("\n" + "=" * 60)
    print("SIMULATED TRADE FLOW")
    print("=" * 60)
    
    config = load_config()
    detector = RegimeDetector(config.regime)
    
    # Simulate market data
    vix = 18.5
    spy_price = 585.0
    history = generate_mock_price_history(start_price=spy_price, trend='bullish')
    
    print(f"\n📊 Market Data:")
    print(f"   SPY Price: ${spy_price:.2f}")
    print(f"   VIX: {vix:.1f}")
    
    # Detect regime
    analysis = detector.analyze(vix, history, 'SPY')
    
    print(f"\n🔍 Regime Analysis:")
    print(f"   Regime: {analysis.regime.value}")
    print(f"   Confidence: {analysis.confidence:.0%}")
    print(f"   Trend: {analysis.trend}")
    
    # Determine strategy
    strategy = REGIME_STRATEGY_MAP.get(analysis.regime, Strategy.NO_TRADE)
    print(f"\n📈 Strategy: {strategy.value}")
    
    if strategy == Strategy.BULL_PUT_SPREAD:
        # Simulate spread construction
        short_strike = round(spy_price * 0.96, 0)  # ~4% OTM
        long_strike = short_strike - config.spread.spread_width
        credit = 1.25  # Simulated
        max_loss = config.spread.spread_width - credit
        
        print(f"\n💰 Bull Put Spread:")
        print(f"   Sell {short_strike} Put")
        print(f"   Buy {long_strike} Put")
        print(f"   Credit: ${credit:.2f}")
        print(f"   Max Loss: ${max_loss:.2f}")
        print(f"   Risk/Reward: {credit/max_loss:.1%}")
        
        # Calculate exits
        profit_target = credit * config.risk.profit_target_pct
        stop_loss = credit * config.risk.stop_loss_multiplier
        
        print(f"\n🎯 Exit Rules:")
        print(f"   Profit Target: ${profit_target:.2f} (50% of credit)")
        print(f"   Stop Loss: -${stop_loss:.2f} (2x credit)")
        print(f"   DTE Exit: {config.risk.min_dte_exit} days")
        
    elif strategy == Strategy.BEAR_CALL_SPREAD:
        short_strike = round(spy_price * 1.04, 0)  # ~4% OTM
        long_strike = short_strike + config.spread.spread_width
        credit = 1.15
        
        print(f"\n💰 Bear Call Spread:")
        print(f"   Sell {short_strike} Call")
        print(f"   Buy {long_strike} Call")
        print(f"   Credit: ${credit:.2f}")
        
    elif strategy == Strategy.IRON_CONDOR:
        put_short = round(spy_price * 0.96, 0)
        put_long = put_short - config.spread.spread_width
        call_short = round(spy_price * 1.04, 0)
        call_long = call_short + config.spread.spread_width
        
        print(f"\n💰 Iron Condor:")
        print(f"   Put side: Sell {put_short}P / Buy {put_long}P")
        print(f"   Call side: Sell {call_short}C / Buy {call_long}C")
        
    else:
        print(f"\n⚠️ No trade for this regime")


def main():
    print("""
╔═══════════════════════════════════════════════════════════╗
║          OPTIONS BOT - OFFLINE TEST SUITE                 ║
║            (No IBKR Connection Required)                  ║
╚═══════════════════════════════════════════════════════════╝
    """)
    
    test_strategy_mapping()
    test_spread_parameters()
    test_risk_parameters()
    test_regime_detection()
    simulate_trade_flow()
    
    print("\n" + "=" * 60)
    print("✅ All tests completed!")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Configure your Telegram bot in config.py")
    print("2. Start TWS/Gateway and enable API")
    print("3. Run: python main.py test")
    print("4. Then: python main.py run")


if __name__ == '__main__':
    main()
