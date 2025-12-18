"""
AMM Engine using Logarithmic Market Scoring Rule (LMSR).

LMSR provides automatic liquidity for prediction markets. It always
provides quotes for buying/selling and adjusts prices based on demand.

Key formulas:
- Cost function: C(q) = b * ln(e^(q_yes/b) + e^(q_no/b))
- Price: P_yes = e^(q_yes/b) / (e^(q_yes/b) + e^(q_no/b))
- YES + NO prices always sum to 100 cents
"""

import math
from decimal import Decimal
from django.db import transaction

from .models import Market, AMMPool, AMMTrade, Position, Transaction
from .exceptions import (
    TradingError,
    InsufficientFundsError,
    InsufficientPositionError,
    MarketNotActiveError,
    InsufficientLiquidityError,
)


class AMMEngine:
    """Engine for executing trades against the LMSR AMM."""

    def __init__(self, market: Market):
        self.market = market
        self.pool = self._get_or_create_pool()

    def _get_or_create_pool(self) -> AMMPool:
        """Get existing pool or create new one for the market."""
        pool, created = AMMPool.objects.get_or_create(
            market=self.market,
            defaults={
                'liquidity_b': Decimal('100.00'),
                'yes_shares': Decimal('0'),
                'no_shares': Decimal('0'),
            }
        )
        return pool

    def _cost_function(self, yes_shares: float, no_shares: float) -> float:
        """
        LMSR cost function.
        C(q) = b * ln(e^(q_yes/b) + e^(q_no/b))
        """
        b = float(self.pool.liquidity_b)
        # Use log-sum-exp trick for numerical stability
        max_val = max(yes_shares / b, no_shares / b)
        return b * (max_val + math.log(
            math.exp(yes_shares / b - max_val) +
            math.exp(no_shares / b - max_val)
        ))

    def get_price(self, contract_type: str) -> int:
        """
        Get current price for a contract type in cents (1-99).
        Price = e^(q/b) / (e^(q_yes/b) + e^(q_no/b))
        """
        b = float(self.pool.liquidity_b)
        yes_shares = float(self.pool.yes_shares)
        no_shares = float(self.pool.no_shares)

        # Use log-sum-exp trick for numerical stability
        max_val = max(yes_shares / b, no_shares / b)
        exp_yes = math.exp(yes_shares / b - max_val)
        exp_no = math.exp(no_shares / b - max_val)
        total = exp_yes + exp_no

        if contract_type == 'yes':
            price = exp_yes / total
        else:
            price = exp_no / total

        # Convert to cents, ensure within 1-99 range
        price_cents = int(round(price * 100))
        return max(1, min(99, price_cents))

    def get_prices(self) -> dict:
        """Get current prices for both YES and NO contracts."""
        yes_price = self.get_price('yes')
        no_price = 100 - yes_price  # Ensure they sum to 100
        return {
            'yes': yes_price,
            'no': no_price,
        }

    def get_buy_cost(self, contract_type: str, quantity: int) -> Decimal:
        """
        Calculate cost to buy N contracts.
        Cost = C(new_state) - C(current_state)

        In LMSR, each contract pays $1 if it wins. The cost function
        gives the total cost in dollars.
        """
        yes_shares = float(self.pool.yes_shares)
        no_shares = float(self.pool.no_shares)

        current_cost = self._cost_function(yes_shares, no_shares)

        if contract_type == 'yes':
            new_cost = self._cost_function(yes_shares + quantity, no_shares)
        else:
            new_cost = self._cost_function(yes_shares, no_shares + quantity)

        # LMSR cost is in dollars (b determines scale)
        cost_dollars = new_cost - current_cost
        return Decimal(str(cost_dollars)).quantize(Decimal('0.01'))

    def get_sell_payout(self, contract_type: str, quantity: int) -> Decimal:
        """
        Calculate payout for selling N contracts.
        Payout = C(current_state) - C(new_state)

        Returns the amount in dollars the user receives for selling.
        """
        yes_shares = float(self.pool.yes_shares)
        no_shares = float(self.pool.no_shares)

        current_cost = self._cost_function(yes_shares, no_shares)

        if contract_type == 'yes':
            new_cost = self._cost_function(yes_shares - quantity, no_shares)
        else:
            new_cost = self._cost_function(yes_shares, no_shares - quantity)

        # LMSR payout is in dollars
        payout_dollars = current_cost - new_cost
        return Decimal(str(payout_dollars)).quantize(Decimal('0.01'))

    def get_quote(self, side: str, contract_type: str, quantity: int) -> dict:
        """
        Get a quote for a trade without executing it.
        Returns estimated cost/payout and price impact.
        """
        price_before = self.get_price(contract_type)

        if side == 'buy':
            cost = self.get_buy_cost(contract_type, quantity)
            fee = cost * self.pool.fee_percentage
            total = cost + fee
            avg_price = (cost * 100 / quantity) if quantity > 0 else Decimal('0')
        else:  # sell
            payout = self.get_sell_payout(contract_type, quantity)
            fee = payout * self.pool.fee_percentage
            total = payout - fee
            avg_price = (payout * 100 / quantity) if quantity > 0 else Decimal('0')

        # Simulate price after trade
        yes_shares = float(self.pool.yes_shares)
        no_shares = float(self.pool.no_shares)

        if side == 'buy':
            if contract_type == 'yes':
                yes_shares += quantity
            else:
                no_shares += quantity
        else:
            if contract_type == 'yes':
                yes_shares -= quantity
            else:
                no_shares -= quantity

        # Calculate simulated price after
        b = float(self.pool.liquidity_b)
        max_val = max(yes_shares / b, no_shares / b)
        exp_yes = math.exp(yes_shares / b - max_val)
        exp_no = math.exp(no_shares / b - max_val)
        total_exp = exp_yes + exp_no

        if contract_type == 'yes':
            price_after = int(round(exp_yes / total_exp * 100))
        else:
            price_after = int(round(exp_no / total_exp * 100))
        price_after = max(1, min(99, price_after))

        return {
            'side': side,
            'contract_type': contract_type,
            'quantity': quantity,
            'price_before': price_before,
            'price_after': price_after,
            'price_impact': price_after - price_before,
            'avg_price': float(avg_price),
            'subtotal': float(cost if side == 'buy' else payout),
            'fee': float(fee),
            'total': float(total),
        }

    @transaction.atomic
    def execute_trade(
        self,
        user,
        side: str,
        contract_type: str,
        quantity: int
    ) -> AMMTrade:
        """
        Execute a trade against the AMM.

        Args:
            user: The user executing the trade
            side: 'buy' or 'sell'
            contract_type: 'yes' or 'no'
            quantity: Number of contracts

        Returns:
            AMMTrade record
        """
        # Validate market is active
        if not self.market.is_trading_active:
            raise MarketNotActiveError("Market is not active for trading")

        if not self.market.amm_enabled:
            raise TradingError("AMM is not enabled for this market")

        if quantity <= 0:
            raise TradingError("Quantity must be positive")

        # Lock records for update
        pool = AMMPool.objects.select_for_update().get(pk=self.pool.pk)
        user = user.__class__.objects.select_for_update().get(pk=user.pk)

        price_before = self.get_price(contract_type)

        if side == 'buy':
            return self._execute_buy(user, pool, contract_type, quantity, price_before)
        else:
            return self._execute_sell(user, pool, contract_type, quantity, price_before)

    def _execute_buy(self, user, pool, contract_type: str, quantity: int, price_before: int) -> AMMTrade:
        """Execute a buy trade against the AMM."""
        # Calculate cost
        cost = self.get_buy_cost(contract_type, quantity)
        fee = cost * pool.fee_percentage
        total_cost = cost + fee

        # Check user balance
        if user.available_balance < total_cost:
            raise InsufficientFundsError(
                f"Insufficient funds. Need ${total_cost:.2f}, have ${user.available_balance:.2f}"
            )

        # Deduct from user balance
        balance_before = user.balance
        user.balance -= total_cost
        user.save()

        # Update pool state
        if contract_type == 'yes':
            pool.yes_shares += quantity
        else:
            pool.no_shares += quantity

        pool.pool_balance += cost
        pool.total_fees_collected += fee
        pool.save()

        # Calculate average price and price after
        avg_price = (cost * 100 / quantity) if quantity > 0 else Decimal('0')
        price_after = self.get_price(contract_type)

        # Update user position
        position, _ = Position.objects.get_or_create(
            user=user,
            market=self.market
        )
        if contract_type == 'yes':
            # Update average cost
            old_qty = position.yes_quantity
            old_cost = position.yes_avg_cost * old_qty
            new_total_cost = old_cost + (avg_price * quantity)
            new_total_qty = old_qty + quantity
            position.yes_quantity = new_total_qty
            position.yes_avg_cost = new_total_cost / new_total_qty if new_total_qty > 0 else Decimal('0')
        else:
            old_qty = position.no_quantity
            old_cost = position.no_avg_cost * old_qty
            new_total_cost = old_cost + (avg_price * quantity)
            new_total_qty = old_qty + quantity
            position.no_quantity = new_total_qty
            position.no_avg_cost = new_total_cost / new_total_qty if new_total_qty > 0 else Decimal('0')
        position.save()

        # Update market prices
        self.market.last_yes_price = self.get_price('yes')
        self.market.last_no_price = 100 - self.market.last_yes_price
        self.market.total_volume += quantity
        self.market.save()

        # Create trade record
        trade = AMMTrade.objects.create(
            pool=pool,
            user=user,
            side='buy',
            contract_type=contract_type,
            quantity=quantity,
            price_before=price_before,
            price_after=price_after,
            avg_price=avg_price,
            total_cost=total_cost,
            fee_amount=fee,
        )

        # Create transaction record
        Transaction.objects.create(
            user=user,
            type=Transaction.Type.TRADE_BUY,
            amount=-total_cost,
            balance_before=balance_before,
            balance_after=user.balance,
            market=self.market,
            description=f"Bought {quantity} {contract_type.upper()} @ {avg_price:.1f}c via AMM"
        )

        return trade

    def _execute_sell(self, user, pool, contract_type: str, quantity: int, price_before: int) -> AMMTrade:
        """Execute a sell trade against the AMM."""
        # Check user position
        position = Position.objects.filter(
            user=user,
            market=self.market
        ).first()

        if not position:
            raise InsufficientPositionError("No position to sell")

        if contract_type == 'yes':
            if position.yes_quantity < quantity:
                raise InsufficientPositionError(
                    f"Insufficient YES contracts. Have {position.yes_quantity}, want to sell {quantity}"
                )
        else:
            if position.no_quantity < quantity:
                raise InsufficientPositionError(
                    f"Insufficient NO contracts. Have {position.no_quantity}, want to sell {quantity}"
                )

        # Calculate payout
        payout = self.get_sell_payout(contract_type, quantity)
        fee = payout * pool.fee_percentage
        net_payout = payout - fee

        # Update pool state
        if contract_type == 'yes':
            pool.yes_shares -= quantity
        else:
            pool.no_shares -= quantity

        pool.pool_balance -= payout
        pool.total_fees_collected += fee
        pool.save()

        # Credit user balance
        balance_before = user.balance
        user.balance += net_payout
        user.save()

        # Calculate average price and price after
        avg_price = (payout * 100 / quantity) if quantity > 0 else Decimal('0')
        price_after = self.get_price(contract_type)

        # Update user position
        if contract_type == 'yes':
            # Calculate realized P&L
            cost_basis = position.yes_avg_cost * quantity
            sale_proceeds = payout * 100  # Convert to cents
            realized_pnl = (sale_proceeds - cost_basis) / 100  # Back to dollars
            position.realized_pnl += realized_pnl
            position.yes_quantity -= quantity
        else:
            cost_basis = position.no_avg_cost * quantity
            sale_proceeds = payout * 100
            realized_pnl = (sale_proceeds - cost_basis) / 100
            position.realized_pnl += realized_pnl
            position.no_quantity -= quantity
        position.save()

        # Update market prices
        self.market.last_yes_price = self.get_price('yes')
        self.market.last_no_price = 100 - self.market.last_yes_price
        self.market.total_volume += quantity
        self.market.save()

        # Create trade record
        trade = AMMTrade.objects.create(
            pool=pool,
            user=user,
            side='sell',
            contract_type=contract_type,
            quantity=quantity,
            price_before=price_before,
            price_after=price_after,
            avg_price=avg_price,
            total_cost=net_payout,
            fee_amount=fee,
        )

        # Create transaction record
        Transaction.objects.create(
            user=user,
            type=Transaction.Type.TRADE_SELL,
            amount=net_payout,
            balance_before=balance_before,
            balance_after=user.balance,
            market=self.market,
            description=f"Sold {quantity} {contract_type.upper()} @ {avg_price:.1f}c via AMM"
        )

        return trade
