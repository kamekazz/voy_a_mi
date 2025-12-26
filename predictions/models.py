from django.db import models
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from decimal import Decimal


class User(AbstractUser):
    """Custom user model for the prediction market platform."""
    balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="User's available balance in dollars"
    )
    reserved_balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Funds locked in open buy orders"
    )

    @property
    def available_balance(self):
        """Balance available for new orders."""
        return self.balance - self.reserved_balance

    @property
    def total_balance(self):
        """Total balance including reserved funds."""
        return self.balance


class Category(models.Model):
    """Categories for organizing prediction events."""
    name = models.CharField(max_length=64)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True, help_text="CSS icon class name")
    display_order = models.IntegerField(default=0)

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ['display_order', 'name']

    def __str__(self):
        return self.name


class Event(models.Model):
    """
    Parent container for related markets.
    Example: "2024 US Presidential Election"
    """
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        ACTIVE = 'active', 'Active'
        CLOSED = 'closed', 'Closed (Trading Halted)'
        SETTLED = 'settled', 'Settled'
        CANCELLED = 'cancelled', 'Cancelled'

    class EventType(models.TextChoices):
        BINARY = 'binary', 'Binary (Yes/No)'
        MULTI = 'multi', 'Multi-Outcome'

    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    description = models.TextField()
    event_type = models.CharField(
        max_length=10,
        choices=EventType.choices,
        default=EventType.BINARY
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='events'
    )
    resolution_source = models.CharField(
        max_length=500,
        help_text="Source used to determine outcome (e.g., official website, news agency)"
    )

    # Timing
    created_at = models.DateTimeField(auto_now_add=True)
    trading_starts = models.DateTimeField()
    trading_ends = models.DateTimeField()
    resolution_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Expected date when event outcome will be known"
    )

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.DRAFT
    )

    # Admin tracking
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_events'
    )

    # Images (optional)
    image = models.ImageField(
        upload_to='events/images/',
        blank=True,
        null=True,
        help_text="Main event image (recommended: 800x600px)"
    )
    thumbnail = models.ImageField(
        upload_to='events/thumbnails/',
        blank=True,
        null=True,
        help_text="Thumbnail for listings (recommended: 200x150px)"
    )

    class Meta:
        ordering = ['-trading_starts']
        indexes = [
            models.Index(fields=['status', 'trading_ends']),
            models.Index(fields=['category', 'status']),
        ]

    def __str__(self):
        return self.title

    @property
    def is_trading_active(self):
        """Check if trading is currently active for this event."""
        now = timezone.now()
        return (
            self.status == self.Status.ACTIVE and
            self.trading_starts <= now <= self.trading_ends
        )

    @property
    def time_remaining(self):
        """Return time remaining until trading ends."""
        if self.trading_ends:
            remaining = self.trading_ends - timezone.now()
            if remaining.total_seconds() > 0:
                return remaining
        return None


class Market(models.Model):
    """
    A tradeable contract within an event.
    For binary events: single market with YES/NO sides.
    For multi-outcome: multiple markets (one per outcome).
    """
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        HALTED = 'halted', 'Trading Halted'
        SETTLED_YES = 'settled_yes', 'Settled - Yes Won'
        SETTLED_NO = 'settled_no', 'Settled - No Won'
        CANCELLED = 'cancelled', 'Cancelled'

    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='markets'
    )
    title = models.CharField(
        max_length=200,
        help_text="The specific question, e.g., 'Will Biden win?'"
    )
    slug = models.SlugField()
    description = models.TextField(blank=True)

    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.ACTIVE
    )

    # Price cache (updated on each trade) - stored as cents (1-99)
    last_yes_price = models.IntegerField(
        default=50,
        help_text="Last traded YES price (1-99 cents)"
    )
    last_no_price = models.IntegerField(
        default=50,
        help_text="Last traded NO price (1-99 cents)"
    )

    # Best bid/ask cache (updated on order changes)
    best_yes_bid = models.IntegerField(null=True, blank=True)
    best_yes_ask = models.IntegerField(null=True, blank=True)
    best_no_bid = models.IntegerField(null=True, blank=True)
    best_no_ask = models.IntegerField(null=True, blank=True)

    # Volume tracking
    total_volume = models.IntegerField(default=0, help_text="Total contracts traded")
    volume_24h = models.IntegerField(default=0, help_text="Contracts traded in last 24h")

    # Polymarket-style collateral tracking
    total_shares_outstanding = models.IntegerField(
        default=0,
        help_text="Total YES/NO pairs minted (equals collateral locked in dollars)"
    )

    # For multi-outcome events
    is_mutually_exclusive = models.BooleanField(
        default=True,
        help_text="If true, only one market in the event can settle YES"
    )

    # AMM settings
    amm_enabled = models.BooleanField(
        default=True,
        help_text="If true, market uses AMM for instant trades"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    # Images (optional)
    image = models.ImageField(
        upload_to='markets/images/',
        blank=True,
        null=True,
        help_text="Market-specific image (recommended: 800x600px)"
    )
    thumbnail = models.ImageField(
        upload_to='markets/thumbnails/',
        blank=True,
        null=True,
        help_text="Thumbnail for listings (recommended: 200x150px)"
    )

    class Meta:
        unique_together = ['event', 'slug']
        ordering = ['event', 'title']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['event', 'status']),
        ]

    def __str__(self):
        return f"{self.event.title} - {self.title}"

    @property
    def is_trading_active(self):
        """Check if trading is currently active for this market."""
        return (
            self.status == self.Status.ACTIVE and
            self.event.is_trading_active
        )

    @property
    def yes_probability(self):
        """Current implied probability based on last YES price."""
        return self.last_yes_price / 100

    @property
    def spread(self):
        """Current bid-ask spread for YES contracts."""
        if self.best_yes_bid and self.best_yes_ask:
            return self.best_yes_ask - self.best_yes_bid
        return None

    @property
    def display_image(self):
        """Return market image, or fall back to event image if not set."""
        return self.image if self.image else self.event.image

    @property
    def display_thumbnail(self):
        """Return market thumbnail, or fall back to event thumbnail if not set."""
        return self.thumbnail if self.thumbnail else self.event.thumbnail


class Order(models.Model):
    """
    Order in the orderbook.
    Supports both limit orders (specify price) and market orders (automatic price).
    Price-time priority matching.
    """
    class Side(models.TextChoices):
        BUY = 'buy', 'Buy'
        SELL = 'sell', 'Sell'

    class ContractType(models.TextChoices):
        YES = 'yes', 'Yes'
        NO = 'no', 'No'

    class OrderType(models.TextChoices):
        LIMIT = 'limit', 'Limit'
        MARKET = 'market', 'Market'

    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        PARTIALLY_FILLED = 'partial', 'Partially Filled'
        FILLED = 'filled', 'Filled'
        CANCELLED = 'cancelled', 'Cancelled'
        EXPIRED = 'expired', 'Expired'

    market = models.ForeignKey(
        Market,
        on_delete=models.CASCADE,
        related_name='orders'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='prediction_orders'
    )

    side = models.CharField(max_length=4, choices=Side.choices)
    contract_type = models.CharField(max_length=3, choices=ContractType.choices)
    order_type = models.CharField(
        max_length=6,
        choices=OrderType.choices,
        default=OrderType.LIMIT,
        help_text="Limit orders specify price, market orders use best available"
    )

    # Price in cents (1-99). For market orders, this is set automatically.
    price = models.DecimalField(
        max_digits=4, decimal_places=2,
        help_text="Price in dollars (0.01-0.99)",
        null=True, blank=True
    )

    # Quantity
    quantity = models.IntegerField(help_text="Number of contracts")
    filled_quantity = models.IntegerField(default=0)

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.OPEN
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['market', 'status', 'side', 'contract_type', 'price']),
            models.Index(fields=['user', 'status']),
            models.Index(fields=['created_at']),
        ]

    @property
    def remaining_quantity(self):
        """Number of contracts not yet filled."""
        return self.quantity - self.filled_quantity

    @property
    def total_cost(self):
        """Total cost in dollars for buy orders."""
        return Decimal(self.price * self.quantity) / 100

    @property
    def is_active(self):
        """Check if order can still be matched."""
        return self.status in [self.Status.OPEN, self.Status.PARTIALLY_FILLED]

    def __str__(self):
        return f"{self.side.upper()} {self.quantity} {self.contract_type.upper()} @ {self.price}c"


class Trade(models.Model):
    """
    Record of a matched trade between two orders.
    Created when orders are matched in the orderbook.
    """
    class TradeType(models.TextChoices):
        DIRECT = 'direct', 'Direct Match'
        MINT = 'mint', 'Minted (Buy YES + Buy NO)'
        MERGE = 'merge', 'Merged (Sell YES + Sell NO)'

    market = models.ForeignKey(
        Market,
        on_delete=models.CASCADE,
        related_name='trades'
    )

    # The two orders involved in the trade
    buy_order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='buy_trades'
    )
    sell_order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='sell_trades'
    )

    # Users involved
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='prediction_purchases'
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='prediction_sales'
    )

    contract_type = models.CharField(max_length=3, choices=Order.ContractType.choices)
    price = models.IntegerField(help_text="Execution price in cents")
    quantity = models.IntegerField(help_text="Number of contracts traded")

    # Trade type for Polymarket-style matching
    trade_type = models.CharField(
        max_length=10,
        choices=TradeType.choices,
        default=TradeType.DIRECT,
        help_text="How this trade was matched (direct, mint, or merge)"
    )

    executed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-executed_at']
        indexes = [
            models.Index(fields=['market', 'executed_at']),
            models.Index(fields=['buyer', 'executed_at']),
            models.Index(fields=['seller', 'executed_at']),
        ]

    @property
    def total_value(self):
        """Total trade value in dollars."""
        return Decimal(self.price * self.quantity) / 100

    def __str__(self):
        return f"{self.quantity} {self.contract_type.upper()} @ {self.price}c"


class UserBalance(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    reserved_balance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))  # Funds locked in open orders

    def __str__(self):
        return f"{self.user.username}: ${self.balance} (Reserved: ${self.reserved_balance})"


class Position(models.Model):
    """
    User's holdings in a specific market.
    Tracks both YES and NO contract holdings.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='positions'
    )
    market = models.ForeignKey(
        Market,
        on_delete=models.CASCADE,
        related_name='positions'
    )

    # Contract holdings (can be 0 or positive)
    yes_quantity = models.IntegerField(default=0)
    no_quantity = models.IntegerField(default=0)
    reserved_yes_quantity = models.IntegerField(default=0)  # Shares locked in open Sell YES orders
    reserved_no_quantity = models.IntegerField(default=0)   # Shares locked in open Sell NO orders

    # Average cost basis in cents (for P&L calculation)
    yes_avg_cost = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00')
    )
    no_avg_cost = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00')
    )

    # Realized P&L from closed positions (in dollars)
    realized_pnl = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00')
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['user', 'market']
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['market']),
        ]

    @property
    def unrealized_pnl_yes(self):
        """Unrealized P&L on YES positions in dollars."""
        if self.yes_quantity <= 0:
            return Decimal('0.00')
        current_value = Decimal(self.yes_quantity * self.market.last_yes_price)
        cost_basis = Decimal(self.yes_quantity) * self.yes_avg_cost
        return (current_value - cost_basis) / 100

    @property
    def unrealized_pnl_no(self):
        """Unrealized P&L on NO positions in dollars."""
        if self.no_quantity <= 0:
            return Decimal('0.00')
        current_value = Decimal(self.no_quantity * self.market.last_no_price)
        cost_basis = Decimal(self.no_quantity) * self.no_avg_cost
        return (current_value - cost_basis) / 100

    @property
    def total_unrealized_pnl(self):
        """Total unrealized P&L across both contract types."""
        return self.unrealized_pnl_yes + self.unrealized_pnl_no

    @property
    def has_position(self):
        """Check if user has any position in this market."""
        return self.yes_quantity > 0 or self.no_quantity > 0

    def __str__(self):
        return f"{self.user.username}: {self.yes_quantity} YES, {self.no_quantity} NO in {self.market.title}"


class Transaction(models.Model):
    """
    Tracks all balance changes for audit trail.
    Every change to user balance is recorded here.
    """
    class Type(models.TextChoices):
        DEPOSIT = 'deposit', 'Deposit'
        WITHDRAWAL = 'withdrawal', 'Withdrawal'
        TRADE_BUY = 'trade_buy', 'Trade (Buy)'
        TRADE_SELL = 'trade_sell', 'Trade (Sell)'
        SETTLEMENT_WIN = 'settlement_win', 'Settlement (Win)'
        SETTLEMENT_LOSS = 'settlement_loss', 'Settlement (Loss)'
        ORDER_RESERVE = 'order_reserve', 'Order Reserve'
        ORDER_RELEASE = 'order_release', 'Order Release'
        REFUND = 'refund', 'Refund'
        # Polymarket-style minting/merging
        MINT = 'mint', 'Mint (Create Complete Set)'
        REDEEM = 'redeem', 'Redeem (Burn Complete Set)'
        MINT_MATCH = 'mint_match', 'Mint via Order Match'
        MERGE_MATCH = 'merge_match', 'Merge via Order Match'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='transactions'
    )

    type = models.CharField(max_length=20, choices=Type.choices)
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Positive for credit, negative for debit"
    )

    balance_before = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)

    # References to related objects
    order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions'
    )
    trade = models.ForeignKey(
        Trade,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions'
    )
    market = models.ForeignKey(
        Market,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions'
    )

    description = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['type', 'created_at']),
        ]

    def __str__(self):
        sign = '+' if self.amount > 0 else ''
        return f"{self.user.username}: {sign}${self.amount} ({self.get_type_display()})"


class AMMPool(models.Model):
    """
    Automated Market Maker pool using LMSR (Logarithmic Market Scoring Rule).
    Provides instant liquidity for market orders.
    """
    market = models.OneToOneField(
        Market,
        on_delete=models.CASCADE,
        related_name='amm_pool'
    )

    # LMSR liquidity parameter - higher = more liquidity, less price impact
    liquidity_b = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('100.00'),
        help_text="LMSR liquidity parameter (b)"
    )

    # Outstanding shares in the pool
    yes_shares = models.DecimalField(
        max_digits=15,
        decimal_places=4,
        default=Decimal('0.0000'),
        help_text="Total YES shares outstanding"
    )
    no_shares = models.DecimalField(
        max_digits=15,
        decimal_places=4,
        default=Decimal('0.0000'),
        help_text="Total NO shares outstanding"
    )

    # Pool's accumulated funds from trades
    pool_balance = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Pool's accumulated balance in dollars"
    )

    # Fee settings
    fee_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal('0.0100'),  # 1% fee
        help_text="Trading fee percentage (0.01 = 1%)"
    )
    total_fees_collected = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Total fees collected"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "AMM Pool"
        verbose_name_plural = "AMM Pools"

    def __str__(self):
        return f"AMM Pool for {self.market.title}"


class AMMTrade(models.Model):
    """
    Record of a trade executed against the AMM pool.
    """
    class Side(models.TextChoices):
        BUY = 'buy', 'Buy'
        SELL = 'sell', 'Sell'

    class ContractType(models.TextChoices):
        YES = 'yes', 'Yes'
        NO = 'no', 'No'

    pool = models.ForeignKey(
        AMMPool,
        on_delete=models.CASCADE,
        related_name='trades'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='amm_trades'
    )

    side = models.CharField(max_length=4, choices=Side.choices)
    contract_type = models.CharField(max_length=3, choices=ContractType.choices)

    quantity = models.IntegerField(help_text="Number of contracts")
    price = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True) # Null for Market Orders

    # Prices in cents (1-99)
    price_before = models.IntegerField(help_text="Price before trade in cents")
    price_after = models.IntegerField(help_text="Price after trade in cents")
    avg_price = models.DecimalField(
        max_digits=7,
        decimal_places=4,
        help_text="Average execution price in cents"
    )

    # Costs in dollars
    total_cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Total cost in dollars"
    )
    fee_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Fee paid in dollars"
    )

    executed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-executed_at']
        indexes = [
            models.Index(fields=['pool', 'executed_at']),
            models.Index(fields=['user', 'executed_at']),
        ]

    def __str__(self):
        return f"{self.side.upper()} {self.quantity} {self.contract_type.upper()} @ {self.avg_price}c"
