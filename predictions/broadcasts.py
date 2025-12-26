"""
Broadcast helpers for sending real-time updates via Django Channels.

These functions are designed to be called from synchronous code
(like the matching engine) and handle the async channel layer operations.
"""

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def broadcast_market_update(market):
    """
    Broadcast market price updates to all connected clients.

    Call this after trades update market prices.

    Args:
        market: Market model instance with updated prices
    """
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return  # No channel layer configured

    group_name = f'market_{market.pk}'

    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            'type': 'market_update',
            'data': {
                'market_id': market.pk,
                'last_yes_price': market.last_yes_price,
                'last_no_price': market.last_no_price,
                'best_yes_bid': market.best_yes_bid,
                'best_yes_ask': market.best_yes_ask,
                'best_no_bid': market.best_no_bid,
                'best_no_ask': market.best_no_ask,
                'total_volume': market.total_volume,
            }
        }
    )


def broadcast_trade_executed(trade):
    """
    Broadcast a trade execution to all connected clients.

    Call this after a trade is created.

    Args:
        trade: Trade model instance
    """
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    group_name = f'market_{trade.market_id}'

    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            'type': 'trade_executed',
            'data': {
                'trade_id': trade.pk,
                'market_id': trade.market_id,
                'contract_type': trade.contract_type,
                'price': trade.price,
                'quantity': trade.quantity,
                'executed_at': trade.executed_at.isoformat(),
            }
        }
    )


def broadcast_orderbook_update(market, orderbook=None):
    """
    Broadcast orderbook changes to all connected clients.

    Call this after orders are placed, filled, or cancelled.

    Args:
        market: Market model instance
        orderbook: Optional pre-computed orderbook dict. If None, will be computed.
    """
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    if orderbook is None:
        from .engine.matching import get_orderbook
        orderbook = get_orderbook(market, depth=10)

    group_name = f'market_{market.pk}'

    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            'type': 'orderbook_update',
            'data': {
                'market_id': market.pk,
                'orderbook': orderbook,
                'best_yes_bid': market.best_yes_bid,
                'best_yes_ask': market.best_yes_ask,
                'best_no_bid': market.best_no_bid,
                'best_no_ask': market.best_no_ask,
            }
        }
    )
