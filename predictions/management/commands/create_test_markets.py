"""
Management command to create test events and markets for the prediction market.
Creates ~20 events with ~40 markets across all categories with images from Unsplash.
"""
import os
import requests
from io import BytesIO
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from django.utils import timezone
from django.utils.text import slugify

from predictions.models import User, Category, Event, Market, AMMPool


class Command(BaseCommand):
    help = 'Creates test events and markets with images for all categories'

    def download_image(self, keyword, size="800x600"):
        """Download a random image from Lorem Picsum (reliable free service)."""
        # Parse size
        width, height = size.split('x')
        # Use Lorem Picsum - reliable free image service
        # Add random seed based on keyword for consistency
        seed = hash(keyword) % 1000
        url = f"https://picsum.photos/seed/{seed}/{width}/{height}"
        try:
            response = requests.get(url, timeout=15, allow_redirects=True)
            if response.status_code == 200:
                return response.content
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"    Could not download image: {e}"))
        return None

    def get_or_create_admin(self):
        """Get the first superuser or create one."""
        admin = User.objects.filter(is_superuser=True).first()
        if not admin:
            admin = User.objects.create_superuser(
                username='admin',
                email='admin@example.com',
                password='AdminPass123!'
            )
            self.stdout.write(self.style.SUCCESS('  Created admin user'))
        return admin

    def handle(self, *args, **options):
        self.stdout.write('\n' + '='*60)
        self.stdout.write('Creating Test Events and Markets')
        self.stdout.write('='*60 + '\n')

        # Get admin user for created_by
        admin = self.get_or_create_admin()

        # Ensure all categories exist
        categories_data = [
            ('Politics', 'politics', '🚨', 1),
            ('Sports', 'sports', '🏈', 2),
            ('Finance', 'finance', '💰', 3),
            ('Geopolitics', 'geopolitics', '🌎', 4),
            ('Music', 'music', '🎵', 5),
            ('Culture', 'culture', '🧫', 6),
        ]

        categories = {}
        for name, slug, icon, order in categories_data:
            cat, created = Category.objects.get_or_create(
                slug=slug,
                defaults={'name': name, 'icon': icon, 'display_order': order}
            )
            categories[slug] = cat
            if created:
                self.stdout.write(f'  Created category: {name}')

        # Define all events and markets
        now = timezone.now()

        events_data = [
            # POLITICS (4 events, 8 markets)
            {
                'title': '2026 Congressional Elections',
                'slug': '2026-congressional-elections',
                'description': 'Predictions on the 2026 US midterm elections for the House and Senate.',
                'category': 'politics',
                'resolution_source': 'Official election results from state election boards',
                'trading_ends': now + timedelta(days=700),  # Nov 2026
                'image_keyword': 'us congress capitol',
                'markets': [
                    {'title': 'Will Democrats win the House in 2026?', 'slug': 'democrats-win-house-2026'},
                    {'title': 'Will Republicans gain 5+ Senate seats in 2026?', 'slug': 'republicans-gain-5-senate-2026'},
                ]
            },
            {
                'title': '2025 State Elections',
                'slug': '2025-state-elections',
                'description': 'Key state-level elections and ballot initiatives in 2025.',
                'category': 'politics',
                'resolution_source': 'State election boards and Secretary of State offices',
                'trading_ends': now + timedelta(days=365),  # Dec 2025
                'image_keyword': 'state capitol government',
                'markets': [
                    {'title': 'Will California hold a gubernatorial recall in 2025?', 'slug': 'california-recall-2025'},
                    {'title': 'Will Florida pass recreational marijuana in 2025?', 'slug': 'florida-marijuana-2025'},
                ]
            },
            {
                'title': 'Presidential Approval Ratings 2025',
                'slug': 'presidential-approval-2025',
                'description': 'Tracking presidential approval and third-party polling in 2025.',
                'category': 'politics',
                'resolution_source': 'FiveThirtyEight polling averages',
                'trading_ends': now + timedelta(days=180),  # Jun 2025
                'image_keyword': 'white house washington',
                'markets': [
                    {'title': 'Will Biden\'s approval reach 50% in 2025?', 'slug': 'biden-approval-50-2025'},
                    {'title': 'Will any third-party candidate poll above 15%?', 'slug': 'third-party-15-percent'},
                ]
            },
            {
                'title': 'Supreme Court 2025',
                'slug': 'supreme-court-2025',
                'description': 'Predictions on Supreme Court retirements and major decisions.',
                'category': 'politics',
                'resolution_source': 'Official Supreme Court announcements',
                'trading_ends': now + timedelta(days=365),  # Dec 2025
                'image_keyword': 'supreme court building',
                'markets': [
                    {'title': 'Will a Supreme Court justice retire in 2025?', 'slug': 'scotus-retirement-2025'},
                    {'title': 'Will the court overturn a major precedent in 2025?', 'slug': 'scotus-overturn-precedent'},
                ]
            },

            # SPORTS (4 events, 8 markets)
            {
                'title': 'Super Bowl LX (2026)',
                'slug': 'super-bowl-lx-2026',
                'description': 'Predictions on Super Bowl LX outcomes and game statistics.',
                'category': 'sports',
                'resolution_source': 'Official NFL game results',
                'trading_ends': now + timedelta(days=420),  # Feb 2026
                'image_keyword': 'super bowl football stadium',
                'markets': [
                    {'title': 'Will the Kansas City Chiefs win Super Bowl LX?', 'slug': 'chiefs-win-super-bowl-lx'},
                    {'title': 'Will Super Bowl LX go to overtime?', 'slug': 'super-bowl-lx-overtime'},
                ]
            },
            {
                'title': 'FIFA World Cup 2026',
                'slug': 'fifa-world-cup-2026',
                'description': 'Predictions on the 2026 FIFA World Cup hosted by USA, Canada, and Mexico.',
                'category': 'sports',
                'resolution_source': 'Official FIFA match results',
                'trading_ends': now + timedelta(days=560),  # Jul 2026
                'image_keyword': 'soccer world cup stadium',
                'markets': [
                    {'title': 'Will Argentina win the 2026 World Cup?', 'slug': 'argentina-win-world-cup-2026'},
                    {'title': 'Will USA reach the World Cup semifinals?', 'slug': 'usa-world-cup-semifinals'},
                ]
            },
            {
                'title': 'NBA 2025-26 Season',
                'slug': 'nba-2025-26-season',
                'description': 'Predictions on the 2025-26 NBA season outcomes.',
                'category': 'sports',
                'resolution_source': 'Official NBA statistics and results',
                'trading_ends': now + timedelta(days=540),  # Jun 2026
                'image_keyword': 'nba basketball court',
                'markets': [
                    {'title': 'Will the Lakers win the 2026 NBA Championship?', 'slug': 'lakers-nba-championship-2026'},
                    {'title': 'Will Victor Wembanyama win NBA MVP?', 'slug': 'wembanyama-mvp-2026'},
                ]
            },
            {
                'title': 'MLB 2025 Season',
                'slug': 'mlb-2025-season',
                'description': 'Predictions on the 2025 Major League Baseball season.',
                'category': 'sports',
                'resolution_source': 'Official MLB statistics and results',
                'trading_ends': now + timedelta(days=300),  # Oct 2025
                'image_keyword': 'baseball stadium mlb',
                'markets': [
                    {'title': 'Will the Yankees win the 2025 World Series?', 'slug': 'yankees-world-series-2025'},
                    {'title': 'Will Shohei Ohtani hit 50+ home runs in 2025?', 'slug': 'ohtani-50-homers-2025'},
                ]
            },

            # FINANCE (3 events, 7 markets)
            {
                'title': 'Bitcoin & Crypto 2025',
                'slug': 'bitcoin-crypto-2025',
                'description': 'Predictions on cryptocurrency prices and market dynamics in 2025.',
                'category': 'finance',
                'resolution_source': 'CoinMarketCap daily closing prices',
                'trading_ends': now + timedelta(days=365),  # Dec 2025
                'image_keyword': 'bitcoin cryptocurrency',
                'markets': [
                    {'title': 'Will Bitcoin reach $150,000 in 2025?', 'slug': 'bitcoin-150k-2025'},
                    {'title': 'Will Bitcoin fall below $50,000 in 2025?', 'slug': 'bitcoin-below-50k-2025'},
                    {'title': 'Will Ethereum flip Bitcoin in market cap?', 'slug': 'ethereum-flip-bitcoin'},
                ]
            },
            {
                'title': 'Stock Market 2025',
                'slug': 'stock-market-2025',
                'description': 'Predictions on major stock market indices and individual stocks.',
                'category': 'finance',
                'resolution_source': 'Official stock exchange closing prices',
                'trading_ends': now + timedelta(days=365),  # Dec 2025
                'image_keyword': 'stock market trading',
                'markets': [
                    {'title': 'Will S&P 500 reach 6,500 by December 2025?', 'slug': 'sp500-6500-2025'},
                    {'title': 'Will Tesla stock double from January 2025 price?', 'slug': 'tesla-double-2025'},
                ]
            },
            {
                'title': 'Tech IPOs 2025',
                'slug': 'tech-ipos-2025',
                'description': 'Predictions on major technology company IPOs in 2025.',
                'category': 'finance',
                'resolution_source': 'SEC filings and stock exchange listings',
                'trading_ends': now + timedelta(days=365),  # Dec 2025
                'image_keyword': 'ipo stock market bell',
                'markets': [
                    {'title': 'Will OpenAI go public in 2025?', 'slug': 'openai-ipo-2025'},
                    {'title': 'Will Stripe IPO in 2025?', 'slug': 'stripe-ipo-2025'},
                ]
            },

            # GEOPOLITICS (3 events, 6 markets)
            {
                'title': 'Ukraine-Russia Conflict',
                'slug': 'ukraine-russia-conflict-2025',
                'description': 'Predictions on the ongoing conflict between Ukraine and Russia.',
                'category': 'geopolitics',
                'resolution_source': 'Major news agencies (Reuters, AP, AFP)',
                'trading_ends': now + timedelta(days=365),  # Dec 2025
                'image_keyword': 'ukraine flag peace',
                'markets': [
                    {'title': 'Will there be a ceasefire agreement by end of 2025?', 'slug': 'ukraine-ceasefire-2025'},
                    {'title': 'Will Ukraine reclaim Crimea by 2026?', 'slug': 'ukraine-reclaim-crimea'},
                ]
            },
            {
                'title': 'China-Taiwan Relations',
                'slug': 'china-taiwan-relations-2025',
                'description': 'Predictions on cross-strait relations and international responses.',
                'category': 'geopolitics',
                'resolution_source': 'Official government statements and major news agencies',
                'trading_ends': now + timedelta(days=365),  # Dec 2025
                'image_keyword': 'taiwan strait asia',
                'markets': [
                    {'title': 'Will China impose new sanctions on Taiwan in 2025?', 'slug': 'china-taiwan-sanctions-2025'},
                    {'title': 'Will US send troops to Taiwan in 2025?', 'slug': 'us-troops-taiwan-2025'},
                ]
            },
            {
                'title': 'Middle East 2025',
                'slug': 'middle-east-2025',
                'description': 'Predictions on Middle East conflicts and diplomatic developments.',
                'category': 'geopolitics',
                'resolution_source': 'UN announcements and major news agencies',
                'trading_ends': now + timedelta(days=365),  # Dec 2025
                'image_keyword': 'middle east diplomacy peace',
                'markets': [
                    {'title': 'Will Israel-Gaza achieve a lasting ceasefire in 2025?', 'slug': 'israel-gaza-ceasefire-2025'},
                    {'title': 'Will Saudi Arabia normalize relations with Israel?', 'slug': 'saudi-israel-normalization'},
                ]
            },

            # MUSIC (3 events, 5 markets)
            {
                'title': 'Grammy Awards 2026',
                'slug': 'grammy-awards-2026',
                'description': 'Predictions on the 68th Grammy Awards ceremony.',
                'category': 'music',
                'resolution_source': 'Official Grammy Awards results',
                'trading_ends': now + timedelta(days=420),  # Feb 2026
                'image_keyword': 'grammy award music',
                'markets': [
                    {'title': 'Will Taylor Swift win Album of the Year at 2026 Grammys?', 'slug': 'taylor-swift-aoty-2026'},
                    {'title': 'Will a K-pop artist win a major Grammy in 2026?', 'slug': 'kpop-grammy-2026'},
                ]
            },
            {
                'title': 'Concert Tours 2025',
                'slug': 'concert-tours-2025',
                'description': 'Predictions on major concert tour announcements and sales.',
                'category': 'music',
                'resolution_source': 'Official artist announcements and Ticketmaster data',
                'trading_ends': now + timedelta(days=365),  # Dec 2025
                'image_keyword': 'concert stadium crowd',
                'markets': [
                    {'title': 'Will Beyonce announce a world tour in 2025?', 'slug': 'beyonce-tour-2025'},
                    {'title': 'Will a stadium concert sell out in under 1 minute?', 'slug': 'concert-sellout-1-minute'},
                ]
            },
            {
                'title': 'Music Streaming Wars 2025',
                'slug': 'music-streaming-2025',
                'description': 'Predictions on music streaming platform growth and competition.',
                'category': 'music',
                'resolution_source': 'Official company earnings reports',
                'trading_ends': now + timedelta(days=365),  # Dec 2025
                'image_keyword': 'music streaming headphones',
                'markets': [
                    {'title': 'Will Spotify reach 300M paid subscribers by end of 2025?', 'slug': 'spotify-300m-subscribers'},
                ]
            },

            # CULTURE (3 events, 6 markets)
            {
                'title': 'Oscars 2026',
                'slug': 'oscars-2026',
                'description': 'Predictions on the 98th Academy Awards ceremony.',
                'category': 'culture',
                'resolution_source': 'Official Academy Awards results',
                'trading_ends': now + timedelta(days=450),  # Mar 2026
                'image_keyword': 'oscar award hollywood',
                'markets': [
                    {'title': 'Will a streaming film win Best Picture at 2026 Oscars?', 'slug': 'streaming-best-picture-2026'},
                    {'title': 'Will an AI-assisted film be nominated for an Oscar?', 'slug': 'ai-film-oscar-nomination'},
                ]
            },
            {
                'title': 'Social Media 2025',
                'slug': 'social-media-2025',
                'description': 'Predictions on social media platform developments and regulations.',
                'category': 'culture',
                'resolution_source': 'Official company statements and government announcements',
                'trading_ends': now + timedelta(days=365),  # Dec 2025
                'image_keyword': 'social media phone apps',
                'markets': [
                    {'title': 'Will TikTok be banned in the US in 2025?', 'slug': 'tiktok-ban-us-2025'},
                    {'title': 'Will Threads overtake Twitter/X in active users?', 'slug': 'threads-overtake-twitter'},
                ]
            },
            {
                'title': 'AI & Technology 2025',
                'slug': 'ai-technology-2025',
                'description': 'Predictions on artificial intelligence developments and adoption.',
                'category': 'culture',
                'resolution_source': 'Official company announcements and verified reports',
                'trading_ends': now + timedelta(days=365),  # Dec 2025
                'image_keyword': 'artificial intelligence robot',
                'markets': [
                    {'title': 'Will ChatGPT reach 500M weekly active users?', 'slug': 'chatgpt-500m-users'},
                    {'title': 'Will an AI pass the bar exam with top 1% score?', 'slug': 'ai-bar-exam-top-1-percent'},
                ]
            },
        ]

        events_created = 0
        markets_created = 0

        for event_data in events_data:
            event_slug = event_data['slug']

            # Check if event already exists
            if Event.objects.filter(slug=event_slug).exists():
                self.stdout.write(f'  Event "{event_data["title"]}" already exists, skipping...')
                continue

            self.stdout.write(f'\nCreating event: {event_data["title"]}')

            # Download event image
            image_content = self.download_image(event_data['image_keyword'])
            thumbnail_content = self.download_image(event_data['image_keyword'], "400x300")

            # Create the event
            event = Event(
                title=event_data['title'],
                slug=event_slug,
                description=event_data['description'],
                event_type=Event.EventType.BINARY,
                category=categories[event_data['category']],
                resolution_source=event_data['resolution_source'],
                trading_starts=now,
                trading_ends=event_data['trading_ends'],
                status=Event.Status.ACTIVE,
                created_by=admin,
            )

            # Save images if downloaded
            if image_content:
                event.image.save(f'{event_slug}.jpg', ContentFile(image_content), save=False)
                self.stdout.write(self.style.SUCCESS(f'    Downloaded event image'))
            if thumbnail_content:
                event.thumbnail.save(f'{event_slug}_thumb.jpg', ContentFile(thumbnail_content), save=False)

            event.save()
            events_created += 1
            self.stdout.write(self.style.SUCCESS(f'  Created event: {event_data["title"]}'))

            # Create markets for this event
            for market_data in event_data['markets']:
                market = Market.objects.create(
                    event=event,
                    title=market_data['title'],
                    slug=market_data['slug'],
                    description=f"Trade on: {market_data['title']}",
                    status=Market.Status.ACTIVE,
                    last_yes_price=50,  # 50% probability
                    last_no_price=50,
                    amm_enabled=True,
                )
                markets_created += 1
                self.stdout.write(f'    Created market: {market_data["title"][:50]}...')

                # Create AMM pool for instant trading
                AMMPool.objects.create(
                    market=market,
                    liquidity_b=Decimal('100.00'),
                    yes_shares=Decimal('0.0000'),
                    no_shares=Decimal('0.0000'),
                    pool_balance=Decimal('0.00'),
                    fee_percentage=Decimal('0.0100'),  # 1% fee
                )

        self.stdout.write('\n' + '='*60)
        self.stdout.write(self.style.SUCCESS(f'Done! Created {events_created} events and {markets_created} markets.'))
        self.stdout.write('='*60 + '\n')
