from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone
from .models import Category, Event, Market, Order, Trade, Position, Transaction


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'display_order', 'event_count']
    list_editable = ['display_order']
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ['name']
    ordering = ['display_order', 'name']

    def event_count(self, obj):
        return obj.events.count()
    event_count.short_description = 'Events'


class MarketInline(admin.TabularInline):
    model = Market
    extra = 1
    fields = ['title', 'slug', 'status', 'last_yes_price', 'total_volume']
    readonly_fields = ['last_yes_price', 'total_volume']
    prepopulated_fields = {'slug': ('title',)}


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'category', 'event_type', 'status', 'trading_status',
        'trading_starts', 'trading_ends', 'market_count'
    ]
    list_filter = ['status', 'event_type', 'category', 'trading_starts']
    search_fields = ['title', 'description']
    prepopulated_fields = {'slug': ('title',)}
    date_hierarchy = 'trading_starts'
    readonly_fields = ['created_at', 'created_by']
    inlines = [MarketInline]

    fieldsets = (
        (None, {
            'fields': ('title', 'slug', 'description', 'event_type', 'category')
        }),
        ('Resolution', {
            'fields': ('resolution_source', 'resolution_date')
        }),
        ('Trading Schedule', {
            'fields': ('trading_starts', 'trading_ends', 'status')
        }),
        ('Metadata', {
            'fields': ('created_at', 'created_by'),
            'classes': ('collapse',)
        }),
    )

    def trading_status(self, obj):
        if obj.is_trading_active:
            return format_html('<span style="color: {};">{}</span>', 'green', 'Active')
        elif obj.status == Event.Status.SETTLED:
            return format_html('<span style="color: {};">{}</span>', 'gray', 'Settled')
        elif obj.status == Event.Status.CLOSED:
            return format_html('<span style="color: {};">{}</span>', 'orange', 'Closed')
        elif timezone.now() < obj.trading_starts:
            return format_html('<span style="color: {};">{}</span>', 'blue', 'Upcoming')
        else:
            return format_html('<span style="color: {};">{}</span>', 'red', 'Ended')
    trading_status.short_description = 'Trading'

    def market_count(self, obj):
        return obj.markets.count()
    market_count.short_description = 'Markets'

    def save_model(self, request, obj, form, change):
        if not change:  # New object
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    actions = ['activate_events', 'close_events']

    @admin.action(description='Activate selected events')
    def activate_events(self, request, queryset):
        updated = queryset.filter(status=Event.Status.DRAFT).update(status=Event.Status.ACTIVE)
        self.message_user(request, f'{updated} event(s) activated.')

    @admin.action(description='Close trading on selected events')
    def close_events(self, request, queryset):
        updated = queryset.filter(status=Event.Status.ACTIVE).update(status=Event.Status.CLOSED)
        self.message_user(request, f'{updated} event(s) closed.')


@admin.register(Market)
class MarketAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'event_link', 'status', 'yes_price_display', 'no_price_display',
        'spread_display', 'total_volume', 'order_count'
    ]
    list_filter = ['status', 'event__category', 'event__status']
    search_fields = ['title', 'event__title']
    raw_id_fields = ['event']
    readonly_fields = [
        'last_yes_price', 'last_no_price',
        'best_yes_bid', 'best_yes_ask', 'best_no_bid', 'best_no_ask',
        'total_volume', 'volume_24h', 'created_at'
    ]

    fieldsets = (
        (None, {
            'fields': ('event', 'title', 'slug', 'description', 'status')
        }),
        ('Pricing', {
            'fields': (
                ('last_yes_price', 'last_no_price'),
                ('best_yes_bid', 'best_yes_ask'),
                ('best_no_bid', 'best_no_ask'),
            )
        }),
        ('Volume', {
            'fields': ('total_volume', 'volume_24h')
        }),
        ('Settings', {
            'fields': ('is_mutually_exclusive',)
        }),
    )

    def event_link(self, obj):
        url = reverse('admin:predictions_event_change', args=[obj.event.pk])
        return format_html('<a href="{}">{}</a>', url, obj.event.title[:30])
    event_link.short_description = 'Event'

    def yes_price_display(self, obj):
        return format_html('<span style="color: green;">{}c</span>', obj.last_yes_price)
    yes_price_display.short_description = 'YES Price'

    def no_price_display(self, obj):
        return format_html('<span style="color: red;">{}c</span>', obj.last_no_price)
    no_price_display.short_description = 'NO Price'

    def spread_display(self, obj):
        spread = obj.spread
        if spread is not None:
            return f'{spread}c'
        return '-'
    spread_display.short_description = 'Spread'

    def order_count(self, obj):
        return obj.orders.filter(status__in=['open', 'partial']).count()
    order_count.short_description = 'Open Orders'

    actions = ['settle_yes', 'settle_no', 'halt_trading', 'resume_trading']

    @admin.action(description='Settle as YES (pay YES holders $1/share)')
    def settle_yes(self, request, queryset):
        from .matching_engine import settle_market
        settled = 0
        errors = []
        for market in queryset.filter(status=Market.Status.ACTIVE):
            try:
                settle_market(market, 'yes')
                settled += 1
            except Exception as e:
                errors.append(f'{market.title}: {str(e)}')

        if settled:
            self.message_user(request, f'{settled} market(s) settled as YES. Winners paid $1/share.')
        if errors:
            self.message_user(request, f'Errors: {"; ".join(errors)}', level='ERROR')

    @admin.action(description='Settle as NO (pay NO holders $1/share)')
    def settle_no(self, request, queryset):
        from .matching_engine import settle_market
        settled = 0
        errors = []
        for market in queryset.filter(status=Market.Status.ACTIVE):
            try:
                settle_market(market, 'no')
                settled += 1
            except Exception as e:
                errors.append(f'{market.title}: {str(e)}')

        if settled:
            self.message_user(request, f'{settled} market(s) settled as NO. Winners paid $1/share.')
        if errors:
            self.message_user(request, f'Errors: {"; ".join(errors)}', level='ERROR')

    @admin.action(description='Halt trading')
    def halt_trading(self, request, queryset):
        updated = queryset.filter(status=Market.Status.ACTIVE).update(
            status=Market.Status.HALTED
        )
        self.message_user(request, f'{updated} market(s) halted.')

    @admin.action(description='Resume trading')
    def resume_trading(self, request, queryset):
        updated = queryset.filter(status=Market.Status.HALTED).update(
            status=Market.Status.ACTIVE
        )
        self.message_user(request, f'{updated} market(s) resumed.')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'user_link', 'market_link', 'side', 'contract_type',
        'price_display', 'quantity', 'filled_quantity', 'status', 'created_at'
    ]
    list_filter = ['status', 'side', 'contract_type', 'created_at']
    search_fields = ['user__username', 'market__title']
    raw_id_fields = ['user', 'market']
    readonly_fields = ['filled_quantity', 'created_at', 'updated_at']
    date_hierarchy = 'created_at'

    fieldsets = (
        (None, {
            'fields': ('user', 'market', 'status')
        }),
        ('Order Details', {
            'fields': (('side', 'contract_type'), ('price', 'quantity', 'filled_quantity'))
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def user_link(self, obj):
        url = reverse('admin:auctions_user_change', args=[obj.user.pk])
        return format_html('<a href="{}">{}</a>', url, obj.user.username)
    user_link.short_description = 'User'

    def market_link(self, obj):
        url = reverse('admin:predictions_market_change', args=[obj.market.pk])
        return format_html('<a href="{}">{}</a>', url, obj.market.title[:25])
    market_link.short_description = 'Market'

    def price_display(self, obj):
        return f'{obj.price}c'
    price_display.short_description = 'Price'

    actions = ['cancel_orders']

    @admin.action(description='Cancel selected orders')
    def cancel_orders(self, request, queryset):
        updated = queryset.filter(status__in=['open', 'partial']).update(
            status=Order.Status.CANCELLED
        )
        self.message_user(request, f'{updated} order(s) cancelled.')


@admin.register(Trade)
class TradeAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'market_link', 'buyer_link', 'seller_link',
        'contract_type', 'price_display', 'quantity', 'total_value', 'executed_at'
    ]
    list_filter = ['contract_type', 'executed_at', 'market__event']
    search_fields = ['buyer__username', 'seller__username', 'market__title']
    raw_id_fields = ['market', 'buy_order', 'sell_order', 'buyer', 'seller']
    readonly_fields = ['market', 'buy_order', 'sell_order', 'buyer', 'seller',
                       'contract_type', 'price', 'quantity', 'executed_at']
    date_hierarchy = 'executed_at'

    def market_link(self, obj):
        url = reverse('admin:predictions_market_change', args=[obj.market.pk])
        return format_html('<a href="{}">{}</a>', url, obj.market.title[:25])
    market_link.short_description = 'Market'

    def buyer_link(self, obj):
        url = reverse('admin:auctions_user_change', args=[obj.buyer.pk])
        return format_html('<a href="{}">{}</a>', url, obj.buyer.username)
    buyer_link.short_description = 'Buyer'

    def seller_link(self, obj):
        url = reverse('admin:auctions_user_change', args=[obj.seller.pk])
        return format_html('<a href="{}">{}</a>', url, obj.seller.username)
    seller_link.short_description = 'Seller'

    def price_display(self, obj):
        return f'{obj.price}c'
    price_display.short_description = 'Price'

    def has_add_permission(self, request):
        return False  # Trades are created by the matching engine only

    def has_change_permission(self, request, obj=None):
        return False  # Trades are immutable


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = [
        'user_link', 'market_link', 'yes_quantity', 'no_quantity',
        'yes_avg_cost', 'no_avg_cost', 'realized_pnl', 'unrealized_pnl'
    ]
    list_filter = ['market__event', 'market__status']
    search_fields = ['user__username', 'market__title']
    raw_id_fields = ['user', 'market']
    readonly_fields = ['created_at', 'updated_at']

    def user_link(self, obj):
        url = reverse('admin:auctions_user_change', args=[obj.user.pk])
        return format_html('<a href="{}">{}</a>', url, obj.user.username)
    user_link.short_description = 'User'

    def market_link(self, obj):
        url = reverse('admin:predictions_market_change', args=[obj.market.pk])
        return format_html('<a href="{}">{}</a>', url, obj.market.title[:25])
    market_link.short_description = 'Market'

    def unrealized_pnl(self, obj):
        pnl = obj.total_unrealized_pnl
        color = 'green' if pnl >= 0 else 'red'
        return format_html('<span style="color: {};">${:.2f}</span>', color, pnl)
    unrealized_pnl.short_description = 'Unrealized P&L'


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'user_link', 'type', 'amount_display',
        'balance_before', 'balance_after', 'created_at'
    ]
    list_filter = ['type', 'created_at']
    search_fields = ['user__username', 'description']
    raw_id_fields = ['user', 'order', 'trade', 'market']
    readonly_fields = [
        'user', 'type', 'amount', 'balance_before', 'balance_after',
        'order', 'trade', 'market', 'description', 'created_at'
    ]
    date_hierarchy = 'created_at'

    def user_link(self, obj):
        url = reverse('admin:auctions_user_change', args=[obj.user.pk])
        return format_html('<a href="{}">{}</a>', url, obj.user.username)
    user_link.short_description = 'User'

    def amount_display(self, obj):
        color = 'green' if obj.amount >= 0 else 'red'
        sign = '+' if obj.amount >= 0 else ''
        return format_html('<span style="color: {};">{}{:.2f}</span>', color, sign, obj.amount)
    amount_display.short_description = 'Amount'

    def has_add_permission(self, request):
        return False  # Transactions are created by the system only

    def has_change_permission(self, request, obj=None):
        return False  # Transactions are immutable
