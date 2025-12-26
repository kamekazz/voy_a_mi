"""
Comprehensive tests for the Polymarket-style prediction market.

Tests cover:
- Direct order matching (BUY vs SELL same contract)
- Minting (BUY YES + BUY NO = create shares)
- Merging (SELL YES + SELL NO = burn shares)
- Market settlement
- Direct mint/redeem complete sets
- Integration workflows
"""

from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from .models import User, Category, Event, Market, Order, Trade, Position, Transaction
from .engine.matching import MatchingEngine, get_orderbook
from .exceptions import (
    InsufficientFundsError,
    InsufficientPositionError,
    MarketNotActiveError,
)


class BaseTestCase(TestCase):
    """Base test case with common setup."""

    def setUp(self):
        # Create test users with $100 each
        self.user1 = User.objects.create_user(
            username='trader1',
            password='test123',
            balance=Decimal('100.00')
        )
        self.user2 = User.objects.create_user(
            username='trader2',
            password='test123',
            balance=Decimal('100.00')
        )
        self.user3 = User.objects.create_user(
            username='trader3',
            password='test123',
            balance=Decimal('100.00')
        )

        # Create test category
        self.category = Category.objects.create(
            name='Test',
            slug='test'
        )

        # Create test event
        self.event = Event.objects.create(
            title='Test Event',
            slug='test-event',
            description='A test event',
            category=self.category,
            resolution_source='Test source',
            trading_starts=timezone.now() - timedelta(hours=1),
            trading_ends=timezone.now() + timedelta(days=7),
            status=Event.Status.ACTIVE
        )

        # Create test market (AMM disabled for orderbook tests)
        self.market = Market.objects.create(
            event=self.event,
            title='Test Market',
            slug='test-market',
            status=Market.Status.ACTIVE,
            amm_enabled=False
        )


class DirectMatchingTest(BaseTestCase):
    """Test direct order matching (existing functionality)."""

    def test_buy_sell_match_yes(self):
        """Test BUY YES matches SELL YES."""
        engine = MatchingEngine(self.market)

        # User2 needs position to sell
        Position.objects.create(
            user=self.user2,
            market=self.market,
            yes_quantity=10,
            yes_avg_cost=Decimal('40.00')
        )

        # User2 places sell order
        sell_order, _ = engine.place_order(
            user=self.user2,
            side='sell',
            contract_type='yes',
            price=55,
            quantity=5
        )

        # User1 places buy order that matches
        buy_order, trades = engine.place_order(
            user=self.user1,
            side='buy',
            contract_type='yes',
            price=55,
            quantity=5
        )

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].quantity, 5)
        self.assertEqual(trades[0].price, 55)
        self.assertEqual(trades[0].trade_type, Trade.TradeType.DIRECT)

        # Verify orders filled
        buy_order.refresh_from_db()
        sell_order.refresh_from_db()
        self.assertEqual(buy_order.status, Order.Status.FILLED)
        self.assertEqual(sell_order.status, Order.Status.FILLED)

        # Verify positions
        buyer_pos = Position.objects.get(user=self.user1, market=self.market)
        seller_pos = Position.objects.get(user=self.user2, market=self.market)
        self.assertEqual(buyer_pos.yes_quantity, 5)
        self.assertEqual(seller_pos.yes_quantity, 5)  # Had 10, sold 5

    def test_no_self_trade(self):
        """Test that users cannot trade with themselves."""
        engine = MatchingEngine(self.market)

        # User1 places buy order
        buy_order, _ = engine.place_order(
            user=self.user1,
            side='buy',
            contract_type='yes',
            price=60,
            quantity=5
        )

        # Give user1 a position to sell
        Position.objects.create(
            user=self.user1,
            market=self.market,
            yes_quantity=10
        )

        # User1 places sell order - should not match own buy
        sell_order, trades = engine.place_order(
            user=self.user1,
            side='sell',
            contract_type='yes',
            price=55,
            quantity=5
        )

        self.assertEqual(len(trades), 0)
        buy_order.refresh_from_db()
        self.assertEqual(buy_order.status, Order.Status.OPEN)

    def test_partial_fill(self):
        """Test partial order fills."""
        engine = MatchingEngine(self.market)

        Position.objects.create(
            user=self.user2,
            market=self.market,
            yes_quantity=3,
            yes_avg_cost=Decimal('40.00')
        )

        # Sell 3 contracts
        engine.place_order(
            user=self.user2,
            side='sell',
            contract_type='yes',
            price=50,
            quantity=3
        )

        # Try to buy 5 - should only fill 3
        buy_order, trades = engine.place_order(
            user=self.user1,
            side='buy',
            contract_type='yes',
            price=50,
            quantity=5
        )

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].quantity, 3)
        buy_order.refresh_from_db()
        self.assertEqual(buy_order.status, Order.Status.PARTIALLY_FILLED)
        self.assertEqual(buy_order.filled_quantity, 3)


class MintingTest(BaseTestCase):
    """Test minting logic (BUY YES + BUY NO = create shares)."""

    def test_mint_match_exact(self):
        """Test BUY YES + BUY NO at exactly $1 creates new shares."""
        engine = MatchingEngine(self.market)

        # User1 places BUY YES @ 60c
        yes_order, _ = engine.place_order(
            user=self.user1,
            side='buy',
            contract_type='yes',
            price=60,
            quantity=5
        )

        # User2 places BUY NO @ 40c (60 + 40 = 100, exactly $1)
        no_order, trades = engine.place_order(
            user=self.user2,
            side='buy',
            contract_type='no',
            price=40,
            quantity=5
        )

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].trade_type, Trade.TradeType.MINT)
        self.assertEqual(trades[0].quantity, 5)

        # Verify positions
        user1_pos = Position.objects.get(user=self.user1, market=self.market)
        user2_pos = Position.objects.get(user=self.user2, market=self.market)

        self.assertEqual(user1_pos.yes_quantity, 5)
        self.assertEqual(user1_pos.no_quantity, 0)
        self.assertEqual(user2_pos.yes_quantity, 0)
        self.assertEqual(user2_pos.no_quantity, 5)

        # Verify market shares outstanding increased
        self.market.refresh_from_db()
        self.assertEqual(self.market.total_shares_outstanding, 5)

        # Verify balances
        self.user1.refresh_from_db()
        self.user2.refresh_from_db()
        self.assertEqual(self.user1.balance, Decimal('97.00'))  # 100 - 5*0.60
        self.assertEqual(self.user2.balance, Decimal('98.00'))  # 100 - 5*0.40

    def test_mint_with_surplus(self):
        """Test minting when prices sum to > $1."""
        engine = MatchingEngine(self.market)

        # User1 places BUY YES @ 65c
        engine.place_order(
            user=self.user1,
            side='buy',
            contract_type='yes',
            price=65,
            quantity=5
        )

        # User2 places BUY NO @ 45c (65 + 45 = 110c > $1)
        # Should still match - each pays their price
        _, trades = engine.place_order(
            user=self.user2,
            side='buy',
            contract_type='no',
            price=45,
            quantity=5
        )

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].trade_type, Trade.TradeType.MINT)

        # Verify positions created
        user1_pos = Position.objects.get(user=self.user1, market=self.market)
        user2_pos = Position.objects.get(user=self.user2, market=self.market)
        self.assertEqual(user1_pos.yes_quantity, 5)
        self.assertEqual(user2_pos.no_quantity, 5)

    def test_no_mint_when_sum_less_than_100(self):
        """Test no minting when prices sum to < $1."""
        engine = MatchingEngine(self.market)

        # User1 places BUY YES @ 40c
        engine.place_order(
            user=self.user1,
            side='buy',
            contract_type='yes',
            price=40,
            quantity=5
        )

        # User2 places BUY NO @ 40c (40 + 40 = 80c < $1)
        # Should NOT match - can't mint for less than $1
        no_order, trades = engine.place_order(
            user=self.user2,
            side='buy',
            contract_type='no',
            price=40,
            quantity=5
        )

        self.assertEqual(len(trades), 0)
        no_order.refresh_from_db()
        self.assertEqual(no_order.status, Order.Status.OPEN)

    def test_mint_partial_fill(self):
        """Test partial fill during minting."""
        engine = MatchingEngine(self.market)

        # User1 places BUY YES @ 60c for 10 contracts
        engine.place_order(
            user=self.user1,
            side='buy',
            contract_type='yes',
            price=60,
            quantity=10
        )

        # User2 places BUY NO @ 40c for only 3 contracts
        _, trades = engine.place_order(
            user=self.user2,
            side='buy',
            contract_type='no',
            price=40,
            quantity=3
        )

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].quantity, 3)

        # Verify market shares
        self.market.refresh_from_db()
        self.assertEqual(self.market.total_shares_outstanding, 3)


class MergingTest(BaseTestCase):
    """Test merging logic (SELL YES + SELL NO = burn shares)."""

    def setUp(self):
        super().setUp()
        # Give both users positions to sell
        Position.objects.create(
            user=self.user1,
            market=self.market,
            yes_quantity=10,
            yes_avg_cost=Decimal('50.00')
        )
        Position.objects.create(
            user=self.user2,
            market=self.market,
            no_quantity=10,
            no_avg_cost=Decimal('50.00')
        )
        # Set market shares outstanding
        self.market.total_shares_outstanding = 10
        self.market.save()

    def test_merge_match_exact(self):
        """Test SELL YES + SELL NO at exactly $1 burns shares."""
        engine = MatchingEngine(self.market)

        # User1 places SELL YES @ 55c
        yes_order, _ = engine.place_order(
            user=self.user1,
            side='sell',
            contract_type='yes',
            price=55,
            quantity=5
        )

        # User2 places SELL NO @ 45c (55 + 45 = 100, exactly $1)
        no_order, trades = engine.place_order(
            user=self.user2,
            side='sell',
            contract_type='no',
            price=45,
            quantity=5
        )

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].trade_type, Trade.TradeType.MERGE)
        self.assertEqual(trades[0].quantity, 5)

        # Verify positions decreased
        user1_pos = Position.objects.get(user=self.user1, market=self.market)
        user2_pos = Position.objects.get(user=self.user2, market=self.market)

        self.assertEqual(user1_pos.yes_quantity, 5)  # Had 10, sold 5
        self.assertEqual(user2_pos.no_quantity, 5)   # Had 10, sold 5

        # Verify market shares outstanding decreased
        self.market.refresh_from_db()
        self.assertEqual(self.market.total_shares_outstanding, 5)

        # Verify balances increased
        self.user1.refresh_from_db()
        self.user2.refresh_from_db()
        self.assertEqual(self.user1.balance, Decimal('102.75'))  # 100 + 5*0.55
        self.assertEqual(self.user2.balance, Decimal('102.25'))  # 100 + 5*0.45

    def test_merge_with_profit(self):
        """Test merging when prices sum to < $1 (sellers profit)."""
        engine = MatchingEngine(self.market)

        # User1 places SELL YES @ 50c
        engine.place_order(
            user=self.user1,
            side='sell',
            contract_type='yes',
            price=50,
            quantity=5
        )

        # User2 places SELL NO @ 40c (50 + 40 = 90c < $1)
        # Should still match
        _, trades = engine.place_order(
            user=self.user2,
            side='sell',
            contract_type='no',
            price=40,
            quantity=5
        )

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].trade_type, Trade.TradeType.MERGE)

    def test_no_merge_when_sum_more_than_100(self):
        """Test no merging when prices sum to > $1."""
        engine = MatchingEngine(self.market)

        # User1 places SELL YES @ 60c
        engine.place_order(
            user=self.user1,
            side='sell',
            contract_type='yes',
            price=60,
            quantity=5
        )

        # User2 places SELL NO @ 60c (60 + 60 = 120c > $1)
        # Should NOT match - can't pay out more than $1
        no_order, trades = engine.place_order(
            user=self.user2,
            side='sell',
            contract_type='no',
            price=60,
            quantity=5
        )

        self.assertEqual(len(trades), 0)
        no_order.refresh_from_db()
        self.assertEqual(no_order.status, Order.Status.OPEN)


class SettlementTest(BaseTestCase):
    """Test market settlement."""

    def setUp(self):
        super().setUp()
        # Give users positions
        Position.objects.create(
            user=self.user1,
            market=self.market,
            yes_quantity=10,
            no_quantity=0,
            yes_avg_cost=Decimal('60.00')
        )
        Position.objects.create(
            user=self.user2,
            market=self.market,
            yes_quantity=0,
            no_quantity=10,
            no_avg_cost=Decimal('40.00')
        )

    def test_settle_yes(self):
        """Test settling market as YES."""
        from .engine.matching import settle_market

        stats = settle_market(self.market, 'yes')

        self.assertEqual(stats['winning_outcome'], 'yes')
        self.assertEqual(stats['winners'], 1)  # user1
        self.assertEqual(stats['total_payout'], Decimal('10.00'))  # 10 * $1

        # Verify user balances
        self.user1.refresh_from_db()
        self.user2.refresh_from_db()
        self.assertEqual(self.user1.balance, Decimal('110.00'))  # 100 + 10
        self.assertEqual(self.user2.balance, Decimal('100.00'))  # unchanged

        # Verify positions cleared
        pos1 = Position.objects.get(user=self.user1, market=self.market)
        pos2 = Position.objects.get(user=self.user2, market=self.market)
        self.assertEqual(pos1.yes_quantity, 0)
        self.assertEqual(pos2.no_quantity, 0)

        # Verify market status
        self.market.refresh_from_db()
        self.assertEqual(self.market.status, Market.Status.SETTLED_YES)

    def test_settle_no(self):
        """Test settling market as NO."""
        from .engine.matching import settle_market

        stats = settle_market(self.market, 'no')

        self.assertEqual(stats['winning_outcome'], 'no')
        self.assertEqual(stats['winners'], 1)  # user2
        self.assertEqual(stats['total_payout'], Decimal('10.00'))

        self.user1.refresh_from_db()
        self.user2.refresh_from_db()
        self.assertEqual(self.user1.balance, Decimal('100.00'))  # unchanged
        self.assertEqual(self.user2.balance, Decimal('110.00'))  # 100 + 10

    def test_settlement_cancels_open_orders(self):
        """Test that settlement cancels all open orders."""
        from .matching_engine import settle_market
        engine = MatchingEngine(self.market)

        # User3 places an open buy order
        order, _ = engine.place_order(
            user=self.user3,
            side='buy',
            contract_type='yes',
            price=50,
            quantity=5
        )

        # Record reserved balance
        self.user3.refresh_from_db()
        reserved_before = self.user3.reserved_balance
        self.assertGreater(reserved_before, 0)

        # Settle market
        settle_market(self.market, 'yes')

        # Verify order cancelled
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)

        # Verify reserved balance released
        self.user3.refresh_from_db()
        self.assertEqual(self.user3.reserved_balance, Decimal('0.00'))


class MintRedeemTest(BaseTestCase):
    """Test direct mint/redeem complete sets."""

    def test_mint_complete_set(self):
        """Test minting complete sets directly."""
        from .engine.matching import mint_complete_set

        result = mint_complete_set(self.market, self.user1, 5)

        self.assertEqual(result['quantity'], 5)
        self.assertEqual(result['cost'], Decimal('5.00'))
        self.assertEqual(result['yes_received'], 5)
        self.assertEqual(result['no_received'], 5)

        # Verify position
        pos = Position.objects.get(user=self.user1, market=self.market)
        self.assertEqual(pos.yes_quantity, 5)
        self.assertEqual(pos.no_quantity, 5)
        self.assertEqual(pos.yes_avg_cost, Decimal('50.00'))
        self.assertEqual(pos.no_avg_cost, Decimal('50.00'))

        # Verify balance
        self.user1.refresh_from_db()
        self.assertEqual(self.user1.balance, Decimal('95.00'))

        # Verify market
        self.market.refresh_from_db()
        self.assertEqual(self.market.total_shares_outstanding, 5)

    def test_redeem_complete_set(self):
        """Test redeeming complete sets."""
        from .engine.matching import mint_complete_set, redeem_complete_set

        # First mint some sets
        mint_complete_set(self.market, self.user1, 5)

        # Then redeem them
        result = redeem_complete_set(self.market, self.user1, 3)

        self.assertEqual(result['quantity'], 3)
        self.assertEqual(result['payout'], Decimal('3.00'))
        self.assertEqual(result['yes_burned'], 3)
        self.assertEqual(result['no_burned'], 3)

        # Verify position
        pos = Position.objects.get(user=self.user1, market=self.market)
        self.assertEqual(pos.yes_quantity, 2)
        self.assertEqual(pos.no_quantity, 2)

        # Verify balance (100 - 5 + 3 = 98)
        self.user1.refresh_from_db()
        self.assertEqual(self.user1.balance, Decimal('98.00'))

        # Verify market
        self.market.refresh_from_db()
        self.assertEqual(self.market.total_shares_outstanding, 2)

    def test_redeem_insufficient_position(self):
        """Test redeeming fails without enough contracts."""
        from .engine.matching import mint_complete_set, redeem_complete_set

        # Mint 5 sets
        mint_complete_set(self.market, self.user1, 5)

        # Try to redeem 10 - should fail
        with self.assertRaises(InsufficientPositionError):
            redeem_complete_set(self.market, self.user1, 10)

    def test_mint_insufficient_funds(self):
        """Test minting fails without enough balance."""
        from .engine.matching import mint_complete_set

        with self.assertRaises(InsufficientFundsError):
            mint_complete_set(self.market, self.user1, 200)  # Would cost $200


class OrderbookIntegrationTest(BaseTestCase):
    """Integration tests for full orderbook scenarios."""

    def test_priority_direct_over_mint(self):
        """Test that direct matching takes priority over minting."""
        engine = MatchingEngine(self.market)

        # Give user2 YES contracts to sell
        Position.objects.create(
            user=self.user2,
            market=self.market,
            yes_quantity=10,
            yes_avg_cost=Decimal('40.00')
        )

        # User2 places SELL YES @ 55c
        engine.place_order(
            user=self.user2,
            side='sell',
            contract_type='yes',
            price=55,
            quantity=5
        )

        # User3 places BUY NO @ 50c (would mint with any BUY YES @ 50c+)
        engine.place_order(
            user=self.user3,
            side='buy',
            contract_type='no',
            price=50,
            quantity=5
        )

        # User1 places BUY YES @ 60c
        # Should FIRST match with SELL YES @ 55c (direct)
        # NOT mint with BUY NO @ 50c
        _, trades = engine.place_order(
            user=self.user1,
            side='buy',
            contract_type='yes',
            price=60,
            quantity=5
        )

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].trade_type, Trade.TradeType.DIRECT)
        self.assertEqual(trades[0].price, 55)

    def test_full_trading_cycle(self):
        """Test a complete trading cycle: mint -> trade -> merge."""
        engine = MatchingEngine(self.market)

        # Step 1: Mint shares (user1 buys YES, user2 buys NO)
        engine.place_order(self.user1, 'buy', 'yes', 60, 10)
        _, mint_trades = engine.place_order(self.user2, 'buy', 'no', 40, 10)

        self.assertEqual(len(mint_trades), 1)
        self.assertEqual(mint_trades[0].trade_type, Trade.TradeType.MINT)

        self.market.refresh_from_db()
        self.assertEqual(self.market.total_shares_outstanding, 10)

        # Step 2: Direct trade (user1 sells some YES to user3)
        # First user1 needs to place a sell order
        engine.place_order(self.user1, 'sell', 'yes', 60, 3)
        # Then user3 buys and matches
        _, direct_trades = engine.place_order(self.user3, 'buy', 'yes', 65, 3)

        self.assertEqual(len(direct_trades), 1)
        self.assertEqual(direct_trades[0].trade_type, Trade.TradeType.DIRECT)

        # Verify positions
        pos1 = Position.objects.get(user=self.user1, market=self.market)
        pos3 = Position.objects.get(user=self.user3, market=self.market)
        self.assertEqual(pos1.yes_quantity, 7)  # 10 - 3
        self.assertEqual(pos3.yes_quantity, 3)

        # Step 3: Merge (user1 sells remaining YES, user2 sells NO)
        engine.place_order(self.user1, 'sell', 'yes', 55, 5)
        _, merge_trades = engine.place_order(self.user2, 'sell', 'no', 45, 5)

        self.assertEqual(len(merge_trades), 1)
        self.assertEqual(merge_trades[0].trade_type, Trade.TradeType.MERGE)

        self.market.refresh_from_db()
        self.assertEqual(self.market.total_shares_outstanding, 5)  # 10 - 5

    def test_orderbook_structure(self):
        """Test orderbook returns correct structure."""
        engine = MatchingEngine(self.market)

        # Place some orders
        engine.place_order(self.user1, 'buy', 'yes', 45, 10)
        engine.place_order(self.user2, 'buy', 'yes', 50, 5)

        # Give positions and place sell orders
        Position.objects.create(user=self.user3, market=self.market, yes_quantity=20)
        engine.place_order(self.user3, 'sell', 'yes', 55, 8)

        orderbook = get_orderbook(self.market)

        # Check structure
        self.assertIn('yes_bids', orderbook)
        self.assertIn('yes_asks', orderbook)
        self.assertIn('no_bids', orderbook)
        self.assertIn('no_asks', orderbook)

        # Check YES bids (highest first)
        self.assertEqual(len(orderbook['yes_bids']), 2)
        self.assertEqual(orderbook['yes_bids'][0]['price'], 50)
        self.assertEqual(orderbook['yes_bids'][1]['price'], 45)

        # Check YES asks
        self.assertEqual(len(orderbook['yes_asks']), 1)
        self.assertEqual(orderbook['yes_asks'][0]['price'], 55)
