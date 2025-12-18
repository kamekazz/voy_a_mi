from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db.models import Sum, Q
from django.utils import timezone
from decimal import Decimal

from .models import User, Category, Event, Market, Order, Trade, Position, Transaction, AMMTrade
from .forms import UserRegistrationForm
from .forms import OrderForm, QuickOrderForm
from .matching_engine import MatchingEngine, get_orderbook
from .amm_engine import AMMEngine
from .exceptions import (
    TradingError,
    InsufficientFundsError,
    InsufficientPositionError,
    MarketNotActiveError,
)


def index(request):
    """Homepage showing active events and markets."""
    # Get active events
    active_events = Event.objects.filter(
        status=Event.Status.ACTIVE
    ).prefetch_related('markets', 'category')[:10]

    # Get featured/popular markets
    popular_markets = Market.objects.filter(
        status=Market.Status.ACTIVE,
        event__status=Event.Status.ACTIVE
    ).select_related('event').order_by('-total_volume')[:6]

    # Get categories with event counts
    categories = Category.objects.annotate(
        active_events=Sum('events__status')
    ).filter(events__status=Event.Status.ACTIVE).distinct()

    context = {
        'active_events': active_events,
        'popular_markets': popular_markets,
        'categories': categories,
    }
    return render(request, 'predictions/index.html', context)


def event_list(request):
    """List all events with filtering."""
    events = Event.objects.filter(
        status__in=[Event.Status.ACTIVE, Event.Status.CLOSED]
    ).select_related('category').prefetch_related('markets')

    # Filter by category
    category_slug = request.GET.get('category')
    if category_slug:
        events = events.filter(category__slug=category_slug)

    # Filter by status
    status = request.GET.get('status')
    if status:
        events = events.filter(status=status)

    # Filter by event type
    event_type = request.GET.get('type')
    if event_type:
        events = events.filter(event_type=event_type)

    categories = Category.objects.all()

    context = {
        'events': events,
        'categories': categories,
        'selected_category': category_slug,
        'selected_status': status,
        'selected_type': event_type,
    }
    return render(request, 'predictions/event_list.html', context)


def event_detail(request, slug):
    """Event detail page showing all markets."""
    event = get_object_or_404(
        Event.objects.select_related('category', 'created_by'),
        slug=slug
    )
    markets = event.markets.all()

    context = {
        'event': event,
        'markets': markets,
    }
    return render(request, 'predictions/event_detail.html', context)


def market_detail(request, pk):
    """Market detail page with orderbook and trading interface."""
    market = get_object_or_404(
        Market.objects.select_related('event', 'event__category'),
        pk=pk
    )

    # Get orderbook
    orderbook = get_orderbook(market, depth=10)

    # Get AMM prices if enabled
    amm_prices = None
    if market.amm_enabled:
        amm = AMMEngine(market)
        amm_prices = amm.get_prices()

    # Get recent trades (both orderbook and AMM)
    recent_trades = Trade.objects.filter(market=market).select_related(
        'buyer', 'seller'
    )[:20]
    recent_amm_trades = AMMTrade.objects.filter(
        pool__market=market
    ).select_related('user')[:20]

    # Get user's position and open orders if logged in
    user_position = None
    user_orders = []
    if request.user.is_authenticated:
        user_position = Position.objects.filter(
            user=request.user, market=market
        ).first()
        user_orders = Order.objects.filter(
            user=request.user,
            market=market,
            status__in=[Order.Status.OPEN, Order.Status.PARTIALLY_FILLED]
        )

    # Order form
    order_form = QuickOrderForm()

    context = {
        'market': market,
        'event': market.event,
        'orderbook': orderbook,
        'amm_prices': amm_prices,
        'recent_trades': recent_trades,
        'recent_amm_trades': recent_amm_trades,
        'user_position': user_position,
        'user_orders': user_orders,
        'order_form': order_form,
    }
    return render(request, 'predictions/market_detail.html', context)


@login_required
@require_POST
def place_order(request, pk):
    """Place a new order on a market."""
    market = get_object_or_404(Market, pk=pk)

    # Parse order parameters
    side = request.POST.get('side')
    contract_type = request.POST.get('contract_type')
    order_type = request.POST.get('order_type', 'market')  # Default to market order

    try:
        quantity = int(request.POST.get('quantity', 0))
        # Price is optional for market orders
        price_str = request.POST.get('price', '')
        price = int(price_str) if price_str and price_str.strip() else None
    except (ValueError, TypeError):
        messages.error(request, "Invalid price or quantity.")
        return redirect('predictions:market_detail', pk=pk)

    # Validate basic inputs
    if side not in ['buy', 'sell']:
        messages.error(request, "Invalid order side.")
        return redirect('predictions:market_detail', pk=pk)

    if contract_type not in ['yes', 'no']:
        messages.error(request, "Invalid contract type.")
        return redirect('predictions:market_detail', pk=pk)

    if order_type not in ['market', 'limit']:
        messages.error(request, "Invalid order type.")
        return redirect('predictions:market_detail', pk=pk)

    # Price is required for limit orders
    if order_type == 'limit' and not price:
        messages.error(request, "Price is required for limit orders.")
        return redirect('predictions:market_detail', pk=pk)

    try:
        # Route market orders to AMM if enabled
        if order_type == 'market' and market.amm_enabled:
            # Use AMM for instant execution
            amm = AMMEngine(market)
            trade = amm.execute_trade(
                user=request.user,
                side=side,
                contract_type=contract_type,
                quantity=quantity
            )
            messages.success(
                request,
                f"Trade executed! {side.upper()} {quantity} {contract_type.upper()} "
                f"@ {trade.avg_price:.1f}c avg (${trade.total_cost:.2f})"
            )
        else:
            # Use limit orderbook for limit orders
            engine = MatchingEngine(market)
            order, trades = engine.place_order(
                user=request.user,
                side=side,
                contract_type=contract_type,
                price=price,
                quantity=quantity,
                order_type=order_type
            )

            if trades:
                messages.success(
                    request,
                    f"Order executed! {len(trades)} trade(s), "
                    f"{order.filled_quantity} contracts filled @ {order.price}c."
                )
            else:
                messages.success(
                    request,
                    f"Limit order placed: {side.upper()} {quantity} "
                    f"{contract_type.upper()} @ {price}c"
                )

    except InsufficientFundsError as e:
        messages.error(request, str(e))
    except InsufficientPositionError as e:
        messages.error(request, str(e))
    except MarketNotActiveError as e:
        messages.error(request, str(e))
    except TradingError as e:
        messages.error(request, f"Trading error: {e}")

    return redirect('predictions:market_detail', pk=pk)


@login_required
@require_POST
def cancel_order(request, pk):
    """Cancel an open order."""
    order = get_object_or_404(Order, pk=pk)
    market_pk = order.market.pk

    engine = MatchingEngine(order.market)

    try:
        engine.cancel_order(order, request.user)
        messages.success(request, "Order cancelled successfully.")
    except TradingError as e:
        messages.error(request, str(e))

    return redirect('predictions:market_detail', pk=market_pk)


@login_required
def portfolio(request):
    """User's portfolio showing all positions."""
    positions = Position.objects.filter(
        user=request.user
    ).filter(
        Q(yes_quantity__gt=0) | Q(no_quantity__gt=0)
    ).select_related('market', 'market__event')

    # Calculate total unrealized P&L
    total_unrealized = sum(p.total_unrealized_pnl for p in positions)
    total_realized = sum(p.realized_pnl for p in positions)

    context = {
        'positions': positions,
        'total_unrealized': total_unrealized,
        'total_realized': total_realized,
        'balance': request.user.balance,
        'available_balance': request.user.available_balance,
    }
    return render(request, 'predictions/portfolio.html', context)


@login_required
def order_history(request):
    """User's order history."""
    orders = Order.objects.filter(
        user=request.user
    ).select_related('market', 'market__event').order_by('-created_at')

    # Filter by status
    status = request.GET.get('status')
    if status:
        orders = orders.filter(status=status)

    context = {
        'orders': orders,
        'selected_status': status,
    }
    return render(request, 'predictions/order_history.html', context)


@login_required
def trade_history(request):
    """User's trade history."""
    trades = Trade.objects.filter(
        Q(buyer=request.user) | Q(seller=request.user)
    ).select_related('market', 'market__event', 'buyer', 'seller').order_by('-executed_at')

    context = {
        'trades': trades,
    }
    return render(request, 'predictions/trade_history.html', context)


@login_required
def transactions(request):
    """User's transaction history."""
    txns = Transaction.objects.filter(
        user=request.user
    ).select_related('market', 'order', 'trade').order_by('-created_at')

    # Filter by type
    txn_type = request.GET.get('type')
    if txn_type:
        txns = txns.filter(type=txn_type)

    context = {
        'transactions': txns,
        'selected_type': txn_type,
        'transaction_types': Transaction.Type.choices,
    }
    return render(request, 'predictions/transactions.html', context)


# API Views (for AJAX/future mobile app)

def api_orderbook(request, pk):
    """Get current orderbook for a market as JSON."""
    market = get_object_or_404(Market, pk=pk)
    orderbook = get_orderbook(market)

    return JsonResponse({
        'market_id': market.pk,
        'last_yes_price': market.last_yes_price,
        'last_no_price': market.last_no_price,
        'best_yes_bid': market.best_yes_bid,
        'best_yes_ask': market.best_yes_ask,
        'best_no_bid': market.best_no_bid,
        'best_no_ask': market.best_no_ask,
        'orderbook': orderbook,
    })


def api_recent_trades(request, pk):
    """Get recent trades for a market as JSON."""
    market = get_object_or_404(Market, pk=pk)
    trades = Trade.objects.filter(market=market).order_by('-executed_at')[:50]

    return JsonResponse({
        'market_id': market.pk,
        'trades': [
            {
                'id': t.id,
                'contract_type': t.contract_type,
                'price': t.price,
                'quantity': t.quantity,
                'executed_at': t.executed_at.isoformat(),
            }
            for t in trades
        ]
    })


@login_required
def api_user_position(request, pk):
    """Get user's position in a market as JSON."""
    market = get_object_or_404(Market, pk=pk)
    position = Position.objects.filter(user=request.user, market=market).first()

    if position:
        return JsonResponse({
            'yes_quantity': position.yes_quantity,
            'no_quantity': position.no_quantity,
            'yes_avg_cost': float(position.yes_avg_cost),
            'no_avg_cost': float(position.no_avg_cost),
            'unrealized_pnl': float(position.total_unrealized_pnl),
            'realized_pnl': float(position.realized_pnl),
        })
    else:
        return JsonResponse({
            'yes_quantity': 0,
            'no_quantity': 0,
            'yes_avg_cost': 0,
            'no_avg_cost': 0,
            'unrealized_pnl': 0,
            'realized_pnl': 0,
        })


def api_amm_quote(request, pk):
    """Get a quote from the AMM for a potential trade."""
    market = get_object_or_404(Market, pk=pk)

    if not market.amm_enabled:
        return JsonResponse({'error': 'AMM not enabled for this market'}, status=400)

    side = request.GET.get('side', 'buy')
    contract_type = request.GET.get('contract_type', 'yes')
    try:
        quantity = int(request.GET.get('quantity', 1))
    except ValueError:
        return JsonResponse({'error': 'Invalid quantity'}, status=400)

    if side not in ['buy', 'sell']:
        return JsonResponse({'error': 'Invalid side'}, status=400)

    if contract_type not in ['yes', 'no']:
        return JsonResponse({'error': 'Invalid contract type'}, status=400)

    amm = AMMEngine(market)
    quote = amm.get_quote(side, contract_type, quantity)

    return JsonResponse({
        'market_id': market.pk,
        'quote': quote,
        'current_prices': amm.get_prices(),
    })


def api_amm_prices(request, pk):
    """Get current AMM prices for a market."""
    market = get_object_or_404(Market, pk=pk)

    if not market.amm_enabled:
        return JsonResponse({'error': 'AMM not enabled for this market'}, status=400)

    amm = AMMEngine(market)
    prices = amm.get_prices()

    return JsonResponse({
        'market_id': market.pk,
        'yes_price': prices['yes'],
        'no_price': prices['no'],
        'last_yes_price': market.last_yes_price,
        'last_no_price': market.last_no_price,
        'total_volume': market.total_volume,
    })


def register(request):
    """User registration view."""
    if request.user.is_authenticated:
        return redirect('predictions:index')

    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, 'Account created successfully! Welcome to Voy a Mi.')
            return redirect('predictions:index')
    else:
        form = UserRegistrationForm()

    return render(request, 'registration/register.html', {'form': form})
