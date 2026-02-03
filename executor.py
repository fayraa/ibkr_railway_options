"""
Order Executor
Handles order placement and execution for spreads
"""
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime

from ib_insync import Contract, ComboLeg, LimitOrder, MarketOrder

from config import RiskConfig
from ibkr_client import IBKRClient
from spread_builder import CreditSpread, IronCondor, SpreadLeg

logger = logging.getLogger(__name__)


@dataclass
class OrderResult:
    """Result of order placement"""
    success: bool
    order_id: int
    status: str
    fill_price: Optional[float]
    commission: Optional[float]
    message: str
    timestamp: datetime


class OrderExecutor:
    """
    Executes spread orders on IBKR
    """
    
    def __init__(self, client: IBKRClient, config: RiskConfig):
        self.client = client
        self.config = config
    
    def execute_credit_spread(
        self, 
        spread: CreditSpread,
        quantity: int = 1,
        use_limit: bool = True,
        limit_offset: float = 0.02  # How much below mid to start
    ) -> OrderResult:
        """
        Execute a credit spread order
        
        Args:
            spread: CreditSpread to execute
            quantity: Number of contracts
            use_limit: Use limit order (vs market)
            limit_offset: Offset from mid price for limit
        
        Returns:
            OrderResult with execution details
        """
        try:
            # Validate position size
            max_contracts = self._calculate_max_contracts(spread.max_loss)
            if quantity > max_contracts:
                return OrderResult(
                    success=False,
                    order_id=0,
                    status='REJECTED',
                    fill_price=None,
                    commission=None,
                    message=f"Quantity {quantity} exceeds max {max_contracts} based on risk limit",
                    timestamp=datetime.now()
                )
            
            # Build combo contract
            combo = self._build_spread_combo(
                spread.short_leg, 
                spread.long_leg
            )
            
            if not combo:
                return OrderResult(
                    success=False,
                    order_id=0,
                    status='ERROR',
                    fill_price=None,
                    commission=None,
                    message="Failed to build combo contract",
                    timestamp=datetime.now()
                )
            
            # Calculate limit price
            # For credit spreads, we want to SELL the combo (receive credit)
            # In IBKR, selling a combo at a negative price = receiving credit
            if use_limit:
                limit_price = -(spread.credit - limit_offset)
                order = LimitOrder(
                    action='SELL',
                    totalQuantity=quantity,
                    lmtPrice=round(limit_price, 2)
                )
            else:
                order = MarketOrder(
                    action='SELL',
                    totalQuantity=quantity
                )
            
            # Place order
            trade = self.client.ib.placeOrder(combo, order)
            
            # Wait for fill (with timeout)
            self.client.ib.sleep(2)
            
            # Check status
            if trade.orderStatus.status == 'Filled':
                return OrderResult(
                    success=True,
                    order_id=trade.order.orderId,
                    status='FILLED',
                    fill_price=trade.orderStatus.avgFillPrice,
                    commission=sum(f.commission for f in trade.fills) if trade.fills else 0,
                    message=f"Order filled at {trade.orderStatus.avgFillPrice}",
                    timestamp=datetime.now()
                )
            elif trade.orderStatus.status in ['PreSubmitted', 'Submitted']:
                return OrderResult(
                    success=True,
                    order_id=trade.order.orderId,
                    status='PENDING',
                    fill_price=None,
                    commission=None,
                    message="Order submitted, waiting for fill",
                    timestamp=datetime.now()
                )
            else:
                return OrderResult(
                    success=False,
                    order_id=trade.order.orderId if trade.order else 0,
                    status=trade.orderStatus.status,
                    fill_price=None,
                    commission=None,
                    message=f"Order status: {trade.orderStatus.status}",
                    timestamp=datetime.now()
                )
                
        except Exception as e:
            logger.error(f"Error executing spread: {e}")
            return OrderResult(
                success=False,
                order_id=0,
                status='ERROR',
                fill_price=None,
                commission=None,
                message=str(e),
                timestamp=datetime.now()
            )
    
    def execute_iron_condor(
        self,
        condor: IronCondor,
        quantity: int = 1,
        use_limit: bool = True,
        limit_offset: float = 0.05
    ) -> OrderResult:
        """
        Execute an iron condor as a single 4-leg order
        """
        try:
            max_contracts = self._calculate_max_contracts(condor.max_loss)
            if quantity > max_contracts:
                return OrderResult(
                    success=False,
                    order_id=0,
                    status='REJECTED',
                    fill_price=None,
                    commission=None,
                    message=f"Quantity {quantity} exceeds max {max_contracts}",
                    timestamp=datetime.now()
                )
            
            # Build 4-leg combo
            combo = self._build_iron_condor_combo(condor)
            
            if not combo:
                return OrderResult(
                    success=False,
                    order_id=0,
                    status='ERROR',
                    fill_price=None,
                    commission=None,
                    message="Failed to build iron condor combo",
                    timestamp=datetime.now()
                )
            
            # Limit price (negative = credit)
            if use_limit:
                limit_price = -(condor.total_credit - limit_offset)
                order = LimitOrder(
                    action='SELL',
                    totalQuantity=quantity,
                    lmtPrice=round(limit_price, 2)
                )
            else:
                order = MarketOrder(action='SELL', totalQuantity=quantity)
            
            trade = self.client.ib.placeOrder(combo, order)
            self.client.ib.sleep(2)
            
            if trade.orderStatus.status == 'Filled':
                return OrderResult(
                    success=True,
                    order_id=trade.order.orderId,
                    status='FILLED',
                    fill_price=trade.orderStatus.avgFillPrice,
                    commission=sum(f.commission for f in trade.fills) if trade.fills else 0,
                    message=f"Iron condor filled at {trade.orderStatus.avgFillPrice}",
                    timestamp=datetime.now()
                )
            elif trade.orderStatus.status in ['PreSubmitted', 'Submitted']:
                return OrderResult(
                    success=True,
                    order_id=trade.order.orderId,
                    status='PENDING',
                    fill_price=None,
                    commission=None,
                    message="Order submitted",
                    timestamp=datetime.now()
                )
            else:
                return OrderResult(
                    success=False,
                    order_id=trade.order.orderId if trade.order else 0,
                    status=trade.orderStatus.status,
                    fill_price=None,
                    commission=None,
                    message=f"Order status: {trade.orderStatus.status}",
                    timestamp=datetime.now()
                )
                
        except Exception as e:
            logger.error(f"Error executing iron condor: {e}")
            return OrderResult(
                success=False,
                order_id=0,
                status='ERROR',
                fill_price=None,
                commission=None,
                message=str(e),
                timestamp=datetime.now()
            )
    
    def close_spread(
        self,
        spread: CreditSpread,
        quantity: int = 1
    ) -> OrderResult:
        """
        Close an existing spread position (buy back the combo)
        """
        try:
            combo = self._build_spread_combo(spread.short_leg, spread.long_leg)
            if not combo:
                return OrderResult(
                    success=False,
                    order_id=0,
                    status='ERROR',
                    fill_price=None,
                    commission=None,
                    message="Failed to build combo",
                    timestamp=datetime.now()
                )
            
            # To close a credit spread, we BUY the combo back
            order = MarketOrder(action='BUY', totalQuantity=quantity)
            
            trade = self.client.ib.placeOrder(combo, order)
            self.client.ib.sleep(2)
            
            return OrderResult(
                success=trade.orderStatus.status in ['Filled', 'PreSubmitted', 'Submitted'],
                order_id=trade.order.orderId if trade.order else 0,
                status=trade.orderStatus.status,
                fill_price=trade.orderStatus.avgFillPrice if trade.orderStatus.status == 'Filled' else None,
                commission=sum(f.commission for f in trade.fills) if trade.fills else None,
                message=f"Close order: {trade.orderStatus.status}",
                timestamp=datetime.now()
            )
            
        except Exception as e:
            logger.error(f"Error closing spread: {e}")
            return OrderResult(
                success=False,
                order_id=0,
                status='ERROR',
                fill_price=None,
                commission=None,
                message=str(e),
                timestamp=datetime.now()
            )
    
    def _build_spread_combo(
        self, 
        short_leg: SpreadLeg, 
        long_leg: SpreadLeg
    ) -> Optional[Contract]:
        """Build a combo contract for a 2-leg spread"""
        try:
            # Qualify both contracts
            self.client.ib.qualifyContracts(short_leg.contract)
            self.client.ib.qualifyContracts(long_leg.contract)
            
            # Create combo legs
            leg1 = ComboLeg(
                conId=short_leg.contract.conId,
                ratio=1,
                action='SELL',
                exchange='SMART'
            )
            leg2 = ComboLeg(
                conId=long_leg.contract.conId,
                ratio=1,
                action='BUY',
                exchange='SMART'
            )
            
            # Create bag contract
            bag = Contract()
            bag.symbol = short_leg.contract.symbol
            bag.secType = 'BAG'
            bag.currency = 'USD'
            bag.exchange = 'SMART'
            bag.comboLegs = [leg1, leg2]
            
            return bag
            
        except Exception as e:
            logger.error(f"Error building spread combo: {e}")
            return None
    
    def _build_iron_condor_combo(self, condor: IronCondor) -> Optional[Contract]:
        """Build a combo contract for a 4-leg iron condor"""
        try:
            # Qualify all contracts
            for leg in [condor.put_short_leg, condor.put_long_leg, 
                       condor.call_short_leg, condor.call_long_leg]:
                self.client.ib.qualifyContracts(leg.contract)
            
            # Create combo legs
            legs = [
                ComboLeg(
                    conId=condor.put_short_leg.contract.conId,
                    ratio=1,
                    action='SELL',
                    exchange='SMART'
                ),
                ComboLeg(
                    conId=condor.put_long_leg.contract.conId,
                    ratio=1,
                    action='BUY',
                    exchange='SMART'
                ),
                ComboLeg(
                    conId=condor.call_short_leg.contract.conId,
                    ratio=1,
                    action='SELL',
                    exchange='SMART'
                ),
                ComboLeg(
                    conId=condor.call_long_leg.contract.conId,
                    ratio=1,
                    action='BUY',
                    exchange='SMART'
                )
            ]
            
            bag = Contract()
            bag.symbol = condor.symbol
            bag.secType = 'BAG'
            bag.currency = 'USD'
            bag.exchange = 'SMART'
            bag.comboLegs = legs
            
            return bag
            
        except Exception as e:
            logger.error(f"Error building iron condor combo: {e}")
            return None
    
    def _calculate_max_contracts(self, max_loss_per_contract: float) -> int:
        """Calculate max contracts based on risk limit"""
        if max_loss_per_contract <= 0:
            return 0
        
        # Each contract = 100 shares
        max_loss_per_contract_actual = max_loss_per_contract * 100
        
        return max(1, int(self.config.max_risk_per_trade / max_loss_per_contract_actual))
