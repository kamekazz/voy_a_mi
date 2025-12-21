from django.urls import path
from . import views

app_name = 'predictions'

urlpatterns = [
    # Public pages
    path('', views.index, name='index'),
    path('events/', views.event_list, name='event_list'),
    path('events/<slug:slug>/', views.event_detail, name='event_detail'),
    path('markets/<int:pk>/', views.market_detail, name='market_detail'),

    # Trading actions (require login)
    path('markets/<int:pk>/order/', views.place_order, name='place_order'),
    path('markets/<int:pk>/quick-bet/', views.place_quick_bet, name='place_quick_bet'),
    path('orders/<int:pk>/cancel/', views.cancel_order, name='cancel_order'),

    # Mint/Redeem complete sets (require login)
    path('markets/<int:pk>/mint/', views.mint_complete_set_view, name='mint_complete_set'),
    path('markets/<int:pk>/redeem/', views.redeem_complete_set_view, name='redeem_complete_set'),

    # User pages (require login)
    path('portfolio/', views.portfolio, name='portfolio'),
    path('orders/', views.order_history, name='order_history'),
    path('trades/', views.trade_history, name='trade_history'),
    path('transactions/', views.transactions, name='transactions'),

    # API endpoints
    path('api/markets/<int:pk>/orderbook/', views.api_orderbook, name='api_orderbook'),
    path('api/markets/<int:pk>/trades/', views.api_recent_trades, name='api_recent_trades'),
    path('api/markets/<int:pk>/position/', views.api_user_position, name='api_user_position'),
    path('api/markets/<int:pk>/price-history/', views.api_price_history, name='api_price_history'),
]
