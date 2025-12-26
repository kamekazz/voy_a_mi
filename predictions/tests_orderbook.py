"""
Comprehensive Order Book Test Suite for Polymarket-Style Prediction Market.

Tests cover:
- A: Direct Matching (4 tests)
- B: Mint Matching (4 tests)
- C: Merge Matching (3 tests)
- D: Price-Time Priority (3 tests)
- E: Partial Fills (2 tests)
- F: Market Orders (2 tests)
- G: Fund Reservation (3 tests)
- H: Position Updates (3 tests)
- I: Settlement (3 tests)
- J: Complete Sets (3 tests)
- K: Order Cancellation (4 tests)
- L: Edge Cases (7 tests)
- M: Priority (1 test)

Total: 42 test scenarios

Run with: python manage.py test predictions.tests_orderbook -v 2
"""

from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta

from .models import User, Event, Market, Order, Trade, Position, Transaction, Category
from .engine.matching import MatchingEngine, get_orderbook, settle_market, mint_complete_set, redeem_complete_set
from .exceptions import (
    InsufficientFundsError,
    InsufficientPositionError,
    InvalidPriceError,
    InvalidQuantityError,
    MarketNotActiveError,
    OrderCancellationError,
)


class OrderBookTestBase(TestCase):
    """Base test class with common setup for all order book tests."""

    def setUp(self):
        """Create test users, event, and market."""
        # Create test users
        self.user_a = User.objects.create_user(
            username='user_a',
            email='a@test.com',
            password='testpass123',
            balance=Decimal('100.00')
        )
        self.user_b = User.objects.create_user(
            username='user_b',
            email='b@test.com',
            password='testpass123',
            balance=Decimal('100.00')
        )
        self.user_c = User.objects.create_user(
            username='user_c',
            email='c@test.com',
            password='testpass123',
            balance=Decimal('100.00')
        )

        # Create category
        self.category = Category.objects.create(
            name='Test Category',
            slug='test-category'
        )

        # Create event
        self.event = Event.objects.create(
            title='Test Event',
            slug='test-event',
            description='A test event',
            category=self.category,
            resolution_source='Test',
            trading_starts=timezone.now() - timedelta(days=1),
            trading_ends=timezone.now() + timedelta(days=30),
            status=Event.Status.ACTIVE
        )

        # Create market
        self.market = Market.objects.create(
            event=self.event,
            title='Test Market',
            slug='test-market',
            status=Market.Status.ACTIVE
        )

        # Create matching engine
        self.engine = MatchingEngine(self.market)

    def create_position(self, user, yes_qty=0, no_qty=0, yes_avg_cost=50, no_avg_cost=50):
        """Helper to create a position for a user."""
        position, _ = Position.objects.get_or_create(
            user=user,
            market=self.market,
            defaults={
                'yes_quantity': yes_qty,
                'no_quantity': no_qty,
                'yes_avg_cost': Decimal(str(yes_avg_cost)),
                'no_avg_cost': Decimal(str(no_avg_cost)),
            }
        )
        if position.yes_quantity != yes_qty or position.no_quantity != no_qty:
            position.yes_quantity = yes_qty
            position.no_quantity = no_qty
            position.yes_avg_cost = Decimal(str(yes_avg_cost))
            position.no_avg_cost = Decimal(str(no_avg_cost))
            position.save()
        return position


# =============================================================================
# A: DIRECT MATCHING TESTS (4 tests)
# =============================================================================

class DirectMatchingTest(OrderBookTestBase):
    """Test direct order matching (BUY vs SELL on same outcome)."""

    def test_a1_buy_sell_yes_match(self):
        """A1: BUY YES vs SELL YES Match at same price."""
        # Setup: User B has YES shares
        self.create_position(self.user_b, yes_qty=10)

        # Action: B sells, then A buys
        order_b, _ = self.engine.place_order(
            user=self.user_b,
            side='sell',
            contract_type='yes',
            price=55,
            quantity=5
        )

        order_a, trades = self.engine.place_order(
            user=self.user_a,
            side='buy',
            contract_type='yes',
            price=55,
            quantity=5
        )

        # Verify
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].price, 55)
        self.assertEqual(trades[0].quantity, 5)
        self.assertEqual(trades[0].trade_type, Trade.TradeType.DIRECT)

    def test_a2_price_improvement(self):
        """A2: Trade executes at maker (better) price."""
        # Setup: User B has YES shares
        self.create_position(self.user_b, yes_qty=10)

        # B sells at 45c, A buys at 55c -> should trade at 45c
        self.engine.place_order(
            user=self.user_b,
            side='sell',
            contract_type='yes',
            price=45,
            quantity=5
        )

        order_a, trades = self.engine.place_order(
            user=self.user_a,
            side='buy',
            contract_type='yes',
            price=55,
            quantity=5
        )

        # Verify trade at maker price (45c)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].price, 45)

    def test_a3_buy_sell_no_match(self):
        """A3: BUY NO vs SELL NO Match."""
        # Setup: User B has NO shares
        self.create_position(self.user_b, no_qty=10)

        # B sells NO, A buys NO
        self.engine.place_order(
            user=self.user_b,
            side='sell',
            contract_type='no',
            price=60,
            quantity=5
        )

        order_a, trades = self.engine.place_order(
            user=self.user_a,
            side='buy',
            contract_type='no',
            price=60,
            quantity=5
        )

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].contract_type, 'no')
        self.assertEqual(trades[0].trade_type, Trade.TradeType.DIRECT)

    def test_a4_no_match_prices_dont_cross(self):
        """A4: No match when bid < ask."""
        # Setup: User B has YES shares
        self.create_position(self.user_b, yes_qty=10)

        # B sells at 60c, A bids at 50c -> no match
        self.engine.place_order(
            user=self.user_b,
            side='sell',
            contract_type='yes',
            price=60,
            quantity=5
        )

        order_a, trades = self.engine.place_order(
            user=self.user_a,
            side='buy',
            contract_type='yes',
            price=50,
            quantity=5
        )

        self.assertEqual(len(trades), 0)
        self.assertEqual(order_a.status, Order.Status.OPEN)


# =============================================================================
# B: MINT MATCHING TESTS (4 tests)
# =============================================================================

class MintMatchingTest(OrderBookTestBase):
    """Test mint matching (BUY YES + BUY NO at complementary prices)."""

    def test_b1_exact_mint_at_100c(self):
        """B1: Exact mint when BUY YES + BUY NO = $1.00."""
        # A buys YES @ 60c, B buys NO @ 40c = $1.00
        order_a, _ = self.engine.place_order(
            user=self.user_a,
            side='buy',
            contract_type='yes',
            price=60,
            quantity=10
        )

        order_b, trades = self.engine.place_order(
            user=self.user_b,
            side='buy',
            contract_type='no',
            price=40,
            quantity=10
        )

        # Verify mint trade
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].trade_type, Trade.TradeType.MINT)

        # Check positions
        pos_a = Position.objects.get(user=self.user_a, market=self.market)
        pos_b = Position.objects.get(user=self.user_b, market=self.market)
        self.assertEqual(pos_a.yes_quantity, 10)
        self.assertEqual(pos_b.no_quantity, 10)

    def test_b2_mint_with_surplus(self):
        """B2: Mint when prices sum to > $1.00."""
        # A buys YES @ 65c, B buys NO @ 45c = $1.10
        self.engine.place_order(
            user=self.user_a,
            side='buy',
            contract_type='yes',
            price=65,
            quantity=5
        )

        order_b, trades = self.engine.place_order(
            user=self.user_b,
            side='buy',
            contract_type='no',
            price=45,
            quantity=5
        )

        # Should still mint
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].trade_type, Trade.TradeType.MINT)

    def test_b3_no_mint_under_100c(self):
        """B3: No mint when prices sum to < $1.00."""
        # A buys YES @ 40c, B buys NO @ 40c = $0.80 (not enough)
        self.engine.place_order(
            user=self.user_a,
            side='buy',
            contract_type='yes',
            price=40,
            quantity=5
        )

        order_b, trades = self.engine.place_order(
            user=self.user_b,
            side='buy',
            contract_type='no',
            price=40,
            quantity=5
        )

        # No mint should occur
        self.assertEqual(len(trades), 0)
        self.assertEqual(order_b.status, Order.Status.OPEN)

    def test_b4_partial_mint(self):
        """B4: Partial mint when quantities differ."""
        # A buys 10 YES @ 60c, B buys only 3 NO @ 40c
        self.engine.place_order(
            user=self.user_a,
            side='buy',
            contract_type='yes',
            price=60,
            quantity=10
        )

        order_b, trades = self.engine.place_order(
            user=self.user_b,
            side='buy',
            contract_type='no',
            price=40,
            quantity=3
        )

        # Should mint 3
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].quantity, 3)

        # A's order should be partially filled
        order_a = Order.objects.get(user=self.user_a, market=self.market, side='buy')
        self.assertEqual(order_a.filled_quantity, 3)
        self.assertEqual(order_a.status, Order.Status.PARTIALLY_FILLED)


# =============================================================================
# C: MERGE MATCHING TESTS (3 tests)
# =============================================================================

class MergeMatchingTest(OrderBookTestBase):
    """Test merge matching (SELL YES + SELL NO at complementary prices)."""

    def test_c1_exact_merge_at_100c(self):
        """C1: Exact merge when SELL YES + SELL NO = $1.00."""
        # Setup: Users have shares
        self.create_position(self.user_a, yes_qty=10)
        self.create_position(self.user_b, no_qty=10)
        self.market.total_shares_outstanding = 10
        self.market.save()

        # A sells YES @ 55c, B sells NO @ 45c = $1.00
        self.engine.place_order(
            user=self.user_a,
            side='sell',
            contract_type='yes',
            price=55,
            quantity=5
        )

        order_b, trades = self.engine.place_order(
            user=self.user_b,
            side='sell',
            contract_type='no',
            price=45,
            quantity=5
        )

        # Verify merge trade
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].trade_type, Trade.TradeType.MERGE)

        # Check shares burned
        self.market.refresh_from_db()
        self.assertEqual(self.market.total_shares_outstanding, 5)

    def test_c2_merge_with_discount(self):
        """C2: Merge when prices sum to < $1.00."""
        # Setup
        self.create_position(self.user_a, yes_qty=10)
        self.create_position(self.user_b, no_qty=10)
        self.market.total_shares_outstanding = 10
        self.market.save()

        # A sells YES @ 50c, B sells NO @ 40c = $0.90 (discount)
        self.engine.place_order(
            user=self.user_a,
            side='sell',
            contract_type='yes',
            price=50,
            quantity=5
        )

        order_b, trades = self.engine.place_order(
            user=self.user_b,
            side='sell',
            contract_type='no',
            price=40,
            quantity=5
        )

        # Should still merge
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].trade_type, Trade.TradeType.MERGE)

    def test_c3_no_merge_over_100c(self):
        """C3: No merge when prices sum to > $1.00."""
        # Setup
        self.create_position(self.user_a, yes_qty=10)
        self.create_position(self.user_b, no_qty=10)

        # A sells YES @ 60c, B sells NO @ 60c = $1.20 (can't pay this much)
        self.engine.place_order(
            user=self.user_a,
            side='sell',
            contract_type='yes',
            price=60,
            quantity=5
        )

        order_b, trades = self.engine.place_order(
            user=self.user_b,
            side='sell',
            contract_type='no',
            price=60,
            quantity=5
        )

        # No merge
        self.assertEqual(len(trades), 0)


# =============================================================================
# D: PRICE-TIME PRIORITY TESTS (3 tests)
# =============================================================================

class PriceTimePriorityTest(OrderBookTestBase):
    """Test price-time priority matching."""

    def test_d1_price_priority_higher_bid(self):
        """D1: Higher bid gets matched first."""
        # Setup: C has shares to sell
        self.create_position(self.user_c, yes_qty=10)

        # A bids 50c, B bids 55c
        self.engine.place_order(self.user_a, 'buy', 'yes', 50, 5)
        self.engine.place_order(self.user_b, 'buy', 'yes', 55, 5)

        # C sells at 50c
        _, trades = self.engine.place_order(self.user_c, 'sell', 'yes', 50, 5)

        # B should match (higher price)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].buyer, self.user_b)

    def test_d2_time_priority_same_price(self):
        """D2: Earlier order gets matched when prices equal."""
        # Setup: C has shares
        self.create_position(self.user_c, yes_qty=10)

        # A bids first, then B bids at same price
        self.engine.place_order(self.user_a, 'buy', 'yes', 55, 5)
        self.engine.place_order(self.user_b, 'buy', 'yes', 55, 5)

        # C sells
        _, trades = self.engine.place_order(self.user_c, 'sell', 'yes', 55, 5)

        # A should match (placed first)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].buyer, self.user_a)

    def test_d3_price_priority_lower_ask(self):
        """D3: Lower ask gets matched first."""
        # Setup: A and B have shares
        self.create_position(self.user_a, yes_qty=10)
        self.create_position(self.user_b, yes_qty=10)

        # A asks 55c, B asks 50c
        self.engine.place_order(self.user_a, 'sell', 'yes', 55, 5)
        self.engine.place_order(self.user_b, 'sell', 'yes', 50, 5)

        # C buys at 60c
        _, trades = self.engine.place_order(self.user_c, 'buy', 'yes', 60, 5)

        # B should match (lower price)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].seller, self.user_b)


# =============================================================================
# E: PARTIAL FILL TESTS (2 tests)
# =============================================================================

class PartialFillTest(OrderBookTestBase):
    """Test partial order fills."""

    def test_e1_single_partial_fill(self):
        """E1: Order partially filled when liquidity insufficient."""
        # Setup: B has only 3 shares
        self.create_position(self.user_b, yes_qty=3)

        # B sells 3, A tries to buy 10
        self.engine.place_order(self.user_b, 'sell', 'yes', 50, 3)
        order_a, trades = self.engine.place_order(self.user_a, 'buy', 'yes', 50, 10)

        # Should fill 3
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].quantity, 3)
        self.assertEqual(order_a.filled_quantity, 3)
        self.assertEqual(order_a.status, Order.Status.PARTIALLY_FILLED)

    def test_e2_multiple_fills(self):
        """E2: Order filled from multiple counterparty orders."""
        # Setup: B and C have shares
        self.create_position(self.user_b, yes_qty=5)
        self.create_position(self.user_c, yes_qty=5)

        # B sells 5 @ 50c, C sells 5 @ 52c
        self.engine.place_order(self.user_b, 'sell', 'yes', 50, 5)
        self.engine.place_order(self.user_c, 'sell', 'yes', 52, 5)

        # A buys 8 @ 55c
        order_a, trades = self.engine.place_order(self.user_a, 'buy', 'yes', 55, 8)

        # Should have 2 trades: 5@50c + 3@52c
        self.assertEqual(len(trades), 2)
        self.assertEqual(order_a.filled_quantity, 8)
        self.assertEqual(order_a.status, Order.Status.FILLED)


# =============================================================================
# F: MARKET ORDER TESTS (2 tests)
# =============================================================================

class MarketOrderTest(OrderBookTestBase):
    """Test market order execution."""

    def test_f1_market_buy_at_best_ask(self):
        """F1: Market buy executes at best ask."""
        # Setup: B has shares and sells
        self.create_position(self.user_b, yes_qty=10)
        self.engine.place_order(self.user_b, 'sell', 'yes', 55, 5)

        # A places market buy (uses order_type='market')
        order_a, trades = self.engine.place_order(
            self.user_a, 'buy', 'yes', 99, 5, order_type='market'
        )

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].price, 55)

    def test_f2_market_order_no_liquidity(self):
        """F2: Market order with no liquidity uses last price."""
        # Empty book - market order uses last_yes_price (50 from setUp)
        order_a, trades = self.engine.place_order(
            self.user_a, 'buy', 'yes', 99, 5, order_type='market'
        )

        # No trades, order should be placed at last price
        self.assertEqual(len(trades), 0)
        self.assertEqual(order_a.status, Order.Status.OPEN)
        self.assertEqual(order_a.price, 50)  # Uses last_yes_price


# =============================================================================
# G: FUND RESERVATION TESTS (3 tests)
# =============================================================================

class FundReservationTest(OrderBookTestBase):
    """Test fund reservation on order placement."""

    def test_g1_reserve_on_buy(self):
        """G1: Funds reserved when buy order placed."""
        initial_balance = self.user_a.balance

        # Place buy order for 10 @ 60c = $6.00
        self.engine.place_order(self.user_a, 'buy', 'yes', 60, 10)

        self.user_a.refresh_from_db()
        self.assertEqual(self.user_a.reserved_balance, Decimal('6.00'))
        # Balance should still be the same (reserved from it)
        self.assertEqual(self.user_a.balance, initial_balance)

    def test_g2_release_on_trade(self):
        """G2: Funds released and settled on trade."""
        # Setup: B has shares
        self.create_position(self.user_b, yes_qty=10)

        # A places buy @ 60c, B sells @ 55c -> trade at 55c
        self.engine.place_order(self.user_a, 'buy', 'yes', 60, 10)
        self.engine.place_order(self.user_b, 'sell', 'yes', 55, 10)

        self.user_a.refresh_from_db()
        # Reserved should be 0 after trade
        self.assertEqual(self.user_a.reserved_balance, Decimal('0.00'))

    def test_g3_release_on_cancel(self):
        """G3: Funds released on order cancellation."""
        # Place order
        order, _ = self.engine.place_order(self.user_a, 'buy', 'yes', 60, 10)

        self.user_a.refresh_from_db()
        self.assertEqual(self.user_a.reserved_balance, Decimal('6.00'))

        # Cancel
        self.engine.cancel_order(order, self.user_a)

        self.user_a.refresh_from_db()
        self.assertEqual(self.user_a.reserved_balance, Decimal('0.00'))


# =============================================================================
# H: POSITION UPDATE TESTS (3 tests)
# =============================================================================

class PositionUpdateTest(OrderBookTestBase):
    """Test position updates after trades."""

    def test_h1_position_created_on_buy(self):
        """H1: Position created on first buy."""
        # Setup: B has shares
        self.create_position(self.user_b, yes_qty=10)

        # Execute trade
        self.engine.place_order(self.user_b, 'sell', 'yes', 50, 5)
        self.engine.place_order(self.user_a, 'buy', 'yes', 50, 5)

        # Check A's position
        pos_a = Position.objects.get(user=self.user_a, market=self.market)
        self.assertEqual(pos_a.yes_quantity, 5)
        self.assertEqual(pos_a.yes_avg_cost, Decimal('50.00'))

    def test_h2_avg_cost_updated(self):
        """H2: Average cost updated on additional purchase."""
        # Setup: A already has position, B has shares
        self.create_position(self.user_a, yes_qty=10, yes_avg_cost=40)
        self.create_position(self.user_b, yes_qty=10)

        # A buys more @ 60c
        self.engine.place_order(self.user_b, 'sell', 'yes', 60, 10)
        self.engine.place_order(self.user_a, 'buy', 'yes', 60, 10)

        pos_a = Position.objects.get(user=self.user_a, market=self.market)
        self.assertEqual(pos_a.yes_quantity, 20)
        # (10*40 + 10*60) / 20 = 50
        self.assertEqual(pos_a.yes_avg_cost, Decimal('50.00'))

    def test_h3_realized_pnl_on_sell(self):
        """H3: Realized P&L calculated on sell."""
        # Setup: A has shares at 40c avg
        self.create_position(self.user_a, yes_qty=10, yes_avg_cost=40)

        # A sells 5 @ 60c -> profit = 5 * (60-40) / 100 = $1.00
        self.engine.place_order(self.user_a, 'sell', 'yes', 60, 5)
        self.engine.place_order(self.user_b, 'buy', 'yes', 60, 5)

        pos_a = Position.objects.get(user=self.user_a, market=self.market)
        self.assertEqual(pos_a.yes_quantity, 5)
        self.assertEqual(pos_a.realized_pnl, Decimal('1.00'))


# =============================================================================
# I: SETTLEMENT TESTS (3 tests)
# =============================================================================

class SettlementTest(OrderBookTestBase):
    """Test market settlement."""

    def test_i1_settle_yes_winners_paid(self):
        """I1: YES holders paid on YES settlement."""
        # Setup: A has YES, B has NO
        self.create_position(self.user_a, yes_qty=10)
        self.create_position(self.user_b, no_qty=10)
        initial_a = self.user_a.balance
        initial_b = self.user_b.balance

        # Settle as YES
        settle_market(self.market, 'yes')

        self.user_a.refresh_from_db()
        self.user_b.refresh_from_db()
        self.market.refresh_from_db()

        # A should receive $10 (10 * $1)
        self.assertEqual(self.user_a.balance, initial_a + Decimal('10.00'))
        # B gets nothing
        self.assertEqual(self.user_b.balance, initial_b)
        self.assertEqual(self.market.status, Market.Status.SETTLED_YES)

    def test_i2_settle_no_winners_paid(self):
        """I2: NO holders paid on NO settlement."""
        # Setup: A has YES, B has NO
        self.create_position(self.user_a, yes_qty=10)
        self.create_position(self.user_b, no_qty=10)
        initial_a = self.user_a.balance
        initial_b = self.user_b.balance

        # Settle as NO
        settle_market(self.market, 'no')

        self.user_a.refresh_from_db()
        self.user_b.refresh_from_db()

        # B should receive $10
        self.assertEqual(self.user_b.balance, initial_b + Decimal('10.00'))
        # A gets nothing
        self.assertEqual(self.user_a.balance, initial_a)

    def test_i3_open_orders_cancelled(self):
        """I3: Open orders cancelled on settlement."""
        # Place open order
        order, _ = self.engine.place_order(self.user_a, 'buy', 'yes', 50, 5)

        # Settle
        settle_market(self.market, 'yes')

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)


# =============================================================================
# J: COMPLETE SET TESTS (3 tests)
# =============================================================================

class CompleteSetTest(OrderBookTestBase):
    """Test mint/redeem complete sets."""

    def test_j1_mint_complete_set(self):
        """J1: User can mint complete sets for $1 each."""
        initial_balance = self.user_a.balance
        initial_shares = self.market.total_shares_outstanding

        result = mint_complete_set(self.market, self.user_a, 5)

        self.user_a.refresh_from_db()
        self.market.refresh_from_db()
        pos_a = Position.objects.get(user=self.user_a, market=self.market)

        self.assertEqual(self.user_a.balance, initial_balance - Decimal('5.00'))
        self.assertEqual(pos_a.yes_quantity, 5)
        self.assertEqual(pos_a.no_quantity, 5)
        self.assertEqual(self.market.total_shares_outstanding, initial_shares + 5)

    def test_j2_redeem_complete_set(self):
        """J2: User can redeem complete sets for $1 each."""
        # Setup: A has both YES and NO
        self.create_position(self.user_a, yes_qty=10, no_qty=10)
        self.market.total_shares_outstanding = 10
        self.market.save()
        initial_balance = self.user_a.balance

        result = redeem_complete_set(self.market, self.user_a, 5)

        self.user_a.refresh_from_db()
        self.market.refresh_from_db()
        pos_a = Position.objects.get(user=self.user_a, market=self.market)

        self.assertEqual(self.user_a.balance, initial_balance + Decimal('5.00'))
        self.assertEqual(pos_a.yes_quantity, 5)
        self.assertEqual(pos_a.no_quantity, 5)
        self.assertEqual(self.market.total_shares_outstanding, 5)

    def test_j3_redeem_insufficient_fails(self):
        """J3: Redeem fails with insufficient position."""
        # Setup: A has 5 YES but 10 NO
        self.create_position(self.user_a, yes_qty=5, no_qty=10)

        with self.assertRaises(InsufficientPositionError):
            redeem_complete_set(self.market, self.user_a, 10)


# =============================================================================
# K: ORDER CANCELLATION TESTS (4 tests)
# =============================================================================

class OrderCancellationTest(OrderBookTestBase):
    """Test order cancellation."""

    def test_k1_cancel_open_order(self):
        """K1: Can cancel open order."""
        order, _ = self.engine.place_order(self.user_a, 'buy', 'yes', 55, 10)

        self.engine.cancel_order(order, self.user_a)

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)

    def test_k2_cancel_partially_filled(self):
        """K2: Can cancel partially filled order."""
        # Setup: B has 3 shares
        self.create_position(self.user_b, yes_qty=3)

        # A places order for 10, gets filled for 3
        self.engine.place_order(self.user_b, 'sell', 'yes', 55, 3)
        order, _ = self.engine.place_order(self.user_a, 'buy', 'yes', 55, 10)

        self.assertEqual(order.filled_quantity, 3)
        self.assertEqual(order.status, Order.Status.PARTIALLY_FILLED)

        # Cancel remaining
        self.engine.cancel_order(order, self.user_a)

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)

    def test_k3_cannot_cancel_filled(self):
        """K3: Cannot cancel filled order."""
        # Setup and execute full fill
        self.create_position(self.user_b, yes_qty=10)
        self.engine.place_order(self.user_b, 'sell', 'yes', 55, 10)
        order, _ = self.engine.place_order(self.user_a, 'buy', 'yes', 55, 10)

        self.assertEqual(order.status, Order.Status.FILLED)

        with self.assertRaises(OrderCancellationError):
            self.engine.cancel_order(order, self.user_a)

    def test_k4_cannot_cancel_others_order(self):
        """K4: Cannot cancel another user's order."""
        order, _ = self.engine.place_order(self.user_a, 'buy', 'yes', 55, 10)

        with self.assertRaises(OrderCancellationError):
            self.engine.cancel_order(order, self.user_b)


# =============================================================================
# L: EDGE CASE TESTS (7 tests)
# =============================================================================

class EdgeCaseTest(OrderBookTestBase):
    """Test edge cases and error handling."""

    def test_l1_self_trade_prevention(self):
        """L1: Self-trading is prevented."""
        # Setup: A has shares and open buy order
        self.create_position(self.user_a, yes_qty=10)
        self.engine.place_order(self.user_a, 'buy', 'yes', 60, 5)

        # A tries to sell into own order
        _, trades = self.engine.place_order(self.user_a, 'sell', 'yes', 55, 5)

        # No self-trade should occur
        self.assertEqual(len(trades), 0)

    def test_l2_empty_orderbook(self):
        """L2: Order on empty book stays open."""
        order, trades = self.engine.place_order(self.user_a, 'buy', 'yes', 50, 5)

        self.assertEqual(len(trades), 0)
        self.assertEqual(order.status, Order.Status.OPEN)

    def test_l3_zero_quantity_rejected(self):
        """L3: Zero quantity order rejected."""
        with self.assertRaises(InvalidQuantityError):
            self.engine.place_order(self.user_a, 'buy', 'yes', 50, 0)

    def test_l4_price_zero_rejected(self):
        """L4: Price=0 rejected."""
        with self.assertRaises(InvalidPriceError):
            self.engine.place_order(self.user_a, 'buy', 'yes', 0, 5)

    def test_l5_price_100_rejected(self):
        """L5: Price=100 rejected."""
        with self.assertRaises(InvalidPriceError):
            self.engine.place_order(self.user_a, 'buy', 'yes', 100, 5)

    def test_l6_insufficient_funds_rejected(self):
        """L6: Insufficient funds rejected."""
        # User has $100, try to buy $500 worth
        with self.assertRaises(InsufficientFundsError):
            self.engine.place_order(self.user_a, 'buy', 'yes', 50, 1000)

    def test_l7_insufficient_position_rejected(self):
        """L7: Insufficient position for sell rejected."""
        # User has 5 YES, tries to sell 10
        self.create_position(self.user_a, yes_qty=5)

        with self.assertRaises(InsufficientPositionError):
            self.engine.place_order(self.user_a, 'sell', 'yes', 50, 10)


# =============================================================================
# M: PRIORITY TEST (1 test)
# =============================================================================

class PriorityTest(OrderBookTestBase):
    """Test direct matching has priority over mint."""

    def test_m1_direct_over_mint(self):
        """M1: Direct match takes priority over mint match."""
        # Setup: B has NO (for potential mint), C has YES to sell
        self.create_position(self.user_c, yes_qty=10)

        # B places buy NO @ 50c (potential mint counterparty)
        self.engine.place_order(self.user_b, 'buy', 'no', 50, 5)

        # C places sell YES @ 55c (direct match target)
        self.engine.place_order(self.user_c, 'sell', 'yes', 55, 5)

        # A places buy YES @ 60c
        _, trades = self.engine.place_order(self.user_a, 'buy', 'yes', 60, 5)

        # Should direct match with C's sell, not mint with B's buy NO
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].trade_type, Trade.TradeType.DIRECT)
        self.assertEqual(trades[0].seller, self.user_c)
