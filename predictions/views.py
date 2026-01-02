from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST
from django.db.models import Q, F, Sum
from django.utils import timezone
from decimal import Decimal, InvalidOperation

from .models import User, Category, Event, Market, Order, Trade, Position, Transaction, UserPreferences
from .forms import UserRegistrationForm
from .forms import OrderForm, QuickOrderForm
from .engine.matching import get_orderbook, MatchingEngine
from .exceptions import (
    InsufficientFundsError,
    InsufficientPositionError,
    InvalidPriceError,
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


def market_detail(request, market_id):
    """Market detail page with orderbook and trading interface."""
    market = get_object_or_404(
        Market.objects.select_related('event', 'event__category'),
        pk=market_id
    )

    # Get orderbook
    orderbook = get_orderbook(market, depth=10)

    # Get recent trades from order book
    recent_trades = Trade.objects.filter(market=market).select_related(
        'buyer', 'seller'
    ).order_by('-executed_at')[:20]

    # Get user's position and open orders if logged in
    user_position = None
    user_orders = []
    ui_mode = 'easy'  # Default for anonymous users

    if request.user.is_authenticated:
        user_position = Position.objects.filter(
            user=request.user, market=market
        ).first()
        user_orders = Order.objects.filter(
            user=request.user,
            market=market,
            status__in=[Order.Status.OPEN, Order.Status.PARTIALLY_FILLED]
        )
        # Get UI mode preference
        preferences, _ = UserPreferences.objects.get_or_create(user=request.user)
        ui_mode = preferences.ui_mode

    # Order form
    order_form = QuickOrderForm()

    # Order book prices (use last traded price or best bid/ask)
    ob_prices = {
        'yes_price': market.last_yes_price,
        'no_price': market.last_no_price,
        'best_yes_bid': market.best_yes_bid,
        'best_yes_ask': market.best_yes_ask,
        'best_no_bid': market.best_no_bid,
        'best_no_ask': market.best_no_ask,
    }

    context = {
        'market': market,
        'event': market.event,
        'ob_prices': ob_prices,
        'orderbook': orderbook,
        'recent_trades': recent_trades,
        'user_position': user_position,
        'user_orders': user_orders,
        'order_form': order_form,
        'ui_mode': ui_mode,
    }
    return render(request, 'predictions/market_detail_fixed.html', context)

def order_book_json(request, market_id):
    market = get_object_or_404(Market, pk=market_id)
    
    buy_yes = Order.objects.filter(market=market, order_type='BUY', outcome='YES').values('price').annotate(total=Sum('quantity')).order_by('-price')
    sell_yes = Order.objects.filter(market=market, order_type='SELL', outcome='YES').values('price').annotate(total=Sum('quantity')).order_by('price')
    buy_no = Order.objects.filter(market=market, order_type='BUY', outcome='NO').values('price').annotate(total=Sum('quantity')).order_by('-price')
    sell_no = Order.objects.filter(market=market, order_type='SELL', outcome='NO').values('price').annotate(total=Sum('quantity')).order_by('price')
    
    return JsonResponse({
        'buy_yes': list(buy_yes),
        'sell_yes': list(sell_yes),
        'buy_no': list(buy_no),
        'sell_no': list(sell_no)
    })


@login_required
@require_POST
def place_order(request, pk):
    """Place a new order on a market using the matching engine."""
    market = get_object_or_404(Market, pk=pk)

    order_type_input = request.POST.get('order_type')  # 'BUY' or 'SELL'
    outcome_input = request.POST.get('outcome')
    if not outcome_input:
        return HttpResponse("Missing outcome")
    contract_type = outcome_input.lower()

    price_input = request.POST.get('price')

    try:
        quantity = int(request.POST.get('quantity'))
    except (ValueError, TypeError):
        messages.error(request, "Invalid quantity.")
        return redirect('predictions:market_detail', market_id=market.id)

    # Handle price - convert to cents for matching engine
    if not price_input:
        price_cents = None  # Market order
        actual_order_type = 'market'
    else:
        try:
            price_cents = int(price_input)
            # Validate price range (1-99 cents)
            if price_cents < 1 or price_cents > 99:
                messages.error(request, "Price must be between 1 and 99 cents")
                return redirect('predictions:market_detail', market_id=market.id)
            actual_order_type = 'limit'
        except (ValueError, TypeError):
            messages.error(request, "Invalid price.")
            return redirect('predictions:market_detail', market_id=market.id)

    user = request.user
    side = order_type_input.lower()  # 'buy' or 'sell'

    try:
        engine = MatchingEngine(market)
        order, trades = engine.place_order(
            user=user,
            side=side,
            contract_type=contract_type,
            price=price_cents,  # In cents, or None for market order
            quantity=quantity,
            order_type=actual_order_type
        )

        if trades:
            if side == 'buy':
                total = sum(t.quantity * t.price / 100 for t in trades)
                messages.success(request, f"Bought {order.filled_quantity} {contract_type.upper()} shares for ${total:.2f}")
            else:
                total = sum(t.quantity * t.price / 100 for t in trades)
                messages.success(request, f"Sold {order.filled_quantity} {contract_type.upper()} shares for ${total:.2f}")
        elif order.filled_quantity > 0:
            messages.success(request, f"Partially filled: {order.filled_quantity}/{quantity} shares.")
        else:
            messages.success(request, f"Order placed for {quantity} {contract_type.upper()} @ {price_cents}c. Waiting for match.")

    except InsufficientFundsError as e:
        messages.error(request, f"Insufficient funds. You have ${e.available:.2f} available.")
    except InsufficientPositionError as e:
        messages.error(request, f"Insufficient {e.contract_type.upper()} shares. You have {e.available}.")
    except InvalidPriceError:
        messages.error(request, "Price must be between 1 and 99 cents.")
    except MarketNotActiveError:
        messages.error(request, "Market is not active for trading.")
    except Exception as e:
        messages.error(request, f"Error placing order: {e}")

    return redirect('predictions:market_detail', market_id=market.id)

@login_required
@require_POST
def place_quick_bet(request, pk):
    """Place a quick bet using the matching engine.

    Buy: User specifies dollar amount and contract type (YES/NO).
    Sell: User specifies number of shares to sell.
    Order is placed and immediately matched by the engine.
    """
    market = get_object_or_404(Market, pk=pk)

    # Validate market is active
    if not market.is_trading_active:
        messages.error(request, "Market is not active for trading.")
        return redirect('predictions:market_detail', market_id=pk)

    # Parse parameters
    action = request.POST.get('action', 'buy')  # 'buy' or 'sell'
    contract_type = request.POST.get('contract_type')

    # Validate contract type
    if contract_type not in ['yes', 'no']:
        messages.error(request, "Please select YES or NO.")
        return redirect('predictions:market_detail', market_id=pk)

    try:
        user = request.user
        engine = MatchingEngine(market)

        if action == 'sell':
            # SELL: User enters number of shares to sell
            try:
                quantity = int(request.POST.get('amount', '0'))
            except (ValueError, TypeError):
                messages.error(request, "Invalid quantity.")
                return redirect('predictions:market_detail', market_id=pk)

            if quantity <= 0:
                messages.error(request, "Quantity must be at least 1 share.")
                return redirect('predictions:market_detail', market_id=pk)

            # Use matching engine to place and match the order
            order, trades = engine.place_order(
                user=user,
                side='sell',
                contract_type=contract_type,
                price=None,  # Market order
                quantity=quantity,
                order_type='market'
            )

            if trades:
                total_proceeds = sum(t.quantity * t.price / 100 for t in trades)
                messages.success(request, f"Sold {order.filled_quantity} {contract_type.upper()} shares for ${total_proceeds:.2f}")
            elif order.filled_quantity > 0:
                messages.success(request, f"Partially filled: {order.filled_quantity}/{quantity} shares sold.")
            else:
                messages.info(request, f"Sell order placed for {quantity} {contract_type.upper()} shares. Waiting for match.")

        else:
            # BUY: User enters dollar amount
            try:
                amount = Decimal(request.POST.get('amount', '0'))
            except (ValueError, TypeError, InvalidOperation):
                messages.error(request, "Invalid amount.")
                return redirect('predictions:market_detail', market_id=pk)

            if amount <= 0:
                messages.error(request, "Amount must be greater than $0.")
                return redirect('predictions:market_detail', market_id=pk)

            # Calculate quantity based on current price
            current_price = market.last_yes_price if contract_type == 'yes' else market.last_no_price
            if current_price <= 0:
                current_price = 50  # Default to 50c
            quantity = int(amount * 100 / current_price)

            if quantity < 1:
                messages.error(request, f"Amount too small to buy any shares.")
                return redirect('predictions:market_detail', market_id=pk)

            # Use matching engine to place and match the order
            order, trades = engine.place_order(
                user=user,
                side='buy',
                contract_type=contract_type,
                price=None,  # Market order - engine determines price
                quantity=quantity,
                order_type='market'
            )

            if trades:
                total_cost = sum(t.quantity * t.price / 100 for t in trades)
                messages.success(request, f"Bought {order.filled_quantity} {contract_type.upper()} shares for ${total_cost:.2f}")
            elif order.filled_quantity > 0:
                messages.success(request, f"Partially filled: {order.filled_quantity}/{quantity} shares bought.")
            else:
                messages.info(request, f"Buy order placed for {quantity} {contract_type.upper()} shares. Waiting for match.")

    except InsufficientFundsError as e:
        messages.error(request, f"Insufficient balance. You have ${e.available:.2f} available.")
    except InsufficientPositionError as e:
        messages.error(request, f"Insufficient {e.contract_type.upper()} shares. You have {e.available}.")
    except MarketNotActiveError:
        messages.error(request, "Market is not active for trading.")
    except Exception as e:
        messages.error(request, f"Error placing order: {e}")

    return redirect('predictions:market_detail', market_id=pk)


@login_required
@require_POST
def cancel_order(request, pk):
    """Cancel an order and refund reserved funds/shares."""
    order = get_object_or_404(Order, pk=pk, user=request.user)
    market = order.market

    # Only allow cancelling open or partially filled orders
    if order.status not in [Order.Status.OPEN, Order.Status.PARTIALLY_FILLED]:
        messages.error(request, "Order cannot be cancelled.")
        return redirect('predictions:market_detail', market_id=market.id)

    # Get user balance and position
    user = request.user
    position, _ = Position.objects.get_or_create(user=request.user, market=market)

    # Calculate remaining quantity (unfilled portion)
    remaining_qty = order.quantity - order.filled_quantity

    if order.order_type == 'mint_set':
        # Refund reserved funds for mint request
        refund = Decimal(remaining_qty)  # $1 per set
        user.reserved_balance -= refund
        user.balance += refund
        user.save()

    elif order.order_type == 'redeem_set':
        # Return reserved shares for redeem request
        position.reserved_yes_quantity -= remaining_qty
        position.yes_quantity += remaining_qty
        position.reserved_no_quantity -= remaining_qty
        position.no_quantity += remaining_qty
        position.save()

    elif order.side == 'buy':
        # Refund reserved funds for buy order
        refund_price = order.price if order.price is not None else Decimal('1.00')
        refund = refund_price * remaining_qty
        user.reserved_balance -= refund
        user.balance += refund
        user.save()

    elif order.side == 'sell':
        # Return reserved shares for sell order
        if order.contract_type == 'yes':
            position.reserved_yes_quantity -= remaining_qty
            position.yes_quantity += remaining_qty
        else:
            position.reserved_no_quantity -= remaining_qty
            position.no_quantity += remaining_qty
        position.save()

    order.status = Order.Status.CANCELLED
    order.save()

    messages.success(request, "Order cancelled.")
    return redirect('predictions:market_detail', market_id=market.id)





@login_required
@require_POST
def mint_complete_set_view(request, pk):
    """Request to mint complete sets - engine processes in background."""
    market = get_object_or_404(Market, pk=pk)

    if not market.is_trading_active:
        messages.error(request, "Market is not active.")
        return redirect('predictions:market_detail', market_id=pk)

    try:
        quantity = int(request.POST.get('quantity', 0))
    except (ValueError, TypeError):
        messages.error(request, "Invalid quantity.")
        return redirect('predictions:market_detail', market_id=pk)

    if quantity <= 0:
        messages.error(request, "Quantity must be positive.")
        return redirect('predictions:market_detail', market_id=pk)

    cost = Decimal(quantity)  # $1 per complete set

    user = request.user

    if user.balance < cost:
        messages.error(request, f"Insufficient funds. Need ${cost:.2f}, have ${user.balance:.2f}.")
        return redirect('predictions:market_detail', market_id=pk)

    # Reserve funds
    user.balance -= cost
    user.reserved_balance += cost
    user.save()

    # Create mint request as special order type - engine will process
    Order.objects.create(
        user=request.user,
        market=market,
        side='buy',  # Conceptually buying complete sets
        contract_type='yes',  # Placeholder - minting gives both YES and NO
        order_type='mint_set',
        price=Decimal('1.00'),  # $1 per set
        quantity=quantity,
        status=Order.Status.OPEN
    )

    messages.success(request, f"Mint request submitted for {quantity} complete sets. Processing...")
    return redirect('predictions:market_detail', market_id=pk)


@login_required
@require_POST
def redeem_complete_set_view(request, pk):
    """Request to redeem complete sets - engine processes in background."""
    market = get_object_or_404(Market, pk=pk)

    if not market.is_trading_active:
        messages.error(request, "Market is not active.")
        return redirect('predictions:market_detail', market_id=pk)

    try:
        quantity = int(request.POST.get('quantity', 0))
    except (ValueError, TypeError):
        messages.error(request, "Invalid quantity.")
        return redirect('predictions:market_detail', market_id=pk)

    if quantity <= 0:
        messages.error(request, "Quantity must be positive.")
        return redirect('predictions:market_detail', market_id=pk)

    position, _ = Position.objects.get_or_create(user=request.user, market=market)

    # Check user has enough of BOTH contract types
    if position.yes_quantity < quantity:
        messages.error(request, f"Insufficient YES contracts. You have {position.yes_quantity}.")
        return redirect('predictions:market_detail', market_id=pk)
    if position.no_quantity < quantity:
        messages.error(request, f"Insufficient NO contracts. You have {position.no_quantity}.")
        return redirect('predictions:market_detail', market_id=pk)

    # Reserve both YES and NO shares
    position.yes_quantity -= quantity
    position.reserved_yes_quantity += quantity
    position.no_quantity -= quantity
    position.reserved_no_quantity += quantity
    position.save()

    # Create redeem request as special order type - engine will process
    Order.objects.create(
        user=request.user,
        market=market,
        side='sell',  # Conceptually selling/burning complete sets
        contract_type='yes',  # Placeholder - redeeming burns both
        order_type='redeem_set',
        price=Decimal('1.00'),  # $1 per set payout
        quantity=quantity,
        status=Order.Status.OPEN
    )

    messages.success(request, f"Redeem request submitted for {quantity} complete sets. Processing...")
    return redirect('predictions:market_detail', market_id=pk)


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
    """Get recent trades for a market as JSON (Order Book only)."""
    market = get_object_or_404(Market, pk=pk)

    # Fetch Order Book Trades
    trades = Trade.objects.filter(market=market).order_by('-executed_at')[:50]

    # Serialize trades
    serialized = []
    for t in trades:
        serialized.append({
            'id': t.id,
            'contract_type': t.contract_type,
            'price': t.price,
            'avg_price': t.price,  # Frontend expects avg_price
            'quantity': t.quantity,
            'trade_type': t.trade_type,  # direct, mint, or merge
            'side': 'buy',  # All trades have a buyer
            'executed_at': t.executed_at.isoformat(),
        })

    return JsonResponse({
        'market_id': market.pk,
        'trades': serialized
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


def api_price_history(request, pk):
    """Get price history from Order Book trades for charting."""
    from datetime import timedelta

    market = get_object_or_404(Market, pk=pk)

    # Parse timeframe parameter
    timeframe = request.GET.get('timeframe', '24h')
    now = timezone.now()

    # Determine the cutoff time
    if timeframe == '1h':
        cutoff = now - timedelta(hours=1)
    elif timeframe == '24h':
        cutoff = now - timedelta(hours=24)
    elif timeframe == '7d':
        cutoff = now - timedelta(days=7)
    else:  # 'all'
        cutoff = market.created_at

    # The actual start time for the chart is the later of cutoff or market creation
    start_time = max(cutoff, market.created_at)

    # Determine starting price from last trade before cutoff
    start_yes = 50
    start_no = 50

    if start_time > market.created_at:
        last_trade_before = Trade.objects.filter(
            market=market,
            executed_at__lt=start_time
        ).order_by('-executed_at').first()

        if last_trade_before:
            # Use the trade price to determine market state
            if last_trade_before.contract_type == 'yes':
                start_yes = last_trade_before.price
                start_no = 100 - last_trade_before.price
            else:
                start_no = last_trade_before.price
                start_yes = 100 - last_trade_before.price

    # Get trades within the window
    trades = Trade.objects.filter(
        market=market,
        executed_at__gte=start_time
    ).order_by('executed_at').values(
        'executed_at', 'price', 'contract_type'
    )

    # Build price history
    price_history = []

    # Add start point
    price_history.append({
        'time': start_time.timestamp() * 1000,
        'yes_price': start_yes,
        'no_price': start_no,
    })

    # Add each trade
    current_yes = start_yes
    current_no = start_no

    for trade in trades:
        # Determine new prices based on trade
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

    # Add current point (now) to ensure line goes to the edge
    price_history.append({
        'time': now.timestamp() * 1000,
        'yes_price': current_yes,
        'no_price': current_no,
    })

    return JsonResponse({
        'market_id': market.pk,
        'price_history': price_history,
        'current_yes': market.last_yes_price,
        'current_no': market.last_no_price,
    })


@login_required
def api_order_preview(request, pk):
    """
    Calculate order preview for confirmation modal.

    POST parameters:
    - action: 'buy' or 'sell'
    - contract_type: 'yes' or 'no'
    - order_type: 'market' or 'limit'
    - amount: dollar amount (for buy) or quantity (for sell) in quick bet
    - price: price in cents (for limit orders only)
    - quantity: number of shares (for limit orders only)

    Returns calculated preview data for the confirmation popup.
    """
    import json

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    market = get_object_or_404(Market, pk=pk)

    # Check if market is active
    if not market.is_trading_active:
        return JsonResponse({'error': 'Market is not active for trading'}, status=400)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    action = data.get('action', 'buy').lower()  # 'buy' or 'sell'
    contract_type = data.get('contract_type', 'yes').lower()  # 'yes' or 'no'
    order_type = data.get('order_type', 'market').lower()  # 'market' or 'limit'

    user = request.user
    user_balance = float(user.available_balance)

    # Get user position for sell validation
    position = Position.objects.filter(user=user, market=market).first()
    user_position = {
        'yes': position.yes_quantity - position.reserved_yes_quantity if position else 0,
        'no': position.no_quantity - position.reserved_no_quantity if position else 0
    }

    result = {
        'user_balance': user_balance,
        'user_position': user_position,
        'current_yes_price': market.last_yes_price,
        'current_no_price': market.last_no_price,
        'warning': None,
    }

    if order_type == 'limit':
        # Limit order: straightforward calculation
        price = int(data.get('price', 50))
        quantity = int(data.get('quantity', 1))

        # Validate price
        if price < 1 or price > 99:
            return JsonResponse({'error': 'Price must be between 1 and 99 cents'}, status=400)

        total = quantity * price / 100  # Convert cents to dollars

        result.update({
            'shares': quantity,
            'avg_price': price,
            'total_cost': total if action == 'buy' else 0,
            'total_proceeds': total if action == 'sell' else 0,
            'potential_payout': quantity,  # $1 per share if wins
            'implied_probability': price,
        })

        # Validation
        if action == 'buy' and total > user_balance:
            result['warning'] = f'Insufficient funds. You have ${user_balance:.2f}'
        elif action == 'sell':
            available = user_position.get(contract_type, 0)
            if quantity > available:
                result['warning'] = f'Insufficient {contract_type.upper()} shares. You have {available}'

    else:
        # Market order: use current market price or walk the orderbook
        amount = float(data.get('amount', 0))

        # Get current orderbook
        orderbook = get_orderbook(market, depth=50)

        if action == 'buy':
            # Get the price we'll buy at (ask side for buying)
            if contract_type == 'yes':
                asks = orderbook.get('yes_asks', [])
                current_price = market.last_yes_price or 50
            else:
                asks = orderbook.get('no_asks', [])
                current_price = market.last_no_price or 50

            if not asks:
                # No asks available, use last price
                price = current_price
                shares = int(amount * 100 / price) if price > 0 else 0
                avg_price = price
            else:
                # Walk through asks to calculate average fill price
                shares, total_spent, avg_price = _calculate_market_buy_fill(asks, amount)

            total_cost = amount

            result.update({
                'shares': shares,
                'avg_price': avg_price,
                'total_cost': total_cost,
                'total_proceeds': 0,
                'potential_payout': shares,  # $1 per share if wins
                'implied_probability': avg_price,
            })

            if amount > user_balance:
                result['warning'] = f'Insufficient funds. You have ${user_balance:.2f}'
            elif shares == 0:
                result['warning'] = 'Amount too small to purchase any shares'

        else:  # sell
            quantity = int(amount)  # For sell, amount is quantity

            # Get bid side of orderbook
            if contract_type == 'yes':
                bids = orderbook.get('yes_bids', [])
                current_price = market.last_yes_price or 50
            else:
                bids = orderbook.get('no_bids', [])
                current_price = market.last_no_price or 50

            if not bids:
                price = current_price
                proceeds = quantity * price / 100
                avg_price = price
            else:
                shares_sold, proceeds, avg_price = _calculate_market_sell_fill(bids, quantity)
                quantity = shares_sold

            result.update({
                'shares': quantity,
                'avg_price': avg_price,
                'total_cost': 0,
                'total_proceeds': proceeds,
                'potential_payout': proceeds,
                'implied_probability': avg_price,
            })

            available = user_position.get(contract_type, 0)
            if quantity > available:
                result['warning'] = f'Insufficient {contract_type.upper()} shares. You have {available}'

    return JsonResponse(result)


def _calculate_market_buy_fill(asks, amount):
    """
    Walk through ask levels to calculate fill for market buy.

    Args:
        asks: List of ask levels [{'price': int, 'quantity': int}, ...]
        amount: Dollar amount to spend

    Returns: (shares, total_spent_dollars, avg_price_cents)
    """
    remaining_budget = amount * 100  # Convert to cents
    shares = 0
    total_cost_cents = 0

    for level in asks:
        price = level['price']
        available = level['quantity']

        # How many can we buy at this level?
        max_shares_at_level = int(remaining_budget / price)
        shares_to_buy = min(max_shares_at_level, available)

        if shares_to_buy > 0:
            cost = shares_to_buy * price
            shares += shares_to_buy
            total_cost_cents += cost
            remaining_budget -= cost

        if remaining_budget < 1:  # Less than 1 cent left
            break

    avg_price = int(total_cost_cents / shares) if shares > 0 else 50
    return shares, total_cost_cents / 100, avg_price


def _calculate_market_sell_fill(bids, quantity):
    """
    Walk through bid levels to calculate fill for market sell.

    Args:
        bids: List of bid levels [{'price': int, 'quantity': int}, ...]
        quantity: Number of shares to sell

    Returns: (shares_sold, proceeds_dollars, avg_price_cents)
    """
    remaining_quantity = quantity
    shares_sold = 0
    total_proceeds_cents = 0

    for level in bids:
        price = level['price']
        available = level['quantity']

        shares_to_sell = min(remaining_quantity, available)

        if shares_to_sell > 0:
            proceeds = shares_to_sell * price
            shares_sold += shares_to_sell
            total_proceeds_cents += proceeds
            remaining_quantity -= shares_to_sell

        if remaining_quantity <= 0:
            break

    avg_price = int(total_proceeds_cents / shares_sold) if shares_sold > 0 else 50
    return shares_sold, total_proceeds_cents / 100, avg_price


@login_required
@require_POST
def api_toggle_ui_mode(request):
    """Toggle user's UI mode preference between easy and advanced."""
    import json

    try:
        data = json.loads(request.body)
        new_mode = data.get('mode', 'easy')

        if new_mode not in ['easy', 'advanced']:
            return JsonResponse({'error': 'Invalid mode'}, status=400)

        preferences, _ = UserPreferences.objects.get_or_create(user=request.user)
        preferences.ui_mode = new_mode
        preferences.save()

        return JsonResponse({
            'success': True,
            'mode': preferences.ui_mode,
            'message': f'Switched to {preferences.get_ui_mode_display()}'
        })
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


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


def market_analysis(request, pk=None):
    """
    Market analysis page for development/testing.
    Shows detailed breakdown of market economics, positions, and settlement scenarios.
    """
    markets = Market.objects.select_related('event').order_by('-id')

    context = {
        'markets': markets,
        'selected_market': None,
        'analysis': None,
    }

    # If a market is selected (via pk or GET param)
    market_id = pk or request.GET.get('market_id')
    if market_id:
        try:
            market = Market.objects.select_related('event').get(id=market_id)
            context['selected_market'] = market

            # Get all trades
            trades = Trade.objects.filter(market=market).select_related('buyer', 'seller')

            # Breakdown by trade type
            trade_breakdown = []
            for tt in ['direct', 'mint', 'merge']:
                t = trades.filter(trade_type=tt)
                if t.exists():
                    total_qty = t.aggregate(Sum('quantity'))['quantity__sum'] or 0
                    total_value = sum(tr.quantity * tr.price for tr in t)
                    trade_breakdown.append({
                        'type': tt.upper(),
                        'count': t.count(),
                        'quantity': total_qty,
                        'value_cents': total_value,
                        'value_dollars': total_value / 100,
                    })

            # Get all positions
            positions = Position.objects.filter(market=market).select_related('user')
            position_details = []
            total_yes = 0
            total_no = 0

            for pos in positions:
                yes_qty = pos.yes_quantity + pos.reserved_yes_quantity
                no_qty = pos.no_quantity + pos.reserved_no_quantity
                if yes_qty > 0 or no_qty > 0:
                    position_details.append({
                        'username': pos.user.username,
                        'yes_qty': yes_qty,
                        'no_qty': no_qty,
                        'total': yes_qty + no_qty,
                    })
                    total_yes += yes_qty
                    total_no += no_qty

            # Sort by total holdings
            position_details.sort(key=lambda x: -x['total'])

            # Transaction analysis
            txns = Transaction.objects.filter(market=market)
            tx_breakdown = []
            tx_types = ['trade_buy', 'trade_sell', 'mint_match', 'merge_match', 'order_reserve', 'order_release']
            for tx_type in tx_types:
                t = txns.filter(type=tx_type)
                if t.exists():
                    total = t.aggregate(Sum('amount'))['amount__sum'] or Decimal(0)
                    tx_breakdown.append({
                        'type': tx_type.upper(),
                        'count': t.count(),
                        'amount': total,
                    })

            # Money flow calculations
            buy_total = abs(txns.filter(type='trade_buy').aggregate(Sum('amount'))['amount__sum'] or Decimal(0))
            mint_total = abs(txns.filter(type='mint_match').aggregate(Sum('amount'))['amount__sum'] or Decimal(0))
            sell_total = txns.filter(type='trade_sell').aggregate(Sum('amount'))['amount__sum'] or Decimal(0)
            merge_total = txns.filter(type='merge_match').aggregate(Sum('amount'))['amount__sum'] or Decimal(0)

            net_locked = buy_total + mint_total - sell_total - merge_total

            # Settlement scenarios
            yes_payout = Decimal(total_yes)
            no_payout = Decimal(total_no)
            admin_profit_yes = net_locked - yes_payout
            admin_profit_no = net_locked - no_payout

            # Recent trades for display
            recent_trades = trades.order_by('-executed_at')[:30]

            context['analysis'] = {
                'trades_count': trades.count(),
                'trade_breakdown': trade_breakdown,
                'positions': position_details,
                'total_yes': total_yes,
                'total_no': total_no,
                'tx_breakdown': tx_breakdown,
                'buy_total': buy_total,
                'mint_total': mint_total,
                'sell_total': sell_total,
                'merge_total': merge_total,
                'net_locked': net_locked,
                'yes_payout': yes_payout,
                'no_payout': no_payout,
                'admin_profit_yes': admin_profit_yes,
                'admin_profit_no': admin_profit_no,
                'recent_trades': recent_trades,
            }

        except Market.DoesNotExist:
            messages.error(request, f'Market {market_id} not found.')

    return render(request, 'predictions/market_analysis.html', context)
