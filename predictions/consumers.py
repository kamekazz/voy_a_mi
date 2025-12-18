"""
WebSocket consumers for real-time market updates.

Uses Django Channels to broadcast price changes, trades, and orderbook
updates to all users viewing a specific market.
"""

import json
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async


class MarketConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer for real-time market updates.

    Each connected client joins a group named 'market_<market_id>'.
    When trades execute, the matching engine broadcasts updates
    to all clients in that market's group.
    """

    async def connect(self):
        """
        Called when a WebSocket connection is opened.
        Validates market exists and joins the market's channel group.
        """
        self.market_id = self.scope['url_route']['kwargs']['market_id']
        self.room_group_name = f'market_{self.market_id}'

        # Validate market exists
        market_exists = await self.check_market_exists(self.market_id)
        if not market_exists:
            await self.close()
            return

        # Join market group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

        # Send current market state on connect
        market_data = await self.get_market_state(self.market_id)
        await self.send_json({
            'type': 'initial_state',
            'data': market_data
        })

    async def disconnect(self, close_code):
        """
        Called when the WebSocket connection is closed.
        Leaves the market's channel group.
        """
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive_json(self, content):
        """
        Called when a message is received from the WebSocket client.
        Currently only handles ping/pong for connection health.
        """
        message_type = content.get('type')

        if message_type == 'ping':
            await self.send_json({'type': 'pong'})

    # --- Handlers for messages from the channel layer ---

    async def market_update(self, event):
        """
        Handler for 'market_update' messages from the channel layer.
        Sent when prices change after a trade.
        """
        await self.send_json({
            'type': 'market_update',
            'data': event['data']
        })

    async def trade_executed(self, event):
        """
        Handler for 'trade_executed' messages from the channel layer.
        Sent when a new trade is executed.
        """
        await self.send_json({
            'type': 'trade_executed',
            'data': event['data']
        })

    async def orderbook_update(self, event):
        """
        Handler for 'orderbook_update' messages from the channel layer.
        Sent when the orderbook changes (order placed/cancelled).
        """
        await self.send_json({
            'type': 'orderbook_update',
            'data': event['data']
        })

    # --- Database access methods ---

    @database_sync_to_async
    def check_market_exists(self, market_id):
        """Check if a market with the given ID exists."""
        from .models import Market
        return Market.objects.filter(pk=market_id).exists()

    @database_sync_to_async
    def get_market_state(self, market_id):
        """Get current market state for initial WebSocket connection."""
        from .models import Market
        from .matching_engine import get_orderbook

        try:
            market = Market.objects.select_related('event').get(pk=market_id)
            orderbook = get_orderbook(market, depth=10)

            return {
                'market_id': market.pk,
                'last_yes_price': market.last_yes_price,
                'last_no_price': market.last_no_price,
                'best_yes_bid': market.best_yes_bid,
                'best_yes_ask': market.best_yes_ask,
                'best_no_bid': market.best_no_bid,
                'best_no_ask': market.best_no_ask,
                'total_volume': market.total_volume,
                'is_trading_active': market.is_trading_active,
                'orderbook': orderbook,
            }
        except Market.DoesNotExist:
            return None
