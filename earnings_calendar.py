"""
Earnings Calendar
Fetches and manages earnings dates to avoid selling into binary events

Data Sources (free):
1. Yahoo Finance (via yfinance)
2. Alpha Vantage (free tier)
3. Manual override file

Usage:
- Check if earnings are within DTE before opening position
- Auto-close positions before earnings if already open
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from dataclasses import dataclass
import json
import os

logger = logging.getLogger(__name__)


@dataclass
class EarningsEvent:
    """Single earnings event"""
    symbol: str
    date: datetime
    timing: str  # 'BMO' (before market open), 'AMC' (after market close), 'Unknown'
    confirmed: bool
    source: str
    
    def days_until(self) -> int:
        """Days until earnings"""
        return (self.date.date() - datetime.now().date()).days
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'date': self.date.isoformat(),
            'timing': self.timing,
            'confirmed': self.confirmed,
            'source': self.source
        }
    
    @staticmethod
    def from_dict(data: Dict) -> 'EarningsEvent':
        return EarningsEvent(
            symbol=data['symbol'],
            date=datetime.fromisoformat(data['date']),
            timing=data.get('timing', 'Unknown'),
            confirmed=data.get('confirmed', False),
            source=data.get('source', 'manual')
        )


class EarningsCalendar:
    """
    Manages earnings calendar data
    """
    
    def __init__(self, cache_file: str = "earnings_cache.json"):
        self.cache_file = cache_file
        self.earnings: Dict[str, EarningsEvent] = {}
        self._load_cache()
    
    def get_next_earnings(self, symbol: str) -> Optional[EarningsEvent]:
        """
        Get next earnings date for symbol
        Returns None if no upcoming earnings found
        """
        # Check cache first
        if symbol in self.earnings:
            event = self.earnings[symbol]
            if event.days_until() >= 0:  # Still in future
                return event
        
        # Try to fetch fresh data
        event = self._fetch_earnings_yfinance(symbol)
        
        if event:
            self.earnings[symbol] = event
            self._save_cache()
            return event
        
        return None
    
    def is_earnings_within_dte(
        self, 
        symbol: str, 
        dte: int,
        buffer_days: int = 2
    ) -> bool:
        """
        Check if earnings fall within DTE range
        
        Args:
            symbol: Stock symbol
            dte: Days to expiration of the option
            buffer_days: Extra buffer (don't sell if earnings within buffer after DTE)
        
        Returns:
            True if earnings are within the danger zone
        """
        event = self.get_next_earnings(symbol)
        
        if not event:
            return False  # No earnings found, safe to trade
        
        days_to_earnings = event.days_until()
        
        # Danger zone: earnings between now and (DTE + buffer)
        if 0 <= days_to_earnings <= (dte + buffer_days):
            logger.warning(
                f"{symbol} earnings in {days_to_earnings} days "
                f"(within {dte}+{buffer_days} day window)"
            )
            return True
        
        return False
    
    def get_safe_dte(
        self, 
        symbol: str, 
        preferred_dte: int,
        buffer_days: int = 2
    ) -> Optional[int]:
        """
        Get a safe DTE that avoids earnings
        
        Returns:
            Adjusted DTE or None if no safe option
        """
        event = self.get_next_earnings(symbol)
        
        if not event:
            return preferred_dte
        
        days_to_earnings = event.days_until()
        
        # If earnings are far out, use preferred DTE
        if days_to_earnings > preferred_dte + buffer_days:
            return preferred_dte
        
        # If earnings are soon, can we go shorter?
        if days_to_earnings > buffer_days + 7:  # At least 1 week before earnings
            return days_to_earnings - buffer_days - 1
        
        # Earnings too close, skip
        return None
    
    def _fetch_earnings_yfinance(self, symbol: str) -> Optional[EarningsEvent]:
        """Fetch earnings from Yahoo Finance"""
        try:
            import yfinance as yf
            
            ticker = yf.Ticker(symbol)
            calendar = ticker.calendar
            
            if calendar is None or calendar.empty:
                return None
            
            # Get earnings date
            if 'Earnings Date' in calendar.index:
                earnings_dates = calendar.loc['Earnings Date']
                if isinstance(earnings_dates, (list, tuple)) and len(earnings_dates) > 0:
                    earnings_date = earnings_dates[0]
                else:
                    earnings_date = earnings_dates
                
                if earnings_date:
                    # Convert to datetime if needed
                    if hasattr(earnings_date, 'to_pydatetime'):
                        earnings_date = earnings_date.to_pydatetime()
                    elif isinstance(earnings_date, str):
                        earnings_date = datetime.fromisoformat(earnings_date)
                    
                    return EarningsEvent(
                        symbol=symbol,
                        date=earnings_date,
                        timing='Unknown',
                        confirmed=False,
                        source='yfinance'
                    )
            
            return None
            
        except ImportError:
            logger.warning("yfinance not installed. Run: pip install yfinance")
            return None
        except Exception as e:
            logger.error(f"Error fetching earnings for {symbol}: {e}")
            return None
    
    def add_manual_earnings(
        self, 
        symbol: str, 
        date: datetime,
        timing: str = 'Unknown',
        confirmed: bool = True
    ):
        """Manually add earnings date"""
        self.earnings[symbol] = EarningsEvent(
            symbol=symbol,
            date=date,
            timing=timing,
            confirmed=confirmed,
            source='manual'
        )
        self._save_cache()
    
    def refresh_all(self, symbols: List[str]):
        """Refresh earnings data for all symbols"""
        for symbol in symbols:
            event = self._fetch_earnings_yfinance(symbol)
            if event:
                self.earnings[symbol] = event
        self._save_cache()
    
    def _save_cache(self):
        """Save earnings to cache file"""
        try:
            data = {
                symbol: event.to_dict() 
                for symbol, event in self.earnings.items()
            }
            with open(self.cache_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving earnings cache: {e}")
    
    def _load_cache(self):
        """Load earnings from cache file"""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r') as f:
                    data = json.load(f)
                    self.earnings = {
                        symbol: EarningsEvent.from_dict(event_data)
                        for symbol, event_data in data.items()
                    }
                logger.info(f"Loaded {len(self.earnings)} earnings events from cache")
        except Exception as e:
            logger.error(f"Error loading earnings cache: {e}")
            self.earnings = {}


# Known earnings for major ETFs (they don't have earnings but track them for reference)
# These are constituent earnings that can cause volatility
MAJOR_ETF_EARNINGS_WINDOWS = {
    'SPY': [],  # Track mega-cap earnings (AAPL, MSFT, etc.)
    'QQQ': [],  # Tech earnings heavy
    'IWM': [],  # Less concentrated
}


def get_high_impact_earnings_this_week() -> List[str]:
    """
    Get list of high-impact earnings this week
    These affect index ETFs significantly
    """
    # In production, fetch from API
    # For now, return empty list
    return []


def format_earnings_warning(event: EarningsEvent) -> str:
    """Format earnings warning for alerts"""
    return f"""
⚠️ EARNINGS WARNING: {event.symbol}

📅 Date: {event.date.strftime('%Y-%m-%d')}
⏰ Timing: {event.timing}
📊 Days until: {event.days_until()}
✓ Confirmed: {'Yes' if event.confirmed else 'Estimated'}

Recommendation: Avoid opening new positions or close existing ones.
"""
