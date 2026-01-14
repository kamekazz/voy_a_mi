# Generated migration to rename balance fields to token fields

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('predictions', '0014_remove_userbalance'),
    ]

    operations = [
        # Rename User model fields
        migrations.RenameField(
            model_name='user',
            old_name='balance',
            new_name='tokens',
        ),
        migrations.RenameField(
            model_name='user',
            old_name='reserved_balance',
            new_name='reserved_tokens',
        ),

        # Rename Transaction model fields
        migrations.RenameField(
            model_name='transaction',
            old_name='balance_before',
            new_name='tokens_before',
        ),
        migrations.RenameField(
            model_name='transaction',
            old_name='balance_after',
            new_name='tokens_after',
        ),
    ]
