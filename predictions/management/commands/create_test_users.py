"""
Management command to create test users for the prediction market.
"""
from django.core.management.base import BaseCommand
from predictions.models import User
from decimal import Decimal
import os


class Command(BaseCommand):
    help = 'Creates 20 test users and saves credentials to TEST_USERS.md'

    def handle(self, *args, **options):
        # Test user data
        users_data = [
            ('carlos_trader', 'Carlos', 'Martinez'),
            ('maria_bets', 'Maria', 'Rodriguez'),
            ('john_predictor', 'John', 'Smith'),
            ('ana_markets', 'Ana', 'Garcia'),
            ('mike_odds', 'Mike', 'Johnson'),
            ('sofia_wins', 'Sofia', 'Lopez'),
            ('david_picks', 'David', 'Williams'),
            ('laura_trade', 'Laura', 'Brown'),
            ('james_bet', 'James', 'Jones'),
            ('elena_market', 'Elena', 'Davis'),
            ('robert_pred', 'Robert', 'Miller'),
            ('carmen_wins', 'Carmen', 'Wilson'),
            ('alex_trader', 'Alex', 'Moore'),
            ('isabel_bets', 'Isabel', 'Taylor'),
            ('chris_odds', 'Chris', 'Anderson'),
            ('lucia_picks', 'Lucia', 'Thomas'),
            ('daniel_trade', 'Daniel', 'Jackson'),
            ('paula_bet', 'Paula', 'White'),
            ('kevin_market', 'Kevin', 'Harris'),
            ('rosa_pred', 'Rosa', 'Martin'),
        ]

        password = 'TestPass123!'
        starting_balance = Decimal('1000.00')
        created_users = []

        self.stdout.write('Creating 20 test users...\n')

        for username, first_name, last_name in users_data:
            email = f'{username}@testmail.com'

            # Check if user already exists
            if User.objects.filter(username=username).exists():
                self.stdout.write(f'  User {username} already exists, skipping...')
                user = User.objects.get(username=username)
            else:
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                    balance=starting_balance,
                )
                self.stdout.write(self.style.SUCCESS(f'  Created user: {username}'))

            created_users.append({
                'username': username,
                'email': email,
                'password': password,
                'first_name': first_name,
                'last_name': last_name,
            })

        # Write credentials to markdown file
        md_content = """# Test Users

These are test accounts for the Voy a Mi prediction market platform.

## Credentials

| # | Username | Email | Password | Name |
|---|----------|-------|----------|------|
"""
        for i, user in enumerate(created_users, 1):
            md_content += f"| {i} | {user['username']} | {user['email']} | {user['password']} | {user['first_name']} {user['last_name']} |\n"

        md_content += """
## Notes

- All users have a starting balance of **$1,000.00**
- Password for all accounts: `TestPass123!`
- Email domain `@testmail.com` is for testing only

## Quick Login

For quick testing, use any of these accounts:
- **carlos_trader** / TestPass123!
- **maria_bets** / TestPass123!
- **john_predictor** / TestPass123!
"""

        # Get the project root directory
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        md_path = os.path.join(base_dir, 'TEST_USERS.md')

        with open(md_path, 'w') as f:
            f.write(md_content)

        self.stdout.write(self.style.SUCCESS(f'\nCredentials saved to: {md_path}'))
        self.stdout.write(self.style.SUCCESS('Done! 20 test users are ready.'))
