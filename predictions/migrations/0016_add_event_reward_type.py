# Generated migration to add EVENT_REWARD transaction type

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('predictions', '0015_rename_balance_to_tokens'),
    ]

    operations = [
        migrations.AlterField(
            model_name='transaction',
            name='type',
            field=models.CharField(
                choices=[
                    ('deposit', 'Deposit'),
                    ('withdrawal', 'Withdrawal'),
                    ('trade_buy', 'Trade (Buy)'),
                    ('trade_sell', 'Trade (Sell)'),
                    ('settlement_win', 'Settlement (Win)'),
                    ('settlement_loss', 'Settlement (Loss)'),
                    ('order_reserve', 'Order Reserve'),
                    ('order_release', 'Order Release'),
                    ('refund', 'Refund'),
                    ('mint', 'Mint (Create Complete Set)'),
                    ('redeem', 'Redeem (Burn Complete Set)'),
                    ('mint_match', 'Mint via Order Match'),
                    ('merge_match', 'Merge via Order Match'),
                    ('transaction_fee', 'Transaction Fee'),
                    ('event_reward', 'Event Reward'),
                ],
                max_length=20
            ),
        ),
    ]
