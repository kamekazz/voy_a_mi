"""
Broadcast helpers - NO-OP stubs.

This project uses REST API with polling instead of WebSockets.
These functions are kept as no-ops to prevent import errors in the matching engine.
"""


def broadcast_market_update(market):
    """No-op: Market updates are fetched via polling."""
    pass


def broadcast_trade_executed(trade):
    """No-op: Trades are fetched via polling."""
    pass


def broadcast_orderbook_update(market, orderbook=None):
    """No-op: Orderbook is fetched via polling."""
    pass
