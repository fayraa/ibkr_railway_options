"""
Position Manager
Tracks open positions and handles exit logic
"""
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime
import json
import os

from config import RiskConfig
from ibkr_client import IBKRClient
from spread_builder import CreditSpread, IronCondor

logger = logging.getLogger(__name__)


@dataclass
class TrackedPosition:
    """A tracked spread position"""
    position_id: str
    symbol: str
    strategy: str  # 'bull_put_spread', 'bear_call_spread', 'iron_condor'
    expiration: str
    
    # Entry details
    entry_credit: float
    entry_date: datetime
    quantity: int
    
    # Current state
    current_value: float = 0.0
    current_pnl: float = 0.0
    current_pnl_pct: float = 0.0
    dte_remaining: int = 0
    
    # Strikes
    short_strike: float = 0.0
    long_strike: float = 0.0
    call_short_strike: Optional[float] = None  # For iron condors
    call_long_strike: Optional[float] = None
    
    # Exit targets
    profit_target: float = 0.0  # $ amount
    stop_loss: float = 0.0      # $ amount (negative)
    
    # Status
    status: str = 'OPEN'  # OPEN, CLOSED, EXPIRED
    exit_reason: Optional[str] = None
    exit_date: Optional[datetime] = None
    realized_pnl: Optional[float] = None
    
    def to_dict(self) -> Dict:
        return {
            'position_id': self.position_id,
            'symbol': self.symbol,
            'strategy': self.strategy,
            'expiration': self.expiration,
            'entry_credit': self.entry_credit,
            'entry_date': self.entry_date.isoformat(),
            'quantity': self.quantity,
            'short_strike': self.short_strike,
            'long_strike': self.long_strike,
            'call_short_strike': self.call_short_strike,
            'call_long_strike': self.call_long_strike,
            'profit_target': self.profit_target,
            'stop_loss': self.stop_loss,
            'status': self.status,
            'exit_reason': self.exit_reason,
            'exit_date': self.exit_date.isoformat() if self.exit_date else None,
            'realized_pnl': self.realized_pnl
        }
    
    @staticmethod
    def from_dict(data: Dict) -> 'TrackedPosition':
        return TrackedPosition(
            position_id=data['position_id'],
            symbol=data['symbol'],
            strategy=data['strategy'],
            expiration=data['expiration'],
            entry_credit=data['entry_credit'],
            entry_date=datetime.fromisoformat(data['entry_date']),
            quantity=data['quantity'],
            short_strike=data.get('short_strike', 0),
            long_strike=data.get('long_strike', 0),
            call_short_strike=data.get('call_short_strike'),
            call_long_strike=data.get('call_long_strike'),
            profit_target=data.get('profit_target', 0),
            stop_loss=data.get('stop_loss', 0),
            status=data.get('status', 'OPEN'),
            exit_reason=data.get('exit_reason'),
            exit_date=datetime.fromisoformat(data['exit_date']) if data.get('exit_date') else None,
            realized_pnl=data.get('realized_pnl')
        )


class PositionManager:
    """
    Manages open positions:
    - Tracks all open spreads
    - Monitors P&L
    - Triggers exits based on rules
    """
    
    def __init__(self, client: IBKRClient, config: RiskConfig, data_file: str = "positions.json"):
        self.client = client
        self.config = config
        self.data_file = data_file
        self.positions: Dict[str, TrackedPosition] = {}
        
        # Load existing positions
        self._load_positions()
    
    def add_position(
        self,
        spread: CreditSpread | IronCondor,
        quantity: int,
        fill_price: float
    ) -> TrackedPosition:
        """
        Add a new position after order fill
        """
        position_id = f"{spread.symbol}_{spread.expiration}_{datetime.now().strftime('%H%M%S')}"
        
        # Calculate exit targets
        credit_per_contract = abs(fill_price) if fill_price else spread.credit if hasattr(spread, 'credit') else spread.total_credit
        total_credit = credit_per_contract * quantity * 100  # Convert to dollars
        
        profit_target = total_credit * self.config.profit_target_pct
        stop_loss = -(total_credit * self.config.stop_loss_multiplier)
        
        if isinstance(spread, CreditSpread):
            position = TrackedPosition(
                position_id=position_id,
                symbol=spread.symbol,
                strategy=spread.strategy.value,
                expiration=spread.expiration,
                entry_credit=credit_per_contract,
                entry_date=datetime.now(),
                quantity=quantity,
                short_strike=spread.short_leg.strike,
                long_strike=spread.long_leg.strike,
                profit_target=profit_target,
                stop_loss=stop_loss
            )
        else:  # IronCondor
            position = TrackedPosition(
                position_id=position_id,
                symbol=spread.symbol,
                strategy='iron_condor',
                expiration=spread.expiration,
                entry_credit=credit_per_contract,
                entry_date=datetime.now(),
                quantity=quantity,
                short_strike=spread.put_short_leg.strike,
                long_strike=spread.put_long_leg.strike,
                call_short_strike=spread.call_short_leg.strike,
                call_long_strike=spread.call_long_leg.strike,
                profit_target=profit_target,
                stop_loss=stop_loss
            )
        
        self.positions[position_id] = position
        self._save_positions()
        
        logger.info(f"Added position {position_id}: {spread.symbol} {position.strategy}")
        return position
    
    def update_position_values(self):
        """
        Update current values and P&L for all open positions
        """
        for pos_id, position in self.positions.items():
            if position.status != 'OPEN':
                continue
            
            try:
                # Calculate DTE
                exp_date = datetime.strptime(position.expiration, '%Y%m%d').date()
                position.dte_remaining = (exp_date - datetime.now().date()).days
                
                # Get current spread value
                current_value = self._get_spread_current_value(position)
                
                if current_value is not None:
                    position.current_value = current_value
                    
                    # P&L = Entry Credit - Current Value (to close)
                    # If we sold for $1.00 credit and can buy back for $0.50, we profit $0.50
                    position.current_pnl = (position.entry_credit - current_value) * position.quantity * 100
                    
                    if position.entry_credit > 0:
                        position.current_pnl_pct = position.current_pnl / (position.entry_credit * position.quantity * 100)
                    
            except Exception as e:
                logger.error(f"Error updating position {pos_id}: {e}")
        
        self._save_positions()
    
    def check_exit_signals(self) -> List[Dict]:
        """
        Check all positions for exit signals
        Returns list of positions that should be closed with reason
        """
        exits = []
        
        for pos_id, position in self.positions.items():
            if position.status != 'OPEN':
                continue
            
            exit_reason = None
            
            # Check profit target (50% of credit)
            if position.current_pnl >= position.profit_target:
                exit_reason = 'PROFIT_TARGET'
            
            # Check stop loss (2x credit)
            elif position.current_pnl <= position.stop_loss:
                exit_reason = 'STOP_LOSS'
            
            # Check DTE (close at 21 DTE)
            elif position.dte_remaining <= self.config.min_dte_exit:
                exit_reason = 'DTE_EXIT'
            
            if exit_reason:
                exits.append({
                    'position': position,
                    'reason': exit_reason
                })
        
        return exits
    
    def close_position(
        self, 
        position_id: str, 
        reason: str,
        realized_pnl: Optional[float] = None
    ):
        """Mark a position as closed"""
        if position_id in self.positions:
            position = self.positions[position_id]
            position.status = 'CLOSED'
            position.exit_reason = reason
            position.exit_date = datetime.now()
            position.realized_pnl = realized_pnl or position.current_pnl
            
            self._save_positions()
            logger.info(f"Closed position {position_id}: {reason}, P&L: ${position.realized_pnl:.2f}")
    
    def get_open_positions(self) -> List[TrackedPosition]:
        """Get all open positions"""
        return [p for p in self.positions.values() if p.status == 'OPEN']
    
    def get_position_count(self) -> int:
        """Get count of open positions"""
        return len(self.get_open_positions())
    
    def get_positions_by_symbol(self, symbol: str) -> List[TrackedPosition]:
        """Get open positions for a specific symbol"""
        return [
            p for p in self.positions.values() 
            if p.status == 'OPEN' and p.symbol == symbol
        ]
    
    def can_open_new_position(self, symbol: str) -> bool:
        """Check if we can open a new position"""
        # Check total position limit
        if self.get_position_count() >= self.config.max_positions:
            return False
        
        # Check per-symbol limit
        symbol_positions = len(self.get_positions_by_symbol(symbol))
        if symbol_positions >= self.config.max_positions_per_underlying:
            return False
        
        return True
    
    def get_portfolio_summary(self) -> Dict:
        """Get summary of all positions"""
        open_positions = self.get_open_positions()
        
        total_pnl = sum(p.current_pnl for p in open_positions)
        total_credit = sum(p.entry_credit * p.quantity * 100 for p in open_positions)
        
        return {
            'open_positions': len(open_positions),
            'total_pnl': total_pnl,
            'total_credit_at_risk': total_credit,
            'pnl_pct': total_pnl / total_credit if total_credit > 0 else 0,
            'positions': [p.to_dict() for p in open_positions]
        }
    
    def _get_spread_current_value(self, position: TrackedPosition) -> Optional[float]:
        """Get current market value to close a spread"""
        try:
            if position.strategy == 'iron_condor':
                # Get all 4 legs
                put_data = self.client.get_options_with_greeks(
                    position.symbol,
                    position.expiration,
                    [position.short_strike, position.long_strike],
                    'P'
                )
                call_data = self.client.get_options_with_greeks(
                    position.symbol,
                    position.expiration,
                    [position.call_short_strike, position.call_long_strike],
                    'C'
                )
                
                if len(put_data) < 2 or len(call_data) < 2:
                    return None
                
                # Calculate cost to close
                put_short = next((o for o in put_data if o['strike'] == position.short_strike), None)
                put_long = next((o for o in put_data if o['strike'] == position.long_strike), None)
                call_short = next((o for o in call_data if o['strike'] == position.call_short_strike), None)
                call_long = next((o for o in call_data if o['strike'] == position.call_long_strike), None)
                
                if not all([put_short, put_long, call_short, call_long]):
                    return None
                
                # To close: buy back shorts, sell longs
                # Value = (short_ask - long_bid) for each side
                put_value = (put_short.get('ask', 0) or 0) - (put_long.get('bid', 0) or 0)
                call_value = (call_short.get('ask', 0) or 0) - (call_long.get('bid', 0) or 0)
                
                return put_value + call_value
                
            else:
                # 2-leg spread
                right = 'P' if 'put' in position.strategy else 'C'
                
                data = self.client.get_options_with_greeks(
                    position.symbol,
                    position.expiration,
                    [position.short_strike, position.long_strike],
                    right
                )
                
                if len(data) < 2:
                    return None
                
                short_opt = next((o for o in data if o['strike'] == position.short_strike), None)
                long_opt = next((o for o in data if o['strike'] == position.long_strike), None)
                
                if not short_opt or not long_opt:
                    return None
                
                # Cost to close = buy back short (ask) - sell long (bid)
                return (short_opt.get('ask', 0) or 0) - (long_opt.get('bid', 0) or 0)
                
        except Exception as e:
            logger.error(f"Error getting spread value: {e}")
            return None
    
    def _save_positions(self):
        """Save positions to file"""
        try:
            data = {pid: pos.to_dict() for pid, pos in self.positions.items()}
            with open(self.data_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving positions: {e}")
    
    def _load_positions(self):
        """Load positions from file"""
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                    self.positions = {
                        pid: TrackedPosition.from_dict(pdata) 
                        for pid, pdata in data.items()
                    }
                logger.info(f"Loaded {len(self.positions)} positions from file")
        except Exception as e:
            logger.error(f"Error loading positions: {e}")
            self.positions = {}


def format_position_alert(position: TrackedPosition, action: str) -> str:
    """Format position update for Telegram"""
    if action == 'OPEN':
        return f"""
✅ POSITION OPENED

{position.strategy.upper().replace('_', ' ')} on {position.symbol}
📅 Expiration: {position.expiration}
💰 Credit: ${position.entry_credit:.2f} x {position.quantity}

Strikes: {position.short_strike}/{position.long_strike}
Target: ${position.profit_target:.2f}
Stop: ${position.stop_loss:.2f}
"""
    elif action == 'CLOSE':
        emoji = "🟢" if position.realized_pnl and position.realized_pnl > 0 else "🔴"
        return f"""
{emoji} POSITION CLOSED

{position.strategy.upper().replace('_', ' ')} on {position.symbol}
Reason: {position.exit_reason}

💰 Realized P&L: ${position.realized_pnl:.2f}
Days held: {(position.exit_date - position.entry_date).days if position.exit_date else 'N/A'}
"""
    else:  # UPDATE
        emoji = "🟢" if position.current_pnl > 0 else "🔴"
        return f"""
{emoji} POSITION UPDATE: {position.symbol}

Current P&L: ${position.current_pnl:.2f} ({position.current_pnl_pct:.1%})
DTE: {position.dte_remaining}
Value to close: ${position.current_value:.2f}
"""


def format_portfolio_summary(summary: Dict) -> str:
    """Format portfolio summary for Telegram"""
    emoji = "🟢" if summary['total_pnl'] > 0 else "🔴"
    
    lines = [
        f"📊 PORTFOLIO SUMMARY",
        f"",
        f"Open positions: {summary['open_positions']}",
        f"{emoji} Total P&L: ${summary['total_pnl']:.2f} ({summary['pnl_pct']:.1%})",
        f"Credit at risk: ${summary['total_credit_at_risk']:.2f}",
    ]
    
    if summary['positions']:
        lines.append("")
        lines.append("Positions:")
        for pos in summary['positions']:
            pnl = pos.get('current_pnl', 0)
            emoji = "🟢" if pnl > 0 else "🔴"
            lines.append(f"  {emoji} {pos['symbol']}: ${pnl:.2f}")
    
    return "\n".join(lines)
