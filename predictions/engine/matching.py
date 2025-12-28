"""
Order Matching Engine for the Prediction Market.

Implements price-time priority matching with atomic transactions.
"""

from django.db import transaction
from django.db.models import F
from decimal import Decimal
# Changed from .models to predictions.models (or ..models)
from predictions.models import User, Market, Order, Trade, Position, Transaction
from predictions.exceptions import (
    InsufficientFundsError,
    InsufficientPositionError,
    InvalidPriceError,
    InvalidQuantityError,
    MarketNotActiveError,
    OrderCancellationError,
)
from predictions.broadcasts import broadcast_market_update, broadcast_trade_executed, broadcast_orderbook_update


class MatchingEngine:
    """
    Price-time priority order matching engine.

    Key Concepts:
    - Buying YES at price P means paying Pc for a contract worth $1 if YES wins
    - Buying NO at price P means paying Pc for a contract worth $1 if NO wins
    - YES price + NO price should equal 100c (approximately)
    - Orders match when buy_price >= sell_price
    - Execution price is the maker's (resting order's) price

    Order Types:
    - Limit: User specifies exact price, order sits in book until matched
    - Market: Price determined automatically from best available in orderbook
    """

    # Transaction fee percentage (2%)
    FEE_PERCENTAGE = Decimal('0.02')

    def __init__(self, market):
        self.market = market

    def _get_market_price(self, side, contract_type):
        """
        Determine execution price for a market order.

        For BUY: Use best ASK (lowest sell order) or last traded price
        For SELL: Use best BID (highest buy order) or last traded price

        Args:
            side: 'buy' or 'sell'
            contract_type: 'yes' or 'no'

        Returns:
            int: Price in cents (1-99)
        """
        if contract_type == 'yes':
            if side == 'buy':
                # Buying YES - use best ask (lowest sell price) or last price
                return self.market.best_yes_ask or self.market.last_yes_price
            else:
                # Selling YES - use best bid (highest buy price) or last price
                return self.market.best_yes_bid or self.market.last_yes_price
        else:  # NO
            if side == 'buy':
                # Buying NO - use best ask (lowest sell price) or last price
                return self.market.best_no_ask or self.market.last_no_price
            else:
                # Selling NO - use best bid (highest buy price) or last price
                return self.market.best_no_bid or self.market.last_no_price

    def _validate_order(self, user, side, contract_type, price, quantity, order_type='limit'):
        """Validate order parameters before processing."""
        # Validate market is active
        if not self.market.is_trading_active:
            raise MarketNotActiveError(self.market)

        # Validate price (1-99 cents) - only for limit orders
        if order_type == 'limit':
            if not isinstance(price, int) or price < 1 or price > 99:
                raise InvalidPriceError(price)

        # Validate quantity
        if not isinstance(quantity, int) or quantity < 1:
            raise InvalidQuantityError(quantity)

    @transaction.atomic
    def place_order(self, user, side, contract_type, price, quantity, order_type='limit'):
        """
        Place a new order and attempt to match.

        Args:
            user: User placing the order
            side: 'buy' or 'sell'
            contract_type: 'yes' or 'no'
            price: Price in cents (1-99) - required for limit orders, ignored for market
            quantity: Number of contracts
            order_type: 'limit' or 'market' (default: 'limit')

        Returns:
            tuple: (order, list of trades executed)

        Raises:
            InsufficientFundsError: If user can't afford the order
            InsufficientPositionError: If user doesn't have contracts to sell
            InvalidPriceError: If price is outside 1-99 range
            InvalidQuantityError: If quantity is not positive
            MarketNotActiveError: If market isn't active for trading
        """
        # For market orders, determine price from orderbook
        if order_type == 'market':
            price = self._get_market_price(side, contract_type)

        # Validate inputs
        self._validate_order(user, side, contract_type, price, quantity, order_type)

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

        # Create the order (convert cents to dollars for storage)
        price_dollars = Decimal(price) / 100
        order = Order.objects.create(
            market=self.market,
            user=user,
            side=side,
            contract_type=contract_type,
            order_type=order_type,
            price=price_dollars,
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

        Matching Priority (Polymarket-style):
        1. Direct match: BUY YES vs SELL YES (or BUY NO vs SELL NO)
        2. Mint match: BUY YES + BUY NO at complementary prices (creates shares)
        3. Merge match: SELL YES + SELL NO at complementary prices (burns shares)

        Uses price-time priority within each matching type.
        """
        trades = []
        remaining = incoming_order.quantity - incoming_order.filled_quantity

        while remaining > 0:
            # First, try direct match (highest priority)
            matching_order = self._find_best_match(incoming_order)

            if matching_order is not None:
                # Calculate fill quantity
                fill_qty = min(remaining, matching_order.remaining_quantity)

                # Execution price is maker's (resting order's) price
                exec_price = matching_order.price

                # Execute the direct trade
                trade = self._execute_trade(
                    incoming_order,
                    matching_order,
                    fill_qty,
                    exec_price
                )
                trades.append(trade)
            else:
                # No direct match - try complementary matching
                if incoming_order.side == 'buy':
                    # Try minting: find BUY order for opposite contract
                    comp_order, yes_price, no_price = self._find_complementary_buy_match(incoming_order)
                    if comp_order:
                        fill_qty = min(remaining, comp_order.remaining_quantity)

                        # Determine which is YES and which is NO order
                        if incoming_order.contract_type == 'yes':
                            trade = self._execute_mint(incoming_order, comp_order, fill_qty, yes_price, no_price)
                        else:
                            trade = self._execute_mint(comp_order, incoming_order, fill_qty, yes_price, no_price)
                        trades.append(trade)
                    else:
                        break  # No match found
                else:
                    # Try merging: find SELL order for opposite contract
                    comp_order, yes_price, no_price = self._find_complementary_sell_match(incoming_order)
                    if comp_order:
                        fill_qty = min(remaining, comp_order.remaining_quantity)

                        if incoming_order.contract_type == 'yes':
                            trade = self._execute_merge(incoming_order, comp_order, fill_qty, yes_price, no_price)
                        else:
                            trade = self._execute_merge(comp_order, incoming_order, fill_qty, yes_price, no_price)
                        trades.append(trade)
                    else:
                        break  # No match found

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

    def _find_complementary_buy_match(self, incoming_order):
        """
        Find a complementary buy order for minting (Polymarket-style).

        If incoming is BUY YES @ P_yes, find BUY NO @ P_no where P_yes + P_no >= 100.
        This allows two buyers to mint new YES/NO shares by paying $1 combined.

        Returns:
            tuple: (complementary_order, yes_price, no_price) or (None, None, None)
        """
        if incoming_order.side != 'buy':
            return None, None, None

        # Find complementary buy orders for the opposite contract type
        opposite_type = 'no' if incoming_order.contract_type == 'yes' else 'yes'

        # For minting: YES_price + NO_price >= $1.00 (sum to at least $1)
        # If incoming is BUY YES @ $0.60, need BUY NO @ $0.40 or higher
        # Prices are stored in dollars (0.01-0.99), so use $1.00 as base
        min_complementary_price = Decimal('1.00') - incoming_order.price

        complementary_orders = Order.objects.filter(
            market=self.market,
            side='buy',
            contract_type=opposite_type,
            status__in=[Order.Status.OPEN, Order.Status.PARTIALLY_FILLED],
            price__gte=min_complementary_price
        ).exclude(
            user=incoming_order.user  # Prevent self-matching
        ).order_by('-price', 'created_at')  # Highest price first for best match

        complementary = complementary_orders.select_for_update().first()

        if complementary:
            # Determine which is YES and which is NO order
            if incoming_order.contract_type == 'yes':
                return complementary, incoming_order.price, complementary.price
            else:
                return complementary, complementary.price, incoming_order.price

        return None, None, None

    def _find_complementary_sell_match(self, incoming_order):
        """
        Find a complementary sell order for merging (Polymarket-style).

        If incoming is SELL YES @ P_yes, find SELL NO @ P_no where P_yes + P_no <= 100.
        This allows two sellers to burn their shares and split $1 collateral.

        Returns:
            tuple: (complementary_order, yes_price, no_price) or (None, None, None)
        """
        if incoming_order.side != 'sell':
            return None, None, None

        opposite_type = 'no' if incoming_order.contract_type == 'yes' else 'yes'

        # For merging: YES_price + NO_price <= $1.00 (split $1 collateral)
        # If incoming is SELL YES @ $0.55, need SELL NO @ $0.45 or lower
        # Prices are stored in dollars (0.01-0.99), so use $1.00 as base
        max_complementary_price = Decimal('1.00') - incoming_order.price

        complementary_orders = Order.objects.filter(
            market=self.market,
            side='sell',
            contract_type=opposite_type,
            status__in=[Order.Status.OPEN, Order.Status.PARTIALLY_FILLED],
            price__lte=max_complementary_price
        ).exclude(
            user=incoming_order.user
        ).order_by('price', 'created_at')  # Lowest price first for best match

        complementary = complementary_orders.select_for_update().first()

        if complementary:
            if incoming_order.contract_type == 'yes':
                return complementary, incoming_order.price, complementary.price
            else:
                return complementary, complementary.price, incoming_order.price

        return None, None, None

    def _execute_mint(self, yes_order, no_order, quantity, yes_price, no_price):
        """
        Execute a mint trade: combine BUY YES and BUY NO to create new shares.

        Both buyers pay their respective prices (summing to >= $1).
        Each buyer receives their contract type.
        New shares are created (market.total_shares_outstanding increases).

        Args:
            yes_order: The BUY YES order
            no_order: The BUY NO order
            quantity: Number of share pairs to mint
            yes_price: Price YES buyer pays (Decimal in dollars, e.g., 0.60)
            no_price: Price NO buyer pays (Decimal in dollars, e.g., 0.40)

        Returns:
            Trade record for the mint operation
        """
        # Lock both users
        yes_buyer = User.objects.select_for_update().get(pk=yes_order.user.pk)
        no_buyer = User.objects.select_for_update().get(pk=no_order.user.pk)

        # Convert prices to cents for calculations that need cents (avg_cost, Market, Trade)
        yes_price_cents = int(Decimal(yes_price) * 100)
        no_price_cents = int(Decimal(no_price) * 100)

        # Calculate costs (prices are in dollars, no conversion needed)
        yes_cost = Decimal(yes_price) * quantity
        no_cost = Decimal(no_price) * quantity

        # Calculate 2% transaction fee for each buyer
        yes_fee = yes_cost * self.FEE_PERCENTAGE
        no_fee = no_cost * self.FEE_PERCENTAGE
        total_fees = yes_fee + no_fee

        # Release reserved funds and deduct actual costs + fee for YES buyer
        yes_reserved_release = Decimal(yes_order.price) * quantity
        yes_buyer.reserved_balance -= yes_reserved_release
        yes_buyer.balance -= (yes_cost + yes_fee)  # Deduct cost plus fee
        yes_buyer.save()

        # Release reserved funds and deduct actual costs + fee for NO buyer
        no_reserved_release = Decimal(no_order.price) * quantity
        no_buyer.reserved_balance -= no_reserved_release
        no_buyer.balance -= (no_cost + no_fee)  # Deduct cost plus fee
        no_buyer.save()

        # Track fees collected by the market
        from django.db.models import F as ModelF
        self.market.fees_collected = ModelF('fees_collected') + total_fees
        self.market.save(update_fields=['fees_collected'])

        # Update positions - each buyer gets their contract type (avg_cost stored in cents)
        self._update_position_for_mint(yes_buyer, 'yes', quantity, yes_price_cents)
        self._update_position_for_mint(no_buyer, 'no', quantity, no_price_cents)

        # Update order fill quantities
        yes_order.filled_quantity = F('filled_quantity') + quantity
        no_order.filled_quantity = F('filled_quantity') + quantity
        yes_order.save()
        no_order.save()

        # Refresh and update statuses
        for order in [yes_order, no_order]:
            order.refresh_from_db()
            if order.filled_quantity >= order.quantity:
                order.status = Order.Status.FILLED
            else:
                order.status = Order.Status.PARTIALLY_FILLED
            order.save()

        # Update market: new shares created (prices already converted to cents above)
        self.market.total_shares_outstanding = F('total_shares_outstanding') + quantity
        self.market.total_volume = F('total_volume') + quantity
        self.market.last_yes_price = yes_price_cents
        self.market.last_no_price = 100 - yes_price_cents
        self.market.save()
        self.market.refresh_from_db()

        # Create trade record (price stored in cents for Trade model)
        trade = Trade.objects.create(
            market=self.market,
            buy_order=yes_order,
            sell_order=no_order,  # Reuse field for the NO buyer's order
            buyer=yes_buyer,
            seller=no_buyer,  # Actually also a buyer (getting NO contracts)
            contract_type='yes',
            price=yes_price_cents,
            quantity=quantity,
            trade_type=Trade.TradeType.MINT
        )

        # Create transaction records (balance was already updated, so calculate before from current)
        yes_total_cost = yes_cost + yes_fee
        Transaction.objects.create(
            user=yes_buyer,
            type=Transaction.Type.MINT_MATCH,
            amount=-yes_cost,
            balance_before=yes_buyer.balance + yes_total_cost,
            balance_after=yes_buyer.balance + yes_fee,  # Before fee was deducted
            trade=trade,
            market=self.market,
            description=f"Minted {quantity} YES @ {yes_price_cents}c (paired with NO buyer)"
        )

        # Fee transaction for YES buyer
        Transaction.objects.create(
            user=yes_buyer,
            type=Transaction.Type.TRANSACTION_FEE,
            amount=-yes_fee,
            balance_before=yes_buyer.balance + yes_fee,
            balance_after=yes_buyer.balance,
            trade=trade,
            market=self.market,
            description=f"Transaction fee (2%) on mint of {quantity} YES"
        )

        no_total_cost = no_cost + no_fee
        Transaction.objects.create(
            user=no_buyer,
            type=Transaction.Type.MINT_MATCH,
            amount=-no_cost,
            balance_before=no_buyer.balance + no_total_cost,
            balance_after=no_buyer.balance + no_fee,  # Before fee was deducted
            trade=trade,
            market=self.market,
            description=f"Minted {quantity} NO @ {no_price_cents}c (paired with YES buyer)"
        )

        # Fee transaction for NO buyer
        Transaction.objects.create(
            user=no_buyer,
            type=Transaction.Type.TRANSACTION_FEE,
            amount=-no_fee,
            balance_before=no_buyer.balance + no_fee,
            balance_after=no_buyer.balance,
            trade=trade,
            market=self.market,
            description=f"Transaction fee (2%) on mint of {quantity} NO"
        )

        broadcast_trade_executed(trade)

        return trade

    def _execute_merge(self, yes_order, no_order, quantity, yes_price, no_price):
        """
        Execute a merge trade: combine SELL YES and SELL NO to burn shares.

        Each seller gives up their contracts and receives their price from collateral.
        Shares are destroyed (market.total_shares_outstanding decreases).

        Args:
            yes_order: The SELL YES order
            no_order: The SELL NO order
            quantity: Number of share pairs to merge
            yes_price: Price YES seller receives (Decimal in dollars, e.g., 0.55)
            no_price: Price NO seller receives (Decimal in dollars, e.g., 0.45)

        Returns:
            Trade record for the merge operation
        """
        # Lock both users
        yes_seller = User.objects.select_for_update().get(pk=yes_order.user.pk)
        no_seller = User.objects.select_for_update().get(pk=no_order.user.pk)

        # Verify positions (should already be checked, but double-verify)
        yes_pos = Position.objects.select_for_update().get(user=yes_seller, market=self.market)
        no_pos = Position.objects.select_for_update().get(user=no_seller, market=self.market)

        if yes_pos.yes_quantity < quantity:
            raise InsufficientPositionError(quantity, yes_pos.yes_quantity, 'yes')
        if no_pos.no_quantity < quantity:
            raise InsufficientPositionError(quantity, no_pos.no_quantity, 'no')

        # Convert prices to cents for calculations that need cents
        yes_price_cents = int(Decimal(yes_price) * 100)
        no_price_cents = int(Decimal(no_price) * 100)

        # Calculate payouts (prices are in dollars, no conversion needed)
        yes_payout = Decimal(yes_price) * quantity
        no_payout = Decimal(no_price) * quantity

        # Calculate 2% transaction fee for each seller
        yes_fee = yes_payout * self.FEE_PERCENTAGE
        no_fee = no_payout * self.FEE_PERCENTAGE
        total_fees = yes_fee + no_fee

        # Credit sellers (minus fee)
        yes_seller.balance += (yes_payout - yes_fee)
        yes_seller.save()

        no_seller.balance += (no_payout - no_fee)
        no_seller.save()

        # Track fees collected by the market
        from django.db.models import F as ModelF
        self.market.fees_collected = ModelF('fees_collected') + total_fees
        self.market.save(update_fields=['fees_collected'])

        # Update positions - deduct contracts and calculate realized P&L
        # avg_cost is stored in cents, so use cents for P&L calculation
        yes_pnl = Decimal(quantity) * (Decimal(yes_price_cents) - yes_pos.yes_avg_cost) / 100
        yes_pos.yes_quantity -= quantity
        yes_pos.realized_pnl += yes_pnl
        yes_pos.save()

        no_pnl = Decimal(quantity) * (Decimal(no_price_cents) - no_pos.no_avg_cost) / 100
        no_pos.no_quantity -= quantity
        no_pos.realized_pnl += no_pnl
        no_pos.save()

        # Update order fill quantities
        yes_order.filled_quantity = F('filled_quantity') + quantity
        no_order.filled_quantity = F('filled_quantity') + quantity
        yes_order.save()
        no_order.save()

        for order in [yes_order, no_order]:
            order.refresh_from_db()
            if order.filled_quantity >= order.quantity:
                order.status = Order.Status.FILLED
            else:
                order.status = Order.Status.PARTIALLY_FILLED
            order.save()

        # Update market: shares burned (prices in cents for Market model)
        self.market.total_shares_outstanding = F('total_shares_outstanding') - quantity
        self.market.total_volume = F('total_volume') + quantity
        self.market.last_yes_price = yes_price_cents
        self.market.last_no_price = 100 - yes_price_cents
        self.market.save()
        self.market.refresh_from_db()

        # Create trade record (price in cents for Trade model)
        trade = Trade.objects.create(
            market=self.market,
            buy_order=yes_order,  # Reusing field for YES seller
            sell_order=no_order,  # Reusing field for NO seller
            buyer=yes_seller,  # Actually a seller
            seller=no_seller,  # Actually also a seller
            contract_type='yes',
            price=yes_price_cents,
            quantity=quantity,
            trade_type=Trade.TradeType.MERGE
        )

        # Create transaction records (with fees)
        yes_net_payout = yes_payout - yes_fee
        Transaction.objects.create(
            user=yes_seller,
            type=Transaction.Type.MERGE_MATCH,
            amount=yes_net_payout,
            balance_before=yes_seller.balance - yes_net_payout,
            balance_after=yes_seller.balance,
            trade=trade,
            market=self.market,
            description=f"Merged {quantity} YES @ {yes_price_cents}c (after 2% fee)"
        )

        # Fee transaction for YES seller
        Transaction.objects.create(
            user=yes_seller,
            type=Transaction.Type.TRANSACTION_FEE,
            amount=-yes_fee,
            balance_before=yes_seller.balance + yes_fee,
            balance_after=yes_seller.balance,
            trade=trade,
            market=self.market,
            description=f"Transaction fee (2%) on merge of {quantity} YES"
        )

        no_net_payout = no_payout - no_fee
        Transaction.objects.create(
            user=no_seller,
            type=Transaction.Type.MERGE_MATCH,
            amount=no_net_payout,
            balance_before=no_seller.balance - no_net_payout,
            balance_after=no_seller.balance,
            trade=trade,
            market=self.market,
            description=f"Merged {quantity} NO @ {no_price_cents}c (after 2% fee)"
        )

        # Fee transaction for NO seller
        Transaction.objects.create(
            user=no_seller,
            type=Transaction.Type.TRANSACTION_FEE,
            amount=-no_fee,
            balance_before=no_seller.balance + no_fee,
            balance_after=no_seller.balance,
            trade=trade,
            market=self.market,
            description=f"Transaction fee (2%) on merge of {quantity} NO"
        )

        broadcast_trade_executed(trade)

        return trade

    def _update_position_for_mint(self, user, contract_type, quantity, price):
        """Update user position after receiving minted contracts."""
        position, _ = Position.objects.get_or_create(user=user, market=self.market)

        if contract_type == 'yes':
            old_qty = position.yes_quantity
            new_qty = old_qty + quantity

            if new_qty > 0:
                position.yes_avg_cost = (
                    (Decimal(old_qty) * position.yes_avg_cost + Decimal(quantity * price)) / Decimal(new_qty)
                )
            position.yes_quantity = new_qty
        else:
            old_qty = position.no_quantity
            new_qty = old_qty + quantity

            if new_qty > 0:
                position.no_avg_cost = (
                    (Decimal(old_qty) * position.no_avg_cost + Decimal(quantity * price)) / Decimal(new_qty)
                )
            position.no_quantity = new_qty

        position.save()

    def _execute_trade(self, incoming_order, resting_order, quantity, price):
        """
        Execute a trade between two orders.

        Args:
            incoming_order: The new order that triggered the match
            resting_order: The existing order in the book
            quantity: Number of contracts to trade
            price: Execution price (maker's price, Decimal in dollars e.g., 0.60)

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

        # Convert price to cents for calculations that need cents (avg_cost, Market, Trade)
        price_cents = int(Decimal(price) * 100)

        # Calculate trade value in dollars (prices are in dollars, no conversion needed)
        trade_value = Decimal(price) * quantity

        # Calculate 2% transaction fee (deducted from seller's proceeds)
        fee_amount = trade_value * self.FEE_PERCENTAGE

        # Update buyer's balance
        # Release reserved funds (at order's price), deduct actual cost (at execution price)
        buyer_reserved_release = Decimal(buy_order.price) * quantity
        buyer.reserved_balance -= buyer_reserved_release

        # The difference between reserved and actual goes back to available balance
        # (if execution price < order price, buyer saves money)
        savings = buyer_reserved_release - trade_value
        if savings != 0:
            buyer.balance += savings

        buyer.save()

        # Update seller's balance (receive payment minus fee)
        seller_proceeds = trade_value - fee_amount
        seller.balance += seller_proceeds
        seller.save()

        # Track fee collected by the market
        from django.db.models import F as ModelF
        self.market.fees_collected = ModelF('fees_collected') + fee_amount
        self.market.save(update_fields=['fees_collected'])

        # Update positions (avg_cost stored in cents)
        self._update_positions(buyer, seller, buy_order.contract_type, quantity, price_cents)

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

        # Create trade record (price in cents for Trade model)
        trade = Trade.objects.create(
            market=self.market,
            buy_order=buy_order,
            sell_order=sell_order,
            buyer=buyer,
            seller=seller,
            contract_type=buy_order.contract_type,
            price=price_cents,
            quantity=quantity
        )

        # Update market last price (prices in cents for Market model)
        if buy_order.contract_type == 'yes':
            self.market.last_yes_price = price_cents
            self.market.last_no_price = 100 - price_cents
        else:
            self.market.last_no_price = price_cents
            self.market.last_yes_price = 100 - price_cents
        self.market.total_volume = F('total_volume') + quantity
        self.market.save()

        # Refresh market to get updated total_volume for broadcasting
        self.market.refresh_from_db()

        # Broadcast the trade execution via WebSocket
        broadcast_trade_executed(trade)

        # Create transaction records (with fee)
        self._create_trade_transactions(trade, buyer, seller, trade_value, fee_amount)

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
            new_qty = old_qty + quantity

            # Update average cost basis
            if new_qty > 0:
                buyer_pos.yes_avg_cost = (
                    (Decimal(old_qty) * buyer_pos.yes_avg_cost + Decimal(quantity) * Decimal(price)) / Decimal(new_qty)
                )
            buyer_pos.yes_quantity = new_qty

            # Seller loses YES contracts
            seller_pos.yes_quantity -= quantity
            # Calculate realized P&L for seller
            pnl = Decimal(quantity) * (Decimal(price) - seller_pos.yes_avg_cost) / 100
            seller_pos.realized_pnl += pnl

        else:  # NO contracts
            # Buyer gets NO contracts
            old_qty = buyer_pos.no_quantity
            new_qty = old_qty + quantity

            if new_qty > 0:
                buyer_pos.no_avg_cost = (
                    (Decimal(old_qty) * buyer_pos.no_avg_cost + Decimal(quantity) * Decimal(price)) / Decimal(new_qty)
                )
            buyer_pos.no_quantity = new_qty

            # Seller loses NO contracts
            seller_pos.no_quantity -= quantity
            pnl = Decimal(quantity) * (Decimal(price) - seller_pos.no_avg_cost) / 100
            seller_pos.realized_pnl += pnl

        buyer_pos.save()
        seller_pos.save()

    def _create_trade_transactions(self, trade, buyer, seller, trade_value, fee_amount):
        """Create transaction records for a trade including fee."""
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

        # Seller transaction (credit - minus fee)
        seller_proceeds = trade_value - fee_amount
        Transaction.objects.create(
            user=seller,
            type=Transaction.Type.TRADE_SELL,
            amount=seller_proceeds,
            balance_before=seller.balance - seller_proceeds,
            balance_after=seller.balance,
            order=trade.sell_order,
            trade=trade,
            market=self.market,
            description=f"Sold {trade.quantity} {trade.contract_type.upper()} @ {trade.price}c (after 2% fee)"
        )

        # Fee transaction record for seller
        Transaction.objects.create(
            user=seller,
            type=Transaction.Type.TRANSACTION_FEE,
            amount=-fee_amount,
            balance_before=seller.balance + fee_amount,
            balance_after=seller.balance,
            trade=trade,
            market=self.market,
            description=f"Transaction fee (2%) on sale of {trade.quantity} {trade.contract_type.upper()}"
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

        # Broadcast market and orderbook updates via WebSocket
        broadcast_market_update(self.market)
        broadcast_orderbook_update(self.market)

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

        # Release reserved funds for buy orders (prices are in dollars)
        if order.side == 'buy':
            remaining_qty = order.quantity - order.filled_quantity
            release_amount = Decimal(order.price) * remaining_qty

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

        # Price is stored in dollars (0.01-0.99), convert to cents for display
        return [{'price': int(float(o['price']) * 100) if o['price'] else 0, 'quantity': o['quantity']} for o in orders]

    return {
        'yes_bids': get_levels('buy', 'yes', ascending=False),  # Highest first
        'yes_asks': get_levels('sell', 'yes', ascending=True),   # Lowest first
        'no_bids': get_levels('buy', 'no', ascending=False),
        'no_asks': get_levels('sell', 'no', ascending=True),
    }


# =============================================================================
# Settlement and Direct Mint/Redeem Functions
# =============================================================================

@transaction.atomic
def settle_market(market, outcome):
    """
    Settle a market and pay out winners.

    Winning contracts pay $1 each. Losing contracts pay $0.
    All open orders are cancelled and reserved funds released.

    Args:
        market: Market instance to settle
        outcome: 'yes' or 'no' - the winning outcome

    Returns:
        dict with settlement statistics
    """
    from django.db.models import Q

    if market.status not in [Market.Status.ACTIVE, Market.Status.HALTED]:
        from .exceptions import TradingError
        raise TradingError(f"Market {market.id} cannot be settled: status is {market.status}")

    if outcome not in ['yes', 'no']:
        raise ValueError("Outcome must be 'yes' or 'no'")

    # Cancel all open orders first
    open_orders = Order.objects.filter(
        market=market,
        status__in=[Order.Status.OPEN, Order.Status.PARTIALLY_FILLED]
    )

    for order in open_orders:
        if order.side == 'buy':
            # Release reserved funds (prices are in dollars, no conversion needed)
            user = User.objects.select_for_update().get(pk=order.user.pk)
            remaining_qty = order.quantity - order.filled_quantity
            release_amount = Decimal(order.price) * remaining_qty
            user.reserved_balance -= release_amount
            user.save()

            Transaction.objects.create(
                user=user,
                type=Transaction.Type.ORDER_RELEASE,
                amount=release_amount,
                balance_before=user.balance,
                balance_after=user.balance,
                order=order,
                market=market,
                description=f"Released funds from cancelled order (market settled)"
            )

        order.status = Order.Status.CANCELLED
        order.save()

    # Get all positions with holdings
    positions = Position.objects.filter(market=market).filter(
        Q(yes_quantity__gt=0) | Q(no_quantity__gt=0)
    )

    stats = {
        'winners': 0,
        'losers': 0,
        'total_payout': Decimal('0.00'),
        'winning_outcome': outcome
    }

    for position in positions:
        user = User.objects.select_for_update().get(pk=position.user.pk)

        if outcome == 'yes':
            # YES wins: pay $1 per YES contract, NO contracts worth $0
            winning_qty = position.yes_quantity
            losing_qty = position.no_quantity
        else:
            # NO wins: pay $1 per NO contract, YES contracts worth $0
            winning_qty = position.no_quantity
            losing_qty = position.yes_quantity

        # Pay winners
        if winning_qty > 0:
            payout = Decimal(winning_qty)  # $1 per contract
            balance_before = user.balance
            user.balance += payout
            user.save()

            Transaction.objects.create(
                user=user,
                type=Transaction.Type.SETTLEMENT_WIN,
                amount=payout,
                balance_before=balance_before,
                balance_after=user.balance,
                market=market,
                description=f"Won {winning_qty} {outcome.upper()} contracts @ $1 each"
            )

            stats['winners'] += 1
            stats['total_payout'] += payout

        # Record losses
        if losing_qty > 0:
            Transaction.objects.create(
                user=user,
                type=Transaction.Type.SETTLEMENT_LOSS,
                amount=Decimal('0.00'),
                balance_before=user.balance,
                balance_after=user.balance,
                market=market,
                description=f"Lost {losing_qty} {'NO' if outcome == 'yes' else 'YES'} contracts (worthless)"
            )
            stats['losers'] += 1

        # Clear positions
        position.yes_quantity = 0
        position.no_quantity = 0
        position.save()

    # Update market status
    if outcome == 'yes':
        market.status = Market.Status.SETTLED_YES
    else:
        market.status = Market.Status.SETTLED_NO
    market.save()

    return stats


@transaction.atomic
def mint_complete_set(market, user, quantity):
    """
    Mint complete sets of YES+NO contracts.

    User pays $1 per set, receives 1 YES and 1 NO contract.
    This is the canonical way to create new shares without a counterparty.

    Args:
        market: Market instance
        user: User minting the set
        quantity: Number of complete sets to mint

    Returns:
        dict with minting details
    """
    if not market.is_trading_active:
        raise MarketNotActiveError(market)

    if quantity <= 0:
        raise InvalidQuantityError(quantity)

    cost = Decimal(quantity)  # $1 per set
    fee = cost * Decimal('0.02')  # 2% transaction fee
    total_cost = cost + fee

    user = User.objects.select_for_update().get(pk=user.pk)

    if user.available_balance < total_cost:
        raise InsufficientFundsError(total_cost, user.available_balance)

    balance_before = user.balance
    user.balance -= total_cost
    user.save()

    # Track fee collected by the market
    market.fees_collected = F('fees_collected') + fee
    market.save(update_fields=['fees_collected'])

    # Get or create position
    position, _ = Position.objects.get_or_create(user=user, market=market)

    # Add contracts at 50c each (fair value for complete set)
    old_yes_qty = position.yes_quantity
    old_no_qty = position.no_quantity

    # Update YES position
    if old_yes_qty > 0:
        position.yes_avg_cost = (
            (position.yes_avg_cost * old_yes_qty + Decimal('50.00') * quantity) /
            (old_yes_qty + quantity)
        )
    else:
        position.yes_avg_cost = Decimal('50.00')
    position.yes_quantity += quantity

    # Update NO position
    if old_no_qty > 0:
        position.no_avg_cost = (
            (position.no_avg_cost * old_no_qty + Decimal('50.00') * quantity) /
            (old_no_qty + quantity)
        )
    else:
        position.no_avg_cost = Decimal('50.00')
    position.no_quantity += quantity

    position.save()

    # Update market shares outstanding
    market.total_shares_outstanding = F('total_shares_outstanding') + quantity
    market.save()
    market.refresh_from_db()

    # Create transaction for the mint
    Transaction.objects.create(
        user=user,
        type=Transaction.Type.MINT,
        amount=-cost,
        balance_before=balance_before,
        balance_after=user.balance + fee,  # Before fee was deducted
        market=market,
        description=f"Minted {quantity} complete sets (YES+NO) @ $1/set"
    )

    # Create transaction for the fee
    Transaction.objects.create(
        user=user,
        type=Transaction.Type.TRANSACTION_FEE,
        amount=-fee,
        balance_before=user.balance + fee,
        balance_after=user.balance,
        market=market,
        description=f"Transaction fee (2%) on minting {quantity} complete sets"
    )

    return {
        'quantity': quantity,
        'cost': cost,
        'fee': fee,
        'total_cost': total_cost,
        'yes_received': quantity,
        'no_received': quantity
    }


@transaction.atomic
def redeem_complete_set(market, user, quantity):
    """
    Redeem complete sets of YES+NO contracts for $1 each.

    User gives up 1 YES and 1 NO contract, receives $1.
    This burns shares and releases collateral.

    Args:
        market: Market instance
        user: User redeeming the set
        quantity: Number of complete sets to redeem

    Returns:
        dict with redemption details
    """
    if not market.is_trading_active:
        raise MarketNotActiveError(market)

    if quantity <= 0:
        raise InvalidQuantityError(quantity)

    user = User.objects.select_for_update().get(pk=user.pk)

    # Verify user has enough of both contract types
    position = Position.objects.filter(user=user, market=market).first()

    if not position:
        raise InsufficientPositionError(quantity, 0, 'complete set')

    if position.yes_quantity < quantity:
        raise InsufficientPositionError(quantity, position.yes_quantity, 'yes')

    if position.no_quantity < quantity:
        raise InsufficientPositionError(quantity, position.no_quantity, 'no')

    payout = Decimal(quantity)  # $1 per set
    fee = payout * Decimal('0.02')  # 2% transaction fee
    net_payout = payout - fee

    # Calculate realized P&L (redeeming at 50c each, since pair = $1)
    yes_pnl = Decimal(quantity * (50 - float(position.yes_avg_cost))) / 100
    no_pnl = Decimal(quantity * (50 - float(position.no_avg_cost))) / 100

    # Update position
    position.yes_quantity -= quantity
    position.no_quantity -= quantity
    position.realized_pnl += yes_pnl + no_pnl
    position.save()

    # Credit user (minus fee)
    balance_before = user.balance
    user.balance += net_payout
    user.save()

    # Track fee collected by the market
    market.fees_collected = F('fees_collected') + fee
    market.save(update_fields=['fees_collected'])

    # Update market shares outstanding
    market.total_shares_outstanding = F('total_shares_outstanding') - quantity
    market.save()
    market.refresh_from_db()

    # Create transaction for the redeem
    Transaction.objects.create(
        user=user,
        type=Transaction.Type.REDEEM,
        amount=net_payout,
        balance_before=balance_before,
        balance_after=user.balance,
        market=market,
        description=f"Redeemed {quantity} complete sets (YES+NO) @ $1/set (after 2% fee)"
    )

    # Create transaction for the fee
    Transaction.objects.create(
        user=user,
        type=Transaction.Type.TRANSACTION_FEE,
        amount=-fee,
        balance_before=balance_before + payout,
        balance_after=user.balance,
        market=market,
        description=f"Transaction fee (2%) on redemption of {quantity} complete sets"
    )

    return {
        'quantity': quantity,
        'payout': payout,
        'fee': fee,
        'net_payout': net_payout,
        'yes_burned': quantity,
        'no_burned': quantity
    }
