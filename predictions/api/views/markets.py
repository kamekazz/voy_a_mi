from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly, AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.utils import timezone
from decimal import Decimal
from drf_spectacular.utils import extend_schema, OpenApiParameter

from predictions.models import Category, Event, Market, Order, Trade, Position
from predictions.engine.matching import MatchingEngine, get_orderbook
from predictions.exceptions import (
    InsufficientFundsError,
    InsufficientPositionError,
    InvalidPriceError,
    MarketNotActiveError,
)
from predictions.api.serializers import (
    CategorySerializer,
    EventListSerializer,
    EventDetailSerializer,
    MarketListSerializer,
    MarketDetailSerializer,
    OrderSerializer,
    OrderCreateSerializer,
    QuickOrderSerializer,
    TradeSerializer,
    MintRedeemSerializer,
    OrderPreviewSerializer,
)
from predictions.api.serializers.trading import PositionSummarySerializer


class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for categories.

    GET /api/categories/ - List all categories
    GET /api/categories/<slug>/ - Get category detail
    """
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    lookup_field = 'slug'
    permission_classes = [AllowAny]


class EventViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for events.

    GET /api/events/ - List events (filterable by status, type, category)
    GET /api/events/<slug>/ - Get event detail with all markets
    """
    queryset = Event.objects.filter(
        status__in=[Event.Status.ACTIVE, Event.Status.CLOSED]
    ).select_related('category').prefetch_related('markets')
    lookup_field = 'slug'
    permission_classes = [AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'event_type', 'category__slug']
    search_fields = ['title', 'description']
    ordering_fields = ['trading_starts', 'trading_ends', 'created_at']
    ordering = ['-trading_starts']

    def get_serializer_class(self):
        if self.action == 'list':
            return EventListSerializer
        return EventDetailSerializer


class MarketViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for markets with trading actions.

    GET /api/markets/ - List active markets
    GET /api/markets/<id>/ - Get market detail
    GET /api/markets/<id>/orderbook/ - Get orderbook data
    GET /api/markets/<id>/trades/ - Get recent trades
    GET /api/markets/<id>/position/ - Get user's position (auth required)
    GET /api/markets/<id>/price-history/ - Get price history for charts
    POST /api/markets/<id>/orders/ - Place a new order (auth required)
    POST /api/markets/<id>/quick-order/ - Quick bet by amount (auth required)
    POST /api/markets/<id>/order-preview/ - Preview order before placing (auth required)
    POST /api/markets/<id>/mint/ - Mint complete set (auth required)
    POST /api/markets/<id>/redeem/ - Redeem complete set (auth required)
    """
    queryset = Market.objects.filter(
        status=Market.Status.ACTIVE,
        event__status=Event.Status.ACTIVE
    ).select_related('event', 'event__category')
    permission_classes = [AllowAny]
    filter_backends = [filters.OrderingFilter, filters.SearchFilter]
    search_fields = ['title', 'event__title']
    ordering_fields = ['total_volume', 'created_at', 'last_yes_price']
    ordering = ['-total_volume']

    def get_queryset(self):
        """Allow viewing all markets, not just active ones."""
        if self.action in ['retrieve', 'orderbook', 'trades', 'price_history']:
            return Market.objects.select_related('event', 'event__category')
        return super().get_queryset()

    def get_serializer_class(self):
        if self.action == 'list':
            return MarketListSerializer
        return MarketDetailSerializer

    @extend_schema(
        responses={200: {'type': 'object'}},
        description='Get current orderbook for a market'
    )
    @action(detail=True, methods=['get'], permission_classes=[AllowAny])
    def orderbook(self, request, pk=None):
        """GET /api/markets/<id>/orderbook/"""
        market = self.get_object()
        orderbook = get_orderbook(market, depth=10)

        return Response({
            'market_id': market.pk,
            'last_yes_price': market.last_yes_price,
            'last_no_price': market.last_no_price,
            'best_yes_bid': market.best_yes_bid,
            'best_yes_ask': market.best_yes_ask,
            'best_no_bid': market.best_no_bid,
            'best_no_ask': market.best_no_ask,
            'orderbook': orderbook,
        })

    @extend_schema(
        responses={200: TradeSerializer(many=True)},
        description='Get recent trades for a market'
    )
    @action(detail=True, methods=['get'], permission_classes=[AllowAny])
    def trades(self, request, pk=None):
        """GET /api/markets/<id>/trades/"""
        market = self.get_object()
        trades = Trade.objects.filter(market=market).order_by('-executed_at')[:50]

        serialized = []
        for t in trades:
            serialized.append({
                'id': t.id,
                'contract_type': t.contract_type,
                'price': t.price,
                'quantity': t.quantity,
                'trade_type': t.trade_type,
                'executed_at': t.executed_at.isoformat(),
            })

        return Response({
            'market_id': market.pk,
            'trades': serialized
        })

    @extend_schema(
        responses={200: PositionSummarySerializer},
        description='Get user\'s position in this market (requires authentication)'
    )
    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated])
    def position(self, request, pk=None):
        """GET /api/markets/<id>/position/"""
        market = self.get_object()
        position = Position.objects.filter(user=request.user, market=market).first()

        if position:
            return Response({
                'market_id': market.pk,
                'yes_quantity': position.yes_quantity,
                'no_quantity': position.no_quantity,
                'available_yes': position.yes_quantity - position.reserved_yes_quantity,
                'available_no': position.no_quantity - position.reserved_no_quantity,
                'yes_avg_cost': float(position.yes_avg_cost),
                'no_avg_cost': float(position.no_avg_cost),
                'unrealized_pnl': float(position.total_unrealized_pnl),
                'realized_pnl': float(position.realized_pnl),
            })
        return Response({
            'market_id': market.pk,
            'yes_quantity': 0,
            'no_quantity': 0,
            'available_yes': 0,
            'available_no': 0,
            'yes_avg_cost': 0,
            'no_avg_cost': 0,
            'unrealized_pnl': 0,
            'realized_pnl': 0,
        })

    @extend_schema(
        parameters=[
            OpenApiParameter(name='timeframe', description='Time range: 1h, 24h, 7d, all', type=str)
        ],
        responses={200: {'type': 'object'}},
        description='Get price history for charting'
    )
    @action(detail=True, methods=['get'], url_path='price-history', permission_classes=[AllowAny])
    def price_history(self, request, pk=None):
        """GET /api/markets/<id>/price-history/?timeframe=24h"""
        from datetime import timedelta

        market = self.get_object()
        timeframe = request.GET.get('timeframe', '24h')
        now = timezone.now()

        # Determine cutoff time
        if timeframe == '1h':
            cutoff = now - timedelta(hours=1)
        elif timeframe == '24h':
            cutoff = now - timedelta(hours=24)
        elif timeframe == '7d':
            cutoff = now - timedelta(days=7)
        else:
            cutoff = market.created_at

        start_time = max(cutoff, market.created_at)

        # Get starting price from last trade before cutoff
        start_yes = 50
        start_no = 50

        if start_time > market.created_at:
            last_trade_before = Trade.objects.filter(
                market=market,
                executed_at__lt=start_time
            ).order_by('-executed_at').first()

            if last_trade_before:
                if last_trade_before.contract_type == 'yes':
                    start_yes = last_trade_before.price
                    start_no = 100 - last_trade_before.price
                else:
                    start_no = last_trade_before.price
                    start_yes = 100 - last_trade_before.price

        # Get trades within window
        trades = Trade.objects.filter(
            market=market,
            executed_at__gte=start_time
        ).order_by('executed_at').values('executed_at', 'price', 'contract_type')

        # Build price history
        price_history = [{
            'time': start_time.timestamp() * 1000,
            'yes_price': start_yes,
            'no_price': start_no,
        }]

        current_yes = start_yes
        current_no = start_no

        for trade in trades:
            if trade['contract_type'] == 'yes':
                p_yes = trade['price']
                p_no = 100 - trade['price']
            else:
                p_no = trade['price']
                p_yes = 100 - trade['price']

            price_history.append({
                'time': trade['executed_at'].timestamp() * 1000,
                'yes_price': p_yes,
                'no_price': p_no,
            })
            current_yes = p_yes
            current_no = p_no

        # Add current point
        price_history.append({
            'time': now.timestamp() * 1000,
            'yes_price': current_yes,
            'no_price': current_no,
        })

        return Response({
            'market_id': market.pk,
            'price_history': price_history,
            'current_yes': market.last_yes_price,
            'current_no': market.last_no_price,
        })

    @extend_schema(
        request=OrderCreateSerializer,
        responses={201: OrderSerializer},
        description='Place a new limit or market order'
    )
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def orders(self, request, pk=None):
        """POST /api/markets/<id>/orders/ - Place a new order"""
        market = self.get_object()
        serializer = OrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        try:
            engine = MatchingEngine(market)
            order, trades = engine.place_order(
                user=request.user,
                side=data['side'],
                contract_type=data['contract_type'],
                price=data.get('price'),
                quantity=data['quantity'],
                order_type=data['order_type']
            )

            return Response({
                'order': OrderSerializer(order).data,
                'trades': [TradeSerializer(t, context={'request': request}).data for t in trades],
                'message': f"Order placed. {order.filled_quantity}/{order.quantity} filled."
            }, status=status.HTTP_201_CREATED)

        except InsufficientFundsError as e:
            return Response({
                'error': 'insufficient_funds',
                'message': f"Insufficient funds. You have ${e.available:.2f} available.",
                'available': float(e.available),
            }, status=status.HTTP_400_BAD_REQUEST)
        except InsufficientPositionError as e:
            return Response({
                'error': 'insufficient_position',
                'message': f"Insufficient {e.contract_type.upper()} shares. You have {e.available}.",
                'contract_type': e.contract_type,
                'available': e.available,
            }, status=status.HTTP_400_BAD_REQUEST)
        except InvalidPriceError:
            return Response({
                'error': 'invalid_price',
                'message': "Price must be between 1 and 99 cents.",
            }, status=status.HTTP_400_BAD_REQUEST)
        except MarketNotActiveError:
            return Response({
                'error': 'market_not_active',
                'message': "Market is not active for trading.",
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'error': 'order_failed',
                'message': str(e),
            }, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        request=QuickOrderSerializer,
        responses={201: OrderSerializer},
        description='Place a quick market order by dollar amount (buy) or quantity (sell)'
    )
    @action(detail=True, methods=['post'], url_path='quick-order', permission_classes=[IsAuthenticated])
    def quick_order(self, request, pk=None):
        """POST /api/markets/<id>/quick-order/"""
        market = self.get_object()
        serializer = QuickOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        action = data['action']
        contract_type = data['contract_type']
        amount = data['amount']

        if not market.is_trading_active:
            return Response({
                'error': 'market_not_active',
                'message': "Market is not active for trading.",
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            engine = MatchingEngine(market)

            if action == 'sell':
                quantity = int(amount)
                if quantity <= 0:
                    return Response({
                        'error': 'invalid_quantity',
                        'message': "Quantity must be at least 1 share.",
                    }, status=status.HTTP_400_BAD_REQUEST)

                order, trades = engine.place_order(
                    user=request.user,
                    side='sell',
                    contract_type=contract_type,
                    price=None,
                    quantity=quantity,
                    order_type='market'
                )
            else:
                # Buy: Calculate quantity based on current price
                current_price = market.last_yes_price if contract_type == 'yes' else market.last_no_price
                if current_price <= 0:
                    current_price = 50
                quantity = int(float(amount) * 100 / current_price)

                if quantity < 1:
                    return Response({
                        'error': 'amount_too_small',
                        'message': "Amount too small to purchase any shares.",
                    }, status=status.HTTP_400_BAD_REQUEST)

                order, trades = engine.place_order(
                    user=request.user,
                    side='buy',
                    contract_type=contract_type,
                    price=None,
                    quantity=quantity,
                    order_type='market'
                )

            if trades:
                total = sum(t.quantity * t.price / 100 for t in trades)
                message = f"{'Sold' if action == 'sell' else 'Bought'} {order.filled_quantity} {contract_type.upper()} shares for ${total:.2f}"
            else:
                message = f"Order placed for {quantity} {contract_type.upper()} shares. Waiting for match."

            return Response({
                'order': OrderSerializer(order).data,
                'trades': [TradeSerializer(t, context={'request': request}).data for t in trades],
                'message': message
            }, status=status.HTTP_201_CREATED)

        except InsufficientFundsError as e:
            return Response({
                'error': 'insufficient_funds',
                'message': f"Insufficient balance. You have ${e.available:.2f} available.",
                'available': float(e.available),
            }, status=status.HTTP_400_BAD_REQUEST)
        except InsufficientPositionError as e:
            return Response({
                'error': 'insufficient_position',
                'message': f"Insufficient {e.contract_type.upper()} shares. You have {e.available}.",
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'error': 'order_failed',
                'message': str(e),
            }, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        request=OrderPreviewSerializer,
        responses={200: {'type': 'object'}},
        description='Preview order calculation before placing'
    )
    @action(detail=True, methods=['post'], url_path='order-preview', permission_classes=[IsAuthenticated])
    def order_preview(self, request, pk=None):
        """POST /api/markets/<id>/order-preview/"""
        market = self.get_object()
        serializer = OrderPreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        action = data['action']
        contract_type = data['contract_type']
        order_type = data['order_type']

        user = request.user
        user_balance = float(user.available_balance)

        position = Position.objects.filter(user=user, market=market).first()
        user_position = {
            'yes': (position.yes_quantity - position.reserved_yes_quantity) if position else 0,
            'no': (position.no_quantity - position.reserved_no_quantity) if position else 0
        }

        result = {
            'user_balance': user_balance,
            'user_position': user_position,
            'current_yes_price': market.last_yes_price,
            'current_no_price': market.last_no_price,
            'warning': None,
        }

        if order_type == 'limit':
            price = data['price']
            quantity = data['quantity']
            total = quantity * price / 100

            result.update({
                'shares': quantity,
                'avg_price': price,
                'total_cost': total if action == 'buy' else 0,
                'total_proceeds': total if action == 'sell' else 0,
                'potential_payout': quantity,
                'implied_probability': price,
            })

            if action == 'buy' and total > user_balance:
                result['warning'] = f'Insufficient funds. You have ${user_balance:.2f}'
            elif action == 'sell':
                available = user_position.get(contract_type, 0)
                if quantity > available:
                    result['warning'] = f'Insufficient {contract_type.upper()} shares. You have {available}'
        else:
            # Market order
            amount = float(data['amount'])
            orderbook = get_orderbook(market, depth=50)

            if action == 'buy':
                current_price = market.last_yes_price if contract_type == 'yes' else market.last_no_price
                if current_price <= 0:
                    current_price = 50
                shares = int(amount * 100 / current_price)

                result.update({
                    'shares': shares,
                    'avg_price': current_price,
                    'total_cost': amount,
                    'total_proceeds': 0,
                    'potential_payout': shares,
                    'implied_probability': current_price,
                })

                if amount > user_balance:
                    result['warning'] = f'Insufficient funds. You have ${user_balance:.2f}'
                elif shares == 0:
                    result['warning'] = 'Amount too small to purchase any shares'
            else:
                quantity = int(amount)
                current_price = market.last_yes_price if contract_type == 'yes' else market.last_no_price
                proceeds = quantity * current_price / 100

                result.update({
                    'shares': quantity,
                    'avg_price': current_price,
                    'total_cost': 0,
                    'total_proceeds': proceeds,
                    'potential_payout': proceeds,
                    'implied_probability': current_price,
                })

                available = user_position.get(contract_type, 0)
                if quantity > available:
                    result['warning'] = f'Insufficient {contract_type.upper()} shares. You have {available}'

        return Response(result)

    @extend_schema(
        request=MintRedeemSerializer,
        responses={201: {'type': 'object'}},
        description='Mint complete set (1 YES + 1 NO for $1)'
    )
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def mint(self, request, pk=None):
        """POST /api/markets/<id>/mint/"""
        market = self.get_object()
        serializer = MintRedeemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        quantity = serializer.validated_data['quantity']
        cost = Decimal(quantity)
        user = request.user

        if not market.is_trading_active:
            return Response({
                'error': 'market_not_active',
                'message': "Market is not active.",
            }, status=status.HTTP_400_BAD_REQUEST)

        if user.balance < cost:
            return Response({
                'error': 'insufficient_funds',
                'message': f"Insufficient funds. Need ${cost:.2f}, have ${user.balance:.2f}.",
            }, status=status.HTTP_400_BAD_REQUEST)

        # Reserve funds
        user.balance -= cost
        user.reserved_balance += cost
        user.save()

        # Create mint request order
        order = Order.objects.create(
            user=user,
            market=market,
            side='buy',
            contract_type='yes',
            order_type='mint_set',
            price=Decimal('1.00'),
            quantity=quantity,
            status=Order.Status.OPEN
        )

        return Response({
            'order': OrderSerializer(order).data,
            'message': f"Mint request submitted for {quantity} complete sets. Processing..."
        }, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=MintRedeemSerializer,
        responses={201: {'type': 'object'}},
        description='Redeem complete set (1 YES + 1 NO for $1)'
    )
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def redeem(self, request, pk=None):
        """POST /api/markets/<id>/redeem/"""
        market = self.get_object()
        serializer = MintRedeemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        quantity = serializer.validated_data['quantity']
        user = request.user

        if not market.is_trading_active:
            return Response({
                'error': 'market_not_active',
                'message': "Market is not active.",
            }, status=status.HTTP_400_BAD_REQUEST)

        position, _ = Position.objects.get_or_create(user=user, market=market)

        if position.yes_quantity < quantity:
            return Response({
                'error': 'insufficient_position',
                'message': f"Insufficient YES contracts. You have {position.yes_quantity}.",
            }, status=status.HTTP_400_BAD_REQUEST)

        if position.no_quantity < quantity:
            return Response({
                'error': 'insufficient_position',
                'message': f"Insufficient NO contracts. You have {position.no_quantity}.",
            }, status=status.HTTP_400_BAD_REQUEST)

        # Reserve shares
        position.yes_quantity -= quantity
        position.reserved_yes_quantity += quantity
        position.no_quantity -= quantity
        position.reserved_no_quantity += quantity
        position.save()

        # Create redeem request order
        order = Order.objects.create(
            user=user,
            market=market,
            side='sell',
            contract_type='yes',
            order_type='redeem_set',
            price=Decimal('1.00'),
            quantity=quantity,
            status=Order.Status.OPEN
        )

        return Response({
            'order': OrderSerializer(order).data,
            'message': f"Redeem request submitted for {quantity} complete sets. Processing..."
        }, status=status.HTTP_201_CREATED)
