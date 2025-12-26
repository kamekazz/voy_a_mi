import time
import signal
import sys
from datetime import datetime
from django.core.management.base import BaseCommand
from django.db import transaction
from predictions.models import Order, Market
from predictions.engine.matching import MatchingEngine

class Command(BaseCommand):
    help = 'Runs the matching engine to process open orders continuously.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting Matching Engine...'))
        self.stdout.write('Note: This engine only processes LIMIT ORDERS in the order book.')
        self.stdout.write('Quick Bets use the AMM and are processed instantly without this engine.')
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

                active_markets = Market.objects.filter(status=Market.Status.ACTIVE)
                total_open_orders = Order.objects.filter(
                    market__status=Market.Status.ACTIVE,
                    status__in=[Order.Status.OPEN, Order.Status.PARTIALLY_FILLED]
                ).count()

                processed_count = 0

                for market in active_markets:
                    open_orders = Order.objects.filter(
                        market=market,
                        status__in=[Order.Status.OPEN, Order.Status.PARTIALLY_FILLED]
                    ).order_by('created_at')

                    if open_orders.exists():
                        engine = MatchingEngine(market)

                        for order in open_orders:
                            trades = engine._match_order(order)
                            if trades:
                                processed_count += len(trades)
                                self.stdout.write(self.style.SUCCESS(
                                    f"  MATCHED {len(trades)} trade(s) for Order #{order.id} "
                                    f"({order.side} {order.contract_type.upper()} @ {order.price}c)"
                                ))

                # Print status periodically
                current_time = time.time()
                if current_time - last_status_time >= status_interval:
                    timestamp = datetime.now().strftime('%H:%M:%S')
                    if total_open_orders > 0:
                        self.stdout.write(f"[{timestamp}] Scanning {active_markets.count()} markets, "
                                        f"{total_open_orders} open limit order(s) in book")
                    else:
                        self.stdout.write(f"[{timestamp}] Engine running - no limit orders in book")
                    last_status_time = current_time

                if processed_count > 0:
                    self.stdout.write(self.style.SUCCESS(f"Processed {processed_count} trades total"))

                time.sleep(0.5)

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error in engine loop: {e}"))
                time.sleep(1)
