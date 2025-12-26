from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST
from django.db.models import Q, F, Sum
from django.utils import timezone
from decimal import Decimal, InvalidOperation

from .models import User, Category, Event, Market, Order, Trade, Position, Transaction, UserBalance, AMMTrade
from .forms import UserRegistrationForm
from .forms import OrderForm, QuickOrderForm
from .engine.matching import MatchingEngine, get_orderbook
from .bookmaker_amm import BookmakerAMM, get_bookmaker_prices
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

    # Get AMM prices (live prices from the AMM)
    amm_prices = get_bookmaker_prices(market)

    # Get orderbook (for limit orders)
    orderbook = get_orderbook(market, depth=10)

    # Get recent trades (both AMM and orderbook)
    recent_trades = Trade.objects.filter(market=market).select_related(
        'buyer', 'seller'
    ).order_by('-executed_at')[:20]

    # Get AMM trades for this market
    from .models import AMMTrade
    try:
        amm_trades = AMMTrade.objects.filter(
            pool__market=market
        ).select_related('user').order_by('-executed_at')[:20]
    except:
        amm_trades = []

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
        'amm_prices': amm_prices,
        'orderbook': orderbook,
        'recent_trades': recent_trades,
        'amm_trades': amm_trades,
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
            price_val = Decimal(price)
        except:
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
    """Place a quick bet (buy or sell) using the AMM - Polymarket style.

    Buy: User specifies dollar amount and contract type (YES/NO).
    Sell: User specifies number of shares to sell.
    AMM provides instant execution with smooth price movement.
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
        # Use Bookmaker AMM for instant execution with vig
        amm = BookmakerAMM(market)

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

            # Execute the sell
            trade = amm.sell(request.user, contract_type, quantity)

            # Get the new price after trade
            yes_price, no_price = amm.get_display_prices()
            new_price = yes_price if contract_type == 'yes' else no_price

            messages.success(
                request,
                f"Sold {quantity} {contract_type.upper()} shares "
                f"at avg {float(trade.avg_price):.1f}c for ${float(trade.total_cost):.2f}. "
                f"New price: {new_price}c"
            )

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

            # Calculate how many shares the amount buys
            quantity = amm.calculate_shares_for_amount(contract_type, amount)

            if quantity < 1:
                messages.error(request, f"Amount too small to buy any shares.")
                return redirect('predictions:market_detail', market_id=pk)

            # Execute the buy
            trade = amm.buy(request.user, contract_type, quantity)

            # Get the new price after trade
            yes_price, no_price = amm.get_display_prices()
            new_price = yes_price if contract_type == 'yes' else no_price

            messages.success(
                request,
                f"Bought {quantity} {contract_type.upper()} shares "
                f"at avg {float(trade.avg_price):.1f}c for ${float(trade.total_cost):.2f}. "
                f"New price: {new_price}c. Potential payout: ${quantity:.2f}"
            )

    except InsufficientFundsError as e:
        messages.error(request, str(e))
    except MarketNotActiveError as e:
        messages.error(request, str(e))
    except TradingError as e:
        messages.error(request, f"Trading error: {e}")

    return redirect('predictions:market_detail', market_id=pk)


@login_required
@require_POST
def place_hybrid_bet(request, pk):
    """
    Hybrid bet: Fill what AMM can handle instantly, queue the rest as a limit order.

    For BUY orders:
    - Part gets filled instantly via AMM
    - Remainder becomes a pending limit order
    - User can cancel the pending portion anytime

    For SELL orders:
    - Just uses AMM directly (selling shares you own)
    """
    market = get_object_or_404(Market, pk=pk)
    action = request.POST.get('action', 'buy')
    contract_type = request.POST.get('contract_type')

    if contract_type not in ['yes', 'no']:
        messages.error(request, "Please select YES or NO.")
        return redirect('predictions:market_detail', market_id=pk)

    try:
        amm = BookmakerAMM(market)

        # SELL: Just use AMM directly
        if action == 'sell':
            try:
                quantity = int(request.POST.get('amount', '0'))
            except (ValueError, TypeError):
                messages.error(request, "Invalid quantity.")
                return redirect('predictions:market_detail', market_id=pk)

            if quantity <= 0:
                messages.error(request, "Quantity must be at least 1 share.")
                return redirect('predictions:market_detail', market_id=pk)

            trade = amm.sell(request.user, contract_type, quantity)
            yes_price, no_price = amm.get_display_prices()
            new_price = yes_price if contract_type == 'yes' else no_price

            messages.success(
                request,
                f"Sold {quantity} {contract_type.upper()} shares "
                f"at avg {float(trade.avg_price):.1f}c for ${float(trade.total_cost):.2f}. "
                f"New price: {new_price}c"
            )
            return redirect('predictions:market_detail', market_id=pk)

        # BUY: Hybrid system (AMM + Order Book)
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

        # Calculate total shares requested
        total_quantity = amm.calculate_shares_for_amount(contract_type, amount)
        if total_quantity < 1:
            messages.error(request, "Amount too small to buy any shares.")
            return redirect('predictions:market_detail', market_id=pk)

        # Calculate how much AMM can fill
        max_amm_qty = amm.max_fillable_quantity(contract_type)
        amm_quantity = min(total_quantity, max_amm_qty)

        amm_trade = None
        pending_order = None
        amm_cost = Decimal('0')

        # Step 1: Fill what AMM can handle
        if amm_quantity > 0:
            amm_trade = amm.buy(request.user, contract_type, amm_quantity)
            amm_cost = amm_trade.total_cost

        # Step 2: Create limit order for remainder
        remaining_quantity = total_quantity - amm_quantity
        if remaining_quantity > 0:
            # Use current fair price for the limit order
            yes_price, no_price = amm.get_display_prices()
            order_price = yes_price if contract_type == 'yes' else no_price

            # Create limit order via matching engine
            engine = MatchingEngine(market)
            pending_order, trades = engine.place_order(
                user=request.user,
                side='buy',
                contract_type=contract_type,
                price=order_price,
                quantity=remaining_quantity
            )

        # Build success message
        if amm_trade and pending_order:
            # Both: partial AMM fill + pending order
            messages.success(
                request,
                f"Filled {amm_quantity} {contract_type.upper()} shares instantly for ${float(amm_cost):.2f}. "
                f"Pending: {remaining_quantity} shares @ {order_price}c (cancel anytime in Orders)."
            )
        elif amm_trade:
            # Full AMM fill
            yes_price, no_price = amm.get_display_prices()
            new_price = yes_price if contract_type == 'yes' else no_price
            messages.success(
                request,
                f"Bought {amm_quantity} {contract_type.upper()} shares "
                f"at avg {float(amm_trade.avg_price):.1f}c for ${float(amm_cost):.2f}. "
                f"New price: {new_price}c"
            )
        elif pending_order:
            # AMM at capacity, all goes to order book
            yes_price, no_price = amm.get_display_prices()
            order_price = yes_price if contract_type == 'yes' else no_price
            messages.info(
                request,
                f"AMM at capacity. Created limit order for {remaining_quantity} {contract_type.upper()} @ {order_price}c. "
                f"Will fill when someone bets the other side."
            )

    except InsufficientFundsError as e:
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
    """Get recent trades for a market (both Order Book and AMM trades) as JSON."""
    market = get_object_or_404(Market, pk=pk)
    
    # 1. Fetch Order Book Trades
    ob_trades = Trade.objects.filter(market=market).order_by('-executed_at')[:50]
    
    # 2. Fetch AMM Trades (if pool exists)
    amm_trades = []
    if hasattr(market, 'amm_pool'):
        amm_trades = AMMTrade.objects.filter(pool=market.amm_pool).order_by('-executed_at')[:50]
    
    # 3. Combine and normalize
    combined_trades = []
    
    for t in ob_trades:
        combined_trades.append({
            'id': f"ob-{t.id}",
            'contract_type': t.contract_type,
            'price': t.price, # already in cents
            'avg_price': t.price, 
            'quantity': t.quantity,
            'side': 'buy', # simplified for display, or derivation needed? 
            # Trade model doesn't store 'side' directly on the trade itself as clearly as AMMTrade
            # It has buyer/seller. 
            # Usually we show the 'taker' side or just color code green/red?
            # Polymarket shows 'Buy' or 'Sell' depending on the aggressor.
            # For simplicity, we can default to 'Buy' if not easily determining aggressor, 
            # BUT wait, the `Trade` model has trade_type.
            # Let's assume 'buy' for now or infer?
            # Actually, `Trade` implies a match. 
            # Let's check the Trade model in models.py again.
            # It has `buyer` and `seller`. It doesn't say who was the taker.
            # For the purpose of the feed, usually 'Buy' is Green (YES) or Red (NO)?
            # Wait, AMMTrade HAS 'side'.
            # Let's verify standard behavior.
            # Use 'buy' for simplicity as it's a match.
            'executed_at': t.executed_at,
            'source': 'book'
        })
        
    for t in amm_trades:
        combined_trades.append({
            'id': f"amm-{t.id}",
            'contract_type': t.contract_type,
            'price': float(t.avg_price), # Decimal to float
            'avg_price': float(t.avg_price),
            'quantity': t.quantity,
            'side': t.side, # 'buy' or 'sell'
            'executed_at': t.executed_at,
            'source': 'amm'
        })
        
    # 4. Sort and Slice
    combined_trades.sort(key=lambda x: x['executed_at'], reverse=True)
    recent = combined_trades[:50]
    
    # 5. Serialization for JSON
    serialized = []
    for t in recent:
        serialized.append({
            'id': t['id'],
            'contract_type': t['contract_type'],
            'avg_price': t['avg_price'],
            'quantity': t['quantity'],
            'side': t.get('side', 'buy'),
            'executed_at': t['executed_at'].isoformat(),
            'source': t['source']
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
    """Get price history from AMM trades for charting."""
    from .models import AMMTrade
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

    # Determine starting price
    # 1. If start_time is market creation, it's 50/50
    # 2. Otherwise, find the last trade BEFORE cutoff to get the opening state
    start_yes = 50
    start_no = 50

    if start_time > market.created_at: # We are looking at a window (e.g. last 24h) of an older market
        last_trade_before = AMMTrade.objects.filter(
            pool__market=market,
            executed_at__lt=start_time
        ).order_by('-executed_at').first()

        if last_trade_before:
            if last_trade_before.contract_type == 'yes':
                start_yes = last_trade_before.price_after
                start_no = 100 - last_trade_before.price_after
            else:
                start_no = last_trade_before.price_after
                start_yes = 100 - last_trade_before.price_after

    # Get trades within the window
    trades = AMMTrade.objects.filter(
        pool__market=market,
        executed_at__gte=start_time
    ).order_by('executed_at').values(
        'executed_at', 'price_after', 'contract_type'
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
        # Determine new prices
        if trade['contract_type'] == 'yes':
            p_yes = trade['price_after']
            p_no = 100 - trade['price_after']
        else:
            p_no = trade['price_after']
            p_yes = 100 - trade['price_after']
        
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
        'yes_price': current_yes, # Use tracked current in loop to be consistent with history
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
