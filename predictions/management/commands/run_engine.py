import time
import signal
import sys
from django.core.management.base import BaseCommand
from django.db import transaction
from predictions.models import Order, Market
from predictions.engine.matching import MatchingEngine

class Command(BaseCommand):
    help = 'Runs the matching engine to process open orders continuously.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting Matching Engine...'))
        
        # Handle graceful shutdown
        def signal_handler(sig, frame):
            self.stdout.write(self.style.WARNING('\nStopping Matching Engine...'))
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        while True:
            try:
                # Find orders that need processing
                # We prioritize oldest orders first to respect time priority
                # We process OPEN and PARTIALLY_FILLED orders
                # Optimization: We could have a 'needs_matching' flag or queue
                # For now, we iterate active markets and their open orders
                
                active_markets = Market.objects.filter(status=Market.Status.ACTIVE)
                
                processed_count = 0
                
                for market in active_markets:
                    # Find orders that might match
                    # Ideally, we trigger on new orders. simpler: poll all open orders?
                    # Polling all open orders every loop is expensive if there are many resting orders.
                    # But for a demo/MVP, it functions.
                    # BETTER: Only process orders that are "aggressors" (newly placed).
                    # But since we decoupled, subsequent orders in book are resting.
                    # If we iterate ALL open orders, we treat everyone as potentially aggressive.
                    # This ensures crosses are cleared.
                    
                    open_orders = Order.objects.filter(
                        market=market,
                        status__in=[Order.Status.OPEN, Order.Status.PARTIALLY_FILLED]
                    ).order_by('created_at')
                    
                    engine = MatchingEngine(market)
                    
                    for order in open_orders:
                        # Attempt to match this order against others
                        # logical cycle: treat this order as incoming
                        trades = engine._match_order(order)
                        if trades:
                            processed_count += len(trades)
                            self.stdout.write(f"  Matched {len(trades)} trades for Order #{order.id}")

                if processed_count == 0:
                    time.sleep(0.5) # Sleep if no activity to save CPU
                else:
                     self.stdout.write(self.style.SUCCESS(f"Processed {processed_count} trades"))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error in engine loop: {e}"))
                time.sleep(1)
