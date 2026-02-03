"""
Test script for V2 volatility-focused analysis
No IBKR connection required - uses simulated data
"""
import sys
sys.path.insert(0, '.')

from datetime import datetime, timedelta
import random
import numpy as np

from config_v2 import load_config, Strategy
from options_analyzer import (
    OptionsMarketAnalyzer, OptionsAnalysis,
    VolatilityRegime, TermStructure, SkewRegime,
    format_analysis_report
)


def generate_mock_price_history(
    start_price: float = 500.0,
    days: int = 60,
    volatility: float = 0.15
) -> list:
    """Generate mock OHLCV data"""
    history = []
    price = start_price
    
    daily_vol = volatility / np.sqrt(252)
    
    for i in range(days):
        daily_return = random.gauss(0.0003, daily_vol)  # Slight upward drift
        price = price * (1 + daily_return)
        
        high = price * (1 + abs(random.gauss(0, daily_vol)))
        low = price * (1 - abs(random.gauss(0, daily_vol)))
        open_price = price * (1 + random.gauss(0, daily_vol/2))
        
        history.append({
            'date': datetime.now() - timedelta(days=days-i),
            'open': open_price,
            'high': max(high, open_price, price),
            'low': min(low, open_price, price),
            'close': price,
            'volume': random.randint(50000000, 150000000)
        })
    
    return history


def generate_mock_iv_history(
    current_iv: float,
    days: int = 252
) -> list:
    """Generate mock IV history around current level"""
    # IV mean-reverts, so generate around a base level
    base_iv = current_iv * 0.9
    iv_history = []
    
    iv = base_iv
    for _ in range(days):
        # Mean-reverting process
        iv = iv + 0.05 * (base_iv - iv) + random.gauss(0, 0.01)
        iv = max(0.08, min(0.60, iv))  # Clamp between 8% and 60%
        iv_history.append(iv)
    
    return iv_history


def test_scenario(
    name: str,
    vix: float,
    vix3m: float,
    current_iv: float,
    iv_rank_target: float,  # What IV rank we want to achieve
    put_iv_premium: float,  # How much higher put IV is
    unusual_volume: bool = False
):
    """Test a specific market scenario"""
    
    print(f"\n{'='*60}")
    print(f"SCENARIO: {name}")
    print(f"{'='*60}")
    
    config = load_config()
    analyzer = OptionsMarketAnalyzer({
        'iv_rank_high': config.volatility.iv_rank_rich,
        'iv_rank_low': config.volatility.iv_rank_fair,
        'iv_rank_extreme': config.volatility.iv_rank_extreme,
        'iv_hv_rich': config.volatility.iv_hv_rich,
        'iv_hv_cheap': config.volatility.iv_hv_cheap,
        'contango_threshold': config.volatility.contango_threshold,
        'backwardation_threshold': config.volatility.backwardation_threshold,
        'move_ratio_rich': config.volatility.move_ratio_edge,
        'skew_rich_threshold': config.volatility.skew_put_rich,
        'unusual_volume_mult': config.flow.unusual_volume_mult,
        'vol_oi_unusual': config.flow.vol_oi_unusual,
    })
    
    # Generate mock data
    price_history = generate_mock_price_history(volatility=current_iv * 0.8)
    
    # Generate IV history to achieve target IV rank
    # IV Rank = (Current - Min) / (Max - Min)
    # If we want 70% rank with current = 0.20:
    # We need min and max such that (0.20 - min) / (max - min) = 0.70
    iv_min = current_iv * (1 - iv_rank_target/100)
    iv_max = current_iv * (1 + (100-iv_rank_target)/100)
    iv_history = [random.uniform(iv_min, iv_max) for _ in range(252)]
    
    # Skew data
    skew_data = {
        'put_25d_iv': current_iv + put_iv_premium/100,
        'call_25d_iv': current_iv - put_iv_premium/200,
        'atm_iv': current_iv
    }
    
    # Volume data
    volume_data = {
        'put_volume': random.randint(80000, 120000),
        'call_volume': random.randint(90000, 110000),
        'put_oi': random.randint(400000, 600000),
        'call_oi': random.randint(400000, 600000),
        'avg_daily_volume': 100000 if not unusual_volume else 50000
    }
    
    # Run analysis
    analysis = analyzer.analyze(
        symbol='SPY',
        current_iv=current_iv,
        iv_history=iv_history,
        price_history=price_history,
        vix=vix,
        vix3m=vix3m,
        options_chain_data=skew_data,
        volume_data=volume_data,
        earnings_date=None,
        target_dte=35
    )
    
    # Print results
    print(format_analysis_report(analysis))
    
    return analysis


def run_all_scenarios():
    """Run through different market scenarios"""
    
    print("""
╔═══════════════════════════════════════════════════════════╗
║     OPTIONS BOT V2 - SCENARIO TESTING                     ║
║         Volatility-Focused Decision Logic                 ║
╚═══════════════════════════════════════════════════════════╝
    """)
    
    scenarios = [
        # Scenario 1: Rich premium environment - IDEAL
        {
            'name': 'RICH PREMIUM (Ideal Selling Environment)',
            'vix': 22.0,
            'vix3m': 24.0,
            'current_iv': 0.22,
            'iv_rank_target': 70,
            'put_iv_premium': 4.0,  # Puts 4 pts higher
            'unusual_volume': False
        },
        # Scenario 2: Cheap premium - DON'T SELL
        {
            'name': 'CHEAP PREMIUM (Avoid Selling)',
            'vix': 13.0,
            'vix3m': 14.0,
            'current_iv': 0.13,
            'iv_rank_target': 20,
            'put_iv_premium': 2.0,
            'unusual_volume': False
        },
        # Scenario 3: High VIX backwardation - SELL PUTS ONLY
        {
            'name': 'FEAR MODE (Backwardation - Sell Puts)',
            'vix': 28.0,
            'vix3m': 26.0,  # VIX > VIX3M = backwardation
            'current_iv': 0.28,
            'iv_rank_target': 80,
            'put_iv_premium': 6.0,  # Very rich put skew
            'unusual_volume': True
        },
        # Scenario 4: Crisis - NO TRADE
        {
            'name': 'CRISIS MODE (VIX Extreme)',
            'vix': 40.0,
            'vix3m': 35.0,
            'current_iv': 0.42,
            'iv_rank_target': 95,
            'put_iv_premium': 8.0,
            'unusual_volume': True
        },
        # Scenario 5: Fair premium, neutral skew - SELECTIVE
        {
            'name': 'FAIR PREMIUM (Selective Trading)',
            'vix': 18.0,
            'vix3m': 19.5,
            'current_iv': 0.18,
            'iv_rank_target': 45,
            'put_iv_premium': 2.5,
            'unusual_volume': False
        },
    ]
    
    results = []
    for scenario in scenarios:
        analysis = test_scenario(**scenario)
        results.append({
            'name': scenario['name'],
            'vol_regime': analysis.vol_regime.value,
            'recommendation': analysis.recommendation,
            'strategy': analysis.recommended_strategy,
            'confidence': analysis.confidence,
            'iv_rank': analysis.iv_rank
        })
    
    # Summary table
    print(f"\n{'='*80}")
    print("SUMMARY: Decision Matrix Results")
    print(f"{'='*80}")
    print(f"{'Scenario':<35} {'Vol Regime':<15} {'Action':<15} {'Strategy':<20}")
    print("-" * 80)
    
    for r in results:
        print(f"{r['name'][:34]:<35} {r['vol_regime']:<15} {r['recommendation']:<15} {r['strategy']:<20}")
    
    print(f"\n{'='*80}")


def test_iv_rank_calculation():
    """Test that IV rank calculation is correct"""
    print("\n" + "="*60)
    print("IV RANK CALCULATION TEST")
    print("="*60)
    
    analyzer = OptionsMarketAnalyzer()
    
    test_cases = [
        # (current_iv, iv_history, expected_rank_approx)
        (0.20, [0.15, 0.16, 0.17, 0.18, 0.19, 0.20, 0.21, 0.22, 0.23, 0.24, 0.25], 50),
        (0.25, [0.15, 0.16, 0.17, 0.18, 0.19, 0.20, 0.21, 0.22, 0.23, 0.24, 0.25], 100),
        (0.15, [0.15, 0.16, 0.17, 0.18, 0.19, 0.20, 0.21, 0.22, 0.23, 0.24, 0.25], 0),
        (0.18, [0.15, 0.16, 0.17, 0.18, 0.19, 0.20, 0.21, 0.22, 0.23, 0.24, 0.25], 30),
    ]
    
    for current, history, expected in test_cases:
        rank, percentile = analyzer._calculate_iv_rank(current, history)
        status = "✅" if abs(rank - expected) < 10 else "⚠️"
        print(f"{status} Current IV: {current:.0%} | Calculated Rank: {rank:.0f}% | Expected: ~{expected}%")


def test_term_structure():
    """Test term structure detection"""
    print("\n" + "="*60)
    print("TERM STRUCTURE DETECTION TEST")
    print("="*60)
    
    analyzer = OptionsMarketAnalyzer()
    
    test_cases = [
        (18.0, 20.0, TermStructure.CONTANGO, "Normal market"),
        (25.0, 23.0, TermStructure.BACKWARDATION, "Fear/stress"),
        (20.0, 20.5, TermStructure.FLAT, "Transitional"),
    ]
    
    for vix, vix3m, expected, desc in test_cases:
        structure, slope = analyzer._analyze_term_structure(vix, vix3m)
        status = "✅" if structure == expected else "❌"
        print(f"{status} VIX: {vix:.1f} | VIX3M: {vix3m:.1f} | Structure: {structure.value} | Expected: {expected.value} ({desc})")


def test_strategy_selection():
    """Test strategy selection logic"""
    print("\n" + "="*60)
    print("STRATEGY SELECTION LOGIC")
    print("="*60)
    
    print("""
┌─────────────────┬─────────────────┬─────────────────┬─────────────────┐
│ Vol Regime      │ Skew            │ Term Structure  │ Strategy        │
├─────────────────┼─────────────────┼─────────────────┼─────────────────┤
│ RICH            │ PUT_RICH        │ Any             │ Bull Put Spread │
│ RICH            │ NEUTRAL         │ Contango        │ Iron Condor     │
│ RICH            │ NEUTRAL         │ Backwardation   │ Bull Put Spread │
│ FAIR            │ PUT_RICH        │ Any             │ Bull Put Spread │
│ FAIR            │ NEUTRAL         │ Any             │ No Trade        │
│ CHEAP           │ Any             │ Any             │ No Trade        │
│ EXTREME         │ Any             │ Any             │ No Trade        │
└─────────────────┴─────────────────┴─────────────────┴─────────────────┘
    """)


def main():
    """Run all tests"""
    test_iv_rank_calculation()
    test_term_structure()
    test_strategy_selection()
    run_all_scenarios()
    
    print("\n" + "="*60)
    print("✅ All V2 tests completed!")
    print("="*60)
    print("""
Key Differences from V1:
------------------------
❌ OLD: SMA crossover, RSI for regime detection
✅ NEW: IV Rank, IV/HV ratio, term structure

❌ OLD: Trend-following approach
✅ NEW: Volatility mean-reversion approach

❌ OLD: Trade in any regime with trend signal
✅ NEW: Only trade when premium is rich (IV Rank > 50%)

❌ OLD: Same strategy regardless of skew
✅ NEW: Skew-aware strategy selection

Next Steps:
-----------
1. Start TWS/Gateway and enable API
2. Run: python main_v2.py test
3. Review analysis output
4. Adjust thresholds in config_v2.py
5. Run: python main_v2.py run
    """)


if __name__ == '__main__':
    main()
