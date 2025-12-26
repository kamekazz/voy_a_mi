from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST
from django.db.models import Q, F, Sum
from django.utils import timezone
from decimal import Decimal, InvalidOperation

from .models import User, Category, Event, Market, Order, Trade, Position, Transaction, UserBalance
from .forms import UserRegistrationForm
from .forms import OrderForm, QuickOrderForm
from .engine.matching import MatchingEngine, get_orderbook
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
    """Place a new order on a market (Order Book only)."""
    market = get_object_or_404(Market, pk=pk)

    order_type = request.POST.get('order_type')
    outcome_input = request.POST.get('outcome')
    if not outcome_input:
         return HttpResponse("Missing outcome")
    contract_type = outcome_input.lower()
    
    price = request.POST.get('price')
    quantity = int(request.POST.get('quantity'))

    # Handle Market Orders (empty price)
    if not price:
        price_val = None
    else:
        try:
            price_cents = int(price)
            # Validate price range (1-99 cents)
            if price_cents < 1 or price_cents > 99:
                messages.error(request, "Price must be between 1 and 99 cents")
                return redirect('predictions:market_detail', market_id=market.id)
            # Convert cents to dollars for storage
            price_val = Decimal(price_cents) / 100
        except (ValueError, TypeError):
             return HttpResponse("Invalid price")

    user_balance, _ = UserBalance.objects.get_or_create(user=request.user)
    position, _ = Position.objects.get_or_create(user=request.user, market=market)

    if order_type == 'BUY':
        # Calculate reservation amount
        # If Market Order, reserve max possible price ($1.00) to be safe
        reservation_price = price_val if price_val is not None else Decimal('1.00')
        total_cost = reservation_price * quantity
        
        if user_balance.balance >= total_cost:
            user_balance.balance -= total_cost
            user_balance.reserved_balance += total_cost
            user_balance.save()
        else:
            messages.error(request, "Insufficient funds")
            return redirect('predictions:market_detail', market_id=market.id)
            
    elif order_type == 'SELL':
        if contract_type == 'yes':
            if position.yes_quantity >= quantity:
                position.yes_quantity -= quantity
                position.reserved_yes_quantity += quantity
                position.save()
            else:
                messages.error(request, "Insufficient YES shares")
                return redirect('predictions:market_detail', market_id=market.id)
        else: # NO
            if position.no_quantity >= quantity:
                position.no_quantity -= quantity
                position.reserved_no_quantity += quantity
                position.save()
            else:
                messages.error(request, "Insufficient NO shares")
                return redirect('predictions:market_detail', market_id=market.id)

    # Determine actual order type (LIMIT/MARKET) based on price presence
    actual_order_type = 'market' if price_val is None else 'limit'
    side = order_type.lower() # 'buy' or 'sell'

    Order.objects.create(
        user=request.user,
        market=market,
        side=side,
        contract_type=contract_type,
        order_type=actual_order_type,
        price=price_val,
        quantity=quantity
    )
    

    
    messages.success(request, "Order placed successfully.")
    return redirect('predictions:market_detail', market_id=market.id)

@login_required
@require_POST
def place_quick_bet(request, pk):
    """Place a quick bet using market orders through the order book.

    Buy: User specifies dollar amount and contract type (YES/NO).
    Sell: User specifies number of shares to sell.
    Uses market orders for best available execution.
    """
    market = get_object_or_404(Market, pk=pk)

    # Parse parameters
    action = request.POST.get('action', 'buy')  # 'buy' or 'sell'
    contract_type = request.POST.get('contract_type')

    # Validate contract type
    if contract_type not in ['yes', 'no']:
        messages.error(request, "Please select YES or NO.")
        return redirect('predictions:market_detail', market_id=pk)

    try:
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

            # Place market sell order
            order, trades = engine.place_order(
                user=request.user,
                side='sell',
                contract_type=contract_type,
                price=None,  # Market order
                quantity=quantity
            )

            if trades:
                total_value = sum(t.quantity * t.price for t in trades) / 100
                total_qty = sum(t.quantity for t in trades)
                avg_price = sum(t.quantity * t.price for t in trades) / total_qty if total_qty > 0 else 0
                messages.success(
                    request,
                    f"Sold {total_qty} {contract_type.upper()} shares at avg {avg_price:.1f}c "
                    f"for ${total_value:.2f}"
                )
            else:
                messages.info(request, f"Sell order placed. Waiting for buyers.")

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

            if amount > request.user.available_balance:
                messages.error(request, f"Insufficient balance. You have ${request.user.available_balance:.2f} available.")
                return redirect('predictions:market_detail', market_id=pk)

            # Calculate approximate quantity based on current price
            current_price = market.last_yes_price if contract_type == 'yes' else market.last_no_price
            if current_price <= 0:
                current_price = 50  # Default to 50c
            quantity = int(amount * 100 / current_price)

            if quantity < 1:
                messages.error(request, f"Amount too small to buy any shares.")
                return redirect('predictions:market_detail', market_id=pk)

            # Place market buy order
            order, trades = engine.place_order(
                user=request.user,
                side='buy',
                contract_type=contract_type,
                price=None,  # Market order
                quantity=quantity
            )

            if trades:
                total_value = sum(t.quantity * t.price for t in trades) / 100
                total_qty = sum(t.quantity for t in trades)
                avg_price = sum(t.quantity * t.price for t in trades) / total_qty if total_qty > 0 else 0
                messages.success(
                    request,
                    f"Bought {total_qty} {contract_type.upper()} shares at avg {avg_price:.1f}c "
                    f"for ${total_value:.2f}. Potential payout: ${total_qty:.2f}"
                )
            else:
                messages.info(request, f"Buy order placed. Waiting for sellers.")

    except InsufficientFundsError as e:
        messages.error(request, str(e))
    except InsufficientPositionError as e:
        messages.error(request, str(e))
    except MarketNotActiveError as e:
        messages.error(request, str(e))
    except TradingError as e:
        messages.error(request, f"Trading error: {e}")

    return redirect('predictions:market_detail', market_id=pk)


@login_required
@require_POST
def cancel_order(request, pk):
    """Cancel an order and refund reserved funds/shares."""
    # Note: Using 'pk' to match URL pattern, but function logic used order_id
    # I will unify this.
    order = get_object_or_404(Order, pk=pk, user=request.user)
    market = order.market
    
    # Reverse Reservation
    user_balance = UserBalance.objects.get(user=request.user)
    position = Position.objects.get(user=request.user, market=market)

    if order.order_type == 'BUY':
        # Refund reserved funds
        refund_price = order.price if order.price is not None else Decimal('1.00')
        refund_amount = refund_price * order.quantity
        
        user_balance.reserved_balance -= refund_amount
        user_balance.balance += refund_amount
        user_balance.save()
        
    elif order.order_type == 'SELL':
        if order.outcome == 'YES':
            position.reserved_yes_quantity -= order.quantity
            position.yes_quantity += order.quantity
        else:
            position.reserved_no_quantity -= order.quantity
            position.no_quantity += order.quantity
        position.save()

    order.delete()
    return redirect('market_detail', market_id=market.id)





@login_required
@require_POST
def mint_complete_set_view(request, pk):
    """Mint complete sets of YES+NO contracts."""
    from .engine.matching import mint_complete_set

    market = get_object_or_404(Market, pk=pk)

    try:
        quantity = int(request.POST.get('quantity', 0))
    except (ValueError, TypeError):
        messages.error(request, "Invalid quantity.")
        return redirect('predictions:market_detail', market_id=pk)

    try:
        result = mint_complete_set(market, request.user, quantity)
        messages.success(
            request,
            f"Minted {result['quantity']} complete sets. "
            f"Received {result['yes_received']} YES + {result['no_received']} NO contracts. "
            f"Cost: ${result['cost']:.2f}"
        )
    except InsufficientFundsError as e:
        messages.error(request, str(e))
    except MarketNotActiveError as e:
        messages.error(request, str(e))
    except TradingError as e:
        messages.error(request, f"Error: {e}")

    return redirect('predictions:market_detail', market_id=pk)


@login_required
@require_POST
def redeem_complete_set_view(request, pk):
    """Redeem complete sets for $1 each."""
    from .engine.matching import redeem_complete_set

    market = get_object_or_404(Market, pk=pk)

    try:
        quantity = int(request.POST.get('quantity', 0))
    except (ValueError, TypeError):
        messages.error(request, "Invalid quantity.")
        return redirect('predictions:market_detail', market_id=pk)

    try:
        result = redeem_complete_set(market, request.user, quantity)
        messages.success(
            request,
            f"Redeemed {result['quantity']} complete sets. "
            f"Burned {result['yes_burned']} YES + {result['no_burned']} NO contracts. "
            f"Received: ${result['payout']:.2f}"
        )
    except InsufficientPositionError as e:
        messages.error(request, str(e))
    except MarketNotActiveError as e:
        messages.error(request, str(e))
    except TradingError as e:
        messages.error(request, f"Error: {e}")

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
            'quantity': t.quantity,
            'trade_type': t.trade_type,  # direct, mint, or merge
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
