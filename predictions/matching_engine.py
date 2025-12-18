"""
Order Matching Engine for the Prediction Market.

Implements price-time priority matching with atomic transactions.
"""

from django.db import transaction
from django.db.models import F
from decimal import Decimal
from .models import User, Market, Order, Trade, Position, Transaction
from .exceptions import (
    InsufficientFundsError,
    InsufficientPositionError,
    InvalidPriceError,
    InvalidQuantityError,
    MarketNotActiveError,
    OrderCancellationError,
)


class MatchingEngine:
    """
    Price-time priority order matching engine.

    Key Concepts:
    - Buying YES at price P means paying Pc for a contract worth $1 if YES wins
    - Buying NO at price P means paying Pc for a contract worth $1 if NO wins
    - YES price + NO price should equal 100c (approximately)
    - Orders match when buy_price >= sell_price
    - Execution price is the maker's (resting order's) price
    """

    def __init__(self, market):
        self.market = market

    def _validate_order(self, user, side, contract_type, price, quantity):
        """Validate order parameters before processing."""
        # Validate market is active
        if not self.market.is_trading_active:
            raise MarketNotActiveError(self.market)

        # Validate price (1-99 cents)
        if not isinstance(price, int) or price < 1 or price > 99:
            raise InvalidPriceError(price)

        # Validate quantity
        if not isinstance(quantity, int) or quantity < 1:
            raise InvalidQuantityError(quantity)

    @transaction.atomic
    def place_order(self, user, side, contract_type, price, quantity):
        """
        Place a new order and attempt to match.

        Args:
            user: User placing the order
            side: 'buy' or 'sell'
            contract_type: 'yes' or 'no'
            price: Price in cents (1-99)
            quantity: Number of contracts

        Returns:
            tuple: (order, list of trades executed)

        Raises:
            InsufficientFundsError: If user can't afford the order
            InsufficientPositionError: If user doesn't have contracts to sell
            InvalidPriceError: If price is outside 1-99 range
            InvalidQuantityError: If quantity is not positive
            MarketNotActiveError: If market isn't active for trading
        """
        # Validate inputs
        self._validate_order(user, side, contract_type, price, quantity)

        # Lock user row for balance updates
        user = User.objects.select_for_update().get(pk=user.pk)

        # Calculate and reserve funds for buy orders
        if side == 'buy':
            required_funds = Decimal(price * quantity) / 100
            if user.available_balance < required_funds:
                raise InsufficientFundsError(required_funds, user.available_balance)

            # Reserve the funds
            user.reserved_balance += required_funds
            user.save()

            # Create transaction record for reservation
            Transaction.objects.create(
                user=user,
                type=Transaction.Type.ORDER_RESERVE,
                amount=-required_funds,
                balance_before=user.balance + required_funds,
                balance_after=user.balance,
                description=f"Reserved for {side.upper()} {quantity} {contract_type.upper()} @ {price}c"
            )
        else:
            # For sell orders, verify user has position
            position = Position.objects.select_for_update().filter(
                user=user, market=self.market
            ).first()

            if contract_type == 'yes':
                available = position.yes_quantity if position else 0
            else:
                available = position.no_quantity if position else 0

            if available < quantity:
                raise InsufficientPositionError(quantity, available, contract_type)

        # Create the order
        order = Order.objects.create(
            market=self.market,
            user=user,
            side=side,
            contract_type=contract_type,
            price=price,
            quantity=quantity,
            status=Order.Status.OPEN
        )

        # Attempt to match
        trades = self._match_order(order)

        # Update order status based on fills
        order.refresh_from_db()
        if order.filled_quantity == order.quantity:
            order.status = Order.Status.FILLED
        elif order.filled_quantity > 0:
            order.status = Order.Status.PARTIALLY_FILLED
        order.save()

        # Update market best bid/ask cache
        self._update_market_quotes()

        return order, trades

    def _match_order(self, incoming_order):
        """
        Match incoming order against resting orders.

        Uses price-time priority:
        - For BUY: Match against lowest priced SELL orders first
        - For SELL: Match against highest priced BUY orders first
        - Within same price, oldest order matches first
        """
        trades = []
        remaining = incoming_order.quantity - incoming_order.filled_quantity

        while remaining > 0:
            # Find best matching order
            matching_order = self._find_best_match(incoming_order)

            if matching_order is None:
                break

            # Calculate fill quantity
            fill_qty = min(remaining, matching_order.remaining_quantity)

            # Execution price is maker's (resting order's) price
            exec_price = matching_order.price

            # Execute the trade
            trade = self._execute_trade(
                incoming_order,
                matching_order,
                fill_qty,
                exec_price
            )
            trades.append(trade)

            # Update remaining quantity
            incoming_order.refresh_from_db()
            remaining = incoming_order.quantity - incoming_order.filled_quantity

        return trades

    def _find_best_match(self, incoming):
        """
        Find the best matching order using price-time priority.

        For a BUY order: find lowest ASK where ask_price <= buy_price
        For a SELL order: find highest BID where bid_price >= sell_price
        """
        if incoming.side == 'buy':
            # Find sell orders at or below our buy price
            matching_orders = Order.objects.filter(
                market=self.market,
                side='sell',
                contract_type=incoming.contract_type,
                status__in=[Order.Status.OPEN, Order.Status.PARTIALLY_FILLED],
                price__lte=incoming.price  # sell price <= buy price
            ).exclude(
                user=incoming.user  # Prevent self-trading
            ).order_by('price', 'created_at')  # lowest price first, then oldest

        else:  # sell
            # Find buy orders at or above our sell price
            matching_orders = Order.objects.filter(
                market=self.market,
                side='buy',
                contract_type=incoming.contract_type,
                status__in=[Order.Status.OPEN, Order.Status.PARTIALLY_FILLED],
                price__gte=incoming.price  # buy price >= sell price
            ).exclude(
                user=incoming.user  # Prevent self-trading
            ).order_by('-price', 'created_at')  # highest price first, then oldest

        return matching_orders.select_for_update().first()

    def _execute_trade(self, incoming_order, resting_order, quantity, price):
        """
        Execute a trade between two orders.

        Args:
            incoming_order: The new order that triggered the match
            resting_order: The existing order in the book
            quantity: Number of contracts to trade
            price: Execution price (maker's price)

        Returns:
            Trade: The executed trade record
        """
        # Determine buyer and seller
        if incoming_order.side == 'buy':
            buy_order = incoming_order
            sell_order = resting_order
        else:
            buy_order = resting_order
            sell_order = incoming_order

        # Lock both users
        buyer = User.objects.select_for_update().get(pk=buy_order.user.pk)
        seller = User.objects.select_for_update().get(pk=sell_order.user.pk)

        # Calculate trade value in dollars
        trade_value = Decimal(price * quantity) / 100

        # Update buyer's balance
        # Release reserved funds (at order's price), deduct actual cost (at execution price)
        buyer_reserved_release = Decimal(buy_order.price * quantity) / 100
        buyer.reserved_balance -= buyer_reserved_release

        # The difference between reserved and actual goes back to available balance
        # (if execution price < order price, buyer saves money)
        savings = buyer_reserved_release - trade_value
        if savings != 0:
            buyer.balance += savings

        buyer.save()

        # Update seller's balance (receive payment)
        seller.balance += trade_value
        seller.save()

        # Update positions
        self._update_positions(buyer, seller, buy_order.contract_type, quantity, price)

        # Update order fill quantities
        buy_order.filled_quantity = F('filled_quantity') + quantity
        sell_order.filled_quantity = F('filled_quantity') + quantity
        buy_order.save()
        sell_order.save()

        # Refresh to get updated values
        buy_order.refresh_from_db()
        sell_order.refresh_from_db()

        # Update order statuses
        for order in [buy_order, sell_order]:
            if order.filled_quantity >= order.quantity:
                order.status = Order.Status.FILLED
            else:
                order.status = Order.Status.PARTIALLY_FILLED
            order.save()

        # Create trade record
        trade = Trade.objects.create(
            market=self.market,
            buy_order=buy_order,
            sell_order=sell_order,
            buyer=buyer,
            seller=seller,
            contract_type=buy_order.contract_type,
            price=price,
            quantity=quantity
        )

        # Update market last price
        if buy_order.contract_type == 'yes':
            self.market.last_yes_price = price
            self.market.last_no_price = 100 - price
        else:
            self.market.last_no_price = price
            self.market.last_yes_price = 100 - price
        self.market.total_volume = F('total_volume') + quantity
        self.market.save()

        # Create transaction records
        self._create_trade_transactions(trade, buyer, seller, trade_value)

        return trade

    def _update_positions(self, buyer, seller, contract_type, quantity, price):
        """Update user positions after a trade."""
        # Get or create positions
        buyer_pos, _ = Position.objects.get_or_create(
            user=buyer, market=self.market
        )
        seller_pos, _ = Position.objects.get_or_create(
            user=seller, market=self.market
        )

        if contract_type == 'yes':
            # Buyer gets YES contracts
            old_qty = buyer_pos.yes_quantity
            old_cost = float(buyer_pos.yes_avg_cost)
            new_qty = old_qty + quantity

            # Update average cost basis
            if new_qty > 0:
                buyer_pos.yes_avg_cost = Decimal(
                    (old_qty * old_cost + quantity * price) / new_qty
                )
            buyer_pos.yes_quantity = new_qty

            # Seller loses YES contracts
            seller_pos.yes_quantity -= quantity
            # Calculate realized P&L for seller
            pnl = Decimal(quantity * (price - float(seller_pos.yes_avg_cost))) / 100
            seller_pos.realized_pnl += pnl

        else:  # NO contracts
            # Buyer gets NO contracts
            old_qty = buyer_pos.no_quantity
            old_cost = float(buyer_pos.no_avg_cost)
            new_qty = old_qty + quantity

            if new_qty > 0:
                buyer_pos.no_avg_cost = Decimal(
                    (old_qty * old_cost + quantity * price) / new_qty
                )
            buyer_pos.no_quantity = new_qty

            # Seller loses NO contracts
            seller_pos.no_quantity -= quantity
            pnl = Decimal(quantity * (price - float(seller_pos.no_avg_cost))) / 100
            seller_pos.realized_pnl += pnl

        buyer_pos.save()
        seller_pos.save()

    def _create_trade_transactions(self, trade, buyer, seller, trade_value):
        """Create transaction records for a trade."""
        # Buyer transaction (debit)
        Transaction.objects.create(
            user=buyer,
            type=Transaction.Type.TRADE_BUY,
            amount=-trade_value,
            balance_before=buyer.balance + trade_value,
            balance_after=buyer.balance,
            order=trade.buy_order,
            trade=trade,
            market=self.market,
            description=f"Bought {trade.quantity} {trade.contract_type.upper()} @ {trade.price}c"
        )

        # Seller transaction (credit)
        Transaction.objects.create(
            user=seller,
            type=Transaction.Type.TRADE_SELL,
            amount=trade_value,
            balance_before=seller.balance - trade_value,
            balance_after=seller.balance,
            order=trade.sell_order,
            trade=trade,
            market=self.market,
            description=f"Sold {trade.quantity} {trade.contract_type.upper()} @ {trade.price}c"
        )

    def _update_market_quotes(self):
        """Update market's best bid/ask cache."""
        # Best YES bid (highest buy price)
        best_yes_bid = Order.objects.filter(
            market=self.market,
            side='buy',
            contract_type='yes',
            status__in=[Order.Status.OPEN, Order.Status.PARTIALLY_FILLED]
        ).order_by('-price').values_list('price', flat=True).first()

        # Best YES ask (lowest sell price)
        best_yes_ask = Order.objects.filter(
            market=self.market,
            side='sell',
            contract_type='yes',
            status__in=[Order.Status.OPEN, Order.Status.PARTIALLY_FILLED]
        ).order_by('price').values_list('price', flat=True).first()

        # Best NO bid (highest buy price)
        best_no_bid = Order.objects.filter(
            market=self.market,
            side='buy',
            contract_type='no',
            status__in=[Order.Status.OPEN, Order.Status.PARTIALLY_FILLED]
        ).order_by('-price').values_list('price', flat=True).first()

        # Best NO ask (lowest sell price)
        best_no_ask = Order.objects.filter(
            market=self.market,
            side='sell',
            contract_type='no',
            status__in=[Order.Status.OPEN, Order.Status.PARTIALLY_FILLED]
        ).order_by('price').values_list('price', flat=True).first()

        self.market.best_yes_bid = best_yes_bid
        self.market.best_yes_ask = best_yes_ask
        self.market.best_no_bid = best_no_bid
        self.market.best_no_ask = best_no_ask
        self.market.save()

    @transaction.atomic
    def cancel_order(self, order, user):
        """
        Cancel an open order and release reserved funds.

        Args:
            order: Order to cancel
            user: User requesting cancellation

        Returns:
            Order: The cancelled order

        Raises:
            OrderCancellationError: If order cannot be cancelled
        """
        # Verify ownership
        if order.user != user:
            raise OrderCancellationError(order, "You don't own this order")

        # Verify order is cancellable
        if order.status not in [Order.Status.OPEN, Order.Status.PARTIALLY_FILLED]:
            raise OrderCancellationError(
                order,
                f"Order status is {order.get_status_display()}"
            )

        # Lock user for balance update
        user = User.objects.select_for_update().get(pk=user.pk)

        # Release reserved funds for buy orders
        if order.side == 'buy':
            remaining_qty = order.quantity - order.filled_quantity
            release_amount = Decimal(order.price * remaining_qty) / 100

            user.reserved_balance -= release_amount
            user.save()

            # Create transaction record
            Transaction.objects.create(
                user=user,
                type=Transaction.Type.ORDER_RELEASE,
                amount=release_amount,
                balance_before=user.balance - release_amount,
                balance_after=user.balance,
                order=order,
                description=f"Released funds from cancelled order"
            )

        order.status = Order.Status.CANCELLED
        order.save()

        # Update market quotes
        self._update_market_quotes()

        return order


def get_orderbook(market, depth=10):
    """
    Get the current orderbook for a market.

    Args:
        market: Market instance
        depth: Number of price levels to return

    Returns:
        dict with 'yes_bids', 'yes_asks', 'no_bids', 'no_asks'
        Each is a list of {'price': int, 'quantity': int}
    """
    from django.db.models import Sum

    def get_levels(side, contract_type, ascending=True):
        orders = Order.objects.filter(
            market=market,
            side=side,
            contract_type=contract_type,
            status__in=[Order.Status.OPEN, Order.Status.PARTIALLY_FILLED]
        ).values('price').annotate(
            quantity=Sum(F('quantity') - F('filled_quantity'))
        ).order_by('price' if ascending else '-price')[:depth]

        return [{'price': o['price'], 'quantity': o['quantity']} for o in orders]

    return {
        'yes_bids': get_levels('buy', 'yes', ascending=False),  # Highest first
        'yes_asks': get_levels('sell', 'yes', ascending=True),   # Lowest first
        'no_bids': get_levels('buy', 'no', ascending=False),
        'no_asks': get_levels('sell', 'no', ascending=True),
    }
