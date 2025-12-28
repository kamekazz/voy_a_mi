from django.core.management.base import BaseCommand
from predictions.models import Market, Order, Trade, Position, Transaction
from django.db.models import Sum
from decimal import Decimal

class Command(BaseCommand):
    help = 'Analyze a market for settlement breakdown'

    def add_arguments(self, parser):
        parser.add_argument('market_id', type=int, help='Market ID to analyze')

    def handle(self, *args, **options):
        market_id = options['market_id']
        market = Market.objects.get(id=market_id)

        self.stdout.write('='*60)
        self.stdout.write(f'MARKET #{market.id}: {market.title}')
        self.stdout.write(f'Event: {market.event.title}')
        self.stdout.write(f'Status: {market.status}')
        self.stdout.write(f'Current YES Price: {market.last_yes_price}c | NO Price: {market.last_no_price}c')
        self.stdout.write('='*60)

        # Get all trades
        trades = Trade.objects.filter(market=market)
        self.stdout.write(f'\nTOTAL TRADES: {trades.count()}')

        # Breakdown by trade type (lowercase values in DB)
        for tt in ['direct', 'mint', 'merge']:
            t = trades.filter(trade_type=tt)
            if t.exists():
                total_qty = t.aggregate(Sum('quantity'))['quantity__sum'] or 0
                total_value = sum(tr.quantity * tr.price for tr in t)
                self.stdout.write(f'  {tt.upper()}: {t.count()} trades, {total_qty} shares, value={total_value}c')

        # Get all positions
        positions = Position.objects.filter(market=market)
        self.stdout.write(f'\nALL POSITIONS:')
        total_yes = 0
        total_no = 0
        position_details = []
        for pos in positions:
            yes_qty = pos.yes_quantity + pos.reserved_yes_quantity
            no_qty = pos.no_quantity + pos.reserved_no_quantity
            if yes_qty > 0 or no_qty > 0:
                position_details.append((pos.user.username, yes_qty, no_qty))
                total_yes += yes_qty
                total_no += no_qty

        for user, yes, no in sorted(position_details, key=lambda x: -(x[1]+x[2])):
            self.stdout.write(f'  {user}: YES={yes}, NO={no}')

        self.stdout.write(f'\nTOTAL OUTSTANDING SHARES: YES={total_yes}, NO={total_no}')

        # Transactions analysis (uses 'type' field, lowercase values)
        txns = Transaction.objects.filter(market=market)
        self.stdout.write('\nTransactions by type:')
        tx_types = ['trade_buy', 'trade_sell', 'mint_match', 'merge_match', 'order_reserve', 'order_release']
        for tx_type in tx_types:
            t = txns.filter(type=tx_type)
            if t.exists():
                total = t.aggregate(Sum('amount'))['amount__sum'] or Decimal(0)
                self.stdout.write(f'  {tx_type.upper()}: {t.count()} txns, ${total:.2f}')

        # Settlement scenarios
        self.stdout.write('\n' + '='*60)
        self.stdout.write('SETTLEMENT SCENARIOS')
        self.stdout.write('='*60)

        # Each share pays out $1 (100 cents) if it wins
        self.stdout.write('\nIF YES WINS:')
        self.stdout.write(f'  YES holders get $1 per share: {total_yes} shares = ${total_yes:.2f}')
        self.stdout.write(f'  NO holders get $0: {total_no} shares = $0.00')

        self.stdout.write('\nIF NO WINS:')
        self.stdout.write(f'  NO holders get $1 per share: {total_no} shares = ${total_no:.2f}')
        self.stdout.write(f'  YES holders get $0: {total_yes} shares = $0.00')

        # Settlement by user
        self.stdout.write('\n' + '='*60)
        self.stdout.write('SETTLEMENT BREAKDOWN BY USER')
        self.stdout.write('='*60)

        self.stdout.write('\nIF YES WINS:')
        for user, yes, no in sorted(position_details, key=lambda x: -x[1]):
            self.stdout.write(f'  {user}: {yes} YES shares -> ${yes:.2f} payout')

        self.stdout.write('\nIF NO WINS:')
        for user, yes, no in sorted(position_details, key=lambda x: -x[2]):
            self.stdout.write(f'  {user}: {no} NO shares -> ${no:.2f} payout')

        # Money in system
        self.stdout.write('\n' + '='*60)
        self.stdout.write('TOTAL MONEY IN SYSTEM')
        self.stdout.write('='*60)

        buy_txns = txns.filter(type='trade_buy')
        total_bought = buy_txns.aggregate(Sum('amount'))['amount__sum'] or Decimal(0)
        self.stdout.write(f'Total from TRADE_BUY: ${abs(total_bought):.2f}')

        mint_txns = txns.filter(type='mint_match')
        total_mint = mint_txns.aggregate(Sum('amount'))['amount__sum'] or Decimal(0)
        self.stdout.write(f'Total from MINT_MATCH: ${abs(total_mint):.2f}')

        sell_txns = txns.filter(type='trade_sell')
        total_sold = sell_txns.aggregate(Sum('amount'))['amount__sum'] or Decimal(0)
        self.stdout.write(f'Total from TRADE_SELL: ${total_sold:.2f}')

        merge_txns = txns.filter(type='merge_match')
        total_merge = merge_txns.aggregate(Sum('amount'))['amount__sum'] or Decimal(0)
        self.stdout.write(f'Total from MERGE_MATCH: ${total_merge:.2f}')

        net_in = abs(total_bought) + abs(total_mint) - total_sold - total_merge
        self.stdout.write(f'\nNet money currently locked in market: ${net_in:.2f}')

        # Admin analysis
        self.stdout.write('\n' + '='*60)
        self.stdout.write('ADMIN/HOUSE ANALYSIS')
        self.stdout.write('='*60)

        # Each share pays $1 on settlement
        if total_yes > 0:
            yes_payout = Decimal(total_yes)
            self.stdout.write(f'If YES wins, payout: ${yes_payout:.2f}')
            self.stdout.write(f'  Admin profit/loss if YES: ${net_in - yes_payout:.2f}')

        if total_no > 0:
            no_payout = Decimal(total_no)
            self.stdout.write(f'If NO wins, payout: ${no_payout:.2f}')
            self.stdout.write(f'  Admin profit/loss if NO: ${net_in - no_payout:.2f}')

        # Trade history (uses executed_at and contract_type)
        self.stdout.write('\n' + '='*60)
        self.stdout.write('TRADE HISTORY DETAIL')
        self.stdout.write('='*60)
        for trade in trades.order_by('executed_at')[:30]:
            self.stdout.write(f'{trade.executed_at.strftime("%m/%d %H:%M")} | {trade.trade_type:6} | {trade.contract_type:3} | {trade.quantity}@{trade.price}c | buyer:{trade.buyer.username[:10]:10} seller:{trade.seller.username[:10]:10}')

        if trades.count() > 30:
            self.stdout.write(f'... and {trades.count() - 30} more trades')
