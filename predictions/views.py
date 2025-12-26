from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST
from django.db.models import Q, F, Sum
from django.utils import timezone
from decimal import Decimal, InvalidOperation

from .models import User, Category, Event, Market, Order, Trade, Position, Transaction
from .forms import UserRegistrationForm
from .forms import OrderForm, QuickOrderForm
from .matching_engine import MatchingEngine, get_orderbook
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


def market_detail(request, pk):
    """Market detail page with orderbook and trading interface."""
    market = get_object_or_404(
        Market.objects.select_related('event', 'event__category'),
        pk=pk
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
    return render(request, 'predictions/market_detail.html', context)

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

    try:
        # Use Order Book matching engine
        engine = MatchingEngine(market)
        order, trades = engine.place_order(
            user=request.user,
            side=side,
            contract_type=contract_type,
            price=price,
            quantity=quantity,
            order_type='limit'
        )

        if trades:
            total_filled = sum(t.quantity for t in trades)
            messages.success(
                request,
                f"Order executed! {len(trades)} trade(s), "
                f"{total_filled} contracts filled @ {order.price}c."
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
        return redirect('predictions:market_detail', pk=pk)

    try:
        # Use Bookmaker AMM for instant execution with vig
        amm = BookmakerAMM(market)

        if action == 'sell':
            # SELL: User enters number of shares to sell
            try:
                quantity = int(request.POST.get('amount', '0'))
            except (ValueError, TypeError):
                messages.error(request, "Invalid quantity.")
                return redirect('predictions:market_detail', pk=pk)

            if quantity <= 0:
                messages.error(request, "Quantity must be at least 1 share.")
                return redirect('predictions:market_detail', pk=pk)

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
                return redirect('predictions:market_detail', pk=pk)

            if amount <= 0:
                messages.error(request, "Amount must be greater than $0.")
                return redirect('predictions:market_detail', pk=pk)

            if amount > request.user.available_balance:
                messages.error(request, f"Insufficient balance. You have ${request.user.available_balance:.2f} available.")
                return redirect('predictions:market_detail', pk=pk)

            # Calculate how many shares the amount buys
            quantity = amm.calculate_shares_for_amount(contract_type, amount)

            if quantity < 1:
                messages.error(request, f"Amount too small to buy any shares.")
                return redirect('predictions:market_detail', pk=pk)

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

    return redirect('predictions:market_detail', pk=pk)


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
        return redirect('predictions:market_detail', pk=pk)

    try:
        amm = BookmakerAMM(market)

        # SELL: Just use AMM directly
        if action == 'sell':
            try:
                quantity = int(request.POST.get('amount', '0'))
            except (ValueError, TypeError):
                messages.error(request, "Invalid quantity.")
                return redirect('predictions:market_detail', pk=pk)

            if quantity <= 0:
                messages.error(request, "Quantity must be at least 1 share.")
                return redirect('predictions:market_detail', pk=pk)

            trade = amm.sell(request.user, contract_type, quantity)
            yes_price, no_price = amm.get_display_prices()
            new_price = yes_price if contract_type == 'yes' else no_price

            messages.success(
                request,
                f"Sold {quantity} {contract_type.upper()} shares "
                f"at avg {float(trade.avg_price):.1f}c for ${float(trade.total_cost):.2f}. "
                f"New price: {new_price}c"
            )
            return redirect('predictions:market_detail', pk=pk)

        # BUY: Hybrid system (AMM + Order Book)
        try:
            amount = Decimal(request.POST.get('amount', '0'))
        except (ValueError, TypeError, InvalidOperation):
            messages.error(request, "Invalid amount.")
            return redirect('predictions:market_detail', pk=pk)

        if amount <= 0:
            messages.error(request, "Amount must be greater than $0.")
            return redirect('predictions:market_detail', pk=pk)

        if amount > request.user.available_balance:
            messages.error(request, f"Insufficient balance. You have ${request.user.available_balance:.2f} available.")
            return redirect('predictions:market_detail', pk=pk)

        # Calculate total shares requested
        total_quantity = amm.calculate_shares_for_amount(contract_type, amount)
        if total_quantity < 1:
            messages.error(request, "Amount too small to buy any shares.")
            return redirect('predictions:market_detail', pk=pk)

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

    return redirect('predictions:market_detail', pk=pk)


@login_required
@require_POST
def cancel_order(request, pk):
    """Cancel an open order."""
    order = get_object_or_404(Order, pk=pk)
    market_pk = order.market.pk

    engine = MatchingEngine(order.market)
def cancel_order(request, order_id):
    order = get_object_or_404(Order, pk=order_id, user=request.user)
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
            position.reserved_yes_shares -= order.quantity
            position.yes_shares += order.quantity
        else:
            position.reserved_no_shares -= order.quantity
            position.no_shares += order.quantity
        position.save()

    order.delete()
    return redirect('market_detail', market_id=market.id)


def match_orders(market_id):
    market = Market.objects.get(pk=market_id)
    matches = True
    while matches:
        matches = False
        
        # 1. Direct Matching
        for outcome in ['YES', 'NO']:
            buy_orders = Order.objects.filter(market=market, order_type='BUY', outcome=outcome).order_by('-price', 'created_at')
            sell_orders = Order.objects.filter(market=market, order_type='SELL', outcome=outcome).order_by('price', 'created_at')

            if buy_orders.exists() and sell_orders.exists():
                best_buy = buy_orders.first()
                best_sell = sell_orders.first()
                
                # Market order (price=None) or Limit match
                buy_price = best_buy.price if best_buy.price is not None else Decimal('1.00')
                sell_price = best_sell.price if best_sell.price is not None else Decimal('0.00')
                
                if buy_price >= sell_price:
                    quantity = min(best_buy.quantity, best_sell.quantity)
                    
                    # Match at Maker's price (Earliest order)
                    if best_buy.created_at < best_sell.created_at:
                        price = buy_price
                    else:
                        price = sell_price
                    
                    matches = True
                    execute_direct_trade(best_buy, best_sell, quantity, price)
                    continue

        # 2. Minting (Buy YES + Buy NO)
        buy_yes = Order.objects.filter(market=market, order_type='BUY', outcome='YES').order_by('-price', 'created_at')
        buy_no = Order.objects.filter(market=market, order_type='BUY', outcome='NO').order_by('-price', 'created_at')
        
        if buy_yes.exists() and buy_no.exists():
            best_yes = buy_yes.first()
            best_no = buy_no.first()
            
            p_yes = best_yes.price if best_yes.price is not None else Decimal('1.00')
            p_no = best_no.price if best_no.price is not None else Decimal('1.00')
            
            if p_yes + p_no >= Decimal('1.00'):
                matches = True
                quantity = min(best_yes.quantity, best_no.quantity)
                execute_mint(best_yes, best_no, quantity)
                continue

        # 3. Merging (Sell YES + Sell NO)
        sell_yes = Order.objects.filter(market=market, order_type='SELL', outcome='YES').order_by('price', 'created_at')
        sell_no = Order.objects.filter(market=market, order_type='SELL', outcome='NO').order_by('price', 'created_at')
        
        if sell_yes.exists() and sell_no.exists():
            s_yes = sell_yes.first()
            s_no = sell_no.first()
            
            p_yes = s_yes.price if s_yes.price is not None else Decimal('0.00')
            p_no = s_no.price if s_no.price is not None else Decimal('0.00')
            
            if p_yes + p_no <= Decimal('1.00'):
                matches = True
                quantity = min(s_yes.quantity, s_no.quantity)
                execute_merge(s_yes, s_no, quantity)
                continue

def execute_direct_trade(buy_order, sell_order, quantity, price):
    # Buyer pays 'price'. Refund diff if reserved > price.
    buyer_bal = UserBalance.objects.get(user=buy_order.user)
    buyer_pos, _ = Position.objects.get_or_create(user=buy_order.user, market=buy_order.market)
    seller_bal = UserBalance.objects.get(user=sell_order.user)
    seller_pos, _ = Position.objects.get_or_create(user=sell_order.user, market=sell_order.market)
    
    cost = price * quantity
    reserved_cost = (buy_order.price if buy_order.price is not None else Decimal('1.00')) * quantity
    
    # Buyer updates
    buyer_bal.reserved_balance -= reserved_cost
    buyer_bal.balance += (reserved_cost - cost) # Refund difference
    buyer_bal.save()
    if buy_order.outcome == 'YES': buyer_pos.yes_shares += quantity
    else: buyer_pos.no_shares += quantity
    buyer_pos.save()
    
    # Seller updates
    seller_bal.balance += cost
    seller_bal.save()
    if sell_order.outcome == 'YES': seller_pos.reserved_yes_shares -= quantity
    else: seller_pos.reserved_no_shares -= quantity
    seller_pos.save()
    
    # Update Orders
    update_order(buy_order, quantity)
    update_order(sell_order, quantity)
    
    # Log
    Transaction.objects.create(
        user=buy_order.user, 
        market=buy_order.market, 
        amount=-cost, 
        description=f"Bought {quantity} {buy_order.outcome} @ {price}"
    )
    Transaction.objects.create(
        user=sell_order.user, 
        market=sell_order.market, 
        amount=cost, 
        description=f"Sold {quantity} {sell_order.outcome} @ {price}"
    )

def execute_mint(buy_yes, buy_no, quantity):
    # Both buyers pay their limit price (or we can split $1). 
    # Logic: Pay Bid. System keeps excess if Sum > 1.
    cost_yes = (buy_yes.price if buy_yes.price is not None else Decimal('0.50')) * quantity
    cost_no = (buy_no.price if buy_no.price is not None else Decimal('0.50')) * quantity
    # If Market Order, price is None. We assumed 1.00 reserved.
    # If both market, we can charge 0.50 each or 1.00 total.
    # Logic above uses price or 1.00. If 1.00, user pays 1.00?
    # Actually if Mint happens, we essentially fill them.
    # If we charge them their max willingness, it's safe.
    
    res_yes = (buy_yes.price if buy_yes.price is not None else Decimal('1.00')) * quantity
    res_no = (buy_no.price if buy_no.price is not None else Decimal('1.00')) * quantity
    
    # Buyer YES
    b_yes_bal = UserBalance.objects.get(user=buy_yes.user)
    b_yes_pos, _ = Position.objects.get_or_create(user=buy_yes.user, market=buy_yes.market)
    b_yes_bal.reserved_balance -= res_yes
    b_yes_bal.balance += (res_yes - cost_yes) 
    b_yes_bal.save()
    b_yes_pos.yes_shares += quantity
    b_yes_pos.save()
    
    # Buyer NO
    b_no_bal = UserBalance.objects.get(user=buy_no.user)
    b_no_pos, _ = Position.objects.get_or_create(user=buy_no.user, market=buy_no.market)
    b_no_bal.reserved_balance -= res_no
    b_no_bal.balance += (res_no - cost_no)
    b_no_bal.save()
    b_no_pos.no_shares += quantity
    b_no_pos.save()
    
    update_order(buy_yes, quantity)
    update_order(buy_no, quantity)
    
    Transaction.objects.create(user=buy_yes.user, market=buy_yes.market, amount=-cost_yes, description=f"Minted/Bought YES {quantity}")
    Transaction.objects.create(user=buy_no.user, market=buy_no.market, amount=-cost_no, description=f"Minted/Bought NO {quantity}")

def execute_merge(sell_yes, sell_no, quantity):
    # Release $1.00 * quantity.
    # Pay sellers their ask.
    pay_yes = (sell_yes.price if sell_yes.price is not None else Decimal('0.50')) * quantity
    pay_no = (sell_no.price if sell_no.price is not None else Decimal('0.50')) * quantity
    
    # Seller YES
    s_yes_bal = UserBalance.objects.get(user=sell_yes.user)
    s_yes_pos, _ = Position.objects.get_or_create(user=sell_yes.user, market=sell_yes.market)
    s_yes_bal.balance += pay_yes
    s_yes_bal.save()
    s_yes_pos.reserved_yes_shares -= quantity
    s_yes_pos.save()
    
    # Seller NO
    s_no_bal = UserBalance.objects.get(user=sell_no.user)
    s_no_pos, _ = Position.objects.get_or_create(user=sell_no.user, market=sell_no.market)
    s_no_bal.balance += pay_no
    s_no_bal.save()
    s_no_pos.reserved_no_shares -= quantity
    s_no_pos.save()
    
    update_order(sell_yes, quantity)
    update_order(sell_no, quantity)
    
    Transaction.objects.create(user=sell_yes.user, market=sell_yes.market, amount=pay_yes, description=f"Merged/Sold YES {quantity}")
    Transaction.objects.create(user=sell_no.user, market=sell_no.market, amount=pay_no, description=f"Merged/Sold NO {quantity}")

def update_order(order, quantity):
    if order.quantity > quantity:
        order.quantity -= quantity
        order.save()
    else:
        order.delete()


@login_required
@require_POST
def mint_complete_set_view(request, pk):
    """Mint complete sets of YES+NO contracts."""
    from .matching_engine import mint_complete_set

    market = get_object_or_404(Market, pk=pk)

    try:
        quantity = int(request.POST.get('quantity', 0))
    except (ValueError, TypeError):
        messages.error(request, "Invalid quantity.")
        return redirect('predictions:market_detail', pk=pk)

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

    return redirect('predictions:market_detail', pk=pk)


@login_required
@require_POST
def redeem_complete_set_view(request, pk):
    """Redeem complete sets for $1 each."""
    from .matching_engine import redeem_complete_set

    market = get_object_or_404(Market, pk=pk)

    try:
        quantity = int(request.POST.get('quantity', 0))
    except (ValueError, TypeError):
        messages.error(request, "Invalid quantity.")
        return redirect('predictions:market_detail', pk=pk)

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

    return redirect('predictions:market_detail', pk=pk)


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


def api_price_history(request, pk):
    """Get price history from AMM trades for charting."""
    from .models import AMMTrade
    from datetime import timedelta

    market = get_object_or_404(Market, pk=pk)

    # Parse timeframe parameter
    timeframe = request.GET.get('timeframe', '24h')
    now = timezone.now()

    if timeframe == '1h':
        since = now - timedelta(hours=1)
    elif timeframe == '24h':
        since = now - timedelta(hours=24)
    elif timeframe == '7d':
        since = now - timedelta(days=7)
    else:  # 'all'
        since = None

    # Get AMM trades ordered by time
    queryset = AMMTrade.objects.filter(pool__market=market)
    if since:
        queryset = queryset.filter(executed_at__gte=since)

    trades = queryset.order_by('executed_at').values(
        'executed_at', 'price_after', 'contract_type', 'side'
    )

    # Build price history
    price_history = []

    # Add initial price point (50/50)
    if trades:
        first_trade = trades[0]
        price_history.append({
            'time': (first_trade['executed_at'].timestamp() - 1) * 1000,  # 1 second before first trade
            'yes_price': 50,
            'no_price': 50,
        })

    # Add each trade's resulting price
    for trade in trades:
        yes_price = trade['price_after']
        no_price = 100 - trade['price_after']

        # If this was a NO trade, the price_after is for NO, so flip it
        if trade['contract_type'] == 'no':
            no_price = trade['price_after']
            yes_price = 100 - trade['price_after']

        price_history.append({
            'time': trade['executed_at'].timestamp() * 1000,  # JavaScript timestamp
            'yes_price': yes_price,
            'no_price': no_price,
        })

    # Add current price as final point
    price_history.append({
        'time': timezone.now().timestamp() * 1000,
        'yes_price': market.last_yes_price,
        'no_price': market.last_no_price,
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
