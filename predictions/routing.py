"""
WebSocket URL routing for the predictions app.
"""

from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/market/(?P<market_id>\d+)/$', consumers.MarketConsumer.as_asgi()),
]
