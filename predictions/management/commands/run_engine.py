import time
import signal
import sys
from datetime import datetime
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from predictions.models import Order, Market, Position, Transaction, User
from predictions.engine.matching import MatchingEngine
from predictions.broadcasts import broadcast_market_update, broadcast_orderbook_update


class Command(BaseCommand):
    help = 'Runs the matching engine - SINGLE source of truth for ALL trading operations.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('='*60))
        self.stdout.write(self.style.SUCCESS('  MATCHING ENGINE - Single Source of Truth'))
        self.stdout.write(self.style.SUCCESS('='*60))
        self.stdout.write('')
        self.stdout.write('Processing:')
        self.stdout.write('  - Limit orders (price specified)')
        self.stdout.write('  - Market orders (best available price)')
        self.stdout.write('  - Mint requests (create YES+NO pairs)')
        self.stdout.write('  - Redeem requests (burn YES+NO pairs)')
        self.stdout.write('')

        # Handle graceful shutdown
        def signal_handler(sig, frame):
            self.stdout.write(self.style.WARNING('\nStopping Matching Engine...'))
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        loop_count = 0
        last_status_time = time.time()
        status_interval = 10  # Print status every 10 seconds

        while True:
            try:
                loop_count += 1

                # Process all order types
                trades_count = self._process_trading_orders()
                mint_count = self._process_mint_requests()
                redeem_count = self._process_redeem_requests()

                # Print status periodically
                current_time = time.time()
                if current_time - last_status_time >= status_interval:
                    timestamp = datetime.now().strftime('%H:%M:%S')

                    # Count open orders by type
                    open_trading = Order.objects.filter(
                        market__status=Market.Status.ACTIVE,
                        status__in=[Order.Status.OPEN, Order.Status.PARTIALLY_FILLED],
                        order_type__in=['limit', 'market']
                    ).count()

                    open_mint = Order.objects.filter(
                        market__status=Market.Status.ACTIVE,
                        status=Order.Status.OPEN,
                        order_type='mint_set'
                    ).count()

                    open_redeem = Order.objects.filter(
                        market__status=Market.Status.ACTIVE,
                        status=Order.Status.OPEN,
                        order_type='redeem_set'
                    ).count()

                    total = open_trading + open_mint + open_redeem

                    if total > 0:
                        self.stdout.write(
                            f"[{timestamp}] Pending: {open_trading} orders, "
                            f"{open_mint} mints, {open_redeem} redeems"
                        )
                    else:
                        self.stdout.write(f"[{timestamp}] Engine running - no pending requests")

                    last_status_time = current_time

                time.sleep(0.5)

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error in engine loop: {e}"))
                import traceback
                traceback.print_exc()
                time.sleep(1)

    def _process_trading_orders(self):
        """Process limit and market orders - matching logic."""
        trades_count = 0
        active_markets = Market.objects.filter(status=Market.Status.ACTIVE)

        for market in active_markets:
            # Get orders that need matching (exclude mint/redeem special types)
            open_orders = Order.objects.filter(
                market=market,
                status__in=[Order.Status.OPEN, Order.Status.PARTIALLY_FILLED],
                order_type__in=['limit', 'market']
            ).order_by('created_at')

            if open_orders.exists():
                engine = MatchingEngine(market)

                for order in open_orders:
                    # For market orders without price, determine from orderbook
                    if order.order_type == 'market' and order.price is None:
                        price = engine._get_market_price(order.side, order.contract_type)
                        if price:
                            order.price = Decimal(price) / 100  # Convert cents to dollars
                            order.save()
                        else:
                            # No counterparty available, skip for now
                            continue

                    trades = engine._match_order(order)
                    if trades:
                        trades_count += len(trades)
                        self.stdout.write(self.style.SUCCESS(
                            f"  MATCHED {len(trades)} trade(s) for Order #{order.id} "
                            f"({order.side} {order.contract_type.upper()})"
                        ))

        return trades_count

    @transaction.atomic
    def _process_mint_requests(self):
        """Process mint complete set requests."""
        count = 0
        mint_requests = Order.objects.filter(
            order_type='mint_set',
            status=Order.Status.OPEN,
            market__status=Market.Status.ACTIVE
        ).select_for_update()

        for request in mint_requests:
            try:
                market = request.market
                user = User.objects.select_for_update().get(pk=request.user_id)
                quantity = request.quantity
                cost = Decimal(quantity)  # $1 per set

                # Release reserved funds (already deducted from balance during view)
                user.reserved_balance -= cost
                user.save()

                # Create/update position
                position, _ = Position.objects.get_or_create(user=user, market=market)

                # Add contracts at 50c cost basis each
                old_yes = position.yes_quantity
                old_no = position.no_quantity

                if old_yes > 0:
                    position.yes_avg_cost = (
                        (position.yes_avg_cost * old_yes + Decimal('50.00') * quantity) /
                        (old_yes + quantity)
                    )
                else:
                    position.yes_avg_cost = Decimal('50.00')
                position.yes_quantity += quantity

                if old_no > 0:
                    position.no_avg_cost = (
                        (position.no_avg_cost * old_no + Decimal('50.00') * quantity) /
                        (old_no + quantity)
                    )
                else:
                    position.no_avg_cost = Decimal('50.00')
                position.no_quantity += quantity
                position.save()

                # Update market shares outstanding
                market.total_shares_outstanding += quantity
                market.save()

                # Create transaction record
                Transaction.objects.create(
                    user=user,
                    type=Transaction.Type.MINT,
                    amount=-cost,
                    balance_before=user.balance + cost,
                    balance_after=user.balance,
                    market=market,
                    order=request,
                    description=f"Minted {quantity} complete sets (YES+NO) @ $1/set"
                )

                # Mark request as filled
                request.status = Order.Status.FILLED
                request.filled_quantity = quantity
                request.save()

                count += 1
                self.stdout.write(self.style.SUCCESS(
                    f"  MINTED {quantity} complete sets for {user.username} in {market.title}"
                ))

                # Broadcast update
                try:
                    broadcast_market_update(market)
                except Exception:
                    pass  # Don't fail if broadcast fails

            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f"  Error processing mint request #{request.id}: {e}"
                ))

        return count

    @transaction.atomic
    def _process_redeem_requests(self):
        """Process redeem complete set requests."""
        count = 0
        redeem_requests = Order.objects.filter(
            order_type='redeem_set',
            status=Order.Status.OPEN,
            market__status=Market.Status.ACTIVE
        ).select_for_update()

        for request in redeem_requests:
            try:
                market = request.market
                user = User.objects.select_for_update().get(pk=request.user_id)
                quantity = request.quantity
                payout = Decimal(quantity)  # $1 per set

                # Get position and release reserved shares (burn them)
                position = Position.objects.select_for_update().get(user=user, market=market)

                # Calculate realized P&L before burning
                yes_pnl = Decimal(quantity) * (Decimal('50') - position.yes_avg_cost) / 100
                no_pnl = Decimal(quantity) * (Decimal('50') - position.no_avg_cost) / 100

                # Burn reserved shares (they were moved to reserved during view)
                position.reserved_yes_quantity -= quantity
                position.reserved_no_quantity -= quantity
                position.realized_pnl += yes_pnl + no_pnl
                position.save()

                # Credit user with payout
                user.balance += payout
                user.save()

                # Update market shares outstanding
                market.total_shares_outstanding -= quantity
                market.save()

                # Create transaction record
                Transaction.objects.create(
                    user=user,
                    type=Transaction.Type.REDEEM,
                    amount=payout,
                    balance_before=user.balance - payout,
                    balance_after=user.balance,
                    market=market,
                    order=request,
                    description=f"Redeemed {quantity} complete sets (YES+NO) @ $1/set"
                )

                # Mark request as filled
                request.status = Order.Status.FILLED
                request.filled_quantity = quantity
                request.save()

                count += 1
                self.stdout.write(self.style.SUCCESS(
                    f"  REDEEMED {quantity} complete sets for {user.username} in {market.title}"
                ))

                # Broadcast update
                try:
                    broadcast_market_update(market)
                except Exception:
                    pass  # Don't fail if broadcast fails

            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f"  Error processing redeem request #{request.id}: {e}"
                ))

        return count
