"""
AMM (Automated Market Maker) for Prediction Markets

Implements LMSR (Logarithmic Market Scoring Rule) like Polymarket uses.
Provides instant liquidity for buying/selling YES/NO contracts.

LMSR Formula:
- Cost function: C(q_yes, q_no) = b * ln(exp(q_yes/b) + exp(q_no/b))
- Price of YES: p_yes = exp(q_yes/b) / (exp(q_yes/b) + exp(q_no/b))
- Cost to buy shares: C(new_state) - C(old_state)

Where:
- b = liquidity parameter (higher = more liquidity, less price impact)
- q_yes, q_no = shares outstanding
"""

import math
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from django.db import transaction

from .models import AMMPool, AMMTrade, Market, Position, Transaction, User
from .exceptions import TradingError, InsufficientFundsError, MarketNotActiveError


class AMMEngine:
    """
    Automated Market Maker using LMSR (Logarithmic Market Scoring Rule).
    """

    def __init__(self, market: Market):
        self.market = market
        self.pool = self._get_or_create_pool()

    def _get_or_create_pool(self) -> AMMPool:
        """Get existing pool or create one with default liquidity."""
        pool, created = AMMPool.objects.get_or_create(
            market=self.market,
            defaults={
                'liquidity_b': Decimal('100.00'),  # Default liquidity
                'yes_shares': Decimal('0.0000'),
                'no_shares': Decimal('0.0000'),
                'pool_balance': Decimal('0.00'),
                'fee_percentage': Decimal('0.0200'),  # 2% fee
            }
        )
        return pool

    @property
    def b(self) -> float:
        """Liquidity parameter as float for calculations."""
        return float(self.pool.liquidity_b)

    @property
    def q_yes(self) -> float:
        """YES shares outstanding."""
        return float(self.pool.yes_shares)

    @property
    def q_no(self) -> float:
        """NO shares outstanding."""
        return float(self.pool.no_shares)

    def _cost_function(self, q_yes: float, q_no: float) -> float:
        """
        LMSR cost function: C(q_yes, q_no) = b * ln(exp(q_yes/b) + exp(q_no/b))

        Uses log-sum-exp trick for numerical stability.
        """
        b = self.b
        if b <= 0:
            raise TradingError("Invalid liquidity parameter")

        # Log-sum-exp trick to prevent overflow
        max_val = max(q_yes / b, q_no / b)
        return b * (max_val + math.log(
            math.exp(q_yes / b - max_val) + math.exp(q_no / b - max_val)
        ))

    def get_yes_price(self) -> float:
        """
        Current price of YES shares (probability).
        p_yes = exp(q_yes/b) / (exp(q_yes/b) + exp(q_no/b))
        """
        b = self.b
        q_yes = self.q_yes
        q_no = self.q_no

        # Use softmax for numerical stability
        max_val = max(q_yes / b, q_no / b)
        exp_yes = math.exp(q_yes / b - max_val)
        exp_no = math.exp(q_no / b - max_val)

        return exp_yes / (exp_yes + exp_no)

    def get_no_price(self) -> float:
        """Current price of NO shares (probability)."""
        return 1.0 - self.get_yes_price()

    def get_prices_cents(self) -> tuple[int, int]:
        """Get current YES and NO prices in cents (1-99)."""
        yes_price = self.get_yes_price()
        yes_cents = max(1, min(99, round(yes_price * 100)))
        no_cents = 100 - yes_cents
        return yes_cents, no_cents

    def calculate_buy_cost(self, contract_type: str, quantity: int) -> tuple[float, float, float]:
        """
        Calculate cost to buy shares.

        Returns: (total_cost, avg_price_cents, price_after_cents)
        """
        if quantity <= 0:
            raise TradingError("Quantity must be positive")

        q_yes = self.q_yes
        q_no = self.q_no

        # Current cost
        cost_before = self._cost_function(q_yes, q_no)

        # New state after buying
        if contract_type == 'yes':
            new_q_yes = q_yes + quantity
            new_q_no = q_no
        else:
            new_q_yes = q_yes
            new_q_no = q_no + quantity

        # Cost after buying
        cost_after = self._cost_function(new_q_yes, new_q_no)

        # Total cost to buy
        total_cost = cost_after - cost_before

        # Average price per share
        avg_price = total_cost / quantity
        avg_price_cents = avg_price * 100

        # Price after trade
        b = self.b
        max_val = max(new_q_yes / b, new_q_no / b)
        exp_yes = math.exp(new_q_yes / b - max_val)
        exp_no = math.exp(new_q_no / b - max_val)

        if contract_type == 'yes':
            price_after = exp_yes / (exp_yes + exp_no)
        else:
            price_after = exp_no / (exp_yes + exp_no)

        price_after_cents = price_after * 100

        return total_cost, avg_price_cents, price_after_cents

    def calculate_sell_payout(self, contract_type: str, quantity: int) -> tuple[float, float, float]:
        """
        Calculate payout for selling shares.

        Returns: (total_payout, avg_price_cents, price_after_cents)
        """
        if quantity <= 0:
            raise TradingError("Quantity must be positive")

        q_yes = self.q_yes
        q_no = self.q_no

        # Check if enough shares exist to sell
        if contract_type == 'yes' and quantity > q_yes:
            raise TradingError(f"Cannot sell {quantity} YES shares, only {q_yes} exist")
        if contract_type == 'no' and quantity > q_no:
            raise TradingError(f"Cannot sell {quantity} NO shares, only {q_no} exist")

        # Current cost
        cost_before = self._cost_function(q_yes, q_no)

        # New state after selling
        if contract_type == 'yes':
            new_q_yes = q_yes - quantity
            new_q_no = q_no
        else:
            new_q_yes = q_yes
            new_q_no = q_no - quantity

        # Cost after selling
        cost_after = self._cost_function(new_q_yes, new_q_no)

        # Payout is the reduction in cost function
        total_payout = cost_before - cost_after

        # Average price per share
        avg_price = total_payout / quantity
        avg_price_cents = avg_price * 100

        # Price after trade
        b = self.b
        max_val = max(new_q_yes / b, new_q_no / b)
        exp_yes = math.exp(new_q_yes / b - max_val)
        exp_no = math.exp(new_q_no / b - max_val)

        if contract_type == 'yes':
            price_after = exp_yes / (exp_yes + exp_no)
        else:
            price_after = exp_no / (exp_yes + exp_no)

        price_after_cents = price_after * 100

        return total_payout, avg_price_cents, price_after_cents

    def calculate_shares_for_amount(self, contract_type: str, amount: Decimal) -> int:
        """
        Calculate how many shares you can buy for a given dollar amount.
        Uses binary search for precision.
        """
        amount_float = float(amount)
        if amount_float <= 0:
            return 0

        # Binary search for quantity
        low, high = 1, 10000  # Max 10k shares per trade
        best_qty = 0

        while low <= high:
            mid = (low + high) // 2
            try:
                cost, _, _ = self.calculate_buy_cost(contract_type, mid)
                if cost <= amount_float:
                    best_qty = mid
                    low = mid + 1
                else:
                    high = mid - 1
            except:
                high = mid - 1

        return best_qty

    @transaction.atomic
    def buy(self, user: User, contract_type: str, quantity: int) -> AMMTrade:
        """
        Execute a buy order against the AMM.

        Returns: AMMTrade record
        """
        if not self.market.is_trading_active:
            raise MarketNotActiveError("Market is not active for trading")

        if contract_type not in ['yes', 'no']:
            raise TradingError("Contract type must be 'yes' or 'no'")

        if quantity <= 0:
            raise TradingError("Quantity must be positive")

        # Calculate cost
        total_cost, avg_price_cents, price_after_cents = self.calculate_buy_cost(
            contract_type, quantity
        )

        # Add fee
        fee = total_cost * float(self.pool.fee_percentage)
        total_with_fee = total_cost + fee

        # Check user balance
        if Decimal(str(total_with_fee)) > user.available_balance:
            raise InsufficientFundsError(
                f"Insufficient funds. Need ${total_with_fee:.2f}, "
                f"have ${user.available_balance:.2f}"
            )

        # Get prices before trade
        yes_before, no_before = self.get_prices_cents()
        price_before = yes_before if contract_type == 'yes' else no_before

        # Deduct from user balance
        balance_before = user.balance
        user.balance -= Decimal(str(total_with_fee))
        user.save()

        # Update pool shares
        if contract_type == 'yes':
            self.pool.yes_shares += Decimal(str(quantity))
        else:
            self.pool.no_shares += Decimal(str(quantity))

        self.pool.pool_balance += Decimal(str(total_cost))
        self.pool.total_fees_collected += Decimal(str(fee))
        self.pool.save()

        # Update user position
        position, _ = Position.objects.get_or_create(
            user=user,
            market=self.market
        )

        if contract_type == 'yes':
            # Update average cost
            old_cost = float(position.yes_avg_cost) * position.yes_quantity
            new_cost = old_cost + (avg_price_cents * quantity)
            new_qty = position.yes_quantity + quantity
            position.yes_avg_cost = Decimal(str(new_cost / new_qty)) if new_qty > 0 else Decimal('0')
            position.yes_quantity = new_qty
        else:
            old_cost = float(position.no_avg_cost) * position.no_quantity
            new_cost = old_cost + (avg_price_cents * quantity)
            new_qty = position.no_quantity + quantity
            position.no_avg_cost = Decimal(str(new_cost / new_qty)) if new_qty > 0 else Decimal('0')
            position.no_quantity = new_qty

        position.save()

        # Update market prices
        yes_cents, no_cents = self.get_prices_cents()
        self.market.last_yes_price = yes_cents
        self.market.last_no_price = no_cents
        self.market.total_volume += quantity
        self.market.save()

        # Create trade record
        trade = AMMTrade.objects.create(
            pool=self.pool,
            user=user,
            side='buy',
            contract_type=contract_type,
            quantity=quantity,
            price_before=price_before,
            price_after=round(price_after_cents),
            avg_price=Decimal(str(avg_price_cents)),
            total_cost=Decimal(str(total_with_fee)),
            fee_amount=Decimal(str(fee))
        )

        # Create transaction record
        Transaction.objects.create(
            user=user,
            type=Transaction.Type.TRADE_BUY,
            amount=-Decimal(str(total_with_fee)),
            balance_before=balance_before,
            balance_after=user.balance,
            market=self.market,
            description=f"AMM Buy {quantity} {contract_type.upper()} @ {avg_price_cents:.1f}c"
        )

        # Broadcast update via WebSocket
        self._broadcast_update(trade)

        return trade

    @transaction.atomic
    def sell(self, user: User, contract_type: str, quantity: int) -> AMMTrade:
        """
        Execute a sell order against the AMM.
        User must have the shares in their position.

        Returns: AMMTrade record
        """
        if not self.market.is_trading_active:
            raise MarketNotActiveError("Market is not active for trading")

        if contract_type not in ['yes', 'no']:
            raise TradingError("Contract type must be 'yes' or 'no'")

        if quantity <= 0:
            raise TradingError("Quantity must be positive")

        # Check user position
        try:
            position = Position.objects.get(user=user, market=self.market)
        except Position.DoesNotExist:
            raise TradingError("You don't have any position in this market")

        if contract_type == 'yes' and position.yes_quantity < quantity:
            raise TradingError(
                f"Insufficient YES shares. Have {position.yes_quantity}, need {quantity}"
            )
        if contract_type == 'no' and position.no_quantity < quantity:
            raise TradingError(
                f"Insufficient NO shares. Have {position.no_quantity}, need {quantity}"
            )

        # Calculate payout
        total_payout, avg_price_cents, price_after_cents = self.calculate_sell_payout(
            contract_type, quantity
        )

        # Deduct fee from payout
        fee = total_payout * float(self.pool.fee_percentage)
        payout_after_fee = total_payout - fee

        # Get prices before trade
        yes_before, no_before = self.get_prices_cents()
        price_before = yes_before if contract_type == 'yes' else no_before

        # Add to user balance
        balance_before = user.balance
        user.balance += Decimal(str(payout_after_fee))
        user.save()

        # Update pool shares
        if contract_type == 'yes':
            self.pool.yes_shares -= Decimal(str(quantity))
        else:
            self.pool.no_shares -= Decimal(str(quantity))

        self.pool.pool_balance -= Decimal(str(total_payout))
        self.pool.total_fees_collected += Decimal(str(fee))
        self.pool.save()

        # Update user position
        if contract_type == 'yes':
            # Calculate realized P&L
            cost_basis = float(position.yes_avg_cost) * quantity
            realized = (avg_price_cents * quantity) - cost_basis
            position.realized_pnl += Decimal(str(realized / 100))
            position.yes_quantity -= quantity
            if position.yes_quantity == 0:
                position.yes_avg_cost = Decimal('0')
        else:
            cost_basis = float(position.no_avg_cost) * quantity
            realized = (avg_price_cents * quantity) - cost_basis
            position.realized_pnl += Decimal(str(realized / 100))
            position.no_quantity -= quantity
            if position.no_quantity == 0:
                position.no_avg_cost = Decimal('0')

        position.save()

        # Update market prices
        yes_cents, no_cents = self.get_prices_cents()
        self.market.last_yes_price = yes_cents
        self.market.last_no_price = no_cents
        self.market.total_volume += quantity
        self.market.save()

        # Create trade record
        trade = AMMTrade.objects.create(
            pool=self.pool,
            user=user,
            side='sell',
            contract_type=contract_type,
            quantity=quantity,
            price_before=price_before,
            price_after=round(price_after_cents),
            avg_price=Decimal(str(avg_price_cents)),
            total_cost=Decimal(str(payout_after_fee)),
            fee_amount=Decimal(str(fee))
        )

        # Create transaction record
        Transaction.objects.create(
            user=user,
            type=Transaction.Type.TRADE_SELL,
            amount=Decimal(str(payout_after_fee)),
            balance_before=balance_before,
            balance_after=user.balance,
            market=self.market,
            description=f"AMM Sell {quantity} {contract_type.upper()} @ {avg_price_cents:.1f}c"
        )

        # Broadcast update via WebSocket
        self._broadcast_update(trade)

        return trade

    @transaction.atomic
    def buy_with_amount(self, user: User, contract_type: str, amount: Decimal) -> AMMTrade:
        """
        Buy as many shares as possible with a given dollar amount.

        Returns: AMMTrade record
        """
        quantity = self.calculate_shares_for_amount(contract_type, amount)
        if quantity <= 0:
            raise TradingError(f"Amount ${amount} is too small to buy any shares")

        return self.buy(user, contract_type, quantity)

    def _broadcast_update(self, trade: AMMTrade = None):
        """Broadcast price and trade update via WebSocket."""
        try:
            from .broadcasts import broadcast_market_update, broadcast_amm_trade
            broadcast_market_update(self.market)
            if trade:
                broadcast_amm_trade(trade, self.market)
        except Exception:
            pass  # Don't fail trades if broadcast fails


def get_amm_prices(market: Market) -> dict:
    """
    Get current AMM prices for a market.

    Returns dict with yes_price, no_price (in cents).
    """
    try:
        engine = AMMEngine(market)
        yes_cents, no_cents = engine.get_prices_cents()
        return {
            'yes_price': yes_cents,
            'no_price': no_cents,
            'yes_probability': engine.get_yes_price(),
            'no_probability': engine.get_no_price(),
        }
    except Exception:
        return {
            'yes_price': market.last_yes_price,
            'no_price': market.last_no_price,
            'yes_probability': market.last_yes_price / 100,
            'no_probability': market.last_no_price / 100,
        }
