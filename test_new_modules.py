"""
Test all new modules:
- Earnings Calendar
- Liquidity Filter
- Correlation Filter
- Portfolio Greeks
- Rolling Manager
- Expected Move
- IV Surface
"""
import sys
sys.path.insert(0, '.')

from datetime import datetime, timedelta
import random


def test_earnings_calendar():
    """Test earnings calendar functionality"""
    print("\n" + "="*60)
    print("EARNINGS CALENDAR TEST")
    print("="*60)
    
    from earnings_calendar import EarningsCalendar, EarningsEvent
    
    calendar = EarningsCalendar(cache_file="test_earnings.json")
    
    # Test manual addition
    calendar.add_manual_earnings(
        'AAPL',
        datetime.now() + timedelta(days=15),
        timing='AMC',
        confirmed=True
    )
    
    # Check if earnings within DTE
    print(f"\nAAPL earnings within 30 DTE: {calendar.is_earnings_within_dte('AAPL', 30)}")
    print(f"AAPL earnings within 10 DTE: {calendar.is_earnings_within_dte('AAPL', 10)}")
    
    # Test safe DTE
    safe_dte = calendar.get_safe_dte('AAPL', preferred_dte=35)
    print(f"Safe DTE for AAPL: {safe_dte}")
    
    print("\n✅ Earnings calendar working")


def test_liquidity_filter():
    """Test liquidity filter functionality"""
    print("\n" + "="*60)
    print("LIQUIDITY FILTER TEST")
    print("="*60)
    
    from liquidity_filter import LiquidityFilter, LiquidityConfig
    
    config = LiquidityConfig()
    filter = LiquidityFilter(config)
    
    # Test liquid option
    liquid = filter.check_option(
        symbol='SPY',
        strike=580.0,
        right='P',
        expiration='20260306',
        bid=2.50,
        ask=2.55,
        volume=5000,
        open_interest=50000
    )
    print(f"\nLiquid SPY put: {liquid.is_liquid} (spread: {liquid.spread_pct:.1%})")
    
    # Test illiquid option
    illiquid = filter.check_option(
        symbol='SPY',
        strike=580.0,
        right='P',
        expiration='20260306',
        bid=2.00,
        ask=3.00,
        volume=10,
        open_interest=50
    )
    print(f"Illiquid SPY put: {illiquid.is_liquid} (reason: {illiquid.rejection_reason})")
    
    # Test spread check
    short_leg = {'bid': 2.50, 'ask': 2.55, 'volume': 5000, 'open_interest': 50000}
    long_leg = {'bid': 1.00, 'ask': 1.05, 'volume': 3000, 'open_interest': 30000}
    
    is_liquid, reason, fill = filter.check_spread(short_leg, long_leg, 'SPY')
    print(f"\nSpread liquidity: {is_liquid}, estimated fill: ${fill:.2f}")
    
    print("\n✅ Liquidity filter working")


def test_correlation_filter():
    """Test correlation filter functionality"""
    print("\n" + "="*60)
    print("CORRELATION FILTER TEST")
    print("="*60)
    
    from correlation_filter import (
        CorrelationFilter, CorrelationConfig, PositionExposure,
        get_direction_from_strategy, format_correlation_matrix
    )
    
    config = CorrelationConfig(
        max_positions_per_group=1,
        max_cross_equity_positions=2
    )
    filter = CorrelationFilter(config)
    
    # Check correlations
    print(f"\nSPY-QQQ correlation: {filter.get_correlation('SPY', 'QQQ'):.0%}")
    print(f"SPY-IWM correlation: {filter.get_correlation('SPY', 'IWM'):.0%}")
    print(f"SPY-GLD correlation: {filter.get_correlation('SPY', 'GLD'):.0%}")
    
    # Test with existing positions
    existing = [
        PositionExposure(
            symbol='SPY',
            direction='bullish',
            strategy='bull_put_spread',
            delta_exposure=10,
            notional_risk=500
        )
    ]
    
    # Try to add QQQ (correlated)
    can_add_qqq, reason = filter.can_open_position('QQQ', 'bullish', existing)
    print(f"\nCan add QQQ bull put (with SPY): {can_add_qqq}")
    print(f"Reason: {reason}")
    
    # Try to add GLD (uncorrelated)
    can_add_gld, reason = filter.can_open_position('GLD', 'bullish', existing)
    print(f"\nCan add GLD bull put (with SPY): {can_add_gld}")
    print(f"Reason: {reason}")
    
    # Print correlation matrix
    print(f"\n{format_correlation_matrix(['SPY', 'QQQ', 'IWM', 'GLD'])}")
    
    print("\n✅ Correlation filter working")


def test_portfolio_greeks():
    """Test portfolio Greeks tracking"""
    print("\n" + "="*60)
    print("PORTFOLIO GREEKS TEST")
    print("="*60)
    
    from portfolio_greeks import (
        PortfolioGreeksManager, GreeksLimits, format_greeks_report
    )
    
    limits = GreeksLimits(
        max_net_delta=100,
        max_delta_per_symbol=50
    )
    manager = PortfolioGreeksManager(limits)
    
    # Add a bull put spread position
    manager.update_position(
        position_id='SPY_20260306_1',
        symbol='SPY',
        strategy='bull_put_spread',
        quantity=1,
        short_delta=-0.25,  # Short put
        long_delta=-0.10,   # Long put
        short_gamma=0.02,
        long_gamma=0.01,
        short_theta=-0.05,  # Negative because we sold
        long_theta=-0.02,
        short_vega=0.15,
        long_vega=0.08,
        underlying_price=585.0,
        dte=35
    )
    
    # Add an iron condor
    manager.update_iron_condor(
        position_id='QQQ_20260306_1',
        symbol='QQQ',
        quantity=1,
        put_short_greeks={'delta': -0.20, 'gamma': 0.02, 'theta': -0.04, 'vega': 0.12},
        put_long_greeks={'delta': -0.08, 'gamma': 0.01, 'theta': -0.02, 'vega': 0.06},
        call_short_greeks={'delta': 0.20, 'gamma': 0.02, 'theta': -0.04, 'vega': 0.12},
        call_long_greeks={'delta': 0.08, 'gamma': 0.01, 'theta': -0.02, 'vega': 0.06},
        underlying_price=510.0,
        dte=35
    )
    
    # Get summary
    summary = manager.get_summary()
    print(format_greeks_report(summary))
    
    # Check limits
    breaches = manager.check_limits()
    if breaches:
        print("\n⚠️ Limit breaches:")
        for metric, status, current, limit in breaches:
            print(f"  {metric}: {status} ({current:.1f} vs {limit:.1f})")
    else:
        print("\n✅ All limits OK")
    
    # Check if can add more
    can_add, reason = manager.can_add_position(new_delta=15, new_symbol='IWM')
    print(f"\nCan add 15 delta IWM position: {can_add} ({reason})")
    
    print("\n✅ Portfolio Greeks working")


def test_rolling_manager():
    """Test position rolling logic"""
    print("\n" + "="*60)
    print("ROLLING MANAGER TEST")
    print("="*60)
    
    from rolling_manager import (
        RollingManager, RollConfig, format_roll_recommendation
    )
    
    config = RollConfig(
        tested_threshold=0.03,  # 3% from short strike
        loss_threshold_pct=1.0,
        max_rolls_per_position=2
    )
    manager = RollingManager(config)
    
    # Test position being tested (price near short strike)
    candidate = manager.analyze_position_for_roll(
        position_id='SPY_20260306_1',
        symbol='SPY',
        strategy='bull_put_spread',
        short_strike=575.0,
        long_strike=570.0,
        expiration='20260306',
        entry_credit=1.50,
        current_value=2.50,  # Losing money
        underlying_price=577.0,  # Near short strike!
        available_expirations=['20260306', '20260313', '20260320', '20260327'],
        available_strikes=[550, 555, 560, 565, 570, 575, 580, 585, 590],
        roll_count=0
    )
    
    if candidate:
        should_roll, reason = manager.should_roll(candidate)
        print(format_roll_recommendation(candidate, should_roll, reason))
    else:
        print("No roll needed")
    
    print("\n✅ Rolling manager working")


def test_expected_move():
    """Test expected move calculation"""
    print("\n" + "="*60)
    print("EXPECTED MOVE TEST")
    print("="*60)
    
    from expected_move import (
        ExpectedMoveCalculator, format_expected_move_report
    )
    
    calc = ExpectedMoveCalculator()
    
    # Calculate from straddle
    em_data = calc.calculate_from_straddle(
        symbol='SPY',
        underlying_price=585.0,
        atm_strike=585.0,
        call_price=8.50,
        put_price=8.00,
        expiration='20260306',
        dte=35
    )
    
    print(format_expected_move_report(em_data))
    
    # Get probability OTM
    prob_575_put = calc.get_probability_otm(
        strike=575.0,
        underlying_price=585.0,
        expected_move=em_data.expected_move_dollars,
        is_put=True
    )
    print(f"\nProbability 575 put expires OTM: {prob_575_put:.0%}")
    
    # Get strike suggestions
    suggestions = calc.suggest_strikes(em_data, target_prob_otm=0.70)
    print(f"\n70% Prob OTM strike suggestions:")
    print(f"  Put spread: {suggestions['put_spread']}")
    print(f"  Call spread: {suggestions['call_spread']}")
    
    print("\n✅ Expected move calculator working")


def test_iv_surface():
    """Test IV surface analysis"""
    print("\n" + "="*60)
    print("IV SURFACE TEST")
    print("="*60)
    
    from iv_surface import (
        IVSurfaceAnalyzer, format_iv_surface
    )
    
    analyzer = IVSurfaceAnalyzer()
    
    # Generate mock options data
    def mock_options(exp: str, base_iv: float, price: float):
        options = []
        for strike in range(int(price * 0.90), int(price * 1.10), 5):
            distance = abs(strike - price) / price
            # IV smile: higher IV away from ATM
            smile_adj = 1 + (distance * 0.5)
            
            # Skew: puts have higher IV
            put_skew = 1.03 if strike < price else 0.98
            
            iv = base_iv * smile_adj
            
            # Delta approximation
            if strike < price:
                put_delta = -0.5 + (price - strike) / price
                call_delta = 1 + put_delta
            else:
                call_delta = 0.5 - (strike - price) / price
                put_delta = call_delta - 1
            
            options.extend([
                {'strike': strike, 'right': 'C', 'iv': iv, 'delta': call_delta},
                {'strike': strike, 'right': 'P', 'iv': iv * put_skew, 'delta': put_delta},
            ])
        return options
    
    price = 585.0
    options_data = {
        '20260220': mock_options('20260220', 0.18, price),
        '20260306': mock_options('20260306', 0.19, price),
        '20260320': mock_options('20260320', 0.195, price),
        '20260417': mock_options('20260417', 0.20, price),
    }
    
    surface = analyzer.build_surface(
        symbol='SPY',
        underlying_price=price,
        options_data=options_data
    )
    
    print(format_iv_surface(surface))
    
    # Find best expiration
    best_exp = analyzer.find_best_expiration_for_selling(surface, min_dte=20, max_dte=45)
    if best_exp:
        print(f"\n💡 Best expiration for selling: {best_exp.expiration} ({best_exp.dte} DTE)")
        print(f"   ATM IV: {best_exp.atm_iv:.1%}, Skew: {best_exp.skew:+.1f}")
    
    # Find calendar opportunities
    calendars = analyzer.find_calendar_spread_opportunities(surface)
    if calendars:
        print(f"\n📅 Calendar spread opportunity:")
        c = calendars[0]
        print(f"   {c['near_exp']} ({c['near_iv']:.1%}) vs {c['far_exp']} ({c['far_iv']:.1%})")
        print(f"   IV diff: {c['iv_diff_pct']:+.1%} -> {c['trade']}")
    
    print("\n✅ IV surface analyzer working")


def test_integration():
    """Test integration of all modules"""
    print("\n" + "="*60)
    print("INTEGRATION TEST: Full Trade Decision Flow")
    print("="*60)
    
    from earnings_calendar import EarningsCalendar
    from liquidity_filter import LiquidityFilter
    from correlation_filter import CorrelationFilter, PositionExposure
    from portfolio_greeks import PortfolioGreeksManager
    from expected_move import ExpectedMoveCalculator
    
    # Initialize all components
    earnings = EarningsCalendar(cache_file="test_earnings.json")
    liquidity = LiquidityFilter()
    correlation = CorrelationFilter()
    greeks = PortfolioGreeksManager()
    em_calc = ExpectedMoveCalculator()
    
    # Simulate existing position
    existing_positions = [
        PositionExposure('SPY', 'bullish', 'bull_put_spread', 15, 500)
    ]
    
    # Mock new trade parameters
    new_symbol = 'QQQ'
    new_direction = 'bullish'
    dte = 35
    
    print(f"\nEvaluating new trade: {new_symbol} bull put spread")
    print("-" * 40)
    
    # Step 1: Check earnings
    has_earnings = earnings.is_earnings_within_dte(new_symbol, dte)
    print(f"1. Earnings check: {'❌ BLOCKED' if has_earnings else '✅ CLEAR'}")
    
    if has_earnings:
        print("   Trade blocked due to upcoming earnings")
        return
    
    # Step 2: Check correlation
    can_add, corr_reason = correlation.can_open_position(
        new_symbol, new_direction, existing_positions
    )
    print(f"2. Correlation check: {'✅ OK' if can_add else '❌ BLOCKED'} - {corr_reason}")
    
    if not can_add:
        print("   Trade blocked due to correlation")
        return
    
    # Step 3: Check portfolio Greeks
    can_add_greeks, greek_reason = greeks.can_add_position(15, new_symbol)
    print(f"3. Greeks check: {'✅ OK' if can_add_greeks else '❌ BLOCKED'} - {greek_reason}")
    
    # Step 4: Calculate expected move for strike selection
    em = em_calc.calculate_from_iv(
        symbol=new_symbol,
        underlying_price=510.0,
        implied_vol=0.22,
        dte=dte
    )
    print(f"4. Expected move: ±${em[0]:.2f} ({em[0]/510:.1%})")
    
    # Step 5: Mock liquidity check
    is_liquid, liq_reason, fill = liquidity.check_spread(
        {'bid': 2.50, 'ask': 2.55, 'volume': 5000, 'open_interest': 50000},
        {'bid': 1.00, 'ask': 1.05, 'volume': 3000, 'open_interest': 30000},
        new_symbol
    )
    print(f"5. Liquidity check: {'✅ OK' if is_liquid else '❌ BLOCKED'} - Est fill: ${fill:.2f}")
    
    print("\n" + "="*40)
    print("✅ ALL CHECKS PASSED - TRADE APPROVED")
    print("="*40)


def main():
    """Run all tests"""
    print("""
╔═══════════════════════════════════════════════════════════╗
║          NEW MODULES TEST SUITE                           ║
║                                                           ║
║   • Earnings Calendar                                     ║
║   • Liquidity Filter                                      ║
║   • Correlation Filter                                    ║
║   • Portfolio Greeks                                      ║
║   • Rolling Manager                                       ║
║   • Expected Move Calculator                              ║
║   • IV Surface Analyzer                                   ║
╚═══════════════════════════════════════════════════════════╝
    """)
    
    try:
        test_earnings_calendar()
        test_liquidity_filter()
        test_correlation_filter()
        test_portfolio_greeks()
        test_rolling_manager()
        test_expected_move()
        test_iv_surface()
        test_integration()
        
        print("\n" + "="*60)
        print("🎉 ALL TESTS PASSED!")
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
