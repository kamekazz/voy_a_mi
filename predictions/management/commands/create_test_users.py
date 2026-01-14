"""
Management command to create test users for testing the token reward system.
"""
from django.core.management.base import BaseCommand
from predictions.models import User, Transaction
from decimal import Decimal


class Command(BaseCommand):
    help = 'Create 10 test users with password tito123456'

    def handle(self, *args, **options):
        password = 'tito123456'
        created_users = []

        for i in range(1, 11):
            username = f'testuser{i}'
            email = f'testuser{i}@test.com'

            # Check if user already exists
            if User.objects.filter(username=username).exists():
                self.stdout.write(
                    self.style.WARNING(f'User {username} already exists. Skipping...')
                )
                continue

            # Create user
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=f'Test',
                last_name=f'User {i}'
            )

            created_users.append(username)

            # Check tokens and transaction
            user.refresh_from_db()
            self.stdout.write(
                self.style.SUCCESS(
                    f'[OK] Created {username} - Tokens: {user.tokens} (Reserved: {user.reserved_tokens})'
                )
            )

            # Show transaction
            reward_transaction = Transaction.objects.filter(
                user=user,
                type=Transaction.Type.EVENT_REWARD
            ).first()

            if reward_transaction:
                self.stdout.write(
                    f'  -> Transaction: {reward_transaction.description}'
                )

        if created_users:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\nSuccessfully created {len(created_users)} test users!'
                )
            )
            self.stdout.write(
                f'\nCredentials for all users:'
            )
            self.stdout.write(f'  Password: {password}')
            self.stdout.write(f'  Users: {", ".join(created_users)}')
        else:
            self.stdout.write(
                self.style.WARNING('No new users created.')
            )
