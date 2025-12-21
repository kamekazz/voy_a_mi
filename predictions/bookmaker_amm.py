"""
Bookmaker-Style AMM for Prediction Markets

This AMM is designed to MAKE MONEY like a traditional bookmaker:
1. Vigorish (vig): Prices sum to MORE than 100% (e.g., 52/52 = 104%)
2. Position Limits: Cap maximum loss on any outcome
3. Balanced Book: Encourage bets that balance exposure
4. Dynamic Pricing: Adjust odds based on exposure

Key Concept - Maximum Loss Cap:
- Pool has a fixed "max_loss" it will accept (e.g., $100)
- Every trade is evaluated: "If this outcome wins, what do I lose?"
- Reject trades that would push loss beyond the cap
"""

import math
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from django.db import transaction

from .models import AMMPool, AMMTrade, Market, Position, Transaction, User
from .exceptions import TradingError, InsufficientFundsError, MarketNotActiveError


class BookmakerAMM:
    """
    Bookmaker-style AMM that guarantees bounded losses and profits from vig.
    """

    # Configuration - Tune these for profitability!
    # With these settings, max loss is roughly: MAX_IMBALANCE * (1 - avg_price/100)
    # E.g., 50 shares at 52c each means exposure of 50 * $0.48 = $24 max loss
    DEFAULT_VIG = Decimal('0.05')  # 5% vig (prices sum to ~105%)
    DEFAULT_MAX_LOSS = Decimal('200.00')  # Max loss capped at $200 per outcome
    DEFAULT_FEE = Decimal('0.02')  # 2% transaction fee
    DEFAULT_MAX_IMBALANCE = 200  # Max 200 shares imbalance (allows ~$100 bets)

    def __init__(self, market: Market):
        self.market = market
        self.pool = self._get_or_create_pool()

    def _get_or_create_pool(self) -> AMMPool:
        """Get existing pool or create one."""
        pool, created = AMMPool.objects.get_or_create(
            market=self.market,
            defaults={
                'liquidity_b': Decimal('100.00'),
                'yes_shares': Decimal('0.0000'),
                'no_shares': Decimal('0.0000'),
                'pool_balance': Decimal('0.00'),
                'fee_percentage': self.DEFAULT_FEE,
            }
        )
        return pool

    @property
    def vig(self) -> Decimal:
        """Vigorish percentage (profit margin)."""
        return self.DEFAULT_VIG

    @property
    def max_loss(self) -> Decimal:
        """Maximum loss the pool will accept on any outcome."""
        return self.DEFAULT_MAX_LOSS

    @property
    def fee(self) -> Decimal:
        """Transaction fee percentage."""
        return self.pool.fee_percentage

    @property
    def max_imbalance(self) -> int:
        """Maximum allowed imbalance between YES and NO shares."""
        return self.DEFAULT_MAX_IMBALANCE

    def get_fair_probability(self) -> float:
        """
        Get fair YES probability based on current positions.
        Uses the imbalance of positions to determine probability.
        """
        yes_shares = float(self.pool.yes_shares)
        no_shares = float(self.pool.no_shares)
        total = yes_shares + no_shares

        if total == 0:
            return 0.5  # Start at 50/50

        # More YES bets = higher YES price (lower implied probability for new buyers)
        # This encourages balancing
        return 0.5 + (yes_shares - no_shares) / (2 * max(total, 100))

    def get_prices_with_vig(self) -> tuple[int, int]:
        """
        Get YES and NO prices including DYNAMIC vig.

        Key insight: To guarantee profit, we need balanced books.
        - If YES has more exposure, make NO more expensive (discourage)
        - If NO has more exposure, make YES more expensive (discourage)
        - Base vig is always applied to both sides

        Returns: (yes_price_cents, no_price_cents)
        """
        yes_shares = float(self.pool.yes_shares)
        no_shares = float(self.pool.no_shares)
        total_shares = yes_shares + no_shares

        # Base price is 50/50
        base_yes = 50
        base_no = 50

        # Base vig (5%) split between both sides = 2.5c each
        base_vig = float(self.vig) * 100 / 2  # 2.5c

        if total_shares > 0:
            # Imbalance factor: how much one side exceeds the other
            imbalance = (yes_shares - no_shares) / max(total_shares, 10)

            # Dynamic vig: the side with MORE exposure gets HIGHER price
            # (to discourage further bets on that side)
            # The side with LESS exposure gets LOWER price
            # (to encourage balancing bets)

            # Imbalance adjustment: up to 10c swing based on imbalance
            adjustment = imbalance * 10

            # YES price: base + vig + adjustment (higher if YES has more exposure)
            yes_price = base_yes + base_vig + adjustment

            # NO price: base + vig - adjustment (lower if YES has more exposure)
            no_price = base_no + base_vig - adjustment
        else:
            # No exposure yet - use base vig only
            yes_price = base_yes + base_vig
            no_price = base_no + base_vig

        # Clamp to 1-99
        yes_cents = max(1, min(99, round(yes_price)))
        no_cents = max(1, min(99, round(no_price)))

        return yes_cents, no_cents

    def get_display_prices(self) -> tuple[int, int]:
        """
        Get display prices that sum to 100 (for UI).
        This is the fair probability without vig.
        """
        fair_prob = self.get_fair_probability()
        yes_cents = max(1, min(99, round(fair_prob * 100)))
        no_cents = 100 - yes_cents
        return yes_cents, no_cents

    def calculate_exposure(self) -> dict:
        """
        Calculate current exposure (potential loss on each outcome).

        Returns dict with:
        - money_collected: Total money received from all bets
        - yes_payout: What we'd pay if YES wins
        - no_payout: What we'd pay if NO wins
        - yes_exposure: Loss if YES wins (payout - collected)
        - no_exposure: Loss if NO wins (payout - collected)
        """
        money_collected = float(self.pool.pool_balance)
        yes_shares = float(self.pool.yes_shares)
        no_shares = float(self.pool.no_shares)

        # If YES wins, we pay $1 per YES share
        yes_payout = yes_shares
        # If NO wins, we pay $1 per NO share
        no_payout = no_shares

        # Exposure is potential loss (negative = profit)
        yes_exposure = yes_payout - money_collected
        no_exposure = no_payout - money_collected

        return {
            'money_collected': money_collected,
            'yes_payout': yes_payout,
            'no_payout': no_payout,
            'yes_exposure': yes_exposure,
            'no_exposure': no_exposure,
            'max_exposure': max(yes_exposure, no_exposure),
        }

    def can_accept_bet(self, contract_type: str, quantity: int, cost: float) -> tuple[bool, str]:
        """
        Check if we can accept this bet without exceeding limits.

        Checks:
        1. Max loss cap: Don't exceed maximum exposure on any outcome
        2. Imbalance limit: Keep YES and NO shares roughly balanced

        Returns: (can_accept, reason)
        """
        yes_shares = float(self.pool.yes_shares)
        no_shares = float(self.pool.no_shares)
        exposure = self.calculate_exposure()
        new_money = exposure['money_collected'] + cost

        # Check imbalance limit
        if contract_type == 'yes':
            new_yes = yes_shares + quantity
            new_imbalance = new_yes - no_shares
            if new_imbalance > self.max_imbalance:
                return False, (
                    f"Would create too much imbalance ({new_imbalance:.0f} shares). "
                    f"Max allowed: {self.max_imbalance}. Consider betting NO to balance."
                )
        else:
            new_no = no_shares + quantity
            new_imbalance = new_no - yes_shares
            if new_imbalance > self.max_imbalance:
                return False, (
                    f"Would create too much imbalance ({new_imbalance:.0f} shares). "
                    f"Max allowed: {self.max_imbalance}. Consider betting YES to balance."
                )

        # Check max loss cap
        if contract_type == 'yes':
            new_yes_payout = exposure['yes_payout'] + quantity
            new_yes_exposure = new_yes_payout - new_money

            if new_yes_exposure > float(self.max_loss):
                return False, f"Would exceed max loss. Current YES exposure: ${exposure['yes_exposure']:.2f}, max: ${self.max_loss}"
        else:
            new_no_payout = exposure['no_payout'] + quantity
            new_no_exposure = new_no_payout - new_money

            if new_no_exposure > float(self.max_loss):
                return False, f"Would exceed max loss. Current NO exposure: ${exposure['no_exposure']:.2f}, max: ${self.max_loss}"

        return True, "OK"

    def calculate_buy_cost(self, contract_type: str, quantity: int) -> dict:
        """
        Calculate cost to buy shares WITH vig.

        Returns dict with:
        - base_cost: Cost without fees
        - fee: Transaction fee
        - total_cost: Total cost to user
        - price_cents: Price per share in cents
        - can_accept: Whether pool can accept this bet
        - reject_reason: Why bet was rejected (if applicable)
        """
        if quantity <= 0:
            raise TradingError("Quantity must be positive")

        # Get price with vig
        yes_price, no_price = self.get_prices_with_vig()
        price_cents = yes_price if contract_type == 'yes' else no_price

        # Calculate cost
        base_cost = (price_cents * quantity) / 100
        fee = base_cost * float(self.fee)
        total_cost = base_cost + fee

        # Check if we can accept this bet
        can_accept, reason = self.can_accept_bet(contract_type, quantity, base_cost)

        return {
            'base_cost': base_cost,
            'fee': fee,
            'total_cost': total_cost,
            'price_cents': price_cents,
            'can_accept': can_accept,
            'reject_reason': reason if not can_accept else None,
        }

    def calculate_shares_for_amount(self, contract_type: str, amount: Decimal) -> int:
        """
        Calculate how many shares you can buy for a given dollar amount.
        Takes into account the vig and fees.
        """
        amount_float = float(amount)
        if amount_float <= 0:
            return 0

        # Get price with vig
        yes_price, no_price = self.get_prices_with_vig()
        price_cents = yes_price if contract_type == 'yes' else no_price

        # Price includes vig, but we also need to account for fee
        # total_cost = (price * qty / 100) * (1 + fee)
        # So: amount = (price * qty / 100) * (1 + fee)
        # qty = amount / (price / 100 * (1 + fee))
        fee_factor = 1 + float(self.fee)
        price_dollars = price_cents / 100

        quantity = int(amount_float / (price_dollars * fee_factor))
        return max(0, quantity)

    def max_fillable_quantity(self, contract_type: str) -> int:
        """
        Calculate the maximum quantity the AMM can fill for a given contract type.

        Returns the max shares that can be bought before hitting:
        1. Imbalance limit
        2. Max loss limit
        """
        yes_shares = float(self.pool.yes_shares)
        no_shares = float(self.pool.no_shares)
        exposure = self.calculate_exposure()

        # Constraint 1: Imbalance limit
        # For YES: (yes_shares + qty) - no_shares <= max_imbalance
        # So: qty <= max_imbalance + no_shares - yes_shares
        if contract_type == 'yes':
            imbalance_limit = self.max_imbalance + no_shares - yes_shares
        else:
            imbalance_limit = self.max_imbalance + yes_shares - no_shares

        # Constraint 2: Max loss limit
        # For YES: (yes_payout + qty) - (money + cost) <= max_loss
        # Approximation: cost ≈ qty * price / 100
        # So: yes_payout + qty - money - qty*price/100 <= max_loss
        # qty * (1 - price/100) <= max_loss - yes_payout + money
        # qty <= (max_loss - current_exposure) / (1 - price/100)
        yes_price, no_price = self.get_prices_with_vig()

        if contract_type == 'yes':
            current_exposure = exposure['yes_exposure']
            price_cents = yes_price
        else:
            current_exposure = exposure['no_exposure']
            price_cents = no_price

        remaining_loss_capacity = float(self.max_loss) - current_exposure
        price_factor = 1 - (price_cents / 100)

        if price_factor <= 0:
            loss_limit = 0
        else:
            loss_limit = remaining_loss_capacity / price_factor

        # Return the minimum of both constraints (can't exceed either)
        max_qty = int(min(imbalance_limit, loss_limit))
        return max(0, max_qty)

    def calculate_sell_payout(self, contract_type: str, quantity: int) -> dict:
        """
        Calculate payout for selling shares.
        Selling reduces our exposure, so we pay fair price minus vig.

        Returns dict with payout info.
        """
        if quantity <= 0:
            raise TradingError("Quantity must be positive")

        # Sellers get worse price (fair - vig)
        fair_prob = self.get_fair_probability()
        if contract_type == 'yes':
            price = fair_prob * (1 - float(self.vig) / 2) * 100
        else:
            price = (1 - fair_prob) * (1 - float(self.vig) / 2) * 100

        price_cents = max(1, min(99, round(price)))
        base_payout = (price_cents * quantity) / 100
        fee = base_payout * float(self.fee)
        net_payout = base_payout - fee

        return {
            'base_payout': base_payout,
            'fee': fee,
            'net_payout': net_payout,
            'price_cents': price_cents,
        }

    @transaction.atomic
    def buy(self, user: User, contract_type: str, quantity: int) -> AMMTrade:
        """
        Execute a buy order.
        """
        if not self.market.is_trading_active:
            raise MarketNotActiveError("Market is not active for trading")

        if contract_type not in ['yes', 'no']:
            raise TradingError("Contract type must be 'yes' or 'no'")

        if quantity <= 0:
            raise TradingError("Quantity must be positive")

        # Calculate cost
        cost_info = self.calculate_buy_cost(contract_type, quantity)

        # Check if we can accept
        if not cost_info['can_accept']:
            raise TradingError(cost_info['reject_reason'])

        total_cost = Decimal(str(cost_info['total_cost']))

        # Check user balance
        if total_cost > user.available_balance:
            raise InsufficientFundsError(
                f"Insufficient funds. Need ${total_cost:.2f}, have ${user.available_balance:.2f}"
            )

        # Get price before
        yes_before, no_before = self.get_display_prices()
        price_before = yes_before if contract_type == 'yes' else no_before

        # Deduct from user
        balance_before = user.balance
        user.balance -= total_cost
        user.save()

        # Update pool
        if contract_type == 'yes':
            self.pool.yes_shares += Decimal(str(quantity))
        else:
            self.pool.no_shares += Decimal(str(quantity))

        self.pool.pool_balance += Decimal(str(cost_info['base_cost']))
        self.pool.total_fees_collected += Decimal(str(cost_info['fee']))
        self.pool.save()

        # Update position
        position, _ = Position.objects.get_or_create(user=user, market=self.market)

        if contract_type == 'yes':
            old_cost = float(position.yes_avg_cost) * position.yes_quantity
            new_cost = old_cost + (cost_info['price_cents'] * quantity)
            new_qty = position.yes_quantity + quantity
            position.yes_avg_cost = Decimal(str(new_cost / new_qty)) if new_qty > 0 else Decimal('0')
            position.yes_quantity = new_qty
        else:
            old_cost = float(position.no_avg_cost) * position.no_quantity
            new_cost = old_cost + (cost_info['price_cents'] * quantity)
            new_qty = position.no_quantity + quantity
            position.no_avg_cost = Decimal(str(new_cost / new_qty)) if new_qty > 0 else Decimal('0')
            position.no_quantity = new_qty

        position.save()

        # Update market prices
        yes_after, no_after = self.get_display_prices()
        self.market.last_yes_price = yes_after
        self.market.last_no_price = no_after
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
            price_after=yes_after if contract_type == 'yes' else no_after,
            avg_price=Decimal(str(cost_info['price_cents'])),
            total_cost=total_cost,
            fee_amount=Decimal(str(cost_info['fee']))
        )

        # Create transaction
        Transaction.objects.create(
            user=user,
            type=Transaction.Type.TRADE_BUY,
            amount=-total_cost,
            balance_before=balance_before,
            balance_after=user.balance,
            market=self.market,
            description=f"Buy {quantity} {contract_type.upper()} @ {cost_info['price_cents']}c"
        )

        self._broadcast_update(trade)
        return trade

    @transaction.atomic
    def sell(self, user: User, contract_type: str, quantity: int) -> AMMTrade:
        """
        Execute a sell order.
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
            raise TradingError(f"Insufficient YES shares. Have {position.yes_quantity}, need {quantity}")
        if contract_type == 'no' and position.no_quantity < quantity:
            raise TradingError(f"Insufficient NO shares. Have {position.no_quantity}, need {quantity}")

        # Calculate payout
        payout_info = self.calculate_sell_payout(contract_type, quantity)
        net_payout = Decimal(str(payout_info['net_payout']))

        # Get price before
        yes_before, no_before = self.get_display_prices()
        price_before = yes_before if contract_type == 'yes' else no_before

        # Add to user balance
        balance_before = user.balance
        user.balance += net_payout
        user.save()

        # Update pool
        if contract_type == 'yes':
            self.pool.yes_shares -= Decimal(str(quantity))
        else:
            self.pool.no_shares -= Decimal(str(quantity))

        self.pool.pool_balance -= Decimal(str(payout_info['base_payout']))
        self.pool.total_fees_collected += Decimal(str(payout_info['fee']))
        self.pool.save()

        # Update position
        if contract_type == 'yes':
            position.yes_quantity -= quantity
            if position.yes_quantity == 0:
                position.yes_avg_cost = Decimal('0')
        else:
            position.no_quantity -= quantity
            if position.no_quantity == 0:
                position.no_avg_cost = Decimal('0')

        position.save()

        # Update market prices
        yes_after, no_after = self.get_display_prices()
        self.market.last_yes_price = yes_after
        self.market.last_no_price = no_after
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
            price_after=yes_after if contract_type == 'yes' else no_after,
            avg_price=Decimal(str(payout_info['price_cents'])),
            total_cost=net_payout,
            fee_amount=Decimal(str(payout_info['fee']))
        )

        # Create transaction
        Transaction.objects.create(
            user=user,
            type=Transaction.Type.TRADE_SELL,
            amount=net_payout,
            balance_before=balance_before,
            balance_after=user.balance,
            market=self.market,
            description=f"Sell {quantity} {contract_type.upper()} @ {payout_info['price_cents']}c"
        )

        self._broadcast_update(trade)
        return trade

    def get_status(self) -> dict:
        """
        Get pool status including profitability info.
        """
        exposure = self.calculate_exposure()
        yes_price, no_price = self.get_display_prices()
        buy_yes, buy_no = self.get_prices_with_vig()

        return {
            'yes_price': yes_price,
            'no_price': no_price,
            'buy_yes_price': buy_yes,
            'buy_no_price': buy_no,
            'vig_total': buy_yes + buy_no - 100,  # How much over 100%
            'money_collected': exposure['money_collected'],
            'yes_shares': float(self.pool.yes_shares),
            'no_shares': float(self.pool.no_shares),
            'yes_exposure': exposure['yes_exposure'],
            'no_exposure': exposure['no_exposure'],
            'max_exposure': exposure['max_exposure'],
            'max_loss_cap': float(self.max_loss),
            'fees_collected': float(self.pool.total_fees_collected),
            'is_balanced': abs(exposure['yes_exposure'] - exposure['no_exposure']) < 10,
        }

    def _broadcast_update(self, trade: AMMTrade = None):
        """Broadcast update via WebSocket."""
        try:
            from .broadcasts import broadcast_market_update, broadcast_amm_trade
            broadcast_market_update(self.market)
            if trade:
                broadcast_amm_trade(trade, self.market)
        except Exception:
            pass


def get_bookmaker_prices(market: Market) -> dict:
    """Get current bookmaker prices for a market."""
    try:
        bm = BookmakerAMM(market)
        status = bm.get_status()
        return {
            'yes_price': status['yes_price'],
            'no_price': status['no_price'],
            'buy_yes_price': status['buy_yes_price'],
            'buy_no_price': status['buy_no_price'],
        }
    except Exception:
        return {
            'yes_price': 50,
            'no_price': 50,
            'buy_yes_price': 52,
            'buy_no_price': 52,
        }
